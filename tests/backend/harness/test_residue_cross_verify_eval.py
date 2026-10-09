"""잔여 축 교차검증 Wilson 게이트(S4-13 ②) — hermetic(교차검증기 대역·라이브 LLM 0).

검증 축:
  ① 실 파일럿 코퍼스 전건이 **전수 기계 검산**(감사 시점 재검산)을 통과한다.
  ② 잔여 축 만장일치 ok + 충분 표본 → PASS(exit 0).
  ③ **변별력 전수 실측** — 실패해야 할 상황마다 *서로 다른 사유*로 exit 1이 난다:
     MACHINE_FAIL(정답 변조)·TIER_UNSUPPORTED(등급 미명시/범위 밖)·NO_DATA(표본 부족)·
     UNRESOLVED(측정 실패)·DEFECT_RATE(Wilson 상한 초과).
  ④ **측정 실패 ≠ 통과** — 교차검증이 판정을 못 내면 '결함 0건 PASS'가 되지 않는다.
  ⑤ **이중 회계** — 산출 감사 JSONL을 `corpus_audit_eval`이 독립 재판정한다(as-found 병기 포함).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from whymath_backend.harness.corpus_audit_eval import load_audit, summarize
from whymath_backend.harness.finite_probability_batch import (
    CORPUS_DIR_NAME,
    run_finite_probability_batch,
)
from whymath_backend.harness.residue_cross_verify_eval import (
    PilotRecord,
    load_pilot_records,
    run_residue_cross_verify,
    select_sample,
    write_audit_jsonl,
)
from whymath_backend.l3.cross_verify import (
    UNRECORDED_AUTHOR,
    CrossVerificationResult,
    PerspectiveVerdict,
    assert_author_independent,
    deterministic_author,
    llm_author,
)
from whymath_backend.l3.verification_tier import VerificationTier

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PILOT_CORPUS = _REPO_ROOT / "data" / "corpus" / CORPUS_DIR_NAME / "problems.jsonl"


class StubVerifier:
    """교차검증기 대역 — 대상 slug에 따라 정해진 집계를 낸다(LLM 호출 0).

    `CrossVerifier`의 `verify(subject)` 표면만 충족한다. 실 검증기의 라우터·프롬프트 경로는
    `tests/backend/l3/test_cross_verify.py`가 따로 본다(여기선 게이트 배선만 본다).
    """

    def __init__(
        self, *, defects: frozenset[str] = frozenset(), unclear: frozenset[str] = frozenset()
    ):
        self._defects = defects
        self._unclear = unclear
        self.seen: list[str] = []

    def verify(self, subject: object) -> CrossVerificationResult:
        problem_id = subject.problem_id
        self.seen.append(problem_id)
        if problem_id in self._unclear:
            return CrossVerificationResult(
                problem_id,
                (PerspectiveVerdict("p", "unclear", "provider_error", "다운"),),
                "unclear",
                "p:provider_error",
                "측정 실패",
            )
        if problem_id in self._defects:
            return CrossVerificationResult(
                problem_id,
                (PerspectiveVerdict("p", "defect", "model_mismatch", "불일치"),),
                "defect",
                "p:model_mismatch",
                "결함",
            )
        return CrossVerificationResult(
            problem_id, (PerspectiveVerdict("p", "ok", "", "정상"),), "ok", "", "만장일치"
        )


@pytest.fixture(scope="module")
def records() -> list[PilotRecord]:
    if not _PILOT_CORPUS.exists():  # pragma: no cover — 코퍼스 미생성 환경 방어
        pytest.skip(f"파일럿 코퍼스 미존재({_PILOT_CORPUS})")
    return load_pilot_records(_PILOT_CORPUS)


def _run(records: list[PilotRecord], verifier: object, **kwargs: object):
    defaults: dict[str, object] = {
        "sample_n": 34,
        "min_n": 20,
        "max_defect_upper": 0.20,
        "max_unresolved": 0,
    }
    defaults.update(kwargs)
    return run_residue_cross_verify(records, verifier=verifier, **defaults)  # type: ignore[arg-type]


# ── ① 기계 축(전수) ───────────────────────────────────────────────────
def test_pilot_corpus_is_nonempty_and_fully_tiered(records: list[PilotRecord]) -> None:
    assert len(records) >= 30
    assert {r.tier for r in records} == {VerificationTier.MACHINE_EXHAUSTIVE}
    assert {r.answer_kind for r in records} == {"finite_probability", "finite_count"}


def test_machine_axis_reverified_exhaustively_at_audit_time(records: list[PilotRecord]) -> None:
    """저작 시점 게이트와 별개로 감사 시점에 다시 전수로 센다(재현성·변조 검출)."""
    report = _run(records, StubVerifier())
    assert report.machine_checked == len(records)
    assert report.machine_failures == []


# ── ② PASS ───────────────────────────────────────────────────────────
def test_unanimous_ok_sample_passes_wilson_gate(records: list[PilotRecord]) -> None:
    report = _run(records, StubVerifier())
    assert report.outcome == "PASS" and report.passed
    assert report.resolved == len(records) and report.defects == 0
    assert report.defect_upper is not None and report.defect_upper < 0.20


def test_sample_selection_is_deterministic_and_seed_sensitive(records: list[PilotRecord]) -> None:
    a = [r.slug for r in select_sample(records, sample_n=10, seed="S4-13")]
    b = [r.slug for r in select_sample(records, sample_n=10, seed="S4-13")]
    c = [r.slug for r in select_sample(records, sample_n=10, seed="other")]
    assert a == b and a != c


# ── ③④ 변별력 — 실패해야 할 상황마다 다른 사유로 실패 ──────────────────
def test_tampered_answer_is_caught_by_machine_axis(records: list[PilotRecord]) -> None:
    """정답을 변조한 코퍼스는 LLM에 물어보기 전에 기계 축에서 걸린다."""
    tampered = [replace(records[0], answer="7/7")] + list(records[1:])
    report = _run(tampered, StubVerifier())
    assert report.outcome == "MACHINE_FAIL"
    assert any("기계 전수 검산 fail" in reason for reason in report.machine_failures)


def test_missing_tier_is_refused_not_silently_passed(records: list[PilotRecord]) -> None:
    untiered = [replace(records[0], tier=None)] + list(records[1:])
    report = _run(untiered, StubVerifier())
    assert report.outcome == "TIER_UNSUPPORTED"
    assert any("검증 등급 미명시" in reason for reason in report.reasons)


def test_sampled_tier_is_out_of_scope_for_this_gate(records: list[PilotRecord]) -> None:
    """난수 표본 검산 등급은 전수 열거 게이트의 범위 밖 — 통과시키지 않고 명시 거부한다."""
    mixed = [replace(records[0], tier=VerificationTier.MACHINE_SAMPLED)] + list(records[1:])
    report = _run(mixed, StubVerifier())
    assert report.outcome == "TIER_UNSUPPORTED"
    assert any("범위 밖" in reason for reason in report.reasons)


def test_small_sample_is_no_data_not_pass(records: list[PilotRecord]) -> None:
    """작은 표본으로 거짓 통과가 나지 않는다(Wilson 하한 철학의 게이트 판)."""
    report = _run(records, StubVerifier(), sample_n=5, min_n=20)
    assert report.outcome == "NO_DATA" and not report.passed


def test_unresolved_measurement_is_not_a_pass(records: list[PilotRecord]) -> None:
    """교차검증이 판정을 못 내면 '결함 0건 통과'가 아니라 UNRESOLVED로 exit 1."""
    unclear = frozenset({records[0].slug, records[1].slug})
    report = _run(records, StubVerifier(unclear=unclear))
    assert report.outcome == "UNRESOLVED"
    assert report.unresolved == 2 and report.defects == 0
    assert not report.passed


def test_unresolved_tolerance_can_be_declared_explicitly(records: list[PilotRecord]) -> None:
    """허용치를 *명시적으로* 올리면 통과할 수 있다 — 묵인이 아니라 선언이어야 한다."""
    report = _run(records, StubVerifier(unclear=frozenset({records[0].slug})), max_unresolved=1)
    assert report.outcome == "PASS" and report.unresolved == 1


def test_defect_rate_above_threshold_fails(records: list[PilotRecord]) -> None:
    defects = frozenset(r.slug for r in records[:6])
    report = _run(records, StubVerifier(defects=defects), max_defect_upper=0.05)
    assert report.outcome == "DEFECT_RATE"
    assert report.defects == 6
    assert report.defect_upper is not None and report.defect_upper > 0.05
    assert report.defect_classes == {"p:model_mismatch": 6}


def test_single_defect_within_threshold_still_passes(records: list[PilotRecord]) -> None:
    """대조군 — 임계 안이면 통과한다(위 실패가 무차별 실패가 아님)."""
    report = _run(
        records, StubVerifier(defects=frozenset({records[0].slug})), max_defect_upper=0.20
    )
    assert report.outcome == "PASS" and report.defects == 1


# ── ⑤ 이중 회계(감사 JSONL 재판정) ────────────────────────────────────
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


# ── 로더 위생 ─────────────────────────────────────────────────────────
def test_loader_rejects_record_without_verify_clause(tmp_path: Path) -> None:
    """L1 스키마·저작권 위생은 통과하는(=유효한) 레코드라도 verify 절이 없으면 감사가 거부한다.

    S4-17로 `load_pilot_records`가 `load_problem_bank_records`(L1 정본) 경유로 바뀌어, L1이
    먼저 통과시키는 레코드여야 이 감사 전용 불변식(검산 재료 필요)까지 도달한다 — 그래서
    fixture가 최소 무효 dict가 아니라 *L1 통과·verify만 결측*인 완전한 레코드여야 한다.
    """
    record = {
        "slug": "wm-residue-loader-test",
        "source_type": "자체생성",
        "license": "WHYMATH_GENERATED",
        "generation_type": "FULLY_GENERATED",
        "subject": "공통",
        "curriculum_version": "2022_REVISION",
        "valid_from_year": 2025,
        "unit_codes": ["QUAD-EQ"],
        "question_format": "단답형",
        "answer_format": "자연수",
        "difficulty_overall": 2.0,
        "question_text": "q",
        "answer": "1",
        "answer_explanation": "e",
        "achievement_standard_codes": ["[10공수1-02-02]"],
    }
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="verify 절 결측"):
        load_pilot_records(path)


def test_loader_reads_freshly_generated_corpus(tmp_path: Path) -> None:
    """배치 산출물 → 로더 → 게이트가 실제로 이어진다(파이프라인 결선)."""
    out = tmp_path / "problems.jsonl"
    run_finite_probability_batch(n_per_band=20, out_path=out)
    fresh = load_pilot_records(out)
    assert _run(fresh, StubVerifier()).outcome == "PASS"


# ── ⑥ 생성자 ≠ 검증자 (PB-15) ─────────────────────────────────────────
_VERIFIER_SIGNATURE = llm_author("qwen3:30b-a3b")


class GuardedStub(StubVerifier):
    """실 `CrossVerifier.verify`와 같은 순서 — **가드가 먼저**, 통과해야 판정 로직으로 간다.

    위 `StubVerifier`는 가드를 건너뛰므로 하네스가 `IndependenceError`를 어떻게 다루는지 볼 수
    없다. 이 대역은 실제 `assert_author_independent`를 호출한다(검증자 서명만 고정).
    """

    def verify(self, subject: object) -> CrossVerificationResult:
        assert_author_independent(subject.authored_by, _VERIFIER_SIGNATURE)  # type: ignore[attr-defined]
        return super().verify(subject)


def _strip_author_from_all_records(path: Path) -> None:
    """모든 레코드에서 `authored_by` 키를 제거 — 서명이 없던 구 코퍼스 상태를 재현한다."""
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.strip():
            record = json.loads(line)
            record.pop("authored_by", None)
            lines[index] = json.dumps(record, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _legacy(records: list[PilotRecord]) -> list[PilotRecord]:
    """서명 기록이 없는 구 코퍼스 상태 — 실 코퍼스는 PB-17 백필로 서명이 있으므로 지운다."""
    return [replace(r, authored_by=UNRECORDED_AUTHOR) for r in records]


def _set_author_in_first_record(path: Path, author: str) -> None:
    """코퍼스 JSONL의 첫 레코드에만 `authored_by`를 심는다(나머지는 키 없음 = 기록 없음)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.strip() and not line.lstrip().startswith("#"):
            record = json.loads(line)
            record["authored_by"] = author
            lines[index] = json.dumps(record, ensure_ascii=False)
            break
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_loader_reads_recorded_author_and_never_fabricates_a_corpus_prefix(tmp_path: Path) -> None:
    """기록된 서명은 그대로, 기록 없는 레코드는 `unknown` — `corpus:<유형>`을 지어내지 않는다.

    종전 로더는 모든 레코드에 `corpus:FULLY_GENERATED`를 조립했다. 그 값은 검증자 서명과 형식이
    달라 가드를 영영 비껴갔다. 두 방향을 한 번에 본다: 기록 있음(값 보존)·기록 없음(`unknown`).
    """
    out = tmp_path / "problems.jsonl"
    run_finite_probability_batch(n_per_band=20, out_path=out)
    _strip_author_from_all_records(
        out
    )  # PB-17: 신규 배치는 서명을 찍으므로 구 코퍼스 상태로 되돌린다.
    _set_author_in_first_record(out, "llm:some-model")

    loaded = load_pilot_records(out)

    assert [r.authored_by for r in loaded].count("llm:some-model") == 1
    assert {r.authored_by for r in loaded} == {"llm:some-model", UNRECORDED_AUTHOR}
    assert not any(r.authored_by.startswith("corpus:") for r in loaded)


