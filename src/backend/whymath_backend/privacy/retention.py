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

EOS-131 ⑪ — 서버 세션의 연쇄 파기가 시도를 *조기에* 지우지 않게 한다:
  `problem_attempt.session_id`는 `learning_session`에 `ON DELETE CASCADE`로 걸려 있다. 서버 writer
  (`l2/learning_session_writer`) 이전에는 이 값이 항상 NULL이라 연쇄가 한 번도 작동하지 않았다.
  이제 서버가 값을 채우므로, 세션을 `started_at` 기준으로 지우면 세션 시작은 파기 기준을 넘었지만
  *그 세션의 뒤쪽 시도는 아직 기준 안쪽*인 경우 그 시도가 연쇄로 함께 지워진다(세션 길이만큼 조기
  파기 — 그리고 파기 리포트의 `problem_attempt` 건수가 실제보다 적게 집계된다). 두 선택지(기준
  맞추기 / 연쇄 건수 계상) 중 **기준 맞추기**를 택했다 — 연쇄 건수를 세는 것은 조기 파기를 *보고*할
  뿐 막지 못한다. 규칙(서버 세션 = `last_activity_at IS NOT NULL`인 행에만 적용):
    ① 파기 기준 시각은 `last_activity_at`(세션의 마지막 활동)이다 — 세션 안 모든 시도의 수신
       시각 이상이다(writer가 시도 수신 시각으로 `last_activity_at`을 갱신한다).
    ② 그리고 **그 세션에 남은 시도가 하나도 없을 때만** 지운다. 시도는 이 플랜에서 세션보다 먼저
       파기되므로, 남아 있는 시도는 정의상 아직 기준 안쪽이다 — 클라 신고 `started_at`이 수신보다
       최대 5분 앞선(허용 오차) 경계 사례에서도 ①만으로는 뚫릴 틈을 ②가 닫는다.
  writer 이전의 행(`last_activity_at IS NULL`)은 종전 규칙(`started_at` 기준·조건 없음) 그대로다 —
  그 행들의 시도는 `session_id`가 NULL이라 연쇄 대상 자체가 아니고, 동작을 바꿀 이유가 없다.

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

SEC-41 — 보존 파기 *완전성* 가드와 사유 없던 4테이블의 처분 (판정 기준 main `a05eb49a`):
  삭제권에는 "소유 테이블이 계획 밖이면 RED"인 가드가 있었지만(`test_erasure_plan_completeness`),
  보존 파기에는 같은 가드가 없었다 — 새 학생 테이블이 이 플랜에 들어갔는지 기계가 묻지 않았다.
  `tests/backend/privacy/test_retention_plan_completeness.py`가 삭제권 가드의 소유 판정
  (A)∪(B)∪(C)를 그대로 재사용해, 소유 테이블이 아래 셋 중 어디에도 없으면 RED를 낸다.
    ① `_RETENTION_PLAN` — 이 모듈이 지운다.
    ② `_PURGED_ELSEWHERE` — 다른 경로가 지운다(`evidence_links` → `purge_expired`).
    ③ `_RETENTION_PLAN_EXEMPTIONS` — 사유와 함께 *의도적으로* 지우지 않는다. 임시 제외는
       `_RETENTION_PLAN_EXEMPTION_EXPIRY`에 해소 태스크를 구조 필드로 둔다(삭제권 쪽 SEC-39와
       같은 만료 계약 — 해소 태스크가 종결됐는데 항목이 남으면 RED).
  실측(소유 28테이블 · 계획 14건): 계획 밖 15건 중 11건은 사유 있는 제외(감사 2·계정/인증/동의/
  가설 계열 8·`evidence_links`)였고, **4건이 사유 없이** 계획 밖이었다. 처분:
    편입 3건 — `evidence_event`(`time`) · `learning_state_transition`(`occurred_at`) ·
      `job_ownership`(`created_at`). 셋 다 NOT NULL 타임스탬프라 NULL-미파기 잔존이 없고, 새 보존
      연한 숫자를 정하지 않는다(위 기존 균일 `pii_retention_years` 창을 그대로 쓴다).
    제외 1건 — `learner_state`(학생당 1행 현재값). 사유는 `_RETENTION_PLAN_EXEMPTIONS`가 정본이다.
  주의 두 가지(정직 표기):
    ⓐ `evidence_event.retention_until`은 이 모듈이 읽지 않는다 — 읽는 파기 경로도, 값을 채우는
       writer도 없는 *예약 컬럼*이다(모델 docstring이 "retention.py 소관"이라 적던 것은 사실이
       아니었고 SEC-41 ④로 정정했다). 행별 만료일이 필요해지면 `_purge_condition`에 그 분기를
       더하는 별도 판단이다 — 지금은 `time` 기준 균일 창이다. 이 편입은 삭제권 처분(SEC-40 ·
       결정 게이트 `G-eos37-erasure-kpi-disposition`)과 별개 축이다: 그쪽은 *요청 시 삭제*, 이쪽은
       *창 만료 삭제*다. 창 만료 삭제는 데이터를 더 일찍 줄이는 방향이라 `docs/legal/
       pipa_data_matrix.md`가 금지한 "가명 보존 적법" 가정을 깔지 않는다 — 그 게이트의 선택 결과가
       이 편입과 어긋나는지는 확인하지 못했다(미결정이라 판정 불가 · 결정 후 재확인).
    ⓑ `learning_state_transition`의 최신 행이 현재 상태의 정본이다(`l2/learning_state_machine.
       get_current_state`). 학생의 모든 전이가 창보다 오래됐으면(비활동 `pii_retention_years`년+)
       원장이 비어 현재 상태는 `NEW`로 되돌아간다 — 같은 학생의 시도·숙달 이력도 같은 창으로
       이미 파기됐으므로 일관된 결과이나, "파기가 현재 상태를 바꾼다"는 사실은 여기 적어 둔다.
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast

