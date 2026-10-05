"""Phase 3 대표 과정 범위 명세 — 로더·무결성 게이트 테스트 (P3-01 acceptance ⑤).

이 테스트가 지키는 것
---------------------
`data/corpus/phase3_scope_v1/scope_spec.yaml` 은 Phase 3 모든 Coverage 의 **분모**다. 명세가
스키마를 어기거나(빈 목록·중복·산술 불일치) 존재하지 않는 ID 를 참조하면 로더가 실패해야 한다.

검증 방식 — 정상 입력의 초록은 증거가 아니다
--------------------------------------------
각 위반 형태를 **실제로 주입**해 RED 를 확인한다. 주입은 `_mutate` 가 "주입이 실제로 적용됐는가"를
단언한다(변경 전후가 같으면 정상 파일에 대해 테스트가 돌고 'N passed' 가 검출처럼 보인다).
모든 주입 테스트는 짝이 되는 **무주입 대조군**(`test_control_*`)이 0건임을 함께 보인다 — 대조군이
없으면 "무엇을 넣어도 위반이 나는 과잉 검증기"가 통과한다.

동결 불변식(계획 문서가 못박은 어휘·수치)은 로더가 아니라 이 테스트가 소유한다 — 로더는 구조만
알고, "슬롯이 6개·필수 필드가 7개"는 Phase 3 계획의 사실이기 때문이다.
"""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from whymath_backend.l1.standards import phase3_scope as ps

_SPEC_PATH = ps.default_spec_path()
_REAL_DOC: dict[str, Any] = yaml.safe_load(_SPEC_PATH.read_text(encoding="utf-8"))

# ── 계획 문서(지시문 [03]·[04]·[07]·[08])가 못박은 동결 불변식 ──────────────────────────
_EXPECTED_SLOTS = (
    "representative",
    "basic",
    "applied",
    "misconception_trigger",
    "diagnostic",
    "mastery_check",
)
_EXPECTED_PROBLEM_FIELDS = (
    "difficulty",
    "skill",
    "concept",
    "solution",
    "answer",
    "misconception_signature",
    "hint_strategy",
)
_EXPECTED_LINKS = ("prerequisite", "misconception", "solution", "hint", "pedagogy")
_EXPECTED_TARGETS = {
    "content_coverage_rate": 0.95,
    "curriculum_coverage": 0.98,
    "concept_completeness": 0.95,
    "problem_coverage_by_skill": 0.95,
    "graph_connectivity_coverage": None,
}


@pytest.fixture(scope="module")
def scope() -> ps.ScopeSpec:
    return ps.load_scope_spec()


@pytest.fixture(scope="module")
def index(scope: ps.ScopeSpec) -> ps.ReferenceIndex:
    return ps.load_reference_index(scope)


def _mutate(mutator: Callable[[dict[str, Any]], None]) -> ps.ScopeSpec:
    """실제 명세 사본에 주입을 적용해 파싱한다. 주입이 실제로 바꿨는지 단언한다."""
    doc = copy.deepcopy(_REAL_DOC)
    before = _fingerprint(doc)
    mutator(doc)
    # 파이썬에서 True == 1 이라 `doc != before` 로는 1 → True 주입이 '변경 없음'으로 읽힌다.
    # 직렬화 지문으로 비교해 타입만 바뀐 주입도 적용됐음을 잡는다.
    assert _fingerprint(doc) != before, "주입이 적용되지 않았다 — 정상 파일로 테스트가 돌고 있다"
    return ps.parse_scope_spec(doc, _SPEC_PATH)


def _fingerprint(doc: dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, default=str)


def _violations(mutator: Callable[[dict[str, Any]], None], index: ps.ReferenceIndex) -> str:
    return "\n".join(ps.verify_spec(_mutate(mutator), index))


# ── 정상 경로 · 대조군 ─────────────────────────────────────────────────────


def test_real_spec_passes_against_real_corpora(
    scope: ps.ScopeSpec, index: ps.ReferenceIndex
) -> None:
    assert ps.verify_spec(scope, index) == ()


def test_control_unmutated_spec_has_zero_violations(index: ps.ReferenceIndex) -> None:
    """무주입 대조군 — 아래 주입 테스트들이 '무엇을 넣어도 위반' 인 과잉 검증기가 아님을 보인다."""
    doc = copy.deepcopy(_REAL_DOC)
    assert ps.verify_spec(ps.parse_scope_spec(doc, _SPEC_PATH), index) == ()


