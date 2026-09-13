"""오개념 진단·개입 — 모델·인터페이스.

`docs/architecture/04_pedagogy_engine.md` §"오개념 진단·개입"(L121-127) + `docs/prompts/
misconception_diagnosis.md` 정본.

핵심 원칙(스펙 L126 + 절대 금지 §): **직접 교정 ❌ / 반례 유도 ✅ / 구체 사례 ✅**.
학생 라벨링("이건 흔한 오개념이야") 금지·재풀이 강요 금지.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MisconceptionDomain = Literal[
    "대수", "기하", "확률통계", "함수", "미적분", "수열", "삼각함수", "벡터"
]
"""오개념 카탈로그 영역 — 정본 prompt doc 분류. 슬: 대수·기하·확률통계·함수 +
수능 핵심(미적분·수열·삼각함수·벡터). doc `### N 영역` 섹션과 1:1."""


class Misconception(BaseModel):
    """카탈로그 단위 — `docs/prompts/misconception_diagnosis.md` 정본 ID·내용 정렬.

    `signals`는 학생 풀이에 *공출현*해야 매칭되는 substring 토큰(AND). 첫 슬라이스의 매칭은
    규칙 기반(임베딩·LLM-judged는 후속) — 토큰 모두 일치 시 confidence=1.0.

    `counterexample`은 *반례*(패턴 1) 어셈블리 입력. `canonical_statement`는 학생 가정 진술.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(
        description="정본 ID — kebab-case(예: 'distribution-over-power'). doc과 1:1.",
    )
    name_kr: str = Field(description="짧은 한국어 라벨(예: '제곱 분배').")
    domain: MisconceptionDomain = Field(description="카탈로그 영역.")
    canonical_statement: str = Field(
        description="학생이 *암묵적으로 가정한* 잘못된 진술(예: '(a+b)² = a²+b²').",
    )
    counterexample: str = Field(
        description="반례 입력(예: 'a=1, b=1') — 패턴 1 어셈블리에 사용.",
    )
    signals: tuple[str, ...] = Field(
        description=(
            "학생 풀이에 *공출현*해야 매칭되는 substring 토큰(AND). 모두 일치=confidence 1.0."
        ),
    )
    regex_signals: tuple[str, ...] = Field(
        default=(),
        description=(
            "v1.2 보조 탐지 경로 — *정규화된 텍스트*에 `re.search`로 검사하는 정규식(OR). "
            "주로 *거짓 항등식의 수치 대입*(예: `(3+4)²=3²+4²`)을 잡는다. 미설정(기본 빈 튜플) 시 "
            "기존 substring 동작 불변. v1.5(MISC-22): 정규식 매치 1건은 substring 신호 **전체**와 "
            "동등한 완결 증거로 가산(단독으로도 confidence 1.0) — 명명그룹 역참조로 정답·기호식과 "
            "*disjoint*하게 작성된 정규식은 substring AND 전체에 준하는 확정적 단서이기 때문이다. "
            "그래서 정규식은 *반드시* 기호 substring 케이스·정답과 겹치지 않게(disjoint) 작성해야 "
            "하고(그렇지 않으면 확신 오진단), substring만으로의 기존 confidence·matched_signals는 "
            "불변이다."
        ),
    )
    refuting_regex: tuple[str, ...] = Field(
        default=(),
        description=(
            "**반박 조건**(OR·정규식) — 하나라도 정규형 텍스트에 매치되면 이 오개념은 매칭 자체가 "
            "성립하지 않는다(`_match_one`이 None 반환). `signals`가 다 맞아도 무효다.\n\n"
            "`signals`·`regex_signals`가 *양성* 단편을 찾는 것과 반대 방향이며, 공출현 AND에 "
            "**부정 조건이 없다는 구조적 공백**을 메운다(MISC-23). 그 공백의 실례: "
            "`root-loss-by-dividing`의 `('양변','x로 나누')`는 근 손실을 *저지른* 풀이와 그 함정을 "
            '*정확히 설명한 정답*을 구별하지 못해, "…x=2만 나와서 안 되고 해는 0과 2다"라는 '
            "정답에 confidence 1.0을 줬다(게이트 0.65를 넘어 확신 오진단이 나갔다).\n\n"
            "**왜 감점이 아니라 거부인가**: 오개념 귀속이 *반박된* 것이지 *덜 확실한* 것이 아니다. "
            "낮은 confidence로 남기면 하류(가설·역추적·shadow)가 그것을 약한 증거로 "
            "취급한다 — 반박된 후보는 증거가 아니라 소음이다. 또 놓치는 오류보다 **정답에 틀렸다고 "
            "말하는 오류가 해롭다**(결정 우선순위 #1 학생 정서).\n\n"
            "미설정(기본 빈 튜플)이면 동작 완전 불변 — 기존 항목은 이 필드를 갖지 않는다."
        ),
    )
    ambiguous_regex_signals: bool = Field(
        default=False,
        description=(
            "**MISC-24** — true면 이 항목의 `regex_signals` 매치는 `matched_regex_signals`"
            "(디버그·텔레메트리)에는 여전히 기록되지만 confidence 가산에는 **기여하지 않는다**"
            "(`_match_one`이 numerator에서 완전히 배제 — matched substring만으로 confidence를 "
            "결정). `refuting_regex`(반박·OR)와는 반대 축이다: 반박은 *반박할 문자열*이 따로 "
            "있어야 성립하는데, 이 필드가 다루는 케이스는 반박할 대상 자체가 없다 — 극점 x좌표와 "
            "극값이 *우연히 같은 수*(f(x₀)=x₀)인 정답과, 그 값을 x좌표로 혼동한 오답은 텍스트가 "
            "**글자 그대로 동일**하다(disjoint 증명이 성립하지 않음 — MISC-22가 다른 5개 정규식 "
            "채널에 요구한 disjoint 보증과 근본적으로 다른 케이스). 옛 v1.2식(정규식 매치=신호 "
            "1개 상당)으로도 이 문제는 안 풀린다: `extremum-value-vs-point-confused`는 signals가 "
            "2개뿐이고 정규식 패턴 자체가 리터럴 '극댓값'을 포함해 매치 시 substring이 이미 1개"
            "(=신호 1개 상당) 함께 발화하므로, 옛 식으로도 1(substring)+1(regex 1개 credit)="
            "2=len(signals) → confidence 1.0으로 동일하게 게이트를 넘는다(실측: MISC-24). 그래서 "
            "이 필드는 *가산분을 아예 0으로* 만든다 — 이 항목의 confidence는 substring 신호"
            "(`극댓값`·`x좌표`)만으로 결정되고, 'x좌표'라는 말을 학생이 실제로 쓴 명시적 케이스만 "
            "confidence 1.0(원래도 정규식과 무관하게 도달하던 경로)에 도달한다. 미설정(기본 "
            "False)이면 기존 항목(MISC-22 5개 채널) 동작 완전 불변."
        ),
    )
    canonical_wrong_form: tuple[str, str] | None = Field(
        default=None,
        description=(
            "거짓 항등식의 *머신 검증 가능* 표현 (lhs, rhs) — SymPy syntax(`**`·`sqrt`·`log`). "
            "부여 시 카탈로그 무결성 테스트가 `identity_status`(동치 권위 단일·L3)로 "
            "**not_identity**(SymPy가 거짓임을 *증명*)임을 강제한다 → 'wrong form이 실제로 "
            "틀렸다'를 문자열이 아닌 *기호 권위*로 못 박는다(감사 §7·동치 권위 일원화). 정직 "
            "스코프: SymPy가 가정 없이 반증 가능한 *다항* 거짓 항등식에만 부여(예 `(a+b)²=a²+b²`·"
            "`a⁰=0`). 정의역 의존(`√(x²)=x`)·초월(`log(a+b)`)·유리식은 SymPy 미결정이라 *부여 "
            "안 함*(거짓 머신 검증 주장 금지·regex/substring·semantic 경로가 담당). "
            "`canonical_statement`(표시 문자열)와 별개의 *구조* 표현이다(표현≠의미)."
        ),
    )
    correct_form: str | None = Field(
        default=None,
        description=(
            "오개념의 *정정 형태*(올바른 항등식·식) — identity-shaped 오개념에만 선택 부여. 학생의 "
            "*검증된* clean 풀이에 이 형태가 나타나면 그 오개념을 *강하게* 반박(−1·정밀 귀속)하는 "
            "신호다(`correct_form_present`·tier). 표기는 `signals`와 동일(위첨자·공백 가변)·매칭은 "
            "`_normalize`(NFKC+공백제거)로 흡수. None(기본)이면 정정 탐지 비활성 → 기존(일반 "
            "clean) 약한 반박 동작 불변. 부여 시 *불변식*: `diagnose(correct_form)`이 그 오개념을 "
            "신뢰 게이트(0.65) 이상으로 내면 안 됨(정정이 자기 오개념으로 confident 오진단 금지) — "
            "카탈로그 테스트로 강제. 그래서 `signals`의 LHS만 공유하고 *틀린 RHS*는 미포함하는 "
            "오개념(distribution·log·곱미분·sin 합분배·a⁰)에만 단다."
        ),
    )


