"""L2 BKT↔ConceptMasteryHistory 결선 — *순수* 측정 계산 단위테스트 (hermetic).

`compute_mastery_record`(prior + 관측 → 다음 측정)를 전수 검증한다. DB 래퍼
`record_attempt_mastery`(SELECT 정렬·INSERT)는 통합테스트(`*_integration.py`)가 실 PG로 검증.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.assessment import ConceptMasteryHistory
from whymath_backend.l2 import (
    BktModel,
    BktParameters,
    compute_mastery_record,
    update_mastery,
)
from whymath_backend.l2.mastery_tracking import (
    get_current_mastery,
    get_primary_concept_id,
    record_attempt_mastery,
    record_problem_attempt_mastery,
)
from whymath_backend.schema.assessment_evidence import (
    AssessmentEvidence,
    build_assessment_evidence,
)

_M = BktModel()  # 기본 파라미터(p_init=0.3 등)
_UID = uuid.uuid4()
_CID = uuid.uuid4()
_PID = uuid.uuid4()
_T = datetime(2026, 1, 8, tzinfo=UTC)


def _evidence(correct: bool, observed_at: datetime = _T) -> AssessmentEvidence:
    """실 `AssessmentEvidence` — EOS-18 이후 적재 경로가 받는 타입(어댑터 폐기)."""
    return build_assessment_evidence(
        learner_id=_UID,
        problem_id=_PID,
        correct=correct,
        observed_at=observed_at,
        concept_evidence=(),
        skill_evidence=(),
        concept_mapping_present=False,
        skill_bridge_present=False,
    )


class _FakeResult:
    def __init__(self, row: Any) -> None:
        self._row = row

    def scalars(self) -> _FakeResult:
        return self

    def first(self) -> Any:
        return self._row


class _FakeSession:
    """`record_attempt_mastery`의 SELECT(직전 측정)·add·commit만 시뮬(stmt 무시).

    정렬 정확성(measured_at DESC)은 통합테스트가 실 PG로 검증 — 여기선 래퍼 로직(prior→계산
    →INSERT)만 본다. `prior` 인자가 직전 측정 행(또는 None).
    """

    def __init__(self, prior: ConceptMasteryHistory | None = None) -> None:
        self._prior = prior
        self.added: list[Any] = []
        self.commits = 0

    async def execute(self, _stmt: Any) -> _FakeResult:
        return _FakeResult(self._prior)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


class TestComputeMasteryRecord:
    def test_first_observation_uses_p_init(self) -> None:
        """prior None(첫 관측)이면 사전 P(L0)에서 갱신·표본 1."""
        rec = compute_mastery_record(None, None, True, _M)
        assert rec.mastery == round(update_mastery(_M.initial_mastery, True, _M.params), 2)
        assert rec.mastery == 0.69
        assert rec.sample_size == 1

    def test_first_observation_incorrect(self) -> None:
        rec = compute_mastery_record(None, None, False, _M)
        assert rec.mastery == 0.15
        assert rec.sample_size == 1

    def test_uses_prior_not_p_init(self) -> None:
        """prior가 주어지면 그 값에서 갱신(P(L0) 무시)."""
        rec = compute_mastery_record(0.69, 1, True, _M)
        assert rec.mastery == round(update_mastery(0.69, True, _M.params), 2)
        assert rec.mastery == 0.92

    def test_sample_size_increments(self) -> None:
        assert compute_mastery_record(0.5, 4, True, _M).sample_size == 5
        assert compute_mastery_record(0.5, None, True, _M).sample_size == 1

    def test_confidence_monotonic_in_sample_size(self) -> None:
        c1 = compute_mastery_record(0.5, 0, True, _M).confidence
        c10 = compute_mastery_record(0.5, 9, True, _M).confidence
        assert c10 > c1
        # n=5 → 5/(5+5)=0.5
        assert compute_mastery_record(0.5, 4, True, _M).confidence == 0.5

    def test_mastery_rounded_to_two_decimals(self) -> None:
        """Numeric(3,2) 정합 — 저장 정밀도(2자리)로 반올림."""
        rec = compute_mastery_record(0.3, 0, True, _M)
        assert rec.mastery == round(rec.mastery, 2)
        assert 0.0 <= rec.mastery <= 1.0

    def test_custom_model_params(self) -> None:
        params = BktParameters(p_init=0.6, p_slip=0.05, p_guess=0.1, p_transit=0.2)
        model = BktModel(params)
        rec = compute_mastery_record(None, None, True, model)
        assert rec.mastery == round(update_mastery(0.6, True, params), 2)

    def test_repeated_correct_increases_mastery(self) -> None:
        """연속 정답을 prior로 이어주면 숙달도가 단조 증가(학습 곡선)."""
        r1 = compute_mastery_record(None, None, True, _M)
        r2 = compute_mastery_record(r1.mastery, r1.sample_size, True, _M)
        r3 = compute_mastery_record(r2.mastery, r2.sample_size, True, _M)
        assert r1.mastery < r2.mastery < r3.mastery
        assert r3.sample_size == 3


def _prior_row(mastery: float | None, sample_size: int | None) -> ConceptMasteryHistory:
    return ConceptMasteryHistory(
        user_id=_UID,
        concept_id=_CID,
        measured_at=datetime(2026, 1, 1, tzinfo=UTC),
        mastery=mastery,
        confidence=None,
        sample_size=sample_size,
    )


class TestRecordAttemptMastery:
    """DB 래퍼 — 직전 측정 읽기→계산→INSERT(fake session·stmt 무시)."""

    async def test_first_observation_no_prior(self) -> None:
        """직전 측정 없으면 P(L0)에서 갱신·표본 1·새 행 add·commit."""
        fake = _FakeSession(prior=None)
        row = await record_attempt_mastery(
            cast(AsyncSession, fake), _CID, evidence=_evidence(True), model=_M
        )
        assert row.mastery == 0.69
        assert row.sample_size == 1
        assert row.user_id == _UID and row.concept_id == _CID
        assert fake.added == [row]
        assert fake.commits == 1

    async def test_reads_prior_and_updates(self) -> None:
        """직전 측정(0.69·표본1)을 prior로 → 0.92·표본 2."""
        fake = _FakeSession(prior=_prior_row(0.69, 1))
        row = await record_attempt_mastery(
            cast(AsyncSession, fake), _CID, evidence=_evidence(True), model=_M
        )
        assert row.mastery == 0.92
        assert row.sample_size == 2

    async def test_prior_with_null_mastery_falls_back_to_p_init(self) -> None:
        """직전 행은 있으나 mastery=NULL이면 P(L0)에서 시작."""
        fake = _FakeSession(prior=_prior_row(None, None))
        row = await record_attempt_mastery(
            cast(AsyncSession, fake), _CID, evidence=_evidence(True), model=_M
        )
        assert row.mastery == 0.69

    async def test_explicit_measured_at(self) -> None:
        ts = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        fake = _FakeSession(prior=None)
        row = await record_attempt_mastery(
            cast(AsyncSession, fake), _CID, evidence=_evidence(False, ts)
        )
        assert row.measured_at == ts
        assert row.mastery == 0.15  # 기본 모델·오답

    async def test_default_model_when_omitted(self) -> None:
        """model 생략 시 기본 BktModel 사용."""
        fake = _FakeSession(prior=None)
        row = await record_attempt_mastery(cast(AsyncSession, fake), _CID, evidence=_evidence(True))
        assert row.mastery == 0.69


class _QResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _QResult:
        return self

    def all(self) -> list[Any]:
        return self._rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _QueueSession:
    """execute 호출마다 미리 큐잉한 결과를 순서대로 반환 — 다중 쿼리(개념 조회 → 개념별
    prior) 시뮬. record_problem_attempt_mastery: execute#1=개념 id들·이후 N=개념별 prior."""

    def __init__(self, results: list[_QResult]) -> None:
        self._results = results
        self._i = 0
        self.added: list[Any] = []
        self.commits = 0

    async def execute(self, _stmt: Any) -> _QResult:
        result = self._results[self._i]
        self._i += 1
        return result

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


