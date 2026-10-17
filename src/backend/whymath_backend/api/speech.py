"""L5 수식 음성화 HTTP 표면 — LaTeX → 한국어 낭독 명세(SpeechSpec). 음성 슬라이스 S1.

7계층: L5(api)는 L4(`l4/speech`)를 호출해 변환을 *오케스트레이션*만 한다 — 수학 로직은 L3 엔진이,
사전·프로파일 주입은 L4가 한다. 변환은 결정론(LLM 0)이라 `api/visualization.py`의 `/spec`
라운드트립처럼 *레이트리미터를 적용하지 않는다*(외부 호출·비용 0).

클라(L5)는 이 명세를 받아 오디오 합성만 한다(수학 로직 0·슬89). plain_text는 SSML 미지원
환경의 폴백, ssml은 지원 엔진용, unresolved_symbols는 정직성 신호다.

**클라 소비는 현재 0이다**(2026-08-11 실측) — 유일한 합성 경로였던 `flutter_tts`는 Gradle
비호환이 실측돼 `src/mobile/pubspec.yaml`에서 *의도적으로 제거*됐다. 즉 이 엔드포인트는
서버 축만 완비된 상태이고, "클라만 붙이면 된다"가 아니다(재도입은 실기기 Gradle 호환
재검증이 선행 — `docs/architecture/service_operations_gap_review.md` §5-④ 트리거).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.api._auth import ConsentedUser
from whymath_backend.l3.speech import InvalidSpeechSpecError
from whymath_backend.l4.speech import speak_latex
from whymath_backend.schema.speech import SpeechGradeBand, SpeechSpec

router = APIRouter(prefix="/v1/speech", tags=["speech"])


class SpeechLatexRequest(BaseModel):
    """단일 수식 낭독 요청 — LaTeX + 학년 밴드(기본 고등·MVP 페르소나 A 고3)."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    latex: str = Field(..., min_length=1, description="읽을 LaTeX 수식")
    grade_band: SpeechGradeBand = Field(
        default=SpeechGradeBand.고등, description="낭독 학년 밴드(초등/중등/고등/대학)"
    )


@router.post(
    "/latex",
    response_model=SpeechSpec,
    summary="LaTeX 수식 → 한국어 낭독 명세(SpeechSpec) 생성 (결정론·LLM 0)",
)
async def post_speech_latex(user: ConsentedUser, body: SpeechLatexRequest) -> SpeechSpec:
    """LaTeX를 학년 밴드에 맞춰 한국어 낭독 명세로 변환한다(L4→L3 결정론 변환).

    변환 실패(빈 낭독·불변식 위반 등 `InvalidSpeechSpecError`)는 학생 미노출 원칙에 따라 422다.
    인증은 `ConsentedUser`(미성년 동의 게이트), LLM 호출이 없어 레이트리미터는 적용하지 않는다.
    """
    try:
        return speak_latex(body.latex, body.grade_band)
    except InvalidSpeechSpecError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"낭독 명세를 생성할 수 없습니다: {exc}",
        ) from exc
