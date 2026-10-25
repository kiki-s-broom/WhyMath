"""오개념 crosswalk 후보의 *기계 자동 거부* — cross-standard 오매핑을 측정 안전 구간에서 자율 거부.

초인간 검증 §3.3 crosswalk 축의 계약 플립: 강등전(240/240·Wilson 하한 0.989)으로 *성취기준
가로지르는 오매핑 거부*가 측정된 구간에서만, 기계가 검수 큐의 pending 후보를 **자율 거부**한다
(절대 승인 아님 — 승인은 인간 존치). 거부 조건은 `crosslink_standard_signal.machine_rejectable`
(증거 하한 + 성취기준 disagree). 거부 실패 모드는 보수적(correct 매핑을 놓쳐도 *누락*이지 오매핑
적재가 아님).

**봉인 준수(핵심)**: 이 도구는 커밋된 검수 큐 템플릿을 **변경하지 않는다**(전행 pending 유지·
`test_real_queue_all_pending_unsigned` 무손상). 기계 거부는 큐를 읽어 *거부 대상을 산출*할 뿐이며,
실제 큐 반영은 ops가 산출을 검토 후 적용한다(자기승인 금지 원칙은 승인 방향에만·거부는 보수적).

CLI: `python -m whymath_backend.l4.misconception.crosslink_machine_reject`(커밋 큐+코퍼스로 산출).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from whymath_backend.l1.misconception.crosslink_gate import MACHINE_REJECT_EVIDENCE_FLOOR
from whymath_backend.l1.problem_bank.populate import load_problem_bank_records
from whymath_backend.l4.misconception.crosslink_review import parse_review_queue
from whymath_backend.l4.misconception.crosslink_standard_signal import (
    derive_kebab_problem_counts,
    derive_kebab_standards,
    machine_rejectable,
)

__all__ = ["MachineRejection", "machine_reject_candidates"]


@dataclass(frozen=True, slots=True)
class MachineRejection:
    """기계 자율 거부 1건 — 후보 + 증거·사유(감사용). 승인은 절대 담지 않는다(거부 전용)."""

    kebab_id: str
    mis_id: str
    link_type: str
    kebab_problem_count: int
    reason: str


def machine_reject_candidates(
    *,
    queue: dict[str, object],
    kebab_standards: Mapping[str, frozenset[str]],
    kebab_counts: Mapping[str, int],
    mid_standards: Mapping[str, str | None],
    evidence_floor: int = MACHINE_REJECT_EVIDENCE_FLOOR,
) -> list[MachineRejection]:
    """검수 큐 pending 후보 중 기계 자율 거부 대상 산출(순수·결정론).

    pending 행만 대상(approved/rejected/deferred는 사람 판정 불변). 각 행에 `machine_rejectable`
    (증거 하한 + disagree)을 적용해 True만 거부 목록에 담는다. 승인은 절대 산출 안 함(거부 전용).
    """
    items = parse_review_queue(queue)  # top key/형식 검증 재사용(단일 정본)
    out: list[MachineRejection] = []
    for item in items:
        if item.status != "pending":
            continue
        kebab_std = kebab_standards.get(item.kebab_id, frozenset())
        count = kebab_counts.get(item.kebab_id, 0)
        if machine_rejectable(
            kebab_std, count, mid_standards.get(item.mis_id), evidence_floor=evidence_floor
        ):
            out.append(
                MachineRejection(
                    kebab_id=item.kebab_id,
                    mis_id=item.mis_id,
                    link_type=item.link_type,
                    kebab_problem_count=count,
                    reason=f"성취기준 불일치(cross-standard)·증거 {count}문항(≥{evidence_floor})",
                )
            )
    return out


def _repo_root() -> Path:
    # src/backend/whymath_backend/l4/misconception/ → repo root 5단계.
    return Path(__file__).resolve().parents[5]


def _default_corpora() -> list[Path]:
    return sorted((_repo_root() / "data" / "corpus").glob("problem_bank_*/problems.jsonl"))


def _load_mid_standards(path: Path) -> dict[str, str | None]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("misconceptions", data)
    return {
        str(m["mis_id"]): (str(m["standard_code"]) if m.get("standard_code") else None)
        for m in items
        if isinstance(m, dict) and "mis_id" in m
    }


def run(
    *,
    queue_path: Path,
    corpora: Sequence[Path],
    misconceptions: Path,
    evidence_floor: int = MACHINE_REJECT_EVIDENCE_FLOOR,
) -> list[MachineRejection]:
    """커밋 큐+코퍼스에서 기계 거부 대상 산출(파일 IO·DB 0·큐 무변경)."""
    records = []
    for path in corpora:
        records.extend(load_problem_bank_records(path))
    kebab_standards = derive_kebab_standards(records)
    kebab_counts = derive_kebab_problem_counts(records)
    mid_standards = _load_mid_standards(misconceptions)
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    return machine_reject_candidates(
        queue=queue,
        kebab_standards=kebab_standards,
        kebab_counts=kebab_counts,
        mid_standards=mid_standards,
        evidence_floor=evidence_floor,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI — 커밋 큐+코퍼스로 기계 거부 대상 산출·출력(큐 무변경·advisory)."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.l4.misconception.crosslink_machine_reject",
        description="crosswalk 후보의 기계 자율 거부(cross-standard·측정 안전 구간·승인 아님).",
    )
    parser.add_argument("--queue", default=None, help="검수 큐 JSON(기본 docs/data).")
    parser.add_argument("--misconceptions", default=None, help="M-id 코퍼스 JSON.")
    parser.add_argument("--floor", type=int, default=MACHINE_REJECT_EVIDENCE_FLOOR)
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
    rejections = run(
        queue_path=queue_path,
        corpora=_default_corpora(),
        misconceptions=mis_path,
        evidence_floor=args.floor,
    )
    print(f"기계 자율 거부 대상: {len(rejections)}건 (승인 아님·큐 무변경·advisory)")
    for r in rejections:
        print(f"  reject {r.kebab_id} → {r.mis_id} [{r.link_type}] — {r.reason}")
    return 0


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
