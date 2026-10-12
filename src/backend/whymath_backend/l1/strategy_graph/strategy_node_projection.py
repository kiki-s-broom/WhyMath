"""전략 메타 PG 프로젝션 적재 — `strategy_node` 테이블 strategy_id 키 멱등 upsert (P6a).

`l1/formula_graph/formula_node_projection.py`(수식 프로젝션)의 *전략* 짝이다. data 산출
`strategy_graph_v1/graph.json`(canonical 전략 노드)의 *안전 메타*를 `strategy_node`(PG)에 멱등
upsert한다 — 검색 enrichment·필터·(후속) 전략 참조 백킹.

차이(`formula_node_projection.py` 대비):
  - **키가 strategy_id**(graph.json `strategy_id`·`strategy.<slug>`) — 타 노드 공간과 분리.
  - **입력 배열이 `strategies`**(복수형 키).
  - **latex·dsl·canonical_signature·aliases 없음**: 전략은 수식이 아니라 공략 발상(cognitive
    action)이라 `description`(인지행동 기준 자체작성 설명)만 담는다. 엔진에 sympy 의존 없음.
  - **review_status는 상수**('ai_estimated'·v1 자체작성이나 전문 검수 전·정직 표기).

법적(CLAUDE.md 우선순위 #2): 전략 택소노미는 자체작성 heuristic 추상이라 redaction 무관. 적재
필드는 전부 안전 메타(어느 책 본문도 0·`description`은 인지행동 기준 자체 서술).

sync 엔진 재사용(신규 seam 0): 슬3 `embedding._build_sync_engine`을 그대로 재사용한다
(formula_node_projection·problem_type_node_projection과 동일 sync 좌석 규약·자격증명 하드코딩 0).

7계층: L1 데이터 기반의 *영속 프로젝션 적재*. 조회·소비(strategy 참조·resolution)는 후속(역방향
의존 금지).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from whymath_backend.config import Settings, get_settings
from whymath_backend.db.cms_edit_marker import format_conflict
from whymath_backend.db.models.strategy_node import STRATEGY_REVIEW_STATUS_DEFAULT

# 슬3 sync 엔진 빌더 재사용(신규 seam 0) — formula_node_projection과 동일 규약.
from whymath_backend.l1.concept_graph.embedding import _build_sync_engine

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


def _opt_str(value: object) -> str | None:
    """빈 문자열·None → None, 그 외 strip한 str(formula_node_projection `_opt_str` 미러)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True, slots=True)
class StrategyNodeRecord:
    """프로젝션 대상 한 canonical 전략 노드의 *안전 메타* — strategy_id + 표시·설명 필드.

    `graph.json`의 한 strategy에서 안전 키만 추린 값이다. 수식 슬롯(latex·dsl·signature·aliases)은
    없다(전략은 공략 발상이지 수식이 아님). 적재기가 이 레코드를 strategy_id 키로 upsert한다.
    `review_status`는 슬롯이 없다 — 적재기가 상수로 박는다(v1 자체작성·전문 검수 전).
    """

    strategy_id: str
    name_ko: str
    family: str
    description: str
    standard_codes: tuple[str, ...]


