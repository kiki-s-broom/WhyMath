"""학습 활동 PII 시계열 보존 파기 — `evidence_links` 외 *타 PII 테이블* 무기한 보존 차단.

`evidence_store.purge_expired`(증거 그래프·`retention_until` 기반)는 evidence_links만 다룬다.
그러나 *학습 활동 데이터*(대화·세션·시도·평가·시계열 지표)도 무기한 보존되면 GDPR 데이터
최소화 위반이다(미성년 학습 로그). 이 모듈은 그 테이블들을 *타임스탬프 기준*으로 파기한다 —
`timestamp < (as_of − pii_retention_years)`인 행을 지운다(retention_until 컬럼이 없으므로 적재
시각으로 만료를 계산).

설계(삭제권 `privacy.erasure` 패턴 답습):
  - `AsyncSession`을 *주입*받고 **commit은 호출자**(어느 단계 실패도 전부 롤백 — 부분 파기 0).
  - **순수 ORM/쿼리빌더만**(`delete(Model).where(ts < cutoff)`·원시 SQL 0).
  - 플랜은 삭제권 `_ERASURE_PLAN`의 *학습 데이터 시계열 부분집합*을 **child→parent** 순서로
    (FK 안전·session→attempt CASCADE 역순 방지). **계정/인증/동의/가설 테이블은 제외** — 보존
    의미가 다르다(토큰 자가만료·동의는 법적 증빙 보존·계정 상태는 현재값). evidence_links는
    `purge_expired`(retention_until)가 별도 처리(중복 0).

정직 스코프: NULL 타임스탬프(미시작 세션 등)는 `ts < cutoff`가 NULL이라 *파기 대상 아님*
(보수적). 테이블별 차등 보존기한·졸업일 기반 정밀 보존은 후속(현 균일 `pii_retention_years`).

SEC-33 — `ProblemAttempt`만 예외: 클라가 `started_at`을 신고하지 않으면(NULL) 위 정직 스코프가
그 행을 *영원히* 파기 대상에서 빼는 회피 통로가 된다(started_at은 클라 재량 — 신고 자체를
생략하면 미래값 검증(`api/me.py::submit_attempt`의 422 가드)조차 우회한다). 그래서 이 테이블만
`COALESCE(started_at, ingested_at)`을 파기 기준으로 쓴다 — `ingested_at`은 서버가 수신 시각
그대로 채우는 값이라 클라가 조작할 수 없다(⑥: `server_default`로 세 번째 writer의 누락까지
방어 — `db/models/activity.py` 참조). 미신고 행은 *발생*이 아니라 *수신* 기준으로 파기되므로
보수성이 살짝 낮아지지만(오프라인 sync로 발생이 훨씬 과거인 행이 조금 늦게 파기될 뿐 — 방향은
항상 "덜 지운다"), 무기한 잔존보다 안전하다. `started_at`·`ingested_at`이 둘 다 NULL인 행
(EOS-48 도입 이전 레거시)은 여전히 파기 대상이 아니다 — 그 소급 처리는 게이트
`G-attempt-retention-purge-backfill-decision`(법령 유래 판단·Kiki 소유)의 몫이며 이 모듈은
그 행에 손대지 않는다(신규 회피 통로만 닫는다).

감사 2테이블 의도적 제외 — 무기한 보존의 *명문화된* 침묵 (ADMIN-03):
  `deletion_audit`(`DeletionAudit`)·`privacy_audit`(`PrivacyAudit`, `db/models/audit.py`)는
  이 `_RETENTION_PLAN`에도, 삭제권 `_ERASURE_PLAN`에도 **의도적으로 넣지 않는다**. 두 테이블은
  "언제·누가·무엇을 지웠는가/반출했는가"의 **법정 증빙(compliance evidence)** 성격이라, 학습 활동
  PII와 달리 *즉시 파기 대상이 아니다* — 오히려 지우면 삭제·반출 사실 자체를 증빙할 수 없어 목적이
  무너진다(그래서 `user_id`가 FK 아닌 plain UUID라 계정 삭제 후에도 잔존한다 — `audit.py` 설계
  메모). 삭제권 쪽에는 이 제외 사유가 `erasure.py`의 `_ERASURE_PLAN_EXEMPTIONS`에 이미 사유와
  함께 등재돼 있으나, 보존 파기(retention) 쪽에는 그 결정이 코드·문서 어디에도 없어 *사실상
  무기한 보존이 침묵으로 남아* 있었다 — 이 문단이 그 공백을 정직하게 명문화한다.
  다만 이 제외는 "영원히 보존한다"는 확정이 **아니다**. 감사 로그의 최종 **보존 연한은 미확정**
  이며, 그 확정은 법령(개인정보보호법) 유래 판단이라 **MGMT-02(이용약관·개인정보처리방침 변호사
  검토) 회신이 선행**한다(CLAUDE.md 「법령 유래 절차의 기계 대체 금지」 — 연한을 코드가 임의로
  정하지 않는다). 연한이 확정되면 그때 별도 태스크로 감사 전용 파기 경로를 배선한다 — 이 모듈에는
  지금 그 로직·연한 숫자를 넣지 않는다. 이 제외는 `tests/backend/privacy/
  test_audit_retention_exclusion.py`가 동결한다(감사 2테이블이 `_RETENTION_PLAN`에 없음).
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast

from sqlalchemy import ColumnElement, CursorResult, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.config import get_settings
from whymath_backend.db.base import Base
from whymath_backend.db.models.activity import AttemptEvent, LearningSession, ProblemAttempt
from whymath_backend.db.models.answer_submission import AnswerSubmission
from whymath_backend.db.models.assessment import (
    AbilitySnapshot,
    Assessment,
    ConceptMasteryHistory,
    SkillMasteryHistory,
)
from whymath_backend.db.models.dialogue import Dialogue
from whymath_backend.db.models.hint_usage import HintUsage
from whymath_backend.db.models.student_solution_step import StudentSolutionStep
from whymath_backend.db.models.timeseries import (
    DailyLearningMetrics,
    ProblemSolveTimeDistribution,
    UserBehaviorMetrics,
)

__all__ = ["purge_expired_records", "retention_cutoff"]

# 보존 파기 플랜 — (모델, 타임스탬프 컬럼명). child→parent 순서(FK 안전·`_ERASURE_PLAN` 미러).
# dialogue→dialogue_turn·learning_session→problem_attempt는 DB CASCADE라 부모 파기가 자식
# 동반 제거(자식 타임스탬프 무관). attempt_event·시계열 지표는 느슨참조(FK 차단 없음).
_RETENTION_PLAN: tuple[tuple[type[Base], str], ...] = (
    (Dialogue, "started_at"),  # → dialogue_turn DB CASCADE
    # EOS-32: 제출 시퀀스(미성년 풀이 데이터) — problem_attempt보다 먼저(자식 우선·attempt 파기
    # 시 CASCADE 동반 제거와 별개로, attempt가 창 안에 남아도 만료 제출은 파기). NOT NULL
    # submitted_at이라 NULL-미파기 잔존 없음.
    (AnswerSubmission, "submitted_at"),
    # EOS-45: 힌트 사용 이력 — answer_submission과 동형(자식 우선·NOT NULL requested_at이라
    # NULL-미파기 잔존 없음).
    (HintUsage, "requested_at"),
    # EOS-46: 학생 풀이 step — 같은 계열(자식 우선·NOT NULL submitted_at·NULL-미파기 없음).
    (StudentSolutionStep, "submitted_at"),
    (ProblemAttempt, "started_at"),  # learning_session보다 먼저(session→attempt CASCADE 역순 방지)
    (LearningSession, "started_at"),
    (AttemptEvent, "event_at"),  # 느슨참조·hypertable(고아 방지)
    (Assessment, "started_at"),
    (ConceptMasteryHistory, "measured_at"),  # BKT 숙달 이력·느슨참조
    (SkillMasteryHistory, "measured_at"),  # 스킬 숙달 이력·느슨참조
    (AbilitySnapshot, "measured_at"),  # IRT θ 이력·느슨참조
    (DailyLearningMetrics, "metric_date"),  # 일 집계·DATE 컬럼·느슨참조
    (UserBehaviorMetrics, "measured_at"),  # 행동 지표·느슨참조
    # COLLAB-03: 풀이 시간 분포는 `user_id`가 없는 *교차 사용자 집계*라 삭제권(`_ERASURE_PLAN`)·
    # 본인 반출(`export.py`) 대상이 아니다(비-PII — export.py 모듈 docstring의 기존 결정 유지).
    # 그러나 *보존*은 다르다: `l2.learning_metrics_rollup`이 매일 (문항, 페르소나)별 행을 새
    # `measured_at`으로 적재하기 시작했으므로, 파기 경로가 없으면 상한 없이 증가한다. 「무기한
    # 보존 금지」(GDPR 데이터 최소화)는 PII 여부와 무관한 원칙이라 같은 `pii_retention_years`
    # 창으로 파기한다. 파기해도 원천(problem_attempt)이 남아 있는 한 재집계로 복원 가능하다.
    (ProblemSolveTimeDistribution, "measured_at"),  # 문항×페르소나 교차집계·비-PII·느슨참조
)


def _effective_timestamp(model: type[Base], column: str) -> ColumnElement[Any]:
    """파기 기준 표현식 — 기본은 `getattr(model, column)` 그대로, `ProblemAttempt`만 예외(SEC-33 ②).

    `started_at`은 클라 신고값이라 미신고(NULL)가 파기를 영원히 회피하는 통로다(모듈 docstring
    「SEC-33」 참조). `ingested_at`(서버 수신 시각 — server_default로 보장·⑥)으로 폴백해
    그 통로를 닫는다. 다른 모든 테이블은 NOT NULL이거나 서버 통제 컬럼이라 이 폴백이 불필요하다.
    """
    ts_column = getattr(model, column)
    if model is ProblemAttempt:
        return cast("ColumnElement[Any]", func.coalesce(ts_column, ProblemAttempt.ingested_at))
    return cast("ColumnElement[Any]", ts_column)


def retention_cutoff(as_of: date, *, years: int) -> date:
    """보존 만료 기준일 = `as_of − years`년(순수·윤년 안전·2/29→2/28 클램프).

    이 날짜 *이전*(`< cutoff`) 타임스탬프 행이 보존기한 경과분이다. `default_retention_until`
    (적재일+years)의 역방향 — 적재일 + years ≤ as_of 인 행을 가린다.
    """
    try:
        return as_of.replace(year=as_of.year - years)
    except ValueError:  # as_of가 2/29인데 −years년이 비윤년 → 2/28로 클램프.
        return as_of.replace(year=as_of.year - years, month=2, day=28)


async def purge_expired_records(
    session: AsyncSession,
    *,
    as_of: date,
    years: int | None = None,
) -> dict[str, int]:
    """학습 활동 PII 시계열에서 보존기한 경과분을 파기 — 테이블별 삭제 행수 반환(commit은 호출자).

    `years` 미지정 시 `Settings.pii_retention_years`(기본 3). `cutoff = as_of − years`년 이전
    타임스탬프(`_RETENTION_PLAN`의 각 컬럼 — `ProblemAttempt`는 `_effective_timestamp`가
    COALESCE로 대체·SEC-33 ②) 행을 child→parent 순서로 삭제한다(FK 안전·CASCADE 동반). NULL
    타임스탬프는 비교가 NULL이라 미파기(보수적) — `ProblemAttempt`도 `started_at`·`ingested_at`
    이 둘 다 NULL인 레거시 행에는 여전히 적용된다. 순수 ORM·원시 SQL 0.
    """
    resolved_years = years if years is not None else get_settings().pii_retention_years
    cutoff = retention_cutoff(as_of, years=resolved_years)
    counts: dict[str, int] = {}
    for model, column in _RETENTION_PLAN:
        ts_expr = _effective_timestamp(model, column)
        result = await session.execute(delete(model).where(ts_expr < cutoff))
        counts[model.__tablename__] = cast("CursorResult[Any]", result).rowcount or 0
    return counts
