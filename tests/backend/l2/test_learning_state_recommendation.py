"""EOS-24 · EOS-26 — 추천이 학습 상태 머신의 결정을 **집행**하는가 (hermetic · DB 0).

설계 정본: `docs/reviews/eos24_recommendation_reads_learning_state_judgment_2026-09-25.md`(R3) ·
`docs/reviews/eos26_r6_diagnosis_prerequisite_directed_judgment_2026-09-26.md`(R6 — 파일 끝 ⑤~⑦절).

이 파일이 지키는 넷:

① **무엇을 지시로 읽는가** — R3(`POLICY_REMEDIATE_MISCONCEPTION`)로 들어간 `REMEDIATING`만.
   R5의 `REMEDIATING`·PRACTICING·ADVANCING은 지시가 아니다(판정문 §3). 국면과 트리거를 **둘 다**
   본다 — 한쪽만 보는 뮤테이션을 잡는 반례가 각각 있다.
② **안전장치 4개가 실제로 막는가** — 교정 국면에서의 재실패(해제) · 이번 회차 가설 없음(회차 경계 =
   직전 다른 응답의 마지막 원장 전이 — EOS-140)/하한 이하
   (신뢰 경계는 *리터럴*로 밟는다 — 상수를 import해 픽스처를 만들면 경계가 움직일 때 픽스처도 따라
   움직여 검출이 불가능하다 · MISC-30 1차 실행 교훈) · 교정 대상 개념 미해소 · 개념 안 후보 0.
③ **지시가 없으면 조회 0건** — 대다수 요청이 전환 전과 같은 쿼리 수·같은 결과를 낸다.
④ **정책 이음매** — 집행되면 후보·근거·목표·밴드·정책 버전이 전부 상태 경로에서 오고, 집행되지
   않으면 전환 전 경로를 그대로 탄다(지시 결과는 어느 쪽이든 응답에 실린다).

실 PG·HTTP 경로 단언은 `tests/backend/api/test_eos24_recommendation_follows_learning_state.py`가
전담한다(acceptance ③).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.l2 import learning_state_recommendation as lsr
from whymath_backend.l2 import recommendation_policy as policy_module
from whymath_backend.l2.learner_state import LearnerState, LearningStateSnapshot
from whymath_backend.l2.next_problem_selection import CANDIDATE_POOL_SIZE, AttemptHistoryState
from whymath_backend.l2.prerequisite_recommendation import PrerequisiteRow
from whymath_backend.l2.recommendation_contract import (
    LearningContext,
    ReasonBasis,
    ReasonType,
    Recommendation,
    RecommendationAction,
    RecommendationReason,
    action_for,
    build_reason,
    remediation_reason,
)
from whymath_backend.l2.recommendation_evidence import (
    POLICY_VERSION_CAT,
    POLICY_VERSION_CAT_STATE_REMEDIATION,
    POLICY_VERSION_CAT_STATE_UNDIAGNOSED,
)
from whymath_backend.l2.recommendation_policy import (
    CatRecommendationPolicy,
    ConceptGraphBudget,
    IntentResolution,
    PolicyIntent,
)
from whymath_backend.schema.learning_state import LearningState, TransitionTrigger

_UID = uuid.uuid4()
_ATTEMPT = uuid.uuid4()
_PROBLEM = uuid.uuid4()
_CONCEPT = uuid.uuid4()

R3 = TransitionTrigger.POLICY_REMEDIATE_MISCONCEPTION
R5 = TransitionTrigger.POLICY_REPEATED_FAILURE


def _state(snapshot: LearningStateSnapshot | None) -> LearnerState:
    """학습 국면만 채운 최소 `LearnerState` — 이 파일이 재는 것은 국면 → 지시다."""
    return LearnerState(
        student_id=str(_UID),
        timestamp=datetime.now(UTC),
        mastery={},
        general_ability=None,
        domain_abilities={},
        active_misconceptions=[],
        recent_struggles=[],
        recent_successes=[],
        grade=None,
        goals={},
        learning_state=snapshot,
    )


def _remediating(
    *,
    trigger: TransitionTrigger = R3,
    state: LearningState = LearningState.REMEDIATING,
    assessed_from: LearningState | None = LearningState.LEARNING,
    attempt_id: uuid.UUID | None = _ATTEMPT,
) -> LearnerState:
    return _state(
        LearningStateSnapshot(
            state=state,
            trigger=trigger,
            rule_id="R3-wrong-misconception" if trigger is R3 else None,
            attempt_id=attempt_id,
            assessed_from=assessed_from,
        )
    )


# ── 순서 큐 세션 — 이 모듈의 조회는 순서가 결정론이다(가설 → 응답 → 후보) ─────────────────
class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return list(self._rows)


@dataclass
class _QueueSession:
    """`execute`가 큐를 순서대로 소비한다. **마르면 IndexError** — 조회가 늘면 반드시 발각된다."""

    results: list[list[Any]]
    statements: list[Any] = field(default_factory=list)

    async def execute(self, stmt: Any) -> _Result:
        self.statements.append(stmt)
        return _Result(self.results.pop(0))


def _session(*results: list[Any]) -> tuple[_QueueSession, AsyncSession]:
    fake = _QueueSession(list(results))
    return fake, cast(AsyncSession, fake)


@pytest.fixture
def anchored(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """대표 개념 조회를 대역으로 — 그 좌석(PRIMARY→TESTED 폴백)은 숙달 모듈이 전담해 검증한다."""
    seen: list[uuid.UUID] = []

    async def _primary(_session: Any, problem_id: uuid.UUID) -> uuid.UUID | None:
        seen.append(problem_id)
        return _CONCEPT

    monkeypatch.setattr(lsr, "get_primary_concept_id", _primary)
    return seen


async def _no_prerequisite_read(concept_id: uuid.UUID, max_depth: int) -> list[Any]:
    """R3 경로는 선수를 읽지 않는다 — 읽으면 그 자체가 결함이다(EOS-26 이후 이음매 공용 인자)."""
    raise AssertionError(f"R3 경로가 선수를 읽었다: concept={concept_id} depth={max_depth}")


async def _route(learner_state: LearnerState, session: AsyncSession) -> lsr.StateRoute | None:
    return await lsr.route_by_learning_state(
        session,
        learner_state,
        theta=-1.0,
        attempted_ids=set(),
        excluded_ids=set(),
        read_prerequisites=_no_prerequisite_read,
    )


# ──────────────────────────────────────────────────────────────────────────
# ① 무엇을 지시로 읽는가
# ──────────────────────────────────────────────────────────────────────────
class TestReadRemediationDirective:
    def test_r3_remediating_is_a_directive(self) -> None:
        directive = lsr.read_remediation_directive(_remediating())
        assert directive == lsr.RemediationDirective(
            attempt_id=_ATTEMPT, repeated_in_remediation=False
        )

    def test_unassembled_state_is_not_a_directive(self) -> None:
        """조립기를 거치지 않은 상태(None)를 '지시 있음'으로 읽지 않는다."""
        assert lsr.read_remediation_directive(_state(None)) is None

    def test_empty_ledger_is_not_a_directive(self) -> None:
        empty = _state(LearningStateSnapshot(state=LearningState.NEW))
        assert lsr.read_remediation_directive(empty) is None

    def test_repeated_failure_remediating_is_not_a_directive(self) -> None:
        """R5의 REMEDIATING — **국면만 보는** 뮤테이션의 반례(판정문 §3: 선수 하강을 막지 않는다)."""
        assert lsr.read_remediation_directive(_remediating(trigger=R5)) is None

    def test_r3_trigger_outside_remediating_is_not_a_directive(self) -> None:
        """트리거가 R3여도 국면이 바뀌었으면 지시가 아니다 — **트리거만 보는** 뮤테이션의 반례."""
        assert lsr.read_remediation_directive(_remediating(state=LearningState.LEARNING)) is None

    @pytest.mark.parametrize(
        ("assessed_from", "repeated"),
        [
            (LearningState.REMEDIATING, True),
            (LearningState.LEARNING, False),
            (LearningState.PRACTICING, False),
            (None, False),  # 짝 행을 못 찾았으면 "재실패"라고 단정하지 않는다
        ],
    )
    def test_repeat_in_remediation_is_read_from_assessed_from(
        self, assessed_from: LearningState | None, repeated: bool
    ) -> None:
        directive = lsr.read_remediation_directive(_remediating(assessed_from=assessed_from))
        assert directive is not None
        assert directive.repeated_in_remediation is repeated


# ──────────────────────────────────────────────────────────────────────────
# ② 안전장치 · ③ 지시가 없으면 조회 0건
# ──────────────────────────────────────────────────────────────────────────
class TestRouteByLearningState:
    async def test_no_directive_issues_no_query(self) -> None:
        fake, session = _session()  # 빈 큐 — 조회가 한 건이라도 나가면 IndexError
        assert (
            await _route(_state(LearningStateSnapshot(state=LearningState.PRACTICING)), session)
            is None
        )
        assert fake.statements == []

    async def test_repeat_in_remediation_releases_without_query(self) -> None:
        """안전장치 ③ — 교정 1문항이 이미 실패했다. 가설을 다시 묻지 않고 곧장 해제한다."""
        fake, session = _session()
        route = await _route(_remediating(assessed_from=LearningState.REMEDIATING), session)
        assert route == lsr.StateRoute(outcome=lsr.StateDirectiveOutcome.RELEASED_AFTER_REPEAT)
        assert fake.statements == []

    async def test_no_fresh_hypothesis_is_weak_evidence(self) -> None:
        """안전장치 ① — 이번 회차에 확인된 가설이 없다(옛 가설로 고정하지 않는다)."""
        fake, session = _session([])
        route = await _route(_remediating(), session)
        assert route is not None
        assert route.outcome is lsr.StateDirectiveOutcome.WEAK_MISCONCEPTION_EVIDENCE
        assert len(fake.statements) == 1

    @pytest.mark.parametrize("confidence", [0.70, 0.5, 0.15])
    async def test_confidence_at_or_below_floor_is_weak(self, confidence: float) -> None:
        """안전장치 ② — 하한 **이하**는 집행하지 않는다. 0.70(경계 자체)이 핵심 반례다."""
        _fake, session = _session([confidence])
        route = await _route(_remediating(), session)
        assert route is not None
        assert route.outcome is lsr.StateDirectiveOutcome.WEAK_MISCONCEPTION_EVIDENCE

    async def test_confidence_just_above_floor_proceeds(self, anchored: list[uuid.UUID]) -> None:
        """0.71 — 하한 *초과*의 반례. `>=`나 `>` 뒤바뀜 뮤테이션을 0.70과 함께 가른다."""
        _fake, session = _session([0.71], [_PROBLEM], [(_PROBLEM, 3.0, None)])
        route = await _route(_remediating(), session)
        assert route is not None and route.applied

    async def test_hypothesis_query_asks_for_this_turns_evidence_only(self) -> None:
        """①의 집행 — 조회 문장이 `turns_since_evidence = 0`과 활성 조건을 실제로 싣는가."""
        fake, session = _session([])
        await _route(_remediating(), session)
        sql = str(fake.statements[0].compile(dialect=postgresql.dialect()))
        assert "misconception_hypothesis.turns_since_evidence =" in sql
        assert "misconception_hypothesis.is_active IS true" in sql
        assert "misconception_hypothesis.user_id =" in sql

    async def test_hypothesis_query_bounds_the_turn_by_the_previous_attempt(self) -> None:
        """①의 회차 경계(EOS-140) — tse=0만으로는 미스캔 회차에서 옛 가설이 '방금'으로 읽힌다.

        조회가 **직전 다른 응답의 마지막 원장 전이 이후에 갱신된 가설**로 좁혀지는가를 문장으로
        고정한다. 실제로 옛 가설을 걸러내는지는 실 PG 반례
        (`test_eos24_recommendation_follows_learning_state.py::test_stale_hypothesis_*`)가 판정한다.
        """
        fake, session = _session([])
        await _route(_remediating(), session)
        stmt = fake.statements[0]
        compiled = stmt.compile(dialect=postgresql.dialect())
        sql = str(compiled)
        assert len(fake.statements) == 1  # 경계는 서브쿼리다 — 조회 수가 늘지 않는다
        assert "max(learning_state_transition.occurred_at)" in sql
        assert "learning_state_transition.user_id =" in sql
        assert "learning_state_transition.attempt_id !=" in sql  # NULL 행도 이 비교가 뺀다
        assert "misconception_hypothesis.updated_at >" in sql
        # 경계에서 빠지는 것은 **결정 응답 자신**의 행이다(그 행은 이번 스캔 뒤에 적재된다).
        assert _ATTEMPT in compiled.params.values()

    async def test_missing_attempt_keeps_the_unbounded_query(self) -> None:
        """결정 응답을 모르면 경계를 잡을 수 없다 — 그래도 집행되지 않는다(바로 뒤 앵커 미해소)."""
        fake, session = _session([0.9])
        route = await _route(_remediating(attempt_id=None), session)
        sql = str(fake.statements[0].compile(dialect=postgresql.dialect()))
        assert "learning_state_transition" not in sql
        assert route is not None
        assert route.outcome is lsr.StateDirectiveOutcome.ANCHOR_UNRESOLVED

    async def test_missing_attempt_is_anchor_unresolved(self) -> None:
        _fake, session = _session([0.9])
        route = await _route(_remediating(attempt_id=None), session)
        assert route is not None
        assert route.outcome is lsr.StateDirectiveOutcome.ANCHOR_UNRESOLVED

    async def test_attempt_not_found_is_anchor_unresolved(self, anchored: list[uuid.UUID]) -> None:
        _fake, session = _session([0.9], [])
        route = await _route(_remediating(), session)
        assert route is not None
        assert route.outcome is lsr.StateDirectiveOutcome.ANCHOR_UNRESOLVED
        assert anchored == []  # 문항이 없으면 대표 개념을 묻지 않는다

    async def test_unmapped_problem_is_anchor_unresolved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _unmapped(_session: Any, _pid: uuid.UUID) -> None:
            return None

        monkeypatch.setattr(lsr, "get_primary_concept_id", _unmapped)
        _fake, session = _session([0.9], [_PROBLEM])
        route = await _route(_remediating(), session)
        assert route is not None
        assert route.outcome is lsr.StateDirectiveOutcome.ANCHOR_UNRESOLVED

    async def test_attempt_lookup_is_scoped_to_the_learner(self, anchored: list[uuid.UUID]) -> None:
        """원장 `attempt_id`는 느슨한 참조다 — 다른 학생의 응답으로 교정 대상을 정하지 않는다."""
        fake, session = _session([0.9], [_PROBLEM], [])
        await _route(_remediating(), session)
        sql = str(fake.statements[1].compile(dialect=postgresql.dialect()))
        assert "problem_attempt.attempt_id =" in sql
        assert "problem_attempt.user_id =" in sql

    async def test_empty_concept_pool_falls_back(self, anchored: list[uuid.UUID]) -> None:
        _fake, session = _session([0.9], [_PROBLEM], [])
        route = await _route(_remediating(), session)
        assert route == lsr.StateRoute(
            outcome=lsr.StateDirectiveOutcome.NO_CANDIDATE_IN_CONCEPT, concept_id=_CONCEPT
        )

    async def test_applied_route_carries_rows_concept_and_confidence(
        self, anchored: list[uuid.UUID]
    ) -> None:
        other = uuid.uuid4()
        _fake, session = _session([0.9], [_PROBLEM], [(_PROBLEM, 3.0, None), (other, 3.5, 0.4)])
        route = await _route(_remediating(), session)
        assert route == lsr.StateRoute(
            outcome=lsr.StateDirectiveOutcome.APPLIED,
            concept_id=_CONCEPT,
            candidate_rows=((_PROBLEM, 3.0, None), (other, 3.5, 0.4)),
            misconception_confidence=0.9,
        )
        assert anchored == [_PROBLEM]


# ──────────────────────────────────────────────────────────────────────────
# 선택 축 — 개념 제한은 노출 게이트를 **덧붙일 뿐** 다시 쓰지 않는다
# ──────────────────────────────────────────────────────────────────────────
class TestConceptRestrictedPool:
    def _sql(self) -> str:
        stmt = lsr.build_concept_candidate_pool_stmt(
            0.0, concept_id=_CONCEPT, attempted_ids={uuid.uuid4()}, excluded_ids={uuid.uuid4()}
        )
        return str(stmt.compile(dialect=postgresql.dialect()))

    def test_exposure_gates_survive_the_restriction(self) -> None:
        """저작권·검수·난이도 라벨 게이트(REC-06 정본)가 제한 문장에도 그대로 있다."""
        sql = self._sql()
        assert "problem.difficulty_overall IS NOT NULL" in sql
        assert "problem.source_type NOT IN" in sql
        assert "problem.review_status =" in sql

    def test_restricts_to_primary_members_of_the_concept(self) -> None:
        sql = self._sql()
        assert "problem.problem_id IN (SELECT problem_concept.problem_id" in sql
        assert "problem_concept.concept_id =" in sql
        assert "problem_concept.role =" in sql

    def test_primary_role_is_bound(self) -> None:
        """TESTED 문항은 대표 개념이 다르다 — 근거의 개념과 문항이 어긋나지 않게 PRIMARY만."""
        stmt = lsr.build_concept_candidate_pool_stmt(
            0.0, concept_id=_CONCEPT, attempted_ids=set(), excluded_ids=set()
        )
        params = stmt.compile(dialect=postgresql.dialect()).params
        assert "PRIMARY" in {str(getattr(v, "value", v)) for v in params.values()}

    def test_attempt_and_sibling_exclusions_and_limit_are_kept(self) -> None:
        sql = self._sql()
        assert sql.count("problem.problem_id NOT IN") == 2
        assert "LIMIT" in sql
        assert sql.index("WHERE") < sql.index("ORDER BY") < sql.index("LIMIT")


# ──────────────────────────────────────────────────────────────────────────
# 근거 — 상태 머신 근거는 basis=learning_state와만 짝을 이룬다
# ──────────────────────────────────────────────────────────────────────────
class TestRemediationReasonContract:
    def test_remediation_reason_shape(self) -> None:
        reason = remediation_reason(concept_id=_CONCEPT, mastery=0.15, misconception_confidence=0.9)
        assert reason.type is ReasonType.MISCONCEPTION_REMEDIATION
        assert reason.basis is ReasonBasis.LEARNING_STATE
        assert reason.confidence == 0.9
        assert reason.mastery == 0.15
        assert reason.concept_id == _CONCEPT

    def test_remediation_is_practice_current_not_unmeasured(self) -> None:
        """Gate 2 Loop 1 기준 — action ∈ {practice_current, practice_prerequisite} · type ≠ unmeasured."""
        rec = Recommendation(
            problem_id=_PROBLEM,
            reason=remediation_reason(
                concept_id=_CONCEPT, mastery=None, misconception_confidence=0.8
            ),
        )
        assert (
            action_for(ReasonType.MISCONCEPTION_REMEDIATION)
            is RecommendationAction.PRACTICE_CURRENT
        )
        assert rec.action is RecommendationAction.PRACTICE_CURRENT
        assert rec.reason.type is not ReasonType.UNMEASURED

    def test_state_type_with_mastery_basis_cannot_be_constructed(self) -> None:
        with pytest.raises(ValueError, match="basis"):
            RecommendationReason(
                type=ReasonType.MISCONCEPTION_REMEDIATION,
                confidence=0.9,
                basis=ReasonBasis.MEASURED_MASTERY,
                concept_id=_CONCEPT,
            )

    def test_mastery_type_with_state_basis_cannot_be_constructed(self) -> None:
        """반대 방향 — 숙달 구간 근거에 '상태 머신이 결정했다'를 붙이는 거짓도 막는다."""
        with pytest.raises(ValueError, match="basis"):
            RecommendationReason(
                type=ReasonType.CURRENT_CONCEPT,
                confidence=0.5,
                basis=ReasonBasis.LEARNING_STATE,
                concept_id=_CONCEPT,
                mastery=0.5,
            )

    async def test_collect_refuses_a_route_that_was_not_applied(self) -> None:
        """폴백 추천에 오개념 교정 근거를 달면 '상태 머신이 결정했다'가 거짓이 된다."""
        _fake, session = _session()
        with pytest.raises(ValueError, match="집행되지 않은"):
            await lsr.collect_remediation_reason(
                session,
                learner_id=_UID,
                route=lsr.StateRoute(outcome=lsr.StateDirectiveOutcome.NO_CANDIDATE_IN_CONCEPT),
            )

    async def test_collect_reads_mastery_of_the_concept(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        asked: list[uuid.UUID] = []

        @dataclass
        class _Row:
            mastery: float | None

        async def _latest(_s: Any, _learner: uuid.UUID, concept_id: uuid.UUID) -> _Row:
            asked.append(concept_id)
            return _Row(mastery=0.2)

        monkeypatch.setattr(lsr, "_latest_mastery", _latest)
        route = lsr.StateRoute(
            outcome=lsr.StateDirectiveOutcome.APPLIED,
            concept_id=_CONCEPT,
            candidate_rows=((_PROBLEM, 3.0, None),),
            misconception_confidence=0.9,
        )
        reason = await lsr.collect_remediation_reason(
            cast(AsyncSession, object()), learner_id=_UID, route=route
        )
        assert asked == [_CONCEPT]
        assert reason.mastery == 0.2
        assert reason.confidence == 0.9


# ──────────────────────────────────────────────────────────────────────────
# ④ 정책 이음매 — CatRecommendationPolicy가 상태 경로를 실제로 쓰는가
# ──────────────────────────────────────────────────────────────────────────
_CHOSEN = uuid.uuid4()
_FALLBACK = uuid.uuid4()


@dataclass
class _PolicySpies:
    loaded_default_pool: int = 0
    remediation_reason_calls: int = 0
    band_calls: int = 0


@pytest.fixture
def policy_env(monkeypatch: pytest.MonkeyPatch) -> tuple[_PolicySpies, list[lsr.StateRoute | None]]:
    """정책의 DB 좌석을 전부 대역으로 — 재는 것은 **배선**(어느 경로가 무엇을 공급하는가)이다."""
    spies = _PolicySpies()
    routes: list[lsr.StateRoute | None] = []

    async def _history(_s: Any, _uid: uuid.UUID) -> AttemptHistoryState:
        return AttemptHistoryState(
            attempted_ids=set(),
            theta=-2.0,
            standard_error=None,
            measurement_sufficient=False,
            administered_count=1,
        )

    async def _route_stub(*_a: Any, **_k: Any) -> lsr.StateRoute | None:
        return routes[0]

    async def _default_pool(*_a: Any, **_k: Any) -> list[tuple[uuid.UUID, float, float | None]]:
        spies.loaded_default_pool += 1
        return [(_FALLBACK, 1.0, None)]

    async def _remediation(
        _s: Any, *, learner_id: uuid.UUID, route: lsr.StateRoute
    ) -> RecommendationReason:
        spies.remediation_reason_calls += 1
        assert route.concept_id is not None
        return remediation_reason(
            concept_id=route.concept_id, mastery=0.15, misconception_confidence=0.9
        )

    async def _band_reason(*_a: Any, **_k: Any) -> RecommendationReason:
        return build_reason(concept_id=uuid.uuid4(), mastery=None, confidence=None)

    real_band = policy_module.learning_band_weight

    def _band(theta: float, item: Any) -> float:
        spies.band_calls += 1
        return real_band(theta, item)

    monkeypatch.setattr(policy_module, "load_attempt_history_state", _history)
    monkeypatch.setattr(policy_module, "route_by_learning_state", _route_stub)
    monkeypatch.setattr(policy_module, "load_candidate_rows", _default_pool)
    monkeypatch.setattr(policy_module, "collect_remediation_reason", _remediation)
    monkeypatch.setattr(policy_module, "collect_recommendation_reason", _band_reason)
    monkeypatch.setattr(policy_module, "learning_band_weight", _band)
    return spies, routes


class TestPolicySeam:
    async def _call(self) -> policy_module.NextProblemOutcome:
        policy = CatRecommendationPolicy(cast(AsyncSession, object()))
        return await policy(_remediating(), LearningContext(purpose="diagnosis"))

    async def test_applied_route_supplies_pool_reason_target_band_and_version(
        self, policy_env: tuple[_PolicySpies, list[lsr.StateRoute | None]]
    ) -> None:
        spies, routes = policy_env
        routes.append(
            lsr.StateRoute(
                outcome=lsr.StateDirectiveOutcome.APPLIED,
                concept_id=_CONCEPT,
                candidate_rows=((_CHOSEN, 3.0, None),),
                misconception_confidence=0.9,
            )
        )
        outcome = await self._call()
        assert outcome.problem_id == _CHOSEN  # 제한 후보에서 골랐다
        assert spies.loaded_default_pool == 0  # 기본 후보 풀은 묻지도 않았다
        assert spies.remediation_reason_calls == 1
        assert outcome.reason.type is ReasonType.MISCONCEPTION_REMEDIATION
        assert outcome.action is RecommendationAction.PRACTICE_CURRENT
        assert outcome.target_concept == _CONCEPT
        # 요청은 diagnosis였지만 교정 확인은 학습 밴드로 고른다(판정문 §5)
        assert spies.band_calls == 1
        assert outcome.band_calibrated is False
        assert outcome.policy_version == POLICY_VERSION_CAT_STATE_REMEDIATION
        assert outcome.learning_state_directive is lsr.StateDirectiveOutcome.APPLIED

    @pytest.mark.parametrize(
        "outcome_kind",
        [
            lsr.StateDirectiveOutcome.RELEASED_AFTER_REPEAT,
            lsr.StateDirectiveOutcome.WEAK_MISCONCEPTION_EVIDENCE,
            lsr.StateDirectiveOutcome.NO_CANDIDATE_IN_CONCEPT,
        ],
    )
    async def test_unapplied_route_takes_the_pre_eos24_path_but_reports_why(
        self,
        policy_env: tuple[_PolicySpies, list[lsr.StateRoute | None]],
        outcome_kind: lsr.StateDirectiveOutcome,
    ) -> None:
        spies, routes = policy_env
        routes.append(lsr.StateRoute(outcome=outcome_kind, concept_id=_CONCEPT))
        outcome = await self._call()
        assert outcome.problem_id == _FALLBACK
        assert spies.loaded_default_pool == 1
        assert spies.remediation_reason_calls == 0
        assert outcome.reason.basis is not ReasonBasis.LEARNING_STATE
        assert spies.band_calls == 0  # 요청 목적(diagnosis) 그대로 — 밴드 없음
        assert outcome.band_calibrated is None
        assert outcome.policy_version == POLICY_VERSION_CAT
        assert outcome.learning_state_directive is outcome_kind

    async def test_no_directive_is_indistinguishable_from_before(
        self, policy_env: tuple[_PolicySpies, list[lsr.StateRoute | None]]
    ) -> None:
        spies, routes = policy_env
        routes.append(None)
        outcome = await self._call()
        assert outcome.problem_id == _FALLBACK
        assert outcome.policy_version == POLICY_VERSION_CAT
        assert outcome.learning_state_directive is None
        assert spies.remediation_reason_calls == 0


# ══════════════════════════════════════════════════════════════════════════
# EOS-26 — R6(원인 미상 오답) 집행
#
# ⑤ 무엇을 지시로 읽는가(R2 제외 — 국면·트리거 둘 다) ⑥ 판정 트리(연속 둘째 · 막힘 문턱 · 아는
# 결손 · 미측정 선수 탐침 · 같은 개념 폴백)와 선택 축(직접 선수 · 미측정만 · 병합 정렬) ⑦ 정책
# 이음매(후보 제한 · 연습 경로 학습 밴드 · 정책 버전 · 전진 보류 · 예산을 건 선수 읽기). 설계
# 정본은 EOS-26 판정문 §2~§4. 경계는 상수를 import하지 않고 리터럴(막힘 0.39·0.40 · 선수 결손
# 0.29·0.30 — EOS-151이 EOS-33 (가) 술어로 정합하기 전에는 0.69·0.70)로 밟는다(MISC-30 자기참조
# 교훈 — 파일 머리 ②와 같은 규율).
# ══════════════════════════════════════════════════════════════════════════
R6 = TransitionTrigger.POLICY_PRACTICE_UNDIAGNOSED
R2 = TransitionTrigger.POLICY_PRACTICE_LOW_CONFIDENCE
_PRE_A = uuid.uuid4()
_PRE_B = uuid.uuid4()
_SAME = uuid.uuid4()  # 같은 개념(오답 개념) 문항
_PROBE_ITEM = uuid.uuid4()  # 선수 문항


def _undiagnosed(
    *,
    trigger: TransitionTrigger = R6,
    state: LearningState = LearningState.PRACTICING,
    attempt_id: uuid.UUID | None = _ATTEMPT,
    mastery: dict[str, float] | None = None,
) -> LearnerState:
    snapshot = LearningStateSnapshot(
        state=state,
        trigger=trigger,
        rule_id="R6-wrong-undiagnosed" if trigger is R6 else "R2-correct-low-confidence",
        attempt_id=attempt_id,
        assessed_from=LearningState.LEARNING,
    )
    return _state(snapshot).model_copy(update={"mastery": mastery or {}})


def _prereq(code: str | None, concept_id: uuid.UUID, *, depth: int = 1) -> PrerequisiteRow:
    return PrerequisiteRow(
        concept_id=concept_id, concept_code=code, name_ko=None, edge_strength=None, depth=depth
    )


@dataclass
class _Reader:
    """주입되는 선수 읽기 함수의 대역 — 호출(개념·깊이)을 기록하고 행을 주거나 예외를 낸다."""

    rows: list[PrerequisiteRow] = field(default_factory=list)
    raises: BaseException | None = None
    calls: list[tuple[uuid.UUID, int]] = field(default_factory=list)

    async def __call__(self, concept_id: uuid.UUID, max_depth: int) -> list[PrerequisiteRow]:
        self.calls.append((concept_id, max_depth))
        if self.raises is not None:
            raise self.raises
        return list(self.rows)


async def _route_r6(
    learner_state: LearnerState, session: AsyncSession, reader: _Reader
) -> lsr.StateRoute | None:
    return await lsr.route_by_learning_state(
        session,
        learner_state,
        theta=-4.0,
        attempted_ids=set(),
        excluded_ids=set(),
        read_prerequisites=reader,
    )


def _param_values(stmt: Any) -> set[Any]:
    """컴파일 파라미터를 평평하게 — `IN` 목록 파라미터(리스트 값)도 원소로 펼친다."""
    values: set[Any] = set()
    for value in stmt.compile(dialect=postgresql.dialect()).params.values():
        if isinstance(value, list | tuple):
            values.update(value)
        else:
            values.add(value)
    return values


class TestReadUndiagnosedWrongDirective:
    def test_r6_practicing_is_a_directive(self) -> None:
        directive = lsr.read_undiagnosed_wrong_directive(_undiagnosed())
        assert directive == lsr.UndiagnosedWrongDirective(attempt_id=_ATTEMPT)

    def test_r2_practicing_is_not_a_directive(self) -> None:
        """ⓓ — **국면만 보는** 뮤테이션의 반례. 확신도 미보고 정답(R2)마다 탐침이 나가면 안 된다."""
        assert lsr.read_undiagnosed_wrong_directive(_undiagnosed(trigger=R2)) is None

    def test_r6_trigger_outside_practicing_is_not_a_directive(self) -> None:
        """**트리거만 보는** 뮤테이션의 반례 — R6 뒤 국면이 바뀌었으면 지시가 아니다."""
        changed = _undiagnosed(state=LearningState.LEARNING)
        assert lsr.read_undiagnosed_wrong_directive(changed) is None

    def test_unassembled_or_empty_ledger_is_not_a_directive(self) -> None:
        assert lsr.read_undiagnosed_wrong_directive(_state(None)) is None
        empty = _state(LearningStateSnapshot(state=LearningState.NEW))
        assert lsr.read_undiagnosed_wrong_directive(empty) is None

    def test_r3_remediating_is_not_an_undiagnosed_directive(self) -> None:
        assert lsr.read_undiagnosed_wrong_directive(_remediating()) is None

    def test_policy_decision_triggers_cover_every_policy_trigger(self) -> None:
        """연속 판정이 보는 '정책 결정' 집합 — 새 `POLICY_*` 트리거가 생기면 여기서 드러난다."""
        derived = frozenset(t for t in TransitionTrigger if t.name.startswith("POLICY_"))
        assert lsr.POLICY_DECISION_TRIGGERS == derived
        assert TransitionTrigger.ATTEMPT_SUBMITTED not in lsr.POLICY_DECISION_TRIGGERS


@dataclass
class _MasteryRow:
    mastery: float | None


@pytest.fixture
def anchor_mastery(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """오답 개념의 최신 숙달 조회를 대역으로 — `[값]`을 바꿔 막힘 여부를 정한다(기본 0.15 = 오답 1회 뒤
    콜드스타트 값). 조회 인자(학생·개념)를 기록한다. 숙달 좌석 자체는 숙달 모듈 테스트가 검증한다."""
    state: list[Any] = [0.15]
    asked: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def _latest(_s: Any, learner: uuid.UUID, concept_id: uuid.UUID) -> _MasteryRow | None:
        asked.append((learner, concept_id))
        return None if state[0] is None else _MasteryRow(mastery=state[0])

    monkeypatch.setattr(lsr, "_latest_mastery", _latest)
    state.append(asked)
    return state


class TestPrerequisiteStatus:
    """직접 선수의 측정 상태 — EOS-124 (가)와 같은 입력·같은 술어(사전값 0.3 미만이면 결손 ·
    EOS-151). 리터럴로 밟는다."""

    @pytest.mark.parametrize(
        ("code", "mastery", "status"),
        [
            ("UC-A", None, "unmeasured"),
            (None, None, "unmeasured"),  # 코드가 없으면 숙달을 찾을 수 없다 — 미측정
            ("UC-A", 0.29, "weak"),
            ("UC-A", 0.15, "weak"),
            ("UC-A", 0.30, "strong"),  # 경계 자체 — (가)도 사전값 0.30을 결손으로 보지 않는다
            # 옛 약점 구간(0.3~0.7)은 이제 "측정됐고 결손 아님"이다 — 경계를 0.7로 되돌리면 RED
            ("UC-A", 0.69, "strong"),
            ("UC-A", 0.95, "strong"),
        ],
    )
    def test_status(self, code: str | None, mastery: float | None, status: str) -> None:
        values = {} if mastery is None or code is None else {code: mastery}
        row = _prereq(code, _PRE_A)
        assert lsr._prerequisite_status(row, _undiagnosed(mastery=values)).value == status


class TestRouteUndiagnosedWrong:
    async def test_r2_issues_no_query_and_reads_no_prerequisite(self) -> None:
        fake, session = _session()
        reader = _Reader()
        assert await _route_r6(_undiagnosed(trigger=R2), session, reader) is None
        assert fake.statements == []
        assert reader.calls == []

    async def test_missing_attempt_is_anchor_unresolved_without_query(self) -> None:
        fake, session = _session()
        reader = _Reader()
        route = await _route_r6(_undiagnosed(attempt_id=None), session, reader)
        assert route == lsr.StateRoute(outcome=lsr.StateDirectiveOutcome.ANCHOR_UNRESOLVED)
        assert fake.statements == []
        assert reader.calls == []

    async def test_attempt_not_found_is_anchor_unresolved(self, anchored: list[uuid.UUID]) -> None:
        fake, session = _session([])
        reader = _Reader()
        route = await _route_r6(_undiagnosed(), session, reader)
        assert route == lsr.StateRoute(outcome=lsr.StateDirectiveOutcome.ANCHOR_UNRESOLVED)
        assert len(fake.statements) == 1  # 직전 결정을 묻지 않는다(앵커가 먼저다)
        assert anchored == []
        assert reader.calls == []

    @pytest.mark.parametrize("previous", [R6, R3])
    async def test_second_consecutive_wrong_restricts_to_the_concept_just_failed(
        self, anchored: list[uuid.UUID], anchor_mastery: list[Any], previous: TransitionTrigger
    ) -> None:
        """ⓒ — 직전 정책 결정이 오답 결정(R6·R3)이면 연속 두 번째 오답이다. 탐침하지 않고 방금 틀린
        개념으로 간다(R6 문면 · ⓑ의 근원). 셋째는 R5라 탐침 결과를 쓸 하강이 없기 때문이다.

        R3가 핵심 반례다 — "직전이 R6일 때만 연속"으로 좁히는 뮤테이션은 R3→R6에서 탐침을 내보낸다.
        """
        fake, session = _session([_PROBLEM], [previous], [(_SAME, 3.0, None)])
        reader = _Reader(rows=[_prereq("UC-PRE-A", _PRE_A)])
        route = await _route_r6(_undiagnosed(), session, reader)
        assert route == lsr.StateRoute(
            outcome=lsr.StateDirectiveOutcome.SAME_CONCEPT_REPEAT,
            concept_id=_CONCEPT,
            candidate_rows=((_SAME, 3.0, None),),
        )
        assert route.undiagnosed_applied
        assert route.undiagnosed_practice  # 연습 경로 — 정책이 학습 밴드로 고른다
        assert not route.applied  # R3 근거 경로가 아니다
        assert reader.calls == []  # 연속이면 선수를 읽지 않는다
        assert anchor_mastery[1] == []  # 오답 개념 숙달도 묻지 않는다
        assert _CONCEPT in _param_values(fake.statements[2])  # 같은 개념 제한 문장

    @pytest.mark.parametrize(
        "previous",
        [None, R2, TransitionTrigger.POLICY_ADVANCE, TransitionTrigger.POLICY_REPEATED_FAILURE],
    )
    async def test_non_wrong_previous_decision_is_a_first_wrong(
        self,
        anchored: list[uuid.UUID],
        anchor_mastery: list[Any],
        previous: TransitionTrigger | None,
    ) -> None:
        """직전이 오답 결정(R3·R6)이 아니면 연속 첫 오답이다 — 탐침으로 간다.

        "직전 결정이 있기만 하면 연속"으로 접는 뮤테이션을 R2·R1·R5가 각각 잡는다(R5 뒤에는 연속
        안에서 R6가 올 수 없다 — 연속 3회 이상이면 계속 R5다).
        """
        previous_rows = [] if previous is None else [previous]
        _fake, session = _session([_PROBLEM], previous_rows, [(_PROBE_ITEM, 1.2, None, _PRE_A)])
        reader = _Reader(rows=[_prereq("UC-PRE-A", _PRE_A)])
        route = await _route_r6(_undiagnosed(), session, reader)
        assert route is not None
        assert route.outcome is lsr.StateDirectiveOutcome.PREREQUISITE_PROBE

    async def test_previous_decision_query_is_scoped_and_excludes_this_attempt(
        self, anchored: list[uuid.UUID]
    ) -> None:
        """연속 판정 조회 — 이 학생 · 결정 응답 **밖** · 정책 결정만 · 최신순."""
        fake, session = _session([_PROBLEM], [R6], [])
        await _route_r6(_undiagnosed(), session, _Reader())
        stmt = fake.statements[1]
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        assert "learning_state_transition.user_id =" in sql
        assert "learning_state_transition.attempt_id !=" in sql
        assert "learning_state_transition.trigger IN" in sql
        assert "ORDER BY learning_state_transition.occurred_at DESC" in sql
        values = _param_values(stmt)
        assert _ATTEMPT in values  # 빠지는 것은 결정 응답 자신의 행이다
        assert TransitionTrigger.ATTEMPT_SUBMITTED not in values

    @pytest.mark.parametrize("mastery", [0.40, 0.63])
    async def test_unblocked_anchor_practices_the_same_concept(
        self, anchored: list[uuid.UUID], anchor_mastery: list[Any], mastery: float
    ) -> None:
        """첫 오답인데 오답 개념이 선수 구간이 아니다(≥ 0.4) — 1회 실수를 선수 결손으로 읽지 않는다.

        0.40이 핵심 반례다(선수 경계 자체 — `select_reason_type`도 0.4를 current로 본다).
        """
        anchor_mastery[0] = mastery
        _fake, session = _session([_PROBLEM], [], [(_SAME, 3.0, None)])
        reader = _Reader(rows=[_prereq("UC-PRE-A", _PRE_A)])
        route = await _route_r6(_undiagnosed(), session, reader)
        assert route == lsr.StateRoute(
            outcome=lsr.StateDirectiveOutcome.SAME_CONCEPT_NOT_BLOCKED,
            concept_id=_CONCEPT,
            candidate_rows=((_SAME, 3.0, None),),
        )
        assert reader.calls == []  # 막히지 않았으면 선수를 읽지도 않는다

    async def test_blocked_anchor_just_below_the_boundary_proceeds(
        self, anchored: list[uuid.UUID], anchor_mastery: list[Any]
    ) -> None:
        """0.39 — 선수 경계 **미만**의 반례. `<`→`<=` 뒤바뀜 뮤테이션을 0.40과 함께 가른다."""
        anchor_mastery[0] = 0.39
        _fake, session = _session([_PROBLEM], [], [(_PROBE_ITEM, 1.2, None, _PRE_A)])
        reader = _Reader(rows=[_prereq("UC-PRE-A", _PRE_A)])
        route = await _route_r6(_undiagnosed(), session, reader)
        assert route is not None
        assert route.outcome is lsr.StateDirectiveOutcome.PREREQUISITE_PROBE

    async def test_anchor_mastery_is_read_for_this_learner_and_the_failed_concept(
        self, anchored: list[uuid.UUID], anchor_mastery: list[Any]
    ) -> None:
        _fake, session = _session([_PROBLEM], [], [(_PROBE_ITEM, 1.2, None, _PRE_A)])
        await _route_r6(_undiagnosed(), session, _Reader(rows=[_prereq("UC-PRE-A", _PRE_A)]))
        assert anchor_mastery[1] == [(_UID, _CONCEPT)]

    async def test_unmeasured_anchor_practices_the_same_concept_and_warns(
        self,
        anchored: list[uuid.UUID],
        anchor_mastery: list[Any],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """오답 직후인데 오답 개념의 숙달이 없다 — 막힘을 세울 근거가 없다(모른다 ≠ 막힘 · 경고 로그)."""
        anchor_mastery[0] = None
        _fake, session = _session([_PROBLEM], [], [(_SAME, 3.0, None)])
        reader = _Reader(rows=[_prereq("UC-PRE-A", _PRE_A)])
        with caplog.at_level(logging.WARNING, logger="whymath.l2.learning_state_recommendation"):
            route = await _route_r6(_undiagnosed(), session, reader)
        assert route is not None
        assert route.outcome is lsr.StateDirectiveOutcome.SAME_CONCEPT_ANCHOR_UNMEASURED
        assert reader.calls == []
        assert "숙달 측정이 없다" in caplog.text

    async def test_probe_reads_direct_prerequisites_of_the_failed_concept(
        self, anchored: list[uuid.UUID], anchor_mastery: list[Any]
    ) -> None:
        """ⓑ — 탐침은 오답 개념의 **직접** 선수(깊이 1)만 읽는다. 깊이 뮤테이션을 잡는다."""
        _fake, session = _session([_PROBLEM], [], [(_PROBE_ITEM, 1.2, None, _PRE_A)])
        reader = _Reader(rows=[_prereq("UC-PRE-A", _PRE_A)])
        await _route_r6(_undiagnosed(), session, reader)
        assert reader.calls == [(_CONCEPT, 1)]

    async def test_probe_route_carries_the_prerequisite_pool(
        self, anchored: list[uuid.UUID], anchor_mastery: list[Any]
    ) -> None:
        _fake, session = _session([_PROBLEM], [], [(_PROBE_ITEM, 1.2, None, _PRE_A)])
        reader = _Reader(rows=[_prereq("UC-PRE-A", _PRE_A)])
        route = await _route_r6(_undiagnosed(), session, reader)
        assert route == lsr.StateRoute(
            outcome=lsr.StateDirectiveOutcome.PREREQUISITE_PROBE,
            concept_id=_CONCEPT,
            candidate_rows=((_PROBE_ITEM, 1.2, None),),
        )
        assert route.undiagnosed_applied
        assert not route.undiagnosed_practice  # 탐침은 측정이다 — 요청 목적 그대로

    async def test_no_prerequisite_edge_practices_the_same_concept(
        self, anchored: list[uuid.UUID], anchor_mastery: list[Any]
    ) -> None:
        """ⓐ — 선수 엣지가 없으면 기본 경로가 아니라 같은 개념(R6 문면 · 사유 unsupported)."""
        _fake, session = _session([_PROBLEM], [], [(_SAME, 3.0, None)])
        route = await _route_r6(_undiagnosed(), session, _Reader(rows=[]))
        assert route == lsr.StateRoute(
            outcome=lsr.StateDirectiveOutcome.SAME_CONCEPT_PROBE_UNSUPPORTED,
            concept_id=_CONCEPT,
            candidate_rows=((_SAME, 3.0, None),),
        )

    @pytest.mark.parametrize("mastery", [0.30, 0.69, 0.95])
    async def test_measured_strong_prerequisites_are_refuted(
        self, anchored: list[uuid.UUID], anchor_mastery: list[Any], mastery: float
    ) -> None:
        """측정됐고 결손이 아닌(사전값 0.3 이상) 선수만 있으면 원인 후보가 선수에 없다 — 같은
        개념(사유 refuted). 0.30은 `<`를 `<=`로 바꾸는 뮤테이션을, 0.69는 경계를 0.7로 되돌리는
        뮤테이션을 가른다(EOS-151)."""
        fake, session = _session([_PROBLEM], [], [(_SAME, 3.0, None)])
        reader = _Reader(rows=[_prereq("UC-PRE-A", _PRE_A)])
        route = await _route_r6(_undiagnosed(mastery={"UC-PRE-A": mastery}), session, reader)
        assert route is not None
        assert route.outcome is lsr.StateDirectiveOutcome.SAME_CONCEPT_PROBE_REFUTED
        assert len(fake.statements) == 3  # 앵커 · 직전 결정 · 같은 개념 — 탐침 후보는 묻지 않는다

    @pytest.mark.parametrize("mastery", [0.29, 0.15])
    async def test_measured_weak_prerequisite_is_a_known_deficit(
        self, anchored: list[uuid.UUID], anchor_mastery: list[Any], mastery: float
    ) -> None:
        """이미 측정된 결손(사전값 0.3 미만) — 진단하지 않고 오답 개념으로 제한한다(EOS-124 (가)가
        잇는다 — 같은 술어라 반드시 이 선수를 찾는다).

        0.29가 핵심 반례다(경계를 사전값 아래로 내리는 뮤테이션을 가른다 · `<`→`<=`와 0.7 복귀는 위
        refuted의 0.30·0.69가 가른다).
        """
        fake, session = _session([_PROBLEM], [], [(_SAME, 3.0, None)])
        reader = _Reader(rows=[_prereq("UC-PRE-A", _PRE_A)])
        route = await _route_r6(_undiagnosed(mastery={"UC-PRE-A": mastery}), session, reader)
        assert route == lsr.StateRoute(
            outcome=lsr.StateDirectiveOutcome.KNOWN_PREREQUISITE_DEFICIT,
            concept_id=_CONCEPT,
            candidate_rows=((_SAME, 3.0, None),),
        )
        assert route.undiagnosed_practice
        assert _CONCEPT in _param_values(fake.statements[2])  # 탐침 후보가 아니라 같은 개념 문장

    async def test_known_deficit_takes_precedence_over_probing(
        self, anchored: list[uuid.UUID], anchor_mastery: list[Any]
    ) -> None:
        """아는 결손이 먼저다 — 미측정 선수가 함께 있어도 탐침하지 않는다(판정문 §3 ⓑ)."""
        _fake, session = _session([_PROBLEM], [], [(_SAME, 3.0, None)])
        reader = _Reader(rows=[_prereq("UC-PRE-A", _PRE_A), _prereq("UC-PRE-B", _PRE_B)])
        route = await _route_r6(_undiagnosed(mastery={"UC-PRE-A": 0.15}), session, reader)
        assert route is not None
        assert route.outcome is lsr.StateDirectiveOutcome.KNOWN_PREREQUISITE_DEFICIT

    @pytest.mark.parametrize("mastery", [0.30, 0.69])
    async def test_mixed_evidence_prerequisite_does_not_block_probing(
        self, anchored: list[uuid.UUID], anchor_mastery: list[Any], mastery: float
    ) -> None:
        """측정됐지만 결손이 아닌 선수(사전값 0.3~0.7 — 엇갈린 증거)는 아는 결손이 아니다 — 함께
        있는 미측정 선수를 탐침한다(EOS-151 — 정합 전에는 0.3~0.7이 아는 결손으로 탐침을 막았다)."""
        fake, session = _session([_PROBLEM], [], [(_PROBE_ITEM, 1.2, None, _PRE_B)])
        reader = _Reader(rows=[_prereq("UC-PRE-A", _PRE_A), _prereq("UC-PRE-B", _PRE_B)])
        route = await _route_r6(_undiagnosed(mastery={"UC-PRE-A": mastery}), session, reader)
        assert route is not None
        assert route.outcome is lsr.StateDirectiveOutcome.PREREQUISITE_PROBE
        values = _param_values(fake.statements[2])
        assert _PRE_B in values  # 미측정 선수만 탐침 후보다
        assert _PRE_A not in values

    async def test_probe_pool_holds_only_unmeasured_prerequisites(
        self, anchored: list[uuid.UUID], anchor_mastery: list[Any]
    ) -> None:
        """진단은 모르는 것을 잰다 — 숙달된 선수는 탐침 후보 문장에 들어가지 않는다."""
        fake, session = _session([_PROBLEM], [], [(_PROBE_ITEM, 1.2, None, _PRE_A)])
        reader = _Reader(rows=[_prereq("UC-PRE-A", _PRE_A), _prereq("UC-PRE-B", _PRE_B)])
        await _route_r6(_undiagnosed(mastery={"UC-PRE-B": 0.9}), session, reader)
        values = _param_values(fake.statements[2])
        assert _PRE_A in values
        assert _PRE_B not in values

    async def test_codeless_prerequisite_is_probed_as_unmeasured(
        self, anchored: list[uuid.UUID], anchor_mastery: list[Any]
    ) -> None:
        fake, session = _session([_PROBLEM], [], [(_PROBE_ITEM, 1.2, None, _PRE_A)])
        reader = _Reader(rows=[_prereq(None, _PRE_A)])
        route = await _route_r6(_undiagnosed(mastery={}), session, reader)
        assert route is not None
        assert route.outcome is lsr.StateDirectiveOutcome.PREREQUISITE_PROBE
        assert _PRE_A in _param_values(fake.statements[2])

    async def test_unmeasured_prerequisites_without_items_practice_the_same_concept(
        self, anchored: list[uuid.UUID], anchor_mastery: list[Any]
    ) -> None:
        _fake, session = _session([_PROBLEM], [], [], [(_SAME, 3.0, None)])
        reader = _Reader(rows=[_prereq("UC-PRE-A", _PRE_A)])
        route = await _route_r6(_undiagnosed(), session, reader)
        assert route == lsr.StateRoute(
            outcome=lsr.StateDirectiveOutcome.SAME_CONCEPT_PROBE_UNAVAILABLE,
            concept_id=_CONCEPT,
            candidate_rows=((_SAME, 3.0, None),),
        )

    async def test_graph_timeout_practices_the_same_concept_and_logs_the_type(
        self,
        anchored: list[uuid.UUID],
        anchor_mastery: list[Any],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """ⓕ — 시간 예산 초과는 추천을 실패시키지 않는다. 예외 타입명을 남긴다(침묵 실패 금지)."""
        _fake, session = _session([_PROBLEM], [], [(_SAME, 3.0, None)])
        reader = _Reader(raises=TimeoutError())
        with caplog.at_level(logging.WARNING, logger="whymath.l2.learning_state_recommendation"):
            route = await _route_r6(_undiagnosed(), session, reader)
        assert route is not None
        assert route.outcome is lsr.StateDirectiveOutcome.SAME_CONCEPT_GRAPH_TIMEOUT
        assert "TimeoutError" in caplog.text

    async def test_same_concept_without_items_falls_back(self, anchored: list[uuid.UUID]) -> None:
        """같은 개념에도 미시도 문항이 없으면 제한하지 못한 것이다 — 기본 경로(집행 아님)."""
        _fake, session = _session([_PROBLEM], [R6], [])
        route = await _route_r6(_undiagnosed(), session, _Reader())
        assert route == lsr.StateRoute(
            outcome=lsr.StateDirectiveOutcome.NO_CANDIDATE_IN_CONCEPT, concept_id=_CONCEPT
        )
        assert not route.undiagnosed_applied
        assert not route.applied


class TestProbeCandidates:
    """탐침 후보 병합 — 기본 후보 풀과 같은 키(|b−θ| → problem_id)로 정렬 · 중복 제거 · 상한."""

    def test_dedups_and_sorts_like_the_default_pool(self) -> None:
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        rows = [
            (a, 2.0, None, _PRE_A),  # b = -1.0 → |b−θ| 3.0
            (b, 1.2, None, _PRE_A),  # b = -1.8 → 2.2
            (c, 5.0, -3.0, _PRE_B),  # 보정 b 우선 = -3.0 → 1.0
            (b, 1.2, None, _PRE_B),  # 같은 문항이 두 선수의 PRIMARY — 한 번만
        ]
        got = lsr._probe_candidates(rows, -4.0)
        assert [pid for pid, _d, _b in got] == [c, b, a]

    def test_ties_break_by_problem_id(self) -> None:
        low, high = sorted((uuid.uuid4(), uuid.uuid4()), key=str)
        got = lsr._probe_candidates([(high, 1.5, None, _PRE_A), (low, 1.5, None, _PRE_B)], -4.0)
        assert [pid for pid, _d, _b in got] == [low, high]

    def test_caps_at_the_default_pool_size(self) -> None:
        rows = [
            (uuid.uuid4(), 1.0 + i * 0.01, None, _PRE_A) for i in range(CANDIDATE_POOL_SIZE + 7)
        ]
        assert len(lsr._probe_candidates(rows, -4.0)) == CANDIDATE_POOL_SIZE


# ──────────────────────────────────────────────────────────────────────────
# ⑦ 정책 이음매 — R6 제한 후보 · 정책 버전 · 전진 금지 · 예산을 건 선수 읽기
# ──────────────────────────────────────────────────────────────────────────
_ANCHOR = uuid.uuid4()


@dataclass
class _R6Spies:
    loaded_default_pool: int = 0
    intent_calls: int = 0
    band_calls: int = 0
    route_kwargs: dict[str, Any] = field(default_factory=dict)


@pytest.fixture
def r6_policy_env(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_R6Spies, list[lsr.StateRoute | None], list[RecommendationReason]]:
    """정책의 DB 좌석을 대역으로 — R6 경로가 **무엇을 바꾸고 무엇을 그대로 두는가**를 잰다."""
    spies = _R6Spies()
    routes: list[lsr.StateRoute | None] = []
    anchor_reasons: list[RecommendationReason] = []

    async def _history(_s: Any, _uid: uuid.UUID) -> AttemptHistoryState:
        return AttemptHistoryState(
            attempted_ids=set(),
            theta=-4.0,
            standard_error=None,
            measurement_sufficient=False,
            administered_count=1,
        )

    async def _route_stub(*_a: Any, **kwargs: Any) -> lsr.StateRoute | None:
        spies.route_kwargs = kwargs
        return routes[0]

    async def _default_pool(*_a: Any, **_k: Any) -> list[tuple[uuid.UUID, float, float | None]]:
        spies.loaded_default_pool += 1
        return [(_FALLBACK, 1.0, None)]

    async def _anchor_reason(*_a: Any, **_k: Any) -> RecommendationReason:
        return anchor_reasons[0]

    real_intent = policy_module.resolve_policy_intent

    async def _intent(*args: Any, **kwargs: Any) -> PolicyIntent:
        spies.intent_calls += 1
        if kwargs["anchor_reason"].type is ReasonType.NEXT_CONCEPT:
            # 기본 경로의 전진 갈래는 그래프를 읽는다 — 여기서는 "불렸다"만 재고 강등으로 끝낸다.
            return policy_module._demoted(kwargs["anchor_reason"], IntentResolution.UNSUPPORTED)
        result: PolicyIntent = await real_intent(*args, **kwargs)
        return result

    real_band = policy_module.learning_band_weight

    def _band(theta: float, item: Any) -> float:
        spies.band_calls += 1
        return real_band(theta, item)

    monkeypatch.setattr(policy_module, "load_attempt_history_state", _history)
    monkeypatch.setattr(policy_module, "route_by_learning_state", _route_stub)
    monkeypatch.setattr(policy_module, "load_candidate_rows", _default_pool)
    monkeypatch.setattr(policy_module, "collect_recommendation_reason", _anchor_reason)
    monkeypatch.setattr(policy_module, "resolve_policy_intent", _intent)
    monkeypatch.setattr(policy_module, "learning_band_weight", _band)
    return spies, routes, anchor_reasons


# 연습 경로(탐침 제외) 8종 — 구현의 집합을 import하지 않고 리터럴로 적는다(자기참조 방지).
_PRACTICE_OUTCOMES = [
    lsr.StateDirectiveOutcome.SAME_CONCEPT_REPEAT,
    lsr.StateDirectiveOutcome.SAME_CONCEPT_NOT_BLOCKED,
    lsr.StateDirectiveOutcome.SAME_CONCEPT_ANCHOR_UNMEASURED,
    lsr.StateDirectiveOutcome.KNOWN_PREREQUISITE_DEFICIT,
    lsr.StateDirectiveOutcome.SAME_CONCEPT_PROBE_UNSUPPORTED,
    lsr.StateDirectiveOutcome.SAME_CONCEPT_PROBE_REFUTED,
    lsr.StateDirectiveOutcome.SAME_CONCEPT_PROBE_UNAVAILABLE,
    lsr.StateDirectiveOutcome.SAME_CONCEPT_GRAPH_TIMEOUT,
]


def _probe_route() -> lsr.StateRoute:
    return lsr.StateRoute(
        outcome=lsr.StateDirectiveOutcome.PREREQUISITE_PROBE,
        concept_id=_CONCEPT,
        candidate_rows=((_PROBE_ITEM, 1.2, None),),
    )


class TestUndiagnosedPolicyVersion:
    """R6 집행 추천의 정책 식별자 — 이름표·재선택이 기본 CAT 규칙을 따르므로 판 번호도 기본 CAT을
    따른다(EOS-151 ② — 소급 평가가 두 규칙을 한 식별자로 섞지 않게)."""

    def test_wire_value(self) -> None:
        # 리터럴로 못 박는다 — 값을 옛 `cat_v2_state_undiagnosed`로 되돌리면 RED
        assert POLICY_VERSION_CAT_STATE_UNDIAGNOSED == "cat_v3_state_undiagnosed"

    def test_tracks_the_base_cat_version(self) -> None:
        # 기본 CAT이 다음 판으로 올라가면 이 식별자도 함께 올라가야 한다 — 잊으면 여기서 RED
        assert POLICY_VERSION_CAT_STATE_UNDIAGNOSED == f"{POLICY_VERSION_CAT}_state_undiagnosed"


class TestUndiagnosedPolicySeam:
    async def _call(self, policy: CatRecommendationPolicy | None = None) -> Any:
        policy = policy or CatRecommendationPolicy(cast(AsyncSession, object()))
        return await policy(_undiagnosed(), LearningContext(purpose="diagnosis"))

    async def test_probe_route_supplies_the_pool_but_not_the_reason(
        self,
        r6_policy_env: tuple[_R6Spies, list[lsr.StateRoute | None], list[RecommendationReason]],
    ) -> None:
        """후보는 R6 경로에서, 이름표는 기본 연산(숙달 파생 + EOS-124)에서 — 판정문 §2-2 근거 4."""
        spies, routes, anchor_reasons = r6_policy_env
        routes.append(_probe_route())
        anchor_reasons.append(build_reason(concept_id=_PRE_A, mastery=None, confidence=None))
        outcome = await self._call()
        assert outcome.problem_id == _PROBE_ITEM  # 제한 후보에서 골랐다
        assert spies.loaded_default_pool == 0  # 기본 후보 풀은 묻지도 않았다
        assert outcome.action is RecommendationAction.DIAGNOSE  # 미측정 선수 → 진단
        assert outcome.reason.basis is ReasonBasis.COLD_START  # 근거는 상태 머신 몫이 아니다
        assert outcome.target_concept == _PRE_A
        assert outcome.intent_resolution is IntentResolution.DIRECT
        assert spies.intent_calls == 1  # EOS-124 해소가 돈다(R3 경로와 다르다)
        assert outcome.band_calibrated is None  # 요청 목적(diagnosis) 그대로 — 탐침은 측정이다
        assert spies.band_calls == 0
        assert outcome.policy_version == POLICY_VERSION_CAT_STATE_UNDIAGNOSED
        assert outcome.learning_state_directive is lsr.StateDirectiveOutcome.PREREQUISITE_PROBE

    def test_route_sets_are_frozen_by_literal(self) -> None:
        """집행 집합(후보 제한)과 연습 집합(학습 밴드)의 경계 — 새 R6 결과값이 생기면 여기서 밴드를
        정하게 만든다. 탐침만 '제한하되 연습이 아니다'."""
        applied = {
            o for o in lsr.StateDirectiveOutcome if lsr.StateRoute(outcome=o).undiagnosed_applied
        }
        practice = {
            o for o in lsr.StateDirectiveOutcome if lsr.StateRoute(outcome=o).undiagnosed_practice
        }
        assert practice == set(_PRACTICE_OUTCOMES)
        assert applied == practice | {lsr.StateDirectiveOutcome.PREREQUISITE_PROBE}

    @pytest.mark.parametrize("outcome_kind", _PRACTICE_OUTCOMES)
    async def test_practice_routes_select_with_the_learning_band(
        self,
        r6_policy_env: tuple[_R6Spies, list[lsr.StateRoute | None], list[RecommendationReason]],
        outcome_kind: lsr.StateDirectiveOutcome,
    ) -> None:
        """연습 경로는 요청 목적(diagnosis)과 무관하게 학습 밴드로 고른다 — 오답 직후 연습에 정보량
        최대(정답 확률 ~50% 지향)를 쓰지 않는다(판정문 §4 · R3 교정과 같은 규칙)."""
        spies, routes, anchor_reasons = r6_policy_env
        routes.append(
            lsr.StateRoute(
                outcome=outcome_kind, concept_id=_CONCEPT, candidate_rows=((_SAME, 3.0, None),)
            )
        )
        anchor_reasons.append(build_reason(concept_id=_CONCEPT, mastery=0.55, confidence=0.6))
        outcome = await self._call()
        assert outcome.problem_id == _SAME
        assert spies.loaded_default_pool == 0
        assert spies.band_calls == 1
        assert outcome.band_calibrated is False
        assert outcome.policy_version == POLICY_VERSION_CAT_STATE_UNDIAGNOSED
        assert outcome.learning_state_directive is outcome_kind

    @pytest.mark.parametrize(
        ("route_outcome", "purpose"),
        [
            (lsr.StateDirectiveOutcome.SAME_CONCEPT_REPEAT, "learning"),
            (lsr.StateDirectiveOutcome.PREREQUISITE_PROBE, "diagnosis"),
            (None, "diagnosis"),
        ],
    )
    async def test_reselection_keeps_the_first_selection_context(
        self,
        r6_policy_env: tuple[_R6Spies, list[lsr.StateRoute | None], list[RecommendationReason]],
        monkeypatch: pytest.MonkeyPatch,
        route_outcome: lsr.StateDirectiveOutcome | None,
        purpose: str,
    ) -> None:
        """EOS-124 정렬 재선택도 1차 선택과 **같은 요청 상황**으로 고른다 — 연습 경로가 학습 밴드를
        강제했으면 선수로 내려가는 재선택도 학습 밴드다. 지시가 없으면 원래 요청 그대로(대조군)."""
        _spies, routes, anchor_reasons = r6_policy_env
        routes.append(
            None
            if route_outcome is None
            else lsr.StateRoute(
                outcome=route_outcome, concept_id=_CONCEPT, candidate_rows=((_SAME, 3.0, None),)
            )
        )
        weak = build_reason(concept_id=_CONCEPT, mastery=0.15, confidence=0.6)
        anchor_reasons.append(weak)
        purposes: list[str] = []

        async def _reselecting(*_a: Any, **_k: Any) -> PolicyIntent:
            return PolicyIntent(
                reason=weak, resolution=IntentResolution.SERVED, reselect_groups=((_PRE_A,),)
            )

        async def _select_aligned(_self: Any, _groups: Any, **kwargs: Any) -> None:
            purposes.append(kwargs["learning_context"].purpose)
            return None

        monkeypatch.setattr(policy_module, "resolve_policy_intent", _reselecting)
        monkeypatch.setattr(CatRecommendationPolicy, "_select_aligned", _select_aligned)
        outcome = await self._call()
        assert purposes == [purpose]
        assert outcome.intent_resolution is IntentResolution.TARGET_UNAVAILABLE

    async def test_policy_injects_its_own_budgeted_prerequisite_reader(
        self,
        r6_policy_env: tuple[_R6Spies, list[lsr.StateRoute | None], list[RecommendationReason]],
    ) -> None:
        """예산은 정책이 소유한다 — 이음매에 넘기는 읽기 함수가 정책 자신의 `_read_prerequisites`다."""
        spies, routes, anchor_reasons = r6_policy_env
        routes.append(None)
        anchor_reasons.append(build_reason(concept_id=_ANCHOR, mastery=None, confidence=None))
        policy = CatRecommendationPolicy(cast(AsyncSession, object()))
        await self._call(policy)
        assert spies.route_kwargs["read_prerequisites"] == policy._read_prerequisites

    async def test_advance_band_anchor_is_demoted_on_the_r6_path(
        self,
        r6_policy_env: tuple[_R6Spies, list[lsr.StateRoute | None], list[RecommendationReason]],
    ) -> None:
        """부가 안전장치 — R6 경로의 앵커가 전진 구간이어도 전진하지 않는다(해소 `state_withheld`).

        닿는 경로는 막히지 않은 오답이다: 사전 숙달 0.95인 학생은 오답 1회로 약 0.73까지만
        내려가 막힘 문턱(0.4) 위에 남고, 같은 개념 연습의 앵커가 전진 구간이 된다. 막은 주체는
        측정이 아니라 R6 결정이므로 `refuted`(측정 반증)와 구별한다."""
        spies, routes, anchor_reasons = r6_policy_env
        routes.append(
            lsr.StateRoute(
                outcome=lsr.StateDirectiveOutcome.SAME_CONCEPT_NOT_BLOCKED,
                concept_id=_ANCHOR,
                candidate_rows=((_SAME, 3.0, None),),
            )
        )
        anchor_reasons.append(build_reason(concept_id=_ANCHOR, mastery=0.73, confidence=0.6))
        outcome = await self._call()
        assert spies.intent_calls == 0  # 전진 재선택(그래프 읽기)을 돌리지 않는다
        assert outcome.problem_id == _SAME
        assert outcome.action is RecommendationAction.PRACTICE_CURRENT
        assert outcome.reason.type is ReasonType.CURRENT_CONCEPT
        assert outcome.reason.mastery == 0.73  # 실측은 그대로 — 강등은 행위만 바꾼다
        assert outcome.target_concept == _ANCHOR
        assert outcome.intent_resolution is IntentResolution.STATE_WITHHELD
        assert outcome.band_calibrated is False  # 연습 경로 — 학습 밴드

    async def test_advance_guard_is_confined_to_the_r6_path(
        self,
        r6_policy_env: tuple[_R6Spies, list[lsr.StateRoute | None], list[RecommendationReason]],
    ) -> None:
        """대조군 — 지시가 없으면 전진 구간 앵커는 EOS-124 해소로 간다(가드가 새지 않는다)."""
        spies, routes, anchor_reasons = r6_policy_env
        routes.append(None)
        anchor_reasons.append(build_reason(concept_id=_ANCHOR, mastery=0.73, confidence=0.6))
        outcome = await self._call()
        assert spies.intent_calls == 1
        assert outcome.policy_version == POLICY_VERSION_CAT
        assert outcome.learning_state_directive is None

    @pytest.mark.parametrize(
        "outcome_kind",
        [
            lsr.StateDirectiveOutcome.ANCHOR_UNRESOLVED,
            lsr.StateDirectiveOutcome.NO_CANDIDATE_IN_CONCEPT,
        ],
    )
    async def test_unrestricted_r6_takes_the_default_path_but_reports_why(
        self,
        r6_policy_env: tuple[_R6Spies, list[lsr.StateRoute | None], list[RecommendationReason]],
        outcome_kind: lsr.StateDirectiveOutcome,
    ) -> None:
        spies, routes, anchor_reasons = r6_policy_env
        routes.append(lsr.StateRoute(outcome=outcome_kind, concept_id=_CONCEPT))
        anchor_reasons.append(build_reason(concept_id=_ANCHOR, mastery=None, confidence=None))
        outcome = await self._call()
        assert outcome.problem_id == _FALLBACK
        assert spies.loaded_default_pool == 1
        assert outcome.policy_version == POLICY_VERSION_CAT
        assert outcome.learning_state_directive is outcome_kind


class TestPolicyPrerequisiteReader:
    """`CatRecommendationPolicy._read_prerequisites` — 이음매에 주입되는 선수 읽기의 예산 3장치."""

    async def test_depth_is_the_request_capped_by_the_budget_ceiling(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        depths: list[int] = []

        async def _fetch(_s: Any, _cid: uuid.UUID, *, max_depth: int) -> list[PrerequisiteRow]:
            depths.append(max_depth)
            return []

        monkeypatch.setattr(policy_module, "fetch_prerequisites", _fetch)
        policy = CatRecommendationPolicy(
            cast(AsyncSession, object()), graph_budget=ConceptGraphBudget(max_depth=2)
        )
        await policy._read_prerequisites(_CONCEPT, 1)
        await policy._read_prerequisites(_CONCEPT, 5)
        assert depths == [1, 2]

    async def test_visited_and_node_budget_apply(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rows = [_prereq(f"UC-{i}", uuid.uuid4()) for i in range(5)]

        async def _fetch(_s: Any, _cid: uuid.UUID, *, max_depth: int) -> list[PrerequisiteRow]:
            return [rows[0], *rows]  # 첫 행이 두 경로로 두 번 온다(diamond)

        monkeypatch.setattr(policy_module, "fetch_prerequisites", _fetch)
        policy = CatRecommendationPolicy(
            cast(AsyncSession, object()), graph_budget=ConceptGraphBudget(max_nodes=3)
        )
        got = await policy._read_prerequisites(_CONCEPT, 1)
        assert [row.concept_id for row in got] == [row.concept_id for row in rows[:3]]

    async def test_time_budget_raises_for_the_caller_to_judge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _slow(_s: Any, _cid: uuid.UUID, *, max_depth: int) -> list[PrerequisiteRow]:
            await asyncio.sleep(1.0)
            return []

        monkeypatch.setattr(policy_module, "fetch_prerequisites", _slow)
        policy = CatRecommendationPolicy(
            cast(AsyncSession, object()), graph_budget=ConceptGraphBudget(timeout_seconds=0.01)
        )
        with pytest.raises(TimeoutError):
            await policy._read_prerequisites(_CONCEPT, 1)
