"""L2 — 보정(Remediation) 정책 테이블: 오개념 교정 신뢰 하한 + 반복 오류 개입 사다리 (MISC-30).

설계 정본: 계획서 300 §9 = 실행 프롬프트 카탈로그
`docs/ops/phase2_eos_closed_loop_execution_prompts.md` §P-09.

**경로 표는 여기 없다 — EOS-138 ③ 판정 요지 (3줄)**
  1. 오답 직후 "무엇을 먼저 보정하나"의 정본은 상태 머신 하나다(`l2/learning_state_policy.V1_RULES`
     — R5 반복 실패 > R3 오개념. 선수 결손 규칙 R4는 EOS-127에서 삭제됐다).
  2. 이 모듈에 있던 두 번째 순서 선언(`select_route` · RT1 선수 > RT2 오개념)은 소비처 0건이었고
     순서가 반대였다 — 정렬하지 않고 **삭제**했다(진실 원천 둘 = 유지보수 지옥).
  3. R4가 R3를 이기는 예외(R4a: 측정된 선수 결손 ∧ 교정 저항)는 R4와 함께 소멸했다(EOS-127 —
     R4를 삭제하는 처분이라 예외도 넣지 않는다). 선수 하강은 다음 문항 선택이 맡는다.
  판정문: `docs/reviews/eos138_r3_input_scope_and_route_order_judgment_2026-09-28.md`.
  재등장 방지: `tests/backend/l2/test_remediation_policy.py::TestNoRouteVocabulary`.

**이 모듈이 존재하는 이유(한 줄)**: "오개념 교정으로 보낼 만큼 확신하나"(하한)와 "얼마나 세게
개입할 것인가"(강도)를 결정하는 임계값이 코드 여러 곳에 흩어지지 않고 **읽을 수 있는 표 하나**로
모이게 한다. 이 값들은 나중에 실측으로 조정될 값이지 영구 상수가 아니다.

────────────────────────────────────────────────────────────────────────────
"same error"의 정의 — 셋 중 하나를 고른다 (§P-09 항목 4)
────────────────────────────────────────────────────────────────────────────
계획서는 사다리를 `same error >= 2/3/4`로 적었을 뿐 "같은 오류"가 무엇인지 고르지 않았다.
고르지 않으면 구현마다 달라지므로 여기서 **한 번** 고른다.

| 후보 | 무엇을 세는가 | 채택? |
|---|---|---|
| 같은 **문제** | 동일 `problem_id` 재시도 횟수 | ✗ |
| 같은 **error signature** | 동일 오답 표면형(`l4/misconception/answer_signature.py`) | ✗ |
| 같은 **오개념 가설** | 한 `misconception_id` 가설을 지지한 누적 증거 수 | ✓ **채택** |

채택 근거 셋:

1. **교육적으로 세고 싶은 것이 그것이다.** 같은 문제를 두 번 틀리는 일은 드물고(보통 다음
   문항으로 넘어간다), 서로 다른 문항에서 *같은 이유로* 막히는 것이 개입 강도를 올려야 할
   상태다. 문제 단위로 세면 사다리가 사실상 발동하지 않는다.
2. **표면형은 같은 오류를 여러 개로 쪼갠다.** `answer_signature`는 숫자가 다르면 다른
   서명이다 — 같은 오개념이 다른 문항에서 나오면 각각 1회로 세어져 영영 2에 닿지 않는다.
   서명은 *매칭의 입력*이고, 그 서명들을 한 원인으로 모은 결과가 오개념 가설이다.
3. **낙인 방지 장치가 이미 붙어 있다.** `l4/misconception/hypothesis.py`의 가설은 증거가
   끊기면 감쇠(`decay`)하고 임계 미만이면 가지치기된다. 즉 이 카운트는 "한 번 의심되면
   영원히 올라가는 값"이 아니라 최근 증거가 유지될 때만 쌓이는 값이다. 사다리를 여기에
   얹으면 강도 상승도 자동으로 되돌아온다(CLAUDE.md 교수학 금기 — 정서적 낙인 금지).

**구현상의 의미**: 이 모듈은 `MisconceptionHypothesis.evidence_count`를 **읽기만** 한다.
새 카운터를 만들지 않는다(MISC-30 acceptance ② — 신호 원천은 이미 있다). 다만 L2는 L4를
import할 수 없으므로(7계층 역방향 금지) 이 모듈의 입력은 정수 하나(`same_error_count`)이고,
그 값을 어디서 읽어 올지는 호출부(L4)가 정한다.

────────────────────────────────────────────────────────────────────────────
임계 소유권 — 어느 값이 어디의 정본인가 (MISC-30 acceptance ④)
────────────────────────────────────────────────────────────────────────────
착수 노트는 임계가 3모듈에 분산돼 있다고 적었다. 실측하니 **넷은 서로 다른 질문에 답한다** —
값이 비슷하다고 합치면 한쪽을 고칠 때 다른 쪽이 조용히 따라 움직인다.

| 값 | 위치 | 묻는 질문 | 본 표에서 |
|---|---|---|---|
| 0.4 / 0.7 | `l2/recommendation_contract.py` | 숙달이 어느 구간인가 | 무관(추천의 숙달 구간 판정) |
| 0.65 | `l4/misconception/match_gate.py` | 이 매칭을 후보로 인정할까 | 무관(매칭 품질) |
| 0.8 / 0.5 | `l4/misconception/intervene.py` | 어느 *발화 패턴*을 쓸까 | 무관(패턴 선택) |
| 0.7 | **여기** | 오개념 교정으로 보낼 만큼 확신하나 | **정본** |
| 3회 | `schema/learning_state.py` | 연속 오답이 몇 번이면 설명·힌트인가 | 무관(아래 참조) |
| 2·3·4회 | **여기** | 같은 오류가 몇 번이면 강도를 올리나 | **정본** |

숙달 0.4/0.7은 종전에 이 표가 **미러**로 옮겨 적었으나, 그 미러는 경로 판정(`select_route`)만을
위해 있었으므로 경로 표와 함께 삭제했다(EOS-138 ③ — 미러가 남으면 소비처 없는 두 번째 사본이 된다).

**`REPEATED_FAILURE_THRESHOLD`(3회)와 이 사다리는 다른 축이다.** 그쪽은 *원인과 무관한
연속 오답* 수이고(`AttemptEvidence.consecutive_failures`), 이쪽은 *같은 오개념*의 누적 증거
수다. 한 학생이 서로 다른 이유로 3연속 틀릴 수 있고(그쪽만 발동), 세 번의 오답 사이에 정답이
끼어도 같은 오개념이 3회 쌓일 수 있다(이쪽만 발동). 숫자가 겹친다고 합치지 않는다.

**과목 중립**: 하한·사다리 어디에도 수학 어휘가 없다(`if subject == "math"` 0건).
`l2`는 import-linter의 "EOS Core → Math Adapter 금지(baseline 0)" 구역이므로 이 중립성은
산문이 아니라 CI가 잰다.

────────────────────────────────────────────────────────────────────────────
지금 배선된 것 (정직 표기)
────────────────────────────────────────────────────────────────────────────
**사다리**(`select_rung`)는 `l4/misconception/intervene.py::select_intervention_from_hypotheses`가
focus 가설의 `evidence_count`로 호출하고, 결과 등급이 `InterventionDecision.escalation_rung`에 실려
`harness/wh1_loop.py`의 `TurnOutcome`까지 올라온다(작동 비율의 원자료 — MISC-30 acceptance ⑥).

**하한**(`MISCONCEPTION_REMEDIATION_FLOOR`)은 상태 머신 R3의 입력 필터
(`l2/learning_state_evidence.py`)와 추천의 집행 안전장치(`l2/learning_state_recommendation.py`)가
읽는다 — 둘 다 **초과** 방향이다.

**LLM은 이 표에서 결정하지 않는다.** LLM은 오개념 후보를 *제안*하는 쪽(L4)에만 관여하고, 하한·
사다리 판정은 이 표가 가진다(마스터 프리앰블 설계 규율).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

__all__ = [
    "MISCONCEPTION_REMEDIATION_FLOOR",
    "REMEDIATION_POLICY_V1",
    "EscalationRung",
    "RemediationPolicyTable",
    "select_rung",
]

#: 오개념 교정으로 보낼 신뢰 하한 — 이 값을 **초과**해야 교정으로 간다(계획서 §9).
#: 소비처 2곳: 상태 머신 R3의 입력 필터(`l2/learning_state_evidence.py` · EOS-138 ②)와 추천의
#: 집행 안전장치 ②(`l2/learning_state_recommendation.py` · EOS-24). 두 곳 모두 "초과" 방향이다.
#: `match_gate`의 0.65(후보 인정)·`intervene`의 0.8/0.5(발화 패턴 선택)와 **다른 질문**이다 —
#: 모듈 docstring의 소유권 표 참조. 값이 가까운 것은 우연이고 합치지 않는다.
MISCONCEPTION_REMEDIATION_FLOOR: Final = 0.7


class EscalationRung(str, Enum):
    """**얼마나 세게 개입할 것인가** — 같은 오류가 쌓일수록 올라가는 사다리(계획서 §9).

    강도는 *콘텐츠 난이도·스캐폴드 밀도*로 표현된다. 실패 횟수 자체는 학생에게 숫자로
    노출하지 않는다 — "너는 계속 틀린다"로 읽히면 안 된다(CLAUDE.md 교수학 금기:
    부정적 피드백의 정서적 강화 금지). 이 값은 텔레메트리와 콘텐츠 라우팅용이다.
    """

    NONE = "none"
    """반복 신호가 사다리 첫 칸에 못 미친다 — 강도를 올리지 않는다(측정했고 미발동)."""

    CORRECTIVE_EXPLANATION = "corrective_explanation"
    """2회 이상 — 스캐폴드를 한 단계 더 준다(교정 설명)."""

    EASIER_PROBLEM = "easier_problem"
    """3회 이상 — 같은 개념의 더 쉬운 문항으로 내린다."""

    PREREQUISITE_CONCEPT = "prerequisite_concept"
    """4회 이상 — 현재 개념을 붙잡고 있는 것을 멈추고 선수 개념으로 되돌아간다.

    이 등급은 반복 오류 사다리의 강도 표기이지 경로 순서가 아니다. 선수 쪽 하강은 상태 머신
    전이가 아니라 다음 문항 선택(R6 선수 탐침 · `l2/learning_state_recommendation`)이 소유한다
    (EOS-127 — 종전에 이 자리를 가리키던 R4는 삭제됐다).
    """


@dataclass(frozen=True, slots=True)
class RemediationPolicyTable:
    """보정 정책의 **임계값 전량** — 나중에 실측으로 조정될 값들이 사는 한 곳.

    dataclass로 두는 이유는 `learning_state_policy.V1_RULES`와 같다: 인스턴스 하나가 "이 정책이
    아는 임계가 무엇인가"의 전량 목록이 되어 테스트가 직접 셀 수 있다. 값을 함수 본문의
    리터럴로 두면 임계 하나를 옮겨도 "임계가 몇 개인가"를 기계가 물을 수 없다.

    주입 가능하게 둔 것은 확장이 아니라 **검증**을 위해서다 — 경계 이동 뮤테이션 테스트가
    한 칸 옮긴 표를 넣어 픽스처가 그 경계를 실제로 밟는지 확인한다(CLAUDE.md 픽스처 접촉 규칙).
    """

    misconception_remediation_floor: float = MISCONCEPTION_REMEDIATION_FLOOR
    """오개념 교정의 신뢰 하한 — **이 표가 정본**(초과라야 교정).

    소비처 2곳(R3 입력 필터·추천 안전장치 ②)은 모듈 상수 `MISCONCEPTION_REMEDIATION_FLOOR`를
    직접 읽는다. 이 필드는 그 상수를 기본값으로 가질 뿐 별도 값이 아니다(같은 객체).
    """

    escalation_ladder: tuple[tuple[int, EscalationRung], ...] = (
        (4, EscalationRung.PREREQUISITE_CONCEPT),
        (3, EscalationRung.EASIER_PROBLEM),
        (2, EscalationRung.CORRECTIVE_EXPLANATION),
    )
    """반복 오류 사다리 — `(최소 횟수, 등급)`을 **횟수 내림차순**으로. 첫 매치가 이긴다.

    내림차순인 것이 계약이다(오름차순이면 4회 학생이 2회 칸에 걸린다). `__post_init__`이
    그 순서를 검사해 위반을 **거부**한다 — 조용히 정렬해 주면 잘못된 표가 정상처럼 돈다.
    """

    def __post_init__(self) -> None:
        """표 자체의 불변식 — 깨진 표를 조용히 고쳐 주지 않고 거부한다."""
        if not self.escalation_ladder:
            raise ValueError(
                "escalation_ladder가 비어 있습니다 — 빈 사다리는 모든 반복을 NONE으로 "
                "접어 사다리가 없는 것과 구별되지 않습니다."
            )
        counts = [count for count, _ in self.escalation_ladder]
        if counts != sorted(counts, reverse=True):
            raise ValueError(
                f"escalation_ladder는 횟수 내림차순이어야 합니다(받은 순서: {counts}). "
                "오름차순이면 첫 매치 규칙 때문에 높은 반복이 낮은 등급에 걸립니다."
            )
        if len(set(counts)) != len(counts):
            raise ValueError(f"escalation_ladder에 중복 횟수가 있습니다: {counts}.")
        if counts[-1] < 1:
            raise ValueError(
                f"escalation_ladder의 최소 횟수는 1 이상이어야 합니다(받은 값: {counts[-1]}). "
                "0이면 반복이 없는 학생도 개입 강도가 올라갑니다."
            )


#: v1 정책 표 — **이 인스턴스가 "한 곳"이다**. 호출부는 자기 리터럴을 쓰지 않고 이것을 읽는다.
REMEDIATION_POLICY_V1: Final = RemediationPolicyTable()


def select_rung(
    same_error_count: int,
    policy: RemediationPolicyTable = REMEDIATION_POLICY_V1,
) -> EscalationRung:
    """같은 오류 누적 횟수 → 개입 강도 등급 — 순수·결정론.

    표의 사다리를 **위(높은 횟수)에서부터** 훑어 첫 매치를 돌린다. 어느 칸에도 못 미치면
    `NONE`(측정했고 미발동)이며, 이는 "반복 신호를 아예 모른다"와 구별된다 — 후자는 호출부가
    `escalation_rung=None`으로 표현한다.
    """
    if same_error_count < 0:
        raise ValueError(f"same_error_count는 0 이상이어야 합니다(받은 값: {same_error_count}).")
    for minimum, rung in policy.escalation_ladder:
        if same_error_count >= minimum:
            return rung
    return EscalationRung.NONE
