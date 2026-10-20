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

**P3-72 — 전달 경로 분리와 내용 요약(Kiki 결정 (가) 2026-10-20).** `delivered_to_tutor` 한 비트를
슬롯별 전달 경로(`delivery_paths`)로 나눈다 — `prompt`(LLM 프롬프트 문자열에 실림)·`private_tool`
(정책·하네스가 사적 보유, 프롬프트 미포함: θ·학생 답안·풀이 단계·가설 세트)·`output_guard`(출력
후처리 필터 — 교수법 팩 금지모드 가드가 *실제로 돈* 턴만). 빈 목록이 `none`이다.
`delivered_to_tutor`는 이 목록에서 파생된다(`bool(delivery_paths)` — 하위호환 필드 유지).

프롬프트에 싣는 것은 `TutorContentSummary` — 개념(code·이름)·스킬(수·이름 ≤ 5)·문제 *구조*
(형식·인지 수준·시각자료·조건 수)·교수법 팩(유형·금지 모드) 요약뿐이다. 이 타입에는 학생 개인 학습
데이터(θ·숙달도·그 파생 라벨)·학년·정답·해설·지문·보기를 담을 필드가 **없다**(`extra="forbid"`).
학생 상태·숙달 슬롯은 `prompt` 경로를 가질 수 없다 — 검증자가 거부한다(`PROMPT_FORBIDDEN_SLOTS`).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.schema.pedagogy_pack import PedagogyPack

