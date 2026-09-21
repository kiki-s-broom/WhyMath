"""개인정보·콘텐츠 감사(SEC-09, SEC-29) — 반출·동의변경·관리자접근·역할변경·콘텐츠CUD 5종
writer + IP 해싱.

설계 정본: `docs/architecture/account_security_gap_review.md` D3. `security_privacy.md:88-100`의
"모든 PII 접근 로그"는 **채택하지 않는다**(정정 경위는 `docs/standards/security_privacy.md`
§감사 로그 편집자 부기) — 본인 조회 29개 엔드포인트 전수 감사는 미성년 학습 조회 이력 자체를
프로파일링 자산화하고 볼륨도 소음이라 의도적으로 제외한다. D3 원 결정은 "시스템 밖으로 나가는
사건"과 "본인 아닌 주체의 접근" 3종을 감사 대상으로 확정했고, ADMIN-01(`ops/role_grant_cli.py`)이
권한 경계 자체가 바뀌는 4번째 종을, SEC-29가 전역 콘텐츠 리소스 CUD의 5번째 종을 더한다:

  1. **데이터 반출**(`GET /v1/me/export` → `api/me.py:export_my_data`)
  2. **동의 변경**(`POST /v1/users/me/parental-consent` → `api/users.py:grant_parental_consent`)
  3. **관리자접근**(`record_admin_access_audit` — **현재 호출부 0곳**, 관리자 콘솔 Phase B가
     착지할 때 배선. `AuditEventKind.admin_access` docstring 참조 — 가짜 이벤트 날조 금지)
  4. **역할 변경**(`record_role_change_audit` — `ops/role_grant_cli.py`(ADMIN-01)의 grant/revoke가
     **진짜 첫 호출부**. `AuditEventKind.role_change` docstring 참조)
  5. **콘텐츠 CUD**(`record_content_mutation_audit` — `api/concepts.py`·`api/problems.py`의
     `RequireContentAdmin` 게이팅 6라우터가 **첫 호출부**. `AuditEventKind.content_mutation`
     docstring 참조 — SEC-29가 "관리자 콘텐츠 CUD에 감사 로그가 없다"는, ADMIN-06과 무관하게
     *오늘* 실재하는 별도 갭을 메운다)

`erasure.py`·`export.py`와 같은 저장소 패턴: `AsyncSession` 주입·`session.add()`만 하고
**commit은 호출자**(엔드포인트/CLI 트랜잭션과 합류) — 감사 행과 주행위(반출/동의기록/역할변경/
콘텐츠CUD)가 같은 트랜잭션으로 원자적이어야 하기 때문이다(하나만 성공하는 부분 실패 방지).
`deletion_audit`는 학생 소유 데이터 삭제 감사의 단일 권위로 유지하고 이 모듈은 그 범주의 삭제
이벤트를 다루지 않는다(이중 진실원천 금지) — 콘텐츠(개념·문항) 삭제는 학생 소유 데이터가
아니므로 이 경계 밖이며 `content_mutation`의 `action=delete`로 여기 적재된다.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.audit import PrivacyAudit
from whymath_backend.schema.enums import (
    AuditEventKind,
    ConsentScope,
    PrivacyAuditAction,
    PrivacyAuditResourceType,
)

if TYPE_CHECKING:
    from whymath_backend.config import Settings

__all__ = [
    "hash_client_ip",
    "record_admin_access_audit",
    "record_consent_change_audit",
    "record_content_mutation_audit",
    "record_export_audit",
    "record_role_change_audit",
]

_logger = logging.getLogger("whymath.privacy.audit")


def hash_client_ip(ip: str | None, *, settings: Settings) -> str | None:
    """IP → `sha256(salt+ip)` hex(64자), 평문 미저장(D3 필드 정정 ①).

    `api/auth.py:email_hash`와 달리 **유염**이다 — email_hash는 upsert 조회 키라 같은 이메일이
    항상 같은 해시여야 하지만, 감사 IP 해시는 조회 키가 아니라 *레인보우테이블 역산 불가*가
    목표라 새 salt(`Settings.pii_audit_ip_salt`)를 쓴다.

    `ip=None`(IP 추출 실패)이면 무조건 None(해싱할 것이 없음). salt 미설정 시:
      - **프로덕션 추정 환경**(`is_production_like`)은 `RuntimeError`(SEC-01
        `require_dialogue_content_cipher` fail-closed 패턴 답습 — 평문/의사 해시로 조용히
        대체하지 않는다).
      - **개발·CI**는 경고 로그 후 `None` — 감사 *행 자체*는 호출자가 계속 적재한다(IP 해시
        미비로 반출·동의변경이라는 주행위·그 감사 사건 자체를 놓치는 것이 더 나쁜 실패 모드).
    """
    if ip is None:
        return None
    if not settings.pii_audit_ip_salt_configured:
        from whymath_backend.config import is_production_like

        if is_production_like(settings):
            raise RuntimeError(
                "프로덕션 추정 환경(실 OAuth provider 구성)인데 개인정보 감사 IP salt가 "
                "미설정입니다 — `WHYMATH_PII_AUDIT_IP_SALT`를 설정하세요. 평문/의사 해시로 "
                "대체하지 않습니다(레인보우테이블 위험)."
            )
        _logger.warning(
            "WHYMATH_PII_AUDIT_IP_SALT 미설정 — 개발환경이라 ip_hash=None으로 감사 행은 "
            "계속 적재합니다(주행위를 막지 않음)."
        )
        return None
    salt = settings.pii_audit_ip_salt.get_secret_value().encode("utf-8")
    return hashlib.sha256(salt + ip.encode("utf-8")).hexdigest()


def record_export_audit(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    ip: str | None,
    settings: Settings,
) -> PrivacyAudit:
    """반출 감사 1행을 `session.add()`한다(commit은 호출자·`export_my_data`와 동일 TX).

    반출 *내용*(export payload)은 저장하지 않는다 — 감사가 데이터 사본이 되면 최소화 위반
    (D3 필드 정정 ②). "반출이 일어났다"는 사실·시각·행위자·IP 해시만.
    """
    row = PrivacyAudit(
        user_id=user_id,
        event_kind=AuditEventKind.export_data.value,
        ip_hash=hash_client_ip(ip, settings=settings),
    )
    session.add(row)
    return row


def record_consent_change_audit(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    consent_scope: ConsentScope,
    ip: str | None,
    settings: Settings,
) -> PrivacyAudit:
    """동의변경 감사 1행을 `session.add()`한다(commit은 호출자·`grant_parental_consent`와 동일 TX).

    `consent_scope`가 *어떤* 동의 범위가 바뀌었는지 구분하는 유일한 typed 메타데이터다(자유텍스트
    0). 법정대리인 이메일 등 PII는 이 행에 담기지 않는다(그 값은 `parental_consent` 테이블의
    책임이며 이미 해시로만 저장됨).
    """
    row = PrivacyAudit(
        user_id=user_id,
        event_kind=AuditEventKind.consent_change.value,
        consent_scope=consent_scope.value,
        ip_hash=hash_client_ip(ip, settings=settings),
    )
    session.add(row)
    return row


def record_admin_access_audit(
    session: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    ip: str | None,
    settings: Settings,
) -> PrivacyAudit:
    """관리자접근 감사 1행을 `session.add()`한다 — **현재 호출부 0곳**(SEC-09 시점 실측).

    관리자 콘솔(`docs/design/ui/04_admin_console_architecture.md` Phase B)이 아직 없어 이
    함수를 실제로 부르는 엔드포인트가 없다(가짜 이벤트 날조 금지 — `AuditEventKind.admin_access`
    docstring 동형). 그 콘솔이 착지할 때 "관리자가 학생 A의 데이터를 조회" 지점에서
    `record_admin_access_audit(session, actor_user_id=admin.user_id, target_user_id=student_id,
    ip=_client_ip(request, settings=settings), settings=settings)`로 바로 배선할 수 있도록 미리
    세운다.

    `actor_user_id`(관리자)와 `target_user_id`(피조회 사용자)가 반드시 다름을 전제하지는
    않는다(자기 자신 접근을 관리자접근으로 부를 이유는 없으나, 이 함수는 그 판단을 호출자에게
    맡긴다 — 순수 writer).
    """
    row = PrivacyAudit(
        user_id=actor_user_id,
        target_user_id=target_user_id,
        event_kind=AuditEventKind.admin_access.value,
        ip_hash=hash_client_ip(ip, settings=settings),
    )
    session.add(row)
    return row


def record_role_change_audit(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    ip: str | None,
    settings: Settings,
) -> PrivacyAudit:
    """역할변경 감사 1행을 `session.add()`한다(commit은 호출자) — ADMIN-01의 **진짜 첫 호출부**.

    `ops/role_grant_cli.py`의 grant/revoke가 `apply_role_change`(역할 mutate) 직후 이 함수를
    호출하고, 마지막에 **단일 `session.commit()`**으로 묶는다 — 역할 변경과 감사 행 적재가
    같은 트랜잭션이라 부분 성공(역할만 바뀌고 감사가 안 남거나, 그 반대)이 없다.

    `user_id`는 역할이 *바뀐 대상 계정*이다 — `admin_access`(actor≠target)와 달리 이 CLI는
    운영자가 셸에서 직접 실행하며 인증된 세션·`UserProfile` 신원을 갖는 "행위자"가 존재하지
    않는다(`retention_purge_cli`처럼 배치 성격 — 로그인한 관리자가 누른 버튼이 아니다). 그래서
    `export_data`/`consent_change`와 동형으로 *본인 계정의 사건*으로 취급하고 `target_user_id`는
    채우지 않는다(NULL) — 이렇게 하면 `GET /v1/me/privacy-audit`(user_id 필터)로 그 계정 소유자
    본인도 "언제 내 역할이 바뀌었는지"를 조회할 수 있다.

    old_role/new_role *값 자체*는 이 행에 담지 않는다 — `PrivacyAudit`에 그 값을 위한 typed
    컬럼이 없고(consent_scope는 `consent_change` 전용, 다른 이벤트에 전용하지 않는다는 게
    문서화된 불변식), 자유텍스트 필드도 두지 않는다(CLAUDE.md 미성년 PII 자유서술 금지 정신과
    동형 — 값이 아니라 *발생 사실*만). 무엇으로/무엇에서 바뀌었는지는 CLI stdout JSON
    (`{"user_id", "old_role", "new_role"}`)과 운영자 셸 로그가 1차 기록이고, 이 행은 "그 시각
    role_change가 있었다"는 2차 감사 신호다.
    """
    row = PrivacyAudit(
        user_id=user_id,
        event_kind=AuditEventKind.role_change.value,
        ip_hash=hash_client_ip(ip, settings=settings),
    )
    session.add(row)
    return row


def record_content_mutation_audit(
    session: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    resource_type: PrivacyAuditResourceType,
    resource_id: uuid.UUID,
    action: PrivacyAuditAction,
    ip: str | None,
    settings: Settings,
) -> PrivacyAudit:
    """콘텐츠CUD 감사 1행을 `session.add()`한다(commit은 호출자) — SEC-29의 **진짜 첫 호출부**.

    `api/concepts.py`·`api/problems.py`의 `POST`/`PATCH`/`DELETE`(전부 `RequireContentAdmin`
    게이팅)가 리소스 mutate 직후 이 함수를 호출하고, 기존 `try/commit/except IntegrityError`
    블록의 그 `commit()`에 합류한다 — mutate와 감사 행 적재가 같은 트랜잭션이라 부분 성공(리소스만
    바뀌고 감사가 안 남거나, 그 반대)이 없다(`record_role_change_audit`과 동일 원자성 원칙).

    `actor_user_id`는 게이트를 통과한 관리자(`RequireContentAdmin` 의존성이 준 `UserProfile.
    user_id`)다. `target_user_id`는 채우지 않는다 — 대상이 사용자 개인정보가 아니라 콘텐츠
    리소스이므로(`admin_access`와 다른 축), 그 역할은 `resource_type`+`resource_id`가 한다.

    `action` 값 자체 이상의 diff(무엇이 바뀌었는지)는 이 행에 담지 않는다 — `PrivacyAudit`에
    자유텍스트 필드가 없다는 문서화된 불변식과 동일 이유(`record_role_change_audit` docstring
    참조). 상세는 PG 자체의 현재 상태·애플리케이션 로그가 1차 기록이고, 이 행은 "그 시각 그
    관리자가 그 리소스에 그 동작을 했다"는 2차 감사 신호다.
    """
    row = PrivacyAudit(
        user_id=actor_user_id,
        event_kind=AuditEventKind.content_mutation.value,
        resource_type=resource_type.value,
        resource_id=resource_id,
        action=action.value,
        ip_hash=hash_client_ip(ip, settings=settings),
    )
    session.add(row)
    return row
