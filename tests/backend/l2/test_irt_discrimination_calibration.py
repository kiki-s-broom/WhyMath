"""EOS-129 — IRT 변별도 a 보정의 도달 비용 회귀·2PL 추정기·CAT 소비 배선 (hermetic).

세 축을 한 파일에서 동결한다.

① **도달 하한 회귀**(acceptance ①·④): a=1.0이면 SE ≤ `TARGET_SE`(0.3)에 이상적 적응 출제로도
   45문항이 하한이다. 같은 프로브를 a=1.5·2.0 문항 풀로 돌려 하한이 얼마나 내려가는지 실측값을
   고정한다 — 이 수들이 바뀌면 선택기·SE 공식·중단 임계 중 무엇인가가 바뀐 것이다.
② **2PL 추정기**(`estimate_item_parameters`): 회복·SE 게이트 변별·추정 불가 표시.
③ **CAT 소비**(`load_attempt_history_state`): a가 전부 NULL이면 종전 Rasch와 *같은* θ·SE,
   a가 채워지면 SE가 작아지고 적용 건수가 집계된다.
"""

from __future__ import annotations

import math
import random
import uuid
from statistics import NormalDist
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.l2.ability_estimation import (
    difficulty_to_logit,
    resolve_item_discrimination_a,
)
from whymath_backend.l2.irt import (
    IrtItem,
    ability_standard_error,
    estimate_ability,
    estimate_item_parameters,
    probability_correct,
    select_next_item,
)
from whymath_backend.l2.next_problem_selection import (
    MAX_ADMINISTERED_ITEMS,
    TARGET_SE,
    load_attempt_history_state,
)

# ── ① 도달 하한 프로브 ─────────────────────────────────────────────────────────────
# 코퍼스: 난이도 1.0~5.0 균등 201문항(0.02 간격) → `difficulty_to_logit`으로 b ∈ [-2, 2].
_CORPUS_SIZE = 201


def _corpus(discrimination: float) -> list[IrtItem]:
    return [
        IrtItem(
            difficulty=difficulty_to_logit(1.0 + 4.0 * k / (_CORPUS_SIZE - 1)),
            discrimination=discrimination,
        )
        for k in range(_CORPUS_SIZE)
    ]


def _analytic_lower_bound(discrimination: float, target_se: float = TARGET_SE) -> int:
    """SE ≤ target에 필요한 최소 문항 수 — 문항당 최대 정보 a²·0.25(P=0.5)로 총정보 1/SE²를 채움."""
    return math.ceil(1.0 / (target_se**2 * 0.25 * discrimination**2))


def _reach_fixed_theta(items: list[IrtItem], theta: float = 0.0) -> tuple[int, float]:
    """θ를 참값에 *고정*하고 정보량 최대 문항만 누적 — 순수 정보 축의 도달 문항 수와 그때 SE."""
    administered: set[int] = set()
    used: list[IrtItem] = []
    while True:
        index = select_next_item(theta, items, administered=administered)
        assert index is not None, "코퍼스 소진 — 프로브가 목표 SE에 닿지 못했다"
        administered.add(index)
        used.append(items[index])
        se = ability_standard_error(theta, used)
        if se <= TARGET_SE:
            return len(used), se


def _reach_adaptive(items: list[IrtItem], true_theta: float = 0.0) -> tuple[int, float]:
    """실제 CAT 루프 — θ̂로 다음 문항 선택 → 결정론 응답 → θ̂·SE 재추정, SE ≤ 목표까지.

    응답은 난수 없이 결정론으로 만든다: 참 θ에서의 기대 정답 누적과 실제 정답 누적의 차가 0.5
    이상이면 정답(기대값을 반올림으로 따라가는 응답열). 같은 입력 → 같은 문항 수.
    """
    administered: set[int] = set()
    responses: list[tuple[IrtItem, bool]] = []
    expected = 0.0
    correct_total = 0
    theta_hat = 0.0
    while True:
        index = select_next_item(theta_hat, items, administered=administered)
        assert index is not None, "코퍼스 소진 — 프로브가 목표 SE에 닿지 못했다"
        administered.add(index)
        item = items[index]
        expected += probability_correct(true_theta, item)
        correct = (expected - correct_total) >= 0.5
        correct_total += int(correct)
        responses.append((item, correct))
        theta_hat = estimate_ability(responses)
        se = ability_standard_error(theta_hat, [it for it, _ in responses])
        if se <= TARGET_SE:
            return len(responses), se


