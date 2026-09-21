"""SEC-31: `api/coach.py::_complete_problem`의 학생 답안 봉투 암호화 배선 — hermetic.

`api/me.py::submit_attempt`(test_me.py::TestSubmitAttempt)와 *같은 헬퍼*(encrypt_dialogue_content
+ require_student_work_cipher)를 재사용하므로 두 ProblemAttempt 적재 경로가 같은 보호를 받아야
한다(부분 배선 방지 — 이 태스크의 존재 이유). `_complete_problem`을 직접 호출해 L2 숙달 전파
헬퍼(mastery_tracking 등)는 monkeypatch로 no-op 처리하고(DB 무접근), attempt 적재 자체만
격리 검증한다.
"""

from __future__ import annotations

import asyncio
import base64
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from whymath_backend.api import coach as coach_module
from whymath_backend.api._crypto import SecretCipher
from whymath_backend.config import get_settings

_ENV_VAR = "WHYMATH_STUDENT_WORK_ENCRYPTION_KEY"


@contextmanager
def _student_work_key_env(key_b64: str | None) -> Iterator[None]:
    prev = os.environ.get(_ENV_VAR)
    if key_b64 is None:
        os.environ.pop(_ENV_VAR, None)
    else:
        os.environ[_ENV_VAR] = key_b64
    get_settings.cache_clear()
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop(_ENV_VAR, None)
        else:
            os.environ[_ENV_VAR] = prev
        get_settings.cache_clear()


class _EmptyResult:
    """모든 조회가 0행 — 문항-개념 미매핑 상태(이 파일의 관심은 암호화이지 매핑이 아니다)."""

    def all(self) -> list[Any]:
        return []

    def scalars(self) -> "_EmptyResult":
        return self


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.commits = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def execute(self, _stmt: Any) -> _EmptyResult:
        """EOS-12 증거 조립이 개념·스킬을 조회한다 — 스텁하지 않고 *실제로* 돌린다.

        스텁하면 이 경로가 증거를 만드는지 아닌지를 이 파일이 말할 수 없게 된다. 0행을
        돌려주면 "문항-개념 미매핑" 상태의 증거가 나오고, 그것으로 충분하다.
        """
        return _EmptyResult()


async def _noop_mastery(*_args: Any, **_kwargs: Any) -> list[Any]:
    return []


async def _noop_skill_event(*_args: Any, **_kwargs: Any) -> None:
    return None


@pytest.fixture(autouse=True)
def _stub_l2_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    """attempt 적재 자체만 보되, 숙달 전파 L2 헬퍼는 DB 무접근 no-op으로 대체."""
    monkeypatch.setattr(coach_module, "record_problem_attempt_mastery", _noop_mastery)
    monkeypatch.setattr(coach_module, "record_problem_attempt_skill_mastery", _noop_mastery)
    monkeypatch.setattr(coach_module, "record_attempt_skill_event", _noop_skill_event)


def test_plaintext_when_key_unset() -> None:
    """키 미설정(기존 동작) — student_answer는 평문·암호화 컬럼은 None."""
    session = _FakeSession()
    with _student_work_key_env(None):
        attempt_id, evidence = asyncio.run(
            coach_module._complete_problem(
                session,  # type: ignore[arg-type]
                user_id=uuid.uuid4(),
                problem_id=uuid.uuid4(),
                final_answer="x=3",
                started_at=None,
            )
        )
    assert attempt_id is not None
    # EOS-12: 완료 채점이 증거를 함께 낸다. 이 픽스처는 문항-개념 미매핑이라 증거는 비지만,
    # 그 0건이 "보지 않았다"로 정직하게 표기되는지까지가 계약이다.
    assert evidence is not None
    assert evidence.attempt_id == attempt_id
    assert evidence.correct is True
    assert evidence.coverage.concept.value == "not_measured"
    assert evidence.coverage.misconception_scan.value == "not_run"
    assert len(session.added) == 1
    attempt = session.added[0]
    assert attempt.student_answer == "x=3"
    assert attempt.student_answer_encrypted is None
    assert attempt.student_answer_nonce is None


def test_encrypts_when_key_configured() -> None:
    """키 설정 시 — student_answer는 NULL·암호화 컬럼에 실리고 같은 키로 복호하면 원문 그대로.

    `api/me.py::submit_attempt`와 *같은* student_work 키를 공유하므로(SEC-31 acceptance③), 두
    적재 경로 중 하나만 암호화되는 보호 비대칭이 생기지 않는다.
    """
    session = _FakeSession()
    key_b64 = base64.b64encode(os.urandom(32)).decode()
    with _student_work_key_env(key_b64):
        attempt_id, evidence = asyncio.run(
            coach_module._complete_problem(
                session,  # type: ignore[arg-type]
                user_id=uuid.uuid4(),
                problem_id=uuid.uuid4(),
                final_answer="x=5",
                started_at=None,
            )
        )
    assert attempt_id is not None
    attempt = session.added[0]
    assert attempt.student_answer is None
    assert attempt.student_answer_encrypted is not None
    assert attempt.student_answer_nonce is not None
    cipher = SecretCipher(base64.b64decode(key_b64))
    assert cipher.decrypt(attempt.student_answer_encrypted, attempt.student_answer_nonce) == "x=5"


def test_none_final_answer_produces_no_ciphertext() -> None:
    """final_answer가 None(정답이 이전 턴에 이미 확인된 케이스)이면 암호화 대상 자체가 없다."""
    session = _FakeSession()
    key_b64 = base64.b64encode(os.urandom(32)).decode()
    with _student_work_key_env(key_b64):
        asyncio.run(
            coach_module._complete_problem(
                session,  # type: ignore[arg-type]
                user_id=uuid.uuid4(),
                problem_id=uuid.uuid4(),
                final_answer=None,
                started_at=None,
            )
        )
    attempt = session.added[0]
    assert attempt.student_answer is None
    assert attempt.student_answer_encrypted is None
    assert attempt.student_answer_nonce is None
