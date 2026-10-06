#!/usr/bin/env python3
"""작업 흐름 그래프 — 프로젝트의 진행 중 작업을 "창(윈도우)"으로, 선후 관계를 "연결선"으로
한 캔버스에 통합해 그린다 (HARN-182).

작업 보드(board.py)가 *상태별 칸반*이라면 이 모듈은 *선후 관계 지도*다. 칸반은 "무엇이 막혔나"는
보여 주지만 "무엇이 끝나면 무엇이 풀리나"는 보여 주지 못한다 — 그 흐름은 태스크 YAML의
depends_on·requires_gates, 게이트의 depends_on, 트랙 entry_gate, 그리고 **저장소 밖**(다른
브랜치의 완료분·원격 claim)에 흩어져 있다. 이 모듈은 그것들을 한데 모아 노드 편집기처럼 그린다.

세 종류의 창(Kiki 지시 2026-09-27 — 열린 작업·사람 작업·미머지 작업의 통합):
    · 작업 창   — 열린 태스크(todo·in_progress·review·blocked). 사람 소유 태스크는 "사람 작업"
    · 게이트 창 — 미통과 게이트(pending). 상태는 셋: 여는 작업이 남았다(선행 작업 대기) ·
                  입력은 끝났는데 판정 기록이 빠졌다(판정 결과 미기록) · 담당자 차례(사람
                  차례). 판정 결과 미기록은 사람 차례가 아니다(HARN-184 — store.gate_wait_kind)
    · 브랜치 창 — 트렁크에 아직 흡수되지 않은 원격 브랜치 = 미머지 작업. 그 브랜치가 어떤
                  태스크를 done으로 들고 있는지(미머지 완료분), 어떤 태스크를 claim 중인지
                  (다른 세션의 진행), 고립/PR 제출/PR 닫힘 판정을 싣는다
    선후 관계 = 창 오른쪽 출력 포트 → 다음 창 왼쪽 입력 포트로 잇는 연결선. 브랜치 창은
    그 브랜치가 들고 있는 태스크 창의 **선행**이다(브랜치를 머지하면 그 태스크가 풀린다).
    서로 이어진 창 묶음 = "흐름" 프레임, 이어진 것이 없는 창 = 상태별 그룹 프레임.
    전부 한 캔버스 — 끌어 이동·확대 축소·창 끌어 옮기기·미니맵은 화면(work_graph_page.html) 몫.

사용:
    python3 scripts/harness/work_graph.py                    # work/graph.html 생성
    python3 scripts/harness/work_graph.py --out <경로>
    python3 scripts/harness/work_graph.py --json             # 페이로드만 표준출력
    python3 scripts/harness/work_graph.py --text             # 터미널 축약 요약만
    python3 scripts/harness/work_graph.py --out <경로> --fragment   # 문서 껍데기 없는 조각
    python3 scripts/harness/work_graph.py --no-remote        # 원격 조회 생략(판정 불가로 표기)

설계 원칙 (board.py와 같다):
    · 판정 로직 무복제 — 작업 창 상태는 board.build_tasks(=selector.classify_todo)·
      board.apply_remote_done, 원격 claim은 selector.classify_todo(remote_claimed=…), 태스크·게이트
      간선은 store.dependency_graph, 해금 수는 selector.unblock_counts, 대기 경로는
      selector.wait_chain, 게이트 창 상태는 store.gate_wait_kind(판정 기록 상태는 그 안의
      store.gate_judgment_state), 정렬은 selector.sort_key,
      미머지 완료분·원격 claim·고립 브랜치는 remote_claims의 스캔 결과를 그대로 쓴다.
      이 모듈이 새로 만드는 것은 **브랜치 창의 조립, 배치(좌표), 화면**뿐이다.
    · 판정 불가는 숨기지 않는다 — 원격 스캔 3종의 상태가 `ok`가 아니면 페이로드·화면 배너·
      터미널 요약이 전부 그 사실을 말한다(빈 결과 ≠ 없음).
    · 의존성 0 — 표준 라이브러리만. 산출 HTML도 자기완결(외부 CDN·폰트 요청 없음).
    · 읽기 전용 — 백로그 파일을 일절 쓰지 않는다(상태 변경 창구는 backlog.py CLI 단독).
    · 결정적 — 같은 입력이면 같은 좌표가 나온다(모든 정렬 키에 ID를 포함).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import board
import remote_claims
import report
import selector
import store
from models import TERMINAL_STATUSES, Backlog, Gate, Task

Node = store.Node
BRANCH_NODE = "branch"
DUMMY_NODE = "dummy"

PAGE_TEMPLATE = Path(__file__).resolve().parent / "work_graph_page.html"
_BODY_MARKER = "<!--BODY-->"

# ── 배치 상수 (px, 캔버스 좌표) ───────────────────────────────────────────────
# 창 크기는 제목 두 줄 + 완료 조건 발췌 두 줄 + 메타 한 줄이 들어가는 최소치다. 값을 바꾸면
# 테스트의 겹침·방향·프레임 포함 계약이 그대로 다시 검사한다.
WIN_W = 300
WIN_H = 176
GAP_X = 104  # 계층 사이 — 연결선이 꺾여 들어갈 자리
GAP_Y = 26
DUMMY_H = 10  # 두 계층 이상을 건너는 연결선이 지나가는 빈 자리의 높이
FRAME_PAD = 28
FRAME_HEAD = 56  # 프레임 제목 띠
FRAME_GAP = 72  # 프레임 사이
SECTION_GAP = 160  # "흐름" 구역과 "연결 없는 작업" 구역 사이
CANVAS_MIN_W = 5200  # 선반(shelf) 배치의 목표 폭 — 가장 넓은 프레임이 더 넓으면 그것을 따른다
GROUP_MAX_COLS = 16
_SWEEPS = 12  # 교차 줄이기(무게중심법) 반복 횟수 — 흐름 최대 수십 노드라 충분하다

EXCERPT_ITEMS = 2  # 창 본문에 싣는 완료 조건 수
EXCERPT_CHARS = 96  # 발췌 한 줄 상한
NOTES_CHARS = 1600  # 상세 패널에 싣는 노트 상한 (전문은 YAML에 있다)

# 상태 키 → 화면 라벨. 작업 창은 board 열 판정을 그대로 쓰고(사람 소유만 따로 이름을 붙인다),
# 게이트 창은 세 갈래(여는 작업이 남았는가 / 판정 기록이 빠졌는가 / 담당자 차례인가 —
# `store.gate_wait_kind` 그대로 · HARN-184), 브랜치 창은 한 상태다.
STATE_LABEL: dict[str, str] = {
    "ready": "시작 가능",
    "in_progress": "진행 중",
    "review": "검토 대기",
    "waiting": "대기",
    "blocked": "차단",
    "human": "사람 소유",
    "gate_turn": "사람 차례",
    "gate_verdict": "판정 결과 미기록",
    "gate_wait": "선행 작업 대기",
    "branch": "미머지 브랜치",
}

# 게이트 대기 분류(store) → 게이트 창 상태. 판정 결과 미기록은 '사람 차례'가 아니다 — 판정이
# 이미 났는데 기록만 빠졌을 수 있다(HARN-177 ② · 2026-09-25 사고). 그래프가 스스로 가르지 않는다.
GATE_STATE: dict[str, str] = {
    store.GATE_WAITS_INPUTS: "gate_wait",
    store.GATE_WAITS_VERDICT: "gate_verdict",
    store.GATE_WAITS_PERSON: "gate_turn",
}

# 브랜치 창의 고립 판정 라벨 — remote_claims.StaleBranch.status 그대로 + 미판정 2종.
BRANCH_LABEL: dict[str, str] = {
    "isolated": "고립 — PR 없음",
    "pr_filed": "PR 제출됨",
    "pr_closed": "PR 닫힘(미머지)",
    "ported": "이식됨(정리 대상)",
    "active": "타 세션 진행 중",
    "unresolved": "PR 대조 미수행",
    "unscanned": "고립 판정 안 함",
}

# 연결 없는 창의 그룹 프레임 — 순서가 곧 캔버스 배치 순서("지금 손댈 수 있는 것"이 먼저).
GROUP_ORDER: tuple[tuple[str, str, str], ...] = (
    ("in_progress", "진행 중", "지금 누군가 작업 중이거나 검토를 기다린다"),
    ("ready", "지금 시작 가능", "선행·게이트가 없다 — 순서 상관없이 바로 착수할 수 있다"),
    (
        "human",
        "사람 작업",
        "Kiki 소유 태스크와 아무 작업도 걸려 있지 않은 게이트 — 사람이 움직이거나 판정 기록을 "
        "기다린다(창의 상태 표시가 어느 쪽인지 말한다)",
    ),
    ("blocked", "차단", "사유가 붙어 멈춰 있다"),
    ("waiting", "대기", "다른 세션 claim 등 그래프 밖 사유로 기다린다"),
    ("branch", "미머지 브랜치", "트렁크에 흡수되지 않은 브랜치 — 들고 있는 태스크가 없는 것"),
)

EDGE_LABEL: dict[str, str] = {
    "depends_on": "선행 태스크",
    "requires_gates": "필요 게이트",
    "entry_gate": "트랙 진입 게이트",
    "gate_input": "게이트를 여는 작업",
    "done_on_branch": "이 브랜치에 완료분이 있다(미머지)",
    "claimed_on_branch": "이 브랜치의 세션이 진행 중",
}

Edge = tuple[Node, Node, str]


def node_key(node: Node) -> str:
    """화면용 키 — 태스크·게이트·브랜치 ID가 우연히 같아도 섞이지 않게 접두를 붙인다."""
    kind, nid = node
    prefix = {store.TASK_NODE: "t:", store.GATE_NODE: "g:", BRANCH_NODE: "b:"}[kind]
    return prefix + nid


_SHORT_ID = re.compile(r"^([A-Za-z][A-Za-z0-9]*-\d+)(?:-|$)")


def short_id(task_id: str) -> str:
    """`HARN-182-open-work-flow-graph` → `HARN-182` (번호가 없는 ID는 그대로)."""
    match = _SHORT_ID.match(task_id)
    return match.group(1) if match else task_id


def is_open(backlog: Backlog, node: Node) -> bool:
    kind, nid = node
    if kind == store.TASK_NODE:
        return backlog.tasks[nid].status not in TERMINAL_STATUSES
    return not backlog.gates[nid].passed


def _clip(text: str, limit: int) -> str:
    """공백을 한 칸으로 접고 상한에서 자른다(말줄임표 포함 길이 = limit)."""
    flat = " ".join(text.split())
    return flat[: limit - 1] + "…" if len(flat) > limit else flat


def _clip_block(text: str, limit: int) -> str:
    """줄바꿈은 살린 채 상한에서 자른다(상세 패널의 원문 표시용)."""
    text = text.strip()
    return text[: limit - 1] + "…" if len(text) > limit else text


def excerpt_lines(acceptance: list[str], notes: str) -> list[str]:
    """창 본문 발췌 — 완료 조건 앞 N개, 없으면 노트 첫 문단(작업 내용 일부 표시)."""
    items = [_clip(a, EXCERPT_CHARS) for a in acceptance if a.strip()][:EXCERPT_ITEMS]
    if items:
        return items
    first = next((p for p in notes.split("\n\n") if p.strip()), "")
    return [_clip(first, EXCERPT_CHARS * EXCERPT_ITEMS)] if first else []


# ── 미머지 작업(브랜치) 조립 ─────────────────────────────────────────────────


@dataclass
class BranchWork:
    """브랜치 창 1개의 재료 — 세 스캔(미머지 done·원격 claim·고립 브랜치)을 브랜치명으로 합친다."""

    branch: str
    # 이 브랜치가 done으로 들고 있는 열린 태스크 (미머지 완료분)
    done_tasks: list[str] = field(default_factory=list)
    # 이 브랜치의 세션이 claim 중인 태스크 (로컬 대장에 있음)
    claimed_tasks: list[str] = field(default_factory=list)
    # claim 중이나 로컬 대장에 없는 태스크 (그 브랜치에서 새로 등재됐다)
    foreign_tasks: list[str] = field(default_factory=list)
    stale: remote_claims.StaleBranch | None = None


def collect_branches(
    backlog: Backlog,
    remote_done: dict[str, list[str]],
    remote_claimed: dict[str, str],
    stale: list[remote_claims.StaleBranch],
) -> dict[str, BranchWork]:
    """브랜치명 → BranchWork. 열린 태스크와 이어지는 것·고립 스캔이 잡은 것을 전부 창으로 만든다."""
    works: dict[str, BranchWork] = {}

    def get(branch: str) -> BranchWork:
        return works.setdefault(branch, BranchWork(branch=branch))

    for task_id, branches in sorted(remote_done.items()):
        task = backlog.tasks.get(task_id)
        if task is None or task.status in TERMINAL_STATUSES:
            continue
        for branch in sorted(set(branches)):
            get(branch).done_tasks.append(task_id)
    for task_id, branch in sorted(remote_claimed.items()):
        task = backlog.tasks.get(task_id)
        if task is None:
            get(branch).foreign_tasks.append(task_id)
        elif task.status not in TERMINAL_STATUSES:
            get(branch).claimed_tasks.append(task_id)
    for item in sorted(stale, key=lambda s: s.branch):
        get(item.branch).stale = item
    return works


# ── 그래프 추출 ──────────────────────────────────────────────────────────────


def open_subgraph(
    backlog: Backlog, graph: store.DependencyGraph, branches: dict[str, BranchWork]
) -> tuple[list[Node], list[Edge]]:
    """열린 노드 전부(작업·게이트·브랜치) + 열린 노드끼리 잇는 간선 전부 (둘 다 결정적 정렬).

    브랜치 → 태스크 간선은 store.dependency_graph 밖에서 여기서만 덧붙인다 — 저장소 밖 사실
    (다른 브랜치의 대장 사본)이라 validate·selector가 다루는 그래프에 섞지 않는다.
    """
    nodes = [node for node in graph.succ if is_open(backlog, node)]
    edges: list[Edge] = [
        (src, dst, kind)
        for (src, dst), kind in graph.edge_kind.items()
        if is_open(backlog, src) and is_open(backlog, dst)
    ]
    for name, work in branches.items():
        bnode = (BRANCH_NODE, name)
        nodes.append(bnode)
        for task_id in work.done_tasks:
            edges.append((bnode, (store.TASK_NODE, task_id), "done_on_branch"))
        for task_id in work.claimed_tasks:
            edges.append((bnode, (store.TASK_NODE, task_id), "claimed_on_branch"))
    return sorted(nodes), sorted(edges)


def components(nodes: list[Node], edges: list[Edge]) -> list[list[Node]]:
    """방향을 무시한 연결 성분 — 한 성분이 한 "흐름"이다. 각 성분·성분 목록 모두 정렬."""
    adjacency: dict[Node, set[Node]] = {node: set() for node in nodes}
    for src, dst, _kind in edges:
        adjacency[src].add(dst)
        adjacency[dst].add(src)
    seen: set[Node] = set()
    result: list[list[Node]] = []
    for start in nodes:
        if start in seen:
            continue
        seen.add(start)
        stack = [start]
        members: list[Node] = []
        while stack:
            cur = stack.pop()
            members.append(cur)
            for nxt in adjacency[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        result.append(sorted(members))
    return result


# ── 흐름 하나의 계층 배치 (Sugiyama 축약판) ──────────────────────────────────


@dataclass
class FlowLayout:
    """흐름 하나의 배치 결과 — 좌표는 흐름 내부 좌상단(0,0) 기준 px(정수)."""

    boxes: dict[Node, tuple[int, int, int, int]]  # 노드 → (x, y, w, h)
    edges: list[dict[str, object]]  # {src, dst, kind, back, points}
    width: int
    height: int
    layers: dict[Node, int] = field(default_factory=dict)


def _split_back_edges(nodes: list[Node], edges: list[Edge]) -> tuple[list[Edge], list[Edge]]:
    """순환을 닫는 간선(DFS 역방향)을 떼어 낸다 — (앞으로 가는 간선, 되돌아가는 간선).

    대장은 순환을 validate로 거부하므로(HARN-174) 정상 데이터에서 두 번째 목록은 비어 있다.
    그래도 여기서 무한 루프·배치 실패가 나면 안 되므로, 떼어 낸 간선은 `back: true`로 표시해
    그대로 그린다(숨기지 않는다).
    """
    succ: dict[Node, list[Node]] = {node: [] for node in nodes}
    for src, dst, _kind in edges:
        succ[src].append(dst)
    for key in succ:
        succ[key].sort()
    state: dict[Node, int] = {}  # 1 = 방문 중, 2 = 완료
    back: set[tuple[Node, Node]] = set()
    for root in nodes:
        if root in state:
            continue
        state[root] = 1
        stack: list[tuple[Node, int]] = [(root, 0)]
        while stack:
            cur, idx = stack[-1]
            if idx < len(succ[cur]):
                stack[-1] = (cur, idx + 1)
                nxt = succ[cur][idx]
                if state.get(nxt) == 1:
                    back.add((cur, nxt))
                elif nxt not in state:
                    state[nxt] = 1
                    stack.append((nxt, 0))
            else:
                state[cur] = 2
                stack.pop()
    forward = [e for e in edges if (e[0], e[1]) not in back]
    backward = [e for e in edges if (e[0], e[1]) in back]
    return forward, backward


def _longest_path_layers(nodes: list[Node], edges: list[Edge]) -> dict[Node, int]:
    """원천(선행 없음)을 0층으로 두고, 각 노드를 선행 중 가장 깊은 것 + 1층에 둔다."""
    preds: dict[Node, list[Node]] = {node: [] for node in nodes}
    succ: dict[Node, list[Node]] = {node: [] for node in nodes}
    for src, dst, _kind in edges:
        preds[dst].append(src)
        succ[src].append(dst)
    indegree = {node: len(preds[node]) for node in nodes}
    queue = sorted(node for node in nodes if indegree[node] == 0)
    layer: dict[Node, int] = {}
    while queue:
        cur = queue.pop(0)
        layer[cur] = max((layer[p] + 1 for p in preds[cur]), default=0)
        for nxt in sorted(succ[cur]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
        queue.sort()
    # _split_back_edges를 거친 입력이면 여기까지 오지 않는다 — 방어적으로 남은 노드를 맨 뒤층에.
    tail = max(layer.values(), default=-1) + 1
    for node in nodes:
        layer.setdefault(node, tail)
    return layer


def _crossings(layers: list[list[Node]], succ: dict[Node, list[Node]]) -> int:
    """인접 계층 사이 간선 교차 수 (쌍 비교 — 흐름당 수십 간선이라 O(E²)로 충분)."""
    total = 0
    for upper, lower in zip(layers, layers[1:], strict=False):
        pos = {node: i for i, node in enumerate(lower)}
        pairs = [(i, pos[dst]) for i, src in enumerate(upper) for dst in succ[src] if dst in pos]
        for a in range(len(pairs)):
            for b in range(a + 1, len(pairs)):
                (u1, v1), (u2, v2) = pairs[a], pairs[b]
                if (u1 - u2) * (v1 - v2) < 0:
                    total += 1
    return total


def _order_layers(
    layers: list[list[Node]], preds: dict[Node, list[Node]], succ: dict[Node, list[Node]]
) -> list[list[Node]]:
    """무게중심법으로 계층 안 순서를 정해 교차를 줄인다 — 교차가 가장 적었던 배치를 반환."""
    pos = {node: i for layer in layers for i, node in enumerate(layer)}
    best = [list(layer) for layer in layers]
    best_cross = _crossings(layers, succ)
    for sweep in range(_SWEEPS):
        downward = sweep % 2 == 0
        indices = range(1, len(layers)) if downward else range(len(layers) - 2, -1, -1)
        neighbors = preds if downward else succ
        for idx in indices:
            layer = layers[idx]

            def weight(node: Node, _nbrs: dict[Node, list[Node]] = neighbors) -> float:
                refs = [pos[m] for m in _nbrs[node]]
                return sum(refs) / len(refs) if refs else float(pos[node])

            layer.sort(key=lambda node: (weight(node), pos[node], node))
            for i, node in enumerate(layer):
                pos[node] = i
        cross = _crossings(layers, succ)
        if cross < best_cross:
            best_cross = cross
            best = [list(layer) for layer in layers]
    return best


def layout_flow(nodes: list[Node], edges: list[Edge]) -> FlowLayout:
    """흐름 하나를 왼쪽→오른쪽 계층 그래프로 배치한다.

    ① 순환 간선 분리 ② 최장 경로 층 배정 ③ 두 층 이상 건너는 간선에 빈 자리(dummy) 삽입
    ④ 무게중심법 교차 줄이기 ⑤ 층마다 세로로 쌓고 가운데 정렬.
    간선 좌표 `points`는 [출력 포트, (빈자리 입구, 빈자리 출구)*, 입력 포트] — 항상 짝수 개다.
    """
    forward, backward = _split_back_edges(nodes, edges)
    layer = _longest_path_layers(nodes, forward)

    # ③ 빈 자리 삽입 — 모든 앞 방향 간선이 바로 옆 층만 잇게 만든다.
    all_nodes: list[Node] = list(nodes)
    preds: dict[Node, list[Node]] = {node: [] for node in nodes}
    succ: dict[Node, list[Node]] = {node: [] for node in nodes}
    chains: dict[tuple[Node, Node], list[Node]] = {}
    for src, dst, _kind in forward:
        chain: list[Node] = []
        prev = src
        for step in range(1, layer[dst] - layer[src]):
            dummy = (DUMMY_NODE, f"{src[1]}>{dst[1]}#{step}")
            layer[dummy] = layer[src] + step
            all_nodes.append(dummy)
            preds[dummy] = [prev]
            succ[dummy] = []
            succ[prev].append(dummy)
            chain.append(dummy)
            prev = dummy
        succ[prev].append(dst)
        preds[dst].append(prev)
        chains[(src, dst)] = chain

    depth = max(layer.values(), default=0) + 1
    layers: list[list[Node]] = [[] for _ in range(depth)]
    # 초기 순서: 게이트를 위로(흐름의 관문이 먼저 눈에 띈다), 그다음 ID.
    for node in sorted(all_nodes, key=lambda n: (n[0] != store.GATE_NODE, n)):
        layers[layer[node]].append(node)
    layers = _order_layers(layers, preds, succ)

    # ⑤ 좌표 — 층마다 세로로 쌓은 뒤, 가장 높은 층 기준으로 가운데 정렬.
    def height_of(node: Node) -> int:
        return DUMMY_H if node[0] == DUMMY_NODE else WIN_H

    stack_heights = [
        sum(height_of(n) for n in column) + GAP_Y * max(len(column) - 1, 0) for column in layers
    ]
    inner_h = max(stack_heights, default=WIN_H)
    boxes: dict[Node, tuple[int, int, int, int]] = {}
    for idx, column in enumerate(layers):
        x = idx * (WIN_W + GAP_X)
        y = (inner_h - stack_heights[idx]) // 2
        for node in column:
            h = height_of(node)
            boxes[node] = (x, y, WIN_W, h)
            y += h + GAP_Y

    def out_pt(node: Node) -> list[int]:
        x, y, w, h = boxes[node]
        return [x + w, y + h // 2]

    def in_pt(node: Node) -> list[int]:
        x, y, _w, h = boxes[node]
        return [x, y + h // 2]

    drawn: list[dict[str, object]] = []
    for src, dst, kind in sorted(forward + backward):
        points = [out_pt(src)]
        for dummy in chains.get((src, dst), []):
            points.append(in_pt(dummy))
            points.append(out_pt(dummy))
        points.append(in_pt(dst))
        drawn.append(
            {
                "src": node_key(src),
                "dst": node_key(dst),
                "kind": kind,
                "back": (src, dst, kind) in backward,
                "points": points,
            }
        )

    real = {node: box for node, box in boxes.items() if node[0] != DUMMY_NODE}
    return FlowLayout(
        boxes=real,
        edges=drawn,
        width=depth * WIN_W + (depth - 1) * GAP_X,
        height=inner_h,
        layers={node: layer[node] for node in nodes},
    )


def grid_size(count: int) -> tuple[int, int]:
    """연결 없는 창 묶음의 격자 (열, 행) — 가로가 세로의 약 2배가 되게, 열은 상한 16."""
    if count <= 0:
        return 0, 0
    cols = max(1, min(GROUP_MAX_COLS, count, math.ceil(math.sqrt(count * 2))))
    return cols, math.ceil(count / cols)


def shelf_pack(sizes: list[tuple[int, int]], width: int, top: int = 0) -> list[tuple[int, int]]:
    """크기 목록을 **순서대로** 선반에 채운다 — 폭을 넘으면 다음 줄. 반환은 각 좌상단 (x, y).

    순서를 바꾸지 않는 이유: 흐름 번호(크기순)가 곧 읽는 순서다. 빈틈을 줄이려 재정렬하면
    "흐름 1"이 캔버스 한가운데로 가 버린다.
    """
    placed: list[tuple[int, int]] = []
    x, y, row_h = 0, top, 0
    for w, h in sizes:
        if x > 0 and x + w > width:
            x, y, row_h = 0, y + row_h + FRAME_GAP, 0
        placed.append((x, y))
        x += w + FRAME_GAP
        row_h = max(row_h, h)
    return placed


# ── 창 상세 ──────────────────────────────────────────────────────────────────


def gate_clear_command(gate: Gate) -> str:
    """사람이 복사해 실행할 clear 명령 — 담당자를 `--as`로 싣는다 (HARN-60 · board.py와 동일 규칙).

    `--as`를 빼면 Kiki가 실행한 clear가 대장에 `cleared_by: claude`로 남는다. 담당자가
    claude(에이전트 소유 게이트)면 플래그를 붙이지 않는다 — `--as claude`는 선택지가 아니다.
    """
    as_flag = f" --as {gate.assignee}" if gate.assignee and gate.assignee != "claude" else ""
    return (
        f"python3 scripts/harness/backlog.py gates clear {gate.id}{as_flag} "
        '--evidence "<근거: PR 번호 또는 커밋 해시>"'
    )


def branch_inspect_command(branch: str) -> str:
    """브랜치 창의 확인 명령 — 읽기 전용(트렁크에 없는 커밋 목록)."""
    return f"git fetch origin {branch} && git log --oneline origin/main..origin/{branch}"


def apply_remote_claims(
    cards: list[board.BoardTask], backlog: Backlog, remote_claimed: dict[str, str]
) -> None:
    """다른 세션이 원격 claim한 태스크를 "시작 가능"에서 빼 대기(원격 claim)로 옮긴다.

    board는 원격 claim을 보지 않지만 `backlog.py next`는 본다 — 그래프가 "시작 가능"이라고
    보여 준 작업을 다른 세션이 이미 잡고 있으면 중복 구현을 부른다(2026-07-27 OPS-07 선례).
    판정은 selector.classify_todo에 remote_claimed를 넘겨 **그대로** 받는다(자체 판정 금지).
    """
    if not remote_claimed:
        return
    for card in cards:
        if card.column != "ready":
            continue
        exclusion = selector.classify_todo(
            backlog, backlog.tasks[card.id], remote_claimed=remote_claimed
        )
        if exclusion is not None and exclusion.reason == "claimed_remote":
            card.column = "waiting"
            card.reason = board.WAIT_LABEL["claimed_remote"]
            card.detail = ", ".join(exclusion.detail)


def _task_state(card: board.BoardTask, owner: str) -> tuple[str, str]:
    """board 카드 → (상태 키, 화면 라벨). 판정은 board.classify가 이미 끝냈다 — 이름만 붙인다."""
    if card.status == "review":
        return "review", STATE_LABEL["review"]
    if card.column == "waiting":
        if card.reason == board.WAIT_LABEL["owner"]:
            return "human", f"{STATE_LABEL['human']} · {owner}"
        return "waiting", card.reason or STATE_LABEL["waiting"]
    return card.column, STATE_LABEL[card.column]


def _link(
    backlog: Backlog, branches: dict[str, BranchWork], node: Node, edge: str
) -> dict[str, object]:
    """상세 패널의 선행·후속 한 줄 — 끝난 것도 남긴다(무엇이 이미 풀렸는지도 정보다)."""
    kind, nid = node
    if kind == store.TASK_NODE:
        task = backlog.tasks[nid]
        title, status, open_ = task.title, task.status, task.status not in TERMINAL_STATUSES
    elif kind == store.GATE_NODE:
        gate = backlog.gates[nid]
        title, status, open_ = gate.title, gate.status, not gate.passed
    else:
        title, status, open_ = _branch_title(branches[nid]), "unmerged", True
    return {
        "key": node_key(node),
        "id": nid,
        "kind": kind,
        "title": title,
        "status": status,
        "open": open_,
        "edge": EDGE_LABEL.get(edge, edge),
    }


def _branch_title(work: BranchWork) -> str:
    parts = []
    if work.done_tasks:
        parts.append(f"완료분 {len(work.done_tasks)}건")
    if work.claimed_tasks or work.foreign_tasks:
        parts.append(f"진행 중 {len(work.claimed_tasks) + len(work.foreign_tasks)}건")
    if work.stale is not None:
        parts.append(f"트렁크보다 {work.stale.ahead}커밋 앞 · {work.stale.age_days:.0f}일 경과")
    return " · ".join(parts) or "미머지 브랜치"


def build_nodes(
    backlog: Backlog,
    graph: store.DependencyGraph,
    branches: dict[str, BranchWork],
    nodes: list[Node],
    edges: list[Edge],
    today: date,
    remote_done: dict[str, list[str]],
    remote_claimed: dict[str, str] | None = None,
) -> dict[str, dict[str, object]]:
    """모든 창의 화면 자료 — 상태·사유·발췌·선후·대기 경로·명령 (좌표는 build_graph가 붙인다)."""
    cards_list: list[board.BoardTask] = board.build_tasks(backlog)
    board.apply_remote_done(cards_list, remote_done)
    apply_remote_claims(cards_list, backlog, remote_claimed or {})
    cards = {card.id: card for card in cards_list}

    # 선후 목록 — 대장 그래프(끝난 것 포함) + 브랜치 간선.
    preds: dict[Node, list[tuple[Node, str]]] = {node: [] for node in nodes}
    succs: dict[Node, list[tuple[Node, str]]] = {node: [] for node in nodes}
    for node in nodes:
        if node[0] != BRANCH_NODE:
            preds[node] += [(p, graph.edge_kind[(p, node)]) for p in graph.pred[node]]
            succs[node] += [(s, graph.edge_kind[(node, s)]) for s in graph.succ[node]]
    for src, dst, kind in edges:
        if src[0] == BRANCH_NODE:
            succs[src].append((dst, kind))
            preds[dst].append((src, kind))

    result: dict[str, dict[str, object]] = {}
    for node in nodes:
        kind, nid = node
        base: dict[str, object] = {
            "key": node_key(node),
            "kind": kind,
            "id": nid,
            "preds": [_link(backlog, branches, p, e) for p, e in preds[node]],
            "succs": [_link(backlog, branches, s, e) for s, e in succs[node]],
        }
        if kind == store.TASK_NODE:
            task: Task = backlog.tasks[nid]
            card = cards[nid]
            state, label = _task_state(card, task.owner)
            chain = selector.wait_chain(backlog, task, graph)
            base.update(
                {
                    "short": short_id(nid),
                    "title": task.title,
                    "state": state,
                    "label": label,
                    "reason": card.reason,
                    "detail": card.detail,
                    "stage": task.stage,
                    "layer": task.layer,
                    "track": task.track,
                    "subject": task.subject,
                    "priority": task.priority,
                    "owner": task.owner,
                    "session": task.session or "",
                    "updated": task.updated,
                    "unlocks": card.unlocks,
                    "wait_chain": chain if len(chain) > 1 else [],
                    "excerpt": excerpt_lines(task.acceptance, task.notes),
                    "acceptance": list(task.acceptance),
                    "notes": _clip_block(task.notes, NOTES_CHARS),
                    "cmd": (
                        f"python3 scripts/harness/backlog.py start {nid}"
                        if state == "ready"
                        else ""
                    ),
                }
            )
        elif kind == store.GATE_NODE:
            gate = backlog.gates[nid]
            detail = board.gate_detail(backlog, gate, today)
            # 창 상태는 공용 분류를 그대로 받는다(HARN-184 — 그래프 자체 판정 금지). 종전의
            # "열린 선행이 있는가"만으로는 판정 결과 미기록 게이트가 '사람 차례'로 떨어졌다.
            wait_kind = store.gate_wait_kind(backlog, gate)
            state = GATE_STATE[str(wait_kind)]
            judgment = store.gate_judgment_state(backlog, gate)
            chain = selector.wait_chain_from_gate(backlog, nid, graph)
            if judgment is not None:
                reason = store.judgment_state_label(judgment)
            elif wait_kind == store.GATE_WAITS_INPUTS:
                reason = "이 게이트를 여는 작업이 아직 남았다"
            else:
                reason = f"담당 {gate.assignee}의 행동을 기다린다"
            base.update(
                {
                    "short": nid,
                    "title": gate.title,
                    "state": state,
                    "label": STATE_LABEL[state],
                    "reason": reason,
                    "detail": "",
                    "gate_kind": gate.kind,
                    "assignee": gate.assignee,
                    "requested": gate.requested,
                    "days": detail["days"],
                    "overdue": detail["overdue"],
                    "unlocks": len(store.open_descendant_tasks(backlog, node, graph)),
                    "wait_chain": chain if len(chain) > 1 else [],
                    "excerpt": excerpt_lines([], gate.notes),
                    "acceptance": [],
                    "notes": _clip_block(gate.notes, NOTES_CHARS * 2),
                    "cmd": gate_clear_command(gate),
                }
            )
        else:
            work = branches[nid]
            stale = work.stale
            verdict = stale.status if stale is not None else "unscanned"
            excerpt = [f"완료분: {', '.join(short_id(t) for t in work.done_tasks)}"] * bool(
                work.done_tasks
            )
            claimed = work.claimed_tasks + work.foreign_tasks
            if claimed:
                excerpt.append(f"진행 중: {', '.join(short_id(t) for t in claimed)}")
            if stale is not None and stale.evidence:
                excerpt.append(f"근거: {stale.evidence}")
            base.update(
                {
                    "short": nid.removeprefix("claude/"),
                    "title": _branch_title(work),
                    "state": "branch",
                    "label": STATE_LABEL["branch"],
                    "reason": BRANCH_LABEL.get(verdict, verdict),
                    "detail": stale.evidence if stale is not None else "",
                    "verdict": verdict,
                    "done_tasks": list(work.done_tasks),
                    "claimed_tasks": list(work.claimed_tasks),
                    "foreign_tasks": list(work.foreign_tasks),
                    "ahead": stale.ahead if stale is not None else None,
                    "age_days": round(stale.age_days, 1) if stale is not None else None,
                    "last_commit_at": stale.last_commit_at.isoformat() if stale is not None else "",
                    "disposal_labels": list(stale.disposal_labels) if stale is not None else [],
                    "unlocks": len(work.done_tasks) + len(work.claimed_tasks),
                    "wait_chain": [],
                    "excerpt": excerpt,
                    "acceptance": [],
                    "notes": "",
                    "cmd": branch_inspect_command(nid),
                }
            )
        result[node_key(node)] = base
    return result


# ── 캔버스 조립 ──────────────────────────────────────────────────────────────


def _hub(members: list[Node], edges: list[Edge], unlocks: dict[str, int]) -> Node:
    """흐름의 대표 노드 — 가장 많이 이어진 노드(동률이면 게이트 → 해금 수 → ID)."""
    degree = {node: 0 for node in members}
    for src, dst, _kind in edges:
        degree[src] += 1
        degree[dst] += 1
    return min(
        members,
        key=lambda n: (-degree[n], n[0] != store.GATE_NODE, -unlocks.get(node_key(n), 0), n),
    )


def _state_counts(keys: list[str], info: dict[str, dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key in keys:
        state = str(info[key]["state"])
        counts[state] = counts.get(state, 0) + 1
    return counts


def _independent_group(state: str) -> str:
    if state in ("gate_turn", "gate_verdict", "gate_wait", "human"):
        return "human"
    if state == "review":
        return "in_progress"
    return state


def _as_int(value: object) -> int:
    return int(str(value))


def build_graph(
    backlog: Backlog,
    errors: list[str],
    today: date,
    *,
    remote_done: dict[str, list[str]] | None = None,
    remote_done_status: str = "skipped",
    remote_claimed: dict[str, str] | None = None,
    remote_claim_status: str = "skipped",
    stale_branches: list[remote_claims.StaleBranch] | None = None,
    stale_status: str = "skipped",
    base: str = "",
) -> dict[str, object]:
    """캔버스 페이로드 — HTML 렌더와 --json이 공유하는 단일 자료구조.

    remote_done / remote_done_status: board.build_board와 같은 의미(미머지 완료분 — HARN-11).
    remote_claimed / remote_claim_status: 원격 claim(task_id → 브랜치)과 그 조회 상태.
    stale_branches / stale_status: 고립 브랜치 스캔(HARN-47)과 그 상태(`shallow` 포함).
        세 상태 모두 `ok`가 아니면 판정 불가이며 화면이 그 사실을 배너로 드러낸다 — 빈 결과를
        "없음"으로 읽히게 두면 측정 실패가 통과로 위장된다.
    base: 판정 기준 커밋(짧은 해시). 판정은 시점에 종속되므로 화면 머리에 박는다.

    좌표계: 캔버스 좌상단 (0,0), px 정수. 창의 (x, y, w, h)는 `nodes[key]`에, 프레임은
    `frames`에, 연결선은 `edges`(캔버스 좌표로 옮긴 points)에 있다.
    """
    graph = store.dependency_graph(backlog)
    branches = collect_branches(
        backlog, remote_done or {}, remote_claimed or {}, stale_branches or []
    )
    nodes, edges = open_subgraph(backlog, graph, branches)
    info = build_nodes(
        backlog, graph, branches, nodes, edges, today, remote_done or {}, remote_claimed
    )
    unlocks = {key: _as_int(item["unlocks"]) for key, item in info.items()}

    # ① 흐름 — 연결 성분(2개 이상)마다 계층 배치.
    flows: list[dict[str, object]] = []
    layouts: list[FlowLayout] = []
    singles: list[str] = []
    for members in components(nodes, edges):
        # 창 1개짜리 성분이라도 자기 자신을 가리키는 간선(validate가 거부하는 자기 순환)이
        # 있으면 흐름으로 배치한다 — 연결 없는 묶음으로 보내면 그 간선이 edge_total에는
        # 세지고 화면에는 안 그려져 간선 전수 계약이 깨진다(순환은 숨기지 않고 드러낸다).
        solo = members[0]
        if len(members) == 1 and not any(e[0] == e[1] == solo for e in edges):
            singles.append(node_key(solo))
            continue
        member_set = set(members)
        flow_edges = [e for e in edges if e[0] in member_set and e[1] in member_set]
        layout = layout_flow(members, flow_edges)
        hub = _hub(members, flow_edges, unlocks)
        keys = sorted(node_key(n) for n in members)
        flows.append(
            {
                "kind": "flow",
                "hub": node_key(hub),
                # 대표가 브랜치면 요약("완료분 N건")이 아니라 브랜치 이름이 흐름을 설명한다.
                "title": str(info[node_key(hub)]["id" if hub[0] == BRANCH_NODE else "title"]),
                "size": len(members),
                "edge_count": len(flow_edges),
                "depth": max(layout.layers.values()) + 1,
                "counts": _state_counts(keys, info),
                "keys": keys,
            }
        )
        layouts.append(layout)
    # 큰 흐름이 먼저 — 병목이 몰린 곳이 위에 온다. 동률은 대표 노드 키로 결정.
    order = sorted(range(len(flows)), key=lambda i: (-_as_int(flows[i]["size"]), flows[i]["hub"]))
    flows = [flows[i] for i in order]
    layouts = [layouts[i] for i in order]

    # ② 연결 없는 창 — 상태 그룹마다 격자. 그룹 안 순서는 next 정렬(selector.sort_key).
    task_unlocks = {
        str(item["id"]): unlocks[k] for k, item in info.items() if item["kind"] == "task"
    }

    def order_key(key: str) -> tuple[object, ...]:
        item = info[key]
        if item["kind"] == store.TASK_NODE:
            return (0, selector.sort_key(backlog, backlog.tasks[str(item["id"])], task_unlocks))
        return (1, (-unlocks[key], key))

    groups: list[dict[str, object]] = []
    for gkey, label, hint in GROUP_ORDER:
        keys = sorted(
            (k for k in singles if _independent_group(str(info[k]["state"])) == gkey),
            key=order_key,
        )
        if keys:
            groups.append(
                {"kind": "group", "group": gkey, "title": label, "hint": hint, "keys": keys}
            )

    # ③ 프레임 크기 → 선반 배치 → 창·연결선을 캔버스 좌표로 옮긴다.
    def frame_size(inner_w: int, inner_h: int) -> tuple[int, int]:
        return inner_w + FRAME_PAD * 2, inner_h + FRAME_HEAD + FRAME_PAD

    flow_sizes = [frame_size(lay.width, lay.height) for lay in layouts]
    group_grids = [grid_size(len(g["keys"])) for g in groups]  # type: ignore[arg-type]
    group_sizes = [
        frame_size(cols * WIN_W + (cols - 1) * GAP_Y, rows * WIN_H + (rows - 1) * GAP_Y)
        for cols, rows in group_grids
    ]
    canvas_w = max([CANVAS_MIN_W] + [w for w, _h in flow_sizes + group_sizes])
    flow_pos = shelf_pack(flow_sizes, canvas_w)
    flows_bottom = max(
        (y + h for (_x, y), (_w, h) in zip(flow_pos, flow_sizes, strict=True)), default=0
    )
    group_top = flows_bottom + SECTION_GAP if flows else 0
    group_pos = shelf_pack(group_sizes, canvas_w, top=group_top)

    frames: list[dict[str, object]] = []
    canvas_edges: list[dict[str, object]] = []
    for index, (flow, layout, (fx, fy), (fw, fh)) in enumerate(
        zip(flows, layouts, flow_pos, flow_sizes, strict=True), start=1
    ):
        ox, oy = fx + FRAME_PAD, fy + FRAME_HEAD
        frame_id = f"flow-{index}"
        flow.update({"id": frame_id, "index": index, "x": fx, "y": fy, "w": fw, "h": fh})
        for node, (x, y, w, h) in layout.boxes.items():
            info[node_key(node)].update(
                {"x": ox + x, "y": oy + y, "w": w, "h": h, "frame": frame_id, "flow": index}
            )
        for edge in layout.edges:
            moved = dict(edge)
            moved["points"] = [[px + ox, py + oy] for px, py in edge["points"]]  # type: ignore[union-attr]
            moved["frame"] = frame_id
            canvas_edges.append(moved)
        frames.append(flow)
    for group, (cols, _rows), (gx, gy), (gw, gh) in zip(
        groups, group_grids, group_pos, group_sizes, strict=True
    ):
        frame_id = f"group-{group['group']}"
        keys = list(group["keys"])  # type: ignore[arg-type]
        group.update({"id": frame_id, "x": gx, "y": gy, "w": gw, "h": gh, "size": len(keys)})
        for i, key in enumerate(keys):
            col, row = i % cols, i // cols
            info[key].update(
                {
                    "x": gx + FRAME_PAD + col * (WIN_W + GAP_Y),
                    "y": gy + FRAME_HEAD + row * (WIN_H + GAP_Y),
                    "w": WIN_W,
                    "h": WIN_H,
                    "frame": frame_id,
                    "flow": None,
                }
            )
        frames.append(group)
    canvas_h = max((_as_int(f["y"]) + _as_int(f["h"]) for f in frames), default=0)

    all_counts = _state_counts(list(info), info)
    ready_order = sorted((k for k, item in info.items() if item["state"] == "ready"), key=order_key)
    task_total = sum(1 for n in nodes if n[0] == store.TASK_NODE)
    gate_total = sum(1 for n in nodes if n[0] == store.GATE_NODE)
    return {
        "generated": today.strftime("%Y-%m-%d"),
        "base": base,
        "current_stage": report.current_stage(backlog),
        "open_tasks": task_total,
        "open_gates": gate_total,
        "branch_total": len(nodes) - task_total - gate_total,
        "edge_total": len(edges),
        "counts": {
            "ready": all_counts.get("ready", 0),
            "in_progress": all_counts.get("in_progress", 0) + all_counts.get("review", 0),
            "waiting": all_counts.get("waiting", 0),
            "blocked": all_counts.get("blocked", 0),
            "human": all_counts.get("human", 0),
            "gate_turn": all_counts.get("gate_turn", 0),
            "gate_verdict": all_counts.get("gate_verdict", 0),
            "gate_wait": all_counts.get("gate_wait", 0),
            "branch": all_counts.get("branch", 0),
        },
        "flow_count": len(flows),
        "flow_node_total": sum(_as_int(f["size"]) for f in flows),
        "independent_total": len(singles),
        "canvas": {"w": canvas_w, "h": canvas_h, "win_w": WIN_W, "win_h": WIN_H},
        "frames": frames,
        "edges": canvas_edges,
        "ready_order": ready_order,
        "stages": list(backlog.stage_order),
        "scans": {
            "remote_done": {"status": remote_done_status, "count": len(remote_done or {})},
            "remote_claim": {
                "status": remote_claim_status,
                "count": len(remote_claimed or {}),
            },
            "stale_branches": {"status": stale_status, "count": len(stale_branches or [])},
        },
        "errors": errors,
        "nodes": info,
    }


# ── 렌더 ─────────────────────────────────────────────────────────────────────


def _template() -> tuple[str, str]:
    """화면 템플릿 → (머리 조각: title+style, 본문 조각: 마크업+스크립트)."""
    text = PAGE_TEMPLATE.read_text(encoding="utf-8")
    if text.count(_BODY_MARKER) != 1 or text.count("__PAYLOAD__") != 1:
        raise ValueError(
            f"{PAGE_TEMPLATE.name}: {_BODY_MARKER}·__PAYLOAD__ 표식이 각각 정확히 1개여야 한다"
        )
    head, body = text.split(_BODY_MARKER)
    return head.strip(), body.strip()


def render_html(payload: dict[str, object], *, fragment: bool = False) -> str:
    """페이로드를 자기완결 HTML로 렌더.

    fragment=True면 <html>/<head>/<body> 껍데기를 생략하고 <title>+<style>+본문만 낸다
    (문서 골격을 스스로 두르는 호스트에 그대로 삽입하기 위한 출력).
    """
    head, body = _template()
    # </script> 조기 종료 방지 — JSON 안의 '<'를 이스케이프한다.
    blob = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    body = body.replace("__PAYLOAD__", blob)
    if fragment:
        return head + "\n" + body + "\n"
    return (
        '<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f"{head}\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


def render_text(payload: dict[str, object]) -> str:
    """터미널 요약 — HTML을 열 수 없는 환경(SSH·CI 로그)용 같은 데이터의 축약본."""
    counts: dict[str, int] = payload["counts"]  # type: ignore[assignment]
    nodes: dict[str, dict[str, object]] = payload["nodes"]  # type: ignore[assignment]
    scans: dict[str, dict[str, object]] = payload["scans"]  # type: ignore[assignment]
    base = f" · 기준 {payload['base']}" if payload["base"] else ""
    lines = [
        f"🕸  WhyMath 작업 흐름 — {payload['generated']}{base} "
        f"(현재 스테이지 {payload['current_stage']})",
        "",
        f"  열린 작업 {payload['open_tasks']} · 미통과 게이트 {payload['open_gates']} "
        f"· 미머지 브랜치 {payload['branch_total']} · 연결선 {payload['edge_total']}",
        f"  시작 가능 {counts['ready']} · 진행 중 {counts['in_progress']} "
        f"· 대기 {counts['waiting']} · 차단 {counts['blocked']} · 사람 소유 {counts['human']} "
        f"· 사람 차례 {counts['gate_turn']} · 판정 결과 미기록 {counts['gate_verdict']} "
        f"· 게이트 선행 대기 {counts['gate_wait']}",
        f"  이어진 흐름 {payload['flow_count']}개(창 {payload['flow_node_total']}) "
        f"· 연결 없는 창 {payload['independent_total']}",
    ]
    for label, key in (
        ("미머지 완료", "remote_done"),
        ("원격 claim", "remote_claim"),
        ("고립 브랜치", "stale_branches"),
    ):
        status = scans[key]["status"]
        if status != "ok":
            lines.append(f"  ⚠ {label} 판정 불가({status}) — 이 축은 이번 실행에서 측정되지 않았다")
    for frame in payload["frames"]:  # type: ignore[union-attr]
        if frame["kind"] != "flow":
            continue
        lines.append("")
        lines.append(
            f"── 흐름 {frame['index']} · 창 {frame['size']} · 깊이 {frame['depth']} "
            f"· 대표 {nodes[frame['hub']]['id']} ──"
        )
        for state, label in (
            ("ready", "시작 가능"),
            ("gate_turn", "사람 차례"),
            ("gate_verdict", "판정 결과 미기록"),
            ("branch", "미머지"),
        ):
            picked = [k for k in frame["keys"] if nodes[k]["state"] == state]
            if picked:
                lines.append(f"  {label}: " + ", ".join(str(nodes[k]["id"]) for k in picked))
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────


def base_commit(root: Path) -> str:
    """판정 기준 커밋(짧은 해시) — 실패하면 빈 값이 아니라 실패 사실을 문자열로 남긴다."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            # HARN-19: 로케일(cp949) 디코드 금지 — git 출력은 UTF-8이 정본이다.
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except Exception as exc:  # 환경 의존 — 침묵 실패 금지(예외 타입명을 남긴다)
        return f"확인 불가({type(exc).__name__})"
    sha = (out.stdout or "").strip()
    return sha if out.returncode == 0 and sha else f"확인 불가(exit {out.returncode})"


