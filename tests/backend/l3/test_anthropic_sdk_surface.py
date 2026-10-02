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

OPS-89 변경 — 프롬프트 캐싱의 *위치*가 최상위 `cache_control`에서 **system 블록 끝 브레이크포인트**로
옮겨졌다. 그래서 (1) 최상위 인자 집합에서 `cache_control`이 빠졌고(아래 FIRST_VERSION·TUNING_KEYS에서
제외, 되돌리면 RED인 음성 대조군 추가) (2) 새로 싣는 것은 `system=[{"type":"text","text":…,
"cache_control":{"type":"ephemeral"}}]`라서, 이 파일 뒤쪽 `TestSystemBlockSurface`가 그 표면을 *실물 SDK*에
대고 확인한다 — ⓐ `create(system=)`이 텍스트 블록 리스트를 받는 시그니처 ⓑ `TextBlockParam`에
`cache_control` 필드 실재 ⓒ 우리가 실제로 싣는 블록의 모든 키가 그 TypedDict에 있음 ⓓ 하한 대조
(SYSTEM_BLOCK_FIRST_VERSION: 2026-10-02 실물 설치 실측 — 0.40.0에는 없고 0.41.0부터 있음) ⓔ 실물
`AsyncAnthropic`을 네트워크 없는 `httpx.MockTransport`에 물려 *실제 직렬화된 요청 본문*에 최상위
`cache_control`이 없고 system 블록에 있음을 확인(라이브 호출 아님 — ARCH-66).
"""

from __future__ import annotations

import collections.abc
import importlib.metadata
import inspect
import json
import re
import tomllib
import typing
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx
import pytest
from anthropic import AsyncAnthropic
from anthropic.resources.messages import AsyncMessages
from anthropic.types import CacheControlEphemeralParam, TextBlockParam

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
    # 최상위 `cache_control`(0.83.0)은 OPS-89로 더 이상 싣지 않아 표에서 뺐다 — 캐싱은 system 블록 안에 있다.
    # 되돌리면 test_top_level_cache_control_is_not_sent·test_every_sent_key_has_a_recorded_first_version이 RED.
}

# system 텍스트 블록(`TextBlockParam`)의 `cache_control` 필드가 처음 존재한 anthropic 버전.
# 2026-10-02 실물 설치 실측(`pip install --no-deps --target`별 버전 → `typing.get_type_hints(TextBlockParam)`):
# 0.40.0 없음 · 0.41.0~0.45.0(0.43.1 포함)·0.50.0~0.80.0(5 간격 표본)·0.83.0·0.125.0 있음.
# 표본 구간에서 한 번 생긴 필드가 뒤 버전에서 사라진 경우는 없었다(전수는 아님).
SYSTEM_BLOCK_FIRST_VERSION: dict[str, Version] = {"cache_control": (0, 41, 0)}

# 이 태스크가 지목한 두 키 — 유도 결과에 이 둘이 없으면 노브를 못 켠 것이라 검사가 공허하다(양성 대조군).
TUNING_KEYS = frozenset({"output_config", "thinking"})

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

    prompt_caching도 켠다 — OPS-89 이후 그 효과는 최상위 키가 아니라 system 블록 안에 나타나므로
    합집합에 `cache_control`이 *없어야* 한다(음성 대조군은 아래 테스트).

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
        """하한 0.76.0은 output_config(0.77.0)를 허용하지 못한다 — 옛 하한 0.40.0은 둘 다 지목된다."""
        keys = set(FIRST_VERSION)
        assert floor_violations((0, 76, 0), keys, FIRST_VERSION) == {"output_config": (0, 77, 0)}
        assert floor_violations((0, 40, 0), keys, FIRST_VERSION) == {
            "output_config": (0, 77, 0),
            "thinking": (0, 47, 0),
        }

    def test_floor_at_or_above_every_first_version_is_clean(self) -> None:
        assert floor_violations((0, 77, 0), set(FIRST_VERSION), FIRST_VERSION) == {}
        assert floor_violations((0, 90, 0), set(FIRST_VERSION), FIRST_VERSION) == {}

    def test_unrecorded_key_is_named(self) -> None:
        """코드가 새 키를 싣기 시작했는데 표에 없으면 판정 불능이라 이름으로 지목한다."""
        assert unrecorded_keys(["model", "service_tier"], FIRST_VERSION) == ["service_tier"]
        assert unrecorded_keys(["model", "thinking"], FIRST_VERSION) == []
        # OPS-89: 최상위 cache_control은 더 이상 표에 없다 — 코드가 다시 싣기 시작하면 지목된다.
        assert unrecorded_keys(["model", "cache_control"], FIRST_VERSION) == ["cache_control"]

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
        """양성 대조군 — 유도가 두 튜닝 키를 실제로 잡았다(노브가 안 켜졌으면 아래 검사가 공허해진다)."""
        sent = await sent_top_level_keys()
        not_sent = sorted(TUNING_KEYS - sent)
        assert not not_sent, f"노브를 켰는데 최상위 인자로 안 실린 키: {not_sent}"
        assert {"model", "max_tokens", "system", "messages", "temperature", "top_p"} <= sent

    async def test_top_level_cache_control_is_not_sent(self) -> None:
        """음성 대조군(OPS-89) — 캐싱을 켜도 최상위 `cache_control`(자동 캐싱)은 싣지 않는다.

        자동 캐싱은 마지막 캐시 가능 블록(가변 user 프롬프트) 뒤에 브레이크포인트를 놓아 공유 system
        프리픽스가 적중하지 못한다. 이 키가 다시 나타나면 그 배치로 되돌아간 것이다.
        """
        assert "cache_control" not in await sent_top_level_keys()

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
        """하한 버전에도 우리가 싣는 모든 인자가 존재한다 — 옛 하한 0.40.0이면 두 키가 지목돼 RED였다."""
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


# ──────────────────────────────────────────────────────────────────────────
# OPS-89 · system 블록 표면 — `system=[{"type":"text","text":…,"cache_control":…}]`가 실물 SDK에 있는가
# ──────────────────────────────────────────────────────────────────────────
async def sent_system_blocks() -> list[dict[str, Any]]:
    """캐싱 ON 호출이 `messages.create(system=)`에 실제로 싣는 블록 리스트(코드 경로에서 유도)."""
    client = _CaptureClient()
    provider = AnthropicProvider(
        client=client,  # type: ignore[arg-type]
        settings=Settings(anthropic_prompt_caching=True),
    )
    await provider.generate("p", "공유 system", _cloud_decision())
    system = client.messages.calls[0]["system"]
    assert isinstance(system, list), f"캐싱 ON인데 system이 블록 리스트가 아니다: {system!r}"
    return [dict(block) for block in system]


def _typed_dict_keys(td: Any) -> set[str]:
    """TypedDict의 선언 키(상속 포함) — 실물 SDK의 타입 표면."""
    return set(typing.get_type_hints(td, include_extras=True))


class TestSystemBlockSurface:
    def test_create_system_accepts_a_list_of_text_blocks(self) -> None:
        """실물 `AsyncMessages.create`의 `system` 시그니처가 `Iterable[TextBlockParam]`을 받는다."""
        system_hint = typing.get_type_hints(AsyncMessages.create)["system"]
        members = typing.get_args(system_hint)
        iterable_args = [
            typing.get_args(m) for m in members if typing.get_origin(m) is collections.abc.Iterable
        ]
        assert str in members, f"system이 문자열을 못 받는다(현행 OFF 경로 깨짐): {system_hint}"
        assert (TextBlockParam,) in iterable_args, (
            f"설치된 SDK의 create(system=)이 Iterable[TextBlockParam]을 받지 않는다: {system_hint}. "
            "OPS-89의 system 블록 브레이크포인트가 전송될 수 없다 — pin 하한·코드를 재검토하라."
        )

    def test_text_block_param_has_cache_control_field(self) -> None:
        """실물 `TextBlockParam`에 text·type·cache_control 필드가 있다."""
        keys = _typed_dict_keys(TextBlockParam)
        assert {"text", "type", "cache_control"} <= keys, sorted(keys)
        assert "type" in _typed_dict_keys(CacheControlEphemeralParam)

    async def test_every_key_we_send_in_system_block_exists_in_the_sdk_types(self) -> None:
        """우리가 실제로 싣는 system 블록·cache_control의 모든 키가 실물 SDK TypedDict에 있다."""
        blocks = await sent_system_blocks()
        assert blocks, "system 블록이 비었다 — 검사가 공허하다"
        block_keys = _typed_dict_keys(TextBlockParam)
        cc_keys = _typed_dict_keys(CacheControlEphemeralParam)
        required = set(TextBlockParam.__required_keys__)
        for block in blocks:
            unknown = set(block) - block_keys
            assert not unknown, f"SDK에 없는 system 블록 키: {unknown}"
            assert required <= set(block), f"필수 키 누락: {required - set(block)}"
            unknown_cc = set(block["cache_control"]) - cc_keys
            assert not unknown_cc, f"SDK에 없는 cache_control 키: {unknown_cc}"

    async def test_every_system_block_key_has_a_recorded_first_version(self) -> None:
        """블록의 선택 키(cache_control)는 최초 실재 버전이 기록돼 있어야 하한 판정이 선다."""
        optional = {k for b in await sent_system_blocks() for k in b} - {"type", "text"}
        assert optional == set(SYSTEM_BLOCK_FIRST_VERSION), (
            f"system 블록이 싣는 선택 키 {sorted(optional)}와 기록된 "
            f"{sorted(SYSTEM_BLOCK_FIRST_VERSION)}가 다르다 — 새 키는 PyPI 구버전을 실물 설치해 "
            "TypedDict로 최초 버전을 재서 표에 넣어라."
        )

    async def test_declared_floor_covers_system_block_keys(self) -> None:
        """pyproject 하한이 system 블록 `cache_control`의 최초 실재 버전(0.41.0) 이상이다."""
        floor = parse_floor(declared_requirement())
        sent = {k for b in await sent_system_blocks() for k in b}
        violations = floor_violations(floor, sent, SYSTEM_BLOCK_FIRST_VERSION)
        assert (
            not violations
        ), f"하한 {_fmt(floor)}이 system 블록 키의 최초 버전보다 낮다: {violations}"

    async def test_real_sdk_serializes_breakpoint_on_system_block_only(self) -> None:
        """실물 `AsyncAnthropic`이 직렬화한 *요청 본문*에서 브레이크포인트가 system 블록에만 있다.

        네트워크 없음 — `httpx.MockTransport`가 요청을 캡처하고 최소 유효 응답을 돌려준다(라이브 호출
        아님·ARCH-66 준수). 시임(가짜 create)이 아니라 SDK의 실제 직렬화 경로를 통과한다는 점이 요지다.
        응답 usage의 캐시 필드가 `_extract_usage`까지 흘러 `Usage`로 올라오는지도 함께 본다.
        """
        captured: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-4-6",
                    "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": 5,
                        "output_tokens": 2,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 123,
                    },
                },
            )

        real_client = AsyncAnthropic(
            api_key="test-key-not-a-secret",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            max_retries=0,
        )
        provider = AnthropicProvider(
            client=real_client,  # type: ignore[arg-type]
            settings=Settings(anthropic_prompt_caching=True),
        )

        out = await provider.generate("가변 user 꼬리", "공유 system 프리픽스", _cloud_decision())

        assert len(captured) == 1
        body = captured[0]
        assert (
            "cache_control" not in body
        ), "최상위 cache_control이 직렬화됐다 — 자동 캐싱 배치로 회귀"
        assert body["system"] == [
            {
                "type": "text",
                "text": "공유 system 프리픽스",
                "cache_control": {"type": "ephemeral"},
            }
        ]
        assert body["messages"] == [{"role": "user", "content": "가변 user 꼬리"}]
        assert out.usage is not None
        assert out.usage.cache_read_input_tokens == 123
