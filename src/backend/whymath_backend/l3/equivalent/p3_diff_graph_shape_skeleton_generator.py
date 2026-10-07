"""[12미적Ⅰ-02-08] 함수의 그래프의 개형 — 파생 판정 문항 결정론 생성기 — P3-03(결정론·LLM 0).

개념: `H:12미적Ⅰ02-08`(`math.calculus.hamsuui-geuraepeu-gaehyeong`). 이 개념은 개형 *그림*을
고르게 하는 문항을 두지 않는다 — 게이트 `G-p318-calc-02-08-disposition`(처분 (나))이 개형에서
*파생되는 값*(극값의 x좌표·극값의 값·증감 판정)을 묻는 문항으로 대체했고, 게이트
`G-p321-derived-form-disposition`(Kiki 2026-10-05 · 안 나)이 **허용 형태**를 좁혔다.
허용·금지 규칙의 정본·집행 코드는 `l1/problem_bank/derived_form_rules.py`(P3-24 ·
`populate._record_from_line`이 적재 전 거부)다.

이 파일이 지키는 허용 형태
------------------------
  · **A1 증감 경계점 x좌표**(f'=0의 근 중 큰/작은 값) — `answer_selection`
    (largest/smallest)을 *항상* 붙인다. 프로브 B1은 selection 없이도 '값만 틀린' 오답은
    걸렀지만 두 근 중 *다른 근*을 답한 오답은 통과시킨다 — selection이 그 구멍을 막는다.
  · **A2·A2d 구간 소속 정수**(f'>0 / f'<0) — 구간에 정수가 **정확히 하나뿐**인 함수만
    쓴다(정답이 유일). 발문은 f'의 부등식이 아니라 '증가·감소하는 x의 값의 범위'로 묻고(3차 감사
    T08-derivative-inequality), f'의 근을 정수가 아닌 p/2로 둬 범위를 열린·닫힌 어느 쪽으로 읽어도
    정수 집합이 같게 한다(2차 감사 개폐 모호성 재발 방지 — `_interval_item`).
  · **B 극대·극소의 x좌표**(규칙 B3) — `answer_selection`을 *반드시* 단다. 어느 쪽 근을
    고를지는 SymPy가 f'의 부호 변화를 직접 읽어 정한다(최고차항 계수의 부호를 손으로
    가정하지 않는다 — 계수가 음수이면 극대·극소가 뒤바뀐다는 규칙 문서 §3-1의 함정을
    코드가 피한다).
  · **C 극값의 값**(규칙 C3) — 문항 본문에 극값 x좌표를 `x = r`로 **고정**하고
    `answer_map`에 x를 싣는다. 검산 조건에 `f'(x) = 0`을 함께 둬 "x = r이 정말 임계점인가"
    까지 기계가 본다.

만들지 않는 형태(제외 4형태 + 이 파일의 자체 제외)
------------------------------------------------
  · 증감 구간을 **구간 기호**로 답하기(A4) · **경계 포함 여부**(A3) · 구간을
    **함수식 단독 조건**으로 검산(A5) · x 없이 극값의 값만 답(C4) — 규칙 코드가 적재 시
    거부한다.
  · **극값의 개수**: 게이트 결정문은 "극값 개수(실측 가능)"를 허용 예로 들지만,
    `answer_kind = extremum_count` 검산 조건은 f(x) *식 단독*(`x**3 - 3*x`)이라 규칙 A5에
    정면으로 걸리고, "극값의 개수" 문면은 규칙 C3의 정규식(`극값`)에도 걸려 x 고정을
    요구받는다(개수 문항에 x 고정은 무의미). 규칙을 우회하지 않고(관계식으로 위장한 가짜
    조건 금지) **이 생성기는 개수 문항을 만들지 않는다** — 규칙 코드와 결정문의 불일치로
    호출자에게 보고했다.
  · 함수식 답(`answer_format=식`) — 섀도 채점 계약(NLP-09)이 스칼라 단일 미지수만 받는다.

슬롯 6종 × 틀(frame)
-------------------
대표(증감 경계점·극대/극소 x좌표·극값의 값·구간 소속 정수) · 기본(작은 근·극값 x좌표·값) ·
응용(미지수 구하기·사차함수 극소/극대 x좌표) · 오개념 유발(객관식 —
`critical-point-implies-extremum`) · 진단 · 숙련도 확인. 개념당 고유 문면 골격 30 이상이
목표다.

오개념 연결
----------
이 개념에 귀속된 핵심 오개념은 M0676("증감표 없이 몇 점만 찍어 잇는다 — 극값과 변곡점을
구분하지 않는다")뿐이고, 크로스링크에 M0676을 가리키는 kebab은 **없다**(MISC-40이 '문항
맥락 종속형'이라 의도적 제외 — `l4/misconception/catalog.py` 주석). 그래서 오답 선지는
같은 오류 유형(극값변곡혼동)을 정확히 서술하는 *기존* kebab
`critical-point-implies-extremum`(f'(a)=0이면 극값이라는 단정 — 반례 x^3)에 연결한다(신규
id 0). 이 kebab은 M0080에만 직접매핑이며 M0676에는 닿지 않으므로 Phase 3 계측기의
'핵심 오개념 도달'(M0676)은 이 문항들로 세어지지 않는다 — 정직하게 보고한다.

문제유형 정직성
--------------
극대·극소·증감 경계점의 x좌표와 극값의 값을 구하는 문항은 `ptype.optimize-extremum`
(스킬 graph-sketching·solution-checking·completing-square)이다 — 02-08의 스킬
(graph-sketching·graph-reading)과 `graph-sketching`에서 겹친다. 구간 소속 정수·미지수
구하기는 f'>0 / f'(r)=0을 *풀어* 얻으므로 `ptype.solve-for-unknown`으로 정직하게 달고
(스킬 연결로 세어지지 않는다), 겹치게 하려고 유형을 바꾸지 않는다.

검산 재료의 형식(중요)
--------------------
· 조건은 `Derivative(<f>, x).doit() = 0`(등식)·`> 0`·`< 0`(부등식) — 문항의 *원래 함수*를
  그대로 싣는다(전개한 f'만 싣지 않으므로 상수항이 조건 서명에 반영돼 문항 사이 중복이
  줄고, 문항과 검산이 같은 함수를 말한다).
· 극값의 값·미지수 구하기는 미지수가 x와 y(또는 a·k) 둘이라 **연립 목록 조건**이다 —
  규칙 C3이 answer_map에 x를 요구하기 때문이다. 섀도 채점 코퍼스 로더는 문자열 조건만
  읽으므로(목록은 건너뜀) 단일 미지수 계약 동결(`test_multi_symbol_population_is_frozen`)을
  깨지 않는다(P3-03 기존 17건과 같은 경로).
· `answer_selection`은 `CandidateProblem`에만 있고 기반 `DiffItem`에는 없다 — 기반 모듈을
  고치지 않고 `ShapeItem`(DiffItem 하위)이 실어 `_assemble`에서 후보에 얹는다.

review_status는 쓰지 않는다(키 부재 유지 — 기반 모듈 docstring과 같다).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, Final

import sympy

from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.generator import CandidateProblem
from whymath_backend.l3.equivalent.p3_diff_expr import (
    Poly,
    derivative_of,
    eval_at,
    poly_to_sympy,
    poly_to_sympy_str,
    render_affine,
    render_factored,
    render_poly,
    with_eun_neun,
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
from whymath_backend.lang.josa import eul_reul, eun_neun, i_ga, wa_gwa
from whymath_backend.schema.enums import AnswerFormat

__all__ = ["P3DiffGraphShapeGenerator", "ShapeItem"]

_KEBAB: Final = "critical-point-implies-extremum"
_OPT: Final = "ptype.optimize-extremum"
_SOLVE: Final = "ptype.solve-for-unknown"

_X = sympy.Symbol("x")


# ──────────────────────────────────────────────────────────────────────────
# 항목 타입 — 기반 DiffItem에 answer_selection만 더한다
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ShapeItem(DiffItem):
    """`DiffItem` + 근 선택(`answer_selection`) — 기반을 고치지 않고 후보에 얹을 값을 싣는다."""

    answer_selection: str | None = None


def _fmt(value: object) -> AnswerFormat:
    """정답 형식 — 기반의 단일 규칙(`answer_format_for`)을 따른다."""
    return answer_format_for(str(value))


# ──────────────────────────────────────────────────────────────────────────
# 함수 분석 — f'의 근과 부호 변화를 SymPy가 직접 읽는다(극대·극소를 손으로 가정하지 않는다)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class _Fn:
    poly: Poly
    deriv: Poly
    #: f'(x) = 0의 서로 다른 실근(오름차순·전부 정수)
    roots: tuple[int, ...]
    #: 부호가 바뀌는 근 → "max"(+→-) | "min"(-→+)
    kinds: dict[int, str]

    @property
    def text(self) -> str:
        return render_poly(self.poly)

    @property
    def sym(self) -> str:
        return poly_to_sympy_str(self.poly)

    @property
    def flat_roots(self) -> tuple[int, ...]:
        """f'=0이지만 부호가 바뀌지 않는 근(극값이 아닌 임계점)."""
        return tuple(r for r in self.roots if r not in self.kinds)


