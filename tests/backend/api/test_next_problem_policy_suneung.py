"""EOS-25 수능 모드 추천 — 설명은 전달 문항에 맞추고 콘텐츠 재선택은 보류한다 (hermetic · DB 0).

수능 정책(`api/_next_problem_policy.py::SuneungRecommendationPolicy`)은 EOS-124가 기본 CAT에서
고친 결함을 그대로 품고 있었다(2026-09-28 재현 · main `78a8edff`). 문항을 수능 CAT으로 고른 *뒤*
그 문항 개념의 숙달 구간으로 행위를 붙이고, 목표 개념은 따로 계산했다. 그래서 세 형태가 나갔다:

  (가) 숙달 0.98 개념 문항에 `advance_next` · target = 그 개념        → 정렬 R3 위반
  (나) 선수 숙달 1.0인데 `practice_prerequisite` · target = 그 선수   → 정렬 R2 위반
  (다) 선수가 미측정인데 `practice_prerequisite` · target = 문항 개념 → 정렬 R3 위반

판정(`docs/reviews/eos25_suneung_policy_alignment_judgment_2026-09-28.md`)은 안 B′다 — 의도는
기본 CAT과 같은 함수로 세우고 산출은 정렬을 선언하지만, 관계 행위의 **콘텐츠 재선택은 보류**한다
(`mode_withheld`). 수능 게이트가 학년·범위를 보지 않고(`EOS-31`) 구간 입력에 신뢰 하한이 없어서
(`EOS-33`) 지금 재선택을 켜면 응답 1~2개로 모드 밖 콘텐츠로 옮겨 가기 때문이다.

이 파일이 지키는 것:

① **세 형태가 다시 나오지 않는다** — 세 입력을 그대로 재주입하고, 산출을 정렬 판정기에 한 번 더
   건다(생성 시점 검증기와 별개로).
② **콘텐츠는 옮겨지지 않는다** — 어떤 구간·그래프 모양에서도 전달 문항은 1차 선택 문항이다. 세션
   대역은 1차 후보 풀 조회 **한 번만** 허용한다 — 누군가 재선택(목표 개념 후보 조회)을 끼워 넣으면
   두 번째 직접 조회에서 곧바로 터진다.
③ **보류와 다른 강등이 섞이지 않는다** — "안 했다"(`mode_withheld`)와 "못 했다"(반증 `refuted` ·
   근거 없음 `unsupported` · 시간 초과 `graph_timeout`)가 다른 값으로 남는다.

그래프·근거 조회는 모듈 이름을 바꿔 끼운 대역이다. 실제 그래프·숙달 이력으로 같은 판정이 서는지는
`test_eos25_suneung_alignment_integration.py`(실 PG)가 본다.

**변별력 확인**: `scripts/analysis/mutate_eos25_suneung_alignment_guards.py`가 결함 형태를 되살리는
뮤테이션을 주입해 이 파일이 RED가 되는지 본다(CLAUDE.md "보호 장치를 실패 주입 없이 선언 금지").
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from whymath_backend.api import _next_problem_policy as suneung_module
from whymath_backend.api._next_problem_policy import SuneungRecommendationPolicy
from whymath_backend.l1.problem_bank.persona_fit_rules import derive_persona_fit
from whymath_backend.l2 import recommendation_policy as policy_module
from whymath_backend.l2.learner_state import LearnerState
from whymath_backend.l2.next_problem_selection import AttemptHistoryState, SuccessorRow
from whymath_backend.l2.prerequisite_recommendation import PrerequisiteRow
from whymath_backend.l2.recommendation_contract import (
    LearningContext,
    ReasonType,
    RecommendationAction,
    RecommendationReason,
    build_reason,
    check_intent_alignment,
    no_candidate_reason,
)
from whymath_backend.l2.recommendation_evidence import POLICY_VERSION_SUNEUNG
from whymath_backend.l2.recommendation_policy import (
    ConceptGraphBudget,
    IntentResolution,
    NextProblemOutcome,
)
from whymath_backend.l6.suneung import is_suneung_eligible
from whymath_backend.schema.enums import (
    Curriculum,
    Persona,
    ReviewStatus,
    SignaturePattern,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem as SchemaProblem

_ANCHOR = uuid.uuid4()
_PRE_A = uuid.uuid4()
_PRE_B = uuid.uuid4()
_NEXT = uuid.uuid4()
_BLOCKED = uuid.uuid4()


def _state(mastery: dict[str, float] | None = None) -> LearnerState:
    """숙달만 채운 최소 `LearnerState` — 이 파일이 재는 것은 정책 오케스트레이션이다."""
    return LearnerState(
        student_id=str(uuid.uuid4()),
        timestamp=datetime.now(UTC),
        mastery=mastery or {},
        general_ability=None,
        domain_abilities={},
        active_misconceptions=[],
        recent_struggles=[],
        recent_successes=[],
        grade=None,
        goals={},
    )


def _problem(**over: Any) -> SchemaProblem:
    """수능 적격 기본값(시그니처 보유 · 검수 통과 · 자체생성) — 필요한 필드만 덮어쓴다."""
    kwargs: dict[str, Any] = {
        "source_type": SourceType.자체생성,
        "review_status": ReviewStatus.approved,
        "curriculum_version": Curriculum.REVISION_2022,
        "valid_from_year": 2022,
        "subject": Subject.공통,
        "unit_codes": ["U-EOS25"],
        "difficulty_overall": 3.0,
        "signature_patterns": [SignaturePattern.COMPOUND_CHOICES],
    }
    kwargs.update(over)
    return SchemaProblem(**kwargs)


def _prereq(concept_id: uuid.UUID, code: str, depth: int = 1) -> PrerequisiteRow:
    return PrerequisiteRow(
        concept_id=concept_id, concept_code=code, name_ko=None, edge_strength=None, depth=depth
    )


def _succ(concept_id: uuid.UUID, code: str) -> SuccessorRow:
    return SuccessorRow(concept_id=concept_id, concept_code=code)


class _OrmRow:
    """`select(Problem)` ORM 행 대역 — 정책은 `.to_schema()`만 부른다."""

    def __init__(self, problem: SchemaProblem) -> None:
        self._problem = problem

    def to_schema(self) -> SchemaProblem:
        return self._problem


class _Result:
    def __init__(self, rows: list[_OrmRow]) -> None:
        self._rows = rows

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[_OrmRow]:
        return self._rows


class _PoolSession:
    """1차 후보 풀 **한 번**만 돌려주는 세션 대역 — 두 번째 직접 조회는 설계 밖이다.

    나머지 조회(이력·근거·그래프·약점 가중)는 전부 모듈 이름 교체로 대역한다. 그래서 정책이
    콘텐츠 재선택(목표 개념 후보 조회)을 다시 끼워 넣으면 여기서 곧바로 드러난다(EOS-25 보류 집행).
    """

    def __init__(self, pool: list[SchemaProblem]) -> None:
        self._pool = pool
        self.execute_calls = 0

    async def execute(self, _stmt: Any) -> _Result:
        self.execute_calls += 1
        if self.execute_calls > 1:
            raise AssertionError(
                "1차 후보 풀 외의 직접 조회 — 수능 모드는 콘텐츠를 다시 고르지 않는다(EOS-25)"
            )
        return _Result([_OrmRow(p) for p in self._pool])


class _Env:
    """정책이 부르는 조회 대역 묶음 — 호출 사실을 센다."""

    def __init__(
        self,
        *,
        anchor_reason: RecommendationReason,
        prereqs: list[PrerequisiteRow] | None = None,
        successors: list[SuccessorRow] | None = None,
        concept_reasons: dict[uuid.UUID, RecommendationReason] | None = None,
        hang: bool = False,
    ) -> None:
        self.anchor_reason = anchor_reason
        self.prereqs = prereqs or []
        self.successors = successors or []
        self.concept_reasons = concept_reasons or {}
        self.hang = hang
        self.graph_calls = 0
        self.reason_calls: list[uuid.UUID | None] = []

    async def history(self, _s: object, _u: uuid.UUID) -> AttemptHistoryState:
        return AttemptHistoryState(
            attempted_ids=set(),
            theta=0.0,
            standard_error=None,
            measurement_sufficient=False,
            administered_count=0,
        )

    async def reason(
        self, _s: object, *, learner_id: uuid.UUID, problem_id: uuid.UUID | None
    ) -> RecommendationReason:
        self.reason_calls.append(problem_id)
        return self.anchor_reason if problem_id is not None else no_candidate_reason()

    async def fetch_prerequisites(
        self, _s: object, concept_id: uuid.UUID, *, max_depth: int = 1
    ) -> list[PrerequisiteRow]:
        self.graph_calls += 1
        if self.hang:
            await asyncio.sleep(1.0)
        return self.prereqs

    async def load_direct_successors(
        self, _s: object, concept_id: uuid.UUID, *, max_nodes: int
    ) -> list[SuccessorRow]:
        self.graph_calls += 1
        if self.hang:
            await asyncio.sleep(1.0)
        return self.successors

    async def collect_concept_reason(
        self, _s: object, *, learner_id: uuid.UUID, concept_id: uuid.UUID
    ) -> RecommendationReason:
        return self.concept_reasons[concept_id]


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Any:
    def _install(**kw: Any) -> _Env:
        e = _Env(**kw)
        monkeypatch.setattr(suneung_module, "load_attempt_history_state", e.history)
        monkeypatch.setattr(suneung_module, "collect_recommendation_reason", e.reason)
        monkeypatch.setattr(policy_module, "fetch_prerequisites", e.fetch_prerequisites)
        monkeypatch.setattr(policy_module, "load_direct_successors", e.load_direct_successors)
        monkeypatch.setattr(policy_module, "collect_concept_reason", e.collect_concept_reason)
        return e

    return _install


async def _run(
    pool: list[SchemaProblem],
    mastery: dict[str, float] | None = None,
    *,
    budget: ConceptGraphBudget | None = None,
) -> tuple[NextProblemOutcome, _PoolSession]:
    session = _PoolSession(pool)
    kwargs: dict[str, Any] = {}
    if budget is not None:
        kwargs["graph_budget"] = budget
    policy = SuneungRecommendationPolicy(
        session,  # type: ignore[arg-type]
        persona=Persona.A_일반고고3,
        **kwargs,
    )
    outcome = await policy(_state(mastery), LearningContext(mode="suneung"))
    return outcome, session


def _assert_aligned(outcome: NextProblemOutcome) -> None:
    """산출이 정렬 계약을 **독립적으로** 만족하는지 다시 판정한다(생성 검증기와 별개로)."""
    check_intent_alignment(
        problem_id=outcome.problem_id,
        action=outcome.action,
        reason_concept_id=outcome.reason.concept_id,
        target_concept=outcome.target_concept,
        delivered_concept=outcome.delivered_concept,
    )


def _assert_first_pass_delivered(
    outcome: NextProblemOutcome, first: SchemaProblem, session: _PoolSession
) -> None:
    """콘텐츠 불변 — 전달 문항이 1차 선택 문항이고, 목표 개념 후보를 다시 읽지 않았다."""
    assert outcome.problem_id == first.problem_id
    assert outcome.delivered_concept == _ANCHOR  # 1차 문항의 대표 개념(앵커) 그대로
    assert outcome.target_concept == outcome.delivered_concept
    assert session.execute_calls == 1
    # 소급 평가 재료도 1차 선택의 비교 집합 그대로다(재선택 집합이 섞이지 않는다).
    assert [pid for pid, _ in outcome.candidate_scores] == [first.problem_id]


# ──────────────────────────────────────────────────────────────────────────
# ① 세 결함 형태의 재주입 — 설명이 전달 문항과 어긋난 채로 나가지 않는다
# ──────────────────────────────────────────────────────────────────────────
class TestDefectShapesStayClosed:
    async def test_mastered_anchor_with_open_next_concept_is_withheld_not_advanced(
        self, env: Any
    ) -> None:
        """(가) — 넘어갈 다음 개념이 있어도 수능 모드는 옮기지 않는다: 현재 개념 연습 · 보류."""
        first = _problem()
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.98, confidence=0.7)
        e = env(anchor_reason=anchor, successors=[_succ(_NEXT, "UC-N")])
        outcome, session = await _run([first])
        assert outcome.action is RecommendationAction.PRACTICE_CURRENT
        assert outcome.reason.type is ReasonType.CURRENT_CONCEPT
        assert outcome.reason.mastery == 0.98  # 강등은 측정을 고치지 않는다
        assert outcome.target_concept == _ANCHOR
        assert outcome.intent_resolution is IntentResolution.MODE_WITHHELD
        assert e.graph_calls >= 1  # 의도는 실제로 판정됐다(그래프를 읽고 목표를 세웠다)
        _assert_first_pass_delivered(outcome, first, session)
        _assert_aligned(outcome)

    async def test_mastered_prerequisite_is_refuted_not_called_blocked(self, env: Any) -> None:
        """(나) — 선수가 1.0이면 '막힌 선수'가 아니다. 반증이지 보류가 아니다."""
        first = _problem()
        env(
            anchor_reason=build_reason(concept_id=_ANCHOR, mastery=0.12, confidence=0.6),
            prereqs=[_prereq(_PRE_A, "UC-P")],
        )
        outcome, session = await _run([first], {"UC-P": 1.0})
        assert outcome.action is RecommendationAction.PRACTICE_CURRENT
        assert outcome.target_concept == _ANCHOR
        assert outcome.intent_resolution is IntentResolution.REFUTED
        assert outcome.reason.mastery == 0.12
        _assert_first_pass_delivered(outcome, first, session)
        _assert_aligned(outcome)

    async def test_unmeasured_prerequisite_is_unsupported_not_a_self_pointing_action(
        self, env: Any
    ) -> None:
        """(다) — 선수가 미측정이면 근거 없음이다. 제자리를 선수라 부르지 않는다."""
        first = _problem()
        env(
            anchor_reason=build_reason(concept_id=_ANCHOR, mastery=0.12, confidence=0.6),
            prereqs=[_prereq(_PRE_A, "UC-P")],
        )
        outcome, session = await _run([first], {})
        assert outcome.action is RecommendationAction.PRACTICE_CURRENT
        assert outcome.target_concept == _ANCHOR
        assert outcome.intent_resolution is IntentResolution.UNSUPPORTED
        _assert_first_pass_delivered(outcome, first, session)
        _assert_aligned(outcome)

    async def test_weak_measured_prerequisite_is_withheld_not_reselected(self, env: Any) -> None:
        """약한 선수가 측정돼 있어도(기본 CAT이라면 그 선수 문항으로 다시 고를 상황) 옮기지 않는다."""
        first = _problem()
        env(
            anchor_reason=build_reason(concept_id=_ANCHOR, mastery=0.1, confidence=0.5),
            prereqs=[_prereq(_PRE_A, "UC-A"), _prereq(_PRE_B, "UC-B")],
        )
        outcome, session = await _run([first], {"UC-A": 0.3, "UC-B": 0.1})
        assert outcome.action is RecommendationAction.PRACTICE_CURRENT
        assert outcome.target_concept == _ANCHOR
        assert outcome.intent_resolution is IntentResolution.MODE_WITHHELD
        _assert_first_pass_delivered(outcome, first, session)
        _assert_aligned(outcome)

    async def test_anchor_that_is_the_prerequisite_of_a_blocked_concept_is_served_in_place(
        self, env: Any
    ) -> None:
        """앵커 자신이 막힌 후행의 선수 — 1차 문항이 곧 목표라 콘텐츠를 옮길 일이 없다(served).

        보류 조건은 '관계 행위'가 아니라 '콘텐츠를 옮겨야 하는가'다. 이 갈래는 옮기지 않으므로
        설명(원래 개념이 막혀서 선수를 연습한다)을 그대로 싣는다.
        """
        first = _problem()
        blocked = build_reason(concept_id=_BLOCKED, mastery=0.1, confidence=0.6)
        env(
            anchor_reason=build_reason(concept_id=_ANCHOR, mastery=0.2, confidence=0.5),
            successors=[_succ(_BLOCKED, "UC-W")],
            concept_reasons={_BLOCKED: blocked},
        )
        outcome, session = await _run([first], {"UC-W": 0.1})
        assert outcome.action is RecommendationAction.PRACTICE_PREREQUISITE
        assert outcome.reason == blocked
        assert outcome.target_concept == _ANCHOR
        assert outcome.intent_resolution is IntentResolution.SERVED
        _assert_first_pass_delivered(outcome, first, session)
        _assert_aligned(outcome)


# ──────────────────────────────────────────────────────────────────────────
# ② 보류와 다른 강등을 섞지 않는다 — "안 했다" ≠ "못 했다"
# ──────────────────────────────────────────────────────────────────────────
class TestWithheldIsDistinctFromOtherDemotions:
    async def test_every_successor_mastered_is_refuted_not_withheld(self, env: Any) -> None:
        """다음 개념이 전부 이미 숙달이면 측정이 전진을 반증한 것이다 — 모드가 보류한 게 아니다."""
        first = _problem()
        env(
            anchor_reason=build_reason(concept_id=_ANCHOR, mastery=0.98, confidence=0.7),
            successors=[_succ(_NEXT, "UC-N")],
        )
        outcome, session = await _run([first], {"UC-N": 0.95})
        assert outcome.intent_resolution is IntentResolution.REFUTED
        _assert_first_pass_delivered(outcome, first, session)

    async def test_no_successor_is_unsupported_not_withheld(self, env: Any) -> None:
        first = _problem()
        env(anchor_reason=build_reason(concept_id=_ANCHOR, mastery=0.98, confidence=0.7))
        outcome, session = await _run([first])
        assert outcome.intent_resolution is IntentResolution.UNSUPPORTED
        _assert_first_pass_delivered(outcome, first, session)

    async def test_graph_budget_of_the_policy_reaches_the_intent_resolution(
        self, env: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        """정책이 받은 그래프 예산이 의도 판정까지 전달된다 — 시간 초과는 강등이지 실패가 아니다."""
        first = _problem()
        env(
            anchor_reason=build_reason(concept_id=_ANCHOR, mastery=0.98, confidence=0.7),
            successors=[_succ(_NEXT, "UC-N")],
            hang=True,
        )
        with caplog.at_level("WARNING"):
            outcome, session = await _run([first], budget=ConceptGraphBudget(timeout_seconds=0.01))
        assert outcome.intent_resolution is IntentResolution.GRAPH_TIMEOUT
        assert "TimeoutError" in caplog.text
        _assert_first_pass_delivered(outcome, first, session)

    def test_withheld_is_its_own_wire_value(self) -> None:
        """응답·처치 기록에 실리는 문자열이 다른 해소값과 겹치지 않는다(Enum 별칭 금지)."""
        assert IntentResolution.MODE_WITHHELD.value == "mode_withheld"
        values = [member.value for member in IntentResolution]
        assert len(values) == len(set(values))


# ──────────────────────────────────────────────────────────────────────────
# ③ 관계 행위가 아닌 구간·부재 — 1차 선택 그대로이며 그래프도 읽지 않는다
# ──────────────────────────────────────────────────────────────────────────
class TestFirstPassPathsAndDeclarations:
    @pytest.mark.parametrize(
        "anchor",
        [
            build_reason(concept_id=_ANCHOR, mastery=0.55, confidence=0.5),  # 학습 구간
            build_reason(concept_id=_ANCHOR, mastery=None, confidence=None),  # 콜드스타트
            build_reason(concept_id=None, mastery=None, confidence=None),  # 미매핑
        ],
    )
    async def test_non_relational_bands_are_direct_and_read_no_graph(
        self, env: Any, anchor: RecommendationReason
    ) -> None:
        first = _problem()
        e = env(
            anchor_reason=anchor,
            prereqs=[_prereq(_PRE_A, "UC-A")],
            successors=[_succ(_NEXT, "UC-N")],
        )
        outcome, session = await _run([first], {"UC-A": 0.1})
        assert outcome.problem_id == first.problem_id
        assert outcome.reason == anchor
        assert outcome.intent_resolution is IntentResolution.DIRECT
        assert outcome.target_concept == anchor.concept_id
        assert e.graph_calls == 0
        assert session.execute_calls == 1
        _assert_aligned(outcome)

    @pytest.mark.parametrize(
        ("pool", "zero_reason"),
        [
            pytest.param([], "no_candidate_pool", id="empty-pool"),
            pytest.param(
                [_problem(signature_patterns=[])], "all_candidates_gated_ineligible", id="all-gated"
            ),
        ],
    )
    async def test_absent_recommendation_declares_no_candidate(
        self, env: Any, pool: list[SchemaProblem], zero_reason: str
    ) -> None:
        e = env(anchor_reason=no_candidate_reason())
        outcome, _session = await _run(pool)
        assert outcome.problem_id is None
        assert outcome.action is RecommendationAction.NONE
        assert outcome.reason.type is ReasonType.NO_CANDIDATE
        assert outcome.intent_resolution is IntentResolution.NO_CANDIDATE
        assert outcome.candidate_zero_reason == zero_reason
        assert e.reason_calls == [None]  # 없는 문항의 개념을 묻지 않는다
        _assert_aligned(outcome)

    def test_selection_rule_identifier_is_suneung_v2(self) -> None:
        """REC-11 식별자는 선택 규칙의 판이다 — EOS-25는 설명만 정렬해 `suneung_v1` 그대로였고,
        EOS-147이 전부 정답 이력의 표적 θ를 바꿔 `suneung_v2`로 올렸다.

        콘텐츠 재선택을 켜는 변경(EOS-35)이나 표적 규칙의 보정(EOS-39)은 선택 규칙을 다시 바꾸므로
        그때 이 값을 올리고 이 단언을 함께 고친다(소급 평가가 두 규칙의 로그를 섞지 않게).
        """
        assert SuneungRecommendationPolicy.policy_version == POLICY_VERSION_SUNEUNG == "suneung_v2"


# ──────────────────────────────────────────────────────────────────────────
# ④ 판정 전제의 동결 — 이 사실이 바뀌면 재선택 보류를 다시 판정한다
# ──────────────────────────────────────────────────────────────────────────
class TestJudgmentPremiseFreeze:
    """EOS-25가 재선택을 보류한 첫 번째 근거를 **사실로** 동결한다(현행 결함 동결 · EOS-124 ⑤ 선례).

    근거 = "수능 게이트가 학년·출제범위를 보지 않는다"(독립 비판 F1). 그 사실은 `persona_fit`이 난이도
    구간 하나만의 함수라는 데서 나온다. 초안은 이 사실을 게이트의 **조건 목록**만 보고 놓쳤다 — 게이트가
    존재한다는 것을 게이트가 작동한다는 것으로 읽었다(사고 대장 기록). 그래서 조건 목록이 아니라 **실제
    규칙 함수를 통과시킨 결과**로 동결한다. `EOS-31`이 게이트에 학년·범위를 넣으면 이 테스트가 실패한다.
    그때 재선택 보류의 근거 ①이 바뀐 것이므로 `EOS-35`(재선택 재판정)의 트리거를 확인하고 이 동결을
    올바른 값 단언으로 바꾼다.
    """

    @pytest.mark.parametrize("difficulty", [1.0, 2.5, 3.2, 3.7, 4.5])
    def test_every_labeled_problem_passes_the_suneung_gate_for_persona_a(
        self, difficulty: float
    ) -> None:
        # 기출 유형도 시그니처도 없는 문항 — 수능 신호는 적합도 규칙이 매긴 persona_fit 하나뿐이다.
        bare = _problem(signature_patterns=[], difficulty_overall=difficulty)
        fit, _rationale = derive_persona_fit(bare)
        scored = bare.model_copy(update={"persona_fit": fit})
        assert is_suneung_eligible(scored, Persona.A_일반고고3) is True, (
            "수능 게이트가 이제 라벨 있는 문항을 거른다 — EOS-31 착지로 보인다. EOS-25의 재선택 보류 "
            "근거 ①이 바뀌었으니 EOS-35(재선택 재판정)의 트리거를 확인하고 이 동결을 갱신하라."
        )
