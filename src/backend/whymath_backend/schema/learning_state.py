"""학습 상태 머신 계약 — 8상태 · 전이표(데이터) · 정책 입출력 (EOS-105).

설계 정본: 계획서 300 §3 「Phase 2의 핵심 상태 머신」 = 실행 프롬프트 카탈로그
`docs/ops/phase2_eos_closed_loop_execution_prompts.md` §P-04.

**이 모듈이 존재하는 이유(한 줄)**: 학습을 *페이지 이동*이 아니라 *상태 전이*로 구현하되,
정의되지 않은 전이가 조용히 통과하지 않게 한다.

핵심 설계 결정 4건
------------------
① **전이는 코드 분기가 아니라 데이터다.** 허용 전이는 `ALLOWED_TRANSITIONS`(frozenset)에만
   선언되며, 판정 함수(`l2/learning_state_machine.py`)는 이 집합만 읽는다. 새 전이를 열려면
   여기 한 줄을 추가한다 — `if`를 추가하는 경로는 없다. 표가 단일 진실 원천이므로 "어떤
   전이가 가능한가"라는 질문의 답이 코드 전체를 읽지 않아도 나온다.

② **미정의 전이는 거부한다.** 표에 없는 (from, to)는 `UndefinedTransitionError`다. 조용히
   통과시키거나 기본 상태로 폴백하지 않는다 — 폴백은 "모른다"를 "괜찮다"로 바꾸는 위장이며
   그 순간 상태 머신은 상태를 보증하지 못한다(CLAUDE.md 침묵 실패 금지).

③ **정책은 교체 가능한 이음매다.** 이 모듈은 정책의 *입력*(`AttemptEvidence`)과
   *출력*(`PolicyDecision`)만 타입으로 고정하고, 규칙 자체는 `l2/learning_state_policy.py`가
   가진다. v1 내부 구현은 if/else지만 BKT/DKT/IRT/LLM으로 교체해도 이 두 타입은 그대로다
   — 교체 가능성을 주석이 아니라 **타입으로** 표현한다(마스터 프리앰블 §2 설계 규율).

④ **과목 중립이다.** 상태·전이·규칙 어디에도 수학 어휘가 없다(`if subject == "math"` 0건).
   import-linter 계약("EOS Core → Math Adapter 금지")이 `schema`를 baseline 0 구역으로
   동결하고 있으므로 이 중립성은 산문이 아니라 CI가 잰다.

진실 원천 중복에 대하여 (2026-09-03 보류 사유의 처리)
-----------------------------------------------------
이 머신의 신설은 2026-09-03 Kiki 결정으로 한 번 보류됐고, 그 사유는 "`*MasteryHistory`와
같은 사실의 두 번째 진실 원천이 생긴다"였다(재확인 지점 G4 · 게이트
`G-state-machine-deferral-recheck`). 2026-09-16 Kiki 지시로 그 보류를 번복해 착수하며,
중복 위험은 **역할을 겹치지 않게 갈라서** 다룬다:

  - `ConceptMasteryHistory`·`SkillMasteryHistory`·`AttemptEvent` = **무슨 일이 있었는가**
    (측정·증거). 이 머신은 그것을 복제하지 않는다 — 숙달값·정답률·이벤트를 저장하지 않는다.
  - 학습 상태 = **그 증거를 근거로 학생이 지금 어느 교육적 국면에 있는가**(제어 평면).
    어느 기존 테이블도 이 사실을 담고 있지 않다(어휘 3종 전수 검색 코드 0건 — EOS-105 notes).

두 축이 어긋날 수 있다는 것 자체는 남는 위험이므로, 영속 상태와 증거에서 재계산한 상태를
대조하는 경로(`l2/learning_state_machine.py::reconcile_state`)를 함께 둔다. 대조가 어긋나면
조용히 덮어쓰지 않고 불일치를 보고한다 — 어느 쪽이 옳은지는 사람이 판정할 문제다.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ALLOWED_TRANSITIONS",
    "AttemptEvidence",
    "HIGH_CONFIDENCE_THRESHOLD",
    "LearningState",
    "NextAction",
    "NextActionKind",
    "PolicyDecision",
    "REPEATED_FAILURE_THRESHOLD",
    "TransitionTrigger",
    "UndefinedTransitionError",
    "allowed_targets",
    "is_transition_allowed",
]


class LearningState(str, Enum):
    """학습 국면 8상태 — 계획서 300 §3.

    값은 대문자 영문 식별자다(한글 값을 쓰는 `EventType`과 다름): 이 열거형은 PG native enum
    라벨·API 응답·클라이언트 분기에 그대로 실리는 **제어 어휘**라 로케일 중립이어야 한다.
    """

    NEW = "NEW"
    """가입 직후 — 아무 진단도 학습도 시작하지 않은 상태. 모든 학생의 시작점이다."""

    DIAGNOSING = "DIAGNOSING"
    """진단 중 — 어디서부터 가르칠지 재는 중. 이 구간의 오답은 실패가 아니라 측정이다."""

    READY = "READY"
    """진단 완료 — 출발점이 정해졌고 아직 첫 학습에 들어가지 않은 상태."""

    LEARNING = "LEARNING"
    """개념 학습 중 — 설명·예시를 통해 새 개념(또는 선수 개념)을 익히는 국면."""

    PRACTICING = "PRACTICING"
    """연습 중 — 익힌 개념을 반복 적용해 숙달을 올리는 국면."""

    ASSESSING = "ASSESSING"
    """평가 중 — 학생의 응답으로 숙달을 판정하는 국면. 정책 규칙이 작동하는 유일한 출발 상태다."""

    REMEDIATING = "REMEDIATING"
    """교정 중 — 오개념 처치·설명·힌트로 막힌 지점을 푸는 국면."""

    ADVANCING = "ADVANCING"
    """진급 중 — 현재 개념을 통과해 다음 개념으로 넘어가는 국면."""


class TransitionTrigger(str, Enum):
    """전이를 일으킨 사건 — "왜 상태가 바뀌었는가"의 기록.

    상태만 남기면 나중에 "이 학생은 왜 REMEDIATING에 있었나"를 재구성할 수 없다. 전이 1건마다
    이 값을 함께 적재해 사후 감사(audit)가 성립하게 한다.

    `POLICY_*` 계열은 `l2/learning_state_policy.py`의 규칙 id와 1:1로 대응한다 — 규칙이
    바뀌면 트리거도 함께 바뀌어야 하며, 그 대응은 테스트가 동결한다.
    """

    DIAGNOSIS_STARTED = "DIAGNOSIS_STARTED"
    DIAGNOSIS_COMPLETED = "DIAGNOSIS_COMPLETED"
    LEARNING_STARTED = "LEARNING_STARTED"
    PRACTICE_STARTED = "PRACTICE_STARTED"
    ATTEMPT_SUBMITTED = "ATTEMPT_SUBMITTED"
    """학생이 응답을 제출해 평가 국면(ASSESSING)에 들어갔다."""

    POLICY_ADVANCE = "POLICY_ADVANCE"
    """정책 R1 — 정답 + 높은 확신."""

    POLICY_PRACTICE_LOW_CONFIDENCE = "POLICY_PRACTICE_LOW_CONFIDENCE"
    """정책 R2 — 정답 + 낮은(또는 미측정) 확신."""

    POLICY_REMEDIATE_MISCONCEPTION = "POLICY_REMEDIATE_MISCONCEPTION"
    """정책 R3 — 오답 + 오개념 확인."""

    POLICY_PREREQUISITE_GAP = "POLICY_PREREQUISITE_GAP"
    """정책 R4 — 오답 + 선수 개념 결손."""

    POLICY_REPEATED_FAILURE = "POLICY_REPEATED_FAILURE"
    """정책 R5 — 반복 실패(설명·힌트 개입)."""

    POLICY_PRACTICE_UNDIAGNOSED = "POLICY_PRACTICE_UNDIAGNOSED"
    """정책 R6 — 오답이나 원인(오개념·선수결손·반복)이 확인되지 않음."""

    REMEDIATION_COMPLETED = "REMEDIATION_COMPLETED"
    ADVANCE_COMPLETED = "ADVANCE_COMPLETED"


# ──────────────────────────────────────────────────────────────────────────
# 전이표 — 이 머신의 단일 진실 원천
# ──────────────────────────────────────────────────────────────────────────
#
# 읽는 법: `(from, to)`가 이 집합에 있으면 허용, 없으면 `UndefinedTransitionError`.
# 판정 함수는 이 집합만 본다 — 전이 규칙을 담은 `if`는 코드베이스 어디에도 없다.
#
# **여기 없는 것이 곧 금지다.** 대표적으로 다음은 *의도적으로* 열지 않았다:
#   - `NEW → ADVANCING`  : 진단·학습 없이 진급. 테스트가 이 쌍으로 거부 경로를 잰다.
#   - `NEW → ASSESSING`  : 첫 접속 학생의 **평가로의 직행**. 상태 이력이 없는 학생을 평가로
#                          밀어 넣으면 "무엇 대비 평가인가"가 없다. 여전히 닫혀 있다.
#                          (주의 — `NEW → LEARNING`은 EOS-115에서 *열었다*. 그것은 평가가
#                          아니라 학습 맥락을 만드는 간선이라 이 금지와 충돌하지 않는다:
#                          진단 없는 학습자도 `NEW → LEARNING → ASSESSING`을 거치므로
#                          "평가는 언제나 학습 맥락에서 출발한다"가 유지된다.)
#   - `DIAGNOSING → LEARNING` : READY(출발점 확정)를 건너뛴 학습 시작.
#   - `READY → ASSESSING`     : 학습 없이 평가.
#   - `ADVANCING → ASSESSING` : 진급 중 평가(다음 개념 LEARNING을 거쳐야 한다).
#
# 새 전이가 필요하면 **여기 한 줄을 추가하고 그 근거를 주석으로 남긴다**. 코드에 분기를
# 더하는 경로는 존재하지 않는다.
ALLOWED_TRANSITIONS: frozenset[tuple[LearningState, LearningState]] = frozenset(
    {
        # ── 온보딩: 가입 → 진단 → 출발점 확정 ──
        (LearningState.NEW, LearningState.DIAGNOSING),
        (LearningState.DIAGNOSING, LearningState.READY),
        # 진단을 거치지 않은 학습자의 첫 학습 진입 (EOS-115).
        #
        # 왜 여는가: 이 시스템은 **진단받지 않은 학습자를 이미 1급 시민으로 모델링하고 있다** —
        # 정책 R6(`POLICY_PRACTICE_UNDIAGNOSED`)의 존재가 그 증거다. 그런데 전이표에는 그들이
        # 학습에 들어갈 문이 없어, 정책이 준비한 자리에 도달할 경로가 없었다. 여기를 닫아 둔
        # 것은 설계 의도가 아니라 표와 정책의 **불일치**였다.
        #
        # 왜 `NEW → ASSESSING`(아래 금지 목록)과 다른가: 그쪽은 "무엇 대비 평가인가"가 없는
        # 평가를 합법으로 만든다. 이 간선은 평가를 만들지 않는다 — 학습 맥락을 만든다. 평가는
        # 여전히 `LEARNING → ASSESSING`을 거쳐야 하므로 "평가는 언제나 학습 맥락에서 출발한다"는
        # 불변식이 그대로 유지된다. 즉 이 한 줄은 그 불변식을 깨는 것이 아니라 **충족시키는**
        # 경로다.
        #
        # 진단 사실을 위조하지 않는다: 원장에는 `from_state=NEW`가 남으므로 "진단 없이 학습에
        # 들어왔다"가 사후에 그대로 읽힌다. `NEW → DIAGNOSING → READY → LEARNING` 3행을 대신
        # 적재하는 선택지도 있었으나 채택하지 않았다 — 일어나지 않은 진단을 원장에 적는 셈이고,
        # 그것은 `reconcile_state`가 잡으려는 바로 그 어긋남을 우리 손으로 만드는 것이다.
        (LearningState.NEW, LearningState.LEARNING),
        # ── 주기: 학습 → 연습 → 평가 ──
        (LearningState.READY, LearningState.LEARNING),
        (LearningState.LEARNING, LearningState.PRACTICING),
        (LearningState.PRACTICING, LearningState.ASSESSING),
        # 학습 직후 평가(연습을 건너뛴 즉시 확인 문항) · 연습 중 연속 제출.
        (LearningState.LEARNING, LearningState.ASSESSING),
        (LearningState.PRACTICING, LearningState.PRACTICING),
        (LearningState.ASSESSING, LearningState.ASSESSING),
        # ── 평가 결과 분기(정책 규칙 R1~R6가 도착하는 곳) ──
        (LearningState.ASSESSING, LearningState.ADVANCING),  # R1 정답+높은 확신
        (LearningState.ASSESSING, LearningState.PRACTICING),  # R2 정답+낮은 확신 · R6
        (LearningState.ASSESSING, LearningState.REMEDIATING),  # R3 오개념 · R5 반복 실패
        (LearningState.ASSESSING, LearningState.LEARNING),  # R4 선수 개념으로 되돌아감
        # ── 교정 이후 ──
        (LearningState.REMEDIATING, LearningState.LEARNING),
        (LearningState.REMEDIATING, LearningState.PRACTICING),
        (LearningState.REMEDIATING, LearningState.ASSESSING),  # 교정 후 재평가
        # ── 진급 이후: 다음 개념 학습으로 ──
        (LearningState.ADVANCING, LearningState.LEARNING),
    }
)


class UndefinedTransitionError(ValueError):
    """전이표에 없는 상태 전이 — 조용히 통과하지 않는다.

    `ValueError`를 상속하는 이유: 호출부가 `except ValueError`로 넓게 잡던 기존 코드에서도
    이 오류가 *삼켜지지 않고* 최소한 같은 등급으로 다뤄지게 한다. 다만 호출부는 가급적 이
    타입을 명시적으로 잡아 무엇이 거부됐는지 표면에 드러내야 한다(CLAUDE.md 침묵 실패 금지 —
    예외 타입명을 로그에 포함).
    """

    def __init__(self, from_state: LearningState, to_state: LearningState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"정의되지 않은 학습 상태 전이입니다: {from_state.value} → {to_state.value}. "
            f"허용 전이는 schema/learning_state.py의 ALLOWED_TRANSITIONS에만 선언됩니다 — "
            f"{from_state.value}에서 갈 수 있는 상태: "
            f"{sorted(s.value for s in allowed_targets(from_state)) or '없음'}."
        )


def is_transition_allowed(from_state: LearningState, to_state: LearningState) -> bool:
    """전이표 조회 — 순수 함수(부수효과·DB 접근 없음).

    판정은 **표만** 본다. 이 함수 안에 상태별 분기를 넣지 말 것 — 넣는 순간 전이 규칙의
    진실 원천이 둘(표 + 분기)이 된다.
    """
    return (from_state, to_state) in ALLOWED_TRANSITIONS


def allowed_targets(from_state: LearningState) -> frozenset[LearningState]:
    """주어진 상태에서 갈 수 있는 상태 집합 — 오류 메시지·API 안내용."""
    return frozenset(to_state for src, to_state in ALLOWED_TRANSITIONS if src == from_state)


# ──────────────────────────────────────────────────────────────────────────
# 정책 경계 — 입력(증거)과 출력(결정)의 타입
# ──────────────────────────────────────────────────────────────────────────

HIGH_CONFIDENCE_THRESHOLD: float = 0.7
"""정답을 "높은 확신"으로 볼 경계(자기보고 0~1).

