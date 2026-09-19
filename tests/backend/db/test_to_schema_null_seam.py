"""`to_schema()` NULL seam 계약 동결 — EOS-109.

**무엇을 막는가**: ORM 컬럼은 nullable인데 대응 schema 필드가 *비옵셔널 + 기본값*인 자리에서
`to_schema()`가 NULL을 그대로 넘겨 `ValidationError`를 내던 결함. 실제 피해는 OAuth 콜백
(`api/auth.py:resolve_user`)이 `from_schema`를 경유하지 않고 ORM 생성자를 직접 불러 배열
4컬럼을 NULL로 남긴 것이고, 그 결과 **운영 로그인으로 만들어진 계정이 `GET/PATCH
/v1/users/me`에서 500**이었다.

이 파일은 세 층을 동결한다:
  1. 헬퍼 자체의 판정 규칙(경계 4종 — 각 절마다 *그 절이 없으면 통과하는* 반례를 픽스처로 둔다)
  2. `UserProfile.to_schema()`의 회귀(결함이 났던 바로 그 지점)
  3. **전수 거버넌스** — 저장소의 모든 ORM 모델에 대해 같은 형태의 불일치가 남아 있지 않은지
     매퍼·스키마에서 산출물로 판정한다(이름 목록 열거 없음). 새 모델·새 컬럼이 같은 함정에
     빠지면 여기서 red가 난다.
"""

from __future__ import annotations

import importlib
import pkgutil
import typing
import uuid

import pytest
import sqlalchemy as sa
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from pydantic_core import PydanticUndefined
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

import whymath_backend.db.models as models_pkg
from whymath_backend.db.base import Base
from whymath_backend.db.models._schema_seam import drop_unset_nulls
from whymath_backend.db.models.user import UserProfile as OrmUserProfile
from whymath_backend.schema.enums import Persona

# 모든 모델 모듈을 임포트해 매퍼를 등록시킨다(전수 거버넌스의 전제 — 미임포트 모델은
# `Base.registry.mappers`에 없어 스캔 0건으로 *공허하게* 통과한다).
for _mod in pkgutil.iter_modules(models_pkg.__path__):
    importlib.import_module(f"{models_pkg.__name__}.{_mod.name}")


# ──────────────────────────────────────────────────────────────────────────
# 1) 헬퍼 판정 규칙 — 절마다 그 절의 반례를 픽스처로 둔다
#    (CLAUDE.md "픽스처가 그 절을 실제로 밟는가" — 절을 지웠을 때 실패하는 입력이어야 한다)
# ──────────────────────────────────────────────────────────────────────────
class _Probe(BaseModel):
    """헬퍼의 네 분기를 각각 밟는 최소 스키마."""

    pk: uuid.UUID = Field(default_factory=uuid.uuid4)  # PK 절: 기본값 있으나 보호돼야 함
    items: list[str] = Field(default_factory=list)  # 대상: None 거부 + 기본값
    nickname: str | None = None  # None 허용 절: 빼면 안 됨(None이 뜻을 가짐)
    required_text: str  # 기본값 없는 required 절: 빼면 안 됨(메울 값 없음)


class _ProbeBase(DeclarativeBase):
    """픽스처 전용 선언 베이스 — **운영 `Base.metadata`에 테이블을 등록하지 않는다.**

    처음엔 이 픽스처를 운영 `Base`에 붙였는데, 그러면 `_seam_probe`가 `Base.metadata`에 들어가
    정본 엔티티 동결(`test_canonical_entity_model_freeze.py`)이 "귀속 없는 신규 테이블"로 red를
    냈다 — 맞는 지적이다. 테스트 픽스처는 도메인 엔티티가 아니므로 정본에 등재할 것이 아니라
    등록 자체를 격리해야 한다(alembic autogenerate에 섞이는 것도 같은 이유로 막는다).
    """


