"""P3-08 — 튜터 context 9종 매니페스트: 조회됐는가(resolved)와 튜터에 실렸는가(delivered)를 가른다.

정본 지시: `docs/strategy/phase3_math_eos_completion_instruction_set.md` [12] P3-08.
보고서: `docs/reviews/p3_08_tutor_context_builder_2026-10-20.md`.

**이 모듈이 막는 것 — 누락·미전달의 무증상 통과.** 코치 세션 핸들러(`api/coach.py`)는 9종 context
조각을 대부분 조회하지만, 조회 결과가 `None`이면 소비처마다 조용히 기본값으로 진행했다(θ 없음 →
`theta=0.0` 콜드스타트, 팩 없음 → base 발문). 더 근본적으로 **조회된 값의 대부분은 튜터(WH-1 primary
LLM 정책)에 아예 전달되지 않는다** — 정책이 받는 것은 학생 답안·풀이 단계·활성 가설·θ뿐이다.

그래서 슬롯마다 두 축을 따로 판정한다.

- `resolved` — 서버/요청에서 값을 얻었는가. 못 얻었으면 원인 코드(`cause`)를 함께 싣는다.
- `delivered_to_tutor` — 그 값이 튜터 러너의 입력(정책 사적 보유값·초기 가설·금지모드 가드)에
  **실제로** 실렸는가. 이 축은 핸들러가 추정하지 않는다 — `harness/wh1_primary.py`가 정책을
  만든 *뒤* 정책 객체가 실제로 보유한 값에서 계산해 `TutorDeliveryReceipt`로 돌려준다
  (`LLMTutorPolicy.delivered_context_slots`).

누락 처리 정책(보고서 §3): **진행하되 표기**. 표기는 응답 `tutor_context`, 로그 1줄, 튜터 프롬프트
요약(`context_missing`·`context_not_delivered`), 관측 레코드 네 곳이다. **값은 어디에도
싣지 않는다** — 숙달·θ 수치(slice 69/70 비노출)·개념/스킬 id·학생 원문·답안 길이·예외
타입명은 응답에 없다(예외 타입명은 조회 좌석의 서버 로그에만 남는다).

**로그 등급**: WARNING은 *시스템 결함*(`source_disabled`·`lookup_failed`)이 있고 튜터가 실제로 불린
턴에만 낸다. 학생 측 정상 부재(`not_supplied`·`no_problem_context`·`none_detected`·`no_history`=
콜드스타트)와 데이터 커버리지 공백(`coverage_gap` — 팩 미보유 단원·개념/스킬 미매핑)은 INFO다 —
운영 턴 대부분이 해당하므로 WARNING이면 상시 경보가 되어 진짜 결함이 묻힌다. 커버리지 공백은 관측
레코드의 `context_coverage_gap`으로 집계한다.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.schema.pedagogy_pack import PedagogyPack

__all__ = [
    "SYSTEM_DEFECT_CAUSES",
    "AbsenceCause",
    "TutorContextManifest",
    "TutorContextSlot",
    "TutorContextSlotStatus",
    "TutorDeliveryReceipt",
    "build_tutor_context_manifest",
    "log_tutor_context",
]

logger = logging.getLogger("whymath.harness.wh1_tutor_context")


class TutorContextSlot(str, Enum):
    """튜터 context 9종(P3-08 지시문 순서 그대로). 값의 순서가 매니페스트 `slots`의 순서다."""

    LEARNER_STATE = "learner_state"
    """학생 상태 — 서버 L2 능력 θ(필수 축)·학년(보조 축). θ 없으면 튜터는 0.0 콜드스타트."""
    CONCEPT = "concept"
    """현재 Concept — 문항의 대표 개념(PRIMARY, 없으면 TESTED)."""
    SKILL = "skill"
    """현재 Skill — 대표 개념의 mastery-estimable 스킬(1홉 해소)."""
    PROBLEM = "problem"
    """문제 — 이 대화가 속한 문항."""
    STUDENT_ANSWER = "student_answer"
    """학생 답안 — 이번 턴 학생 풀이/발화 텍스트(공백만이면 없음)."""
    SOLUTION_RECORD = "solution_record"
    """풀이 기록 — 이번 턴 제출된 풀이 단계 시퀀스(verify 대상)."""
    MISCONCEPTION = "misconception"
    """추정 Misconception — 이번 턴 매칭으로 큐레이션된 활성 가설(reactive·preload 아님)."""
    MASTERY = "mastery"
    """Mastery — 서버 개념 숙달도 또는 클라 제출 숙달 신호."""
    PEDAGOGY_POLICY = "pedagogy_policy"
    """Pedagogy Policy — 문항 개념의 교수법 팩. 없으면 base Polya 정책만으로 진행한다."""


class AbsenceCause(str, Enum):
    """슬롯을 못 얻은 원인 — 조회 안 함·이력 없음·매핑 없음·실패를 같은 None으로 뭉개지 않는다."""

    NOT_SUPPLIED = "not_supplied"
    """요청이 싣지 않았다(학생 측 정상 부재 — 첫 진입·텍스트 턴)."""
    NO_PROBLEM_CONTEXT = "no_problem_context"
    """문항 맥락이 없어 문항 기반 조회가 성립하지 않는다(문항 없는 대화)."""
    NONE_DETECTED = "none_detected"
    """조회는 했고 결과가 0건이다(오개념 의심 없음)."""
    NO_HISTORY = "no_history"
    """이 학생의 측정 이력이 아직 없다(콜드스타트 — 학생 측 정상 부재)."""
    COVERAGE_GAP = "coverage_gap"
    """데이터 커버리지 공백 — 문항-개념·개념-스킬 미매핑, 팩 미보유 단원(관측 레코드로 집계)."""
    SOURCE_DISABLED = "source_disabled"
    """기능 플래그가 꺼져 조회 자체를 하지 않았다(시스템 설정 — WARNING)."""
    LOOKUP_FAILED = "lookup_failed"
    """조회 중 예외(never-break로 흡수 — 예외 타입명은 조회 좌석 서버 로그에만·WARNING)."""


SYSTEM_DEFECT_CAUSES: frozenset[AbsenceCause] = frozenset(
    {AbsenceCause.SOURCE_DISABLED, AbsenceCause.LOOKUP_FAILED}
)
"""튜터가 불린 턴에서 WARNING을 낼 원인 — 시스템 결함뿐(학생 측 부재·커버리지 공백은 INFO)."""


class TutorContextSlotStatus(BaseModel):
    """슬롯 1개의 판정 — 값 없이 조회 여부·튜터 전달 여부·크기·원인만."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slot: TutorContextSlot = Field(description="9종 중 어느 슬롯인가.")
    resolved: bool = Field(description="이 턴에 서버 조회·요청으로 값을 얻었는가.")
    delivered_to_tutor: bool = Field(
        description=(
            "그 값이 튜터 러너 입력(정책 보유값·초기 가설·금지모드 가드)에 실제로 실렸는가. "
            "튜터가 불리지 않은 턴은 전부 false다."
        )
    )
    size: int | None = Field(
        default=None,
        ge=0,
        description=(
            "크기(값 아님) — 학생 상태=있는 축 수(θ·학년)·스킬=스킬 수·풀이 기록=단계 수·"
            "오개념=가설 수·그 외=1·못 얻었으면 0. 학생 답안은 길이를 노출하지 않아 null."
        ),
    )
    cause: AbsenceCause | None = Field(
        default=None, description="못 얻었을 때만 — 원인 코드. 얻었으면 null."
    )

    @model_validator(mode="after")
    def _consistent(self) -> TutorContextSlotStatus:
        # 못 얻었는데 원인이 없거나, 얻었는데 원인이 있으면 그 자체가 '무증상 누락'이다 — 거부.
        if self.resolved == (self.cause is not None):
            raise ValueError(f"{self.slot.value}: resolved={self.resolved}·cause={self.cause}")
        if self.delivered_to_tutor and not self.resolved:
            raise ValueError(f"{self.slot.value}: 못 얻은 값을 튜터에 실었다고 표기할 수 없다")
        if self.slot is TutorContextSlot.STUDENT_ANSWER and self.size is not None:
            raise ValueError("학생 답안의 크기(길이)는 노출하지 않는다")
        return self


