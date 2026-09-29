"""개념 그래프 traversal 성능 예산 실부하 판정 — 전 앵커 전수 측정 CLI (S4-01 슬라이스 2).

무엇을 판정하나
───────────────
S4-01 acceptance 원문의 "traversal 성능 예산 실부하 통과"를 *측정 가능한 판정*으로 바꾼다.
예산 가드(`l2.recommendation_policy.ConceptGraphBudget` — 깊이 ≤ 2 · 노드 ≤ 20 · 시간 2.0초)는
코드로 존재했지만, 그 가드가 **전 그래프 규모에서** 실제로 어느 정도 여유를 두고 버티는지는 한 번도
측정된 적이 없었다. "가드가 있다"와 "실부하에서 통과한다"는 다른 주장이다.

측정 대상 = 서빙 경로에서 `concept_edge`를 읽는 탐색 형태 3종(2026-09-28 전수 조사 기준):

  ① `policy_prerequisites` — `/v1/me/next-problem` 정책 경로. `_budgeted_prerequisites`
     (깊이 2·시간 2.0초) + `_apply_node_budget`(노드 20). **실제 함수를 그대로 부른다.**
  ② `policy_successors` — 같은 정책의 직접 후행 1-hop. `load_direct_successors`(노드 20) +
     `_within_budget`(시간 2.0초).
  ③ `route_prerequisites_depth5` — `/v1/me/weak-concepts/{id}/*` 라우트가 허용하는 최대 깊이
     (`MAX_PREREQUISITE_DEPTH`=5)의 선수 탐색. **이 라우트에는 시간 예산이 없다** — 그래서 정책과
     같은 2.0초를 *참조 기준*으로 삼아 측정만 한다(예산을 거는 일은 별도 태스크의 몫이다).

판정 (exit code — CLAUDE.md "게이트 판정은 항상 CLI exit 0/1"):

  * exit 0 — 전 앵커 × 전 형태 × 전 동시성 수준에서 ⓐ 시간 예산(2.0초) 초과 0건 ⓑ 시간 초과·
    예외 0건 ⓒ **DB가 돌려준 결과 집합이 `graph.json` 구조 전수 계산과 앵커마다 일치**.
  * exit 1 — 위 셋 중 하나라도 위반.
  * exit 2 — **측정 불성립**: 앵커 0건, DB 개념·엣지가 코퍼스와 다름(드리프트), DB 접속 실패,
    입력 오류. "0건 측정"을 "0건 위반"으로 위장하지 않는다(CLAUDE.md "스캔 0건은 실패").

ⓒ가 이 도구의 변별력이다. 지연만 재면 "빈 결과를 빨리 돌려준" 회귀(엣지 적재 누락·조인 조건
오류)도 통과한다. 결과 집합을 DB와 무관한 독립 계산(순수 파이썬 · `graph.json`)과 앵커마다
대조하므로, 탐색이 **빠르고 옳다**는 두 주장을 같이 판정한다.

표본이 아니라 전수다 — 모집단(DB의 전 개념) 전체를 재므로 비율에 Wilson 경계를 씌우지 않는다.
판정 대상 비율(초과·불일치)은 전부 0건 기준이다.

구조 전수 계산(DB 불요)
──────────────────────
`--structural-only`는 DB 없이 `graph.json`만으로 앵커마다 ⓐ CTE가 만들어 낼 원시 행 수(경로 수
— `UNION ALL`이라 diamond에서 중복 행이 생긴다) ⓑ 중복 제거 후 선수 수 ⓒ 직접 후행 수를 전수로
센다. `--extra-edges`로 **아직 병합되지 않은 제안 엣지 파일**을 겹쳐 병합 후 부하를 미리 계산할 수
있다(S4-60 병합 판단 입력). 제안 엣지는 DB에 없으므로 DB 측정과는 함께 쓸 수 없다(exit 2).

"작동한 비율" 원칙(CLAUDE.md)에 따라 예산이 **실제로 잘라 낸** 앵커 수(노드 상한 발동 수)도
보고한다 — 현재 규모에서 가드가 한 번도 발동하지 않는다면 그것도 사실로 적는다.

CLI::

    python -m whymath_backend.harness.traversal_load_probe \\
        --graph data/corpus/atom_graph_v1/graph.json --concurrency 1,8 --out report.json
    python -m whymath_backend.harness.traversal_load_probe --structural-only \\
        --extra-edges data/corpus/atom_graph_v1/cross_band_edges_university_v1.json

접속은 `Settings.database_url`(env `WHYMATH_DATABASE_URL`) — 자격증명 하드코딩 0. 읽기 전용이다
(쓰기 쿼리 0 — 적재는 `l1.atom_graph.populate`가 먼저 해 둬야 한다).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from whymath_backend.l1.atom_graph.atom_backend_concept import load_atom_concepts_from_graph_json
from whymath_backend.l1.atom_graph.atom_backend_edge import load_atom_edges_from_graph_json
from whymath_backend.l2.next_problem_selection import load_direct_successors
from whymath_backend.l2.prerequisite_recommendation import (
    MAX_PREREQUISITE_DEPTH,
    MAX_PREREQUISITE_NODES,
    fetch_prerequisites,
)

# 정책 경로의 *실제* 함수를 부른다 — 복제하면 측정 대상이 서빙 코드와 조용히 갈라진다.
from whymath_backend.l2.recommendation_policy import (
    DEFAULT_GRAPH_BUDGET,
    ConceptGraphBudget,
    _apply_node_budget,
    _budgeted_prerequisites,
    _within_budget,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_logger = logging.getLogger("whymath.harness.traversal_load_probe")

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_INVALID = 2

DEFAULT_GRAPH = Path("data/corpus/atom_graph_v1/graph.json")
DEFAULT_CONCURRENCY: tuple[int, ...] = (1, 8)

#: 구조 계산의 깊이 축 — 정책 1·2 + 라우트 최대(`MAX_PREREQUISITE_DEPTH`, 단일 출처 재사용).
STRUCTURAL_DEPTHS: tuple[int, ...] = (1, DEFAULT_GRAPH_BUDGET.max_depth, MAX_PREREQUISITE_DEPTH)

#: 측정 도구 자신의 정지 장치 — 예산 없는 라우트(③)가 매달려도 프로브는 끝나야 한다. 이 값에
#: 걸린 호출은 `timeouts`로 계상되어 판정을 FAIL로 만든다(측정 실패가 통과로 위장되지 않는다).
PROBE_HARD_CEILING_SECONDS = 30.0

#: 구조 계산 경로 수 폭발 방어 — `UNION ALL` 경로 수는 깊이에 대해 지수적으로 늘 수 있다.
#: 이 값을 넘는 앵커가 나오면 계산을 멈추고 그 사실 자체를 오류로 보고한다(조용한 절단 금지).
RAW_ROW_GUARD = 1_000_000

#: 불일치 예시 보고 상한 — 리포트가 수천 줄로 불어나지 않게(건수는 전수로 센다).
_MISMATCH_EXAMPLES = 5


class StructuralExplosionError(RuntimeError):
    """구조 계산의 원시 경로 수가 `RAW_ROW_GUARD`를 넘었다 — 그래프 폭발 신호."""


# ─────────────────────────────────────────────────────────────────────────
# 구조 전수 계산 (DB 불요 · 순수)
# ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GraphIndex:
    """선수 그래프 인접 색인 — DB 적재기와 같은 필터(선수만·self-edge 제외·중복 쌍 1건)."""

    codes: frozenset[str]
    preds: Mapping[str, tuple[str, ...]]  # 후행 code → 직접 선수 code들
    succs: Mapping[str, tuple[str, ...]]  # 선수 code → 직접 후행 code들
    edge_count: int
    orphan_edges: int  # 양끝 중 하나가 노드 집합 밖이라 버린 엣지 수(적재기의 orphan skip과 동형)


def build_index(codes: Iterable[str], edges: Iterable[tuple[str, str]]) -> GraphIndex:
    """노드 code 집합 + (선수, 후행) 쌍 → 색인. DB `UNIQUE(from, to, edge_type)`대로 쌍 dedup."""
    code_set = frozenset(codes)
    pairs: set[tuple[str, str]] = set()
    orphan = 0
    for src, dst in edges:
        if src == dst:
            continue
        if src not in code_set or dst not in code_set:
            orphan += 1
            continue
        pairs.add((src, dst))
    preds: dict[str, list[str]] = {}
    succs: dict[str, list[str]] = {}
    for src, dst in sorted(pairs):
        preds.setdefault(dst, []).append(src)
        succs.setdefault(src, []).append(dst)
    return GraphIndex(
        codes=code_set,
        preds={k: tuple(v) for k, v in preds.items()},
        succs={k: tuple(v) for k, v in succs.items()},
        edge_count=len(pairs),
        orphan_edges=orphan,
    )


def load_index(graph_path: Path, extra_edge_paths: Sequence[Path] = ()) -> GraphIndex:
    """`graph.json`(+ 제안 엣지 파일들) → 색인. 적재기와 **같은 로더**로 읽어 필터를 공유한다."""
    concepts = load_atom_concepts_from_graph_json(graph_path)
    edge_records, _ = load_atom_edges_from_graph_json(graph_path)
    pairs = [(r.from_code, r.to_code) for r in edge_records]
    for extra in extra_edge_paths:
        extra_records, _ = load_atom_edges_from_graph_json(extra)
        pairs.extend((r.from_code, r.to_code) for r in extra_records)
    return build_index((c.code for c in concepts), pairs)


@dataclass(frozen=True)
class PrerequisiteTrace:
    """앵커 1개의 깊이 제한 선수 탐색 구조값."""

    raw_rows: int  # 재귀 CTE(`UNION ALL`)가 만들어 낼 행 수 = 길이 ≤ depth 경로 수
    ancestors: frozenset[str]  # 중복 제거 후 선수 code 집합(앵커 자신 제외)


def trace_prerequisites(index: GraphIndex, code: str, max_depth: int) -> PrerequisiteTrace:
    """`build_prerequisite_stmt`의 재귀 CTE 의미를 그대로 따른다 — 깊이마다 직전 행의 선수를 편다.

    CTE는 `UNION ALL`이라 같은 선수가 여러 경로로 오면 **행이 경로 수만큼** 생긴다. 그 수가
    `raw_rows`이고, `fetch_prerequisites`가 파이썬에서 dedup한 뒤의 집합이 `ancestors`다.
    """
    level = list(index.preds.get(code, ()))
    raw = len(level)
    seen = set(level)
    for _ in range(max_depth - 1):
        level = [p for c in level for p in index.preds.get(c, ())]
        raw += len(level)
        if raw > RAW_ROW_GUARD:
            raise StructuralExplosionError(
                f"앵커 {code}의 깊이 {max_depth} 경로 수가 {RAW_ROW_GUARD}를 넘었다 — 그래프 폭발"
            )
        seen.update(level)
    seen.discard(code)
    return PrerequisiteTrace(raw_rows=raw, ancestors=frozenset(seen))


@dataclass(frozen=True)
class DepthCensus:
    """한 깊이에서 전 앵커를 센 결과."""

    depth: int
    anchors: int
    raw_rows_max: int
    raw_rows_max_anchor: str | None
    ancestors_max: int
    ancestors_max_anchor: str | None
    zero_prerequisite_anchors: int
    over_policy_nodes: int  # 중복 제거 후 > 정책 노드 예산(20) — 정책이 잘라 낼 앵커 수
    over_route_cap: int  # 중복 제거 후 > 라우트 노드 상한(64)


@dataclass(frozen=True)
class StructuralCensus:
    """전 앵커 구조 계산 — 깊이별 선수 + 직접 후행."""

    nodes: int
    edges: int
    orphan_edges: int
    depths: tuple[DepthCensus, ...]
    successors_max: int
    successors_max_anchor: str | None
    successors_over_policy_nodes: int


def structural_census(
    index: GraphIndex,
    *,
    depths: Sequence[int] = STRUCTURAL_DEPTHS,
    policy_nodes: int = DEFAULT_GRAPH_BUDGET.max_nodes,
    route_cap: int = MAX_PREREQUISITE_NODES,
) -> StructuralCensus:
    """전 앵커 × 깊이 축 구조 계산. 앵커 순서는 code 정렬(결정론 — 동률 최대는 첫 code)."""
    anchors = sorted(index.codes)
    per_depth: list[DepthCensus] = []
    for depth in depths:
        raw_max, raw_arg = -1, None
        anc_max, anc_arg = -1, None
        zero = over_policy = over_route = 0
        for code in anchors:
            trace = trace_prerequisites(index, code, depth)
            if trace.raw_rows > raw_max:
                raw_max, raw_arg = trace.raw_rows, code
            size = len(trace.ancestors)
            if size > anc_max:
                anc_max, anc_arg = size, code
            zero += size == 0
            over_policy += size > policy_nodes
            over_route += size > route_cap
        per_depth.append(
            DepthCensus(
                depth=depth,
                anchors=len(anchors),
                raw_rows_max=max(raw_max, 0),
                raw_rows_max_anchor=raw_arg,
                ancestors_max=max(anc_max, 0),
                ancestors_max_anchor=anc_arg,
                zero_prerequisite_anchors=zero,
                over_policy_nodes=over_policy,
                over_route_cap=over_route,
            )
        )
    succ_max, succ_arg = -1, None
    succ_over = 0
    for code in anchors:
        n = len(index.succs.get(code, ()))
        if n > succ_max:
            succ_max, succ_arg = n, code
        succ_over += n > policy_nodes
    return StructuralCensus(
        nodes=len(index.codes),
        edges=index.edge_count,
        orphan_edges=index.orphan_edges,
        depths=tuple(per_depth),
        successors_max=max(succ_max, 0),
        successors_max_anchor=succ_arg,
        successors_over_policy_nodes=succ_over,
    )


# ─────────────────────────────────────────────────────────────────────────
# 실 PG 측정
# ─────────────────────────────────────────────────────────────────────────

#: 탐색 형태 1개 = (세션, concept_id) → 결과 code 목록. 주입 가능하게 둬 판정 로직을 DB 없이
#: 결함 주입으로 검증한다(실 SQL은 CLI 실행·CI 배선이 검증한다).
TraversalCall = Callable[["AsyncSession", uuid.UUID], Awaitable[list[str]]]
#: 기대 결과 판정기 — (앵커 code, 결과 code 목록) → 불일치면 사유 문자열, 일치면 None.
ExpectationCheck = Callable[[str, list[str]], "str | None"]


@dataclass(frozen=True)
class TraversalShape:
    """측정할 탐색 형태 1종 — 호출 + 기대 결과 판정기 + 예산 성격."""

    name: str
    call: TraversalCall
    check: ExpectationCheck
    budgeted: bool  # True = 서빙 코드가 시간 예산을 건다 · False = 참조 기준으로만 측정


def _codes(rows: Iterable[Any]) -> list[str]:
    return [r.concept_code for r in rows if r.concept_code is not None]


def _subset_check(expected: Callable[[str], frozenset[str]], cap: int) -> ExpectationCheck:
    """결과가 기대 집합의 부분집합이고 길이가 `min(|기대|, cap)`이면 일치.

    상한(cap)이 걸리면 *어느* 원소가 남는지는 정렬 규칙의 몫이라 집합 동일성으로 판정할 수 없다 —
    그래서 "기대 밖 원소 0 + 개수 일치"로 판정한다. 상한 미발동이면 이 둘이 곧 집합 동일성이다.
    """

    def check(anchor: str, got: list[str]) -> str | None:
        want = expected(anchor)
        got_set = set(got)
        if len(got_set) != len(got):
            return f"중복 결과 {len(got) - len(got_set)}건"
        stray = got_set - want
        if stray:
            return f"기대 밖 결과 {len(stray)}건(예: {sorted(stray)[0]})"
        if len(got) != min(len(want), cap):
            return f"개수 불일치 — 결과 {len(got)} · 기대 {min(len(want), cap)}"
        return None

    return check


def build_shapes(index: GraphIndex, budget: ConceptGraphBudget) -> tuple[TraversalShape, ...]:
    """서빙 경로 탐색 형태 3종 — 기대 결과는 `index`(DB와 독립인 구조 계산)에서 온다."""
    anc_cache: dict[tuple[str, int], frozenset[str]] = {}

    def ancestors(depth: int) -> Callable[[str], frozenset[str]]:
        def get(code: str) -> frozenset[str]:
            key = (code, depth)
            if key not in anc_cache:
                anc_cache[key] = trace_prerequisites(index, code, depth).ancestors
            return anc_cache[key]

        return get

    def successors(code: str) -> frozenset[str]:
        return frozenset(index.succs.get(code, ()))

    async def policy_prerequisites(session: AsyncSession, cid: uuid.UUID) -> list[str]:
        rows = await _budgeted_prerequisites(session, cid, budget)
        return _codes(_apply_node_budget(rows, budget))

    async def policy_successors(session: AsyncSession, cid: uuid.UUID) -> list[str]:
        rows = await _within_budget(
            budget, lambda: load_direct_successors(session, cid, max_nodes=budget.max_nodes)
        )
        return [r.concept_code for r in rows]

    async def route_prerequisites(session: AsyncSession, cid: uuid.UUID) -> list[str]:
        # 라우트와 같은 호출 — 시간 예산 없음(측정 도구 자신의 정지 장치만 바깥에서 건다).
        rows = await fetch_prerequisites(session, cid, max_depth=MAX_PREREQUISITE_DEPTH)
        return _codes(rows)

    return (
        TraversalShape(
            name="policy_prerequisites",
            call=policy_prerequisites,
            check=_subset_check(ancestors(budget.max_depth), budget.max_nodes),
            budgeted=True,
        ),
        TraversalShape(
            name="policy_successors",
            call=policy_successors,
            check=_subset_check(successors, budget.max_nodes),
            budgeted=True,
        ),
        TraversalShape(
            name=f"route_prerequisites_depth{MAX_PREREQUISITE_DEPTH}",
            call=route_prerequisites,
            check=_subset_check(ancestors(MAX_PREREQUISITE_DEPTH), MAX_PREREQUISITE_NODES),
            budgeted=False,
        ),
    )


@dataclass
class ShapeMeasurement:
    """형태 1종 × 동시성 1수준의 전수 측정 결과."""

    shape: str
    budgeted: bool
    concurrency: int
    samples: int = 0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    max_ms: float = 0.0
    over_budget: int = 0  # 지연 > 시간 예산(참조 기준 포함)
    timeouts: int = 0  # 서빙 예산 또는 프로브 정지 장치에 걸린 호출
    errors: dict[str, int] = field(default_factory=dict)  # 예외 타입명 → 건수(값은 남기지 않음)
    mismatches: int = 0
    mismatch_examples: list[str] = field(default_factory=list)
    wall_seconds: float = 0.0


def percentile(values: Sequence[float], pct: float) -> float:
    """최근접 순위 백분위 — 빈 입력은 0.0(샘플 0건은 판정에서 따로 막는다)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[rank]


