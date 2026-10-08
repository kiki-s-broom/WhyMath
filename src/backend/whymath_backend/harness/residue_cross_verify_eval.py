"""잔여 축 교차검증 게이트 — 기계 불가 잔여의 Wilson 표본 검수(S4-13 ②·exit 0/1).

정본: `docs/architecture/problem_bank_gap_review.md` §3 D7 ⑵ — "기계 불가 잔여는 독립 다관점
LLM 교차검증(생성자≠검증자·K≥3·원리 다른 프롬프트) + **Wilson 표본 검수 게이트**". 초인간
검증 §2 S5(보증된 오류 상한)의 이 도메인 판이다.

이 CLI가 검증 권위 서열을 **순서대로** 밟는다:
  ① **기계 증명(전수)** — 코퍼스 *전건*의 수치 축을 `l3/finite_probability` 전수 열거로 다시
     센다(표본이 아니라 전수). 하나라도 틀리면 즉시 실패한다 — LLM에게 물어볼 것도 없다.
  ② **측정 통과 기계 게이트(표본)** — 기계가 닫지 못한 잔여(발문↔형식모델 정합·조건 명료성)
     만 K≥3 독립 관점으로 교차검증하고, 그 라벨을 **Wilson 단측 상한**으로 판정한다.
     통계 부품·라벨 스키마·집계는 `harness/wilson`·`harness/corpus_audit_eval`을 재사용한다.
  ③ **인간 폴백** — 게이트가 실패하거나 판정 불가(unresolved)면 여기서 멈추고 사람 검수로 간다.

**측정 실패와 통과는 같은 색이 아니다**(CLAUDE.md): 표본 부족은 `NO_DATA`, 교차검증이 판정을
못 내면 `UNRESOLVED`로 **각각 다른 사유의 exit 1**이다. LLM이 침묵하거나 provider가 죽으면
"결함 0건 통과"가 아니라 "측정 실패"가 보인다.

**생성자≠검증자 가드(PB-15)**: 문항의 저작 서명(`authored_by`)은 코퍼스 레코드가 기록한 값을
그대로 쓴다(`llm:<모델 id>`·`deterministic:<생성기>`). 기록이 없는 레코드(구 코퍼스)는 서명을
**지어내지 않고** `unknown`으로 두며, 이 경우 독립성을 입증할 수 없어 `INDEPENDENCE_UNPROVEN`
(exit 1)이다 — 종전 `corpus:<유형>`은 검증자 서명과 형식이 달라 가드가 영영 발화하지 못했다.
구 코퍼스를 돌리려면 저작 주체를 사람이 `--authored-by`로 **선언**한다(예 결정론 생성기:
`--authored-by deterministic:<생성기>`·LLM 저작분: `--authored-by llm:<모델 id>`).

**합격 로트 무결성(§4.5)**: 산출 감사 JSONL에 as-found 병기 선언을 함께 쓴다. 교정 후 재채점
으로 FAIL→PASS를 세탁하지 않기 위한 기록이며, 같은 파일을 `corpus_audit_eval`에 그대로 먹여
독립 재판정할 수 있다(인프로세스 판정 + 파일 재현의 **이중 회계**).

사용:
    python -m whymath_backend.harness.residue_cross_verify_eval \\
        data/corpus/problem_bank_probability_finite_v0/problems.jsonl \\
        --sample-n 30 --audit-out audit.jsonl --max-defect-upper 0.05 --min-n 20
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from whymath_backend.harness.corpus_audit_eval import AuditLabel, summarize
from whymath_backend.l1.problem_bank.populate import load_problem_bank_records
from whymath_backend.l3.cross_verify import (
    UNRECORDED_AUTHOR,
    CrossVerifier,
    IndependenceError,
    ResidueSubject,
)
from whymath_backend.l3.finite_probability import (
    FiniteProbabilityError,
    describe_model_ko,
    enumerate_model,
    parse_finite_model,
    verify_finite_count,
    verify_finite_probability,
)
from whymath_backend.l3.verification_tier import VerificationTier

__all__ = [
    "PilotRecord",
    "ResidueGateReport",
    "load_pilot_records",
    "run_residue_cross_verify",
    "select_sample",
]

_EXIT_OK = 0
_EXIT_GATE_FAIL = 1

# 이 게이트가 다루는 검산 종류 — 전수 열거가 성립하는 도메인만. 그 밖은 범위 밖으로 거부한다.
_SUPPORTED_KINDS = frozenset({"finite_probability", "finite_count"})

GateOutcome = Literal[
    "PASS",
    "MACHINE_FAIL",
    "TIER_UNSUPPORTED",
    "NO_DATA",
    "UNRESOLVED",
    "INDEPENDENCE_UNPROVEN",
    "DEFECT_RATE",
]


@dataclass(frozen=True, slots=True)
class PilotRecord:
    """파일럿 코퍼스 1건 — 검산 재료 + 검증 등급 + 학생이 읽는 서술."""

    slug: str
    question_text: str
    answer: str
    answer_explanation: str
    conditions: str
    answer_kind: str
    tier: VerificationTier | None
    authored_by: str


def _require_str(value: object, *, slug: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"코퍼스 레코드 {slug}: 필수 문자열 필드 {field_name} 결측/형식오류")
    return value


def load_pilot_records(path: Path) -> list[PilotRecord]:
    """파일럿 코퍼스 JSONL → 레코드 목록. `load_problem_bank_records`(L1 정본) 경유(S4-17).

    L1이 저작권 위생·`Problem` 스키마·`verify.verification_tier`(S4-17에서 L1 정식 필드로 승격)
    를 이미 검증하므로 이 함수는 원시 JSONL을 다시 파싱하지 않는다 — 감사 도구가 로더를
    우회하지 않는다. L1이 강제하지 않는 *감사 전용* 불변식(발문·정답·검산 조건이 비지 않아야
    함)만 여기서 추가로 fail-loud 검증한다(조용한 스킵 0).
    """
    records: list[PilotRecord] = []
    for bank_record in load_problem_bank_records(path):
        slug = bank_record.slug
        problem = bank_record.problem
        conditions = bank_record.verify.conditions
        if not isinstance(conditions, str) or not conditions.strip():
            raise ValueError(f"코퍼스 레코드 {slug}: verify 절 결측 — 검산 재료 없이 감사 불가")
        tier_raw = bank_record.verify.verification_tier
        records.append(
            PilotRecord(
                slug=slug,
                question_text=_require_str(
                    problem.question_text, slug=slug, field_name="question_text"
                ),
                answer=_require_str(problem.answer, slug=slug, field_name="answer"),
                answer_explanation=problem.answer_explanation or "",
                conditions=conditions,
                answer_kind=bank_record.verify.answer_kind or "",
                tier=VerificationTier(tier_raw) if tier_raw is not None else None,
                # 저작 서명은 코퍼스가 기록한 값 그대로다. 기록이 없으면 지어내지 않고
                # `unknown`으로 둔다 — 종전 `corpus:<유형>` 조립은 검증자 서명과 형식이 달라
                # 생성자≠검증자 가드를 영영 비껴갔다(PB-15). 가드는 `unknown`을 거부한다.
                authored_by=(
                    bank_record.provenance.authored_by
                    if bank_record.provenance.authored_by is not None
                    else UNRECORDED_AUTHOR
                ),
            )
        )
    return records


def select_sample(records: Sequence[PilotRecord], *, sample_n: int, seed: str) -> list[PilotRecord]:
    """결정론 무작위 표본 — `sha256(seed:slug)` 순서로 정렬해 앞 n건.

    시드가 같으면 같은 표본이 나오고(재현성 축), slug 해시라 코퍼스 순서·저작 순서와 무관하다
    (선택 편향 차단). n이 코퍼스보다 크면 전건을 돌려준다.
    """
    ordered = sorted(
        records,
        key=lambda r: hashlib.sha256(f"{seed}:{r.slug}".encode()).hexdigest(),
    )
    return list(ordered[:sample_n]) if sample_n > 0 else []


@dataclass(frozen=True, slots=True)
class ResidueGateReport:
    """게이트 결과 — 기계 축(전수) + 잔여 축(표본 Wilson) 판정을 한 화면에.

    `outcome`은 단일 판정이며 exit code로 직결된다. `PASS`가 아닌 값은 각각 *다른 사유*의
    실패다 — 측정 실패(NO_DATA·UNRESOLVED)와 품질 실패(MACHINE_FAIL·DEFECT_RATE)를 섞지 않는다.
    """

    outcome: GateOutcome
    machine_checked: int
    machine_failures: list[str]
    sampled: int
    resolved: int
    defects: int
    unresolved: int
    defect_upper: float | None
    defect_classes: dict[str, int]
    labels: list[AuditLabel] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.outcome == "PASS"


def _verify_machine_axis(records: Sequence[PilotRecord]) -> tuple[list[str], list[str]]:
    """기계 축 **전건** 재검산 — (등급/범위 위반, 검산 실패) 사유 목록.

    수용 게이트가 저작 시점에 이미 검산했지만, 감사 시점에 *다시* 전수로 센다(코퍼스 파일이
    저작 이후 변조·손상되지 않았는지까지 이 재검산이 커버한다 — 재현성 축).
    """
    tier_violations: list[str] = []
    machine_failures: list[str] = []
    for record in records:
        if record.tier is None:
            tier_violations.append(
                f"{record.slug}: 검증 등급 미명시(verify.verification_tier 부재)"
            )
            continue
        if record.tier is not VerificationTier.MACHINE_EXHAUSTIVE:
            tier_violations.append(
                f"{record.slug}: 등급 {record.tier.value}는 전수 열거 게이트의 범위 밖"
            )
            continue
        if record.answer_kind not in _SUPPORTED_KINDS:
            tier_violations.append(
                f"{record.slug}: answer_kind={record.answer_kind!r}는 전수 열거 대상이 아님"
            )
            continue
        verifier = (
            verify_finite_probability
            if record.answer_kind == "finite_probability"
            else verify_finite_count
        )
        verdict = verifier(record.conditions, record.answer)
        if verdict.state != "pass":
            machine_failures.append(
                f"{record.slug}: 기계 전수 검산 {verdict.state} — {verdict.reason}"
            )
    return tier_violations, machine_failures


def _build_subject(record: PilotRecord, *, authored_by: str) -> ResidueSubject | str:
    """교차검증 대상 조립 — 모델 파싱·열거 실패는 *사유 문자열*(호출자가 기계 실패로 처리)."""
    try:
        model = parse_finite_model(record.conditions)
        result = enumerate_model(model)
    except FiniteProbabilityError as exc:
        return f"{record.slug}: 형식 모델 조립 실패({type(exc).__name__}) {exc}"
    return ResidueSubject(
        problem_id=record.slug,
        question_text=record.question_text,
        answer=record.answer,
        answer_explanation=record.answer_explanation,
        machine_model_ko=describe_model_ko(model, result),
        machine_total=result.total,
        machine_favorable=result.favorable,
        authored_by=authored_by,
    )


def run_residue_cross_verify(
    records: Sequence[PilotRecord],
    *,
    verifier: CrossVerifier,
    sample_n: int = 30,
    seed: str = "S4-13",
    max_defect_upper: float = 0.05,
    min_n: int = 20,
    max_unresolved: int = 0,
    confidence: float = 0.95,
    authored_by: str | None = None,
) -> ResidueGateReport:
    """전수 기계 검산 → 표본 교차검증 → Wilson 판정. 순수 조합(LLM은 주입된 검증기 안).

    `authored_by`를 주면 그 값으로 생성자 서명을 덮어쓴다 — 코퍼스에 서명 기록이 없는 구
    코퍼스의 저작 주체를 사람이 *선언*하는 좌석이다(`llm:<모델 id>`·`deterministic:<생성기>`).
    검증자와 같은 LLM이면 `CrossVerifier`가 자기승인으로 거부하고, 형식을 판독할 수 없으면
    독립성 입증 불가로 거부한다 — 둘 다 `INDEPENDENCE_UNPROVEN`(PB-15).
    """
    tier_violations, machine_failures = _verify_machine_axis(records)
    if tier_violations:
        return ResidueGateReport(
            outcome="TIER_UNSUPPORTED",
            machine_checked=len(records),
            machine_failures=[],
            sampled=0,
            resolved=0,
            defects=0,
            unresolved=0,
            defect_upper=None,
            defect_classes={},
            reasons=tier_violations,
        )
    if machine_failures:
        return ResidueGateReport(
            outcome="MACHINE_FAIL",
            machine_checked=len(records),
            machine_failures=machine_failures,
            sampled=0,
            resolved=0,
            defects=0,
            unresolved=0,
            defect_upper=None,
            defect_classes={},
            reasons=["기계 축(전수 열거)이 실패 — 잔여 축 교차검증 이전에 저작 결함을 고쳐야 함"],
        )

    sample = select_sample(records, sample_n=sample_n, seed=seed)
    labels: list[AuditLabel] = []
    unresolved: list[str] = []
    model_failures: list[str] = []
    for record in sample:
        subject = _build_subject(record, authored_by=authored_by or record.authored_by)
        if isinstance(subject, str):
            model_failures.append(subject)
            continue
        try:
            result = verifier.verify(subject)
        except IndependenceError as exc:
            # 생성자≠검증자를 입증하지 못한 측정은 **통째로 무효**다 — 자기승인 라벨은 결함율
            # 증거가 아니다. 첫 건에서 즉시 멈춰 이후 표본의 LLM 호출 낭비를 막고, 트레이스백이
            # 아니라 이름 붙은 측정 실패로 보고한다(품질 실패 DEFECT_RATE와 섞지 않는다).
            return ResidueGateReport(
                outcome="INDEPENDENCE_UNPROVEN",
                machine_checked=len(records),
                machine_failures=[],
                sampled=len(sample),
                resolved=0,
                defects=0,
                unresolved=0,
                defect_upper=None,
                defect_classes={},
                reasons=[f"{record.slug}: {exc}"],
            )
        if result.aggregate == "unclear":
            unresolved.append(f"{record.slug}: {result.reason}")
            continue
        labels.append(
            AuditLabel(
                problem_id=record.slug,
                verdict="ok" if result.aggregate == "ok" else "defect",
                defect_class=result.defect_class,
            )
        )
    if model_failures:
        return ResidueGateReport(
            outcome="MACHINE_FAIL",
            machine_checked=len(records),
            machine_failures=model_failures,
            sampled=len(sample),
            resolved=0,
            defects=0,
            unresolved=len(unresolved),
            defect_upper=None,
            defect_classes={},
            reasons=["표본의 형식 모델을 조립할 수 없음 — 감사 재료 결손"],
        )

    report = summarize(labels)
    upper = report.defect_rate_upper_bound(confidence)
    reasons: list[str] = []
    outcome: GateOutcome = "PASS"
    if len(unresolved) > max_unresolved:
        outcome = "UNRESOLVED"
        reasons.append(
            f"교차검증 판정 불가 {len(unresolved)}건 > 허용 {max_unresolved}건 — "
            "측정 실패(통과 아님)"
        )
        reasons.extend(unresolved)
    elif report.n < min_n:
        outcome = "NO_DATA"
        reasons.append(f"판정 가능한 표본 {report.n} < 최소 {min_n} — 측정 부족(통과 아님)")
    elif upper is None or upper > max_defect_upper:
        outcome = "DEFECT_RATE"
        reasons.append(
            f"잔여 축 결함율 Wilson {round(confidence * 100)}% 상한 "
            f"{'n/a' if upper is None else f'{upper:.4f}'} > 임계 {max_defect_upper}"
        )
    return ResidueGateReport(
        outcome=outcome,
        machine_checked=len(records),
        machine_failures=[],
        sampled=len(sample),
        resolved=report.n,
        defects=report.defects,
        unresolved=len(unresolved),
        defect_upper=upper,
        defect_classes=dict(report.defect_classes),
        labels=labels,
        reasons=reasons,
    )


def write_audit_jsonl(path: Path, report: ResidueGateReport) -> int:
    """감사 라벨 + as-found 병기 선언을 JSONL로 — `corpus_audit_eval`이 그대로 재판정한다.

    as-found(§4.5)는 *이번 측정 그대로*다(교정 전 = 교정 후). 이후 결함을 고치고 재감사할 때
    이 파일이 역사 위조를 막는 기준선이 된다.
    """
    lines = [
        json.dumps(
            {
                "problem_id": label.problem_id,
                "verdict": label.verdict,
                "defect_class": label.defect_class,
            },
            ensure_ascii=False,
        )
        for label in report.labels
    ]
    if report.labels:
        lines.append(
            json.dumps(
                {"as_found_n": report.resolved, "as_found_defects": report.defects},
                ensure_ascii=False,
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")
    return len(lines)


def format_report(report: ResidueGateReport, *, confidence: float) -> str:
    """사람 가독 요약 — 기계 축·잔여 축을 분리해 보여준다(무엇이 증명됐는지 헷갈리지 않게)."""
    pct = round(confidence * 100)
    upper = "n/a" if report.defect_upper is None else f"{report.defect_upper:.4f}"
    lines = [
        "=" * 64,
        "잔여 축 교차검증 게이트 — SymPy 불가 영역 경로 v1(S4-13)",
        "=" * 64,
        f"[기계 축·전수] 전수 열거 재검산 {report.machine_checked}건 "
        f"실패 {len(report.machine_failures)}건",
        f"[잔여 축·표본] 표본 {report.sampled}건 중 판정 {report.resolved}건 "
        f"결함 {report.defects}건 판정불가 {report.unresolved}건",
        f"[Wilson] 잔여 축 결함율 {pct}% 상한 = {upper}",
    ]
    if report.defect_classes:
        lines.append("결함류 분포:")
        for name, count in sorted(report.defect_classes.items()):
            lines.append(f"  {name}: {count}")
    if report.machine_failures:
        lines.append("기계 축 실패:")
        lines.extend(f"  - {reason}" for reason in report.machine_failures[:20])
    if report.reasons:
        lines.append("판정 사유:")
        lines.extend(f"  - {reason}" for reason in report.reasons[:20])
    lines.append(f"판정: {report.outcome}")
    lines.append("=" * 64)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI — 전수 기계 검산 + 표본 교차검증 Wilson 게이트. PASS만 exit 0."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.residue_cross_verify_eval",
        description="유한 확률 파일럿 코퍼스의 잔여 축(발문↔형식모델) 교차검증 Wilson 게이트.",
    )
    parser.add_argument("corpus", type=Path, help="파일럿 코퍼스 JSONL 경로.")
    parser.add_argument("--sample-n", type=int, default=30, help="교차검증 표본 수(기본 30).")
    parser.add_argument("--seed", default="S4-13", help="결정론 표본 추출 시드.")
    parser.add_argument("--min-n", type=int, default=20, help="판정 최소 표본(미만이면 NO_DATA).")
    parser.add_argument(
        "--max-defect-upper", type=float, default=0.05, help="잔여 축 결함율 Wilson 상한 임계."
    )
    parser.add_argument(
        "--max-unresolved", type=int, default=0, help="허용 판정불가 건수(기본 0·측정 실패 무관용)."
    )
    parser.add_argument("--confidence", type=float, default=0.95, help="Wilson 신뢰수준.")
    parser.add_argument("--audit-out", type=Path, default=None, help="감사 JSONL 산출 경로.")
    parser.add_argument(
        "--authored-by",
        default=None,
        help=(
            "생성자 서명 선언(서명 기록이 없는 구 코퍼스용·레코드 값을 덮어씀) — "
            "'llm:<모델 id>' 또는 'deterministic:<생성기>' 형식. 검증자와 같은 LLM이면 거부된다."
        ),
    )
    args = parser.parse_args(argv)

    records = load_pilot_records(args.corpus)
    # 실 provider는 지연 연결(구성만으로 네트워크 0) — 실제 호출은 verify() 시점에 일어난다.
    verifier = CrossVerifier()
    report = run_residue_cross_verify(
        records,
        verifier=verifier,
        sample_n=args.sample_n,
        seed=args.seed,
        max_defect_upper=args.max_defect_upper,
        min_n=args.min_n,
        max_unresolved=args.max_unresolved,
        confidence=args.confidence,
        authored_by=args.authored_by,
    )
    verifier.flush_trace()
    if args.audit_out is not None:
        write_audit_jsonl(args.audit_out, report)
    print(format_report(report, confidence=args.confidence))
    return _EXIT_OK if report.passed else _EXIT_GATE_FAIL


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
