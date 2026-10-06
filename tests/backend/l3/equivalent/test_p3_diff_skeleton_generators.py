"""Phase 3 미적분Ⅰ '미분' 개념별 결정론 생성기 계약 테스트 — P3-03(hermetic·LLM 0).

등록부(`harness.p3_calculus1_diff_batch.GENERATORS`)의 **모든** 생성기를 같은 계약으로 검사한다 —
다른 에이전트가 등록부에 새 개념을 한 줄 더하면 이 테스트가 자동으로 그 개념을 덮는다.

검증 축
-------
① 슬롯 6종 전부가 채워지고 슬롯당 문항 수가 선언(`slot_count`)과 같다.
② 개념당 문면 골격(숫자를 #로 접은 문면) 고유 수 ≥ 30 · 구조적 틀(frame) 수 ≥ 30.
③ **전 문항이 수용 게이트(Tier1 SymPy)를 통과**한다 — 그리고 *정답을 틀리게 주입하면 전 문항이 거부*된다
   (변별력: 무차별 통과가 아니다).
④ 정답의 **독립 재계산** — 생성기가 쓴 `sympy.diff` 경로가 아니라 *미분의 정의(극한)* 로 다시 구한다.
⑤ 오개념 연결의 참조 무결성 — kebab이 정본 카탈로그에 실재하고, 명세의 핵심 오개념(M-id)에
   크로스링크 직접매핑으로 닿는다. 오개념 유발 슬롯 외에는 오개념 연결이 없다.
⑥ 객관식 불변식(선지 4개·표기 상이·정답 위치와 오답 귀속 위치가 다름).
⑦ 필수 문제유형 5종 안에서만 쓴다 · review_status 키를 쓰지 않는다 · 신규 유니코드 글리프 0.
⑧ 슬롯 불변식 위반(균일하지 않은 오개념 집합 등)은 빌드 시점에 ValueError로 멈춘다.
"""

from __future__ import annotations

import json
import re
import typing
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

import pytest
import sympy

