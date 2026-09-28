#!/usr/bin/env python3
"""진단 기준선 러너 — 260927 EOS 통합정밀진단 도구를 이 저장소에 한 번에 돌린다 (CONST-02).

왜 있는가: 이식 완성 결과를 검증하려면 '이식 전' 기준선과 '이식 후' 측정을 같은 도구·같은 인자로
재야 한다. 도구 7종의 인자(특히 계층 설정·개념 그래프 필드 이름)를 사람이 매번 기억하면 두 측정이
서로 다른 눈금이 된다. 그래서 인자를 이 파일 한 곳에 고정한다.

원칙(진단 묶음 공통규칙과 같다)
  · 저장소는 읽기만 한다. 출력은 기본값 work/diag/<시각>/ (gitignore 대상)에만 쓴다.
  · 도구 하나가 실패해도 계속 진행하고, 실패 원인(stderr 끝 20줄)을 남긴다 — 측정 실패 ≠ 0건.
  · 마지막에 출력 폴더의 NUL 바이트 손상 검사를 한다(공통규칙 제5항).

사용법
  python3 scripts/constitution/run_baseline.py                  # 전체
  python3 scripts/constitution/run_baseline.py --only integrity,rules_scan
  python3 scripts/constitution/run_baseline.py --repo <다른 저장소> --out <폴더>

종료 코드: 0 = 전 도구 성공 / 1 = 실패한 도구가 있음 / 2 = 인자 오류(알 수 없는 도구 등)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIAG = HERE / "diag"
ROOT = HERE.parents[1]

#: 학교급 순서 — 개념 그래프의 grade_band_hint 값 (학년 역전 판정용)
GRADE_ORDER = [
    "초등학교 1~2학년군",
    "초등학교 3~4학년군",
    "초등학교 5~6학년군",
    "중학교 1~3학년군",
    "고등학교",
]


def plan(repo: Path, out: Path, since: str) -> dict[str, list[str]]:
    """도구 이름 → 실행 인자(파이썬 스크립트 경로 포함). 인자의 단일 원천이다."""
    raw = str(out / "raw")
    graph = repo / "data" / "corpus" / "concept_graph_v1" / "graph.json"
    return {
        "integrity": ["diag_integrity.py", "--repo", str(repo), "--out", raw],
        "rules_scan": ["diag_rules_scan.py", "--repo", str(repo), "--out", raw],
        "git": ["diag_git.py", "--repo", str(repo), "--out", raw, "--since", since],
        "imports": [
            "diag_imports.py",
            "--repo",
            str(repo),
            "--out",
            raw,
            "--config",
            str(DIAG / "whymath_layers.json"),
        ],
        "imports_7layer": [
            "diag_imports.py",
            "--repo",
            str(repo),
            "--out",
            str(out / "raw_7layer"),
            "--config",
            str(DIAG / "whymath_layers_7layer.json"),
        ],
        "content": ["diag_content.py", "--path", str(repo / "data"), "--out", raw],
        "graph_concept": [
            "diag_graph.py",
            "--file",
            str(graph),
            "--out",
            str(out / "raw_graph_concept"),
            "--nodes-key",
            "concepts",
            "--id-field",
            "concept_id",
            "--prereq-field",
            "prerequisite_concept_ids",
            "--grade-field",
            "grade_band_hint",
            "--grade-order",
            json.dumps(GRADE_ORDER, ensure_ascii=False),
        ],
    }


def run_tool(name: str, args: list[str], timeout: int) -> dict:
    """도구 하나를 실행하고 결과 요약을 돌려준다. 실패해도 예외를 던지지 않는다."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, str(DIAG / args[0]), *args[1:]],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        code, err = proc.returncode, proc.stderr
    except subprocess.TimeoutExpired:
        code, err = -1, f"{timeout}초 시간 초과"
    except OSError as exc:
        code, err = -2, f"실행 불가: {type(exc).__name__}: {exc}"
    return {
        "tool": name,
        "exit": code,
        "seconds": round(time.monotonic() - started, 1),
        "stderr_tail": "\n".join(err.strip().splitlines()[-20:]) if code != 0 else "",
    }


def nul_damaged(folder: Path) -> list[str]:
    """출력 폴더에서 NUL 바이트가 든 파일 목록 (Cowork 쓰기 손상 KR-02 점검)."""
    return [str(p) for p in folder.rglob("*") if p.is_file() and b"\x00" in p.read_bytes()]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="진단 기준선 러너")
    ap.add_argument("--repo", type=Path, default=ROOT)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--since", default="2026-08-27", help="변경 이력 집계 시작일(EOS 계획 Phase 0)")
    ap.add_argument("--only", default="", help="쉼표로 나눈 도구 이름만 실행")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    repo = args.repo.resolve()
    out = args.out or ROOT / "work" / "diag" / datetime.now().strftime("%Y%m%d_%H%M%S")
    tools = plan(repo, out, args.since)
    if not tools:
        raise RuntimeError(
            "도구 목록이 비었다 — 러너 설정 오류(0건 실행을 성공으로 위장하지 않는다)"
        )
    wanted = [t.strip() for t in args.only.split(",") if t.strip()] or list(tools)
    unknown = [t for t in wanted if t not in tools]
    if unknown:
        print(f"⛔ 알 수 없는 도구: {unknown} (가능: {', '.join(tools)})", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)

    results = []
    for name in wanted:
        res = run_tool(name, tools[name], args.timeout)
        results.append(res)
        mark = "✅" if res["exit"] == 0 else "⛔"
        print(f"{mark} {name}: exit {res['exit']} · {res['seconds']}초")
        if res["stderr_tail"]:
            print("   " + res["stderr_tail"].replace("\n", "\n   "))

    damaged = nul_damaged(out)
    summary = {
        "repo": str(repo),
        "out": str(out),
        "since": args.since,
        "results": results,
        "failed": [r["tool"] for r in results if r["exit"] != 0],
        "nul_damaged": damaged,
    }
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    lines = ["# 진단 기준선 실행 요약", "", f"- 저장소: `{repo}`", f"- 출력: `{out}`", ""]
    lines += ["| 도구 | 종료 코드 | 초 |", "|---|---|---|"]
    lines += [f"| {r['tool']} | {r['exit']} | {r['seconds']} |" for r in results]
    lines += ["", f"- NUL 손상 파일: {damaged or '없음'}"]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"요약: {out / 'summary.md'} · NUL 손상 {len(damaged)}건")
    return 1 if summary["failed"] or damaged else 0


if __name__ == "__main__":
    sys.exit(main())
