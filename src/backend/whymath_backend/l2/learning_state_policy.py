"""L2 — 학습 상태 정책 엔진: 증거 → (다음 상태, 다음 행동) (EOS-105).

설계 정본: 계획서 300 §3 = `docs/ops/phase2_eos_closed_loop_execution_prompts.md` §P-04 항목 2·3.

이 모듈의 자리
--------------
    Event → LearnerState → **Policy** → Next Action

`Event`(응답 제출)에서 뽑은 증거(`AttemptEvidence`)와 현재 상태를 받아 다음 상태·행동을
낸다. 상태 전이의 *합법성* 판정은 하지 않는다 — 그것은 `learning_state_machine`의 몫이고,
이 분리 덕에 "정책이 이상한 상태를 제안했다"와 "전이표가 그것을 거부했다"가 서로 다른
실패로 남는다(둘을 합치면 어느 쪽이 틀렸는지 알 수 없다).

교체 가능성 (마스터 프리앰블 §2 · 원 문서 §10·§13)
--------------------------------------------------
`LearningStatePolicy`는 Protocol이다. v1 구현(`RuleBasedPolicyV1`)의 내부는 if/else지만,
호출 계약 `decide(state, evidence) -> PolicyDecision`은 BKT·DKT·IRT·LLM 기반 정책으로
바꿔도 그대로다. 호출부는 구현체가 아니라 Protocol만 안다 — 교체 시 호출부 수정 0.

**LLM은 이 경로에서 상태를 결정하지 않는다.** LLM은 `AttemptEvidence`를 *채우는* 쪽
(오개념 후보 분류 등)에 관여할 수 있고, 결정된 행동을 *설명으로 번역하는* 쪽(L4)에
관여한다. 그 사이의 판단은 정책 엔진이 가진다.

규칙 우선순위가 왜 이 순서인가
------------------------------
R5(반복 실패)가 R3(오개념)·R4(선수결손)보다 **앞선다**. 같은 개념에서 연속으로 막힌 학생에게
원인 분류를 정밀하게 하는 것보다 먼저 막힌 지점을 풀어 주는 것이 앞선다(CLAUDE.md 의사결정
우선순위 1 학생 정서·웰빙 > 3 교수학적 정확성). 이 순서를 뒤집으면 3연속 오답 학생이 계속
오개념 교정만 받고 설명을 못 받는다.

R3(오개념)가 R4(선수결손)보다 앞선다. 오개념은 *틀린 것을 알고 있는* 상태라 선수 개념을
다시 가르쳐도 그 오개념이 그대로 남는다 — 먼저 지워야 한다.

미매치는 예외다
---------------
어떤 규칙도 매치되지 않으면 `NoMatchingPolicyRuleError`를 낸다. 기본 상태로 폴백하지 않는다
— 폴백은 규칙 구멍을 정상 동작으로 위장하고, 그러면 규칙을 하나 지워도 테스트가 초록이다
(CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지"의 반대편: 규칙의 부재가
관측 가능해야 뮤테이션이 RED를 낼 수 있다).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from whymath_backend.schema.learning_state import (
    HIGH_CONFIDENCE_THRESHOLD,
    REPEATED_FAILURE_THRESHOLD,
    AttemptEvidence,
    LearningState,
    NextAction,
    NextActionKind,
    PolicyDecision,
    TransitionTrigger,
)

__all__ = [
    "V1_RULES",
    "LearningStatePolicy",
    "NoMatchingPolicyRuleError",
    "PolicyRule",
    "RuleBasedPolicyV1",
    "default_policy",
]


class NoMatchingPolicyRuleError(RuntimeError):
    """어떤 규칙도 매치되지 않았다 — 기본값으로 넘어가지 않고 거부한다.

    이 예외가 뜬다는 것은 규칙 집합에 구멍이 있다는 뜻이다. 호출부가 이것을 삼키면 그 구멍은
    영원히 보이지 않는다.
    """

    def __init__(self, state: LearningState, evidence: AttemptEvidence) -> None:
        self.state = state
        self.evidence = evidence
        super().__init__(
            f"상태 {state.value}의 증거에 매치되는 정책 규칙이 없습니다 "
            f"(is_correct={evidence.is_correct}, confidence={evidence.confidence}, "
            f"misconceptions={len(evidence.confirmed_misconception_ids)}, "
            f"prereq_gaps={len(evidence.prerequisite_gap_concept_ids)}, "
            f"consecutive_failures={evidence.consecutive_failures}). "
            f"규칙 집합에 구멍이 있습니다 — l2/learning_state_policy.py::V1_RULES 확인."
        )


@runtime_checkable
class LearningStatePolicy(Protocol):
    """정책 이음매 — 구현 교체 지점.

    v1은 `RuleBasedPolicyV1`(if/else)이다. 이후 BKT 사후확률·DKT 은닉상태·IRT θ·LLM 판정을
    쓰는 구현이 들어와도 이 시그니처는 바뀌지 않는다.
    """

    def decide(self, state: LearningState, evidence: AttemptEvidence) -> PolicyDecision:
        """현재 상태와 증거로 다음 상태·행동을 결정한다.

        구현체는 매치되는 규칙이 없으면 **예외를 낸다**(임의 기본값 반환 금지).
        """
        ...


@dataclass(frozen=True)
class PolicyRule:
    """규칙 1건 — 조건과 결정을 데이터로 묶는다.

    규칙을 dataclass로 두는 이유: `V1_RULES` 시퀀스 자체가 "이 정책이 무엇을 아는가"의
    전량 목록이 되어, 규칙 개수·우선순위·id를 테스트가 직접 셀 수 있다. 조건을 함수 본문의
    `if` 사슬로만 두면 규칙 하나를 지워도 "규칙이 몇 개인가"를 기계가 물을 수 없다.
    """

    rule_id: str
    """규칙 식별자 — `PolicyDecision.rule_id`로 적재돼 사후 감사·작동 비율 집계의 키가 된다."""

    description: str
    """왜 이 규칙이 있는가(한 줄). 규칙을 지우려는 사람이 읽어야 할 문장."""

    matches: Callable[[AttemptEvidence], bool]
    """증거가 이 규칙에 해당하는가. 부수효과 없는 순수 술어여야 한다."""

    decide: Callable[[AttemptEvidence], PolicyDecision]
    """매치됐을 때의 결정."""


# ──────────────────────────────────────────────────────────────────────────
# v1 규칙 — 평가 국면(ASSESSING)에서 응답 1건을 받았을 때
#
# 선언 순서가 곧 우선순위다. 위에서부터 첫 매치가 이긴다.
# ──────────────────────────────────────────────────────────────────────────


def _is_high_confidence(evidence: AttemptEvidence) -> bool:
    """확신도가 "높다"의 판정 — **미측정(None)은 높음이 아니다**.

    `None`을 높음으로 접으면 확신도를 보고하지 않은 모든 정답이 곧바로 진급한다. 반대로
    `None`을 0.0으로 채워도 안 된다(미측정과 "확신 없음"은 다른 사실). 그래서 여기서만
    `is not None`을 명시적으로 검사하고 나머지 코드는 이 술어를 재사용한다.
    """
    return evidence.confidence is not None and evidence.confidence >= HIGH_CONFIDENCE_THRESHOLD


V1_RULES: Sequence[PolicyRule] = (
    PolicyRule(
        rule_id="R5-repeated-failure",
        description=(
            "반복 실패 — 같은 개념에서 연속 오답이 임계 이상이면 원인 분류보다 설명·힌트가 "
            "앞선다. R3·R4보다 먼저 평가되지 않으면 막힌 학생이 계속 교정만 받는다."
        ),
        matches=lambda e: (
            not e.is_correct and e.consecutive_failures >= REPEATED_FAILURE_THRESHOLD
        ),
        decide=lambda e: PolicyDecision(
            next_state=LearningState.REMEDIATING,
            next_action=NextAction(kind=NextActionKind.OFFER_EXPLANATION_OR_HINT),
            rule_id="R5-repeated-failure",
            trigger=TransitionTrigger.POLICY_REPEATED_FAILURE,
        ),
    ),
    PolicyRule(
        rule_id="R3-wrong-misconception",
        description=(
            "오답 + 오개념 확인 — 확인된 오개념이 있으면 교정이 먼저다. 오개념을 남긴 채 "
            "선수 개념을 다시 가르치면 그 오개념이 그대로 따라온다(R4보다 앞서는 이유)."
        ),
        matches=lambda e: not e.is_correct and bool(e.confirmed_misconception_ids),
        decide=lambda e: PolicyDecision(
            next_state=LearningState.REMEDIATING,
            next_action=NextAction(
                kind=NextActionKind.REMEDIATE_MISCONCEPTION,
                target_misconception_id=e.confirmed_misconception_ids[0],
            ),
            rule_id="R3-wrong-misconception",
            trigger=TransitionTrigger.POLICY_REMEDIATE_MISCONCEPTION,
        ),
    ),
    PolicyRule(
        rule_id="R4-prerequisite-gap",
        description=(
            "오답 + 선수 개념 결손 — 현재 개념을 더 연습해도 소용없다. 결손 선수 개념의 "
            "학습(LEARNING)으로 되돌아간다."
        ),
        matches=lambda e: not e.is_correct and bool(e.prerequisite_gap_concept_ids),
        decide=lambda e: PolicyDecision(
            next_state=LearningState.LEARNING,
            next_action=NextAction(
                kind=NextActionKind.GO_TO_PREREQUISITE_CONCEPT,
                target_concept_id=e.prerequisite_gap_concept_ids[0],
            ),
            rule_id="R4-prerequisite-gap",
            trigger=TransitionTrigger.POLICY_PREREQUISITE_GAP,
        ),
    ),
    PolicyRule(
        rule_id="R1-correct-high-confidence",
        description="정답 + 높은 확신 — 숙달로 보고 다음 개념으로 진급한다.",
        matches=lambda e: e.is_correct and _is_high_confidence(e),
        decide=lambda e: PolicyDecision(
            next_state=LearningState.ADVANCING,
            next_action=NextAction(kind=NextActionKind.ADVANCE_TO_NEXT_CONCEPT),
            rule_id="R1-correct-high-confidence",
            trigger=TransitionTrigger.POLICY_ADVANCE,
        ),
    ),
    PolicyRule(
        rule_id="R2-correct-low-confidence",
        description=(
            "정답 + 낮은(또는 미측정) 확신 — 맞혔지만 스스로 확신하지 못한다. 진급이 아니라 "
            "같은 개념 연습으로 확신을 쌓는다(메타인지 축 — 정답률만으로 진급시키지 않는다)."
        ),
        matches=lambda e: e.is_correct and not _is_high_confidence(e),
        decide=lambda e: PolicyDecision(
            next_state=LearningState.PRACTICING,
            next_action=NextAction(kind=NextActionKind.PRACTICE_SAME_CONCEPT),
            rule_id="R2-correct-low-confidence",
            trigger=TransitionTrigger.POLICY_PRACTICE_LOW_CONFIDENCE,
        ),
    ),
    PolicyRule(
        rule_id="R6-wrong-undiagnosed",
        description=(
            "오답이나 원인(반복·오개념·선수결손)이 하나도 확인되지 않음 — 추측으로 교정하지 "
            "않고 같은 개념 연습을 이어 간다. 이 규칙이 없으면 원인 미상 오답이 규칙 구멍으로 "
            "떨어져 예외가 된다(그것이 의도한 변별력이다 — 테스트 참조)."
        ),
        matches=lambda e: not e.is_correct,
        decide=lambda e: PolicyDecision(
            next_state=LearningState.PRACTICING,
            next_action=NextAction(kind=NextActionKind.PRACTICE_SAME_CONCEPT),
            rule_id="R6-wrong-undiagnosed",
            trigger=TransitionTrigger.POLICY_PRACTICE_UNDIAGNOSED,
        ),
    ),
)


class RuleBasedPolicyV1:
    """v1 규칙 기반 정책 — `LearningStatePolicy` Protocol의 첫 구현.

    상태는 갖지 않는다(순수 함수의 묶음). DB에 접근하지 않으므로 단위 테스트에 세션이 필요
    없고, 규칙 하나를 지우면 정확히 그 규칙의 픽스처만 RED가 된다.
    """

    def __init__(self, rules: Sequence[PolicyRule] = V1_RULES) -> None:
        """규칙 집합 주입 — 기본값은 `V1_RULES`.

        주입 가능하게 둔 이유는 확장이 아니라 **검증**이다: 뮤테이션 테스트가 규칙을 하나씩
        뺀 집합을 넣어 "그 규칙이 없으면 통과해 버리는 입력"을 실제로 확인한다
        (CLAUDE.md 픽스처 접촉 규칙 — 규칙 하나당 반례 하나).
        """
        self._rules = tuple(rules)

    @property
    def rules(self) -> tuple[PolicyRule, ...]:
        """이 정책이 아는 규칙 전량 — 우선순위 순."""
        return self._rules

    def decide(self, state: LearningState, evidence: AttemptEvidence) -> PolicyDecision:
        """첫 매치 규칙의 결정을 낸다. 매치 없으면 `NoMatchingPolicyRuleError`.

        `state`는 v1에서 결정에 쓰이지 않는다 — 규칙이 전부 평가 국면(ASSESSING) 응답을
        전제하기 때문이다. 그럼에도 시그니처에 남긴 것은 계약이 상태 의존 정책(예: 진단
        국면의 오답을 실패로 세지 않는 규칙)으로 교체돼도 호출부가 그대로이게 하기 위해서다.
        전이의 합법성은 이 함수가 아니라 전이표가 판정한다.
        """
        for rule in self._rules:
            if rule.matches(evidence):
                return rule.decide(evidence)
        raise NoMatchingPolicyRuleError(state, evidence)


def default_policy() -> LearningStatePolicy:
    """기본 정책 구현 선택이 사는 **한 곳**.

    호출부가 `RuleBasedPolicyV1()`을 직접 짓지 않고 이 함수를 쓰면, 정책 교체 시 고칠 곳이
    여기 한 줄이다(합성 루트 패턴의 축소판).
    """
    return RuleBasedPolicyV1()
