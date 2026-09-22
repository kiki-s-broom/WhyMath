"""L4 메타인지 코칭 트리거 — L2 진단(BKT↔IRT) → 교수학적 코칭 포커스 결정.

`docs/architecture/04_pedagogy_engine.md`: L4는 *결정* 계층(L3=생성·L5=노출). 본 모듈은 L2
학습자 모델의 두 신호 — BKT 개념 숙달 P(L)과 IRT 능력 θ — 를 받아 *어떤 메타인지 코칭이
적절한가*를 결정한다(실제 발화 생성·UI 노출은 각각 L3·L5 책임).

핵심 통찰(slice L2-19 교차검증의 교수학적 후속): 두 신호의 *불일치*가 가장 값진 코칭 단서다.
- 문항은 맞히나(θ↑) 숙달 추정은 낮음(BKT↓) → *우연·추측 의심* → 이해 진위를 메타인지로 점검.
- 숙달했(BKT↑)으나 최근 능력은 낮음(θ↓) → *망각·슬럼프 의심* → 인출 연습으로 회복.
- 둘 다 낮으면(합의) 기초 재교육(LTHC 낮은 진입점)·둘 다 높으면 심화(LTHC 높은 천장).
- 한쪽 신호만 있으면 교차검증 불가 → 추가 진단.

레이어 경계 준수: L4는 L2(숙달·θ)를 *안다*. L5(api)·DB는 모른다 — 입력은 원시 수치(float)뿐.
순수·결정론(L2 `irt.theta_to_mastery_proxy` 재사용 외 의존 없음). 발화는 *답을 주지 않는*
메타인지 유도(CLAUDE.md 답 미루기 원칙).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.l2.irt import theta_to_mastery_proxy
from whymath_backend.l4.hint_deferral import HintLevel
from whymath_backend.l4.socratic.categories import SocraticCategory

CoachingFocus = Literal[
    "verify",
    "consolidate",
    "retrieval",
    "foundation",
    "advance",
    "diagnose",
    "prerequisite_review",
    "calibration_overconfident",
    "calibration_underconfident",
    "misconception_review",
]
"""메타인지 코칭 포커스 10종.

- `verify`: *검산* — 구체적 계산 오류가 감지됨(슬립). 개념 재교육 전에 스스로 계산을 다시
  짚게 한다(슬립 vs 오개념 구분 — 이해는 있는데 계산만 틀린 경우 재교육은 역효과).
- `consolidate`: 이해 *공고화* — 맞히나 숙달 낮음(추측 의심). 풀이 근거를 스스로 설명.
- `retrieval`: *인출 연습* — 숙달했으나 능력 낮음(망각·슬럼프). 핵심 아이디어 회상·복습.
- `foundation`: *기초 재교육* — 두 신호 모두 낮음. LTHC 낮은 진입점부터 비계.
- `advance`: *심화* — 두 신호 모두 높음. LTHC 높은 천장(일반화·증명·전이).
- `diagnose`: *추가 진단* — 한쪽 신호만 존재(교차검증 불가). 문항 더 풀어 데이터 확보.
- `prerequisite_review`: *선수 복습 우선* — 후행 개념의 막힌 선수개념(L2 선수 추천)이 근본
  장애물. 후행을 바로 코칭하지 말고 선수부터 다진다(LTHC·기초 우선). `recommend_coaching`은
  *이 포커스를 반환하지 않는다*(BKT/IRT만으로 결정 불가·선수 그래프 입력 필요) — 별도 순수
  결정 함수 `recommend_prerequisite_coaching`(`l4.prerequisite_coaching`)이 선수 갭에서 빌드한다.
  여기 dict 항목은 일관성·exhaustiveness(키 집합 == CoachingFocus)용 일반 템플릿이다.
