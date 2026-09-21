"""콘텐츠 4종 PG 프로젝션 적재 — `concept_content` 테이블 code 키 멱등 upsert (Phase 3 Slice 1).

`l1/atom_graph/atom_node_projection.py`(원자 안전 메타 code 키 프로젝션 적재)의 *콘텐츠* 짝이다.
Phase 3가 캡처한 콘텐츠 코퍼스(`concept_content_v1/content.json`·K-12 개념 437 +
`concept_content_university_v1/content.json`·대학 소단원 409)의 **콘텐츠 4종**(은유·오개념·정식정의·
허용표현)과 설명·암기카드를 `concept_content`(PG)에 멱등 upsert한다 — 학습 장면(L4/L5/L6)이 PG
조인으로 콘텐츠를 끌어쓰기 위한 *적재* 좌석(조회·조인은 후속).

차이(`atom_node_projection.py` 대비):
  - **키가 code**이되 의미가 다르다: K-12=구 437 개념코드(예 'N1'·'A1') / 대학=소단원코드
    (예 'CALC1-U1-S1'). 겹침 0이라 단일 PK·`scope`('K-12'|'대학')로 구분(loader 인자로 주입).
  - **콘텐츠 4종 + 암기카드 수용**: metaphor·misconception·formal_definition_internal·
    accepted_expressions·explanation·flashcards(JSONB list). 4종은 자체작성이고, `explanation`
    일부(K-12 133건)는 NCIC 성취기준 본문과 동일하다 — 교육부 고시라 저작권법 §7 비보호·공공누리
    제1유형이라 보유·노출 제약 없음(코퍼스 사이드카 `ncic_statement_overlap`).
  - **review_status는 코퍼스 record 값**: 콘텐츠는 AI 추정·검수필요라 코퍼스에서
    `review_status`를 읽고, 부재 시만 'ai_estimated'로 폴백한다(정직 표기·검수 게이팅용·
    승격 후 재적재 시 `reviewed` 보존).

────────────────────────────────────────────────────────────────────────────
법적·노출 (CLAUDE.md 우선순위 #2)
────────────────────────────────────────────────────────────────────────────
콘텐츠 4종·설명·암기카드는 전량 자체작성이라 보유 허용이다. K-12 성취기준 *본문*은 코퍼스에 *없고*
(연결 `standard_codes` 코드만 다리), 적재기도 코드만 읽는다. `formal_definition_internal`(정식정의)
은 자체작성이라 *저장*하되 **학생 비노출**(노출 게이팅은 소비계층 책임 — 이 좌석은 충실히 보관만).
`ConceptContentRecord`에 성취기준 본문 슬롯을 두지 않아 구조적으로 차단한다(atom_node 동형).

sync 엔진은 슬3 `_build_sync_engine`을 *그대로 재사용*한다(신규 seam 0·atom_node_projection 동형·
sync URL은 `Settings.sync_database_url` env 파생·자격증명 하드코딩 0).

7계층: L1 데이터 기반의 *영속 프로젝션 적재*. 콘텐츠 조회·소비(L4/L5/L6)는 후속(역방향 의존 금지).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import func

from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.concept_content import CONTENT_REVIEW_STATUS_AI_ESTIMATED

# 슬3 sync 엔진 빌더 재사용(신규 seam 0) — atom_node_projection·node_projection과 동일 규약.
from whymath_backend.l1.concept_graph.embedding import _build_sync_engine

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


def _opt_str(value: object) -> str | None:
    """빈 문자열·None → None, 그 외 strip한 str(atom_node_projection `_opt_str` 미러)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True, slots=True)
class ConceptContentRecord:
    """프로젝션 대상 한 개념(K-12)/소단원(대학)의 콘텐츠 4종 + 설명 + 암기카드 + 검수 상태.

    `content.json`의 한 content 항목에서 콘텐츠 키만 추린 값이다. **성취기준 *본문* 슬롯은 없다**
    (코퍼스에 본문 부재·standard_codes 코드만·구조적 차단). `formal_definition_internal`은 저장하되
    학생 비노출(노출은 소비계층 게이팅). `review_status`는 코퍼스 record 값을 그대로 읽어
    upsert한다(승격 후 재적재 시 `reviewed` 보존 — 부재 시 'ai_estimated' 기본).
    """

    code: str
    scope: str
    name: str
    subject: str
    unit: str | None
    metaphor: str | None
    misconception: str | None
    formal_definition_internal: str | None
    accepted_expressions: str | None
    explanation: str | None
    standard_codes: tuple[str, ...]
    flashcards: tuple[dict[str, object], ...]
    review_status: str


