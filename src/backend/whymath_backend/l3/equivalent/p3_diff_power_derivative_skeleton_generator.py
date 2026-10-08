"""[12미적Ⅰ-02-03] 함수 y=x^n의 도함수 결정론 문항 생성기 — P3-03(결정론·LLM 0).

개념: `H:12미적Ⅰ02-03`(`math.calculus.hamsu-y-x-nui-dohamsu`). 핵심 오개념: M0671 ←
kebab `power-rule-step-omitted`(지수를 앞으로 내리는 일과 1 줄이는 일 중 하나를 빠뜨린다 —
크로스링크 직접매핑 승인분). 신규 오개념 id를 만들지 않는다.

범위(이 개념에 한정)
--------------------
`x^n`(n은 양의 정수)의 도함수·미분계수만 다룬다. 상수함수 문항(`f(x) = 3`의 `f'(2)`)은 소영역
`함수 y=xⁿ의 도함수`가 묻지 않는 선수 지식이라 뺐다(감사 bad_tag 교정 — PRIMARY 태그를 선수
진단 문항에 두지 않는다). **실수배·합·곱의 미분법은 다루지
않는다** — 그것은 `[12미적Ⅰ-02-04]`의 몫이다("김에 같이" 금지). 그래서 계수가 붙은 `cx^n`
문항은 이 파일에 없다(오개념 유발 슬롯의 *구하는 미지수*도 `x^n`의 지수·위치에 한정).

슬롯 6종 × 틀(frame) 구성
------------------------
대표(식 답)·기본(값)·응용(미지수 구하기 — 스킬 연결 유형)·오개념 유발(객관식 — kebab 연결)·진단·
숙련도 확인. 틀은 문면이 구조적으로 다른 서로 다른 발문 형태이며(개념당 고유 문면 골격 30 이상이
목표), 파라미터(n·a·b)만 다른 문항은 같은 골격을 공유한다.

문제유형 정직성
--------------
이 개념의 명세 스킬(`equation-rearrangement`·`pattern-generalization`)과 겹치는 필수 유형은
`ptype.solve-for-unknown` 하나뿐이다. 값 계산·식 도출 문항은 `ptype.evaluate-expression`으로
정직하게 달며(스킬 연결로 세어지지 않는다), 스킬 연결 문항은 *미지수를 실제로 구하는* 응용·진단·
숙련도·오개념 유발(solve형) 틀에서 나온다.

검산 재료의 형식 제약(중요)
--------------------------
Tier1(`l3/verify_answer`)은 미분 평가(`Derivative(...).doit().subs(...)`)가 든 변을 **다른 연산과
섞지 못한다**(`D + 108 = y`·`2*D = y`·`D1 + D2 = y` 모두 unverifiable — 2026-10-06 실측). 그리고
섀도 채점 경로(`attempt_grading_shadow_report`)는 검산 조건의 자유기호가 **정확히 하나이고
answer_map의 유일한 키와 같을 것**을 요구한다(NLP-09 · 코퍼스 0건 동결).
그래서 이 파일의 모든 문항은

  · 미분 평가를 조건당 1회·맨몸으로 쓰고(여러 값의 합·차는 `Derivative(F + G, x)`처럼
    *합쳐 한 번에* 미분),
  · 미지수를 정확히 1개만 둔다(보조 변수 `p`·`q`·`y = p + q` 형태 금지).

**함수식을 답으로 하는 문항은 만들지 않는다**(`y = 도함수` 형태의 검산 조건은 자유기호가 x와 y
둘이라 위 계약 밖이다 — 현 코퍼스 13,520블록이 전부 스칼라 답이다). 도함수의 계수·차수·값은
*x = 2에서의 평가*를 한 번 거쳐 스칼라 미지수 1개로 묻는다(`c·2^m` 형태 — 단항 c·x^m은
한 점의 값이 (다른 하나를 알 때) c와 m을 유일하게 정한다).

두 번째 미지수가 필요한 문항(예: n을 찾은 뒤 f'(3))은 첫 미지수를 *생성기가 SymPy로 푼 값*으로
조건식에 미리 대입하고(`_unique_exponent`가 유일해를 확인), Tier1은 마지막 답만 검산한다.

정답: 모든 문항의 정답은 `sympy.diff`로 계산한다(`p3_diff_expr.derivative_of`). 객관식 오답 선지는
정답식과 별개로 *오개념이 만드는 식*(계수 누락 x^(n-1)·지수 감소 누락 n·x^n)을 직접 쓰고,
오개념 연결은 그 두 종류에만 건다(그 밖의 필러 선지는 미매핑).
"""

from __future__ import annotations

from typing import ClassVar, Final

import sympy

