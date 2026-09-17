"""EOS-105 정책 증거 조립기 — 연속 실패 계수·reactive 오개념 조회 (hermetic).

이 파일이 지키는 것 3가지:
  ① **모른다 ≠ 아니다** — 미채점(`is_correct IS NULL`) 이력이 연속 오답을 *끊는다*. 접으면
     미채점 기록이 학생을 교정 국면으로 밀어 넣는다(CLAUDE.md 3상태를 2상태로 접기 금지).
  ② **오개념 reactive 조회** — 정답일 때는 오개념 쿼리를 **돌리지 않는다**(preload 금지).
  ③ **미측정 확신도 보존** — `None`을 0.0으로 채우지 않는다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.l2.learning_state_evidence import (
    CONSECUTIVE_FAILURE_SCAN_LIMIT,
    build_attempt_evidence,
)
from whymath_backend.schema.learning_state import REPEATED_FAILURE_THRESHOLD

_UID = uuid.UUID("99999999-8888-7777-6666-555555555555")


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return [r if isinstance(r, tuple) else (r,) for r in self._rows]

    def scalars(self) -> _Rows:
        return _Scalars(self._rows)  # type: ignore[return-value]


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


@dataclass
class _FakeSession:
    """두 질의(attempt 이력 · 오개념 가설)를 렌더된 SQL로 구분한다.

    호출 **순서**로 구분하지 않는 이유: 조립기가 질의 순서를 바꾸면 테스트가 엉뚱한 데이터를
    주면서도 통과할 수 있다. 무엇을 묻는지로 답한다.
    """

    attempt_history: list[bool | None] = field(default_factory=list)
    misconceptions: list[str] = field(default_factory=list)
    misconception_queries: int = 0
    observed_limit: int | None = None

    async def execute(self, stmt: Any) -> _Rows:
        rendered = str(stmt)
        if "misconception_hypothesis" in rendered:
            self.misconception_queries += 1
            return _Rows(list(self.misconceptions))
        # 실 DB처럼 LIMIT을 **실제로 적용한다**. 적용하지 않으면 "상한이 걸려 있다"를 재는
        # 테스트가 가짜 세션의 관대함 덕에 통과하거나 실패해, 상한의 유무와 무관해진다.
        rows = list(self.attempt_history)
        limit = getattr(stmt, "_limit", None)
        self.observed_limit = limit
        if limit is not None:
            rows = rows[:limit]
        return _Rows(rows)


def _session(**kwargs: Any) -> tuple[AsyncSession, _FakeSession]:
    fake = _FakeSession(**kwargs)
    return cast(AsyncSession, fake), fake


@pytest.mark.asyncio
async def test_correct_answer_resets_the_failure_streak_to_zero() -> None:
    """정답이면 연속 오답은 0 — 이번에 끊겼기 때문이다."""
    session, _ = _session(attempt_history=[False, False, False])
    evidence = await build_attempt_evidence(session, user_id=_UID, is_correct=True)
    assert evidence.consecutive_failures == 0


@pytest.mark.asyncio
async def test_wrong_answer_counts_itself_plus_the_preceding_streak() -> None:
    """이번 오답 1 + 직전 연속 오답 2 = 3 → R5 임계에 정확히 닿는다."""
    session, _ = _session(attempt_history=[False, False, True])
    evidence = await build_attempt_evidence(session, user_id=_UID, is_correct=False)
    assert evidence.consecutive_failures == REPEATED_FAILURE_THRESHOLD


@pytest.mark.asyncio
async def test_a_correct_attempt_in_history_breaks_the_streak() -> None:
    session, _ = _session(attempt_history=[True, False, False])
    evidence = await build_attempt_evidence(session, user_id=_UID, is_correct=False)
    assert evidence.consecutive_failures == 1


@pytest.mark.asyncio
async def test_ungraded_history_breaks_the_streak_instead_of_counting_as_failure() -> None:
    """**모른다 ≠ 아니다** — 미채점(None)은 연속 오답을 끊는다.

    `None`을 실패로 접으면 채점되지 않은 기록만으로 학생이 교정 국면(REMEDIATING)에 들어간다.
    그것은 없는 사실로 학생을 처치하는 것이다.
    """
    session, _ = _session(attempt_history=[None, False, False])
    evidence = await build_attempt_evidence(session, user_id=_UID, is_correct=False)
    assert (
        evidence.consecutive_failures == 1
    ), "미채점 이력이 실패로 계상됐습니다 — 3상태를 2상태로 접었습니다"


@pytest.mark.asyncio
async def test_failure_scan_is_bounded() -> None:
    """무제한 스캔하지 않는다 — 상한을 넘겨도 판정(임계 이상)은 같다."""
    session, fake = _session(attempt_history=[False] * (CONSECUTIVE_FAILURE_SCAN_LIMIT + 50))
    evidence = await build_attempt_evidence(session, user_id=_UID, is_correct=False)
    assert (
        fake.observed_limit == CONSECUTIVE_FAILURE_SCAN_LIMIT
    ), "이력 스캔에 LIMIT이 걸려 있지 않습니다 — 오래 쓴 학생에서 제출 경로가 느려집니다"
    # 상한에서 잘려도 판정(임계 **이상**)은 같다 — 정확한 개수는 R5의 결정을 바꾸지 않는다.
    assert evidence.consecutive_failures == CONSECUTIVE_FAILURE_SCAN_LIMIT + 1
    assert evidence.consecutive_failures >= REPEATED_FAILURE_THRESHOLD


@pytest.mark.asyncio
async def test_misconceptions_are_not_preloaded_on_a_correct_answer() -> None:
    """정답이면 오개념 쿼리를 **돌리지 않는다** — reactive retrieval(CLAUDE.md 금기).

    쿼리 결과가 비어 있는지가 아니라 **질의 자체가 없었는지**를 센다. 결과만 보면 "빈 결과를
    받아 버렸다"와 "묻지 않았다"가 같은 값으로 보인다.
    """
    session, fake = _session(misconceptions=["M-frac-01"])
    evidence = await build_attempt_evidence(session, user_id=_UID, is_correct=True)
    assert fake.misconception_queries == 0, "정답 맥락에서 오개념을 preload했습니다"
    assert evidence.confirmed_misconception_ids == ()


@pytest.mark.asyncio
async def test_misconceptions_are_retrieved_on_a_wrong_answer() -> None:
    session, fake = _session(misconceptions=["M-frac-01", "M-frac-02"])
    evidence = await build_attempt_evidence(session, user_id=_UID, is_correct=False)
    assert fake.misconception_queries == 1
    assert evidence.confirmed_misconception_ids == ("M-frac-01", "M-frac-02")


@pytest.mark.asyncio
async def test_unmeasured_confidence_stays_none_instead_of_becoming_zero() -> None:
    """미측정 확신도는 `None`으로 남는다 — 0.0은 "확신 없음"이라는 다른 사실이다."""
    session, _ = _session()
    evidence = await build_attempt_evidence(session, user_id=_UID, is_correct=True)
    assert evidence.confidence is None


@pytest.mark.asyncio
async def test_prerequisite_gaps_come_from_the_caller_not_from_this_module() -> None:
    """선수결손은 호출부가 넣어 준다 — 조립기는 그것을 계산하지 않는다(생산자 미배선 명시).

    기본값이 비어 있다는 사실 자체가 계약이다. 비어 있으면 R4가 매치되지 않는다는 것을
    이 테스트가 못 박아, "규칙은 있는데 영원히 안 도는" 상태를 숨기지 않는다.
    """
    session, _ = _session()
    default_evidence = await build_attempt_evidence(session, user_id=_UID, is_correct=False)
    assert default_evidence.prerequisite_gap_concept_ids == ()

    injected = await build_attempt_evidence(
        session,
        user_id=_UID,
        is_correct=False,
        prerequisite_gap_concept_ids=["C-prereq-01"],
    )
    assert injected.prerequisite_gap_concept_ids == ("C-prereq-01",)