from sqlalchemy import ColumnElement, CursorResult, and_, delete, exists, func, or_, select
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
from whymath_backend.db.models.evidence_event import EvidenceEvent
from whymath_backend.db.models.hint_usage import HintUsage
from whymath_backend.db.models.job_ownership import JobOwnership
from whymath_backend.db.models.learning_state_transition import LearningStateTransition
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
    # SEC-41: 교수법 처치·결과 증거(하이퍼테이블·느슨참조 session_id) — attempt_event와 동형.
    # `time`은 복합 PK 구성요소라 NOT NULL. `retention_until` 컬럼은 읽지 않는다(모듈 docstring ⓐ).
    (EvidenceEvent, "time"),
    # SEC-41: 학습 상태 전이 원장(append-only·user_id 실 FK) — NOT NULL `occurred_at`. 모든 전이가
    # 창보다 오래된 학생은 현재 상태가 NEW로 돌아간다(모듈 docstring ⓑ).
    (LearningStateTransition, "occurred_at"),
    # SEC-41: 비동기 QUALITY 작업 소유권(user_id 실 FK·자식 FK 없음) — NOT NULL `created_at`.
    (JobOwnership, "created_at"),
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

# SEC-41 — 이 모듈이 지우지 *않지만* 다른 경로가 지우는 소유 테이블(테이블명 → 담당 경로).
# 완전성 가드(`test_retention_plan_completeness`)가 ① 플랜 ② 이 맵 ③ 아래 제외 목록의 합집합으로
# 소유 테이블을 덮는지 본다. 이 맵에 올리면 "다른 경로가 실제로 있다"는 주장이므로 가드가 그 경로의
# 실재(`retention_purge_cli`가 호출·`purge_expired`가 그 모델을 지움)도 함께 대조한다.
_PURGED_ELSEWHERE: dict[str, str] = {
    "evidence_links": (
        "`l4.misconception.evidence_store.purge_expired`가 `retention_until < as_of`로 파기한다 — "
        "`retention_purge_cli`가 이 모듈 호출 앞에서 같은 트랜잭션으로 함께 실행한다(중복 0). "
        "`retention_until`이 NULL인 행(무기한)은 지우지 않는다."
    ),
}