def test_record_without_author_is_independence_unproven_not_a_pass(
    records: list[PilotRecord],
) -> None:
    """서명 기록이 없는 구 코퍼스 — 독립성을 입증할 수 없으므로 PASS가 아니다(기본 동작 전환).

    측정이 *시작되기 전에* 멈춘다: 가드가 첫 건에서 발화해 어떤 라벨도 만들지 않는다.
    """
    stub = GuardedStub()
    report = _run(_legacy(records), stub)

    assert report.outcome == "INDEPENDENCE_UNPROVEN"
    assert not report.passed
    assert "판독할 수 없다" in report.reasons[0]
    assert report.resolved == 0 and report.labels == []
    assert stub.seen == [], "가드가 판정보다 먼저여야 한다 — 자기승인 라벨이 하나라도 생기면 무효"


def test_self_approval_from_recorded_author_is_independence_unproven(
    records: list[PilotRecord],
) -> None:
    """코퍼스에 기록된 생성 모델이 검증 모델과 같다 — 자기승인은 품질 실패가 아니라 측정 무효."""
    same_model = [replace(r, authored_by=_VERIFIER_SIGNATURE) for r in records]
    report = _run(same_model, GuardedStub())

    assert report.outcome == "INDEPENDENCE_UNPROVEN"
    assert "자기승인" in report.reasons[0]


