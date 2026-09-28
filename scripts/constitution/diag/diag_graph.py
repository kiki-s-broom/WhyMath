# diag_graph.py — 개념(선수 관계) 그래프 불변식 점검 (단계 S03·S06, 표준북 20장)
# 보는 것: ID 중복, 없는 노드를 가리키는 선수 관계, 자기 자신이 선수, 순환, 학년 역전,
#          추이적 중복 간선(A→B→C인데 A→C도 있음), 고립 노드, ID 형식 혼재(KR-01), 폐기 노드 참조
# 입력: JSON / JSONL / CSV / XLSX(openpyxl 필요). 노드 목록 위치와 필드 이름은 옵션으로 지정한다.
# 예: python diag_graph.py --file 통합데이터셋.json --nodes-key "records.*.nodes.*" \
#        --id-field node_id --prereq-field 선수노드 --grade-field grade --out <결과>/raw
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict, deque
from pathlib import Path

from _diagcommon import md_table, setup_console, write_outputs
from diag_content import shape


def select(obj, path: str):
    """'records.*.nodes.*' 같은 경로로 노드 레코드들을 꺼낸다 ('*'는 목록·사전의 모든 항목)."""
    items = [obj]
    for seg in [s for s in path.split(".") if s]:
        nxt = []
        for it in items:
            if seg == "*":
                nxt.extend(
                    it.values() if isinstance(it, dict) else it if isinstance(it, list) else []
                )
            elif isinstance(it, dict) and seg in it:
                nxt.append(it[seg])
        items = nxt
    out = []
    for it in items:  # 마지막이 목록이면 펼친다
        out.extend(it if isinstance(it, list) else [it])
    return [x for x in out if isinstance(x, dict)]


