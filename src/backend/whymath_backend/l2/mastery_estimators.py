"""L2 — 계획서 300 §6의 **v1 가산 규칙** 추정기(`simple-additive-v1`).

왜 이 파일이 따로 있는가
------------------------
`EOS-13`이 세운 것은 *계약*이었고, 그 계약의 구현은 기존 `BktMasteryEstimator` 하나뿐이었다.
구현이 하나인 교체 계약은 "교체 가능하다"는 주장을 증명하지 못한다 — 가짜 스텁 주입은 *테스트가
할 수 있다*는 것만 보이고, **다른 수학을 쓰는 진짜 두 번째 구현**이 호출부 수정 0으로 도는지는
보이지 않는다. 이 모듈이 그 두 번째 구현이다.

동시에, 계획서 §6이 글로 적어 둔 v1 규칙(정답 +0.10 / 오답 -0.08 / 힌트 x0.7 / 연속 정답 →
confidence↑)을 **코드로 정본화**한다. 문서에만 있는 규칙은 대조할 대상이 없어 드리프트를
검출할 수 없다.

기본값이 아니다 (중요 · 판정 시점 2026-09-18)
---------------------------------------------
등록은 하되 **기본 추정기는 `bkt-v1` 그대로**다. 기본을 바꾸는 것은 리팩터가 아니라 **전
학생의 숙달 궤적을 바꾸는 정책 변경**이고, `EOS-13` acceptance ④가 그 경우 "값 변화를 전수
열거하라"고 요구한다. 측정 없이 BKT(사후 확률 갱신)를 가산 규칙으로 되돌리는 것은 학습 모델의
격하이므로(의사결정 우선순위 4 「학습 효과」), 채택 여부는 실측 비교 뒤의 결정으로 남긴다.
전환 자체는 한 줄이다 — `use_estimator(ADDITIVE_ESTIMATOR_ID)` 또는 레지스트리 기본값 변경이며
**호출부는 한 글자도 바뀌지 않는다**(그것이 계약의 요점이다).

무엇이 실제로 작동하는지 말한다
--------------------------------
산출의 `estimator_id`가 항상 실린다(CLAUDE.md 「작동 신호 없는 알고리즘 부착 금지」). 즉 이
추정기가 돌았는지 아닌지는 추측이 아니라 적재된 값으로 판별된다.

**정직 표기**: 힌트·연속 정답 축은 *선택 신호*(`HintUsageSignal`·`StreakSignal`)로 읽는다.
2026-09-18 현재 두 서빙 호출부는 그 둘을 채우지 않으므로(`l2/mastery_contract.py`
`AttemptOutcomeEvidence` docstring), 이 추정기를 기본으로 올리기 전에 생산자 배선이 선행한다.
`None`(모른다)을 `False`/`0`으로 접지 않는 이유가 여기에 있다 — 접으면 "힌트를 안 썼다"와
"힌트를 썼는지 모른다"가 같은 숫자를 내고, 배선 여부를 사후에 판별할 수 없게 된다.
"""

from __future__ import annotations

from whymath_backend.l2.mastery_contract import register_estimator
from whymath_backend.schema.mastery_contract import (
    AssessmentEvidenceInput,
    LearnerMasteryState,
    MasteryUpdate,
    clamp_unit,
    consecutive_correct_of,
    hint_used_of,
)

__all__ = [
    "ADDITIVE_ESTIMATOR_ID",
    "CONFIDENCE_HALFLIFE",
    "CONFIDENCE_STREAK_CAP",
    "CONFIDENCE_STREAK_STEP",
    "CORRECT_GAIN",
    "HINT_GAIN_FACTOR",
    "INITIAL_MASTERY",
    "WRONG_PENALTY",
    "AdditiveMasteryEstimator",
]

#: 레지스트리 키이자 산출 출처 표기. 값을 바꾸면 적재된 과거 산출의 출처가 미아가 된다.
ADDITIVE_ESTIMATOR_ID = "simple-additive-v1"

# ── 계획서 300 §6 v1 규칙 상수 — **여기가 그 규칙의 정본이다** ────────────────────
#: 정답 1건의 기본 이득.
CORRECT_GAIN = 0.10
#: 오답 1건의 기본 감점. 이득보다 작다(오답 1회로 정답 1회를 지우지 않는다 — 오답은 실패가
#: 아니라 정보라는 교수학 전제. CLAUDE.md "오답=약점 단정 금지"와 같은 축).
WRONG_PENALTY = 0.08
#: 힌트를 쓰고 맞힌 경우 이득에 곱하는 계수. **감점에는 곱하지 않는다** — 힌트를 받고도 틀린
#: 것을 *덜* 벌하는 규칙은 §6에 없고, 만들면 힌트가 감점 회피 수단이 된다.
HINT_GAIN_FACTOR = 0.7

