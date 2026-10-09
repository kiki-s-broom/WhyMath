"""OPS-50 QUALITY 티어(MoE) 파싱 실패 안정화 도구 — hermetic(fake client·라이브 LLM 0).

검증 축:
  ① 실제 OPS-48 감사 JSONL 재분류 — 파싱 실패 16건의 정답지별·원인별 분포를 고정한다.
  ⑤ 미분류 처리 A/B/C — 같은 감사 파일에서 문서(§6.2 민감도 표)의 수치가 재현된다.
  ② 프롬프트 변형 — 한 번에 하나만 바꾼다(기준 대비 차이가 변형이 말한 곳에만 있다).
  원인 기록 — 출력 상한 절단·형식 불량·빈 응답·전송 오류가 서로 다른 failure_kind 로 남는다.
  게이트 — 미분류율 상한·최악 가정(B/C) 정책이 A 정책과 다른 판정을 낸다.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import quality_tier_moe_accuracy_battle as qb
from whymath_backend.l3.equivalent.defect_seeder import (
    DEFECT_CLASSES,
    build_defect_seeded_set,
)

_AUDIT = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "audit"
    / "ops-48-moe-accuracy-battle-20260822_232452.jsonl"
)


# ──────────────────────────────────────────────────────────────────────────
# Fake Ollama client
# ──────────────────────────────────────────────────────────────────────────
class _FakeResponse:
    def __init__(self, response: str, eval_count: int = 30) -> None:
        self.response = response
        self.prompt_eval_count = 100
        self.eval_count = eval_count


class _FakeOllamaClient:
    def __init__(self, responder: Any) -> None:
        self._responder = responder
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        return self._responder(kwargs)

    async def list(self) -> dict[str, list[dict[str, str]]]:
        return {"models": []}


def _slug_of(kwargs: dict[str, Any]) -> str:
    return str(kwargs["prompt"].split("[문항 slug] ")[1].split("\n")[0])


def _oracle_client(items: list[Any]) -> _FakeOllamaClient:
    truth = {i.candidate.problem.slug: i.defect_class for i in items}

    def responder(kwargs: dict[str, Any]) -> _FakeResponse:
        cls = truth.get(_slug_of(kwargs))
        if cls:
            return _FakeResponse(f'{{"has_defect": true, "defect_class": "{cls}"}}')
        return _FakeResponse('{"has_defect": false}')

    return _FakeOllamaClient(responder)


def _audit_outcomes(side: str) -> list[qb.ModelOutcome]:
    rows = [json.loads(x) for x in _AUDIT.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [
        qb.ModelOutcome(
            model_id=r[side]["model_id"],
            slug=r["slug"],
            ground_truth=r["ground_truth"],
            detected=r[side]["detected"],
            predicted_class=r[side]["predicted_class"],
            parsed=r[side]["parsed"],
        )
        for r in rows
        if "slug" in r
    ]


# ──────────────────────────────────────────────────────────────────────────
# ① 감사 JSONL 재분류
# ──────────────────────────────────────────────────────────────────────────
def test_reclassification_of_real_ops48_audit(capsys: Any) -> None:
    assert _AUDIT.exists()
    assert qb.main(["--analyze-audit", str(_AUDIT)]) == 0
    out = capsys.readouterr().out
    assert "미분류 16/100" in out
    # 정답지별 — 무결함 10 · broken_latex 4 · explanation_slip 1 · standard_tag_error 1
    assert any(line.split()[:2] == ["clean", "10/50"] for line in out.splitlines())
    assert any(line.split()[:2] == ["broken_latex", "4/7"] for line in out.splitlines())
    # 원인 — 16건 전부 출력 상한(512)에서 절단
    assert "[원인별] truncated 16" in out
    # 잘린 응답 앞부분의 판정 — 무결함 10건도 has_defect=true 로 시작했다
    assert "clean     문항 · has_defect=true       10건" in out
    assert "defective 문항 · has_defect=true       6건" in out


def test_analyze_missing_file_is_input_error(tmp_path: Path) -> None:
    assert qb.main(["--analyze-audit", str(tmp_path / "없는파일.jsonl")]) == 2


def test_analyze_empty_scan_is_failure(tmp_path: Path) -> None:
    """문항이 0건인 감사 파일은 '실패 0건 통과'가 아니라 입력 오류다."""
    empty = tmp_path / "empty.jsonl"
    empty.write_text(json.dumps({"as_found_x": 1}) + "\n", encoding="utf-8")
    assert qb.main(["--analyze-audit", str(empty)]) == 2


# ──────────────────────────────────────────────────────────────────────────
# ⑤ A/B/C 민감도 — 문서 §6.2 표 재현
# ──────────────────────────────────────────────────────────────────────────
def test_abc_sensitivity_reproduces_documented_table() -> None:
    cand = qb._summarize("cand", _audit_outcomes("candidate")).metrics
    base = qb._summarize("base", _audit_outcomes("baseline")).metrics
    # A — 판정에 쓴 방식(미분류 제외)
    assert (cand.true_positives, cand.defective_total) == (28, 44)
    assert (cand.false_positives, cand.clean_total) == (2, 40)
    assert cand.detection_lower_bound() == pytest.approx(0.512, abs=1e-3)
    assert cand.false_alarm_upper_bound() == pytest.approx(0.140, abs=1e-3)
    # B — 결함 미분류=놓침: 28/50
    assert (cand.unresolved_defective, cand.unresolved_clean) == (6, 10)
    assert cand.worst_case_detection_lower_bound() == pytest.approx(0.444, abs=1e-3)
    # C — 무결함 미분류=오경보: (2+10)/50
    assert cand.worst_case_false_alarm_upper_bound() == pytest.approx(0.351, abs=1e-3)
    assert base.worst_case_false_alarm_upper_bound() == pytest.approx(0.141, abs=1e-3)
    assert cand.unresolved_rate == pytest.approx(0.16)


def test_worst_case_equals_plain_when_nothing_unresolved() -> None:
    m = qb.DetectionMetrics(8, 2, 1, 9, 0)
    assert m.worst_case_detection_lower_bound() == m.detection_lower_bound()
    assert m.worst_case_false_alarm_upper_bound() == m.false_alarm_upper_bound()
    assert m.unresolved_rate == 0.0


# ──────────────────────────────────────────────────────────────────────────
# ② 프롬프트 변형 — 한 번에 하나만 바꾼다
# ──────────────────────────────────────────────────────────────────────────
def test_every_variant_builds_and_unknown_is_rejected() -> None:
    for name in qb.PROMPT_VARIANTS:
        assert qb.build_variant(name).name == name
    with pytest.raises(ValueError):
        qb.build_variant("없는변형")


def test_baseline_variant_is_ops48_prompt_unchanged() -> None:
    v = qb.build_variant("baseline")
    assert v.system == qb._SYSTEM_PROMPT
    assert v.json_schema == qb._JSON_SCHEMA
    assert not v.two_stage


@pytest.mark.parametrize("name", ["latex_check", "few_shot"])
def test_prompt_only_variants_keep_schema(name: str) -> None:
    v = qb.build_variant(name)
    assert v.json_schema == qb._JSON_SCHEMA  # schema 는 그대로
    assert v.system.startswith(qb._SYSTEM_PROMPT)  # 기준 프롬프트 뒤에 덧붙이기만
    assert len(v.system) > len(qb._SYSTEM_PROMPT)


def test_short_reason_changes_only_reason_property() -> None:
    v = qb.build_variant("short_reason")
    assert v.system.startswith(qb._SYSTEM_PROMPT)
    base_props = qb._JSON_SCHEMA["properties"]
    props = v.json_schema["properties"]
    assert props["has_defect"] == base_props["has_defect"]
    assert props["defect_class"] == base_props["defect_class"]
    assert props["reason"]["maxLength"] <= 100
    assert v.json_schema["required"] == qb._JSON_SCHEMA["required"]


def test_reason_first_puts_reason_before_verdict() -> None:
    v = qb.build_variant("reason_first")
    assert list(v.json_schema["properties"])[:2] == ["reason", "has_defect"]
    assert v.json_schema["required"][0] == "reason"  # 선택 항목이면 건너뛸 수 있다
    assert qb._prompt_head(qb._SYSTEM_PROMPT) in v.system  # 결함 유형 목록은 그대로


def test_stage_split_defines_two_calls_with_enum() -> None:
    v = qb.build_variant("stage_split")
    assert v.two_stage
    assert list(v.json_schema["properties"]) == ["has_defect"]
    assert v.stage2_json_schema is not None
    assert v.stage2_json_schema["properties"]["defect_class"]["enum"] == list(DEFECT_CLASSES)


def test_variant_needs_format_marker_in_base_prompt() -> None:
    with pytest.raises(ValueError):
        qb.build_variant("stage_split", base_system="표지 없는 프롬프트", base_schema={})


def test_few_shot_example_is_not_in_the_seeded_test_set() -> None:
    """예시가 시험지 문항과 겹치면 정답을 알려 주는 셈이다."""
    items = build_defect_seeded_set(n_defective=50, n_clean=50, seed=20260708)
    for item in items:
        p = item.candidate.problem
        assert p.slug != "example-distance"
        assert "거리 공식" not in p.question_text


# ──────────────────────────────────────────────────────────────────────────
# 원인 기록 — failure_kind
# ──────────────────────────────────────────────────────────────────────────
def test_classify_failure_separates_causes() -> None:
    assert qb._classify_failure("", 30, 512) == "empty"
    assert qb._classify_failure('{"has_defect": true, "reason": "끊긴', 512, 512) == "truncated"
    assert qb._classify_failure("JSON 아님", 30, 512) == "malformed"
    # 상한을 모르면(None) 절단이라 단정하지 않는다.
    assert qb._classify_failure("{끊긴", 512, None) == "malformed"


def _run(responder: Any, **kwargs: Any) -> list[qb.ModelOutcome]:
    items = build_defect_seeded_set(n_defective=7, n_clean=7, seed=3)
    client = _FakeOllamaClient(responder)
    return asyncio.run(
        qb.evaluate_model(
            "fake",
            items,
            client=client,  # type: ignore[arg-type]
            **kwargs,
        )
    )


def test_truncated_response_is_recorded_with_cause() -> None:
    out = _run(
        lambda _k: _FakeResponse('{"has_defect": true, "reason": "정답이 맞으나, 해설에서', 512)
    )
    assert all(not o.parsed and o.failure_kind == "truncated" for o in out)
    report = qb._summarize("fake", out)
    assert report.failure_kinds == {"truncated": len(out)}
    assert report.metrics.unresolved_defective == 7
    assert report.metrics.unresolved_clean == 7


def test_malformed_empty_and_transport_get_distinct_kinds() -> None:
    assert {o.failure_kind for o in _run(lambda _k: _FakeResponse("그냥 문장", 30))} == {
        "malformed"
    }
    assert {o.failure_kind for o in _run(lambda _k: _FakeResponse("", 0))} == {"empty"}

    def boom(_k: dict[str, Any]) -> _FakeResponse:
        raise RuntimeError("ollama down")

    assert {o.failure_kind for o in _run(boom)} == {"transport"}


def test_parsed_response_has_no_failure_kind() -> None:
    out = _run(lambda _k: _FakeResponse('{"has_defect": false}'))
    assert all(o.parsed and o.failure_kind is None for o in out)


# ──────────────────────────────────────────────────────────────────────────
# stage_split — 호출 규약
# ──────────────────────────────────────────────────────────────────────────
def test_stage_split_asks_class_only_when_defect_found() -> None:
    items = build_defect_seeded_set(n_defective=7, n_clean=7, seed=4)
    truth = {i.candidate.problem.slug: i.defect_class for i in items}

    def responder(kwargs: dict[str, Any]) -> _FakeResponse:
        fmt = kwargs["format"]
        if "has_defect" in fmt["properties"]:  # 1단계
            return _FakeResponse(
                f'{{"has_defect": {str(truth[_slug_of(kwargs)] is not None).lower()}}}'
            )
        return _FakeResponse(f'{{"defect_class": "{truth[_slug_of(kwargs)]}"}}')

    client = _FakeOllamaClient(responder)
    out = asyncio.run(
        qb.evaluate_model(
            "fake",
            items,
            client=client,  # type: ignore[arg-type]
            json_schema=qb._JSON_SCHEMA,
            variant=qb.build_variant("stage_split"),
        )
    )
    assert len(client.calls) == 7 * 2 + 7  # 결함 문항 2회 · 무결함 문항 1회
    for o in out:
        assert o.parsed
        assert o.detected == (o.ground_truth is not None)
        assert o.predicted_class == o.ground_truth
        assert o.latency_ms is not None
    assert any("\n---\n" in o.raw_response for o in out)


def test_variant_respects_no_json_schema() -> None:
    items = build_defect_seeded_set(n_defective=1, n_clean=1, seed=4)
    client = _FakeOllamaClient(lambda _k: _FakeResponse('{"has_defect": false}'))
    asyncio.run(
        qb.evaluate_model(
            "fake",
            items,
            client=client,  # type: ignore[arg-type]
            json_schema=None,
            variant=qb.build_variant("short_reason"),
        )
    )
    assert all("format" not in c for c in client.calls)


def test_variant_system_and_schema_reach_the_call() -> None:
    items = build_defect_seeded_set(n_defective=1, n_clean=1, seed=4)
    client = _FakeOllamaClient(lambda _k: _FakeResponse('{"has_defect": false}'))
    variant = qb.build_variant("short_reason")
    asyncio.run(
        qb.evaluate_model(
            "fake",
            items,
            client=client,  # type: ignore[arg-type]
            json_schema=qb._JSON_SCHEMA,
            variant=variant,
        )
    )
    assert client.calls[0]["system"] == variant.system
    assert client.calls[0]["format"] == variant.json_schema


# ──────────────────────────────────────────────────────────────────────────
# 기준 결과 재사용
# ──────────────────────────────────────────────────────────────────────────
def test_baseline_audit_reuse_skips_baseline_calls(monkeypatch: Any, tmp_path: Path) -> None:
    items = build_defect_seeded_set(n_defective=7, n_clean=7, seed=12)
    clients = {"base": _oracle_client(items), "candidate": _oracle_client(items)}
    original = qb.evaluate_model

    async def fake_evaluate(model_id: str, its: list[Any], *, client: Any = None, **kw: Any) -> Any:
        return await original(model_id, its, client=clients[model_id], **kw)

    monkeypatch.setattr(qb, "evaluate_model", fake_evaluate)
    common = ["--n-defective", "7", "--n-clean", "7", "--seed", "12"]
    first = tmp_path / "first.jsonl"
    assert (
        qb.main(
            [
                "--baseline-model",
                "base",
                "--candidate-model",
                "candidate",
                *common,
                "--audit-out",
                str(first),
            ]
        )
        == 0
    )
    base_calls = len(clients["base"].calls)
    assert base_calls == 14

    second = tmp_path / "second.jsonl"
    rc = qb.main(
        [
            "--candidate-model",
            "candidate",
            *common,
            "--baseline-audit",
            str(first),
            "--prompt-variant",
            "short_reason",
            "--audit-out",
            str(second),
        ]
    )
    assert rc == 0
    assert len(clients["base"].calls) == base_calls  # 기준 모델은 다시 부르지 않았다
    summary = json.loads(second.read_text(encoding="utf-8").splitlines()[-1])
    assert summary["prompt_variant"] == "short_reason"
    assert "candidate_worst_case_false_alarm_upper_bound" in summary


def test_baseline_audit_with_different_test_set_is_rejected(tmp_path: Path) -> None:
    items = build_defect_seeded_set(n_defective=7, n_clean=7, seed=12)
    other = build_defect_seeded_set(n_defective=7, n_clean=7, seed=13)
    assert [i.candidate.problem.slug for i in items] != [i.candidate.problem.slug for i in other]
    outcomes = asyncio.run(
        qb.evaluate_model("b", items, client=_oracle_client(items))  # type: ignore[arg-type]
    )
    report = qb._summarize("b", outcomes)
    audit = tmp_path / "a.jsonl"
    qb._write_audit(
        audit,
        outcomes,
        outcomes,
        qb.BattleReport(
            baseline=report,
            candidate=report,
            n_defective=7,
            n_clean=7,
            seed=12,
            confidence=0.95,
            baseline_model_id="b",
            candidate_model_id="b",
        ),
    )
    assert len(qb.load_baseline_outcomes(audit, items)) == 14
    with pytest.raises(ValueError):
        qb.load_baseline_outcomes(audit, other)
    with pytest.raises(ValueError):
        qb.load_baseline_outcomes(audit, items[:5])


# ──────────────────────────────────────────────────────────────────────────
# 게이트 — 미분류율 상한 · 최악 가정 정책
# ──────────────────────────────────────────────────────────────────────────
def _half_unresolved_clean_client(items: list[Any]) -> _FakeOllamaClient:
    """결함 문항은 정답, 무결함 문항 절반은 출력 상한에서 잘린 응답."""
    truth = {i.candidate.problem.slug: i.defect_class for i in items}
    clean_slugs = [s for s, c in truth.items() if c is None]
    cut = set(clean_slugs[: len(clean_slugs) // 2])

    def responder(kwargs: dict[str, Any]) -> _FakeResponse:
        slug = _slug_of(kwargs)
        if truth[slug]:
            return _FakeResponse(f'{{"has_defect": true, "defect_class": "{truth[slug]}"}}')
        if slug in cut:
            return _FakeResponse('{"has_defect": true, "reason": "끊긴', 512)
        return _FakeResponse('{"has_defect": false}')

    return _FakeOllamaClient(responder)


def _main_with(monkeypatch: Any, extra: list[str]) -> int:
    items = build_defect_seeded_set(n_defective=20, n_clean=20, seed=14)
    clients = {"base": _oracle_client(items), "candidate": _half_unresolved_clean_client(items)}
    original = qb.evaluate_model

    async def fake_evaluate(model_id: str, its: list[Any], *, client: Any = None, **kw: Any) -> Any:
        return await original(model_id, its, client=clients[model_id], **kw)

    monkeypatch.setattr(qb, "evaluate_model", fake_evaluate)
    return qb.main(
        [
            "--baseline-model",
            "base",
            "--candidate-model",
            "candidate",
            "--n-defective",
            "20",
            "--n-clean",
            "20",
            "--seed",
            "14",
            *extra,
        ]
    )


def test_unresolved_rate_gate(monkeypatch: Any) -> None:
    assert _main_with(monkeypatch, []) == 0  # 기본값은 끔
    assert _main_with(monkeypatch, ["--max-unresolved-rate", "0.05"]) == 1  # 10/40 = 25%
    assert _main_with(monkeypatch, ["--max-unresolved-rate", "0.30"]) == 0


def test_worst_policy_flips_false_alarm_gate(monkeypatch: Any) -> None:
    gate = ["--max-false-alarm-upper", "0.30"]
    # A(미분류 제외): 무결함 10건 중 오경보 0 → 상한 ≈ 0.21 < 0.30 → 통과
    assert _main_with(monkeypatch, gate) == 0
    # C(무결함 미분류=오경보): 10/20 → 상한 > 0.30 → 실패
    assert _main_with(monkeypatch, [*gate, "--unresolved-policy", "worst"]) == 1


def test_unknown_variant_is_rejected_by_cli() -> None:
    with pytest.raises(SystemExit) as exc:
        qb.main(["--prompt-variant", "없는변형"])
    assert exc.value.code == 2
