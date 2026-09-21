"""L5 학습 공급 엔드포인트 — `supply()`의 **첫 소비자** + 교수법 처치·결과 기록 (PED-03).

REND-01(렌더 어댑터) → PED-02(런타임 선택·게이트) → CACHE-01(공급·캐시)로 이어진 사슬은
좌석만 서 있고 학생 경로에 배선되지 않아 **한 번도 실행된 적이 없었다**(`supply()` API 소비자 0건).
이 라우터가 그 사슬을 학생 요청에 연결하고, 그 과정에서 생기는 처치·결과를 L2 증거 좌석에 남긴다.

────────────────────────────────────────────────────────────────────────────
왜 objective 스코프인가 (개념 code 스코프가 아니라)
────────────────────────────────────────────────────────────────────────────
`evidence_event`는 `objective_id`(느슨참조)와 `k_type`(NOT NULL)을 요구한다. `learning_objective`
행이 그 둘을 *실값*으로 갖고 있고(`k_type`은 교수법 팩 바인딩 축·`concept_nodes`는 원자 code 배열),
소단원 DSL 컴파일러(`l1/pedagogy/unit_compiler.py`)가 이미 그 행을 만든다. 개념 code만 받으면
objective를 역추적해야 하고 그 매핑이 1:N이라 임의 선택이 생긴다 — 축을 목표에 맞추는 편이 정직하다.

────────────────────────────────────────────────────────────────────────────
"가짜 처치" 금지 — 고른 전략이 실제로 화면을 바꾼다
────────────────────────────────────────────────────────────────────────────
처치 기록은 `supply()`가 **렌더를 끝낸 뒤** 그 결과(`SupplyResult.strategy`)로 남긴다. 고르기만 하고
응답이 전략과 무관하면 그 기록은 유효해 보이지만 틀린 측정이 된다. 어댑터가 전략별로 다른
segments를 내므로(SOCRATIC=질문 중심·DIRECT=설명 중심…) 응답은 실제로 달라진다.

게이트가 요청 전략을 강등한 경우에도 **강등 결과**를 처치로 기록한다 — 학생이 본 것이 처치다.

────────────────────────────────────────────────────────────────────────────
경계
────────────────────────────────────────────────────────────────────────────
- `decide()`를 직접 부르지 않는다. `supply()`만 부른다 — 게이트가 공급 안쪽에 있어 우회 불가라는
  CACHE-01 불변식을 API 층에서도 지킨다.
- 생성 폴백(LLM)은 이 좌석에서 **켜지 않는다**(`generate_request` 미주입). DSL이 없으면 렌더 실패
  사유를 담아 404로 돌려준다 — 학습 공급 첫 배선에서 LLM 비용·환각 표면을 열지 않는다(후속 결정).
- 미성년자: 요청·응답 어디에도 학생 원문 발화가 없다. 기록되는 것은 전략명·공급 경로·개념 code뿐.
- SEC-24(원 SEC-16): `/outcome`은 `/study`가 그 학생에게 발급한 `session_id`만 받는다 —
  소유권 검증은 유일 outcome writer(`record_pedagogy_outcome`) 안쪽에서 일어나고,
  이 라우터는 검증 실패를 HTTP(403·409)로 번역만 한다.

7계층: L5(api)가 세션을 보유하고 L4 공급(`supply`)·L2 기록(`pedagogy_evidence`)을 *조합*한다.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.api._auth import ConsentedUser
from whymath_backend.api._l3_state import get_cache
from whymath_backend.api._rate_limit import RateLimitedVisualization
from whymath_backend.api._subject_capability_state import (
    get_assessment_answer_verifier,
    get_expression_seal,
)
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.pedagogy_dsl import LearningObjective
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.l2.irt import theta_to_mastery_proxy
from whymath_backend.l2.learner_state import get_state
from whymath_backend.l2.learner_state_store import (
    LearnerStateMissingError,
    require_learner_state,
)
from whymath_backend.l2.pedagogy_evidence import (
    DuplicateOutcomeError,
    SessionOwnershipError,
    record_pedagogy_outcome,
    record_pedagogy_treatment,
)
from whymath_backend.l4.content_supply import get_process_tally, supply
from whymath_backend.l4.lthc import mastery_to_level
from whymath_backend.l4.pedagogy.runtime_selector import StudentSignals, grade_to_band
from whymath_backend.schema.enums import KnowledgeType

router = APIRouter(prefix="/v1/me/objectives", tags=["study"])

logger = logging.getLogger("whymath.api.study")

# 세션 의존성 — 모듈별 로컬 선언이 이 저장소 관례다(`api/scene.py`·`api/users.py` 동형).
SessionDep = Annotated[AsyncSession, Depends(get_session)]
# 설정 의존성 — SEC-24(원 SEC-16) 세션↔사용자 바인딩(HMAC 키 = jwt_secret)에 필요(`_auth.py` 관례).
SettingsDep = Annotated[Settings, Depends(get_settings)]


class StudySegment(BaseModel):
    """렌더된 조각 하나 — 렌더러-중립 표기(화면 문자열 아님·슬라이스 89)."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(description="조각 종류(question·explanation·example·prompt 등).")
    content: str = Field(description="렌더러-중립 본문(LaTeX + 구조 태그).")


