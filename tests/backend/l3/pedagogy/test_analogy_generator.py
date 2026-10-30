"""비유 생성기(analogy_generator) 단위 테스트 — 라우터 경유·seam 주입·상태기계·착지 가드.

hermetic(라이브 LLM 0 — FakeProvider 주입·이 컨테이너에 로컬 LLM 없음). 검증 축:
  ① select-vs-generate 표적 계획(공백·결함·탈락분만 — 무결함 기존 비유 발주 금지·04g §6.4)
  ② 라우터 경유(RoutingDecision이 provider에 전달·저작 패밀리 GENERAL 스왑)
  ③ DRAFT 산출 → prescreen→review 상태기계 재사용(게임형 산출 REJECTED — 게임형 0 검사)
  ④ MetaphorFillStore SQL 가드(공백·ai_estimated 행만 UPDATE·review_status 'ai_estimated' 유지)
  ⑤ 실패 폴백(None) — provider 예외·JSON 붕괴·breaks 결측(04g §6.3 계약)
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import TracebackType

import pytest

from whymath_backend.l3.models import GenerationResult, ModelFamily, RoutingDecision
from whymath_backend.l3.pedagogy.analogy_generator import (
    ANALOGY_TARGET_REASONS,
    AnalogyGenerator,
    AnalogyTarget,
    MetaphorFillStore,
    build_analogy_draft_row,
    plan_analogy_targets,
    run_analogy_review,
)

# 한계 명시를 갖춘 무결함 비유 응답(전 축 clean) — 정상 경로 표본.
_GOOD_ANALOGY = (
    "함수는 자판기와 같아. 다만 실제 함수는 버튼 없는 입력도 받는다는 점이 다르다 — "
    "이 비유는 정의가 아니라 디딤돌이다."
)
_GOOD_JSON = json.dumps(
    {"analogy": _GOOD_ANALOGY, "breaks": "입력 형태가 버튼에 한정되지 않는 지점"},
    ensure_ascii=False,
)


class FakeProvider:
    """스크립트 응답 provider 대역 — LLMProvider 충족(네트워크 0·llm_generator 테스트 미러)."""

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.calls: list[tuple[str, str]] = []
        self.decisions: list[RoutingDecision] = []
        self.temperatures: list[float | None] = []

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
        temperature: float | None = None,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,  # EOS-73 — LLMProvider 계약 정합(대역은 시드를 쓰지 않는다)
    ) -> GenerationResult:
        self.calls.append((prompt, system))
        self.decisions.append(decision)
        self.temperatures.append(temperature)
        text = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return GenerationResult(text=text)


class BrokenProvider:
    """항상 던지는 provider — 안전 폴백(None) 검증용."""

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
        temperature: float | None = None,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,  # EOS-73 — LLMProvider 계약 정합(대역은 시드를 쓰지 않는다)
    ) -> GenerationResult:
        raise RuntimeError("provider 다운(테스트)")


class _NullTrace:
    """무동작 관측 싱크 — 테스트에서 Langfuse 기본 구성을 회피(hermetic)."""

    def record(self, fields: dict[str, object]) -> None:
        del fields


@dataclass
class _Record:
    """plan 입력용 최소 레코드(duck-typing) — 코퍼스/ORM 행 동형 속성만."""

    code: str
    name: str
    subject: str
    metaphor: str | None


def _generator(provider: object) -> AnalogyGenerator:
    return AnalogyGenerator(provider, trace=_NullTrace())  # type: ignore[arg-type]


_TARGET = AnalogyTarget(code="N1", name="자연수", subject="초등수학", reason="blank")


# ──────────────────────────────────────────────────────────────────────────
# ① 표적 계획 — select-vs-generate 불변식
# ──────────────────────────────────────────────────────────────────────────
class TestPlanTargets:
    def test_blank_and_defective_only(self) -> None:
        """공백→blank·결함 보유→defective·무결함 기존 비유→발주 제외(사전 대량 생성 금지)."""
        records = [
            _Record("A", "가", "수학", None),  # 공백
            _Record("B", "나", "수학", "이것이 정의다. 그대로 외워라."),  # 결함(참칭·한계 부재)
            _Record("C", "다", "수학", _GOOD_ANALOGY),  # 무결함 — 제외돼야 한다
        ]
        targets = plan_analogy_targets(records)
        by_code = {t.code: t.reason for t in targets}
        assert by_code == {"A": "blank", "B": "defective"}

    def test_rejected_codes_reordered(self) -> None:
        """검수 탈락 code는 무결함이어도 재발주된다(rejected — 탈락분 재저작 경로)."""
        records = [_Record("C", "다", "수학", _GOOD_ANALOGY)]
        targets = plan_analogy_targets(records, rejected_codes=["C"])
        assert [(t.code, t.reason) for t in targets] == [("C", "rejected")]

    def test_dedup_one_per_concept(self) -> None:
        """개념당 1건(상한 불변식 04g §6.4) — 중복 레코드는 첫 건만."""
        records = [_Record("A", "가", "수학", None), _Record("A", "가", "수학", None)]
        assert len(plan_analogy_targets(records)) == 1

    def test_target_reason_closed_vocab(self) -> None:
        """발주 사유 폐쇄 어휘 밖은 타입 수준 거부 — 무사유 대량 생성 봉인."""
        assert ANALOGY_TARGET_REASONS == frozenset({"blank", "defective", "rejected"})
        with pytest.raises(ValueError):
            AnalogyTarget(code="X", name="x", subject="수학", reason="bulk")

    def test_register_validated(self) -> None:
        with pytest.raises(ValueError):
            AnalogyTarget(code="X", name="x", subject="수학", reason="blank", register="유아")


# ──────────────────────────────────────────────────────────────────────────
# ② 라우터 경유·패밀리 스왑 ⑤ 실패 폴백
# ──────────────────────────────────────────────────────────────────────────
class TestGenerateDraft:
    def test_routes_via_router_with_authoring_family_swap(self) -> None:
        """provider가 받은 결정은 라우터 산출(LOCAL)+저작 패밀리 GENERAL 스왑이다(직접 호출 0)."""
        provider = FakeProvider([_GOOD_JSON])
        row = _generator(provider).generate_draft(_TARGET)
        assert row is not None
        assert len(provider.decisions) == 1
        decision = provider.decisions[0]
        assert decision.cost_tier == "local"  # free 구독 — LOCAL 강제(라우터 규칙 2)
        assert decision.local_family == ModelFamily.GENERAL.value  # 저작 스왑(S2-h 미러)
        assert "저작:general" in decision.reason

    def test_draft_row_shape_and_status(self) -> None:
        """DRAFT 행 형태 — 상태기계 호환 키 + 개념-grain 키(target_code·register)."""
        row = _generator(FakeProvider([_GOOD_JSON])).generate_draft(_TARGET)
        assert row is not None
        assert row["status"] == "DRAFT"
        assert row["id"] == "metaphor:N1:고등"
        assert row["target_code"] == "N1"
        assert row["sympy_verified"] is None  # 은유는 수치 검증 미대상(정직 표기)
        assert row["tts_safe"] is True
        assert row["payload"]["reasoning_type"] == "concept_metaphor"

    def test_register_parameter_reaches_prompt(self) -> None:
        """학년 레지스터는 파라미터 — 프롬프트에 실린다(독립 생성기 금지 축)."""
        provider = FakeProvider([_GOOD_JSON])
        target = AnalogyTarget(
            code="N1", name="자연수", subject="초등수학", reason="blank", register="초등"
        )
        _generator(provider).generate_draft(target)
        prompt, _system = provider.calls[0]
        assert "초등" in prompt

    def test_provider_failure_returns_none(self) -> None:
        assert _generator(BrokenProvider()).generate_draft(_TARGET) is None

    def test_json_garbage_returns_none(self) -> None:
        assert _generator(FakeProvider(["JSON 아님"])).generate_draft(_TARGET) is None

    def test_missing_breaks_returns_none(self) -> None:
        """breaks(깨짐 명시) 결측은 04g §6.3 생성 계약 위반 — 생성 실패(None)."""
        no_breaks = json.dumps({"analogy": _GOOD_ANALOGY}, ensure_ascii=False)
        assert _generator(FakeProvider([no_breaks])).generate_draft(_TARGET) is None

    def test_code_fence_tolerated(self) -> None:
        """코드펜스 응답 관대 파싱(_extract_json 미러) — 실 LLM 출력 형태 내성."""
        fenced = f"```json\n{_GOOD_JSON}\n```"
        assert _generator(FakeProvider([fenced])).generate_draft(_TARGET) is not None


# ──────────────────────────────────────────────────────────────────────────
# ③ 상태기계 재사용 — 게임형 REJECTED(게임형 산출 0 검사)
# ──────────────────────────────────────────────────────────────────────────
class TestRunAnalogyReview:
    def test_clean_draft_approved(self) -> None:
        row = build_analogy_draft_row(_TARGET, _GOOD_ANALOGY, "입력 형태 한정 지점")
        outcome = run_analogy_review([row])[0]
        assert outcome.status == "APPROVED"
        assert outcome.reject_reason is None
        assert outcome.prescreen_score >= 2  # 예심 통과 임계(v_prescreen_calibration 정합)

    def test_gamified_draft_rejected(self) -> None:
        """게임형 초안은 REJECTED(GAMIFIED) — APPROVED 산출의 게임형 0을 게이트가 보장."""
        row = build_analogy_draft_row(
            _TARGET, "문제를 풀면 경험치가 쌓이고 레벨업하는 비유. 다만 다르다.", "깨짐"
        )
        outcome = run_analogy_review([row])[0]
        assert outcome.status == "REJECTED"
        assert outcome.reject_reason == "GAMIFIED"

    def test_missing_break_clause_rejected(self) -> None:
        row = build_analogy_draft_row(_TARGET, "함수는 자판기와 같다. 그게 전부다.", "없음")
        outcome = run_analogy_review([row])[0]
        assert outcome.status == "REJECTED"
        assert outcome.reject_reason == "MISSING_BREAK_CLAUSE"

    def test_definition_usurpation_rejected(self) -> None:
        row = build_analogy_draft_row(_TARGET, "함수란 자판기라고 정의된다. 외워라.", "없음")
        outcome = run_analogy_review([row])[0]
        assert outcome.status == "REJECTED"
        assert outcome.reject_reason in ("MISSING_BREAK_CLAUSE", "DEFINITION_USURPATION")

    def test_structural_defect_rejected_by_reused_gate(self) -> None:
        """빈 본문은 기존 review_slot 게이트가 반려 — 상태기계 *재사용*의 실증(새 게이트 아님)."""
        row = build_analogy_draft_row(_TARGET, "   ", "깨짐")
        outcome = run_analogy_review([row])[0]
        assert outcome.status == "REJECTED"
        assert outcome.reject_reason == "empty_body"

    def test_no_approved_output_contains_gamification(self) -> None:
        """게임형 산출 0 검사(전수) — 어떤 초안 집합이든 APPROVED에 게임화 어휘가 없다."""
        from whymath_backend.l3.pedagogy.analogy_checker import GAMIFICATION_VOCAB

        rows = [
            build_analogy_draft_row(_TARGET, _GOOD_ANALOGY, "지점"),
            build_analogy_draft_row(
                AnalogyTarget(code="N2", name="정수", subject="수학", reason="blank"),
                "퀘스트를 깨듯 정수를 배우자. 다만 다르다.",
                "지점",
            ),
        ]
        for outcome in run_analogy_review(rows):
            if outcome.status == "APPROVED":
                body = outcome.row["payload"]["body"]
                assert not any(word in body for word in GAMIFICATION_VOCAB)


# ──────────────────────────────────────────────────────────────────────────
# ④ MetaphorFillStore — 착지 SQL 가드(fake engine·slot_generator 테스트 패턴)
# ──────────────────────────────────────────────────────────────────────────
class _FakeConnection:
    def __init__(self, engine: _FakeEngine) -> None:
        self._engine = engine

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def execute(self, statement: object) -> None:
        self._engine.executed.append(statement)


class _FakeEngine:
    def __init__(self) -> None:
        self.executed: list[object] = []

    def begin(self) -> _FakeConnection:
        return _FakeConnection(self)


def _compile_sql(statement: object) -> str:
    from sqlalchemy.dialects import postgresql

    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


class TestMetaphorFillStore:
    def _approved_outcome(self) -> object:
        row = build_analogy_draft_row(_TARGET, _GOOD_ANALOGY, "지점")
        return run_analogy_review([row])[0]

    def test_apply_updates_with_blank_or_ai_estimated_guard(self) -> None:
        """UPDATE 가드 — 공백·ai_estimated 행만 갱신(검수 승격 행 보호·fail-closed)."""
        engine = _FakeEngine()
        outcome = self._approved_outcome()
        n = MetaphorFillStore(engine=engine).apply([outcome])  # type: ignore[arg-type, list-item]
        assert n == 1
        sql = _compile_sql(engine.executed[0])
        assert "UPDATE concept_content" in sql
        assert "metaphor IS NULL" in sql
        assert "review_status" in sql

    def test_rejected_outcomes_not_applied(self) -> None:
        """REJECTED는 착지하지 않는다 — 검수 통과 후 metaphor 채움(04g §6.2)."""
        engine = _FakeEngine()
        # 깨짐 신호 어휘가 전무한 본문("한계"라는 낱말 자체도 신호라 피한다) — 확실한 REJECTED.
        row = build_analogy_draft_row(_TARGET, "함수는 자판기와 같다. 그게 전부다.", "없음")
        outcome = run_analogy_review([row])[0]
        assert outcome.status == "REJECTED"
        n = MetaphorFillStore(engine=engine).apply([outcome])  # type: ignore[arg-type, list-item]
        assert n == 0
        assert engine.executed == []