def test_frozen_denominators_match_the_plan(scope: ps.ScopeSpec) -> None:
    assert scope.course_id == "calculus1-differentiation"
    assert (scope.subject_code, scope.domain, scope.grade) == ("12미적Ⅰ", "미분", "고2")
    assert len(scope.nodes) == 10
    assert len(scope.concepts) == 10 and len(scope.core_concepts) == 10
    assert len(scope.skills) == 8
    assert len(scope.core_misconceptions) == 12
    assert len(scope.problem_types) == 5
    assert scope.excluded_domains == ("함수의 극한과 연속", "적분")


def test_slots_fields_links_and_targets_follow_the_plan(scope: ps.ScopeSpec) -> None:
    assert tuple(s.id for s in scope.slots) == _EXPECTED_SLOTS
    assert scope.problem_required_fields == _EXPECTED_PROBLEM_FIELDS
    assert scope.concept_required_links == _EXPECTED_LINKS
    assert {k: t.value for k, t in scope.targets.items()} == _EXPECTED_TARGETS
    assert scope.min_distinct_per_slot == 1
    assert scope.total_min_distinct_problems == 60


def test_disposition_of_p3_18_is_recorded_as_data(scope: ps.ScopeSpec) -> None:
    """처분(Kiki 2026-10-02)이 산문이 아니라 데이터에 남아 있다 — 02-08 은 분모에서 빠지지 않는다."""
    by_code = {c.code: c for c in scope.concepts}
    assert by_code["[12미적Ⅰ-02-08]"].probe_verdict == "replaced_by_derived"
    assert by_code["[12미적Ⅰ-02-08]"].core is True
    assert by_code["[12미적Ⅰ-02-06]"].probe_verdict == "partial"
    assert by_code["[12미적Ⅰ-02-09]"].probe_verdict == "partial"
    assert by_code["[12미적Ⅰ-02-05]"].probe_verdict == "possible"
    assert by_code["[12미적Ⅰ-02-05]"].probe_note


# ── 구조 위반 RED — 빈 목록 (acceptance ⑤ ①) ───────────────────────────────

_EMPTY_LIST_INJECTIONS: dict[str, Callable[[dict[str, Any]], None]] = {
    "curriculum_nodes": lambda d: d.__setitem__("curriculum_nodes", []),
    "concepts": lambda d: d.__setitem__("concepts", []),
    "skills": lambda d: d.__setitem__("skills", []),
    "core_misconceptions.items": lambda d: d["core_misconceptions"].__setitem__("items", []),
    "required_problem_types.items": lambda d: d["required_problem_types"].__setitem__("items", []),
    "quantity_targets.slots": lambda d: d["quantity_targets"].__setitem__("slots", []),
    "completeness.concept_required_links": lambda d: d["completeness"].__setitem__(
        "concept_required_links", []
    ),
    "completeness.graph_path": lambda d: d["completeness"].__setitem__("graph_path", []),
    "completeness.curriculum_path": lambda d: d["completeness"].__setitem__("curriculum_path", []),
    "completeness.problem_required_fields": lambda d: d["completeness"].__setitem__(
        "problem_required_fields", []
    ),
}


@pytest.mark.parametrize("name", sorted(_EMPTY_LIST_INJECTIONS))
def test_empty_list_fails_the_loader(name: str) -> None:
    with pytest.raises(ps.ScopeSpecError, match="비어 있거나 리스트가 아니다"):
        _mutate(_EMPTY_LIST_INJECTIONS[name])


@pytest.mark.parametrize(
    "key",
    [
        "spec_version",
        "spec_id",
        "frozen_at",
        "frozen_by_gate",
        "disposition_gate",
        "design_doc",
        "course",
        "scope",
        "sources",
        "curriculum_nodes",
        "concepts",
        "skills",
        "core_misconceptions",
        "required_problem_types",
        "quantity_targets",
        "completeness",
    ],
)
def test_missing_top_level_field_fails_the_loader(key: str) -> None:
    with pytest.raises(ps.ScopeSpecError, match="결손"):
        _mutate(lambda d: d.pop(key))


def test_unsupported_spec_version_fails() -> None:
    with pytest.raises(ps.ScopeSpecError, match="spec_version"):
        _mutate(lambda d: d.__setitem__("spec_version", 2))


