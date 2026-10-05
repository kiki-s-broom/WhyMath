"""OPS-107 — 저작·배치 경로의 `provider.generate` 직접 호출 전수 + 저작 표지(`traffic_surface`) 동결.

배경: OPS-84 ①은 "파이프라인을 우회하고 provider를 직접 부르는 마지막 1건"을 `rephrase.py`로
적었다. 실측은 달랐다 — AST 스캔으로 `provider.generate` 직접 호출이 **16자리**(12개 함수·
파이프라인 코어 4 포함)이고, 저작 생성기 5곳(동등문제·다중 풀이·설명·비유·교차검증)이 `l3_routing` 이벤트를
`traffic_surface` 표지 없이 낸다. `ops/cost_report`는 표지 없는 이벤트를 **서빙 표본**으로 세므로
(구 이벤트 하위호환), 저작 배치가 라이브로 돌면 게이트②의 로컬 비율·토큰 p50이 위장된다.

이 파일이 계약으로 동결하는 것:
  ① 직접 호출 자리의 전수 — 새 자리가 생기면 RED(판정 없이 늘리지 못한다), 사라져도 RED(낡은 목록 금지).
  ② 저작 모듈의 모든 `trace.record(...)`는 `AuthoringTraceSink`를 통한다(표지 누락 = RED).
  ③ `AuthoringTraceSink`의 의미 — 표지를 싣고, 원 dict를 바꾸지 않고, TraceSink를 충족한다.
  ④ 게이트② 리포트는 표지 붙은 이벤트를 표본에서 빼되 건수를 남긴다(표지 누락이 왜 위험한지의 실측).

전환 판정(파이프라인 경유 vs 의도적 제외)은 `docs/reviews/ops_107_authoring_bypass_inventory_2026-10-05.md`가
자리별로 소유한다. 여기서는 그 목록이 코드와 어긋나지 않는지만 본다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from whymath_backend.l3.interfaces import (
    AUTHORING_TRAFFIC_SURFACE,
    AuthoringTraceSink,
    RecordingTraceSink,
    TraceSink,
)
from whymath_backend.l3.models import CostTier, Usage
from whymath_backend.l3.multi_solution import _record_trace as ms_record_trace
from whymath_backend.l3.multi_solution import generation_routing_request
from whymath_backend.l3.router import Router
from whymath_backend.ops.cost_report import aggregate_l3_events

_PKG = Path(__file__).resolve().parents[3] / "src" / "backend" / "whymath_backend"

# provider 로 읽히는 수신자 — `provider.generate(...)` · `self._provider.generate(...)`.
_PROVIDER_RECEIVERS = {"provider", "self._provider"}

# 자리별 분류 — 판정 근거는 docs/reviews/ops_107_… 가 소유한다. 키 = (패키지 상대 경로, 둘러싼 함수).
_PIPELINE_CORE = "pipeline-core"  # 파이프라인 자신(우회가 아니라 그 경로)
_AUTHORING_TAGGED = "authoring-tagged"  # 저작 생성기 — 직접 호출 유지·trace에 저작 표지 필수
_CACHE_WRITER = "cache-writer"  # 사전생성기 — 런타임 캐시의 쓰기 주체, l3_routing 이벤트 0
_MEASUREMENT = "measurement-harness"  # 측정·진단 하네스 — 서빙 표본과 무관한 일회성 실행

_INVENTORY: dict[tuple[str, str], str] = {
    ("l3/pipeline.py", "generate"): _PIPELINE_CORE,
    ("l3/equivalent/llm_generator.py", "_invoke"): _AUTHORING_TAGGED,
    ("l3/multi_solution.py", "generate_candidates"): _AUTHORING_TAGGED,
    ("l3/pedagogy/explanation_generator.py", "agenerate_draft"): _AUTHORING_TAGGED,
    ("l3/pedagogy/analogy_generator.py", "_invoke"): _AUTHORING_TAGGED,
    ("l3/cross_verify.py", "_run_perspective"): _AUTHORING_TAGGED,
    ("l3/pregenerate/prewarmer.py", "_prewarm_with_decision"): _CACHE_WRITER,
    ("harness/concept_content_review_batch.py", "_assess_one"): _MEASUREMENT,
    ("harness/deepseek_live_probe.py", "_run"): _MEASUREMENT,
    ("harness/generation_seed_replay_probe.py", "probe_one"): _MEASUREMENT,
    ("harness/provider_accuracy_battle.py", "_one"): _MEASUREMENT,
    ("harness/quality_tier_moe_accuracy_battle.py", "_evaluate_one"): _MEASUREMENT,
}

# 같은 함수 안의 호출 개수 — 파이프라인은 호출 형태별 4분기, 사전생성기는 시드 유무 2분기.
_CALLS_PER_SITE: dict[tuple[str, str], int] = {
    ("l3/pipeline.py", "generate"): 4,
    ("l3/pregenerate/prewarmer.py", "_prewarm_with_decision"): 2,
}


class _CallCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.stack: list[str] = []
        self.hits: list[tuple[str, int]] = []  # (둘러싼 함수, 줄)

    def _enter(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = _enter  # noqa: N815
    visit_AsyncFunctionDef = _enter  # noqa: N815

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "generate"
            and ast.unparse(func.value) in _PROVIDER_RECEIVERS
        ):
            self.hits.append((self.stack[-1] if self.stack else "<module>", node.lineno))
        self.generic_visit(node)


def _scan_direct_calls() -> dict[tuple[str, str], int]:
    """패키지 전체의 `provider.generate` 직접 호출 → {(상대 경로, 함수): 호출 수}."""
    found: dict[tuple[str, str], int] = {}
    for path in sorted(_PKG.rglob("*.py")):
        collector = _CallCollector()
        collector.visit(ast.parse(path.read_text(encoding="utf-8")))
        for func_name, _line in collector.hits:
            key = (path.relative_to(_PKG).as_posix(), func_name)
            found[key] = found.get(key, 0) + 1
    return found


# ── ① 전수 ──────────────────────────────────────────────────────────────────


class TestInventoryIsExhaustive:
    def test_scan_finds_something(self) -> None:
        """스캔 0건은 실패 — 전수 가드가 공허하게 통과하는 것을 막는다."""
        assert len(_scan_direct_calls()) >= 10

    def test_inventory_equals_scan(self) -> None:
        found = _scan_direct_calls()
        expected = {
            key: _CALLS_PER_SITE.get(key, 1)
            for key in _INVENTORY  # 호출 수까지 동결(분기 하나가 조용히 늘어도 RED)
        }
        added = sorted(set(found) - set(expected))
        removed = sorted(set(expected) - set(found))
        assert not added, f"판정 없이 늘어난 provider.generate 직접 호출: {added}"
        assert not removed, f"더는 없는 자리가 목록에 남았다: {removed}"
        assert found == expected

    def test_every_site_has_a_known_class(self) -> None:
        known = {_PIPELINE_CORE, _AUTHORING_TAGGED, _CACHE_WRITER, _MEASUREMENT}
        assert set(_INVENTORY.values()) <= known
        assert sum(1 for v in _INVENTORY.values() if v == _AUTHORING_TAGGED) == 5


# ── ② 저작 모듈의 모든 trace.record 는 표지 래퍼를 통한다 ────────────────────────


def _record_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "record"
    ]


def _is_wrapped(call: ast.Call) -> bool:
    """`AuthoringTraceSink(...).record(...)` 형태인가."""
    receiver = call.func.value  # type: ignore[attr-defined]
    return (
        isinstance(receiver, ast.Call)
        and isinstance(receiver.func, ast.Name)
        and receiver.func.id == "AuthoringTraceSink"
    )


_TAGGED_MODULES = sorted(
    {rel for (rel, _fn), cls in _INVENTORY.items() if cls == _AUTHORING_TAGGED}
    | {"l3/equivalent/rephrase.py"}  # rephrase 는 파이프라인 경유지만 같은 표지를 쓴다(OPS-84 ③)
)


class TestAuthoringTraceIsAlwaysTagged:
    @pytest.mark.parametrize(
        "rel", [m for m in _TAGGED_MODULES if m != "l3/equivalent/rephrase.py"]
    )
    def test_every_trace_record_goes_through_the_authoring_sink(self, rel: str) -> None:
        calls = _record_calls(_PKG / rel)
        assert calls, f"{rel}: trace.record 호출이 없다 — 관측 경로가 사라졌거나 이름이 바뀌었다"
        bare = [c.lineno for c in calls if not _is_wrapped(c)]
        assert bare == [], f"{rel}: 저작 표지 없이 기록하는 줄 {bare}"

    def test_rephrase_passes_the_authoring_sink_to_the_pipeline(self) -> None:
        text = (_PKG / "l3/equivalent/rephrase.py").read_text(encoding="utf-8")
        assert "trace=AuthoringTraceSink(" in text


# ── ③ AuthoringTraceSink 의미 ───────────────────────────────────────────────


class TestAuthoringTraceSink:
    def test_adds_the_authoring_surface_tag(self) -> None:
        inner = RecordingTraceSink()
        AuthoringTraceSink(inner).record({"cost_tier": "LOCAL"})
        assert inner.records == [
            {"cost_tier": "LOCAL", "traffic_surface": AUTHORING_TRAFFIC_SURFACE}
        ]
        assert AUTHORING_TRAFFIC_SURFACE == "authoring"

    def test_does_not_mutate_the_callers_dict(self) -> None:
        inner = RecordingTraceSink()
        fields: dict[str, object] = {"cost_tier": "LOCAL"}
        AuthoringTraceSink(inner).record(fields)
        assert "traffic_surface" not in fields  # 호출자 dict 불변

    def test_satisfies_the_trace_sink_protocol(self) -> None:
        assert isinstance(AuthoringTraceSink(RecordingTraceSink()), TraceSink)

    def test_explicit_surface_in_input_is_overwritten_not_trusted(self) -> None:
        # 저작 래퍼를 거친 기록은 항상 authoring 이다 — 호출자가 다른 값을 실어도 덮어쓴다.
        inner = RecordingTraceSink()
        AuthoringTraceSink(inner).record({"traffic_surface": "serving"})
        assert inner.records[0]["traffic_surface"] == "authoring"


# ── 실제 사이트 1곳의 행동 — 모듈 함수라 생성자 없이 호출 가능 ─────────────────────


class TestMultiSolutionRecordsTheAuthoringTag:
    def test_record_trace_emits_the_tag(self) -> None:
        sink = RecordingTraceSink()
        decision = Router().route(generation_routing_request("free"))
        ms_record_trace(sink, decision, Usage(input_tokens=10, output_tokens=5, latency_ms=100))
        assert len(sink.records) == 1
        assert sink.records[0]["traffic_surface"] == "authoring"


# ── ④ 표지가 없으면 서빙 표본으로 센다 — 표지 누락이 위험한 이유의 실측 ──────────────────


class TestUntaggedAuthoringEventsPolluteTheServingSample:
    def _event(self, **extra: object) -> dict[str, object]:
        return {
            "cost_tier": CostTier.LOCAL.value,
            "cache_hit": False,
            "input_tokens": 100,
            "output_tokens": 50,
            "cost_krw": 0.0,
            **extra,
        }

    def test_tagged_events_are_excluded_and_counted(self) -> None:
        events = [self._event(), self._event(traffic_surface="authoring")]
        report = aggregate_l3_events(events)
        assert report.authoring_excluded_count == 1

    def test_untagged_authoring_batch_inflates_the_local_ratio(self) -> None:
        # 서빙 2건(1 로컬·1 클라우드) + 표지 없는 저작 배치 8건(로컬) → 로컬 비율이 0.5 → 0.9로 부푼다.
        serving = [self._event(), self._event(cost_tier=CostTier.CLOUD_MID.value)]
        batch_untagged = [self._event() for _ in range(8)]
        batch_tagged = [self._event(traffic_surface="authoring") for _ in range(8)]
        untagged = aggregate_l3_events(serving + batch_untagged)
        tagged = aggregate_l3_events(serving + batch_tagged)
        assert untagged.local_ratio is not None and tagged.local_ratio is not None
        assert tagged.local_ratio == pytest.approx(0.5)
        assert untagged.local_ratio == pytest.approx(0.9)
