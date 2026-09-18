"""L2 — 보정(Remediation) 정책 테이블: 경로 선택 + 반복 오류 개입 사다리 (MISC-30).

설계 정본: 계획서 300 §9 = 실행 프롬프트 카탈로그
`docs/ops/phase2_eos_closed_loop_execution_prompts.md` §P-09.

**이 모듈이 존재하는 이유(한 줄)**: "무엇을 보정할 것인가"(경로)와 "얼마나 세게 개입할
것인가"(강도)를 결정하는 임계값이 코드 여러 곳에 흩어지지 않고 **읽을 수 있는 표 하나**로
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
| 0.4 / 0.7 | `l2/recommendation_contract.py` | 숙달이 어느 구간인가 | **미러**(판정 권위는 저쪽) |
| 0.65 | `l4/misconception/match_gate.py` | 이 매칭을 후보로 인정할까 | 무관(매칭 품질) |
| 0.8 / 0.5 | `l4/misconception/intervene.py` | 어느 *발화 패턴*을 쓸까 | 무관(패턴 선택) |
| 0.7 | **여기** | 오개념 교정 *경로*로 보낼 만큼 확신하나 | **정본** |
| 3회 | `schema/learning_state.py` | 연속 오답이 몇 번이면 설명·힌트인가 | 무관(아래 참조) |
| 2·3·4회 | **여기** | 같은 오류가 몇 번이면 강도를 올리나 | **정본** |

**숙달 축은 미러다.** `PREREQUISITE_MASTERY_CEILING`(0.4)·`WEAK_CONCEPT_MASTERY_CEILING`(0.7)은
EOS-14가 세운 상수이고 분기 판정은 `select_reason_type`이 유일 권위다. 이 표는 그 값을
**읽기 좋게 옮겨 적기만** 하고 비교를 재구현하지 않는다 — 재구현하면 같은 질문의 진실 원천이
둘이 된다(구축 플레이북 "유지보수 지옥 ← truth source가 하나가 아님"). 미러가 원본과
어긋나지 않는 것은 `tests/backend/l2/test_remediation_policy.py`가 동결한다.

**`REPEATED_FAILURE_THRESHOLD`(3회)와 이 사다리는 다른 축이다.** 그쪽은 *원인과 무관한
연속 오답* 수이고(`AttemptEvidence.consecutive_failures`), 이쪽은 *같은 오개념*의 누적 증거
수다. 한 학생이 서로 다른 이유로 3연속 틀릴 수 있고(그쪽만 발동), 세 번의 오답 사이에 정답이
끼어도 같은 오개념이 3회 쌓일 수 있다(이쪽만 발동). 숫자가 겹친다고 합치지 않는다.

────────────────────────────────────────────────────────────────────────────
교체 가능성 — v1은 규칙이지만 호출 계약은 그대로다 (마스터 프리앰블 §2)
────────────────────────────────────────────────────────────────────────────
`RemediationPolicy` Protocol은 `RemediationSignals` 하나를 받아 `RemediationDecision` 하나를
낸다. v1 구현은 if 사슬이 아니라 **순서 있는 규칙 튜플**(`V1_ROUTE_RULES`)이고, 내부가
BKT 사후·DKT 은닉상태·bandit으로 바뀌어도 이 시그니처는 바뀌지 않는다. 호출부는 구현체가
아니라 Protocol만 안다.

**LLM은 이 경로에서 결정하지 않는다.** LLM은 `RemediationSignals`를 *채우는* 쪽(오개념 후보
분류)과 결정된 경로를 *설명으로 번역하는* 쪽(L4)에 관여하고, 그 사이의 판단은 이 정책이
가진다(마스터 프리앰블 설계 규율).

**과목 중립**: 경로·사다리·임계 어디에도 수학 어휘가 없다(`if subject == "math"` 0건).
`l2`는 import-linter의 "EOS Core → Math Adapter 금지(baseline 0)" 구역이므로 이 중립성은
산문이 아니라 CI가 잰다.

────────────────────────────────────────────────────────────────────────────
지금 배선된 것과 아닌 것 (정직 표기)
────────────────────────────────────────────────────────────────────────────
**배선됨**: 사다리(`select_rung`)는 `l4/misconception/intervene.py::
select_intervention_from_hypotheses`가 focus 가설의 `evidence_count`로 호출하고, 결과 등급이
`InterventionDecision.escalation_rung`에 실려 `harness/wh1_loop.py`의 `TurnOutcome`까지
올라온다(작동 비율의 원자료 — MISC-30 acceptance ⑥).

**아직 아님**: 경로 선택(`select_route`)의 소비처는 **0건**이다. 숙달 축은 이미
`select_reason_type`이 추천 경로에서 쓰이고 있고(중복 배선 금지), 오개념 축을 경로로 실제
분기시키는 것은 `learning_state_policy`의 R3와 겹치는 구간이라 별도 판단이 필요하다.
그 전환은 이 태스크가 하지 않는다 — 여기서는 표와 판정 함수까지다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.l2.recommendation_contract import (
    PREREQUISITE_MASTERY_CEILING,
    WEAK_CONCEPT_MASTERY_CEILING,
    ReasonType,
    select_reason_type,
)

__all__ = [
    "MISCONCEPTION_REMEDIATION_FLOOR",
    "REMEDIATION_POLICY_V1",
    "V1_ROUTE_RULES",
    "EscalationRung",
    "RemediationDecision",
    "RemediationPolicy",
    "RemediationPolicyTable",
    "RemediationRoute",
    "RemediationSignals",
    "RouteRule",
    "decide_remediation",
    "select_route",
    "select_rung",
]

#: 오개념 교정 *경로*로 보낼 신뢰 하한 — 이 값을 **초과**해야 교정으로 간다(계획서 §9).
#: `match_gate`의 0.65(후보 인정)·`intervene`의 0.8/0.5(발화 패턴 선택)와 **다른 질문**이다 —
#: 모듈 docstring의 소유권 표 참조. 값이 가까운 것은 우연이고 합치지 않는다.
MISCONCEPTION_REMEDIATION_FLOOR: Final = 0.7


class RemediationRoute(str, Enum):
    """**무엇을 보정할 것인가** — 계획서 §9 기본 정책의 네 경로 + 판정 불가 1종."""

    PREREQUISITE_CONCEPT = "prerequisite_concept"
    """숙달이 선수 경계 미만 — 현재 개념을 더 밀어도 막힌다. 선수 개념으로 되돌아간다."""

    MISCONCEPTION_REMEDIATION = "misconception_remediation"
    """오개념 신뢰가 교정 하한 초과 — 연습이 아니라 잘못 알고 있는 것을 먼저 지운다."""

    SAME_CONCEPT_PRACTICE = "same_concept_practice"
    """숙달이 학습 구간 — 같은 개념을 계속 연습한다."""

    NEXT_CONCEPT = "next_concept"
    """숙달이 약점 컷 초과 — 다음 개념으로 넘어갈 수 있다."""

    UNMEASURED = "unmeasured"
    """숙달도 오개념 신뢰도 없다 — 경로를 말할 수 없다.

    네 경로 중 하나로 접지 않는다. 특히 `PREREQUISITE_CONCEPT`으로 접으면 측정된 적 없는
    학생이 전부 "선수가 막혔다"로 분류된다(CLAUDE.md "모른다 ≠ 아니다").
    """


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
    """4회 이상 — 현재 개념을 붙잡고 있는 것을 멈추고 선수 개념으로 되돌아간다."""


class RemediationSignals(BaseModel):
    """정책이 읽는 **신호** — 세 축의 관측치만.

    세 필드 전부 *이미 다른 좌석이 생산하는 값*이다. 이 모듈은 생산자를 만들지 않는다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mastery: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "현재 개념의 실측 숙달 0~1. **미측정은 None**이다 — 0.0으로 채우면 "
            "콜드스타트 학생이 전부 선수 결손으로 오진된다."
        ),
    )
    misconception_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "최상위 오개념 *가설*의 현재 신뢰 0~1(`MisconceptionHypothesis.confidence`). "
            "가설이 없으면 None — 0.0으로 채우지 않는다(가설 부재와 신뢰 0은 다른 사실)."
        ),
    )
    same_error_count: int = Field(
        default=0,
        ge=0,
        description=(
            "같은 오류의 누적 횟수. 정의는 모듈 docstring 참조 — "
            "**같은 오개념 가설을 지지한 증거 수**(`evidence_count`)이지 재시도 횟수가 아니다. "
            "0은 '반복 신호 없음'이다."
        ),
    )