def load(args) -> list[dict]:
    p, ext = args.file, args.file.suffix.lower()
    if ext == ".json":
        return select(json.loads(p.read_text(encoding="utf-8-sig")), args.nodes_key)
    if ext == ".jsonl":
        return [json.loads(l) for l in p.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
    if ext == ".csv":
        with p.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    if ext == ".xlsx":
        from openpyxl import load_workbook  # 없으면 ImportError로 알림

        wb = load_workbook(p, read_only=True, data_only=True)
        ws = wb[args.sheet] if args.sheet else wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        header = [str(h) if h is not None else "" for h in next(rows)]
        recs = [dict(zip(header, r)) for r in rows]
        wb.close()
        return recs
    raise SystemExit(f"⛔ 지원하지 않는 형식: {ext}")


def as_list(v, sep: str | None) -> list[str]:
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    s = str(v).strip()
    return [x.strip() for x in s.split(sep) if x.strip()] if sep else [s]


def main() -> int:
    setup_console()
    ap = argparse.ArgumentParser(description="개념 그래프 불변식 점검")
    ap.add_argument("--file", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument(
        "--nodes-key", default="", help="JSON 안 노드 목록 경로 (예: nodes 또는 records.*.nodes.*)"
    )
    ap.add_argument("--id-field", required=True)
    ap.add_argument("--prereq-field", help="선수 노드 ID 목록 필드 (목록 또는 구분자 문자열)")
    ap.add_argument(
        "--sep",
        help="선수 필드가 문자열일 때 구분자 (예: ,). 가운뎃점(·)은 개념 이름에도 쓰이므로 주의",
    )
    ap.add_argument("--grade-field", help="학년 필드 (숫자이거나 --grade-order로 순서 지정)")
    ap.add_argument("--grade-order", help='학년 순서 JSON 목록 (예: ["초1","초2",...,"고3"])')
    ap.add_argument("--deprecated-field", help="폐기 표시 필드 (참이면 폐기 노드)")
    ap.add_argument("--sheet", help="xlsx 시트 이름")
    args = ap.parse_args()
    if not args.prereq_field:
        raise SystemExit("⛔ --prereq-field 가 필요합니다")
    recs = load(args)
    order = {g: i for i, g in enumerate(json.loads(args.grade_order))} if args.grade_order else None

    ids = [str(r.get(args.id_field, "")).strip() for r in recs]
    dup = sorted(k for k, n in Counter(ids).items() if n > 1 and k)
    empty_ids = ids.count("")
    node = {i: r for i, r in zip(ids, recs) if i}
    prereq = {i: as_list(node[i].get(args.prereq_field), args.sep) for i in node}
    deprecated = {
        i
        for i in node
        if args.deprecated_field
        and str(node[i].get(args.deprecated_field)).lower() in ("true", "1", "yes", "y", "o")
    }

    def grade(i):
        g = node[i].get(args.grade_field) if args.grade_field else None
        if g is None or g == "":
            return None
        if order is not None:
            return order.get(str(g))
        try:
            return float(g)
        except (TypeError, ValueError):
            return None

    missing, selfloop, inversions, dep_ref, edges = [], [], [], [], []
    for v, ps in prereq.items():
        for p in ps:
            if p == v:
                selfloop.append(v)
            elif p not in node:
                missing.append({"node": v, "prereq": p})
            else:
                edges.append((p, v))
                if p in deprecated:
                    dep_ref.append({"node": v, "prereq": p})
                gp, gv = grade(p), grade(v)
                if gp is not None and gv is not None and gp > gv:
                    inversions.append(
                        {
                            "prereq": p,
                            "grade_pre": node[p].get(args.grade_field),
                            "node": v,
                            "grade_node": node[v].get(args.grade_field),
                        }
                    )
    succ, indeg = defaultdict(set), Counter()
    for p, v in set(edges):
        succ[p].add(v)
        indeg[v] += 1
    # 순환 찾기: 위상 정렬(Kahn)로 풀리지 않고 남는 노드가 순환에 걸린 노드
    q = deque(sorted(n for n in node if indeg[n] == 0))
    deg, topo = dict(indeg), []
    while q:
        n = q.popleft()
        topo.append(n)
        for m in sorted(succ[n]):
            deg[m] -= 1
            if deg[m] == 0:
                q.append(m)
    stuck = sorted(set(node) - set(topo))
    cycles = []
    seen = set()
    for start in stuck:  # 대표 순환 경로 몇 개를 꺼내 보여 준다
        if start in seen or len(cycles) >= 10:
            continue
        path, pos, cur = [], {}, start
        while cur not in pos:
            pos[cur] = len(path)
            path.append(cur)
            nxt = sorted(m for m in succ[cur] if m in stuck)
            if not nxt:
                break
            cur = nxt[0]
        if cur in pos:
            cyc = path[pos[cur] :] + [cur]
            cycles.append(cyc)
            seen.update(cyc)
    # 추이적 중복 간선 (순환이 없는 부분에서만)
    redundant = []
    if not stuck:
        bit = {n: 1 << i for i, n in enumerate(topo)}
        anc = {}
        for n in topo:
            a = 0
            for p in (x for x in prereq[n] if x in node and x != n):
                a |= anc.get(p, 0) | bit[p]
            anc[n] = a
        for v in topo:
            direct = [p for p in set(prereq[v]) if p in node and p != v]
            for p in direct:
                if any(anc[q] & bit[p] for q in direct if q != p):
                    redundant.append({"prereq": p, "node": v})
    has_out = {p for p, _ in edges}
    isolated = sorted(n for n in node if not prereq[n] and n not in has_out)
    shapes = Counter(shape(i) for i in node)

    data = {
        "file": str(args.file),
        "nodes": len(node),
        "records": len(recs),
        "edges": len(set(edges)),
        "summary": {
            "duplicate_ids": len(dup),
            "empty_ids": empty_ids,
            "missing_refs": len(missing),
            "self_loops": len(selfloop),
            "nodes_in_cycles": len(stuck),
            "grade_inversions": len(inversions),
            "redundant_edges": len(redundant) if not stuck else "순환 해소 후 계산",
            "isolated": len(isolated),
            "roots": sum(1 for n in node if not prereq[n]),
            "deprecated_referenced": len(dep_ref),
            "id_shapes": len(shapes),
        },
        "duplicate_ids": dup,
        "missing_refs": missing,
        "self_loops": selfloop,
        "cycles": cycles,
        "grade_inversions": inversions,
        "redundant_edges": redundant,
        "isolated": isolated,
        "deprecated_referenced": dep_ref,
        "id_shapes": dict(shapes.most_common(15)),
    }
    s = data["summary"]
    md = [
        "# 개념 그래프 불변식 점검 (표준북 20장)\n",
        f"파일: `{args.file}` · 노드 {len(node):,}개 · 선수 간선 {len(set(edges)):,}개 · 레코드 {len(recs):,}개\n",
        md_table(
            ["불변식", "위반 수"],
            [
                ["I1 순환에 걸린 노드", s["nodes_in_cycles"]],
                ["I7 없는 노드를 가리키는 선수 관계", s["missing_refs"]],
                ["자기 자신이 선수", s["self_loops"]],
                ["I4 학년 역전", s["grade_inversions"] if args.grade_field else "학년 필드 미지정"],
                ["I5 추이적 중복 간선", s["redundant_edges"]],
                ["ID 중복 / 빈 ID", f"{s['duplicate_ids']} / {s['empty_ids']}"],
                [
                    "폐기 노드를 선수로 참조",
                    s["deprecated_referenced"] if args.deprecated_field else "폐기 필드 미지정",
                ],
                ["고립 노드 (선수도 후속도 없음)", s["isolated"]],
                ["ID 모양 종류 (KR-01, 1이 이상적)", s["id_shapes"]],
            ],
        ),
        "\n## 순환 경로 예시\n",
        md_table(["경로"], [[" → ".join(c)] for c in cycles]),
        "\n## 없는 노드 참조\n",
        md_table(["노드", "선수(없음)"], [[m["node"], m["prereq"]] for m in missing], 40),
        "\n## 학년 역전\n",
        md_table(
            ["선수", "선수 학년", "노드", "노드 학년"],
            [[x["prereq"], x["grade_pre"], x["node"], x["grade_node"]] for x in inversions],
            40,
        ),
        "\n## ID 모양\n",
        md_table(["모양", "개수"], shapes.most_common(15)),
    ]
    write_outputs(args.out, "diag_graph", data, "\n".join(md) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
