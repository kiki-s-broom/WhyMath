#!/usr/bin/env python3
"""EOS-52 앵커 자산 실사 — 재현 스크립트 (2026-08-30 EOS 전환 선언 §3.2-② 지시).

12월 내부 검증 앵커 후보 8단원(A1~A8)의 저장소 자산 커버리지를 5축으로 실측한다:
  ① 원자 노드 수  ② 성취기준 코드(2022 개정) 수  ③ 오개념 항목 수
  ④ 기계판정형 detection_rule 수(리터럴 필드 + 실재 최근접 대응물 L4 탐지채널)
  ⑤ 기존 문항 코퍼스 문항 수

정본 원칙: 읽는 것은 저장소 파일뿐(YAML/JSON=소스, DB=산출물 단방향) — prod DB는 읽지 않는다.
DB 적재분 대조는 산출 문서(docs/reviews/eos_anchor_asset_audit_2026-09.md) 부록의 psql 명령으로.

실패 경로 설계(CLAUDE.md 2026-08-22 "측정·수집 도구를 성공 경로만 보고 설계 금지" 준수):
  ① 단계별 즉시 flush — 각 단계 종료마다 결과 JSON을 원자적으로(tmp→replace) 저장한다.
     중간 실패 시에도 그때까지의 부분 결과가 파일로 남는다.
  ② 실패 원인 기록 — 단계 예외는 예외 타입명+메시지를 결과 JSON `errors`에 남긴다(침묵 실패 금지).
  ③ 시간 필터 — 결과 JSON에 `measured_at_utc`를 기록해 이전 실행 산출물과의 혼동을 막는다.
  ④ 외부 프로세스 호출 없음 — subprocess 미사용(파일 I/O만)이므로 타임아웃 규칙 해당 없음.
  종료 코드: 전 단계 성공=0, 한 단계라도 실패=1 (측정 실패가 성공 화면으로 위장되면 안 된다).

실행(레포 루트 기준):
  python3 scripts/analysis/eos_anchor_asset_audit.py
  → 기본 산출: data/audit/eos_anchor_asset_audit_2026-09.json + stdout 마크다운 표

계층 경계: 본 스크립트는 분석 전용(scripts/analysis 격리)이며 src/backend 코드를 import하지
않는다 — L4 카탈로그(catalog.py·distractor.py)는 AST 파싱으로만 읽는다(무거운 패키지 의존
체인 회피 + 역방향 의존 신설 금지).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# 앵커 정의 — **1급 등록(코퍼스)에서 읽는다** (EOS-56)
#
# 이전에는 이 자리에 `ANCHOR_DEFS` 파이썬 상수 리터럴이 있었다. 그 형태는 ① 런타임·생산
# 배치가 읽을 수 없고 ② 성취기준 코퍼스가 코드를 잃어도 아무도 소리내지 않는 정의였다.
# 이제 정본은 `data/corpus/eos_anchor_set_v1/anchors.yaml`(G0 동결본)이고 이 스크립트는
# 그것을 읽기만 한다 — 코드셋은 무손실 이관됐고 추가·삭제·수정은 없다.
#
# 매핑 축 = **성취기준 코드 단일 축**. 근거(레지스트리 헤더와 동일):
#  - 원자(atom_graph)·오개념(misconceptions)·문항(problem_bank)이 모두 성취기준 코드 필드를
#    가져 세 자산을 같은 축으로 재현 가능하게 귀속시킬 수 있다.
#  - 대안이던 subunit(소단원명) 축은 구조 헤더 노드(level=소단원, standard_codes=[])와
#    교과서 단원 granularity 차이로 앵커 경계가 흐려진다. 코드 축에서는 리프만 걸린다.
#  - 대학 앵커도 자체작성 성취기준([CALC1-*]·[LINA1-*])이 동일 메커니즘으로 존재한다.
# 포함/제외 경계는 각 앵커의 excluded에 사유와 함께 등재돼 있다(재현 가능성).
#
# 계층 경계: 여전히 src/backend를 import하지 않는다(모듈 docstring 참조) — 같은 *파일*을
# 읽을 뿐이며, 백엔드 쪽 소비자는 `whymath_backend.l1.standards.anchor_registry`를 쓴다.
# 파일이 하나이므로 리더가 둘이어도 진실 원천은 하나다.
#
# 8건을 그대로 감사하는 이유: G0 확정 12월 대상은 6건(A1~A6)이나, EOS-52 실사 문서는 8앵커
# 기준으로 발행됐다. 전건을 읽어 그 문서의 재현성을 유지하고, 이월 여부는 산출 JSON의
# `scope` 필드로 기계가 구분한다(집계에서 지우지 않는다).
# ---------------------------------------------------------------------------
ANCHOR_REGISTRY_PATH = "data/corpus/eos_anchor_set_v1/anchors.yaml"


class AnchorRegistryLoadError(RuntimeError):
    """앵커 레지스트리 적재·구조 실패 — **일반 예외**다(SystemExit 아님).

    왜 SystemExit이 아닌가(#950 codex P2 상환): 초판은 이 적재를 *모듈 import 시점*에 하고
    실패를 `SystemExit`으로 던졌다. 그러면 `main()`에 진입하기 전에 죽어 `--out`도 파싱되지
    않고 첫 `_flush()`도 실행되지 않는다 — **측정 실패 원인을 담은 JSON 증거가 한 줄도 남지
    않는다**. 이 스크립트가 모듈 docstring에 스스로 선언한 실패 경로 설계("①단계별 즉시
    flush — 실패해도 증거가 남는다")가 정확히 이 실패에서만 깨져 있었다.

    이제 적재는 **하나의 측정 단계**이고, 단계 실패는 러너가 예외 타입명과 함께 `errors`에
    기록한 뒤 flush한다 — 다른 모든 단계와 같은 규율을 받는다.
    """


def load_anchor_defs(registry_path: Path | None = None) -> tuple[dict[str, Any], ...]:
    """1급 등록에서 앵커 정의를 읽는다 — 실패는 `AnchorRegistryLoadError`.

    감사 도구가 앵커 0건으로 "성공"하면 그 결과는 "자산 없음"으로 읽힌다. 레지스트리를 못
    읽는 것은 측정 실패이지 측정 결과가 아니므로 조용한 빈 튜플을 돌려주지 않는다.

    `registry_path`(OPS-70): 기본은 정본(`REPO_ROOT / ANCHOR_REGISTRY_PATH`)이지만, 실패
    경로를 실측하는 테스트가 정본을 직접 훼손하지 않도록 임시 사본을 가리키는 주입구다 —
    `-n auto` 병렬 실행에서 다른 워커가 정본을 읽는 창과 경합하는 사고(OPS-70)를 없앤다.
    """
    path = registry_path if registry_path is not None else REPO_ROOT / ANCHOR_REGISTRY_PATH
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise AnchorRegistryLoadError(
            f"앵커 레지스트리 적재 실패 {path}: {type(exc).__name__}: {exc}"
        ) from exc
    anchors = doc.get("anchors") if isinstance(doc, dict) else None
    if not isinstance(anchors, list) or not anchors:
        raise AnchorRegistryLoadError(f"앵커 레지스트리 {path}: anchors 배열이 비어 있다")
    try:
        return tuple(
            {
                "id": a["id"],
                "title": a["title"],
                "codes": list(a["codes"]),
                "excluded": dict(a.get("excluded") or {}),
                "note": a["note"],
                "scope": a["scope"],
            }
            for a in anchors
        )
    except (KeyError, TypeError) as exc:
        # 필수 필드 결손을 무증상 부분 집계로 흘려보내지 않는다(스키마 정본 검증은
        # whymath_backend.l1.standards.anchor_registry + CI 게이트가 담당).
        raise AnchorRegistryLoadError(
            f"앵커 레지스트리 구조 오류 {path}: {type(exc).__name__}: {exc}"
        ) from exc


# 문항 은행 디렉터리(전수) — data/corpus/problem_bank_*/problems.jsonl
PROBLEM_BANK_GLOB = "problem_bank_*"

# 리터럴 스캔 분류: 최상위 경로 → 코드/문서/데이터
CODE_TOP_DIRS = {"src", "scripts", "tests", "schemas", "infra", "conftest.py"}
DOC_TOP_DIRS = {"docs", "backlog"}
SKIP_DIRS = {
    ".git",
    "work",  # 병렬 세션 worktree 자리 — 본 체크아웃 콘텐츠가 아님
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".dart_tool",
    "build",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
}
SCAN_EXTS = {
    ".py",
    ".md",
    ".yaml",
    ".yml",
    ".json",
    ".jsonl",
    ".dart",
    ".ts",
    ".js",
    ".sql",
    ".toml",
    ".txt",
    ".sh",
    ".ps1",
}
SCAN_MAX_BYTES = 30 * 1024 * 1024  # 30MB 초과 파일은 스캔 생략(warnings에 기록)


def _now_utc() -> str:
    """측정 시각(UTC ISO) — 결과 JSON의 시간 필터 축."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _flush(result: dict[str, Any], out_path: Path) -> bool:
    """결과를 원자적으로 저장(tmp→replace) — 단계별 즉시 flush의 실체.

    실패해도 증거가 남게, 매 단계 호출된다. 쓰기 실패는 stderr 예외 타입명 + result
    warnings에 기록하고 False를 반환한다 — 측정 루프는 계속하되(마지막 flush가 성공할 수
    있다), **최종 flush 실패·증거 파일 부재는 main()이 exit 1로 승격**한다(성공 위장 금지
    — PR #907 리뷰 수용: 영속 실패한 측정을 자동화가 성공으로 받아들이면 안 된다).
    """
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, out_path)
        return True
    except OSError as exc:
        print(f"[flush 실패] {type(exc).__name__}: {exc}", file=sys.stderr)
        result["warnings"].append(f"flush 실패: {type(exc).__name__}: {str(exc)[:200]}")
        return False


def _load_json(rel: str) -> Any:
    """저장소 상대 경로의 JSON 로드 — 실패는 호출부(단계 러너)가 타입명으로 기록."""
    return json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 측정 단계들 — 각 단계는 ctx(공유 데이터)와 result(산출 JSON)를 갱신한다
# ---------------------------------------------------------------------------


def step_anchor_registry(ctx: dict[str, Any], result: dict[str, Any]) -> None:
    """앵커 1급 등록 적재 — **첫 단계**. 실패는 러너가 errors에 기록하고 flush한다.

    이 단계가 실패하면 뒤 단계는 조인 축 자체가 없으므로 main()이 측정을 중단한다
    (같은 원인으로 8개 단계가 각자 죽는 소음 대신 중단 사유 1건).
    """
    defs = load_anchor_defs(ctx.get("registry_path"))
    ctx["anchor_defs"] = defs
    result["anchor_defs"] = [
        {
            "id": a["id"],
            "title": a["title"],
            "codes": a["codes"],
            "excluded": a["excluded"],
            "note": a["note"],
            "scope": a["scope"],
        }
        for a in defs
    ]
    result["anchors"] = {a["id"]: {} for a in defs}


def step_standards(ctx: dict[str, Any], result: dict[str, Any]) -> None:
    """성취기준 로드 — 학교급(2022/2015 혼재 분리) + 대학(자체작성). 앵커 코드 실재 검증."""
    school = _load_json("data/corpus/standards_v1/standards.json")["standards"]
    univ = _load_json("data/corpus/standards_university_v1/standards.json")["standards"]
    s2022 = [x for x in school if x.get("curriculum_revision") == "2022 개정"]
    s2015 = [x for x in school if x.get("curriculum_revision") == "2015 개정"]
    ctx["std2022_by_code"] = {}
    for x in s2022:
        ctx["std2022_by_code"].setdefault(x["code"], []).append(x)
    ctx["stdu_by_code"] = {}
    for x in univ:
        ctx["stdu_by_code"].setdefault(x["code"], []).append(x)
    result["global"]["standards"] = {
        "school_rows_total": len(school),
        "school_rows_2022": len(s2022),
        "school_rows_2015": len(s2015),
        "school_unique_codes": len({x["code"] for x in school}),
        "university_rows": len(univ),
        "note": "학교급 895행은 2022·2015 개정 혼재 — 앵커 집계는 2022 개정 행만 사용",
    }
    # 앵커 코드 실재 검증(동결 코드셋 vs 데이터 드리프트 감지 — 변별력 있는 검사)
    for a in ctx["anchor_defs"]:
        rows: list[dict[str, Any]] = []
        for code in a["codes"]:
            hits = ctx["std2022_by_code"].get(code, []) + ctx["stdu_by_code"].get(code, [])
            if not hits:
                result["warnings"].append(
                    f"{a['id']}: 동결 코드 {code}가 성취기준 데이터에 없음(드리프트 의심)"
                )
            for h in hits:
                rows.append(
                    {
                        "code": h["code"],
                        "sub_domain": h.get("sub_domain"),
                        "statement_head": (h.get("statement") or "")[:40],
                    }
                )
        result["anchors"][a["id"]]["standards"] = {"count": len(rows), "rows": rows}


def step_atoms(ctx: dict[str, Any], result: dict[str, Any]) -> None:
    """원자 백본 로드 — 전역(노드·엣지·레벨 분포) + 앵커별 원자 수(성취기준 코드 축)."""
    g = _load_json("data/corpus/atom_graph_v1/graph.json")
    atoms = g["concepts"]
    levels: dict[str, int] = {}
    schools: dict[str, int] = {}
    for x in atoms:
        lv = x.get("level") or "(없음)"
        levels[lv] = levels.get(lv, 0) + 1
        sc = x.get("school_level") or "(없음)"
        schools[sc] = schools.get(sc, 0) + 1
    result["global"]["atom_graph"] = {
        "concept_nodes_total": len(atoms),
        "edges": len(g.get("edges") or []),
        "narrative_edges_raw": len(g.get("narrative_edges_raw") or []),
        "level_split": dict(sorted(levels.items())),
        "school_level_split": dict(sorted(schools.items())),
        "note": "노드 총계는 구조 노드(단원·소단원) 포함 — 앵커 집계는 코드 보유 리프만",
    }
    for a in ctx["anchor_defs"]:
        codes = set(a["codes"])
        hit = [x for x in atoms if codes & set(x.get("standard_codes") or [])]
        lv_split: dict[str, int] = {}
        for x in hit:
            lv = x.get("level") or "(없음)"
            lv_split[lv] = lv_split.get(lv, 0) + 1
        result["anchors"][a["id"]]["atoms"] = {
            "count": len(hit),
            "level_split": lv_split,
            "atom_codes": sorted(x.get("code") or "?" for x in hit)[:30],
        }


def step_misconceptions(ctx: dict[str, Any], result: dict[str, Any]) -> None:
    """오개념 DB(M-id) — 전역 건수 + 앵커별 귀속 + detection_rule 리터럴 필드 실재 검사."""
    doc = _load_json("data/corpus/misconceptions_v1/misconceptions.json")
    mis = doc["misconceptions"]
    declared = doc.get("count")
    if declared is not None and declared != len(mis):
        result["warnings"].append(
            f"misconceptions.json 자체 선언 count={declared} ≠ 실제 {len(mis)} (정합성 확인 필요)"
        )
    # detection_rule 리터럴 필드: 행 단위 실재 검사(가정 금지 — 키 존재를 직접 센다)
    field_rows = sum(1 for x in mis if "detection_rule" in x)
    levels: dict[str, int] = {}
    for x in mis:
        lv = x.get("school_level") or "(없음)"
        levels[lv] = levels.get(lv, 0) + 1
    result["global"]["misconceptions"] = {
        "rows_total": len(mis),
        "rows_with_detection_rule_field": field_rows,
        "school_level_split": dict(sorted(levels.items())),
        "collected_at": doc.get("collected_at"),
    }
    ctx["mis_by_id"] = {x["mis_id"]: x for x in mis}
    for a in ctx["anchor_defs"]:
        codes = set(a["codes"])
        hit = [x for x in mis if (x.get("standard_code") or "") in codes]
        result["anchors"][a["id"]]["misconceptions"] = {
            "count": len(hit),
            "with_detection_rule_field": sum(1 for x in hit if "detection_rule" in x),
            "mis_ids": sorted(x["mis_id"] for x in hit),
        }


def step_problems(ctx: dict[str, Any], result: dict[str, Any]) -> None:
    """문항 코퍼스 — 은행별 전역 건수 + 앵커별 귀속(achievement_standard_codes 교집합)."""
    corpus_dir = REPO_ROOT / "data" / "corpus"
    banks = sorted(p.name for p in corpus_dir.glob(PROBLEM_BANK_GLOB) if p.is_dir())
    if not banks:
        # 은행 0개는 '문항 0건'이 아니라 측정 실패다(0건 위장 금지 — CLAUDE.md 이중 회계 원칙)
        raise FileNotFoundError(f"문항 은행 디렉터리 없음: {corpus_dir}/{PROBLEM_BANK_GLOB}")
    per_bank: dict[str, int] = {}
    problems: list[tuple[str, set[str]]] = []  # (은행, 성취기준 코드 집합)
    for bank in banks:
        path = corpus_dir / bank / "problems.jsonl"
        if not path.exists():
            # 은행 디렉터리는 있는데 데이터 파일이 없다 = 부분 체크아웃·삭제 의심.
            # 이 총계는 G0 결정 근거이므로 조용한 누락은 0건 위장이다 — 측정 실패로 승격
            # (PR #907 리뷰 수용)
            raise FileNotFoundError(
                f"{bank}: problems.jsonl 없음(은행 디렉터리만 잔존) — 부분 입력으로 총계 산출 금지"
            )
        n = 0
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                p = json.loads(line)
                n += 1
                problems.append((bank, set(p.get("achievement_standard_codes") or [])))
        per_bank[bank] = n
    result["global"]["problem_corpus"] = {
        "rows_total": sum(per_bank.values()),
        "per_bank": per_bank,
    }
    for a in ctx["anchor_defs"]:
        codes = set(a["codes"])
        bank_split: dict[str, int] = {}
        for bank, pcodes in problems:
            if codes & pcodes:
                bank_split[bank] = bank_split.get(bank, 0) + 1
        result["anchors"][a["id"]]["problems"] = {
            "count": sum(bank_split.values()),
            "per_bank": dict(sorted(bank_split.items())),
        }


def _ast_calls(py_rel: str, func_name: str) -> list[dict[str, ast.expr]]:
    """py 파일에서 `func_name(...)` 호출 전부의 키워드 인자 맵을 AST로 수집(임포트 없이)."""
    tree = ast.parse((REPO_ROOT / py_rel).read_text(encoding="utf-8"))
    out: list[dict[str, ast.expr]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == func_name
        ):
            out.append({k.arg: k.value for k in node.keywords if k.arg})
    return out


def step_l4_catalog(ctx: dict[str, Any], result: dict[str, Any]) -> None:
    """L4 오개념 카탈로그(kebab) — 탐지 채널 집계 + crosswalk 경유 앵커 귀속.

    '기계판정형 detection_rule'의 실재 최근접 대응물 판정 축:
      substring `signals`(규칙) < `regex_signals`(정규식) < `canonical_wrong_form`(SymPy 술어).
    """
    calls = _ast_calls("src/backend/whymath_backend/l4/misconception/catalog.py", "Misconception")
    entries = []
    for kw in calls:
        cwf = kw.get("canonical_wrong_form")
        rx = kw.get("regex_signals")
        entries.append(
            {
                "id": ast.literal_eval(kw["id"]),
                "has_sympy_wrong_form": cwf is not None
                and not (isinstance(cwf, ast.Constant) and cwf.value is None),
                "has_regex": rx is not None and bool(getattr(rx, "elts", [])),
            }
        )
    xl = _load_json("data/corpus/misconception_crosslinks_v1/crosslinks.json")["crosslinks"]
    kebab2mid = {r["kebab_id"]: r["mis_id"] for r in xl}
    result["global"]["l4_misconception_catalog"] = {
        "entries": len(entries),
        "with_sympy_wrong_form": sum(1 for e in entries if e["has_sympy_wrong_form"]),
        "with_regex_signals": sum(1 for e in entries if e["has_regex"]),
        "crosslink_rows": len(xl),
        "crosslinked_entries": sum(1 for e in entries if e["id"] in kebab2mid),
        "machine_channel_entries": [
            {
                "id": e["id"],
                "sympy": e["has_sympy_wrong_form"],
                "regex": e["has_regex"],
                "mis_id": kebab2mid.get(e["id"]),
                "standard_code": (ctx.get("mis_by_id", {}).get(kebab2mid.get(e["id"], ""), {})).get(
                    "standard_code"
                ),
            }
            for e in entries
            if e["has_sympy_wrong_form"] or e["has_regex"]
        ],
    }
    mis_by_id = ctx.get("mis_by_id", {})
    for a in ctx["anchor_defs"]:
        codes = set(a["codes"])
        hit = []
        for e in entries:
            mid = kebab2mid.get(e["id"])
            if mid and (mis_by_id.get(mid, {}).get("standard_code") or "") in codes:
                hit.append(e)
        result["anchors"][a["id"]]["l4_detection"] = {
            "crosslinked_entries": len(hit),
            "machine_entries_sympy_or_regex": sum(
                1 for e in hit if e["has_sympy_wrong_form"] or e["has_regex"]
            ),
            "entry_ids": sorted(e["id"] for e in hit),
        }


def step_distractor_op_codes(ctx: dict[str, Any], result: dict[str, Any]) -> None:
    """L4 distractor op-code 카탈로그 — 'OP코드'의 실재 대응물. 앵커 귀속은 오개념 경유."""
    calls = _ast_calls(
        "src/backend/whymath_backend/l4/misconception/distractor.py", "DistractorOpCode"
    )
    ops = [
        {
            "id": ast.literal_eval(kw["id"]),
            "misconception_id": ast.literal_eval(kw["misconception_id"]),
        }
        for kw in calls
    ]
    result["global"]["distractor_op_codes"] = {
        "entries": len(ops),
        "ids": sorted(o["id"] for o in ops),
        "note": "kebab-case 추상 오류연산 op-code — 설계서 표기 OP_01~08과 명명 체계가 다름",
    }
    xl = _load_json("data/corpus/misconception_crosslinks_v1/crosslinks.json")["crosslinks"]
    kebab2mid = {r["kebab_id"]: r["mis_id"] for r in xl}
    mis_by_id = ctx.get("mis_by_id", {})
    for a in ctx["anchor_defs"]:
        codes = set(a["codes"])
        hit = []
        for o in ops:
            mid = kebab2mid.get(o["misconception_id"])
            if mid and (mis_by_id.get(mid, {}).get("standard_code") or "") in codes:
                hit.append(o["id"])
        result["anchors"][a["id"]]["distractor_op_codes"] = {
            "count": len(hit),
            "ids": sorted(hit),
        }


def step_related_stores(ctx: dict[str, Any], result: dict[str, Any]) -> None:
    """전역 정정표 보조 수치 — 구 개념그래프·crosswalk(개념↔원자) 행수."""
    cg_path = REPO_ROOT / "data/corpus/concept_graph_v1/concepts.jsonl"
    n_cg = sum(1 for line in cg_path.read_text(encoding="utf-8").splitlines() if line.strip())
    xw_path = REPO_ROOT / "data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl"
    n_xw = sum(1 for line in xw_path.read_text(encoding="utf-8").splitlines() if line.strip())
    result["global"]["concept_graph_v1_concepts"] = n_cg
    result["global"]["concept_atom_crosswalk_rows"] = n_xw


def step_literal_scan(ctx: dict[str, Any], result: dict[str, Any]) -> None:
    """리터럴 스캔 — OP_01~08·detection_rule이 코드로 실재하는지 저장소 전수 판정.

    스캔 제외: 자기 자신(이 스크립트)·자기 산출 JSON — 패턴 문자열을 담고 있어 오염원이 된다.
    """
    pat_op = re.compile(r"\bOP_0[1-8]\b")
    pat_dr = re.compile(r"detection_rule")
    self_paths = {
        Path(__file__).resolve(),
        Path(result["out_path"]).resolve(),
        # 실사 문서 자신도 제외 — 판정 결과를 서술하며 패턴 문자열을 담으므로 재실행 시 오염원
        (REPO_ROOT / "docs/reviews/eos_anchor_asset_audit_2026-09.md").resolve(),
        # 실사 결정 로그(MEMORY.md 2026-08-30 항목)도 동일 사유로 제외 — MEMORY는 코드가
        # 아니라 결정 로그이므로 '코드 실재' 판정에 기여하지 않으며, 포함 시 재현이
        # 비멱등이 된다(PR #907 리뷰 수용)
        (REPO_ROOT / "MEMORY.md").resolve(),
    }
    hits: dict[str, list[dict[str, Any]]] = {"OP_01~08": [], "detection_rule": []}
    skipped_large: list[str] = []
    n_scanned = 0
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix.lower() not in SCAN_EXTS or p.resolve() in self_paths:
                continue
            try:
                if p.stat().st_size > SCAN_MAX_BYTES:
                    skipped_large.append(str(p.relative_to(REPO_ROOT)))
                    continue
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError as exc:
                result["warnings"].append(
                    f"스캔 실패 {p.relative_to(REPO_ROOT)}: {type(exc).__name__}"
                )
                continue
            n_scanned += 1
            rel = str(p.relative_to(REPO_ROOT))
            top = rel.split("/", 1)[0]
            kind = "code" if top in CODE_TOP_DIRS else ("doc" if top in DOC_TOP_DIRS else "other")
            n_op = len(pat_op.findall(text))
            n_dr = len(pat_dr.findall(text))
            if n_op:
                hits["OP_01~08"].append({"path": rel, "kind": kind, "n": n_op})
            if n_dr:
                hits["detection_rule"].append({"path": rel, "kind": kind, "n": n_dr})
    if skipped_large:
        result["warnings"].append(
            f"크기 초과 스캔 생략 {len(skipped_large)}건: {skipped_large[:5]}"
        )
    if n_scanned == 0:
        # 스캔 0파일은 '리터럴 없음'이 아니라 측정 실패다(0건 위장 금지)
        raise FileNotFoundError(f"스캔 대상 파일 0건: {REPO_ROOT} 아래에 대상 확장자 파일이 없음")
    scan: dict[str, Any] = {"files_scanned": n_scanned}
    scan["excluded_self"] = sorted(str(p) for p in self_paths)
    for key, rows in hits.items():
        rows.sort(key=lambda r: r["path"])
        scan[key] = {
            "files_total": len(rows),
            "code_dir_files": sum(1 for r in rows if r["kind"] == "code"),
            "doc_dir_files": sum(1 for r in rows if r["kind"] == "doc"),
            "other_files": sum(1 for r in rows if r["kind"] == "other"),
            "files": rows[:50],
        }
    result["literal_scan"] = scan


def step_summary_table(ctx: dict[str, Any], result: dict[str, Any]) -> None:
    """앵커×5축 마크다운 표 생성(문서 붙여넣기용) — JSON에도 동봉."""
    lines = [
        "| 앵커 | 단원 | 성취기준(2022) | 원자 노드 | 오개념 | detection_rule 필드 | "
        "L4 탐지항목(기계) | op-code | 문항 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for a in ctx["anchor_defs"]:
        r = result["anchors"][a["id"]]
        std = r.get("standards", {}).get("count", "측정실패")
        atom = r.get("atoms", {}).get("count", "측정실패")
        mis = r.get("misconceptions", {}).get("count", "측정실패")
        drf = r.get("misconceptions", {}).get("with_detection_rule_field", "측정실패")
        l4 = r.get("l4_detection", {})
        l4n = l4.get("crosslinked_entries", "?")
        l4m = l4.get("machine_entries_sympy_or_regex", "?")
        l4s = f"{l4n}({l4m})"
        opc = r.get("distractor_op_codes", {}).get("count", "측정실패")
        prob = r.get("problems", {}).get("count", "측정실패")
        cells = [a["id"], a["title"], std, atom, mis, drf, l4s, opc, prob]
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    result["table_markdown"] = "\n".join(lines)


STEPS: tuple[tuple[str, Any], ...] = (
    # 앵커 등록 적재가 **첫 단계**다 — import 시점이 아니라 여기서 실패해야 증거가 남는다.
    ("anchor_registry", step_anchor_registry),
    ("standards", step_standards),
    ("atoms", step_atoms),
    ("misconceptions", step_misconceptions),
    ("problems", step_problems),
    ("l4_catalog", step_l4_catalog),
    ("distractor_op_codes", step_distractor_op_codes),
    ("related_stores", step_related_stores),
    ("literal_scan", step_literal_scan),
    ("summary_table", step_summary_table),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="EOS-52 앵커 자산 실사(저장소 파일 실측)")
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "data/audit/eos_anchor_asset_audit_2026-09.json"),
        help="결과 JSON 경로(기본: data/audit/eos_anchor_asset_audit_2026-09.json)",
    )
    parser.add_argument(
        "--registry",
        default=str(REPO_ROOT / ANCHOR_REGISTRY_PATH),
        help=(
            "앵커 1급 등록 경로(기본: 정본 "
            f"{ANCHOR_REGISTRY_PATH}) — 실패 경로를 실측하는 테스트가 정본을 훼손하지 "
            "않도록 사본을 가리키는 주입구(OPS-70)"
        ),
    )
    args = parser.parse_args()
    out_path = Path(args.out)
    registry_path = Path(args.registry)

    result: dict[str, Any] = {
        "task": "EOS-52-anchor-asset-audit",
        "measured_at_utc": _now_utc(),
        "script": "scripts/analysis/eos_anchor_asset_audit.py",
        "repo_root": str(REPO_ROOT),
        "out_path": str(out_path),
        "mapping_axis": (
            "성취기준 코드(2022 개정·대학 자체작성) 단일 축 — "
            f"1급 등록 {ANCHOR_REGISTRY_PATH} 동결 코드셋"
        ),
        # 아래 두 키는 첫 단계(step_anchor_registry)가 채운다 — 적재 실패 시에도 빈 값으로
        # 증거 JSON이 남아야 하므로 여기서 미리 선언한다(키 부재 ≠ 앵커 0건).
        "anchor_defs": [],
        "steps_completed": [],
        "errors": [],
        "warnings": [],
        "global": {},
        "anchors": {},
    }
    persist_ok = _flush(result, out_path)  # 시작 상태부터 저장 — 첫 단계 전 실패도 증거가 남는다

    ctx: dict[str, Any] = {"registry_path": registry_path}
    for name, fn in STEPS:
        try:
            fn(ctx, result)
            result["steps_completed"].append(name)
        except Exception as exc:  # 단계 실패를 타입명으로 기록하고 계속(부분 결과 보존)
            result["errors"].append(
                {"step": name, "error_type": type(exc).__name__, "error": str(exc)[:500]}
            )
        persist_ok = _flush(result, out_path)
        if "anchor_defs" not in ctx:
            # 조인 축(앵커 정의) 없이 뒤 단계를 돌리면 같은 원인으로 8건이 각자 죽는다 —
            # 중단 사유를 1건으로 남기고 멈춘다. 여기까지의 증거는 위 flush로 이미 디스크에.
            result["errors"].append(
                {
                    "step": "(중단)",
                    "error_type": "AnchorRegistryLoadError",
                    "error": "앵커 정의 미적재 — 조인 축이 없어 이후 단계를 진행하지 않는다",
                }
            )
            persist_ok = _flush(result, out_path)
            break

    print(f"측정 시각(UTC): {result['measured_at_utc']}")
    print(f"결과 JSON: {out_path}")
    print(f"완료 단계: {len(result['steps_completed'])}/{len(STEPS)}")
    if result.get("table_markdown"):
        print()
        print(result["table_markdown"])
    if result["warnings"]:
        print(f"\n경고 {len(result['warnings'])}건:")
        for w in result["warnings"]:
            print(f"  - {w}")
    if result["errors"]:
        print(f"\n측정 실패 단계 {len(result['errors'])}건:", file=sys.stderr)
        for e in result["errors"]:
            print(f"  - {e['step']}: {e['error_type']}: {e['error']}", file=sys.stderr)
        return 1
    # 영속 검증 — 최종 flush가 실패했거나 증거 파일이 없으면 측정 성공을 선언할 수 없다
    # (성공 위장 금지: 증거 없는 EXIT=0은 자동화가 빈 측정을 수용하게 만든다)
    if not persist_ok or not out_path.exists():
        print(
            "\n[측정 실패] 결과 JSON 영속 실패 — 최종 flush 실패 또는 증거 파일 부재",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