#: 표본 기반 confidence 반감 상수 — `bkt-v1` 커널과 **같은 값**을 쓴다. 두 추정기가 서로 다른
#: 신뢰도 척도를 쓰면 추정기를 바꿨을 때 mastery가 아니라 confidence 때문에 판정이 흔들린다.
CONFIDENCE_HALFLIFE = 5
#: 연속 정답 1회당 confidence 가산.
CONFIDENCE_STREAK_STEP = 0.05
#: 연속 정답 가산의 상한 횟수(= 최대 +0.20). 상한이 없으면 연속 정답만으로 confidence가 1.0에
#: 붙어 "표본이 적어 잘 모른다"는 사실이 사라진다.
CONFIDENCE_STREAK_CAP = 4

#: 첫 관측의 출발점. `bkt.BktParameters.p_init` 기본값과 **같은 값**이며, 그 일치는
#: `tests/backend/l2/test_mastery_estimators.py`가 기계로 동결한다 — 추정기를 바꿨을 때
#: 출발점까지 달라지면 두 추정기의 차이가 *규칙의 차이*인지 *사전값의 차이*인지 구분되지 않는다.
INITIAL_MASTERY = 0.3

_MASTERY_DECIMALS = 2  # Numeric(3,2) 정합 — 적재 정밀도에 맞춰 반올림해야 다음 prior가 같다.


class AdditiveMasteryEstimator:
    """계획서 §6 v1 가산 규칙 — `MasteryEstimator` Protocol 구현(기본 아님).

    규칙(전부 위 모듈 상수가 정본):
      ① 정답 → `prior + CORRECT_GAIN`
      ② 오답 → `prior - WRONG_PENALTY`
      ③ 힌트를 쓰고 **맞힌** 경우 → 이득에 `HINT_GAIN_FACTOR`를 곱한다.
         힌트 여부가 `None`(모른다)이면 곱하지 않는다 — 모르는 것을 "안 썼다"로 읽지 않는다.
      ④ 연속 정답 → confidence에 `CONFIDENCE_STREAK_STEP x min(streak, CAP)`을 더한다.
         **이번 관측이 오답이면 가산하지 않는다**(연속이 거기서 끊긴다).

    `prior`가 `None`(첫 관측)이면 `INITIAL_MASTERY`에서 시작한다. 결과는 0~1로 클램프되며,
    클램프는 *규칙의 일부*이지 사후 구제가 아니다(호출 계약의 `_enforce_bounds`는 그 위의
    두 번째 회계다 — 임의 구현을 신뢰하지 않기 위한 것이고 이 구현은 스스로도 지킨다).

    **망각 감쇠를 적용하지 않는다.** §6 v1 규칙에 그 축이 없기 때문이다. `elapsed_days`는
    산출에 그대로 실어 *관측은 남기되 사용하지 않았음*을 드러낸다 — 계산에 안 썼다는 이유로
    None으로 지우면 두 추정기의 산출을 나란히 놓고 비교할 수 없다.
    """

    @property
    def estimator_id(self) -> str:
        """레지스트리 키이자 산출 출처 표기."""
        return ADDITIVE_ESTIMATOR_ID

    def estimate(
        self,
        learner_state: LearnerMasteryState,
        assessment_evidence: AssessmentEvidenceInput,
    ) -> MasteryUpdate:
        """직전 상태 + 증거 1건 → 다음 측정(순수·DB 무관)."""
        prior = INITIAL_MASTERY if learner_state.mastery is None else learner_state.mastery
        correct = assessment_evidence.correct
        hint_used = hint_used_of(assessment_evidence)
        streak = consecutive_correct_of(assessment_evidence)

        if correct:
            # ③ 힌트 여부가 True일 때만 감액. None(모른다)·False는 전액.
            gain = CORRECT_GAIN * HINT_GAIN_FACTOR if hint_used is True else CORRECT_GAIN
            raw = prior + gain
        else:
            raw = prior - WRONG_PENALTY

        sample_size = (learner_state.sample_size or 0) + 1
        base_confidence = sample_size / (sample_size + CONFIDENCE_HALFLIFE)
        # ④ 연속 정답 가산 — 이번이 정답이고 streak를 아는 경우만.
        bonus = (
            CONFIDENCE_STREAK_STEP * min(streak, CONFIDENCE_STREAK_CAP)
            if correct and streak is not None
            else 0.0
        )
        return MasteryUpdate(
            axis=learner_state.axis,
            target_id=learner_state.target_id,
            mastery=round(clamp_unit(raw), _MASTERY_DECIMALS),
            confidence=round(clamp_unit(base_confidence + bonus), _MASTERY_DECIMALS),
            sample_size=sample_size,
            prior_mastery=learner_state.mastery,
            elapsed_days=learner_state.elapsed_days_until(assessment_evidence.observed_at),
            estimator_id=self.estimator_id,
            attempt_id=assessment_evidence.attempt_id,
        )


# import 시점 등록 — `l2/__init__.py`가 이 모듈을 import하므로 `whymath_backend.l2`를 쓰는 모든
# 경로에서 레지스트리에 실재한다. `replace=False`(기본)라 같은 id의 중복 등록은 조용히 덮어쓰지
# 않고 즉시 실패한다.
register_estimator(ADDITIVE_ESTIMATOR_ID, AdditiveMasteryEstimator)
