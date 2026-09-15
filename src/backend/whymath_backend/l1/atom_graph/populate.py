"""원자 백본 코퍼스 → backend `concept`/`concept_edge`/`atom_node` 적재 진입점(원자 Phase 1).

구 개념그래프 `populate.py`와 *별개* 진입점이다(원자 백본 전용·기존 적재 경로 무변경). 순서:
  ① concept 노드 전량 upsert(parent 없이) → ② parent_concept_id 2-pass 해소 → ③ 선수엣지 적재
  (code→UUID 해석·orphan skip). 엣지는 노드가 먼저 적재돼야 양끝 UUID가 잡히므로 ③은 ①②  다음.
  ④·⑤ 시각화 Overlay 2종(`concept_visual_style`·`concept_visualization`) 적재 — **VIZ-01 D1**
  (`docs/architecture/visualization_module_gap_review.md` §3) 해소: 이 함수가 이전에는
  concept·concept_edge만 적재하고 두 Overlay를 건드리지 않아, 학생 경로(`/v1/scenes/weak-concept`
  → `l4/scene_generation.py`의 AND 게이트)가 항상 시각화를 생략했다(전 시각화 스택 도달 0회).
  ④⑤는 *opt-in*이다(`visual_style_path`/`visualization_path`가 `None`이면 스킵) — 기존
  단위테스트(`tests/backend/l1/atom_graph/test_populate.py`)가 tmp_path 그래프만 주입하고 오버레이
  코퍼스 경로를 모르므로, 무조건 기본 상대경로를 시도하면 CWD에 따라 부수적으로 실패한다.
  프로덕션 CLI(`_main()`)는 기본값으로 두 코퍼스를 항상 로드해 실제 배포에서는 상시 적재된다.
  ⑥ `atom_node` 메타 프로젝션 적재 — **SKB-03**: 이 디렉터리의 `atom_node_projection.py`가
  적재 구현을 갖고도 어느 CLI에서도 호출되지 않아 prod에 한 번도 적재된 적이 없었다(형제 모듈을
  부르는 저장소 관례에서 atom_graph만 빠져 있었다). L2 약개념 추천의 메타 enrich가 그만큼 조용히
  `off_atom_axis`로 계상돼 왔다. ④⑤와 같이 *opt-in*이되 스위치는 경로가 아니라 불린이다
  (같은 `graph.json`을 읽으므로 별도 경로 인자가 없다).

멱등: 재실행 시 갱신(노드 UUID·엣지 edge_id 보존, Overlay는 code PK upsert). sync 엔진은 슬3
좌석 재사용(신규 seam 0).

CLI: `python -m whymath_backend.l1.atom_graph.populate --graph data/corpus/atom_graph_v1/graph.json`
(atom_node 적재는 CLI 기본 ON — `--skip-atom-node`로 opt-out)
(접속은 `Settings.sync_database_url` env·자격증명 하드코딩 0). `--visual-style-corpus`·
`--visualization-corpus`로 오버레이 코퍼스 경로를 바꿀 수 있고, 빈 문자열(`""`)을 주면 해당
오버레이 적재를 건너뛴다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from whymath_backend.config import Settings, get_settings
from whymath_backend.l1.atom_graph.atom_backend_concept import (
    AtomBackendConceptStore,
    load_atom_concepts_from_graph_json,
    populate_atom_concepts,
)
from whymath_backend.l1.atom_graph.atom_backend_edge import (
    AtomBackendEdgeRecord,
    AtomBackendEdgeStore,
    load_atom_edges_from_graph_json,
    populate_atom_edges,
)
from whymath_backend.l1.atom_graph.atom_node_projection import (
    AtomNodeStore,
    load_atom_nodes_from_graph_json,
    populate_atom_nodes,
)
from whymath_backend.l1.concept_visual_style import (
    ConceptVisualStyleStore,
    load_concept_visual_style_from_json,
    populate_concept_visual_style,
)
from whymath_backend.l1.concept_visualization import (
    ConceptVisualizationStore,
    load_concept_visualization_from_json,
    populate_concept_visualization,
)

# 프로덕션 CLI 기본 오버레이 코퍼스 경로(리포 루트 상대 — 기존 `--graph` 기본값과 동일 관례).
DEFAULT_VISUAL_STYLE_CORPUS = Path("data/corpus/concept_visual_style_v1/concept_visual_style.json")
DEFAULT_VISUALIZATION_CORPUS = Path("data/corpus/concept_visualization_v1/visualizability.json")


class AtomBackboneCycleError(ValueError):
    """선수엣지에 순환(cycle)이 있어 적재를 거부할 때 — 학습 경로 구성 불가.

    DAG 불변식(`math_dsl_risk_register.md` Q10-②)을 *적재 시점*에 강제하는 방어선이다.
    데이터 파이프라인 `validate.py`가 이미 transform 단계에서 cycle을 hard-error로 막지만,
    backend는 graph.json을 신뢰하고 직접 적재하므로(부분 재적재·손수 편집된 코퍼스 대비)
    여기서도 한 번 더 막는다. `cycle`은 순환 경로(닫힘 노드 반복 포함)다.
    """

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        super().__init__("순환 선수관계로 적재 거부 — 학습 경로 구성 불가: " + " → ".join(cycle))


def _find_prerequisite_cycle_in_records(
    records: Sequence[AtomBackendEdgeRecord],
) -> list[str] | None:
    """선수엣지 레코드(from=선수→to=후행)에서 사이클 1건 탐지(DFS·비재귀 스택).

    데이터 파이프라인 `data_pipeline.atom_graph.validate._find_prerequisite_cycle`의 backend
    짝이다(별 패키지라 import 대신 동일 알고리즘 미러). 모든 레코드는 PREREQUISITE이다
    (`load_atom_edges_from_graph_json`이 선수만 남김). 1,837 노드 깊은 체인 대비 재귀 대신 명시
    스택을 쓴다. Returns: 사이클 노드 경로(닫힘 노드 반복) 또는 None.
    """
    adj: dict[str, list[str]] = {}
    for record in records:
        adj.setdefault(record.from_code, []).append(record.to_code)

    white, gray, black = 0, 1, 2
    color: dict[str, int] = {}

    for start in list(adj):
        if color.get(start, white) != white:
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        path: list[str] = [start]
        color[start] = gray
        while stack:
            node, child_idx = stack[-1]
            children = adj.get(node, [])
            if child_idx < len(children):
                stack[-1] = (node, child_idx + 1)
                nxt = children[child_idx]
                state = color.get(nxt, white)
                if state == gray:  # back-edge → 사이클
                    return path[path.index(nxt) :] + [nxt]
                if state == white:
                    color[nxt] = gray
                    path.append(nxt)
                    stack.append((nxt, 0))
            else:
                color[node] = black
                path.pop()
                stack.pop()
    return None


@dataclass(frozen=True, slots=True)
class AtomBackbonePopulateReport:
    """원자 백본 적재 결과 요약(운영 가시성·테스트 단언용)."""

    concepts_loaded: int
    parents_skipped: int
    edges_loaded: int
    edges_skipped: int
    # VIZ-01 D1 — 두 시각화 Overlay 적재 행 수(경로 미지정=스킵이면 0. 0이 "적재 시도했으나 코퍼스가
    # 비었다"와 "애초에 스킵했다"를 리포트만으로 구분 못 하는 점은 알려진 한계 — CLI stdout이 실행
    # 시점에 어느 경로를 썼는지 함께 찍어 보완한다).
    visual_styles_loaded: int
    visualization_loaded: int
    # SKB-03 — `atom_node` 메타 프로젝션 적재 행 수(opt-out이면 0). 위 Overlay 2종과 같은 한계를
    # 공유한다(0이 "코퍼스가 비었다"와 "건너뛰었다"를 구분 못 함) — CLI stdout이 어느 쪽인지 찍는다.
    atom_nodes_loaded: int


def populate_atom_backbone(
    graph_path: Path,
    *,
    settings: Settings | None = None,
    concept_store: AtomBackendConceptStore | None = None,
    edge_store: AtomBackendEdgeStore | None = None,
    visual_style_path: Path | None = None,
    visual_style_store: ConceptVisualStyleStore | None = None,
    visualization_path: Path | None = None,
    visualization_store: ConceptVisualizationStore | None = None,
    populate_node_meta: bool = False,
    atom_node_store: AtomNodeStore | None = None,
) -> AtomBackbonePopulateReport:
    """원자 코퍼스 graph.json을 backend `concept`/`concept_edge`에 멱등 적재(노드→parent→엣지).

    store 미주입 시 슬3 sync 엔진 재사용 store를 만든다(같은 settings 공유). 반환: 적재 리포트.

    `visual_style_path`/`visualization_path`(VIZ-01 D1)는 *opt-in*이다 — `None`(기본)이면 그
    Overlay는 건드리지 않는다(파일 접근 0·기존 단위테스트가 tmp_path 그래프만 주고도 그대로
    통과하는 이유). 프로덕션 CLI(`_main()`)는 두 경로 모두 기본값을 채워 호출하므로 실제 배포
    적재에서는 항상 함께 적재된다. 코퍼스 파일이 지정됐는데 없으면(오탈자 등) 기존 concept/edge
    로더와 동일하게 `FileNotFoundError`가 그대로 전파된다(조용한 스킵 금지 — 명시적 opt-out만
    허용, 암묵적 실패 금지).
    """
    resolved = settings if settings is not None else get_settings()
    c_store = (
        concept_store if concept_store is not None else AtomBackendConceptStore(settings=resolved)
    )
    e_store = edge_store if edge_store is not None else AtomBackendEdgeStore(settings=resolved)

    concept_records = load_atom_concepts_from_graph_json(graph_path)
    concepts_loaded, parent_skipped = populate_atom_concepts(
        concept_records, settings=resolved, store=c_store
    )

    edge_records, _load_skipped = load_atom_edges_from_graph_json(graph_path)

    # 적재 전 cycle 방어선(DAG 불변식·hard fail·조용한 skip 금지) — graph.json이 손수 편집되거나
    # 부분 재적재돼 순환이 유입되면 거부한다. 데이터 파이프라인 validate가 1차로 막지만 backend는
    # graph.json을 직접 신뢰하므로 여기서 한 번 더 막는다(math_dsl_risk_register.md Q10-②).
    cycle = _find_prerequisite_cycle_in_records(edge_records)
    if cycle is not None:
        raise AtomBackboneCycleError(cycle)

    edges_loaded = populate_atom_edges(edge_records, settings=resolved, store=e_store)

    # ── VIZ-01 D1 — 시각화 Overlay 2종 적재(opt-in·concept/edge 적재 성공 후) ──────────────
    visual_styles_loaded = 0
    if visual_style_path is not None:
        vs_store = (
            visual_style_store
            if visual_style_store is not None
            else ConceptVisualStyleStore(settings=resolved)
        )
        visual_style_records = load_concept_visual_style_from_json(visual_style_path)
        visual_styles_loaded = populate_concept_visual_style(
            visual_style_records, settings=resolved, store=vs_store
        )

    visualization_loaded = 0
    if visualization_path is not None:
        vz_store = (
            visualization_store
            if visualization_store is not None
            else ConceptVisualizationStore(settings=resolved)
        )
        visualization_records = load_concept_visualization_from_json(visualization_path)
        visualization_loaded = populate_concept_visualization(
            visualization_records, settings=resolved, store=vz_store
        )

    # ── SKB-03 — `atom_node` 메타 프로젝션 적재(opt-in·같은 graph.json 재파싱) ──────────────
    # 이 디렉터리의 `atom_node_projection.py`는 적재 구현을 갖고도 **어느 CLI도 부르지 않아**
    # prod에 한 번도 적재된 적이 없었다(2026-09-14 실측: 크로스워크 이전이 "atom_node 대상 행 부재
    # 1311건"을 보고). 저장소 관례상 `<dir>/populate.py`가 형제 `*_node_projection.py`를 부르는데
    # (`skill_graph`·`problem_type_graph`·`concept_content` 전부 그렇다) atom_graph만 그 연결이
    # 없었다 — 이 스텝이 그 공백을 메운다.
    #
    # Overlay 2종과 달리 **경로 인자가 없다**(같은 `graph_path`를 읽으므로). 그래서 opt-in 스위치는
    # `None` 경로가 아니라 불린 플래그다 — 기존 단위테스트가 tmp_path 그래프만 주고 PG 없이 도는
    # 계약을 그대로 보존하려면 기본값이 False여야 한다(VIZ-01 D1이 같은 이유로 opt-in을 택했다).
    # 프로덕션 CLI(`_main()`)는 True로 호출하므로 실제 배포 적재에서는 항상 함께 적재된다.
    atom_nodes_loaded = 0
    if populate_node_meta:
        n_store = (
            atom_node_store if atom_node_store is not None else AtomNodeStore(settings=resolved)
        )
        atom_node_records = load_atom_nodes_from_graph_json(graph_path)
        atom_nodes_loaded = populate_atom_nodes(atom_node_records, settings=resolved, store=n_store)

    return AtomBackbonePopulateReport(
        concepts_loaded=concepts_loaded,
        parents_skipped=len(parent_skipped),
        edges_loaded=edges_loaded,
        edges_skipped=len(edge_records) - edges_loaded,
        visual_styles_loaded=visual_styles_loaded,
        visualization_loaded=visualization_loaded,
        atom_nodes_loaded=atom_nodes_loaded,
    )


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "원자 백본 코퍼스 → backend concept/concept_edge 멱등 적재 "
            "(+ 시각화 Overlay 2종 — VIZ-01 D1 · + atom_node 메타 프로젝션 — SKB-03)"
        )
    )
    parser.add_argument(
        "--graph",
        type=Path,
        default=Path("data/corpus/atom_graph_v1/graph.json"),
        help="원자 코퍼스 graph.json 경로",
    )
    parser.add_argument(
        "--visual-style-corpus",
        type=str,
        default=str(DEFAULT_VISUAL_STYLE_CORPUS),
        help=(
            "권장 시각화 양식 코퍼스 경로(기본 "
            f"{DEFAULT_VISUAL_STYLE_CORPUS}). 빈 문자열('')이면 이 Overlay 적재를 건너뛴다."
        ),
    )
    parser.add_argument(
        "--visualization-corpus",
        type=str,
        default=str(DEFAULT_VISUALIZATION_CORPUS),
        help=(
            "시각화 가능성 4분류 코퍼스 경로(기본 "
            f"{DEFAULT_VISUALIZATION_CORPUS}). 빈 문자열('')이면 이 Overlay 적재를 건너뛴다."
        ),
    )
    parser.add_argument(
        "--skip-atom-node",
        action="store_true",
        help=(
            "atom_node 메타 프로젝션 적재를 건너뛴다(SKB-03). 기본은 적재 — 이 CLI가 그것을 "
            "부르지 않아 prod에 한 번도 적재된 적이 없었다."
        ),
    )
    args = parser.parse_args()
    visual_style_path = Path(args.visual_style_corpus) if args.visual_style_corpus else None
    visualization_path = Path(args.visualization_corpus) if args.visualization_corpus else None
    report = populate_atom_backbone(
        args.graph,
        visual_style_path=visual_style_path,
        visualization_path=visualization_path,
        populate_node_meta=not args.skip_atom_node,
    )
    print(
        f"[원자 백본 적재] concepts={report.concepts_loaded} "
        f"parent_skip={report.parents_skipped} "
        f"edges={report.edges_loaded} edge_skip={report.edges_skipped} "
        f"visual_styles={report.visual_styles_loaded}"
        f"({visual_style_path if visual_style_path else '스킵'}) "
        f"visualizability={report.visualization_loaded}"
        f"({visualization_path if visualization_path else '스킵'}) "
        f"atom_nodes={report.atom_nodes_loaded}"
        f"({'스킵' if args.skip_atom_node else args.graph})"
    )


if __name__ == "__main__":  # pragma: no cover
    _main()


__all__ = [
    "AtomBackboneCycleError",
    "AtomBackbonePopulateReport",
    "DEFAULT_VISUAL_STYLE_CORPUS",
    "DEFAULT_VISUALIZATION_CORPUS",
    "populate_atom_backbone",
]