- `calibration_overconfident`: *과신 구간* — 틀렸으나 자기보고 확신이 높음(예측 vs 실제 불일치).
  자기점검·가정 재검토를 유도한다(소크라테스 강화·ASSUMPTION). `recommend_coaching`은 *이 포커스를
  반환하지 않는다*(BKT/IRT가 아니라 *확신도↔정오답* 보정 입력 필요) — 별도 순수 결정 함수
  `recommend_calibration_coaching`(`l4.calibration_coaching`)이 보정 신호에서 빌드한다. 측정 단계
  (⑥ Brier 보정 점수·`harness`)가 *얼마나* 어긋났는지 잰다면, 이 코칭은 그 어긋남을 *학생별 행동*
  으로 잇는다(측정→코칭).
- `calibration_underconfident`: *과소신 구간* — 맞았으나 확신이 낮음. 성취를 명시해 효능감을
  회복시킨다(META). prerequisite_review·overconfident와 동일하게 `recommend_coaching` 밖·별도
  결정 함수가 빌드한다(아래 dict 항목은 exhaustiveness용 정본 템플릿).
- `misconception_review`: *오개념 복습* — 누적된 활성 오개념 *가설*이 충분히 강해 그 오개념
  자체를 다시 보자고 권한다(ASSUMPTION·가정 재검토). 앞 셋과 동일하게 `recommend_coaching`은
  *이 포커스를 반환하지 않는다*(BKT/IRT가 아니라 오개념 가설 세트 입력 필요) — 별도 순수 결정
  함수 `recommend_misconception_review_coaching`(`l4.misconception_review_coaching`)이 빌드한다.
  **선수 복습과 다른 축이다**: `prerequisite_review`는 "아래 개념이 비어 있다"(결손)이고 이쪽은
  "규칙을 잘못 알고 있을 수 있다"(오적용)다. 가설은 확정 라벨이 아니므로 발화는 단정하지 않는다.
