"""[LEGACY_SNAPSHOT · non_runtime · audit_only] 구 437 격하(S0-4b).

런타임 truth source는 원자 백본(atom_graph_v1). 이 모듈은 audit·빌드타임 provenance이며 런타임
호출자 0(api·l2·l3·l4 구 437 reader 0). 물리 삭제 0·형식 격하만(S0-4b).

개념그래프 선수엣지 → backend `concept_edge` ORM 적재 — 선수 관계 적재기(소비 아크 선수 슬1).

`backend_concept.py`(개념 *노드* 적재)의 *엣지* 짝이다. 브리지 슬1이 graph.json 개념을 backend
`concept`(UUID PK·`code`=UC)로 적재해 런타임 노드 평면을 채웠으나, **개념 *관계*(`concept_edge`
테이블)는 비어 있다** — 마이그레이션은 테이블·UNIQUE를 만들어 뒀지만 *적재기가 없었다*. 이 모듈이
그 적재기를 놓아, graph.json `payload["edges"]`의 *선수(prerequisite) 관계*를 backend
`concept_edge`로 멱등 적재한다. 그러면 L2 선수 추천(소비처)이 "약개념의 막힌 선수개념"을
*concept_edge traversal*로 찾을 수 있다(backend `Concept`에 선수 캐시 컬럼이 없어 concept_edge가
유일 경로).

────────────────────────────────────────────────────────────────────────────
방향 (src=선수 → dst=후행 · backend from=to의 선수)
────────────────────────────────────────────────────────────────────────────
graph.json 엣지: `src_concept_id`(UC·**선수**) → `dst_concept_id`(UC·**후행**) — "src를 알아야
dst를 안다". backend `ConceptEdge`도 같은 규약 — `from_concept_id`는 `to_concept_id`의 *선수*
(`EdgeType.PREREQUISITE` docstring: "선수 — A를 알아야 B를 안다(A→B)"). 따라서 매핑은 일치한다:
**src→from_concept_id · dst→to_concept_id**. 후행 개념의 선수를 찾으려면 `to_concept_id ==
후행`인 행의 `from_concept_id`를 보면 된다(소비처 L2가 이 방향에 의존).

────────────────────────────────────────────────────────────────────────────
범위 (이번 슬라이스는 선수만 · 그 외 relation skip)
────────────────────────────────────────────────────────────────────────────
graph.json `relation`은 현재 전량 `"prerequisite"`이나, 모델은 6관계 enum이다. 이 적재기는
`relation == "prerequisite"`인 엣지만 `EdgeType.PREREQUISITE`로 적재하고, *그 외 relation은
건너뛴다*(skip 메시지 수집). 선수 추천이 이번 소비 슬라이스의 목표이므로 선수 관계만 적재한다
(다른 관계 적재는 후속 — 억지 매핑·미사용 적재 0).

────────────────────────────────────────────────────────────────────────────
최소 적재 (evidence·notes·typical_gap_signal NULL 유지 — 날조 회피)
────────────────────────────────────────────────────────────────────────────
backend `ConceptEdge`의 `typical_gap_signal`·`notes`는 NULL로 남긴다. graph.json `evidence`는
*관계 판단 근거*(전문가 작성 산문)이지 `typical_gap_signal`(선수 미충족 시 나타나는 *진단 신호*)
의미가 아니므로, evidence를 gap_signal에 *욱여넣지 않는다*(의미 부정합·날조 회피). `edge_strength`
만 graph `strength`(0~1)에서 적재한다(의미 일치 — 관계 강도). 본문성 필드는 적재 레코드에
*슬롯 자체가 없다*(구조적 차단).

────────────────────────────────────────────────────────────────────────────
code→UUID 해석 (N+1 0 · orphan skip)
────────────────────────────────────────────────────────────────────────────
graph.json 엣지는 UC(src_code·dst_code)로 양끝을 가리키나 backend `concept_edge`는 UUID FK
(from_concept_id·to_concept_id)를 쓴다. 적재 전에 backend `concept` 전량을 *단일 조회*
(`SELECT concept_id, code`)로 `{code: uuid}` 맵을 만들어 변환한다(N+1 0). 노드가 먼저 적재돼야
이 맵이 채워지므로 populate ④(엣지)는 ③(노드) 다음에 온다. 양끝 중 하나라도 맵에 없으면(orphan —
노드 미적재 UC) 그 엣지는 건너뛴다(FK 위반 방지·정직).

────────────────────────────────────────────────────────────────────────────
멱등 (UNIQUE(from,to,type) 충돌 upsert · edge_id 보존)
────────────────────────────────────────────────────────────────────────────
복합 UNIQUE `(from_concept_id, to_concept_id, edge_type)`로 `INSERT ... ON CONFLICT DO UPDATE`
멱등 적재한다 — 같은 (선수,후행,선수관계) 재적재는 `edge_strength`만 갱신하고 **edge_id(PK)·
created_at은 SET하지 않아 보존**한다(재적재가 엣지 식별자를 바꾸지 않음). self-edge(src==dst)는
`_no_self_edge` 불변 위반이므로 로딩 단계에서 skip한다(적재 전 차단).

sync 엔진은 슬3 `_build_sync_engine`을 재사용한다(신규 seam 0 — backend_concept·node_projection과
동일 좌석 규약). 자격증명은 env(`Settings.sync_database_url`)·하드코딩 0.

7계층: L1 데이터 기반의 *런타임 관계 적재*. 소비(L2 선수 추천)는 이 행을 *조회*하되 여기서
구현하지 않는다(역방향 의존 금지·후속).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from whymath_backend.config import Settings, get_settings

# 슬3 sync 엔진 빌더 재사용(신규 seam 0) — backend_concept·node_projection과 동일 규약.
from whymath_backend.l1.concept_graph.embedding import _build_sync_engine
from whymath_backend.schema.enums import EdgeType

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.engine import Engine


# graph.json `relation`(use_enum_values 직렬화) 중 이 슬라이스가 적재하는 값 — 선수만.
# data-pipeline `Relation.PREREQUISITE.value`("prerequisite")와 동일 문자열.
_PREREQUISITE_RELATION: str = "prerequisite"


def _opt_str(value: object) -> str | None:
    """빈 문자열·None → None, 그 외 strip한 str(backend_concept `_opt_str` 미러)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_float(value: object) -> float | None:
    """관계 강도 옵션 파싱 — 빈/None/비수치는 None(strength 미기재 엣지 graceful)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True, slots=True)
class BackendConceptEdgeRecord:
    """backend `concept_edge` 행으로 적재할 한 *선수 관계*의 최소 값 — UC 양끝 + 강도.

    `graph.json` 엣지(`ConceptEdge.model_dump()`)에서 backend 런타임 관계에 필요한 최소만 추린
    값이다. **`typical_gap_signal`·`notes`·`evidence` 슬롯이 *없다*** — evidence는 gap_signal
    의미가 아니고(부정합·날조 회피) 본문성이라 적재기가 채우지 않으므로 레코드에도 두지 않는다
    (구조적 차단·NULL 유지). `src_code`(선수 UC)·`dst_code`(후행 UC)는 적재 시 code→UUID로
    해석되어 `from_concept_id`·`to_concept_id`가 된다(방향 일치 — from은 to의 선수).
    """

    src_code: str  # = UC(선수·src_concept_id) → from_concept_id
    dst_code: str  # = UC(후행·dst_concept_id) → to_concept_id
    edge_type: EdgeType  # 이번 범위는 PREREQUISITE 고정(그 외 relation은 로딩에서 skip)
    edge_strength: float | None  # graph `strength`(0~1)·미기재 None


def load_backend_edges_from_graph_json(
    path: Path,
) -> tuple[list[BackendConceptEdgeRecord], list[str]]:
    """슬1 산출 `graph.json` → backend `concept_edge` 선수 적재 레코드 + skip 메시지 목록.

    `payload["edges"]`의 각 항목에서 `relation == "prerequisite"`인 엣지만 `EdgeType.PREREQUISITE`
    로 매핑한다 — `src_concept_id`→src_code(선수)·`dst_concept_id`→dst_code(후행)·`strength`→
    edge_strength. **그 외 relation은 건너뛴다**(이번 범위는 선수만·skip 메시지 수집). self-edge
    (src==dst)는 `_no_self_edge` 불변 위반이므로 건너뛴다(적재 전 차단). 양끝 UC가 비면(오염 입력)
    건너뛴다(NULL FK 방지). **`evidence`는 읽지 않는다**(레코드에 슬롯 부재·gap_signal 의미 아님).

    반환: (적재 레코드 목록, skip 사유 메시지 목록). 메시지는 운영 가시성용(조용한 누락 금지).

    Raises:
        FileNotFoundError: graph.json 부재.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: list[BackendConceptEdgeRecord] = []
    skipped: list[str] = []
    for record in payload.get("edges", []):
        relation = _opt_str(record.get("relation"))
        src_code = _opt_str(record.get("src_concept_id"))
        dst_code = _opt_str(record.get("dst_concept_id"))

        if relation != _PREREQUISITE_RELATION:
            # 이번 범위는 선수만 — 그 외 관계(구성·유사·확장·대조)는 후속 슬라이스.
            skipped.append(f"비-선수 관계 skip: relation={relation!r} ({src_code}→{dst_code})")
            continue
        if src_code is None or dst_code is None:
            skipped.append(f"양끝 UC 누락 skip: src={src_code!r} dst={dst_code!r}")
            continue
        if src_code == dst_code:
            # self-edge 금지(_no_self_edge 불변) — 적재 전 차단.
            skipped.append(f"self-edge skip: {src_code}")
            continue

        out.append(
            BackendConceptEdgeRecord(
                src_code=src_code,
                dst_code=dst_code,
                edge_type=EdgeType.PREREQUISITE,
                edge_strength=_opt_float(record.get("strength")),
            )
        )
    return out, skipped


