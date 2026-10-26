"""잔여 축 교차검증 게이트 v2(S4-56) — hermetic(교차검증기 대역·라이브 LLM 0).

검증 축:
  ① 레지스트리 정합 — 게이트가 verifier·관점 세트의 **단일 출처**(`l3/verifier`)와 어긋나지 않는다.
     새 관점 세트가 게이트 설정 없이 늘면 RED(통과할 수 없는 게이트·누락된 게이트 양쪽 차단).
  ② 기본 임계의 도달 가능성 — 도메인 기본값이 *무결함 로트도 통과할 수 없는 조합*이 아니다
     (v1 기본 sample 30 · 상한 0.05 → 0.0827의 함정).
  ③ **변별력 전수** — 실패해야 할 상황마다 *서로 다른 사유*로 exit 1이 나고, 대조군이 통과한다.
  ④ **LLM 호출 전 거부** — 도달 불가 임계·기계 실패·서명 판독 불가는 검증기를 *한 번도 부르지 않고*
     끝난다(비용을 쓰기 전에 성립 불가한 측정을 막는 것이 v2의 존재 이유).
  ⑤ dry-run은 통과 위장이 아니다 — `DRY_RUN_OK`는 `PASS`가 아니고 라벨·감사 기록을 만들지 않는다.
  ⑥ 도메인 일반성 — 코퍼스 소비처가 없는 도메인(`statistical_claim`·`sequence_induction`)도 합성
     레코드로 같은 경로를 밟고, 서빙 경로와 **같은 관점 세트·같은 대상 조립**을 쓴다.
  ⑦ CLI 종료 코드 3분리 — 0 통과 · 1 게이트 실패 · 2 측정 불가.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import residue_cross_verify_eval_v2 as gate
from whymath_backend.harness.corpus_audit_eval import load_audit, summarize
from whymath_backend.harness.finite_probability_batch import CORPUS_DIR_NAME
from whymath_backend.harness.residue_cross_verify_eval import PilotRecord, load_pilot_records
from whymath_backend.harness.residue_cross_verify_eval_v2 import (
    DOMAIN_SPECS,
    PLANNED_DOMAINS,
    UnsupportedDomainError,
    min_zero_defect_n,
    resolve_spec,
    run_residue_gate_v2,
    write_audit_jsonl,
)
from whymath_backend.harness.wilson import wilson_upper_bound
from whymath_backend.l3.cross_verify import (
    SEQUENCE_PERSPECTIVES,
    STATISTICAL_PERSPECTIVES,
    UNRECORDED_AUTHOR,
    CrossVerificationResult,
    IndependenceError,
    PerspectiveVerdict,
    ResidueSubject,
    assert_author_independent,
)
from whymath_backend.l3.verification_tier import VerificationTier
from whymath_backend.l3.verifier import (
    _CROSS_VERIFY_PERSPECTIVES,
    _VERIFIERS_V2,
    ProblemVerifyInput,
    Verifier,
    build_residue_subject,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PILOT_CORPUS = _REPO_ROOT / "data" / "corpus" / CORPUS_DIR_NAME / "problems.jsonl"
# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
_FACTS = json.loads(
    (_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
)

_VERIFIER_SIGNATURE = "llm:stub-verifier-model"


class StubVerifier:
    """교차검증기 대역 — 받은 대상·관점을 기록하고 slug별로 정해진 집계를 낸다(LLM 호출 0)."""

    def __init__(
        self,
        *,
        defects: frozenset[str] = frozenset(),
        unclear: frozenset[str] = frozenset(),
        guarded: bool = False,
    ) -> None:
        self._defects = defects
        self._unclear = unclear
        self._guarded = guarded
        self.subjects: list[ResidueSubject] = []
        self.perspective_sets: list[Any] = []

    @property
    def seen(self) -> list[str]:
        return [s.problem_id for s in self.subjects]

    def verify(self, subject: ResidueSubject, perspectives: Any = None) -> CrossVerificationResult:
        if self._guarded:  # 실 CrossVerifier.verify와 같은 순서 — 가드가 먼저
            assert_author_independent(subject.authored_by, _VERIFIER_SIGNATURE)
        self.subjects.append(subject)
        self.perspective_sets.append(perspectives)
        pid = subject.problem_id
        if pid in self._unclear:
            return CrossVerificationResult(
                pid,
                (PerspectiveVerdict("p", "unclear", "provider_error", "다운"),),
                "unclear",
                "p:provider_error",
                "측정 실패",
            )
        if pid in self._defects:
            return CrossVerificationResult(
                pid,
                (PerspectiveVerdict("p", "defect", "model_mismatch", "불일치"),),
                "defect",
                "p:model_mismatch",
                "결함",
            )
        return CrossVerificationResult(
            pid, (PerspectiveVerdict("p", "ok", "", "정상"),), "ok", "", "만장일치"
        )

    def flush_trace(self) -> None:  # CLI 경로가 호출 — 대역은 할 일이 없다
        return None


@pytest.fixture(scope="module")
def records() -> list[PilotRecord]:
    if not _PILOT_CORPUS.exists():  # pragma: no cover — 코퍼스 미생성 환경 방어
        pytest.skip(f"파일럿 코퍼스 미존재({_PILOT_CORPUS})")
    return load_pilot_records(_PILOT_CORPUS)


def _run(records: list[PilotRecord], verifier: Any, **kwargs: Any) -> gate.ResidueGateReportV2:
    """34문 파일럿에서 *도달 가능한* 임계(0.20)로 돈다 — 기본 임계 거동은 따로 본다."""
    defaults: dict[str, Any] = {
        "domain": "finite",
        "sample_n": 34,
        "min_n": 20,
        "max_defect_upper": 0.20,
        "max_unresolved": 0,
    }
    defaults.update(kwargs)
    return run_residue_gate_v2(records, verifier=verifier, **defaults)


# ── ① 레지스트리 정합 ─────────────────────────────────────────────────
def test_every_spec_kind_has_a_verifier_and_a_perspective_set() -> None:
    """게이트 설정이 가리키는 kind는 전부 서빙 경로(`l3/verifier`)에 등록돼 있다."""
    for name, spec in DOMAIN_SPECS.items():
        assert name == spec.name
        assert spec.answer_kinds, f"{name}: kind 없음"
        for kind in spec.answer_kinds:
            assert kind in _VERIFIERS_V2, f"{name}: {kind} 도메인 verifier 미등록"
            assert kind in _CROSS_VERIFY_PERSPECTIVES, f"{name}: {kind} 관점 미등록"
        resolve_spec(name)  # 예외 없이 통과


def test_every_registered_perspective_kind_is_reachable_by_some_gate_spec() -> None:
    """관점 세트가 늘었는데 게이트 설정이 없으면 RED — 심사는 되는데 로트 게이트가 없는 상태 차단."""
    covered = {kind for spec in DOMAIN_SPECS.values() for kind in spec.answer_kinds}
    missing = set(_CROSS_VERIFY_PERSPECTIVES) - covered
    assert not missing, f"관점 세트는 있으나 게이트 설정이 없는 kind: {sorted(missing)}"


def test_planned_domains_are_not_secretly_implemented() -> None:
    """계획만 있는 도메인은 실제 구현이 없어야 한다 — 구현되면 PLANNED에서 DOMAIN_SPECS로 옮겨라."""
    assert not set(PLANNED_DOMAINS) & set(DOMAIN_SPECS)
    for name in PLANNED_DOMAINS:
        assert name not in _VERIFIERS_V2, f"{name}가 구현됐다 — PLANNED_DOMAINS에서 승격하라"
        assert name not in _CROSS_VERIFY_PERSPECTIVES


def test_planned_and_unknown_domains_are_refused_with_distinct_reasons() -> None:
    with pytest.raises(UnsupportedDomainError, match="미착수"):
        resolve_spec("geometric_discrete")
    with pytest.raises(UnsupportedDomainError, match="알 수 없는 도메인"):
        resolve_spec("no_such_domain")


# ── ② 기본 임계의 도달 가능성 ─────────────────────────────────────────
def test_zero_defect_minimum_n_matches_the_design_table() -> None:
    """설계 부록 FC-4 표(95%·0.05)와 같다 — n=51은 0.0504로 불통과, n=52는 0.0495로 통과."""
    assert min_zero_defect_n(0.05, 0.95) == 52
    assert wilson_upper_bound(0, 51, 0.95) > 0.05
    assert wilson_upper_bound(0, 52, 0.95) <= 0.05
    assert min_zero_defect_n(0.11, 0.95) == 22


def test_min_zero_defect_n_is_the_exact_boundary_for_other_thresholds() -> None:
    """닫힌 식 시작값이 아니라 판정 함수 기준의 정확한 경계다(여러 임계에서 양쪽을 본다)."""
    for p in (0.02, 0.05, 0.10, 0.20):
        for conf in (0.90, 0.95, 0.99):
            n = min_zero_defect_n(p, conf)
            assert wilson_upper_bound(0, n, conf) <= p
            assert n == 1 or wilson_upper_bound(0, n - 1, conf) > p


def test_every_domain_default_is_passable_by_a_flawless_lot() -> None:
    """도메인 기본값이 *무결함 로트도 통과 못 하는 조합*이면 RED — v1 기본(30·0.05)의 함정 재발 차단."""
    for spec in DOMAIN_SPECS.values():
        assert spec.sample_n >= 1 and spec.min_n <= spec.sample_n, spec.name
        upper = wilson_upper_bound(0, spec.sample_n, 0.95)
        assert (
            upper <= spec.max_defect_upper
        ), f"{spec.name}: 결함 0건이어도 상한 {upper:.4f} > 임계 {spec.max_defect_upper}"


def test_invalid_threshold_is_rejected_not_silently_accepted() -> None:
    for bad in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            min_zero_defect_n(bad)


# ── ③ 변별력 전수(34문 파일럿 · 대역) ──────────────────────────────────
def test_pilot_passes_with_reachable_threshold(records: list[PilotRecord]) -> None:
    stub = StubVerifier()
    report = _run(records, stub)
    assert report.outcome == "PASS" and report.passed and report.exit_ok
    pilot = _FACTS["problem_bank.probability_finite_v0"]  # 적격 = 파일럿 은행 전건
    assert report.eligible == pilot and report.machine_checked == pilot
    assert report.sampled == 34  # 표본 크기는 입력(sample_n=34)이다
    assert len(stub.subjects) == 34 and report.defects == 0


def test_domain_filter_selects_only_matching_kind_and_reports_the_rest(
    records: list[PilotRecord],
) -> None:
    """`finite_count`만 걸면 8건만 심사하고, 대상 외 kind는 *세어서 보고한다*(조용히 버리지 않는다)."""
    stub = StubVerifier()
    report = _run(records, stub, domain="finite_count", sample_n=8, min_n=1, max_defect_upper=0.5)
    assert report.eligible == 8 and report.sampled == 8
    assert report.skipped_kinds == {"finite_probability": 26}
    assert {s.problem_id for s in stub.subjects} == {
        r.slug for r in records if r.answer_kind == "finite_count"
    }


def test_domain_with_zero_records_is_no_data_not_a_vacuous_pass(
    records: list[PilotRecord],
) -> None:
    """스캔 0건은 통과가 아니다 — 소비처 없는 도메인이 초록이 되지 않는다."""
    stub = StubVerifier()
    report = _run(records, stub, domain="statistical_claim")
    assert report.outcome == "NO_DATA" and not report.exit_ok
    assert report.eligible == 0 and stub.subjects == []


def test_tampered_answer_is_machine_fail_and_never_reaches_the_verifier(
    records: list[PilotRecord],
) -> None:
    tampered = [replace(records[0], answer="999999")] + records[1:]
    stub = StubVerifier()
    report = _run(tampered, stub)
    assert report.outcome == "MACHINE_FAIL" and not report.exit_ok
    assert any(records[0].slug in m for m in report.machine_failures)
    assert stub.subjects == []  # 기계 축 실패는 LLM에게 물을 것도 없다


def test_duplicate_slug_is_a_corpus_defect_not_silently_collapsed(
    records: list[PilotRecord],
) -> None:
    """slug로 결과를 색인하므로 중복은 한쪽이 조용히 사라진다 — 실패로 드러내야 한다."""
    doubled = [*records, records[0]]
    report = _run(doubled, StubVerifier())
    assert report.outcome == "MACHINE_FAIL"
    assert any("slug 중복" in m for m in report.machine_failures)


def test_missing_tier_is_refused_not_silently_passed(records: list[PilotRecord]) -> None:
    report = _run([replace(records[0], tier=None)] + records[1:], StubVerifier())
    assert report.outcome == "TIER_UNSUPPORTED"


@pytest.mark.parametrize(
    "tier",
    [
        VerificationTier.MACHINE_SAMPLED,
        VerificationTier.NUMERIC_SAMPLING,
        VerificationTier.STATISTICAL_ESTIMATE,
        VerificationTier.HUMAN_REVIEWED,
    ],
)
def test_non_exhaustive_tiers_are_out_of_scope(
    records: list[PilotRecord], tier: VerificationTier
) -> None:
    """'다시 센다'는 이 게이트의 전제 밖 등급은 거부된다(표본 추정·인간 검수 등급)."""
    report = _run([replace(records[0], tier=tier)] + records[1:], StubVerifier())
    assert report.outcome == "TIER_UNSUPPORTED"
    assert any(records[0].slug in r for r in report.reasons)


def test_legacy_and_new_exhaustive_tier_spellings_are_both_accepted(
    records: list[PilotRecord],
) -> None:
    """대조군 — 레거시 `machine_exhaustive`와 신규 `finite_exhaustive`는 같은 등급으로 읽힌다."""
    assert records[0].tier is VerificationTier.MACHINE_EXHAUSTIVE  # 실 코퍼스는 레거시 표기
    modern = [replace(r, tier=VerificationTier.FINITE_EXHAUSTIVE) for r in records]
    assert _run(records, StubVerifier()).outcome == "PASS"
    assert _run(modern, StubVerifier()).outcome == "PASS"


def test_unresolved_measurement_is_not_a_pass(records: list[PilotRecord]) -> None:
    unclear = frozenset({records[0].slug, records[1].slug})
    report = _run(records, StubVerifier(unclear=unclear))
    assert report.outcome == "UNRESOLVED" and report.unresolved == 2 and not report.exit_ok


def test_unresolved_tolerance_can_be_declared_explicitly(records: list[PilotRecord]) -> None:
    report = _run(records, StubVerifier(unclear=frozenset({records[0].slug})), max_unresolved=1)
    assert report.outcome == "PASS" and report.unresolved == 1


def test_tolerated_unresolved_cannot_shrink_the_sample_below_the_minimum(
    records: list[PilotRecord],
) -> None:
    """판정불가를 *허용*해도 판정 가능한 표본이 최소 아래로 줄면 NO_DATA — 통과가 아니다.

    사전점검은 *뽑은* 표본 크기만 본다. 심사 도중 판정불가가 늘어 판정 가능 표본이 줄어드는 경로는
    사후 점검이 따로 막는다(이 분기를 안 밟으면 사후 NO_DATA 절이 지워져도 초록이다).
    """
    stub = StubVerifier(unclear=frozenset({records[0].slug}))
    report = _run(records, stub, sample_n=34, min_n=34, max_unresolved=1)
    assert len(stub.subjects) == 34  # 사전점검은 통과했다(표본 34 ≥ 최소 34)
    assert report.unresolved == 1 and report.resolved == 33
    assert report.outcome == "NO_DATA" and not report.exit_ok


def test_defect_rate_above_threshold_fails(records: list[PilotRecord]) -> None:
    defects = frozenset(r.slug for r in records[:6])
    report = _run(records, StubVerifier(defects=defects))
    assert report.outcome == "DEFECT_RATE" and report.defects == 6
    assert report.defect_upper is not None and report.defect_upper > 0.20
    assert report.defect_classes == {"p:model_mismatch": 6}


def test_single_defect_within_threshold_still_passes(records: list[PilotRecord]) -> None:
    """대조군 — 임계 안이면 통과한다(위 실패가 무차별 실패가 아님)."""
    report = _run(records, StubVerifier(defects=frozenset({records[0].slug})))
    assert report.outcome == "PASS" and report.defects == 1


def test_sample_is_deterministic_and_seed_sensitive(records: list[PilotRecord]) -> None:
    first, second, other = StubVerifier(), StubVerifier(), StubVerifier()
    kwargs: dict[str, Any] = {"sample_n": 22, "min_n": 20, "max_defect_upper": 0.2}
    _run(records, first, **kwargs)
    _run(records, second, **kwargs)
    _run(records, other, seed="다른-시드", **kwargs)
    assert first.seen == second.seen
    assert set(first.seen) != set(other.seen)


# ── ④ LLM 호출 전 거부 ────────────────────────────────────────────────
def test_default_threshold_on_the_34_pilot_is_unreachable_and_never_calls_the_llm(
    records: list[PilotRecord],
) -> None:
    """기본 임계(0.05)는 34문 파일럿으로 통과 불가 — v1은 34건을 다 호출한 뒤 DEFECT_RATE로 실패했다."""
    stub = StubVerifier()
    report = run_residue_gate_v2(records, domain="finite", verifier=stub)
    assert report.outcome == "THRESHOLD_UNREACHABLE" and not report.exit_ok
    assert stub.subjects == []
    assert report.min_zero_defect_n == 52
    assert any("52건 이상" in r for r in report.reasons)


def test_unreachable_is_decided_before_insufficient_sample(records: list[PilotRecord]) -> None:
    """두 사유가 겹치면 더 강한 진단(통계적 불가능)을 낸다 — 고칠 곳(임계/표본)을 정확히 가리킨다."""
    report = _run(records, StubVerifier(), min_n=52, max_defect_upper=0.05)
    assert report.outcome == "THRESHOLD_UNREACHABLE"


def test_insufficient_sample_is_no_data_when_the_threshold_is_reachable(
    records: list[PilotRecord],
) -> None:
    stub = StubVerifier()
    report = _run(records, stub, sample_n=34, min_n=40, max_defect_upper=0.20)
    assert report.outcome == "NO_DATA" and stub.subjects == []


def test_reachability_boundary_is_exact_at_n34(records: list[PilotRecord]) -> None:
    """n=34의 결함 0건 상한은 0.0737 — 바로 위 임계는 통과, 바로 아래는 도달 불가(양쪽 대조)."""
    upper = wilson_upper_bound(0, 34, 0.95)
    assert 0.0736 < upper < 0.0738
    assert _run(records, StubVerifier(), max_defect_upper=0.0738).outcome == "PASS"
    assert _run(records, StubVerifier(), max_defect_upper=0.0736).outcome == (
        "THRESHOLD_UNREACHABLE"
    )


def test_unrecorded_author_is_refused_before_the_first_call(records: list[PilotRecord]) -> None:
    """서명이 없는 표본이 하나라도 있으면 측정 전체가 무효 — 첫 호출 *전에* 멈춘다."""
    legacy = [replace(r, authored_by=UNRECORDED_AUTHOR) for r in records]
    stub = StubVerifier()
    report = _run(legacy, stub)
    assert report.outcome == "INDEPENDENCE_UNPROVEN" and stub.subjects == []
    assert len(report.reasons) == 20  # 표본 34건 중 출력 상한까지 — 전건이 거부 사유


def test_declared_author_fills_only_unrecorded_records(records: list[PilotRecord]) -> None:
    legacy = [replace(r, authored_by=UNRECORDED_AUTHOR) for r in records]
    stub = StubVerifier()
    report = _run(legacy, stub, authored_by="deterministic:finite-test")
    assert report.outcome == "PASS"
    assert {s.authored_by for s in stub.subjects} == {"deterministic:finite-test"}


def test_declaration_cannot_overwrite_a_recorded_author(records: list[PilotRecord]) -> None:
    """기록이 있는 레코드를 선언으로 뒤집을 수 없다(LLM 저작분을 결정론으로 위장하는 우회 차단)."""
    recorded = [replace(r, authored_by="llm:some-model") for r in records]
    stub = StubVerifier()
    report = _run(recorded, stub, authored_by="deterministic:evasion")
    assert report.outcome == "INDEPENDENCE_UNPROVEN" and stub.subjects == []


def test_self_approval_stops_at_the_first_call(records: list[PilotRecord]) -> None:
    """검증자 서명은 호출 시점에 정해진다 — 같은 모델이 만든 문항은 첫 건에서 멈춘다."""
    self_made = [replace(r, authored_by=_VERIFIER_SIGNATURE) for r in records]
    stub = StubVerifier(guarded=True)
    with pytest.raises(IndependenceError):
        stub.verify(ResidueSubject("x", "q", "a", "e", "m", 0, 0, authored_by=_VERIFIER_SIGNATURE))
    report = _run(self_made, stub)
    assert report.outcome == "INDEPENDENCE_UNPROVEN"
    assert stub.subjects == []  # 가드가 첫 호출에서 막았다 — 두 번째 호출 없음


def test_recorded_deterministic_author_passes_the_guard(records: list[PilotRecord]) -> None:
    """대조군 — 결정론 서명은 가드를 통과한다(위 거부가 무차별 거부가 아님)."""
    report = _run(records, StubVerifier(guarded=True))
    assert report.outcome == "PASS"


# ── ⑤ dry-run은 통과 위장이 아니다 ────────────────────────────────────
def test_dry_run_is_not_a_pass_and_needs_no_verifier(records: list[PilotRecord]) -> None:
    report = _run(records, None, dry_run=True)
    assert report.outcome == "DRY_RUN_OK"
    assert report.exit_ok and not report.passed  # 종료 코드는 0이나 PASS가 아니다
    assert report.labels == [] and report.resolved == 0 and report.defect_upper is None
    assert any("통과(PASS)가 아니다" in r for r in report.reasons)


def test_dry_run_still_runs_the_machine_axis_and_the_preflights(
    records: list[PilotRecord],
) -> None:
    """dry-run이 사전점검을 건너뛰면 CI 배선 검사가 실제 실행의 실패를 못 본다."""
    tampered = [replace(records[0], answer="999999")] + records[1:]
    assert _run(tampered, None, dry_run=True).outcome == "MACHINE_FAIL"
    assert run_residue_gate_v2(records, domain="finite", verifier=None, dry_run=True).outcome == (
        "THRESHOLD_UNREACHABLE"
    )
    legacy = [replace(r, authored_by=UNRECORDED_AUTHOR) for r in records]
    assert _run(legacy, None, dry_run=True).outcome == "INDEPENDENCE_UNPROVEN"


def test_real_run_without_a_verifier_is_refused(records: list[PilotRecord]) -> None:
    """측정 없이 통과를 만들 수 있는 조합(dry_run=False·verifier=None)은 허용하지 않는다."""
    with pytest.raises(ValueError, match="교차검증기가 필요"):
        _run(records, None)


@pytest.mark.parametrize(
    "bad",
    [
        {"sample_n": 0},
        {"min_n": 0},
        {"max_defect_upper": 0.0},
        {"max_defect_upper": 1.0},
        {"max_unresolved": -1},
        {"confidence": 1.0},
    ],
)
def test_out_of_range_parameters_are_rejected(
    records: list[PilotRecord], bad: dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        _run(records, StubVerifier(), **bad)


# ── 감사 JSONL(이중 회계) ─────────────────────────────────────────────
def test_audit_jsonl_roundtrips_through_corpus_audit_eval(
    records: list[PilotRecord], tmp_path: Path
) -> None:
    """산출 파일을 기존 Wilson 감사 CLI가 그대로 재판정 — 인프로세스 판정과 값이 일치한다."""
    report = _run(records, StubVerifier(defects=frozenset({records[0].slug})))
    out = tmp_path / "audit.jsonl"
    write_audit_jsonl(out, report)
    audit = load_audit(out.read_text(encoding="utf-8"))
    assert audit.as_found is not None  # §4.5 as-found 병기 의무
    assert (audit.as_found.as_found_n, audit.as_found.as_found_defects) == (
        report.resolved,
        report.defects,
    )
    replayed = summarize(audit.labels)
    assert replayed.n == report.resolved and replayed.defects == report.defects
    assert replayed.defect_rate_upper_bound(0.95) == report.defect_upper


def test_unmeasured_runs_write_an_empty_audit_file(
    records: list[PilotRecord], tmp_path: Path
) -> None:
    """측정하지 않은 로트에 as-found를 지어내지 않는다 — dry-run·사전점검 실패는 빈 파일."""
    out = tmp_path / "audit.jsonl"
    assert write_audit_jsonl(out, _run(records, None, dry_run=True)) == 0
    assert out.read_text(encoding="utf-8") == ""


# ── ⑥ 도메인 일반성(합성 레코드) · 서빙 경로와의 정합 ───────────────────
def _synthetic(
    kind: str, conditions: str, answer: str, *, index: int, tier: VerificationTier
) -> PilotRecord:
    return PilotRecord(
        slug=f"synthetic-{kind}-{index:02d}",
        question_text=f"합성 문항 {index}",
        answer=answer,
        answer_explanation="합성 해설",
        conditions=conditions,
        answer_kind=kind,
        tier=tier,
        authored_by="deterministic:synthetic-test",
    )


def _stat_records(count: int) -> list[PilotRecord]:
    return [
        _synthetic(
            "statistical_claim",
            f"data=[{i}, {i + 1}, {i + 2}]; stat=mean",
            str(i + 1),
            index=i,
            tier=VerificationTier.DETERMINISTIC_DATA,
        )
        for i in range(count)
    ]


def _seq_records(count: int) -> list[PilotRecord]:
    return [
        _synthetic(
            "sequence_induction",
            f"init=a(1)={i}; rec=a(n+1)=a(n)+6; query=a(12)",
            str(i + 66),
            index=i,
            tier=VerificationTier.DETERMINISTIC_DATA,
        )
        for i in range(count)
    ]


@pytest.mark.parametrize(
    ("domain", "build", "perspectives"),
    [
        ("statistical_claim", _stat_records, STATISTICAL_PERSPECTIVES),
        ("sequence_induction", _seq_records, SEQUENCE_PERSPECTIVES),
    ],
)
def test_data_domains_run_the_same_path_with_their_own_perspectives(
    domain: str, build: Any, perspectives: Any
) -> None:
    """소비처 없는 도메인도 같은 경로를 밟고, 서빙 경로와 **같은 관점 세트 객체**로 심사한다."""
    synthetic = build(6)
    stub = StubVerifier()
    report = run_residue_gate_v2(
        synthetic, domain=domain, verifier=stub, sample_n=6, min_n=6, max_defect_upper=0.5
    )
    assert report.outcome == "PASS" and report.eligible == 6
    assert all(p is perspectives for p in stub.perspective_sets)
    assert all(p is _CROSS_VERIFY_PERSPECTIVES[domain] for p in stub.perspective_sets)


@pytest.mark.parametrize(
    ("domain", "build"),
    [("statistical_claim", _stat_records), ("sequence_induction", _seq_records)],
)
def test_data_domains_catch_a_wrong_answer_in_the_machine_axis(domain: str, build: Any) -> None:
    synthetic = build(6)
    synthetic[0] = replace(synthetic[0], answer="123456789")
    stub = StubVerifier()
    report = run_residue_gate_v2(
        synthetic, domain=domain, verifier=stub, sample_n=6, min_n=6, max_defect_upper=0.5
    )
    assert report.outcome == "MACHINE_FAIL" and stub.subjects == []


def test_unverifiable_machine_axis_is_not_reported_as_a_failure() -> None:
    """못 쟀다(unverifiable)는 틀렸다(fail)와 다른 사유다 — 형식 오류 DSL은 MACHINE_UNVERIFIABLE."""
    synthetic = _seq_records(6)
    synthetic[0] = replace(synthetic[0], conditions="이건 DSL이 아니다")
    report = run_residue_gate_v2(
        synthetic,
        domain="sequence_induction",
        verifier=StubVerifier(),
        sample_n=6,
        min_n=6,
        max_defect_upper=0.5,
    )
    assert report.outcome == "MACHINE_UNVERIFIABLE" and not report.exit_ok


def test_gate_builds_the_same_subject_as_the_serving_path() -> None:
    """게이트와 서빙 경로(`Verifier`)가 **같은 대상**을 심사한다 — 조립 드리프트 차단.

    서빙 경로가 교차검증기에 넘기는 대상을 가로채 게이트가 만든 대상과 필드 단위로 비교한다.
    """
    record = _seq_records(1)[0]
    captured: list[ResidueSubject] = []

    class _Spy:
        def verify(
            self, subject: ResidueSubject, perspectives: Any = None
        ) -> CrossVerificationResult:
            captured.append(subject)
            return CrossVerificationResult(
                subject.problem_id, (PerspectiveVerdict("p", "ok", "", ""),), "ok", "", ""
            )

    problem = ProblemVerifyInput(
        slug=record.slug,
        question_text=record.question_text,
        answer=record.answer,
        answer_kind=record.answer_kind,
        conditions=record.conditions,
        answer_explanation=record.answer_explanation,
        authored_by=record.authored_by,
    )
    import asyncio

    asyncio.run(Verifier(cross_verifier=_Spy()).verify(problem))  # type: ignore[arg-type]
    stub = StubVerifier()
    run_residue_gate_v2(
        [record],
        domain="sequence_induction",
        verifier=stub,
        sample_n=1,
        min_n=1,
        max_defect_upper=0.9,
    )
    assert len(captured) == 1 and len(stub.subjects) == 1
    assert stub.subjects[0] == captured[0]
    assert stub.subjects[0] == build_residue_subject(
        problem, _VERIFIERS_V2["sequence_induction"](record.conditions, record.answer)
    )


# ── ⑦ CLI 종료 코드 3분리 ─────────────────────────────────────────────
_CORPUS_ARG = str(_PILOT_CORPUS)


def test_cli_dry_run_with_reachable_threshold_exits_zero(
    records: list[PilotRecord], capsys: pytest.CaptureFixture[str]
) -> None:
    code = gate.main(
        [_CORPUS_ARG, "--domain", "finite", "--dry-run", "--sample-n", "34", "--min-n", "20",
         "--max-defect-upper", "0.11"]
    )  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0 and "판정: DRY_RUN_OK" in out and "판정: PASS" not in out


def test_cli_default_threshold_on_the_pilot_exits_one(
    records: list[PilotRecord], capsys: pytest.CaptureFixture[str]
) -> None:
    code = gate.main([_CORPUS_ARG, "--domain", "finite", "--dry-run"])
    assert code == 1 and "판정: THRESHOLD_UNREACHABLE" in capsys.readouterr().out


def test_cli_planned_domain_exits_two_not_one(capsys: pytest.CaptureFixture[str]) -> None:
    """게이트가 판정을 못 낸 것(미구현)은 게이트 실패(1)와 다른 코드다."""
    code = gate.main([_CORPUS_ARG, "--domain", "geometric_discrete", "--dry-run"])
    assert code == 2 and "미착수" in capsys.readouterr().err


def test_cli_unreadable_corpus_exits_two_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = gate.main([str(tmp_path / "없는-파일.jsonl"), "--domain", "finite", "--dry-run"])
    assert code == 2 and "코퍼스 로드 실패" in capsys.readouterr().err


def test_cli_out_of_range_argument_exits_two(capsys: pytest.CaptureFixture[str]) -> None:
    code = gate.main([_CORPUS_ARG, "--domain", "finite", "--dry-run", "--max-defect-upper", "0"])
    assert code == 2 and "인자 오류" in capsys.readouterr().err


def test_cli_real_run_writes_audit_and_exits_by_outcome(
    records: list[PilotRecord],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """실 실행 경로(검증기 구성→판정→감사 기록→종료 코드) — 검증기만 대역으로 바꾼다."""
    stub = StubVerifier()
    monkeypatch.setattr(gate, "CrossVerifier", lambda: stub)
    out = tmp_path / "audit.jsonl"
    argv = [_CORPUS_ARG, "--domain", "finite", "--sample-n", "34", "--min-n", "20",
            "--max-defect-upper", "0.20", "--audit-out", str(out)]  # fmt: skip
    code = gate.main(argv)
    assert code == 0 and "판정: PASS" in capsys.readouterr().out
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 35 and lines[-1] == {"as_found_n": 34, "as_found_defects": 0}


def test_cli_dry_run_never_constructs_the_cross_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dry-run은 관측 sink(Langfuse)조차 만들지 않는다 — 구성하면 이 테스트가 터진다."""

    def _boom() -> None:
        raise AssertionError("dry-run이 CrossVerifier를 구성했다")

    monkeypatch.setattr(gate, "CrossVerifier", _boom)
    code = gate.main(
        [_CORPUS_ARG, "--domain", "finite", "--dry-run", "--sample-n", "34", "--min-n", "20",
         "--max-defect-upper", "0.11"]  # fmt: skip
    )
    assert code == 0
