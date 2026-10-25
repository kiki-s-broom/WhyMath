"""원자 메타 *PG 프로젝션* ORM — code 키 안전 표시·필터 메타 (원자 마이그레이션 Phase 2a).

`concept_node`(개념그래프 소비 슬1·UC 키 메타 프로젝션)의 *원자 백본* 짝이다. Phase 1이 원자
코퍼스(`data/corpus/atom_graph_v1/graph.json` — 노드 수는 `docs/data/corpus_facts.md`의
`atom_graph.nodes`)를 backend `concept`/`concept_edge`에 *런타임 최소 식별*만 적재했고, 풍부
원자 메타(인지축·노드유형·학교급·전이·원자성·연결성취기준)는 코퍼스에 보존돼 있었다. 이
테이블이 그 *안전 메타*를 code 키로 영속 투영한다 — 검색 enrichment·필터·검수 게이팅을
backend async-PG 조인으로 하기 위한 백킹(`concept_node`와 동일 설계 철학).

────────────────────────────────────────────────────────────────────────────
concept_node와의 차이 (왜 신규 테이블인가 — 재키잉 아닌 additive)
────────────────────────────────────────────────────────────────────────────
`concept_node`(UC 키·`difficulty_tier` 0~24·`domain` NOT NULL)는 *건드리지 않는다*. 원자는
의미가 다르다:
  - **키**: code(`원자ID`/`소단원코드`/`단원코드`·예 `2수01-01-2`·`초수연-U1-S1`·`초수연-U1`) —
    backend `concept.code`·Phase 1 적재기와 동일 키 공간(UC 아님).
  - **난이도**: `intrinsic_difficulty` 1~5 정수(세부개념만·단원/소단원 None) — `concept_node`의
    0~24 difficulty_tier와 스케일이 다르다(억지 재사용 금지·Phase 1 `clamp_difficulty`와 동형).
  - **영역**: `subject_area`(예 '수와 연산'·null 허용) — `concept_node.domain`(NOT NULL)과 다름.
신규 테이블이라 기존 검색·`concept_node`·임베딩에 무영향(additive).

────────────────────────────────────────────────────────────────────────────
redaction (CLAUDE.md 우선순위 #2 — 협상 불가·구조적 차단)
────────────────────────────────────────────────────────────────────────────
**`core_proposition`·`description`·`formal_definition`은 이 테이블에 컬럼으로 두지 않는다.**
성취기준 *본문* 근접 복제 위험 필드이고, ① graph.json엔 있으나 적재기가 *읽지도 않고* ② 여기
*둘 곳도 없다*(이중 방어). `concept_node`가 본문 슬롯을 두지 않은 것과 같은 redaction 규약이다.

**4요소 콘텐츠(①misconception·②diagnostic_item/answer/signal·③socratic)도 넣지 않는다** —
이는 Phase 3에서 `misconception_catalog`/`problem`로 *정식 콘텐츠 소스 승격* 대상이라(로드맵
Phase 3), 메타 프로젝션이 *선점·이중 보관*하면 안 된다. 4요소 중 ④`transfer`(전이)·`atomicity`
(원자성)만 concept-level *안전 메타*라 포함한다(은유·정식정의 아님·표시 가능 교수 주석 성격).

수록 필드는 *전부 안전*이다:
  - `name_ko`·`level`·`parent_code`: 표시·계층 식별용 자체 메타(본문 아님).
  - `school_level`·`subject_area`·`subunit_code`: 학교급·영역·소단원 코드(필터·코드는 사실정보).
  - `cognitive_type`(인지축)·`node_type`(노드유형)·`misconception_type`(오개념유형): 자체 택소노미
    라벨(본문 아님·필터·분석 메타). **plain TEXT — PG native enum을 만들지 않는다**(인지축/노드유형/
    학교급은 자유 라벨이고, `concept_node.review_status`가 plain text인 선례·억지 enum 결합 회피).
  - `intrinsic_difficulty`(1~5 정수): 난이도 라벨(본문 아님).
  - `standard_codes`(NCIC 코드[]): 코드는 사실정보·공공·*본문 statement는 아님*(concept_node 동형).
  - `transfer`(전이): 자체 작성 교수 주석(표시 가능 안전 필드).
  - `atomicity`(JSONB·원자성 dict): a/b/c/d 원자성 판정 메타(구조 메타·본문 아님).

review_status는 PG enum 타입을 새로 만들지 않고 **plain `sa.Text`**로 둔다(`concept_node` 동형).
원자 메타는 안내 시트상 *AI 추정*이라 기본값 상수 `'ai_estimated'`로 적재한다(검수 게이팅용·정직
표기 — '검수 완료'가 아님을 기계적으로 드러낸다).

────────────────────────────────────────────────────────────────────────────
인덱스
────────────────────────────────────────────────────────────────────────────
PK `code`로 충분하다(enrichment는 code IN/조인). 다만 `level`(단원/소단원/세부개념 필터)·
`school_level`(초/중/고/대 필터)은 검색·추천에서 자주 거는 필터라 보조 인덱스를 둔다(2,697행
규모에 과하지 않은 정석 필터 인덱스).

7계층: L1 데이터 기반의 *영속 프로젝션*(검색 서빙 백킹). 표시·필터·게이팅 메타를 보관할 뿐,
검색 *로직*·소비(L2 추천·L4 오개념 결선)는 이 좌석을 쓰되 여기서 구현하지 않는다(역방향 의존
금지·후속). schema/ 상응 Pydantic 표면은 없다(`concept_node`·`concept_embedding` 선례).
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base

# 원자 메타 검수 상태 기본값 — 안내 시트상 *AI 추정*이라 '검수 완료'가 아닌 'ai_estimated'.
# 게이팅 필터가 이 리터럴과 비교한다(정직 표기·검수 승격 시 'reviewed'로 갱신 가능·plain text).
ATOM_REVIEW_STATUS_AI_ESTIMATED: str = "ai_estimated"


class AtomNode(Base):
    """원자 메타 PG 프로젝션 — code 키 안전 표시·필터 메타(검색 enrichment 백킹).

    한 행 = 한 원자 노드(원자/단원/소단원)의 *안전 메타*(name_ko·level·school_level·인지축·
    노드유형·난이도·전이·원자성 등). PK(code=원자ID/소단원코드/단원코드)로 backend `concept.code`·
    Phase 1 적재기와 동일 키 공간. upsert로 멱등 적재한다(`ON CONFLICT(code) DO UPDATE`).
    **core_proposition·description·formal_definition·4요소(misconception/diagnostic/socratic)는
    컬럼으로 두지 않는다**(redaction — 안전 메타만 투영·docstring 참조).
    """

    __tablename__ = "atom_node"

    # PK = 원자ID/소단원코드/단원코드(Phase 1 `concept.code`와 동일 공간·UC 아님). upsert 충돌 키.
    code: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    # 한국어 명칭(graph.json `name`·필수). 검색 enrichment의 핵심 표시 필드.
    name_ko: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 계층(단원/소단원/세부개념·graph.json `level`·필수·직대응). 필터·표시. plain TEXT(보조 인덱스).
    level: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 부모 노드 code(원자→소단원·소단원→단원·단원→None·graph.json `parent_code`·nullable).
    parent_code: Mapped[str | None] = mapped_column(sa.Text)
    # 학교급(초등/중학/고등/대학·graph.json `school_level`·nullable·필터). plain TEXT(보조 인덱스).
    school_level: Mapped[str | None] = mapped_column(sa.Text)
    # 영역명(예 '수와 연산'·graph.json `subject_area`·nullable·필터·concept_node.domain과 별 의미).
    subject_area: Mapped[str | None] = mapped_column(sa.Text)
    # 소단원 코드(graph.json `subunit_code`·nullable·식별·코드는 사실정보).
    subunit_code: Mapped[str | None] = mapped_column(sa.Text)
    # 인지축(개념/절차/표상·graph.json `cognitive_type`·nullable·자체 택소노미·plain TEXT·enum 무).
    cognitive_type: Mapped[str | None] = mapped_column(sa.Text)
    # 노드유형(선행/구성/결과·graph.json `node_type`·nullable·자체 택소노미·plain TEXT·enum 무).
    node_type: Mapped[str | None] = mapped_column(sa.Text)
    # 오개념유형(개념혼동 등·graph.json `misconception_type`·nullable·라벨만·오개념 *본문* 아님).
    misconception_type: Mapped[str | None] = mapped_column(sa.Text)
    # 내재 난이도 1~5(graph.json `intrinsic_difficulty`·세부개념만·단원/소단원 None). 정수 라벨.
    intrinsic_difficulty: Mapped[int | None] = mapped_column(sa.Integer)
    # 매핑된 NCIC 성취기준 *코드* 목록(graph.json `standard_codes`·기본 빈 배열). 코드는 사실정보·
    # 공공이며 *본문 statement는 아님*(redaction 무관). nullable=False·server_default 빈 배열.
    standard_codes: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")
    )
    # 전이(④요소·graph.json `transfer`·nullable·자체 작성 교수 주석·표시 가능 안전 필드).
    transfer: Mapped[str | None] = mapped_column(sa.Text)
    # 전이 예시(graph.json `transfer_example`·nullable·자체 작성·표시 가능).
    transfer_example: Mapped[str | None] = mapped_column(sa.Text)
    # 원자성 판정(graph.json `atomicity`·a/b/c/d dict·nullable·구조 메타·본문 아님). JSONB.
    atomicity: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    # 원자→skill 참조 키 목록(S0-2·437↔원자 크로스워크 경유 이전·`concept_node.behavior_skills`
    # 동형 미러). skill_id(`skill.<slug>`) 목록이며 본문 아님(안전 배열·junction 아님·신규 엣지
    # 타입 0 — anti-explosion). 채움 좌석은 `l1/concept_atom_crosswalk/transfer.py`(크로스워크
    # 전파)이며 graph.json 메타 프로젝션(`atom_node_projection`)은 이 컬럼을 건드리지 않는다.
    # 전파 규칙: crosswalk 행의 atom_codes *전체*에 concept의 behavior_skills를 전파, 복수
    # concept이 닿으면 union+dedup·사전순 — 스킬은 개념의 구성 원자 전체에 적용되는 인지 행동
    # 이라 배타 귀속이 아니다(primary 귀속 규칙은 mastery/오개념용·데이터카드 §4).
    behavior_skills: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")
    )
    # 검수 게이팅 플래그 — 원자 메타는 *AI 추정*이라 기본 'ai_estimated'(정직 표기). PG native enum
    # 미생성(concept_node.review_status 동형·plain text). 게이팅이 이 값과 리터럴 비교. NOT NULL.
    review_status: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 마지막 upsert 시각 — 운영·신선도. server_default now()(upsert 시 코드가 갱신·concept_node 동).
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    __table_args__ = (
        # level(단원/소단원/세부개념)·school_level(초/중/고/대) 필터 보조 인덱스(검색·추천 빈번).
        sa.Index("ix_atom_node_level", "level"),
        sa.Index("ix_atom_node_school_level", "school_level"),
    )


__all__ = ["AtomNode", "ATOM_REVIEW_STATUS_AI_ESTIMATED"]
