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
from whymath_backend.l1.concept_content.review_gate import is_supply_eligible
from whymath_backend.l3.models import RoutingRequest
from whymath_backend.l3.render.adapter import RenderContext
from whymath_backend.l3.render.dsl import ConceptDSL
from whymath_backend.l4.content_supply import (
    DSL_CACHE_PREFIX,
    LOOKUP_CROSSWALK,
    LOOKUP_PK,
    REASON_CANNOT_RENDER,
    REASON_NO_DSL,
    REASON_UNREVIEWED,
    SupplyTally,
    get_concept_dsl,
    resolve_concept_content,
    resolve_concept_dsl,
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
    # 렌더·폴백·집계 테스트는 검수 통과 행을 전제한다(CONT-05 공급 게이트 통과). 게이트 자체는
    # `TestSupplyReviewGate`가 `ai_estimated`를 명시해 검사한다 — 실 코퍼스 846행은 전부 ai_estimated다.
    review_status: str = "reviewed"
    # 역조회(CONT-06)는 K-12 행만 본다 — 대학 행은 code가 이미 원자 소단원이라 PK로 닿는다.
    scope: str = "K-12"


class _FakeScalars:
    def __init__(self, rows: list[_FakeRow]) -> None:
        self._rows = rows

    def all(self) -> list[_FakeRow]:
        return list(self._rows)


class _FakeResult:
    def __init__(self, rows: list[_FakeRow]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeSession:
    """`session.get(Model, pk)` + 역조회용 `session.execute(select)` 대역 — 실 DB 없이 공급 경로를 검사한다.

    `execute`는 stmt를 **해석**해 흉내낸다(전건 반환 위장 금지): 바인딩 값 중에 행의 `atom_codes`에
    들어 있는 것이 있고 scope가 K-12인 행만 돌려주며, stmt에 ORDER BY가 있을 때만 code 오름차순으로
    정렬한다 — 쿼리에서 정렬이나 scope 조건이 빠지면 이 대역도 그대로 어긋난다.
    """

    def __init__(self, rows: dict[str, _FakeRow] | None = None) -> None:
        self._rows = rows or {}
        self.get_calls = 0
        self.execute_calls = 0

    async def get(self, _model: object, pk: str) -> _FakeRow | None:
        self.get_calls += 1
        return self._rows.get(pk)

    async def execute(self, stmt: Any) -> _FakeResult:
        self.execute_calls += 1
        params = set(stmt.compile().params.values())
        sql = str(stmt)
        rows = [
            r
            for r in self._rows.values()
            if ("scope" not in sql or r.scope in params) and params & set(r.atom_codes)
        ]
        if "ORDER BY" in sql:
            rows.sort(key=lambda r: r.code)
        return _FakeResult(rows)


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
    async def test_cache_hit_rereads_review_status_but_serves_cached_body(self) -> None:
        # CONT-05 ③ — 종전 계약("적중이면 DB를 안 탄다")을 의도적으로 바꿨다. 적중도 검수 게이트
        # 판정을 위해 행을 읽는다(get_calls 2): 판정을 캐시에 맡기면 강등된 행이 TTL(24h) 동안
        # 계속 공급된다. 캐시가 여전히 쓰인다는 대조로, 두 호출 사이에 DB 본문을 바꿔도 적중은
        # 캐시 본문을 준다 — 캐시가 아끼는 것은 투영·주입이지 게이트 판정이 아니다.
        row = _FakeRow()
        session, cache = _FakeSession({"A1": row}), _FakeCache()
        await get_concept_dsl("A1", session=session, cache=cache)
        row.name = "바뀐 이름"
        again = await get_concept_dsl("A1", session=session, cache=cache)

        assert again is not None and again.name == "일차식"  # 캐시 본문
        assert session.get_calls == 2  # 적중도 게이트 판정을 위해 행을 읽는다.

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


# ── 검수 게이트(CONT-05) ──────────────────────────────────────────


class TestSupplyReviewGate:
    """CONT-05 ⓐ — 공급은 `reviewed`만 통과(fail-closed)하고, 캐시 적중 경로도 같은 검사를 지난다.

    변별력 축 셋(acceptance ④): ai_estimated 거부 · reviewed 공급(성공 방향 대조) · 없는 code는
    기존대로 None. 거기에 캐시 적중 우회 차단(강등 즉시 반영)과 사유 분리(집계 관측)를 더한다.
    """

    @pytest.mark.asyncio
    async def test_ai_estimated_row_is_refused_and_not_cached(self) -> None:
        session = _FakeSession({"A1": _FakeRow(review_status="ai_estimated")})
        cache = _FakeCache()
        dsl, reason = await resolve_concept_dsl("A1", session=session, cache=cache)

        assert dsl is None
        assert reason == REASON_UNREVIEWED
        assert cache.store == {}  # 검수 전 본문은 캐시에도 남기지 않는다.
        assert await get_concept_dsl("A1", session=session, cache=cache) is None

    @pytest.mark.asyncio
    async def test_reviewed_row_is_supplied(self) -> None:
        # 성공 방향 대조 — 같은 형태의 행이 reviewed면 공급된다(게이트가 항상 막는 위장이 아니다).
        session = _FakeSession({"A1": _FakeRow(review_status="reviewed")})
        dsl, reason = await resolve_concept_dsl("A1", session=session, cache=_FakeCache())

        assert dsl is not None and dsl.code == "A1"
        assert reason is None

    @pytest.mark.asyncio
    async def test_missing_code_keeps_no_dsl_reason(self) -> None:
        # 없는 code는 기존대로 None — 사유는 검수 전(UNREVIEWED)과 구분된다.
        dsl, reason = await resolve_concept_dsl("NOPE", session=_FakeSession(), cache=_FakeCache())

        assert dsl is None
        assert reason == REASON_NO_DSL

    @pytest.mark.asyncio
    async def test_demoted_row_is_refused_even_on_cache_hit(self) -> None:
        # 캐시 적중 경로 우회 차단 — reviewed일 때 적재된 캐시 항목이 TTL 안에 남아 있어도 행이
        # 강등되면 즉시 공급이 멈춘다(판정은 캐시보다 먼저, DB의 현재 상태로 한다).
        row = _FakeRow(review_status="reviewed")
        session, cache = _FakeSession({"A1": row}), _FakeCache()
        assert await get_concept_dsl("A1", session=session, cache=cache) is not None
        assert f"{DSL_CACHE_PREFIX}A1" in cache.store  # 전제 — 캐시가 채워져 있다.

        row.review_status = "ai_estimated"  # 강등(코퍼스 재적재가 DB 승격을 되돌리는 경로 등)
        dsl, reason = await resolve_concept_dsl("A1", session=session, cache=cache)

        assert dsl is None
        assert reason == REASON_UNREVIEWED

    @pytest.mark.parametrize(
        "status",
        ["ai_estimated", "rejected", "", "Reviewed", " reviewed", "reviewed ", "REVIEWED", None],
    )
    def test_only_exact_reviewed_is_eligible(self, status: str | None) -> None:
        # fail-closed — 완전 일치만 통과. 표기 변형·빈 값·None은 오염 입력으로 보고 거부한다.
        assert is_supply_eligible(status) is False

    def test_exact_reviewed_is_eligible(self) -> None:
        assert is_supply_eligible("reviewed") is True

    @pytest.mark.asyncio
    async def test_supply_refuses_unreviewed_and_counts_reason(self) -> None:
        # 공급 경로 — 렌더하지 않고(학생이 볼 조각 0) 사유 UNREVIEWED를 집계에 남긴다.
        tally = SupplyTally()
        result = await supply(
            code="A1",
            signals=StudentSignals(),
            session=_FakeSession({"A1": _FakeRow(review_status="ai_estimated")}),
            cache=_FakeCache(),
            tally=tally,
            seal=default_expression_seal(),
            assessment_verifier=default_assessment_answer_verifier(),
        )

        assert result.rendered is None
        assert result.text is None
        assert result.fallback_reason == REASON_UNREVIEWED
        assert tally.by_fallback_reason == {REASON_UNREVIEWED: 1}
        assert "dsl_render" not in tally.counts

    @pytest.mark.asyncio
    async def test_unreviewed_takes_existing_generate_fallback(self) -> None:
        # "DSL 없음과 같게"(acceptance ②ⓐ) — 생성 폴백을 켠 호출자에게는 기존 폴백 경로 그대로다.
        provider, trace = _FakeProvider(), _RecordingTrace()
        result = await supply(
            code="A1",
            signals=StudentSignals(),
            session=_FakeSession({"A1": _FakeRow(review_status="ai_estimated")}),
            cache=_FakeCache(),
            generate_request=_routing_request(),
            provider=provider,
            trace=trace,
            seal=default_expression_seal(),
            assessment_verifier=default_assessment_answer_verifier(),
        )

        assert result.content_source == "generate"
        assert result.fallback_reason == REASON_UNREVIEWED
        assert provider.calls == 1

    @pytest.mark.asyncio
    async def test_review_status_alone_flips_outcome(self) -> None:
        # 변별력 — 같은 행에서 review_status 하나만 바꿨을 때 결과가 뒤집힌다(캐시는 호출마다 새로).
        async def run(status: str) -> str | None:
            result = await supply(
                code="A1",
                signals=StudentSignals(),
                session=_FakeSession({"A1": _FakeRow(review_status=status)}),
                cache=_FakeCache(),
                seal=default_expression_seal(),
                assessment_verifier=default_assessment_answer_verifier(),
            )
            return result.content_source if result.rendered is not None else result.fallback_reason

        assert await run("reviewed") == "dsl_render"
        assert await run("ai_estimated") == REASON_UNREVIEWED


# ── 크로스워크 역조회(CONT-06) ────────────────────────────────────

_ATOM = "10공수1-02-06-2"  # 파일럿 소단원의 세부개념 원자 — 콘텐츠 PK(구 437 코드)와 겹치지 않는다.


def _k12_row(code: str, *, status: str = "reviewed", atoms: tuple[str, ...] = (_ATOM,)) -> _FakeRow:
    return _FakeRow(code=code, name=f"{code} 콘텐츠", atom_codes=list(atoms), review_status=status)


class TestCrosswalkReverseLookup:
    """CONT-06 ⓐ — PK 미스 시 `atom_codes`를 따라간다. 게이트·캐시 순서는 PK 경로와 같다.

    acceptance ④의 3상태: 역조회 전 NO_DSL → 역조회 후 해석(검수 통과) → ai_estimated면 UNREVIEWED.
    """

    @pytest.mark.asyncio
    async def test_three_states_for_one_pilot_atom(self) -> None:
        # ① 연결된 K-12 행이 없다 → NO_DSL (역조회 이전 상태와 같다)
        none_res = await resolve_concept_content(_ATOM, session=_FakeSession(), cache=_FakeCache())
        assert (none_res.dsl, none_res.reason) == (None, REASON_NO_DSL)
        assert none_res.lookup_via is None

        # ② 연결된 행이 reviewed → 그 행의 DSL로 해석된다(요청 code는 원자, 서빙 code는 콘텐츠 행).
        ok = await resolve_concept_content(
            _ATOM, session=_FakeSession({"HK11": _k12_row("HK11")}), cache=_FakeCache()
        )
        assert ok.reason is None and ok.dsl is not None
        assert ok.dsl.code == "HK11"
        assert (ok.content_code, ok.lookup_via, ok.candidates) == (
            "HK11",
            LOOKUP_CROSSWALK,
            ("HK11",),
        )

        # ③ 같은 연결이 ai_estimated → UNREVIEWED (NO_DSL이 아니다 — 승격하면 열리는 상태다)
        blocked = await resolve_concept_content(
            _ATOM,
            session=_FakeSession({"HK11": _k12_row("HK11", status="ai_estimated")}),
            cache=_FakeCache(),
        )
        assert (blocked.dsl, blocked.reason) == (None, REASON_UNREVIEWED)
        assert blocked.content_code == "HK11" and blocked.lookup_via == LOOKUP_CROSSWALK

    @pytest.mark.asyncio
    async def test_pk_hit_wins_and_skips_reverse_lookup(self) -> None:
        # PK 우선 — 대학 소단원 코드처럼 PK로 닿으면 역조회를 하지 않는다(쿼리 0회).
        session = _FakeSession(
            {
                "UNI1": _FakeRow(code="UNI1", scope="대학"),
                "HK11": _k12_row("HK11", atoms=("UNI1",)),  # 같은 문자열을 atom으로 가진 다른 행
            }
        )
        res = await resolve_concept_content("UNI1", session=session, cache=_FakeCache())

        assert res.content_code == "UNI1" and res.lookup_via == LOOKUP_PK
        assert session.execute_calls == 0

    @pytest.mark.asyncio
    async def test_university_rows_are_not_reverse_matched(self) -> None:
        # 대학 행은 역조회 대상이 아니다 — atom_codes가 우연히 맞아도 scope가 걸러낸다.
        session = _FakeSession({"U1": _FakeRow(code="U1", scope="대학", atom_codes=[_ATOM])})
        res = await resolve_concept_content(_ATOM, session=session, cache=_FakeCache())

        assert (res.dsl, res.reason) == (None, REASON_NO_DSL)

    @pytest.mark.asyncio
    async def test_reviewed_candidate_is_preferred_over_lower_code_unreviewed(self) -> None:
        # 대표 선택 — 코드 순서가 앞서도 검수 전 행이 검수 통과 행을 가리지 못한다.
        session = _FakeSession(
            {
                "HK11": _k12_row("HK11", status="reviewed"),
                "10기수1-02-05": _k12_row("10기수1-02-05", status="ai_estimated"),
            }
        )
        res = await resolve_concept_content(_ATOM, session=session, cache=_FakeCache())

        assert res.content_code == "HK11"
        assert res.candidates == ("10기수1-02-05", "HK11")  # 후보 전체가 오름차순으로 남는다.

    @pytest.mark.asyncio
    async def test_ties_resolve_to_lowest_code_deterministically(self) -> None:
        # 둘 다 reviewed면 code 오름차순 첫 행 — 삽입 순서(DB 반환 순서)에 기대지 않는다.
        rows = {
            "HK11": _k12_row("HK11"),
            "10기수1-02-05": _k12_row("10기수1-02-05"),
        }
        res = await resolve_concept_content(_ATOM, session=_FakeSession(rows), cache=_FakeCache())
        assert res.content_code == "10기수1-02-05"

    @pytest.mark.asyncio
    async def test_all_candidates_unreviewed_reports_unreviewed_not_no_dsl(self) -> None:
        session = _FakeSession(
            {
                "HK11": _k12_row("HK11", status="ai_estimated"),
                "10기수1-02-05": _k12_row("10기수1-02-05", status="rejected"),
            }
        )
        res = await resolve_concept_content(_ATOM, session=session, cache=_FakeCache())

        assert (res.dsl, res.reason) == (None, REASON_UNREVIEWED)
        assert res.candidates == ("10기수1-02-05", "HK11")

    @pytest.mark.asyncio
    async def test_cache_is_keyed_by_serving_row_and_demotion_is_immediate(self) -> None:
        # 캐시 키는 서빙 행 code — 요청 원자로 쪼개지 않는다. 그리고 역조회 경로도 캐시 적중이 게이트를
        # 우회하지 못한다(강등 즉시 거부) — CONT-05 ③이 역조회로 새지 않는다는 동결.
        row = _k12_row("HK11")
        session, cache = _FakeSession({"HK11": row}), _FakeCache()
        assert (await resolve_concept_content(_ATOM, session=session, cache=cache)).dsl is not None
        assert f"{DSL_CACHE_PREFIX}HK11" in cache.store
        assert f"{DSL_CACHE_PREFIX}{_ATOM}" not in cache.store

        row.review_status = "ai_estimated"
        res = await resolve_concept_content(_ATOM, session=session, cache=cache)
        assert (res.dsl, res.reason) == (None, REASON_UNREVIEWED)

    @pytest.mark.asyncio
    async def test_two_atoms_share_one_cache_entry(self) -> None:
        row = _k12_row("HK11", atoms=(_ATOM, "10공수1-02-06-3"))
        session, cache = _FakeSession({"HK11": row}), _FakeCache()
        await resolve_concept_content(_ATOM, session=session, cache=cache)
        await resolve_concept_content("10공수1-02-06-3", session=session, cache=cache)

        assert list(cache.store) == [f"{DSL_CACHE_PREFIX}HK11"]

    @pytest.mark.asyncio
    async def test_supply_serves_via_crosswalk_and_reports_lookup(self) -> None:
        # 서빙 경로 — SupplyResult·집계·trace에 역조회가 보인다(작동한 비율 원칙).
        tally, trace = SupplyTally(), _RecordingTrace()
        result = await supply(
            code=_ATOM,
            signals=StudentSignals(),
            session=_FakeSession({"HK11": _k12_row("HK11")}),
            cache=_FakeCache(),
            trace=trace,
            tally=tally,
            seal=default_expression_seal(),
            assessment_verifier=default_assessment_answer_verifier(),
        )

        assert result.content_source == "dsl_render" and result.rendered is not None
        assert (result.content_code, result.lookup_via) == ("HK11", LOOKUP_CROSSWALK)
        assert result.lookup_candidates == ("HK11",)
        assert tally.by_lookup_via == {LOOKUP_CROSSWALK: 1}
        assert tally.to_json()["by_lookup_via"] == {LOOKUP_CROSSWALK: 1}
        assert trace.records[0]["dsl_code"] == _ATOM
        assert trace.records[0]["content_code"] == "HK11"

    @pytest.mark.asyncio
    async def test_supply_unreviewed_via_crosswalk_renders_nothing(self) -> None:
        # 검수 전 연결 — 렌더 0 · 사유 UNREVIEWED · 그래도 역조회가 일했음은 집계에 남는다.
        tally = SupplyTally()
        result = await supply(
            code=_ATOM,
            signals=StudentSignals(),
            session=_FakeSession({"HK11": _k12_row("HK11", status="ai_estimated")}),
            cache=_FakeCache(),
            tally=tally,
            seal=default_expression_seal(),
            assessment_verifier=default_assessment_answer_verifier(),
        )

        assert result.rendered is None and result.fallback_reason == REASON_UNREVIEWED
        assert tally.by_lookup_via == {LOOKUP_CROSSWALK: 1}
        assert "dsl_render" not in tally.counts

    def test_query_shape_is_scoped_ordered_and_array_membership(self) -> None:
        # 쿼리 형태 동결 — 대역이 아니라 실제로 생성되는 PG SQL을 본다: K-12 한정·배열 포함·code 정렬.
        from sqlalchemy.dialects import postgresql

        from whymath_backend.l1.concept_content.resolve import find_k12_contents_by_atom

        captured: list[Any] = []

        class _Capture:
            async def execute(self, stmt: Any) -> _FakeResult:
                captured.append(stmt)
                return _FakeResult([])

        import asyncio

        asyncio.run(find_k12_contents_by_atom(_Capture(), _ATOM))  # type: ignore[arg-type]
        sql = str(captured[0].compile(dialect=postgresql.dialect()))

        assert "concept_content.scope =" in sql
        assert "= ANY (concept_content.atom_codes)" in sql
        assert "ORDER BY concept_content.code" in sql


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
