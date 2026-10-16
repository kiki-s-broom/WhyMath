"""오답 → 오개념 후보 → 교정 전략 **전 구간 계측기** — 핵심 오개념마다 끝까지 이어지는지 잰다
(P3-06).

CLAUDE.md "지표는 사람이 세지 않는다 — CLI가 계산하고 exit code로 판정한다". 이 도구가 재는 것은
대표 과정(P3-01 동결)의 핵심 오개념 각각에 대해:

  ① **좌석** — 런타임 후보 id(kebab)를 크로스워크가 낸다(없으면 후보를 낼 수 없다).
  ② **오답 → 후보** — 두 입구 모두: (가) 서명 규칙의 `wrong` 픽스처(질문 + 학생 답) (나) 문항은행이
     그 오개념으로 표시한 오답 보기(선지 인덱스). 후보가 나오고 신뢰도가 게이트를 넘는가.
  ③ **오탐** — 서명 규칙의 `not_wrong` 픽스처(정답·타 오개념 답)에서 후보가 나오지 **않는가**.
  ④ **후보 → 교정 전략** — 사다리 세 칸(교정 설명·쉬운 문항·선수 개념) 모두 `ADVICE`이고, 쉬운 문항
     선택 조건이 승인 문항에 닿으며, 선수 개념 기준 개념에 선수 원자가 있는가.

재구현 0 — 서빙 함수 그대로
────────────────────────────────────────────────────────────────────────────
②는 서빙이 쓰는 `api._attempt_misconception_scan.scan_attempt_misconceptions`를 **그대로** 부른다.
DB 대신 문항 한 건의 `question_text`·`distractor_map`만 돌려주는 최소 세션을 넘길 뿐이다. 계측기가
따로 채널 합류를 구현하면 서빙과 어긋나도 초록이 나오는 사본이 되기 때문이다(CLAUDE.md "정본화를
집행으로 착각한 완료 선언 금지"의 반대 방향 — 측정이 실제 경로를 지나야 한다).

판정과 종료 코드
────────────────────────────────────────────────────────────────────────────
오개념 한 건의 상태는 셋이다:
  · `PASS`    — 좌석이 있고 ②③④가 모두 성립.
  · `NO_SEAT` — 크로스워크가 kebab을 내지 않는다(게이트 `G-misc40-unseated-concepts-disposition`
                처분 대기). **후보를 낼 수 없다**는 사실의 보고이며 PASS가 아니다.
  · `FAIL`    — 좌석은 있는데 ②③④ 중 하나가 깨졌다.
종료 코드: `FAIL`이 하나라도 있으면 1. `NO_SEAT`는 기본으로는 종료 코드를 바꾸지 않되 보고에
드러내고,
`--require-all`이면 1이다("12개 각각" 완료 판정은 `--require-all`이 0일 때만 충족이다). 측정 자체가
불가능하면(규칙표 적재 실패 등) 3 — "0건 통과"로 위장하지 않는다.

학생 원문·정답은 출력에 싣지 않는다(코퍼스 문항 id와 규칙 id, 건수만).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from whymath_backend.l1.misconception.wrong_answer_tables import (
    kebab_for_mis_id,
    load_remediation_spec,
    load_signature_spec,
    mis_ids_for_kebab,
    remediation_row_for_mis_id,
)
from whymath_backend.l1.standards.phase3_coverage import (
    load_corpus,
    prerequisite_sources_of,
)
from whymath_backend.l1.standards.phase3_scope import (
    ScopeSpec,
    load_reference_index,
    load_scope_spec,
)
from whymath_backend.l2.remediation_policy import (
    REMEDIATION_POLICY_V1,
    EscalationRung,
)
from whymath_backend.l4.misconception.remediation_advice import (
    AdviceOutcome,
    advise_for_rung,
)
from whymath_backend.schema.assessment_evidence import MisconceptionCandidate
from whymath_backend.schema.verification_capabilities import AttemptMisconceptionDetector

__all__ = [
    "BankProblem",
    "MisconceptionRow",
    "Report",
    "build_report",
    "iter_approved_problems",
    "main",
    "trace_attempt",
]

_REPO_ROOT = Path(__file__).resolve().parents[4]
_ACTIVE_RUNGS: tuple[EscalationRung, ...] = tuple(
    rung for _, rung in reversed(REMEDIATION_POLICY_V1.escalation_ladder)
)

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_UNMEASURABLE = 3


@dataclass(frozen=True, slots=True)
class BankProblem:
    """승인 문항 1건 — 계측에 필요한 필드만."""

    problem_id: str
    bank: str
    question_text: str
    answer: str
    choices: tuple[str, ...]
    distractor_map: tuple[dict[str, Any], ...]
    achievement_codes: tuple[str, ...]
    difficulty: float | None


def iter_approved_problems(root: Path | None = None) -> Iterator[BankProblem]:
    """`problem_bank_*/problems.jsonl`의 승인(approved) 문항 전량 — 디렉터리 순서로 결정론.

    0건이면 호출자가 실패로 다룬다(`build_report`가 검사) — 빈 코퍼스를 통과로 읽지 않는다.
    """
    base = (root or _REPO_ROOT) / "data" / "corpus"
    for path in sorted(base.glob("problem_bank_*/problems.jsonl")):
        bank = path.parent.name.removeprefix("problem_bank_")
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("review_status") != "approved":
                continue
            difficulty = row.get("difficulty_overall")
            yield BankProblem(
                problem_id=str(row["problem_id"]),
                bank=bank,
                question_text=str(row["question_text"]),
                answer=str(row["answer"]),
                choices=tuple(str(c) for c in (row.get("choices") or ())),
                distractor_map=tuple(row.get("distractor_map") or ()),
                achievement_codes=tuple(row.get("achievement_standard_codes") or ()),
                difficulty=None if difficulty is None else float(difficulty),
            )


class _ProblemSession:
    """서빙 훑기 함수가 쓰는 `session.scalar(select(Problem.<col>)…)` 두 가지만 흉내 낸다.

    어느 열을 고르는지는 문장 문자열이 아니라 SQLAlchemy가 계산한 `column_descriptions`로 읽는다
    (열 이름 문자열 부분일치는 표기 변형에서 뚫린다). 모르는 열이 오면 예외 — 서빙 함수가 새 열을
    읽기 시작했다면 이 계측기가 조용히 `None`을 돌려주며 초록을 내지 않게 한다.
    """

    def __init__(self, problem: BankProblem) -> None:
        self._problem = problem

    async def scalar(self, stmt: Any) -> Any:
        column = stmt.column_descriptions[0]["name"]
        if column == "distractor_map":
            return list(self._problem.distractor_map)
        if column == "question_text":
            return self._problem.question_text
        raise RuntimeError(f"계측기가 모르는 열을 서빙 함수가 읽었다: {column!r}")


async def trace_attempt(
    problem: BankProblem,
    *,
    answer: str | None,
    selected_choice_index: int | None,
    detector: AttemptMisconceptionDetector,
) -> tuple[MisconceptionCandidate, ...]:
    """서빙 훑기 함수로 후보를 낸다 — 후보만 돌려준다(상태 3상태는 `scan`이 따로 든다)."""
    from whymath_backend.api._attempt_misconception_scan import scan_attempt_misconceptions

    result = await scan_attempt_misconceptions(
        _ProblemSession(problem),  # type: ignore[arg-type]  # 두 열만 읽는 최소 대역
        detector,
        problem_id=uuid.UUID(problem.problem_id),
        answer=answer,
        selected_choice_index=selected_choice_index,
    )
    return result.candidates


# ── 오개념 한 건의 계측 ────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class MisconceptionRow:
    """핵심 오개념 1건의 전 구간 상태."""

    mis_id: str
    concept_code: str
    kebab_id: str | None
    shared_with: tuple[str, ...] = ()
    rule_ids: tuple[str, ...] = ()
    signature_wrong: tuple[int, int] = (0, 0)  # (후보가 난 수, 전체)
    signature_clean: tuple[int, int] = (0, 0)  # (후보가 안 난 수, 전체)
    choice_tagged_problems: int = 0
    choice_reproduced: tuple[int, int] = (0, 0)  # (후보가 난 보기 수, 표시된 보기 수)
    signature_vs_oracle: tuple[int, int] = (
        0,
        0,
    )  # 서명 독법만으로 (재현한 보기 수, 표시된 보기 수)
    direct_mis_id_tags: int = 0
    min_confidence: float | None = None
    rungs_ready: dict[str, bool] = field(default_factory=dict)
    easier_matches: int | None = None
    prerequisite_atoms: int | None = None
    problems: list[str] = field(default_factory=list)
    status: str = "FAIL"


@dataclass(slots=True)
class Report:
    """전 구간 계측 결과."""

    rows: list[MisconceptionRow]
    seated_total: int
    seated_pass: int
    gaps: list[str]
    failures: list[str]
    scanned_problems: int
    false_positive_sweep: tuple[int, int]  # (후보가 난 정답 수, 정답을 훑은 수)
    swept: bool = True  # False면 오탐 전수 점검을 건너뛴 것 — 0/0을 '오탐 0건'으로 읽으면 안 된다

    @property
    def exit_code(self) -> int:
        return EXIT_FAIL if self.failures else EXIT_OK


async def _measure_signature(
    row: MisconceptionRow,
    problems: dict[str, BankProblem],
    detector: AttemptMisconceptionDetector,
    confidences: list[float],
) -> None:
    """서명 규칙 픽스처를 서빙 경로(텍스트 채널)로 통과시킨다."""
    assert row.kebab_id is not None
    spec = load_signature_spec()
    rules = [r for r in spec.rules if row.mis_id in r.mis_ids]
    row.rule_ids = tuple(r.rule_id for r in rules)
    wrong_hit = wrong_total = clean_ok = clean_total = 0
    for rule in rules:
        for fixture in rule.fixtures.wrong:
            problem = problems.get(fixture.problem_id)
            wrong_total += 1
            if problem is None:
                row.problems.append(
                    f"{rule.rule_id}: 픽스처 문항 {fixture.problem_id}가 코퍼스에 없다"
                )
                continue
            candidates = await trace_attempt(
                problem, answer=fixture.answer, selected_choice_index=None, detector=detector
            )
            hit = [c for c in candidates if c.misconception_id == row.kebab_id]
            if hit:
                wrong_hit += 1
                confidences.append(hit[0].confidence)
            else:
                row.problems.append(f"{rule.rule_id}: 오답 픽스처에서 후보가 나오지 않았다")
        for fixture in rule.fixtures.not_wrong:
            problem = problems.get(fixture.problem_id)
            clean_total += 1
            if problem is None:
                row.problems.append(
                    f"{rule.rule_id}: 픽스처 문항 {fixture.problem_id}가 코퍼스에 없다"
                )
                continue
            candidates = await trace_attempt(
                problem, answer=fixture.answer, selected_choice_index=None, detector=detector
            )
            if any(c.misconception_id == row.kebab_id for c in candidates):
                row.problems.append(f"{rule.rule_id}: 잡으면 안 되는 답에서 후보가 나왔다(오탐)")
            else:
                clean_ok += 1
    row.signature_wrong = (wrong_hit, wrong_total)
    row.signature_clean = (clean_ok, clean_total)


async def _measure_choices(
    row: MisconceptionRow,
    problems: list[BankProblem],
    detector: AttemptMisconceptionDetector,
    confidences: list[float],
) -> None:
    """문항은행이 이 오개념으로 표시한 오답 보기를 서빙 경로(선지 + 텍스트 채널)로 통과시킨다."""
    assert row.kebab_id is not None
    tagged = reproduced = signature_only = 0
    touched: set[str] = set()
    for problem in problems:
        for entry in problem.distractor_map:
            if entry.get("misconception_id") != row.kebab_id:
                continue
            index = int(entry["choice_index"])
            tagged += 1
            touched.add(problem.problem_id)
            candidates = await trace_attempt(
                problem,
                answer=problem.choices[index],
                selected_choice_index=index,
                detector=detector,
            )
            hit = [c for c in candidates if c.misconception_id == row.kebab_id]
            if hit:
                reproduced += 1
                confidences.append(hit[0].confidence)
            # 선지 채널이 보기 표시를 그대로 읽는 것과 **독립으로**, 서명 독법이 같은 오답 값만 보고
            # 후보를 내는가 — 문항은행의 보기 표시는 별도 생성기가 만든 독립 오라클이다.
            by_signature = await trace_attempt(
                problem,
                answer=problem.choices[index],
                selected_choice_index=None,
                detector=detector,
            )
            if any(c.misconception_id == row.kebab_id for c in by_signature):
                signature_only += 1
    row.choice_tagged_problems = len(touched)
    row.choice_reproduced = (reproduced, tagged)
    row.signature_vs_oracle = (signature_only, tagged)


def _measure_strategy(
    row: MisconceptionRow, spec: ScopeSpec, problems: list[BankProblem], coverage_ctx: Any
) -> None:
    """교정 전략 — 사다리 세 칸이 ADVICE이고 선택 조건이 코퍼스에 닿는가."""
    assert row.kebab_id is not None
    table_row = remediation_row_for_mis_id(row.mis_id)
    for rung in _ACTIVE_RUNGS:
        advice = advise_for_rung(row.kebab_id, rung)
        ready = advice.outcome is AdviceOutcome.ADVICE
        row.rungs_ready[rung.value] = ready
        if not ready:
            row.problems.append(f"사다리 {rung.value}: 교정 전략이 {advice.outcome.value}")
    if table_row is None:
        # 같은 kebab의 다른 M-id(M0672↔M0075) 행으로 대신하는 경우를 뺀 순수 부재.
        row.problems.append(f"교정표에 {row.mis_id} 행이 없다")
        return
    selector = table_row.easier_problem
    row.easier_matches = sum(
        1
        for p in problems
        if selector.concept_code in p.achievement_codes
        and p.difficulty is not None
        and p.difficulty <= selector.max_difficulty
    )
    if row.easier_matches == 0:
        row.problems.append(
            f"쉬운 문항 선택 조건이 승인 문항에 닿지 않는다({selector.concept_code})"
        )
    corpus, index = coverage_ctx
    sources = prerequisite_sources_of(
        spec, index, corpus, table_row.prerequisite_concept.concept_code
    )
    row.prerequisite_atoms = len(sources)
    if not sources:
        row.problems.append(
            f"선수 개념 기준 개념에 선수 원자가 없다({table_row.prerequisite_concept.concept_code})"
        )


async def _false_positive_sweep(
    problems: list[BankProblem], detector: AttemptMisconceptionDetector
) -> tuple[int, int]:
    """모든 승인 문항의 **정답**을 학생 답으로 훑어 후보가 나오는 수를 센다 — 오탐 전수 점검."""
    hits = scanned = 0
    for problem in problems:
        candidates = await trace_attempt(
            problem, answer=problem.answer, selected_choice_index=None, detector=detector
        )
        scanned += 1
        if candidates:
            hits += 1
    return hits, scanned


async def build_report(detector: AttemptMisconceptionDetector, *, sweep: bool = True) -> Report:
    """핵심 오개념 각각의 전 구간 상태를 계측한다. 측정 불가(규칙표·코퍼스 적재 실패)는 예외로
    올린다."""
    spec = load_scope_spec()
    index = load_reference_index(spec)
    corpus = load_corpus(spec)
    problems = list(iter_approved_problems())
    if not problems:
        raise RuntimeError("승인 문항이 0건이다 — 빈 코퍼스는 통과가 아니라 측정 실패다")
    by_id = {p.problem_id: p for p in problems}
    load_signature_spec()
    load_remediation_spec()

    rows: list[MisconceptionRow] = []
    for core in spec.core_misconceptions:
        kebab = kebab_for_mis_id(core.mis_id)
        row = MisconceptionRow(mis_id=core.mis_id, concept_code=core.concept_code, kebab_id=kebab)
        if kebab is not None:
            row.shared_with = tuple(m for m in mis_ids_for_kebab(kebab) if m != core.mis_id)
        # 보기가 M-id를 직접 적은 문항(좌석 없이도 계측기는 '닿았다'로 세는 이음새).
        row.direct_mis_id_tags = sum(
            1
            for p in problems
            for d in p.distractor_map
            if d.get("misconception_id") == core.mis_id
        )
        rows.append(row)

    for row in rows:
        if row.kebab_id is None:
            row.status = "NO_SEAT"
            row.problems.append(
                "크로스워크에 kebab 좌석이 없어 런타임 후보를 낼 수 없다"
                + (
                    f" (문항은행 보기가 M-id를 직접 적은 문항 {row.direct_mis_id_tags}건은 "
                    "서빙이 버린다)"
                    if row.direct_mis_id_tags
                    else ""
                )
            )
            continue
        confidences: list[float] = []
        await _measure_signature(row, by_id, detector, confidences)
        await _measure_choices(row, problems, detector, confidences)
        _measure_strategy(row, spec, problems, (corpus, index))
        row.min_confidence = min(confidences) if confidences else None
        detection_paths = row.signature_wrong[1] + row.choice_reproduced[1]
        if detection_paths == 0:
            row.problems.append("오답 → 후보 입구가 하나도 없다(서명 픽스처 0 · 표시된 보기 0)")
        if row.signature_wrong[0] != row.signature_wrong[1]:
            row.problems.append(
                f"서명 오답 픽스처 {row.signature_wrong[0]}/{row.signature_wrong[1]}만 후보가 났다"
            )
        if row.choice_reproduced[0] != row.choice_reproduced[1]:
            row.problems.append(
                f"표시된 오답 보기 {row.choice_reproduced[0]}/{row.choice_reproduced[1]}만 "
                "후보가 났다"
            )
        if row.signature_clean[0] != row.signature_clean[1]:
            row.problems.append("오탐 픽스처에서 후보가 났다")
        row.status = "FAIL" if row.problems else "PASS"

    fp = await _false_positive_sweep(problems, detector) if sweep else (0, 0)
    seated = [r for r in rows if r.status != "NO_SEAT"]
    failures = [f"{r.mis_id}: {p}" for r in rows if r.status == "FAIL" for p in r.problems]
    if sweep and fp[0]:
        failures.append(f"정답 오탐 전수 점검: 정답 {fp[1]}건 중 {fp[0]}건에서 후보가 났다")
    return Report(
        rows=rows,
        seated_total=len(seated),
        seated_pass=sum(1 for r in seated if r.status == "PASS"),
        gaps=[r.mis_id for r in rows if r.status == "NO_SEAT"],
        failures=failures,
        scanned_problems=len(problems),
        false_positive_sweep=fp,
        swept=sweep,
    )


# ── 출력 ───────────────────────────────────────────────────────────────────────────────────


def to_json(report: Report) -> dict[str, Any]:
    """기계가 읽는 요약 — 학생 원문 없음."""
    return {
        "seated_total": report.seated_total,
        "seated_pass": report.seated_pass,
        "core_total": len(report.rows),
        "gaps": report.gaps,
        "failures": report.failures,
        "scanned_problems": report.scanned_problems,
        "false_positive_sweep": {
            "ran": report.swept,
            "positives": report.false_positive_sweep[0],
            "scanned": report.false_positive_sweep[1],
        },
        "rows": [
            {
                "mis_id": r.mis_id,
                "concept_code": r.concept_code,
                "kebab_id": r.kebab_id,
                "status": r.status,
                "shared_with": list(r.shared_with),
                "rule_ids": list(r.rule_ids),
                "signature_wrong": list(r.signature_wrong),
                "signature_clean": list(r.signature_clean),
                "choice_tagged_problems": r.choice_tagged_problems,
                "choice_reproduced": list(r.choice_reproduced),
                "signature_vs_oracle": list(r.signature_vs_oracle),
                "direct_mis_id_tags": r.direct_mis_id_tags,
                "min_confidence": r.min_confidence,
                "rungs_ready": r.rungs_ready,
                "easier_matches": r.easier_matches,
                "prerequisite_atoms": r.prerequisite_atoms,
                "problems": r.problems,
            }
            for r in report.rows
        ],
    }


def _frac(pair: tuple[int, int]) -> str:
    return f"{pair[0]}/{pair[1]}"


def render(report: Report) -> str:
    """사람이 읽는 표."""
    header = (
        "M-id",
        "상태",
        "kebab",
        "서명오답",
        "서명정상",
        "보기재현",
        "서명↔보기",
        "사다리",
        "쉬운문항",
        "선수원자",
    )
    table: list[tuple[str, ...]] = [header]
    for r in report.rows:
        ready = sum(1 for v in r.rungs_ready.values() if v)
        table.append(
            (
                r.mis_id,
                r.status,
                r.kebab_id or "-",
                _frac(r.signature_wrong),
                _frac(r.signature_clean),
                _frac(r.choice_reproduced),
                _frac(r.signature_vs_oracle),
                f"{ready}/{len(_ACTIVE_RUNGS)}" if r.kebab_id else "-",
                "-" if r.easier_matches is None else str(r.easier_matches),
                "-" if r.prerequisite_atoms is None else str(r.prerequisite_atoms),
            )
        )
    widths = [max(len(row[i]) for row in table) for i in range(len(header))]
    lines = [
        "오답 → 오개념 후보 → 교정 전략 전 구간 (P3-06)",
        f"  핵심 오개념 {len(report.rows)}개 중 좌석 있음 {report.seated_total}개 · "
        f"PASS {report.seated_pass}개 · 좌석 없음(NO_SEAT) {len(report.gaps)}개",
        "",
    ]
    lines += ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) for row in table]
    hits, scanned = report.false_positive_sweep
    if report.swept:
        lines += ["", f"정답 오탐 전수 점검: 승인 문항 {scanned}건의 정답 중 후보가 난 것 {hits}건"]
    else:
        lines += ["", "정답 오탐 전수 점검: 건너뜀(--no-sweep) — 오탐 0건이라는 뜻이 아니다"]
    for r in report.rows:
        for problem in r.problems:
            lines.append(f"  [{r.status}] {r.mis_id}: {problem}")
    return "\n".join(lines)


def _build_detector() -> AttemptMisconceptionDetector:
    """운영과 같은 합성 루트의 기본 탐지기 — 계측기가 어댑터를 이름으로 알지 않는다."""
    from whymath_backend.composition import default_attempt_misconception_detector

    return default_attempt_misconception_detector()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="오답 → 교정 전략 전 구간 계측기 (P3-06)")
    parser.add_argument("--json", action="store_true", help="기계 가독 JSON으로 출력")
    parser.add_argument(
        "--require-all",
        action="store_true",
        help="좌석 없는 핵심 오개념(NO_SEAT)이 하나라도 있으면 종료 코드 1",
    )
    parser.add_argument(
        "--no-sweep", action="store_true", help="정답 오탐 전수 점검을 건너뛴다(빠른 점검용)"
    )
    parser.add_argument(
        "--isolated",
        action="store_true",
        help="운영처럼 프로세스 풀 격리(OPS-96)로 훑는다(기본은 인라인 — 결정론·속도)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.isolated:
        os.environ.setdefault("WHYMATH_SYMPY_ISOLATION_ENABLED", "false")
    try:
        report = asyncio.run(build_report(_build_detector(), sweep=not args.no_sweep))
    except Exception as exc:  # noqa: BLE001 — 측정 불가를 통과로 위장하지 않는다(타입명만 노출)
        print(f"측정 불가: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_UNMEASURABLE
    print(
        json.dumps(to_json(report), ensure_ascii=False, indent=2) if args.json else render(report)
    )
    code = report.exit_code
    if code == EXIT_OK and args.require_all and report.gaps:
        print(
            f"\n--require-all: 좌석 없는 핵심 오개념 {len(report.gaps)}개 {report.gaps}",
            file=sys.stderr,
        )
        return EXIT_FAIL
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
