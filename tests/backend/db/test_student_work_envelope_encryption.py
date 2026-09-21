"""SEC-31: 학생 답안/풀이 3테이블 봉투 암호화 — 전수 배선 스캔 (부분 배선 방지, hermetic).

EOS-32 §4-6이 "일괄 후속"으로 유보한 답안 계열 3테이블(problem_attempt·answer_submission·
student_solution_step)의 봉투 암호화를 이 태스크가 일괄 해소한다. 이 테스트가 동결하는 것은
*그 "일괄"이 실제로 일괄인가*다 — 8쌍 16컬럼 중 어느 하나라도 빠지면(부분 배선) 이 태스크의
존재 이유(EOS-32 §4-6 "단일 테이블 선행 암호화는 보호 비대칭" 판정 재생산 금지)가 무너진다.

검증 축:
  ① 8쌍 16컬럼이 3모델 전부에 정확히 존재(LargeBinary·nullable)
  ② `_NON_SCHEMA_COLUMNS`가 그 16컬럼과 *정확히* 일치(초과·누락 없음 — schema round-trip 오염
     방지 축과 partial-exclusion 방지 축을 동시에 검사)
  ③ `student_solution_step.expression`만 원본 NOT NULL → nullable로 완화(다른 7개는 생성부터
     nullable — dialogue_turn.content 선례와 동형)
  ④ 마이그레이션 파일 1개가 16 add_column + 1 alter_column(nullable 완화)을 대칭 up/down으로
     담고 있다
  ⑤ 백필 CLI(`student_work_backfill.py`)가 3테이블 함수를 모두 export한다(한 테이블만 백필
     가능한 상태 방지)
"""

from __future__ import annotations

from pathlib import Path

from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.db.models.answer_submission import AnswerSubmission
from whymath_backend.db.models.student_solution_step import StudentSolutionStep

_REPO_ROOT = Path(__file__).resolve().parents[3]
_VERSIONS_DIR = _REPO_ROOT / "src" / "backend" / "alembic" / "versions"
_MIGRATION_REVISION = "3f5c83f51246"
_MIGRATION_DOWN_REVISION = "4c6dfb1527a9"

# 모델 → 대상 컬럼(암호화 축 이름) — acceptance①의 대상 전수 그대로.
_TARGET_COLUMNS: dict[type, tuple[str, ...]] = {
    ProblemAttempt: ("student_answer", "handwriting_uri", "ocr_result"),
    AnswerSubmission: ("raw_response", "latex", "canonical_ast"),
    StudentSolutionStep: ("expression", "canonical_ast"),
}


def _encrypted_pair_names(base: str) -> tuple[str, str]:
    return f"{base}_encrypted", f"{base}_nonce"


class TestEnvelopeColumnsPresentAcrossAllThreeTables:
    """① 8쌍 16컬럼 전수 — 어느 모델도 절반만 배선되지 않는다."""

    def test_each_target_column_has_encrypted_and_nonce_pair(self) -> None:
        total_pairs = 0
        for model, targets in _TARGET_COLUMNS.items():
            columns = model.__table__.columns
            for base in targets:
                enc_name, nonce_name = _encrypted_pair_names(base)
                assert enc_name in columns, f"{model.__name__}.{enc_name} 누락(부분 배선)"
                assert nonce_name in columns, f"{model.__name__}.{nonce_name} 누락(부분 배선)"
                assert columns[enc_name].nullable is True
                assert columns[nonce_name].nullable is True
                import sqlalchemy as sa

                assert isinstance(columns[enc_name].type, sa.LargeBinary)
                assert isinstance(columns[nonce_name].type, sa.LargeBinary)
                total_pairs += 1
        assert total_pairs == 8, f"8쌍이어야 한다(실제 {total_pairs}) — 대상 전수 변경 시 갱신"

    def test_non_schema_columns_exactly_match_envelope_pairs(self) -> None:
        """②`_NON_SCHEMA_COLUMNS`가 암호화 8쌍과 정확히 일치 — 초과(ciphertext 노출 위험 컬럼
        누락)도 누락(schema round-trip ValidationError)도 없어야 한다."""
        for model, targets in _TARGET_COLUMNS.items():
            expected = {name for base in targets for name in _encrypted_pair_names(base)}
            actual = model._NON_SCHEMA_COLUMNS  # type: ignore[attr-defined]
            assert actual == expected, (
                f"{model.__name__}._NON_SCHEMA_COLUMNS 불일치 — "
                f"기대={sorted(expected)} 실제={sorted(actual)}"
            )


