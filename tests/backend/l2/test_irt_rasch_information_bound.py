"""EOS-129 ① — CAT 진단이 Rasch(a=1.0)로 도는 한 SE 0.3에는 **최소 45문항**이 든다(회귀 동결).

근본 원인: `l2/next_problem_selection.py::load_attempt_history_state`가 `IrtItem(difficulty=b)`만
만들고 변별도 a를 넘기지 않는다 → 모든 문항이 a=1.0이다. a=1.0 문항 하나의 최대 정보량은
a²·P(1-P)의 최댓값 0.25(P=0.5, 즉 θ=b)이고, SE ≤ 0.3은 총정보량 1/0.3² = 11.11을 요구한다 →
11.11/0.25 = 44.4 → **45문항**. 이것은 튜닝 여지가 아니라 *모든 문항의 난이도가 능력과 정확히
맞을 때*의 이론적 하한이다(EOS-126이 실측으로 확인: 이상적 적응 출제 46문항·EOS-22 프로브 67문항).

이 파일은 그 하한을 **실제 IRT 함수로** 고정한다. 그리고 a를 보정하면 하한이 어디까지 내려가는지
(EOS-129 ④가 재측정할 목표치 — a=1.5면 20문항·a=2.0이면 12문항)를 같은 식으로 고정한다.

경계값은 상수를 import하지 않고 **리터럴로** 밟는다 — 상수를 import한 테스트는 상수가 바뀌면 함께
움직여 아무것도 잡지 못한다(MISC-30 교훈). 대신 `TARGET_SE`가 0.3이라는 사실 자체를 따로 단언해,
임계를 바꾸는 변경이 이 파일의 하한 전부를 다시 보게 만든다.
"""

from __future__ import annotations

import math
import uuid
from typing import Any

import pytest

from whymath_backend.l2 import next_problem_selection as nps
from whymath_backend.l2.irt import IrtItem, ability_standard_error, item_information


def _items_at(theta: float, n: int, discrimination: float) -> list[IrtItem]:
    """능력과 난이도가 정확히 같은(P=0.5) 문항 n개 — 정보량이 최대인 이상적 출제."""
    return [IrtItem(difficulty=theta, discrimination=discrimination) for _ in range(n)]


class TestRaschInformationCeiling:
    """a=1.0 문항 하나가 줄 수 있는 정보의 상한 — 하한 45의 출발점."""

    def test_item_information_peaks_at_a_quarter_when_theta_equals_b(self) -> None:
        item = IrtItem(difficulty=0.0, discrimination=1.0)
        assert item_information(0.0, item) == pytest.approx(0.25)

    def test_item_information_never_exceeds_a_quarter(self) -> None:
        # θ를 -4~4에서 촘촘히 훑어도 0.25를 넘지 않는다(θ=b가 최대점).
        item = IrtItem(difficulty=0.3, discrimination=1.0)
        grid = [k / 100 for k in range(-400, 401)]
        assert max(item_information(theta, item) for theta in grid) <= 0.25 + 1e-12


class TestStandardErrorItemBound:
    """SE ≤ 0.3에 필요한 최소 문항 수 — 이상적 출제(P=0.5)에서도 깰 수 없는 하한."""

    @pytest.mark.parametrize(
        ("discrimination", "minimum_items"),
        [
            (1.0, 45),  # 현재 CAT 경로(Rasch) — EOS-126이 20문항 상한으로 우회한 원인
            (1.5, 20),  # EOS-129 ④ 목표치 — 상한 20과 같아진다
            (2.0, 12),
        ],
    )
    def test_minimum_items_for_target_se(self, discrimination: float, minimum_items: int) -> None:
        theta = 0.0
        one_short = ability_standard_error(
            theta, _items_at(theta, minimum_items - 1, discrimination)
        )
        enough = ability_standard_error(theta, _items_at(theta, minimum_items, discrimination))
        assert one_short > 0.3, f"a={discrimination}: {minimum_items - 1}문항에서 이미 SE≤0.3"
        assert enough <= 0.3, f"a={discrimination}: {minimum_items}문항에서도 SE>0.3"

    def test_rasch_bound_matches_closed_form(self) -> None:
        # 닫힌 식과 함수 결과가 같은 수를 낸다 — ceil(1 / (0.3² × 0.25)) = 45.
        assert math.ceil(1.0 / (0.3**2 * 0.25)) == 45

    def test_target_se_is_still_point_three(self) -> None:
        # 이 파일의 하한은 전부 SE 0.3 기준이다. 임계가 바뀌면 여기서 멈추고 하한을 다시 계산한다.
        assert nps.TARGET_SE == 0.3


class _Result:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class _FakeSession:
    """`load_attempt_history_state`의 조회 1회만 흉내 — (문항, 정답, 난이도, 보정 b) 행을 돌려준다."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    async def execute(self, _stmt: Any) -> _Result:
        return _Result(self._rows)


def _history_rows(n: int) -> list[tuple[Any, ...]]:
    """보정 b=0.0 문항 n개에 정답·오답을 번갈아 둔 이력 — θ̂가 b 근처에 앉아 정보량이 최대가 된다."""
    return [(uuid.uuid4(), k % 2 == 0, 3.0, 0.0) for k in range(n)]


class TestCatPathIsRasch:
    """근본 원인 동결 — CAT 진단 경로는 지금 모든 응답을 a=1.0으로 다룬다.

    a가 소비되지 않는 한 이상적 이력(능력=난이도)에서도 44문항은 부족하고 45문항에서야 SE≤0.3이
    된다. EOS-129 ③이 착지해 CAT가 보정 a를 소비하게 되면, 이 이력(보정 a가 없는 문항)은 여전히
    a=1.0 폴백이라 이 테스트는 그대로 성립해야 한다 — 폴백 경로의 하한으로 남는다.
    """

    @pytest.mark.asyncio
    async def test_44_items_are_not_enough(self) -> None:
        state = await nps.load_attempt_history_state(
            _FakeSession(_history_rows(44)),  # type: ignore[arg-type]
            uuid.uuid4(),
        )
        assert state.administered_count == 44
        assert state.standard_error is not None and state.standard_error > 0.3
        assert state.measurement_sufficient is False

    @pytest.mark.asyncio
    async def test_45_items_reach_target_se(self) -> None:
        state = await nps.load_attempt_history_state(
            _FakeSession(_history_rows(45)),  # type: ignore[arg-type]
            uuid.uuid4(),
        )
        assert state.administered_count == 45
        assert state.standard_error is not None and state.standard_error <= 0.3
        assert state.measurement_sufficient is True
