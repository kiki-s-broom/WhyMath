"""Phase 3 미적분Ⅰ '미분' 대단원 결정론 문항 생성기 공용 기반 — P3-03(결정론·LLM 0).

`data/corpus/phase3_scope_v1/scope_spec.yaml`의 핵심 개념 10개 중 승인 문항이 0건이던 개념을
채우기 위한 **개념별 생성기**(`p3_diff_*_skeleton_generator`)가 공유하는 뼈대다. 개념마다 생성기
파일 1개를 두고, 이 모듈이 슬롯 구조·문항 조립·후보 번들 구성을 맡는다. 배치(`harness/
p3_calculus1_diff_batch`)는 생성기 등록부(`GENERATORS`)만 알면 되므로, 새 개념은 생성기 파일 1개
+ 등록부 1줄로 추가된다.

슬롯(명세 `quantity_targets.slots` 6종)
---------------------------------------
대표·기본·응용·오개념 유발·진단·숙련도 확인. 생성기 인스턴스는 **슬롯 1개**를 담당한다
(`generator_cls(slot=...)`). 슬롯마다 문항이 가진 오개념 연결 집합이 균일해야(오개념 유발 슬롯은
정확히 {kebab}, 나머지는 공집합) 수용 게이트의 동등성 점수(오개념 Jaccard)가 문항별로 1.0이 된다 —
`items()`가 이 불변식을 빌드 시점에 fail-loud로 강제한다.

문제유형·스킬 연결(중요)
-----------------------
문항의 `problem_type_codes`는 *문항이 실제로 요구하는 인지 행동*을 정직하게 단다. 계측기
(`l1/standards/phase3_coverage`)는 문제유형 → 행동 스킬 → 개념 스킬 겹침으로 '스킬 연결'을
세므로, 개념에 따라 일부 유형은 연결로 세어지지 않는다(예: [12미적Ⅰ-02-03]의 스킬과
`ptype.evaluate-expression`은 겹치지 않는다). 겹치게 하려고 유형을 거짓으로 달지 않는다 — 대신
겹치는 유형(`ptype.solve-for-unknown` 등)의 *진짜* 문항을 개념마다 충분히 만든다.

review_status
-------------
이 모듈은 `review_status` 키를 **쓰지 않는다**(None/키 부재 유지). 승인은 감사 표본 경로의 몫이며,
저작 도구가 승인을 대신 쓰면 "승인 문항 0건"이라는 계측이 무의미해진다.

7계층: L3 지역(LLM 0). schema·동일 패키지·L1(ConceptTag)만 import(L4 참조 0). 오개념 id(kebab)는
이미 정본 카탈로그에 실재하는 것만 문자열로 받는다(신규 id 신설 0 — 참조 무결성은 L4 검증자·테스트).
"""

from __future__ import annotations

import hashlib
import random
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import ClassVar, Final, Literal

