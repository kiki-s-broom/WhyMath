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
    쓴다(정답이 유일).
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
    render_poly,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import (
    ChoiceEntry,
    DiffItem,
    Frame,
    P3DiffSlotGenerator,
    build_choices,
    round_robin_items,
    seeded_order,
)
from whymath_backend.lang.josa import eul_reul, eun_neun, i_ga
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


def _fmt(value: int) -> AnswerFormat:
    return AnswerFormat.자연수 if value > 0 else AnswerFormat.실수


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
    parts = [f"f'(x)는 {render_poly(fn.deriv)}이고 f'(x) = 0의 근은 x = {roots}이다."]
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


def _quartic_even(a: int, p: int, c: int) -> Poly:
    """a x^4 - 2a p^2 x^2 + c — f' = 4a x(x - p)(x + p) (임계점 -p, 0, p)."""
    terms = [(4, a), (2, -2 * a * p * p), (0, c)]
    return tuple((e, k) for e, k in terms if k != 0)


def _quartic_even_pool(seed: str) -> tuple[tuple[object, ...], ...]:
    combos = [
        (a, p, c)
        for a in (1, 2, -1, -2)
        for p in (1, 2, 3)
        for c in (-6, -4, -3, -2, -1, 1, 2, 3, 4, 5)
    ]
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
    slot: str, frame_id: str, template: str, fn: _Fn, *, direction: str
) -> ShapeItem | None:
    """증가(`pos`)·감소(`neg`) 구간에 속하는 정수가 **정확히 하나**인 문항(정답이 유일)."""
    d_expr = poly_to_sympy(fn.deriv)
    wanted = 1 if direction == "pos" else -1
    inside = [n for n in range(-40, 41) if int(sympy.sign(d_expr.subs(_X, n))) == wanted]
    if len(inside) != 1:
        return None
    n = inside[0]
    relation = ">" if direction == "pos" else "<"
    word = "증가" if direction == "pos" else "감소"
    return _item(
        slot=slot,
        frame_id=frame_id,
        text=_fill(template, fn.text),
        answer=n,
        conditions=_deriv_cond(fn.sym, relation),
        answer_map=(("x", str(n)),),
        ptype=_SOLVE,
        explanation=(
            f"{_explain(fn)} f'(x) {relation} 0이 되는 x의 범위는 {word}하는 구간의 양 끝을 "
            f"뺀 안쪽이고, 그 범위에 속하는 정수는 {n}뿐이다."
        ),
    )


def _kind_word(kind: str) -> str:
    return "극댓값" if kind == "max" else "극솟값"


def _value_item(
    slot: str,
    frame_id: str,
    template: str,
    fn: _Fn,
    *,
    r: int,
    word: str,
) -> ShapeItem | None:
    """x = r에서의 극값의 값(규칙 C3 — x 고정·answer_map에 x). word: "max"|"min"|"any"."""
    kind = fn.kinds.get(r)
    if kind is None or (word != "any" and kind != word):
        return None
    value = eval_at(fn.poly, r)
    return _item(
        slot=slot,
        frame_id=frame_id,
        text=_fill(template, fn.text, r=r),
        answer=value,
        conditions=(f"y = {fn.sym}", poly_to_sympy_str(fn.deriv) + " = 0"),
        answer_map=(("x", str(r)), ("y", str(value))),
        ptype=_OPT,
        explanation=(
            f"{_explain(fn)} x = {r}에서 {_kind_word(kind)}을 가지며 "
            f"그 값은 f({r})의 값 {value}이다."
        ),
    )


def _signed(value: int, tail: str) -> str:
    """부호를 앞에 두는 항 표기 — 예 (-9, "x") → '- 9x', (5, "") → '+ 5'."""
    return f"{'-' if value < 0 else '+'} {abs(value)}{tail}"


