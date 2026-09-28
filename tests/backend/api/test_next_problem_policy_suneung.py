"""EOS-25 수능 모드 추천의 설명·콘텐츠 정렬 — 오케스트레이션 단위 검증 (hermetic · DB 0).

수능 정책(`api/_next_problem_policy.py::SuneungRecommendationPolicy`)은 EOS-124가 기본 CAT에서
고친 결함을 그대로 품고 있었다(2026-09-28 재현 · main `78a8edff`). 문항을 수능 CAT으로 고른 *뒤*
그 문항 개념의 숙달 구간으로 행위를 붙이고, 목표 개념은 따로 계산했다. 그래서 세 형태가 나갔다:

  (가) 숙달 0.98 개념 문항에 `advance_next` · target = 그 개념        → 정렬 R3 위반
  (나) 선수 숙달 1.0인데 `practice_prerequisite` · target = 그 선수   → 정렬 R2 위반
  (다) 선수가 미측정인데 `practice_prerequisite` · target = 문항 개념 → 정렬 R3 위반

이 파일이 지키는 것:

① **세 형태가 다시 나오지 않는다** — 산출이 정렬을 선언하고(`intent_resolution`), 생성 시점
   검증기가 그것을 강제한다. 아래 테스트는 세 형태의 입력을 그대로 재주입한다.
② **재선택은 수능 모드 안에서만** — 재선택 후보에도 L6 진실 게이트(`is_suneung_eligible`)가
   똑같이 걸린다. 사전필터를 통과한 행이라도 게이트가 막으면 고르지 않는다(검수·페르소나는
   게이트만 본다). 목표에 적격 문항이 없으면 모드를 벗어나지 않고 정직 강등한다.
③ **수능 장치가 재선택에도 그대로 작동한다** — 페르소나 · 수능 우선순위 가중 · 학습 밴드 ·
   미응답/형제 배제가 1차 선택과 같은 값으로 전달된다.

조회는 전부 대역이다: 1차 후보 풀만 세션 대역이 돌려주고(`execute`는 **한 번만** 허용 — 예상하지
않은 직접 SQL이 끼면 여기서 터진다), 나머지는 모듈 이름을 바꿔 끼운다. SQL 자체가 옳은 행을 내는지는
`test_eos25_suneung_alignment_integration.py`(실 PG)가 본다.

**변별력 확인**: `scripts/analysis/mutate_eos25_suneung_alignment_guards.py`가 결함 형태를 되살리는
뮤테이션을 주입해 이 파일이 RED가 되는지 본다(CLAUDE.md "보호 장치를 실패 주입 없이 선언 금지").
"""

from __future__ import annotations

