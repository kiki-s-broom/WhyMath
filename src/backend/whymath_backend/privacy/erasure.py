"""개인정보 삭제권(R11) — 한 사용자의 *모든* 학생-연결 데이터 단일 트랜잭션 영구 삭제.

설계 정본: `docs/architecture/04a_wh1_tutoring_harness.md` §2.3 개인정보 설계 원칙(R11) — "삭제권
행사 시: student_id 기준 evidence_links → … 연쇄 삭제, BKT 상태 초기화, pgvector 임베딩 삭제까지
**한 트랜잭션 단위로**". 본 모듈은 그 *오케스트레이션 좌석*이다. 미성년자의 인지·행동 정밀
프로파일(가설·증거·BKT·θ·대화·행동 로그)을 하나의 원자적 삭제로 지운다(부분 삭제 0).

왜 앱레벨 명시 삭제인가(정직):
  레포 FK 실태(2026-06-17 전수 조사) — 학생-연결 17개 테이블 중 `evidence_links`만 user_profile
  FK `ON DELETE CASCADE`다. 나머지는 ① user_id FK가 **NO ACTION**(user_profile 삭제를 *차단*)
  이거나 ② **느슨참조**(FK 0·hypertable — user 삭제 시 *고아 잔존*)다. 따라서 user_profile 한
  행을 지우는 것만으론 삭제권이 충족되지 않는다 — 자식·고아를 *명시 삭제*해야 한다. FK 전부에
  CASCADE를 거는 대안은 대규모 마이그레이션 + 전역 삭제 의미 변경(오삭제 시 연쇄 위험)이라
  배제하고, **명시·감사 가능·마이그레이션 0**인 앱레벨 오케스트레이션을 택한다(`_ERASURE_PLAN`).

삭제 순서(FK 의존 안전·단일 트랜잭션):
  1. `dialogue`(→ `dialogue_turn` DB CASCADE) → 2. `problem_attempt` → 3. `learning_session`
  (자식 attempt는 위에서 선삭제) → 4~ 나머지 user_id/student_id 테이블(서로 의존 없음·user_profile
  만 참조) → 마지막에 `user_profile`. 같은 트랜잭션이라 어느 단계 실패도 전부 롤백(부분 삭제 0).

감사(GDPR 증빙·slice 57 동형): user_profile 삭제 *전* `DeletionAudit` 1행 적재
  (`resource_type="user_profile"`·user_id·콘텐츠 미저장). `deletion_audit`는 user FK가 없어
  사용자 삭제 후에도 *잔존*한다(compliance 로그 독립성·audit.py 설계).

저장소 패턴: `AsyncSession` 주입·**commit은 호출자**(엔드포인트 트랜잭션과 합류·flush만). 순수
ORM/쿼리빌더만(`delete(Model).where(...)` — 원시 SQL 0·CLAUDE.md). `dialogue_turn`은 user 컬럼이
없어 `dialogue` CASCADE로 제거(보고에는 cascade로 표기).

외부 store(Redis 캐시·큐 · Langfuse 트레이스 SaaS)는 RDB 밖이라 이 단일 트랜잭션에 못 넣는다 —
삭제를 *조용히 누락하지 않고* `external_erasure_targets`로 *구조화*해
`ErasureReport.pending_external`에 담는다(GDPR 범위 정직·날조 0·ops 후속 체크리스트). 실제 외부
삭제 *집행*은 후속.

매니페스트 진실성(SEC-32, 2026-09-07): 이 목록에는 **실재하는 store만** 적는다. 종전 판은 도입된
적 없는 ClickHouse·S3를 선언하면서(설정 키 0·compose 서비스 0) 정작 학생 유래 데이터가 실제로
나가는 Langfuse를 빠뜨렸다 — 양방향 오류이고, 없는 곳을 적는 쪽보다 *있는 곳을 빠뜨린* 쪽이
중대하다(외부 반출 사실 자체가 은폐된다). 선언↔실재 대조는
`tests/backend/_external_store_evidence.py` 계약이 강제한다(설정 키·compose 서비스를 실제로 조회).

범위 밖(후속): 삭제권 *요청* API 엔드포인트(인증·본인 확인·법정대리인 동의 흐름)·보존 기한 배치
(`evidence_store.purge_expired`는 retention 전용·여기는 user 단위)·외부 store 삭제 *집행*
(Redis 무효화·Langfuse 삭제 API — 현재는 `pending_external` 매니페스트로 명시만).

완전성 검사의 방향(COLLAB-02, 2026-08): 기존 `tests/backend/privacy/test_erasure.py`는 "계획된
테이블은 전부 실제 삭제 순서에 등장하는가"(계획→실행)만 단언했다 — 그 역방향("소유 컬럼을 가진
테이블인데 계획에 없는 것이 있는가", 실행→계획)은 검사되지 않아 신설 테이블의 파기 누락이 조용히
샐 수 있었다. `_ERASURE_PLAN_EXEMPTIONS`(아래)가 그 역방향 검사의 *사유 명시 허용목록*이고,
`tests/backend/privacy/test_erasure_plan_completeness.py`가 `Base.metadata.tables` 전수 스윕으로
이를 강제한다. 협업(다자 소유) 스키마의 파기 규칙은
`docs/architecture/collaboration_landing_design.md` §3(5분류·3배관 처리표·변호사 검토 대상)이
정본이다.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import CursorResult, delete
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.base import Base
from whymath_backend.db.models.activity import AttemptEvent, LearningSession, ProblemAttempt
from whymath_backend.db.models.answer_submission import AnswerSubmission
from whymath_backend.db.models.assessment import (
    AbilitySnapshot,
    Assessment,
    ConceptMasteryHistory,
    SkillMasteryHistory,
)
from whymath_backend.db.models.audit import DeletionAudit
from whymath_backend.db.models.device import DeviceCredential
from whymath_backend.db.models.dialogue import Dialogue
from whymath_backend.db.models.evidence_link import EvidenceLink
from whymath_backend.db.models.hint_usage import HintUsage
from whymath_backend.db.models.job_ownership import JobOwnership
from whymath_backend.db.models.learning_state_transition import (
    LearningStateTransition,
)
from whymath_backend.db.models.misconception_hypothesis import MisconceptionHypothesisRecord
from whymath_backend.db.models.parental_consent import ParentalConsent
from whymath_backend.db.models.refresh_token_session import RefreshTokenSession
from whymath_backend.db.models.student_solution_step import StudentSolutionStep
from whymath_backend.db.models.timeseries import DailyLearningMetrics, UserBehaviorMetrics
from whymath_backend.db.models.user import (
    UserPersonaHistory,
    UserProfile,
    UserStateSnapshot,
    UserTrackHistory,
)
from whymath_backend.schema.enums import AuditResourceType

__all__ = [
    "ErasureReport",
    "ExternalErasureTarget",
    "erase_user",
    "external_erasure_targets",
]

# 삭제 계획 — (모델, user 컬럼명) child→parent 순서(FK 의존 안전). user_profile·dialogue_turn
# 제외: user_profile은 마지막에 명시 삭제, dialogue_turn은 dialogue CASCADE로 자동 제거.
#   · dialogue 먼저(→ dialogue_turn cascade) · problem_attempt 먼저(learning_session보다).
#   · 나머지는 user_profile만 참조(상호 의존 0)라 순서 무관.
_ERASURE_PLAN: tuple[tuple[type[Base], str], ...] = (
    (Dialogue, "user_id"),  # → dialogue_turn DB CASCADE
    # EOS-32: attempt CASCADE 자식이나 user_id 직접 보유 — 명시 삭제로 보고 일관(EvidenceLink
    # 선례). problem_attempt보다 먼저(attempt→submission CASCADE 역순 방지·자식 우선).
    (AnswerSubmission, "user_id"),
    # EOS-45: 힌트 사용 이력 — answer_submission과 동형(attempt CASCADE 자식·자식 우선).
    (HintUsage, "user_id"),
    # EOS-46: 학생 풀이 step — 같은 계열(attempt CASCADE 자식·자식 우선·ADR-002).
    (StudentSolutionStep, "user_id"),
    (ProblemAttempt, "user_id"),  # learning_session보다 먼저(session→attempt CASCADE 역순 방지)
    (LearningSession, "user_id"),
    (AttemptEvent, "user_id"),  # 느슨참조·hypertable(고아 방지)
    (Assessment, "user_id"),
    (ConceptMasteryHistory, "user_id"),  # BKT 숙달·느슨참조·hypertable
    (SkillMasteryHistory, "user_id"),  # 스킬 숙달·느슨참조·hypertable
    (AbilitySnapshot, "user_id"),  # IRT θ·느슨참조
    (DailyLearningMetrics, "user_id"),  # 느슨참조·hypertable
    (UserBehaviorMetrics, "user_id"),  # 느슨참조·hypertable
    (MisconceptionHypothesisRecord, "user_id"),  # 활성 오개념 가설
    (EvidenceLink, "student_id"),  # 증거 그래프(user CASCADE이나 명시 삭제로 보고 일관)
    (DeviceCredential, "user_id"),
    (RefreshTokenSession, "user_id"),
    (JobOwnership, "user_id"),  # SEC-27: 비동기 QUALITY 작업 소유권·느슨참조(job_id FK 아님)
    (ParentalConsent, "user_id"),
    (UserTrackHistory, "user_id"),
    (UserPersonaHistory, "user_id"),
    (UserStateSnapshot, "user_id"),
    # EOS-105: 학습 상태 전이 원장 — 학생의 학습 국면 이력(느슨참조·user_id 실 FK).
    # 삭제권 대상인 이유: "이 학생이 언제 교정 국면에 있었는가"는 미성년 학습자의 학습
    # 기록 그 자체이며, 익명 통계가 아니라 user_id로 직접 지목되는 행이다.
    (LearningStateTransition, "user_id"),
)

# COLLAB-02 방향 역전 — 소유 컬럼(user_id·student_id·target_user_id)을 가졌지만 *정당하게*
# `_ERASURE_PLAN` 밖에 있어야 하는 테이블의 사유 명시 허용목록. 무사유 예외는 금지(CLAUDE.md).
# `tests/backend/privacy/test_erasure_plan_completeness.py`가 `Base.metadata.tables` 전수에서
# 소유 컬럼 보유 테이블을 스윕해 이 두 집합(_ERASURE_PLAN ∪ 아래 허용목록) 밖의 테이블을 red로
# 잡는다 — 기존 test_erasure.py:94 `test_covers_all_planned_tables`(계획→실행, planned <= order)의
# *역방향*(실행→계획, 소유 테이블 중 계획 누락 검출)이다.
#
# 분류 근거: `docs/architecture/collaboration_landing_design.md` §2.2(소유 축 5분류) — 여기 등재된
# 모든 테이블은 **E형(감사)** 또는 `user_profile`(별도 명시 삭제) 둘 중 하나다. 미래 협업 스키마가
# 만드는 B형(학생 기여+타인 컨테이너)·C형(교차 사용자 집계)·D형(조직 소유) 테이블도 같은 방식으로
# 이 상수에 사유와 함께 등재하거나, `_ERASURE_PLAN`에 편입해야 한다(같은 문서 §3 다자 소유 규칙).
_ERASURE_PLAN_EXEMPTIONS: dict[str, str] = {
    "user_profile": (
        "user_id가 PK 자체 — `_ERASURE_PLAN` 튜플이 아니라 `erase_user()`가 자식 삭제 전부가 "
        "끝난 뒤 마지막에 명시적으로 `delete(UserProfile)...`한다(FK 의존 안전 순서, 위 삭제 순서 "
        "주석 참조). 계획 튜플에 없다고 파기 누락이 아니다 — 코드에서 항상 실행된다."
    ),
    "deletion_audit": (
        "GDPR 삭제 증빙 append-only 로그(`privacy/audit.py` `DeletionAudit`) — user_id는 FK가 "
        "*아닌* plain UUID로 설계돼 있다. 사용자 삭제 *후*에도 잔존해야 삭제 사실 자체를 증빙할 수 "
        "있다(지우면 증빙이 함께 사라져 목적이 무너진다). 협업 5분류(E형 감사)와 동형."
    ),
    "privacy_audit": (
        "SEC-09 개인정보 감사(반출·동의변경·관리자접근·역할변경) append-only 로그"
        "(`privacy/audit.py` "
        "`PrivacyAudit`) — user_id·target_user_id 둘 다 FK가 아닌 plain UUID. deletion_audit와 "
        "동일 근거로 계정 삭제 후에도 잔존해야 감사 목적을 달성한다. 협업 5분류(E형 감사)와 동형."
    ),
}


class ExternalErasureTarget(BaseModel):
    """`erase_user`가 *직접 삭제하지 않는* 외부 store의 사용자 데이터 — 별도 ops 삭제 대상. 불변.

    `erase_user`는 PostgreSQL(`_ERASURE_PLAN`)만 단일 트랜잭션으로 지운다. 외부 store(Redis
    캐시·큐, Langfuse 트레이스 SaaS)는 RDB 밖·별도 클라이언트/전송 인프라라 그 트랜잭션에
    *포함되지 않는다*. 이 모델은 그 누락을 *조용히 넘기지 않고*(날조 0·GDPR 삭제 범위 정직) ops가
    집행할 체크리스트로 *구조화*한다. `locator`는 *정확한 키 문법을 단정하지 않는다* — 키/프리픽스
    규약은 인프라 정의라 user_id 연관 대상을 서술만 한다(없는 사실 날조 금지). 나아가 **user 단위
    특정이 애초에 불가능한 store는 그 사실 자체를 locator에 적는다**(SEC-32) — "지울 수 있다"는
    인상만 남기고 실제로는 못 지우는 체크리스트가 가장 위험하다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    store: str = Field(description="외부 store 식별자(redis·langfuse).")
    data: str = Field(description="그 store가 보유한 사용자 데이터 설명(한국어).")
    locator: str = Field(description="삭제 대상(user_id 연관·키 규약은 인프라 정의·단정 아님).")
    reason: str = Field(description="`erase_user` 단일 TX에 *포함되지 않는* 이유.")


