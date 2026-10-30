"""Phase 3 Coverage 계측기 4종 — 정의·주입·적재·CLI 테스트 (P3-02).

이 테스트가 지키는 것
---------------------
계측기는 "연결이 끊기면 수치가 떨어진다"가 증명돼야 측정 도구다. 정상 입력에서 수치가 나오는 것은
증거가 아니다(모든 입력에서 같은 값을 내는 계측기도 같은 화면을 낸다). 그래서 이 파일은

  1. **전부 연결된 합성 세계**를 만들어 기준선(전 지표 100%)을 고정하고,
  2. 연결을 하나씩 끊는 주입을 가해 **어느 지표가 떨어지고 어느 지표는 그대로인지**를 표로 못박는다.
     '무언가 떨어진다'가 아니라 '이것만 떨어진다'를 단언해야 4개 지표가 서로 다른 것을 재고 있음이
     증명된다(전부 같이 떨어지는 계측기는 지표 하나를 네 번 낸 것이다).
  3. 주입은 `_inject` 가 "실제로 적용됐는가"를 단언한다(변경 전후가 같으면 정상 세계에 대해 테스트가
     돌고 초록이 검출처럼 보인다).
  4. 고립 개념 대조군 — 코퍼스에 이웃이 하나도 없는 개념은 연결 5종이 전부 missing 이어야 한다
     (필드 채움 검사가 통과시키던 바로 그 상태 · ARCH-43).

합성 세계는 실제 명세·실제 참조 색인 위에 얹는다(개념·원자·스킬·핵심 오개념은 실물, 문항·교수 목표·
힌트만 합성). 실제 코퍼스 기준선의 *수치*는 여기서 고정하지 않는다 — P3-03 이 채울 때마다 바뀌는
값이라 고정하면 정당한 진척이 테스트 실패가 된다. 기준선은 CLI 출력과 보고 문서가 소유한다.
"""

from __future__ import annotations

import asyncio
import json
import math
import shutil
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from whymath_backend.l1.standards import phase3_coverage as pc
from whymath_backend.l1.standards import phase3_scope as ps
from whymath_backend.schema.problem_metadata import (
    EMPTY_DIFFICULTY,
    ProblemMetadataField,
    ProblemSlot,
    slot_tag,
)

_REPO = Path(__file__).resolve().parents[3]
_KEYS = (
    "content_coverage_rate",
    "curriculum_coverage",
    "concept_completeness",
    "graph_connectivity_coverage",
    "supply_coverage",
)


# ──────────────────────────────────────────────────────────────────────────
# 픽스처 — 실제 명세·실제 참조 색인 + 전부 연결된 합성 세계
# ──────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def spec() -> ps.ScopeSpec:
    return ps.load_scope_spec()


@pytest.fixture(scope="module")
def index(spec: ps.ScopeSpec) -> ps.ReferenceIndex:
    return ps.load_reference_index(spec)


def _world(spec: ps.ScopeSpec, index: ps.ReferenceIndex) -> pc.CoverageCorpus:
    """핵심 개념마다 연결 5종·경로가 전부 성립하는 합성 코퍼스. 기준선은 전 지표 100% 다."""
    atom_nodes = set(index.atoms)
    edges: list[tuple[str, str]] = []
    problems: list[pc.ProblemRef] = []
    type_skills: dict[str, tuple[str, ...]] = {}
    crosslinks: dict[str, frozenset[str]] = {}
    content: dict[str, str | None] = {}
    objectives: list[pc.UnitObjective] = []
    for n, concept in enumerate(spec.core_concepts):
        atoms = tuple(a for a in index.crosswalk[concept.concept_id].atom_codes if a in index.atoms)
        skills = sorted(
            {s for a in atoms for s in index.atoms[a].behavior_skills if s in spec.skills}
        )
        mis_ids = [m.mis_id for m in spec.core_misconceptions if m.concept_code == concept.code]
        prerequisite = f"SYN-PRE-{n}"
        atom_nodes.add(prerequisite)
        edges.append((prerequisite, atoms[0]))
        type_skills[f"ptype.syn-{n}"] = tuple(skills)
        crosslinks[f"syn-kebab-{n}"] = frozenset(mis_ids[:1])
        problems.append(
            pc.ProblemRef(
                problem_id=f"syn-problem-{n}",
                primary_src_ids=frozenset({concept.source_id}),
                review_status="approved",
                has_explanation=True,
                has_steps=True,
                problem_type_codes=(f"ptype.syn-{n}",),
                distractor_ids=(f"syn-kebab-{n}",),
                # P3-04 — 7필드 축. 대조군은 "전부 연결된 세계"이므로 새 축도 채운다.
                difficulty=2.0,
                answer="7",
                solution_text="거듭제곱의 미분법에 따라 구한다.",
            )
        )
        content[concept.source_id] = "reviewed"
        objectives.append(pc.UnitObjective("syn-unit", "CONCEPT", frozenset({atoms[0]})))
    return pc.CoverageCorpus(
        atom_nodes=frozenset(atom_nodes),
        prerequisite_edges=tuple(edges),
        problems=tuple(problems),
        problems_scanned=len(problems),
        type_skills=type_skills,
        crosslinks=crosslinks,
        content_status=content,
        objectives=tuple(objectives),
        full_pack_k_types=frozenset({"CONCEPT"}),
        stub_pack_k_types=frozenset(),
        hint_problem_ids=frozenset(p.problem_id for p in problems),
    )


@pytest.fixture(scope="module")
def world(spec: ps.ScopeSpec, index: ps.ReferenceIndex) -> pc.CoverageCorpus:
    return _world(spec, index)


def _values(report: pc.CoverageReport) -> dict[str, float | None]:
    return {key: report.metric(key).value for key in _KEYS}


def _inject(world: pc.CoverageCorpus, **changes: Any) -> pc.CoverageCorpus:
    """주입 적용 + '정말 바뀌었는가' 단언 — 안 바뀌었으면 정상 세계로 테스트가 돈 것이다."""
    mutated = replace(world, **changes)
    assert mutated != world, "주입이 적용되지 않았다(변경 전후가 같다) — 하네스 결함"
    return mutated


# ──────────────────────────────────────────────────────────────────────────
# 대조군 — 전부 연결된 세계는 100% 이고 통과한다
# ──────────────────────────────────────────────────────────────────────────
class TestControl:
    def test_fully_linked_world_is_100_percent_and_passes(self, spec, index, world) -> None:
        report = pc.evaluate(spec, index, world)
        assert _values(report) == {key: 1.0 for key in _KEYS}
        assert report.failures == ()
        assert report.warnings == ()
        assert report.exit_code == 0
        assert all(m.unmet == () for m in report.metrics)

    def test_funnel_is_full_in_control_world(self, spec, index, world) -> None:
        n = len(spec.core_concepts)
        report = pc.evaluate(spec, index, world)
        assert report.chain_funnel == {"skill": n, "problem": n, "misconception": n, "pedagogy": n}

    def test_populations_come_from_the_frozen_spec(self, spec, index, world) -> None:
        report = pc.evaluate(spec, index, world)
        assert report.metric("content_coverage_rate").population == len(spec.core_concepts)
        assert report.metric("concept_completeness").population == len(spec.core_concepts)
        assert report.metric("curriculum_coverage").population == len(spec.nodes)


# ──────────────────────────────────────────────────────────────────────────
# 주입 표 — 어느 지표가 떨어지고 어느 지표는 그대로인가 (acceptance ③)
# ──────────────────────────────────────────────────────────────────────────
_ALL = set(_KEYS)


def _first(spec: ps.ScopeSpec) -> ps.ConceptEntry:
    return spec.core_concepts[0]


def _index_of(spec: ps.ScopeSpec, concept: ps.ConceptEntry) -> int:
    return list(spec.core_concepts).index(concept)


def _drop_problem(spec, index, w):
    k = _index_of(spec, _first(spec))
    return spec, _inject(w, problems=tuple(p for i, p in enumerate(w.problems) if i != k))


def _cut_skill_to_problem(spec, index, w):
    key = "ptype.syn-0"
    skills = dict(w.type_skills)
    skills[key] = ()
    return spec, _inject(w, type_skills=skills)


def _drop_content_row(spec, index, w):
    content = {k: v for k, v in w.content_status.items() if k != _first(spec).source_id}
    return spec, _inject(w, content_status=content)


def _add_node_without_concept(spec, index, w):
    node = ps.CurriculumNode(code="[99수00-00]", sub_domain="합성 노드(개념 없음)")
    return replace(spec, nodes=spec.nodes + (node,)), w


def _drop_prerequisite(spec, index, w):
    return spec, _inject(w, prerequisite_edges=w.prerequisite_edges[1:])


def _drop_pedagogy(spec, index, w):
    return spec, _inject(w, objectives=())


def _drop_crosslinks(spec, index, w):
    return spec, _inject(w, crosslinks={})


def _drop_misconception_attribution(spec, index, w):
    """핵심 오개념이 정확히 1개인 개념을 골라 그 귀속을 끊는다."""
    by_concept: dict[str, list[ps.CoreMisconception]] = {}
    for m in spec.core_misconceptions:
        by_concept.setdefault(m.concept_code, []).append(m)
    code = next(c for c, ms in by_concept.items() if len(ms) == 1)
    kept = tuple(m for m in spec.core_misconceptions if m.concept_code != code)
    assert kept != spec.core_misconceptions
    return replace(spec, core_misconceptions=kept), w


def _demote_review_status(spec, index, w):
    content = dict(w.content_status)
    content[_first(spec).source_id] = "ai_estimated"
    return spec, _inject(w, content_status=content)


def _pending_problem(spec, index, w):
    problems = list(w.problems)
    problems[0] = replace(problems[0], review_status="pending")
    return spec, _inject(w, problems=tuple(problems))


def _stub_pack(spec, index, w):
    return spec, _inject(w, full_pack_k_types=frozenset(), stub_pack_k_types=frozenset({"CONCEPT"}))


def _drop_steps(spec, index, w):
    problems = list(w.problems)
    problems[0] = replace(problems[0], has_steps=False)
    return spec, _inject(w, problems=tuple(problems))


def _drop_explanation(spec, index, w):
    problems = list(w.problems)
    problems[0] = replace(problems[0], has_explanation=False)
    return spec, _inject(w, problems=tuple(problems))


def _non_primary_tag(spec, index, w):
    """문항의 개념 태그가 PRIMARY 가 아니면 연결이 아니다 — 태그 집합이 비면 같은 효과다."""
    problems = list(w.problems)
    problems[0] = replace(problems[0], primary_src_ids=frozenset())
    return spec, _inject(w, problems=tuple(problems))


_INJECTIONS: list[tuple[str, Callable[..., Any], set[str]]] = [
    (
        "문항 연결 끊기",
        _drop_problem,
        {
            "content_coverage_rate",
            "curriculum_coverage",
            "concept_completeness",
            "graph_connectivity_coverage",
            "supply_coverage",
        },
    ),
    (
        "스킬→문항 연결 끊기(문제유형 스킬 비우기)",
        _cut_skill_to_problem,
        {
            "content_coverage_rate",
            "curriculum_coverage",
            "graph_connectivity_coverage",
            "supply_coverage",
        },
    ),
    ("개념 콘텐츠 행 삭제", _drop_content_row, {"content_coverage_rate", "supply_coverage"}),
    ("개념 없는 교육과정 노드 추가", _add_node_without_concept, {"curriculum_coverage"}),
    ("선수 간선 삭제", _drop_prerequisite, {"concept_completeness"}),
    (
        "교수 경로 제거(단원 DSL 목표 없음)",
        _drop_pedagogy,
        {"concept_completeness", "graph_connectivity_coverage"},
    ),
    ("오답 보기→오개념 크로스링크 삭제", _drop_crosslinks, {"graph_connectivity_coverage"}),
    (
        "핵심 오개념 귀속 삭제",
        _drop_misconception_attribution,
        {"concept_completeness", "graph_connectivity_coverage"},
    ),
    ("개념 콘텐츠 검수 상태 강등(ai_estimated)", _demote_review_status, {"supply_coverage"}),
    (
        "문항 검수 상태 pending",
        _pending_problem,
        {
            "content_coverage_rate",
            "curriculum_coverage",
            "concept_completeness",
            "graph_connectivity_coverage",
            "supply_coverage",
        },
    ),
    (
        "교수 팩이 stub 뿐",
        _stub_pack,
        {"concept_completeness", "graph_connectivity_coverage"},
    ),
    ("풀이 단계 삭제", _drop_steps, {"concept_completeness"}),
    ("해설 삭제", _drop_explanation, {"concept_completeness"}),
    (
        "PRIMARY 태그 제거",
        _non_primary_tag,
        {
            "content_coverage_rate",
            "curriculum_coverage",
            "concept_completeness",
            "graph_connectivity_coverage",
            "supply_coverage",
        },
    ),
]


@pytest.mark.parametrize(("name", "inject", "drops"), _INJECTIONS, ids=[i[0] for i in _INJECTIONS])
def test_injection_drops_exactly_the_expected_metrics(
    spec, index, world, name, inject, drops
) -> None:
    """연결을 끊으면 그 연결에 의존하는 지표**만** 떨어지고 나머지는 그대로다."""
    before = _values(pc.evaluate(spec, index, world))
    spec2, world2 = inject(spec, index, world)
    after = _values(pc.evaluate(spec2, index, world2))
    for key in _KEYS:
        assert before[key] is not None and after[key] is not None
        if key in drops:
            assert (
                after[key] < before[key]
            ), f"[{name}] {key} 가 떨어져야 하는데 {before[key]}→{after[key]}"
        else:
            assert (
                after[key] == before[key]
            ), f"[{name}] {key} 는 그대로여야 하는데 {before[key]}→{after[key]}"