def _find_param_item(
    slot: str,
    frame_id: str,
    template: str,
    *,
    param: str,
    base_text: str,
    base_sym: str,
    r: int,
    value_at_r: int,
    kind: str,
    answer: int,
) -> ShapeItem:
    """x = r에서 극값 `value_at_r`를 갖도록 하는 미지수(param)를 구하는 문항 — 목록 조건(x·param).

    조건 2개: f'(x) = 0(임계점)과 f(x) = 값. 둘 다 x = r·param = answer에서 성립한다.
    """
    return _item(
        slot=slot,
        frame_id=frame_id,
        text=_fill(
            template,
            base_text,
            r=r,
            v=value_at_r,
            veul=eul_reul(str(value_at_r)),
            kind=_kind_word(kind),
            p=param,
        ),
        answer=answer,
        conditions=(
            _deriv_cond(base_sym, "="),
            f"{base_sym} = {value_at_r}",
        ),
        answer_map=(("x", str(r)), (param, str(answer))),
        ptype=_SOLVE,
        explanation=(
            f"x = {r}에서 {_kind_word(kind)}을 가지므로 f'({r})의 값은 0이다. "
            f"이 조건에서 {param}의 값은 "
            f"{answer}이고, 이때 f({r})의 값은 {value_at_r}이다."
        ),
    )


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


def _cubic_value_frame(
    frame_id: str, template: str, seed: str, *, slot: str, word: str, at: str
) -> Frame:
    """삼차함수의 극값의 값 — at: "low"(작은 임계점)·"high"(큰 임계점)에 x를 고정한다."""

    def build(p: tuple[object, ...]) -> DiffItem | None:
        poly = _cubic(_i(p[0]), _i(p[1]), _i(p[2]), _i(p[3]))
        fn = _analyze(poly) if poly is not None else None
        if fn is None:
            return None
        r = fn.roots[0] if at == "low" else fn.roots[-1]
        return _value_item(slot, frame_id, template, fn, r=r, word=word)

    return Frame(frame_id, _cubic_pool(seed, _LEADS, _C_ALL), build)


def _cubic_interval_frame(
    frame_id: str, template: str, seed: str, *, slot: str, direction: str
) -> Frame:
    """f' = 3a(x - r)(x - r - 2) — 두 근의 간격이 2라 f'의 부호가 하나의 구간 안에서 정수 1개."""

    def build(p: tuple[object, ...]) -> DiffItem | None:
        poly = _cubic(_i(p[0]), _i(p[1]), _i(p[2]), _i(p[3]))
        fn = _analyze(poly) if poly is not None else None
        if fn is None:
            return None
        return _interval_item(slot, frame_id, template, fn, direction=direction)

    # a > 0이면 두 근 사이가 감소 구간, a < 0이면 증가 구간 — 간격 2가 정수 하나를 보장한다.
    return Frame(frame_id, _cubic_pool(seed, _LEADS, _C_ALL, gap=2), build)


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
        _cubic_value_frame(
            "rep-value-local-min-at",
            "함수 f(x) = {f}{neun} x = {r}에서 극솟값을 갖는다. 이때의 극솟값을 구하시오.",
            "p3-shape:rep4",
            slot=slot,
            word="min",
            at="high",
        ),
        _cubic_value_frame(
            "rep-value-local-max-at",
            "곡선 y = {f}의 x = {r}에서의 극댓값을 구하시오.",
            "p3-shape:rep5",
            slot=slot,
            word="max",
            at="low",
        ),
        _cubic_interval_frame(
            "rep-decreasing-integer",
            "함수 f(x) = {f}에 대하여 f'(x) < 0을 만족시키는 정수 x는 하나뿐이다. "
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
            "함수 f(x) = {f}에 대하여 f'(x) > 0을 만족시키는 정수 x는 하나뿐이다. "
            "그 정수를 구하시오.",
            "p3-shape:bas4",
            slot=slot,
            direction="pos",
        ),
        _cubic_value_frame(
            "basic-value-local-min-curve",
            "곡선 y = {f}의 x = {r}에서의 극솟값을 구하시오.",
            "p3-shape:bas5",
            slot=slot,
            word="min",
            at="high",
        ),
        _cubic_value_frame(
            "basic-value-local-max-function",
            "함수 f(x) = {f}{neun} x = {r}에서 극댓값을 갖는다. 그 극댓값은 얼마인가?",
            "p3-shape:bas6",
            slot=slot,
            word="max",
            at="low",
        ),
        _cubic_value_frame(
            "basic-value-extremum-unspecified",
            "함수 f(x) = {f}{neun} x = {r}에서 극값을 갖는다. 그 극값을 구하시오.",
            "p3-shape:bas7",
            slot=slot,
            word="any",
            at="low",
        ),
    ]


