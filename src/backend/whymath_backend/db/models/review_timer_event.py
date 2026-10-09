"""ReviewTimerEvent 영속 ORM(`review_timer_event`) — HIT 검수 타이머 이벤트 저장소 (EOS-54).

설계 정본: `docs/standards/eos_verification_design_v1.md` §6 — HIT(CU당 인간 개입 시간·주 기준
KPI)의 측정 방법 "검수 타이머 이벤트(시작·종료·중단) 전수 자동 수집"의 영속 계층. 검증 Pydantic
정본은 `schema/review_timer.py` — 본 모듈은 *영속 스키마*만 둔다(EOS-45 `hint_usage.py` 관례).

**append-only**(EOS-45/46 관례): 이벤트는 사실 기록 — UPDATE 경로 없음·정정은 새 이벤트로.

영속 매핑 결정(근거 병기):
  - `event_id` UUID PK `gen_random_uuid()` (hint_usage 동형).
  - `review_session_id` UUID **NOT NULL** — 세션(sitting) 페어링 축. FK 아님(세션 정본 테이블
    없음 — writer가 발급하는 상관 id·FK 날조 금지).
  - `cu_slug` TEXT **NOT NULL** — CU 식별 축(코퍼스 JSONL·워크리스트·problem.slug 공통).
    폭 128 강제는 schema(max_length=128 = problem.slug String(128) 일치)·DB는 TEXT 좌석
    (hint_usage.hint_id 동형 — 폭은 schema가 강제).
  - `problem_id` UUID **nullable FK → problem.problem_id** — 적재된 CU만 채운다.
    needs_review 후보는 problem 행이 없어(적재 전) NOT NULL FK면 검수 기록 자체가 불가 =
    스키마가 측정 실패를 제조한다. `GenerationLog.problem_id`(같은 생산 계측 로그 계열)와
    동형: nullable·ondelete 지정 없음(NO ACTION).
  - `reviewer_id` TEXT NOT NULL — 검수 *행위자* 핸들. **학생 소유 축 아님**: privacy 스윕
    (`test_erasure_plan_completeness` — (A) FK 산출물 ∪ (B) 계획 파생 이름 ∪ (C) 학생 세션 축)이
    이 테이블을 소유로 잡지 않음을 실측 확인(green)했다. (A)·(B)는 이 테이블에 `user_profile.
    user_id` FK도 `_ERASURE_PLAN`이 쓰는 컬럼명도 없어 *구조적으로* 안 걸린다. **(C)는 다르다** —
    `review_session_id`가 (C)의 이름 절(`*_session_id`)에 *걸린다*. 그런데 이 컬럼은 검수자 세션
    (sitting) 상관 id이지 학생 학습 세션이 아니라서, 그 파일의 `NON_STUDENT_SESSION_COLUMNS`
    (`("review_timer_event", "review_session_id")`)에 사유와 함께 *제외*돼 있다. 즉 초록은 "안
    걸려서"가 아니라 "걸렸으나 사유 있게 제외돼서"다 — 그 제외가 사라지면 이 테이블이 삭제권
    스윕에서 RED가 된다(`test_non_student_session_columns_are_excluded_and_the_exclusion_is_
    load_bearing`가 동결). 보존 파기 완전성 가드(SEC-41)는 같은 소유 판정을 재사용하므로 같은
    결론이다. 그 파일 주석이 created_by·approved_by류를 "콘텐츠
    저작/검수 행위자"로 명시 분류한다. 따라서 erasure/retention/export 3종 배선 **불요** —
    학생 축 컬럼 부재는 `test_review_timer_event_orm.py`가 RPT-01(`test_defect_report_no_
    user_id.py`) 선례로 동결한다.
  - `event_type`/`verdict`/`failure_code` TEXT — 폐쇄 강제는 schema(3종/2종/F1~F8 enum)·DB는
    값만 담는다(`hint_usage.hint_level`·`answer_submission.response_type` 동형).
  - `elapsed_ms` INTEGER **nullable** — None=미측정(계측 실패 — **server_default 0 날조 금지**·
    acceptance ④). 집계(`ops/hit_cu_metrics`)가 미계측을 분리 카운트한다.
  - `occurred_at` TIMESTAMPTZ nullable — 검수 도구 신고 *발생* 시각(EOS-48 발생/수신 분리·
    None=미신고). `recorded_at` TIMESTAMPTZ **NOT NULL `server_default now()`** — *수신* 시각
    (시간 필터·주간 창 집계 축. NOT NULL이라 시각 미상 행 없음).

인덱스: `(review_session_id)` — 세션 페어링 조인. `(cu_slug, recorded_at DESC)` — CU 단위
HIT 집계·최근순(hint_usage `(user_id, requested_at DESC)` 동형).

집행 별항(정본화≠집행 — acceptance ③): 서버 쪽 집행은 ADMIN-18이 `api/admin_bff.py`에 건다 —
approve/reject 전이는 `review_session_id` 없이 422, 반려는 `failure_code` 없이 422, 성공 시 같은
트랜잭션에 finished 행을 이 테이블에 적재하고(`from_schema`) 적재가 실패하면 상태 변경도 롤백한다.
검수 화면의 착수·판정 호출 결선은 웹 쪽 절반이다. 이 테이블·writer·CLI 자체는 저장소와 함수 레벨
계약까지만 집행한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.schema.review_timer import ReviewTimerEvent as SchemaReviewTimerEvent


class ReviewTimerEvent(Base):
    """검수 타이머 이벤트 영속 ORM — `review_timer_event`(append-only·recorded_at 순서).

    한 행 = 검수 세션(`review_session_id`) 안에서 CU(`cu_slug`)에 일어난 시작/종료/중단 사건
    1건. CU당 HIT 집계·적재율("작동한 비율") 리포트의 원천 — 소비는 `ops/hit_cu_metrics`.
    """

    __tablename__ = "review_timer_event"

    # ===== 기본 식별 =====
    event_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    # 세션 페어링 축 — FK 아님(세션 정본 테이블 부재·상관 id·FK 날조 금지).
    review_session_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)

    # ===== 검수 대상 CU =====
    # 폭 128 강제는 schema — DB는 TEXT 좌석(hint_usage.hint_id 동형).
    cu_slug: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 적재된 CU만 채움(미적재 후보는 NULL) — GenerationLog.problem_id 동형(nullable FK).
    problem_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("problem.problem_id")
    )

    # ===== 검수 행위자 (학생 소유 축 아님 — 모듈 docstring 판정) =====
    reviewer_id: Mapped[str] = mapped_column(sa.Text, nullable=False)

    # ===== 이벤트 내용 — 폐쇄 강제는 schema·DB는 값만 =====
    event_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    verdict: Mapped[str | None] = mapped_column(sa.Text)
    failure_code: Mapped[str | None] = mapped_column(sa.Text)
    failure_note: Mapped[str | None] = mapped_column(sa.Text)

    # ===== 시간·계측 =====
    # NULL = 미측정(0 날조 금지 — server_default 없음·acceptance ④).
    elapsed_ms: Mapped[int | None] = mapped_column(sa.Integer)
    # 발생/수신 분리(EOS-48) — occurred_at=도구 신고 발생(미신고=NULL), recorded_at=수신.
    occurred_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    # ── 인덱스 ──
    __table_args__ = (
        sa.Index("idx_review_timer_session", "review_session_id"),
        sa.Index("idx_review_timer_cu", "cu_slug", sa.desc("recorded_at")),
    )

    # ── 변환 헬퍼 (schema↔db seam, hint_usage.py 패턴) ────────────────────
    @classmethod
    def from_schema(cls, schema: SchemaReviewTimerEvent) -> ReviewTimerEvent:
        """검증된 `schema.ReviewTimerEvent` → 영속 ORM(mapper 컬럼키 필터).

        `recorded_at=None`(schema 기본 — DB가 채움)은 kwargs에서 *제외*한다 — 명시적 None
        할당은 NULL INSERT가 되어 NOT NULL 위반이고, 속성 미설정이어야 `server_default now()`
        가 적용된다(EOS-45 `requested_at` 동형).
        """
        if schema.content_fingerprint is not None:
            # EOS-27: 지문은 JSONL 매체(검수 CLI → 각인 도구 → 승격 게이트)에서만 운반된다 — DB 컬럼
            # 좌석이 없다. 아래 mapped_keys 필터가 조용히 버리면 "지문을 저장했다고 믿는" 소비자가
            # 생긴다(침묵 실패). 좌석 신설(마이그레이션 + 프로브)은 후속 태스크(EOS-174)이므로
            # 그때까지 크게 거부한다.
            raise ValueError(
                "content_fingerprint는 review_timer_event에 컬럼 좌석이 없다 — 영속하면 지문이 "
                "조용히 소실된다(EOS-27: JSONL 매체 한정)"
            )
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        if kwargs.get("recorded_at") is None:
            kwargs.pop("recorded_at", None)  # server_default now() 적용(명시 NULL 금지)
        return cls(**kwargs)

    def to_schema(self) -> SchemaReviewTimerEvent:
        """영속 ORM → `schema.ReviewTimerEvent`(Pydantic 재검증 — 교차 필드 계약 안전망)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaReviewTimerEvent.model_validate(data)


__all__ = ["ReviewTimerEvent"]
