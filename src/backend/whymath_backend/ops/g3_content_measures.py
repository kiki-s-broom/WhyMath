"""G3 판정 전 미측정 3항목 측정기 — 자동검증 1차 통과율·힌트 정답 누설·메타 누락 (EOS-207).

왜 이 모듈이 있는가
------------------
게이트 `G-eos-g3`(11/22 · ADR-007 개정)의 조건 다섯 중 셋 — **자동검증 1차 통과율 산출됨 ·
힌트 의미 누설 0 · 메타 누락 0** — 은 2026-10-28 EOS-197 회차 시점에 **측정 경로가 없었다**.
주간 KPI 원장(`metrics/weekly.json`)의 `auto_gate_pass_rate`는 "Deterministic Gate pass/fail 누적
로그 없음"으로 구조적 미측정이고, 누설·메타는 이번 회차에서 따로 재지 않았다. 이 CLI가 저작 회차
산출물(`data/runs/<회차>-*/cu.jsonl`·`cu.genlog.jsonl`·`cu.review.jsonl`)만 읽어(DB 0·LLM 0·
네트워크 0) 세 값을 낸다.

(a) 자동검증 1차 통과율 — 정의 (EOS-51 `eos_verification_design_v1.md` §6 동결 문구)
-------------------------------------------------------------------------------
§6: "Deterministic Gate pass ÷ 전체 생성 (수용 게이트 로그)". 이 저장소에서 그 낱말들은:

- **Deterministic Gate** = 동등문제 수용 게이트(`l3/equivalent/acceptance.py` — 저작권·SymPy
  정확성·위생·동등성 4종, LLM 0). 오케스트레이터(`l3/equivalent/orchestrator.py`)의 처리 순서가
  `생성 → 수용 게이트 → 과유사(dedup) → 저장`이므로 **게이트 통과 = `accepted_stored` +
  `rejected_duplicate`**다(중복 거부는 게이트를 통과한 *뒤* 신규성 축에서 걸린 것이다).
  `needs_review`(게이트가 정확성을 확인하지 못함)·`rejected_gate`는 1차 불통과다.
- **전체 생성** = 생성기가 후보를 낸 시도 = 게이트에 도달한 후보(`generation_failed` 제외 —
  후보가 없으면 게이트가 판정할 것이 없다). 시도 전체 대비 비율도 함께 낸다(`ATTEMPT_PASS_RATE`).
- **수용 게이트 로그** = 회차 폴더의 `cu.jsonl`(저장분) + `cu.review.jsonl`(비저장분 · 사유 포함).
  두 파일의 행 합이 생성 로그(`cu.genlog.jsonl`) 행 수와 같아야 한다 — 다르면 **회계 불일치로
  측정 실패**다(빠진 행이 하필 불통과였다면 비율이 부풀어 보인다).
- **1차** = 게이트가 후보를 처음 판정한 결과. 사람 검수(승인·수정승인)는 세지 않는다 — 사람이
  고친 뒤의 통과는 자동검증의 통과가 아니다.

**우회된 통과는 통과가 아니다**: 게이트 통과분의 검산식을 `l3/equivalent/verify_bypass`로 기계
판정해, 정답 상수를 재진술만 하는 검산식(`n = 3`·`v - 24 = 0`)이나 무조건 참인 검산식으로 통과한
후보를 **우회(bypassed)**로 뺀다. KPI 값(`AUTO_GATE_PASS_RATE`)은 **재계산 검증으로 통과한
후보 ÷ 게이트 도달 후보**다. 우회를 빼지 않은 값은 `AUTO_GATE_PASS_RATE_RAW`로 함께 남긴다(두 값의
차가 곧 우회의 크기다). 우회 판정이 안 되는 통과가 1건이라도 있으면 값을 내지 않는다
(`measured=False` · 상·하한만 사유에 적는다 — 모르는 것을 통과로도 불통과로도 접지 않는다).

(b) 힌트 정답 누설 — 기계 축 2종 + 의미 축은 미측정으로 분리
-----------------------------------------------------------
CU 정의(§3)의 "3단계 힌트" 좌석은 S4-11 `hints` 표다(`l4/hint_content/models.Hint`). 이 CLI는
그 표의 내보내기(`--hints-jsonl` · `Hint` 모델 JSON 1행 1건)를 `solution_step_ref.problem_id`로 CU에
붙이고, 힌트 게이트 B(`l4/hint_content/gates.check_answer_leakage` — **재구현 0**)를 그대로 돌린다:
글자 축(`detect_answer_leakage`)과 값 축(`MathAnswerValueExposure` — 계산하면 정답이 되는 식).
힌트 1건의 판정은 3상태다 — 둘 중 하나라도 노출이면 **누설(True)**, 둘 다 clean이면 **아님
(False)**, 그 밖(짧은 정답의 글자 축 유보·값 축 판정 불가)은 **사람 폴백(None)**.

무관용 기준은 F8 정의대로 **L1·L2**다(§4 "힌트 정답 누설(L1·L2 무관용)"). L3 누설은 따로 센다.
힌트가 0건인 CU는 "누설 0"이 아니라 **측정 대상 부재**다(스캔 0건은 통과가 아니다).

**의미 축은 이 CLI가 재지 않는다**: §5 F-Ⅴ가 "힌트의 의미적 정답 누설(**자동 검사 밖**)"을 표본
검수로 재라고 못박았고, §6이 "전수 자동 + LLM 심판 + 인간 30건"을 요구한다. 기계 두 축이 clean이라는
것은 *글자·값으로는 안 드러났다*는 뜻일 뿐 의미상 누설 0의 증명이 아니다(측정 없는 기계 게이트를
인간 검수 대체로 선언 금지 — `docs/standards/superhuman_verification_standard.md`). 그래서 출력에
`HINT_SEMANTIC_AXIS=NOT_MEASURED`를 항상 싣고, 종료 코드는 **기계 판정**만 말한다.

(c) 메타 누락 — 필수 목록과 그 출처
---------------------------------
CU 레코드: `achievement_standard_codes`(1개 이상 — CLAUDE.md "모든 콘텐츠는 성취기준 코드 1개 이상"
· §3 성취기준 좌석) · `license`·`source_type`(`ops/provenance_audit` ③④) · `generation_type`·
`authored_by`(헌법 R27-01 "출처 필드(유형·근거·생성 모델·라이선스)"). 생성 로그: 같은 `cu_slug`의
**성공** 호출 존재(provenance_audit ⑥) + 그 호출의 `model_name`·`prompt_version`·`input_sha256`
(감리 W-18) + `seed`(모델이 seed를 받는 좌석일 때만 — Kiki 2026-10-27 결정 · provenance_audit ⑦).
seed를 검사하지 않은 CU는 모델별로 따로 센다(검사 안 함 ≠ 통과 — 그러나 누락도 아니다).

③ 검수 라벨 대조 — 둘 다 보존
----------------------------
`--review-dir`(기본 `<runs-root>/<회차>-review`)의 `canary_review_verdicts.jsonl`이 있으면 검수자
라벨(판정·실패 코드)을 기계 측정과 나란히 둔다. 어긋나도 **어느 쪽도 고치지 않는다** — 원 기록은
위변조하지 않고(EOS-197 ⑦ (c)) 어긋남만 `LABEL_MISMATCH`로 센다. 예: 실패 코드 F8(힌트 정답
누설)인데 그 CU에 힌트가 0건이면 라벨이 가리킬 힌트가 없다.

종료 코드 (기계 판정)
--------------------
- 0 : 세 항목 모두 측정됐고 위반 0·판정 불가 0(힌트 의미 축은 별도 — 위 (b)).
- 1 : 측정된 위반이 있다(L1·L2 힌트 누설 ≥1 또는 메타 누락 CU ≥1).
- 2 : 측정 실패 또는 판정 불가(회차 없음·파싱 실패·회계 불일치·우회 판정 불가·힌트 0건·사람 폴백
  대기). "0건 통과"로 위장하지 않는다.

사용
----
    python -m whymath_backend.ops.g3_content_measures --round eos197-a6
    python -m whymath_backend.ops.g3_content_measures --round eos197-a6 --json out.json
    python -m whymath_backend.ops.g3_content_measures --round eos197-a6 --hints-jsonl hints.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from whymath_backend.harness.wilson import wilson_lower_bound
from whymath_backend.l3.equivalent.verify_bypass import (
    VerifyBypassVerdict,
    classify_verify_bypass,
)
from whymath_backend.l3.generation_seed import SeedCapability, capability_for_model
from whymath_backend.l4.hint_content.gates import GateContext, check_answer_leakage
from whymath_backend.l4.hint_content.models import Hint
from whymath_backend.l4.subject_adapter_math import math_answer_value_exposure
from whymath_backend.ops.provenance_audit import (
    GENLOG_ALWAYS_REQUIRED_FIELDS,
    RUN_REQUIRED_RECORD_FIELDS,
    default_runs_root,
)

__all__ = [
    "GATE_PASS_STATUSES",
    "GATE_FAIL_STATUSES",
    "REQUIRED_RECORD_META",
    "AutoGateMeasure",
    "HintLeakMeasure",
    "MetaMeasure",
    "RoundInput",
    "RunDirInput",
    "build_report",
    "discover_round",
    "load_run_dir",
    "main",
    "measure_auto_gate",
    "measure_hint_leakage",
    "measure_meta",
]

EXIT_PASS = 0
EXIT_VIOLATION = 1
EXIT_UNMEASURED = 2

_CU_FILE = "cu.jsonl"
_GENLOG_FILE = "cu.genlog.jsonl"
_REVIEW_FILE = "cu.review.jsonl"
_VERDICTS_FILE = "canary_review_verdicts.jsonl"

# 오케스트레이터 상태(`l3/equivalent/orchestrator.EquivalentOutcome.status`)의 게이트 관점 분류.
# `accepted`는 저장 좌석 미주입 실행의 통과 상태다(같은 게이트 통과).
GATE_PASS_STATUSES: frozenset[str] = frozenset(
    {"accepted_stored", "accepted", "rejected_duplicate"}
)
GATE_FAIL_STATUSES: frozenset[str] = frozenset({"needs_review", "rejected_gate"})
_NOT_EVALUATED_STATUS = "generation_failed"
_KNOWN_STATUSES = GATE_PASS_STATUSES | GATE_FAIL_STATUSES | {_NOT_EVALUATED_STATUS}

# (c) 레코드 필수 메타 — 모듈 docstring (c)의 출처 순서. provenance_audit의 정본 목록을 포함한다.
REQUIRED_RECORD_META: tuple[str, ...] = (
    "achievement_standard_codes",
    *RUN_REQUIRED_RECORD_FIELDS,
    "generation_type",
    "authored_by",
)

# 무관용 레벨(F8 정의 — L1·L2).
_ZERO_TOLERANCE_LEVELS: frozenset[int] = frozenset({1, 2})


# ──────────────────────────────────────────────────────────────────────────
# 입력 — 회차 폴더 읽기(파싱 실패는 전건 기록 · 부분 입력으로 판정하지 않는다)
# ──────────────────────────────────────────────────────────────────────────
def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """JSONL → (객체 행, 오류 목록). 오류는 줄 번호·예외 타입명을 싣는다(필드값은 싣지 않는다)."""
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return rows, [f"{path.name} 읽기 실패 — {type(exc).__name__}"]
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}:{line_no} JSON 파싱 실패 — {type(exc).__name__}")
            continue
        if not isinstance(parsed, dict):
            errors.append(f"{path.name}:{line_no} 객체가 아님({type(parsed).__name__})")
            continue
        rows.append(parsed)
    return rows, errors


def _parse_moment(raw: object) -> datetime | None:
    """ISO8601 문자열 → aware datetime. 비었거나 형식이 틀리면 None(창 밖으로 친다)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


