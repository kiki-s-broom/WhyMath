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

from whymath_backend.config import get_settings
from whymath_backend.db.models.assessment import AbilitySnapshot
from whymath_backend.l2 import ability_snapshot_capture as mod
from whymath_backend.l2.ability_snapshot_capture import (
    CAPTURE_STRIDE,
    AbilityCaptureOutcome,
    capture_global_ability_if_due,
)
from whymath_backend.l2.ability_tracking import AbilityReading

_UID = uuid.uuid4()
_MIN = get_settings().l4_theta_min_responses  # 코치 노이즈 가드와 같은 신뢰 하한


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


async def test_cold_start_captures_once_evidence_is_reliable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """스냅샷이 없어도 신뢰 하한(응답 수·SE)을 처음 넘는 채점에서 1건 적재 — general_ability가 열린다."""
    _wire(monkeypatch, latest_count=None, graded=_MIN, estimate=(0.7, 0.9, _MIN))
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
        _MIN,
    )


async def test_below_min_responses_is_not_captured_and_not_estimated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """응답 수가 하한 미만이면 적재하지 않는다 — 코치 전과목 θ 폴백이 1건짜리 θ를 읽지 않게.

    (실측 사고: 첫 채점 직후 θ를 적재했더니 코치 힌트 사다리가 바뀌었다 — EOS-133 통합테스트.)
    무거운 추정도 돌리지 않는다.
    """
    calls = _wire(monkeypatch, latest_count=None, graded=_MIN - 1, estimate=(4.0, 0.5, _MIN - 1))
    s = _FakeSession()
    assert await _run(s) is AbilityCaptureOutcome.UNRELIABLE
    assert s.added == [] and s.commits == 0
    assert calls["estimate"] == 0


async def test_unmeasurable_standard_error_is_not_captured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """응답 수가 충분해도 SE가 None(전부 정답 등 정보 0 — θ가 극단)이면 적재하지 않는다.

    stride 재적재에서도 확인한다 — 신뢰하던 θ를 극단값으로 덮지 않는다.
    """
    for latest in (None, 10):
        _wire(
            monkeypatch,
            latest_count=latest,
            graded=_MIN if latest is None else 10 + CAPTURE_STRIDE,
            estimate=(4.0, None, _MIN),
        )
        s = _FakeSession()
        assert await _run(s) is AbilityCaptureOutcome.UNRELIABLE
        assert s.added == [] and s.commits == 0


async def test_large_standard_error_is_still_captured(monkeypatch: pytest.MonkeyPatch) -> None:
    """SE가 크더라도(측정 가능하면) 적재한다 — `l4_theta_max_se`는 걸지 않는다(짧게 푸는 학습자 보호).

    기본 상한 1.0은 6건을 풀어도 못 넘는다(SE 1.13 실측). SE는 행에 실려 소비처가 구분한다.
    """
    _wire(monkeypatch, latest_count=None, graded=_MIN, estimate=(0.1, 1.24, _MIN))
    s = _FakeSession()
    assert await _run(s) is AbilityCaptureOutcome.CAPTURED


async def test_below_stride_skips_without_estimating(monkeypatch: pytest.MonkeyPatch) -> None:
    """마지막 스냅샷 이후 채점이 stride 미만이면 건너뛴다 — 무거운 추정도 돌리지 않는다."""
    calls = _wire(monkeypatch, latest_count=10, graded=10 + CAPTURE_STRIDE - 1)
    s = _FakeSession()
    assert await _run(s) is AbilityCaptureOutcome.NOT_DUE
    assert s.added == [] and s.commits == 0
    assert calls["estimate"] == 0


async def test_at_stride_captures_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """정확히 stride건 쌓이면(경계값) 적재한다 — `>=` 경계 동결."""
    calls = _wire(monkeypatch, latest_count=10, graded=10 + CAPTURE_STRIDE, estimate=(0.7, 0.4, 15))
    s = _FakeSession()
    assert await _run(s) is AbilityCaptureOutcome.CAPTURED
    assert calls["estimate"] == 1 and s.commits == 1


async def test_empty_theta_is_not_captured(monkeypatch: pytest.MonkeyPatch) -> None:
    """난이도 b를 못 정해 응답이 0건이면 빈 θ를 적재하지 않는다(세션 종료 적재와 같은 규칙)."""
    _wire(monkeypatch, latest_count=None, graded=_MIN, estimate=(0.0, None, 0))
    s = _FakeSession()
    assert await _run(s) is AbilityCaptureOutcome.NO_RESPONSES
    assert s.added == [] and s.commits == 0


async def test_failure_is_swallowed_with_exception_type_in_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """적재 실패는 채점을 깨지 않는다 — 삼키되 예외 *타입명*을 경고로 남기고 롤백한다."""
    _wire(monkeypatch, latest_count=None, graded=_MIN, estimate=(0.7, 0.4, _MIN))
    s = _FakeSession(commit_error=ConnectionError("secret-detail"))
    with caplog.at_level(logging.WARNING, logger="whymath.l2.ability_snapshot_capture"):
        assert await _run(s) is AbilityCaptureOutcome.FAILED
    assert s.rollbacks == 1
    assert "ConnectionError" in caplog.text
    assert "secret-detail" not in caplog.text  # 값·메시지는 로그에 싣지 않는다