class TestReachLowerBound:
    """acceptance ①·④ — SE 0.3 도달 문항 수의 해석적 하한과 실측 프로브 동결."""

    @pytest.mark.parametrize(("a", "bound"), [(1.0, 45), (1.5, 20), (2.0, 12)])
    def test_analytic_lower_bound(self, a: float, bound: int) -> None:
        # a=1 → 1/(0.09·0.25)=44.4 → 45 · a=1.5 → 19.75 → 20 · a=2 → 11.1 → 12
        assert _analytic_lower_bound(a) == bound

    def test_rasch_needs_at_least_45_items_even_with_ideal_adaptive_selection(self) -> None:
        """① a=1.0(현행 폴백)이면 완벽한 적응 출제로도 45문항을 깰 수 없다.

        실측(2026-09-28): 고정 θ 46문항(SE 0.2975) · 적응 루프 46문항(SE 0.2998).
        EOS-126 주석의 "46문항(SE 0.2973)"과 같은 축이다.
        """
        items = _corpus(1.0)
        fixed_n, fixed_se = _reach_fixed_theta(items)
        adaptive_n, adaptive_se = _reach_adaptive(items)
        assert fixed_n >= _analytic_lower_bound(1.0) == 45
        assert adaptive_n >= 45
        assert (fixed_n, adaptive_n) == (46, 46)  # 실측 동결
        assert fixed_se <= TARGET_SE and adaptive_se <= TARGET_SE
        # a=1.0인 한 2차 중단 규칙(상한 20)이 정밀도 축보다 **먼저** 발화한다.
        assert adaptive_n > MAX_ADMINISTERED_ITEMS

    @pytest.mark.parametrize(
        ("a", "fixed_expected", "adaptive_expected"),
        # 실측(2026-09-28): a=1.5 → 고정 20(SE 0.2993)·적응 22(SE 0.2942)
        #                   a=2.0 → 고정 12(SE 0.2894)·적응 13(SE 0.2986)
        [(1.5, 20, 22), (2.0, 12, 13)],
    )
    def test_calibrated_discrimination_lowers_reach(
        self, a: float, fixed_expected: int, adaptive_expected: int
    ) -> None:
        """④ 변별도가 채워진 풀에서는 도달 문항 수가 하한을 따라 내려간다(실측 동결).

        읽는 법: a=2.0이면 적응 루프 13문항으로 상한(20) 전에 정밀도 축이 먼저 발화한다.
        a=1.5는 순수 정보 축(고정 θ)으로는 정확히 20이지만, θ̂ 재추정 비용 때문에 실제
        적응 루프는 22문항 — **상한이 여전히 먼저 발화한다**(비상구로 물러나려면 a≈2 필요).
        """
        items = _corpus(a)
        fixed_n, _ = _reach_fixed_theta(items)
        adaptive_n, _ = _reach_adaptive(items)
        bound = _analytic_lower_bound(a)
        assert fixed_n >= bound and adaptive_n >= bound
        assert (fixed_n, adaptive_n) == (fixed_expected, adaptive_expected)
        rasch_n, _ = _reach_adaptive(_corpus(1.0))
        assert adaptive_n < rasch_n  # a 보정은 실제로 도달 비용을 줄인다


