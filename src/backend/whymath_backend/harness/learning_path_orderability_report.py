"""학습 경로 위상 제약 밀도 관측 리포트 CLI — 빌드타임 결정론 관측(DB 0·LLM 0·HTTP 0). PATH-01
acceptance(D1).

설계 정본: `docs/architecture/learning_path_module_gap_review.md` §3 D1. `l2.learning_path.
order_learning_path`("Kahn 위상정렬")는 엔드포인트 기본 파라미터(`max_depth=1`)에서 집합 내부
제약 엣지가 0인 사례가 96.4%다 — "위상정렬"로 문서화된 알고리즘이 실사용 대부분에서 실제로는
`_tiebreak` 가중 정렬로 조용히 강등된다는 뜻이다. 이 밀도는 코드·테스트·문서 어디에도 수치로
존재하지 않았다(D1 문제 정의 — 8회차 반복 실수: "만들고 기본값으로 껐음"). 이 모듈은 그 수치를
*영구히 눈에 보이게* 한다 — `visualization_reach_report.py`가 확립한 "코퍼스 JSON을 읽고
프로덕션 판정 함수를 그대로 재호출" 패턴의 답습이다.

**게이트가 아니다**(`visualization_reach_report`·`problem_bank_coverage`와 동일 원칙) — 낮은
순서화 비율이 exit 1을 내지 않는다.

**구조적 상한 — 100%가 목표가 아니다**(acceptance③): 이 리포트의 모든 비율은 실제 런타임
(`build_learning_path`)의 `weak_only=True` 필터 *이전* 값이다:
  ① 런타임은 BKT/IRT로 *막힌*(약한) 선수만 노드로 삼는다 — 이 리포트는 코퍼스 구조 *전체*를
     대상으로 하므로(모든 선수개념이 이미 다 막혔다고 가정한 값), 실측 런타임 순서화 비율은
     이 값 **이하**다.
  ② 진짜 병렬 집합(두 선수개념 사이에 실제로 선수관계가 없어 순서가 없는 게 정답인 경우)이
     상당수 존재한다 — 그때 "병렬"로 표기하는 것 자체가 *정직한* 결과다. 가짜 순서를 부여하는
     것이 오히려 날조다(§2-⑨).

산출 3축(D1 "산출 3축" 그대로):
  1. **깊이별(1·2·5) 순서화 가능 비율** — `MAX_PREREQUISITE_DEPTH`(=5·`prerequisite_
     recommendation`의 단일 출처를 재사용·하드코딩 0) 예산 내에서 "전이 도달"(reach) 기준
     순서화 성립 비율. 깊이가 클수록 커진다(D3의 근거 수치 — 27.0% → 69.9%).
  2. **직접 엣지 vs 전이 도달 병기** — "직접" 축은 문자 그대로 1-hop `prerequisite` 엣지만
     쓰므로 **깊이와 무관하게 항상 동일**하다(96/356 = 27.0%). 아래 렌더 표에서 세 깊이 행의
     직접 축 값이 똑같다는 사실 자체가 "왜 깊이 예산을 늘려야 순서화가 느는가"(D3)의 실측
     근거다 — 두 축이 서로 다른 값을 낸다는 것 자체가 축이 실제로 둘로 분리돼 있다는 변별력
     증거다(acceptance⑤).
  3. **결정도 분포** — 완전 결정(모집단 내 모든 쌍이 순서 관계를 가짐) / 부분 결정(일부만) /
     **진짜 병렬**(어떤 쌍도 순서 관계가 없음 — 병렬이 정답인 경우). 병렬 건수가 0이 아닌 것
     자체는 실패가 아니다.

────────────────────────────────────────────────────────────────────────────
정렬 로직 재사용 — 신규 Kahn 구현 0
────────────────────────────────────────────────────────────────────────────
각 (개념 C의 막힌 선수집합, 깊이, 축) 조합마다 `l2.learning_path.order_learning_path`를
**그대로 재호출**한다 — 리포트가 자체 위상정렬을 재구현하면 리포트와 런타임이 갈라질 수 있다
(CLAUDE.md 구조 붕괴 방지 — "유지보수 지옥"은 truth source가 하나가 아닐 때 온다). 이 리포트가
자체적으로 갖는 신규 로직은 정확히 둘뿐이다:
  ① `_reach_within_hops` — "어떤 쌍이 내부 제약 엣지 후보가 되는가"를 정의하는 그래프 도달성
     계산(정렬 로직이 아니다 — D3가 미래에 `derive_ordering_edges`로 프로덕션화할 계산의 관측판).
  ② 결정도 분류(`full`/`partial`/`parallel`) — `order_learning_path` 자체엔 없는 *이 리포트
     전용* 분석 축이다(D2/D3가 착지하기 전까지 프로덕션에 대응 개념이 없어 새로 정의해야 했다).
`order_learning_path`의 반환값(`has_cycle`)은 사이클 안전성 sanity check로 소비한다 — 원자
백본은 DAG 보장(`validate.py` prerequisite_cycle hard error)이라 항상 False여야 하며, 그렇지
않으면 조용히 넘어가지 않고 리포트에 그대로 노출한다(CLAUDE.md "환각 발견 시 조용히 넘어가지
말고 로그·수정").

────────────────────────────────────────────────────────────────────────────
범위 밖 (acceptance⑥ — 이 태스크에 포함하지 않는다)
────────────────────────────────────────────────────────────────────────────
엔드포인트 응답 변경(`PATH-02`) · 정렬 알고리즘 변경(`PATH-03`) · `max_depth` 기본값 변경
(§4 페이퍼 P1) · 전역(全域) 학습 경로(§5, 발화 조건 4개 AND 미충족). 이 모듈은 코퍼스 JSON만
읽는 관측 리포트다 — 신규 스키마·DB 접근·네트워크 0.

사용:
    python -m whymath_backend.harness.learning_path_orderability_report
    python -m whymath_backend.harness.learning_path_orderability_report \\
        --json out/path_orderability.json
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from whymath_backend.l2.learning_path import order_learning_path
from whymath_backend.l2.prerequisite_recommendation import MAX_PREREQUISITE_DEPTH, PrerequisiteGap

__all__ = [
    "DEFAULT_CORPUS_PATH",
    "DEPTH_BUDGETS",
    "Axis",
    "CorpusGraph",
    "Determinism",
    "DepthAxisSummary",
    "OrderabilityReport",
    "build_report",
    "dump_json",
    "load_corpus_graph",
    "main",
    "render_report",
    "report_to_json",
]

_EXIT_OK = 0
_EXIT_INPUT_ERROR = 2

# harness→whymath_backend→backend→src→repo 루트(visualization_reach_report·problem_bank_
# coverage와 동일 관례).
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CORPUS_PATH = _REPO_ROOT / "data" / "corpus" / "atom_graph_v1" / "graph.json"

# 코퍼스 `edges[].relation` 리터럴 — `data_pipeline.atom_graph.validate.AtomRelation.
# PREREQUISITE.value`와 동일 문자열이다. 이 리포트는 backend 전용 harness라 data_pipeline
# cross-package import를 새로 늘리지 않고(`qa_pipeline.py` 모듈 docstring의 "cross-package
# import 경계" 절과 같은 근거 — 필요한 건 리터럴 문자열 하나뿐) 그대로 문자열로 둔다.
_RELATION_PREREQUISITE = "prerequisite"

# 깊이 축 — 1·2·5(acceptance②). "5"는 `MAX_PREREQUISITE_DEPTH`(구현 예산의 단일 출처)를 그대로
# 재사용한다(하드코딩 5 금지 — CLAUDE.md 매직넘버 중복 금지와 동형).
DEPTH_BUDGETS: tuple[int, ...] = (1, 2, MAX_PREREQUISITE_DEPTH)

Axis = Literal["direct", "transitive"]
_AXES: tuple[Axis, ...] = ("direct", "transitive")

Determinism = Literal["full", "partial", "parallel"]

# code(atom_graph_v1) → concept_id(UUID) 결정론 합성 전용 네임스페이스 — 이 리포트 하나만 쓴다.
# 코퍼스는 code 문자열만 갖고 실제 backend `concept.id`(UUID)가 없어 `order_learning_path`가
# 요구하는 `PrerequisiteGap.concept_id: uuid.UUID`를 합성해야 한다. 보장하는 것은 단 하나 —
# **같은 code는 항상 같은 UUID로 매핑된다**(교차 실행 재현성·결정론). 실 DB concept.id와는
# 무관한 리포트 전용 값이다.
_REPORT_UUID_NAMESPACE = uuid.UUID("6f1d9b8a-6b7a-5b1a-9c2e-8f7a0d2b6a11")


def _concept_id_for_code(code: str) -> uuid.UUID:
    """코퍼스 code → 결정론 합성 UUID(같은 code는 항상 같은 값·리포트 전용 네임스페이스)."""
    return uuid.uuid5(_REPORT_UUID_NAMESPACE, code)


# ──────────────────────────────────────────────────────────────────────────
# 로더 — 코퍼스 JSON → 최소 투영(정직 실패)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class CorpusGraph:
    """원자 백본 코퍼스(`graph.json`) 투영 — 이 리포트 집계에 필요한 최소 뷰(code 문자열만).

    `concept_codes`는 레벨 무관 전체 개념 code다(`visualization_reach_report`의 "세부개념만"
    필터와 달리 이 리포트는 분모를 좁히지 않는다 — 직접 선수 분포·population 재현이 전체
    개념 집합 자체를 분모로 삼기 때문·부록 실측 스크립트와 동형). `prerequisite_edges`는
    `relation == "prerequisite"`인 `(from_code, to_code)` 쌍만(원자 백본 v1은 전량
    prerequisite이나 방어적으로 필터한다).
    """

    concept_codes: tuple[str, ...]
    prerequisite_edges: tuple[tuple[str, str], ...]


def load_corpus_graph(payload: object) -> CorpusGraph:
    """atom_graph_v1 `graph.json`(dict) → `CorpusGraph`.

    Raises:
        ValueError: 최상위가 dict가 아니거나 `concepts`/`edges` 배열 부재·행 형식 오류
            (분모·엣지를 모른 채 리포트 불가 — `visualization_reach_report.load_catalog` 동형).
    """
    if not isinstance(payload, dict):
        raise ValueError(f"graph.json 최상위가 object가 아님(type={type(payload).__name__})")

    raw_concepts = payload.get("concepts")
    if not isinstance(raw_concepts, list):
        raise ValueError("graph.json에 'concepts' 배열이 없음")
    codes: list[str] = []
    for idx, item in enumerate(raw_concepts):
        if not isinstance(item, dict):
            raise ValueError(f"concepts[{idx}]가 object가 아님(type={type(item).__name__})")
        code = item.get("code")
        if not isinstance(code, str) or not code:
            raise ValueError(f"concepts[{idx}]에 code 문자열이 없음")
        codes.append(code)

    raw_edges = payload.get("edges")
    if not isinstance(raw_edges, list):
        raise ValueError("graph.json에 'edges' 배열이 없음")
    edges: list[tuple[str, str]] = []
    for idx, item in enumerate(raw_edges):
        if not isinstance(item, dict):
            raise ValueError(f"edges[{idx}]가 object가 아님(type={type(item).__name__})")
        if item.get("relation") != _RELATION_PREREQUISITE:
            continue  # 선수관계 외(원자 백본 v1엔 없으나 방어적 필터).
        from_code = item.get("from_code")
        to_code = item.get("to_code")
        if not isinstance(from_code, str) or not from_code:
            raise ValueError(f"edges[{idx}]에 from_code 문자열이 없음")
        if not isinstance(to_code, str) or not to_code:
            raise ValueError(f"edges[{idx}]에 to_code 문자열이 없음")
        edges.append((from_code, to_code))

    return CorpusGraph(concept_codes=tuple(codes), prerequisite_edges=tuple(edges))


# ──────────────────────────────────────────────────────────────────────────
# 인접·모집단·도달성 — 순수 헬퍼(정렬 로직 아님)
# ──────────────────────────────────────────────────────────────────────────
def _build_adjacency(
    edges: Sequence[tuple[str, str]],
) -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    """`(from,to)` prerequisite 엣지 → (선수맵 `pred[to]={from...}`, 후행맵 `succ[from]={to...}`).

    순수 인덱싱(정렬·판정 로직 0) — `order_learning_path`가 매번 내부에서 하는 인접 구성과
    무관한, 이 리포트가 population·reach 계산에 쓰는 조회 구조일 뿐이다.
    """
    pred: dict[str, set[str]] = defaultdict(set)
    succ: dict[str, set[str]] = defaultdict(set)
    for frm, to in edges:
        pred[to].add(frm)
        succ[frm].add(to)
    return (
        {k: frozenset(v) for k, v in pred.items()},
        {k: frozenset(v) for k, v in succ.items()},
    )


def _direct_predecessor_distribution(
    codes: Sequence[str], pred: Mapping[str, frozenset[str]]
) -> dict[int, int]:
    """전체 개념의 직접 선수 개수(in-degree) 분포 — acceptance① 915/1412/278/70/8 재현 대상."""
    dist: Counter[int] = Counter(len(pred.get(code, frozenset())) for code in codes)
    return dict(sorted(dist.items()))


def _population(codes: Sequence[str], pred: Mapping[str, frozenset[str]]) -> tuple[str, ...]:
    """직접 선수 2개 이상인 개념(code) — "순서화가 성립할 수 있는" 후보 모집단(정렬 결정론)."""
    return tuple(sorted(code for code in codes if len(pred.get(code, frozenset())) >= 2))


def _reach_within_hops(start: str, hops: int, succ: Mapping[str, frozenset[str]]) -> frozenset[str]:
    """`start`에서 후행(succ) 방향으로 `hops` 이내 도달 가능한 노드 집합(본인 제외).

    이것은 Kahn 정렬 로직이 아니다 — "전이 축"에서 어떤 쌍이 순서 제약 후보가 되는지 정의하는
    그래프 탐색이다(D3가 미래에 `derive_ordering_edges`로 프로덕션화할 계산의 관측판 — 이
    리포트가 유일하게 갖는 신규 로직 중 하나. 정렬·tiebreak는 100% `order_learning_path`에
    위임한다). `hops=1`이면 직접 후행 집합과 동일 — "직접 엣지" 축과 "전이 축 depth=1"이
    구조적으로 같은 값을 내는 이유다.
    """
    seen: set[str] = set()
    frontier: set[str] = {start}
    depth = 0
    while frontier and depth < hops:
        depth += 1
        nxt: set[str] = set()
        for node in frontier:
            for neighbor in succ.get(node, frozenset()):
                if neighbor not in seen:
                    seen.add(neighbor)
                    nxt.add(neighbor)
        frontier = nxt
    return frozenset(seen)


# ──────────────────────────────────────────────────────────────────────────
# 셀 판정 — order_learning_path 재호출(신규 정렬 로직 0)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class _ConceptCellResult:
    """population 개념 1건의 (깊이, 축) 1칸 판정 — `order_learning_path` 재호출 산출."""

    orderable: bool
    determinism: Determinism
    pair_determined: int
    pair_total: int
    has_cycle: bool  # order_learning_path 사이클 sanity(DAG 코퍼스라 항상 False 기대).


def _evaluate_cell(
    predecessors: frozenset[str],
    *,
    axis: Axis,
    depth: int,
    edge_set: frozenset[tuple[str, str]],
    succ: Mapping[str, frozenset[str]],
) -> _ConceptCellResult:
    """개념 C의 직접 선수집합(`predecessors`, `|predecessors| >= 2`는 호출부 population 보증)에
    대해 (축, 깊이) 1칸의 순서화·결정도를 판정한다.

    `order_learning_path`(프로덕션 함수)를 실제로 호출해 `LearningPath`를 얻는다 — 신규 Kahn
    구현 0. orderable/결정도는 여기서 구성한 `internal_edges`(=Kahn이 그대로 소비할 그 집합)
    에서 직접 셈한다 — `order_learning_path`가 내부적으로 하는 것과 동일한 (frm,to 둘 다 노드
    집합 안·중복 제거) 판정을 이 리포트가 이미 알고 있는 입력에서 다시 셈하는 것뿐이며, Kahn
    루프·`_tiebreak` 비교자 자체는 전혀 재구현하지 않는다(D2가 예고한 `ordering_edge_count =
    sum(len(v) for v in adj.values())`와 동형의 trivial 카운트 — 정렬 알고리즘이 아니다).
    `has_cycle`은 DAG 보장 코퍼스의 sanity check로만 쓴다(True가 나오면 조용히 넘어가지 않고
    그대로 리포트에 노출 — CLAUDE.md "환각 발견 시 조용히 넘어가지 말고 로그").
    """
    nodes = sorted(predecessors)
    node_ids = {code: _concept_id_for_code(code) for code in nodes}

    pairs: set[tuple[str, str]]
    if axis == "direct":
        # 직접 축 — 문자 그대로 1-hop prerequisite 엣지만(깊이 무관·항상 동일한 값).
        pairs = {(a, b) for a in nodes for b in nodes if a != b and (a, b) in edge_set}
    else:
        # 전이 축 — a에서 depth 이내 도달 가능한(succ 방향) 노드를 predecessors와 교집합.
        pairs = set()
        for a in nodes:
            reachable = _reach_within_hops(a, depth, succ) & predecessors
            for b in reachable:
                if b != a:
                    pairs.add((a, b))

    gaps = [
        PrerequisiteGap(
            concept_id=node_ids[code],
            concept_code=code,
            agreement="insufficient",  # 측정 없음(BKT/IRT 실데이터는 이 리포트 범위 밖).
            depth=0,  # 임의 상수 — Kahn 핵심(in-degree)엔 무관·풀 내부 tie-break에만 쓰임.
        )
        for code in nodes
    ]
    internal_edges = [(node_ids[a], node_ids[b]) for a, b in pairs]
    path = order_learning_path(gaps, internal_edges)  # 프로덕션 재호출(신규 정렬 로직 0).

    total = len(nodes) * (len(nodes) - 1) // 2
    determined = 0
    for i, a in enumerate(nodes):
        for b in nodes[i + 1 :]:
            if (a, b) in pairs or (b, a) in pairs:
                determined += 1

    determinism: Determinism
    if total == 0:
        determinism = "parallel"  # population 계약상 발생 안 함(|S|>=2)이나 방어적.
    elif determined == total:
        determinism = "full"
    elif determined == 0:
        determinism = "parallel"
    else:
        determinism = "partial"

    return _ConceptCellResult(
        orderable=len(pairs) > 0,
        determinism=determinism,
        pair_determined=determined,
        pair_total=total,
        has_cycle=path.has_cycle,
    )


# ──────────────────────────────────────────────────────────────────────────
# 집계 — 리포트(순수 코어)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class DepthAxisSummary:
    """population 전체에 대한 (깊이 d, 축) 1행 집계 — 깊이×축 그리드의 셀 하나.

    `cycle_detected_count`는 sanity 값이다 — 원자 백본은 DAG 보장(prerequisite_cycle hard
    error)이라 항상 0이어야 한다. 0이 아니면 데이터·코드 가정이 깨진 것이므로 렌더·JSON에서
    조용히 넘어가지 않고 그대로 노출한다.
    """

    depth: int
    axis: Axis
    population: int
    orderable_count: int
    full_count: int
    partial_count: int
    parallel_count: int
    pair_determined_total: int
    pair_total: int
    cycle_detected_count: int

    @property
    def orderable_rate(self) -> float | None:
        if self.population == 0:
            return None
        return self.orderable_count / self.population


def _summarize(
    population_codes: tuple[str, ...],
    pred: Mapping[str, frozenset[str]],
    succ: Mapping[str, frozenset[str]],
    edge_set: frozenset[tuple[str, str]],
    *,
    depth: int,
    axis: Axis,
) -> DepthAxisSummary:
    """모집단 전체를 순회해 (깊이, 축) 1행으로 집계(`_evaluate_cell`을 개념마다 재호출)."""
    orderable = full = partial = parallel = cycles = 0
    pair_determined_total = pair_total = 0
    for code in population_codes:
        result = _evaluate_cell(pred[code], axis=axis, depth=depth, edge_set=edge_set, succ=succ)
        if result.orderable:
            orderable += 1
        if result.determinism == "full":
            full += 1
        elif result.determinism == "partial":
            partial += 1
        else:
            parallel += 1
        pair_determined_total += result.pair_determined
        pair_total += result.pair_total
        if result.has_cycle:
            cycles += 1
    return DepthAxisSummary(
        depth=depth,
        axis=axis,
        population=len(population_codes),
        orderable_count=orderable,
        full_count=full,
        partial_count=partial,
        parallel_count=parallel,
        pair_determined_total=pair_determined_total,
        pair_total=pair_total,
        cycle_detected_count=cycles,
    )


@dataclass(slots=True, frozen=True)
class OrderabilityReport:
    """PATH-01 D1 산출 전량(불변·렌더/직렬화의 단일 입력).

    **구조적 상한(acceptance③)**: `cells`의 모든 비율은 `build_learning_path`의
    `weak_only=True` 필터 *이전* — 즉 코퍼스 구조 전체를 "이미 다 막혔다"고 가정했을 때의
    상한이다. 실측 런타임 비율은 이 값 **이하**다. 진짜 병렬 집합(순서가 없는 것이 정답인 경우)
    이 존재하므로 **100%는 목표가 아니다**.
    """

    corpus_concept_total: int
    corpus_edge_total: int
    direct_predecessor_distribution: dict[int, int]
    population_size: int
    cells: tuple[DepthAxisSummary, ...]  # len == len(DEPTH_BUDGETS) * len(_AXES).


def build_report(graph: CorpusGraph) -> OrderabilityReport:
    """코퍼스 → `OrderabilityReport`(순수·부작용 0·`order_learning_path` 그대로 재호출)."""
    pred, succ = _build_adjacency(graph.prerequisite_edges)
    edge_set = frozenset(graph.prerequisite_edges)
    population_codes = _population(graph.concept_codes, pred)
    distribution = _direct_predecessor_distribution(graph.concept_codes, pred)

    cells = tuple(
        _summarize(population_codes, pred, succ, edge_set, depth=depth, axis=axis)
        for depth in DEPTH_BUDGETS
        for axis in _AXES
    )

    return OrderabilityReport(
        corpus_concept_total=len(graph.concept_codes),
        corpus_edge_total=len(graph.prerequisite_edges),
        direct_predecessor_distribution=distribution,
        population_size=len(population_codes),
        cells=cells,
    )


# ──────────────────────────────────────────────────────────────────────────
# 렌더 — 사람이 읽는 마크다운 + 기계가 읽는 JSON
# ──────────────────────────────────────────────────────────────────────────
def _pct(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "데이터없음"
    return f"{numerator / denominator * 100:.1f}%"


_AXIS_LABEL: dict[Axis, str] = {"direct": "직접", "transitive": "전이"}


def render_report(report: OrderabilityReport) -> str:
    """관측 결과를 마크다운으로 렌더(순수·입력 외 계산 없음)."""
    lines: list[str] = [
        "# 학습 경로 위상 제약 밀도 관측 리포트 (PATH-01 D1)",
        "",
        "> 관측 리포트다 — **exit 게이트가 아니다**(낮은 순서화 비율로 실패시키지 않는다).",
        "> **구조적 상한**: 이 수치는 `build_learning_path`의 `weak_only=True` 필터 *이전* —",
        "> 코퍼스 구조 전체를 기준으로 한다. 실측 런타임 순서화 비율은 이 값 **이하**다.",
        "> **100%는 목표가 아니다** — 진짜 병렬 집합(선수관계가 없어 순서가 없는 게 정답인 쌍)이",
        "> 존재한다. 병렬 건수가 0이 아닌 것 자체는 실패가 아니다.",
        "",
        "## 0. 코퍼스",
        "",
        f"- 개념(전체 레벨) 총계: **{report.corpus_concept_total}**",
        f"- `prerequisite` 엣지 총계: **{report.corpus_edge_total}**",
        "",
        "## 1. 직접 선수 개수 분포 (in-degree)",
        "",
        "| 직접 선수 개수 | 개념 수 |",
        "|---:|---:|",
    ]
    for count, n in sorted(report.direct_predecessor_distribution.items()):
        lines.append(f"| {count} | {n} |")
    lines += [
        "",
        f"- 직접 선수 **2개 이상**(순서화가 성립할 수 있는 모집단): **{report.population_size}**",
        "",
        "## 2. 깊이별(1·2·5) × (직접 엣지·전이 도달) × 결정도",
        "",
        "직접 엣지 축은 문자 그대로 1-hop `prerequisite` 엣지만 쓰므로 **깊이와 무관하게 항상",
        "동일**하다 — 아래 표에서 세 깊이 행의 직접 축 값이 똑같다는 사실 자체가 D3의 핵심",
        "근거다(깊이 예산을 늘려도 직접 축은 그대로고, 전이 축만 자란다).",
        "",
        "| 깊이 | 축 | 순서화 가능 | 비율 | 완전 결정 | 부분 결정 | 병렬 |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for cell in report.cells:
        lines.append(
            f"| {cell.depth} | {_AXIS_LABEL[cell.axis]} | "
            f"{cell.orderable_count}/{cell.population} | "
            f"{_pct(cell.orderable_count, cell.population)} | {cell.full_count} | "
            f"{cell.partial_count} | {cell.parallel_count} |"
        )
    cycle_total = sum(c.cycle_detected_count for c in report.cells)
    lines += [
        "",
        "## 3. 사이클 sanity",
        "",
        f"- 원자 백본은 DAG 보장(`prerequisite_cycle` hard error) — 항상 0 기대: "
        f"**{cycle_total}**"
        + (
            ""
            if cycle_total == 0
            else " ⚠️ DAG 가정 위반 실측 — 데이터·코드 재점검 필요(조용히 넘어가지 않음)."
        ),
        "",
    ]
    return "\n".join(lines)


def report_to_json(report: OrderabilityReport) -> dict[str, Any]:
    """리포트 → JSON 직렬화 가능 dict(키 정렬은 dump 시 `sort_keys=True`로 고정).

    `is_structural_ceiling`·`structural_ceiling_note`는 acceptance③ 이행 — 산출값이 런타임
    실측과 혼동되지 않도록 JSON 자체에도 명시한다.
    """
    return {
        "corpus_concept_total": report.corpus_concept_total,
        "corpus_edge_total": report.corpus_edge_total,
        "direct_predecessor_distribution": {
            str(k): v for k, v in sorted(report.direct_predecessor_distribution.items())
        },
        "population_size": report.population_size,
        "cells": [
            {
                "depth": cell.depth,
                "axis": cell.axis,
                "population": cell.population,
                "orderable_count": cell.orderable_count,
                "orderable_rate": cell.orderable_rate,
                "full_count": cell.full_count,
                "partial_count": cell.partial_count,
                "parallel_count": cell.parallel_count,
                "pair_determined_total": cell.pair_determined_total,
                "pair_total": cell.pair_total,
                "cycle_detected_count": cell.cycle_detected_count,
            }
            for cell in report.cells
        ],
        "is_structural_ceiling": True,
        "structural_ceiling_note": (
            "이 수치는 build_learning_path의 weak_only=True 필터 적용 이전의 구조적 상한이다. "
            "실측 런타임 순서화 비율은 이 값 이하다. 100%는 목표가 아니다 — 진짜 병렬 집합"
            "(선수관계가 없어 순서가 없는 게 정답인 쌍)이 존재한다."
        ),
    }


def dump_json(report: OrderabilityReport) -> str:
    return json.dumps(report_to_json(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# ──────────────────────────────────────────────────────────────────────────
# CLI (얇은 껍데기 — 경로 해석·입출력만, 집계는 위 순수 코어)
# ──────────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 위상 제약 밀도 관측 리포트를 stdout에 출력. **0=성공 / 2=입력 오류**(1 없음).

    순서화 비율이 낮아도(심지어 0이어도) exit 0이다(게이트 아님). exit 2는 코퍼스 자체를 읽을
    수 없는 입력 오류에만 쓴다.
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.learning_path_orderability_report",
        description=(
            "학습 경로 위상 제약 밀도 관측 리포트(PATH-01 D1) — 깊이별(1·2·5)×(직접·전이)×"
            "결정도(완전/부분/병렬) 3축. 결정론·게이트 아님(exit 0/2)."
        ),
    )
    parser.add_argument(
        "--corpus", type=Path, default=DEFAULT_CORPUS_PATH, help="atom_graph_v1 graph.json 경로"
    )
    parser.add_argument(
        "--json", dest="json_path", type=Path, default=None, help="JSON 산출물 경로(선택)"
    )
    args = parser.parse_args(argv)

    try:
        graph = load_corpus_graph(json.loads(args.corpus.read_text(encoding="utf-8")))
    except Exception as exc:  # noqa: BLE001 — 입력 오류는 타입명과 함께 보고하고 exit 2
        print(f"입력 오류 — 코퍼스 적재 실패({type(exc).__name__}): {exc}", file=sys.stderr)
        return _EXIT_INPUT_ERROR

    report = build_report(graph)
    print(render_report(report))
    if args.json_path is not None:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(dump_json(report), encoding="utf-8")
        print(f"JSON 산출물: {args.json_path}")
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
