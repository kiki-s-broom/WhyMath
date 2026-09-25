"""EOS-131 학습 세션 writer — hermetic 계약 동결(DB 없이).

실 DB 동작(유휴 규칙·동시성·조회 시점 확정)은 `test_learning_session_writer_integration.py`가
실 PostgreSQL로 본다. 이 파일은 DB 없이 판정 가능한 계약만 고정한다:
  ① 유휴 간격 상수는 30분이고 모듈 안에 **한 곳**에만 있다.
  ② 이 writer는 `focus_score`·`engagement_score`를 **절대** 쓰지 않는다(S3-16 ③ 유지) — 산출물
     검사(AST)로 본다. 문자열이 아니라 *쓰기 대상 이름*을 찾는다.
  ③ 서빙 경로 래퍼는 never-break이되 **침묵하지 않는다** — 예외 타입명 로그·인프로세스 회계.
  ④ naive 시각은 거부한다(asyncpg가 서버 로컬 TZ로 오해석).
"""

from __future__ import annotations

import ast
import logging
import pathlib
import uuid
from datetime import datetime, timedelta
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.l2 import learning_session_writer as writer

_MODULE = pathlib.Path(writer.__file__)


def _tree() -> ast.Module:
    source = _MODULE.read_text(encoding="utf-8")
    assert source.strip(), f"writer 모듈이 비었다: {_MODULE}"
    return ast.parse(source)


class TestIdleGapConstant:
    def test_idle_gap_is_thirty_minutes(self) -> None:
        assert timedelta(minutes=30) == writer.IDLE_GAP

    def test_idle_gap_is_defined_in_exactly_one_place(self) -> None:
        """`timedelta(...)` 리터럴이 모듈에 1개뿐이다 — 두 번째 경계값이 생기면 규칙이 갈라진다."""
        calls = [
            node
            for node in ast.walk(_tree())
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "timedelta"
        ]
        assert len(calls) == 1, f"timedelta 리터럴이 {len(calls)}개 — IDLE_GAP 한 곳이어야 한다"


class TestNeverWritesScores:
    """S3-16 ③ 점수 미신설 유지 — writer가 점수 컬럼을 건드리면 RED(EOS-131 ③)."""

    _SCORES = frozenset({"focus_score", "engagement_score"})

    def test_no_score_column_is_named_anywhere_in_the_writer(self) -> None:
        """속성 접근·키워드 인자·문자열 키 어디에도 점수 컬럼이 없다(쓰기 대상 산출물 검사)."""
        hits: list[str] = []
        for node in ast.walk(_tree()):
            if isinstance(node, ast.Attribute) and node.attr in self._SCORES:
                hits.append(f"attr {node.attr}@{node.lineno}")
            elif isinstance(node, ast.keyword) and node.arg in self._SCORES:
                hits.append(f"kw {node.arg}@{node.lineno}")
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in self._SCORES
            ):
                hits.append(f"str {node.value}@{node.lineno}")
        assert hits == [], f"writer가 점수 컬럼을 언급한다(S3-16 ③ 위반): {hits}"

    def test_the_scan_is_not_vacuous(self) -> None:
        """스캐너 변별력 — 같은 모듈에서 실제로 쓰는 컬럼(`last_activity_at`)은 잡혀야 한다."""
        attrs = {n.attr for n in ast.walk(_tree()) if isinstance(n, ast.Attribute)}
        keywords = {n.arg for n in ast.walk(_tree()) if isinstance(n, ast.keyword)}
        assert "last_activity_at" in attrs
        assert "last_activity_at" in keywords


class _BrokenSession:
    """`begin_nested`가 터지는 세션 — never-break 래퍼의 실패 경로 주입."""

    def begin_nested(self) -> Any:
        raise ConnectionResetError("주입된 연결 실패")


class TestNeverBreakButNotSilent:
    async def test_record_returns_none_and_logs_the_exception_type(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        before = writer.failure_count()
        with caplog.at_level(logging.WARNING, logger="whymath.l2.learning_session_writer"):
            result = await writer.record_learning_activity(
                cast(AsyncSession, _BrokenSession()), user_id=uuid.uuid4()
            )
        assert result is None
        assert writer.failure_count() == before + 1
        assert "ConnectionResetError" in caplog.text

    async def test_close_best_effort_returns_zero_and_logs_the_exception_type(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        before = writer.failure_count()
        with caplog.at_level(logging.WARNING, logger="whymath.l2.learning_session_writer"):
            closed = await writer.close_idle_sessions_best_effort(
                cast(AsyncSession, _BrokenSession()), user_id=uuid.uuid4()
            )
        assert closed == 0
        assert writer.failure_count() == before + 1
        assert "ConnectionResetError" in caplog.text


class TestNaiveTimeRejected:
    async def test_naive_now_is_rejected_before_any_query(self) -> None:
        class _Exploding:
            def __getattr__(self, name: str) -> Any:  # pragma: no cover - 호출되면 실패다
                raise AssertionError(f"naive 시각인데 DB를 건드렸다: {name}")

        with pytest.raises(ValueError, match="timezone-aware"):
            await writer.touch_learning_session(
                cast(AsyncSession, _Exploding()),
                user_id=uuid.uuid4(),
                now=datetime(2026, 9, 25, 9, 0),  # noqa: DTZ001 — naive 주입이 목적
            )
