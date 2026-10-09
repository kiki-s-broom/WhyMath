"""L4 교수학 엔진 — 모델·인터페이스(Pydantic·Protocol).

`docs/architecture/04_pedagogy_engine.md` §"인터페이스"(L139-174) 정본 반영.
- `PolyaStage` — 4단계 식별자(UNDERSTAND/PLAN/EXECUTE/REVIEW).
- `PolyaState` — 세션의 현재 단계·이력·턴 수(L4 spec §"Polya 4단계 엔진" L26).
- `StageTransition` — 다음 단계 전이 결정(stay/next/previous).
- `PedagogyDecision` — L4 결정 단위(스펙 §"인터페이스" L162-174).
- `ToneReport` — 톤필터 위반·재작성 기록(KPI 입력).
- `LLMSeam` — L4→L3 호출 경계(Protocol, L3 import 0 — 계층 분리 유지).
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.l3.models import CostTier


class PolyaStage(str, Enum):
    """Polya 4단계 — `docs/architecture/04_pedagogy_engine.md` L22-27 정본."""

    UNDERSTAND = "understand"
    """이해 — 문제가 뭐야? 자기 언어로 재진술."""

    PLAN = "plan"
    """계획 — 어떻게 풀까? 전략·접근 선정."""

    EXECUTE = "execute"
    """실행 — 해보자. AI는 관찰자, 학생이 단계별 실행."""

    REVIEW = "review"
    """검토 — 맞나? 다른 방법? 일반화·전이 메타인지."""


StageTransition = Literal["stay", "next", "previous"]
"""다음 단계 전이 결정. *자동 previous는 절대 없음* — 학생 명시 후퇴 신호로만 발생."""


POLYA_STAGE_ORDER: tuple[PolyaStage, ...] = (
    PolyaStage.UNDERSTAND,
    PolyaStage.PLAN,
    PolyaStage.EXECUTE,
    PolyaStage.REVIEW,
)
"""단계 순서 정본(스펙 L22-27). PED-04 이전에는 `polya/engine.py`·`socratic/select.py`가
동일 튜플을 각자 사복제했고, `DialogueTurn.targeted_step`(1-기반 인덱스) 적재·역산이 세 번째
사본을 요구하게 되어 여기로 단일화했다 — 유지보수 지옥 방어(단일 진실원천)."""


def next_polya_stage(current: PolyaStage) -> PolyaStage:
    """현 단계의 다음 단계. REVIEW는 종착이라 자기 자신(셀프루프)."""
    idx = POLYA_STAGE_ORDER.index(current)
    if idx == len(POLYA_STAGE_ORDER) - 1:
        return current
    return POLYA_STAGE_ORDER[idx + 1]


def polya_stage_index(stage: PolyaStage) -> int:
    """단계 → **1-기반** 인덱스(UNDERSTAND=1 … REVIEW=4).

    `DialogueTurn.targeted_step`(INTEGER)의 값 공간 정본. 1-기반인 이유: 0은 "미지정"과
    구분되지 않아 NULL/0 혼동을 부른다(적재 여부 판정이 값 자체로 서게 하려는 것).
    """
    return POLYA_STAGE_ORDER.index(stage) + 1


def polya_stage_from_index(index: int | None) -> PolyaStage | None:
    """1-기반 인덱스 → 단계. 범위 밖·None이면 None(관용 — 과거 행·손상 값 방어).

    PED-04 D2가 `targeted_step`에서 서버측 Polya 상태를 역산할 때 쓴다.
    """
    if index is None or not 1 <= index <= len(POLYA_STAGE_ORDER):
        return None
    return POLYA_STAGE_ORDER[index - 1]


class PolyaState(BaseModel):
    """세션의 현재 Polya 상태. 자연스러운 진행·후퇴 추적(스펙 §"Polya 4단계 엔진" L27).

    `turn_count`는 단계 *내* 턴 수(전이 시 0으로 리셋) — 같은 단계서 5회+ 막히면
    답 미루기 단계 상승의 시그널(후속 슬라이스). 답 미루기 KPI 입력.
    """

    model_config = ConfigDict(extra="forbid")

    current_stage: PolyaStage = Field(
        default=PolyaStage.UNDERSTAND,
        description="현재 단계. 새 세션은 1단계(이해)에서 시작.",
    )
    history: list[PolyaStage] = Field(
        default_factory=list,
        description="단계 전이 이력(전이 직전 단계만 append). 후퇴 빈도 분석용.",
    )
    turn_count: int = Field(
        default=0,
        ge=0,
        description="현재 단계서 누적 턴 수(전이 시 0 리셋). 막힘 길이의 신호.",
    )
    prev_hint_level: int | None = Field(
        default=None,
        ge=1,
        le=4,
        description=(
            "직전 응답의 답 미루기 단계(1-4). None이면 첫 결정(1부터 시작). "
            "점진 상승 규칙(socratic_template 시나리오 3·4)의 입력."
        ),
    )


class PedagogyDecision(BaseModel):
    """L4가 한 발화에서 내리는 결정 단위 — 스펙 §"인터페이스" L162-174 정본.

    - `polya_stage_to_advance`: 다음 단계로 갈지(`next`)·머무를지(`stay`)·후퇴(`previous`).
    - `hint_level`: 답 미루기 4단계(1=가장 은근, 4=전체 풀이). 기본 1(가장 자주·생산적 막힘 우선).
    - `socratic_category`: 6카테고리 중 하나(슬라이스 1은 빈 문자열 기본, 슬라이스 2서 채움).
    - `prompt`/`system`: 다음 발화에 사용할 시스템·사용자 프롬프트(L3 호출 좌석에 전달).
    - `recommended_cost_tier`: *교수학적 권장 비용 티어*(스펙 L171 — L4는 축1만 힌트,
      로컬 모델 크기는 L3 라우터 결정).
    - `suggested_actions`: 보조 UI/내부 후속 행동 라벨.
    """

    model_config = ConfigDict(extra="forbid")

    polya_stage_to_advance: StageTransition = Field(description="다음 단계 전이 결정.")
    # `hint_deferral.HintLevel`과 동일한 Literal을 *인라인*한다 — models→hint_deferral import는
    # 순환(hint_deferral→lthc→…→models)이라 회피하고, mypy는 두 Literal[1,2,3,4]를 *같은 타입*으로
    # 보므로 `recommend_coaching(hint_level=)`(HintLevel|None)에 그대로 전달된다(점층 입력).
    hint_level: Literal[1, 2, 3, 4] = Field(
        default=1,
        description="답 미루기 단계(1=가장 은근/방향, 4=전체 풀이/마지막 수단). 항상 1~4.",
    )
    socratic_category: str = Field(
        default="",
        description="소크라테스 6카테고리 라벨(슬라이스 2에서 채움; 기본 빈 문자열).",
    )
    prompt: str = Field(description="사용자 프롬프트(학생에게 던질 발화의 본문).")
    system: str = Field(description="시스템 프롬프트(역할·금기·톤 지시).")
    recommended_cost_tier: CostTier = Field(
        default=CostTier.LOCAL,
        description="권장 비용 티어 — Polya 코칭 기본은 LOCAL(CLAUDE.md '로컬 LLM 우선').",
    )
    suggested_actions: list[str] = Field(
        default_factory=list,
        description="단계 보조 행동 라벨(UI 표시·내부 트리거 후보).",
    )
    reveals: str = Field(
        default="",
        description=(
            "노출량 라벨(스펙 L41-50, PRD `Hint.reveals` 정렬). `hint_level`에서 파생 — "
            "1=next_concept_to_focus·2=step_flow·3=partial_steps_demo·4=full_solution. "
            "세션당 평균 노출량 KPI 입력."
        ),
    )
    # EOS-178 — 공급 원장(`힌트제공`)에 싣는 *내부 계측*이라 응답 본문에는 나가지 않는다
    # (`exclude=True` — 직렬화·OpenAPI 응답 스키마에서 빠진다. `model_copy(update=)`는 보존한다).
    base_hint_level: Literal[1, 2, 3, 4] | None = Field(
        default=None,
        exclude=True,
        description=(
            "능력 라벨 없이 계산한 단계(`hint_deferral.decide_base_hint_level`). `hint_level`과 "
            "비교하면 그 턴의 단계가 학생 신호 때문인지 라벨 때문인지 가른다. None=엔진을 거치지 "
            "않은 결정(직접 구성)."
        ),
    )
    applied_mastery_level: str | None = Field(
        default=None,
        exclude=True,
        description=(
            "이 결정에 적용된 능력 라벨('초보'|'발전 중'|'숙달'). None=라벨 없이 결정됨(숙달도 "
            "미관측·stateless). 라벨 정확도 계측의 입력 — 응답 본문에는 나가지 않는다."
        ),
    )
    label_source: str | None = Field(
        default=None,
        exclude=True,
        description=(
            "적용된 능력 라벨이 *어디서 왔는지*(EOS-179): 'explicit'(클라가 `mastery_level`을 직접 "
            "보냄)·'server_bkt'(서버 L2 개념 숙달도가 들어감)·'server_theta'(서버 θ만)·"
            "'client_bkt'(클라 제출 bkt가 들어감 — 서버가 검증하지 못한 입력). None=라벨 없음 또는 "
            "엔진을 거치지 않은 결정. 라벨 정확도 해석의 층화 축이며 응답 본문에는 나가지 않는다."
        ),
    )
    label_evidence_n: int | None = Field(
        default=None,
        exclude=True,
        ge=0,
        description=(
            "라벨을 만든 서버 개념 숙달도의 관측 수(`concept_mastery_history.sample_size`). "
            "None=**모름**(서버 숙달도가 라벨에 안 들어갔거나 sample_size가 기록되지 않음) — 0이 "
            "아니다. 관측 1~2건짜리 라벨과 수십 건짜리 라벨을 같은 정확도로 세지 않기 위한 "
            "입력이며 응답 본문에는 나가지 않는다."
        ),
    )


class ToneReport(BaseModel):
    """정서 안전 톤필터 결과 — 위반 패턴·재작성 여부 기록.

    `violations`는 발견된 금지 패턴 목록(원문 순). `rewritten`은 치환 발생 여부.
    KPI: 세션당 violations 합계 = 정서 안전 0건 위반 목표 추적(스펙 §"성공 기준" L183).
    """

    model_config = ConfigDict(extra="forbid")

    violations: list[str] = Field(
        default_factory=list,
        description="발견된 금지 패턴 목록(원문 순서·중복 가능).",
    )
    rewritten: bool = Field(
        default=False, description="텍스트가 실제로 치환됐는지(=violations 비공집합)."
    )


@runtime_checkable
class LLMSeam(Protocol):
    """L4→L3 호출 경계 — Protocol으로 L3 import 의존성 격리.

    L4는 *결정*, L3는 *생성*(스펙 L13). L4 단위 테스트는 이 Protocol에 FakeProvider를
    주입해 LLM 없이 검증한다. 실제 결선(L3 라우터 + provider 호출 → 이 Protocol 만족
    어댑터)은 별도 슬라이스(HTTP 노출·L2 통합 시).
    """

    async def generate(self, prompt: str, system: str) -> str:
        """프롬프트·시스템 발화를 받아 LLM 응답을 반환."""
        ...
