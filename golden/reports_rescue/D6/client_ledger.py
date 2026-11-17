"""RS-D6 클라이언트 대장 생성기 — Flutter(src/mobile/lib)·웹(src/web/webapp) import 도달성 측정.

진단 전용이다. 앱을 빌드·실행하지 않고, 소스 파일의 import 문만 정적으로 따라간다.
재생성: 저장소 루트에서 `python3 golden/reports_rescue/D6/client_ledger.py`
"""

from __future__ import annotations

import csv
import re
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # 저장소 루트
OUT = Path(__file__).resolve().parent
MOBILE = "src/mobile"
WEBAPP = "src/web/webapp"


def git_files(prefix: str) -> list[str]:
    """git이 추적하는 파일만 센다(빌드 산출물·node_modules 제외)."""
    out = subprocess.run(
        ["git", "ls-files", prefix], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line]


def line_count(rel: str) -> int:
    with open(ROOT / rel, encoding="utf-8", errors="replace") as fh:
        return sum(1 for _ in fh)


def strip_comments(text: str) -> str:
    """블록 주석과 줄 주석을 지운다(문자열 안의 // 는 import 문에 없으므로 단순 처리)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", text)


# ---------------------------------------------------------------- Flutter(Dart)
DART_DIRECTIVE = re.compile(r"\b(import|export|part)\s+'([^']+)'([^;]*);", re.S)
DART_COND = re.compile(r"if\s*\([^)]*\)\s*'([^']+)'")


def dart_targets(rel: str, pkg: str) -> list[str]:
    """한 Dart 파일이 import·export·part로 가리키는 저장소 경로 목록(조건부 import 포함)."""
    text = strip_comments((ROOT / rel).read_text(encoding="utf-8", errors="replace"))
    found: list[str] = []
    base = Path(rel).parent
    for kind, uri, rest in DART_DIRECTIVE.findall(text):
        if kind == "part" and uri.startswith("of"):
            continue
        uris = [uri] + DART_COND.findall(rest)
        for u in uris:
            if u.startswith("dart:"):
                continue
            if u.startswith("package:"):
                name, _, sub = u[len("package:") :].partition("/")
                if name != pkg:
                    continue  # 외부 패키지
                found.append(f"{MOBILE}/lib/{sub}")
            else:
                found.append(str((base / u).as_posix()))
    # 정규화(../ 해소)
    return [str(Path(p).resolve().relative_to(ROOT).as_posix()) for p in (ROOT / f for f in found)]


# ---------------------------------------------------------------- 웹(TS)
TS_IMPORT = re.compile(
    r"""(?:import|export)\s+(?:type\s+)?(?:[^'";]*?\sfrom\s+)?['"]([^'"]+)['"]"""
    r"""|import\(\s*['"]([^'"]+)['"]\s*\)|require\(\s*['"]([^'"]+)['"]\s*\)"""
)
TS_EXT = ["", ".ts", ".tsx", ".js", ".jsx", ".mjs", "/index.ts", "/index.tsx", "/index.js"]


def ts_targets(rel: str, universe: set[str]) -> tuple[list[str], list[str]]:
    """한 TS 파일이 가리키는 저장소 경로(해결됨)와 해결 실패한 상대 경로."""
    text = strip_comments((ROOT / rel).read_text(encoding="utf-8", errors="replace"))
    found, unresolved = [], []
    base = Path(rel).parent
    for groups in TS_IMPORT.findall(text):
        spec = next(g for g in groups if g)
        if spec.startswith("@/"):
            cand = Path(WEBAPP) / spec[2:]
        elif spec.startswith("."):
            cand = base / spec
        else:
            continue  # 외부 패키지(react·next 등)
        cand_s = str((ROOT / cand).resolve().relative_to(ROOT).as_posix())
        hit = next((cand_s + e for e in TS_EXT if cand_s + e in universe), None)
        if hit:
            found.append(hit)
        else:
            unresolved.append(spec)
    return found, unresolved


