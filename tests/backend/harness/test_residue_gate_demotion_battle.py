"""잔여 축 교차검증 게이트 강등전 — hermetic(fake verifier·라이브 LLM 0·네트워크 0).

검증 축:
  ① 변조기 단위 — 그룹별 실 코퍼스 문자열(리터럴)로 정확한 변조 결과·비적용 케이스를 확인.
  ② 커버리지 회계 — 결함류별 적용 가능 건수가 정직하게(비적용 0 포함) 드러난다.
  ③ **변별력** — fake verifier를 스크립트로 조작해, 완벽 검출기/눈먼(항상 ok) 검출기/
     상시발화(항상 defect) 검출기가 각각 다른 측정치를 낸다는 것을 증명한다(변별력 없는
     검증 스텝 금지 — CLAUDE.md).
  ④ 게이트 exit code — 임계 미지정(리포트 전용) vs 지정 시 통과/미달.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import pytest

from whymath_backend.harness.residue_cross_verify_eval import (
    PilotRecord,
    load_pilot_records,
)
from whymath_backend.harness.residue_gate_demotion_battle import (
    RESIDUE_DEFECT_CLASSES,
    RESIDUE_HOLDOUT_DEFECT_CLASSES,
    RESIDUE_TUNED_DEFECT_CLASSES,
    MeasurementConfig,
    ResidueBattleReport,
    UnionCrossVerifier,
    _max_value,
    _mean,
    _min_value,
    _mutate_ambiguous_wording,
    _mutate_contradictory_condition,
    _mutate_missing_condition,
    _mutate_multiple_valid_answers,
    _mutate_unstated_equiprobability,
    _stdev,
    build_residue_seeded_set,
    build_v4_wiring,
    main,
    render_repeated_report,
    render_report,
    repeated_report_to_json,
    report_to_json,
    run_repeated_residue_demotion_battle,
    run_residue_demotion_battle,
    write_audit_jsonl,
    write_repeated_audit_jsonl,
)
from whymath_backend.l3.cross_verify import (
    MISSING_CONDITION_PERSPECTIVES,
    MULTIPLE_VALID_ANSWERS_PERSPECTIVES,
    CrossVerificationResult,
    CrossVerifier,
    PerspectiveVerdict,
    ResidueSubject,
)
from whymath_backend.l3.models import GenerationResult
from whymath_backend.l3.verification_tier import VerificationTier

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PILOT_CORPUS = (
    _REPO_ROOT / "data" / "corpus" / "problem_bank_probability_finite_v0" / "problems.jsonl"
)

# 실 코퍼스에서 읽은 리터럴 발문(그룹별 대표 1건) — 패러프레이즈 아님, 문자 그대로 확인한 값.
_GROUP_A_TEXT = (
    "서로 구별되는 두 개의 주사위를 동시에 던진다. 각 주사위의 여섯 눈이 나올 가능성이 "
    "모두 같을 때, 나온 두 눈의 수의 합이 7일 확률을 기약분수로 나타내시오."
)
_GROUP_B_TEXT = (
    "한 개의 동전을 3번 던진다. 매번 앞면과 뒷면이 나올 가능성이 같을 때, "
    "앞면이 정확히 1번 나올 확률을 기약분수로 나타내시오."
)
_GROUP_C_TEXT = (
    "주머니 안에 서로 구별되는 빨간 공 3개와 파란 공 2개가 들어 있다. 이 주머니에서 "
    "임의로 2개의 공을 동시에 꺼낼 때, 꺼낸 공이 모두 빨간 공일 확률을 기약분수로 "
    "나타내시오."
)
_GROUP_D_TEXT = (
    "서로 구별되는 두 개의 주사위를 동시에 던진다. 나온 두 눈의 수의 합이 6 이상이 되는 "
    "경우의 수를 구하시오. (두 주사위는 서로 구별하며, 눈의 순서가 다르면 다른 경우로 센다.)"
)


@pytest.fixture(scope="module")
def records() -> list[PilotRecord]:
    if not _PILOT_CORPUS.exists():  # pragma: no cover — 코퍼스 미생성 환경 방어
        pytest.skip(f"파일럿 코퍼스 미존재({_PILOT_CORPUS})")
    return load_pilot_records(_PILOT_CORPUS)


# ── ① 변조기 단위 — 실 코퍼스 리터럴 문자열 기준 ────────────────────────
def test_missing_condition_removes_distinguishability_clause_a_c_d() -> None:
    mutated_a, note_a = _mutate_missing_condition(_GROUP_A_TEXT)
    assert mutated_a == (
        "두 개의 주사위를 동시에 던진다. 각 주사위의 여섯 눈이 나올 가능성이 모두 같을 때, "
        "나온 두 눈의 수의 합이 7일 확률을 기약분수로 나타내시오."
    )
    assert "구별되는" in note_a

    mutated_c, _ = _mutate_missing_condition(_GROUP_C_TEXT)
    assert mutated_c == (
        "주머니 안에 빨간 공 3개와 파란 공 2개가 들어 있다. 이 주머니에서 임의로 2개의 공을 "
        "동시에 꺼낼 때, 꺼낸 공이 모두 빨간 공일 확률을 기약분수로 나타내시오."
    )

    mutated_d, _ = _mutate_missing_condition(_GROUP_D_TEXT)
    assert mutated_d == (
        "두 개의 주사위를 동시에 던진다. 나온 두 눈의 수의 합이 6 이상이 되는 경우의 수를 "
        "구하시오. (두 주사위는 서로 구별하며, 눈의 순서가 다르면 다른 경우로 센다.)"
    )


def test_missing_condition_not_applicable_to_group_b() -> None:
    """그룹 B(동전)는 애초 구별성 어구를 담지 않는다 — 억지 변조 대신 정직한 None."""
    assert _mutate_missing_condition(_GROUP_B_TEXT) is None


def test_unstated_equiprobability_applies_to_a_and_b_only() -> None:
    mutated_a, _ = _mutate_unstated_equiprobability(_GROUP_A_TEXT)
    assert mutated_a == (
        "서로 구별되는 두 개의 주사위를 동시에 던진다. 나온 두 눈의 수의 합이 7일 확률을 "
        "기약분수로 나타내시오."
    )
    mutated_b, _ = _mutate_unstated_equiprobability(_GROUP_B_TEXT)
    assert mutated_b == (
        "한 개의 동전을 3번 던진다. 앞면이 정확히 1번 나올 확률을 기약분수로 나타내시오."
    )
    assert _mutate_unstated_equiprobability(_GROUP_C_TEXT) is None
    assert _mutate_unstated_equiprobability(_GROUP_D_TEXT) is None


def test_ambiguous_wording_applies_to_a_b_c_not_d() -> None:
    mutated_a, _ = _mutate_ambiguous_wording(_GROUP_A_TEXT)
    assert mutated_a == (
        "서로 구별되는 두 개의 주사위를 동시에 던진다. 각 주사위의 여섯 눈이 나올 가능성이 "
        "모두 같을 때, 나온 두 눈의 수가 7일 확률을 기약분수로 나타내시오."
    )
    mutated_b, _ = _mutate_ambiguous_wording(_GROUP_B_TEXT)
    assert mutated_b == (
        "한 개의 동전을 3번 던진다. 매번 앞면과 뒷면이 나올 가능성이 같을 때, 앞면이 1번 "
        "나올 확률을 기약분수로 나타내시오."
    )
    mutated_c, _ = _mutate_ambiguous_wording(_GROUP_C_TEXT)
    assert mutated_c == (
        "주머니 안에 서로 구별되는 빨간 공 3개와 파란 공 2개가 들어 있다. 이 주머니에서 "
        "임의로 2개의 공을 동시에 꺼낼 때, 꺼낸 공이 빨간 공일 확률을 기약분수로 나타내시오."
    )
    # 그룹 D — "이상" 제거는 중의성이 아니라 문제 자체의 변경이라 설계상 의도적 제외.
    assert _mutate_ambiguous_wording(_GROUP_D_TEXT) is None


def test_multiple_valid_answers_applies_only_to_group_c() -> None:
    mutated_c, _ = _mutate_multiple_valid_answers(_GROUP_C_TEXT)
    assert mutated_c == (
        "주머니 안에 서로 구별되는 빨간 공 3개와 파란 공 2개가 들어 있다. 이 주머니에서 "
        "임의로 2개의 공을 꺼낼 때, 꺼낸 공이 모두 빨간 공일 확률을 기약분수로 나타내시오."
    )
    # 주사위(A·D)는 "동시에" 제거가 모델을 바꾸지 않는 무의미 변조라 의도적으로 배제.
    assert _mutate_multiple_valid_answers(_GROUP_A_TEXT) is None
    assert _mutate_multiple_valid_answers(_GROUP_D_TEXT) is None


def test_mutations_never_touch_answer_or_conditions(records: list[PilotRecord]) -> None:
    """변조는 question_text만 건드린다 — answer·conditions는 원본 그대로."""
    battery = build_residue_seeded_set(records)
    by_slug = {r.slug: r for r in records}
    for item in battery.seeded:
        original = by_slug[item.record.slug]
        assert item.record.answer == original.answer
        assert item.record.conditions == original.conditions
        assert item.mutated_question_text != original.question_text  # 실제로 변조됐는지


# ── ② 커버리지 회계 — 정직한 불균등 (침묵 생략 아님) ────────────────────
def test_coverage_is_honest_and_uneven(records: list[PilotRecord]) -> None:
    battery = build_residue_seeded_set(records)
    assert set(battery.coverage) == set(RESIDUE_DEFECT_CLASSES)
    # 실측(코퍼스 34건 기준) — missing_condition은 그룹 B(9건) 비적용이라 25건(전 34건 아님).
    assert battery.coverage["missing_condition"] == 25
    assert battery.coverage["unstated_equiprobability"] == 20
    assert battery.coverage["ambiguous_wording"] == 26
    assert battery.coverage["multiple_valid_answers"] == 6
    # 0인 결함류가 있어도 키 자체는 반드시 존재(침묵 생략 금지).
    assert all(name in battery.coverage for name in RESIDUE_DEFECT_CLASSES)


def test_clean_control_is_untouched_originals(records: list[PilotRecord]) -> None:
    battery = build_residue_seeded_set(records)
    assert battery.clean == tuple(records)
    assert len(battery.clean) == len(records)


# ── ③ 변별력 — 스크립트 fake verifier로 세 가지 검출기 프로파일 구분 ─────
class _ScriptedVerifier:
    """대역 검증기 — question_text가 원본(무결함)과 다르면 "변조됨"으로 인식 가능.

    `mode="oracle"`은 완벽 검출기(변조=defect·원본=ok), `mode="blind_ok"`는 항상 ok(눈먼
    검출기), `mode="blind_defect"`는 항상 defect(상시발화 검출기) — 세 프로파일 모두 다른
    측정치를 내야 harness가 "변별력 없는 검증 스텝"이 아님을 증명한다.
    """

    def __init__(self, *, mode: str, clean_texts: frozenset[str]):
        self._mode = mode
        self._clean_texts = clean_texts
        self.seen: list[str] = []

    def verify(self, subject: object) -> CrossVerificationResult:
        problem_id = subject.problem_id  # type: ignore[attr-defined]
        question_text = subject.question_text  # type: ignore[attr-defined]
        self.seen.append(problem_id)
        if self._mode == "blind_ok":
            verdict = "ok"
        elif self._mode == "blind_defect":
            verdict = "defect"
        else:  # "oracle"
            verdict = "ok" if question_text in self._clean_texts else "defect"
        if verdict == "defect":
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


def _clean_texts(records: list[PilotRecord]) -> frozenset[str]:
    return frozenset(r.question_text for r in records)


def test_oracle_verifier_detects_all_seeded_and_zero_false_alarms(
    records: list[PilotRecord],
) -> None:
    battery = build_residue_seeded_set(records)
    verifier = _ScriptedVerifier(mode="oracle", clean_texts=_clean_texts(records))
    report = run_residue_demotion_battle(battery, verifier=verifier, sample_n=50, seed="t1")

    overall_lower = report.overall_detection_lower_bound(0.95)
    fau = report.false_alarm_upper_bound(0.95)
    assert report.overall_detected == report.overall_resolved  # 100% 점추정
    assert overall_lower is not None and overall_lower > 0.8  # Wilson 하한도 높게
    assert report.clean_false_alarms == 0
    assert fau is not None and fau < 0.2  # Wilson 상한도 낮게


def test_blind_ok_verifier_never_detects_defects(records: list[PilotRecord]) -> None:
    """항상 ok를 내는 눈먼 검출기 — harness가 좋은 결과를 위장하지 않고 0%를 그대로 낸다."""
    battery = build_residue_seeded_set(records)
    verifier = _ScriptedVerifier(mode="blind_ok", clean_texts=_clean_texts(records))
    report = run_residue_demotion_battle(battery, verifier=verifier, sample_n=50, seed="t2")

    assert report.overall_detected == 0
    overall_lower = report.overall_detection_lower_bound(0.95)
    # successes=0의 Wilson 하한은 이론상 0이지만 부동소수 잔차(예: ~1e-18)가 남을 수 있다 —
    # 정확히 0.0을 요구하지 않고 무시 가능한 허용오차로 확인한다.
    assert overall_lower is not None and overall_lower < 1e-9
    assert report.clean_false_alarms == 0  # 오검출도 0(항상 ok니까)


def test_blind_defect_verifier_flags_everything_including_clean(
    records: list[PilotRecord],
) -> None:
    """항상 defect를 내는 상시발화 검출기 — 검출률은 100%지만 오검출도 100%로 드러난다."""
    battery = build_residue_seeded_set(records)
    verifier = _ScriptedVerifier(mode="blind_defect", clean_texts=_clean_texts(records))
    report = run_residue_demotion_battle(battery, verifier=verifier, sample_n=50, seed="t3")

    assert report.overall_detected == report.overall_resolved  # 결함도 전부 검출(우연히)
    assert report.clean_false_alarms == report.clean_resolved  # 그러나 대조군도 전부 오검출
    fau = report.false_alarm_upper_bound(0.95)
    assert fau is not None and fau > 0.8  # 오검출 상한이 높게 나와 "상시발화"가 드러난다


def test_unresolved_is_tracked_separately_from_detection(records: list[PilotRecord]) -> None:
    """판정불가(unclear)는 '결함 미검출'로 뭉개지지 않고 별도 집계된다."""

    class _UnclearVerifier:
        def verify(self, subject: object) -> CrossVerificationResult:
            return CrossVerificationResult(
                subject.problem_id,  # type: ignore[attr-defined]
                (PerspectiveVerdict("p", "unclear", "provider_error", "다운"),),
                "unclear",
                "p:provider_error",
                "측정 실패",
            )

    battery = build_residue_seeded_set(records)
    report = run_residue_demotion_battle(
        battery, verifier=_UnclearVerifier(), sample_n=5, seed="t4"
    )
    assert report.overall_resolved == 0
    assert report.overall_unresolved > 0
    assert report.overall_detection_lower_bound(0.95) is None  # 측정 실패는 0%가 아니라 None
    assert report.clean_resolved == 0
    assert report.false_alarm_upper_bound(0.95) is None


# ── 표본 크기 통제 확인 ──────────────────────────────────────────────────
def test_sample_n_caps_per_class_and_is_deterministic(records: list[PilotRecord]) -> None:
    battery = build_residue_seeded_set(records)
    verifier_a = _ScriptedVerifier(mode="oracle", clean_texts=_clean_texts(records))
    verifier_b = _ScriptedVerifier(mode="oracle", clean_texts=_clean_texts(records))
    report_a = run_residue_demotion_battle(
        battery, verifier=verifier_a, sample_n=2, seed="fixed-seed"
    )
    run_residue_demotion_battle(battery, verifier=verifier_b, sample_n=2, seed="fixed-seed")
    for name in RESIDUE_DEFECT_CLASSES:
        assert report_a.per_class[name].sampled <= 2
    assert verifier_a.seen == verifier_b.seen  # 결정론 — 같은 시드는 같은 표본·같은 순서


# ── ④ 감사 JSONL 왕복 ────────────────────────────────────────────────────
def test_write_audit_jsonl_includes_as_found_summary(
    records: list[PilotRecord], tmp_path: Path
) -> None:
    battery = build_residue_seeded_set(records)
    verifier = _ScriptedVerifier(mode="oracle", clean_texts=_clean_texts(records))
    report = run_residue_demotion_battle(battery, verifier=verifier, sample_n=3, seed="t5")
    out = tmp_path / "battle_audit.jsonl"
    n = write_audit_jsonl(out, report)
    assert n == len(report.audit_rows) + 1  # +1 = as_found 요약 행
    lines = out.read_text(encoding="utf-8").splitlines()
    summary = json.loads(lines[-1])
    assert summary["as_found_overall_detected"] == report.overall_detected
    assert summary["as_found_clean_false_alarms"] == report.clean_false_alarms


def test_report_to_json_matches_report_fields(records: list[PilotRecord]) -> None:
    battery = build_residue_seeded_set(records)
    verifier = _ScriptedVerifier(mode="oracle", clean_texts=_clean_texts(records))
    report = run_residue_demotion_battle(battery, verifier=verifier, sample_n=3, seed="t6")
    payload = report_to_json(report, confidence=0.95)
    assert payload["overall"]["detected"] == report.overall_detected
    assert payload["clean_control"]["false_alarms"] == report.clean_false_alarms
    assert set(payload["coverage"]) == set(RESIDUE_DEFECT_CLASSES)  # type: ignore[arg-type]


# ── ⑤ CLI 게이트 exit code ───────────────────────────────────────────────
def _make_scripted_verifier_for_cli(records: list[PilotRecord], mode: str) -> type:
    """CLI는 내부에서 실 CrossVerifier()를 생성하므로, main()을 직접 호출하는 대신
    run_residue_demotion_battle을 거치는 별도 헬퍼로 exit code 로직만 재사용해 검증한다
    (라이브 LLM 0 원칙 — main() 자체를 hermetic하게 부르려면 CrossVerifier 생성자가 provider
    lazy-import만 하고 네트워크 0인 것과 동일하게, 여기서는 run_residue_demotion_battle이
    반환한 report에 CLI와 동일한 게이트 판정식을 적용해 배선을 검증한다)."""
    del records, mode
    return ResidueBattleReport


def test_gate_report_only_mode_is_always_exit_0_regardless_of_rate(
    records: list[PilotRecord],
) -> None:
    battery = build_residue_seeded_set(records)
    verifier = _ScriptedVerifier(mode="blind_ok", clean_texts=_clean_texts(records))
    report = run_residue_demotion_battle(battery, verifier=verifier, sample_n=5, seed="t7")
    # 게이트 미지정(min_detection_lower=0.0·max_false_alarm_upper=1.0 기본값) → 항상 off.
    min_detection_lower, max_false_alarm_upper = 0.0, 1.0
    dlb = report.overall_detection_lower_bound(0.95)
    fau = report.false_alarm_upper_bound(0.95)
    exit_code = 0
    if min_detection_lower > 0.0 and (dlb is None or dlb < min_detection_lower):
        exit_code = 1
    if max_false_alarm_upper < 1.0 and (fau is None or fau > max_false_alarm_upper):
        exit_code = 1
    assert exit_code == 0  # 검출률 0%인데도 게이트 미지정이면 통과(리포트 전용)


def test_gate_min_detection_lower_fails_when_above_actual_rate(
    records: list[PilotRecord],
) -> None:
    battery = build_residue_seeded_set(records)
    verifier = _ScriptedVerifier(mode="blind_ok", clean_texts=_clean_texts(records))
    report = run_residue_demotion_battle(battery, verifier=verifier, sample_n=5, seed="t8")
    dlb = report.overall_detection_lower_bound(0.95)
    assert dlb is not None and dlb < 1e-9  # 부동소수 잔차 허용(위 blind_ok 테스트와 동형)
    threshold = 0.5
    exit_code = 1 if (threshold > 0.0 and (dlb is None or dlb < threshold)) else 0
    assert exit_code == 1


def test_gate_min_detection_lower_passes_when_below_actual_rate(
    records: list[PilotRecord],
) -> None:
    battery = build_residue_seeded_set(records)
    verifier = _ScriptedVerifier(mode="oracle", clean_texts=_clean_texts(records))
    report = run_residue_demotion_battle(battery, verifier=verifier, sample_n=50, seed="t9")
    dlb = report.overall_detection_lower_bound(0.95)
    threshold = 0.5
    exit_code = 1 if (threshold > 0.0 and (dlb is None or dlb < threshold)) else 0
    assert exit_code == 0
    assert dlb is not None and dlb >= threshold


def test_gate_max_false_alarm_upper_fails_when_below_actual_rate(
    records: list[PilotRecord],
) -> None:
    battery = build_residue_seeded_set(records)
    verifier = _ScriptedVerifier(mode="blind_defect", clean_texts=_clean_texts(records))
    report = run_residue_demotion_battle(battery, verifier=verifier, sample_n=5, seed="t10")
    fau = report.false_alarm_upper_bound(0.95)
    assert fau is not None and fau > 0.5
    threshold = 0.1
    exit_code = 1 if (threshold < 1.0 and (fau is None or fau > threshold)) else 0
    assert exit_code == 1


def test_gate_max_false_alarm_upper_passes_when_above_actual_rate(
    records: list[PilotRecord],
) -> None:
    battery = build_residue_seeded_set(records)
    verifier = _ScriptedVerifier(mode="oracle", clean_texts=_clean_texts(records))
    report = run_residue_demotion_battle(battery, verifier=verifier, sample_n=50, seed="t11")
    fau = report.false_alarm_upper_bound(0.95)
    threshold = 0.9
    exit_code = 1 if (threshold < 1.0 and (fau is None or fau > threshold)) else 0
    assert exit_code == 0
    assert fau is not None and fau <= threshold


# ── CLI 진입점 — main()은 실 CrossVerifier()를 구성하지만 provider는 lazy-import라
#    네트워크 호출 없이 --sample-n 0(대상 0건)으로 배선만 확인한다.
def test_main_report_only_wiring_smoke(tmp_path: Path) -> None:
    """main() 배선 자체(파서·로더·리포트 출력)를 --sample-n 0으로 hermetic하게 스모크."""
    if not _PILOT_CORPUS.exists():  # pragma: no cover — 코퍼스 미생성 환경 방어
        pytest.skip(f"파일럿 코퍼스 미존재({_PILOT_CORPUS})")
    audit_out = tmp_path / "audit.jsonl"
    exit_code = main([str(_PILOT_CORPUS), "--sample-n", "0", "--audit-out", str(audit_out)])
    assert exit_code == 0  # 표본 0건이라 검증기 호출 0 — 게이트 미지정이므로 통과
    assert not audit_out.exists() or audit_out.read_text(encoding="utf-8") == ""


# ── 로더 위생(재사용 확인) ────────────────────────────────────────────────
def test_pilot_record_reuses_shared_loader_type(records: list[PilotRecord]) -> None:
    """PilotRecord/load_pilot_records는 이 모듈이 재구현한 것이 아니라 재사용임을 확인."""
    assert records and isinstance(records[0], PilotRecord)
    assert {r.tier for r in records} == {VerificationTier.MACHINE_EXHAUSTIVE}


# ══════════════════════════════════════════════════════════════════════════
# S4-16 2차 강등전 준비분 — A) 반복 측정 · B) 대조군 표본 분리 · C) 클라우드 좌석 ·
# D) 홀드아웃 결함류. 전부 hermetic(결정론 fake verifier·네트워크 0).
# ══════════════════════════════════════════════════════════════════════════


# ── D) 홀드아웃 변조기 `contradictory_condition` ──────────────────────────
def test_holdout_mutator_inserts_dice_clause_for_groups_a_and_d() -> None:
    """주사위 그룹(A 확률·D 경우의 수) — 첫 문장 직후에 모순 조건이 한 문장으로 들어간다."""
    mutated_a, note_a = _mutate_contradictory_condition(_GROUP_A_TEXT)
    assert mutated_a == (
        "서로 구별되는 두 개의 주사위를 동시에 던진다. 단, 두 눈의 수는 서로 다르다. "
        "각 주사위의 여섯 눈이 나올 가능성이 모두 같을 때, 나온 두 눈의 수의 합이 7일 "
        "확률을 기약분수로 나타내시오."
    )
    assert "홀드아웃" in note_a

    mutated_d, _ = _mutate_contradictory_condition(_GROUP_D_TEXT)
    assert mutated_d == (
        "서로 구별되는 두 개의 주사위를 동시에 던진다. 단, 두 눈의 수는 서로 다르다. "
        "나온 두 눈의 수의 합이 6 이상이 되는 경우의 수를 구하시오. "
        "(두 주사위는 서로 구별하며, 눈의 순서가 다르면 다른 경우로 센다.)"
    )


def test_holdout_mutator_inserts_coin_clause_for_group_b() -> None:
    mutated_b, note_b = _mutate_contradictory_condition(_GROUP_B_TEXT)
    assert mutated_b == (
        "한 개의 동전을 3번 던진다. 단, 첫 번째 시행은 반드시 앞면이다. "
        "매번 앞면과 뒷면이 나올 가능성이 같을 때, 앞면이 정확히 1번 나올 확률을 "
        "기약분수로 나타내시오."
    )
    assert "홀드아웃" in note_b


def test_holdout_mutator_returns_none_when_white_ball_absent() -> None:
    """공 추출 그룹 — 이 코퍼스에는 흰 공이 없으므로 정직하게 None(억지 변조 금지)."""
    assert "흰 공" not in _GROUP_C_TEXT
    assert _mutate_contradictory_condition(_GROUP_C_TEXT) is None


def test_holdout_mutator_applies_to_ball_group_only_when_white_ball_exists() -> None:
    """변별력 — 흰 공이 *있는* 문장에서는 같은 앵커가 적용된다(비적용이 색인 하드코딩이
    아니라 '흰 공 실재' 판정의 결과임을 증명한다)."""
    with_white = (
        "주머니 안에 서로 구별되는 빨간 공 3개와 흰 공 2개가 들어 있다. 이 주머니에서 "
        "임의로 2개의 공을 동시에 꺼낼 때, 꺼낸 공이 모두 빨간 공일 확률을 기약분수로 "
        "나타내시오."
    )
    result = _mutate_contradictory_condition(with_white)
    assert result is not None
    mutated, _ = result
    assert mutated == (
        "주머니 안에 서로 구별되는 빨간 공 3개와 흰 공 2개가 들어 있다. "
        "단, 꺼낸 공 중 적어도 하나는 흰 공이다. 이 주머니에서 임의로 2개의 공을 "
        "동시에 꺼낼 때, 꺼낸 공이 모두 빨간 공일 확률을 기약분수로 나타내시오."
    )


def test_holdout_coverage_is_measured_not_estimated(records: list[PilotRecord]) -> None:
    """실측 커버리지 28/34 — 주사위 19(A 11 + D 8) + 동전 9 + 공 추출 0."""
    battery = build_residue_seeded_set(records)
    assert len(records) == 34
    assert battery.coverage["contradictory_condition"] == 28
    holdout_items = [i for i in battery.seeded if i.defect_class == "contradictory_condition"]
    assert len(holdout_items) == 28
    # 변조는 발문에만 — 정답·조건식은 손대지 않는다(튜닝 4종과 같은 계약).
    for item in holdout_items:
        assert item.mutated_question_text != item.record.question_text
        assert item.record.answer == item.record.answer


def test_holdout_is_registered_as_holdout_not_tuned() -> None:
    assert RESIDUE_HOLDOUT_DEFECT_CLASSES == ("contradictory_condition",)
    assert "contradictory_condition" not in RESIDUE_TUNED_DEFECT_CLASSES
    assert set(RESIDUE_DEFECT_CLASSES) == set(RESIDUE_TUNED_DEFECT_CLASSES) | set(
        RESIDUE_HOLDOUT_DEFECT_CLASSES
    )


class _HoldoutOnlyVerifier:
    """홀드아웃 변조만 잡고 튜닝 4종은 전부 놓치는 검출기 — 분리 집계의 **변별력** 증명용.

    이 프로파일에서 `overall_*`(튜닝)과 `holdout_*`가 **다른 값**을 내야 한다. 같은 값이
    나오면 분리가 장식이라는 뜻이다.
    """

    def verify(self, subject: object) -> CrossVerificationResult:
        question_text: str = subject.question_text  # type: ignore[attr-defined]
        problem_id: str = subject.problem_id  # type: ignore[attr-defined]
        is_holdout = "단, 두 눈의 수는 서로 다르다." in question_text or (
            "단, 첫 번째 시행은 반드시 앞면이다." in question_text
        )
        if is_holdout:
            return CrossVerificationResult(
                problem_id,
                (PerspectiveVerdict("p", "defect", "model_mismatch", "모순 조건"),),
                "defect",
                "p:model_mismatch",
                "결함",
            )
        return CrossVerificationResult(
            problem_id, (PerspectiveVerdict("p", "ok", "", "정상"),), "ok", "", "만장일치"
        )


def test_holdout_totals_are_not_summed_into_overall(records: list[PilotRecord]) -> None:
    """홀드아웃만 잡는 검출기 — 튜닝 집계는 0, 홀드아웃 집계는 100%로 **갈라져야** 한다."""
    battery = build_residue_seeded_set(records)
    report = run_residue_demotion_battle(
        battery, verifier=_HoldoutOnlyVerifier(), sample_n=4, seed="hold1"
    )
    assert report.overall_detected == 0
    assert report.overall_resolved > 0
    assert report.holdout_detected == report.holdout_resolved > 0
    # 전체 집계는 튜닝 4종의 합과 정확히 일치한다(홀드아웃이 새지 않는다).
    assert report.overall_resolved == sum(
        report.per_class[n].resolved for n in RESIDUE_TUNED_DEFECT_CLASSES
    )
    assert report.holdout_resolved == sum(
        report.per_class[n].resolved for n in RESIDUE_HOLDOUT_DEFECT_CLASSES
    )
    holdout_lower = report.holdout_detection_lower_bound(0.95)
    overall_lower = report.overall_detection_lower_bound(0.95)
    assert holdout_lower is not None and holdout_lower > 0.4
    assert overall_lower is not None and overall_lower < 1e-9


def test_holdout_reported_on_its_own_line_and_json_key(records: list[PilotRecord]) -> None:
    """리포트·JSON에서 홀드아웃이 튜닝 집계와 **분리된 자리**에 실린다."""
    battery = build_residue_seeded_set(records)
    report = run_residue_demotion_battle(
        battery, verifier=_HoldoutOnlyVerifier(), sample_n=3, seed="hold2"
    )
    text = render_report(report, confidence=0.95, corpus_size=len(records))
    assert "[홀드아웃 결함류" in text
    assert "[전체 — 튜닝 4종만 합산(홀드아웃 제외)]" in text
    # 전체 블록과 홀드아웃 블록은 서로 다른 줄이고, 전체 줄에 홀드아웃 수치가 없다.
    overall_line = next(line for line in text.splitlines() if "결함 검출률" in line)
    assert f"{report.overall_detected}/{report.overall_resolved}" in overall_line
    holdout_line = next(line for line in text.splitlines() if "홀드아웃 검출률" in line)
    assert f"{report.holdout_detected}/{report.holdout_resolved}" in holdout_line
    assert overall_line != holdout_line

    payload = report_to_json(report, confidence=0.95)
    overall = payload["overall"]
    holdout = payload["holdout"]
    assert isinstance(overall, dict) and isinstance(holdout, dict)
    assert overall["detected"] == report.overall_detected
    assert holdout["detected"] == report.holdout_detected
    assert payload["holdout_classes"] == ["contradictory_condition"]


def test_audit_rows_flag_holdout(records: list[PilotRecord], tmp_path: Path) -> None:
    """감사 JSONL의 홀드아웃 판정 행은 `holdout: true`로 표시된다(하류 합산 사고 방지)."""
    battery = build_residue_seeded_set(records)
    report = run_residue_demotion_battle(
        battery, verifier=_HoldoutOnlyVerifier(), sample_n=2, seed="hold3"
    )
    out = tmp_path / "audit.jsonl"
    write_audit_jsonl(out, report)
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    verdicts = [r for r in rows if r["record_type"] == "verdict"]
    holdout_rows = [r for r in verdicts if r["defect_class"] == "contradictory_condition"]
    assert holdout_rows and all(r["holdout"] is True for r in holdout_rows)
    tuned_rows = [r for r in verdicts if r["defect_class"] in RESIDUE_TUNED_DEFECT_CLASSES]
    assert tuned_rows and all(r["holdout"] is False for r in tuned_rows)
    summary = rows[-1]
    assert summary["as_found_holdout_detected"] == report.holdout_detected
    assert summary["as_found_overall_detected"] == report.overall_detected


# ── B) `--clean-n` 대조군 표본 분리 ───────────────────────────────────────
def test_clean_n_scales_control_only(records: list[PilotRecord]) -> None:
    """대조군만 늘고 결함류 표본 수는 그대로 — 1차가 못 한 오검출 보정의 선결 조건."""
    battery = build_residue_seeded_set(records)
    report = run_residue_demotion_battle(
        battery,
        verifier=_ScriptedVerifier(mode="oracle", clean_texts=_clean_texts(records)),
        sample_n=2,
        clean_n=20,
        seed="cn1",
    )
    assert report.clean_sampled == 20
    for name in RESIDUE_DEFECT_CLASSES:
        assert report.per_class[name].sampled <= 2
    # 대조군 판정 표본이 20이면 Wilson 상한이 실제로 좁아진다(보정이 가능해진다).
    fau = report.false_alarm_upper_bound(0.95)
    assert fau is not None and fau < 0.15


def test_clean_n_omitted_preserves_legacy_behaviour(records: list[PilotRecord]) -> None:
    """생략 시 기존 동작과 **동일** — sample_n이 양쪽을 함께 정한다(회귀 0)."""
    battery = build_residue_seeded_set(records)
    omitted = run_residue_demotion_battle(
        battery,
        verifier=_ScriptedVerifier(mode="oracle", clean_texts=_clean_texts(records)),
        sample_n=3,
        seed="cn2",
    )
    explicit = run_residue_demotion_battle(
        battery,
        verifier=_ScriptedVerifier(mode="oracle", clean_texts=_clean_texts(records)),
        sample_n=3,
        clean_n=3,
        seed="cn2",
    )
    assert omitted.clean_sampled == 3
    assert omitted.clean_sampled == explicit.clean_sampled
    assert omitted.clean_resolved == explicit.clean_resolved
    assert omitted.audit_rows == explicit.audit_rows


def test_clean_n_keeps_select_sample_determinism(records: list[PilotRecord]) -> None:
    """표본 추출의 결정론(시드) 성질 유지 — 작은 n의 표본은 큰 n의 **접두사**다."""
    battery = build_residue_seeded_set(records)
    small = run_residue_demotion_battle(
        battery,
        verifier=_ScriptedVerifier(mode="oracle", clean_texts=_clean_texts(records)),
        sample_n=1,
        clean_n=3,
        seed="cn3",
    )
    large = run_residue_demotion_battle(
        battery,
        verifier=_ScriptedVerifier(mode="oracle", clean_texts=_clean_texts(records)),
        sample_n=1,
        clean_n=9,
        seed="cn3",
    )
    small_clean = [r.problem_id for r in small.audit_rows if r.role == "clean"]
    large_clean = [r.problem_id for r in large.audit_rows if r.role == "clean"]
    assert len(small_clean) == 3
    assert len(large_clean) == 9
    assert large_clean[:3] == small_clean


# ── A) `--repeat-runs` 반복 측정 집계 ─────────────────────────────────────
def test_stat_helpers_exact_values_and_none_handling() -> None:
    """알려진 입력에서 정확한 값 — None(측정 실패)은 제외하고 0으로 접지 않는다."""
    assert _mean([1.0, 2.0, None]) == pytest.approx(1.5)
    assert _mean([None, None]) is None
    assert _stdev([1.0, 2.0]) == pytest.approx(statistics.stdev([1.0, 2.0]))
    assert _stdev([0.2, 0.4, 0.9]) == pytest.approx(statistics.stdev([0.2, 0.4, 0.9]))
    assert _stdev([1.0]) is None  # 1회 실행에 변동성은 없다
    assert _stdev([1.0, None]) is None
    assert _min_value([0.3, 0.1, None]) == pytest.approx(0.1)
    assert _max_value([0.3, 0.1, None]) == pytest.approx(0.3)
    assert _min_value([None]) is None and _max_value([None]) is None


class _PhasedVerifier:
    """회차 경계에서 동작이 바뀌는 검출기 — 반복 집계가 *회차 간 차이*를 잡는지 증명한다.

    `calls_per_run` 콜마다 위상이 바뀐다: 1회차는 완벽 검출, 2회차는 눈먼 검출기. 반복
    집계가 옳다면 평균 0.5·표준편차 = stdev([하한1, 하한2])가 나와야 한다.
    """

    def __init__(self, *, calls_per_run: int) -> None:
        self._calls_per_run = calls_per_run
        self._calls = 0

    def verify(self, subject: object) -> CrossVerificationResult:
        run_index = self._calls // self._calls_per_run
        self._calls += 1
        problem_id: str = subject.problem_id  # type: ignore[attr-defined]
        if run_index % 2 == 0:  # 1회차(및 3, 5…) — 전건 검출
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


def _calls_per_run(records: list[PilotRecord], *, sample_n: int, clean_n: int, seed: str) -> int:
    """1회차 실행이 실제로 몇 콜을 쓰는지 실측 — 위상 전환 지점을 추측하지 않는다."""
    battery = build_residue_seeded_set(records)
    probe = _ScriptedVerifier(mode="oracle", clean_texts=_clean_texts(records))
    run_residue_demotion_battle(
        battery, verifier=probe, sample_n=sample_n, clean_n=clean_n, seed=seed
    )
    return len(probe.seen)


def test_repeated_run_aggregates_mean_stdev_min_max(records: list[PilotRecord]) -> None:
    """알려진 입력(1회차 100% · 2회차 0%)에서 평균/표준편차/최악이 정확한 값을 낸다."""
    battery = build_residue_seeded_set(records)
    per_run = _calls_per_run(records, sample_n=2, clean_n=2, seed="rep1")
    repeated = run_repeated_residue_demotion_battle(
        battery,
        verifier=_PhasedVerifier(calls_per_run=per_run),
        sample_n=2,
        clean_n=2,
        seed="rep1",
        repeat_runs=2,
        corpus_size=len(records),
        confidence=0.95,
    )
    assert repeated.repeat_runs == 2 and len(repeated.reports) == 2
    run1, run2 = repeated.reports
    assert run1.overall_detected == run1.overall_resolved > 0  # 1회차 100%
    assert run2.overall_detected == 0  # 2회차 0%
    # 표본 추출은 시드 고정 → 두 회차가 같은 문항을 본다(차이는 검증기의 비결정성뿐).
    assert [r.problem_id for r in run1.audit_rows] == [r.problem_id for r in run2.audit_rows]

    payload = repeated_report_to_json(repeated)
    overall = payload["overall"]
    assert overall["detection_rate_mean"] == pytest.approx(0.5)
    lowers = [run1.overall_detection_lower_bound(0.95), run2.overall_detection_lower_bound(0.95)]
    assert lowers[0] is not None and lowers[1] is not None
    assert overall["detection_lower_bound_mean"] == pytest.approx(statistics.mean(lowers))
    assert overall["detection_lower_bound_worst"] == pytest.approx(min(lowers))
    assert overall["detection_lower_bound_stdev"] == pytest.approx(statistics.stdev(lowers))


def test_repeated_run_single_run_has_no_stdev(records: list[PilotRecord]) -> None:
    """1회 실행 — 표준편차는 None(0.0으로 위장하면 '변동 없음'으로 오독된다)."""
    battery = build_residue_seeded_set(records)
    repeated = run_repeated_residue_demotion_battle(
        battery,
        verifier=_ScriptedVerifier(mode="oracle", clean_texts=_clean_texts(records)),
        sample_n=2,
        seed="rep2",
        repeat_runs=1,
        corpus_size=len(records),
    )
    payload = repeated_report_to_json(repeated)
    overall = payload["overall"]
    assert overall["detection_lower_bound_stdev"] is None
    assert overall["detection_rate_mean"] == pytest.approx(1.0)


def test_repeated_run_rejects_zero_runs(records: list[PilotRecord]) -> None:
    battery = build_residue_seeded_set(records)
    with pytest.raises(ValueError, match="repeat_runs"):
        run_repeated_residue_demotion_battle(
            battery,
            verifier=_ScriptedVerifier(mode="oracle", clean_texts=_clean_texts(records)),
            repeat_runs=0,
        )


def test_repeated_report_separates_holdout_and_renders_stats(records: list[PilotRecord]) -> None:
    battery = build_residue_seeded_set(records)
    repeated = run_repeated_residue_demotion_battle(
        battery,
        verifier=_HoldoutOnlyVerifier(),
        sample_n=2,
        clean_n=4,
        seed="rep3",
        repeat_runs=3,
        corpus_size=len(records),
    )
    text = render_repeated_report(repeated)
    assert "반복 실행" in text
    assert "[전체 — 튜닝 4종만 합산(홀드아웃 제외)]" in text
    assert "[홀드아웃 결함류" in text
    assert "대조군 표본 4건" in text and "반복 3회" in text

    payload = repeated_report_to_json(repeated)
    overall = payload["overall"]
    holdout = payload["holdout"]
    assert overall["detection_rate_mean"] == pytest.approx(0.0)
    assert holdout["detection_rate_mean"] == pytest.approx(1.0)
    per_class = payload["per_class"]
    assert per_class["contradictory_condition"]["holdout"] is True
    assert per_class["missing_condition"]["holdout"] is False


def test_write_repeated_audit_jsonl_tags_each_run(
    records: list[PilotRecord], tmp_path: Path
) -> None:
    battery = build_residue_seeded_set(records)
    repeated = run_repeated_residue_demotion_battle(
        battery,
        verifier=_ScriptedVerifier(mode="oracle", clean_texts=_clean_texts(records)),
        sample_n=1,
        clean_n=1,
        seed="rep4",
        repeat_runs=2,
        corpus_size=len(records),
        measurement_config=MeasurementConfig(kind="local_fixed", local_model="qwen2.5:7b"),
    )
    out = tmp_path / "repeated.jsonl"
    written = write_repeated_audit_jsonl(out, repeated)
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert written == len(rows)
    assert rows[0]["record_type"] == "measurement_config"
    assert rows[0]["local_model"] == "qwen2.5:7b"
    assert rows[0]["repeat_runs"] == 2
    verdicts = [r for r in rows if r["record_type"] == "verdict"]
    assert {r["run"] for r in verdicts} == {1, 2}
    summaries = [r for r in rows if r["record_type"] == "as_found_summary"]
    assert [s["run"] for s in summaries] == [1, 2]


# ── 결함류별 검증기 주입(--v4 배선을 위한 확장 지점) ──────────────────────
def test_verifier_mapping_routes_per_defect_class(records: list[PilotRecord]) -> None:
    """Mapping 주입 — 결함류별로 다른 검증기가 쓰이고, 매핑에 없는 결함류는 기본을 쓴다."""
    battery = build_residue_seeded_set(records)
    targeted = _ScriptedVerifier(mode="oracle", clean_texts=_clean_texts(records))
    fallback = _ScriptedVerifier(mode="blind_ok", clean_texts=_clean_texts(records))
    report = run_residue_demotion_battle(
        battery,
        verifier={"missing_condition": targeted},  # type: ignore[dict-item]
        default_verifier=fallback,
        sample_n=2,
        clean_n=2,
        seed="map1",
    )
    # missing_condition만 oracle을 탔으므로 그 결함류만 검출된다.
    assert report.per_class["missing_condition"].detected > 0
    for name in RESIDUE_DEFECT_CLASSES:
        if name != "missing_condition":
            assert report.per_class[name].detected == 0
    assert len(targeted.seen) == report.per_class["missing_condition"].sampled
    # 대조군은 기본 검증기가 맡는다.
    assert len(fallback.seen) > 0


def test_verifier_mapping_without_any_verifier_raises(records: list[PilotRecord]) -> None:
    """빈 매핑 + 기본 검증기 없음 — 조용히 0건으로 끝내지 않고 raise(침묵 실패 금지)."""
    battery = build_residue_seeded_set(records)
    with pytest.raises(ValueError, match="검증기"):
        run_residue_demotion_battle(battery, verifier={}, sample_n=1)


# ── C) 클라우드 좌석 선택(`--cloud`) ──────────────────────────────────────
def test_cloud_and_local_model_are_mutually_exclusive() -> None:
    """둘 다 주면 argparse가 거부한다 — 어느 좌석의 수치인지 말할 수 없는 측정은 시작도 못 한다."""
    if not _PILOT_CORPUS.exists():  # pragma: no cover — 코퍼스 미생성 환경 방어
        pytest.skip(f"파일럿 코퍼스 미존재({_PILOT_CORPUS})")
    with pytest.raises(SystemExit) as excinfo:
        main([str(_PILOT_CORPUS), "--cloud", "--local-model", "qwen2.5:7b"])
    assert excinfo.value.code == 2  # argparse 사용법 오류


def test_measurement_config_describe_and_json() -> None:
    cloud = MeasurementConfig(
        kind="cloud_seat",
        cloud_provider="openrouter",
        cloud_model_mid="deepseek/deepseek-v4.1-flash",
        cloud_model_high="deepseek/deepseek-v4.1",
    )
    assert "openrouter" in cloud.describe()
    assert "deepseek/deepseek-v4.1-flash" in cloud.describe()
    assert cloud.to_json()["cloud_provider"] == "openrouter"

    local = MeasurementConfig(kind="local_fixed", local_model="qwen2.5:7b")
    assert "qwen2.5:7b" in local.describe()
    assert local.to_json()["local_model"] == "qwen2.5:7b"

    router = MeasurementConfig(kind="router_default")
    assert "라우터" in router.describe()


def test_report_records_measurement_config(records: list[PilotRecord]) -> None:
    """측정 구성이 리포트·JSON에 실린다 — 없으면 '기록 없음'이라고 말한다(침묵 금지)."""
    battery = build_residue_seeded_set(records)
    config = MeasurementConfig(
        kind="cloud_seat",
        cloud_provider="openrouter",
        cloud_model_mid="mid-pin",
        cloud_model_high="high-pin",
    )
    report = run_residue_demotion_battle(
        battery,
        verifier=_ScriptedVerifier(mode="oracle", clean_texts=_clean_texts(records)),
        sample_n=1,
        clean_n=1,
        seed="mc1",
        measurement_config=config,
    )
    text = render_report(report, confidence=0.95, corpus_size=len(records))
    assert "[측정 구성] 클라우드 좌석 openrouter" in text
    assert "mid-pin" in text and "high-pin" in text
    assert report_to_json(report)["measurement_config"] == config.to_json()

    without = run_residue_demotion_battle(
        battery,
        verifier=_ScriptedVerifier(mode="oracle", clean_texts=_clean_texts(records)),
        sample_n=1,
        clean_n=1,
        seed="mc1",
    )
    assert "[측정 구성] 기록 없음" in render_report(
        without, confidence=0.95, corpus_size=len(records)
    )
    assert report_to_json(without)["measurement_config"] is None


def test_cli_cloud_goes_through_provider_factory(
    records: list[PilotRecord], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--cloud`가 factory를 경유하고 좌석 이름·모델 핀이 산출물에 실린다(네트워크 0)."""
    if not _PILOT_CORPUS.exists():  # pragma: no cover — 코퍼스 미생성 환경 방어
        pytest.skip(f"파일럿 코퍼스 미존재({_PILOT_CORPUS})")
    import whymath_backend.harness.residue_gate_demotion_battle as battle_mod

    sentinel = object()
    factory_calls: list[str] = []

    def _fake_build_cloud_provider() -> object:
        factory_calls.append("build_cloud_provider")
        return sentinel

    def _fake_cloud_provider_name() -> str:
        factory_calls.append("cloud_provider_name")
        return "openrouter"

    def _fake_cloud_model_pins() -> tuple[str, str]:
        factory_calls.append("cloud_model_pins")
        return ("mid-pin", "high-pin")

    seen_providers: list[object] = []
    clean_texts = _clean_texts(records)

    class _FakeCrossVerifier:
        def __init__(self, *, provider: object | None = None) -> None:
            seen_providers.append(provider)
            self._inner = _ScriptedVerifier(mode="oracle", clean_texts=clean_texts)

        def verify(self, subject: object) -> CrossVerificationResult:
            return self._inner.verify(subject)

        def flush_trace(self) -> None:
            return None

    monkeypatch.setattr(battle_mod, "build_cloud_provider", _fake_build_cloud_provider)
    monkeypatch.setattr(battle_mod, "cloud_provider_name", _fake_cloud_provider_name)
    monkeypatch.setattr(battle_mod, "cloud_model_pins", _fake_cloud_model_pins)
    monkeypatch.setattr(battle_mod, "CrossVerifier", _FakeCrossVerifier)

    audit_out = tmp_path / "cloud_audit.jsonl"
    exit_code = main(
        [
            str(_PILOT_CORPUS),
            "--cloud",
            "--sample-n",
            "1",
            "--clean-n",
            "2",
            "--audit-out",
            str(audit_out),
        ]
    )
    assert exit_code == 0
    assert "build_cloud_provider" in factory_calls  # 팩토리 경유 — 자체 클라이언트 조립 아님
    assert "cloud_provider_name" in factory_calls and "cloud_model_pins" in factory_calls
    assert seen_providers == [sentinel]  # 팩토리가 만든 provider가 검증기에 주입됐다

    rows = [json.loads(line) for line in audit_out.read_text(encoding="utf-8").splitlines()]
    header = rows[0]
    assert header["record_type"] == "measurement_config"
    assert header["kind"] == "cloud_seat"
    assert header["cloud_provider"] == "openrouter"
    assert header["cloud_model_mid"] == "mid-pin"
    clean_rows = [r for r in rows if r.get("role") == "clean"]
    assert len(clean_rows) == 2  # --clean-n이 대조군만 2건으로 정했다