class _ProbeOrm(_ProbeBase):
    """`_Probe`에 대응하는 최소 ORM — PK 판정을 매퍼에서 뽑기 위해 실재 매핑이 필요하다."""

    __tablename__ = "_seam_probe"
    pk: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    items: Mapped[list[str] | None] = mapped_column(sa.ARRAY(sa.Text))
    nickname: Mapped[str | None] = mapped_column(sa.Text)
    required_text: Mapped[str | None] = mapped_column(sa.Text)


def _drop(data: dict[str, object]) -> dict[str, object]:
    return drop_unset_nulls(data, _Probe, orm_cls=_ProbeOrm)


def test_nonoptional_field_with_default_drops_null() -> None:
    """대상 절 — None 거부 + 기본값 보유 필드의 NULL은 빠져서 기본값이 적용된다."""
    out = _drop({"items": None, "required_text": "x"})
    assert "items" not in out, out
    assert _Probe.model_validate(out).items == []


def test_primary_key_null_is_never_dropped() -> None:
    """PK 절의 반례 — PK는 `default_factory`가 있어도 빠지면 안 된다.

    이 절이 없으면 NULL PK에 대해 매 호출 *새 UUID가 지어져* 전혀 다른 주체의 레코드처럼
    200이 나간다. 그래서 픽스처는 "기본값이 있는 PK"여야 한다(기본값 없는 PK는 required
    절이 이미 막으므로 이 절을 밟지 않는다).
    """
    out = _drop({"pk": None, "required_text": "x"})
    assert out["pk"] is None, "PK가 빠져 기본값으로 지어졌다"
    with pytest.raises(ValidationError):
        _Probe.model_validate(out)


def test_optional_field_keeps_its_null() -> None:
    """None 허용 절의 반례 — `str | None`에서 None은 *뜻이 있는 값*이라 보존한다."""
    out = _drop({"nickname": None, "required_text": "x"})
    assert "nickname" in out and out["nickname"] is None


def test_required_without_default_keeps_null_and_still_fails() -> None:
    """required 절의 반례 — 기본값이 없으면 조용히 메우지 않고 검증 실패를 남긴다."""
    out = _drop({"required_text": None})
    assert out["required_text"] is None
    with pytest.raises(ValidationError):
        _Probe.model_validate(out)


def test_input_dict_is_not_mutated() -> None:
    """호출자의 dict를 오염시키지 않는다(다른 용도로 쓰는 호출부가 있다)."""
    src: dict[str, object] = {"items": None, "required_text": "x"}
    _drop(src)
    assert src == {"items": None, "required_text": "x"}


# ──────────────────────────────────────────────────────────────────────────
# 2) 회귀 — 결함이 났던 바로 그 지점
# ──────────────────────────────────────────────────────────────────────────
def test_orm_constructed_user_profile_converts_to_schema() -> None:
    """`resolve_user`와 동형으로 ORM 생성자만 써서 만든 행이 `to_schema()`를 통과한다.

    `from_schema`를 경유하지 않는다 — 경유하면 `[]`가 채워져 이 경로를 지나가지 않으므로
    결함을 한 번도 밟지 않는다(원 결함이 1년 가까이 숨어 있던 이유가 정확히 그것이다).
    """
    user = OrmUserProfile(
        user_id=uuid.uuid4(),
        email_hash="a" * 64,
        persona_primary=list(Persona)[0],
    )
    assert user.track_type is None, "픽스처 전제 붕괴 — 이 컬럼이 NULL이어야 결함을 밟는다"

    schema = user.to_schema()

    assert schema.track_type == []
    assert schema.target_universities == []
    assert schema.inkang_provider == []
    assert schema.accessibility_needs == []
    assert schema.user_id == user.user_id, "PK가 재생성되면 남의 프로필을 돌려주는 것과 같다"


def test_explicit_empty_lists_are_preserved() -> None:
    """대조군 — 이미 `[]`인 행은 그대로 통과한다(과잉 수정 탐지)."""
    user = OrmUserProfile(
        user_id=uuid.uuid4(),
        email_hash="c" * 64,
        persona_primary=list(Persona)[0],
        track_type=[],
        inkang_provider=["메가스터디"],
    )
    schema = user.to_schema()
    assert schema.track_type == []
    assert schema.inkang_provider == ["메가스터디"]


