"""user 도메인 HTTP API — 인증된 본인 프로필 조회/수정 + 법정대리인 동의 기록(`/v1/users/me`).

조회·수정(`GET`/`PATCH /me`)은 `ConsentedUser`(인증 + 미성년 동의 게이트) 뒤에 노출한다.
**PII**(email_hash·parent_email_hash)는 응답에서 제외(`response_model_exclude`). **PATCH는 자기
편집 가능 필드 화이트리스트만 허용** — 동의·신원·결제·시스템·감사 필드(parent_consent_at·
is_minor·email_hash·persona_*·subscription_*·created_at 등)는 사용자가 바꿀 수 없다(미성년 *동의
게이트 우회 방지*가 핵심 보안 요구).

법정대리인 동의 기록(`POST /me/parental-consent`·PIPA 만14세 미만 §3)은 *예외적으로*
`get_current_user`(인증만)로 노출한다 — 동의가 *아직 없는* 미성년은 동의 게이트가 403으로 막으므로
동의를 *받는* 경로가 게이트 뒤에 있으면 도달 불가하기 때문(닭-달걀). 신원 확인은 stub seam
(`consent_grant.py` — 실 본인확인은 변호사 자문 후속). 법정대리인 이메일은 *해시만* 저장(평문 PII
금지·CLAUDE.md).

다른 사용자 프로필 조회/관리(관리자)는 범위 밖 — 본인(`me`)만 노출(CLAUDE.md 미성년 PII 보호).

SEC-09: 동의 기록 성공 시 `privacy.record_consent_change_audit`가 `privacy_audit`에 감사 1행을
같은 트랜잭션으로 적재한다(`account_security_gap_review.md` D3 — 감사 대상 3종 중 "동의 변경").

SEC-20(`account_security_gap_review_r2.md` D9): 동의 *철회*(`DELETE /me/parental-consent`)를
신설했다 — 그전까지 동의는 받을 수만 있고 거둘 수 없어 **한 번 받은 동의가 영구히 유효**했다.
철회는 원장을 지우지 않고(append-only) `revoked_at`을 찍고 `parent_consent_at`을 해제해 게이트를
다시 닫으며, GRANT와 같은 감사 writer를 재사용한다(신규 감사 테이블 0).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.api._auth import ConsentedUser, get_current_user
from whymath_backend.api._concurrency import ensure_if_match, etag_for
from whymath_backend.api._rate_limit import _client_ip
from whymath_backend.api.auth import email_hash
from whymath_backend.config import Settings, get_settings
from whymath_backend.consent import current_year_kst, derive_is_minor
from whymath_backend.consent_grant import (
    GuardianVerificationRequest,
    GuardianVerifier,
    _default_guardian_verifier,
)
from whymath_backend.db.models.parental_consent import ParentalConsent
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.privacy import record_consent_change_audit
from whymath_backend.schema.enums import ConsentScope
from whymath_backend.schema.parental_consent import (
    ConsentScopeStatus,
    ParentalConsentGrantRequest,
    ParentalConsentGrantResponse,
    ParentalConsentHistoryResponse,
    ParentalConsentRevokeResponse,
)
from whymath_backend.schema.user import UserProfile as UserProfileSchema

router = APIRouter(prefix="/v1/users", tags=["user"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
# 법정대리인 신원 확인 SEAM 주입(기본 StubGuardianVerifier). 테스트·미래 실 구현은
# app.dependency_overrides[_default_guardian_verifier]로 교체한다(consent_grant.py 경계).
VerifierDep = Annotated[GuardianVerifier, Depends(_default_guardian_verifier)]

# 응답에서 항상 제외하는 PII(해시 식별자 — 클라이언트에 불필요).
_PII_EXCLUDE = {"email_hash", "parent_email_hash"}

# 사용자가 자기 PATCH로 바꿀 수 있는 필드(화이트리스트). 여기 없는 키는 422로 거부 —
# 특히 parent_consent_at·is_minor(동의 게이트)·email_hash(신원)·subscription_*(결제)·
# persona_*·diagnostic_*(시스템 판정)·created_at 등 감사/신원/결제 필드는 자가수정 불가.
#
# `grade`·`school_type`(학적 자가신고)이 여기 있는 이유 — EOS-82. 둘은 **소비자가 이미 4곳**
# 인데(`api/study.py::_build_signals`의 grade_band 교수법 필터 · `api/coach.py::_grade_for`의
# 학년 프롬프트 개인화 · `l2/target_progress.py`의 성취기준 커버리지 스코프 ·
# `l2/learner_state.py`의 학습자 상태 조립) **값을 넣는 HTTP 경로가 0곳**이라 전 학생이 영구
# `None`이었다. ORM 컬럼(`db/models/user.py`)과 DB 인덱스(`idx_user_school`)까지 있는데 입력만
# 없어서, 만들어 둔 기능들이 *에러 없이 조용히* 스킵/null 되고 있었다(무증상 무효화 —
# CLAUDE.md "작동 신호 없는 알고리즘 부착 금지"와 같은 형태). 실측·경위는
# `docs/reviews/eos_one_subject_completion_review_2026-09-03.md` §2.3 G1.
#
# 이 둘이 화이트리스트에 들어가도 안전한 근거: ⑴ **자가신고 학적 정보**이지 동의·신원·결제·
# 시스템 판정 필드가 아니다 ⑵ 미성년 게이트의 입력이 아니다 — 게이트는 `birth_year` → 서버
# 파생 `is_minor` 단일 경로이고 `grade`는 그 계산에 들어가지 않는다(아래 패치 로직 참조)
# ⑶ 값 범위는 스키마가 강제한다(`grade` ge=10 le=14 · `school_type` enum 12종) — 병합 결과
# 재검증에서 범위 밖은 422 ⑷ `security_privacy.md` §PII가 `UserProfile`의 학년 수집을 이미
# 승인한다(닉네임·학년·`school_id`·`birth_year` + 암호화 비대상 — 커리큘럼 정렬·진단의 쿼리
# 입력이라 암호화하면 조회가 불가능해진다).
#
# **여기 넣지 않는 것**: `school_id`·`school_region`·`gender`는 미소비 컬럼 처분 게이트
# (`G-prod-dead-column-check`)의 *제거* 후보라 방향이 반대다. 소비자가 생기기 전에 수집을
# 열면 목적 없는 PII 수집이 된다(최소 수집 원칙).
#
# `birth_year`는 *수정 가능*하다(온보딩에서 사용자가 입력) — 단 그 결과로 정해지는
# `is_minor`(미성년 동의 게이트의 입력)는 클라가 *직접 못 정한다*: is_minor는 화이트리스트에
# 없어 직접 PATCH가 422고, patch_me가 매 쓰기마다 birth_year에서 *서버 파생*해 덮어쓴다
# (consent.derive_is_minor — 단일 진실). 즉 미성년이 is_minor=false를 보내 게이트를 우회할
# 수 없다(클라 입력 미신뢰). birth_year를 거짓 신고하는 것은 자가신고 연령의 본질적 한계로
# 정확한 만나이 검증(생일 수집)·신원 확인은 변호사 자문 후속(pipa_data_matrix.md §3).
_SELF_EDITABLE = frozenset(
    {
        "nickname",
        "birth_year",
        "grade",  # 학년 10~14(고1~고3·N수1·N수2) — EOS-82. 소비자: study·coach·target_progress
        "school_type",  # 학교 유형 12종 enum — EOS-82. 소비자: target_progress 커버리지 스코프
        "primary_device",
        "has_apple_pencil",
        "note_app",
        "accessibility_needs",
        "target_universities",
        "target_major_category",
        "target_grade",
        "target_score",
        "target_exam_date",
        "uses_inkang",
        "inkang_provider",
        "uses_offline_academy",
        "monthly_education_spend",
    }
)


@router.get(
    "/me",
    response_model=UserProfileSchema,
    response_model_exclude=_PII_EXCLUDE,
    summary="내 프로필 조회",
)
async def read_me(user: ConsentedUser, response: Response) -> UserProfileSchema:
    """인증된 본인 프로필 — PII(해시) 제외, ETag 동봉(이후 조건부 PATCH용)."""
    result = user.to_schema()
    response.headers["ETag"] = etag_for(result)
    return result


@router.patch(
    "/me",
    response_model=UserProfileSchema,
    response_model_exclude=_PII_EXCLUDE,
    summary="내 프로필 부분 수정",
)
async def patch_me(
    body: dict[str, Any],
    user: ConsentedUser,
    session: SessionDep,
    settings: SettingsDep,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> UserProfileSchema:
    """본인 프로필 부분 수정 — 화이트리스트 필드만(동의·신원·결제 필드는 422로 거부).

    `If-Match`(GET ETag)로 낙관적 동시성(412). 병합 결과를 schema로 재검증(불변식 유지) 후
    `session.merge`로 PK 기준 갱신. 응답에 새 ETag.

    **미성년 게이트(서버측 is_minor 파생)**: `is_minor`는 화이트리스트에 없어 클라가 직접 못
    바꾸고(여기까지 오면 위 disallowed 422), 병합 후 *항상* 현재 birth_year에서 서버 파생해
    덮어쓴다(`consent.derive_is_minor` — 클라 입력 미신뢰의 단일 진실). 매 쓰기마다 재파생하는
    이유: birth_year를 바꾼 경우 새 값으로 갱신되고, 안 바꾼 경우라도 stale/잘못된 is_minor를
    *자가 치유*하기 때문(is_minor는 birth_year의 순수 서버 투영). 따라서 미성년이 is_minor=
    false로 게이트를 우회할 수 없다(우회 차단의 핵심).
    """
    disallowed = set(body) - _SELF_EDITABLE
    if disallowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"수정할 수 없는 필드입니다(자가수정 불가): {sorted(disallowed)}",
        )
    ensure_if_match(if_match, etag_for(user.to_schema()))
    merged = user.to_schema().model_dump()
    merged.update(body)
    merged["user_id"] = user.user_id  # PK 고정(본인)
    # is_minor를 *서버 파생*으로 덮어쓴다(클라 입력·stale 값 무시) — 병합된 birth_year 기준.
    # 미성년 동의 게이트 우회 방지의 핵심: is_minor는 birth_year의 순수 서버 투영이다.
    merged["is_minor"] = derive_is_minor(
        merged.get("birth_year"),
        current_year=current_year_kst(),
        threshold=settings.minor_consent_age,
    )
    try:
        validated = UserProfileSchema.model_validate(merged)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "수정 본문 병합 결과가 스키마를 위반합니다.",
                "errors": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()],
            },
        ) from exc
    updated = await session.merge(UserProfile.from_schema(validated))
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="고유 제약 위반으로 수정할 수 없습니다.",
        ) from exc
    result = updated.to_schema()
    response.headers["ETag"] = etag_for(result)
    return result


@router.post(
    "/me/parental-consent",
    response_model=ParentalConsentGrantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="법정대리인 동의 기록(14세 미만 게이트 해제) — PIPA §22-2",
)
async def grant_parental_consent(
    request: Request,
    body: ParentalConsentGrantRequest,
    user: Annotated[UserProfile, Depends(get_current_user)],
    session: SessionDep,
    verifier: VerifierDep,
    settings: SettingsDep,
) -> ParentalConsentGrantResponse:
    """법정대리인 동의를 기록하고 미성년 동의 게이트를 통과시킨다(PIPA 만14세 미만·§3).

    **인증 게이트가 `get_consented_user`가 아니라 `get_current_user`인 이유(핵심)**: 동의가
    *아직 없는* 미성년자는 `get_consented_user`가 403으로 막으므로, 동의를 *받는* 이 엔드포인트가
    동의 게이트 뒤에 있으면 영원히 도달할 수 없다(닭-달걀). 그래서 인증만 요구하고 동의 게이트는
    요구하지 않는다 — 동의를 *받는* 경로는 동의 게이트의 *예외*여야 한다.

    흐름: 신원 확인 SEAM(`verifier.verify` — 현재 StubGuardianVerifier) 실행 → 미통과면 403 →
    통과면 `parental_consent` 행 1개 적재(해시된 법정대리인 이메일·방식·범위·서명 시각) +
    `user_profile.parent_consent_at = now`를 *같은 트랜잭션*으로 커밋. 이후 그 학생의
    `get_consented_user` 게이트가 통과한다(end-to-end).

    **법적 경계(변호사 자문 필수)**: 신원 확인 *방식*은 stub이다 — 실 본인확인(휴대폰 인증·카드)
    의 법적 적정성은 변호사 자문 후속이고(consent_grant.py·pipa_data_matrix.md §3.2/§5), 동의
    *재확인 주기*(expires_at 정책)와 *법정대리인 인증 모델*(보호자가 어떻게 이 화면에 접근하는가)
    도 후속이다. 현재 expires_at은 미설정(None)으로 기록만 한다(게이트 만료 재차단은 후속).

    **미성년 PII(CLAUDE.md 절대 금기)**: 법정대리인 이메일은 *평문 미저장* — sha256 해시
    (`email_hash` 재사용)로만 둔다. 응답에도 PII를 싣지 않는다(불필요).

    멱등성: 이미 동의가 있어도(만료 후 재확인·범위 재동의) append-only로 새 행을 적재하고
    `parent_consent_at`을 현재 시각으로 갱신한다 — 반복 호출이 안전하다(게이트는 통과 유지).
    """
    # 0. 기능 플래그 게이트 — 실 GuardianVerifier 결선 전까지 prod에서 off(기본). stub만으론
    #    임의 이메일로 self-consent 우회가 가능하므로, off면 동의 경로 자체를 막는다
    #    (consent_grant.py·pipa_data_matrix.md §3.5·변호사 자문 후속).
    if not settings.parental_consent_grant_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="법정대리인 동의 기록 기능이 비활성화되어 있습니다.",
        )
    # 1. 신원 확인 SEAM 실행(현재 stub) — 미통과면 동의를 받지 않는다(403).
    verification = verifier.verify(GuardianVerificationRequest(guardian_email=body.guardian_email))
    if not verification.verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="법정대리인 신원 확인에 실패했습니다(동의를 진행할 수 없습니다).",
        )

    now = datetime.now(tz=timezone.utc)
    # 2. 동의 레코드 적재 — 법정대리인 이메일은 *해시만*(평문 PII 금지·CLAUDE.md). expires_at은
    #    재확인 주기 미확정이라 None(변호사 자문 후속) — 기록만 하고 게이트 만료 재차단은 후속.
    #    consent_id는 앱에서 명시 생성(server_default 의존 없이 즉시 응답에 쓰려고 — resolve_user·
    #    RefreshTokenSession 동형: 발급 코드가 발급 전에 PK 값을 안다).
    consent = ParentalConsent(
        consent_id=uuid.uuid4(),
        user_id=user.user_id,
        guardian_email_hash=email_hash(body.guardian_email),
        verification_method=verification.method,
        verification_ref=verification.reference,
        consent_scope=body.consent_scope.value,
        consent_signed_at=now,
        expires_at=None,
        revoked_at=None,
    )
    session.add(consent)
    # 3. 같은 트랜잭션으로 게이트 통과 근거(parent_consent_at) 설정 — 동의 기록과 원자적.
    #    단, core scope(`service_core`·`ai_inference`)에 대해서만 설정한다. 선택 동의
    #    (`ai_training`·`research`·`marketing`)는 서비스 이용 게이트를 열어서는 안 된다
    #    (EOS §45·§48: optional scope이 core gate를 여는 문제).
    if body.consent_scope.is_core_scope:
        user.parent_consent_at = now
        await session.merge(user)
    # 4. SEC-09: 동의변경 감사 1행 — 위 두 쓰기와 *같은* 트랜잭션(session.commit() 1회)이라
    #    동의 기록·게이트 갱신·감사가 원자적(부분 성공 없음). 어떤 동의 범위가 바뀌었는지만
    #    typed 메타(consent_scope)로 남기고, 법정대리인 이메일 등 PII는 담지 않는다.
    record_consent_change_audit(
        session,
        user_id=user.user_id,
        consent_scope=body.consent_scope,
        ip=_client_ip(request, settings=settings),
        settings=settings,
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="동의를 기록할 수 없습니다(제약 위반).",
        ) from exc
    return ParentalConsentGrantResponse(
        consent_id=consent.consent_id,
        consent_scope=body.consent_scope,
        verification_method=verification.method,
        consent_signed_at=now,
        parent_consent_at=now,
    )


def _effective_service_scope(scope: ConsentScope) -> ConsentScope:
    """`ai_inference`는 `service_core`와 동일 취급(서비스 본 기능)."""
    if scope is ConsentScope.ai_inference:
        return ConsentScope.service_core
    return scope


@router.delete(
    "/me/parental-consent",
    response_model=ParentalConsentRevokeResponse,
    summary="법정대리인 동의 철회(게이트 재차단) — PIPA §22-2·SEC-20",
)
async def revoke_parental_consent(
    request: Request,
    user: Annotated[UserProfile, Depends(get_current_user)],
    session: SessionDep,
    settings: SettingsDep,
    scope: Annotated[
        ConsentScope | None,
        Query(description="철회할 동의 scope. 미지정 시 전체 철회."),
    ] = None,
) -> ParentalConsentRevokeResponse:
    """법정대리인 동의를 철회하고 미성년 동의 게이트를 다시 닫는다(SEC-20 D9).

    **scope 파라미터**: 특정 scope(예: `ai_training`)만 철회하려면 query string으로
    `?scope=ai_training`를 전달. 미지정 시 모든 미철회 동의를 철회(기존 동작).
    `service_core`를 철회하면 `parent_consent_at`을 해제해 서비스 이용 게이트를 닫는다.
    `ai_training` 등 다른 scope만 철회하면 서비스 이용은 유지되고 해당 목적 처리만 중단.

    **인증 게이트가 `get_current_user`인 이유**: GRANT와 동형이다. 이미 만료·철회된 미성년은
    `get_consented_user`가 403으로 막으므로 동의 상태를 *바꾸는* 경로가 그 뒤에 있으면 도달할 수
    없다(닭-달걀). 본인 스코핑은 경로(`me`)와 토큰이 함께 보장한다.

    **접근 주체 축소(v0·의도적)**: 지금 여는 것은 **학생 본인 토큰** 경로뿐이다. 법정대리인이
    자기 화면에서 철회하는 경로는 *보호자를 어떻게 인증할 것인가*(`MGMT-01` 법정대리인 인증
    모델·blocked)가 정해져야 만들 수 있고, 그전에 만들면 가짜 법적 의사표시가 된다.

    **원장은 지우지 않는다**: append-only 방침 유지 — 미철회 동의 행에 `revoked_at`을 찍는다.
    `service_core`가 철회되면 `parent_consent_at`을 해제한다. 감사 1행이 같은 트랜잭션.

    멱등: 이미 철회 상태면 `revoked_count=0`으로 200을 돌려준다(반복 호출 안전).
    """
    now = datetime.now(tz=timezone.utc)
    # 1. 미철회 동의 행 조회 — scope 미지정 시 전체, 지정 시 해당 scope만.
    where_clause = [
        ParentalConsent.user_id == user.user_id,
        ParentalConsent.revoked_at.is_(None),
    ]
    if scope is not None:
        where_clause.append(ParentalConsent.consent_scope == scope.value)
    rows = list((await session.scalars(select(ParentalConsent).where(*where_clause))).all())
    for row in rows:
        row.revoked_at = now

    # 2. service_core 철회 시에만 게이트 근거 해제. 다른 scope만 철회하면 서비스 이용은 유지.
    revoked_scopes = {
        ConsentScope(row.consent_scope) if row.consent_scope else ConsentScope.service_core
        for row in rows
    }
    if scope is None or _effective_service_scope(scope) is ConsentScope.service_core:
        # service_core가 포함된 철회면 parent_consent_at 해제.
        user.parent_consent_at = None
        await session.merge(user)

    # 3. SEC-09 감사 — 철회된 scope 중 하나를 기록. 여러 scope가 한꺼번에 철회되면
    #    service_core를 우선(가장 보수적), 아니면 첫 번째 scope.
    audit_scope = ConsentScope.service_core
    if ConsentScope.service_core not in revoked_scopes and rows:
        first_scope = rows[0].consent_scope or ConsentScope.service_core.value
        audit_scope = ConsentScope(first_scope)
    record_consent_change_audit(
        session,
        user_id=user.user_id,
        consent_scope=audit_scope,
        ip=_client_ip(request, settings=settings),
        settings=settings,
    )
    await session.commit()
    return ParentalConsentRevokeResponse(revoked_at=now, revoked_count=len(rows))


@router.get(
    "/me/parental-consent",
    response_model=ParentalConsentHistoryResponse,
    summary="내 동의 내역 조회 — scope별 최신 상태",
)
async def read_parental_consent_history(
    user: Annotated[UserProfile, Depends(get_current_user)],
    session: SessionDep,
) -> ParentalConsentHistoryResponse:
    """현재 로그인한 사용자(또는 그 보호자)의 동의 scope별 최신 상태를 반환.

    법정대리인 이메일·해시 등 PII는 응답에 포함하지 않는다.
    """
    # 각 scope별 최신 동의 행을 한 번에 조회.
    all_consents = list(
        (
            await session.scalars(
                select(ParentalConsent).where(ParentalConsent.user_id == user.user_id)
            )
        ).all()
    )

    def _latest(scope_value: str) -> ParentalConsent | None:
        matches = [c for c in all_consents if c.consent_scope == scope_value]
        if not matches:
            return None
        return max(
            matches,
            key=lambda c: (
                c.consent_signed_at
                if c.consent_signed_at is not None
                else (c.created_at or datetime.min.replace(tzinfo=timezone.utc))
            ),
        )

    now = datetime.now(tz=timezone.utc)
    statuses: list[ConsentScopeStatus] = []
    for scope in ConsentScope:
        latest = _latest(scope.value)
        if latest is None:
            statuses.append(
                ConsentScopeStatus(
                    scope=scope, status="NEVER_GRANTED", granted_at=None, expires_at=None
                )
            )
            continue
        if latest.revoked_at is not None:
            statuses.append(
                ConsentScopeStatus(
                    scope=scope,
                    status="WITHDRAWN",
                    granted_at=latest.consent_signed_at,
                    expires_at=None,
                )
            )
        elif latest.expires_at is not None and latest.expires_at <= now:
            statuses.append(
                ConsentScopeStatus(
                    scope=scope,
                    status="EXPIRED",
                    granted_at=latest.consent_signed_at,
                    expires_at=latest.expires_at,
                )
            )
        else:
            statuses.append(
                ConsentScopeStatus(
                    scope=scope,
                    status="GRANTED",
                    granted_at=latest.consent_signed_at,
                    expires_at=latest.expires_at,
                )
            )

    return ParentalConsentHistoryResponse(scopes=statuses)
