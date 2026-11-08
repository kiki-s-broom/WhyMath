"""개념 상태 변경 기록 + 학생 노출 기록 — PED-17 A1.

두 테이블: `concept_state_transition`(상태 변경)·`concept_exposure_event`(학생 노출).

C안(조건부 개방)의 안전장치 6번 "모든 노출을 기록한다"와 "누가 언제 상태를 바꿨는가"의 영속
좌석이다.
B6 공개 관문·C작업(킬스위치)·D작업(감사·카나리·단계적 공개)이 이 두 테이블을 읽고 쓴다.

────────────────────────────────────────────────────────────────────────────
concept_state_transition — 추가 전용(UPDATE·DELETE·TRUNCATE를 DB 트리거가 거부)
────────────────────────────────────────────────────────────────────────────
`learning_state_transition`(EOS-105)과 같은 "전이 사건 원장" 형태지만 **관례가 아니라 DB가 막는다**.
지시문이 "추가만 하고 수정·삭제는 막는다"를 요구했고, 이 원장은 회수 사유와 변경 주체를 사후에
증명하는 증거라 코드 경로가 아니라 DB 수준에서 불변이어야 한다(트리거 =
`whymath_concept_state_transition_append_only`, 리비전 `b1a4d7c92e05`).

- `concept_code`에 FK를 걸지 않는다. 개념 행이 사라져도 과거 전이 기록은 남아야 한다(원장의 요건 ·
  `learning_state_transition.concept_id` 선례). 이 원장 자체는 학생 정보가 없어 보존기한 파기
  대상이 아니다.
- `from_state`가 NULL인 행은 **최초 부여**다(`via='최초 부여'`). 마이그레이션이 기존 행에 상태를
  처음
  매길 때 남기는 행이며, 허용 전환 5쌍에 없는 가짜 이력(예: 초안→공개됨)을 만들지 않으려고 NULL로
  둔다.
- `changed_by_kind`는 규칙(rule)·에이전트(agent)·Kiki(kiki) 중 하나, `changed_by_name`은 그 이름
  (규칙 이름 · 에이전트 이름 · 'Kiki'). **DB는 'kiki'라는 자기 신고를 검증하지 못한다** — 위조
  방어는
  이 좌석의 책임이 아니며 전환 함수가 "긴급 정지는 kiki만"을 거부 규칙으로 걸 뿐이다(한계).

────────────────────────────────────────────────────────────────────────────
concept_exposure_event — 수정만 막고 삭제는 막지 않는다 (의도적 비대칭)
────────────────────────────────────────────────────────────────────────────
학생이 어떤 개념을 언제 보았는가의 기록이다. UPDATE는 막는다(`ai_label_shown`을 사후에 고쳐 "라벨을
보여 줬다"로 바꿀 수 없어야 한다). **DELETE는 막지 않는다.** 이 테이블은 (가명이라도) 학생 학습
기록이라
보존기한 파기·삭제 요청 같은 법령 유래 절차(CLAUDE.md "법령 유래 절차의 기계 대체 금지")가 행을
지워야
할 수 있기 때문이다. 이 파기 배선은 A1 범위 밖이며 보고서의 "다음 작업이 알아야 할 것"에 적었다.

- `student_pseudonym`은 **키드 해시(HMAC-SHA256 hexdigest 64자)** 다. 실제 이름도, 원본 `user_id`도
  저장하지 않는다. DB CHECK가 소문자 16진 64자만 받으므로 UUID(36자)·이메일·이름이 실수로 들어오면
  쓰기 시점에 거부된다. 서버가 같은 `user_id`로 해시를 재계산하면 학생 단위 조회·삭제가 가능하다.
- `ai_label_shown`은 **그 응답이 실제로 AI 라벨을 담았는가**의 사실이다. 기본값이 없다(NOT NULL) —
  호출자가 반드시 명시해야 하고, 모르면 거짓으로 적는다(없는 라벨을 있다고 적지 않는다).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base

# 상태 어휘를 CHECK 문자열로 인라인한다 — 마이그레이션 리비전과 같은 값이어야 하며, 어긋나면
# `tests/backend/db/test_concept_lifecycle_migration_integration.py`가 실패한다.
_STATE_VOCAB = "'초안', '검증됨', '공개됨', '회수됨'"
_VIA_VOCAB = (
    "'B6 공개 관문', 'D4 AI 카나리', 'D5 단계적 공개', 'D2 AI 감사', 'D6', "
    "'킬스위치', '회수 기능', '긴급 정지', '재생성', '최초 부여'"
)


class ConceptStateTransition(Base):
    """개념 상태 변경 1건 — 추가 전용 원장. 과거 행은 수정·삭제하지 않는다(DB 트리거)."""

    __tablename__ = "concept_state_transition"

    transition_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    # 느슨참조 — FK 없음(위 모듈 docstring). 값 = concept_content.code.
    concept_code: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # NULL = 최초 부여(via='최초 부여'). 그 외에는 허용 전환 5쌍의 출발 상태.
    from_state: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    to_state: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 변경 주체 — 종류(rule|agent|kiki)와 이름(규칙 이름·에이전트 이름·'Kiki').
    changed_by_kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    changed_by_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 어느 작업·기능이 바꿨는가(B6 공개 관문·D4·D5·킬스위치·긴급 정지 등). 전환표 검증의 증거다.
    via: Mapped[str] = mapped_column(sa.Text, nullable=False)
    reason: Mapped[str] = mapped_column(sa.Text, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    __table_args__ = (
        # 한 개념의 이력 조회(회수 사유 확인·감사)가 지배적 질의다.
        sa.Index("ix_concept_state_transition_concept_changed", "concept_code", "changed_at"),
        sa.CheckConstraint(
            f"from_state IS NULL OR from_state IN ({_STATE_VOCAB})",
            name="from_state",
        ),
        sa.CheckConstraint(f"to_state IN ({_STATE_VOCAB})", name="to_state"),
        sa.CheckConstraint(
            "changed_by_kind IN ('rule', 'agent', 'kiki')",
            name="changed_by_kind",
        ),
        sa.CheckConstraint("length(btrim(changed_by_name)) > 0", name="changed_by_name"),
        sa.CheckConstraint(f"via IN ({_VIA_VOCAB})", name="via"),
        # 최초 부여(출발 상태 없음)와 경로 '최초 부여'는 한 쌍이다 — 어느 한쪽만 있는 행을 막는다.
        sa.CheckConstraint(
            "(from_state IS NULL) = (via = '최초 부여')",
            name="initial_pair",
        ),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="reason"),
    )


class ConceptExposureEvent(Base):
    """학생 노출 1건 — 어떤 개념을 언제 보았는가.

    UPDATE는 DB가 막고 DELETE는 허용한다(위 모듈 docstring 참조).
    """

    __tablename__ = "concept_exposure_event"

    exposure_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    # 학생이 실제로 본 `concept_content` 행의 code(역조회면 요청 원자 code가 아니라 서빙 행 code).
    concept_code: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 키드 해시(HMAC-SHA256 hexdigest) — 이름·원본 user_id 미저장. CHECK가 형식을 강제한다.
    student_pseudonym: Mapped[str] = mapped_column(sa.Text, nullable=False)
    exposed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    # 이 응답이 AI 라벨을 담았는가. 기본값 없음 — 호출자가 사실을 명시한다.
    ai_label_shown: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)

    __table_args__ = (
        # 개념별 노출 집계(24시간 판정·킬스위치 회수 대상 학생 조회)가 지배적 질의다.
        sa.Index("ix_concept_exposure_event_concept_exposed", "concept_code", "exposed_at"),
        sa.CheckConstraint(
            "student_pseudonym ~ '^[0-9a-f]{64}$'",
            name="pseudonym_format",
        ),
    )


__all__ = ["ConceptExposureEvent", "ConceptStateTransition"]