# ── ② 2PL 문항 모수 추정기 ─────────────────────────────────────────────────────────
def _stratified(points: int, per_point: int, a: float, b: float) -> list[tuple[float, bool]]:
    """결정론 합성 응답 — θ는 N(0,1) 분위 격자, 각 격자점에서 정답 수 = round(n·P)."""
    nd = NormalDist()
    out: list[tuple[float, bool]] = []
    for k in range(points):
        theta = nd.inv_cdf((k + 0.5) / points)
        p = 1.0 / (1.0 + math.exp(-a * (theta - b)))
        n_correct = round(per_point * p)
        out += [(theta, True)] * n_correct + [(theta, False)] * (per_point - n_correct)
    return out


def _seeded(n: int, a: float, b: float, seed: int) -> list[tuple[float, bool]]:
    rng = random.Random(seed)
    out: list[tuple[float, bool]] = []
    for _ in range(n):
        theta = rng.gauss(0.0, 1.0)
        out.append((theta, rng.random() < 1.0 / (1.0 + math.exp(-a * (theta - b)))))
    return out


def _logistic_regression_reference(data: list[tuple[float, bool]]) -> tuple[float, float]:
    """독립 참조 구현 — y ~ c0 + c1·θ 로지스틱 회귀(IRLS). 2PL과 a=c1·b=-c0/c1로 동치."""
    c0 = c1 = 0.0
    for _ in range(100):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for theta, y in data:
            p = 1.0 / (1.0 + math.exp(-(c0 + c1 * theta)))
            w = p * (1.0 - p)
            r = (1.0 if y else 0.0) - p
            g0 += r
            g1 += r * theta
            h00 += w
            h01 += w * theta
            h11 += w * theta * theta
        det = h00 * h11 - h01 * h01
        c0 += (h11 * g0 - h01 * g1) / det
        c1 += (h00 * g1 - h01 * g0) / det
    return c1, -c0 / c1


class TestEstimateItemParameters:
    def test_recovers_true_parameters_with_400_responses(self) -> None:
        # 참 a=1.8·b=0.5, 400응답(40격자×10) → 실측 a=1.865·b=0.486·SE=0.197
        fit = estimate_item_parameters(_stratified(40, 10, 1.8, 0.5))
        assert fit.converged and not fit.a_clamped and not fit.b_clamped
        assert abs(fit.discrimination - 1.8) <= 0.3
        assert abs(fit.difficulty - 0.5) <= 0.3
        assert fit.discrimination_se <= 0.3

    def test_60_responses_fail_se_gate(self) -> None:
        # 같은 문항·60응답(12격자×5) → 실측 SE≈0.59 — 수렴은 하지만 a를 믿을 정밀도가 아니다.
        fit = estimate_item_parameters(_stratified(12, 5, 1.8, 0.5))
        assert fit.converged
        assert fit.discrimination_se > 0.3

    def test_matches_independent_logistic_regression(self) -> None:
        """θ 고정 조건부 2PL MLE는 로지스틱 회귀의 재매개화다 — 독립 구현과 수치 일치."""
        data = _seeded(400, 1.8, 0.5, seed=42)
        fit = estimate_item_parameters(data)
        ref_a, ref_b = _logistic_regression_reference(data)
        assert fit.discrimination == pytest.approx(ref_a, abs=1e-6)
        assert fit.difficulty == pytest.approx(ref_b, abs=1e-6)

    @pytest.mark.parametrize("value", [True, False])
    def test_all_same_response_is_not_estimable(self, value: bool) -> None:
        fit = estimate_item_parameters([(k / 10.0, value) for k in range(-20, 20)])
        assert not fit.converged
        assert math.isinf(fit.discrimination_se)
        assert (fit.discrimination, fit.difficulty) == (1.0, 0.0)  # 초기값 그대로

    def test_empty_is_not_estimable(self) -> None:
        fit = estimate_item_parameters([])
        assert not fit.converged and math.isinf(fit.discrimination_se)

    def test_identical_theta_is_singular(self) -> None:
        # θ 분산 0이면 a와 b를 가를 수 없다(정보행렬 특이) → 미수렴·SE inf.
        fit = estimate_item_parameters([(0.3, True), (0.3, False)] * 30)
        assert not fit.converged
        assert math.isinf(fit.discrimination_se)

    def test_perfect_separation_hits_upper_bound(self) -> None:
        # θ<0 전부 오답·θ>0 전부 정답(완전 분리) → a가 상한으로 발산 → a_clamped.
        data = [(t / 10.0, t > 0) for t in range(-30, 31) if t != 0]
        fit = estimate_item_parameters(data, max_iter=200)
        assert fit.a_clamped

    def test_deterministic(self) -> None:
        data = _seeded(200, 1.2, -0.3, seed=7)
        assert estimate_item_parameters(data) == estimate_item_parameters(data)


