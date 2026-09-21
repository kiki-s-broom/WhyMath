"""도메인4 학습 활동(Activity) ORM 모델 (SQLAlchemy 2.0 영속 레이어).

설계 정본: `schemas/v1.0/schema_v1.0.md` §6.1(`learning_session`·`problem_attempt`·
`attempt_event` DDL 3테이블)·§6.1 인덱스. 이 ORM은 `schema/activity.py`(Pydantic, 검증·API)와
*별도*로 세운 영속 매핑이며 `from_schema`/`to_schema` 변환 헬퍼가 둘을 잇는다(배치1
`problem.py`·`user.py` 동일 패턴 — SQLModel 미사용).

타입 매핑(DDL → ORM, problem.py/user.py 선례 그대로):
  - `UUID PRIMARY KEY` → `server_default gen_random_uuid()`(배치1 모든 UUID PK 선례).
  - `UUID REFERENCES`(nullable FK) → `uuid.UUID|None` + FK(예: user_id→user_profile,
    session_id→learning_session, problem_id→problem).
  - `UUID`(REFERENCES 없음) → `uuid.UUID|None`(*FK 아님* — DDL에 REFERENCES 절이 없는
    `target_concept_id`·`stuck_at_concept_id`. concept_fusion.concept_ids가 배열이라 FK가
    아니었던 것과 달리, 여기선 *DDL이 REFERENCES를 명시하지 않은* 느슨참조다).
  - `BIGSERIAL`(시계열 PK) → `mapped_column(sa.BigInteger, primary_key=True,
    autoincrement=True)` — DB가 INSERT 시 할당하는 정수 PK(UUID PK와 달리 gen_random_uuid
    server_default를 두지 않는다). `attempt_event.event_id`에서만 사용.
  - `TIMESTAMPTZ NOT NULL`(복합 PK 구성요소) → required `datetime` + `primary_key=True`
    (예: attempt_event.event_at — `user.py` UserPersonaHistory.detected_at 선례).
  - `session_type_enum`/`attempt_mode_enum`/`event_type_enum` → `_pg_enum(...)`(신규 PG 타입).
  - `device_enum`(device_used) → `_pg_enum(Device, "device_enum")` — *배치1 user.py가 이미
    정의한 PG 타입을 동일 name으로 공유*한다(중복 정의 X, 메타데이터상 같은 타입). 공유 enum의
    create_type 처리는 마이그레이션(메인) 몫.
  - `DECIMAL(p,s)` → `Mapped[float|None] = mapped_column(sa.Numeric(p, s))`(focus/engagement).
  - `BOOLEAN`(기본값 없음) → `bool|None`(미응답=NULL 구분 — `user.py` 선례; is_correct·
    used_socratic 등).
  - `JSONB`(자유형) → `JSONB`(ocr_result·event_data); schema가 default_factory=list인 JSONB
    배열(step_times) → problem.py conditions_parsed처럼 `nullable=False, server_default
    "'[]'::jsonb"`.
  - `VARCHAR(n)`(enum 아님) → `sa.String(n)`(network_type).
  - 인덱스(§6.1 CREATE INDEX) → `__table_args__`; 부분 인덱스(idx_attempt_stuck WHERE
    stuck_at_concept_id IS NOT NULL) → `postgresql_where=sa.text(...)`.

개인정보 메모(CLAUDE.md 절대 금기·개인정보보호법, `user.py`·`concept.py` 방침과 동일):
  `problem_attempt`의 `student_answer`·`handwriting_uri`·`ocr_result`는 *미성년 학생 풀이
  데이터*다. 평문 저장 금지·동의 없는 학습 사용 금지는 *저장·동의 계층*(암호화·미들웨어·
  검수) 책임이며, ORM에는 컬럼만 두고 가짜 CHECK를 만들지 않는다(schema.activity 모듈
  docstring·problem.py 본문 미보유 불변식 방침과 동형 — 문서화만).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.db.models._orm_enum import _pg_enum
from whymath_backend.schema.activity import AttemptEvent as SchemaAttemptEvent
from whymath_backend.schema.activity import LearningSession as SchemaLearningSession
from whymath_backend.schema.activity import ProblemAttempt as SchemaProblemAttempt
from whymath_backend.schema.enums import (
    AttemptMode,
    Device,
    EventType,
    SessionType,
)


# ──────────────────────────────────────────────────────────────────────────
# 핵심: LearningSession (§6.1 learning_session — 앱 진입~종료 한 단위)
# ──────────────────────────────────────────────────────────────────────────
class LearningSession(Base):
    """학습 세션 영속 ORM — §6.1 `learning_session`(앱 진입~종료 한 단위).

    PK `session_id`만 있고 나머지는 nullable/기본값(DDL 그대로). `user_id`→user_profile FK.
    `target_concept_id`는 §6.1 DDL에 `REFERENCES`가 없어 *FK가 아니다*(느슨참조 — schema
    docstring 정합). `device_used`는 배치1 user.py가 정의한 `device_enum` PG 타입을 공유한다.
    """

    __tablename__ = "learning_session"

    # ===== 기본 식별 =====
    session_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("user_profile.user_id")
    )

    # ===== 시간 =====
    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(sa.Integer)

    # ===== 세션 유형·목표 =====
    session_type: Mapped[SessionType | None] = mapped_column(
        _pg_enum(SessionType, "session_type_enum")
    )
    # REFERENCES 없음 → FK 아님(느슨참조).
    target_concept_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)

    # ===== 진행 카운트 =====
    problems_attempted: Mapped[int | None] = mapped_column(sa.Integer)
    problems_completed: Mapped[int | None] = mapped_column(sa.Integer)
    problems_correct: Mapped[int | None] = mapped_column(sa.Integer)

    # ===== 세션 품질 신호 =====
    focus_score: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    engagement_score: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))

    # ===== 실측 활동/공백 시간 (EOS-48 — 32_learning_history §7) =====
    # `duration_seconds`(경과 elapsed)와 *별개 축*: 자리 비움이 섞인 경과를 학습 시간으로 쓰지
    # 않기 위한 실측 좌석. 클라 heartbeat 등 실측 신호가 있을 때만 적재하고 NULL=미측정
    # (0 날조 금지·ended_at-started_at 승격 백필 금지). 롤업은 기존 daily_active_minutes
    # (경과 기반)를 *재정의하지 않고* 병행 지표(measured)로만 소비한다.
    active_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    idle_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    # ===== 환경 (device_used는 배치1 device_enum 공유) =====
    device_used: Mapped[Device | None] = mapped_column(_pg_enum(Device, "device_enum"))
    # VARCHAR(20) — enum 아닌 자유 문자열(schema network_type 선례).
    network_type: Mapped[str | None] = mapped_column(sa.String(20))

    # ── 인덱스 (§6.1 CREATE INDEX — started_at DESC) ──
    __table_args__ = (sa.Index("idx_session_user", "user_id", sa.desc("started_at")),)

    # ── 변환 헬퍼 (schema↔db seam, problem.py 패턴) ──────────────────────
    @classmethod
    def from_schema(cls, schema: SchemaLearningSession) -> LearningSession:
        """검증된 `schema.LearningSession` → 영속 ORM(mapper 컬럼키 필터)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaLearningSession:
        """영속 ORM → `schema.LearningSession`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaLearningSession.model_validate(data)


# ──────────────────────────────────────────────────────────────────────────
# 핵심: ProblemAttempt (§6.1 problem_attempt — 한 문제 풀이 1단위, 특성 #96)
# ──────────────────────────────────────────────────────────────────────────
class ProblemAttempt(Base):
    """문항 풀이 시도 영속 ORM — §6.1 `problem_attempt`(특성 #2/#39/#42/#95/#96).

    PK `attempt_id`만 있고 나머지는 nullable/기본값(DDL 그대로). FK 3개:
    `user_id`→user_profile·`session_id`→learning_session·`problem_id`→problem. 단,
    `stuck_at_concept_id`는 §6.1 DDL에 `REFERENCES`가 없어 *FK가 아니다*(느슨참조).

    개인정보 메모(모듈 docstring 참조): `student_answer`·`handwriting_uri`·`ocr_result`는
    *미성년 풀이 데이터*다. 저장·동의 계층 책임이라 ORM에는 컬럼만 두고 가짜 CHECK를 만들지
    않는다(schema.activity 방침과 동형 — 문서화만).
    """

    __tablename__ = "problem_attempt"

    # ===== 기본 식별 =====
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("user_profile.user_id")
    )
    # slice 56: 세션 삭제(GDPR) 시 자식 attempt 함께 제거 — ON DELETE CASCADE.
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("learning_session.session_id", ondelete="CASCADE")
    )
    problem_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("problem.problem_id")
    )

    # ===== 시간 =====
    # 실측(EOS-48): started_at/ended_at은 *클라이언트 신고* 발생 시각(schema Optional — 클라가
    # 채우는 운영 메타), created_at은 server_default지만 from_schema 경유 덮어쓰기가 가능해
    # 수신 시각을 *보장*하지 않는다 — 그래서 아래 ingested_at(서버 전용 좌석)을 분리한다.
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(sa.Integer)
    # EOS-48: 서버 *수신* 시각 — 오프라인 sync에서 발생(started_at)과 수신이 벌어지는 것을
    # 구분한다. NULL=미기록(EOS-48 도입 이전 기존 행 — server_default가 없었을 때라 정직하게
    # 비어 있다). SEC-33 ⑥: 이후 이 컬럼이 `privacy/retention`의 COALESCE 폴백 좌석이 되므로
    # server_default를 부여했다(19149e92d368 — 신규 INSERT가 값을 생략해도 서버 시각으로
    # 채워진다·기존 NULL 행은 SET DEFAULT가 건드리지 않아 날조 없음). 두 writer(api/me.py·
    # api/coach.py)가 여전히 명시적으로 `received_at`을 채우므로 이 기본값은 *셋째 writer가
    # 생략했을 때만* 발동하는 안전망이다.
    ingested_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()
    )
    # EOS-48: 실측 활동/공백 시간(초) — 클라 heartbeat 등 *실측 신호가 있을 때만* 적재
    # (32_learning_history §7 "측정된 것만 적재"). NULL=미측정(0 날조 금지 — ended_at-started_at
    # 을 active로 승격하는 백필 금지·EOS-45 view_duration_ms 판정과 동형).
    active_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    idle_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    # ===== 결과 (기본값 없는 BOOLEAN → 미채점=NULL) =====
    is_correct: Mapped[bool | None] = mapped_column(sa.Boolean)
    # *미성년 풀이 데이터* — 평문 저장 금지는 저장계층 책임(모듈 docstring).
    student_answer: Mapped[str | None] = mapped_column(sa.Text)
    # SEC-31: 학생 답안 at-rest 봉투 암호화(AES-256-GCM) — 마스터 키(DB 밖·env)로 암호화된 본문 +
    # 96-bit nonce. 둘 다 NULL이면 평문(student_answer) 행. dialogue_turn.content_encrypted/
    # content_nonce 선례 미러(schema round-trip 제외 — `_NON_SCHEMA_COLUMNS`).
    student_answer_encrypted: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)
    student_answer_nonce: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)
    confidence_self_reported: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))

    # ===== 풀이 방식 (특성 #96) =====
    attempt_mode: Mapped[AttemptMode | None] = mapped_column(
        _pg_enum(AttemptMode, "attempt_mode_enum")
    )
    used_socratic: Mapped[bool | None] = mapped_column(sa.Boolean)
    used_hint: Mapped[bool | None] = mapped_column(sa.Boolean)
    used_solution_view: Mapped[bool | None] = mapped_column(sa.Boolean)

    # ===== 풀이 이미지/PDF (특성 #95) — *미성년 풀이 데이터* =====
    handwriting_uri: Mapped[str | None] = mapped_column(sa.Text)
    # SEC-31: 손글씨 URI at-rest 봉투 암호화 — student_answer와 같은 등급·같은 키(student_work).
    handwriting_uri_encrypted: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)
    handwriting_uri_nonce: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)
    ocr_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # SEC-31: OCR 결과(JSONB)는 **결정론 JSON 직렬화 후** 암호화(dialogue_turn.image_analysis
    # 선례 — sort_keys=True·ensure_ascii=False). SEC-04: none_as_null=True는 원본 컬럼에 이미
    # 적용됨(위) — 암호화 컬럼 자체는 스칼라 bytes라 해당 없음.
    ocr_result_encrypted: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)
    ocr_result_nonce: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)

    # ===== 막힌 지점 분석 =====
    stuck_at_step: Mapped[int | None] = mapped_column(sa.Integer)
    # REFERENCES 없음 → FK 아님(느슨참조).
    stuck_at_concept_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)

    # ===== 시간 관리 =====
    time_vs_expected: Mapped[float | None] = mapped_column(sa.Numeric(4, 2))

    # ===== 풀이 단계별 시간 (특성 #42) — schema default_factory=list → NOT NULL JSONB =====
    step_times: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB(none_as_null=True), nullable=False, server_default=sa.text("'[]'::jsonb")
    )

    # ===== 운영 메타 =====
    created_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    # ── 인덱스 (§6.1 CREATE INDEX — idx_attempt_stuck은 부분 인덱스) ──
    __table_args__ = (
        sa.Index("idx_attempt_user", "user_id", sa.desc("started_at")),
        sa.Index("idx_attempt_problem", "problem_id"),
        sa.Index(
            "idx_attempt_stuck",
            "stuck_at_concept_id",
            postgresql_where=sa.text("stuck_at_concept_id IS NOT NULL"),
        ),
        # EOS-32(PR #902 P1): answer_submission의 복합 FK (attempt_id, user_id) 참조 대상.
        # attempt_id가 PK라 이 UNIQUE는 논리적으로 중복이지만, PG는 복합 FK가 가리키는 컬럼
        # 조합에 유일성 보장(UNIQUE/PK)을 요구한다 — 참조 대상 좌석용 표준 패턴(값 제약 추가
        # 효과는 0·기존 행 무영향).
        sa.UniqueConstraint("attempt_id", "user_id", name="uq_problem_attempt_attempt_user"),
    )

    # SEC-31: schema round-trip에서 제외하는 봉투 암호화 컬럼(schema는 extra="forbid"라 이 키가
    # model_validate에 들어가면 실패). 복호는 handler/헬퍼 층이 담당하고(순수 seam에 cipher
    # 미주입), schema 필드엔 복호된 평문을 별도 설정한다. ciphertext는 API·export에 노출하지
    # 않는다(dialogue_turn._NON_SCHEMA_COLUMNS 동형).
    _NON_SCHEMA_COLUMNS = frozenset(
        {
            "student_answer_encrypted",
            "student_answer_nonce",
            "handwriting_uri_encrypted",
            "handwriting_uri_nonce",
            "ocr_result_encrypted",
            "ocr_result_nonce",
        }
    )

    @classmethod
    def from_schema(cls, schema: SchemaProblemAttempt) -> ProblemAttempt:
        """검증된 `schema.ProblemAttempt` → 영속 ORM(schema↔db seam).

        암호화 컬럼(student_answer_encrypted 등)은 schema에 없어 여기서 설정되지 않는다 —
        handler/헬퍼 층이 student_answer 등을 암호화해 채운다(dialogue_turn._build_dialogue_turn
        패턴 동형).
        """
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaProblemAttempt:
        """영속 ORM → `schema.ProblemAttempt`(Pydantic 검증 복원).

        봉투 암호화 컬럼은 `_NON_SCHEMA_COLUMNS`로 제외(schema extra="forbid"·ciphertext 비노출).
        암호화 행은 student_answer 등이 NULL이므로 handler/헬퍼 층이 복호값을 schema 필드에
        덮어쓴다(예: `privacy/export.py`).
        """
        mapped_keys = {
            col.key
            for col in sa.inspect(type(self)).mapper.column_attrs
            if col.key not in self._NON_SCHEMA_COLUMNS
        }
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaProblemAttempt.model_validate(data)


# ──────────────────────────────────────────────────────────────────────────
# 핵심: AttemptEvent (§6.1 attempt_event — 실시간 단계 이벤트)
# ──────────────────────────────────────────────────────────────────────────
class AttemptEvent(Base):
    """학생 풀이 단계 이벤트 영속 ORM — §6.1 `attempt_event`(실시간 분석용 시계열).

    복합 PK `(event_id, event_at)` — DDL 제약. `event_id`는 `BIGSERIAL`이라 DB가 INSERT 시
    할당하는 정수 PK(autoincrement; UUID PK와 달리 gen_random_uuid server_default 없음).
    `event_at`은 `TIMESTAMPTZ NOT NULL`이라 required(복합 PK 구성요소).

    `attempt_id`·`user_id`·`problem_id`는 §6.1 DDL에 `REFERENCES`가 없어 *FK가 아니다*
    (hypertable 느슨참조 — schema docstring 정합). 운영 시 이 테이블은 TimescaleDB
    hypertable로 변환되나(`event_at` 1일 청크), *그 변환은 마이그레이션 레벨*이라 ORM에서는
    일반 테이블로 둔다(hypertable 관련 코드를 ORM에 넣지 않는다).
    """

    __tablename__ = "attempt_event"

    # ===== 복합 PK (event_id, event_at) =====
    # BIGSERIAL → BigInteger autoincrement PK(DB-assigned, gen_random_uuid 없음).
    event_id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    # EOS-48 실측 명문화: 전 writer(api/coach.py·interactions.py)가 `datetime.now(UTC)` 서버
    # 시각을 넣는다 — 즉 event_at의 실측 의미는 **서버 수신(기록) 시각**(ingested)이다.
    # 소비자(롤업 `_fetch_events` 귀속·`_RETENTION_PLAN` 파기·하네스 지표 스캔)도 이 의미로
    # 읽어 왔다. 재정의하지 않는다(hypertable 파티션 키 — ADR-001 추기).
    event_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), primary_key=True)
    # EOS-48: 클라이언트 신고 *발생* 시각 — 오프라인 태블릿이 하루 뒤 sync하면 event_at(수신)과
    # 벌어진다. NULL=미신고(기존 writer·기존 행 무영향 — 백필 금지: 수신 시각 복제는 날조).
    # 귀속 계약(발생 우선·미래 신고=시계 왜곡은 수신 폴백)은 l2.learning_metrics_rollup.
    # effective_event_moment가 정본.
    event_time: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    # ===== FK 아님 (REFERENCES 없음 — hypertable 느슨참조) =====
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)
    problem_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)

    # ===== 이벤트 내용 =====
    event_type: Mapped[EventType | None] = mapped_column(_pg_enum(EventType, "event_type_enum"))
    event_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))

    # ===== 해소된 스킬 배열 (EOS-57 — W2 되돌릴 수 없는 스키마 ①) =====
    # 채점 확정 시 `l2.skill_mastery_tracking`이 concept→skill로 해소한 스킬 id 배열
    # (`skill_node` PK = Text `skill.<slug>`·assessment.SkillMasteryHistory.skill_id 동형).
    # REFERENCES 없음 → FK 아님(hypertable 느슨참조 — 이 테이블의 기존 3 참조 컬럼과 동형).
    #
    # **nullable + server_default 없음**이 이 좌석의 핵심 계약이다(EOS-48 비파괴 규약 동형):
    #   - NULL  = 미기록 — 구판 이벤트, 또는 이 축을 쓰지 않는 다른 event_type(검산결과 등).
    #   - `{}`  = 해소를 *실행했으나* 매핑 0건(concept→skill 브리지 미보유 문항).
    # 둘을 구분하지 않으면 "writer가 안 돌았다"와 "돌았는데 0건이다"가 같은 글자로 보인다
    # (S3-07 None≠0 규약 · CLAUDE.md "작동한 비율" 원칙의 데이터 전제). `'{}'::text[]`
    # server_default를 달면 기존 행 전체가 "해소 0건"으로 백필되는 날조라 달지 않는다.
    skill_ids: Mapped[list[str] | None] = mapped_column(ARRAY(sa.Text), nullable=True)

    @classmethod
    def from_schema(cls, schema: SchemaAttemptEvent) -> AttemptEvent:
        """검증된 `schema.AttemptEvent` → 영속 ORM(schema↔db seam).

        `event_id`는 BIGSERIAL(DB-assigned)이라 schema에서 None일 수 있다 — 그 경우 생성자에
        넘기지 않으면 ORM 인스턴스 속성은 None이고, INSERT 시 DB가 채운다(autoincrement).
        """
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaAttemptEvent:
        """영속 ORM → `schema.AttemptEvent`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaAttemptEvent.model_validate(data)


__all__ = ["LearningSession", "ProblemAttempt", "AttemptEvent"]
