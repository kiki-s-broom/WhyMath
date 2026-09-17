"""채점 Evidence 계약 — Answer → **Evidence** → Learner State 의 중간 객체 (EOS-12).

설계 정본: 계획서 300 §5.1. 요지는 *"정답/오답에서 끝나면 안 된다"* 이다 — 채점의 산출은
불리언이 아니라 **무엇에 대한 증거인가**여야 하고, 학습자 상태 변경은 그 증거를 받아 일어나야
한다.

────────────────────────────────────────────────────────────────────────────
현행과의 차이 (acceptance ② — 먼저 적는다)
────────────────────────────────────────────────────────────────────────────
2026-09-16 main 기준 실측:

1. **중간 객체 없이 상태 갱신이 먼저 일어난다.** `AttemptSubmitResponse`는 개념·스킬을
   *증거*가 아니라 **이미 갱신된 mastery delta**로 반환한다. 즉 "이 답이 무엇의 증거인가"는
   `record_problem_attempt_mastery` 내부에서 계산되고 밖으로 나오지 않는다 — 나오는 것은
   갱신 결과뿐이라, 왜 그 개념이 선택됐는지(역할·귀속 근거)를 아무도 볼 수 없다.
2. **오개념은 채점에 합류하지 않는다.** `l4/misconception/diagnose.py`는 coach 대화 경로
   (`api/coach.py`)에서만 호출되고, 채점 응답에는 오개념 축이 0개다.
3. **Assessment 조립은 per-answer가 아니라 배치다**(`POST /v1/me/assessments/capture`) —
   즉 답 1건 단위의 증거 좌석은 그 축에도 없다.

이 모듈이 메우는 것은 **1번의 중간 객체**다. 2번은 이 계약에 슬롯을 두되 오늘의 생산자가
없음을 3상태로 *고지*하고(아래 `MisconceptionScan`) 별건이 소유한다 — 빈 리스트로 조용히
내보내면 "오개념이 없었다"는 거짓이 된다.

────────────────────────────────────────────────────────────────────────────
이 계약이 지는 불변식
────────────────────────────────────────────────────────────────────────────
- **관측이지 상태가 아니다.** `AssessmentEvidence`는 아무것도 영속하지 않고, 영속이
  성공했다고 주장하지도 않는다. 채점 경로는 attempt·개념 숙달·스킬 숙달·이벤트가 각자
  commit하는 구조이고(EOS-81 ⑦이 정직 표기로 동결), 이 객체가 그것을 "한 트랜잭션"인 것처럼
  가리면 안 된다(acceptance ⑤). 그래서 응답은 증거(쓰기 *이전*)와 mastery delta(쓰기 *이후*)를
  **나란히** 싣는다 — 두 단계가 각각 보인다.
- **LLM·매처는 오개념을 확정하지 않는다.** `possible_misconceptions`는 이름 그대로 *후보*이며,
  이 계약에 실리기 전에 `l4/misconception/match_gate.apply_match_quality_gate`(top-1 신뢰도
  floor 0.65)를 통과해야 한다. 확정·영속은 가설 저장소의 몫이고 이 객체는 그 판정을 **옮길 뿐
  내리지 않는다**(계획서 §10 · `harness/wh1_llm_policy._enforce_invariants`와 같은 축).
- **모델 B(역할 비대칭 부분 크레딧)의 정본은 `select_concept_evidence`다.** 정답은 평가 개념
  전체의 합동 증거, 오답은 책임귀속이 분명한 PRIMARY에만(없으면 TESTED 폴백). 오늘은 같은
  규칙이 `l2/mastery_tracking`·`l2/skill_mastery_tracking`에도 인라인으로 살아 있어 **사본이
  셋**이다 — 그 일치를 `tests/backend/schema/test_assessment_evidence.py`의 합치 테스트가
  기계로 동결하며, 사본 통합은 호출 계약을 소유한 `EOS-13`이 가져간다.
- **빈 것과 안 본 것을 구분한다.** 세 종 각각이 `EvidenceKindState` 3상태를 달고 나간다 —
  0건이 "이 답에는 없었다"인지 "우리가 보지 않았다"인지 읽는 쪽이 알 수 있어야 한다
  (CLAUDE.md 「작동한 비율」 원칙 · `l2/learning_event_trace`의 원천 가용성 대장과 같은 축).

계층: 이 모듈은 `schema`(최하위)라 **DB도 다른 계층도 import하지 않는다** — 순수 타입과 순수
함수뿐이다. 조회는 `l2/assessment_evidence.py`가, 소비는 api·L2가 한다.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from enum import Enum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, computed_field

from whymath_backend.schema.enums import ConceptRole

__all__ = [
    "AssessmentEvidence",
    "AttributionBasis",
    "ConceptEvidence",
    "EvidenceCoverage",
    "EvidenceDirection",
    "EvidenceKindState",
    "MisconceptionCandidate",
    "MisconceptionScan",
    "SkillEvidence",
    "build_assessment_evidence",
    "select_concept_evidence",
]


class EvidenceDirection(str, Enum):
    """이 증거가 숙달을 **지지**하는가 **반증**하는가.

    `correct`의 단순 복제가 아니다 — 같은 오답에서도 PRIMARY는 반증 증거를 받고 TESTED는
    *아무 증거도 받지 않는다*(선택되지 않는다). 방향은 선택된 대상에만 붙는다.
    """

    SUPPORTING = "supporting"
    """정답 — 이 개념/스킬이 작동했다는 지지 증거."""

    REFUTING = "refuting"
    """오답 — 책임귀속이 분명한 대상에만 붙는 반증 증거."""


class AttributionBasis(str, Enum):
    """**왜 이 대상이 선택됐는가** — 모델 B의 선택 근거(가장 잃기 쉬운 정보).

    숙달 delta만 반환하면 이 축이 통째로 사라진다. "왜 이 개념이 내려갔는가"에 답하려면
    귀속 근거가 증거에 남아 있어야 한다.
    """

    JOINT_SUPPORT = "joint_support"
    """정답 — 평가 개념(PRIMARY·TESTED) 전체가 함께 작동했다는 합동 증거."""

    PRIMARY_ATTRIBUTION = "primary_attribution"
    """오답 — 책임귀속이 정의상 분명한 PRIMARY."""

    TESTED_FALLBACK = "tested_fallback"
    """오답인데 PRIMARY 매핑이 없는 퇴화 문항 — TESTED로 폴백(기존 writer 동작 승계)."""


class EvidenceKindState(str, Enum):
    """세 종 각각의 상태 — 0건의 *의미*를 결정한다(acceptance ⑥).

    `l2/learning_event_trace`의 원천 가용성 3상태와 같은 규약이다: 미측정이 무활동으로
    읽히면 안 된다.
    """

    FILLED = "filled"
    """실제로 증거가 담겼다."""

    EMPTY_MEASURED = "empty_measured"
    """**보았는데** 없다 — 이 답에는 그 종의 증거가 없는 것이 사실이다."""

    NOT_MEASURED = "not_measured"
    """**보지 않았다**(또는 전제가 없다) — 0건은 학생이 아니라 우리 쪽 사실이다."""


class MisconceptionScan(str, Enum):
    """오개념 후보를 이 채점에서 실제로 훑었는가 — `possible_misconceptions`의 0건 해석."""

    NOT_RUN = "not_run"
    """이 경로는 오개념 매칭을 돌리지 않았다(정답 경로·입력 텍스트 부재·미배선)."""

    RAN_NO_CANDIDATE = "ran_no_candidate"
    """돌렸고 품질 게이트가 후보를 비웠다 — "확실한 후보 없음"이 측정된 결과다."""

    RAN_WITH_CANDIDATES = "ran_with_candidates"
    """돌렸고 게이트를 통과한 후보가 있다."""


class ConceptEvidence(BaseModel):
    """개념 1건에 대한 증거 — *무엇을*, *어느 방향으로*, *왜 그 대상인가*."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    concept_id: uuid.UUID
    role: ConceptRole = Field(description="문항 안에서 이 개념의 역할(PRIMARY·TESTED).")
    direction: EvidenceDirection
    attribution: AttributionBasis


