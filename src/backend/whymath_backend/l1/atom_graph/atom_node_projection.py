"""원자 메타 PG 프로젝션 적재 — `atom_node` 테이블 code 키 멱등 upsert (원자 Phase 2a).

`l1/concept_graph/node_projection.py`(개념 메타 UC 키 프로젝션 적재)의 *원자 백본* 짝이다.
Phase 1 산출 코퍼스 `data/corpus/atom_graph_v1/graph.json`(세부개념 1,823 + 단원 217 +
소단원 643 = 2,683 노드 — 2026-09-14 실측. 이전 표기 '원자 1,837…2,697'은 낡은 값이었다)의
원자 *안전 메타*를 `atom_node`(PG) 테이블에 멱등 upsert한다. Phase 1 적재기
(`atom_backend_concept.py`)가 backend `concept`에 *런타임 최소 식별*만 적재했다면, 이 모듈은
풍부 원자 메타(인지축·노드유형·학교급·전이·원자성·연결성취기준)를 code 키로 투영한다 — 검색
enrichment·필터·게이팅을 PG 조인으로 하기 위한 *적재* 좌석이다(조회·조인은 후속).

차이(`node_projection.py` 대비):
  - **키가 code**(graph.json `code`·원자ID/소단원코드/단원코드) — UC 아님(`concept.code` 동일 공간).
  - **풍부 메타 수용**: 인지축·노드유형·학교급·subject_area·subunit_code·transfer·atomicity 등.
  - **review_status는 상수 'ai_estimated'**: 원자 메타는 안내 시트상 AI 추정이라 graph.json에서
    읽지 않고 코드 상수로 박는다(정직 표기·검수 게이팅용).
  - **전 노드 적재**(name 빈 노드만 skip): 단원/소단원/세부개념 전량(검색·필터 recall).

────────────────────────────────────────────────────────────────────────────
redaction (CLAUDE.md 우선순위 #2 — 협상 불가·구조적 차단)
────────────────────────────────────────────────────────────────────────────
적재 필드는 **안전 메타만** — name_ko·level·parent_code·school_level·subject_area·subunit_code·
cognitive_type·node_type·misconception_type·intrinsic_difficulty·standard_codes·transfer·
transfer_example·atomicity. **`core_proposition`·`description`·`formal_definition`은 읽지도
적재하지도 않는다**(성취기준 본문 근접 필드·ORM 컬럼 부재·레코드 슬롯 부재의 이중 방어).

**4요소 콘텐츠(①misconception·②diagnostic_item/answer/signal·③socratic)도 읽지/적재하지 않는다**
— Phase 3에서 `misconception_catalog`/`problem`로 *정식 콘텐츠 소스 승격* 대상이라(로드맵 Phase 3),
메타 프로젝션이 선점·이중 보관하면 안 된다. 4요소 중 ④`transfer`·`atomicity`만 concept-level
안전 메타라 포함한다. `AtomNodeRecord` dataclass에 본문/④요소(misconception/diagnostic/socratic)
슬롯을 *두지 않아* 구조적으로 차단하고, upsert SQL에도 미등장한다(테스트로 단언).

────────────────────────────────────────────────────────────────────────────
sync 엔진 재사용 (신규 seam 0)
────────────────────────────────────────────────────────────────────────────
슬3 `embedding._build_sync_engine`(sync psycopg·지연 import·`db_disable_pool` NullPool 가드)을
*그대로 재사용*한다 — `node_projection`·`atom_backend_concept`와 동일 sync 좌석 규약(신규 엔진
빌더 0·CLAUDE.md 로컬 우선). sync URL은 `Settings.sync_database_url`(env 파생)·자격증명 하드코딩 0.

7계층: L1 데이터 기반의 *영속 프로젝션 적재*. 검색 조회·소비(L2/L4)는 후속(역방향 의존 금지).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.atom_node import ATOM_REVIEW_STATUS_AI_ESTIMATED

# 슬3 sync 엔진 빌더 재사용(신규 seam 0) — node_projection·atom_backend_concept과 동일 규약.
from whymath_backend.l1.concept_graph.embedding import _build_sync_engine

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


@dataclass(frozen=True, slots=True)
class AtomNodeMeta:
    """원자 검색 enrichment용 *안전* 메타 한 묶음 — `atom_node` 조회 결과.

    `concept_node`의 `ConceptNodeMeta`(name_ko·domain·review_status)의 *원자 백본* 짝이다.
    `search_atoms`가 code 키로 이 메타를 붙여 `AtomSearchHit`를 풍부하게 한다(name_ko·subject_area
    표시·review_status 게이팅). concept의 `domain` 자리에 원자는 `subject_area`(nullable)를
    둔다 — 의미는 대응하나 원자 subject_area는 단원/소단원/일부 원자에서 비어 있을 수 있어 `None`을
    허용한다(`atom_node.subject_area` 컬럼이 nullable). **본문 필드(core_proposition·description·
    formal_definition)는 없다** — `atom_node`에 컬럼 자체가 없으므로 구조적으로 흐를 수 없다
    (redaction). 검색 결과에 실리는 안전 표시·게이팅 메타만 담는다.
    """

    name_ko: str
    subject_area: str | None
    review_status: str


def _opt_str(value: object) -> str | None:
    """빈 문자열·None → None, 그 외 strip한 str(node_projection `_opt_str` 미러)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_int(value: object) -> int | None:
    """정수 옵션 파싱 — 빈/None/비정수는 None(node_projection `_opt_int` 미러). 검증은 ORM/DB."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True, slots=True)
class AtomNodeRecord:
    """프로젝션 대상 한 원자 노드의 *안전 메타* — code + 표시·필터·게이팅 필드.

    `graph.json`의 한 concept(원자/단원/소단원)에서 안전 키만 추린 값이다. **`core_proposition`·
    `description`·`formal_definition`(본문)·4요소(`misconception`/`diagnostic_*`/`socratic`)는
    슬롯 자체가 없다**(redaction·구조적 차단 — 본문/검수 책임·Phase 3 승격 대상). 적재기가 이
    레코드를 code 키로 upsert한다. `review_status`는 슬롯이 없다 — 적재기가 상수로 박는다(AI 추정).
    """

    code: str
    name_ko: str
    level: str
    parent_code: str | None
    school_level: str | None
    subject_area: str | None
    subunit_code: str | None
    cognitive_type: str | None
    node_type: str | None
    misconception_type: str | None
    intrinsic_difficulty: int | None
    standard_codes: tuple[str, ...]
    transfer: str | None
    transfer_example: str | None
    atomicity: dict[str, object] | None


def load_atom_nodes_from_graph_json(path: Path) -> list[AtomNodeRecord]:
    """Phase 1 산출 `graph.json` → 원자 *안전 메타* 레코드 목록(code 키·redaction 청결).

    `concepts` 배열의 각 항목에서 **안전 키만** 읽어 `AtomNodeRecord`를 만든다 —
    `core_proposition`·`description`·`formal_definition`(본문)·4요소(`misconception`/
    `diagnostic_*`/`socratic`)는 읽지 않는다(레코드 슬롯 부재·구조적 차단). `node_projection`과
    같이 *빈 표현 제외를 하지 않는다*: 메타 프로젝션은 검색 enrichment·필터용이라 전
    노드(2,683·실측)를 적재해야 한다(name 빈 노드만 skip).

    `code`·`name`·`level`은 graph.json이 항상 보유한다(필수 필드). `name`이 빈/None이면
    *건너뛴다*(NOT NULL 위반 방지·정직·조용한 빈 적재 금지). `standard_codes`는 리스트가 아니면 빈
    튜플로, `atomicity`는 dict가 아니면 None으로 정규화한다.

    Raises:
        FileNotFoundError: graph.json 부재.
        ValueError: code 없는 항목(Phase 1 산출은 항상 code를 갖는다 — 방어).
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: list[AtomNodeRecord] = []
    for record in payload.get("concepts", []):
        code = _opt_str(record.get("code"))
        if code is None:
            raise ValueError(f"graph.json 노드에 code가 없습니다: {record!r}")

        name_ko = _opt_str(record.get("name"))
        level = _opt_str(record.get("level"))
        if name_ko is None or level is None:
            # 필수 표시·계층 필드 누락(오염 입력) — NOT NULL 위반 대신 건너뛴다(정직).
            # 정상 코퍼스는 name·level을 항상 보유하므로 실제 경로에선 발생하지 않는다.
            continue

        raw_codes = record.get("standard_codes")
        codes: tuple[str, ...] = (
            tuple(str(c) for c in raw_codes) if isinstance(raw_codes, (list, tuple)) else ()
        )
        raw_atomicity = record.get("atomicity")
        atomicity: dict[str, object] | None = (
            dict(raw_atomicity) if isinstance(raw_atomicity, dict) and raw_atomicity else None
        )
        out.append(
            AtomNodeRecord(
                code=code,
                name_ko=name_ko,
                level=level,
                parent_code=_opt_str(record.get("parent_code")),
                school_level=_opt_str(record.get("school_level")),
                subject_area=_opt_str(record.get("subject_area")),
                subunit_code=_opt_str(record.get("subunit_code")),
                cognitive_type=_opt_str(record.get("cognitive_type")),
                node_type=_opt_str(record.get("node_type")),
                misconception_type=_opt_str(record.get("misconception_type")),
                intrinsic_difficulty=_opt_int(record.get("intrinsic_difficulty")),
                standard_codes=codes,
                transfer=_opt_str(record.get("transfer")),
                transfer_example=_opt_str(record.get("transfer_example")),
                atomicity=atomicity,
            )
        )
    return out