"""

# 포커스별 근거(rationale)·학생 노출 코칭 발화(prompt) — 답을 주지 않는 메타인지 유도.
_RATIONALE: dict[CoachingFocus, str] = {
    "verify": "구체적 계산 오류 감지 — 개념 재교육보다 *검산*으로 어긋난 지점을 스스로 찾게.",
    "consolidate": "문항은 맞혔지만 숙달 추정이 낮음 — 우연·추측이 아닌 진짜 이해인지 점검.",
    "retrieval": "숙달했던 개념인데 최근 능력 추정이 낮음 — 망각·슬럼프 가능성, 인출로 회복.",
    "foundation": "숙달·능력 두 신호 모두 낮음 — 기초 사례부터 비계(LTHC 낮은 진입점).",
    "advance": "숙달·능력 두 신호 모두 높음 — 일반화·증명·전이로 심화(LTHC 높은 천장).",
    "diagnose": "한쪽 신호만 있어 교차검증 불가 — 문항을 더 풀어 상태를 정확히 파악.",
    "prerequisite_review": "선수개념 미숙달이 후행 개념의 근본 장애물 — 선수부터 복습 권장"
    "(LTHC·기초 우선).",
    "calibration_overconfident": "과신 구간(틀렸으나 확신 높음) — 자기점검·가정 재검토 유도"
    "(소크라테스 강화).",
    "calibration_underconfident": "과소신 구간(맞았으나 확신 낮음) — 성취 명시·효능감 회복.",
    "misconception_review": "누적 오개념 가설이 충분히 강함 — 그 오개념 자체를 다시 점검"
    "(가정 재검토·확정 라벨 아님).",
}
_PROMPT: dict[CoachingFocus, str] = {
    "verify": "계산을 한 단계씩 다시 짚어보면서 어디서 숫자가 어긋났는지 찾아볼래?",
    "consolidate": "방금 푼 방법을 *왜* 그렇게 했는지 한 단계씩 설명해볼래?",
    "retrieval": "이 개념의 핵심 아이디어를 먼저 떠올려 한 줄로 적어볼래?",
    "foundation": "이 개념의 *가장 기본 사례*부터 같이 차근차근 볼까?",
    "advance": "조건을 바꾸거나 *왜 항상* 성립하는지 증명에 도전해볼래?",
    "diagnose": "이 개념 문제를 몇 개 더 풀어보면 네 상태를 더 정확히 볼 수 있어.",
    "prerequisite_review": "지금 개념 전에, 먼저 막힌 선수개념부터 한 번 같이 복습해 볼까? "
    "기초가 탄탄해지면 훨씬 수월할 거야.",
    "calibration_overconfident": "이번엔 아쉽게 안 맞았네. 어디서 그렇게 확신했는지 "
    "같이 한 줄씩 짚어볼까?",
    "calibration_underconfident": "맞았어! 충분히 잘 풀었는데 스스로는 자신이 없었구나. "
    "다음엔 네 풀이를 좀 더 믿어도 돼.",
    "misconception_review": "혹시 여기서 쓴 규칙이 항상 성립하는지 한 번 더 확인해 볼까? "
    "간단한 수를 직접 넣어 보면 금방 보일 거야.",
}
# verify 포커스의 *단계 자가검산* 변형 — 다단계 대수 슬립(L3 error_kind="solution")일 때만 쓴다.
# 위치를 *지목하지 않고* 학생이 스스로 인접 줄의 해 일관성을 확인하게 한다(답 미루기·slice 61).
# 일반 verify("어디서 숫자가 어긋났는지")는 순수 수치 슬립용, 이건 다단계 변환의 등가 자가점검용.
_PROMPT_VERIFY_STEPS = "각 줄이 바로 윗줄과 같은 답을 갖는지 한 줄씩 확인해볼래?"
# verify 포커스의 *위치 인지 단계 자가검산* 변형 — `verify_solution`이 첫 incorrect 전이
# 인덱스를 함께 줄 때만 쓴다(다단계 대수 슬립·전이 인덱스 제공·WH-1 1단계). 위 비지목 변형보다
# *주의를 좁히되* CLAUDE.md 답 미루기·LTHC 최소도움·정서안전을 엄수한다:
#   - **앞 단계 통과 확인**: first_incorrect_index 이전 전이는 verify_solution이 correct/
#     unverifiable로 통과시킨 것 → "처음 {k}줄까지는 잘 따라왔어"로 *효능감*을 준다.
#   - **그 지점부터 *스스로* 재검산**: 위치(몇 번째 줄)는 알려주되 *무엇이 왜 어긋났는지·
#     고치는 법은 미제공* — 학생이 스스로 찾게 한다(LTHC 최소도움·답 미루기).
#   - **단정·부정 강화 금지**: "N번째 줄이 *틀렸다*"가 아니라 "그 줄이 바로 윗줄과 같은 값인지
#     거기서부터 다시 확인해볼까?"로 *의심 결과 줄을 스스로 검산*하게 한다(소크라테스·질문형).
# off-by-one(전이 인덱스 → 사람 줄번호): 전이 i는 steps[i]→steps[i+1]이고 i 이전 전이가
# 모두 통과 → steps[0..i](1-indexed 1..i+1)까지는 *잘 따라온* 줄이므로 k = i+1. *의심 결과 줄*
# 은 전이 i의 도착 줄 steps[i+1](1-indexed i+2)이므로 m = i+2. (테스트 `test_*off_by_one`가 핀.)
_PROMPT_VERIFY_STEPS_AT = (
    "처음 {k}줄까지는 잘 따라왔어. {m}번째 줄이 바로 윗줄과 같은 값인지 "
    "거기서부터 한 줄씩 다시 확인해볼까?"
)


def _verify_steps_at_prompt(step_index: int) -> str:
    """위치 인지 단계 자가검산 발화 빌드 — 전이 인덱스(0-based)를 사람 줄번호로 환산.

    `step_index`(=`verify_solution.first_incorrect_index`)는 전이 i(steps[i]→steps[i+1])다.
    i 이전 전이는 모두 통과했으므로 1..i+1번째 줄까지 *잘 따라온* 것(k=i+1)·*의심 결과 줄*은
    전이 i의 도착 줄(1-indexed i+2, m=i+2). 위치만 좁혀줄 뿐 *무엇이 왜 어긋났는지·고치는
    법은 주지 않는다*(답 미루기·LTHC 최소도움·스스로 검산).
    """
    k = step_index + 1  # 잘 따라온 줄 수(1-indexed 마지막 통과 줄 = i+1).
    m = step_index + 2  # 스스로 재검산할 의심 결과 줄(1-indexed steps[i+1]).
    return _PROMPT_VERIFY_STEPS_AT.format(k=k, m=m)


# ── 답 미루기 점층(hint_level 3·4) verify 자가검산 변형 ────────────────────────────────
# hint_deferral 4단계 사다리(1 방향→2 의사코드→3 부분풀이→4 안전망)와 verify 자가검산을
# 통합한다(slice·hint escalation). 학생이 *같은 단계*에서 반복해 막힐수록(상위 hint_level)
# 호출자(오케스트레이터)가 hint_deferral.decide_hint_level로 단계를 올려 전달하면, 3·4단계에서
# 더 *과정* 비계를 준다. 단, 답 미루기·정확성·정서안전 금기를 엄수:
#   - ❌ 정답/정답값/올바른 다음 줄을 제시하지 않는다(verify는 정답을 모름 — 학생 풀이의
#     *내부 일관성*만 본다).
#   - ❌ "틀렸다/틀렸/잘못" 같은 단정·부정 강화 표현 금지.
#   - ✅ 질문형(소크라테스)·앞 단계 통과 효능감 유지.
#   - ✅ 점층은 *과정 재구성 비계*(의사코드/부분풀이 수준) — 바로 윗줄에서 *어떤 규칙을
#     적용했는지*부터 한 단계씩 말로 다시 세우게 한다. 무엇이 왜 어긋났는지·고치는 법은 학생 몫.
# 1·2단계는 점층하지 않는다(기존 동작 그대로·가장 빠른 단계에서 멈춤·스펙 L39).
#
# 위치 비지목 버전(step_index 없음) — 인덱스가 없으니 줄을 좁히지 못한다. 대신 *각 줄에서 바로
# 윗줄에 어떤 규칙을 적용했는지*를 말로 재구성하게 한다(부분풀이 수준 과정 비계).
_PROMPT_VERIFY_STEPS_ESCALATED = (
    "규칙을 한 단계씩 짚다 보면 어디서 두 줄의 값이 달라지는지 스스로 보일 거야. 이번엔 "
    "한 줄씩, 바로 윗줄에서 *어떤 규칙*을 적용해 그 줄을 얻었는지 말로 다시 세워볼래?"
)
# 위치 인지 버전(step_index 있음) — 앞 단계 통과 효능감(처음 k줄)을 유지하면서, 의심 결과 줄
# (m번째)에 *어떤 규칙*을 적용했는지부터 한 단계씩 말로 재구성하게 한다(부분풀이 수준 과정 비계).
# off-by-one 규약은 위치 인지 기본형과 동일(k=i+1 통과·m=i+2 의심 줄).
_PROMPT_VERIFY_STEPS_AT_ESCALATED = (
    "처음 {k}줄까지는 잘 따라왔어. 규칙을 짚다 보면 그 줄의 값이 윗줄과 같은지 스스로 보일 "
    "거야. 이번엔 {m}번째 줄을 바로 윗줄에서 *어떤 규칙*을 적용해 얻었는지부터 한 단계씩 "
    "말로 다시 세워볼까?"
)


def _verify_steps_escalated_prompt(step_index: int | None) -> str:
    """답 미루기 점층(hint_level 3·4) verify 자가검산 발화 빌드 — 과정 재구성 비계.

    `step_index`가 있으면 위치 인지 점층(앞 k줄 통과 효능감 + m번째 줄 규칙 재구성), 없으면
    위치 비지목 점층(각 줄의 규칙을 한 단계씩 재구성). off-by-one(k=i+1·m=i+2)은 기본형과 동일.
    정답/수정/"틀렸다"는 어떤 경우에도 미포함 — 무엇이 왜 어긋났는지·고치는 법은 학생 몫이다.
    """
    if step_index is None:
        return _PROMPT_VERIFY_STEPS_ESCALATED
    k = step_index + 1  # 잘 따라온 줄 수(1-indexed 마지막 통과 줄 = i+1).
    m = step_index + 2  # 스스로 규칙을 재구성할 의심 결과 줄(1-indexed steps[i+1]).
    return _PROMPT_VERIFY_STEPS_AT_ESCALATED.format(k=k, m=m)


# 포커스 → 대화 진입 소크라테스 카테고리(slice 5·socratic 6분류). coach가 *어떤 질문 종류*로
# 시작할지 — verify=근거(계산 재점검)·consolidate=근거(추측 검증)·retrieval=메타(예전 풀이
# 회상)·foundation/diagnose=명료화(기초·상태 파악)·advance=관점(다른 방법·일반화).
_SOCRATIC_BY_FOCUS: dict[CoachingFocus, SocraticCategory] = {
    "verify": SocraticCategory.EVIDENCE,
    "consolidate": SocraticCategory.EVIDENCE,
    "retrieval": SocraticCategory.META,
    "foundation": SocraticCategory.CLARIFICATION,
    "advance": SocraticCategory.PERSPECTIVE,
    "diagnose": SocraticCategory.CLARIFICATION,
    "prerequisite_review": SocraticCategory.CLARIFICATION,  # 기초 지향(선수 명료화)
    "calibration_overconfident": SocraticCategory.ASSUMPTION,  # 가정 재검토(왜 확신?)
    "calibration_underconfident": SocraticCategory.META,  # 메타인지·효능감
    "misconception_review": SocraticCategory.ASSUMPTION,  # 가정 재검토(그 규칙이 항상 맞나?)
}


def focus_to_socratic_category(focus: CoachingFocus) -> SocraticCategory:
    """코칭 포커스 → 대화 진입 소크라테스 카테고리 — 순수 매핑(coach 발화 종류 결정 입력)."""
    return _SOCRATIC_BY_FOCUS[focus]


class CoachingTrigger(BaseModel):
    """메타인지 코칭 결정 — 포커스 + 근거 + 학생 노출 발화. 불변(frozen)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    focus: CoachingFocus = Field(description="코칭 포커스 5종.")
    rationale: str = Field(description="결정 근거(교사/학생 노출 가능 한국어).")
    prompt: str = Field(description="학생에게 보일 수 있는 메타인지 유도 발화(답 미제공).")
    socratic_category: SocraticCategory = Field(
        description="대화 진입 소크라테스 카테고리(coach 발화 종류·slice 5)."
    )
    focus_step_index: int | None = Field(
        default=None,
        description=(
            "verify 포커스가 가리키는 *첫 incorrect 전이* 인덱스(0-based·steps[i]→steps[i+1]). "
            "`verify_solution.first_incorrect_index`를 그대로 옮긴 *구조화 메타데이터*로, 발화"
            "(prompt)와 *별도 채널*이다 — L5가 학생 풀이의 해당 줄 하이라이트·점층 유도·교사 "
            "대시보드에 쓴다. verify 포커스가 아니거나 인덱스 미제공이면 None(하위호환). 위치만 "
            "담을 뿐 정답/본문은 아니다(학생 자기 풀이 구조·노출 안전)."
        ),
    )
    hint_level: HintLevel | None = Field(
        default=None,
        description=(
            "verify 자가검산 발화에 적용된 답 미루기 단계(1 방향~4 안전망·hint_deferral 사다리). "
            "호출자(오케스트레이터)가 `decide_hint_level`로 계산해 전달한 값을 그대로 옮긴 *구조화 "
            "메타데이터*로, 발화(prompt)와 *별도 채널*이다 — L5 점층 렌더·교사 대시보드에 쓴다. "
            "`focus_step_index`와 같은 컨벤션: *verify 포커스일 때만* 채우고 그 외/미제공이면 "
            "None(하위호환). 척도 변환은 L4 내부 책임이며 L5는 단계 라벨만 표시한다."
        ),
    )