@dataclass(slots=True)
class RunDirInput:
    """저작 회차 폴더 1개(좌석 하나)의 세 파일."""

    name: str
    cu_rows: list[dict[str, Any]]
    review_rows: list[dict[str, Any]]
    genlog_rows: list[dict[str, Any]]
    errors: list[str] = field(default_factory=list)


def load_run_dir(path: Path) -> RunDirInput:
    """회차 폴더 → 세 파일. `cu.jsonl`·`cu.genlog.jsonl`은 필수, `cu.review.jsonl`은 없으면 0행
    (비저장 후보가 하나도 없던 회차). 필수 파일 부재는 오류로 남긴다."""
    errors: list[str] = []
    loaded: dict[str, list[dict[str, Any]]] = {}
    for filename, required in ((_CU_FILE, True), (_GENLOG_FILE, True), (_REVIEW_FILE, False)):
        file_path = path / filename
        if not file_path.is_file():
            loaded[filename] = []
            if required:
                errors.append(f"{path.name}/{filename} 없음")
            continue
        rows, errs = _read_jsonl(file_path)
        loaded[filename] = rows
        errors.extend(f"{path.name}/{e}" for e in errs)
    return RunDirInput(
        name=path.name,
        cu_rows=loaded[_CU_FILE],
        review_rows=loaded[_REVIEW_FILE],
        genlog_rows=loaded[_GENLOG_FILE],
        errors=errors,
    )


