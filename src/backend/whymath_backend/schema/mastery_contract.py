"""Mastery 갱신 **호출 계약** v1 — 순수 타입·Protocol만(계층 의존 0).

계획서 300 §6(Mastery Engine v1 — "반드시 엔진 인터페이스를 분리합니다") + §2(알고리즘보다
Contract)가 요구하는 *형태*를 코드로 고정한다. 이 모듈은 **알고리즘을 바꾸지 않는다** — 바꾸는
것은 호출 형태다: 스칼라 5개(`prior_mastery, prior_sample_size, correct, model, elapsed_days`)를
받던 자리를 **`update_mastery(learner_state, assessment_evidence) -> MasteryUpdate`** 로 바꾼다.

왜 `schema/`인가
-----------------
import-linter 7계층 계약에서 `schema`는 최하위(어느 계층도 import하지 않는다)다. 계약 타입이
`l2`에 살면 미래의 소비자(L3 라우팅·L4 교수학 결정)가 계약을 읽으려고 `l2`를 통째로 끌어와야
한다. 순수 타입만 여기 두고, **추정기 구현·레지스트리·조립은 `l2/mastery_contract.py`** 가
가진다(그쪽이 BKT를 안다).

이 모듈이 **하는 것**
---------------------
① `LearnerMasteryState` — 한 축(개념/스킬) 한 대상의 *직전 측정* 상태. 미측정은 `None`이다
   (`0.0`이 아니다 — CLAUDE.md "None ≠ 0. 미측정을 0으로 접지 마라").
② `AssessmentEvidenceInput` — 이 계약이 **실제로 읽는** 증거 속성만 담은 구조적 입력 Protocol.
③ `MasteryUpdate` — 갱신 산출. *어느 추정기가 실제로 작동했는지*(`estimator_id`)를 함께 낸다
   (CLAUDE.md "작동 신호 없는 알고리즘 부착 금지").
④ `MasteryEstimator` — 추정기 교체 가능성을 **주석이 아니라 타입으로** 표현하는 Protocol.

이 모듈이 **하지 않는 것** (있는 척 금지)
-----------------------------------------
- **`AssessmentEvidence` 구체 타입을 정의하지 않는다.** 그 좌석은 `EOS-12`가 소유하며 아직
  착지하지 않았다. 여기 있는 것은 *구조적 입력 계약*(Protocol)뿐이고, 필드를 늘리지 않는다 —
  두 번째 진실 원천을 만들지 않기 위해서다. **`EOS-12`가 착지하면 그 `AssessmentEvidence`가
  이 Protocol을 만족해야 한다**(`correct: bool` · `observed_at: datetime` 두 속성).
  이름은 2026-09-16 Kiki 판정(A안)으로 확정된 `AssessmentEvidence`이며, 저장소 정본
  `schema/assessment.py::Assessment`(진단 세션)와는 **다른 객체**다
  (`learning_loop_contract.py`의 `ASSESSMENT_EVIDENCE` 좌석 주석 참조).
- **신규 DB 테이블·좌석을 만들지 않는다.** 숙달 좌석은 `concept_mastery_history`·
  `skill_mastery_history`(ARCH-37 `MasteryState`) 그대로다. 여기서 고정하는 것은 *호출 어휘*다.
- **숙달 수치를 바꾸지 않는다.** 계약 경유 전후로 같은 값이 나오는지는
  `tests/backend/l2/test_mastery_contract.py`의 행동 동결 축이 대조한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from whymath_backend.schema.learning_loop_contract import (
    LoopEdge,
    LoopObject,
    LoopRelation,
)

__all__ = [
    "CONTRACT_RELATION",
    "MASTERY_AXIS_LOOP_OBJECT",
    "AssessmentEvidenceInput",
    "LearnerMasteryState",
    "MasteryAxis",
    "MasteryContractError",
    "MasteryEstimator",
    "MasteryUpdate",
]

#: 이 계약이 집행하는 루프 관계 — `AssessmentEvidence --updates--> LearnerState`.
#: `learning_loop_contract.LOOP_RELATIONS`에 선언된 삼중항이며, 선언이 사라지면
#: `test_mastery_contract.py`가 RED를 낸다(어휘와 계약이 따로 놀지 못하게).
CONTRACT_RELATION = LoopRelation(
    LoopObject.ASSESSMENT_EVIDENCE, LoopEdge.UPDATES, LoopObject.LEARNER_STATE
)


class MasteryAxis(StrEnum):
    """숙달을 재는 축 — 개념(Concept)이냐 스킬(Skill)이냐.

    계획서 §1 관계도의 `LearnerState --mastery--> Concept` · `LearnerState --mastery--> Skill`
    두 간선에 1:1 대응한다. **축은 계산을 가르지 않는다** — 같은 수학을 쓰고, 다른 것은 *어느
    이력을 prior로 읽고 어느 좌석에 적재하는가*뿐이다(그래서 계약이 하나다).
    """

    CONCEPT = "concept"
    SKILL = "skill"


#: 축 ↔ 루프 객체 대응. 계약 어휘(14객체)와 이 모듈이 서로 다른 말을 쓰지 못하게 고정한다.
MASTERY_AXIS_LOOP_OBJECT: Mapping[MasteryAxis, LoopObject] = MappingProxyType(
    {
        MasteryAxis.CONCEPT: LoopObject.CONCEPT,
        MasteryAxis.SKILL: LoopObject.SKILL,
    }
)


class MasteryContractError(ValueError):
    """계약 위반 — 입력이 계약을 만족하지 않거나, 추정기 산출이 계약을 벗어났다.

    *조용히 넘어가지 않는다*(CLAUDE.md 침묵 실패 금지). 메시지에는 무엇이 어긋났는지를 값과
    함께 적되, 개인 식별 정보는 싣지 않는다(대상 id는 개념/스킬 식별자이지 학생 PII가 아니다).
    """


@dataclass(frozen=True, slots=True)
class LearnerMasteryState:
    """한 축·한 대상의 **직전 측정** 상태 — `update_mastery`의 첫째 인자.

    루프 어휘의 `LearnerState --mastery--> {Concept|Skill}` 간선 *하나*를 값으로 들고 다니는
    조각이다(학습자 상태 전체가 아니다 — 전체 조립은 `l2/learner_state.py::LearnerState`이며
    그것은 조회 표면이지 갱신 입력이 아니다).

    **미측정은 `None`이다.** `mastery=None`은 "아직 한 번도 재지 않았다"이며 `0.0`("재봤더니
    0이다")과 다르다. 추정기는 `None`을 받으면 자기 사전값(BKT의 P(L0))에서 시작한다.

    필드
    ----
    axis: 개념 축이냐 스킬 축이냐.
    target_id: 대상 식별자 문자열(개념 축은 `concept_id` UUID의 문자열, 스킬 축은 `skill_id`).
        축마다 키 타입이 달라 계약 층에서는 문자열로 통일한다 — 축을 통합하되 *재계산을 낳지
        않기* 위한 최소 표현이다(UUID 파싱·조회를 계약이 하지 않는다).
    mastery: 직전 측정 숙달 확률 0~1, 미측정이면 None.
    sample_size: 직전까지 누적 관측 수, 미측정이면 None.
    measured_at: 직전 측정 시각, 미측정이면 None. 경과일(망각 감쇠 입력)의 기준점이다.
    """

    axis: MasteryAxis
    target_id: str
    mastery: float | None
    sample_size: int | None
    measured_at: datetime | None

    def __post_init__(self) -> None:
        if not self.target_id:
            raise MasteryContractError("target_id는 비어 있을 수 없습니다(대상 미지정).")
        if self.mastery is not None and not 0.0 <= self.mastery <= 1.0:
            raise MasteryContractError(f"prior mastery는 0~1이어야 합니다(받음: {self.mastery}).")
        if self.sample_size is not None and self.sample_size < 0:
            raise MasteryContractError(
                f"prior sample_size는 음수일 수 없습니다(받음: {self.sample_size})."
            )

    @property
    def is_first_observation(self) -> bool:
        """직전 측정이 없는가 — 추정기가 사전값에서 시작해야 하는 상태."""
        return self.mastery is None

    def elapsed_days_until(self, observed_at: datetime) -> float | None:
        """직전 측정 → 관측 시각 경과일. **직전 측정 시각을 모르면 None**(0이 아니다).

        기존 두 축(`mastery_tracking`·`skill_mastery_tracking`)이 각자 복제하고 있던 계산을
        한 자리로 모은 것이다. 음수(시계 역행)를 여기서 자르지 않는다 — 감쇠 구현
        (`bkt.apply_forgetting`)이 이미 `elapsed_days <= 0`을 무영향으로 처리하며, 여기서
        클램프하면 "시계가 역행했다"는 사실 자체가 계약 층에서 사라진다.
        """
        if self.measured_at is None:
            return None
        return (observed_at - self.measured_at).total_seconds() / 86400.0


@runtime_checkable
class AssessmentEvidenceInput(Protocol):
    """이 계약이 **실제로 읽는** 증거 속성만 담은 구조적 입력(nominal 상속 불요).

    **필드를 늘리지 마라.** 구체 타입 `AssessmentEvidence`의 좌석은 `EOS-12`가 소유한다
    (이 모듈 docstring "하지 않는 것" 참조). 여기에 속성을 추가하는 순간 evidence의 두 번째
    진실 원천이 생기고, `EOS-12`가 착지할 때 두 정의를 맞추는 비용이 발생한다. 반대로 계약이
    새 속성을 *정말* 읽어야 하게 되면 그때 `EOS-12`의 타입과 함께 한 번에 넓힌다.

    읽기 전용 property로 선언한 이유: 그래야 frozen dataclass·Pydantic 모델·평범한 속성 어느
    쪽으로 구현해도 구조적으로 만족한다(가변 속성으로 선언하면 읽기 전용 구현이 탈락한다).
    """

    @property
    def correct(self) -> bool:
        """채점 결과 — 이 관측이 정답이었는가."""

    @property
    def observed_at(self) -> datetime:
        """관측 시각(= 새 측정의 `measured_at`). 경과일 계산의 종점."""


@dataclass(frozen=True, slots=True)
class MasteryUpdate:
    """숙달 갱신 산출 — `update_mastery`의 반환. 좌석 적재 입력이자 추적 기록.

    `mastery`·`confidence`·`sample_size`는 `concept_mastery_history`/`skill_mastery_history`
    컬럼에 그대로 대응한다(정밀도 2자리 — `Numeric(3,2)` 정합).

    나머지 3필드는 *관측 가능성*을 위한 것이다:
    - `prior_mastery`: 무엇에서 출발했는가(첫 관측이면 None — 0으로 접지 않는다).
    - `elapsed_days`: 망각 감쇠에 실제로 쓰인 경과일(직전 시각을 모르면 None).
    - `estimator_id`: **어느 추정기가 실제로 작동했는가.** 알고리즘을 갈아 끼울 수 있게 만든
      이상, 산출이 자기 출처를 말하지 않으면 "무엇이 돌았는지 모르는 상태"가 된다
      (CLAUDE.md "작동 신호 없는 알고리즘 부착 금지").
    """

    axis: MasteryAxis
    target_id: str
    mastery: float
    confidence: float
    sample_size: int
    prior_mastery: float | None
    elapsed_days: float | None
    estimator_id: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.mastery <= 1.0:
            raise MasteryContractError(f"갱신된 mastery는 0~1이어야 합니다(받음: {self.mastery}).")
        if not 0.0 <= self.confidence <= 1.0:
            raise MasteryContractError(f"confidence는 0~1이어야 합니다(받음: {self.confidence}).")
        if self.sample_size < 1:
            raise MasteryContractError(
                f"갱신 후 sample_size는 1 이상이어야 합니다(받음: {self.sample_size})."
            )
        if not self.estimator_id:
            raise MasteryContractError(
                "estimator_id가 비어 있습니다 — 어느 추정기가 작동했는지 말하지 않는 산출은 "
                "계약 위반입니다(작동 신호 없는 알고리즘 부착 금지)."
            )


@runtime_checkable
class MasteryEstimator(Protocol):
    """숙달 추정기 경계 — **교체 가능성을 타입으로 표현**한다(주석이 아니라).

    BKT·DKT·IRT-기반 등 어떤 구현이든 이 두 멤버만 만족하면 레지스트리에 꽂혀 호출부 수정 0으로
    교체된다. 호출부(`l2/mastery_tracking.py`·`l2/skill_mastery_tracking.py`)는 구체 클래스를
    이름으로 알지 않는다.

    **v1 범위 메모(있는 척 금지)**: 이 Protocol은 *상태 + 증거 1건 → 갱신 1건*이라는 형태만
    고정한다. 시퀀스 전체를 입력으로 받는 모델(DKT의 원형)은 자신의 은닉 상태를 스스로 보관하거나
    `LearnerMasteryState`를 넓히는 후속 계약 변경이 필요하다 — 그 변경은 이 태스크 범위 밖이며,
    v1 내부 구현은 현행 heuristic(BKT) 그대로다(태스크 notes "구현 금지 경계").
    """

    @property
    def estimator_id(self) -> str:
        """이 추정기의 안정적 식별자 — 레지스트리 키이자 산출의 출처 표기."""

    def estimate(
        self,
        learner_state: LearnerMasteryState,
        assessment_evidence: AssessmentEvidenceInput,
    ) -> MasteryUpdate:
        """직전 상태 + 증거 1건 → 다음 측정. 순수(DB·IO 무관)해야 한다."""