def _analyze(poly: Poly) -> _Fn | None:
    """f'의 근이 전부 정수 실근이면 분석 결과를, 아니면 None(이 틀에 부적합)."""
    deriv = derivative_of(poly)
    if not deriv:
        return None
    dpoly = sympy.Poly(poly_to_sympy(deriv), _X)
    mult = sympy.roots(dpoly)
    if sum(mult.values()) != dpoly.degree():
        return None
    if any(not (r.is_integer and r.is_real) for r in mult):
        return None
    roots = tuple(sorted(int(r) for r in mult))
    d_expr = poly_to_sympy(deriv)
    samples = [
        sympy.Integer(roots[0] - 1),
        *(sympy.Rational(roots[i] + roots[i + 1], 2) for i in range(len(roots) - 1)),
        sympy.Integer(roots[-1] + 1),
    ]
    signs = [int(sympy.sign(d_expr.subs(_X, s))) for s in samples]
    kinds: dict[int, str] = {}
    for index, root in enumerate(roots):
        left, right = signs[index], signs[index + 1]
        if left > 0 > right:
            kinds[root] = "max"
        elif left < 0 < right:
            kinds[root] = "min"
    return _Fn(poly=poly, deriv=deriv, roots=roots, kinds=kinds)


def _selection(fn: _Fn, target: int) -> str | None:
    """f'=0의 *모든* 실근 중 target의 위치 — 맨 앞이면 smallest, 맨 뒤면 largest, 가운데면 None."""
    if len(fn.roots) < 2:
        return None
    if target == fn.roots[0]:
        return "smallest"
    if target == fn.roots[-1]:
        return "largest"
    return None


def _explain(fn: _Fn) -> str:
    """f'의 근과 각 근 좌우의 부호 변화를 서술한다(정답 근거 — SymPy 분석 결과 그대로)."""
    roots = ", ".join(str(r) for r in fn.roots)
    # 도함수를 인수분해해 근을 보인다 — 결론(근)만 적지 않는다(2차 감사: 핵심 중간 단계).
    parts = [
        f"f'(x) = {render_poly(fn.deriv)} = {render_factored(fn.deriv)}이므로 f'(x) = 0의 근은 "
        f"x = {roots}이다."
    ]
    for r in fn.roots:
        kind = fn.kinds.get(r)
        if kind == "max":
            parts.append(f"x = {r}의 좌우에서 f'(x)의 부호가 양에서 음으로 바뀌므로 극대이다.")
        elif kind == "min":
            parts.append(f"x = {r}의 좌우에서 f'(x)의 부호가 음에서 양으로 바뀌므로 극소이다.")
        else:
            parts.append(f"x = {r}의 좌우에서 f'(x)의 부호가 바뀌지 않으므로 극값이 아니다.")
    return " ".join(parts)


def _fill(template: str, fn_text: str, **values: object) -> str:
    """발문 틀 채우기 — 함수식 꼬리의 받침에 맞춰 조사(가·는)를 고른다(`{ga}`·`{neun}`)."""
    return template.format(f=fn_text, ga=i_ga(fn_text), neun=eun_neun(fn_text), **values)


def _deriv_cond(fn_sym: str, relation: str) -> str:
    return f"Derivative({fn_sym}, x).doit() {relation} 0"


def _item(
    *,
    slot: str,
    frame_id: str,
    text: str,
    answer: int,
    conditions: str | tuple[str, ...],
    answer_map: tuple[tuple[str, str], ...],
    ptype: str,
    explanation: str,
    selection: str | None = None,
    choices: tuple[str, ...] | None = None,
    distractors: tuple[tuple[int, str], ...] = (),
    setup: str | None = None,
) -> ShapeItem:
    return ShapeItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=str(answer),
        explanation=explanation,
        conditions=conditions,
        answer_map=answer_map,
        problem_type_code=ptype,
        answer_format=_fmt(answer),
        choices=choices,
        distractors=distractors,
        answer_selection=selection,
        solution_setup=setup,
    )


# ──────────────────────────────────────────────────────────────────────────
# 함수 풀 — 전부 임계점이 정수가 되도록 *구성*한다
# ──────────────────────────────────────────────────────────────────────────
def _cubic(a: int, r1: int, r2: int, c: int) -> Poly | None:
    """f' = 3a(x - r1)(x - r2)인 삼차함수 a x^3 + b x^2 + d x + c — 계수가 정수가 아니면 None."""
    if r1 >= r2:
        return None
    b_twice = -3 * a * (r1 + r2)  # x^2 계수의 2배
    if b_twice % 2:
        return None
    b = b_twice // 2
    d = 3 * a * r1 * r2
    if max(abs(b), abs(d)) > 36:
        return None
    terms = [(3, a), (2, b), (1, d), (0, c)]
    return tuple((e, k) for e, k in terms if k != 0)


def _cubic_pool(
    seed: str,
    leads: Sequence[int],
    c_values: Sequence[int],
    *,
    gap: int | None = None,
) -> tuple[tuple[object, ...], ...]:
    combos: list[tuple[object, ...]] = []
    for a in leads:
        for r1 in range(-4, 4):
            for r2 in range(r1 + 1, 5):
                if gap is not None and r2 - r1 != gap:
                    continue
                for c in c_values:
                    combos.append((a, r1, r2, c))
    return tuple(seeded_order(seed, combos))


def _quartic_flat(a: int, b: int, c: int) -> tuple[Poly, int] | None:
    """a x^4 + b x^3 + c — f' = x^2(4a x + 3b).

    x = 0은 f'=0이지만 부호가 안 바뀌는 점이고, q = -3b/(4a)만 극값이다.

    q가 0이 아닌 정수(|q| <= 6)일 때만 만든다. (poly, q)를 돌려준다.
    """
    if b == 0 or (-3 * b) % (4 * a):
        return None
    q = (-3 * b) // (4 * a)
    if q == 0 or abs(q) > 6:
        return None
    terms = [(4, a), (3, b), (0, c)]
    return tuple((e, k) for e, k in terms if k != 0), q


def _quartic_flat_pool(seed: str, c_values: Sequence[int]) -> tuple[tuple[object, ...], ...]:
    combos: list[tuple[object, ...]] = []
    for a in (1, 2, 3, 4, -1, -2, -3, -4):
        for b in range(-16, 17):
            if _quartic_flat(a, b, 1) is None or abs(b) > 16:
                continue
            for c in c_values:
                combos.append((a, b, c))
    return tuple(seeded_order(seed, combos))


_C_ALL: Final = (-6, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 6)
_LEADS: Final = (1, 2, -1, -2)


def _i(value: object) -> int:
    return int(str(value))


# ──────────────────────────────────────────────────────────────────────────
# 문항 조립 도우미 — 틀 하나가 이 함수들 중 하나를 부른다
# ──────────────────────────────────────────────────────────────────────────
def _x_item(
    slot: str,
    frame_id: str,
    template: str,
    fn: _Fn,
    *,
    role: str,
    pick: str | None,
) -> ShapeItem | None:
    """극대·극소·증감 경계점·평평한 임계점의 x좌표 문항.

    role: "turn"(부호가 바뀌는 근 전부) | "max" | "min" | "flat"(바뀌지 않는 임계점).
    pick: "largest"/"smallest"(후보 중 큰/작은 값을 묻는다 — 후보가 2개 이상) | None(후보가
    정확히 1개).
    """
    if role == "turn":
        candidates = sorted(fn.kinds)
    elif role in ("max", "min"):
        candidates = sorted(r for r, k in fn.kinds.items() if k == role)
    else:
        candidates = list(fn.flat_roots)
    if pick is None:
        if len(candidates) != 1:
            return None
        target = candidates[0]
    else:
        if len(candidates) < 2:
            return None
        target = candidates[-1] if pick == "largest" else candidates[0]
    selection = _selection(fn, target)
    if selection is None:
        return None
    return _item(
        slot=slot,
        frame_id=frame_id,
        text=_fill(template, fn.text),
        answer=target,
        conditions=_deriv_cond(fn.sym, "="),
        answer_map=(("x", str(target)),),
        ptype=_OPT,
        explanation=f"{_explain(fn)} 따라서 구하는 x좌표는 {target}이다.",
        selection=selection,
    )


