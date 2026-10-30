"""오개념 crosswalk 검수 큐 *기계 트리아지* — 사람 검수 부담을 구조 신호로 우선순위화(순수·결정론).

`crosslink_machine_reject`(거부 전용)의 상위 도구다. 같은 독립 구조 신호(kebab 성취기준 역유도 ↔
M-id `standard_code` 대조·`crosslink_standard_signal`)로 pending 후보 전량을 **4버킷**으로 분류해,
사람이 무엇을 먼저·무엇을 안 봐도 되는지 알려준다(검수 부담 집중). 임베딩·LLM 0·완전 결정론.

버킷(정직한 라벨):
  - `auto_reject`   — disagree + 증거 ≥ 하한. 기계가 자율 거부해도 되는 측정 안전 구간
    (`machine_rejectable`·`crosslink_machine_reject`와 동일 집합). 승인 아님·거부만.
  - `corroborated` — agree(성취기준 정합). **승인이 아니라** "구조 신호가 반박하지 않음"이다 —
    같은 성취기준 내 형제 오개념 오매핑도 agree로 통과하므로(구조축 한계·§신호 정직 경계) 사람이
    *우선 검토*할 후보일 뿐, 정답 보증이 아니다. 사람이 닫는다.
  - `thin_disagree` — disagree이나 증거 < 하한. 역유도가 얇아 자율 거부 못 함(인간 폴백).
  - `no_signal`    — kebab 문항 미등장 또는 M-id 성취기준 없음. 기계 판정 불가(인간 전용).

**봉인 준수(핵심)**: 큐를 **읽기만** 한다(전행 pending 유지·`test_real_queue_all_pending_unsigned`
무손상). 산출은 advisory 리포트이며, 실제 승인/거부 반영은 사람(ops)이 검토 후 적용한다. 기계는
어떤 후보도 *승인* 표시하지 않는다(자기승인 금지·초인간 검증 §3.3 — 승인은 인간 존치).

CLI: `python -m whymath_backend.l4.misconception.crosslink_triage [--json]`(커밋 큐+코퍼스로 산출).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from whymath_backend.l1.misconception.crosslink_gate import (
    MACHINE_REJECT_EVIDENCE_FLOOR,
)
from whymath_backend.l1.problem_bank.populate import load_problem_bank_records
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.crosslink_machine_reject import (
    _default_corpora,
    _load_mid_standards,
    _repo_root,
)
from whymath_backend.l4.misconception.crosslink_review import parse_review_queue
from whymath_backend.l4.misconception.crosslink_standard_signal import (
    StandardAgreement,
    derive_kebab_problem_counts,
    derive_kebab_standards,
    standard_agreement,
)

__all__ = [
    "TriageBucket",
    "TriageReport",
    "TriagedCandidate",
    "format_worksheet",
    "run",
    "triage_candidates",
]

# 4버킷 — auto_reject(기계 거부 가능)·corroborated(구조 신호 긍정)·thin_disagree·no_signal.
TriageBucket = Literal["auto_reject", "corroborated", "thin_disagree", "no_signal"]
_BUCKETS: tuple[TriageBucket, ...] = (
    "auto_reject",
    "corroborated",
    "thin_disagree",
    "no_signal",
)

# 링크 유형 우선순위 — 직접매핑을 인간 검토 앞에 둔다(신뢰 밴드 순).
_LINK_TYPE_RANK: dict[str, int] = {"직접매핑": 0, "부분매핑": 1, "개념겹침": 2}


@dataclass(frozen=True, slots=True)
class TriagedCandidate:
    """트리아지된 후보 1건 — 버킷 + 구조 신호 근거(감사·검수 보조). 승인 표시는 담지 않는다."""

    kebab_id: str
    mis_id: str
    link_type: str
    confidence: float | None
    bucket: TriageBucket
    agreement: StandardAgreement
    kebab_problem_count: int
    mid_standard: str | None
    kebab_standards: tuple[str, ...]

    def _sort_key(self) -> tuple[int, float, str, str]:
        # 인간 우선 검토 정렬 — 직접매핑 우선·confidence 내림차순·안정 tie-break.
        conf = self.confidence if self.confidence is not None else 0.0
        return (
            _LINK_TYPE_RANK.get(self.link_type, 9),
            -conf,
            self.kebab_id,
            self.mis_id,
        )


@dataclass(frozen=True, slots=True)
class TriageReport:
    """트리아지 리포트 — 버킷별 후보(불변). 큐 무변경·advisory(승인 아님)."""

    candidates: tuple[TriagedCandidate, ...]

    def bucket(self, name: TriageBucket) -> tuple[TriagedCandidate, ...]:
        """한 버킷 후보를 인간 검토 우선순위로 정렬해 반환(순수)."""
        return tuple(
            sorted(
                (c for c in self.candidates if c.bucket == name),
                key=lambda c: c._sort_key(),
            )
        )

    @property
    def counts(self) -> dict[TriageBucket, int]:
        out: dict[TriageBucket, int] = {
            "auto_reject": 0,
            "corroborated": 0,
            "thin_disagree": 0,
            "no_signal": 0,
        }
        for c in self.candidates:
            out[c.bucket] += 1
        return out


def _classify(agreement: StandardAgreement, count: int, evidence_floor: int) -> TriageBucket:
    """구조 신호 판정 + 증거량 → 버킷(순수·거부는 측정 안전 구간만)."""
    if agreement == "disagree":
        return "auto_reject" if count >= evidence_floor else "thin_disagree"
    if agreement == "agree":
        return "corroborated"
    return "no_signal"


def triage_candidates(
    *,
    queue: dict[str, object],
    kebab_standards: Mapping[str, frozenset[str]],
    kebab_counts: Mapping[str, int],
    mid_standards: Mapping[str, str | None],
    evidence_floor: int = MACHINE_REJECT_EVIDENCE_FLOOR,
) -> TriageReport:
    """검수 큐 pending 후보를 4버킷으로 분류(순수·결정론·큐 무변경).

    pending 행만 대상(approved/rejected/deferred는 사람 판정 불변). 각 행에 독립 구조 신호를 적용해
    버킷을 매긴다. 승인은 절대 매기지 않는다(corroborated는 우선 검토 신호일 뿐·정답 보증 아님).
    """
    items = parse_review_queue(queue)  # top key/형식 검증 재사용(단일 정본)
    out: list[TriagedCandidate] = []
    for item in items:
        if item.status != "pending":
            continue
        kebab_std = kebab_standards.get(item.kebab_id, frozenset())
        count = kebab_counts.get(item.kebab_id, 0)
        mid_std = mid_standards.get(item.mis_id)
        agreement = standard_agreement(kebab_std, mid_std)
        out.append(
            TriagedCandidate(
                kebab_id=item.kebab_id,
                mis_id=item.mis_id,
                link_type=str(item.link_type),
                confidence=item.confidence,
                bucket=_classify(agreement, count, evidence_floor),
                agreement=agreement,
                kebab_problem_count=count,
                mid_standard=mid_std,
                kebab_standards=tuple(sorted(kebab_std)),
            )
        )
    return TriageReport(candidates=tuple(out))


def run(
    *,
    queue_path: Path,
    corpora: Sequence[Path],
    misconceptions: Path,
    evidence_floor: int = MACHINE_REJECT_EVIDENCE_FLOOR,
) -> TriageReport:
    """커밋 큐+코퍼스에서 트리아지 리포트 산출(파일 IO·DB 0·큐 무변경)."""
    records = []
    for path in corpora:
        records.extend(load_problem_bank_records(path))
    kebab_standards = derive_kebab_standards(records)
    kebab_counts = derive_kebab_problem_counts(records)
    mid_standards = _load_mid_standards(misconceptions)
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    return triage_candidates(
        queue=queue,
        kebab_standards=kebab_standards,
        kebab_counts=kebab_counts,
        mid_standards=mid_standards,
        evidence_floor=evidence_floor,
    )


def _report_json(report: TriageReport) -> dict[str, object]:
    """리포트를 JSON 직렬화 형태로(버킷별·advisory 표기)."""
    return {
        "advisory": "기계 트리아지·승인 아님·큐 무변경(corroborated는 우선 검토 신호일 뿐).",
        "counts": report.counts,
        "buckets": {
            bucket: [
                {
                    "kebab_id": c.kebab_id,
                    "mis_id": c.mis_id,
                    "link_type": c.link_type,
                    "confidence": c.confidence,
                    "agreement": c.agreement,
                    "kebab_problem_count": c.kebab_problem_count,
                    "mid_standard": c.mid_standard,
                    "kebab_standards": list(c.kebab_standards),
                }
                for c in report.bucket(bucket)
            ]
            for bucket in _BUCKETS
        },
    }


def _load_mid_texts(path: Path) -> dict[str, tuple[str, str]]:
    """M-id 콘텐츠 서술 로드 — mis_id → (canonical_statement, student_wrong_thinking)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("misconceptions", data)
    out: dict[str, tuple[str, str]] = {}
    for m in items:
        if isinstance(m, dict) and "mis_id" in m:
            out[str(m["mis_id"])] = (
                str(m.get("canonical_statement") or ""),
                str(m.get("student_wrong_thinking") or ""),
            )
    return out


