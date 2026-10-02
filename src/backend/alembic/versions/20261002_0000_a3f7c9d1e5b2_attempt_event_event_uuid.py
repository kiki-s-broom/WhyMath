"""attempt_event.event_uuid 멱등키 + UNIQUE 부분 인덱스 (DP-03).

DP-02가 `AnalyticsEventEnvelope.event_uuid`(producer 생성 재전송 멱등키)를 계약으로만 정의했다.
이 리비전이 그 키를 DB에 착지시켜, 같은 이벤트의 재전송이 **DB가** 한 번만 반영되게 한다.

**시각 컬럼은 신설하지 않는다(실측 근거)**: envelope의 두 시각은 이미 영속 좌석이 있다.
  - `received_at`(서버 수신) = `attempt_event.event_at` (전 writer가 서버 now(UTC)를 넣어 왔고,
    hypertable 파티션 키라 재정의하지 않는다 — EOS-48·ADR-001 추기)
  - `occurred_at`(도메인 발생) = `attempt_event.event_time` (EOS-48, nullable)
새 `received_at`/`occurred_at` 컬럼을 더하면 같은 사실의 중복 좌석이 되어 "어느 쪽이 정본인가"
가 갈린다. 그래서 이 리비전은 `event_uuid` 1컬럼만 더한다.

**기존 BIGSERIAL `event_id`는 내부 키로 유지**한다(복합 PK `(event_id, event_at)` 불변).

**nullable·server_default 없음(백필 금지)**: 기존 행에 `gen_random_uuid()`를 채우면 *producer가
만든 적 없는 멱등키*를 날조하는 것이다 — NULL=멱등키 미부여(구판 writer·기존 행)가 정직하다
(EOS-48/57과 같은 규약). 기존 writer는 키를 안 넘기므로 무영향이다.

**부분 UNIQUE 인덱스**: `WHERE event_uuid IS NOT NULL` — NULL 행끼리는 충돌하지 않는다. 앱 사전
조회만으로는 동시 재전송 두 건이 서로의 행을 못 보고 둘 다 통과(check-then-act 경합)하므로,
정확히 한 건만 살리는 일은 유니크 제약이 맡는다(`uq_concept_mastery_history_attempt` 선례).
writer는 이 인덱스를 충돌 대상으로 `ON CONFLICT DO NOTHING` 한다.

**ADR-001 재확인 — hypertable 비호환을 fail-closed로 막는다**: TimescaleDB hypertable의 UNIQUE
인덱스는 파티션 키(`event_at`)를 포함해야 한다. 그런데 재전송은 `event_at`(서버 수신 시각)이
매번 달라 `(event_uuid, event_at)` UNIQUE로는 재전송을 못 막는다 — 즉 hypertable 위에서는 이
멱등 계약이 성립하지 않는다. 운영 DB는 일반 PostgreSQL 16(ADR-001 실측)이라 지금은 무충돌이지만,
`attempt_event`가 hypertable인 환경에서 이 인덱스를 조용히 약화(복합 키로 대체)하면 "멱등 보호
있음"으로 위장된다. 그래서 hypertable이면 **예외로 중단**하고 전환 ADR이 별도 설계(멱등키 전용
비-hypertable 테이블 등)를 하게 한다.

upgrade: 컬럼 1개 add(nullable) + 부분 UNIQUE 인덱스 1개.
downgrade: 인덱스 drop + 컬럼 drop(대칭).

Revision ID: a3f7c9d1e5b2
Revises: 9d3e7b1c5a20
Create Date: 2026-10-02 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f7c9d1e5b2"
down_revision: str | None = "9d3e7b1c5a20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_attempt_event_event_uuid"


def upgrade() -> None:
    # hypertable 가드 — timescaledb 미설치(운영·CI)면 정보 뷰 자체가 없으므로 extension 존재를
    # 먼저 본다. 존재+hypertable이면 멱등 계약이 성립하지 않아 중단한다(위 docstring).
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
                IF EXISTS (
                    SELECT 1 FROM timescaledb_information.hypertables
                    WHERE hypertable_name = 'attempt_event'
                ) THEN
                    RAISE EXCEPTION
                        'attempt_event가 hypertable이라 event_uuid 단독 UNIQUE를 만들 수 없다 '
                        '(파티션 키 event_at 포함 규칙) — ADR-001 전환 설계가 좌석을 정해야 한다';
                END IF;
            END IF;
        END
        $$;
        """)
    op.add_column("attempt_event", sa.Column("event_uuid", sa.Uuid(), nullable=True))
    op.create_index(
        _INDEX,
        "attempt_event",
        ["event_uuid"],
        unique=True,
        postgresql_where=sa.text("event_uuid IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="attempt_event")
    op.drop_column("attempt_event", "event_uuid")