async def measure_shape(
    session_factory: Callable[[], Any],
    shape: TraversalShape,
    anchors: Sequence[tuple[uuid.UUID, str]],
    *,
    concurrency: int,
    budget_seconds: float,
    hard_ceiling_seconds: float = PROBE_HARD_CEILING_SECONDS,
) -> ShapeMeasurement:
    """앵커 전수를 `concurrency`개 워커(워커마다 세션 1개)로 나눠 측정한다."""
    result = ShapeMeasurement(shape=shape.name, budgeted=shape.budgeted, concurrency=concurrency)
    latencies: list[float] = []
    errors: Counter[str] = Counter()
    queue = list(anchors)
    queue.reverse()

    async def worker() -> None:
        async with session_factory() as session:
            while queue:
                cid, code = queue.pop()
                started = time.perf_counter()
                try:
                    async with asyncio.timeout(hard_ceiling_seconds):
                        got = await shape.call(session, cid)
                except TimeoutError:
                    result.timeouts += 1
                    latencies.append(time.perf_counter() - started)
                    continue
                except Exception as exc:  # noqa: BLE001 — 타입명으로 계상하고 FAIL로 만든다
                    errors[type(exc).__name__] += 1
                    _logger.warning("탐색 예외 — shape=%s 타입=%s", shape.name, type(exc).__name__)
                    await session.rollback()
                    continue
                latencies.append(time.perf_counter() - started)
                reason = shape.check(code, got)
                if reason is not None:
                    result.mismatches += 1
                    if len(result.mismatch_examples) < _MISMATCH_EXAMPLES:
                        result.mismatch_examples.append(f"{code}: {reason}")

    wall_started = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    result.wall_seconds = round(time.perf_counter() - wall_started, 3)
    result.samples = len(latencies)
    result.errors = dict(errors)
    result.p50_ms = round(percentile(latencies, 50) * 1000, 3)
    result.p95_ms = round(percentile(latencies, 95) * 1000, 3)
    result.p99_ms = round(percentile(latencies, 99) * 1000, 3)
    result.max_ms = round(max(latencies, default=0.0) * 1000, 3)
    result.over_budget = sum(1 for x in latencies if x > budget_seconds)
    return result


