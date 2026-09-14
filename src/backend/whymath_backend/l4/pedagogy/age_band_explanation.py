"""연령별 개념 설명 생성 — 공개 진입점 (EOS-98 C9 생성 좌석).

`l3/pedagogy/explanation_generator.py`(생성 엔진·L3)를 L4에서 오케스트레이션한다("L4=결정·
L3=생성" 원칙 — `analogy_generator.py` 모듈 docstring 파이프라인 표기와 동형). L4가 하는 결정
2가지: ①원문 조회(`concept_content.explanation` — L1 경유) ②레지스터별 도입 구조 주입
(`l4/speech/profiles.py::PROFILES` — 낭독 프로파일과 **같은 데이터를 재사용**해 "이 학년에
아직 없는 구조" 판정의 단일 진실 원천을 하나로 유지한다).

이 모듈이 EOS-70(SubjectAdapter explain 능력 판정)이 위임 대상으로 삼을 공개 진입점이다
(`explain_concept_at_age_band`/`explain_concept_all_bands`). 착지(영속화) 좌석은 아직 없다 —
이 슬라이스는 **온디맨드 생성**까지만 놓는다(EOS-98 notes: 4개 언어 수준 정의는 여기서 확정하되
지어내지 않고 기존 `SpeechGradeBand` 재사용). 저장 축은 EOS-70이 explain 계약을 확정한 뒤
별도 태스크로 판단한다(정직한 공백 — 소비처 없는 저작 선행 금지 원칙의 반대 방향: 저장처 없는
생성도 선행하지 않는다).

7계층: L4 교수학 엔진. L1(concept_content 조회)·L3(생성 엔진)·L4 형제(speech profiles) 호출.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.l1.concept_content.resolve import get_concept_content
from whymath_backend.l3.pedagogy.explanation_generator import (
    ExplanationGenerator,
    ExplanationOutcome,
    ExplanationTarget,
    run_explanation_review,
)
from whymath_backend.l4.speech.profiles import PROFILES
from whymath_backend.schema.speech import SpeechGradeBand

_LOGGER = logging.getLogger(__name__)

# EOS-98 acceptance ③ "학교급 4개 언어 수준" — `SpeechGradeBand`(기존 닫힌 교수학 어휘) 그대로
# 재사용한다. 성취기준 school_type(초등학교/중학교/고등학교)은 3값뿐이라 "대학"은 성취기준 밖의
# 페르소나 확장(B/E 페르소나·`SpeechGradeBand.대학` 도큐멘트와 동일 근거)이다 — 지어내지 않고
# 기존 낭독 프로파일 축의 4값을 그대로 상속한다(설계 시 확정·CLAUDE.md "지어내지 않는다" 준수).
AGE_BANDS: tuple[SpeechGradeBand, ...] = (
    SpeechGradeBand.초등,
    SpeechGradeBand.중등,
    SpeechGradeBand.고등,
    SpeechGradeBand.대학,
)


def _forbidden_vocabulary_for(band: SpeechGradeBand) -> tuple[str, ...]:
    """이 밴드에 아직 없는 구조명(사람이 읽는 한글 표기) — 프롬프트 동봉용(생성측 예방).

    판정 자체는 `explanation_checker`가 독립적으로 한다 — 이 목록은 프롬프트 힌트일 뿐,
    생성기 자기 보고를 검수 통과 근거로 쓰지 않는다(기계 게이트가 별도로 재검사).
    """
    introduced = PROFILES[band].introduced_constructs
    all_constructs = PROFILES[SpeechGradeBand.대학].introduced_constructs
    missing = sorted(all_constructs - introduced)
    return tuple(missing)


async def explain_concept_at_age_band(
    session: AsyncSession,
    code: str,
    band: SpeechGradeBand,
    *,
    generator: ExplanationGenerator | None = None,
) -> ExplanationOutcome | None:
    """개념 1건을 지정 학년 레지스터의 설명으로 생성·검수한다.

    흐름: ①`concept_content` 조회(L1) — 원문 없으면 `None`(생성 발주 불가·환각 방지 설계
    ExplanationTarget 불변식과 동형) ②`ExplanationGenerator.generate_draft`(라우터 경유)
    ③`run_explanation_review`(F7 언어 수준 게이트 포함). 반환은 검수 *결과*(APPROVED/REJECTED)를
    담은 `ExplanationOutcome`이다 — 호출자(EOS-70 SubjectAdapter 등)가 APPROVED만 노출한다
    (CLAUDE.md "LLM 응답을 검증 없이 학생에게 제공 금지").
    """
    content = await get_concept_content(session, code)
    source_explanation = (content.explanation or "").strip() if content is not None else ""
    if not source_explanation:
        _LOGGER.warning(
            "연령별 설명 생성 표적 없음(code=%s) — concept_content 원문 부재/공백.", code
        )
        return None
    assert content is not None  # source_explanation이 비지 않으려면 content가 있어야 한다.
    target = ExplanationTarget(
        code=content.code,
        name=content.name,
        subject=content.subject,
        band=band,
        source_explanation=source_explanation,
        forbidden_vocabulary=_forbidden_vocabulary_for(band),
    )
    active_generator = generator if generator is not None else ExplanationGenerator()
    # async 호출부 — 이미 실행 중인 이벤트 루프(FastAPI 요청 핸들러 등) 안이라 sync 래퍼
    # `generate_draft`(자체 루프 재진입 시 RuntimeError)가 아니라 `agenerate_draft`를 직접 await.
    row = await active_generator.agenerate_draft(target)
    if row is None:
        return None
    outcomes = run_explanation_review(
        [row],
        introduced_constructs_by_band={b: PROFILES[b].introduced_constructs for b in AGE_BANDS},
    )
    return outcomes[0]


async def explain_concept_all_bands(
    session: AsyncSession,
    code: str,
    *,
    generator: ExplanationGenerator | None = None,
) -> dict[SpeechGradeBand, ExplanationOutcome | None]:
    """개념 1건의 설명을 4개 학년 레지스터 전부에 대해 생성·검수한다("동일 개념 다수준 설명").

    generator를 재사용해 배치 전체가 provider 커넥션 풀·이벤트 루프를 공유하게 한다
    (`ExplanationGenerator._ensure_loop` 선례 — 반복 `asyncio.run` 금지).
    """
    active_generator = generator if generator is not None else ExplanationGenerator()
    return {
        band: await explain_concept_at_age_band(session, code, band, generator=active_generator)
        for band in AGE_BANDS
    }


__all__ = [
    "AGE_BANDS",
    "explain_concept_at_age_band",
    "explain_concept_all_bands",
]
