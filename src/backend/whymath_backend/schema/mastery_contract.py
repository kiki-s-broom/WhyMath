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
⑤ `clamp_unit` — 0~1 경계 강제(EOS-108). 추정기를 **신뢰하지 않는다**: 갈아 끼울 수 있게
   만든 순간, 범위를 지키지 않는 구현이 들어올 수 있는 표면이 생겼다.
⑥ `HintUsageSignal`·`hint_used_of` — 힌트 사용 여부의 **선택적** 3상태 축(EOS-108). 계획서
   §6 v1 규칙의 "힌트 사용 → 이득 x0.7"이 읽는 자리이며, `None`은 "안 썼다"가 아니라 "모른다"다.

이 모듈이 **하지 않는 것** (있는 척 금지)
-----------------------------------------
- **`AssessmentEvidence` 구체 타입을 정의하지 않는다.** 그 좌석은 `EOS-12`가 소유한다(2026-09-16
  착지). 여기 있는 것은 *구조적 입력 계약*(Protocol)뿐이며, **추정기가 실제로 읽는 2속성만**
  담는다(`correct` · `observed_at` — EOS-18 ④ 재판정). 이름은 2026-09-16 Kiki 판정(A안)으로
  확정된 `AssessmentEvidence`이며, 저장소 정본 `schema/assessment.py::Assessment`(진단 세션)와는
  **다른 객체**다 (`learning_loop_contract.py`의 `ASSESSMENT_EVIDENCE` 좌석 주석 참조).
- **신규 DB 테이블·좌석을 만들지 않는다.** 숙달 좌석은 `concept_mastery_history`·
  `skill_mastery_history`(ARCH-37 `MasteryState`) 그대로다. EOS-108은 그 두 테이블에 멱등 키
  컬럼 1개(`attempt_id`)를 더할 뿐 **좌석을 늘리지 않는다**(엔티티 동결 불변).
