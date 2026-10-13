"""시도 버전 고정 헬퍼(`l2/attempt_version_pin`) 단위 테스트 (EOS-47).

DB 없이 가짜 세션의 `get`만으로 검증한다(헬퍼는 PK 조회 1건만 한다). 실 PG에서 문항이 수정된 뒤에도
시도가 원 판을 가리키는 재현성 시나리오는 `tests/backend/db/test_attempt_version_pinning_integration.py`.
"""

from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from whymath_backend.db.models.problem import Problem
from whymath_backend.l2.attempt_version_pin import resolve_attempt_version_pin
from whymath_backend.schema.enums import Curriculum
from whymath_backend.schema.evaluation_context import (
    EVALUATION_CONTEXT_SOURCES,
    EvaluationContext,
)


class _GetSession:
    """`session.get(model, pk)`만 지원하는 가짜 세션 — 호출 기록을 남긴다(DB 조회 횟수 단언용)."""

    def __init__(self, rows: dict[uuid.UUID, Any]) -> None:
        self._rows = rows
        self.get_calls: list[tuple[Any, uuid.UUID]] = []

    async def get(self, model: Any, pk: uuid.UUID) -> Any:
        self.get_calls.append((model, pk))
        return self._rows.get(pk)


def _problem(*, version_id: uuid.UUID | None, curriculum: Any = Curriculum.REVISION_2022) -> Any:
    return SimpleNamespace(problem_version_id=version_id, curriculum_version=curriculum)


async def test_pinned_when_problem_has_a_version_pointer() -> None:
    pid, vid = uuid.uuid4(), uuid.uuid4()
    session = _GetSession({pid: _problem(version_id=vid)})

    pin = await resolve_attempt_version_pin(session, pid)  # type: ignore[arg-type]

    assert pin.outcome == "pinned"
    assert pin.problem_version_id == vid
    assert session.get_calls == [(Problem, pid)]


async def test_no_version_pointer_is_none_not_a_made_up_id() -> None:
    """판이 없는 문항(= 현재 모든 문항) → problem_version_id는 None. 날조 id를 만들지 않는다."""
    pid = uuid.uuid4()
    session = _GetSession({pid: _problem(version_id=None)})

    pin = await resolve_attempt_version_pin(session, pid)  # type: ignore[arg-type]

    assert pin.outcome == "no_version"
    assert pin.problem_version_id is None


async def test_context_is_still_recorded_when_there_is_no_version() -> None:
    """교육과정 라벨은 문항 자체의 사실이라 판이 없어도 기록된다(두 값은 독립)."""
    pid = uuid.uuid4()
    session = _GetSession({pid: _problem(version_id=None, curriculum=Curriculum.REVISION_2015)})

    pin = await resolve_attempt_version_pin(session, pid)  # type: ignore[arg-type]

    assert pin.evaluation_context is not None
    assert pin.evaluation_context["curriculum_version"] == "2015_REVISION"


async def test_unsourced_keys_stay_none_in_the_recorded_context() -> None:
    """핵심 규율 — 출처 표에서 None인 키는 헬퍼가 절대 채우지 않는다.

    표와 헬퍼가 어긋나는 두 방향을 모두 잡는다: ①표에 출처가 없는데 헬퍼가 값을 채움(날조)
    ②표에 출처가 있는데 헬퍼가 안 채움(약속 불이행).
    """
    pid = uuid.uuid4()
    session = _GetSession({pid: _problem(version_id=uuid.uuid4())})

    pin = await resolve_attempt_version_pin(session, pid)  # type: ignore[arg-type]

    assert pin.evaluation_context is not None
    ctx = EvaluationContext.model_validate(pin.evaluation_context)
    filled = {k for k in EVALUATION_CONTEXT_SOURCES if getattr(ctx, k) is not None}
    sourced = {k for k, src in EVALUATION_CONTEXT_SOURCES.items() if src}
    assert (
        filled == sourced
    ), f"헬퍼가 채운 키 {sorted(filled)} ≠ 출처 표가 허용한 키 {sorted(sourced)}"


async def test_curriculum_label_accepts_plain_string_value_too() -> None:
    """ORM이 enum 멤버 대신 값 문자열을 돌려줘도 같은 라벨이 된다(직렬화 위치 단일화)."""
    pid = uuid.uuid4()
    session = _GetSession({pid: _problem(version_id=None, curriculum="2009_REVISION")})

    pin = await resolve_attempt_version_pin(session, pid)  # type: ignore[arg-type]

    assert pin.evaluation_context is not None
    assert pin.evaluation_context["curriculum_version"] == "2009_REVISION"


async def test_problem_missing_records_nothing() -> None:
    session = _GetSession({})

    pin = await resolve_attempt_version_pin(session, uuid.uuid4())  # type: ignore[arg-type]

    assert pin.outcome == "problem_missing"
    assert pin.problem_version_id is None
    assert pin.evaluation_context is None


async def test_no_problem_id_skips_the_database_entirely() -> None:
    session = _GetSession({})

    pin = await resolve_attempt_version_pin(session, None)  # type: ignore[arg-type]

    assert pin.outcome == "no_problem"
    assert pin.problem_version_id is None
    assert pin.evaluation_context is None
    assert session.get_calls == [], "problem_id가 없는데 DB를 읽었다"


async def test_read_failure_propagates_instead_of_being_swallowed() -> None:
    """읽기 실패는 삼키지 않는다 — 실패한 트랜잭션 뒤의 INSERT는 어차피 불가하고, 삼키면 첫 원인이 가려진다."""

    class _Boom:
        async def get(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("db down")

    with pytest.raises(RuntimeError, match="db down"):
        await resolve_attempt_version_pin(_Boom(), uuid.uuid4())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("version_present", "expected_outcome"),
    [(True, "pinned"), (False, "no_version")],
)
async def test_outcome_is_logged_for_the_worked_rate(
    caplog: pytest.LogCaptureFixture, version_present: bool, expected_outcome: str
) -> None:
    """'작동한 비율' — 고정이 실제로 일했는지(pinned/no_version)를 로그가 센다."""
    pid = uuid.uuid4()
    session = _GetSession({pid: _problem(version_id=uuid.uuid4() if version_present else None)})

    with caplog.at_level(logging.INFO, logger="whymath_backend.l2.attempt_version_pin"):
        await resolve_attempt_version_pin(session, pid)  # type: ignore[arg-type]

    assert any(f"outcome={expected_outcome}" in r.getMessage() for r in caplog.records)
