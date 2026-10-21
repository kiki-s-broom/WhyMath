"""P3-10 AI 품질 평가 CLI — 8축 각각에 나쁜 응답을 넣으면 그 축 점수가 떨어지고 FAIL이 되는가.

정상 입력에서 초록인 것은 증거가 아니다(acceptance ②). 이 파일의 중심은
  ① 주입 8종이 실제로 응답을 바꾸고(`mutated > 0`) 그 축 점수를 떨어뜨려 FAIL로 바꾸는지,
  ② 자가 점검 자체가 위장하지 않는지 — 주입이 무력하거나(항등) 판정기가 상수 통과면 exit 1,
  ③ 측정 실패(대상 부족·판정기 예외·적재 실패)가 통과로 접히지 않는지(exit 2)
다.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import ai_quality_candidates as candidates
from whymath_backend.harness import ai_quality_eval as cli
from whymath_backend.harness import ai_quality_judges as judges
from whymath_backend.harness.ai_quality_candidates import (
    CandidateError,
    build_eos_candidate,
    dump_responses,
    inject,
    parse_responses,
)
from whymath_backend.harness.ai_quality_eval_set import EvalSet, load_eval_set
from whymath_backend.harness.ai_quality_judges import AXES, Judgment, TutorResponse
from whymath_backend.harness.ai_quality_registry import Registry, RegistryError, load_registry


@pytest.fixture(scope="module")
def registry() -> Registry:
    return load_registry()


@pytest.fixture(scope="module")
def eval_set(registry: Registry) -> EvalSet:
    return load_eval_set(registry)


@pytest.fixture(scope="module")
def base(eval_set: EvalSet, registry: Registry) -> dict[str, TutorResponse]:
    return build_eos_candidate(eval_set, registry)


@pytest.fixture(scope="module")
def baseline(eval_set, registry, base) -> cli.EvalReport:
    return cli.evaluate(eval_set, registry, base, candidate="test")


def _eval(eval_set, registry, responses: Mapping[str, TutorResponse]) -> cli.EvalReport:
    return cli.evaluate(eval_set, registry, responses, candidate="test")


# ──────────────────────────────────────────────────────────────────────────
# 기준(주입 없음) — 측정 가능성
# ──────────────────────────────────────────────────────────────────────────
def test_baseline_is_measurable_on_every_axis(baseline: cli.EvalReport) -> None:
    """현재 코드의 결정론 출력으로 8축 모두 판정 대상이 최소 N 이상이고 임계에 도달 가능하다."""
    for axis in baseline.axes:
        assert axis.verdict in ("PASS", "FAIL"), axis.spec.axis
        assert axis.n_applicable >= axis.spec.min_n, axis.spec.axis
        assert axis.reachable, axis.spec.axis
        assert axis.n_errors == 0


def test_baseline_candidate_never_claims_state_authority(base) -> None:
    assert all(r.tutor_output.get("mastery_update_allowed") is False for r in base.values())


# ──────────────────────────────────────────────────────────────────────────
# ① 주입 8종 — 그 축 점수 하락 + FAIL 전환
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("axis", AXES)
def test_injection_drops_its_axis(axis, eval_set, registry, base, baseline) -> None:
    mutated, changed = inject(axis, eval_set, registry, base)
    assert changed > 0  # 주입이 실제로 적용됐다(적용 단언)
    assert any(
        dict(mutated[k].tutor_output) != dict(base[k].tutor_output)
        or mutated[k].referenced_concept_ids != base[k].referenced_concept_ids
        for k in base
    )
    report = _eval(eval_set, registry, mutated)
    before, after = baseline.axis(axis), report.axis(axis)
    assert after.pass_rate is not None and before.pass_rate is not None
    assert after.pass_rate < before.pass_rate, axis
    assert after.verdict == "FAIL", axis
    assert report.exit_code == 1


def test_injection_does_not_mutate_input(eval_set, registry, base) -> None:
    snapshot = {k: json.dumps(dict(v.tutor_output), sort_keys=True) for k, v in base.items()}
    for axis in AXES:
        inject(axis, eval_set, registry, base)
    assert snapshot == {
        k: json.dumps(dict(v.tutor_output), sort_keys=True) for k, v in base.items()
    }


def test_self_test_passes_on_real_code(eval_set, registry, base) -> None:
    report = cli.run_self_test(eval_set, registry, base, candidate="test")
    assert report.exit_code == 0
    assert all(o.ok and o.mutated > 0 for o in report.outcomes)
    assert [o.axis for o in report.outcomes] == list(AXES)


# ──────────────────────────────────────────────────────────────────────────
# ② 자가 점검이 위장하지 않는다
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("axis", ["answer_leak", "hint_appropriateness", "curriculum_scope"])
def test_self_test_fails_when_injection_is_inert(
    axis, eval_set, registry, base, monkeypatch
) -> None:
    """주입이 아무것도 안 바꾸면(항등) 그 축은 '무반응' — 자가 점검 exit 1."""
    inert = dict(candidates.INJECTIONS)
    inert[axis] = lambda es, reg, b: dict(b)
    monkeypatch.setattr(candidates, "INJECTIONS", inert)
    report = cli.run_self_test(eval_set, registry, base, candidate="test")
    assert report.exit_code == 1
    outcome = next(o for o in report.outcomes if o.axis == axis)
    assert outcome.mutated == 0 and not outcome.ok


@pytest.mark.parametrize("axis", AXES)
def test_self_test_fails_when_judge_is_constant_pass(
    axis, eval_set, registry, base, monkeypatch
) -> None:
    """판정기가 항상 통과를 내면 주입해도 점수가 안 떨어진다 — 자가 점검이 그것을 잡아야 한다."""
    real = dict(judges._JUDGES)

    def constant(case, response, ctx) -> Judgment:
        j = real[axis](case, response, ctx)
        return Judgment(applicable=j.applicable, passed=True)

    patched = dict(real)
    patched[axis] = constant
    monkeypatch.setattr(judges, "_JUDGES", patched)
    report = cli.run_self_test(eval_set, registry, base, candidate="test")
    assert report.exit_code == 1
    assert not next(o for o in report.outcomes if o.axis == axis).ok


def test_injection_outcome_requires_every_condition() -> None:
    """점검 통과 = 주입 적용(mutated>0) ∧ 점수 하락 ∧ FAIL 전환 — 셋 중 하나라도 빠지면 무반응이다."""
    ok = cli.InjectionOutcome("answer_leak", 3, 1.0, 0.5, "FAIL")
    assert ok.ok
    assert not dataclasses.replace(ok, mutated=0).ok
    assert not dataclasses.replace(ok, injected_rate=1.0).ok
    assert not dataclasses.replace(ok, injected_verdict="PASS").ok
    assert not dataclasses.replace(ok, injected_rate=None).ok


def test_self_test_requires_fail_transition_not_just_a_drop(
    eval_set, registry, base, monkeypatch
) -> None:
    """점수는 떨어졌지만 임계 위에 머문 축은 '무반응'이다 — `run_self_test`가 실제 판정을 읽어야 잡힌다.

    `InjectionOutcome.ok`만 단위로 보면, `run_self_test`가 판정 대신 상수 "FAIL"을 넘겨도 통과한다
    (2026-10-21 리뷰 뮤테이션 E5 생존). 그래서 실제 경로를 통과시켜, 임계를 0으로 내린 축이
    주입 후에도 PASS로 남을 때 자가 점검이 그 축을 무반응으로 계상하는지 본다.
    """
    specs = dict(judges.AXIS_SPECS)
    specs["student_level_fit"] = dataclasses.replace(specs["student_level_fit"], threshold=0.0)
    monkeypatch.setattr(cli, "AXIS_SPECS", specs)
    report = cli.run_self_test(eval_set, registry, base, candidate="test")
    outcome = next(o for o in report.outcomes if o.axis == "student_level_fit")
    assert outcome.mutated > 0 and outcome.dropped  # 주입은 들어갔고 점수도 떨어졌다
    assert outcome.injected_verdict == "PASS"  # 그런데 임계 위라 판정이 바뀌지 않았다
    assert not outcome.ok
    assert report.exit_code == 1


# ──────────────────────────────────────────────────────────────────────────
# ③ 측정 실패는 통과가 아니다
# ──────────────────────────────────────────────────────────────────────────
def test_below_min_n_is_unmeasured(eval_set, registry, base, monkeypatch) -> None:
    specs = dict(judges.AXIS_SPECS)
    specs["hallucination"] = dataclasses.replace(specs["hallucination"], min_n=10_000)
    monkeypatch.setattr(cli, "AXIS_SPECS", specs)
    report = _eval(eval_set, registry, base)
    assert report.axis("hallucination").verdict == "UNMEASURED"
    assert report.exit_code == 2


def test_judge_exception_is_unmeasured_with_type_name(
    eval_set, registry, base, monkeypatch
) -> None:
    patched = dict(judges._JUDGES)

    def boom(case, response, ctx) -> Judgment:
        raise ZeroDivisionError("x")

    patched["curriculum_scope"] = boom
    monkeypatch.setattr(judges, "_JUDGES", patched)
    report = _eval(eval_set, registry, base)
    axis = report.axis("curriculum_scope")
    assert axis.verdict == "UNMEASURED" and axis.n_errors == len(eval_set.cases)
    assert "ZeroDivisionError" in axis.failures[0].reasons[0]
    assert report.exit_code == 2


def test_zero_tolerance_axis_fails_on_single_failure(eval_set, registry, base) -> None:
    """무관용 축은 Wilson 상한이 임계 아래여도 실패 1건이면 FAIL이다."""
    case = next(c for c in eval_set.cases if not c.answer_known_to_student)
    answer = eval_set.materials[case.problem_id].answer
    responses = dict(base)
    r = responses[case.case_id]
    responses[case.case_id] = dataclasses.replace(
        r, tutor_output={**r.tutor_output, "explanation": f"정답은 {answer}이야."}
    )
    clean = {k: v for k, v in responses.items()}
    report = _eval(eval_set, registry, clean)
    leak = report.axis("answer_leak")
    assert leak.n_fail >= 1 and leak.bound is not None and leak.bound <= leak.spec.threshold
    assert leak.verdict == "FAIL"


def test_missing_responses_count_as_failures(eval_set, registry, base) -> None:
    partial = dict(list(base.items())[: len(base) // 2])
    report = _eval(eval_set, registry, partial)
    assert report.missing_responses == len(base) - len(partial)
    reasons = {r for a in report.axes for f in a.failures for r in f.reasons}
    assert "응답 누락" in reasons
    assert report.exit_code == 1


# ──────────────────────────────────────────────────────────────────────────
# 외부 응답 JSONL · CLI 진입점
# ──────────────────────────────────────────────────────────────────────────
def test_response_jsonl_roundtrip(base) -> None:
    text = dump_responses(base)
    again = parse_responses(text)
    assert set(again) == set(base)
    assert all(dict(again[k].tutor_output) == dict(base[k].tutor_output) for k in base)


@pytest.mark.parametrize(
    "line",
    [
        "{}",
        '{"schema": "ai-quality-response/v1", "case_id": 1, "tutor_output": {}}',
        '{"schema": "ai-quality-response/v1", "case_id": "a", "tutor_output": []}',
        '{"schema": "ai-quality-response/v1", "case_id": "a", "tutor_output": {}, '
        '"referenced_concept_ids": [1]}',
        "not json",
    ],
)
def test_response_jsonl_rejects_violations(line) -> None:
    with pytest.raises(CandidateError):
        parse_responses(line + "\n")


def test_response_jsonl_rejects_duplicates_and_empty() -> None:
    row = '{"schema": "ai-quality-response/v1", "case_id": "a", "tutor_output": {}}\n'
    with pytest.raises(CandidateError, match="중복"):
        parse_responses(row + row)
    with pytest.raises(CandidateError, match="0건"):
        parse_responses("\n")


def test_main_with_external_responses_and_json(base, tmp_path: Path, capsys) -> None:
    responses = tmp_path / "responses.jsonl"
    responses.write_text(dump_responses(base), encoding="utf-8")
    out = tmp_path / "report.json"
    code = cli.main(["--responses", str(responses), "--json", str(out)])
    payload: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    assert code == payload["exit_code"]
    assert payload["candidate"].startswith("external:")
    assert [a["axis"] for a in payload["axes"]] == list(AXES)
    for a in payload["axes"]:
        assert a["blind_spots"] and a["threshold"]["basis"]
    stdout = capsys.readouterr().out
    assert "AI 품질 평가 8종" in stdout and "sha256" in stdout


def test_main_inject_writes_fail(tmp_path: Path) -> None:
    out = tmp_path / "inj.json"
    assert cli.main(["--inject", "hallucination", "--json", str(out)]) == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    hall = next(a for a in payload["axes"] if a["axis"] == "hallucination")
    assert payload["injection"] == "hallucination" and hall["verdict"] == "FAIL"
    assert all(f["blocked_by_p309"] for f in hall["failures"])  # 가짜 개념 id는 P3-09가 막는다


def test_main_missing_responses_file_is_measurement_failure(tmp_path: Path, capsys) -> None:
    assert cli.main(["--responses", str(tmp_path / "nope.jsonl")]) == 2
    assert "측정 실패" in capsys.readouterr().err


def test_main_bad_eval_set_is_measurement_failure(tmp_path: Path, capsys) -> None:
    bad = tmp_path / "eval.jsonl"
    bad.write_text("{}\n", encoding="utf-8")
    assert cli.main(["--eval-set", str(bad)]) == 2
    assert "평가셋 적재" in capsys.readouterr().err


def test_main_registry_failure_is_measurement_failure(monkeypatch, capsys) -> None:
    def fail() -> Registry:
        raise RegistryError("주입된 적재 실패")

    monkeypatch.setattr(cli, "load_registry", fail)
    assert cli.main([]) == 2
    assert "레지스트리" in capsys.readouterr().err


def test_main_build_eval_set_matches_committed(tmp_path: Path) -> None:
    out = tmp_path / "eval.jsonl"
    assert cli.main(["--build-eval-set", str(out)]) == 0
    committed = (
        Path(__file__).resolve().parents[3] / "data/corpus/ai_quality_eval_v1/eval_set.jsonl"
    )
    assert out.read_bytes() == committed.read_bytes()


def test_main_self_test_json(tmp_path: Path) -> None:
    out = tmp_path / "self.json"
    assert cli.main(["--self-test", "--json", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["exit_code"] == 0
    assert [i["axis"] for i in payload["injections"]] == list(AXES)
    assert all(i["ok"] and i["dropped"] and i["mutated"] > 0 for i in payload["injections"])


def test_numeric_parse_contract_error_is_not_swallowed(
    eval_set, registry, base, monkeypatch
) -> None:
    """식 해석기 호출 계약이 깨지면(TypeError) 정답 누설 축은 '통과'가 아니라 측정 실패여야 한다.

    광범위 `except Exception`이 이것을 '판정 불가'로 삼키면 동치 산술식 검사가 조용히 꺼져
    무관용 축이 전부 통과로 바뀐다(2026-10-21 리뷰 뮤테이션 X2: 실결함이 사라지고 종합 exit 0).
    """

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise TypeError("unexpected keyword argument")

    monkeypatch.setattr(judges, "safe_sympify", broken)
    report = _eval(eval_set, registry, base)
    leak = report.axis("answer_leak")
    assert leak.verdict == "UNMEASURED" and leak.n_errors > 0
    assert any("TypeError" in r for f in leak.failures for r in f.reasons)
    assert report.exit_code == 2


def test_expected_parse_failure_is_still_unverifiable() -> None:
    """대조군 — 해석 불가인 산술식(SympifyError 계열)은 예외 없이 '판정 불가'(None)로 접힌다."""
    assert judges._closed_numeric("(1 + ") is None
    assert judges._closed_numeric("2 + 3") == 5
