"""사람 검수 승인 라벨 → 코퍼스 JSON + DB `review_status` 갱신 CLI.

입력 JSONL은 사람(또는 강등전을 통과한 기계 판정자)이 검수한 `code`·`review_status` 목록이다.
`review_status='reviewed'`인 code만 코퍼스 JSON과 `concept_content` 테이블에 반영한다.
다른 상태(rejected, ai_estimated 등)는 코퍼스/DB를 건드리지 않는다(fail-closed).

**승인 행은 검수 게이트를 통과해야 한다** — `l1.concept_content.review_gate`가 승격 권위를
검사한다(`reviewed_by`가 등재 검수자 + `reviewed_at` ISO 8601). `review_status='reviewed'`는
학생 노출 게이팅 기준이라(`l1/*/retrieval.py`) 서명 없는 승격은 미검증 AI 콘텐츠의 학생 노출이
된다. 위반이 1건이라도 있으면 **전체를 거부**한다(부분 적용 금지).

사용:
    python -m whymath_backend.harness.concept_content_review_apply \
        --labels docs/data/concept_content_reviewed.jsonl \
        [--dry-run]

입력 JSONL 예시:
    {
      "code": "N1",
      "review_status": "reviewed",
      "reviewed_by": "kiki",
      "reviewed_at": "2026-08-16T00:00:00Z"
    }
    {
      "code": "N2",
      "review_status": "rejected",
      "reviewed_by": "kiki",
      "reviewed_at": "2026-08-16T00:00:00Z"
    }

exit code:
    0 — 갱신 완료(또는 dry-run 시 갱신할 수 있음).
    1 — 검수 게이트 위반(서명 누락·미등재 검수자) 또는 DB 코퍼스 불일치 등 검수 라벨 문제.
    2 — 입력 파일 부재·JSONL 파싱 오류.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from whymath_backend.l1.concept_content.projection import ConceptContentStore
from whymath_backend.l1.concept_content.review_gate import promotion_violations

_EXIT_OK = 0
_EXIT_LABEL_ERROR = 1
_EXIT_INPUT_ERROR = 2

_DEFAULT_K12 = Path("data/corpus/concept_content_v1/content.json")
_DEFAULT_UNIV = Path("data/corpus/concept_content_university_v1/content.json")
_REPO_ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True, slots=True)
class LabelRow:
    """사람 검수 라벨 1건."""

    code: str
    review_status: str
    reviewed_by: str | None
    reviewed_at: str | None


@dataclass(slots=True)
class ApplyReport:
    """갱신 리포트."""

    total_labels: int
    approved_codes: list[str]
    rejected_or_other: list[str]
    k12_updated: int
    university_updated: int
    db_updated: int
    missing_in_corpus: list[str]
    gate_violations: list[str]

    def to_json(self) -> dict[str, Any]:
        return {
            "total_labels": self.total_labels,
            "approved_count": len(self.approved_codes),
            "approved_codes": sorted(self.approved_codes),
            "rejected_or_other_count": len(self.rejected_or_other),
            "k12_updated": self.k12_updated,
            "university_updated": self.university_updated,
            "db_updated": self.db_updated,
            "missing_in_corpus": sorted(self.missing_in_corpus),
            "gate_violations": list(self.gate_violations),
        }

    def render(self) -> str:
        lines = [
            "=" * 72,
            "개념 콘텐츠 검수 승인 적용 리포트",
            "=" * 72,
            f"전체 라벨: {self.total_labels}건",
            f"승인(reviewed): {len(self.approved_codes)}건",
            f"기타/거부: {len(self.rejected_or_other)}건",
            f"K-12 JSON 갱신: {self.k12_updated}건",
            f"대학 JSON 갱신: {self.university_updated}건",
            f"DB 갱신: {self.db_updated}건",
        ]
        if self.gate_violations:
            lines.append("")
            lines.append(
                f"검수 게이트 위반: {len(self.gate_violations)}건 — 승격 거부(fail-closed)"
            )
            for violation in self.gate_violations[:10]:
                lines.append(f"  - {violation}")
            if len(self.gate_violations) > 10:
                lines.append(f"  ... 외 {len(self.gate_violations) - 10}건")
        if self.missing_in_corpus:
            lines.append(f"코퍼스에 없는 승인 code: {len(self.missing_in_corpus)}건")
            for code in self.missing_in_corpus[:10]:
                lines.append(f"  - {code}")
            if len(self.missing_in_corpus) > 10:
                lines.append(f"  ... 외 {len(self.missing_in_corpus) - 10}건")
        lines.append("=" * 72)
        return "\n".join(lines)


def load_labels(path: Path) -> list[LabelRow]:
    """JSONL 라벨 파일을 로드한다."""
    rows: list[LabelRow] = []
    with path.open("r", encoding="utf-8") as f:
        for line_num, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL 파싱 오류 line {line_num}: {exc}") from exc
            reviewed_by = obj.get("reviewed_by")
            reviewed_by = reviewed_by if isinstance(reviewed_by, str) else None
            reviewed_at = obj.get("reviewed_at")
            reviewed_at = reviewed_at if isinstance(reviewed_at, str) else None
            rows.append(
                LabelRow(
                    code=str(obj.get("code", "")),
                    review_status=str(obj.get("review_status", "")),
                    reviewed_by=reviewed_by,
                    reviewed_at=reviewed_at,
                )
            )
    return rows


def _update_corpus(path: Path, approved_codes: set[str]) -> int:
    """코퍼스 JSON에서 approved_codes에 해당하는 항목 review_status를 'reviewed'로 갱신.

    변경이 있을 때만 파일을 덮어쓴다. 반환=갱신한 항목 수.
    """
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    updated = 0
    for record in data.get("content", []):
        code = record.get("code")
        if code in approved_codes and record.get("review_status") != "reviewed":
            record["review_status"] = "reviewed"
            updated += 1

    if updated > 0:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
    return updated


def apply_labels(
    labels: list[LabelRow],
    *,
    k12_path: Path,
    university_path: Path,
    store: ConceptContentStore | None = None,
    dry_run: bool = False,
) -> ApplyReport:
    """라벨을 코퍼스 JSON + DB에 적용한다."""
    approved = [row for row in labels if row.review_status == "reviewed"]
    approved_codes = [row.code for row in approved]
    approved_set = set(approved_codes)
    other = [row.code for row in labels if row.review_status != "reviewed"]

    report = ApplyReport(
        total_labels=len(labels),
        approved_codes=approved_codes,
        rejected_or_other=other,
        k12_updated=0,
        university_updated=0,
        db_updated=0,
        missing_in_corpus=[],
        gate_violations=[],
    )

    # 검수 게이트 — 승격 권위 확인이 가장 먼저다(fail-closed: 1행이라도 위반이면 전체 거부).
    # 부분 적용을 허용하면 "일부는 서명 없이도 들어간다"가 되어 게이트가 무의미해진다.
    for index, row in enumerate(approved):
        report.gate_violations.extend(
            promotion_violations(
                code=row.code,
                review_status=row.review_status,
                reviewed_by=row.reviewed_by,
                reviewed_at=row.reviewed_at,
                row_label=f"[행 {index}] ",
            )
        )
    if report.gate_violations:
        return report

    if not approved_codes:
        return report

    # 승인 code가 코퍼스에 존재하는지 먼저 검증(fail-closed: 불일치 시 DB·코퍼스 모두 갱신 안 함).
    k12_data = json.loads(k12_path.read_text(encoding="utf-8"))
    univ_data = json.loads(university_path.read_text(encoding="utf-8"))
    corpus_codes = {
        str(r.get("code")) for r in k12_data.get("content", []) + univ_data.get("content", [])
    }
    report.missing_in_corpus = [code for code in approved_codes if code not in corpus_codes]
    if report.missing_in_corpus:
        return report

    # 코퍼스 JSON 갱신
    if not dry_run:
        report.k12_updated = _update_corpus(k12_path, approved_set)
        report.university_updated = _update_corpus(university_path, approved_set)

    # DB 갱신
    content_store = store if store is not None else ConceptContentStore()
    if not dry_run:
        report.db_updated = content_store.mark_review_status(tuple(approved_codes), "reviewed")

    return report


def main(argv: list[str] | None = None) -> int:
    """CLI 본체."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.concept_content_review_apply",
        description="사람 검수 라벨 → 코퍼스 JSON + DB review_status 갱신.",
    )
    parser.add_argument("--labels", type=Path, required=True, help="검수 라벨 JSONL 경로.")
    parser.add_argument("--k12", type=Path, default=None, help="K-12 content.json 경로.")
    parser.add_argument("--university", type=Path, default=None, help="대학 content.json 경로.")
    parser.add_argument("--dry-run", action="store_true", help="갱신하지 않고 리포트만 출력.")
    parser.add_argument("--json", type=Path, default=None, help="리포트 JSON 저장 경로.")
    args = parser.parse_args(argv)

    k12 = args.k12 or _REPO_ROOT / _DEFAULT_K12
    university = args.university or _REPO_ROOT / _DEFAULT_UNIV

    if not args.labels.exists():
        print(f"입력 오류: 라벨 파일 없음 {args.labels}", file=sys.stderr)
        return _EXIT_INPUT_ERROR

    try:
        labels = load_labels(args.labels)
    except (OSError, ValueError) as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return _EXIT_INPUT_ERROR

    try:
        report = apply_labels(
            labels,
            k12_path=k12,
            university_path=university,
            dry_run=args.dry_run,
        )
    except (OSError, json.JSONDecodeError) as exc:
        print(f"코퍼스 갱신 오류: {exc}", file=sys.stderr)
        return _EXIT_INPUT_ERROR

    print(report.render())
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"리포트 JSON: {args.json}")

    if report.gate_violations:
        print(
            f"검수 게이트 거부: {len(report.gate_violations)}건 — 승격하지 않았습니다"
            " (AI 자기승인 금지·서명 필수).",
            file=sys.stderr,
        )
        return _EXIT_LABEL_ERROR
    if report.missing_in_corpus:
        print(
            f"라벨 오류: {len(report.missing_in_corpus)}건의 승인 code가 코퍼스에 없습니다.",
            file=sys.stderr,
        )
        return _EXIT_LABEL_ERROR
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
