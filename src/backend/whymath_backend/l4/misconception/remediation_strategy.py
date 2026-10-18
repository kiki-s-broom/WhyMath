"""오답 1건 → 오류 서명 → 오개념 후보·신뢰도 → 교정 전략 — Phase 2 부품의 **조립** (P3-06).

새 탐지기가 아니다. 이 모듈은 이미 있는 부품을 채점 경로와 **같은 순서·같은 규칙**으로 부를 뿐이다:

    선택한 보기 ─ ① 서명 ─ ② 후보 ─ ③ 가설(누적·감쇠) ─ ④ 개입 ─ ⑤ P-09 등급 ─ ⑥ 교정 행동

    ① distractor_map          ④ intervene
    ② distractor_link         ⑤ remediation_policy
    ③ attempt_hypothesis_policy + hypothesis.update_hypotheses      ⑥ + 교수 전략(select)

각 단계의 정본(여기서 재구현하지 않는다):
  ② `distractor_link.distractor_link_matches` — 카탈로그 실재 + 품질 게이트(floor 0.65) 통과분만.
  ③ `attempt_hypothesis_policy` 6칸 표 + `hypothesis.update_hypotheses` — 오답은 강화, 정답은 1턴
     감쇠, 충돌은 보류. 신뢰도 누적·감쇠 규칙은 Phase 2 것 그대로다(바꾸지 않았다).
  ④ `intervene.select_intervention_from_hypotheses` — 신뢰도 >0.8 반례 유도, 0.5~0.8 거꾸로 사고.
  ⑤ `l2.remediation_policy` — 교정 신뢰 하한(0.7 초과)·반복 오류 사다리(2/3/4회).
  ⑥ 교수 전략은 `l4.pedagogy.runtime_selector.select` 를 **그대로 호출**한 결과다. 오개념↔교수 전략
     간선을 여기서 새로 만들지 않는다(어휘 불일치 판정은 P3-23 소유 — 만들면 그 판정을 선점한다).

**LLM 은 여기서 아무것도 결정하지 않는다.** 순수 함수·DB 없음·학생 원문 없음(보기 인덱스와 id 뿐).
**수학 어휘 없음** — 과목 중립이라 EOS Core 의 과목 분기 금지를 어기지 않는다. 과목 특화는
주입되는 데이터(문항의 distractor_map)와 해소기에 있다.

정직 표기 (작동한 비율 원칙):
  · 서명이 있었는데 후보가 비면 **왜 비었는지**를 `dropped_reason` 으로 남긴다 — 카탈로그에 없는 id
    (`unknown_misconception`)와 품질 게이트 미달(`below_floor`)은 처분이 다르다. 오답 보기 12건이
    raw M-id(`M0674`)를 달고 있어 런타임이 조용히 버리는 실측이 이 필드의 존재 이유다.
  · 쉬운 문항·선수 개념을 해소기가 못 찾으면 `resolved=False` 다. 있는 척 채우지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.l2.recommendation_contract import (
    ReasonType,
    RecommendationAction,
    action_for,
)
from whymath_backend.l2.remediation_policy import (
    MISCONCEPTION_REMEDIATION_FLOOR,
    EscalationRung,
)
from whymath_backend.l4.misconception.attempt_hypothesis_policy import (
    AttemptHypothesisAction,
    decide_attempt_hypothesis_action,
)
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.distractor_link import (
    distractor_link_matches,
    resolve_misconception_from_choice,
)
from whymath_backend.l4.misconception.hypothesis import (
    MisconceptionHypothesis,
    update_hypotheses,
)
from whymath_backend.l4.misconception.intervene import select_intervention_from_hypotheses
from whymath_backend.l4.misconception.models import InterventionPattern
from whymath_backend.l4.pedagogy.runtime_selector import StudentSignals, select
from whymath_backend.schema.assessment_evidence import MisconceptionScan

__all__ = [
    "ChainResult",
    "ChoiceErrorSignature",
    "RemediationStrategy",
    "RungAction",
    "RungResolvers",
    "run_choice_chain",
]

DroppedReason = Literal["unknown_misconception", "below_floor"]


class RungResolvers(Protocol):
    """사다리 등급이 가리키는 **실제 대상**을 코퍼스에서 찾는 주입 좌석.

    L4 는 코퍼스 로더를 알지 못한다 — 호출부(ops·테스트)가 구현을 넣는다. 못 찾으면 빈 시퀀스를
    돌려주면 되고, 이 모듈은 그것을 `resolved=False` 로 정직하게 옮긴다.
    """

    def easier_problem_ids(self, problem_id: str, misconception_id: str) -> Sequence[str]:
        """틀린 문항과 같은 개념의 **더 쉬운** 승인 문항 id (같은 오개념을 겨냥한 것 우선)."""
        ...

    def prerequisite_atoms(self, problem_id: str) -> Sequence[str]:
        """틀린 문항의 개념으로 들어오는 선수 간선의 시작 원자 코드(깊이 1·상한은 해소기 몫)."""
        ...


class ChoiceErrorSignature(BaseModel):
    """객관식 채널의 오류 서명 — 어떤 문항에서 어떤 보기를 골랐고, 그 보기가 무엇이라 적혀 있는가.

    화면 문자열이 아니라 구조다(보기 본문·학생 원문 없음). `op_code` 는 문항 항목에 적혀 있을 때만
    채운다 — 없으면 None 이고, 그것이 사실이다(4개 kebab 은 op-code 가 어디에도 없다).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    problem_id: str
    choice_index: int = Field(ge=0)
    misconception_id: str
    op_code: str | None = None