class TestExpressionNullableRelaxationIsIsolated:
    """③ nullable 완화는 `student_solution_step.expression`에만 적용 — 나머지 7개는 생성부터
    nullable이었으므로 이 마이그레이션이 그들의 nullable 상태를 바꿀 필요가 없다(대칭 diff 최소)."""

    def test_expression_is_nullable(self) -> None:
        assert StudentSolutionStep.__table__.columns["expression"].nullable is True

    def test_other_seven_target_columns_were_already_nullable_pre_migration(self) -> None:
        """(문서 확인용) 이 테스트가 실패한다면 대상 컬럼 원본 nullable 전제가 바뀐 것 —
        마이그레이션이 alter_column을 추가로 필요로 하게 된다."""
        already_nullable = {
            (ProblemAttempt, "student_answer"),
            (ProblemAttempt, "handwriting_uri"),
            (ProblemAttempt, "ocr_result"),
            (AnswerSubmission, "raw_response"),
            (AnswerSubmission, "latex"),
            (AnswerSubmission, "canonical_ast"),
            (StudentSolutionStep, "canonical_ast"),
        }
        assert len(already_nullable) == 7
        for model, column_name in already_nullable:
            assert model.__table__.columns[column_name].nullable is True


class TestMigrationFileCompleteness:
    """④ 마이그레이션 파일이 16 add_column + 1 alter_column을 대칭 up/down으로 담는다."""

    def _source(self) -> str:
        matches = list(_VERSIONS_DIR.glob("*student_work_envelope_encryption.py"))
        assert len(matches) == 1, "SEC-31 마이그레이션 파일이 정확히 1개여야 한다"
        return matches[0].read_text(encoding="utf-8")

    def test_revision_chain(self) -> None:
        source = self._source()
        assert f'revision: str = "{_MIGRATION_REVISION}"' in source
        assert f'down_revision: str | None = "{_MIGRATION_DOWN_REVISION}"' in source

    def test_all_sixteen_columns_added_in_upgrade(self) -> None:
        source = self._source()
        upgrade = source[source.find("def upgrade") : source.find("def downgrade")]
        for model, targets in _TARGET_COLUMNS.items():
            table_name = model.__tablename__
            for base in targets:
                for suffix in ("_encrypted", "_nonce"):
                    col = f"{base}{suffix}"
                    assert f'sa.Column("{col}"' in upgrade, f"upgrade에 {table_name}.{col} 누락"

    def test_all_sixteen_columns_dropped_in_downgrade_symmetrically(self) -> None:
        source = self._source()
        downgrade = source[source.find("def downgrade") :]
        for model, targets in _TARGET_COLUMNS.items():
            for base in targets:
                for suffix in ("_encrypted", "_nonce"):
                    col = f"{base}{suffix}"
                    assert (
                        f'op.drop_column("{model.__tablename__}", "{col}")' in downgrade
                    ), f"downgrade에 {model.__tablename__}.{col} 제거 누락(대칭 위반)"

    def test_expression_nullable_relaxation_and_restoration(self) -> None:
        source = self._source()
        upgrade = source[source.find("def upgrade") : source.find("def downgrade")]
        downgrade = source[source.find("def downgrade") :]
        assert '"student_solution_step"' in upgrade and "nullable=True" in upgrade
        assert (
            "nullable=False" in downgrade
        )  # 원복 — 실 데이터에 NULL 없을 때만 안전(모듈 docstring)


class TestBackfillCliExportsAllThreeTables:
    """⑤ 백필 CLI가 3테이블 함수를 전부 export — 한 테이블만 재암호화 가능한 상태를 막는다."""

    def test_all_three_reencrypt_functions_exported(self) -> None:
        from whymath_backend.privacy import student_work_backfill

        for name in (
            "reencrypt_plaintext_problem_attempt",
            "reencrypt_plaintext_answer_submission",
            "reencrypt_plaintext_student_solution_step",
        ):
            assert hasattr(student_work_backfill, name), f"백필 CLI에 {name} 누락(부분 배선)"
            assert name in student_work_backfill.__all__