def recommend_coaching(
    bkt_mastery: float | None,
    irt_theta: float | None,
    *,
    arithmetic_error: bool = False,
    verify_steps: bool = False,
    incorrect_step_index: int | None = None,
    discrepancy_tol: float = 0.2,
    mastery_threshold: float = 0.6,
    hint_level: HintLevel | None = None,
) -> CoachingTrigger:
    """L2 두 신호(BKT 숙달·IRT θ)+선택적 계산 오류 신호에서 코칭 포커스 결정 — 순수·결정론.

    **우선순위**: `arithmetic_error=True`(구체적 계산 오류가 결정론으로 감지됨·예: L3 관계
    검증기가 학생 풀이의 "2+3=6"을 탐지)면 다른 신호와 무관하게 `verify`(검산) — 슬립 vs
    오개념 구분 원칙: 이해는 있는데 *계산만* 틀린 경우 개념 재교육은 역효과, 구체적 오류는
    스스로 검산하게 하는 것이 직접·효과적이다. 구체적 오류 신호는 θ/숙달 추정(추상)보다
    *즉시 코칭*에 우선한다(데이터가 없어도 작동).

    그 외: 한쪽이라도 없으면 `diagnose`(교차검증 불가). 둘 다 있으면 θ를 숙달 프록시(logistic)로
    환산해 BKT 숙달과 비교: 프록시-숙달 > `discrepancy_tol` → `consolidate`(맞히나 숙달 낮음)·
    < -tol → `retrieval`(숙달했으나 능력 낮음). 차가 tol 이내면 *합의* — 두 신호 평균이
    `mastery_threshold` 미만이면 `foundation`(기초)·이상이면 `advance`(심화).

    `arithmetic_error`는 *L4가 직접 검출하지 않는다* — 호출자(오케스트레이터)가 L3 결정론
    검증 결과를 bool로 전달(레이어 경계: L4는 원시 신호만 받음). `verify_steps`도 같은 *순수 bool* —
    True면 verify 발화를 *단계 자가검산* 변형으로 바꾼다(다단계 대수 슬립용·위치 비지목·slice 61).
    오케스트레이터가 L3 kind="solution"을 이 bool로 환산해 전달(L4는 kind를 모름). 발화·근거는
    포커스별 정본 카탈로그에서 조회(답 미제공·메타인지 유도).

    `incorrect_step_index`(verify_solution 첫 incorrect 전이 인덱스·0-based·None이면 위치
    미지정)도 같은 *순수 신호* — 오케스트레이터가 `verify_solution.first_incorrect_index`를
    그대로 전달한다(L4는 verify_solution을 모름). verify 발화가 단계 자가검산 변형일 때 이
    인덱스가 있으면 *위치 인지 점층 발화*(앞 단계 통과 확인 + 그 지점부터 스스로 재검산)로
    좁히되, *무엇이 왜 어긋났는지·고치는 법은 주지 않는다*(답 미루기·LTHC 최소도움·정서안전).
    인덱스가 None이면 기존 위치 비지목 발화 그대로(하위호환). 또한 verify 포커스면 이 인덱스를
    `CoachingTrigger.focus_step_index`(구조화 메타데이터·발화와 별도 채널)로도 옮긴다.

    `hint_level`(답 미루기 단계·1~4·None이면 미적용)도 같은 *순수 신호* — 호출자가
    `hint_deferral.decide_hint_level`로 *미리 계산*해 전달한다(L4는 raw 입력에서 재계산하지
    않는다·레이어 경계). verify 자가검산 경로(focus=="verify" and verify_steps)에서만 점층에
    쓰인다: 1·2·None이면 *현재 동작 그대로*(가장 빠른 단계에서 멈춤), 3·4면 더 많은 *과정* 비계를
    주는 점층 발화로 바꾼다(과정 재구성 비계·정답/"틀렸다" 미포함·답 미루기·정서안전). verify
    포커스면 이 단계를 `CoachingTrigger.hint_level`(구조화 메타데이터·발화와 별도 채널)로도
    옮긴다(verify가 아니면 None·하위호환).
    """
    if arithmetic_error:
        return _build(
            "verify",
            steps=verify_steps,
            step_index=incorrect_step_index,
            hint_level=hint_level,
        )
    if bkt_mastery is None or irt_theta is None:
        return _build("diagnose")

    proxy = theta_to_mastery_proxy(irt_theta)
    diff = proxy - bkt_mastery
    if diff > discrepancy_tol:
        return _build("consolidate")
    if diff < -discrepancy_tol:
        return _build("retrieval")
    # 합의 — 수준으로 기초/심화 분기.
    level = (bkt_mastery + proxy) / 2.0
    return _build("foundation" if level < mastery_threshold else "advance")


