"""오개념 후보 → 교정 전략 조회 (P3-06) — 사다리 칸에 맞는 교정 내용을 표에서 꺼낸다.

흐름의 마지막 이음새다:

    학생 답안 → 오류 서명 → 오개념 후보(kebab, confidence) → **여기** → 교정 전략

`l2/remediation_policy.select_rung`이 "얼마나 세게"(같은 오류 누적 횟수 → 사다리 칸)를 정하고, 이
모듈은 "그 칸에서 무엇을 내놓나"를 `misconception_remediation_v1` 표에서 읽는다. 사다리 임계값은
여기서 다시 적지 않는다 — 호출자가 `select_rung`을 부르고 그 결과를 넘기거나, 횟수를 넘기면 이
모듈이 **같은 함수**를 부른다(임계 사본 0).

과목 중립
────────────────────────────────────────────────────────────────────────────
이 모듈에는 수학 어휘가 없다. kebab id와 사다리 칸을 받아 표의 행을 돌려줄 뿐이다. 수학을 아는
것은 표의 내용(데이터)과 후보를 만든 어댑터(`answer_signature`·`derivative_signature`)다.

정직한 3상태
────────────────────────────────────────────────────────────────────────────
조회 결과는 세 가지이고 서로 다른 글자로 구별한다 — 하나로 뭉치면 "교정할 것이 없다"와 "교정표에
이 오개념이 없다"가 같은 빈 값이 된다:
  · `ADVICE`        — 칸이 올라갔고 표에 행이 있다. 내용을 낸다.
  · `NO_ESCALATION` — 반복이 사다리 첫 칸에 못 미친다(`EscalationRung.NONE`). 강도를 올리지 않는다.
  · `NO_STRATEGY`   — 칸은 올라갔는데 교정표에 이 오개념의 행이 없다. **공백이 드러난다**.

저작 상태(`authoring_status`)를 그대로 싣는다. 이 모듈은 draft 행을 걸러 내지 않는다 — 학생에게
내보낼지는 소비 경로가 정할 일이고, 그 정책 없이 여기서 조용히 걸러 내면 "표는 있는데 안 나온다"는
침묵 실패가 된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from whymath_backend.l1.misconception.wrong_answer_tables import (
    canonical_mis_id_for_kebab,
    mis_ids_for_kebab,
    remediation_row_for_mis_id,
)
from whymath_backend.l2.remediation_policy import (
    REMEDIATION_POLICY_V1,
    EscalationRung,
    RemediationPolicyTable,
    select_rung,
)
from whymath_backend.schema.wrong_answer_remediation import (
    AuthoringStatus,
    CorrectiveExplanation,
    EasierProblemSelector,
    PrerequisiteSelector,
    RemediationRow,
)

__all__ = [
    "RUNG_CONTENT_FIELD",
    "AdviceOutcome",
    "RemediationAdvice",
    "advise",
    "advise_for_rung",
    "resolve_row",
]

#: 사다리 칸 → 교정표 행의 필드. 칸이 늘면(`EscalationRung`) 이 표와 데이터가 함께 늘어야 하며,
#: 어긋남은 `tests/backend/l4/misconception/test_remediation_advice.py`가 막는다.
RUNG_CONTENT_FIELD: dict[EscalationRung, str] = {
    EscalationRung.CORRECTIVE_EXPLANATION: "corrective_explanation",
    EscalationRung.EASIER_PROBLEM: "easier_problem",
    EscalationRung.PREREQUISITE_CONCEPT: "prerequisite_concept",
}


class AdviceOutcome(str, Enum):
    """조회 결과 3상태 — 서로 다른 글자로 구별한다."""

    ADVICE = "advice"
    NO_ESCALATION = "no_escalation"
    NO_STRATEGY = "no_strategy"


@dataclass(frozen=True, slots=True)
class RemediationAdvice:
    """한 후보 + 한 사다리 칸의 교정 전략 — 칸에 해당하는 내용 하나만 채워진다."""

    outcome: AdviceOutcome
    kebab_id: str
    rung: EscalationRung
    mis_id: str | None = None
    corrective_explanation: CorrectiveExplanation | None = None
    easier_problem: EasierProblemSelector | None = None
    prerequisite_concept: PrerequisiteSelector | None = None
    authoring_status: AuthoringStatus | None = None


def resolve_row(kebab_id: str) -> RemediationRow | None:
    """kebab의 교정표 행 — canonical M-id의 행을 먼저, 없으면 그 kebab에 걸린 다른 M-id의 행.

    canonical 선정은 크로스워크의 기존 정책(`select_canonical`)이다. canonical이 없으면(동률·직접
    매핑 부재) 임의로 고르지 않고 **정렬된 첫 번째 행 있는 M-id**를 결정론적으로 쓴다 — 동률인
    오개념들의 교정이 같은 kebab을 가리키는 이유는 같은 오류의 다른 표현이기 때문이다.
    """
    canonical = canonical_mis_id_for_kebab(kebab_id)
    if canonical is not None:
        row = remediation_row_for_mis_id(canonical)
        if row is not None:
            return row
    for mis_id in mis_ids_for_kebab(kebab_id):
        row = remediation_row_for_mis_id(mis_id)
        if row is not None:
            return row
    return None


def advise_for_rung(kebab_id: str, rung: EscalationRung) -> RemediationAdvice:
    """사다리 칸이 이미 정해졌을 때의 조회 — 호출자가 `select_rung` 결과를 넘긴다."""
    if rung is EscalationRung.NONE:
        return RemediationAdvice(outcome=AdviceOutcome.NO_ESCALATION, kebab_id=kebab_id, rung=rung)
    row = resolve_row(kebab_id)
    if row is None:
        return RemediationAdvice(outcome=AdviceOutcome.NO_STRATEGY, kebab_id=kebab_id, rung=rung)
    field = RUNG_CONTENT_FIELD[rung]
    return RemediationAdvice(
        outcome=AdviceOutcome.ADVICE,
        kebab_id=kebab_id,
        rung=rung,
        mis_id=row.mis_id,
        authoring_status=row.authoring_status,
        corrective_explanation=(
            row.corrective_explanation if field == "corrective_explanation" else None
        ),
        easier_problem=row.easier_problem if field == "easier_problem" else None,
        prerequisite_concept=row.prerequisite_concept if field == "prerequisite_concept" else None,
    )


def advise(
    kebab_id: str,
    same_error_count: int,
    policy: RemediationPolicyTable = REMEDIATION_POLICY_V1,
) -> RemediationAdvice:
    """같은 오류 누적 횟수로 사다리 칸을 정하고(`select_rung` — 임계 사본 0) 그 칸의 교정을 낸다."""
    return advise_for_rung(kebab_id, select_rung(same_error_count, policy))
