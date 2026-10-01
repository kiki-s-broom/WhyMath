"""anthropic SDK 표면 계약 — 우리가 messages.create에 싣는 최상위 인자가 *실물* SDK에 있는가 (OPS-87).

왜 이 파일이 있는가
-------------------
`test_anthropic_provider.py`의 가짜 클라이언트는 `create(..., **kwargs)`라서 어떤 키든 받는다. 그래서
"우리가 싣는 인자가 실제 SDK에 있는가"는 시임 테스트로는 영원히 증명되지 않는다(CLAUDE.md
'외부 SDK 표면을 시임 테스트만으로 정합 선언 금지'). 실제 `AsyncMessages.create`에는 `**kwargs`가 없어,
없는 인자를 싣는 순간 `TypeError`로 호출이 즉사한다. 조용히 무시되는 실패는 아니지만, 저작 배치는 호출
실패를 `generation_failed`로 집계해 회차가 정상 종료하므로 사람에게는 "측정 0건"으로만 보인다.

이 파일이 고정하는 것 — 세 층
-----------------------------
 ① 우리가 *실제로* 싣는 최상위 인자 집합을 코드 경로에서 유도한다. 손으로 쓴 목록은 코드가 바뀌면
    조용히 낡으므로, 가짜 클라이언트로 모든 선택 노브(effort·thinking·prompt_caching·temperature·
    top_p)를 켠 호출을 캡처한다. 코드가 새 키를 싣기 시작하면 아래 FIRST_VERSION 표에 그 키가 없어서
    RED가 난다(최초 실재 버전을 실측해 표에 넣게 강제한다).
 ② 그 집합 전부가 설치된 실물 SDK의 `AsyncMessages.create` 시그니처에 있다 — 없으면 키 이름을 대며 RED.
 ③ pyproject의 anthropic 하한이 각 키의 최초 실재 버전 이상이다. ②는 CI가 허용 구간의 *최신* SDK를
    설치하므로 하한 쪽의 구멍을 보지 못한다(하한이 0.40.0이던 동안 ②는 항상 초록이었다). 그래서 하한은
    별도로 실측 표와 대조한다.

FIRST_VERSION 표의 출처
-----------------------
2026-10-01 실물 설치 실측 — PyPI 0.40.0~0.90.0의 67개 버전을 각각 `pip install --no-deps --target`으로
따로 설치하고 `inspect.signature(AsyncMessages.create)`를 읽었다(시임·가짜 클라이언트 아님). 67개 버전
전건에서 `**kwargs`(VAR_KEYWORD) 없음·동기/비동기 시그니처 동일·한 번 생긴 인자가 뒤 버전에서 사라지는
경우 없음. 최초 실재 버전: thinking 0.47.0 · output_config 0.77.0 · cache_control 0.83.0, 나머지 6종은
측정 구간 전체(0.40.0 이전은 미측정 — 우리 하한이 0.40.0 밑으로 내려갈 일은 없다).
설치본(0.125.0)은 ②가 매 실행마다 직접 확인한다.
"""

from __future__ import annotations

import importlib.metadata
import inspect
import re
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from anthropic.resources.messages import AsyncMessages

from whymath_backend.config import Settings
from whymath_backend.l3.models import CostTier, RoutingDecision
from whymath_backend.l3.providers.anthropic import AnthropicProvider

Version = tuple[int, int, int]

# 각 최상위 인자가 messages.create 시그니처에 *처음 존재한* anthropic 버전(모듈 docstring의 실측).
FIRST_VERSION: dict[str, Version] = {
    "model": (0, 40, 0),
    "max_tokens": (0, 40, 0),
    "system": (0, 40, 0),
    "messages": (0, 40, 0),
    "temperature": (0, 40, 0),
    "top_p": (0, 40, 0),
    "thinking": (0, 47, 0),
    "output_config": (0, 77, 0),
    "cache_control": (0, 83, 0),
}

# 이 태스크가 지목한 세 키 — 유도 결과에 이 셋이 없으면 노브를 못 켠 것이라 검사가 공허하다(양성 대조군).
TUNING_KEYS = frozenset({"cache_control", "output_config", "thinking"})

_PYPROJECT = Path(__file__).resolve().parents[3] / "src" / "backend" / "pyproject.toml"


# ── 판정 함수(순수) — 아래 TestJudgementFunctions가 주입한 결함에서 키 이름을 대는지 직접 고정한다 ──
def missing_keys(signature_params: Iterable[str], keys: Iterable[str]) -> list[str]:
    """시그니처에 없는 키 이름(정렬)."""
    present = set(signature_params)
    return sorted(k for k in keys if k not in present)


def unrecorded_keys(keys: Iterable[str], table: dict[str, Version]) -> list[str]:
    """최초 실재 버전이 표에 없는 키 이름(정렬) — 하한 판정이 이 표에 기대므로 기록 없는 키는 판정 불능이다."""
    return sorted(k for k in keys if k not in table)


