"""ConceptVersion ORM(영속 레이어) 단위테스트 — DB 연결 *없이* 검증 가능한 것만 — EOS-49.

`test_concept_orm.py`·`test_curriculum_version` 계열 패턴 답습: 메타데이터 등록 / PG DDL
컴파일(JSONB·enum 타입명·gen_random_uuid·FK 방향) / schema↔ORM 변환 roundtrip. 실 PG에서의
트리거 발화(PUBLISHED 불변·PUBLISHED→DRAFT 금지)는 `test_concept_version_migration_
integration.py`(WHYMATH_RUN_INTEGRATION)가 검증한다 — 이 파일은 DDL·매핑만 본다.

설계 정본: `docs/architecture/44_eos_version_management.md` §6.2/§6.3.
좌석 판정: `docs/architecture/canonical_entity_model_v1.md` §3-D(게이트
`G-eos49-content-version-seat` D안) — `concept_version`은 Concept 좌석 4번째 테이블.
"""

from __future__ import annotations

import uuid

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from whymath_backend.db.base import Base
from whymath_backend.db.models.concept import Concept as OrmConcept
from whymath_backend.db.models.concept_version import ConceptVersion as OrmConceptVersion
from whymath_backend.schema.concept import Concept as SchemaConcept
from whymath_backend.schema.concept_version import (
    ConceptVersion as SchemaConceptVersion,
)
from whymath_backend.schema.concept_version import (
    ConceptVersionPayload,
)
from whymath_backend.schema.enums import CognitiveType, ConceptLevel
from whymath_backend.schema.version_header import (
    VersionChange,
    VersionGovernance,
    VersionIntegrity,
    VersionSource,
    VersionStatus,
)


def _pg_ddl(table: object) -> str:
    """ORM 테이블을 PostgreSQL dialect로 컴파일한 CREATE TABLE 문자열로 반환."""
    return str(CreateTable(table).compile(dialect=postgresql.dialect()))  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────
# 1) 메타데이터 등록
# ──────────────────────────────────────────────────────────────────────────
def test_concept_version_table_registered_in_metadata() -> None:
    """Base.metadata에 concept_version 테이블이 등록돼 있다(alembic 인식 전제)."""
    assert "concept_version" in Base.metadata.tables


def test_concept_version_tablename() -> None:
    assert OrmConceptVersion.__tablename__ == "concept_version"


# ──────────────────────────────────────────────────────────────────────────
# 2) PG DDL 컴파일 — FK 방향·enum·JSONB·PK
# ──────────────────────────────────────────────────────────────────────────
def test_concept_version_ddl_compiles_to_postgres() -> None:
    """DDL에 concept_version_status_enum·JSONB·gen_random_uuid()·UUID 포함."""
    ddl = _pg_ddl(OrmConceptVersion.__table__)
    assert "concept_version_status_enum" in ddl
    assert "JSONB" in ddl
    assert "gen_random_uuid()" in ddl
    assert "UUID" in ddl


def test_concept_id_fk_targets_concept_code_not_uuid_pk() -> None:
    """Principle 1(Entity ID ≠ Version ID) — concept_id는 concept.code(의미 ID)를 FK로
    가리킨다. concept.concept_id(UUID 대리키)를 가리키지 않는다(acceptance ① 핵심)."""
    ddl = _pg_ddl(OrmConceptVersion.__table__)
    assert "FOREIGN KEY(concept_id) REFERENCES concept (code)" in ddl
    assert "FOREIGN KEY(concept_id) REFERENCES concept (concept_id)" not in ddl

    col = OrmConceptVersion.__table__.c.concept_id
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "concept"
    assert fks[0].column.name == "code"


def test_concept_version_self_fk_previous_version() -> None:
    """previous_version_id는 concept_version.version_id를 가리키는 self-FK."""
    ddl = _pg_ddl(OrmConceptVersion.__table__)
    assert "FOREIGN KEY(previous_version_id) REFERENCES concept_version (version_id)" in ddl


def test_concept_version_unique_and_index() -> None:
    """UNIQUE(concept_id, version_no) + idx(concept_id, status) 존재."""
    uniques = [
        tuple(c.name for c in constraint.columns)
        for constraint in OrmConceptVersion.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    ]
    assert ("concept_id", "version_no") in uniques

    by_name = {ix.name: [c.name for c in ix.columns] for ix in OrmConceptVersion.__table__.indexes}
    assert by_name["idx_concept_version_concept_status"] == ["concept_id", "status"]