def external_erasure_targets(user_id: uuid.UUID) -> tuple[ExternalErasureTarget, ...]:
    """이 사용자에 대해 외부 store에 남아 *별도 삭제가 필요한* 데이터 목록(per-user·구조화).

    `erase_user`의 PostgreSQL 단일 트랜잭션 *밖*에 있는 store들을 명시한다 — 삭제 범위를 정직히
    드러내(GDPR·날조 0) ops/후속 오케스트레이터가 집행하게 한다. 순수 함수(외부 호출 0)·locator는
    *키 문법을 단정하지 않고* user_id 연관 대상만 서술한다(인프라 키 규약 날조 금지).
    """
    uid = str(user_id)
    # 여기서 뺀 것 — ClickHouse(행동 로그)·S3/MinIO(객체 저장소)는 **아직 도입되지 않았다**
    # (설정 키 0·compose 서비스 0·SDK 0 · 2026-09-07 실측). CLAUDE.md 스택 표는 Neo4j·Wolfram
    # 처럼 *계획된 미도입*을 "미도입" 병기로 남기지만, 그 표는 아키텍처 서술이고 이쪽은 **집행
    # 체크리스트**다 — 없는 store를 적으면 ops는 지울 수 없는 항목을 받고, 법적 독자는 "학생
    # 행동 로그가 ClickHouse에 있다"는 거짓 사실을 읽는다. 그래서 목록에서는 빼고 사유만 여기
    # 남긴다. 도입하는 날 이 주석과 매니페스트·계약 상수를 함께 갱신하라
    # (`tests/backend/_external_store_evidence.py` KNOWN_UNDEPLOYED_STORES).
    return (
        ExternalErasureTarget(
            store="redis",
            data=(
                "LLM 응답 캐시(학생 프롬프트로 생성된 응답 본문)·QUALITY 비동기 큐 payload"
                "(prompt·system 원문). 레이트리밋·디바이스 캐시는 배포 기본값에서 비활성"
                "(coach_rate_limit_backend=memory·device_store_mode=none)이라 제외."
            ),
            locator=(
                f"user_id={uid}의 요청에서 파생되나 *user_id로 조회할 키가 없다* — 캐시 키는 "
                "(프롬프트·시스템·티어) 해시이고(l3/router.cache_key_for) 큐 payload에도 user "
                "축이 없다(l3/pipeline._build_async_payload). 선택 삭제 불가·TTL 만료가 실질 경로."
            ),
            reason="캐시·브로커는 RDB 밖·별도 클라이언트 무효화 — 단일 TX 불포함.",
        ),
        ExternalErasureTarget(
            store="langfuse",
            data=(
                "L3 라우팅 결정 트레이스(`l3_routing` 이벤트) — 티어·모델·토큰·비용·지연·결정 "
                "사유 등 *결정 메타데이터*. 프롬프트·응답 *본문*은 보내지 않는다"
                "(l3/router.langfuse_fields 필드 표가 전송 범위의 정본)."
            ),
            locator=(
                f"user_id={uid}의 학습 요청에서 생성되나 학생 연결 축은 `student_id_hash` 하나뿐"
                "이고 그마저 *이미 해시된 값*이라 원시 user_id로 조회되지 않는다. 더구나 현행 "
                "서빙 경로는 그 필드를 채우지 않아(전달 호출부 0건·2026-09-07 실측) 지금 적재된 "
                "트레이스는 user 단위 특정 자체가 성립하지 않는다 — 삭제 요청은 기간·프로젝트 "
                "단위로만 가능하다."
            ),
            reason=(
                "외부 SaaS로 전송되는 별도 저장소(기본 호스트 cloud.langfuse.com·`langfuse_host`"
                "로 자체 호스팅 가능) — 삭제는 Langfuse API/보존 정책으로 별도 집행."
            ),
        ),
    )