def test_injection_table_covers_all_four_metrics_independently() -> None:
    """각 지표를 '혼자' 떨어뜨리는 주입이 표에 있어야 4개가 서로 다른 것을 재고 있다고 말할 수 있다."""
    solo = {next(iter(drops)) for _, _, drops in _INJECTIONS if len(drops) == 1}
    assert {
        "curriculum_coverage",
        "concept_completeness",
        "graph_connectivity_coverage",
        "supply_coverage",
    } <= solo
    # Content Coverage 는 공급 가능 커버리지와 함께만 떨어지는 주입(콘텐츠 행 삭제)이 독립 증거다.
    pair = {frozenset(drops) for _, _, drops in _INJECTIONS}
    assert frozenset({"content_coverage_rate", "supply_coverage"}) in pair


# ──────────────────────────────────────────────────────────────────────────
# 판정 — 목표 미달·분모 0 은 non-zero exit (지시문 항 4)
# ──────────────────────────────────────────────────────────────────────────
class TestVerdict:
    def test_single_broken_concept_misses_the_95_percent_target(self, spec, index, world) -> None:
        """분모 10 에서 95% 는 사실상 '전부'다 — 1개만 끊어도 90% 라 미달이다."""
        _, broken = _drop_problem(spec, index, world)
        report = pc.evaluate(spec, index, broken)
        content = report.metric("content_coverage_rate")
        assert (content.met_count, content.population) == (9, 10)
        assert content.met is False
        assert report.exit_code == 1
        assert any("Content Coverage Rate" in f for f in report.failures)

    def test_zero_core_concepts_is_failure_not_pass(self, spec, index, world) -> None:
        empty = replace(spec, concepts=tuple(replace(c, core=False) for c in spec.concepts))
        report = pc.evaluate(empty, index, world)
        for key in ("content_coverage_rate", "concept_completeness", "graph_connectivity_coverage"):
            metric = report.metric(key)
            assert metric.population == 0
            assert metric.value is None
        assert report.exit_code == 1
        assert any("분모가 0" in f for f in report.failures)
        assert report.metric("content_coverage_rate").met is False

    def test_zero_curriculum_nodes_is_failure_not_pass(self, spec, index, world) -> None:
        report = pc.evaluate(replace(spec, nodes=()), index, world)
        curriculum = report.metric("curriculum_coverage")
        assert curriculum.population == 0 and curriculum.value is None
        assert report.exit_code == 1
        assert any("Curriculum Coverage" in f and "분모가 0" in f for f in report.failures)

    def test_target_less_metric_does_not_change_exit_code(self, spec, index, world) -> None:
        """목표가 null 인 지표는 떨어져도 exit 을 바꾸지 않는다 — 판정이 없는 지표의 계약.

        실 명세는 Graph Connectivity 목표를 0.95 로 확정했으므로(P3-33) 이 경로는 실 명세로는
        더 닿지 않는다. 목표를 명시적으로 null 로 둔 명세를 만들어 그 계약을 계속 겨냥한다.
        """
        _, cut = _drop_crosslinks(spec, index, world)
        targets = {
            **spec.targets,
            "graph_connectivity_coverage": ps.Target(value=None, reason="테스트 — 목표 미정"),
        }
        report = pc.evaluate(replace(spec, targets=targets), index, cut)
        connectivity = report.metric("graph_connectivity_coverage")
        assert connectivity.value == 0.0
        assert connectivity.met is None and not connectivity.gated
        assert report.exit_code == 0

    def test_graph_connectivity_is_gated_by_the_confirmed_spec_target(
        self, spec, index, world
    ) -> None:
        """확정된 목표(0.95)가 판정을 만든다 — 크로스링크가 끊기면 미달이고 exit 1 이다.

        위 null 대조군과 한 쌍이다: 같은 위반 입력에서 목표가 null 이면 exit 0, 목표가 있으면
        exit 1 이어야 둘 다 변별력이 있다.
        """
        assert spec.targets["graph_connectivity_coverage"].value == 0.95
        _, cut = _drop_crosslinks(spec, index, world)
        report = pc.evaluate(spec, index, cut)
        connectivity = report.metric("graph_connectivity_coverage")
        assert connectivity.value == 0.0
        assert connectivity.gated and connectivity.met is False
        assert report.exit_code == 1
        # 성공 방향 대조군 — 위반 없는 세계는 같은 목표에서 충족이다
        clean = pc.evaluate(spec, index, world).metric("graph_connectivity_coverage")
        assert clean.gated and clean.met is True

    def test_supply_coverage_never_gates(self, spec, index, world) -> None:
        _, demoted = _demote_review_status(spec, index, world)
        report = pc.evaluate(spec, index, demoted)
        assert report.metric("supply_coverage").met is None
        assert report.exit_code == 0


# ──────────────────────────────────────────────────────────────────────────
# CONT-05 판정 ⓑ — 연결과 공급 가능을 병기하고 벌어지면 경고한다
# ──────────────────────────────────────────────────────────────────────────
class TestSupplySeparation:
    def test_review_status_does_not_change_linked_coverage(self, spec, index, world) -> None:
        reviewed = pc.evaluate(spec, index, world)
        content = {k: "ai_estimated" for k in world.content_status}
        unreviewed = pc.evaluate(spec, index, _inject(world, content_status=content))
        assert unreviewed.metric("content_coverage_rate").value == 1.0
        assert unreviewed.metric("supply_coverage").value == 0.0
        assert reviewed.metric("supply_coverage").value == 1.0

    def test_warning_names_the_gap(self, spec, index, world) -> None:
        content = {k: "ai_estimated" for k in world.content_status}
        report = pc.evaluate(spec, index, _inject(world, content_status=content))
        n = len(spec.core_concepts)
        assert any(f"{n}/{n}" in w and "0/" in w and "공급" in w for w in report.warnings)
        # 연결이 충족이라 exit 는 0 이다 — 검수 승격은 사람 서명의 몫이다.
        assert report.exit_code == 0

    def test_supply_uses_the_single_source_predicate(self) -> None:
        """공급 가능 판정은 CONT-05 의 술어를 그대로 쓴다 — 여기서 표기를 따로 정의하지 않는다."""
        from whymath_backend.l1.concept_content.review_gate import is_supply_eligible

        assert pc.is_supply_eligible is is_supply_eligible

    def test_unreviewed_variants_are_not_supplyable(self, spec, index, world) -> None:
        for bad in (None, "", "Reviewed", " reviewed ", "rejected", "ai_estimated"):
            content = {k: bad for k in world.content_status}
            report = pc.evaluate(spec, index, _inject(world, content_status=content))
            assert report.metric("supply_coverage").value == 0.0, bad


# ──────────────────────────────────────────────────────────────────────────
# Completeness 재설계 — 필드 채움이 아니라 해석되는 관계 (acceptance ④ · ARCH-43)
# ──────────────────────────────────────────────────────────────────────────
class TestCompletenessIsNotFieldFilling:
    def test_isolated_concept_has_all_five_links_missing(self, spec, index, world) -> None:
        """코퍼스에 이웃이 하나도 없는 개념 — 필드 채움 검사가 통과시키던 대조군이다."""
        k = _first(spec)
        n = _index_of(spec, k)
        atoms = tuple(a for a in index.crosswalk[k.concept_id].atom_codes if a in index.atoms)
        isolated = _inject(
            world,
            problems=tuple(p for i, p in enumerate(world.problems) if i != n),
            prerequisite_edges=tuple(e for e in world.prerequisite_edges if e[1] not in atoms),
            objectives=tuple(o for o in world.objectives if not (o.concept_nodes & set(atoms))),
            content_status={s: v for s, v in world.content_status.items() if s != k.source_id},
        )
        stripped = replace(
            spec,
            core_misconceptions=tuple(
                m for m in spec.core_misconceptions if m.concept_code != k.code
            ),
        )
        report = pc.evaluate(stripped, index, isolated)
        entry = next(u for u in report.metric("concept_completeness").unmet if u.subject == k.code)
        named = {line.split(":")[0] for line in entry.missing}
        assert named == set(pc.COMPLETENESS_LINKS)
        assert all("missing" not in line for line in entry.missing)  # 상태명이 아니라 사유를 적는다

    def test_unmet_entries_say_what_is_missing(self, spec, index, world) -> None:
        _, cut = _drop_problem(spec, index, world)
        report = pc.evaluate(spec, index, cut)
        entry = next(
            u
            for u in report.metric("content_coverage_rate").unmet
            if u.subject == _first(spec).code
        )
        assert any("승인된 PRIMARY 문항이 0건" in why for why in entry.missing)
        solution = next(
            u for u in report.metric("concept_completeness").unmet if u.subject == _first(spec).code
        )
        assert any(line.startswith("solution:") for line in solution.missing)

    def test_unmeasured_hint_is_not_complete(self, spec, index, world) -> None:
        """측정 불가는 충족이 아니다 — 다른 4개가 전부 linked 여도 완전하지 않다."""
        report = pc.evaluate(spec, index, _inject(world, hint_problem_ids=None))
        n = len(spec.core_concepts)
        assert report.metric("concept_completeness").met_count == 0
        assert report.link_counts["hint"] == {"linked": 0, "missing": 0, "unmeasured": n}
        assert report.completeness_measurable == (n, n)  # 측정 가능한 연결만 보면 완전(참고 수치)
        assert any("hint" in w and "측정 불가" in w for w in report.warnings)
        assert report.exit_code == 1  # Completeness 목표 미달로 실패

    def test_measured_empty_hint_is_missing_not_unmeasured(self, spec, index, world) -> None:
        """좌석이 생겨 측정했는데 힌트가 없으면 'missing' 이다 — 'unmeasured' 와 구별돼야 한다."""
        report = pc.evaluate(spec, index, _inject(world, hint_problem_ids=frozenset()))
        n = len(spec.core_concepts)
        assert report.link_counts["hint"] == {"linked": 0, "missing": n, "unmeasured": 0}
        assert report.completeness_measurable == (0, n)

    def test_hint_on_one_problem_links_only_that_concept(self, spec, index, world) -> None:
        only_first = frozenset({world.problems[0].problem_id})
        report = pc.evaluate(spec, index, _inject(world, hint_problem_ids=only_first))
        assert report.link_counts["hint"]["linked"] == 1

    def test_prerequisite_source_must_exist_as_an_atom(self, spec, index, world) -> None:
        """시작 원자가 백본에 없는 간선은 연결이 아니다 — 끊어진 참조를 세지 않는다."""
        ghost = tuple((f"GHOST-{i}", dst) for i, (_, dst) in enumerate(world.prerequisite_edges))
        report = pc.evaluate(spec, index, _inject(world, prerequisite_edges=ghost))
        assert report.link_counts["prerequisite"]["linked"] == 0

    def test_self_loop_is_not_a_prerequisite(self, spec, index, world) -> None:
        loops = tuple((dst, dst) for _, dst in world.prerequisite_edges)
        report = pc.evaluate(spec, index, _inject(world, prerequisite_edges=loops))
        assert report.link_counts["prerequisite"]["linked"] == 0

    def test_stub_pack_is_reported_with_its_reason(self, spec, index, world) -> None:
        _, stubbed = _stub_pack(spec, index, world)
        report = pc.evaluate(spec, index, stubbed)
        entry = report.metric("concept_completeness").unmet[0]
        assert any("stub" in line for line in entry.missing)

    def test_objective_on_another_concepts_atom_does_not_link(self, spec, index, world) -> None:
        shifted = tuple(
            replace(o, concept_nodes=frozenset({"SYN-NOT-AN-ATOM"})) for o in world.objectives
        )
        report = pc.evaluate(spec, index, _inject(world, objectives=shifted))
        assert report.link_counts["pedagogy"]["linked"] == 0


# ──────────────────────────────────────────────────────────────────────────
# Graph Connectivity — 경로는 한 줄이어야 한다 (고리마다 따로 있는 것은 경로가 아니다)
# ──────────────────────────────────────────────────────────────────────────
class TestConnectivityIsOnePath:
    def test_hops_on_different_problems_are_not_a_path(self, spec, index, world) -> None:
        """스킬을 매개로 이어진 문항과 오개념에 닿는 문항이 **다른 문항**이면 경로가 아니다."""
        k = _first(spec)
        skills = dict(world.type_skills)
        skills["ptype.syn-0"] = ()  # 문항 0 은 스킬이 안 맞고
        extra = pc.ProblemRef(
            problem_id="syn-skill-only",
            primary_src_ids=frozenset({k.source_id}),
            review_status="approved",
            has_explanation=True,
            has_steps=True,
            problem_type_codes=("ptype.syn-skill-only",),
            distractor_ids=(),  # 스킬은 맞지만 오개념에 안 닿는 문항
        )
        skills["ptype.syn-skill-only"] = world.type_skills["ptype.syn-0"]
        split = _inject(world, type_skills=skills, problems=world.problems + (extra,))
        report = pc.evaluate(spec, index, split)
        n = len(spec.core_concepts)
        # 개념 k: 스킬 문항(extra)은 있고, 오개념 닿는 문항(0)은 있지만 같은 문항이 아니다.
        assert report.metric("graph_connectivity_coverage").met_count == n - 1
        assert report.chain_funnel["problem"] == n
        assert report.chain_funnel["misconception"] == n - 1

    def test_funnel_shows_where_the_path_breaks(self, spec, index, world) -> None:
        _, cut = _drop_crosslinks(spec, index, world)
        report = pc.evaluate(spec, index, cut)
        n = len(spec.core_concepts)
        assert report.chain_funnel == {"skill": n, "problem": n, "misconception": 0, "pedagogy": 0}
        entry = report.metric("graph_connectivity_coverage").unmet[0]
        assert any("problem→misconception" in line for line in entry.missing)

    def test_funnel_is_monotonic_on_every_injection(self, spec, index, world) -> None:
        for name, inject, _ in _INJECTIONS:
            spec2, world2 = inject(spec, index, world)
            f = pc.evaluate(spec2, index, world2).chain_funnel
            assert f["skill"] >= f["problem"] >= f["misconception"] >= f["pedagogy"], name

    def test_direct_misconception_id_in_distractor_counts_without_crosslink(
        self, spec, index, world
    ) -> None:
        k = _first(spec)
        mis = next(m.mis_id for m in spec.core_misconceptions if m.concept_code == k.code)
        problems = list(world.problems)
        problems[0] = replace(problems[0], distractor_ids=(mis,))
        crosslinks = {key: v for key, v in world.crosslinks.items() if key != "syn-kebab-0"}
        report = pc.evaluate(
            spec, index, _inject(world, problems=tuple(problems), crosslinks=crosslinks)
        )
        assert report.metric("graph_connectivity_coverage").value == 1.0

    def test_misconception_outside_the_concepts_core_set_does_not_link(
        self, spec, index, world
    ) -> None:
        """오답 보기가 닿는 오개념이 **이 개념의** 핵심 오개념이 아니면 경로가 아니다."""
        k = _first(spec)
        other = next(m.mis_id for m in spec.core_misconceptions if m.concept_code != k.code)
        crosslinks = dict(world.crosslinks)
        crosslinks["syn-kebab-0"] = frozenset({other})
        report = pc.evaluate(spec, index, _inject(world, crosslinks=crosslinks))
        n = len(spec.core_concepts)
        assert report.metric("graph_connectivity_coverage").met_count == n - 1