class SkillEvidence(BaseModel):
    """행동(스킬) 축 증거 — 어느 개념에서 해소됐는지를 함께 남긴다.

    `resolved_from`이 비면 안 된다: 스킬은 항상 개념 브리지(`Concept.behavior_skills`)를 거쳐
    해소되므로, 출처 없는 스킬 증거는 재구성 불가능한 주장이 된다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_id: str
    direction: EvidenceDirection
    resolved_from: tuple[uuid.UUID, ...] = Field(
        description="이 스킬을 해소해 준 평가 개념 id들(빈 튜플 금지 — 출처 없는 증거 방지)."
    )


class MisconceptionCandidate(BaseModel):
    """오개념 **후보** — 확정이 아니다(낙인 금지·LLM 비권위).

    이 객체에 실리려면 이미 `apply_match_quality_gate`의 top-1 신뢰도 floor를 통과했어야
    한다. 그 사실을 `gate_passed`가 자기 기술한다 — 게이트를 건너뛴 후보를 여기 담으면
    계약 위반이고, 그것을 `build_assessment_evidence`가 거부한다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    misconception_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    gate_passed: bool = Field(
        description="품질 게이트(top-1 신뢰도 floor)를 통과했는가. False면 계약상 실릴 수 없다."
    )
    low_quality: bool = Field(
        default=False, description="OCR 신뢰도 미달 — 후보는 유지하되 오염 가능성 플래그."
    )
    attribution_unclear: bool = Field(
        default=False, description="정정 어구의 귀속 불명 — 후보는 유지하되 확신 진단 보류."
    )


