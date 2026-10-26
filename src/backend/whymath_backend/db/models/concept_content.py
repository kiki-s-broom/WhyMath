"""콘텐츠 4종 *PG 프로젝션* ORM — code 키 은유·오개념·정식정의·허용표현 + 암기카드 (Phase 3).

`atom_node`(원자 안전 메타 프로젝션·Phase 2a)의 *콘텐츠* 짝이다. Phase 3가 이미 캡처·커밋한
콘텐츠 코퍼스(`data/corpus/concept_content_v1/content.json`·K-12 개념 437 +
`concept_content_university_v1/content.json`·대학 소단원 409)의 **콘텐츠 4종**(은유·오개념·정식정의·
허용표현)과 설명·암기카드를 code 키로 영속 투영한다 — 학습 장면(L4 코칭·L5 표시·L6 게이팅)이
backend 조인으로 콘텐츠를 끌어쓰기 위한 백킹(`atom_node`·`concept_node`와 동일 설계 철학).

────────────────────────────────────────────────────────────────────────────
additive — 구 437/원자/concept_node와 무충돌 (왜 신규 테이블인가)
────────────────────────────────────────────────────────────────────────────
`concept_node`(UC 키·search enrichment용 loose `metaphor`/`accepted_expressions`만)는 *건드리지
않는다*. 이 테이블은 *콘텐츠 4종 정식 소스*(전 4종 + 설명 + 암기카드)를 담는 별개 좌석이다.
PK는 `code`(K-12=구 437 개념코드 예 `N1`·`A1` / 대학=소단원코드 예 `CALC1-U1-S1`)다 — K-12·대학
코드는 겹치지 않아 단일 PK로 안전하며, `scope`('K-12'|'대학') 컬럼으로 구분·필터한다. **FK는 두지
않는다**(loose ref·`misconception_catalog.concept_src_id` 선례): K-12 콘텐츠 코드는 *구 437 개념
택소노미*라 원자 code와 닿지 않고(원자 연결은 Phase 4 크로스워크), 대학 코드는 atom_node 소단원
code와 일치하나 FK 결합 대신 느슨참조로 둔다(적재 순서·재적재 독립성).

────────────────────────────────────────────────────────────────────────────
법적·노출 (CLAUDE.md 우선순위 #2)
────────────────────────────────────────────────────────────────────────────
콘텐츠 4종·설명·암기카드는 **전량 와이매스 자체작성**(AI 생성+검수)이라 보유 허용이다. K-12 성취기준
*본문*은 코퍼스에 *애초에 없고*(연결 `standard_codes` *코드*만 다리·구조 차단), 이 테이블도
standard_codes만 둔다. `formal_definition_internal`(정식정의)은 자체창작이라 *저장*하되 **학생
비노출(내부·검수·교사용)**이다 — 컬럼명이 그 의도를 드러내며, 노출 게이팅은 소비계층(L5/L6)
책임이다(이 좌석은 충실히 보관할 뿐 노출 정책을 구현하지 않는다).

review_status는 PG enum 타입을 새로 만들지 않고 **plain `sa.Text`**로 둔다(`atom_node` 동형).
콘텐츠는 안내 시트상 *AI 추정·검수필요*라 기본값 상수 `'ai_estimated'`로 적재한다(정직 표기·게이팅).

7계층: L1 데이터 기반의 *영속 프로젝션*(콘텐츠 서빙 백킹). 보관만 하며 소비(L4/L5/L6)는 후속
(역방향 의존 금지). schema/ 상응 Pydantic 표면은 코퍼스 계약용으로 둔다(misconception_catalog 선례).
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.schema.concept_content import ConceptContentSchema

# 콘텐츠 검수 상태 기본값 — 안내 시트상 *AI 추정·검수필요*라 '검수 완료'가 아닌 'ai_estimated'.
# 게이팅 필터가 이 리터럴과 비교한다(정직 표기·검수 승격 시 'reviewed'로 갱신 가능·plain text).
CONTENT_REVIEW_STATUS_AI_ESTIMATED: str = "ai_estimated"

# scope 값 — K-12 콘텐츠(구 437 개념코드)와 대학 콘텐츠(소단원코드)를 구분·필터.
CONTENT_SCOPE_K12: str = "K-12"
CONTENT_SCOPE_UNIVERSITY: str = "대학"


class ConceptContent(Base):
    """콘텐츠 4종 PG 프로젝션 — code 키 은유·오개념·정식정의·허용표현 + 설명 + 암기카드.

    한 행 = 한 개념(K-12)/소단원(대학)의 콘텐츠 4종 + 설명 + 암기카드(JSONB list). PK(code)는
    K-12=구 437 개념코드·대학=소단원코드(겹침 0). upsert로 멱등 적재한다(`ON CONFLICT(code) DO
    UPDATE`). `formal_definition_internal`은 저장하되 학생 비노출(노출 게이팅은 소비계층 책임).
    """

    __tablename__ = "concept_content"

    # PK = K-12 개념코드(예 'N1'·'A1') / 대학 소단원코드(예 'CALC1-U1-S1'). 겹침 0·upsert 충돌 키.
    code: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    # 범위(K-12|대학) — 콘텐츠 출처 축 구분·필터. plain TEXT(보조 인덱스).
    scope: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 개념명/소단원명(corpus `name`·필수). 표시 핵심.
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 과목(corpus `subject`·필수·예 '초등수학'·'갈루아 이론'·필터). plain TEXT(보조 인덱스).
    subject: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 단원/영역(corpus `unit`·nullable).
    unit: Mapped[str | None] = mapped_column(sa.Text)
    # 콘텐츠 4종 — 전량 자체작성(보유 허용). nullable(코퍼스 빈 값 가능·채움률은 코퍼스 의존).
    metaphor: Mapped[str | None] = mapped_column(sa.Text)
    misconception: Mapped[str | None] = mapped_column(sa.Text)
    # 정식정의 — 자체창작·**학생 비노출**(내부·검수·교사용). 노출은 소비계층(L5/L6) 게이팅 책임.
    formal_definition_internal: Mapped[str | None] = mapped_column(sa.Text)
    accepted_expressions: Mapped[str | None] = mapped_column(sa.Text)
    # 설명(연결 맥락·corpus `explanation`·nullable).
    explanation: Mapped[str | None] = mapped_column(sa.Text)
    # 연결 NCIC 성취기준 *코드* 목록(corpus `standard_codes`·K-12만·대학은 []). 코드는 사실정보·
    # *본문 statement는 아님*(redaction 무관·atom_node 동형). nullable=False·server_default 빈 배열.
    standard_codes: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")
    )
    # 연결 원자 code 목록(S0-2·437↔원자 크로스워크 경유 연결 — Slice 1이 "원자 연결은 Phase 4"로
    # 예고한 좌석). K-12 행만 크로스워크 atom_codes(사전순·dedup)로 채우고, **대학 행은 '{}' 유지**
    # (대학 code=소단원코드가 이미 원자 그래프 `atom_node.code`와 같은 키 공간이라 원자 정합 —
    # 다리 불요). FK 없는 느슨참조(standard_codes 동형·적재 순서 독립). 채움 좌석은
    # `l1/concept_atom_crosswalk/transfer.py`(콘텐츠 4종 projection은 이 컬럼을 건드리지 않는다).
    atom_codes: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")
    )
    # 암기카드 목록(corpus `flashcards`·front/back/mnemonic/exposure_condition/grade/difficulty_tier
    # dict 배열·0개 이상). JSONB로 보관(중첩 구조·atom_node.atomicity JSONB 선례). 기본 빈 배열.
    flashcards: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB(none_as_null=True), nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    # 검수 게이팅 플래그 — 콘텐츠는 *AI 추정·검수필요*라 기본 'ai_estimated'(정직 표기). PG native
    # enum 미생성(atom_node.review_status 동형·plain text). 게이팅이 이 값과 리터럴 비교. NOT NULL.
    review_status: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 마지막 upsert 시각 — 운영·신선도. server_default now()(upsert 시 코드가 갱신·atom_node 동형).
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    # CMS 편집 표지(P3-25) — NULL=사람이 고친 적 없음(적재가 소유), 값=CMS가 마지막으로 고친 시각.
    # 적재(`populate`)는 이 값이 있는 행을 건너뛰어 충돌로 보고한다. server_default·백필 금지.
    # 규약 정본: `db/cms_edit_marker.py` · `docs/standards/cms_edit_vs_loader_contract.md`.
    cms_edited_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # scope(K-12/대학)·subject(과목) 필터 보조 인덱스(콘텐츠 서빙·검수 빈번).
        sa.Index("ix_concept_content_scope", "scope"),
        sa.Index("ix_concept_content_subject", "subject"),
    )

    def to_schema(self) -> ConceptContentSchema:
        """ORM 행 → Pydantic 응답 스키마(안전·내부 표면용)."""
        return ConceptContentSchema(
            code=self.code,
            scope=self.scope,
            name=self.name,
            subject=self.subject,
            unit=self.unit,
            metaphor=self.metaphor,
            misconception=self.misconception,
            formal_definition_internal=self.formal_definition_internal,
            accepted_expressions=self.accepted_expressions,
            explanation=self.explanation,
            standard_codes=list(self.standard_codes or []),
            flashcards=list(self.flashcards or []),
            review_status=self.review_status,
            updated_at=self.updated_at,
        )


__all__ = [
    "ConceptContent",
    "CONTENT_REVIEW_STATUS_AI_ESTIMATED",
    "CONTENT_SCOPE_K12",
    "CONTENT_SCOPE_UNIVERSITY",
]
