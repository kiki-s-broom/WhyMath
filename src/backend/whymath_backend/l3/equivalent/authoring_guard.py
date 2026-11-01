"""LLM 저작 산출물의 생성 단계 거부 규칙 — 검산식 근거·정답 키·단원 코드·교육과정 범위 (EOS-205).

왜 필요한가
----------
EOS-197 A6 회차(30 CU)의 검수 메모에 같은 결함 네 가지가 반복됐다.

1. **검산식이 문항을 다시 계산하지 않는다** — `n = 3`·`v - 24 = 0`처럼 정답 상수를 다시 적거나
   (재진술), `b = 7*(0 - 2)`처럼 모델이 미리 구한 중간값(기울기 7)을 박아 넣는다. 정답이 틀려도
   모델은 같은 틀린 값으로 식을 적으므로 Tier1 대입 검산이 **항상 통과한다** — 검증이 아니라
   자기 확인이다(학생 제공 전 검증 원칙 위반 위험).
2. **정답 키가 제각각** — `b`·`v`·`n`·`y`·`M`·`answer`가 섞였다.
3. **단원 코드가 비표준** — `CALC1-TANGENT`·`CAL-TANGENT`·`MI-CALC-EXTREMA` 등 회차 하나에 15종.
4. **교육과정 밖 해설** — 미적분Ⅰ 극값 문항 해설이 이계도함수(f″)로 판정했다(수정승인 2건).

이 모듈은 넷을 **결정론 순수 함수**로 판정한다. 호출부는 `llm_generator._assemble`이고, 거부는
`ValueError` 하위 예외로 올라가 생성 실패(`후보 조립 실패: <예외 타입명>`)로 GenerationLog에 남는다
— 타입명이 사유를 가르므로 회차 측정에서 "동어반복으로 버린 건수"를 셀 수 있다.

검산식 근거 판정 (`grounding_verdict`)
------------------------------------
조건 목록과 발문을 받아 네 상태 중 하나를 낸다.

- **RESTATEMENT** — 기존 판정기 `verify_bypass.classify_verify_bypass`(EOS-207)가 우회로 판정
  (정답 상수 재진술·무조건 참). 그 판정기를 그대로 재사용한다(규칙 중복 금지).
- **GROUNDED** — 검산식의 어느 부분식이 **발문의 함수 P(또는 P′·P″)를 실제로 계산**한다.
    · 기호 부분식: `(x**3 - 5*x + 2)`처럼 P(또는 P′·P″)의 상수배와 같은 식(`.subs(x, 2)` 꼴 포함)
    · 수치 부분식: `(3*2**2 - 5)`처럼 **점 a를 대입한 꼴**의 식 — 값이 P(a)·P′(a)·P″(a)와 같고,
      그 식에서 a의 출현 일부를 변수로 되돌리면 정확히 P(또는 P′·P″)가 된다(구조 일치).
      Kiki 검수 메모의 교체안 `answer == (2**3 - 5*2 + 2) - 2*(3*2**2 - 5)`가 이 꼴이다.
      값만 보면 `-2*1`(미리 구한 기울기 -2를 박은 식)이 f′(1) = -2와 우연히 같아 통과하므로
      구조 일치를 함께 요구한다.
    · 방정식 문항: 조건 전체가 발문의 방정식과 같은 정규형(`canonicalize.canonical_condition`)
- **UNGROUNDED** — 발문에서 함수·방정식을 읽었는데 검산식이 그중 어느 것도 쓰지 않는다
  (`b = 7*(0 - 2)` 기울기 하드코딩 · `M**2 - M - 182 = 0` 정답을 근으로 거꾸로 만든 이차식).
- **UNKNOWN** — 발문에서 함수·방정식을 하나도 읽지 못했다. 근거 유무를 판정할 수 없으므로
  거부하지 않는다(모른다 ≠ 아니다) — 호출부가 경고 로그를 남긴다. 아래 한계 참조.

정직한 한계(있는 척 금지)
-----------------------
- 발문 함수 추출은 `f(x) = …`·`s(t) = …`·`y = …`·`… = 0` 꼴의 **다항·유리식 표기만** 읽는다.
  `sqrt`·삼각함수·로그 등 함수 이름이 든 식은 암묵 곱셈 보정과 충돌해 읽지 못할 수 있고, 그러면
  UNKNOWN이 되어 이 판정이 걸리지 않는다(재진술 판정은 여전히 걸린다).
- 이 판정은 적대적 회피가 아니라 *게으른 검산식*(정답·중간값 하드코딩)을 막는 것이 목적이다.
  구조 일치는 "P에 a를 대입한 식이 검산식 안에 있다"까지만 보장한다 — 그 대입식을 정답과 어떻게
  엮었는지(접선 공식 자체가 옳은지)는 Tier1 대입 검산과 사람 검수의 몫이다.
- 한 점의 출현이 8개를 넘는 부분식은 구조 일치를 시도하지 않는다(부분집합 2^N 상한).
- 상수 도함수(이차함수의 P″ 등)는 후보에서 뺀다 — 상수는 어느 수치식과도 너무 쉽게 같아진다.
"""