# ── 응용: 미지수 구하기·사차함수 ────────────────────────────────────────────
def _find_a_frame(frame_id: str, template: str, seed: str, *, slot: str, want: str) -> Frame:
    """f(x) = x^3 + a x^2 + b x + c가 x = r에서 극값 v를 갖는다 — b·c는 주고 a를 구한다."""
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
        b = -3 * r * r - 2 * a * r  # f'(r) = 3r^2 + 2ar + b = 0이 되도록 b를 정한다.
        if b == 0 or abs(b) > 40:
            return None
        poly: Poly = tuple((e, k) for e, k in ((3, 1), (2, a), (1, b), (0, c)) if k)
        fn = _analyze(poly)
        if fn is None or fn.kinds.get(r) is None or fn.kinds[r] != want:
            return None
        tail_b = _signed(b, "x")
        tail_c = _signed(c, "")
        base_text = f"x^3 + ax^2 {tail_b} {tail_c}"
        base_sym = f"x**3 + a*x**2 + ({b})*x + ({c})"
        value = eval_at(poly, r)
        return _find_param_item(
            slot,
            frame_id,
            template,
            param="a",
            base_text=base_text,
            base_sym=base_sym,
            r=r,
            value_at_r=value,
            kind=want,
            answer=a,
        )

    return Frame(frame_id, combos, build)


def _find_k_frame(frame_id: str, template: str, seed: str, *, slot: str, want: str) -> Frame:
    """f(x) = (삼차 다항식) + k가 x = r에서 극값 v를 갖는다 — 상수항 k를 구한다."""
    combos = tuple(
        seeded_order(
            seed,
            [
                (a, r1, r2, k, idx)
                for a in _LEADS
                for r1 in range(-3, 3)
                for r2 in range(r1 + 1, 4)
                for k in (-5, -3, -2, 2, 3, 4, 6)
                for idx in (0, 1)
            ],
        )
    )

    def build(p: tuple[object, ...]) -> DiffItem | None:
        a, r1, r2, k, idx = (_i(v) for v in p)
        poly = _cubic(a, r1, r2, 0)
        fn0 = _analyze(poly) if poly is not None else None
        if poly is None or fn0 is None:
            return None
        r = fn0.roots[idx]
        if fn0.kinds.get(r) != want:
            return None
        value = eval_at(poly, r) + k
        base_text = render_poly(poly)
        base_sym = f"{poly_to_sympy_str(poly)} + k"
        return _find_param_item(
            slot,
            frame_id,
            template,
            param="k",
            base_text=f"{base_text} + k",
            base_sym=base_sym,
            r=r,
            value_at_r=value,
            kind=want,
            answer=k,
        )

    return Frame(frame_id, combos, build)


def _quartic_even_frame(
    frame_id: str, template: str, seed: str, *, slot: str, role: str, pick: str
) -> Frame:
    def build(p: tuple[object, ...]) -> DiffItem | None:
        fn = _analyze(_quartic_even(_i(p[0]), _i(p[1]), _i(p[2])))
        if fn is None:
            return None
        return _x_item(slot, frame_id, template, fn, role=role, pick=pick)

    return Frame(frame_id, _quartic_even_pool(seed), build)


