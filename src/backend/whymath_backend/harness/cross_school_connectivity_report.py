"""학교급 경계 선수 연결 밀도 관측 리포트 CLI — 빌드타임 결정론 관측(DB 0·LLM 0·HTTP 0). CUR-06
acceptance(D6).

설계 정본: `docs/architecture/curriculum_module_gap_review_r2.md` §3 D6. 원자 백본 2,210엣지는
전량 `prerequisite`인데, 이 중 **양끝점의 학교급이 다른 경계 엣지는 20건(0.9%)** 뿐이고
고등→대학은 0건이다(= 설계 시점 실측. 2026-10-09 S4-60이 고→대 24건을 병합해 현재 정본은
2,234엣지 중 경계 44건·1.97%, 고→대 24건이다). 그래서 `recommend_prerequisite_gaps`의
재귀 CTE(깊이 ≤ `MAX_PREREQUISITE_DEPTH`)는 고등 약점에서 중학 결손으로 사실상 내려가지
못한다 — 알고리즘이 아니라 **데이터 위상** 문제다. 이전 판정("prerequisite ✅ 초과")은 내부
밀도(2,190건)만 보고 경계 밀도를 보지 않았다.
이 모듈은 그 수치를 *영구히 눈에 보이게* 한다 — `learning_path_orderability_report`(PATH-01)가
확립한 "코퍼스 JSON을 읽고 순수 코어로 집계" 패턴의 답습이다.

**게이트가 아니다**(`learning_path_orderability_report`·`problem_bank_coverage`와 동일 원칙) —
경계 밀도가 0이어도 exit 1을 내지 않는다. 종료 코드는 0(성공)·2(코퍼스를 읽을 수 없는 입력
오류)뿐이다.

산출 4축:
  1. **학교급 쌍별 엣지 밀도** — (선수 학교급 → 후행 학교급)별 건수. 같은 학교급 내부 vs 경계.
  2. **학년군 경계 밀도** — 양끝점 `grade_band`가 둘 다 있고 서로 다른 엣지의 (선수→후행) 쌍.
     학년군이 비어 있는 끝점이 낀 엣지는 별도로 센다(모르는 것을 경계 아님으로 접지 않는다).
  3. **경계 표시 이중 확인** — 소스 자체의 `school_link` 플래그 집합과 양끝점 유도 집합의
     교집합/차집합(both · flag only · endpoint only). 판정 권위는 두 근거의 일치이며, 코퍼스
     내부의 `relation_subtype` 라벨(학년간·학교급간(추정))은 부수적으로 기록만 한다.
  4. **하향 도달 가능 비율** — "상위 학교급 노드 출발 → 선수 사슬을 거슬러 하위 학교급 노드에
     도달"하는 비율(깊이 1·2·`MAX_PREREQUISITE_DEPTH`·무제한). 고등→중학 행이 핵심이다. 총
     엣지 수가 아니라 *도달*을 재므로 경계 엣지 1건의 가감에 반응한다(총량 지표는 반응하지
     않는다 — 변별력 계약).

범위 밖(acceptance⑤): 경계 엣지의 생성·적재는 하지 않는다(소스에 신호 없는 관계를 채우면 교수학
날조). 엣지 저작은 S4-01 소관이다. 또한 이 리포트는 **병합된 정본 `graph.json`만** 읽는다 —
S4-01 오버레이(`*_edges_university_v1.json`)는 검수 전 제안이라 합치지 않는다.

사용:
    python -m whymath_backend.harness.cross_school_connectivity_report
    python -m whymath_backend.harness.cross_school_connectivity_report --json out/cross_school.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from whymath_backend.l2.prerequisite_recommendation import MAX_PREREQUISITE_DEPTH

__all__ = [
    "DEFAULT_CORPUS_PATH",
    "DEPTH_BUDGETS",
    "SCHOOL_LEVEL_ORDER",
    "ConnectivityReport",
    "CorpusGraph",
    "ReachCell",
    "build_report",
    "dump_json",
    "load_corpus_graph",
    "main",
    "render_report",
    "report_to_json",
]

_EXIT_OK = 0
_EXIT_INPUT_ERROR = 2

# harness→whymath_backend→backend→src→repo 루트(learning_path_orderability_report와 동일 관례).
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CORPUS_PATH = _REPO_ROOT / "data" / "corpus" / "atom_graph_v1" / "graph.json"

# 코퍼스 `edges[].relation` 리터럴 — data_pipeline cross-package import를 늘리지 않으려고
# 문자열로 둔다(learning_path_orderability_report와 같은 근거).
_RELATION_PREREQUISITE = "prerequisite"

# 학교급 서열(낮음→높음). 코퍼스 `concepts[].school_level` 리터럴과 동일하다.
SCHOOL_LEVEL_ORDER: tuple[str, ...] = ("초등", "중학", "고등", "대학")
_LEVEL_RANK: Mapping[str, int] = {level: i for i, level in enumerate(SCHOOL_LEVEL_ORDER)}
_UNKNOWN = "미상"

# 소스 `relation_subtype` 중 경계를 뜻하는 라벨 둘 — 부수 기록 전용(판정 권위 아님).
_BOUNDARY_SUBTYPE_LABELS: tuple[str, ...] = ("학년간", "학교급간(추정)")

# 깊이 축 — `MAX_PREREQUISITE_DEPTH`는 재귀 CTE 예산의 단일 출처(하드코딩 5 금지).
DEPTH_BUDGETS: tuple[int, ...] = (1, 2, MAX_PREREQUISITE_DEPTH)


# ──────────────────────────────────────────────────────────────────────────
# 로더 — 코퍼스 JSON → 최소 투영(정직 실패)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class _Concept:
    code: str
    school_level: str | None
    grade_band: str | None


@dataclass(slots=True, frozen=True)
class _Edge:
    from_code: str
    to_code: str
    school_link: bool | None  # None = 소스에 플래그 필드 없음(미측정)
    relation_subtype: str | None


@dataclass(slots=True, frozen=True)
class CorpusGraph:
    """원자 백본 코퍼스 투영 — 이 리포트 집계에 필요한 최소 뷰.

    `edges`는 `relation == "prerequisite"`만(원자 백본 v1은 전량 prerequisite이나 방어적으로
    필터한다). 모든 엣지 끝점은 `concepts`에 실재함이 로더에서 보증된다.
    """

    concepts: tuple[_Concept, ...]
    edges: tuple[_Edge, ...]


def _opt_str(item: Mapping[str, object], key: str) -> str | None:
    value = item.get(key)
    return value if isinstance(value, str) and value else None


def load_corpus_graph(payload: object) -> CorpusGraph:
    """atom_graph_v1 `graph.json`(dict) → `CorpusGraph`.

    Raises:
        ValueError: 최상위가 dict가 아니거나 `concepts`/`edges` 배열 부재·행 형식 오류·중복
            code·끝점이 개념에 없는 엣지(학교급을 모른 채 경계 판정 불가 — 조용히 건너뛰면
            분모가 줄어 경계 밀도가 거짓으로 보인다).
    """
    if not isinstance(payload, dict):
        raise ValueError(f"graph.json 최상위가 object가 아님(type={type(payload).__name__})")

    raw_concepts = payload.get("concepts")
    if not isinstance(raw_concepts, list):
        raise ValueError("graph.json에 'concepts' 배열이 없음")
    concepts: list[_Concept] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw_concepts):
        if not isinstance(item, dict):
            raise ValueError(f"concepts[{idx}]가 object가 아님(type={type(item).__name__})")
        code = item.get("code")
        if not isinstance(code, str) or not code:
            raise ValueError(f"concepts[{idx}]에 code 문자열이 없음")
        if code in seen:
            raise ValueError(f"concepts[{idx}] code 중복: {code}")
        seen.add(code)
        concepts.append(
            _Concept(code, _opt_str(item, "school_level"), _opt_str(item, "grade_band"))
        )

    raw_edges = payload.get("edges")
    if not isinstance(raw_edges, list):
        raise ValueError("graph.json에 'edges' 배열이 없음")
    edges: list[_Edge] = []
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
        if from_code not in seen or to_code not in seen:
            raise ValueError(f"edges[{idx}] 끝점이 concepts에 없음: {from_code} → {to_code}")
        flag = item.get("school_link")
        edges.append(
            _Edge(
                from_code,
                to_code,
                flag if isinstance(flag, bool) else None,
                _opt_str(item, "relation_subtype"),
            )
        )
    return CorpusGraph(concepts=tuple(concepts), edges=tuple(edges))


# ──────────────────────────────────────────────────────────────────────────
# 집계 — 순수 코어
# ──────────────────────────────────────────────────────────────────────────
def _level_label(level: str | None) -> str:
    return level if level is not None else _UNKNOWN


def _pair_sort_key(pair: tuple[str, str]) -> tuple[int, int]:
    unknown_rank = len(SCHOOL_LEVEL_ORDER)
    return (_LEVEL_RANK.get(pair[0], unknown_rank), _LEVEL_RANK.get(pair[1], unknown_rank))


@dataclass(slots=True, frozen=True)
class ReachCell:
    """(출발 학교급 → 도달 대상 하위 학교급) 1행 — 출발 노드 중 선수 사슬을 거슬러 대상 학교급
    노드에 닿는 수. `reached_within[i]`는 `DEPTH_BUDGETS[i]` 홉 이내, `reached_any`는 무제한."""

    start_level: str
    target_level: str
    population: int
    reached_within: tuple[int, ...]
    reached_any: int

    def rate_within(self, index: int) -> float | None:
        return None if self.population == 0 else self.reached_within[index] / self.population

    @property
    def rate_any(self) -> float | None:
        return None if self.population == 0 else self.reached_any / self.population


def _build_pred(graph: CorpusGraph) -> dict[str, tuple[str, ...]]:
    pred: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        pred[edge.to_code].add(edge.from_code)
    return {k: tuple(sorted(v)) for k, v in pred.items()}


def _first_hit_hops(
    start: str,
    pred: Mapping[str, Sequence[str]],
    level_of: Mapping[str, str | None],
) -> dict[str, int]:
    """`start`에서 선수(pred) 방향 BFS — 학교급별로 처음 닿는 홉 수.

    BFS 층 순서라 먼저 기록된 값이 최단 홉이다. 경로는 어떤 학교급 노드든 통과할 수 있다(예:
    대학→고등→중학). 방문 집합으로 사이클에도 종료한다. 어느 학교급을 도달 대상으로 읽을지는
    호출부(`_reach_cells`)가 정한다 — 여기서는 닿은 모든 학교급을 기록만 한다.
    """
    first: dict[str, int] = {}
    visited = {start}
    frontier = [start]
    hop = 0
    while frontier:
        hop += 1
        nxt: list[str] = []
        for node in frontier:
            for p in pred.get(node, ()):
                if p in visited:
                    continue
                visited.add(p)
                nxt.append(p)
                level = level_of[p]
                if level is not None:
                    first.setdefault(level, hop)
        frontier = nxt
    return first


def _reach_cells(graph: CorpusGraph) -> tuple[ReachCell, ...]:
    pred = _build_pred(graph)
    level_of = {c.code: c.school_level for c in graph.concepts}
    starts: dict[str, list[str]] = defaultdict(list)
    for concept in graph.concepts:
        if concept.school_level is not None and concept.school_level in _LEVEL_RANK:
            starts[concept.school_level].append(concept.code)

    cells: list[ReachCell] = []
    for start_level in SCHOOL_LEVEL_ORDER:
        start_rank = _LEVEL_RANK[start_level]
        codes = starts.get(start_level, [])
        hits: dict[str, list[int]] = defaultdict(list)  # target_level → 노드별 최단 홉
        for code in codes:
            for target_level, hop in _first_hit_hops(code, pred, level_of).items():
                hits[target_level].append(hop)
        for target_level in SCHOOL_LEVEL_ORDER[:start_rank]:
            hops = hits.get(target_level, [])
            cells.append(
                ReachCell(
                    start_level=start_level,
                    target_level=target_level,
                    population=len(codes),
                    reached_within=tuple(sum(1 for h in hops if h <= d) for d in DEPTH_BUDGETS),
                    reached_any=len(hops),
                )
            )
    return tuple(cells)


@dataclass(slots=True, frozen=True)
class ConnectivityReport:
    """CUR-06 산출 전량(불변·렌더/직렬화의 단일 입력).

    `boundary_edge_total`은 양끝점 학교급이 다른 엣지(학교급을 모르는 끝점이 낀 엣지 포함 —
    모르는 것을 같은 학교급으로 접지 않는다)이고, `backward_boundary_total`은 그중 선수가 후행보다
    *높은* 학교급인 역방향 엣지다(정상 코퍼스에선 0).
    """

    concept_total: int
    edge_total: int
    level_pair_counts: Mapping[tuple[str, str], int]
    intra_level_total: int
    boundary_edge_total: int
    backward_boundary_total: int
    grade_band_pair_counts: Mapping[tuple[str, str], int]
    grade_band_unknown_edge_total: int
    flag_known_total: int  # school_link 필드가 있는 엣지 수(0이면 이중 확인 불가)
    flag_both: int
    flag_only: int
    endpoint_only: int
    flagged_subtype_counts: Mapping[str, int]
    boundary_label_total: int  # relation_subtype ∈ {학년간, 학교급간(추정)} 엣지 수
    reach_cells: tuple[ReachCell, ...]

    @property
    def boundary_rate(self) -> float | None:
        return None if self.edge_total == 0 else self.boundary_edge_total / self.edge_total


def build_report(graph: CorpusGraph) -> ConnectivityReport:
    """코퍼스 → 리포트(순수 함수·입력 순서에 무관한 결정론)."""
    level_of = {c.code: c.school_level for c in graph.concepts}
    band_of = {c.code: c.grade_band for c in graph.concepts}

    pair_counts: Counter[tuple[str, str]] = Counter()
    band_pairs: Counter[tuple[str, str]] = Counter()
    subtype_flagged: Counter[str] = Counter()
    intra = boundary = backward = band_unknown = 0
    flag_known = both = flag_only = endpoint_only = label_total = 0

    for edge in graph.edges:
        a, b = level_of[edge.from_code], level_of[edge.to_code]
        pair_counts[(_level_label(a), _level_label(b))] += 1
        is_boundary = a != b
        if is_boundary:
            boundary += 1
            rank_a = _LEVEL_RANK.get(a) if a is not None else None
            rank_b = _LEVEL_RANK.get(b) if b is not None else None
            if rank_a is not None and rank_b is not None and rank_a > rank_b:
                backward += 1
        else:
            intra += 1

        band_a, band_b = band_of[edge.from_code], band_of[edge.to_code]
        if band_a is None or band_b is None:
            band_unknown += 1
        elif band_a != band_b:
            band_pairs[(band_a, band_b)] += 1

        if edge.school_link is not None:
            flag_known += 1
            if edge.school_link and is_boundary:
                both += 1
            elif edge.school_link:
                flag_only += 1
            elif is_boundary:
                endpoint_only += 1
            if edge.school_link:
                subtype_flagged[edge.relation_subtype or _UNKNOWN] += 1
        if edge.relation_subtype in _BOUNDARY_SUBTYPE_LABELS:
            label_total += 1

    return ConnectivityReport(
        concept_total=len(graph.concepts),
        edge_total=len(graph.edges),
        level_pair_counts=dict(sorted(pair_counts.items(), key=lambda kv: _pair_sort_key(kv[0]))),
        intra_level_total=intra,
        boundary_edge_total=boundary,
        backward_boundary_total=backward,
        grade_band_pair_counts=dict(sorted(band_pairs.items())),
        grade_band_unknown_edge_total=band_unknown,
        flag_known_total=flag_known,
        flag_both=both,
        flag_only=flag_only,
        endpoint_only=endpoint_only,
        flagged_subtype_counts=dict(sorted(subtype_flagged.items())),
        boundary_label_total=label_total,
        reach_cells=_reach_cells(graph),
    )


# ──────────────────────────────────────────────────────────────────────────
# 렌더·직렬화
# ──────────────────────────────────────────────────────────────────────────
def _pct(num: int, den: int) -> str:
    return "n/a" if den == 0 else f"{num / den * 100:.1f}%"


def render_report(report: ConnectivityReport) -> str:
    """사람용 Markdown 리포트."""
    lines = [
        "# 학교급 경계 선수 연결 밀도 관측 리포트 (CUR-06 D6)",
        "",
        "병합된 정본 `graph.json`만 읽는 빌드타임 관측이다. **게이트가 아니다** —",
        "경계 밀도가 0이어도 exit 1을 내지 않는다(0=성공·2=입력 오류).",
        "S4-01 오버레이(검수 전 제안)는 합치지 않는다.",
        "",
        f"- 개념 노드 **{report.concept_total}** · prerequisite 엣지 **{report.edge_total}**",
        f"- 같은 학교급 내부 **{report.intra_level_total}** · 학교급 경계 통과 "
        f"**{report.boundary_edge_total}** ({_pct(report.boundary_edge_total, report.edge_total)})"
        f" · 역방향 경계 {report.backward_boundary_total}",
        "",
        "## 1. 학교급 쌍별 엣지 밀도 (선수 → 후행)",
        "",
        "| 선수 | 후행 | 엣지 | 구분 |",
        "|---|---|---:|---|",
    ]
    for (frm, to), n in report.level_pair_counts.items():
        lines.append(f"| {frm} | {to} | {n} | {'내부' if frm == to else '**경계**'} |")
    in_band = report.grade_band_pair_counts
    lines += [
        "",
        "## 2. 학년군 경계 (양끝점 학년군이 둘 다 있고 서로 다른 엣지)",
        "",
        "- 학년군을 모르는 끝점이 낀 엣지(경계 여부 판정 불가): "
        f"**{report.grade_band_unknown_edge_total}**",
        "",
        "| 선수 학년군 | 후행 학년군 | 엣지 |",
        "|---|---|---:|",
    ]
    for (frm, to), n in in_band.items():
        lines.append(f"| {frm} | {to} | {n} |")
    if report.flag_known_total == 0:
        flag_line = "- 소스에 `school_link` 필드가 없어 이중 확인 **불가**(양끝점 유도만 유효)."
    else:
        flag_line = (
            f"- `school_link` 플래그 vs 양끝점 유도: 일치(both) **{report.flag_both}** · "
            f"플래그만 **{report.flag_only}** · 양끝점만 **{report.endpoint_only}**"
            + (
                ""
                if report.flag_only == report.endpoint_only == 0
                else " ⚠️ 불일치 — 코퍼스 재점검"
            )
        )
    subtype = ", ".join(f"{k} {v}" for k, v in report.flagged_subtype_counts.items()) or "없음"
    label_gap = report.boundary_edge_total - report.boundary_label_total
    lines += [
        "",
        "## 3. 경계 표시 이중 확인",
        "",
        flag_line,
        f"- 플래그 엣지의 `relation_subtype` 분포: {subtype}",
        f"- 경계 라벨(학년간·학교급간(추정)) 합 **{report.boundary_label_total}** vs 경계 "
        f"{report.boundary_edge_total} (차 {label_gap:+d}) — 코퍼스 내부 라벨 불일치 기록용. "
        "판정 권위는 플래그+양끝점이다.",
        "",
        "## 4. 하향 도달 가능 비율 (상위 학교급 노드 출발 → 선수 사슬을 거슬러 하위 학교급 도달)",
        "",
        "분모는 출발 학교급의 전체 노드다. 선수가 없는 뿌리 노드도 포함 — 도달 못 하는 것이 곧",
        "관측하려는 사실이다. **고등 → 중학** 행이 MVP 페르소나 A(고3)의 결손 복구 경로다.",
        "",
        "| 출발 | 도달 대상 | 노드 | "
        + " | ".join(f"≤{d}홉" for d in DEPTH_BUDGETS)
        + " | 무제한 |",
        "|---|---|---:|" + "---:|" * (len(DEPTH_BUDGETS) + 1),
    ]
    for cell in report.reach_cells:
        mark = "**" if (cell.start_level, cell.target_level) == ("고등", "중학") else ""
        within = " | ".join(
            f"{mark}{n}/{cell.population} ({_pct(n, cell.population)}){mark}"
            for n in cell.reached_within
        )
        lines.append(
            f"| {mark}{cell.start_level}{mark} | {mark}{cell.target_level}{mark} | "
            f"{cell.population} | {within} | "
            f"{mark}{cell.reached_any}/{cell.population} "
            f"({_pct(cell.reached_any, cell.population)}){mark} |"
        )
    lines.append("")
    return "\n".join(lines)


def report_to_json(report: ConnectivityReport) -> dict[str, Any]:
    """리포트 → JSON 직렬화 가능 dict(키 정렬은 dump 시 `sort_keys=True`로 고정)."""
    return {
        "concept_total": report.concept_total,
        "edge_total": report.edge_total,
        "intra_level_total": report.intra_level_total,
        "boundary_edge_total": report.boundary_edge_total,
        "boundary_rate": report.boundary_rate,
        "backward_boundary_total": report.backward_boundary_total,
        "level_pair_counts": [
            {"from": f, "to": t, "edges": n} for (f, t), n in report.level_pair_counts.items()
        ],
        "grade_band_pair_counts": [
            {"from": f, "to": t, "edges": n} for (f, t), n in report.grade_band_pair_counts.items()
        ],
        "grade_band_unknown_edge_total": report.grade_band_unknown_edge_total,
        "school_link_check": {
            "flag_known_total": report.flag_known_total,
            "both": report.flag_both,
            "flag_only": report.flag_only,
            "endpoint_only": report.endpoint_only,
            "flagged_subtype_counts": dict(report.flagged_subtype_counts),
            "boundary_label_total": report.boundary_label_total,
        },
        "depth_budgets": list(DEPTH_BUDGETS),
        "reach": [
            {
                "start_level": c.start_level,
                "target_level": c.target_level,
                "population": c.population,
                "reached_within": dict(zip(map(str, DEPTH_BUDGETS), c.reached_within, strict=True)),
                "reached_any": c.reached_any,
                "rate_any": c.rate_any,
            }
            for c in report.reach_cells
        ],
        "is_gate": False,
    }


def dump_json(report: ConnectivityReport) -> str:
    return json.dumps(report_to_json(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# ──────────────────────────────────────────────────────────────────────────
# CLI (얇은 껍데기 — 경로 해석·입출력만, 집계는 위 순수 코어)
# ──────────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 리포트를 stdout에 출력. **0=성공 / 2=입력 오류**(1 없음).

    경계 밀도가 낮아도(심지어 0이어도) exit 0이다(게이트 아님). exit 2는 코퍼스 자체를 읽을 수
    없는 입력 오류에만 쓴다.
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.cross_school_connectivity_report",
        description=(
            "학교급 경계 선수 연결 밀도 관측 리포트(CUR-06 D6) — 학교급 쌍별 밀도·학년군 경계·"
            "school_link 이중 확인·하향 도달 가능 비율. 결정론·게이트 아님(exit 0/2)."
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