def _interval_item(
    slot: str, frame_id: str, template: str, poly: Poly, *, roots: tuple[int, int], direction: str
) -> ShapeItem | None:
    """증가(`pos`)·감소(`neg`)하는 범위에 속하는 정수가 **개폐 해석과 무관하게** 정확히 하나인 문항.

    3차 감사(2026-10) 처분 — 종전 발문은 `f'(x) < 0`을 직접 줘 증감 판정 없이 이차부등식만
    남았다(우회로 판정기 T08-derivative-inequality). 발문을 '감소하는 x의 값의 범위'로 바꾸면
    이번에는 교과서 관례상 그 범위를 *닫힌* 구간으로 읽을 수 있어, f'의 근이 정수이면 양 끝
    정수까지 세어 '하나뿐'이 거짓이 된다(2차 감사가 교정한 개폐 모호성의 재발). 그래서 f'의 두
    근을 **정수가 아닌** p/2, q/2로 둔다 — 열린 범위(f'의 부호)와 닫힌 범위(f' = 0 포함)의 정수
    집합이 같고 하나뿐이다.
    """
    deriv = derivative_of(poly)
    d_expr = poly_to_sympy(deriv)
    wanted = 1 if direction == "pos" else -1
    strict = [n for n in range(-40, 41) if int(sympy.sign(d_expr.subs(_X, n))) == wanted]
    closed = [n for n in range(-40, 41) if int(sympy.sign(d_expr.subs(_X, n))) in (wanted, 0)]
    if len(strict) != 1 or strict != closed:
        return None
    n = strict[0]
    relation, other = (">", "<") if direction == "pos" else ("<", ">")
    word = "증가" if direction == "pos" else "감소"
    lo, hi = (sympy.Rational(r, 2) for r in roots)
    return _item(
        slot=slot,
        frame_id=frame_id,
        text=_fill(template, render_poly(poly)),
        answer=n,
        conditions=_deriv_cond(poly_to_sympy_str(poly), relation),
        answer_map=(("x", str(n)),),
        ptype=_SOLVE,
        explanation=(
            f"f'(x) = {render_poly(deriv)} = {render_factored(deriv)}이므로 f'(x) = 0의 근은 "
            f"x = {lo}, {hi}이다. {lo} < x < {hi}에서 f'(x) {relation} 0이고 x < {lo} 또는 "
            f"x > {hi}에서 f'(x) {other} 0이므로 f(x)는 {lo} ≤ x ≤ {hi}에서 {word}한다. 양 끝 "
            f"{lo}, {with_eun_neun(str(hi))} 정수가 아니므로 이 범위에 속하는 정수는 {n}뿐이다."
        ),
    )


def _kind_word(kind: str) -> str:
    return "극댓값" if kind == "max" else "극솟값"


_KIND_KO: Final = {"max": "극댓값", "min": "극솟값"}


def _pins_text(roots: Sequence[int]) -> str:
    """극값 후보의 x좌표 고정 표기 — 'x = 1과 x = 3'·'x = -2, x = 0, x = 2'."""
    if len(roots) == 2:
        first = str(roots[0])
        return f"x = {first}{wa_gwa(first)} x = {roots[1]}"
    return ", ".join(f"x = {r}" for r in roots)


def _judged_value_item(
    slot: str,
    frame_id: str,
    template: str,
    fn: _Fn,
    *,
    word: str,
    pick: str | None = None,
) -> ShapeItem | None:
    """고정한 극값 *후보들* 중 종류를 판정해야 답이 정해지는 극값의 값 문항(규칙 C3 + 판정 요구).

    발문은 f'(x) = 0의 근 x = r1, r2(, r3)를 모두 고정하지만 어느 것이 극대·극소(또는 극값이
    아닌 점)인지는 밝히지 않는다 — 학생은 f'의 부호 변화로 *종류를 판정*해야 답에 닿는다. 1차 은행의
    'x = 1에서 극솟값을 갖는다. 극솟값을 구하시오'는 위치·종류를 다 주어 대입만 남았다(2차 감사
    bad_tag 14건 — 맞혀도 숙달 추정이 부풀려진다). 규칙 C3(x 고정·answer_map의 x)은 그대로 지킨다.

    4차 감사(2026-10-07) 이후 이 함수는 *평평한 임계점이 섞인* 고정(사차 a x^4 + b x^3 + c의
    0과 q — 진단 `diag-extremum-value-among-critical-points`)에만 쓴다. 고정점이 전부 극값이면
    대입·대소 비교로 풀리므로(판정기 T08-given-critical-points) 그 형태는 `_other_root_value_item`
    계열로 바꿨다.

    word: "max"|"min"(그 종류의 값) · "any"(극값이 아닌 임계점을 가려내야 하는 형태).
    pick: None(그 종류의 값이 하나뿐 — 사차 우함수의 대칭 극값처럼 값이 같으면 하나로 본다) ·
    "smaller"/"larger"(같은 종류 둘의 *값*을 비교).
    """
    if word == "any":
        targets = [r for r in fn.roots if r in fn.kinds]
    else:
        targets = [r for r in fn.roots if fn.kinds.get(r) == word]
    if not targets:
        return None
    values = {r: eval_at(fn.poly, r) for r in targets}
    if pick is None:
        if len(set(values.values())) != 1:
            return None
        target = max(targets)  # 값이 같은 대칭 극값이면 양의 쪽을 검산 좌석으로 쓴다
    else:
        if len(targets) < 2 or len(set(values.values())) != len(targets):
            return None
        chooser = min if pick == "smaller" else max
        target = chooser(targets, key=lambda r: values[r])
    if target == 0:
        return None  # 극값이 x = 0에서면 상수항이 곧 답이다(2차 감사: 사실상 정답 노출)
    value = values[target]
    kind_word = _KIND_KO[fn.kinds[target]]
    if pick is None:
        tail = f"따라서 {kind_word}은 f({target}) = {value}이다."
    else:
        # 함숫값 등식('f(-4) = 102, f(1) = -23')을 나열하지 않는다 — 위생 게이트가 f(1)을 f·1로
        # 읽어 다른 등식과 모순이라 판정한다(오탐). 교과서 표기 'x = -4에서 102'로 쓴다.
        listed = ", ".join(f"x = {r}에서 {values[r]}" for r in sorted(targets))
        size = "작은" if pick == "smaller" else "큰"
        tail = f"두 {kind_word}은 {listed}이고, 이 중 {size} 값은 {value}이다."
    return _item(
        slot=slot,
        frame_id=frame_id,
        text=_fill(
            template,
            fn.text,
            pins=_pins_text(fn.roots),
            kind=kind_word,
            size="작은" if pick == "smaller" else "큰",
        ),
        answer=value,
        conditions=(f"y = {fn.sym}", poly_to_sympy_str(fn.deriv) + " = 0"),
        answer_map=(("x", str(target)), ("y", str(value))),
        ptype=_OPT,
        explanation=f"{_explain(fn)} {tail}",
        # 검산 조건의 f'(x) = 0은 도함수를 미리 풀어 쓴 다항식 — 풀이 단계는 미분에서 출발한다.
        setup=f"Derivative({fn.sym}, x).doit() = 0",
    )


def _signed(value: int, tail: str) -> str:
    """부호를 앞에 두는 항 표기 — 예 (-9, "x") → '- 9x', (5, "") → '+ 5'."""
    return f"{'-' if value < 0 else '+'} {abs(value)}{tail}"


# ──────────────────────────────────────────────────────────────────────────
# 4차 감사(2026-10-07) 재설계 — 임계점을 학생이 도함수로 직접 찾게 하는 극값 문항
# ──────────────────────────────────────────────────────────────────────────
# 종전 '극값 판정형'(`x = r1과 x = r2에서 극값을 갖는다. 극솟값을 구하시오`)은 임계점을 모두 발문이
# 주어, 두 위치에 대입한 뒤 '작은 값이 극솟값'으로 고르면 끝났다(삼차·사차에서 그 휴리스틱은 늘
# 맞는다 — 감사자 R3 30건). 사차 우함수(복이차식)는 완전제곱만으로 극값이 나왔다(R3·R5 8건).
# 이제 발문은 임계점 *하나*만 x = p로 고정하고(규칙 C3의 x 고정은 그대로 — answer_map의 x는 실제로
# 답한 극값의 위치), 함수식에 미지 계수 하나를 둔다. 학생은 f'(p) = 0으로 계수를 구하고, 도함수를
# 인수분해해 *나머지* 임계점을 찾고, 부호 변화로 종류를 판정해야 답에 닿는다. 묻는 극값은 고정한
# p가 아닌 쪽이다. 판정기 T08-given-critical-points·T08-biquadratic이 종전 형태의 재발을 막는다.


def _cubic_a_parts(lead: int, r1: int, r2: int) -> tuple[int, int] | None:
    """f' = 3·lead(x - r1)(x - r2)일 때 (a, B) — f = lead x^3 + a x^2 + B x + C.

    정수가 아니면 None.
    """
    twice = -3 * lead * (r1 + r2)
    if twice % 2:
        return None
    return twice // 2, 3 * lead * r1 * r2