@dataclass(slots=True)
class RoundInput:
    """한 회차(좌석 여러 개 + 검수 폴더)의 입력."""

    round_id: str
    runs_root: str
    run_dirs: list[RunDirInput]
    verdict_rows: list[dict[str, Any]] | None
    verdicts_path: str | None
    errors: list[str] = field(default_factory=list)


def discover_round(runs_root: Path, round_id: str, *, review_dir: Path | None = None) -> RoundInput:
    """`<runs_root>/<round_id>-*` 중 `cu.jsonl`을 가진 폴더 = 좌석, `<round_id>-review` = 검수 폴더.

    좌석이 0개면 오류다(측정 대상 부재 — 0건 통과로 위장 금지).
    """
    errors: list[str] = []
    run_dirs: list[RunDirInput] = []
    if not runs_root.is_dir():
        errors.append(f"회차 루트 {runs_root} 이(가) 디렉터리가 아니다")
    else:
        for candidate in sorted(runs_root.glob(f"{round_id}-*")):
            if candidate.is_dir() and (candidate / _CU_FILE).is_file():
                loaded = load_run_dir(candidate)
                errors.extend(loaded.errors)
                run_dirs.append(loaded)
        if not run_dirs:
            errors.append(f"{runs_root} 아래 {round_id}-* 중 {_CU_FILE}를 가진 좌석 폴더가 0개")
    resolved_review = review_dir if review_dir is not None else runs_root / f"{round_id}-review"
    verdicts_path = resolved_review / _VERDICTS_FILE
    verdict_rows: list[dict[str, Any]] | None = None
    if verdicts_path.is_file():
        verdict_rows, verdict_errors = _read_jsonl(verdicts_path)
        errors.extend(f"review/{e}" for e in verdict_errors)
    elif review_dir is not None:
        errors.append(f"--review-dir를 줬는데 {verdicts_path} 이(가) 없다")
    return RoundInput(
        round_id=round_id,
        runs_root=str(runs_root),
        run_dirs=run_dirs,
        verdict_rows=verdict_rows,
        verdicts_path=str(verdicts_path) if verdict_rows is not None else None,
        errors=errors,
    )


# ──────────────────────────────────────────────────────────────────────────
# (a) 자동검증 1차 통과율
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class GateOutcome:
    """게이트 판정 1건(=생성 시도 1건). `bypass`는 게이트 통과분에만 있다."""

    run_dir: str
    slug: str | None
    status: str
    moment: datetime | None
    bypass: VerifyBypassVerdict | None


def _success_times(genlog_rows: Iterable[Mapping[str, Any]]) -> dict[str, datetime]:
    """cu_slug → 성공 생성 호출의 생성 시각(가장 이른 것).

    저장분(`cu.jsonl`) 행에는 시각이 없어 이것으로 붙인다.
    """
    times: dict[str, datetime] = {}
    for row in genlog_rows:
        slug = row.get("cu_slug")
        moment = _parse_moment(row.get("generated_at"))
        if row.get("success") is True and isinstance(slug, str) and moment is not None:
            if slug not in times or moment < times[slug]:
                times[slug] = moment
    return times