# SEC-41 — 소유 테이블이지만 *의도적으로* 타임스탬프 창 파기 계획 밖에 두는 테이블의 사유 있는 목록.
# 무사유 제외 금지(CLAUDE.md). 만료 없는 제외도 금지라, 영구 제외(인증 자격 2건)가 아닌 항목은
# 전부 아래 `_RETENTION_PLAN_EXEMPTION_EXPIRY`에 해소 태스크를 함께 등재해야 한다 — 그 태스크가
# 종결(done·cancelled)됐는데 항목이 남아 있으면 가드가 RED를 낸다(자동 해제 아님 — 걷는 것은
# 처분하는 사람).
# 연한 숫자는 어느 항목에도 적지 않는다: 법령 유래 판단이면 코드가 정하지 않고 MGMT-02(이용약관·
# 개인정보처리방침 변호사 검토) 회신을 기다린다(CLAUDE.md 「법령 유래 절차의 기계 대체 금지」).
_RETENTION_PLAN_EXEMPTIONS: dict[str, str] = {
    # ── 법령 판단 대기(MGMT-02) — 감사·동의 증빙 ──
    "deletion_audit": (
        "GDPR 삭제 증빙 append-only 로그 — 법정 증빙 성격이라 즉시 파기 대상이 아니다(지우면 삭제 "
        "사실을 증빙할 수 없다). 최종 보존 연한은 미확정이며 MGMT-02 변호사 회신이 선행한다 — 임시 "
        "제외(ADMIN-03 문단 · `test_audit_retention_exclusion.py`가 제외를 동결)."
    ),
    "privacy_audit": (
        "SEC-09 개인정보 감사(반출·동의변경·관리자접근) append-only 로그 — deletion_audit와 같은 "
        "근거의 법정 증빙이다. 최종 보존 연한은 미확정이며 MGMT-02 변호사 회신이 선행한다 — 임시 "
        "제외(ADMIN-03 문단 · `test_audit_retention_exclusion.py`가 제외를 동결)."
    ),
    "parental_consent": (
        "14세 미만 법정대리인 동의 증빙(append-only · PIPA §22-2) — 동의 사실의 법적 증빙이라 학습 "
        "활동 PII의 창 만료와 의미가 다르다(지우면 동의 사실을 증빙할 수 없다). 보존 연한은 법령 "
        "판단이라 코드가 정하지 않는다 — 임시 제외, MGMT-02 회신 대기."
    ),
    # ── 법령 판단 대기(MGMT-02) — 계정 수명에 종속된 *현재값* ──
    # 시계열이 아니라서 `created_at`·`updated_at`은 '마지막 활동'이 아니라 생성·변경 시각이다. 그
    # 기준으로 지우면 활동 중이지만 값이 오래 안 바뀐 학생의 행이 지워진다 — 창 파기의 기준이
    # 될 수 없다. 이 현재값들의 수명은 계정(삭제권 `erase_user`)에 매여 있고, 탈퇴·비활동 계정의
    # 현재값을 언제 지울지는 법령 판단이라 이 모듈이 정하지 않는다.
    "user_profile": (
        "계정 현재값(PK 자체) — 시계열이 아니라 타임스탬프 창으로 지울 대상이 아니다. 계정 삭제는 "
        "`erase_user`가 자식 전부 뒤에 명시적으로 한다. 탈퇴·비활동 계정 현재값의 보존 연한은 법령 "
        "판단이라 코드가 정하지 않는다 — 임시 제외, MGMT-02 회신 대기."
    ),
    "learner_state": (
        "학생당 1행 *현재값*(PK=learner_id · SEC-41 처분) — 시계열이 아니고 `updated_at`·"
        "`provisioned_at`은 변경·생성 시각이라, 이 기준으로 지우면 활동 중이지만 목표가 오래 "
        "안 바뀐 학생의 학습 루프 진입 상태가 사라진다. 수명은 계정에 종속(삭제권 "
        "`erase_user`). 비활동 계정 현재값의 보존 연한은 법령 판단이라 코드가 정하지 않는다 — "
        "임시 제외, MGMT-02 회신 대기."
    ),
    "misconception_hypothesis": (
        "학생×오개념 1행 upsert의 활성 가설 *현재값*(`is_active`로 비활성화할 뿐 행을 지우지 "
        "않는다) — 시계열이 아니라 `updated_at` 기준 삭제는 오래 갱신되지 않은 활성 가설을 "
        "지운다. 수명은 계정에 종속(삭제권 `erase_user`). 비활동 계정 현재값의 보존 연한은 "
        "법령 판단이라 코드가 정하지 않는다 — 임시 제외, MGMT-02 회신 대기."
    ),
    # ── writer 0 — 보존할 행이 아직 없다(쓰는 곳이 생기면 이 사유가 거짓이 된다) ──
    # 실측(2026-10-02 SEC-41 · 판정 기준 main `a05eb49a`): `whymath_backend` 전수에서 이 세 모델은
    # `schema/` 변환 seam과 삭제·반출·가드 외에 쓰는 코드가 0건이다(내가 찾은 방법으로 0건 — 범위는
    # 모델 참조 grep). 쓰기 경로가 생기는 순간 이 제외는 근거를 잃으므로 해소 태스크를 단다.
    "user_state_snapshot": (
        "시점별 학습 상태 스냅샷 — 현재 writer 0건(schema 변환 seam 외 쓰는 코드 없음 · 2026-10-02 "
        "SEC-41 실측)이라 보존할 행이 없다. 좌석의 배선·폐기 판정은 ARCH-51이 소유하며, 배선되면 "
        "`snapshot_at` 기준 편입 여부를 그때 판정한다 — 임시 제외, 해소 태스크 ARCH-51."
    ),
    "user_track_history": (
        "계정 속성(진로 트랙) 변경 이력 — 현재 writer 0건(schema 변환 seam 외 쓰는 코드 없음 "
        "· 2026-10-02 SEC-41 실측)이라 보존할 행이 없다. writer 도입 전 처분 판정은 SEC-25"
        "(writer0-account-history-retention-disposition)가 소유한다 — 임시 제외, 해소 태스크 "
        "SEC-25."
    ),
    "user_persona_history": (
        "페르소나 분류 이력 — 현재 writer 0건(schema 변환 seam 외 쓰는 코드 없음 · 2026-10-02 "
        "SEC-41 실측)이라 보존할 행이 없다. writer 도입 전 처분 판정은 SEC-25"
        "(writer0-account-history-retention-disposition)가 소유한다 — 임시 제외, 해소 태스크 "
        "SEC-25."
    ),
    # ── 영구 제외 — 인증 자격(기술적 자가만료) ──
    "device_credential": (
        "디바이스 자격증명 — 폐기는 `revoked`·`revoked_at` 플래그가 맡고(`api/_device_store`) "
        "학습 활동 PII 시계열이 아니라 타임스탬프 창 파기 대상이 아니다. 계정 삭제 시 "
        "`erase_user`가 지운다."
    ),
    "refresh_token_session": (
        "리프레시 토큰 서버측 취소(allowlist) 행 — 토큰 만료는 JWT `exp`가 강제하고 행의 "
        "`expires_at`은 프루닝·감사 용도이며 폐기는 `revoked` 플래그가 맡는다. 학습 활동 PII "
        "시계열이 아니라 창 파기 대상이 아니다. 계정 삭제 시 `erase_user`가 지운다."
    ),
}