__all__ = [
    "MAX_SKILL_NAMES",
    "PROMPT_FORBIDDEN_SLOTS",
    "PROMPT_KEY_SLOTS",
    "SYSTEM_DEFECT_CAUSES",
    "AbsenceCause",
    "ConceptBrief",
    "PackBrief",
    "ProblemBrief",
    "SkillBrief",
    "TutorContentSummary",
    "TutorContextManifest",
    "TutorContextSlot",
    "TutorContextSlotStatus",
    "TutorDeliveryPath",
    "TutorDeliveryReceipt",
    "build_tutor_content_summary",
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


class TutorDeliveryPath(str, Enum):
    """슬롯 값이 튜터에 닿은 경로(P3-72 ⑦). 슬롯 하나가 여러 경로를 가질 수 있다(빈 목록 = none)."""

    PROMPT = "prompt"
    """LLM 프롬프트 문자열에 실렸다 — 클라우드 좌석으로 나갈 수 있는 유일한 경로."""
    PRIVATE_TOOL = "private_tool"
    """정책·하네스가 사적으로 보유해 도구 실행에만 쓴다 — 프롬프트에 없다(LLM은 내용을 못 본다)."""
    OUTPUT_GUARD = "output_guard"
    """출력 후처리 필터가 실제로 소비했다 — 교수법 팩 금지모드 가드가 돈 턴만."""


_PATH_ORDER: dict[TutorDeliveryPath, int] = {p: i for i, p in enumerate(TutorDeliveryPath)}

PROMPT_FORBIDDEN_SLOTS: frozenset[TutorContextSlot] = frozenset(
    {TutorContextSlot.LEARNER_STATE, TutorContextSlot.MASTERY}
)
"""Kiki 결정 (가) 2026-10-20 — 학생 개인 학습 데이터(θ·숙달도·파생 라벨)는 프롬프트 경로 불가."""


class TutorContextSlotStatus(BaseModel):
    """슬롯 1개의 판정 — 값 없이 조회 여부·튜터 전달 여부·크기·원인만."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slot: TutorContextSlot = Field(description="9종 중 어느 슬롯인가.")
    resolved: bool = Field(description="이 턴에 서버 조회·요청으로 값을 얻었는가.")
    delivered_to_tutor: bool = Field(
        description=(
            "그 값이 튜터 러너 입력(프롬프트·정책 사적 보유값·초기 가설·금지모드 가드)에 실제로 "
            "실렸는가 — `delivery_paths`가 비지 않았는가와 같다(하위호환 필드). 튜터가 불리지 "
            "않은 턴은 전부 false다."
        )
    )
    delivery_paths: list[TutorDeliveryPath] = Field(
        default_factory=list,
        description=(
            "실제 전달 경로(P3-72) — prompt(LLM 프롬프트 문자열)·private_tool(사적 보유·프롬프트 "
            "미포함)·output_guard(출력 후처리 가드가 실제로 돈 턴). 빈 목록이면 none(미전달)."
        ),
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
        # P3-72: 전달 비트는 경로에서 파생된다 — 둘이 어긋나면 표기 자체가 거짓이다.
        if self.delivered_to_tutor != bool(self.delivery_paths):
            raise ValueError(f"{self.slot.value}: delivered_to_tutor가 delivery_paths와 어긋난다")
        if self.delivery_paths != sorted(set(self.delivery_paths), key=_PATH_ORDER.__getitem__):
            raise ValueError(f"{self.slot.value}: delivery_paths는 중복 없이 정해진 순서여야 한다")
        if self.slot in PROMPT_FORBIDDEN_SLOTS and TutorDeliveryPath.PROMPT in self.delivery_paths:
            raise ValueError(f"{self.slot.value}: 학생 학습 데이터는 프롬프트 경로 불가(결정 (가))")
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

    def prompt_names(self) -> list[str]:
        """LLM 프롬프트 문자열에 실제로 실린 슬롯 이름(P3-72 — 결정 (가) 집행 판정 좌석)."""
        return [s.slot.value for s in self.slots if TutorDeliveryPath.PROMPT in s.delivery_paths]

    def held_privately_names(self) -> list[str]:
        """전달은 됐으나 프롬프트에는 없는 슬롯 이름 — LLM은 그 *내용*을 볼 수 없다."""
        return [
            s.slot.value
            for s in self.slots
            if s.delivery_paths and TutorDeliveryPath.PROMPT not in s.delivery_paths
        ]

    def with_delivery(
        self,
        *,
        tutor_invoked: bool,
        paths: Mapping[TutorContextSlot, Iterable[TutorDeliveryPath]],
    ) -> TutorContextManifest:
        """튜터 호출 결과(슬롯별 실제 전달 경로)를 반영한 새 매니페스트.

        `paths`는 러너가 정책 객체·러너 입력·가드 실행 기록에서 계산한 값이다. 못 얻은 슬롯이
        전달됐다고 오면 판정 불일치이므로 표기하지 않고 WARNING을 남긴다(조용히 넘기지 않는다·
        요청은 깨지 않는다). 튜터를 부르지 않은 턴은 경로를 전부 비운다.
        """
        given: dict[TutorContextSlot, frozenset[TutorDeliveryPath]] = (
            {slot: frozenset(p) for slot, p in paths.items()} if tutor_invoked else {}
        )
        bogus = sorted(
            slot.value for slot, p in given.items() if p and not self.status_of(slot).resolved
        )
        if bogus:
            logger.warning("튜터 context 판정 불일치 — 못 얻은 슬롯이 전달됨으로 보고됨: %s", bogus)
        slots = []
        for s in self.slots:
            ordered = (
                sorted(given.get(s.slot, frozenset()), key=_PATH_ORDER.__getitem__)
                if s.resolved
                else []
            )
            # 슬롯을 명시적으로 재검증한다 — 아래 매니페스트 생성자도 슬롯 인스턴스를 재검증하지만
            # (2026-10-20 실측·뮤테이션 M24 등가), 결정 (가) 거부가 그 동작에 기대지 않게 둔다.
            slots.append(
                TutorContextSlotStatus.model_validate(
                    {
                        **s.model_dump(),
                        "delivered_to_tutor": bool(ordered),
                        "delivery_paths": ordered,
                    }
                )
            )
        return TutorContextManifest(
            tutor_invoked=tutor_invoked,
            slots=slots,
            missing=list(self.missing),
            not_delivered=[s.slot for s in slots if s.resolved and not s.delivered_to_tutor],
            complete=self.complete,
        )


@dataclass
class TutorDeliveryReceipt:
    """러너가 채우는 전달 영수증 — 턴이 끝난 *뒤* 실제 전달 경로를 반영한 매니페스트."""

    manifest: TutorContextManifest | None = None


# ──────────────────────────────────────────────────────────────────────────
# P3-72 — 튜터 프롬프트에 싣는 내용 요약(비식별·정답 0·학생 학습 데이터 0)
# ──────────────────────────────────────────────────────────────────────────
MAX_SKILL_NAMES = 5
"""스킬 이름 상한 — skill_id 오름차순 앞 5개만 싣고 총수는 `count`로 남긴다(선택 규칙·결정론)."""
_MAX_CODE_CHARS = 120
"""개념 code 상한 — 넘으면 code를 싣지 않는다(잘린 id는 다른 id다 — 도구 인자로 쓰이면 오류)."""
_MAX_NAME_CHARS = 60
"""개념·스킬 이름 상한 — 넘으면 잘라 '…'를 붙인다(표시명이라 잘라도 의미 손실만)."""
_MAX_FORBIDDEN_MODES = 8
"""팩 금지 모드 상한(폐쇄 어휘 토큰) — 팩 순서 앞 8개."""
_MAX_CONDITIONS = 20
"""조건 수 상한(발문 구조) — 넘으면 20으로 자른다."""


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ConceptBrief(BaseModel):
    """현재 Concept 요약 — 개념 그래프 code·한국어 이름(자체 저작 그래프·비식별)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str | None = Field(default=None, max_length=_MAX_CODE_CHARS)
    name: str = Field(min_length=1, max_length=_MAX_NAME_CHARS)


class SkillBrief(BaseModel):
    """현재 Skill 요약 — 총수와 이름(≤ 5·skill_id 오름차순)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    count: int = Field(ge=1)
    names: list[str] = Field(default_factory=list, max_length=MAX_SKILL_NAMES)


class ProblemBrief(BaseModel):
    """문제 *구조* 요약 — 지문·보기·정답·해설·오답 선지 매핑은 담을 자리가 없다(정답 억제 계약).

    지문을 싣지 않는 이유 둘: ① 정답 억제 — 지문·보기·정답 형식은 정답 경로를 좁힌다 ② 데이터 등급 —
    튜터 호출은 `SELF_AUTHORED_CORPUS`로 라우팅되는데(`wh1_llm_policy._routing_request`) 문항
    본문은 출처별 라이선스가 따로 있어 그 선언을 거짓으로 만든다. 구조 메타는 우리가 붙인 분류다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    question_format: str | None = None
    bloom_level: str | None = None
    has_visual: bool = False
    condition_count: int | None = Field(default=None, ge=0, le=_MAX_CONDITIONS)


class PackBrief(BaseModel):
    """교수법 팩 요약 — 지식 유형·스텁 여부·금지 모드(폐쇄 어휘). 발문 템플릿 본문은 싣지 않는다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    k_type: str = Field(min_length=1)
    is_stub: bool = False
    forbidden_modes: list[str] = Field(default_factory=list, max_length=_MAX_FORBIDDEN_MODES)


PROMPT_KEY_SLOTS: dict[str, TutorContextSlot] = {
    "concept": TutorContextSlot.CONCEPT,
    "skills": TutorContextSlot.SKILL,
    "problem": TutorContextSlot.PROBLEM,
    "pedagogy_policy": TutorContextSlot.PEDAGOGY_POLICY,
}
"""프롬프트 요약 키 → 슬롯. 정책은 *실제로 렌더한* 키에서 prompt 경로를 계산한다(추정 금지)."""


class TutorContentSummary(BaseModel):
    """튜터 프롬프트에 싣는 슬롯 내용 요약(P3-72·Kiki 결정 (가)).

    필드는 개념·스킬·문제 구조·교수법 팩 네 가지뿐이다. 학생 상태(θ·학년)·숙달도·답안·풀이는
    담을 필드가 없다(`extra="forbid"`) — 그 값은 이 타입을 거쳐 프롬프트에 실릴 수 없다.
    크기 상한(개념 1·스킬 이름 5·금지 모드 8·문자열 길이)이 고정이라 프롬프트 압력은 상수다 —
    그래서 토큰 예산 루프가 이 요약을 자르지 않는다(`wh1_llm_policy._build_prompt`).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    concept: ConceptBrief | None = None
    skills: SkillBrief | None = None
    problem: ProblemBrief | None = None
    pedagogy_policy: PackBrief | None = None

    def prompt_fields(self) -> dict[str, object]:
        """프롬프트 요약에 합칠 키 → 값(비어 있는 섹션은 키 자체가 없다)."""
        out: dict[str, object] = {}
        for key in PROMPT_KEY_SLOTS:
            section = getattr(self, key)
            if section is not None:
                out[key] = section.model_dump(exclude_none=True)
        return out

    def node_count(self) -> int:
        """Minimal Reasoning Subgraph 노드 회계 — 개념 1 + 실린 스킬 이름 수."""
        return int(self.concept is not None) + (len(self.skills.names) if self.skills else 0)


def build_tutor_content_summary(
    *,
    concept_code: str | None,
    concept_name: str | None,
    skills: Sequence[tuple[str, str]],
    skill_total: int,
    problem: ProblemBrief | None,
    pack: PedagogyPack | None,
) -> TutorContentSummary:
    """핸들러가 조회한 행으로 프롬프트 요약을 만든다(순수·결정론). 상한을 넘으면 선택 규칙을 쓴다.

    선택 규칙(보고서 §3): 개념 code > 120자면 code 제외·이름 > 60자면 자름 · 스킬은 skill_id
    오름차순 앞 5개 이름만(총수는 `count`) · 금지 모드는 팩 순서 앞 8개 · 조건 수는 20에서 자름.
    """
    concept: ConceptBrief | None = None
    if concept_name and concept_name.strip():
        code = concept_code.strip() if concept_code else None
        concept = ConceptBrief(
            code=code if code and len(code) <= _MAX_CODE_CHARS else None,
            name=_clip(concept_name, _MAX_NAME_CHARS),
        )
    skill_brief: SkillBrief | None = None
    if skill_total > 0:
        chosen = sorted(skills, key=lambda pair: pair[0])[:MAX_SKILL_NAMES]
        skill_brief = SkillBrief(
            count=skill_total,
            names=[_clip(name, _MAX_NAME_CHARS) for _, name in chosen if name.strip()],
        )
    pack_brief: PackBrief | None = None
    if pack is not None:
        pack_brief = PackBrief(
            k_type=str(getattr(pack.k_type, "value", pack.k_type)),
            is_stub=pack.is_stub,
            forbidden_modes=list(pack.forbidden_modes)[:_MAX_FORBIDDEN_MODES],
        )
    return TutorContentSummary(
        concept=concept, skills=skill_brief, problem=problem, pedagogy_policy=pack_brief
    )


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
        "튜터 context(seat=%s·tutor_invoked=%s) — 누락 %d/9: %s · 튜터 미전달 %d: %s"
        " · 프롬프트 %d: %s",
        seat,
        manifest.tutor_invoked,
        len(manifest.missing),
        gaps or "-",
        len(manifest.not_delivered),
        " ".join(manifest.not_delivered_names()) or "-",
        len(manifest.prompt_names()),
        " ".join(manifest.prompt_names()) or "-",
    )