# ──────────────────────────────────────────────────────────────────────────
# 명세 ↔ 계측 정의 정합 — 어긋나면 계측이 거짓이 된다
# ──────────────────────────────────────────────────────────────────────────
class TestSpecAlignment:
    def test_control_real_spec_is_aligned(self, spec, index, world) -> None:
        pc.evaluate(spec, index, world)  # 예외 없음

    def test_changed_required_links_is_rejected(self, spec, index, world) -> None:
        drifted = replace(spec, concept_required_links=spec.concept_required_links[:-1])
        with pytest.raises(pc.CoverageError, match="concept_required_links"):
            pc.evaluate(drifted, index, world)

    def test_changed_graph_path_is_rejected(self, spec, index, world) -> None:
        drifted = replace(spec, graph_path=tuple(reversed(spec.graph_path)))
        with pytest.raises(pc.CoverageError, match="graph_path"):
            pc.evaluate(drifted, index, world)

    def test_changed_curriculum_path_is_rejected(self, spec, index, world) -> None:
        drifted = replace(spec, curriculum_path=spec.curriculum_path[:-1])
        with pytest.raises(pc.CoverageError, match="curriculum_path"):
            pc.evaluate(drifted, index, world)

    @pytest.mark.parametrize(
        "key",
        [
            "content_coverage_rate",
            "curriculum_coverage",
            "concept_completeness",
            "graph_connectivity_coverage",
        ],
    )
    def test_missing_target_key_is_rejected(self, spec, index, world, key) -> None:
        targets = {k: v for k, v in spec.targets.items() if k != key}
        with pytest.raises(pc.CoverageError, match=key):
            pc.evaluate(replace(spec, targets=targets), index, world)

    def test_targets_are_read_from_the_spec_not_hardcoded(self, spec, index, world) -> None:
        """목표는 명세가 갖는다 — 코드가 자기 합격선을 박으면 명세 변경(PR)이 무의미해진다."""
        _, cut = _drop_problem(spec, index, world)
        lenient = dict(spec.targets)
        lenient["content_coverage_rate"] = ps.Target(value=0.5, reason=None)
        lenient["curriculum_coverage"] = ps.Target(value=0.5, reason=None)
        lenient["concept_completeness"] = ps.Target(value=0.5, reason=None)
        lenient["graph_connectivity_coverage"] = ps.Target(value=0.5, reason=None)
        report = pc.evaluate(replace(spec, targets=lenient), index, cut)
        assert report.metric("content_coverage_rate").met is True
        assert report.exit_code == 0


class TestDefinitionsBite:
    """실제 코퍼스에서는 효과가 없어 보이는 절(필터·경계)을 입력을 만들어 직접 겨냥한다.

    실제 데이터에서 값이 같은 절은 뮤테이션에서 '동등 변이'로 살아남아 검증된 가드의 일부로
    조용히 계상된다 — 그 절이 없을 때 통과하는 입력을 따로 넣어야 한다.
    """

    def test_skills_outside_the_spec_do_not_link(self, spec, index, world) -> None:
        narrowed = replace(spec, skills=("skill.not-in-any-atom",))
        report = pc.evaluate(narrowed, index, world)
        assert report.metric("content_coverage_rate").met_count == 0
        assert report.chain_funnel["skill"] == 0

    def test_atoms_outside_the_leaf_backbone_are_ignored(self, spec, index, world) -> None:
        k = _first(spec)
        cross = index.crosswalk[k.concept_id]
        widened = {
            **index.crosswalk,
            k.concept_id: ps.CrosswalkRef(
                primary_atom_code=cross.primary_atom_code,
                atom_codes=cross.atom_codes + ("NOT-A-LEAF-ATOM",),
            ),
        }
        before = _values(pc.evaluate(spec, index, world))
        after = _values(pc.evaluate(spec, replace(index, crosswalk=widened), world))
        assert after == before

    def test_misconception_attributed_to_another_standard_does_not_link(
        self, spec, index, world
    ) -> None:
        by_concept: dict[str, list[str]] = {}
        for m in spec.core_misconceptions:
            by_concept.setdefault(m.concept_code, []).append(m.mis_id)
        code, (only,) = next((c, ms) for c, ms in by_concept.items() if len(ms) == 1)
        moved = {**index.misconceptions, only: "[99수00-00]"}
        report = pc.evaluate(spec, replace(index, misconceptions=moved), world)
        assert report.link_counts["misconception"]["linked"] == len(spec.core_concepts) - 1
        assert any(
            u.subject == code and any(line.startswith("misconception:") for line in u.missing)
            for u in report.metric("concept_completeness").unmet
        )

    def test_foreign_misconception_is_not_adopted_by_attribution_alone(
        self, spec, index, world
    ) -> None:
        """명세가 다른 개념에 귀속한 M-id 를, 코퍼스가 이 개념에 귀속했다는 이유로 가져오지 않는다."""
        by_concept: dict[str, list[str]] = {}
        for m in spec.core_misconceptions:
            by_concept.setdefault(m.concept_code, []).append(m.mis_id)
        code = next(c for c, ms in by_concept.items() if len(ms) == 1)
        kept = tuple(m for m in spec.core_misconceptions if m.concept_code != code)
        foreign = ps.CoreMisconception(mis_id="M9999", concept_code="[99수00-00]")
        injected_spec = replace(spec, core_misconceptions=kept + (foreign,))
        injected_index = replace(index, misconceptions={**index.misconceptions, "M9999": code})
        report = pc.evaluate(injected_spec, injected_index, world)
        assert report.link_counts["misconception"]["linked"] == len(spec.core_concepts) - 1

    def test_target_boundary_is_inclusive(self, spec, index, world) -> None:
        """값이 목표와 같으면 충족이다(≥) — 목표 90% 에서 9/10 은 통과해야 한다."""
        _, cut = _drop_problem(spec, index, world)
        exact = {
            **spec.targets,
            "content_coverage_rate": ps.Target(value=0.9, reason=None),
            "curriculum_coverage": ps.Target(value=0.9, reason=None),
            "concept_completeness": ps.Target(value=0.9, reason=None),
            "graph_connectivity_coverage": ps.Target(value=0.9, reason=None),
        }
        report = pc.evaluate(replace(spec, targets=exact), index, cut)
        assert report.metric("content_coverage_rate").value == 0.9
        assert report.metric("content_coverage_rate").met is True
        assert report.exit_code == 0

    def test_non_core_concept_still_covers_its_curriculum_node(self, spec, index, world) -> None:
        """분모는 핵심 개념이지만 교육과정 노드의 경로는 핵심이 아닌 개념도 지난다."""
        k = _first(spec)
        demoted = replace(
            spec, concepts=tuple(replace(c, core=False) if c == k else c for c in spec.concepts)
        )
        report = pc.evaluate(demoted, index, world)
        assert report.metric("content_coverage_rate").population == len(spec.core_concepts) - 1
        assert report.metric("curriculum_coverage").value == 1.0

    def test_problem_skills_are_the_union_over_type_codes(self, spec, index, world) -> None:
        """문항의 스킬은 문제유형 코드 전부의 합집합이다 — 첫 유형만 보면 뒤 유형의 스킬이 사라진다."""
        skills = dict(world.type_skills)
        real = skills["ptype.syn-0"]
        skills["ptype.syn-0"] = ()
        skills["ptype.syn-0b"] = real
        problems = list(world.problems)
        problems[0] = replace(problems[0], problem_type_codes=("ptype.syn-0", "ptype.syn-0b"))
        report = pc.evaluate(
            spec, index, _inject(world, type_skills=skills, problems=tuple(problems))
        )
        assert report.metric("content_coverage_rate").value == 1.0

    def test_unknown_problem_type_code_links_nothing(self, spec, index, world) -> None:
        problems = list(world.problems)
        problems[0] = replace(problems[0], problem_type_codes=("ptype.never-defined",))
        report = pc.evaluate(spec, index, _inject(world, problems=tuple(problems)))
        assert report.metric("content_coverage_rate").met_count == len(spec.core_concepts) - 1


# ──────────────────────────────────────────────────────────────────────────
# 문항 행 해석 — 지표가 읽는 필드의 경계
# ──────────────────────────────────────────────────────────────────────────
def _row(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "problem_id": "p-1",
        "concepts": [{"concept_src_id": "H:x", "role": "PRIMARY", "relevance": 0.9}],
        "review_status": "approved",
        "answer_explanation": "해설",
        "verify": {"solution_steps": ["a"]},
        "problem_type_codes": ["ptype.a"],
        "distractor_map": [{"choice_index": 1, "misconception_id": "kebab-x"}],
    }
    base.update(over)
    return base


class TestProblemRow:
    def test_control_row_is_parsed(self) -> None:
        p = pc._problem_from_row(_row())
        assert p is not None
        assert p.primary_src_ids == frozenset({"H:x"})
        assert p.has_explanation and p.has_steps
        assert p.distractor_ids == ("kebab-x",)

    def test_non_primary_role_is_ignored(self) -> None:
        row = _row(concepts=[{"concept_src_id": "H:x", "role": "SECONDARY"}])
        p = pc._problem_from_row(row)
        assert p is not None and p.primary_src_ids == frozenset()

    @pytest.mark.parametrize("blank", ["", "   ", None, 7])
    def test_blank_explanation_is_not_an_explanation(self, blank) -> None:
        p = pc._problem_from_row(_row(answer_explanation=blank))
        assert p is not None and not p.has_explanation

    @pytest.mark.parametrize("steps", [[], None, "단계", {}])
    def test_empty_steps_are_not_steps(self, steps) -> None:
        p = pc._problem_from_row(_row(verify={"solution_steps": steps}))
        assert p is not None and not p.has_steps

    def test_missing_problem_id_is_skipped(self) -> None:
        row = _row()
        del row["problem_id"]
        assert pc._problem_from_row(row) is None

    def test_missing_review_status_is_not_eligible(self, spec, index, world) -> None:
        """필드가 없는 행은 '승인'이 아니다 — 문제은행 대다수가 이 상태다(`review_unset`)."""
        problems = list(world.problems)
        problems[0] = replace(problems[0], review_status=None)
        report = pc.evaluate(spec, index, _inject(world, problems=tuple(problems)))
        assert report.metric("content_coverage_rate").met_count == len(spec.core_concepts) - 1


# ──────────────────────────────────────────────────────────────────────────
# 적재 — 읽기 실패·0건은 CoverageError (조용한 통과 금지)
# ──────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def mini_repo(tmp_path_factory: pytest.TempPathFactory, spec: ps.ScopeSpec) -> Path:
    """실제 코퍼스 중 계측기가 읽는 것만 복사한 작은 저장소 — 파일 하나를 망가뜨려 보는 용도다."""
    root = tmp_path_factory.mktemp("mini_repo")
    needed = [
        spec.sources["atoms"],
        spec.sources["problem_types"],
        pc._CROSSLINKS,
        pc._CONCEPT_CONTENT,
        "data/corpus/units_v1/quadratic_maxmin.unit.yaml",
        "data/corpus/pedagogy_packs_v1/concept.yaml",
        "data/corpus/pedagogy_packs_v1/modeling.yaml",
    ]
    for rel in needed:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(_REPO / rel, target)
    bank = root / "data/corpus/problem_bank_synthetic/problems.jsonl"
    bank.parent.mkdir(parents=True, exist_ok=True)
    scope_src = spec.core_concepts[0].source_id
    rows = [
        _row(problem_id="in-scope", concepts=[{"concept_src_id": scope_src, "role": "PRIMARY"}]),
        _row(
            problem_id="out-of-scope", concepts=[{"concept_src_id": "H:other", "role": "PRIMARY"}]
        ),
    ]
    bank.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    return root


@pytest.fixture
def repo(mini_repo: Path, tmp_path: Path) -> Path:
    """테스트마다 새 복사본 — 한 테스트의 훼손이 다음 테스트로 새지 않는다."""
    target = tmp_path / "repo"
    shutil.copytree(mini_repo, target)
    return target