from whymath_backend.l1.problem_bank.populate import ConceptTag
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.generator import CandidateProblem
from whymath_backend.l3.equivalent.p3_diff_expr import anchor_curve_function
from whymath_backend.schema.enums import (
    AnswerFormat,
    Curriculum,
    GenerationType,
    LicenseType,
    QuestionFormat,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import DistractorEntry, Problem
from whymath_backend.schema.provenance import ContentProvenance

__all__ = [
    "SLOT_IDS",
    "SLOT_NAMES_KO",
    "SlotId",
    "ChoiceEntry",
    "DiffItem",
    "Frame",
    "P3DiffSlotGenerator",
    "answer_format_for",
    "build_choices",
    "round_robin_items",
    "seeded_order",
    "skeleton_of",
]

#: 슬롯 id 타입 — `Literal`로 두어야 형제 생성기 공간 겹침 감사기(`harness/
#: generator_space_overlap_audit`, QUAL-08)가 생성자의 필수 인자 `slot`을 *모든 값으로*
#: 인스턴스화해 6슬롯 공간을 각각 잰다(일반 `str`이면 감사기가 채울 수 없어 '측정 불가 클래스'로
#: 게이트가 깨진다).
SlotId = Literal[
    "representative",
    "basic",
    "applied",
    "misconception_trigger",
    "diagnostic",
    "mastery_check",
]

#: 명세 `quantity_targets.slots`의 6종 id(순서 고정 — 배치 출력 순서의 단일 원천).
SLOT_IDS: Final[tuple[SlotId, ...]] = (
    "representative",
    "basic",
    "applied",
    "misconception_trigger",
    "diagnostic",
    "mastery_check",
)

SLOT_NAMES_KO: Final[Mapping[str, str]] = {
    "representative": "대표",
    "basic": "기본",
    "applied": "응용",
    "misconception_trigger": "오개념 유발",
    "diagnostic": "진단",
    "mastery_check": "숙련도 확인",
}

#: 슬롯 태그 접두 — `Problem.tags`에 `p3-slot:<slot id>`로 남긴다(슬롯 분포 계측의 읽기 원천).
SLOT_TAG_PREFIX: Final = "p3-slot:"

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


_RATIONAL_RE = re.compile(r"-?\d+(?:/\d+)?")


def answer_format_for(answer_text: str) -> AnswerFormat:
    """정답 표기에서 `answer_format`을 정한다 — 은행 전체의 *단일* 규칙(2차 감사 결함 교정).

    양의 정수 → 자연수, 정수가 아닌 유리수 → 분수, 그 밖(0·음의 정수·무리수 등) → 실수. 1차
    은행은 틀마다 형식을 손으로 박아 '자연수인데 정답 0'(모순)·'실수인데 정답 8'(불일치)이
    섞였다. `_validate_slot`이 문항마다 이 규칙과 대조해 어긋나면 빌드를 멈춘다.
    """
    text = answer_text.strip()
    if _RATIONAL_RE.fullmatch(text):
        if "/" in text:
            numerator, denominator = (int(v) for v in text.split("/"))
            if numerator % denominator:
                return AnswerFormat.분수
            text = str(numerator // denominator)
        return AnswerFormat.자연수 if int(text) > 0 else AnswerFormat.실수
    return AnswerFormat.실수


def skeleton_of(question_text: str) -> str:
    """문면 골격 — 숫자를 `#`로 접고 공백을 정규화한 문면.

    명세 `quantity_targets.distinct_basis`("문면 골격(숫자를 #로 접은 문면)의 고유 수")와
    `scripts/analysis/p3_01_scope_inventory.py`의 실측 정의와 같다(정의를 한 곳에 맞춘다).
    """
    return " ".join(_NUMBER_RE.sub("#", question_text).split())


def seeded_order[T](seed: str, values: Sequence[T]) -> tuple[T, ...]:
    """결정론 셔플 — 문자열 시드(`random.Random(str)`은 프로세스·플랫폼 무관하게 같은 순열을 낸다).

    틀의 파라미터 후보열을 시드 순서로 섞어 같은 틀의 문항이 파라미터 공간에 고르게 흩어지게 한다.
    """
    ordered = list(values)
    random.Random(seed).shuffle(ordered)
    return tuple(ordered)


@dataclass(frozen=True, slots=True)
class DiffItem:
    """문항 1건의 전 재료 — 수치·표기의 단일 진실 원천(생성기 빌더가 만들고 `_assemble`이 소비)."""

    slot: str
    frame_id: str
    question_text: str
    answer_text: str
    explanation: str
    #: Tier1 검산 조건 — 문자열 1개 또는 연립(튜플·AND).
    conditions: str | tuple[str, ...]
    #: Tier1 치환맵 (변수, 값) 쌍.
    answer_map: tuple[tuple[str, str], ...]
    problem_type_code: str
    answer_format: AnswerFormat
    choices: tuple[str, ...] | None = None
    #: (오답 선지 인덱스, 오개념 kebab) — 카탈로그에 매핑되는 오답만(미매핑 오답은 싣지 않는다).
    distractors: tuple[tuple[int, str], ...] = ()

    @property
    def misconception_ids(self) -> frozenset[str]:
        return frozenset(kebab for _, kebab in self.distractors)


@dataclass(frozen=True, slots=True)
class ChoiceEntry:
    """객관식 선지 후보 1개 — 표기·오개념 귀속(없으면 None)·정답 여부·정렬 키(None이면 섞는다)."""

    text: str
    kebab: str | None = None
    is_correct: bool = False
    sort_key: float | None = None


def build_choices(
    entries: Sequence[ChoiceEntry], *, shuffle_seed: str
) -> tuple[tuple[str, ...], str, tuple[tuple[int, str], ...]]:
    """선지 4개 조립 → (선지 표기, 정답 표기, 오답 귀속 (인덱스, kebab)).

    · 표기가 서로 달라야 하고(충돌이면 ValueError — 빌더가 건너뛴다) 정답은 정확히 1개.
    · 모든 선지에 `sort_key`가 있으면 오름차순 정렬(수치 선지 관례), 하나라도 None이면
      `shuffle_seed`로 결정론 셔플(식 선지 — 정답 위치가 편향되지 않게).
    """
    if len(entries) != 4:
        raise ValueError(f"선지는 4개여야 한다: {len(entries)}")
    if len({e.text for e in entries}) != 4:
        raise ValueError("선지 표기 충돌")
    if sum(1 for e in entries if e.is_correct) != 1:
        raise ValueError("정답 선지는 정확히 1개여야 한다")
    ordered = list(entries)
    if all(e.sort_key is not None for e in ordered):
        ordered.sort(key=lambda e: float(e.sort_key if e.sort_key is not None else 0.0))
    else:
        random.Random(shuffle_seed).shuffle(ordered)
    choices = tuple(e.text for e in ordered)
    answer = next(e.text for e in ordered if e.is_correct)
    distractors = tuple((index, e.kebab) for index, e in enumerate(ordered) if e.kebab is not None)
    return choices, answer, distractors


@dataclass(frozen=True, slots=True)
class Frame:
    """슬롯 안의 문면 틀 1종 — 파라미터 후보열과 빌더(파라미터 → 문항|None).

    `params`는 이미 결정론 순서로 정렬된 후보열이다(`round_robin_items`가 앞에서부터 소비).
    빌더가 None을 내면(예: 선지 충돌·답 범위 이탈) 그 파라미터를 조용히 건너뛴다 — 건너뛴 만큼
    다음 파라미터로 채우므로, 빌더의 None은 '이 입력은 이 틀에 부적합'이라는 뜻일 뿐이다.
    """

    frame_id: str
    params: tuple[tuple[object, ...], ...]
    build: Callable[[tuple[object, ...]], DiffItem | None]


def _condition_key(item: DiffItem) -> str:
    cond = item.conditions
    return cond if isinstance(cond, str) else "&&".join(cond)


def round_robin_items(
    frames: Sequence[Frame], count: int, *, claimed: set[str] | None = None
) -> list[DiffItem]:
    """틀을 돌아가며(라운드로빈) 문항을 모아 `count`건을 채운다 — 한 틀이 몰리지 않게 한다.

    중복 제거 키는 *검산 조건*과 *발문* 둘이다: 같은 수학 실체를 다른 틀로 두 번 내지 않는다
    (같은 은행 안 실체 중복 방지 — QUAL-07 교훈). 후보가 모자라 `count`에 못 미치면 있는 만큼만 낸다
    (호출자·테스트가 건수를 단언한다 — 침묵 절삭이 아니다).

    `claimed`는 개념 안 *슬롯 사이* 검산 조건 중복을 막는 공유 집합이다 — 앞 슬롯이 가져간 조건은 뒤
    슬롯이 못 쓰고(다음 파라미터로 넘어간다), 이 함수가 뽑은 조건은 집합에 더해진다.
    """
    cursor = {frame.frame_id: 0 for frame in frames}
    seen_conditions: set[str] = claimed if claimed is not None else set()
    seen_texts: set[str] = set()
    out: list[DiffItem] = []
    progressed = True
    while len(out) < count and progressed:
        progressed = False
        for frame in frames:
            if len(out) >= count:
                break
            while cursor[frame.frame_id] < len(frame.params):
                params = frame.params[cursor[frame.frame_id]]
                cursor[frame.frame_id] += 1
                item = frame.build(params)
                if item is None:
                    continue
                key = _condition_key(item)
                if key in seen_conditions or item.question_text in seen_texts:
                    continue
                seen_conditions.add(key)
                seen_texts.add(item.question_text)
                out.append(item)
                progressed = True
                break
    return out


_ITEM_CACHE: dict[tuple[type, str], tuple[DiffItem, ...]] = {}


class P3DiffSlotGenerator:
    """개념 1개 × 슬롯 1개를 담당하는 결정론 생성기 베이스(`EquivalentProblemGenerator` 좌석).

    하위 클래스가 채울 것(클래스 변수 + `_slot_items`):
      · `standard_code`·`concept_src_id`·`unit_code`·`slug_prefix` — 개념 식별.
      · `slot_difficulty` — 슬롯별 종합 난이도(spec 난이도와 같은 값을 쓴다).
      · `slot_count` — 슬롯당 목표 문항 수.
      · `_slot_items(slot)` — 그 슬롯의 문항 목록(결정론).

    `run_equivalent_generation`을 `signature_index=None`으로 호출해야 한다(구조 dedup이 조건식을
    해값으로 정규화하므로 서로 다른 문항이 같은 값을 내면 오탐 — 선례 생성기들과 동일 사유).
    """

    standard_code: ClassVar[str]
    concept_src_id: ClassVar[str]
    unit_code: ClassVar[str]
    slug_prefix: ClassVar[str]
    concept_relevance: ClassVar[float] = 0.95
    slot_difficulty: ClassVar[Mapping[str, float]]
    slot_count: ClassVar[int] = 12

    def __init__(self, *, slot: SlotId, skip_conditions: AbstractSet[str] | None = None) -> None:
        if slot not in SLOT_IDS:
            raise ValueError(f"알 수 없는 슬롯: {slot!r}")
        self._slot = slot
        self._items = type(self).items(slot)
        self._index = 0
        self._skip = skip_conditions

    # ── 하위 클래스 계약 ────────────────────────────────────────────────
    @classmethod
    def _slot_items(cls, slot: str, claimed: set[str]) -> list[DiffItem]:
        """슬롯 문항 목록 — `round_robin_items(..., claimed=claimed)`를 그대로 호출하면 된다."""
        raise NotImplementedError

    # ── 슬롯 문항·스펙(배치가 소비) ─────────────────────────────────────
    @classmethod
    def items(cls, slot: str) -> tuple[DiffItem, ...]:
        """슬롯의 전 문항(캐시) — 슬롯 불변식을 빌드 시점에 강제한다."""
        key = (cls, slot)
        cached = _ITEM_CACHE.get(key)
        if cached is not None:
            return cached
        # 호출 순서와 무관하게 결정론이도록 6슬롯을 SLOT_IDS 순서로 한 번에 빌드한다
        # (슬롯 사이 검산 조건 중복 제거를 위해 `claimed`를 공유).
        claimed: set[str] = set()
        for slot_id in SLOT_IDS:
            built = tuple(cls._slot_items(slot_id, claimed))
            cls._validate_slot(slot_id, built)
            _ITEM_CACHE[(cls, slot_id)] = built
        return _ITEM_CACHE[key]

    @classmethod
    def _validate_slot(cls, slot: str, items: Sequence[DiffItem]) -> None:
        if not items:
            raise ValueError(f"{cls.__name__}[{slot}]: 문항이 0건이다")
        sets = {item.misconception_ids for item in items}
        if len(sets) != 1:
            raise ValueError(
                f"{cls.__name__}[{slot}]: 슬롯 안 오개념 연결 집합이 균일하지 않다 — "
                f"{sorted(sorted(s) for s in sets)}"
            )
        linked = next(iter(sets))
        if slot == "misconception_trigger" and not linked:
            raise ValueError(
                f"{cls.__name__}: 오개념 유발 슬롯인데 연결된 오개념이 없다 — 센 문항이 0이다"
            )
        if slot != "misconception_trigger" and linked:
            raise ValueError(f"{cls.__name__}[{slot}]: 오개념 유발이 아닌 슬롯에 오개념이 연결됨")
        for item in items:
            if item.slot != slot:
                raise ValueError(f"{cls.__name__}: 문항 슬롯 불일치 {item.slot} != {slot}")
            if item.distractors and not item.choices:
                raise ValueError("오답 귀속이 있는데 선지가 없다")
            if item.choices is not None and len(item.choices) != 4:
                raise ValueError("객관식 선지는 4개여야 한다")
            if slot == "misconception_trigger" and item.choices is None:
                raise ValueError("오개념 유발 슬롯은 객관식(오답 선지가 오개념에 연결)이어야 한다")
            expected = answer_format_for(item.answer_text)
            if item.answer_format != expected:
                raise ValueError(
                    f"{cls.__name__}[{slot}] {item.frame_id}: answer_format "
                    f"{item.answer_format.value} != 정답 {item.answer_text}의 형식 {expected.value}"
                )

    @classmethod
    def target_misconception_ids(cls, slot: str) -> frozenset[str]:
        """슬롯의 오개념 연결 집합(균일성은 `items()`가 보증) — 배치 스펙의 입력."""
        return next(iter(cls.items(slot))).misconception_ids

    @classmethod
    def spec_for(cls, slot: str) -> EquivalenceSpec:
        """슬롯 1개의 수용 게이트 스펙 — 성취기준·오개념·난이도가 문항과 정합해야 동치가 된다."""
        return EquivalenceSpec(
            achievement_standard_codes=frozenset({cls.standard_code}),
            target_misconception_ids=cls.target_misconception_ids(slot),
            difficulty_overall=cls.slot_difficulty[slot],
            answer_format=None,
        )

    # ── EquivalentProblemGenerator 좌석 ─────────────────────────────────
    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 문항을 후보로 조립 — skip 집합에 있는 조건식은 건너뛰고, 소진 시 None."""
        while self._index < len(self._items):
            item = self._items[self._index]
            self._index += 1
            if self._skip is not None and _condition_key(item) in self._skip:
                continue
            return self._assemble(spec, item)
        return None

    def _assemble(self, spec: EquivalenceSpec, item: DiffItem) -> CandidateProblem:
        standard_codes = sorted(spec.achievement_standard_codes)
        slug = self._stable_slug(item.question_text, item.answer_text, standard_codes)
        distractor_map = (
            [
                DistractorEntry(choice_index=i, misconception_id=k, op_code=None)
                for i, k in item.distractors
            ]
            if item.distractors
            else None
        )
        problem = Problem(
            problem_id=uuid.uuid5(uuid.NAMESPACE_URL, f"whymath:problem:{slug}"),
            slug=slug,
            source_type=SourceType.자체생성,
            curriculum_version=Curriculum.REVISION_2022,
            valid_from_year=2022,
            subject=Subject.미적분,
            unit_codes=[self.unit_code],
            difficulty_overall=type(self).slot_difficulty[item.slot],
            question_format=QuestionFormat.객관식 if item.choices else QuestionFormat.단답형,
            answer_format=item.answer_format,
            achievement_standard_codes=standard_codes,
            question_text=item.question_text,
            choices=list(item.choices) if item.choices else None,
            answer=item.answer_text,
            answer_explanation=anchor_curve_function(item.question_text, item.explanation),
            distractor_map=distractor_map,
            problem_type_codes=[item.problem_type_code],
            tags=[f"{SLOT_TAG_PREFIX}{item.slot}"],
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 스켈레톤 조립(슬롯 틀·파라미터 열거·정답은 SymPy 미분으로 계산)",
                    "S2-a 수용 게이트(Tier1 SymPy 검산)",
                    "감사 표본 승인 경로(이 도구는 review_status를 쓰지 않는다)",
                ],
            },
        )
        # 조건이 1개면 문자열로 싣는다(섀도 채점 코퍼스 경로는 문자열 조건만 읽는다).
        conditions: str | list[str]
        if isinstance(item.conditions, str):
            conditions = item.conditions
        elif len(item.conditions) == 1:
            conditions = item.conditions[0]
        else:
            conditions = list(item.conditions)
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=conditions,
            answer_map=dict(item.answer_map),
            solution_steps=None,
            concept_tags=[
                ConceptTag(
                    concept_src_id=self.concept_src_id,
                    role="PRIMARY",
                    relevance=self.concept_relevance,
                )
            ],
        )

    def _stable_slug(self, question_text: str, answer: str, codes: Sequence[str]) -> str:
        """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
        payload = "|".join([question_text, answer, ",".join(sorted(codes))])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self.slug_prefix}-{digest}"