class BackendEdgeStore:
    """개념그래프 선수엣지 → backend `concept_edge` 적재기 — UNIQUE 충돌 멱등 upsert(sync).

    `BackendConceptStore`(노드)의 *엣지* 짝이다(같은 sync 좌석·멱등 규약). `populate`는 먼저
    backend `concept` 전량을 단일 조회해 `{code: uuid}` 맵을 만들고(N+1 0), 각 레코드의 UC 양끝을
    UUID로 해석한 뒤 `INSERT ... ON CONFLICT(from_concept_id, to_concept_id, edge_type) DO UPDATE`
    로 멱등 적재한다 — 같은 (선수,후행,선수관계) 재적재는 `edge_strength`만 갱신하고 **edge_id(PK)·
    created_at은 SET하지 않아 보존**한다(재적재가 엣지 식별자를 바꾸지 않음 — 결정적). 양끝 중
    하나라도 맵에 없으면(orphan·노드 미적재) 그 엣지는 건너뛴다(FK 위반 방지). sync 엔진은
    슬3 `_build_sync_engine`을 재사용해 지연 생성·캐시한다(신규 seam 0).

    최소 적재: INSERT 컬럼은 (from_concept_id·to_concept_id·edge_type·edge_strength)뿐이다 —
    `typical_gap_signal`·`notes`는 레코드에 슬롯이 없어 구조적으로 NULL(evidence를 gap_signal에
    욱여넣지 않음·날조 회피).
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
        """설정 지연 해석 — 주입 우선, 없으면 캐시된 전역 Settings(backend_concept 패턴)."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_engine(self) -> Engine:
        """sync 엔진 지연 해석 — 주입 우선, 없으면 슬3 빌더로 생성·캐시(신규 seam 0)."""
        if self._engine is None:
            self._engine = _build_sync_engine(self._resolved_settings)
        return self._engine

    def _load_code_to_uuid(self) -> dict[str, uuid.UUID]:
        """backend `concept` 전량을 단일 조회해 `{code(UC): concept_id(UUID)}` 맵 구축(N+1 0).

        엣지 양끝 UC를 UUID FK로 해석하는 데 쓴다. 노드가 먼저 적재돼야(populate ③) 이 맵이
        채워지므로, 엣지 적재(④)는 노드 적재 다음에 와야 한다.
        """
        from sqlalchemy import select

        from whymath_backend.db.models.concept import Concept

        stmt = select(Concept.code, Concept.concept_id)
        with self._get_engine().connect() as conn:
            rows = conn.execute(stmt).all()
        return {row.code: row.concept_id for row in rows}

    def populate(
        self,
        records: Sequence[BackendConceptEdgeRecord],
        *,
        overwrite_cms_edits: bool = False,
        conflicts: list[str] | None = None,
    ) -> tuple[int, list[str]]:
        """선수엣지 레코드들을 backend `concept_edge`에 멱등 upsert (orphan skip·UUID 보존).

        ① code→UUID 맵 단일 구축 → ② 각 레코드의 src_code/dst_code를 UUID로 해석(하나라도 맵에
        없으면 orphan skip) → ③ **선수 그래프 잠금 + DB 인지 순환 검사**(P3-26 — DB의 CMS 관계와
        합쳐
        순환이면 `PrerequisiteCycleError`) → ④ `ON CONFLICT(from,to,type) DO UPDATE`로
        edge_strength만
        갱신(edge_id·created_at 미-SET·보존). 반환: (적재 행 수, orphan skip 메시지 목록). 입력이
        비면 (0, []). `edge_type`은 enum 값(문자열)으로 바인딩한다(PG enum 컬럼·use_enum_values
        등가).

        **CMS 소유 보호(P3-26)**: CMS가 만든 관계(`cms_edited_at` 있음)와 같은 쌍인 레코드는
        건너뛰고
        `conflicts`에 `concept_edge:<선수>-><후행>`으로 보고한다 — 적재 행 수에는 포함하지 않는다.
        """
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
        resolved: list[tuple[BackendConceptEdgeRecord, uuid.UUID, uuid.UUID]] = []
        for record in records:
            from_uuid = code_to_uuid.get(record.src_code)
            to_uuid = code_to_uuid.get(record.dst_code)
            if from_uuid is None or to_uuid is None:
                # orphan — 노드 미적재 UC(FK 위반 방지·정직).
                skipped.append(
                    f"orphan edge skip: src={record.src_code}"
                    f"({'있음' if from_uuid else '없음'}) → "
                    f"dst={record.dst_code}({'있음' if to_uuid else '없음'})"
                )
                continue
            resolved.append((record, from_uuid, to_uuid))
        if not resolved:
            return 0, skipped  # 쓸 것이 없으면 잠금·순환 검사도 필요 없다
        where, release = upsert_guard(ConceptEdge, overwrite=overwrite_cms_edits)
        with self._get_engine().begin() as conn:
            lock_prerequisite_graph_sync(conn)
            assert_acyclic_with_db(conn, [(f, t) for _r, f, t in resolved], uuid_to_code)
            for record, from_uuid, to_uuid in resolved:
                stmt = pg_insert(ConceptEdge).values(
                    from_concept_id=from_uuid,
                    to_concept_id=to_uuid,
                    edge_type=record.edge_type.value,
                    edge_strength=record.edge_strength,
                )
                # UNIQUE(from,to,type) 충돌 시 강도만 갱신 — edge_id(PK)·created_at은 SET 안 함
                # (보존·재적재가 식별자 불변). typical_gap_signal·notes는 컬럼 미수록(NULL).
                upsert = stmt.on_conflict_do_update(
                    index_elements=[
                        ConceptEdge.from_concept_id,
                        ConceptEdge.to_concept_id,
                        ConceptEdge.edge_type,
                    ],
                    set_={"edge_strength": stmt.excluded.edge_strength, **release},
                    where=where,
                ).returning(ConceptEdge.edge_id)
                if upsert_skipped(conn.execute(upsert)):
                    if conflicts is not None:
                        conflicts.append(
                            format_conflict("concept_edge", f"{record.src_code}->{record.dst_code}")
                        )
                    continue
                loaded += 1
        return loaded, skipped


