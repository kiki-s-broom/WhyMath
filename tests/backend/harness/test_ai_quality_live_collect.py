"""P3-78 라이브 품질 수집 도구 — 스크립트 provider로 실제 primary 러너를 hermetic하게 돌린다.

정상 입력에서 초록인 것은 증거가 아니다. 이 파일의 중심은 각 판정 절이 **없으면 통과해 버리는
입력**이다(CLAUDE.md '픽스처가 그 절을 실제로 밟는가'):
  - provider 예외가 난 사례는 정책이 강등으로 흡수해 발화를 *돌려준다* — 실패 절이 없으면 그
    결정론 발화가 응답 파일에 라이브처럼 들어간다(ⓑ).
  - 폴백·강등만 나는 실행은 응답 파일을 *채운다* — 공허 수집 절이 없으면 exit 0이다(ⓓ·ⓖ).
  - `--resume`은 이미 쓴 사례를 *다시 돌릴 수 있다* — 건너뛰기 절이 없으면 중복 줄이 생겨
    `load_responses`가 거부한다(ⓔ).
  - 실행 식별의 평가셋 지문은 *정본이 아닌* 평가셋 파일로 잰다 — 경로를 무시하고 정본 지문을 쓰면
    통과해 버리지 않게(ⓕ).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from whymath_backend.harness import ai_quality_eval as cli
from whymath_backend.harness import ai_quality_live_collect as live
from whymath_backend.harness.ai_quality_candidates import (
    RESPONSE_SCHEMA,
    build_eos_candidate,
    load_responses,
)
from whymath_backend.harness.ai_quality_eval_set import DEFAULT_EVAL_SET, load_eval_set
from whymath_backend.harness.ai_quality_registry import Registry, default_repo_root, load_registry
from whymath_backend.harness.wh1_shadow import record_logger
from whymath_backend.harness.wh1_tutor_output import (
    TutorOutputReceipt,
    build_tutor_output,
    validate_tutor_output,
)
from whymath_backend.l3.interfaces import InMemoryCache, RecordingTraceSink
from whymath_backend.l3.models import (
    CostTier,
    GenerationResult,
    LocalModelTier,
    ModelFamily,
    RoutingDecision,
)
from whymath_backend.l3.pipeline import served_cloud_seat

_MARKER = "고유발화표지P378"
_QUESTION = json.dumps(
    {
        "kind": "end_turn",
        "action_type": "질문",
        "utterance": f"{_MARKER} 어떤 규칙을 썼는지 말해 볼래?",
    },
    ensure_ascii=False,
)


# ──────────────────────────────────────────────────────────────────────────
# 픽스처
# ──────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def registry() -> Registry:
    return load_registry()


@pytest.fixture(autouse=True)
def _cached_registry(monkeypatch: pytest.MonkeyPatch, registry: Registry) -> None:
    """레지스트리 적재(약 3.5초)를 사례마다 반복하지 않는다 — 같은 객체를 돌려준다."""
    monkeypatch.setattr(live, "load_registry", lambda: registry)
    monkeypatch.setattr(cli, "load_registry", lambda: registry)


def _canonical_rows() -> list[tuple[str, dict[str, Any]]]:
    lines = (default_repo_root() / DEFAULT_EVAL_SET).read_text(encoding="utf-8").splitlines()
    return [(line, json.loads(line)) for line in lines if line.strip()]


def _small_eval(path: Path, *, with_choices: bool = True) -> Path:
    """정본 평가셋에서 힌트 1건(사다리 1위치) + 첫 선택 문항의 오답·정답 사례를 고른 부분 평가셋."""
    rows = _canonical_rows()
    hint = next(r for _, r in rows if r["kind"] == "hint" and r["ladder_pos"] == 1)
    base = next(r for _, r in rows if r["kind"] == "choice")["case_id"].rsplit("-", 1)[0]
    wanted = {hint["case_id"]}
    if with_choices:
        wanted |= {r["case_id"] for _, r in rows if r["case_id"].startswith(base + "-")}
    path.write_text(
        "".join(line + "\n" for line, r in rows if r["case_id"] in wanted), encoding="utf-8"
    )
    return path


def _ids(path: Path) -> list[str]:
    return [json.loads(line)["case_id"] for line in path.read_text(encoding="utf-8").splitlines()]


class _Scripted:
    """스크립트 provider — 호출 번호로 실패·지연을 주입한다(사례는 순차라 번호가 결정론이다)."""

    def __init__(
        self,
        *,
        reply: str = _QUESTION,
        mode: str = "reply",
        fail_calls: frozenset[int] = frozenset(),
        exc_factory: Callable[[], BaseException] | None = None,
        sleep_calls: frozenset[int] = frozenset(),
        on_call: Callable[[int], None] | None = None,
    ) -> None:
        self.reply = reply
        self.mode = mode
        self.fail_calls = fail_calls
        self.exc_factory = exc_factory
        self.sleep_calls = sleep_calls
        self.on_call = on_call
        self.calls = 0

    async def generate(
        self, prompt: str, system: str, decision: RoutingDecision, **kwargs: Any
    ) -> GenerationResult:
        self.calls += 1
        if self.on_call is not None:
            self.on_call(self.calls)
        if self.calls in self.sleep_calls:
            await asyncio.sleep(30)
        if self.calls in self.fail_calls or self.mode == "fail":
            assert self.exc_factory is not None
            raise self.exc_factory()
        if self.mode == "budget":
            return GenerationResult(json.dumps({"kind": "match_misconception"}))
        if self.mode == "garbage":
            return GenerationResult("이건 JSON 객체가 아니다")
        return GenerationResult(self.reply)


def _http_503() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://127.0.0.1:11434/api/chat")
    response = httpx.Response(
        503, text="upstream overloaded — key sk-or-secret123456", request=request
    )
    return httpx.HTTPStatusError("503 Service Unavailable", request=request, response=response)


def _run(out: Path, eval_path: Path, provider: Any, *extra: str) -> tuple[int, str]:
    stream = io.StringIO()

    def _deps(settings: Any) -> live.LiveDeps:
        return live.LiveDeps(
            provider=provider,
            trace=RecordingTraceSink(),
            cache=InMemoryCache(),
            declared_models={"cloud_seat": "test-seat"},
            trace_configured=None,
        )

    code = live.main(
        ["--out", str(out), "--eval-set", str(eval_path), *extra], deps_factory=_deps, stream=stream
    )
    return code, stream.getvalue()


def _failures(out: Path) -> list[dict[str, Any]]:
    path, _ = live.output_paths(out)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _run_json(out: Path) -> dict[str, Any]:
    _, path = live.output_paths(out)
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


# ──────────────────────────────────────────────────────────────────────────
# ⓐ 정상 — 평가기가 그대로 읽는다
# ──────────────────────────────────────────────────────────────────────────
def test_normal_cases_are_loadable_and_evaluable(tmp_path: Path, registry: Registry) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    code, _ = _run(out, small, _Scripted())
    assert code == live.EXIT_OK
    responses = load_responses(out)  # 메타 줄이 섞이면 schema 위반으로 거부된다
    assert sorted(responses) == sorted(_ids(small))
    assert {r.origin for r in responses.values()} == {live.LIVE_ORIGIN}
    eval_set = load_eval_set(registry, small)
    for case in eval_set.cases:
        verdict = validate_tutor_output(
            dict(responses[case.case_id].tutor_output),
            known_concept_ids=frozenset({case.concept_id}),
        )
        assert not isinstance(verdict, str), (case.case_id, verdict)
        # 서버 측 재료는 결정론 후보와 같은 원천 — 진단·개념이 같다.
    eos = build_eos_candidate(eval_set, registry)
    for case_id, response in responses.items():
        assert response.tutor_output["diagnosis"] == eos[case_id].tutor_output["diagnosis"]
    report_path = tmp_path / "report.json"
    eval_code = cli.main(
        ["--eval-set", str(small), "--responses", str(out), "--json", str(report_path)]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["candidate"] == f"external:{out}"
    assert report["missing_responses"] == 0
    assert all(axis["n_cases"] == len(responses) for axis in report["axes"])
    # 3사례는 축별 최소 표본(30) 미만이라 측정 실패(2)가 정답이다 — 통과로 접히지 않는다.
    assert eval_code == 2


def test_utterance_stays_only_in_the_response_file(tmp_path: Path) -> None:
    """응답 원문은 평가 산출물에만 — 진행 출력·실행 식별·실패 파일에는 없다(acceptance ①)."""
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    # 첫 호출(힌트 사례 — 정책 명시 발화가 노출되는 턴)만 성공, 나머지는 전부 실패 파일로 간다.
    provider = _Scripted(fail_calls=frozenset(range(2, 100)), exc_factory=_http_503)
    code, printed = _run(out, small, provider)
    assert code == live.EXIT_PARTIAL
    assert _MARKER in out.read_text(encoding="utf-8")
    failures_path, run_path = live.output_paths(out)
    for text in (printed, run_path.read_text(encoding="utf-8")):
        assert _MARKER not in text
    assert _MARKER not in failures_path.read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────
# ⓑ provider 예외 — 실패 파일로, 나머지는 계속
# ──────────────────────────────────────────────────────────────────────────
def test_provider_http_error_goes_to_failures_and_rest_continue(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    ids = _ids(small)
    code, _ = _run(out, small, _Scripted(fail_calls=frozenset({1}), exc_factory=_http_503))
    assert code == live.EXIT_PARTIAL
    responses = load_responses(out)
    # 정책은 그 예외를 강등으로 흡수해 발화를 돌려줬다 — 그래도 응답 파일에 들어가면 안 된다.
    assert ids[0] not in responses
    assert sorted(responses) == sorted(ids[1:])
    [failure] = _failures(out)
    assert failure["schema"] == live.FAILURE_SCHEMA
    assert failure["case_id"] == ids[0]
    assert failure["kind"] == "provider_error"
    assert failure["exc_type"] == "HTTPStatusError"
    assert failure["primary_outcome"] == "fallback_llm_degraded"
    assert failure["timeout"] is False
    [fault] = failure["faults"]
    assert fault["http_status"] == 503
    assert "upstream overloaded" in fault["body_excerpt"]
    assert "sk-or-secret123456" not in json.dumps(failure, ensure_ascii=False)
    assert fault["seat"]["cost_tier"] == "local"
    counts = _run_json(out)["runs"][-1]["counts"]
    assert (counts["failed"], counts["live"], counts["provider_faults"]) == (1, len(ids) - 1, 1)


# ──────────────────────────────────────────────────────────────────────────
# ⓒ 타임아웃 — 러너 예산 · 바깥 방어선
# ──────────────────────────────────────────────────────────────────────────
def test_runner_timeout_is_a_failure_with_timeout_flag(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    ids = _ids(small)
    code, _ = _run(out, small, _Scripted(sleep_calls=frozenset({1})), "--timeout", "0.2")
    assert code == live.EXIT_PARTIAL
    [failure] = _failures(out)
    assert failure["case_id"] == ids[0]
    assert failure["kind"] == "runner_timeout"
    assert failure["primary_outcome"] == "fallback_timeout"
    assert failure["timeout"] is True
    [fault] = failure["faults"]
    assert fault["cancelled"] is True and fault["exc_type"] == "CancelledError"
    assert sorted(load_responses(out)) == sorted(ids[1:])


def test_outer_timeout_backstop_when_runner_hangs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """러너 밖에서 멈춘 경우 — 바깥 방어선이 끊고 그 사례만 실패로 남긴다."""
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    ids = _ids(small)
    real = live.run_wh1_primary_turn
    seen = {"n": 0}

    async def _hang_first(**kwargs: Any) -> str | None:
        seen["n"] += 1
        if seen["n"] == 1:
            await asyncio.sleep(30)
        return await real(**kwargs)

    monkeypatch.setattr(live, "run_wh1_primary_turn", _hang_first)
    prose = live.get_settings().wh1_prose_timeout_seconds
    monkeypatch.setattr(live, "_OUTER_GRACE_SECONDS", -prose)  # 바깥 = 한 턴 예산(0.2초)
    code, _ = _run(out, small, _Scripted(), "--timeout", "0.2")
    assert code == live.EXIT_PARTIAL
    [failure] = _failures(out)
    assert (failure["case_id"], failure["kind"]) == (ids[0], "outer_timeout")
    assert failure["exc_type"] == "TimeoutError" and failure["timeout"] is True
    assert sorted(load_responses(out)) == sorted(ids[1:])


# ──────────────────────────────────────────────────────────────────────────
# ⓓ 폴백·강등 — 표지·건수, 라이브로 위장 금지
# ──────────────────────────────────────────────────────────────────────────
def test_primary_none_falls_back_with_origin_and_count(tmp_path: Path, registry: Registry) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    code, _ = _run(out, small, _Scripted(mode="budget"))
    assert code == live.EXIT_MEASUREMENT  # 폴백만으로 채운 파일은 라이브 측정이 아니다
    responses = load_responses(out)
    eos = build_eos_candidate(load_eval_set(registry, small), registry)
    for case_id, response in responses.items():
        assert response.origin == live.FALLBACK_ORIGIN
        assert response.note is not None and "fallback_budget_exhausted" in response.note
        assert dict(response.tutor_output) == dict(eos[case_id].tutor_output)
    record = _run_json(out)["runs"][-1]
    assert record["counts"]["fallback"] == len(responses)
    assert record["counts"]["live"] == 0
    assert record["primary_outcomes"] == {"fallback_budget_exhausted": len(responses)}
    assert record["exit_code"] == live.EXIT_MEASUREMENT


def test_policy_degrade_is_marked_not_live(tmp_path: Path) -> None:
    """LLM 출력이 계약 위반이면 정책이 결정론으로 강등한다 — 발화는 돌아오지만 라이브가 아니다."""
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    code, _ = _run(out, small, _Scripted(mode="garbage"))
    assert code == live.EXIT_MEASUREMENT
    responses = load_responses(out)
    assert {r.origin for r in responses.values()} == {live.DEGRADED_ORIGIN}
    assert {r.tutor_output["explanation_source"] for r in responses.values()} == {
        "harness_template"
    }
    assert all("fallback_llm_degraded" in (r.note or "") for r in responses.values())
    assert _run_json(out)["runs"][-1]["counts"]["degraded"] == len(responses)


def test_rebuild_rejection_keeps_served_structure_with_note(registry: Registry) -> None:
    """사례 판정으로 재조립이 거부되면(오답 턴의 격려) 러너가 서빙한 구조체를 주석과 함께 싣는다."""
    eval_set = load_eval_set(registry)
    case = next(c for c in eval_set.cases if c.verdict == "incorrect")
    inputs = live.live_turn_inputs(case, eval_set, registry)
    served = build_tutor_output(
        explanation="잘하고 있어!",
        explanation_source="llm",
        action_type="격려",
        mode_guard_replaced=False,
        verify_verdict=None,  # 하네스 판정이 없던 턴 — 러너는 통과시켰다
        hypotheses=inputs.active_hypotheses,
        concept_id=case.concept_id,
        known_concept_ids=frozenset({case.concept_id}),
        hint_level=inputs.hint_level,
    )
    assert not isinstance(served, str)
    ledger = live.CaseLedger(observations=[{"primary": True, "primary_outcome": "adopted"}])
    result = live.classify_case(
        case,
        inputs,
        utterance=served.explanation,
        receipt=TutorOutputReceipt(output=served),
        ledger=ledger,
        eos=build_eos_candidate(eval_set, registry)[case.case_id],
        outer_error=None,
        elapsed_ms=1,
    )
    assert result.category == "live" and result.rebuild_rejected
    assert result.response is not None
    assert result.response.tutor_output == served.model_dump(mode="json")
    assert "재조립" in (result.response.note or "")


def test_strategy_inverse_matches_the_builder() -> None:
    """역매핑 드리프트 동결 — 빌더의 행위 유형 → 전략을 정확히 되돌린다."""
    for action in ("질문", "힌트", "출제", "격려"):
        out = build_tutor_output(
            explanation="어떻게 생각해?",
            explanation_source="llm",
            action_type=action,  # type: ignore[arg-type]
            mode_guard_replaced=False,
            verify_verdict=None,
            hypotheses=(),
            concept_id=None,
            known_concept_ids=frozenset(),
            hint_level=1,
        )
        assert not isinstance(out, str)
        assert live._STRATEGY_TO_ACTION[out.response_strategy] == action
    assert len(live._STRATEGY_TO_ACTION) == 4


# ──────────────────────────────────────────────────────────────────────────
# ⓔ --resume
# ──────────────────────────────────────────────────────────────────────────
def test_resume_skips_done_and_retries_failed(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    ids = _ids(small)
    first, _ = _run(out, small, _Scripted(fail_calls=frozenset({1}), exc_factory=_http_503))
    assert first == live.EXIT_PARTIAL
    again = _Scripted()
    code, _ = _run(out, small, again, "--resume")
    assert code == live.EXIT_OK
    responses = load_responses(out)  # 중복 case_id면 여기서 거부된다
    assert sorted(responses) == sorted(ids)
    assert again.calls == 1  # 힌트 사례 1건만 다시 돌았다(힌트 턴 = LLM 1호출)
    payload = _run_json(out)
    assert len(payload["runs"]) == 2
    second = payload["runs"][-1]
    assert second["counts"]["attempted"] == 1
    assert second["counts"]["skipped_resume"] == len(ids) - 1
    assert payload["file_totals"]["responses"] == len(ids)
    assert len(_failures(out)) == 1  # 첫 실행의 실패 기록은 이력으로 남는다


def test_existing_output_without_resume_is_refused(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    out.write_text("이전 실행의 증거\n", encoding="utf-8")
    code, _ = _run(out, small, _Scripted())
    assert code == live.EXIT_MEASUREMENT
    assert out.read_text(encoding="utf-8") == "이전 실행의 증거\n"


def test_resume_rejects_a_different_eval_set(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    other = _small_eval(tmp_path / "other.jsonl", with_choices=False)
    out = tmp_path / "live.jsonl"
    first, _ = _run(out, small, _Scripted(), "--limit", "1")
    assert first == live.EXIT_OK
    before = out.read_bytes()
    code, _ = _run(out, other, _Scripted(), "--resume")
    assert code == live.EXIT_MEASUREMENT
    assert out.read_bytes() == before


def test_resume_rejects_a_corrupt_response_file(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    first, _ = _run(out, small, _Scripted(), "--limit", "1")
    assert first == live.EXIT_OK
    with out.open("a", encoding="utf-8") as handle:
        handle.write('{"schema": "ai-quality-response/v1", "case_id": "잘린')  # 중간에 끊긴 줄
    code, _ = _run(out, small, _Scripted(), "--resume")
    assert code == live.EXIT_MEASUREMENT


# ──────────────────────────────────────────────────────────────────────────
# ⓕ 실행 식별
# ──────────────────────────────────────────────────────────────────────────
def test_run_json_identifies_eval_set_models_and_survives_midway(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    seen_midway: list[dict[str, Any]] = []

    def _peek(call: int) -> None:
        if call == 1:  # 첫 LLM 호출 시점 — 실행 식별이 이미 디스크에 있어야 한다
            seen_midway.append(_run_json(out))

    code, _ = _run(out, small, _Scripted(on_call=_peek))
    assert code == live.EXIT_OK
    [midway] = seen_midway
    assert midway["runs"][-1]["status"] == "running"
    payload = _run_json(out)
    expected = hashlib.sha256(small.read_bytes()).hexdigest()
    canonical = hashlib.sha256((default_repo_root() / DEFAULT_EVAL_SET).read_bytes()).hexdigest()
    assert expected != canonical  # 정본 지문을 쓰면 통과해 버리지 않는 픽스처
    assert payload["schema"] == live.RUN_SCHEMA
    assert payload["eval_set"]["sha256"] == expected == midway["eval_set"]["sha256"]
    record = payload["runs"][-1]
    assert record["status"] == "finished" and record["exit_code"] == live.EXIT_OK
    assert record["started_at"].endswith("Z") and record["finished_at"].endswith("Z")
    assert record["declared_models"] == {"cloud_seat": "test-seat"}
    assert record["trace"]["surface"] == "probe"
    observed = record["observed_models"]
    assert observed and all(m["cost_tier"] == "local" for m in observed)
    assert sum(m["calls"] for m in observed) == record["counts"]["llm_calls_recorded"] > 0
    assert set(record["git"]) >= {"head", "dirty"}


# ──────────────────────────────────────────────────────────────────────────
# ⓖ 공허 수집 = exit 1
# ──────────────────────────────────────────────────────────────────────────
def test_all_failures_is_measurement_failure(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    code, _ = _run(out, small, _Scripted(mode="fail", exc_factory=_http_503))
    assert code == live.EXIT_MEASUREMENT
    assert len(_failures(out)) == len(_ids(small))
    assert not out.exists() or not out.read_text(encoding="utf-8").strip()


def test_run_with_zero_live_is_failure_even_if_file_has_live(tmp_path: Path) -> None:
    """이번 실행이 라이브 0이면 exit 1 — 이전 실행의 라이브가 파일에 있어도 가려지지 않는다."""
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    first, _ = _run(out, small, _Scripted(), "--limit", "1")
    assert first == live.EXIT_OK
    code, _ = _run(out, small, _Scripted(mode="budget"), "--resume")
    assert code == live.EXIT_MEASUREMENT


def test_nothing_left_with_zero_live_in_file_is_failure(tmp_path: Path) -> None:
    """시도할 사례가 없는 --resume이라도 파일 전체에 라이브가 0이면 exit 1."""
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    first, _ = _run(out, small, _Scripted(mode="budget"))
    assert first == live.EXIT_MEASUREMENT
    code, _ = _run(out, small, _Scripted(), "--resume")
    assert code == live.EXIT_MEASUREMENT
    assert _run_json(out)["runs"][-1]["counts"]["attempted"] == 0


# ──────────────────────────────────────────────────────────────────────────
# 래퍼·원인 추출 단위
# ──────────────────────────────────────────────────────────────────────────
def _decision() -> RoutingDecision:
    return RoutingDecision(
        cost_tier=CostTier.LOCAL,
        local_family=ModelFamily.GENERAL,
        local_model=LocalModelTier.FAST,
        mode="sync",
        reason="test",
        est_latency_ms=1000,
    )


def test_recording_provider_forwards_unchanged_and_keeps_seat_surface() -> None:
    received: list[tuple[Any, ...]] = []

    class _Inner:
        cloud_seat = "openrouter"

        async def generate(self, *args: Any, **kwargs: Any) -> GenerationResult:
            received.append((args, kwargs))
            return GenerationResult("ok")

    class _NoSeat:
        async def generate(self, *args: Any, **kwargs: Any) -> GenerationResult:
            return GenerationResult("ok")

    decision = _decision()
    scope = live._Scope()
    wrapper = live.RecordingProvider(_Inner(), scope)  # type: ignore[arg-type]
    result = asyncio.run(wrapper.generate("p", "s", decision, temperature=0.3))
    assert result.text == "ok"
    [(args, kwargs)] = received
    assert args == ("p", "s", decision) and args[2] is decision
    assert kwargs == {"temperature": 0.3}  # 받지 않은 선택 인자는 넘기지 않는다
    assert served_cloud_seat(wrapper) == "openrouter"
    bare = live.RecordingProvider(_NoSeat(), scope)  # type: ignore[arg-type]
    assert served_cloud_seat(bare) == served_cloud_seat(_NoSeat())
    assert scope.ledger.faults == []


def test_describe_fault_walks_the_cause_chain_for_timeout() -> None:
    try:
        try:
            raise httpx.ReadTimeout("read timed out")
        except httpx.ReadTimeout as inner:
            raise RuntimeError("Ollama 호출 실패") from inner
    except RuntimeError as exc:
        fault = live.describe_fault(exc, _decision())
    assert fault["chain"] == ["RuntimeError", "ReadTimeout"]
    assert fault["timeout"] is True
    assert fault["http_status"] is None


def test_describe_fault_survives_a_hostile_exception() -> None:
    class _HostileError(Exception):
        @property
        def response(self) -> object:
            raise RuntimeError("본문 접근 불가")

    fault = live.describe_fault(_HostileError("x"), None)
    assert fault["exc_type"] == "_HostileError"
    assert fault["extraction_error"] == "RuntimeError"


def test_observation_capture_restores_logger_level() -> None:
    before = record_logger.level
    sink: list[dict[str, object]] = []
    with live._capture_observations(sink):
        record_logger.info(json.dumps({"primary": True, "primary_outcome": "adopted"}))
        record_logger.info("JSON 아님")
    assert sink == [{"primary": True, "primary_outcome": "adopted"}]
    assert record_logger.level == before
    assert not any(isinstance(h, live._ObservationHandler) for h in record_logger.handlers)
    assert logging.getLogger(record_logger.name) is record_logger


def test_response_lines_use_the_shared_schema(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl", with_choices=False)
    out = tmp_path / "live.jsonl"
    code, _ = _run(out, small, _Scripted())
    assert code == live.EXIT_OK
    [line] = out.read_text(encoding="utf-8").splitlines()
    row = json.loads(line)
    assert row["schema"] == RESPONSE_SCHEMA
    assert set(row) == {
        "schema",
        "case_id",
        "tutor_output",
        "referenced_concept_ids",
        "origin",
        "note",
    }