# ─────────────────────────────────────────────────────────────────────────
# 판정
# ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Coverage:
    """DB 모집단 ↔ 코퍼스 대조 — 측정 성립 조건."""

    db_concepts: int
    db_edges: int
    corpus_concepts: int
    corpus_edges: int
    missing_in_db: int  # 코퍼스에 있는데 DB에 없는 code 수
    extra_in_db: int  # DB에 있는데 코퍼스에 없는 code 수


def invalid_reasons(coverage: Coverage) -> list[str]:
    """측정이 성립하지 않는 사유 — 하나라도 있으면 exit 2(통과도 실패도 아니다)."""
    reasons: list[str] = []
    if coverage.db_concepts == 0:
        reasons.append("DB 개념 0건 — 적재(`l1.atom_graph.populate`) 전에 측정했다")
    if coverage.missing_in_db or coverage.extra_in_db:
        reasons.append(
            f"코퍼스 드리프트 — DB 누락 {coverage.missing_in_db} · DB 초과 {coverage.extra_in_db}"
        )
    if coverage.db_edges != coverage.corpus_edges:
        reasons.append(f"엣지 드리프트 — DB {coverage.db_edges} · 코퍼스 {coverage.corpus_edges}")
    return reasons


def fail_reasons(measurements: Sequence[ShapeMeasurement], *, expected_samples: int) -> list[str]:
    """판정 위반 사유 — 비면 PASS. 샘플 수가 앵커 수와 다르면 그것도 위반(조용한 누락 금지)."""
    reasons: list[str] = []
    if not measurements:
        reasons.append("측정 0건")
    for m in measurements:
        tag = f"{m.shape}@c{m.concurrency}"
        if m.samples != expected_samples:
            reasons.append(f"{tag}: 샘플 {m.samples} ≠ 앵커 {expected_samples}")
        if m.timeouts:
            reasons.append(f"{tag}: 시간 초과 {m.timeouts}건")
        if m.over_budget:
            reasons.append(f"{tag}: 시간 예산 초과 {m.over_budget}건")
        if m.errors:
            reasons.append(f"{tag}: 예외 {sum(m.errors.values())}건 {sorted(m.errors)}")
        if m.mismatches:
            reasons.append(f"{tag}: 결과 불일치 {m.mismatches}건 (예: {m.mismatch_examples[:1]})")
    return reasons


