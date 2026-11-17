"""RS-R1 모듈 대장 — 모듈마다 증거 세 가지를 모아 진입점별 등급을 붙인다.

실행: `cd src/backend && python -m golden.rescue.ledger --entry golden.api
      --entry whymath_backend.app --csv 대장.csv [--journey-golden j.json]
      [--journey-legacy j.json] [--unit u.json] [--baseline b.txt [--update]]`
- 첫 번째 `--entry`는 "골든" 열, 두 번째는 "옛앱" 열이다. 분석 패키지는 whymath_backend·golden 고정.
- 실행 기록은 `coverage json`이 만든 JSON(형식 3 · 함수별 `functions` 영역 필요)을 읽는다.
- 진입점 모듈을 import하지 않는다(정적 그래프만) — golden.api도 실행되지 않는다.

증거 세 가지: ①진입점에서 닿는가(grimp 정적 그래프 + 보정) ②경로 테스트가 실행했는가
③단위 테스트가 실행했는가. 등급 = 가동 · 대기 · 섬 · 잔해(RS 공유 계약 「등급 판정」).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import grimp

REPO = Path(__file__).resolve().parents[4]  # src/backend/golden/rescue → 저장소 루트
BACKEND = REPO / "src" / "backend"
PACKAGES = ("whymath_backend", "golden")
COLUMN_LABELS = ("골든", "옛앱")  # --entry 순서대로
CSV_HEADER = (
    "모듈", "파일 경로", "줄 수", "파트", "골든 등급", "옛앱 등급", "골든에서 닿음",
    "옛앱에서 닿음", "경로 테스트가 실행", "단위 테스트가 실행",
    "이 모듈을 import하는 모듈 수", "비고",
)  # fmt: skip
NO_RECORD = "(실행 기록 없음)"
ORPHAN_GRADES = ("섬", "잔해", "섬/잔해" + NO_RECORD)
# RS 공유 계약 「파트 표」 — whymath_backend 바로 아래 이름 → 파트
_PART_B = {"l1", "l2", "l3", "l4"}
_PART_C = {"api", "app", "composition", "config", "consent", "consent_grant", "security"}
_PART_C |= {"db", "schema"}
_PART_D = {"harness", "ops", "whs", "privacy", "l5", "l6", "lang"}


@dataclass
class Row:
    """대장 한 줄(모듈 하나)."""

    module: str
    path: Path
    lines: int
    in_graph: bool
    importers: int | None
    reached: list[bool] = field(default_factory=list)  # 진입점별
    journey: list[bool | None] = field(default_factory=list)  # 진입점별 · None = 기록 없음
    unit: bool | None = None
    grades: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def part_of(module: str) -> str:
    """모듈 이름 → 파트(A~D). 표에 없는 이름은 '미분류'."""
    head = module.split(".")
    if head[0] == "golden":
        return "A 뼈대"
    if len(head) < 2:
        return "C 접착제"  # whymath_backend/__init__.py
    if head[1] in _PART_B:
        return "B 지식 자산"
    if head[1] in _PART_C:
        return "C 접착제"
    return "D 측정·운영 도구" if head[1] in _PART_D else "미분류"


def ancestors(module: str) -> list[str]:
    """a.b.c → [a, a.b]. a.b.c를 import하면 이 패키지들의 __init__.py도 실행된다."""
    parts = module.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts))]


def reach_from(graph: grimp.ImportGraph, entry: str) -> set[str]:
    """진입점에서 정적으로 닿는 모듈. 보정 ①: 부모 __init__과 그것이 import하는 모듈까지 닫는다."""
    reached = {entry} | set(graph.find_upstream_modules(entry))
    while True:
        add = {a for m in reached for a in ancestors(m)} - reached
        for anc in list(add):
            add |= set(graph.find_upstream_modules(anc))
        add -= reached
        if not add:
            return reached
        reached |= add


def filesystem_modules(src_root: Path, packages: Sequence[str]) -> dict[str, Path]:
    """보정 ②: 파일 시스템 기준 모듈 전체(__init__.py 없는 폴더의 파일 포함) → 파일 경로."""
    found: dict[str, Path] = {}
    for pkg in packages:
        for path in sorted((src_root / pkg).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            parts = list(path.relative_to(src_root).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            found[".".join(parts)] = path
    return found


def executed_modules(coverage_json: Path, files: dict[str, Path], src_root: Path) -> set[str]:
    """coverage JSON에서 '실행된' 모듈을 고른다.

    실행 = 함수 안에서 실행된 줄이 1줄 이상. 함수가 없는 모듈만 맨 위 코드 실행 여부로 본다
    (import만 되고 호출되지 않은 모듈은 실행 아님).
    """
    data = json.loads(coverage_json.read_text(encoding="utf-8"))
    by_rel = {p.relative_to(src_root).as_posix(): m for m, p in files.items()}
    hit: set[str] = set()
    matched = 0
    for key, info in data.get("files", {}).items():
        if "functions" not in info:
            raise ValueError(
                f"{coverage_json}: 함수별 영역(functions)이 없다 — coverage 7.x로 다시"
            )
        parts = Path(key).as_posix().split("/")
        module = next(
            (by_rel[r] for i in range(len(parts)) if (r := "/".join(parts[i:])) in by_rel), None
        )
        if module is None:
            continue  # 분석 패키지 밖 파일(테스트·표준 라이브러리 등)
        matched += 1
        funcs = info["functions"]
        named = [f for name, f in funcs.items() if name]
        regions = named if named else [funcs.get("", {})]
        if any(r.get("executed_lines") for r in regions):
            hit.add(module)
    if matched == 0:
        raise ValueError(f"{coverage_json}: 분석 패키지 파일이 0건 — 경로가 맞지 않는다")
    return hit


def grade(reached: bool, journey: bool | None, unit: bool | None) -> str:
    """공유 계약 「등급 판정」. 기록이 없어 구분할 수 없으면 '(실행 기록 없음)'을 붙인다."""
    if journey:
        return "가동"
    if reached:
        return "대기" if journey is not None else "대기" + NO_RECORD
    if unit is None:
        return "섬/잔해" + NO_RECORD
    return "섬" if unit else "잔해"


def build_ledger(
    entries: Sequence[str],
    journeys: Sequence[Path | None],
    unit: Path | None,
    src_root: Path = BACKEND,
    packages: Sequence[str] = PACKAGES,
) -> list[Row]:
    """대장을 만든다. 진입점 모듈은 import하지 않는다(grimp 정적 분석)."""
    sys.path.insert(0, str(src_root))
    try:
        graph = grimp.build_graph(*packages, cache_dir=None)
    finally:
        sys.path.remove(str(src_root))
    for entry in entries:
        if entry not in graph.modules:
            raise ValueError(f"진입점 {entry}이 그래프에 없다")
    files = filesystem_modules(src_root, packages)
    reach = [reach_from(graph, e) for e in entries]
    ran = [executed_modules(j, files, src_root) if j else None for j in journeys]
    unit_ran = executed_modules(unit, files, src_root) if unit else None
    rows: list[Row] = []
    for mod, path in sorted(files.items()):
        in_graph = mod in graph.modules
        importers = len(graph.find_modules_that_directly_import(mod)) if in_graph else None
        row = Row(mod, path, path.read_bytes().count(b"\n"), in_graph, importers)
        row.unit = None if unit_ran is None else mod in unit_ran
        if not in_graph:
            row.notes.append("그래프 밖(__init__ 없는 폴더)")
        for label, r, j in zip(COLUMN_LABELS, reach, ran, strict=False):
            row.reached.append(mod in r)
            row.journey.append(None if j is None else mod in j)
            row.grades.append(grade(row.reached[-1], row.journey[-1], row.unit))
            if row.journey[-1] and not row.reached[-1]:
                row.notes.append(f"문자열로 불러옴({label})")
        rows.append(row)
    return rows


def _yes(flag: bool | None) -> str:
    return "기록 없음" if flag is None else ("예" if flag else "아니오")


def write_csv(rows: list[Row], out: Path, display_root: Path) -> None:
    """공유 계약 열 순서 그대로 · utf-8-sig(엑셀 한글)."""

    def col(values: list[str], i: int) -> str:
        return values[i] if i < len(values) else "해당 없음"

    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_HEADER)
        for r in rows:
            j = [lab for lab, x in zip(COLUMN_LABELS, r.journey, strict=False) if x]
            ran_none = all(x is None for x in r.journey)
            journey = f"예({'·'.join(j)})" if j else ("기록 없음" if ran_none else "아니오")
            reached = [_yes(x) for x in r.reached]
            w.writerow(
                [r.module, r.path.relative_to(display_root).as_posix(), r.lines, part_of(r.module),
                 col(r.grades, 0), col(r.grades, 1), col(reached, 0), col(reached, 1), journey,
                 _yes(r.unit), "" if r.importers is None else r.importers, " · ".join(r.notes)]
            )  # fmt: skip


def orphans(rows: list[Row], gate_package: str) -> set[str]:
    """게이트 패키지에서 어느 진입점으로도 섬·잔해인 모듈(고아)."""
    return {
        r.module
        for r in rows
        if (r.module == gate_package or r.module.startswith(gate_package + "."))
        and all(g in ORPHAN_GRADES for g in r.grades)
    }


def check_baseline(rows: list[Row], gate_package: str, baseline: Path, update: bool) -> int:
    """고아 게이트. 기준선에 없는 새 고아가 있으면 1. --update면 기준선을 다시 쓰고 0."""
    if not any(r.module == gate_package or r.module.startswith(gate_package + ".") for r in rows):
        print(f"게이트 실패: {gate_package} 모듈 0개 — 공허 통과 금지")
        return 1
    current = orphans(rows, gate_package)
    if update:
        body = "".join(f"{m}\n" for m in sorted(current))
        head = f"# 고아 기준선({gate_package}) — ledger --update가 쓴다\n"
        baseline.write_text(head + body, encoding="utf-8")
        print(f"기준선 갱신: {baseline} ({len(current)}개)")
        return 0
    if not baseline.exists():
        print(f"게이트 실패: 기준선 {baseline} 없음 — 처음이면 --update로 만든다")
        return 2
    lines = baseline.read_text(encoding="utf-8").splitlines()
    known = {ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")}
    new = sorted(current - known)
    print(f"고아 게이트({gate_package}): 현재 {len(current)} · 기준선 {len(known)}")
    for m in new:
        print(f"  새 고아: {m}")
    return 1 if new else 0


def _short(g: str) -> str:
    """등급 → 한 글자(가·대·섬·잔 · 섬/잔해 미구분은 미)."""
    return "미" if g.startswith("섬/잔해") else g[0]


def summarize(rows: list[Row], entries: Sequence[str]) -> list[str]:
    """화면 요약(50줄 이하): 등급별 → 패키지별 큰 순서 30 → 전부 잔해인 패키지 한 줄."""
    out = [f"모듈 {len(rows)}개 · 그래프 밖 {sum(not r.in_graph for r in rows)}개"]
    for i, (label, entry) in enumerate(zip(COLUMN_LABELS, entries, strict=False)):
        cnt = Counter(r.grades[i] for r in rows)
        out.append(f"[{label} {entry}] " + " · ".join(f"{g} {n}" for g, n in sorted(cnt.items())))
    pkg_rows: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        pkg_rows[".".join(r.module.split(".")[:2])].append(r)
    out.append("패키지(줄 수 큰 순서 30) · 모듈 · 줄 · 진입점마다 가/대/섬/잔/미(섬·잔해 미구분)")
    for pkg, rs in sorted(pkg_rows.items(), key=lambda kv: -sum(r.lines for r in kv[1]))[:30]:
        dist = []
        for i in range(len(entries)):
            c = Counter(_short(r.grades[i]) for r in rs)
            dist.append("/".join(str(c[k]) for k in "가대섬잔미"))
        out.append(f"  {pkg} · {len(rs)} · {sum(r.lines for r in rs):,} · {' | '.join(dist)}")
    # 전부 잔해: 패키지(하위 모듈이 있는 이름) 안 모든 모듈이 모든 진입점에서 잔해(또는 미구분)
    members: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        for a in [*ancestors(r.module), r.module]:
            members[a].append(r)
    parents = {a for r in rows for a in ancestors(r.module)}
    debris = {p for p in parents if all(_short(g) in "잔미" for x in members[p] for g in x.grades)}
    top = sorted(p for p in debris if not any(a in debris for a in ancestors(p)))
    vague = any(_short(g) == "미" for r in rows for g in r.grades)
    tag = "(단위 기록 없음 → 섬·잔해 미구분 포함)" if vague else ""
    out.append(f"전부 잔해인 패키지{tag} {len(top)}개: " + (", ".join(top) or "없음"))
    return out


def main(
    argv: Sequence[str] | None = None,
    src_root: Path = BACKEND,
    packages: Sequence[str] = PACKAGES,
    display_root: Path = REPO,
) -> int:
    """CLI. 종료 코드 0 = 정상 · 1 = 고아 게이트 실패 · 2 = 입력 오류."""
    ap = argparse.ArgumentParser(prog="python -m golden.rescue.ledger")
    ap.add_argument("--entry", action="append", required=True)
    ap.add_argument("--journey-golden", type=Path)
    ap.add_argument("--journey-legacy", type=Path)
    ap.add_argument("--unit", type=Path)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--gate-package", default="golden")
    args = ap.parse_args(argv)
    if not 1 <= len(args.entry) <= len(COLUMN_LABELS):
        ap.error("--entry는 1~2개(첫째 = 골든 열 · 둘째 = 옛앱 열)")
    journeys = [args.journey_golden, args.journey_legacy][: len(args.entry)]
    try:
        rows = build_ledger(args.entry, journeys, args.unit, src_root, packages)
    except ValueError as exc:
        print(f"입력 오류: {exc}")
        return 2
    write_csv(rows, args.csv, display_root)
    print("\n".join(summarize(rows, args.entry)))
    print(f"CSV: {args.csv}")
    if args.baseline:
        return check_baseline(rows, args.gate_package, args.baseline, args.update)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
