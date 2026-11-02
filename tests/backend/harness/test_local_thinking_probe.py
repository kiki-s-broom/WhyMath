"""EOS-203 — 사고 모드 지시(라우터 판정·생성기·저작 CLI)와 켬/끔 실측 탐침(`harness.local_thinking_probe`).

라이브 LLM 없이(가짜 provider) 계약을 고정한다: 모드를 번갈아(순서 회전) 돌리는가, 시도마다 즉시 쓰는가,
이번 실행 것만 세는가, 실패·게이트 거부의 원인이 행에 남는가, 지시어가 안 붙는 결정·짧은 타임아웃이면
측정을 거부하는가. 수치(수락률)는 사람 PC 실측이 낸다.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import local_thinking_probe as probe
from whymath_backend.harness import problem_corpus_accumulate as pca
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.llm_generator import LLMEquivalentProblemGenerator
from whymath_backend.l3.models import (
    CostTier,
    GenerationResult,
    LocalModelTier,
    ModelFamily,
    RoutingDecision,
    Usage,
)
from whymath_backend.l3.router import thinking_soft_switch
from whymath_backend.schema.provenance import GenerationLog

_QUAD = json.dumps(
    {
        "question_text": "이차방정식 x^2 - 5x + 6 = 0 의 두 근 중 큰 근을 구하시오.",
        "answer": "3",
        "answer_explanation": "인수분해하면 (x-2)(x-3)=0, 큰 근은 3.",
        "conditions": "x**2 - 5*x + 6 = 0",
        "answer_map": {"x": "3"},
        "answer_selection": "largest",
        "answer_format": "자연수",
        "achievement_standard_codes": ["[10공수1-02-02]"],
    },
    ensure_ascii=False,
)


class _Provider:
    """스크립트 응답 대역 — 받은 프롬프트를 남긴다. `fail`이면 provider 예외(타임아웃 흉내)."""

    def __init__(self, text: str = _QUAD, tokens: int = 400, fail: bool = False) -> None:
        self.prompts: list[str] = []
        self._text, self._tokens, self._fail = text, tokens, fail

    async def generate(
        self, prompt: str, system: str, decision: RoutingDecision, **_: Any
    ) -> GenerationResult:
        self.prompts.append(prompt)
        if self._fail:
            raise TimeoutError("ReadTimeout 흉내")
        return GenerationResult(
            text=self._text, usage=Usage(output_tokens=self._tokens, latency_ms=1200.0)
        )


def _decision(local_model: LocalModelTier, family: ModelFamily | None) -> RoutingDecision:
    return RoutingDecision(
        cost_tier=CostTier.LOCAL,
        local_family=family,
        local_model=local_model,
        mode="async" if local_model is LocalModelTier.QUALITY else "sync",  # 불변식 3
        reason="test",
        est_latency_ms=1,
        est_cost_krw=0.0,
    )


def _spec() -> EquivalenceSpec:
    return EquivalenceSpec(
        achievement_standard_codes=frozenset({"[10공수1-02-02]"}),
        target_misconception_ids=frozenset(),
        difficulty_overall=2.5,
        answer_format=None,
    )


def _plan_file(tmp_path: Path, n: int = 1) -> Path:
    path = tmp_path / "plan.jsonl"
    rows = [
        {"spec_id": f"s{i}", "standard_code": "[10공수1-02-02]", "difficulty": 2.5,
         "topic_hint": "이차방정식 — 큰 근"}
        for i in range(n)
    ]  # fmt: skip
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    return path


def _plan(n: int = 1) -> list[probe.PlanEntry]:
    return [(f"s{i}", _spec(), "이차방정식 — 큰 근") for i in range(n)]


Factory = Callable[[EquivalenceSpec, str, bool | None, Callable[[GenerationLog], None]], object]


def _factory(
    provider_for: Callable[[bool | None], _Provider], *, routing_sync: bool = False
) -> Factory:
    def build(
        spec: EquivalenceSpec,
        topic: str,
        thinking: bool | None,
        sink: Callable[[GenerationLog], None],
    ) -> object:
        return LLMEquivalentProblemGenerator(
            provider_for(thinking),  # type: ignore[arg-type]
            topic_hint=topic,
            routing_sync=routing_sync,
            generation_log_sink=sink,
            thinking=thinking,
        )

    return build


def _ok(_: bool | None) -> _Provider:
    return _Provider()


class TestRouterSwitch:
    def test_quality_local_qwen3_gets_switch(self) -> None:
        decision = _decision(LocalModelTier.QUALITY, None)
        assert thinking_soft_switch(decision, enabled=False) == "/no_think"
        assert thinking_soft_switch(decision, enabled=True) == "/think"

    def test_non_hybrid_local_model_gets_none(self) -> None:
        mid = _decision(LocalModelTier.MID, ModelFamily.GENERAL)
        assert thinking_soft_switch(mid, enabled=False) is None

    def test_cloud_decision_gets_none(self) -> None:
        cloud = RoutingDecision(
            cost_tier=CostTier.CLOUD_MID,
            mode="sync",
            reason="t",
            est_latency_ms=1,
            est_cost_krw=1.0,
        )
        assert thinking_soft_switch(cloud, enabled=False) is None


class TestGeneratorThinking:
    def test_default_none_keeps_prompt_and_snapshot_unchanged(self) -> None:
        """기본값(None)은 프롬프트도 스냅샷 키도 종전과 같다(스냅샷 해시 보존)."""
        provider, logs = _Provider(), []  # type: ignore[var-annotated]
        gen = LLMEquivalentProblemGenerator(  # type: ignore[arg-type]
            provider, routing_sync=False, generation_log_sink=logs.append
        )
        assert gen.generate(_spec()) is not None
        assert not provider.prompts[0].rstrip().endswith(("/no_think", "/think"))
        snapshot = logs[0].input_snapshot
        assert isinstance(snapshot, Mapping) and "thinking" not in snapshot

    def test_off_appends_no_think_and_records_it(self) -> None:
        provider, logs = _Provider(), []  # type: ignore[var-annotated]
        gen = LLMEquivalentProblemGenerator(  # type: ignore[arg-type]
            provider, routing_sync=False, thinking=False, generation_log_sink=logs.append
        )
        gen.generate(_spec())
        assert provider.prompts[0].endswith("\n/no_think")
        snapshot = logs[0].input_snapshot
        assert isinstance(snapshot, Mapping) and snapshot["thinking"] is False

    def test_off_is_a_no_op_for_non_hybrid_route(self) -> None:
        """동기 저작(qwen2.5 MID)에는 지시어가 붙지 않는다 — 비대상 모델 발문 오염 금지."""
        provider = _Provider()
        gen = LLMEquivalentProblemGenerator(  # type: ignore[arg-type]
            provider, routing_sync=True, thinking=False
        )
        gen.generate(_spec())
        assert "/no_think" not in provider.prompts[0]


class TestAuthoringCli:
    @pytest.mark.parametrize(
        ("flag", "expected"), [("default", None), ("off", False), ("on", True)]
    )
    def test_flag_reaches_generator(
        self, flag: str, expected: bool | None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """저작 CLI `--thinking`이 생성기 `thinking`까지 내려간다(실제 저작 경로에서 켤 수 있다)."""
        assert pca.THINKING_CHOICES[flag] is expected
        gen = pca._build_live_generator(
            "이차방정식", authoring_tier="quality", thinking=pca.THINKING_CHOICES[flag]
        )
        assert gen._thinking is expected  # type: ignore[attr-defined]


class TestProbe:
    def test_modes_alternate_with_rotation_and_rows_flush(self) -> None:
        providers: dict[bool | None, _Provider] = {}

        def provider_for(thinking: bool | None) -> _Provider:
            return providers.setdefault(thinking, _Provider())

        out = io.StringIO()
        rows = probe.run_probe(
            _plan(1), modes=["default", "off"], per_spec=4, factory=_factory(provider_for),
            out=out, run_id="r1",
        )  # fmt: skip
        assert [r["mode"] for r in rows] == ["default", "off", "off", "default"] * 2
        assert len(out.getvalue().splitlines()) == 8  # 시도마다 한 줄(규칙 ①)
        assert all(p.endswith("/no_think") for p in providers[False].prompts)
        assert not any(p.endswith("/no_think") for p in providers[None].prompts)

    def test_repeat_within_mode_is_a_round_duplicate(self) -> None:
        """같은 모드가 같은 구조를 또 내면 실제 회차처럼 `rejected_duplicate`다."""
        rows = probe.run_probe(
            _plan(1), modes=["default", "off"], per_spec=2, factory=_factory(_ok),
            out=io.StringIO(), run_id="r",
        )  # fmt: skip
        by_mode = {(r["mode"], r["attempt"]): r["status"] for r in rows}
        assert by_mode[("default", 0)] == "accepted"
        assert by_mode[("default", 1)] == "rejected_duplicate"
        assert rows[-1]["reasons"]  # 사유가 행에 남는다(규칙 ②)

    def test_failed_attempts_keep_cause_and_count_in_wall_time(self) -> None:
        """타임아웃 시도도 지연 통계에 들어가고 원인이 남는다(살아남은 시도만으로 빨라 보이지 않게)."""
        ticks = iter(range(0, 1000, 5))
        rows = probe.run_probe(
            _plan(1), modes=["default", "off"], per_spec=1,
            factory=_factory(lambda thinking: _Provider(fail=thinking is None)),
            out=io.StringIO(), run_id="r", clock=lambda: float(next(ticks)),
        )  # fmt: skip
        failed = next(r for r in rows if r["mode"] == "default")
        assert failed["status"] == "generation_failed"
        assert failed["failure_kind"] == "TimeoutError"
        assert failed["output_tokens"] is None and failed["wall_s"] == 5.0
        summary = probe.summarize(rows, "r")
        modes = summary["modes"]
        assert isinstance(modes, dict)
        assert modes["default"]["median_wall_s"] == 5.0
        assert modes["default"]["token_samples"] == 0

    def test_summary_counts_only_this_run_and_reports_token_ratio(self) -> None:
        rows: list[dict[str, object]] = [
            {"run_id": "old", "mode": "off", "status": "accepted", "failure_kind": None},
            {"run_id": "r", "mode": "off", "status": "accepted", "output_tokens": 300,
             "wall_s": 10.0, "failure_kind": None},
            {"run_id": "r", "mode": "off", "status": "generation_failed", "output_tokens": 500,
             "wall_s": 20.0, "failure_kind": "TautologicalConditionError"},
            {"run_id": "r", "mode": "default", "status": "accepted", "output_tokens": 4000,
             "wall_s": 90.0, "failure_kind": None},
        ]  # fmt: skip
        summary = probe.summarize(rows, "r")
        modes = summary["modes"]
        assert isinstance(modes, dict)
        assert modes["off"]["attempts"] == 2  # 'old' 실행 행은 세지 않는다(규칙 ③)
        assert modes["off"]["acceptance_rate"] == 0.5
        assert modes["off"]["failure_kinds"] == {"TautologicalConditionError": 1}
        assert summary["off_to_default_token_ratio"] == 0.1  # 400 / 4000

    def test_failure_kind_parsing(self) -> None:
        assert probe._failure_kind("후보 조립 실패: ValidationError(errors=2)") == "ValidationError"
        assert probe._failure_kind("provider.generate failed: ReadTimeout") == "ReadTimeout"
        assert probe._failure_kind("응답 JSON 파싱 실패") == "응답 JSON 파싱 실패"
        assert probe._failure_kind(None) is None


class TestMain:
    def _args(self, tmp_path: Path, *extra: str) -> list[str]:
        return [
            "--plan", str(_plan_file(tmp_path)), "--per-spec", "1",
            "--out", str(tmp_path / "rows.jsonl"), "--summary", str(tmp_path / "summary.json"),
            *extra,
        ]  # fmt: skip

    def test_writes_rows_and_summary(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = probe.main(self._args(tmp_path), factory=_factory(_ok), timeout_s=lambda: 180.0)
        text = capsys.readouterr().out
        assert code == 0, text
        assert "switch=/no_think" in text and "PROBE_DONE=True ROWS=2" in text
        assert set(json.loads((tmp_path / "summary.json").read_text("utf-8"))["modes"]) == {
            "default",
            "off",
        }

    def test_refuses_when_switch_would_not_apply(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """변별력 — 지시어가 안 붙는 결정(qwen2.5)이면 두 모드가 같은 호출이라 거부한다."""
        code = probe.main(
            self._args(tmp_path), factory=_factory(_ok, routing_sync=True), timeout_s=lambda: 180.0
        )
        assert code == 2 and "PROBE_REFUSED=True" in capsys.readouterr().out
        assert not (tmp_path / "rows.jsonl").exists()

    def test_refuses_short_timeout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """30초면 사고 모드 쪽이 타임아웃으로만 실패해 끔이 유리하게 나온다 — 측정을 거부한다."""
        code = probe.main(self._args(tmp_path), factory=_factory(_ok), timeout_s=lambda: 30.0)
        assert code == 2 and "ollama_request_timeout_s=30.0" in capsys.readouterr().out

    @pytest.mark.parametrize("modes", ["off", "default,bogus", "off,off"])
    def test_refuses_bad_modes(
        self, tmp_path: Path, modes: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = probe.main(
            self._args(tmp_path, "--modes", modes), factory=_factory(_ok), timeout_s=lambda: 180.0
        )
        assert code == 2 and "PROBE_REFUSED=True" in capsys.readouterr().out

    def test_refuses_empty_plan(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        empty = tmp_path / "empty.jsonl"
        empty.write_text("\n", encoding="utf-8")
        args = [
            "--plan",
            str(empty),
            "--out",
            str(tmp_path / "o"),
            "--summary",
            str(tmp_path / "s"),
        ]
        assert probe.main(args, factory=_factory(_ok), timeout_s=lambda: 180.0) == 2
        assert "PROBE_REFUSED=True" in capsys.readouterr().out
