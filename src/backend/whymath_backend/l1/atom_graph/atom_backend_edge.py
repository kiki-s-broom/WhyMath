"""원자 백본 선수엣지 → backend `concept_edge` ORM 적재 — PREREQUISITE + relation_subtype(Phase 1).

`l1/concept_graph/backend_edge.py`(구 개념그래프 엣지 적재)의 *원자 백본* 짝이다. 차이점:
  - graph.json 엣지 키가 다르다: `from_code`/`to_code`/`relation`/`relation_subtype`/`strength`
    (구 `src_concept_id`/`dst_concept_id`가 아님).
  - **`relation_subtype`(관계유형: 원본/소단원내/소단원간/학년간/학교급간(추정))을 적재**한다(이번
    슬라이스가 추가한 `concept_edge.relation_subtype` nullable TEXT 컬럼).

방향: `from_code`(선수) → `to_code`(후행) — "from을 알아야 to를 안다". backend
`EdgeType.PREREQUISITE`(A→B: A는 B의 선수)와 일치 → from_code→from_concept_id·to_code→to_concept_id.

범위: graph.json `relation`은 전량 `"prerequisite"`(원자ID 엣지 2,213). 서술형 엣지
(narrative_edges_raw 1,007)는 원자ID가 아니라 적재 대상이 아니다. self-edge·양끝 누락은
로딩에서 skip(불변·FK 방어).

최소 적재: INSERT 컬럼은 (from·to·edge_type·edge_strength·relation_subtype)뿐 —
`typical_gap_signal`·`notes`는 슬롯 부재(NULL·날조 회피). code→UUID 해석은 단일 조회(N+1 0)·
orphan skip(FK 위반 방지).
멱등: UNIQUE(from,to,type) 충돌 시 edge_strength·relation_subtype만 갱신(edge_id·created_at 보존).
sync 엔진은 슬3 `_build_sync_engine` 재사용(신규 seam 0). 자격증명 env·하드코딩 0.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from whymath_backend.config import Settings, get_settings
from whymath_backend.l1.atom_graph.atom_edge_retire import (
    RETIRE_APPLY,
    RETIRE_PLAN,
    RETIRE_REPORT,
    DbEdgeRow,
    RetireOutcome,
    RetirePlan,
    StaleEdgeRetireError,
    plan_retirement,
    summarize,
    validate_mode,
)
from whymath_backend.l1.concept_graph.embedding import _build_sync_engine
from whymath_backend.schema.enums import EdgeType

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.engine import Connection, Engine


# graph.json `relation`(use_enum_values 직렬화) 중 적재 대상 — 선수만(원자ID 엣지 전량).
_PREREQUISITE_RELATION: str = "prerequisite"


def _opt_str(value: object) -> str | None:
    """빈 문자열·None → None, 그 외 strip한 str."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_float(value: object) -> float | None:
    """관계 강도 옵션 파싱 — 빈/None/비수치는 None."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True, slots=True)
class AtomBackendEdgeRecord:
    """backend `concept_edge` 행으로 적재할 한 *선수 관계*의 최소 값 — 원자 백본.

    `from_code`(선수)·`to_code`(후행)는 적재 시 code→UUID로 해석되어 `from_concept_id`·
    `to_concept_id`가 된다(방향 일치). `relation_subtype`은 관계유형(자유 텍스트). **`evidence`·
    `notes`·`typical_gap_signal` 슬롯이 *없다*** — 본문/판단근거라 적재기가 채우지 않는다
    (구조적 차단).
    """

    from_code: str  # 선수 code → from_concept_id
    to_code: str  # 후행 code → to_concept_id
    edge_type: EdgeType  # PREREQUISITE 고정
    edge_strength: float | None  # graph `strength`(0~1)·미기재 None
    relation_subtype: str | None  # 관계유형(원본/소단원내/소단원간/학년간/학교급간 등)


def load_atom_edges_from_graph_json(
    path: Path,
) -> tuple[list[AtomBackendEdgeRecord], list[str]]:
    """원자 코퍼스 `graph.json` → backend `concept_edge` 선수 적재 레코드 + skip 메시지 목록.

    `payload["edges"]`의 각 항목에서 `relation == "prerequisite"`인 엣지만
    `EdgeType.PREREQUISITE`로 매핑한다 — `from_code`(선수)·`to_code`(후행)·`strength`→
    edge_strength·`relation_subtype`. self-edge(from==to)·양끝 누락은 건너뛴다(불변·FK 방어).
    **`evidence`는 읽지 않는다**(슬롯 부재).

    반환: (적재 레코드 목록, skip 사유 메시지 목록). 메시지는 운영 가시성용(조용한 누락 금지).

    Raises:
        FileNotFoundError: graph.json 부재.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: list[AtomBackendEdgeRecord] = []
    skipped: list[str] = []
    for record in payload.get("edges", []):
        relation = _opt_str(record.get("relation"))
        from_code = _opt_str(record.get("from_code"))
        to_code = _opt_str(record.get("to_code"))

        if relation != _PREREQUISITE_RELATION:
            skipped.append(f"비-선수 관계 skip: relation={relation!r} ({from_code}→{to_code})")
            continue
        if from_code is None or to_code is None:
            skipped.append(f"양끝 code 누락 skip: from={from_code!r} to={to_code!r}")
            continue
        if from_code == to_code:
            skipped.append(f"self-edge skip: {from_code}")
            continue

        out.append(
            AtomBackendEdgeRecord(
                from_code=from_code,
                to_code=to_code,
                edge_type=EdgeType.PREREQUISITE,
                edge_strength=_opt_float(record.get("strength")),
                relation_subtype=_opt_str(record.get("relation_subtype")),
            )
        )
    return out, skipped