class EvidenceCoverage(BaseModel):
    """**작동한 비율** — 3종 중 몇 종이 실제로 채워졌는가(acceptance ⑥).

    200 응답은 알고리즘이 일했다는 증거가 아니다. 이 블록이 없으면 "증거가 비었다"와
    "증거를 만들지 않았다"가 같은 화면으로 보인다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    concept: EvidenceKindState
    skill: EvidenceKindState
    misconception: EvidenceKindState
    misconception_scan: MisconceptionScan
    concept_count: int = Field(ge=0)
    skill_count: int = Field(ge=0)
    misconception_count: int = Field(ge=0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def filled_kinds(self) -> int:
        """3종 중 실제로 채워진 종 수 — **응답에 함께 실린다**(작동 비율의 단일 수치).

        `computed_field`인 이유: 이 값이 직렬화되지 않으면 소비자가 세 상태를 각자 세어야 하고,
        그러면 "작동 비율"이 화면에 없는 것과 같다(200 응답은 알고리즘이 일했다는 증거가 아니다).
        """
        return sum(
            1
            for state in (self.concept, self.skill, self.misconception)
            if state is EvidenceKindState.FILLED
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unmeasured_kinds(self) -> tuple[str, ...]:
        """0건이 *우리 쪽 사실*인 종 — 빈 것과 안 본 것을 섞어 보고하지 않기 위한 축."""
        pairs = (
            ("concept", self.concept),
            ("skill", self.skill),
            ("misconception", self.misconception),
        )
        return tuple(name for name, state in pairs if state is EvidenceKindState.NOT_MEASURED)


class AssessmentEvidence(BaseModel):
    """채점 1건이 만들어 낸 증거 묶음 — 학습자 상태 변경의 **입력**.

    이 객체는 상태가 아니라 관측이다. 영속하지 않고, 영속 성공을 주장하지도 않는다
    (모듈 docstring 「관측이지 상태가 아니다」).

    `EOS-13`이 세울 `update_mastery(state, evidence)` 계약의 `evidence`가 바로 이 타입이다 —
    그래서 BKT를 DKT/IRT로 갈아 끼워도 이 모양은 그대로 유지돼야 한다. 여기에 delta·mastery
    값이 **없는 것이 의도**다: 추정기가 무엇을 산출하든 증거는 같다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    learner_id: uuid.UUID
    problem_id: uuid.UUID
    attempt_id: uuid.UUID | None = Field(
        default=None,
        description="이 증거가 귀속되는 attempt. 적재 전에 조립하면 None일 수 있다.",
    )
    correct: bool
    observed_at: datetime

    concept_evidence: tuple[ConceptEvidence, ...] = ()
    skill_evidence: tuple[SkillEvidence, ...] = ()
    possible_misconceptions: tuple[MisconceptionCandidate, ...] = ()
    coverage: EvidenceCoverage


#: 세 종의 이름 — 리포트·테스트가 같은 어휘를 쓰게 고정한다.
EVIDENCE_KINDS: Final[tuple[str, str, str]] = ("concept", "skill", "misconception")


def select_concept_evidence(
    *,
    correct: bool,
    primary_ids: Sequence[uuid.UUID],
    tested_ids: Sequence[uuid.UUID],
) -> tuple[ConceptEvidence, ...]:
    """모델 B(역할 비대칭 부분 크레딧) 선택 — **이 함수가 그 규칙의 정본이다**(순수).

    - **정답** → PRIMARY·TESTED *전체*를 지지(합동 증거). 모든 평가 개념이 함께 작동했다는
      증거라 귀속 모호성이 작다.
    - **오답** → 책임귀속이 정의상 분명한 **PRIMARY에만** 반증. TESTED는 선택하지 않는다 —
      책임귀속이 모호한 개념에 거짓 약점 신호를 주지 않는다(CLAUDE.md "오답=약점 단정 금지").
      PRIMARY 매핑이 없는 퇴화 문항만 TESTED로 폴백한다.

    입력 순서를 보존하고 중복 id는 앞선 것만 남긴다(같은 개념이 두 역할로 실려도 증거는 1건).
    """
    if correct:
        selected: list[tuple[uuid.UUID, ConceptRole]] = [
            (cid, ConceptRole.PRIMARY) for cid in primary_ids
        ]
        selected += [(cid, ConceptRole.TESTED) for cid in tested_ids]
        direction = EvidenceDirection.SUPPORTING
        basis = AttributionBasis.JOINT_SUPPORT
    elif primary_ids:
        selected = [(cid, ConceptRole.PRIMARY) for cid in primary_ids]
        direction = EvidenceDirection.REFUTING
        basis = AttributionBasis.PRIMARY_ATTRIBUTION
    else:
        # PRIMARY 미매핑 퇴화 문항 — 기존 writer의 TESTED 폴백을 그대로 승계한다.
        selected = [(cid, ConceptRole.TESTED) for cid in tested_ids]
        direction = EvidenceDirection.REFUTING
        basis = AttributionBasis.TESTED_FALLBACK

    seen: set[uuid.UUID] = set()
    evidence: list[ConceptEvidence] = []
    for concept_id, role in selected:
        if concept_id in seen:
            continue
        seen.add(concept_id)
        evidence.append(
            ConceptEvidence(
                concept_id=concept_id, role=role, direction=direction, attribution=basis
            )
        )
    return tuple(evidence)


