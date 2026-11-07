"""A3 집계 — 학습 단계 404 개념마다 생성 근거로 쓸 수 있는 소스 ID를 연결한다.

목적: PED-17 작업 A3 "근거 소스 정리"를 저장소 스냅샷으로 재현 가능하게 만든다.
읽기 전용이다 — DB·네트워크에 접속하지 않고, 코퍼스 파일을 고치지 않는다.
결과는 `ped17/산출물/A3/`에만 쓴다(T1 산출물은 건드리지 않는다).

404 목록:
  T1 스크립트(`ped17_t1_study_404_count.py`)의 판정 함수를 그대로 import해 쓴다.
  T1의 main()은 T1 결과 파일을 덮어쓰므로 부르지 않는다.
  범위 1 = 학습목표 34개, 범위 2 = 원자 백본 개념 2,683개(T1 보고와 같은 두 범위).

근거 연결 규칙(지어내지 않는다 — 데이터에 적힌 연결만 쓴다):
  - 직접: ①원자 노드의 `standard_codes`를 2022 개정 NCIC 성취기준(`standards_v1`)이나
    대학 성취기준(`standards_university_v1`)에서 찾은 것 ②대학 소단원 노드는
    `standards_university_v1/concept_standard_links.json`의 연결 행.
    학습목표는 소단원 DSL의 `standard_code`도 직접 근거로 더한다.
  - 간접: 노드에 성취기준이 없을 때(소단원·단원 노드), `parent_code`로 이어진
    하위 노드의 직접 근거를 모은 것. 데이터에 있는 상하위 관계만 쓴다.
  - 보조(판정에 안 셈): 크로스워크(`concept_atom_crosswalk_v1`)가 이 원자를 포함한
    개념 그래프 노드 ID. 크로스워크가 사람 검수 전(ai_estimated)이고 이름 유사도를
    쓰므로, 근거 유무 판정에는 넣지 않는다.
  - 연결하지 않음: KICE 평가기준(`achievement_criteria_v1`)은 2015 개정 코드라서,
    2022 개정 원자 코드와 글자가 같아도 내용이 같다는 보장이 없다. 개념별로 잇지 않는다.

판정: 직접 근거가 있으면 "직접", 간접만 있으면 "간접만", 둘 다 없으면 "근거 없음".

검증(완료 기준):
  근거 ID 전체에서 10개를 무작위로 뽑아, 구조화 파싱이 아니라 원본 파일의 *원문 텍스트*에서
  `"norm_id": "<ID>"` 문자열이 실제로 있는지 따로 확인한다. 씨앗값(seed)은 결과에 남긴다.
  변별력 확인으로 존재하지 않는 ID 1개를 같은 검사에 넣어 실패하는지도 본다.

실행(저장소 루트에서):
  PYTHONPATH=src/backend:scripts/analysis \
    python3 scripts/analysis/ped17_a3_evidence_links.py [--seed N]
종료 코드: 0 = 404 개념 전부 표에 있고 표본 10개 전부 존재 확인, 1 = 그렇지 않음.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import secrets
import subprocess
import sys
from collections import Counter
from pathlib import Path

import ped17_t1_study_404_count as t1

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data" / "corpus"
OUT_DIR = ROOT / "ped17" / "산출물" / "A3"

K12_STD = CORPUS / "standards_v1" / "standards.json"
UNIV_STD = CORPUS / "standards_university_v1" / "standards.json"
UNIV_LINKS = CORPUS / "standards_university_v1" / "concept_standard_links.json"
ATOM_GRAPH = CORPUS / "atom_graph_v1" / "graph.json"
CROSSWALK = CORPUS / "concept_atom_crosswalk_v1" / "crosswalk.jsonl"
CONCEPT_GRAPH = CORPUS / "concept_graph_v1" / "graph.json"

DIRECT, INDIRECT, NONE = "직접", "간접만", "근거 없음"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _standards() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """성취기준 코드 → norm_id. K-12는 2022 개정만(원자 백본 출처가 2022 고시)."""
    k12 = {
        s["code"]: s["norm_id"]
        for s in _load_json(K12_STD)["standards"]
        if s["curriculum_revision"] == "2022 개정"
    }
    univ = {s["code"]: s["norm_id"] for s in _load_json(UNIV_STD)["standards"]}
    # norm_id → 소스 파일 이름(검증·표 표기용)
    origin = {v: "standards_v1" for v in k12.values()}
    origin.update({v: "standards_university_v1" for v in univ.values()})
    return k12, univ, origin


def _direct_links(atoms: list[dict]) -> tuple[dict[str, list[str]], list[str]]:
    """원자 코드 → 직접 근거 norm_id 목록. 소스에서 못 찾은 코드는 따로 모은다."""
    k12, univ, _ = _standards()
    univ_links: dict[str, list[str]] = {}
    for link in _load_json(UNIV_LINKS)["links"]:
        univ_links.setdefault(link["concept_src_id"], []).append(link["norm_id"])

    direct: dict[str, list[str]] = {}
    unresolved: list[str] = []
    for node in atoms:
        ids: list[str] = []
        for code in node.get("standard_codes") or []:
            norm = k12.get(code) or univ.get(code)
            if norm is None:
                unresolved.append(f"{node['code']}→{code}")
            elif norm not in ids:
                ids.append(norm)
        for norm in univ_links.get(node["code"], []):
            if norm not in ids:
                ids.append(norm)
        direct[node["code"]] = ids
    return direct, unresolved


def _indirect_links(atoms: list[dict], direct: dict[str, list[str]]) -> dict[str, list[str]]:
    """직접 근거가 없는 노드 → 하위 노드(parent_code 체인)의 직접 근거 합집합."""
    children: dict[str, list[str]] = {}
    for node in atoms:
        if node.get("parent_code"):
            children.setdefault(node["parent_code"], []).append(node["code"])

    def collect(code: str, seen: set[str]) -> list[str]:
        out: list[str] = []
        for child in sorted(children.get(code, [])):
            if child in seen:  # 순환 방지
                continue
            seen.add(child)
            for norm in direct.get(child, []) or collect(child, seen):
                if norm not in out:
                    out.append(norm)
        return out

    out: dict[str, list[str]] = {}
    for node in atoms:
        code = node["code"]
        out[code] = [] if direct[code] else sorted(collect(code, {code}))
    return out


def _crosswalk_concepts() -> tuple[dict[str, list[str]], set[str]]:
    """원자 코드 → 크로스워크가 그 원자를 포함한 개념 그래프 concept_id(보조)."""
    by_atom: dict[str, list[str]] = {}
    for line in CROSSWALK.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        for atom in rec.get("atom_codes") or []:
            by_atom.setdefault(atom, []).append(rec["concept_id"])
    concept_ids = {c["concept_id"] for c in _load_json(CONCEPT_GRAPH)["concepts"]}
    return by_atom, concept_ids


def _reasons() -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    """T1 판정 함수로 원자별 404 사유를 다시 계산한다(T1 결과 파일은 쓰지 않음)."""
    rows = t1._load_content_rows()
    t1._attach_k12_atom_codes(rows)
    by_atom: dict[str, list[dict]] = {}
    for row in rows.values():
        if row["scope"] != "K-12":
            continue
        for atom in row["atom_codes"]:
            by_atom.setdefault(atom, []).append(row)
    atoms = _load_json(ATOM_GRAPH)["concepts"]
    reasons = {n["code"]: t1._resolve(n["code"], rows, by_atom) for n in atoms}
    objectives = [
        (oid, first, t1._resolve(first, rows, by_atom) if first else "개념 미연결")
        for oid, first, _unit in t1._objectives()
    ]
    return reasons, objectives


def _objective_standards() -> dict[str, str]:
    """학습목표 id → 소단원 DSL의 standard_code."""
    import yaml

    out: dict[str, str] = {}
    for path in sorted((CORPUS / "units_v1").glob("*.unit.yaml")):
        unit = yaml.safe_load(path.read_text(encoding="utf-8"))
        for obj in unit["objectives"]:
            out[f"{unit['unit_id']}:{obj['suffix']}"] = obj.get("standard_code") or ""
    return out


def _raw_exists(norm_id: str, origin: dict[str, str]) -> bool:
    """원본 파일 원문에 `"norm_id": "<ID>"`가 있는지 — 구조화 파싱과 독립된 검사."""
    folder = origin.get(norm_id)
    paths = [CORPUS / folder / "standards.json"] if folder else [K12_STD, UNIV_STD]
    needle = json.dumps({"norm_id": norm_id}, ensure_ascii=False)[1:-1]  # "norm_id": "<ID>"
    return any(needle in p.read_text(encoding="utf-8") for p in paths)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=None, help="표본 추출 씨앗값(생략하면 무작위)")
    args = parser.parse_args()
    seed = args.seed if args.seed is not None else secrets.randbelow(2**31)

    atoms = _load_json(ATOM_GRAPH)["concepts"]
    _, _, origin = _standards()
    direct, unresolved = _direct_links(atoms)
    indirect = _indirect_links(atoms, direct)
    xwalk, concept_ids = _crosswalk_concepts()
    reasons, objectives = _reasons()
    obj_std = _objective_standards()
    k12, univ, _ = _standards()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 표 1 — 원자 개념별 근거 연결(2,683행)
    verdicts: Counter = Counter()
    verdict_by_level: dict[str, Counter] = {}
    atom_rows = []
    for node in atoms:
        code = node["code"]
        d, i = direct[code], indirect[code]
        verdict = DIRECT if d else (INDIRECT if i else NONE)
        verdicts[verdict] += 1
        key = f"{node.get('school_level')}·{node.get('level')}"
        verdict_by_level.setdefault(key, Counter())[verdict] += 1
        atom_rows.append(
            {
                "개념ID": code,
                "개념명": node.get("name") or "",
                "학교급": node.get("school_level") or "",
                "노드수준": node.get("level") or "",
                "404사유": reasons[code],
                "판정": verdict,
                "직접근거ID": ";".join(d) if d else "",
                "간접근거ID(하위노드경유)": ";".join(i) if i else "",
                "근거ID목록": ";".join(d or i) if (d or i) else "근거 없음",
                "보조_개념그래프ID(크로스워크·검수전)": ";".join(xwalk.get(code, [])),
            }
        )
    with (OUT_DIR / "개념별_근거연결.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(atom_rows[0].keys()))
        writer.writeheader()
        writer.writerows(atom_rows)

    # 표 2 — 학습목표별 근거 연결(34행) — 목표의 standard_code + 첫 개념의 근거
    obj_rows = []
    for oid, first, reason in objectives:
        ids: list[str] = []
        sc = obj_std.get(oid, "")
        norm = k12.get(sc) or univ.get(sc)
        if norm:
            ids.append(norm)
        for n in direct.get(first, []) or indirect.get(first, []):
            if n not in ids:
                ids.append(n)
        obj_rows.append(
            {
                "학습목표ID": oid,
                "첫개념ID": first,
                "404사유": reason,
                "목표_성취기준코드": sc,
                "근거ID목록": ";".join(ids) if ids else "근거 없음",
            }
        )

    # 404 목록 대조 — 404 개념 전부가 표에 있는가
    not_404 = [c for c, r in reasons.items() if r == t1.ELIGIBLE]
    table_codes = {r["개념ID"] for r in atom_rows}
    missing_atoms = sorted(set(reasons) - table_codes)
    obj_ids_404 = {o for o, _f, r in objectives if r != t1.ELIGIBLE}
    missing_objs = sorted(obj_ids_404 - {r["학습목표ID"] for r in obj_rows})

    # 근거 ID 전수 존재 확인(파싱 기준) + 무작위 10개 원문 확인
    id_set: set[str] = set()
    for r in atom_rows:
        id_set.update(n for n in r["직접근거ID"].split(";") if n)
        id_set.update(n for n in r["간접근거ID(하위노드경유)"].split(";") if n)
    for r in obj_rows:
        id_set.update(n for n in r["근거ID목록"].split(";") if n and n != "근거 없음")
    all_ids = sorted(id_set)
    parsed_missing = [n for n in all_ids if n not in origin]
    xwalk_missing = sorted({c for cs in xwalk.values() for c in cs} - concept_ids)
    rng = random.Random(seed)
    sample = rng.sample(all_ids, min(10, len(all_ids)))
    sample_checks = [
        {"근거ID": n, "소스": origin.get(n, "?"), "원문에_존재": _raw_exists(n, origin)}
        for n in sample
    ]
    fake = "2022_가짜_99_99"  # 변별력 확인용 — 존재하면 안 된다
    fake_detected = not _raw_exists(fake, origin)

    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()
    summary = {
        "판정_기준_커밋": head,
        "404_원자개념_수": len(reasons),
        "404_아님_후보": not_404,
        "표에_없는_404_원자": missing_atoms,
        "표에_없는_404_학습목표": missing_objs,
        "원자_판정별": dict(verdicts),
        "원자_학교급·노드수준별_판정": {k: dict(v) for k, v in sorted(verdict_by_level.items())},
        "학습목표_수": len(obj_rows),
        "학습목표_근거없음": [r["학습목표ID"] for r in obj_rows if r["근거ID목록"] == "근거 없음"],
        "소스에서_못찾은_성취기준코드": unresolved,
        "근거ID_고유개수": len(all_ids),
        "근거ID_전수_파싱확인_누락": parsed_missing,
        "보조_크로스워크ID_개념그래프_누락": xwalk_missing,
        "표본_씨앗값": seed,
        "표본_원문확인": sample_checks,
        "변별력_가짜ID_불존재_판정": fake_detected,
        "학습목표_표": obj_rows,
    }
    (OUT_DIR / "근거연결_요약.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    ok = (
        not missing_atoms
        and not missing_objs
        and all(c["원문에_존재"] for c in sample_checks)
        and len(sample_checks) == min(10, len(all_ids))
        and fake_detected
        and not parsed_missing
    )
    print(f"판정 기준 커밋: {head}")
    print(f"404 원자 {len(reasons)}개 · 표 {len(atom_rows)}행 · 누락 {len(missing_atoms)}")
    print(f"404 아님 후보 {len(not_404)}")
    print(f"판정별: {dict(verdicts)}")
    print(f"학습목표 {len(obj_rows)}행 · 누락 {len(missing_objs)}")
    print(f"근거 ID 고유 {len(all_ids)}개 · 파싱 누락 {len(parsed_missing)}")
    print(f"소스에서 못 찾은 성취기준 코드 {len(unresolved)}건")
    marks = [f"{c['근거ID']}={'O' if c['원문에_존재'] else 'X'}" for c in sample_checks]
    print(f"표본(seed={seed}): " + ", ".join(marks))
    print(f"가짜 ID 불존재 판정: {fake_detected}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
