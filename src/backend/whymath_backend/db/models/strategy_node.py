"""전략 노드 *PG 프로젝션* ORM — strategy_id 키 안전 메타 (리치 Part 2 Phase 6a).

`problem_type_node`·`formula_node`(메타 프로젝션)의 *전략* 짝이다. data-pipeline
`strategy_graph`가 문제 공략 heuristic 택소노미를 `graph.json`(canonical 전략 노드)으로
정형화했고, 이 테이블이 그 *안전 메타*를 strategy_id 키로 영속 투영한다 — 검색 enrichment·필터·
(후속) 전략 참조 백킹. upsert로 멱등 적재한다(`ON CONFLICT(strategy_id) DO UPDATE`).

────────────────────────────────────────────────────────────────────────────
축 구별 (핵심 경계 — 전략 ≠ 추론타입 ≠ 접근유형)
────────────────────────────────────────────────────────────────────────────
- `StrategyNode`는 학생이 문제를 만났을 때 *어떤 발상으로 공략하는가*(Polya 계획 단계의 heuristic·
  cognitive action)를 canonical 단위로 담는다.
- 스텝 단위 `ReasoningType`(한 추론 스텝이 무엇인가)·풀이 전체 `approach_type`(완성된 풀이가 어떤
  접근인가)과 **직교하는 축**이다 — slug 집합이 두 축 값과 문자열 disjoint하게 명명됐다
  (`test_strategy_governance.py`가 교집합 ∅을 동결). 세 축 혼동 금지.

법적(CLAUDE.md 우선순위 #2): 전략 택소노미는 **전량 자체작성**(Polya 표준 어휘로 수렴한 heuristic
추상)이라 저작권 무관 — 어느 책 *본문도 복제하지 않는다*(`description`은 인지행동 기준 자체 서술·
`standard_codes`는 연결 코드만). native PG enum 없음(전량 TEXT/TEXT[]·enum-free). schema/ 상응
Pydantic 표면 없음(`problem_type_node`·`formula_node` 선례).

인덱스: PK `strategy_id`로 충분하되 `family`(전략 그룹핑)는 필터 축이라 보조 인덱스를 둔다.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base

# 전략 메타 검수 상태 기본값 — v1 택소노미는 자체작성이나 검수 전이라 정직하게 'ai_estimated'
# (formula_node·problem_type_node 동형·검수 승격 시 'reviewed'로 갱신·plain text). 게이팅이 비교.
STRATEGY_REVIEW_STATUS_DEFAULT: str = "ai_estimated"


class StrategyNode(Base):
    """전략 메타 PG 프로젝션 — strategy_id 키 안전 표시·필터 메타(검색 백킹).

    한 행 = 한 canonical 전략 노드의 안전 메타(name_ko·family·description·연결 성취기준 코드).
    PK(strategy_id=`strategy.<slug>`)로 멱등 upsert 적재한다. 별도 엣지·선수 DAG 슬롯은 두지 않는다
    (closed 8노드 택소노미·연결은 소비처 참조 키가 담당·formula_node·problem_type_node 동형).
    """

    __tablename__ = "strategy_node"

    # PK = strategy_id(`strategy.<slug>`·사람 관리 안정 code·upsert 충돌 키). 타 노드 공간과 분리.
    strategy_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    # 한국어 표시명(graph.json `name_ko`·필수). 검색 enrichment 핵심 표시 필드.
    name_ko: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 전략 family(4종 그룹·graph.json `family`·필수). 필터·집계 축.
    family: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 인지행동 기준 자체작성 설명(graph.json `description`·필수·표면 표현 아님·본문 미복제).
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 연결 NCIC 성취기준 *코드* 목록(graph.json `standard_codes`·기본 빈 배열·코드는 사실정보).
    standard_codes: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")
    )
    # 검수 게이팅 — v1 자체작성이나 검수 전이라 기본 'ai_estimated'(formula 동형·NOT NULL).
    review_status: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 마지막 upsert 시각 — 운영·신선도. server_default now()(formula_node·problem_type_node 동형).
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
        # family(전략 family 그룹) 보조 인덱스(검색·집계).
        sa.Index("ix_strategy_node_family", "family"),
    )


__all__ = ["StrategyNode", "STRATEGY_REVIEW_STATUS_DEFAULT"]
