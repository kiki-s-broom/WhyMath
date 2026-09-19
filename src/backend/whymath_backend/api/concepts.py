"""개념(concept) 도메인 HTTP API — 첫 DB-backed 라우터 (영속 레이어 → HTTP 표면).

엔드포인트(prefix `/v1/concepts`):
  - POST   /v1/concepts          — 개념 생성(검증된 schema.Concept → ORM → commit). 201.
  - GET    /v1/concepts/{id}     — 단건 조회(UUID). 없으면 404.
  - GET    /v1/concepts          — 목록(code 오름차순, limit/offset 페이지네이션).

세션 결선: `db.session.get_session` 의존성을 `Annotated[AsyncSession, Depends(...)]`로 받는다
(Depends를 기본인자에 두면 ruff B008·mypy가 막으므로 Annotated 메타데이터로 둔다 — FastAPI
현행 권장 패턴). 트랜잭션 commit/rollback은 *핸들러 책임*이다(get_session은 세션을 열고
닫기만 함 — 읽기 요청까지 강제 commit하지 않으려는 session.py 계약).

schema↔ORM seam은 `Concept.from_schema`/`to_schema`(problem.py 패턴)가 담당한다 — 핸들러는
PG 행을 직접 만지지 않고 검증된 Pydantic 모델만 주고받는다.

경계 메모(CLAUDE.md): `description`·`formal_definition` 등 교수 텍스트는 *자체 작성*이어야
하며(검정교과서·EBS 본문 복제 금지) — 이 불변식은 schema.Concept 검수 단계 책임이고 이
라우터는 이미 검증된 모델을 영속화할 뿐이다.

인가(SEC-07 D1): POST/PATCH/DELETE 3개는 `RequireContentAdmin`(`Role.CONTENT_ADMIN`)로
게이팅한다 — 이전엔 인증 의존성이 0건이라 누구나 개념을 생성·수정·삭제할 수 있었다(실측
`docs/architecture/account_security_gap_review.md` D1). GET(단건·목록·엣지·의미검색)은
*무인증 유지*(공개 카탈로그·현 클라·데모 경로 파괴 금지 — 봉인 범위 과확대 방지).

의미검색(S0-4a — runtime truth source=원자 전환): `GET /v1/concepts/search`가 적재된 *원자*
임베딩(`atom_embedding` pgvector·Phase 2b)을 조회하고, 잡힌 원자 code들의 안전 메타(name_ko·
subject_area·review_status)를 `atom_node`(PG 프로젝션·Phase 2a) 조인으로 enrich한다.
`reviewed_only` 쿼리로 검수 게이팅(필터)을 건다. 이건 *조회 좌석*(L1 데이터 서빙)을 HTTP로
노출하는 표면이고, 검색·enrich·게이팅 로직은 `l1/atom_graph/retrieval.search_atoms`가 소유한다
(L5는 표면·L1은 서빙). 메타 브리지는 **PG 프로젝션**(backend↔Neo4j 런타임 연결 0 — 확정 설계
결정). **학생 직접 노출이 아니라** L2/L4·교사 도구가 소비하는 내부 표면이고, enrich는 안전 표시·
게이팅 필드뿐(본문 0 — atom_node에 core_proposition·description·formal_definition 컬럼 자체가
없음·redaction).

**응답 계약 안정(경로·스키마 유지)**: 클라 계약 안정을 위해 경로(`/v1/concepts/search`)·응답
스키마(`ConceptSearchResponse`)를 유지한다 — 단 `concept_id` 필드는 이제 *원자 code*를, `domain`
필드는 원자 `subject_area`를 담는다(runtime truth source=원자). 구 437(`concept_embedding`/
`concept_node`)은 런타임에서 더 이상 읽지 않는다(S0-4b legacy_snapshot 격하 전제). 원자
`review_status`는 전 행 'ai_estimated'라 `reviewed_only=true`면 결과가 빈다(원자 검수 승격 전
정상·정직).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
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
from whymath_backend.db.models.concept import Concept, ConceptEdge
from whymath_backend.db.models.concept_content import ConceptContent
from whymath_backend.db.session import get_session
from whymath_backend.l1.atom_graph.retrieval import search_atoms
from whymath_backend.l4.misconception.semantic.provider import (
    EmbeddingProvider,
    build_provider,
)
from whymath_backend.privacy.audit import record_content_mutation_audit
from whymath_backend.schema.concept import Concept as ConceptSchema
from whymath_backend.schema.concept import ConceptEdge as ConceptEdgeSchema
from whymath_backend.schema.concept_content import ConceptContentSchema
from whymath_backend.schema.enums import PrivacyAuditAction, PrivacyAuditResourceType

router = APIRouter(prefix="/v1/concepts", tags=["concept"])

# get_session 의존성 — Annotated 메타데이터로 둬 기본인자 호출(B008)을 피한다.
SessionDep = Annotated[AsyncSession, Depends(get_session)]


# ──────────────────────────────────────────────────────────────────────────
# 의미검색 (슬라이스 4) — 적재된 pgvector 임베딩 조회 좌석의 HTTP 표면
# ──────────────────────────────────────────────────────────────────────────
def get_embedding_provider() -> EmbeddingProvider:
    """임베딩 제공자 의존성 — `build_provider`(좌석 팩토리·신규 0) 재사용.

    `build_provider(settings)`는 `local`(기본·bge-m3)·`openai`·`fake` 중 Settings로 고르고,
    **모델·클라이언트는 지연**이라 이 의존성 해석만으로는 모델 로드·네트워크가 없다(첫 embed
    시점). 단위테스트는 `dependency_overrides[get_embedding_provider]`로 `FakeEmbeddingProvider`
    를 주입해 라이브 없이 검색 표면을 검증한다(coach 의미 테스트의 매처 주입과 동형). FastAPI가
    이 의존성을 매 요청 호출하나 build_provider는 가벼운 객체 생성뿐(모델은 lazy)이라 무해하다.
    """
    return build_provider(get_settings())


# 검색 k 상한 — 조회 좌석은 *후보 fan-out*용(L2/L4가 점수로 추려 씀)이라 페이지네이션보다 작게
# 둔다. 1~50: 0은 무의미(빈 결과 강제)·과대 k는 DB·임베딩 공간 무관 비용. list 엔드포인트
# limit(200)과 다른 의미라 별 상한.
_SEARCH_MAX_K = 50
_SEARCH_DEFAULT_K = 10

EmbeddingProviderDep = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]


class ConceptSearchResultItem(BaseModel):
    """의미검색 결과 1건(HTTP) — code + 코사인 유사도 + *안전* 메타(enrich).

    (S0-4a) `atom_graph.retrieval.AtomSearchHit`의 HTTP 직렬화 형태다. 클라 계약 안정을 위해 필드명
    (`concept_id`·`domain`)을 유지하되, 값의 의미는 원자 축으로 바뀌었다: `concept_id`는 이제
    *원자 code*(`atom_embedding`/`atom_node`와 동일 공간·원자ID/소단원코드/단원코드), `domain`은
    원자 `subject_area`다. `similarity`는 코사인 [-1, 1]. `name_ko`·`domain`·`review_status`는
    `atom_node`(PG 프로젝션) 조인으로 붙인 *안전 표시·게이팅 필드*다 — 메타 미적재 code는
    **null**(graceful). **본문(core_proposition·description·formal_definition)은 미포함** —
    프로젝션 테이블에 컬럼 자체가 없다(redaction·노출 계약). 소비처(L2/L4·교사 도구)가 code 키 +
    안전 메타로 동작한다.
    """

    model_config = ConfigDict(extra="forbid")

    concept_id: str = Field(
        description=(
            "원자 code(runtime truth source=원자·`atom_embedding`/`atom_node`와 동일 공간). "
            "필드명은 클라 계약 안정을 위해 유지하되 값은 원자 code다(S0-4a)."
        )
    )
    similarity: float = Field(
        description="질의 임베딩과의 코사인 유사도 [-1, 1](클수록 의미 근접)."
    )
    name_ko: str | None = Field(
        default=None,
        description="원자 한국어 명칭(atom_node 조인·안전 표시 필드). 메타 미적재 시 null.",
    )
    domain: str | None = Field(
        default=None,
        description=(
            "원자 영역명(atom_node.subject_area 조인·안전 표시 필드). 필드명은 계약 안정 유지·"
            "값은 subject_area. 메타 미적재·subject_area 부재 시 null."
        ),
    )
    review_status: str | None = Field(
        default=None,
        description=(
            "검수 상태(atom_node 조인·게이팅·원자는 전 행 'ai_estimated'). 미적재 시 null."
        ),
    )


class ConceptSearchResponse(BaseModel):
    """개념 의미검색 응답(HTTP) — 질의 에코 + 랭킹된 결과 목록.

    `results`는 유사도 내림차순(상위 top_k). `vector_store_enabled`는 영속 임베딩 store(pgvector)
    가 켜졌는지다 — `false`면(memory 모드) 적재 임베딩이 없어 `results`가 항상 비고, 소비처가
    "검색 미가용"을 *조용한 빈 결과*와 구분하도록 명시 신호를 준다(조용한 무동작 금지).
    """

    model_config = ConfigDict(extra="forbid")

    query: str = Field(description="검색 질의 텍스트(에코).")
    results: list[ConceptSearchResultItem] = Field(
        description="유사도 내림차순 랭킹 결과(상위 top_k)."
    )
    vector_store_enabled: bool = Field(
        description=(
            "영속 임베딩 store(pgvector) 활성 여부. false면 memory 모드라 적재 임베딩이 없어 "
            "results가 항상 빈다(검색 미가용 — 조용한 빈 결과와 구분하는 명시 신호)."
        )
    )


@router.get(
    "/search",
    response_model=ConceptSearchResponse,
    summary="개념 의미검색(조회 좌석)",
)
async def search_concepts_endpoint(
    provider: EmbeddingProviderDep,
    q: Annotated[
        str,
        Query(min_length=1, max_length=500, description="검색 질의 텍스트(필수·비공백)."),
    ],
    k: Annotated[
        int,
        Query(ge=1, le=_SEARCH_MAX_K, description=f"반환 후보 수(1~{_SEARCH_MAX_K})."),
    ] = _SEARCH_DEFAULT_K,
    reviewed_only: Annotated[
        bool,
        Query(
            description=(
                "검수 게이팅. false(기본)=recall 보존(pending 개념도 노출). true=상위 k 창에서 "
                "review_status='reviewed'만 남김(필터·유사도 정렬 유지)."
            ),
        ),
    ] = False,
) -> ConceptSearchResponse:
    """적재된 *원자* 임베딩(pgvector·Phase 2b)에 대한 의미검색 — 코사인 상위 k + 메타 enrich·게이팅.

    (S0-4a) 질의 `q`를 임베딩해 `search_atoms`(L1 조회 좌석)로 코사인 상위 k를 받고, 잡힌 원자
    code들의 안전 메타(name_ko·subject_area·review_status)를 `atom_node`(PG 프로젝션) 조인으로
    enrich한다(메타 브리지=PG 프로젝션·backend↔Neo4j 런타임 연결 0). `reviewed_only=true`면 검수 안
    된 원자를 *필터*한다(유사도 정렬 유지 — 원자는 전 행 'ai_estimated'라 이 경우 결과가 빈다).
    검색 좌석은 *블로킹*(임베딩 + sync psycopg 검색·메타 조인)이라 `asyncio.to_thread`로 워커
    스레드에서 돌린다 — 이벤트 루프를 막지 않게(CLAUDE.md p50<2s·동시 요청 보호). 요청 검증은
    Query 제약(q 필수·비공백·k 범위)이 한다(위반 시 422 — list 엔드포인트 패턴 동형).

    **응답 계약**: 경로·응답 스키마는 유지한다(클라 계약 안정) — `concept_id` 필드는 원자 code를,
    `domain` 필드는 원자 subject_area를 담는다(runtime truth source=원자). 구 437은 런타임에서
    읽지 않는다.

    **노출 계약(CLAUDE.md)**: 학생 직접 노출이 아니라 L2/L4·교사 도구가 소비하는 *조회 좌석*이다.
    enrich되는 건 안전 표시·게이팅 필드(name_ko·subject_area·review_status)뿐 — **본문
    (core_proposition·description·formal_definition) 0**(atom_node에 컬럼 자체가 없음·redaction).
    우열 매기기·정답 빠르게 등 금기 표현 0. memory 모드면 `vector_store_enabled=false` + 빈
    `results`로 *명시* 안내한다(조용한 무동작 금지 — 좌석이 정직하게 "미가용/없음"을 반환하고
    표면이 그 신호를 그대로 노출).
    """
    enabled = get_settings().vector_store == "pgvector"
    # 검색 좌석은 동기(블로킹 임베딩·sync psycopg 검색+메타 조인) → 워커 스레드로(이벤트 루프
    # 보호). memory 모드면 search_atoms가 즉시 빈 리스트를 돌려준다(좌석 내부 graceful).
    # (S0-4a) runtime truth source=원자 — 좌석을 `search_atoms`로 전환. 응답 필드 `concept_id`는
    # 이제 *원자 code*를, `domain`은 원자 `subject_area`를 담는다(스키마·경로 계약 안정 유지).
    hits = await asyncio.to_thread(
        search_atoms, q, top_k=k, provider=provider, reviewed_only=reviewed_only
    )
    return ConceptSearchResponse(
        query=q,
        results=[
            ConceptSearchResultItem(
                concept_id=hit.atom_code,
                similarity=hit.similarity,
                name_ko=hit.name_ko,
                domain=hit.subject_area,
                review_status=hit.review_status,
            )
            for hit in hits
        ],
        vector_store_enabled=enabled,
    )


@router.get(
    "/content",
    response_model=list[ConceptContentSchema],
    summary="개념 콘텐츠 목록",
)
async def list_concept_content(
    session: SessionDep,
    reviewed_only: Annotated[
        bool,
        Query(
            description=("검수 게이팅. false(기본)=전체 콘텐츠. true='reviewed' 상태만 반환."),
        ),
    ] = False,
    scope: Annotated[str | None, Query(description="scope 필터 (K-12|대학).")] = None,
    subject: Annotated[str | None, Query(description="subject 필터.")] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="페이지 크기")] = 50,
    offset: Annotated[int, Query(ge=0, description="건너뛸 행 수")] = 0,
) -> list[ConceptContentSchema]:
    """`concept_content` PG 프로젝션 조회 좌석 — 콘텐츠 4종·설명·암기카드·검수 상태.

    **노출 계약**: 학생 직접 노출이 아니라 L2/L4·교사 도구가 소비하는 *내부 표면*이다.
    `formal_definition_internal`은 내부·검수용이므로 학생 렌더 경로에서는 별도 게이팅으로
    제외해야 한다. `reviewed_only=true`면 검수 완료 콘텐츠만 반환(fail-closed).
    """
    stmt = select(ConceptContent)
    if reviewed_only:
        stmt = stmt.where(ConceptContent.review_status == "reviewed")
    if scope is not None:
        stmt = stmt.where(ConceptContent.scope == scope)
    if subject is not None:
        stmt = stmt.where(ConceptContent.subject == subject)
    stmt = stmt.order_by(ConceptContent.code).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return [row.to_schema() for row in result.scalars().all()]


@router.get(
    "/content/{code}",
    response_model=ConceptContentSchema,
    summary="개념 콘텐츠 단건",
)
async def get_concept_content(
    code: Annotated[str, Path(description="`concept_content` 기본키 — 개념 콘텐츠 코드.")],
    session: SessionDep,
) -> ConceptContentSchema:
    """`concept_content` 단건 조회 — 계획서 300 §12 `GET /contents/{id}`의 대응 표면.

    **최소 형태다(P-11 ④)**: 목록 좌석 `GET /v1/concepts/content`와 **같은 응답 스키마**를
    돌려줄 뿐 필드를 늘리지 않는다. 목록에 `code` 필터가 없어 단건 조회 경로가 없던 것을
    메우는 것이 전부이고, 새 표현·새 집계는 만들지 않는다.

    **노출 계약은 목록과 동일하다** — 학생 직접 노출이 아니라 L2/L4·교사 도구가 소비하는
    *내부 표면*이며, `formal_definition_internal`은 학생 렌더 경로에서 별도 게이팅으로
    제외해야 한다. 단건이라고 해서 더 관대하지 않다.

    이 테이블의 기본키는 UUID가 아니라 **코드 문자열**(`concept_content.code`)이다 — 계획서의
    `{id}`를 UUID로 읽어 경로를 만들면 조회가 영구히 0건이 된다.
    """
    row = await session.get(ConceptContent, code)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"개념 콘텐츠를 찾을 수 없다: {code}",
        )
    return row.to_schema()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ConceptSchema,
    summary="개념 노드 생성",
)
async def create_concept(
    body: ConceptSchema,
    session: SessionDep,
    response: Response,
    admin: RequireContentAdmin,
    request: Request,
) -> ConceptSchema:
    """검증된 schema.Concept를 영속화하고 복원해 반환한다(201). `Role.CONTENT_ADMIN` 전용.

    `code`는 UNIQUE이므로 중복이면 PG가 IntegrityError를 던진다 → 롤백 후 **409**로
    명확히 보고한다(스택트레이스 노출 금지 — 시스템 경계 검증). commit은 핸들러 책임이며
    여기서 명시적으로 부른다(get_session은 commit하지 않음). 응답에 ETag를 실어 이후
    조건부 수정(If-Match)을 가능케 한다.

    SEC-29: 성공 시 `record_content_mutation_audit`로 감사 행을 같은 트랜잭션에 합류시킨다
    (IntegrityError로 롤백되면 감사 행도 함께 롤백 — 실패한 시도는 감사하지 않는다).
    """
    orm = Concept.from_schema(body)
    session.add(orm)
    settings = get_settings()
    record_content_mutation_audit(
        session,
        actor_user_id=admin.user_id,
        resource_type=PrivacyAuditResourceType.concept,
        resource_id=orm.concept_id,
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
            detail=f"이미 존재하는 개념 code입니다: {body.code}",
        ) from exc
    await session.refresh(orm)
    result = orm.to_schema()
    response.headers["ETag"] = etag_for(result)
    return result


@router.get("/{concept_id}", response_model=ConceptSchema, summary="개념 단건 조회")
async def read_concept(
    concept_id: uuid.UUID,
    session: SessionDep,
    response: Response,
    if_none_match: Annotated[str | None, Header()] = None,
) -> ConceptSchema | Response:
    """UUID로 개념 단건 조회 — 없으면 404.

    ETag(낙관적 동시성 검증자)를 응답에 싣는다. `If-None-Match`가 현재 ETag와 일치하면
    내용이 안 바뀐 것이므로 **304 Not Modified**(빈 본문)로 응답해 모바일 대역폭을 아낀다.
    """
    orm = await session.get(Concept, concept_id)
    if orm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"개념을 찾을 수 없습니다: {concept_id}",
        )
    result = orm.to_schema()
    etag = etag_for(result)
    if matches_if_none_match(if_none_match, etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    response.headers["ETag"] = etag
    return result


@router.get("", response_model=list[ConceptSchema], summary="개념 목록")
async def list_concepts(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200, description="페이지 크기")] = 50,
    offset: Annotated[int, Query(ge=0, description="건너뛸 행 수")] = 0,
) -> list[ConceptSchema]:
    """개념 목록 — `code` 오름차순, limit/offset 페이지네이션.

    정렬 키를 code(UNIQUE)로 고정해 페이지네이션이 안정적(동률 없는 전순서)이다.
    """
    stmt = select(Concept).order_by(Concept.code).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return [row.to_schema() for row in result.scalars().all()]


@router.get(
    "/{concept_id}/edges",
    response_model=list[ConceptEdgeSchema],
    summary="개념 의존 엣지 목록",
)
async def list_concept_edges(concept_id: uuid.UUID, session: SessionDep) -> list[ConceptEdgeSchema]:
    """이 개념에서 나가는(outgoing) 그래프 엣지 목록 — 개념 없으면 404.

    `from_concept_id == path`인 엣지만(나가는 방향, `idx_concept_edge_from` 활용). 역방향은 후속.
    주의: 이건 backend PG `concept_edge`이며, data-pipeline의 Neo4j concept_graph와 *별개*다
    (다른 키 공간·다른 저장소).
    """
    if await session.get(Concept, concept_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"개념을 찾을 수 없습니다: {concept_id}",
        )
    stmt = (
        select(ConceptEdge)
        .where(ConceptEdge.from_concept_id == concept_id)
        .order_by(ConceptEdge.to_concept_id, ConceptEdge.edge_type)
    )
    result = await session.execute(stmt)
    return [row.to_schema() for row in result.scalars().all()]


@router.patch("/{concept_id}", response_model=ConceptSchema, summary="개념 부분 수정")
async def patch_concept(
    concept_id: uuid.UUID,
    body: dict[str, Any],
    session: SessionDep,
    response: Response,
    admin: RequireContentAdmin,
    request: Request,
    if_match: Annotated[str | None, Header()] = None,
) -> ConceptSchema:
    """제공된 필드만 부분 수정 — 병합 결과를 schema로 *재검증*해 불변식을 유지한다.
    `Role.CONTENT_ADMIN` 전용.

    `concept_id`(PK)는 경로로 고정(본문이 덮어쓰지 못함). 없으면 404, 병합 결과가 스키마
    위반(미정의 필드·잘못된 값)이면 422, `code` UNIQUE 충돌이면 409. **낙관적 동시성**:
    `If-Match`(GET ETag)를 보내면 그사이 변경됐을 때 412로 거부한다(미전송 시 무조건 진행 —
    비파괴). `session.merge`로 PK 기준 갱신하고 응답에 새 ETag를 싣는다.

    SEC-29: 성공 시 `record_content_mutation_audit`로 감사 행을 같은 트랜잭션에 합류시킨다.
    """
    existing = await session.get(Concept, concept_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"개념을 찾을 수 없습니다: {concept_id}",
        )
    ensure_if_match(if_match, etag_for(existing.to_schema()))
    merged = existing.to_schema().model_dump()
    merged.update(body)
    merged["concept_id"] = concept_id  # PK는 경로 고정
    try:
        validated = ConceptSchema.model_validate(merged)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "수정 본문 병합 결과가 스키마를 위반합니다.",
                "errors": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()],
            },
        ) from exc
    updated = await session.merge(Concept.from_schema(validated))
    settings = get_settings()
    record_content_mutation_audit(
        session,
        actor_user_id=admin.user_id,
        resource_type=PrivacyAuditResourceType.concept,
        resource_id=concept_id,
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
            detail=f"이미 존재하는 개념 code입니다: {validated.code}",
        ) from exc
    result = updated.to_schema()
    response.headers["ETag"] = etag_for(result)
    return result


@router.delete("/{concept_id}", status_code=status.HTTP_204_NO_CONTENT, summary="개념 삭제")
async def delete_concept(
    concept_id: uuid.UUID,
    session: SessionDep,
    admin: RequireContentAdmin,
    request: Request,
    if_match: Annotated[str | None, Header()] = None,
) -> Response:
    """개념 삭제 — 없으면 404. 이 개념을 참조하는 엣지·매핑이 있으면 FK 위반 → 409.
    `Role.CONTENT_ADMIN` 전용.

    cascade를 ORM에 두지 않았으므로(가짜 cascade 금지) 참조가 있으면 삭제를 거부한다.
    `If-Match`를 보내면 그사이 변경된 리소스의 삭제를 412로 막는다(조건부 삭제).

    SEC-29: 성공 시 `record_content_mutation_audit`로 감사 행을 같은 트랜잭션에 합류시킨다
    (FK 위반으로 롤백되면 감사 행도 함께 롤백).
    """
    existing = await session.get(Concept, concept_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"개념을 찾을 수 없습니다: {concept_id}",
        )
    ensure_if_match(if_match, etag_for(existing.to_schema()))
    await session.delete(existing)
    settings = get_settings()
    record_content_mutation_audit(
        session,
        actor_user_id=admin.user_id,
        resource_type=PrivacyAuditResourceType.concept,
        resource_id=concept_id,
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
            detail="이 개념을 참조하는 엣지·매핑이 있어 삭제할 수 없습니다.",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
