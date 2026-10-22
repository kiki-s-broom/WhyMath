"""값 노출 훑기 `scan_value_exposure` — 힌트 게이트(S4-11 B·④)·P3-10 판정기의 공용 판정 (P3-77).

이 함수 하나가 "본문에 계산하면 목표 값이 되는 식이 있는가"를 정한다. 그래서 세 방향을 모두 잰다:
① 노출 주입 → exposed(RED 신호) ② 값이 다른 대조군 → clean ③ 판정 불가 → undecidable(clean으로
접지 않는다). 그리고 코퍼스 실측에서 드러난 오탐(문자 섞인 식의 *일부*를 잘라 정답과 같다고 보는
것)을 픽스처로 둔다 — 그 규칙이 없으면 승인·미승인 3,735문항의 검수 L3 5,377건 중 2,155건이
오탐으로 거부됐다(2026-10-22 실측).
"""

from __future__ import annotations

from typing import Any

import pytest

from whymath_backend.l3 import verify_solution
from whymath_backend.l3.verify_solution import arithmetic_fragments, scan_value_exposure
from whymath_backend.schema.verification_capabilities import ValueExposure, ValueExposureScan

# P3-10 실측 `aq-h-06-04-l3`의 L3 본문 한 줄(정답 4).
_MVT_LINE = (
    "이것을 한 번 바꾸면 2번째 단계의 식이 돼: (-3) + (4)*((2) - (0)) + (-3) + (1)*((2) - (0)) = y"
)


def test_measured_leak_is_exposed() -> None:
    scan = scan_value_exposure(_MVT_LINE, "4")
    assert scan.outcome is ValueExposure.exposed
    assert scan.fragment == "(-3) + (4)*((2) - (0)) + (-3) + (1)*((2) - (0))"
    assert scan.candidates == 1 and scan.undecided == 0


def test_result_satisfies_the_core_contract() -> None:
    """어댑터 결과가 Core가 읽는 구조적 계약(`ValueExposureScan`)을 만족한다(변환 객체 없음)."""
    assert isinstance(scan_value_exposure(_MVT_LINE, "4"), ValueExposureScan)


def test_different_value_is_clean() -> None:
    """대조군 — 같은 식이라도 목표가 다르면(4 ≠ 5) clean. 과잉 거부가 아니다."""
    scan = scan_value_exposure(_MVT_LINE, "5")
    assert scan.outcome is ValueExposure.clean and scan.candidates == 1


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("참고: 2 + 5", "7"),  # 1자 정답 — 글자 대조가 유보하는 구간
        ("참고: 1/2 + 0", "0.5"),  # 표기가 달라도 값이 같다(정본 채점기 위임)
        ("참고: 2^3", "8"),  # 거듭제곱 표기
        ("참고: 3 × 4", "12"),  # 곱셈 기호 정규화
        ("참고: 1 + 1", "x = 2, x = 3"),  # 여러 값 중 하나만 드러내도 노출
        ("참고: 2 + 2", "y = 4"),  # 목표가 관계식(최종 단계)이어도 값으로 비교
        ("참고: 1 + 1", "\\frac{4}{2}"),  # LaTeX 목표는 단일 권위로 평문화
    ],
)
def test_value_equal_expressions_are_exposed(text: str, target: str) -> None:
    assert scan_value_exposure(text, target).outcome is ValueExposure.exposed


def test_expression_inside_a_symbolic_expression_is_not_a_candidate() -> None:
    """`Derivative(x - 1 + 1, x)` 속 `- 1 + 1`(= 0)은 독립 식이 아니다 — 변 *전체*만 대상이다."""
    text = "첫 단계에서 적는 식은 다음과 같아: (Derivative(x - 1 + 1, x) - 3).doit()"
    assert arithmetic_fragments(text) == []
    assert scan_value_exposure(text, "0").outcome is ValueExposure.clean


def test_relation_side_is_a_candidate_but_a_bare_number_is_not() -> None:
    """`3*(2) + 1 = y`의 좌변은 대상. 수 1개(`x = 7`의 7)는 산술식이 아니다(글자 축의 몫)."""
    assert arithmetic_fragments("y = 3*(2) + 1, x = 7") == ["3*(2) + 1"]


def test_truncated_run_is_not_a_candidate_and_not_undecidable() -> None:
    """괄호 짝이 안 맞는 잘린 조각은 식이 아니다 — 판정 불가로도 세지 않는다(대상 0)."""
    scan = scan_value_exposure("앞에서 ((2) + (3) 까지 봤어", "5")
    assert scan.outcome is ValueExposure.clean and scan.candidates == 0


@pytest.mark.parametrize("target", ["{1, 6}", "3개", "(1, 4)"])
def test_unreadable_target_is_undecidable_not_clean(target: str) -> None:
    """목표 값을 읽지 못하면 판정 불가 — clean으로 접지 않는다(모른다 ≠ 아니다)."""
    scan = scan_value_exposure("참고: 2 + 2", target)
    assert scan.outcome is ValueExposure.undecidable and scan.undecided == 1


def test_empty_target_with_candidates_is_undecidable() -> None:
    scan = scan_value_exposure("참고: 2 + 2", "  ")
    assert scan.outcome is ValueExposure.undecidable


def test_no_candidates_is_clean_without_reading_the_target() -> None:
    """볼 식이 없으면 목표를 읽을 필요가 없다 — 읽을 수 없는 목표여도 clean(candidates=0)."""
    scan = scan_value_exposure("풀이는 모두 4단계로 이어져. 지금은 2번째 단계야.", "{1, 6}")
    assert scan.outcome is ValueExposure.clean and scan.candidates == 0


def test_programming_errors_are_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """식 해석기 호출 계약이 깨지면(TypeError) 삼키지 않는다 — 삼키면 무관용 축이 통과로 바뀐다."""

    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise TypeError("unexpected keyword argument")

    monkeypatch.setattr(verify_solution, "safe_sympify", broken)
    with pytest.raises(TypeError):
        scan_value_exposure("참고: 2 + 2", "4")