def _poly_with_unknown(terms: Sequence[tuple[int, int | str]]) -> tuple[str, str]:
    """(지수, 계수) 목록 → (학생 표기, SymPy 표기). 계수가 문자열이면 미지 상수(이름 그대로) 항이다.

    계수 0 항은 뺀다. 미지 상수 항은 'ax^2'·'kx'·'k'·'2ax'처럼 쓰고 SymPy 표기는 곱을 명시한다
    ('2a' → '2*a*x').
    """
    human: list[str] = []
    symbolic: list[str] = []
    for exp, coef in terms:
        if coef == 0:
            continue
        var_h = "" if exp == 0 else ("x" if exp == 1 else f"x^{exp}")
        var_s = "" if exp == 0 else ("x" if exp == 1 else f"x**{exp}")
        if isinstance(coef, str):
            digits = coef.rstrip("abcdefghijklmnopqrstuvwxyz")
            letters = coef[len(digits) :]
            body_h = f"{coef}{var_h}"
            factors = [f for f in (digits, letters, var_s) if f]
            body_s = "*".join(factors)
            negative = False
        else:
            mag = abs(coef)
            body_h = var_h if (mag == 1 and var_h) else f"{mag}{var_h}"
            body_s = var_s if (mag == 1 and var_s) else (f"{mag}*{var_s}" if var_s else str(mag))
            negative = coef < 0
        if not human:
            human.append(f"-{body_h}" if negative else body_h)
            symbolic.append(f"-{body_s}" if negative else body_s)
        else:
            human.append(f"{'-' if negative else '+'} {body_h}")
            symbolic.append(f"{'-' if negative else '+'} {body_s}")
    return " ".join(human), " ".join(symbolic)


def _find_coef_steps(p: int, const: int, coef: int, unknown: str, value: int) -> str:
    """'f'(p)의 값은 0이고, f'(p)의 값은 (일차식)이므로 (일차식) = 0에서 a = 값이다' — 함숫값 등식
    'f'(2) = 5'를 쓰지 않는다(위생 게이트가 f'(2)를 곱으로 읽는 오탐 — QUAL-13)."""
    expr = render_affine(const, coef, unknown)
    return (
        f"x = {p}에서 극값을 가지므로 f'({p})의 값은 0이고, f'({p})의 값은 {expr}이므로 "
        f"{expr} = 0에서 {unknown} = {value}이다."
    )


def _other_root_value_item(
    slot: str,
    frame_id: str,
    template: str,
    *,
    lead: int,
    r1: int,
    r2: int,
    c: int,
    pin: str,
    ask_kind: str,
) -> ShapeItem | None:
    """삼차 f(x) = lead x^3 + a x^2 + B x + C(a 미지)가 x = p에서 극값 — 다른 임계점의 극값.

    pin: "max"|"min" — 발문이 고정하는 임계점의 종류(그 종류는 발문에 쓰지 않는다).
    ask_kind: 묻는 극값의 종류 — 고정한 점의 *반대* 종류여야 한다(묻는 극값은 고정점이 아니다).
    """
    parts = _cubic_a_parts(lead, r1, r2)
    if parts is None or pin == ask_kind:
        return None
    a, b = parts
    if a == 0:
        return None  # 미지 계수가 0이면 'ax^2' 항이 사라져 발문과 검산이 어긋난다
    poly: Poly = tuple((e, k) for e, k in ((3, lead), (2, a), (1, b), (0, c)) if k)
    fn = _analyze(poly)
    if fn is None or len(fn.kinds) != 2:
        return None
    p = next(r for r, k in fn.kinds.items() if k == pin)
    q = next(r for r, k in fn.kinds.items() if k == ask_kind)
    if 0 in (p, q):
        return None  # p = 0이면 f'(0) = B라 a가 정해지지 않고, q = 0이면 상수항이 곧 답이다
    value = eval_at(poly, q)
    if value == a:
        return None  # 정답과 미지 계수의 값이 같으면 판정기의 '묻는 상수' 추정이 흔들린다
    f_text, f_sym = _poly_with_unknown(((3, lead), (2, "a"), (1, b), (0, c)))
    d_text, _ = _poly_with_unknown(((2, 3 * lead), (1, "2a"), (0, b)))
    explanation = (
        f"f'(x) = {d_text}이다. "
        + _find_coef_steps(p, 3 * lead * p * p + b, 2 * p, "a", a)
        + f" 이때 {_explain(fn)} 따라서 {_KIND_KO[ask_kind]}은 x = {q}에서의 함숫값 {value}이다."
    )
    return _item(
        slot=slot,
        frame_id=frame_id,
        text=_fill(template, f_text, p=p, kind=_KIND_KO[ask_kind]),
        answer=value,
        conditions=(f"y = {f_sym}", f"Derivative({f_sym}, x).doit() = 0"),
        answer_map=(("x", str(q)), ("a", str(a)), ("y", str(value))),
        ptype=_OPT,
        explanation=explanation,
    )


def _cubic_other_root_frame(
    frame_id: str, template: str, seed: str, *, slot: str, pin: str, ask_kind: str
) -> Frame:
    combos = [
        (lead, r1, r2, c)
        for lead in _LEADS
        for r1 in range(-4, 4)
        for r2 in range(r1 + 1, 5)
        for c in _C_ALL
    ]

    def build(p: tuple[object, ...]) -> DiffItem | None:
        lead, r1, r2, c = (_i(v) for v in p)
        return _other_root_value_item(
            slot, frame_id, template, lead=lead, r1=r1, r2=r2, c=c, pin=pin, ask_kind=ask_kind
        )

    return Frame(frame_id, tuple(seeded_order(seed, combos)), build)


def _find_k_other_root_frame(
    frame_id: str, template: str, seed: str, *, slot: str, pin: str, ask_kind: str
) -> Frame:
    """삼차 f(x) = lead x^3 + a x^2 + B x + k(a·k 미지) — x = p에서 극값, 다른 쪽 극값이 V일 때 k.

    학생은 f'(p) = 0으로 a를 구하고, 나머지 임계점과 그 종류를 판정한 뒤 f(q) = V를 푼다. 종전
    틀은 임계점 둘을 발문이 다 주어 '큰 쪽이 극댓값' 대입만 남았다(4차 감사 R3 4건).
    """
    combos = [
        (lead, r1, r2, k)
        for lead in _LEADS
        for r1 in range(-3, 3)
        for r2 in range(r1 + 1, 4)
        for k in (-5, -3, -2, 2, 3, 4, 6)
    ]

    def build(p: tuple[object, ...]) -> DiffItem | None:
        lead, r1, r2, k = (_i(v) for v in p)
        parts = _cubic_a_parts(lead, r1, r2)
        if parts is None or pin == ask_kind:
            return None
        a, b = parts
        if a == 0:
            return None
        base: Poly = tuple((e, v) for e, v in ((3, lead), (2, a), (1, b)) if v)
        fn = _analyze(base)
        if fn is None or len(fn.kinds) != 2:
            return None
        pp = next(r for r, kd in fn.kinds.items() if kd == pin)
        q = next(r for r, kd in fn.kinds.items() if kd == ask_kind)
        if 0 in (pp, q):
            return None
        base_value = eval_at(base, q)
        value = base_value + k
        if k in (a, value):
            return None
        f_text, f_sym = _poly_with_unknown(((3, lead), (2, "a"), (1, b), (0, "k")))
        d_text, _ = _poly_with_unknown(((2, 3 * lead), (1, "2a"), (0, b)))
        k_side = render_affine(base_value, 1, "k")
        explanation = (
            f"f'(x) = {d_text}이다. "
            + _find_coef_steps(pp, 3 * lead * pp * pp + b, 2 * pp, "a", a)
            + f" 이때 {_explain(fn)} 따라서 {_KIND_KO[ask_kind]}은 x = {q}에서 생기고, "
            f"f({q})의 값은 {k_side}이다. {k_side} = {value}에서 k = {k}이다."
        )
        return _item(
            slot=slot,
            frame_id=frame_id,
            text=_fill(template, f_text, p=pp, kind=_KIND_KO[ask_kind], v=value),
            answer=k,
            conditions=(f"Derivative({f_sym}, x).doit() = 0", f"{f_sym} = {value}"),
            answer_map=(("x", str(q)), ("k", str(k)), ("a", str(a))),
            ptype=_SOLVE,
            explanation=explanation,
        )

    return Frame(frame_id, tuple(seeded_order(seed, combos)), build)


def _quartic_k_parts(lead: int, p: int, m: int, q: int) -> tuple[int, int, int] | None:
    """f' = 4·lead(x - p)(x - m)(x - q)인 사차 f = lead x^4 + A x^3 + B x^2 + k x + D의
    (A, B, k).
    """
    s1, s2, s3 = p + m + q, p * m + m * q + p * q, p * m * q
    if (4 * lead * s1) % 3:
        return None
    return -(4 * lead * s1) // 3, 2 * lead * s2, -4 * lead * s3