class StudyUnitResponse(BaseModel):
    """학습 공급 응답 — 무엇을(개념) 어떤 교수법으로 보여줬는지 + 조각들.

    `session_id`는 **결과 기록 시 되돌려 보내야 하는 값**이다(처치↔결과를 잇는 축). 클라이언트가
    보관했다가 `/outcome`에 실어 준다.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID = Field(description="이 학습 단위의 세션 id — 결과 기록 시 재전송.")
    objective_id: str = Field(description="학습목표 id.")
    concept_code: str = Field(description="렌더 대상 개념 code(원자 축).")
    strategy: str = Field(description="실제로 적용된 교수법 전략(게이트 강등 후 결과).")
    content_source: str = Field(description="공급 경로(dsl_render·prompt_cache·generate).")
    gate_reason_code: str | None = Field(
        default=None, description="게이트가 전략을 강등했으면 그 사유 코드. 통과면 null."
    )
    segments: list[StudySegment] = Field(description="렌더된 조각(순서 = 제시 순서).")


class OutcomeRequest(BaseModel):
    """결과 기록 요청 — 처치와 같은 `session_id`로 묶인다."""

    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID = Field(
        description=(
            "`/study` 응답이 준 세션 id. 서버가 *요청 학생 본인에게* 발급한 값인지 소유권을 "
            "검증한다(SEC-24(원 SEC-16)) — 타인·위조 세션 id는 403으로 거부된다."
        )
    )
    correct: bool = Field(description="시도 정답 여부.")
    rt_ms: int | None = Field(default=None, ge=0, description="소요 시간(ms·체류 지표). 선택.")


class OutcomeResponse(BaseModel):
    """결과 기록 확인 — 기록 성공 여부만(집계는 하네스 소관)."""

    model_config = ConfigDict(extra="forbid")

    recorded: bool = Field(description="증거 이벤트가 기록됐는지.")


async def _load_objective(session: AsyncSession, objective_id: str) -> LearningObjective:
    """학습목표 로드 — 없으면 404. `k_type`·`concept_nodes`가 이후 단계의 축이다."""
    objective = await session.get(LearningObjective, objective_id)
    if objective is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="학습목표를 찾을 수 없습니다.",
        )
    return objective


async def _build_signals(
    session: AsyncSession, user_id: uuid.UUID, concept_code: str
) -> StudentSignals:
    """L2 학습자 상태(`get_state`) → `StudentSignals` 조립 — **실재하는 신호만** 채운다.

    PED-05 리팩터: 예전엔 `compute_concept_diagnoses`를 직접 호출해 그 결과 리스트를 순회하며
    `concept_code`가 일치하는 항목을 찾았다. `get_state()`가 내부적으로 *같은*
    `compute_concept_diagnoses` 호출을 이미 하고 그 결과를 `mastery`/`domain_abilities` dict로
    미리 인덱싱해 두므로, 이제 그 dict에서 O(1) lookup만 한다(쿼리 중복 0 — 리스트 순회가 dict
    lookup으로 *방식만* 바뀌고 값은 비트동일).

    `get_state().domain_abilities`는 raw IRT θ를 담는다(원래 `ConceptDiagnosis.irt_theta`와
    동일 소스). `mastery_level` 산출은 원래처럼 **BKT 우선·없으면 IRT 프록시([0,1]) 폴백**이므로,
    θ를 `theta_to_mastery_proxy`로 재환산한다(순수·결정론 함수라 원래 `irt_mastery_proxy`와
    비트동일 값).

    진단이 없거나(신규 학생) 해당 개념이 진단 목록에 없으면 숙달 축은 비운 채로 둔다 — 없는 값을
    기본치로 채우면 선택기가 근거 없는 판단을 하게 된다(PED-02가 세운 "가짜 통과 금지" 규약).
    Polya 단계·턴 수·힌트는 대화 세션 축이라 여기서는 기본값이다(공급 진입 = 시도 전).

    `grade_band`(PED-23 회수 — 04e §4 카탈로그 후보 필터 축)는 `UserProfile.grade`(10~14 —
    `schema/user.py` 계약)에서 `grade_to_band` 순수 변환으로 파생한다("생산자 먼저" — 04d §2.1).
    프로필 미존재·grade 미기입이면 None으로 두어 필터의 학년 축이 조용히 스킵된다(필수화 금지).
    """
    profile = await session.get(UserProfile, user_id)
    grade_band = grade_to_band(profile.grade if profile is not None else None)

    state = await get_state(session, user_id)
    bkt_mastery = state.mastery.get(concept_code)
    irt_theta = state.domain_abilities.get(concept_code)
    mastery = (
        bkt_mastery
        if bkt_mastery is not None
        else (theta_to_mastery_proxy(irt_theta) if irt_theta is not None else None)
    )
    return StudentSignals(
        mastery_level=mastery_to_level(mastery) if mastery is not None else None,
        bkt_mastery=bkt_mastery,
        irt_theta=irt_theta,
        grade_band=grade_band,
    )


@router.post(
    "/{objective_id}/study",
    response_model=StudyUnitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="학습목표 맞춤 학습 단위 공급 (교수법 선택 → 렌더 → 처치 기록)",
    dependencies=[RateLimitedVisualization],
)
async def post_study_unit(
    objective_id: str,
    user: ConsentedUser,
    session: SessionDep,
    settings: SettingsDep,
    request: Request,
) -> StudyUnitResponse:
    """학습목표를 학생 상태에 맞춘 교수법으로 렌더해 돌려주고, 그 처치를 기록한다.

    흐름: 목표 로드(k_type·concept) → L2 신호 조립 → `supply()`(선택·게이트·렌더가 그 안에서
    일어난다) → 처치 기록(`evidence_event`) → 응답.

    에러: 목표 없음 404 · 목표에 개념 미연결 404 · 렌더 불가(DSL 미적재) 404.
    렌더 불가를 500이 아니라 404로 내는 이유는 서버 결함이 아니라 *그 개념의 콘텐츠가 아직 없다*는
    데이터 상태이기 때문이다(정직한 구분).
    """
    objective = await _load_objective(session, objective_id)
    concept_codes = list(objective.concept_nodes or ())
    if not concept_codes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="학습목표에 연결된 개념이 없습니다.",
        )
    # 목표에 여러 개념이 붙어 있으면 첫 개념을 쓴다(컴파일러가 주 개념을 앞에 둔다). 다개념
    # 공급은 후속 — 지금 임의 병합을 하면 처치 귀속이 흐려진다.
    concept_code = concept_codes[0]

    # EOS-103 루프 진입 게이트 — LearnerState 영속 행이 없으면 **여기서 멈춘다**.
    #
    # 왜 조용히 진행하면 안 되는가: `_build_signals`는 진단이 없는 학생에게 숙달 축을 비운
    # `StudentSignals`를 만들어 내려보낸다(그 자체는 "가짜 통과 금지" 규약이 옳게 작동하는
    # 것이다 — 없는 값을 기본치로 채우지 않는다). 문제는 그 다음이다: 선택기는 근거 0으로
    # 교수법을 고르고, 학생은 *맞춤 학습 단위*라는 이름의 무근거 콘텐츠를 받고, 처치 행이
    # 기록되어 나중 집계에서 "개인화된 처치"로 계상된다. 즉 침묵 실패가 데이터까지 오염시킨다.
    #
    # 409를 쓰는 이유: 서버 결함(5xx)도 인가 문제(403)도 아니고, *선행 상태가 아직 아니다*
    # 라는 리소스 상태 충돌이다. 학생이 할 일(진단 완료)이 응답에 적혀 있어야 한다.
    try:
        await require_learner_state(session, user.user_id)
    except LearnerStateMissingError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="학습을 시작하려면 먼저 진단을 완료해야 합니다.",
        ) from exc

    signals = await _build_signals(session, user.user_id, concept_code)
    tally = get_process_tally()
    # EOS-89: 과목 능력 2종은 app.state 등록분(`create_app`)에서 꺼내 공급 사슬에 내려보낸다 —
    # 렌더 어댑터가 합성 루트를 스스로 부르지 않게 하는 push 경로의 시작점이 여기다.
    result = await supply(
        code=concept_code,
        signals=signals,
        session=session,
        cache=get_cache(request),
        seal=get_expression_seal(request),
        assessment_verifier=get_assessment_answer_verifier(request),
        k_type=KnowledgeType(objective.k_type).value,
        tally=tally,
    )
    # 공급 경로 리포트 1줄 — 이중 회계의 in-process 축을 *프로덕션에서* 관측 가능하게 만든다.
    # 어댑터별 비율을 함께 실어, 특정 교수법만 학생에게 도달하지 못하는 상태(전건 404)가 전체
    # 평균에 묻히지 않게 한다. 학생 원문·식별자는 싣지 않는다(개념 code·전략·경로만).
    logger.info(
        "study supply — concept=%s strategy=%s source=%s fallback=%s "
        "dsl_render_rate=%s strategy_render_rate=%s",
        concept_code,
        result.strategy.value,
        result.content_source,
        result.fallback_reason,
        tally.dsl_render_rate,
        tally.strategy_render_rate(result.strategy.value),
    )
    if result.rendered is None:
        # 생성 폴백을 켜지 않았으므로 렌더 실패 = 공급 불가. 처치도 기록하지 않는다 —
        # 학생이 아무것도 보지 못했으면 처치가 아니다(가짜 처치 금지).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="이 개념의 학습 콘텐츠가 아직 준비되지 않았습니다.",
        )

    session_id = uuid.uuid4()
    # SEC-24(원 SEC-16): 처치 행 meta에 (session_id ↔ user) 키드 해시 바인딩이 함께 남는다 —
    # `/outcome` 소유권 대조의 앵커(raw user_id 미저장·가명화 유지).
    await record_pedagogy_treatment(
        session,
        objective_id=objective.id,
        k_type=KnowledgeType(objective.k_type).value,
        session_id=session_id,
        user_id=user.user_id,
        settings=settings,
        strategy=result.strategy.value,
        content_source=result.content_source,
        concept_code=concept_code,
        gate_reason_code=result.gate_reason_code,
    )
    await session.commit()

    return StudyUnitResponse(
        session_id=session_id,
        objective_id=objective.id,
        concept_code=concept_code,
        strategy=result.strategy.value,
        content_source=result.content_source,
        gate_reason_code=result.gate_reason_code,
        segments=[
            StudySegment(kind=str(seg.kind), content=seg.content)
            for seg in result.rendered.segments
        ],
    )


@router.post(
    "/{objective_id}/outcome",
    response_model=OutcomeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="학습 결과 기록 (처치와 같은 session_id로 묶임)",
)
async def post_study_outcome(
    objective_id: str,
    body: OutcomeRequest,
    user: ConsentedUser,
    session: SessionDep,
    settings: SettingsDep,
) -> OutcomeResponse:
    """처치 이후의 시도 결과를 기록한다 — 효과 집계의 분자·분모가 되는 행.

    `session_id`는 `/study`가 *요청 학생 본인에게* 발급한 값이어야 한다(SEC-24(원 SEC-16) —
    `docs/reviews/functional_security_audit_2026-08-08.md` M2). 소유권 검증(처치 행의 키드 해시
    바인딩 대조)·중복 검사는 유일 outcome writer(`record_pedagogy_outcome`) 안쪽에서 일어나고,
    실패하면 행을 남기지 않고 403(소유권)·409(중복)로 거부한다 — 예전의 "세션이 맞지 않으면
    결과 행은 남지만 처치 미상으로 집계에서 제외" 규약을 "기입 거부"로 승격했다(고아 outcome
    자체가 오염 벡터).

    학생 원문 풀이는 받지 않는다(요청 스키마에 슬롯 부재 — B1 구조적 차단).
    """
    objective = await _load_objective(session, objective_id)
    try:
        await record_pedagogy_outcome(
            session,
            objective_id=objective.id,
            k_type=KnowledgeType(objective.k_type).value,
            session_id=body.session_id,
            user_id=user.user_id,
            settings=settings,
            correct=body.correct,
            rt_ms=body.rt_ms,
        )
    except SessionOwnershipError as exc:
        # 미존재·타인 소유·바인딩 부재 전부 **단일 메시지**의 403 — 사유를 구분해 주면
        # "그 session_id가 존재하는가"를 알려주는 존재 오라클이 된다(SEC-24(원 SEC-16) 오라클 차단).
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "학습 세션 소유권을 확인할 수 없습니다 — /study 응답이 발급한 session_id로만 "
                "결과를 기록할 수 있습니다."
            ),
        ) from exc
    except DuplicateOutcomeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이 학습 세션의 결과는 이미 기록되어 있습니다.",
        ) from exc
    await session.commit()
    return OutcomeResponse(recorded=True)


__all__ = [
    "OutcomeRequest",
    "OutcomeResponse",
    "StudySegment",
    "StudyUnitResponse",
    "router",
]
