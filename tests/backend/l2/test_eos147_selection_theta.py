"""EOS-147 — 전부 정답 이력의 **선택 θ**(추천 표적)와 추정 θ의 분리 (hermetic · DB 0).

결함: 전부 정답이면 MLE가 존재하지 않아 `estimate_ability`가 상한(4.0)을 돌려주는데, 추천이 그
클램프를 표적으로 써서 첫 정답 뒤 은행에서 가장 어려운 문항으로 뛰었다(실 PG 실측 2.9 → 4.8).
판정(`docs/reviews/eos147_all_correct_theta_pin_judgment_2026-09-29.md`)은 **추정기를 그대로 두고**
추천이 쓰는 θ만 분리하는 안(C)이다. 이 파일은 그 결정의 두 반쪽을 지킨다.

① **바뀌는 것** — 선택 θ 규칙(경계 판정·단계·바닥·상한·단조성)과 그것이 두 정책의 **모든 소비
   지점**에 실제로 도달하는가(후보 풀 정렬·정보량 선택·후보 점수·학습 밴드 가중·정렬 재선택·상태
   머신 이음매·수능 후보 정렬/선택).
② **바뀌지 않는 것** — 추정기 출력·SE·`measurement_sufficient`·평가 캡처 입력·문항 보정의 경계 θ
   제외·처치 기록의 `theta`. 판정문 §2 소비처 지도의 "불변" 열이다.

**기대값은 전부 리터럴이다.** `ALL_CORRECT_STEP_LOGIT`을 import해 기대값을 만들면 그 상수를 바꾸는
뮤테이션을 테스트가 따라 움직여 잡지 못한다(MISC-30 교훈). 그래서 상수를 이 파일에서 읽는 곳은 "상수의
현재 값이 1.0인가"를 직접 묻는 한 테스트뿐이고, 나머지는 0.9·1.9 같은 숫자를 직접 쓴다.
변별력은 `scripts/analysis/mutate_eos147_selection_theta_guards.py`가 뮤테이션으로 확인한다.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.l2 import irt as irt_module
from whymath_backend.l2 import item_calibration
from whymath_backend.l2 import recommendation_policy as policy_module
from whymath_backend.l2.irt import (
    IrtItem,
    ability_boundary,
    ability_for_selection,
    ability_standard_error,
    estimate_ability,
)
from whymath_backend.l2.learner_state import LearnerState
from whymath_backend.l2.next_problem_selection import (
    AttemptHistoryState,
    load_attempt_history_state,
)
from whymath_backend.l2.prerequisite_recommendation import PrerequisiteRow
from whymath_backend.l2.recommendation_contract import (
    LearningContext,
    build_reason,
    no_candidate_reason,
)
from whymath_backend.l2.recommendation_evidence import (
    META_KEY_SELECTION_THETA,
    META_KEY_THETA,
    record_recommendation_treatment,
)
from whymath_backend.l2.recommendation_policy import CatRecommendationPolicy, NextProblemOutcome

_ABS = 1e-9


def _item(b: float) -> IrtItem:
    return IrtItem(difficulty=b)


def _all_correct(*bs: float) -> list[tuple[IrtItem, bool]]:
    return [(_item(b), True) for b in bs]


def _all_wrong(*bs: float) -> list[tuple[IrtItem, bool]]:
    return [(_item(b), False) for b in bs]


# ══════════════════════════════════════════════════════════════════════════
# ① 경계 판정 — 응답에서 판정한다(θ의 값이 아니라)
# ══════════════════════════════════════════════════════════════════════════
class TestAbilityBoundary:
    def test_empty_is_not_a_boundary(self) -> None:
        assert ability_boundary([]) is None

    @pytest.mark.parametrize("bs", [(0.0,), (-2.0, 2.0), (0.5, 0.5, 0.5, 0.5, 0.5)])
    def test_all_correct_is_upper(self, bs: tuple[float, ...]) -> None:
        assert ability_boundary(_all_correct(*bs)) == "upper"

    @pytest.mark.parametrize("bs", [(0.0,), (-2.0, 2.0), (1.0, 1.0, 1.0)])
    def test_all_wrong_is_lower(self, bs: tuple[float, ...]) -> None:
        assert ability_boundary(_all_wrong(*bs)) == "lower"

    def test_one_wrong_among_correct_is_not_a_boundary(self) -> None:
        assert ability_boundary(_all_correct(0.0, 0.0) + _all_wrong(0.5)) is None

    def test_one_correct_among_wrong_is_not_a_boundary(self) -> None:
        assert ability_boundary(_all_wrong(0.0, 0.0) + _all_correct(0.5)) is None

    def test_clamped_mixed_history_is_not_a_boundary(self) -> None:
        """오답이 섞여 MLE가 범위 밖으로 나가 4.0에 **클램프**된 이력은 식별 불가가 아니다.

        MLE는 존재한다(>4). 이 이력에 규칙을 걸면 진짜 추정을 표적 규칙으로 덮어쓰게 된다 —
        그래서 경계는 θ의 값(`>= 4.0`)이 아니라 응답에서 판정한다.
        """
        responses = _all_correct(*([3.0] * 20)) + _all_wrong(-4.0)
        assert estimate_ability(responses) == 4.0  # 전제: 실제로 상한에 붙는다
        assert ability_boundary(responses) is None
        assert ability_for_selection(responses, 4.0) == 4.0  # 규칙 밖 — 추정 θ 그대로

    @pytest.mark.parametrize("seed", range(40))
    def test_boundary_agrees_with_the_estimators_own_special_cases(self, seed: int) -> None:
        """`ability_boundary` ⇔ `estimate_ability`의 경계 특례 — 두 함수가 갈라지지 않는다."""
        rnd = random.Random(seed)
        n = rnd.randint(0, 6)
        mode = rnd.choice(["all_correct", "all_wrong", "mixed"])
        responses: list[tuple[IrtItem, bool]] = []
        for i in range(n):
            if mode == "all_correct":
                correct = True
            elif mode == "all_wrong":
                correct = False
            else:
                correct = i % 2 == 0
            responses.append((_item(rnd.uniform(-2.0, 2.0)), correct))
        boundary = ability_boundary(responses)
        theta = estimate_ability(responses)
        if boundary == "upper":
            assert theta == 4.0
        elif boundary == "lower":
            assert theta == -4.0
        elif not responses:
            assert theta == 0.0
        else:
            assert -4.0 < theta < 4.0 or len({c for _, c in responses}) == 2


# ══════════════════════════════════════════════════════════════════════════
# ② 선택 θ 규칙 — 리터럴 기대값
# ══════════════════════════════════════════════════════════════════════════
class TestAbilityForSelection:
    def test_step_constant_is_one_logit(self) -> None:
        """상수 자체의 현재 값 — 이 값을 바꾸면 이 테스트가 먼저 말한다(판정문 §4-2)."""
        assert irt_module.ALL_CORRECT_STEP_LOGIT == 1.0

    def test_first_correct_is_one_step_above_the_solved_difficulty(self) -> None:
        """실 PG 재현의 모양 — 난이도 라벨 2.9(b=-0.1)를 맞히면 표적은 0.9(라벨 3.9)다."""
        assert ability_for_selection(_all_correct(-0.1), 4.0) == pytest.approx(0.9, abs=_ABS)

    def test_uses_the_hardest_solved_difficulty(self) -> None:
        got = ability_for_selection(_all_correct(-0.1, 0.4, 0.9), 4.0)
        assert got == pytest.approx(1.9, abs=_ABS)

    def test_is_independent_of_answer_order(self) -> None:
        assert ability_for_selection(_all_correct(0.9, -0.1, 0.4), 4.0) == pytest.approx(
            1.9, abs=_ABS
        )

    def test_does_not_depend_on_how_many_were_solved(self) -> None:
        """정답 개수(n)를 쓰지 않는다 — 같은 최고 난이도면 1개든 10개든 같은 표적(판정문 §9-2)."""
        assert ability_for_selection(_all_correct(*([-0.1] * 10)), 4.0) == pytest.approx(
            0.9, abs=_ABS
        )

    def test_never_drops_below_the_cold_start(self) -> None:
        """아주 쉬운 문항(b=-2)만 맞혀도 표적은 시작점(0.0)이다 — 정답이 표적을 낮추지 않는다."""
        assert ability_for_selection(_all_correct(-2.0), 4.0) == 0.0
        assert ability_for_selection(_all_correct(-2.0, -1.5), 4.0) == 0.0

    def test_cold_start_floor_is_exactly_reached_at_minus_one(self) -> None:
        """바닥의 경계 — b=-1이면 b+1=0.0으로 바닥과 같고, b=-1.01이면 바닥이 이긴다."""
        assert ability_for_selection(_all_correct(-1.0), 4.0) == 0.0
        assert ability_for_selection(_all_correct(-1.01), 4.0) == 0.0

    def test_is_capped_at_the_upper_bound(self) -> None:
        """맞힌 최고 난이도 + 1이 상한을 넘으면 상한이다(보정 b는 ±4까지 갈 수 있다)."""
        assert ability_for_selection(_all_correct(3.5), 4.0) == 4.0
        assert ability_for_selection(_all_correct(3.0), 4.0) == 4.0
        assert ability_for_selection(_all_correct(2.9), 4.0) == pytest.approx(3.9, abs=_ABS)

    def test_step_argument_overrides_the_default(self) -> None:
        assert ability_for_selection(_all_correct(-0.1), 4.0, step=0.5) == pytest.approx(
            0.4, abs=_ABS
        )

    def test_mixed_history_returns_the_estimate_untouched(self) -> None:
        """혼합 이력은 규칙 밖이다 — **넘긴 추정 θ 그대로**(센티널로 재계산이 아님을 못박는다)."""
        mixed = _all_correct(0.0) + _all_wrong(0.5)
        assert ability_for_selection(mixed, 1.234) == 1.234

    def test_all_wrong_returns_the_estimate_untouched(self) -> None:
        """하한(전부 오답)은 이번 범위 밖이다 — 비대칭을 동결한다(판정문 §4-4)."""
        assert ability_for_selection(_all_wrong(0.0, 1.0), -4.0) == -4.0
        assert ability_for_selection(_all_wrong(0.0), 1.234) == 1.234

    def test_empty_returns_the_estimate_untouched(self) -> None:
        assert ability_for_selection([], 0.0) == 0.0
        assert ability_for_selection([], 1.234) == 1.234

    @pytest.mark.parametrize("seed", range(25))
    def test_is_monotone_non_decreasing_while_everything_stays_correct(self, seed: int) -> None:
        """정답이 늘 때 표적이 내려가지 않는다(맞힌 최고 난이도 앵커의 존재 이유)."""
        rnd = random.Random(seed)
        history: list[tuple[IrtItem, bool]] = []
        previous = ability_for_selection([], 0.0)
        for _ in range(8):
            history.append((_item(rnd.uniform(-2.0, 2.0)), True))
            current = ability_for_selection(history, 4.0)
            assert current >= previous
            assert 0.0 <= current <= 4.0
            previous = current

    def test_never_exceeds_the_estimators_boundary_value(self) -> None:
        """표적은 어떤 전부 정답 이력에서도 현행(상한 4.0) 이하 — 현행보다 어려워지지 않는다."""
        for seed in range(30):
            rnd = random.Random(seed)
            responses = _all_correct(*[rnd.uniform(-4.0, 4.0) for _ in range(rnd.randint(1, 9))])
            assert ability_for_selection(responses, estimate_ability(responses)) <= 4.0


# ══════════════════════════════════════════════════════════════════════════
# ③ AttemptHistoryState — 두 소비처가 다른 값을 읽는다
# ══════════════════════════════════════════════════════════════════════════
def _state(**over: Any) -> AttemptHistoryState:
    base: dict[str, Any] = {
        "attempted_ids": set(),
        "theta": 4.0,
        "standard_error": 7.9,
        "measurement_sufficient": False,
        "administered_count": 1,
    }
    base.update(over)
    return AttemptHistoryState(**base)


class TestAttemptHistoryStateSelectionTheta:
    def test_defaults_keep_pre_eos147_constructors_working(self) -> None:
        """이 필드 이전의 생성자 호출(테스트 스텁 등) — 선택 θ = 추정 θ, 경계 없음."""
        state = _state(theta=1.25)
        assert state.selection_theta == 1.25
        assert state.theta_boundary is None
        assert state.boundary_selection_theta is None

    def test_override_wins_for_selection_only(self) -> None:
        state = _state(theta=4.0, theta_boundary="upper", boundary_selection_theta=0.9)
        assert state.selection_theta == 0.9
        assert state.theta == 4.0  # 추정 θ는 그대로

    def test_a_zero_override_is_not_mistaken_for_missing(self) -> None:
        """0.0은 유효한 선택 θ다(콜드스타트 바닥) — `if override`(truthiness)로 읽으면 사라진다."""
        state = _state(theta=4.0, theta_boundary="upper", boundary_selection_theta=0.0)
        assert state.selection_theta == 0.0


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _HistorySession:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def execute(self, _stmt: Any) -> _Result:
        return _Result(self._rows)


def _row(
    correct: bool | None, difficulty: float | None, irt_b: float | None = None
) -> tuple[uuid.UUID, bool | None, float | None, float | None, float | None]:
    """`(problem_id, is_correct, difficulty_overall, irt_difficulty_b, irt_a)`."""
    return (uuid.uuid4(), correct, difficulty, irt_b, None)


async def _load(rows: list[Any]) -> AttemptHistoryState:
    return await load_attempt_history_state(cast(AsyncSession, _HistorySession(rows)), uuid.uuid4())


class TestLoadAttemptHistoryState:
    async def test_all_correct_splits_selection_from_estimate(self) -> None:
        """난이도 라벨 2.9 정답 1건 — 추정은 상한 4.0, 표적은 0.9(실 PG 재현과 같은 모양)."""
        state = await _load([_row(True, 2.9)])
        assert state.theta == 4.0
        assert state.theta_boundary == "upper"
        assert state.selection_theta == pytest.approx(0.9, abs=_ABS)

    async def test_estimate_and_precision_stay_byte_identical_for_all_correct(self) -> None:
        """**바뀌지 않는 것** — 전부 정답 이력에서도 SE·중단 규칙 입력은 추정 θ(4.0)에서 계산된다.

        표적 θ(0.9)로 SE를 재면 같은 이력의 SE가 7.9에서 2.26으로 내려가 MLE가 없는 이력이 정밀해
        보인다(판정문 §3-2). 리터럴 7.8966은 수정 전 코드의 실측이다(실 PG · 응답 `standard_error`).
        """
        state = await _load([_row(True, 2.9)])
        assert state.standard_error == pytest.approx(7.8966, abs=1e-3)
        assert state.measurement_sufficient is False
        assert state.administered_count == 1
        assert state.diagnosis_confirmable is False
        # SE를 표적 θ에서 재면 이 값이 나온다 — 두 값이 갈라져 있다는 증거(변별력).
        at_target = ability_standard_error(0.9, [_item(-0.1)])
        assert at_target == pytest.approx(2.2553, abs=1e-3)
        assert state.standard_error != pytest.approx(at_target, abs=0.5)

    async def test_calibrated_difficulty_overrides_the_label(self) -> None:
        """표적은 **해소된 b**(보정 b 우선)에서 나온다 — 라벨 2.0(b=-1)이 아니라 보정 b 1.5."""
        state = await _load([_row(True, 2.0, irt_b=1.5)])
        assert state.selection_theta == pytest.approx(2.5, abs=_ABS)

    async def test_capped_selection_equals_the_estimate_and_carries_no_override(self) -> None:
        """표적이 상한에 막혀 추정과 같으면 덮어쓰기 값을 싣지 않는다(경계 사실은 남는다)."""
        state = await _load([_row(True, 3.0, irt_b=3.5)])
        assert state.theta_boundary == "upper"
        assert state.selection_theta == 4.0
        assert state.boundary_selection_theta is None

    async def test_mixed_history_is_untouched(self) -> None:
        """혼합 이력 — 추정 θ(MLE)가 그대로 선택 θ이고 경계가 아니다."""
        state = await _load([_row(True, 3.0), _row(False, 3.5)])
        assert state.theta == pytest.approx(0.25, abs=1e-9)  # 정답 b=0 · 오답 b=0.5의 MLE
        assert state.selection_theta == state.theta
        assert state.theta_boundary is None
        assert state.boundary_selection_theta is None

    async def test_all_wrong_is_reported_but_not_acted_on(self) -> None:
        """하한 — 경계 사실은 보고하되 선택은 추정 θ(-4.0) 그대로다(범위 밖 · 비대칭 동결)."""
        state = await _load([_row(False, 3.0)])
        assert state.theta == -4.0
        assert state.theta_boundary == "lower"
        assert state.selection_theta == -4.0
        assert state.boundary_selection_theta is None

    async def test_no_history_is_cold_start(self) -> None:
        state = await _load([])
        assert (state.theta, state.selection_theta, state.theta_boundary) == (0.0, 0.0, None)
        assert state.standard_error is None

    async def test_ungraded_and_undifficulty_rows_do_not_create_a_boundary(self) -> None:
        """채점 안 된 행(is_correct NULL은 SELECT가 거른다)·난이도 없는 행은 응답에서 빠진다.

        난이도(라벨·보정 b)가 둘 다 없는 정답은 θ·SE에 기여하지 못하므로 표적에도 기여하지 않는다
        (상한과 SE가 같은 문항 집합을 가리키게 한 EOS-126의 원칙).
        """
        state = await _load([_row(True, None, None), _row(True, 3.0)])
        assert state.administered_count == 1
        assert state.selection_theta == pytest.approx(1.0, abs=_ABS)


# ══════════════════════════════════════════════════════════════════════════
# ④ 바뀌지 않는 것 — 문항 보정(EOS-129)의 경계 θ 제외
# ══════════════════════════════════════════════════════════════════════════
class TestItemCalibrationStillExcludesBoundaryLearners:
    def test_all_correct_learners_are_still_excluded_from_the_2pl_input(self) -> None:
        """`fit_jmle`이 학생 θ 단계에서 `estimate_ability`를 부르고, 보정기는 경계 θ 학생을 a 입력에서
        뺀다. 추정기를 바꾸면(B안) 이 제외가 사라진다 — 합성 측정에서 364 → 20, 1600 → 0(판정문
        §3-1). 이 테스트는 추정기가 그대로여서 제외가 유지된다는 것을 리터럴 5건으로 동결한다.
        """
        pid = uuid.UUID(int=1)
        rows = [(uuid.UUID(int=100 + i), pid, True) for i in range(5)]
        plan = item_calibration._compute_calibration(rows)
        assert plan.report.boundary_theta_responses_excluded == 5
        assert plan.report.calibrated_b == 1

    def test_fit_jmle_still_gives_all_correct_learners_the_boundary_value(self) -> None:
        abilities, _difficulties = irt_module.fit_jmle(
            [(0, 0, True), (1, 0, True), (2, 0, False), (2, 1, True), (3, 1, False)], 4, 2
        )
        assert abilities[0] == 4.0 and abilities[1] == 4.0


# ══════════════════════════════════════════════════════════════════════════
# ⑤ 정책 소비 지점 — 선택 θ가 **모든 지점**에 도달한다 (기본 CAT)
# ══════════════════════════════════════════════════════════════════════════
_ANCHOR = uuid.uuid4()
_PREREQ = uuid.uuid4()
_A, _B, _C = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _learner(mastery: dict[str, float] | None = None) -> LearnerState:
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


class _Spy:
    """정책이 부르는 조회·연산의 θ 인자를 지점별로 기록하는 대역 묶음."""

    def __init__(self) -> None:
        self.pool_theta: list[float] = []
        self.route_theta: list[float] = []
        self.target_theta: list[float] = []
        self.band_theta: list[float] = []
        self.select_theta: list[float] = []


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    history: AttemptHistoryState,
    pool: list[tuple[uuid.UUID, float, float | None]],
    anchor_mastery: float = 0.5,
    target_rows: list[tuple[uuid.UUID, float, float | None, uuid.UUID]] | None = None,
    prereqs: list[PrerequisiteRow] | None = None,
) -> _Spy:
    spy = _Spy()

    async def _history(_s: object, _u: uuid.UUID) -> AttemptHistoryState:
        return history

    async def _pool(_s: object, theta: float, **_kw: Any) -> list[Any]:
        spy.pool_theta.append(theta)
        return pool

    async def _route(_s: object, _state: object, *, theta: float, **_kw: Any) -> None:
        spy.route_theta.append(theta)
        return None

    async def _targets(_s: object, theta: float, **_kw: Any) -> list[Any]:
        spy.target_theta.append(theta)
        return target_rows or []

    async def _reason(_s: object, *, learner_id: uuid.UUID, problem_id: Any) -> Any:
        if problem_id is None:
            return no_candidate_reason()
        return build_reason(concept_id=_ANCHOR, mastery=anchor_mastery, confidence=0.5)

    async def _prereqs(_s: object, _cid: uuid.UUID, *, max_depth: int = 1) -> list[Any]:
        return prereqs or []

    async def _successors(_s: object, _cid: uuid.UUID, *, max_nodes: int) -> list[Any]:
        return []

    real_band = policy_module.learning_band_weight
    real_select = policy_module.select_weighted_item

    def _band(theta: float, item: IrtItem, **kw: Any) -> float:
        spy.band_theta.append(theta)
        return real_band(theta, item, **kw)

    def _select(theta: float, items: list[IrtItem], **kw: Any) -> int | None:
        spy.select_theta.append(theta)
        return real_select(theta, items, **kw)

    monkeypatch.setattr(policy_module, "load_attempt_history_state", _history)
    monkeypatch.setattr(policy_module, "load_candidate_rows", _pool)
    monkeypatch.setattr(policy_module, "route_by_learning_state", _route)
    monkeypatch.setattr(policy_module, "load_target_candidate_rows", _targets)
    monkeypatch.setattr(policy_module, "collect_recommendation_reason", _reason)
    monkeypatch.setattr(policy_module, "fetch_prerequisites", _prereqs)
    monkeypatch.setattr(policy_module, "load_direct_successors", _successors)
    monkeypatch.setattr(policy_module, "learning_band_weight", _band)
    monkeypatch.setattr(policy_module, "select_weighted_item", _select)
    return spy


#: 후보 3종 — b = 0.9(라벨 3.9) · 1.8(라벨 4.8) · -1.0(라벨 2.0). 표적 0.9에서는 A가, 추정 4.0에서는 B가
#: 정보량 최대다(A: P=0.5 → 0.25 / B: P(4.0)=0.90 → 0.0885 > A: P(4.0)=0.957 → 0.0405).
_POOL: list[tuple[uuid.UUID, float, float | None]] = [
    (_A, 3.9, None),
    (_B, 4.8, None),
    (_C, 2.0, None),
]
_BOUNDARY = dict(theta=4.0, theta_boundary="upper", boundary_selection_theta=0.9)


async def _run(
    context: LearningContext | None = None, mastery: dict[str, float] | None = None
) -> Any:
    policy = CatRecommendationPolicy(object())  # type: ignore[arg-type]
    return await policy(_learner(mastery), context or LearningContext())


class TestCatPolicyConsumesSelectionTheta:
    async def test_first_pass_is_chosen_at_the_selection_theta_not_the_estimate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """추정 4.0이면 B(4.8)가 나갔을 배치 — 표적 0.9라 A(3.9)가 나간다(수정 전 재현의 단위판)."""
        spy = _install(monkeypatch, history=_state(**_BOUNDARY), pool=_POOL)
        outcome = await _run()
        assert outcome.problem_id == _A
        assert outcome.difficulty == 3.9
        assert spy.pool_theta == [pytest.approx(0.9, abs=_ABS)]  # 후보 풀 조회(정렬 표적)
        assert spy.select_theta == [pytest.approx(0.9, abs=_ABS)]  # 정보량 최대 선택

    async def test_candidate_scores_are_computed_at_the_selection_theta(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """REC-11 후보 점수는 선택에 쓴 θ의 정보량이다 — A는 P=0.5라 정확히 0.25."""
        _install(monkeypatch, history=_state(**_BOUNDARY), pool=_POOL)
        outcome = await _run()
        scores = dict(outcome.candidate_scores)
        assert scores[_A] == pytest.approx(0.25, abs=1e-9)
        # B(b=1.8)는 표적 0.9에서 P=0.289 → 0.2055. 추정 4.0에서 계산했다면 0.0885였을 값이다.
        assert scores[_B] == pytest.approx(0.2055, abs=1e-3)

    async def test_learning_band_weights_use_the_selection_theta(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = _install(monkeypatch, history=_state(**_BOUNDARY), pool=_POOL)
        await _run(LearningContext(purpose="learning"))
        assert len(spy.band_theta) == 3
        assert spy.band_theta == [pytest.approx(0.9, abs=_ABS)] * 3

    async def test_state_machine_seam_receives_the_selection_theta(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = _install(monkeypatch, history=_state(**_BOUNDARY), pool=_POOL)
        await _run()
        assert spy.route_theta == [pytest.approx(0.9, abs=_ABS)]

    async def test_aligned_reselection_uses_the_selection_theta(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """선수 복귀 재선택 — 목표 개념 후보 조회와 재선택의 밴드 가중 모두 표적 θ다."""
        target_pid = uuid.uuid4()
        spy = _install(
            monkeypatch,
            history=_state(**_BOUNDARY),
            pool=_POOL,
            anchor_mastery=0.1,  # 선수 구간 → 측정된 약한 선수가 있으면 그쪽으로 재선택
            prereqs=[
                PrerequisiteRow(
                    concept_id=_PREREQ,
                    concept_code="UC-P",
                    name_ko=None,
                    edge_strength=None,
                    depth=1,
                )
            ],
            target_rows=[(target_pid, 3.0, 0.0, _PREREQ)],
        )
        outcome = await _run(LearningContext(purpose="learning"), {"UC-P": 0.2})
        assert outcome.problem_id == target_pid  # 전제: 재선택이 실제로 돌았다
        assert spy.target_theta == [pytest.approx(0.9, abs=_ABS)]
        # 밴드 가중은 1차 선택(3건) + 재선택(1건) 전부 표적 θ다.
        assert len(spy.band_theta) == 4
        assert spy.band_theta == [pytest.approx(0.9, abs=_ABS)] * 4
        # 선택기도 두 번 모두 표적 θ.
        assert spy.select_theta == [pytest.approx(0.9, abs=_ABS)] * 2

    async def test_outcome_reports_estimate_precision_and_boundary_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """관측 필드 — `theta`·SE·중단 규칙은 추정 θ 그대로, 표적과 경계 사실은 가산 필드로."""
        _install(monkeypatch, history=_state(**_BOUNDARY), pool=_POOL)
        outcome: NextProblemOutcome = await _run()
        assert outcome.theta == 4.0
        assert outcome.selection_theta == pytest.approx(0.9, abs=_ABS)
        assert outcome.theta_boundary == "upper"
        assert outcome.standard_error == 7.9
        assert outcome.measurement_sufficient is False

    async def test_without_a_boundary_everything_uses_the_estimate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """경계가 아니면 전 지점이 추정 θ — 규칙이 발동하지 않은 요청은 종전과 같다."""
        spy = _install(monkeypatch, history=_state(theta=0.7), pool=_POOL)
        outcome = await _run(LearningContext(purpose="learning"))
        assert spy.pool_theta == [0.7] and spy.route_theta == [0.7] and spy.select_theta == [0.7]
        assert spy.band_theta == [0.7] * 3
        assert outcome.theta == 0.7
        assert outcome.selection_theta == 0.7
        assert outcome.theta_boundary is None

    async def test_lower_boundary_is_reported_but_selection_stays_on_the_estimate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """하한 비대칭 동결 — 전부 오답이면 경계 사실만 싣고 표적은 -4.0 그대로(범위 밖)."""
        spy = _install(
            monkeypatch,
            history=_state(theta=-4.0, theta_boundary="lower"),
            pool=_POOL,
        )
        outcome = await _run()
        assert spy.pool_theta == [-4.0] and spy.select_theta == [-4.0]
        assert outcome.theta == -4.0
        assert outcome.selection_theta == -4.0
        assert outcome.theta_boundary == "lower"
        assert outcome.problem_id == _C  # 가장 쉬운 문항 — EOS-24·26 기준선의 전제

    async def test_no_candidate_outcome_still_carries_the_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, history=_state(**_BOUNDARY), pool=[])
        outcome = await _run()
        assert outcome.problem_id is None
        assert outcome.theta == 4.0
        assert outcome.selection_theta == pytest.approx(0.9, abs=_ABS)
        assert outcome.theta_boundary == "upper"


# ══════════════════════════════════════════════════════════════════════════
# ⑥ 처치 기록 — 선택 θ가 다를 때만 남긴다
# ══════════════════════════════════════════════════════════════════════════
class _FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)


class TestTreatmentRecordsSelectionTheta:
    async def _meta(self, **over: Any) -> dict[str, Any]:
        row = await record_recommendation_treatment(
            cast(AsyncSession, _FakeSession()),
            problem_id=uuid.uuid4(),
            theta=4.0,
            pool_size=3,
            applied_weights=False,
            **over,
        )
        assert row.meta is not None
        return cast(dict[str, Any], row.meta)

    async def test_key_is_written_when_selection_differs_from_the_estimate(self) -> None:
        meta = await self._meta(selection_theta=0.9)
        assert meta[META_KEY_THETA] == 4.0  # 기록 theta = 응답 theta(추정 θ) — 갈라지지 않는다
        assert meta[META_KEY_SELECTION_THETA] == 0.9
        assert meta["selection_theta"] == 0.9  # 소비처가 읽는 리터럴 키 이름 동결
        assert meta.get(META_KEY_SELECTION_THETA, meta[META_KEY_THETA]) == 0.9  # 소급 평가 식

    async def test_key_is_absent_when_selection_equals_the_estimate(self) -> None:
        meta = await self._meta(selection_theta=4.0)
        assert META_KEY_SELECTION_THETA not in meta
        assert meta.get(META_KEY_SELECTION_THETA, meta[META_KEY_THETA]) == 4.0

    async def test_key_is_absent_when_the_caller_does_not_pass_it(self) -> None:
        """수정 전 호출부·경계 아닌 요청 — 키가 없다("없음"과 "null로 기록됨"을 구분한다)."""
        meta = await self._meta()
        assert META_KEY_SELECTION_THETA not in meta

    async def test_zero_selection_theta_is_recorded_not_dropped(self) -> None:
        """0.0은 유효한 선택 θ다 — truthiness로 걸러내면 콜드스타트 바닥 기록이 사라진다."""
        meta = await self._meta(selection_theta=0.0)
        assert meta[META_KEY_SELECTION_THETA] == 0.0
