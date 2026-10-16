"""[12미적Ⅰ-02-07] 함수의 증가·감소와 극대·극소 결정론 문항 생성기 — P3-05 4단계(결정론·LLM 0).

개념: `H:12미적Ⅰ02-07`(함수의 증가·감소, 극대·극소). 슬롯이 비어 있던 4칸(기본·응용·진단·
숙련도 확인)을 채운다 — 대표·오개념 유발 칸은 기존 승인 문항(`generated_v0` 등 237건)이 이미 채웠다.

설계 — 02-08 생성기의 틀을 *새 발문·새 시드*로 다시 쓴다
--------------------------------------------------------
증가·감소와 극값을 판정하는 행동(f'의 부호 변화 읽기)은 02-07과 02-08(그래프 개형의 파생 판정)이
같은 SymPy 분석을 쓴다. 02-08 생성기(`p3_diff_graph_shape_skeleton_generator`)의 틀 공장
(`_cubic_frame`·`_find_a_frame` 등)은 감사 5~8회차를 거치며 우회로 판정기·적재 규칙(B3·C3)을 모두
통과하도록 다듬어졌다 — 같은 공장을 쓰되 이 파일이 **발문과 시드를 따로** 둔다. 그래서 같은 함수라도
발문이 다르고, 02-08 문항의 검산 조건 키를 미리 `claimed`에 넣어 같은 수학 실체(같은 함수·같은
조건)를 건너뛴다(`test_p3_diff_monotonicity_extremum_generator.py`가 코퍼스 전체와 문면 중복
0건을 동결한다).

기존 02-07 문항(237건)과 다른 점
------------------------------
기존 문항은 전부 `x^3 + bx^2 + cx`(최고차항 1·상수항 0)의 극값·극점을 묻는다. 이 생성기는
최고차항 계수가 1·2·-1·-2인 삼차함수, 비대칭 사차함수, 증가·감소 범위에 속하는 정수, 미지 상수를
거치는 문항을 낸다. 오개념 유발 칸은 기존 승인 문항이 채웠으므로 이 생성기는 오답 선지를 달지
않는다(객관식 틀 없음).

문제유형 정직성
--------------
공장이 달아 주는 대로 따른다: 극대·극소 x좌표·극값은 `ptype.optimize-extremum`, 구간 속 정수·
미지수 구하기는 `ptype.solve-for-unknown`.
"""

from __future__ import annotations

import functools
from typing import ClassVar

