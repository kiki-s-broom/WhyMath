"""EOS-203 — 사고 모드 지시(라우터 판정·생성기 부착)와 켬/끔 실측 탐침(`local_thinking_probe`).

라이브 LLM 없이(가짜 provider) 탐침의 계약을 고정한다: 모드를 번갈아 돌리는가, 시도마다 즉시 쓰는가,
이번 실행 것만 세는가, 지시어가 안 붙는 결정이면 측정을 거부하는가. 수치(수락률)는 사람 PC 실측이 낸다.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.l3.equivalent import local_thinking_probe as probe
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
    """스크립트 응답 대역 — 받은 프롬프트를 남기고 출력 토큰 수를 usage로 돌려준다."""

    def __init__(self, text: str = _QUAD, tokens: int = 400) -> None:
        self.prompts: list[str] = []
        self._text = text
        self._tokens = tokens

    async def generate(
        self, prompt: str, system: str, decision: RoutingDecision, **_: Any
    ) -> GenerationResult:
        self.prompts.append(prompt)
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


def _plan(tmp_path: Path, n: int = 1) -> Path:
    path = tmp_path / "plan.jsonl"
    rows = [
        {
            "spec_id": f"s{i}",
            "standard_code": "[10공수1-02-02]",
            "difficulty": 2.5,
            "topic_hint": "이차방정식 — 큰 근",
        }
        for i in range(n)
    ]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    return path


def _factory(
    provider: _Provider, *, routing_sync: bool = False
) -> Callable[[str, bool | None, Callable[[GenerationLog], None]], object]:
    def build(topic: str, thinking: bool | None, sink: Callable[[GenerationLog], None]) -> object:
        return LLMEquivalentProblemGenerator(
            provider,  # type: ignore[arg-type]
            topic_hint=topic,
            routing_sync=routing_sync,
            generation_log_sink=sink,
            thinking=thinking,
        )

    return build


class TestRouterSwitch:
    def test_quality_local_qwen3_gets_switch(self) -> None:
        decision = _decision(LocalModelTier.QUALITY, None)
        assert thinking_soft_switch(decision, enabled=False) == "/no_think"
        assert thinking_soft_switch(decision, enabled=True) == "/think"

    def test_non_hybrid_local_model_gets_none(self) -> None:
        """qwen2.5(GENERAL MID)는 하이브리드 사고 모델이 아니다 — 지시어를 붙이지 않는다."""
        assert (
            thinking_soft_switch(_decision(LocalModelTier.MID, ModelFamily.GENERAL), enabled=False)
            is None
        )


def test_cloud_decision_gets_none() -> None:
    cloud = RoutingDecision(
        cost_tier=CostTier.CLOUD_MID,
        mode="sync",
        reason="test",
        est_latency_ms=1,
        est_cost_krw=1.0,
    )
    assert thinking_soft_switch(cloud, enabled=False) is None


class TestGeneratorThinking:
    def test_default_none_leaves_prompt_untouched(self, tmp_path: Path) -> None:
        """기본값(None)은 종전과 바이트 단위로 같다 — 실측 전 기본값 변경 금지(acceptance ②)."""
        provider = _Provider()
        gen = LLMEquivalentProblemGenerator(provider, routing_sync=False)  # type: ignore[arg-type]
        assert gen.generate(probe.load_plan(_plan(tmp_path))[0].spec) is not None
        assert not provider.prompts[0].rstrip().endswith(("/no_think", "/think"))

    def test_off_appends_no_think_for_quality_route(self, tmp_path: Path) -> None:
        provider = _Provider()
        gen = LLMEquivalentProblemGenerator(  # type: ignore[arg-type]
            provider, routing_sync=False, thinking=False
        )
        gen.generate(probe.load_plan(_plan(tmp_path))[0].spec)
        assert provider.prompts[0].endswith("\n/no_think")

    def test_off_is_a_no_op_for_non_hybrid_route(self, tmp_path: Path) -> None:
        """동기 저작(qwen2.5 MID)에는 지시어가 붙지 않는다 — 비대상 모델 발문 오염 금지."""
        provider = _Provider()
        gen = LLMEquivalentProblemGenerator(  # type: ignore[arg-type]
            provider, routing_sync=True, thinking=False
        )
        gen.generate(probe.load_plan(_plan(tmp_path))[0].spec)
        assert "/no_think" not in provider.prompts[0]

    def test_snapshot_records_thinking(self, tmp_path: Path) -> None:
        logs: list[GenerationLog] = []
        gen = LLMEquivalentProblemGenerator(  # type: ignore[arg-type]
            _Provider(), routing_sync=False, thinking=False, generation_log_sink=logs.append
        )
        gen.generate(probe.load_plan(_plan(tmp_path))[0].spec)
        snapshot = logs[0].input_snapshot
        assert isinstance(snapshot, Mapping)
        assert snapshot["thinking"] is False
        assert str(snapshot["prompt"]).endswith("/no_think")


class TestProbe:
    def test_modes_alternate_and_rows_flush_per_attempt(self, tmp_path: Path) -> None:
        provider = _Provider()
        out = io.StringIO()
        rows = probe.run_probe(
            probe.load_plan(_plan(tmp_path, 2)),
            modes=["default", "off"],
            per_spec=2,
            factory=_factory(provider),
            out=out,
            run_id="r1",
        )
        assert [(r["spec_id"], r["mode"]) for r in rows] == [
            ("s0", "default"), ("s0", "off"), ("s0", "default"), ("s0", "off"),
            ("s1", "default"), ("s1", "off"), ("s1", "default"), ("s1", "off"),
        ]  # fmt: skip
        assert len(out.getvalue().splitlines()) == 8  # 시도마다 한 줄(규칙 ①)
        # 끔 모드 호출에만 지시어가 붙었다 — 두 모드가 실제로 다른 호출이다.
        assert sum(p.endswith("/no_think") for p in provider.prompts) == 4
        assert all(r["status"] == "accepted" and r["output_tokens"] == 400 for r in rows)

    def test_summary_counts_only_this_run_and_failure_kinds(self, tmp_path: Path) -> None:
        rows: list[dict[str, object]] = [
            {"run_id": "old", "mode": "off", "status": "accepted", "failure_kind": None},
            {"run_id": "r", "mode": "off", "status": "accepted", "output_tokens": 300,
             "latency_ms": 1000, "failure_kind": None},
            {"run_id": "r", "mode": "off", "status": "generation_failed", "output_tokens": 900,
             "latency_ms": 3000, "failure_kind": "TautologicalConditionError"},
            {"run_id": "r", "mode": "default", "status": "generation_failed",
             "output_tokens": None, "latency_ms": None, "failure_kind": "ReadTimeout"},
        ]  # fmt: skip
        summary = probe.summarize(rows, "r")
        modes = summary["modes"]
        assert isinstance(modes, dict)
        assert modes["off"]["attempts"] == 2  # 'old' 실행 행은 세지 않는다(규칙 ③)
        assert modes["off"]["accepted"] == 1 and modes["off"]["acceptance_rate"] == 0.5
        assert modes["off"]["failure_kinds"] == {"TautologicalConditionError": 1}
        assert modes["off"]["median_output_tokens"] == 600.0
        assert modes["default"]["failure_kinds"] == {"ReadTimeout": 1}

    def test_failure_kind_parsing(self) -> None:
        assert probe._failure_kind("후보 조립 실패: ValidationError(errors=2)") == "ValidationError"
        assert probe._failure_kind("provider.generate failed: ReadTimeout") == "ReadTimeout"
        assert probe._failure_kind("응답 JSON 파싱 실패") == "응답 JSON 파싱 실패"
        assert probe._failure_kind(None) is None

    def test_main_writes_rows_and_summary(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out, summary = tmp_path / "rows.jsonl", tmp_path / "summary.json"
        args = ["--plan", str(_plan(tmp_path)), "--per-spec", "1"]
        args += ["--out", str(out), "--summary", str(summary)]
        assert probe.main(args, factory=_factory(_Provider())) == 0
        text = capsys.readouterr().out
        assert "PREFLIGHT mode=off" in text and "switch=/no_think" in text
        assert "PROBE_DONE=True ROWS=2" in text
        assert set(json.loads(summary.read_text("utf-8"))["modes"]) == {"default", "off"}

    def test_main_refuses_when_switch_would_not_apply(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """변별력 — 지시어가 안 붙는 결정(qwen2.5)이면 두 모드가 같은 호출이라 측정을 거부한다."""
        out = tmp_path / "rows.jsonl"
        args = ["--plan", str(_plan(tmp_path)), "--out", str(out)]
        args += ["--summary", str(tmp_path / "s.json")]
        assert probe.main(args, factory=_factory(_Provider(), routing_sync=True)) == 2
        assert "PROBE_REFUSED=True" in capsys.readouterr().out
        assert not out.exists()

    @pytest.mark.parametrize("modes", ["off", "default,bogus"])
    def test_main_refuses_bad_modes(
        self, tmp_path: Path, modes: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args = ["--plan", str(_plan(tmp_path)), "--modes", modes, "--out", str(tmp_path / "o")]
        args += ["--summary", str(tmp_path / "s")]
        assert probe.main(args, factory=_factory(_Provider())) == 2
        assert "PROBE_REFUSED=True" in capsys.readouterr().out

    def test_empty_plan_is_refused(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.jsonl"
        empty.write_text("\n", encoding="utf-8")
        with pytest.raises(ValueError, match="스펙 0건"):
            probe.load_plan(empty)