class TestLoader:
    def test_control_loads_and_keeps_only_scope_problems(self, spec, repo) -> None:
        corpus = pc.load_corpus(spec, repo)
        assert [p.problem_id for p in corpus.problems] == ["in-scope"]
        assert corpus.problems_scanned == 2  # 범위 밖 행도 읽었다(0건 방지 계수)
        assert corpus.hint_problem_ids is None  # 좌석이 없으면 측정 불가다
        assert corpus.full_pack_k_types == frozenset({"CONCEPT"})
        assert corpus.stub_pack_k_types == frozenset({"MODELING"})
        assert corpus.prerequisite_edges and corpus.atom_nodes

    def test_content_status_is_carried_from_the_corpus(self, spec, repo) -> None:
        raw = json.loads((repo / pc._CONCEPT_CONTENT).read_text(encoding="utf-8"))["content"]
        corpus = pc.load_corpus(spec, repo)
        assert len(corpus.content_status) == len({r["code"] for r in raw})
        for row in raw[:20]:
            assert corpus.content_status[row["code"]] == row.get("review_status"), row["code"]

    def test_type_skills_are_carried_from_the_corpus(self, spec, repo) -> None:
        corpus = pc.load_corpus(spec, repo)
        raw = [
            json.loads(line)
            for line in (repo / spec.sources["problem_types"]).read_text("utf-8").splitlines()
            if line.strip()
        ]
        assert len(corpus.type_skills) == len(raw)
        for row in raw:
            assert corpus.type_skills[row["problem_type_id"]] == tuple(row["behavior_skills"])

    def test_hint_seat_is_injected_by_the_caller(self, spec, repo) -> None:
        corpus = pc.load_corpus(spec, repo, hint_problem_ids=frozenset({"in-scope"}))
        assert corpus.hint_problem_ids == frozenset({"in-scope"})

    def test_empty_problem_bank_is_a_failure(self, spec, repo) -> None:
        (repo / "data/corpus/problem_bank_synthetic/problems.jsonl").write_text(
            "", encoding="utf-8"
        )
        with pytest.raises(pc.CoverageError, match="문항 코퍼스가 0건"):
            pc.load_corpus(spec, repo)

    def test_no_problem_bank_directory_is_a_failure(self, spec, repo) -> None:
        shutil.rmtree(repo / "data/corpus/problem_bank_synthetic")
        with pytest.raises(pc.CoverageError, match="문항 코퍼스가 0건"):
            pc.load_corpus(spec, repo)

    def test_malformed_problem_row_names_the_exception_type(self, spec, repo) -> None:
        (repo / "data/corpus/problem_bank_synthetic/problems.jsonl").write_text(
            "{not json\n", encoding="utf-8"
        )
        with pytest.raises(pc.CoverageError, match="JSONDecodeError"):
            pc.load_corpus(spec, repo)

    def test_missing_atom_graph_names_the_exception_type(self, spec, repo) -> None:
        (repo / spec.sources["atoms"]).unlink()
        with pytest.raises(pc.CoverageError, match="FileNotFoundError"):
            pc.load_corpus(spec, repo)

    def test_crosslinks_without_rows_is_a_failure(self, spec, repo) -> None:
        (repo / pc._CROSSLINKS).write_text('{"crosslinks": []}', encoding="utf-8")
        with pytest.raises(pc.CoverageError, match="크로스링크 코퍼스가 0건"):
            pc.load_corpus(spec, repo)

    def test_non_direct_crosslink_does_not_reach(self, spec, repo) -> None:
        rows = [
            {"kebab_id": "k-direct", "mis_id": "M0001", "link_type": "직접매핑"},
            {"kebab_id": "k-partial", "mis_id": "M0002", "link_type": "부분매핑"},
        ]
        (repo / pc._CROSSLINKS).write_text(json.dumps({"crosslinks": rows}), encoding="utf-8")
        corpus = pc.load_corpus(spec, repo)
        assert set(corpus.crosslinks) == {"k-direct"}

    def test_content_without_rows_is_a_failure(self, spec, repo) -> None:
        (repo / pc._CONCEPT_CONTENT).write_text('{"content": []}', encoding="utf-8")
        with pytest.raises(pc.CoverageError, match="개념 콘텐츠 코퍼스가 0건"):
            pc.load_corpus(spec, repo)

    def test_no_unit_dsl_is_a_failure(self, spec, repo) -> None:
        (repo / "data/corpus/units_v1/quadratic_maxmin.unit.yaml").unlink()
        with pytest.raises(pc.CoverageError, match="단원 DSL 코퍼스가 0건"):
            pc.load_corpus(spec, repo)

    def test_no_pedagogy_pack_is_a_failure(self, spec, repo) -> None:
        for path in (repo / "data/corpus/pedagogy_packs_v1").glob("*.yaml"):
            path.unlink()
        with pytest.raises(pc.CoverageError, match="교수 팩 코퍼스가 0건"):
            pc.load_corpus(spec, repo)

    def test_broken_unit_yaml_names_the_exception_type(self, spec, repo) -> None:
        (repo / "data/corpus/units_v1/quadratic_maxmin.unit.yaml").write_text(
            "a: [unclosed", encoding="utf-8"
        )
        with pytest.raises(pc.CoverageError, match="ParserError"):
            pc.load_corpus(spec, repo)

    def test_atom_graph_without_prerequisite_edges_is_a_failure(self, spec, repo) -> None:
        path = repo / spec.sources["atoms"]
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["edges"] = [e for e in doc["edges"] if e.get("relation") != "prerequisite"]
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(pc.CoverageError, match="선수 간선 코퍼스가 0건"):
            pc.load_corpus(spec, repo)

    def test_stub_flag_decides_the_pack_class(self, spec, repo) -> None:
        pack = repo / "data/corpus/pedagogy_packs_v1/concept.yaml"
        doc = yaml.safe_load(pack.read_text(encoding="utf-8"))
        doc["is_stub"] = True
        pack.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
        corpus = pc.load_corpus(spec, repo)
        assert corpus.full_pack_k_types == frozenset()
        assert corpus.stub_pack_k_types == frozenset({"CONCEPT", "MODELING"})


# ──────────────────────────────────────────────────────────────────────────
# 실제 코퍼스 — 수치는 고정하지 않고 적재가 조용히 0 으로 읽히지 않음을 본다
# ──────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def real_report(spec: ps.ScopeSpec, index: ps.ReferenceIndex) -> pc.CoverageReport:
    return pc.evaluate(spec, index, pc.load_corpus(spec))


class TestRealCorpus:
    def test_loader_reads_the_whole_problem_bank(self, spec) -> None:
        corpus = pc.load_corpus(spec)
        assert corpus.problems_scanned > 10_000
        assert corpus.problems  # 범위 안 문항이 하나도 안 읽히면 필드 해석이 깨진 것이다

    def test_independent_recount_matches_the_loader(self, spec, index) -> None:
        """로더와 **다른 경로**(평문 json)로 센 적격 문항 수가 같아야 한다 — 필드 이름이 바뀌어
        조용히 0 으로 읽히는 상태를 잡는다. 이 비교가 없으면 0/10 이 '데이터 없음'인지 '파싱 실패'인지
        숫자만으로는 구별되지 않는다."""
        corpus = pc.load_corpus(spec)
        raw: dict[str, set[str]] = {c.source_id: set() for c in spec.concepts}
        for path in sorted(_REPO.glob(pc._PROBLEM_GLOB)):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("review_status") != "approved":
                    continue
                for tag in row.get("concepts") or []:
                    if tag.get("role") == "PRIMARY" and tag.get("concept_src_id") in raw:
                        raw[tag["concept_src_id"]].add(row["problem_id"])
        for c in spec.concepts:
            facts = pc._facts(spec, index, corpus, c)
            assert {p.problem_id for p in facts.eligible} == raw[c.source_id], c.code
        assert sum(len(v) for v in raw.values()) > 0

    def test_every_input_kind_reaches_a_concept_on_real_data(self, spec, index) -> None:
        """입력 종류마다 '읽었는데 어떤 개념에도 안 닿는다'면 필드 해석이 조용히 깨진 것이다."""
        corpus = pc.load_corpus(spec)
        facts = [pc._facts(spec, index, corpus, c) for c in spec.concepts]
        assert any(f.content_present for f in facts)
        assert any(f.skills for f in facts)
        assert any(f.eligible for f in facts)
        assert any(f.skill_linked for f in facts)
        assert any(f.chain_problems for f in facts)
        assert any(f.prerequisite_sources for f in facts)
        assert corpus.objectives and corpus.full_pack_k_types
        assert corpus.crosslinks and corpus.type_skills

    def test_report_is_internally_consistent(self, spec, real_report) -> None:
        n = len(spec.core_concepts)
        for key in pc.COMPLETENESS_LINKS:
            assert sum(real_report.link_counts[key].values()) == n, key
        for key in _KEYS:
            metric = real_report.metric(key)
            assert metric.value is not None and 0.0 <= metric.value <= 1.0
        # 연결 여부만 세는 두 지표는 미충족 수가 분모 - 분자와 정확히 같다.
        for key in ("content_coverage_rate", "curriculum_coverage"):
            metric = real_report.metric(key)
            assert len(metric.unmet) == metric.population - metric.met_count, key
        f = real_report.chain_funnel
        assert f["skill"] >= f["problem"] >= f["misconception"] >= f["pedagogy"]

    def test_every_unmet_entry_says_what_is_missing(self, real_report) -> None:
        for metric in (*real_report.metrics, real_report.supply):
            for entry in metric.unmet:
                assert entry.missing, (metric.key, entry.subject)

    def test_hint_is_unmeasured_when_no_hint_input_is_given(self, spec, real_report) -> None:
        """P3-22 — 좌석(DB `hints.verified`)은 실재한다. 그래서 이 단언이 말하는 것은 '좌석이 없다'가
        아니라 '이 실행은 힌트를 읽지 않았다'(`--hints-from-db` 미지정)다. 입력이 없을 때 빈 집합으로
        위장하지 않고 unmeasured 로 남는 것을 동결한다. 좌석을 읽는 경로는 `TestHintSeatWiring`."""
        n = len(spec.core_concepts)
        assert real_report.link_counts["hint"] == {"linked": 0, "missing": 0, "unmeasured": n}
        assert real_report.hint_seat is None


# ──────────────────────────────────────────────────────────────────────────
# 힌트 좌석 배선 (P3-22) — DB hints(verified) → hint_problem_ids → Completeness
# ──────────────────────────────────────────────────────────────────────────
class _Scalars:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return list(self._values)


class _Result:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def scalars(self) -> _Scalars:
        return _Scalars(self._values)


class _FakeHintSession:
    """실제 문장(SQL)을 기록하고 정해 둔 값을 돌려준다 — 조건을 스스로 보태지 않는다.

    WHERE 를 가짜가 흉내 내면 리더에서 `verified` 조건이 빠져도 초록이므로, 조건의 유무는 컴파일된
    SQL 문자열로 따로 단언한다(`test_reader_asks_only_for_verified_distinct_problem_ids`).
    """

    def __init__(self, values: list[Any]) -> None:
        self.values = values
        self.sql: list[str] = []

    async def execute(self, stmt: Any) -> _Result:
        self.sql.append(str(stmt.compile()))
        return _Result(self.values)


def _read(values: list[Any]) -> frozenset[str]:
    return asyncio.run(pc.fetch_verified_hint_problem_ids(_FakeHintSession(values)))


class TestHintSeatWiring:
    def test_reader_asks_only_for_verified_distinct_problem_ids(self) -> None:
        session = _FakeHintSession([])
        asyncio.run(pc.fetch_verified_hint_problem_ids(session))
        sql = " ".join(session.sql).lower()
        assert "from hints" in sql
        assert "hints.verified is true" in sql  # 미검수 힌트는 학생에게 나갈 수 없다
        assert "distinct" in sql
        assert "hints.content" not in sql  # 본문은 읽지 않는다

    def test_reader_returns_uuid_as_text_so_it_matches_the_jsonl_bank(self) -> None:
        pid = uuid.UUID("c944bffa-4308-5c4e-b793-d2cbd8163c48")
        assert _read([pid, pid]) == frozenset({"c944bffa-4308-5c4e-b793-d2cbd8163c48"})

    def test_reader_with_no_rows_is_an_empty_set_not_none(self) -> None:
        """읽었는데 없다(missing)와 읽지 않았다(unmeasured)는 다른 사건이다."""
        assert _read([]) == frozenset()

    def test_db_hints_turn_unmeasured_into_linked(self, spec, index, world) -> None:
        # 합성 세계의 ID 는 문자열이라 UUID 가 아니다 — 문자열 그대로 읽은 집합을 쓴다.
        ids = _read([p.problem_id for p in world.problems])
        report = pc.evaluate(spec, index, replace(world, hint_problem_ids=ids))
        n = len(spec.core_concepts)
        assert report.link_counts["hint"] == {"linked": n, "missing": 0, "unmeasured": 0}
        assert report.metric("concept_completeness").value == 1.0

    def test_deleting_the_hints_from_the_seat_drops_completeness(self, spec, index, world) -> None:
        """acceptance ② — 좌석에서 힌트를 지우는 주입에 Completeness 가 실제로 떨어진다."""
        full = _read([p.problem_id for p in world.problems])
        before = pc.evaluate(spec, index, replace(world, hint_problem_ids=full))
        cut = _inject(replace(world, hint_problem_ids=full), hint_problem_ids=_read([]))
        after = pc.evaluate(spec, index, cut)
        assert before.metric("concept_completeness").value == 1.0
        assert after.metric("concept_completeness").value == 0.0
        n = len(spec.core_concepts)
        # 지운 것은 missing 이지 unmeasured 가 아니다 — 읽었는데 없는 것이다.
        assert after.link_counts["hint"] == {"linked": 0, "missing": n, "unmeasured": 0}
        # 힌트를 지워도 나머지 지표는 그대로다(힌트만 재는 연결이다).
        for key in ("content_coverage_rate", "curriculum_coverage", "graph_connectivity_coverage"):
            assert after.metric(key).value == before.metric(key).value, key

    def test_one_problem_hint_links_exactly_one_concept(self, spec, index, world) -> None:
        first = world.problems[0].problem_id
        report = pc.evaluate(spec, index, replace(world, hint_problem_ids=_read([first])))
        assert report.link_counts["hint"]["linked"] == 1
        assert report.link_counts["hint"]["unmeasured"] == 0

    def test_seat_stats_report_overlap_with_the_bank(self, spec, index, world) -> None:
        ids = frozenset({world.problems[0].problem_id, "db-only-problem"})
        seat = pc.evaluate(spec, index, replace(world, hint_problem_ids=ids)).hint_seat
        assert seat == pc.HintSeatStats(
            hinted_problems=2, in_scope_bank=1, eligible_hinted=1, outside_scope=1
        )

    def test_id_space_mismatch_is_warned_not_disguised_as_no_hints(
        self, spec, index, world
    ) -> None:
        """DB 힌트가 있는데 은행과 한 건도 안 겹치면 '힌트 0'이 아니라 ID 불일치 경고가 나온다."""
        ids = frozenset({"uuid-not-in-the-bank-1", "uuid-not-in-the-bank-2"})
        report = pc.evaluate(spec, index, replace(world, hint_problem_ids=ids))
        assert report.hint_seat is not None and report.hint_seat.in_scope_bank == 0
        assert any("ID 공간" in w for w in report.warnings)
        assert report.link_counts["hint"]["linked"] == 0

    def test_no_mismatch_warning_when_the_ids_overlap(self, spec, index, world) -> None:
        report = pc.evaluate(
            spec, index, replace(world, hint_problem_ids=_read([world.problems[0].problem_id]))
        )
        assert not any("ID 공간" in w for w in report.warnings)

    def test_json_and_text_carry_the_seat(self, spec, index, world) -> None:
        with_seat = pc.evaluate(spec, index, world)
        without = pc.evaluate(spec, index, replace(world, hint_problem_ids=None))
        assert pc.to_json(with_seat)["hint_seat"]["hinted_problems"] == len(world.problems)
        assert pc.to_json(without)["hint_seat"] is None
        assert "힌트 입력: DB 검수 통과" in pc.render(with_seat)
        assert "힌트 입력: 없음(측정 불가)" in pc.render(without)