def _outcomes_for(run: RunDirInput) -> tuple[list[GateOutcome], list[str]]:
    """좌석 1개의 게이트 판정 목록 + 회계 오류."""
    errors: list[str] = []
    times = _success_times(run.genlog_rows)
    outcomes: list[GateOutcome] = []
    for row in run.cu_rows:
        slug = row.get("slug") if isinstance(row.get("slug"), str) else None
        # 저장분 = accepted_stored. 검산식 판정은 저장된 *원본* 페이로드로 한다(사람 수정 전).
        outcomes.append(
            GateOutcome(
                run.name,
                slug,
                "accepted_stored",
                times.get(slug) if slug else None,
                classify_verify_bypass(_mapping(row.get("verify"))),
            )
        )
    for row in run.review_rows:
        status = row.get("status")
        slug = row.get("slug") if isinstance(row.get("slug"), str) else None
        if not isinstance(status, str) or status not in _KNOWN_STATUSES:
            errors.append(f"{run.name}/{_REVIEW_FILE} 알 수 없는 상태 {status!r} — 회계 불가")
            continue
        bypass = None
        if status in GATE_PASS_STATUSES:
            payload = _mapping(row.get("candidate_payload"))
            bypass = classify_verify_bypass(_mapping(payload.get("verify")) if payload else None)
        outcomes.append(
            GateOutcome(run.name, slug, status, _parse_moment(row.get("recorded_at")), bypass)
        )
    if len(run.genlog_rows) != len(outcomes):
        errors.append(
            f"{run.name} 회계 불일치 — 생성 로그 {len(run.genlog_rows)}행 ≠ 게이트 기록 "
            f"{len(outcomes)}행({_CU_FILE} {len(run.cu_rows)} + {_REVIEW_FILE} "
            f"{len(run.review_rows)})"
        )
    return outcomes, errors


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


@dataclass(slots=True)
class AutoGateMeasure:
    """(a)의 결과. `measured=False`면 `rate`는 None이다(0으로 위장 금지)."""

    attempts: int = 0
    generation_failed: int = 0
    evaluated: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    passed_raw: int = 0
    recomputed: int = 0
    bypassed: int = 0
    bypass_kinds: dict[str, int] = field(default_factory=dict)
    bypass_undecided: int = 0
    outside_window: int = 0
    errors: list[str] = field(default_factory=list)
    passes: list[dict[str, Any]] = field(default_factory=list)

    @property
    def measured(self) -> bool:
        return not self.errors and self.evaluated > 0 and self.bypass_undecided == 0

    @property
    def rate(self) -> float | None:
        return self.recomputed / self.evaluated if self.measured else None

    @property
    def rate_raw(self) -> float | None:
        return self.passed_raw / self.evaluated if (not self.errors and self.evaluated) else None

    @property
    def attempt_rate(self) -> float | None:
        return self.recomputed / self.attempts if self.measured and self.attempts else None

    @property
    def wilson_lower(self) -> float | None:
        return wilson_lower_bound(self.recomputed, self.evaluated) if self.measured else None

    @property
    def reason(self) -> str | None:
        """미측정 사유(측정됐으면 None) — 원장·출력에 그대로 싣는다."""
        if self.errors:
            return (
                f"입력·회계 오류 {len(self.errors)}건 — 부분 입력으로 판정하지 않는다"
                f"(첫 사유: {self.errors[0]})"
            )
        if self.evaluated == 0:
            return "게이트에 도달한 후보 0건 — 분모 0(통과율 미산출)"
        if self.bypass_undecided:
            low = self.recomputed / self.evaluated
            high = (self.recomputed + self.bypass_undecided) / self.evaluated
            return (
                f"게이트 통과 {self.passed_raw}건 중 검산식 우회 판정 불가 "
                f"{self.bypass_undecided}건 — "
                f"통과율은 [{low:.4f}, {high:.4f}] 사이(값을 하나로 정하지 않는다)"
            )
        return None

    def to_json(self) -> dict[str, Any]:
        return {
            "measured": self.measured,
            "rate": self.rate,
            "rate_raw": self.rate_raw,
            "attempt_rate": self.attempt_rate,
            "wilson_lower_95": self.wilson_lower,
            "reason": self.reason,
            "attempts": self.attempts,
            "generation_failed": self.generation_failed,
            "evaluated": self.evaluated,
            "status_counts": dict(sorted(self.status_counts.items())),
            "passed_raw": self.passed_raw,
            "recomputed": self.recomputed,
            "bypassed": self.bypassed,
            "bypass_kinds": dict(sorted(self.bypass_kinds.items())),
            "bypass_undecided": self.bypass_undecided,
            "outside_window": self.outside_window,
            "errors": list(self.errors),
            "passes": self.passes,
        }


def measure_auto_gate(
    run_dirs: Sequence[RunDirInput],
    *,
    window: tuple[datetime, datetime] | None = None,
    input_errors: Sequence[str] = (),
) -> AutoGateMeasure:
    """좌석들 → (a). `window=[start, end)`를 주면 판정 시각이 창 안인 시도만 센다(주간 KPI 용 ·
    시각 없는 시도는 창 밖 — `weekly_metrics_report`의 NULL 규칙과 같다)."""
    measure = AutoGateMeasure(errors=list(input_errors))
    status_counts: Counter[str] = Counter()
    bypass_kinds: Counter[str] = Counter()
    for run in run_dirs:
        outcomes, errors = _outcomes_for(run)
        measure.errors.extend(errors)
        for outcome in outcomes:
            if window is not None and not (
                outcome.moment is not None and window[0] <= outcome.moment < window[1]
            ):
                measure.outside_window += 1
                continue
            measure.attempts += 1
            status_counts[outcome.status] += 1
            if outcome.status == _NOT_EVALUATED_STATUS:
                measure.generation_failed += 1
                continue
            measure.evaluated += 1
            if outcome.status not in GATE_PASS_STATUSES:
                continue
            measure.passed_raw += 1
            assert outcome.bypass is not None  # 통과 상태는 _outcomes_for가 항상 판정을 붙인다
            verdict = outcome.bypass
            bypass_kinds[verdict.kind.value] += 1
            if verdict.bypassed is True:
                measure.bypassed += 1
            elif verdict.bypassed is False:
                measure.recomputed += 1
            else:
                measure.bypass_undecided += 1
            measure.passes.append(
                {
                    "run_dir": outcome.run_dir,
                    "slug": outcome.slug,
                    "status": outcome.status,
                    "bypass": verdict.to_json(),
                }
            )
    measure.status_counts = dict(status_counts)
    measure.bypass_kinds = dict(bypass_kinds)
    return measure


