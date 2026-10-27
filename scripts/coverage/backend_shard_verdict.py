#!/usr/bin/env python3
"""backend 집계 잡(`backend — lint·type·test`)의 판정기 (OPS-83).

왜 필요한가
-----------
backend 잡을 정적 검사 1잡 + pytest 샤드 N잡으로 쪼갰다(OPS-83). 룰셋·머지 큐의 required
status check 이름(`backend — lint·type·test`)은 그대로 두기 위해, **그 이름을 가진 집계 잡**이
나머지를 `needs:`로 기다려 결과를 판정한다. 이때 두 가지가 조용히 새면 안 된다:

1. **선행 잡의 실패·취소·건너뜀이 삼켜지는 것.** GitHub는 `needs`가 실패하면 뒤 잡을 *건너뛰고*,
   건너뛴(skipped) required check를 **충족**으로 센다. 그래서 집계 잡은 `if: always()`로 반드시
   돌고, 선행 잡 결과가 하나라도 `success`가 아니면 이 판정기가 exit 1을 낸다. `skipped`도
   실패다 — 집계 잡의 `if`는 샤드 잡과 같은 실행 조건을 쓰므로, 집계 잡이 돌았다는 것은 샤드가
   *돌았어야 했다*는 뜻이다. 그런데 건너뛰었다면 검증이 일어나지 않은 것이다
   (CLAUDE.md 「안 돌린 검사와 통과한 검사를 같은 화면에서 읽지 않는다」 — PR #1075 선례).
2. **샤드 배정이 불완전한 것.** 샤드 잡이 전부 초록이어도, 어떤 파일이 어느 샤드에도 배정되지
   않았다면 "일부만 돌았다"가 "전부 통과"로 보인다. `reports`가 배정 보고서
   (`backend_shard_plugin.py`)를 모아 우주·몫·합을 대조한다.

사용
----
  needs    환경변수 NEEDS_JSON(= `${{ toJSON(needs) }}`)의 모든 선행 잡이 success인가
  reports  DIR 아래 report-*.json이 하나의 완전한 분할을 이루는가

exit code: 0 통과 · 1 위반(실패·취소·건너뜀·불완전 분할) · 2 측정 실패(입력 없음·파싱 불가·
형식 판 불일치). 2를 1과 나누는 이유는 처방이 다르기 때문이다 — 1은 코드·테스트를 고치고, 2는
배선(artifact 업로드·다운로드·환경변수)을 고친다. CI에서는 둘 다 잡을 red로 만든다.

표준 라이브러리만 쓴다(집계 잡은 pytest를 설치하기 전에 needs 판정부터 한다).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_MEASURE_FAILED = 2

#: `backend_shard_plugin.REPORT_SCHEMA`와 같아야 한다(형식이 다르면 비교 자체가 무의미하다).
EXPECTED_REPORT_SCHEMA = 1

REPORT_GLOB = "report-*.json"


class MeasureError(RuntimeError):
    """판정 입력을 읽지 못했다 — 위반이 아니라 측정 실패(exit 2)."""


# ── needs ────────────────────────────────────────────────────────────────


def needs_violations(needs: Any) -> list[str]:
    """`toJSON(needs)` 값에서 success가 아닌 선행 잡을 사유와 함께 돌려준다.

    빈 매핑은 측정 실패다 — 판정할 선행 잡이 하나도 없으면 "위반 0"이 아니라 배선이 깨진 것이다.
    """
    if not isinstance(needs, Mapping):
        raise MeasureError(f"needs가 매핑이 아니다: {type(needs).__name__}")
    if not needs:
        raise MeasureError("needs가 비었다 — 판정할 선행 잡이 없다(스캔 0건은 통과가 아니다)")
    violations: list[str] = []
    for job, body in sorted(needs.items()):
        result = body.get("result") if isinstance(body, Mapping) else None
        if result != "success":
            violations.append(f"{job}: result={result!r} (success만 통과 — skipped·cancelled 포함)")
    return violations


def cmd_needs(args: argparse.Namespace) -> int:
    raw = os.environ.get(args.env)
    if raw is None:
        raise MeasureError(f"환경변수 {args.env}가 없다 — ci.yml 스텝의 env 배선을 확인하라")
    try:
        needs = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MeasureError(f"{type(exc).__name__}: {args.env} JSON 파싱 실패") from exc
    violations = needs_violations(needs)
    for job, body in sorted(needs.items()):
        result = body.get("result") if isinstance(body, Mapping) else None
        mark = "✔" if result == "success" else "✘"
        print(f"{mark} {job}: {result}")
    if violations:
        print("\n선행 잡 중 success가 아닌 것이 있다 — 이 잡은 통과할 수 없다:")
        for line in violations:
            print(f"  · {line}")
        return EXIT_VIOLATION
    print(f"\n선행 잡 {len(needs)}건 전부 success")
    return EXIT_OK


# ── reports ──────────────────────────────────────────────────────────────


def _digest(paths: Sequence[str]) -> str:
    # backend_shard_plugin.files_digest와 같은 정의(정렬 후 개행 결합 → sha256).
    return hashlib.sha256("\n".join(sorted(set(paths))).encode("utf-8")).hexdigest()


def load_reports(directory: Path) -> list[dict[str, Any]]:
    if not directory.is_dir():
        raise MeasureError(f"보고서 디렉터리가 없다: {directory} — artifact 다운로드를 확인하라")
    paths = sorted(directory.glob(REPORT_GLOB))
    if not paths:
        raise MeasureError(f"{directory}에 {REPORT_GLOB}가 하나도 없다 — 스캔 0건은 통과가 아니다")
    reports: list[dict[str, Any]] = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MeasureError(f"{type(exc).__name__}: {path} 읽기 실패") from exc
        if not isinstance(data, dict):
            raise MeasureError(f"{path}: 보고서가 객체가 아니다")
        if data.get("schema") != EXPECTED_REPORT_SCHEMA:
            raise MeasureError(
                f"{path}: 형식 판 {data.get('schema')!r} ≠ 기대 {EXPECTED_REPORT_SCHEMA}"
            )
        data["_source"] = path.name
        reports.append(data)
    return reports


def partition_violations(reports: Sequence[Mapping[str, Any]]) -> list[str]:
    """보고서들이 하나의 완전한 분할(겹침 0·누락 0·합 일치)을 이루는지 검사한다."""
    if not reports:
        return ["보고서 0건 — 분할을 판정할 수 없다"]
    violations: list[str] = []

    def field(name: str) -> set[Any]:
        return {r.get(name) for r in reports}

    totals = field("total_shards")
    if len(totals) != 1:
        violations.append(f"샤드마다 N이 다르다: {sorted(map(str, totals))}")
    total_shards = next(iter(totals)) if len(totals) == 1 else None

    shards = [r.get("shard") for r in reports]
    if len(set(shards)) != len(shards):
        violations.append(f"같은 샤드 번호가 두 번 이상 보고됐다: {shards}")
    if isinstance(total_shards, int):
        expected = set(range(1, total_shards + 1))
        missing = sorted(expected - set(shards))
        extra = sorted(str(s) for s in set(shards) - expected)
        if missing:
            violations.append(f"보고서가 없는 샤드: {missing} (N={total_shards})")
        if extra:
            violations.append(f"1..N 밖의 샤드 번호: {extra}")

    for name in ("total_items", "total_files", "files_digest"):
        values = field(name)
        if len(values) != 1:
            violations.append(f"샤드마다 수집 우주가 다르다 — {name}: {sorted(map(str, values))}")

    seen: dict[str, Any] = {}
    for r in reports:
        files = r.get("selected_files")
        if not isinstance(files, list):
            violations.append(f"{r.get('_source')}: selected_files가 목록이 아니다")
            continue
        if not files or not r.get("selected_items"):
            violations.append(
                f"샤드 {r.get('shard')}: 배정 0건 — 빈 샤드는 아무것도 검증하지 않는다"
            )
        for f in files:
            if f in seen:
                violations.append(
                    f"파일이 두 샤드에 배정됐다: {f} (샤드 {seen[f]}·{r.get('shard')})"
                )
            seen[f] = r.get("shard")

    union = list(seen)
    universe = field("files_digest")
    if len(universe) == 1 and _digest(union) != next(iter(universe)):
        violations.append(
            f"몫의 합집합({len(union)}파일)이 수집 우주와 다르다 — 어느 샤드에도 배정되지 않은 "
            "파일이 있다"
        )
    item_totals = field("total_items")
    if len(item_totals) == 1:
        summed = sum(int(r.get("selected_items") or 0) for r in reports)
        expected_items = next(iter(item_totals))
        if summed != expected_items:
            violations.append(f"몫의 항목 합 {summed} ≠ 수집 우주 {expected_items}")
    return violations


def cmd_reports(args: argparse.Namespace) -> int:
    reports = load_reports(Path(args.directory))
    for r in sorted(reports, key=lambda r: str(r.get("shard"))):
        mine = len(r.get("selected_files") or [])
        print(
            f"샤드 {r.get('shard')}/{r.get('total_shards')}: 파일 {mine}"
            f" · 항목 {r.get('selected_items')} (우주 파일 {r.get('total_files')}"
            f" · 항목 {r.get('total_items')})"
        )
    violations = partition_violations(reports)
    if violations:
        print("\n샤드 분할이 완전하지 않다 — 일부만 돌았을 수 있다:")
        for line in violations:
            print(f"  · {line}")
        return EXIT_VIOLATION
    print(f"\n분할 완전: 샤드 {len(reports)}개 · 겹침 0 · 누락 0 · 항목 합 = 수집 우주")
    return EXIT_OK


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_needs = sub.add_parser("needs", help="선행 잡이 전부 success인가")
    p_needs.add_argument("--env", default="NEEDS_JSON", help="toJSON(needs)를 담은 환경변수 이름")
    p_needs.set_defaults(func=cmd_needs)
    p_reports = sub.add_parser("reports", help="배정 보고서가 완전한 분할인가")
    p_reports.add_argument("directory", help="report-*.json이 있는 디렉터리")
    p_reports.set_defaults(func=cmd_reports)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(argv)
    try:
        return int(args.func(args))
    except MeasureError as exc:
        print(f"측정 실패: {exc}", file=sys.stderr)
        return EXIT_MEASURE_FAILED


if __name__ == "__main__":
    sys.exit(main())
