"""개념 임베딩+메타+런타임엔티티 영속 적재 CLI — `whymath_backend.l1.concept_graph.populate`.

슬1 산출 `graph.json`(UC 키·정제)의 개념을 *세 투영*으로 동시 적재한다(같은 graph.json·동일 UC 키):
  ① **임베딩 벡터**(슬3): 설정된 임베딩 제공자(`config.embedding_provider`)로 안전 표현을 임베딩해
     `ConceptEmbeddingIndex`(pgvector `concept_embedding` 테이블)에 멱등 upsert.
  ② **메타 프로젝션**(소비 슬1·슬117): 개념의 *안전 메타*(name_ko·domain·review_status·코드·교수
     주석)를 `ConceptNodeStore`(`concept_node` 테이블)에 멱등 upsert — 검색 enrichment·게이팅 PG
     조인 백킹(UC 키 전용 프로젝션·UUID 없음).
  ③ **런타임 엔티티**(브리지 슬1): 개념을 backend `Concept` ORM 행으로 `BackendConceptStore`
     (`concept` 테이블·UUID PK)에 멱등 upsert하되 **`code`=UC**로 둔다 — 런타임 UUID concept ↔
     개념그래프 UC를 잇는 **브리지**(L2 mastery·problem_concept·L4가 참조하는 UUID가 UC에 닿음).
한 CLI에서 셋 다 적재가 자연스럽다(같은 입력·같은 UC 키·같은 sync 엔진 좌석). ①②는 UC 공간 전용
투영이고 ③이 UC↔UUID 브리지를 놓는다(삼중 store → 사중 store 단일 논리키 UC). L4 오개념 적재
CLI(`l4.misconception.semantic.populate`)와 동형이되, 입력이 카탈로그가 아니라 `graph.json`이다.

전제: `WHYMATH_VECTOR_STORE=pgvector` + 마이그레이션 head 적용된 실 PG 도달(`concept_embedding`·
`concept_node` 테이블) + `graph.json` 존재(슬1 `transform-v1 --output-dir`로 생성). 기본(memory)에선
영속 store가 없으므로 이 CLI는 의미가 없다(pgvector 명시 시에만). 자격증명은 env(시크릿 0 하드코딩).
라이브 임베딩 모델 로드(bge-m3 다운로드·OpenAI 키)는 첫 embed에서 발생한다. 메타 적재는 임베딩
호출이 없다(provider 불요·순수 메타 upsert).

CI hermetic: 이 모듈 import만으로는 임베딩·PG 연결이 없다(provider·엔진 모두 지연). 실제
적재는 CLI 실행(`__main__`) 또는 통합테스트에서만.

redaction(우선순위 #2): 세 투영 모두 *안전 필드만* — description·formal_definition·intuitive_
explanation은 임베딩 입력에도 메타 컬럼에도 런타임 엔티티에도 없다(graph.json 부재·로더 미독·컬럼
부재의 삼중 방어). ③ backend `concept`은 본문 3컬럼·오개념 컬럼을 2026-07-03 Phase 1b로 아예
제거했다(런타임 소비처 0·redaction 청산 — `db/models/concept.py`·`schema/concept.py`).

사용:
    WHYMATH_VECTOR_STORE=pgvector \
    python -m whymath_backend.l1.concept_graph.populate \
        --graph data/concept_graph/graph.json
"""

from __future__ import annotations

import argparse
from pathlib import Path

from whymath_backend.config import get_settings
from whymath_backend.db.cms_edit_marker import add_overwrite_argument, conflict_summary
from whymath_backend.l1.concept_graph.backend_concept import (
    load_backend_concepts_from_graph_json,
    populate_backend_concepts,
)
from whymath_backend.l1.concept_graph.backend_edge import (
    load_backend_edges_from_graph_json,
    populate_backend_edges,
)
from whymath_backend.l1.concept_graph.embedding import (
    load_concepts_from_graph_json,
    populate_concept_embeddings,
)
from whymath_backend.l1.concept_graph.node_projection import (
    load_concept_nodes_from_graph_json,
    populate_concept_nodes,
)
from whymath_backend.l1.embedding_provider import build_provider

# graph.json 기본 경로(슬1 transform-v1 --output-dir 관례). 명시 --graph로 오버라이드.
_DEFAULT_GRAPH_PATH = Path("data/concept_graph/graph.json")


