"""S15 할 일 1 — golden이 3주간 한 번도 쓰지 않은 옛 모듈 목록을 측정한다.

실행: `cd src/backend && python -m golden.measure_unreferenced`
S20A 예산 판정: `cd src/backend && python -m golden.measure_unreferenced --budget`
(파일을 쓰지 않음 · 직접 ≤10 · 전이 ≤30 · 넘으면 exit 1)

결과는 `golden/reports_no_students/S15/`에 쓴다. 학생 경로(GP-1~GP-6)와 무관한 측정 도구라
`golden.api`는 이 모듈을 import하지 않는다(S11 `sim_student.py`와 같은 자리 · CI 린트 대상 위치).

하는 일
1. 백엔드: grimp로 whymath_backend + golden 그래프를 만들고, golden 패키지의 상류
   (find_upstream_modules — golden이 직간접 import하는 모듈) 중 whymath_backend.* 를
   "쓰는 모듈"로 본다. 보정 3가지(조상 패키지 · 런타임 실측 · 그래프 밖 파일)를 더한 뒤,
   전체에서 빼면 "쓰지 않는 모듈".
2. Flutter: lib/main_golden.dart 와 lib/golden/*.dart 에서 시작해 import/export/part 를 따라가며
   닿는 lib/ 파일을 전수 열거한다(같은 패키지 안만).
3. 결과를 TSV 4개 + 요약 JSON + HARVEST용 압축 표(마크다운)로 쓴다.
   저장소 밖으로는 아무것도 보내지 않는다.

해석 범위(정직한 공백)
- grimp는 정적 import 문만 본다(함수 안의 지연 import는 포함, importlib 문자열 로딩은 제외 —
  그쪽은 보정 ②의 런타임 실측이 import 시점에 일어난 것만 잡는다).
- "golden이 쓰지 않는다"는 "죽은 코드"가 아니다 — 옛 create_app·옛 테스트·CLI 스크립트는
  여전히 쓴다.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import grimp

# 이 파일 위치(src/backend/golden/)에서 저장소 루트를 찾는다 — 세 단계 위
REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "golden" / "reports_no_students" / "S15"
BACKEND = REPO / "src" / "backend"
MOBILE = REPO / "src" / "mobile"
OLD = "whymath_backend"
SELF = "golden.measure_unreferenced"

# Dart import/export/part 문 — 작은따옴표·큰따옴표 모두
DART_DIRECTIVE = re.compile(r"""^\s*(?:import|export|part)\s+['"]([^'"]+)['"]""", re.M)


def is_old(mod: str) -> bool:
    """옛 패키지(whymath_backend) 소속인가."""
    return mod == OLD or mod.startswith(OLD + ".")


def module_to_path(mod: str) -> Path:
    """모듈 이름을 파일 경로로 바꾼다. 패키지면 __init__.py."""
    base = BACKEND.joinpath(*mod.split("."))
    if (base / "__init__.py").exists():
        return base / "__init__.py"
    return base.with_suffix(".py")


def line_count(p: Path) -> int:
    """파일 줄 수(wc -l과 같은 기준: 개행 수)."""
    return p.read_bytes().count(b"\n")


def top2(mod: str) -> str:
    """whymath_backend.l3.providers.x → whymath_backend.l3 (하위 패키지 집계용)."""
    return ".".join(mod.split(".")[:2])


def ancestors(mod: str) -> list[str]:
    """a.b.c → [a, a.b]. import a.b.c 하면 이 패키지들의 __init__.py도 실행된다."""
    parts = mod.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts))]


def close_over_ancestors(graph: grimp.ImportGraph, start: set[str]) -> set[str]:
    """보정 ①: 조상 패키지와 그 조상이 import하는 옛 모듈을 더 늘지 않을 때까지 더한다.

    grimp는 "a.b.c를 import하면 a/__init__·a/b/__init__도 실행된다"를 의존으로 세지 않는다.
    """
    closure = set(start)
    while True:
        add = {anc for m in closure for anc in ancestors(m)} - closure
        for anc in list(add):
            add |= {u for u in graph.find_upstream_modules(anc) if is_old(u)}
        add -= closure
        if not add:
            return closure
        closure |= add


def filesystem_modules() -> set[str]:
    """보정 ③: 파일 시스템 기준 옛 모듈 전체.

    __init__.py 없는 디렉터리(네임스페이스 패키지 — 실측 whymath_backend/l1/rights/ 5파일)는
    grimp 그래프에 아예 없어서 파일로 다시 센다.
    """
    mods: set[str] = set()
    for path in (BACKEND / OLD).rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        parts = list(path.relative_to(BACKEND).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        mods.add(".".join(parts))
    return mods


def write_tsv(name: str, header: str, rows: list[tuple[str, ...]]) -> None:
    """탭 구분 파일 하나를 쓴다."""
    lines = [header] + ["\t".join(r) for r in rows]
    (OUT / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def measure_backend() -> dict[str, Any]:
    """백엔드 그래프 측정."""
    sys.path.insert(0, str(BACKEND))
    graph = grimp.build_graph(OLD, "golden")
    graph_old = {m for m in graph.modules if is_old(m)}
    static_direct = {m for m in graph.find_upstream_modules("golden", as_package=True) if is_old(m)}
    closure = close_over_ancestors(graph, static_direct)

    # 보정 ②: 런타임 실측 — golden 모듈을 실제로 import한 뒤 sys.modules에 올라온 옛 모듈.
    # 가짜 LLM 모드로 import만 한다(네트워크·DB 접속 없음).
    # 이 측정 모듈 자신은 다시 import하지 않는다.
    os.environ.setdefault("GOLDEN_FAKE_LLM", "1")
    for gm in sorted(m for m in graph.modules if m.startswith("golden.") and m != SELF):
        importlib.import_module(gm)

    fs_mods = filesystem_modules()
    all_old = sorted(graph_old | fs_mods)
    runtime = {k for k in sys.modules if is_old(k)} & set(all_old)  # 실제 파일이 있는 모듈만
    used = sorted(closure | runtime)
    used_set = set(used)
    unused = [m for m in all_old if m not in used_set]

    def row(mod: str) -> tuple[str, str, int]:
        path = module_to_path(mod)
        return mod, str(path.relative_to(REPO)), line_count(path)

    rows_used = [row(m) for m in used]
    rows_unused = [row(m) for m in unused]
    write_tsv(
        "referenced_backend.tsv", "module\tpath\tlines", [(m, p, str(n)) for m, p, n in rows_used]
    )
    write_tsv(
        "unreferenced_backend.tsv",
        "module\tpath\tlines",
        [(m, p, str(n)) for m, p, n in rows_unused],
    )

    # 하위 패키지별 집계
    agg: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "used": 0, "unused": 0, "unused_lines": 0, "used_lines": 0}
    )
    for mod, _, n in rows_used:
        agg[top2(mod)]["total"] += 1
        agg[top2(mod)]["used"] += 1
        agg[top2(mod)]["used_lines"] += n
    for mod, _, n in rows_unused:
        agg[top2(mod)]["total"] += 1
        agg[top2(mod)]["unused"] += 1
        agg[top2(mod)]["unused_lines"] += n

    # golden 모듈별로 직접 import한 옛 모듈(어디서 끌려왔는지 보이게)
    direct = {
        gm: sorted(m for m in graph.find_modules_directly_imported_by(gm) if is_old(m))
        for gm in sorted(m for m in graph.modules if m.startswith("golden."))
    }
    used_lines = sum(n for *_, n in rows_used)
    unused_lines = sum(n for *_, n in rows_unused)
    return {
        "all_modules": len(all_old),
        "all_lines": used_lines + unused_lines,
        "grimp_graph_modules": len(graph_old),
        "missing_from_grimp_graph": sorted(fs_mods - graph_old),
        "static_direct_modules": len(static_direct),
        "static_with_ancestors_modules": len(closure),
        "runtime_modules": len(runtime),
        "runtime_only": sorted(runtime - closure),
        "static_only": sorted(closure - runtime),
        "used_modules": len(used),
        "used_lines": used_lines,
        "unused_modules": len(unused),
        "unused_lines": unused_lines,
        "by_subpackage": dict(sorted(agg.items())),
        "golden_direct_imports": {k: v for k, v in direct.items() if v},
    }


def measure_flutter() -> dict[str, Any]:
    """Flutter: 골든 진입점에서 닿는 lib/ 파일 전수 열거."""
    match = re.search(
        r"^name:\s*(\S+)", (MOBILE / "pubspec.yaml").read_text(encoding="utf-8"), re.M
    )
    if match is None:
        raise RuntimeError("pubspec.yaml에서 패키지 이름을 찾지 못했다")  # 침묵 실패 금지
    pkg = match.group(1)
    lib = MOBILE / "lib"
    seen: set[Path] = set()
    external: set[str] = set()
    stack = [lib / "main_golden.dart", *sorted((lib / "golden").glob("*.dart"))]
    while stack:
        path = stack.pop().resolve()
        if path in seen or not path.exists():
            continue
        seen.add(path)
        for uri in DART_DIRECTIVE.findall(path.read_text(encoding="utf-8")):
            if uri.startswith(f"package:{pkg}/"):
                stack.append(lib / uri[len(f"package:{pkg}/") :])
            elif uri.startswith(("package:", "dart:")):
                external.add(uri.split("/")[0])  # 외부 패키지 이름만
            else:
                stack.append(path.parent / uri)  # 상대 경로

    reached = sorted(str(p.relative_to(REPO)) for p in seen)
    all_lib = sorted(p.resolve() for p in lib.rglob("*.dart"))
    # 생성 파일(*.g.dart·*.freezed.dart)은 빌드 산출물이라 따로 센다
    generated = [p for p in all_lib if p.name.endswith((".g.dart", ".freezed.dart"))]
    source = [p for p in all_lib if p not in generated]
    unused = [p for p in source if p not in seen]
    write_tsv(
        "flutter_golden_imports.tsv",
        "path\tlines",
        [(r, str(line_count(REPO / r))) for r in reached],
    )
    write_tsv(
        "unreferenced_flutter.tsv",
        "path\tlines",
        [(str(p.relative_to(REPO)), str(line_count(p))) for p in unused],
    )
    golden_paths = ("src/mobile/lib/golden/", "src/mobile/lib/main_golden.dart")
    return {
        "package": pkg,
        "reached_files": reached,
        "reached_lines": sum(line_count(REPO / r) for r in reached),
        "old_files_reached": [r for r in reached if not r.startswith(golden_paths)],
        "external_packages": sorted(external),
        "lib_dart_files_total": len(all_lib),
        "lib_generated_files": len(generated),
        "lib_source_files": len(source),
        "unused_source_files": len(unused),
        "unused_source_lines": sum(line_count(p) for p in unused),
    }


def compact(
    unused: list[tuple[str, int]], used: list[str], depth: int
) -> list[tuple[str, int, int]]:
    """미사용 파일 목록에서 '통째로 안 쓰는 가장 위 디렉터리'는 한 줄로 접는다.

    unused: (경로, 줄 수). used: 쓰는 파일 경로. depth: 접기 시작할 경로 깊이
    (예: src/backend/whymath_backend/<x> → 4 — 그보다 위 디렉터리는 접지 않는다).
    반환: (경로, 파일 수, 줄 수). 쓰는 파일이 섞인 디렉터리는 파일 단위로 남긴다.
    """

    def has_used(dirp: str) -> bool:
        return any(u.startswith(dirp + "/") for u in used)

    rows: list[tuple[str, int, int]] = []
    done: set[str] = set()
    for path, n in sorted(unused):
        parts = path.split("/")
        col = next(
            (
                "/".join(parts[:i])
                for i in range(depth, len(parts))
                if not has_used("/".join(parts[:i]))
            ),
            None,
        )
        if col is None:
            rows.append((path, 1, n))
        elif col not in done:
            done.add(col)
            sub = [k for q, k in unused if q.startswith(col + "/")]
            rows.append((col + "/", len(sub), sum(sub)))
    return rows


def read_tsv(name: str) -> list[list[str]]:
    """write_tsv로 쓴 파일을 머리줄 없이 읽는다."""
    lines = (OUT / name).read_text(encoding="utf-8").splitlines()[1:]
    return [ln.split("\t") for ln in lines]


def write_compact() -> None:
    """HARVEST.md에 붙일 압축 표(마크다운)를 만든다."""
    backend_rows = compact(
        [(r[1], int(r[2])) for r in read_tsv("unreferenced_backend.tsv")],
        [r[1] for r in read_tsv("referenced_backend.tsv")],
        4,
    )
    flutter_rows = compact(
        [(r[0], int(r[1])) for r in read_tsv("unreferenced_flutter.tsv")],
        [r[0] for r in read_tsv("flutter_golden_imports.tsv")],
        4,
    )
    out = ["<!-- golden.measure_unreferenced 가 생성 — 손으로 고치지 않는다 -->", ""]
    for title, rows in (
        ("백엔드 (`src/backend/whymath_backend/`)", backend_rows),
        ("Flutter (`src/mobile/lib/`)", flutter_rows),
    ):
        out += [f"#### {title} — {len(rows)}줄로 접음", ""]
        out += ["| 경로 | 파일 수 | 줄 수 |", "| --- | ---: | ---: |"]
        out += [f"| `{p}` | {k} | {n:,} |" for p, k, n in rows]
        out.append("")
    (OUT / "unreferenced_compact.md").write_text("\n".join(out), encoding="utf-8")


# S20A 전이 의존 예산(개정판 S20+1 · 공통 규칙 8) — 골든이 쓰는 옛 모듈 수의 상한
BUDGET_DIRECT = 10  # 골든 모듈이 import 문으로 직접 부르는 옛 모듈(서로 다른 것) 수
BUDGET_TRANSITIVE = 30  # 그 상류 전체(조상 패키지 보정 + 런타임 실측 합집합) 수

# 런타임 실측용 하위 프로세스 코드 — 깨끗한 인터프리터에서 골든 모듈만 import하고
# 옛 모듈 이름을 낸다.
# (pytest 프로세스는 특성화 테스트가 옛 모듈을 직접 import하므로 sys.modules가 오염돼 있다)
_RUNTIME_PROBE = (
    "import importlib, json, sys\n"
    "for m in sys.argv[1:]:\n"
    "    importlib.import_module(m)\n"
    "print(json.dumps(sorted(k for k in sys.modules if k == 'whymath_backend'"
    " or k.startswith('whymath_backend.'))))\n"
)


def measure_budget() -> dict[str, Any]:
    """예산 판정에 쓰는 숫자만 센다. 파일을 쓰지 않는다(S15 측정 결과를 덮어쓰지 않게).

    - direct: 골든 모듈 각각이 직접 import하는 옛 모듈의 합집합
    - transitive: 정적 상류(조상 패키지 보정 포함 — measure_backend와 같은 계산) ∪ 런타임 실측
    """
    import subprocess  # 예산 모드에서만 쓴다

    sys.path.insert(0, str(BACKEND))
    graph = grimp.build_graph(OLD, "golden")
    golden_mods = sorted(m for m in graph.modules if m.startswith("golden."))
    direct = sorted(
        {m for gm in golden_mods for m in graph.find_modules_directly_imported_by(gm) if is_old(m)}
    )
    static_direct = {m for m in graph.find_upstream_modules("golden", as_package=True) if is_old(m)}
    closure = close_over_ancestors(graph, static_direct)

    env = {**os.environ, "GOLDEN_FAKE_LLM": "1"}
    probe = subprocess.run(
        [sys.executable, "-c", _RUNTIME_PROBE, *[m for m in golden_mods if m != SELF]],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    if probe.returncode != 0:
        # 침묵 실패 금지 — 런타임 실측이 안 되면 숫자를 내지 않는다
        raise RuntimeError(f"런타임 실측 실패(exit {probe.returncode}): {probe.stderr[-2000:]}")
    fs_mods = filesystem_modules() | {m for m in graph.modules if is_old(m)}
    runtime = set(json.loads(probe.stdout.strip().splitlines()[-1])) & fs_mods
    transitive = sorted(closure | runtime)
    top: defaultdict[str, int] = defaultdict(int)
    for m in transitive:
        top[top2(m)] += 1
    return {
        "direct": direct,
        "direct_count": len(direct),
        "static_with_ancestors_count": len(closure),
        "runtime_count": len(runtime),
        "runtime_only": sorted(runtime - closure),
        "transitive": transitive,
        "transitive_count": len(transitive),
        "by_subpackage": dict(sorted(top.items(), key=lambda kv: (-kv[1], kv[0]))),
        "budget": {"direct": BUDGET_DIRECT, "transitive": BUDGET_TRANSITIVE},
        "within_budget": len(direct) <= BUDGET_DIRECT and len(transitive) <= BUDGET_TRANSITIVE,
    }


def main(argv: list[str] | None = None) -> int:
    """측정을 돌리고 요약 두 줄을 출력한다. `--budget`이면 예산 판정만 하고 파일은 쓰지 않는다."""
    args = sys.argv[1:] if argv is None else argv
    if args == ["--budget"]:
        result = measure_budget()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        # 예산을 넘으면 exit 1 — 판정은 exit code로 한다
        return 0 if result["within_budget"] else 1
    if args:
        raise SystemExit(f"알 수 없는 인자: {args} (쓸 수 있는 것: --budget)")
    OUT.mkdir(parents=True, exist_ok=True)
    backend = measure_backend()
    flutter = measure_flutter()
    summary = {"backend": backend, "flutter": flutter}
    (OUT / "measure_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_compact()
    print(
        f"backend: 전체 {backend['all_modules']}모듈 {backend['all_lines']}줄 · "
        f"golden 사용 {backend['used_modules']}모듈 {backend['used_lines']}줄 · "
        f"미사용 {backend['unused_modules']}모듈 {backend['unused_lines']}줄"
    )
    print(
        f"flutter: 골든 진입점 도달 {len(flutter['reached_files'])}파일 "
        f"{flutter['reached_lines']}줄 (옛 파일 {len(flutter['old_files_reached'])}개) · "
        f"lib 소스 {flutter['lib_source_files']}개 중 "
        f"미도달 {flutter['unused_source_files']}개 {flutter['unused_source_lines']}줄"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