from __future__ import annotations

import ast
import copy
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from itertools import combinations

import sympy

from whymath_backend.l3.equivalent.canonicalize import canonical_condition
from whymath_backend.l3.equivalent.verify_bypass import classify_verify_bypass
from whymath_backend.l3.safe_parse import safe_sympify
from whymath_backend.l3.verify_answer import _relation_sides

__all__ = [
    "ANSWER_KEY",
    "AuthoringGuardError",
    "CurriculumScopeError",
    "GroundingState",
    "GroundingVerdict",
    "QuestionRelations",
    "TautologicalConditionError",
    "curriculum_method_violation",
    "extract_question_relations",
    "grounding_verdict",
    "normalize_answer_key",
    "standard_unit_codes",
]

# 정답 키 표준 — 답이 방정식의 근이 아닌 문항(접선의 y절편·극값·속도·개수)은 이 이름으로 고정한다.
ANSWER_KEY = "answer"


class AuthoringGuardError(ValueError):
    """생성 단계 거부의 공통 상위형 — `ValueError` 하위라 기존 조립 실패 경로(None 폴백)를 탄다."""


class TautologicalConditionError(AuthoringGuardError):
    """검산식이 문항을 다시 계산하지 않는다(재진술·중간값 하드코딩·역산 식)."""


class CurriculumScopeError(AuthoringGuardError):
    """해설·발문이 그 성취기준의 교육과정 범위 밖 방법을 쓴다."""


class GroundingState(str, Enum):
    """검산식 근거 판정 4상태(모듈 docstring)."""

    GROUNDED = "grounded"
    RESTATEMENT = "restatement"
    UNGROUNDED = "ungrounded"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class GroundingVerdict:
    """판정 결과 — `rejected`가 True면 호출부가 생성을 거부한다."""

    state: GroundingState
    reason: str

    @property
    def rejected(self) -> bool:
        return self.state in (GroundingState.RESTATEMENT, GroundingState.UNGROUNDED)


@dataclass(frozen=True, slots=True)
class QuestionRelations:
    """발문에서 읽은 수식 관계.

    - `functions`: (변수 이름, P) — `f(x) = …` 꼴의 함수 정의.
    - `equations`: 방정식 원문(SymPy 표기) — 근을 묻는 문항의 근거 대조용.
    - `variables`: 발문 수식의 자유 기호 이름(정답 키 정규화가 "문항 자신의 변수"를 가르는 데 쓴다).
    """

    functions: tuple[tuple[str, sympy.Expr], ...]
    equations: tuple[str, ...]
    variables: frozenset[str]

    @property
    def empty(self) -> bool:
        return not self.functions and not self.equations


# ── 발문 수식 추출 ─────────────────────────────────────────────────────────
# 발문 속 수식으로 볼 문자(한글·쉼표를 만나면 멈춘다 — `(2, 0)`·`의`·`로` 경계).
_MATH_CHAR = re.compile(r"[0-9A-Za-z+\-*/^().\s²³⁴−·×]")
# 함수 머리: `f(x)`·`s(t)`·`x(t)` — 한 글자 이름 + 한 글자 변수.
_FUNCTION_HEAD = re.compile(r"^([A-Za-z])\s*\(\s*([A-Za-z])\s*\)$")
# 위첨자·유니코드 연산자 → SymPy 표기.
_SUPERSCRIPTS = {"²": "**2", "³": "**3", "⁴": "**4"}
_UNICODE_OPS = {"−": "-", "×": "*", "·": "*"}
# 꼬리 다듬기 시도 상한 — `3 (x의`처럼 수식 뒤에 붙은 괄호 조각을 잘라 보는 횟수.
_TRIM_ATTEMPTS = 6


