"""원자 백본 Neo4j 적재 단위테스트 — FAKE 드라이버 주입(실 Neo4j 불요).

정본: docs/data/atom_graph_v1.md(§6 Phase 2 파생 스토어) + load.py 설계 핵심. 실 Neo4j 왕복은
test_load_neo4j_integration.py(통합·기본 SKIP)에서 한다. 여기서는 발행 Cypher가 ① CONSTRAINT
② 노드 MERGE ③ 엣지 MERGE(:ATOM_PREREQUISITE)를 포함하고, 멱등(2회=동일)이며, 끝점·relation을
엣지 속성에서 빼고, atomicity dict를 JSON 문자열로 직렬화하며, 어디에도 시크릿이 없음을
*주입 FAKE*로
검증한다. concept_graph/test_load.py의 분담을 원자 스키마로 미러링한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pytest
from data_pipeline.atom_graph.load import (
    CONSTRAINT_NAME,
    NODE_LABEL,
    AtomGraphCycleError,
    LoadReport,
    ensure_schema,
    load_graph,
    merge_edges,
    merge_nodes,
)
from data_pipeline.atom_graph.models import AtomConcept, AtomEdge, NodeLevel, SchoolLevel
from data_pipeline.atom_graph.transform import TransformResult


# ──────────────────────────────────────────────────────────────────────
# FAKE neo4j 드라이버 — session.run 호출(쿼리·파라미터)을 기록만 한다.
# ──────────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class _RunCall:
    """기록된 session.run 1건."""

    query: str
    params: dict[str, Any]


class _FakeResult:
    """neo4j Result 모사 — single()만 제공."""

    def single(self) -> None:  # pragma: no cover - 본 테스트는 결과를 안 읽음
        return None


class _FakeSession:
    """neo4j Session 모사 — run 기록 + context manager."""

    def __init__(self, calls: list[_RunCall], session_kwargs: dict[str, Any]) -> None:
        self._calls = calls
        self.session_kwargs = session_kwargs

    def run(self, query: str, **parameters: Any) -> _FakeResult:
        self._calls.append(_RunCall(query=query, params=dict(parameters)))
        return _FakeResult()

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeDriver:
    """neo4j Driver 모사 — session()·close(). 발행된 run을 calls에 누적."""

    def __init__(self) -> None:
        self.calls: list[_RunCall] = []
        self.closed = False
        self.last_session_kwargs: dict[str, Any] = {}

    def session(self, **kwargs: Any) -> _FakeSession:
        self.last_session_kwargs = dict(kwargs)
        return _FakeSession(self.calls, dict(kwargs))

    def close(self) -> None:
        self.closed = True


# ──────────────────────────────────────────────────────────────────────
# 픽스처 — 작은 합성 그래프 + 실 코퍼스(2683/2234)
# ──────────────────────────────────────────────────────────────────────
def _atom(code: str, **over: object) -> AtomConcept:
    data: dict[str, object] = {
        "code": code,
        "name": "원자",
        "level": NodeLevel.ATOM,
        "school_level": SchoolLevel.ELEMENTARY,
        "standard_codes": ["[2수01-01]"],
    }
    data.update(over)
    return AtomConcept(**data)  # type: ignore[arg-type]


def _edge(frm: str, to: str, **over: object) -> AtomEdge:
    data: dict[str, object] = {
        "from_code": frm,
        "to_code": to,
        # 명시 전달(검증 경로) → use_enum_values로 dump 시 "prerequisite" 문자열(코퍼스와 동형).
        # 미전달 시 필드 기본값은 검증을 안 거쳐 enum 객체로 dump됨
        # (Pydantic v2 validate_default=False).
        "relation": "prerequisite",
        "relation_subtype": "원본",
        "school_link": False,
        "strength": 0.8,
        "evidence": "원자 백본 v1",
    }
    data.update(over)
    return AtomEdge(**data)  # type: ignore[arg-type]


_A = "2수01-01-1"
_B = "2수01-01-2"


@pytest.fixture
def small_result() -> TransformResult:
    """원자 2(난이도·atomicity 혼합)·엣지 1 합성 그래프."""
    return TransformResult(
        concepts=[
            _atom(_A, intrinsic_difficulty=1, atomicity={"a": "예", "b": "예"}),
            _atom(_B, school_level=SchoolLevel.HIGH),
        ],
        edges=[_edge(_A, _B)],
    )


def _result_from_corpus(corpus_graph: dict[str, object]) -> TransformResult:
    """실 코퍼스 graph.json dict → TransformResult(모델 라운드트립)."""
    concepts = [AtomConcept(**r) for r in corpus_graph["concepts"]]  # type: ignore[union-attr]
    edges = [AtomEdge(**r) for r in corpus_graph["edges"]]  # type: ignore[union-attr]
    narrative = list(corpus_graph.get("narrative_edges_raw", []))  # type: ignore[arg-type]
    return TransformResult(concepts=concepts, edges=edges, narrative_edges_raw=narrative)


def _node_calls(calls: Sequence[_RunCall]) -> list[_RunCall]:
    return [c for c in calls if "MERGE (a:" + NODE_LABEL in c.query]


def _edge_calls(calls: Sequence[_RunCall]) -> list[_RunCall]:
    return [c for c in calls if "MERGE (src)-[r:" in c.query]


def _constraint_calls(calls: Sequence[_RunCall]) -> list[_RunCall]:
    return [c for c in calls if "CREATE CONSTRAINT" in c.query]


# ──────────────────────────────────────────────────────────────────────
# 발행 Cypher 구성
# ──────────────────────────────────────────────────────────────────────
class TestEmittedCypher:
    def test_emits_constraint_before_nodes(self, small_result: TransformResult) -> None:
        """제약 DDL이 노드 MERGE보다 먼저 발행된다."""
        driver = _FakeDriver()
        load_graph(small_result, driver=driver)
        queries = [c.query for c in driver.calls]
        constraint_idx = next(i for i, q in enumerate(queries) if "CREATE CONSTRAINT" in q)
        first_node_idx = next(i for i, q in enumerate(queries) if "MERGE (a:" + NODE_LABEL in q)
        assert constraint_idx < first_node_idx
        cons = _constraint_calls(driver.calls)[0].query
        assert CONSTRAINT_NAME in cons
        assert "IF NOT EXISTS" in cons
        assert "REQUIRE a.code IS UNIQUE" in cons

    def test_node_count_matches(self, small_result: TransformResult) -> None:
        """노드 MERGE 수 = 개념 수(전량)."""
        driver = _FakeDriver()
        report = load_graph(small_result, driver=driver)
        assert len(_node_calls(driver.calls)) == 2
        assert report.nodes_merged == 2

    def test_rejects_cycle_before_any_merge(self) -> None:
        """선수엣지에 순환(A→B→A)이 있으면 Neo4j 적재 직전 거부한다(어떤 MERGE도 발행 안 함)."""
        cyclic = TransformResult(
            concepts=[_atom(_A), _atom(_B)],
            edges=[_edge(_A, _B), _edge(_B, _A)],
        )
        driver = _FakeDriver()
        with pytest.raises(AtomGraphCycleError) as exc_info:
            load_graph(cyclic, driver=driver)
        assert exc_info.value.cycle[0] == exc_info.value.cycle[-1]
        assert driver.calls == []  # cycle 검사가 세션 진입 전이라 어떤 Cypher도 발행되지 않음

    def test_edge_uses_atom_reltype_and_match(self, small_result: TransformResult) -> None:
        """엣지 MERGE는 reltype ATOM_PREREQUISITE·양끝 MATCH를 쓴다(고아 방지·구 그래프와 분리)."""
        driver = _FakeDriver()
        load_graph(small_result, driver=driver)
        edge_calls = _edge_calls(driver.calls)
        assert len(edge_calls) == 1
        q = edge_calls[0].query
        assert "MERGE (src)-[r:ATOM_PREREQUISITE]->(dst)" in q
        assert q.count("MATCH (") == 2  # src·dst 둘 다 MATCH

    def test_node_props_set_school_level_and_level(self, small_result: TransformResult) -> None:
        """노드 props에 school_level·level이 들어간다(운영 인덱스 대상)."""
        driver = _FakeDriver()
        load_graph(small_result, driver=driver)
        levels = {
            call.params["code"]: call.params["props"]["school_level"]
            for call in _node_calls(driver.calls)
        }
        assert levels[_A] == "초등"
        assert levels[_B] == "고등"
        for call in _node_calls(driver.calls):
            assert call.params["props"]["level"] == "세부개념"

    def test_atomicity_serialized_to_json_string(self, small_result: TransformResult) -> None:
        """atomicity dict는 결정론 JSON 문자열로 직렬화된다(Neo4j map 속성 불가). 빈 dict는 생략."""
        driver = _FakeDriver()
        load_graph(small_result, driver=driver)
        props_by_code = {c.params["code"]: c.params["props"] for c in _node_calls(driver.calls)}
        assert props_by_code[_A]["atomicity"] == '{"a": "예", "b": "예"}'
        # _B는 atomicity 기본 빈 dict → props에 키 없음
        assert "atomicity" not in props_by_code[_B]

    def test_code_not_duplicated_in_props(self, small_result: TransformResult) -> None:
        """MERGE 키 code는 props에서 제외(중복 SET 방지)."""
        driver = _FakeDriver()
        load_graph(small_result, driver=driver)
        for call in _node_calls(driver.calls):
            assert "code" not in call.params["props"]
            assert call.params["code"]  # 별도 파라미터로 전달

    def test_edge_props_carry_meta(self, small_result: TransformResult) -> None:
        """엣지 props에 relation_subtype·school_link·strength·evidence가 실린다
        (끝점·relation 제외)."""
        driver = _FakeDriver()
        load_graph(small_result, driver=driver)
        props = _edge_calls(driver.calls)[0].params["props"]
        assert props["relation_subtype"] == "원본"
        assert props["school_link"] is False
        assert props["strength"] == pytest.approx(0.8)
        assert props["evidence"] == "원자 백본 v1"
        assert "from_code" not in props
        assert "relation" not in props

    def test_none_props_omitted(self) -> None:
        """None 속성(name_display 미보유 등)은 props에서 제거(Neo4j null 속성 방지)."""
        driver = _FakeDriver()
        result = TransformResult(concepts=[_atom(_A)], edges=[])
        load_graph(result, driver=driver)
        props = _node_calls(driver.calls)[0].params["props"]
        assert "name_display" not in props  # 합성 원자는 표시명 None
        assert "core_proposition" not in props  # K-12 핵심명제 redact(None)
        assert props["name"] == "원자"


# ──────────────────────────────────────────────────────────────────────
# 멱등성
# ──────────────────────────────────────────────────────────────────────
class TestIdempotency:
    def test_two_loads_emit_identical_cypher(self, small_result: TransformResult) -> None:
        """2회 적재가 *완전히 동일한* Cypher·파라미터를 발행한다(MERGE 멱등)."""
        d1, d2 = _FakeDriver(), _FakeDriver()
        load_graph(small_result, driver=d1)
        load_graph(small_result, driver=d2)
        as_tuples = lambda d: [(c.query, c.params) for c in d.calls]  # noqa: E731
        assert as_tuples(d1) == as_tuples(d2)

    def test_repeated_load_same_node_edge_counts(self, small_result: TransformResult) -> None:
        """같은 드라이버로 2회 적재 — 노드·엣지 MERGE 보고 수가 회당 불변."""
        driver = _FakeDriver()
        r1 = load_graph(small_result, driver=driver)
        r2 = load_graph(small_result, driver=driver)
        assert (r1.nodes_merged, r1.edges_merged) == (2, 1)
        assert (r2.nodes_merged, r2.edges_merged) == (2, 1)


# ──────────────────────────────────────────────────────────────────────
# 시크릿·redaction 불변
# ──────────────────────────────────────────────────────────────────────
class TestNoSecretsNoRedactedFields:
    def test_no_credentials_in_emitted_cypher(self, small_result: TransformResult) -> None:
        """발행 쿼리·파라미터 어디에도 접속 자격·시크릿 흔적이 없다(env 전용)."""
        driver = _FakeDriver()
        load_graph(small_result, driver=driver)
        blob = " ".join(
            [c.query for c in driver.calls] + [repr(c.params) for c in driver.calls]
        ).lower()
        for needle in ("password", "neo4j_password", "bolt://", "auth"):
            assert needle not in blob

    def test_no_body_field_slots_in_props(self, small_result: TransformResult) -> None:
        """본문 슬롯(K-12 핵심명제·정식정의)은 어떤 노드 props에도 없다(구조 차단 불변)."""
        driver = _FakeDriver()
        load_graph(small_result, driver=driver)
        for call in _node_calls(driver.calls):
            assert "core_proposition" not in call.params["props"]
            assert "formal_definition" not in call.params["props"]


# ──────────────────────────────────────────────────────────────────────
# 실 코퍼스(2683/2234) — graph.json 라운드트립 후 적재
# ──────────────────────────────────────────────────────────────────────
class TestRealCorpus:
    def test_loads_2683_nodes_2234_edges(self, corpus_graph: dict[str, object]) -> None:
        """실 코퍼스 적재: 노드 2683·엣지 2234 MERGE·skip 0(전 엣지 ATOM_PREREQUISITE)."""
        result = _result_from_corpus(corpus_graph)
        driver = _FakeDriver()
        report = load_graph(result, driver=driver)
        assert report.nodes_merged == 2683
        assert report.edges_merged == 2234  # 2210 + S4-60 고→대 경계 24
        assert report.edges_skipped == 0
        for call in _edge_calls(driver.calls):
            assert "MERGE (src)-[r:ATOM_PREREQUISITE]->(dst)" in call.query

    def test_real_corpus_node_codes_unique_in_merge(self, corpus_graph: dict[str, object]) -> None:
        """2683 노드 MERGE의 code가 모두 유일(코드 충돌 0)."""
        result = _result_from_corpus(corpus_graph)
        driver = _FakeDriver()
        load_graph(result, driver=driver)
        codes = [c.params["code"] for c in _node_calls(driver.calls)]
        assert len(codes) == len(set(codes)) == 2683

    def test_real_corpus_no_map_props(self, corpus_graph: dict[str, object]) -> None:
        """실 코퍼스 적재 시 어떤 노드 props도 dict(map)를 담지 않는다(Neo4j 속성 규칙)."""
        result = _result_from_corpus(corpus_graph)
        driver = _FakeDriver()
        load_graph(result, driver=driver)
        for call in _node_calls(driver.calls):
            for value in call.params["props"].values():
                assert not isinstance(value, dict)


# ──────────────────────────────────────────────────────────────────────
# 보조 함수·엣지 케이스
# ──────────────────────────────────────────────────────────────────────
class TestHelpers:
    def test_merge_edges_skips_unknown_relation(self) -> None:
        """enum 밖 relation은 skip(주입 차단·고아 방지) — 발행 안 함."""
        driver = _FakeDriver()
        with driver.session() as session:
            merged, skipped = merge_edges(
                session,
                [
                    {
                        "from_code": _A,
                        "to_code": _B,
                        "relation": "; DROP",  # allowlist 밖
                        "strength": 0.5,
                        "evidence": "x",
                    }
                ],
            )
        assert (merged, skipped) == (0, 1)
        assert _edge_calls(driver.calls) == []

    def test_merge_edges_skips_missing_endpoint(self) -> None:
        """끝점(code) 누락 엣지는 skip."""
        driver = _FakeDriver()
        with driver.session() as session:
            merged, skipped = merge_edges(
                session,
                [
                    {
                        "from_code": "",
                        "to_code": _B,
                        "relation": "prerequisite",
                        "strength": 0.5,
                        "evidence": "x",
                    }
                ],
            )
        assert (merged, skipped) == (0, 1)

    def test_merge_nodes_skips_missing_code(self) -> None:
        """code 없는 노드 dict는 skip(방어)."""
        driver = _FakeDriver()
        with driver.session() as session:
            count = merge_nodes(session, [{"name": "이름만"}])
        assert count == 0

    def test_ensure_schema_emits_constraint_and_indexes(self) -> None:
        """ensure_schema가 제약 1·인덱스 2를 발행한다."""
        driver = _FakeDriver()
        with driver.session() as session:
            constraints, indexes = ensure_schema(session)
        assert (constraints, indexes) == (1, 2)
        assert len(_constraint_calls(driver.calls)) == 1
        index_calls = [c for c in driver.calls if "CREATE INDEX" in c.query]
        assert len(index_calls) == 2

    def test_load_graph_passes_database_to_session(self, small_result: TransformResult) -> None:
        """database 인자가 session(database=...)로 전달된다(멀티-DB)."""
        driver = _FakeDriver()
        load_graph(small_result, driver=driver, database="neo4j")
        assert driver.last_session_kwargs == {"database": "neo4j"}

    def test_load_graph_omits_database_when_none(self, small_result: TransformResult) -> None:
        """database None이면 session에 database 키를 넣지 않는다(기본 DB)."""
        driver = _FakeDriver()
        load_graph(small_result, driver=driver)
        assert "database" not in driver.last_session_kwargs


class TestLoadReport:
    def test_summary_mentions_counts(self) -> None:
        report = LoadReport(constraints=1, indexes=2, nodes_merged=2683, edges_merged=2210)
        text = report.summary()
        assert "2683" in text
        assert "2210" in text