def _quartic_k_frame(
    frame_id: str,
    template: str,
    seed: str,
    *,
    slot: str,
    leads: tuple[int, ...],
    pin: str,
    ask: str,
) -> Frame:
    """비대칭 사차 f(x) = lead x^4 + A x^3 + B x^2 + kx + D(k 미지)가 x = (고정점)에서 극값.

    pin: "outer"(바깥 임계점 하나를 고정) | "middle"(가운데 임계점을 고정).
    ask: "middle"(가운데 극값 하나의 값) | "outer-smaller"/"outer-larger"(바깥 두 극값 중
    작은/큰 값). 학생은 f'(고정점) = 0으로 k를 구하고, 삼차 도함수를 고정점으로 나눠 나머지 두
    임계점을 찾고, 부호 변화로 종류를 판정한다. 임계점이 비대칭이라 복이차 완전제곱 우회로가 없다.
    """
    # 최고차항 계수 ±3은 f'의 x^3·x^2 계수 조건(3으로 나누어떨어짐)을 늘 만족해 임계점 조합이 넓다
    # (±1만 쓰면 같은 도함수가 상수항만 바꿔 되풀이된다).
    combos = [
        (lead, pp, m, q, d)
        for lead in leads
        for pp in range(-4, 3)
        for m in range(pp + 1, 4)
        for q in range(m + 1, 5)
        if m - pp != q - m
        for d in (-5, -2, 1, 3, 6)
    ]

    def build(p: tuple[object, ...]) -> DiffItem | None:
        lead, pp, m, q, d = (_i(v) for v in p)
        parts = _quartic_k_parts(lead, pp, m, q)
        if parts is None:
            return None
        a3, b2, k = parts
        if k == 0 or max(abs(a3), abs(b2), abs(k)) > 72:
            return None
        poly: Poly = tuple((e, v) for e, v in ((4, lead), (3, a3), (2, b2), (1, k), (0, d)) if v)
        fn = _analyze(poly)
        if fn is None or len(fn.kinds) != 3:
            return None
        pinned = m if pin == "middle" else (pp if (pp + q) % 2 else q)
        if pinned == 0:
            return None
        if ask == "middle":
            if pinned == m:
                return None
            targets = [m]
        else:
            targets = [pp, q]
        values = {r: eval_at(poly, r) for r in targets}
        if ask == "middle":
            target = m
        else:
            if len(set(values.values())) != 2:
                return None
            chooser = min if ask == "outer-smaller" else max
            target = chooser(targets, key=lambda r: values[r])
        if target == pinned:
            return None  # 답하는 극값은 고정점이 아닌 쪽이다(다른 임계점을 학생이 찾아야 한다)
        value = values[target]
        if value == k:
            return None
        kind = _KIND_KO[fn.kinds[target]]
        f_text, f_sym = _poly_with_unknown(((4, lead), (3, a3), (2, b2), (1, "k"), (0, d)))
        d_text, _ = _poly_with_unknown(((3, 4 * lead), (2, 3 * a3), (1, 2 * b2), (0, "k")))
        const = 4 * lead * pinned**3 + 3 * a3 * pinned**2 + 2 * b2 * pinned
        if ask == "middle":
            tail = f"따라서 {kind}은 x = {target}에서의 함숫값 {value}이다."
        else:
            listed = ", ".join(f"x = {r}에서 {values[r]}" for r in sorted(targets))
            size = "작은" if ask == "outer-smaller" else "큰"
            tail = f"두 {kind}은 {listed}이고, 이 중 {size} 값은 {value}이다."
        explanation = (
            f"f'(x) = {d_text}이다. "
            + _find_coef_steps(pinned, const, 1, "k", k)
            + f" 이때 {_explain(fn)} {tail}"
        )
        return _item(
            slot=slot,
            frame_id=frame_id,
            text=_fill(
                template,
                f_text,
                p=pinned,
                kind=kind,
                size="작은" if ask == "outer-smaller" else "큰",
            ),
            answer=value,
            conditions=(f"y = {f_sym}", f"Derivative({f_sym}, x).doit() = 0"),
            answer_map=(("x", str(target)), ("k", str(k)), ("y", str(value))),
            ptype=_OPT,
            explanation=explanation,
        )

    return Frame(frame_id, tuple(seeded_order(seed, combos)), build)


def _quartic_asym_x_frame(
    frame_id: str,
    template: str,
    seed: str,
    *,
    slot: str,
    leads: tuple[int, ...],
    role: str,
    pick: str,
) -> Frame:
    """비대칭 사차함수의 극대·극소 x좌표(규칙 B3 — selection 필수). 종전 우함수(복이차)는
    (x^2 - p^2)^2 완전제곱으로 극값 위치가 바로 나왔다(4차 감사 R3·R5 8건)."""
    combos = [
        (lead, pp, m, q, d)
        for lead in leads
        for pp in range(-4, 3)
        for m in range(pp + 1, 4)
        for q in range(m + 1, 5)
        if m - pp != q - m
        for d in (-5, -2, 1, 3, 6)
    ]

    def build(p: tuple[object, ...]) -> DiffItem | None:
        lead, pp, m, q, d = (_i(v) for v in p)
        poly = _quartic_asym(lead, pp, m, q, d)
        if poly is None or max(abs(k) for _, k in poly) > 72:
            return None
        fn = _analyze(poly)
        if fn is None or len(fn.kinds) != 3:
            return None
        return _x_item(slot, frame_id, template, fn, role=role, pick=pick)

    return Frame(frame_id, tuple(seeded_order(seed, combos)), build)


# ──────────────────────────────────────────────────────────────────────────
# 슬롯별 틀
# ──────────────────────────────────────────────────────────────────────────
def _cubic_frame(
    frame_id: str,
    template: str,
    seed: str,
    *,
    role: str,
    pick: str | None,
    slot: str,
    leads: Sequence[int] = _LEADS,
) -> Frame:
    def build(p: tuple[object, ...]) -> DiffItem | None:
        poly = _cubic(_i(p[0]), _i(p[1]), _i(p[2]), _i(p[3]))
        fn = _analyze(poly) if poly is not None else None
        if fn is None:
            return None
        return _x_item(slot, frame_id, template, fn, role=role, pick=pick)

    return Frame(frame_id, _cubic_pool(seed, leads, _C_ALL), build)


def _cubic_interval_frame(
    frame_id: str, template: str, seed: str, *, slot: str, direction: str
) -> Frame:
    """f' = 3L(2x - p)(2x - q) (p 홀수·q = p + 2) — 근 p/2, q/2 사이의 정수는 (p + 1)/2 하나뿐.

    f(x) = L(4x^3 - 3(p + q)x^2 + 3pq x) + c. L > 0이면 두 근 사이가 감소 범위, L < 0이면
    증가 범위다.
    """
    leads = (1, 2) if direction == "neg" else (-1, -2)
    combos = [(lead, p0, c) for lead in leads for p0 in (-5, -3, -1, 1, 3) for c in _C_ALL]

    def build(p: tuple[object, ...]) -> DiffItem | None:
        lead, p0, c = _i(p[0]), _i(p[1]), _i(p[2])
        q0 = p0 + 2
        terms = ((3, 4 * lead), (2, -3 * lead * (p0 + q0)), (1, 3 * lead * p0 * q0), (0, c))
        poly: Poly = tuple((e, k) for e, k in terms if k)
        if max(abs(k) for _, k in poly) > 48:
            return None
        return _interval_item(slot, frame_id, template, poly, roots=(p0, q0), direction=direction)

    return Frame(frame_id, tuple(seeded_order(seed, combos)), build)


def _rep_frames() -> list[Frame]:
    slot = "representative"
    return [
        _cubic_frame(
            "rep-turning-point-larger",
            "삼차함수 f(x) = {f}의 증가·감소가 바뀌는 점의 x좌표 중 큰 값을 구하시오.",
            "p3-shape:rep1",
            role="turn",
            pick="largest",
            slot=slot,
        ),
        _cubic_frame(
            "rep-local-max-x",
            "삼차함수 f(x) = {f}{ga} 극대가 되는 x좌표를 구하시오.",
            "p3-shape:rep2",
            role="max",
            pick=None,
            slot=slot,
        ),
        _cubic_frame(
            "rep-local-min-x",
            "삼차함수 f(x) = {f}{ga} 극소가 되는 x좌표를 구하시오.",
            "p3-shape:rep3",
            role="min",
            pick=None,
            slot=slot,
        ),
        # 극값의 값 — 임계점 하나만 고정(규칙 C3)하고 계수 a를 미지로 둔다. 다른 임계점과 종류는
        # 학생이 도함수로 찾는다(4차 감사: 두 위치를 다 주면 대입·대소 비교로 끝났다).
        _cubic_other_root_frame(
            "rep-other-extremum-min-value",
            "함수 f(x) = {f}{ga} x = {p}에서 극값을 가질 때, f(x)의 {kind}을 구하시오. "
            "(단, a는 상수이다.)",
            "p3-shape:rep4",
            slot=slot,
            pin="max",
            ask_kind="min",
        ),
        _cubic_other_root_frame(
            "rep-other-extremum-max-value",
            "삼차함수 f(x) = {f}{neun} x = {p}에서 극값을 갖는다. f(x)의 {kind}을 구하시오. "
            "(단, a는 상수이다.)",
            "p3-shape:rep5",
            slot=slot,
            pin="min",
            ask_kind="max",
        ),
        _cubic_interval_frame(
            "rep-decreasing-integer",
            # 3차 감사 bad_tag — 종전 발문은 f'(x) < 0을 직접 줘 증감 판정 없이 이차부등식만 남았다.
            "함수 f(x) = {f}{ga} 감소하는 x의 값의 범위에 속하는 정수는 하나뿐이다. "
            "그 정수를 구하시오.",
            "p3-shape:rep6",
            slot=slot,
            direction="neg",
        ),
    ]