def _normalize_math(text: str) -> str:
    """발문 수식 표기 → SymPy 표기(`^`·위첨자·유니코드 연산자·암묵 곱셈)."""
    out = text.strip()
    for src, dst in {**_SUPERSCRIPTS, **_UNICODE_OPS}.items():
        out = out.replace(src, dst)
    out = out.replace("^", "**")
    # 암묵 곱셈: `5x`→`5*x` · `)(`→`)*(` · `)x`→`)*x` · `xy`→`x*y` · `x(`→`x*(`.
    out = re.sub(r"(\d)\s*(?=[A-Za-z(])", r"\1*", out)
    out = re.sub(r"\)\s*(?=[A-Za-z0-9(])", ")*", out)
    out = re.sub(r"([A-Za-z])(?=[A-Za-z(])", r"\1*", out)
    return out


def _parse_math(text: str, allowed: frozenset[str] | None = None) -> sympy.Expr | None:
    """발문 수식 조각 → SymPy 식. 꼬리의 괄호 조각을 잘라 가며 재시도하고, 끝내 못 읽으면 None.

    `allowed`를 주면 자유 기호가 그 안에 들어올 때까지 꼬리를 더 자른다 — `… + 1 (m)`의 단위
    표기 `(m)`가 암묵 곱셈으로 `1*m`이 되어 함수식에 섞이는 것을 막는다.
    """
    candidate = text.strip().rstrip(".")
    # 짝 없는 여는 괄호 머리 제거 — `\( x^2 - 5x + 6 = 0 \)`의 왼쪽은 `( x^2 - 5x + 6`로 잘린다.
    while candidate.startswith("(") and candidate.count("(") > candidate.count(")"):
        candidate = candidate[1:].lstrip()
    for _ in range(_TRIM_ATTEMPTS):
        if not candidate:
            return None
        try:
            expr = safe_sympify(_normalize_math(candidate))
        except Exception:  # noqa: BLE001 — 발문 수식을 못 읽으면 다음 꼬리 자르기로(판정은 호출부)
            expr = None
        if isinstance(expr, sympy.Expr) and (
            allowed is None or {str(s) for s in expr.free_symbols} <= allowed
        ):
            return expr
        # 마지막 여는 괄호 또는 마지막 공백에서 자른다(`… + 3 (x` → `… + 3`).
        cut = max(candidate.rfind("("), candidate.rfind(" "))
        if cut <= 0:
            return None
        candidate = candidate[:cut].rstrip()
    return None


def _scan(text: str, start: int, step: int) -> str:
    """`start`에서 `step` 방향으로 수식 문자가 이어지는 구간을 잘라 낸다."""
    end = start
    while 0 <= end < len(text) and _MATH_CHAR.match(text[end]):
        end += step
    if step > 0:
        return text[start:end]
    return text[end + 1 : start + 1]


def extract_question_relations(question_text: str) -> QuestionRelations:
    """발문 → 함수 정의·방정식·변수 목록. 못 읽은 관계는 조용히 건너뛴다(빈 결과 = UNKNOWN 재료)."""
    functions: list[tuple[str, sympy.Expr]] = []
    equations: list[str] = []
    variables: set[str] = set()
    text = question_text or ""
    for match in re.finditer(r"(?<![<>!=])=(?!=)", text):
        pos = match.start()
        lhs_raw = _scan(text, pos - 1, -1).strip()
        rhs_raw = _scan(text, pos + 1, 1).strip()
        if not lhs_raw or not rhs_raw:
            continue
        head = _FUNCTION_HEAD.match(lhs_raw)
        if head is not None or lhs_raw == "y":
            # 함수 정의 — 우변에 자기 변수만 있어야 함수다(`f(x) = k`는 정의가 아니라 조건).
            # `y = …`는 변수 이름이 머리에 없으므로 x를 기본으로 본다(발문 관례).
            var = head.group(2) if head is not None else "x"
            rhs = _parse_math(rhs_raw, allowed=frozenset({var}))
            if rhs is None or sympy.Symbol(var) not in rhs.free_symbols:
                continue
            functions.append((var, rhs))
            variables.update(str(s) for s in rhs.free_symbols)
            continue
        rhs = _parse_math(rhs_raw)
        lhs = _parse_math(lhs_raw)
        if lhs is None or rhs is None:
            continue
        residual = sympy.expand(lhs - rhs)
        if not residual.free_symbols:
            continue
        equations.append(f"{sympy.sstr(lhs)} = {sympy.sstr(rhs)}")
        variables.update(str(s) for s in residual.free_symbols)
    return QuestionRelations(tuple(functions), tuple(equations), frozenset(variables))