def _build(
    focus: CoachingFocus,
    *,
    steps: bool = False,
    step_index: int | None = None,
    hint_level: HintLevel | None = None,
) -> CoachingTrigger:
    # verify 발화 변형 결정(우선순위 명확):
    #   1) verify + steps + hint_level∈{3,4} → 답 미루기 점층 *과정 재구성 비계*(위치 인지/비지목
    #      각각·정답/수정/"틀렸다" 미포함·답 미루기). 학생이 같은 단계에서 반복해 막혀(상위 단계)
    #      더 많은 *과정* 비계가 필요할 때.
    #   2) verify + steps + hint_level∈{None,1,2} + step_index 제공 → *위치 인지* 단계 자가검산
    #      (앞단계 확인 + 그 지점 재검산·기존 동작 그대로).
    #   3) verify + steps + hint_level∈{None,1,2} + step_index 없음 → 위치 비지목 단계 자가검산
    #      (_PROMPT_VERIFY_STEPS·기존 동작 그대로).
    #   4) 그 외 → 포커스별 정본 발화(_PROMPT).
    if focus == "verify" and steps:
        if hint_level in (3, 4):
            prompt = _verify_steps_escalated_prompt(step_index)
        elif step_index is not None:
            prompt = _verify_steps_at_prompt(step_index)
        else:
            prompt = _PROMPT_VERIFY_STEPS
    else:
        prompt = _PROMPT[focus]
    # focus_step_index는 *구조화 메타데이터*(발화와 별도 채널) — verify 포커스일 때만 step_index를
    # 그대로 옮긴다(steps bool 여부 무관: L5 하이라이트/교사 대시보드는 발화 변형과 독립). verify가
    # 아니거나 인덱스 미제공이면 None(하위호환).
    focus_step_index = step_index if focus == "verify" else None
    # hint_level도 동일 컨벤션 — verify 포커스일 때만 그대로 옮긴다(L5 점층 렌더·교사 대시보드).
    # verify가 아니거나 미제공이면 None(하위호환).
    out_hint_level = hint_level if focus == "verify" else None
    return CoachingTrigger(
        focus=focus,
        rationale=_RATIONALE[focus],
        prompt=prompt,
        socratic_category=_SOCRATIC_BY_FOCUS[focus],
        focus_step_index=focus_step_index,
        hint_level=out_hint_level,
    )


__all__ = [
    "CoachingFocus",
    "CoachingTrigger",
    "focus_to_socratic_category",
    "recommend_coaching",
]