class TestHintSeatCli:
    def test_default_run_never_touches_the_db(self, world, monkeypatch, capsys) -> None:
        def _boom(*a: Any, **k: Any) -> frozenset[str]:
            raise AssertionError("플래그 없이 DB 를 읽었다")

        monkeypatch.setattr(pc, "read_hint_problem_ids_from_db", _boom)
        monkeypatch.setattr(pc, "load_corpus", lambda s: world)
        pc.main([])  # 호출이 일어나면 AssertionError 로 터진다
        capsys.readouterr()

    def test_flag_passes_the_db_ids_into_the_corpus(self, world, monkeypatch, capsys) -> None:
        seen: dict[str, Any] = {}
        ids = frozenset({"p1", "p2"})
        monkeypatch.setattr(pc, "read_hint_problem_ids_from_db", lambda: ids)

        def _load(s: Any, repo_root: Any = None, *, hint_problem_ids: Any = None) -> Any:
            seen["ids"] = hint_problem_ids
            return world

        monkeypatch.setattr(pc, "load_corpus", _load)
        pc.main(["--hints-from-db"])
        capsys.readouterr()
        assert seen["ids"] == ids

    def test_unreadable_db_is_exit_2_with_the_exception_type(self, monkeypatch, capsys) -> None:
        async def _refuse() -> frozenset[str]:
            raise ConnectionRefusedError("db down")

        monkeypatch.setattr(pc, "_read_hint_problem_ids", _refuse)
        assert pc.main(["--hints-from-db"]) == 2
        err = capsys.readouterr().err
        assert "적재 실패" in err and "ConnectionRefusedError" in err  # 타입명이 남는다

    def test_hanging_db_times_out_instead_of_hanging_the_measurement(self, monkeypatch) -> None:
        async def _hang() -> frozenset[str]:
            await asyncio.sleep(30)
            return frozenset()

        monkeypatch.setattr(pc, "_read_hint_problem_ids", _hang)
        with pytest.raises(pc.CoverageError, match="TimeoutError"):
            pc.read_hint_problem_ids_from_db(timeout_s=0.05)

    def test_unmeasured_hint_is_still_a_failure_without_the_flag(
        self, world, monkeypatch, capsys
    ) -> None:
        """플래그가 없으면 힌트를 못 잰 채 Completeness 가 0 이라 exit 1 이다 — 통과로 위장하지 않는다."""
        monkeypatch.setattr(pc, "load_corpus", lambda s: replace(world, hint_problem_ids=None))
        assert pc.main([]) == 1
        assert "힌트 입력: 없음(측정 불가)" in capsys.readouterr().out


# ──────────────────────────────────────────────────────────────────────────
# CLI — exit code 가 판정이다
# ──────────────────────────────────────────────────────────────────────────
class TestCli:
    def test_exit_0_when_everything_is_linked(
        self, spec, index, world, monkeypatch, capsys
    ) -> None:
        monkeypatch.setattr(pc, "load_corpus", lambda s: world)
        assert pc.main([]) == 0
        out = capsys.readouterr().out
        assert "판정: 통과" in out

    def test_exit_1_when_a_target_is_missed(self, spec, index, world, monkeypatch, capsys) -> None:
        _, cut = _drop_problem(spec, index, world)
        monkeypatch.setattr(pc, "load_corpus", lambda s: cut)
        assert pc.main([]) == 1
        out = capsys.readouterr().out
        assert "판정: 미달" in out
        assert "미충족" in out

    def test_text_output_lists_unmet_concepts_with_reasons(
        self, spec, index, world, monkeypatch, capsys
    ) -> None:
        _, cut = _drop_problem(spec, index, world)
        monkeypatch.setattr(pc, "load_corpus", lambda s: cut)
        pc.main([])
        out = capsys.readouterr().out
        assert _first(spec).code in out
        assert "승인된 PRIMARY 문항이 0건이다" in out
        assert "경로 깔때기" in out

    def test_json_output_carries_values_and_unmet(
        self, spec, index, world, monkeypatch, capsys
    ) -> None:
        _, cut = _drop_problem(spec, index, world)
        monkeypatch.setattr(pc, "load_corpus", lambda s: cut)
        assert pc.main(["--json"]) == 1
        doc = json.loads(capsys.readouterr().out)
        assert doc["exit_code"] == 1
        keys = [m["key"] for m in doc["metrics"]]
        assert keys == list(_KEYS[:4])
        content = next(m for m in doc["metrics"] if m["key"] == "content_coverage_rate")
        assert (content["met_count"], content["population"]) == (9, 10)
        assert content["unmet"][0]["subject"] == _first(spec).code
        assert content["unmet"][0]["missing"]
        assert doc["supply_coverage"]["target"] is None

    def test_exit_2_when_the_spec_cannot_be_loaded(self, tmp_path, capsys) -> None:
        assert pc.main(["--spec", str(tmp_path / "missing.yaml")]) == 2
        assert "적재 실패" in capsys.readouterr().err

    def test_exit_2_and_refusal_when_the_population_is_polluted(self, tmp_path, capsys) -> None:
        """분모(명세)가 코퍼스와 어긋난 채로 잰 수치는 의미가 없다 — 측정을 거부한다."""
        doc = json.loads(json.dumps(yaml.safe_load(ps.default_spec_path().read_text("utf-8"))))
        doc["concepts"][0]["concept_id"] = "math.calculus.does-not-exist-injected"
        polluted = tmp_path / "polluted.yaml"
        polluted.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
        assert pc.main(["--spec", str(polluted)]) == 2
        err = capsys.readouterr().err
        assert "측정을 거부" in err and "does-not-exist-injected" in err

    def test_real_corpus_run_returns_a_verdict_not_a_crash(self, capsys) -> None:
        code = pc.main(["--json"])
        assert code in (0, 1)
        doc = json.loads(capsys.readouterr().out)
        assert doc["exit_code"] == code
        assert [m["population"] for m in doc["metrics"]] == [10, 10, 10, 10]

    def test_corpus_load_failure_is_exit_2_not_a_zero_pass(self, monkeypatch, capsys) -> None:
        def boom(spec: ps.ScopeSpec) -> pc.CoverageCorpus:
            raise pc.CoverageError("문항 코퍼스가 0건이다")

        monkeypatch.setattr(pc, "load_corpus", boom)
        assert pc.main([]) == 2
        assert "CoverageError" in capsys.readouterr().err


# ──────────────────────────────────────────────────────────────────────────
# P3-04 — Problem 필수 7필드 현황 + 문제 유형 6슬롯 충족
# ──────────────────────────────────────────────────────────────────────────
_F = ProblemMetadataField
_S = ProblemSlot


def _slotted(world: pc.CoverageCorpus) -> pc.CoverageCorpus:
    """핵심 개념마다 6슬롯 문항을 하나씩 — 기본 문항을 복제하고 슬롯 태그만 달리한다(60문항)."""
    problems = [
        replace(base, problem_id=f"{base.problem_id}-{slot.value}", tags=(slot_tag(slot),))
        for base in world.problems
        for slot in ProblemSlot
    ]
    return replace(
        world,
        problems=tuple(problems),
        problems_scanned=len(problems),
        hint_problem_ids=frozenset(p.problem_id for p in problems),
    )


@pytest.fixture(scope="module")
def slotted(world: pc.CoverageCorpus) -> pc.CoverageCorpus:
    return _slotted(world)


def _clone_of(corpus: pc.CoverageCorpus, slot: ProblemSlot, nth: int = 0) -> pc.ProblemRef:
    return [p for p in corpus.problems if p.problem_id.endswith(f"-{slot.value}")][nth]


def _swap(
    corpus: pc.CoverageCorpus, target: pc.ProblemRef, **changes: Any
) -> tuple[pc.CoverageCorpus, pc.ProblemRef]:
    """문항 하나를 바꿔 끼운다. 바뀐 문항도 돌려준다 — 주입이 적용됐는지 호출부가 단언한다."""
    new = replace(target, **changes)
    assert new != target, "주입이 적용되지 않았다(변경 전후가 같다) — 하네스 결함"
    problems = tuple(new if p is target else p for p in corpus.problems)
    return replace(corpus, problems=problems), new


