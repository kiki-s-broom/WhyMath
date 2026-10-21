#!/usr/bin/env bash
# 원자 백본 정본 재생성 체인 (KG-09 · KG-10) — 통합마스터 xlsx → 경계 엣지 병합 *전* 정본.
#
# 무엇을 하나: transform-v1 → dedup 14건 재적용(+병합흡수 notes 이식) → 대학 성취기준 채움(U2)
#              → 행동스킬 병합(SKB-02). 산출 $W/g.json 은 cross_band_edges_merge.pre_merge_view(정본)와
#              바이트 동일해야 한다(2026-10-20 실측: sha256 12936fb9… 일치).
# 하지 않는 것: 정본(data/corpus/atom_graph_v1/graph.json)을 쓰지 않는다. 정본 교체는 사람이
#              $W/g.json 을 복사한 뒤 아래 순서로 원장을 재생성·병합한다:
#                python3 scripts/build_cross_band_edges_s4_01.py
#                python3 -m data_pipeline.atom_graph.cross_band_edges_merge --merged-on <날짜>
#                python3 scripts/build_inter_course_edges_s4_01.py
#                python3 -m data_pipeline.atom_graph.narrative_promotion_merge \
#                    --ledger data/corpus/atom_graph_v1/narrative_edge_promotion_v2.json --merged-on <날짜>
#              그리고 _provenance.json 의 source_sha256·pipeline_input·regeneration_history 를 갱신한다.
#              역사 원장(KG-10 resolution · KG-11 reference/promotion · KG-12 reference v2)은 재생성하지
#              않는다 — 검수 행 번호의 정본이며 graph_history 가 묶인 정본을 되감아 --check 한다(KG-12).
#              MATCHES_CANON 비교의 pre_merge_view 는 경계 24건과 그 뒤 덧붙은 승격 v2 엣지를 함께 벗긴다.
# 입력 xlsx: 정본 통합마스터의 선수엣지_통합.from_유형만 치환한 파이프라인 입력 사본(데이터 카드 §1
#            pipeline_input 블록). 원본 xlsx 는 저장소에 없다(데이터 카드 §3 redaction) — Kiki 보관.
# 사용: bash scripts/regenerate_atom_backbone_v3.sh <pipeline_input.xlsx> <작업 디렉터리>
set -euo pipefail
XLSX="${1:?입력 xlsx 경로}"; W="${2:?작업 디렉터리}"
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$W"
( cd "$R/src/data-pipeline" && python3 -m data_pipeline.atom_graph transform-v1 --source "$XLSX" \
    --output-dir "$W/t" --standards "$R/data/corpus/standards_v1/standards.json" | tail -1 )
cd "$R"
# dedup 14건 재적용 + 병합흡수 notes 이식(dedup_merge_2026-07-28 관례: notes 가 비어 있을 때만)
python3 -I - "$W" "$R" <<'PY'
import json, sys
from pathlib import Path
W = Path(sys.argv[1]); R = Path(sys.argv[2])
g = json.load(open(W / "t/graph.json", encoding="utf-8"))
dm = json.load(open(R / "data/corpus/atom_graph_v1/dedup_merges_v1.json", encoding="utf-8"))
names = {c["code"]: c["name"] for c in g["concepts"]}
ret = {x["retired"]: x["canonical"] for x in dm["applied"]}
pair = {x["retired"]: x["pair_id"] for x in dm["applied"]}
keep = [c for c in g["concepts"] if c["code"] not in ret]
by = {c["code"]: c for c in keep}
for r, cano in ret.items():
    if cano in by and not by[cano].get("notes"):
        by[cano]["notes"] = (
            f"병합흡수: {r}({names[r]}) — 검수:Kiki 2026-07-28({pair[r]}·트랙 구분은 Curriculum Overlay)"
        )
g["concepts"] = keep
seen = set(); edges = []
for e in g["edges"]:
    f = ret.get(e["from_code"], e["from_code"]); t = ret.get(e["to_code"], e["to_code"])
    if f == t:
        continue
    k = (f, t, e["relation"])
    if k in seen:
        continue
    seen.add(k); e = dict(e); e["from_code"] = f; e["to_code"] = t; edges.append(e)
g["edges"] = edges
(W / "g.json").write_text(json.dumps(g, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"dedup 재적용: 노드 {len(keep)} 엣지 {len(edges)}")
PY
python3 -m data_pipeline.atom_graph.university_standard_fill --graph "$W/g.json" | tail -1
python3 -m data_pipeline.atom_graph merge-behavior-skills --graph "$W/g.json" | tail -1
python3 - "$W" "$R" <<'PY'
import json, sys, hashlib
sys.path.insert(0, sys.argv[2] + "/src/data-pipeline")
from data_pipeline.atom_graph.cross_band_edges_merge import graph_sha256, pre_merge_view
g = json.load(open(sys.argv[1] + "/g.json", encoding="utf-8"))
cur = json.load(open(sys.argv[2] + "/data/corpus/atom_graph_v1/graph.json", encoding="utf-8"))
print(f"REGEN_SHA={graph_sha256(g)}")
print(f"CANON_PRE_MERGE_SHA={graph_sha256(pre_merge_view(cur))}")
print(f"MATCHES_CANON={graph_sha256(g) == graph_sha256(pre_merge_view(cur))}")
PY
