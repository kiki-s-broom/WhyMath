"""S31·S32 특성화 — 슬롯 T3 옛 자산: BKT 숙련도 갱신(F-06 · 다섯 걸음 ②③).

옛 `whymath_backend.l2.bkt`의 `BktParameters` + `update_mastery(prior, correct, params)`를
**옛 자리에서 그대로** 불러, 입력 10쌍에 대한 **지금 출력**을 고정한다(S31).
출력이 맞는지는 묻지 않는다 — 바뀌지 않는지만 본다.
S32가 골든 사본 `golden.mastery.bkt`를 만들었으므로, 같은 10쌍을 **원본·사본 두 대상**에
parametrize한다(S22 선례). 사본이 원본과 갈라지면 여기서 걸린다.

- 대상: `BktParameters`(파라미터 묶음 · 비퇴화 검증) · `update_mastery`(관측 1회 → 새 숙련도).
  `update_mastery`가 같은 파일 안에서 직접 쓰는 `posterior_mastery`·`apply_learning`은 따라온다.
  망각(`apply_forgetting`·`BktModel.apply_forgetting`)은 가져오지 않는다(지시서 S31 · 계획서 §6).
  경계는 `golden/HARVEST.md` 「슬롯 T3 경계 (S31)」 절에 먼저 적었다.
- 입력 10쌍 = 옛 기본값 4 · 골든 제안값(S31 · 0.2·0.3·0.2·0.1) 4 · 분모 0 분기 2.
  출력 값은 S31 세션이 옛 함수를 불러 얻은 값을 손으로 옮긴 것이다(테스트 안에서 계산하지 않는다).
- 옛 모듈은 이 테스트에서만 import한다. 골든 코드(`src/backend/golden/`)는 옛 모듈을 import하지
  않는다(import-linter 계약 `golden-no-legacy`의 대상은 `golden` 패키지뿐 · 이 모듈은 LEGACY_MANIFEST에 있다).
- 함수는 LLM·DB·파일·시간을 쓰지 않는다(순수 함수 · 결정적).
"""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType
from typing import Any

import pytest
from golden.mastery import bkt as golden_bkt

from whymath_backend.l2 import bkt as old_bkt

# 검사 대상 두 곳 — 원본(옛 자리)과 사본(골든)
_TARGETS: dict[str, ModuleType] = {"old": old_bkt, "golden-copy": golden_bkt}

# 파라미터 묶음 4종(이름 → 키워드 인자) — p_init(초기 숙련도) · p_transit(학습률) · p_slip(실수율) · p_guess(추측률)
_PARAM_SETS: dict[str, dict[str, float]] = {
    "old-default": {},  # 옛 기본값 0.3 · 0.1 · 0.1 · 0.2
    "golden": {"p_init": 0.2, "p_transit": 0.3, "p_slip": 0.1, "p_guess": 0.2},  # S31 제안값
    "no-guess": {"p_init": 0.3, "p_transit": 0.1, "p_slip": 0.1, "p_guess": 0.0},  # 분모 0(정답)
    "no-slip-no-learn": {
        "p_init": 0.3,
        "p_transit": 0.0,
        "p_slip": 0.0,
        "p_guess": 0.2,
    },  # 분모 0(오답)
}

# (설명, prior, correct, 파라미터 묶음 이름, 지금 출력) — 출력은 옛 함수의 현재 값 그대로
_CASES: list[tuple[str, float, bool, str, float]] = [
    ("old-default-correct", 0.3, True, "old-default", 0.6926829268292684),
    ("old-default-wrong", 0.3, False, "old-default", 0.14576271186440679),
    ("old-default-prior0-correct", 0.0, True, "old-default", 0.1),
    ("old-default-prior1-wrong", 1.0, False, "old-default", 1.0),
    ("golden-correct", 0.2, True, "golden", 0.6705882352941176),
    ("golden-wrong", 0.2, False, "golden", 0.32121212121212117),
    ("golden-high-correct", 0.95, True, "golden", 0.9919075144508671),
    ("golden-half-wrong", 0.5, False, "golden", 0.37777777777777777),
    ("zero-denominator-correct", 0.0, True, "no-guess", 0.1),
    ("zero-denominator-wrong", 1.0, False, "no-slip-no-learn", 1.0),
]
_IDS = [c[0] for c in _CASES]


