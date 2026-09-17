"""learner_state 테이블 — 학습 루프 진입에 필요한 **학습자 현재 상태 1행** (EOS-103).

정본 `docs/architecture/canonical_entity_model_v1.md` §2-A의 핵심 엔티티 13번 `LearnerState`의
**두 번째 좌석**이다(첫 좌석 `user_state_snapshot`은 *시점별 스냅샷 이력*). 좌석 추가는 정본
갱신을 경유했다 — `EOS-49`가 `concept_version`을 Concept의 4번째 좌석으로 편입한 선례와 동형
(`tests/backend/db/test_canonical_entity_model_freeze.py` ①·④가 기계로 대조한다).

**왜 기존 좌석을 쓰지 않는가**(실측 근거 — 판정 기준 main `265a4106`):
  - `user_state_snapshot`은 카디널리티가 *학생당 N행*(append-only 시점 사진)이고 컬럼 구성이
    종합 학력 추정(`estimated_score`·`estimated_percentile`)·시간관리·멘탈 신호다. "지금 이
    학생이 어느 교육과정의 어느 목표에 서 있는가"를 담을 자리가 없고, 담으면 *현재 상태*를
    이력 테이블에서 최신 1행 정렬로 되읽는 구조가 된다.
  - 그 좌석은 **writer 0**이다(백엔드 전수 grep — `from_schema`/`to_schema` seam 외 호출 0).
    이 모듈은 그 좌석을 **배선하지도 폐기하지도 않는다** — 그 판정은 `EOS-10`이 소유한다.

**이 테이블이 담지 않는 것**(두 번째 진실 원천 금지 — 붕괴 연쇄 "유지보수 지옥"):
  - `concept_mastery` → 정본은 `concept_mastery_history`(BKT). 여기에 복제하지 않는다.
  - `skill_mastery` → 정본은 `skill_mastery_history`. 복제하지 않는다.
  - `misconceptions` → 정본은 `misconception_hypothesis`(활성 가설). 복제하지 않는다.
  세 축은 **조립 즉시 계산**이 정본이며(`l2/learner_state.py::get_state`), 이 테이블은 그
  조립기가 알 수 없는 축 — *생산자가 아예 없던* `curriculum_id`·`current_objective_id`와
  **생성 시점**(provisioning) — 만 영속한다.

**확장 규약**(§15 동결 준수): BKT/DKT/Knowledge Tracing 확장은 *추정기*가 먼저 생기고 그
산출물의 좌석이 따로 정해진다. 이 테이블에 추정치 컬럼을 늘리는 것이 아니라, 새 축이
생산자를 얻으면 **nullable 컬럼 추가**로만 편입한다(기존 행 백필 불요 — 그래서 신규 컬럼은
전부 nullable이어야 한다). 이 규약을 `tests/backend/db/test_learner_state_orm.py`가 동결한다.

Pydantic `schema/` 상응물 없음 — DDL 유래 테이블이 아니라 이 태스크가 신설한 서버 내부 상태
테이블이다(`job_ownership`·`refresh_token_session` 방침 동일). 계약 표면은 `l2/
learner_state_store.py`의 `PersistedLearnerState`가 담당한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base

# 생성 계기(provisioning trigger) 문자열의 정본 — enum 테이블을 만들지 않는다(값 3종·확장
# 시 문자열 추가만). 관측용이지 분기용이 아니다: 코드가 이 값으로 `if`를 치면 안 된다.
PROVISIONED_BY_DIAGNOSIS_CAPTURE = "diagnosis_capture"
"""`POST /v1/me/assessments/capture`가 CAT 중단 경계(measurement_sufficient)에서 생성."""

PROVISIONED_BY_BACKFILL = "backfill"
"""운영 백필 — 이 경로로 생긴 행은 '진단 완료'를 근거로 갖지 않는다(정직 표기)."""


class LearnerStateRecord(Base):
    """학습자 현재 상태 영속 행 — 학생 1명당 **정확히 1행**(PK = learner_id).

    스냅샷이 아니라 *현재*다. 이력이 필요하면 그것은 `user_state_snapshot`(시점 사진)이나
    `*_mastery_history`(숙련 시계열)의 몫이지 이 테이블을 append-only로 쓰는 것이 아니다.

    쓰기는 `l2/learner_state_store.py`의 함수들만 한다 —
    `tests/backend/db/test_learner_state_single_writer.py`가 AST 전수 스캔으로 동결한다.
    """

    __tablename__ = "learner_state"

    # PK 겸 FK — 학생 1명당 1행. 별도 대리키(surrogate)를 두지 않는다: 두면 같은 학생에게
    # 두 행이 생기는 상태가 *표현 가능해지고*, 그 순간 "현재 상태"의 정의가 흔들린다.
    learner_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("user_profile.user_id"), primary_key=True
    )

    # ===== 생산자가 없던 축 (이 테이블이 존재하는 이유) =====
    # 교육과정 식별자 — `user_profile`에 대응 컬럼이 없어 `LearnerState` v0에서 제외됐던 필드
    # (`l2/learner_state.py` 클래스 docstring "curriculum: user_profile에 대응 컬럼이 없다").
    # FK를 걸지 않는다: 교육과정 정본이 `curriculum_framework`/`curriculum_version` 2테이블로
    # 나뉘어 있어 어느 쪽 키인지가 아직 결정되지 않았다. 결정되면 FK를 추가한다(느슨참조 →
    # 강참조는 마이그레이션 1건이고, 잘못 건 FK를 되돌리는 것보다 싸다).
    curriculum_id: Mapped[str | None] = mapped_column(sa.String(128))

    # 지금 이 학생이 서 있는 학습목표 — `learning_objective.objective_id`(String) 느슨참조.
    # FK 미적용 사유: 목표 삭제가 학생 상태 행을 막지 않아야 한다(콘텐츠 수명 ≠ 학생 수명).
    current_objective_id: Mapped[str | None] = mapped_column(sa.String(128))

    # ===== 생성·변경 계보 =====
    # 최초 생성 시각 — "진단 완료가 상태를 만들었다"의 증거. 갱신되지 않는다.
    provisioned_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    # 무엇이 이 행을 만들었는가(관측 — 위 PROVISIONED_BY_* 상수). 분기용이 아니다.
    provisioned_by: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    # 마지막 변경 시각 — 단일 쓰기 경로가 매 변경마다 갱신한다.
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    # 변경 횟수 — 단일 쓰기 경로를 **관측 가능하게** 만드는 축. 우회 쓰기가 생기면 이 값이
    # 변경 횟수와 어긋나므로, 가드 테스트가 죽어도 사후 대조가 가능하다(이중 회계).
    revision: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("1"))


__all__ = [
    "LearnerStateRecord",
    "PROVISIONED_BY_DIAGNOSIS_CAPTURE",
    "PROVISIONED_BY_BACKFILL",
]