from whymath_backend.l3.equivalent.p3_diff_expr import (
    Poly,
    derivative_of,
    eval_at,
    render_difference,
    render_poly,
    render_sum,
    render_surd,
    with_eul_reul,
    with_eun_neun,
    with_i_ga,
    with_wa_gwa,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import (
    ChoiceEntry,
    DiffItem,
    Frame,
    P3DiffSlotGenerator,
    answer_format_for,
    build_choices,
    round_robin_items,
    seeded_order,
)
from whymath_backend.lang.josa import eul_reul
from whymath_backend.schema.enums import AnswerFormat

__all__ = ["P3DiffPowerDerivativeGenerator"]

_KEBAB: Final = "power-rule-step-omitted"
_EVAL: Final = "ptype.evaluate-expression"
_SOLVE: Final = "ptype.solve-for-unknown"

_X = sympy.Symbol("x")


def _mono(n: int, var: str = "x") -> Poly:
    return ((n, 1),)


def _dval(n: int, point: int) -> int:
    """x^n의 도함수의 x = point에서의 값(SymPy 평가) — 해설의 산술 과정 표기용."""
    return eval_at(derivative_of(_mono(n)), point)


def _unique_exponent(point: int, value: int) -> int:
    """f(x) = x^n에서 f'(point) = value인 자연수 n(2..20)이 **유일**함을 SymPy 평가로 확인한다."""
    found = [n for n in range(2, 21) if eval_at(derivative_of(_mono(n)), point) == value]
    if len(found) != 1:
        raise ValueError(f"유일한 n이 아니다: point={point} value={value} → {found}")
    return found[0]


def _deriv_sym(expr_str: str, point: str) -> str:
    """`Derivative(식, x).doit().subs(x, 점)` — 미분 평가 1회(맨몸) 표기."""
    return f"Derivative({expr_str}, x).doit().subs(x, {point})"


def _fmt(value: object) -> AnswerFormat:
    """정답 형식 — 기반의 단일 규칙(`answer_format_for`)을 따른다(틀마다 손으로 박지 않는다)."""
    return answer_format_for(str(value))


def _deriv_form_item(
    *,
    slot: str,
    frame_id: str,
    text: str,
    n: int,
    ask: str,
    var: str = "x",
) -> DiffItem:
    """x^n의 도함수 c·x^m 꼴에서 c + m(`ask='sum'`) 또는 c와 m의 곱(`ask='product'`)을 묻는 문항.

    정답은 SymPy로 구한 도함수의 항(`derivative_of`)에서 읽고, 검산 조건은 x = 2에서의 평가
    (`c·2^m`)로 미지수 1개만 남긴다 — 묻는 값 s(= c + m)·p(= c·m)와 SymPy로 구한 지수 m으로 c를
    (s - m)·(p/m)로 쓴다. 단항식 c·x^m은 한 점의 값이 (m을 알 때) c를 유일하게 정한다.
    """
    d = derivative_of(_mono(n), var)
    ((m_exp, c_coef),) = d
    expr = f"Derivative({var}**{n}, {var}).doit().subs({var}, 2)"
    # 7회차 감사(2026-10-08) 처분 — c만 묻으면 지수를 줄이지 않는 오개념(n·x^n)도 c = n을, m만
    # 묻으면 계수를 내리지 않는 오개념(x^(n - 1))도 m = n - 1을 맞힌다(판정자 지적 76a9f5ac · 판정기
    # T-power-path-coincidence). 두 단계가 모두 맞아야 나오는 c + m · c와 m의 곱을 묻는다(오답
    # 경로는 각각 n · 2n, n - 1 · n^2). 미지수는 하나만 두므로 생성기가 SymPy로 구한 지수 m을 조건에
    # 대입한다.
    if ask == "sum":
        symbol, value = "s", c_coef + m_exp
        condition = f"{expr} = (s - {m_exp})*2**{m_exp}"
        tail = f"c = {c_coef}, m = {m_exp}이고 c + m = {value}이다."
    elif ask == "product":
        symbol, value = "p", c_coef * m_exp
        condition = f"{expr} = (p/{m_exp})*2**{m_exp}"
        tail = f"c = {c_coef}, m = {m_exp}이고 c와 m의 곱은 {value}이다."
    else:  # pragma: no cover — 호출 오류
        raise ValueError(f"알 수 없는 질문: {ask}")
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=str(value),
        explanation=(
            f"거듭제곱의 미분법에 따라 지수 {with_eul_reul(n)} 앞으로 내리고 지수를 1 줄이면 "
            f"{render_poly(_mono(n), var)}의 도함수는 {render_poly(d, var)}이므로 {tail}"
        ),
        conditions=condition,
        answer_map=((symbol, str(value)),),
        problem_type_code=_EVAL,
        answer_format=_fmt(value),
    )


def _value_item(
    *,
    slot: str,
    frame_id: str,
    text: str,
    n: int,
    point: int,
    ptype: str = _EVAL,
) -> DiffItem:
    f = _mono(n)
    value = eval_at(derivative_of(f), point)
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=str(value),
        explanation=(
            f"거듭제곱의 미분법에 따라 x^{n}의 도함수는 {render_poly(derivative_of(f))}이므로 "
            f"x가 {point}일 때의 값은 {value}이다."
        ),
        conditions=f"Derivative(x**{n}, x).doit().subs(x, {point}) = y",
        answer_map=(("y", str(value)),),
        problem_type_code=ptype,
        answer_format=_fmt(value),
    )


# ──────────────────────────────────────────────────────────────────────────
# 대표(representative) — x^n의 도함수를 식으로 구한다
# ──────────────────────────────────────────────────────────────────────────
_N_RANGE: Final = tuple(range(2, 10))