def test_duplicate_node_concept_skill_and_misconception_fail() -> None:
    with pytest.raises(ps.ScopeSpecError, match="중복"):
        _mutate(lambda d: d["curriculum_nodes"].append(copy.deepcopy(d["curriculum_nodes"][0])))
    with pytest.raises(ps.ScopeSpecError, match="중복"):
        _mutate(lambda d: d["concepts"].append(copy.deepcopy(d["concepts"][0])))
    with pytest.raises(ps.ScopeSpecError, match="중복"):
        _mutate(lambda d: d["skills"].append(d["skills"][0]))
    with pytest.raises(ps.ScopeSpecError, match="중복"):
        _mutate(
            lambda d: d["core_misconceptions"]["items"].append(
                copy.deepcopy(d["core_misconceptions"]["items"][0])
            )
        )


def test_one_concept_per_standard_code_is_enforced() -> None:
    """437 입도 = 성취기준당 대표 개념 1개. 같은 코드에 둘이 걸리면 분모가 이중 계상된다."""

    def inject(doc: dict[str, Any]) -> None:
        extra = copy.deepcopy(doc["concepts"][0])
        extra["concept_id"] = "math.calculus.other"
        extra["source_id"] = "H:other"
        doc["concepts"].append(extra)

    with pytest.raises(ps.ScopeSpecError, match="code.*중복"):
        _mutate(inject)


def test_zero_core_concepts_means_empty_denominator_and_fails() -> None:
    def inject(doc: dict[str, Any]) -> None:
        for concept in doc["concepts"]:
            concept["core"] = False

    with pytest.raises(ps.ScopeSpecError, match="분모가 0"):
        _mutate(inject)


def test_core_flag_must_be_a_boolean_not_a_string() -> None:
    with pytest.raises(ps.ScopeSpecError, match="true/false"):
        _mutate(lambda d: d["concepts"][0].__setitem__("core", "yes"))


def test_unknown_probe_verdict_fails() -> None:
    with pytest.raises(ps.ScopeSpecError, match="probe_verdict"):
        _mutate(lambda d: d["concepts"][0].__setitem__("probe_verdict", "posible"))


@pytest.mark.parametrize("bad", [0, 1.5, -0.1, True, "0.95"])
def test_target_value_out_of_range_fails(bad: Any) -> None:
    with pytest.raises(ps.ScopeSpecError, match="0 초과 1 이하"):
        _mutate(
            lambda d: d["completeness"]["targets"]["content_coverage_rate"].__setitem__(
                "value", bad
            )
        )


def test_null_target_without_a_reason_fails() -> None:
    """수치가 없다는 사실은 허용하되 왜 없는지가 데이터로 남아야 한다."""
    with pytest.raises(ps.ScopeSpecError, match="reason"):
        _mutate(lambda d: d["completeness"]["targets"]["graph_connectivity_coverage"].pop("reason"))


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "1"])
def test_slot_minimum_must_be_a_positive_integer(bad: Any) -> None:
    with pytest.raises(ps.ScopeSpecError, match="1 이상의 정수"):
        _mutate(lambda d: d["quantity_targets"].__setitem__("min_distinct_problems_per_slot", bad))


def test_empty_denominator_policy_must_be_fail() -> None:
    with pytest.raises(ps.ScopeSpecError, match="empty_denominator"):
        _mutate(lambda d: d["completeness"].__setitem__("empty_denominator", "pass"))


def test_course_and_scope_must_point_at_the_same_subject_and_domain() -> None:
    with pytest.raises(ps.ScopeSpecError, match="course.domain"):
        _mutate(lambda d: d["course"].__setitem__("domain", "적분"))


def test_missing_corpus_source_key_fails() -> None:
    with pytest.raises(ps.ScopeSpecError, match="problem_types"):
        _mutate(lambda d: d["sources"].pop("problem_types"))


# ── 참조 실재 RED — 존재하지 않는 ID 주입 (acceptance ⑤ ②) ──────────────────

_FAKE_CONCEPT_ID = "math.calculus.does-not-exist-injected"


def test_injected_nonexistent_concept_id_is_caught(index: ps.ReferenceIndex) -> None:
    out = _violations(lambda d: d["concepts"][3].__setitem__("concept_id", _FAKE_CONCEPT_ID), index)
    assert f"Concept ID '{_FAKE_CONCEPT_ID}'가 개념 ID 코퍼스에 없다" in out
    assert f"Concept ID '{_FAKE_CONCEPT_ID}'가 크로스워크에 없다" in out


