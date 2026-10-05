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

import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from whymath_backend.l1.standards import phase3_coverage as pc
from whymath_backend.l1.standards import phase3_scope as ps

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
        """Graph Connectivity 는 명세에 목표가 없다 — 떨어져도 exit 은 다른 지표가 정한다."""
        _, cut = _drop_crosslinks(spec, index, world)
        report = pc.evaluate(spec, index, cut)
        connectivity = report.metric("graph_connectivity_coverage")
        assert connectivity.value == 0.0
        assert connectivity.met is None and not connectivity.gated
        assert report.exit_code == 0

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
        """필드가 없는 행은 '승인'이 아니다 — 14,034행 중 11,396행이 이 상태다."""
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

    def test_hint_is_reported_unmeasured_while_the_seat_is_absent(self, spec, real_report) -> None:
        """힌트 저장 좌석이 생기면(P3-04) 이 테스트를 갱신한다 — 좌석이 생겼는데 이 단언이 남아
        있으면 배선 누락을 드러낸다."""
        n = len(spec.core_concepts)
        assert real_report.link_counts["hint"] == {"linked": 0, "missing": 0, "unmeasured": n}


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
