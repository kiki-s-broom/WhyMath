"""ORM→schema 변환(seam)의 NULL 처리 공용 규칙 — `to_schema()`가 쓰는 단일 정본.

**왜 필요한가 (EOS-109)**: ORM 컬럼은 DDL을 따라 nullable인데(`schemas/v1.0/schema_v1.0.md`
§5.1) 대응 schema 필드는 *비옵셔널*이고 기본값만 갖는 경우가 있다 — 예: `user_profile.
track_type`은 `ARRAY(...)` nullable인데 `schema.UserProfile.track_type`은
`list[TrackType] = Field(default_factory=list)`다. 이때 `to_schema()`가 매핑 컬럼을 훑어
`data[key] = None`을 *명시적으로* 넣으면 Pydantic은 "키가 주어졌다"고 보아 `default_factory`를
적용하지 않고 `Input should be a valid list [input_value=None]`로 거부한다.

실제 피해: OAuth 콜백(`api/auth.py:resolve_user`)은 `from_schema`를 경유하지 않고 ORM
생성자를 직접 부르므로 그 4컬럼이 NULL로 남는다 → **운영 로그인 경로로 만들어진 계정은
`GET/PATCH /v1/users/me`가 500이라 자기 프로필을 읽지도 고치지도 못했다**.

**규칙**: `value is None`이고 대응 schema 필드가 ①None을 거부하며 ②기본값(default 또는
default_factory)을 가지면 그 키를 *빼서* 기본값이 적용되게 한다. 즉 "비옵셔널 필드에 대한
ORM NULL"은 `미설정(unset)`으로 읽는다.

일부러 고치지 않는 것이 둘 있다 — 둘 다 "조용히 값을 지어내는 것이 500보다 나쁜" 자리다:

1) **기본값 없는 required 필드** — 키를 그대로 둔다(→ 검증 실패 유지). 그런 컬럼의 NULL은
   "미설정"이 아니라 *데이터 무결성 결함*이거나 의도된 계약이며 메울 값이 없다. 실측 2건:
   `ProblemStep.problem_id`(FK nullable ↔ schema `uuid.UUID` required)와
   `StudentSolutionStep.expression` — 후자는 봉투 암호화 행이 NULL이고 호출자가 복호 평문을
   먼저 확보해야 한다는 계약이 그 모듈 docstring에 *명시*돼 있다.

2) **기본키(PK) 컬럼** — 기본값이 있어도 절대 빼지 않는다. 예컨대 `UserProfile.user_id`는
   schema에서 `default_factory=uuid4`라, 뺐다면 NULL인 PK에 대해 *매 호출 새 UUID를 지어내*
   전혀 다른 학생의 프로필인 양 200을 돌려줬을 것이다. PK의 NULL은 미설정이 아니라 고장이므로
   검증 실패로 남긴다. 보호 대상은 매퍼에서 파생한다(이름 목록 아님).

**판정 방식(열거 금지)**: 어느 필드가 대상인지 *이름 목록으로 적지 않는다*. schema 필드에
실제로 `None`을 넣어 보고(`TypeAdapter`) 거부 여부를, PK 여부는 SQLAlchemy 매퍼에서
산출물로 판정한다 — 새 컬럼이 늘어도 목록 갱신이 필요 없고 목록 누락으로 조용히 뚫리지
않는다(CLAUDE.md "금지 패턴 열거 대신 산출물 검사"). 판정 결과는 (ORM, schema) 쌍당 1회만
계산해 캐시한다(핫 경로 비용 0).

**왜 저장소 전역에 안전한가**: 이 변환이 값을 바꾸는 경우는 "NULL + 비옵셔널 + 기본값 보유"
뿐인데, 그 조합은 이 변경 *이전에 예외 없이 `ValidationError`(→ 500)였다*. 즉 지금 동작하는
경로의 값은 하나도 바뀌지 않고, 터지던 경로만 스키마가 선언한 기본값으로 읽힌다. 기본값이
무언가를 *참칭*하지도 않는다 — 실측상 대상 20건의 기본값은 전부 보수적이다(빈 리스트, 또는
`VersionGovernance()`처럼 created_by·reviewed_by·approved_by가 모두 None인 "아무도 검토·승인하지
않음"). 승인·검토를 긍정하는 기본값은 없다.

**한계(명시)**: 판정은 필드 *어노테이션* 기준이다. 어노테이션은 None을 거부하지만
`BeforeValidator`가 None을 받아 주는 필드가 있다면 이 헬퍼는 그 키를 뺀다(기본값 적용).
저장소 실측상 그런 필드는 없으며, 생기면 거버넌스 테스트가 왕복 검증에서 잡는다
(`tests/backend/db/test_to_schema_null_seam.py`).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import sqlalchemy as sa
from pydantic import BaseModel, TypeAdapter
from pydantic_core import PydanticUndefined
from sqlalchemy.orm import Mapper


@lru_cache(maxsize=None)
def _unset_null_keys(orm_cls: type, schema_cls: type[BaseModel]) -> frozenset[str]:
    """`None`을 "미설정"으로 읽어도 되는 필드명 — None 거부 + 기본값 보유 − PK(산출물 판정)."""
    mapper: Mapper[Any] = sa.inspect(orm_cls).mapper
    # PK는 기본값이 있어도 제외 — NULL PK는 미설정이 아니라 고장이다(모듈 docstring 2).
    primary_keys = {
        attr.key for attr in mapper.column_attrs if any(c.primary_key for c in attr.columns)
    }
    keys: set[str] = set()
    for name, field in schema_cls.model_fields.items():
        if name in primary_keys:
            continue
        has_default = field.default_factory is not None or field.default is not PydanticUndefined
        if not has_default:
            continue  # 기본값 없는 required — 메울 값이 없다(모듈 docstring 1).
        try:
            TypeAdapter(field.annotation).validate_python(None)
        except Exception:  # noqa: BLE001 — 거부하면 어떤 예외든 "None 불가" 판정
            keys.add(name)
    return frozenset(keys)


def drop_unset_nulls(
    data: dict[str, Any], schema_cls: type[BaseModel], *, orm_cls: type
) -> dict[str, Any]:
    """ORM에서 뽑은 `data`에서 "비옵셔널·기본값 보유 비-PK 필드의 NULL" 키를 제거한 새 dict.

    입력 dict는 변경하지 않는다(새 dict 반환 — 호출자의 다른 용도를 오염시키지 않는다).
    """
    droppable = _unset_null_keys(orm_cls, schema_cls)
    return {k: v for k, v in data.items() if not (v is None and k in droppable)}
