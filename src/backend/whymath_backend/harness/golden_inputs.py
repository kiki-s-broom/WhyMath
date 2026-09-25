"""골든 경로 입력 준비 CLI — 승격 제안 목록·앵커 매핑을 검수 기록에서 **파생**한다 (MP-03).

왜 필요한가
-----------
골든 경로의 두 판정기는 둘 다 사람이 손으로 만들 입력을 전제로 서 있었다:

  - `harness/golden_promotion_gate`는 `--proposal`(승격 제안 slug 목록)을 요구한다.
  - `harness/golden_benchmark`는 `--anchor-map`(cu_slug → 앵커 JSONL)을 요구한다.

그런데 둘 다 **만드는 도구가 저장소에 없었다**(2026-09-25 MP-03 착수 실측 — `anchor-map`은
그 모듈·테스트·계약 문서에만 나오고 생산자가 0건). 그 공백을 운영자가 런북 안의 인라인
스니펫으로 메우면, 검증되지 않은 코드가 판정 입력을 만든다 — 판정기는 테스트로 동결돼 있는데
그 입력은 아무도 재지 않은 셈이다. 이 모듈은 두 입력을 **테스트된 경로**로 만든다.

두 하위 명령
-----------
  proposal   — 검수 타이머 이벤트 → 사람 종결 판정(finished + verdict)이 있는 cu_slug 목록.
               판정 해석은 `golden_promotion_gate._human_verdicts`를 **그대로 재사용**한다(같은
               파일에서 게이트가 보는 판정 집합과 제안 집합이 어긋나지 않게 — 단일 권위).
  anchor-map — 검수 큐 JSONL(`canary_slice` 산출 등)의 후보 성취기준 코드
               (`candidate_payload.achievement_standard_codes`) → `l1/standards/anchor_registry`의
               코드 역인덱스로 cu_slug → anchor_id.

비날조 — 판정도 앵커도 만들지 않는다
-----------------------------------
  - `proposal`은 판정을 **열거**할 뿐 만들지 않는다. 받는 인자는 어떤 판정 값을 포함할지의
    필터(`--verdict`)뿐이다. started·aborted는 판정이 아니므로 세지 않는다(게이트와 같은 규칙).
  - `anchor-map`은 앵커를 **추론하지 않는다**. 후보가 스스로 적은 성취기준 코드가 레지스트리에서
    **정확히 1개** 앵커로 역인덱스되고 그 앵커가 골든 어휘(A1~A6) 안일 때만 행을 쓴다. payload
    없음·코드 없음·레지스트리 밖 코드·복수 앵커·골든 범위 밖 앵커는 미매핑으로 **사유와 함께
    전건** 보고한다(조용한 제외 금지 — 미측정 ≠ 정상).
    회차 스펙 코드로 덮어쓰지 않는 이유: 모델이 스펙과 다른 코드를 적은 후보(2026-09-25 MP-02
    2회차 실측 — 예시 코드 복사 4건)를 스펙 앵커로 붙이면 그 결함이 골든에서 사라진다.

측정 도구 실패 경로 (2026-08-22 규칙)
------------------------------------
exit 0 = 1건 이상 산출 · 1 = 산출 0건(측정 실패 — "0건 통과"가 아니다) ·
2 = 입력 오류(파일 부재·**파싱 실패 1건 이상**·레지스트리 적재 실패). 입력이 손상되면 산출
파일을 **쓰지 않는다** — 잘린 반려 행 하나가 판정을 뒤집을 수 있다(게이트 docstring 선례).
요약 JSON은 stdout으로 항상 낸다(실패해도 원인이 남는다).

사용법(운영자):
    python -m whymath_backend.harness.golden_inputs proposal \\
        --events <review_timer.jsonl> [--events ...] --out <proposal.txt> \\
        [--verdict approved --verdict rejected ...]
    python -m whymath_backend.harness.golden_inputs anchor-map \\
        --queue <canary_review_queue.jsonl> --out <anchor_map.jsonl> [--registry <anchors.yaml>]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from whymath_backend.harness.golden_benchmark import ANCHOR_IDS
from whymath_backend.harness.golden_promotion_gate import _human_verdicts
from whymath_backend.l1.standards.anchor_registry import (
    AnchorRegistry,
    AnchorRegistryError,
    load_anchor_registry,
)

__all__ = [
    "VERDICT_CHOICES",
    "AnchorMapResult",
    "UNMAPPED_REASONS",
    "build_anchor_map",
    "main",
    "select_proposal",
]

# 판정 어휘 — `schema/review_timer.ReviewVerdict`와 같은 3값(EOS-62). 필터 인자의 폐쇄 집합.
VERDICT_CHOICES = ("approved", "approved_with_edit", "rejected")

# 미매핑 사유 5종 — 조치가 달라 뭉뚱그리지 않는다(payload 부재는 큐 형식 문제, 코드 부재는
# 생성기 문제, 레지스트리 밖은 앵커 범위 문제, 복수 앵커는 레지스트리 설계 문제, 골든 범위 밖은
# 레지스트리(A1~A8)와 골든 어휘(A1~A6)의 차이 — 쓰면 golden_benchmark가 파싱 실패로 전건을 막는다).
UNMAPPED_REASONS = (
    "no_payload",
    "no_standard_codes",
    "code_not_in_registry",
    "multiple_anchors",
    "anchor_out_of_golden_scope",
)


def select_proposal(verdicts: dict[str, str], include: Iterable[str]) -> list[str]:
    """{slug: 최신 종결 판정} → 포함할 판정 값에 해당하는 slug 목록(첫 등장 순서 보존·순수)."""
    wanted = set(include)
    return [slug for slug, verdict in verdicts.items() if verdict in wanted]


@dataclass(frozen=True, slots=True)
class AnchorMapResult:
    """앵커 매핑 파생 결과 — 쓸 행과 못 쓴 행(사유별)을 함께 나른다."""

    rows: list[dict[str, Any]]
    """매핑된 행 — `golden_benchmark.parse_anchor_rows`가 먹는 `cu_slug`·`anchor_id` + 근거 코드."""

    unmapped: list[dict[str, Any]]
    """미매핑 전건 — slug·사유·후보가 적은 코드(절단 없음)."""

    rows_total: int
    """큐 행 수(빈 줄 제외)."""

    duplicate_rows: int
    """같은 slug의 2번째 이후 행 수 — 한 번만 세고 버린다(review_session과 같은 규칙)."""

    missing_slug_rows: int
    """slug가 없는 행 수 — 정체성이 없어 매핑 대상이 아니다."""

    by_anchor: dict[str, int] = field(default_factory=dict)
    """앵커별 매핑 건수."""


def _codes_of(payload: Any) -> list[str] | None:
    """candidate_payload에서 성취기준 코드 목록을 꺼낸다 — 형식이 아니면 None."""
    if not isinstance(payload, dict):
        return None
    raw = payload.get("achievement_standard_codes")
    if not isinstance(raw, list):
        return []
    return [str(code) for code in raw if isinstance(code, str) and code]


def build_anchor_map(
    queue_rows: Sequence[dict[str, Any]], registry: AnchorRegistry
) -> AnchorMapResult:
    """검수 큐 행 → 앵커 매핑(순수 — 파일 I/O 0). 정확히 1개 앵커일 때만 행을 만든다."""
    rows: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicate_rows = 0
    missing_slug_rows = 0
    for row in queue_rows:
        slug = row.get("slug")
        if not (isinstance(slug, str) and slug):
            missing_slug_rows += 1
            continue
        if slug in seen:
            duplicate_rows += 1
            continue
        seen.add(slug)
        codes = _codes_of(row.get("candidate_payload"))
        if codes is None:
            unmapped.append({"slug": slug, "reason": "no_payload", "codes": []})
            continue
        if not codes:
            unmapped.append({"slug": slug, "reason": "no_standard_codes", "codes": []})
            continue
        anchor_ids = sorted(
            {anchor.id for code in codes if (anchor := registry.anchor_for_code(code)) is not None}
        )
        if not anchor_ids:
            unmapped.append({"slug": slug, "reason": "code_not_in_registry", "codes": codes})
            continue
        if len(anchor_ids) > 1:
            unmapped.append(
                {"slug": slug, "reason": "multiple_anchors", "codes": codes, "anchors": anchor_ids}
            )
            continue
        if anchor_ids[0] not in ANCHOR_IDS:
            # 레지스트리에는 있으나 골든 어휘(`golden_benchmark.ANCHOR_IDS`) 밖 — 행으로 쓰면
            # 소비자가 "어휘 밖 앵커"를 파싱 실패로 세어 exit 1이 된다. 여기서 사유로 분리한다.
            unmapped.append(
                {
                    "slug": slug,
                    "reason": "anchor_out_of_golden_scope",
                    "codes": codes,
                    "anchors": anchor_ids,
                }
            )
            continue
        rows.append({"cu_slug": slug, "anchor_id": anchor_ids[0], "standard_codes": codes})
    return AnchorMapResult(
        rows=rows,
        unmapped=unmapped,
        rows_total=len(queue_rows),
        duplicate_rows=duplicate_rows,
        missing_slug_rows=missing_slug_rows,
        by_anchor=dict(Counter(row["anchor_id"] for row in rows)),
    )


def _load_jsonl_objects(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """JSONL → 객체 행 목록 + 실패 사유(파일명·줄 번호·예외 타입명 — 값은 남기지 않는다)."""
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except Exception as exc:  # noqa: BLE001 — 사유 수집(타입명 보존)이 목적
                errors.append(f"{path.name} line {line_no}: {type(exc).__name__}")
                continue
            if not isinstance(parsed, dict):
                errors.append(f"{path.name} line {line_no}: NotAnObject")
                continue
            rows.append(parsed)
    return rows, errors


def _emit(summary: dict[str, Any]) -> None:
    """요약 JSON을 stdout에 낸다 — 성공·실패 모두(원인이 남아야 한다)."""
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")


def _run_proposal(args: argparse.Namespace) -> int:
    missing = [str(path) for path in args.events if not path.is_file()]
    if missing:
        _emit(
            {"command": "proposal", "written": False, "error": "input_missing", "missing": missing}
        )
        return 2
    verdicts, load_errors = _human_verdicts(args.events)
    include = args.verdict or list(VERDICT_CHOICES)
    selected = select_proposal(verdicts, include)
    summary: dict[str, Any] = {
        "command": "proposal",
        "events": [str(path) for path in args.events],
        "judged_slugs": len(verdicts),
        "by_verdict": dict(Counter(verdicts.values())),
        "include": list(include),
        "selected": len(selected),
        "out": str(args.out),
        "written": False,
        "load_errors": load_errors,
    }
    if load_errors:
        # 손상된 이벤트 위의 제안은 권위가 없다 — 쓰지 않는다(게이트 exit 2와 같은 판단).
        summary["error"] = "input_damaged"
        _emit(summary)
        return 2
    if not selected:
        summary["error"] = "no_selection"
        _emit(summary)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(f"{slug}\n" for slug in selected), encoding="utf-8")
    summary["written"] = True
    _emit(summary)
    return 0


def _run_anchor_map(args: argparse.Namespace) -> int:
    if not args.queue.is_file():
        _emit(
            {
                "command": "anchor-map",
                "written": False,
                "error": "input_missing",
                "missing": [str(args.queue)],
            }
        )
        return 2
    try:
        registry = load_anchor_registry(args.registry)
    except AnchorRegistryError as exc:  # 로더가 OSError·YAML 오류를 전부 이 타입으로 감싼다
        _emit(
            {
                "command": "anchor-map",
                "written": False,
                "error": "registry_load_failed",
                "error_type": type(exc).__name__,
            }
        )
        return 2
    queue_rows, load_errors = _load_jsonl_objects(args.queue)
    result = build_anchor_map(queue_rows, registry)
    summary: dict[str, Any] = {
        "command": "anchor-map",
        "queue": str(args.queue),
        "rows_total": result.rows_total,
        "duplicate_rows": result.duplicate_rows,
        "missing_slug_rows": result.missing_slug_rows,
        "distinct_slugs": len(result.rows) + len(result.unmapped),
        "mapped": len(result.rows),
        "by_anchor": result.by_anchor,
        "unmapped_count": len(result.unmapped),
        "unmapped_counts": dict(Counter(item["reason"] for item in result.unmapped)),
        # 미매핑은 전건을 싣는다(절단 없음) — 여기서 자르면 그 행이 조용히 사라진다.
        "unmapped": result.unmapped,
        "out": str(args.out),
        "written": False,
        "load_errors": load_errors,
    }
    if load_errors:
        summary["error"] = "input_damaged"
        _emit(summary)
        return 2
    if not result.rows:
        summary["error"] = "no_mapped_rows"
        _emit(summary)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in result.rows), encoding="utf-8"
    )
    summary["written"] = True
    _emit(summary)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 진입점 — exit 0=산출 1건+, 1=산출 0건(측정 실패), 2=입력 오류·인자 오류."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.golden_inputs",
        description=(
            "골든 경로 입력 준비 — 검수 기록에서 승격 제안 목록(proposal)·앵커 매핑(anchor-map)을 "
            "파생한다. 판정도 앵커도 만들지 않는다(열거·역인덱스만)."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    proposal = sub.add_parser("proposal", help="검수 이벤트 → 사람 종결 판정 slug 목록(텍스트).")
    proposal.add_argument(
        "--events",
        type=Path,
        action="append",
        required=True,
        help="검수 타이머 이벤트 JSONL(복수).",
    )
    proposal.add_argument("--out", type=Path, required=True, help="제안 목록 출력(한 줄 1 slug).")
    proposal.add_argument(
        "--verdict",
        action="append",
        choices=VERDICT_CHOICES,
        default=None,
        help="포함할 판정 값(복수 · 생략 시 3값 전부 — 사람이 판정한 전건을 제안).",
    )

    anchor = sub.add_parser("anchor-map", help="검수 큐 → cu_slug→anchor_id JSONL.")
    anchor.add_argument(
        "--queue", type=Path, required=True, help="검수 큐 JSONL(candidate_payload 포함)."
    )
    anchor.add_argument("--out", type=Path, required=True, help="앵커 매핑 JSONL 출력.")
    anchor.add_argument(
        "--registry", type=Path, default=None, help="앵커 레지스트리 YAML(생략 시 저장소 정본)."
    )

    args = parser.parse_args(argv)
    if args.command == "proposal":
        return _run_proposal(args)
    return _run_anchor_map(args)


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