class RungAction(BaseModel):
    """사다리 등급 → 학생에게 갈 **구체적 교정 행동**. `targets` 는 코퍼스에 실재하는 id 다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rung: EscalationRung
    targets: tuple[str, ...] = Field(
        default=(),
        description="EASIER_PROBLEM=문항 id · PREREQUISITE_CONCEPT=원자 코드 · 그 외 빈 튜플.",
    )
    anchor: str = Field(
        default="",
        description="CORRECTIVE_EXPLANATION 의 근거 — 카탈로그 반례 문장. 다른 등급은 빈 문자열.",
    )
    resolved: bool = Field(
        description="이 등급이 가리키는 대상이 실제로 있는가. 없으면 False — 채우지 않는다.",
    )


class RemediationStrategy(BaseModel):
    """오개념 가설 하나에 대한 교정 전략 — P-09 정책 표와 교수 전략에 연결된 결과."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    misconception_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_count: int = Field(ge=1)
    remediation_eligible: bool = Field(
        description=f"신뢰도가 교정 하한({MISCONCEPTION_REMEDIATION_FLOOR})을 초과하는가(P-09).",
    )
    reason_type: ReasonType | None
    action: RecommendationAction | None
    intervention_pattern: InterventionPattern
    escalation_rung: EscalationRung
    rung_action: RungAction
    pedagogy_strategy: str = Field(
        description="`runtime_selector.select` 결과 — 간선을 새로 만들지 않고 선택기를 호출한다.",
    )


