"""Phase 3 미적분Ⅰ '미분' — 접선의 방정식·속도와 가속도 생성기 계약 테스트(P3-03·hermetic·LLM 0).

대상: `P3DiffTangentLineGenerator`([12미적Ⅰ-02-05])·`P3DiffVelocityAccelerationGenerator`
([12미적Ⅰ-02-10]). 기존 개념 생성기 계약(`test_p3_diff_skeleton_generators.py`)과 같은 불변식을 이
두 클래스에 직접 적용한다(등록부 순회 테스트는 호출자가 등록부에 더한 뒤에야 이 클래스들을 덮으므로,
등록 전에도 계약이 돌도록 클래스를 명시 참조한다 — 생성기 모듈명 참조 가드 `tests/infra/
test_path_scoped_counting_guard`도 이 명시 import로 충족된다).

검증 축
-------
① 슬롯 6종 전부 채움·슬롯당 문항 수 = 선언 · ② 개념당 문면 골격 ≥ 30·틀 ≥ 30 ·
③ 전 문항 수용 게이트(Tier1) 통과 + 정답을 틀리게 주입하면 전 문항 거부(변별력) ·
④ **정답의 독립 재계산** — (a) 미분계수를 극한 정의로 재계산, (b) 조건식을 SymPy `solve`로 *실수 전체*에서
   풀어 보호 조건(`a > 0` 등) 아래 해가 **정답 하나뿐**임을 확인(게이트는 "이 값이 조건을 만족한다"만 본다 —
   유일성은 이 테스트가 처음 본다) ·
⑤ 오개념 연결의 참조 무결성(kebab 실재·오개념 유발 슬롯에만·`validate_distractor_map` 통과) ·
   **핵심 오개념(M0673·M0678)의 크로스링크 도달은 현재 불가**임을 strict xfail로 동결(보고 사항) ·
⑥ 객관식 불변식 · ⑦ 필수 문제유형 안에서만 사용·review_status 키 부재·ASCII+한글만(신규 글리프 0) ·
⑧ 함수식 답 금지·섀도 채점 단일 미지수 계약 ·
⑨ 문제유형 → 개념 스킬 연결 계측(`phase3_coverage`와 같은 정의) 하한 ·
⑩ 검출기 자신의 변별력 — 정답 +1·유형 교체·오개념 kebab 교체·오개념 누출 주입을 넣으면 위 검사가 RED.
"""

from __future__ import annotations

import dataclasses
import json
import re
import typing
from pathlib import Path

import pytest
import sympy

