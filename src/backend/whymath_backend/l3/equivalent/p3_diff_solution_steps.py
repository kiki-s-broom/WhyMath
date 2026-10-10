"""P3-03 미분 문항 은행의 풀이 단계(`verify.solution_steps`) 결정론 도출 — SymPy 계산·LLM 0.

`p3_diff_*_skeleton_generator`가 만든 문항(`DiffItem`)마다 **도함수가 든 출발식**에서 시작해 답(또는
답을 고르는 근 목록)까지 가는 SymPy 식 문자열의 연쇄를 만든다. 은행이 Phase 3 계측기
(`l1/standards/phase3_coverage`)의 Concept Completeness 'solution' 연결(해설 + 비어 있지 않은
`solution_steps`)을 갖추게 하려는 것이며, 단계는 손으로 조립하지 않고 **SymPy로 계산**해 넣는다.

소비처 계약(2026-10-07 실측) — 단계가 지켜야 하는 것
---------------------------------------------------
· **수용 게이트**(`l3/equivalent/acceptance._evaluate_verification`): 단계가 있으면 Tier2
  (`verify_solution`)의 **모든 전이가 correct**여야 verified다(incorrect 1건 = failed,
  unverifiable 1건 = unverified → 배치가 그 문항을 적재하지 않는다). 개념형(`answer_kind`)·근 집계
  문항은 게이트가 Tier2 앞에서 반환해 단계를 보지 않으므로, 이 모듈이 *스스로* 전이 전건 correct를
  확인한다
  (`solution_steps`가 그런 연쇄를 못 만들면 ValueError — 조용히 넘기지 않는다).
· **상시 재검증**(`harness/corpus_reverify`): 전이에 incorrect가 하나라도 있으면 fail.
· **WH-S replay**(`whs/corpus_replay`): 길이 ≥ 2·문자열 조건 문항만 싣고 전이마다 `verify_step`
  라벨을 단다(VERIFIED만 좋은 라벨).
· **계측기**(`phase3_coverage`): 비어 있지 않은 list면 '단계 있음'.
· 마지막 단계 = 정답은 *소비처 계약이 아니다*(선례 `problem_bank_generated_v0`은 인수분해형에서
  끝난다). 이 모듈은 가능하면 답에서 끝내고, 못 끝내는 형태(아래 '한계')는 정직하게 그 앞에서
  멈춘다.

`verify_step`이 correct로 판정할 수 있는 형태 — 설계가 이 제약에서 나온다
----------------------------------------------------------------------
· 식↔식: SymPy 항등(상수끼리는 값 일치). 등식↔등식: **실수 해집합이 같다**(미지수 1개·다항식·
  실근만일 때 계산 가능 — 허근이 섞이거나 분모에 미지수가 있으면 판정 불가). 등식↔식 혼합은
  판정 불가다(그래서 한 연쇄는 처음부터 끝까지 한 형태다).
· `.doit()`·`.subs()`는 **한 변 전체**일 때만 안전 파서를 통과한다(`Derivative(...).doit()*2`는
  거부, `(f + Derivative(f, x)*(t - x)).doit().subs(x, a)`는 통과). 그래서 도함수를 산술과 섞어야
  하는 출발식은 '식 전체를 괄호로 묶고 `.doit().subs(x, 점)`'으로 쓴다.
· 유한 근 목록에서 일부만 남기는 전이(답 고르기)는 판정 불가다(S3-08 진부분집합 가드) — 그래서
  `a > 0`·`answer_selection` 같은 *선택*이 필요한 문항의 연쇄는 근 목록에서 끝나고, 선택은
  Tier1(조건 목록·근 선택 검산)이 맡는다.

출발식(setup)
------------
기본은 검산 조건(`conditions`)에서 도함수가 든 등식이다. 조건에 도함수가 없는 문항(생성기가 기울기를
상수로 풀어 쓴 산술식·판별식 등)은 생성기가 `DiffItem.solution_setup`에 출발식을 직접 단다 —
조건식의 상수(기울기 m·함숫값)를 `Derivative(f, x)`·`f`로 되돌려 쓴 것이다. 도함수 부호 조건만 있는
문항(`Derivative(...).doit() < 0`)은 경계점 방정식 `... = 0`을, 실근 개수 문항(3차 이상 다항식
조건)은 그 함수의 임계점 방정식 `Derivative(h, x).doit() = 0`을 출발식으로 삼는다(해설의 첫 단계).

전략(앞에서부터 처음으로 '전이 전건 correct'인 것을 쓴다)
--------------------------------------------------------
A. **방정식 연쇄** — 출발식 → 도함수 전개 → 점 대입 → (정리 → 인수분해) → `u = 값` 또는 근 목록.
B. **정답 대입 검산 연쇄** — A가 판정 불가일 때(허근·유리식·지수에 미지수). 출발식 양변에 정답을
   넣어 같은 값임을 보인다: 도함수 쪽 변 → 도함수 전개 → 대입 → 값 → 다른 변(정답이 든 식).
C. **도함수 식 연쇄** — A·B 모두 불가일 때. `Derivative(f, x).doit()` → 도함수 → 인수분해형.
   임계점 방정식(`f'(x) = 0` 꼴)이 허근 인수 때문에 A로 판정 불가하면 B보다 C를 먼저 쓴다(해설이
   도함수를 인수분해해 실근을 읽는다).

A가 근 목록(`u = r1, u = r2`)으로 끝났는데 정답 u가 그 안에 없으면 다음 전략으로 넘기지 않고
ValueError다(정답이나 출발식이 문항과 어긋난 것 — 단계가 그것을 가리면 안 된다). 예외는 도함수 부호
조건에서 만든 경계점 연쇄뿐이다 — 그 근은 증감 구간의 끝점이고 정답은 구간 안의 정수다.

한계(정직 보고)
--------------
· 미지수가 바뀌는 다단계 풀이(상수 a를 먼저 구하고 임계점을 찾는 극값 문항, 운동 방향이 바뀌는
  시각을 구하고 그때의 위치를 묻는 문항 등)는 한 연쇄에 담을 수 없다(전이가 판정 불가). 이 경우
  연쇄는 도함수가 쓰이는 단계(임계점 방정식)에서 끝나고, 마지막 값은 Tier1 조건이 검산한다.
· 개념형(`real_root_count`) 문항의 답(개수)은 식 연쇄로 표현되지 않는다 — 연쇄는 임계점(또는
  평균값 정리의 c 후보)에서 끝난다.
· 평균값 정리의 *결론*(f'(c) = 평균변화율)만 묻는 진단 틀 둘은 출발식에 도함수가 없다 — 함수식이
  주어지지 않는 틀은 미분할 함수가 없고, 함수식이 주어지는 짝 틀(5회차 감사 교정 · f'(c)의 값을
  묻는다)은 c를 구하지 않고 평균변화율로 f'(c)를 정하는 것이 진단 대상 자체다.

7계층: L3 지역(LLM 0). SymPy·`l3.safe_parse`(CAS 파싱 단일 안전 진입점)·`l3.verify_solution`만
쓴다. 문항·슬롯을 모른다(입력은 문자열·dict).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, cast

import sympy

from whymath_backend.l3.safe_parse import safe_sympify
from whymath_backend.l3.verify_solution import verify_solution

__all__ = [
    "StepChain",
    "apply_subs",
    "derive_setup",
    "expand_derivatives",
    "final_solution_values",
    "solution_steps",
]

_DERIVATIVE: Final = "Derivative"
_DOIT: Final = ".doit()"
_SUBS: Final = ").subs("
_INEQUALITY_SPLIT: Final = re.compile(r"<=|>=|!=|<|>")


@dataclass(frozen=True, slots=True)
class StepChain:
    """도출 결과 — 단계 문자열 연쇄와 어느 전략으로 만들었는지(A/B/C · 테스트·보고용)."""

    steps: tuple[str, ...]
    strategy: str


# ──────────────────────────────────────────────────────────────────────────
# 문자열 도구 — 괄호 짝 맞추기(정규식으로는 중첩 괄호를 못 다룬다)
# ──────────────────────────────────────────────────────────────────────────
def _close_of(text: str, open_index: int) -> int:
    """`text[open_index] == '('`의 짝 ')' 위치."""
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError(f"괄호 짝이 없다: {text!r}")


def _open_of(text: str, close_index: int) -> int:
    """`text[close_index] == ')'`의 짝 '(' 위치."""
    depth = 0
    for index in range(close_index, -1, -1):
        char = text[index]
        if char == ")":
            depth += 1
        elif char == "(":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError(f"괄호 짝이 없다: {text!r}")


def _split_top_level(text: str) -> list[str]:
    """최상위 쉼표로 나눈다(괄호 안 쉼표는 무시)."""
    parts: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    parts.append(text[start:].strip())
    return parts


def _find_call(text: str, name: str, start: int = 0) -> int:
    """`name(` 호출의 시작 위치(식별자 일부로 붙은 것은 제외) — 없으면 -1."""
    index = text.find(name + "(", start)
    while index > 0 and (text[index - 1].isalnum() or text[index - 1] == "_"):
        index = text.find(name + "(", index + 1)
    return index


def _strip_outer_parens(text: str) -> str:
    """식 전체를 감싼 괄호 한 겹을 벗긴다(`(3*(-2)**2)` → `3*(-2)**2`)."""
    stripped = text.strip()
    while stripped.startswith("(") and _close_of(stripped, 0) == len(stripped) - 1:
        stripped = stripped[1:-1].strip()
    return stripped


def _sides(equation: str) -> tuple[str, str]:
    lhs, rhs = equation.split("=")
    return lhs.strip(), rhs.strip()


def _is_equation(condition: str) -> bool:
    """등식 1개(`<`·`>`·`!`가 없는 `=` 하나) — 부등식·`!=` 보호 조건은 아니다."""
    return condition.count("=") == 1 and _INEQUALITY_SPLIT.search(condition) is None


def _parse(text: str) -> sympy.Expr:
    """생성기 자신의 식 문자열 파싱 — CAS 파싱 단일 안전 진입점(`l3.safe_parse`)을 거친다.

    입력은 생성기가 만든 신뢰 문자열이지만 코딩 헌법 R22-03(진입점 밖 직접 파싱 금지 —
    `tests/infra/test_cas_parse_entrypoint_governance.py`)을 그대로 따른다. 거부는
    `UnsafeExpressionError`(→ `ValueError`)라 전략 실패로 정직하게 집계된다.
    """
    value = safe_sympify(text)
    if not isinstance(value, sympy.Basic):
        raise ValueError(f"식이 아니다: {text!r}")
    return cast(sympy.Expr, value)


def _fmt(value: sympy.Expr) -> str:
    return str(sympy.sstr(value))


def _replace_symbol(pattern: re.Pattern[str], text: str, replacement: str) -> str:
    """정규식 치환 — 치환 문자열을 그대로 넣는다(역참조·이스케이프 해석 없음)."""
    return pattern.sub(lambda _match: replacement, text)


def _derivative_text(expr: sympy.Expr) -> str:
    """도함수 전개형 표기 — 지수에 문자가 있으면(x^n) `n*x**(n - 1)`로 모은다."""
    return _fmt(sympy.powsimp(sympy.expand(sympy.powsimp(expr))))


# ──────────────────────────────────────────────────────────────────────────
# 단계 변환 — 도함수 전개 · 점 대입
# ──────────────────────────────────────────────────────────────────────────
def expand_derivatives(text: str) -> str:
    """최상위 `Derivative(...)` 호출을 도함수 전개형 `(G)`로 바꾸고 `.doit()`을 지운다.

    `Derivative(x**3, x).doit().subs(x, 2)` → `(3*x**2).subs(x, 2)`,
    `(f + Derivative(f, x)*(t - x)).doit().subs(x, a)` → `(f + (f')*(t - x)).subs(x, a)`.
    중첩 `Derivative(f + Derivative(f, t), t)`는 바깥 호출 하나를 통째로 계산한다(f' + f'').
    도함수가 사라지면 `.doit()`은 아무 일도 하지 않으므로 지워도 값이 같다.
    """
    pieces: list[str] = []
    cursor = 0
    while True:
        start = _find_call(text, _DERIVATIVE, cursor)
        if start < 0:
            pieces.append(text[cursor:])
            break
        close = _close_of(text, start + len(_DERIVATIVE))
        derivative = _parse(text[start : close + 1]).doit()
        pieces.append(text[cursor:start])
        pieces.append(f"({_derivative_text(derivative)})")
        cursor = close + 1
    return "".join(pieces).replace(_DOIT, "")


def apply_subs(text: str) -> str:
    """`(본문).subs(v, 값)`을 본문 안의 v를 `(값)`으로 바꾼 `(본문')`으로 푼다(계산은 하지 않는다).

    `(3*x**2).subs(x, -2)` → `(3*(-2)**2)` — 학생 풀이의 '대입' 단계 그대로다. 왼쪽부터 풀어
    `((G).subs(x, 2)).subs(a, 3)` 같은 겹친 대입도 안쪽부터 처리한다.
    """
    result = text
    while True:
        marker = result.find(_SUBS)
        if marker < 0:
            return result
        body_open = _open_of(result, marker)
        args_open = marker + len(_SUBS) - 1
        args_close = _close_of(result, args_open)
        variable, value = _split_top_level(result[args_open + 1 : args_close])
        bare = _strip_outer_parens(value)
        body = result[body_open + 1 : marker]
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(variable)}(?![A-Za-z0-9_])")
        replaced = _replace_symbol(pattern, body, f"({bare})")
        result = result[:body_open] + "(" + replaced + ")" + result[args_close + 1 :]


def _derivative_variables(text: str) -> set[str]:
    """출발식에 든 `Derivative(f, v)`들의 미분 변수 v."""
    found: set[str] = set()
    cursor = 0
    while True:
        start = _find_call(text, _DERIVATIVE, cursor)
        if start < 0:
            return found
        close = _close_of(text, start + len(_DERIVATIVE))
        args = _split_top_level(text[start + len(_DERIVATIVE) + 1 : close])
        if len(args) >= 2:
            found.add(args[1])
        found |= _derivative_variables(args[0])
        cursor = close + 1


_PLAIN_NATURAL: Final = re.compile(r"\d+")


def _substitute_symbol(text: str, symbol: str, value: str) -> str:
    """식 안의 기호를 값으로 바꾼다.

    음수·분수는 괄호로 감싼다(`2*a` → `2*(-3)`, `x**n` → `x**2`).
    """
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])")
    shown = value if _PLAIN_NATURAL.fullmatch(value) else f"({value})"
    return _replace_symbol(pattern, text, shown)


def _mentions(text: str, symbol: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


# ──────────────────────────────────────────────────────────────────────────
# 출발식 도출
# ──────────────────────────────────────────────────────────────────────────
def _conditions_list(conditions: str | Sequence[str]) -> list[str]:
    return [conditions] if isinstance(conditions, str) else [str(c) for c in conditions]


def _is_boundary_setup(conditions: str | Sequence[str]) -> bool:
    """조건에 도함수가 든 등식은 없고 도함수 부호 조건만 있는가 — 출발식이 경계점 방정식인 경우.

    그 연쇄의 근은 증감 구간의 *끝점*이고 정답(구간 안의 정수)은 근이 아니다 — 정답 도달 검사 대상이
    아니다.
    """
    items = _conditions_list(conditions)
    equations = [c for c in items if _is_equation(c)]
    if any(_DERIVATIVE in e for e in equations):
        return False
    return any(_DERIVATIVE in c and not _is_equation(c) for c in items)


def derive_setup(conditions: str | Sequence[str], answer_kind: str | None) -> str:
    """검산 조건에서 풀이의 출발식(등식 1개)을 고른다.

    ① 도함수가 든 등식 → 그것. ② 도함수 부호 조건만 있으면(`Derivative(...).doit() < 0`) 경계점
    방정식 `Derivative(...).doit() = 0`. ③ 실근 개수 문항이고 조건이 3차 이상 다항식이면 그
    함수의 임계점 방정식 `Derivative(h, v).doit() = 0`(h = 좌변 - 우변 · 우변이 상수면 좌변).
    ④ 그 밖에는 첫 등식(도함수 없음 — 생성기가 `solution_setup`을 달지 않은 경우뿐이다).
    """
    items = _conditions_list(conditions)
    equations = [c for c in items if _is_equation(c)]
    for equation in equations:
        if _DERIVATIVE in equation:
            return equation
    for condition in items:
        if _DERIVATIVE in condition and not _is_equation(condition):
            side = next(s for s in _INEQUALITY_SPLIT.split(condition) if _DERIVATIVE in s)
            return f"{side.strip()} = 0"
    if not equations:
        raise ValueError(f"출발식으로 쓸 등식이 없다: {items!r}")
    first = equations[0]
    if answer_kind == "real_root_count":
        lhs, rhs = _sides(first)
        h_expr = _parse(lhs) - _parse(rhs)
        symbols = sorted(h_expr.free_symbols, key=str)
        if len(symbols) == 1 and sympy.degree(h_expr, symbols[0]) >= 3:
            rhs_value = _parse(rhs)
            h_text = lhs if not rhs_value.free_symbols else f"{lhs} - ({rhs})"
            return f"{_DERIVATIVE}({h_text}, {symbols[0]}).doit() = 0"
    return first


# ──────────────────────────────────────────────────────────────────────────
# 전략 A · B · C
# ──────────────────────────────────────────────────────────────────────────
def _dedupe(steps: Sequence[str]) -> tuple[str, ...]:
    out: list[str] = []
    for step in steps:
        if not out or out[-1] != step:
            out.append(step)
    return tuple(out)


def _equation_text(lhs: str, rhs: str) -> str:
    return f"{_strip_outer_parens(lhs)} = {_strip_outer_parens(rhs)}"


def _reduce_parameters(setup: str, answer_map: Mapping[str, str]) -> str | None:
    """미지수가 2개 이상이면 미분 변수 하나만 남기고 나머지(상수 a·b·k 등)에 정답 값을 넣는다.

    연립 문항(상수를 먼저 구하고 임계점을 찾는 극값 문항)의 '임계점' 단계 — 해설의 'a = -3을 대입한
    f'(x) = 0의 근' — 이다. 남길 변수가 없거나 정답 값이 없으면 None.
    """
    lhs, rhs = _sides(setup)
    unknowns = {str(s) for s in (_parse(lhs).doit() - _parse(rhs).doit()).free_symbols}
    if len(unknowns) <= 1:
        return setup
    keep = unknowns & _derivative_variables(setup)
    if len(keep) != 1:
        return None
    reduced = setup
    for symbol in sorted(unknowns - keep):
        if symbol not in answer_map:
            return None
        reduced = _substitute_symbol(reduced, symbol, answer_map[symbol])
    return reduced


def _solve_tail(lhs_text: str, rhs_text: str) -> list[str] | None:
    """대입까지 끝난 등식 → 정리·인수분해·`u = 값`/근 목록. 미지수 1개·다항식·유한 실근만."""
    lhs, rhs = _parse(lhs_text), _parse(rhs_text)
    unknowns = (lhs - rhs).free_symbols
    if len(unknowns) != 1:
        return None
    (unknown,) = unknowns
    for bare, other in ((lhs, rhs), (rhs, lhs)):
        if bare == unknown and unknown not in other.free_symbols:
            value = sympy.nsimplify(sympy.simplify(other))
            return [f"{unknown} = {_fmt(value)}"]
    difference = sympy.expand(lhs - rhs)
    if not difference.is_polynomial(unknown):
        return None
    if sympy.Poly(difference, unknown).LC().is_negative:
        difference = sympy.expand(-difference)
    tail = [f"{_fmt(difference)} = 0"]
    factored = sympy.factor(difference)
    nontrivial = isinstance(factored, sympy.Pow) and unknown in factored.free_symbols
    if isinstance(factored, sympy.Mul):
        nontrivial = sum(1 for f in factored.args if unknown in f.free_symbols) >= 2 or any(
            isinstance(f, sympy.Pow) and unknown in f.free_symbols for f in factored.args
        )
    if nontrivial and _fmt(factored) != _fmt(difference):
        tail.append(f"{_fmt(factored)} = 0")
    solutions = sympy.solveset(difference, unknown, sympy.S.Reals)
    if not isinstance(solutions, sympy.FiniteSet) or not solutions:
        return None
    ordered = sorted(solutions, key=lambda v: float(v))
    tail.append(", ".join(f"{unknown} = {_fmt(v)}" for v in ordered))
    return tail


def _strategy_a(setup: str, answer_map: Mapping[str, str]) -> tuple[str, ...] | None:
    reduced = _reduce_parameters(setup, answer_map)
    if reduced is None:
        return None
    lhs, rhs = _sides(reduced)
    steps = [reduced]
    if _DERIVATIVE in reduced:
        lhs, rhs = expand_derivatives(lhs), expand_derivatives(rhs)
        steps.append(_equation_text(lhs, rhs))
    if _SUBS in lhs or _SUBS in rhs:
        lhs, rhs = apply_subs(lhs), apply_subs(rhs)
        steps.append(_equation_text(lhs, rhs))
    tail = _solve_tail(lhs, rhs)
    if tail is None:
        return None
    return _dedupe([*steps, *tail])


def _side_chain(side: str) -> list[str]:
    """정답이 들어간 한 변 → 도함수 전개 → 대입 → 값(전부 상수 식)."""
    chain = [_strip_outer_parens(side)]
    text = side
    if _DERIVATIVE in text:
        text = expand_derivatives(text)
        chain.append(_strip_outer_parens(text))
    if _SUBS in text:
        text = apply_subs(text)
        chain.append(_strip_outer_parens(text))
    value = sympy.nsimplify(sympy.simplify(_parse(side).doit()))
    if value.free_symbols:
        raise ValueError(f"정답을 넣어도 값이 정해지지 않는다: {side!r}")
    chain.append(_fmt(value))
    return chain


def _strategy_b(setup: str, answer_map: Mapping[str, str]) -> tuple[str, ...] | None:
    lhs, rhs = _sides(setup)
    unknowns = {str(s) for s in (_parse(lhs).doit() - _parse(rhs).doit()).free_symbols}
    if not unknowns or not unknowns <= set(answer_map):
        return None
    bound = _derivative_variables(setup)
    filled: list[str] = []
    for side in (lhs, rhs):
        text = side
        for symbol in sorted(unknowns):
            value = answer_map[symbol]
            if symbol not in bound:
                text = _substitute_symbol(text, symbol, value)
            elif _mentions(text, symbol):
                # 미분 변수 자체가 미지수(임계점 x)면 Derivative 안에서 바꿀 수 없다 — 변 전체에
                # 대입한다. 변이 `Derivative(...).doit()` 하나뿐이면 괄호 없이 `.subs`를 잇는다.
                start = _find_call(text, _DERIVATIVE)
                whole_call = (
                    start == 0
                    and text.endswith(_DOIT)
                    and _close_of(text, len(_DERIVATIVE)) == len(text) - len(_DOIT) - 1
                )
                text = (
                    f"{text}.subs({symbol}, {value})"
                    if whole_call
                    else f"({text}).subs({symbol}, {value})"
                )
        filled.append(text)
    derivative_first = sorted(filled, key=lambda s: _DERIVATIVE not in s)
    first, second = (_side_chain(s) for s in derivative_first)
    return _dedupe([*first, *reversed(second)])


def _strategy_c(setup: str, answer_map: Mapping[str, str]) -> tuple[str, ...] | None:
    start = _find_call(setup, _DERIVATIVE)
    if start < 0:
        return None
    reduced = _reduce_parameters(setup, answer_map) or setup
    start = _find_call(reduced, _DERIVATIVE)
    close = _close_of(reduced, start + len(_DERIVATIVE))
    call = reduced[start : close + 1]
    derivative = _parse(call).doit()
    expanded = _derivative_text(derivative)
    factored = _fmt(sympy.factor(sympy.expand(derivative)))
    # `.doit()`을 붙여 둔다 — 맨 `Derivative(...)`는 검증기가 미계산 도함수를 simplify로 풀어야 해
    # 느리다(관측 예산 0.2초 초과 실측). 다른 전략의 출발식과 같은 표기이기도 하다.
    return _dedupe([f"{call}{_DOIT}", expanded, factored])


_Strategy = Callable[[str, Mapping[str, str]], tuple[str, ...] | None]
#: 기본 순서 — 방정식 연쇄 → 정답 대입 검산 → 도함수 식.
_DEFAULT_ORDER: Final[tuple[tuple[str, _Strategy], ...]] = (
    ("A", _strategy_a),
    ("B", _strategy_b),
    ("C", _strategy_c),
)
#: 임계점 방정식(`f'(x) = 0` 꼴 · 미지수 = 미분 변수)이 판정 불가일 때(허근 인수) — 해설은 도함수를
#: 인수분해해 실근 하나를 읽으므로 도함수 식 연쇄(C)가 정답 대입 검산(B)보다 풀이에 가깝다.
_CRITICAL_ORDER: Final[tuple[tuple[str, _Strategy], ...]] = (
    ("A", _strategy_a),
    ("C", _strategy_c),
    ("B", _strategy_b),
)


def _solves_for_derivative_variable(setup: str, answer_map: Mapping[str, str]) -> bool:
    """출발식(상수 대입 후)의 미지수가 미분 변수 자신인가 — 임계점 방정식 판별."""
    reduced = _reduce_parameters(setup, answer_map)
    if reduced is None:
        return False
    lhs, rhs = _sides(reduced)
    unknowns = {str(s) for s in (_parse(lhs).doit() - _parse(rhs).doit()).free_symbols}
    return len(unknowns) == 1 and unknowns <= _derivative_variables(reduced)


def _all_correct(steps: Sequence[str]) -> bool:
    result = verify_solution(list(steps))
    return result.n_transitions >= 1 and result.n_correct == result.n_transitions


_NAME: Final = re.compile(r"[A-Za-z]\w*")


def final_solution_values(step: str) -> tuple[str, tuple[sympy.Expr, ...]] | None:
    """마지막 단계가 `u = 값`·근 목록(`u = r1, u = r2`)이면 (u, 값들), 아니면 None."""
    variable: str | None = None
    values: list[sympy.Expr] = []
    for part in _split_top_level(step):
        if part.count("=") != 1:
            return None
        lhs, rhs = (s.strip() for s in part.split("="))
        if not _NAME.fullmatch(lhs) or (variable is not None and lhs != variable):
            return None
        variable = lhs
        values.append(_parse(rhs))
    return (variable, tuple(values)) if variable is not None else None


class _AnswerNotReachedError(Exception):
    """정답 미도달 — 전략 실패(ValueError)와 구별해 다음 전략으로 흘려보내지 않는다."""


def _check_answer_reached(steps: Sequence[str], answer_map: Mapping[str, str]) -> None:
    """근 목록(`u = ...`)으로 끝난 연쇄에 정답 u가 들어 있는지 — 빠지면 ValueError(다음 전략으로
    넘기지 않는다: 정답이 틀렸거나 출발식이 문항과 다른 것이다)."""
    reached = final_solution_values(steps[-1])
    if reached is None or reached[0] not in answer_map:
        return
    variable, values = reached
    answer = _parse(answer_map[variable])
    if not any(sympy.simplify(value - answer) == 0 for value in values):
        raise _AnswerNotReachedError(
            f"풀이 단계의 마지막 근 목록에 정답 {variable} = {answer_map[variable]}이 없다: "
            f"{steps[-1]!r}"
        )


def solution_steps(
    *,
    conditions: str | Sequence[str],
    answer_map: Mapping[str, str],
    answer_kind: str | None = None,
    setup: str | None = None,
) -> StepChain:
    """문항 1건의 풀이 단계 연쇄 — 전략 A → B → C 중 처음으로 전이 전건 correct인 것.

    `setup`이 있으면(생성기가 단 출발식) 그것을, 없으면 `derive_setup`이 고른 등식을 출발식으로
    쓴다. 어느 전략도 전건 correct를 못 내면 **ValueError**(fail-loud — 검증 안 된 단계를 은행에
    싣지 않는다).
    """
    start = setup if setup is not None else derive_setup(conditions, answer_kind)
    check_answer = setup is not None or not _is_boundary_setup(conditions)
    order = (
        _CRITICAL_ORDER if _solves_for_derivative_variable(start, answer_map) else _DEFAULT_ORDER
    )
    attempts: list[str] = []
    for name, strategy in order:
        try:
            steps = strategy(start, answer_map)
        except (ValueError, TypeError, sympy.SympifyError, NotImplementedError) as exc:
            attempts.append(f"{name}: {type(exc).__name__}")
            continue
        if steps is None or len(steps) < 2:
            attempts.append(f"{name}: 형태 불가")
            continue
        if _all_correct(steps):
            if check_answer:
                try:
                    _check_answer_reached(steps, answer_map)
                except _AnswerNotReachedError as exc:
                    raise ValueError(str(exc)) from None
            return StepChain(steps=steps, strategy=name)
        attempts.append(f"{name}: 전이 판정 불가/불일치 {list(steps)!r}")
    raise ValueError(f"풀이 단계를 만들 수 없다 — 출발식 {start!r}: " + " / ".join(attempts))
