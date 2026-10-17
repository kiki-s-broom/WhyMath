"""L4 중간 step 등가성 shadow 관측 — 학생 풀이의 단계-비보존을 *로그로만* 진단(비노출·비차단).

`docs/architecture/04_pedagogy_engine.md`: L4는 *결정* 계층. 본 모듈은 L3 결정론 도구
`detect_step_breaks`(slice 62)를 호출해 다단계 풀이의 인접 단계 해집합 비보존을 *관측*한다 —
**student-facing이 아니다**. pedagogy-designer 결론(slice 61): 순차유도 오류(A)와 변수재사용(B)은
정보이론적으로 구문 분리 불가하므로 *단계 위치 지목은 학생에게 금지*. 검출 신호는 노이즈((A)/(B)
미분리)이므로 진단 데이터로만 흡수한다(향후 L7·교사 대시보드·KPI sink; 당장은 로그가 유일 sink).

레이어·shadow 위생: L4는 L3 도구를 *호출*만(검출 로직은 L3 소유). 워커 shadow(slice 43·
`whymath.l3.quality` 로거)·`l3_shadow_validation_enabled` 게이트의 직접 선례를 따른다 —
**비차단**(반환 None·예외 흡수)이라 본류(코칭 결정·반환)를 어떤 경우에도 바꾸지 않는다.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.config import get_settings
from whymath_backend.l3.pregenerate.validator import (
    StepAnswerVerdict,
    classify_step_break,
    detect_step_breaks,
)

logger = logging.getLogger("whymath.l4.step_shadow")  # 워커 "whymath.l3.quality" 네이밍 동형
# 구조화 관측 레코드 sink(slice 67·harvest 입력) — 부모의 *자식* 로거라 평문과 분리 캡처/라우팅된다.
record_logger = logging.getLogger("whymath.l4.step_shadow.record")

# verdict(L3 사실판정) → A/B *후보*(L4 교수학 해석). "diverged"=정답서 이탈=(A) 후보의 양성
# 증거. 나머지는 양성 아님/모호/판정불가다. (A)/(B)는 구문상 미분리라 *후보*일 뿐 — precision은
# 사람 라벨 축적 후 측정한다(정책 2026-06-06 해금 경로 ①). 학생 단계 지목 금지 불변(로그 sink만).
_VERDICT_TO_CANDIDATE: dict[StepAnswerVerdict, str] = {
    "diverged_from_answer": "A",  # 변환오류 후보(정답서 이탈)
    "reached_answer": "not_A",  # 정답 도달(양성 아님)
    "unrelated": "ambiguous",  # (A)/(B) 미분리(모호)
    "indeterminate": "unknown",  # 정답/해집합 파싱 불가
}


def candidate_for_verdict(verdict: StepAnswerVerdict) -> str:
    """verdict(L3 사실판정) → A/B *후보* 라벨(L4 교수학 해석)의 단일 출처.

    `observe_step_breaks` 로그와 precision eval 하니스(`step_shadow_eval`·slice 66)가 같은 매핑을
    쓰도록 공개한다 — verdict→candidate가 `_VERDICT_TO_CANDIDATE` 한 곳에만 정의되게 한다.
    """
    return _VERDICT_TO_CANDIDATE[verdict]


class StepBreakObservation(BaseModel):
    """단계-비보존 관측 1건의 *구조화 레코드* — record_logger JSON emit(slice 67·harvest).

    `observe_step_breaks`가 평문 로그와 *나란히* 이 레코드를 JSON으로 남겨, 향후 사람이 A/B 라벨링할
    코퍼스(harvest → eval)로 수집되게 한다. **학생 풀이 원문(`solution_text`)을
    담지 않는다** — slice 64~65 로그의 의도적 누락 계승(미성년자 프라이버시). 담는 건
    추상화된 해집합(`solset_*`)·마커·변수·verdict/candidate(로그 sink 한정·비노출 불변).
    """

    model_config = ConfigDict(extra="forbid")

    problem_id: uuid.UUID | None = None
    expected_answer: str | None = None
    verdict: StepAnswerVerdict
    candidate: str
    var: str
    step_index: int
    solset_before: str
    solset_after: str
    marker: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def observe_step_breaks(
    solution_text: str,
    *,
    problem_id: uuid.UUID | None = None,
    expected_answer: str | None = None,
) -> None:
    """학생 풀이의 단계-비보존 의심을 *로그로만* 관측(shadow·비차단·비노출). 반환 `None`.

    반환이 `None`이라 호출자가 신호를 받을 변수가 *없다* — student-facing 누출을 구조적으로 차단한다
    (오케스트레이터는 fire-and-forget으로 호출하고 반환을 쓰지 않는다). `l4_step_shadow_enabled`
    게이트 off(기본)면 검출조차 안 돌리고 즉시 반환(비용 0). 예외는 삼킨다 — 관측이 본류(코칭
    결정·반환)를 깨면 안 된다(우선순위: 학생 경험 > 진단 관측).

    `problem_id`·`expected_answer`는 *진단 맥락*(slice 64) — 검출된 break를 *어느 문항·기대정답*에
    귀속시켜 향후 (A)순차유도 오류 vs (B)변수재사용 라벨 정확도를 증거 기반으로 측정하게 한다(결정
    로그 2026-06-06 해금 경로 ①). 둘 다 *서버 로그 sink에만* 흐른다 — 반환은 여전히 `None`이라
    비노출 불변이 보존된다(특히 `expected_answer`는 절대 student-facing이면 안 됨 = 정답 누출).
    `expected_answer`는 *서버 DB 조회*(api 계층)로만 얻고 요청/응답엔 결코 싣지 않는다.

    slice 65: 각 break를 `classify_step_break`로 기대정답 대비 분류(verdict)하고 verdict→A/B
    *후보*(candidate)를 로그에 남긴다 — 둘 다 로그 sink에만(반환 None·비노출 불변). 후보는
    (A)/(B) 미분리라 *양성 증거*일 뿐이며 precision은 사람 라벨 축적 후 측정한다.

    slice 67: 평문 로그와 *나란히* 각 관측을 `StepBreakObservation` JSON 한 줄로 `record_logger`에도
    남긴다(harvest 입력·로그 sink·반환 None). 학생 풀이 원문은 레코드에 안 담는다(프라이버시).
    검출·분류·직렬화·로깅을 한 `try`로 감싸 어떤 예외도 본류를 안 깨게 한다(비차단 불변).
    """
    if not get_settings().l4_step_shadow_enabled:
        return
    try:
        breaks = detect_step_breaks(solution_text)
        for b in breaks:
            verdict = classify_step_break(b, expected_answer)
            candidate = candidate_for_verdict(verdict)
            logger.info(
                "단계 비보존 의심(shadow·비노출) — problem_id=%s expected=%r "
                "verdict=%s candidate=%s var=%s step=%d %s→%s marker=%r",
                problem_id,
                expected_answer,
                verdict,
                candidate,
                b.var,
                b.step_index,
                b.solset_before,
                b.solset_after,
                b.marker,
            )
            record_logger.info(
                StepBreakObservation(
                    problem_id=problem_id,
                    expected_answer=expected_answer,
                    verdict=verdict,
                    candidate=candidate,
                    var=b.var,
                    step_index=b.step_index,
                    solset_before=b.solset_before,
                    solset_after=b.solset_after,
                    marker=b.marker,
                ).model_dump_json()
            )
    except Exception as exc:  # noqa: BLE001 — 관측은 본류를 안 깬다(방어선·테스트 커버)
        # 침묵 실패 금지 — 타입명만 남긴다(메시지는 학생 풀이를 담을 수 있어 제외).
        logger.warning("step 관측 실패 — 비차단 방어선: %s", type(exc).__name__)
        return


__all__ = ["StepBreakObservation", "candidate_for_verdict", "observe_step_breaks"]