# ── 검산식 근거 판정 ─────────────────────────────────────────────────────
def _candidates(relations: QuestionRelations) -> list[tuple[sympy.Symbol, sympy.Expr]]:
    """대조 후보 — 함수 P와 그 1·2계 도함수(상수는 제외)."""
    out: list[tuple[sympy.Symbol, sympy.Expr]] = []
    for name, expr in relations.functions:
        var = sympy.Symbol(name)
        for order in range(3):
            derived = sympy.expand(sympy.diff(expr, var, order) if order else expr)
            if var in derived.free_symbols:
                out.append((var, derived))
    return out


def _symbolic_match(
    expr: sympy.Expr, candidates: Sequence[tuple[sympy.Symbol, sympy.Expr]]
) -> bool:
    """기호 부분식이 후보 하나의 상수배인가(0배 제외)."""
    for var, cand in candidates:
        if var not in expr.free_symbols:
            continue
        ratio = sympy.cancel(expr / cand)
        if not ratio.free_symbols and ratio != 0:
            return True
    return False


# 한 점의 출현 위치 상한 — 부분집합 시도가 2^N이라 N을 묶는다(문항 하나의 대입식은 이보다 짧다).
_MAX_OCCURRENCES = 8

_PositionKey = tuple[int, int, str]


def _key(node: ast.AST) -> _PositionKey:
    return (
        getattr(node, "col_offset", -1),
        getattr(node, "end_col_offset", -1),
        type(node).__name__,
    )


def _point_occurrences(node: ast.AST) -> dict[sympy.Expr, list[_PositionKey]]:
    """부분식에 나오는 '대입된 점' 후보 → 그 출현 위치들. 지수 자리는 구조라서 보지 않는다.

    `(-1)**3`의 -1처럼 음수 점은 `-(1)` 단항 노드 하나로 출현한다(양수 1의 출현과 따로 센다).
    """
    found: dict[sympy.Expr, list[_PositionKey]] = {}

    def add(value: sympy.Expr, sub: ast.AST) -> None:
        found.setdefault(value, []).append(_key(sub))

    def walk(sub: ast.AST) -> None:
        if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Pow):
            walk(sub.left)  # 지수(right)는 대입된 점이 아니다
            return
        if isinstance(sub, ast.Constant) and type(sub.value) in (int, float):
            add(sympy.nsimplify(sub.value), sub)
            return
        if (
            isinstance(sub, ast.UnaryOp)
            and isinstance(sub.op, ast.USub)
            and isinstance(sub.operand, ast.Constant)
            and type(sub.operand.value) in (int, float)
        ):
            add(-sympy.nsimplify(sub.operand.value), sub)
        for child in ast.iter_child_nodes(sub):
            walk(child)

    walk(node)
    return found


class _Substitute(ast.NodeTransformer):
    """지정한 위치의 노드를 변수 이름으로 바꾼다(그 점을 다시 변수로 되돌리기)."""

    def __init__(self, keys: frozenset[_PositionKey], name: str) -> None:
        self._keys = keys
        self._name = name

    def visit(self, node: ast.AST) -> ast.AST:
        if _key(node) in self._keys and isinstance(node, (ast.Constant, ast.UnaryOp)):
            return ast.copy_location(ast.Name(id=self._name, ctx=ast.Load()), node)
        visited: ast.AST = super().visit(node)
        return visited