# ──────────────────────────────────────────────────────────────────────────
# (b) 힌트 정답 누설
# ──────────────────────────────────────────────────────────────────────────
def _hint_leaked(hint: Hint, answer: str | None) -> tuple[bool | None, dict[str, str]]:
    """게이트 B(재사용)의 두 축 → 3상태. 개념 이름 지우기는 하지 않는다(맥락 없음 · 보수)."""
    verdict = check_answer_leakage(
        hint,
        GateContext(
            step_contents=(),
            concept_name=None,
            final_answer=answer,
            value_exposure=math_answer_value_exposure(),
        ),
    )
    text_axis = verdict.detail.get("verdict", "not_run")
    value_axis = verdict.detail.get("value_verdict", "not_run")
    if text_axis == "leaked" or value_axis == "exposed":
        return True, verdict.detail
    if text_axis == "clean" and value_axis == "clean":
        return False, verdict.detail
    return None, verdict.detail


@dataclass(slots=True)
class HintLeakMeasure:
    """(b)의 결과. `status` ∈ PASS·FAIL·UNDECIDED·NOT_MEASURABLE(기계 축만 — 의미 축은 별도)."""

    hint_inputs: int = 0
    cu_total: int = 0
    cu_with_hints: int = 0
    cu_without_hints: int = 0
    hints_total: int = 0
    hints_by_level: dict[str, int] = field(default_factory=dict)
    leaked_l12: int = 0
    undecided_l12: int = 0
    clean_l12: int = 0
    leaked_l3: int = 0
    unmatched_hints: int = 0
    errors: list[str] = field(default_factory=list)
    per_cu: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def status(self) -> str:
        if self.errors:
            return "NOT_MEASURABLE"
        if self.hints_total == 0:
            return "NOT_MEASURABLE"
        if self.leaked_l12:
            return "FAIL"
        if self.cu_without_hints or self.undecided_l12:
            return "UNDECIDED"
        return "PASS"

    @property
    def reason(self) -> str:
        if self.errors:
            return f"힌트 입력 오류 {len(self.errors)}건(첫 사유: {self.errors[0]})"
        if self.hint_inputs == 0:
            return (
                "힌트 입력 없음(--hints-jsonl 미지정) — 회차 산출물에는 힌트가 실리지 않으므로"
                f"(좌석은 S4-11 hints 표) CU {self.cu_total}건 전부 측정 대상 부재(누설 0이 아니다)"
            )
        if self.hints_total == 0:
            return f"CU {self.cu_total}건에 붙는 힌트 0건 — 측정 대상 부재(누설 0이 아니다)"
        if self.leaked_l12:
            return f"L1·L2 힌트 정답 누설 {self.leaked_l12}건(무관용)"
        if self.cu_without_hints or self.undecided_l12:
            return (
                f"힌트 없는 CU {self.cu_without_hints}건 · L1·L2 사람 폴백 "
                f"{self.undecided_l12}건 — "
                "누설 0을 확정할 수 없다"
            )
        return "기계 두 축(글자·값) L1·L2 누설 0 — 의미 축은 별도(사람 표본)"

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "semantic_axis": "NOT_MEASURED",
            "hint_inputs": self.hint_inputs,
            "cu_total": self.cu_total,
            "cu_with_hints": self.cu_with_hints,
            "cu_without_hints": self.cu_without_hints,
            "hints_total": self.hints_total,
            "hints_by_level": dict(sorted(self.hints_by_level.items())),
            "leaked_l12": self.leaked_l12,
            "undecided_l12": self.undecided_l12,
            "clean_l12": self.clean_l12,
            "leaked_l3": self.leaked_l3,
            "unmatched_hints": self.unmatched_hints,
            "errors": list(self.errors),
            "per_cu": self.per_cu,
        }


def load_hints(paths: Sequence[Path]) -> tuple[list[Hint], list[str]]:
    """`Hint` 모델 JSON 1행 1건 JSONL들 → (힌트, 오류).

    검증 실패는 줄 번호·예외 타입명으로 남긴다(필드값은 싣지 않는다).
    """
    hints: list[Hint] = []
    errors: list[str] = []
    for path in paths:
        if not path.is_file():
            errors.append(f"{path} 없음")
            continue
        rows, errs = _read_jsonl(path)
        errors.extend(errs)
        for index, row in enumerate(rows, start=1):
            try:
                hints.append(Hint.model_validate(row))
            except ValidationError as exc:
                errors.append(f"{path.name} 객체 {index}번 Hint 계약 위반 — {type(exc).__name__}")
    return hints, errors


