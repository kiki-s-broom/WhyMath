#!/usr/bin/env python3
"""P3-01 대표 과정 후보 실측 — 학년/과목/단원별 Concept·Skill·Problem·Misconception 보유·연결.

지위
----
`P3-01-scope-freeze` acceptance ①(실측 표)·②(후보 비교)의 **재현 스크립트**다. 일회성 분석
스크립트이며 앱 코드가 아니다(테스트 불요 — 지시). 결과 문서:
`docs/reviews/p3_01_scope_candidates_2026-09-30.md`.

계수 범위 — 파일 기준
--------------------
저장소 코퍼스 파일(`data/corpus/**` — YAML/JSON=소스, DB=산출물 단방향 관례)을 센다. 운영 DB
(whymath-pg)는 이 컨테이너에 없다. 파일→DB 적재 규칙 중 **연결을 만드는 규칙**은 백엔드 적재기의
함수를 그대로 불러 재현한다(재구현 금지 — 규칙 드리프트 방지):

  · 문항→개념: `l1.problem_bank.populate.derive_src_to_primary_atom`
      (문항 `concepts[].concept_src_id`(구 437 src) → 크로스워크 `primary_atom_code` → 원자).
      런타임 `problem_concept` 적재와 같은 해석 체인이다(populate.py §원자 재연결).
  · 437↔원자 다리: `l1.concept_atom_crosswalk.transfer`의
    `load_crosswalk_records`·`load_concept_src_bridge`

축(무엇으로 묶었나)
------------------
  · 학년/과목/단원 = 2022 개정 성취기준 코퍼스(`standards_v1`, `curriculum_revision="2022 개정"`
    435행)의 `grade_band`·`subject`(과목 코드: 9수·10공수1·12미적Ⅰ …)·`domain`(영역=대단원)·
    `sub_domain`(소단원). 원자·오개념·문항을 전부 **성취기준 코드**로 이 축에 귀속한다
    (EOS-52 §2 동일).
  · Concept = 원자 백본 리프(`atom_graph_v1`, `level=세부개념`). 런타임 정본 축(S4-11). 구 437
    `concept_graph_v1`은 참고 열로만 센다.
  · Misconception = M-id 오개념 DB(`misconceptions_v1`) 행. `ATOM:<code>` 원자 유래 오개념은 원자
    1,823개 전부가 1:1로 가져 변별력이 없으므로 밀도 계산에서 제외하고 총량만 보고한다.
  · Skill = `skill_graph_v1`(27종). 원자↔스킬은 원자 `behavior_skills`(SKB-02 병합분).

연결(명시적 링크만 — 같은 성취기준에 속한다는 것은 '보유'이지 '연결'이 아니다)
-----------------------------------------------------------------------------
  · C↔P  문항 개념 태그 → primary 원자 (런타임 problem_concept 동일)
  · C↔M  M-id `concept_src_id`(구 437 src) → 크로스워크 primary 원자 (같은 다리·같은 귀속 규칙)
  · P↔M  문항 `distractor_map[].misconception_id`(kebab 또는 M-id) → crosslink → M-id
  · C↔S  원자 `behavior_skills`
  · P↔S  문항 `problem_type_codes` → problem_type `behavior_skills` (간접)
  · 선수   원자 엣지 `relation=prerequisite` 입·출 1건 이상

삼각 연결(밀도 분자) = 원자가 C↔S ∧ C↔P ∧ C↔M 을 모두 가진다. **이것은 P3-01의 대리 지표다** —
P3-02가 "완전 연결"(Prerequisite·Misconception·Solution·Hint·Pedagogy 포함)을 코드 한 곳에 정의하면
그 값이 정본이 된다.

실패 경로 (CLAUDE.md "측정·수집 도구를 성공 경로만 보고 설계 금지")
-----------------------------------------------------------------
  · 단계마다 결과 JSON을 즉시 flush한다(중간 실패 시 앞 단계 증거 보존).
  · 실패는 예외 타입명 + 메시지를 `errors`에 남기고 exit 1. 입력 0건(스캔 0건)은 실패로 친다.
  · 결과 JSON에 측정 시각·HEAD 커밋을 박는다(이번 실행 것인지 판별).

사용 (레포 루트):
    python scripts/analysis/p3_01_scope_inventory.py            # 표 출력 + JSON
    python scripts/analysis/p3_01_scope_inventory.py --json-only
종료 코드: 0=전 단계 성공 · 1=측정 실패(결과 JSON `errors`) · 2=인자 오류.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import math
import re
import subprocess
import sys
import traceback
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "data" / "corpus"
DEFAULT_OUT = REPO / "data" / "audit" / "p3_01_scope_inventory.json"

# 백엔드 적재기 함수 재사용(연결 규칙 드리프트 방지) — 읽기 전용 import.
sys.path.insert(0, str(REPO / "src" / "backend"))

REV_2022 = "2022 개정"
SLOT_TARGET = 6  # P3-04/05 문제 유형 6슬롯(대표·기본·응용·오개념 유발·진단·숙련도 확인)
DENSITY_TARGET = 0.95  # 지시문 목표 예시(Kiki가 P3-02 기준선 뒤 확정)


def _git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=True,
        )
        return out.stdout.strip()
    except Exception as exc:  # noqa: BLE001 — 측정 메타, 실패해도 타입명 기록
        return f"unknown({type(exc).__name__})"


class Run:
    """단계별 flush 러너 — 실패 원인(예외 타입명)을 남기고 계속 진행 여부를 판단한다."""

    def __init__(self, out: Path) -> None:
        self.out = out
        self.result: dict[str, Any] = {
            "task": "P3-01-scope-freeze",
            "measured_at": dt.datetime.now(dt.UTC).isoformat(),
            "head": _git_head(),
            "scope": "file-based (data/corpus/**) — 운영 DB 아님",
            "stages": {},
            "errors": [],
            "warnings": [],
        }

    def flush(self) -> None:
        self.out.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.result, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.out)

    def stage(self, name: str, fn: Any) -> Any:
        try:
            value = fn()
            self.result["stages"][name] = "ok"
            return value
        except Exception as exc:  # noqa: BLE001 — 원인 기록 후 상위에서 exit 1
            self.result["stages"][name] = f"error:{type(exc).__name__}"
            self.result["errors"].append(
                {
                    "stage": name,
                    "type": type(exc).__name__,
                    "message": str(exc)[:500],
                    "trace_tail": traceback.format_exc().splitlines()[-4:],
                }
            )
            return None
        finally:
            self.flush()


# ──────────────────────────────────────────────────────────────────────────
# 적재
# ──────────────────────────────────────────────────────────────────────────
def load_standards() -> dict[str, Any]:
    raw = json.loads((CORPUS / "standards_v1" / "standards.json").read_text(encoding="utf-8"))
    rows = raw["standards"]
    r22 = [r for r in rows if r.get("curriculum_revision") == REV_2022]
    r15_codes = {r["code"] for r in rows if r.get("curriculum_revision") != REV_2022}
    if not r22:
        raise ValueError("2022 개정 성취기준 0행 — 스캔 0건은 실패")
    by_code: dict[str, dict[str, Any]] = {}
    for r in r22:
        by_code[r["code"]] = {
            "code": r["code"],
            "grade_band": r.get("grade_band"),
            "subject": r.get("subject"),
            "domain": r.get("domain"),
            "sub_domain": r.get("sub_domain"),
        }
    uni = json.loads(
        (CORPUS / "standards_university_v1" / "standards.json").read_text(encoding="utf-8")
    )
    uni_codes = {r["code"] for r in uni["standards"]}
    return {
        "by_code": by_code,
        "rows_total": len(rows),
        "rows_2022": len(r22),
        "codes_2015_only": sorted(r15_codes - set(by_code)),
        "university_codes": uni_codes,
    }


def load_atoms() -> dict[str, Any]:
    g = json.loads((CORPUS / "atom_graph_v1" / "graph.json").read_text(encoding="utf-8"))
    nodes = g["concepts"]
    leaf = {n["code"]: n for n in nodes if n.get("level") == "세부개념"}
    if not leaf:
        raise ValueError("원자 리프 0건")
    prereq_touch: Counter[str] = Counter()
    for e in g["edges"]:
        if e.get("relation") == "prerequisite":
            prereq_touch[e["from_code"]] += 1
            prereq_touch[e["to_code"]] += 1
    return {
        "leaf": leaf,
        "total_nodes": len(nodes),
        "levels": dict(Counter(n.get("level") for n in nodes)),
        "edges": len(g["edges"]),
        "prereq_touch": prereq_touch,
    }


def load_bridge() -> dict[str, Any]:
    from whymath_backend.l1.concept_atom_crosswalk.transfer import (
        load_concept_src_bridge,
        load_crosswalk_records,
    )
    from whymath_backend.l1.problem_bank.populate import derive_src_to_primary_atom

    cw = load_crosswalk_records(CORPUS / "concept_atom_crosswalk_v1" / "crosswalk.jsonl")
    bridge = load_concept_src_bridge(CORPUS / "concept_graph_v1" / "graph.json")
    src_to_primary = derive_src_to_primary_atom(cw, bridge)
    g437 = json.loads((CORPUS / "concept_graph_v1" / "graph.json").read_text(encoding="utf-8"))
    c437 = g437["concepts"]
    return {
        "src_to_primary": src_to_primary,
        "crosswalk_rows": len(cw),
        "crosswalk_unmapped": sum(1 for r in cw if r.primary_atom_code is None),
        "concepts_437": c437,
    }


def load_misconceptions() -> dict[str, Any]:
    raw = json.loads(
        (CORPUS / "misconceptions_v1" / "misconceptions.json").read_text(encoding="utf-8")
    )
    rows = raw["misconceptions"]
    if not rows:
        raise ValueError("M-id 오개념 0행")
    xl = json.loads(
        (CORPUS / "misconception_crosslinks_v1" / "crosslinks.json").read_text(encoding="utf-8")
    )["crosslinks"]
    kebab_to_mids: dict[str, set[str]] = defaultdict(set)
    for r in xl:
        kebab_to_mids[r["kebab_id"]].add(r["mis_id"])
    from whymath_backend.l4.misconception.catalog import CATALOG

    machine = {
        e.id
        for e in CATALOG
        if getattr(e, "regex_signals", ()) or getattr(e, "canonical_wrong_form", ())
    }
    return {
        "rows": rows,
        "kebab_to_mids": dict(kebab_to_mids),
        "crosslinks": len(xl),
        "kebab_catalog": len(CATALOG),
        "kebab_machine": machine,
    }


def load_skills() -> dict[str, Any]:
    skills = [
        json.loads(line)
        for line in (CORPUS / "skill_graph_v1" / "skills.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    ptypes = [
        json.loads(line)
        for line in (CORPUS / "problem_type_graph_v1" / "problem_types.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    if not skills:
        raise ValueError("스킬 0건")
    return {
        "skills": {s["skill_id"]: s for s in skills},
        "ptype_skills": {p["problem_type_id"]: p.get("behavior_skills") or [] for p in ptypes},
    }


def load_problems() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    files = sorted(glob.glob(str(CORPUS / "problem_bank_*" / "problems.jsonl")))
    if not files:
        raise ValueError("문항 은행 0개")
    for f in files:
        bank = Path(f).parent.name
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            verify = d.get("verify") or {}
            qtext = d.get("question_text") or ""
            # 근사 중복 대리 지표: 숫자·공백을 접은 문면(P3-05 근사 중복 기준의 대체물 아님 — 참고).
            skeleton = " ".join(re.sub(r"\d+(?:\.\d+)?", "#", qtext).split())
            out.append(
                {
                    "bank": bank,
                    "slug": d.get("slug"),
                    "skeleton": skeleton,
                    "codes": list(d.get("achievement_standard_codes") or []),
                    "srcs": [c.get("concept_src_id") for c in d.get("concepts") or []],
                    "dm": [x.get("misconception_id") for x in d.get("distractor_map") or []],
                    "ptypes": list(d.get("problem_type_codes") or []),
                    "has_steps": bool(verify.get("solution_steps")),
                    "has_expl": bool((d.get("answer_explanation") or "").strip()),
                    "review": d.get("review_status"),
                    "tier": verify.get("verification_tier"),
                }
            )
    return out


# ──────────────────────────────────────────────────────────────────────────
# 계산
# ──────────────────────────────────────────────────────────────────────────
def compute(
    std: dict[str, Any],
    atoms: dict[str, Any],
    br: dict[str, Any],
    mis: dict[str, Any],
    sk: dict[str, Any],
    probs: list[dict[str, Any]],
    run: Run,
) -> dict[str, Any]:
    leaf = atoms["leaf"]
    s2p = br["src_to_primary"]
    by_code = std["by_code"]

    # 원자 → 코드
    atom_codes: dict[str, list[str]] = {
        a: list(n.get("standard_codes") or []) for a, n in leaf.items()
    }
    code_atoms: dict[str, set[str]] = defaultdict(set)
    for a, cs in atom_codes.items():
        for c in cs:
            code_atoms[c].add(a)

    # 문항 → primary 원자(명시적 C↔P)
    atom_problems: dict[str, set[int]] = defaultdict(set)
    prob_atoms: list[set[str]] = []
    unresolved_src: Counter[str] = Counter()
    for i, p in enumerate(probs):
        resolved = set()
        for s in p["srcs"]:
            a = s2p.get(s)
            if a is None:
                unresolved_src[str(s)] += 1
                continue
            if a not in leaf:
                unresolved_src[f"(비리프){s}->{a}"] += 1
                continue
            resolved.add(a)
            atom_problems[a].add(i)
        prob_atoms.append(resolved)

    # 문항 → M-id (P↔M)
    kebab_to_mids = mis["kebab_to_mids"]
    mid_set = {r["mis_id"] for r in mis["rows"]}
    prob_mids: list[set[str]] = []
    prob_kebabs: list[set[str]] = []
    unresolved_dm: Counter[str] = Counter()
    mid_problems: dict[str, set[int]] = defaultdict(set)
    for i, p in enumerate(probs):
        ms: set[str] = set()
        ks: set[str] = set()
        for mid in p["dm"]:
            if mid is None:
                continue
            if mid in mid_set:
                ms.add(mid)
            elif mid in kebab_to_mids:
                ks.add(mid)
                ms |= kebab_to_mids[mid]
            else:
                unresolved_dm[mid] += 1
        for m in ms:
            mid_problems[m].add(i)
        prob_mids.append(ms)
        prob_kebabs.append(ks)

    # M-id → primary 원자 (C↔M)
    atom_mids: dict[str, set[str]] = defaultdict(set)
    mid_atom: dict[str, str | None] = {}
    code_mids: dict[str, set[str]] = defaultdict(set)
    mid_row = {}
    for r in mis["rows"]:
        mid = r["mis_id"]
        mid_row[mid] = r
        a = s2p.get(r.get("concept_src_id"))
        if a is not None and a in leaf:
            atom_mids[a].add(mid)
            mid_atom[mid] = a
        else:
            mid_atom[mid] = None
        if r.get("standard_code"):
            code_mids[r["standard_code"]].add(mid)

    # 코드 → 문항(보유)
    code_problems: dict[str, set[int]] = defaultdict(set)
    code_not_2022: Counter[str] = Counter()
    for i, p in enumerate(probs):
        for c in p["codes"]:
            code_problems[c].add(i)
            if c not in by_code:
                code_not_2022[c] += 1

    # 코드 → 437 개념 (구 437 축 — 참고 열 + '성취기준당 1개념' 입도 비교용)
    code_c437: dict[str, set[str]] = defaultdict(set)
    c437_by_id: dict[str, dict[str, Any]] = {}
    for c in br["concepts_437"]:
        c437_by_id[c["concept_id"]] = c
        for code in c.get("standard_codes") or []:
            code_c437[code].add(c["concept_id"])
    # 437 src → 문항·M-id (437 입도의 명시 연결 — 원자 해석 이전 단계)
    src_problems: dict[str, set[int]] = defaultdict(set)
    for i, p in enumerate(probs):
        for s in p["srcs"]:
            if s:
                src_problems[s].add(i)
    src_mids: dict[str, set[str]] = defaultdict(set)
    for r in mis["rows"]:
        if r.get("concept_src_id"):
            src_mids[r["concept_src_id"]].add(r["mis_id"])

    ptype_skills = sk["ptype_skills"]
    machine = mis["kebab_machine"]
    prereq_touch = atoms["prereq_touch"]

    def unit_metrics(codes: set[str]) -> dict[str, Any]:
        atoms_s = set().union(*(code_atoms.get(c, set()) for c in codes)) if codes else set()
        probs_s = set().union(*(code_problems.get(c, set()) for c in codes)) if codes else set()
        mids_s = set().union(*(code_mids.get(c, set()) for c in codes)) if codes else set()
        c437_s = set().union(*(code_c437.get(c, set()) for c in codes)) if codes else set()

        a_skill = {a for a in atoms_s if leaf[a].get("behavior_skills")}
        a_prob = {a for a in atoms_s if atom_problems.get(a)}
        a_mis = {a for a in atoms_s if atom_mids.get(a)}
        a_pre = {a for a in atoms_s if prereq_touch.get(a)}
        a_tri = a_skill & a_prob & a_mis
        skills_distinct = set()
        for a in atoms_s:
            skills_distinct.update(leaf[a].get("behavior_skills") or [])
        cs_links = sum(len(leaf[a].get("behavior_skills") or []) for a in atoms_s)

        # 문항 측
        p_linked_in = {i for i in probs_s if prob_atoms[i] & atoms_s}
        p_linked_out = {i for i in probs_s if prob_atoms[i] and not (prob_atoms[i] & atoms_s)}
        p_unlinked = {i for i in probs_s if not prob_atoms[i]}
        p_mis = {i for i in probs_s if prob_mids[i]}
        p_mis_in = {i for i in probs_s if prob_mids[i] & mids_s}
        p_ptype = {i for i in probs_s if probs[i]["ptypes"]}
        p_skill = {i for i in probs_s if any(ptype_skills.get(t) for t in probs[i]["ptypes"])}
        p_solution = {i for i in probs_s if probs[i]["has_steps"] or probs[i]["has_expl"]}
        p_steps = {i for i in probs_s if probs[i]["has_steps"]}
        p_approved = {i for i in probs_s if probs[i]["review"] == "approved"}
        p_orphan = {i for i in probs_s if not (prob_atoms[i] & atoms_s) and not prob_mids[i]}
        cp_links = sum(1 for i in probs_s for a in prob_atoms[i] if a in atoms_s)
        pm_links = sum(len(prob_mids[i] & mids_s) for i in probs_s)
        ptypes_distinct = {t for i in probs_s for t in probs[i]["ptypes"]}
        banks = Counter(probs[i]["bank"] for i in probs_s)

        # 오개념 측
        m_concept = {m for m in mids_s if mid_atom.get(m) in atoms_s}
        m_prob_any = {m for m in mids_s if mid_problems.get(m)}
        m_prob_in = {m for m in mids_s if mid_problems.get(m, set()) & probs_s}
        m_skill = {m for m in mids_s if mid_row[m].get("behavior_skills")}
        m_machine = set()
        for m in mids_s:
            for k, mids_k in kebab_to_mids.items():
                if m in mids_k and k in machine:
                    m_machine.add(m)
        m_kebab = {m for m in mids_s if any(m in v for v in kebab_to_mids.values())}
        m_orphan = {m for m in mids_s if m not in m_concept and not mid_problems.get(m)}
        cm_links = sum(len(atom_mids.get(a, set())) for a in atoms_s)

        # 고아 개념 = 문항·M-id 명시 연결 둘 다 없음
        a_orphan = {a for a in atoms_s if not atom_problems.get(a) and not atom_mids.get(a)}

        # 현 적재 규칙의 C↔P 천장: 문항 태그는 437 src → primary 원자로만 해석된다(populate.py).
        # 범위 안 437 개념들의 primary 원자만 문항을 받을 수 있다.
        primary_in_scope = {s2p.get(c437_by_id[cid]["source_id"]) for cid in c437_s} & atoms_s

        # 437 입도(성취기준당 1개념 — 고교는 437 개념 = 성취기준 1:1)
        k_prob = {cid for cid in c437_s if src_problems.get(c437_by_id[cid]["source_id"])}
        k_mid = {cid for cid in c437_s if src_mids.get(c437_by_id[cid]["source_id"])}
        k_skill = {cid for cid in c437_s if c437_by_id[cid].get("behavior_skills")}
        k_tri = k_prob & k_mid & k_skill
        n437 = len(c437_s)
        need437 = max(0, math.ceil(DENSITY_TARGET * n437) - len(k_tri)) if n437 else 0
        miss437 = sorted(
            (
                (cid not in k_skill) + (cid not in k_prob) + (cid not in k_mid),
                cid,
                (int(cid not in k_skill), int(cid not in k_prob), int(cid not in k_mid)),
            )
            for cid in c437_s - k_tri
        )[:need437]

        # 437 입도 개념별 작업 분해 — 문항 0 / 고유 문면 6 미만 / 오개념 연결 문항 없음
        k_zero_prob = {cid for cid in c437_s if not src_problems.get(c437_by_id[cid]["source_id"])}
        k_lt6_skel = {
            cid
            for cid in c437_s - k_zero_prob
            if len({probs[i]["skeleton"] for i in src_problems[c437_by_id[cid]["source_id"]]})
            < SLOT_TARGET
        }
        k_no_mlinked_prob = {
            cid
            for cid in c437_s
            if not any(prob_mids[i] for i in src_problems.get(c437_by_id[cid]["source_id"], set()))
        }
        # 오개념 유발 문항을 만들려면 distractor_map.misconception_id가 L4 kebab 카탈로그
        # id여야 하고(schema/problem.py DistractorEntry), kebab→M-id는 crosslink(수동 검수
        # 게이트)로만 이어진다. 그 개념의 M-id 중 crosslink된 것이 하나도 없으면
        # kebab 신설 + crosslink 검수가 선행돼야 한다.
        crosslinked_mids = {m for v in kebab_to_mids.values() for m in v}
        k_no_crosslinked_mid = {
            cid
            for cid in c437_s
            if not (src_mids.get(c437_by_id[cid]["source_id"], set()) & crosslinked_mids)
        }
        # 6슬롯 결손(437 입도·고유 문면 기준): 개념별 max(0, 6 − 고유 문면 수)
        slot6_437 = sum(
            max(
                0,
                SLOT_TARGET
                - len(
                    {
                        probs[i]["skeleton"]
                        for i in src_problems.get(c437_by_id[cid]["source_id"], set())
                    }
                ),
            )
            for cid in c437_s
        )

        # 스킬 커버: 범위 스킬 중 문항이 닿는 것
        unit_skills = set()
        for a in atoms_s:
            unit_skills.update(leaf[a].get("behavior_skills") or [])
        skills_via_ptype = {
            s for i in probs_s for t in probs[i]["ptypes"] for s in ptype_skills.get(t, [])
        } & unit_skills
        skills_via_atom = {
            s
            for a in atoms_s
            if atom_problems.get(a)
            for s in (leaf[a].get("behavior_skills") or [])
        }
        skeletons = {probs[i]["skeleton"] for i in probs_s if probs[i]["skeleton"]}
        # 런타임 기준 보유량: 런타임은 문항의 성취기준을 파일 태그가 아니라
        # problem_concept → atom_node.standard_codes 로 얻는다
        # (api/gating.py _fetch_achievement_codes).
        probs_rt = (
            set().union(*(atom_problems.get(a, set()) for a in atoms_s)) if atoms_s else set()
        )

        # 6슬롯 결손(상한 — 리프 원자 전부를 핵심으로 가정)
        slot_deficit = sum(max(0, SLOT_TARGET - len(atom_problems.get(a, set()))) for a in atoms_s)

        # 95% 삼각 도달 최소 작업 — 결손 링크 수가 적은 원자부터 채운다
        n = len(atoms_s)
        need = max(0, math.ceil(DENSITY_TARGET * n) - len(a_tri)) if n else 0
        missing = []
        for a in atoms_s - a_tri:
            miss = (
                (0 if a in a_skill else 1),
                (0 if a in a_prob else 1),
                (0 if a in a_mis else 1),
            )
            missing.append((sum(miss), a, miss))
        missing.sort()
        chosen = missing[:need]
        add_skill = sum(m[2][0] for m in chosen)
        add_prob = sum(m[2][1] for m in chosen)
        add_mis = sum(m[2][2] for m in chosen)

        return {
            "standards": len(codes),
            "concepts_atom": n,
            "concepts_437": len(c437_s),
            "skills_distinct": len(skills_distinct),
            "problems": len(probs_s),
            "misconceptions_mid": len(mids_s),
            # 연결 건수
            "links_cs": cs_links,
            "links_cp": cp_links,
            "links_cm": cm_links,
            "links_pm": pm_links,
            # 원자 측 연결률
            "atoms_with_skill": len(a_skill),
            "atoms_with_problem": len(a_prob),
            "atoms_with_mid": len(a_mis),
            "atoms_with_prereq": len(a_pre),
            "atoms_triangle": len(a_tri),
            "density_triangle": round(len(a_tri) / n, 4) if n else None,
            "orphan_atoms": len(a_orphan),
            # 문항 측
            "problems_linked_in_unit": len(p_linked_in),
            "problems_linked_out_unit": len(p_linked_out),
            "problems_concept_unlinked": len(p_unlinked),
            "problems_with_mid": len(p_mis),
            "problems_with_mid_in_unit": len(p_mis_in),
            "problems_with_ptype": len(p_ptype),
            "problems_with_skill_via_ptype": len(p_skill),
            "problems_with_solution": len(p_solution),
            "problems_with_solution_steps": len(p_steps),
            "problems_approved": len(p_approved),
            "orphan_problems": len(p_orphan),
            "ptypes_distinct": len(ptypes_distinct),
            "banks": dict(banks.most_common()),
            # 오개념 측
            "mids_with_concept": len(m_concept),
            "mids_with_problem_any": len(m_prob_any),
            "mids_with_problem_in_unit": len(m_prob_in),
            "mids_with_skill": len(m_skill),
            "mids_with_kebab": len(m_kebab),
            "mids_machine_detectable": len(m_machine),
            "orphan_mids": len(m_orphan),
            # 95% 작업량
            "work95_target_atoms": math.ceil(DENSITY_TARGET * n) if n else 0,
            "work95_atoms_to_fix": need,
            "work95_add_skill_tags": add_skill,
            "work95_add_problem_links": add_prob,
            "work95_add_mid_links": add_mis,
            "slot6_deficit_upper": slot_deficit,
            # 현 적재 규칙 천장
            "primary_atoms_in_scope": len(primary_in_scope),
            "cp_ceiling_current_loader": round(len(primary_in_scope) / n, 4) if n else None,
            # 437 입도
            "c437_with_problem": len(k_prob),
            "c437_with_mid": len(k_mid),
            "c437_with_skill": len(k_skill),
            "c437_triangle": len(k_tri),
            "density_437": round(len(k_tri) / n437, 4) if n437 else None,
            "work95_437_to_fix": need437,
            "work95_437_add_skill": sum(m[2][0] for m in miss437),
            "work95_437_add_problem": sum(m[2][1] for m in miss437),
            "work95_437_add_mid": sum(m[2][2] for m in miss437),
            "c437_zero_problem": len(k_zero_prob),
            "c437_lt6_skeletons": len(k_lt6_skel),
            "c437_no_misconception_linked_problem": len(k_no_mlinked_prob),
            "c437_no_crosslinked_mid": len(k_no_crosslinked_mid),
            # 목록(문서 §3 작업량 근거) — 437 개념의 성취기준 코드로 표기
            "list_c437_zero_problem": sorted(
                ",".join(c437_by_id[cid].get("standard_codes") or [cid]) for cid in k_zero_prob
            ),
            "list_c437_lt6_skeletons": sorted(
                ",".join(c437_by_id[cid].get("standard_codes") or [cid]) for cid in k_lt6_skel
            ),
            "list_c437_no_misconception_linked_problem": sorted(
                ",".join(c437_by_id[cid].get("standard_codes") or [cid])
                for cid in k_no_mlinked_prob
            ),
            "slot6_deficit_437_by_skeleton": slot6_437,
            # 스킬·다양성
            "unit_skills": len(unit_skills),
            "skills_with_problem_via_ptype": len(skills_via_ptype),
            "skills_with_problem_via_atom": len(skills_via_atom),
            "problem_skeletons_distinct": len(skeletons),
            "problems_runtime": len(probs_rt),
            "problems_runtime_from_other_codes": len(probs_rt - probs_s),
            "mids_without_problem": len(mids_s) - len(m_prob_any),
            "atoms_list": sorted(atoms_s),
        }

    def per_code(codes: list[str]) -> list[dict[str, Any]]:
        rows = []
        for c in codes:
            atoms_s = code_atoms.get(c, set())
            probs_s = code_problems.get(c, set())
            mids_s = code_mids.get(c, set())
            prim = {
                s2p.get(c437_by_id[cid]["source_id"]) for cid in code_c437.get(c, set())
            } & atoms_s
            rows.append(
                {
                    "code": c,
                    "sub_domain": by_code[c]["sub_domain"] if c in by_code else None,
                    "atoms": len(atoms_s),
                    "primary_atoms": len(prim),
                    "atoms_with_problem": sum(1 for a in atoms_s if atom_problems.get(a)),
                    "problems": len(probs_s),
                    "problems_linked_in_code": sum(1 for i in probs_s if prob_atoms[i] & atoms_s),
                    "problems_runtime": len(
                        set().union(*(atom_problems.get(a, set()) for a in atoms_s))
                        if atoms_s
                        else set()
                    ),
                    "problems_with_mid": sum(1 for i in probs_s if prob_mids[i]),
                    "problems_skeletons": len({probs[i]["skeleton"] for i in probs_s}),
                    "mids": len(mids_s),
                    "mids_with_problem": sum(1 for m in mids_s if mid_problems.get(m)),
                    "atoms_with_mid": sum(1 for a in atoms_s if atom_mids.get(a)),
                }
            )
        return rows

    # 축 구성
    subj_codes: dict[str, set[str]] = defaultdict(set)
    dom_codes: dict[tuple[str, str], set[str]] = defaultdict(set)
    sub_codes: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    subj_band: dict[str, str] = {}
    for c, r in by_code.items():
        subj_codes[r["subject"]].add(c)
        dom_codes[(r["subject"], r["domain"])].add(c)
        sub_codes[(r["subject"], r["domain"], r["sub_domain"])].add(c)
        subj_band[r["subject"]] = r["grade_band"]

    # 원자 학년(고등은 과목별 고1/고2/고3 — atom grade_band)
    subj_grade: dict[str, Counter[str]] = defaultdict(Counter)
    for a, n in leaf.items():
        for c in atom_codes[a]:
            if c in by_code:
                subj_grade[by_code[c]["subject"]][
                    f"{n.get('school_level')}·{n.get('grade_band')}"
                ] += 1

    def strip(m: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in m.items() if k != "atoms_list"}

    by_subject = {}
    for s, cs in sorted(subj_codes.items()):
        m = unit_metrics(cs)
        m["grade_band"] = subj_band[s]
        m["atom_grade"] = dict(subj_grade[s])
        by_subject[s] = strip(m)
    by_domain = []
    for (s, d), cs in sorted(dom_codes.items()):
        m = strip(unit_metrics(cs))
        m.update({"subject": s, "domain": d, "codes": sorted(cs)})
        by_domain.append(m)
    by_subdomain = []
    for (s, d, sd), cs in sorted(sub_codes.items()):
        m = strip(unit_metrics(cs))
        m.update({"subject": s, "domain": d, "sub_domain": sd, "codes": sorted(cs)})
        by_subdomain.append(m)

    # 전역
    all22 = set(by_code)
    school_total = strip(unit_metrics(all22))
    probs_2022 = {i for i in range(len(probs)) if any(c in by_code for c in probs[i]["codes"])}
    probs_uni = {
        i for i in range(len(probs)) if any(c in std["university_codes"] for c in probs[i]["codes"])
    }
    probs_none = {i for i in range(len(probs)) if not probs[i]["codes"]}
    probs_other = set(range(len(probs))) - probs_2022 - probs_uni - probs_none

    distinct_primary_atoms = {a for s in prob_atoms for a in s}
    global_ = {
        "standards_rows_total": std["rows_total"],
        "standards_2022": std["rows_2022"],
        "university_standards": len(std["university_codes"]),
        "atoms_total_nodes": atoms["total_nodes"],
        "atoms_levels": atoms["levels"],
        "atoms_leaf": len(leaf),
        "atom_edges": atoms["edges"],
        "concepts_437": len(br["concepts_437"]),
        "crosswalk_rows": br["crosswalk_rows"],
        "crosswalk_unmapped": br["crosswalk_unmapped"],
        "src_to_primary_size": len(s2p),
        "misconceptions_mid": len(mis["rows"]),
        "misconceptions_atom_stub_equiv": len(leaf),  # ATOM:<code> — 리프 1:1(변별력 없음)
        "kebab_catalog": mis["kebab_catalog"],
        "kebab_machine_detectable": len(machine),
        "crosslinks": mis["crosslinks"],
        "skills": len(sk["skills"]),
        "problem_types": len(sk["ptype_skills"]),
        "problems_total": len(probs),
        "problem_banks": len({p["bank"] for p in probs}),
        "problems_2022_coded": len(probs_2022),
        "problems_university_coded": len(probs_uni),
        "problems_no_code": len(probs_none),
        "problems_other_code": len(probs_other),
        "problem_codes_not_2022_top": dict(code_not_2022.most_common(15)),
        "problems_concept_resolved": sum(1 for s in prob_atoms if s),
        "problems_concept_unresolved": sum(1 for s in prob_atoms if not s),
        "distinct_primary_atoms_hit_by_problems": len(distinct_primary_atoms),
        "unresolved_concept_src_top": dict(unresolved_src.most_common(10)),
        "problems_with_mid": sum(1 for s in prob_mids if s),
        "unresolved_distractor_ids_top": dict(unresolved_dm.most_common(10)),
        "review_status": dict(Counter(str(p["review"]) for p in probs)),
        "atoms_with_problem_link": len([a for a in leaf if atom_problems.get(a)]),
        "atoms_with_mid_link": len([a for a in leaf if atom_mids.get(a)]),
        "atoms_with_skill": len([a for a in leaf if leaf[a].get("behavior_skills")]),
        "mids_resolved_to_atom": sum(1 for v in mid_atom.values() if v),
        "school_2022_total": school_total,
    }
    if not probs_2022:
        run.result["warnings"].append("2022 코드 문항 0건")
    return {
        "global": global_,
        "by_subject": by_subject,
        "by_domain": by_domain,
        "by_subdomain": by_subdomain,
        "_unit_metrics": unit_metrics,  # 후보 범위 산정용(직렬화 제외)
        "_per_code": per_code,
        "_by_code": by_code,
        "_leaf": leaf,
        "_atom_problems": atom_problems,
        "_atom_mids": atom_mids,
    }


# ──────────────────────────────────────────────────────────────────────────
# 후보 범위 — 문서 §3과 동일 정의(성취기준 코드 집합)
# ──────────────────────────────────────────────────────────────────────────
def candidate_scopes(by_code: dict[str, Any]) -> dict[str, dict[str, Any]]:
    def codes_where(**kw: str) -> list[str]:
        return sorted(c for c, r in by_code.items() if all(r.get(k) == v for k, v in kw.items()))

    return {
        "C1_12미적Ⅰ_미분": {
            "label": "미적분Ⅰ '미분' 대단원 (고2·2028 수능 공통)",
            "codes": codes_where(subject="12미적Ⅰ", domain="미분"),
        },
        "C2_12미적Ⅰ_전체": {
            "label": "미적분Ⅰ 전 과정 (극한·미분·적분)",
            "codes": codes_where(subject="12미적Ⅰ"),
        },
        "C3_10공수1_방정식과부등식": {
            "label": "공통수학1 '방정식과 부등식' 대단원 (고1)",
            "codes": codes_where(subject="10공수1", domain="방정식과 부등식"),
        },
        "C7_10공수1_전체": {
            "label": "공통수학1 전 과정 (고1 공통과목 — 다항식·방정식과 부등식·경우의 수·행렬)",
            "codes": codes_where(subject="10공수1"),
        },
        "C4_12확통_전체": {
            "label": "확률과 통계 전 과정 (고2·2028 수능 공통)",
            "codes": codes_where(subject="12확통"),
        },
        "C8_12확통_확률": {
            "label": "확률과 통계 '확률' 대단원 (고2·2028 수능 공통)",
            "codes": codes_where(subject="12확통", domain="확률"),
        },
        "C5_12대수_전체": {
            "label": "대수 전 과정 (고2·2028 수능 공통)",
            "codes": codes_where(subject="12대수"),
        },
        "C6_9수_이차방정식": {
            "label": "중3 이차방정식 (EOS 깊이 앵커 A4)",
            "codes": ["[9수02-20]"],
        },
    }


# ──────────────────────────────────────────────────────────────────────────
# 출력 — 문서 표 1·2·후보 표를 이 함수들이 그대로 낸다(문서 수치의 재현 경로)
# ──────────────────────────────────────────────────────────────────────────
SUBJECT_ORDER = [
    "9수",
    "10공수1",
    "10공수2",
    "10기수1",
    "10기수2",
    "12대수",
    "12미적Ⅰ",
    "12확통",
    "12미적Ⅱ",
    "12기하",
    "12경수",
    "12수과",
    "12수문",
    "12실통",
    "12인수",
    "12직수",
    "2수",
    "4수",
    "6수",
]


def pct(a: int, b: int) -> str:
    return f"{(100 * a / b):.0f}%" if b else "-"


def row(cells: list[Any]) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def subject_cells(name: str, grade: str, m: dict[str, Any]) -> list[Any]:
    n = m["concepts_atom"]
    k = m["concepts_437"]
    links = f"{m['links_cs']}·{m['links_cp']}·{m['links_cm']}·{m['links_pm']}"
    linked = f"{m['atoms_with_skill']}·{m['atoms_with_problem']}·{m['atoms_with_mid']}"
    return [
        name,
        grade,
        m["standards"],
        f"{n}/{k}",
        m["skills_distinct"],
        f"{m['problems']}/{m['problems_runtime']}",
        m["problem_skeletons_distinct"],
        m["misconceptions_mid"],
        links,
        linked,
        m["orphan_atoms"],
        m["problems_with_mid"],
        m["misconceptions_mid"] - m["mids_without_problem"],
        f"{m['atoms_triangle']} ({pct(m['atoms_triangle'], n)})",
        f"{m['c437_triangle']}/{k} ({pct(m['c437_triangle'], k)})",
    ]


SUBJECT_HEAD = [
    "과목",
    "학년",
    "성취기준",
    "Concept 원자/437",
    "Skill종",
    "Problem 파일/런타임",
    "문면고유",
    "M-id",
    "연결 C↔S·C↔P·C↔M·P↔M",
    "연결 원자 S·P·M",
    "고아 개념",
    "문항 M연결",
    "M 문항연결",
    "원자 삼각(밀도)",
    "437 삼각(밀도)",
]

DOMAIN_HEAD = [
    "과목",
    "대단원(영역)",
    "성취기준",
    "Concept 원자/437",
    "Skill종",
    "Problem 파일/런타임",
    "문면고유",
    "M-id",
    "연결 원자 S·P·M",
    "고아 개념",
    "고아 문항",
    "문항 M연결",
    "M 문항연결",
    "원자 삼각",
    "437 삼각",
    "6슬롯 결손(437·문면)",
]

PER_CODE_HEAD = [
    "코드",
    "소단원",
    "원자",
    "primary",
    "문항(파일태그)",
    "문항(런타임)",
    "문항 M연결",
    "문면 고유",
    "M-id",
    "M 문항연결",
]


def print_tables(result: dict[str, Any]) -> None:
    print("### 표 1 — 과목별\n")
    print(row(SUBJECT_HEAD))
    print(row(["---"] * len(SUBJECT_HEAD)))
    for s in SUBJECT_ORDER:
        m = result["by_subject"][s]
        grade = ",".join(sorted({k.split("·")[1] for k in m["atom_grade"]})) or m["grade_band"]
        print(row(subject_cells(s, grade, m)))
    t = result["global"]["school_2022_total"]
    print(row(subject_cells("**학교급 2022 합계**", "초1~고3", t)))

    print("\n### 표 2 — 대단원(영역)별\n")
    print(row(DOMAIN_HEAD))
    print(row(["---"] * len(DOMAIN_HEAD)))
    doms = sorted(
        result["by_domain"], key=lambda m: (SUBJECT_ORDER.index(m["subject"]), m["domain"])
    )
    for m in doms:
        n = m["concepts_atom"]
        k = m["concepts_437"]
        linked = f"{m['atoms_with_skill']}·{m['atoms_with_problem']}·{m['atoms_with_mid']}"
        print(
            row(
                [
                    m["subject"],
                    m["domain"],
                    m["standards"],
                    f"{n}/{k}",
                    m["skills_distinct"],
                    f"{m['problems']}/{m['problems_runtime']}",
                    m["problem_skeletons_distinct"],
                    m["misconceptions_mid"],
                    linked,
                    m["orphan_atoms"],
                    m["orphan_problems"],
                    m["problems_with_mid"],
                    m["misconceptions_mid"] - m["mids_without_problem"],
                    f"{m['atoms_triangle']}/{n}",
                    f"{m['c437_triangle']}/{k}",
                    m["slot6_deficit_437_by_skeleton"],
                ]
            )
        )

    print("\n### 후보 범위 — 성취기준 코드별\n")
    for key, m in result["candidates"].items():
        print(f"\n#### {key} — {m['label']}\n")
        print(row(PER_CODE_HEAD))
        print(row(["---"] * len(PER_CODE_HEAD)))
        for r in m["per_code"]:
            print(
                row(
                    [
                        r["code"],
                        r["sub_domain"],
                        r["atoms"],
                        r["primary_atoms"],
                        r["problems"],
                        r["problems_runtime"],
                        r["problems_with_mid"],
                        r["problems_skeletons"],
                        r["mids"],
                        r["mids_with_problem"],
                    ]
                )
            )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args(argv)

    run = Run(args.out)
    run.flush()
    std = run.stage("load_standards", load_standards)
    atoms = run.stage("load_atoms", load_atoms)
    br = run.stage("load_bridge", load_bridge)
    mis = run.stage("load_misconceptions", load_misconceptions)
    sk = run.stage("load_skills", load_skills)
    probs = run.stage("load_problems", load_problems)
    if run.result["errors"]:
        print(json.dumps(run.result["errors"], ensure_ascii=False, indent=1), file=sys.stderr)
        return 1

    res = run.stage("compute", lambda: compute(std, atoms, br, mis, sk, probs, run))
    if res is None:
        print(json.dumps(run.result["errors"], ensure_ascii=False, indent=1), file=sys.stderr)
        return 1
    run.result["global"] = res["global"]
    run.result["by_subject"] = res["by_subject"]
    run.result["by_domain"] = res["by_domain"]
    run.result["by_subdomain"] = res["by_subdomain"]
    run.flush()

    def cands() -> dict[str, Any]:
        out = {}
        um = res["_unit_metrics"]
        leaf = res["_leaf"]
        ap_ = res["_atom_problems"]
        am_ = res["_atom_mids"]
        for key, spec in candidate_scopes(res["_by_code"]).items():
            if not spec["codes"]:
                raise ValueError(f"후보 {key} 코드 0건 — 정의 오류")
            m = um(set(spec["codes"]))
            atoms_detail = [
                {
                    "code": a,
                    "name": leaf[a].get("name"),
                    "std": leaf[a].get("standard_codes"),
                    "skills": len(leaf[a].get("behavior_skills") or []),
                    "problems": len(ap_.get(a, set())),
                    "mids": len(am_.get(a, set())),
                }
                for a in m.pop("atoms_list")
            ]
            m["label"] = spec["label"]
            m["codes"] = spec["codes"]
            m["atoms_detail"] = atoms_detail
            m["per_code"] = res["_per_code"](spec["codes"])
            out[key] = m
        return out

    cand = run.stage("candidates", cands)
    run.result["candidates"] = cand
    run.flush()
    if run.result["errors"]:
        print(json.dumps(run.result["errors"], ensure_ascii=False, indent=1), file=sys.stderr)
        return 1

    if not args.json_only:
        print(f"# P3-01 실측 — HEAD {run.result['head'][:8]} · {run.result['measured_at']}\n")
        print_tables(run.result)
    shown = args.out.relative_to(REPO) if args.out.is_relative_to(REPO) else args.out
    print(f"\n[p3_01] 결과 JSON: {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
