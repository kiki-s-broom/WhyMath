"""RS-D5 테스트 대응표 집계 — 테스트 파일이 어느 옛 패키지를 import하는지 ast로만 센다.

옛 코드 살리기(RS) 진단 전용 도구다. 학생 경로와 무관하다.
- 테스트를 실행하지 않는다. 각 파일을 ast로 파싱해 import 문만 모은다(본문 의미는 보지 않는다).
- 결과는 "정적 근사"다: import했다고 실행했다는 뜻이 아니고,
  import 안 했다고 검사 안 한다는 뜻도 아니다
  (예: HTTP 클라이언트로 앱 전체를 부르는 테스트는 `whymath_backend.app` 하나만 import한다).

재생성(src/backend에서 · 기본 출력은 저장소의 golden/reports_rescue/D5):
    python -m golden.rescue.testmap
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

# 저장소 루트(src/backend/golden/rescue/testmap.py에서 네 단계 위)
REPO_ROOT = Path(__file__).resolve().parents[4]

# 이 묶음이 "옛 모듈"로 세는 import 뿌리와 그 소스 폴더(저장소 루트 기준)
SOURCE_ROOTS = {
    "whymath_backend": "src/backend/whymath_backend",
    "golden": "src/backend/golden",
}
# 옛 모듈은 아니지만 "옛 모듈을 import하지 않는 테스트"가 무엇을 보는지 설명하려고 함께 적는 뿌리
OTHER_FIRST_PARTY = ("data_pipeline", "scripts", "tests")
# 동적 import로 보는 호출 이름(첫 인자가 문자열 상수일 때만)
DYNAMIC_IMPORT_FUNCS = {"import_module", "importorskip", "__import__"}


def git_ls(root: Path, prefix: str) -> list[str]:
    """git이 추적하는 파일 목록(실제 파일 수의 기준)."""
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", prefix],
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout.decode("utf-8")
    return sorted(p for p in out.split("\0") if p)


def count_lines(path: Path) -> int:
    """줄 수 — `wc -l`과 같은 뜻(줄바꿈 개수, 마지막 줄에 줄바꿈이 없으면 +1)."""
    data = path.read_bytes()
    if not data:
        return 0
    n = data.count(b"\n")
    return n if data.endswith(b"\n") else n + 1


def module_name(rel: str, root_name: str, root_dir: str) -> str:
    """파일 경로 → 점 표기 모듈 이름(`__init__.py`는 패키지 이름)."""
    sub = Path(rel).relative_to(root_dir).with_suffix("")
    parts = [root_name, *sub.parts]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def package_of(mod: str) -> str:
    """2단계 패키지. golden은 파트 A 전체를 한 단위로 본다."""
    parts = mod.split(".")
    if parts[0] == "golden":
        return "golden"
    return ".".join(parts[:2])


def resolve(target: str, names: list[str], known: set[str]) -> tuple[list[str], list[str]]:
    """import 대상 → 실제 모듈 이름들.

    `from a.b import c`에서 a.b.c가 모듈이면 그것, 아니면 a.b(c는 a.b 안의 이름)로 본다.
    a.b 자체가 없으면(지워졌거나 옮겨진 모듈) 상위 패키지로 내려가 세지 않고
    '해석 못 함'으로만 남긴다.
    """
    found: list[str] = []
    unresolved: list[str] = []
    for name in names or [""]:
        cand = f"{target}.{name}" if name and name != "*" else target
        if cand in known:
            found.append(cand)
        elif target in known:
            found.append(target)
        else:
            unresolved.append(target)
    return found, unresolved


def scan_test(path: Path, known: set[str]) -> dict[str, Any]:
    """테스트 한 파일의 import를 ast로 모은다(본문 실행·해석 없음)."""
    info: dict[str, Any] = {
        "mods": Counter(),
        "other": set(),
        "unresolved": set(),
        "dynamic": 0,
        "error": "",
    }
    try:
        tree = ast.parse(path.read_bytes(), filename=str(path))
    except SyntaxError as exc:  # 파싱 실패는 행을 지우지 않고 비고에 남긴다
        info["error"] = f"파싱 실패: {type(exc).__name__}"
        return info
    for node in ast.walk(tree):
        pairs: list[tuple[str, list[str]]] = []
        if isinstance(node, ast.Import):
            pairs = [(a.name, []) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            pairs = [(node.module, [a.name for a in node.names])]
        elif isinstance(node, ast.Call) and node.args:
            fn = node.func
            fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            arg = node.args[0]
            if fname in DYNAMIC_IMPORT_FUNCS and isinstance(arg, ast.Constant):
                if isinstance(arg.value, str) and arg.value.split(".")[0] in SOURCE_ROOTS:
                    pairs = [(arg.value, [])]
                    info["dynamic"] += 1
        for target, names in pairs:
            root = target.split(".")[0]
            if root in SOURCE_ROOTS:
                found, unres = resolve(target, names, known)
                info["mods"].update(found)
                info["unresolved"].update(unres)
            elif root in OTHER_FIRST_PARTY:
                info["other"].add(root)
    return info


# 산출물 머리줄(열 순서 고정)
HEAD_TEST = [
    "테스트 경로", "줄 수", "상위 폴더",
    "import하는 옛 모듈 수(목록은 테스트_대응_모듈목록.tsv · 정적 근사)",
    "대표 패키지(가장 많이 import한 2단계 패키지)", "대표 패키지 동점",
    "기타 1자 import 뿌리", "해석 못 한 import", "동적 import 수", "비고",
]  # fmt: skip
HEAD_MODLIST = [
    "테스트 경로",
    "import하는 옛 모듈 목록(정적 근사 · 'whymath_backend.' 접두 생략 · golden.*은 그대로)",
]
HEAD_MODULE = [
    "모듈", "파일 경로", "줄 수", "2단계 패키지",
    "직접 import하는 테스트 파일 수(정적 근사·실행 아님)", "비고",
]  # fmt: skip
NOTE_INIT = "패키지 __init__ — `from 패키지 import 이름`(이름이 모듈이 아닐 때)도 여기로 센다"


def write_tsv(path: Path, header: list[str], body: Iterable[Sequence[object]]) -> None:
    """엑셀에서 한글이 안 깨지게 utf-8-sig로 쓴다."""
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(header)
        w.writerows(body)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(REPO_ROOT), help="저장소 루트")
    ap.add_argument(
        "--out", default=None, help="산출물 폴더(기본: <root>/golden/reports_rescue/D5)"
    )
    args = ap.parse_args()
    root = Path(args.root).resolve()
    out = Path(args.out) if args.out else root / "golden" / "reports_rescue" / "D5"
    out.mkdir(parents=True, exist_ok=True)

    # 1) 소스 모듈 목록(파일 시스템 기준 — grimp가 못 보는 l1/rights도 포함)
    src: dict[str, dict[str, Any]] = {}
    for root_name, root_dir in SOURCE_ROOTS.items():
        for rel in git_ls(root, root_dir):
            if rel.endswith(".py"):
                mod = module_name(rel, root_name, root_dir)
                src[mod] = {"path": rel, "lines": count_lines(root / rel)}
    known = set(src)
    # 디렉터리는 있지만 __init__.py가 없는 네임스페이스 패키지도 import 대상이 될 수 있다
    for mod in list(known):
        parts = mod.split(".")
        for i in range(1, len(parts)):
            known.add(".".join(parts[:i]))

    # 2) 테스트 파일 스캔
    tests = [p for p in git_ls(root, "tests") if p.endswith(".py")]
    rows: list[dict[str, Any]] = []
    by_mod: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for rel in tests:
        info = scan_test(root / rel, known)
        top = rel.split("/")[1] if rel.count("/") >= 2 else "(tests 바로 아래)"
        mods = sorted(info["mods"])
        pkg_cnt = Counter(package_of(m) for m in mods)
        # 대표 패키지 = 서로 다른 모듈을 가장 많이 import한 2단계 패키지(동점이면 이름순 첫째)
        leaders = sorted(p for p, c in pkg_cnt.items() if c == max(pkg_cnt.values()))
        for m in mods:
            by_mod[m][top] += 1
        rows.append(
            dict(path=rel, lines=count_lines(root / rel), top=top, mods=mods, pkgs=sorted(pkg_cnt),
                 rep=leaders[0] if leaders else "",
                 tie="동점: " + ", ".join(leaders) if len(leaders) > 1 else "",
                 other=sorted(info["other"]), unresolved=sorted(info["unresolved"]),
                 dynamic=info["dynamic"], error=info["error"])
        )  # fmt: skip

    # 3) 테스트_대응.tsv — 테스트 파일 한 개당 한 행.
    #    모듈 목록까지 한 파일에 넣으면 327KB라 커밋 상한(200KB)을 넘는다.
    #    그래서 같은 행 순서의 두 파일로 나눈다(경로 열로 이어 붙인다).
    write_tsv(out / "테스트_대응.tsv", HEAD_TEST, (
        [r["path"], r["lines"], r["top"], len(r["mods"]), r["rep"] or "(없음)", r["tie"],
         ";".join(r["other"]), ";".join(r["unresolved"]), r["dynamic"], r["error"]]
        for r in rows
    ))  # fmt: skip
    write_tsv(out / "테스트_대응_모듈목록.tsv", HEAD_MODLIST, (
        [r["path"], ";".join(m.removeprefix("whymath_backend.") for m in r["mods"])]
        for r in rows
    ))  # fmt: skip

    # 4) 모듈별_테스트수.tsv — whymath_backend 모듈 한 개당 한 행(844행 기대)
    tops = sorted({r["top"] for r in rows})
    legacy = sorted(m for m in src if m.split(".")[0] == "whymath_backend")
    write_tsv(
        out / "모듈별_테스트수.tsv",
        [*HEAD_MODULE[:5], *[f"그중 tests/{t}" for t in tops], HEAD_MODULE[5]],
        (
            [m, src[m]["path"], src[m]["lines"], package_of(m), sum(by_mod[m].values()),
             *[by_mod[m][t] for t in tops],
             NOTE_INIT if src[m]["path"].endswith("__init__.py") else ""]
            for m in legacy
        ),
    )  # fmt: skip

    # 5) 패키지별 집계 — 요약.md의 표 재료(JSON)
    pk: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for m, meta in src.items():
        pk[package_of(m)].update(mods=1, src_lines=meta["lines"])
        if m.split(".")[0] == "whymath_backend" and not by_mod[m]:
            pk[package_of(m)].update(zero=1, zero_lines=meta["lines"])
    for r in rows:
        if r["rep"]:
            pk[r["rep"]].update(rep_files=1, rep_lines=r["lines"])
        for p in r["pkgs"]:
            pk[p].update(any_files=1, any_lines=r["lines"])
    none_rows = [r for r in rows if not r["mods"]]

    def by_top(rs: list[dict[str, Any]], key: str | None = None) -> Counter[str]:
        """상위 폴더별 파일 수(key가 있으면 그 값의 합)."""
        return Counter({t: sum(r[key] if key else 1 for r in rs if r["top"] == t) for t in tops})

    summary: dict[str, Any] = {
        "test_files": len(rows),
        "test_lines": sum(r["lines"] for r in rows),
        "legacy_modules": len(legacy),
        "golden_modules": sum(1 for m in src if m.startswith("golden")),
        "parse_errors": [r["path"] for r in rows if r["error"]],
        "files_by_top": by_top(rows),
        "lines_by_top": by_top(rows, "lines"),
        "no_legacy_by_top": +by_top(none_rows),
        "no_legacy_lines_by_top": by_top(none_rows, "lines"),
        "no_legacy_other_roots": Counter(
            ";".join(r["other"]) or "(1자 import 없음)" for r in none_rows
        ),
        "rep_ties": sum(1 for r in rows if r["tie"]),
        "unresolved_files": sum(1 for r in rows if r["unresolved"]),
        "unresolved_targets": Counter(u for r in rows for u in r["unresolved"]),
        "dynamic_files": sum(1 for r in rows if r["dynamic"]),
        "packages": pk,
        "zero_total": sum(1 for m in legacy if not by_mod[m]),
        "top_modules": Counter({m: sum(c.values()) for m, c in by_mod.items()}).most_common(15),
    }  # fmt: skip
    (out / "집계.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=dict), encoding="utf-8"
    )

    # 6) 자체 검사 — 쓴 파일을 다시 읽어 행 수(머리줄 제외)가 실제 파일 수와 같은지 본다
    #    (쓰기 도중 잘림까지 잡는다 · 다르면 종료 코드 1)
    n_backend = sum(1 for p in git_ls(root, SOURCE_ROOTS["whymath_backend"]) if p.endswith(".py"))
    want = {"테스트_대응.tsv": len(tests), "테스트_대응_모듈목록.tsv": len(tests)}
    want["모듈별_테스트수.tsv"] = n_backend
    ok = True
    for name, b in want.items():
        with (out / name).open(encoding="utf-8-sig", newline="") as fh:
            a = sum(1 for _ in csv.reader(fh, delimiter="\t")) - 1
        ok = ok and a == b
        print(f"{name}: 데이터 {a}행 / 실제 파일 {b}개 · {'일치' if a == b else '불일치'}")
    print(f"자체검사 {'통과' if ok else '실패'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
