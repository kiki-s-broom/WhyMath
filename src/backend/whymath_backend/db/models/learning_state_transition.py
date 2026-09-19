"""LearningStateTransition 영속 ORM — 학습 상태 전이 append-only 원장 (EOS-105).

설계 정본: 계획서 300 §3 = `docs/ops/phase2_eos_closed_loop_execution_prompts.md` §P-04.

왜 "현재 상태 컬럼"이 아니라 "전이 원장"인가
--------------------------------------------
이 저장소는 학습 사실을 일관되게 **append-only 이력**으로 모델링한다(`ConceptMasteryHistory`·
`SkillMasteryHistory`·`AttemptEvent` hypertable). 상태를 `user_profile`이나
`user_state_snapshot`의 가변 컬럼 하나로 두면 두 가지를 잃는다:

  ① **왜 그 상태인가**를 잃는다. UPDATE는 직전 값을 지우므로 "이 학생은 왜 REMEDIATING에
     있었나"를 사후에 재구성할 수 없다. 전이 원장은 (from, to, trigger, rule_id)를 남긴다.
  ② **누가 바꿨는가**를 잃는다. 가변 컬럼은 어느 코드 경로든 덮어쓸 수 있어 단일 writer
     보증이 관습에 의존한다. append-only는 과거 행을 바꿀 방법 자체가 없다.

현재 상태 = 이 테이블에서 `occurred_at` 최신 행의 `to_state`이며, 행이 없으면 `NEW`다
(`l2/learning_state_machine.py::get_current_state`). 즉 현재 상태는 **파생값**이고 원장이
정본이다 — 같은 사실을 두 곳에 두지 않는다.

좌석 판정 (정본화 ≠ 집행 — 별항)
--------------------------------
이 테이블은 `user_state_snapshot`(writer 0 좌석)에도 EOS-103이 도입 중인 `learner_state`
에도 **컬럼을 추가하지 않는다**. 이유는 담는 사실이 다르기 때문이다:

  - `user_state_snapshot` = 시점별 종합 학력 추정 사진(학생당 N행, 숙달 맵·시간·멘탈 신호).
  - `learner_state`(EOS-103, PR #1185 미머지) = 학생당 1행의 현재 학습 좌표(교육과정·목표).
  - 이 테이블 = 학습 국면의 **전이 사건**(학생당 N행, 사건마다 1행).

셋 중 어느 것도 전이 사건을 담을 자리가 없고, 반대로 전이 원장에 숙달값·교육과정 좌표를
복제하지도 않는다. 좌석이 겹치지 않으므로 EOS-103과 파일·테이블 충돌이 없다(판정 기준:
main 0f12e76a에 `learner_state` 테이블 부재 — 실측).

`user_id` FK는 `user_profile.user_id`를 참조한다(다른 학생 축 테이블과 동일).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.db.models._orm_enum import _pg_enum
from whymath_backend.schema.learning_state import LearningState, TransitionTrigger


class LearningStateTransition(Base):
    """학습 상태 전이 1건 — append-only. 과거 행은 수정·삭제하지 않는다.

    `from_state`가 nullable이 아닌 이유: 최초 전이도 `NEW`에서 출발한다(상태 없음이 아니라
    `NEW`가 시작 상태다). "상태가 없는 학생"이라는 개념을 만들지 않으면 NULL 분기가 필요 없다.
    """

    __tablename__ = "learning_state_transition"

    transition_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("user_profile.user_id"), nullable=False
    )
    from_state: Mapped[LearningState] = mapped_column(
        _pg_enum(LearningState, "learning_state_enum"), nullable=False
    )
    to_state: Mapped[LearningState] = mapped_column(
        _pg_enum(LearningState, "learning_state_enum"), nullable=False
    )
    trigger: Mapped[TransitionTrigger] = mapped_column(
        _pg_enum(TransitionTrigger, "learning_state_trigger_enum"), nullable=False
    )
    rule_id: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        doc=(
            "정책 규칙 id(예: 'R3-wrong-misconception'). 정책이 낸 전이만 채워지고 "
            "생애주기 전이(진단 시작 등)는 NULL이다 — '규칙이 없었다'와 '규칙을 못 적었다'를 "
            "구분하기 위해 빈 문자열로 채우지 않는다."
        ),
    )
    concept_id: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        doc=(
            "이 전이가 일어난 맥락 개념의 의미 id(`concept.code`). FK를 걸지 않는다 — "
            "개념이 폐기·개명돼도 과거 전이 기록은 남아야 하며(append-only 원장의 요건), "
            "FK는 그 보존을 깨뜨린다."
        ),
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid,
        nullable=True,
        doc=(
            "이 전이를 유발한 `problem_attempt` 행. FK를 걸지 않는 이유는 concept_id와 같다 "
            "— 보존기한 파기로 attempt가 지워져도 전이 이력은 남는다."
        ),
    )
    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (
        # 현재 상태 조회(`user_id`로 최신 1행)가 이 테이블의 지배적 질의다.
        sa.Index(
            "idx_learning_state_transition_user_time",
            "user_id",
            sa.desc("occurred_at"),
        ),
    )
