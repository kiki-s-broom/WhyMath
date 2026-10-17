"""EOS-147 — 수능 정책도 **선택 θ**로 후보를 고른다 (hermetic · DB 0).

판정(`docs/reviews/eos147_all_correct_theta_pin_judgment_2026-09-29.md` §2 표 2행)은 기본 CAT과 수능
모드가 같은 상태 객체(`AttemptHistoryState`)를 읽으므로 표적 θ의 정의를 갈라 두지 않는다고 했다. 수능
정책이 추정 θ(전부 정답 → 상한 4.0)를 그대로 쓰면 같은 결함이 그 모드에 남는다 — 수능 적격 문항 중
가장 어려운 것으로 뛴다.

이 파일은 수능 정책의 **θ 소비 지점 전부**를 지점별로 잡는다: 후보 풀 정렬(SQL) · 학습 밴드 가중 ·
`recommend_suneung_index`(L6 진실 게이트 × 정보량) · 후보 점수(REC-11). 그리고 `theta`·SE·중단 규칙은
추정 θ 그대로임을 동결한다. 기본 CAT의 짝은 `tests/backend/l2/test_eos147_selection_theta.py`다.

기대값은 리터럴이다(상수를 import해 기대값을 만들면 상수 뮤테이션을 따라 움직인다 — MISC-30).
아래의 표적 0.9는 `_history()`가 **손으로 주입한 상태값**이지 규칙(맞힌 최고 난이도 + 0.5)이 낸 값이
아니다 — 이 파일은 정책이 그 값을 어느 지점에 쓰는지만 재므로 단계 상수와 무관하다. 규칙 산출(단계·
바닥·상한)은 `tests/backend/l2/test_eos147_selection_theta.py`가 지킨다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from whymath_backend.api import _next_problem_policy as suneung_module
from whymath_backend.api._next_problem_policy import SuneungRecommendationPolicy
from whymath_backend.l2.irt import IrtItem
from whymath_backend.l2.learner_state import LearnerState
from whymath_backend.l2.next_problem_selection import AttemptHistoryState
from whymath_backend.l2.recommendation_contract import (
    LearningContext,
    build_reason,
    no_candidate_reason,
)
from whymath_backend.l2.recommendation_policy import NextProblemOutcome
from whymath_backend.schema.enums import (
    Curriculum,
    Persona,
    ReviewStatus,
    SignaturePattern,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem as SchemaProblem

_ABS = 1e-9
_ANCHOR = uuid.uuid4()


def _state() -> LearnerState:
    return LearnerState(
        student_id=str(uuid.uuid4()),
        timestamp=datetime.now(UTC),
        mastery={},
        general_ability=None,
        domain_abilities={},
        active_misconceptions=[],
        recent_struggles=[],
        recent_successes=[],
        grade=None,
        goals={},
    )


def _problem(difficulty: float) -> SchemaProblem:
    """수능 적격(시그니처 보유·검수 통과·자체생성) 문항 — 난이도만 다르다(`b = 난이도 − 3`)."""
    return SchemaProblem(
        source_type=SourceType.자체생성,
        review_status=ReviewStatus.approved,
        curriculum_version=Curriculum.REVISION_2022,
        valid_from_year=2022,
        subject=Subject.공통,
        unit_codes=["U-EOS147"],
        # EOS-31 — 수능 출제 범위 안 성취기준 코드(2022 개정 대수). 게이트 ②-c가 범위를
        # 선결 조건으로 보므로 코드가 없으면 후보가 전부 UNKNOWN으로 거절된다. 정책이
        # 조인으로 주입하는 비영속 필드다.
        achievement_standard_codes=["[12대수01-01]"],
        difficulty_overall=difficulty,
        signature_patterns=[SignaturePattern.COMPOUND_CHOICES],
    )


class _OrmRow:
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
    """1차 후보 풀 한 번만 돌려준다 — 수능 정책은 콘텐츠를 다시 고르지 않는다(EOS-25)."""

    def __init__(self, pool: list[SchemaProblem]) -> None:
        self._pool = pool
        self.calls = 0

    async def execute(self, _stmt: Any) -> _Result:
        self.calls += 1
        assert self.calls == 1, "1차 후보 풀 외의 직접 조회 — 수능 모드는 재선택하지 않는다"
        return _Result([_OrmRow(p) for p in self._pool])


async def _no_injection(_s: object, _problem_ids: list[uuid.UUID]) -> dict[uuid.UUID, set[str]]:
    """성취기준 코드 조인 대역 — 빌더가 이미 코드를 갖고 있어 주입은 빈 결과다(EOS-31).

    조인은 두 번째 직접 조회라 `_PoolSession`의 "풀 한 번" 규약을 깬다. 주입 자체는 실 PG 통합
    테스트가 본다 — 이 파일은 θ 소비 지점만 잰다.
    """
    return {}


class _Spy:
    def __init__(self) -> None:
        self.order_theta: list[float] = []
        self.index_theta: list[float] = []
        self.band_theta: list[float] = []


def _install(
    monkeypatch: pytest.MonkeyPatch, history: AttemptHistoryState, *, anchor_mastery: float = 0.5
) -> _Spy:
    spy = _Spy()

    async def _history(_s: object, _u: uuid.UUID) -> AttemptHistoryState:
        return history

    async def _reason(_s: object, *, learner_id: uuid.UUID, problem_id: Any) -> Any:
        if problem_id is None:
            return no_candidate_reason()
        return build_reason(concept_id=_ANCHOR, mastery=anchor_mastery, confidence=0.5)

    real_order = suneung_module.candidate_pool_order_by
    real_index = suneung_module.recommend_suneung_index
    real_band = suneung_module.learning_band_weight

    def _order(theta: float) -> Any:
        spy.order_theta.append(theta)
        return real_order(theta)

    def _index(theta: float, *args: Any, **kwargs: Any) -> Any:
        spy.index_theta.append(theta)
        return real_index(theta, *args, **kwargs)

    def _band(theta: float, item: IrtItem, **kw: Any) -> float:
        spy.band_theta.append(theta)
        return real_band(theta, item, **kw)

    monkeypatch.setattr(suneung_module, "load_attempt_history_state", _history)
    # EOS-31 — 코드 조인도 이름 교체로 대역한다(풀 조회 "한 번" 규약을 지키려고).
    monkeypatch.setattr(suneung_module, "fetch_achievement_codes", _no_injection)
    monkeypatch.setattr(suneung_module, "collect_recommendation_reason", _reason)
    monkeypatch.setattr(suneung_module, "candidate_pool_order_by", _order)
    monkeypatch.setattr(suneung_module, "recommend_suneung_index", _index)
    monkeypatch.setattr(suneung_module, "learning_band_weight", _band)
    return spy


def _history(**over: Any) -> AttemptHistoryState:
    base: dict[str, Any] = {
        "attempted_ids": set(),
        "theta": 4.0,
        "standard_error": 7.9,
        "measurement_sufficient": False,
        "administered_count": 1,
        "theta_boundary": "upper",
        "selection_theta_override": 0.9,
    }
    base.update(over)
    return AttemptHistoryState(**base)


async def _run(pool: list[SchemaProblem], context: LearningContext) -> NextProblemOutcome:
    policy = SuneungRecommendationPolicy(
        _PoolSession(pool),  # type: ignore[arg-type]
        persona=Persona.A_일반고고3,
    )
    return await policy(_state(), context)


class TestSuneungPolicyConsumesSelectionTheta:
    async def test_pool_order_selection_and_scores_use_the_selection_theta(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """추정 4.0이면 난이도 4.8이 나갔을 배치 — 표적 0.9라 3.9가 나간다."""
        easy, hard = _problem(3.9), _problem(4.8)  # b = 0.9 · 1.8
        spy = _install(monkeypatch, _history())
        outcome = await _run([easy, hard], LearningContext(mode="suneung"))
        assert outcome.problem_id == easy.problem_id
        assert outcome.difficulty == 3.9
        assert spy.order_theta == [pytest.approx(0.9, abs=_ABS)]  # 후보 풀 SQL 정렬 표적
        assert spy.index_theta == [pytest.approx(0.9, abs=_ABS)]  # 적격 게이트 × 정보량 선택
        # 후보 점수 비 = 정보량 비 × 수능 가중 비(난이도가 우선순위에 들어가 가중이 다르다 — 0.8676):
        # 표적 0.9에서 (0.25 / 0.2055) × 0.8676 = 1.0555. 추정 4.0에서 계산했다면
        # (0.0405 / 0.0885) × 0.8676 = 0.397이었을 값이다 — 표적이 점수 계산에도 닿는다는 증거.
        scores = dict(outcome.candidate_scores)
        assert scores[easy.problem_id] / scores[hard.problem_id] == pytest.approx(1.0555, abs=1e-3)

    async def test_learning_band_weights_use_the_selection_theta(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = _install(monkeypatch, _history())
        await _run(
            [_problem(3.9), _problem(4.8)], LearningContext(mode="suneung", purpose="learning")
        )
        assert spy.band_theta == [pytest.approx(0.9, abs=_ABS)] * 2

    async def test_outcome_reports_estimate_precision_and_boundary_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _history())
        outcome = await _run([_problem(3.9), _problem(4.8)], LearningContext(mode="suneung"))
        assert outcome.theta == 4.0
        assert outcome.selection_theta == pytest.approx(0.9, abs=_ABS)
        assert outcome.theta_boundary == "upper"
        assert outcome.standard_error == 7.9
        assert outcome.measurement_sufficient is False

    async def test_without_a_boundary_everything_uses_the_estimate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """경계가 아니면 전 지점이 추정 θ — 규칙이 발동하지 않은 요청은 종전과 같다."""
        spy = _install(
            monkeypatch,
            _history(theta=0.7, theta_boundary=None, selection_theta_override=None),
        )
        outcome = await _run(
            [_problem(3.9), _problem(4.8)], LearningContext(mode="suneung", purpose="learning")
        )
        assert spy.order_theta == [0.7] and spy.index_theta == [0.7]
        assert spy.band_theta == [0.7] * 2
        assert (outcome.theta, outcome.selection_theta, outcome.theta_boundary) == (0.7, 0.7, None)

    async def test_lower_boundary_is_reported_but_selection_stays_on_the_estimate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """하한 비대칭 동결 — 전부 오답이면 경계 사실만 싣고 표적은 -4.0 그대로(범위 밖)."""
        spy = _install(
            monkeypatch,
            _history(theta=-4.0, theta_boundary="lower", selection_theta_override=None),
        )
        outcome = await _run([_problem(3.9), _problem(4.8)], LearningContext(mode="suneung"))
        assert spy.order_theta == [-4.0] and spy.index_theta == [-4.0]
        assert (outcome.theta, outcome.selection_theta, outcome.theta_boundary) == (
            -4.0,
            -4.0,
            "lower",
        )

    async def test_no_candidate_outcome_still_carries_the_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _history())
        outcome = await _run([], LearningContext(mode="suneung"))
        assert outcome.problem_id is None
        assert outcome.theta == 4.0
        assert outcome.selection_theta == pytest.approx(0.9, abs=_ABS)
        assert outcome.theta_boundary == "upper"

    async def test_help_fold_counts_flow_into_the_outcome(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """EOS-39 — 도움 접기·미상 계측이 수능 정책 결과까지 흐른다(처치 기록의 재료)."""
        _install(monkeypatch, _history(selection_help_count=2, selection_hint_unknown_count=3))
        outcome = await _run([_problem(3.9), _problem(4.8)], LearningContext(mode="suneung"))
        assert outcome.selection_help_count == 2
        assert outcome.selection_hint_unknown_count == 3

    async def test_help_fold_counts_default_to_zero_and_survive_no_candidate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _history())
        outcome = await _run([_problem(3.9)], LearningContext(mode="suneung"))
        assert (outcome.selection_help_count, outcome.selection_hint_unknown_count) == (0, 0)
        _install(monkeypatch, _history(selection_help_count=1))
        empty = await _run([], LearningContext(mode="suneung"))
        assert empty.problem_id is None and empty.selection_help_count == 1