class ChainResult(BaseModel):
    """시도 1건이 체인을 통과한 전 과정 — 어느 단계에서 끊겼는지가 필드로 보인다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scan: MisconceptionScan
    hypothesis_action: AttemptHypothesisAction
    signature: ChoiceErrorSignature | None
    dropped_reason: DroppedReason | None = Field(
        default=None,
        description="서명이 있었는데 후보가 비었을 때의 사유. 서명이 없으면 None.",
    )
    candidate_ids: tuple[str, ...] = ()
    candidate_confidence: float | None = None
    hypotheses: tuple[MisconceptionHypothesis, ...] = ()
    strategy: RemediationStrategy | None = None


def _signature(
    problem_id: str,
    distractor_map: Sequence[Mapping[str, Any]] | None,
    selected_choice_index: int | None,
) -> ChoiceErrorSignature | None:
    """선택한 보기의 distractor_map 항목 → 서명. 항목이 없으면(정답·미매핑) None."""
    misconception_id = resolve_misconception_from_choice(distractor_map, selected_choice_index)
    if misconception_id is None or selected_choice_index is None or not distractor_map:
        return None
    op_code: str | None = None
    for entry in distractor_map:
        if isinstance(entry, Mapping) and entry.get("choice_index") == selected_choice_index:
            raw = entry.get("op_code")
            op_code = raw if isinstance(raw, str) and raw else None
            break
    return ChoiceErrorSignature(
        problem_id=problem_id,
        choice_index=selected_choice_index,
        misconception_id=misconception_id,
        op_code=op_code,
    )


def _rung_action(
    rung: EscalationRung,
    *,
    problem_id: str,
    misconception_id: str,
    resolvers: RungResolvers | None,
) -> RungAction:
    if rung is EscalationRung.NONE:
        return RungAction(rung=rung, resolved=True)
    if rung is EscalationRung.CORRECTIVE_EXPLANATION:
        misconception = CATALOG_BY_ID.get(misconception_id)
        anchor = misconception.counterexample if misconception is not None else ""
        return RungAction(rung=rung, anchor=anchor, resolved=bool(anchor))
    if resolvers is None:
        return RungAction(rung=rung, resolved=False)
    if rung is EscalationRung.EASIER_PROBLEM:
        easier = tuple(resolvers.easier_problem_ids(problem_id, misconception_id))
        return RungAction(rung=rung, targets=easier, resolved=bool(easier))
    atoms = tuple(resolvers.prerequisite_atoms(problem_id))
    return RungAction(rung=rung, targets=atoms, resolved=bool(atoms))


def run_choice_chain(
    *,
    problem_id: str,
    distractor_map: Sequence[Mapping[str, Any]] | None,
    selected_choice_index: int | None,
    is_correct: bool,
    prior: Sequence[MisconceptionHypothesis] = (),
    resolvers: RungResolvers | None = None,
    turns_elapsed: int = 1,
) -> ChainResult:
    """객관식 한 번의 선택을 체인에 통과시킨다 — 순수·결정론(rng 없음).

    `is_correct` 는 호출자가 안다(보기 인덱스가 정답 인덱스인가) — 이 함수가 정오를 판정하지 않는다.
    학습 상태의 최종 변경은 Assessment/Mastery/Policy 몫이므로, 여기서 만든 가설 세트는 **시뮬레이션
    결과를 돌려줄 뿐 저장하지 않는다**.
    """
    # 선지 채널이 돌 재료가 없으면(매핑 없음·인덱스 미보고) 훑지 않은 것이다 — 후보 0건이 아니다.
    if not distractor_map or selected_choice_index is None:
        return ChainResult(
            scan=MisconceptionScan.NOT_RUN,
            hypothesis_action=decide_attempt_hypothesis_action(
                is_correct=is_correct, scan=MisconceptionScan.NOT_RUN
            ),
            signature=None,
            hypotheses=tuple(prior),
        )

    signature = _signature(problem_id, distractor_map, selected_choice_index)
    matches = distractor_link_matches(distractor_map, selected_choice_index)
    scan = MisconceptionScan.RAN_WITH_CANDIDATES if matches else MisconceptionScan.RAN_NO_CANDIDATE
    action = decide_attempt_hypothesis_action(is_correct=is_correct, scan=scan)

    dropped: DroppedReason | None = None
    if signature is not None and not matches:
        dropped = (
            "unknown_misconception"
            if signature.misconception_id not in CATALOG_BY_ID
            else "below_floor"
        )

    if action is AttemptHypothesisAction.APPLY:
        hypotheses = update_hypotheses(prior, matches, turns_elapsed=turns_elapsed)
    elif action is AttemptHypothesisAction.DECAY_ONLY:
        hypotheses = update_hypotheses(prior, [], turns_elapsed=turns_elapsed)
    else:  # HOLD_CONFLICT · NONE — 가설을 건드리지 않는다.
        hypotheses = list(prior)

    strategy: RemediationStrategy | None = None
    # 교정 전략은 오답 + 후보가 있는 회차에만 만든다(복습 코칭은 APPLY 에서만 — 정책 표의 결론).
    if action is AttemptHypothesisAction.APPLY and matches:
        decision = select_intervention_from_hypotheses(hypotheses, epsilon=0.0)
        focus = hypotheses[0] if hypotheses else None
        if decision is not None and focus is not None and decision.escalation_rung is not None:
            eligible = focus.confidence > MISCONCEPTION_REMEDIATION_FLOOR
            reason = ReasonType.MISCONCEPTION_REMEDIATION if eligible else None
            pedagogy = select(
                StudentSignals(
                    misconception_ids=(focus.misconception_id,), last_attempt_correct=False
                )
            )
            strategy = RemediationStrategy(
                misconception_id=focus.misconception_id,
                confidence=focus.confidence,
                evidence_count=focus.evidence_count,
                remediation_eligible=eligible,
                reason_type=reason,
                action=action_for(reason) if reason is not None else None,
                intervention_pattern=decision.pattern,
                escalation_rung=decision.escalation_rung,
                rung_action=_rung_action(
                    decision.escalation_rung,
                    problem_id=problem_id,
                    misconception_id=focus.misconception_id,
                    resolvers=resolvers,
                ),
                pedagogy_strategy=pedagogy.value,
            )

    return ChainResult(
        scan=scan,
        hypothesis_action=action,
        signature=signature,
        dropped_reason=dropped,
        candidate_ids=tuple(m.misconception.id for m in matches),
        candidate_confidence=matches[0].confidence if matches else None,
        hypotheses=tuple(hypotheses),
        strategy=strategy,
    )