def test_recorded_other_model_or_declared_deterministic_author_passes(
    records: list[PilotRecord],
) -> None:
    """대조군 — 다른 LLM이 만들었거나 결정론 생성기로 선언된 코퍼스는 정상 PASS한다.

    이 두 단언이 없으면 '기록이 있어도 전부 거부'하는 과잉 수정도 위 테스트를 통과한다.
    """
    other_llm = [replace(r, authored_by=llm_author("other-model:7b")) for r in records]
    deterministic = [
        replace(r, authored_by=deterministic_author("finite_enumerator")) for r in records
    ]

    assert _run(other_llm, GuardedStub()).outcome == "PASS"
    assert _run(deterministic, GuardedStub()).outcome == "PASS"


def test_declared_author_override_fills_a_legacy_corpus(records: list[PilotRecord]) -> None:
    """`--authored-by` 선언 — 기록 없는 구 코퍼스를 사람이 저작 주체를 선언해 돌릴 수 있다."""
    declared = deterministic_author("finite_enumerator")
    report = _run(_legacy(records), GuardedStub(), authored_by=declared)

    assert report.outcome == "PASS"


# ── ⑦ 저작 서명 백필·선언 좁힘 (PB-17) ────────────────────────────────
def test_backfilled_real_corpus_runs_without_any_declaration(records: list[PilotRecord]) -> None:
    """PB-17 목적 — 백필된 실 코퍼스는 `--authored-by` 선언 없이 가드를 통과한다."""
    assert all(r.authored_by.startswith("deterministic:") for r in records)
    assert _run(records, GuardedStub()).outcome == "PASS"


