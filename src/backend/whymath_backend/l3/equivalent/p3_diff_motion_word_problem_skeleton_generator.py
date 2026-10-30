"""[12미적Ⅰ-02-10] 속도와 가속도 — 상황 설명(문장제) 모델링 결정론 문항 생성기.

P3-05 5단계(결정론·LLM 0). 범위 명세의 스킬 `skill.word-problem-modeling`을 행사하는
승인 문항이 0건이라 Problem Coverage가 8/8이 되지 못한다. 이 스킬은 개념 02-09·02-10의
원자에서 왔고 이 생성기는 02-10에 둔다(`ptype.model-word-problem` — "실상황을 수학
구조로 번역한다. 해석→정식화가 본질").

기존 02-10 문항과 다른 점
------------------------
기존 문항(P3-03)은 "수직선 위를 움직이는 점 P의 위치가 x = …"처럼 *수학 객체로 이미
번역된* 상태에서 미분만 시킨다. 이 생성기는 직선 레일 위의 장난감 열차 같은 **상황 설명**을
주고, 학생이 상황의 말을 식으로 옮기게 한다.
- "방향을 바꾼다 / 멈췄다" ⇒ 속도 v(t) = 0
- "가속도가 0이 되었다" ⇒ 가속도 a(t) = 0
- "t초 때의 속도(가속도)가 …이다" ⇒ v(t)(a(t))의 값
정답을 구하는 계산은 이 번역 뒤에 온다.

첫 설계를 버린 이유 (은행 감사 1회차 as-found)
---------------------------------------------
처음에는 던진 공·브레이크를 밟은 자동차의 *이차* 위치함수를 썼다. 감사 1회차에서 판정자가
꼭짓점 공식으로 풀린다(미분 없이 풀림)고 지적했고, 같은 높이를 묻는 틀은 일차방정식 하나로 끝난다는
지적도 있었다(결함 5건). 그래서 **삼차** 위치함수만 쓴다 — 속도 0인 시각이 포물선 꼭짓점이 아니라
도함수의 근이고, 양의 근이 하나뿐이도록 구성해(`v(t) = 3A(t - r)(t + n)`) 발문의 '출발 후'가 답을
하나로 정한다.

정직한 한계
----------
위치함수 자체는 문면이 준다(물리 법칙으로 세우게 하지 않는다). 번역하는 것은 *조건의 말*이다. 학생
대면 문장이 짧고 정형이라 "현실 맥락을 읽는 힘" 전체를 대표하지 않는다는 한계를 둔다.

검산 재료
---------
위치 다항식은 변수 x로 쓴다(시각 t는 문면 표기일 뿐). 시각·값을 묻는 문항은 `(도함수 = 0, x > 0)`
조건과 `answer_map`(x = 그 시각, y = 값)으로 *그 시각이 정말 속도 0인가*까지 기계가 본다.
상수를 묻는 문항은 상황의 말을 그대로 방정식으로 쓴다.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import ClassVar, Final

from whymath_backend.l3.equivalent.p3_diff_expr import Poly, poly_to_sympy_str, render_poly
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
from whymath_backend.l3.equivalent.p3_diff_velocity_acceleration_skeleton_generator import (
    P3DiffVelocityAccelerationGenerator,
)

__all__ = ["P3DiffMotionWordProblemGenerator"]

_MODEL: Final = "ptype.model-word-problem"
_RAIL: Final = "직선 레일 위를 움직이는 장난감 열차가 출발한 지 t초 후, 출발 지점에서 잰 위치는"
_NOUN: Final = "열차의 위치"


def _grid(seed: str, *axes: tuple[int, ...]) -> tuple[tuple[object, ...], ...]:
    combos: list[tuple[object, ...]] = [()]
    for axis in axes:
        combos = [(*c, v) for c in combos for v in axis]
    return tuple(seeded_order(seed, combos))


def _distinct_answer_frame(
    frame_id: str,
    params: tuple[tuple[object, ...], ...],
    build: Callable[[tuple[object, ...]], DiffItem | None],
) -> Frame:
    """답이 같은 후보는 첫 하나만 남긴다 — 같은 틀에서 정답이 겹치면 값 짐작이 통한다."""
    seen: set[str] = set()
    kept: list[tuple[object, ...]] = []
    for p in params:
        item = build(p)
        if item is None or item.answer_text in seen:
            continue
        seen.add(item.answer_text)
        kept.append(p)
    return Frame(frame_id, tuple(kept), build)


def _rail_poly(a: int, r: int, n: int) -> Poly | None:
    """v(t) = 3a(t - r)(t + n)인 위치 a t^3 + b t^2 + c t — 계수가 정수가 아니면 None."""
    if r == n or (3 * a * (n - r)) % 2:
        return None
    b = 3 * a * (n - r) // 2
    c = -3 * a * r * n
    return tuple((e, k) for e, k in ((3, a), (2, b), (1, c)) if k)


def _derivative_text(poly: Poly) -> str:
    """위치 다항식의 도함수 표기(변수 t)."""
    return render_poly(tuple((e - 1, c * e) for e, c in poly if e), "t")


def _second_text(poly: Poly) -> str:
    first = tuple((e - 1, c * e) for e, c in poly if e)
    return render_poly(tuple((e - 1, c * e) for e, c in first if e), "t")


def _v_head(poly: Poly) -> str:
    """'속도 v(t)는 열차의 위치 s(t)의 도함수이므로 v(t) = …이다.' (기호를 주어 자리에 소개)

    기호 v(t)를 주어 자리에서 소개하고 '위치'를 말해야 판정기(E-motion-symbol-intro)가 정의 문장으로
    읽는다.
    """
    return f"속도 v(t)는 {_NOUN} s(t)의 도함수이므로 v(t) = {_derivative_text(poly)}이다."


def _intro(poly: Poly) -> str:
    return f"{_RAIL} s(t) = {render_poly(poly, 't')} (cm)이다."


def _turn_conditions(sym: str, *extra: str) -> tuple[str, ...]:
    return (*extra, f"Derivative({sym}, x).doit() = 0", "x > 0")


def _rail_item(
    *, slot: str, frame_id: str, text: str, poly: Poly, r: int, value: int | None,
    explanation: str, extra: str | None = None,
) -> DiffItem:  # fmt: skip
    """방향을 바꾸는 시각(`value`가 없으면 시각 자체)이나 그 시각의 값을 묻는 문항."""
    sym = poly_to_sympy_str(poly, "x")
    if value is None:
        return DiffItem(
            slot=slot,
            frame_id=frame_id,
            question_text=text,
            answer_text=str(r),
            explanation=explanation,
            conditions=_turn_conditions(sym),
            answer_map=(("x", str(r)),),
            problem_type_code=_MODEL,
            answer_format=answer_format_for(str(r)),
        )
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=str(value),
        explanation=explanation,
        conditions=_turn_conditions(sym, extra or f"y = {sym}"),
        answer_map=(("x", str(r)), ("y", str(value))),
        problem_type_code=_MODEL,
        answer_format=answer_format_for(str(value)),
    )


def _turn_reason(a: int, r: int) -> str:
    """방향 전환의 근거 — v = 0인 시각 좌우에서 속도의 부호가 바뀐다.

    v = 0만으로는 방향 전환이 아니다.
    """
    change = "음에서 양으로" if a > 0 else "양에서 음으로"
    return f"t = {r}의 좌우에서 v(t)의 부호가 {change} 바뀌므로 이때 운동 방향이 바뀐다."


def _at(poly: Poly, point: int) -> int:
    """위치 다항식의 값 — (지수, 계수) 쌍을 정수로 직접 더한다(문자열 파서를 거치지 않는다)."""
    return sum(coeff * point**exponent for exponent, coeff in poly)


# ──────────────────────────────────────────────────────────────────────────
# 응용 — 상황의 말("방향을 바꾼다")을 v(t) = 0 으로 옮긴다
# ──────────────────────────────────────────────────────────────────────────
def _rail_params(seed: str) -> tuple[tuple[object, ...], ...]:
    return _grid(seed, (1, 2, -1, 4, -2), (1, 2, 3, 4, 5), (1, 2, 3, 4))


def _turn_time(p: tuple[object, ...]) -> DiffItem | None:
    a, r, n = (int(str(v)) for v in p)
    poly = _rail_poly(a, r, n)
    if poly is None:
        return None
    return _rail_item(
        slot="applied",
        frame_id="word-rail-time-of-turn",
        text=f"{_intro(poly)} 열차가 운동 방향을 바꾸는 것은 출발한 지 몇 초 후인가? (단, t > 0)",
        poly=poly,
        r=r,
        value=None,
        explanation=(
            f"{_v_head(poly)} 운동 방향이 바뀌는 순간에는 v(t) = 0이고, t > 0이므로 t = {r}이다. "
            f"{_turn_reason(a, r)}"
        ),
    )


def _turn_position(p: tuple[object, ...]) -> DiffItem | None:
    a, r, n = (int(str(v)) for v in p)
    poly = _rail_poly(a, r, n)
    if poly is None:
        return None
    value = _at(poly, r)
    return _rail_item(
        slot="applied",
        frame_id="word-rail-position-at-turn",
        text=(
            f"{_intro(poly)} 열차가 운동 방향을 바꾸는 순간 출발 지점에서 잰 위치는 몇 cm인가? "
            "(단, t > 0)"
        ),
        poly=poly,
        r=r,
        value=value,
        explanation=(
            f"{_v_head(poly)} 운동 방향이 바뀌는 순간에는 v(t) = 0이고 t > 0이므로 t = {r}이다. "
            f"{_turn_reason(a, r)} 그때의 위치는 s({r}) = {value}이다."
        ),
    )


def _turn_acceleration(p: tuple[object, ...]) -> DiffItem | None:
    a, r, n = (int(str(v)) for v in p)
    poly = _rail_poly(a, r, n)
    if poly is None:
        return None
    value = 6 * a * r + 3 * a * (n - r)  # s''(r) = 6a r + 2b
    sym = poly_to_sympy_str(poly, "x")
    return _rail_item(
        slot="applied",
        frame_id="word-rail-acceleration-at-turn",
        text=(
            f"{_intro(poly)} 열차가 운동 방향을 바꾸는 순간의 가속도는 몇 cm/초^2인가? (단, t > 0)"
        ),
        poly=poly,
        r=r,
        value=value,
        extra=f"y = Derivative({sym}, x, x).doit()",
        explanation=(
            f"{_v_head(poly)} 운동 방향이 바뀌는 순간에는 v(t) = 0이고 t > 0이므로 t = {r}이다. "
            f"{_turn_reason(a, r)} 가속도 a(t)는 속도 v(t)의 도함수이므로 "
            f"a(t) = {_second_text(poly)}이고 a({r}) = {value}이다."
        ),
    )


def _applied_frames() -> list[Frame]:
    return [
        _distinct_answer_frame("word-rail-time-of-turn", _rail_params("p3mw:a1"), _turn_time),
        _distinct_answer_frame(
            "word-rail-position-at-turn", _rail_params("p3mw:a2"), _turn_position
        ),
        _distinct_answer_frame(
            "word-rail-acceleration-at-turn", _rail_params("p3mw:a3"), _turn_acceleration
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 숙련도 확인 — 상황의 말에서 상수를 거꾸로 구한다
# ──────────────────────────────────────────────────────────────────────────
def _unknown_item(
    *, frame_id: str, text: str, condition: str, answer: int, explanation: str
) -> DiffItem:
    return DiffItem(
        slot="mastery_check",
        frame_id=frame_id,
        question_text=text,
        answer_text=str(answer),
        explanation=explanation,
        conditions=condition,
        answer_map=(("u", str(answer)),),
        problem_type_code=_MODEL,
        answer_format=answer_format_for(str(answer)),
    )


def _u_poly_text(c: int) -> str:
    """s(t) = t^3 - ut^2 + ct 의 표기."""
    return f"t^3 - ut^2 + {c}t"


def _stop_constant(p: tuple[object, ...]) -> DiffItem | None:
    t0, u = int(str(p[0])), int(str(p[1]))
    c = 2 * u * t0 - 3 * t0 * t0
    if c <= 0:
        return None
    return _unknown_item(
        frame_id="word-rail-constant-from-stop-time",
        text=(
            f"{_RAIL} s(t) = {_u_poly_text(c)} (cm)이다 (u는 상수). 열차가 출발한 지 {t0}초 후에 "
            "순간적으로 멈췄다고 할 때, u의 값을 구하시오."
        ),
        condition=f"Derivative(x**3 - u*x**2 + {c}*x, x).doit().subs(x, {t0}) = 0",
        answer=u,
        explanation=(
            f"속도 v(t)는 {_NOUN} s(t)의 도함수이므로 v(t) = 3t^2 - 2ut + {c}이다. 멈춘 순간에는 "
            f"v(t) = 0이므로 t = {t0}일 때 {3 * t0 * t0} - {2 * t0}u + {c} = 0이고 u = {u}이다."
        ),
    )


def _zero_acceleration_constant(p: tuple[object, ...]) -> DiffItem | None:
    t0, c = int(str(p[0])), int(str(p[1]))
    return _unknown_item(
        frame_id="word-rail-constant-from-zero-acceleration",
        text=(
            f"{_RAIL} s(t) = {_u_poly_text(c)} (cm)이다 (u는 상수). 열차의 가속도가 출발한 지 "
            f"{t0}초 후에 0이 되었다고 할 때, u의 값을 구하시오."
        ),
        condition=f"Derivative(x**3 - u*x**2 + {c}*x, x, x).doit().subs(x, {t0}) = 0",
        answer=3 * t0,
        explanation=(
            f"속도 v(t)는 {_NOUN} s(t)의 도함수이므로 v(t) = 3t^2 - 2ut + {c}이고, 가속도 a(t)는 "
            f"속도 v(t)의 도함수이므로 a(t) = 6t - 2u이다. a({t0}) = 0에서 {6 * t0} - 2u = 0이므로 "
            f"u = {3 * t0}이다."
        ),
    )


def _speed_constant(p: tuple[object, ...]) -> DiffItem | None:
    t0, u, c = (int(str(v)) for v in p)
    speed = 3 * t0 * t0 - 2 * u * t0 + c
    if speed == 0:
        return None
    return _unknown_item(
        frame_id="word-rail-constant-from-speed",
        text=(
            f"{_RAIL} s(t) = {_u_poly_text(c)} (cm)이다 (u는 상수). 열차의 속도가 출발한 지 "
            f"{t0}초 후에 {speed} cm/초였다고 할 때, u의 값을 구하시오."
        ),
        condition=f"Derivative(x**3 - u*x**2 + {c}*x, x).doit().subs(x, {t0}) = {speed}",
        answer=u,
        explanation=(
            f"속도 v(t)는 {_NOUN} s(t)의 도함수이므로 v(t) = 3t^2 - 2ut + {c}이다. "
            f"v({t0}) = {speed}에서 {3 * t0 * t0} - {2 * t0}u + {c} = {speed}이므로 u = {u}이다."
        ),
    )


def _acceleration_constant(p: tuple[object, ...]) -> DiffItem | None:
    t0, u = int(str(p[0])), int(str(p[1]))
    accel = 6 * t0 - 2 * u
    if accel == 0:
        return None
    return _unknown_item(
        frame_id="word-rail-constant-from-acceleration",
        text=(
            f"{_RAIL} s(t) = t^3 - ut^2 + 5t (cm)이다 (u는 상수). 열차의 가속도가 출발한 지 "
            f"{t0}초 후에 {accel} cm/초^2였다고 할 때, u의 값을 구하시오."
        ),
        condition=f"Derivative(x**3 - u*x**2 + 5*x, x, x).doit().subs(x, {t0}) = {accel}",
        answer=u,
        explanation=(
            f"속도 v(t)는 {_NOUN} s(t)의 도함수이므로 v(t) = 3t^2 - 2ut + 5이고, 가속도 a(t)는 "
            f"속도 v(t)의 도함수이므로 a(t) = 6t - 2u이다. a({t0}) = {accel}에서 "
            f"{6 * t0} - 2u = {accel}이므로 u = {u}이다."
        ),
    )


def _mastery_frames() -> list[Frame]:
    return [
        _distinct_answer_frame(
            "word-rail-constant-from-stop-time",
            _grid("p3mw:m1", (2, 3, 4, 5, 6), (3, 4, 5, 6, 7, 8, 9)),
            _stop_constant,
        ),
        _distinct_answer_frame(
            "word-rail-constant-from-zero-acceleration",
            _grid("p3mw:m2", (2, 3, 4, 5, 6), (2, 4, 7, 9, 11)),
            _zero_acceleration_constant,
        ),
        _distinct_answer_frame(
            "word-rail-constant-from-speed",
            _grid("p3mw:m3", (2, 3, 4, 5), (2, 3, 4, 5, 6, 7), (4, 6, 9, 10)),
            _speed_constant,
        ),
        _distinct_answer_frame(
            "word-rail-constant-from-acceleration",
            _grid("p3mw:m4", (2, 3, 4, 5, 6), (1, 2, 4, 5, 7, 8)),
            _acceleration_constant,
        ),
    ]


_SLOT_FRAMES = {"applied": _applied_frames, "mastery_check": _mastery_frames}


@functools.lru_cache(maxsize=1)
def _sibling_condition_keys() -> frozenset[str]:
    """02-10 승인 은행(P3-03)이 이미 낸 문항의 검산 조건 키 — 같은 수학 실체를 피한다."""
    return frozenset(
        _condition_key(item)
        for slot in P3DiffVelocityAccelerationGenerator.slots
        for item in P3DiffVelocityAccelerationGenerator.items(slot)
    )


class P3DiffMotionWordProblemGenerator(P3DiffSlotGenerator):
    """[12미적Ⅰ-02-10] 상황 설명 모델링 — 스킬 word-problem-modeling을 덮는 24건 결정론 생성기."""

    standard_code: ClassVar[str] = "[12미적Ⅰ-02-10]"
    concept_src_id: ClassVar[str] = "H:12미적Ⅰ02-10"
    unit_code: ClassVar[str] = "P3-CALC1-DIFF-MOTION-WORD"
    slug_prefix: ClassVar[str] = "wm-p3-diff-motion-word"
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
