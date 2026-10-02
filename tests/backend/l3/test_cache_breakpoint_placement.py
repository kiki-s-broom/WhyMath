"""프롬프트 캐시 브레이크포인트 위치(OPS-89) — 공유 system 프리픽스가 *적중하는 자리*에 있는가.

**이 파일이 라이브 증거가 아닌 이유 (먼저 읽을 것)**

ARCH-66(2026-09-24~2026-12-31 Anthropic API 사용 중단)으로 라이브 호출이 막혀 있다. 여기의
"적중"은 전부 아래 `PrefixCacheSim`이 *모사한* 값이다 — **실측 `cache_read_input_tokens > 0`이 아니다.**
시뮬레이터가 맞는 것은 Anthropic 프롬프트 캐싱의 *문서화된 규칙*(렌더 순서 `tools → system →
messages`, 브레이크포인트까지의 프리픽스 바이트가 같으면 읽기, 최상위 `cache_control`은 마지막 캐시
가능 블록에 브레이크포인트)을 코드로 옮긴 것까지다. 그 규칙이 실제 API에서 그대로 성립하는지는 라이브
회차의 몫이고, 이 태스크에서는 **미수행**이다(미측정을 통과로 계상하지 않는다 — 태스크 notes·보고서에 명시).

**그러면 무엇을 증명하나**

시뮬레이터가 *문서화된 규칙*을 옳게 모사한다는 전제 하에, 호출 경로가 보내는 **요청 형태**가 그 규칙 아래서
적중하는 형태인지 — 즉 "브레이크포인트가 공유 프리픽스의 끝에 있는가, 가변 꼬리 뒤에 있는가"를 경로별로
가른다. 세 경로를 *실제 코드*(`CrossVerifier._run_perspective`·`multi_solution.generate_candidates`·
`AnthropicProvider.generate`)로 구동하고, 종전 형태(system 문자열 + 최상위 `cache_control`)와 수정 형태
(system 블록 끝 명시 브레이크포인트)를 같은 시뮬레이터에 번갈아 물려 대조한다.

  - 종전(최상위 자동 캐싱): 연속 2회 호출에서 2회차 적중 0 · 쓰기 할증을 매번 낸다.
  - 수정(system 블록 끝): 2회차 적중 > 0 · 쓰기는 1회차뿐.

종전 형태는 이제 `AnthropicProvider`가 보내지 않으므로 `_LegacyTopLevelAdapter`가 수정 provider의 출력을
*종전 형태로 변환*해 재현한다(종전 코드는 `system=<문자열>, cache_control={"type":"ephemeral"}`를 보냈다).

변별력 대조군(시뮬레이터가 항상 0을 내거나 항상 적중을 내는 가짜가 아님을 보인다):
  - 종전 형태라도 *user 프롬프트가 완전히 같으면* 적중한다(2026-09-21 라이브 회차가 89.9%로 성공한 이유 —
    그 회차의 user가 사실상 상수였다). 즉 시뮬레이터는 "가변 꼬리"에서만 종전 형태를 0으로 만든다.
  - 수정 형태라도 system이 다르면 적중 0.
  - 최소 캐시 프리픽스 미만이면 두 형태 모두 조용히 무효(creation 0·read 0) — 위치 수정이 이를 구제하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

import pytest

from whymath_backend.config import Settings
from whymath_backend.l3.cross_verify import (
    PROBABILITY_PERSPECTIVES,
    CrossVerifier,
    ResidueSubject,
)
from whymath_backend.l3.interfaces import RecordingTraceSink
from whymath_backend.l3.models import (
    CostTier,
    GenerationResult,
    RoutingDecision,
)
from whymath_backend.l3.multi_solution import (
    _SYSTEM_PROMPT as MULTI_SOLUTION_SYSTEM,
)
from whymath_backend.l3.multi_solution import (
    MultiSolutionReport,
    SeedProblem,
    generate_candidates,
)
from whymath_backend.l3.providers.anthropic import AnthropicProvider

# ──────────────────────────────────────────────────────────────────────────
# 프리픽스 캐시 모사기 — 시뮬레이션(라이브 아님)
# ──────────────────────────────────────────────────────────────────────────
# 토큰 수 *대용치* — 오프라인에는 정확한 토크나이저가 없다. 위치 판정(적중/비적중)에는 크기의 절대값이
# 아니라 "프리픽스가 같은가"만 쓰이고, 이 값은 usage 필드를 채우는 데와 최소 프리픽스 시험에만 쓰인다.
_CHARS_PER_TOKEN_PROXY = 4


def _tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN_PROXY)


@dataclass(frozen=True)
class _Segment:
    """렌더 순서상의 한 블록 — 텍스트와 '여기서 끝나는 브레이크포인트' 표시."""

    text: str
    marked: bool


def _segments(system: Any, messages: Sequence[Mapping[str, Any]]) -> list[_Segment]:
    """요청을 렌더 순서(tools → system → messages)의 블록 리스트로 편다. tools는 이 경로에 없다."""
    segs: list[_Segment] = []
    if isinstance(system, str):
        # 문자열 system은 API가 텍스트 블록 1개로 취급한다 — 표시 없음.
        if system:
            segs.append(_Segment(system, False))
    else:
        for block in system:
            segs.append(_Segment(block["text"], "cache_control" in block))
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            segs.append(_Segment(content, False))
        else:
            for block in content:
                segs.append(_Segment(block["text"], "cache_control" in block))
    return segs


class PrefixCacheSim:
    """`_AnthropicClient` 시임을 충족하는 프리픽스 캐시 모사 클라이언트(시뮬레이션 — 라이브 증거 아님).

    규칙(공식 문서의 서술을 옮긴 것 — 실제 API와의 일치는 라이브 미검증):
      1. 브레이크포인트 = 블록에 단 `cache_control` 표시의 끝, 그리고 요청 최상위 `cache_control`이
         있으면 *마지막 캐시 가능 블록*의 끝(자동 캐싱).
      2. 브레이크포인트까지의 프리픽스(모델 + 그 앞 모든 블록의 바이트)가 이전에 쓰인 적 있으면 그만큼
         `cache_read_input_tokens`, 아니면 `cache_creation_input_tokens`(쓰기)로 계상.
      3. 프리픽스가 `min_cache_tokens`(대용 토큰) 미만이면 읽기도 쓰기도 없다(조용한 무효).
    """

    def __init__(self, *, min_cache_tokens: int = 0) -> None:
        self.min_cache_tokens = min_cache_tokens
        self.requests: list[dict[str, Any]] = []
        self.results: list[dict[str, int]] = []
        self._store: set[str] = set()
        self.messages = self  # `client.messages.create` 시임

    def _key(self, model: str, segs: Sequence[_Segment]) -> str:
        payload = json.dumps([model, [s.text for s in segs]], ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: Any,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.requests.append(
            {"model": model, "system": system, "messages": messages, "kwargs": dict(kwargs)}
        )
        segs = _segments(system, messages)
        breakpoints = [i for i, s in enumerate(segs) if s.marked]
        if "cache_control" in kwargs and segs:  # 자동 캐싱 — 마지막 캐시 가능 블록
            breakpoints.append(len(segs) - 1)
        breakpoints = sorted(set(breakpoints))

        total = sum(_tokens(s.text) for s in segs)
        read = creation = 0
        if breakpoints:
            # 가장 긴 적중 프리픽스를 읽고, 마지막 브레이크포인트가 미적중이면 그 프리픽스를 쓴다.
            for bp in reversed(breakpoints):
                prefix = segs[: bp + 1]
                prefix_tokens = sum(_tokens(s.text) for s in prefix)
                if prefix_tokens < self.min_cache_tokens:
                    continue
                if self._key(model, prefix) in self._store:
                    read = prefix_tokens
                    break
            last = segs[: breakpoints[-1] + 1]
            last_tokens = sum(_tokens(s.text) for s in last)
            if last_tokens >= self.min_cache_tokens:
                creation = max(0, last_tokens - read)
                self._store.add(self._key(model, last))
        usage = {
            "input_tokens": total - read - creation,
            "output_tokens": 1,
            "cache_creation_input_tokens": creation,
            "cache_read_input_tokens": read,
        }
        self.results.append(usage)
        return {"content": [{"type": "text", "text": "{}"}], "usage": usage}

    async def list(self) -> Any:  # pragma: no cover - models 시임(미사용)
        return {"data": []}

    @property
    def models(self) -> PrefixCacheSim:
        return self


class _LegacyTopLevelAdapter:
    """수정 provider의 출력을 *종전 요청 형태*로 변환 — system 문자열 + 최상위 `cache_control`.

    종전 `AnthropicProvider.generate`는 캐싱 ON일 때 `system=<문자열>`과 최상위
    `cache_control={"type":"ephemeral"}`를 보냈다. 지금 코드는 그렇게 보내지 않으므로, 같은 호출 인자를
    그 형태로 되돌려 시뮬레이터에 넘긴다(종전 배치의 재현 — 이 파일 docstring 참조).
    """

    def __init__(self, inner: PrefixCacheSim) -> None:
        self._inner = inner
        self.messages = self

    @property
    def models(self) -> PrefixCacheSim:
        return self._inner

    async def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: Any,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        wants_cache = False
        if not isinstance(system, str):
            wants_cache = any("cache_control" in block for block in system)
            system = "".join(block["text"] for block in system)
        legacy_kwargs = dict(kwargs)
        if wants_cache:
            legacy_kwargs["cache_control"] = {"type": "ephemeral"}
        return await self._inner.create(
            model=model, max_tokens=max_tokens, system=system, messages=messages, **legacy_kwargs
        )


def _cloud_decision() -> RoutingDecision:
    return RoutingDecision(
        cost_tier=CostTier.CLOUD_MID,
        local_family=None,
        local_model=None,
        mode="sync",
        reason="ops89-sim",
        est_latency_ms=3000,
        est_cost_krw=10.0,
    )


class _CloudSeatProvider:
    """호출 경로(`CrossVerifier`·`multi_solution`)가 라우터로 LOCAL을 골라도 클라우드 좌석으로 돌린다.

    이 테스트의 관심은 라우팅이 아니라 **경로가 만드는 (system, user) 인자가 요청에서 어디에 놓이는가**다.
    `json_schema`(LOCAL 결정일 때만 실리는 인자)는 클라우드 좌석이 거부하므로 버린다 — 이 어댑터는
    테스트 전용이며 운영 경로를 바꾸지 않는다. 내부 provider가 돌려준 `GenerationResult.usage`는
    기록해 `_extract_usage`를 통과한 `cache_read_input_tokens`를 직접 볼 수 있게 한다.
    """

    def __init__(self, inner: AnthropicProvider) -> None:
        self._inner = inner
        self.usages: list[Any] = []

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
        temperature: float | None = None,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,
        top_p: float | None = None,
    ) -> GenerationResult:
        result = await self._inner.generate(
            prompt, system, _cloud_decision(), temperature=temperature, top_p=top_p
        )
        self.usages.append(result.usage)
        return result


Placement = Literal["legacy_top_level", "system_block"]
PATH_NAMES = ["generic_generate", "cross_verify_run_perspective", "multi_solution_generate"]


def _build(
    placement: Placement, *, min_cache_tokens: int = 0
) -> tuple[PrefixCacheSim, _CloudSeatProvider]:
    sim = PrefixCacheSim(min_cache_tokens=min_cache_tokens)
    client: Any = sim if placement == "system_block" else _LegacyTopLevelAdapter(sim)
    provider = AnthropicProvider(client=client, settings=Settings(anthropic_prompt_caching=True))
    return sim, _CloudSeatProvider(provider)


_SUBJECT = ResidueSubject(
    problem_id="wm-ops89",
    question_text="서로 구별되는 두 개의 주사위를 던질 때 눈의 합이 7일 확률은?",
    answer="1/6",
    answer_explanation="전체 36가지 중 6가지.",
    machine_model_ko="표본공간: 36가지.\n사건 A: 합이 7.\n확률 = 6/36.",
    machine_total=36,
    machine_favorable=6,
    authored_by="corpus:FULLY_GENERATED",
)


async def _drive(path: str, provider: _CloudSeatProvider) -> int:
    """경로를 실제 코드로 구동한다 — 같은 system·**서로 다른 user**의 연속 호출을 쌍으로 만든다.

    반환: 쌍의 개수(시뮬레이터에 쌓이는 요청은 쌍마다 2건, 순서대로).
    """
    if path == "generic_generate":
        await provider.generate(
            "문항 A의 가변 프롬프트", "공유 system 프리픽스 " * 20, _cloud_decision()
        )
        await provider.generate(
            "문항 B의 전혀 다른 프롬프트", "공유 system 프리픽스 " * 20, _cloud_decision()
        )
        return 1
    if path == "cross_verify_run_perspective":
        verifier = CrossVerifier(provider, trace=RecordingTraceSink())
        decision = _cloud_decision()
        for perspective in PROBABILITY_PERSPECTIVES:
            for n in (1, 2):
                subject = replace(
                    _SUBJECT,
                    problem_id=f"wm-ops89-{n}",
                    question_text=f"문항 {n}: " + _SUBJECT.question_text * n,
                )
                await verifier._run_perspective(perspective, subject, decision)
        return len(PROBABILITY_PERSPECTIVES)
    if path == "multi_solution_generate":
        seeds = [
            SeedProblem(
                problem_id=uuid.uuid4(),
                question_text=f"일차방정식 {k}*x = {6 * k} 을 푸시오. (문항 {k})",
                conditions=(f"{k}*x = {6 * k}",),
                answer_map={"x": "6"},
            )
            for k in (2, 3)
        ]
        await generate_candidates(
            seeds,
            provider,
            trace=RecordingTraceSink(),
            report=MultiSolutionReport(),
        )
        return 1
    raise AssertionError(path)


def _pairs(sim: PrefixCacheSim, n_pairs: int) -> list[tuple[dict[str, int], dict[str, int]]]:
    assert len(sim.results) == 2 * n_pairs, f"기대 요청 {2 * n_pairs}건, 실제 {len(sim.results)}건"
    return [(sim.results[2 * i], sim.results[2 * i + 1]) for i in range(n_pairs)]


# ──────────────────────────────────────────────────────────────────────────
# 시뮬레이터 자체 — 항상 0/항상 적중이 아님을 먼저 고정한다(변별력의 전제)
# ──────────────────────────────────────────────────────────────────────────
class TestSimulatorDiscriminates:
    async def test_identical_request_hits_on_second_call(self) -> None:
        """대조군 — 브레이크포인트 앞 프리픽스가 같으면 2회차는 읽는다."""
        sim = PrefixCacheSim()
        system = [{"type": "text", "text": "S" * 400, "cache_control": {"type": "ephemeral"}}]
        for _ in range(2):
            await sim.create(
                model="m", max_tokens=1, system=system, messages=[{"role": "user", "content": "q"}]
            )
        assert sim.results[0]["cache_creation_input_tokens"] > 0
        assert sim.results[0]["cache_read_input_tokens"] == 0
        assert (
            sim.results[1]["cache_read_input_tokens"]
            == sim.results[0]["cache_creation_input_tokens"]
        )
        assert sim.results[1]["cache_creation_input_tokens"] == 0

    async def test_different_prefix_does_not_hit(self) -> None:
        """대조군 — system이 다르면 같은 브레이크포인트 위치여도 적중 0."""
        sim = PrefixCacheSim()
        for text in ("A" * 400, "B" * 400):
            await sim.create(
                model="m",
                max_tokens=1,
                system=[{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": "q"}],
            )
        assert [r["cache_read_input_tokens"] for r in sim.results] == [0, 0]

    async def test_top_level_cache_control_marks_the_last_block(self) -> None:
        """최상위 `cache_control` = 마지막 블록(user)이 브레이크포인트 — user가 같으면 적중, 다르면 0."""
        sim = PrefixCacheSim()
        for user in ("같은 user", "같은 user", "다른 user"):
            await sim.create(
                model="m",
                max_tokens=1,
                system="S" * 400,
                messages=[{"role": "user", "content": user}],
                cache_control={"type": "ephemeral"},
            )
        assert [r["cache_read_input_tokens"] > 0 for r in sim.results] == [False, True, False]


# ──────────────────────────────────────────────────────────────────────────
# 경로별 — 종전(최상위) vs 수정(system 블록 끝), 연속 2회 호출
# ──────────────────────────────────────────────────────────────────────────
class TestPlacementPerPath:
    @pytest.mark.parametrize("path", PATH_NAMES)
    async def test_legacy_top_level_never_hits_on_variable_tail(self, path: str) -> None:
        """종전 배치 — 2회차 적중 0, 쓰기 할증은 *매번* 낸다(문제 실증·시뮬레이션)."""
        sim, provider = _build("legacy_top_level")
        pairs = _pairs(sim, await _drive(path, provider))
        for first, second in pairs:
            assert first["cache_creation_input_tokens"] > 0
            assert second["cache_read_input_tokens"] == 0
            assert second["cache_creation_input_tokens"] > 0  # 다시 읽히지 않을 바이트에 또 쓴다
        assert all(u is not None and u.cache_read_input_tokens == 0 for u in provider.usages[1::2])

    @pytest.mark.parametrize("path", PATH_NAMES)
    async def test_system_block_breakpoint_hits_on_second_call(self, path: str) -> None:
        """수정 배치 — 2회차 `cache_read_input_tokens` > 0, 쓰기는 1회차뿐(시뮬레이션 — 라이브 아님)."""
        sim, provider = _build("system_block")
        pairs = _pairs(sim, await _drive(path, provider))
        for first, second in pairs:
            assert first["cache_creation_input_tokens"] > 0
            assert first["cache_read_input_tokens"] == 0
            assert second["cache_read_input_tokens"] > 0
            assert second["cache_read_input_tokens"] == first["cache_creation_input_tokens"]
            assert second["cache_creation_input_tokens"] == 0
        # 시뮬레이터 usage가 provider의 실제 `_extract_usage`를 거쳐 GenerationResult에 올라온다.
        second_usages = provider.usages[1::2]
        assert second_usages and all(
            u is not None and u.cache_read_input_tokens and u.cache_read_input_tokens > 0
            for u in second_usages
        )

    @pytest.mark.parametrize("path", PATH_NAMES)
    async def test_variable_user_tail_is_never_marked(self, path: str) -> None:
        """수정 배치의 요청 형태 — 최상위 키 없음·system 마지막 블록 표시·user 무표시."""
        sim, provider = _build("system_block")
        await _drive(path, provider)
        assert sim.requests
        for request in sim.requests:
            assert "cache_control" not in request["kwargs"]
            system = request["system"]
            assert isinstance(system, list) and len(system) == 1
            assert system[0]["cache_control"] == {"type": "ephemeral"}
            for message in request["messages"]:
                assert isinstance(message["content"], str)  # 블록·표시 없는 문자열 content

    async def test_legacy_hits_only_when_user_prompt_is_identical(self) -> None:
        """대조군 — 종전 배치도 user가 *완전히 같으면* 적중한다(2026-09-21 라이브 89.9%의 정체)."""
        sim, provider = _build("legacy_top_level")
        for _ in range(2):
            await provider.generate("완전히 같은 user", "공유 system " * 30, _cloud_decision())
        assert sim.results[1]["cache_read_input_tokens"] > 0

    async def test_different_system_does_not_share_prefix(self) -> None:
        """대조군 — 수정 배치라도 system이 다르면(관점이 다르면) 프리픽스가 달라 적중 0."""
        sim, provider = _build("system_block")
        await provider.generate("같은 user", "system 가 " * 40, _cloud_decision())
        await provider.generate("같은 user", "system 나 " * 40, _cloud_decision())
        assert sim.results[1]["cache_read_input_tokens"] == 0

    async def test_empty_system_has_no_breakpoint_so_no_cache(self) -> None:
        """빈 system + 캐싱 ON → 브레이크포인트 없음(user에 옮겨 달지 않는다) — 읽기도 쓰기도 없다."""
        sim, provider = _build("system_block")
        for user in ("u1", "u2"):
            await provider.generate(user, "", _cloud_decision())
        assert (
            sim.results
            == [
                {
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                }
            ]
            * 2
        )


# ──────────────────────────────────────────────────────────────────────────
# ④ 최소 캐시 프리픽스 — 위/아래/불명 3상태(불명을 통과로 접지 않는다)
# ──────────────────────────────────────────────────────────────────────────
# 상·하한 근거(오프라인 — 정확한 토크나이저 없음, `count_tokens`는 라이브라 미수행):
#   · 토큰 수 *상한* = UTF-8 바이트 수. 바이트 단위 BPE는 바이트당 토큰을 1개보다 많이 내지 않는다.
#   · 토큰 수 *하한* = 문자 수 / _MAX_CHARS_PER_TOKEN. 토큰당 문자 수가 이 값을 넘지 않는다고 가정한
#     **보수적 가정**이다(영어 산문 약 4, 수식·한글·JSON은 그보다 낮다). 이 가정이 깨지면 '위' 판정이
#     틀릴 수 있다 — 그래서 '위'는 하한 *가정* 하의 판정이라고 문서에 적는다.
_MAX_CHARS_PER_TOKEN = 6

PrefixState = Literal["above", "below", "unknown"]

# 핀된 모델별 최소 캐시 프리픽스(공개 문서 표를 옮긴 값 — 라이브 미검증):
# claude-sonnet-4-6 = 1024 · claude-opus-4-7 = 2048. (Opus 4.7은 1024가 아니다 — 태스크 본문은 Sonnet 기준.)
MIN_PREFIX_TOKENS: dict[str, int] = {"claude-sonnet-4-6": 1024, "claude-opus-4-7": 2048}


def classify_min_prefix(text: str, minimum: int) -> PrefixState:
    """system 프롬프트가 최소 캐시 프리픽스 위/아래/불명인가 — 오프라인 보수적 3상태."""
    upper_tokens = len(text.encode("utf-8"))
    lower_tokens = len(text) / _MAX_CHARS_PER_TOKEN
    if upper_tokens < minimum:
        return "below"
    if lower_tokens >= minimum:
        return "above"
    return "unknown"


def may_assume_cache_effective(state: PrefixState) -> bool:
    """'위'만 캐시 유효로 가정할 수 있다 — '불명'은 통과가 아니다."""
    return state == "above"


class TestMinPrefixThreeState:
    def test_below_when_even_every_byte_is_a_token(self) -> None:
        assert classify_min_prefix("가" * 300, 1024) == "below"  # 900 bytes < 1024

    def test_above_when_even_the_densest_tokenization_exceeds(self) -> None:
        assert classify_min_prefix("a" * 6144, 1024) == "above"  # 6144/6 = 1024

    def test_unknown_in_between_and_unknown_is_not_a_pass(self) -> None:
        text = "가" * 1000  # 3000 bytes ≥ 1024 이고 1000/6 < 1024 → 불명
        state = classify_min_prefix(text, 1024)
        assert state == "unknown"
        assert may_assume_cache_effective(state) is False
        assert may_assume_cache_effective("below") is False
        assert may_assume_cache_effective("above") is True

    def test_boundary_just_below_and_just_above_the_byte_bound(self) -> None:
        assert classify_min_prefix("a" * 1023, 1024) == "below"
        assert classify_min_prefix("a" * 1024, 1024) == "unknown"

    def test_pinned_models_have_a_recorded_minimum(self) -> None:
        """핀된 모델 ID가 바뀌면 최소 프리픽스 표를 다시 확인하게 강제한다."""
        settings = Settings()
        assert settings.anthropic_model_mid in MIN_PREFIX_TOKENS
        assert settings.anthropic_model_high in MIN_PREFIX_TOKENS

    def test_real_system_prompts_are_classified_never_assumed(self) -> None:
        """실제 경로의 system 프롬프트 전부가 3상태 중 하나로 *판정*된다(가정으로 통과시키지 않는다)."""
        prompts = {
            f"cross_verify[{p.principle}]": p.system_prompt for p in PROBABILITY_PERSPECTIVES
        }
        prompts["multi_solution._SYSTEM_PROMPT"] = MULTI_SOLUTION_SYSTEM
        for name, prompt in prompts.items():
            for model, minimum in MIN_PREFIX_TOKENS.items():
                state = classify_min_prefix(prompt, minimum)
                assert state in ("above", "below", "unknown"), (name, model)

    async def test_below_minimum_prefix_is_a_silent_noop_even_with_correct_placement(self) -> None:
        """위치를 고쳐도 최소 미만이면 캐시는 조용히 무효다 — 응답은 정상이고 creation·read 모두 0."""
        sim, provider = _build("system_block", min_cache_tokens=1024)
        for user in ("u1", "u2"):
            await provider.generate(user, "짧은 system", _cloud_decision())
        for result in sim.results:
            assert result["cache_creation_input_tokens"] == 0
            assert result["cache_read_input_tokens"] == 0