v1은 학생 자기보고(`ProblemAttempt.confidence_self_reported`)를 쓴다. 나중에 BKT 사후확률·
IRT θ 기반 추정 확신도로 교체되더라도 `AttemptEvidence.confidence`의 **의미와 범위(0~1)는
그대로**이므로 규칙 코드는 건드리지 않는다 — 교체 지점을 타입으로 고정한 결과다.
"""

REPEATED_FAILURE_THRESHOLD: int = 3
"""이 횟수 이상 연속 실패하면 원인 분류보다 설명·힌트 개입이 앞선다.

같은 개념에서 3연속 틀린 학생에게 "오개념 교정"을 정밀하게 하는 것보다 먼저 막힌 지점을
풀어 주는 것이 교수학적으로 우선이다(CLAUDE.md 의사결정 우선순위 1 학생 정서 > 3 정확성).
그래서 R5가 R3·R4보다 먼저 평가된다.
"""


class AttemptEvidence(BaseModel):
    """정책이 읽는 **증거** — 한 번의 응답 제출에서 관측된 사실만.

    이 모델은 *추정치가 아니라 증거*를 담는다. 그래서 BKT를 DKT로, 규칙 기반 오개념 매칭을
    LLM 후보 분류로 바꿔도 필드 구성은 유지된다 — 바뀌는 것은 이 값을 **누가 채우는가**다.
    (마스터 프리앰블: "교체 가능성을 주석이 아니라 타입으로 표현한다".)

    **LLM은 여기까지만 온다.** LLM은 `confirmed_misconception_ids`의 *후보*를 제안할 수 있지만,
    그 후보가 확인(confirmed)으로 승격되는 판단과 상태 전이의 최종 결정은 정책 엔진이 한다
    (마스터 프리앰블 설계 규율 — LLM은 학습 상태를 직접 결정하지 않는다).
    """

    model_config = ConfigDict(frozen=True)

    is_correct: bool = Field(description="이번 응답의 정오답. 규칙 R1~R6의 1차 분기축.")
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "확신도 0~1. v1 생산자는 학생 자기보고(`confidence_self_reported`)이며 "
            "**미측정은 None**이다 — 0.0으로 채우지 않는다(미측정과 '확신 없음'은 다른 사실)."
        ),
    )
    confirmed_misconception_ids: tuple[str, ...] = Field(
        default=(),
        description=(
            "이번 오답에서 *확인된* 오개념 id. 후보(가설)가 아니라 확인분만 담는다 — "
            "가설 단계 값을 넣으면 R3가 추측으로 학생을 교정 국면에 밀어 넣는다."
        ),
    )
    prerequisite_gap_concept_ids: tuple[str, ...] = Field(
        default=(),
        description="이번 오답의 원인으로 지목된 선수 개념 id(약한 것부터). R4의 입력.",
    )
    consecutive_failures: int = Field(
        default=0,
        ge=0,
        description=(
            "이번 응답을 **포함한** 같은 개념 연속 오답 수. 정답이면 0이 자연스럽다 — "
            "다만 정책은 이 값을 `is_correct`와 함께만 읽으므로 모순 입력에서도 오동작하지 않는다."
        ),
    )


class NextActionKind(str, Enum):
    """다음 행동의 *종류* — 무엇을 보여줄지의 구체는 L4·L6이 정한다.

    이 열거형은 제어 어휘지 콘텐츠가 아니다. "어떤 문항을 낼 것인가"·"힌트를 몇 단계로
    줄 것인가"는 여기서 정하지 않는다(그것을 여기로 끌어오면 L2가 교수학을 구현하게 된다 —
    7계층 경계 침범).
    """

    ADVANCE_TO_NEXT_CONCEPT = "ADVANCE_TO_NEXT_CONCEPT"
    PRACTICE_SAME_CONCEPT = "PRACTICE_SAME_CONCEPT"
    REMEDIATE_MISCONCEPTION = "REMEDIATE_MISCONCEPTION"
    GO_TO_PREREQUISITE_CONCEPT = "GO_TO_PREREQUISITE_CONCEPT"
    OFFER_EXPLANATION_OR_HINT = "OFFER_EXPLANATION_OR_HINT"


class NextAction(BaseModel):
    """정책이 지시하는 다음 행동 — 종류 + 대상 + 근거.

    `rationale`은 사람이 읽는 문장이 아니라 **기계가 읽는 근거 식별자**를 담는 자리다
    (규칙 id·증거 id). 학생에게 보일 문장은 L4가 만든다 — 표현과 의미를 섞지 않는다
    (CLAUDE.md "표현 ≠ 의미").
    """

    model_config = ConfigDict(frozen=True)

    kind: NextActionKind
    target_concept_id: str | None = Field(
        default=None,
        description=(
            "행동의 대상 개념 id. `GO_TO_PREREQUISITE_CONCEPT`이면 되돌아갈 선수 개념, "
            "그 외에는 None일 수 있다(현재 개념을 그대로 이어감)."
        ),
    )
    target_misconception_id: str | None = Field(
        default=None, description="`REMEDIATE_MISCONCEPTION`의 처치 대상 오개념 id."
    )


class PolicyDecision(BaseModel):
    """정책 1회 실행의 결과 — 다음 상태 + 다음 행동 + 어느 규칙이 결정했는가.

    `rule_id`가 필수인 이유: 이것이 없으면 "왜 이 학생이 REMEDIATING으로 갔는가"를 사후에
    재구성할 수 없다. 알고리즘을 붙였으면 **그 알고리즘이 작동한 비율**을 말할 수 있어야
    한다(CLAUDE.md "작동한 비율" 원칙) — `rule_id` 분포가 그 비율의 원자료다.
    """

    model_config = ConfigDict(frozen=True)

    next_state: LearningState
    next_action: NextAction
    rule_id: str = Field(description="결정을 낸 규칙 식별자(예: 'R3-wrong-misconception').")
    trigger: TransitionTrigger = Field(description="전이 적재에 함께 남길 사유 코드.")