def _structural_match(
    node: ast.AST,
    value: sympy.Expr,
    candidates: Sequence[tuple[sympy.Symbol, sympy.Expr]],
) -> bool:
    """수치 부분식이 '후보 함수에 점 a를 대입한 식'인가 — 값 일치 + 구조 일치 둘 다 본다.

    값만 보면 `-2*1`(미리 구한 기울기 -2를 박은 식)이 P′(1) = -2와 우연히 같아 통과한다.
    그래서 a의 출현 중 일부를 변수로 되돌렸을 때 식이 **정확히** 후보(P·P′·P″)가 되는지 본다 —
    `(2**3 - 5*2 + 2)`는 앞의 두 2를 x로 되돌리면 `x**3 - 5*x + 2`가 된다(마지막 2는 상수항).
    """
    for point, positions in _point_occurrences(node).items():
        if len(positions) > _MAX_OCCURRENCES:
            continue
        for var, cand in candidates:
            if sympy.simplify(cand.subs(var, point) - value) != 0:
                continue  # 값이 다르면 구조를 볼 필요도 없다(값 일치는 필요조건)
            for size in range(1, len(positions) + 1):
                for chosen in combinations(positions, size):
                    rebuilt = _Substitute(frozenset(chosen), str(var)).visit(copy.deepcopy(node))
                    try:
                        expr = safe_sympify(ast.unparse(rebuilt))
                    except Exception:  # noqa: BLE001 — 되돌린 식을 못 읽으면 다음 조합으로
                        continue
                    if isinstance(expr, sympy.Expr) and sympy.expand(expr - cand) == 0:
                        return True
    return False


def _side_grounded(side: str, candidates: Sequence[tuple[sympy.Symbol, sympy.Expr]]) -> bool:
    """식 원문 한 변의 부분식 중 문항 함수를 계산하는 것이 있는가."""
    text = side.strip()
    try:
        safe_sympify(text)  # 안전 진입점의 허용 문자·예산 검사를 먼저 통과해야 한다
        tree = ast.parse(text.replace("^", "**"), mode="eval")
    except Exception:  # noqa: BLE001 — 못 읽은 변은 근거 없음으로 본다(호출부가 UNGROUNDED 판정)
        return False
    for node in ast.walk(tree.body):
        if not isinstance(node, (ast.BinOp, ast.UnaryOp, ast.Call)):
            continue  # 잎(수·이름)은 계산이 아니다 — 상수 하나가 P(a)와 우연히 같은 것을 배제
        segment = ast.get_source_segment(text, node)
        if not segment:
            continue
        try:
            expr = safe_sympify(segment)
        except Exception:  # noqa: BLE001 — 부분식 하나를 못 읽어도 다른 부분식으로 계속
            continue
        if not isinstance(expr, sympy.Expr):
            continue
        if expr.free_symbols:
            if _symbolic_match(expr, candidates):
                return True
        elif _structural_match(node, expr, candidates):
            return True
    return False


def _condition_list(conditions: str | Sequence[str]) -> list[str]:
    return [conditions] if isinstance(conditions, str) else list(conditions)


def grounding_verdict(
    question_text: str,
    conditions: str | Sequence[str],
    answer_map: Mapping[str, str],
) -> GroundingVerdict:
    """검산식이 문항을 다시 계산하는가 — 모듈 docstring의 4상태 판정."""
    items = _condition_list(conditions)
    if answer_map:
        bypass = classify_verify_bypass({"conditions": items, "answer_map": dict(answer_map)})
        if bypass.bypassed is True:
            return GroundingVerdict(
                GroundingState.RESTATEMENT, f"검산식 우회(EOS-207 {bypass.kind.value})"
            )
    relations = extract_question_relations(question_text)
    if relations.empty:
        return GroundingVerdict(GroundingState.UNKNOWN, "발문에서 함수·방정식을 읽지 못함")
    question_forms = {canonical_condition(eq) for eq in relations.equations} - {None}
    if any(canonical_condition(c) in question_forms for c in items):
        return GroundingVerdict(GroundingState.GROUNDED, "발문의 방정식과 같은 검산식")
    candidates = _candidates(relations)
    for condition in items:
        if any(_side_grounded(side, candidates) for side in _relation_sides(condition)):
            return GroundingVerdict(GroundingState.GROUNDED, "문항 함수를 계산하는 부분식이 있다")
    return GroundingVerdict(
        GroundingState.UNGROUNDED,
        "검산식이 문항의 함수·방정식을 쓰지 않는다(중간값 하드코딩·역산 식)",
    )


