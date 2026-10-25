"""crosswalk 승인 강등전 — 독립 구조 신호 게이트의 오매핑 거부를 *측정*(초인간 검증 §3 확장).

crosswalk(kebab↔M-id) 매핑 승인을 인간 검수 대신 기계가 얼마나 대신할 수 있는지를 **측정**한다
(자기승인 아님·게이트 계약 무변경). 게이트 = 독립 구조 신호(`crosslink_standard_signal`): kebab의
성취기준을 문항 사용에서 역유도해 M-id `standard_code`와 대조 — `agree`면 승인·`disagree`면 거부·
`no_signal`이면 기권(인간 폴백). 강등전 셋(`crosslink_demotion_seeder`·인간 라벨 0)에 게이트를 돌려
tier별 거부율 Wilson 경계를 낸다:

  - `cross_standard_neg`(성취기준 다른 오매핑) 거부율 **Wilson 하한** — 게이트가 잡는 구간(강점).
  - `same_standard_neg`(같은 성취기준 형제 오매핑) 거부율 — 게이트가 *못 잡는* 구간(false accept·
    인간 존치·정직 표기).
  - `positive`(정답) 오거부율 **Wilson 상한** — 정답을 거부하면 회귀(0이어야 함).

**커버리지 정직 회계**: 34 kebab 중 구조 신호가 유도되는(문항 등장) machine-decidable 수 vs
no_signal(인간 전용) 수를 명시 출력한다(silent cap 금지). 순수·결정론·임베딩 0·LLM 0·DB 0.

사용:
    python -m whymath_backend.harness.crosslink_demotion_eval          # 커밋 코퍼스로 측정
    python -m whymath_backend.harness.crosslink_demotion_eval --human-labels human.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound
from whymath_backend.l1.problem_bank.populate import load_problem_bank_records
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.crosslink_demotion_seeder import (
    CrosslinkTrial,
    build_demotion_set,
)
from whymath_backend.l4.misconception.crosslink_standard_signal import (
    derive_kebab_standards,
    standard_agreement,
)

_EXIT_OK = 0
_EXIT_FAIL = 1

# cross-standard 거부율 Wilson 하한 최소선 — 구조 신호가 성취기준 가로지르는 오매핑을 신뢰성
# 있게 거부해야 게이트로서 의미가 있다(정확 신호라 실측 ~0.98·플로어 보수적 0.90).
_CROSS_REJECT_FLOOR = 0.90


def _repo_root() -> Path:
    # src/backend/whymath_backend/harness/ → repo root 5단계.
    return Path(__file__).resolve().parents[4]


def _default_problem_corpora() -> list[Path]:
    corpus = _repo_root() / "data" / "corpus"
    return sorted(corpus.glob("problem_bank_*/problems.jsonl"))


def _default_misconceptions() -> Path:
    return _repo_root() / "data" / "corpus" / "misconceptions_v1" / "misconceptions.json"


def _load_mid_standards(path: Path) -> dict[str, str | None]:
    """M-id 코퍼스(misconceptions_v1) → {mis_id: standard_code}(없으면 None)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("misconceptions", data)
    out: dict[str, str | None] = {}
    for m in items:
        if isinstance(m, dict) and "mis_id" in m:
            std = m.get("standard_code")
            out[str(m["mis_id"])] = str(std) if std else None
    return out


def _gate_decision(
    trial: CrosslinkTrial,
    kebab_standards: dict[str, frozenset[str]],
    mid_standards: dict[str, str | None],
) -> str:
    """게이트 판정 — agree→approve·disagree→reject·no_signal→abstain."""
    agreement = standard_agreement(
        kebab_standards.get(trial.kebab_id, frozenset()), mid_standards.get(trial.mis_id)
    )
    return {"agree": "approve", "disagree": "reject", "no_signal": "abstain"}[agreement]


@dataclass(slots=True, frozen=True)
class CrosslinkDemotionReport:
    """tier별 게이트 성능 + 커버리지 회계(순수 집계)."""

    positive_total: int
    positive_false_reject: int
    cross_detected: int
    cross_total: int
    same_detected: int
    same_total: int
    kebabs_total: int
    kebabs_decidable: int

    def cross_lower_bound(self, confidence: float = 0.95) -> float | None:
        if self.cross_total == 0:
            return None
        return wilson_lower_bound(self.cross_detected, self.cross_total, confidence)

    def same_lower_bound(self, confidence: float = 0.95) -> float | None:
        if self.same_total == 0:
            return None
        return wilson_lower_bound(self.same_detected, self.same_total, confidence)

    def false_reject_upper(self, confidence: float = 0.95) -> float | None:
        if self.positive_total == 0:
            return None
        return wilson_upper_bound(self.positive_false_reject, self.positive_total, confidence)


