"""학생 의도 섀도 *수확기* — 섀도 레코드 로그 → 규칙↔laya 일치도 표 (PED-51 · 오프라인·비노출).

배경 (왜 이 도구가 필요한가)
----------------------------
PED-48 섀도는 학생 턴마다 규칙 분류기(`classify_student_intent`, 5종)와 laya-ko-whymath(6종)의
판단 쌍을 `intent_shadow_records.log`에 JSON 한 줄로 남긴다. 그런데 그 줄을 모아 **일치도 표**로
바꿀 도구가 없었다 — 두 라벨 체계의 대응표가 사람 결정이었기 때문이다. 그 결정이 2026-11-04에
내려졌고(`_intent_shadow.LAYA_TO_RULE_INTENT`, 측정 전용), 이 모듈이 그 표로 집계한다.

    python -m whymath_backend.harness.intent_shadow_harvest intent_shadow_records.log \
        [--since 2026-11-03T00:00:00Z] [--until ...] [--json report.json]

무엇을 내나 (순서가 곧 읽는 순서다)
----------------------------------
1. **작동 비율** — `failure`가 없는 레코드 / 전체. 실패(`ConnectError`·`Overloaded`…)도 분모다.
   일치도보다 먼저 낸다: 작동하지 않은 판정기의 일치도는 표본이 아니라 생존자다.
2. **일치도** — 성공 레코드에서 rule_intent × laya_intent 교차표, 대응표 기준 일치율과 Wilson
   단측 95% 하한·상한, laya 라벨별·확신 구간별·풀이 동반 여부별 일치.
3. **개인정보 겹침** — laya(`pii_prob ≥ 0.5`)와 규칙 백스톱(`pii_rule`, PED-50)의 2×2와 종류별 건수.
4. **지연** — 성공 레코드의 중앙값·p95(ms).

설계 경계
---------
- **판정선 없음**: 분포를 *제시*한다. 승격 여부는 사람(Kiki) 결정이다 — 종료 코드는 성공(0)과
  입력 오류(2)만 구분한다.
- **레코드 스키마 단일 진실 원천**: 파싱은 emit 측 `IntentShadowObservation`(`extra="forbid"`)으로
  검증한다. 손으로 키를 재타이핑하지 않는다.
- **정직 회계 (침묵 실패 금지)**: parsed·skipped(섀도 레코드가 아닌 줄)·broken(레코드로 보이는데
  JSON·스키마가 깨짐 — *예외 타입명*을 함께 센다)을 나눈다. 집계 대상이 0건이면 exit 2다 —
  스캔 0건은 공허한 통과가 아니라 실패다.
- **모른다 ≠ 아니다**: 레코드 v1(규칙 필드 이전)과 규칙 판정 실패(`pii_rule=None`)는 개인정보
  겹침에서 "아님"으로 접지 않고 *규칙 미기록*으로 따로 센다. rule_intent가 없는 레코드도 일치도
  분모에서 빼고 따로 센다.
- **중복 입력**: 레코드에는 식별자가 없다(프라이버시 설계 — 학생과 재결합 금지). 그래서 줄 단위
  중복 제거는 할 수 없고, *같은 파일*(sha256 동일)을 두 번 넣은 경우만 한 번으로 센다.

프라이버시: 레코드에 학생 원문·해시·식별자가 없으므로 리포트도 비식별이다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from whymath_backend.api._intent_shadow import LAYA_TO_RULE_INTENT, IntentShadowObservation
from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_INPUT_ERROR = 2

# laya 개인정보 판정 기준 — laya-serve noul 확률의 기본 경계
# (Laya 배포 안내서의 pii_guard 규칙과 같다).
PII_PROB_THRESHOLD = 0.5

# 확신 구간 — 경계는 [하한, 상한). 마지막 구간은 1.0을 포함한다.
CONFIDENCE_BINS: tuple[tuple[float, float], ...] = ((0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.0))

# 섀도 레코드로 *식별*하는 키 — 둘 다 있으면 레코드로 보고, 검증 실패는 broken으로 센다.
_IDENTIFYING_KEYS = ("route", "questions_version")


# ──────────────────────────────────────────────────────────────────────────
# 파싱 — 회계를 분리한다
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class ParseAccounting:
    parsed: int = 0
    skipped: int = 0
    broken: int = 0
    broken_types: dict[str, int] = field(default_factory=dict)
    duplicate_files: int = 0

    def add_broken(self, type_name: str) -> None:
        self.broken += 1
        self.broken_types[type_name] = self.broken_types.get(type_name, 0) + 1

    def merge(self, other: ParseAccounting) -> None:
        self.parsed += other.parsed
        self.skipped += other.skipped
        self.broken += other.broken
        for k, v in other.broken_types.items():
            self.broken_types[k] = self.broken_types.get(k, 0) + v


def parse_log_text(text: str) -> tuple[list[IntentShadowObservation], ParseAccounting]:
    """로그 본문 → (레코드, 회계). Windows 로그의 CRLF·BOM도 받는다."""
    acc = ParseAccounting()
    records: list[IntentShadowObservation] = []
    for raw in text.lstrip("\ufeff").splitlines():
        line = raw.strip()
        if not line:
            continue
        if not line.startswith("{"):
            acc.skipped += 1
            continue
        try:
            obj = json.loads(line)
        except ValueError as exc:
            # "{"로 시작하는데 깨졌다 — 로테이션 절단 등. 레코드였을 수 있으니 broken으로 센다.
            acc.add_broken(type(exc).__name__)
            continue
        if not isinstance(obj, dict) or not all(k in obj for k in _IDENTIFYING_KEYS):
            acc.skipped += 1
            continue
        try:
            records.append(IntentShadowObservation.model_validate(obj))
        except ValidationError as exc:
            acc.add_broken(type(exc).__name__)
            continue
        acc.parsed += 1
    return records, acc


def _as_utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def filter_window(
    records: Sequence[IntentShadowObservation],
    *,
    since: datetime | None,
    until: datetime | None,
) -> tuple[list[IntentShadowObservation], int]:
    """관측 시각 구간 필터(양끝 포함) → (남은 것, 구간 밖 건수). 관측 시각은 시 단위 절삭값이다."""
    kept: list[IntentShadowObservation] = []
    for r in records:
        t = _as_utc(r.observed_at)
        if since is not None and t < _as_utc(since):
            continue
        if until is not None and t > _as_utc(until):
            continue
        kept.append(r)
    return kept, len(records) - len(kept)


# ──────────────────────────────────────────────────────────────────────────
# 집계 — 순수 함수
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class RateCell:
    agree: int
    n: int
    rate: float | None
    wilson_lower: float | None
    wilson_upper: float | None


def _rate(agree: int, n: int) -> RateCell:
    if n == 0:
        return RateCell(agree, n, None, None, None)
    return RateCell(
        agree,
        n,
        round(agree / n, 4),
        round(wilson_lower_bound(agree, n), 4),
        round(wilson_upper_bound(agree, n), 4),
    )


@dataclass
class IntentShadowHarvestSummary:
    total: int
    succeeded: int
    working_ratio: float | None
    failure_types: dict[str, int]
    by_route: dict[str, int]
    schema_versions: dict[str, int]
    # 일치도
    no_rule_intent: int
    cross_table: dict[str, dict[str, int]]
    agreement: RateCell
    agreement_by_laya: dict[str, RateCell]
    agreement_by_confidence: dict[str, RateCell]
    agreement_by_has_solution: dict[str, RateCell]
    # 개인정보 겹침
    pii_both: int
    pii_laya_only: int
    pii_rule_only: int
    pii_neither: int
    pii_rule_unrecorded: int
    pii_rule_kinds: dict[str, int]
    # 지연
    latency_median_ms: float | None
    latency_p95_ms: float | None


def _bin_label(lo: float, hi: float) -> str:
    return f"[{lo:.1f},{hi:.1f}]" if hi >= 1.0 else f"[{lo:.1f},{hi:.1f})"


def _bin_of(confidence: float) -> str:
    for lo, hi in CONFIDENCE_BINS:
        if lo <= confidence < hi or (hi >= 1.0 and confidence == hi):
            return _bin_label(lo, hi)
    return "범위밖"


def _percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    # 최근접 순위법 — 작은 표본에서 보간으로 없는 값을 만들지 않는다.
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


def summarize(records: Sequence[IntentShadowObservation]) -> IntentShadowHarvestSummary:
    total = len(records)
    ok = [r for r in records if r.failure is None and r.laya_intent is not None]
    # failure 없이 laya 판정도 없는 레코드는 이 모듈이 만들지 않지만, 생기면 0으로 숨기지 않는다.
    failure_types = Counter(
        r.failure or "응답없음"
        for r in records
        if not (r.failure is None and r.laya_intent is not None)
    )

    comparable = [r for r in ok if r.rule_intent is not None]
    cross: dict[str, dict[str, int]] = {}
    for r in comparable:
        assert r.rule_intent is not None and r.laya_intent is not None
        row = cross.setdefault(r.rule_intent.value, {})
        row[r.laya_intent] = row.get(r.laya_intent, 0) + 1

    def agrees(r: IntentShadowObservation) -> bool:
        return r.laya_intent is not None and LAYA_TO_RULE_INTENT.get(r.laya_intent) == r.rule_intent

    by_laya: dict[str, RateCell] = {}
    for label in sorted({r.laya_intent for r in comparable if r.laya_intent}):
        grp = [r for r in comparable if r.laya_intent == label]
        by_laya[label] = _rate(sum(agrees(r) for r in grp), len(grp))

    by_conf: dict[str, RateCell] = {}
    for lo, hi in CONFIDENCE_BINS:
        lab = _bin_label(lo, hi)
        grp = [
            r
            for r in comparable
            if r.laya_confidence is not None and _bin_of(r.laya_confidence) == lab
        ]
        by_conf[lab] = _rate(sum(agrees(r) for r in grp), len(grp))

    by_sol: dict[str, RateCell] = {}
    for flag in (True, False):
        grp = [r for r in comparable if r.has_solution is flag]
        by_sol["풀이동반" if flag else "발화만"] = _rate(sum(agrees(r) for r in grp), len(grp))

    # 개인정보 겹침 — laya 판정이 있는 성공 레코드 기준. 규칙 미기록은 따로.
    pii_scope = [r for r in ok if r.pii_prob is not None]
    known = [r for r in pii_scope if r.pii_rule is not None and r.schema_version >= 2]
    unrecorded = len(pii_scope) - len(known)
    both = sum(
        1
        for r in known
        if r.pii_rule and r.pii_prob is not None and r.pii_prob >= PII_PROB_THRESHOLD
    )
    laya_only = sum(
        1
        for r in known
        if not r.pii_rule and r.pii_prob is not None and r.pii_prob >= PII_PROB_THRESHOLD
    )
    rule_only = sum(
        1
        for r in known
        if r.pii_rule and r.pii_prob is not None and r.pii_prob < PII_PROB_THRESHOLD
    )
    neither = len(known) - both - laya_only - rule_only
    kinds = Counter(k for r in records if r.pii_rule for k in r.pii_rule_kinds)

    latencies = [r.latency_ms for r in ok]
    return IntentShadowHarvestSummary(
        total=total,
        succeeded=len(ok),
        working_ratio=round(len(ok) / total, 4) if total else None,
        failure_types=dict(sorted(failure_types.items())),
        by_route=dict(sorted(Counter(r.route for r in records).items())),
        schema_versions={
            str(k): v for k, v in sorted(Counter(r.schema_version for r in records).items())
        },
        no_rule_intent=len(ok) - len(comparable),
        cross_table={k: dict(sorted(v.items())) for k, v in sorted(cross.items())},
        agreement=_rate(sum(agrees(r) for r in comparable), len(comparable)),
        agreement_by_laya=by_laya,
        agreement_by_confidence=by_conf,
        agreement_by_has_solution=by_sol,
        pii_both=both,
        pii_laya_only=laya_only,
        pii_rule_only=rule_only,
        pii_neither=neither,
        pii_rule_unrecorded=unrecorded,
        pii_rule_kinds=dict(sorted(kinds.items())),
        latency_median_ms=_percentile(latencies, 0.5),
        latency_p95_ms=_percentile(latencies, 0.95),
    )


# ──────────────────────────────────────────────────────────────────────────
# 입력·출력
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class IntentShadowHarvestReport:
    files: list[str]
    accounting: ParseAccounting
    outside_window: int
    window: dict[str, str | None]
    summary: IntentShadowHarvestSummary


def harvest_files(
    paths: Iterable[Path],
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> IntentShadowHarvestReport:
    """파일들 → 리포트. 같은 내용(sha256)의 파일은 한 번만 센다. 없는 파일은 FileNotFoundError."""
    acc = ParseAccounting()
    records: list[IntentShadowObservation] = []
    seen: set[str] = set()
    names: list[str] = []
    for path in paths:
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            acc.duplicate_files += 1
            continue
        seen.add(digest)
        names.append(str(path))
        recs, file_acc = parse_log_text(data.decode("utf-8"))
        records.extend(recs)
        acc.merge(file_acc)
    kept, outside = filter_window(records, since=since, until=until)
    return IntentShadowHarvestReport(
        files=names,
        accounting=acc,
        outside_window=outside,
        window={
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
        },
        summary=summarize(kept),
    )


def _fmt_cell(c: RateCell) -> str:
    if c.n == 0:
        return "0건(판정 불가)"
    bounds = f"Wilson 단측95% 하한 {c.wilson_lower:.3f} · 상한 {c.wilson_upper:.3f}"
    return f"{c.agree}/{c.n} = {c.rate:.3f} ({bounds})"


def render_report(report: IntentShadowHarvestReport) -> str:
    s, a = report.summary, report.accounting
    out = [
        "=" * 72,
        "학생 의도 섀도 수확 — 규칙(5종) ↔ laya(6종) 일치도 [판정선 없음 · 분포 제시]",
        "=" * 72,
        f"입력 파일 {len(report.files)}개 (내용 중복으로 건너뛴 파일 {a.duplicate_files}개)",
        f"[파싱] 레코드 {a.parsed} · 비레코드 줄 {a.skipped} · "
        f"깨진 줄 {a.broken} {a.broken_types or ''}",
    ]
    w = report.window
    if w["since"] or w["until"]:
        out.append(
            f"[집계 구간] {w['since']} ~ {w['until']} · 구간 밖 제외 {report.outside_window}건"
        )
    else:
        out.append("[집계 구간] 미지정 (전체)")
    out += [
        "",
        f"[1. 작동 비율] {s.succeeded}/{s.total} = {s.working_ratio}  "
        f"실패 {s.failure_types or '없음'}",
        f"  경로별 {s.by_route} · 레코드 버전별 {s.schema_versions}",
        "",
        f"[2. 일치도] 대응표(LAYA_TO_RULE_INTENT) 기준 {_fmt_cell(s.agreement)}",
        f"  규칙 의도 없음(분모 제외) {s.no_rule_intent}건",
        "  교차표 (행 = 규칙 · 열 = laya):",
    ]
    for rule, row in s.cross_table.items():
        out.append(f"    {rule}: " + ", ".join(f"{k} {v}" for k, v in row.items()))
    out.append("  laya 라벨별:")
    for k, c in s.agreement_by_laya.items():
        out.append(f"    {k}: {_fmt_cell(c)}")
    out.append("  laya 확신 구간별:")
    for k, c in s.agreement_by_confidence.items():
        out.append(f"    {k}: {_fmt_cell(c)}")
    out.append("  풀이 동반 여부별:")
    for k, c in s.agreement_by_has_solution.items():
        out.append(f"    {k}: {_fmt_cell(c)}")
    out += [
        "",
        f"[3. 개인정보 겹침] laya(p≥{PII_PROB_THRESHOLD}) × 규칙 백스톱",
        f"  둘 다 {s.pii_both} · laya만 {s.pii_laya_only} · "
        f"규칙만 {s.pii_rule_only} · 둘 다 아님 {s.pii_neither}",
        f"  규칙 미기록(레코드 v1·규칙 판정 실패 — '아님'으로 세지 않음) {s.pii_rule_unrecorded}건",
        f"  규칙 종류별 {s.pii_rule_kinds or '없음'}",
        "",
        f"[4. 지연] 중앙값 {s.latency_median_ms} ms · p95 {s.latency_p95_ms} ms",
        "",
        "★ 판정선 없음 — 승격 여부는 사람(Kiki) 결정. "
        "합성 트래픽이면 실 학생 분포를 대표하지 않는다.",
    ]
    return "\n".join(out)


def report_to_json(report: IntentShadowHarvestReport) -> dict[str, object]:
    return asdict(report)


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.intent_shadow_harvest",
        description="학생 의도 섀도 레코드 → 규칙↔laya 일치도 표 (판정선 없음)",
    )
    parser.add_argument(
        "logs", nargs="+", type=Path, help="intent_shadow_records.log 경로(여러 개 가능)"
    )
    parser.add_argument("--since", type=_parse_iso, default=None, help="ISO 8601 · 포함")
    parser.add_argument("--until", type=_parse_iso, default=None, help="ISO 8601 · 포함")
    parser.add_argument("--json", type=Path, default=None, help="JSON 리포트 저장 경로")
    args = parser.parse_args(argv)

    try:
        report = harvest_files(args.logs, since=args.since, until=args.until)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"HARVEST_REFUSED=True 사유={type(exc).__name__}: {exc}")
        return EXIT_INPUT_ERROR
    print(render_report(report))
    if args.json is not None:
        args.json.write_text(
            json.dumps(report_to_json(report), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"JSON={args.json}")
    if report.summary.total == 0:
        print(
            "HARVEST_EMPTY=True — 집계 대상 0건(스캔 0건은 통과가 아니다). 경로·구간을 확인하세요"
        )
        return EXIT_INPUT_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
