"""concept_graph 그래프 검증 단위테스트 — §5 invariant 1:1 대응.

정본: docs/data/concept_graph.md §5 표.
"""

from __future__ import annotations

import json
from pathlib import Path

from data_pipeline.concept_graph.models import Concept, ConceptEdge
from data_pipeline.concept_graph.transform import transform_dataset
from data_pipeline.concept_graph.validate import (
    validate_dataset,
    validate_graph,
    validate_idmap,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
# 고정 지점이 사실 파일 한 곳이다 — 값이 바뀌면 그 파일의 diff가 의식적 리뷰 지점이다.
_FACTS = json.loads(
    (_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
)


def _concept(
    concept_id: str, *, standard_codes: list[str] | None = None, **over: object
) -> Concept:
    # 기본은 *신규* 후보(source_id==concept_id) — alias_roundtrip 옛 키 요건 면제. 표시이름은
    # 노드 비내장(P2d Concept Purity)이라 name_* 인자 없음. 마이그레이션 케이스는 over로 주입.
    src_id = concept_id
    data: dict[str, object] = {
        "concept_id": concept_id,
        "source_id": src_id,
        "aliases": [],
        "domain": "미적분",
        "standard_codes": standard_codes or [],
    }
    data.update(over)
    return Concept(**data)  # type: ignore[arg-type]


def _edge(src: str, dst: str, relation: str = "prerequisite", **over: object) -> ConceptEdge:
    data: dict[str, object] = {
        "src_concept_id": src,
        "dst_concept_id": dst,
        "relation": relation,
        "strength": 0.8,
        "evidence": "근거",
        "evidence_source": "ncic",
    }
    data.update(over)
    return ConceptEdge(**data)  # type: ignore[arg-type]


_A = "math.calculus.aa"
_B = "math.calculus.bb"
_C = "math.calculus.cc"


def _rules(report: object) -> set[str]:
    return {i.rule for i in report.issues}  # type: ignore[attr-defined]


class TestCycle:
    def test_detects_prerequisite_cycle(self) -> None:
        """선수관계 순환 → error, success=False."""
        concepts = [_concept(_A), _concept(_B)]
        edges = [_edge(_A, _B), _edge(_B, _A)]
        report = validate_graph(concepts, edges)
        assert "prerequisite_cycle" in _rules(report)
        assert report.success is False
        assert len(report.errors) == 1

    def test_acyclic_graph_has_no_cycle_error(self) -> None:
        concepts = [_concept(_A), _concept(_B)]
        edges = [_edge(_A, _B)]
        report = validate_graph(concepts, edges)
        assert "prerequisite_cycle" not in _rules(report)
        assert report.success is True


class TestInversePair:
    def test_warns_generalization_specialization_inverse(self) -> None:
        """(A→B generalization) + (B→A specialization) → warning."""
        concepts = [_concept(_A), _concept(_B)]
        edges = [
            _edge(_A, _B, relation="generalization"),
            _edge(_B, _A, relation="specialization"),
        ]
        report = validate_graph(concepts, edges)
        assert "inverse_pair" in _rules(report)
        assert report.success is True  # warning이라 통과

    def test_no_inverse_when_only_one_direction(self) -> None:
        report = validate_graph(
            [_concept(_A), _concept(_B)], [_edge(_A, _B, relation="generalization")]
        )
        assert "inverse_pair" not in _rules(report)


class TestIsolatedNode:
    def test_warns_isolated_node(self) -> None:
        """엣지에 안 닿는 노드 → warning."""
        concepts = [_concept(_A), _concept(_B), _concept(_C)]
        edges = [_edge(_A, _B)]  # _C 고립
        report = validate_graph(concepts, edges)
        isolated = [i for i in report.issues if i.rule == "isolated_node"]
        assert len(isolated) == 1
        assert isolated[0].ref == _C


class TestDangling:
    def test_warns_dangling_edge_endpoint(self) -> None:
        """엣지가 노드 집합에 없는 끝점을 가리키면 warning."""
        report = validate_graph([_concept(_A)], [_edge(_A, _B)])  # _B 노드 없음
        assert "dangling_edge_endpoint" in _rules(report)
        assert report.success is True

    def test_warns_dangling_prerequisite_cache(self) -> None:
        report = validate_graph([_concept(_A, prerequisite_concept_ids=[_B])], [])
        assert "dangling_prerequisite_ref" in _rules(report)

    def test_warns_dangling_misconception_when_catalog_given(self) -> None:
        """known 카탈로그 주어지면 미수록 오개념 키 → warning."""
        concepts = [_concept(_A, misconception_codes=["unknown-mc"])]
        report = validate_graph(concepts, [], known_misconception_codes={"known-mc"})
        assert "dangling_misconception" in _rules(report)

    def test_skips_dangling_misconception_without_catalog(self) -> None:
        """known 미지정이면 검증 불가 → 건너뜀(경고 없음)."""
        concepts = [_concept(_A, misconception_codes=["whatever"])]
        report = validate_graph(concepts, [])
        assert "dangling_misconception" not in _rules(report)


class TestGradeMonotonic:
    def test_warns_when_prerequisite_grade_inverted(self) -> None:
        """선수개념(11학년)이 후행(10학년)보다 높은 학년 → warning."""
        senior = _concept(_C, standard_codes=["[11미적Ⅰ01-01]"])  # g11
        junior = _concept(_A, standard_codes=["[10공수1-01-01]"])  # g10
        edges = [_edge(_C, _A)]  # 11학년이 10학년의 선수 — 역전
        report = validate_graph([senior, junior], edges)
        assert "grade_monotonic" in _rules(report)

    def test_no_warning_when_grade_monotonic(self) -> None:
        junior = _concept(_A, standard_codes=["[10공수1-01-01]"])  # g10
        senior = _concept(_C, standard_codes=["[11미적Ⅰ01-01]"])  # g11
        edges = [_edge(_A, _C)]  # 10학년이 11학년의 선수 — 정상
        report = validate_graph([junior, senior], edges)
        assert "grade_monotonic" not in _rules(report)

    def test_skips_when_no_standard_codes(self) -> None:
        """standard_codes 없으면 학년 비교 건너뜀."""
        report = validate_graph([_concept(_A), _concept(_B)], [_edge(_A, _B)])
        assert "grade_monotonic" not in _rules(report)


class TestWeakEdge:
    """weight floor(Part 3 '낮은 weight 제거') — MIN_EDGE_STRENGTH 미만은 warning."""

    def test_warns_below_floor(self) -> None:
        """strength가 하한 미만이면 weak_edge warning(적재 비차단)."""
        concepts = [_concept(_A), _concept(_B)]
        edges = [_edge(_A, _B, strength=0.1)]  # 하한 0.3 미만
        report = validate_graph(concepts, edges)
        assert "weak_edge" in _rules(report)
        assert report.success is True  # warning이라 통과

    def test_no_warning_at_or_above_floor(self) -> None:
        """하한 이상(0.3·기본 0.8)이면 weak_edge 없음."""
        concepts = [_concept(_A), _concept(_B), _concept(_C)]
        edges = [_edge(_A, _B, strength=0.3), _edge(_B, _C, strength=0.8)]
        report = validate_graph(concepts, edges)
        assert "weak_edge" not in _rules(report)


class TestPrerequisiteCacheConsistency:
    """prerequisite_concept_ids 캐시 == prerequisite 엣지 src 집합(dual-truth drift 방어)."""

    def test_consistent_cache_no_warning(self) -> None:
        """캐시가 엣지와 일치하면 경고 없음(_B가 _A의 선수 — dst=_A 캐시에 _B)."""
        concepts = [_concept(_A, prerequisite_concept_ids=[_B]), _concept(_B)]
        edges = [_edge(_B, _A)]  # src=_B(선수) → dst=_A(후행)
        report = validate_graph(concepts, edges)
        assert "prerequisite_cache_consistency" not in _rules(report)

    def test_cache_missing_edge_source_warns(self) -> None:
        """엣지엔 선수가 있으나 캐시가 비면 불일치 warning."""
        concepts = [_concept(_A, prerequisite_concept_ids=[]), _concept(_B)]
        edges = [_edge(_B, _A)]  # 캐시엔 _B 누락
        report = validate_graph(concepts, edges)
        assert "prerequisite_cache_consistency" in _rules(report)
        assert report.success is True

    def test_cache_extra_without_edge_warns(self) -> None:
        """캐시엔 선수가 있으나 대응 엣지가 없으면 불일치 warning."""
        concepts = [_concept(_A, prerequisite_concept_ids=[_B]), _concept(_B)]
        edges: list[ConceptEdge] = []  # 대응 prerequisite 엣지 없음
        report = validate_graph(concepts, edges)
        assert "prerequisite_cache_consistency" in _rules(report)

    def test_non_prerequisite_edge_not_counted(self) -> None:
        """비-prerequisite 관계는 캐시 기대치에 포함되지 않는다(선수 캐시 전용)."""
        concepts = [_concept(_A, prerequisite_concept_ids=[]), _concept(_B)]
        edges = [_edge(_B, _A, relation="generalization")]  # 선수 아님 → 캐시 기대 0
        report = validate_graph(concepts, edges)
        assert "prerequisite_cache_consistency" not in _rules(report)


class TestReport:
    def test_summary_counts(self) -> None:
        report = validate_graph([_concept(_A), _concept(_B)], [_edge(_A, _B)])
        assert "노드 2개" in report.summary()
        assert "엣지 1개" in report.summary()

    def test_summary_pass_verdict(self) -> None:
        report = validate_graph([_concept(_A), _concept(_B)], [_edge(_A, _B)])
        assert "PASS" in report.summary()

    def test_summary_fail_verdict_on_cycle(self) -> None:
        report = validate_graph([_concept(_A), _concept(_B)], [_edge(_A, _B), _edge(_B, _A)])
        assert "FAIL" in report.summary()

    def test_counts_by_rule(self) -> None:
        """rule별 집계 — 고립 2건이면 isolated_node: 2."""
        report = validate_graph([_concept(_A), _concept(_B), _concept(_C)], [])
        tally = report.counts_by_rule()
        assert tally.get("isolated_node") == 3

    def test_report_text_lists_examples(self) -> None:
        """report_text에 rule별 집계와 예시가 포함된다."""
        report = validate_graph([_concept(_A)], [_edge(_A, _B)])  # dangling 끝점
        text = report.report_text()
        assert "dangling_edge_endpoint" in text
        assert "rule별 집계" in text


class TestIdInvariants:
    """P2a 재ID 그래프 레벨 불변식 — id_conformance·id_unique·alias_roundtrip(전부 error)."""

    def test_clean_graph_has_no_id_errors(self) -> None:
        """정상 개념(새 ID·source_id·옛 UC 별칭)은 ID 불변식 위반 0."""
        report = validate_graph([_concept(_A), _concept(_B)], [])
        id_rules = {"id_conformance", "id_unique", "alias_roundtrip"}
        assert not (id_rules & _rules(report))

    def test_duplicate_concept_id_is_error(self) -> None:
        """같은 concept_id 2개 → id_unique error(success=False)."""
        dup = _concept(_A)
        report = validate_graph([_concept(_A), dup], [])
        assert "id_unique" in _rules(report)
        assert report.success is False

    def test_migrated_concept_missing_legacy_alias_is_error(self) -> None:
        """*재ID된* 개념(source_id≠concept_id)이 옛 UC 별칭을 잃으면 alias_roundtrip error."""
        # source_id='HK01'(원천 src_id) ≠ concept_id → 마이그레이션됨. 별칭에 옛 UC 없음.
        c = _concept(_A, source_id="HK01", aliases=["HK01"])
        report = validate_graph([c], [])
        assert "alias_roundtrip" in _rules(report)
        assert report.success is False

    def test_fresh_seed_without_legacy_alias_is_ok(self) -> None:
        """*신규* 후보(source_id==concept_id)는 옛 UC 별칭 면제(보존할 옛 키 없음)."""
        c = _concept(_A, aliases=[])  # source_id==concept_id(헬퍼 기본)·별칭 없음
        report = validate_graph([c], [])
        assert "alias_roundtrip" not in _rules(report)

    def test_migrated_source_id_must_be_in_aliases(self) -> None:
        """재ID된 개념의 source_id가 aliases에 없으면 error(원천 키 조회 불가)."""
        c = _concept(_A, source_id="HK01", aliases=["UC.common1.a01.hk01"])  # src_id 누락
        report = validate_graph([c], [])
        assert "alias_roundtrip" in _rules(report)
        assert report.success is False


class TestValidateIdmap:
    """원천 레코드 대상 재ID 불변식 — area_map_total·id_unique·alias_roundtrip(P2a 안전망)."""

    def _records(self) -> list[dict[str, object]]:
        return [
            {
                "src_id": "HK01",
                "name_ko": "다항식의 사칙연산",
                "category": "[공통]식·방정식·부등식",
                "difficulty_tier": "6",
                "standard_codes": ["[10공수1-01-01]"],
            },
            {
                "src_id": "HK02",
                "name_ko": "나머지정리와 인수정리",
                "category": "[공통]식·방정식·부등식",
                "difficulty_tier": "7",
                "standard_codes": ["[10공수1-01-02]"],
            },
        ]

    def test_clean_records_pass(self) -> None:
        report = validate_idmap(self._records())
        assert report.success is True
        assert report.errors == []
        assert report.node_count == 2

    def test_unmapped_category_is_area_map_error(self) -> None:
        """미수록 category → area_map_total error(KeyError를 error로 환원)."""
        bad = [{"src_id": "X1", "category": "외계수학", "standard_codes": ["[6수01-01]"]}]
        report = validate_idmap(bad)
        assert "area_map_total" in {i.rule for i in report.issues}
        assert report.success is False

    def test_real_corpus_idmap_passes(self, concept_records: list[dict[str, object]]) -> None:
        """실데이터 전건 재ID 불변식 전부 통과(area_map_total·id_unique·alias_roundtrip)."""
        report = validate_idmap(concept_records)
        assert report.node_count == _FACTS["concept_graph.concepts"]
        assert report.success is True
        assert report.errors == []


class TestValidateDataset:
    def test_wraps_transform_result(self) -> None:
        """validate_dataset은 TransformResult의 개념·엣지를 검증한다."""
        records = [
            {
                "src_id": "HK01",
                "name_ko": "다항식",
                "category": "[공통]식·방정식·부등식",
                "standard_codes": ["[10공수1-01-01]"],
            },
            {
                "src_id": "HK02",
                "name_ko": "나머지정리",
                "category": "[공통]식·방정식·부등식",
                "standard_codes": ["[10공수1-01-02]"],
            },
        ]
        edges = [{"from_id": "HK01", "relation": "선수(prereq)", "to_id": "HK02"}]
        result = transform_dataset(concept_records=records, edge_records=edges)
        report = validate_dataset(result)
        assert report.node_count == 2
        assert report.edge_count == 1
        assert report.success is True


class TestRealDataValidation:
    """실데이터 1회 전체 검증 — PASS(error 0) 단언 + 리포트 산출."""

    def test_full_dataset_passes(
        self,
        concept_records: list[dict[str, object]],
        edge_records: list[dict[str, object]],
    ) -> None:
        result = transform_dataset(concept_records=concept_records, edge_records=edge_records)
        report = validate_dataset(result)
        assert report.node_count == _FACTS["concept_graph.concepts"]
        assert report.edge_count == _FACTS["concept_graph.edges"]
        assert report.success is True  # error 0 (Phase 1: warning은 통과)
        assert report.errors == []

    def test_full_dataset_report_text_renders(
        self,
        concept_records: list[dict[str, object]],
        edge_records: list[dict[str, object]],
    ) -> None:
        """리포트 텍스트가 PASS 판정과 카운트를 담는다."""
        result = transform_dataset(concept_records=concept_records, edge_records=edge_records)
        report = validate_dataset(result)
        text = report.report_text()
        assert "PASS" in text
        assert f"노드 {_FACTS['concept_graph.concepts']}개" in text
        assert f"엣지 {_FACTS['concept_graph.edges']}개" in text
