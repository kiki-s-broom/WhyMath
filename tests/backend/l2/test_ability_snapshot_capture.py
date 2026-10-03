"""채점 경계 θ 스냅샷 자동 적재 단위테스트 (hermetic) — EOS-125 처분 (가).

적재 시점 판정(콜드스타트·stride)·빈 θ 미적재·never-break(예외 타입명 로그)를 가짜 세션으로
검증한다. 실 PG 왕복(쿼리 정확성)은 통합테스트가 맡는다 — `mastery_tracking` 단위/통합 분리 패턴.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.assessment import AbilitySnapshot
from whymath_backend.l2 import ability_snapshot_capture as mod
from whymath_backend.l2.ability_snapshot_capture import (
    CAPTURE_STRIDE,
    AbilityCaptureOutcome,
    capture_global_ability_if_due,
)
from whymath_backend.l2.ability_tracking import AbilityReading

_UID = uuid.uuid4()


class _FakeSession:
    def __init__(self, *, commit_error: Exception | None = None) -> None:
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self._commit_error = commit_error

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        if self._commit_error is not None:
            raise self._commit_error
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    latest_count: int | None,
    graded: int,
    estimate: tuple[float, float | None, int] = (0.7, 0.4, 3),
) -> dict[str, int]:
    """읽기 3종을 고정한다. 반환 dict로 추정(무거운 쿼리) 호출 횟수를 센다."""
    calls = {"estimate": 0}

    async def _latest(_s: Any, _u: uuid.UUID) -> AbilityReading | None:
        if latest_count is None:
            return None
        return AbilityReading(theta=0.1, standard_error=0.5, response_count=latest_count)

    async def _count(_s: Any, _u: uuid.UUID) -> int:
        return graded

    async def _estimate(_s: Any, _u: uuid.UUID) -> tuple[float, float | None, int]:
        calls["estimate"] += 1
        return estimate

    monkeypatch.setattr(mod, "get_current_ability", _latest)
    monkeypatch.setattr(mod, "_count_graded_attempts", _count)
    monkeypatch.setattr(mod, "estimate_global_ability", _estimate)
    return calls


async def _run(session: _FakeSession) -> AbilityCaptureOutcome:
    return await capture_global_ability_if_due(cast(AsyncSession, session), _UID)


async def test_cold_start_captures_after_first_graded_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """스냅샷이 아직 없으면 첫 채점 직후 1건 적재 — 루프 학습자의 general_ability가 null이 아니게."""
    _wire(monkeypatch, latest_count=None, graded=1, estimate=(0.7, 0.9, 1))
    s = _FakeSession()
    assert await _run(s) is AbilityCaptureOutcome.CAPTURED
    assert s.commits == 1 and len(s.added) == 1
    row = s.added[0]
    assert isinstance(row, AbilitySnapshot)
    assert row.concept_id is None  # 전과목 곡선만 — 개념별은 이 모듈의 범위 밖
    assert (row.user_id, row.theta, row.standard_error, row.response_count) == (
        _UID,
        0.7,
        0.9,
        1,
    )


async def test_below_stride_skips_without_estimating(monkeypatch: pytest.MonkeyPatch) -> None:
    """마지막 스냅샷 이후 채점이 stride 미만이면 건너뛴다 — 무거운 추정도 돌리지 않는다."""
    calls = _wire(monkeypatch, latest_count=10, graded=10 + CAPTURE_STRIDE - 1)
    s = _FakeSession()
    assert await _run(s) is AbilityCaptureOutcome.NOT_DUE
    assert s.added == [] and s.commits == 0
    assert calls["estimate"] == 0


async def test_at_stride_captures_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """정확히 stride건 쌓이면(경계값) 적재한다 — `>=` 경계 동결."""
    calls = _wire(monkeypatch, latest_count=10, graded=10 + CAPTURE_STRIDE)
    s = _FakeSession()
    assert await _run(s) is AbilityCaptureOutcome.CAPTURED
    assert calls["estimate"] == 1 and s.commits == 1


async def test_empty_theta_is_not_captured(monkeypatch: pytest.MonkeyPatch) -> None:
    """난이도 b를 못 정해 응답이 0건이면 빈 θ를 적재하지 않는다(세션 종료 적재와 같은 규칙)."""
    _wire(monkeypatch, latest_count=None, graded=2, estimate=(0.0, None, 0))
    s = _FakeSession()
    assert await _run(s) is AbilityCaptureOutcome.NO_RESPONSES
    assert s.added == [] and s.commits == 0


async def test_failure_is_swallowed_with_exception_type_in_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """적재 실패는 채점을 깨지 않는다 — 삼키되 예외 *타입명*을 경고로 남기고 롤백한다."""
    _wire(monkeypatch, latest_count=None, graded=1)
    s = _FakeSession(commit_error=ConnectionError("secret-detail"))
    with caplog.at_level(logging.WARNING, logger="whymath.l2.ability_snapshot_capture"):
        assert await _run(s) is AbilityCaptureOutcome.FAILED
    assert s.rollbacks == 1
    assert "ConnectionError" in caplog.text
    assert "secret-detail" not in caplog.text  # 값·메시지는 로그에 싣지 않는다