def measure_hint_leakage(
    cu_rows: Sequence[Mapping[str, Any]],
    hints: Sequence[Hint],
    *,
    hint_inputs: int,
    errors: Sequence[str] = (),
) -> HintLeakMeasure:
    """CU 정답 × 그 CU의 힌트 → (b). `hint_inputs`는 받은 힌트 파일 수(0이면 '입력 없음' 사유)."""
    measure = HintLeakMeasure(hint_inputs=hint_inputs, errors=list(errors))
    by_problem: dict[str, list[Hint]] = {}
    for hint in hints:
        by_problem.setdefault(str(hint.solution_step_ref.problem_id), []).append(hint)
    known_problems: set[str] = set()
    levels: Counter[str] = Counter()
    for row in cu_rows:
        measure.cu_total += 1
        problem_id = str(row.get("problem_id"))
        known_problems.add(problem_id)
        slug = str(row.get("slug"))
        answer = row.get("answer") if isinstance(row.get("answer"), str) else None
        cu_hints = by_problem.get(problem_id, [])
        entry: dict[str, Any] = {"problem_id": problem_id, "hints": len(cu_hints), "judged": []}
        if not cu_hints:
            measure.cu_without_hints += 1
            measure.per_cu[slug] = entry
            continue
        measure.cu_with_hints += 1
        for hint in cu_hints:
            measure.hints_total += 1
            levels[f"L{hint.level}"] += 1
            leaked, detail = _hint_leaked(hint, answer)
            entry["judged"].append(
                {"hint_id": hint.hint_id, "level": hint.level, "leaked": leaked, **detail}
            )
            if hint.level in _ZERO_TOLERANCE_LEVELS:
                if leaked is True:
                    measure.leaked_l12 += 1
                elif leaked is False:
                    measure.clean_l12 += 1
                else:
                    measure.undecided_l12 += 1
            elif leaked is True:
                measure.leaked_l3 += 1
        measure.per_cu[slug] = entry
    measure.unmatched_hints = sum(
        len(group) for pid, group in by_problem.items() if pid not in known_problems
    )
    measure.hints_by_level = dict(levels)
    return measure


