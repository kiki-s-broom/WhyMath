"""콘텐츠 공급 경로 테스트 — render-vs-generate 분기·폴백·게이트 우회 불가·경로 집계.

핵심 회귀 둘:
  ① **검증 실패·재료 부족 시 생성 폴백** — 미검증 렌더가 학생에게 나가지 않는다.
  ② **게이트 우회 불가** — supply가 `decide()`를 내부 호출하므로 이 경로로는 냉담 완전예제가
     나갈 수 없다(PED-02 방어선 유지).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from whymath_backend.composition import (
    default_assessment_answer_verifier,
    default_expression_seal,
)
from whymath_backend.l3.models import RoutingRequest
from whymath_backend.l3.render.adapter import RenderContext
from whymath_backend.l3.render.dsl import ConceptDSL
from whymath_backend.l4.content_supply import (
    DSL_CACHE_PREFIX,
    REASON_CANNOT_RENDER,
    REASON_NO_DSL,
    SupplyTally,
    get_concept_dsl,
    supply,
)
from whymath_backend.l4.models import PolyaStage
from whymath_backend.l4.pedagogy.runtime_selector import StudentSignals
from whymath_backend.schema.enums import PedagogyStrategy

# ── 테스트 대역 ──────────────────────────────────────────────────


@dataclass
class _FakeRow:
    """`ConceptContent` ORM 행 최소 대역(투영에 필요한 속성만)."""

    code: str = "A1"
    name: str = "일차식"
    subject: str = "중등수학"
    unit: str | None = "문자와 식"
    metaphor: str | None = "저울의 균형을 맞추는 일과 같다."
    misconception: str | None = "차수를 혼동한다."
    formal_definition_internal: str | None = "미지수의 차수가 1인 식."
    accepted_expressions: str | None = "2x + 3"
    explanation: str | None = None
    standard_codes: list[str] = field(default_factory=list)
    atom_codes: list[str] = field(default_factory=list)
    flashcards: list[dict[str, object]] = field(default_factory=list)


class _FakeSession:
    """`session.get(Model, pk)`만 흉내내는 대역 — 실 DB 없이 공급 경로를 검사한다."""

    def __init__(self, rows: dict[str, _FakeRow] | None = None) -> None:
        self._rows = rows or {}
        self.get_calls = 0

    async def get(self, _model: object, pk: str) -> _FakeRow | None:
        self.get_calls += 1
        return self._rows.get(pk)


class _FakeCache:
    """str 전용 인메모리 캐시(`CacheBackend` 형태). TTL은 기록만."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self.store[key] = value


class _RecordingTrace:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record(self, fields: dict[str, object]) -> None:
        self.records.append(fields)


class _FakeProvider:
    """생성 폴백용 provider 대역 — 호출 여부를 센다."""

    def __init__(self, text: str = "생성된 설명") -> None:
        self.text = text
        self.calls = 0

    async def generate(self, prompt: str, system: str, decision: Any, **kwargs: Any) -> Any:
        from whymath_backend.l3.models import GenerationResult as ProviderResult

        self.calls += 1
        return ProviderResult(text=self.text)


def _routing_request() -> RoutingRequest:
    """LOCAL·동기로 라우팅되는 평이한 요청(기존 파이프라인 테스트 픽스처 동형)."""
    return RoutingRequest(
        task_type="explain",
        difficulty="easy",
        requires_reasoning=False,
        student_subscription="free",  # 무료 → LOCAL 강제(테스트에서 클라우드 미접촉)
        sync=True,
    )


def _session_with_content() -> _FakeSession:
    return _FakeSession({"A1": _FakeRow()})


# ── DSL 캐시 ─────────────────────────────────────────────────────


class TestConceptDslCache:
    """개념 주소화 캐시 — DB read-through·직렬화 왕복·손상 시 미스 취급."""

    @pytest.mark.asyncio
    async def test_db_read_through_populates_cache(self) -> None:
        session, cache = _session_with_content(), _FakeCache()
        dsl = await get_concept_dsl("A1", session=session, cache=cache)

        assert dsl is not None and dsl.code == "A1"
        assert f"{DSL_CACHE_PREFIX}A1" in cache.store  # 적재됨
        assert session.get_calls == 1

    @pytest.mark.asyncio
    async def test_cache_hit_skips_db(self) -> None:
        session, cache = _session_with_content(), _FakeCache()
        await get_concept_dsl("A1", session=session, cache=cache)
        again = await get_concept_dsl("A1", session=session, cache=cache)

        assert again is not None
        assert session.get_calls == 1  # 두 번째는 DB를 안 탄다.

    @pytest.mark.asyncio
    async def test_corrupt_cache_falls_back_to_db(self) -> None:
        # 계약 변경·손상 → 조용히 낡은 형태를 쓰지 않고 미스 취급 후 재적재.
        session, cache = _session_with_content(), _FakeCache()
        cache.store[f"{DSL_CACHE_PREFIX}A1"] = '{"broken": true}'
        dsl = await get_concept_dsl("A1", session=session, cache=cache)

        assert dsl is not None and dsl.name == "일차식"
        assert session.get_calls == 1

    @pytest.mark.asyncio
    async def test_missing_concept_returns_none(self) -> None:
        dsl = await get_concept_dsl("NOPE", session=_FakeSession(), cache=_FakeCache())
        assert dsl is None

    @pytest.mark.asyncio
    async def test_roundtrip_preserves_contract(self) -> None:
        session, cache = _session_with_content(), _FakeCache()
        first = await get_concept_dsl("A1", session=session, cache=cache)
        second = await get_concept_dsl("A1", session=session, cache=cache)
        assert first == second  # 직렬화 왕복이 계약을 보존한다.


