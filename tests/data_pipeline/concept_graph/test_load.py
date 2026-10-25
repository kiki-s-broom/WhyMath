"""concept_graph Neo4j 적재 단위테스트 — FAKE 드라이버 주입(실 Neo4j 불요).

정본: docs/data/concept_graph.md §2.3(DDL)·§4 단계7(멱등 MERGE)·§5 #9(멱등 invariant).
실 Neo4j 왕복은 test_load_neo4j_integration.py(통합·기본 SKIP)에서 한다. 여기서는 발행 Cypher가
① CONSTRAINT ② 노드 MERGE(403) ③ 엣지 MERGE(541)를 포함하고, 멱등(2회=동일)이며, review_status를
SET하고, 어디에도 시크릿이 없음을 *주입 FAKE*로 검증한다. ncic의 mock 분담과 같은 철학.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from data_pipeline.concept_graph.load import (
    CONSTRAINT_NAME,
    NODE_LABEL,
    LoadReport,
    ensure_schema,
    load_graph,
    merge_edges,
    merge_nodes,
)
from data_pipeline.concept_graph.models import Concept, ConceptEdge
from data_pipeline.concept_graph.transform import TransformResult, transform_dataset

_REPO_ROOT = Path(__file__).resolve().parents[3]
# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
# 고정 지점이 사실 파일 한 곳이다 — 값이 바뀌면 그 파일의 diff가 의식적 리뷰 지점이다.
_FACTS = json.loads(
    (_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
)


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
# 픽스처 — 작은 합성 그래프 + 실데이터(403/541)
# ──────────────────────────────────────────────────────────────────────
def _concept(concept_id: str, **over: object) -> Concept:
    data: dict[str, object] = {
        "concept_id": concept_id,
        "source_id": concept_id,  # 적재 테스트는 추적성 무관 — 자기 정체로 충족
        "domain": "미적분",  # 표시이름(name_ko)은 노드 비내장(P2d) — locale 레이어 소관
        "standard_codes": ["[12미적Ⅰ01-01]"],
    }
    data.update(over)
    return Concept(**data)  # type: ignore[arg-type]


def _edge(src: str, dst: str, **over: object) -> ConceptEdge:
    data: dict[str, object] = {
        "src_concept_id": src,
        "dst_concept_id": dst,
        "relation": "prerequisite",
        "strength": 0.8,
        "evidence": "근거",
        "evidence_source": "ncic",
    }
    data.update(over)
    return ConceptEdge(**data)  # type: ignore[arg-type]


_A = "math.calculus.hamsuui-geukhan"
_B = "math.calculus.dohamsu"


@pytest.fixture
def small_result() -> TransformResult:
    """노드 2·엣지 1(pending 1·reviewed 1 혼합) 합성 그래프."""
    return TransformResult(
        concepts=[
            _concept(_A, review_status="reviewed"),
            _concept(_B, review_status="pending"),
        ],
        edges=[_edge(_A, _B)],
    )


def _node_calls(calls: Sequence[_RunCall]) -> list[_RunCall]:
    return [c for c in calls if "MERGE (c:" + NODE_LABEL in c.query]


def _edge_calls(calls: Sequence[_RunCall]) -> list[_RunCall]:
    return [c for c in calls if "MERGE (src)-[r:" in c.query]


def _constraint_calls(calls: Sequence[_RunCall]) -> list[_RunCall]:
    return [c for c in calls if "CREATE CONSTRAINT" in c.query]


# ──────────────────────────────────────────────────────────────────────
# 발행 Cypher 구성
# ──────────────────────────────────────────────────────────────────────
class TestEmittedCypher:
    def test_emits_constraint_before_nodes(self, small_result: TransformResult) -> None:
        """제약 DDL이 노드 MERGE보다 먼저 발행된다(§2.3)."""
        driver = _FakeDriver()
        load_graph(small_result, driver=driver)
        queries = [c.query for c in driver.calls]
        constraint_idx = next(i for i, q in enumerate(queries) if "CREATE CONSTRAINT" in q)
        first_node_idx = next(i for i, q in enumerate(queries) if "MERGE (c:" + NODE_LABEL in q)
        assert constraint_idx < first_node_idx
        # 제약명·유일성 조건이 §2.3 DDL과 일치
        cons = _constraint_calls(driver.calls)[0].query
        assert CONSTRAINT_NAME in cons
        assert "IF NOT EXISTS" in cons
        assert "REQUIRE c.concept_id IS UNIQUE" in cons

    def test_node_count_matches(self, small_result: TransformResult) -> None:
        """노드 MERGE 수 = 개념 수(전량 — pending 포함)."""
        driver = _FakeDriver()
        report = load_graph(small_result, driver=driver)
        assert len(_node_calls(driver.calls)) == 2
        assert report.nodes_merged == 2

    def test_edge_uses_reltype_and_match(self, small_result: TransformResult) -> None:
        """엣지 MERGE는 reltype PREREQUISITE·양끝 MATCH를 쓴다(고아 방지)."""
        driver = _FakeDriver()
        load_graph(small_result, driver=driver)
        edge_calls = _edge_calls(driver.calls)
        assert len(edge_calls) == 1
        q = edge_calls[0].query
        assert "MERGE (src)-[r:PREREQUISITE]->(dst)" in q
        assert q.count("MATCH (") == 2  # src·dst 둘 다 MATCH

    def test_node_props_set_review_status(self, small_result: TransformResult) -> None:
        """노드 props에 review_status가 들어간다(pending도 적재·플래그 표식)."""
        driver = _FakeDriver()
        load_graph(small_result, driver=driver)
        statuses = {
            call.params["concept_id"]: call.params["props"]["review_status"]
            for call in _node_calls(driver.calls)
        }
        assert statuses[_A] == "reviewed"
        assert statuses[_B] == "pending"

    def test_concept_id_not_duplicated_in_props(self, small_result: TransformResult) -> None:
        """MERGE 키 concept_id는 props에서 제외(중복 SET 방지)."""
        driver = _FakeDriver()
        load_graph(small_result, driver=driver)
        for call in _node_calls(driver.calls):
            assert "concept_id" not in call.params["props"]
            assert call.params["concept_id"]  # 별도 파라미터로 전달

    def test_edge_props_carry_strength_evidence(self, small_result: TransformResult) -> None:
        """엣지 props에 strength·evidence·evidence_source가 실린다(끝점·relation은 제외)."""
        driver = _FakeDriver()
        load_graph(small_result, driver=driver)
        props = _edge_calls(driver.calls)[0].params["props"]
        assert props["strength"] == pytest.approx(0.8)
        assert props["evidence"] == "근거"
        assert props["evidence_source"] == "ncic"
        assert "src_concept_id" not in props
        assert "relation" not in props

    def test_none_props_omitted(self) -> None:
        """None 속성(ccss_code·grade_band_hint 미보유 등)은 props에서 제거(Neo4j null 속성 방지)."""
        driver = _FakeDriver()
        result = TransformResult(concepts=[_concept(_A)], edges=[])
        load_graph(result, driver=driver)
        props = _node_calls(driver.calls)[0].params["props"]
        # 미설정 Optional(ccss_code·grade_band_hint) → props에 없어야 함
        assert "ccss_code" not in props
        assert "grade_band_hint" not in props
        assert props["domain"] == "미적분"


# ──────────────────────────────────────────────────────────────────────
# 멱등성(§5 #9)
# ──────────────────────────────────────────────────────────────────────
class TestIdempotency:
    def test_two_loads_emit_identical_cypher(self, small_result: TransformResult) -> None:
        """2회 적재가 *완전히 동일한* Cypher·파라미터를 발행한다(MERGE 멱등 — §5 #9)."""
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
        # MERGE라 같은 쿼리가 반복 발행돼도(드라이버 레벨) Neo4j 결과는 멱등(통합테스트가 단언)


# ──────────────────────────────────────────────────────────────────────
# 시크릿·redaction
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

    def test_no_redacted_body_fields_in_props(self, small_result: TransformResult) -> None:
        """description·formal_definition은 어떤 노드 props에도 없다(redaction 불변)."""
        driver = _FakeDriver()
        load_graph(small_result, driver=driver)
        for call in _node_calls(driver.calls):
            assert "description" not in call.params["props"]
            assert "formal_definition" not in call.params["props"]


# ──────────────────────────────────────────────────────────────────────
# 실데이터(403/541) — 정형화 산출을 그대로 적재
# ──────────────────────────────────────────────────────────────────────
class TestRealCorpus:
    def test_loads_all_nodes_and_edges(
        self,
        concept_records: list[dict[str, object]],
        edge_records: list[dict[str, object]],
    ) -> None:
        """실데이터 정형화 → 적재: 전 노드·전 엣지 MERGE(전 엣지 prerequisite · 건수는 사실 파일)."""
        result = transform_dataset(
            concept_records=concept_records,
            edge_records=edge_records,
        )
        driver = _FakeDriver()
        report = load_graph(result, driver=driver)
        assert report.nodes_merged == _FACTS["concept_graph.concepts"]
        assert report.edges_merged == _FACTS["concept_graph.edges"]
        assert report.edges_skipped == 0
        # 모든 엣지 reltype은 PREREQUISITE(데이터셋 단일 관계)
        for call in _edge_calls(driver.calls):
            assert "MERGE (src)-[r:PREREQUISITE]->(dst)" in call.query

    def test_real_corpus_node_ids_unique_in_merge(
        self,
        concept_records: list[dict[str, object]],
        edge_records: list[dict[str, object]],
    ) -> None:
        """전 노드 MERGE의 concept_id가 모두 유일(concept_id 매핑 충돌 0 — 슬1 보장)."""
        result = transform_dataset(concept_records=concept_records, edge_records=edge_records)
        driver = _FakeDriver()
        load_graph(result, driver=driver)
        ids = [c.params["concept_id"] for c in _node_calls(driver.calls)]
        assert len(ids) == len(set(ids)) == _FACTS["concept_graph.concepts"]


# ──────────────────────────────────────────────────────────────────────
# 보조 함수·엣지 케이스
# ──────────────────────────────────────────────────────────────────────
class TestHelpers:
    def test_merge_edges_skips_unknown_relation(self) -> None:
        """enum 밖 relation은 skip(주입 차단·고아 방지) — 발행 안 함."""
        driver = _FakeDriver()
        with driver.session() as session:
            # dump 형태의 dict를 직접 넘긴다(모델 우회 — 방어 경로 검증)
            merged, skipped = merge_edges(
                session,
                [
                    {
                        "src_concept_id": _A,
                        "dst_concept_id": _B,
                        "relation": "; DROP",  # allowlist 밖
                        "strength": 0.5,
                        "evidence": "x",
                        "evidence_source": "ncic",
                    }
                ],
            )
        assert (merged, skipped) == (0, 1)
        assert _edge_calls(driver.calls) == []

    def test_merge_edges_skips_missing_endpoint(self) -> None:
        """끝점(concept_id) 누락 엣지는 skip."""
        driver = _FakeDriver()
        with driver.session() as session:
            merged, skipped = merge_edges(
                session,
                [
                    {
                        "src_concept_id": "",
                        "dst_concept_id": _B,
                        "relation": "prerequisite",
                        "strength": 0.5,
                        "evidence": "x",
                        "evidence_source": "ncic",
                    }
                ],
            )
        assert (merged, skipped) == (0, 1)

    def test_merge_nodes_skips_missing_concept_id(self) -> None:
        """concept_id 없는 노드 dict는 skip(방어)."""
        driver = _FakeDriver()
        with driver.session() as session:
            count = merge_nodes(session, [{"name_ko": "이름만"}])
        assert count == 0

    def test_ensure_schema_emits_constraint_and_indexes(self) -> None:
        """ensure_schema가 제약 1·인덱스 2를 발행한다(§2.3)."""
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
        report = LoadReport(constraints=1, indexes=2, nodes_merged=403, edges_merged=541)
        text = report.summary()
        assert "403" in text
        assert "541" in text
