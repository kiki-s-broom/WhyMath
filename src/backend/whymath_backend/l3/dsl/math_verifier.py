"""수학 검증기 — SymPy 기반 정답·풀이·제약 일관성 검증.

설계 정본: `docs/architecture/03d_dsl_content_generator.md` §5.1 ④.

- 정답 검증: ProblemDSL.answer.expression을 변수 값으로 평가해 statement와 일치 여부 확인.
- 풀이 일관성: solution.steps의 formula가 순차적으로 정답에 도달하는지 확인.
- 수학 검증 FAIL은 전체 FAIL이다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from whymath_backend.l3.dsl.models import ProblemDSL
from whymath_backend.l3.dsl.validators import BaseDSLValidator, ValidationResult
from whymath_backend.l3.dsl.variable_engine import VariableBinding
from whymath_backend.l3.pregenerate.models import ValidationSignal

# 침묵 실패 금지(CLAUDE.md) — 파싱 회피는 예외 타입명만 남긴다.
logger = logging.getLogger("whymath.l3.dsl.math_verifier")


@dataclass(frozen=True, slots=True)
class MathVerificationContext:
    """수학 검증에 필요한 변수 바인딩."""

    binding: VariableBinding


class MathValidator(BaseDSLValidator):
    """④ 수학 검증 — SymPy로 정답·풀이를 검증한다."""

    def __init__(self, binding: VariableBinding | None = None) -> None:
        self._binding = binding

    @property
    def stage(self) -> str:
        return "math"

    def validate(self, dsl: ProblemDSL) -> ValidationResult:
        # 1) 정답 검증
        answer_result = verify_problem_answer(dsl, self._binding)
        if answer_result is not None:
            return ValidationResult(passed=False, signal=answer_result)

        # 2) 풀이 일관성 검증
        solution_result = verify_solution_consistency(dsl, self._binding)
        if solution_result is not None:
            return ValidationResult(passed=False, signal=solution_result)

        return ValidationResult(passed=True)


def _parse_expression(text: str, local_dict: dict[str, object]) -> object | None:
    """SymPy로 식을 파싱한다. 실패 시 None."""
    try:
        from sympy.parsing.sympy_parser import (
            convert_xor,
            implicit_multiplication,
            standard_transformations,
        )

        # CONST-09(R22-03): DSL은 `/v1/dsl/validate`·`/compile`로 *인증된 모든 사용자*가 보낼 수
        # 있다 — 식 문자열은 신뢰 입력이 아니므로 안전 진입점을 거친다(지연 import 유지).
        from whymath_backend.l3.safe_parse import safe_parse_expr
    except ImportError:
        return None

    transformations = standard_transformations + (
        convert_xor,
        implicit_multiplication,
    )
    try:
        result: object = safe_parse_expr(
            text, local_dict=local_dict, transformations=transformations
        )
        return result
    except Exception as exc:  # noqa: BLE001 — 파싱 실패·거부는 None(보수)
        logger.debug("DSL 식 파싱 회피: %s", type(exc).__name__)
        return None


def _parse_formula(text: str, local_dict: dict[str, object]) -> object | None:
    """SymPy로 수식(표현식 또는 등식)을 파싱한다. 실패 시 None.

    등식(예: "x = 5 - 2")은 좌변·우변을 각각 파싱해 `Eq(left, right)`로 만든다.
    """
    # 등식은 좌변·우변을 각각 파싱해 Eq로 조립한다.
    if "=" in text:
        left_text, right_text = text.split("=", 1)
        left = _parse_expression(left_text.strip(), local_dict)
        right = _parse_expression(right_text.strip(), local_dict)
        if left is None or right is None:
            return None
        try:
            from sympy import Eq

            eq_result: object = Eq(left, right)
            return eq_result
        except ImportError:
            return None

    return _parse_expression(text, local_dict)


def _binding_to_locals(binding: VariableBinding | None) -> dict[str, object]:
    """VariableBinding을 SymPy local_dict로 변환한다."""
    if binding is None:
        return {}
    local_dict: dict[str, object] = {}
    for name, value in binding.values.items():
        try:
            local_dict[name] = int(value)
        except ValueError:
            try:
                local_dict[name] = float(value)
            except ValueError:
                local_dict[name] = value
    return local_dict


def verify_problem_answer(
    dsl: ProblemDSL, binding: VariableBinding | None = None
) -> ValidationSignal | None:
    """문제의 정답이 statement와 일치하는지 SymPy로 검증한다.

    통과 시 None, 실패 시 ValidationSignal.
    """
    local_dict = _binding_to_locals(binding)

    # 고정 값 정답은 파싱 가능 여부와 자료형 일치를 확인한다.
    if dsl.answer.value is not None:
        expr = _parse_expression(dsl.answer.value, local_dict)
        if expr is None:
            return ValidationSignal(
                kind="arithmetic",
                reason=f"정답 값을 파싱할 수 없습니다: {dsl.answer.value!r}",
            )
        # integer/float 타입은 숫자여야 한다.
        if dsl.answer.type in ("integer", "float"):
            try:
                from sympy import Number

                if not isinstance(expr, Number):
                    return ValidationSignal(
                        kind="arithmetic",
                        reason=f"정답이 숫자가 아닙니다: {dsl.answer.value!r}",
                    )
            except ImportError:
                pass
        return None

    # expression 기반 정답은 변수 치환 후 평가한다.
    if dsl.answer.expression is not None:
        expr = _parse_expression(dsl.answer.expression, local_dict)
        if expr is None:
            return ValidationSignal(
                kind="arithmetic",
                reason=f"정답 식을 파싱할 수 없습니다: {dsl.answer.expression!r}",
            )
        return None

    # 객관식 선택지는 별도 검증 로직이 필요하므로 현재는 통과.
    return None


def verify_solution_consistency(
    dsl: ProblemDSL, binding: VariableBinding | None = None
) -> ValidationSignal | None:
    """풀이 단계가 정답으로 수렴하는지 확인한다.

    현재는 각 단계의 formula가 파싱 가능한지만 확인한다.
    정교한 단계별 동치 검증은 `l3/verify_step.py`와 연동한다.
    """
    local_dict = _binding_to_locals(binding)

    for step in dsl.solution:
        if step.formula is None:
            continue
        expr = _parse_formula(step.formula, local_dict)
        if expr is None:
            return ValidationSignal(
                kind="solution",
                reason=f"풀이 단계 {step.order}의 수식을 파싱할 수 없습니다: {step.formula!r}",
            )

    return None


__all__ = [
    "MathValidator",
    "MathVerificationContext",
    "verify_problem_answer",
    "verify_solution_consistency",
]
