"""L2 학습 증거 하이퍼테이블 ORM — 유형별 달성 증거 이벤트 (교수법 DSL 기반·별 리비전).

설계 정본: `docs/reviews/260724_v2_migration_pedagogy_dsl_review.md`(검토서)와
`docs/reviews/260724_v2_migration_pedagogy_dsl.alembic_draft.py`(수정 목표 스키마).

`evidence_event`는 학습목표(`learning_objective`)에 대한 *유형별 달성 증거*("정답≠달성")를
시계열로 적재하는 L2 학습자 데이터 하이퍼테이블이다. L3 콘텐츠/팩과 계층 경계가 다르므로
**별 모듈·별 마이그레이션**으로 분리한다(검토서 H3 — 역방향 의존 금지).

────────────────────────────────────────────────────────────────────────────
attempt_event 선례 (이벤트 하이퍼테이블 PK·느슨참조)
────────────────────────────────────────────────────────────────────────────
`attempt_event`(§6.1)와 동형으로:
  - surrogate `BigInteger` `event_id`(autoincrement·DB-assigned) + 파티션 키 `time`을 **복합 PK**로
    둔다(하이퍼테이블 UNIQUE 제약이 파티션 키를 포함하도록 하는 규칙·동시 이벤트 충돌 회피).
  - `objective_id`·`session_id`는 §6.1 attempt_event처럼 **FK가 아니다**(하이퍼테이블 느슨참조 —
    FK 조인 회피). `objective_id`는 `learning_objective.id`를 가리키는 느슨참조다.
  - 하이퍼테이블 변환(`create_hypertable`)은 *마이그레이션 레벨*이라 ORM에서는 일반 테이블로
    둔다(hypertable 코드를 ORM에 넣지 않는다·attempt_event 방침).

────────────────────────────────────────────────────────────────────────────
B1: 미성년 원문 발화 평문 저장 금지 (CLAUDE.md 절대 금기)
────────────────────────────────────────────────────────────────────────────
학생 원문 발화·풀이 같은 *미성년 채팅 데이터*는 **평문 컬럼으로 두지 않는다**. `dialogue_turn`의
봉투 암호화(AES-256-GCM) 선례를 미러한다:
  - `payload_encrypted`(LargeBinary·nullable) — 마스터 키(DB 밖·env)로 암호화된 본문.
  - `payload_nonce`(LargeBinary·nullable) — 96-bit nonce. 둘 다 NULL이면 원문 없음(메타만).
  - `retention_until`(TIMESTAMPTZ·nullable) — 행별 파기 만료일 *예약 컬럼*. 이 값을 읽는 파기
    경로도, 채우는 writer도 현재 없다(SEC-41 실측: `EvidenceEvent(...)` writer 3곳 모두 미설정 ·
    `EvidenceEventStore.log`는 호출처 0건·기본 None). 보존 파기는 `time` 기준 균일 창이다 —
    `privacy/retention.py`의 `_RETENTION_PLAN`(모듈 docstring ⓐ). 예전 서술("retention.py
    소관")은 읽는 코드가 없는 상태에서 소관만 선언한 것이었다.
비민감 메타(문항 ID·유형 등)만 평문 `meta`(JSONB)에 둔다. 암호화-at-write는 handler/헬퍼 층이
담당하고(순수 seam에 cipher 미주입·dialogue 선례), 이 좌석에는 컬럼만 두고 가짜 CHECK를 만들지
않는다. **schema/ Pydantic 표면·round-trip seam을 신설하지 않으므로** `dialogue_turn`의
`_NON_SCHEMA_COLUMNS`(round-trip 시 ciphertext 제외) 패턴은 이 모듈에 해당 없음이다 — 제외할
seam 자체가 없다(ciphertext는 애초에 어떤 schema 표면에도 노출되지 않는다).

7계층: L2 학습자 모델의 영속 증거 좌석. 소비(달성 판정·출구 게이트)는 이 좌석을 쓰되 여기서
구현하지 않는다(역방향 의존 금지·후속).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.db.models._orm_enum import _pg_enum
from whymath_backend.schema.enums import KnowledgeType


class EvidenceEvent(Base):
    """학습 증거 이벤트 영속 ORM — 학습목표별 유형 달성 증거 시계열(하이퍼테이블·B1 암호화).

    복합 PK `(event_id, time)` — attempt_event 선례(surrogate BigInt·파티션 키). `objective_id`·
    `session_id`는 FK가 아니다(하이퍼테이블 느슨참조). `k_type`은 native enum(M4). 원문 발화는
    평문 금지 → `payload_encrypted`/`payload_nonce`/`retention_until`(B1·dialogue_turn 선례), 비민감
    메타만 `meta`(JSONB) 평문.

    운영 시 이 테이블은 TimescaleDB 하이퍼테이블(`time` 7일 청크)로 변환되나, *그 변환은
    마이그레이션 레벨*이라 ORM에서는 일반 테이블로 둔다(attempt_event 방침).
    """

    __tablename__ = "evidence_event"

    # ===== 복합 PK (event_id, time) — attempt_event 선례 =====
    # BIGSERIAL → BigInteger autoincrement PK(DB-assigned·gen_random_uuid 없음).
    event_id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    # 파티션 키(TIMESTAMPTZ NOT NULL)이자 복합 PK 구성요소.
    time: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), primary_key=True)

    # ===== 느슨참조 (REFERENCES 없음 — 하이퍼테이블 FK 회피) =====
    session_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    # learning_objective.id를 가리키는 느슨참조(FK 아님·하이퍼테이블 규칙).
    objective_id: Mapped[str] = mapped_column(sa.Text, nullable=False)

    # ===== 유형·팩 컨텍스트 =====
    k_type: Mapped[KnowledgeType] = mapped_column(
        _pg_enum(KnowledgeType, "knowledge_type"), nullable=False
    )
    pack_version: Mapped[int | None] = mapped_column(sa.Integer)

    # ===== 이벤트 본문 신호 =====
    # 이벤트 유형(팩이 정의 — enum 아닌 TEXT). NOT NULL.
    event_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    correct: Mapped[bool | None] = mapped_column(sa.Boolean)
    rt_ms: Mapped[int | None] = mapped_column(sa.Integer)
    judge_score: Mapped[int | None] = mapped_column(sa.SmallInteger)
    fidelity_score: Mapped[int | None] = mapped_column(sa.SmallInteger)

    # ===== B1: 비민감 메타만 평문·원문 발화는 봉투 암호화 =====
    # 비민감 메타(문항 ID·유형 등)만 평문 JSONB. 원문 발화 금지.
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # 원문 발화 등 미성년 데이터 — AES-256-GCM 암호화 본문(dialogue_turn 선례 미러).
    payload_encrypted: Mapped[bytes | None] = mapped_column(sa.LargeBinary)
    # 96-bit nonce. 둘 다 NULL이면 원문 없음(메타만). 키가 DB 밖이라 dump 단독 복호 불가.
    payload_nonce: Mapped[bytes | None] = mapped_column(sa.LargeBinary)
    # 행별 파기 만료일 예약 컬럼 — 읽는 파기 경로·채우는 writer 모두 없다(위 docstring·SEC-41).
    # 실제 보존 파기는 `time` 기준(`privacy/retention.py` `_RETENTION_PLAN`).
    retention_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (
        # judge/fidelity 점수 0~3(nullable 허용).
        sa.CheckConstraint(
            "judge_score IS NULL OR judge_score BETWEEN 0 AND 3",
            name="judge",
        ),
        sa.CheckConstraint(
            "fidelity_score IS NULL OR fidelity_score BETWEEN 0 AND 3",
            name="fidelity",
        ),
        # 목표별 최근 증거 조회(objective_id, time DESC) — idx_session_user 선례(DESC 정렬).
        sa.Index("idx_ev_obj_time", "objective_id", sa.desc("time")),
    )


__all__ = ["EvidenceEvent"]
