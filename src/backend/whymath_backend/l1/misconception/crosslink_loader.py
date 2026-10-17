"""오개념 crosswalk(kebab-id ↔ M-id) 매핑 → `misconception_crosslink` 멱등 적재기.

`catalog_loader.py`(M-id 카탈로그 적재)의 *crosswalk* 짝이다. 큐레이션 매핑 Collection JSON
(`{"crosslinks": [{kebab_id, mis_id, link_type, confidence, method, note}, ...]}`)을 backend 영속
`misconception_crosslink` 테이블에 멱등 upsert한다.

**매핑 데이터 = 사람 검수 산출물**(math_dsl_remediation_design.md §1·CLAUDE.md 우선순위 #1·#3):
틀린 매핑은 오도된 학부모/학생 리포트로 이어지므로 자동 생성 매핑을 검수 없이 적재하지 않는다.
실제 매핑 파일은 검수 후 별도로 공급한다(코드 슬라이스엔 미동봉). `load_crosslinks`는 적재 직전
**Gate Contract**(`crosslink_gate.load_gate_violations`)를 강제한다 — 전 행 `method="manual"`이고
note에 검수 서명 stamp가 있어야 하므로, promote --load 산출물만 통과하고 candidate/미서명 직접
적재는 거부된다(검수 우회·자기승인을 *코드로* 차단). 저수준 `Store.populate`는 게이트를 안 거친다
(resolve/shadow 단위의 합성 시딩 좌석).

멱등(PG ON CONFLICT — catalog_loader 규약): PK는 `link_id`(UUID·server_default)지만 *의미 유일키*는
`(kebab_id, mis_id, link_type)`라 그 트리플 충돌 시 confidence·method·note만 갱신한다(link_id 보존).
입력 내 트리플 중복은 *마지막 우선* dedup(단일 배치 ON CONFLICT 중복행 오류 방지).

sync 엔진은 슬3 `_build_sync_engine` 재사용(신규 seam 0). 자격은 env(`Settings.sync_database_url`).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from whymath_backend.config import Settings, get_settings

# ORM·schema 이름 충돌 주의 — ORM은 alias(MisconceptionCrosslinkORM).
from whymath_backend.db.models.misconception_crosslink import (
    MisconceptionCrosslink as MisconceptionCrosslinkORM,
)
from whymath_backend.l1.concept_graph.embedding import _build_sync_engine
from whymath_backend.l1.fk_precheck import (
    ForeignKeyTargetMissingError,
    MissingFkTargets,
    missing_fk_targets,
)
from whymath_backend.l1.misconception.crosslink_gate import (
    CrosslinkGateError,
    load_gate_violations,
)
from whymath_backend.l1.misconception.crosslink_resolve import (
    CanonicalLoadVerdict,
    MisconceptionCrosslinkResolver,
    ResolvedLink,
    simulate_load_canonical,
)
from whymath_backend.schema.misconception_crosslink import MisconceptionCrosslink

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


def _as_collection(source: dict[str, Any] | Path) -> dict[str, Any]:
    """매핑 입력을 Collection dict로 정규화 — `dict`는 그대로, `Path`는 단일 JSON 객체로 로드.

    Raises:
        FileNotFoundError: Path가 가리키는 파일 부재.
        TypeError: dict·Path가 아닌 입력.
    """
    if isinstance(source, dict):
        return source
    if isinstance(source, Path):
        loaded: dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))
        return loaded
    raise TypeError(f"crosswalk 입력은 dict 또는 Path여야 합니다: {type(source).__name__}")


def _crosslink_from_row(row: dict[str, Any]) -> MisconceptionCrosslink:
    """매핑 dict → 검증된 `schema.MisconceptionCrosslink`(rename 0·extra=forbid 게이트)."""
    return MisconceptionCrosslink.model_validate(row)


class CanonicalFlipError(Exception):
    """적재가 라이브 잔존 행과 경쟁해 canonical을 코퍼스 의도와 다르게 만든다 — 쓰기 0건.

    업서트는 코퍼스에 없는 라이브 행을 지우지 못한다(HARN-216). `verdicts`에 `wrong_winner`·`tie`
    판정 kebab **전건**이 있고 메시지도 전건을 싣는다(일부만 보이면 고치고 다시 돌려 또 걸린다).
    해소는 라이브 잔존 행을 사람이 확인한 뒤 삭제하는 것뿐이다 — 이 도구에는 우회 인자가 없다.
    """

    def __init__(self, verdicts: list[CanonicalLoadVerdict]) -> None:
        self.verdicts = verdicts
        lines = [
            f"적재 후 canonical이 코퍼스 의도와 달라지는 kebab {len(verdicts)}건 — "
            "아무것도 쓰지 않았습니다:"
        ]
        for v in verdicts:
            want = (
                f"{v.corpus.canonical_mis_id}({v.corpus_confidence})"
                if v.corpus.canonical_mis_id is not None
                else f"미선정({v.corpus.reason})"
            )
            got = (
                v.after_load.canonical_mis_id
                if v.after_load.canonical_mis_id is not None
                else f"미선정({v.after_load.reason})"
            )
            rivals = ", ".join(f"{r.mis_id}({r.confidence})" for r in v.rivals) or "없음"
            lines.append(
                f"  · {v.kebab_id} [{v.verdict}]: 코퍼스 의도 {want} → 적재 후 {got} "
                f"· 라이브 잔존 행 {rivals}"
            )
        lines.append(
            "해소: 위 라이브 잔존 행이 오귀속인지 사람이 확인해 삭제한 뒤 다시 적재하세요"
            "(우회 인자 없음)."
        )
        super().__init__("\n".join(lines))


def _incoming_links(crosslinks: Sequence[MisconceptionCrosslink]) -> dict[str, list[ResolvedLink]]:
    """적재 예정 행 → kebab별 `ResolvedLink`(시뮬 입력). 트리플 중복 접기는 시뮬이 맡는다."""
    grouped: dict[str, list[ResolvedLink]] = {}
    for record in crosslinks:
        grouped.setdefault(record.kebab_id, []).append(
            ResolvedLink(
                mis_id=record.mis_id, link_type=record.link_type, confidence=record.confidence
            )
        )
    return grouped


def canonical_flip_verdicts(
    store: MisconceptionCrosslinkStore, crosslinks: Sequence[MisconceptionCrosslink]
) -> list[CanonicalLoadVerdict]:
    """라이브 행을 읽어 적재 후 canonical을 시뮬해 **코퍼스와 다른 kebab만** 돌려준다(읽기)."""
    incoming = _incoming_links(crosslinks)
    live = store.live_links(list(incoming))
    return [v for v in simulate_load_canonical(live, incoming) if v.verdict != "ok"]


def load_crosslinks(
    session: dict[str, Any] | Path | None,
    collection_json: dict[str, Any] | Path,
    *,
    engine: Engine | None = None,
    settings: Settings | None = None,
    store: MisconceptionCrosslinkStore | None = None,
    check_fk_targets: bool = True,
) -> int:
    """crosswalk Collection JSON을 `misconception_crosslink`에 멱등 upsert. 반환=적재 행 수.

    Collection의 `crosslinks` 배열을 행마다 `schema.MisconceptionCrosslink`로 빌드(rename 0)한 뒤
    의미 유일키 `(kebab_id, mis_id, link_type)` 충돌 멱등 upsert한다. 빈 컬렉션은 0(조기 반환).
    `session`은 catalog_loader 좌석 규약 호환 자리표시(sync 엔진 사용·async Session 불요).

    Raises:
        FileNotFoundError: collection_json이 Path인데 파일 부재.
        pydantic.ValidationError: 행이 schema 형식을 위반.
        CrosslinkGateError: load 게이트 위반(method≠manual·미서명 — 검수 우회·전건 열거).
        ForeignKeyTargetMissingError: `mis_id`가 `misconception_catalog`에 없다(HARN-302) —
            쓰기 **전에** 읽기만으로 확인해 누락 키를 전건 열거하고 아무것도 쓰지 않는다.
            `check_fk_targets=False`는 가짜 엔진을 쓰는 hermetic 테스트용 좌석이다
            (실 경로는 항상 켠다).
        CanonicalFlipError: 적재 후 canonical이 코퍼스 의도와 달라진다(HARN-216) — 라이브 잔존 행이
            더 높은 신뢰도로 이기거나(wrong_winner) 같은 신뢰도로 동률을 만든다(tie). 쓰기 **전에**
            읽기만으로 판정하고 아무것도 쓰지 않는다. **끄는 인자가 없다**(`check_fk_targets` 무관).
    """
    del session  # async Session 미사용(sync 엔진 좌석) — 호환 자리표시.
    collection = _as_collection(collection_json)
    rows = collection.get("crosslinks", [])
    crosslinks = [_crosslink_from_row(row) for row in rows]
    if not crosslinks:
        return 0
    # load 게이트(Gate Contract) — method=manual·검수 서명 없는 행은 거부(검수 우회·자기승인 차단).
    # promote --load 산출물은 통과하고, candidate/미서명 직접 적재는 막는다(전건 열거).
    violations = load_gate_violations(crosslinks)
    if violations:
        raise CrosslinkGateError("crosswalk load 게이트 위반:\n" + "\n".join(violations))
    resolved = settings if settings is not None else get_settings()
    cl_store = (
        store
        if store is not None
        else MisconceptionCrosslinkStore(engine=engine, settings=resolved)
    )
    if check_fk_targets:
        # 적재 전 외래키 대상 사전확인(HARN-302) — 누락이 하나라도 있으면
        # 쓰기 0건으로 전건 열거 거부.
        missing = cl_store.missing_fk_targets(crosslinks)
        if missing:
            raise ForeignKeyTargetMissingError(missing)
    # canonical 경쟁 사전판정(HARN-216) — 끄는 인자 없음. 코퍼스에 없는 라이브 행은 업서트가 지우지
    # 못하므로, 적재 후 canonical이 코퍼스 의도와 달라지면 쓰기 전에 전건 열거하고 거부한다.
    flips = canonical_flip_verdicts(cl_store, crosslinks)
    if flips:
        raise CanonicalFlipError(flips)
    return cl_store.populate(crosslinks)


class MisconceptionCrosslinkStore:
    """crosswalk 매핑 → `misconception_crosslink` 적재기 — 의미 유일키 멱등 upsert(sync).

    `MisconceptionCatalogStore`(M-id 카탈로그)의 *crosswalk* 짝이다. `populate`는 각 매핑을
    `INSERT ... ON CONFLICT(kebab_id, mis_id, link_type) DO UPDATE`로 멱등 적재한다 — 같은 트리플
    재적재는 confidence·method·note를 갱신한다(link_id PK는 보존·SET 안 함). 입력 내 트리플 중복은
    적재 전 *마지막 우선* dedup한다. sync 엔진은 슬3 `_build_sync_engine` 재사용(신규 seam 0).
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
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_engine(self) -> Engine:
        if self._engine is None:
            self._engine = _build_sync_engine(self._resolved_settings)
        return self._engine

    def missing_fk_targets(
        self, records: Sequence[MisconceptionCrosslink]
    ) -> list[MissingFkTargets]:
        """적재 대상 행의 외래키(`mis_id`) 참조 대상 중 DB에 없는 것을 전건 센다(HARN-302).

        읽기 전용이다. `populate`와 **다른 트랜잭션**이다: 확인 뒤 쓰기 전에 대상이 지워지면 DB
        외래키 제약이 마지막 방어선이다(`fk_precheck` 모듈 한계 절). `populate`는 순수 쓰기 원시
        함수로 남겨 합성 시딩 좌석(resolve/shadow 테스트)의 동작을 바꾸지 않는다.
        """
        table = MisconceptionCrosslinkORM.__table__
        rows = [record.model_dump() for record in records]
        with self._get_engine().connect() as conn:
            return missing_fk_targets(conn, table, rows)  # type: ignore[arg-type]

    def live_links(self, kebab_ids: Sequence[str]) -> dict[str, list[ResolvedLink]]:
        """주어진 kebab들의 라이브 링크 전량(HARN-216 시뮬 입력) — 읽기 전용·쓰기와 다른 트랜잭션.

        조회는 resolver의 단일 조회 경로(`resolve_links_many`)를 그대로 쓴다 — 읽기 진실 원천을
        하나로 둔다. 확인과 쓰기 사이에 다른 세션이 행을 넣으면 이 판정은 낡는다 —
        `fk_precheck`의 한계 절과 같은 종류이며, 적재는 운영자 1인의 수동 작업이라
        수용하고 문서화한다.
        """
        resolver = MisconceptionCrosslinkResolver(engine=self._get_engine())
        return resolver.resolve_links_many(kebab_ids)

    def populate(self, records: Sequence[MisconceptionCrosslink]) -> int:
        """crosswalk schema 모델들을 멱등 upsert. 반환=적재 행 수(dedup 후).

        ① 의미 유일키 `(kebab_id, mis_id, link_type)` 기준 *마지막 우선* dedup → ② 각 행을
        `ON CONFLICT(kebab_id, mis_id, link_type) DO UPDATE`로 적재(confidence·method·note 갱신·
        link_id PK 보존). 컬럼 값은 검증된 schema `model_dump()`에서 ORM 컬럼키만 추려 바인딩한다.
        """
        if not records:
            return 0

        import sqlalchemy as sa
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        # 의미 유일키 dedup(마지막 우선) — 단일 배치 ON CONFLICT 중복행 오류 방지.
        by_key: dict[tuple[str, str, str], MisconceptionCrosslink] = {
            (r.kebab_id, r.mis_id, r.link_type): r for r in records
        }
        deduped = list(by_key.values())

        all_keys = {col.key for col in sa.inspect(MisconceptionCrosslinkORM).mapper.column_attrs}
        # 충돌 시 갱신 컬럼 — 의미키·link_id(PK)는 SET하지 않아 보존(멱등).
        conflict_cols = {"kebab_id", "mis_id", "link_type", "link_id"}
        update_keys = all_keys - conflict_cols

        with self._get_engine().begin() as conn:
            for record in deduped:
                payload = record.model_dump()
                values = {k: v for k, v in payload.items() if k in all_keys}
                stmt = pg_insert(MisconceptionCrosslinkORM).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[
                        MisconceptionCrosslinkORM.kebab_id,
                        MisconceptionCrosslinkORM.mis_id,
                        MisconceptionCrosslinkORM.link_type,
                    ],
                    set_={key: stmt.excluded[key] for key in update_keys},
                )
                conn.execute(stmt)
        return len(deduped)


__all__ = [
    "CanonicalFlipError",
    "MisconceptionCrosslinkStore",
    "canonical_flip_verdicts",
    "load_crosslinks",
]