def summarize(
    trials: list[CrosslinkTrial],
    kebab_standards: dict[str, frozenset[str]],
    mid_standards: dict[str, str | None],
) -> CrosslinkDemotionReport:
    """강등전 셋에 게이트를 돌려 tier별 집계 + 커버리지 회계(순수·결정론)."""
    pos_total = pos_false_reject = 0
    cross_detected = cross_total = 0
    same_detected = same_total = 0
    for trial in trials:
        decision = _gate_decision(trial, kebab_standards, mid_standards)
        if trial.tier == "positive":
            pos_total += 1
            if decision == "reject":
                pos_false_reject += 1
        elif trial.tier == "cross_standard_neg":
            cross_total += 1
            if decision == "reject":
                cross_detected += 1
        else:  # same_standard_neg
            same_total += 1
            if decision == "reject":
                same_detected += 1
    decidable = sum(1 for k in CATALOG_BY_ID if kebab_standards.get(k))
    return CrosslinkDemotionReport(
        positive_total=pos_total,
        positive_false_reject=pos_false_reject,
        cross_detected=cross_detected,
        cross_total=cross_total,
        same_detected=same_detected,
        same_total=same_total,
        kebabs_total=len(CATALOG_BY_ID),
        kebabs_decidable=decidable,
    )


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def format_report(
    report: CrosslinkDemotionReport,
    *,
    confidence: float,
    human_reject_rate: float | None,
) -> str:
    """사람 가독 리포트 — tier별 거부율 + 커버리지 경계 + (있으면) 사람 대조."""
    pct = round(confidence * 100)
    cross_pt = report.cross_detected / report.cross_total if report.cross_total else None
    same_pt = report.same_detected / report.same_total if report.same_total else None
    lines = [
        "=" * 66,
        "crosswalk 승인 강등전 — 독립 구조 신호 게이트 (초인간 검증 §3 확장)",
        "=" * 66,
        "[tier별 오매핑 거부(높을수록 좋음)]",
        f"  cross-standard(성취기준 다름) : {report.cross_detected}/{report.cross_total} "
        f"(점 {_fmt(cross_pt)}·{pct}% 하한 {_fmt(report.cross_lower_bound(confidence))})",
        f"  same-standard(형제 오개념)   : {report.same_detected}/{report.same_total} "
        f"(점 {_fmt(same_pt)}·{pct}% 하한 {_fmt(report.same_lower_bound(confidence))})"
        "  ← 구조축 못 잡음(인간 존치)",
        "[정답 오거부(낮을수록 좋음)]",
        f"  positive 오거부 : {report.positive_false_reject}/{report.positive_total} "
        f"({pct}% 상한 {_fmt(report.false_reject_upper(confidence))})",
        "[커버리지 정직 회계]",
        f"  machine-decidable(구조 신호 有) : {report.kebabs_decidable}/{report.kebabs_total}",
        f"  human-only(no_signal·문항 미등장): "
        f"{report.kebabs_total - report.kebabs_decidable}/{report.kebabs_total} kebab",
    ]
    if human_reject_rate is not None:
        lines.append("[사람 대조 — same-standard 구간(기계 사각)]")
        lines.append(f"  사람 오매핑 거부율(점추정): {_fmt(human_reject_rate)}")
        lines.append(
            "  → 기계는 cross-standard를 자동 거부(인간 부하↓)하나 same-standard는 사람이 존치"
            " (부분 대체·측정된 경계)."
        )
    lines.append("=" * 66)
    return "\n".join(lines)


def _human_reject_rate(labels_path: Path) -> float:
    """사람 라벨 JSONL({label: reject|approve, is_wrong: bool}) → 오매핑 거부율(점추정)."""
    detected = total = 0
    for raw in labels_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        row = json.loads(raw)
        if row.get("is_wrong"):
            total += 1
            if row.get("label") == "reject":
                detected += 1
    return detected / total if total else 0.0


def run(
    *,
    problem_corpora: list[Path],
    misconceptions: Path,
    cross_per_positive: int,
    same_per_positive: int,
) -> tuple[CrosslinkDemotionReport, list[CrosslinkTrial]]:
    """커밋 코퍼스에서 강등전 셋 구성 + 게이트 측정(순수 파일 IO·DB 0)."""
    records = []
    for path in problem_corpora:
        records.extend(load_problem_bank_records(path))
    kebab_standards = derive_kebab_standards(records)
    mid_standards = _load_mid_standards(misconceptions)
    trials = build_demotion_set(
        mid_standards=mid_standards,
        kebab_standards=kebab_standards,
        cross_per_positive=cross_per_positive,
        same_per_positive=same_per_positive,
    )
    return summarize(trials, kebab_standards, mid_standards), trials


def main(argv: list[str] | None = None) -> int:
    """CLI — crosswalk 구조 게이트 강등전 측정. 정답 오거부·cross 거부율 하한 미달이면 exit 1."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.crosslink_demotion_eval",
        description="crosswalk 승인 독립 구조 신호 게이트를 강등전으로 측정(자기승인 아님).",
    )
    parser.add_argument("--corpus", action="append", default=None, help="문항 코퍼스 JSONL(반복).")
    parser.add_argument("--misconceptions", default=None, help="M-id 코퍼스 JSON.")
    parser.add_argument("--cross-per-positive", type=int, default=60)
    parser.add_argument("--same-per-positive", type=int, default=60)
    parser.add_argument("--confidence", type=float, default=0.95, help="Wilson 신뢰수준(단측).")
    parser.add_argument("--human-labels", default=None, help="사람 라벨 JSONL → 대조.")
    args = parser.parse_args(argv)

    corpora = [Path(p) for p in args.corpus] if args.corpus else _default_problem_corpora()
    mis_path = Path(args.misconceptions) if args.misconceptions else _default_misconceptions()

    report, _ = run(
        problem_corpora=corpora,
        misconceptions=mis_path,
        cross_per_positive=args.cross_per_positive,
        same_per_positive=args.same_per_positive,
    )
    human = _human_reject_rate(Path(args.human_labels)) if args.human_labels else None
    print(format_report(report, confidence=args.confidence, human_reject_rate=human))

    cross_lb = report.cross_lower_bound(args.confidence)
    if report.positive_false_reject > 0:
        print("❌ 회귀 — 정답 매핑을 거부(구조 신호 오작동).")
        return _EXIT_FAIL
    if cross_lb is None or cross_lb < _CROSS_REJECT_FLOOR:
        print(f"❌ cross-standard 거부율 하한 {_fmt(cross_lb)} < 플로어 {_CROSS_REJECT_FLOOR}.")
        return _EXIT_FAIL
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