class AtomNodeStore:
    """원자 메타 PG 프로젝션 적재기 — `atom_node` 테이블 code 키 멱등 upsert(sync).

    `ConceptNodeStore`(개념 메타 프로젝션)의 *원자 백본* 짝이다. `upsert`는 PK 충돌 upsert
    (`INSERT ... ON CONFLICT(code) DO UPDATE`)로 멱등 적재한다(같은 code 재적재 → 행 갱신·
    updated_at 갱신). `review_status`는 상수 'ai_estimated'로 박는다(원자 메타는 AI 추정·정직).
    sync 엔진은 슬3 `_build_sync_engine`을 재사용해 지연 생성·캐시한다(신규 seam 0). 벡터 컬럼이
    없어 검색 메서드는 두지 않는다 — *적재 전용* 좌석이다(조회·조인은 후속).
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
        """설정 지연 해석 — 주입 우선, 없으면 캐시된 전역 Settings(node_projection 패턴)."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_engine(self) -> Engine:
        """sync 엔진 지연 해석 — 주입 우선, 없으면 슬3 빌더로 생성·캐시(신규 seam 0)."""
        if self._engine is None:
            self._engine = _build_sync_engine(self._resolved_settings)
        return self._engine

    def upsert(self, record: AtomNodeRecord) -> None:
        """단일 원자 메타 upsert (멱등·code PK 충돌 갱신).

        `INSERT ... ON CONFLICT(code) DO UPDATE` — 안전 메타 전 필드 + review_status('ai_estimated'
        상수) + updated_at(now())을 갱신한다. **core_proposition·description·formal_definition·
        4요소(misconception/diagnostic/socratic)는 INSERT 컬럼에 없다**(redaction — 레코드에 슬롯이
        없어 구조적 차단). standard_codes는 리스트로 바인딩(PG TEXT[])·atomicity는 dict(PG JSONB).
        **`behavior_skills`는 여기서 건드리지 않는다**(INSERT·set_ 미등장 — 신규 행은 server_default
        '{}', 기존 행 값은 보존): 채움 좌석은 S0-2 크로스워크 전파(`l1/concept_atom_crosswalk/
        transfer.py`)이며, 메타 재적재가 전파 결과를 지우면 안 된다.
        """
        from sqlalchemy import func
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from whymath_backend.db.models.atom_node import AtomNode

        stmt = pg_insert(AtomNode).values(
            code=record.code,
            name_ko=record.name_ko,
            level=record.level,
            parent_code=record.parent_code,
            school_level=record.school_level,
            subject_area=record.subject_area,
            subunit_code=record.subunit_code,
            cognitive_type=record.cognitive_type,
            node_type=record.node_type,
            misconception_type=record.misconception_type,
            intrinsic_difficulty=record.intrinsic_difficulty,
            standard_codes=list(record.standard_codes),
            transfer=record.transfer,
            transfer_example=record.transfer_example,
            atomicity=record.atomicity,
            review_status=ATOM_REVIEW_STATUS_AI_ESTIMATED,
        )
        # PK 충돌 시 갱신 — updated_at은 now()로 새로 찍는다(server_default는 INSERT 전용).
        stmt = stmt.on_conflict_do_update(
            index_elements=[AtomNode.code],
            set_={
                "name_ko": stmt.excluded.name_ko,
                "level": stmt.excluded.level,
                "parent_code": stmt.excluded.parent_code,
                "school_level": stmt.excluded.school_level,
                "subject_area": stmt.excluded.subject_area,
                "subunit_code": stmt.excluded.subunit_code,
                "cognitive_type": stmt.excluded.cognitive_type,
                "node_type": stmt.excluded.node_type,
                "misconception_type": stmt.excluded.misconception_type,
                "intrinsic_difficulty": stmt.excluded.intrinsic_difficulty,
                "standard_codes": stmt.excluded.standard_codes,
                "transfer": stmt.excluded.transfer,
                "transfer_example": stmt.excluded.transfer_example,
                "atomicity": stmt.excluded.atomicity,
                "review_status": stmt.excluded.review_status,
                "updated_at": func.now(),
            },
        )
        with self._get_engine().begin() as conn:
            conn.execute(stmt)


