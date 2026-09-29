"""L2 문항 난이도 b 보정 — `item_calibration` 단위테스트 (hermetic·FakeSession).

slice 79: `_compute_calibrated_b`(순수 — 인덱싱·JMLE 적합·응답수 임계 필터)와
`calibrate_item_difficulties`(SELECT→보정→UPDATE→commit 글루)를 DB 없이 검증한다. 마이그레이션
↔ORM 정합·실 SQL은 `tests/backend/db/test_problem_irt_b_integration.py`(실 PG)가 가드.
"""

from __future__ import annotations

import math
import random
import uuid
from statistics import NormalDist
from typing import Any, cast

import pytest
from sqlalchemy import Select, Update
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.l2 import calibrate_item_difficulties
from whymath_backend.l2.irt import ItemFit
from whymath_backend.l2.item_calibration import (
    _MAX_DISCRIMINATION_SE,
    _MIN_RESPONSES_FOR_CALIBRATION,
    _MIN_RESPONSES_FOR_DISCRIMINATION,
    FALLBACK_A_AT_BOUND,
    FALLBACK_B_AT_BOUND,
    FALLBACK_INSUFFICIENT_RESPONSES,
    FALLBACK_NO_RESPONSE_VARIANCE,
    FALLBACK_NOT_CONVERGED,
    FALLBACK_REASONS,
    FALLBACK_SE_ABOVE_LIMIT,
    RESPONSE_COUNT_BUCKETS,
    _classify_discrimination,
    _compute_calibrated_b,
    _compute_calibration,
)


def _responses(item: uuid.UUID, corrects: list[bool]) -> list[tuple[uuid.UUID, uuid.UUID, bool]]:
    """문항 하나에 학생 N명(각기 다른 user_id)의 정오답 응답을 만든다."""
    return [(uuid.uuid4(), item, c) for c in corrects]