def test_declaration_cannot_overwrite_a_recorded_llm_author(records: list[PilotRecord]) -> None:
    """③ 핵심 — 기록된 LLM 저작분을 `deterministic:`으로 선언해 가드를 우회할 수 없다.

    종전 `declared or recorded`는 이 선언이 기록을 덮어써 자기승인 검사를 건너뛰게 했다.
    기록이 검증자와 같은 모델이라 원래대로면 자기승인으로 거부돼야 하는 상황이다.
    """
    llm_recorded = [replace(r, authored_by=_VERIFIER_SIGNATURE) for r in records]
    stub = GuardedStub()
    report = _run(llm_recorded, stub, authored_by=deterministic_author("fake"))

    assert report.outcome == "INDEPENDENCE_UNPROVEN"
    assert "충돌" in report.reasons[0]
    assert stub.seen == [], "충돌한 측정은 어떤 라벨도 만들지 않는다"


def test_declaration_equal_to_the_record_is_harmless(records: list[PilotRecord]) -> None:
    """대조군 — 기록과 같은 선언은 충돌이 아니다(과잉 거부 방지)."""
    recorded = [replace(r, authored_by=llm_author("other-model:7b")) for r in records]
    report = _run(recorded, GuardedStub(), authored_by=llm_author("OTHER-model:7b"))
    assert report.outcome == "PASS"