from whymath_backend.harness import attempt_grading_shadow_report as shadow
from whymath_backend.harness import generator_space_overlap_audit as overlap_audit
from whymath_backend.harness.p3_calculus1_diff_batch import GENERATORS
from whymath_backend.l1.standards.phase3_scope import load_scope_spec
from whymath_backend.l3.equivalent import p3_diff_skeleton_base as base
from whymath_backend.l3.equivalent.acceptance import evaluate_equivalent_candidate
from whymath_backend.l3.equivalent.generator import CandidateProblem
from whymath_backend.l3.equivalent.orchestrator import run_equivalent_generation
from whymath_backend.l3.equivalent.p3_diff_polynomial_rules_skeleton_generator import (
    P3DiffPolynomialRulesGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_power_derivative_skeleton_generator import (
    P3DiffPowerDerivativeGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import (
    SLOT_IDS,
    DiffItem,
    P3DiffSlotGenerator,
    skeleton_of,
)
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.validate import validate_distractor_map
from whymath_backend.schema.enums import AnswerFormat

# PB-13: 생성기·배치 회귀는 corpus-authoring 잡이 돌린다(backend 잡 35분 상한 — 비활성화가 아니다).
pytestmark = pytest.mark.corpus_authoring

_MIN_SKELETONS = 30
_MIN_FRAMES = 30
_CORPUS_ROOT = Path(__file__).resolve().parents[4] / "data" / "corpus"
_GLYPHS = ("²", "³", "Σ", "α", "β", "√", "′")

_ALL = pytest.mark.parametrize("generator_cls", GENERATORS, ids=lambda g: g.standard_code)


def _all_items(generator_cls: type[P3DiffSlotGenerator]) -> list[DiffItem]:
    return [item for slot in SLOT_IDS for item in generator_cls.items(slot)]


def _candidates(generator_cls: type[P3DiffSlotGenerator], slot: str) -> list[CandidateProblem]:
    spec = generator_cls.spec_for(slot)
    generator = generator_cls(slot=slot)
    out: list[CandidateProblem] = []
    while (candidate := generator.generate(spec)) is not None:
        out.append(candidate)
    return out


@_ALL
def test_every_slot_is_filled_with_the_declared_count(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    for slot in SLOT_IDS:
        items = generator_cls.items(slot)
        assert len(items) == generator_cls.slot_count, (slot, len(items))
        assert {item.slot for item in items} == {slot}
        assert len({item.frame_id for item in items}) >= 4, f"{slot}: 틀이 4종 미만"
    assert set(generator_cls.slot_difficulty) == set(SLOT_IDS)


@_ALL
def test_distinct_skeletons_and_frames_reach_the_floor(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    items = _all_items(generator_cls)
    skeletons = {skeleton_of(i.question_text) for i in items}
    frames = {i.frame_id for i in items}
    assert len(skeletons) >= _MIN_SKELETONS, len(skeletons)
    # 골격 수는 부호·항 수 변형으로 부풀 수 있어 *구조적 틀 수*도 따로 잰다(부풀림 방지).
    assert len(frames) >= _MIN_FRAMES, len(frames)
    # 슬롯마다 최소 4개의 서로 다른 골격(한 슬롯이 한 문면으로 도배되지 않는다).
    for slot in SLOT_IDS:
        slot_skeletons = {skeleton_of(i.question_text) for i in generator_cls.items(slot)}
        assert len(slot_skeletons) >= 4, slot


@_ALL
def test_questions_and_conditions_are_unique_within_the_concept(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    items = _all_items(generator_cls)
    texts = [i.question_text for i in items]
    conds = [
        i.conditions if isinstance(i.conditions, str) else "&&".join(i.conditions) for i in items
    ]
    assert len(set(texts)) == len(texts)
    assert len(set(conds)) == len(conds)  # 슬롯 사이에서도 같은 수학 실체를 두 번 내지 않는다


@_ALL
def test_every_item_passes_the_acceptance_gate(generator_cls: type[P3DiffSlotGenerator]) -> None:
    for slot in SLOT_IDS:
        spec = generator_cls.spec_for(slot)
        generator = generator_cls(slot=slot)
        for _ in range(len(generator_cls.items(slot))):
            outcome = run_equivalent_generation(spec, generator, signature_index=None)
            assert outcome.status == "accepted", (slot, outcome.status, outcome.reasons)
        assert generator.generate(spec) is None  # 소진


@_ALL
def test_gate_rejects_a_wrong_answer_for_every_item(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    """**변별력 실측(RED)** — 검산 재료의 답을 틀리게 만들면 전 문항이 Tier1에서 거부된다."""
    rejected = 0
    total = 0
    for slot in SLOT_IDS:
        spec = generator_cls.spec_for(slot)
        for candidate in _candidates(generator_cls, slot):
            total += 1
            key = sorted(candidate.answer_map)[-1]  # 마지막 키 = 최종 답(보조 변수는 앞)
            broken_map = dict(candidate.answer_map)
            broken_map[key] = f"({broken_map[key]}) + 1"
            verdict = evaluate_equivalent_candidate(
                spec,
                candidate.problem,
                provenance=candidate.provenance,
                conditions=candidate.conditions,
                answer_map=broken_map,
            )
            if not verdict.accepted and any("Tier1" in r for r in verdict.reasons):
                rejected += 1
    assert total > 0
    assert rejected == total, f"{total - rejected}건이 틀린 답을 통과시켰다"


_SINGLE_DERIV = re.compile(
    r"^Derivative\((?P<expr>.+), (?P<var>[a-z])\)\.doit\(\)\.subs\((?P=var), (?P<pt>-?\d+)\) = y$"
)


@_ALL
def test_value_answers_match_the_limit_definition(generator_cls: type[P3DiffSlotGenerator]) -> None:
    """정답의 독립 재계산 — 미분계수를 `sympy.diff`가 아니라 **극한 정의**로 구해 비교한다."""
    checked = 0
    for item in _all_items(generator_cls):
        if not isinstance(item.conditions, str):
            continue
        match = _SINGLE_DERIV.match(item.conditions)
        if match is None:
            continue
        var = sympy.Symbol(match["var"])
        h = sympy.Symbol("h")
        expr = sympy.sympify(match["expr"])
        point = int(match["pt"])
        by_definition = sympy.limit((expr.subs(var, point + h) - expr.subs(var, point)) / h, h, 0)
        claimed = dict(item.answer_map)["y"]
        assert sympy.simplify(by_definition - sympy.sympify(claimed)) == 0, item.question_text
        # 표기된 정답도 같은 값이어야 한다(단답형·객관식 공통).
        assert sympy.simplify(sympy.sympify(item.answer_text) - by_definition) == 0
        checked += 1
    assert checked >= 15, f"극한 정의로 재검산한 문항이 너무 적다: {checked}"


@_ALL
def test_no_function_valued_answers(generator_cls: type[P3DiffSlotGenerator]) -> None:
    """함수식(`식`)을 답으로 하는 문항은 만들지 않는다 — 섀도 채점 계약이 스칼라 단일 미지수만 받는다.

    함수 답을 되살리려면 이 테스트가 아니라 *그 계약*(`attempt_grading_shadow_report`의
    `_SUPPORTED_UNKNOWN_COUNT`·코퍼스 0건 동결)을 소유자가 먼저 바꿔야 한다.
    """
    for item in _all_items(generator_cls):
        assert item.answer_format != AnswerFormat.식, item.question_text
        assert "x^" not in item.answer_text and not re.search(
            r"[a-z]", item.answer_text.replace("sqrt", "")
        ), (
            item.question_text,
            item.answer_text,
        )


@_ALL
def test_conditions_obey_the_single_unknown_contract_of_shadow_grading(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    """섀도 채점 계약(NLP-09) — 문자열 조건의 자유기호가 정확히 하나이고 answer_map의 유일한 키다.

    함수식 답(`y = 도함수`)·보조 변수(`p`·`q`)·미지수 2개는 전부 이 계약을 깬다(그래서
    `test_multi_symbol_population_is_frozen`이 red가 된다). 연립 목록 조건은 코퍼스 로더가
    읽지 않으므로(해를 부등식으로 유일하게 가르는 문항) 여기서는 *부등식 보호가 붙은 목록*만 허용한다.
    """
    str_checked = 0
    for item in _all_items(generator_cls):
        if isinstance(item.conditions, str):
            parsed = shadow._parse_for_derivation(item.conditions)
            assert parsed is not None, item.conditions
            symbols = shadow._free_symbol_names(parsed)
            assert symbols is not None and len(symbols) == 1, (item.conditions, symbols)
            assert symbols == {k for k, _ in item.answer_map}, item.conditions
            str_checked += 1
        else:
            assert len(item.conditions) >= 2, "목록 조건은 2개 이상일 때만(1개는 문자열로 쓴다)"
            assert any(re.search(r"[<>!]=?", c) for c in item.conditions[1:]), (
                "목록 조건의 존재 이유(부등식 보호)가 없다",
                item.conditions,
            )
            assert len(item.answer_map) == 1
    assert str_checked >= 0.7 * len(_all_items(generator_cls))


@_ALL
def test_misconception_links_are_exactly_the_mc_slot_and_resolve(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    spec = load_scope_spec()
    core = {
        m.mis_id for m in spec.core_misconceptions if m.concept_code == generator_cls.standard_code
    }
    assert core, "명세에 이 개념의 핵심 오개념이 없다"
    crosslinks = json.loads(
        (_CORPUS_ROOT / "misconception_crosslinks_v1" / "crosslinks.json").read_text(
            encoding="utf-8"
        )
    )["crosslinks"]
    reached: set[str] = set()
    for slot in SLOT_IDS:
        linked = generator_cls.target_misconception_ids(slot)
        if slot != "misconception_trigger":
            assert linked == frozenset(), f"{slot}: 오개념 유발이 아닌 슬롯에 오개념이 연결됨"
            continue
        assert linked, "오개념 유발 슬롯에 연결된 오개념이 없다 — 센 문항이 0이다"
        for kebab in linked:
            assert kebab in CATALOG_BY_ID, f"카탈로그에 없는 kebab: {kebab}"
            reached |= {
                row["mis_id"]
                for row in crosslinks
                if row["kebab_id"] == kebab and row["link_type"] == "직접매핑"
            }
        for candidate in _candidates(generator_cls, slot):
            assert candidate.problem.distractor_map, "오개념 유발 문항에 distractor_map이 없다"
            assert validate_distractor_map(candidate.problem.distractor_map) == []
    assert core <= reached, f"핵심 오개념 {core}이 크로스링크로 닿지 않는다: {reached}"


@_ALL
def test_multiple_choice_invariants(generator_cls: type[P3DiffSlotGenerator]) -> None:
    mc_seen = 0
    for slot in SLOT_IDS:
        for item in generator_cls.items(slot):
            if item.choices is None:
                assert not item.distractors
                continue
            mc_seen += 1
            assert len(item.choices) == 4
            assert len(set(item.choices)) == 4
            assert item.answer_text in item.choices
            answer_index = item.choices.index(item.answer_text)
            for index, _kebab in item.distractors:
                assert index != answer_index, "정답 선지에 오개념이 귀속됐다"
                assert 0 <= index < 4
            assert len({i for i, _ in item.distractors}) == len(item.distractors)
    assert mc_seen >= generator_cls.slot_count  # 오개념 유발 슬롯 전량이 객관식


@_ALL
def test_only_required_problem_types_and_no_review_status(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    allowed = set(load_scope_spec().problem_types)
    for slot in SLOT_IDS:
        for candidate in _candidates(generator_cls, slot):
            problem = candidate.problem
            assert set(problem.problem_type_codes) <= allowed
            assert len(problem.problem_type_codes) == 1
            assert problem.review_status is None  # 승인은 감사 표본 경로의 몫
            assert problem.is_published is False
            assert problem.tags == [f"{base.SLOT_TAG_PREFIX}{slot}"]
            assert problem.achievement_standard_codes == [generator_cls.standard_code]
            assert [t.concept_src_id for t in candidate.concept_tags] == [
                generator_cls.concept_src_id
            ]


@_ALL
def test_no_new_unicode_glyphs_or_latex_markup(generator_cls: type[P3DiffSlotGenerator]) -> None:
    for item in _all_items(generator_cls):
        for field in (
            item.question_text,
            item.explanation,
            item.answer_text,
            *(item.choices or ()),
        ):
            assert not any(g in field for g in _GLYPHS), field
            assert "$" not in field and "\\" not in field, field
        assert item.answer_format in set(AnswerFormat)


@_ALL
def test_items_are_deterministic_across_cache_rebuilds(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    before = {slot: generator_cls.items(slot) for slot in SLOT_IDS}
    for slot in SLOT_IDS:
        base._ITEM_CACHE.pop((generator_cls, slot), None)
    after = {slot: generator_cls.items(slot) for slot in SLOT_IDS}
    assert before == after


# ──────────────────────────────────────────────────────────────────────────
# 슬롯 불변식(`_validate_slot`) — 위반이 빌드 시점에 멈추는지(가드의 변별력)
# ──────────────────────────────────────────────────────────────────────────
def _item(slot: str, *, kebab: str | None, mc: bool = True, frame: str = "f") -> DiffItem:
    return DiffItem(
        slot=slot,
        frame_id=frame,
        question_text=f"문항 {slot} {frame} {kebab}",
        answer_text="1",
        explanation="해설",
        conditions="x = y",
        answer_map=(("y", "1"),),
        problem_type_code="ptype.evaluate-expression",
        answer_format=AnswerFormat.자연수,
        choices=("1", "2", "3", "4") if mc else None,
        distractors=((1, kebab),) if kebab else (),
    )


def _fake(items_by_slot: dict[str, list[DiffItem]]) -> type[P3DiffSlotGenerator]:
    class Fake(P3DiffSlotGenerator):
        standard_code: ClassVar[str] = "[FAKE-01]"
        concept_src_id: ClassVar[str] = "H:FAKE"
        unit_code: ClassVar[str] = "FAKE"
        slug_prefix: ClassVar[str] = "wm-fake"
        slot_difficulty: ClassVar[dict[str, float]] = dict.fromkeys(SLOT_IDS, 3.0)

        @classmethod
        def _slot_items(cls, slot: str, claimed: set[str]) -> list[DiffItem]:
            return items_by_slot[slot]

    return Fake


def _healthy() -> dict[str, list[DiffItem]]:
    out = {slot: [_item(slot, kebab=None, mc=False)] for slot in SLOT_IDS}
    out["misconception_trigger"] = [_item("misconception_trigger", kebab="power-rule-step-omitted")]
    return out


def test_validate_slot_accepts_a_healthy_registry_entry() -> None:
    fake = _fake(_healthy())
    assert fake.target_misconception_ids("misconception_trigger") == {"power-rule-step-omitted"}


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda d: d.__setitem__(
                "misconception_trigger",
                [
                    _item("misconception_trigger", kebab="power-rule-step-omitted", frame="a"),
                    _item("misconception_trigger", kebab="product-rule-naive", frame="b"),
                ],
            ),
            "균일하지 않다",
        ),
        (
            lambda d: d.__setitem__(
                "misconception_trigger", [_item("misconception_trigger", kebab=None)]
            ),
            "연결된 오개념이 없다",
        ),
        (
            lambda d: d.__setitem__("basic", [_item("basic", kebab="power-rule-step-omitted")]),
            "오개념 유발이 아닌 슬롯",
        ),
        (
            lambda d: d.__setitem__("applied", []),
            "0건",
        ),
    ],
    ids=["mixed-kebab-sets", "mc-slot-without-kebab", "kebab-outside-mc-slot", "empty-slot"],
)
def test_validate_slot_rejects_violations(
    mutate: Callable[[dict[str, list[DiffItem]]], None], message: str
) -> None:
    data = _healthy()
    mutate(data)
    fake = _fake(data)
    with pytest.raises(ValueError, match=message):
        fake.items("representative")


@_ALL
def test_overlap_audit_can_instantiate_every_slot(generator_cls: type[P3DiffSlotGenerator]) -> None:
    """QUAL-08 형제 생성기 공간 겹침 감사기가 6슬롯을 *전부* 인스턴스화할 수 있다.

    `slot`이 `Literal` 인자라 감사기가 모든 값으로 인스턴스를 만든다(일반 `str`이면 "측정 불가
    클래스"로 감사 게이트 `test_trunk_measures_every_generator_class`가 깨진다).
    """
    instances, failure = overlap_audit.build_instances(generator_cls)
    assert failure is None, failure
    assert len(instances) == len(SLOT_IDS)
    assert typing.get_args(base.SlotId) == SLOT_IDS


def test_registry_holds_both_first_concepts_in_order() -> None:
    """등록부에 02-03·02-04 생성기가 이 순서로 있다.

    각 생성기 *모듈명*을 이 테스트가 직접 import하는 것은 `tests/infra/test_path_scoped_counting_guard`
    (생성기 모듈마다 그 이름을 참조하는 테스트가 있어야 한다)를 위한 명시 참조이기도 하다 — 등록부 순회
    테스트만으로는 새 모듈명이 어느 테스트에도 안 나온다. **새 개념을 등록부에 더하면 여기에도 한 줄을
    더한다.**
    """
    assert GENERATORS[:2] == (P3DiffPowerDerivativeGenerator, P3DiffPolynomialRulesGenerator)
    assert [g.standard_code for g in GENERATORS[:2]] == ["[12미적Ⅰ-02-03]", "[12미적Ⅰ-02-04]"]
    assert len({g.standard_code for g in GENERATORS}) == len(GENERATORS)  # 개념당 생성기 1개


def test_slot_ids_match_the_frozen_scope_spec() -> None:
    """슬롯 id·순서가 명세 `quantity_targets.slots`와 어긋나면(명세 변경) 즉시 드러난다."""
    assert tuple(slot.id for slot in load_scope_spec().slots) == SLOT_IDS
