"""P3-78 라이브 품질 수집 도구 — 스크립트 provider로 실제 primary 러너를 hermetic하게 돌린다.

정상 입력에서 초록인 것은 증거가 아니다. 이 파일의 중심은 각 판정 절이 **없으면 통과해 버리는
입력**이다(CLAUDE.md '픽스처가 그 절을 실제로 밟는가'):
  - provider·파이프라인 예외가 난 사례는 정책이 강등으로 흡수해 발화를 *돌려준다* — 실패 절이
    없으면 그 결정론 발화가 응답 파일에 들어간다.
  - 발화 없는 `end_turn`만 주는 provider는 `adopted`를 *만든다* — 라이브 정의가 저자를 보지 않으면
    LLM 문장 0건으로 live=전건·exit 0이 된다.
  - 같은 개념·같은 신호의 사례는 같은 프롬프트를 *받는다* — 캐시를 실행 전체가 공유하면 provider를
    한 번만 부르고 나머지는 재생한다.
  - 보기 탭 턴은 앱이 풀이 단계를 *보내지 않는다* — 수집기가 단계를 넣으면 정답 억제 백스톱이
    LLM 발화를 막아 선택 누설 축이 구조적으로 0이 된다.
  - 이어서 돌린 실행의 결말은 *파일 전체*로 판정한다 — 이번 실행만 보면 마지막 몇 건의 폴백이 공허로,
    243 폴백 + 1 라이브가 통과로 보인다.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

from whymath_backend.harness import ai_quality_eval as cli
from whymath_backend.harness import ai_quality_live_collect as live
from whymath_backend.harness import wh1_primary
from whymath_backend.harness.ai_quality_candidates import (
    RESPONSE_SCHEMA,
    build_eos_candidate,
    case_hypotheses,
    load_responses,
)
from whymath_backend.harness.ai_quality_eval_set import DEFAULT_EVAL_SET, load_eval_set
from whymath_backend.harness.ai_quality_registry import Registry, default_repo_root, load_registry
from whymath_backend.harness.wh1_llm_policy import _SYSTEM_PROMPT
from whymath_backend.harness.wh1_shadow import record_logger
from whymath_backend.harness.wh1_tutor_output import (
    TutorOutputReceipt,
    build_tutor_output,
    validate_tutor_output,
)
from whymath_backend.l3.interfaces import InMemoryCache, RecordingTraceSink, TrafficSurface
from whymath_backend.l3.models import (
    CostTier,
    GenerationResult,
    LocalModelTier,
    ModelFamily,
    RoutingDecision,
)
from whymath_backend.l3.pipeline import served_cloud_seat

_MARKER = "고유발화표지P378"
_SAY = json.dumps(
    {"kind": "end_turn", "action_type": "질문", "utterance": f"{_MARKER} 어떤 규칙을 떠올렸어?"},
    ensure_ascii=False,
)
_SILENT = json.dumps({"kind": "end_turn", "action_type": "질문"}, ensure_ascii=False)
_SHARED_PROMPT_IDS = ("aq-h-01-01-l1", "aq-h-01-02-l1")
"""같은 개념·같은 신호·같은 문제 구조 — 첫 정책 프롬프트가 같은 두 사례(2026-10-31 실측)."""


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


def _eval_file(path: Path, ids: Sequence[str]) -> Path:
    wanted = set(ids)
    path.write_text(
        "".join(line + "\n" for line, r in _canonical_rows() if r["case_id"] in wanted),
        encoding="utf-8",
    )
    return path


def _small_eval(path: Path, *, with_choices: bool = True) -> Path:
    """정본 평가셋에서 힌트 1건(사다리 1위치) + 첫 선택 문항의 오답·정답 사례를 고른 부분 평가셋."""
    rows = _canonical_rows()
    hint = next(r for _, r in rows if r["kind"] == "hint" and r["ladder_pos"] == 1)
    base = next(r for _, r in rows if r["kind"] == "choice")["case_id"].rsplit("-", 1)[0]
    wanted = [hint["case_id"]]
    if with_choices:
        wanted += [r["case_id"] for _, r in rows if r["case_id"].startswith(base + "-")]
    return _eval_file(path, wanted)


def _ids(path: Path) -> list[str]:
    return [json.loads(line)["case_id"] for line in path.read_text(encoding="utf-8").splitlines()]


class _Scripted:
    """스크립트 provider — 호출 번호로 응답·실패·지연을 주입한다(사례는 순차라 번호가 결정론이다)."""

    def __init__(
        self,
        *,
        reply: str = _SAY,
        mode: str = "reply",
        replies: dict[int, str] | None = None,
        fail_calls: frozenset[int] = frozenset(),
        exc_factory: Callable[[], BaseException] | None = None,
        sleep_calls: frozenset[int] = frozenset(),
        on_call: Callable[[int], None] | None = None,
    ) -> None:
        self.reply = reply
        self.mode = mode
        self.replies = replies or {}
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
        return GenerationResult(self.replies.get(self.calls, self.reply))


def _http_503() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://127.0.0.1:11434/api/chat")
    response = httpx.Response(
        503, text="upstream overloaded — key sk-or-secret123456", request=request
    )
    return httpx.HTTPStatusError("503 Service Unavailable", request=request, response=response)


def _run(
    out: Path,
    eval_path: Path,
    provider: Any,
    *extra: str,
    trace: Any = None,
    cache_factory: Callable[[], Any] = InMemoryCache,
    trace_configured: bool | None = None,
) -> tuple[int, str]:
    stream = io.StringIO()

    def _deps(settings: Any) -> live.LiveDeps:
        return live.LiveDeps(
            provider=provider,
            trace=trace if trace is not None else RecordingTraceSink(),
            declared_models={"cloud_seat": "test-seat"},
            trace_configured=trace_configured,
            cache_factory=cache_factory,
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
# 정상 — 평가기가 그대로 읽고, 라이브는 LLM이 쓴 발화뿐이다
# ──────────────────────────────────────────────────────────────────────────
def test_normal_cases_are_loadable_and_evaluable(tmp_path: Path, registry: Registry) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    code, _ = _run(out, small, _Scripted())
    assert code == live.EXIT_OK
    responses = load_responses(out)  # 메타 줄이 섞이면 schema 위반으로 거부된다
    assert sorted(responses) == sorted(_ids(small))
    for response in responses.values():
        # 라이브 = LLM이 쓴 발화가 학생 대면 본문으로 나간 턴 — 저자와 본문을 함께 단언한다.
        assert response.origin == live.LIVE_ORIGIN
        assert response.tutor_output["explanation_source"] == "llm"
        assert _MARKER in str(response.tutor_output["explanation"])
    eval_set = load_eval_set(registry, small)
    eos = build_eos_candidate(eval_set, registry)
    for case in eval_set.cases:
        output = dict(responses[case.case_id].tutor_output)
        verdict = validate_tutor_output(output, known_concept_ids=frozenset({case.concept_id}))
        assert not isinstance(verdict, str), (case.case_id, verdict)
        assert output["diagnosis"] == eos[case.case_id].tutor_output["diagnosis"]
    report_path = tmp_path / "report.json"
    eval_code = cli.main(
        ["--eval-set", str(small), "--responses", str(out), "--json", str(report_path)]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["candidate"] == f"external:{out}"
    assert report["missing_responses"] == 0
    assert all(axis["n_cases"] == len(responses) for axis in report["axes"])
    assert eval_code == 2  # 축별 최소 표본(30) 미만 — 측정 실패가 정답이다


def test_harness_only_adopted_turns_are_not_live(tmp_path: Path) -> None:
    """발화 없는 end_turn만 주는 provider — 전부 adopted지만 LLM 문장은 0건이다."""
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    code, printed = _run(out, small, _Scripted(reply=_SILENT))
    assert code == live.EXIT_MEASUREMENT  # 파일 전체 라이브 0 = 공허
    responses = load_responses(out)
    assert {r.origin for r in responses.values()} == {live.HARNESS_ORIGIN}
    assert {r.tutor_output["explanation_source"] for r in responses.values()} == {
        "harness_template"
    }
    payload = _run_json(out)
    record = payload["runs"][-1]
    assert record["primary_outcomes"] == {"adopted": len(responses)}
    assert (record["counts"]["live"], record["counts"]["harness"]) == (0, len(responses))
    assert payload["file_totals"]["live"] == 0
    assert f"하네스 {len(responses)}" in printed


# ──────────────────────────────────────────────────────────────────────────
# [H1] 보기 탭 턴 — 앱 요청 그대로(풀이 단계 없음)
# ──────────────────────────────────────────────────────────────────────────
def test_turn_inputs_match_the_app_request(registry: Registry) -> None:
    eval_set = load_eval_set(registry)
    settings = live.get_settings()
    choice = next(c for c in eval_set.cases if c.kind == "choice" and c.verdict == "incorrect")
    material = eval_set.materials[choice.problem_id]
    inputs = live.live_turn_inputs(choice, eval_set, registry, settings=settings)
    assert choice.selected_choice_index is not None
    chosen = material.choices[choice.selected_choice_index]
    assert inputs.solution_steps == ()  # ChatController.send는 solutionSteps를 보내지 않는다
    assert (inputs.student_input, inputs.student_solution) == (chosen, chosen)
    assert inputs.selected_choice_index == choice.selected_choice_index
    assert inputs.turn_index == 1  # create_session
    assert inputs.active_hypotheses == case_hypotheses(choice, eval_set)
    hint = next(c for c in eval_set.cases if c.kind == "hint" and c.ladder_pos == 3)
    hint_inputs = live.live_turn_inputs(hint, eval_set, registry, settings=settings)
    assert hint.signals is not None
    assert hint_inputs.solution_steps == ()
    assert hint_inputs.turn_index == hint.signals.turn_count + 1  # append_turns
    assert hint_inputs.hint_level == 3


def test_choice_turn_llm_utterance_reaches_the_response(tmp_path: Path) -> None:
    """단계 제출이 없는 턴이라 정답 억제 백스톱이 걸리지 않는다 — 서빙처럼 LLM 발화가 나간다."""
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    code, _ = _run(out, small, _Scripted())
    assert code == live.EXIT_OK
    choices = {k: v for k, v in load_responses(out).items() if k.startswith("aq-c-")}
    assert len(choices) >= 2
    for response in choices.values():
        assert response.tutor_output["explanation_source"] == "llm"
        assert _MARKER in str(response.tutor_output["explanation"])
    by_kind = _run_json(out)["runs"][-1]["counts"]["explanation_source_by_kind"]
    assert by_kind["choice"] == {"llm": len(choices)}


# ──────────────────────────────────────────────────────────────────────────
# [H3] 캐시 재생 금지 · 첫 프롬프트 지문 · 유효 표본 상한
# ──────────────────────────────────────────────────────────────────────────
def test_cache_is_fresh_per_case_and_shared_prompts_are_counted(tmp_path: Path) -> None:
    eval_path = _eval_file(tmp_path / "eval.jsonl", _SHARED_PROMPT_IDS)
    out = tmp_path / "live.jsonl"
    provider = _Scripted()
    code, printed = _run(out, eval_path, provider)
    assert code == live.EXIT_OK
    assert provider.calls == 2  # 두 사례 모두 provider까지 갔다 — 재생 0
    payload = _run_json(out)
    record = payload["runs"][-1]
    assert record["counts"]["cache_hits"] == 0
    first = record["first_prompts"]
    assert set(first) == set(_SHARED_PROMPT_IDS)
    assert first[_SHARED_PROMPT_IDS[0]] == first[_SHARED_PROMPT_IDS[1]]  # 같은 프롬프트
    assert len(first[_SHARED_PROMPT_IDS[0]]) == 64  # sha256 hex
    assert payload["file_totals"]["effective_sample_upper_bound"] == 1
    assert record["distinct_first_prompts"] == {"total": 1, "hint": 1}
    assert "유효 표본 상한(서로 다른 첫 프롬프트) 1" in printed
    raw = json.dumps(payload, ensure_ascii=False)
    assert _SYSTEM_PROMPT[:40] not in raw  # 지문만 — 프롬프트 원문은 남기지 않는다


# ──────────────────────────────────────────────────────────────────────────
# 실패 — 응답 파일에 쓰지 않고 원인을 남긴다
# ──────────────────────────────────────────────────────────────────────────
def test_provider_http_error_goes_to_failures_and_rest_continue(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    ids = _ids(small)
    code, _ = _run(out, small, _Scripted(fail_calls=frozenset({1}), exc_factory=_http_503))
    assert code == live.EXIT_INCOMPLETE_FAILED
    responses = load_responses(out)
    assert ids[0] not in responses  # 정책이 흡수해 발화를 돌려줬어도 응답 파일에 넣지 않는다
    assert sorted(responses) == sorted(ids[1:])
    [failure] = _failures(out)
    assert failure["schema"] == live.FAILURE_SCHEMA
    assert failure["run_id"] == _run_json(out)["runs"][-1]["run_id"]
    assert (failure["case_id"], failure["kind"]) == (ids[0], "provider_error")
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


def test_runner_exception_keeps_the_swallowed_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """러너가 예외를 삼켜 None을 돌려도 타입명·메시지 일부를 실패 파일에 남긴다(acceptance ③)."""
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    ids = _ids(small)
    real = wh1_primary.assemble_probe_candidate_pool
    seen = {"n": 0}

    async def _boom_first(*args: Any, **kwargs: Any) -> Any:
        seen["n"] += 1
        if seen["n"] == 1:
            raise RuntimeError("probe pool unavailable")
        return await real(*args, **kwargs)

    monkeypatch.setattr(wh1_primary, "assemble_probe_candidate_pool", _boom_first)
    code, _ = _run(out, small, _Scripted())
    assert code == live.EXIT_INCOMPLETE_FAILED
    [failure] = _failures(out)
    assert (failure["case_id"], failure["kind"]) == (ids[0], "runner_exception")
    assert failure["exc_type"] == "RuntimeError"
    [swallowed] = failure["swallowed"]
    assert swallowed["exc_type"] == "RuntimeError"
    assert "probe pool unavailable" in swallowed["message_excerpt"]
    assert sorted(load_responses(out)) == sorted(ids[1:])


def test_pipeline_error_absorbed_by_policy_is_a_failure(tmp_path: Path) -> None:
    """provider 밖(캐시·파이프라인) 예외를 정책이 강등으로 흡수 — 강등이 아니라 인프라 실패다."""
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    ids = _ids(small)
    made = {"n": 0}

    class _BrokenCache(InMemoryCache):
        async def get(self, key: str) -> str | None:
            raise ConnectionError("cache down")

    def _factory() -> InMemoryCache:
        made["n"] += 1
        return _BrokenCache() if made["n"] == 1 else InMemoryCache()

    code, _ = _run(out, small, _Scripted(), cache_factory=_factory)
    assert code == live.EXIT_INCOMPLETE_FAILED
    [failure] = _failures(out)
    assert (failure["case_id"], failure["kind"]) == (ids[0], "pipeline_error")
    assert failure["exc_type"] == "ConnectionError"
    assert failure["faults"] == []  # provider까지 가지 않았다
    assert sorted(load_responses(out)) == sorted(ids[1:])


def test_runner_timeout_is_a_failure_with_timeout_flag(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    ids = _ids(small)
    code, _ = _run(out, small, _Scripted(sleep_calls=frozenset({1})), "--timeout", "0.2")
    assert code == live.EXIT_INCOMPLETE_FAILED
    [failure] = _failures(out)
    assert (failure["case_id"], failure["kind"]) == (ids[0], "runner_timeout")
    assert failure["primary_outcome"] == "fallback_timeout"
    assert failure["timeout"] is True
    [fault] = failure["faults"]
    assert fault["cancelled"] is True and fault["exc_type"] == "CancelledError"
    assert sorted(load_responses(out)) == sorted(ids[1:])


def test_outer_timeout_backstop_when_runner_hangs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    assert code == live.EXIT_INCOMPLETE_FAILED
    [failure] = _failures(out)
    assert (failure["case_id"], failure["kind"]) == (ids[0], "outer_timeout")
    assert failure["exc_type"] == "TimeoutError" and failure["timeout"] is True
    assert sorted(load_responses(out)) == sorted(ids[1:])


# ──────────────────────────────────────────────────────────────────────────
# 폴백·강등 — 표지·원인·건수
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
    assert record["primary_outcomes"] == {"fallback_budget_exhausted": len(responses)}
    assert record["exit_code"] == live.EXIT_MEASUREMENT


def test_policy_degrade_from_output_contract_is_marked_with_its_cause(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    code, _ = _run(out, small, _Scripted(mode="garbage"))
    assert code == live.EXIT_MEASUREMENT
    responses = load_responses(out)
    assert {r.origin for r in responses.values()} == {live.DEGRADED_ORIGIN}
    assert all("원인 output_schema" in (r.note or "") for r in responses.values())
    counts = _run_json(out)["runs"][-1]["counts"]
    assert counts["degraded"] == len(responses)
    assert counts["degraded_causes"] == {"output_schema": len(responses)}


def test_rebuild_rejection_keeps_served_structure_with_note(registry: Registry) -> None:
    """사례 판정으로 재조립이 거부되면(오답 턴의 격려) 러너가 서빙한 구조체를 주석과 함께 싣는다."""
    eval_set = load_eval_set(registry)
    case = next(c for c in eval_set.cases if c.verdict == "incorrect")
    inputs = live.live_turn_inputs(case, eval_set, registry, settings=live.get_settings())
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
# 종료 코드 — 응답 파일 전체 상태
# ──────────────────────────────────────────────────────────────────────────
def test_limit_stops_incomplete_with_its_own_code(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    code, printed = _run(out, small, _Scripted(), "--limit", "1")
    assert code == live.EXIT_INCOMPLETE_LIMIT
    assert f"남은 사례 {len(_ids(small)) - 1}" in printed
    assert _run_json(out)["file_totals"]["remaining"] == len(_ids(small)) - 1


def test_resume_that_completes_with_fallbacks_is_judged_on_the_whole_file(tmp_path: Path) -> None:
    """1차 실패 1건 → 재개에서 그 1건이 폴백으로 끝남: 파일은 완결·라이브 2/3 — 공허가 아니다."""
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    first, _ = _run(out, small, _Scripted(fail_calls=frozenset({1}), exc_factory=_http_503))
    assert first == live.EXIT_INCOMPLETE_FAILED
    code, _ = _run(out, small, _Scripted(mode="budget"), "--resume")
    assert code == live.EXIT_OK
    totals = _run_json(out)["file_totals"]
    assert totals["complete"] is True
    assert totals["by_origin"] == {live.FALLBACK_ORIGIN: 1, live.LIVE_ORIGIN: len(_ids(small)) - 1}


def test_complete_file_with_low_live_share_is_not_ok(tmp_path: Path) -> None:
    """라이브 1건 + 나머지 하네스 발화 — 완결이지만 LLM 발화 비중이 하한 미만이면 exit 4."""
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    code, _ = _run(out, small, _Scripted(reply=_SILENT, replies={1: _SAY}))
    assert code == live.EXIT_LOW_LIVE
    totals = _run_json(out)["file_totals"]
    assert totals["live"] == 1 and totals["complete"] is True
    lenient = tmp_path / "lenient.jsonl"
    provider = _Scripted(reply=_SILENT, replies={1: _SAY})
    code, _ = _run(lenient, small, provider, "--min-live-rate", "0.3")
    assert code == live.EXIT_OK


def test_all_failures_is_measurement_failure(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    code, _ = _run(out, small, _Scripted(mode="fail", exc_factory=_http_503))
    assert code == live.EXIT_MEASUREMENT
    assert len(_failures(out)) == len(_ids(small))
    assert not out.exists() or not out.read_text(encoding="utf-8").strip()


def test_nothing_left_with_zero_live_in_file_is_failure(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    first, _ = _run(out, small, _Scripted(mode="budget"))
    assert first == live.EXIT_MEASUREMENT
    code, _ = _run(out, small, _Scripted(), "--resume")
    assert code == live.EXIT_MEASUREMENT
    assert _run_json(out)["runs"][-1]["counts"]["attempted"] == 0


# ──────────────────────────────────────────────────────────────────────────
# --resume — 같은 평가셋·설정·코드에서만 이어 붙인다
# ──────────────────────────────────────────────────────────────────────────
def test_resume_skips_done_and_retries_failed(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    ids = _ids(small)
    first, _ = _run(out, small, _Scripted(fail_calls=frozenset({1}), exc_factory=_http_503))
    assert first == live.EXIT_INCOMPLETE_FAILED
    again = _Scripted()
    code, _ = _run(out, small, again, "--resume")
    assert code == live.EXIT_OK
    responses = load_responses(out)  # 중복 case_id면 여기서 거부된다
    assert sorted(responses) == sorted(ids)
    assert again.calls == 1  # 힌트 사례 1건만 다시 돌았다
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
    assert first == live.EXIT_INCOMPLETE_LIMIT
    before = out.read_bytes()
    code, _ = _run(out, other, _Scripted(), "--resume")
    assert code == live.EXIT_MEASUREMENT
    assert out.read_bytes() == before


def test_resume_rejects_changed_settings(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    first, _ = _run(out, small, _Scripted(), "--limit", "1", "--timeout", "15")
    assert first == live.EXIT_INCOMPLETE_LIMIT
    before = out.read_bytes()
    code, _ = _run(out, small, _Scripted(), "--resume", "--timeout", "20")
    assert code == live.EXIT_MEASUREMENT
    assert out.read_bytes() == before
    same, _ = _run(out, small, _Scripted(), "--resume", "--timeout", "15")
    assert same == live.EXIT_OK  # 같은 설정이면 이어진다(거부가 상수가 아니다)


def test_resume_rejects_a_different_git_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    heads = iter(["a" * 40, "b" * 40])
    monkeypatch.setattr(
        live, "_git_identity", lambda root: {"head": next(heads), "dirty_src": False}
    )
    first, _ = _run(out, small, _Scripted(), "--limit", "1")
    assert first == live.EXIT_INCOMPLETE_LIMIT
    code, _ = _run(out, small, _Scripted(), "--resume")
    assert code == live.EXIT_MEASUREMENT


def test_resume_without_run_json_is_refused(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    first, _ = _run(out, small, _Scripted(), "--limit", "1")
    assert first == live.EXIT_INCOMPLETE_LIMIT
    live.output_paths(out)[1].unlink()
    code, _ = _run(out, small, _Scripted(), "--resume")
    assert code == live.EXIT_MEASUREMENT


def test_resume_rejects_a_corrupt_response_file(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    first, _ = _run(out, small, _Scripted(), "--limit", "1")
    assert first == live.EXIT_INCOMPLETE_LIMIT
    with out.open("a", encoding="utf-8") as handle:
        handle.write('{"schema": "ai-quality-response/v1", "case_id": "잘린')  # 중간에 끊긴 줄
    code, _ = _run(out, small, _Scripted(), "--resume")
    assert code == live.EXIT_MEASUREMENT


# ──────────────────────────────────────────────────────────────────────────
# 실행 식별 · 관측 · 쓰기 실패 · 누설
# ──────────────────────────────────────────────────────────────────────────
class _SurfaceSink(RecordingTraceSink):
    traffic_surface = TrafficSurface.PROBE


def test_run_json_identifies_eval_set_models_and_survives_midway(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    seen_midway: list[dict[str, Any]] = []

    def _peek(call: int) -> None:
        if call == 1:  # 첫 LLM 호출 시점 — 실행 식별이 이미 디스크에 있어야 한다
            seen_midway.append(_run_json(out))

    code, _ = _run(out, small, _Scripted(on_call=_peek), trace=_SurfaceSink())
    assert code == live.EXIT_OK
    [midway] = seen_midway
    assert midway["runs"][-1]["status"] == "running"
    payload = _run_json(out)
    expected = hashlib.sha256(small.read_bytes()).hexdigest()
    canonical = hashlib.sha256((default_repo_root() / DEFAULT_EVAL_SET).read_bytes()).hexdigest()
    assert expected != canonical
    assert payload["schema"] == live.RUN_SCHEMA
    assert payload["eval_set"]["sha256"] == expected == midway["eval_set"]["sha256"]
    record = payload["runs"][-1]
    assert record["status"] == "finished" and record["exit_code"] == live.EXIT_OK
    assert record["started_at"].endswith("Z") and record["finished_at"].endswith("Z")
    assert len(record["run_id"]) == 32 and len(record["config_fingerprint"]) == 64
    assert record["declared_models"] == {"cloud_seat": "test-seat"}
    assert record["trace"]["surface"] == "probe"  # 싱크 값을 읽는다(하드코딩 아님)
    assert record["mode_guard"]["effective"] is False
    assert "pedagogy_pack" in record["unsupplied"] and "problem_brief" in record["supplied"]
    assert record["problem_briefs"]["found"] >= 1
    observed = record["observed_models"]
    assert observed and all(m["cost_tier"] == "local" for m in observed)
    assert sum(m["calls"] for m in observed) == record["counts"]["trace_records"] > 0
    assert set(record["git"]) >= {"head", "dirty_src"}


def test_unset_surface_is_recorded_as_unknown_not_probe(tmp_path: Path) -> None:
    small = _small_eval(tmp_path / "eval.jsonl", with_choices=False)
    out = tmp_path / "live.jsonl"
    code, _ = _run(out, small, _Scripted())
    assert code == live.EXIT_OK
    assert _run_json(out)["runs"][-1]["trace"]["surface"] is None


def test_trace_flush_distinguishes_unconfigured_failure_and_warnings() -> None:
    class _Warns:
        def record(self, fields: dict[str, object]) -> None: ...

        def flush(self) -> None:
            logging.getLogger("whymath.l3.trace").warning("Langfuse 전송 실패(ConnectError)")

    class _Raises(_Warns):
        def flush(self) -> None:
            raise RuntimeError("flush down")

    class _Quiet(_Warns):
        def flush(self) -> None:
            return None

    assert live._flush_trace(_Quiet(), False) == "skipped_not_configured"
    assert live._flush_trace(_Quiet(), True) == "ok"
    assert live._flush_trace(_Warns(), True) == "warned:1"
    assert live._flush_trace(_Raises(), True) == "error:RuntimeError"
    assert live._flush_trace(RecordingTraceSink(), None) == "not_supported"


def test_run_json_write_retries_and_midway_failure_does_not_stop_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    monkeypatch.setattr(live, "_WRITE_RETRY_DELAYS", (0.0, 0.0, 0.0))
    real = live.os.replace
    attempts = {"n": 0}

    def _flaky(src: Any, dst: Any) -> None:
        attempts["n"] += 1
        if attempts["n"] <= 4:  # 첫 쓰기의 4회 시도가 전부 실패 → 중간 쓰기 실패 1건
            raise PermissionError("locked by another process")
        if attempts["n"] in (5, 6):  # 둘째 쓰기는 2회 실패 후 재시도로 성공
            raise PermissionError("locked")
        real(src, dst)

    monkeypatch.setattr(live.os, "replace", _flaky)
    code, _ = _run(out, small, _Scripted())
    assert code == live.EXIT_OK
    assert sorted(load_responses(out)) == sorted(_ids(small))
    assert _run_json(out)["runs"][-1]["counts"]["run_json_write_errors"] == 1


def test_final_run_json_write_failure_is_measurement_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    monkeypatch.setattr(live, "_WRITE_RETRY_DELAYS", (0.0,))

    def _always(src: Any, dst: Any) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(live.os, "replace", _always)
    code, _ = _run(out, small, _Scripted())
    assert code == live.EXIT_MEASUREMENT
    assert sorted(load_responses(out)) == sorted(_ids(small))  # 1차 증거(응답)는 남는다


def test_utterance_never_reaches_stdout_stderr_logs_or_side_files(
    tmp_path: Path, capfd: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    small = _small_eval(tmp_path / "eval.jsonl")
    out = tmp_path / "live.jsonl"
    caplog.set_level(logging.DEBUG)
    # 첫 사례(힌트 · LLM 발화 노출)는 성공, 마지막 사례는 provider 실패 → 실패 파일도 생긴다.
    provider = _Scripted(fail_calls=frozenset(range(3, 100)), exc_factory=_http_503)
    code, printed = _run(out, small, provider)
    assert code == live.EXIT_INCOMPLETE_FAILED
    captured = capfd.readouterr()
    assert _MARKER in out.read_text(encoding="utf-8")
    failures_path, run_path = live.output_paths(out)
    for text in (
        printed,
        captured.out,
        captured.err,
        caplog.text,
        run_path.read_text(encoding="utf-8"),
        failures_path.read_text(encoding="utf-8"),
    ):
        assert _MARKER not in text


# ──────────────────────────────────────────────────────────────────────────
# 래퍼·원인 추출·로그 캡처 단위
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
    assert kwargs == {"temperature": 0.3}
    assert served_cloud_seat(wrapper) == "openrouter"
    bare = live.RecordingProvider(_NoSeat(), scope)  # type: ignore[arg-type]
    assert served_cloud_seat(bare) == served_cloud_seat(_NoSeat())
    assert scope.ledger.faults == []
    assert scope.ledger.prompt_fingerprints == [live._fingerprint("s", "p")]


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


def test_log_capture_collects_and_restores_even_when_the_turn_raises() -> None:
    before = record_logger.level
    harness = logging.getLogger("whymath.harness")
    before_handlers = list(harness.handlers)
    ledger = live.CaseLedger()
    with pytest.raises(RuntimeError, match="turn exploded"):
        with live._capture_logs(ledger):
            record_logger.info(json.dumps({"primary": True, "primary_outcome": "adopted"}))
            record_logger.info("JSON 아님")
            logging.getLogger("whymath.harness.wh1_primary").warning(
                "실패(%s)", "ValueError", exc_info=ValueError("bad")
            )
            raise RuntimeError("turn exploded")
    assert ledger.observations == [{"primary": True, "primary_outcome": "adopted"}]
    [warning] = ledger.warnings
    assert warning["arg_types"] == ["ValueError"]
    exception = warning["exception"]
    assert isinstance(exception, dict) and exception["exc_type"] == "ValueError"
    assert record_logger.level == before
    assert harness.handlers == before_handlers
    assert not any(isinstance(h, live._ObservationHandler) for h in record_logger.handlers)


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
