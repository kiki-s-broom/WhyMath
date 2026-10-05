"""OPS-107 — 저작·배치 경로의 `provider.generate` 직접 호출 전수 동결.

배경: OPS-84 ①은 "파이프라인을 우회하고 provider를 직접 부르는 마지막 1건"을 `rephrase.py`로
적었다. 실측은 달랐다 — AST 스캔으로 `provider.generate` 직접 호출이 **16자리**(12개 함수·
파이프라인 코어 4 포함)다. 이 파일은 그 목록이 코드와 어긋나지 않도록 동결한다.

**표지(`traffic_surface`)는 이 파일이 다루지 않는다.** OPS-105(`l3.interfaces.TrafficSurface`)가
저작 생성기들(`llm_generator`·`multi_solution`·`pedagogy/*`·`cross_verify`)을 *의도적 미표기*로
판정했다 — 표면을 추측해 채우면 틀린 표지가 관측으로 위장되기 때문이다. 이 세션이 처음에 그 5곳에
저작 표지를 붙였다가 호출부 추적(`explain_concept_at_age_band`가 FastAPI 요청 핸들러에서 쓰이도록
설계됐다는 docstring 등)과 OPS-105의 판정을 확인하고 철회했다. 근거는
`docs/reviews/ops_107_authoring_bypass_inventory_2026-10-05.md` §3-1이 소유한다.

이 파일이 계약으로 동결하는 것:
  ① 직접 호출 자리의 전수 — 새 자리가 생기면 RED(판정 없이 늘리지 못한다), 사라져도 RED(낡은 목록 금지).
  ② 호출 수까지 동결 — 분기 하나가 조용히 늘어도 RED.
  ③ 목록의 모든 분류가 알려진 어휘다.

전환 판정(파이프라인 경유 vs 의도적 제외)은 같은 문서가 자리별로 소유한다.
"""

from __future__ import annotations

import ast
from pathlib import Path

_PKG = Path(__file__).resolve().parents[3] / "src" / "backend" / "whymath_backend"

# provider 로 읽히는 수신자 — `provider.generate(...)` · `self._provider.generate(...)`.
_PROVIDER_RECEIVERS = {"provider", "self._provider"}

# 자리별 분류 — 판정 근거는 docs/reviews/ops_107_… 가 소유한다. 키 = (패키지 상대 경로, 둘러싼 함수).
_PIPELINE_CORE = "pipeline-core"  # 파이프라인 자신(우회가 아니라 그 경로)
_AUTHORING_UNTAGGED = "authoring-untagged-by-design"  # 저작 생성기 — OPS-105가 의도적 미표기로 판정
_CACHE_WRITER = "cache-writer"  # 사전생성기 — 런타임 캐시의 쓰기 주체, l3_routing 이벤트 0
_MEASUREMENT = "measurement-harness"  # 측정·진단 하네스 — 서빙 표본과 무관한 일회성 실행

_INVENTORY: dict[tuple[str, str], str] = {
    ("l3/pipeline.py", "generate"): _PIPELINE_CORE,
    ("l3/equivalent/llm_generator.py", "_invoke"): _AUTHORING_UNTAGGED,
    ("l3/multi_solution.py", "generate_candidates"): _AUTHORING_UNTAGGED,
    ("l3/pedagogy/explanation_generator.py", "agenerate_draft"): _AUTHORING_UNTAGGED,
    ("l3/pedagogy/analogy_generator.py", "_invoke"): _AUTHORING_UNTAGGED,
    ("l3/cross_verify.py", "_run_perspective"): _AUTHORING_UNTAGGED,
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
        known = {_PIPELINE_CORE, _AUTHORING_UNTAGGED, _CACHE_WRITER, _MEASUREMENT}
        assert set(_INVENTORY.values()) <= known
        assert sum(1 for v in _INVENTORY.values() if v == _AUTHORING_UNTAGGED) == 5
