"""api/study.py `_build_signals` PED-05 리팩터 회귀 — `get_state()` 경유 dict lookup.

예전엔 `compute_concept_diagnoses`를 직접 호출해 결과 리스트를 순회하며 `concept_code`
일치 항목을 찾았다. 이제 `get_state()`(l2 조립기)를 호출해 그 `mastery`/`domain_abilities`
dict에서 O(1) lookup한다. 이 테스트는 *같은 값*이 나오는지(비트동일)를 hermetic으로 확인한다
(`tests/backend/l2/test_learner_state.py`의 `_QueueSession` 관례 재사용 — get_state() 내부
execute() 4회 순서: ①BKT ②IRT abilities ③전과목 θ ④활성 오개념).
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.api.study import _build_signals

_UID = uuid.uuid4()


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class _QueueSession:
    """`get_state()`가 여는 4회 execute() + 1회 get()(user_profile — study.py는 미사용)."""

    def __init__(self, results: list[list[Any]]) -> None:
        self._results = list(results)

    async def execute(self, _stmt: Any) -> _Result:
        return _Result(self._results.pop(0))

    async def get(self, _model: Any, _pk: Any) -> None:
        return None


def _session(
    *,
    bkt_rows: list[Any] | None = None,
    ability_rows: list[Any] | None = None,
    theta_rows: list[Any] | None = None,
    misconception_rows: list[Any] | None = None,
    skill_rows: list[Any] | None = None,
) -> AsyncSession:
    """`_build_signals` → `get_state()`의 execute 큐 — 순서가 조립기 계약이다.

    ①BKT 숙달 ②개념별 IRT ③전과목 θ ④활성 오개념 ⑤스킬별 최신 숙달(EOS-10).
    큐가 마르면 `IndexError`가 나므로 조립기의 쿼리가 *늘어나면* 반드시 발각된다 —
    실제로 EOS-10이 ⑤를 추가했을 때 이 하네스가 그렇게 잡았다.
    """
    return cast(
        AsyncSession,
        _QueueSession(
            [
                bkt_rows or [],
                ability_rows or [],
                theta_rows or [],
                misconception_rows or [],
                skill_rows or [],
            ]
        ),
    )


class TestBuildSignals:
    async def test_bkt_mastery_present_yields_mastery_level_and_bkt(self) -> None:
        cid = uuid.uuid4()
        session = _session(bkt_rows=[(cid, "MATH-A", "개념A", 0.9)])
        signals = await _build_signals(session, _UID, "MATH-A")
        assert signals.bkt_mastery == 0.9
        assert signals.mastery_level == "숙달"  # >= 0.8
        assert signals.irt_theta is None

    async def test_only_irt_theta_present_falls_back_to_proxy_for_level(self) -> None:
        cid = uuid.uuid4()
        # is_correct=True·difficulty=3.0(중간) → 어떤 유한 θ가 나온다(정확한 값은 무관 — 폴백 경로
        # 자체가 작동하는지가 관심사).
        session = _session(ability_rows=[(cid, "MATH-B", "개념B", True, 3.0, None)])
        signals = await _build_signals(session, _UID, "MATH-B")
        assert signals.bkt_mastery is None
        assert signals.irt_theta is not None
        # BKT 없음 → IRT 프록시로 폴백해 mastery_level이 채워진다(None이 아님).
        assert signals.mastery_level is not None

    async def test_no_match_yields_default_signals(self) -> None:
        cid = uuid.uuid4()
        session = _session(bkt_rows=[(cid, "OTHER-CONCEPT", "다른개념", 0.5)])
        signals = await _build_signals(session, _UID, "MATH-NOT-PRESENT")
        assert signals.mastery_level is None
        assert signals.bkt_mastery is None
        assert signals.irt_theta is None

    async def test_no_diagnoses_at_all_yields_default_signals(self) -> None:
        session = _session()
        signals = await _build_signals(session, _UID, "MATH-ANY")
        assert signals.mastery_level is None
        assert signals.bkt_mastery is None
        assert signals.irt_theta is None
