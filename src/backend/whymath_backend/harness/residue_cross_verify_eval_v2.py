"""잔여 축 교차검증 게이트 v2 — 도메인 플러그인 로트 게이트 (S4-56, 설계서 §6).

v1(`residue_cross_verify_eval`)은 확률 유한 전수형(`finite_probability`·`finite_count`)만 안다.
v2는 `--domain`으로 도메인을 고르고, 통합 verifier(`l3/verifier.py`)에 **이미 등록된**
도메인 verifier·교차검증 관점 세트를 그대로 쓴다 — 게이트가 자기만의 심사 재료를 따로
들지 않는다(단일 출처).

검증 권위 서열을 **순서대로** 밟는 점은 v1과 같다:
  ① **기계 증명(전수)** — 도메인 레코드 *전건*을 도메인 verifier로 다시 검산한다
     (표본이 아니라 전수).
  ② **측정 통과 기계 게이트(표본)** — 기계가 닫지 못한 잔여 축만 K≥3 독립 관점으로
     교차검증하고 라벨을 Wilson 단측 상한으로 판정한다.
  ③ **인간 폴백** — 실패·판정 불가면 멈추고 사람 검수로 간다.

v2가 v1에 더하는 것:
  - **도달 불가 임계를 LLM 호출 *전에* 거부한다**(`THRESHOLD_UNREACHABLE`). 결함 0건이어도
    95% 상한이 0.05를 넘는 표본 크기(n<52)로 0.05를 요구하면 어떤 결과도 통과할 수 없다 —
    v1은 표본 전건을 LLM에 보낸 *뒤에야* `DEFECT_RATE`로 실패해 호출 비용만 쓰고 결함율
    판정처럼 읽혔다(`residue_gate_demotion_battle_history.md` §6 · 설계 부록 FC-4).
    통과할 수 없는 게이트를 "게이트가 있다"로 세지 않는다.
  - **저작 서명 사전점검** — 표본 전건의 서명 판독 가능 여부를 첫 호출 *전에* 본다
    (첫 거부에서 멈추면 그 앞 표본의 호출이 낭비된다).
  - **`--dry-run`** — LLM 0·네트워크 0으로 ①과 사전점검까지만 돈다. 잔여 축은
    **측정하지 않는다**: 출력은 `DRY_RUN_OK`이며 `PASS`가 아니다(통과 위장 금지).
  - **측정 실패와 게이트 실패의 종료 코드 분리** — 코퍼스를 못 읽었거나 도메인이 미구현이면
    exit 2(게이트가 판정을 내지 못한 것). 게이트 판정 실패는 exit 1, 통과는 exit 0.

**지위(2026-09-25 Kiki 판정)**: 잔여 축 LLM 교차검증 게이트는 *인간 검수 대체 후보에서
제외*됐다(`residue_gate_demotion_battle_history.md` §6 — 프로덕션 모드 오검출 33/33).
이 CLI는 그 판정을 뒤집지 않는다: 라이브 PASS가 나와도 "검수 대체"가 아니며, 재측정하려면
변조기 정답지 수리와 대조군 사람 검수가 먼저다. 이 모듈이 주는 것은 메커니즘(도메인 선택·
사전점검·이중 회계)이지 승격이 아니다.

사용:
    python -m whymath_backend.harness.residue_cross_verify_eval_v2 \\
        data/corpus/problem_bank_probability_finite_v0/problems.jsonl \\
        --domain finite --dry-run --sample-n 34 --max-defect-upper 0.11
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from whymath_backend.harness.corpus_audit_eval import AuditLabel, summarize
from whymath_backend.harness.residue_cross_verify_eval import (
    PilotRecord,
    load_pilot_records,
    select_sample,
)
from whymath_backend.harness.wilson import wilson_upper_bound
from whymath_backend.l3.cross_verify import (
    CrossVerificationResult,
    CrossVerifier,
    IndependenceError,
    Perspective,
    ResidueSubject,
    assert_author_independent,
    resolve_author_signature,
)
from whymath_backend.l3.verification_tier import (
    VERIFICATION_TIER_KEY,
    VerificationTier,
    read_verification_tier,
)
from whymath_backend.l3.verifier import (
    _CROSS_VERIFY_PERSPECTIVES,
    _VERIFIERS_V2,
    ProblemVerifyInput,
    _DomainResult,
    build_residue_subject,
)

__all__ = [
    "DOMAIN_SPECS",
    "PLANNED_DOMAINS",
    "DomainGateSpec",
    "ResidueGateReportV2",
    "UnsupportedDomainError",
    "min_zero_defect_n",
    "resolve_spec",
    "run_residue_gate_v2",
    "write_audit_jsonl",
]

_EXIT_OK = 0
_EXIT_GATE_FAIL = 1
_EXIT_MEASUREMENT_FAIL = 2  # 게이트가 판정을 못 낸 경우(코퍼스 로드 실패·미구현 도메인·인자 오류)

# 독립성 사전점검에서 실제 검증자 서명 대신 쓰는 자리표시 — *판독 가능 여부*만 본다. 자기승인
# 비교는 첫 호출의 `CrossVerifier.verify`가 실제 서명으로 한다(여기서 같아질 일이 없는 값).
_PREFLIGHT_VERIFIER_SIGNATURE = "llm:__preflight__"

# 사유 목록 출력 상한 — 수백 건이 한 화면을 덮지 않게(전건은 감사 JSONL이 든다).
_MAX_REASONS_SHOWN = 20

GateOutcome = Literal[
    "PASS",
    "DRY_RUN_OK",
    "MACHINE_FAIL",
    "MACHINE_UNVERIFIABLE",
    "TIER_UNSUPPORTED",
    "NO_DATA",
    "THRESHOLD_UNREACHABLE",
    "UNRESOLVED",
    "INDEPENDENCE_UNPROVEN",
    "DEFECT_RATE",
]


class UnsupportedDomainError(ValueError):
    """게이트가 다룰 수 없는 도메인 — 미구현(계획만 있음)이거나 레지스트리에 없음."""


# ──────────────────────────────────────────────────────────────────────────
# 도메인 레지스트리 — 기본 임계의 *유도 규칙*을 코드로 고정한다
# ──────────────────────────────────────────────────────────────────────────
def min_zero_defect_n(max_defect_upper: float, confidence: float = 0.95) -> int:
    """결함 0건일 때 Wilson 단측 상한이 `max_defect_upper` 이하가 되는 **최소 표본 크기**.

    결함 0건의 상한은 닫힌 식 `z² / (n + z²)`라 `n ≥ z²(1/p − 1)`이 해다. 식의 올림값에서 시작해
    저장소의 `wilson_upper_bound`(실제 판정 함수)로 경계를 맞춘다 — 식만 믿지 않고 판정기와 같은
    함수로 확인한다(95%·0.05 → 52, 설계 부록 FC-4 표와 일치).
    """
    if not 0.0 < max_defect_upper < 1.0:
        raise ValueError(f"max_defect_upper must be in (0, 1), got {max_defect_upper}")
    z = statistics.NormalDist().inv_cdf(confidence)
    n = max(1, math.ceil(z * z * (1.0 / max_defect_upper - 1.0)))
    while wilson_upper_bound(0, n, confidence) > max_defect_upper:
        n += 1
    while n > 1 and wilson_upper_bound(0, n - 1, confidence) <= max_defect_upper:
        n -= 1
    return n


_DEFAULT_CONFIDENCE = 0.95
_DEFAULT_MAX_DEFECT_UPPER = 0.05
# 기본 표본 크기 = 기본 임계를 *결함 0건으로 통과할 수 있는* 최소 n. 이보다 작은 기본값은 무결함
# 로트도 통과할 수 없는 조합이다(v1 기본 30 → 상한 0.0827, 실측으로 확인된 함정).
_DEFAULT_SAMPLE_N = min_zero_defect_n(_DEFAULT_MAX_DEFECT_UPPER, _DEFAULT_CONFIDENCE)


@dataclass(frozen=True, slots=True)
class DomainGateSpec:
    """도메인 1개의 게이트 설정 — 어떤 kind를 어떤 등급 아래서 어떤 기본 임계로 거는가.

    관점 세트·도메인 verifier는 여기 두지 않는다 — `l3/verifier`의 `_CROSS_VERIFY_PERSPECTIVES`·
    `_VERIFIERS_V2`가 단일 출처다(게이트와 서빙 경로가 다른 심사를 하는 드리프트 차단).

    기본 임계(sample_n·min_n·max_defect_upper)는 **도메인 간 차등을 두지 않는다** — 차등의 근거가
    될 라이브 측정이 아직 없다(오검출 100% 이력 · `residue_gate_demotion_battle_history.md` §2.3).
    근거 없는 차등은 숫자의 위장이다. 칸을 도메인별로 둔 것은 측정이 쌓이면 *개별로* 조정하기
    위해서다.
    """

    name: str
    answer_kinds: tuple[str, ...]
    accepted_tiers: frozenset[VerificationTier]
    sample_n: int = _DEFAULT_SAMPLE_N
    min_n: int = _DEFAULT_SAMPLE_N
    max_defect_upper: float = _DEFAULT_MAX_DEFECT_UPPER
    note: str = ""


# 전수 열거 게이트는 수치 축을 *전수로 닫는* 등급만 받는다 — 표본 추정(NUMERIC_SAMPLING)·통계 추정·
# 잔여 검토·인간 검수 등급은 "다시 센다"는 이 게이트의 전제 밖이다.
_FINITE_TIERS = frozenset({VerificationTier.FINITE_EXHAUSTIVE})
_DATA_TIERS = frozenset({VerificationTier.FINITE_EXHAUSTIVE, VerificationTier.DETERMINISTIC_DATA})

DOMAIN_SPECS: dict[str, DomainGateSpec] = {
    spec.name: spec
    for spec in (
        DomainGateSpec(
            name="finite",
            answer_kinds=("finite_probability", "finite_count"),
            accepted_tiers=_FINITE_TIERS,
            note="v1 게이트와 같은 로트 — 확률+경우의 수(관점 세트 공유). 파일럿 34문.",
        ),
        DomainGateSpec(
            name="finite_probability",
            answer_kinds=("finite_probability",),
            accepted_tiers=_FINITE_TIERS,
        ),
        DomainGateSpec(
            name="finite_count",
            answer_kinds=("finite_count",),
            accepted_tiers=_FINITE_TIERS,
        ),
        DomainGateSpec(
            name="statistical_claim",
            answer_kinds=("statistical_claim",),
            accepted_tiers=_DATA_TIERS,
            note="소비처(코퍼스 레코드) 0건 — hermetic 대역으로만 검증된 상태(설계 부록 §6.1).",
        ),
        DomainGateSpec(
            name="sequence_induction",
            answer_kinds=("sequence_induction",),
            accepted_tiers=_DATA_TIERS,
            note="[12대수03-06] 30건은 아직 answer_kind·등급 미각인 — 소비처 0건(S4-66 범위 밖).",
        ),
    )
}

# 설계상 후보지만 **구현이 없는** 도메인 — 이름만 받고 거부한다(있는 척 통과시키지 않는다).
PLANNED_DOMAINS: dict[str, str] = {
    "geometric_discrete": (
        "기하 이산형은 미착수다 — 단계 A는 statistical_claim으로 구현됐다"
        "(verifier_v2_domains.md §6.1). 도메인 verifier·관점 세트가 없어 게이트를 걸 수 없다."
    ),
}


def resolve_spec(domain: str) -> DomainGateSpec:
    """도메인 이름 → 게이트 설정. 미구현·미지·관점/verifier 미등록은 `UnsupportedDomainError`."""
    if domain in PLANNED_DOMAINS:
        raise UnsupportedDomainError(f"--domain {domain}: {PLANNED_DOMAINS[domain]}")
    spec = DOMAIN_SPECS.get(domain)
    if spec is None:
        raise UnsupportedDomainError(
            f"--domain {domain}: 알 수 없는 도메인. 지원: {sorted(DOMAIN_SPECS)}"
        )
    for kind in spec.answer_kinds:
        if kind not in _VERIFIERS_V2:
            raise UnsupportedDomainError(f"--domain {domain}: {kind}의 도메인 verifier가 미등록")
        if kind not in _CROSS_VERIFY_PERSPECTIVES:
            raise UnsupportedDomainError(f"--domain {domain}: {kind}의 교차검증 관점이 미등록")
    return spec


# ──────────────────────────────────────────────────────────────────────────
# 결과 타입
# ──────────────────────────────────────────────────────────────────────────
class _CrossVerifierLike(Protocol):
    """게이트가 요구하는 교차검증기 표면 — 실 `CrossVerifier`와 hermetic 대역이 함께 만족한다."""

    def verify(
        self, subject: ResidueSubject, perspectives: Sequence[Perspective] | None = None
    ) -> CrossVerificationResult: ...


@dataclass(frozen=True, slots=True)
class ResidueGateReportV2:
    """게이트 결과 — 기계 축(전수) + 사전점검 + 잔여 축(표본 Wilson)을 한 화면에.

    `outcome`은 단일 판정이다. `PASS`만 통과이고 `DRY_RUN_OK`는 *잔여 축을 재지 않은* 사전점검
    통과다(둘을 섞으면 dry-run이 통과 증거로 인용된다). 나머지는 각각 다른 사유의 실패 —
    측정 실패(NO_DATA·UNRESOLVED·MACHINE_UNVERIFIABLE·INDEPENDENCE_UNPROVEN)와 설계 실패
    (THRESHOLD_UNREACHABLE)와 품질 실패(MACHINE_FAIL·DEFECT_RATE)를 섞지 않는다.
    """

    domain: str
    outcome: GateOutcome
    eligible: int
    skipped_kinds: dict[str, int]
    machine_checked: int
    machine_failures: list[str]
    sampled: int
    resolved: int
    defects: int
    unresolved: int
    defect_upper: float | None
    defect_classes: dict[str, int]
    min_zero_defect_n: int
    labels: list[AuditLabel] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """잔여 축까지 측정해 통과했는가 — dry-run은 여기 해당하지 않는다."""
        return self.outcome == "PASS"

    @property
    def exit_ok(self) -> bool:
        """종료 코드 0 여부 — 통과이거나 dry-run 사전점검 통과."""
        return self.outcome in ("PASS", "DRY_RUN_OK")


def _early_report(
    spec: DomainGateSpec,
    outcome: GateOutcome,
    *,
    eligible: int,
    skipped_kinds: dict[str, int],
    machine_checked: int,
    reasons: list[str],
    machine_failures: list[str] | None = None,
    sampled: int = 0,
    min_reachable_n: int,
) -> ResidueGateReportV2:
    """표본 심사 이전(또는 도중) 중단 보고 — 라벨·결함율이 없는 실패/사전점검 결과."""
    return ResidueGateReportV2(
        domain=spec.name,
        outcome=outcome,
        eligible=eligible,
        skipped_kinds=skipped_kinds,
        machine_checked=machine_checked,
        machine_failures=machine_failures or [],
        sampled=sampled,
        resolved=0,
        defects=0,
        unresolved=0,
        defect_upper=None,
        defect_classes={},
        min_zero_defect_n=min_reachable_n,
        reasons=reasons,
    )


# ──────────────────────────────────────────────────────────────────────────
# ① 기계 축 전수 재검산
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class _MachinePass:
    """기계 축 통과 레코드의 도메인 결과 — 표본 심사가 같은 재료를 재사용한다(재계산 방지)."""

    record: PilotRecord
    domain_result: _DomainResult


def _machine_axis(
    eligible: Sequence[PilotRecord], spec: DomainGateSpec
) -> tuple[list[str], list[str], list[str], dict[str, _MachinePass]]:
    """도메인 레코드 **전건** 재검산 — (등급 위반, 검산 실패, 검산 불가, slug→통과 결과).

    저작 시점에 이미 검산했어도 감사 시점에 다시 전수로 센다(코퍼스 변조·손상까지 이 재검산이
    커버한다 — 재현성 축). `unverifiable`은 `fail`이 아니다: 못 쟀다는 뜻이라 따로 모은다.
    """
    tier_violations: list[str] = []
    failures: list[str] = []
    unverifiable: list[str] = []
    passed: dict[str, _MachinePass] = {}
    seen: set[str] = set()
    for record in eligible:
        if record.slug in seen:
            # slug로 통과 결과를 색인하므로 중복은 한쪽 결과가 조용히 사라진다 — 코퍼스 결함이다.
            failures.append(f"{record.slug}: slug 중복 — 같은 식별자의 레코드가 둘 이상")
            continue
        seen.add(record.slug)
        if record.tier is None:
            tier_violations.append(
                f"{record.slug}: 검증 등급 미명시(verify.verification_tier 부재)"
            )
            continue
        tier = read_verification_tier({VERIFICATION_TIER_KEY: record.tier})
        if tier not in spec.accepted_tiers:
            shown = "미명시" if tier is None else tier.value
            tier_violations.append(
                f"{record.slug}: 등급 {shown}는 {spec.name} 게이트의 범위 밖"
                f"(허용: {sorted(t.value for t in spec.accepted_tiers)})"
            )
            continue
        domain_verifier = _VERIFIERS_V2[record.answer_kind]
        try:
            domain_result = domain_verifier(record.conditions, record.answer)
        except (
            Exception
        ) as exc:  # noqa: BLE001 — 한 건의 예외가 전수 검산을 죽이지 않게. 타입명은 남긴다.
            unverifiable.append(f"{record.slug}: 도메인 verifier 예외({type(exc).__name__})")
            continue
        state = domain_result.verdict.state
        if state == "pass":
            passed[record.slug] = _MachinePass(record, domain_result)
        elif state == "fail":
            failures.append(f"{record.slug}: 기계 전수 검산 fail — {domain_result.verdict.reason}")
        else:
            unverifiable.append(f"{record.slug}: 기계 검산 불가 — {domain_result.verdict.reason}")
    return tier_violations, failures, unverifiable, passed


# ──────────────────────────────────────────────────────────────────────────
# 본체
# ──────────────────────────────────────────────────────────────────────────
def _validate_params(
    *,
    sample_n: int,
    min_n: int,
    max_defect_upper: float,
    max_unresolved: int,
    confidence: float,
) -> None:
    """인자 범위 — 잘못된 값이 조용히 다른 판정으로 흘러가지 않게 ValueError(CLI는 exit 2)."""
    if sample_n < 1:
        raise ValueError(f"sample_n은 1 이상이어야 한다: {sample_n}")
    if min_n < 1:
        raise ValueError(f"min_n은 1 이상이어야 한다: {min_n}")
    if not 0.0 < max_defect_upper < 1.0:
        raise ValueError(f"max_defect_upper는 (0, 1) 안이어야 한다: {max_defect_upper}")
    if max_unresolved < 0:
        raise ValueError(f"max_unresolved는 0 이상이어야 한다: {max_unresolved}")
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence는 (0, 1) 안이어야 한다: {confidence}")


def run_residue_gate_v2(
    records: Sequence[PilotRecord],
    *,
    domain: str,
    verifier: _CrossVerifierLike | None,
    sample_n: int | None = None,
    min_n: int | None = None,
    max_defect_upper: float | None = None,
    max_unresolved: int = 0,
    confidence: float = _DEFAULT_CONFIDENCE,
    seed: str | None = None,
    authored_by: str | None = None,
    dry_run: bool = False,
) -> ResidueGateReportV2:
    """전수 기계 검산 → 사전점검 → (표본 교차검증 → Wilson 판정). 순수 조합(LLM은 주입된 검증기 안).

    `None` 인자는 도메인 기본값(`DomainGateSpec`)을 쓴다. `dry_run=True`이면 LLM을 부르지 않으므로
    `verifier`는 `None`이어도 되고, 반대로 `dry_run=False`에 `verifier=None`은 허용하지 않는다
    (측정 없이 통과를 만들 수 있는 조합이라서).
    """
    spec = resolve_spec(domain)
    n_sample = spec.sample_n if sample_n is None else sample_n
    n_min = spec.min_n if min_n is None else min_n
    threshold = spec.max_defect_upper if max_defect_upper is None else max_defect_upper
    _validate_params(
        sample_n=n_sample,
        min_n=n_min,
        max_defect_upper=threshold,
        max_unresolved=max_unresolved,
        confidence=confidence,
    )
    if verifier is None and not dry_run:
        raise ValueError(
            "dry_run=False이면 교차검증기가 필요하다(측정 없이는 통과를 만들지 않는다)"
        )
    reachable_n = min_zero_defect_n(threshold, confidence)

    eligible = [r for r in records if r.answer_kind in spec.answer_kinds]
    skipped = dict(
        Counter(
            r.answer_kind or "(없음)" for r in records if r.answer_kind not in spec.answer_kinds
        )
    )

    def early(
        outcome: GateOutcome,
        reasons: list[str],
        *,
        machine_failures: list[str] | None = None,
        sampled: int = 0,
    ) -> ResidueGateReportV2:
        return _early_report(
            spec,
            outcome,
            eligible=len(eligible),
            skipped_kinds=skipped,
            machine_checked=len(eligible),
            reasons=reasons,
            machine_failures=machine_failures,
            sampled=sampled,
            min_reachable_n=reachable_n,
        )

    if not eligible:
        # 스캔 0건은 통과가 아니다 — 대상을 하나도 못 찾은 전수 검사는 공허하게 초록이 된다.
        kinds = ", ".join(spec.answer_kinds)
        label = spec.name if kinds == spec.name else f"{spec.name}({kinds})"
        return early(
            "NO_DATA",
            [
                f"도메인 {label} 레코드가 코퍼스에 0건 — 스캔 0건은 통과가 아니다"
                "(소비처가 없거나 --domain이 코퍼스와 어긋남)"
            ],
        )

    tier_violations, failures, unverifiable, passed = _machine_axis(eligible, spec)
    if tier_violations:
        return early("TIER_UNSUPPORTED", tier_violations)
    if failures:
        return early(
            "MACHINE_FAIL",
            ["기계 축(전수)이 실패 — 잔여 축 교차검증 이전에 저작 결함을 고쳐야 함"],
            machine_failures=failures,
        )
    if unverifiable:
        return early(
            "MACHINE_UNVERIFIABLE",
            ["기계 축이 일부 레코드를 닫지 못함 — 못 쟀다는 뜻이며 통과가 아니다", *unverifiable],
        )

    # ── 사전점검: LLM 호출 *전에* 이 측정이 성립할 수 있는지 본다 ───────────────
    # 도달 불가를 표본 부족(NO_DATA)보다 먼저 본다 — "표본이 모자란다"는 사실이 곧 "이 임계로는
    # 어떤 결과도 통과할 수 없다"는 더 강한 진단일 때(기본 임계 + 소형 파일럿), 후자가 고칠 곳을
    # 정확히 가리킨다(임계를 올리거나 표본을 늘리거나).
    effective_n = min(n_sample, len(eligible))
    zero_defect_upper = wilson_upper_bound(0, effective_n, confidence)
    if zero_defect_upper > threshold:
        return early(
            "THRESHOLD_UNREACHABLE",
            [
                f"표본 {effective_n}건(= min(표본 {n_sample}, 도메인 레코드 {len(eligible)}))은 "
                f"결함이 0건이어도 Wilson {round(confidence * 100)}% 상한이 "
                f"{zero_defect_upper:.4f}라 임계 {threshold}를 넘는다 — 어떤 결과도 통과할 수 없는 "
                f"측정이다(임계 {threshold}에는 표본 {reachable_n}건 이상, 또는 이 표본에는 임계 "
                f"{zero_defect_upper:.4f} 초과가 필요). LLM 호출 전에 거부한다"
            ],
            sampled=effective_n,
        )
    if effective_n < n_min:
        return early(
            "NO_DATA",
            [
                f"심사 가능한 표본 {effective_n}(= min(표본 {n_sample}, 도메인 레코드 "
                f"{len(eligible)})) < 최소 {n_min} — 측정 부족(통과 아님)"
            ],
        )

    sample = select_sample(
        [machine.record for machine in passed.values()],
        sample_n=n_sample,
        seed=seed if seed is not None else f"S4-56:{spec.name}",
    )
    signatures: dict[str, str] = {}
    independence_reasons: list[str] = []
    for record in sample:
        try:
            signature = resolve_author_signature(record.authored_by, authored_by)
            assert_author_independent(signature, _PREFLIGHT_VERIFIER_SIGNATURE)
        except IndependenceError as exc:
            independence_reasons.append(f"{record.slug}: {exc}")
            continue
        signatures[record.slug] = signature
    if independence_reasons:
        # 서명을 판독할 수 없는 표본이 하나라도 있으면 측정 전체가 무효다 — 첫 호출 전에 멈춘다.
        return early(
            "INDEPENDENCE_UNPROVEN",
            independence_reasons[:_MAX_REASONS_SHOWN],
            sampled=len(sample),
        )

    if dry_run:
        return early(
            "DRY_RUN_OK",
            [
                "dry-run — 기계 축 전수 재검산과 사전점검(임계 도달성·저작 서명)만 수행했다. "
                "잔여 축 교차검증은 실행하지 않았으므로 이 결과는 통과(PASS)가 아니다"
            ],
            sampled=len(sample),
        )
    assert verifier is not None  # 위에서 dry_run=False & None 조합을 거부했다 — mypy용

    # ── ② 잔여 축 표본 교차검증 ─────────────────────────────────────────────
    labels: list[AuditLabel] = []
    unresolved: list[str] = []
    for record in sample:
        machine = passed[record.slug]
        problem = ProblemVerifyInput(
            slug=record.slug,
            question_text=record.question_text,
            answer=record.answer,
            answer_kind=record.answer_kind,
            conditions=record.conditions,
            answer_explanation=record.answer_explanation,
            authored_by=signatures[record.slug],
        )
        subject = build_residue_subject(problem, machine.domain_result)
        perspectives = _CROSS_VERIFY_PERSPECTIVES[record.answer_kind]
        try:
            result = verifier.verify(subject, perspectives)
        except IndependenceError as exc:
            # 자기승인(검증자 서명 == 생성자 서명)은 사전점검이 못 본다(검증자 서명은 호출 시점에
            # 라우터가 정한다). 첫 건에서 즉시 멈춘다 — 자기승인 라벨은 결함율 증거가 아니다.
            return early(
                "INDEPENDENCE_UNPROVEN",
                [f"{record.slug}: {exc}"],
                sampled=len(sample),
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

    summary = summarize(labels)
    upper = summary.defect_rate_upper_bound(confidence)
    reasons: list[str] = []
    outcome: GateOutcome = "PASS"
    if len(unresolved) > max_unresolved:
        outcome = "UNRESOLVED"
        reasons.append(
            f"교차검증 판정 불가 {len(unresolved)}건 > 허용 {max_unresolved}건 — "
            "측정 실패(통과 아님)"
        )
        reasons.extend(unresolved[:_MAX_REASONS_SHOWN])
    elif summary.n < n_min:
        outcome = "NO_DATA"
        reasons.append(f"판정 가능한 표본 {summary.n} < 최소 {n_min} — 측정 부족(통과 아님)")
    elif upper is None or upper > threshold:
        outcome = "DEFECT_RATE"
        reasons.append(
            f"잔여 축 결함율 Wilson {round(confidence * 100)}% 상한 "
            f"{'n/a' if upper is None else f'{upper:.4f}'} > 임계 {threshold}"
        )
    return ResidueGateReportV2(
        domain=spec.name,
        outcome=outcome,
        eligible=len(eligible),
        skipped_kinds=skipped,
        machine_checked=len(eligible),
        machine_failures=[],
        sampled=len(sample),
        resolved=summary.n,
        defects=summary.defects,
        unresolved=len(unresolved),
        defect_upper=upper,
        defect_classes=dict(summary.defect_classes),
        min_zero_defect_n=reachable_n,
        labels=labels,
        reasons=reasons,
    )


# ──────────────────────────────────────────────────────────────────────────
# 산출 — 감사 JSONL(이중 회계) · 사람 가독 요약
# ──────────────────────────────────────────────────────────────────────────
def write_audit_jsonl(path: Path, report: ResidueGateReportV2) -> int:
    """감사 라벨 + as-found 병기 선언을 JSONL로 — `corpus_audit_eval`이 그대로 재판정한다.

    v1과 **같은 형식**이다(재판정 도구가 하나). as-found(§4.5)는 *이번 측정 그대로*라, 이후 결함을
    고치고 재감사할 때 이 파일이 역사 위조를 막는 기준선이 된다. 라벨이 없는 실행(dry-run·사전점검
    실패)은 빈 파일을 쓴다 — 측정하지 않은 로트에 as-found를 지어내지 않는다.
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


