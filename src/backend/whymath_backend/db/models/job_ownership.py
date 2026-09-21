"""job_ownership 테이블 — 비동기 QUALITY 작업(job_id)의 생성자 기록 (SEC-27, 48_보안 §P0).

`/v1/jobs/{job_id}` 폴링은 인증만 게이트했고(SEC-24(원 SEC-15) M6) 소유권(job↔user) 검사는
job 저장 구조에 user 매핑이 없어 불가능했다(`app.py` 모듈 docstring 경계 메모). 이 테이블이
그 매핑이다 — Celery 자체는 job_id(태스크 id) 외에 어떤 메타데이터도 갖지 않으므로(브로커·
result backend는 이름 없는 페이로드만 오간다), 소유자 기록은 이 백엔드가 별도로 영속해야 한다.

설계(`refresh_token_session.py` 동형 — 서버 내부 소유권 테이블):
  - **PK = job_id(String) = Celery 태스크 id**: `queue.enqueue()`가 반환한 문자열을 그대로
    쓴다(발급 시 앱이 만드는 UUID가 아니라 *외부에서 받은 불투명 문자열*이므로 `sa.Uuid`가
    아니라 `sa.String` — Celery의 job_id 포맷을 이 테이블이 강제하지 않는다). server_default
    없음 — API 핸들러가 큐잉 직후 즉시 기록한다.
  - **user_id FK → user_profile.user_id (NOT NULL)**: 소유자. CASCADE 미적용 — 사용자 삭제
    시 정리는 상위 lifecycle 몫(device.py·refresh_token_session.py 방침 동일).
  - **created_at**: 기록 시각(운영·감사 메타). 조회는 PK(job_id) 단건 lookup뿐이라 별도
    사용자별 인덱스는 두지 않는다(refresh_token_session의 idx_..._user는 *사용자별 목록
    조회*가 있어 필요했지만, 이 테이블은 그런 소비처가 아직 없다 — 필요해지면 추가).

Pydantic `schema/` 상응물 없음(서버 내부 테이블 — device.py·refresh_token_session.py 방침).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base


class JobOwnership(Base):
    """비동기 작업 소유권 행 — job_id(Celery 태스크 id) 1개당 1행(PK).

    `POST /v1/generate`가 QUALITY로 큐잉되면 반환된 job_id로 이 행을 기록하고, `GET
    /v1/jobs/{job_id}`가 PK lookup으로 `user_id`를 대조해 소유자 여부를 판정한다.
    """

    __tablename__ = "job_ownership"

    # PK = Celery 태스크 id(문자열, 외부 발급 — server_default 없음. API가 큐잉 직후 기록).
    job_id: Mapped[str] = mapped_column(sa.String(255), primary_key=True)
    # user_profile.user_id FK — 소유자. CASCADE 미적용(device.py·refresh_token_session.py 방침).
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("user_profile.user_id"), nullable=False
    )
    # 기록 시각 — 운영/감사 메타.
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


__all__ = ["JobOwnership"]
