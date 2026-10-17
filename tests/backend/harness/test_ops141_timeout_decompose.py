"""OPS-141 — WH-1 primary 시간 초과 소요 분해 측정 도구(`scripts/ops/wh1_primary_timeout_decompose.py`)의 동결.

이 도구는 Phaiakes9에서 Kiki가 돌리는 측정기라 라이브 값을 CI가 볼 수 없다. 그래서 여기서 고정하는 것은
**"도구가 귀속을 맞게 하는가"** 이다 — 정상 입력에서 초록인 테스트는 보호의 증거가 아니므로(CLAUDE.md
「보호 장치를 실패 주입 없이 선언 금지」) 실패를 실제로 주입해 **귀속이 갈리는지**를 본다:

- 캐시를 느리게 만들면 → 캐시 구간으로 귀속, 프로바이더를 느리게 만들면 → 프로바이더 구간으로 귀속
  (쌍으로 본다. 한쪽만 보면 "항상 캐시"를 내는 고장난 도구도 통과한다)
- 캐시 대기 중에 예산이 끊기면 → 취소 시점의 진행 중 구간이 `cache_get`으로 남는다
- 래퍼가 걸리지 않았으면(구간 0개인데 LLM 호출>0) → 계측 대조가 `MISMATCH`로 드러난다
- 선언한 조건(redis-up)이 실제(Redis 없음)와 다르면 → 측정하지 않고 거부하며 기록 파일도 남기지 않는다
- 집계는 지정한 run_id 분만 읽는다(다른 실행분이 섞이지 않는다), 0건이면 실패다
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from whymath_backend.l3.models import GenerationResult, RoutingDecision

_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "ops" / "wh1_primary_timeout_decompose.py"
)
_END_TURN = '{"kind": "end_turn", "action_type": "질문", "utterance": "방금 왜 그렇게 전개했는지 말해줄래?"}'


def _load() -> ModuleType:
    name = "wh1_primary_timeout_decompose_under_test"
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclass가 문자열 주석을 풀 때 모듈을 찾는다
    spec.loader.exec_module(module)
    return module


tool = _load()


# ──────────────────────────────────────────────────────────────────────────
# 대역
# ──────────────────────────────────────────────────────────────────────────
class _Provider:
    """지정한 시간만큼 걸린 뒤 end_turn을 돌려주는 프로바이더 대역."""

    def __init__(self, delay_s: float = 0.0) -> None:
        self._delay_s = delay_s

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
    ) -> GenerationResult:
        await asyncio.sleep(self._delay_s)
        return GenerationResult(_END_TURN)


class _Cache:
    """연산마다 지정한 시간이 걸리는 캐시 대역. `degrade=True`면 RedisCache처럼 강등을 센다."""

    def __init__(self, delay_s: float = 0.0, *, degrade: bool = False) -> None:
        self._delay_s = delay_s
        self._degrade = degrade
        self._store: dict[str, str] = {}
        self.keys_seen: list[str] = []
        self.degradation_count = 0

    async def get(self, key: str) -> str | None:
        self.keys_seen.append(key)
        await asyncio.sleep(self._delay_s)
        if self._degrade:
            self.degradation_count += 1
            return None
        return self._store.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self.keys_seen.append(key)
        await asyncio.sleep(self._delay_s)
        if self._degrade:
            self.degradation_count += 1
            return
        self._store[key] = value


SIMPLE_TURN = next(s for s in tool.SCENARIOS if s[0] == "simple_turn")


def _turn(provider: Any, inner_cache: Any, *, timeout_s: float = 5.0) -> dict[str, Any]:
    """도구의 `_run_turn`을 실제 `run_wh1_primary_turn`에 태워 한 턴을 기록한다."""
    recorder = tool.SpanRecorder()
    cache = tool.TimedCache(inner_cache, recorder)
    timed = tool.TimedProvider(provider, recorder)

    async def go() -> dict[str, Any]:
        with tool.capture_observations() as capture:
            return await tool._run_turn(  # noqa: SLF001 — 도구의 내부 단위를 직접 겨냥한다.
                provider=timed,
                cache=cache,
                recorder=recorder,
                capture=capture,
                scenario=SIMPLE_TURN,
                run_id="t",
                seq=1,
                rep=1,
                cold=False,
                timeout_s=timeout_s,
            )

    return asyncio.run(go())


def _decomp(turn: dict[str, Any]) -> Any:
    spans = [
        tool.Span(
            kind=s["kind"],
            start_ms=s["start_ms"],
            end_ms=s["end_ms"],
            outcome=s["outcome"],
            degraded=s["degraded"],
            hit=s["hit"],
            model=s["model"],
        )
        for s in turn["spans"]
    ]
    return tool.decompose_turn(spans, turn["elapsed_ms"])


# ──────────────────────────────────────────────────────────────────────────
# 귀속 — 실패 주입 쌍 (실제 run_wh1_primary_turn 경로)
# ──────────────────────────────────────────────────────────────────────────
class TestAttributionUnderInjectedFaults:
    def test_slow_cache_is_attributed_to_cache_not_provider(self) -> None:
        turn = _turn(_Provider(0.0), _Cache(0.2))
        d = _decomp(turn)
        assert turn["returned_utterance"] is True
        assert turn["instrument_check"] == "OK", turn["instrument_check"]
        # 호출 1회 = 캐시 get 1 + set 1. 연산마다 0.2초이므로 캐시 합은 0.4초 근방이어야 한다.
        assert d.cache_ops == 2 and d.provider_calls == 1
        assert d.cache_ms >= 380.0
        assert d.provider_ms < 100.0
        assert d.dominant == "cache_wait"

    def test_slow_provider_is_attributed_to_provider_not_cache(self) -> None:
        turn = _turn(_Provider(0.3), _Cache(0.0))
        d = _decomp(turn)
        assert turn["instrument_check"] == "OK", turn["instrument_check"]
        assert d.provider_ms >= 280.0
        assert d.cache_ms < 100.0
        assert d.dominant == "provider"

    def test_budget_cut_during_cache_wait_leaves_cache_get_in_flight(self) -> None:
        started = time.monotonic()
        turn = _turn(_Provider(0.0), _Cache(5.0), timeout_s=0.3)
        wall = time.monotonic() - started
        d = _decomp(turn)
        assert wall < 3.0, f"예산(0.3초)이 끊지 못했다: {wall:.1f}초"
        assert turn["returned_utterance"] is False
        assert turn["ops134"]["primary_outcome"] == "fallback_timeout"
        assert d.inflight_at_cancel == "cache_get"
        assert d.dominant == "cache_wait"
        # 취소로 닫힌 구간이 기록에 남아 있다(열린 채 사라지지 않는다).
        assert all(s["end_ms"] is not None for s in turn["spans"])

    def test_degraded_cache_ops_are_counted_separately_from_healthy_waits(self) -> None:
        turn = _turn(_Provider(0.0), _Cache(0.1, degrade=True))
        d = _decomp(turn)
        assert d.cache_ops == 2
        assert d.cache_degraded_ms >= 180.0
        assert d.cache_degraded_ms == pytest.approx(d.cache_ms)
        healthy = _decomp(_turn(_Provider(0.0), _Cache(0.1, degrade=False)))
        assert healthy.cache_degraded_ms == 0.0

    def test_cache_keys_carry_the_per_turn_salt(self) -> None:
        inner = _Cache(0.0)
        _turn(_Provider(0.0), inner)
        assert inner.keys_seen, "캐시 연산이 하나도 관측되지 않았다"
        assert all(k.startswith("ops141:t:1:") for k in inner.keys_seen), inner.keys_seen

    def test_provider_failure_is_counted_and_not_mistaken_for_an_llm_turn(self) -> None:
        # 정책은 프로바이더 예외를 안전 강등으로 삼켜 턴을 정상 종료시킨다 — 스모크에서 실측한 위장.
        class _Boom:
            async def generate(
                self, prompt: str, system: str, decision: RoutingDecision, **kwargs: Any
            ) -> GenerationResult:
                raise ConnectionError("Ollama 없음(테스트)")

        turn = _turn(_Boom(), _Cache(0.0))
        assert turn["provider_errors"] >= 1
        assert turn["ops134"]["primary_outcome"] == "fallback_llm_degraded"
        assert any(s["outcome"] == "ConnectionError" for s in turn["spans"])

    def test_healthy_provider_reports_zero_provider_errors(self) -> None:
        assert _turn(_Provider(0.0), _Cache(0.0))["provider_errors"] == 0

    def test_budget_cancel_is_not_counted_as_a_provider_failure(self) -> None:
        turn = _turn(_Provider(5.0), _Cache(0.0), timeout_s=0.3)
        assert turn["returned_utterance"] is False
        assert turn["provider_errors"] == 0
        assert _decomp(turn).inflight_at_cancel == "provider"

    def test_instrument_check_matches_ops134_record_call_count(self) -> None:
        turn = _turn(_Provider(0.0), _Cache(0.0))
        assert turn["ops134"]["llm_calls"] == 1
        assert sum(1 for s in turn["spans"] if s["kind"] == "cache_get") == 1


# ──────────────────────────────────────────────────────────────────────────
# 순수 함수
# ──────────────────────────────────────────────────────────────────────────
def _span(
    kind: str, start: float, end: float, *, outcome: str = "ok", degraded: bool = False
) -> Any:
    return tool.Span(kind=kind, start_ms=start, end_ms=end, outcome=outcome, degraded=degraded)


class TestDecomposeTurn:
    def test_components_sum_and_other_is_the_remainder(self) -> None:
        spans = [
            _span("cache_get", 0, 100),
            _span("provider", 100, 400),
            _span("cache_set", 400, 450),
        ]
        d = tool.decompose_turn(spans, 1000.0)
        assert (d.cache_ms, d.provider_ms, d.other_ms) == (150.0, 300.0, 550.0)
        assert d.dominant == "non_llm"

    def test_no_component_reaching_half_means_no_dominant_cause(self) -> None:
        spans = [_span("cache_get", 0, 300), _span("provider", 300, 600)]
        assert tool.decompose_turn(spans, 1000.0).dominant == "none"

    def test_other_never_goes_negative(self) -> None:
        d = tool.decompose_turn([_span("provider", 0, 900)], 500.0)
        assert d.other_ms == 0.0

    def test_zero_elapsed_is_safe(self) -> None:
        assert tool.decompose_turn([], 0.0).dominant == "none"

    def test_inflight_is_the_cancelled_span_kind(self) -> None:
        spans = [_span("provider", 0, 200), _span("cache_set", 200, 900, outcome="CancelledError")]
        assert tool.decompose_turn(spans, 900.0).inflight_at_cancel == "cache_set"
        assert tool.decompose_turn(spans[:1], 900.0).inflight_at_cancel is None


class TestCheckInstrument:
    def test_matching_counts_are_ok(self) -> None:
        spans = [_span("cache_get", 0, 1), _span("cache_get", 2, 3)]
        assert tool.check_instrument(spans, {"llm_calls": 2}) == "OK"

    def test_unhooked_wrapper_is_a_mismatch_not_a_silent_ok(self) -> None:
        # 래퍼가 걸리지 않으면 구간 0개인데 LLM은 호출됐다 — 이 대조가 그 고장을 드러낸다.
        assert tool.check_instrument([], {"llm_calls": 3}).startswith("MISMATCH")

    def test_missing_record_cannot_be_compared(self) -> None:
        assert tool.check_instrument([], None) == "NO_RECORD"
        assert tool.check_instrument([], {"llm_calls": None}) == "NO_RECORD"


class TestBudgetExceedTable:
    def _turns(self, elapsed_s: Sequence[float]) -> list[dict[str, Any]]:
        return [{"elapsed_ms": e * 1000.0} for e in elapsed_s]

    def test_budgets_above_the_run_timeout_are_censored_not_zero(self) -> None:
        rows = {
            r["budget_s"]: r for r in tool.budget_exceed_table(self._turns([5, 14, 15.2]), 15.0)
        }
        assert rows[10.0]["exceed_rate"] == pytest.approx(2 / 3)
        assert rows[15.0]["exceed_rate"] == pytest.approx(1 / 3)
        # 15초에서 잘린 표본으로 20초 초과율을 말하면 낮게 위장된다 → None.
        assert rows[20.0]["exceed_rate"] is None and rows[60.0]["exceed_rate"] is None

    def test_unconstrained_run_answers_every_budget(self) -> None:
        rows = tool.budget_exceed_table(self._turns([8, 12, 18, 40]), 120.0)
        # 소요 [8, 12, 18, 40]초 — 예산 10/15/20/30/60초를 넘는 턴은 각각 3·2·1·1·0개(엄격히 초과).
        assert [r["exceed_rate"] for r in rows] == [0.75, 0.5, 0.25, 0.25, 0.0]

    def test_empty_sample_is_unknown_not_zero_percent(self) -> None:
        assert all(r["exceed_rate"] is None for r in tool.budget_exceed_table([], 120.0))


class TestColdOverhead:
    @staticmethod
    def _turn_with_provider(dur_ms: float, *, cold: bool) -> dict[str, Any]:
        return {
            "cold": cold,
            "spans": [{"kind": "provider", "start_ms": 0.0, "end_ms": dur_ms, "outcome": "ok"}],
        }

    def test_overhead_is_cold_first_call_minus_warm_median(self) -> None:
        turns = [
            self._turn_with_provider(9000.0, cold=True),
            self._turn_with_provider(1000.0, cold=False),
            self._turn_with_provider(1200.0, cold=False),
        ]
        est = tool.cold_overhead_estimate(turns)
        assert est["overhead_ms"] == pytest.approx(9000.0 - 1100.0)

    def test_without_a_warm_baseline_it_does_not_invent_zero(self) -> None:
        est = tool.cold_overhead_estimate([self._turn_with_provider(9000.0, cold=True)])
        assert est["overhead_ms"] is None

    def test_without_a_cold_turn_it_does_not_invent_overhead(self) -> None:
        est = tool.cold_overhead_estimate([self._turn_with_provider(1000.0, cold=False)] * 3)
        assert est["overhead_ms"] is None


class TestConditionGate:
    @staticmethod
    def _probe(ops: int, degraded: int) -> dict[str, Any]:
        return {"ops": ops, "degraded": degraded}

    def test_declared_condition_must_match_the_probe(self) -> None:
        assert tool._condition_matches("redis-down", self._probe(6, 6)) is None
        assert tool._condition_matches("redis-up", self._probe(6, 0)) is None
        assert "응답하지 않는다" in tool._condition_matches("redis-up", self._probe(6, 6))
        assert "응답한다" in tool._condition_matches("redis-down", self._probe(6, 0))

    def test_flapping_redis_fits_neither_condition(self) -> None:
        for cond in ("redis-down", "redis-up"):
            assert "불안정" in tool._condition_matches(cond, self._probe(6, 2))

    def test_zero_probe_ops_cannot_confirm_a_condition(self) -> None:
        assert tool._condition_matches("redis-down", self._probe(0, 0)) is not None

    def test_memory_condition_needs_no_probe(self) -> None:
        assert tool._condition_matches("memory", None) is None


# ──────────────────────────────────────────────────────────────────────────
# 기록·집계
# ──────────────────────────────────────────────────────────────────────────
def _turn_record(run_id: str, seq: int, elapsed_ms: float, **extra: Any) -> dict[str, Any]:
    return {
        "kind": "turn",
        "run_id": run_id,
        "seq": seq,
        "elapsed_ms": elapsed_ms,
        "returned_utterance": True,
        "cold": False,
        "spans": [
            {"kind": "provider", "start_ms": 0.0, "end_ms": elapsed_ms, "outcome": "ok"},
        ],
        "instrument_check": "OK",
        **extra,
    }


def _header(run_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "kind": "header",
        "run_id": run_id,
        "condition": "memory",
        "timeout_seconds": 15.0,
        "ollama_ps_before": [],
        "cold_verified": None,
        "code_head": "abc1234",
        **extra,
    }


def _write(path: Path, records: Sequence[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", "utf-8")


class TestJsonlWriter:
    def test_each_line_is_on_disk_before_close(self, tmp_path: Path) -> None:
        path = tmp_path / "x" / "decompose.jsonl"
        writer = tool.JsonlWriter(path)
        assert (
            not path.exists()
        ), "쓰기 전에는 파일을 만들지 않는다(거부된 실행이 빈 파일을 남기면 안 된다)"
        writer.write({"kind": "turn", "n": 1})
        # 닫지 않았는데도 읽힌다 — 중간에 멈춰도 증거가 남는다.
        assert json.loads(path.read_text("utf-8").splitlines()[0]) == {"kind": "turn", "n": 1}
        writer.close()


class TestLoadRun:
    def test_only_the_requested_run_is_read(self, tmp_path: Path) -> None:
        path = tmp_path / "decompose.jsonl"
        _write(
            path,
            [
                _header("A"),
                _turn_record("A", 1, 1000.0),
                _header("B"),
                _turn_record("B", 1, 9000.0),
                _turn_record("B", 2, 9000.0),
                {"kind": "footer", "run_id": "A"},
            ],
        )
        a = tool.load_run(path, "A")
        assert len(a.turns) == 1 and a.interrupted is False
        b = tool.load_run(path, "B")
        assert len(b.turns) == 2 and b.interrupted is True  # B는 footer가 없다 = 중단

    def test_zero_matching_turns_is_a_failure_not_an_empty_pass(self, tmp_path: Path) -> None:
        path = tmp_path / "decompose.jsonl"
        _write(path, [_header("A"), _turn_record("A", 1, 1000.0)])
        with pytest.raises(ValueError, match="측정 0건"):
            tool.load_run(path, "NOPE")

    def test_corrupt_line_is_reported_not_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "decompose.jsonl"
        path.write_text('{"kind": "header", "run_id": "A"}\n{깨진 줄\n', "utf-8")
        with pytest.raises(ValueError, match="JSON 해석 실패"):
            tool.load_run(path, "A")


class TestCli:
    def test_summarize_prints_only_the_requested_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(
            tmp_path / "decompose.jsonl",
            [
                _header("A"),
                _turn_record("A", 1, 1000.0),
                {"kind": "footer", "run_id": "A"},
                _header("B"),
                _turn_record("B", 1, 9000.0),
                {"kind": "footer", "run_id": "B"},
            ],
        )
        rc = tool.main(["summarize", "--out", str(tmp_path), "--run-id", "A"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "실행 A" in out and "실행 B" not in out
        assert "9,000ms" not in out  # B의 수치가 A에 섞이지 않는다

    def test_summarize_unknown_run_exits_nonzero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path / "decompose.jsonl", [_header("A"), _turn_record("A", 1, 1000.0)])
        assert tool.main(["summarize", "--out", str(tmp_path), "--run-id", "NOPE"]) == 1
        assert "측정 실패" in capsys.readouterr().err

    def test_declared_redis_up_with_no_redis_is_refused_and_leaves_no_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # 포트 1은 어디에서도 열려 있지 않다 — 실제 RedisCache가 실제로 강등하는 경로를 탄다.
        rc = tool.main(
            [
                "measure",
                "--condition",
                "redis-up",
                "--redis-url",
                "redis://127.0.0.1:1/0",
                "--cache-probe-ops",
                "2",
                "--out",
                str(tmp_path),
            ]
        )
        assert rc == 2
        assert "거부" in capsys.readouterr().err
        assert not (tmp_path / "decompose.jsonl").exists()

    def test_reps_below_one_is_refused(self, tmp_path: Path) -> None:
        assert (
            tool.main(["measure", "--condition", "memory", "--reps", "0", "--out", str(tmp_path)])
            == 2
        )

    def test_summary_flags_a_run_whose_llm_calls_all_failed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        dead = _turn_record(
            "D",
            1,
            50.0,
            provider_errors=2,
            ops134={"primary_outcome": "fallback_llm_degraded", "llm_calls": 2},
        )
        _write(
            tmp_path / "decompose.jsonl", [_header("D"), dead, {"kind": "footer", "run_id": "D"}]
        )
        assert tool.main(["summarize", "--out", str(tmp_path), "--run-id", "D"]) == 0
        out = capsys.readouterr().out
        assert "프로바이더 호출 실패 2건" in out
        assert "LLM 발화 미채택 1/1턴" in out and "fallback_llm_degraded" in out

    def test_summary_does_not_warn_for_a_healthy_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ok = _turn_record(
            "H",
            1,
            900.0,
            provider_errors=0,
            ops134={"primary_outcome": "adopted", "llm_calls": 1},
        )
        _write(tmp_path / "decompose.jsonl", [_header("H"), ok, {"kind": "footer", "run_id": "H"}])
        tool.main(["summarize", "--out", str(tmp_path), "--run-id", "H"])
        out = capsys.readouterr().out
        assert "프로바이더 호출 실패" not in out
        assert "LLM 발화 미채택 0/1턴" in out

    def test_unreachable_ollama_is_refused_and_leaves_no_file(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(tool, "_ollama_loaded_models", lambda host: None)
        rc = tool.main(["measure", "--condition", "memory", "--out", str(tmp_path)])
        assert rc == 2
        assert "Ollama" in capsys.readouterr().err
        assert not (tmp_path / "decompose.jsonl").exists()

    def test_all_in_file_summarizes_every_run_in_header_order(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(
            tmp_path / "decompose.jsonl",
            [
                _header("RUN-B"),
                _turn_record("RUN-B", 1, 1000.0),
                {"kind": "footer", "run_id": "RUN-B"},
                _header("RUN-A"),
                _turn_record("RUN-A", 1, 2000.0),
                {"kind": "footer", "run_id": "RUN-A"},
            ],
        )
        assert tool.main(["summarize", "--out", str(tmp_path), "--all-in-file"]) == 0
        out = capsys.readouterr().out
        assert out.index("실행 RUN-B") < out.index("실행 RUN-A")

    def test_summarize_needs_exactly_one_of_run_id_or_all_in_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path / "decompose.jsonl", [_header("A"), _turn_record("A", 1, 1000.0)])
        assert tool.main(["summarize", "--out", str(tmp_path)]) == 2
        both = ["summarize", "--out", str(tmp_path), "--all-in-file", "--run-id", "A"]
        assert tool.main(both) == 2

    def test_all_in_file_with_no_runs_is_a_failure_not_an_empty_pass(self, tmp_path: Path) -> None:
        (tmp_path / "decompose.jsonl").write_text("\n", encoding="utf-8")
        assert tool.main(["summarize", "--out", str(tmp_path), "--all-in-file"]) == 1