def format_worksheet(
    report: TriageReport,
    *,
    kebab_statements: Mapping[str, tuple[str, str]],
    mid_texts: Mapping[str, tuple[str, str]],
    bucket: TriageBucket = "corroborated",
) -> str:
    """사람 검토 워크시트 — 한 버킷의 두 서술(kebab↔M-id)을 대조 + 판정란(승인은 사람만).

    `kebab_statements`: kebab_id → (name_kr, canonical_statement)(L4 탐지 카탈로그).
    `mid_texts`: mis_id → (canonical_statement, student_wrong_thinking)(콘텐츠 카탈로그).
    기계는 우선순위·근거만 제공하고 승인은 담지 않는다 — 판정란은 사람이 채운다(초인간 검증 §3.3).
    """
    candidates = report.bucket(bucket)
    lines = [
        "=" * 72,
        f"crosswalk 검토 워크시트 — [{bucket}] {len(candidates)}건 (사람 승인 대상·기계 승인 0)",
        "=" * 72,
        "두 서술을 대조해 판정하세요. 승인은 사람만 — 기계는 우선순위·구조 근거만 제공.",
        "",
    ]
    for i, c in enumerate(candidates, start=1):
        k_name, k_stmt = kebab_statements.get(c.kebab_id, ("", ""))
        m_stmt, m_think = mid_texts.get(c.mis_id, ("", ""))
        conf = f"{c.confidence:.2f}" if c.confidence is not None else "—"
        shared = ", ".join(c.kebab_standards) or "—"
        lines.append(f"[{i:2d}] {c.kebab_id} → {c.mis_id}  ({c.link_type}·conf {conf})")
        lines.append(f"     성취기준 정합: {c.mid_standard} ∈ {{{shared}}}")
        lines.append(f"     오개념(kebab·{k_name}): {k_stmt}")
        lines.append(f"     콘텐츠(M-id): {m_stmt}")
        if m_think:
            lines.append(f"       학생 오사고: {m_think}")
        lines.append("     판정: [ ] 승인   [ ] 반려    근거: ______")
        lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)