# ── ③ CAT 소비 배선 ────────────────────────────────────────────────────────────────
class TestResolveItemDiscriminationA:
    @pytest.mark.parametrize("value", [1.7, 0.4, 3.9])
    def test_positive_finite_used(self, value: float) -> None:
        assert resolve_item_discrimination_a(value) == value

    @pytest.mark.parametrize("value", [None, 0.0, -1.2, math.nan, math.inf])
    def test_missing_or_invalid_falls_back_to_rasch(self, value: float | None) -> None:
        assert resolve_item_discrimination_a(value) == 1.0


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _HistorySession:
    """`load_attempt_history_state`의 단일 SELECT에 미리 준 행을 돌려준다(stmt는 기록만)."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> _Result:
        self.statements.append(stmt)
        return _Result(self._rows)


def _rows(
    irt_a: float | None,
) -> list[tuple[uuid.UUID, bool, float, float | None, float | None, bool | None]]:
    """난이도 2~4 교대·정오답 교대 30건 — (problem_id, is_correct, difficulty, irt_b, irt_a,
    used_hint). 힌트 귀속은 전부 미상(None) — 이 테스트는 변별도 a만 잰다."""
    return [(uuid.uuid4(), k % 3 != 0, 2.0 + (k % 3), None, irt_a, None) for k in range(30)]


class TestLoadAttemptHistoryDiscrimination:
    async def test_null_a_is_byte_identical_to_rasch(self) -> None:
        """a 전부 NULL → 종전 계산(`IrtItem(difficulty=b)`)과 **같은** θ·SE(회귀 0)."""
        rows = _rows(None)
        state = await load_attempt_history_state(
            cast(AsyncSession, _HistorySession(rows)), uuid.uuid4()
        )
        legacy = [(IrtItem(difficulty=difficulty_to_logit(d)), c) for _p, c, d, _b, _a, _h in rows]
        theta = estimate_ability(legacy)
        assert state.theta == theta
        assert state.standard_error == ability_standard_error(theta, [i for i, _ in legacy])
        assert state.administered_count == 30
        assert state.discrimination_applied_count == 0

    async def test_calibrated_a_shrinks_standard_error(self) -> None:
        base = await load_attempt_history_state(
            cast(AsyncSession, _HistorySession(_rows(None))), uuid.uuid4()
        )
        sharp = await load_attempt_history_state(
            cast(AsyncSession, _HistorySession(_rows(2.0))), uuid.uuid4()
        )
        assert base.standard_error is not None and sharp.standard_error is not None
        assert sharp.standard_error < base.standard_error
        assert sharp.discrimination_applied_count == 30

    async def test_applied_count_counts_only_valid_a(self) -> None:
        rows = _rows(None)[:10] + _rows(1.6)[:5] + _rows(-0.5)[:3]
        state = await load_attempt_history_state(
            cast(AsyncSession, _HistorySession(rows)), uuid.uuid4()
        )
        assert state.administered_count == 18
        assert state.discrimination_applied_count == 5  # 음수 a는 폴백(적용 아님)

    async def test_select_reads_irt_a(self) -> None:
        session = _HistorySession([])
        await load_attempt_history_state(cast(AsyncSession, session), uuid.uuid4())
        assert "problem.irt_a" in str(session.statements[0])
