"""학생 답안/풀이 봉투 암호화 백필 CLI 단위테스트 — no-op 분기 (SEC-31, hermetic).

키 미설정(cipher None)이면 세션을 건드리지 않고 0을 반환하는지 3테이블 전부 격리 검증한다
(DB 무접근). 실제 배치 재암호화(평문 행 → 암호화)는 @integration(실 PG)에서 검증
(`dialogue_content_backfill` 선례와 동일 제약 — 이 저장소에 실 PG 불요).
"""

from __future__ import annotations

import asyncio
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.privacy.student_work_backfill import (
    reencrypt_plaintext_answer_submission,
    reencrypt_plaintext_problem_attempt,
    reencrypt_plaintext_student_solution_step,
)


class _ExplodingSession:
    """접근 시 폭발하는 세션 — cipher None 경로가 세션을 안 건드림을 증명."""

    async def execute(self, stmt: object) -> object:  # pragma: no cover - 호출되면 실패
        raise AssertionError("cipher None인데 세션을 접근했다(no-op 위반)")

    async def commit(self) -> None:  # pragma: no cover
        raise AssertionError("cipher None인데 commit했다")


@pytest.mark.parametrize(
    "fn",
    [
        reencrypt_plaintext_problem_attempt,
        reencrypt_plaintext_answer_submission,
        reencrypt_plaintext_student_solution_step,
    ],
)
def test_noop_when_cipher_none_does_not_touch_session(fn: object) -> None:
    """cipher None(키 미설정)이면 3테이블 함수 전부 0 반환·세션 무접근(암호화 비활성 no-op)."""
    session = cast(AsyncSession, _ExplodingSession())
    result = asyncio.run(fn(session, None, batch_size=50))  # type: ignore[operator]
    assert result == 0
