"""S31 특성화 — 슬롯 T3 옛 자산: BKT 숙련도 갱신(F-06 · 다섯 걸음 ②).

옛 `whymath_backend.l2.bkt`의 `BktParameters` + `update_mastery(prior, correct, params)`를
**옛 자리에서 그대로** 불러, 입력 10쌍에 대한 **지금 출력**을 고정한다.
출력이 맞는지는 묻지 않는다 — 바뀌지 않는지만 본다.

- 대상: `BktParameters`(파라미터 묶음 · 비퇴화 검증) · `update_mastery`(관측 1회 → 새 숙련도).
  `update_mastery`가 같은 파일 안에서 직접 쓰는 `posterior_mastery`·`apply_learning`은 따라온다.
  망각(`apply_forgetting`·`BktModel.apply_forgetting`)은 가져오지 않는다(지시서 S31 · 계획서 §6).
  경계는 `golden/HARVEST.md` 「슬롯 T3 경계 (S31)」 절에 먼저 적었다.
- 입력 10쌍 = 옛 기본값 4 · 골든 제안값(S31 · 0.2·0.3·0.2·0.1) 4 · 분모 0 분기 2.
  출력 값은 이 세션이 옛 함수를 불러 얻은 값을 손으로 옮긴 것이다(테스트 안에서 계산하지 않는다).
- 옛 모듈은 이 테스트에서만 import한다. 골든 코드(`src/backend/golden/`)는 import하지 않는다
  (import-linter 계약 `golden-no-legacy`의 대상은 `golden` 패키지뿐이다 · 이 모듈은 LEGACY_MANIFEST에 있다).
- 함수는 LLM·DB·파일·시간을 쓰지 않는다(순수 함수 · 결정적).
"""

from __future__ import annotations

import pytest

from whymath_backend.l2.bkt import BktParameters, update_mastery

# 파라미터 묶음 4종 — 필드 순서: p_init(초기 숙련도) · p_transit(학습률) · p_slip(실수율) · p_guess(추측률)
_OLD_DEFAULT = BktParameters()  # 옛 기본값 0.3 · 0.1 · 0.1 · 0.2
_GOLDEN_PROPOSED = BktParameters(p_init=0.2, p_transit=0.3, p_slip=0.1, p_guess=0.2)  # S31 제안값
_NO_GUESS = BktParameters(p_init=0.3, p_transit=0.1, p_slip=0.1, p_guess=0.0)  # 분모 0 분기(정답)
_NO_SLIP_NO_LEARN = BktParameters(
    p_init=0.3, p_transit=0.0, p_slip=0.0, p_guess=0.2
)  # 분모 0(오답)

# (설명, prior, correct, params, 지금 출력) — 출력은 옛 함수의 현재 값 그대로
_CASES: list[tuple[str, float, bool, BktParameters, float]] = [
    ("old-default-correct", 0.3, True, _OLD_DEFAULT, 0.6926829268292684),
    ("old-default-wrong", 0.3, False, _OLD_DEFAULT, 0.14576271186440679),
    ("old-default-prior0-correct", 0.0, True, _OLD_DEFAULT, 0.1),
    ("old-default-prior1-wrong", 1.0, False, _OLD_DEFAULT, 1.0),
    ("golden-correct", 0.2, True, _GOLDEN_PROPOSED, 0.6705882352941176),
    ("golden-wrong", 0.2, False, _GOLDEN_PROPOSED, 0.32121212121212117),
    ("golden-high-correct", 0.95, True, _GOLDEN_PROPOSED, 0.9919075144508671),
    ("golden-half-wrong", 0.5, False, _GOLDEN_PROPOSED, 0.37777777777777777),
    ("zero-denominator-correct", 0.0, True, _NO_GUESS, 0.1),
    ("zero-denominator-wrong", 1.0, False, _NO_SLIP_NO_LEARN, 1.0),
]
_IDS = [c[0] for c in _CASES]


def test_ten_cases_cover_both_answers_and_four_parameter_sets() -> None:
    """입력 10쌍이 정답·오답을 다 담고, 파라미터 묶음 4종을 모두 쓴다(픽스처가 비지 않았는지)."""
    assert len(_CASES) == 10
    assert {c[2] for c in _CASES} == {True, False}
    assert len({id(c[3]) for c in _CASES}) == 4


@pytest.mark.parametrize(("name", "prior", "correct", "params", "expected"), _CASES, ids=_IDS)
def test_update_mastery_current_output(
    name: str, prior: float, correct: bool, params: BktParameters, expected: float
) -> None:
    """옛 `update_mastery`가 지금 내는 값 그대로다(부동소수 표현 오차 1e-12 안)."""
    assert update_mastery(prior, correct, params) == pytest.approx(expected, abs=1e-12)


def test_update_mastery_is_deterministic_over_100_runs() -> None:
    """같은 입력 100회 → 같은 출력(결정성 · "버림: 비결정적" 아님)."""
    for _name, prior, correct, params, _expected in _CASES:
        outputs = {update_mastery(prior, correct, params) for _ in range(100)}
        assert len(outputs) == 1


def test_parameter_names_and_old_defaults() -> None:
    """파라미터 이름 4개와 옛 기본값(망각 p_forget은 가져오지 않지만 필드로 남아 있다 — 기본 0)."""
    fields = set(BktParameters.model_fields)
    assert {"p_init", "p_transit", "p_slip", "p_guess"} <= fields
    assert (
        _OLD_DEFAULT.p_init,
        _OLD_DEFAULT.p_transit,
        _OLD_DEFAULT.p_slip,
        _OLD_DEFAULT.p_guess,
        _OLD_DEFAULT.p_forget,
    ) == (0.3, 0.1, 0.1, 0.2, 0.0)


def test_non_degenerate_check_rejects_slip_plus_guess_of_one() -> None:
    """비퇴화 검증: p_slip + p_guess ≥ 1이면 만들 수 없다(정답이 숙련도를 낮추는 모델이 된다)."""
    with pytest.raises(ValueError, match="비퇴화"):
        BktParameters(p_slip=0.5, p_guess=0.5)