def test_concept_version_status_enum_values() -> None:
    """status 컬럼의 PG enum이 6종 값을 갖고 기본값은 DRAFT."""
    col = OrmConceptVersion.__table__.c.status
    enums = col.type.enums  # type: ignore[attr-defined]
    assert set(enums) == {
        "DRAFT",
        "IN_REVIEW",
        "APPROVED",
        "PUBLISHED",
        "DEPRECATED",
        "RETIRED",
    }
    assert col.nullable is False


def test_concept_version_jsonb_columns_none_as_null() -> None:
    """change/source/governance/integrity/payload 전부 JSONB(none_as_null=True) — SEC-06."""
    for name in ("change", "source", "governance", "integrity", "payload"):
        col = OrmConceptVersion.__table__.c[name]
        assert col.type.none_as_null is True  # type: ignore[attr-defined]
    assert OrmConceptVersion.__table__.c.payload.nullable is False
    for name in ("change", "source", "governance", "integrity"):
        assert OrmConceptVersion.__table__.c[name].nullable is True


def test_concept_version_pk_is_version_id() -> None:
    pk_cols = [c.name for c in OrmConceptVersion.__table__.primary_key.columns]
    assert pk_cols == ["version_id"]


# ──────────────────────────────────────────────────────────────────────────
# 3) Concept 테이블 — current_published_version_id 추가(비파괴)
# ──────────────────────────────────────────────────────────────────────────
def test_concept_gains_current_published_version_id_column() -> None:
    """§6.4 — concept.current_published_version_id는 nullable·concept_version FK."""
    col = OrmConcept.__table__.c.current_published_version_id
    assert col.nullable is True
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "concept_version"
    assert fks[0].column.name == "version_id"


def test_concept_schema_orm_parity_still_holds_with_new_field() -> None:
    """concept.py의 schema↔ORM 필드 정합 동결(test_concept_orm.py)이 새 필드를 포함해도
    깨지지 않는다 — schema에도 짝 필드를 추가했음을 이 테스트가 직접 확인한다."""
    import sqlalchemy as sa

    schema_fields = set(SchemaConcept.model_fields)
    orm_columns = {col.key for col in sa.inspect(OrmConcept).mapper.column_attrs}
    assert "current_published_version_id" in schema_fields
    assert "current_published_version_id" in orm_columns


# ──────────────────────────────────────────────────────────────────────────
# 4) 변환 roundtrip
# ──────────────────────────────────────────────────────────────────────────
def _sample_payload() -> ConceptVersionPayload:
    return ConceptVersionPayload(
        name_ko="미적분학의 기본정리",
        name_en="Fundamental Theorem of Calculus",
        level=ConceptLevel.세부개념,
        cognitive_type=[CognitiveType.THEOREM],
    )


def test_concept_version_roundtrip_preserves_core_fields() -> None:
    """schema.ConceptVersion → ORM → schema가 핵심 필드를 보존한다."""
    vid = uuid.uuid4()
    s = SchemaConceptVersion(
        version_id=vid,
        concept_id="HIGH-CALC-001",  # 의미 ID(Concept.code) — UUID 아님
        version_no=1,
        schema_version="concept-schema@1",
        status=VersionStatus.DRAFT,
        change=VersionChange(reason="최초 저작"),
        source=VersionSource(source_ids=["N1"]),
        governance=VersionGovernance(created_by="pipeline"),
        integrity=VersionIntegrity(content_hash="abc123"),
        payload=_sample_payload(),
    )
    orm = OrmConceptVersion.from_schema(s)
    assert orm.version_id == vid
    assert orm.concept_id == "HIGH-CALC-001"
    assert orm.entity_type == "Concept"
    assert orm.version_no == 1
    assert orm.status == "DRAFT"
    # JSONB 컬럼은 model_dump()가 dict로 풀어 저장된다.
    assert orm.change == {
        "change_type": None,
        "impact": None,
        "reason": "최초 저작",
        "ticket_id": None,
    }
    assert orm.payload["name_ko"] == "미적분학의 기본정리"

    back = orm.to_schema()
    assert back.version_id == vid
    assert back.concept_id == s.concept_id
    assert back.status == s.status
    assert back.payload.name_ko == "미적분학의 기본정리"
    assert back.governance.created_by == "pipeline"


def test_concept_version_previous_version_id_roundtrip() -> None:
    """previous_version_id(self-FK)가 None·값 양쪽 모두 왕복 보존된다."""
    prev = uuid.uuid4()
    s = SchemaConceptVersion(
        concept_id="HIGH-CALC-001",
        version_no=2,
        schema_version="concept-schema@1",
        previous_version_id=prev,
        payload=_sample_payload(),
    )
    orm = OrmConceptVersion.from_schema(s)
    assert orm.previous_version_id == prev
    back = orm.to_schema()
    assert back.previous_version_id == prev
