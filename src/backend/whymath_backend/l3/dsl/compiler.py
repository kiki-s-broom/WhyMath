"""콘텐츠 컴파일러 — ProblemDSL → CompiledContent / ConceptDSL.

설계 정본: `docs/architecture/03d_dsl_content_generator.md` §8.3.

DSL을 Runtime이 소비할 수 있는 형태로 변환한다.
"""

from __future__ import annotations

import logging

from whymath_backend.l3.dsl.models import CompiledContent, ProblemDSL
from whymath_backend.l3.dsl.variable_engine import VariableBinding, VariableEngine

# 침묵 실패 금지(CLAUDE.md) — 폴백 경로는 예외 타입명만 남긴다.
logger = logging.getLogger("whymath.l3.dsl.compiler")


class ContentCompiler:
    """ProblemDSL을 Runtime 객체로 컴파일한다."""

    def compile(
        self,
        dsl: ProblemDSL,
        binding: VariableBinding | None = None,
    ) -> CompiledContent:
        """DSL을 컴파일한다.

        binding이 주어지면 변수를 치환한 최종 본문·정답을 만든다.
        """
        if binding is None:
            engine = VariableEngine(dsl.problem)
            binding = engine.generate(seed=0)

        problem_text = self._render_text(dsl.problem.statement, dsl.problem.template, binding)
        answer_text = self._resolve_answer(dsl, binding)
        solution_texts = tuple(step.content for step in sorted(dsl.solution, key=lambda s: s.order))
        hint_texts = tuple(h.text for h in sorted(dsl.hints, key=lambda h: h.level))

        concept_dsl = self._to_concept_dsl(dsl)

        return CompiledContent(
            content_id=dsl.content_id,
            runtime_type="math_problem",
            render={"type": "equation_problem" if "=" in problem_text else "problem"},
            grading={"type": self._grading_type(dsl)},
            problem_text=problem_text,
            answer=answer_text,
            solution_texts=solution_texts,
            hint_texts=hint_texts,
            concept_dsl=concept_dsl,
        )

    def _render_text(
        self,
        statement: str | None,
        template: str | None,
        binding: VariableBinding,
    ) -> str:
        if template is not None:
            return binding.apply(template)
        if statement is not None:
            return statement
        return ""

    def _resolve_answer(self, dsl: ProblemDSL, binding: VariableBinding) -> str:
        if dsl.answer.value is not None:
            return binding.apply(dsl.answer.value)
        if dsl.answer.expression is not None:
            # expression은 SymPy로 평가해 최종 값으로 만든다.
            try:
                from sympy.parsing.sympy_parser import (
                    convert_xor,
                    implicit_multiplication,
                    standard_transformations,
                )

                # CONST-09(R22-03): 정답 식은 `/v1/dsl/compile`로 사용자가 보낼 수 있다.
                from whymath_backend.l3.safe_parse import safe_parse_expr

                transformations = standard_transformations + (
                    convert_xor,
                    implicit_multiplication,
                )
                local_dict: dict[str, object] = {}
                for name, value in binding.values.items():
                    try:
                        local_dict[name] = int(value)
                    except ValueError:
                        try:
                            local_dict[name] = float(value)
                        except ValueError:
                            local_dict[name] = value

                expr = safe_parse_expr(
                    dsl.answer.expression,
                    local_dict=local_dict,
                    transformations=transformations,
                )
                # parse_expr가 이미 값으로 평가한 경우(Python 숫자) 그대로 사용.
                if isinstance(expr, (int, float)):
                    evaluated = float(expr)
                else:
                    evaluated = expr.evalf()
                # 정수면 int로, 아니면 float로 표현
                if evaluated == int(evaluated):
                    return str(int(evaluated))
                return str(float(evaluated))
            except Exception as exc:  # noqa: BLE001 — 평가 실패·안전 파싱 거부는 원문 폴백
                # SymPy 평가 실패 시 치환된 원문을 그대로 반환(예외 타입명만 로그 — 침묵 실패 금지)
                logger.debug("DSL 정답 식 평가 회피: %s", type(exc).__name__)
                return binding.apply(dsl.answer.expression)
        if dsl.answer.choices is not None:
            return ",".join(dsl.answer.choices)
        return ""

    def _grading_type(self, dsl: ProblemDSL) -> str:
        if dsl.answer.type == "integer":
            return "numeric"
        if dsl.answer.type == "choice":
            return "choice"
        return "expression"

    def _to_concept_dsl(self, dsl: ProblemDSL) -> dict[str, object] | None:
        """ProblemDSL에서 ConceptDSL 투영을 만든다.

        L4/L5가 소비하는 교수법-중립 개념 자산으로 변환한다.
        `ConceptDSL`은 `l3/render/dsl.py`에 정의돼 있으나, 그 모듈을 임포트하면
        프로젝트 전체 의존성(pgvector 등)이 끌려오므로 여기서는 dict로 투영한다.
        """
        try:
            return {
                "code": dsl.content_id,
                "name": dsl.curriculum.concept,
                "subject": dsl.curriculum.subject,
                "unit": dsl.curriculum.domain,
                "definition": None,
                "intuition": None,
                "examples": (dsl.problem.statement or dsl.problem.template or "",),
                "misconceptions": dsl.misconception.target if dsl.misconception else (),
                "relations": (),
                "assessment": None,
            }
        except Exception:
            return None


__all__ = ["ContentCompiler"]