class TestGetCurrentMastery:
    """slice 70: (user, concept) 현재 숙달도 읽기 — 최신 측정 mastery·없으면 None."""

    async def test_returns_latest_mastery(self) -> None:
        prior = ConceptMasteryHistory(
            user_id=_UID,
            concept_id=_CID,
            measured_at=datetime(2026, 1, 1, tzinfo=UTC),
            mastery=0.75,
            confidence=0.6,
            sample_size=5,
        )
        fake = _FakeSession(prior=prior)
        assert await get_current_mastery(cast(AsyncSession, fake), _UID, _CID) == 0.75

    async def test_returns_none_when_no_history(self) -> None:
        fake = _FakeSession(prior=None)
        assert await get_current_mastery(cast(AsyncSession, fake), _UID, _CID) is None

    async def test_returns_none_when_mastery_null(self) -> None:
        prior = ConceptMasteryHistory(
            user_id=_UID,
            concept_id=_CID,
            measured_at=datetime(2026, 1, 1, tzinfo=UTC),
            mastery=None,
            confidence=None,
            sample_size=None,
        )
        fake = _FakeSession(prior=prior)
        assert await get_current_mastery(cast(AsyncSession, fake), _UID, _CID) is None


class TestGetPrimaryConceptId:
    """slice 70: 문항 대표 개념 — PRIMARY 우선·없으면 TESTED 폴백·둘 다 없으면 None."""

    async def test_primary_when_present(self) -> None:
        cid = uuid.uuid4()
        fake = _QueueSession([_QResult([cid])])
        assert await get_primary_concept_id(cast(AsyncSession, fake), uuid.uuid4()) == cid

    async def test_falls_back_to_tested(self) -> None:
        tested = uuid.uuid4()
        # execute#1=PRIMARY 없음 → #2=TESTED 폴백
        fake = _QueueSession([_QResult([]), _QResult([tested])])
        assert await get_primary_concept_id(cast(AsyncSession, fake), uuid.uuid4()) == tested

    async def test_none_when_no_concept(self) -> None:
        fake = _QueueSession([_QResult([]), _QResult([])])
        assert await get_primary_concept_id(cast(AsyncSession, fake), uuid.uuid4()) is None