from whymath_backend.harness import attempt_grading_shadow_report as shadow
from whymath_backend.harness import generator_space_overlap_audit as overlap_audit
from whymath_backend.l1.standards import phase3_coverage as coverage
from whymath_backend.l1.standards.phase3_scope import load_scope_spec
from whymath_backend.l3.equivalent import p3_diff_skeleton_base as base
from whymath_backend.l3.equivalent.acceptance import evaluate_equivalent_candidate
from whymath_backend.l3.equivalent.generator import CandidateProblem
from whymath_backend.l3.equivalent.orchestrator import run_equivalent_generation
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import (
    SLOT_IDS,
    DiffItem,
    P3DiffSlotGenerator,
    skeleton_of,
)
from whymath_backend.l3.equivalent.p3_diff_tangent_line_skeleton_generator import (
    P3DiffTangentLineGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_velocity_acceleration_skeleton_generator import (
    P3DiffVelocityAccelerationGenerator,
)
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.validate import validate_distractor_map
from whymath_backend.schema.enums import AnswerFormat

# PB-13: 생성기·배치 회귀는 corpus-authoring 잡이 돌린다(backend 잡 35분 상한 — 비활성화가 아니다).
pytestmark = pytest.mark.corpus_authoring

_REPO_ROOT = Path(__file__).resolve().parents[3].parent
_CORPUS_ROOT = _REPO_ROOT / "data" / "corpus"
_MIN_SKELETONS = 30
_MIN_FRAMES = 30
_GENERATORS: tuple[type[P3DiffSlotGenerator], ...] = (
    P3DiffTangentLineGenerator,
    P3DiffVelocityAccelerationGenerator,
)
_ALL = pytest.mark.parametrize("generator_cls", _GENERATORS, ids=lambda g: g.standard_code)


def _all_items(generator_cls: type[P3DiffSlotGenerator]) -> list[DiffItem]:
    return [item for slot in SLOT_IDS for item in generator_cls.items(slot)]


def _candidates(generator_cls: type[P3DiffSlotGenerator], slot: str) -> list[CandidateProblem]:
    spec = generator_cls.spec_for(slot)
    generator = generator_cls(slot=slot)
    out: list[CandidateProblem] = []
    while (candidate := generator.generate(spec)) is not None:
        out.append(candidate)
    return out


# ──────────────────────────────────────────────────────────────────────────
# ① 슬롯·② 골격·틀·유일성
# ──────────────────────────────────────────────────────────────────────────
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
    assert len(frames) >= _MIN_FRAMES, len(frames)
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
    assert len(set(conds)) == len(conds)


# ──────────────────────────────────────────────────────────────────────────
# ③ 수용 게이트 + 변별력
# ──────────────────────────────────────────────────────────────────────────
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
            key = sorted(candidate.answer_map)[-1]
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


# ──────────────────────────────────────────────────────────────────────────
# ④ 정답의 독립 재계산
# ──────────────────────────────────────────────────────────────────────────
_DERIV_Y = re.compile(
    r"^(?P<abs>Abs\()?Derivative\((?P<expr>[^,]+), (?P<var>[a-z])(?P<second>, (?P=var))?\)"
    r"\.doit\(\)\.subs\((?P=var), (?P<pt>-?\d+)\)\)? = y$"
)
_GUARD = re.compile(r"^(?P<sym>[a-z]) (?P<op>>|<|!=) (?P<num>-?\d+)$")


def _limit_derivative(expr: sympy.Expr, var: sympy.Symbol) -> sympy.Expr:
    """미분의 정의(극한)로 구한 도함수 — `sympy.diff`가 아닌 독립 경로."""
    h = sympy.Symbol("h")
    return sympy.simplify(sympy.limit((expr.subs(var, var + h) - expr) / h, h, 0))


def _limit_check(item: DiffItem) -> bool | None:
    """속도·기울기·가속도 값 문항을 극한 정의로 다시 구해 정답과 같은지 — 대상이 아니면 None."""
    if not isinstance(item.conditions, str):
        return None
    match = _DERIV_Y.match(item.conditions)
    if match is None:
        return None
    var = sympy.Symbol(match["var"])
    expr = sympy.sympify(match["expr"])
    derived = _limit_derivative(expr, var)
    if match["second"]:
        derived = _limit_derivative(derived, var)
    value = derived.subs(var, int(match["pt"]))
    if match["abs"]:
        value = sympy.Abs(value)
    claimed = sympy.sympify(dict(item.answer_map)["y"])
    return bool(sympy.simplify(value - claimed) == 0) and bool(
        sympy.simplify(sympy.sympify(item.answer_text) - value) == 0
    )


def _independent_problems(item: DiffItem) -> list[str]:
    """조건식을 SymPy `solve`로 *실수 전체*에서 풀어 정답이 보호 조건 아래 유일한 해인지 본다.

    빈 목록이면 독립 재계산이 정답을 지지한다. 첫 조건 = 방정식(`lhs = rhs`), 나머지 = 보호 조건
    (`a > 0`·`b != 4`·`s < 6` 꼴). 게이트(Tier1)는 "답이 조건을 만족하는가"만 보므로 *다른 해가 보호를
    통과해 정답이 모호해지는* 문항은 여기서 처음 걸린다.
    """
    conds = [item.conditions] if isinstance(item.conditions, str) else list(item.conditions)
    problems: list[str] = []
    ((symbol_name, answer_text),) = item.answer_map
    symbol = sympy.Symbol(symbol_name)
    answer = sympy.sympify(answer_text)
    lhs, rhs = conds[0].split(" = ")
    residual = sympy.sympify(lhs) - sympy.sympify(rhs)
    guards = []
    for guard_text in conds[1:]:
        g = _GUARD.match(guard_text)
        if g is None:
            problems.append(f"해석할 수 없는 보호 조건: {guard_text}")
            continue
        number = sympy.Integer(int(g["num"]))
        op = g["op"]
        guards.append(
            lambda r, op=op, number=number: (
                r > number if op == ">" else (r < number if op == "<" else r != number)
            )
        )
    roots = [r for r in sympy.solve(residual, symbol) if r.is_real]
    survivors = [r for r in roots if all(bool(g(r)) for g in guards)]
    if survivors != [answer]:
        problems.append(f"보호 조건을 통과하는 해가 정답 {answer} 하나가 아니다: {survivors}")
    if answer_text != str(answer):  # 표기 정규형(공백·부호)
        problems.append(f"정답 표기가 정규형이 아니다: {answer_text}")
    return problems


@_ALL
def test_value_answers_match_the_limit_definition(generator_cls: type[P3DiffSlotGenerator]) -> None:
    """정답의 독립 재계산(a) — 미분계수·속도·가속도를 **극한 정의**로 다시 구해 비교한다."""
    checked = 0
    for item in _all_items(generator_cls):
        verdict = _limit_check(item)
        if verdict is None:
            continue
        assert verdict, item.question_text
        checked += 1
    assert checked >= 15, f"극한 정의로 재검산한 문항이 너무 적다: {checked}"


@_ALL
def test_every_answer_is_the_unique_real_solution(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    """정답의 독립 재계산(b) — 전 문항: SymPy `solve`가 보호 조건 아래 정답만 남긴다."""
    for item in _all_items(generator_cls):
        assert _independent_problems(item) == [], (item.frame_id, item.question_text)


@_ALL
def test_independent_check_has_discriminating_power(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    """검출기 자신의 변별력(RED) — 정답을 +1 주입하면 독립 재계산이 *전 문항에서* 문제를 낸다."""
    broken = 0
    items = _all_items(generator_cls)
    for item in items:
        key, value = item.answer_map[0]
        mutated = dataclasses.replace(
            item,
            answer_text=str(int(value) + 1),
            answer_map=((key, str(int(value) + 1)),),
        )
        assert mutated != item  # 주입이 실제로 적용됐다
        if _independent_problems(mutated):
            broken += 1
    assert broken == len(items), f"{len(items) - broken}건이 +1 주입을 놓쳤다"
    limit_total = limit_caught = 0
    for item in items:
        verdict = _limit_check(item)
        if verdict is None:
            continue
        limit_total += 1
        key, value = item.answer_map[0]
        mutated = dataclasses.replace(
            item,
            answer_text=str(int(value) + 1),
            answer_map=((key, str(int(value) + 1)),),
        )
        if _limit_check(mutated) is False:
            limit_caught += 1
    assert limit_total > 0 and limit_caught == limit_total


# ──────────────────────────────────────────────────────────────────────────
# ⑧ 함수식 답 금지·섀도 채점 단일 미지수 계약
# ──────────────────────────────────────────────────────────────────────────
@_ALL
def test_no_function_valued_answers(generator_cls: type[P3DiffSlotGenerator]) -> None:
    for item in _all_items(generator_cls):
        assert item.answer_format != AnswerFormat.식, item.question_text
        assert re.fullmatch(r"-?\d+", item.answer_text), (item.question_text, item.answer_text)


@_ALL
def test_conditions_obey_the_single_unknown_contract_of_shadow_grading(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    """섀도 채점 계약(NLP-09) — 문자열 조건의 자유기호가 정확히 하나이고 answer_map의 유일한 키다."""
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
    assert str_checked >= 0.5 * len(_all_items(generator_cls))


# ──────────────────────────────────────────────────────────────────────────
# ⑤ 오개념 연결
# ──────────────────────────────────────────────────────────────────────────
def _crosslink_reach(kebabs: frozenset[str]) -> set[str]:
    rows = json.loads(
        (_CORPUS_ROOT / "misconception_crosslinks_v1" / "crosslinks.json").read_text(
            encoding="utf-8"
        )
    )["crosslinks"]
    return {
        row["mis_id"]
        for row in rows
        if row["kebab_id"] in kebabs and row["link_type"] == "직접매핑"
    }


@_ALL
def test_misconception_links_are_exactly_the_mc_slot_and_resolve(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    for slot in SLOT_IDS:
        linked = generator_cls.target_misconception_ids(slot)
        if slot != "misconception_trigger":
            assert linked == frozenset(), f"{slot}: 오개념 유발이 아닌 슬롯에 오개념이 연결됨"
            continue
        assert linked, "오개념 유발 슬롯에 연결된 오개념이 없다 — 센 문항이 0이다"
        for kebab in linked:
            assert kebab in CATALOG_BY_ID, f"카탈로그에 없는 kebab: {kebab}"
        for candidate in _candidates(generator_cls, slot):
            assert candidate.problem.distractor_map, "오개념 유발 문항에 distractor_map이 없다"
            assert validate_distractor_map(candidate.problem.distractor_map) == []


@_ALL
def test_wrong_choices_are_the_actual_misconception_outputs(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    """오개념 연결 문항의 의미 검사 — kebab이 걸린 선지는 정답과 다르고, 걸리지 않은 선지와도 겹치지 않는다."""
    for item in generator_cls.items("misconception_trigger"):
        assert item.choices is not None and item.distractors
        for index, _kebab in item.distractors:
            assert item.choices[index] != item.answer_text
        mapped = {index for index, _ in item.distractors}
        assert len(mapped) >= 1, "kebab이 걸린 오답 선지가 없다"
        assert len(item.choices) - len(mapped) >= 2  # 정답 1 + 미매핑 선지 1 이상


@_ALL
@pytest.mark.xfail(
    strict=True,
    reason=(
        "알려진 공백(보고 사항): 이 개념의 핵심 오개념(M0673·M0678)에는 *승인된* kebab 크로스링크가 "
        "없다(MISC-40 판정 — omission형·문맥 종속형이라 의도적 미승격). 새 id를 만들지 않는 제약 아래 "
        "오개념 유발 슬롯은 기존 kebab `power-rule-step-omitted`(→ M0671)에 연결되므로 핵심 오개념에 "
        "도달하지 못한다. 크로스링크가 승인돼 이 xfail이 XPASS가 되면 strict가 깨지므로 그때 이 마커를 "
        "제거한다."
    ),
)
def test_core_misconception_is_reachable_through_crosslinks(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    core = {
        m.mis_id
        for m in load_scope_spec().core_misconceptions
        if m.concept_code == generator_cls.standard_code
    }
    assert core, "명세에 이 개념의 핵심 오개념이 없다"
    reached = _crosslink_reach(generator_cls.target_misconception_ids("misconception_trigger"))
    assert core <= reached, f"핵심 오개념 {core}이 크로스링크로 닿지 않는다: {reached}"


# ──────────────────────────────────────────────────────────────────────────
# ⑥·⑦ 객관식·유형·글리프
# ──────────────────────────────────────────────────────────────────────────
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
    assert mc_seen >= generator_cls.slot_count


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
            dumped = problem.model_dump()
            assert dumped.get("review_status") is None


#: 승인 은행 표기 글리프(4차 감사 표기 교정) — 이 셋 밖의 비ASCII·비한글 문자는 금지.
_ALLOWED_GLYPHS = frozenset("√≤≥")


@_ALL
def test_text_is_ascii_plus_hangul_only(generator_cls: type[P3DiffSlotGenerator]) -> None:
    """신규 유니코드 글리프 0 — 한글 음절·ASCII와 승인 은행 표기 글리프 '√'·'≤'·'≥'만 쓴다.

    4차 감사(2026-10-07) 표기 교정 — 코드 표기 '8sqrt(3)'·'<='를 '8√3'·'≤'로 바꿨다. 세 글리프는 승인
    은행 4종이 쓰고 표기 커버리지 베이스라인에 있다. 위첨자·≠·± 등 그 밖의 글리프는 여전히 금지하고,
    코드 표기('<='·'>='·'sqrt('·'*')는 따로 금지한다.
    """
    for item in _all_items(generator_cls):
        for field in (
            item.question_text,
            item.explanation,
            item.answer_text,
            *(item.choices or ()),
        ):
            offenders = {
                c for c in field if not (c.isascii() or "가" <= c <= "힣" or c in _ALLOWED_GLYPHS)
            }
            assert not offenders, (offenders, field)
            assert not re.search(r"<=|>=|sqrt\(|\*", field), field
            assert "$" not in field and "\\" not in field, field


@_ALL
def test_explanations_have_no_double_signs_or_josa_slips(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    """생성 문면의 흔한 결함 — 이중 부호('+ -'·'- (-')와 빈 괄호 표기."""
    for item in _all_items(generator_cls):
        for field in (item.question_text, item.explanation):
            assert "+ -" not in field and "- (-" not in field and "( )" not in field, field


@_ALL
def test_items_are_deterministic_across_cache_rebuilds(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    before = {slot: generator_cls.items(slot) for slot in SLOT_IDS}
    for slot in SLOT_IDS:
        base._ITEM_CACHE.pop((generator_cls, slot), None)
    after = {slot: generator_cls.items(slot) for slot in SLOT_IDS}
    assert before == after


@_ALL
def test_overlap_audit_can_instantiate_every_slot(generator_cls: type[P3DiffSlotGenerator]) -> None:
    instances, failure = overlap_audit.build_instances(generator_cls)
    assert failure is None, failure
    assert len(instances) == len(SLOT_IDS)
    assert typing.get_args(base.SlotId) == SLOT_IDS


# ──────────────────────────────────────────────────────────────────────────
# ⑨ 문제유형 → 개념 스킬 연결(계측기 정의 그대로)
# ──────────────────────────────────────────────────────────────────────────
def _concept_skills_and_types(
    generator_cls: type[P3DiffSlotGenerator],
) -> tuple[set[str], dict[str, tuple[str, ...]]]:
    spec = load_scope_spec()
    index = coverage.load_reference_index(spec, _REPO_ROOT)
    corpus = coverage.load_corpus(spec, _REPO_ROOT)
    concept = next(c for c in spec.concepts if c.code == generator_cls.standard_code)
    cross = index.crosswalk.get(concept.concept_id)
    assert cross is not None
    atoms = [a for a in cross.atom_codes if a in index.atoms]
    skills = {s for a in atoms for s in index.atoms[a].behavior_skills if s in spec.skills}
    return skills, dict(corpus.type_skills)


def _linked_by_slot(
    generator_cls: type[P3DiffSlotGenerator],
    skills: set[str],
    type_skills: dict[str, tuple[str, ...]],
    items_by_slot: dict[str, list[DiffItem]] | None = None,
) -> dict[str, int]:
    out: dict[str, int] = {}
    for slot in SLOT_IDS:
        items = items_by_slot[slot] if items_by_slot else list(generator_cls.items(slot))
        out[slot] = sum(1 for i in items if skills & set(type_skills.get(i.problem_type_code, ())))
    return out


@_ALL
def test_skill_link_floor_and_every_type_is_honest(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    """스킬 연결 하한 — 겹치는 유형은 `solve-for-unknown`뿐이고, 그 진짜 문항을 충분히 만든다.

    응용 슬롯은 전부 연결 유형이다(미지수를 실제로 구하는 문항). 값 계산 문항을 겹치게 하려고 유형을
    거짓으로 달지 않았음은 `ptype.evaluate-expression` 문항이 연결로 *세어지지 않는* 것으로 확인한다.
    """
    skills, type_skills = _concept_skills_and_types(generator_cls)
    linked = _linked_by_slot(generator_cls, skills, type_skills)
    assert linked["applied"] == generator_cls.slot_count
    assert linked["mastery_check"] >= 4
    assert linked["misconception_trigger"] >= 1  # 오개념 유발 슬롯에도 연결 문항이 있다
    assert sum(linked.values()) >= 24
    eval_overlap = skills & set(type_skills.get("ptype.evaluate-expression", ()))
    assert eval_overlap == set(), "값 계산 유형이 이 개념 스킬과 겹치면 정직성 전제가 달라졌다"
    solve_overlap = skills & set(type_skills.get("ptype.solve-for-unknown", ()))
    assert "skill.equation-rearrangement" in solve_overlap
    used = {i.problem_type_code for i in _all_items(generator_cls)}
    assert used == {"ptype.evaluate-expression", "ptype.solve-for-unknown"}


# ──────────────────────────────────────────────────────────────────────────
# ⑩ 검출기 자신의 변별력 — 정답 +1·유형 교체·오개념 kebab 교체·오개념 누출
# ──────────────────────────────────────────────────────────────────────────
def _validate(generator_cls: type[P3DiffSlotGenerator], slot: str, items: list[DiffItem]) -> None:
    generator_cls._validate_slot(slot, items)


@_ALL
def test_mutation_kebab_swap_in_one_item_breaks_slot_uniformity(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    items = list(generator_cls.items("misconception_trigger"))
    first = items[0]
    swapped = dataclasses.replace(
        first, distractors=tuple((i, "product-rule-naive") for i, _ in first.distractors)
    )
    assert swapped != first
    items[0] = swapped
    with pytest.raises(ValueError, match="균일하지 않다"):
        _validate(generator_cls, "misconception_trigger", items)


@_ALL
def test_mutation_misconception_leak_into_basic_slot_is_rejected(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    items = list(generator_cls.items("basic"))
    leaked = dataclasses.replace(
        items[0],
        choices=("1", "2", "3", "4"),
        distractors=((1, "power-rule-step-omitted"),),
    )
    assert leaked != items[0]
    items[0] = leaked
    with pytest.raises(ValueError, match="균일하지 않다|오개념 유발이 아닌 슬롯"):
        _validate(generator_cls, "basic", items)


@_ALL
def test_mutation_problem_type_swap_drops_the_skill_link_count(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    """응용 슬롯의 유형을 값 계산으로 바꾸면(거짓 유형 반대 방향) 연결 계측이 0으로 떨어진다."""
    skills, type_skills = _concept_skills_and_types(generator_cls)
    original = {slot: list(generator_cls.items(slot)) for slot in SLOT_IDS}
    before = _linked_by_slot(generator_cls, skills, type_skills, original)
    swapped = dict(original)
    swapped["applied"] = [
        dataclasses.replace(i, problem_type_code="ptype.evaluate-expression")
        for i in original["applied"]
    ]
    assert swapped["applied"] != original["applied"]
    after = _linked_by_slot(generator_cls, skills, type_skills, swapped)
    assert before["applied"] == generator_cls.slot_count and after["applied"] == 0


@_ALL
def test_mutation_answer_plus_one_is_caught_by_the_acceptance_gate(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    """생성기 출력의 정답 표기만 +1로 바꾼 후보는 수용 게이트(answer_map 검산)에서 거부된다."""
    slot = "applied"
    spec = generator_cls.spec_for(slot)
    candidate = _candidates(generator_cls, slot)[0]
    key, value = next(iter(candidate.answer_map.items()))
    broken = dict(candidate.answer_map)
    broken[key] = str(int(value) + 1)
    assert broken != candidate.answer_map
    verdict = evaluate_equivalent_candidate(
        spec,
        candidate.problem,
        provenance=candidate.provenance,
        conditions=candidate.conditions,
        answer_map=broken,
    )
    assert not verdict.accepted
    ok = evaluate_equivalent_candidate(
        spec,
        candidate.problem,
        provenance=candidate.provenance,
        conditions=candidate.conditions,
        answer_map=dict(candidate.answer_map),
    )
    assert ok.accepted, ok.reasons  # 대조군 — 원본은 통과한다


# ──────────────────────────────────────────────────────────────────────────
# 개념별 정체성
# ──────────────────────────────────────────────────────────────────────────
def test_concept_identities_match_the_frozen_scope_spec() -> None:
    spec = load_scope_spec()
    by_code = {c.code: c for c in spec.concepts}
    for generator_cls in _GENERATORS:
        concept = by_code[generator_cls.standard_code]
        assert concept.source_id == generator_cls.concept_src_id
    assert {g.standard_code for g in _GENERATORS} == {"[12미적Ⅰ-02-05]", "[12미적Ⅰ-02-10]"}
    assert len({g.slug_prefix for g in _GENERATORS}) == len(_GENERATORS)
    assert len({g.unit_code for g in _GENERATORS}) == len(_GENERATORS)


def _student_expr(text: str) -> sympy.Expr:
    """학생 표기('2x^3 - 3x^2 + px')를 SymPy 식으로 — 독립 재계산용(생성기 렌더러 미사용)."""
    out = re.sub(r"(\d)([a-z])", r"\1*\2", text.strip())
    out = re.sub(r"([a-z])(?=[a-z])", r"\1*", out)
    return sympy.sympify(out.replace("^", "**"))


_CURVE_ARG = r"(?P<{name}>[-0-9a-z^ +]+?)"
#: 문면에서 (곡선, 직선족)을 읽는 세 형태 — 미지 상수 u는 answer_map의 유일한 키다.
_TANGENT_SHAPES = (
    # ① '직선 y = 3x + k가 곡선 y = … 위의 …에서 이 곡선에 접할 때'
    re.compile(
        r"직선 y = "
        + _CURVE_ARG.format(name="line")
        + r"(?:가|이) 곡선 y = "
        + _CURVE_ARG.format(name="curve")
        + r" 위의"
    ),
    # ② '점 (0, P)에서 곡선 y = …에 그은 접선' — 직선족 y = ux + P
    re.compile(
        r"점 \(0, (?P<p>-?\d+)\)에서 곡선 y = " + _CURVE_ARG.format(name="curve") + r"에 그은 접선"
    ),
    # ③ '곡선 y = x^2 + px + q가 곡선 y = …와 x = a인 점에서 접할 때' — p는 기울기 조건으로 정한다
    re.compile(
        r"곡선 y = "
        + _CURVE_ARG.format(name="family")
        + r"(?:가|이) 곡선 y = "
        + _CURVE_ARG.format(name="curve")
        + r"(?:와|과) x = (?P<a>-?\d+)인 점에서 접할"
    ),
)


def _independent_tangency_discriminant(item: DiffItem) -> sympy.Expr | None:
    """문면만 읽어 '곡선 - 직선족'의 x에 대한 판별식(미지 상수 u의 다항식)을 다시 만든다.

    ③형의 p는 두 곡선의 기울기가 x = a에서 같다는 조건으로 이 테스트가 직접 정한다(문면이 주는 정보만
    쓴다). 세 형태 중 어디에도 맞지 않으면 None.
    """
    x = sympy.Symbol("x")
    ((key, _),) = item.answer_map
    u = sympy.Symbol(key)
    for shape in _TANGENT_SHAPES:
        match = shape.search(item.question_text)
        if match is None:
            continue
        curve = _student_expr(match["curve"])
        groups = match.groupdict()
        if groups.get("line") is not None:
            line = _student_expr(match["line"])
        elif groups.get("p") is not None:
            line = u * x + int(match["p"])
        else:
            family = _student_expr(match["family"])
            a = int(match["a"])
            others = family.free_symbols - {x, u}
            (p_sym,) = others
            (p_val,) = sympy.solve(sympy.diff(family - curve, x).subs(x, a), p_sym)
            line = family.subs(p_sym, p_val)
        if line.free_symbols != {x, u}:
            return None
        return sympy.expand(sympy.discriminant(sympy.expand(curve - line), x))
    return None


def _is_proportional(left: sympy.Expr, right: sympy.Expr) -> bool:
    ratio = sympy.cancel(left / right)
    return not ratio.free_symbols and ratio != 0


def test_tangent_double_root_items_use_the_discriminant_not_a_derivative() -> None:
    """명세 probe_note — 접선 조건을 '접점에서 이중근' 항등식으로 쓰는 문항이 실제로 있다.

    판별식형 조건은 미분 평가(`Derivative`)를 쓰지 않는 독립 경로여야 한다(두 경로가 어긋나면 게이트가
    거부). 대표·응용·숙련도 슬롯에 걸쳐 있어야 한다.

    두 갈래를 센다 — (a) 이차 곡선의 판별식 `(b - m)**2 - 4*A*(c - k)` 문자열, (b) 삼차 곡선(3차 감사
    처분으로 숙련도의 접할 조건을 삼차로 바꿨다 — 이차 곡선은 판별식만으로 풀려 미분이 필요 없었다)의
    x에 대한 판별식. (b)는 문자열 모양으로 알아볼 수 없으므로 **문면에서 곡선·직선족을 읽어 판별식을
    다시 계산**하고 검산 조건의 좌변이 그것의 상수배인지 대조한다(생성기 코드 미사용 — 독립 재계산).
    """
    quadratic: list[DiffItem] = []
    cubic: list[DiffItem] = []
    for i in _all_items(P3DiffTangentLineGenerator):
        first = i.conditions if isinstance(i.conditions, str) else i.conditions[0]
        if "Derivative" in first:
            continue
        if "**2 - 4*" in first:
            quadratic.append(i)
            continue
        expected = _independent_tangency_discriminant(i)
        if expected is None:
            continue
        lhs, rhs = first.split(" = ")
        residual = sympy.expand(sympy.sympify(lhs) - sympy.sympify(rhs))
        assert _is_proportional(residual, expected), (i.question_text, first, expected)
        cubic.append(i)
    discriminant_items = quadratic + cubic
    slots = {i.slot for i in discriminant_items}
    assert {"representative", "applied", "mastery_check"} <= slots
    assert len(discriminant_items) >= 8
    # 숙련도의 삼차 접선 틀 셋(기울기 주고 k · y축 위의 점에서 그은 접선 · 두 곡선이 접함)이 전부
    # 판별식 경로를 쓴다 — 하나라도 다른 경로(항등식·미분 평가)로 돌아가면 개수가 줄어든다.
    assert {i.frame_id for i in cubic} == {
        "mastery-cubic-tangent-given-slope",
        "mastery-tangent-from-point-on-y-axis",
        "mastery-two-curves-touch-find-constant",
    }, {i.frame_id for i in cubic}
