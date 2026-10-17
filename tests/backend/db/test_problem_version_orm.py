"""ProblemVersion ORM(영속 레이어) 단위테스트 — DB 연결 *없이* 검증 가능한 것만 — ARCH-31.

`test_concept_version_orm.py` 패턴 답습: 메타데이터 등록 / PG DDL 컴파일(JSONB·enum 타입명·
gen_random_uuid·FK 방향) / schema↔ORM 변환 roundtrip / `Problem` 포인터 컬럼. 실 PG에서의 트리거
발화는 `test_problem_version_migration_integration.py`(WHYMATH_RUN_INTEGRATION)가 검증한다.

설계 정본: `docs/architecture/arch31_problem_version.md`·`44_eos_version_management.md` §6.
좌석 판정: `canonical_entity_model_v1.md` §3-D(게이트 `G-eos49-content-version-seat` D안) —
`problem_version`은 Problem 좌석 3번째 테이블, `ContentVersion` 좌석은 비어 있다.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from whymath_backend.db.base import Base
from whymath_backend.db.models.problem import Problem as OrmProblem
from whymath_backend.db.models.problem_version import ProblemVersion as OrmProblemVersion
from whymath_backend.schema.enums import Curriculum, SourceType, Subject
from whymath_backend.schema.problem import PUBLIC_HIDDEN_OPS_FIELDS, PublicProblem
from whymath_backend.schema.problem import Problem as SchemaProblem
from whymath_backend.schema.problem_version import ProblemVersion as SchemaProblemVersion
from whymath_backend.schema.problem_version import ProblemVersionPayload
from whymath_backend.schema.version_header import (
    VersionChange,
    VersionGovernance,
    VersionIntegrity,
    VersionSource,
    VersionStatus,
)

_TABLE = OrmProblemVersion.__table__


def _pg_ddl(table: object) -> str:
    return str(CreateTable(table).compile(dialect=postgresql.dialect()))  # type: ignore[arg-type]


# ── 1) 메타데이터 등록 ────────────────────────────────────────────────────
def test_problem_version_registered_in_metadata() -> None:
    assert "problem_version" in Base.metadata.tables
    assert OrmProblemVersion.__tablename__ == "problem_version"


def test_no_generic_content_version_table_exists() -> None:
    """범용 ContentVersion은 만들지 않는다(D안) — 도메인 버전 테이블만 있다."""
    assert "content_version" not in Base.metadata.tables


# ── 2) PG DDL 컴파일 — FK 방향·enum·JSONB·PK ──────────────────────────────
def test_ddl_compiles_to_postgres() -> None:
    ddl = _pg_ddl(_TABLE)
    assert "problem_version_status_enum" in ddl
    assert "JSONB" in ddl
    assert "gen_random_uuid()" in ddl


def test_problem_id_fk_targets_problem_uuid_pk() -> None:
    """엔티티 FK는 problem.problem_id(UUID PK) — 44 §6.3 `problem_id: UUID  # Problem entity FK`."""
    fks = list(_TABLE.c.problem_id.foreign_keys)
    assert len(fks) == 1
    assert (fks[0].column.table.name, fks[0].column.name) == ("problem", "problem_id")
    assert isinstance(_TABLE.c.problem_id.type, sa.Uuid)
    assert _TABLE.c.problem_id.nullable is False


def test_self_fk_previous_version() -> None:
    ddl = _pg_ddl(_TABLE)
    assert "FOREIGN KEY(previous_version_id) REFERENCES problem_version (version_id)" in ddl


def test_unique_and_index() -> None:
    uniques = [
        tuple(c.name for c in constraint.columns)
        for constraint in _TABLE.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    ]
    assert ("problem_id", "version_no") in uniques
    by_name = {ix.name: [c.name for c in ix.columns] for ix in _TABLE.indexes}
    assert by_name["idx_problem_version_problem_status"] == ["problem_id", "status"]


def test_status_enum_has_all_seven_values_from_the_start() -> None:
    """VersionStatus 7종 전량(IN_QA 포함)을 처음부터 갖는다 — concept의 사후 ADD VALUE 이력 반복 금지."""
    col = _TABLE.c.status
    assert set(col.type.enums) == {s.value for s in VersionStatus}  # type: ignore[attr-defined]
    assert "IN_QA" in col.type.enums  # type: ignore[attr-defined]
    assert col.nullable is False


def test_jsonb_columns_none_as_null() -> None:
    for name in ("change", "source", "governance", "integrity", "qa", "payload"):
        assert _TABLE.c[name].type.none_as_null is True  # type: ignore[attr-defined]
    assert _TABLE.c.payload.nullable is False
    for name in ("change", "source", "governance", "integrity", "qa"):
        assert _TABLE.c[name].nullable is True
        assert _TABLE.c[name].server_default is None  # 기록 날조 금지


def test_pk_is_version_id() -> None:
    assert [c.name for c in _TABLE.primary_key.columns] == ["version_id"]


def test_no_identity_id_column_on_version_table() -> None:
    """identity_id(변형 계열)는 problem 쪽이 정본 — 버전 테이블에 복제하지 않는다."""
    assert "identity_id" not in _TABLE.c


# ── 3) Problem 포인터 컬럼 ────────────────────────────────────────────────
def test_problem_gains_nullable_pointer_fk_without_default() -> None:
    col = OrmProblem.__table__.c.problem_version_id
    assert col.nullable is True
    assert col.server_default is None and col.default is None  # 백필 금지 — NULL=버전 미부여
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    assert (fks[0].column.table.name, fks[0].column.name) == ("problem_version", "version_id")


def test_problem_pointer_is_in_schema_and_orm_parity() -> None:
    orm_columns = {c.key for c in sa.inspect(OrmProblem).mapper.column_attrs}
    assert "problem_version_id" in SchemaProblem.model_fields
    assert "problem_version_id" in orm_columns
    assert SchemaProblem.model_fields["problem_version_id"].default is None


def test_problem_pointer_is_hidden_from_public_projection() -> None:
    """판 포인터는 운영 좌표 — 무인증 공개 응답에 키 자체가 없다(허용목록 원칙)."""
    assert "problem_version_id" in PUBLIC_HIDDEN_OPS_FIELDS
    assert "problem_version_id" not in PublicProblem.model_fields


def test_identity_id_unchanged_and_independent_of_pointer() -> None:
    """identity_id는 FK 아닌 계열 공유값 그대로 — 이 PR이 의미를 바꾸지 않았다."""
    col = OrmProblem.__table__.c.identity_id
    assert not list(col.foreign_keys)
    assert col.nullable is True


# ── 4) 변환 roundtrip ─────────────────────────────────────────────────────
def _payload() -> ProblemVersionPayload:
    return ProblemVersionPayload(
        source_type=SourceType.자체생성,
        subject=Subject.공통,
        curriculum_version=Curriculum.REVISION_2022,
        unit_codes=["U-1"],
        question_text="2x=4일 때 x는?",
        answer="2",
        stem_hash="h1",
    )


def test_roundtrip_preserves_core_fields() -> None:
    vid, pid, prev = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    s = SchemaProblemVersion(
        version_id=vid,
        problem_id=pid,
        version_no=2,
        schema_version="problem-schema@1",
        status=VersionStatus.IN_QA,
        previous_version_id=prev,
        change=VersionChange(reason="해설 정정"),
        source=VersionSource(source_ids=["src-1"], derived_from=prev),
        governance=VersionGovernance(created_by="pipeline"),
        integrity=VersionIntegrity(content_hash="abc"),
        payload=_payload(),
    )
    orm = OrmProblemVersion.from_schema(s)
    assert (orm.version_id, orm.problem_id, orm.version_no) == (vid, pid, 2)
    assert orm.entity_type == "Problem"
    assert orm.status == "IN_QA"
    assert orm.previous_version_id == prev
    # JSONB는 mode="json" — 중첩 UUID(derived_from)가 문자열로 직렬화돼 INSERT 시 TypeError가 없다.
    assert orm.source == {"source_ids": ["src-1"], "derived_from": str(prev)}
    assert orm.payload["question_text"] == "2x=4일 때 x는?"

    back = orm.to_schema()
    assert back.version_id == vid and back.problem_id == pid
    assert back.status == VersionStatus.IN_QA.value
    assert back.source.derived_from == prev
    assert back.payload.answer == "2" and back.payload.stem_hash == "h1"
    assert back.governance.created_by == "pipeline"


def test_roundtrip_first_version_has_no_previous() -> None:
    s = SchemaProblemVersion(
        problem_id=uuid.uuid4(),
        version_no=1,
        schema_version="problem-schema@1",
        payload=_payload(),
    )
    back = OrmProblemVersion.from_schema(s).to_schema()
    assert back.previous_version_id is None
    assert back.published_at is None


def test_pointer_fk_is_use_alter_and_named_like_the_migration() -> None:
    """상호 FK 순환은 ALTER로 푼다(신규 SAWarning 방지) — 제약명은 마이그레이션과 같아야 한다."""
    (fk,) = list(OrmProblem.__table__.c.problem_version_id.foreign_keys)
    assert fk.use_alter is True
    assert fk.name == "fk_problem_problem_version_id_problem_version"