class TestRecordProblemAttemptMastery:
    """채점 풀이 → 평가 개념 전파(개념 조회 → 개념별 갱신)."""

    async def test_propagates_to_all_assessed_concepts(self) -> None:
        cid1, cid2 = uuid.uuid4(), uuid.uuid4()
        ts = datetime(2026, 3, 1, tzinfo=UTC)
        # execute#1 → 두 개념·이후 각 개념 prior 없음
        fake = _QueueSession([_QResult([cid1, cid2]), _QResult([]), _QResult([])])
        records = await record_problem_attempt_mastery(
            cast(AsyncSession, fake), evidence=_evidence(True, ts), model=_M
        )
        assert [r.concept_id for r in records] == [cid1, cid2]
        assert all(r.mastery == 0.69 for r in records)  # 첫 관측·정답
        assert all(r.measured_at == ts for r in records)  # 한 풀이=같은 시각
        assert len(fake.added) == 2
        assert fake.commits == 1  # 다개념 = 단일 트랜잭션(원자성)

    async def test_multi_concept_single_transaction(self) -> None:
        """3개념도 add 3·commit 1 — 루프 N회·트랜잭션 1회(전부 성공 또는 전부 롤백)."""
        cids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        fake = _QueueSession([_QResult(cids), _QResult([]), _QResult([]), _QResult([])])
        records = await record_problem_attempt_mastery(
            cast(AsyncSession, fake), evidence=_evidence(True), model=_M
        )
        assert len(records) == 3
        assert len(fake.added) == 3
        assert fake.commits == 1

    async def test_no_mapped_concepts_returns_empty(self) -> None:
        """문제↔개념 매핑이 없으면 숙달 갱신 0(빈 리스트·add 0)."""
        fake = _QueueSession([_QResult([])])
        records = await record_problem_attempt_mastery(
            cast(AsyncSession, fake), evidence=_evidence(True)
        )
        assert records == []
        assert fake.added == []
        assert fake.commits == 0

    async def test_single_concept_incorrect(self) -> None:
        cid = uuid.uuid4()
        fake = _QueueSession([_QResult([cid]), _QResult([])])
        records = await record_problem_attempt_mastery(
            cast(AsyncSession, fake), evidence=_evidence(False), model=_M
        )
        assert len(records) == 1
        assert records[0].mastery == 0.15  # 오답
        assert fake.commits == 1  # 1개념 = 1 트랜잭션

    async def test_incorrect_blames_primary_only(self) -> None:
        """모델 B — 오답은 PRIMARY에만 귀속. PRIMARY 존재 시 TESTED 쿼리·갱신 0(거짓 약점 0)."""
        cid_p = uuid.uuid4()
        # 큐: PRIMARY 쿼리→[cid_p], cid_p prior→[]. (PRIMARY 비지 않아 TESTED 폴백 미발생)
        fake = _QueueSession([_QResult([cid_p]), _QResult([])])
        records = await record_problem_attempt_mastery(
            cast(AsyncSession, fake), evidence=_evidence(False), model=_M
        )
        assert [r.concept_id for r in records] == [cid_p]  # PRIMARY만
        assert len(fake.added) == 1  # TESTED는 add 안 됨
        assert fake.commits == 1

    async def test_incorrect_falls_back_to_tested_when_no_primary(self) -> None:
        """모델 B — PRIMARY 미매핑인 퇴화 문항은 TESTED로 폴백(신호 손실 방지)."""
        cid_t = uuid.uuid4()
        # 큐: PRIMARY 쿼리→[](없음), TESTED 폴백 쿼리→[cid_t], cid_t prior→[].
        fake = _QueueSession([_QResult([]), _QResult([cid_t]), _QResult([])])
        records = await record_problem_attempt_mastery(
            cast(AsyncSession, fake), evidence=_evidence(False), model=_M
        )
        assert [r.concept_id for r in records] == [cid_t]
        assert fake.commits == 1

    async def test_correct_supports_all_assessed(self) -> None:
        """모델 B — 정답은 PRIMARY+TESTED *전체* 지지(합동 증거·비대칭의 반대편)."""
        cid_p, cid_t = uuid.uuid4(), uuid.uuid4()
        # 큐: assessed 쿼리→[cid_p, cid_t], 각 prior→[].
        fake = _QueueSession([_QResult([cid_p, cid_t]), _QResult([]), _QResult([])])
        records = await record_problem_attempt_mastery(
            cast(AsyncSession, fake), evidence=_evidence(True), model=_M
        )
        assert [r.concept_id for r in records] == [cid_p, cid_t]  # 둘 다 지지
        assert all(r.mastery == 0.69 for r in records)  # 정답·첫 관측 상승