# ─────────────────────────────────────────────────────────────────────────
# 실행
# ─────────────────────────────────────────────────────────────────────────


def _write(out: Path | None, report: dict[str, Any]) -> None:
    """단계마다 즉시 저장 — 중간에 멈춰도 거기까지의 증거가 남는다."""
    if out is None:
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _census_json(census: StructuralCensus) -> dict[str, Any]:
    return asdict(census)


async def run_probe(
    database_url: str,
    index: GraphIndex,
    *,
    concurrency: Sequence[int],
    budget: ConceptGraphBudget = DEFAULT_GRAPH_BUDGET,
    out: Path | None = None,
) -> tuple[int, dict[str, Any]]:
    """실 PG 전수 측정 → (exit code, 리포트)."""
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from whymath_backend.db.models import Concept, ConceptEdge

    report: dict[str, Any] = {
        "verdict": "INCOMPLETE",
        "budget": asdict(budget),
        "route_max_depth": MAX_PREREQUISITE_DEPTH,
        "route_node_cap": MAX_PREREQUISITE_NODES,
        "concurrency": list(concurrency),
        "structural": _census_json(structural_census(index)),
        "measurements": [],
        "reasons": [],
    }
    _write(out, report)

    engine = create_async_engine(database_url, pool_size=max(concurrency), max_overflow=0)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as session:
                rows = (await session.execute(select(Concept.concept_id, Concept.code))).all()
                db_edges = (
                    await session.execute(select(func.count()).select_from(ConceptEdge))
                ).scalar_one()
        except Exception as exc:  # noqa: BLE001 — 접속 실패는 측정 불성립(exit 2)
            report["verdict"] = "INVALID"
            report["reasons"] = [f"DB 조회 실패 — {type(exc).__name__}"]
            _write(out, report)
            return EXIT_INVALID, report

        db_codes = {code for _, code in rows}
        coverage = Coverage(
            db_concepts=len(rows),
            db_edges=int(db_edges),
            corpus_concepts=len(index.codes),
            corpus_edges=index.edge_count,
            missing_in_db=len(index.codes - db_codes),
            extra_in_db=len(db_codes - index.codes),
        )
        report["coverage"] = asdict(coverage)
        invalid = invalid_reasons(coverage)
        if invalid:
            report["verdict"] = "INVALID"
            report["reasons"] = invalid
            _write(out, report)
            return EXIT_INVALID, report

        anchors = sorted(((cid, code) for cid, code in rows), key=lambda r: r[1])
        measurements: list[ShapeMeasurement] = []
        for shape in build_shapes(index, budget):
            for level in concurrency:
                m = await measure_shape(
                    sessions,
                    shape,
                    anchors,
                    concurrency=level,
                    budget_seconds=budget.timeout_seconds,
                )
                measurements.append(m)
                report["measurements"].append(asdict(m))
                _write(out, report)
                print(
                    f"  {m.shape:<28} c={m.concurrency:<3} n={m.samples} "
                    f"p50={m.p50_ms}ms p99={m.p99_ms}ms max={m.max_ms}ms "
                    f"초과={m.over_budget} 시간초과={m.timeouts} 예외={sum(m.errors.values())} "
                    f"불일치={m.mismatches}"
                )
    finally:
        await engine.dispose()

    reasons = fail_reasons(measurements, expected_samples=len(anchors))
    report["verdict"] = "FAIL" if reasons else "PASS"
    report["reasons"] = reasons
    worst = max((m.max_ms for m in measurements), default=0.0)
    report["headroom_ratio"] = round(budget.timeout_seconds * 1000 / worst, 1) if worst else None
    _write(out, report)
    return (EXIT_FAIL if reasons else EXIT_PASS), report