class TestProblemMetadataAndSlots:
    def test_control_every_problem_has_all_seven_fields_and_all_slots_are_filled(
        self, spec, index, slotted
    ) -> None:
        report = pc.evaluate(spec, index, slotted)
        stats = report.problem_metadata
        assert stats is not None and report.slots is not None
        assert (stats.population, stats.complete, stats.without_missing) == (60, 60, 60)
        assert stats.unmet == () and stats.unmeasured_fields == ()
        assert all(c["present"] == 60 for c in stats.field_counts.values())
        assert (report.slots.met_count, report.slots.population) == (60, 60)
        assert report.slots.unmet == ()
        assert report.failures == () and report.warnings == () and report.exit_code == 0

    # ── 7필드: 하나씩 비우는 주입 — 그 필드만 비고 CI 가 실패한다 ─────────────────────
    @pytest.mark.parametrize(
        "field",
        [f for f in ProblemMetadataField if f is not ProblemMetadataField.CONCEPT],
        ids=lambda f: f.value,
    )
    def test_blanking_one_field_of_one_problem_is_flagged_and_only_that_field(
        self, spec, index, slotted, field
    ) -> None:
        target = _clone_of(slotted, _S.REPRESENTATIVE)
        if field is _F.DIFFICULTY:
            broken, _ = _swap(slotted, target, difficulty=EMPTY_DIFFICULTY)
        elif field is _F.SKILL:
            broken, _ = _swap(slotted, target, problem_type_codes=())
        elif field is _F.SOLUTION:
            broken, _ = _swap(slotted, target, solution_text="")
        elif field is _F.ANSWER:
            broken, _ = _swap(slotted, target, answer="  ")
        elif field is _F.MISCONCEPTION_SIGNATURE:
            # 오개념 유발 슬롯 문항에서 문항 자체 연결을 지운다 — 개념 상속으로는 인정되지 않는다.
            target = _clone_of(slotted, _S.MISCONCEPTION_TRIGGER)
            broken, _ = _swap(slotted, target, distractor_ids=())
        else:
            assert field is _F.HINT_STRATEGY
            assert slotted.hint_problem_ids is not None
            hints = slotted.hint_problem_ids - {target.problem_id}
            broken = replace(slotted, hint_problem_ids=hints)
            assert broken != slotted
        report = pc.evaluate(spec, index, broken)
        stats = report.problem_metadata
        assert stats is not None
        counts = {name: c["missing"] for name, c in stats.field_counts.items()}
        assert counts == {name: int(name == field.value) for name in counts}, counts
        assert [u.subject for u in stats.unmet] == [target.problem_id]
        assert stats.unmet[0].missing == (f"{field.value}: 비어 있다",)
        assert (stats.complete, stats.without_missing) == (59, 59)
        assert report.exit_code == 1
        assert any("문제 메타데이터 7필드" in f and "1건" in f for f in report.failures)

    def test_concept_field_cannot_be_blank_for_an_in_scope_problem_it_leaves_the_scope(
        self, spec, index, slotted
    ) -> None:
        """범위 안 문항은 정의상 PRIMARY 개념이 있다 — 그것을 지우면 '결손'이 아니라 범위 밖이 된다.

        그래서 코퍼스 쪽에서 이 필드의 결손은 분모 감소로 나타난다(실 코퍼스 래칫이 분모 하한을 건다).
        """
        target = _clone_of(slotted, _S.BASIC)
        broken, _ = _swap(slotted, target, primary_src_ids=frozenset())
        stats = pc.evaluate(spec, index, broken).problem_metadata
        assert stats is not None
        assert stats.population == 59 and stats.unmet == ()

    def test_unmeasured_hint_is_reported_not_counted_and_not_a_failure(
        self, spec, index, slotted
    ) -> None:
        report = pc.evaluate(spec, index, replace(slotted, hint_problem_ids=None))
        stats = report.problem_metadata
        assert stats is not None
        assert stats.field_counts["hint_strategy"] == {"present": 0, "missing": 0, "unknown": 60}
        assert stats.unmeasured_fields == ("hint_strategy",)
        assert (stats.complete, stats.without_missing) == (
            0,
            60,
        ), "측정 불가를 충족으로 세면 안 된다"
        assert not any("문제 메타데이터" in f for f in report.failures)
        assert any("측정 불가 필드: hint_strategy" in w for w in report.warnings)

    def test_inherited_only_signature_is_counted_separately(self, spec, index, slotted) -> None:
        """대조군 — 오개념 유발이 아닌 슬롯은 개념 상속으로 인정되고, 그 비율이 따로 센다."""
        base = pc.evaluate(spec, index, slotted).problem_metadata
        assert base is not None
        target = _clone_of(slotted, _S.REPRESENTATIVE)
        weaker, _ = _swap(slotted, target, distractor_ids=())
        stats = pc.evaluate(spec, index, weaker).problem_metadata
        assert stats is not None
        assert stats.field_counts["misconception_signature"]["missing"] == 0
        assert stats.inherited_only == base.inherited_only + 1
        assert stats.unmet == ()

    # ── 6슬롯: 하나씩 비우는 주입 — 그 칸 하나만 떨어진다 ─────────────────────────────
    @pytest.mark.parametrize("slot", list(ProblemSlot), ids=lambda s: s.value)
    def test_removing_one_slot_tag_drops_exactly_one_cell(self, spec, index, slotted, slot) -> None:
        control = pc.evaluate(spec, index, slotted)
        target = _clone_of(slotted, slot)
        broken, _ = _swap(slotted, target, tags=())
        report = pc.evaluate(spec, index, broken)
        assert report.slots is not None and control.slots is not None
        assert report.slots.met_count == control.slots.met_count - 1 == 59
        assert len(report.slots.unmet) == 1
        names = {s.id: s.name_ko for s in spec.slots}
        assert report.slots.unmet[0].missing[0].startswith(f"{names[slot.value]}:")
        # 다른 네 지표는 그대로 — 슬롯 지표가 독립된 축을 잰다는 증거.
        assert _values(report) == _values(control)
        assert not any("Slot" in f for f in report.failures)  # 목표가 없는 지표는 exit 에 불참

    def test_trigger_slot_counts_only_problems_with_their_own_signature(
        self, spec, index, slotted
    ) -> None:
        target = _clone_of(slotted, _S.MISCONCEPTION_TRIGGER)
        broken, _ = _swap(slotted, target, distractor_ids=())
        report = pc.evaluate(spec, index, broken)
        assert report.slots is not None
        assert report.slots.met_count == 59
        assert "문항 자체 오개념 연결이 없는 1건은 세지 않는다" in report.slots.unmet[0].missing[0]

    def test_ineligible_problem_does_not_fill_a_slot(self, spec, index, slotted) -> None:
        target = _clone_of(slotted, _S.APPLIED)
        broken, _ = _swap(slotted, target, review_status="pending")
        report = pc.evaluate(spec, index, broken)
        assert report.slots is not None and report.slots.met_count == 59

    def test_unknown_slot_tag_is_a_failure_and_leaves_the_cell_empty(
        self, spec, index, slotted
    ) -> None:
        """오타(`p3-slot:aplied`)를 조용히 무시하면 그 문항은 슬롯이 없는 것으로 보일 뿐이다."""
        target = _clone_of(slotted, _S.APPLIED)
        broken, _ = _swap(slotted, target, tags=("p3-slot:aplied",))
        report = pc.evaluate(spec, index, broken)
        assert report.exit_code == 1
        assert any("알 수 없는 슬롯 태그" in f and "p3-slot:aplied" in f for f in report.failures)
        assert report.slots is not None and report.slots.met_count == 59

    # ── 정의 정합 — 명세가 다른 필드·슬롯을 말하면 측정을 거부한다 ──────────────────────
    def test_refuses_to_measure_when_the_spec_names_different_fields(
        self, spec, index, slotted
    ) -> None:
        changed = replace(spec, problem_required_fields=spec.problem_required_fields[:-1])
        assert changed != spec
        with pytest.raises(pc.CoverageError, match="problem_required_fields"):
            pc.evaluate(changed, index, slotted)

    def test_refuses_to_measure_when_the_spec_names_different_slots(
        self, spec, index, slotted
    ) -> None:
        changed = replace(spec, slots=spec.slots[:-1])
        assert changed != spec
        with pytest.raises(pc.CoverageError, match="슬롯"):
            pc.evaluate(changed, index, slotted)

    # ── 출력 ─────────────────────────────────────────────────────────────────────
    def test_json_and_text_carry_the_new_sections(self, spec, index, slotted) -> None:
        report = pc.evaluate(spec, index, replace(slotted, hint_problem_ids=None))
        doc = pc.to_json(report)
        assert doc["slot_coverage"]["population"] == 60
        assert doc["problem_metadata"]["field_counts"]["hint_strategy"]["unknown"] == 60
        assert doc["problem_metadata"]["unmeasured_fields"] == ["hint_strategy"]
        text = pc.render(report)
        assert "Concept Slot Coverage(6슬롯)" in text
        assert "문제 메타데이터 7필드 (적격 문항 60건)" in text
        assert "측정 불가 필드: hint_strategy" in text

    def test_metric_lookup_finds_the_slot_metric(self, spec, index, slotted) -> None:
        assert pc.evaluate(spec, index, slotted).metric("slot_coverage").population == 60


# ──────────────────────────────────────────────────────────────────────────
# P3-05 — 슬롯 계수가 "문항 수"가 아니라 "서로 다른 문제 수"를 센다
# ──────────────────────────────────────────────────────────────────────────
# 슬롯당 최소가 1건이면 어떤 중복 기준도 칸 수를 바꾸지 못한다(한 건이면 채워진다). 그래서 이 클래스는
# 슬롯당 최소를 2로 올린 명세에서 본다 — 그때 비로소 "같은 문제 2건"과 "다른 문제 2건"이 갈린다.
_STEM_A = "함수 f(x) = x^3 - 3x 의 극값의 개수를 구하시오."
_STEM_B = "함수 f(x) = x^3 - 3x 의 변곡점의 개수를 구하시오."


def _with_stems(
    corpus: pc.CoverageCorpus, slot: ProblemSlot, stems: list[str | None]
) -> pc.CoverageCorpus:
    """한 슬롯의 문항 하나를 stems 만큼으로 불려 각자 다른 문면을 단다(첫 칸만, 나머지 칸은 그대로)."""
    target = _clone_of(corpus, slot)
    extra = [
        replace(target, problem_id=f"{target.problem_id}-dup{n}", question_text=text)
        for n, text in enumerate(stems[1:], start=1)
    ]
    first = replace(target, question_text=stems[0])
    problems = tuple(first if p is target else p for p in corpus.problems) + tuple(extra)
    return replace(corpus, problems=problems, problems_scanned=len(problems))


class TestSlotCountsDistinctProblemsNotProblems:
    @pytest.fixture(scope="class")
    def strict_spec(self, spec: ps.ScopeSpec) -> ps.ScopeSpec:
        changed = replace(spec, min_distinct_per_slot=2, total_min_distinct_problems=120)
        assert changed != spec
        return changed

    def test_control_without_stems_every_problem_counts_so_two_problems_fill_a_cell(
        self, strict_spec, index, slotted
    ) -> None:
        """대조군 — 문면을 모르는 문항은 합쳐지지 않는다(모르면서 합치지 않는다). 2건이면 채워진다."""
        corpus = _with_stems(slotted, _S.BASIC, [None, None])
        report = pc.evaluate(strict_spec, index, corpus)
        assert report.slots is not None
        # 기본 슬롯은 2건이 됐지만 나머지 5칸은 1건뿐이라 최소 2에 못 미친다.
        names = {s.id: s.name_ko for s in strict_spec.slots}
        basic_cells = [
            m for u in report.slots.unmet for m in u.missing if m.startswith(f"{names['basic']}:")
        ]
        assert len(basic_cells) == len(strict_spec.core_concepts) - 1, basic_cells

    def test_numbers_only_copies_do_not_fill_a_cell_that_needs_two_distinct_problems(
        self, strict_spec, index, slotted
    ) -> None:
        """핵심 — 숫자만 바꾼 복제 2건은 같은 문제다. 문항은 2건이지만 서로 다른 문제는 1건이다."""
        same_problem = [_STEM_A.replace("3", "5"), _STEM_A.replace("3", "7")]
        assert same_problem[0] != same_problem[1]  # 문면 자체는 다르다(숫자가 다르다)
        corpus = _with_stems(slotted, _S.BASIC, same_problem)
        report = pc.evaluate(strict_spec, index, corpus)
        assert report.slots is not None
        names = {s.id: s.name_ko for s in strict_spec.slots}
        gaps = [
            m for u in report.slots.unmet for m in u.missing if m.startswith(f"{names['basic']}:")
        ]
        # 복제를 넣은 개념의 기본 칸도 비어 있어야 한다 — 문항 수로 셌다면 채워졌을 것이다.
        assert len(gaps) == len(strict_spec.core_concepts), gaps
        assert any("서로 다른 문제 1건" in g and "문항 2건" in g for g in gaps), gaps

    def test_structurally_different_problems_fill_the_cell(
        self, strict_spec, index, slotted
    ) -> None:
        """대조군 — 같은 2건이라도 구조가 다르면 서로 다른 문제 2건이라 채워진다."""
        corpus = _with_stems(slotted, _S.BASIC, [_STEM_A, _STEM_B])
        report = pc.evaluate(strict_spec, index, corpus)
        assert report.slots is not None
        names = {s.id: s.name_ko for s in strict_spec.slots}
        gaps = [
            m for u in report.slots.unmet for m in u.missing if m.startswith(f"{names['basic']}:")
        ]
        assert len(gaps) == len(strict_spec.core_concepts) - 1, gaps

    def test_unfolded_count_is_reported_in_the_note(self, spec, index, slotted) -> None:
        """작동한 비율 — 문면을 몰라 접지 못한 문항이 몇 건인지 지표가 말한다(침묵하지 않는다)."""
        note = pc.evaluate(spec, index, slotted).metric("slot_coverage").note
        assert note is not None and "문면 미확인 60건" in note, note
        known = replace(
            slotted,
            problems=tuple(
                replace(p, question_text=f"문항 {n} 번 문제")
                for n, p in enumerate(slotted.problems)
            ),
        )
        note_known = pc.evaluate(spec, index, known).metric("slot_coverage").note
        assert note_known is not None and "문면 미확인 0건" in note_known, note_known


class TestProblemRowToEvidence:
    """코퍼스 행 → `ProblemRef` 변환. 실 코퍼스에는 빈 필드가 한 건도 없어서, 이 변환이 "비어 있으면
    비어 있다"로 읽는지는 실 코퍼스 테스트로 볼 수 없다 — 합성 행으로 직접 잰다."""

    _ROW: dict[str, Any] = {
        "problem_id": "p-1",
        "concepts": [{"concept_src_id": "H:x", "role": "PRIMARY"}],
        "review_status": "approved",
        "difficulty_overall": 2.5,
        "answer": "7",
        "answer_explanation": "지수를 앞으로 내린다.",
        "tags": ["p3-slot:basic", "unrelated"],
        "problem_type_codes": ["ptype.a"],
    }

    def _ref(self, **changes: Any) -> pc.ProblemRef:
        row = {**self._ROW, **changes}
        for key in [k for k, v in changes.items() if v is _GONE]:
            del row[key]
        ref = pc._problem_from_row(row)
        assert ref is not None
        return ref

    def test_complete_row_fills_every_field_axis(self) -> None:
        ref = self._ref()
        assert ref.difficulty == 2.5
        assert (ref.answer, ref.solution_text) == ("7", "지수를 앞으로 내린다.")
        assert ref.tags == ("p3-slot:basic", "unrelated")

    @pytest.mark.parametrize("key", ["difficulty_overall", "answer", "answer_explanation"])
    def test_a_row_without_the_key_is_measured_empty_not_unmeasured(self, key: str) -> None:
        """행을 읽었는데 값이 없다 → "측정했고 비어 있음". None(측정 못함)이면 사유가 틀려진다."""
        ref = self._ref(**{key: _GONE})
        if key == "difficulty_overall":
            assert ref.difficulty is not None and math.isnan(ref.difficulty)
        elif key == "answer":
            assert ref.answer == ""
        else:
            assert ref.solution_text == ""

    @pytest.mark.parametrize("bad", [True, False, "2.5", None, [2.5]])
    def test_non_numeric_difficulty_is_measured_empty(self, bad: Any) -> None:
        ref = self._ref(difficulty_overall=bad)
        assert ref.difficulty is not None and math.isnan(ref.difficulty)

    def test_numeric_answer_is_kept_as_text_and_non_text_tags_are_dropped(self) -> None:
        ref = self._ref(answer=7, tags=["p3-slot:applied", 3, None])
        assert ref.answer == "7"
        assert ref.tags == ("p3-slot:applied",)
        assert self._ref(tags="not-a-list").tags == ()

    def test_non_text_explanation_is_empty(self) -> None:
        assert self._ref(answer_explanation=123).solution_text == ""

    # ── P3-05 — 근사 중복 기준이 읽는 문면 ───────────────────────────────────────
    def test_question_text_is_loaded_from_the_row(self) -> None:
        """이 경로가 끊기면 모든 문항이 '문면 미확인'이 되어 중복 제거가 조용히 꺼진다.

        합성 `ProblemRef` 로 만든 지표 테스트는 이 변환을 거치지 않으므로 여기서 따로 잰다.
        """
        ref = self._ref(question_text="함수 f(x) = x^2 의 값을 구하시오.")
        assert ref.question_text == "함수 f(x) = x^2 의 값을 구하시오."

    @pytest.mark.parametrize("bad", [None, 7, ["문면"], {"a": 1}])
    def test_a_missing_or_non_text_stem_is_unknown_not_empty(self, bad: Any) -> None:
        """문면은 다른 세 필드와 반대다: 모르면 None(합치지 않는다). ''로 바꾸면 의미가 흐려진다."""
        assert self._ref(question_text=bad).question_text is None
        assert self._ref(question_text=_GONE).question_text is None