def floor_violations(
    floor: Version, keys: Iterable[str], table: dict[str, Version]
) -> dict[str, Version]:
    """하한이 최초 실재 버전보다 낮은 키 → 그 키가 처음 생긴 버전."""
    return {k: table[k] for k in sorted(keys) if k in table and table[k] > floor}


def parse_floor(requirement: str) -> Version:
    """`anthropic>=0.83.0,<1` 같은 요구 문자열에서 하한(>=) 버전을 읽는다. 하한이 없으면 실패한다."""
    match = re.search(r">=\s*(\d+)\.(\d+)\.(\d+)", requirement)
    reason = f"anthropic pin에 하한(>=X.Y.Z)이 없다 — 구버전 전부 허용: {requirement!r}"
    assert match is not None, reason
    major, minor, patch = (int(g) for g in match.groups())
    return (major, minor, patch)


def declared_requirement() -> str:
    """pyproject.toml `[project].dependencies`의 anthropic 요구 문자열."""
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    matches = [d for d in data["project"]["dependencies"] if re.match(r"anthropic\b", d)]
    assert len(matches) == 1, f"pyproject에 anthropic 요구가 정확히 1건이어야 한다: {matches}"
    return str(matches[0])


def _fmt(version: Version) -> str:
    return ".".join(str(part) for part in version)