def read_db_edge_rows(conn: Connection) -> list[DbEdgeRow]:
    """DB `concept_edge` 전량을 코드로 해석해 읽는다(SELECT 한 문장 · 쓰기 없음)."""
    from sqlalchemy import select
    from sqlalchemy.orm import aliased

    from whymath_backend.db.models.concept import Concept, ConceptEdge

    src = aliased(Concept)
    dst = aliased(Concept)
    stmt = (
        select(
            ConceptEdge.edge_id,
            src.code.label("from_code"),
            dst.code.label("to_code"),
            ConceptEdge.relation_subtype,
            ConceptEdge.edge_type,
            ConceptEdge.cms_edited_at.is_not(None).label("cms_owned"),
        )
        .join(src, src.concept_id == ConceptEdge.from_concept_id)
        .join(dst, dst.concept_id == ConceptEdge.to_concept_id)
    )
    rows = conn.execute(stmt).all()
    out: list[DbEdgeRow] = []
    for row in rows:
        edge_type = row.edge_type
        type_text = str(getattr(edge_type, "value", edge_type))
        out.append(
            DbEdgeRow(
                edge_id=str(row.edge_id),
                from_code=str(row.from_code),
                to_code=str(row.to_code),
                relation_subtype=(
                    None if row.relation_subtype is None else str(row.relation_subtype)
                ),
                edge_type=type_text,
                cms_owned=bool(row.cms_owned),
            )
        )
    return out


def delete_stale_edges(conn: Connection, plan: RetirePlan) -> int:
    """계획한 잔존 행만 지운다 — WHERE에 범위 조건을 다시 걸고, 지운 수가 계획과 다르면 올린다.

    호출자는 선수 그래프 잠금(`lock_prerequisite_graph_sync`)을 잡은 트랜잭션 안이어야 한다. 예외는
    트랜잭션을 롤백시킨다 — 계획과 다른 삭제(동시 CMS 편집 등)를 조용히 커밋하지 않는다.
    """
    if not plan.stale:
        return 0
    import uuid

    from sqlalchemy import delete

    from whymath_backend.db.models.concept import ConceptEdge

    ids = [uuid.UUID(row.edge_id) for row in plan.stale]
    stmt = (
        delete(ConceptEdge)
        .where(ConceptEdge.edge_id.in_(ids))
        .where(ConceptEdge.edge_type == EdgeType.PREREQUISITE)
        .where(ConceptEdge.cms_edited_at.is_(None))
        .returning(ConceptEdge.edge_id)
    )
    deleted = len(conn.execute(stmt).all())
    if deleted != len(ids):
        raise StaleEdgeRetireError(
            f"잔존 엣지 은퇴 건수 불일치 — 계획 {len(ids)}건 · 실제 삭제 {deleted}건 "
            "(동시 편집 또는 CMS 표지 변경 가능성). 트랜잭션을 롤백한다"
        )
    return deleted