def fetch_atom_node_meta(
    codes: Sequence[str],
    *,
    engine: Engine | None = None,
    settings: Settings | None = None,
) -> dict[str, AtomNodeMeta]:
    """code 키 목록 → `atom_node` 안전 메타 dict (원자 검색 enrichment용 단일 IN 조회·sync).

    `concept_graph/node_projection.fetch_node_meta`(UC 키 concept_node 조인)의 *원자 백본* 짝이다.
    `WHERE code = ANY(:codes)` 단일 쿼리로 표시·게이팅 *안전 필드*(name_ko·subject_area·
    review_status)만 SELECT한다 — **core_proposition·description·formal_definition은 컬럼이 없어
    조회 자체가 불가**(redaction·구조적 차단). `atom_node`에 없는 code(적재 누락)는 결과 dict에서
    빠진다 → 호출자가 None으로 graceful 처리(`search_atoms`). 입력이 비면 빈 dict(쿼리 생략).

    sync 엔진은 슬3 `_build_sync_engine`을 재사용한다(신규 seam 0·`fetch_node_meta` 동형) — 검색
    좌석이 이미 sync(블로킹)라 같은 엔진 평면에서 enrichment 조회가 일어난다(`search` 직후 같은
    워커 스레드). engine 주입 가능(테스트 격리·검색 좌석이 index가 든 같은 엔진을 넘김).
    """
    ids = [str(c) for c in codes]
    if not ids:
        return {}
    from sqlalchemy import select

    from whymath_backend.db.models.atom_node import AtomNode

    resolved = settings if settings is not None else get_settings()
    eng = engine if engine is not None else _build_sync_engine(resolved)
    stmt = select(
        AtomNode.code,
        AtomNode.name_ko,
        AtomNode.subject_area,
        AtomNode.review_status,
    ).where(AtomNode.code.in_(ids))
    with eng.connect() as conn:
        rows = conn.execute(stmt).all()
    return {
        row.code: AtomNodeMeta(
            name_ko=row.name_ko,
            subject_area=row.subject_area,
            review_status=row.review_status,
        )
        for row in rows
    }


def populate_atom_nodes(
    records: Sequence[AtomNodeRecord],
    *,
    settings: Settings | None = None,
    store: AtomNodeStore | None = None,
) -> int:
    """원자 안전 메타를 `atom_node`에 멱등 upsert 적재(영속 프로젝션). 반환=적재 행 수.

    `populate_concept_nodes`의 *원자 백본* 짝이다 — 임베딩 호출 없이(provider 불요) 각 레코드를
    code 키로 upsert한다(2,683 전량·review_status='ai_estimated'). 멱등(재실행 시 갱신). store
    미주입 시 슬3 sync 엔진 재사용 `AtomNodeStore`를 만든다.
    """
    resolved = settings if settings is not None else get_settings()
    node_store = store if store is not None else AtomNodeStore(settings=resolved)
    for record in records:
        node_store.upsert(record)
    return len(records)


__all__ = [
    "AtomNodeMeta",
    "AtomNodeRecord",
    "AtomNodeStore",
    "fetch_atom_node_meta",
    "load_atom_nodes_from_graph_json",
    "populate_atom_nodes",
]
