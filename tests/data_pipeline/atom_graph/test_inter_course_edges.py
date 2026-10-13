"""대학 과목간 선수 엣지 제안(S4-01 슬라이스 3) 검증기 테스트 — 정상 대조군 + 뮤테이션 전건 RED.

두 가지를 증명한다:

1. **제안 동결** — 커밋된 `inter_course_edges_university_v1.json`이 정본 graph.json에 대해
   error 0건·warning 0건임을 못 박는다. 저작 목록이 바뀌면 여기서 먼저 깨진다.
2. **검증기의 변별력** — 정상 입력에서 초록인 것은 보호의 증거가 아니다. 검사 항목마다 *그 검사가
   없으면 통과할 입력*을 주입해 RED를 확인하고, **정상 대조군**을 함께 둔다(대조군이 없으면
   "모든 입력을 error로 뱉는 과잉 검증기"도 뮤테이션 전건 RED로 위장한다).

뮤테이션 하네스는 **순수 Python**이다. 주입 직후 `mutated != original`을 단언하고(주입이 조용히
실패하면 정상 파일에 대해 검증이 돌아 "통과"가 "검출"처럼 보인다), 검증 후 디스크 바이트 무변경을
단언한다(읽기 전용 검증기).

또한 *도달성 측정*(고등에서 선수 방향으로 도달 가능한 대학 세부개념 수)의 판별력을 따로 검증한다.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from data_pipeline.atom_graph.cross_band_edges import CrossBandValidationReport
from data_pipeline.atom_graph.cross_band_edges import proposal_edges as _proposal_edges
from data_pipeline.atom_graph.cross_band_edges_merge import pre_merge_view
from data_pipeline.atom_graph.inter_course_edges import (
    ALLOWED_COURSE_PAIRS,
    MAX_EDGES_PER_COURSE_PAIR,
    PROPOSAL_EVIDENCE,
    course_components,
    main,
    proposal_edges,
    university_reachability,
    validate_inter_course_edges,
)

# tests/data_pipeline/atom_graph/ → parents[3] = 프로젝트 루트.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
CORPUS_DIR = _PROJECT_ROOT / "data" / "corpus" / "atom_graph_v1"
PROPOSAL_PATH = CORPUS_DIR / "inter_course_edges_university_v1.json"
BOUNDARY_PROPOSAL_PATH = CORPUS_DIR / "cross_band_edges_university_v1.json"
GRAPH_PATH = CORPUS_DIR / "graph.json"
BUILDER_PATH = _PROJECT_ROOT / "scripts" / "build_inter_course_edges_s4_01.py"

#: 저작 목록 동결 값 — 검수로 일부가 반려되면 이 숫자와 아래 도달성 수치가 함께 바뀐다.
_EXPECTED_EDGE_COUNT = 129  # 2026-10-08 AI 검수: 137 − 반려 8

Mutation = Callable[[dict[str, Any]], None]


@pytest.fixture(scope="session")
def proposal_bytes() -> bytes:
    if not PROPOSAL_PATH.exists():
        pytest.skip(f"제안 미생성: {PROPOSAL_PATH} — scripts/build_inter_course_edges_s4_01.py")
    return PROPOSAL_PATH.read_bytes()


@pytest.fixture()
def proposal(proposal_bytes: bytes) -> dict[str, Any]:
    return json.loads(proposal_bytes.decode("utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="session")
def graph() -> dict[str, Any]:
    if not GRAPH_PATH.exists():
        pytest.skip(f"코퍼스 미생성: {GRAPH_PATH}")
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="session")
def boundary_pairs() -> list[tuple[str, str]]:
    """슬라이스 1(고→대 경계) 제안의 (from, to) 쌍 — 도달성 측정에서 K-12 진입로로 쓴다."""
    if not BOUNDARY_PROPOSAL_PATH.exists():
        pytest.skip(f"슬라이스 1 제안 없음: {BOUNDARY_PROPOSAL_PATH}")
    payload = json.loads(BOUNDARY_PROPOSAL_PATH.read_text(encoding="utf-8"))
    return [(str(e["from_code"]), str(e["to_code"])) for e in payload["edges"]]


def _node_index(graph: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(c["code"]): c for c in graph["concepts"]}


def _edge_record(from_code: str, to_code: str) -> dict[str, Any]:
    """정상 형태의 제안 레코드(뮤테이션이 주입하는 새 엣지의 틀)."""
    return {
        "from_code": from_code,
        "from_name": "-",
        "to_code": to_code,
        "to_name": "-",
        "relation": "prerequisite",
        "relation_subtype": "과목간(추정)",
        "school_link": False,
        "strength": 0.8,
        "evidence": PROPOSAL_EVIDENCE,
        "rationale": "테스트 주입용 근거",
    }


def _run_mutation(
    proposal_bytes: bytes,
    graph: Mapping[str, Any],
    mutate: Mutation,
) -> CrossBandValidationReport:
    """뮤테이션 1종 실행 — 주입 실재·원복 무결을 단언하고 검증 리포트를 돌려준다."""
    original: dict[str, Any] = json.loads(proposal_bytes.decode("utf-8"))
    snapshot = json.dumps(original, ensure_ascii=False, sort_keys=True)

    mutated = copy.deepcopy(original)
    mutate(mutated)
    assert mutated != original, "주입이 적용되지 않았다 — 뮤테이션 하네스 결함(검출이 아니다)"

    report = validate_inter_course_edges(proposal_edges(mutated), graph)

    assert json.dumps(original, ensure_ascii=False, sort_keys=True) == snapshot, "원본 객체 오염"
    assert PROPOSAL_PATH.read_bytes() == proposal_bytes, "검증기가 디스크 파일을 건드렸다"
    return report


class TestProposalFileShape:
    """제안 파일 자체의 형태 동결."""

    def test_meta_fields(self, proposal: dict[str, Any]) -> None:
        meta = proposal["_meta"]
        assert meta["generated_by"] == "scripts/build_inter_course_edges_s4_01.py"
        assert meta["task"] == "S4-01-math-k12-complete"
        assert meta["status"].startswith("proposal")
        assert meta["edge_count"] == _EXPECTED_EDGE_COUNT
        assert meta["source_graph_sha256"] == hashlib.sha256(GRAPH_PATH.read_bytes()).hexdigest()

    def test_edge_records(self, proposal: dict[str, Any], graph: dict[str, Any]) -> None:
        edges = proposal["edges"]
        assert len(edges) == _EXPECTED_EDGE_COUNT
        nodes = _node_index(graph)
        for e in edges:
            assert e["relation"] == "prerequisite"
            assert e["evidence"] == PROPOSAL_EVIDENCE
            assert e["rationale"].strip(), e
            # 노드명은 정본에서 조회해 채운 값이어야 한다(손 타이핑 불일치 차단).
            assert e["from_name"] == nodes[e["from_code"]]["name"]
            assert e["to_name"] == nodes[e["to_code"]]["name"]

    def test_no_new_relation_types_and_graph_untouched(self, graph: dict[str, Any]) -> None:
        """신규 relation 타입 0 — 정본의 relation 집합은 prerequisite 단일이다(제안이 늘리지 않음)."""
        assert {e["relation"] for e in graph["edges"]} == {"prerequisite"}
        assert len(graph["concepts"]) == 2683
        # 정본 = 백본 2,210 + S4-60 고→대 경계 병합 24. 이 제안(S4-61)은 아직 병합 전이라 무변경이다.
        assert len(graph["edges"]) == 2234  # 정본 무변경 동결
        assert len(pre_merge_view(graph)["edges"]) == 2210

    def test_report_label_default_is_preserved(self) -> None:
        """슬라이스 1 리포트의 기본 문구가 label 필드 추가로 바뀌지 않았다."""
        assert CrossBandValidationReport().summary().startswith("경계 엣지 제안 검증[PASS]")

    def test_proposal_edges_helper_is_shared(self) -> None:
        """슬라이스 1·3이 같은 레코드 추출 헬퍼를 공유한다(두 검증기가 갈라지지 않는다)."""
        assert proposal_edges is _proposal_edges


class TestCleanProposal:
    """정상 대조군 — 제안 137건이 error 0·warning 0."""

    def test_clean_proposal_passes_with_no_findings(
        self, proposal: dict[str, Any], graph: dict[str, Any]
    ) -> None:
        report = validate_inter_course_edges(proposal_edges(proposal), graph)
        assert report.success, report.report_text()
        assert report.issues == [], report.report_text()
        assert report.proposal_count == _EXPECTED_EDGE_COUNT
        assert report.summary().startswith("대학 과목간 엣지 제안 검증[PASS]")

    def test_every_course_pair_is_within_cap_and_allowed(
        self, proposal: dict[str, Any], graph: dict[str, Any]
    ) -> None:
        nodes = _node_index(graph)
        per_pair: dict[tuple[str, str], int] = {}
        for e in proposal["edges"]:
            key = (
                str(nodes[e["from_code"]]["subject_area"]),
                str(nodes[e["to_code"]]["subject_area"]),
            )
            per_pair[key] = per_pair.get(key, 0) + 1
        assert max(per_pair.values()) <= MAX_EDGES_PER_COURSE_PAIR
        assert set(per_pair) <= ALLOWED_COURSE_PAIRS
        # 허용 표가 *쓰이지 않는 쌍*을 쌓아 두지 않는다(표와 저작 목록의 동기화 동결).
        assert set(per_pair) == ALLOWED_COURSE_PAIRS

    def test_control_extra_valid_edge_under_cap_still_passes(
        self, proposal_bytes: bytes, graph: dict[str, Any]
    ) -> None:
        """대조군: 상한 미만 과목 쌍에 적법한 엣지를 더해도 통과한다(과잉 검증기 방지)."""

        def mutate(payload: dict[str, Any]) -> None:
            # 선형대수학 I → 선형대수학 II 는 3건(상한 4 미만).
            payload["edges"].append(_edge_record("LINA1-C01", "LINA2-C03"))

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert report.success, report.report_text()
        assert "pair_density_cap" not in report.rules_hit()


def _first_container_in_other_course(graph: Mapping[str, Any], avoid_subject: str) -> str:
    for c in graph["concepts"]:
        if (
            c["school_level"] == "대학"
            and c["level"] != "세부개념"
            and c["subject_area"] != avoid_subject
        ):
            return str(c["code"])
    raise AssertionError("대학 컨테이너 노드를 찾지 못했다 — 코퍼스 형태 변경")


class TestMutationsAreRed:
    """검사 항목마다 그 검사가 없으면 통과할 입력을 주입해 RED를 확인한다."""

    def test_m1_nonexistent_endpoint(self, proposal_bytes: bytes, graph: dict[str, Any]) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            payload["edges"][0]["to_code"] = "NO-SUCH-CODE-XYZ"

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert "endpoint_exists" in report.rules_hit(), report.report_text()
        assert report.success is False

    def test_m2_high_school_to_university_is_not_inter_course(
        self, proposal_bytes: bytes, graph: dict[str, Any]
    ) -> None:
        """M2: 고등→대학(슬라이스 1 소관)이 섞이면 direction_inter_course RED."""

        def mutate(payload: dict[str, Any]) -> None:
            payload["edges"].append(_edge_record("12미적Ⅰ-01-01-1", "CALC1-C03"))

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert "direction_inter_course" in report.rules_hit(), report.report_text()
        detail = " ".join(i.detail for i in report.issues if i.rule == "direction_inter_course")
        assert "대학이 아님" in detail
        assert report.success is False

    def test_m3_same_course_edge(self, proposal_bytes: bytes, graph: dict[str, Any]) -> None:
        """M3: 같은 과목 안 엣지(과목 내부는 정본 소관) → direction_inter_course RED."""

        def mutate(payload: dict[str, Any]) -> None:
            payload["edges"].append(_edge_record("CALC1-C01", "CALC1-C27"))

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert "direction_inter_course" in report.rules_hit(), report.report_text()
        detail = " ".join(i.detail for i in report.issues if i.rule == "direction_inter_course")
        assert "같은 과목" in detail
        assert report.success is False

    def test_m4_container_endpoint_on_either_side(
        self, proposal_bytes: bytes, graph: dict[str, Any]
    ) -> None:
        """M4: 단원·소단원 컨테이너에 선수관계를 걸면 level_detail_concept RED(양쪽 모두)."""
        container = _first_container_in_other_course(graph, "미적분학 I")

        def mutate_to(payload: dict[str, Any]) -> None:
            payload["edges"].append(_edge_record("CALC1-C01", container))

        def mutate_from(payload: dict[str, Any]) -> None:
            payload["edges"].append(_edge_record(container, "CALC1-C01"))

        for mutate in (mutate_to, mutate_from):
            report = _run_mutation(proposal_bytes, graph, mutate)
            assert "level_detail_concept" in report.rules_hit(), report.report_text()
            assert report.success is False

    def test_m5_duplicate_within_proposal(
        self, proposal_bytes: bytes, graph: dict[str, Any]
    ) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            payload["edges"].append(copy.deepcopy(payload["edges"][0]))

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert "no_duplicate" in report.rules_hit(), report.report_text()
        assert "제안 내부" in " ".join(i.detail for i in report.issues if i.rule == "no_duplicate")
        assert report.success is False

    def test_m6_duplicate_of_existing_graph_edge(
        self, proposal_bytes: bytes, graph: dict[str, Any]
    ) -> None:
        """M6: 정본에 이미 있는 과목간 엣지(CALC1-C16→NUMER-C06) 재등재 → no_duplicate RED."""
        pairs = {(e["from_code"], e["to_code"]) for e in graph["edges"]}
        assert ("CALC1-C16", "NUMER-C06") in pairs  # 전제: 정본의 기존 과목간 엣지

        def mutate(payload: dict[str, Any]) -> None:
            payload["edges"].append(_edge_record("CALC1-C16", "NUMER-C06"))

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert "no_duplicate" in report.rules_hit(), report.report_text()
        assert "기존" in " ".join(i.detail for i in report.issues if i.rule == "no_duplicate")
        assert report.success is False

    def test_m7_cycle_when_merged_by_reversing_a_proposal_edge(
        self, proposal_bytes: bytes, graph: dict[str, Any]
    ) -> None:
        """M7: 제안 엣지의 역방향을 더하면 2-사이클 → acyclic_when_merged RED."""

        def mutate(payload: dict[str, Any]) -> None:
            first = payload["edges"][0]
            payload["edges"].append(_edge_record(first["to_code"], first["from_code"]))

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert "acyclic_when_merged" in report.rules_hit(), report.report_text()
        assert report.success is False

    def test_m7b_cycle_through_existing_intra_course_chain(
        self, proposal_bytes: bytes, graph: dict[str, Any]
    ) -> None:
        """M7b: 실제로 만난 함정 — 미적분학 I 후반→수치해석 전반 엣지는 기존 사슬 때문에 순환.

        정본에 NUMER-P01→CALC1-C16 이 있고 CALC1 사슬이 C16→…→C26 으로 이어지며 수치해석 사슬이
        NUMER-C01→…→NUMER-C04→NUMER-P01 로 이어지므로 CALC1-C26→NUMER-C01 은 닫힌 고리를 만든다.
        제안 *단독*으로는 사이클이 보이지 않는 — 정본과 합쳐야만 보이는 — 형태다.
        """

        def mutate(payload: dict[str, Any]) -> None:
            payload["edges"].append(_edge_record("CALC1-C26", "NUMER-C01"))

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert "acyclic_when_merged" in report.rules_hit(), report.report_text()
        assert report.success is False

    def test_m8_empty_rationale(self, proposal_bytes: bytes, graph: dict[str, Any]) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            payload["edges"][0]["rationale"] = "   "

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert "rationale_present" in report.rules_hit(), report.report_text()
        assert report.success is False

    def test_m9_foreign_relation_type(self, proposal_bytes: bytes, graph: dict[str, Any]) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            payload["edges"][0]["relation"] = "related_to"

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert "relation_prerequisite_only" in report.rules_hit(), report.report_text()
        assert report.success is False

    def test_m10_pair_density_cap(self, proposal_bytes: bytes, graph: dict[str, Any]) -> None:
        """M10: 이미 상한(4건)인 과목 쌍에 5번째 엣지 → pair_density_cap RED(관계 폭발 방어)."""
        nodes = _node_index(graph)
        at_cap = [
            e
            for e in json.loads(proposal_bytes.decode("utf-8"))["edges"]
            if nodes[e["from_code"]]["subject_area"] == "미적분학 I"
            and nodes[e["to_code"]]["subject_area"] == "미적분학 II"
        ]
        assert len(at_cap) == MAX_EDGES_PER_COURSE_PAIR  # 전제: 이 쌍은 상한에 닿아 있다

        def mutate(payload: dict[str, Any]) -> None:
            payload["edges"].append(_edge_record("CALC1-C01", "CALC2-C01"))

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert "pair_density_cap" in report.rules_hit(), report.report_text()
        assert "미적분학 I → 미적분학 II" in " ".join(
            i.ref for i in report.issues if i.rule == "pair_density_cap"
        )
        assert report.success is False


class TestSubjectCoherenceIsWarningOnly:
    """과목 쌍 표 이탈은 warning — 검수 신호이지 차단이 아니다(과잉 차단 방지)."""

    def test_unlisted_course_pair_warns_but_passes(
        self, proposal_bytes: bytes, graph: dict[str, Any]
    ) -> None:
        nodes = _node_index(graph)
        assert nodes["CAPST-P01"]["subject_area"] == "졸업세미나학사논문"
        assert nodes["ANAL1-P01"]["subject_area"] == "해석학 I"
        assert ("졸업세미나학사논문", "해석학 I") not in ALLOWED_COURSE_PAIRS

        def mutate(payload: dict[str, Any]) -> None:
            payload["edges"].append(_edge_record("CAPST-P01", "ANAL1-P01"))

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert report.rules_hit() == {"subject_coherence"}, report.report_text()
        assert [i.severity for i in report.issues] == ["warning"]
        assert report.success is True  # warning은 통과


class TestReachability:
    """도달성 측정 — '4축 활성'을 노드 존재가 아니라 도달 가능성으로 말한다."""

    def test_baseline_university_is_an_island(self, graph: dict[str, Any]) -> None:
        """병합 *전* 정본(S4-60 이전)에서는 대학이 섬이다 — pre_merge_view로 원래 주장을 보존한다."""
        rep = university_reachability(pre_merge_view(graph))
        assert rep.university_atoms == 512
        assert rep.university_courses == 32
        assert rep.reached_atoms == 0  # 고등→대학 엣지 0건이라 K-12에서 한 걸음도 못 간다
        assert rep.reached_courses == 0
        # 32과목 중 수치해석↔미적분학 I 두 과목만 정본에서 이어져 있다 → 31개 성분.
        assert rep.course_components == 31

    def test_baseline_after_boundary_merge(self, graph: dict[str, Any]) -> None:
        """S4-60 병합 후 정본의 기준선 — 경계 24건이 만든 진입로만큼 도달한다(수치는 실측 동결)."""
        rep = university_reachability(graph)
        assert rep.reached_atoms == 198
        assert rep.reached_courses == 7
        assert rep.course_components == 31  # 진입 엣지는 과목 사이를 잇지 않는다

    def test_this_proposal_alone_reaches_nothing(
        self, proposal: dict[str, Any], graph: dict[str, Any]
    ) -> None:
        """변별 대조군: 과목간 엣지만으로는 K-12 진입로가 없어 도달 0 — 측정이 값을 지어내지 않는다.

        진입로가 없는 병합 전 정본에 얹어야 이 주장이 성립한다(병합 후 정본엔 진입로가 이미 있다).
        """
        pairs = [(e["from_code"], e["to_code"]) for e in proposal["edges"]]
        rep = university_reachability(pre_merge_view(graph), pairs)
        assert rep.reached_atoms == 0
        # 그러나 과목 연결 구조는 바뀐다(성분 31 → 2).
        assert rep.course_components == 2

    def test_this_proposal_on_merged_graph_reaches_462(
        self, proposal: dict[str, Any], graph: dict[str, Any]
    ) -> None:
        """병합 후 정본 위에 이 제안을 얹으면 진입로(198) + 과목간 확산으로 462까지 도달한다."""
        pairs = [(e["from_code"], e["to_code"]) for e in proposal["edges"]]
        rep = university_reachability(graph, pairs)
        assert rep.reached_atoms == 462
        assert rep.reached_courses == 31
        assert rep.course_components == 2

    def test_boundary_proposal_alone_reaches_part_of_the_university(
        self, graph: dict[str, Any], boundary_pairs: list[tuple[str, str]]
    ) -> None:
        rep = university_reachability(graph, boundary_pairs)
        assert rep.reached_atoms == 198
        assert rep.reached_courses == 7
        assert rep.course_components == 31  # 진입 엣지는 과목 사이를 잇지 않는다

    def test_both_proposals_together(
        self,
        proposal: dict[str, Any],
        graph: dict[str, Any],
        boundary_pairs: list[tuple[str, str]],
    ) -> None:
        pairs = boundary_pairs + [(e["from_code"], e["to_code"]) for e in proposal["edges"]]
        rep = university_reachability(graph, pairs)
        assert rep.reached_atoms == 462  # AI 검수 반려 8건 후 재측정(종전 466)
        assert rep.university_atoms == 512
        assert rep.reached_courses == 31  # 졸업세미나(내용 선수 없음)만 제외
        assert rep.course_components == 2
        assert rep.atom_ratio == pytest.approx(462 / 512)
        assert "462/512" in rep.summary()

    def test_measure_is_sensitive_to_edges(
        self,
        proposal: dict[str, Any],
        graph: dict[str, Any],
        boundary_pairs: list[tuple[str, str]],
    ) -> None:
        """뮤테이션: 한 과목으로 들어오는 엣지를 전부 빼면 도달이 줄어든다(측정이 엣지에 반응)."""
        nodes = _node_index(graph)
        full = boundary_pairs + [(e["from_code"], e["to_code"]) for e in proposal["edges"]]
        without = [
            p
            for p in full
            if not (
                p in {(e["from_code"], e["to_code"]) for e in proposal["edges"]}
                and nodes[p[1]]["subject_area"] == "해석학 II"
            )
        ]
        assert len(without) < len(full), "주입(엣지 제거)이 적용되지 않았다"
        assert (
            university_reachability(graph, without).reached_atoms
            < university_reachability(graph, full).reached_atoms
        )

    def test_course_components_ignores_within_course_edges(self, graph: dict[str, Any]) -> None:
        """과목 내부 엣지는 성분 수에 영향이 없다 — 정본 481건이 있어도 31이다."""
        assert course_components(graph) == 31


class TestCli:
    """CLI 판정은 exit 0/1이어야 한다 — 리포트 문구가 아니라 **종료 코드**가 판정이다."""

    def _args(self, proposal: Path) -> list[str]:
        return ["--proposal", str(proposal), "--graph", str(GRAPH_PATH)]

    def test_exit_zero_on_clean_proposal(
        self, proposal_bytes: bytes, capsys: pytest.CaptureFixture[str]
    ) -> None:
        argv = [*self._args(PROPOSAL_PATH), "--also-proposal", str(BOUNDARY_PROPOSAL_PATH)]
        assert main(argv) == 0
        out = capsys.readouterr().out
        assert "[PASS]" in out
        assert "462/512" in out  # 도달성 병기: 슬라이스 1+3 병합 가정 결과
        assert PROPOSAL_PATH.read_bytes() == proposal_bytes  # 읽기 전용

    def test_exit_one_on_broken_proposal(self, proposal_bytes: bytes, tmp_path: Path) -> None:
        broken = json.loads(proposal_bytes.decode("utf-8"))
        broken["edges"][0]["to_code"] = "NO-SUCH-CODE-XYZ"
        target = tmp_path / "broken.json"
        target.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
        assert main(self._args(target)) == 1

    def test_exit_one_on_missing_proposal_or_extra_file(self, tmp_path: Path) -> None:
        """파일 부재를 조용히 통과시키지 않는다(없으면 검사 0건 통과가 되는 사각)."""
        assert main(self._args(tmp_path / "없는파일.json")) == 1
        argv = [*self._args(PROPOSAL_PATH), "--also-proposal", str(tmp_path / "없는파일.json")]
        assert main(argv) == 1


def _load_builder() -> Any:
    spec = importlib.util.spec_from_file_location("build_inter_course_edges_s4_01", BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestBuilder:
    """생성 스크립트 — 결정론·멱등·정본 조회 규율."""

    def test_regeneration_is_byte_identical(
        self, proposal_bytes: bytes, graph: dict[str, Any]
    ) -> None:
        builder = _load_builder()
        sha = hashlib.sha256(GRAPH_PATH.read_bytes()).hexdigest()
        regenerated = builder.serialize(builder.build_payload(graph, sha)).encode("utf-8")
        assert regenerated == proposal_bytes

    def test_check_mode_exit_zero(self) -> None:
        assert _load_builder().main(["--check"]) == 0

    def test_authored_list_has_no_duplicates_and_matches_evidence(self) -> None:
        builder = _load_builder()
        pairs = [(f, t) for f, t, _ in builder.AUTHORED_EDGES]
        assert len(pairs) == len(set(pairs)) == _EXPECTED_EDGE_COUNT
        assert builder.EVIDENCE == PROPOSAL_EVIDENCE
        assert all(r.strip() for _, _, r in builder.AUTHORED_EDGES)

    def test_unknown_code_fails_loudly(
        self, graph: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """코드가 정본에 없으면 이름을 비워 두고 넘어가지 않고 즉시 실패한다."""
        builder = _load_builder()
        monkeypatch.setattr(
            builder, "AUTHORED_EDGES", (("CALC1-C01", "NO-SUCH-CODE", "근거"),), raising=True
        )
        with pytest.raises(KeyError):
            builder.build_payload(graph, "0" * 64)
