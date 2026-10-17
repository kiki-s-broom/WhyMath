"""Variable DSL / 문제 변형 엔진 — 템플릿 + 변수 + 제약 → 결정론적 인스턴스.

설계 정본: `docs/architecture/03d_dsl_content_generator.md` §6.

핵심 불변식:
- 난수 시드가 주어지면 같은 시드는 같은 인스턴스를 만든다(재현 가능).
- 제약은 SymPy로 검증한다(자체 CAS 금지).
- 제약을 만족하는 조합이 없으면 명확한 오류를 던진다(침묵 실패 금지).
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass

from whymath_backend.l3.dsl.models import ProblemTemplate, VariableSpec

# 침묵 실패 금지(CLAUDE.md) — 제약 파싱 회피는 예외 타입명만 남긴다.
logger = logging.getLogger("whymath.l3.dsl.variable_engine")


@dataclass(frozen=True, slots=True)
class VariableBinding:
    """한 인스턴스의 변수 값 바인딩."""

    values: dict[str, str]

    def apply(self, text: str) -> str:
        """텍스트 내 {name} 자리를 값으로 치환한다."""
        result = text
        for key, value in self.values.items():
            result = result.replace("{" + key + "}", value)
        return result


class VariableEngine:
    """템플릿 기반 문제 변형 엔진."""

    def __init__(self, template: ProblemTemplate) -> None:
        self._template = template

    def generate(self, seed: int | None = None) -> VariableBinding:
        """변수 값을 샘플링하고 제약을 검증해 바인딩을 만든다.

        Args:
            seed: 난수 시드. None이면 시스템 난수.

        Returns:
            VariableBinding — {변수명: 문자열 값}.

        Raises:
            ValueError: 제약을 만족하는 조합을 찾지 못함.
        """
        rng = random.Random(seed)
        variables = self._template.variables

        if not variables:
            return VariableBinding(values={})

        # 변수 이름 순서를 정렬해 재현 가능하게 한다.
        names = sorted(variables.keys())
        max_attempts = 1000

        for _ in range(max_attempts):
            candidate: dict[str, str] = {}
            for name in names:
                spec = variables[name]
                candidate[name] = self._sample_value(spec, rng)

            if self._satisfies_constraints(candidate):
                return VariableBinding(values=candidate)

        raise ValueError(
            f"제약을 만족하는 변수 조합을 {max_attempts}회 내에 찾지 못했습니다: " f"{names}"
        )

    def instantiate(self, binding: VariableBinding) -> str:
        """템플릿 본문에 바인딩을 적용해 최종 문제 본문을 만든다."""
        if self._template.template is not None:
            return binding.apply(self._template.template)
        if self._template.statement is not None:
            return self._template.statement
        raise ValueError("ProblemTemplate에 statement와 template이 모두 없습니다.")

    def _sample_value(self, spec: VariableSpec, rng: random.Random) -> str:
        if spec.default is not None:
            return spec.default
        if spec.type == "string":
            if spec.choices is None:
                raise ValueError("string 변수는 choices가 필요합니다.")
            return rng.choice(spec.choices)
        if spec.range is None:
            raise ValueError(f"{spec.type} 변수는 range가 필요합니다.")

        min_v, max_v = spec.range
        if spec.type == "integer":
            return str(rng.randint(int(min_v), int(max_v)))
        # float
        return str(rng.uniform(min_v, max_v))

    def _satisfies_constraints(self, binding: dict[str, str]) -> bool:
        """제약을 SymPy로 검증한다."""
        if not self._template.constraints:
            return True

        # 지연 import — sympy가 없는 환경에서도 모듈 로드는 가능해야 한다.
        try:
            from sympy.parsing.sympy_parser import (
                convert_xor,
                implicit_multiplication,
                standard_transformations,
            )

            # CONST-09(R22-03): 제약식은 `/v1/dsl/*`로 사용자가 보낼 수 있다 — 안전 진입점 경유.
            from whymath_backend.l3.safe_parse import safe_parse_expr
        except ImportError as exc:
            raise RuntimeError("VariableEngine 제약 검증에는 sympy가 필요합니다.") from exc

        transformations = standard_transformations + (
            convert_xor,
            implicit_multiplication,
        )

        local_dict: dict[str, object] = {}
        for name, value in binding.items():
            try:
                local_dict[name] = int(value)
            except ValueError:
                try:
                    local_dict[name] = float(value)
                except ValueError:
                    local_dict[name] = value

        for constraint in self._template.constraints:
            expr_text = constraint.expression
            try:
                expr = safe_parse_expr(
                    expr_text, local_dict=local_dict, transformations=transformations
                )
            except Exception as exc:  # noqa: BLE001 — 파싱 실패·안전 파싱 거부는 제약 불충족
                logger.debug("DSL 제약식 파싱 회피: %s", type(exc).__name__)
                return False

            try:
                if hasattr(expr, "doit"):
                    expr = expr.doit()
                if hasattr(expr, "is_true"):
                    result = expr.is_true
                    if result is False:
                        return False
                    elif result is None:
                        return False
                elif hasattr(expr, "is_number"):
                    if expr.is_number and expr == 0:
                        return False
                else:
                    # 비교식이 아니면 bool로 평가
                    if not bool(expr):
                        return False
            except Exception:
                return False

        return True


__all__ = ["VariableBinding", "VariableEngine"]
