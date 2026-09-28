"""EOS-132 — 추천이 소비한 LearnerState의 근거 식별자(`LearnerStateBasis`) 단위테스트 (hermetic).

근거는 KPI⑤ 역추적의 LearnerState 홉이다. 그래서 세 축을 각각 반례로 고정한다:
  · **캡처** — 한 문장으로 세 근거를 읽고, 없는 근거는 사유와 함께 비운다(지어내지 않는다).
  · **직렬화** — meta에 식별자·시각만 싣고, 비어 있는 근거는 `absent` 사유로 말한다.
  · **되읽기** — 형식이 하나라도 어긋나면 None(추측으로 채우지 않는다). 역추적 게이트는 None을
    '읽을 수 없다'(끊김)로 센다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from whymath_backend.l2.learner_state import (
    LEARNER_STATE_BASIS_SCHEMA,
    BasisAbsence,
    LearnerStateBasis,
    MasteryBasis,
    capture_state_basis,
)

_UID = uuid.uuid4()
_C = uuid.uuid4()
_S = uuid.uuid4()
_H1 = uuid.UUID("00000000-0000-4000-8000-000000000002")
_H2 = uuid.UUID("00000000-0000-4000-8000-000000000001")
_MEASURED = datetime(2026, 9, 28, 8, 0, 0, 123456, tzinfo=UTC)
_ASSEMBLED = datetime(2026, 9, 28, 8, 5, tzinfo=UTC)


class _Result:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row

    def first(self) -> tuple[Any, ...] | None:
        return self._row


class _RecordingSession:
    """실행 문장을 기록하고 미리 준 한 행을 돌려준다."""

    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> _Result:
        self.statements.append(stmt)
        return _Result(self._row)


def _sql(stmt: Any) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


class TestCapture:
    async def test_reads_all_three_bases_in_one_statement(self) -> None:
        session = _RecordingSession((_C, _MEASURED, _S, [_H1, _H2]))
        basis = await capture_state_basis(session, _UID, assembled_at=_ASSEMBLED)  # type: ignore[arg-type]
        assert len(session.statements) == 1  # 세 근거가 같은 스냅샷을 본다
        assert basis.mastery == MasteryBasis(concept_id=_C, measured_at=_MEASURED)
        assert basis.ability_snapshot_id == _S
        assert basis.assembled_at == _ASSEMBLED
        # 순서는 의미가 없다 — 재현되도록 문자열 순으로 고정한다.
        assert basis.misconception_hypothesis_ids == (_H2, _H1)

    async def test_student_without_history_gets_absent_bases(self) -> None:
        session = _RecordingSession((None, None, None, None))
        basis = await capture_state_basis(session, _UID, assembled_at=_ASSEMBLED)  # type: ignore[arg-type]
        assert basis.mastery is None
        assert basis.ability_snapshot_id is None
        assert basis.misconception_hypothesis_ids == ()

    async def test_half_a_mastery_key_is_not_a_key(self) -> None:
        # 개념만 있고 시각이 없으면 행을 특정할 수 없다 — 반쪽 키를 근거로 싣지 않는다.
        session = _RecordingSession((_C, None, None, None))
        basis = await capture_state_basis(session, _UID, assembled_at=_ASSEMBLED)  # type: ignore[arg-type]
        assert basis.mastery is None

    async def test_no_row_from_a_test_double_reads_as_absent(self) -> None:
        basis = await capture_state_basis(
            _RecordingSession(None), _UID, assembled_at=_ASSEMBLED  # type: ignore[arg-type]
        )
        assert (basis.mastery, basis.ability_snapshot_id) == (None, None)

    async def test_statement_scopes_each_basis_to_this_learner(self) -> None:
        session = _RecordingSession(None)
        await capture_state_basis(session, _UID, assembled_at=_ASSEMBLED)  # type: ignore[arg-type]
        sql = _sql(session.statements[0])
        # 최신 숙달 행 — 동률(한 채점이 여러 개념을 같은 시각으로 적재)은 개념 id로 끊는다.
        assert sql.count("ORDER BY concept_mastery_history.measured_at DESC,") == 2
        assert "concept_mastery_history.concept_id" in sql
        # 전과목 θ — `get_current_theta`와 같은 범위(개념 NULL).
        assert "ability_snapshot.concept_id IS NULL" in sql
        # 활성 가설만.
        assert "misconception_hypothesis.is_active IS true" in sql
        assert sql.count("user_id = ") >= 4  # 네 서브쿼리 전부 이 학습자로 제한

    async def test_capture_writes_nothing(self) -> None:
        session = _RecordingSession(None)
        await capture_state_basis(session, _UID, assembled_at=_ASSEMBLED)  # type: ignore[arg-type]
        assert _sql(session.statements[0]).lstrip().upper().startswith("SELECT")


def _basis(**override: Any) -> LearnerStateBasis:
    fields: dict[str, Any] = {
        "assembled_at": _ASSEMBLED,
        "mastery": MasteryBasis(concept_id=_C, measured_at=_MEASURED),
        "ability_snapshot_id": _S,
        "misconception_hypothesis_ids": (_H1,),
    }
    fields.update(override)
    return LearnerStateBasis(**fields)


class TestMetaRoundTrip:
    def test_round_trip_is_exact_to_the_microsecond(self) -> None:
        basis = _basis()
        assert LearnerStateBasis.from_meta(basis.to_meta()) == basis

    def test_absent_bases_carry_their_reason(self) -> None:
        meta = _basis(mastery=None, ability_snapshot_id=None).to_meta()
        assert meta["mastery"] == {"absent": BasisAbsence.NO_MASTERY_HISTORY.value}
        assert meta["ability_snapshot"] == {"absent": BasisAbsence.NO_ABILITY_SNAPSHOT.value}
        parsed = LearnerStateBasis.from_meta(meta)
        assert parsed is not None and parsed.mastery is None and parsed.ability_snapshot_id is None

    def test_meta_carries_identifiers_and_times_only(self) -> None:
        meta = _basis().to_meta()
        assert set(meta) == {
            "schema",
            "assembled_at",
            "mastery",
            "ability_snapshot",
            "misconception_hypothesis_ids",
        }
        assert meta["schema"] == LEARNER_STATE_BASIS_SCHEMA
        assert set(meta["mastery"]) == {"concept_id", "measured_at"}


def _malformed(mutate: Any) -> dict[str, Any]:
    meta = _basis().to_meta()
    mutate(meta)
    return meta


@pytest.mark.parametrize(
    "value",
    [
        None,
        "not a mapping",
        _malformed(lambda m: m.update(schema=2)),  # 다른 판본
        _malformed(lambda m: m.pop("schema")),
        _malformed(lambda m: m.update(assembled_at="2026-09-28T08:05:00")),  # 시간대 없음
        _malformed(lambda m: m.update(assembled_at=12345)),
        _malformed(lambda m: m.update(mastery={"absent": "who_knows"})),  # 모르는 부재 사유
        _malformed(lambda m: m.update(mastery={"absent": "no_mastery_history", "x": 1})),
        _malformed(lambda m: m.update(mastery={"concept_id": str(_C)})),  # 시각 없음
        _malformed(lambda m: m.update(mastery={"concept_id": "bad", "measured_at": "x"})),
        _malformed(lambda m: m.update(mastery=None)),  # 부재는 None이 아니라 사유로 말한다
        _malformed(lambda m: m.update(ability_snapshot={"absent": "no_mastery_history"})),
        _malformed(lambda m: m.update(ability_snapshot={"snapshot_id": "bad"})),
        _malformed(lambda m: m.update(misconception_hypothesis_ids="h1")),  # 목록이 아님
        _malformed(lambda m: m.update(misconception_hypothesis_ids=["bad"])),
    ],
)
def test_any_malformation_reads_as_none(value: Any) -> None:
    assert LearnerStateBasis.from_meta(value) is None


def test_absent_marker_is_not_confused_with_a_present_key() -> None:
    # 부재 사유가 있는 객체에 키가 섞이면 형식 불량이다 — 한쪽으로 반올림하지 않는다.
    meta = _basis().to_meta()
    meta["ability_snapshot"] = {"absent": "no_ability_snapshot", "snapshot_id": str(_S)}
    assert LearnerStateBasis.from_meta(meta) is None


def test_assembled_at_keeps_its_offset() -> None:
    kst = datetime(2026, 9, 28, 17, 5, tzinfo=UTC) + timedelta(0)
    parsed = LearnerStateBasis.from_meta(_basis(assembled_at=kst).to_meta())
    assert parsed is not None and parsed.assembled_at == kst