def _params(target: ModuleType, set_name: str) -> Any:
    """대상 모듈의 `BktParameters`로 이름 붙은 파라미터 묶음을 만든다."""
    return target.BktParameters(**_PARAM_SETS[set_name])


def _update(target: ModuleType) -> Callable[[float, bool, Any], float]:
    """대상 모듈의 `update_mastery`."""
    func: Callable[[float, bool, Any], float] = target.update_mastery
    return func


def test_ten_cases_cover_both_answers_and_four_parameter_sets() -> None:
    """입력 10쌍이 정답·오답을 다 담고, 파라미터 묶음 4종을 모두 쓴다(픽스처가 비지 않았는지)."""
    assert len(_CASES) == 10
    assert {c[2] for c in _CASES} == {True, False}
    assert {c[3] for c in _CASES} == set(_PARAM_SETS)


@pytest.mark.parametrize("target_name", list(_TARGETS))
@pytest.mark.parametrize(("name", "prior", "correct", "set_name", "expected"), _CASES, ids=_IDS)
def test_update_mastery_current_output(
    target_name: str, name: str, prior: float, correct: bool, set_name: str, expected: float
) -> None:
    """옛 `update_mastery`가 지금 내는 값 그대로다 — 사본도 같은 값(부동소수 표현 오차 1e-12 안)."""
    target = _TARGETS[target_name]
    result = _update(target)(prior, correct, _params(target, set_name))
    assert result == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize("target_name", list(_TARGETS))
def test_update_mastery_is_deterministic_over_100_runs(target_name: str) -> None:
    """같은 입력 100회 → 같은 출력(결정성 · "버림: 비결정적" 아님)."""
    target = _TARGETS[target_name]
    for _name, prior, correct, set_name, _expected in _CASES:
        params = _params(target, set_name)
        outputs = {_update(target)(prior, correct, params) for _ in range(100)}
        assert len(outputs) == 1


def test_parameter_names_and_old_defaults() -> None:
    """파라미터 이름 4개와 옛 기본값(망각 p_forget은 가져오지 않지만 원본에는 필드로 남아 있다 — 기본 0)."""
    default = old_bkt.BktParameters()
    fields = set(old_bkt.BktParameters.model_fields)
    assert {"p_init", "p_transit", "p_slip", "p_guess"} <= fields
    assert (
        default.p_init,
        default.p_transit,
        default.p_slip,
        default.p_guess,
        default.p_forget,
    ) == (0.3, 0.1, 0.1, 0.2, 0.0)


def test_copy_keeps_four_parameters_and_drops_forgetting() -> None:
    """사본은 파라미터 4개와 옛 기본값을 그대로 두고, 망각(`p_forget`·`apply_forgetting`)만 뺐다."""
    default = golden_bkt.BktParameters()
    assert set(golden_bkt.BktParameters.model_fields) == {
        "p_init",
        "p_transit",
        "p_slip",
        "p_guess",
    }
    assert (default.p_init, default.p_transit, default.p_slip, default.p_guess) == (
        0.3,
        0.1,
        0.1,
        0.2,
    )
    assert not hasattr(golden_bkt, "apply_forgetting")
    with pytest.raises(ValueError):
        golden_bkt.BktParameters(p_forget=0.1)  # type: ignore[call-arg]


def test_golden_update_uses_s31_proposed_parameters() -> None:
    """사본의 `update(prior, correct)`는 S31 제안값(0.2·0.3·0.1·0.2)으로 원본과 같은 값을 낸다."""
    params = golden_bkt.GOLDEN_BKT_PARAMETERS
    assert (params.p_init, params.p_transit, params.p_slip, params.p_guess) == (0.2, 0.3, 0.1, 0.2)
    assert golden_bkt.update(0.2, True) == pytest.approx(0.6705882352941176, abs=1e-12)
    assert golden_bkt.update(0.2, False) == pytest.approx(0.32121212121212117, abs=1e-12)


@pytest.mark.parametrize("target_name", list(_TARGETS))
def test_non_degenerate_check_rejects_slip_plus_guess_of_one(target_name: str) -> None:
    """비퇴화 검증: p_slip + p_guess ≥ 1이면 만들 수 없다(정답이 숙련도를 낮추는 모델이 된다)."""
    with pytest.raises(ValueError, match="비퇴화"):
        _TARGETS[target_name].BktParameters(p_slip=0.5, p_guess=0.5)