class TestComputeCalibratedB:
    """순수 보정 — 빈 입력·응답수 임계·난이도 방향."""

    def test_empty_returns_empty(self) -> None:
        assert _compute_calibrated_b([]) == {}

    def test_below_threshold_excluded(self) -> None:
        # 응답 < 임계 문항은 보정 보류(휴리스틱 유지).
        item = uuid.uuid4()
        rows = _responses(item, [True] * (_MIN_RESPONSES_FOR_CALIBRATION - 1))
        assert item not in _compute_calibrated_b(rows)

    def test_at_threshold_included(self) -> None:
        # 응답 ≥ 임계 문항은 보정 b를 채택(혼합 응답 → 유한 b).
        item = uuid.uuid4()
        corrects = [k % 2 == 0 for k in range(_MIN_RESPONSES_FOR_CALIBRATION)]
        result = _compute_calibrated_b(_responses(item, corrects))
        assert item in result
        assert isinstance(result[item], float)

    def test_easy_item_lower_b_than_hard(self) -> None:
        # 모두 맞힌 문항(쉬움)은 모두 틀린 문항(어려움)보다 낮은 b로 적합된다.
        students = [uuid.uuid4() for _ in range(_MIN_RESPONSES_FOR_CALIBRATION + 1)]
        easy, hard = uuid.uuid4(), uuid.uuid4()
        rows: list[tuple[uuid.UUID, uuid.UUID, bool]] = []
        for s in students:
            rows.append((s, easy, True))
            rows.append((s, hard, False))
        result = _compute_calibrated_b(rows)
        assert easy in result and hard in result
        assert result[easy] < result[hard]


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeSession:
    """SELECT엔 미리 준 응답 행을 돌려주고, UPDATE 호출·commit을 기록(글루만 검증)."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows
        self.updates: list[Update] = []
        self.committed = False

    async def execute(self, stmt: Any) -> _FakeResult:
        if isinstance(stmt, Update):
            self.updates.append(stmt)
            return _FakeResult([])
        assert isinstance(stmt, Select)  # 그 외엔 채점 응답 SELECT
        return _FakeResult(self._rows)

    async def commit(self) -> None:
        self.committed = True


class TestCalibrateItemDifficulties:
    """글루 — SELECT 응답 → 보정 문항만 UPDATE → commit → 리포트 반환(EOS-129: int → 리포트)."""

    async def test_updates_and_commits(self) -> None:
        item = uuid.uuid4()
        corrects = [k % 2 == 0 for k in range(_MIN_RESPONSES_FOR_CALIBRATION + 1)]
        rows = _responses(item, corrects)
        sess = _FakeSession(rows)
        report = await calibrate_item_difficulties(cast(AsyncSession, sess))
        assert report.calibrated_b == 1  # 1 문항(응답 ≥ 임계) 보정
        assert len(sess.updates) == 1
        assert sess.committed

    async def test_empty_no_updates_still_commits(self) -> None:
        sess = _FakeSession([])
        report = await calibrate_item_difficulties(cast(AsyncSession, sess))
        assert report.calibrated_b == 0
        assert report.discrimination_fallback_ratio is None  # 분모 0 → None(0으로 접지 않음)
        assert sess.updates == []
        assert sess.committed  # 빈 입력도 commit(무해)


# ── EOS-129: 2PL 변별도 a 단계 ────────────────────────────────────────────────────
def _synthetic_rows() -> tuple[list[tuple[uuid.UUID, uuid.UUID, bool]], dict[str, uuid.UUID]]:
    """결정론 합성 코퍼스 — 학생 400명(θ=N(0,1) 분위 격자) × 문항 10개 전원 응답 + 특수 문항 2개.

    - 문항 10개: 참 (a, b)가 서로 다른 2PL 문항(고정 seed 응답) → 전부 a 채택 대상
    - `small`: 30명만 응답 → b는 보정(≥5)되지만 a는 `insufficient_responses`
    - `easy`: 100명 전원 정답 → `no_response_variance`
    """
    rng = random.Random(20260928)
    nd = NormalDist()
    students = [uuid.UUID(int=i + 1) for i in range(400)]
    thetas = [nd.inv_cdf((k + 0.5) / 400) for k in range(400)]
    params = [
        (2.0, 0.0), (1.6, -0.5), (1.2, 0.5), (0.9, -1.0), (1.8, 1.0),
        (1.0, 0.0), (1.4, -1.5), (2.2, 0.3), (0.8, 0.8), (1.5, -0.2),
    ]  # fmt: skip
    items = [uuid.UUID(int=1000 + j) for j in range(len(params))]
    rows: list[tuple[uuid.UUID, uuid.UUID, bool]] = []
    for student, theta in zip(students, thetas, strict=True):
        for item, (a, b) in zip(items, params, strict=True):
            rows.append((student, item, rng.random() < 1.0 / (1.0 + math.exp(-a * (theta - b)))))
    small, easy = uuid.UUID(int=5000), uuid.UUID(int=6000)
    for student in students[:30]:
        rows.append((student, small, rng.random() < 0.5))
    for student in students[100:200]:
        rows.append((student, easy, True))
    named = {"sharpest": items[7], "flattest": items[8], "small": small, "easy": easy}
    return rows, named


@pytest.fixture(scope="module")
def synthetic() -> tuple[list[tuple[uuid.UUID, uuid.UUID, bool]], dict[str, uuid.UUID]]:
    return _synthetic_rows()


class TestComputeCalibration:
    """2단계 보정 계획 — 채택·사유 분류·분포·1PL 동작 불변."""

    def test_reports_adoption_and_reasons(
        self, synthetic: tuple[list[tuple[uuid.UUID, uuid.UUID, bool]], dict[str, uuid.UUID]]
    ) -> None:
        rows, named = synthetic
        plan = _compute_calibration(rows)
        report = plan.report
        assert report.items_with_responses == 12
        assert report.calibrated_b == 12
        assert report.discrimination_calibrated == 10
        assert report.discrimination_fallback == 2
        assert report.fallback_reasons[FALLBACK_INSUFFICIENT_RESPONSES] == 1
        assert report.fallback_reasons[FALLBACK_NO_RESPONSE_VARIANCE] == 1
        assert set(report.fallback_reasons) == set(FALLBACK_REASONS)  # 0건 사유도 표기
        assert report.discrimination_fallback_ratio == pytest.approx(2 / 12)
        assert report.response_count_distribution == {"1-4": 0, "5-49": 1, "50-99": 0, "100+": 11}
        assert report.boundary_theta_responses_excluded > 0  # 만점·영점 학생 응답은 a 입력 제외
        assert named["small"] not in plan.adopted and named["easy"] not in plan.adopted
        # 순위 보존 — 참 a=2.2 문항이 참 a=0.8 문항보다 큰 a로 적합된다(척도는 1PL θ 기준).
        assert (
            plan.adopted[named["sharpest"]].discrimination
            > plan.adopted[named["flattest"]].discrimination
        )

    def test_one_pl_stage_unchanged(
        self, synthetic: tuple[list[tuple[uuid.UUID, uuid.UUID, bool]], dict[str, uuid.UUID]]
    ) -> None:
        """2PL 단계를 붙여도 1PL b 산출은 그대로다(θ 척도의 정의)."""
        rows, _ = synthetic
        assert _compute_calibration(rows).calibrated_b == _compute_calibrated_b(rows)

    def test_empty_rows_ratio_none(self) -> None:
        report = _compute_calibration([]).report
        assert report.calibrated_b == 0
        assert report.discrimination_fallback_ratio is None
        assert report.response_count_distribution == dict.fromkeys(RESPONSE_COUNT_BUCKETS, 0)

    def test_small_corpus_all_insufficient(self) -> None:
        # b는 보정되지만(응답 6) a는 전부 폴백 — 비율 1.0("0건 작동"을 숨기지 않는다).
        item = uuid.uuid4()
        rows = _responses(item, [k % 2 == 0 for k in range(6)])
        report = _compute_calibration(rows).report
        assert report.calibrated_b == 1
        assert report.discrimination_calibrated == 0
        assert report.discrimination_fallback_ratio == 1.0
        assert report.response_count_distribution["5-49"] == 1


def _fit(**over: Any) -> ItemFit:
    base: dict[str, Any] = {
        "discrimination": 1.4,
        "difficulty": 0.2,
        "discrimination_se": 0.2,
        "converged": True,
        "a_clamped": False,
        "b_clamped": False,
    }
    base.update(over)
    return ItemFit(**base)


class TestClassifyDiscrimination:
    """채택 판정 게이트 — 사유별 1건씩 + 경계값."""

    def test_adopted(self) -> None:
        assert _classify_discrimination(_fit(), _MIN_RESPONSES_FOR_DISCRIMINATION, True) is None

    def test_insufficient(self) -> None:
        n = _MIN_RESPONSES_FOR_DISCRIMINATION - 1
        assert _classify_discrimination(_fit(), n, True) == FALLBACK_INSUFFICIENT_RESPONSES

    def test_no_variance(self) -> None:
        assert _classify_discrimination(None, 100, False) == FALLBACK_NO_RESPONSE_VARIANCE

    def test_not_converged(self) -> None:
        assert _classify_discrimination(_fit(converged=False), 100, True) == FALLBACK_NOT_CONVERGED
        assert _classify_discrimination(None, 100, True) == FALLBACK_NOT_CONVERGED

    def test_a_at_bound(self) -> None:
        assert _classify_discrimination(_fit(a_clamped=True), 100, True) == FALLBACK_A_AT_BOUND

    def test_b_at_bound(self) -> None:
        assert _classify_discrimination(_fit(b_clamped=True), 100, True) == FALLBACK_B_AT_BOUND

    def test_se_gate_boundary(self) -> None:
        at = _fit(discrimination_se=_MAX_DISCRIMINATION_SE)
        above = _fit(discrimination_se=_MAX_DISCRIMINATION_SE + 1e-9)
        assert _classify_discrimination(at, 100, True) is None  # 경계값은 채택(≤)
        assert _classify_discrimination(above, 100, True) == FALLBACK_SE_ABOVE_LIMIT
        infinite = _fit(discrimination_se=math.inf)
        assert _classify_discrimination(infinite, 100, True) == FALLBACK_SE_ABOVE_LIMIT


def _update_values(stmt: Update) -> dict[str, Any]:
    """UPDATE 문의 SET 절 값만 뽑는다(WHERE 바인드 제외)."""
    params = stmt.compile().params
    return {k: v for k, v in params.items() if k in ("irt_difficulty_b", "irt_a")}


class TestCalibrateDiscriminationPersistence:
    async def test_dry_run_writes_nothing(
        self, synthetic: tuple[list[tuple[uuid.UUID, uuid.UUID, bool]], dict[str, uuid.UUID]]
    ) -> None:
        rows, _ = synthetic
        sess = _FakeSession(rows)
        report = await calibrate_item_difficulties(cast(AsyncSession, sess), dry_run=True)
        assert report.dry_run is True
        assert report.discrimination_calibrated == 10  # 측정은 그대로 한다
        assert sess.updates == []  # UPDATE 0건
        assert sess.committed is False  # commit 0건

    async def test_adopted_items_persist_paired_a_and_b(
        self, synthetic: tuple[list[tuple[uuid.UUID, uuid.UUID, bool]], dict[str, uuid.UUID]]
    ) -> None:
        rows, _ = synthetic
        plan = _compute_calibration(rows)
        sess = _FakeSession(rows)
        report = await calibrate_item_difficulties(cast(AsyncSession, sess))
        assert report.dry_run is False and sess.committed
        assert len(sess.updates) == 12  # b 보정 대상 전부
        values = [_update_values(u) for u in sess.updates]
        with_a = [v for v in values if v["irt_a"] is not None]
        assert len(with_a) == 10
        adopted_pairs = {(f.difficulty, f.discrimination) for f in plan.adopted.values()}
        # a와 짝이 맞는 b는 1PL b가 아니라 **같은 2PL 적합의 b**다.
        assert {(v["irt_difficulty_b"], v["irt_a"]) for v in with_a} == adopted_pairs

    async def test_fallback_item_resets_stale_a_to_null(self) -> None:
        """이전에 채택됐다가 이번에 탈락한 문항의 낡은 a가 남지 않게 irt_a=NULL로 되돌린다."""
        item = uuid.uuid4()
        rows = _responses(item, [k % 2 == 0 for k in range(_MIN_RESPONSES_FOR_CALIBRATION + 1)])
        sess = _FakeSession(rows)
        await calibrate_item_difficulties(cast(AsyncSession, sess))
        assert len(sess.updates) == 1
        values = _update_values(sess.updates[0])
        assert "irt_a" in values and values["irt_a"] is None
        assert values["irt_difficulty_b"] == _compute_calibrated_b(rows)[item]
