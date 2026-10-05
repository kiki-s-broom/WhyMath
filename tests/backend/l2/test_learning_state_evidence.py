"""EOS-105 정책 증거 조립기 — 연속 실패 계수·R3 입력 필터 (hermetic).

이 파일이 지키는 것 4가지:
  ① **모른다 ≠ 아니다** — 미채점(`is_correct IS NULL`) 이력이 연속 오답을 *끊는다*. 접으면
     미채점 기록이 학생을 교정 국면으로 밀어 넣는다(CLAUDE.md 3상태를 2상태로 접기 금지).
  ② **오개념 preload 금지** — 정답이면 오개념 id를 싣지 않고, 어떤 경우에도 가설 테이블을
     **조회하지 않는다**(EOS-138 ② — 학생 전체 활성 가설을 읽던 경로 제거).
  ③ **R3 입력 = 이번 응답 스캔 후보 중 하한 초과**(EOS-138 ②) — 경계 0.7은 제외·0.7001은 포함,
     신뢰 내림차순·동률 id 오름차순, 중복 id는 최고 신뢰 하나, 망가진 신뢰는 거부.
  ④ **미측정 확신도 보존** — `None`을 0.0으로 채우지 않는다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.l2 import learning_state_evidence
from whymath_backend.l2.learning_state_evidence import (
    CONSECUTIVE_FAILURE_SCAN_LIMIT,
    build_attempt_evidence,
)
from whymath_backend.l2.remediation_policy import MISCONCEPTION_REMEDIATION_FLOOR
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
    """질의를 렌더된 SQL로 구분한다 — attempt 이력, 그리고 **있어선 안 되는** 오개념 가설 조회.

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
    """정답이면 오개념 id를 싣지 않는다 — 넘겨받은 강한 후보가 있어도(preload 금지).

    쿼리 결과가 비어 있는지가 아니라 **질의 자체가 없었는지**도 센다. 결과만 보면 "빈 결과를
    받아 버렸다"와 "묻지 않았다"가 같은 값으로 보인다.
    """
    session, fake = _session(misconceptions=["M-frac-01"])
    evidence = await build_attempt_evidence(
        session,
        user_id=_UID,
        is_correct=True,
        this_attempt_misconceptions=[("M-frac-01", 0.95)],
    )
    assert fake.misconception_queries == 0, "정답 맥락에서 오개념을 preload했습니다"
    assert evidence.confirmed_misconception_ids == ()


@pytest.mark.asyncio
async def test_hypothesis_table_is_never_read_even_on_a_wrong_answer() -> None:
    """EOS-138 ② — 오답이어도 학생 전체 활성 가설을 읽지 않는다.

    가짜 세션에 옛 가설을 심어 둔다. 조립기가 그것을 읽으면 R3 입력에 "M-stale"이 나타난다
    (종전 동작 — 다른 개념의 옛 가설이 이번 오답의 교정 대상이 되던 반례 S1).
    """
    session, fake = _session(misconceptions=["M-stale"])
    evidence = await build_attempt_evidence(session, user_id=_UID, is_correct=False)
    assert fake.misconception_queries == 0, "가설 테이블을 조회했습니다 — 옛 가설이 R3로 샙니다"
    assert evidence.confirmed_misconception_ids == ()


@pytest.mark.asyncio
async def test_unscanned_wrong_answer_has_no_r3_input() -> None:
    """스캔이 돌지 않은 회차(호출부가 빈 값을 넘김) → R3 입력 없음."""
    session, _ = _session()
    evidence = await build_attempt_evidence(
        session, user_id=_UID, is_correct=False, this_attempt_misconceptions=()
    )
    assert evidence.confirmed_misconception_ids == ()