# ──────────────────────────────────────────────────────────────────────────
# (c) 메타 누락
# ──────────────────────────────────────────────────────────────────────────
def _blank(value: object) -> bool:
    """메타 값이 비었는가 — None·빈 문자열·공백 문자열·빈 목록(목록 안 빈 문자열만 있어도 빈 것)."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple)):
        return not any(isinstance(item, str) and item.strip() for item in value)
    return False


@dataclass(slots=True)
class MetaMeasure:
    """(c)의 결과. `status` ∈ PASS·FAIL·NOT_MEASURABLE."""

    cu_total: int = 0
    cu_missing: int = 0
    missing_by_field: dict[str, int] = field(default_factory=dict)
    seed_checked: int = 0
    seed_not_applicable_by_model: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    per_cu: dict[str, list[str]] = field(default_factory=dict)

    @property
    def status(self) -> str:
        if self.errors or self.cu_total == 0:
            return "NOT_MEASURABLE"
        return "FAIL" if self.cu_missing else "PASS"

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "required_record_meta": list(REQUIRED_RECORD_META),
            "required_genlog_meta": [
                "linked_success_call",
                *GENLOG_ALWAYS_REQUIRED_FIELDS,
                "seed*",
            ],
            "cu_total": self.cu_total,
            "cu_missing": self.cu_missing,
            "missing_by_field": dict(sorted(self.missing_by_field.items())),
            "seed_checked": self.seed_checked,
            "seed_not_applicable_by_model": dict(sorted(self.seed_not_applicable_by_model.items())),
            "errors": list(self.errors),
            "per_cu_missing": self.per_cu,
        }


def measure_meta(
    run_dirs: Sequence[RunDirInput], *, input_errors: Sequence[str] = ()
) -> MetaMeasure:
    """저장된 CU 전수 → (c). 필수 목록은 모듈 docstring (c)."""
    measure = MetaMeasure(errors=list(input_errors))
    missing_counter: Counter[str] = Counter()
    seed_na: Counter[str] = Counter()
    for run in run_dirs:
        success_by_slug: dict[str, list[Mapping[str, Any]]] = {}
        for log in run.genlog_rows:
            slug = log.get("cu_slug")
            if isinstance(slug, str) and log.get("success") is True:
                success_by_slug.setdefault(slug, []).append(log)
        for row in run.cu_rows:
            measure.cu_total += 1
            slug = row.get("slug")
            missing = [name for name in REQUIRED_RECORD_META if _blank(row.get(name))]
            linked = success_by_slug.get(slug) if isinstance(slug, str) else None
            if not linked:
                missing.append("genlog.linked_success_call")
            else:
                for linked_log in linked:
                    missing.extend(
                        f"genlog.{name}"
                        for name in GENLOG_ALWAYS_REQUIRED_FIELDS
                        if _blank(linked_log.get(name))
                    )
                    model = linked_log.get("model_name")
                    capability = capability_for_model(model if isinstance(model, str) else None)
                    if capability is SeedCapability.SUPPORTED:
                        measure.seed_checked += 1
                        if linked_log.get("seed") is None:
                            missing.append("genlog.seed")
                    else:
                        seed_na[f"{model}({capability.value})"] += 1
            missing = sorted(set(missing))
            if missing:
                measure.cu_missing += 1
                missing_counter.update(missing)
                measure.per_cu[f"{run.name}/{slug}"] = missing
    measure.missing_by_field = dict(missing_counter)
    measure.seed_not_applicable_by_model = dict(seed_na)
    return measure


# ──────────────────────────────────────────────────────────────────────────
# ③ 검수 라벨 대조 + 종합
# ──────────────────────────────────────────────────────────────────────────
def _label_crosscheck(
    verdict_rows: Sequence[Mapping[str, Any]] | None,
    gate: AutoGateMeasure,
    hint: HintLeakMeasure,
    meta: MetaMeasure,
) -> dict[str, Any]:
    """검수자 라벨과 기계 측정을 나란히 — 어긋남만 센다(어느 쪽도 고치지 않는다)."""
    if verdict_rows is None:
        return {"performed": False, "reason": "검수 판정 파일 없음", "mismatches": [], "rows": []}
    bypass_by_slug = {p["slug"]: p["bypass"] for p in gate.passes if p.get("slug")}
    rows: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    crosstab: Counter[str] = Counter()
    for verdict in verdict_rows:
        slug = verdict.get("slug")
        if not isinstance(slug, str):
            continue
        note = verdict.get("failure_note")
        first_line = (
            note.strip().splitlines()[0][:160] if isinstance(note, str) and note.strip() else None
        )
        bypass = bypass_by_slug.get(slug)
        hint_entry = hint.per_cu.get(slug)
        machine_hint_leak: bool | None = None
        if hint_entry and hint_entry["judged"]:
            flags = [
                j["leaked"] for j in hint_entry["judged"] if j["level"] in _ZERO_TOLERANCE_LEVELS
            ]
            machine_hint_leak = True if True in flags else (None if None in flags else False)
        record = {
            "slug": slug,
            "label_verdict": verdict.get("verdict"),
            "label_failure_code": verdict.get("failure_code"),
            "label_note_first_line": first_line,
            "machine_bypass_kind": bypass["kind"] if bypass else None,
            "machine_hints": hint_entry["hints"] if hint_entry else None,
            "machine_hint_leak_l12": machine_hint_leak,
            "machine_meta_missing": [v for k, v in meta.per_cu.items() if k.endswith(f"/{slug}")],
        }
        rows.append(record)
        crosstab[f"{verdict.get('verdict')}×{bypass['kind'] if bypass else 'no_gate_pass'}"] += 1
        code = verdict.get("failure_code")
        if code == "F8" and machine_hint_leak is not True:
            hints_n = hint_entry["hints"] if hint_entry else 0
            mismatches.append(
                {
                    "slug": slug,
                    "kind": "F8_label_without_machine_hint_leak",
                    "detail": (
                        f"검수 라벨 F8(힌트 정답 누설) ↔ 기계: 이 CU의 힌트 {hints_n}건"
                        + (
                            " — 라벨이 가리킬 힌트가 없다"
                            if hints_n == 0
                            else f" · L1·L2 기계 판정 {machine_hint_leak}"
                        )
                    ),
                }
            )
        if machine_hint_leak is True and code != "F8":
            mismatches.append(
                {
                    "slug": slug,
                    "kind": "machine_hint_leak_without_F8",
                    "detail": f"기계: L1·L2 힌트 누설 ↔ 검수 라벨 {verdict.get('verdict')}/{code}",
                }
            )
        if verdict.get("verdict") == "approved" and bypass and bypass.get("bypassed") is True:
            mismatches.append(
                {
                    "slug": slug,
                    "kind": "approved_with_bypassed_verification",
                    "detail": "검수 무수정 승인 ↔ 기계: 검산식이 정답 재진술(검증 우회)",
                }
            )
    return {
        "performed": True,
        "verdict_rows": len(rows),
        "crosstab_verdict_x_bypass": dict(sorted(crosstab.items())),
        "mismatches": mismatches,
        "rows": rows,
    }


def _exit_code(
    round_input: RoundInput, gate: AutoGateMeasure, hint: HintLeakMeasure, meta: MetaMeasure
) -> int:
    """종료 코드(모듈 docstring) — 입력 실패 > 위반 > 미측정 > 통과 순."""
    if round_input.errors or gate.errors:
        return EXIT_UNMEASURED
    if hint.status == "FAIL" or meta.status == "FAIL":
        return EXIT_VIOLATION
    if not gate.measured or hint.status != "PASS" or meta.status != "PASS":
        return EXIT_UNMEASURED
    return EXIT_PASS


def build_report(
    round_input: RoundInput, hints: Sequence[Hint], *, hint_inputs: int, hint_errors: Sequence[str]
) -> dict[str, Any]:
    """세 측정 + 라벨 대조 → 리포트 dict(순수 · I/O 0)."""
    gate = measure_auto_gate(round_input.run_dirs, input_errors=round_input.errors)
    cu_rows = [row for run in round_input.run_dirs for row in run.cu_rows]
    hint = measure_hint_leakage(cu_rows, hints, hint_inputs=hint_inputs, errors=hint_errors)
    meta = measure_meta(round_input.run_dirs, input_errors=round_input.errors)
    crosscheck = _label_crosscheck(round_input.verdict_rows, gate, hint, meta)
    exit_code = _exit_code(round_input, gate, hint, meta)
    return {
        "round": round_input.round_id,
        "runs_root": round_input.runs_root,
        "run_dirs": [run.name for run in round_input.run_dirs],
        "verdicts_path": round_input.verdicts_path,
        "input_errors": list(round_input.errors),
        "auto_gate": gate.to_json(),
        "hint_leak": hint.to_json(),
        "meta": meta.to_json(),
        "label_crosscheck": crosscheck,
        "exit_code": exit_code,
    }


def _j(value: object) -> str:
    """판정 줄용 JSON(키 정렬·한글 그대로)."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _fmt(value: float | None) -> str:
    return "None" if value is None else f"{value:.4f}"


