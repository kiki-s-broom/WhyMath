"""`l2/learner_state_store.py` 계약 — 자동 생성·단일 변경·부재 시 명시적 실패 (EOS-103).

**측정 경계(정직 표기)**: 이 파일은 hermetic 단위 테스트다 — 실 PG 왕복이 없으므로
`server_default`(gen_random_uuid·now()·revision 1)의 *DB 측* 동작은 여기서 검증되지 않는다.
검증 대상은 **store 함수의 계약**이다: 멱등성, `UNSET`↔`None` 구별, 부재 시 예외, revision
증가. 스키마 자체의 왕복은 마이그레이션·`test_learner_state_orm.py`가 본다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from whymath_backend.db.models.learner_state import LearnerStateRecord
from whymath_backend.l2.learner_state_store import (
    UNSET,
    LearnerStateMissingError,
    LearnerStateMutation,
    PersistedLearnerState,
    apply_learner_state_mutation,
    load_learner_state,
    provision_learner_state,
    require_learner_state,
)

_LEARNER = uuid.UUID("22222222-2222-2222-2222-222222222222")


class _FakeSession:
    """`session.get`/`add`/`flush`만 제공하는 최소 표면 — store가 쓰는 것이 그뿐이다.

    `get`은 PK 단건 조회를 dict lookup으로 흉내 낸다. commit은 **일부러 제공하지 않는다** —
    store가 commit을 부르면 AttributeError로 즉시 드러나야 한다(트랜잭션 경계는 호출부 소유).
    """

    def __init__(self, rows: dict[uuid.UUID, LearnerStateRecord] | None = None) -> None:
        self._rows: dict[uuid.UUID, LearnerStateRecord] = dict(rows or {})
        self.flush_count = 0

    async def get(self, model: type[Any], pk: uuid.UUID) -> Any:
        assert model is LearnerStateRecord
        return self._rows.get(pk)

    def add(self, obj: Any) -> None:
        self._rows[obj.learner_id] = obj

    async def flush(self) -> None:
        self.flush_count += 1


def _existing(**overrides: Any) -> LearnerStateRecord:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    defaults: dict[str, Any] = {
        "learner_id": _LEARNER,
        "curriculum_id": None,
        "current_objective_id": None,
        "provisioned_at": now,
        "provisioned_by": "diagnosis_capture",
        "updated_at": now,
        "revision": 1,
    }
    defaults.update(overrides)
    return LearnerStateRecord(**defaults)


# ── 자동 생성 (acceptance ②) ──────────────────────────────────────────────
async def test_provision_creates_row_when_absent() -> None:
    """행이 없으면 만든다 — 운영자가 DB를 직접 건드릴 필요가 없다."""
    session = _FakeSession()
    state = await provision_learner_state(
        session, _LEARNER, reason="diagnosis_capture"  # type: ignore[arg-type]
    )
    assert isinstance(state, PersistedLearnerState)
    assert state.learner_id == _LEARNER
    assert state.provisioned_by == "diagnosis_capture"
    assert state.revision == 1
    assert await load_learner_state(session, _LEARNER) is not None


async def test_provision_is_idempotent_and_keeps_original_lineage() -> None:
    """재호출해도 새 행을 만들지 않고 `provisioned_at`·`provisioned_by`를 덮어쓰지 않는다.

    최초 생성 계보는 사실이다 — 나중 호출이 그것을 고쳐 쓰면 "무엇이 이 상태를 만들었는가"가
    거짓이 된다.
    """
    original = _existing(provisioned_by="diagnosis_capture")
    session = _FakeSession({_LEARNER: original})
    state = await provision_learner_state(
        session, _LEARNER, reason="backfill"  # type: ignore[arg-type]
    )
    assert state.provisioned_by == "diagnosis_capture"
    assert state.provisioned_at == original.provisioned_at
    assert session.flush_count == 0  # 쓰기 자체가 일어나지 않았다


async def test_provision_carries_curriculum_id_on_creation() -> None:
    session = _FakeSession()
    state = await provision_learner_state(
        session,
        _LEARNER,
        reason="diagnosis_capture",  # type: ignore[arg-type]
        curriculum_id="2022-math",
    )
    assert state.curriculum_id == "2022-math"


# ── 부재 시 명시적 실패 (acceptance ④) ────────────────────────────────────
async def test_require_raises_when_absent() -> None:
    """기본값 객체를 돌려주지 않는다 — 조용한 진행 경로는 존재하지 않는다."""
    session = _FakeSession()
    with pytest.raises(LearnerStateMissingError) as exc:
        await require_learner_state(session, _LEARNER)
    assert exc.value.learner_id == _LEARNER


async def test_load_returns_none_not_a_default_object() -> None:
    """부재를 `None`으로 돌려준다 — 호출부가 타입으로 처리하도록 강제한다."""
    assert await load_learner_state(_FakeSession(), _LEARNER) is None


async def test_mutation_does_not_create_rows() -> None:
    """변경 경로가 조용히 행을 만들면 진단 없이 상태가 생기는 우회로가 열린다."""
    session = _FakeSession()
    with pytest.raises(LearnerStateMissingError):
        await apply_learner_state_mutation(
            session, _LEARNER, LearnerStateMutation(current_objective_id="obj-1")
        )
    assert await load_learner_state(session, _LEARNER) is None


# ── 단일 변경 경로의 의미론 (acceptance ③·⑤) ─────────────────────────────
async def test_unset_fields_are_left_alone() -> None:
    """지정하지 않은 필드는 건드리지 않는다 — 부분 갱신이 다른 필드를 지우면 안 된다."""
    session = _FakeSession({_LEARNER: _existing(curriculum_id="2022-math")})
    state = await apply_learner_state_mutation(
        session, _LEARNER, LearnerStateMutation(current_objective_id="obj-1")
    )
    assert state.curriculum_id == "2022-math"  # UNSET이라 보존
    assert state.current_objective_id == "obj-1"


async def test_explicit_none_clears_the_field() -> None:
    """`None`을 명시하면 비운다 — `UNSET`("건드리지 않음")과 구별된다."""
    session = _FakeSession({_LEARNER: _existing(curriculum_id="2022-math")})
    state = await apply_learner_state_mutation(
        session, _LEARNER, LearnerStateMutation(curriculum_id=None)
    )
    assert state.curriculum_id is None


async def test_revision_increments_only_on_actual_change() -> None:
    """빈 변경은 revision을 올리지 않는다 — 이중 회계 축이 잡음으로 오염되면 못 쓴다."""
    session = _FakeSession({_LEARNER: _existing(revision=3)})
    unchanged = await apply_learner_state_mutation(session, _LEARNER, LearnerStateMutation())
    assert unchanged.revision == 3
    assert session.flush_count == 0

    changed = await apply_learner_state_mutation(
        session, _LEARNER, LearnerStateMutation(curriculum_id="2015-math")
    )
    assert changed.revision == 4
    assert session.flush_count == 1


async def test_updated_at_moves_on_change() -> None:
    old = datetime(2026, 1, 1, tzinfo=UTC)
    session = _FakeSession({_LEARNER: _existing(updated_at=old)})
    state = await apply_learner_state_mutation(
        session, _LEARNER, LearnerStateMutation(current_objective_id="obj-2")
    )
    assert state.updated_at > old


def test_mutation_defaults_are_unset_not_none() -> None:
    """확장 좌석의 기본값은 `UNSET`이다 — None이면 새 필드가 생길 때마다 기존 값이 지워진다."""
    mutation = LearnerStateMutation()
    assert mutation.curriculum_id is UNSET
    assert mutation.current_objective_id is UNSET
    assert mutation.assignments() == {}
