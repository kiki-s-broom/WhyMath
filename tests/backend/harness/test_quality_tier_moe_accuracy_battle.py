"""OPS-48 QUALITY 티어 MoE 정확도 강등전 — hermetic(fake client·라이브 LLM 0).

검증 축:
  ① 응답 파싱 — JSON 직접·코드펜스·fallback·빈 응답.
  ② 집계 — 완벽 검출기/눈먼 검출기/상시발화 검출기가 서로 다른 Wilson 경계를 낸다.
  ③ 동시성/지연/usage 기록 — fake client로 호출 규약 확인.
  ④ CLI 게이트 — 단독 임계 + "기준보다 열등하면 안 됨" exit code.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from whymath_backend.harness import quality_tier_moe_accuracy_battle as qb
from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound
from whymath_backend.l3.equivalent.defect_seeder import (
    DEFECT_CLASSES,
    build_defect_seeded_set,
)


# ──────────────────────────────────────────────────────────────────────────
# Fake Ollama client (provider에 주입)
# ──────────────────────────────────────────────────────────────────────────
class _FakeResponse:
    """ollama generate 반용 객체."""

    def __init__(
        self,
        response: str,
        prompt_eval_count: int = 100,
        eval_count: int = 30,
    ) -> None:
        self.response = response
        self.prompt_eval_count = prompt_eval_count
        self.eval_count = eval_count


class _FakeOllamaClient:
    """테스트용 Ollama client — 호출 인자 기록 + 지정된 응답 반환."""

    def __init__(self, responder: Any) -> None:
        self._responder = responder
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        return self._responder(kwargs)

    async def list(self) -> dict[str, list[dict[str, str]]]:
        return {"models": []}


# ──────────────────────────────────────────────────────────────────────────
# 응답 파싱
# ──────────────────────────────────────────────────────────────────────────
def test_parse_direct_json() -> None:
    v, ok, err = qb._parse_response('{"has_defect": true, "defect_class": "answer_error"}')
    assert ok and err == ""
    assert v.has_defect is True
    assert v.defect_class == "answer_error"


def test_parse_json_in_codefence() -> None:
    text = '분석 결과:\n```json\n{"has_defect": false, "reason": "정상"}\n```'
    v, ok, err = qb._parse_response(text)
    assert ok and err == ""
    assert v.has_defect is False


def test_parse_string_bool() -> None:
    v, ok, err = qb._parse_response('{"has_defect": "true"}')
    assert ok
    assert v.has_defect is True


def test_parse_empty_response_is_unparsed() -> None:
    v, ok, err = qb._parse_response("")
    assert not ok
    assert err == "empty response"
    assert v.has_defect is False


def test_parse_no_json_falls_back_to_heuristic() -> None:
    v, ok, err = qb._parse_response("이 문항에는 결함이 있습니다.")
    assert not ok
    assert "fallback" in err
    assert v.has_defect is True


# ──────────────────────────────────────────────────────────────────────────
# 시험지 + 집계
# ──────────────────────────────────────────────────────────────────────────
def test_seeded_set_composition() -> None:
    items = build_defect_seeded_set(n_defective=70, n_clean=70, seed=7)
    assert len(items) == 140
    assert sum(1 for i in items if i.defect_class is not None) == 70
    assert sum(1 for i in items if i.defect_class is None) == 70
    counts: dict[str, int] = {}
    for i in items:
        if i.defect_class:
            counts[i.defect_class] = counts.get(i.defect_class, 0) + 1
    assert all(counts.get(k, 0) == 10 for k in DEFECT_CLASSES)


def test_summarize_perfect_detector() -> None:
    # Wilson 상한이 의미 있게 작아지려면 무결함 표본을 70개 이상 쓴다.
    items = build_defect_seeded_set(n_defective=70, n_clean=70, seed=1)
    outcomes: list[qb.ModelOutcome] = []
    for item in items:
        truth = item.defect_class
        outcomes.append(
            qb.ModelOutcome(
                model_id="fake",
                slug=item.candidate.problem.slug or "",
                ground_truth=truth,
                detected=truth is not None,
                predicted_class=truth,
                parsed=True,
                latency_ms=100.0,
            )
        )
    report = qb._summarize("fake", outcomes)
    assert report.metrics.true_positives == 70
    assert report.metrics.false_negatives == 0
    assert report.metrics.false_positives == 0
    assert report.metrics.true_negatives == 70
    assert report.metrics.unresolved == 0
    lb = report.metrics.detection_lower_bound(0.95)
    assert lb is not None and lb > 0.95
    ub = report.metrics.false_alarm_upper_bound(0.95)
    assert ub is not None and ub < 0.05


def test_summarize_blind_ok_detector() -> None:
    items = build_defect_seeded_set(n_defective=14, n_clean=14, seed=2)
    outcomes = [
        qb.ModelOutcome(
            model_id="fake",
            slug=item.candidate.problem.slug or "",
            ground_truth=item.defect_class,
            detected=False,
            predicted_class=None,
            parsed=True,
        )
        for item in items
    ]
    report = qb._summarize("fake", outcomes)
    assert report.metrics.true_positives == 0
    assert report.metrics.false_positives == 0
    assert report.metrics.false_negatives == 14
    assert report.metrics.true_negatives == 14
    lb = report.metrics.detection_lower_bound(0.95)
    assert lb is not None and lb < 1e-9


def test_summarize_blind_defect_detector() -> None:
    items = build_defect_seeded_set(n_defective=14, n_clean=14, seed=3)
    outcomes = [
        qb.ModelOutcome(
            model_id="fake",
            slug=item.candidate.problem.slug or "",
            ground_truth=item.defect_class,
            detected=True,
            predicted_class=None,
            parsed=True,
        )
        for item in items
    ]
    report = qb._summarize("fake", outcomes)
    assert report.metrics.true_positives == 14
    assert report.metrics.false_positives == 14
    assert report.metrics.false_negatives == 0
    assert report.metrics.true_negatives == 0
    fau = report.metrics.false_alarm_upper_bound(0.95)
    assert fau is not None and fau > 0.75


def test_summarize_unresolved_is_not_counted_as_detection() -> None:
    items = build_defect_seeded_set(n_defective=7, n_clean=7, seed=4)
    outcomes = [
        qb.ModelOutcome(
            model_id="fake",
            slug=item.candidate.problem.slug or "",
            ground_truth=item.defect_class,
            detected=False,
            predicted_class=None,
            parsed=False,
            parse_error="boom",
        )
        for item in items
    ]
    report = qb._summarize("fake", outcomes)
    assert report.metrics.unresolved == 14
    assert report.metrics.defective_total == 0
    assert report.metrics.clean_total == 0
    assert report.metrics.detection_lower_bound(0.95) is None


# ──────────────────────────────────────────────────────────────────────────
# 비동기 평가 (fake client)
# ──────────────────────────────────────────────────────────────────────────
def test_evaluate_model_records_latency_and_usage() -> None:
    items = build_defect_seeded_set(n_defective=7, n_clean=7, seed=5)

    def responder(kwargs: dict[str, Any]) -> _FakeResponse:
        return _FakeResponse(
            '{"has_defect": true, "defect_class": "answer_error"}',
            prompt_eval_count=50,
            eval_count=20,
        )

    client = _FakeOllamaClient(responder)
    outcomes = asyncio.run(
        qb.evaluate_model(
            "fake-model",
            items,
            concurrency=2,
            client=client,  # type: ignore[arg-type]
        )
    )
    assert len(outcomes) == len(items)
    assert all(o.model_id == "fake-model" for o in outcomes)
    assert all(o.input_tokens == 50 for o in outcomes)
    assert all(o.output_tokens == 20 for o in outcomes)
    assert all(o.latency_ms is not None for o in outcomes)
    assert len(client.calls) == len(items)
    # options에 num_ctx/num_predict/temperature가 들어간다.
    options = client.calls[0]["options"]
    assert options.get("num_ctx") == 8192
    assert options.get("num_predict") == 512  # corpus-pin: 코퍼스 무관 — 출력 토큰 상한
    assert options.get("temperature") == 0.0


def test_evaluate_model_oracle_perfect_match() -> None:
    items = build_defect_seeded_set(n_defective=70, n_clean=70, seed=6)
    truth_by_slug = {item.candidate.problem.slug: item.defect_class for item in items}

    def responder(kwargs: dict[str, Any]) -> _FakeResponse:
        slug = kwargs["prompt"].split("[문항 slug] ")[1].split("\n")[0]
        truth = truth_by_slug.get(slug)
        if truth:
            return _FakeResponse(f'{{"has_defect": true, "defect_class": "{truth}"}}')
        return _FakeResponse('{"has_defect": false}')

    client = _FakeOllamaClient(responder)
    outcomes = asyncio.run(
        qb.evaluate_model(
            "fake",
            items,
            client=client,  # type: ignore[arg-type]
        )
    )
    report = qb._summarize("fake", outcomes)
    assert report.metrics.true_positives == 70
    assert report.metrics.false_positives == 0
    assert report.metrics.false_negatives == 0
    assert report.metrics.true_negatives == 70


def test_evaluate_model_handles_generation_error_gracefully() -> None:
    items = build_defect_seeded_set(n_defective=2, n_clean=2, seed=7)

    def responder(kwargs: dict[str, Any]) -> _FakeResponse:
        raise RuntimeError("ollama down")

    client = _FakeOllamaClient(responder)
    outcomes = asyncio.run(
        qb.evaluate_model(
            "fake",
            items,
            client=client,  # type: ignore[arg-type]
        )
    )
    assert all(not o.parsed for o in outcomes)
    assert all("ollama down" in (o.parse_error or "") for o in outcomes)


# ──────────────────────────────────────────────────────────────────────────
# CLI / 게이트
# ──────────────────────────────────────────────────────────────────────────
def _make_oracle_client(items: list[Any]) -> _FakeOllamaClient:
    truth_by_slug = {item.candidate.problem.slug: item.defect_class for item in items}

    def responder(kwargs: dict[str, Any]) -> _FakeResponse:
        slug = kwargs["prompt"].split("[문항 slug] ")[1].split("\n")[0]
        truth = truth_by_slug.get(slug)
        if truth:
            return _FakeResponse(f'{{"has_defect": true, "defect_class": "{truth}"}}')
        return _FakeResponse('{"has_defect": false}')

    return _FakeOllamaClient(responder)


def _make_blind_ok_client() -> _FakeOllamaClient:
    return _FakeOllamaClient(lambda _k: _FakeResponse('{"has_defect": false}'))


def _monkeypatch_evaluate(monkeypatch: Any, baseline_client: Any, candidate_client: Any) -> None:
    """evaluate_model을 monkeypatch해 client 주입을 시뮬레이션한다."""
    original = qb.evaluate_model

    async def fake_evaluate(
        model_id: str,
        items: list[Any],
        *,
        client: Any = None,
        **kwargs: Any,
    ) -> list[qb.ModelOutcome]:
        selected = candidate_client if model_id == "candidate" else baseline_client
        return await original(model_id, items, client=selected, **kwargs)

    monkeypatch.setattr(qb, "evaluate_model", fake_evaluate)


def test_main_report_only_returns_0(monkeypatch: Any) -> None:
    items = build_defect_seeded_set(n_defective=14, n_clean=14, seed=8)
    _monkeypatch_evaluate(
        monkeypatch,
        _make_oracle_client(items),
        _make_oracle_client(items),
    )
    rc = qb.main(
        [
            "--baseline-model",
            "base",
            "--candidate-model",
            "candidate",
            "--n-defective",
            "14",
            "--n-clean",
            "14",
            "--seed",
            "8",
        ]
    )
    assert rc == 0


def test_main_candidate_worse_fails_not_worse_gate(monkeypatch: Any) -> None:
    items = build_defect_seeded_set(n_defective=14, n_clean=14, seed=9)
    _monkeypatch_evaluate(
        monkeypatch,
        _make_oracle_client(items),
        _make_blind_ok_client(),
    )
    rc = qb.main(
        [
            "--baseline-model",
            "base",
            "--candidate-model",
            "candidate",
            "--n-defective",
            "14",
            "--n-clean",
            "14",
            "--seed",
            "9",
            "--require-candidate-not-worse-than-baseline",
        ]
    )
    assert rc == 1


def test_main_min_detection_gate_fails(monkeypatch: Any) -> None:
    items = build_defect_seeded_set(n_defective=14, n_clean=14, seed=10)
    _monkeypatch_evaluate(
        monkeypatch,
        _make_oracle_client(items),
        _make_blind_ok_client(),
    )
    rc = qb.main(
        [
            "--baseline-model",
            "base",
            "--candidate-model",
            "candidate",
            "--n-defective",
            "14",
            "--n-clean",
            "14",
            "--seed",
            "10",
            "--min-detection-lower",
            "0.5",
        ]
    )
    assert rc == 1


def test_main_audit_out_written(monkeypatch: Any, tmp_path: Path) -> None:
    items = build_defect_seeded_set(n_defective=7, n_clean=7, seed=11)
    _monkeypatch_evaluate(
        monkeypatch,
        _make_oracle_client(items),
        _make_oracle_client(items),
    )
    audit = tmp_path / "ops48.jsonl"
    rc = qb.main(
        [
            "--baseline-model",
            "base",
            "--candidate-model",
            "candidate",
            "--n-defective",
            "7",
            "--n-clean",
            "7",
            "--seed",
            "11",
            "--audit-out",
            str(audit),
        ]
    )
    assert rc == 0
    lines = audit.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 7 + 7 + 1  # baseline+candidate rows + summary
    summary = json.loads(lines[-1])
    assert "as_found_baseline_detection_rate" in summary
    assert "as_found_candidate_detection_rate" in summary


# ──────────────────────────────────────────────────────────────────────────
# Wilson sanity
# ──────────────────────────────────────────────────────────────────────────
def test_wilson_bounds_around_point_estimate() -> None:
    lb = wilson_lower_bound(45, 50, 0.95)
    ub = wilson_upper_bound(45, 50, 0.95)
    assert lb < 0.90 < ub
