"""문제(problem) 도메인 HTTP API — concept 라우터와 동형의 DB-backed CRUD-read.

엔드포인트(prefix `/v1/problems`):
  - POST   /v1/problems          — 문제 생성(검증된 schema.Problem → ORM → commit). 201.
  - GET    /v1/problems/{id}     — 단건 조회(UUID). 없으면 404.
  - GET    /v1/problems          — 목록(최신순, limit/offset, subject 선택 필터).

세션 결선·트랜잭션 책임·Annotated 의존성 패턴은 concepts.py와 동일(session.py 계약).
`external_id`/`slug`는 UNIQUE라 중복 시 IntegrityError→409.

경계 메모(CLAUDE.md 절대 금기): 본문 보유 금지 불변식(평가원·EBS·교과서 출처는 question_text
미저장·license=WHYMATH_GENERATED 강제 등)은 *schema.Problem after-validator*가 이미 강제한다
— 이 라우터는 검증 통과한 모델만 영속화한다. 학생 표면화 전 LLM 생성물은 L3/app.py 소관.

인가(SEC-07 D1): POST/PATCH/DELETE 3개는 `RequireContentAdmin`(`Role.CONTENT_ADMIN`)로
게이팅한다 — 이전엔 인증 의존성이 0건이라 누구나 문제를 생성·수정·삭제할 수 있었다(실측
`docs/architecture/account_security_gap_review.md` D1). GET(단건·목록·steps·relations)은
*무인증 유지*(공개 카탈로그·현 클라·데모 경로 파괴 금지 — 봉인 범위 과확대 방지).

정답류 비노출(SEC-24(원 SEC-15) — `functional_security_audit_2026-08-08.md` M1): 무인증 GET의
response_model은 `PublicProblem`/`PublicProblemStep`(공개 투영 — 정답류 필드에 *자리가
없다*, 키 부재가 계약)이다. SEC-07 D1의 공개 카탈로그(본문·메타)는 유지하되 정답류만
구조적으로 뺀다 — D1은 본문 공개 결정이었지 정답 동봉 결정이 아니었다(감사 M1: 저작권
강제-비움 목록에서 answer가 *빠진* 누락). 관리자 표면(POST/PATCH — RequireContentAdmin
게이트)은 전체 `ProblemSchema`를 유지한다. Kiki가 D1을 정답까지 공개로 확장하기로
결정하면 GET의 response_model을 되돌리면 된다(가역 — 안전측 재량 판단).

격리 비노출(EOS-71): 무인증 GET 4종(단건·목록·steps·relations)은 `review_status=quarantined`
문항을 내보내지 않는다 — 단건류는 404, 목록은 SQL 레벨 배제(`quarantine_exclusion_condition`).
운영 중 사후 결함 판정(정답 오류·복수 정답·모호 문장 등)을 받은 문항의 **비파괴 회수** 경로이며,
레코드·`problem_attempt` 학습 기록은 보존하고 노출만 끊는다. 이 4종이 격리를 놓치던 구멍이었다
— 나머지 노출 경로(L6 6모드·blueprint·기본 CAT)는 `approved` 허용목록이라 자동 배제된다.
계약 정본: `docs/standards/problem_quarantine_contract.md`.

ETag(SEC-24): 모든 ETag는 **공개 투영 기준**으로 계산한다 — 전체 스키마 해시를 무인증
GET에 노출하면, 공개 필드를 다 아는 공격자가 정답 후보(예: 1~999)를 오프라인 대입해
해시 일치로 정답을 복원하는 *오라클*이 된다. 공개 투영 기준이면 GET(공개)↔PATCH/DELETE
(If-Match)가 단일 토큰 체계로 정합하고 오라클이 닫힌다. 대가: 정답류 *단독* 변경은
ETag를 바꾸지 않아 그 축의 낙관적 동시성 감지가 약해진다(수용 — 보안 ≫ 편의).
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import ColumnElement, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.api._auth import RequireContentAdmin
from whymath_backend.api._concurrency import (
    ensure_if_match,
    etag_for,
    matches_if_none_match,
)
from whymath_backend.api._rate_limit import _client_ip
from whymath_backend.config import get_settings
from whymath_backend.db.models.problem import Problem, ProblemRelation, ProblemStep
from whymath_backend.db.session import get_session
from whymath_backend.privacy.audit import record_content_mutation_audit
from whymath_backend.schema.enums import (
    PrivacyAuditAction,
    PrivacyAuditResourceType,
    ReviewStatus,
    Subject,
    is_review_status_quarantined,
)
from whymath_backend.schema.problem import Problem as ProblemSchema
from whymath_backend.schema.problem import ProblemRelation as ProblemRelationSchema
from whymath_backend.schema.problem import PublicProblem, PublicProblemStep

router = APIRouter(prefix="/v1/problems", tags=["problem"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# EOS-71 격리(quarantined) 비노출 게이트 — 이 라우터의 무인증 GET 4종 전용
# ──────────────────────────────────────────────────────────────────────────
# **왜 여기에만 두는가**: 격리 배제를 위해 코드를 더해야 하는 표면은 이 파일뿐이다. L6 6모드
# 게이팅·blueprint 조립(`_shared.is_review_cleared`)·기본 CAT 후보 풀(`api/me.py::
# candidate_pool_conditions`)·빌드타임 상속 필터는 전부 "`approved`만 통과"라는 **허용목록**이라,
# `quarantined`가 새 값이라는 이유만으로 *이미* fail-closed로 배제된다 — 거기에 조건을 더하면
# 중복 게이트가 되고 나중에 두 기준이 갈라진다. 반면 이 라우터의 공개 카탈로그 GET은 검수 통과를
# 요구하지 않아(SEC-07 D1 — `pending`·NULL 문항도 그대로 나간다) 격리 문항이 풀이 단계까지 새
# 나가던 **유일한 구멍**이었다.
#
# 아래 두 함수가 그 판정의 **단일 정의**다(SQL 축·행 축). 4개 라우트가 각자 조건을 적으면
# `candidate_pool_conditions`가 REC-06에서 막은 것과 같은 기준 이원화가 생긴다.
# 계약 정본: `docs/standards/problem_quarantine_contract.md` §4(집행 지점 표).


def quarantine_exclusion_condition() -> ColumnElement[bool]:
    """격리 문항 SQL 배제 술어 — 공개 목록 조회의 WHERE 한 줄(단일 정의).

    ⚠️ **`!=` 금지(SQL 3값 논리 함정)**: `Problem.review_status != 'quarantined'`로 쓰면
    `review_status`가 NULL인 행에서 비교 결과가 NULL이 되고, WHERE는 NULL을 참으로 치지 않아
    **검수 미평가 문항이 전부 목록에서 조용히 사라진다**. 실코퍼스에는 `review_status`가 비어 있는
    레코드가 실제로 존재하므로(백필 대상 — `harness/problem_corpus_review_status_backfill.py`) 이건
    이론적 위험이 아니라 즉시 발현하는 회귀다. 그래서 NULL을 값으로 취급해 비교하는
    `IS DISTINCT FROM`을 쓴다 — NULL 행은 "격리가 아니다"로 남는다.

    `tests/backend/api/test_problem_quarantine_serving.py`가 컴파일된 SQL에 `IS DISTINCT FROM`이
    있는지를 단언해 `!=`로의 회귀를 막는다(뮤테이션 변별력 확인 완료).

    Returns:
      `review_status IS DISTINCT FROM 'quarantined'` — 격리가 아닌 행만 남기는 조건.
    """
    return Problem.review_status.is_distinct_from(ReviewStatus.quarantined)


def _reject_if_quarantined(orm: Problem, problem_id: uuid.UUID) -> None:
    """단건 경로의 격리 게이트 — 격리 문항이면 404로 끊는다(존재하지만 노출하지 않는다).

    **왜 404인가**: 이 라우터의 GET은 무인증 공개 표면이라 403(존재하나 금지)으로 답하면 "그 id에
    문항이 있다"를 확인해 주는 오라클이 된다(모듈 docstring SEC-24의 ETag 오라클과 같은 논거).
    부재와 비노출을 클라 입장에서 같은 상태코드로 접는다.

    **침묵 실패 금지**: `detail`을 일반 404("문제를 찾을 수 없습니다")와 *다르게* 적고 로그도 남겨,
    이 비노출이 데이터 부재가 아니라 **운영 격리 판정** 때문임이 응답·로그 양쪽에 남게 한다. 다만
    사유 본문(`quarantine_reason`)은 싣지 않는다 — 운영 메타이고 여긴 무인증 표면이다
    (`schema/problem.py` `PUBLIC_HIDDEN_OPS_FIELDS`).

    Args:
      orm: 조회된 문항 ORM 행(호출자가 부재 404를 이미 처리한 뒤 넘긴다).
      problem_id: 경로에서 받은 문항 id(응답·로그 식별용).

    Raises:
      HTTPException: 404 — `review_status`가 `quarantined`일 때.
    """
    if not is_review_status_quarantined(orm.review_status):
        return
    _logger.info(
        "격리 문항 비노출(EOS-71) — 공개 GET 차단: problem_id=%s review_status=%s",
        problem_id,
        orm.review_status,
    )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=(
            f"격리(quarantined)된 문항이라 노출하지 않습니다: {problem_id}. "
            "결함 판정으로 회수된 문항이며 레코드·학습 기록은 보존됩니다."
        ),
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ProblemSchema,
    summary="문제 생성",
)
async def create_problem(
    body: ProblemSchema,
    session: SessionDep,
    response: Response,
    admin: RequireContentAdmin,
    request: Request,
) -> ProblemSchema:
    """검증된 schema.Problem을 영속화하고 복원해 반환한다(201). `Role.CONTENT_ADMIN` 전용.

    `external_id`/`slug`는 UNIQUE이므로 중복이면 PG가 IntegrityError → 롤백 후 **409**.
    본문 보유 금지 등 출처별 불변식은 schema.Problem이 이미 검증했다(경계 메모 참조).
    응답에 ETag(공개 투영 기준 — 모듈 docstring SEC-24 오라클 항목)를 실어 이후 조건부
    수정(If-Match)을 가능케 한다. 응답 본문은 관리자 표면이라 전체 스키마 유지.

    SEC-29: 성공 시 `record_content_mutation_audit`로 감사 행을 같은 트랜잭션에 합류시킨다
    (IntegrityError로 롤백되면 감사 행도 함께 롤백 — 실패한 시도는 감사하지 않는다).
    """
    orm = Problem.from_schema(body)
    session.add(orm)
    settings = get_settings()
    record_content_mutation_audit(
        session,
        actor_user_id=admin.user_id,
        resource_type=PrivacyAuditResourceType.problem,
        resource_id=orm.problem_id,
        action=PrivacyAuditAction.create,
        ip=_client_ip(request, settings=settings),
        settings=settings,
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 존재하는 external_id 또는 slug입니다.",
        ) from exc
    await session.refresh(orm)
    result = orm.to_schema()
    response.headers["ETag"] = etag_for(PublicProblem.from_problem(result))
    return result


@router.get("/{problem_id}", response_model=PublicProblem, summary="문제 단건 조회(공개 투영)")
async def read_problem(
    problem_id: uuid.UUID,
    session: SessionDep,
    response: Response,
    if_none_match: Annotated[str | None, Header()] = None,
) -> PublicProblem | Response:
    """UUID로 문제 단건 조회 — 없으면 404. **무인증 공개 라우트 → 공개 투영**(SEC-24).

    응답은 `PublicProblem` — 정답류 필드(`PUBLIC_HIDDEN_ANSWER_FIELDS`)는 키 자체가
    없다(값 None이 아니라 부재가 계약). ETag를 싣고, `If-None-Match`가 현재 ETag와
    일치하면 **304 Not Modified**(빈 본문)로 응답해 모바일 대역폭을 아낀다.

    EOS-71: 격리(`quarantined`) 문항은 존재해도 404다(`_reject_if_quarantined`). ETag 계산·304
    분기보다 **앞에** 둔다 — 뒤에 두면 `If-None-Match`를 든 클라가 304로 "여전히 유효함"을 받아
    캐시된 결함 문항을 계속 쓰게 된다.
    """
    orm = await session.get(Problem, problem_id)
    if orm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"문제를 찾을 수 없습니다: {problem_id}",
        )
    _reject_if_quarantined(orm, problem_id)
    result = PublicProblem.from_problem(orm.to_schema())
    etag = etag_for(result)
    if matches_if_none_match(if_none_match, etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    response.headers["ETag"] = etag
    return result


@router.get("", response_model=list[PublicProblem], summary="문제 목록(공개 투영)")
async def list_problems(
    session: SessionDep,
    subject: Annotated[Subject | None, Query(description="과목 필터(선택)")] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="페이지 크기")] = 50,
    offset: Annotated[int, Query(ge=0, description="건너뛸 행 수")] = 0,
) -> list[PublicProblem]:
    """문제 목록 — 최신순(created_at desc, problem_id로 안정 정렬), limit/offset.

    **무인증 공개 라우트 → 공개 투영**(SEC-24 — 정답류 키 부재). `subject`를 주면 해당
    과목만 필터한다. 정렬 보조키로 problem_id(UNIQUE)를 둬 동일 created_at에서도
    페이지네이션이 안정적이다.

    EOS-71: 격리(`quarantined`) 문항은 **SQL 레벨에서** 배제한다(`quarantine_exclusion_condition`).
    파이썬 후처리로 거르면 limit/offset이 격리 문항까지 세어 페이지가 조용히 짧아진다.
    """
    stmt = select(Problem).where(quarantine_exclusion_condition())
    if subject is not None:
        stmt = stmt.where(Problem.subject == subject)
    stmt = stmt.order_by(Problem.created_at.desc(), Problem.problem_id).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return [PublicProblem.from_problem(row.to_schema()) for row in result.scalars().all()]


@router.get(
    "/{problem_id}/steps",
    response_model=list[PublicProblemStep],
    summary="문제 풀이 단계 목록(공개 투영)",
)
async def list_problem_steps(problem_id: uuid.UUID, session: SessionDep) -> list[PublicProblemStep]:
    """문제의 풀이 단계(Polya·Socratic) 목록 — step_order 순. 문제 없으면 404.

    **무인증 공개 라우트 → 공개 투영**(SEC-24): `expected_answer`(단계 정답·S4-09 승격
    어댑터가 `SolutionStep.content`를 싣는 좌석)·`common_mistakes`/`common_errors`(힌트·
    오개념류)는 키 자체가 없다 — 코치(L4)가 서버 내부에서만 쓴다.

    하위 리소스 read 전용(단계 생성/수정은 범위 밖). 부모 부재를 빈 목록과 구분하기 위해
    먼저 문제 존재를 확인한다.

    S4-09(D1) reader ① 소생: WH-S 승격 어댑터(`whs/path_promotion.py`)가 `problem_step`에
    실데이터를 적재하면서 빈 테이블 위 dead API에서 벗어났다. 승격 단계는 additive 필드
    (`solution_path_id`·`concept_node_id`·`reasoning_type`·`justification`·`common_errors`·
    `sympy_verified`)를 함께 싣는다 — 기존 필드 제거·의미 변경 0(스키마 하위호환).

    EOS-71: 부모 문항이 격리(`quarantined`)면 404다. 단건 조회보다 **더 강하게** 막아야 하는
    표면이다 — 결함 문항의 *풀이 경로*를 보여주는 것은 틀린 답으로 가는 길을 안내하는 것이다.
    """
    parent = await session.get(Problem, problem_id)
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"문제를 찾을 수 없습니다: {problem_id}",
        )
    _reject_if_quarantined(parent, problem_id)
    stmt = (
        select(ProblemStep)
        .where(ProblemStep.problem_id == problem_id)
        .order_by(ProblemStep.step_order)
    )
    result = await session.execute(stmt)
    return [PublicProblemStep.from_step(row.to_schema()) for row in result.scalars().all()]


@router.get(
    "/{problem_id}/relations",
    response_model=list[ProblemRelationSchema],
    summary="문항 간 관계 목록",
)
async def list_problem_relations(
    problem_id: uuid.UUID, session: SessionDep
) -> list[ProblemRelationSchema]:
    """이 문제가 출발점인(outgoing) 문항 관계 목록 — 문제 없으면 404.

    `parent_problem_id == path`인 관계만(나가는 방향). 역방향·양방향은 후속.

    EOS-71: 출발점 문항이 격리(`quarantined`)면 404다. 관계 목록은 결함 문항에서 다른 문항으로
    가는 **탐색 경로**라, 격리 문항을 진입점으로 남겨 두면 회수한 문항이 계속 카탈로그를 매개한다.
    (관계 *대상* 문항의 격리 여부는 이 라우터가 판정하지 않는다 — 대상은 각자의 단건 GET에서
    걸러진다. 여기서 조인해 거르면 관계 그래프의 결손을 조용히 만든다.)
    """
    parent = await session.get(Problem, problem_id)
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"문제를 찾을 수 없습니다: {problem_id}",
        )
    _reject_if_quarantined(parent, problem_id)
    stmt = (
        select(ProblemRelation)
        .where(ProblemRelation.parent_problem_id == problem_id)
        .order_by(ProblemRelation.related_problem_id, ProblemRelation.relation_type)
    )
    result = await session.execute(stmt)
    return [row.to_schema() for row in result.scalars().all()]


@router.patch("/{problem_id}", response_model=ProblemSchema, summary="문제 부분 수정")
async def patch_problem(
    problem_id: uuid.UUID,
    body: dict[str, Any],
    session: SessionDep,
    response: Response,
    admin: RequireContentAdmin,
    request: Request,
    if_match: Annotated[str | None, Header()] = None,
) -> ProblemSchema:
    """제공된 필드만 부분 수정 — 병합 결과를 schema로 *재검증*해 불변식(본문 보유 금지 등)을
    유지한다. `Role.CONTENT_ADMIN` 전용. `problem_id`(PK)는 경로 고정. 없으면 404, 병합 결과
    스키마 위반 422, `external_id`/`slug` UNIQUE 충돌 409. **낙관적 동시성**: `If-Match`(GET
    ETag)를 보내면 그사이 변경됐을 때 412로 거부한다(미전송 시 무조건 진행 — 비파괴). 응답에
    새 ETag를 싣는다. ETag는 공개 투영 기준(모듈 docstring SEC-24 — GET이 공개 투영
    ETag를 주므로 여기서도 같은 기준으로 비교해야 If-Match 흐름이 정합한다).

    SEC-29: 성공 시 `record_content_mutation_audit`로 감사 행을 같은 트랜잭션에 합류시킨다.
    """
    existing = await session.get(Problem, problem_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"문제를 찾을 수 없습니다: {problem_id}",
        )
    ensure_if_match(if_match, etag_for(PublicProblem.from_problem(existing.to_schema())))
    merged = existing.to_schema().model_dump()
    merged.update(body)
    merged["problem_id"] = problem_id  # PK는 경로 고정
    try:
        validated = ProblemSchema.model_validate(merged)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "수정 본문 병합 결과가 스키마를 위반합니다(본문 보유 금지 등).",
                "errors": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()],
            },
        ) from exc
    updated = await session.merge(Problem.from_schema(validated))
    settings = get_settings()
    record_content_mutation_audit(
        session,
        actor_user_id=admin.user_id,
        resource_type=PrivacyAuditResourceType.problem,
        resource_id=problem_id,
        action=PrivacyAuditAction.update,
        ip=_client_ip(request, settings=settings),
        settings=settings,
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 존재하는 external_id 또는 slug입니다.",
        ) from exc
    result = updated.to_schema()
    response.headers["ETag"] = etag_for(PublicProblem.from_problem(result))
    return result


@router.delete("/{problem_id}", status_code=status.HTTP_204_NO_CONTENT, summary="문제 삭제")
async def delete_problem(
    problem_id: uuid.UUID,
    session: SessionDep,
    admin: RequireContentAdmin,
    request: Request,
    if_match: Annotated[str | None, Header()] = None,
) -> Response:
    """문제 삭제 — 없으면 404. 풀이단계·관계·시도 등 참조가 있으면 FK 위반 → 409.
    `Role.CONTENT_ADMIN` 전용.

    cascade를 ORM에 두지 않았으므로 참조가 있으면 삭제를 거부한다(가짜 cascade 금지).
    `If-Match`를 보내면 그사이 변경된 리소스의 삭제를 412로 막는다(조건부 삭제 —
    비교 기준은 공개 투영 ETag·모듈 docstring SEC-24).

    SEC-29: 성공 시 `record_content_mutation_audit`로 감사 행을 같은 트랜잭션에 합류시킨다
    (FK 위반으로 롤백되면 감사 행도 함께 롤백).
    """
    existing = await session.get(Problem, problem_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"문제를 찾을 수 없습니다: {problem_id}",
        )
    ensure_if_match(if_match, etag_for(PublicProblem.from_problem(existing.to_schema())))
    await session.delete(existing)
    settings = get_settings()
    record_content_mutation_audit(
        session,
        actor_user_id=admin.user_id,
        resource_type=PrivacyAuditResourceType.problem,
        resource_id=problem_id,
        action=PrivacyAuditAction.delete,
        ip=_client_ip(request, settings=settings),
        settings=settings,
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이 문제를 참조하는 단계·관계·시도가 있어 삭제할 수 없습니다.",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
