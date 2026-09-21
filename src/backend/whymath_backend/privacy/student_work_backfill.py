"""학생 답안·풀이 봉투 암호화 *백필* ops CLI — 평문 저장된 3테이블 8축 전환 (SEC-31).

`dialogue_content_backfill.py`(감사상환 #2) 선례 미러 — 대화 본문 봉투 암호화가 *신규* 턴만
암호화하고 기존 평문 행은 잔존하듯, 학생 답안/풀이 암호화(`_crypto.build_student_work_cipher`·
api 결선)도 신규 행만 암호화한다. 마스터 키 도입 후 기존 행을 점진 전환하는 *백필* 표면이 여기다.

**3테이블 8축을 함께 처리한다**(EOS-32 §4-6 "부분 배선 = 보호 비대칭" 판정 — 이 태스크의 존재
이유 자체를 재생산하지 않는다):
  - `problem_attempt`: student_answer(text)·handwriting_uri(text)·ocr_result(jsonb)
  - `answer_submission`: raw_response(text)·latex(text)·canonical_ast(jsonb)
  - `student_solution_step`: expression(text·NOT NULL 원본)·canonical_ast(jsonb)

한 테이블만 백필하면 운영자가 `{"problem_attempt": N, ...}`에서 다른 두 테이블을 0으로 보고도
"완료"로 오독할 수 있다 — 그래서 반환값은 항상 **3테이블 키를 전부 포함**한 dict다(0이어도 키
자체는 있다 — 스캔 0건과 "그 테이블은 손대지 않았다"를 구분).

동작(테이블별): 대상 축 중 *하나라도* 평문(`<축>_encrypted IS NULL AND <축> IS NOT NULL`)인
행을 batch_size개까지 골라, **평문인 축만** 암호화해 `<축>_encrypted`/`<축>_nonce`를 채우고
평문 컬럼을 NULL로 비운다. 이미 암호화된 축은 건드리지 않는다(idempotent). 키 미설정(cipher
None)이면 no-op(전부 0). CLI는 각 테이블이 0 반환까지 반복해 전체 백필(대형 테이블 메모리/락
보호 — device `PgDeviceStore.reencrypt_plaintext_secrets`·dialogue_content_backfill 컨벤션
미러: 전역 배치는 HTTP 미노출·스크립트가 직접 돈다).

**SEC-04 함정 주의**(JSONB `none_as_null=True` 이전 행): `ocr_result`·`canonical_ast`처럼 JSONB
컬럼은 `IS NOT NULL`만으로는 부족하다 — JSONB 스칼라 `null`이 저장된 행이 걸려 값 없이 LIMIT
창을 차지하고, 진짜 평문 행이 뒤로 밀려 영영 처리되지 않을 수 있다(2026-07-28 실 PG 재현·
dialogue_content_backfill 모듈 docstring). `jsonb_typeof(...) != 'null'`로 실제 값이 있는
행만 대상에 넣는다.

`student_solution_step.expression`은 원본이 NOT NULL이었다(SEC-31 마이그레이션이 nullable로
완화) — 암호화 시 **평문 컬럼을 NULL로 비우는 것은 다른 축과 동일**하나, 복호 헬퍼
(`resolve_student_solution_step_expression`)가 평문·암호문 둘 다 없으면 RuntimeError로
데이터 무결성 오류를 알린다(조용한 빈 문자열 없음).

사용법:
    python -m whymath_backend.privacy.student_work_backfill [--batch-size N]

`WHYMATH_STUDENT_WORK_ENCRYPTION_KEY` 미설정이면 즉시 전부 0(암호화 비활성). 종료 코드 0.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.api._crypto import SupportsEnvelope, build_student_work_cipher

__all__ = [
    "main",
    "reencrypt_plaintext_answer_submission",
    "reencrypt_plaintext_problem_attempt",
    "reencrypt_plaintext_student_solution_step",
]


def _serialize_json(value: Any) -> str:
    """JSONB 축은 구조라 바이트로 못 바꾼다 — 저장 좌석과 **동일한 결정론 직렬화**를 쓴다.

    `api/_crypto.encrypt_dialogue_image_analysis`(SEC-31 학생 답안/풀이 3테이블이 재사용하는
    JSONB 암호화 경로)와 규칙이 어긋나면 백필한 행만 복호 결과가 달라지므로(재현성 붕괴) 규칙을
    여기서 다시 쓰지 않고 동일 인자로 맞춘다.
    """
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


async def reencrypt_plaintext_problem_attempt(
    session: AsyncSession,
    cipher: SupportsEnvelope | None,
    *,
    batch_size: int = 100,
) -> int:
    """`problem_attempt`의 평문 3축(student_answer·handwriting_uri·ocr_result)을 백필 — 재암호화한
    *행* 수 반환. 계약은 모듈 docstring "동작" 절 참조."""
    if cipher is None:
        return 0
    from whymath_backend.db.models.activity import ProblemAttempt

    plaintext_answer = ProblemAttempt.student_answer_encrypted.is_(
        None
    ) & ProblemAttempt.student_answer.is_not(None)
    plaintext_handwriting = ProblemAttempt.handwriting_uri_encrypted.is_(
        None
    ) & ProblemAttempt.handwriting_uri.is_not(None)
    plaintext_ocr = (
        ProblemAttempt.ocr_result_encrypted.is_(None)
        & ProblemAttempt.ocr_result.is_not(None)
        & (func.jsonb_typeof(ProblemAttempt.ocr_result) != "null")
    )
    sel = (
        select(
            ProblemAttempt.attempt_id,
            ProblemAttempt.student_answer,
            ProblemAttempt.student_answer_encrypted,
            ProblemAttempt.handwriting_uri,
            ProblemAttempt.handwriting_uri_encrypted,
            ProblemAttempt.ocr_result,
            ProblemAttempt.ocr_result_encrypted,
        )
        .where(or_(plaintext_answer, plaintext_handwriting, plaintext_ocr))
        .limit(batch_size)
    )
    result = await session.execute(sel)
    count = 0
    for row in result.all():
        attempt_id, answer, answer_enc, handwriting, handwriting_enc, ocr, ocr_enc = row
        values: dict[str, Any] = {}
        if answer is not None and answer_enc is None:
            ciphertext, nonce = cipher.encrypt(answer)
            values |= {
                "student_answer": None,
                "student_answer_encrypted": ciphertext,
                "student_answer_nonce": nonce,
            }
        if handwriting is not None and handwriting_enc is None:
            ciphertext, nonce = cipher.encrypt(handwriting)
            values |= {
                "handwriting_uri": None,
                "handwriting_uri_encrypted": ciphertext,
                "handwriting_uri_nonce": nonce,
            }
        if ocr is not None and ocr_enc is None:
            ciphertext, nonce = cipher.encrypt(_serialize_json(ocr))
            values |= {
                "ocr_result": None,
                "ocr_result_encrypted": ciphertext,
                "ocr_result_nonce": nonce,
            }
        if not values:  # 방어적 — WHERE로 이미 배제되나 명시(무한 루프 방지)
            continue
        await session.execute(
            update(ProblemAttempt).where(ProblemAttempt.attempt_id == attempt_id).values(**values)
        )
        count += 1
    await session.commit()
    return count


async def reencrypt_plaintext_answer_submission(
    session: AsyncSession,
    cipher: SupportsEnvelope | None,
    *,
    batch_size: int = 100,
) -> int:
    """`answer_submission`의 평문 3축(raw_response·latex·canonical_ast)을 백필 — 재암호화한
    *행* 수 반환. 계약은 모듈 docstring "동작" 절 참조."""
    if cipher is None:
        return 0
    from whymath_backend.db.models.answer_submission import AnswerSubmission

    plaintext_raw = AnswerSubmission.raw_response_encrypted.is_(
        None
    ) & AnswerSubmission.raw_response.is_not(None)
    plaintext_latex = AnswerSubmission.latex_encrypted.is_(None) & AnswerSubmission.latex.is_not(
        None
    )
    plaintext_ast = (
        AnswerSubmission.canonical_ast_encrypted.is_(None)
        & AnswerSubmission.canonical_ast.is_not(None)
        & (func.jsonb_typeof(AnswerSubmission.canonical_ast) != "null")
    )
    sel = (
        select(
            AnswerSubmission.submission_id,
            AnswerSubmission.raw_response,
            AnswerSubmission.raw_response_encrypted,
            AnswerSubmission.latex,
            AnswerSubmission.latex_encrypted,
            AnswerSubmission.canonical_ast,
            AnswerSubmission.canonical_ast_encrypted,
        )
        .where(or_(plaintext_raw, plaintext_latex, plaintext_ast))
        .limit(batch_size)
    )
    result = await session.execute(sel)
    count = 0
    for row in result.all():
        submission_id, raw, raw_enc, latex, latex_enc, ast, ast_enc = row
        values: dict[str, Any] = {}
        if raw is not None and raw_enc is None:
            ciphertext, nonce = cipher.encrypt(raw)
            values |= {
                "raw_response": None,
                "raw_response_encrypted": ciphertext,
                "raw_response_nonce": nonce,
            }
        if latex is not None and latex_enc is None:
            ciphertext, nonce = cipher.encrypt(latex)
            values |= {"latex": None, "latex_encrypted": ciphertext, "latex_nonce": nonce}
        if ast is not None and ast_enc is None:
            ciphertext, nonce = cipher.encrypt(_serialize_json(ast))
            values |= {
                "canonical_ast": None,
                "canonical_ast_encrypted": ciphertext,
                "canonical_ast_nonce": nonce,
            }
        if not values:  # 방어적
            continue
        await session.execute(
            update(AnswerSubmission)
            .where(AnswerSubmission.submission_id == submission_id)
            .values(**values)
        )
        count += 1
    await session.commit()
    return count


async def reencrypt_plaintext_student_solution_step(
    session: AsyncSession,
    cipher: SupportsEnvelope | None,
    *,
    batch_size: int = 100,
) -> int:
    """`student_solution_step`의 평문 2축(expression·canonical_ast)을 백필 — 재암호화한 *행* 수
    반환. `expression`은 원본이 NOT NULL이었으나(SEC-31 마이그레이션이 nullable 완화) 백필
    계약은 다른 축과 동일 — 평문 컬럼을 NULL로 비우고 암호화 컬럼을 채운다(둘 다 없는 행은
    존재해선 안 되며, 복호 헬퍼가 그 상태를 RuntimeError로 알린다)."""
    if cipher is None:
        return 0
    from whymath_backend.db.models.student_solution_step import StudentSolutionStep

    plaintext_expression = StudentSolutionStep.expression_encrypted.is_(
        None
    ) & StudentSolutionStep.expression.is_not(None)
    plaintext_ast = (
        StudentSolutionStep.canonical_ast_encrypted.is_(None)
        & StudentSolutionStep.canonical_ast.is_not(None)
        & (func.jsonb_typeof(StudentSolutionStep.canonical_ast) != "null")
    )
    sel = (
        select(
            StudentSolutionStep.student_step_id,
            StudentSolutionStep.expression,
            StudentSolutionStep.expression_encrypted,
            StudentSolutionStep.canonical_ast,
            StudentSolutionStep.canonical_ast_encrypted,
        )
        .where(or_(plaintext_expression, plaintext_ast))
        .limit(batch_size)
    )
    result = await session.execute(sel)
    count = 0
    for row in result.all():
        student_step_id, expression, expression_enc, ast, ast_enc = row
        values: dict[str, Any] = {}
        if expression is not None and expression_enc is None:
            ciphertext, nonce = cipher.encrypt(expression)
            values |= {
                "expression": None,
                "expression_encrypted": ciphertext,
                "expression_nonce": nonce,
            }
        if ast is not None and ast_enc is None:
            ciphertext, nonce = cipher.encrypt(_serialize_json(ast))
            values |= {
                "canonical_ast": None,
                "canonical_ast_encrypted": ciphertext,
                "canonical_ast_nonce": nonce,
            }
        if not values:  # 방어적
            continue
        await session.execute(
            update(StudentSolutionStep)
            .where(StudentSolutionStep.student_step_id == student_step_id)
            .values(**values)
        )
        count += 1
    await session.commit()
    return count


async def _run_backfill(batch_size: int) -> dict[str, int]:  # pragma: no cover — 실 DB(integration)
    """3테이블 전체 백필 — cipher 조립 후 테이블별 0 반환까지 배치 반복. 테이블별 총 행수 반환.

    반환 dict는 **항상 3키 전부**를 담는다(0이어도) — 부분 처리를 완전 처리로 위장하지 않는다.
    """
    from whymath_backend.config import get_settings
    from whymath_backend.db.session import get_sessionmaker

    settings = get_settings()
    cipher = build_student_work_cipher(settings)
    totals = {"problem_attempt": 0, "answer_submission": 0, "student_solution_step": 0}
    if cipher is None:
        return totals
    sessionmaker = get_sessionmaker(settings)

    for key, fn in (
        ("problem_attempt", reencrypt_plaintext_problem_attempt),
        ("answer_submission", reencrypt_plaintext_answer_submission),
        ("student_solution_step", reencrypt_plaintext_student_solution_step),
    ):
        while True:
            async with sessionmaker() as session:
                n = await fn(session, cipher, batch_size=batch_size)
            totals[key] += n
            if n == 0:
                break
    return totals


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 학생 답안/풀이 평문 3테이블을 봉투 암호화로 전환하고 테이블별 재암호화
    행수 JSON을 stdout에 낸다(`{"problem_attempt": N, "answer_submission": N,
    "student_solution_step": N}`).

    `--batch-size`(기본 100)로 1 배치 크기 조절. 키 미설정이면 전부 0(암호화 비활성·정상).
    종료 코드 0.
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.privacy.student_work_backfill",
        description=(
            "학생 답안/풀이 평문 행(problem_attempt·answer_submission·student_solution_step "
            "3테이블 8축)을 봉투 암호화로 백필 전환 (SEC-31·CLAUDE.md '학생 데이터=민감 정보 "
            "암호화 저장')."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="테이블당 1 배치 재암호화 행 수(기본 100·메모리/락 보호).",
    )
    args = parser.parse_args(argv)
    totals = asyncio.run(_run_backfill(args.batch_size))
    print(json.dumps(totals))
    return 0


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트, main이 테스트 대상
    sys.exit(main())