def _basic_frames() -> list[Frame]:
    slot = "basic"
    return [
        _cubic_frame(
            "basic-turning-point-smaller",
            "삼차함수 f(x) = {f}의 증가·감소가 바뀌는 점의 x좌표 중 작은 값을 구하시오.",
            "p3-shape:bas1",
            role="turn",
            pick="smallest",
            slot=slot,
        ),
        _cubic_frame(
            "basic-extremum-x-larger",
            "함수 f(x) = {f}{ga} 극값을 갖는 x좌표 중 큰 값을 구하시오.",
            "p3-shape:bas2",
            role="turn",
            pick="largest",
            slot=slot,
        ),
        _cubic_frame(
            "basic-extremum-x-smaller",
            "곡선 y = {f}{ga} 극값을 갖는 x좌표 중 작은 값을 구하시오.",
            "p3-shape:bas3",
            role="turn",
            pick="smallest",
            slot=slot,
        ),
        _cubic_interval_frame(
            "basic-increasing-integer",
            "함수 f(x) = {f}{ga} 증가하는 x의 값의 범위에 속하는 정수는 하나뿐이다. "
            "그 정수를 구하시오.",
            "p3-shape:bas4",
            slot=slot,
            direction="pos",
        ),
        _cubic_other_root_frame(
            "basic-other-extremum-min-value",
            "함수 y = {f}{ga} x = {p}에서 극값을 가질 때, 이 함수의 {kind}을 구하시오. "
            "(단, a는 상수이다.)",
            "p3-shape:bas5",
            slot=slot,
            pin="max",
            ask_kind="min",
        ),
        _cubic_other_root_frame(
            "basic-other-extremum-max-value",
            "함수 f(x) = {f}에 대하여 방정식 f'(x) = 0의 한 근이 x = {p}이다. f(x)의 {kind}을 "
            "구하시오. (단, a는 상수이다.)",
            "p3-shape:bas6",
            slot=slot,
            pin="min",
            ask_kind="max",
        ),
    ]


# ── 응용: 미지수 구하기·사차함수 ────────────────────────────────────────────
def _linear_ab(ca: int, cb: int, const: int) -> str:
    """'2a + b + 3'·'-a + 4b - 2' — a·b에 대한 일차식 표기(계수 1·0 처리·이중 부호 금지)."""
    parts: list[str] = []
    for coef, name in ((ca, "a"), (cb, "b"), (const, "")):
        if coef == 0:
            continue
        mag = abs(coef)
        body = name if (mag == 1 and name) else f"{mag}{name}"
        if not parts:
            parts.append(f"-{body}" if coef < 0 else body)
        else:
            parts.append(f"{'-' if coef < 0 else '+'} {body}")
    return " ".join(parts) if parts else "0"


def _find_ab_item(
    slot: str,
    frame_id: str,
    template: str,
    *,
    lead: int,
    a: int,
    b: int,
    c: int,
    r: int,
    ask: str,
    want: str | None,
) -> ShapeItem | None:
    """f(x) = lead·x^3 + a x^2 + b x + c(a·b 미지수)가 x = r에서 극값 v — 상수 `ask`를 구한다.

    3차 감사(2026-10) bad_tag 처분 — 종전 틀은 미지수가 하나라 '극값 v'를 주면 f(r) = v 대입만으로
    상수가 정해져 f'(r) = 0이 풀이에 쓰이지 않았다(우회로 판정기 T-value-determines). 이제 a·b
    둘 다 미지수라 f'(r) = 0과 f(r) = v를 **연립**해야 답이 나온다.
    """
    poly: Poly = tuple((e, k) for e, k in ((3, lead), (2, a), (1, b), (0, c)) if k)
    fn = _analyze(poly)
    if fn is None:
        return None
    kind = fn.kinds.get(r)
    if kind is None or (want is not None and kind != want):
        return None
    if a == b or 0 in (a, b, r):
        return None
    value = eval_at(poly, r)
    # f'(r) = 3·lead·r^2 + 2r·a + b = 0 · f(r) = lead·r^3 + r^2·a + r·b + c = v
    eq1 = _linear_ab(2 * r, 1, 3 * lead * r * r)
    eq2 = _linear_ab(r * r, r, lead * r**3 + c - value)
    lead_text = "" if lead == 1 else ("-" if lead == -1 else str(lead))
    tail_c = _signed(c, "") if c else ""
    base_text = f"{lead_text}x^3 + ax^2 + bx {tail_c}".rstrip()
    base_sym = f"({lead})*x**3 + a*x**2 + b*x + ({c})"
    answer = a if ask == "a" else b
    deriv_text = f"{3 * lead if abs(3 * lead) != 1 else ''}x^2 + 2ax + b"
    explanation = (
        f"f'(x) = {deriv_text}이다. x = {r}에서 극값을 가지므로 f'({r})의 값은 0이고, "
        f"f'({r})의 값은 {eq1}이므로 {eq1} = 0이다. 또 그 극값이 {value}이므로 f({r})의 값 "
        f"{with_eun_neun(_linear_ab(r * r, r, lead * r**3 + c))} {with_wa_gwa(value)} 같아야 하고, "
        f"{eq2} = 0이다. 두 식을 연립하면 a = {a}, b = {b}이다. 이때 {_explain(fn)} 따라서 "
        f"x = {r}에서 {_kind_word(kind)}을 갖는다."
    )
    return _item(
        slot=slot,
        frame_id=frame_id,
        text=_fill(
            template,
            base_text,
            r=r,
            v=value,
            veul=eul_reul(str(value)),
            kind=_kind_word(kind),
            p=ask,
        ),
        answer=answer,
        conditions=(_deriv_cond(base_sym, "="), f"{base_sym} = {value}"),
        answer_map=(
            ("x", str(r)),
            (ask, str(answer)),
            ("b" if ask == "a" else "a", str(b if ask == "a" else a)),
        ),
        ptype=_SOLVE,
        explanation=explanation,
    )


def _find_a_frame(frame_id: str, template: str, seed: str, *, slot: str, want: str) -> Frame:
    """f(x) = x^3 + a x^2 + b x + c가 x = r에서 극값 v를 갖는다 — c만 주고 a를 구한다.

    a·b 둘 다 미지수다(f'(r) = 0과 f(r) = v를 연립해야 정해진다).
    """
    combos = tuple(
        seeded_order(
            seed,
            [
                (a, r, c)
                for a in range(-6, 7)
                for r in (-3, -2, -1, 1, 2, 3)
                for c in (-5, -3, -2, 2, 3, 4, 6)
                if a != 0
            ],
        )
    )

    def build(p: tuple[object, ...]) -> DiffItem | None:
        a, r, c = _i(p[0]), _i(p[1]), _i(p[2])
        b = -3 * r * r - 2 * a * r  # f'(r) = 3r^2 + 2ar + b = 0
        if abs(b) > 40:
            return None
        return _find_ab_item(
            slot, frame_id, template, lead=1, a=a, b=b, c=c, r=r, ask="a", want=want
        )

    return Frame(frame_id, combos, build)