def _kind_state(count: int, measured: bool) -> EvidenceKindState:
    if not measured:
        return EvidenceKindState.NOT_MEASURED
    return EvidenceKindState.FILLED if count else EvidenceKindState.EMPTY_MEASURED


def build_assessment_evidence(
    *,
    learner_id: uuid.UUID,
    problem_id: uuid.UUID,
    correct: bool,
    observed_at: datetime,
    concept_evidence: Sequence[ConceptEvidence],
    skill_evidence: Sequence[SkillEvidence],
    possible_misconceptions: Sequence[MisconceptionCandidate] = (),
    misconception_scan: MisconceptionScan = MisconceptionScan.NOT_RUN,
    concept_mapping_present: bool,
    skill_bridge_present: bool,
    attempt_id: uuid.UUID | None = None,
) -> AssessmentEvidence:
    """세 종을 묶고 **작동 비율(coverage)을 함께 계산**한다(순수·DB 무관).

    `concept_mapping_present`/`skill_bridge_present`는 *조회를 실제로 했는가*를 호출자가
    알려 주는 축이다. 0건일 때 그것이 "문항-개념 매핑이 없다"(우리 쪽 공백)인지 "개념은
    있는데 이 답에는 증거가 안 붙는다"인지를 여기서 구분한다 — 둘을 합치면 데이터 공백이
    학생의 무활동으로 보인다.

    계약 집행 2건(조용히 통과시키지 않고 `ValueError`):
      ① 게이트를 통과하지 않은 오개념 후보는 실을 수 없다(LLM·매처 비권위 불변식).
      ② `misconception_scan`과 후보 건수가 어긋날 수 없다 — 돌리지 않았다면서 후보가 있거나,
         후보가 있다면서 `RAN_NO_CANDIDATE`이면 그 보고는 거짓이다.
    """
    ungated = [c.misconception_id for c in possible_misconceptions if not c.gate_passed]
    if ungated:
        raise ValueError(
            "게이트를 통과하지 않은 오개념 후보는 Evidence에 실을 수 없다"
            f"(gate_passed=False): {ungated}. 확정은 match_gate·가설 저장소의 몫이다."
        )
    count = len(possible_misconceptions)
    if misconception_scan is MisconceptionScan.NOT_RUN and count:
        raise ValueError("misconception_scan=not_run인데 후보가 실렸다 — 보고가 사실과 어긋난다.")
    if misconception_scan is MisconceptionScan.RAN_NO_CANDIDATE and count:
        raise ValueError("misconception_scan=ran_no_candidate인데 후보가 실렸다.")
    if misconception_scan is MisconceptionScan.RAN_WITH_CANDIDATES and not count:
        raise ValueError("misconception_scan=ran_with_candidates인데 후보가 0건이다.")

    coverage = EvidenceCoverage(
        concept=_kind_state(len(concept_evidence), concept_mapping_present),
        skill=_kind_state(len(skill_evidence), skill_bridge_present),
        misconception=_kind_state(count, misconception_scan is not MisconceptionScan.NOT_RUN),
        misconception_scan=misconception_scan,
        concept_count=len(concept_evidence),
        skill_count=len(skill_evidence),
        misconception_count=count,
    )
    return AssessmentEvidence(
        learner_id=learner_id,
        problem_id=problem_id,
        attempt_id=attempt_id,
        correct=correct,
        observed_at=observed_at,
        concept_evidence=tuple(concept_evidence),
        skill_evidence=tuple(skill_evidence),
        possible_misconceptions=tuple(possible_misconceptions),
        coverage=coverage,
    )