def main(argv: list[str] | None = None) -> int:
    """graph.json 개념을 임베딩+메타+런타임엔티티 세 투영으로 적재하고 각 행 수를 출력(CLI 본체).

    ① 안전 표현을 임베딩해 `ConceptEmbeddingIndex`(concept_embedding)에, ② 안전 메타를
    `ConceptNodeStore`(concept_node)에, ③ 런타임 엔티티를 `BackendConceptStore`(concept·UUID PK·
    **code=UC 브리지**)에 멱등 upsert한다(같은 graph.json·동일 UC 키). 반환은 프로세스 종료 코드
    (0=성공·2=설정/입력 오류). 세 적재 건수를 stdout으로 보고한다.
    """
    parser = argparse.ArgumentParser(
        prog="whymath-concept-populate",
        description=(
            "개념그래프 graph.json → pgvector 의미 임베딩(concept_embedding) + 메타 프로젝션"
            "(concept_node) + 런타임 엔티티(concept·code=UC 브리지) 멱등 적재(슬3·소비·브리지 슬1)."
        ),
    )
    parser.add_argument(
        "--graph",
        type=Path,
        default=_DEFAULT_GRAPH_PATH,
        help=f"슬1 transform-v1 산출 graph.json 경로(기본 {_DEFAULT_GRAPH_PATH}).",
    )
    add_overwrite_argument(parser)
    args = parser.parse_args(argv)
    conflicts: list[str] = []

    settings = get_settings()
    if settings.vector_store != "pgvector":
        # memory 모드에선 영속 store가 없다 — 명확히 보고하고 비정상 종료(조용한 무동작 금지).
        print(
            "WHYMATH_VECTOR_STORE=pgvector가 아닙니다(현재: "
            f"{settings.vector_store}). pgvector 적재는 영속 store 모드에서만 의미가 있습니다."
        )
        return 2
    graph_path: Path = args.graph
    if not graph_path.exists():
        print(
            f"graph.json 없음: {graph_path} — 슬1 transform-v1 산출을 먼저 생성하세요 "
            "(`python -m data_pipeline.concept_graph transform-v1 --output-dir ...`)."
        )
        return 2
    # ① 임베딩 벡터 적재(슬3) — 안전 표현 임베딩 → concept_embedding upsert.
    #    name_ko·intuition·representations는 전부 graph.json 노드에서 읽는다(Phase 1).
    concepts = load_concepts_from_graph_json(graph_path)
    provider = build_provider(settings)
    embedding_count = populate_concept_embeddings(concepts, provider, settings=settings)

    # ② 메타 프로젝션 적재(소비 슬1) — 안전 메타 → concept_node upsert(임베딩 호출 없음).
    nodes = load_concept_nodes_from_graph_json(graph_path)
    node_count = populate_concept_nodes(nodes, settings=settings)

    # ③ 런타임 엔티티 적재(브리지 슬1) — backend concept upsert(code=UC 브리지·임베딩 호출 없음).
    backend_records = load_backend_concepts_from_graph_json(graph_path)
    backend_count = populate_backend_concepts(
        backend_records,
        settings=settings,
        overwrite_cms_edits=args.overwrite_cms_edits,
        conflicts=conflicts,
    )

    # ④ 선수엣지 적재(선수 슬1) — graph 선수 관계 → backend concept_edge upsert. 노드(③)가 먼저
    #    적재돼야 code→UUID 해석·FK가 가능하므로 ③ 다음에 온다(orphan은 건너뜀). 선수만 적재.
    edge_records, edge_skips = load_backend_edges_from_graph_json(graph_path)
    edge_count = populate_backend_edges(
        edge_records,
        settings=settings,
        overwrite_cms_edits=args.overwrite_cms_edits,
        conflicts=conflicts,
    )

    print(
        f"개념 임베딩 적재 완료: {embedding_count}건 "
        f"(provider={settings.embedding_provider})·"
        f"메타 프로젝션 적재 완료: {node_count}건·"
        f"런타임 엔티티(concept·code=UC) 적재 완료: {backend_count}건·"
        f"선수엣지(concept_edge·PREREQUISITE) 적재 완료: {edge_count}건"
        f"(로딩 skip {len(edge_skips)}건) (graph={graph_path})."
    )
    if conflicts:
        print(conflict_summary(conflicts))
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI 진입점(통합·운영 실행 전용)
    raise SystemExit(main())