# ── 공급 분기 ─────────────────────────────────────────────────────


class TestSupplyBranching:
    """dsl_render / generate 분기 — 있으면 0원 렌더, 없으면 생성."""

    @pytest.mark.asyncio
    async def test_serves_from_dsl_render_when_available(self) -> None:
        provider, trace = _FakeProvider(), _RecordingTrace()
        result = await supply(
            code="A1",
            signals=StudentSignals(),  # 기본 → SOCRATIC(항상 렌더 가능)
            session=_session_with_content(),
            cache=_FakeCache(),
            generate_request=_routing_request(),
            provider=provider,
            trace=trace,
            seal=default_expression_seal(),
            assessment_verifier=default_assessment_answer_verifier(),
        )

        assert result.content_source == "dsl_render"
        assert result.is_free is True
        assert result.rendered is not None and result.rendered.ok
        assert provider.calls == 0  # LLM 미호출.

    @pytest.mark.asyncio
    async def test_falls_back_to_generate_when_no_dsl(self) -> None:
        provider, trace = _FakeProvider(), _RecordingTrace()
        result = await supply(
            code="MISSING",
            signals=StudentSignals(),
            session=_FakeSession(),  # 콘텐츠 없음
            cache=_FakeCache(),
            generate_request=_routing_request(),
            provider=provider,
            trace=trace,
            seal=default_expression_seal(),
            assessment_verifier=default_assessment_answer_verifier(),
        )

        assert result.content_source == "generate"
        assert result.fallback_reason == REASON_NO_DSL
        assert result.text == "생성된 설명"
        assert provider.calls == 1

    @pytest.mark.asyncio
    async def test_cannot_render_falls_back_with_reason(self) -> None:
        # PROBLEM_BASED는 평가 재료가 필요한데 concept_content 투영엔 없다 → 폴백.
        provider, trace = _FakeProvider(), _RecordingTrace()
        result = await supply(
            code="A1",
            signals=StudentSignals(mastery_level="숙달"),  # → PROBLEM_BASED
            session=_session_with_content(),
            cache=_FakeCache(),
            generate_request=_routing_request(),
            provider=provider,
            trace=trace,
            seal=default_expression_seal(),
            assessment_verifier=default_assessment_answer_verifier(),
        )

        assert result.strategy is PedagogyStrategy.PROBLEM_BASED
        assert result.content_source == "generate"
        assert result.fallback_reason == REASON_CANNOT_RENDER
        assert provider.calls == 1

    @pytest.mark.asyncio
    async def test_no_generate_deps_returns_reason_without_calling_llm(self) -> None:
        # 폴백 인자를 안 주면 생성하지 않고 사유만 돌려준다(사전 점검·배치 용도).
        result = await supply(
            code="MISSING",
            signals=StudentSignals(),
            session=_FakeSession(),
            cache=_FakeCache(),
            seal=default_expression_seal(),
            assessment_verifier=default_assessment_answer_verifier(),
        )
        assert result.content_source == "generate"
        assert result.fallback_reason == REASON_NO_DSL
        assert result.text is None


class TestSupplyDiscriminativePower:
    """변별력 — DSL 유무만 바꿨을 때 경로가 실제로 뒤집히는지(위장 방지)."""

    @pytest.mark.asyncio
    async def test_dsl_presence_alone_flips_content_source(self) -> None:
        # 캐시는 호출마다 새로 준다 — 공유하면 첫 호출이 적재한 DSL을 둘째가 히트해
        # "DSL 유무"가 아니라 "캐시 유무"를 재게 된다(변별력 테스트 자체가 무효화된다).
        async def run(session: _FakeSession) -> str:
            result = await supply(
                code="A1",
                signals=StudentSignals(),
                session=session,
                cache=_FakeCache(),
                generate_request=_routing_request(),
                provider=_FakeProvider(),
                trace=_RecordingTrace(),
                seal=default_expression_seal(),
                assessment_verifier=default_assessment_answer_verifier(),
            )
            return result.content_source

        assert await run(_session_with_content()) == "dsl_render"
        assert await run(_FakeSession()) == "generate"