_GONE = object()  # `_ref` 가 키를 행에서 지우라는 표지


# ──────────────────────────────────────────────────────────────────────────
# 게이트 단위 종료 코드 (P3-54) — 합산 종료 코드는 게이트 조건을 가르지 못한다
# ──────────────────────────────────────────────────────────────────────────
#: 지표마다 "그 지표만" 떨어뜨리는 주입(목표가 있는 4종 안에서). Content 의 주입은 목표가 없는
#: 공급 가능 커버리지도 함께 떨어뜨리지만 그 지표는 종료 코드에 불참하므로 게이트 4종 안에서는 단독이다.
_SOLO_INJECTION: dict[str, Callable[..., Any]] = {
    "content_coverage_rate": _drop_content_row,
    "curriculum_coverage": _add_node_without_concept,
    "concept_completeness": _drop_prerequisite,
    "graph_connectivity_coverage": _drop_crosslinks,
}


def _with_gate(spec: ps.ScopeSpec, key: str) -> ps.ScopeSpec:
    """`key` 한 지표만 조건으로 선언한 게이트 `T-<key>` 를 얹은 명세."""
    gates = {f"T-{key}": ps.GateCondition(metrics=(key,), basis="테스트 합성 게이트")}
    return replace(spec, gate_conditions=gates)


def _gate_exit(spec: ps.ScopeSpec, index: ps.ReferenceIndex, w: pc.CoverageCorpus, key: str) -> int:
    gated = _with_gate(spec, key)
    return pc.judge_gate(gated, pc.evaluate(gated, index, w), f"T-{key}").exit_code


def test_solo_injection_table_really_isolates_each_gated_metric(spec, index, world) -> None:
    """전제 검증 — 아래 행렬은 이 표가 '정말 그 지표만' 떨어뜨린다는 가정 위에 선다."""
    before = {k: pc.evaluate(spec, index, world).metric(k).value for k in pc.GATE_METRIC_KEYS}
    for key, inject in _SOLO_INJECTION.items():
        spec2, world2 = inject(spec, index, world)
        after = {k: pc.evaluate(spec2, index, world2).metric(k).value for k in pc.GATE_METRIC_KEYS}
        fell = {k for k in pc.GATE_METRIC_KEYS if after[k] != before[k]}
        assert fell == {key}, f"[{key}] 주입이 다른 지표도 건드렸다: {fell}"


@pytest.mark.parametrize("selected", pc.GATE_METRIC_KEYS)
@pytest.mark.parametrize("injected", pc.GATE_METRIC_KEYS)
def test_gate_exit_is_one_only_for_its_own_metric(spec, index, world, selected, injected) -> None:
    """acceptance ③ — 선택된 지표를 떨어뜨리는 주입에만 1, 다른 지표만 떨어뜨리는 주입에는 0."""
    spec2, world2 = _SOLO_INJECTION[injected](spec, index, world)
    assert _gate_exit(spec2, index, world2, selected) == (1 if selected == injected else 0)


@pytest.mark.parametrize("selected", pc.GATE_METRIC_KEYS)
def test_control_clean_world_passes_every_gate(spec, index, world, selected) -> None:
    """대조군 — 위반 없는 세계는 어떤 게이트도 0 이다(과잉 반응하는 판정기를 막는다)."""
    assert _gate_exit(spec, index, world, selected) == 0


def test_default_exit_code_cannot_tell_the_gate_condition_but_the_gate_can(
    spec, index, world
) -> None:
    """P3-54 가 겨냥한 결함의 재현 — 다른 지표가 이미 미달인 기준선에서 합산 종료 코드는 변별력이 0 이다.

    2026-10-17 실측과 같은 구조: 기준선(Completeness 미달)과 기준선+Content 하락이 둘 다 합산 1 이다.
    """
    spec_a, base = _drop_prerequisite(spec, index, world)  # Completeness 만 이미 미달인 세계
    spec_b, worse = _drop_content_row(spec_a, index, base)  # 거기에 Content 까지 떨어뜨린다
    assert worse != base
    report_a = pc.evaluate(spec_a, index, base)
    report_b = pc.evaluate(spec_b, index, worse)
    assert report_a.metric("content_coverage_rate").met is True
    assert report_b.metric("content_coverage_rate").met is False
    assert report_a.exit_code == report_b.exit_code == 1  # 합산: 둘을 가르지 못한다
    assert _gate_exit(spec_a, index, base, "content_coverage_rate") == 0
    assert _gate_exit(spec_b, index, worse, "content_coverage_rate") == 1


def test_injections_leave_the_shared_world_untouched(spec, index, world) -> None:
    """원복 동일성 — 주입은 새 객체를 만들 뿐 공유 세계를 바꾸지 않는다(다음 테스트가 오염되지 않는다)."""
    fresh = _world(spec, index)
    for inject in _SOLO_INJECTION.values():
        inject(spec, index, world)
    assert world == fresh


def test_measurement_failure_inside_the_gate_is_a_failure_not_a_pass(spec, index, world) -> None:
    """분모 0(측정 불가)은 게이트 안에서도 통과가 아니다."""
    empty = replace(spec, concepts=tuple(replace(c, core=False) for c in spec.concepts))
    gated = _with_gate(empty, "content_coverage_rate")
    verdict = pc.judge_gate(gated, pc.evaluate(gated, index, world), "T-content_coverage_rate")
    assert verdict.exit_code == 1
    assert any("분모가 0" in f for f in verdict.failures)


def test_failure_text_is_shared_with_the_default_verdict(spec, index, world) -> None:
    """게이트 판정의 실패 문구는 합산 판정과 같은 한 곳에서 나온다(문구가 따로 놀지 않는다)."""
    spec2, broken = _drop_content_row(spec, index, world)
    gated = _with_gate(spec2, "content_coverage_rate")
    report = pc.evaluate(gated, index, broken)
    verdict = pc.judge_gate(gated, report, "T-content_coverage_rate")
    assert verdict.failures == tuple(f for f in report.failures if "Content Coverage" in f)
    assert verdict.metric_keys == ("content_coverage_rate",)


class TestGateRefusals:
    """판정할 수 없는 요청은 0 이 아니라 거부다 — 선언이 없다는 사실을 통과로 접지 않는다."""

    def test_undeclared_gate_is_refused(self, spec, index, world) -> None:
        report = pc.evaluate(spec, index, world)
        with pytest.raises(pc.CoverageError, match="조건 지표 선언이 없다"):
            pc.judge_gate(spec, report, "P3-G9")

    def test_spec_without_any_gate_refuses_every_gate(self, spec, index, world) -> None:
        bare = replace(spec, gate_conditions={})
        with pytest.raises(pc.CoverageError, match="선언된 게이트: 없음"):
            pc.judge_gate(bare, pc.evaluate(bare, index, world), "P3-G1")

    @pytest.mark.parametrize("bad", ["supply_coverage", "slot_coverage", "no_such_metric"])
    def test_non_gate_metric_key_is_refused_at_evaluate_time(self, spec, index, world, bad) -> None:
        """명세가 이 계측기에 없는(또는 목표 없는) 지표를 가리키면 측정 자체를 거부한다."""
        lying = replace(
            spec,
            gate_conditions={"T-bad": ps.GateCondition(metrics=(bad,), basis="테스트")},
        )
        with pytest.raises(pc.CoverageError, match="목표가 있는 지표가 아닌 키"):
            pc.evaluate(lying, index, world)

    def test_gate_metric_without_a_spec_target_is_refused_not_vacuously_passed(
        self, spec, index, world
    ) -> None:
        """목표가 null 인 지표로는 종료 코드가 항상 0 이다 — 그것을 판정으로 내지 않는다."""
        targets = {
            **spec.targets,
            "graph_connectivity_coverage": ps.Target(value=None, reason="테스트 — 목표 미정"),
        }
        gated = replace(_with_gate(spec, "graph_connectivity_coverage"), targets=targets)
        _, cut = _drop_crosslinks(gated, index, world)  # 위반이 실제로 있어도
        report = pc.evaluate(gated, index, cut)
        assert report.metric("graph_connectivity_coverage").value == 0.0
        with pytest.raises(pc.CoverageError, match="목표가 없다"):
            pc.judge_gate(gated, report, "T-graph_connectivity_coverage")

    def test_real_spec_declares_only_judgeable_gates(self, spec, index, world) -> None:
        """실 명세의 모든 게이트 선언이 판정 가능하다(거부 경로가 실 명세에서 닿지 않는다)."""
        assert "P3-G1" in spec.gate_conditions
        report = pc.evaluate(spec, index, world)
        for gate_id in spec.gate_conditions:
            assert pc.judge_gate(spec, report, gate_id).exit_code in (0, 1)
        assert set(pc.GATE_METRIC_KEYS) >= {
            k for c in spec.gate_conditions.values() for k in c.metrics
        }


class TestGateCli:
    @staticmethod
    def _failing_completeness_world(spec, index, world):
        """실 코퍼스의 지금 모습 — Completeness 가 미달이라 합산 종료 코드는 이미 1 이다."""
        _, base = _drop_prerequisite(spec, index, world)
        return base

    def test_gate_exit_follows_the_declared_metric_not_the_sum(
        self, spec, index, world, monkeypatch, capsys
    ) -> None:
        base = self._failing_completeness_world(spec, index, world)
        monkeypatch.setattr(pc, "load_corpus", lambda s: base)
        assert pc.main([]) == 1  # 합산: 미달
        capsys.readouterr()
        assert pc.main(["--gate", "P3-G1"]) == 0  # 게이트 조건(Content)은 충족
        out = capsys.readouterr().out
        assert "게이트 P3-G1 판정: 통과" in out
        assert "판정: 미달" in out  # 합산 판정 줄은 그대로 남아 두 판정이 함께 보인다

    def test_gate_exit_is_one_when_the_declared_metric_misses(
        self, spec, index, world, monkeypatch, capsys
    ) -> None:
        base = self._failing_completeness_world(spec, index, world)
        _, worse = _drop_content_row(spec, index, base)
        monkeypatch.setattr(pc, "load_corpus", lambda s: worse)
        assert pc.main(["--gate", "P3-G1"]) == 1
        out = capsys.readouterr().out
        assert "게이트 P3-G1 판정: 미달" in out
        assert "Content Coverage Rate" in out

    def test_json_keeps_the_full_exit_code_and_adds_the_gate_block(
        self, spec, index, world, monkeypatch, capsys
    ) -> None:
        base = self._failing_completeness_world(spec, index, world)
        monkeypatch.setattr(pc, "load_corpus", lambda s: base)
        assert pc.main(["--json", "--gate", "P3-G1"]) == 0
        doc = json.loads(capsys.readouterr().out)
        assert doc["exit_code"] == 1  # 전 지표 합산 — 의미를 바꾸지 않는다
        assert doc["gate"]["exit_code"] == 0
        assert doc["gate"]["gate_id"] == "P3-G1"
        assert doc["gate"]["metrics"] == ["content_coverage_rate"]
        assert doc["gate"]["failures"] == []

    def test_default_run_has_no_gate_block(self, world, monkeypatch, capsys) -> None:
        """--gate 를 주지 않으면 출력 형태가 이전과 같다(게이트 키·게이트 줄이 없다)."""
        monkeypatch.setattr(pc, "load_corpus", lambda s: world)
        assert pc.main(["--json"]) == 0
        assert "gate" not in json.loads(capsys.readouterr().out)
        assert pc.main([]) == 0
        assert "게이트 P3-G1 판정" not in capsys.readouterr().out

    def test_undeclared_gate_is_exit_2_before_the_corpus_is_loaded(
        self, monkeypatch, capsys
    ) -> None:
        def boom(spec: ps.ScopeSpec) -> pc.CoverageCorpus:
            raise AssertionError("판정할 수 없는 게이트인데 코퍼스를 적재했다")

        monkeypatch.setattr(pc, "load_corpus", boom)
        assert pc.main(["--gate", "P3-G9"]) == 2
        err = capsys.readouterr().err
        assert "적재 실패" in err and "CoverageError" in err and "P3-G9" in err

    def test_gate_on_a_metric_without_target_is_exit_2(
        self, world, monkeypatch, tmp_path, capsys
    ) -> None:
        doc = yaml.safe_load(ps.default_spec_path().read_text("utf-8"))
        doc["completeness"]["targets"]["content_coverage_rate"] = {
            "value": None,
            "reason": "테스트 — 목표 미정",
        }
        custom = tmp_path / "no_target.yaml"
        custom.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
        monkeypatch.setattr(pc, "load_corpus", lambda s: world)
        assert pc.main(["--spec", str(custom), "--gate", "P3-G1"]) == 2
        assert "목표가 없다" in capsys.readouterr().err

    def test_real_spec_file_is_byte_identical_after_a_gate_run(self, world, monkeypatch) -> None:
        """읽기 전용 — 게이트 판정이 명세 파일을 건드리지 않는다."""
        path = ps.default_spec_path()
        before = path.read_bytes()
        monkeypatch.setattr(pc, "load_corpus", lambda s: world)
        pc.main(["--gate", "P3-G1"])
        assert path.read_bytes() == before