def format_report(report: TriageReport) -> str:
    """사람 가독 요약 — 버킷별 카운트 + 인간 우선 검토 목록(승인 아님·advisory)."""
    counts = report.counts
    lines = [
        "=" * 66,
        "crosswalk 검수 큐 기계 트리아지 — 독립 구조 신호(승인 아님·큐 무변경)",
        "=" * 66,
        f"pending 후보 {len(report.candidates)}건 → "
        f"corroborated {counts['corroborated']} · no_signal {counts['no_signal']} · "
        f"auto_reject {counts['auto_reject']} · thin_disagree {counts['thin_disagree']}",
        "-" * 66,
        "[auto_reject] 기계 자율 거부 가능(cross-standard·증거 충분) — 사람 확인 후 거부",
    ]
    for c in report.bucket("auto_reject"):
        lines.append(
            f"  ✗ {c.kebab_id} → {c.mis_id} [{c.link_type}] "
            f"(M표준 {c.mid_standard}·증거 {c.kebab_problem_count})"
        )
    lines.append(
        "[corroborated] 구조 신호 긍정 — 사람 *우선* 검토(정답 보증 아님·직접매핑·conf 순)"
    )
    for c in report.bucket("corroborated"):
        conf = f"{c.confidence:.2f}" if c.confidence is not None else "—"
        lines.append(f"  ? {c.kebab_id} → {c.mis_id} [{c.link_type}] (conf {conf})")
    lines.append("[thin_disagree] disagree이나 증거 부족 — 인간 폴백")
    for c in report.bucket("thin_disagree"):
        lines.append(
            f"  · {c.kebab_id} → {c.mis_id} [{c.link_type}] (증거 {c.kebab_problem_count})"
        )
    lines.append(
        f"[no_signal] 기계 판정 불가(문항 미등장 등) — 인간 전용 ({counts['no_signal']}건)"
    )
    lines.append("=" * 66)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI — 커밋 큐+코퍼스로 트리아지 산출·출력(큐 무변경·advisory·승인 아님)."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.l4.misconception.crosslink_triage",
        description="crosswalk 검수 큐를 독립 구조 신호로 4버킷 트리아지(승인 아님·큐 무변경).",
    )
    parser.add_argument("--queue", default=None, help="검수 큐 JSON(기본 docs/data).")
    parser.add_argument("--misconceptions", default=None, help="M-id 코퍼스 JSON.")
    parser.add_argument("--floor", type=int, default=MACHINE_REJECT_EVIDENCE_FLOOR)
    parser.add_argument("--json", action="store_true", help="JSON 리포트 출력(기본 사람 가독).")
    parser.add_argument(
        "--worksheet",
        default=None,
        help="검토 워크시트 버킷(예 corroborated) — 두 서술 대조 + 판정란 출력.",
    )
    args = parser.parse_args(argv)

    queue_path = (
        Path(args.queue)
        if args.queue
        else _repo_root() / "docs" / "data" / "misconception_crosslink_review_queue.json"
    )
    mis_path = (
        Path(args.misconceptions)
        if args.misconceptions
        else _repo_root() / "data" / "corpus" / "misconceptions_v1" / "misconceptions.json"
    )
    report = run(
        queue_path=queue_path,
        corpora=_default_corpora(),
        misconceptions=mis_path,
        evidence_floor=args.floor,
    )
    if args.worksheet:
        kebab_statements = {k: (m.name_kr, m.canonical_statement) for k, m in CATALOG_BY_ID.items()}
        print(
            format_worksheet(
                report,
                kebab_statements=kebab_statements,
                mid_texts=_load_mid_texts(mis_path),
                bucket=args.worksheet,
            )
        )
    elif args.json:
        print(json.dumps(_report_json(report), ensure_ascii=False, indent=2))
    else:
        print(format_report(report))
    return 0


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