def load_concept_content_from_json(path: Path, *, scope: str) -> list[ConceptContentRecord]:
    """콘텐츠 코퍼스 `content.json` → 콘텐츠 4종 레코드 목록(code 키·scope 주입).

    `content` 배열의 각 항목에서 콘텐츠 키를 읽어 `ConceptContentRecord`를 만든다 — 성취기준 본문은
    코퍼스에 없고 슬롯도 없다(구조 차단). K-12·대학 코퍼스가 같은 레코드 형태라 한 로더가 처리하며,
    `scope`('K-12'|'대학')는 호출자가 주입한다(코퍼스 파일별 고정·corpus top-level `scope`와 일치).

    `code`·`name`·`subject`는 코퍼스가 항상 보유한다(필수). 빈/None이면 *건너뛴다*(NOT NULL 위반
    방지·정상 코퍼스에선 미발생). `standard_codes`는 리스트가 아니면 빈 튜플로(대학은 키 부재),
    `flashcards`는 dict 리스트만 보존(비-dict 항목 제외).

    Raises:
        FileNotFoundError: content.json 부재.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: list[ConceptContentRecord] = []
    for record in payload.get("content", []):
        code = _opt_str(record.get("code"))
        name = _opt_str(record.get("name"))
        subject = _opt_str(record.get("subject"))
        if code is None or name is None or subject is None:
            # 필수 식별·표시 필드 누락(오염 입력) — NOT NULL 위반 대신 건너뛴다(정직).
            # 정상 코퍼스는 code·name·subject를 항상 보유하므로 실제 경로에선 발생하지 않는다.
            continue

        raw_codes = record.get("standard_codes")
        codes: tuple[str, ...] = (
            tuple(str(c) for c in raw_codes) if isinstance(raw_codes, (list, tuple)) else ()
        )
        raw_cards = record.get("flashcards")
        cards: tuple[dict[str, object], ...] = (
            tuple(dict(c) for c in raw_cards if isinstance(c, dict))
            if isinstance(raw_cards, (list, tuple))
            else ()
        )
        # 코퍼스가 review_status를 명시하면 그 값을, 없으면 AI 추정 상수를 쓴다(정직 표기).
        review_status = _opt_str(record.get("review_status")) or CONTENT_REVIEW_STATUS_AI_ESTIMATED
        out.append(
            ConceptContentRecord(
                code=code,
                scope=scope,
                name=name,
                subject=subject,
                unit=_opt_str(record.get("unit")),
                metaphor=_opt_str(record.get("metaphor")),
                misconception=_opt_str(record.get("misconception")),
                formal_definition_internal=_opt_str(record.get("formal_definition_internal")),
                accepted_expressions=_opt_str(record.get("accepted_expressions")),
                explanation=_opt_str(record.get("explanation")),
                standard_codes=codes,
                flashcards=cards,
                review_status=review_status,
            )
        )
    return out


class ConceptContentStore:
    """콘텐츠 4종 PG 프로젝션 적재기 — `concept_content` 테이블 code 키 멱등 upsert(sync).

    `AtomNodeStore`(원자 메타 프로젝션)의 *콘텐츠* 짝이다. `upsert`는 PK 충돌 upsert
    (`INSERT ... ON CONFLICT(code) DO UPDATE`)로 멱등 적재한다(같은 code 재적재 → 행 갱신·
    updated_at 갱신). `review_status`는 코퍼스 record의 값을 그대로 사용한다(승격 후 재적재 시
    `reviewed` 보존 — 부재 시 로더가 'ai_estimated' 기본). sync 엔진은 슬3 `_build_sync_engine`을
    재사용해 지연 생성·캐시한다(신규 seam 0). 벡터 컬럼이 없어 검색 메서드는 두지 않는다 — *적재
    전용* 좌석이다(조회·조인은 후속).
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
        """설정 지연 해석 — 주입 우선, 없으면 캐시된 전역 Settings(atom_node_projection 패턴)."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_engine(self) -> Engine:
        """sync 엔진 지연 해석 — 주입 우선, 없으면 슬3 빌더로 생성·캐시(신규 seam 0)."""
        if self._engine is None:
            self._engine = _build_sync_engine(self._resolved_settings)
        return self._engine

    def upsert(self, record: ConceptContentRecord) -> None:
        """단일 콘텐츠 레코드 upsert (멱등·code PK 충돌 갱신).

        `INSERT ... ON CONFLICT(code) DO UPDATE` — 콘텐츠 4종·설명·standard_codes·flashcards +
        record의 `review_status` + updated_at(now())을 갱신한다. 성취기준 *본문* 컬럼은
        없다(코퍼스 부재·레코드 슬롯 부재의 이중 차단). standard_codes는 PG TEXT[]·flashcards는
        dict 리스트(PG JSONB)로 바인딩한다. **`atom_codes`는 여기서 건드리지 않는다**(INSERT·set_
        미등장 — 신규 행은 server_default '{}', 기존 행 값은 보존): 채움 좌석은 S0-2 크로스워크
        전파(`l1/concept_atom_crosswalk/transfer.py`)이며, 콘텐츠 재적재가 전파 결과를 지우면
        안 된다.
        """
        from sqlalchemy import func
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from whymath_backend.db.models.concept_content import ConceptContent

        stmt = pg_insert(ConceptContent).values(
            code=record.code,
            scope=record.scope,
            name=record.name,
            subject=record.subject,
            unit=record.unit,
            metaphor=record.metaphor,
            misconception=record.misconception,
            formal_definition_internal=record.formal_definition_internal,
            accepted_expressions=record.accepted_expressions,
            explanation=record.explanation,
            standard_codes=list(record.standard_codes),
            flashcards=[dict(c) for c in record.flashcards],
            review_status=record.review_status,
        )
        # PK 충돌 시 갱신 — updated_at은 now()로 새로 찍는다(server_default는 INSERT 전용).
        stmt = stmt.on_conflict_do_update(
            index_elements=[ConceptContent.code],
            set_={
                "scope": stmt.excluded.scope,
                "name": stmt.excluded.name,
                "subject": stmt.excluded.subject,
                "unit": stmt.excluded.unit,
                "metaphor": stmt.excluded.metaphor,
                "misconception": stmt.excluded.misconception,
                "formal_definition_internal": stmt.excluded.formal_definition_internal,
                "accepted_expressions": stmt.excluded.accepted_expressions,
                "explanation": stmt.excluded.explanation,
                "standard_codes": stmt.excluded.standard_codes,
                "flashcards": stmt.excluded.flashcards,
                "review_status": stmt.excluded.review_status,
                "updated_at": func.now(),
            },
        )
        with self._get_engine().begin() as conn:
            conn.execute(stmt)

    def mark_review_status(self, codes: Sequence[str], review_status: str) -> int:
        """code 목록의 `review_status`를 일괄 갱신하고 영향받은 행 수를 반환.

        사람 검수 승격 시 `review_status='reviewed'`로 갱신하는 전용 좌석이다. `code`가
        테이블에 없으면 해당 행은 0으로 집계되며, 전체 code가 없으면 0을 반환한다.
        """
        from sqlalchemy import update

        from whymath_backend.db.models.concept_content import ConceptContent

        if not codes:
            return 0
        stmt = (
            update(ConceptContent)
            .where(ConceptContent.code.in_(codes))
            .values(review_status=review_status, updated_at=func.now())
        )
        with self._get_engine().begin() as conn:
            result = conn.execute(stmt)
            return int(result.rowcount)


def populate_concept_content(
    records: Sequence[ConceptContentRecord],
    *,
    settings: Settings | None = None,
    store: ConceptContentStore | None = None,
) -> int:
    """콘텐츠 4종 레코드를 `concept_content`에 멱등 upsert 적재(영속 프로젝션). 반환=적재 행 수.

    `populate_atom_nodes`의 *콘텐츠* 짝이다 — 각 레코드를 code 키로 upsert한다(멱등·재실행 시 갱신).
    store 미주입 시 슬3 sync 엔진 재사용 `ConceptContentStore`를 만든다.
    """
    resolved = settings if settings is not None else get_settings()
    content_store = store if store is not None else ConceptContentStore(settings=resolved)
    for record in records:
        content_store.upsert(record)
    return len(records)


__all__ = [
    "ConceptContentRecord",
    "ConceptContentStore",
    "load_concept_content_from_json",
    "populate_concept_content",
]
