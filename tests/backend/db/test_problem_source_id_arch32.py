"""ARCH-32 — `problem.source_id`(source_entity FK 좌석) 계약 동결.

PG 없이 도는 구조 검증이다(ORM 메타데이터·schema 왕복·마이그레이션 파일). 실 PG 왕복은 CI의
마이그레이션 잡이 전구간으로 수행한다.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import sqlalchemy as sa

from whymath_backend.db.models import Problem as ORMProblem
from whymath_backend.schema.problem import Problem as SchemaProblem

_VERSION = Path(__file__).resolve().parents[3] / "src/backend/alembic/versions"
_FILE = _VERSION / "20261002_1200_b4d8e2a6c0f3_problem_source_id.py"


def _col() -> sa.Column:
    return ORMProblem.__table__.c.source_id


def test_orm_column_is_nullable_uuid_fk_to_source_entity() -> None:
    col = _col()
    assert col.nullable is True
    assert col.server_default is None  # 백필 금지 — NULL=미이관
    assert isinstance(col.type, sa.Uuid)
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    assert fks[0].target_fullname == "source_entity.source_id"


def test_orm_has_lookup_index() -> None:
    names = {i.name for i in ORMProblem.__table__.indexes}
    assert "idx_problem_source_id" in names


def test_legacy_source_columns_are_kept_during_migration() -> None:
    # 저작권 불변식의 근거라 이관 기간 중 지우지 않는다(문서 §3).
    cols = ORMProblem.__table__.c
    assert "source_type" in cols and "source_detail" in cols
    assert cols.source_type.nullable is False


def test_schema_field_defaults_to_none_and_roundtrips() -> None:
    field = SchemaProblem.model_fields["source_id"]
    assert field.default is None
    sid = uuid.uuid4()
    assert SchemaProblem.model_fields["source_id"].annotation == (uuid.UUID | None)
    assert isinstance(sid, uuid.UUID)


def test_migration_is_symmetric_and_chained() -> None:
    tree = ast.parse(_FILE.read_text(encoding="utf-8"))
    consts = {
        t.id: ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.AnnAssign) and isinstance(t := n.target, ast.Name) and n.value
    }
    assert consts["revision"] == "b4d8e2a6c0f3"
    assert consts["down_revision"] == "a3f7c9d1e5b2"
    src = _FILE.read_text(encoding="utf-8")
    up = src.split("def upgrade")[1].split("def downgrade")[0]
    down = src.split("def downgrade")[1]
    assert "add_column" in up and "create_foreign_key" in up and "create_index" in up
    assert "drop_column" in down and "drop_constraint" in down and "drop_index" in down
    assert "server_default" not in up  # 백필 금지
    assert "UPDATE" not in up.upper().replace("UPDATE_", "")