def populate_backend_edges(
    records: Sequence[BackendConceptEdgeRecord],
    *,
    engine: Engine | None = None,
    settings: Settings | None = None,
    store: BackendEdgeStore | None = None,
    overwrite_cms_edits: bool = False,
    conflicts: list[str] | None = None,
) -> int:
    """개념그래프 선수엣지를 backend `concept_edge` 런타임 관계로 멱등 upsert 적재. 반환=적재 행 수.

    `populate_backend_concepts`(노드)의 *엣지* 짝이다 — 각 레코드를 UC 양끝→UUID 해석 후
    `ON CONFLICT(from,to,type)` 멱등 적재한다(orphan은 건너뜀). 멱등(재실행 시 강도 갱신·edge_id
    보존). store 미주입 시 슬3 sync 엔진 재사용 `BackendEdgeStore`를 만든다(engine 주입도 가능).
    orphan skip 수는 (적재 행 수 ≤ 레코드 수)로 드러난다.
    """
    resolved = settings if settings is not None else get_settings()
    edge_store = store if store is not None else BackendEdgeStore(engine=engine, settings=resolved)
    loaded, _skipped = edge_store.populate(
        records, overwrite_cms_edits=overwrite_cms_edits, conflicts=conflicts
    )
    return loaded


__all__ = [
    "BackendConceptEdgeRecord",
    "BackendEdgeStore",
    "load_backend_edges_from_graph_json",
    "populate_backend_edges",
]