import asyncio
import math
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from whymath_backend.api import _next_problem_policy as suneung_module
from whymath_backend.api._next_problem_policy import SuneungRecommendationPolicy
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
from whymath_backend.schema.enums import (
    Curriculum,
    ExamType,
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
_ATTEMPTED = uuid.UUID(int=1)


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


def _no_signal(**over: Any) -> SchemaProblem:
    """수능 신호가 전혀 없는 문항 — 기본 CAT 풀에는 있지만 수능 게이트는 막는다."""
    return _problem(signature_patterns=[], **over)


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

    나머지 조회(이력·근거·그래프·재선택 후보·약점 가중)는 전부 모듈 이름 교체로 대역한다. 그래서
    정책이 대역을 거치지 않는 새 SQL을 끼워 넣으면 여기서 곧바로 드러난다.
    """

    def __init__(self, pool: list[SchemaProblem]) -> None:
        self._pool = pool
        self.execute_calls = 0

    async def execute(self, _stmt: Any) -> _Result:
        self.execute_calls += 1
        if self.execute_calls > 1:
            raise AssertionError("1차 후보 풀 외의 직접 조회 — 대역을 거치지 않는 SQL이 생겼다")
        return _Result([_OrmRow(p) for p in self._pool])


class _Env:
    """정책이 부르는 조회 대역 묶음 — 호출 인자를 캡처한다."""

    def __init__(
        self,
        *,
        anchor_reason: RecommendationReason,
        prereqs: list[PrerequisiteRow] | None = None,
        successors: list[SuccessorRow] | None = None,
        target_rows: list[tuple[SchemaProblem, uuid.UUID]] | None = None,
        concept_reasons: dict[uuid.UUID, RecommendationReason] | None = None,
        weak_weights: dict[uuid.UUID, float] | None = None,
        sibling_ids: set[uuid.UUID] | None = None,
        hang: bool = False,
    ) -> None:
        self.anchor_reason = anchor_reason
        self.prereqs = prereqs or []
        self.successors = successors or []
        self.target_rows = target_rows or []
        self.concept_reasons = concept_reasons or {}
        self.weak_weights = weak_weights or {}
        self.sibling_ids = sibling_ids or set()
        self.hang = hang
        self.target_calls: list[dict[str, Any]] = []
        self.graph_calls = 0
        self.reason_calls: list[uuid.UUID | None] = []

    async def history(self, _s: object, _u: uuid.UUID) -> AttemptHistoryState:
        return AttemptHistoryState(
            attempted_ids={_ATTEMPTED},
            theta=0.0,
            standard_error=None,
            measurement_sufficient=False,
            administered_count=1,
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

    async def target_candidates(
        self, _s: object, theta: float, **kw: Any
    ) -> list[tuple[SchemaProblem, uuid.UUID]]:
        self.target_calls.append(kw)
        wanted = set(kw["concept_ids"])
        return [(p, c) for p, c in self.target_rows if c in wanted]

    async def weak(self, _s: object, _u: uuid.UUID, pids: list[uuid.UUID]) -> list[float]:
        return [self.weak_weights.get(pid, 1.0) for pid in pids]

    async def last_wrong(self, _s: object, _u: uuid.UUID) -> uuid.UUID | None:
        return uuid.uuid4() if self.sibling_ids else None

    async def siblings(self, _s: object, _p: uuid.UUID) -> set[uuid.UUID]:
        return self.sibling_ids


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Any:
    def _install(**kw: Any) -> _Env:
        e = _Env(**kw)
        monkeypatch.setattr(suneung_module, "load_attempt_history_state", e.history)
        monkeypatch.setattr(suneung_module, "collect_recommendation_reason", e.reason)
        monkeypatch.setattr(suneung_module, "load_suneung_target_candidates", e.target_candidates)
        monkeypatch.setattr(suneung_module, "load_weak_concept_weights", e.weak)
        monkeypatch.setattr(suneung_module, "last_incorrect_problem_id", e.last_wrong)
        monkeypatch.setattr(suneung_module, "load_sibling_ids", e.siblings)
        monkeypatch.setattr(policy_module, "fetch_prerequisites", e.fetch_prerequisites)
        monkeypatch.setattr(policy_module, "load_direct_successors", e.load_direct_successors)
        monkeypatch.setattr(policy_module, "collect_concept_reason", e.collect_concept_reason)
        return e

    return _install


async def _run(
    pool: list[SchemaProblem],
    mastery: dict[str, float] | None = None,
    *,
    persona: Persona = Persona.A_일반고고3,
    context: LearningContext | None = None,
    sibling_filter: str | None = None,
    budget: ConceptGraphBudget | None = None,
) -> NextProblemOutcome:
    kwargs: dict[str, Any] = {"persona": persona, "sibling_filter": sibling_filter}
    if budget is not None:
        kwargs["graph_budget"] = budget
    policy = SuneungRecommendationPolicy(_PoolSession(pool), **kwargs)  # type: ignore[arg-type]
    return await policy(_state(mastery), context or LearningContext(mode="suneung"))


def _assert_aligned(outcome: NextProblemOutcome) -> None:
    """산출이 정렬 계약을 **독립적으로** 만족하는지 다시 판정한다(생성 검증기와 별개로)."""
    check_intent_alignment(
        problem_id=outcome.problem_id,
        action=outcome.action,
        reason_concept_id=outcome.reason.concept_id,
        target_concept=outcome.target_concept,
        delivered_concept=outcome.delivered_concept,
    )


# ──────────────────────────────────────────────────────────────────────────
# ① 세 결함 형태의 재주입 — 설명이 전달 문항과 어긋난 채로 나가지 않는다
# ──────────────────────────────────────────────────────────────────────────
class TestDefectShapesStayClosed:
    async def test_mastered_anchor_advances_to_a_suneung_problem_of_the_next_concept(
        self, env: Any
    ) -> None:
        """(가) — 숙달 0.98 개념이 1차 선택돼도 다음 개념의 **수능 적격** 문항이 나간다."""
        first, nxt = _problem(), _problem(difficulty_overall=4.0)
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.98, confidence=0.7)
        e = env(
            anchor_reason=anchor,
            successors=[_succ(_NEXT, "UC-N")],
            target_rows=[(nxt, _NEXT)],
        )
        outcome = await _run([first])
        assert outcome.problem_id == nxt.problem_id
        assert outcome.action is RecommendationAction.ADVANCE_NEXT
        assert outcome.target_concept == _NEXT
        assert outcome.delivered_concept == _NEXT
        assert outcome.reason == anchor  # 전진의 근거는 숙달한 현재 개념
        assert outcome.intent_resolution is IntentResolution.SERVED
        assert outcome.difficulty == 4.0
        # 소급 평가 재료는 *그 문항을 고른* 비교 집합이다(전달 문항이 들어 있다).
        assert [pid for pid, _ in outcome.candidate_scores] == [nxt.problem_id]
        assert e.target_calls[0]["concept_ids"] == [_NEXT]
        _assert_aligned(outcome)

    async def test_mastered_prerequisite_is_refuted_not_called_blocked(self, env: Any) -> None:
        """(나) — 선수가 1.0이면 '막힌 선수'가 아니다. 1차 문항에 현재 개념 연습으로 강등."""
        first = _problem()
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.12, confidence=0.6)
        e = env(anchor_reason=anchor, prereqs=[_prereq(_PRE_A, "UC-P")])
        outcome = await _run([first], {"UC-P": 1.0})
        assert outcome.problem_id == first.problem_id
        assert outcome.action is RecommendationAction.PRACTICE_CURRENT
        assert outcome.target_concept == _ANCHOR
        assert outcome.intent_resolution is IntentResolution.REFUTED
        assert outcome.reason.mastery == 0.12  # 강등은 측정을 고치지 않는다
        assert e.target_calls == []  # 재선택할 목표가 없다
        _assert_aligned(outcome)

    async def test_unmeasured_prerequisite_is_unsupported_not_a_self_pointing_action(
        self, env: Any
    ) -> None:
        """(다) — 선수가 미측정이면 반증이 아니라 근거 없음이다. 제자리를 선수라 부르지 않는다."""
        first = _problem()
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.12, confidence=0.6)
        env(anchor_reason=anchor, prereqs=[_prereq(_PRE_A, "UC-P")])
        outcome = await _run([first], {})
        assert outcome.problem_id == first.problem_id
        assert outcome.action is RecommendationAction.PRACTICE_CURRENT
        assert outcome.target_concept == _ANCHOR
        assert outcome.intent_resolution is IntentResolution.UNSUPPORTED
        _assert_aligned(outcome)

    async def test_weak_prerequisite_is_served_weakest_first(self, env: Any) -> None:
        """약한 선수가 둘이면 **가장 약한 것**부터 — 거기 수능 문항이 없으면 다음 약한 선수로."""
        first, pre_a = _problem(), _problem()
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.1, confidence=0.5)
        e = env(
            anchor_reason=anchor,
            prereqs=[_prereq(_PRE_A, "UC-A"), _prereq(_PRE_B, "UC-B")],
            target_rows=[(pre_a, _PRE_A)],  # 가장 약한 B에는 수능 문항이 없다
        )
        outcome = await _run([first], {"UC-A": 0.3, "UC-B": 0.1})
        assert outcome.problem_id == pre_a.problem_id
        assert outcome.action is RecommendationAction.PRACTICE_PREREQUISITE
        assert outcome.target_concept == _PRE_A
        assert outcome.reason == anchor  # 근거는 막힌 원래 개념
        assert outcome.intent_resolution is IntentResolution.SERVED
        # 조회는 한 번 — 두 목표 개념을 약한 순서로 한꺼번에 읽는다.
        assert len(e.target_calls) == 1
        assert e.target_calls[0]["concept_ids"] == [_PRE_B, _PRE_A]
        _assert_aligned(outcome)

    async def test_anchor_that_is_the_prerequisite_of_a_blocked_concept_keeps_its_problem(
        self, env: Any
    ) -> None:
        """앵커 자신이 막힌 후행의 선수 — 근거는 그 후행으로 옮기고 1차 문항이 곧 목표다."""
        first = _problem()
        blocked = build_reason(concept_id=_BLOCKED, mastery=0.1, confidence=0.6)
        e = env(
            anchor_reason=build_reason(concept_id=_ANCHOR, mastery=0.2, confidence=0.5),
            successors=[_succ(_BLOCKED, "UC-W")],
            concept_reasons={_BLOCKED: blocked},
        )
        outcome = await _run([first], {"UC-W": 0.1})
        assert outcome.problem_id == first.problem_id
        assert outcome.action is RecommendationAction.PRACTICE_PREREQUISITE
        assert outcome.reason == blocked
        assert outcome.target_concept == _ANCHOR
        assert outcome.intent_resolution is IntentResolution.SERVED
        assert e.target_calls == []
        _assert_aligned(outcome)


# ──────────────────────────────────────────────────────────────────────────
# ② 재선택은 수능 모드 안에서만 — 진실 게이트·정직 강등
# ──────────────────────────────────────────────────────────────────────────
class TestReselectionStaysInSuneungMode:
    async def test_target_without_suneung_problem_demotes_instead_of_leaving_the_mode(
        self, env: Any
    ) -> None:
        """목표 개념에 수능 적격 문항이 없다 — 1차 문항을 내보내되 전진을 말하지 않는다."""
        first = _problem()
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.98, confidence=0.7)
        env(anchor_reason=anchor, successors=[_succ(_NEXT, "UC-N")], target_rows=[])
        outcome = await _run([first])
        assert outcome.problem_id == first.problem_id
        assert outcome.action is RecommendationAction.PRACTICE_CURRENT
        assert outcome.target_concept == _ANCHOR
        assert outcome.intent_resolution is IntentResolution.TARGET_UNAVAILABLE
        assert outcome.reason.mastery == 0.98
        _assert_aligned(outcome)

    @pytest.mark.parametrize(
        "leaked",
        [
            pytest.param(lambda: _no_signal(), id="no-suneung-signal"),
            pytest.param(lambda: _problem(review_status=ReviewStatus.pending), id="unreviewed"),
            pytest.param(
                lambda: _problem(
                    source_type=SourceType.평가원, exam_type=ExamType.수능, question_text=None
                ),
                id="copyright-blocked-source",
            ),
        ],
    )
    async def test_reselection_rows_pass_the_same_truth_gate(self, env: Any, leaked: Any) -> None:
        """사전필터를 통과한 행이라도 진실 게이트가 막으면 고르지 않는다 — 모드를 벗어나지 않는다.

        대조군이 핵심이다: 새어 든 행을 **θ에 가장 가깝게**(정보량 최대) 둔다. 게이트가 재선택에서
        빠지면 그 행이 이긴다. 적격 행은 θ에서 멀어도 골라져야 한다.
        """
        first, eligible = _problem(), _problem(difficulty_overall=5.0)
        bad = leaked()
        env(
            anchor_reason=build_reason(concept_id=_ANCHOR, mastery=0.98, confidence=0.7),
            successors=[_succ(_NEXT, "UC-N")],
            target_rows=[(bad, _NEXT), (eligible, _NEXT)],
        )
        outcome = await _run([first])
        assert outcome.problem_id == eligible.problem_id
        assert {pid for pid, _ in outcome.candidate_scores} == {eligible.problem_id}

    async def test_group_whose_rows_are_all_gated_falls_through_to_the_next_group(
        self, env: Any
    ) -> None:
        """가장 약한 선수의 행이 전부 게이트에 막히면 그 묶음을 건너뛴다(None으로 끝내지 않는다)."""
        first, pre_a = _problem(), _problem()
        env(
            anchor_reason=build_reason(concept_id=_ANCHOR, mastery=0.1, confidence=0.5),
            prereqs=[_prereq(_PRE_A, "UC-A"), _prereq(_PRE_B, "UC-B")],
            target_rows=[(_no_signal(), _PRE_B), (pre_a, _PRE_A)],
        )
        outcome = await _run([first], {"UC-A": 0.3, "UC-B": 0.1})
        assert outcome.problem_id == pre_a.problem_id
        assert outcome.target_concept == _PRE_A

    async def test_only_gated_rows_mean_target_unavailable(self, env: Any) -> None:
        first = _problem()
        env(
            anchor_reason=build_reason(concept_id=_ANCHOR, mastery=0.98, confidence=0.7),
            successors=[_succ(_NEXT, "UC-N")],
            target_rows=[(_no_signal(), _NEXT)],
        )
        outcome = await _run([first])
        assert outcome.problem_id == first.problem_id
        assert outcome.intent_resolution is IntentResolution.TARGET_UNAVAILABLE

    async def test_reselection_uses_the_policy_persona(self, env: Any) -> None:
        """페르소나는 재선택 조회와 게이트 양쪽에 **같은 값**으로 간다.

        대조군: 적합도가 페르소나 A에게만 있는 행은 B 학생의 재선택에서 막혀야 한다(1차 문항은
        시그니처로 B에게도 적격이다).
        """
        first = _problem()
        fit_a_only = _no_signal(persona_fit={Persona.A_일반고고3: 0.9})
        e = env(
            anchor_reason=build_reason(concept_id=_ANCHOR, mastery=0.98, confidence=0.7),
            successors=[_succ(_NEXT, "UC-N")],
            target_rows=[(fit_a_only, _NEXT)],
        )
        outcome = await _run([first], persona=Persona.B_자사고N수)
        assert e.target_calls[0]["persona"] is Persona.B_자사고N수
        assert outcome.problem_id == first.problem_id
        assert outcome.intent_resolution is IntentResolution.TARGET_UNAVAILABLE

        e2 = env(
            anchor_reason=build_reason(concept_id=_ANCHOR, mastery=0.98, confidence=0.7),
            successors=[_succ(_NEXT, "UC-N")],
            target_rows=[(fit_a_only, _NEXT)],
        )
        served = await _run([first], persona=Persona.A_일반고고3)
        assert e2.target_calls[0]["persona"] is Persona.A_일반고고3
        assert served.problem_id == fit_a_only.problem_id


# ──────────────────────────────────────────────────────────────────────────
# ③ 수능 장치가 재선택에도 그대로 작동한다
# ──────────────────────────────────────────────────────────────────────────
class TestSuneungDevicesApplyToReselection:
    async def test_suneung_priority_weight_ranks_the_target_candidates(self, env: Any) -> None:
        """같은 난이도면 수능 기출(권위 1.0)이 시그니처만 있는 문항보다 앞선다(우선순위 가중)."""
        first = _problem()
        plain = _problem()
        authority = _problem(exam_type=ExamType.수능, exam_authority_weight=1.0)
        env(
            anchor_reason=build_reason(concept_id=_ANCHOR, mastery=0.98, confidence=0.7),
            successors=[_succ(_NEXT, "UC-N")],
            target_rows=[(plain, _NEXT), (authority, _NEXT)],
        )
        outcome = await _run([first])
        assert outcome.problem_id == authority.problem_id
        scores = dict(outcome.candidate_scores)
        # 정보량(θ=0·b=0 → 0.25) × (1 + 우선순위) — 권위 2.0 + 시그니처 1.0 + 난이도 3.0 = 6.0.
        assert math.isclose(scores[authority.problem_id], 0.25 * 7.0)
        assert math.isclose(scores[plain.problem_id], 0.25 * 5.0)

    async def test_learning_band_applies_to_reselection(self, env: Any) -> None:
        """purpose=learning이면 재선택도 학습 밴드로 고른다(정보량 최대가 아니라)."""
        first = _problem()
        band_b = -math.log(0.8 / 0.2)  # θ=0에서 정답 확률 0.8(밴드 안)
        mid = _problem(irt_difficulty_b=0.0)
        banded = _problem(irt_difficulty_b=band_b)
        env(
            anchor_reason=build_reason(concept_id=_ANCHOR, mastery=0.98, confidence=0.7),
            successors=[_succ(_NEXT, "UC-N")],
            target_rows=[(mid, _NEXT), (banded, _NEXT)],
        )
        outcome = await _run([first], context=LearningContext(mode="suneung", purpose="learning"))
        assert outcome.problem_id == banded.problem_id
        assert outcome.band_calibrated is False

    async def test_reselection_excludes_attempted_and_sibling_problems(self, env: Any) -> None:
        """재선택 조회도 미응답·형제 배제를 1차 선택과 같은 값으로 받는다."""
        first = _problem()
        sibling = uuid.uuid4()
        e = env(
            anchor_reason=build_reason(concept_id=_ANCHOR, mastery=0.98, confidence=0.7),
            successors=[_succ(_NEXT, "UC-N")],
            target_rows=[],
            sibling_ids={sibling},
        )
        await _run([first], sibling_filter="exclude")
        assert e.target_calls[0]["attempted_ids"] == {_ATTEMPTED}
        assert e.target_calls[0]["excluded_ids"] == {sibling}

    async def test_include_sibling_filter_does_not_exclude(self, env: Any) -> None:
        """형제 필터 include는 배제가 아니라 가중이다 — 재선택 조회에서 빼지 않는다."""
        first = _problem()
        e = env(
            anchor_reason=build_reason(concept_id=_ANCHOR, mastery=0.98, confidence=0.7),
            successors=[_succ(_NEXT, "UC-N")],
            target_rows=[],
            sibling_ids={uuid.uuid4()},
        )
        await _run([first], sibling_filter="include")
        assert e.target_calls[0]["excluded_ids"] == set()

    async def test_weak_signal_counts_only_the_weak_axis(self, env: Any) -> None:
        """약점 신호 수는 **약점 가중만** 센다 — 밴드 가중을 곱한 뒤 세면 값이 부풀려진다.

        EOS-19 이동 전 핸들러와 같은 정의다(1차 선택 관측 불변). 약점 가중이 전부 1.0이고 밴드만
        1.0이 아닌 요청에서 0이어야 한다.
        """
        first, second = _problem(irt_difficulty_b=0.0), _problem(irt_difficulty_b=1.5)
        env(anchor_reason=build_reason(concept_id=_ANCHOR, mastery=0.55, confidence=0.5))
        outcome = await _run(
            [first, second],
            context=LearningContext(
                mode="suneung", purpose="learning", prioritize_weak_concepts=True
            ),
        )
        assert outcome.weak_concept_signal_count == 0
        assert outcome.applied_weights is True


# ──────────────────────────────────────────────────────────────────────────
# ④ 관계 행위가 아닌 구간·부재·예산 — 1차 선택 그대로이며 조회가 늘지 않는다
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
            target_rows=[(_problem(), _NEXT)],
        )
        outcome = await _run([first], {"UC-A": 0.1})
        assert outcome.problem_id == first.problem_id
        assert outcome.intent_resolution is IntentResolution.DIRECT
        assert outcome.target_concept == anchor.concept_id
        assert e.graph_calls == 0 and e.target_calls == []
        _assert_aligned(outcome)

    @pytest.mark.parametrize(
        ("pool", "zero_reason"),
        [
            pytest.param([], "no_candidate_pool", id="empty-pool"),
            pytest.param([_no_signal()], "all_candidates_gated_ineligible", id="all-gated"),
        ],
    )
    async def test_absent_recommendation_declares_no_candidate(
        self, env: Any, pool: list[SchemaProblem], zero_reason: str
    ) -> None:
        e = env(anchor_reason=no_candidate_reason())
        outcome = await _run(pool)
        assert outcome.problem_id is None
        assert outcome.action is RecommendationAction.NONE
        assert outcome.reason.type is ReasonType.NO_CANDIDATE
        assert outcome.intent_resolution is IntentResolution.NO_CANDIDATE
        assert outcome.candidate_zero_reason == zero_reason
        assert e.reason_calls == [None]  # 없는 문항의 개념을 묻지 않는다
        _assert_aligned(outcome)

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
            outcome = await _run([first], budget=ConceptGraphBudget(timeout_seconds=0.01))
        assert outcome.problem_id == first.problem_id
        assert outcome.intent_resolution is IntentResolution.GRAPH_TIMEOUT
        assert "TimeoutError" in caplog.text

    def test_policy_version_marks_the_new_selection_rule(self) -> None:
        """선택 규칙이 바뀌었으므로 식별자도 바뀐다(REC-11) — v1 로그와 섞어 평가하지 않는다."""
        assert SuneungRecommendationPolicy.policy_version == POLICY_VERSION_SUNEUNG == "suneung_v2"
