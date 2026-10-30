"""concept_graph Neo4j 적재 통합테스트 — 실 Neo4j 왕복 (기본 SKIP).

`WHYMATH_RUN_INTEGRATION=1` + `[neo4j]` extra + 살아있는 Neo4j에서만 실행한다. CI(data-pipeline
`[dev]`만 — neo4j 드라이버 없음)는 ① conftest 게이트(env var 미설정) ② `importorskip`로 이중
skip된다. Neo4j 미도달 시에도 graceful skip(ncic PG 선례와 동형).

검증: load_graph가 실 Neo4j에 ① 노드 437·엣지 581 적재 ② **멱등**(2회 적재 → 노드·엣지 수 불변·
§5 #9) ③ concept_id 유일 제약(§2.3) 존재. 격리를 위해 *전용 테스트 DB가 아닌 라벨 정리*로
시작·종료 시 적재분을 지운다(앱 그래프를 건드리지 않도록 적재 concept_id 집합만 삭제).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("neo4j")  # [neo4j] 미설치(CI data-pipeline)면 모듈 전체 skip

from data_pipeline.concept_graph.load import (  # noqa: E402
    CONSTRAINT_NAME,
    NODE_LABEL,
    load_graph,
)
from data_pipeline.concept_graph.transform import transform_dataset  # noqa: E402
from neo4j import GraphDatabase  # noqa: E402  (importorskip 뒤에 와야 함)

pytestmark = pytest.mark.integration

# 접속 env(§6.1) — 시크릿 하드코딩 금지. CI/Phaiakes9가 env로 주입(기본값은 로컬 trust 가정).
_URI = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
_USER = os.environ.get("NEO4J_USER", "neo4j")
_PASSWORD = os.environ.get("NEO4J_PASSWORD", "neo4j")

_REPO_ROOT = Path(__file__).resolve().parents[3]
# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
# 고정 지점이 사실 파일 한 곳이다 — 값이 바뀌면 그 파일의 diff가 의식적 리뷰 지점이다.
_FACTS = json.loads(
    (_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
)
_CORPUS = _REPO_ROOT / "data" / "corpus" / "concept_graph_v1"
_NODES = _FACTS["concept_graph.concepts"]
_EDGES = _FACTS["concept_graph.edges"]


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


def _read_jsonl(name: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line in (_CORPUS / name).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            records.append(json.loads(stripped))
    return records


def _count_loaded(driver: "GraphDatabase.driver", ids: set[str]) -> tuple[int, int]:  # type: ignore[name-defined]
    """적재한 concept_id 집합에 한정해 노드·엣지 수를 센다(앱 그래프 격리)."""
    with driver.session() as session:
        node_rec = session.run(
            f"MATCH (c:{NODE_LABEL}) WHERE c.concept_id IN $ids RETURN count(c) AS n",
            ids=list(ids),
        ).single()
        edge_rec = session.run(
            f"MATCH (a:{NODE_LABEL})-[r]->(b:{NODE_LABEL}) "
            "WHERE a.concept_id IN $ids AND b.concept_id IN $ids "
            "RETURN count(r) AS n",
            ids=list(ids),
        ).single()
    nodes = 0 if node_rec is None else int(node_rec["n"])
    edges = 0 if edge_rec is None else int(edge_rec["n"])
    return nodes, edges


def _cleanup(driver: "GraphDatabase.driver", ids: set[str]) -> None:  # type: ignore[name-defined]
    """적재한 concept_id 노드(+관계)만 삭제(앱 그래프 무영향)."""
    with driver.session() as session:
        session.run(
            f"MATCH (c:{NODE_LABEL}) WHERE c.concept_id IN $ids DETACH DELETE c",
            ids=list(ids),
        )


def _constraint_exists(driver: "GraphDatabase.driver") -> bool:  # type: ignore[name-defined]
    with driver.session() as session:
        rows = session.run("SHOW CONSTRAINTS").data()
    return any(row.get("name") == CONSTRAINT_NAME for row in rows)


def test_load_is_idempotent_on_live_neo4j() -> None:
    """실 Neo4j: 2회 적재 → 전 노드·전 엣지 불변(§5 #9 · 건수는 사실 파일) + 제약 존재."""
    if not _reachable():
        pytest.skip("Neo4j 미도달 — 통합 테스트 건너뜀 (NEO4J_URI/USER/PASSWORD 확인)")

    result = transform_dataset(
        concept_records=_read_jsonl("concepts.jsonl"),
        edge_records=_read_jsonl("prerequisite_edges.jsonl"),
    )
    ids = {c.concept_id for c in result.concepts}
    driver = _driver()
    try:
        _cleanup(driver, ids)  # 이전 잔여 제거(재현성)

        # 1회차 적재
        r1 = load_graph(result, driver=driver)
        assert r1.nodes_merged == _NODES
        assert r1.edges_merged == _EDGES
        n1, e1 = _count_loaded(driver, ids)
        assert (n1, e1) == (_NODES, _EDGES)

        # 제약(§2.3) 존재
        assert _constraint_exists(driver)

        # 2회차 적재 — 멱등(MERGE): 노드·엣지 수 불변
        load_graph(result, driver=driver)
        n2, e2 = _count_loaded(driver, ids)
        assert (n2, e2) == (_NODES, _EDGES), "재적재 후 노드·엣지 수가 변했다(멱등성 위반)"
    finally:
        _cleanup(driver, ids)
        driver.close()