def test_injected_nonexistent_standard_code_is_caught(index: ps.ReferenceIndex) -> None:
    out = _violations(
        lambda d: d["curriculum_nodes"].append({"code": "[12미적Ⅰ-99-99]", "sub_domain": "가짜"}),
        index,
    )
    assert "curriculum_nodes[[12미적Ⅰ-99-99]]: 성취기준 코퍼스(2022 개정)에 없다" in out


def test_node_from_another_domain_is_out_of_scope(index: ps.ReferenceIndex) -> None:
    out = _violations(
        lambda d: d["curriculum_nodes"].append(
            {"code": "[12미적Ⅰ-01-01]", "sub_domain": "함수의 극한의 뜻"}
        ),
        index,
    )
    assert "범위(12미적Ⅰ·미분) 밖이다" in out


def test_node_subdomain_mismatch_is_caught(index: ps.ReferenceIndex) -> None:
    out = _violations(lambda d: d["curriculum_nodes"][0].__setitem__("sub_domain", "오타"), index)
    assert "소단원이 다르다" in out


def test_school_level_mismatch_is_caught(index: ps.ReferenceIndex) -> None:
    out = _violations(lambda d: d["scope"].__setitem__("school_level", "중학교"), index)
    assert "학교급이 다르다" in out


def test_dropping_a_node_is_a_scope_omission_and_orphans_its_concept(
    index: ps.ReferenceIndex,
) -> None:
    out = _violations(lambda d: d["curriculum_nodes"].pop(4), index)
    assert "대단원 성취기준 [12미적Ⅰ-02-05]가 명세에 없다(범위 누락)" in out
    assert "concepts[[12미적Ⅰ-02-05]]: 성취기준 코드가 curriculum_nodes 에 없다" in out


def test_dropping_a_concept_leaves_its_node_without_representative(
    index: ps.ReferenceIndex,
) -> None:
    out = _violations(lambda d: d["concepts"].pop(5), index)
    assert "curriculum_nodes[[12미적Ⅰ-02-06]]: 이 성취기준에 대표 Concept 가 없다" in out


def test_source_id_mismatch_is_caught(index: ps.ReferenceIndex) -> None:
    out = _violations(lambda d: d["concepts"][0].__setitem__("source_id", "H:오타"), index)
    assert "source_id 가 다르다" in out


def test_primary_atom_pointing_at_another_standard_is_caught(index: ps.ReferenceIndex) -> None:
    out = _violations(
        lambda d: d["concepts"][0].__setitem__("primary_atom_code", "12미적Ⅰ-02-02-1"), index
    )
    assert "primary 원자가 다르다" in out
    assert "primary 원자가 이 성취기준에 귀속돼 있지 않다" in out


def test_primary_atom_that_does_not_exist_is_caught(index: ps.ReferenceIndex) -> None:
    out = _violations(
        lambda d: d["concepts"][0].__setitem__("primary_atom_code", "12미적Ⅰ-99-99-9"), index
    )
    assert "원자 리프에 없다" in out


def test_grade_mismatch_is_caught_on_every_atom(index: ps.ReferenceIndex) -> None:
    out = _violations(lambda d: d["scope"].__setitem__("grade", "고3"), index)
    assert "의 학년이 다르다" in out


def test_unknown_skill_is_caught(index: ps.ReferenceIndex) -> None:
    out = _violations(lambda d: d["skills"].append("skill.does-not-exist"), index)
    assert "skills[skill.does-not-exist]: 스킬 코퍼스에 없다" in out


def test_existing_but_unused_skill_is_an_orphan(index: ps.ReferenceIndex) -> None:
    out = _violations(lambda d: d["skills"].append("skill.linear-equation-solving"), index)
    assert (
        "skills[skill.linear-equation-solving]: 어느 개념의 원자에도 쓰이지 않는다(고아 스킬)"
        in out
    )


def test_concept_without_any_listed_skill_is_caught(index: ps.ReferenceIndex) -> None:
    """02-09 의 원자 스킬은 case-analysis·word-problem-modeling 뿐이다 — 둘을 빼면 그 개념은 끊긴다."""

    def inject(doc: dict[str, Any]) -> None:
        doc["skills"] = [
            s
            for s in doc["skills"]
            if s not in ("skill.case-analysis", "skill.word-problem-modeling")
        ]

    out = _violations(inject, index)
    assert "concepts[[12미적Ⅰ-02-09]]: 원자 스킬과 겹치는 명세 스킬이 없다" in out