# ──────────────────────────────────────────────────────────────────────────
# P3-64 — 스킬 연결 견고성 공개(건수·줄기·정답·(은행, 유형) 조합) · 판정 불참여
# ──────────────────────────────────────────────────────────────────────────
#: P3-64 이전 `to_json` 의 최상위 키 — 기존 키는 그대로이고 `link_robustness` 하나만 더해진다.
_PRE_P3_64_JSON_KEYS = frozenset(
    {
        "spec_id",
        "frozen_at",
        "frozen_by_gate",
        "exit_code",
        "metrics",
        "supply_coverage",
        "link_counts",
        "chain_funnel",
        "completeness_measurable",
        "problems_scanned",
        "warnings",
        "failures",
        "slot_coverage",
        "problem_metadata",
        "hint_seat",
    }
)

#: 서로 다른 문면 3종 — 숫자가 아니라 낱말이 달라 `phase3_stem_fold` 가 합치지 않는다.
_DIVERSE_STEMS = (
    "함수 f(x) = x^{n} 의 도함수를 구하시오.",
    "곡선 위 점에서 접선의 기울기를 구하시오.",
    "주어진 조건을 만족하는 상수의 값을 구하시오.",
)


def _robust_world(world: pc.CoverageCorpus) -> pc.CoverageCorpus:
    """핵심 개념마다 연결 문항 3건 — 줄기 3 · 정답 3 · (은행, 유형) 조합 2. 취약 표시가 꺼지는 대조군."""
    problems: list[pc.ProblemRef] = []
    for base in world.problems:
        for k, stem in enumerate(_DIVERSE_STEMS):
            problems.append(
                replace(
                    base,
                    problem_id=f"{base.problem_id}-r{k}",
                    question_text=stem,
                    answer=str(k + 1),
                    bank="bank_a" if k < 2 else "bank_b",
                )
            )
    return _inject(world, problems=tuple(problems), problems_scanned=len(problems))


def _rows(report: pc.CoverageReport) -> dict[str, pc.LinkRobustness]:
    assert report.link_robustness is not None
    return {r.concept_code: r for r in report.link_robustness}


def _rewrite_concept(
    corpus: pc.CoverageCorpus, src_id: str, **changes: Callable[[pc.ProblemRef, int], Any]
) -> pc.CoverageCorpus:
    """개념 하나(원 개념 ID)의 문항만 필드별 함수로 다시 쓴다 — 다른 개념은 그대로 둔다."""
    out: list[pc.ProblemRef] = []
    k = 0
    for p in corpus.problems:
        if src_id in p.primary_src_ids:
            p = replace(p, **{name: fn(p, k) for name, fn in changes.items()})
            k += 1
        out.append(p)
    return _inject(corpus, problems=tuple(out))


@pytest.fixture(scope="module")
def robust(world: pc.CoverageCorpus) -> pc.CoverageCorpus:
    return _robust_world(world)


class TestLinkRobustness:
    def test_control_diverse_world_has_no_thin_concept(self, spec, index, robust) -> None:
        rows = _rows(pc.evaluate(spec, index, robust))
        assert set(rows) == {c.code for c in spec.core_concepts}
        for row in rows.values():
            assert row.status == "ok", row
            assert (row.linked, row.distinct_stems, row.distinct_answers) == (3, 3, 3)
            assert len(row.bank_type_pairs) == 2
            assert row.reasons == ()

    def test_single_template_single_answer_turns_thin(self, spec, index, robust) -> None:
        """결함 주입 — P3-55 ②-4 의 02-02 형태: 숫자만 다른 한 틀 + 정답 하나."""
        target = spec.core_concepts[0]
        thin = _rewrite_concept(
            robust,
            target.source_id,
            question_text=lambda p, k: f"함수 f(x) = |x - {k}| 이 미분가능하면 1, 아니면 0을 쓰시오.",
            answer=lambda p, k: "0",
        )
        rows = _rows(pc.evaluate(spec, index, thin))
        row = rows[target.code]
        assert row.status == "thin"
        assert (row.linked, row.distinct_stems, row.distinct_answers) == (3, 1, 1)
        assert len(row.reasons) == 2
        others = [r for code, r in rows.items() if code != target.code]
        assert others and all(r.status == "ok" for r in others)

    def test_single_answer_alone_turns_thin(self, spec, index, robust) -> None:
        """정답 절만 밟는 반례 — 줄기는 다양해도 정답이 하나면 취약이다."""
        target = spec.core_concepts[0]
        row = _rows(
            pc.evaluate(
                spec, index, _rewrite_concept(robust, target.source_id, answer=lambda p, k: "0")
            )
        )[target.code]
        assert row.status == "thin" and row.distinct_stems == 3 and row.distinct_answers == 1
        assert len(row.reasons) == 1 and "정답" in row.reasons[0]

    def test_single_stem_alone_turns_thin(self, spec, index, robust) -> None:
        """줄기 절만 밟는 반례 — 정답이 달라도 숫자만 다른 한 틀이면 취약이다."""
        target = spec.core_concepts[0]
        row = _rows(
            pc.evaluate(
                spec,
                index,
                _rewrite_concept(
                    robust,
                    target.source_id,
                    question_text=lambda p, k: f"x = {k} 일 때 값을 구하시오.",
                ),
            )
        )[target.code]
        assert row.status == "thin" and row.distinct_stems == 1 and row.distinct_answers == 3
        assert len(row.reasons) == 1 and "줄기" in row.reasons[0]

    def test_threshold_boundary_is_not_thin(self, spec, index, robust) -> None:
        """기준값과 같은 수(서로 다른 값 2개)는 취약이 아니다 — `<` 를 `<=` 로 바꾸면 이 테스트가 깨진다."""
        target = spec.core_concepts[0]
        corpus = _rewrite_concept(
            robust,
            target.source_id,
            question_text=lambda p, k: _DIVERSE_STEMS[k % pc.LINK_THIN_MIN_DISTINCT_STEMS],
            answer=lambda p, k: str(k % pc.LINK_THIN_MIN_DISTINCT_ANSWERS),
        )
        row = _rows(pc.evaluate(spec, index, corpus))[target.code]
        assert row.distinct_stems == pc.LINK_THIN_MIN_DISTINCT_STEMS
        assert row.distinct_answers == pc.LINK_THIN_MIN_DISTINCT_ANSWERS
        assert row.status == "ok"

    def test_unlinked_concept_is_not_reported_as_thin(self, spec, index, robust) -> None:
        """연결 0건은 '얇다'가 아니라 '없다'다 — Content 미충족이 이미 말한다."""
        target = spec.core_concepts[0]
        corpus = _rewrite_concept(robust, target.source_id, problem_type_codes=lambda p, k: ())
        row = _rows(pc.evaluate(spec, index, corpus))[target.code]
        assert (row.status, row.linked, row.reasons, row.bank_type_pairs) == ("unlinked", 0, (), ())

    def test_unread_answers_and_stems_are_not_merged(self, spec, index, robust) -> None:
        """모르는 값은 합치지 않는다 — 정답·문면을 못 읽은 문항이 '전부 같다'로 접히면 거짓 취약이다."""
        target = spec.core_concepts[0]
        corpus = _rewrite_concept(
            robust, target.source_id, answer=lambda p, k: None, question_text=lambda p, k: None
        )
        row = _rows(pc.evaluate(spec, index, corpus))[target.code]
        assert (row.distinct_answers, row.unread_answers) == (3, 3)
        assert (row.distinct_stems, row.unfolded_stems) == (3, 3)
        assert row.status == "ok"

    def test_pairs_count_only_types_that_make_the_link(self, spec, index, robust) -> None:
        """연결을 만들지 않은 문제유형은 조합에 넣지 않는다 — 넣으면 다양성이 부풀려진다."""
        target = spec.core_concepts[0]
        stray = "ptype.syn-stray"
        corpus = _inject(robust, type_skills={**robust.type_skills, stray: ("no-such-skill",)})
        corpus = _rewrite_concept(
            corpus, target.source_id, problem_type_codes=lambda p, k: (*p.problem_type_codes, stray)
        )
        row = _rows(pc.evaluate(spec, index, corpus))[target.code]
        assert all(code != stray for _, code in row.bank_type_pairs)
        assert len(row.bank_type_pairs) == 2

    def test_unknown_bank_is_marked_not_dropped(self, spec, index, world) -> None:
        rows = _rows(pc.evaluate(spec, index, world))
        assert all(bank == pc.UNKNOWN_BANK for r in rows.values() for bank, _ in r.bank_type_pairs)
        assert all(r.bank_type_pairs for r in rows.values())


class TestLinkRobustnessDoesNotJudge:
    """acceptance ② — 공개만 한다. 견고성이 바뀌어도 판정(지표·실패·경고·종료 코드)은 같다."""

    def _thin_everywhere(self, robust: pc.CoverageCorpus) -> pc.CoverageCorpus:
        return _inject(
            robust,
            problems=tuple(
                replace(p, question_text="같은 틀 1 의 문제", answer="0", bank=None)
                for p in robust.problems
            ),
        )

    def test_verdict_is_identical_when_only_robustness_changes(self, spec, index, robust) -> None:
        before = pc.evaluate(spec, index, robust)
        after = pc.evaluate(spec, index, self._thin_everywhere(robust))
        assert {r.status for r in _rows(before).values()} == {"ok"}
        assert {r.status for r in _rows(after).values()} == {"thin"}  # 주입이 실제로 닿았다
        assert after.metrics == before.metrics
        assert after.supply == before.supply
        assert (after.failures, after.warnings, after.exit_code) == (
            before.failures,
            before.warnings,
            before.exit_code,
        )
        old, new = pc.to_json(before), pc.to_json(after)
        assert old.pop("link_robustness") != new.pop("link_robustness")
        assert old == new

    def test_json_keeps_every_existing_key_and_adds_one(self, spec, index, robust) -> None:
        doc = pc.to_json(pc.evaluate(spec, index, robust))
        assert set(doc) == _PRE_P3_64_JSON_KEYS | {"link_robustness"}
        block = doc["link_robustness"]
        assert block["thresholds"] == {
            "min_distinct_stems": pc.LINK_THIN_MIN_DISTINCT_STEMS,
            "min_distinct_answers": pc.LINK_THIN_MIN_DISTINCT_ANSWERS,
            "provisional": True,
        }
        first = block["concepts"][0]
        assert set(first) == {
            "concept_code",
            "linked",
            "distinct_stems",
            "unfolded_stems",
            "distinct_answers",
            "unread_answers",
            "bank_type_pairs",
            "pair_count",
            "status",
            "reasons",
        }
        assert first["pair_count"] == len(first["bank_type_pairs"])

    def test_report_without_robustness_serializes_as_none(self, spec, index, robust) -> None:
        report = replace(pc.evaluate(spec, index, robust), link_robustness=None)
        assert pc.to_json(report)["link_robustness"] is None
        assert "스킬 연결 견고성" not in pc.render(report)

    def test_text_output_shows_the_table_and_thin_mark(self, spec, index, robust) -> None:
        text = pc.render(pc.evaluate(spec, index, self._thin_everywhere(robust)))
        assert "스킬 연결 견고성" in text and "판정 불참여" in text
        for concept in spec.core_concepts:
            assert concept.code in text
        assert "취약" in text and "서로 다른 정답 1개" in text


class TestLinkRobustnessRealCorpus:
    """실 코퍼스 — 수치는 박지 않는다. 로더와 **다른 경로**(평문 json·디렉터리 이름)로 다시 센 값과
    대조해, 은행·정답·문면 축이 조용히 비어 읽히는 상태를 잡는다(acceptance ① 재현의 기계 검증)."""

    def test_every_kept_problem_knows_its_bank(self, spec) -> None:
        corpus = pc.load_corpus(spec)
        assert corpus.problems and all(p.bank for p in corpus.problems)

    def test_independent_recount_matches_the_report(self, spec, index, real_report) -> None:
        from whymath_backend.l1.standards.phase3_stem_fold import fold_stem

        raw: dict[str, tuple[str, dict[str, Any]]] = {}
        for path in sorted(_REPO.glob(pc._PROBLEM_GLOB)):
            bank = path.parent.name.split("problem_bank_", 1)[1]
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line) if line.strip() else None
                # ID 없는 행은 로더도 버린다(`_problem_from_row` → None). 중복 ID 는 은행을 가리므로 거부.
                if isinstance(row, dict) and isinstance(row.get("problem_id"), str):
                    assert row["problem_id"] not in raw, row["problem_id"]
                    raw[row["problem_id"]] = (bank, row)
        corpus = pc.load_corpus(spec)
        rows = _rows(real_report)
        assert set(rows) == {c.code for c in spec.core_concepts}
        for concept in spec.core_concepts:
            facts = pc._facts(spec, index, corpus, concept)
            skills = set(facts.skills)
            linked = [raw[p.problem_id] for p in facts.skill_linked]
            stems = {fold_stem(r.get("question_text")) for _, r in linked}
            answers = {
                ("" if r.get("answer") is None else str(r["answer"])).strip() for _, r in linked
            }
            pairs = {
                (bank, code)
                for bank, r in linked
                for code in r.get("problem_type_codes") or []
                if skills & set(corpus.type_skills.get(code, ()))
            }
            got = rows[concept.code]
            assert got.linked == len(linked), concept.code
            assert None not in stems or got.unfolded_stems > 0, concept.code
            assert got.distinct_stems == len(stems - {None}) + got.unfolded_stems, concept.code
            assert got.distinct_answers == len(answers), concept.code
            assert set(got.bank_type_pairs) == pairs, concept.code
            assert got.status == ("unlinked" if not linked else got.status)
        assert any(r.linked for r in rows.values())