def _quartic_even_value_frame(frame_id: str, template: str, seed: str, *, slot: str) -> Frame:
    """사차 우함수 a x^4 - 2a p^2 x^2 + c — x = 0에서의 극값(가운데 임계점)의 값."""

    def build(p: tuple[object, ...]) -> DiffItem | None:
        fn = _analyze(_quartic_even(_i(p[0]), _i(p[1]), _i(p[2])))
        if fn is None:
            return None
        return _value_item(slot, frame_id, template, fn, r=0, word="any")

    return Frame(frame_id, _quartic_even_pool(seed), build)


def _applied_frames() -> list[Frame]:
    slot = "applied"
    return [
        _find_a_frame(
            "applied-find-a-local-min-value",
            "함수 f(x) = {f}{ga} x = {r}에서 {kind} {v}{veul} 가질 때, 상수 {p}의 값을 구하시오.",
            "p3-shape:app1",
            slot=slot,
            want="min",
        ),
        _find_k_frame(
            "applied-find-constant-local-max-value",
            "함수 f(x) = {f}{ga} x = {r}에서 {kind} {v}{veul} 가질 때, 상수 {p}의 값을 구하시오.",
            "p3-shape:app2",
            slot=slot,
            want="max",
        ),
        _quartic_even_frame(
            "applied-quartic-min-x-larger",
            "사차함수 f(x) = {f}{ga} 극소가 되는 x좌표 중 큰 값을 구하시오.",
            "p3-shape:app3",
            slot=slot,
            role="min",
            pick="largest",
        ),
        _quartic_even_frame(
            "applied-quartic-max-x-smaller",
            "사차함수 f(x) = {f}{ga} 극대가 되는 x좌표 중 작은 값을 구하시오.",
            "p3-shape:app4",
            slot=slot,
            role="max",
            pick="smallest",
        ),
        _quartic_even_value_frame(
            "applied-quartic-value-at-origin",
            "사차함수 f(x) = {f}{neun} x = {r}에서 극값을 갖는다. 그 극값을 구하시오.",
            "p3-shape:app5",
            slot=slot,
        ),
        _find_a_frame(
            "applied-find-a-local-max-value",
            "곡선 y = {f}{ga} x = {r}에서 {kind} {v}{veul} 가질 때, 상수 {p}의 값을 구하시오.",
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


def _flat_value_frame(
    frame_id: str, template: str, seed: str, *, slot: str, word: str, at: str
) -> Frame:
    """사차 a x^4 + b x^3 + c — x = q(극값 점) 또는 x = 0(평평한 점 — 극값 아님 → None)에 고정."""

    def build(p: tuple[object, ...]) -> DiffItem | None:
        made = _quartic_flat(_i(p[0]), _i(p[1]), _i(p[2]))
        if made is None:
            return None
        fn = _analyze(made[0])
        if fn is None or tuple(fn.kinds) != (made[1],):
            return None
        r = made[1] if at == "extremum" else 0
        return _value_item(slot, frame_id, template, fn, r=r, word=word)

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
        _flat_value_frame(
            "diag-quartic-extremum-value-at",
            "사차함수 f(x) = {f}{neun} x = {r}에서 극값을 갖는다. 그 극값을 구하시오.",
            "p3-shape:dia5",
            slot=slot,
            word="any",
            at="extremum",
        ),
        _cubic_interval_frame(
            "diag-decreasing-integer-curve",
            "함수 f(x) = {f}의 도함수를 f'(x)라 할 때, f'(x) < 0을 만족시키는 정수 x는 "
            "하나뿐이다. 그 정수를 구하시오.",
            "p3-shape:dia6",
            slot=slot,
            direction="neg",
        ),
    ]


# ── 숙련도 확인 ──────────────────────────────────────────────────────────
def _find_a_quartic_frame(frame_id: str, template: str, seed: str, *, slot: str) -> Frame:
    """f(x) = x^4 + a x^3 + c가 x = q에서 극값 v — f'(q) = 4q^3 + 3a q^2 = 0이므로 a = -4q/3."""
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
        base_sym = f"x**4 + a*x**3 + ({c})"
        value = eval_at(poly, q)
        return _find_param_item(
            slot,
            frame_id,
            template,
            param="a",
            base_text=f"x^4 + ax^3 {_signed(c, '')}",
            base_sym=base_sym,
            r=q,
            value_at_r=value,
            kind="min",
            answer=a,
        )

    return Frame(frame_id, combos, build)


def _find_b_cubic_frame(frame_id: str, template: str, seed: str, *, slot: str) -> Frame:
    """f(x) = x^3 + a x^2 + b x가 x = r에서 극값 v — a를 주고 b를 구한다(f'(r) = 0)."""
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
        b = -3 * r * r - 2 * a * r
        if b == 0 or abs(b) > 40:
            return None
        poly: Poly = tuple((e, k) for e, k in ((3, 1), (2, a), (1, b), (0, c)) if k)
        fn = _analyze(poly)
        if fn is None:
            return None
        kind = fn.kinds.get(r)
        if kind is None:
            return None
        return _find_param_item(
            slot,
            frame_id,
            template,
            param="b",
            base_text=f"x^3 {_signed(a, 'x^2')} + bx {_signed(c, '')}",
            base_sym=f"x**3 + ({a})*x**2 + b*x + ({c})",
            r=r,
            value_at_r=eval_at(poly, r),
            kind=kind,
            answer=b,
        )

    return Frame(frame_id, combos, build)


def _mastery_frames() -> list[Frame]:
    slot = "mastery_check"
    return [
        _find_b_cubic_frame(
            "mastery-find-b-extremum-value",
            "함수 f(x) = {f}{ga} x = {r}에서 {kind} {v}{veul} 가질 때, 상수 {p}의 값을 구하시오.",
            "p3-shape:mas1",
            slot=slot,
        ),
        _find_a_quartic_frame(
            "mastery-find-a-quartic-local-min",
            "사차함수 f(x) = {f}{ga} x = {r}에서 {kind} {v}{veul} 가질 때, "
            "상수 {p}의 값을 구하시오.",
            "p3-shape:mas2",
            slot=slot,
        ),
        _find_k_frame(
            "mastery-find-constant-local-min-value",
            "곡선 y = {f}{ga} x = {r}에서 {kind} {v}{veul} 가질 때, 상수 {p}의 값을 구하시오.",
            "p3-shape:mas3",
            slot=slot,
            want="min",
        ),
        _quartic_even_frame(
            "mastery-quartic-min-x-smaller",
            "사차함수 f(x) = {f}{ga} 극소가 되는 x좌표 중 작은 값을 구하시오.",
            "p3-shape:mas4",
            slot=slot,
            role="min",
            pick="smallest",
        ),
        _quartic_even_frame(
            "mastery-quartic-max-x-larger",
            "곡선 y = {f}{ga} 극대가 되는 x좌표 중 큰 값을 구하시오.",
            "p3-shape:mas5",
            slot=slot,
            role="max",
            pick="largest",
        ),
        _flat_value_frame(
            "mastery-quartic-local-value",
            "함수 f(x) = {f}의 x = {r}에서의 극솟값을 구하시오.",
            "p3-shape:mas6",
            slot=slot,
            word="min",
            at="extremum",
        ),
        _cubic_value_frame(
            "mastery-value-local-min-low",
            "삼차함수 f(x) = {f}의 x = {r}에서의 극솟값을 구하시오.",
            "p3-shape:mas7",
            slot=slot,
            word="min",
            at="low",
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