class RemediationDecision(BaseModel):
    """정책 1회 실행의 결과 — 경로 + 강도 + 어느 규칙이 경로를 골랐는가.

    `rule_id`가 필수인 이유는 `PolicyDecision`과 같다: 이것이 없으면 "왜 이 학생이 이 경로로
    갔는가"를 사후에 재구성할 수 없고, 사다리가 **실제로 발동한 비율**도 셀 수 없다
    (CLAUDE.md "작동 신호 없는 알고리즘 부착 금지").
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    route: RemediationRoute
    rung: EscalationRung
    rule_id: str = Field(description="경로를 결정한 규칙 식별자(예: 'RT1-prerequisite-gap').")


@dataclass(frozen=True, slots=True)
class RemediationPolicyTable:
    """보정 정책의 **임계값 전량** — 나중에 실측으로 조정될 값들이 사는 한 곳.

    dataclass로 두는 이유는 `V1_RULES`와 같다: 인스턴스 하나가 "이 정책이 아는 임계가
    무엇인가"의 전량 목록이 되어 테스트가 직접 셀 수 있다. 값을 함수 본문의 리터럴로 두면
    임계 하나를 옮겨도 "임계가 몇 개인가"를 기계가 물을 수 없다.

    주입 가능하게 둔 것은 확장이 아니라 **검증**을 위해서다 — 경계 이동 뮤테이션 테스트가
    한 칸 옮긴 표를 넣어 픽스처가 그 경계를 실제로 밟는지 확인한다(CLAUDE.md 픽스처 접촉 규칙).
    """

    misconception_remediation_floor: float = MISCONCEPTION_REMEDIATION_FLOOR
    """오개념 교정 경로의 신뢰 하한 — **이 표가 정본**(초과라야 교정)."""

    escalation_ladder: tuple[tuple[int, EscalationRung], ...] = (
        (4, EscalationRung.PREREQUISITE_CONCEPT),
        (3, EscalationRung.EASIER_PROBLEM),
        (2, EscalationRung.CORRECTIVE_EXPLANATION),
    )
    """반복 오류 사다리 — `(최소 횟수, 등급)`을 **횟수 내림차순**으로. 첫 매치가 이긴다.

    내림차순인 것이 계약이다(오름차순이면 4회 학생이 2회 칸에 걸린다). `__post_init__`이
    그 순서를 검사해 위반을 **거부**한다 — 조용히 정렬해 주면 잘못된 표가 정상처럼 돈다.
    """

    prerequisite_mastery_ceiling: float = field(default=PREREQUISITE_MASTERY_CEILING)
    """숙달 하단 경계의 **미러**(0.4). 판정 권위는 `select_reason_type`이다 — 모듈 docstring
    소유권 표 참조. 이 표는 읽기 좋으라고 옮겨 적을 뿐 비교에 쓰지 않는다."""

    weak_concept_mastery_ceiling: float = field(default=WEAK_CONCEPT_MASTERY_CEILING)
    """숙달 상단 경계의 **미러**(0.7). 위와 같다."""

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


@dataclass(frozen=True, slots=True)
class RouteRule:
    """경로 규칙 1건 — 조건과 결과를 데이터로 묶는다(`PolicyRule`과 같은 형태)."""

    rule_id: str
    description: str
    matches: Callable[[RemediationSignals, RemediationPolicyTable], bool]
    route: RemediationRoute


def _mastery_route(signals: RemediationSignals) -> RemediationRoute | None:
    """숙달 축 판정을 `select_reason_type`에 **위임**하고 경로 어휘로 옮긴다(재구현 0).

    미측정(`UNMEASURED`)은 여기서 경로를 내지 않고 `None`을 돌려 뒤 규칙(오개념 축)에 기회를
    넘긴다 — 숙달을 모른다고 오개념 신호까지 버릴 이유가 없다.
    """
    reason = select_reason_type(signals.mastery)
    return {
        ReasonType.PREREQUISITE_GAP: RemediationRoute.PREREQUISITE_CONCEPT,
        ReasonType.CURRENT_CONCEPT: RemediationRoute.SAME_CONCEPT_PRACTICE,
        ReasonType.NEXT_CONCEPT: RemediationRoute.NEXT_CONCEPT,
    }.get(reason)


# ──────────────────────────────────────────────────────────────────────────
# v1 경로 규칙 — 선언 순서가 곧 우선순위다. 위에서부터 첫 매치가 이긴다.
#
# 순서는 계획서 §9가 적은 순서를 따른다(선수 → 오개념 → 연습 → 다음). 숙달이 선수 경계
# 미만인 학생에게 오개념 교정을 먼저 하면, 교정 설명이 딛고 설 바닥이 없다.
#
# 이 순서는 `l2/learning_state_policy.py`의 R3(오개념) > R4(선수결손)와 **반대로 보이지만
# 충돌하지 않는다** — 입력이 다르다. 그쪽 R4는 *지목된 선수 개념 목록*(`prerequisite_gap_
# concept_ids`)이 있을 때만 발동하고, 이쪽은 *실측 숙달 구간*으로 판정한다. 지목된 결손이
# 있다는 것은 이미 원인 분석이 끝났다는 뜻이고, 숙달 0.3은 아직 원인을 모른다는 뜻이다.
# ──────────────────────────────────────────────────────────────────────────
V1_ROUTE_RULES: Sequence[RouteRule] = (
    RouteRule(
        rule_id="RT1-prerequisite-gap",
        description=(
            "숙달이 선수 경계 미만 — 현재 개념을 더 밀어도 막힌다. 오개념 교정보다 앞서는 "
            "이유는 교정 설명이 딛고 설 바닥이 없기 때문이다."
        ),
        matches=lambda s, _t: _mastery_route(s) is RemediationRoute.PREREQUISITE_CONCEPT,
        route=RemediationRoute.PREREQUISITE_CONCEPT,
    ),
    RouteRule(
        rule_id="RT2-misconception",
        description=(
            "오개념 신뢰가 교정 하한 **초과** — 연습을 더 시켜도 잘못 알고 있는 것은 "
            "그대로 남는다. 하한 이하는 매치되지 않아 뒤 규칙(연습)으로 간다."
        ),
        matches=lambda s, t: (
            s.misconception_confidence is not None
            and s.misconception_confidence > t.misconception_remediation_floor
        ),
        route=RemediationRoute.MISCONCEPTION_REMEDIATION,
    ),
    RouteRule(
        rule_id="RT3-current-concept",
        description="숙달이 학습 구간 — 같은 개념을 계속 연습한다.",
        matches=lambda s, _t: _mastery_route(s) is RemediationRoute.SAME_CONCEPT_PRACTICE,
        route=RemediationRoute.SAME_CONCEPT_PRACTICE,
    ),
    RouteRule(
        rule_id="RT4-next-concept",
        description="숙달이 약점 컷 초과 — 다음 개념으로 넘어간다.",
        matches=lambda s, _t: _mastery_route(s) is RemediationRoute.NEXT_CONCEPT,
        route=RemediationRoute.NEXT_CONCEPT,
    ),
)


def select_route(
    signals: RemediationSignals,
    policy: RemediationPolicyTable = REMEDIATION_POLICY_V1,
    *,
    rules: Sequence[RouteRule] = V1_ROUTE_RULES,
) -> tuple[RemediationRoute, str]:
    """신호 → (경로, 결정한 규칙 id) — 순수·결정론.

    어느 규칙도 매치되지 않으면 `UNMEASURED`다. 여기서만은 예외를 내지 않고 값을 돌린다 —
    "숙달도 오개념도 관측되지 않았다"는 규칙 집합의 **구멍이 아니라 실재하는 상태**이기
    때문이다(신규 가입 학생의 첫 턴). `learning_state_policy`가 미매치에 예외를 내는 것과
    다른 판단이며, 그 차이는 입력이 증거(반드시 무언가 관측됨)냐 추정치(비어 있을 수 있음)냐다.
    """
    for rule in rules:
        if rule.matches(signals, policy):
            return rule.route, rule.rule_id
    return RemediationRoute.UNMEASURED, "RT0-unmeasured"


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


def decide_remediation(
    signals: RemediationSignals,
    policy: RemediationPolicyTable = REMEDIATION_POLICY_V1,
) -> RemediationDecision:
    """보정 정책 v1의 단일 진입점 — 경로와 강도를 함께 낸다(`RemediationPolicy` 구현).

    경로와 강도는 **직교**한다. "무엇을 보정하나"(숙달·오개념 축)와 "얼마나 세게
    하나"(반복 축)는 서로 다른 신호를 읽으므로 한쪽이 다른 쪽을 덮어쓰지 않는다.
    """
    route, rule_id = select_route(signals, policy)
    return RemediationDecision(
        route=route,
        rung=select_rung(signals.same_error_count, policy),
        rule_id=rule_id,
    )


class RemediationPolicy(Protocol):
    """보정 정책의 호출 계약 — **v1 내부가 규칙이어도 이 시그니처는 바뀌지 않는다**.

    입력이 `RemediationSignals` 하나인 것이 핵심이다: 정책이 신호를 *받아서* 결정하므로,
    그 신호를 어떻게 추정하는가(BKT/DKT/IRT/LLM 후보 분류)는 정책 바깥의 관심사가 된다.
    """

    def __call__(self, signals: RemediationSignals) -> RemediationDecision: ...