class TutorContextManifest(BaseModel):
    """튜터 호출 1회의 context 구성 요약 — 9슬롯 전부·누락·미전달·튜터 호출 여부."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tutor_invoked: bool = Field(
        description=(
            "이 턴에 튜터(WH-1 primary LLM)를 실제로 불렀는가. false면 완료 상태머신이 발화를 "
            "가로챘거나 primary 플래그가 꺼진 턴이다 — 아래 판정은 '튜터가 받을 수 있었던 것'의 "
            "기록이며 delivered_to_tutor는 전부 false다."
        )
    )
    slots: list[TutorContextSlotStatus] = Field(description="9종 슬롯 판정(지시문 순서).")
    missing: list[TutorContextSlot] = Field(description="값을 못 얻은 슬롯(지시문 순서).")
    not_delivered: list[TutorContextSlot] = Field(
        description="값은 얻었으나 튜터에 실리지 않은 슬롯(지시문 순서). 완비 턴에도 남을 수 있다."
    )
    complete: bool = Field(description="9종 값을 전부 얻었는가(= missing이 비었는가).")

    @model_validator(mode="after")
    def _all_nine_and_consistent(self) -> TutorContextManifest:
        order = [s.slot for s in self.slots]
        if order != list(TutorContextSlot):
            raise ValueError(f"매니페스트는 9종을 순서대로 전부 담아야 한다: {order}")
        if self.missing != [s.slot for s in self.slots if not s.resolved]:
            raise ValueError("missing이 슬롯 판정과 어긋난다")
        expected_nd = [s.slot for s in self.slots if s.resolved and not s.delivered_to_tutor]
        if self.not_delivered != expected_nd:
            raise ValueError("not_delivered가 슬롯 판정과 어긋난다")
        if self.complete != (not self.missing):
            raise ValueError("complete가 missing과 어긋난다")
        if not self.tutor_invoked and any(s.delivered_to_tutor for s in self.slots):
            raise ValueError("튜터를 부르지 않은 턴에 전달됨 표기는 있을 수 없다")
        return self

    def status_of(self, slot: TutorContextSlot) -> TutorContextSlotStatus:
        """슬롯 1개의 판정(9종이 다 있음은 검증자가 보장)."""
        return next(s for s in self.slots if s.slot is slot)

    def missing_names(self) -> list[str]:
        """못 얻은 슬롯 이름 — 튜터 프롬프트·관측 레코드에 싣는 형태."""
        return [s.value for s in self.missing]

    def not_delivered_names(self) -> list[str]:
        """얻었으나 튜터에 안 실린 슬롯 이름."""
        return [s.value for s in self.not_delivered]

    def coverage_gap_names(self) -> list[str]:
        """원인이 데이터 커버리지 공백인 슬롯 이름 — 관측 레코드 집계용."""
        return [s.slot.value for s in self.slots if s.cause is AbsenceCause.COVERAGE_GAP]

    def with_delivery(
        self, *, tutor_invoked: bool, delivered: Iterable[TutorContextSlot]
    ) -> TutorContextManifest:
        """튜터 호출 결과(실제 전달 슬롯)를 반영한 새 매니페스트.

        `delivered`는 러너가 정책 객체에서 계산한 값이다. 못 얻은 슬롯이 전달됐다고 오면 판정
        불일치이므로 표기하지 않고 WARNING을 남긴다(조용히 넘기지 않는다·요청은 깨지 않는다).
        """
        delivered_set = frozenset(delivered) if tutor_invoked else frozenset()
        bogus = sorted(s.value for s in delivered_set if not self.status_of(s).resolved)
        if bogus:
            logger.warning("튜터 context 판정 불일치 — 못 얻은 슬롯이 전달됨으로 보고됨: %s", bogus)
        slots = [
            s.model_copy(update={"delivered_to_tutor": s.resolved and s.slot in delivered_set})
            for s in self.slots
        ]
        return TutorContextManifest(
            tutor_invoked=tutor_invoked,
            slots=slots,
            missing=list(self.missing),
            not_delivered=[s.slot for s in slots if s.resolved and not s.delivered_to_tutor],
            complete=self.complete,
        )


@dataclass
class TutorDeliveryReceipt:
    """러너가 채우는 전달 영수증 — 정책을 만든 *뒤* 실제 전달 슬롯을 반영한 매니페스트."""

    manifest: TutorContextManifest | None = None


def _resolved(slot: TutorContextSlot, size: int | None) -> TutorContextSlotStatus:
    return TutorContextSlotStatus(slot=slot, resolved=True, delivered_to_tutor=False, size=size)


def _absent(
    slot: TutorContextSlot, cause: AbsenceCause, *, size: int | None = 0
) -> TutorContextSlotStatus:
    return TutorContextSlotStatus(
        slot=slot, resolved=False, delivered_to_tutor=False, size=size, cause=cause
    )


def build_tutor_context_manifest(
    *,
    problem_present: bool,
    concept_present: bool,
    concept_lookup_failed: bool,
    skill_ids: Sequence[str],
    skill_lookup_failed: bool,
    theta: float | None,
    theta_enabled: bool,
    grade: int | None,
    student_answer: str | None,
    solution_steps: Sequence[str] | None,
    hypotheses: Sequence[MisconceptionHypothesis],
    server_mastery: float | None,
    client_mastery_supplied: bool,
    mastery_enabled: bool,
    pack: PedagogyPack | None,
    pack_enabled: bool,
) -> TutorContextManifest:
    """핸들러가 이미 조회한 값으로 9종 `resolved` 판정을 낸다(순수·결정론·DB 0·값을 채우지 않음).

    반환 매니페스트는 튜터 호출 *전* 상태다(`tutor_invoked=False`·전달 0). 실제 전달은 러너가
    `with_delivery`로 반영한다. 어떤 슬롯도 기본값으로 채우지 않는다.
    """
    slots: list[TutorContextSlotStatus] = []

    # ① 학생 상태 — 튜터가 소비하는 축은 θ. 학년만 있으면 여전히 '못 얻음'(콜드스타트 위장 금지).
    learner_axes = int(theta is not None) + int(grade is not None)
    if theta is not None:
        slots.append(_resolved(TutorContextSlot.LEARNER_STATE, learner_axes))
    else:
        cause = AbsenceCause.SOURCE_DISABLED if not theta_enabled else AbsenceCause.NO_HISTORY
        slots.append(_absent(TutorContextSlot.LEARNER_STATE, cause, size=learner_axes))

    # ② 현재 Concept / ③ 현재 Skill — 스킬은 개념에서 1홉 해소되므로 개념 원인을 승계한다.
    concept_cause: AbsenceCause | None
    if not problem_present:
        concept_cause = AbsenceCause.NO_PROBLEM_CONTEXT
    elif concept_lookup_failed:
        concept_cause = AbsenceCause.LOOKUP_FAILED
    elif not concept_present:
        concept_cause = AbsenceCause.COVERAGE_GAP
    else:
        concept_cause = None
    if concept_cause is None:
        slots.append(_resolved(TutorContextSlot.CONCEPT, 1))
        if skill_lookup_failed:
            slots.append(_absent(TutorContextSlot.SKILL, AbsenceCause.LOOKUP_FAILED))
        elif skill_ids:
            slots.append(_resolved(TutorContextSlot.SKILL, len(skill_ids)))
        else:
            slots.append(_absent(TutorContextSlot.SKILL, AbsenceCause.COVERAGE_GAP))
    else:
        slots.append(_absent(TutorContextSlot.CONCEPT, concept_cause))
        slots.append(_absent(TutorContextSlot.SKILL, concept_cause))

    # ④ 문제
    slots.append(
        _resolved(TutorContextSlot.PROBLEM, 1)
        if problem_present
        else _absent(TutorContextSlot.PROBLEM, AbsenceCause.NOT_SUPPLIED)
    )

    # ⑤ 학생 답안 — 공백만이면 없음. 길이는 노출하지 않는다(size=None).
    slots.append(
        _resolved(TutorContextSlot.STUDENT_ANSWER, None)
        if (student_answer or "").strip()
        else _absent(TutorContextSlot.STUDENT_ANSWER, AbsenceCause.NOT_SUPPLIED, size=None)
    )

    # ⑥ 풀이 기록 — 공백 단계는 세지 않는다.
    steps = [s for s in (solution_steps or ()) if s.strip()]
    slots.append(
        _resolved(TutorContextSlot.SOLUTION_RECORD, len(steps))
        if steps
        else _absent(TutorContextSlot.SOLUTION_RECORD, AbsenceCause.NOT_SUPPLIED)
    )

    # ⑦ 추정 Misconception — 이번 턴 매칭으로 큐레이션된 세트만(reactive). 0건은 '의심 없음'.
    slots.append(
        _resolved(TutorContextSlot.MISCONCEPTION, len(hypotheses))
        if hypotheses
        else _absent(TutorContextSlot.MISCONCEPTION, AbsenceCause.NONE_DETECTED)
    )

    # ⑧ Mastery — 서버 숙달 또는 클라 숙달 신호 중 하나라도 있으면 얻은 것.
    if server_mastery is not None or client_mastery_supplied:
        slots.append(_resolved(TutorContextSlot.MASTERY, 1))
    elif not mastery_enabled:
        slots.append(_absent(TutorContextSlot.MASTERY, AbsenceCause.SOURCE_DISABLED))
    elif concept_cause is not None:
        slots.append(_absent(TutorContextSlot.MASTERY, concept_cause))
    else:
        slots.append(_absent(TutorContextSlot.MASTERY, AbsenceCause.NO_HISTORY))

    # ⑨ Pedagogy Policy — 문항 개념의 교수법 팩. 없으면 base Polya 정책뿐임을 표기한다.
    if pack is not None:
        slots.append(_resolved(TutorContextSlot.PEDAGOGY_POLICY, 1))
    elif not pack_enabled:
        slots.append(_absent(TutorContextSlot.PEDAGOGY_POLICY, AbsenceCause.SOURCE_DISABLED))
    elif not problem_present:
        slots.append(_absent(TutorContextSlot.PEDAGOGY_POLICY, AbsenceCause.NO_PROBLEM_CONTEXT))
    else:
        slots.append(_absent(TutorContextSlot.PEDAGOGY_POLICY, AbsenceCause.COVERAGE_GAP))

    missing = [s.slot for s in slots if not s.resolved]
    return TutorContextManifest(
        tutor_invoked=False,
        slots=slots,
        missing=missing,
        not_delivered=[s.slot for s in slots if s.resolved],
        complete=not missing,
    )


def log_tutor_context(manifest: TutorContextManifest, *, seat: str) -> None:
    """누락·미전달을 로그 1줄로 남긴다 — `슬롯(원인)`과 미전달 슬롯명만, 값·원문은 없다.

    WARNING은 튜터가 불린 턴에서 시스템 결함 원인이 있을 때만. 그 밖의 누락·미전달은 INFO.
    둘 다 없으면 남기지 않는다.
    """
    if manifest.complete and not manifest.not_delivered:
        return
    # 형식은 `슬롯(원인)`이다 — `슬롯=원인`으로 쓰면 루트 로그 스크러버(`ops/log_scrubber.py`)가
    # `student_answer=…`를 학생 원문 필드로 보고 값 자리를 마스킹해 표기가 지워진다(10-20 실측).
    gaps = " ".join(
        f"{s.slot.value}({s.cause.value if s.cause is not None else '?'})"
        for s in manifest.slots
        if not s.resolved
    )
    defect = manifest.tutor_invoked and any(s.cause in SYSTEM_DEFECT_CAUSES for s in manifest.slots)
    logger.log(
        logging.WARNING if defect else logging.INFO,
        "튜터 context(seat=%s·tutor_invoked=%s) — 누락 %d/9: %s · 튜터 미전달 %d: %s",
        seat,
        manifest.tutor_invoked,
        len(manifest.missing),
        gaps or "-",
        len(manifest.not_delivered),
        " ".join(manifest.not_delivered_names()) or "-",
    )