def closure(starts: list[str], edges: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = list(starts)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(edges.get(cur, []))
    return seen


def grade(reached: bool, unit: bool) -> str:
    """공유 계약 「등급 판정」 — 경로 테스트 실행 기록이 없으므로 '가동'은 판정하지 않는다."""
    if reached:
        return "대기(실행 기록 없음)"
    return "섬" if unit else "잔해"


def main() -> None:
    rows = []
    summary: dict[str, object] = {}

    # ---- Flutter
    pkg = "korean_math_app"
    lib = sorted(f for f in git_files(f"{MOBILE}/lib") if f.endswith(".dart"))
    tests = sorted(f for f in git_files(f"{MOBILE}/test") if f.endswith(".dart"))
    universe = set(lib) | set(tests)
    edges: dict[str, list[str]] = {}
    missing: list[tuple[str, str]] = []
    for f in lib + tests:
        tg = dart_targets(f, pkg)
        edges[f] = [t for t in tg if t in universe]
        missing += [(f, t) for t in tg if t not in universe]
    golden_entry = [f"{MOBILE}/lib/main_golden.dart"] + [
        f for f in lib if f.startswith(f"{MOBILE}/lib/golden/")
    ]
    old_entry = [f"{MOBILE}/lib/main.dart"]
    g_reach = closure(golden_entry, edges)
    o_reach = closure(old_entry, edges)
    t_reach = closure(tests, edges)
    importers: dict[str, set[str]] = defaultdict(set)
    for src in lib:
        for t in edges[src]:
            importers[t].add(src)
    test_importers: dict[str, set[str]] = defaultdict(set)
    for src in tests:
        for t in edges[src]:
            test_importers[t].add(src)
    manifest = {
        line.strip()
        for line in (ROOT / "golden/LEGACY_MANIFEST.txt").read_text(encoding="utf-8").splitlines()
        if line.strip().startswith(f"{MOBILE}/lib/")
    }
    for f in lib:
        notes = []
        if f in manifest:
            notes.append("매니페스트 등재")
        if f in golden_entry:
            notes.append("골든 진입점")
        if f in old_entry:
            notes.append("옛 진입점")
        notes.append(f"테스트 직접 import {len(test_importers[f])}")
        rows.append(
            [
                f[len(f"{MOBILE}/lib/") :].removesuffix(".dart").replace("/", "."),
                f,
                line_count(f),
                "G-Flutter",
                grade(f in g_reach, f in t_reach),
                grade(f in o_reach, f in t_reach),
                "예" if f in g_reach else "아니오",
                "예" if f in o_reach else "아니오",
                "실행 기록 없음",
                "예(import 기준)" if f in t_reach else "아니오",
                len(importers[f]),
                " · ".join(notes),
            ]
        )
    unref = {f for f in lib if f not in g_reach}
    summary["flutter"] = {
        "lib": len(lib),
        "tests": len(tests),
        "golden_reach": len(g_reach & set(lib)),
        "golden_unref": len(unref),
        "manifest": len(manifest),
        "unref_not_in_manifest": sorted(unref - manifest),
        "manifest_but_reached": sorted(manifest - unref),
        "old_reach": len(o_reach & set(lib)),
        "neither": sorted(f for f in lib if f not in g_reach and f not in o_reach),
        "test_reach": len(t_reach & set(lib)),
        "unresolved": missing,
    }

    # ---- 웹(webapp)
    web_all = git_files(WEBAPP)
    web = sorted(f for f in web_all if f.endswith((".ts", ".tsx")))
    web_universe = {f for f in web_all if f.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs"))}
    w_edges: dict[str, list[str]] = {}
    w_unres: list[tuple[str, str]] = []
    for f in sorted(web_universe):
        tg, un = ts_targets(f, web_universe)
        w_edges[f] = tg
        w_unres += [(f, u) for u in un]
    # Next.js 특수 파일. next.config.ts의 pageExtensions가 빌드 타깃을 둘로 가른다:
    # 공개 타깃 = 접미 tsx·ts(단 *.admin.* 은 라우트 아님) · admin 타깃 = admin.tsx·admin.ts
    special = re.compile(
        r"/app/(.*/)?(page|layout|route|loading|error|not-found|template|default|global-error"
        r"|robots|sitemap|manifest|icon|apple-icon|opengraph-image|twitter-image)"
        r"(\.admin)?\.(tsx?|jsx?)$"
    )
    entries = [f for f in sorted(web_universe) if special.search(f)]
    admin_entries = [f for f in entries if ".admin." in f]
    public_entries = [f for f in entries if ".admin." not in f]
    mw = [f for f in web_universe if re.search(r"/webapp/middleware\.(ts|js)$", f)]
    entries += mw
    cfg = [f for f in web_universe if re.search(r"/webapp/(next\.config|eslint\.config)\.", f)]
    # next.config.ts 는 import 되지 않고 next 빌드가 직접 읽는다 — 도구 진입점으로 계상한다
    entries += [f for f in cfg if f.endswith(".ts")]
    w_reach = closure(entries, w_edges)
    pub_reach = closure(public_entries, w_edges)
    adm_reach = closure(admin_entries, w_edges)
    w_tests = [f for f in web_universe if re.search(r"\.(test|spec)\.(tsx?|jsx?)$", f)]
    w_treach = closure(w_tests, w_edges)
    w_importers: dict[str, set[str]] = defaultdict(set)
    for src, tg in w_edges.items():
        for t in tg:
            w_importers[t].add(src)
    for f in web:
        notes = ["웹 골든 진입점 없음(골든 열은 정의상 아니오)"]
        if f in entries:
            notes.append("Next.js 진입점")
        tg = [n for n, r in (("공개", pub_reach), ("admin", adm_reach)) if f in r]
        notes.append("빌드 타깃 " + ("·".join(tg) if tg else "없음"))
        if f in cfg:
            notes.append("빌드 설정 파일(도구가 직접 읽음)")
        rows.append(
            [
                f[len(f"{WEBAPP}/") :],
                f,
                line_count(f),
                "G-웹",
                grade(False, f in w_treach),
                grade(f in w_reach, f in w_treach),
                "아니오",
                "예" if f in w_reach else "아니오",
                "실행 기록 없음",
                "예(import 기준)" if f in w_treach else "아니오",
                len(w_importers[f]),
                " · ".join(notes),
            ]
        )
    summary["web"] = {
        "files": len(web),
        "entries": len(entries),
        "public_entries": len(public_entries),
        "admin_entries": len(admin_entries),
        "public_reach": len(pub_reach & set(web)),
        "admin_reach": len(adm_reach & set(web)),
        "reach": len(w_reach & set(web)),
        "unreached": sorted(f for f in web if f not in w_reach),
        "tests": len(w_tests),
        "unresolved": w_unres,
    }

    header = [
        "모듈",
        "파일 경로",
        "줄 수",
        "파트",
        "골든 등급",
        "옛앱 등급",
        "골든에서 닿음",
        "옛앱에서 닿음",
        "경로 테스트가 실행",
        "단위 테스트가 실행",
        "이 모듈을 import하는 모듈 수",
        "비고",
    ]
    with open(OUT / "클라이언트_대장.tsv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    import json

    (OUT / "요약.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
