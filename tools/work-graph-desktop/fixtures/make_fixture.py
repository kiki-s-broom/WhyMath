#!/usr/bin/env python3
"""작업 그래프 데스크톱 앱 픽스처 생성기 (HARN-206).

`scripts/harness/work_graph.py --json --no-remote`가 낸 **실제 페이로드**를 노드 40개 내외로
잘라 `fixtures/sample.json`을 만든다. 렌더러 계약 테스트(Playwright)와 브라우저 미리보기
(`?fixture=sample`)가 이 파일을 읽는다.

축소 규칙(재현 가능하도록 전부 여기 적는다):
  1. 흐름(frame.kind == "flow")을 index 순으로 훑되 크기 12 이하인 흐름만 통째로 넣는다.
     누적 노드 수가 `--target`(기본 28)을 넘으면 멈춘다. 큰 흐름(31·27개)은 제외한다 —
     40개 예산 안에서 여러 흐름·상태를 고루 보이는 것이 목적이다.
  2. 묶음(frame.kind == "group") 4종(진행 중·시작 가능·사람 작업·차단)에서 각각 앞 N개
     (`--group-take`, 기본 3)를 넣는다. 묶음 프레임은 남긴 창의 경계 상자로 줄인다.
  3. 연결선은 양 끝이 모두 남은 창인 것만 남긴다. `preds`/`succs`는 원본 그대로 둔다 —
     화면은 대장에 없는 키를 '완료·해소' 링크로 그리므로 원본 구조를 보존해도 된다.
  4. 프레임은 왼쪽 위부터 폭 `--row-width`(기본 3600) 안에서 차례로 다시 배치한다. 창·연결선
     좌표는 프레임과 같은 벡터로 옮긴다(상대 배치 보존).
  5. 집계(counts·open_tasks·open_gates·edge_total·flow_count 등)는 **남은 창에서 다시 센다**.
     이것은 픽스처를 만드는 쪽의 계산이지 앱의 계산이 아니다 — 앱은 counts를 그대로 그린다.
  6. `--no-remote`로 만든 페이로드에는 브랜치 창이 없다(원격 조회 생략). 브랜치 창의 화면
     계약을 검사하기 위해 **합성 브랜치 창 1개**(`b:claude/sample-branch`)를 붙인다.
     합성임을 노드의 `synthetic: true`로 표시한다.
  7. `sample_ok.json`은 같은 데이터에서 scans 3종을 ok로 바꾼 변형이다 — '확인 필요' 카드가
     사유 0건일 때의 화면을 검사하는 용도.

사용:
  python3 fixtures/make_fixture.py                      # 저장소 루트에서 work_graph.py 실행
  python3 fixtures/make_fixture.py --from payload.json  # 이미 있는 페이로드에서
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
WIN_W, WIN_H = 300, 176
PAD = 28  # 프레임 안쪽 여백(원본과 동일)
GAP = 72  # 프레임 사이 간격


def load_payload(src: str | None) -> dict:
    if src:
        return json.loads(Path(src).read_text(encoding="utf-8"))
    cmd = [sys.executable, "scripts/harness/work_graph.py", "--json", "--no-remote"]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise SystemExit(f"work_graph.py 실패 exit={proc.returncode}\n{proc.stderr}")
    return json.loads(proc.stdout)


def choose_keys(payload: dict, target: int, group_take: int) -> tuple[list[dict], set[str]]:
    """규칙 1·2 — 남길 프레임(깊은 복사)과 창 키 집합."""
    frames: list[dict] = []
    keep: set[str] = set()
    for f in payload["frames"]:
        if f["kind"] != "flow" or f["size"] > 12:
            continue
        if len(keep) + f["size"] > target:
            break
        frames.append(copy.deepcopy(f))
        keep.update(f["keys"])
    for f in payload["frames"]:
        if f["kind"] != "group":
            continue
        picked = f["keys"][:group_take]
        if not picked:
            continue
        g = copy.deepcopy(f)
        g["keys"] = picked
        g["size"] = len(picked)
        frames.append(g)
        keep.update(picked)
    return frames, keep


def shrink_group(frame: dict, nodes: dict) -> None:
    """규칙 2 — 묶음 프레임을 남은 창의 경계 상자(+여백)로 줄인다."""
    xs = [nodes[k]["x"] for k in frame["keys"]]
    ys = [nodes[k]["y"] for k in frame["keys"]]
    x0, y0 = min(xs) - PAD, min(ys) - 64
    x1 = max(nodes[k]["x"] + nodes[k]["w"] for k in frame["keys"]) + PAD
    y1 = max(nodes[k]["y"] + nodes[k]["h"] for k in frame["keys"]) + PAD
    frame.update({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})


def repack(frames: list[dict], nodes: dict, edges: list[dict], row_width: int) -> dict:
    """규칙 4 — 프레임을 행 단위로 다시 깔고 창·연결선을 같은 벡터로 옮긴다."""
    cx, cy, row_h = 0, 0, 0
    canvas_w = 0
    for f in frames:
        if cx > 0 and cx + f["w"] > row_width:
            cx, cy, row_h = 0, cy + row_h + GAP, 0
        dx, dy = cx - f["x"], cy - f["y"]
        f["x"], f["y"] = cx, cy
        for k in f["keys"]:
            nodes[k]["x"] += dx
            nodes[k]["y"] += dy
        for e in edges:
            if e["frame"] == f["id"]:
                e["points"] = [[px + dx, py + dy] for px, py in e["points"]]
        cx += f["w"] + GAP
        row_h = max(row_h, f["h"])
        canvas_w = max(canvas_w, cx - GAP)
    return {"w": canvas_w + 40, "h": cy + row_h + 40, "win_w": WIN_W, "win_h": WIN_H}


def add_synthetic_branch(frames: list[dict], nodes: dict, edges: list[dict]) -> None:
    """규칙 6 — 합성 브랜치 창 1개를 첫 흐름의 아래에 붙이고 done_on_branch 연결선을 잇는다."""
    flow = next(f for f in frames if f["kind"] == "flow")
    task_key = next(k for k in flow["keys"] if nodes[k]["kind"] == "task")
    task = nodes[task_key]
    branch = "claude/sample-branch"
    key = "b:" + branch
    bx, by = flow["x"] + PAD, flow["y"] + flow["h"]
    flow["h"] += WIN_H + PAD * 2
    flow["keys"].append(key)
    flow["size"] += 1
    edge_label = "이 브랜치에 완료분이 있다(미머지)"
    nodes[key] = {
        "key": key,
        "kind": "branch",
        "id": branch,
        "preds": [],
        "succs": [
            {
                "key": task_key,
                "id": task["id"],
                "kind": "task",
                "title": task["title"],
                "status": "todo",
                "open": True,
                "edge": edge_label,
            }
        ],
        "short": "sample-branch",
        "title": f"완료분 {task['short']} — 트렁크에 아직 합쳐지지 않았다",
        "state": "branch",
        "label": "미머지 브랜치",
        "reason": "합성 픽스처 — 원격 조회 없이 만든 브랜치 창",
        "detail": "",
        "verdict": "unscanned",
        "done_tasks": [task["id"]],
        "claimed_tasks": [],
        "foreign_tasks": [],
        "ahead": 3,
        "age_days": 2.5,
        "last_commit_at": "2026-09-27T09:00:00+00:00",
        "disposal_labels": [],
        "unlocks": 1,
        "wait_chain": [],
        "excerpt": [f"완료분: {task['short']}"],
        "acceptance": [],
        "notes": "",
        "cmd": f"git fetch origin {branch} && git log --oneline origin/main..origin/{branch}",
        "x": bx,
        "y": by,
        "w": WIN_W,
        "h": WIN_H,
        "frame": flow["id"],
        "flow": flow["index"],
        "synthetic": True,
    }
    task["preds"].append(
        {
            "key": key,
            "id": branch,
            "kind": "branch",
            "title": nodes[key]["title"],
            "status": "unmerged",
            "open": True,
            "edge": edge_label,
        }
    )
    edges.append(
        {
            "src": key,
            "dst": task_key,
            "kind": "done_on_branch",
            "back": False,
            "points": [[bx + WIN_W, by + WIN_H // 2], [task["x"], task["y"] + task["h"] // 2]],
            "frame": flow["id"],
        }
    )


def recount(payload: dict, frames: list[dict], nodes: dict, edges: list[dict]) -> None:
    """규칙 5 — 남은 창에서 집계를 다시 센다."""
    counts = {k: 0 for k in payload["counts"]}
    for n in nodes.values():
        st = "in_progress" if n["state"] == "review" else n["state"]
        counts[st] = counts.get(st, 0) + 1
    payload["counts"] = counts
    payload["open_tasks"] = sum(1 for n in nodes.values() if n["kind"] == "task")
    payload["open_gates"] = sum(1 for n in nodes.values() if n["kind"] == "gate")
    payload["branch_total"] = sum(1 for n in nodes.values() if n["kind"] == "branch")
    payload["edge_total"] = len(edges)
    flows = [f for f in frames if f["kind"] == "flow"]
    payload["flow_count"] = len(flows)
    payload["flow_node_total"] = sum(f["size"] for f in flows)
    payload["independent_total"] = len(nodes) - payload["flow_node_total"]
    payload["ready_order"] = [k for k in payload["ready_order"] if k in nodes]
    for f in frames:
        if f["kind"] == "flow":
            c: dict[str, int] = {}
            for k in f["keys"]:
                c[nodes[k]["state"]] = c.get(nodes[k]["state"], 0) + 1
            f["counts"] = c
            f["edge_count"] = sum(1 for e in edges if e["frame"] == f["id"])


def build(payload: dict, target: int, group_take: int, row_width: int) -> dict:
    frames, keep = choose_keys(payload, target, group_take)
    nodes = {k: copy.deepcopy(payload["nodes"][k]) for k in keep}
    edges = [copy.deepcopy(e) for e in payload["edges"] if e["src"] in keep and e["dst"] in keep]
    for f in frames:
        if f["kind"] == "group":
            shrink_group(f, nodes)
    add_synthetic_branch(frames, nodes, edges)
    out = copy.deepcopy({k: v for k, v in payload.items() if k not in ("nodes", "edges", "frames")})
    out["canvas"] = repack(frames, nodes, edges, row_width)
    out["frames"] = frames
    out["edges"] = edges
    out["nodes"] = nodes
    recount(out, frames, nodes, edges)
    out["fixture"] = {
        "source": "scripts/harness/work_graph.py --json --no-remote",
        "rule": "fixtures/make_fixture.py — 모듈 docstring의 축소 규칙 1~7",
        "target": target,
        "group_take": group_take,
    }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--from", dest="src", help="이미 있는 페이로드 JSON (없으면 work_graph.py 실행)"
    )
    ap.add_argument("--target", type=int, default=28)
    ap.add_argument("--group-take", type=int, default=3)
    ap.add_argument("--row-width", type=int, default=3600)
    ap.add_argument("--out-dir", default=str(HERE))
    args = ap.parse_args(argv)

    payload = load_payload(args.src)
    fixture = build(payload, args.target, args.group_take, args.row_width)
    out_dir = Path(args.out_dir)
    (out_dir / "sample.json").write_text(
        json.dumps(fixture, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    ok = copy.deepcopy(fixture)
    ok["scans"] = {k: {**v, "status": "ok"} for k, v in ok["scans"].items()}
    ok["errors"] = []
    (out_dir / "sample_ok.json").write_text(
        json.dumps(ok, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(
        f"sample.json: 창 {len(fixture['nodes'])} · 연결선 {len(fixture['edges'])} · "
        f"프레임 {len(fixture['frames'])} · counts {fixture['counts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