class ErasureReport(BaseModel):
    """삭제권 실행 결과 — 사용자 + 테이블별 삭제 행수(감사·검증·엔드포인트 응답). 불변(frozen).

    `deleted_counts`는 명시 삭제한 테이블별 행수다(`dialogue_turn`은 DB CASCADE라 비가시·미포함).
    `user_profile_deleted`는 최종 user_profile 삭제 여부(존재했으면 1·이미 없으면 0).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: uuid.UUID = Field(description="삭제 대상 사용자 id.")
    deleted_counts: dict[str, int] = Field(
        description="명시 삭제한 테이블(tablename)별 행수(dialogue_turn은 CASCADE라 미포함)."
    )
    user_profile_deleted: int = Field(
        ge=0, description="user_profile 삭제 행수(1=존재했음·0=이미 없음)."
    )
    total_rows_deleted: int = Field(ge=0, description="명시 삭제 총 행수(user_profile 포함).")
    pending_external: tuple[ExternalErasureTarget, ...] = Field(
        default=(),
        description=(
            "이 트랜잭션이 *삭제하지 않은* 외부 store 대상(Redis·Langfuse). RDB 밖이라 "
            "단일 TX에 못 넣어 *별도 ops 삭제*가 필요하다 — 누락을 조용히 넘기지 않고(날조 0·GDPR "
            "범위 정직) 후속 집행 체크리스트로 남긴다. 정보 누출 방지로 응답엔 미노출(ops만)."
        ),
    )


async def erase_user(session: AsyncSession, *, user_id: uuid.UUID) -> ErasureReport:
    """사용자의 *모든* 학생-연결 데이터를 단일 트랜잭션으로 영구 삭제(개인정보 삭제권·R11).

    `_ERASURE_PLAN` 순서로 각 테이블을 `delete(...).where(user컬럼 == user_id)`로 지우고(자식→부모),
    `DeletionAudit` 1행을 적재한 뒤(GDPR 증빙·콘텐츠 미저장) 마지막에 `user_profile`을 삭제한다.
    `dialogue_turn`은 `dialogue` 삭제에 DB CASCADE로 함께 제거된다(user 컬럼 없음). **commit은
    호출자**(flush로 같은 트랜잭션 가시화) — 어느 단계 실패도 전부 롤백돼 *부분 삭제가 없다*.

    멱등성: 이미 없는 사용자면 모든 삭제가 0행이고 `user_profile_deleted=0`(에러 없이 무해 종료).
    감사 행은 user_profile이 실재했든 아니든 적재된다(삭제 *시도* 증빙). 순수 ORM/쿼리빌더만.
    """
    counts: dict[str, int] = {}
    for model, column in _ERASURE_PLAN:
        result = await session.execute(delete(model).where(getattr(model, column) == user_id))
        counts[model.__tablename__] = cast("CursorResult[Any]", result).rowcount or 0

    # GDPR 삭제 증빙 — user_profile 삭제 *전* 적재(user FK 없어 사용자 삭제 후에도 잔존·콘텐츠 0).
    session.add(
        DeletionAudit(
            user_id=user_id,
            resource_type=AuditResourceType.user_profile.value,
            resource_id=user_id,
        )
    )

    profile_result = await session.execute(
        delete(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile_deleted = cast("CursorResult[Any]", profile_result).rowcount or 0

    await session.flush()  # 같은 트랜잭션 가시화(commit은 호출자).

    return ErasureReport(
        user_id=user_id,
        deleted_counts=counts,
        user_profile_deleted=profile_deleted,
        total_rows_deleted=sum(counts.values()) + profile_deleted,
        # RDB 밖 store는 이 TX가 못 지운다 — 누락을 구조화해 후속 ops 삭제 체크리스트로 남긴다.
        pending_external=external_erasure_targets(user_id),
    )
