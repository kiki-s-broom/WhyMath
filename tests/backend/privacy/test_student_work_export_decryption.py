"""SEC-31: `privacy/export.py`의 학생 답안/풀이 3테이블 복호 표면 — hermetic(FakeSession).

`test_export.py`의 조립 로직 검증과 별개로, 여기서는 **암호화 행이 실제로 복호되어 export에
평문으로 실리는지**를 검증한다(감사상환 #2 `test_dialogue_content_encryption_integration.py`가
실 PG로 검증하는 것과 같은 계약을 이 3테이블에 대해 hermetic으로 검증 — `export_user_data`는
FakeSession으로 대체 가능해 실 PG 불요).

  ① **암호화 행 복호** — student_answer_encrypted 등만 있고 평문 컬럼이 NULL이어도 export에는
     평문이 실린다(GDPR 열람권 완전성 — 부분 export를 완전 export로 위장하지 않는다).
  ② **`student_solution_step.expression`의 to_schema() 순서 함정** — 암호화 행에서 ORM
     `expression`이 NULL이므로 `to_schema()`를 먼저 부르면 ValidationError가 난다(모듈
     docstring이 명시한 이유). `_student_work_row_json`은 복호를 먼저 적용해 이 함정을 피한다.
  ③ **키 유실 시 시끄러운 실패** — 암호화 행인데 cipher 미설정이면 RuntimeError(조용한 빈
     export 금지 — CLAUDE.md 침묵 실패 금지).
"""

from __future__ import annotations

import asyncio
import base64
import os
import uuid
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.api._crypto import MultiKeyCipher, SecretCipher
from whymath_backend.config import get_settings
from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.db.models.answer_submission import AnswerSubmission
from whymath_backend.db.models.student_solution_step import StudentSolutionStep
from whymath_backend.privacy.export import export_user_data

_ENC_KEY_B64 = base64.b64encode(os.urandom(32)).decode()
_ENV_VAR = "WHYMATH_STUDENT_WORK_ENCRYPTION_KEY"


def _cipher() -> MultiKeyCipher:
    return MultiKeyCipher(SecretCipher(base64.b64decode(_ENC_KEY_B64)))


class _FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeSession:
    """`_EXPORT_PLAN` 순서대로 큐를 소비 + dialogue_turn 조인·profile 조회는 빈 결과."""

    def __init__(self, category_rows: dict[type, list[Any]]) -> None:
        self._category_rows = category_rows
        self.executed: list[Any] = []

    async def execute(self, stmt: Any) -> _FakeResult:
        self.executed.append(stmt)
        # SELECT 대상 모델을 froms/description으로 추정 — `_EXPORT_PLAN` 순회는 select(model)이라
        # `stmt.column_descriptions[0]["entity"]`가 그 모델이다(dialogue_turn 조인·profile도
        # 동일 API로 안전하게 얻어짐 — 매칭 없으면 빈 리스트).
        try:
            entity = stmt.column_descriptions[0]["entity"]
        except Exception:  # pragma: no cover - 방어적
            entity = None
        return _FakeResult(self._category_rows.get(entity, []))

    async def commit(self) -> None:  # pragma: no cover - 읽기 전용 경로 미호출
        raise AssertionError("export는 읽기 전용이어야 한다(commit 호출됨)")

    async def flush(self) -> None:  # pragma: no cover
        raise AssertionError("export는 읽기 전용이어야 한다(flush 호출됨)")


def _run(session: _FakeSession, user_id: uuid.UUID) -> Any:
    return asyncio.run(export_user_data(cast(AsyncSession, session), user_id=user_id))


@pytest.fixture
def _student_work_key_env() -> Any:
    """`WHYMATH_STUDENT_WORK_ENCRYPTION_KEY`를 env로 주입하고 `get_settings` 캐시를 리셋·원복
    (`test_dialogue_content_encryption_integration.py`의 `_dialogue_key_env` 패턴 미러)."""
    prev = os.environ.get(_ENV_VAR)
    os.environ[_ENV_VAR] = _ENC_KEY_B64
    get_settings.cache_clear()
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop(_ENV_VAR, None)
        else:
            os.environ[_ENV_VAR] = prev
        get_settings.cache_clear()


def test_encrypted_rows_are_decrypted_in_export(_student_work_key_env: Any) -> None:
    """① 암호화 행(평문 컬럼 NULL) 3테이블 전부가 export에서 평문으로 복원된다."""
    cipher = _cipher()
    user_id = uuid.uuid4()

    answer_ct, answer_nonce = cipher.encrypt("학생 제출 답안 원문")
    pa_row = ProblemAttempt(
        attempt_id=uuid.uuid4(),
        user_id=user_id,
        is_correct=True,
        student_answer=None,
        student_answer_encrypted=answer_ct,
        student_answer_nonce=answer_nonce,
        step_times=[],
    )

    raw_ct, raw_nonce = cipher.encrypt("asb 제출 원문")
    asb_row = AnswerSubmission(
        submission_id=uuid.uuid4(),
        attempt_id=uuid.uuid4(),
        user_id=user_id,
        sequence_no=1,
        response_type="text",
        raw_response=None,
        raw_response_encrypted=raw_ct,
        raw_response_nonce=raw_nonce,
    )

    expr_ct, expr_nonce = cipher.encrypt("x^2 - 4 = 0")
    sss_row = StudentSolutionStep(
        student_step_id=uuid.uuid4(),
        attempt_id=uuid.uuid4(),
        user_id=user_id,
        sequence_no=1,
        expression=None,  # 암호화 행 — ORM상 NULL(SEC-31 nullable 완화)
        expression_encrypted=expr_ct,
        expression_nonce=expr_nonce,
        concept_ids=[],
    )

    fake = _FakeSession(
        {ProblemAttempt: [pa_row], AnswerSubmission: [asb_row], StudentSolutionStep: [sss_row]}
    )
    out = _run(fake, user_id)

    assert out.data["problem_attempts"][0]["student_answer"] == "학생 제출 답안 원문"
    assert out.data["answer_submissions"][0]["raw_response"] == "asb 제출 원문"
    assert out.data["student_solution_steps"][0]["expression"] == "x^2 - 4 = 0"


def test_missing_cipher_on_encrypted_row_raises_loud(_student_work_key_env: Any) -> None:
    """③ 키 유실 — get_settings 캐시를 지운 채 키를 지우면(암호화 행은 실재) RuntimeError."""
    cipher = _cipher()
    user_id = uuid.uuid4()
    answer_ct, answer_nonce = cipher.encrypt("원문")
    pa_row = ProblemAttempt(
        attempt_id=uuid.uuid4(),
        user_id=user_id,
        student_answer=None,
        student_answer_encrypted=answer_ct,
        student_answer_nonce=answer_nonce,
        step_times=[],
    )
    fake = _FakeSession({ProblemAttempt: [pa_row]})

    # 키를 지운 채(개발 환경 판정 유지) 실행 — require_student_work_cipher가 None을 돌려주고
    # resolve 헬퍼가 "암호화 행인데 cipher 없음"을 RuntimeError로 노출해야 한다.
    os.environ.pop(_ENV_VAR, None)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            _run(fake, user_id)
    finally:
        os.environ[_ENV_VAR] = _ENC_KEY_B64
        get_settings.cache_clear()