class TestR3InputFilter:
    """이번 응답 후보 → R3 입력: 하한 **초과**·정렬·중복 제거·입력 검증 (EOS-138 ②)."""

    @staticmethod
    async def _ids(pairs: list[tuple[str, float]]) -> tuple[str, ...]:
        session, _ = _session()
        evidence = await build_attempt_evidence(
            session, user_id=_UID, is_correct=False, this_attempt_misconceptions=pairs
        )
        return evidence.confirmed_misconception_ids

    # 값은 리터럴로 적는다 — 상수에서 파생하면 하한이 옮겨질 때 픽스처도 함께 옮겨진다.
    @pytest.mark.parametrize(
        ("confidence", "included"),
        [
            (0.6999, False),  # 바로 아래
            (0.7, False),  # 정확히 — "초과"라 제외
            (0.7001, True),  # 바로 위
            (1.0, True),
        ],
    )
    @pytest.mark.asyncio
    async def test_floor_is_exclusive(self, confidence: float, included: bool) -> None:
        ids = await self._ids([("M-a", confidence)])
        assert ids == (("M-a",) if included else ())

    @pytest.mark.asyncio
    async def test_sorted_by_confidence_descending(self) -> None:
        ids = await self._ids([("M-low", 0.75), ("M-high", 0.95), ("M-mid", 0.85)])
        assert ids == ("M-high", "M-mid", "M-low")

    @pytest.mark.asyncio
    async def test_ties_break_by_id_ascending_regardless_of_input_order(self) -> None:
        """동률에서 입력 순서를 따르면 같은 사실이 호출마다 다른 `target_misconception_id`를 낸다."""
        forward = await self._ids([("M-b", 0.9), ("M-a", 0.9)])
        backward = await self._ids([("M-a", 0.9), ("M-b", 0.9)])
        assert forward == backward == ("M-a", "M-b")

    @pytest.mark.asyncio
    async def test_duplicate_ids_are_merged_keeping_the_highest_confidence(self) -> None:
        """중복 id는 하나로 — 신뢰는 가장 높은 쪽으로 정렬 위치가 정해진다."""
        ids = await self._ids([("M-dup", 0.72), ("M-other", 0.8), ("M-dup", 0.9)])
        assert ids == ("M-dup", "M-other")

    @pytest.mark.asyncio
    async def test_duplicate_below_floor_does_not_resurrect_an_excluded_id(self) -> None:
        ids = await self._ids([("M-dup", 0.5), ("M-dup", 0.7)])
        assert ids == ()

    @pytest.mark.parametrize("bad", [float("nan"), -0.1, 1.5])
    @pytest.mark.asyncio
    async def test_malformed_confidence_is_rejected_not_dropped(self, bad: float) -> None:
        """NaN은 모든 비교가 거짓이라 조용히 "하한 이하"로 떨어진다 — 침묵 대신 거부한다."""
        with pytest.raises(ValueError, match="0~1"):
            await self._ids([("M-bad", bad)])

    @pytest.mark.parametrize("shift", [+0.01, -0.01])
    @pytest.mark.asyncio
    async def test_floor_shift_mutation_flips_the_boundary_fixture(
        self, monkeypatch: pytest.MonkeyPatch, shift: float
    ) -> None:
        """하한을 한 칸 옮기면 그 사이의 탐침 판정이 뒤집힌다 — 필터가 하한을 **실제로** 읽는가."""
        original = learning_state_evidence.MISCONCEPTION_REMEDIATION_FLOOR
        assert original == MISCONCEPTION_REMEDIATION_FLOOR == 0.7
        probe = original + shift / 2
        before = await self._ids([("M-a", probe)])

        mutated = original + shift
        monkeypatch.setattr(learning_state_evidence, "MISCONCEPTION_REMEDIATION_FLOOR", mutated)
        assert (
            learning_state_evidence.MISCONCEPTION_REMEDIATION_FLOOR != original
        ), "뮤테이션 미적용 — 아래 판정은 무의미하다."

        assert await self._ids([("M-a", probe)]) != before


@pytest.mark.asyncio
async def test_unmeasured_confidence_stays_none_instead_of_becoming_zero() -> None:
    """미측정 확신도는 `None`으로 남는다 — 0.0은 "확신 없음"이라는 다른 사실이다."""
    session, _ = _session()
    evidence = await build_attempt_evidence(session, user_id=_UID, is_correct=True)
    assert evidence.confidence is None


def test_prerequisite_gap_is_not_an_evidence_field_anymore() -> None:
    """선수 결손은 정책 증거가 아니다 — 필드도 조립기 인자도 없다(EOS-127 (나) 처분).

    종전에는 `prerequisite_gap_concept_ids`가 열려 있었으나 서빙 경로가 한 번도 채우지 않아 R4가
    발화하지 않았다. "선언만 있고 집행이 없는" 입구를 다시 열면 같은 상태가 재발하므로, 필드와
    인자의 **부재**를 동결한다. 선수 하강은 다음 문항 선택(R6 경로)이 맡는다.
    """
    import inspect

    from whymath_backend.schema.learning_state import AttemptEvidence

    assert "prerequisite_gap_concept_ids" not in AttemptEvidence.model_fields
    assert (
        "prerequisite_gap_concept_ids" not in inspect.signature(build_attempt_evidence).parameters
    )
