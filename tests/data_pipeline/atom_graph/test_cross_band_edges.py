"""고등→대학 경계 엣지 제안(S4-01) 검증기 테스트 — 정상 대조군 + 뮤테이션 전건 RED.

이 테스트의 목적은 두 가지다:

1. **제안 24건 동결** — 커밋된 `cross_band_edges_university_v1.json`이 정본 graph.json에 대해
   error 0건임을 못 박는다(성공 기준). 저작 목록이 바뀌면 여기서 먼저 깨진다.
2. **검증기의 변별력 증명** — 정상 입력에서 초록인 것은 보호의 증거가 아니다(CLAUDE.md
   "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지"). 그래서 검사 항목마다 *그 검사가
   없으면 통과할 입력*을 주입해 RED를 확인하고, **정상 대조군**을 함께 둔다 — 대조군이 없으면
   "모든 입력을 error로 뱉는 과잉 검증기"도 뮤테이션 전건 RED로 위장할 수 있다.

뮤테이션 하네스는 **순수 Python**이다(셸 이스케이프로 주입이 조용히 실패해 미적용 주입이
"검출"로 보인 사고 선례 — 2026-09-06). 주입 직후 `mutated != original`을 단언하고, 검증 후
원본 객체와 **디스크 파일 바이트**가 그대로인지 단언한다(이 검증기는 읽기 전용이다).
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
from data_pipeline.atom_graph.cross_band_edges import (
    PROPOSAL_EVIDENCE,
    CrossBandValidationReport,
    main,
    proposal_edges,
    validate_cross_band_edges,
)

# tests/data_pipeline/atom_graph/ → parents[3] = 프로젝트 루트(conftest.py와 같은 규약).
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
CORPUS_DIR = _PROJECT_ROOT / "data" / "corpus" / "atom_graph_v1"
PROPOSAL_PATH = CORPUS_DIR / "cross_band_edges_university_v1.json"
GRAPH_PATH = CORPUS_DIR / "graph.json"
BUILDER_PATH = _PROJECT_ROOT / "scripts" / "build_cross_band_edges_s4_01.py"

_EXPECTED_EDGE_COUNT = 24

Mutation = Callable[[dict[str, Any]], None]


@pytest.fixture(scope="session")
def proposal_bytes() -> bytes:
    """제안 파일 원본 바이트(원복 단언의 기준). 없으면 skip."""
    if not PROPOSAL_PATH.exists():
        pytest.skip(f"제안 미생성: {PROPOSAL_PATH} — scripts/build_cross_band_edges_s4_01.py 실행")
    return PROPOSAL_PATH.read_bytes()


@pytest.fixture()
def proposal(proposal_bytes: bytes) -> dict[str, Any]:
    """제안 payload(테스트마다 새 dict — 뮤테이션 격리)."""
    return json.loads(proposal_bytes.decode("utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="session")
def graph() -> dict[str, Any]:
    """정본 graph.json. 없으면 skip."""
    if not GRAPH_PATH.exists():
        pytest.skip(f"코퍼스 미생성: {GRAPH_PATH}")
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _node_index(graph: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(c["code"]): c for c in graph["concepts"]}


def _run_mutation(
    proposal_bytes: bytes,
    graph: Mapping[str, Any],
    mutate: Mutation,
) -> CrossBandValidationReport:
    """뮤테이션 1종 실행 — 주입 실재·원복 무결을 단언하고 검증 리포트를 돌려준다.

    ① 주입 전 스냅샷(정렬 직렬화) 확보 → ② deepcopy에 주입 → ③ `mutated != original` 단언
    (주입이 조용히 실패하면 정상 파일에 대해 검증이 돌아 "N passed"가 검출처럼 보인다)
    → ④ 검증 → ⑤ 원본 객체·디스크 바이트 무변경 단언.
    """
    original: dict[str, Any] = json.loads(proposal_bytes.decode("utf-8"))
    snapshot = json.dumps(original, ensure_ascii=False, sort_keys=True)

    mutated = copy.deepcopy(original)
    mutate(mutated)
    assert mutated != original, "주입이 적용되지 않았다 — 뮤테이션 하네스 결함(검출이 아니다)"

    report = validate_cross_band_edges(proposal_edges(mutated), graph)

    assert json.dumps(original, ensure_ascii=False, sort_keys=True) == snapshot, "원본 객체 오염"
    assert PROPOSAL_PATH.read_bytes() == proposal_bytes, "검증기가 디스크 파일을 건드렸다"
    return report


class TestProposalFileShape:
    """제안 파일 자체의 형태 동결(_meta·레코드 스키마·정본 무변경 전제)."""

    def test_meta_fields(self, proposal: dict[str, Any], graph: dict[str, Any]) -> None:
        meta = proposal["_meta"]
        assert meta["generated_by"] == "scripts/build_cross_band_edges_s4_01.py"
        assert meta["task"] == "S4-01-math-k12-complete"
        assert meta["status"].startswith("proposal")
        assert meta["edge_count"] == _EXPECTED_EDGE_COUNT
        # 제안이 전제한 정본 스냅샷 — graph.json이 바뀌면 재검수 신호가 된다.
        assert meta["source_graph_sha256"] == hashlib.sha256(GRAPH_PATH.read_bytes()).hexdigest()

    def test_edge_count_and_record_shape(self, proposal: dict[str, Any]) -> None:
        edges = proposal_edges(proposal)
        assert len(edges) == _EXPECTED_EDGE_COUNT
        expected_keys = {
            "from_code",
            "from_name",
            "to_code",
            "to_name",
            "relation",
            "relation_subtype",
            "school_link",
            "strength",
            "evidence",
            "rationale",
        }
        for edge in edges:
            assert set(edge) == expected_keys
            assert edge["relation"] == "prerequisite"  # 신규 relation 타입 0건
            assert edge["relation_subtype"] == "학교급간(추정)"
            assert edge["school_link"] is True
            assert edge["strength"] == 0.8
            assert edge["evidence"] == PROPOSAL_EVIDENCE
            assert edge["rationale"].strip()

    def test_names_match_canonical_graph(
        self, proposal: dict[str, Any], graph: dict[str, Any]
    ) -> None:
        """from_name/to_name은 손 타이핑이 아니라 정본 조회값이어야 한다."""
        nodes = _node_index(graph)
        for edge in proposal_edges(proposal):
            assert edge["from_name"] == nodes[edge["from_code"]]["name"]
            assert edge["to_name"] == nodes[edge["to_code"]]["name"]

    def test_regeneration_is_byte_identical(self, proposal_bytes: bytes) -> None:
        """결정론 — 생성 스크립트를 다시 돌리면 같은 바이트가 나온다(재현성)."""
        spec = importlib.util.spec_from_file_location("s4_01_builder", BUILDER_PATH)
        assert spec is not None and spec.loader is not None
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)

        graph_payload = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
        sha = hashlib.sha256(GRAPH_PATH.read_bytes()).hexdigest()
        regenerated = builder.serialize(builder.build_payload(graph_payload, sha))
        assert regenerated.encode("utf-8") == proposal_bytes


class TestControlGroup:
    """정상 대조군 — 무결한 제안은 GREEN(과잉 검증기 위장 방지)."""

    def test_pristine_proposal_passes(
        self, proposal: dict[str, Any], graph: dict[str, Any]
    ) -> None:
        report = validate_cross_band_edges(proposal_edges(proposal), graph)
        assert report.errors == [], report.report_text()
        assert report.success is True
        assert report.proposal_count == _EXPECTED_EDGE_COUNT
        assert report.existing_edge_count == len(graph["edges"])

    def test_pristine_proposal_has_no_subject_warning(
        self, proposal: dict[str, Any], graph: dict[str, Any]
    ) -> None:
        """24건 전부 허용 계열표 안 — 경고 0건(계열표가 실제로 이 제안을 덮는지 확인)."""
        report = validate_cross_band_edges(proposal_edges(proposal), graph)
        assert report.warnings == [], report.report_text()

    def test_report_text_says_pass(self, proposal: dict[str, Any], graph: dict[str, Any]) -> None:
        report = validate_cross_band_edges(proposal_edges(proposal), graph)
        assert "PASS" in report.summary()


def _first_high_school_pair(graph: Mapping[str, Any]) -> tuple[str, str]:
    """정본에서 '고등 세부개념 → 고등 세부개념' 엣지 1건을 결정론적으로 고른다(M7 재료)."""
    nodes = _node_index(graph)
    for edge in graph["edges"]:
        a, b = nodes.get(str(edge["from_code"])), nodes.get(str(edge["to_code"]))
        if a is None or b is None:
            continue
        if (
            a.get("school_level") == "고등"
            and b.get("school_level") == "고등"
            and a.get("level") == "세부개념"
            and b.get("level") == "세부개념"
        ):
            return str(edge["from_code"]), str(edge["to_code"])
    pytest.fail("정본에 고등-고등 세부개념 엣지가 없다 — M7 재료 부재")


def _edge_record(
    from_code: str, to_code: str, *, rationale: str = "뮤테이션 합성 근거"
) -> dict[str, Any]:
    """합성 제안 레코드(추가형 뮤테이션 재료)."""
    return {
        "from_code": from_code,
        "from_name": "합성",
        "to_code": to_code,
        "to_name": "합성",
        "relation": "prerequisite",
        "relation_subtype": "학교급간(추정)",
        "school_link": True,
        "strength": 0.8,
        "evidence": PROPOSAL_EVIDENCE,
        "rationale": rationale,
    }


class TestMutations:
    """뮤테이션 전건 RED — 검사 항목마다 그 검사가 없으면 통과할 입력을 주입한다."""

    def test_m1_missing_endpoint_code(self, proposal_bytes: bytes, graph: dict[str, Any]) -> None:
        """M1: 존재하지 않는 code → endpoint_exists RED."""

        def mutate(payload: dict[str, Any]) -> None:
            payload["edges"][0]["to_code"] = "NO-SUCH-CODE-XYZ"

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert "endpoint_exists" in report.rules_hit(), report.report_text()
        assert report.success is False

    def test_m2_reversed_direction(self, proposal_bytes: bytes, graph: dict[str, Any]) -> None:
        """M2: from/to를 뒤집음(대학→고등) → direction RED."""

        def mutate(payload: dict[str, Any]) -> None:
            edge = payload["edges"][0]
            edge["from_code"], edge["to_code"] = edge["to_code"], edge["from_code"]
            edge["from_name"], edge["to_name"] = edge["to_name"], edge["from_name"]

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert "direction_high_to_university" in report.rules_hit(), report.report_text()
        assert report.success is False

    def test_m3_university_to_university(
        self, proposal_bytes: bytes, graph: dict[str, Any]
    ) -> None:
        """M3: 대학→대학(동급) 엣지 추가 → direction RED."""
        nodes = _node_index(graph)
        assert nodes["CALC1-C03"]["school_level"] == "대학"
        assert nodes["CALC1-C05"]["school_level"] == "대학"

        def mutate(payload: dict[str, Any]) -> None:
            payload["edges"].append(_edge_record("CALC1-C03", "CALC1-C05"))

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert "direction_high_to_university" in report.rules_hit(), report.report_text()
        assert report.success is False

    def test_m4_container_node_endpoint(self, proposal_bytes: bytes, graph: dict[str, Any]) -> None:
        """M4: 컨테이너(소단원) code 사용 → level_detail_concept RED."""
        nodes = _node_index(graph)
        container = str(nodes["12미적Ⅰ-01-01-1"]["parent_code"])
        assert nodes[container]["level"] == "소단원"  # 재료가 실제로 컨테이너인지 확인

        def mutate(payload: dict[str, Any]) -> None:
            payload["edges"][0]["from_code"] = container

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert "level_detail_concept" in report.rules_hit(), report.report_text()
        assert report.success is False

    def test_m5_duplicate_within_proposal(
        self, proposal_bytes: bytes, graph: dict[str, Any]
    ) -> None:
        """M5: 같은 엣지 2건 중복 → no_duplicate RED."""

        def mutate(payload: dict[str, Any]) -> None:
            payload["edges"].append(copy.deepcopy(payload["edges"][0]))

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert "no_duplicate" in report.rules_hit(), report.report_text()
        assert report.success is False

    def test_m6_duplicate_of_existing_graph_edge(
        self, proposal_bytes: bytes, graph: dict[str, Any]
    ) -> None:
        """M6: 기존 graph.json에 이미 있는 엣지를 제안에 추가 → no_duplicate RED."""
        existing = graph["edges"][0]

        def mutate(payload: dict[str, Any]) -> None:
            payload["edges"].append(
                _edge_record(str(existing["from_code"]), str(existing["to_code"]))
            )

        report = _run_mutation(proposal_bytes, graph, mutate)
        hits = report.rules_hit()
        assert "no_duplicate" in hits, report.report_text()
        detail = " ".join(i.detail for i in report.issues if i.rule == "no_duplicate")
        assert "기존" in detail  # 제안 내부 중복이 아니라 *정본* 중복으로 잡혔는지
        assert report.success is False

    def test_m7_cycle_when_merged(self, proposal_bytes: bytes, graph: dict[str, Any]) -> None:
        """M7: 병합 시 사이클 발생 → acyclic_when_merged RED.

        대학→고등 역방향을 쓰지 않고(그건 direction이 먼저 잡는다) **정본의 고등-고등 엣지를
        역방향으로 제안에 넣어** 우회 경로로 2-사이클을 만든다 — 사이클 검사만이 잡는 형태다.
        """
        a, b = _first_high_school_pair(graph)

        def mutate(payload: dict[str, Any]) -> None:
            payload["edges"].append(_edge_record(b, a))  # 정본 a→b 의 역방향

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert "acyclic_when_merged" in report.rules_hit(), report.report_text()
        assert report.success is False

    def test_m8_empty_rationale(self, proposal_bytes: bytes, graph: dict[str, Any]) -> None:
        """M8: rationale 공백 → rationale_present RED(교육적 근거 없는 엣지 차단)."""

        def mutate(payload: dict[str, Any]) -> None:
            payload["edges"][0]["rationale"] = "   "

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert "rationale_present" in report.rules_hit(), report.report_text()
        assert report.success is False

    def test_m9_foreign_relation_type(self, proposal_bytes: bytes, graph: dict[str, Any]) -> None:
        """M9: prerequisite 외 관계 타입 → relation_prerequisite_only RED(관계 폭발 차단)."""

        def mutate(payload: dict[str, Any]) -> None:
            payload["edges"][0]["relation"] = "similar_to"

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert "relation_prerequisite_only" in report.rules_hit(), report.report_text()
        assert report.success is False


class TestSubjectCoherenceIsWarningOnly:
    """계열표 이탈은 warning — 검수 신호이지 차단이 아니다(과잉 차단 방지)."""

    def test_incoherent_subject_pair_warns_but_passes(
        self, proposal_bytes: bytes, graph: dict[str, Any]
    ) -> None:
        nodes = _node_index(graph)
        # 고등 '확률과 통계' → 대학 '미적분학 I' = 계열표에 없는 쌍(방향·수준은 적법).
        assert nodes["12확통02-01-1"]["subject_area"] == "확률과 통계"
        assert nodes["CALC1-C03"]["subject_area"] == "미적분학 I"

        def mutate(payload: dict[str, Any]) -> None:
            payload["edges"].append(_edge_record("12확통02-01-1", "CALC1-C03"))

        report = _run_mutation(proposal_bytes, graph, mutate)
        assert "subject_coherence" in report.rules_hit(), report.report_text()
        assert [i.severity for i in report.issues if i.rule == "subject_coherence"] == ["warning"]
        assert report.success is True  # warning은 통과


class TestCli:
    """CLI 판정은 exit 0/1이어야 한다 — 리포트 문구가 아니라 **종료 코드**가 판정이다."""

    def _args(self, proposal: Path) -> list[str]:
        return ["--proposal", str(proposal), "--graph", str(GRAPH_PATH)]

    def test_exit_zero_on_clean_proposal(self, proposal_bytes: bytes) -> None:
        assert main(self._args(PROPOSAL_PATH)) == 0
        assert PROPOSAL_PATH.read_bytes() == proposal_bytes  # 읽기 전용

    def test_exit_one_on_broken_proposal(self, proposal_bytes: bytes, tmp_path: Path) -> None:
        broken = json.loads(proposal_bytes.decode("utf-8"))
        broken["edges"][0]["to_code"] = "NO-SUCH-CODE-XYZ"
        target = tmp_path / "broken.json"
        target.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
        assert main(self._args(target)) == 1

    def test_exit_one_on_missing_file(self, tmp_path: Path) -> None:
        """파일 부재를 조용히 통과시키지 않는다(없으면 검사 0건 통과가 되는 사각)."""
        assert main(self._args(tmp_path / "없는파일.json")) == 1