def scan_remote_claimed(
    root: Path, *, skip: bool = False, own_branch: str = ""
) -> tuple[dict[str, str], str]:
    """원격 claim 조회 — {task_id: 브랜치}와 판정 상태(`ok`/`offline`/`error`/`skipped`/`disabled`).

    지금 이 세션의 브랜치가 잡은 claim은 로컬 `session`으로 이미 진행 중이라 제외한다.
    """
    if skip:
        return {}, "skipped"
    policy, _ = store.load_policy(root)
    if not policy.remote_claims:
        return {}, "disabled"
    try:
        claims, status = remote_claims.list_claims(root)
    except Exception as exc:  # 환경 의존 — 침묵 실패 금지
        return {}, f"error:{type(exc).__name__}"
    return {c.task_id: c.branch for c in claims if c.branch and c.branch != own_branch}, status


def scan_stale(
    root: Path, *, skip: bool = False, active_branches: frozenset[str] = frozenset()
) -> tuple[list[remote_claims.StaleBranch], str]:
    """고립 브랜치 스캔(HARN-47) — 네트워크 0(`fetch=False`, 캐시된 원격 ref만).

    shallow 클론이면 판정 자체가 불가(`shallow`)이며, 그 사실을 상태로 돌려준다.
    """
    if skip:
        return [], "skipped"
    try:
        scan = remote_claims.scan_stale_branches(root, fetch=False, active_branches=active_branches)
    except Exception as exc:  # 환경 의존 — 침묵 실패 금지
        return [], f"error:{type(exc).__name__}"
    status = scan.status
    if status == "ok" and not scan.pr_lookup_ok:
        status = "ok(PR 대조 미수행)"
    return list(scan.stale), status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="backlog/ 작업 흐름 그래프 생성 (읽기 전용)")
    parser.add_argument(
        "--out", default="work/graph.html", help="HTML 출력 경로 (기본 work/graph.html)"
    )
    parser.add_argument("--json", action="store_true", help="HTML 대신 페이로드 JSON을 표준출력")
    parser.add_argument("--text", action="store_true", help="터미널 축약 요약 출력")
    parser.add_argument(
        "--fragment",
        action="store_true",
        help="문서 껍데기(<html>/<head>/<body>) 없이 title+style+본문만 출력",
    )
    parser.add_argument(
        "--no-remote",
        action="store_true",
        help="원격 조회(미머지 done·원격 claim·고립 브랜치) 생략 — 판정 불가로 표기된다",
    )
    args = parser.parse_args(argv)

    root = store.find_repo_root()
    backlog, schema_errors = store.load_backlog(root)
    errors = store.validate_backlog(backlog, schema_errors)
    remote_done, remote_done_status = board.scan_unmerged_done(root, backlog, skip=args.no_remote)
    remote_claimed, remote_claim_status = scan_remote_claimed(
        root, skip=args.no_remote, own_branch=store.current_branch(root)
    )
    stale, stale_status = scan_stale(
        root, skip=args.no_remote, active_branches=frozenset(remote_claimed.values())
    )
    payload = build_graph(
        backlog,
        errors,
        date.today(),
        remote_done=remote_done,
        remote_done_status=remote_done_status,
        remote_claimed=remote_claimed,
        remote_claim_status=remote_claim_status,
        stale_branches=stale,
        stale_status=stale_status,
        base=base_commit(root),
    )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.text:
        print(render_text(payload))
        return 0

    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(payload, fragment=args.fragment), encoding="utf-8")
    print(render_text(payload))
    print("")
    print(f"🕸  작업 흐름 그래프 생성: {out}")
    return 0


if __name__ == "__main__":
    import _stdio  # 스크립트 실행이면 이 디렉터리가 sys.path[0]이다 (OPS-53)

    _stdio.ensure_utf8_stdio()
    raise SystemExit(main())