def _rep_frames() -> list[Frame]:
    def make(frame_id: str, template: str, ask: str, var: str = "x") -> Frame:
        def build(p: tuple[object, ...]) -> DiffItem | None:
            n = int(str(p[0]))
            return _deriv_form_item(
                slot="representative",
                frame_id=frame_id,
                text=template.format(n=n, eul=eul_reul(f"{var}^{n}")),
                n=n,
                ask=ask,
                var=var,
            )

        params = tuple((n,) for n in seeded_order(f"p3-power:{frame_id}", _N_RANGE))
        return Frame(frame_id, params, build)

    # 7회차 감사 처분 — c만·m만 묻던 다섯 틀을 c + m · c와 m의 곱으로 바꿨다(`_deriv_form_item`
    # 참조).
    return [
        make(
            "rep-coefficient-plus-exponent",
            "함수 f(x) = x^{n}의 도함수 f'(x)를 cx^m (c, m은 상수) 꼴로 나타낼 때, c + m의 값을 "
            "구하시오.",
            "sum",
        ),
        make(
            "rep-coefficient-times-exponent",
            "함수 f(x) = x^{n}의 도함수 f'(x)를 cx^m (c, m은 상수) 꼴로 나타낼 때, c와 m의 곱을 "
            "구하시오.",
            "product",
        ),
        make(
            "rep-coefficient-plus-exponent-in-t",
            "함수 g(t) = t^{n}{eul} t에 대하여 미분한 도함수를 ct^m (c, m은 상수) 꼴로 "
            "나타낼 때, c + m의 값을 구하시오.",
            "sum",
            var="t",
        ),
        make(
            "rep-curve-coefficient-times-exponent",
            # '곡선의 도함수'는 대상 혼동이다(도함수는 함수가 갖는다 — 2차 감사 결함).
            "함수 y = x^{n}의 도함수를 y' = cx^m (c, m은 상수) 꼴로 나타낼 때, c와 m의 곱을 "
            "구하시오.",
            "product",
        ),
        make(
            "rep-derivative-coefficient-plus-exponent",
            # 'c + m'의 m이 발문에서 상수로 선언돼야 한다(2차 감사 미선언 상수 부류 —
            # `p3_diff_text_scanner`의 undeclared_constant).
            "함수 f(x) = x^{n}{eul} x에 대하여 미분했을 때 도함수의 계수 c와 지수 m의 합 c + m을 "
            "구하시오. (도함수는 cx^m 꼴이고, c, m은 상수이다.)",
            "sum",
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 기본(basic) — 미분계수(도함수의 값)
# ──────────────────────────────────────────────────────────────────────────
_POINTS: Final = (-3, -2, -1, 1, 2, 3, 4)
_N_VALUE_RANGE: Final = tuple(range(2, 8))


def _grid(seed: str, *axes: tuple[int, ...]) -> tuple[tuple[object, ...], ...]:
    combos: list[tuple[object, ...]] = [()]
    for axis in axes:
        combos = [(*c, v) for c in combos for v in axis]
    return tuple(seeded_order(seed, combos))


def _basic_frames() -> list[Frame]:
    def b1(p: tuple[object, ...]) -> DiffItem | None:
        n, a = int(str(p[0])), int(str(p[1]))
        return _value_item(
            slot="basic",
            frame_id="basic-value-of-derivative",
            text=f"함수 f(x) = x^{n}에 대하여 f'({a})의 값을 구하시오.",
            n=n,
            point=a,
        )

    def b2(p: tuple[object, ...]) -> DiffItem | None:
        n, a = int(str(p[0])), int(str(p[1]))
        return _value_item(
            slot="basic",
            frame_id="basic-differential-coefficient",
            text=f"f(x) = x^{n}일 때, 미분계수 f'({a}){eul_reul(str(a))} 구하시오.",
            n=n,
            point=a,
        )

    def b3(p: tuple[object, ...]) -> DiffItem | None:
        n, a = int(str(p[0])), int(str(p[1]))
        return _value_item(
            slot="basic",
            frame_id="basic-coefficient-at-point",
            text=f"함수 y = x^{n}의 x = {a}에서의 미분계수를 구하시오.",
            n=n,
            point=a,
        )

    def b4(p: tuple[object, ...]) -> DiffItem | None:
        n, m, a = (int(str(v)) for v in p)
        if n == m:
            return None
        total = eval_at(derivative_of(_mono(n)), a) + eval_at(derivative_of(_mono(m)), a)
        return DiffItem(
            slot="basic",
            frame_id="basic-sum-of-two-values",
            question_text=(f"f(x) = x^{n}, g(x) = x^{m}일 때, f'({a}) + g'({a})의 값을 구하시오."),
            answer_text=str(total),
            explanation=(
                f"f'(x) = {render_poly(derivative_of(_mono(n)))}이고 "
                f"g'(x) = {render_poly(derivative_of(_mono(m)))}이므로 "
                f"f'({a}) + g'({a})의 값은 "
                f"{render_sum(_dval(n, a), _dval(m, a))}"
                f" = {total}이다."
            ),
            # 두 미분 평가를 합치지 못하는 Tier1 제약 — 합의 미분으로 *한 번에* 검산한다.
            conditions=_deriv_sym(f"x**{n} + x**{m}", str(a)) + " = y",
            answer_map=(("y", str(total)),),
            problem_type_code=_EVAL,
            answer_format=_fmt(total),
            # 풀이 단계는 해설처럼 f'·g'를 따로 미분한다(검산 조건은 합의 미분 한 번).
            solution_setup=(
                f"(Derivative(x**{n}, x) + Derivative(x**{m}, x)).doit().subs(x, {a}) = y"
            ),
        )

    def b5(p: tuple[object, ...]) -> DiffItem | None:
        n, m, a = (int(str(v)) for v in p)
        if n == m:
            return None
        diff = eval_at(derivative_of(_mono(n)), a) - eval_at(derivative_of(_mono(m)), a)
        return DiffItem(
            slot="basic",
            frame_id="basic-difference-of-two-values",
            question_text=(
                f"함수 f(x) = x^{n}, g(x) = x^{m}에 대하여 f'({a}) - g'({a})의 값을 구하시오."
            ),
            answer_text=str(diff),
            # 프라임 기호 뒤에 조사를 붙이지 않는다('g'를' — 독법에 따라 '를/을'이 갈린다).
            explanation=(
                f"f'(x) = {render_poly(derivative_of(_mono(n)))}이고 "
                f"g'(x) = {render_poly(derivative_of(_mono(m)))}이므로 "
                f"f'({a}) - g'({a})의 값은 "
                f"{render_difference(_dval(n, a), _dval(m, a))}"
                f" = {diff}이다."
            ),
            conditions=_deriv_sym(f"x**{n} - x**{m}", str(a)) + " = y",
            # 풀이 단계는 해설처럼 f'·g'를 따로 미분한다(검산 조건은 차의 미분 한 번).
            solution_setup=(
                f"(Derivative(x**{n}, x) - Derivative(x**{m}, x)).doit().subs(x, {a}) = y"
            ),
            answer_map=(("y", str(diff)),),
            problem_type_code=_EVAL,
            answer_format=_fmt(diff),
        )

    def b7(p: tuple[object, ...]) -> DiffItem | None:
        n, a = int(str(p[0])), int(str(p[1]))
        return _value_item(
            slot="basic",
            frame_id="basic-substitute-into-derivative",
            text=f"함수 f(x) = x^{n}의 도함수 f'(x)에 x = {with_eul_reul(a)} 대입한 값을 구하시오.",
            n=n,
            point=a,
        )

    return [
        Frame("basic-value-of-derivative", _grid("p3-power:b1", _N_VALUE_RANGE, _POINTS), b1),
        Frame("basic-differential-coefficient", _grid("p3-power:b2", _N_VALUE_RANGE, _POINTS), b2),
        Frame("basic-coefficient-at-point", _grid("p3-power:b3", _N_VALUE_RANGE, _POINTS), b3),
        # 7회차 감사 — x = 1은 지수를 줄이지 않는 오개념(n·x^n)도 같은 값이라 매개변수 거부
        # 조건(T-power-path-coincidence)이 건너뛴다. 그 자리를 x = 4(값이 1000을 넘는다) 대신 음수인
        # 점으로 채운다.
        Frame(
            "basic-sum-of-two-values",
            _grid("p3-power:b4", (2, 3, 4), (3, 4, 5), (-1, 2, -2, 3)),
            b4,
        ),
        Frame(
            "basic-difference-of-two-values",
            _grid("p3-power:b5", (2, 3, 4), (3, 4, 5), (-1, 2, -2, 3)),
            b5,
        ),
        Frame(
            "basic-substitute-into-derivative", _grid("p3-power:b7", _N_VALUE_RANGE, _POINTS), b7
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 응용(applied) — 미지수를 구한다(solve-for-unknown · 스킬 연결 유형)
# ──────────────────────────────────────────────────────────────────────────
def _deriv_value_sym(n: str, point: str) -> str:
    return f"Derivative(x**{n}, x).doit().subs(x, {point})"


def _two_power(exponent: int) -> str:
    """'2^3'·'2' — 지수 1은 쓰지 않는다(지수 1 표기 결함 부류)."""
    return "2" if exponent == 1 else f"2^{exponent}"


def _positive_point_steps(n: int, a: int, b: int) -> str:
    """'nа^(n-1) = b → a^(n-1) = b/n → a = ±r → 양수 a = r' — 세운 방정식과 근을 고르는 단계.

    5회차 감사(2026-10-08) 해설 결함 교정 — 종전 해설은 '미분계수가 27인 양수 a는 3'으로 결론만 적어
    세운 방정식(3a^2 = 27)·근 전부(a = ±3)·양수 조건으로 고르는 단계가 없었다(판정기
    E-excluded-root).
    """
    power = a ** (n - 1)
    # 'f'(a) = 2a = 8'처럼 함숫값 기호를 등식에 잇지 않는다 — 위생 게이트가 f'(a)를 곱으로
    # 읽는다(QUAL-13).
    if n - 1 == 1:
        return f"f'(a)의 값은 {n}a이므로 {n}a = {b}에서 a = {a}이고, 이 값은 양수이다."
    head = f"f'(a)의 값은 {n}a^{n - 1}이므로 {n}a^{n - 1} = {b}에서 a^{n - 1} = {power}이다. "
    if (n - 1) % 2 == 0:
        return head + f"a = {a} 또는 a = {-a}이고, a는 양수이므로 a = {a}이다."
    return head + f"이를 만족시키는 실수 a는 {a} 하나뿐이고 양수이므로 a = {a}이다."


def _applied_frames() -> list[Frame]:
    def a1(p: tuple[object, ...]) -> DiffItem | None:
        n, a = int(str(p[0])), int(str(p[1]))
        b = eval_at(derivative_of(_mono(n)), a)
        # 지수가 1이면 '3^1'로 쓰지 않는다(지수 1 표기 결함 — 2차 감사 부류).
        power = f"{a}^{n - 1} = {a ** (n - 1)}" if n - 1 >= 2 else str(a)
        f_at_a = f"f'({a})"
        return DiffItem(
            slot="applied",
            frame_id="applied-find-exponent",
            question_text=(
                f"함수 f(x) = x^n (n은 2 이상의 자연수)에 대하여 f'({a})의 값이 {b}일 때, "
                "n의 값을 구하시오."
            ),
            answer_text=str(n),
            explanation=(
                f"f'(x) = nx^(n - 1)이므로 {with_eun_neun(f_at_a)} n과 {a}^(n - 1)의 곱이다. "
                f"n = {n}일 때 {with_wa_gwa(n)} {power}의 곱이 "
                f"{with_i_ga(b)} 되므로 n은 {n}이다."
            ),
            conditions=f"{_deriv_value_sym('n', str(a))} = {b}",
            answer_map=(("n", str(n)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(n),
        )

    def a2(p: tuple[object, ...]) -> DiffItem | None:
        n, a = int(str(p[0])), int(str(p[1]))
        b = eval_at(derivative_of(_mono(n)), a)
        return DiffItem(
            slot="applied",
            frame_id="applied-find-positive-point",
            question_text=(
                f"함수 f(x) = x^{n}에 대하여 f'(a) = {with_eul_reul(b)} 만족시키는 "
                "양수 a의 값을 구하시오."
            ),
            answer_text=str(a),
            explanation=(
                f"f'(x) = {render_poly(derivative_of(_mono(n)))}이므로 "
                + _positive_point_steps(n, a, b)
            ),
            conditions=(_deriv_value_sym(str(n), "a") + f" = {b}", "a > 0"),
            answer_map=(("a", str(a)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(a),
        )

    def a3(p: tuple[object, ...]) -> DiffItem | None:
        n, a = int(str(p[0])), int(str(p[1]))
        b = eval_at(derivative_of(_mono(n)), a)
        return DiffItem(
            slot="applied",
            frame_id="applied-coefficient-given",
            question_text=(
                f"함수 y = x^{n}의 x = a에서의 미분계수가 {b}일 때, 양수 a의 값을 구하시오."
            ),
            answer_text=str(a),
            explanation=(
                f"y = x^{n}의 도함수를 f'(x)라 하면 f'(x) = {render_poly(derivative_of(_mono(n)))}"
                "이므로 x = a에서의 미분계수는 f'(a)이다. " + _positive_point_steps(n, a, b)
            ),
            conditions=(_deriv_value_sym(str(n), "a") + f" = {b}", "a > 0"),
            answer_map=(("a", str(a)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(a),
        )

    def a4(p: tuple[object, ...]) -> DiffItem | None:
        n = int(str(p[0]))
        return DiffItem(
            slot="applied",
            frame_id="applied-derivative-equals-function",
            question_text=(
                f"함수 f(x) = x^{n}에 대하여 f'(a) = f(a)를 만족시키는 0이 아닌 실수 a의 값을 "
                "구하시오."
            ),
            answer_text=str(n),
            # 5회차 감사 해설 결함 — 방정식 정리(a^(n-1)(a - n) = 0)와 a = 0 배제 단계를 보인다.
            explanation=(
                f"f'(x) = {n}x^{n - 1}이므로 f'(a)의 값은 {n}a^{n - 1}이고 f(a)의 값은 a^{n}이다. "
                f"{n}a^{n - 1} = a^{n}을 정리하면 a^{n - 1}(a - {n}) = 0이므로 a = 0 또는 "
                f"a = {n}이다. a는 0이 아니므로 a = {n}이다."
            ),
            conditions=(f"{_deriv_value_sym(str(n), 'a')} = a**{n}", "a != 0"),
            answer_map=(("a", str(n)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(n),
        )

    def a5(p: tuple[object, ...]) -> DiffItem | None:
        # 6회차 은행 감사(2026-10-08) 처분 — 구판 'f'(a) = k·f'(1)'(applied-ratio-to-f-prime-one)은
        # f(x) = x^n이면 계수 n이 양변에서 약분돼 계수 내리기를 빠뜨린 도함수(x^(n - 1))로 풀어도 늘
        # 같은 a가 나왔고, n = 2면 'f'(a)가 f'(1)의 k배이니 a도 k배'라는 비례 짐작이
        # 정답이었다(판정자 지적 c32c1d5d · 판정기 T-ratio-shortcut). 이 개념은 x^n만 다루므로 배수
        # 틀로는 고칠 매개변수가 없어 차의 꼴로 바꾼다 — f'(a) - f'(1) = m은 계수 누락(a^(n - 1) = 1
        # + m)·지수 유지 (na^n = n + m) 경로가 정답과 갈린다.
        n, a = int(str(p[0])), int(str(p[1]))
        base = eval_at(derivative_of(_mono(n)), 1)
        b = eval_at(derivative_of(_mono(n)), a)
        m = b - base
        return DiffItem(
            slot="applied",
            frame_id="applied-difference-from-f-prime-one",
            # 'f'(a) - f'(1) = 45'는 위생 게이트가 'f'(1) = 45'를 산술 등식으로 읽는다 — 말로 쓴다.
            question_text=(
                f"함수 f(x) = x^{n}에 대하여 f'(a)의 값이 f'(1)의 값보다 {m}만큼 클 때, 양수 a의 "
                "값을 구하시오."
            ),
            answer_text=str(a),
            explanation=(
                f"f'(x) = {render_poly(derivative_of(_mono(n)))}이므로 f'(1)의 값은 {base}이고, "
                f"f'(a)의 값은 {with_eul_reul(base)} {m}만큼 넘는 {b}이다. "
                + _positive_point_steps(n, a, b)
            ),
            # f'(1)의 값은 SymPy로 구해(`eval_at`) 조건식에 상수로 대입한다(미지수 1개 제약 — 미분
            # 평가가 든 변을 다른 연산과 섞지 못한다). 같은 (n, a)의 'f'(a) = b' 틀과 조건이 같으면
            # 라운드로빈의 실체 중복 제거가 건너뛴다(QUAL-07).
            conditions=(f"{_deriv_value_sym(str(n), 'a')} = {b}", "a > 0"),
            answer_map=(("a", str(a)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(a),
        )

    def a6(p: tuple[object, ...]) -> DiffItem | None:
        # 7회차 감사(2026-10-08) 처분 — 종전 '도함수가 f'(x) = 8x^7일 때 n'은 계수를 내리지 않는
        # 오개념(x^(n - 1))이 지수 비교로, 지수를 줄이지 않는 오개념(n·x^n)이 계수 비교로 n = 8을 늘
        # 맞혔다(판정기 T-power-path-coincidence의 주어진 도함수 꼴 절 — 76a9f5ac와 같은 원리).
        # 도함수의 지수만 주고 계수 k를 묻는다: 지수 n - 1 = 7에서 n = 8을 정한 뒤 계수 k = n = 8을
        # 읽어야 한다 (계수 누락이면 k = 1, 지수 유지면 n = 7·k = 7). n은 생성기가 정하고 조건에
        # 대입한다(미지수 k 하나).
        n = int(str(p[0]))
        return DiffItem(
            slot="applied",
            frame_id="applied-coefficient-from-derivative-exponent",
            question_text=(
                f"함수 f(x) = x^n (n은 2 이상의 자연수)의 도함수가 f'(x) = kx^{n - 1} (k는 상수)일 "
                "때, k의 값을 구하시오."
            ),
            answer_text=str(n),
            explanation=(
                "거듭제곱의 미분법에 따라 원래 함수의 지수 n이 도함수의 계수가 되고 지수는 n - 1이 "
                f"되므로 f'(x) = nx^(n - 1)이다. 지수를 비교하면 n - 1 = {n - 1}이므로 "
                f"n = {n}이고, 계수를 비교하면 k = n = {n}이다."
            ),
            conditions=f"Derivative(x**{n}, x).doit().subs(x, 2) = k*2**{n - 1}",
            answer_map=(("k", str(n)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(n),
        )

    return [
        Frame("applied-find-exponent", _grid("p3-power:a1", (2, 3, 4, 5, 6), (2, 3, 4)), a1),
        Frame("applied-find-positive-point", _grid("p3-power:a2", (2, 3, 4), (2, 3, 4, 5, 6)), a2),
        Frame("applied-coefficient-given", _grid("p3-power:a3", (2, 3, 4), (2, 3, 4, 5, 6)), a3),
        Frame("applied-derivative-equals-function", _grid("p3-power:a4", tuple(range(2, 10))), a4),
        Frame(
            "applied-difference-from-f-prime-one", _grid("p3-power:a5", (2, 3, 4), (2, 3, 4)), a5
        ),
        Frame(
            "applied-coefficient-from-derivative-exponent",
            _grid("p3-power:a6", tuple(range(2, 10))),
            a6,
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 오개념 유발(misconception_trigger) — 객관식, 오답이 power-rule-step-omitted에서 나온다
# ──────────────────────────────────────────────────────────────────────────
def _mc_value_item(frame_id: str, text_of: str, n: int, a: int) -> DiffItem | None:
    """f'(a)의 값 4지선다 — 정답·계수 누락(a^(n-1))·지수 감소 누락(n·a^n)·필러(f(a))."""
    correct = eval_at(derivative_of(_mono(n)), a)
    coeff_omitted = a ** (n - 1)
    exponent_kept = n * a**n
    filler = a**n
    try:
        choices, answer, distractors = build_choices(
            [
                ChoiceEntry(str(correct), is_correct=True, sort_key=float(correct)),
                ChoiceEntry(str(coeff_omitted), _KEBAB, sort_key=float(coeff_omitted)),
                ChoiceEntry(str(exponent_kept), _KEBAB, sort_key=float(exponent_kept)),
                ChoiceEntry(str(filler), sort_key=float(filler)),
            ],
            shuffle_seed=f"{frame_id}:{n}:{a}",
        )
    except ValueError:
        return None
    return DiffItem(
        slot="misconception_trigger",
        frame_id=frame_id,
        question_text=text_of,
        answer_text=answer,
        explanation=(
            f"거듭제곱의 미분법에 따라 x^{n}의 도함수는 {render_poly(derivative_of(_mono(n)))}"
            f"이므로 x가 {a}일 때의 값은 {correct}이다."
        ),
        conditions=f"Derivative(x**{n}, x).doit().subs(x, {a}) = y",
        answer_map=(("y", str(correct)),),
        problem_type_code=_EVAL,
        answer_format=_fmt(correct),
        choices=choices,
        distractors=distractors,
    )


def _mc_solve_cubic(a0: int) -> DiffItem | None:
    """f(x) = x^3, f'(a) = b를 만족시키는 양수 a 4지선다 — 계수 누락이면 a = sqrt(b)."""
    b = 3 * a0 * a0
    wrong_coeff = sympy.sqrt(b)  # (x^3)'를 x^2로 쓴 학생이 얻는 a
    entries = [
        ChoiceEntry(str(a0), is_correct=True, sort_key=float(a0)),
        # 학생 표기 — '8√3'(4차 감사 bad_wording: 3차의 '8sqrt(3)'도 코드 표기로 판정됐다).
        ChoiceEntry(render_surd(wrong_coeff), _KEBAB, sort_key=float(wrong_coeff)),
    ]
    cube_root = round(a0 ** (2 / 3))
    if cube_root**3 == a0 * a0 and cube_root != a0:
        # 지수 감소 누락: (x^3)' = 3x^3 → 3a^3 = b → a^3 = a0^2 (정수 해가 있을 때만 매핑)
        entries.append(ChoiceEntry(str(cube_root), _KEBAB, sort_key=float(cube_root)))
        entries.append(ChoiceEntry(str(a0 * a0), sort_key=float(a0 * a0)))
    else:
        entries.append(ChoiceEntry(str(a0 * a0), sort_key=float(a0 * a0)))
        entries.append(ChoiceEntry(str(3 * a0), sort_key=float(3 * a0)))
    try:
        choices, answer, distractors = build_choices(entries, shuffle_seed=f"mc-cubic:{a0}")
    except ValueError:
        return None
    return DiffItem(
        slot="misconception_trigger",
        frame_id="mc-solve-cubic",
        question_text=(
            f"함수 f(x) = x^3에 대하여 f'(a) = {with_eul_reul(b)} 만족시키는 양수 a의 값은?"
        ),
        answer_text=answer,
        explanation=(f"x^3의 도함수는 3x^2이므로 3a^2이 {with_i_ga(b)} 되는 양수 a는 {a0}이다."),
        conditions=(_deriv_value_sym("3", "a") + f" = {b}", "a > 0"),
        answer_map=(("a", str(a0)),),
        problem_type_code=_SOLVE,
        answer_format=_fmt(a0),
        choices=choices,
        distractors=distractors,
    )


def _mc_solve_square(s: int) -> DiffItem | None:
    """f(x) = x^2, f'(a) = b를 만족시키는 a 4지선다 — a0 = s^2.

    계수 누락이면 a = b, 지수 유지면 a = s가 된다.
    """
    a0 = s * s
    b = 2 * a0
    entries = [
        ChoiceEntry(str(a0), is_correct=True, sort_key=float(a0)),
        ChoiceEntry(str(b), _KEBAB, sort_key=float(b)),  # (x^2)'를 x로 쓴 경우
        ChoiceEntry(str(s), _KEBAB, sort_key=float(s)),  # (x^2)'를 2x^2으로 쓴 경우
        ChoiceEntry(str(sympy.Rational(a0, 2)), sort_key=a0 / 2),
    ]
    try:
        choices, answer, distractors = build_choices(entries, shuffle_seed=f"mc-square:{s}")
    except ValueError:
        return None
    return DiffItem(
        slot="misconception_trigger",
        frame_id="mc-solve-square",
        question_text=(f"함수 f(x) = x^2에 대하여 f'(a) = {with_eul_reul(b)} 만족시키는 a의 값은?"),
        answer_text=answer,
        explanation=f"x^2의 도함수는 2x이므로 2a가 {with_i_ga(b)} 되는 a는 {a0}이다.",
        conditions=_deriv_value_sym("2", "a") + f" = {b}",
        answer_map=(("a", str(a0)),),
        problem_type_code=_SOLVE,
        answer_format=_fmt(a0),
        choices=choices,
        distractors=distractors,
    )


_MC_N: Final = (3, 4, 5, 6, 7, 8)
_MC_A: Final = (2, 3, 4, 5)


def _misconception_frames() -> list[Frame]:
    def m1(p: tuple[object, ...]) -> DiffItem | None:
        n, a = int(str(p[0])), int(str(p[1]))
        return _mc_value_item(
            "mc-value-of-derivative",
            f"함수 f(x) = x^{n}에 대하여 f'({a})의 값은?",
            n,
            a,
        )

    def m2(p: tuple[object, ...]) -> DiffItem | None:
        n, a = int(str(p[0])), int(str(p[1]))
        return _mc_value_item(
            "mc-coefficient-at-point",
            f"y = x^{n}의 x = {a}에서의 미분계수로 옳은 것은?",
            n,
            a,
        )

    def m3(p: tuple[object, ...]) -> DiffItem | None:
        n, a = int(str(p[0])), int(str(p[1]))
        return _mc_value_item(
            "mc-substitute-into-derivative",
            f"함수 f(x) = x^{n}의 도함수 f'(x)에 x = {with_eul_reul(a)} 대입한 값으로 옳은 것은?",
            n,
            a,
        )

    def m3b(p: tuple[object, ...]) -> DiffItem | None:
        n, a = int(str(p[0])), int(str(p[1]))
        return _mc_value_item(
            "mc-derivative-of-curve-at-point",
            f"함수 y = x^{n}의 도함수 y'에 대하여 x = {a}일 때 y'의 값은?",
            n,
            a,
        )

    def m4(p: tuple[object, ...]) -> DiffItem | None:
        return _mc_solve_cubic(int(str(p[0])))

    def m4b(p: tuple[object, ...]) -> DiffItem | None:
        return _mc_solve_square(int(str(p[0])))

    return [
        Frame("mc-value-of-derivative", _grid("p3-power:m1", _MC_N, _MC_A), m1),
        Frame("mc-coefficient-at-point", _grid("p3-power:m2", _MC_N, _MC_A), m2),
        Frame("mc-substitute-into-derivative", _grid("p3-power:m3", _MC_N, _MC_A), m3),
        Frame("mc-derivative-of-curve-at-point", _grid("p3-power:m3b", _MC_N, _MC_A), m3b),
        Frame("mc-solve-cubic", _grid("p3-power:m4", (2, 3, 4, 5, 6, 8, 27)), m4),
        Frame("mc-solve-square", _grid("p3-power:m4b", (3, 4, 5, 6, 7)), m4b),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 진단(diagnostic) — 지수·계수·차수·특수한 값을 한 가지씩 확인
# ──────────────────────────────────────────────────────────────────────────
def _diagnostic_frames() -> list[Frame]:
    # 4차 감사(2026-10-07) bad_tag 처분 — 'x^n의 도함수에 x = 0을 대입한 값'·'방정식 f'(x) = 0의
    # 실근' 두 틀을 삭제했다. 정답이 0이고 원함수에 대입해도, 지수를 안 줄이거나 계수를 빠뜨려도
    # 0이라 거듭제곱 미분법을 변별하지 못한다(우회로 판정기 T-zero-monomial이 재발을 막는다).
    def d2(p: tuple[object, ...]) -> DiffItem | None:
        a = int(str(p[0]))
        return DiffItem(
            slot="diagnostic",
            frame_id="diag-derivative-of-identity-function",
            question_text=f"함수 f(x) = x에 대하여 f'({a})의 값을 구하시오.",
            answer_text="1",
            explanation="f(x) = x는 지수가 1인 거듭제곱이므로 도함수는 1이다.",
            conditions=_deriv_sym("x", str(a)) + " = y",
            answer_map=(("y", "1"),),
            problem_type_code=_EVAL,
            answer_format=_fmt(1),
        )

    def d3(p: tuple[object, ...]) -> DiffItem | None:
        # 7회차 감사(2026-10-08) 처분 — 종전 'f'(1)'은 x = 1이라 지수를 줄이지 않는 오개념(n·x^n)도
        # 같은 값 n을 냈다(판정자 지적 cbde3ec3 · 판정기 T-power-path-coincidence). x = -2에서
        # 묻는다 — 지수 유지면 부호까지 뒤집힌 2배(n·(-2)^n), 계수 누락이면 (-2)^(n - 1)로 모두
        # 갈린다.
        n = int(str(p[0]))
        return _value_item(
            slot="diagnostic",
            frame_id="diag-derivative-at-minus-two",
            text=f"함수 f(x) = x^{n}에 대하여 f'(-2)의 값을 구하시오.",
            n=n,
            point=-2,
        )

    def d4(p: tuple[object, ...]) -> DiffItem | None:
        n = int(str(p[0]))
        return _value_item(
            slot="diagnostic",
            frame_id="diag-derivative-at-minus-one",
            text=f"함수 f(x) = x^{n}에 대하여 f'(-1)의 값을 구하시오.",
            n=n,
            point=-1,
        )

    def d6(p: tuple[object, ...]) -> DiffItem | None:
        # 4차 감사 처분으로 지운 두 틀의 자리 — 같은 '지수·계수' 진단을 *변별력 있게* 묻는다.
        # f'(2) = n·2^(n - 1)은 f(2) = 2^n의 n/2배다. 지수를 안 줄이면 n배, 계수를 빠뜨리면 1/2배가
        # 나와 오답 경로마다 답이 다르다(0 불변이던 종전 틀과 반대).
        n = int(str(p[0]))
        d_val, f_val = _dval(n, 2), 2**n
        ratio = sympy.Rational(d_val, f_val)
        return DiffItem(
            slot="diagnostic",
            frame_id="diag-derivative-to-function-ratio",
            question_text=(
                f"함수 f(x) = x^{n}에 대하여 f'(2)의 값은 f(2)의 값의 몇 배인지 구하시오."
            ),
            answer_text=str(ratio),
            explanation=(
                f"f'(x) = {render_poly(derivative_of(_mono(n)))}이므로 f'(2)의 값은 "
                f"{n}(2^{n - 1}) = {d_val}이고, f(2)의 값은 2^{n} = {with_i_ga(f_val)}다. "
                # 5회차 감사 해설 결함 — 정의 없는 기호 k('32 = k(16)')를 쓰지 않고 나눗셈으로 쓴다.
                f"f'(2)의 값을 f(2)의 값으로 나누면 {d_val}/{f_val} = {ratio}이므로 f'(2)의 값은 "
                f"f(2)의 값의 {ratio}배이다."
            ),
            conditions=f"{_deriv_value_sym(str(n), '2')} = k*2**{n}",
            answer_map=(("k", str(ratio)),),
            problem_type_code=_EVAL,
            answer_format=_fmt(ratio),
        )

    def order(frame_id: str) -> tuple[tuple[object, ...], ...]:
        return tuple((n,) for n in seeded_order(f"p3-power:{frame_id}", _N_RANGE))

    return [
        Frame(
            "diag-derivative-of-identity-function",
            tuple((a,) for a in seeded_order("p3-power:d2", (-5, -4, -3, -2, -1, 1, 2, 3, 4, 5))),
            d2,
        ),
        # 지수 2..6 — 진단 문항의 값이 너무 커지지 않게(n = 9면 9·2^8 = 2304).
        Frame(
            "diag-derivative-at-minus-two",
            tuple((n,) for n in seeded_order("p3-power:d3", tuple(range(2, 7)))),
            d3,
        ),
        Frame("diag-derivative-at-minus-one", order("d4"), d4),
        # 지수 3 이상 — n = 2이면 2^(n - 1) = 2^1 표기가 생기고(지수 1 표기 결함 부류) 비율이 1이다.
        Frame(
            "diag-derivative-to-function-ratio",
            tuple((n,) for n in seeded_order("p3-power:d6", tuple(range(3, 10)))),
            d6,
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 숙련도 확인(mastery_check) — 여러 값을 묶거나 미지수를 거쳐 값을 구한다
# ──────────────────────────────────────────────────────────────────────────
def _mastery_frames() -> list[Frame]:
    def k1(p: tuple[object, ...]) -> DiffItem | None:
        n, m, k, a = (int(str(v)) for v in p)
        if len({n, m, k}) != 3:
            return None
        total = sum(eval_at(derivative_of(_mono(e)), a) for e in (n, m, k))
        return DiffItem(
            slot="mastery_check",
            frame_id="mastery-sum-of-three-values",
            question_text=(
                f"f(x) = x^{n}, g(x) = x^{m}, h(x) = x^{k}일 때, "
                f"f'({a}) + g'({a}) + h'({a})의 값을 구하시오."
            ),
            answer_text=str(total),
            explanation=(
                f"세 도함수는 {render_poly(derivative_of(_mono(n)))}, "
                f"{render_poly(derivative_of(_mono(m)))}, {render_poly(derivative_of(_mono(k)))}"
                f"이므로 x가 {a}일 때 세 값을 더하면 {total}이다."
            ),
            conditions=_deriv_sym(f"x**{n} + x**{m} + x**{k}", str(a)) + " = y",
            # 풀이 단계는 해설처럼 세 도함수를 따로 구한다(검산 조건은 합의 미분 한 번).
            solution_setup=(
                f"(Derivative(x**{n}, x) + Derivative(x**{m}, x) + Derivative(x**{k}, x))"
                f".doit().subs(x, {a}) = y"
            ),
            answer_map=(("y", str(total)),),
            problem_type_code=_EVAL,
            answer_format=_fmt(total),
        )

    def k2(p: tuple[object, ...]) -> DiffItem | None:
        n = int(str(p[0]))
        d = derivative_of(_mono(n))
        b = eval_at(d, 2)
        y = eval_at(d, 3)
        found = _unique_exponent(2, b)  # 첫 미지수 n은 생성기가 SymPy로 풀어 조건식에 대입한다
        if found != n:  # pragma: no cover — 유일해 보증(헬퍼가 이미 ValueError)
            return None
        return DiffItem(
            slot="mastery_check",
            frame_id="mastery-find-exponent-then-evaluate",
            question_text=(
                f"함수 f(x) = x^n (n은 2 이상의 자연수)에 대하여 f'(2)의 값이 {b}일 때, "
                "f'(3)의 값을 구하시오."
            ),
            answer_text=str(y),
            # 3차 감사 bad_explanation — n을 정하는 일반 도함수 nx^(n - 1)과 세운 방정식을 보인다
            # (종전 해설은 'f'(2)가 12이므로 n은 3'이라는 결론만 적었다).
            explanation=(
                "거듭제곱의 미분법에 따라 f'(x) = nx^(n - 1)이므로 f'(2)는 n(2^(n - 1))이고, "
                f"방정식 n(2^(n - 1)) = {with_eul_reul(b)} 풀어야 한다. n이 1 늘 때마다 좌변이 "
                f"커지므로 해는 하나뿐이고, {n}({_two_power(n - 1)}) = {b}이므로 n = {n}이다. "
                f"따라서 f'(x) = {render_poly(d)}이고 x가 3일 때의 값은 {y}이다."
            ),
            conditions=_deriv_sym(f"x**{n}", "3") + " = y",
            answer_map=(("y", str(y)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(y),
        )

    def k3(p: tuple[object, ...]) -> DiffItem | None:
        k = int(str(p[0]))
        n = 2 * k
        return DiffItem(
            slot="mastery_check",
            frame_id="mastery-derivative-is-multiple-of-function-value",
            question_text=(
                f"함수 f(x) = x^n (n은 자연수)에 대하여 f'(2)의 값이 f(2)의 값의 {k}배일 때, "
                "n의 값을 구하시오."
            ),
            answer_text=str(n),
            explanation=(
                "f'(x) = nx^(n - 1)이므로 f'(2)는 n과 2^(n - 1)의 곱이고 f(2) = 2^n이다. "
                "2^n은 2^(n - 1)의 2배이므로 f'(2)는 f(2)의 n/2배이다. "
                f"n/2 = {k}에서 n = {n}이다."
            ),
            conditions=f"{_deriv_value_sym('n', '2')} = {k}*2**n",
            answer_map=(("n", str(n)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(n),
        )

    def k4(p: tuple[object, ...]) -> DiffItem | None:
        b = int(str(p[0]))
        x = b // 3
        return DiffItem(
            slot="mastery_check",
            frame_id="mastery-nonzero-root-of-derivative-equation",
            question_text=(
                f"함수 f(x) = x^3에 대하여 방정식 f'(x) = {b}x의 0이 아닌 실근을 구하시오."
            ),
            answer_text=str(x),
            explanation=f"f'(x)는 3x^2이므로 3x^2이 {b}x와 같아지는 0이 아닌 x는 {x}이다.",
            conditions=(f"Derivative(x**3, x).doit() = {b}*x", "x != 0"),
            answer_map=(("x", str(x)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(x),
        )

    return [
        Frame(
            "mastery-sum-of-three-values",
            # 7회차 감사 — x = 1은 매개변수 거부 조건이 건너뛴다(위 basic 틀과 같은 이유) · x = 3은
            # 값이 5000을 넘는다.
            _grid("p3-power:k1", (2, 3), (4, 5), (6, 7), (-1, 2, -2)),
            k1,
        ),
        Frame("mastery-find-exponent-then-evaluate", _grid("p3-power:k2", (2, 3, 4, 5, 6)), k2),
        Frame(
            "mastery-derivative-is-multiple-of-function-value",
            _grid("p3-power:k3", (1, 2, 3, 4, 5)),
            k3,
        ),
        Frame(
            "mastery-nonzero-root-of-derivative-equation",
            _grid("p3-power:k4", tuple(range(6, 60, 3))),
            k4,
        ),
    ]


_SLOT_FRAMES = {
    "representative": _rep_frames,
    "basic": _basic_frames,
    "applied": _applied_frames,
    "misconception_trigger": _misconception_frames,
    "diagnostic": _diagnostic_frames,
    "mastery_check": _mastery_frames,
}


class P3DiffPowerDerivativeGenerator(P3DiffSlotGenerator):
    """[12미적Ⅰ-02-03] 함수 y=x^n의 도함수 — 슬롯 6종 결정론 생성기."""

    standard_code: ClassVar[str] = "[12미적Ⅰ-02-03]"
    concept_src_id: ClassVar[str] = "H:12미적Ⅰ02-03"
    unit_code: ClassVar[str] = "P3-CALC1-DIFF-POWER"
    slug_prefix: ClassVar[str] = "wm-p3-diff-power"
    slot_difficulty: ClassVar[dict[str, float]] = {
        "representative": 2.0,
        "basic": 2.0,
        "applied": 3.0,
        "misconception_trigger": 3.0,
        "diagnostic": 2.0,
        "mastery_check": 3.5,
    }
    slot_count: ClassVar[int] = 12

    @classmethod
    def _slot_items(cls, slot: str, claimed: set[str]) -> list[DiffItem]:
        return round_robin_items(
            _SLOT_FRAMES[slot](),
            cls.slot_count,
            claimed=claimed,
            standard_code=cls.standard_code,  # 매개변수 거부 조건(우연 일치 — 5회차 감사)
        )