def test_unknown_misconception_is_caught(index: ps.ReferenceIndex) -> None:
    out = _violations(
        lambda d: d["core_misconceptions"]["items"].append(
            {"mis_id": "M9999", "concept_code": "[12미적Ⅰ-02-03]"}
        ),
        index,
    )
    assert "core_misconceptions[M9999]: M-id 가 오개념 코퍼스에 없다" in out


def test_misconception_attributed_to_another_standard_is_caught(index: ps.ReferenceIndex) -> None:
    out = _violations(
        lambda d: d["core_misconceptions"]["items"][0].__setitem__(
            "concept_code", "[12미적Ⅰ-02-02]"
        ),
        index,
    )
    assert "귀속 성취기준이 다르다" in out


def test_misconception_for_a_concept_not_in_the_spec_is_caught(index: ps.ReferenceIndex) -> None:
    out = _violations(
        lambda d: d["core_misconceptions"]["items"][0].__setitem__(
            "concept_code", "[12미적Ⅰ-01-01]"
        ),
        index,
    )
    assert "concepts 에 없다" in out


def test_core_concept_without_a_core_misconception_is_caught(index: ps.ReferenceIndex) -> None:
    def inject(doc: dict[str, Any]) -> None:
        items = doc["core_misconceptions"]["items"]
        doc["core_misconceptions"]["items"] = [i for i in items if i["mis_id"] != "M0671"]

    out = _violations(inject, index)
    assert "concepts[[12미적Ⅰ-02-03]]: 핵심 개념인데 핵심 오개념이 없다" in out


def test_unknown_problem_type_is_caught(index: ps.ReferenceIndex) -> None:
    out = _violations(
        lambda d: d["required_problem_types"]["items"].append("ptype.does-not-exist"), index
    )
    assert "required_problem_types[ptype.does-not-exist]: 문제유형 코퍼스에 없다" in out


def test_total_that_disagrees_with_the_arithmetic_is_caught(index: ps.ReferenceIndex) -> None:
    out = _violations(
        lambda d: d["quantity_targets"].__setitem__("total_min_distinct_problems", 59), index
    )
    assert "59 ≠ 핵심 개념 10 × 슬롯 6 × 슬롯당 1 = 60" in out


def test_non_core_concept_shrinks_the_denominator_arithmetic(index: ps.ReferenceIndex) -> None:
    """핵심 표시를 하나 내리면 합계 산술이 어긋난다 — 분모를 몰래 줄이는 경로를 막는다."""
    out = _violations(lambda d: d["concepts"][7].__setitem__("core", False), index)
    assert "핵심 개념 9 × 슬롯 6 × 슬롯당 1 = 54" in out


# ── 코퍼스 적재 실패 RED — 못 읽음·0건을 통과로 위장하지 않는다 ─────────────────


def _redirect(scope: ps.ScopeSpec, key: str, target: Path) -> ps.ScopeSpec:
    return replace(scope, sources={**scope.sources, key: str(target)})


@pytest.mark.parametrize(
    ("key", "content"),
    [
        ("standards", json.dumps({"standards": []})),
        ("concept_ids", yaml.safe_dump({"concepts": []})),
        ("crosswalk", ""),
        ("atoms", json.dumps({"concepts": []})),
        ("skills", ""),
        ("misconceptions", json.dumps({"misconceptions": []})),
        ("problem_types", ""),
    ],
)
def test_empty_corpus_is_a_load_failure_not_a_pass(
    scope: ps.ScopeSpec, tmp_path: Path, key: str, content: str
) -> None:
    target = tmp_path / f"{key}.dat"
    target.write_text(content, encoding="utf-8")
    with pytest.raises(ps.ScopeSpecError, match="0건이다"):
        ps.load_reference_index(_redirect(scope, key, target))


def test_missing_corpus_file_names_the_exception_type(scope: ps.ScopeSpec, tmp_path: Path) -> None:
    with pytest.raises(ps.ScopeSpecError, match="FileNotFoundError"):
        ps.load_reference_index(_redirect(scope, "standards", tmp_path / "nope.json"))


def test_malformed_corpus_json_names_the_exception_type(
    scope: ps.ScopeSpec, tmp_path: Path
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ps.ScopeSpecError, match="JSONDecodeError"):
        ps.load_reference_index(_redirect(scope, "standards", broken))


