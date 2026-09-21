"""활성 오개념 *가설* per-student 영속(`misconception_hypothesis`) ORM — SQLAlchemy 2.0.

설계 정본: `docs/architecture/04a_wh1_tutoring_harness.md` §8.4 **2단계**(WH-1 소크라테스
튜터링 하네스 — "활성 가설 세트(감쇠·ε-규칙) + evidence_links"). 직전 슬라이스(#191)가
순수 결정 로직(`l4/misconception/hypothesis.py` — `MisconceptionHypothesis` Pydantic·`decay`·
`reinforce`·`update_hypotheses`·`select_focus`)을 만들었고, 본 모듈은 그 *활성 가설 세트를
per-student 영속*하는 테이블 좌석이다. 순수 로직은 *재사용*만 하고(재구현 0), 저장소
(`l4/misconception/hypothesis_store.py`)가 ORM 행 ↔ 순수 Pydantic을 잇는다.

**이름 충돌 회피**: 순수 Pydantic은 `hypothesis.py:MisconceptionHypothesis`. 본 ORM은
혼동을 막으려 **`MisconceptionHypothesisRecord`**(테이블 `misconception_hypothesis`)로
명명한다 — 순수 모델 ≠ 영속 레코드.

영속 매핑 컨벤션(배치1 `problem.py`·`activity.py`·`solution_node.py` 선례 답습):
  - `UUID PRIMARY KEY` → `server_default gen_random_uuid()`(모든 UUID PK 선례).
  - `user_id`(nullable FK to `user_profile.user_id`) → `activity.py`의 학생 데이터 FK 동형.
  - per-student per-오개념 1행 — `(user_id, misconception_id)` **유니크 제약**으로
    저장소가 upsert(있으면 갱신·없으면 insert)한다.
  - `confidence`(Numeric(3,2)) → `activity.py`의 focus/engagement DECIMAL(3,2) 동형([0,1]).
  - `turns_since_evidence`·`evidence_count` → 순수 모델 동명 필드의 영속 사본
    (server_default로 신규 행 기본값을 박는다 — 0·1).
  - `is_active`(Boolean NOT NULL·server_default true) → 가지치기(stale 가설 정리·낙인 방지)
    시 *행을 지우지 않고* false로 비활성화한다(증거 이력 보존·`get_active_hypotheses`가 활성만
    로드). 한 번 의심된 오개념이 *영속 라벨*로 따라다니지 않게 하는 #191 원칙의 영속판.
  - `created_at`/`updated_at`(TIMESTAMPTZ NOT NULL·server_default now()·updated_at onupdate)
    → 운영 메타(`solution_node.py` 선례).

개인정보 메모(CLAUDE.md 절대 금기·개인정보보호법, `activity.py` 방침과 동형):
  활성 오개념 가설은 *미성년 학생*에 결부된 **민감 학생 데이터**다(per-student 진단 후보).
  평문 저장 금지·동의 없는 학습 사용 금지는 *저장·동의 계층*(암호화·미들웨어·PIPA 권한
  매트릭스) 책임이며, ORM에는 컬럼만 두고 *가짜 CHECK를 만들지 않는다*(activity.py
  `student_answer` 등과 동형 — 불변식을 ORM에 위장하지 않고 문서화만). 오개념은 *후보일 뿐*
  확정 라벨이 아니므로(낙인 금지) `is_active`로 stale 가설을 비활성화해 관리한다.

범위 밖(후속 — 정직 스코프): `evidence_links`(증거→가설 연결 테이블·학생 풀이 증거·암호화·
동의·PIPA 권한 매트릭스)·coach/intervention 파이프라인 결선(가설→개입 발화)·진단-실제
오개념 *일치율* 게이트 측정·API 엔드포인트 노출은 모두 후속 슬라이스다. 본 모듈은 *가설
영속 스키마*만 둔다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.schema.misconception_hypothesis import (
    MisconceptionHypothesisRecord as SchemaMisconceptionHypothesisRecord,
)


class MisconceptionHypothesisRecord(Base):
    """활성 오개념 가설 per-student 영속 레코드 — §8.4 2단계 `misconception_hypothesis`.

    한 행 = 한 학생(`user_id`)의 한 오개념(`misconception_id`) 가설이다. 저장소가
    `(user_id, misconception_id)` 유니크 제약으로 upsert하고, 가지치기 대상은 `is_active=false`로
    비활성화한다(행 삭제 X — 증거 이력 보존·낙인 방지).

    민감 학생 데이터(모듈 docstring 참조): per-student 오개념 후보다. 평문 저장·동의 없는 학습
    사용 금지는 *저장·동의 계층* 책임이라 ORM에는 컬럼만 두고 가짜 CHECK를 만들지 않는다
    (activity.py 패턴 동형 — 문서화만).
    """

    __tablename__ = "misconception_hypothesis"

    # ===== 기본 식별 =====
    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    # 민감 학생 데이터 — user_profile FK(activity.py 학생 데이터 FK 동형·nullable).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("user_profile.user_id")
    )
    # 카탈로그 오개념 id(`Misconception.id` — kebab-case 문자열). FK 아님(카탈로그는 코드 정본).
    misconception_id: Mapped[str] = mapped_column(sa.Text, nullable=False)

    # ===== 가설 신뢰·증거 (순수 모델 동명 필드의 영속 사본) =====
    # 가설의 *현재* 신뢰([0,1]) — 증거 없으면 감쇠·새 증거에 강화(순수 로직이 계산).
    confidence: Mapped[float] = mapped_column(sa.Numeric(3, 2), nullable=False)
    # 마지막 증거(매치) 이후 경과 턴 — 신규 가설은 0(server_default).
    turns_since_evidence: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    # 이 가설을 지지한 누적 증거 수 — 신규 가설은 1에서 시작(server_default).
    evidence_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("1")
    )

    # ===== 활성 플래그 (가지치기 = 비활성화·삭제 X) =====
    # 가지치기된(임계 미만·결과 세트에서 빠진) 가설은 false로 비활성화(stale 정리·낙인 방지).
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())

    # MISC-20 (b) — 비활성화 *사유*(`l4.misconception.hypothesis.DeactivationReason` 값).
    # `is_active=false` 단일 신호로는 "학생이 실제로 넘어섬(해소)"과 "감쇠·반박·캡절단으로 조용히
    # 빠짐"을 구분할 수 없어 ⑩ 오개념 해소율이 근사에 머물렀다(R2 §2 G4). 이 컬럼이 서면 RESOLVED만
    # 분자로 세는 정직한 해소율이 가능해진다.
    #   · **NULL = 사유 미상**이며 두 경우에 남는다: ⓐ 활성 행(빠진 적 없음) ⓑ 사유를 모르는 경로가
    #     비활성화한 행(하네스 결과 세트 영속 `persist_hypotheses`).
    #     **과거 행 백필은 하지 않는다** —
    #     이미 비활성화된 행의 사유는 복원 불가능한 정보이며, 날조 대신 NULL로 두고
    #     분자에서 제외한다
    #     (정직 회계 · 04e §9-D4 명시).
    #   · CHECK 제약을 두지 않는다 — 값 집합은 애플리케이션(Enum)이 소유하고 ORM에 불변식을
    #     위장하지 않는다(이 모듈 상단 방침·`activity.py` 선례와 동형).
    deactivated_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    # ===== 운영 메타 =====
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    # ── 제약·인덱스 ──
    __table_args__ = (
        # per-student per-오개념 1행 — upsert 충돌 키.
        sa.UniqueConstraint(
            "user_id", "misconception_id", name="uq_misconception_hypothesis_user_mid"
        ),
        # 학생별 활성 가설 로드(`get_active_hypotheses`) 접근 경로.
        sa.Index("idx_misconception_hypothesis_user_active", "user_id", "is_active"),
    )

    def to_schema(self) -> SchemaMisconceptionHypothesisRecord:
        """영속 ORM → `schema.MisconceptionHypothesisRecord`(검증 복원·열람권 export JSON-safe).

        parental_consent 동일 패턴 — 매핑 컬럼키만 추려 검증 복원(UUID·datetime·Numeric→float를
        `model_dump(mode="json")`로 JSON 안전). 자유텍스트 PII 없는 식별자·신호·날짜라 redaction 0.
        """
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaMisconceptionHypothesisRecord.model_validate(data)


__all__ = ["MisconceptionHypothesisRecord"]
