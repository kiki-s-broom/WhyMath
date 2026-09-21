"""Rights & Provenance Infrastructure ORM 모델 (LIC-01).

설계 정본: EOS 42번 모듈의 Source Registry + Rights Registry MVP.
Content-Source/Rights를 N:M으로 분리하고, License를 Permission primitive(JSONB)로
정규화해 기계적 권리 판정을 지원한다.

타입 매핑(`problem.py`·`provenance.py` 선례):
  - UUID PK → server_default gen_random_uuid().
  - JSONB → dict[str, Any] | None.
  - enum → _pg_enum(...).
  - 복합 PK → sa.PrimaryKeyConstraint(...) in __table_args__.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.db.models._orm_enum import _pg_enum
from whymath_backend.db.models._schema_seam import drop_unset_nulls
from whymath_backend.schema.enums import (
    DerivationType,
    LicenseType,
    RightsReviewStatus,
    SourceAuthority,
)
from whymath_backend.schema.rights import (
    ContentRightsLink as SchemaContentRightsLink,
)
from whymath_backend.schema.rights import (
    ContentSourceLink as SchemaContentSourceLink,
)
from whymath_backend.schema.rights import (
    DerivationEdge as SchemaDerivationEdge,
)
from whymath_backend.schema.rights import (
    PermissionSet as SchemaPermissionSet,
)
from whymath_backend.schema.rights import (
    RightsEntity as SchemaRightsEntity,
)
from whymath_backend.schema.rights import (
    RightsHolderEntity as SchemaRightsHolderEntity,
)
from whymath_backend.schema.rights import (
    SourceEntity as SchemaSourceEntity,
)

__all__ = [
    "SourceEntity",
    "RightsHolderEntity",
    "RightsEntity",
    "ContentSourceLink",
    "ContentRightsLink",
    "DerivationEdge",
]


# ──────────────────────────────────────────────────────────────────────────
# SourceEntity
# ──────────────────────────────────────────────────────────────────────────
class SourceEntity(Base):
    """출처 엔티티 영속 ORM."""

    __tablename__ = "source_entity"

    source_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    source_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    title: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    publisher: Mapped[str | None] = mapped_column(sa.String(256))
    creator: Mapped[str | None] = mapped_column(sa.String(256))
    original_url: Mapped[str | None] = mapped_column(sa.String(2048))
    retrieved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    publication_date: Mapped[str | None] = mapped_column(sa.String(32))
    jurisdiction: Mapped[str | None] = mapped_column(sa.String(8))
    source_hash: Mapped[str | None] = mapped_column(sa.String(128))
    archive_uri: Mapped[str | None] = mapped_column(sa.String(2048))
    source_authority: Mapped[SourceAuthority | None] = mapped_column(
        _pg_enum(SourceAuthority, "source_authority_enum"),
        default=SourceAuthority.UNKNOWN,
    )
    status: Mapped[str] = mapped_column(sa.String(32), default="verified")
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    __table_args__ = (
        sa.Index("idx_source_type", "source_type"),
        sa.Index("idx_source_hash", "source_hash"),
    )

    @classmethod
    def from_schema(cls, schema: SchemaSourceEntity) -> "SourceEntity":
        """검증된 schema.SourceEntity → 영속 ORM."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaSourceEntity:
        """영속 ORM → schema.SourceEntity."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaSourceEntity.model_validate(
            drop_unset_nulls(data, SchemaSourceEntity, orm_cls=type(self))
        )


# ──────────────────────────────────────────────────────────────────────────
# RightsHolderEntity
# ──────────────────────────────────────────────────────────────────────────
class RightsHolderEntity(Base):
    """권리 보유자 영속 ORM."""

    __tablename__ = "rights_holder"

    holder_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    entity_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(256), nullable=False)
    country: Mapped[str | None] = mapped_column(sa.String(8))
    aliases: Mapped[list[str]] = mapped_column(
        sa.ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")
    )
    contact: Mapped[str | None] = mapped_column(sa.String(512))
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))

    __table_args__ = (sa.Index("idx_rights_holder_name", "name"),)

    @classmethod
    def from_schema(cls, schema: SchemaRightsHolderEntity) -> "RightsHolderEntity":
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaRightsHolderEntity:
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaRightsHolderEntity.model_validate(
            drop_unset_nulls(data, SchemaRightsHolderEntity, orm_cls=type(self))
        )


# ──────────────────────────────────────────────────────────────────────────
# RightsEntity
# ──────────────────────────────────────────────────────────────────────────
class RightsEntity(Base):
    """권리 정책 영속 ORM."""

    __tablename__ = "rights_entity"

    rights_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    license_code: Mapped[LicenseType] = mapped_column(
        _pg_enum(LicenseType, "license_enum"), nullable=False
    )
    copyright_status: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default="copyrighted"
    )
    holder_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("rights_holder.holder_id")
    )
    permissions: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    attribution_required: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    share_alike: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    conditions: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    review_status: Mapped[RightsReviewStatus] = mapped_column(
        _pg_enum(RightsReviewStatus, "rights_review_status_enum"),
        nullable=False,
        default=RightsReviewStatus.UNVERIFIED,
    )
    valid_from: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    __table_args__ = (
        sa.Index("idx_rights_license", "license_code"),
        sa.Index("idx_rights_valid_until", "valid_until"),
        sa.Index("idx_rights_review_status", "review_status"),
    )

    @classmethod
    def from_schema(cls, schema: SchemaRightsEntity) -> "RightsEntity":
        data = schema.model_dump()
        data["permissions"] = schema.permissions.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaRightsEntity:
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        data["permissions"] = SchemaPermissionSet.model_validate(data.get("permissions") or {})
        return SchemaRightsEntity.model_validate(
            drop_unset_nulls(data, SchemaRightsEntity, orm_cls=type(self))
        )


# ──────────────────────────────────────────────────────────────────────────
# Content-Source N:M
# ──────────────────────────────────────────────────────────────────────────
class ContentSourceLink(Base):
    """콘텐츠 ↔ 출처 N:M 연결 영속 ORM."""

    __tablename__ = "content_source"

    content_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    content_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("source_entity.source_id"), nullable=False
    )
    role: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="primary")
    original_reference: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("content_type", "content_id", "source_id"),
        sa.Index("idx_content_source_lookup", "content_type", "content_id"),
        sa.Index("idx_content_source_source", "source_id"),
    )

    @classmethod
    def from_schema(cls, schema: SchemaContentSourceLink) -> "ContentSourceLink":
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaContentSourceLink:
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaContentSourceLink.model_validate(
            drop_unset_nulls(data, SchemaContentSourceLink, orm_cls=type(self))
        )


# ──────────────────────────────────────────────────────────────────────────
# Content-Rights N:M
# ──────────────────────────────────────────────────────────────────────────
class ContentRightsLink(Base):
    """콘텐츠 ↔ 권리 N:M 연결 영속 ORM."""

    __tablename__ = "content_rights"

    content_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    content_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    rights_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("rights_entity.rights_id"), nullable=False
    )
    is_primary: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    applies_to_fragment: Mapped[str | None] = mapped_column(sa.String(128))
    created_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("content_type", "content_id", "rights_id"),
        sa.Index("idx_content_rights_lookup", "content_type", "content_id"),
        sa.Index("idx_content_rights_rights", "rights_id"),
    )

    @classmethod
    def from_schema(cls, schema: SchemaContentRightsLink) -> "ContentRightsLink":
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaContentRightsLink:
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaContentRightsLink.model_validate(
            drop_unset_nulls(data, SchemaContentRightsLink, orm_cls=type(self))
        )


# ──────────────────────────────────────────────────────────────────────────
# DerivationEdge
# ──────────────────────────────────────────────────────────────────────────
class DerivationEdge(Base):
    """콘텐츠 파생 관계 영속 ORM."""

    __tablename__ = "derivation_edge"

    edge_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    from_content_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    from_content_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    to_content_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    to_content_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    derivation_type: Mapped[DerivationType] = mapped_column(
        _pg_enum(DerivationType, "derivation_type_enum"), nullable=False
    )
    provenance_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)
    edge_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    __table_args__ = (
        sa.Index("idx_derivation_from", "from_content_type", "from_content_id"),
        sa.Index("idx_derivation_to", "to_content_type", "to_content_id"),
    )

    @classmethod
    def from_schema(cls, schema: SchemaDerivationEdge) -> "DerivationEdge":
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaDerivationEdge:
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaDerivationEdge.model_validate(
            drop_unset_nulls(data, SchemaDerivationEdge, orm_cls=type(self))
        )