# ── 정답 키 정규화 ───────────────────────────────────────────────────────
def normalize_answer_key(
    question_text: str,
    conditions: str | list[str],
    answer_map: Mapping[str, str],
) -> tuple[str | list[str], dict[str, str]]:
    """답이 근이 아닌 문항의 정답 키를 `answer`로 고정한다.

    정답 변수가 **발문 수식의 자기 변수**(근을 묻는 방정식의 `x` 등)면 그대로 둔다 — 그 이름을
    바꾸면 검산식이 발문의 방정식과 갈라진다. 그 밖(`b`·`v`·`M` 등 모델이 지은 이름)은 검산식
    원문과 치환맵 양쪽에서 `answer`로 바꾼다. 이름만 바뀌고 식의 의미는 같다.
    """
    if len(answer_map) != 1:
        return conditions, dict(answer_map)
    ((var, value),) = answer_map.items()
    relations = extract_question_relations(question_text)
    if var == ANSWER_KEY or relations.empty or var in relations.variables:
        # 발문을 못 읽었으면(empty) 그 변수가 문항 자신의 변수인지 모른다 — 건드리지 않는다.
        return conditions, dict(answer_map)
    pattern = re.compile(rf"(?<![A-Za-z0-9_.]){re.escape(var)}(?![A-Za-z0-9_])")
    items = _condition_list(conditions)
    if any(re.search(rf"(?<![A-Za-z0-9_.]){ANSWER_KEY}(?![A-Za-z0-9_])", c) for c in items):
        return conditions, dict(answer_map)  # `answer`가 이미 다른 뜻으로 쓰임 — 바꾸지 않는다
    renamed = [pattern.sub(ANSWER_KEY, c) for c in items]
    new_conditions: str | list[str] = renamed[0] if isinstance(conditions, str) else renamed
    return new_conditions, {ANSWER_KEY: value}


# ── 단원 코드 ────────────────────────────────────────────────────────────
def standard_unit_codes(achievement_standard_codes: Sequence[str]) -> list[str]:
    """성취기준 코드 → 단원 코드(대괄호를 벗긴 표준 표기). `[12미적Ⅰ-02-05]` → `12미적Ⅰ-02-05`.

    LLM이 지은 단원 코드(`CALC1-TANGENT` 등)를 읽지 않고 스펙의 성취기준에서 유도한다 — 저작권
    메타를 LLM과 무관하게 박는 것과 같은 원리(구조적 강제)다.
    """
    codes: list[str] = []
    for code in achievement_standard_codes:
        stripped = code.strip().strip("[]").strip()
        if stripped and stripped not in codes:
            codes.append(stripped)
    return codes


# ── 교육과정 범위 밖 방법 ───────────────────────────────────────────────
# (성취기준 코드 접두, 금지 표현 정규식, 사유). 2022 개정 미적분Ⅰ은 이계도함수를 다루지 않는다
# (이계도함수·변곡점은 미적분Ⅱ) — 극대·극소는 f′의 부호 변화로 판정한다(EOS-197 수정승인 2건).
_METHOD_SCOPE: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "12미적Ⅰ",
        re.compile(
            r"이계\s*도함수|이차\s*도함수|2계\s*도함수|second\s+derivative"
            r"|[fgyF]\s*(?:''|″|′′)",
            re.IGNORECASE,
        ),
        "미적분Ⅰ 범위 밖 — 이계도함수(f″) 대신 f′의 부호 변화로 판정해야 한다",
    ),
)


def curriculum_method_violation(
    achievement_standard_codes: Sequence[str], texts: Iterable[str | None]
) -> str | None:
    """성취기준 범위 밖 방법을 쓰면 사유를, 아니면 None.

    범위 표가 없는 성취기준은 검사하지 않는다.
    """
    body = "\n".join(t for t in texts if t)
    if not body:
        return None
    for prefix, pattern, reason in _METHOD_SCOPE:
        if not any(prefix in code for code in achievement_standard_codes):
            continue
        if pattern.search(body):
            return reason
    return None
