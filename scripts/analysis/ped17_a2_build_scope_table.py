"""A2 범위 표 조립 — 개념 판정(분류_원자료)을 합쳐 CSV·요약을 만들고 완료 기준을 검사한다.

목적: PED-17 A2 "1차 범위 확정"의 산출물(범위 표 + 요약)을 *재현 가능하게* 만든다.
읽기 전용 입력: 원자 백본(`data/corpus/atom_graph_v1/graph.json`), T1 집계(`study_404_count.json`),
                 개념 판정 원자료(`ped17/산출물/A2/분류_원자료/*.jsonl`).
쓰기: `ped17/산출물/A2/범위표.csv`, `ped17/산출물/A2/요약.md`.

판정 단위와 규칙:
  - 세부개념(1,823개): 판정 원자료의 판정을 그대로 쓴다(사람이 읽듯 개념마다 내용을 읽고 판정한 결과).
  - 소단원·단원(860개): 이름만 있는 묶음 노드라 내용 판정 근거가 없다. 하위 세부개념
    *전부*가 "검산 가능"일 때만 "검산 가능", 하나라도 아니면 "검산 불가"로 모은다(애매하면 불가).
    하위 세부개념이 하나도 없으면 "미확인".
  - 원자료가 여러 파일이면 파일명 순서대로 읽고, 같은 code가 다시 나오면 *뒤 파일이 이긴다*
    (`재판정.jsonl`이 `chunk*.jsonl`보다 뒤). 어느 파일에서 왔는지 "판정 출처" 열에 남긴다.

완료 기준(검사 실패 시 종료 코드 1):
  1. 404 개념 전부(그래프 2,683개)가 표에 정확히 한 번씩 있다.
  2. 분류·판정 이유·검산 방법이 비어 있지 않다.
  3. 요약 숫자가 표를 다시 세어도 같다.

실행(저장소 루트에서):
  python3 scripts/analysis/ped17_a2_build_scope_table.py; echo "EXIT=$?"
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRAPH = ROOT / "data" / "corpus" / "atom_graph_v1" / "graph.json"
T1_JSON = ROOT / "ped17" / "산출물" / "T1" / "study_404_count.json"
A2_DIR = ROOT / "ped17" / "산출물" / "A2"
RAW_DIR = A2_DIR / "분류_원자료"
OUT_CSV = A2_DIR / "범위표.csv"
OUT_MD = A2_DIR / "요약.md"

POSSIBLE = "검산 가능"
IMPOSSIBLE = "검산 불가"
UNKNOWN = "미확인"
RAW_TO_CLASS = {"가능": POSSIBLE, "불가": IMPOSSIBLE}
LEVEL_ORDER = {"초등": 0, "중학": 1, "고등": 2, "대학": 3}
FIELDS = [
    "개념 ID",
    "이름",
    "분류",
    "판정 이유",
    "검산 방법",
    "학교급",
    "노드 단계",
    "경계 사례",
    "Gate A 학습목표 첫 개념",
    "판정 출처",
]


def _load_raw() -> tuple[dict[str, dict], Counter]:
    """원자료 JSONL → code별 판정(뒤 파일이 이김). 형식 오류는 즉시 예외."""
    judged: dict[str, dict] = {}
    per_file: Counter = Counter()
    for path in sorted(RAW_DIR.glob("*.jsonl")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            rec = json.loads(line)
            for key in ("code", "cls", "reason", "method", "border"):
                if key not in rec:
                    raise ValueError(f"{path.name}:{lineno} 필드 누락: {key}")
            if rec["cls"] not in RAW_TO_CLASS:
                raise ValueError(f"{path.name}:{lineno} cls 값이 가능/불가가 아님: {rec['cls']!r}")
            rec["_source"] = path.stem
            judged[rec["code"]] = rec
            per_file[path.stem] += 1
    return judged, per_file


def _rollup(
    node: dict, kids: dict[str, list[str]], leaf_class: dict[str, str]
) -> tuple[str, str, str]:
    """묶음 노드(소단원·단원) → (분류, 이유, 방법). 하위 세부개념 전부 가능일 때만 가능."""
    leaves: list[str] = []
    stack = list(kids.get(node["code"], []))
    while stack:
        code = stack.pop()
        if code in leaf_class:
            leaves.append(code)
        stack.extend(kids.get(code, []))
    if not leaves:
        return UNKNOWN, "하위 세부개념이 없어 내용을 판정할 근거가 없음", "해당 없음"
    n_ok = sum(1 for c in leaves if leaf_class[c] == POSSIBLE)
    if n_ok == len(leaves):
        return POSSIBLE, f"하위 세부개념 {len(leaves)}개 전부 검산 가능", "하위 세부개념의 검산 방법을 따름"
    return (
        IMPOSSIBLE,
        f"하위 세부개념 {len(leaves)}개 중 {n_ok}개만 검산 가능(전부 가능해야 가능)",
        "해당 없음",
    )


def _build_rows() -> list[dict]:
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    nodes = graph["concepts"]
    judged, _ = _load_raw()
    t1 = json.loads(T1_JSON.read_text(encoding="utf-8"))
    study_first = {x["concept"] for x in t1["범위1_학습목표"]["상세"]}

    kids: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        if n.get("parent_code"):
            kids[n["parent_code"]].append(n["code"])

    leaf_class: dict[str, str] = {}
    rows: list[dict] = []
    for n in nodes:
        if n["level"] != "세부개념":
            continue
        rec = judged.get(n["code"])
        if rec is None:
            cls, reason, method, border, src = UNKNOWN, "판정 원자료에 없음", "해당 없음", "", ""
        else:
            cls = RAW_TO_CLASS[rec["cls"]]
            reason, method, border, src = rec["reason"], rec["method"], rec["border"], rec["_source"]
        leaf_class[n["code"]] = cls
        rows.append(_row(n, cls, reason, method, "Y" if border else "", src, study_first))

    # 묶음 노드 — 세부개념 판정이 다 나온 뒤에 모은다
    for n in nodes:
        if n["level"] == "세부개념":
            continue
        cls, reason, method = _rollup(n, kids, leaf_class)
        rows.append(_row(n, cls, reason, method, "", "묶음 규칙", study_first))

    rows.sort(key=lambda r: (LEVEL_ORDER[r["학교급"]], r["_area"], r["개념 ID"]))
    return rows


def _row(n: dict, cls: str, reason: str, method: str, border: str, src: str, study_first: set) -> dict:
    return {
        "개념 ID": n["code"],
        "이름": n["name"],
        "분류": cls,
        "판정 이유": reason,
        "검산 방법": method,
        "학교급": n["school_level"],
        "노드 단계": n["level"],
        "경계 사례": border,
        "Gate A 학습목표 첫 개념": "Y" if n["code"] in study_first else "",
        "판정 출처": src,
        "_area": n.get("subject_area") or "",
    }


def _summary_line(label: str, rows: list[dict]) -> str:
    n = len(rows)
    ok = sum(1 for r in rows if r["분류"] == POSSIBLE)
    no = sum(1 for r in rows if r["분류"] == IMPOSSIBLE)
    unk = sum(1 for r in rows if r["분류"] == UNKNOWN)
    pct = (ok / n * 100) if n else 0.0
    tail = f", 미확인 {unk}개" if unk else ""
    return f"{label}: 전체 {n:,}개, 검산 가능 {ok:,}개, 검산 불가 {no:,}개{tail}, 가능 비율 {pct:.1f}%"


def _validate(rows: list[dict]) -> list[str]:
    errors: list[str] = []
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    want = [n["code"] for n in graph["concepts"]]
    got = [r["개념 ID"] for r in rows]
    if len(got) != len(set(got)):
        dup = [c for c, k in Counter(got).items() if k > 1]
        errors.append(f"표에 중복 개념 ID {len(dup)}건: {dup[:5]}")
    missing = sorted(set(want) - set(got))
    extra = sorted(set(got) - set(want))
    if missing:
        errors.append(f"표에 없는 개념 {len(missing)}건: {missing[:5]}")
    if extra:
        errors.append(f"그래프에 없는 개념 {len(extra)}건: {extra[:5]}")
    t1 = json.loads(T1_JSON.read_text(encoding="utf-8"))
    if len(want) != t1["범위2_원자개념"]["총"]:
        errors.append(f"그래프 개념 수 {len(want)} ≠ T1 404 개수 {t1['범위2_원자개념']['총']}")
    for col in ("분류", "판정 이유", "검산 방법"):
        blank = [r["개념 ID"] for r in rows if not str(r[col]).strip()]
        if blank:
            errors.append(f"'{col}' 빈 칸 {len(blank)}건: {blank[:5]}")
    bad = [r["개념 ID"] for r in rows if r["분류"] not in (POSSIBLE, IMPOSSIBLE, UNKNOWN)]
    if bad:
        errors.append(f"분류 값 오류 {len(bad)}건: {bad[:5]}")
    no_method = [r["개념 ID"] for r in rows if r["분류"] == POSSIBLE and r["검산 방법"] == "해당 없음"]
    if no_method:
        errors.append(f"검산 가능인데 검산 방법이 '해당 없음' {len(no_method)}건: {no_method[:5]}")
    return errors


def main() -> int:
    A2_DIR.mkdir(parents=True, exist_ok=True)
    rows = _build_rows()

    # newline=""는 csv 모듈 규약. utf-8-sig는 엑셀(한국어 Windows)에서 한글이 깨지지 않게 하는 BOM.
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    # 요약은 방금 쓴 CSV를 *다시 읽어서* 센다(메모리 값이 아니라 파일 기준 — 표와 요약의 일치 검증)
    with OUT_CSV.open(encoding="utf-8-sig", newline="") as f:
        reread = list(csv.DictReader(f))
    errors = _validate(reread)

    leaf = [r for r in reread if r["노드 단계"] == "세부개념"]
    study = [r for r in reread if r["Gate A 학습목표 첫 개념"] == "Y"]
    lines = [
        _summary_line("① 전체 404 개념(원자 백본 전 단계)", reread),
        _summary_line("② 세부개념만(학습 단위)", leaf),
        _summary_line("③ Gate A 학습목표 첫 개념", study),
    ]
    for level in LEVEL_ORDER:
        lines.append(_summary_line(f"   · 세부개념 {level}", [r for r in leaf if r["학교급"] == level]))
    border_n = sum(1 for r in leaf if r["경계 사례"] == "Y")
    lines.append(f"   · 세부개념 중 경계 사례(애매해서 불가로 둠): {border_n:,}개")

    print("\n".join(lines))
    OUT_MD.write_text(
        "# A2 요약 (자동 생성)\n\n" + "\n".join(f"- {l.strip()}" for l in lines) + "\n",
        encoding="utf-8",
    )
    if errors:
        print("\n[검사 실패]")
        for e in errors:
            print(" -", e)
        return 1
    print("\n[검사 통과] 전 개념이 표에 한 번씩 있고, 분류·이유·방법이 모두 채워졌다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
