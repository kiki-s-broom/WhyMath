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

개념별 면제(`_EXEMPT`)
---------------------
이 파일의 일부 검사는 *수치 평가형*(미분계수 값·단일 미지수·kebab 크로스링크 도달)을 전제로 쓰여 있어,
개념형·선택형·M-id 직접 연결 개념(02-05·06·08·09·10)이 구조상 만족하지 못하는 항목이 있다. 검사를
약화·삭제하지 않고 **면제를 명시 데이터(`_EXEMPT`)로** 둔다 — 면제된 개념도 면제 대상이 *아닌* 문항·
단언은 전부 그대로 검사받고, 각 면제는 ①왜 면제인지(근거) ②같은 불변식의 일반화판을 구현한 전용 테스트
(파일·함수명 — `test_exemptions_point_at_real_dedicated_tests`가 실재를 확인) ③면제가 여전히 필요한지
확인하는 *stale 가드*(면제 대상이 사라지거나 해소되면 red → 면제 삭제 신호)를 갖는다. 면제 키는
`test_exemption_keys_only_name_registered_concepts`가 등록부의 실재 개념만 가리키는지 잡는다.
"""

from __future__ import annotations

import json
import re
import typing
from collections.abc import Callable
from dataclasses import dataclass
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
from whymath_backend.l3.equivalent.p3_diff_equation_application_skeleton_generator import (
    P3DiffEquationApplicationGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_graph_shape_skeleton_generator import (
    P3DiffGraphShapeGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_mean_value_theorem_skeleton_generator import (
    P3DiffMeanValueTheoremGenerator,
)
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

_MIN_SKELETONS = 30
_MIN_FRAMES = 30
_CORPUS_ROOT = Path(__file__).resolve().parents[4] / "data" / "corpus"
# 4차 감사(2026-10-07) 표기 교정: 학생 대면 '√'·'≤'·'≥'는 *허용*한다 — 승인 은행 4종이 쓰는 표기이고
# 표기 커버리지 게이트(`l3/notation_coverage`) 베이스라인에 이미 있는 글리프라 신규 누락이 아니다.
# 대신 그 자리를 차지하던 코드 표기('<='·'>='·'sqrt('·'*')를 금지한다(`_CODE_NOTATION`).
_GLYPHS = ("²", "³", "Σ", "α", "β", "′")
_CODE_NOTATION = re.compile(r"<=|>=|sqrt\(|\*")

_ALL = pytest.mark.parametrize("generator_cls", GENERATORS, ids=lambda g: g.standard_code)

# ──────────────────────────────────────────────────────────────────────────
# 개념별 면제 — 명시 데이터(근거·전용 테스트 포인터). 모듈 docstring 참조.
# ──────────────────────────────────────────────────────────────────────────
_C05 = "[12미적Ⅰ-02-05]"
_C06 = "[12미적Ⅰ-02-06]"
_C08 = "[12미적Ⅰ-02-08]"
_C09 = "[12미적Ⅰ-02-09]"
_C10 = "[12미적Ⅰ-02-10]"
_F_TANGENT_VELOCITY = "test_p3_diff_tangent_velocity_generators.py"
_F_MVT_EQUATION = "test_p3_diff_mvt_equation_generators.py"
_F_GRAPH_SHAPE = "test_p3_diff_graph_shape_generator.py"


@dataclass(frozen=True)
class _Exempt:
    """면제 1건 — 근거(왜)와 같은 불변식을 구현한 전용 테스트 포인터(파일, 함수명)."""

    reason: str
    dedicated: tuple[tuple[str, str], ...]


_EXEMPT: dict[str, dict[str, _Exempt]] = {
    # 정답을 틀리게 주입(answer_map +1)해 게이트가 거부하는지 보는 변별력 검사 — 개념형 게이트 재료
    # (answer_kind·answer_aggregate·answer_selection)를 가진 후보는 이 파일의 주입 방식이 재료를 전달하지
    # 않아 *재료 누락 거부/통과*를 재게 된다. 그 후보만 건너뛴다(나머지 후보는 전건 거부를 그대로 요구).
    "gate_wrong_answer": {
        _C06: _Exempt(
            "02-06 개수·집계형 후보는 answer_map이 비어 주입 대상 키가 없다(개념형 검증기가 답을 판정).",
            ((_F_MVT_EQUATION, "test_gate_rejects_a_wrong_answer_for_every_item"),),
        ),
        _C08: _Exempt(
            "02-08 근 선택(answer_selection) 후보는 selection 없이 주입하면 '근 미확정'으로 강등될 뿐 "
            "Tier1 오답 거부와 구분되지 않는다 — 전용 테스트가 selection을 함께 넘겨 전건 거부를 요구한다.",
            ((_F_GRAPH_SHAPE, "test_gate_rejects_a_wrong_answer_for_every_item"),),
        ),
        _C09: _Exempt(
            "02-09 개수형(answer_kind)·합/곱(answer_aggregate)·근 선택 후보는 answer_map이 비거나 "
            "재료가 필요하다 — 전용 테스트가 재료를 함께 넘겨 전건 거부를 요구한다.",
            ((_F_MVT_EQUATION, "test_gate_rejects_a_wrong_answer_for_every_item"),),
        ),
    },
    # 극한 정의 재검산 하한(≥15건) — 02-06·08·09는 `Derivative(식, x).subs(x, 점) = y` 형태 문항이 거의
    # 없는 개념형·판정형 개념이다(하한 15는 수치 평가형 개념의 척도). 매칭된 문항의 정답 검산은 그대로 한다.
    "limit_definition_floor": {
        _C06: _Exempt(
            "02-06은 평균값 정리의 c값·구간 판정형이라 단일 미분계수 평가형이 2건뿐이다.",
            (
                (
                    _F_MVT_EQUATION,
                    "test_answers_match_an_independent_recomputation_from_the_conditions",
                ),
            ),
        ),
        _C08: _Exempt(
            "02-08은 극값 판정·그래프 개형형이라 단일 미분계수 평가형이 없다(f'의 근과 부호로 판정).",
            ((_F_GRAPH_SHAPE, "test_x_coordinate_answers_match_value_based_classification"),),
        ),
        _C09: _Exempt(
            "02-09는 방정식·부등식 활용형(개수·합·근 선택)이라 단일 미분계수 평가형이 없다.",
            (
                (
                    _F_MVT_EQUATION,
                    "test_answers_match_an_independent_recomputation_from_the_conditions",
                ),
            ),
        ),
    },
    # 섀도 채점 단일 미지수 계약 — (a) 02-06·09 개수·집계형은 문자열 조건에 자유기호 x가 있지만 답은
    # 근의 *개수·합·곱*이라 answer_map이 비어 있고, (b) 02-08은 문자열 목록 조건 `(y = 식, f' = 0)`이
    # 부등식 보호 없이 (x, y) 두 키를 쓴다(극값의 좌표·함숫값), (c) 02-09 최솟값형(3차 감사 처분으로
    # '등호가 성립하는 x'형을 대체)은 02-08 규칙 C3과 같은 (임계점 f' = 0, y = f[, 범위]) 목록 조건에
    # (x 또는 t, y) 두 키를 쓴다 — 범위 부등식(`x >= 0`)은 해를 가르는 보호가 아니라 정의역이다.
    # 셋 다 코퍼스 로더가 읽지 않는 형태라 `test_multi_symbol_population_is_frozen`(섀도 모집단 동결)에는
    # 들어가지 않는다 — 그 동결은 무약화.
    "single_unknown": {
        _C06: _Exempt(
            "개수·집계형 문항(answer_map 비어 있음)은 미지수가 답이 아니다.",
            ((_F_MVT_EQUATION, "test_no_function_valued_answers_and_single_unknown_contract"),),
        ),
        _C08: _Exempt(
            "극값 좌표·함숫값 문항은 (x, y) 두 값을 한 목록 조건으로 묶는다(P3-24 적재 파서가 집행).",
            ((_F_GRAPH_SHAPE, "test_every_row_passes_the_p324_enforcement_parser"),),
        ),
        _C09: _Exempt(
            "개수형 문항(answer_map 비어 있음)은 미지수가 답이 아니고, 최솟값형은 (x 또는 t, y) "
            "극값 좌표형 목록 조건이다(02-08 규칙 C3과 같은 구조 — 최솟점은 answer_map이 고정).",
            (
                (_F_MVT_EQUATION, "test_no_function_valued_answers_and_single_unknown_contract"),
                (
                    _F_MVT_EQUATION,
                    "test_answers_match_an_independent_recomputation_from_the_conditions",
                ),
            ),
        ),
    },
    # 핵심 오개념(M-id)이 크로스링크로 닿는지 — 02-05·08·10의 핵심 M0673·M0676·M0678은 MISC-40이 의도적으로
    # 미승격한 omission형·문맥 종속형이라 크로스링크 kebab이 없다. 오개념 유발 슬롯은 기존 kebab에 연결된다
    # (이 파일의 나머지 단언 — 카탈로그 실재·distractor_map 무결성 — 은 그대로).
    "core_crosslink_reach": {
        _C05: _Exempt(
            "핵심 M0673 미승격(MISC-40) — 기존 kebab power-rule-step-omitted(→ M0671)에 연결.",
            ((_F_TANGENT_VELOCITY, "test_core_misconception_is_reachable_through_crosslinks"),),
        ),
        _C08: _Exempt(
            "핵심 M0676 미승격(MISC-40) — critical-point-implies-extremum(→ M0080)에 연결.",
            ((_F_GRAPH_SHAPE, "test_misconception_chain_gap_is_documented_not_hidden"),),
        ),
        _C10: _Exempt(
            "핵심 M0678 미승격(MISC-40) — power-rule-step-omitted(→ M0671)에 연결.",
            ((_F_TANGENT_VELOCITY, "test_core_misconception_is_reachable_through_crosslinks"),),
        ),
    },
    # kebab 좌석 부재 — 02-06의 연결 오개념(M0674)이 L4 카탈로그에 kebab 좌석이 없어 distractor_map에
    # M-id를 직접 쓴다. 참조 무결성 검증자(`validate_distractor_map`)는 M-id를 위반으로 읽는다. **이 충돌은
    # 맞추지 않고 면제 + 좌석 신호(stale 가드: 좌석이 생기면 red)로 둔다** — 억지로 kebab을 지어내면 새 id를
    # 만드는 제약(MISC-40)을 어긴다.
    "kebab_seat_absent": {
        _C06: _Exempt(
            "핵심 M0674에 kebab 좌석 없음 — distractor_map이 M-id 직접 연결.",
            ((_F_MVT_EQUATION, "test_kebab_seat_absence_is_a_tripwire"),),
        ),
    },
    # 핵심 오개념 연결 정지 — 02-09의 핵심 M0677은 설명이 서술어 없이 끊긴 손상 문장이고 잘못된 *절차*를
    # 적지 않아, 연결 선지가 그 오개념에서 나오는 값인지 판정할 수 없었다(5회차 은행 감사 2026-10-08 · 판정자
    # 지적 12건 · 원문 정정 QUAL-14). 5회차 교정이 옮긴 M0615도 설명이 자기모순('두 개로 단정' 대 '(차수만큼
    # 근)')이라 6회차 감사(은행 감사 2회차)에서 같은 12건이 지적돼, 이제 절차가 하나로 적힌 L4 kebab
    # `extremum-value-vs-point-confused`(극값·극점 혼동 — 크로스링크 직접매핑 M0865)에 연결한다(좌석이 있어
    # kebab_seat_absent 면제는 지웠다). stale 가드: 핵심 M0677이 다시 연결되면 red.
    "core_link_suspended": {
        _C09: _Exempt(
            "핵심 M0677 설명 손상(QUAL-14) — 극값 자리에 극점 x좌표를 넣어 센 선지를 '극값·극점 혼동'에 연결.",
            (
                (
                    _F_MVT_EQUATION,
                    "test_equation_concept_links_extremum_point_until_m0677_is_repaired",
                ),
            ),
        ),
    },
}


def _is_exempt(test_key: str, generator_cls: type[P3DiffSlotGenerator]) -> bool:
    return generator_cls.standard_code in _EXEMPT[test_key]


def _gate_extras(obj: object) -> bool:
    """개념형 게이트 재료(kind·aggregate·selection)를 하나라도 갖는가."""
    return any(
        getattr(obj, name, None) is not None
        for name in ("answer_kind", "answer_aggregate", "answer_selection")
    )


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
    exempt = _is_exempt("gate_wrong_answer", generator_cls)
    rejected = 0
    total = 0
    skipped = 0
    for slot in SLOT_IDS:
        spec = generator_cls.spec_for(slot)
        for candidate in _candidates(generator_cls, slot):
            if exempt and (_gate_extras(candidate) or not candidate.answer_map):
                skipped += 1  # 면제: 개념형 게이트 재료 후보 — 전용 테스트가 같은 불변식을 건다
                continue
            total += 1
            # 면제 개념이 아니면 재료 후보·빈 answer_map이 하나도 없어야 한다(면제 누수 방지)
            assert exempt or (not _gate_extras(candidate) and candidate.answer_map)
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
    if exempt:  # stale 가드 — 면제 대상 후보가 사라졌으면 면제를 지운다
        assert skipped > 0, "면제(gate_wrong_answer)가 더는 필요 없다 — _EXEMPT에서 삭제"


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
        expr_parsed = sympy.sympify(match["expr"])
        if isinstance(expr_parsed, tuple) or item.conditions.count("Derivative(") != 1:
            # 이계도함수(`Derivative(f, t, t)`)·속도+가속도 합 같은 *복합* 형태는 이 검사의 단일 1계
            # 미분계수 정규식이 의도한 대상이 아니다(과거엔 여기서 AttributeError로 터졌다). 그 형태의
            # 극한 정의 재검산은 전용 테스트 `_limit_check`(test_p3_diff_tangent_velocity_generators.py
            # `test_value_answers_match_the_limit_definition`)가 맡는다.
            continue
        expr = expr_parsed
        point = int(match["pt"])
        by_definition = sympy.limit((expr.subs(var, point + h) - expr.subs(var, point)) / h, h, 0)
        claimed = dict(item.answer_map)["y"]
        assert sympy.simplify(by_definition - sympy.sympify(claimed)) == 0, item.question_text
        # 표기된 정답도 같은 값이어야 한다(단답형·객관식 공통).
        assert sympy.simplify(sympy.sympify(item.answer_text) - by_definition) == 0
        checked += 1
    if _is_exempt("limit_definition_floor", generator_cls):
        # 면제: 하한(≥15)만 — 매칭된 문항의 정답 재검산은 위에서 그대로 했다. stale 가드: 하한 미달일 때만 면제.
        assert checked < 15, "면제(limit_definition_floor)가 더는 필요 없다 — _EXEMPT에서 삭제"
    else:
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
    exempt = _is_exempt("single_unknown", generator_cls)
    str_checked = 0
    skipped = 0
    for item in _all_items(generator_cls):
        if exempt and _outside_single_unknown_form(item):
            skipped += 1  # 면제: 개수·집계형(빈 answer_map) · 부등식 보호 없는 좌표 목록 조건
            continue
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
    if exempt:
        # 면제 개념은 비율 하한 대신 "검사한 것 + 면제한 것 = 전부"로 닫고, stale 가드로 면제 필요를 확인한다.
        assert skipped > 0, "면제(single_unknown)가 더는 필요 없다 — _EXEMPT에서 삭제"
    else:
        assert skipped == 0
        assert str_checked >= 0.7 * len(_all_items(generator_cls))


def _outside_single_unknown_form(item: DiffItem) -> bool:
    """면제 대상 형태 — (a) answer_map이 빔(개수·집계형 — 문자열 조건이든, 6회차 감사 처분으로 범위 부등식이
    붙은 개수형 목록 조건 `(방정식, x > a, x < b)`든), (b) 부등식 보호 없는 목록 조건, (c) 극값 좌표형 목록
    조건(첫 조건이 임계점 `Derivative(…) = 0`이고 answer_map이 정확히 (x 또는 t, y)).

    (c)는 정의역 부등식(`x >= 0`)이 붙어 (b)로 분류되지 않는 02-09 최솟값형을 위한 것이다 — 키 집합을
    정확히 대조하므로 미지 상수(k·p)를 담은 목록 조건은 여기 걸리지 않고 아래 단일 미지수 검사를 받는다.
    """
    if not item.answer_map:
        return True
    if isinstance(item.conditions, str):
        return False
    keys = {k for k, _ in item.answer_map}
    if item.conditions[0].startswith("Derivative(") and keys in ({"x", "y"}, {"t", "y"}):
        return True
    return not any(re.search(r"[<>!]=?", c) for c in item.conditions[1:])


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
    reach_exempt = _is_exempt("core_crosslink_reach", generator_cls)
    seat_absent = _is_exempt("kebab_seat_absent", generator_cls)
    core_suspended = _is_exempt("core_link_suspended", generator_cls)
    reached: set[str] = set()
    linked_mc: set[str] = set()
    for slot in SLOT_IDS:
        linked = generator_cls.target_misconception_ids(slot)
        if slot != "misconception_trigger":
            assert linked == frozenset(), f"{slot}: 오개념 유발이 아닌 슬롯에 오개념이 연결됨"
            continue
        assert linked, "오개념 유발 슬롯에 연결된 오개념이 없다 — 센 문항이 0이다"
        linked_mc |= set(linked)
        for kebab in linked:
            if seat_absent:
                # 면제: kebab 좌석 없이 M-id를 직접 연결한다. 좌석이 생기면(카탈로그에 등장) red.
                if core_suspended:
                    # 핵심 연결 정지(면제 사유 참조) — 비핵심 M-id다.
                    assert kebab not in core, f"핵심 연결이 돌아왔다 — 면제 삭제: {kebab}"
                else:
                    assert kebab in core, f"좌석 없는 연결은 핵심 M-id여야 한다: {kebab}"
                assert (
                    kebab not in CATALOG_BY_ID
                ), f"kebab 좌석이 생겼다 — 생성기를 kebab 연결로 옮기고 면제 삭제: {kebab}"
                continue
            assert kebab in CATALOG_BY_ID, f"카탈로그에 없는 kebab: {kebab}"
            reached |= {
                row["mis_id"]
                for row in crosslinks
                if row["kebab_id"] == kebab and row["link_type"] == "직접매핑"
            }
        for candidate in _candidates(generator_cls, slot):
            assert candidate.problem.distractor_map, "오개념 유발 문항에 distractor_map이 없다"
            violations = validate_distractor_map(candidate.problem.distractor_map)
            if seat_absent:
                # L4 검증자가 M-id 직접 연결을 위반으로 읽는다 — 충돌을 *숨기지 않고* 신호로 고정한다.
                # 검증자가 M-id를 받아들이게 바뀌면(또는 좌석이 생기면) 이 단언이 red가 된다.
                assert violations, "validate_distractor_map이 M-id를 더는 위반으로 읽지 않는다"
            else:
                assert violations == []
    if core_suspended:
        # stale 가드 — 핵심 M-id가 다시 연결되면(QUAL-14 정정 뒤) 면제를 지운다.
        assert not core & linked_mc, f"핵심 {core}이 다시 연결됐다 — _EXEMPT에서 삭제"
    elif seat_absent:
        assert core <= linked_mc, f"핵심 M-id {core}가 직접 연결되지 않았다: {linked_mc}"
    elif reach_exempt:
        # stale 가드 — 크로스링크가 승격돼 핵심 오개념에 닿으면 면제를 지운다.
        assert not core <= reached, f"핵심 {core}이 크로스링크로 닿는다 — _EXEMPT에서 삭제"
    else:
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
            assert not _CODE_NOTATION.search(field), field
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
#: 가짜 문항의 검산 조건 — 빌드가 풀이 단계(`verify.solution_steps`)를 도출할 수 있어야 한다
#: (`_validate_slot`이 문항마다 전이 전건 correct인 연쇄를 만든다). f(x) = x의 x = 2 미분계수 = 1.
#: (7회차: x = 1이면 'power-rule-step-omitted' 선지 문항에서 지수 유지 경로 1·x^1도 1이라 판정기
#: T-power-path-coincidence에 걸린다 — 가짜 문항은 *건강한* 등록부여야 하므로 x = 2에서 잰다.)
_DERIVABLE = "Derivative(x, x).doit().subs(x, 2) = y"


def _item(
    slot: str,
    *,
    kebab: str | None,
    mc: bool = True,
    frame: str = "f",
    conditions: str = _DERIVABLE,
) -> DiffItem:
    return DiffItem(
        slot=slot,
        frame_id=frame,
        question_text=f"문항 {slot} {frame} {kebab}",
        answer_text="1",
        explanation="해설",
        conditions=conditions,
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
        (
            # 풀이 단계를 도출할 수 없는 검산 조건(미지수 2개·도함수 없음) — 빌드가 멈춘다.
            lambda d: d.__setitem__(
                "diagnostic", [_item("diagnostic", kebab=None, mc=False, conditions="x = y")]
            ),
            "풀이 단계 도출 실패",
        ),
    ],
    ids=[
        "mixed-kebab-sets",
        "mc-slot-without-kebab",
        "kebab-outside-mc-slot",
        "empty-slot",
        "underivable-steps",
    ],
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


def test_registry_holds_the_seven_concepts_in_order() -> None:
    """등록부에 02-03·04·05·06·08·09·10 생성기가 이 순서로 있다.

    각 생성기 *모듈명*을 이 테스트가 직접 import하는 것은 `tests/infra/test_path_scoped_counting_guard`
    (생성기 모듈마다 그 이름을 참조하는 테스트가 있어야 한다)를 위한 명시 참조이기도 하다 — 등록부 순회
    테스트만으로는 새 모듈명이 어느 테스트에도 안 나온다. **새 개념을 등록부에 더하면 여기에도 한 줄을
    더한다.**
    """
    assert GENERATORS == (
        P3DiffPowerDerivativeGenerator,
        P3DiffPolynomialRulesGenerator,
        P3DiffTangentLineGenerator,
        P3DiffMeanValueTheoremGenerator,
        P3DiffGraphShapeGenerator,
        P3DiffEquationApplicationGenerator,
        P3DiffVelocityAccelerationGenerator,
    )
    assert [g.standard_code for g in GENERATORS] == [
        "[12미적Ⅰ-02-03]",
        "[12미적Ⅰ-02-04]",
        _C05,
        _C06,
        _C08,
        _C09,
        _C10,
    ]
    assert len({g.standard_code for g in GENERATORS}) == len(GENERATORS)  # 개념당 생성기 1개


def test_exemption_keys_only_name_registered_concepts() -> None:
    """면제 키가 등록부의 실재 개념만 가리킨다 — 오타·삭제된 개념으로 면제가 새지 않는다."""
    registered = {g.standard_code for g in GENERATORS}
    for test_key, table in _EXEMPT.items():
        assert table, f"빈 면제 표: {test_key}"
        assert set(table) <= registered, (test_key, set(table) - registered)


def test_exemptions_point_at_real_dedicated_tests() -> None:
    """모든 면제가 가리키는 전용 테스트(파일·함수)가 실재한다 — 면제의 근거가 허공이 아니다."""
    here = Path(__file__).resolve().parent
    for test_key, table in _EXEMPT.items():
        for code, exempt in table.items():
            assert exempt.reason.strip() and exempt.dedicated, (test_key, code)
            for filename, func in exempt.dedicated:
                source = (here / filename).read_text(encoding="utf-8")
                assert re.search(rf"^def {re.escape(func)}\(", source, re.MULTILINE), (
                    test_key,
                    code,
                    filename,
                    func,
                )


def test_slot_ids_match_the_frozen_scope_spec() -> None:
    """슬롯 id·순서가 명세 `quantity_targets.slots`와 어긋나면(명세 변경) 즉시 드러난다."""
    assert tuple(slot.id for slot in load_scope_spec().slots) == SLOT_IDS
