"""[12미적Ⅰ-02-03] 함수 y = x^n의 도함수 — 규칙 일반화 결정론 문항 생성기.

P3-05 5단계(결정론·LLM 0). 범위 명세의 스킬 `skill.pattern-generalization`을 행사하는
승인 문항이 0건이라 Problem Coverage가 8/8이 되지 못한다. 이 스킬은 개념 02-03(원자
3개 전부)에서 왔고, 이 생성기가 `ptype.generalize-pattern` 문항 24건을 낸다.

문항이 묻는 것 — 항의 규칙을 읽어 일반항으로
------------------------------------------
첫 몇 항과 끝 항만 적고 가운데를 생략 부호(`...`)로 줄인 다항식 `x + x^2 + x^3 + ... + x^N`의
미분계수를 묻는다. 학생은 ① 생략된 항의 규칙(일반항)을 읽어 내고 ② 각 항을 x^n의 도함수
공식으로 미분하고 ③ 값이 이루는 수열의 규칙(`1 - 2 + 3 - ...` 같은 교대합)을 일반화해 합한다.
`ptype.generalize-pattern`의 설명("구체 사례에서 일반 규칙을 도출한다. 수열·귀납 관찰형")에서
귀납하는 대상이 *문면에 생략된 항*과 *미분계수의 수열*이다.

첫 설계를 버린 이유 (은행 감사 1회차 as-found)
---------------------------------------------
처음에는 "미분계수 a(2), a(3), a(4)를 사례로 보이고 a(8)을 묻는" 꼴이었다. 감사 1회차에서
판정자가 사례의 값만 이어 쓰면 도함수 없이 답에 닿는다고 지적했다(사례 틀에서 9건).
정답이 사례의 연장선에 있으면 미분이 필요 없다는 지적이 옳아서, 사례를 주지 않고 **미분을 해야만
값이 나오는** 다항식 합으로 바꿨다. 이 사실은 대장과 감사 기록에 as-found로 남는다.

검산 재료
---------
정답은 `Derivative(<다항식>, x).doit().subs(x, 점) = y` 한 건이다(전개한 다항식을 한 번에 미분).
02-03의 승인 은행(P3-03)이 낸 문항과 검산 조건이 겹치지 않도록 그 조건 키를 미리 점유한다.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import ClassVar, Final

import sympy

from whymath_backend.l3.equivalent.p3_diff_power_derivative_skeleton_generator import (
    P3DiffPowerDerivativeGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import (
    DiffItem,
    Frame,
    P3DiffSlotGenerator,
    SlotId,
    _condition_key,
    answer_format_for,
    round_robin_items,
    seeded_order,
)

__all__ = ["P3DiffPowerPatternGenerator"]

_GENERALIZE: Final = "ptype.generalize-pattern"
_X = sympy.Symbol("x")

#: 항 하나의 계수 규칙 — k번째 항의 (계수, 지수). 첫 세 항과 끝 항으로 문면에 보인다.
Term = Callable[[int], tuple[int, int]]


def _paren(value: int) -> str:
    """음수는 괄호로 감싼다('2 × (-1)') — 곱 표기에서 '× -1'을 만들지 않는다."""
    return f"({value})" if value < 0 else str(value)


def _signed_sum(values: list[int]) -> str:
    """'1 - 2 + 3' — '+ -2'를 만들지 않고 부호를 연산자로 옮긴다."""
    out = str(values[0])
    for v in values[1:]:
        out += f" - {-v}" if v < 0 else f" + {v}"
    return out


def _term_text(coeff: int, exponent: int, *, first: bool) -> str:
    """'x'·'2x^2'·'-x^3' 항 표기 — 선두가 아니면 앞에 연산자를 붙인다('+ x^2'·'- 3x^3')."""
    magnitude = abs(coeff)
    body = "x" if exponent == 1 else f"x^{exponent}"
    text = body if magnitude == 1 else f"{magnitude}{body}"
    if first:
        return f"-{text}" if coeff < 0 else text
    return f"- {text}" if coeff < 0 else f"+ {text}"


#: 항을 4개 보여야 규칙이 하나로 정해지는 틀 — 부호가 번갈아 바뀌는 급수는 세 항만으로는
#: 생략된 부호를 읽는 사람이 다르게 읽을 수 있다(은행 감사 2회차 as-found).
_SHOWN_TERMS: Final = {"pat-alternating-signs": 4}
_DEFAULT_SHOWN: Final = 3
#: 정답 크기 상한 — 학생이 손으로 더하기엔 너무 큰 값은 건너뛴다.
_MAX_ANSWER: Final = 20000


def _series_text(term: Term, n_terms: int, shown_terms: int = _DEFAULT_SHOWN) -> str:
    """첫 몇 항 + '...' + 끝 항 — 생략된 항은 규칙으로 읽어 내야 한다."""
    shown = [_term_text(*term(k), first=(k == 1)) for k in range(1, shown_terms + 1)]
    last = _term_text(*term(n_terms), first=False)
    return f"{' '.join(shown)} + ... {last}".replace("+ ... +", "+ ... +").replace(
        "+ ... -", "+ ... -"
    )


def _expanded_text(pairs: list[tuple[int, int]]) -> str:
    """(계수, 지수) 목록 → 모든 항을 적은 식('x + x^2 + x^3')·상수항은 숫자로."""
    out = ""
    for index, (coeff, exponent) in enumerate(pairs):
        if exponent == 0:
            magnitude = abs(coeff)
            text = str(magnitude)
            first_text = str(coeff)
        else:
            text = _term_text(abs(coeff), exponent, first=True)
            first_text = _term_text(coeff, exponent, first=True)
        if index == 0:
            out = first_text
        else:
            out += f" - {text}" if coeff < 0 else f" + {text}"
    return out


def _poly(term: Term, n_terms: int) -> sympy.Expr:
    return sympy.Add(*(c * _X**e for c, e in (term(k) for k in range(1, n_terms + 1))))


def _item(
    *,
    slot: str,
    frame_id: str,
    term: Term,
    n_terms: int,
    point: int,
    general: str,
) -> DiffItem | None:
    series = _series_text(term, n_terms, _SHOWN_TERMS.get(frame_id, _DEFAULT_SHOWN))
    poly = _poly(term, n_terms)
    pairs = [term(k) for k in range(1, n_terms + 1)]
    derivative = [(c * e, e - 1) for c, e in pairs]
    values = [
        int(sympy.diff(c * _X**e, _X).subs(_X, point))
        for c, e in (term(k) for k in range(1, n_terms + 1))
    ]
    total = sum(values)
    if abs(total) > _MAX_ANSWER:
        return None
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=(f"함수 f(x) = {series}에 대하여 f'({point})의 값을 구하시오."),
        answer_text=str(total),
        explanation=(
            f"생략된 항을 규칙대로 채우면 f(x) = {_expanded_text(pairs)}이다. "
            f"{general}각 항을 미분하면 f'(x) = {_expanded_text(derivative)}이고, "
            f"x = {point}일 때의 값은 {_signed_sum(values)} = {total}이다."
        ),
        conditions=f"Derivative({poly}, x).doit().subs(x, {point}) = y",
        answer_map=(("y", str(total)),),
        problem_type_code=_GENERALIZE,
        answer_format=answer_format_for(str(total)),
    )


def _grid(seed: str, *axes: tuple[int, ...]) -> tuple[tuple[object, ...], ...]:
    combos: list[tuple[object, ...]] = [()]
    for axis in axes:
        combos = [(*c, v) for c in combos for v in axis]
    return tuple(seeded_order(seed, combos))


def _frame(
    frame_id: str,
    seed: str,
    slot: str,
    term: Term,
    general: str,
    points_and_lengths: tuple[tuple[int, ...], tuple[int, ...]],
) -> Frame:
    def build(p: tuple[object, ...]) -> DiffItem | None:
        point, n_terms = int(str(p[0])), int(str(p[1]))
        return _item(
            slot=slot,
            frame_id=frame_id,
            term=term,
            n_terms=n_terms,
            point=point,
            general=general,
        )

    return Frame(frame_id, _grid(seed, *points_and_lengths), build)


def _power(k: int) -> tuple[int, int]:
    return 1, k


def _odd_power(k: int) -> tuple[int, int]:
    return 1, 2 * k - 1


def _even_power(k: int) -> tuple[int, int]:
    return 1, 2 * k


def _coefficient_equals_exponent(k: int) -> tuple[int, int]:
    return k, k


def _alternating(k: int) -> tuple[int, int]:
    return (1 if k % 2 else -1), k


def _doubling(k: int) -> tuple[int, int]:
    return 2 ** (k - 1), k


def _applied_frames() -> list[Frame]:
    slot = "applied"
    return [
        _frame(
            "pat-consecutive-powers",
            "p3pat:a1",
            slot,
            _power,
            "지수가 1씩 커지는 항들의 합이다. ",
            ((-1, 2, -2), (6, 7, 8, 9)),
        ),
        _frame(
            "pat-odd-powers",
            "p3pat:a2",
            slot,
            _odd_power,
            "지수가 1, 3, 5, ...로 홀수만 커진다. ",
            ((-1, 2, -2), (6, 7, 8, 9)),
        ),
        _frame(
            "pat-even-powers",
            "p3pat:a3",
            slot,
            _even_power,
            "지수가 2, 4, 6, ...로 짝수만 커진다. ",
            ((-1, 2, -2), (6, 7, 8, 9)),
        ),
    ]


def _mastery_frames() -> list[Frame]:
    slot = "mastery_check"
    return [
        _frame(
            "pat-coefficient-equals-exponent",
            "p3pat:m1",
            slot,
            _coefficient_equals_exponent,
            "계수와 지수가 함께 1, 2, 3, ...으로 커진다. ",
            ((-1, -2), (6, 7, 8)),
        ),
        _frame(
            "pat-alternating-signs",
            "p3pat:m2",
            slot,
            _alternating,
            "항의 부호가 번갈아 바뀌고 지수는 1씩 커진다. ",
            ((2, -2, 3), (6, 7, 8)),
        ),
        _frame(
            "pat-doubling-coefficients",
            "p3pat:m3",
            slot,
            _doubling,
            "계수가 1, 2, 4, 8, ...로 두 배씩 커진다. ",
            ((-1, 2), (6, 7, 8)),
        ),
    ]


_SLOT_FRAMES = {"applied": _applied_frames, "mastery_check": _mastery_frames}


@functools.lru_cache(maxsize=1)
def _sibling_condition_keys() -> frozenset[str]:
    """02-03 승인 은행(P3-03)이 이미 낸 문항의 검산 조건 키 — 같은 수학 실체를 피한다."""
    return frozenset(
        _condition_key(item)
        for slot in P3DiffPowerDerivativeGenerator.slots
        for item in P3DiffPowerDerivativeGenerator.items(slot)
    )


class P3DiffPowerPatternGenerator(P3DiffSlotGenerator):
    """[12미적Ⅰ-02-03] 규칙 일반화 — 스킬 pattern-generalization을 덮는 24건 결정론 생성기."""

    standard_code: ClassVar[str] = "[12미적Ⅰ-02-03]"
    concept_src_id: ClassVar[str] = "H:12미적Ⅰ02-03"
    unit_code: ClassVar[str] = "P3-CALC1-DIFF-POWER-PATTERN"
    slug_prefix: ClassVar[str] = "wm-p3-diff-power-pattern"
    slots: ClassVar[tuple[SlotId, ...]] = ("applied", "mastery_check")
    slot_difficulty: ClassVar[dict[str, float]] = {"applied": 3.0, "mastery_check": 3.5}
    slot_count: ClassVar[int] = 12

    @classmethod
    def _slot_items(cls, slot: str, claimed: set[str]) -> list[DiffItem]:
        claimed |= _sibling_condition_keys()
        return round_robin_items(
            _SLOT_FRAMES[slot](),
            cls.slot_count,
            claimed=claimed,
            standard_code=cls.standard_code,
        )
