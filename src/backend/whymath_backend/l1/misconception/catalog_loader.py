"""오개념 카탈로그 코퍼스 → backend ORM 적재기 (Phase B.3 — misconception_catalog).

`l1/standards/standard_loader.py`의 `AchievementStandardStore`·`load_standards`의 *오개념* 짝이다.
Phase B.2(#291)가 카탈로그의 ORM(`db/models/misconception_catalog.py`)·계약
(`schema/misconception_catalog.py`)·마이그레이션만 세우고 코퍼스 로더는 *후속 몫*으로 보류했는데,
이 모듈이 그 로더를 놓는다 — #290 코퍼스(`data/corpus/misconceptions_v1/misconceptions.json`·
839 레코드·Collection JSON)를 backend 영속 `misconception_catalog` 테이블로 멱등 적재한다.

(주의: 기존 `l4/misconception`는 *탐지 엔진*(kebab-id 30종)으로 별개 체계다. 이 패키지는 L1
*적재* 인프라이며 두 체계는 FK로 잇지 않는다 — ORM/schema 모듈 docstring "별개 체계".)

────────────────────────────────────────────────────────────────────────────
성취기준 로더 대비 단순화 (rename·해석 seam 둘 다 없음)
────────────────────────────────────────────────────────────────────────────
성취기준 로더는 두 seam을 메웠다 — ① 코퍼스 `code`→backend `official_code` rename, ②
`concept_src_id`(src_id)→재ID된 새 `code` 해석(resolve-via-map). 오개념은 *둘 다 없다*:
  - 코퍼스 키 = schema 필드(영문·이미 정규화됨)라 rename이 없다(`_misconception_from_row`는 그냥
    `MisconceptionCatalog.model_validate(row)`).
  - `concept_src_id`·`standard_code`는 ORM 컬럼에 *원천 그대로* 저장한다(느슨참조·FK 아님·해소
    없음 — ORM 모듈 docstring). 따라서 성취기준 링크 로더의 concept 해소 로직은 미러하지 않는다.
단일 PK(`mis_id`) 충돌 upsert만 한다(성취기준의 norm_id PK upsert와 동형).

멱등(PG ON CONFLICT — standard_loader 규약): PK `mis_id` 충돌 시 `INSERT ... ON CONFLICT(mis_id)
DO UPDATE`로 나머지 컬럼을 갱신한다. PK는 SET하지 않아 보존한다(멱등). 입력 내 mis_id 중복은
*마지막 우선* dedup한다(단일 배치 ON CONFLICT가 같은 행을 두 번 건드리는 오류 방지).

sync 엔진은 슬3 `_build_sync_engine`을 재사용한다(신규 seam 0 — standard_loader와 동일 좌석
규약). 자격은 env(`Settings.sync_database_url`)·하드코딩 0.

7계층: L1 데이터 기반의 *런타임 엔티티 적재*. 소비(진단·distractor 생성)는 이 행을 *조회*하되
여기서 구현하지 않는다(역방향 의존 금지·후속).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from whymath_backend.config import Settings, get_settings
from whymath_backend.db.cms_edit_marker import (
    CMS_EDIT_MARKER,
    format_conflict,
    upsert_guard,
    upsert_skipped,
)

# ORM·schema 이름 충돌 주의 — ORM은 alias(MisconceptionCatalogORM).
from whymath_backend.db.models.misconception_catalog import (
    MisconceptionCatalog as MisconceptionCatalogORM,
)

# 슬3 sync 엔진 빌더 재사용(신규 seam 0) — standard_loader와 동일 규약.
from whymath_backend.l1.concept_graph.embedding import _build_sync_engine
from whymath_backend.schema.misconception_catalog import MisconceptionCatalog

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


# ──────────────────────────────────────────────────────────────────────────
# 코퍼스 입력 정규화 (dict | Path → Collection dict)
# ──────────────────────────────────────────────────────────────────────────
def _as_collection(source: dict[str, Any] | Path) -> dict[str, Any]:
    """코퍼스 입력을 Collection dict로 정규화 — `dict`는 그대로, `Path`는 단일 JSON 객체로 로드.

    data-pipeline 오개념 추출기는 *한 개의 JSON 객체*(Collection)를 내므로 `json.loads`로 통째
    읽는다(jsonl 아님). dict가 들어오면 이미 로드된 컬렉션으로 보고 그대로 쓴다(테스트·in-memory
    경로). 그 외 타입은 거부한다(정직).

    Raises:
        FileNotFoundError: Path가 가리키는 파일 부재.
        TypeError: dict·Path가 아닌 입력.
    """
    if isinstance(source, dict):
        return source
    if isinstance(source, Path):
        loaded: dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))
        return loaded
    raise TypeError(f"코퍼스 입력은 dict 또는 Path여야 합니다: {type(source).__name__}")


# ──────────────────────────────────────────────────────────────────────────
# 오개념 적재 (코퍼스 misconceptions → misconception_catalog·mis_id ON CONFLICT)
# ──────────────────────────────────────────────────────────────────────────
def _misconception_from_row(row: dict[str, Any]) -> MisconceptionCatalog:
    """코퍼스 오개념 dict → 검증된 `schema.MisconceptionCatalog` (rename 0).

    성취기준 로더와 달리 코퍼스 키 = schema 필드(영문·이미 정규화)라 rename seam이 없다 — 행을
    그대로 `model_validate`한다. schema가 형식·필수성(`mis_id`)을 게이트한다(extra=forbid).
    """
    return MisconceptionCatalog.model_validate(row)


def load_misconceptions(
    session: dict[str, Any] | Path | None,
    collection_json: dict[str, Any] | Path,
    *,
    engine: Engine | None = None,
    settings: Settings | None = None,
    store: MisconceptionCatalogStore | None = None,
    overwrite_cms_edits: bool = False,
    conflicts: list[str] | None = None,
) -> int:
    """오개념 Collection JSON을 backend `misconception_catalog`에 멱등 upsert. 반환=적재 행 수.

    `overwrite_cms_edits`·`conflicts`는 CMS 편집 보호(P3-25)다 —
    `MisconceptionCatalogStore.populate` docstring 참조. 보호로 건너뛴 행은 반환 행 수에서 빠진다.

    `load_standards`(성취기준)의 *오개념* 짝이다 — Collection의 `misconceptions` 배열을 행마다
    `schema.MisconceptionCatalog`로 빌드(rename 0)한 뒤 `mis_id` PK 충돌 멱등 upsert한다. 입력 내
    mis_id 중복은 *마지막 우선* dedup한다(단일 배치 ON CONFLICT 중복행 오류 방지). 빈 컬렉션은
    0(조기 반환).

    `session` 인자는 standard_loader의 store/engine 좌석 규약 호환을 위한 *자리표시*다(이 적재기는
    sync 엔진으로 동작하므로 ORM async Session을 쓰지 않는다 — None 허용). store/engine/settings
    미주입 시 슬3 sync 엔진 재사용 `MisconceptionCatalogStore`를 만든다.

    Raises:
        FileNotFoundError: collection_json이 Path인데 파일 부재.
        pydantic.ValidationError: 코퍼스 행이 schema 형식을 위반(형식 게이트는 schema 몫).
    """
    del session  # async Session 미사용(sync 엔진 좌석) — 호환 자리표시.
    collection = _as_collection(collection_json)
    rows = collection.get("misconceptions", [])
    misconceptions = [_misconception_from_row(row) for row in rows]
    if not misconceptions:
        return 0
    resolved = settings if settings is not None else get_settings()
    mis_store = (
        store if store is not None else MisconceptionCatalogStore(engine=engine, settings=resolved)
    )
    return mis_store.populate(
        misconceptions, overwrite_cms_edits=overwrite_cms_edits, conflicts=conflicts
    )


class MisconceptionCatalogStore:
    """오개념 카탈로그 코퍼스 → `misconception_catalog` 적재기 — mis_id PK 멱등 upsert(sync).

    `AchievementStandardStore`(성취기준)의 *오개념* 짝이다(같은 sync 좌석·멱등 규약). `populate`는
    각 오개념을 `INSERT ... ON CONFLICT(mis_id) DO UPDATE`로 멱등 적재한다 — 같은 mis_id 재적재는
    나머지 컬럼을 갱신한다(mis_id는 의미 문자열 PK라 server_default 없음·로더가 채움). 입력 내
    mis_id 중복은 적재 전 *마지막 우선* dedup한다(단일 배치 ON CONFLICT가 같은 행을 두 번 건드리는
    오류 방지). sync 엔진은 슬3 `_build_sync_engine`을 재사용해 지연 생성·캐시한다(신규 seam 0).

    본문 적재(와이매스 자체 저작): `canonical_statement` 등 본문은 자체 저작이라 보유가 허용된다
    (redaction 불요 — ORM 모듈 docstring 법적 메모).
    """

    def __init__(
        self,
        *,
        engine: Engine | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._engine = engine
        self._settings = settings

    @property
    def _resolved_settings(self) -> Settings:
        """설정 지연 해석 — 주입 우선, 없으면 캐시된 전역 Settings(standard_loader 패턴)."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_engine(self) -> Engine:
        """sync 엔진 지연 해석 — 주입 우선, 없으면 슬3 빌더로 생성·캐시(신규 seam 0)."""
        if self._engine is None:
            self._engine = _build_sync_engine(self._resolved_settings)
        return self._engine

    def populate(
        self,
        records: Sequence[MisconceptionCatalog],
        *,
        overwrite_cms_edits: bool = False,
        conflicts: list[str] | None = None,
    ) -> int:
        """오개념 schema 모델들을 `misconception_catalog`에 멱등 upsert. 반환=적재 행 수(dedup 후).

        **CMS 편집 보호(P3-25)**: CMS가 고친 행(`cms_edited_at` 있음)은 건너뛰고 `conflicts`에
        `misconception_catalog:<mis_id>`로 보고한다 — 반환 행 수에는 포함하지 않는다.
        `overwrite_cms_edits=True`면 덮어쓰고 표지를 비운다.

        ① mis_id PK 기준 *마지막 우선* dedup(단일 배치 ON CONFLICT 중복행 오류 방지) → ② 각 행을
        `ON CONFLICT(mis_id) DO UPDATE`로 적재(나머지 컬럼 갱신·PK는 SET 안 함·보존). 입력 빈 0.
        컬럼 값은 검증된 schema 모델의 `model_dump()`에서 ORM 컬럼키만 추려 바인딩한다(schema
        필드명=ORM 컬럼명). 반환은 적재 시도 행 수(dedup 후 길이)다.
        """
        if not records:
            return 0

        import sqlalchemy as sa
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        # mis_id PK 기준 dedup(마지막 우선) — 단일 배치 INSERT의 ON CONFLICT 중복행 오류 방지.
        by_mis_id: dict[str, MisconceptionCatalog] = {r.mis_id: r for r in records}
        deduped = list(by_mis_id.values())

        # PK mis_id를 제외한 갱신 컬럼 집합(ON CONFLICT DO UPDATE SET) — mapper 컬럼키에서 도출.
        all_keys = {col.key for col in sa.inspect(MisconceptionCatalogORM).mapper.column_attrs}
        # 표지 컬럼은 코퍼스 값이 아니라 보호 규약이 소유한다 — 일반 갱신 집합에서 뺀다.
        update_keys = all_keys - {"mis_id", CMS_EDIT_MARKER}
        where, release = upsert_guard(MisconceptionCatalogORM, overwrite=overwrite_cms_edits)

        written = 0
        with self._get_engine().begin() as conn:
            for record in deduped:
                # 검증된 schema에서 ORM 컬럼 값만 추린다(schema 필드명=ORM 컬럼명).
                payload = record.model_dump()
                values = {k: v for k, v in payload.items() if k in all_keys}
                stmt = pg_insert(MisconceptionCatalogORM).values(**values)
                # mis_id(PK) 충돌 시 나머지 컬럼 갱신 — PK는 SET하지 않아 보존(멱등).
                upsert = stmt.on_conflict_do_update(
                    index_elements=[MisconceptionCatalogORM.mis_id],
                    set_={**{key: stmt.excluded[key] for key in update_keys}, **release},
                    where=where,
                ).returning(MisconceptionCatalogORM.mis_id)
                if upsert_skipped(conn.execute(upsert)):
                    if conflicts is not None:
                        conflicts.append(format_conflict("misconception_catalog", record.mis_id))
                else:
                    written += 1
        return written


__all__ = [
    "MisconceptionCatalogStore",
    "load_misconceptions",
]