class AtomBackendEdgeStore:
    """원자 백본 선수엣지 → backend `concept_edge` 적재기 — UNIQUE 충돌 멱등 upsert(sync).

    `BackendEdgeStore`(구 개념그래프)의 원자 짝이다. `populate`는 먼저 backend `concept` 전량을
    단일 조회해 `{code: uuid}` 맵을 만들고(N+1 0), 각 레코드의 양끝 code를 UUID로 해석한 뒤
    `INSERT ... ON CONFLICT(from, to, edge_type) DO UPDATE`로 멱등 적재한다 — 재적재는
    edge_strength·relation_subtype만 갱신하고 **edge_id(PK)·created_at은 보존**한다. 양끝 중
    하나라도 맵에 없으면(orphan) 건너뛴다(FK 위반 방지). sync 엔진은 슬3 `_build_sync_engine`
    재사용(신규 seam 0).
    """

    def __init__(
        self,
        *,
        engine: Engine | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._engine = engine
        self._settings = settings
        # KG-14 — 직전 `populate`의 잔존 엣지 은퇴 결과(범위 미지정 호출이면 None)
        self.last_retire: RetireOutcome | None = None

    @property
    def _resolved_settings(self) -> Settings:
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_engine(self) -> Engine:
        if self._engine is None:
            self._engine = _build_sync_engine(self._resolved_settings)
        return self._engine

    def _load_code_to_uuid(self) -> dict[str, uuid.UUID]:
        """backend `concept` 전량을 단일 조회해 `{code: concept_id(UUID)}` 맵 구축(N+1 0)."""
        from sqlalchemy import select

        from whymath_backend.db.models.concept import Concept

        stmt = select(Concept.code, Concept.concept_id)
        with self._get_engine().connect() as conn:
            rows = conn.execute(stmt).all()
        return {row.code: row.concept_id for row in rows}

    def read_edge_rows_read_only(self) -> list[DbEdgeRow]:
        """KG-14 plan 모드 — DB `concept_edge`를 한 번 읽는다.

        **읽기 전용 트랜잭션**이라 실수로라도 쓰기가 일어나지 않고, 끝나면 롤백한다.
        """
        from sqlalchemy import text

        with self._get_engine().connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            rows = read_db_edge_rows(conn)
            conn.rollback()
        return rows

    def populate(
        self,
        records: Sequence[AtomBackendEdgeRecord],
        *,
        overwrite_cms_edits: bool = False,
        conflicts: list[str] | None = None,
        retire_mode: str = RETIRE_REPORT,
        retire_scope: frozenset[str] | None = None,
    ) -> tuple[int, list[str]]:
        """선수엣지 레코드들을 backend `concept_edge`에 멱등 upsert (orphan skip·식별자 보존).

        ① code→UUID 맵 단일 구축 → ② 양끝 해석(orphan skip) → ③ **선수 그래프 잠금 + DB 인지 순환
        검사**
        (P3-26 — DB에 있는 CMS 관계와 합쳐 순환이면 `PrerequisiteCycleError`, 쓰기 전에 거부)
        → ④ `ON CONFLICT(from,to,type) DO UPDATE`로 edge_strength·relation_subtype 갱신.
        반환: (적재 행 수, orphan skip 목록). `edge_type`은 enum 값(문자열)으로 바인딩한다.

        **CMS 소유 보호(P3-26)**: CMS가 만든 관계(`cms_edited_at` 있음)와 같은 쌍인 레코드는
        건너뛰고
        `conflicts`에 `concept_edge:<선수>-><후행>`으로 보고한다 — 적재 행 수에는 포함하지 않는다.

        **잔존 엣지 은퇴(KG-14)**: `retire_scope`(원자 백본 정본의 개념 코드 집합)를 주면 잠금
        직후 DB 엣지를 읽어 은퇴 계획을 세운다(범위의 정본은 `atom_edge_retire` 모듈 설명).
        `retire_mode`가 `apply`면 **같은 트랜잭션에서** 잔존 행을 지운 뒤 순환 검사·upsert를
        한다 — 순환 검사가 실패하면 삭제도 함께 롤백된다. `report`(기본)는 계산만 해
        `last_retire`에 싣는다.
        `retire_scope`가 None이면 은퇴 단계를 통째로 건너뛴다(종전 호출 무변경).
        """
        validate_mode(retire_mode)
        if retire_mode == RETIRE_PLAN:
            raise ValueError(
                "plan 모드는 쓰기 경로가 아니다 — populate.plan_atom_edge_retirement 사용"
            )
        self.last_retire = None
        if not records:
            return 0, []

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from whymath_backend.db.cms_edit_marker import format_conflict, upsert_guard, upsert_skipped
        from whymath_backend.db.models.concept import ConceptEdge
        from whymath_backend.l1.concept_graph.prerequisite_guard import (
            assert_acyclic_with_db,
            lock_prerequisite_graph_sync,
        )

        code_to_uuid = self._load_code_to_uuid()
        uuid_to_code = {v: k for k, v in code_to_uuid.items()}
        loaded = 0
        skipped: list[str] = []
        resolved: list[tuple[AtomBackendEdgeRecord, uuid.UUID, uuid.UUID]] = []
        for record in records:
            from_uuid = code_to_uuid.get(record.from_code)
            to_uuid = code_to_uuid.get(record.to_code)
            if from_uuid is None or to_uuid is None:
                skipped.append(
                    f"orphan edge skip: from={record.from_code}"
                    f"({'있음' if from_uuid else '없음'}) → "
                    f"to={record.to_code}({'있음' if to_uuid else '없음'})"
                )
                continue
            resolved.append((record, from_uuid, to_uuid))
        if not resolved:
            return 0, skipped  # 쓸 것이 없으면 잠금·순환 검사도 필요 없다
        where, release = upsert_guard(ConceptEdge, overwrite=overwrite_cms_edits)
        with self._get_engine().begin() as conn:
            lock_prerequisite_graph_sync(conn)
            if retire_scope is not None:
                plan = plan_retirement(
                    read_db_edge_rows(conn),
                    {(r.from_code, r.to_code) for r, _f, _t in resolved},
                    retire_scope,
                )
                retired = delete_stale_edges(conn, plan) if retire_mode == RETIRE_APPLY else 0
                self.last_retire = summarize(plan, retire_mode, retired)
            # 은퇴(apply) 뒤의 DB를 읽는다 — 삭제가 같은 트랜잭션이라 여기서 보인다
            assert_acyclic_with_db(conn, [(f, t) for _r, f, t in resolved], uuid_to_code)
            for record, from_uuid, to_uuid in resolved:
                stmt = pg_insert(ConceptEdge).values(
                    from_concept_id=from_uuid,
                    to_concept_id=to_uuid,
                    edge_type=record.edge_type.value,
                    edge_strength=record.edge_strength,
                    relation_subtype=record.relation_subtype,
                )
                upsert = stmt.on_conflict_do_update(
                    index_elements=[
                        ConceptEdge.from_concept_id,
                        ConceptEdge.to_concept_id,
                        ConceptEdge.edge_type,
                    ],
                    set_={
                        "edge_strength": stmt.excluded.edge_strength,
                        "relation_subtype": stmt.excluded.relation_subtype,
                        **release,
                    },
                    where=where,
                ).returning(ConceptEdge.edge_id)
                if upsert_skipped(conn.execute(upsert)):
                    if conflicts is not None:
                        conflicts.append(
                            format_conflict("concept_edge", f"{record.from_code}->{record.to_code}")
                        )
                    continue
                loaded += 1
        return loaded, skipped


def populate_atom_edges(
    records: Sequence[AtomBackendEdgeRecord],
    *,
    engine: Engine | None = None,
    settings: Settings | None = None,
    store: AtomBackendEdgeStore | None = None,
    overwrite_cms_edits: bool = False,
    conflicts: list[str] | None = None,
    retire_mode: str = RETIRE_REPORT,
    retire_scope: frozenset[str] | None = None,
) -> int:
    """원자 백본 선수엣지를 backend `concept_edge`로 멱등 적재. 반환=적재 행 수(orphan은 제외).

    store 미주입 시 슬3 sync 엔진 재사용 store를 만든다. 멱등(재실행 시 강도·subtype 갱신·
    edge_id 보존).
    """
    resolved = settings if settings is not None else get_settings()
    edge_store = (
        store if store is not None else AtomBackendEdgeStore(engine=engine, settings=resolved)
    )
    loaded, _skipped = edge_store.populate(
        records,
        overwrite_cms_edits=overwrite_cms_edits,
        conflicts=conflicts,
        retire_mode=retire_mode,
        retire_scope=retire_scope,
    )
    return loaded


__all__ = [
    "AtomBackendEdgeRecord",
    "AtomBackendEdgeStore",
    "delete_stale_edges",
    "load_atom_edges_from_graph_json",
    "populate_atom_edges",
    "read_db_edge_rows",
]