def load_strategies_from_graph_json(path: Path) -> list[StrategyNodeRecord]:
    """data-pipeline 산출 `graph.json` → 전략 *안전 메타* 레코드 목록(strategy_id 키).

    `strategies` 배열(복수형 키)의 각 항목에서 안전 키만 읽어 `StrategyNodeRecord`를 만든다.
    `strategy_id`·`name_ko`·`family`·`description`은 필수라 누락 시 건너뛴다(NOT NULL 위반 방지·
    조용한 적재 금지). 정상 코퍼스는 전 필드를 보유하므로 실경로에선 skip이 없다.

    Raises:
        FileNotFoundError: graph.json 부재.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: list[StrategyNodeRecord] = []
    for record in payload.get("strategies", []):
        strategy_id = _opt_str(record.get("strategy_id"))
        name_ko = _opt_str(record.get("name_ko"))
        family = _opt_str(record.get("family"))
        description = _opt_str(record.get("description"))
        if None in (strategy_id, name_ko, family, description):
            continue
        assert strategy_id is not None and name_ko is not None
        assert family is not None and description is not None

        raw_codes = record.get("standard_codes")
        codes: tuple[str, ...] = (
            tuple(str(c) for c in raw_codes) if isinstance(raw_codes, (list, tuple)) else ()
        )
        out.append(
            StrategyNodeRecord(
                strategy_id=strategy_id,
                name_ko=name_ko,
                family=family,
                description=description,
                standard_codes=codes,
            )
        )
    return out


class StrategyNodeStore:
    """전략 메타 PG 프로젝션 적재기 — `strategy_node` 키 멱등 upsert(sync).

    `FormulaNodeStore`(수식 메타 프로젝션)의 *전략 그래프* 짝이다. `upsert`는 PK 충돌 upsert
    (`INSERT ... ON CONFLICT(strategy_id) DO UPDATE`)로 멱등 적재한다(같은 id 재적재 → 행 갱신·
    updated_at 갱신). `review_status`는 상수('ai_estimated')로 박는다. sync 엔진은 슬3
    `_build_sync_engine`을 재사용해 지연 생성·캐시한다(신규 seam 0). *적재 전용* 좌석이다.
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
        """설정 지연 해석 — 주입 우선, 없으면 캐시된 전역 Settings(formula 프로젝션 패턴)."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_engine(self) -> Engine:
        """sync 엔진 지연 해석 — 주입 우선, 없으면 슬3 빌더로 생성·캐시(신규 seam 0)."""
        if self._engine is None:
            self._engine = _build_sync_engine(self._resolved_settings)
        return self._engine

    def upsert(self, record: StrategyNodeRecord, *, overwrite_cms_edits: bool = False) -> bool:
        """단일 전략 메타 upsert (멱등·strategy_id PK 충돌 갱신). 반환=적재했으면 True.

        `INSERT ... ON CONFLICT(strategy_id) DO UPDATE` — 안전 메타 전 필드 + review_status +
        updated_at(now())을 갱신한다. standard_codes는 리스트로 바인딩(PG TEXT[]). 수식·엣지 컬럼은
        없다(closed 택소노미·연결은 소비처 참조 키).

        **CMS 편집 보호(P3-25)**: `cms_edited_at`이 채워진 행은 갱신하지 않고 False를 돌려준다
        (`overwrite_cms_edits=True`면 덮어쓰고 표지를 비운다). 이름·설명은 CMS 편집 대상이다.
        """
        from sqlalchemy import func
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from whymath_backend.db.cms_edit_marker import upsert_guard, upsert_skipped
        from whymath_backend.db.models.strategy_node import StrategyNode

        stmt = pg_insert(StrategyNode).values(
            strategy_id=record.strategy_id,
            name_ko=record.name_ko,
            family=record.family,
            description=record.description,
            standard_codes=list(record.standard_codes),
            review_status=STRATEGY_REVIEW_STATUS_DEFAULT,
        )
        # PK 충돌 시 갱신 — updated_at은 now()로 새로 찍는다(server_default는 INSERT 전용).
        where, release = upsert_guard(StrategyNode, overwrite=overwrite_cms_edits)
        upsert = stmt.on_conflict_do_update(
            index_elements=[StrategyNode.strategy_id],
            set_={
                "name_ko": stmt.excluded.name_ko,
                "family": stmt.excluded.family,
                "description": stmt.excluded.description,
                "standard_codes": stmt.excluded.standard_codes,
                "review_status": stmt.excluded.review_status,
                "updated_at": func.now(),
                **release,
            },
            where=where,
        ).returning(StrategyNode.strategy_id)
        with self._get_engine().begin() as conn:
            return not upsert_skipped(conn.execute(upsert))


def populate_strategy_nodes(
    records: Sequence[StrategyNodeRecord],
    *,
    settings: Settings | None = None,
    store: StrategyNodeStore | None = None,
    overwrite_cms_edits: bool = False,
    conflicts: list[str] | None = None,
) -> int:
    """전략 안전 메타를 `strategy_node`에 멱등 upsert 적재(영속 프로젝션). 반환=적재 행 수.

    `populate_formula_nodes`의 *전략 그래프* 짝이다 — 각 레코드를 strategy_id 키로 upsert한다
    (전량·review_status='ai_estimated'). 멱등(재실행 시 갱신). store 미주입 시 슬3 sync 엔진 재사용
    `StrategyNodeStore`를 만든다.

    **CMS 편집 보호(P3-25)**: CMS가 고친 행(`cms_edited_at` 있음)은 건너뛰고 `conflicts`에
    `strategy_node:<id>`로 보고한다 — 반환 행 수에는 포함하지 않는다. `overwrite_cms_edits=True`면
    덮어쓰고 표지를 비운다.
    """
    resolved = settings if settings is not None else get_settings()
    node_store = store if store is not None else StrategyNodeStore(settings=resolved)
    written = 0
    for record in records:
        if node_store.upsert(record, overwrite_cms_edits=overwrite_cms_edits):
            written += 1
        elif conflicts is not None:
            conflicts.append(format_conflict("strategy_node", record.strategy_id))
    return written


__all__ = [
    "StrategyNodeRecord",
    "StrategyNodeStore",
    "load_strategies_from_graph_json",
    "populate_strategy_nodes",
]