class MisconceptionMatch(BaseModel):
    """진단 결과 1건 — misconception + 신뢰도(0-1) + 매칭 신호(디버그·UI)."""

    model_config = ConfigDict(extra="forbid")

    misconception: Misconception
    confidence: float = Field(ge=0.0, le=1.0)
    matched_signals: tuple[str, ...] = Field(
        default_factory=tuple,
        description="실제 매칭된 substring signals 부분집합(디버그·UI 표시 후보).",
    )
    matched_regex_signals: tuple[str, ...] = Field(
        default_factory=tuple,
        description=(
            "v1.2 — 실제 매치된 `regex_signals` 부분집합(디버그·UI). substring `matched_signals`와 "
            "분리해 보관하므로 기존 소비자의 matched_signals 단언은 불변."
        ),
    )
    attribution_unclear: bool = Field(
        default=False,
        description=(
            "MISC-28 — 학생 풀이에 정정 어구가 있으나 그것이 **이 오개념을 가리키는지** 판정할 "
            "수 없을 때 True(신호 *앞*의 정정). 두 가지가 위치로 구별되지 않기 때문이다: "
            "정당한 반박(`틀린 풀이: <오개념>` — 라벨 후 인용)과 무관한 정정"
            "(`부호를 잘못 옮겨 적었지만 <오개념>`). **매칭은 유지하되**(억제하면 후자를 통째로 "
            "미검출) 확신 진단은 보류한다 — `MatchGateResult.low_quality`와 같은 좌석이다. "
            "정정 어구가 신호 *뒤*면 귀속이 어순으로 확정돼 `_match_one`이 아예 None을 내므로 "
            "이 플래그가 붙은 결과로 오지 않는다. 기본 False(정정 어구 없음·기존 동작 불변)."
        ),
    )
    semantic_similarity: float | None = Field(
        default=None,
        description=(
            "slice 104 — 의미(임베딩) 매칭 경로의 코사인 유사도. substring/regex 경로의 결과는 "
            "*None*(이 필드 미설정)이고, `semantic_matches`가 만든 결과만 코사인 값을 담는다. "
            "선택 필드(기본 None)라 기존 substring 결과·소비자 단언은 불변. **정직 스코프**: 의미 "
            "유사도는 패러프레이즈·동의어 recall만 반영하고 *방향·부정·등치*는 못 가린다(임베딩 "
            "방향맹 — LLM-judged 후속). confidence와 다른 축(이 값은 진단 신뢰가 아니라 표면 "
            "근접도)이니 호출자는 둘을 혼동하지 말 것."
        ),
    )


class InterventionPattern(str, Enum):
    """개입 패턴 4종 — `docs/prompts/misconception_diagnosis.md` "표준 패턴" 정본.

    값은 doc의 패턴 번호 라벨(`pattern_1` ~ `pattern_4`)과 정렬.
    """

    COUNTEREXAMPLE = "counterexample"  # 패턴 1 — 반례 유도
    CONCRETE_CASE = "concrete_case"  # 패턴 2 — 구체 사례
    VISUALIZATION = "visualization"  # 패턴 3 — 시각화 유도
    REVERSE_REASONING = "reverse_reasoning"  # 패턴 4 — 거꾸로 사고


class InterventionDecision(BaseModel):
    """개입 결정 — 패턴 + 학생에게 노출할 프롬프트(반례·구체사례 어셈블리 후).

    `confidence`가 임계 미만이면 호출자(엔진)는 *진단 보류*(None) — 본 모델은 결정된 경우만
    반환된다(스펙 결정트리 L226).
    """

    model_config = ConfigDict(extra="forbid")

    pattern: InterventionPattern
    prompt: str = Field(description="학생에게 노출할 어셈블된 발화(자각 유도형).")
    misconception_id: str = Field(description="진단된 misconception.id — 텔레메트리.")
