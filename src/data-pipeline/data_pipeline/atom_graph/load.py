"""원자 백본 그래프 → Neo4j 멱등 적재(Phase 2c).

정본: docs/data/atom_graph_v1.md(스키마·§3 redaction·§6 Phase 2 파생 스토어) + MEMORY.md
"원자 백본 전면 교체 마이그레이션" 결정 로그. `concept_graph/load.py`(개념 그래프 Neo4j 적재)의
*지연 import + env 접속 + 멱등 MERGE + 드라이버 주입* 패턴을 원자 백본으로 미러링한다.

additive 원칙(MEMORY 결정 로그·태스크 지시): 구 437 개념 그래프(`:Concept`/`concept_id`/
`:PREREQUISITE`)와 *노드·엣지 라벨 모두 충돌하지 않게* 적재한다 — 원자 백본은 별도 노드 라벨
`:Atom`(MERGE 키 `code`)·별도 관계 타입 `:ATOM_PREREQUISITE`를 쓴다(Phase 5 구 폐기까지 병존).

설계 핵심
---------
1. **지연 import**: `neo4j` 드라이버는 `[neo4j]` extra라 이 모듈은 *extra 없이도 import 가능*해야
   한다(단위테스트·CLI 사전체크). `neo4j` import는 `connect_driver` 안에서만 한다.
2. **드라이버 주입**: `load_graph(...)`는 `driver` 인자를 받는다 — 단위테스트가 FAKE 드라이버를
   주입해 *실 Neo4j 없이* 발행 Cypher를 검증한다(미설치 환경에서도 import·테스트 가능).
3. **멱등**: 노드는 `MERGE (a:Atom {code}) SET a += $props`, 엣지는 양끝 `MATCH` 후
   `MERGE (src)-[r:TYPE]->(dst) SET r += $props`. 재실행해도 노드·엣지 수 불변.
4. **제약**: `CREATE CONSTRAINT atom_code_unique IF NOT EXISTS`(멱등 DDL)를 적재 전 보장.
5. **reltype 안전**: Cypher 관계 타입은 파라미터화 불가 → 닫힌 `AtomRelation` enum allowlist에서만
   reltype을 끌어온다(임의 문자열 주입 불가). 값은 enum 검증을 거친 것만 들어온다.
6. **계층은 노드 속성**: `parent_code`(원자→소단원→단원 3단)는 노드 속성으로만 보존한다 — 별도 계층
   관계는 만들지 않는다(엣지는 prerequisite 전량뿐 — 결정 로그(작성 당시)의 "엣지 2,213"과
   일치했다·계층은 Phase 3+). `narrative_edges_raw`(서술형 엣지 — 건수는
   `docs/data/corpus_facts.md`의 `atom_graph.narrative_edges_raw`)는 FK 불가라 적재 대상이
   아니다(패스스루 — concept_graph가 flashcards/intl raw를 적재하지 않는 것과 동형).

법적·redaction(CLAUDE.md·atom_graph_v1.md §3): `graph.json`은 transform에서 이미 청결하다
(AtomConcept에 K-12 핵심명제 본문 슬롯 부재 — 구조 차단). 이 로더는 모델 dump 키만 적재하므로
본문이 *구조적으로* 재유입될 수 없다. 시크릿 0 — 접속 자격은 env(`NEO4J_URI`·`NEO4J_USER`·
`NEO4J_PASSWORD`) 전용·하드코딩 금지.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from data_pipeline.atom_graph.models import AtomRelation
from data_pipeline.atom_graph.transform import TransformResult
from data_pipeline.atom_graph.validate import _find_prerequisite_cycle

logger = logging.getLogger("data_pipeline.atom_graph.load")


class AtomGraphCycleError(ValueError):
    """선수엣지에 순환이 있어 Neo4j 적재를 거부할 때 — 학습 경로 구성 불가(DAG 불변식).

    `load` CLI 경로는 graph.json을 신뢰해 validate를 재호출하지 않으므로(transform-v1에서 이미
    통과한 산출물 가정), 적재 직전 여기서 한 번 더 막는다 — 손수 편집되거나 옛 graph.json이
    재적재될 때 cycle 유입을 차단한다(math_dsl_risk_register.md Q10-②).
    """

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        super().__init__("순환 선수관계로 Neo4j 적재 거부: " + " → ".join(cycle))


# Neo4j 접속 env 키. 시크릿은 코드에 두지 않고 *전적으로* env에서 읽는다(CLAUDE.md 보안).
ENV_URI = "NEO4J_URI"
ENV_USER = "NEO4J_USER"
ENV_PASSWORD = "NEO4J_PASSWORD"

# 노드 라벨·제약명 — 구 개념 그래프(:Concept/concept_id_unique)와 충돌 회피(additive).
# 제약명을 상수로 고정해 통합테스트가 존재를 단언한다.
NODE_LABEL = "Atom"
CONSTRAINT_NAME = "atom_code_unique"

# 제약 DDL — IF NOT EXISTS라 재실행 멱등. MERGE 키 `code`의 유일성을 보장한다.
CONSTRAINT_CYPHER = (
    f"CREATE CONSTRAINT {CONSTRAINT_NAME} IF NOT EXISTS "
    f"FOR (a:{NODE_LABEL}) REQUIRE a.code IS UNIQUE"
)

# 조회 인덱스 — 운영 조회용(학교급 필터·계층 레벨 필터). 멱등 DDL. 구 인덱스명과 무충돌.
INDEX_CYPHERS: tuple[str, ...] = (
    f"CREATE INDEX atom_school_level IF NOT EXISTS FOR (a:{NODE_LABEL}) ON (a.school_level)",
    f"CREATE INDEX atom_level IF NOT EXISTS FOR (a:{NODE_LABEL}) ON (a.level)",
)

# 노드 멱등 upsert — code로 MERGE 후 나머지 속성 일괄 SET(`+=` 병합).
NODE_MERGE_CYPHER = f"MERGE (a:{NODE_LABEL} {{code: $code}})\n" "SET a += $props"

# 관계 reltype은 파라미터화 불가 → enum allowlist에서만 포맷(주입 차단). 끝점은 MATCH(없으면 미생성)
# — 노드를 먼저 전량 적재하므로 정상 경로에선 양끝이 항상 존재한다.
_EDGE_MERGE_TEMPLATE = (
    f"MATCH (src:{NODE_LABEL} {{code: $src}})\n"
    f"MATCH (dst:{NODE_LABEL} {{code: $dst}})\n"
    "MERGE (src)-[r:%s]->(dst)\n"
    "SET r += $props"
)

# enum 검증을 통과한 relation 값 → Cypher reltype(닫힌 집합·주입 불가). 구 :PREREQUISITE와 분리하기
# 위해 `ATOM_` 네임스페이스를 붙인다(reltype 토큰까지 완전 분리 — additive).
_RELTYPE_BY_RELATION: dict[str, str] = {
    AtomRelation.PREREQUISITE.value: "ATOM_PREREQUISITE",
}

# 노드 속성으로 적재하지 않는 키(code는 MERGE 키라 props에서 제외 — 중복 SET 방지).
_NODE_MERGE_KEY = "code"

# 엣지 속성으로 적재하지 않는 키(끝점·relation은 MATCH/reltype에 쓰고 r 속성엔 넣지 않음).
_EDGE_NON_PROP_KEYS: frozenset[str] = frozenset({"from_code", "to_code", "relation"})


@runtime_checkable
class _Result(Protocol):
    """neo4j Result 최소 인터페이스(주입 FAKE도 만족하도록 좁게)."""

    def single(self) -> Any: ...


@runtime_checkable
class _Session(Protocol):
    """neo4j Session 최소 인터페이스 — `run` + context manager."""

    def run(self, query: str, **parameters: Any) -> _Result: ...

    def __enter__(self) -> _Session: ...

    def __exit__(self, *exc: object) -> Any: ...


@runtime_checkable
class _Driver(Protocol):
    """neo4j Driver 최소 인터페이스 — `session` + `close`."""

    def session(self, **kwargs: Any) -> _Session: ...

    def close(self) -> None: ...


@dataclass(slots=True)
class LoadReport:
    """Neo4j 적재 결과 요약(멱등 — 재실행해도 같은 수)."""

    constraints: int = 0
    indexes: int = 0
    nodes_merged: int = 0
    edges_merged: int = 0
    edges_skipped: int = 0

    def summary(self) -> str:
        """사람 가독 요약."""
        return (
            f"Neo4j 원자 적재: 제약 {self.constraints}·인덱스 {self.indexes}, "
            f"노드 MERGE {self.nodes_merged}개, 엣지 MERGE {self.edges_merged}개"
            + (f", 엣지 skip {self.edges_skipped}건" if self.edges_skipped else "")
        )


def _node_props(concept: Mapping[str, Any]) -> dict[str, Any]:
    """AtomConcept dump → Neo4j 노드 속성(MERGE 키 code 제외, None·빈 dict 제거).

    Neo4j 속성은 primitive 또는 *동질 primitive 배열*만 허용한다 — map(dict)은 저장 불가다.
    AtomConcept의 `atomicity`(a~d dict)는 결정론 JSON 문자열로 직렬화한다(원자성은 graph.json·
    Postgres atom_node가 구조 진실 원천 — Neo4j엔 직렬화 보존). 리스트(standard_codes 등)는
    동질 문자열 배열이라 그대로 둔다. None은 빼서 Neo4j null 속성을 만들지 않는다.
    """
    props: dict[str, Any] = {}
    for key, value in concept.items():
        if key == _NODE_MERGE_KEY or value is None:
            continue
        if isinstance(value, dict):
            if not value:
                continue  # 빈 dict(계층 노드 atomicity={})는 생략
            props[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            props[key] = value
    return props


def _edge_props(edge: Mapping[str, Any]) -> dict[str, Any]:
    """AtomEdge dump → Neo4j 관계 속성(끝점·relation 제외). from_name·to_name·relation_subtype·
    school_link·strength·evidence. None은 제거(예: relation_subtype 미보유)."""
    return {
        key: value
        for key, value in edge.items()
        if key not in _EDGE_NON_PROP_KEYS and value is not None
    }


def _edge_cypher(relation: str) -> str | None:
    """relation 값 → 엣지 MERGE Cypher(닫힌 enum allowlist). 미지원 값은 None(주입 차단)."""
    reltype = _RELTYPE_BY_RELATION.get(relation)
    if reltype is None:
        return None
    return _EDGE_MERGE_TEMPLATE % reltype


def ensure_schema(session: _Session) -> tuple[int, int]:
    """제약·인덱스 DDL 보장 — 멱등(IF NOT EXISTS). (제약수, 인덱스수) 반환."""
    session.run(CONSTRAINT_CYPHER)
    for index_cypher in INDEX_CYPHERS:
        session.run(index_cypher)
    return 1, len(INDEX_CYPHERS)


def merge_nodes(session: _Session, concepts: Sequence[Mapping[str, Any]]) -> int:
    """원자·계층 노드를 멱등 MERGE(전량). code 키로 upsert·나머지 속성 SET. 적재 수 반환."""
    count = 0
    for concept in concepts:
        code = concept.get(_NODE_MERGE_KEY)
        if not code:
            logger.warning("code 없는 노드 skip: %r", concept)
            continue
        session.run(
            NODE_MERGE_CYPHER,
            code=code,
            props=_node_props(concept),
        )
        count += 1
    return count


def merge_edges(session: _Session, edges: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    """선수 엣지를 관계로 멱등 MERGE(양끝 MATCH 후). (적재수, skip수) 반환.

    relation이 enum allowlist 밖이거나 끝점 누락이면 skip(주입 차단·고아 방지). 정상 경로(노드 전량
    선적재)에선 끝점이 항상 존재한다.
    """
    merged = 0
    skipped = 0
    for edge in edges:
        relation = str(edge.get("relation", ""))
        src = edge.get("from_code")
        dst = edge.get("to_code")
        cypher = _edge_cypher(relation)
        if cypher is None or not src or not dst:
            logger.warning("엣지 skip(relation/끝점): %r", edge)
            skipped += 1
            continue
        session.run(cypher, src=src, dst=dst, props=_edge_props(edge))
        merged += 1
    return merged, skipped


def connect_driver(
    *,
    uri: str | None = None,
    user: str | None = None,
    password: str | None = None,
) -> _Driver:
    """env(또는 인자)로 Neo4j 드라이버 생성 — `[neo4j]` extra 필요(지연 import).

    인자 미지정 시 env(`NEO4J_URI`·`NEO4J_USER`·`NEO4J_PASSWORD`)에서 읽는다. 시크릿은 코드에 두지
    않는다(CLAUDE.md 보안). 드라이버 미설치 시 RuntimeError로 extra 설치를 안내한다.

    Raises:
        RuntimeError: `[neo4j]` extra 미설치 시.
        ValueError: 접속 env(URI·USER·PASSWORD) 누락 시.
    """
    resolved_uri = uri or os.environ.get(ENV_URI)
    resolved_user = user or os.environ.get(ENV_USER)
    resolved_password = password or os.environ.get(ENV_PASSWORD)
    missing = [
        name
        for name, value in (
            (ENV_URI, resolved_uri),
            (ENV_USER, resolved_user),
            (ENV_PASSWORD, resolved_password),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            "Neo4j 접속 정보 누락: " + ", ".join(missing) + " — "
            "env로 설정하세요(시크릿 하드코딩 금지). "
            "예: export NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=…"
        )
    try:
        from neo4j import GraphDatabase
    except ModuleNotFoundError as exc:  # pragma: no cover - 환경 안내 경로
        raise RuntimeError(
            "Neo4j 적재에는 [neo4j] extra가 필요합니다 — "
            "`pip install -e '.[neo4j]'` 후 재시도하세요."
        ) from exc

    # missing 체크로 셋 다 non-None 보장(타입 좁히기 — 드라이버 시그니처 유무와 무관히 안전).
    assert resolved_uri is not None and resolved_user is not None and resolved_password is not None
    driver: _Driver = GraphDatabase.driver(
        resolved_uri,
        auth=(resolved_user, resolved_password),
    )
    return driver


def load_graph(
    result: TransformResult,
    *,
    driver: _Driver,
    database: str | None = None,
) -> LoadReport:
    """정형화 산출(원자·계층 노드·선수 엣지) → Neo4j 멱등 적재(Phase 2c). 드라이버는 호출자가 주입.

    순서: ① 제약·인덱스 DDL ② 노드 전량 MERGE(원자+단원+소단원) ③ 엣지 MERGE(양끝 MATCH 후).
    모두 MERGE라 재실행해도 노드·엣지 수 불변. narrative_edges_raw는 그래프 적재 대상이 아니다
    (서술형·FK 불가 — 패스스루로만 보존).

    Args:
        result: transform_dataset 산출(`concepts`·`edges`).
        driver: neo4j 드라이버(또는 호환 FAKE). 생명주기는 호출자 책임(여기서 close 안 함).
        database: 대상 DB명(멀티-DB 환경). None이면 기본 DB.

    Returns:
        적재 결과 요약(LoadReport).
    """
    # 적재 전 cycle 방어선(DAG 불변식·hard fail). load CLI는 validate를 재호출하지 않으므로
    # (transform-v1 산출 신뢰) 여기서 한 번 더 막는다 — validate의 동일 탐지기를 재사용한다.
    cycle = _find_prerequisite_cycle(result.edges)
    if cycle is not None:
        raise AtomGraphCycleError(cycle)

    concept_dumps = [c.model_dump() for c in result.concepts]
    edge_dumps = [e.model_dump() for e in result.edges]

    session_kwargs: dict[str, Any] = {}
    if database is not None:
        session_kwargs["database"] = database

    with driver.session(**session_kwargs) as session:
        constraints, indexes = ensure_schema(session)
        nodes = merge_nodes(session, concept_dumps)
        edges, skipped = merge_edges(session, edge_dumps)

    report = LoadReport(
        constraints=constraints,
        indexes=indexes,
        nodes_merged=nodes,
        edges_merged=edges,
        edges_skipped=skipped,
    )
    logger.info(report.summary())
    return report


__all__ = [
    "CONSTRAINT_CYPHER",
    "CONSTRAINT_NAME",
    "AtomGraphCycleError",
    "ENV_PASSWORD",
    "ENV_URI",
    "ENV_USER",
    "INDEX_CYPHERS",
    "LoadReport",
    "NODE_LABEL",
    "NODE_MERGE_CYPHER",
    "connect_driver",
    "ensure_schema",
    "load_graph",
    "merge_edges",
    "merge_nodes",
]