def test_declaration_only_fills_unrecorded_records_in_a_mixed_corpus(
    records: list[PilotRecord],
) -> None:
    """혼합 코퍼스 — 기록 있는 레코드는 그대로, 기록 없는 레코드만 선언으로 채워진다."""
    mixed = [
        (
            replace(r, authored_by=llm_author("other-model:7b"))
            if i % 2 == 0
            else replace(r, authored_by=UNRECORDED_AUTHOR)
        )
        for i, r in enumerate(records)
    ]
    # 선언이 'other-model:7b'와 다르면 기록 있는 쪽과 충돌한다.
    conflict = _run(mixed, GuardedStub(), authored_by=deterministic_author("g"))
    assert conflict.outcome == "INDEPENDENCE_UNPROVEN"
    # 선언이 기록과 같으면(표기 무시) 기록 없는 쪽은 채워지고 전체가 통과한다.
    ok = _run(mixed, GuardedStub(), authored_by=llm_author("other-model:7b"))
    assert ok.outcome == "PASS"


def test_fresh_batch_output_carries_deterministic_signature(tmp_path: Path) -> None:
    """결정론 생성기가 만든 신규 배치는 서명이 찍혀 선언 없이 로더·가드를 지난다(생성 시점 서명)."""
    out = tmp_path / "problems.jsonl"
    run_finite_probability_batch(n_per_band=20, out_path=out)
    fresh = load_pilot_records(out)
    assert {r.authored_by for r in fresh} == {
        deterministic_author("finite_probability_skeleton_generator")
    }