def _parse_concurrency(text: str) -> tuple[int, ...]:
    levels = tuple(int(x) for x in text.split(",") if x.strip())
    if not levels or any(x < 1 for x in levels):
        raise ValueError(f"동시성 수준은 1 이상 정수 목록이어야 한다: {text!r}")
    return levels


def _print_census(label: str, census: StructuralCensus) -> None:
    print(f"[구조 전수 · {label}] 노드 {census.nodes} · 엣지 {census.edges}")
    for d in census.depths:
        print(
            f"  깊이 {d.depth}: 원시행 최대 {d.raw_rows_max}({d.raw_rows_max_anchor}) · "
            f"선수 최대 {d.ancestors_max}({d.ancestors_max_anchor}) · 선수 0 앵커 "
            f"{d.zero_prerequisite_anchors} · 노드예산 초과 {d.over_policy_nodes} · "
            f"라우트상한 초과 {d.over_route_cap}"
        )
    print(
        f"  직접 후행: 최대 {census.successors_max}({census.successors_max_anchor}) · "
        f"노드예산 초과 {census.successors_over_policy_nodes}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="개념 그래프 traversal 성능 예산 실부하 판정 (S4-01 슬라이스 2)"
    )
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument(
        "--extra-edges",
        type=Path,
        action="append",
        default=[],
        help="병합 전 제안 엣지 파일(구조 계산 전용 — --structural-only와 함께만)",
    )
    parser.add_argument("--structural-only", action="store_true", help="DB 없이 구조 계산만")
    parser.add_argument("--concurrency", default=",".join(map(str, DEFAULT_CONCURRENCY)))
    parser.add_argument("--database-url", default=None, help="기본 = Settings.database_url")
    parser.add_argument("--out", type=Path, default=None, help="JSON 리포트 경로(단계마다 갱신)")
    args = parser.parse_args(argv)

    try:
        concurrency = _parse_concurrency(args.concurrency)
        if args.extra_edges and not args.structural_only:
            raise ValueError("--extra-edges는 DB에 없는 엣지라 --structural-only와 함께만 쓴다")
        index = load_index(args.graph)
    except (OSError, ValueError) as exc:
        print(f"[입력 오류] {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_INVALID

    if args.structural_only:
        try:
            base = structural_census(index)
            _print_census("코퍼스", base)
            report: dict[str, Any] = {"structural": _census_json(base)}
            if args.extra_edges:
                merged = structural_census(load_index(args.graph, args.extra_edges))
                _print_census("코퍼스 + 제안 엣지", merged)
                report["structural_with_extra_edges"] = _census_json(merged)
        except (OSError, ValueError, StructuralExplosionError) as exc:
            print(f"[구조 계산 실패] {type(exc).__name__}: {exc}", file=sys.stderr)
            return EXIT_INVALID
        _write(args.out, report)
        return EXIT_PASS

    if args.database_url is None:
        from whymath_backend.config import get_settings

        database_url = get_settings().database_url
    else:
        database_url = args.database_url

    code, report = asyncio.run(
        run_probe(database_url, index, concurrency=concurrency, out=args.out)
    )
    print(f"[판정] {report['verdict']} (exit {code}) · 헤드룸 {report.get('headroom_ratio')}배")
    for reason in report["reasons"]:
        print(f"  - {reason}")
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
