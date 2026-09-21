"""StudentSolutionStep ORM(`student_solution_step`) — DB 연결 없이 검증 + 실 PG 통합 (EOS-46).

`test_answer_submission_orm.py`(EOS-32)·`test_hint_usage_orm.py`(EOS-45) 컨벤션 미러.
판정 정본은 `docs/architecture/adr/ADR-002-student-solution-step-entity.md`(별도 정규 엔티티 —
attempt_event 확장 기각).

검증 핵심:
  - **SolutionNode(WH-S MCTS)와의 분리** — 테이블·클래스가 별개이고 solution_nodes를
    참조하지 않음(ADR-002 명칭·책임 구분의 기계 동결).
  - 복합 FK (attempt_id, user_id) 소유 정합(EOS-32 관례) + 참조 대상 UNIQUE 재사용(중복
    생성 금지 — 마이그레이션 소스 검사).
  - UNIQUE(attempt_id, sequence_no)·expression NOT NULL·JSONB 3종 none_as_null(SEC-06)·
    concept_ids 느슨참조(FK 0).
  - from_schema/to_schema round-trip(StepValidation JSONB 왕복)·submitted_at server_default.
  - alembic 체인(EOS-45 `0e148995e6e9` 뒤)·up/down 대칭.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import CreateTable

from whymath_backend.db.base import Base
from whymath_backend.db.models.student_solution_step import StudentSolutionStep
from whymath_backend.schema.student_solution_step import (
    StepValidation,
)
from whymath_backend.schema.student_solution_step import (
    StudentSolutionStep as SchemaStudentSolutionStep,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_VERSIONS_DIR = _REPO_ROOT / "src" / "backend" / "alembic" / "versions"

# SEC-06 대상 JSONB 컬럼(값 없음 = SQL NULL — 오계수·백필 굶주림 방지).
_JSONB_COLUMNS = ("canonical_ast", "validation", "concept_ids")


def _full_schema() -> SchemaStudentSolutionStep:
    """모든 필드가 채워진 검증 schema 1건(round-trip 재료)."""
    return SchemaStudentSolutionStep(
        student_step_id=uuid.uuid4(),
        attempt_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        sequence_no=3,
        expression=r"x^2 - 4 = (x-2)(x+2)",
        canonical_ast={"op": "Eq", "args": ["lhs", "rhs"]},
        validation=StepValidation(is_valid=True, method="sympy_step_check", detail={"equiv": True}),
        concept_ids=["math.algebra.factorization"],
        submitted_at=datetime(2026, 8, 30, 22, 0, tzinfo=UTC),
    )


class TestStudentSolutionStepTable:
    def test_registered_in_metadata(self) -> None:
        """`student_solution_step`이 Base.metadata에 등록(모델 패키지 import 경유)."""
        import whymath_backend.db.models  # noqa: F401  # 패키지 __init__ 등록 경로 검증

        assert "student_solution_step" in Base.metadata.tables

    def test_distinct_from_whs_solution_node(self) -> None:
        """ADR-002 명칭·책임 구분 — WH-S `solution_nodes`(MCTS·시스템 데이터)와 별개 테이블이고
        어떤 FK로도 solution_nodes를 참조하지 않는다(학생 데이터 ↔ 솔버 상태 혼동 금지)."""
        from whymath_backend.db.models.solution_node import SolutionNode

        assert StudentSolutionStep.__tablename__ != SolutionNode.__tablename__
        fk_targets = {
            fk.target_fullname
            for constraint in StudentSolutionStep.__table__.constraints
            if constraint.__class__.__name__ == "ForeignKeyConstraint"
            for fk in constraint.elements  # type: ignore[attr-defined]
        }
        assert not any(t.startswith("solution_nodes.") for t in fk_targets)
        # 학생 데이터 표식 — 소유 컬럼 보유(완전성 스윕 대상). SolutionNode는 user 컬럼 자체가 없다.
        assert "user_id" in StudentSolutionStep.__table__.columns
        assert "user_id" not in SolutionNode.__table__.columns

    def test_pg_ddl_compiles_with_expected_shapes(self) -> None:
        """PG DDL 컴파일 — PK·복합 FK(CASCADE)·user FK·UNIQUE·NOT NULL·server_default."""
        ddl = str(CreateTable(StudentSolutionStep.__table__).compile(dialect=postgresql.dialect()))
        assert "student_solution_step" in ddl
        assert "PRIMARY KEY (student_step_id)" in ddl
        assert (
            "FOREIGN KEY(attempt_id, user_id) "
            "REFERENCES problem_attempt (attempt_id, user_id) ON DELETE CASCADE" in ddl
        )
        assert "REFERENCES user_profile (user_id)" in ddl
        assert (
            "CONSTRAINT uq_student_solution_step_attempt_seq "
            "UNIQUE (attempt_id, sequence_no)" in ddl
        )
        assert "'[]'::jsonb" in ddl  # concept_ids 기본값(매칭 확정분만 — 날조 금지)
        assert "now()" in ddl  # submitted_at server_default(보존 파기 축)

    def test_composite_attempt_user_fk_declared(self) -> None:
        """(attempt_id, user_id) 복합 FK 정확히 1개 — 소유 정합(EOS-32 PR #902 P1 관례)."""
        composite = [
            constraint
            for constraint in StudentSolutionStep.__table__.constraints
            if constraint.__class__.__name__ == "ForeignKeyConstraint"
            and tuple(constraint.columns.keys()) == ("attempt_id", "user_id")
        ]
        assert len(composite) == 1
        targets = {fk.target_fullname for fk in composite[0].elements}
        assert targets == {"problem_attempt.attempt_id", "problem_attempt.user_id"}
        assert composite[0].ondelete == "CASCADE"

    def test_required_columns_not_null(self) -> None:
        """attempt_id·user_id·sequence_no·concept_ids·submitted_at NOT NULL."""
        columns = StudentSolutionStep.__table__.columns
        for name in (
            "attempt_id",
            "user_id",
            "sequence_no",
            "concept_ids",
            "submitted_at",
        ):
            assert columns[name].nullable is False, f"{name}은 NOT NULL이어야 한다"

    def test_expression_relaxed_to_nullable_for_envelope_encryption(self) -> None:
        """SEC-31: `expression`은 원래 NOT NULL이었으나, 암호화 행에서는 평문 컬럼이 NULL이
        되므로 DB 제약을 nullable로 완화했다(마이그레이션 3f5c83f51246). schema 계약(필수
        `str`·min_length=1)은 불변 — handler/헬퍼 층의
        `resolve_student_solution_step_expression`이 둘 다 없으면 RuntimeError로 "항상 문자열"
        약속을 지킨다(조용한 None 통과 없음)."""
        assert StudentSolutionStep.__table__.columns["expression"].nullable is True

    def test_expression_envelope_columns_present_and_nullable(self) -> None:
        """SEC-31: expression_encrypted/expression_nonce — LargeBinary·nullable·schema 밖."""
        columns = StudentSolutionStep.__table__.columns
        for name in ("expression_encrypted", "expression_nonce"):
            assert columns[name].nullable is True, f"{name}은 nullable이어야 한다"
        assert name in StudentSolutionStep._NON_SCHEMA_COLUMNS  # type: ignore[attr-defined]

    def test_canonical_ast_envelope_columns_present_and_nullable(self) -> None:
        """SEC-31: canonical_ast_encrypted/canonical_ast_nonce — LargeBinary·nullable·schema 밖."""
        columns = StudentSolutionStep.__table__.columns
        for name in ("canonical_ast_encrypted", "canonical_ast_nonce"):
            assert columns[name].nullable is True, f"{name}은 nullable이어야 한다"
            assert name in StudentSolutionStep._NON_SCHEMA_COLUMNS  # type: ignore[attr-defined]

    def test_jsonb_columns_declare_none_as_null(self) -> None:
        """JSONB 3컬럼 전부 `none_as_null=True`(SEC-06)."""
        for name in _JSONB_COLUMNS:
            column = StudentSolutionStep.__table__.columns[name]
            assert isinstance(column.type, JSONB)
            assert column.type.none_as_null is True, f"{name}: none_as_null 필요"

    def test_concept_ids_is_loose_reference(self) -> None:
        """concept_ids는 FK 없는 JSONB 목록 — solution_paths.concept_sequence 선례(느슨참조)."""
        assert len(StudentSolutionStep.__table__.columns["concept_ids"].foreign_keys) == 0

    def test_sequence_unique_and_user_index(self) -> None:
        """UNIQUE(attempt_id, sequence_no) + (user_id, submitted_at DESC) 인덱스."""
        unique_sets = [
            tuple(constraint.columns.keys())
            for constraint in StudentSolutionStep.__table__.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        ]
        assert ("attempt_id", "sequence_no") in unique_sets
        index_names = {index.name for index in StudentSolutionStep.__table__.indexes}
        assert "idx_student_solution_step_user" in index_names


class TestSchemaOrmRoundTrip:
    def test_round_trip_preserves_all_fields(self) -> None:
        """schema → from_schema → to_schema 왕복이 서브모델(validation JSONB) 포함 전 필드 보존."""
        original = _full_schema()
        orm = StudentSolutionStep.from_schema(original)
        assert orm.validation == {
            "is_valid": True,
            "method": "sympy_step_check",
            "detail": {"equiv": True},
        }
        assert orm.concept_ids == ["math.algebra.factorization"]
        restored = orm.to_schema()
        assert restored == original

    def test_expression_whitespace_preserved_verbatim(self) -> None:
        """expression 원문 바이트 동일 보존(strip 정규화 없음 — EOS-32 P2 동형·증거 보존)."""
        raw = "  x = 2  "
        schema = SchemaStudentSolutionStep(
            attempt_id=uuid.uuid4(), user_id=uuid.uuid4(), sequence_no=1, expression=raw
        )
        assert schema.expression == raw
        assert StudentSolutionStep.from_schema(schema).expression == raw

    def test_from_schema_omits_none_submitted_at(self) -> None:
        """submitted_at=None(기본)은 속성 미설정 — server_default 적용(EOS-32/45 동형)."""
        schema = SchemaStudentSolutionStep(
            attempt_id=uuid.uuid4(), user_id=uuid.uuid4(), sequence_no=1, expression="x=2"
        )
        orm = StudentSolutionStep.from_schema(schema)
        assert "submitted_at" not in orm.__dict__

    def test_to_schema_rejects_corrupted_validation(self) -> None:
        """DB에 오염된 validation(빈 method — 검증 없는 판정 위장)이 있으면 to_schema가 거부."""
        orm = StudentSolutionStep.from_schema(_full_schema())
        orm.validation = {"is_valid": True, "method": ""}  # 침묵 valid 위장 시뮬레이션
        with pytest.raises(Exception) as excinfo:
            orm.to_schema()
        assert "method" in str(excinfo.value)


class TestMigrationFile:
    def test_migration_file_exists_with_symmetric_updown(self) -> None:
        """EOS-46 마이그레이션 파일 존재·up/down 대칭·복합 FK·UNIQUE·인덱스."""
        matches = list(_VERSIONS_DIR.glob("*student_solution_step.py"))
        assert len(matches) == 1, "EOS-46 마이그레이션 파일이 정확히 1개여야 한다"
        source = matches[0].read_text(encoding="utf-8")
        assert 'op.create_table(\n        "student_solution_step"' in source
        assert 'op.drop_table("student_solution_step")' in source
        assert 'name="fk_student_solution_step_attempt_owner"' in source
        assert 'name="uq_student_solution_step_attempt_seq"' in source
        assert 'ondelete="CASCADE"' in source
        assert '"idx_student_solution_step_user"' in source
        assert 'op.drop_index("idx_student_solution_step_user"' in source
        # 체인: EOS-45 hint_usage(0e148995e6e9) 위에 쌓인다.
        assert 'down_revision: str | None = "0e148995e6e9"' in source

    def test_no_duplicate_unique_creation_on_problem_attempt(self) -> None:
        """복합 FK 참조 대상 UNIQUE는 EOS-32가 이미 생성 — EOS-46이 재생성하지 않는다.

        중복 create_unique_constraint는 실 PG upgrade에서 DuplicateObject로 터진다(체인 파손).
        problem_attempt에 대한 어떤 constraint 조작도 없어야 한다(EOS-32 소유물 불가침).
        """
        source = next(_VERSIONS_DIR.glob("*student_solution_step.py")).read_text(encoding="utf-8")
        assert "op.create_unique_constraint(" not in source
        assert "op.drop_constraint(" not in source


# ===========================================================================
# 통합 (실 PG·기본 SKIP) — UNIQUE + 복합 FK 소유 정합 실제 강제(EOS-32 동형)
# ===========================================================================


@pytest.mark.integration
def test_sequence_unique_and_owner_fk_enforced_on_live_pg() -> None:
    """①같은 attempt·같은 sequence_no 중복 거부(UNIQUE) ②A의 attempt + B의 user_id 거부(복합 FK)."""
    from pydantic import SecretStr
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from whymath_backend.config import Settings
    from whymath_backend.db.models.activity import ProblemAttempt
    from whymath_backend.db.models.user import UserProfile
    from whymath_backend.schema.activity import ProblemAttempt as ProblemAttemptSchema
    from whymath_backend.schema.enums import Persona
    from whymath_backend.schema.user import UserProfile as UserProfileSchema

    settings = Settings(jwt_secret_key=SecretStr("integration-jwt-secret-0123456789abcdef"))

    async def _pg_reachable() -> bool:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
        finally:
            await engine.dispose()

    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid_a = uuid.uuid4()
    uid_b = uuid.uuid4()
    aid = uuid.uuid4()

    def _user(uid: uuid.UUID, nickname: str) -> UserProfile:
        return UserProfile.from_schema(
            UserProfileSchema(
                user_id=uid,
                persona_primary=Persona.A_일반고고3,
                nickname=nickname,
                email_hash=f"HASH-{uid.hex[:8]}",
                is_minor=True,
            )
        )

    def _step(uid: uuid.UUID, seq: int) -> StudentSolutionStep:
        return StudentSolutionStep.from_schema(
            SchemaStudentSolutionStep(
                attempt_id=aid, user_id=uid, sequence_no=seq, expression="x=2"
            )
        )

    async def _run() -> None:
        engine = create_async_engine(settings.database_url)
        try:
            sm = async_sessionmaker(engine, expire_on_commit=False)
            async with sm() as session:
                session.add(_user(uid_a, "풀이학생A"))
                session.add(_user(uid_b, "타인B"))
                await session.flush()
                session.add(
                    ProblemAttempt.from_schema(ProblemAttemptSchema(attempt_id=aid, user_id=uid_a))
                )
                await session.commit()

            # ① 같은 (attempt_id, sequence_no) — UNIQUE 거부.
            async with sm() as session:
                session.add(_step(uid_a, 1))
                await session.flush()
                session.add(_step(uid_a, 1))
                with pytest.raises(IntegrityError) as excinfo:
                    await session.flush()
                assert "uq_student_solution_step_attempt_seq" in str(excinfo.value)
                await session.rollback()

            # ② A의 attempt + B의 user_id — 복합 FK 거부(소유 정합).
            async with sm() as session:
                session.add(_step(uid_b, 1))
                with pytest.raises(IntegrityError) as excinfo:
                    await session.flush()
                assert "fk_student_solution_step_attempt_owner" in str(excinfo.value)
                await session.rollback()
        finally:
            await engine.dispose()

    async def _cleanup() -> None:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                for tbl, col in (
                    ("student_solution_step", "user_id"),
                    ("problem_attempt", "user_id"),
                    ("user_profile", "user_id"),
                ):
                    for uid in (uid_a, uid_b):
                        await conn.execute(
                            text(f"DELETE FROM {tbl} WHERE {col} = :k"), {"k": str(uid)}
                        )
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(_cleanup())