- **기본 추정기의 숙달 수치를 바꾸지 않는다.** EOS-108이 계획서 §6의 가산 규칙을 두 번째
  추정기(`simple-additive-v1`)로 정본화했지만 **기본값은 `bkt-v1` 그대로**다 — 기본을 바꾸는
  것은 리팩터가 아니라 전 학생에게 적용되는 정책 변경이며, 측정 없이 할 일이 아니다
  (`docs/architecture/mastery_update_contract_v1.md` §추정기 처분).
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
    "HintUsageSignal",
    "StreakSignal",
    "LearnerMasteryState",
    "MasteryAxis",
    "MasteryContractError",
    "MasteryEstimator",
    "MasteryUpdate",
    "clamp_unit",
    "consecutive_correct_of",
    "hint_used_of",
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

    **필드를 함부로 늘리지 마라.** 구체 타입 `AssessmentEvidence`의 좌석은 `EOS-12`가 소유한다.
    여기에 속성을 추가하는 순간 evidence의 두 번째 진실 원천이 생긴다. 넓혀도 되는 유일한
    조건은 **`EOS-12`의 `AssessmentEvidence`가 이미 그 속성을 가지고 있는 것**이다 — 그때는
    두 정의가 갈라지는 것이 아니라 계약이 이미 있는 사실을 읽기 시작하는 것뿐이다.

    `attempt_id`를 **여기에 두지 않은 이유** (EOS-108 · 2026-09-18)
    ------------------------------------------------------------
    멱등 키(`attempt_id`)는 숙달 이중 반영을 막는 데 반드시 필요하지만, 그것은 *추정 입력*이
    아니라 **적재 writer의 관심사**다. 추정기(BKT·후속 DKT)는 "맞았는가·언제인가"만 읽고
    "어느 시도였는가"는 읽지 않는다 — 여기에 실으면 추정기 Protocol이 추정과 무관한 것을
    요구하게 된다(EOS-18 ④가 `learner_id`·`problem_id`를 같은 이유로 배제한 것과 동형).
    그래서 `l2/mastery_tracking`의 공개 writer가 `AssessmentEvidence.attempt_id`를 직접 읽어
    staging에 **명시 인자로** 넘긴다(`user_id`를 넘기는 것과 같은 자리·같은 이유).

    읽기 전용 property로 선언한 이유: 그래야 frozen dataclass·Pydantic 모델·평범한 속성 어느
    쪽으로 구현해도 구조적으로 만족한다(가변 속성으로 선언하면 읽기 전용 구현이 탈락한다).
    """

    @property
    def correct(self) -> bool:
        """채점 결과 — 이 관측이 정답이었는가."""

    @property
    def observed_at(self) -> datetime:
        """관측 시각(= 새 측정의 `measured_at`). 경과일 계산의 종점."""


@runtime_checkable
class HintUsageSignal(Protocol):
    """힌트 사용 여부를 **선택적으로** 싣는 증거 — `AssessmentEvidenceInput`의 확장 축.

    왜 본 Protocol이 아니라 별도인가: `EOS-12`의 `AssessmentEvidence`에는 `hint_used`가
    **아직 없다**. 본 Protocol에 넣으면 그 타입이 계약을 만족하지 못하게 되어, 임시 어댑터를
    폐기하려는 `EOS-18`의 길을 이 태스크가 막는다. 그래서 *가진 증거만 만족하는* 좁은
    Protocol로 분리하고, 소비자는 `hint_used_of()`로 3상태를 받는다.

    계획서 300 §6의 v1 규칙 중 "힌트 사용 → 이득 x0.7"이 읽는 유일한 축이다.
    """

    @property
    def hint_used(self) -> bool | None:
        """이 관측에서 힌트를 썼는가. **`None`은 "모른다"**(안 썼다가 아니다)."""


def hint_used_of(assessment_evidence: object) -> bool | None:
    """증거에서 힌트 사용 여부를 3상태로 읽는다 — True / False / **None=미측정**.

    `None`을 `False`로 접지 않는다(CLAUDE.md "모른다 ≠ 아니다" — 3상태를 truthiness로
    2상태로 접으면 *모르는* 데이터로 확정 신호를 낸다). 힌트 축을 읽는 추정기는 `None`을
    받았을 때 감액을 적용하지 **않되**, 적용하지 않은 이유가 "힌트를 안 썼기 때문"이 아니라
    "모르기 때문"임을 자기 산출에 남겨야 한다.
    """
    if not isinstance(assessment_evidence, HintUsageSignal):
        return None
    value = assessment_evidence.hint_used
    return None if value is None else bool(value)


@runtime_checkable
class StreakSignal(Protocol):
    """연속 정답 횟수를 **선택적으로** 싣는 증거 — 계획서 §6 "연속 정답 → confidence 증가"의 입력.

    `HintUsageSignal`과 같은 이유로 본 Protocol에서 분리했다(`EOS-12`의 `AssessmentEvidence`가
    아직 이 축을 갖지 않는다). 세는 것은 **이번 관측을 포함하지 않은 직전까지의 연속 정답**이다
    — 이번 관측의 정오답은 `correct`가 이미 말하므로 두 번 세면 규칙이 한 칸씩 밀린다.
    """

    @property
    def consecutive_correct(self) -> int | None:
        """직전까지의 연속 정답 횟수. **`None`은 "모른다"**(0회가 아니다)."""


def consecutive_correct_of(assessment_evidence: object) -> int | None:
    """증거에서 연속 정답 횟수를 3상태로 읽는다 — 값 / 0 / **None=미측정**.

    `hint_used_of`와 같은 규율이다: `None`을 0으로 접지 않는다. 음수는 계약 위반이므로
    `None`으로 떨어뜨리지 않고 **예외**로 드러낸다(조용한 정정은 관측을 날조한다).
    """
    if not isinstance(assessment_evidence, StreakSignal):
        return None
    value = assessment_evidence.consecutive_correct
    if value is None:
        return None
    if value < 0:
        raise MasteryContractError(f"consecutive_correct는 음수일 수 없습니다(받음: {value}).")
    return int(value)


def clamp_unit(value: float) -> float:
    """0.0~1.0 단위구간 클램프 — 숙달·신뢰도가 학습자 상태에 들어가기 전 마지막 관문.

    **왜 예외가 아니라 클램프인가**: 범위를 벗어난 산출은 추정기의 결함이지 학생의 사실이
    아니다. 여기서 예외를 던지면 결함 있는 추정기 하나가 *채점 자체를 실패시켜* 학생의 학습을
    멈춘다(의사결정 우선순위 1 "학생 안전·웰빙"이 6 "개발 편의"보다 앞선다). 그래서 값은
    자르되, **자른 사실은 절대 잃지 않는다** — `MasteryUpdate.bounds_clamped`가 그것을 싣고
    호출 계약이 경고 로그를 남긴다(침묵 실패 금지).

    NaN은 클램프할 수 없다 — 비교가 전부 False라 조용히 통과한다. 그래서 여기서만 예외다.
    """
    if value != value:  # NaN — 자기 자신과 같지 않은 유일한 float
        raise MasteryContractError(
            "숙달·신뢰도 값이 NaN입니다 — 클램프로 구제할 수 없는 산출입니다(추정기 결함)."
        )
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


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

    EOS-108이 더한 1필드 — *사실을 잃지 않기 위한* 것이다:
    - `bounds_clamped`: 추정기 산출이 0~1을 벗어나 계약이 **잘랐는가**. 자른 값만 남기고 자른
      사실을 버리면, 결함 있는 추정기가 정상 추정기와 구별되지 않는다(위장). 기본 False이며
      True는 언제나 추정기 결함의 신고다.

    멱등 키(`attempt_id`)는 **여기에 없다** — 추정 산출이 아니라 적재 writer의 관심사다
    (위 `AssessmentEvidenceInput` docstring의 같은 항목 참조).
    """

    axis: MasteryAxis
    target_id: str
    mastery: float
    confidence: float
    sample_size: int
    prior_mastery: float | None
    elapsed_days: float | None
    estimator_id: str
    bounds_clamped: bool = False

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