# ──────────────────────────────────────────────────────────────────────────
# 3) 전수 거버넌스 — 이름 열거 없이 매퍼·스키마에서 산출물로 판정
# ──────────────────────────────────────────────────────────────────────────
def _schema_of(orm_cls: type) -> type[BaseModel] | None:
    """`to_schema()`의 반환 스키마 클래스를 타입힌트에서 뽑는다(없으면 None)."""
    fn = getattr(orm_cls, "to_schema", None)
    if fn is None:
        return None
    try:
        ret = typing.get_type_hints(fn).get("return")
    except Exception:  # noqa: BLE001 — 해석 불가는 대상 제외(아래 스캔 0건 가드가 받친다)
        return None
    return ret if isinstance(ret, type) and issubclass(ret, BaseModel) else None


def _mismatches() -> list[tuple[type, type[BaseModel], str]]:
    """(ORM, schema, 컬럼명) — nullable 컬럼 ↔ None 거부 + 기본값 보유 비-PK 필드."""
    found: list[tuple[type, type[BaseModel], str]] = []
    for mapper in Base.registry.mappers:
        orm_cls = mapper.class_
        schema_cls = _schema_of(orm_cls)
        if schema_cls is None:
            continue
        pks = {a.key for a in mapper.column_attrs if any(c.primary_key for c in a.columns)}
        for attr in mapper.column_attrs:
            if attr.key in pks or not all(c.nullable for c in attr.columns):
                continue
            field = schema_cls.model_fields.get(attr.key)
            if field is None:
                continue
            if field.default_factory is None and field.default is PydanticUndefined:
                continue  # 기본값 없는 required — 의도적 미대상(헬퍼 docstring 1)
            try:
                TypeAdapter(field.annotation).validate_python(None)
            except Exception:  # noqa: BLE001
                found.append((orm_cls, schema_cls, attr.key))
    return found


def test_scan_finds_targets_at_all() -> None:
    """스캔 0건 가드 — 대상을 하나도 못 찾은 전수 검사는 *공허하게* 통과한다.

    (CLAUDE.md "스캔 0건은 실패": 모델 임포트가 깨지거나 타입힌트 해석이 전멸하면 아래
    거버넌스 테스트가 아무것도 안 보고 초록이 된다. 그 상태를 여기서 분리해 잡는다.)
    """
    hits = _mismatches()
    assert hits, "nullable↔비옵셔널 불일치가 0건 — 스캔이 모델을 못 본 것이 아닌지 확인하라"
    orm_names = {orm.__name__ for orm, _schema, _key in hits}
    assert "UserProfile" in orm_names, f"원 결함 지점이 스캔에 안 잡힌다: {sorted(orm_names)}"


@pytest.mark.parametrize("case", _mismatches(), ids=lambda c: f"{c[0].__name__}.{c[2]}")
def test_every_nullable_nonoptional_column_round_trips(
    case: tuple[type, type[BaseModel], str],
) -> None:
    """불일치가 *실재하는 전 지점*에서 NULL이 기본값으로 읽힌다 — 부분 수정 금지의 기계 집행.

    새 모델이 같은 함정(nullable 컬럼 ↔ 비옵셔널 기본값 필드)을 만들고 `to_schema()`에
    `drop_unset_nulls`를 배선하지 않으면 여기서 red가 난다. 고치는 법: 그 모델의
    `to_schema()`가 `drop_unset_nulls(data, <Schema>, orm_cls=type(self))`를 경유하게 한다.
    """
    orm_cls, schema_cls, key = case
    dropped = drop_unset_nulls({key: None}, schema_cls, orm_cls=orm_cls)
    assert key not in dropped, (
        f"{orm_cls.__name__}.{key}: NULL이 비옵셔널 필드로 그대로 넘어간다 — "
        f"{schema_cls.__name__} 변환이 ValidationError로 500을 낸다"
    )