def test_revision_filter_does_not_let_a_retired_code_keep_the_denominator_alive(
    scope: ps.ScopeSpec, tmp_path: Path
) -> None:
    """폐지(2015 개정) 코드는 인정하지 않는다 — 같은 코드가 2022 행에서 사라지면 위반이 나야 한다."""
    real = json.loads(Path(ps._REPO_ROOT, scope.sources["standards"]).read_text(encoding="utf-8"))
    for row in real["standards"]:
        if row.get("subject") == scope.subject_code and row.get("domain") == scope.domain:
            row["curriculum_revision"] = "2015 개정"
    swapped = tmp_path / "standards.json"
    swapped.write_text(json.dumps(real, ensure_ascii=False), encoding="utf-8")
    index = ps.load_reference_index(_redirect(scope, "standards", swapped))
    out = "\n".join(ps.verify_spec(scope, index))
    assert "성취기준 코퍼스(2022 개정)에 없다" in out


def test_concept_missing_from_crosswalk_only_is_caught(
    scope: ps.ScopeSpec, index: ps.ReferenceIndex
) -> None:
    pruned = {k: v for k, v in index.crosswalk.items() if k != "math.calculus.mibungyesu"}
    out = "\n".join(ps.verify_spec(scope, replace(index, crosswalk=pruned)))
    assert "Concept ID 'math.calculus.mibungyesu'가 크로스워크에 없다" in out


def test_crosswalk_atom_missing_from_the_atom_corpus_is_caught(
    scope: ps.ScopeSpec, index: ps.ReferenceIndex
) -> None:
    pruned = {k: v for k, v in index.atoms.items() if k != "12미적Ⅰ-02-01-1"}
    out = "\n".join(ps.verify_spec(scope, replace(index, atoms=pruned)))
    assert "크로스워크 원자 '12미적Ⅰ-02-01-1'가 원자 리프에 없다" in out


def test_non_leaf_atom_is_not_accepted_as_a_primary(
    scope: ps.ScopeSpec, index: ps.ReferenceIndex
) -> None:
    """원자 색인은 세부개념 리프만 담는다 — 그래프에 **실재하는** 단원 노드를 primary 로 쓰면 걸린다.

    '없는 코드'가 아니라 '있지만 리프가 아닌 코드'를 주입해야 리프 필터 절을 밟는다.
    """
    graph = json.loads(Path(ps._REPO_ROOT, scope.sources["atoms"]).read_text(encoding="utf-8"))
    rows = {row["code"]: row for row in graph["concepts"]}
    # 대상 원자의 실제 부모(소단원) 노드 — 그래프에 실재하고 리프가 아니다.
    non_leaf = rows[scope.concepts[0].primary_atom_code]["parent_code"]
    assert non_leaf in rows and rows[non_leaf]["level"] != "세부개념"
    assert non_leaf not in index.atoms  # 그래프에는 있으나 색인(리프 전용)에는 없다
    out = _violations(lambda d: d["concepts"][0].__setitem__("primary_atom_code", non_leaf), index)
    assert f"primary 원자 '{non_leaf}'가 원자 리프에 없다" in out


# ── CLI — 판정은 exit 0/1 ───────────────────────────────────────────────────


def test_cli_exits_zero_on_the_real_spec(capsys: pytest.CaptureFixture[str]) -> None:
    assert ps.main([]) == 0
    assert "판정: 통과" in capsys.readouterr().out


def test_cli_json_summary_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    assert ps.main(["--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["core_concepts"] == 10 and summary["violations"] == []
    assert summary["total_min_distinct_problems"] == 60


def test_cli_exits_one_when_a_nonexistent_concept_id_is_injected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """acceptance ⑤ — 존재하지 않는 ID 를 주입한 명세 파일로 CLI 를 돌려 exit 1 을 확인한다."""
    doc = copy.deepcopy(_REAL_DOC)
    doc["concepts"][2]["concept_id"] = _FAKE_CONCEPT_ID
    injected = tmp_path / "scope_spec.yaml"
    injected.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    assert ps.main(["--spec", str(injected)]) == 1
    out = capsys.readouterr().out
    assert _FAKE_CONCEPT_ID in out and "위반" in out


def test_cli_exits_one_on_structural_failure_and_says_why(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = copy.deepcopy(_REAL_DOC)
    doc["concepts"] = []
    broken = tmp_path / "scope_spec.yaml"
    broken.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    assert ps.main(["--spec", str(broken)]) == 1
    assert "ScopeSpecError" in capsys.readouterr().err


def test_cli_exits_one_when_the_spec_file_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert ps.main(["--spec", str(tmp_path / "nope.yaml")]) == 1
    assert "FileNotFoundError" in capsys.readouterr().err
