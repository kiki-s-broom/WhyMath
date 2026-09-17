"""EOS-13 Mastery 갱신 **호출 계약** — 형태·교체 가능성·행동 동결 검증(hermetic).

이 파일이 지키는 것은 알고리즘이 아니라 *형태*다. 네 축을 본다:

① **계약 형태** — `update_mastery(learner_state, assessment_evidence) -> MasteryUpdate`가
   상태·증거를 받고, 산출이 자기 출처(`estimator_id`)와 대상을 말한다.
② **교체 가능성**(acceptance ⑤) — 가짜 추정기를 레지스트리에 꽂으면 **호출부 수정 0**으로
   적재 값이 바뀐다. 정상 입력에서 초록인 것은 교체 가능성의 증거가 아니므로, 실제로 바꿔 보고
   *바뀌었는지*를 잰다. 계약을 만족하지 않는 구현은 RED가 된다.
③ **행동 동결**(acceptance ④) — 계약 경유 산출이 기존 커널 `compute_mastery_record`와
   **같은 값**이다(그리드 전수 대조). 값이 달라지면 리팩터가 아니라 정책 변경이다.
④ **축 통합**(acceptance ③) — 개념 축·스킬 축이 같은 함수·같은 수학을 쓰고, 축은 계산을
   가르지 않는다(재계산 0).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.assessment import ConceptMasteryHistory, SkillMasteryHistory
from whymath_backend.l2.bkt import BktModel, BktParameters
from whymath_backend.l2.mastery_contract import (
    BKT_ESTIMATOR_ID,
    AttemptOutcomeEvidence,
    BktMasteryEstimator,
    UnknownMasteryEstimatorError,
    active_estimator_id,
    compute_mastery_record,
    register_estimator,
    registered_estimator_ids,
    resolve_estimator,
    unregister_estimator,
    update_mastery,
    use_estimator,
)
from whymath_backend.l2.mastery_tracking import (
    record_attempt_mastery,
    record_problem_attempt_mastery,
)
from whymath_backend.l2.skill_mastery_tracking import record_problem_attempt_skill_mastery
from whymath_backend.schema.enums import ConceptRole
from whymath_backend.schema.learning_loop_contract import (
    LOOP_RELATIONS,
    LoopEdge,
    LoopObject,
    is_declared_relation,
)
from whymath_backend.schema.mastery_contract import (
    CONTRACT_RELATION,
    MASTERY_AXIS_LOOP_OBJECT,
    AssessmentEvidenceInput,
    LearnerMasteryState,
    MasteryAxis,
    MasteryContractError,
    MasteryEstimator,
    MasteryUpdate,
)

_UID = uuid.uuid4()
_CID = uuid.uuid4()
_SID = "skill.compute-fraction"
_T0 = datetime(2026, 1, 1, tzinfo=UTC)
_T1 = datetime(2026, 1, 8, tzinfo=UTC)

# 가짜 추정기 id — 실제 추정기와 절대 겹치지 않도록 접두사를 붙인다.
_STUB_ID = "test-stub-always-half"
_STUB_MASTERY = 0.5


def _state(
    axis: MasteryAxis = MasteryAxis.CONCEPT,
    *,
    mastery: float | None = None,
    sample_size: int | None = None,
    measured_at: datetime | None = None,
    target_id: str | None = None,
) -> LearnerMasteryState:
    return LearnerMasteryState(
        axis=axis,
        target_id=(
            (str(_CID) if axis is MasteryAxis.CONCEPT else _SID) if target_id is None else target_id
        ),
        mastery=mastery,
        sample_size=sample_size,
        measured_at=measured_at,
    )


def _evidence(correct: bool, observed_at: datetime = _T1) -> AttemptOutcomeEvidence:
    return AttemptOutcomeEvidence(correct=correct, observed_at=observed_at)


# ── 가짜 구현들(교체 가능성·계약 위반 검출용) ─────────────────────────────────


class _AlwaysHalfEstimator:
    """항상 0.5를 내는 스텁 — BKT를 상속하지 않는다(구조적 교체의 실증)."""

    @property
    def estimator_id(self) -> str:
        return _STUB_ID

    def estimate(
        self,
        learner_state: LearnerMasteryState,
        assessment_evidence: AssessmentEvidenceInput,
    ) -> MasteryUpdate:
        return MasteryUpdate(
            axis=learner_state.axis,
            target_id=learner_state.target_id,
            mastery=_STUB_MASTERY,
            confidence=_STUB_MASTERY,
            sample_size=(learner_state.sample_size or 0) + 1,
            prior_mastery=learner_state.mastery,
            elapsed_days=learner_state.elapsed_days_until(assessment_evidence.observed_at),
            estimator_id=self.estimator_id,
        )


class _NotAnEstimator:
    """`estimate`가 없는 객체 — Protocol 계약 위반(레지스트리 방어선이 잡아야 한다)."""

    @property
    def estimator_id(self) -> str:
        return "broken"


class _WrongTargetEstimator:
    """다른 대상의 갱신을 반환하는 추정기 — 가장 위험한 실패(남의 숙달 덮어쓰기)."""

    @property
    def estimator_id(self) -> str:
        return "wrong-target"

    def estimate(
        self,
        learner_state: LearnerMasteryState,
        assessment_evidence: AssessmentEvidenceInput,
    ) -> MasteryUpdate:
        return MasteryUpdate(
            axis=learner_state.axis,
            target_id="어딘가-다른-대상",
            mastery=0.9,
            confidence=0.9,
            sample_size=1,
            prior_mastery=None,
            elapsed_days=None,
            estimator_id=self.estimator_id,
        )


@dataclass(frozen=True, slots=True)
class _FutureAssessmentEvidence:
    """`EOS-12`가 착지시킬 `AssessmentEvidence`의 대역 — **상속 없이** Protocol을 만족한다.

    이 테스트가 지키는 이음매: EOS-12의 구체 타입은 `correct`·`observed_at` 두 속성만 있으면
    이 계약에 그대로 꽂힌다(필드를 더 들고 있어도 무방하다 — 계약은 그것을 읽지 않는다).
    """

    correct: bool
    observed_at: datetime
    # 계약이 읽지 않는 부가 필드(EOS-12가 들고 올 법한 것) — 있어도 계약은 무관심하다.
    misconception_ids: tuple[str, ...] = ()


# ── DB 시뮬(기존 테스트 패턴 재사용) ──────────────────────────────────────────


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return self._rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _QueueSession:
    """execute 호출마다 큐잉된 결과를 순서대로 반환(stmt 무시)."""

    def __init__(self, results: list[_Result]) -> None:
        self._results = results
        self._i = 0
        self.added: list[Any] = []
        self.commits = 0

    async def execute(self, _stmt: Any) -> _Result:
        result = self._results[self._i]
        self._i += 1
        return result

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


def _as_session(fake: _QueueSession) -> AsyncSession:
    return cast(AsyncSession, cast(object, fake))


# ── ① 계약 형태 ───────────────────────────────────────────────────────────────


class TestContractShape:
    """`update_mastery(learner_state, assessment_evidence) -> MasteryUpdate`의 형태."""

    def test_takes_state_and_evidence_returns_update(self) -> None:
        update = update_mastery(_state(), _evidence(True))
        assert isinstance(update, MasteryUpdate)
        assert update.axis is MasteryAxis.CONCEPT
        assert update.target_id == str(_CID)

    def test_update_reports_which_estimator_ran(self) -> None:
        """산출이 자기 출처를 말한다 — "무엇이 돌았는지 모르는 상태"를 만들지 않는다."""
        assert update_mastery(_state(), _evidence(True)).estimator_id == BKT_ESTIMATOR_ID

    def test_first_observation_keeps_prior_none_not_zero(self) -> None:
        """미측정은 None으로 남는다(0으로 접지 않는다 — CLAUDE.md None ≠ 0)."""
        update = update_mastery(_state(), _evidence(True))
        assert update.prior_mastery is None
        assert update.elapsed_days is None

    def test_prior_zero_differs_from_prior_none(self) -> None:
        """prior=0.0("재봤더니 0")과 prior=None("안 재봤다")은 다른 입력이다."""
        measured = update_mastery(_state(mastery=0.0, sample_size=3), _evidence(True))
        unmeasured = update_mastery(_state(), _evidence(True))
        assert measured.mastery != unmeasured.mastery
        assert measured.prior_mastery == 0.0
        assert unmeasured.prior_mastery is None

    def test_elapsed_days_computed_from_state(self) -> None:
        update = update_mastery(
            _state(mastery=0.6, sample_size=2, measured_at=_T0),
            _evidence(True, _T0 + timedelta(days=3)),
        )
        assert update.elapsed_days == pytest.approx(3.0)

    def test_rejects_out_of_range_prior(self) -> None:
        with pytest.raises(MasteryContractError):
            _state(mastery=1.4)

    def test_rejects_empty_target(self) -> None:
        with pytest.raises(MasteryContractError):
            _state(target_id="")

    def test_rejects_negative_sample_size(self) -> None:
        with pytest.raises(MasteryContractError):
            _state(mastery=0.5, sample_size=-1)

    def test_update_rejects_empty_estimator_id(self) -> None:
        """출처를 말하지 않는 산출은 만들어질 수 없다."""
        with pytest.raises(MasteryContractError):
            MasteryUpdate(
                axis=MasteryAxis.CONCEPT,
                target_id=str(_CID),
                mastery=0.5,
                confidence=0.5,
                sample_size=1,
                prior_mastery=None,
                elapsed_days=None,
                estimator_id="",
            )


class TestEvidenceProtocolSeam:
    """`AssessmentEvidenceInput` 이음매 — `EOS-12`의 구체 타입이 만족해야 하는 최소 계약."""

    def test_adapter_satisfies_protocol(self) -> None:
        assert isinstance(_evidence(True), AssessmentEvidenceInput)

    def test_future_assessment_evidence_satisfies_without_inheritance(self) -> None:
        """EOS-12가 상속 없이(구조적으로) 이 계약에 꽂힌다 — 두 번째 진실 원천 불요."""
        evidence = _FutureAssessmentEvidence(
            correct=True, observed_at=_T1, misconception_ids=("M-1",)
        )
        assert isinstance(evidence, AssessmentEvidenceInput)
        update = update_mastery(_state(), evidence)
        assert update.mastery == update_mastery(_state(), _evidence(True)).mastery

    def test_protocol_reads_exactly_two_attributes(self) -> None:
        """**필드 증식 방어선** — 계약이 읽는 속성이 늘면 이 테스트가 RED다.

        evidence의 구체 타입 좌석은 EOS-12가 소유한다. 여기서 속성을 늘리는 것은 두 번째
        진실 원천을 만드는 일이므로, 늘리려면 이 동결을 의식적으로 깨야 한다.
        """
        members = {
            name
            for name in AssessmentEvidenceInput.__protocol_attrs__  # type: ignore[attr-defined]
        }
        assert members == {"correct", "observed_at"}


class TestLoopVocabularyBinding:
    """계약이 루프 어휘(14객체·18관계)와 같은 말을 쓰는가."""

    def test_contract_relation_is_declared(self) -> None:
        assert CONTRACT_RELATION in LOOP_RELATIONS
        assert is_declared_relation(
            LoopObject.ASSESSMENT_EVIDENCE, LoopEdge.UPDATES, LoopObject.LEARNER_STATE
        )

    def test_every_axis_maps_to_a_loop_object(self) -> None:
        assert set(MASTERY_AXIS_LOOP_OBJECT) == set(MasteryAxis)
        assert MASTERY_AXIS_LOOP_OBJECT[MasteryAxis.CONCEPT] is LoopObject.CONCEPT
        assert MASTERY_AXIS_LOOP_OBJECT[MasteryAxis.SKILL] is LoopObject.SKILL


# ── ③ 행동 동결 ───────────────────────────────────────────────────────────────


class TestBehaviourFrozen:
    """계약 경유 산출 == 기존 커널 산출. 값이 달라지면 정책 변경이므로 RED여야 한다."""

    def test_matches_kernel_over_grid(self) -> None:
        model = BktModel()
        priors: list[tuple[float | None, int | None]] = [
            (None, None),
            (0.0, 0),
            (0.3, 1),
            (0.5, 4),
            (0.87, 12),
            (1.0, 30),
        ]
        for prior_mastery, prior_sample in priors:
            for correct in (True, False):
                for axis in (MasteryAxis.CONCEPT, MasteryAxis.SKILL):
                    expected = compute_mastery_record(
                        prior_mastery, prior_sample, correct, model, 0.0
                    )
                    got = update_mastery(
                        _state(axis, mastery=prior_mastery, sample_size=prior_sample),
                        _evidence(correct),
                    )
                    assert (got.mastery, got.confidence, got.sample_size) == expected

    def test_matches_kernel_with_forgetting(self) -> None:
        """망각 감쇠 경로도 동결 — 경과일이 계약으로 옮겨갔지만 값은 같다."""
        model = BktModel(BktParameters(p_forget=0.05))
        estimator = BktMasteryEstimator(model)
        for days in (0.0, 1.0, 7.0, 30.0):
            observed = _T0 + timedelta(days=days)
            expected = compute_mastery_record(0.9, 5, True, model, days)
            got = update_mastery(
                _state(mastery=0.9, sample_size=5, measured_at=_T0),
                _evidence(True, observed),
                estimator=estimator,
            )
            assert (got.mastery, got.confidence, got.sample_size) == expected
            assert got.elapsed_days == pytest.approx(days)

    def test_axis_does_not_change_the_math(self) -> None:
        """acceptance ③ — 계약은 하나이고 축은 계산을 가르지 않는다."""
        concept = update_mastery(
            _state(MasteryAxis.CONCEPT, mastery=0.42, sample_size=3), _evidence(False)
        )
        skill = update_mastery(
            _state(MasteryAxis.SKILL, mastery=0.42, sample_size=3), _evidence(False)
        )
        assert (concept.mastery, concept.confidence, concept.sample_size) == (
            skill.mastery,
            skill.confidence,
            skill.sample_size,
        )

    async def test_concept_staging_writes_kernel_values(self) -> None:
        """개념 축 적재 경로가 커널과 같은 값을 쓴다(계약 경유 전후 동일)."""
        prior = ConceptMasteryHistory(
            user_id=_UID,
            concept_id=_CID,
            measured_at=_T0,
            mastery=0.6,
            confidence=0.5,
            sample_size=4,
        )
        session = _QueueSession([_Result([prior])])
        row = await record_attempt_mastery(_as_session(session), _UID, _CID, True, measured_at=_T0)
        expected = compute_mastery_record(0.6, 4, True, BktModel(), 0.0)
        assert (row.mastery, row.confidence, row.sample_size) == expected


# ── ② 교체 가능성(acceptance ⑤) ───────────────────────────────────────────────


@pytest.fixture()
def stub_registered() -> Any:
    """가짜 추정기를 등록했다가 **반드시** 걷어낸다(전역 오염 0)."""
    register_estimator(_STUB_ID, _AlwaysHalfEstimator)
    try:
        yield
    finally:
        unregister_estimator(_STUB_ID)


class TestEstimatorRegistry:
    """레지스트리 자체의 계약 — 조용한 폴백 없음·조용한 덮어쓰기 없음."""

    def test_default_is_bkt(self) -> None:
        assert active_estimator_id() == BKT_ESTIMATOR_ID
        assert BKT_ESTIMATOR_ID in registered_estimator_ids()
        assert isinstance(resolve_estimator(), BktMasteryEstimator)

    def test_unknown_id_raises_instead_of_falling_back(self) -> None:
        with pytest.raises(UnknownMasteryEstimatorError):
            resolve_estimator("존재하지-않는-추정기")

    def test_use_estimator_rejects_unknown_id_at_entry(self) -> None:
        with pytest.raises(UnknownMasteryEstimatorError):
            with use_estimator("존재하지-않는-추정기"):
                pass  # pragma: no cover - 진입 자체가 막힌다

    def test_duplicate_registration_requires_explicit_replace(self) -> None:
        with pytest.raises(MasteryContractError):
            register_estimator(BKT_ESTIMATOR_ID, BktMasteryEstimator)

    def test_empty_id_rejected(self) -> None:
        with pytest.raises(MasteryContractError):
            register_estimator("", BktMasteryEstimator)

    def test_unregister_unknown_raises(self) -> None:
        with pytest.raises(UnknownMasteryEstimatorError):
            unregister_estimator("존재하지-않는-추정기")

    def test_bkt_satisfies_estimator_protocol(self) -> None:
        assert isinstance(BktMasteryEstimator(), MasteryEstimator)

    def test_broken_implementation_is_rejected_on_resolve(self, stub_registered: Any) -> None:
        """Protocol 계약을 깨는 구현은 레지스트리에서 나올 때 RED."""
        register_estimator("broken-stub", _NotAnEstimator, replace=True)
        try:
            with pytest.raises(MasteryContractError):
                resolve_estimator("broken-stub")
        finally:
            unregister_estimator("broken-stub")

    def test_wrong_target_update_is_rejected(self) -> None:
        """다른 대상의 갱신을 반환하면 적재되기 전에 막힌다."""
        with pytest.raises(MasteryContractError):
            update_mastery(_state(), _evidence(True), estimator=_WrongTargetEstimator())

    def test_default_restored_after_context(self, stub_registered: Any) -> None:
        with use_estimator(_STUB_ID):
            assert active_estimator_id() == _STUB_ID
        assert active_estimator_id() == BKT_ESTIMATOR_ID


class TestSwappableWithoutCallsiteEdits:
    """**acceptance ⑤의 본체** — 호출부를 한 글자도 고치지 않고 동작이 바뀌는가.

    적재 함수(`record_*`)의 시그니처·호출 형태는 아래 테스트 어디서도 바뀌지 않는다. 바뀌는
    것은 레지스트리의 기본 추정기 하나뿐이다.
    """

    async def test_concept_axis_swaps(self, stub_registered: Any) -> None:
        prior = ConceptMasteryHistory(
            user_id=_UID,
            concept_id=_CID,
            measured_at=_T0,
            mastery=0.6,
            confidence=0.5,
            sample_size=4,
        )
        baseline_session = _QueueSession([_Result([prior])])
        baseline = await record_attempt_mastery(
            _as_session(baseline_session), _UID, _CID, True, measured_at=_T1
        )
        assert baseline.mastery != _STUB_MASTERY  # 대조군: 기본 추정기는 0.5를 내지 않는다

        swapped_session = _QueueSession([_Result([prior])])
        with use_estimator(_STUB_ID):
            swapped = await record_attempt_mastery(
                _as_session(swapped_session), _UID, _CID, True, measured_at=_T1
            )
        assert swapped.mastery == _STUB_MASTERY
        assert swapped.sample_size == 5

    async def test_problem_propagation_swaps(self, stub_registered: Any) -> None:
        """다개념 전파(서빙 경로가 부르는 함수)도 교체된다."""
        session = _QueueSession([_Result([_CID]), _Result([])])
        with use_estimator(_STUB_ID):
            records = await record_problem_attempt_mastery(
                _as_session(session), _UID, uuid.uuid4(), True, measured_at=_T1
            )
        assert [r.mastery for r in records] == [_STUB_MASTERY]

    async def test_skill_axis_swaps(self, stub_registered: Any) -> None:
        """스킬 축도 **같은 레지스트리**를 본다(계약이 하나라는 것의 실증)."""
        session = _QueueSession([_Result([_CID]), _Result([_SID]), _Result([])])
        with use_estimator(_STUB_ID):
            records = await record_problem_attempt_skill_mastery(
                _as_session(session), _UID, uuid.uuid4(), True, measured_at=_T1
            )
        assert [(r.skill_id, r.mastery) for r in records] == [(_SID, _STUB_MASTERY)]

    async def test_explicit_model_overrides_registry(self, stub_registered: Any) -> None:
        """`model=` 명시는 명시적 덮어쓰기다 — 기본 교체보다 우선한다(하위호환)."""
        model = BktModel()
        session = _QueueSession([_Result([])])
        with use_estimator(_STUB_ID):
            row = await record_attempt_mastery(
                _as_session(session), _UID, _CID, True, model=model, measured_at=_T1
            )
        expected = compute_mastery_record(None, None, True, model, 0.0)
        assert (row.mastery, row.confidence, row.sample_size) == expected

    async def test_incorrect_answer_still_routes_through_contract(
        self, stub_registered: Any
    ) -> None:
        """오답 경로(PRIMARY 귀속)도 계약을 경유한다 — 정답 경로만 배선된 것이 아니다."""
        session = _QueueSession([_Result([_CID]), _Result([])])
        with use_estimator(_STUB_ID):
            records = await record_problem_attempt_mastery(
                _as_session(session),
                _UID,
                uuid.uuid4(),
                False,
                measured_at=_T1,
                assessed_roles=[ConceptRole.PRIMARY],
            )
        assert [r.mastery for r in records] == [_STUB_MASTERY]


class TestStagedRowsCarryUpdateFields:
    """적재 행이 계약 산출을 그대로 싣는다(값 재계산·재해석 0)."""

    async def test_skill_row_fields_match_contract(self) -> None:
        prior = SkillMasteryHistory(
            user_id=_UID,
            skill_id=_SID,
            measured_at=_T0,
            mastery=0.45,
            confidence=0.4,
            sample_size=2,
        )
        session = _QueueSession([_Result([_CID]), _Result([_SID]), _Result([prior])])
        records = await record_problem_attempt_skill_mastery(
            _as_session(session), _UID, uuid.uuid4(), True, measured_at=_T0
        )
        expected = update_mastery(
            _state(MasteryAxis.SKILL, mastery=0.45, sample_size=2, measured_at=_T0),
            _evidence(True, _T0),
        )
        assert [(r.mastery, r.confidence, r.sample_size) for r in records] == [
            (expected.mastery, expected.confidence, expected.sample_size)
        ]
