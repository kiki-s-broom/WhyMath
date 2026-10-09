"""원자 백본 Neo4j 적재 통합테스트 — 실 Neo4j 왕복 (기본 SKIP).

`WHYMATH_RUN_INTEGRATION=1` + `[neo4j]` extra + 살아있는 Neo4j에서만 실행한다. CI(data-pipeline
기본 잡 `[dev]`만 — neo4j 드라이버 없음·PG 통합 잡도 neo4j 미설치)는 ① conftest 게이트(env var
미설정) ② `importorskip`로 이중 skip된다. 전용 `data-pipeline-neo4j` 잡(실 neo4j:5)에서만
실제 적재가 돈다. Neo4j 미도달 시에도 graceful skip(concept_graph 통합 선례와 동형).

검증: load_graph가 실 Neo4j에 ① 노드 2683·엣지 2234 적재 ② **멱등**(2회 적재 → 노드·엣지 수
불변) ③ atom_code_unique 유일 제약 존재. 격리를 위해 적재한 `code` 집합만 시작·종료 시 삭제한다
(앱 그래프·구 :Concept 그래프를 건드리지 않음).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("neo4j")  # [neo4j] 미설치(CI data-pipeline 기본·PG 잡)면 모듈 전체 skip

from data_pipeline.atom_graph.load import (  # noqa: E402
    CONSTRAINT_NAME,
    NODE_LABEL,
    load_graph,
)
from data_pipeline.atom_graph.models import AtomConcept, AtomEdge  # noqa: E402
from data_pipeline.atom_graph.transform import TransformResult  # noqa: E402
from neo4j import GraphDatabase  # noqa: E402  (importorskip 뒤에 와야 함)

pytestmark = pytest.mark.integration

# 접속 env — 시크릿 하드코딩 금지. CI/Phaiakes9가 env로 주입(기본값은 로컬 trust 가정).
_URI = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
_USER = os.environ.get("NEO4J_USER", "neo4j")
_PASSWORD = os.environ.get("NEO4J_PASSWORD", "neo4j")

_CORPUS = Path(__file__).resolve().parents[3] / "data" / "corpus" / "atom_graph_v1"


def _driver() -> "GraphDatabase.driver":  # type: ignore[name-defined]
    return GraphDatabase.driver(_URI, auth=(_USER, _PASSWORD))


def _reachable() -> bool:
    try:
        driver = _driver()
    except Exception:
        return False
    try:
        with driver.session() as session:
            session.run("RETURN 1").single()
        return True
    except Exception:
        return False
    finally:
        try:
            driver.close()
        except Exception:
            pass


def _result_from_corpus() -> TransformResult:
    """실 코퍼스 graph.json → TransformResult(AtomConcept·AtomEdge 라운드트립)."""
    payload = json.loads((_CORPUS / "graph.json").read_text(encoding="utf-8"))
    concepts = [AtomConcept(**r) for r in payload.get("concepts", [])]
    edges = [AtomEdge(**r) for r in payload.get("edges", [])]
    return TransformResult(concepts=concepts, edges=edges)


def _count_loaded(driver: "GraphDatabase.driver", codes: set[str]) -> tuple[int, int]:  # type: ignore[name-defined]
    """적재한 code 집합에 한정해 노드·엣지 수를 센다(앱 그래프·구 :Concept 격리)."""
    with driver.session() as session:
        node_rec = session.run(
            f"MATCH (a:{NODE_LABEL}) WHERE a.code IN $codes RETURN count(a) AS n",
            codes=list(codes),
        ).single()
        edge_rec = session.run(
            f"MATCH (a:{NODE_LABEL})-[r:ATOM_PREREQUISITE]->(b:{NODE_LABEL}) "
            "WHERE a.code IN $codes AND b.code IN $codes "
            "RETURN count(r) AS n",
            codes=list(codes),
        ).single()
    nodes = 0 if node_rec is None else int(node_rec["n"])
    edges = 0 if edge_rec is None else int(edge_rec["n"])
    return nodes, edges


def _cleanup(driver: "GraphDatabase.driver", codes: set[str]) -> None:  # type: ignore[name-defined]
    """적재한 code 노드(+관계)만 삭제(앱 그래프 무영향)."""
    with driver.session() as session:
        session.run(
            f"MATCH (a:{NODE_LABEL}) WHERE a.code IN $codes DETACH DELETE a",
            codes=list(codes),
        )


def _constraint_exists(driver: "GraphDatabase.driver") -> bool:  # type: ignore[name-defined]
    with driver.session() as session:
        rows = session.run("SHOW CONSTRAINTS").data()
    return any(row.get("name") == CONSTRAINT_NAME for row in rows)


def test_load_is_idempotent_on_live_neo4j() -> None:
    """실 Neo4j: 2회 적재 → 노드 2683·엣지 2234 불변(멱등) + atom_code_unique 제약 존재."""
    if not _reachable():
        pytest.skip("Neo4j 미도달 — 통합 테스트 건너뜀 (NEO4J_URI/USER/PASSWORD 확인)")

    result = _result_from_corpus()
    codes = {c.code for c in result.concepts}
    driver = _driver()
    try:
        _cleanup(driver, codes)  # 이전 잔여 제거(재현성)

        # 1회차 적재
        r1 = load_graph(result, driver=driver)
        assert r1.nodes_merged == 2683
        assert r1.edges_merged == 2234
        assert r1.edges_skipped == 0
        n1, e1 = _count_loaded(driver, codes)
        assert (n1, e1) == (2683, 2234)

        # 제약 존재
        assert _constraint_exists(driver)

        # 2회차 적재 — 멱등(MERGE): 노드·엣지 수 불변
        load_graph(result, driver=driver)
        n2, e2 = _count_loaded(driver, codes)
        assert (n2, e2) == (2683, 2234), "재적재 후 노드·엣지 수가 변했다(멱등성 위반)"
    finally:
        _cleanup(driver, codes)
        driver.close()
