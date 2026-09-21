"""WH-1 학습 증거 그래프(`evidence_links`) ORM 모델 — 증거→가설 엣지(설계 04a §2.3·§3 도구7).

설계 정본: `docs/architecture/04a_wh1_tutoring_harness.md` §2.3(학습 증거 그래프)·§3 도구7
(`log_evidence`). 개별 학습 이벤트가 어떤 *오개념 가설*을 지지(+1)/반박(−1)하는지 기록하는 엣지
테이블이다. 이 테이블 하나로 "이 학생이 이차함수를 못 푸는 진짜 원인은 인수분해 노드"라는 진단이
LLM 추론이 아닌 **SQL 조회**로 나온다(학부모 리포트 신뢰 근거).

★개인정보 설계(04a §2.3 v0.2·R11·CLAUDE.md 절대 금기 대조): 증거 그래프는 *미성년자의 인지·행동
정밀 프로파일*에 해당하는 **민감 학생 데이터**다. 본 모델은 그 원칙을 스키마에 못박는다:
  - **삭제권 연쇄**: `student_id`는 `user_profile.user_id` FK **`ON DELETE CASCADE`** — 학생 삭제
    시 증거가 자동 연쇄 삭제된다(삭제권 행사·"나중에 붙이기 어려우므로 1차 마이그레이션 포함"이
    설계 요구). `idx_evidence_student_mid`(student_id 선행)가 삭제권 조회를 받친다.
  - **보존 기한**: `retention_until`(졸업+1년 등 정책) 경과 레코드는 야간 배치로 자동 파기
    (`evidence_store.purge_expired`). `idx_evidence_retention`이 배치 스캔을 받친다.
  - **평문 적정**: 본 테이블은 *식별자·극성·가중치·날짜*만 담고 자유텍스트 PII가 없다(학생 풀이
    원문·채팅은 별도·암호화 대상). `misconception_hypothesis`(민감 학생 데이터·평문) 동일 방침 —
    암호화·redaction 불요·문서화로 민감도 명시.

참조 결정(설계 SQL ↔ 레포 실재 정합):
  - `student_id`(UUID NOT NULL·**FK user_profile ON DELETE CASCADE**) — 삭제권 핵심.
  - `session_id`(UUID NOT NULL·**FK 아님**·느슨참조) — 세션 맥락. 삭제는 student_id 연쇄가 덮는다.
  - `event_id`(BIGINT nullable·**FK 아님**·느슨참조) — 설계의 `learning_events(event_id)`는 레포에선
    `attempt_event`(복합 PK `(event_id, event_at)`)라 단일 컬럼 FK가 불가 → 느슨참조(삭제는
    student 연쇄가 덮음). 설계 `learning_events` 명칭과 1:1 매핑 부재를 정직 표기.
  - `misconception_id`(TEXT NOT NULL·**FK 아님**) — 설계의 `misconceptions(id)`는 레포에선 *인코드
    카탈로그*(`l4/misconception/catalog.CATALOG_BY_ID`)라 DB 테이블 부재 → `evidence_store`
    가 카탈로그 대조로 참조 무결성을 강제(`misconception_hypothesis.misconception_id` 동형 방침).
  - `node_id`(TEXT nullable·**FK 아님**·느슨참조) — 설계의 `curriculum_nodes(id)`(INT 545노드)는
    레포에 부재(개념그래프는 `concept_id` TEXT `{TRACK}-{AREA}-{NNN}`)·개념 identity 유동 →
    느슨 TEXT 참조(activity.py `target_concept_id` 비-FK 선례·§6~§9 DDL 비REFERENCES 패턴).
  - `polarity`(SMALLINT NOT NULL·CHECK ∈ {−1,+1}) — +1 지지·−1 반박. DB CHECK + 스토어 이중 가드.
  - `weight`(REAL nullable) — verify/PRM 기반 가중치(미평가 None). `retention_until`(DATE nullable).
  - `link_id`(BIGSERIAL PK) — 증거는 이벤트 볼륨이라 BIGINT autoincrement(설계 BIGSERIAL·
    `attempt_event` 선례). DB-assigned(`gen_random_uuid` 없음).

범위 밖(후속): `curate_hypothesis`(증거→가설 세트 갱신·감쇠·ε-규칙·하네스)·BKT 초기화·pgvector
삭제까지의 *단일 트랜잭션 삭제 오케스트레이션*(deletion_audit 연계)·`select_probe`. 본 모듈은
*증거 엣지 스키마*만 둔다.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.schema.evidence_link import EvidenceLink as SchemaEvidenceLink


class EvidenceLink(Base):
    """WH-1 학습 증거 엣지 영속 ORM — §2.3 `evidence_links`.

    한 행 = 한 학습 이벤트가 한 학생(`student_id`)의 한 오개념(`misconception_id`) 가설을
    `polarity`(+1 지지/−1 반박)로 지지/반박한다는 증거. `student_id`만 실 FK(삭제권 CASCADE)이고
    나머지 참조(session/event/node)는 느슨참조다(모듈 docstring — 설계↔레포 정합).
    """

    __tablename__ = "evidence_links"

    # ===== 기본 식별 (BIGSERIAL — 이벤트 볼륨·DB-assigned) =====
    link_id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)

    # ===== 학생·세션 (삭제권 연쇄의 축) =====
    # 세션 맥락 — FK 아님(느슨참조). 삭제는 student_id CASCADE가 덮는다.
    session_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    # ★삭제권 핵심 — user_profile FK ON DELETE CASCADE. 학생 삭제 시 증거 자동 연쇄 삭제.
    student_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("user_profile.user_id", ondelete="CASCADE"),
        nullable=False,
    )

    # ===== 증거 본문 (§2.3) =====
    # 학습 이벤트 — FK 아님(attempt_event 복합 PK라 단일 FK 불가·느슨참조). 미연결 시 None.
    event_id: Mapped[int | None] = mapped_column(sa.BigInteger)
    # 오개념 카탈로그 id — FK 아님(인코드 카탈로그). evidence_store가 CATALOG_BY_ID 대조로 무결성.
    misconception_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 커리큘럼 노드(concept_id) — FK 아님(느슨 TEXT 참조·개념 identity 유동). 맥락 없으면 None.
    node_id: Mapped[str | None] = mapped_column(sa.Text)
    # 극성 — +1 지지·−1 반박(CHECK ∈ {−1,+1}).
    polarity: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    # verify/PRM 기반 가중치 — 미평가 None.
    weight: Mapped[float | None] = mapped_column(sa.Float)
    # 증거의 *출처*(어떤 코드 경로가 무엇을 근거로 이 엣지를 썼는가) — MISC-20.
    # **`weight`로 출처를 추론하지 않는다**: `weight`는 nullable이고(미평가 None) WH-1 하네스의
    # `LogEvidenceAction.weight`는 **LLM이 지정**할 수 있다. 즉 가중치는 "누가 왜 썼는가"를
    # 말해 주지 못한다 — 그것으로 "학생이 오개념을 넘어섰다"를 판정하면 LLM이 숫자 하나로
    # 해소를 선언하게 되고, NULL(미평가=모름)을 강한 신호로 접는 순간 *모른다*가 *확정*이 된다.
    # 기계가 확인한 사실만 값으로 남기고, 모르면 NULL로 둔다(해소율 분자에서 제외).
    provenance: Mapped[str | None] = mapped_column(sa.Text)
    # 보존 기한(졸업+1년 등 정책) — 경과 시 야간 배치 파기. 미설정 None.
    retention_until: Mapped[date | None] = mapped_column(sa.Date)

    # ===== 운영 메타 =====
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    __table_args__ = (
        # 극성 이중 가드(DB CHECK + 스토어 검증) — +1/−1만.
        sa.CheckConstraint("polarity IN (-1, 1)", name="ck_evidence_links_polarity"),
        # 삭제권 조회(student_id 선행) + 가설-증거 진단 조인((student, misconception)).
        sa.Index("idx_evidence_student_mid", "student_id", "misconception_id"),
        # 보존 기한 야간 배치 파기 스캔.
        sa.Index("idx_evidence_retention", "retention_until"),
    )

    def to_schema(self) -> SchemaEvidenceLink:
        """영속 ORM → `schema.EvidenceLink`(Pydantic 검증 복원·열람권 export JSON-safe 직렬화).

        parental_consent·audit 동일 패턴 — 매핑 컬럼키만 추려 검증 복원(UUID·datetime·date를
        `model_dump(mode="json")`로 JSON 안전). 본 테이블은 PII 없는 식별자·신호라 redaction 0.
        """
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaEvidenceLink.model_validate(data)


__all__ = ["EvidenceLink"]