# ── 코드 경로에서 "우리가 싣는 인자" 유도 ─────────────────────────────────────
class _CaptureMessages:
    """`**kwargs`를 그대로 받아 이름만 기록한다 — 시임이라 어떤 키든 받는다(그래서 표면 검증은 별도다)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return {"content": [{"type": "text", "text": "ok"}]}


class _CaptureClient:
    def __init__(self) -> None:
        self.messages = _CaptureMessages()


def _cloud_decision() -> RoutingDecision:
    return RoutingDecision(
        cost_tier=CostTier.CLOUD_MID,
        local_family=None,
        local_model=None,
        mode="sync",
        reason="surface-contract",
        est_latency_ms=3000,
        est_cost_krw=10.0,
    )


async def sent_top_level_keys() -> set[str]:
    """모든 선택 노브를 켠 호출들이 `messages.create`에 실제로 싣는 최상위 인자 이름의 합집합.

    temperature와 top_p는 API가 동시 지정을 400으로 거부해(provider가 사전 차단) 두 호출로 나눈다.
    """
    settings = Settings(
        anthropic_effort="high",
        anthropic_thinking=True,
        anthropic_prompt_caching=True,
    )
    keys: set[str] = set()
    for sampling in ({"temperature": 0.9}, {"top_p": 0.9}):
        client = _CaptureClient()
        provider = AnthropicProvider(client=client, settings=settings)  # type: ignore[arg-type]
        await provider.generate("p", "s", _cloud_decision(), **sampling)
        keys |= set(client.messages.calls[0])
    return keys


def _create_parameters() -> dict[str, inspect.Parameter]:
    return dict(inspect.signature(AsyncMessages.create).parameters)


# ──────────────────────────────────────────────────────────────────────────
# 판정 함수 자체 — 결함을 주입하면 키 이름을 대며 실패한다(변별력의 직접 증거)
# ──────────────────────────────────────────────────────────────────────────
class TestJudgementFunctions:
    def test_missing_keys_names_an_absent_key(self) -> None:
        """시그니처에 없는 키는 이름으로 지목된다 — 존재하지 않는 키를 검사 목록에 주입한 경우."""
        params = ["model", "max_tokens", "system", "messages", "cache_control"]
        assert missing_keys(params, ["cache_control", "no_such_key_zz", "also_missing"]) == [
            "also_missing",
            "no_such_key_zz",
        ]

    def test_missing_keys_empty_when_everything_exists(self) -> None:
        assert missing_keys(["a", "b", "c"], ["a", "c"]) == []

    def test_floor_below_first_version_names_the_key(self) -> None:
        """하한 0.82.0은 cache_control(0.83.0)을 허용하지 못한다 — 옛 하한 0.40.0은 셋 다 지목된다."""
        keys = set(FIRST_VERSION)
        assert floor_violations((0, 82, 0), keys, FIRST_VERSION) == {"cache_control": (0, 83, 0)}
        assert floor_violations((0, 40, 0), keys, FIRST_VERSION) == {
            "cache_control": (0, 83, 0),
            "output_config": (0, 77, 0),
            "thinking": (0, 47, 0),
        }

    def test_floor_at_or_above_every_first_version_is_clean(self) -> None:
        assert floor_violations((0, 83, 0), set(FIRST_VERSION), FIRST_VERSION) == {}
        assert floor_violations((0, 90, 0), set(FIRST_VERSION), FIRST_VERSION) == {}

    def test_unrecorded_key_is_named(self) -> None:
        """코드가 새 키를 싣기 시작했는데 표에 없으면 판정 불능이라 이름으로 지목한다."""
        assert unrecorded_keys(["model", "service_tier"], FIRST_VERSION) == ["service_tier"]
        assert unrecorded_keys(["model", "cache_control"], FIRST_VERSION) == []

    def test_parse_floor_reads_the_lower_bound(self) -> None:
        assert parse_floor("anthropic>=0.83.0,<1") == (0, 83, 0)
        assert parse_floor("anthropic >= 0.40.0") == (0, 40, 0)

    def test_parse_floor_rejects_a_requirement_without_lower_bound(self) -> None:
        """무하한은 모든 구버전을 허용한다 — 판정이 조용히 통과하지 못하게 실패시킨다."""
        with pytest.raises(AssertionError, match="하한"):
            parse_floor("anthropic<1")


# ──────────────────────────────────────────────────────────────────────────
# ① 유도 · ② 실물 SDK 시그니처
# ──────────────────────────────────────────────────────────────────────────
class TestSentKeysAgainstRealSdk:
    async def test_derivation_exercises_the_tuning_knobs(self) -> None:
        """양성 대조군 — 유도가 세 튜닝 키를 실제로 잡았다(노브가 안 켜졌으면 아래 검사가 공허해진다)."""
        sent = await sent_top_level_keys()
        not_sent = sorted(TUNING_KEYS - sent)
        assert not not_sent, f"노브를 켰는데 최상위 인자로 안 실린 키: {not_sent}"
        assert {"model", "max_tokens", "system", "messages", "temperature", "top_p"} <= sent

    async def test_every_sent_key_has_a_recorded_first_version(self) -> None:
        """코드가 싣는 모든 키의 최초 실재 버전이 표에 있다 — 새 키는 실측해서 표에 넣어야 하한 판정이 선다."""
        sent = await sent_top_level_keys()
        unrecorded = unrecorded_keys(sent, FIRST_VERSION)
        assert not unrecorded, (
            f"코드가 싣는 인자 {unrecorded}의 최초 실재 버전이 FIRST_VERSION 표에 없다 — "
            "PyPI 구버전을 실물 설치해 inspect.signature(AsyncMessages.create)로 최초 버전을 재고 "
            "표에 추가하라(하한 판정이 이 표에 기대고, 안 재면 하한이 새 키를 보장하는지 알 수 없다)."
        )

    async def test_installed_sdk_has_every_key_we_send(self) -> None:
        """설치된 실물 anthropic의 `AsyncMessages.create`에 우리가 싣는 모든 최상위 인자가 있다."""
        sent = await sent_top_level_keys()
        missing = missing_keys(_create_parameters(), sent)
        version = importlib.metadata.version("anthropic")
        assert not missing, (
            f"설치된 anthropic {version}의 AsyncMessages.create에 없는 최상위 인자: {missing}. "
            "이 SDK의 create에는 **kwargs가 없어 호출이 TypeError로 죽고, 저작 배치는 그것을 "
            "generation_failed로 집계해 회차가 정상 종료한다(무증상). pyproject의 anthropic 하한을 "
            "그 인자가 있는 버전 이상으로 올리거나 그 인자를 싣는 코드를 되돌려라."
        )

    def test_real_create_has_no_var_keyword(self) -> None:
        """전제 고정 — create에 **kwargs가 없어야 '없는 인자 = TypeError(즉사)'가 성립한다.

        이 전제가 바뀌면(미래 버전이 **kwargs를 받으면) 없는 인자가 *조용히 무시*될 수 있어 실패 양태가
        더 나빠진다. 그때는 이 파일의 ② 검사만으로는 부족하니 사람이 표면을 다시 봐야 한다.
        """
        var_keyword = [
            name
            for name, p in _create_parameters().items()
            if p.kind is inspect.Parameter.VAR_KEYWORD
        ]
        assert not var_keyword, (
            f"AsyncMessages.create가 **{var_keyword[0]}를 받는다 — 없는 인자가 TypeError가 아니라 "
            "조용히 무시될 수 있다. 표면 검증 전제가 바뀌었으니 OPS-87의 실패 양태 판정을 재검토하라."
        )


# ──────────────────────────────────────────────────────────────────────────
# ③ pyproject 하한
# ──────────────────────────────────────────────────────────────────────────
class TestDeclaredFloor:
    async def test_declared_floor_covers_every_key_we_send(self) -> None:
        """하한 버전에도 우리가 싣는 모든 인자가 존재한다 — 옛 하한 0.40.0이면 세 키가 지목돼 RED였다."""
        sent = await sent_top_level_keys()
        requirement = declared_requirement()
        floor = parse_floor(requirement)
        violations = floor_violations(floor, sent, FIRST_VERSION)
        needed = max(violations.values()) if violations else floor
        assert not violations, (
            f"pyproject의 `{requirement}` 하한 {_fmt(floor)}이(가) 우리가 싣는 인자의 최초 실재 버전보다 "
            f"낮다: { {k: _fmt(v) for k, v in violations.items()} }. 그 미만 버전은 설치가 허용되지만 "
            f"해당 인자가 없어 호출이 TypeError로 죽는다 — 하한을 {_fmt(needed)} 이상으로 올려라."
        )

    def test_declared_requirement_keeps_an_upper_bound(self) -> None:
        """OPS-87 범위 밖 동결 확인 — 이 태스크는 하한만 바꾼다(상한 <1은 그대로)."""
        assert "<1" in declared_requirement().replace(" ", "")
