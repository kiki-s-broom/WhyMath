"""T1 집계 — 학습 단계(`POST /v1/me/objectives/{id}/study`)에서 404가 나는 개념 수.

목적: PED-17 T1 "현재 404 개념 수"를 *저장소 스냅샷*으로 재현 가능하게 센다.
읽기 전용이다 — DB·네트워크에 접속하지 않고, 어떤 파일도 고치지 않는다.

방법(코드 경로를 그대로 따른다):
  `api/study.py::post_study_unit`은 학습목표의 첫 개념(`concept_nodes[0]`)으로 `supply()`를 부르고,
  `supply()`는 `l4/content_supply.py::resolve_concept_content`의 판정을 따른다.
    ① PK(`concept_content.code`)로 행을 찾는다. 없으면 K-12 행의 `atom_codes` 역조회.
       후보도 없으면 사유 NO_DSL → 404.
    ② 역조회면 검수 통과 행 우선, 없으면 code 오름차순 첫 행.
    ③ `is_supply_eligible(review_status)`가 False면 사유 UNREVIEWED → 404.
  이 스크립트는 ①~③을 코퍼스 파일 위에서 재현한다. 크로스워크 유도와 검수 술어는
  저장소 함수를 그대로 import해서 쓴다(손으로 다시 짜지 않는다).

한계(보고서에 적는다):
  - 운영 DB(Kiki 머신 `whymath-pg`)가 아니라 저장소 코퍼스 기준이다. 운영 DB의 승격 이력·
    `atom_codes` 이전 여부가 다르면 사유(NO_DSL/UNREVIEWED)는 달라질 수 있다.
  - ③을 통과한 개념도 렌더 단계에서 실패할 수 있다. 그래서 통과 수는 "404 아님 후보"로만 센다.
  - 학생 접속 로그(`study supply —` 로그 줄)는 이 세션에서 읽을 수 없어 쓰지 않았다.

실행(저장소 루트에서):
  PYTHONPATH=src/backend python3 scripts/analysis/ped17_t1_study_404_count.py

결과는 `ped17/산출물/T1/study_404_count.json`에 쓴다(T1 산출물 폴더).
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import yaml

from whymath_backend.l1.concept_atom_crosswalk.transfer import (
    derive_k12_content_atom_codes,
    load_concept_src_bridge,
    load_crosswalk_records,
)
from whymath_backend.l1.concept_content.review_gate import is_supply_eligible
from whymath_backend.schema.unit_dsl import UnitDSL

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data" / "corpus"
OUT_JSON = ROOT / "ped17" / "산출물" / "T1" / "study_404_count.json"

NO_DSL = "NO_DSL"
UNREVIEWED = "UNREVIEWED"
ELIGIBLE = "ELIGIBLE(404 아님 후보)"


def _load_content_rows() -> dict[str, dict]:
    """concept_content 코퍼스 2종 → code별 행. scope는 적재 규약대로 K-12 / 대학."""
    rows: dict[str, dict] = {}
    for folder, scope in (
        ("concept_content_v1", "K-12"),
        ("concept_content_university_v1", "대학"),
    ):
        payload = json.loads((CORPUS / folder / "content.json").read_text(encoding="utf-8"))
        for rec in payload["content"]:
            code = rec["code"]
            if code in rows:
                raise ValueError(f"콘텐츠 code 중복: {code}")
            rows[code] = {
                "code": code,
                "scope": scope,
                "review_status": rec.get("review_status"),
                "atom_codes": (),
            }
    return rows


def _attach_k12_atom_codes(rows: dict[str, dict]) -> int:
    """크로스워크 → K-12 행 atom_codes (transfer.py와 같은 유도 함수)."""
    crosswalk = load_crosswalk_records(CORPUS / "concept_atom_crosswalk_v1" / "crosswalk.jsonl")
    bridge = load_concept_src_bridge(CORPUS / "concept_graph_v1" / "graph.json")
    mapping = derive_k12_content_atom_codes(crosswalk, bridge)
    attached = 0
    for src_id, atom_codes in mapping.items():
        row = rows.get(src_id)
        # 갱신 SQL과 같은 조건 — scope='K-12' 행에만 붙인다.
        if row is not None and row["scope"] == "K-12":
            row["atom_codes"] = atom_codes
            attached += 1
    return attached


def _resolve(code: str, rows: dict[str, dict], by_atom: dict[str, list[dict]]) -> str:
    """resolve_concept_content ①~③ 재현 — 사유만 돌려준다."""
    row = rows.get(code)
    if row is None:
        found = sorted(by_atom.get(code, []), key=lambda r: r["code"])
        if not found:
            return NO_DSL
        row = next((r for r in found if is_supply_eligible(r["review_status"])), found[0])
    if not is_supply_eligible(row["review_status"]):
        return UNREVIEWED
    return ELIGIBLE


def _objectives() -> list[tuple[str, str, str]]:
    """units_v1 소단원 DSL → (objective_id, 첫 개념, 학교급 추정용 단원 id)."""
    out: list[tuple[str, str, str]] = []
    for path in sorted((CORPUS / "units_v1").glob("*.unit.yaml")):
        unit = UnitDSL.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        for obj in unit.objectives:
            first = obj.concept_nodes[0] if obj.concept_nodes else ""
            out.append((f"{unit.unit_id}:{obj.suffix}", first, unit.unit_id))
    return out


def main() -> int:
    rows = _load_content_rows()
    attached = _attach_k12_atom_codes(rows)
    by_atom: dict[str, list[dict]] = {}
    for row in rows.values():
        if row["scope"] != "K-12":  # find_k12_contents_by_atom의 scope 조건
            continue
        for atom in row["atom_codes"]:
            by_atom.setdefault(atom, []).append(row)

    # 범위 1 — 학습목표(= /study 요청 단위)
    objectives = _objectives()
    obj_reasons = Counter()
    obj_detail = []
    for objective_id, first, _unit in objectives:
        reason = _resolve(first, rows, by_atom) if first else "개념 미연결"
        obj_reasons[reason] += 1
        obj_detail.append({"objective_id": objective_id, "concept": first, "reason": reason})

    # 범위 2 — 원자 백본 전 개념(학습목표가 앞으로 가리킬 수 있는 모든 개념)
    atoms = json.loads((CORPUS / "atom_graph_v1" / "graph.json").read_text(encoding="utf-8"))
    atom_reasons = Counter()
    atom_by_level: dict[str, Counter] = {}
    for node in atoms["concepts"]:
        reason = _resolve(node["code"], rows, by_atom)
        atom_reasons[reason] += 1
        atom_by_level.setdefault(node.get("school_level") or "미기재", Counter())[reason] += 1

    # 범위 3 — 콘텐츠 행 자체의 검수 상태
    content_status = Counter((r["scope"], r["review_status"]) for r in rows.values())

    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",  # HARN-19 — 로케일(cp949) 디코드 금지
        check=True,
    ).stdout.strip()
    summary = {
        "판정_기준_커밋": head,
        "방법": "저장소 코퍼스 위에서 resolve_concept_content ①~③ 재현(DB·로그 미사용)",
        "K12_atom_codes_부착_행": attached,
        "범위1_학습목표": {
            "총": len(objectives),
            "사유별": dict(obj_reasons),
            "상세": obj_detail,
        },
        "범위2_원자개념": {
            "총": sum(atom_reasons.values()),
            "사유별": dict(atom_reasons),
            "학교급별": {k: dict(v) for k, v in sorted(atom_by_level.items())},
        },
        "범위3_콘텐츠행": {f"{s}|{st}": n for (s, st), n in sorted(content_status.items())},
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"판정 기준 커밋: {head}")
    print(f"범위1 학습목표 {len(objectives)}개 — {dict(obj_reasons)}")
    print(f"범위2 원자 개념 {sum(atom_reasons.values())}개 — {dict(atom_reasons)}")
    for level, counter in sorted(atom_by_level.items()):
        print(f"  · {level}: {dict(counter)}")
    print(f"범위3 콘텐츠 행 — {dict(content_status)}")
    print(f"저장: {OUT_JSON.relative_to(ROOT)}")
    # 404 아님 후보가 하나라도 있으면 1(사람이 읽고 확인할 신호), 전부 404면 0.
    return 1 if (obj_reasons.get(ELIGIBLE) or atom_reasons.get(ELIGIBLE)) else 0


if __name__ == "__main__":
    sys.exit(main())