from whymath_backend.l3.equivalent.p3_diff_graph_shape_skeleton_generator import (
    P3DiffGraphShapeGenerator,
    _cubic_frame,
    _cubic_interval_frame,
    _cubic_other_root_frame,
    _find_a_frame,
    _find_b_cubic_frame,
    _find_b_quartic_frame,
    _find_k_other_root_frame,
    _flat_x_frame,
    _quartic_asym_x_frame,
    _quartic_k_frame,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import (
    DiffItem,
    Frame,
    SlotId,
    _condition_key,
    round_robin_items,
)

__all__ = ["P3DiffMonotonicityExtremumGenerator"]

_SEED = "p3-ext"


def _basic_frames() -> list[Frame]:
    slot = "basic"
    return [
        _cubic_frame(
            "basic-local-max-x-value",
            "삼차함수 f(x) = {f}{ga} 극대가 되는 x의 값을 구하시오.",
            f"{_SEED}:bas1",
            role="max",
            pick=None,
            slot=slot,
        ),
        _cubic_frame(
            "basic-local-min-x-value",
            "삼차함수 f(x) = {f}{ga} 극소가 되는 x의 값을 구하시오.",
            f"{_SEED}:bas2",
            role="min",
            pick=None,
            slot=slot,
        ),
        _cubic_frame(
            "basic-sign-change-larger",
            "함수 f(x) = {f}에서 증가와 감소가 바뀌는 x의 값 중 큰 값을 구하시오.",
            f"{_SEED}:bas3",
            role="turn",
            pick="largest",
            slot=slot,
        ),
        _cubic_interval_frame(
            "basic-increasing-integer-range",
            "함수 f(x) = {f}{ga} 증가하는 x의 값의 범위에 속하는 정수는 하나뿐이다. "
            "그 정수를 구하시오.",
            f"{_SEED}:bas4",
            slot=slot,
            direction="pos",
        ),
        _cubic_interval_frame(
            "basic-decreasing-integer-range",
            "함수 f(x) = {f}{ga} 감소하는 x의 값의 범위에 속하는 정수는 하나뿐이다. "
            "그 정수를 구하시오.",
            f"{_SEED}:bas5",
            slot=slot,
            direction="neg",
        ),
        _cubic_other_root_frame(
            "basic-extremum-value-pinned-other-point",
            "삼차함수 f(x) = {f}{neun} x = {p}에서 극값을 갖는다. f(x)의 {kind}을 구하시오. "
            "(단, a는 상수이다.)",
            f"{_SEED}:bas6",
            slot=slot,
            pin="min",
            ask_kind="max",
        ),
    ]


def _applied_frames() -> list[Frame]:
    slot = "applied"
    return [
        _find_a_frame(
            "applied-constants-from-local-min-value",
            "함수 f(x) = {f}{ga} x = {r}에서 {kind} {v}{veul} 가질 때, 상수 {p}의 값을 구하시오. "
            "(단, a, b는 상수이다.)",
            f"{_SEED}:app1",
            slot=slot,
            want="min",
        ),
        _find_a_frame(
            "applied-constants-from-local-max-value",
            "함수 f(x) = {f}{ga} x = {r}에서 {kind} {v}{veul} 가질 때, 상수 {p}의 값을 구하시오. "
            "(단, a, b는 상수이다.)",
            f"{_SEED}:app2",
            slot=slot,
            want="max",
        ),
        _find_k_other_root_frame(
            "applied-constant-from-other-extremum-value",
            "함수 f(x) = {f}{ga} x = {p}에서 극값을 갖고 f(x)의 {kind}이 {v}일 때, 상수 k의 값을 "
            "구하시오. (단, a는 상수이다.)",
            f"{_SEED}:app3",
            slot=slot,
            pin="max",
            ask_kind="min",
        ),
        _quartic_asym_x_frame(
            "applied-quartic-local-min-x-larger",
            "사차함수 f(x) = {f}{ga} 극소가 되는 x의 값 중 큰 값을 구하시오.",
            f"{_SEED}:app4",
            slot=slot,
            leads=(1, 3),
            role="min",
            pick="largest",
        ),
        _quartic_asym_x_frame(
            "applied-quartic-local-max-x-smaller",
            "사차함수 f(x) = {f}{ga} 극대가 되는 x의 값 중 작은 값을 구하시오.",
            f"{_SEED}:app5",
            slot=slot,
            leads=(-1, -3),
            role="max",
            pick="smallest",
        ),
        _quartic_k_frame(
            "applied-quartic-extremum-value-with-constant",
            "사차함수 f(x) = {f}{ga} x = {p}에서 극값을 가질 때, f(x)의 {kind}을 구하시오. "
            "(단, k는 상수이다.)",
            f"{_SEED}:app6",
            slot=slot,
            leads=(1, 3),
            pin="outer",
            ask="middle",
        ),
    ]


def _diagnostic_frames() -> list[Frame]:
    slot = "diagnostic"
    return [
        _flat_x_frame(
            "diag-critical-point-without-sign-change",
            "함수 f(x) = {f}에 대하여 f'(x) = 0이지만 f'(x)의 부호가 바뀌지 않는 x의 값을 "
            "구하시오.",
            f"{_SEED}:dia1",
            slot=slot,
            role="flat",
            pick=None,
        ),
        _flat_x_frame(
            "diag-quartic-single-extremum",
            "사차함수 f(x) = {f}{ga} 극값을 갖는 x의 값을 구하시오.",
            f"{_SEED}:dia2",
            slot=slot,
            role="turn",
            pick=None,
        ),
        _cubic_frame(
            "diag-increase-to-decrease-x",
            "함수 f(x) = {f}{ga} 증가하다가 감소로 바뀌는 점의 x의 값을 구하시오.",
            f"{_SEED}:dia3",
            role="max",
            pick=None,
            slot=slot,
        ),
        _cubic_interval_frame(
            "diag-decreasing-integer-curve",
            "곡선 y = {f}에서 x의 값이 커질 때 y의 값이 작아지는 x의 값의 범위에 속하는 "
            "정수는 하나뿐이다. 그 정수를 구하시오.",
            f"{_SEED}:dia4",
            slot=slot,
            direction="neg",
        ),
        _cubic_frame(
            "diag-decrease-to-increase-x",
            "함수 f(x) = {f}{ga} 감소하다가 증가로 바뀌는 점의 x의 값을 구하시오.",
            f"{_SEED}:dia5",
            role="min",
            pick=None,
            slot=slot,
        ),
    ]


def _mastery_frames() -> list[Frame]:
    slot = "mastery_check"
    return [
        _find_b_cubic_frame(
            "mastery-constant-from-cubic-extremum-value",
            "함수 f(x) = {f}{ga} x = {r}에서 {kind} {v}{veul} 가질 때, 상수 {p}의 값을 구하시오. "
            "(단, a, b는 상수이다.)",
            f"{_SEED}:mas1",
            slot=slot,
        ),
        _find_b_quartic_frame(
            "mastery-constant-from-quartic-local-min",
            "사차함수 f(x) = {f}{ga} x = {r}에서 {kind} {v}{veul} 가질 때, "
            "상수 {p}의 값을 구하시오. (단, a, b는 상수이다.)",
            f"{_SEED}:mas2",
            slot=slot,
        ),
        _find_k_other_root_frame(
            "mastery-constant-from-other-extremum",
            "함수 y = {f}{neun} x = {p}에서 극값을 갖는다. 이 함수의 {kind}이 {v}일 때, 상수 k의 "
            "값을 구하시오. (단, a는 상수이다.)",
            f"{_SEED}:mas3",
            slot=slot,
            pin="max",
            ask_kind="min",
        ),
        _quartic_k_frame(
            "mastery-quartic-compare-outer-minima",
            "사차함수 f(x) = {f}{neun} x = {p}에서 극값을 갖는다. 두 {kind} 중 {size} 값을 "
            "구하시오. (단, k는 상수이다.)",
            f"{_SEED}:mas4",
            slot=slot,
            leads=(1, 3),
            pin="middle",
            ask="outer-smaller",
        ),
        _quartic_k_frame(
            "mastery-quartic-compare-outer-maxima",
            "사차함수 f(x) = {f}{ga} x = {p}에서 극값을 가질 때, 두 {kind} 중 {size} 값을 "
            "구하시오. (단, k는 상수이다.)",
            f"{_SEED}:mas5",
            slot=slot,
            leads=(-1, -3),
            pin="outer",
            ask="outer-larger",
        ),
    ]


@functools.lru_cache(maxsize=1)
def _sibling_condition_keys() -> frozenset[str]:
    """02-08 생성기가 이미 낸 문항의 검산 조건 키 — 같은 수학 실체(같은 함수·같은 조건)를 피한다."""
    return frozenset(
        _condition_key(item)
        for slot in P3DiffGraphShapeGenerator.slots
        for item in P3DiffGraphShapeGenerator.items(slot)
    )


_SLOT_FRAMES = {
    "basic": _basic_frames,
    "applied": _applied_frames,
    "diagnostic": _diagnostic_frames,
    "mastery_check": _mastery_frames,
}


class P3DiffMonotonicityExtremumGenerator(P3DiffGraphShapeGenerator):
    """[12미적Ⅰ-02-07] 증가·감소, 극대·극소 — 빈 4칸 결정론 생성기.

    02-08 생성기를 상속해 `answer_selection`을 후보에 얹는 `_assemble`을 그대로 쓰고, 개념 식별자·
    담당 슬롯·틀 목록만 바꾼다.
    """

    standard_code: ClassVar[str] = "[12미적Ⅰ-02-07]"
    concept_src_id: ClassVar[str] = "H:12미적Ⅰ02-07"
    unit_code: ClassVar[str] = "P3-CALC1-DIFF-MONOTONICITY-EXTREMUM"
    slug_prefix: ClassVar[str] = "wm-p3-diff-monotonicity"
    slots: ClassVar[tuple[SlotId, ...]] = ("basic", "applied", "diagnostic", "mastery_check")
    slot_difficulty: ClassVar[dict[str, float]] = {
        "basic": 2.5,
        "applied": 3.5,
        "diagnostic": 3.0,
        "mastery_check": 4.0,
    }

    @classmethod
    def _slot_items(cls, slot: str, claimed: set[str]) -> list[DiffItem]:
        claimed |= _sibling_condition_keys()  # 같은 틀 공장을 쓰는 02-08 문항과 실체가 겹치지 않게
        return round_robin_items(
            _SLOT_FRAMES[slot](),
            cls.slot_count,
            claimed=claimed,
            standard_code=cls.standard_code,
        )