class TestForgettingInRecord:
    """slice L2-6: 경과일 망각이 compute/record에 반영(p_forget=0 기본은 무영향)."""

    def test_compute_elapsed_no_effect_default_model(self) -> None:
        """기본 모델(p_forget=0)은 elapsed_days 무관."""
        m = BktModel()
        assert compute_mastery_record(0.9, 1, True, m, elapsed_days=100) == compute_mastery_record(
            0.9, 1, True, m, elapsed_days=0
        )

    def test_compute_forgetting_lowers_result(self) -> None:
        """망각 모델: 경과일이 길수록 prior 감쇠 → 갱신 결과 낮아짐."""
        m = BktModel(BktParameters(p_forget=0.1))
        decayed = compute_mastery_record(0.9, 1, True, m, elapsed_days=20).mastery
        fresh = compute_mastery_record(0.9, 1, True, m, elapsed_days=0).mastery
        assert decayed < fresh

    async def test_record_computes_elapsed_from_prior(self) -> None:
        """record_attempt_mastery가 직전 측정~now 경과일로 망각 적용."""
        model = BktModel(BktParameters(p_forget=0.1))
        # 직전 측정 2026-01-01·mastery 0.9 → 30일 후 관측
        fake_late = _FakeSession(prior=_prior_row(0.9, 1))
        row_late = await record_attempt_mastery(
            cast(AsyncSession, fake_late),
            _CID,
            evidence=_evidence(True, datetime(2026, 1, 31, tzinfo=UTC)),
            model=model,
        )
        # 같은 날 관측(경과 0·감쇠 없음)
        fake_same = _FakeSession(prior=_prior_row(0.9, 1))
        row_same = await record_attempt_mastery(
            cast(AsyncSession, fake_same),
            _CID,
            evidence=_evidence(True, datetime(2026, 1, 1, tzinfo=UTC)),
            model=model,
        )
        assert row_late.mastery < row_same.mastery