def format_report(report: ResidueGateReportV2, *, confidence: float) -> str:
    """사람 가독 요약 — 기계 축·사전점검·잔여 축을 분리해 보여준다(증명 범위가 헷갈리지 않게)."""
    pct = round(confidence * 100)
    upper = "n/a" if report.defect_upper is None else f"{report.defect_upper:.4f}"
    lines = [
        "=" * 64,
        f"잔여 축 교차검증 게이트 v2 — 도메인 {report.domain}(S4-56)",
        "=" * 64,
        f"[도메인 레코드] {report.eligible}건"
        + (
            "  (대상 외 kind: "
            + ", ".join(f"{k} {v}" for k, v in sorted(report.skipped_kinds.items()))
            + ")"
            if report.skipped_kinds
            else ""
        ),
        f"[기계 축·전수] 전수 재검산 {report.machine_checked}건 "
        f"실패 {len(report.machine_failures)}건",
        f"[사전점검] 결함 0건 통과에 필요한 최소 표본 {report.min_zero_defect_n}건",
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
        lines.extend(f"  - {reason}" for reason in report.machine_failures[:_MAX_REASONS_SHOWN])
    if report.reasons:
        lines.append("판정 사유:")
        lines.extend(f"  - {reason}" for reason in report.reasons[:_MAX_REASONS_SHOWN])
    lines.append(f"판정: {report.outcome}")
    lines.append("=" * 64)
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.residue_cross_verify_eval_v2",
        description=(
            "도메인 플러그인 잔여 축(발문↔형식모델) 교차검증 Wilson 게이트 — "
            "기본 임계·표본은 도메인 설정(DomainGateSpec)에서 온다."
        ),
    )
    parser.add_argument("corpus", type=Path, help="코퍼스 JSONL 경로.")
    parser.add_argument(
        "--domain",
        required=True,
        choices=[*sorted(DOMAIN_SPECS), *sorted(PLANNED_DOMAINS)],
        help="게이트를 걸 도메인. 계획만 있는 도메인은 이름만 받고 거부(exit 2).",
    )
    parser.add_argument("--sample-n", type=int, default=None, help="교차검증 표본 수(도메인 기본).")
    parser.add_argument("--seed", default=None, help="결정론 표본 추출 시드(기본 S4-56:<도메인>).")
    parser.add_argument("--min-n", type=int, default=None, help="판정 최소 표본(도메인 기본).")
    parser.add_argument(
        "--max-defect-upper", type=float, default=None, help="결함율 Wilson 상한 임계(도메인 기본)."
    )
    parser.add_argument(
        "--max-unresolved", type=int, default=0, help="허용 판정불가 건수(기본 0·측정 실패 무관용)."
    )
    parser.add_argument("--confidence", type=float, default=_DEFAULT_CONFIDENCE, help="신뢰수준.")
    parser.add_argument("--audit-out", type=Path, default=None, help="감사 JSONL 산출 경로.")
    parser.add_argument(
        "--authored-by",
        default=None,
        help=(
            "생성자 서명 선언(서명 기록이 **없는** 레코드만 채움·기록과 충돌하면 거부) — "
            "'llm:<모델 id>' 또는 'deterministic:<생성기>'."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="LLM 0·네트워크 0 — 기계 축 전수 재검산과 사전점검까지만. 결과는 PASS가 아니다.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI — 종료 코드: 0 통과(또는 dry-run 사전점검 통과) · 1 게이트 판정 실패 · 2 측정 불가."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        resolve_spec(args.domain)
    except UnsupportedDomainError as exc:
        print(f"게이트 측정 불가: {exc}", file=sys.stderr)
        return _EXIT_MEASUREMENT_FAIL

    try:
        records = load_pilot_records(args.corpus)
    except (OSError, ValueError) as exc:
        # 코퍼스를 못 읽은 것은 게이트의 판정이 아니다 — 트레이스백(exit 1)과 섞이지 않게 분리한다.
        print(f"게이트 측정 불가: 코퍼스 로드 실패({type(exc).__name__}) — {exc}", file=sys.stderr)
        return _EXIT_MEASUREMENT_FAIL

    # 실 provider는 지연 연결(구성만으로 네트워크 0). dry-run은 검증기를 아예 만들지 않는다 —
    # 관측 sink(Langfuse) 구성조차 없이 돈다.
    verifier: CrossVerifier | None = None if args.dry_run else CrossVerifier()
    try:
        report = run_residue_gate_v2(
            records,
            domain=args.domain,
            verifier=verifier,
            sample_n=args.sample_n,
            min_n=args.min_n,
            max_defect_upper=args.max_defect_upper,
            max_unresolved=args.max_unresolved,
            confidence=args.confidence,
            seed=args.seed,
            authored_by=args.authored_by,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(f"게이트 측정 불가: 인자 오류 — {exc}", file=sys.stderr)
        return _EXIT_MEASUREMENT_FAIL
    finally:
        if verifier is not None:
            verifier.flush_trace()
    if args.audit_out is not None:
        write_audit_jsonl(args.audit_out, report)
    print(format_report(report, confidence=args.confidence))
    return _EXIT_OK if report.exit_ok else _EXIT_GATE_FAIL


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
