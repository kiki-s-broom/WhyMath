"""EOS-24 — 추천이 학습 상태 머신의 결정을 **집행**하는가 (hermetic · DB 0).

설계 정본: `docs/reviews/eos24_recommendation_reads_learning_state_judgment_2026-09-25.md`.

이 파일이 지키는 넷:

① **무엇을 지시로 읽는가** — R3(`POLICY_REMEDIATE_MISCONCEPTION`)로 들어간 `REMEDIATING`만.
   R5의 `REMEDIATING`·PRACTICING·ADVANCING은 지시가 아니다(판정문 §3). 국면과 트리거를 **둘 다**
   본다 — 한쪽만 보는 뮤테이션을 잡는 반례가 각각 있다.
② **안전장치 4개가 실제로 막는가** — 교정 국면에서의 재실패(해제) · 이번 회차 가설 없음/하한 이하
   (신뢰 경계는 *리터럴*로 밟는다 — 상수를 import해 픽스처를 만들면 경계가 움직일 때 픽스처도 따라
   움직여 검출이 불가능하다 · MISC-30 1차 실행 교훈) · 교정 대상 개념 미해소 · 개념 안 후보 0.
③ **지시가 없으면 조회 0건** — 대다수 요청이 전환 전과 같은 쿼리 수·같은 결과를 낸다.
④ **정책 이음매** — 집행되면 후보·근거·목표·밴드·정책 버전이 전부 상태 경로에서 오고, 집행되지
   않으면 전환 전 경로를 그대로 탄다(지시 결과는 어느 쪽이든 응답에 실린다).

실 PG·HTTP 경로 단언은 `tests/backend/api/test_eos24_recommendation_follows_learning_state.py`가
전담한다(acceptance ③).
"""

from __future__ import annotations

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
from whymath_backend.l2.next_problem_selection import AttemptHistoryState
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
)
from whymath_backend.l2.recommendation_policy import CatRecommendationPolicy
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


async def _route(learner_state: LearnerState, session: AsyncSession) -> lsr.StateRoute | None:
    return await lsr.route_by_learning_state(
        session, learner_state, theta=-1.0, attempted_ids=set(), excluded_ids=set()
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

    async def _target(*_a: Any, reason: RecommendationReason, **_k: Any) -> uuid.UUID | None:
        return reason.concept_id

    real_band = policy_module.learning_band_weight

    def _band(theta: float, item: Any) -> float:
        spies.band_calls += 1
        return real_band(theta, item)

    monkeypatch.setattr(policy_module, "load_attempt_history_state", _history)
    monkeypatch.setattr(policy_module, "route_by_learning_state", _route_stub)
    monkeypatch.setattr(policy_module, "load_candidate_rows", _default_pool)
    monkeypatch.setattr(policy_module, "collect_remediation_reason", _remediation)
    monkeypatch.setattr(policy_module, "collect_recommendation_reason", _band_reason)
    monkeypatch.setattr(policy_module, "resolve_target_concept", _target)
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
