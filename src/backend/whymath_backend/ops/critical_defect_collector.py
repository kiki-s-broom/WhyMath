"""Phase 3 지표 ⑥ Critical Defect 입력 수집기 — 커밋된 회차에서 F-Ⅱ·F-Ⅴ payload 를 만든다 (P3-107).

왜 있나
------
⑥ 은 `ops.validation_scorecard.evaluate_hard_gates` 의 F-Ⅱ·F-Ⅴ 2종을 흡수한다(P3-33). 그런데
`ops.phase3_metrics` 는 그 입력(`content` 4개 키)을 `--hard-gate-input` 으로 **받기만** 했고, 아무도
만들지 않았다. 그래서 P3-17 판정(main `036286a1`)에서 ⑥ 은 '측정 불가(payload 없음)'였다. 이 모듈은
저장소에 이미 커밋된 회차 산출물(`data/runs/`)에서 그 4개 키를 **결정론으로** 만든다.

새 정의를 만들지 않는다 — 입력 원천과 계산은 전부 기존 정본을 그대로 부른다:

  F-Ⅱ  인간 검수를 통과한 CU 의 수학적 오류율 > 2%   (`reviewed_math_errors` / `reviewed_cu_total`)
       · 검수 통과 = `<회차>-review/canary_review_verdicts.jsonl` 의 `review_status == "approved"`
         (판정 `approved`·`approved_with_edit`). 검수 지문
         (`schema.review_timer.review_content_fingerprint`)이 커밋된 CU 와 다르면 **낡은 판정**이라
         세지 않고 따로 센다(검수한 내용이 지금 내용이 아니다).
       · 수학적 오류 = 그 CU 를 `harness.solution_qa.run_solution_qa` 로 다시 검증해 **FAIL** 인 것.
         SymPy 만이 정답·동치의 권위다(CLAUDE.md). 분모는 판정이 난 것(PASS+FAIL)뿐이고,
         **검증 불가(UNVERIFIABLE)는 오류 0 으로 세지 않는다** — 사유 분포를 따로 낸다.
         검사 일부(예: C1 만)를 골라 통과로 세지 않는다 — Solution QA 의 판정 규칙(적용된 검사가
         모두 결정된 문항만 판정)을 그대로 따른다. 골라 쓰면 라벨만 바꿔 지표를 올리는 것이다.
       · 검수자의 실패 코드(F1~F8)는 쓰지 않는다 — 검수가 놓친 오류를 검수 자신의 라벨로 셀 수 없다.
  F-Ⅴ  힌트의 의미적 정답 누설(자동 검사 밖)이 표본 검수에서 ≥ 10%
       (`hint_leak_hits` / `hint_leak_sample`)
       · = `ops.g3_content_measures` 의 **의미 축**(EOS-210 사람 판정 좌석) 의 k / n 그대로.
         입력 = 좌석 폴더의 `cu.hints.jsonl` + `<회차>-review/hint_verdicts.jsonl` +
         `<회차>-review/hint_sample_manifest.json`. 기계 두 축(글자·값)은 '자동 검사' 라서 F-Ⅴ 가
         아니다(F-Ⅴ 문언이 "자동 검사 밖"이다).
       · CU 검수의 F8 라벨은 F-Ⅴ 에 넣지 않는다 — 표본 검수가 아니라 CU 단위 반려 사유다. 건수는
         사실로만 남긴다(두 도구가 어긋나면 사람이 볼 수 있게).

회차 발견(관례 — 하드코딩 회차 목록 없음)
---------------------------------------
`<runs_root>/*-review` 폴더 하나 = 회차 하나(`<회차>` = 폴더 이름에서 `-review` 를 뗀 것).
좌석 폴더는 `ops.g3_content_measures.discover_round` 가 찾는다(`<회차>-*` 중 `cu.jsonl` 을 가진
폴더). 여러 회차의 분자·분모는 더한다(서로 다른 CU 집합이다 — 같은 slug 가 두 회차에 나오면 오류).

상태 — 모른다 ≠ 아니다
--------------------
게이트마다 `measured`(분모 > 0) 또는 `unmeasured`(사유 동반). payload 에는 **measured 인 게이트의
키만** 넣는다 — 키가 없으면 스코어카드가 그 게이트를 '판정 불가'로 내고, ⑥ 은 측정 실패가 된다.
입력 오류(파싱 실패·필수 파일 부재·의미 축 측정 불가)가 한 회차라도 있으면 그 게이트 전체를
`unmeasured` 로 둔다 — 망가진 회차를 빼고 나머지로 판정하면, 하필 그 회차의 결함이 사라진다.

종료 코드
--------
  0  F-Ⅱ·F-Ⅴ 둘 다 measured — payload 완비(판정 PASS/FAIL 은 ⑥ 이 낸다. 이 CLI 는 판정하지 않는다).
  2  1종 이상 unmeasured — 입력 0건·판정 0건·입력 오류. **0건을 통과로 위장하지 않는다.**
  3  실행 오류(회차 루트가 디렉터리가 아님·출력 저장 실패).

결정론 — 같은 입력이면 같은 바이트
---------------------------------
출력 JSON 에 시각·실행 ID·절대 경로를 넣지 않는다. 경로는 `runs_root` 기준 상대 경로, 입력 파일마다
sha256 을 싣는다(어느 바이트를 읽었는지가 출력에 박힌다). 키 정렬·들여쓰기 2·끝 개행 1개.

사용
----
    python -m whymath_backend.ops.critical_defect_collector                 # data/runs · 표만
    python -m whymath_backend.ops.critical_defect_collector --json out.json # 결정론 JSON
    python -m whymath_backend.ops.phase3_metrics --no-db --critical-defect-from-runs   # ⑥ 측정
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from whymath_backend.harness.solution_qa import CheckState, Verdict, run_solution_qa
from whymath_backend.ops.g3_content_measures import (
    RoundInput,
    build_report,
    discover_round,
    load_hints,
)
from whymath_backend.ops.hint_human_verdicts import (
    HintHumanVerdict,
    SampleManifest,
    load_manifest,
    load_verdicts,
)
from whymath_backend.ops.provenance_audit import default_runs_root
from whymath_backend.schema.review_timer import review_content_fingerprint

__all__ = [
    "EXIT_COMPLETE",
    "EXIT_RUNTIME_ERROR",
    "EXIT_UNMEASURED",
    "CollectorResult",
    "GateInput",
    "collect",
    "main",
]

EXIT_COMPLETE: Final = 0
EXIT_UNMEASURED: Final = 2
EXIT_RUNTIME_ERROR: Final = 3

SCHEMA_VERSION: Final = "p3-107/1"
STATE_MEASURED: Final = "measured"
STATE_UNMEASURED: Final = "unmeasured"

_REVIEW_SUFFIX: Final = "-review"
_VERDICTS_FILE: Final = "canary_review_verdicts.jsonl"
_HINT_VERDICTS_FILE: Final = "hint_verdicts.jsonl"
_MANIFEST_FILE: Final = "hint_sample_manifest.json"
_HINTS_FILE: Final = "cu.hints.jsonl"
_CU_FILE: Final = "cu.jsonl"
#: 검수 통과 — `review_status` 는 검수 CLI 가 판정(approved·approved_with_edit)을 접어
#: 각인한 값이다.
_PASSED_STATUS: Final = "approved"
#: 의미 축이 '잰' 상태 — 이 둘만 k/n 을 낸다.
#: NOT_MEASURED 는 표본 미제출, NOT_MEASURABLE 은 측정 실패.
_SEMANTIC_MEASURED: Final = frozenset({"PASS", "FAIL"})
_SEMANTIC_NOT_SUBMITTED: Final = "NOT_MEASURED"
_F8: Final = "F8"


# ──────────────────────────────────────────────────────────────────────────
# 결과 형
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class GateInput:
    """흡수 게이트 1종의 입력 — measured 면 hits/trials, unmeasured 면 사유."""

    code: str
    state: str
    hits: int
    trials: int
    reason: str

    @property
    def measured(self) -> bool:
        return self.state == STATE_MEASURED

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "state": self.state,
            "hits": self.hits,
            "trials": self.trials,
            "reason": self.reason,
        }


@dataclass
class RoundSurvey:
    """회차 1개의 실측 — 원천별 건수를 0건까지 그대로 남긴다."""

    round_id: str
    run_dirs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # F-Ⅱ
    f2_verdict_file: bool = False
    f2_verdict_rows: int = 0
    f2_passed: int = 0
    f2_stale: int = 0
    f2_pass: int = 0
    f2_fail: int = 0
    f2_unverifiable: int = 0
    f2_unverifiable_reasons: dict[str, int] = field(default_factory=dict)
    f2_fail_slugs: list[str] = field(default_factory=list)
    f2_errors: list[str] = field(default_factory=list)
    cu_review_f8_labels: int = 0
    # F-Ⅴ
    f5_manifest_file: bool = False
    f5_hint_files: int = 0
    f5_semantic_status: str | None = None
    f5_sample_id: str | None = None
    f5_n: int = 0
    f5_k: int = 0
    f5_errors: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "round": self.round_id,
            "run_dirs": list(self.run_dirs),
            "errors": list(self.errors),
            "f2": {
                "verdict_file": self.f2_verdict_file,
                "verdict_rows": self.f2_verdict_rows,
                "reviewed_passed": self.f2_passed,
                "stale_fingerprint": self.f2_stale,
                "solution_qa_pass": self.f2_pass,
                "solution_qa_fail": self.f2_fail,
                "solution_qa_unverifiable": self.f2_unverifiable,
                "unverifiable_reasons": dict(sorted(self.f2_unverifiable_reasons.items())),
                "fail_slugs": sorted(self.f2_fail_slugs),
                "errors": list(self.f2_errors),
                "cu_review_f8_labels_not_counted": self.cu_review_f8_labels,
            },
            "f5": {
                "manifest_file": self.f5_manifest_file,
                "hint_files": self.f5_hint_files,
                "semantic_status": self.f5_semantic_status,
                "sample_id": self.f5_sample_id,
                "n": self.f5_n,
                "k": self.f5_k,
                "errors": list(self.f5_errors),
            },
        }


@dataclass(frozen=True)
class CollectorResult:
    """수집 결과 — payload 와 그 근거(회차별 실측·입력 지문)."""

    rounds: tuple[RoundSurvey, ...]
    f2: GateInput
    f5: GateInput
    sources: tuple[tuple[str, str], ...]
    errors: tuple[str, ...]
    runtime_error: str | None = None

    def payload(self) -> dict[str, Any]:
        """스코어카드 입력 조각 — measured 인 게이트의 키만 넣는다(키 부재 = 판정 불가)."""
        content: dict[str, Any] = {}
        if self.f2.measured:
            content["reviewed_math_errors"] = self.f2.hits
            content["reviewed_cu_total"] = self.f2.trials
        if self.f5.measured:
            content["hint_leak_hits"] = self.f5.hits
            content["hint_leak_sample"] = self.f5.trials
        return {"content": content}

    @property
    def exit_code(self) -> int:
        if self.runtime_error is not None:
            return EXIT_RUNTIME_ERROR
        return EXIT_COMPLETE if self.f2.measured and self.f5.measured else EXIT_UNMEASURED

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "exit_code": self.exit_code,
            "runtime_error": self.runtime_error,
            "gates": {"F-Ⅱ": self.f2.to_json(), "F-Ⅴ": self.f5.to_json()},
            "payload": self.payload(),
            "rounds": [r.to_json() for r in self.rounds],
            "errors": list(self.errors),
            "sources": [{"path": p, "sha256": h} for p, h in self.sources],
        }

    def dumps(self) -> str:
        """결정론 직렬화 — 같은 입력이면 같은 바이트."""
        return json.dumps(self.to_json(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    def summary_facts(self) -> tuple[tuple[str, str], ...]:
        """phase3_metrics ⑥ 출력에 붙일 사실 줄(원천·건수·사유)."""
        facts: list[tuple[str, str]] = [
            (
                "수집기",
                f"critical_defect_collector · 회차 {len(self.rounds)}개"
                f"({', '.join(r.round_id for r in self.rounds) or '없음'}) · exit {self.exit_code}",
            )
        ]
        for gate in (self.f2, self.f5):
            facts.append((f"{gate.code} 입력", f"{gate.state} · {gate.reason}"))
        f8 = sum(r.cu_review_f8_labels for r in self.rounds)
        if f8:
            facts.append(
                (
                    "F8 라벨(F-Ⅴ 미산입)",
                    f"CU 검수 F8 {f8}건 — 표본 검수가 아닌 CU 단위 반려 사유라 F-Ⅴ 에 넣지 않는다",
                )
            )
        if self.runtime_error:
            facts.append(("수집기 실행 오류", self.runtime_error))
        return tuple(facts)


# ──────────────────────────────────────────────────────────────────────────
# 입력 지문
# ──────────────────────────────────────────────────────────────────────────
def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:  # 루트 밖(명시 입력) — 이름만 남긴다(절대 경로는 기계마다 다르다)
        return path.name


# ──────────────────────────────────────────────────────────────────────────
# F-Ⅱ — 검수 통과 CU × Solution QA 재검증
# ──────────────────────────────────────────────────────────────────────────
def _survey_f2(survey: RoundSurvey, round_input: RoundInput) -> None:
    rows = round_input.verdict_rows
    if rows is None:
        return
    survey.f2_verdict_file = True
    survey.f2_verdict_rows = len(rows)
    cu_by_slug: dict[str, Mapping[str, Any]] = {}
    for run in round_input.run_dirs:
        for row in run.cu_rows:
            slug = str(row.get("slug"))
            if slug in cu_by_slug:
                survey.f2_errors.append(f"CU slug 중복 {slug}")
            cu_by_slug[slug] = row
    seen: set[str] = set()
    passed: list[Mapping[str, Any]] = []
    for row in rows:
        slug = str(row.get("slug"))
        if slug in seen:
            survey.f2_errors.append(f"검수 판정 slug 중복 {slug}")
            continue
        seen.add(slug)
        if row.get("failure_code") == _F8:
            survey.cu_review_f8_labels += 1
        if row.get("review_status") != _PASSED_STATUS:
            continue
        record = cu_by_slug.get(slug)
        if record is None:
            survey.f2_errors.append(f"검수 통과 판정이 가리킬 CU 없음 {slug}")
            continue
        try:
            fingerprint = review_content_fingerprint(record)
        except TypeError as exc:  # 직렬화 불가 값 — 지문을 만들 수 없다(침묵 금지)
            survey.f2_errors.append(f"지문 계산 실패 {slug} ({type(exc).__name__})")
            continue
        survey.f2_passed += 1
        if fingerprint != row.get("content_fingerprint"):
            survey.f2_stale += 1
            continue
        passed.append(record)
    if not passed:
        return
    report = run_solution_qa(passed)
    reasons: Counter[str] = Counter()
    for item in report.items:
        if item.verdict is Verdict.PASS:
            survey.f2_pass += 1
        elif item.verdict is Verdict.FAIL:
            survey.f2_fail += 1
            survey.f2_fail_slugs.append(item.ident)
        else:
            survey.f2_unverifiable += 1
            for cid, res in item.blocking(CheckState.UNVERIFIABLE):
                reasons[f"{cid}:{res.code}"] += 1
    survey.f2_unverifiable_reasons = dict(reasons)


# ──────────────────────────────────────────────────────────────────────────
# F-Ⅴ — 의미 축(사람 표본) k / n
# ──────────────────────────────────────────────────────────────────────────
def _survey_f5(
    survey: RoundSurvey,
    round_input: RoundInput,
    review_dir: Path,
    hint_paths: Sequence[Path],
) -> None:
    manifest_path = review_dir / _MANIFEST_FILE
    if not manifest_path.is_file():
        return
    survey.f5_manifest_file = True
    survey.f5_hint_files = len(hint_paths)
    hints, hint_errors = load_hints(list(hint_paths))
    human_sources: list[tuple[str, Sequence[HintHumanVerdict]]] = []
    human_errors: list[str] = []
    verdict_path = review_dir / _HINT_VERDICTS_FILE
    if verdict_path.is_file():
        rows, errors = load_verdicts(verdict_path)
        human_sources.append((verdict_path.name, rows))
        human_errors.extend(errors)
    manifest: SampleManifest | None
    manifest, manifest_errors = load_manifest(manifest_path)
    report = build_report(
        round_input,
        hints,
        hint_inputs=len(hint_paths),
        hint_errors=hint_errors,
        human_verdict_sources=human_sources,
        human_errors=human_errors,
        manifest=manifest,
        manifest_requested=True,
        manifest_errors=manifest_errors,
    )
    semantic = report["hint_leak"]["semantic"]
    status = str(report["hint_leak"]["semantic_axis"])
    survey.f5_semantic_status = status
    survey.f5_sample_id = semantic.get("sample_id")
    survey.f5_errors.extend(str(e) for e in semantic.get("errors", []))
    if status in _SEMANTIC_MEASURED:
        survey.f5_n = int(semantic["n"])
        survey.f5_k = int(semantic["k"])
    elif status != _SEMANTIC_NOT_SUBMITTED:
        # 표본은 냈는데 잴 수 없었다 — 오류로 올린다(빼고 판정하면 그 표본의 누설이 사라진다).
        survey.f5_errors.append(f"의미 축 {status}: {report['hint_leak'].get('reason', '')}")


# ──────────────────────────────────────────────────────────────────────────
# 집계
# ──────────────────────────────────────────────────────────────────────────
def _aggregate_f2(rounds: Sequence[RoundSurvey]) -> GateInput:
    code = "F-Ⅱ"
    broken = [f"{r.round_id}: {e}" for r in rounds for e in (*r.errors, *r.f2_errors)]
    if broken:
        return GateInput(code, STATE_UNMEASURED, 0, 0, "입력 오류 — " + " · ".join(broken))
    with_file = [r for r in rounds if r.f2_verdict_file]
    if not with_file:
        return GateInput(
            code,
            STATE_UNMEASURED,
            0,
            0,
            f"원천 0건 — 회차 {len(rounds)}개 중 검수 판정 파일({_VERDICTS_FILE})을 가진 회차 0개",
        )
    hits = sum(r.f2_fail for r in with_file)
    trials = sum(r.f2_pass + r.f2_fail for r in with_file)
    detail = " · ".join(
        f"{r.round_id}: 검수 통과 {r.f2_passed}(낡은 지문 {r.f2_stale}) → SymPy 재검증 "
        f"PASS {r.f2_pass} · FAIL {r.f2_fail} · 검증 불가 {r.f2_unverifiable}"
        + (
            "(" + ", ".join(f"{k} {v}" for k, v in sorted(r.f2_unverifiable_reasons.items())) + ")"
            if r.f2_unverifiable_reasons
            else ""
        )
        for r in with_file
    )
    if trials == 0:
        return GateInput(
            code,
            STATE_UNMEASURED,
            0,
            0,
            f"판정 0건 — 검증 불가를 오류 0으로 세지 않는다 · {detail}",
        )
    return GateInput(code, STATE_MEASURED, hits, trials, f"{hits}/{trials} · {detail}")


def _aggregate_f5(rounds: Sequence[RoundSurvey]) -> GateInput:
    code = "F-Ⅴ"
    broken = [f"{r.round_id}: {e}" for r in rounds for e in (*r.errors, *r.f5_errors)]
    if broken:
        return GateInput(code, STATE_UNMEASURED, 0, 0, "입력 오류 — " + " · ".join(broken))
    with_manifest = [r for r in rounds if r.f5_manifest_file]
    if not with_manifest:
        return GateInput(
            code,
            STATE_UNMEASURED,
            0,
            0,
            f"원천 0건 — 회차 {len(rounds)}개 중 힌트 표본 매니페스트({_MANIFEST_FILE})를 "
            "가진 회차 0개",
        )
    hits = sum(r.f5_k for r in with_manifest)
    trials = sum(r.f5_n for r in with_manifest)
    detail = " · ".join(
        f"{r.round_id}: 의미 축 {r.f5_semantic_status} 표본 {r.f5_sample_id} n={r.f5_n} k={r.f5_k}"
        for r in with_manifest
    )
    if trials == 0:
        return GateInput(code, STATE_UNMEASURED, 0, 0, f"표본 0건 — {detail}")
    return GateInput(code, STATE_MEASURED, hits, trials, f"{hits}/{trials} · {detail}")


def _discover_review_dirs(runs_root: Path) -> list[Path]:
    return sorted(
        p
        for p in runs_root.iterdir()
        if p.is_dir() and p.name.endswith(_REVIEW_SUFFIX) and len(p.name) > len(_REVIEW_SUFFIX)
    )


def collect(runs_root: Path | None = None) -> CollectorResult:
    """`runs_root`(기본 `data/runs`)의 회차 전부 → F-Ⅱ·F-Ⅴ 입력. I/O 는 읽기만 한다."""
    root = runs_root if runs_root is not None else default_runs_root()
    if not root.is_dir():
        reason = f"회차 루트가 디렉터리가 아니다({root.name})"
        empty: tuple[RoundSurvey, ...] = ()
        return CollectorResult(
            rounds=empty,
            f2=GateInput("F-Ⅱ", STATE_UNMEASURED, 0, 0, reason),
            f5=GateInput("F-Ⅴ", STATE_UNMEASURED, 0, 0, reason),
            sources=(),
            errors=(reason,),
            runtime_error=reason,
        )
    rounds: list[RoundSurvey] = []
    sources: dict[str, str] = {}
    all_slugs: dict[str, str] = {}
    for review_dir in _discover_review_dirs(root):
        round_id = review_dir.name[: -len(_REVIEW_SUFFIX)]
        survey = RoundSurvey(round_id=round_id)
        round_input = discover_round(root, round_id, review_dir=review_dir)
        survey.run_dirs = [run.name for run in round_input.run_dirs]
        # `--review-dir` 를 준 호출이라 판정 파일 부재가 오류로 올라온다 — 여기서는 '원천 없음'이다.
        survey.errors = [e for e in round_input.errors if not e.startswith("--review-dir를 줬는데")]
        for run in round_input.run_dirs:
            for row in run.cu_rows:
                slug = str(row.get("slug"))
                other = all_slugs.setdefault(slug, round_id)
                if other != round_id:
                    survey.errors.append(f"CU {slug} 가 회차 {other} 에도 있다(이중 계상)")
        hint_paths = sorted(
            root / name / _HINTS_FILE
            for name in survey.run_dirs
            if (root / name / _HINTS_FILE).is_file()
        )
        read_paths = [root / name / _CU_FILE for name in survey.run_dirs]
        read_paths.extend(hint_paths)
        read_paths.extend(
            review_dir / f for f in (_VERDICTS_FILE, _HINT_VERDICTS_FILE, _MANIFEST_FILE)
        )
        for path in read_paths:
            if path.is_file():
                sources[_rel(path, root)] = _sha256(path)
        _survey_f2(survey, round_input)
        _survey_f5(survey, round_input, review_dir, hint_paths)
        rounds.append(survey)
    errors = tuple(
        f"{r.round_id}: {e}" for r in rounds for e in (*r.errors, *r.f2_errors, *r.f5_errors)
    )
    return CollectorResult(
        rounds=tuple(rounds),
        f2=_aggregate_f2(rounds),
        f5=_aggregate_f5(rounds),
        sources=tuple(sorted(sources.items())),
        errors=errors,
    )


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def render_lines(result: CollectorResult) -> list[str]:
    lines = [
        "[Phase 3 ⑥ Critical Defect 입력 수집기 — P3-107]",
        f"  회차 {len(result.rounds)}개 · 입력 파일 {len(result.sources)}개"
        f" · exit {result.exit_code}",
    ]
    for gate in (result.f2, result.f5):
        lines.append(f"  {gate.code}: {gate.state} — {gate.reason}")
    for label, value in result.summary_facts()[3:]:
        lines.append(f"  {label}: {value}")
    lines.append("  payload: " + json.dumps(result.payload(), ensure_ascii=False, sort_keys=True))
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.ops.critical_defect_collector",
        description="Phase 3 지표 ⑥ 입력(F-Ⅱ·F-Ⅴ) 수집 — 커밋된 회차 산출물에서 결정론으로",
    )
    parser.add_argument("--runs-root", type=Path, default=None, help="회차 루트(기본 data/runs)")
    parser.add_argument("--json", type=Path, default=None, help="결정론 JSON 저장 경로")
    args = parser.parse_args(argv)
    result = collect(args.runs_root)
    if args.json is not None:
        try:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(result.dumps(), encoding="utf-8")
        except OSError as exc:  # 침묵 실패 금지 — 저장 실패는 실행 오류다
            sys.stderr.write(f"[critical_defect_collector] JSON 저장 실패 — {type(exc).__name__}\n")
            return EXIT_RUNTIME_ERROR
    sys.stdout.write("\n".join(render_lines(result)) + "\n")
    return result.exit_code


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