def _quartic_asym(a: int, p: int, m: int, q: int, c: int) -> Poly | None:
    """f' = 4a(x - p)(x - m)(x - q)인 사차함수 — 세 임계점이 비대칭이라 바깥 두 극값의 값이 다르다.

    계수가 정수가 아니거나 너무 크면 None. (f = a x^4 - (4a s1/3) x^3 + 2a s2 x^2 - 4a s3 x + c)
    """
    s1, s2, s3 = p + m + q, p * m + m * q + p * q, p * m * q
    if (4 * a * s1) % 3:
        return None
    terms = [(4, a), (3, -(4 * a * s1) // 3), (2, 2 * a * s2), (1, -4 * a * s3), (0, c)]
    if max(abs(k) for _, k in terms) > 120:
        return None
    return tuple((e, k) for e, k in terms if k != 0)


def _applied_frames() -> list[Frame]:
    slot = "applied"
    return [
        _find_a_frame(
            "applied-find-a-local-min-value",
            "함수 f(x) = {f}{ga} x = {r}에서 {kind} {v}{veul} 가질 때, 상수 {p}의 값을 구하시오. "
            "(단, a, b는 상수이다.)",
            "p3-shape:app1",
            slot=slot,
            want="min",
        ),
        _find_k_other_root_frame(
            "applied-find-constant-from-other-local-max",
            "함수 f(x) = {f}{ga} x = {p}에서 극값을 갖고 f(x)의 {kind}이 {v}일 때, 상수 k의 값을 "
            "구하시오. (단, a는 상수이다.)",
            "p3-shape:app2",
            slot=slot,
            pin="min",
            ask_kind="max",
        ),
        # 사차 극값 x좌표 — 비대칭 임계점(복이차 완전제곱 우회로 없음 · 4차 감사).
        _quartic_asym_x_frame(
            "applied-asym-quartic-min-x-larger",
            "사차함수 f(x) = {f}{ga} 극소가 되는 x좌표 중 큰 값을 구하시오.",
            "p3-shape:app3",
            slot=slot,
            leads=(1, 3),
            role="min",
            pick="largest",
        ),
        _quartic_asym_x_frame(
            "applied-asym-quartic-max-x-smaller",
            "사차함수 f(x) = {f}{ga} 극대가 되는 x좌표 중 작은 값을 구하시오.",
            "p3-shape:app4",
            slot=slot,
            leads=(-1, -3),
            role="max",
            pick="smallest",
        ),
        _quartic_k_frame(
            "applied-quartic-k-middle-extremum-value",
            "사차함수 f(x) = {f}{ga} x = {p}에서 극값을 가질 때, f(x)의 {kind}을 구하시오. "
            "(단, k는 상수이다.)",
            "p3-shape:app5",
            slot=slot,
            leads=(1, 3),
            pin="outer",
            ask="middle",
        ),
        _find_a_frame(
            "applied-find-a-local-max-value",
            "곡선 y = {f}{ga} x = {r}에서 {kind} {v}{veul} 가질 때, 상수 {p}의 값을 구하시오. "
            "(단, a, b는 상수이다.)",
            "p3-shape:app6",
            slot=slot,
            want="max",
        ),
    ]


# ── 오개념 유발: 객관식 — f'(a) = 0이지만 극값이 아닌 점 ────────────────────
def _flat_frame(
    frame_id: str,
    template: str,
    seed: str,
    *,
    slot: str,
    role: str,
    factored: bool = False,
) -> Frame:
    """사차함수 a x^4 + b x^3 + c — 임계점 0(평평)·q(극값). 객관식은 정답 q·오답 0(오개념)."""

    def build(p: tuple[object, ...]) -> DiffItem | None:
        a, b, c = _i(p[0]), _i(p[1]), _i(p[2])
        made = _quartic_flat(a, b, 0 if factored else c)
        if made is None:
            return None
        poly, q = made
        if factored and (-b) % a:
            return None
        fn = _analyze(poly)
        if fn is None or tuple(fn.kinds) != (q,) or fn.flat_roots != (0,):
            return None
        kind = fn.kinds[q]
        if role in ("max", "min") and kind != role:
            return None
        if factored:
            k = -b // a
            lead = "" if a == 1 else "-" if a == -1 else str(a)
            fn_text = f"{lead}x^3(x {'-' if k > 0 else '+'} {abs(k)})"
        else:
            fn_text = fn.text
        selection = _selection(fn, q)
        if selection is None:
            return None
        correct = q
        # 오답: 평평한 임계점 0(오개념 — f'(0) = 0이니 극값이라는 단정) · 필러 2개(임계점 아님).
        fillers = [v for v in (-q, 2 * q, q + 1, q - 1, -2 * q) if v not in (0, q, -q)]
        used = [correct, 0, -q]
        extra = next((v for v in fillers if v not in used), None)
        if extra is None:
            return None
        try:
            choices, answer, distractors = build_choices(
                [
                    ChoiceEntry(str(correct), is_correct=True, sort_key=float(correct)),
                    ChoiceEntry("0", _KEBAB, sort_key=0.0),
                    ChoiceEntry(str(-q), sort_key=float(-q)),
                    ChoiceEntry(str(extra), sort_key=float(extra)),
                ],
                shuffle_seed=f"{frame_id}:{a}:{b}:{c}",
            )
        except ValueError:
            return None
        return _item(
            slot=slot,
            frame_id=frame_id,
            text=_fill(template, fn_text, kind="극대" if kind == "max" else "극소"),
            answer=int(answer),
            conditions=_deriv_cond(fn.sym, "="),
            answer_map=(("x", answer),),
            ptype=_OPT,
            explanation=(f"{_explain(fn)} 따라서 f'(x) = 0의 근 중 극값을 갖는 x좌표는 {q}뿐이다."),
            selection=selection,
            choices=choices,
            distractors=distractors,
        )

    c_values: tuple[int, ...] = (0,) if factored else (-6, -4, -3, -2, -1, 1, 2, 3, 4, 5)
    return Frame(frame_id, _quartic_flat_pool(seed, c_values), build)


def _misconception_frames() -> list[Frame]:
    slot = "misconception_trigger"
    return [
        _flat_frame(
            "mc-extremum-x",
            "함수 f(x) = {f}{ga} 극값을 갖는 x좌표는?",
            "p3-shape:mc1",
            slot=slot,
            role="any",
        ),
        _flat_frame(
            "mc-extremum-x-factored",
            "함수 f(x) = {f}{ga} 극값을 갖는 x좌표는?",
            "p3-shape:mc2",
            slot=slot,
            role="any",
            factored=True,
        ),
        _flat_frame(
            "mc-turning-point",
            "곡선 y = {f}에서 증가·감소가 바뀌는 점의 x좌표는?",
            "p3-shape:mc3",
            slot=slot,
            role="any",
        ),
        _flat_frame(
            "mc-derivative-zero-which-extremum",
            "방정식 f'(x) = 0의 해 중에서 함수 f(x) = {f}{ga} 극값을 갖는 x좌표는?",
            "p3-shape:mc4",
            slot=slot,
            role="any",
        ),
        _flat_frame(
            "mc-local-kind-x",
            "사차함수 f(x) = {f}{ga} {kind}가 되는 x좌표는?",
            "p3-shape:mc5",
            slot=slot,
            role="any",
        ),
    ]


# ── 진단 ────────────────────────────────────────────────────────────────
def _flat_x_frame(
    frame_id: str, template: str, seed: str, *, slot: str, role: str, pick: str | None
) -> Frame:
    def build(p: tuple[object, ...]) -> DiffItem | None:
        made = _quartic_flat(_i(p[0]), _i(p[1]), _i(p[2]))
        if made is None:
            return None
        fn = _analyze(made[0])
        if fn is None or tuple(fn.kinds) != (made[1],) or fn.flat_roots != (0,):
            return None
        return _x_item(slot, frame_id, template, fn, role=role, pick=pick)

    return Frame(frame_id, _quartic_flat_pool(seed, (-6, -4, -3, -2, -1, 1, 2, 3, 4, 5)), build)


def _flat_judged_frame(frame_id: str, template: str, seed: str, *, slot: str) -> Frame:
    """사차 a x^4 + b x^3 + c — f'(x) = 0의 두 근(0과 q)을 고정하고 *극값*을 묻는다.

    x = 0은 f'(0) = 0이지만 부호가 바뀌지 않아 극값이 아니다 — 학생은 두 근 중 어느 것이 극값인지
    판정해야 한다(임계점 = 극값 오개념을 진단). 1차 은행은 'x = q에서 극값을 갖는다'고 위치를 알려
    대입만 남았다(2차 감사).
    """

    def build(p: tuple[object, ...]) -> DiffItem | None:
        made = _quartic_flat(_i(p[0]), _i(p[1]), _i(p[2]))
        if made is None:
            return None
        fn = _analyze(made[0])
        if fn is None or tuple(fn.kinds) != (made[1],) or fn.flat_roots != (0,):
            return None
        return _judged_value_item(slot, frame_id, template, fn, word="any")

    return Frame(frame_id, _quartic_flat_pool(seed, (-6, -4, -3, -2, -1, 1, 2, 3, 4, 5)), build)


def _diagnostic_frames() -> list[Frame]:
    slot = "diagnostic"
    return [
        _flat_x_frame(
            "diag-critical-but-not-turning",
            "함수 f(x) = {f}에 대하여 f'(x) = 0이지만 증가·감소가 바뀌지 않는 x의 값을 구하시오.",
            "p3-shape:dia1",
            slot=slot,
            role="flat",
            pick=None,
        ),
        _cubic_frame(
            "diag-increase-to-decrease-x",
            "함수 f(x) = {f}{ga} 증가하다가 감소로 바뀌는 점의 x좌표를 구하시오.",
            "p3-shape:dia2",
            role="max",
            pick=None,
            slot=slot,
        ),
        _cubic_frame(
            "diag-decrease-to-increase-x",
            "곡선 y = {f}{ga} 감소하다가 증가로 바뀌는 점의 x좌표를 구하시오.",
            "p3-shape:dia3",
            role="min",
            pick=None,
            slot=slot,
        ),
        _flat_x_frame(
            "diag-single-extremum-x",
            "사차함수 f(x) = {f}{ga} 극값을 갖는 x좌표를 구하시오.",
            "p3-shape:dia4",
            slot=slot,
            role="turn",
            pick=None,
        ),
        _flat_judged_frame(
            "diag-extremum-value-among-critical-points",
            "사차함수 f(x) = {f}에 대하여 방정식 f'(x) = 0의 실근은 {pins}이다. f(x)의 극값을 "
            "구하시오.",
            "p3-shape:dia5",
            slot=slot,
        ),
        _cubic_interval_frame(
            "diag-decreasing-integer-curve",
            "곡선 y = {f}에서 x의 값이 커질 때 y의 값이 작아지는 x의 값의 범위에 속하는 "
            "정수는 하나뿐이다. 그 정수를 구하시오.",
            "p3-shape:dia6",
            slot=slot,
            direction="neg",
        ),
    ]


# ── 숙련도 확인 ──────────────────────────────────────────────────────────
def _find_b_quartic_frame(frame_id: str, template: str, seed: str, *, slot: str) -> Frame:
    """f(x) = x^4 + a x^3 + b가 x = q에서 극솟값 v — a(미분계수 조건)를 먼저 구해야 b가 정해진다.

    3차 감사(2026-10) bad_tag 처분 — 종전 틀은 a만 미지수라 f(q) = v 대입만으로 a가 정해졌다
    (f'(q) = 0이 풀이에 불요). 상수항 b를 함께 미지수로 두고 b를 묻는다.
    """
    combos = tuple(
        seeded_order(
            seed,
            [(q, c) for q in (-6, -3, 3, 6) for c in (-6, -5, -3, -2, 2, 3, 4, 5)],
        )
    )

    def build(p: tuple[object, ...]) -> DiffItem | None:
        q, c = _i(p[0]), _i(p[1])
        if (4 * q) % 3:
            return None
        a = -4 * q // 3
        poly: Poly = tuple((e, k) for e, k in ((4, 1), (3, a), (0, c)) if k)
        fn = _analyze(poly)
        if fn is None or fn.kinds.get(q) != "min":
            return None
        base_sym = "x**4 + a*x**3 + b"
        value = eval_at(poly, q)
        a_eq = render_poly(((1, 3 * q * q), (0, 4 * q**3)), "a")
        known = q**4 + a * q**3
        explanation = (
            f"f'(x) = 4x^3 + 3ax^2이다. x = {q}에서 극값을 가지므로 f'({q})의 값은 0이고, "
            f"f'({q})의 값은 {a_eq}이므로 {a_eq} = 0에서 a = {a}이다. 이때 {_explain(fn)} "
            f"따라서 x = {q}에서 극솟값을 갖고, 그 값은 f({q})의 값 "
            f"{render_poly(((1, 1), (0, known)), 'b')}"
            f"이다. {render_poly(((1, 1), (0, known)), 'b')} = {value}에서 b = {c}이다."
        )
        return _item(
            slot=slot,
            frame_id=frame_id,
            text=_fill(
                template,
                "x^4 + ax^3 + b",
                r=q,
                v=value,
                veul=eul_reul(str(value)),
                kind=_kind_word("min"),
                p="b",
            ),
            answer=c,
            conditions=(_deriv_cond(base_sym, "="), f"{base_sym} = {value}"),
            answer_map=(("x", str(q)), ("b", str(c)), ("a", str(a))),
            ptype=_SOLVE,
            explanation=explanation,
        )

    return Frame(frame_id, combos, build)


def _find_b_cubic_frame(frame_id: str, template: str, seed: str, *, slot: str) -> Frame:
    """f(x) = -x^3 + a x^2 + b x + c가 x = r에서 극값 v — a·b 미지수, b를 구한다."""
    combos = tuple(
        seeded_order(
            seed,
            [
                (a, r, c)
                for a in (-6, -3, -2, 2, 3, 6)
                for r in (-3, -2, -1, 1, 2, 3)
                for c in (-4, -2, 1, 3, 5)
            ],
        )
    )

    def build(p: tuple[object, ...]) -> DiffItem | None:
        a, r, c = _i(p[0]), _i(p[1]), _i(p[2])
        b = 3 * r * r - 2 * a * r  # f'(r) = -3r^2 + 2ar + b = 0
        if abs(b) > 40:
            return None
        return _find_ab_item(
            slot, frame_id, template, lead=-1, a=a, b=b, c=c, r=r, ask="b", want=None
        )

    return Frame(frame_id, combos, build)


def _mastery_frames() -> list[Frame]:
    slot = "mastery_check"
    return [
        _find_b_cubic_frame(
            "mastery-find-b-extremum-value",
            "함수 f(x) = {f}{ga} x = {r}에서 {kind} {v}{veul} 가질 때, 상수 {p}의 값을 구하시오. "
            "(단, a, b는 상수이다.)",
            "p3-shape:mas1",
            slot=slot,
        ),
        _find_b_quartic_frame(
            "mastery-find-b-quartic-local-min",
            "사차함수 f(x) = {f}{ga} x = {r}에서 {kind} {v}{veul} 가질 때, "
            "상수 {p}의 값을 구하시오. (단, a, b는 상수이다.)",
            "p3-shape:mas2",
            slot=slot,
        ),
        _find_k_other_root_frame(
            "mastery-find-constant-from-other-local-min",
            "함수 y = {f}{neun} x = {p}에서 극값을 갖는다. 이 함수의 {kind}이 {v}일 때, 상수 k의 "
            "값을 구하시오. (단, a는 상수이다.)",
            "p3-shape:mas3",
            slot=slot,
            pin="max",
            ask_kind="min",
        ),
        _quartic_asym_x_frame(
            "mastery-asym-quartic-min-x-smaller",
            "사차함수 f(x) = {f}{ga} 극소가 되는 x좌표 중 작은 값을 구하시오.",
            "p3-shape:mas4",
            slot=slot,
            leads=(1, 3),
            role="min",
            pick="smallest",
        ),
        _quartic_asym_x_frame(
            "mastery-asym-quartic-max-x-larger",
            "곡선 y = {f}{ga} 극대가 되는 x좌표 중 큰 값을 구하시오.",
            "p3-shape:mas5",
            slot=slot,
            leads=(-1, -3),
            role="max",
            pick="largest",
        ),
        _quartic_k_frame(
            "mastery-quartic-k-compare-outer-minima",
            "사차함수 f(x) = {f}{neun} x = {p}에서 극값을 갖는다. 두 {kind} 중 {size} 값을 "
            "구하시오. (단, k는 상수이다.)",
            "p3-shape:mas6",
            slot=slot,
            leads=(1, 3),
            pin="middle",
            ask="outer-smaller",
        ),
        _quartic_k_frame(
            "mastery-quartic-k-compare-outer-maxima",
            "사차함수 f(x) = {f}{ga} x = {p}에서 극값을 가질 때, 두 {kind} 중 {size} 값을 "
            "구하시오. (단, k는 상수이다.)",
            "p3-shape:mas7",
            slot=slot,
            leads=(-1, -3),
            pin="outer",
            ask="outer-larger",
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


class P3DiffGraphShapeGenerator(P3DiffSlotGenerator):
    """[12미적Ⅰ-02-08] 함수의 그래프의 개형 — 파생 판정 문항 슬롯 6종 결정론 생성기."""

    standard_code: ClassVar[str] = "[12미적Ⅰ-02-08]"
    concept_src_id: ClassVar[str] = "H:12미적Ⅰ02-08"
    unit_code: ClassVar[str] = "P3-CALC1-DIFF-GRAPH-SHAPE"
    slug_prefix: ClassVar[str] = "wm-p3-diff-graphshape"
    slot_difficulty: ClassVar[dict[str, float]] = {
        "representative": 2.5,
        "basic": 2.5,
        "applied": 3.5,
        "misconception_trigger": 3.5,
        "diagnostic": 3.0,
        "mastery_check": 4.0,
    }
    slot_count: ClassVar[int] = 12

    @classmethod
    def _slot_items(cls, slot: str, claimed: set[str]) -> list[DiffItem]:
        return round_robin_items(_SLOT_FRAMES[slot](), cls.slot_count, claimed=claimed)

    def _assemble(self, spec: EquivalenceSpec, item: DiffItem) -> CandidateProblem:
        """기반이 만든 후보에 `answer_selection`을 얹는다(기반 DiffItem에는 그 필드가 없다)."""
        candidate = super()._assemble(spec, item)
        selection = getattr(item, "answer_selection", None)
        if selection is None:
            return candidate
        return candidate.model_copy(update={"answer_selection": selection})