# SEC-41 — 임시 제외의 해소 태스크(테이블명 → 백로그 태스크 ID). 사유 문자열 속 태스크 ID는 기계가
# 대조할 수 없으므로 구조 필드로 따로 둔다(삭제권 `_ERASURE_PLAN_EXEMPTION_EXPIRY`·SEC-39 선례). 이
# 맵에 없는 `_RETENTION_PLAN_EXEMPTIONS` 항목은 영구 제외여야 하며 그 집합은 가드가 고정한다.
_RETENTION_PLAN_EXEMPTION_EXPIRY: dict[str, str] = {
    "deletion_audit": "MGMT-02",
    "privacy_audit": "MGMT-02",
    "parental_consent": "MGMT-02",
    "user_profile": "MGMT-02",
    "learner_state": "MGMT-02",
    "misconception_hypothesis": "MGMT-02",
    "user_state_snapshot": "ARCH-51",
    "user_track_history": "SEC-25",
    "user_persona_history": "SEC-25",
}


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


def _purge_condition(model: type[Base], column: str, cutoff: date) -> ColumnElement[bool]:
    """이 모델의 파기 조건 — 기본은 `기준시각 < cutoff`, 서버 세션만 EOS-131 ⑪ 규칙.

    `LearningSession`은 두 갈래다(모듈 docstring 「EOS-131 ⑪」):
      - writer 이전 행(`last_activity_at IS NULL`): 종전대로 `started_at < cutoff`.
      - 서버 세션: `last_activity_at < cutoff` **그리고** 그 세션을 가리키는 시도가 남아 있지 않음.
    """
    ts_expr = _effective_timestamp(model, column)
    if model is not LearningSession:
        return ts_expr < cutoff
    remaining_attempt = exists(
        select(ProblemAttempt.attempt_id).where(
            ProblemAttempt.session_id == LearningSession.session_id
        )
    )
    return or_(
        and_(LearningSession.last_activity_at.is_(None), ts_expr < cutoff),
        and_(
            LearningSession.last_activity_at.is_not(None),
            LearningSession.last_activity_at < cutoff,
            ~remaining_attempt,
        ),
    )


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
        result = await session.execute(delete(model).where(_purge_condition(model, column, cutoff)))
        counts[model.__tablename__] = cast("CursorResult[Any]", result).rowcount or 0
    return counts
