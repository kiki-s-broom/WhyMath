"""generation_log에 관측 좌석 2컬럼 추가 — served_model·retries (EOS-112).

**왜 필요한가**: `generation_log.model_name`은 *설정이 지목한* 모델이지 *응답이 온* 모델이
아니다. ARCH-57이 클라우드 슬롯을 셀렉터로 바꾸고 ARCH-58이 그 선언값을 셀렉터와 정합하게
고쳤지만, 둘 다 **선언 축**이다. provider 측 대체·폴백·프록시 라우팅이 일어나면 기록은
여전히 조용히 틀린 값을 적고, 읽는 사람은 그것을 믿는다(ARCH-58 사고 경위와 같은 형태).

컬럼(ORM 정본 `db/models/provenance.py::GenerationLog`와 1:1):
  - `served_model` VARCHAR(128) — 응답 최상위의 모델 식별자(OpenAI 호환 `model` ·
    Anthropic `message.model` · Ollama `model`). 폭이 `model_name`(64)보다 넓은 이유는
    **외부 응답이 값을 정하기** 때문이다(공급사 접미·날짜 버전).
  - `retries` INTEGER — 이 호출 1건의 재시도 횟수. 재시도는 측정을 가린다 — 30% 실패를
    재시도로 덮으면 리포트가 100% 성공으로 보인다.

**NULL=미기록·미계측(정직)**: 두 컬럼 다 nullable·server_default 없음. 구 행은 이 축 없이
적재됐으므로 값을 소급 날조하지 않는다(EOS-55 재현 좌석·EOS-97 run_id와 같은 방침).
`retries`의 NULL은 특히 **0이 아니다** — Anthropic SDK·Ollama는 우리 전송기를 타지 않아
카운터 자체가 없고, 0으로 채우면 계측 없는 경로가 '재시도 0회 실측'처럼 보인다.

**인덱스 없음**: 두 축의 주 질의는 회차 단위 집계(이미 `idx_generation_run_id`가 좁혀 준다)
이지 `served_model` 단독 조회가 아니다. 쓰이지 않을 인덱스를 미리 만들지 않는다.

upgrade: nullable 2컬럼 add. downgrade: 역순 drop(완전 복원).

Revision ID: d2a9e4b71c35
Revises: c1f5a8b2d740
Create Date: 2026-09-19 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2a9e4b71c35"
down_revision: str | None = "c1f5a8b2d740"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 관측 축 — nullable·server_default 없음(구 행 NULL=미기록·소급 날조 금지).
    op.add_column("generation_log", sa.Column("served_model", sa.String(length=128), nullable=True))
    op.add_column("generation_log", sa.Column("retries", sa.Integer(), nullable=True))


def downgrade() -> None:
    # upgrade 역순 drop — 완전 복원(대칭).
    op.drop_column("generation_log", "retries")
    op.drop_column("generation_log", "served_model")
