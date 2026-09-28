"""QA 엔진 문항별 판정 어댑터 — 코퍼스/검수 큐 JSONL → predictions JSONL (EOS-137 ①).

왜 필요한가
-----------
`ops/qa_confusion_matrix`는 골든 정답지 대비 QA 엔진의 혼동행렬(FN율)을 재지만, 입력인
`--predictions`(문항마다 QA 엔진이 내린 pass/fail)를 **만드는 도구가 저장소에 없었다**
(2026-09-25 MP-03 착수 실측 — `qa_verdict` 키는 그 모듈·테스트·계약 문서에만 나왔다). 그래서
골든 v1이 동결돼도 QA 엔진 FN율은 "측정 불가"였다. 이 모듈이 그 생산자다.

판정은 여기서 하지 않는다 — `harness/qa_pipeline.judge_item`(QA 엔진의 문항 단위 좌석)을 그대로
부른다(재구현 금지). 이 모듈의 일은 입력 해석·중복 처리·판정 불가 분리·출력 형식뿐이다.

입력 — 경로 지정 (glob에 묶이지 않는다)
--------------------------------------
`--input`(반복 가능)은 JSONL 파일 경로다. `problem_bank_*` 디렉터리 관례에 묶이지 않으므로
축적 회차 코퍼스(`mp02-out\\problems.jsonl` 등)·검수 큐를 그대로 받는다. 행 2종을 같은 규칙으로
읽는다 — 규칙의 단일 원천은 `review_session._resolve_payload`(검수자가 본 본문 = 판정 대상):

  - 코퍼스 행 — 행 자신이 문항 본문이다.
  - 검수 큐 행(`canary_slice`·`needs_review_worklist` 산출) — 본문은 `candidate_payload`다.
    본문이 없는 행(생성 실패 후보 등)은 **판정 불가**(`payload_absent`)로 분리한다.

같은 slug가 여러 번 나오면 **첫 등장이 판정 대상**이다(입력 순서 — `review_session`이 큐의 중복
행을 첫 등장만 검수하는 규칙과 같다. 그래야 골든 라벨이 말하는 본문과 판정한 본문이 같다). 뒤
등장 본문이 첫 본문과 다르면 그 slug를 `duplicate_divergent`로 요약에 적는다(조용한 선택 금지).

출력 — predictions 형식 (`golden_benchmark_contract.md` §7)
----------------------------------------------------------
  - `--out` predictions JSONL — pass/fail만. 행 = `{"cu_slug", "qa_verdict", "predictor",
    "reason", "checks"}`. `predictor`는 판정기 식별자(`qa_pipeline.ITEM_SEAT_PREDICTOR` — fuzz를
    켜면 `+fuzz`)로, 혼동행렬 리포트·평가 원장이 "어느 판정기의 FN율인가"를 가리키는 값이다(④).
  - `--undetermined` JSONL — 판정 불가 문항과 사유. **predictions에 넣지 않는다**: pass로 채우면
    FN이 위장되고, fail로 채우면 검출률이 부풀려진다. 혼동행렬은 이 문항을 `미평가`로 센다.

`--golden`을 주면 그 정답지의 slug만 판정하고, 입력 어디에도 없는 골든 slug는 판정 불가
(`not_in_inputs`)로 분리한다 — 골든 적재율의 분모가 그대로 보인다.

측정 도구 실패 경로 (2026-08-22 규칙)
------------------------------------
exit 0 = predictions 1건 이상 · 1 = predictions 0건(측정 실패 — "0건 통과"가 아니다) ·
2 = 입력 오류(파일 부재·**파싱 실패 1건 이상**·골든 로드 실패). 입력이 손상되면 산출 파일을
**쓰지 않는다** — 유실된 행이 하필 골든 문항이면 미평가가 조용히 늘어난다(`golden_inputs` 선례).
요약 JSON은 stdout으로 항상 낸다(실패해도 원인이 남는다). 외부 프로세스·네트워크 없음.

사용법(운영자):
    python -m whymath_backend.harness.qa_item_verdict \\
        --input <canary_review_queue.jsonl> [--input <problems.jsonl> ...] \\
        --golden <golden.json> --out <qa_verdicts.jsonl> --undetermined <qa_undetermined.jsonl>
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from whymath_backend.harness.golden_benchmark import load_golden_set
from whymath_backend.harness.qa_pipeline import (
    ItemVerdict,
    item_seat_predictor,
    judge_item,
)
from whymath_backend.harness.review_session import _resolve_payload

__all__ = [
    "AdapterResult",
    "UndeterminedItem",
    "build_predictions",
    "main",
]

_EXIT_OK = 0
_EXIT_MEASUREMENT_FAIL = 1
_EXIT_INPUT_ERROR = 2


@dataclass(frozen=True, slots=True)
class UndeterminedItem:
    """판정 불가 문항 1건 — 사유 범주(집계 키)와 사유 원문."""

    cu_slug: str
    category: str
    reason: str
    checks: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


@dataclass(slots=True)
class AdapterResult:
    """어댑터 1회 결과 — 판정(pass/fail) · 판정 불가 · 입력 회계."""

    predictor: str
    verdicts: list[ItemVerdict] = field(default_factory=list)
    undetermined: list[UndeterminedItem] = field(default_factory=list)
    rows_total: int = 0
    missing_slug_rows: int = 0
    duplicate_rows: int = 0
    duplicate_divergent: list[str] = field(default_factory=list)
    outside_golden: int = 0

    def summary(self) -> dict[str, Any]:
        by_verdict = Counter(v.verdict for v in self.verdicts)
        return {
            "predictor": self.predictor,
            "rows_total": self.rows_total,
            "missing_slug_rows": self.missing_slug_rows,
            "duplicate_rows": self.duplicate_rows,
            "duplicate_divergent": sorted(self.duplicate_divergent),
            "outside_golden": self.outside_golden,
            "predictions": by_verdict.get("pass", 0) + by_verdict.get("fail", 0),
            "by_verdict": {
                "pass": by_verdict.get("pass", 0),
                "fail": by_verdict.get("fail", 0),
                "undetermined": len(self.undetermined),
            },
            "undetermined_by_category": dict(
                sorted(Counter(u.category for u in self.undetermined).items())
            ),
        }


def _slug_of(row: Mapping[str, Any]) -> str | None:
    slug = row.get("slug") or row.get("cu_slug")
    return slug if isinstance(slug, str) and slug else None


def _payload_key(payload: Mapping[str, Any] | None) -> str | None:
    """본문 비교 키 — 키 순서 무관 정규 직렬화(뒤 등장 본문이 첫 본문과 같은지 가르는 데만 쓴다)."""
    if payload is None:
        return None
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def _checks_json(verdict: ItemVerdict) -> dict[str, dict[str, Any]]:
    return {check.name: check.to_json() for check in verdict.checks}


def build_predictions(
    rows: Iterable[Mapping[str, Any]],
    *,
    golden_slugs: Sequence[str] | None = None,
    use_fuzz: bool = False,
) -> AdapterResult:
    """입력 행 → 문항별 판정(순수 — 파일 I/O 없음). 판정은 `qa_pipeline.judge_item`이 한다.

    `golden_slugs`가 주어지면 그 slug만 판정하고, 입력에 없는 골든 slug는 `not_in_inputs`로
    판정 불가에 넣는다(골든 순서 보존).
    """
    result = AdapterResult(predictor=item_seat_predictor(use_fuzz=use_fuzz))
    first: dict[str, Mapping[str, Any]] = {}
    first_payload_key: dict[str, str | None] = {}
    order: list[str] = []
    divergent: set[str] = set()
    wanted = set(golden_slugs) if golden_slugs is not None else None

    for row in rows:
        result.rows_total += 1
        slug = _slug_of(row)
        if slug is None:
            # CU 자체가 없는 행(생성 실패 후보 등) — 판정 대상 밖이며 건수만 남긴다.
            result.missing_slug_rows += 1
            continue
        if wanted is not None and slug not in wanted:
            result.outside_golden += 1
            continue
        payload, _absent = _resolve_payload(row)
        payload_key = _payload_key(payload)
        if slug in first:
            result.duplicate_rows += 1
            if payload_key != first_payload_key[slug]:
                divergent.add(slug)
            continue
        first[slug] = row
        first_payload_key[slug] = payload_key
        order.append(slug)
    result.duplicate_divergent = sorted(divergent)

    for slug in order:
        payload, absent_reason = _resolve_payload(first[slug])
        if payload is None:
            result.undetermined.append(
                UndeterminedItem(
                    cu_slug=slug,
                    category="payload_absent",
                    reason=absent_reason or "문항 본문 없음",
                )
            )
            continue
        verdict = judge_item(payload, cu_slug=slug, use_fuzz=use_fuzz)
        if verdict.verdict == "undetermined":
            names = [c.name for c in verdict.checks if c.state == "undetermined"]
            result.undetermined.append(
                UndeterminedItem(
                    cu_slug=slug,
                    category="+".join(names) if names else "required_component_not_passed",
                    reason=verdict.reason or "판정 불가",
                    checks=_checks_json(verdict),
                )
            )
            continue
        result.verdicts.append(verdict)

    if golden_slugs is not None:
        seen = set(order)
        for slug in golden_slugs:
            if slug not in seen:
                result.undetermined.append(
                    UndeterminedItem(
                        cu_slug=slug,
                        category="not_in_inputs",
                        reason="입력 JSONL 어디에도 이 골든 slug가 없다",
                    )
                )
    return result


def prediction_rows(result: AdapterResult) -> list[dict[str, Any]]:
    """predictions JSONL 행 — `qa_confusion_matrix.parse_predictions`가 읽는 형식."""
    return [
        {
            "cu_slug": v.cu_slug,
            "qa_verdict": v.verdict,
            "predictor": result.predictor,
            "reason": v.reason,
            "checks": _checks_json(v),
        }
        for v in result.verdicts
    ]


def undetermined_rows(result: AdapterResult) -> list[dict[str, Any]]:
    return [
        {
            "cu_slug": u.cu_slug,
            "category": u.category,
            "reason": u.reason,
            "predictor": result.predictor,
            "checks": dict(u.checks),
        }
        for u in result.undetermined
    ]


def _load_rows(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """JSONL → 행 목록 + 파싱 실패(예외 타입명·파일명·줄 번호만 — 값·원문 미출력)."""
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for lineno, raw in enumerate(handle, start=1):
            text = raw.strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except json.JSONDecodeError as exc:
                errors.append(f"{type(exc).__name__}: {path.name} {lineno}번째 줄")
                continue
            if not isinstance(obj, dict):
                errors.append(f"TypeError: {path.name} {lineno}번째 줄(객체 아님)")
                continue
            rows.append(obj)
    return rows, errors


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _emit(summary: Mapping[str, Any]) -> None:
    """요약 JSON — stdout 데이터 전용(진행 메시지는 stderr)."""
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI — exit 0(predictions ≥1) · 1(0건 — 측정 실패) · 2(입력 오류)."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.qa_item_verdict",
        description="QA 엔진 문항별 판정 — 코퍼스/검수 큐 JSONL → predictions JSONL (EOS-137 ①)",
    )
    parser.add_argument(
        "--input", action="append", type=Path, required=True, help="코퍼스·검수 큐 JSONL(반복 가능)"
    )
    parser.add_argument("--out", type=Path, required=True, help="predictions JSONL 출력 경로")
    parser.add_argument(
        "--undetermined", type=Path, required=True, help="판정 불가 문항 JSONL 출력 경로"
    )
    parser.add_argument("--golden", type=Path, default=None, help="동결 골든 JSON(slug 필터)")
    parser.add_argument("--fuzz", action="store_true", help="수치 반례 fuzz까지 돌린다(느림)")
    args = parser.parse_args(argv)

    summary: dict[str, Any] = {"inputs": [], "input_errors": []}
    all_rows: list[dict[str, Any]] = []
    for path in args.input:
        if not path.is_file():
            summary["input_errors"].append(f"FileNotFoundError: {path}")
            continue
        rows, errors = _load_rows(path)
        summary["inputs"].append(
            {"path": str(path), "rows": len(rows), "parse_errors": len(errors)}
        )
        summary["input_errors"].extend(errors)
        all_rows.extend(rows)

    golden_slugs: list[str] | None = None
    if args.golden is not None:
        try:
            golden = load_golden_set(args.golden)
        except (OSError, ValueError) as exc:
            summary["input_errors"].append(f"{type(exc).__name__}: 골든 로드 불가 — {args.golden}")
        else:
            golden_slugs = [item.cu_slug for item in golden.items]
            summary["golden"] = {
                "version": golden.golden_version,
                "rotation": golden.rotation,
                "digest": golden.digest,
                "items": len(golden.items),
            }

    if summary["input_errors"]:
        summary["verdict"] = "input_error"
        print(
            f"[입력 오류] {len(summary['input_errors'])}건 — 산출 파일을 쓰지 않는다",
            file=sys.stderr,
            flush=True,
        )
        _emit(summary)
        return _EXIT_INPUT_ERROR

    result = build_predictions(all_rows, golden_slugs=golden_slugs, use_fuzz=args.fuzz)
    predictions = prediction_rows(result)
    _write_jsonl(args.out, predictions)
    _write_jsonl(args.undetermined, undetermined_rows(result))
    summary.update(result.summary())
    summary["out"] = str(args.out)
    summary["undetermined_out"] = str(args.undetermined)

    if not predictions:
        summary["verdict"] = "measurement_failed"
        print(
            "[측정 실패] predictions 0건 — 판정한 문항이 없다(0건 통과가 아니다)",
            file=sys.stderr,
            flush=True,
        )
        _emit(summary)
        return _EXIT_MEASUREMENT_FAIL
    summary["verdict"] = "ok"
    _emit(summary)
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
