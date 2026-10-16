"""Problem 메타데이터 7필드·문제 유형 6슬롯 계약 (P3-04).

지시문 [07] P3-04 ①②의 **정의 한 곳**이다. 7필드가 무엇이고 언제 "있다"고 치는지, 6슬롯이 무엇이고
태그로 어떻게 표기하는지를 이 모듈이 소유한다. 집행은 다른 모듈이 한다(정본화 ≠ 집행):

  · 저장(발행) 시점 — `l3/problem_publish_gate.py` PUBLISH 게이트가 이 판정을 부른다.
  · CI 시점       — `l1/standards/phase3_problem_metadata.py` CLI가 코퍼스 전수에 이 판정을 건다.

## 7필드 ↔ 기존 스키마 대조 (개명하지 않고 매핑한다 — 지시문 [07] ①)

- difficulty — 증거 `difficulty` · 저장 `problem.difficulty_overall`
- skill — 증거 `skill_ids` · 문제유형→skill(코퍼스) · 개념→`behavior_skills`(DB)
- concept — 증거 `concept_ids` · `problem_concept`(PRIMARY) · 코퍼스 `concepts[PRIMARY]`
- solution — 증거 `solution_text` · `problem.answer_explanation`
- answer — 증거 `answer` · `problem.answer`
- misconception_signature — 증거 `own_misconception_ids`(`problem.distractor_map`)와
  `concept_misconception_ids`(소속 개념에 등록된 오개념)
- hint_strategy — 증거 `verified_hint_count` · `hints`(problem_id · verified=true)

상세 대조표·정의 근거는 `docs/standards/problem_metadata_contract.md`.

`SignaturePattern`(수능 시그니처 패턴 10종)은 오개념 서명이 **아니다** — 이름만 닮았다. 매핑에
쓰지 않는다.

## 판정은 3상태다 — 모른다 ≠ 있다

`PRESENT`(있음) · `MISSING`(측정했고 비어 있음) · `UNKNOWN`(측정하지 못함). 증거가 `None`이면
UNKNOWN이다. **UNKNOWN은 통과가 아니다** — `MetadataVerdict.complete`는 7필드가 전부 PRESENT일
때만 참이다. 측정 도구가 죽었을 때 "비어 있지 않으니 통과"로 위장되는 길을 막는다(CLAUDE.md
"모른다 ≠ 아니다" · "측정 실패를 0건 통과로 위장하지 않는다").

## 오개념 서명 정의 (Kiki 결정 2026-10-14 · 슬롯별로 다르게)

- `misconception_trigger` 슬롯 문항 — **문항 자체에 연결된 오개념**(`own_*`)이 있어야 한다.
  지시문 [08] ③ "신호 없는 오개념 유발 문제는 개수에 세지 않는다"와 같은 규칙이다.
- 그 밖의 슬롯·슬롯 미지정 문항 — 문항 자체 연결이 있거나 **소속 개념에 등록된 오개념**
  (`concept_misconception_ids`)이 있으면 인정한다. 이 인정은 상속이라 문항 고유의 보증이 아니다 —
  `MetadataVerdict.misconception_source`에 출처를 남겨 "상속만으로 채워진 비율"을 따로 셀 수 있게
  한다. 출처는 규칙을 **충족시킨** 경우에만 채워진다(거부된 증거는 None).
- 슬롯을 알 수 없으면(`slots is None`) 상속만으로는 인정하지 않는다 — 트리거 슬롯인지 모르는
  채로 완화된 규칙을 적용하지 않는다.

## 힌트 전략 정의 (Kiki 결정 2026-10-14)

그 문항의 `verified=true` 힌트가 1개 이상이면 PRESENT. 새 컬럼을 만들지 않고 기존 `hints`
좌석을 읽는다. 파일 코퍼스에는 문항별 힌트 정보가 없으므로 코퍼스 쪽 증거는 `None`(UNKNOWN)이다 —
P3-02 계측기가 힌트 연결을 "측정 불가"로 보고하는 것과 같은 정직한 처리다.

## 6슬롯 태그

슬롯은 Problem의 **태그(데이터)** 다. 기존 `tags` 컬럼에 `p3-slot:<id>`로 적는다(새 컬럼 없음 —
P3-03 은행 504건이 이미 이 표기를 쓴다). 6개 id는 범위 명세 `quantity_targets.slots`와 같아야
하며, 그 동치는 `tests/backend/schema/test_problem_metadata.py`가 양방향으로 잰다.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class ProblemMetadataField(str, Enum):
    """Problem 필수 7필드 — 값은 범위 명세 `completeness.problem_required_fields`와 같다."""

    DIFFICULTY = "difficulty"
    SKILL = "skill"
    CONCEPT = "concept"
    SOLUTION = "solution"
    ANSWER = "answer"
    MISCONCEPTION_SIGNATURE = "misconception_signature"
    HINT_STRATEGY = "hint_strategy"


class ProblemSlot(str, Enum):
    """핵심 Concept마다 채울 문제 유형 6슬롯 — 값은 범위 명세 `quantity_targets.slots`의 id."""

    REPRESENTATIVE = "representative"
    """대표."""

    BASIC = "basic"
    """기본."""

    APPLIED = "applied"
    """응용."""

    MISCONCEPTION_TRIGGER = "misconception_trigger"
    """오개념 유발 — 문항 자체에 연결된 오개념 서명이 있을 때만 센다."""

    DIAGNOSTIC = "diagnostic"
    """진단."""

    MASTERY_CHECK = "mastery_check"
    """숙련도 확인."""


class FieldState(str, Enum):
    """필드 1개의 판정 — 3상태. UNKNOWN은 통과가 아니다."""

    PRESENT = "present"
    MISSING = "missing"
    UNKNOWN = "unknown"


# ──────────────────────────────────────────────────────────────────────────
# 슬롯 태그
# ──────────────────────────────────────────────────────────────────────────
SLOT_TAG_PREFIX = "p3-slot:"


def slot_tag(slot: ProblemSlot) -> str:
    """슬롯 → 태그 문자열 (`p3-slot:representative`)."""
    return SLOT_TAG_PREFIX + slot.value


@dataclass(frozen=True)
class SlotTags:
    """태그 목록에서 읽은 슬롯. `unknown`은 접두는 맞는데 6개 id에 없는 태그(오타 탐지)."""

    slots: frozenset[ProblemSlot]
    unknown: tuple[str, ...]


def parse_slot_tags(tags: Iterable[str] | None) -> SlotTags:
    """`tags`에서 슬롯을 읽는다. 알 수 없는 슬롯 id는 버리지 않고 `unknown`에 남긴다.

    오타 난 태그(`p3-slot:aplied`)를 조용히 무시하면 그 문항은 슬롯이 없는 문항으로 보이고 슬롯
    지표가 이유 없이 모자란다 — 그래서 보이게 남긴다.
    """
    known = {slot.value: slot for slot in ProblemSlot}
    found: set[ProblemSlot] = set()
    unknown: list[str] = []
    for tag in tags or ():
        if not isinstance(tag, str) or not tag.startswith(SLOT_TAG_PREFIX):
            continue
        ident = tag[len(SLOT_TAG_PREFIX) :]
        if ident in known:
            found.add(known[ident])
        else:
            unknown.append(tag)
    return SlotTags(slots=frozenset(found), unknown=tuple(unknown))


# ──────────────────────────────────────────────────────────────────────────
# 증거 — 측정한 사실. None = 측정하지 못함
# ──────────────────────────────────────────────────────────────────────────
#: 난이도 컬럼을 읽었는데 값이 없을 때(NULL) 쓰는 값 — "측정했고 비어 있음". `None`과 다르다.
EMPTY_DIFFICULTY: float = float("nan")


@dataclass(frozen=True)
class ProblemMetadataEvidence:
    """문항 1건에서 측정한 사실. 모든 속성의 기본값은 None(= 측정하지 못함)이다.

    빈 튜플·빈 문자열은 "측정했고 비어 있다"이고 `None`은 "측정하지 못했다"다 — 둘을 같게
    다루면 측정 도구가 죽은 날 전부 "비어 있다"로 보이거나 전부 "있다"로 위장된다.

    `difficulty`는 부동소수라 "비어 있음"을 표현할 값이 없다 — 컬럼을 읽었는데 NULL이었다면
    `EMPTY_DIFFICULTY`(NaN)를 넣는다. `None`을 넣으면 "측정하지 못함"이 되어 사유가 틀려진다.
    """

    difficulty: float | None = None
    answer: str | None = None
    solution_text: str | None = None
    concept_ids: tuple[str, ...] | None = None
    skill_ids: tuple[str, ...] | None = None
    own_misconception_ids: tuple[str, ...] | None = None
    concept_misconception_ids: tuple[str, ...] | None = None
    verified_hint_count: int | None = None
    slots: frozenset[ProblemSlot] | None = None


#: 필드 → 그 필드를 판정하는 증거 속성들. 문서 대조표의 코드판이며 누락 주입 테스트가 이것으로
#: "그 필드만" 비운다. `slots`는 오개념 서명 판정의 보조 입력이라 별도 필드가 아니다.
FIELD_EVIDENCE: Mapping[ProblemMetadataField, tuple[str, ...]] = MappingProxyType(
    {
        ProblemMetadataField.DIFFICULTY: ("difficulty",),
        ProblemMetadataField.SKILL: ("skill_ids",),
        ProblemMetadataField.CONCEPT: ("concept_ids",),
        ProblemMetadataField.SOLUTION: ("solution_text",),
        ProblemMetadataField.ANSWER: ("answer",),
        ProblemMetadataField.MISCONCEPTION_SIGNATURE: (
            "own_misconception_ids",
            "concept_misconception_ids",
        ),
        ProblemMetadataField.HINT_STRATEGY: ("verified_hint_count",),
    }
)


# ──────────────────────────────────────────────────────────────────────────
# 필드별 판정 — 정의는 여기 한 곳에만 있다
# ──────────────────────────────────────────────────────────────────────────
def _text_state(value: str | None) -> FieldState:
    if value is None:
        return FieldState.UNKNOWN
    return FieldState.PRESENT if value.strip() else FieldState.MISSING


def _links_state(values: tuple[str, ...] | None) -> FieldState:
    if values is None:
        return FieldState.UNKNOWN
    return FieldState.PRESENT if any(v.strip() for v in values) else FieldState.MISSING


def _difficulty_state(ev: ProblemMetadataEvidence) -> FieldState:
    value = ev.difficulty
    if value is None:
        return FieldState.UNKNOWN
    # bool은 int의 하위형이라 True가 1.0으로 통과한다 — 난이도로 인정하지 않는다.
    if isinstance(value, bool):
        return FieldState.MISSING
    try:
        finite = math.isfinite(float(value))
    except (TypeError, ValueError):
        return FieldState.MISSING
    return FieldState.PRESENT if finite else FieldState.MISSING


def _hint_state(ev: ProblemMetadataEvidence) -> FieldState:
    count = ev.verified_hint_count
    if count is None:
        return FieldState.UNKNOWN
    return FieldState.PRESENT if count >= 1 else FieldState.MISSING


def _has(values: tuple[str, ...] | None) -> bool:
    return values is not None and any(v.strip() for v in values)


def _evidence_source(ev: ProblemMetadataEvidence) -> str | None:
    """증거가 있는 출처 — 규칙을 충족했는지와 무관하다(충족 여부는 `_misconception_state`)."""
    if _has(ev.own_misconception_ids):
        return "own"
    if _has(ev.concept_misconception_ids):
        return "concept"
    return None


def _misconception_state(ev: ProblemMetadataEvidence) -> FieldState:
    own, inherited, slots = ev.own_misconception_ids, ev.concept_misconception_ids, ev.slots
    if _has(own):
        return FieldState.PRESENT  # 문항 자체 연결은 어느 슬롯의 규칙도 만족한다.
    if slots is not None and ProblemSlot.MISCONCEPTION_TRIGGER in slots:
        # 트리거 슬롯: 상속으로는 안 된다. 문항 자체 증거를 못 쟀으면 모르는 것이다.
        return FieldState.MISSING if own is not None else FieldState.UNKNOWN
    if _has(inherited):
        # 상속 인정은 "트리거 슬롯이 아님"을 알 때만이다. 슬롯을 모르면 완화 규칙을 쓰지 않는다.
        return FieldState.PRESENT if slots is not None else FieldState.UNKNOWN
    if own is not None and inherited is not None:
        return FieldState.MISSING  # 두 출처를 다 쟀고 둘 다 비었다 — 슬롯과 무관하게 없다.
    return FieldState.UNKNOWN


_JUDGES: Mapping[ProblemMetadataField, Callable[[ProblemMetadataEvidence], FieldState]] = (
    MappingProxyType(
        {
            ProblemMetadataField.DIFFICULTY: _difficulty_state,
            ProblemMetadataField.SKILL: lambda ev: _links_state(ev.skill_ids),
            ProblemMetadataField.CONCEPT: lambda ev: _links_state(ev.concept_ids),
            ProblemMetadataField.SOLUTION: lambda ev: _text_state(ev.solution_text),
            ProblemMetadataField.ANSWER: lambda ev: _text_state(ev.answer),
            ProblemMetadataField.MISCONCEPTION_SIGNATURE: _misconception_state,
            ProblemMetadataField.HINT_STRATEGY: _hint_state,
        }
    )
)

# 필드를 하나 추가하고 판정을 안 달면 그 필드는 조용히 검사에서 빠진다 — 불러오는 순간 막는다.
if set(_JUDGES) != set(ProblemMetadataField) or set(FIELD_EVIDENCE) != set(ProblemMetadataField):
    raise RuntimeError("ProblemMetadataField와 판정·증거 대조표가 어긋났다 — 필드를 빠뜨렸다")


# ──────────────────────────────────────────────────────────────────────────
# 판정 결과
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class MetadataVerdict:
    """7필드 판정 결과. `complete`는 7필드가 전부 PRESENT일 때만 참이다."""

    states: Mapping[ProblemMetadataField, FieldState]
    misconception_source: str | None

    @property
    def missing(self) -> tuple[ProblemMetadataField, ...]:
        return tuple(f for f in ProblemMetadataField if self.states[f] is FieldState.MISSING)

    @property
    def unknown(self) -> tuple[ProblemMetadataField, ...]:
        return tuple(f for f in ProblemMetadataField if self.states[f] is FieldState.UNKNOWN)

    @property
    def complete(self) -> bool:
        return all(self.states[f] is FieldState.PRESENT for f in ProblemMetadataField)

    def failures(self) -> list[str]:
        """게이트 실패 사유 문장들 — 필드 순서 고정, 없음/측정 못함을 구분해 적는다."""
        out: list[str] = []
        for f in ProblemMetadataField:
            state = self.states[f]
            if state is FieldState.MISSING:
                out.append(f"{f.value}: 비어 있다")
            elif state is FieldState.UNKNOWN:
                out.append(f"{f.value}: 측정하지 못했다")
        return out


def evaluate_metadata(evidence: ProblemMetadataEvidence) -> MetadataVerdict:
    """증거 → 7필드 판정. 7필드를 **전부** 판정한다(첫 실패에서 멈추지 않는다)."""
    states = {f: _JUDGES[f](evidence) for f in ProblemMetadataField}
    # 출처는 규칙을 **충족시킨** 경우에만 보고한다. 트리거 슬롯에서 거부된 상속 증거가 "concept"로
    # 보고되면 "상속만으로 채워진 비율"을 세는 쪽이 거부된 문항까지 센다.
    satisfied = states[ProblemMetadataField.MISCONCEPTION_SIGNATURE] is FieldState.PRESENT
    return MetadataVerdict(
        states=MappingProxyType(states),
        misconception_source=_evidence_source(evidence) if satisfied else None,
    )


__all__ = [
    "EMPTY_DIFFICULTY",
    "FIELD_EVIDENCE",
    "FieldState",
    "MetadataVerdict",
    "ProblemMetadataEvidence",
    "ProblemMetadataField",
    "ProblemSlot",
    "SLOT_TAG_PREFIX",
    "SlotTags",
    "evaluate_metadata",
    "parse_slot_tags",
    "slot_tag",
]