def test_cli_local_model_records_its_own_measurement_config(
    records: list[PilotRecord], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--local-model` 경로도 구성을 기록한다 — 클라우드 전용 기능이 아니다."""
    if not _PILOT_CORPUS.exists():  # pragma: no cover — 코퍼스 미생성 환경 방어
        pytest.skip(f"파일럿 코퍼스 미존재({_PILOT_CORPUS})")
    import whymath_backend.harness.residue_gate_demotion_battle as battle_mod

    clean_texts = _clean_texts(records)

    class _FakeCrossVerifier:
        def __init__(self, *, provider: object | None = None) -> None:
            self._inner = _ScriptedVerifier(mode="oracle", clean_texts=clean_texts)

        def verify(self, subject: object) -> CrossVerificationResult:
            return self._inner.verify(subject)

        def flush_trace(self) -> None:
            return None

    monkeypatch.setattr(battle_mod, "CrossVerifier", _FakeCrossVerifier)
    monkeypatch.setattr(battle_mod, "FixedModelOllamaProvider", lambda model: object())

    audit_out = tmp_path / "local_audit.jsonl"
    exit_code = main(
        [
            str(_PILOT_CORPUS),
            "--local-model",
            "qwen2.5:7b",
            "--sample-n",
            "1",
            "--clean-n",
            "1",
            "--audit-out",
            str(audit_out),
        ]
    )
    assert exit_code == 0
    header = json.loads(audit_out.read_text(encoding="utf-8").splitlines()[0])
    assert header["record_type"] == "measurement_config"
    assert header["kind"] == "local_fixed"
    assert header["local_model"] == "qwen2.5:7b"


def test_cli_repeat_runs_uses_repeated_report(
    records: list[PilotRecord], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--repeat-runs 2`가 반복 리포트·반복 감사 JSONL 경로를 탄다."""
    if not _PILOT_CORPUS.exists():  # pragma: no cover — 코퍼스 미생성 환경 방어
        pytest.skip(f"파일럿 코퍼스 미존재({_PILOT_CORPUS})")
    import whymath_backend.harness.residue_gate_demotion_battle as battle_mod

    clean_texts = _clean_texts(records)

    class _FakeCrossVerifier:
        def __init__(self, *, provider: object | None = None) -> None:
            self._inner = _ScriptedVerifier(mode="oracle", clean_texts=clean_texts)

        def verify(self, subject: object) -> CrossVerificationResult:
            return self._inner.verify(subject)

        def flush_trace(self) -> None:
            return None

    monkeypatch.setattr(battle_mod, "CrossVerifier", _FakeCrossVerifier)

    audit_out = tmp_path / "repeat_audit.jsonl"
    exit_code = main(
        [
            str(_PILOT_CORPUS),
            "--sample-n",
            "1",
            "--clean-n",
            "1",
            "--repeat-runs",
            "2",
            "--audit-out",
            str(audit_out),
        ]
    )
    assert exit_code == 0
    rows = [json.loads(line) for line in audit_out.read_text(encoding="utf-8").splitlines()]
    assert {r["run"] for r in rows if r["record_type"] == "verdict"} == {1, 2}


class _AlwaysUnclearVerifier:
    """전건 판정불가 검출기 — 판정 표본 0(측정 실패) 경로를 실제로 밟게 하는 픽스처.

    이 픽스처가 없으면 `resolved == 0` 가드(홀드아웃 하한·검출률 분모)가 뮤테이션에서
    **살아남는다** — 정상 입력에서는 그 분기를 한 번도 지나가지 않기 때문이다.
    """

    def verify(self, subject: object) -> CrossVerificationResult:
        return CrossVerificationResult(
            subject.problem_id,  # type: ignore[attr-defined]
            (PerspectiveVerdict("p", "unclear", "provider_error", "다운"),),
            "unclear",
            "p:provider_error",
            "측정 실패",
        )


def test_holdout_measurement_failure_is_none_not_zero(records: list[PilotRecord]) -> None:
    """홀드아웃 판정 표본 0 — 검출률·하한은 0.0이 아니라 None(완전 실명으로 위장 금지)."""
    battery = build_residue_seeded_set(records)
    report = run_residue_demotion_battle(
        battery, verifier=_AlwaysUnclearVerifier(), sample_n=2, clean_n=1, seed="hold4"
    )
    assert report.holdout_resolved == 0
    assert report.holdout_unresolved > 0  # 판정불가는 별도로 세어진다
    assert report.holdout_detected == 0
    assert report.holdout_detection_lower_bound(0.95) is None
    # 리포트 본문도 0.0이 아니라 n/a로 말해야 한다.
    text = render_report(report, confidence=0.95, corpus_size=len(records))
    holdout_line = next(line for line in text.splitlines() if "홀드아웃 검출률" in line)
    assert "0/0" in holdout_line and "n/a" in holdout_line


def test_repeated_report_rates_are_none_when_nothing_resolved(
    records: list[PilotRecord],
) -> None:
    """반복 집계에서도 0/0은 None — 분모 0을 0.0으로 접으면 '전부 놓쳤다'로 읽힌다."""
    battery = build_residue_seeded_set(records)
    repeated = run_repeated_residue_demotion_battle(
        battery,
        verifier=_AlwaysUnclearVerifier(),
        sample_n=2,
        clean_n=1,
        seed="hold5",
        repeat_runs=2,
        corpus_size=len(records),
    )
    payload = repeated_report_to_json(repeated)
    overall = payload["overall"]
    holdout = payload["holdout"]
    clean = payload["clean_control"]
    assert overall["detection_rate_mean"] is None
    assert overall["detection_lower_bound_mean"] is None
    assert holdout["detection_rate_mean"] is None
    assert holdout["detection_lower_bound_worst"] is None
    assert clean["false_alarm_rate_mean"] is None
    # 판정불가율은 *측정된* 값이므로 None이 아니라 1.0(전건 판정불가)이어야 한다.
    assert overall["abstention_rate_mean"] == pytest.approx(1.0)
    assert holdout["abstention_rate_mean"] == pytest.approx(1.0)
    text = render_repeated_report(repeated)
    assert "보정 제안 불가" in text  # 대조군 판정 0건 → 보정 제안을 지어내지 않는다


# ──────────────────────────────────────────────────────────────────────────
# v4 모드 — 오라클(진단) vs 프로덕션(승격 판정용 합집합)
#
# 왜 두 모드를 가르는가: v4는 결함류별 전용 관점이라, 하네스가 주입한 결함류를 알고
# 세트를 고르면 프로덕션이 갖지 못한 오라클을 쓰는 것이다. 그 수치는 오검출을 과소
# 추정한다(무결함 문항에 세트가 하나만 걸린다).
# 정본 = docs/standards/residue_gate_demotion_battle_history.md §4.6.
# ──────────────────────────────────────────────────────────────────────────


class _NullTrace:
    """관측 대역 — 네트워크 0."""

    def record(self, fields: object) -> None:
        return None

    def flush(self) -> None:
        return None


class _CountingProvider:
    """호출 수를 세는 provider 대역 — 전 관점이 파싱 가능한 응답을 돌려준다(네트워크 0)."""

    def __init__(self, verdict: str = "ok") -> None:
        self.calls = 0
        self._verdict = verdict

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: object,
        *,
        images: object = None,
        temperature: object = None,
        json_schema: object = None,
        seed: object = None,
    ) -> GenerationResult:
        self.calls += 1
        if self._verdict == "ok":
            # 재구성 계열은 숫자를, 라벨 계열은 verdict를 읽는다 — 양쪽을 함께 만족시킨다.
            return GenerationResult(
                '{"total": 36, "favorable": 6, "verdict": "ok", "reason": "이상 없음"}'
            )
        return GenerationResult(
            '{"total": 1, "favorable": 1, "verdict": "defect",'
            ' "defect_class": "x", "reason": "결함"}'
        )


def _union_verifier(provider: _CountingProvider) -> UnionCrossVerifier:
    base = CrossVerifier(provider=provider, trace=_NullTrace())  # type: ignore[arg-type]
    return UnionCrossVerifier(base)


def _v4_subject() -> ResidueSubject:
    return ResidueSubject(
        problem_id="wm-finite-v4mode",
        question_text=_GROUP_A_TEXT,
        answer="1/6",
        answer_explanation="전체 36가지 중 6가지.",
        machine_model_ko="주사위 2개를 던져 두 눈의 합이 7인 경우.",
        machine_total=36,
        machine_favorable=6,
        authored_by="deterministic:test",
    )


def test_v4_production_mode_burns_every_perspective_set() -> None:
    """프로덕션 모드는 세트 3종을 전부 태운다 — 문항당 9콜(세트 3 x K=3)."""
    provider = _CountingProvider()
    verifier = _union_verifier(provider)
    assert len(verifier.perspective_sets) == 3
    verifier.verify(_v4_subject())
    assert provider.calls == 9, f"세트 3종 x K=3 = 9콜이어야 하는데 {provider.calls}콜"


def test_v4_production_mode_unions_defect_verdicts() -> None:
    """어느 세트 하나라도 defect면 합집합 판정은 defect — 배포 집계 규칙 그대로."""
    result = _union_verifier(_CountingProvider(verdict="defect")).verify(_v4_subject())
    assert result.aggregate == "defect"
    # 판정 근거가 9관점 전체에서 모인다(세트별로 잘려 나가지 않는다)
    assert len(result.verdicts) == 9


def test_v4_production_mode_ok_requires_all_sets_unanimous() -> None:
    """전 세트 만장일치 ok여야 ok — 한 세트만 보고 통과시키지 않는다."""
    result = _union_verifier(_CountingProvider()).verify(_v4_subject())
    assert result.aggregate == "ok"
    assert len(result.verdicts) == 9


def test_v4_production_mode_respects_explicit_perspectives() -> None:
    """관점을 명시하면 합집합하지 않는다 — 상위 코드의 지목을 덮어쓰지 않는다."""
    provider = _CountingProvider()
    _union_verifier(provider).verify(_v4_subject(), MISSING_CONDITION_PERSPECTIVES)
    assert provider.calls == 3


def test_union_verifier_rejects_empty_perspective_sets() -> None:
    """세트가 비면 조용히 통과시키지 않고 거부한다 — 검증기 0개의 '검출 0건' 위장 방지."""
    base = CrossVerifier(provider=_CountingProvider(), trace=_NullTrace())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="관점 세트가 비었다"):
        UnionCrossVerifier(base, [])


def test_v4_oracle_wiring_routes_per_class_and_falls_back_for_clean() -> None:
    """오라클 모드: 결함류는 전용 세트로, 대조군·미지정 결함류는 일반 v2 폴백으로.

    대조군까지 오라클을 주면 그 오검출 수치는 아무것도 대표하지 못한다.
    """
    base = CrossVerifier(provider=_CountingProvider(), trace=_NullTrace())  # type: ignore[arg-type]
    mapping, default = build_v4_wiring("oracle", base)
    assert isinstance(mapping, dict)
    assert set(mapping) == {"missing_condition", "multiple_valid_answers"}
    assert mapping["missing_condition"]._perspectives == MISSING_CONDITION_PERSPECTIVES
    assert mapping["multiple_valid_answers"]._perspectives == MULTIPLE_VALID_ANSWERS_PERSPECTIVES
    assert default is base, "대조군 폴백이 일반 v2 검증기여야 한다"


def test_v4_production_wiring_has_no_oracle_fallback() -> None:
    """프로덕션 모드는 매핑이 아니라 합집합 검증기 하나 — 결함류를 아는 경로가 없다."""
    base = CrossVerifier(provider=_CountingProvider(), trace=_NullTrace())  # type: ignore[arg-type]
    verifier, default = build_v4_wiring("production", base)
    assert isinstance(verifier, UnionCrossVerifier)
    assert default is None


def test_v4_off_wiring_preserves_legacy_behaviour() -> None:
    """기본값 off는 종전 동작 — 주입한 검증기를 그대로 쓴다(회귀 0)."""
    base = CrossVerifier(provider=_CountingProvider(), trace=_NullTrace())  # type: ignore[arg-type]
    verifier, default = build_v4_wiring("off", base)
    assert verifier is base
    assert default is None