class TestGateCannotBeBypassed:
    """게이트 우회 불가 — supply 경로로는 냉담 완전예제가 나갈 수 없다(PED-02 방어선)."""

    @pytest.mark.asyncio
    async def test_stuck_concept_student_never_gets_worked_example(self) -> None:
        # 막힘 + 시도 전 + 힌트 미상승 + CONCEPT → 선택은 WORKED_EXAMPLE이지만 게이트가 강등.
        result = await supply(
            code="A1",
            signals=StudentSignals(polya_stage=PolyaStage.UNDERSTAND, turn_count=5, hint_level=1),
            session=_session_with_content(),
            cache=_FakeCache(),
            k_type="CONCEPT",
            seal=default_expression_seal(),
            assessment_verifier=default_assessment_answer_verifier(),
        )

        assert result.strategy is not PedagogyStrategy.WORKED_EXAMPLE
        assert result.strategy is PedagogyStrategy.SOCRATIC  # 말하기 대신 묻기
        assert result.gate_reason_code is not None  # 차단 사유가 보존된다

    @pytest.mark.asyncio
    async def test_supply_signature_has_no_strategy_injection(self) -> None:
        # 구조적 보증 — 전략을 인자로 받지 않으므로 호출자가 게이트를 건너뛸 수 없다.
        import inspect

        params = set(inspect.signature(supply).parameters)
        assert "strategy" not in params
        assert "signals" in params  # 전략은 신호에서 *유도*된다.


# ── 집계(이중 회계) ──────────────────────────────────────────────


class TestSupplyTally:
    """in-process 집계 — 판정치는 Langfuse가 아니라 여기서 나온다."""

    def test_empty_tally_reports_none_not_zero(self) -> None:
        # 표본 0을 0%로 위장하지 않는다("미상" ≠ 0).
        tally = SupplyTally()
        assert tally.total == 0
        assert tally.dsl_render_rate is None
        assert tally.dsl_render_rate_lower is None

    def test_counts_and_rate(self) -> None:
        tally = SupplyTally()
        for _ in range(7):
            tally.record("dsl_render")
        for _ in range(3):
            tally.record("generate")

        assert tally.total == 10
        assert tally.dsl_render_rate == pytest.approx(0.7)

    def test_wilson_lower_is_below_point_estimate(self) -> None:
        # 게이트는 하한으로 — 작은 표본에서 점추정만 보면 과신한다.
        tally = SupplyTally()
        for _ in range(5):
            tally.record("dsl_render")

        assert tally.dsl_render_rate == 1.0
        lower = tally.dsl_render_rate_lower
        assert lower is not None and lower < 1.0

    @pytest.mark.asyncio
    async def test_supply_feeds_tally(self) -> None:
        tally = SupplyTally()
        await supply(
            code="A1",
            signals=StudentSignals(),
            session=_session_with_content(),
            cache=_FakeCache(),
            tally=tally,
            seal=default_expression_seal(),
            assessment_verifier=default_assessment_answer_verifier(),
        )
        assert tally.counts.get("dsl_render") == 1

    def test_to_json_shape(self) -> None:
        tally = SupplyTally()
        tally.record("dsl_render")
        payload = tally.to_json()
        assert payload["total"] == 1
        assert "dsl_render_rate_lower" in payload


class TestSupplyTracing:
    """관측 — 렌더 경로도 기록된다(라우팅 결정이 없어도)."""

    @pytest.mark.asyncio
    async def test_render_path_records_content_source(self) -> None:
        trace = _RecordingTrace()
        await supply(
            code="A1",
            signals=StudentSignals(),
            session=_session_with_content(),
            cache=_FakeCache(),
            trace=trace,
            seal=default_expression_seal(),
            assessment_verifier=default_assessment_answer_verifier(),
        )
        assert any(r.get("content_source") == "dsl_render" for r in trace.records)
        assert any(r.get("cost_krw") == 0.0 for r in trace.records)


class TestRenderContextPassthrough:
    @pytest.mark.asyncio
    async def test_bindings_reach_the_adapter(self) -> None:
        session = _FakeSession({"A1": _FakeRow(metaphor="계수가 {coef}인 저울.")})
        result = await supply(
            code="A1",
            signals=StudentSignals(misconception_ids=("m1",)),  # → ANALOGY(직관 사용)
            session=session,
            cache=_FakeCache(),
            ctx=RenderContext(bindings={"coef": "3"}),
            seal=default_expression_seal(),
            assessment_verifier=default_assessment_answer_verifier(),
        )
        assert result.content_source == "dsl_render"
        assert result.rendered is not None
        body = " ".join(seg.content for seg in result.rendered.segments)
        assert "계수가 3인 저울" in body


def _unused(dsl: ConceptDSL) -> None:  # pragma: no cover - 타입 임포트 보존용
    assert dsl.code