def render_lines(report: Mapping[str, Any]) -> list[str]:
    """판정 줄 KEY=VALUE(사람·셸이 같은 줄을 읽는다)."""
    gate = report["auto_gate"]
    hint = report["hint_leak"]
    meta = report["meta"]
    cross = report["label_crosscheck"]
    verdict = {0: "PASS", 1: "FAIL", 2: "UNMEASURED"}[report["exit_code"]]
    lines = [
        f"ROUND={report['round']}",
        f"RUN_DIRS={','.join(report['run_dirs'])}",
        f"INPUT_ERRORS={len(report['input_errors'])}",
        f"GATE_ATTEMPTS={gate['attempts']}",
        f"GATE_GENERATION_FAILED={gate['generation_failed']}",
        f"GATE_EVALUATED={gate['evaluated']}",
        f"GATE_STATUS_COUNTS={_j(gate['status_counts'])}",
        f"GATE_PASS_RAW={gate['passed_raw']}",
        f"GATE_PASS_BYPASSED={gate['bypassed']}",
        f"GATE_PASS_BYPASS_KINDS={_j(gate['bypass_kinds'])}",
        f"GATE_PASS_RECOMPUTED={gate['recomputed']}",
        f"GATE_PASS_UNDECIDED={gate['bypass_undecided']}",
        f"AUTO_GATE_PASS_RATE_RAW={_fmt(gate['rate_raw'])}",
        f"AUTO_GATE_PASS_RATE={_fmt(gate['rate'])}",
        f"AUTO_GATE_PASS_RATE_WILSON_LOWER_95={_fmt(gate['wilson_lower_95'])}",
        f"ATTEMPT_PASS_RATE={_fmt(gate['attempt_rate'])}",
        f"AUTO_GATE_MEASURED={gate['measured']}",
        f"HINT_INPUTS={hint['hint_inputs']}",
        f"HINT_CU_TOTAL={hint['cu_total']}",
        f"HINT_CU_WITHOUT_HINTS={hint['cu_without_hints']}",
        f"HINT_TOTAL={hint['hints_total']}",
        f"HINT_LEAKED_L12={hint['leaked_l12']}",
        f"HINT_UNDECIDED_L12={hint['undecided_l12']}",
        f"HINT_LEAKED_L3={hint['leaked_l3']}",
        f"HINT_MACHINE_AXIS={hint['status']}",
        f"HINT_SEMANTIC_AXIS={hint['semantic_axis']}",
        f"META_CU_TOTAL={meta['cu_total']}",
        f"META_CU_MISSING={meta['cu_missing']}",
        f"META_MISSING_BY_FIELD={_j(meta['missing_by_field'])}",
        f"META_SEED_NOT_APPLICABLE={_j(meta['seed_not_applicable_by_model'])}",
        f"META_AXIS={meta['status']}",
        f"LABEL_CROSSCHECK={cross['performed']}",
        f"LABEL_MISMATCH={len(cross['mismatches'])}",
        f"MACHINE_VERDICT={verdict}",
        f"EXIT={report['exit_code']}",
    ]
    reasons = [
        ("AUTO_GATE_REASON", gate["reason"]),
        ("HINT_REASON", hint["reason"]),
    ]
    lines.extend(f"{key}={value}" for key, value in reasons if value)
    lines.extend(f"INPUT_ERROR={e}" for e in report["input_errors"])
    lines.extend(f"GATE_ERROR={e}" for e in gate["errors"] if e not in report["input_errors"])
    lines.extend(f"MISMATCH={m['slug']} {m['kind']} — {m['detail']}" for m in cross["mismatches"])
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.ops.g3_content_measures",
        description=(
            "G3 미측정 3항목(자동검증 1차 통과율·힌트 정답 누설·메타 누락)을 저작 회차 산출물에서 "
            "측정한다(EOS-207). exit 0=통과 · 1=위반 · 2=측정 실패/판정 불가."
        ),
    )
    parser.add_argument(
        "--round", required=True, help="회차 접두어(예: eos197-a6 → eos197-a6-* 좌석)"
    )
    parser.add_argument(
        "--runs-root", type=Path, default=None, help="회차 루트(기본 저장소 data/runs)"
    )
    parser.add_argument(
        "--review-dir",
        type=Path,
        default=None,
        help="검수 폴더(기본 <runs-root>/<round>-review · 명시했는데 판정 파일이 없으면 측정 실패)",
    )
    parser.add_argument(
        "--hints-jsonl",
        type=Path,
        action="append",
        default=None,
        help=(
            "hints 표 내보내기(Hint 모델 JSON 1행 1건 · 반복 가능). 없으면 힌트 축은 "
            "측정 대상 부재"
        ),
    )
    parser.add_argument("--json", type=Path, default=None, help="전체 리포트 JSON 저장 경로")
    args = parser.parse_args(argv)

    runs_root = args.runs_root if args.runs_root is not None else default_runs_root()
    round_input = discover_round(runs_root, args.round, review_dir=args.review_dir)
    hint_paths = list(args.hints_jsonl or [])
    hints, hint_errors = load_hints(hint_paths)
    report = build_report(round_input, hints, hint_inputs=len(hint_paths), hint_errors=hint_errors)
    if args.json is not None:
        try:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except OSError as exc:  # 침묵 실패 금지 — 저장 실패는 측정 실패다
            sys.stderr.write(f"리포트 저장 실패 — {type(exc).__name__}\n")
            return EXIT_UNMEASURED
    sys.stdout.write("\n".join(render_lines(report)) + "\n")
    return int(report["exit_code"])


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
