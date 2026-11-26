"""T3 숙련도 엔진 — BKT(Bayesian Knowledge Tracing) 사본(S32 · 다섯 걸음 ③ · 인용 F-06).

옛 `whymath_backend/l2/bkt.py`에서 **네 가지만** 복사했다(경계 = `golden/HARVEST.md`
「슬롯 T3 경계 (S31)」).

- `BktParameters`(파라미터 묶음 · 비퇴화 검증)
- `posterior_mastery`(관측 → 베이지안 사후)
- `apply_learning`(학습 전이)
- `update_mastery`(위 둘을 차례로)

복사한 이유: 원본을 import하면 `whymath_backend/l2/__init__.py`를 거쳐 옛 모듈 141개가
로드된다(S31 실측). 전이 의존 예산 30을 넘으므로 다섯 걸음 ③대로 복사했다.
HARVEST.md에는 "복사: 의존 과다"로 적었다. 원본은 LEGACY_MANIFEST 333행에 있어
골든에서 새로 import할 수 없다.

가져오지 않은 것:
- 망각(`apply_forgetting` · `p_forget` 필드)은 계획서 §6 금지라 버렸다.
  `BktParameters`에서 `p_forget` 필드도 뺐다.
- `BktModel`·`probability_correct`도 버렸다(적응형 문항 선택용 · §6).

남은 네 가지의 계산식·기본값·오류 문구는 원본과 한 글자도 다르지 않게 두었다.
원본과 같은 출력을 내는지는 `tests/golden/characterization/test_t3_bkt.py`가
같은 10쌍으로 원본·사본 두 대상을 함께 검사한다(S22 선례).

LLM·DB·파일·시간을 쓰지 않는 순수 함수다(결정적).
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 원본의 문헌 전형값(개념별 적합 전 기본값) — 사본에서도 그대로 둔다(특성화 테스트가 고정)
_DEFAULT_P_INIT = 0.3
_DEFAULT_P_TRANSIT = 0.1
_DEFAULT_P_SLIP = 0.1
_DEFAULT_P_GUESS = 0.2


class BktParameters(BaseModel):
    """BKT 4-파라미터 — 불변(frozen)·전부 [0,1]. 원본에서 망각률 `p_forget`만 뺐다.

    `p_slip + p_guess < 1`(비퇴화)을 강제한다 — 어기면 정답이 숙달 믿음을 낮추는 모델이
    되어 교수학적으로 무의미하다(`ValueError`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    p_init: float = Field(
        default=_DEFAULT_P_INIT, ge=0.0, le=1.0, description="P(L0) 사전 숙달 확률."
    )
    p_transit: float = Field(
        default=_DEFAULT_P_TRANSIT, ge=0.0, le=1.0, description="P(T) 학습 기회당 전이 확률."
    )
    p_slip: float = Field(
        default=_DEFAULT_P_SLIP, ge=0.0, le=1.0, description="P(S) 숙달했어도 틀릴 확률."
    )
    p_guess: float = Field(
        default=_DEFAULT_P_GUESS, ge=0.0, le=1.0, description="P(G) 미숙달인데 맞힐 확률."
    )

    @model_validator(mode="after")
    def _check_non_degenerate(self) -> Self:
        """비퇴화 검증(원본 그대로) — p_slip + p_guess ≥ 1이면 만들 수 없다."""
        total = self.p_slip + self.p_guess
        if total >= 1.0:
            raise ValueError(
                f"BKT 비퇴화 제약 위반: p_slip({self.p_slip}) + p_guess({self.p_guess}) "
                f"= {total} ≥ 1. 정답이 숙달 믿음을 높이려면 p_slip + p_guess < 1 이어야 합니다."
            )
        return self


# 골든(중2 일차함수) 파라미터 — S31 제안값 그대로(지시서 값 · 보정은 아직 안 했다)
GOLDEN_BKT_PARAMETERS = BktParameters(p_init=0.2, p_transit=0.3, p_slip=0.1, p_guess=0.2)


def posterior_mastery(prior: float, correct: bool, params: BktParameters) -> float:
    """관측(정/오답) 뒤, 학습 전이 전의 베이지안 사후 숙달 확률 P(L|obs) — 원본 그대로.

    `prior`는 0~1이어야 한다(범위 밖이면 ValueError).
    """
    if not 0.0 <= prior <= 1.0:
        raise ValueError(f"prior(사전 숙달 확률)는 0~1이어야 합니다(받음: {prior}).")
    if correct:
        num = prior * (1.0 - params.p_slip)
        denom = num + (1.0 - prior) * params.p_guess
    else:
        num = prior * params.p_slip
        denom = num + (1.0 - prior) * (1.0 - params.p_guess)
    if denom == 0.0:
        # prior=0·guess=0(정답) 또는 prior=1·slip=0(오답) 같은 극단 — 정보가 없으니 prior 그대로
        return prior
    return num / denom


def apply_learning(posterior: float, params: BktParameters) -> float:
    """학습 전이 — 관측 뒤 학습 기회가 미숙달분을 p_transit만큼 숙달로 끌어올린다(원본 그대로)."""
    return posterior + (1.0 - posterior) * params.p_transit


def update_mastery(prior: float, correct: bool, params: BktParameters) -> float:
    """관측 1회 처리 — 사후(`posterior_mastery`) → 학습 전이(`apply_learning`). 원본 그대로."""
    return apply_learning(posterior_mastery(prior, correct, params), params)


def update(prior: float, correct: bool) -> float:
    """골든 파라미터로 관측 1회를 반영한 새 숙련도(지시서 S32 할 일 1의 모양)."""
    return update_mastery(prior, correct, GOLDEN_BKT_PARAMETERS)


__all__ = [
    "GOLDEN_BKT_PARAMETERS",
    "BktParameters",
    "apply_learning",
    "posterior_mastery",
    "update",
    "update_mastery",
]
