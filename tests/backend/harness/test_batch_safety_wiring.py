"""배치 안전장치의 **배선 실재성** 동결 (EOS-95 ④).

`batch_safety` 모듈이 저장소에 존재한다는 것과 배치 루프가 그것을 실제로 부른다는 것은
다르다(CLAUDE.md「정본화를 집행으로 착각한 완료 선언 금지」). 이 파일은 모듈 docstring의
**집행 지점 표가 실물과 일치하는지**를 기계로 대조한다.

특히 "경유하지 않는다"고 적은 두 루프가 나중에 배선되면 이 테스트가 깨진다 — 그때
docstring 표를 갱신하라는 뜻이다. **정직한 미배선을 동결하는 것이지 미배선을 정당화하는
것이 아니다.**

## 왜 `inspect.getsource`가 아니라 AST인가 (2026-09-06 실측 교훈)

초판은 `inspect.getsource(func)`로 함수 본문 문자열을 받아 부분문자열을 검사했다. 그런데
`getsource`는 함수의 `co_firstlineno`로 **파일을 다시 읽어** 소스를 잘라 낸다 — 모듈이
import된 뒤 파일이 바뀌면 **조용히 엉뚱한 함수의 본문을 반환한다**(실측: `run_corpus_accumulate`
를 요청했는데 `_queue_entry` 본문이 왔다). 그 상태에서 부분문자열 검사는 *틀린 대상*을 보고
통과하거나 실패한다 — 검사 자체가 위장이 된다.

그래서 파일을 한 번만 파싱해 **AST에서 함수 노드를 이름으로 찾고, 그 노드 안의 실제 호출
이름을 수집**한다. 문자열이 아니라 구성된 결과를 보는 것이 이 저장소의 규약이기도 하다
(CLAUDE.md 2026-09-01 — "금지 패턴 열거 대신 산출물 검사").
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import ModuleType

import pytest

from whymath_backend.harness import batch_safety, problem_corpus_accumulate, problem_corpus_batch
from whymath_backend.l3.equivalent import orchestrator


def _module_tree(module: ModuleType) -> ast.Module:
    """모듈 파일을 파싱한 AST — 줄 번호 오프셋에 의존하지 않는다."""
    path = Path(module.__file__ or "")
    assert path.is_file(), f"모듈 파일을 찾지 못했다: {module!r}"
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function_node(module: ModuleType, name: str) -> ast.FunctionDef:
    """모듈 최상위에서 `name` 함수 노드를 찾는다 — 없으면 실패(스캔 0건은 공허한 통과)."""
    for node in _module_tree(module).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{module.__name__}에 최상위 함수 {name!r}가 없다")


def _called_names(node: ast.AST) -> set[str]:
    """서브트리 안에서 호출되는 이름 집합 — `f()`는 'f', `obj.m()`은 'm'으로 모은다."""
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def _referenced_attributes(node: ast.AST) -> set[str]:
    """서브트리 안에서 참조되는 속성 이름 집합(`report.canary_blocked` → 'canary_blocked')."""
    return {child.attr for child in ast.walk(node) if isinstance(child, ast.Attribute)}


class TestHelpersAreDiscriminating:
    """검사 도구 자체가 변별력을 갖는지 — 스캔 0건으로 공허하게 통과하지 않아야 한다."""

    def test_missing_function_raises(self) -> None:
        with pytest.raises(AssertionError):
            _function_node(batch_safety, "이런_함수는_없다")

    def test_called_names_finds_both_call_shapes(self) -> None:
        tree = ast.parse("def f():\n    g()\n    obj.m()\n")
        assert _called_names(tree) == {"g", "m"}


class TestAccumulateIsWired:
    """축적 경로는 실제로 경유한다 — 존재가 아니라 **그 함수 안의 호출**을 확인한다."""

    def test_loop_function_calls_both_guards(self) -> None:
        node = _function_node(problem_corpus_accumulate, "run_corpus_accumulate")
        called = _called_names(node)
        assert "evaluate_canary" in called, "카나리 판정이 루프 함수 안에서 불리지 않는다"
        assert "RollingFailureWindow" in called, "롤링 감시가 루프 함수 안에서 만들어지지 않는다"
        assert "should_abort" in called, "롤링 판정이 조회되지 않는다"

    def test_loop_signature_exposes_gate_knobs(self) -> None:
        node = _function_node(problem_corpus_accumulate, "run_corpus_accumulate")
        params = {arg.arg for arg in node.args.args} | {arg.arg for arg in node.args.kwonlyargs}
        for name in (
            "canary_size",
            "canary_threshold",
            "canary_confidence",
            "abort_window",
            "abort_threshold",
        ):
            assert name in params, name

    def test_cli_judges_both_gates_by_exit_code(self) -> None:
        """CLI가 두 게이트 판정을 읽는다 — 판정은 exit code로 한다(CLAUDE.md)."""
        node = _function_node(problem_corpus_accumulate, "main")
        attrs = _referenced_attributes(node)
        assert "canary_blocked" in attrs
        assert "aborted" in attrs


class TestDocumentedNonCoverageStaysHonest:
    """docstring이 "경유하지 않는다"고 적은 좌석 — 실제로 그런지 확인한다.

    배선되면 RED가 되고, 그때 docstring 표를 고치게 된다(있는 척도, 없는 척도 막는다).
    """

    def test_l3_orchestrator_does_not_import_the_harness_gate(self) -> None:
        tree = _module_tree(orchestrator)
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not any("batch_safety" in (mod or "") for mod in imported), (
            "L3 orchestrator가 harness.batch_safety를 import한다 — 계층 역참조이거나, "
            "배선됐다면 batch_safety 모듈 docstring의 집행 지점 표를 갱신해야 한다."
        )

    def test_corpus_batch_does_not_use_the_gate_yet(self) -> None:
        source = Path(problem_corpus_batch.__file__ or "").read_text(encoding="utf-8")
        assert "batch_safety" not in source, (
            "problem_corpus_batch가 배선됐다 — batch_safety 모듈 docstring의 집행 지점 "
            "표에서 '경유하지 않는다'를 고쳐야 한다."
        )


class TestDocstringTableMatchesReality:
    def test_enforcement_table_names_all_three_loops(self) -> None:
        """표가 세 루프를 전부 열거하는지 — 하나라도 빠지면 '있는 척'이 가능해진다."""
        doc = batch_safety.__doc__ or ""
        assert "run_corpus_accumulate" in doc
        assert "orchestrator.py::run_batch" in doc
        assert "problem_corpus_batch.py::run_batch" in doc

    def test_table_states_non_coverage_explicitly(self) -> None:
        doc = batch_safety.__doc__ or ""
        assert "경유하지 않는다" in doc
        assert "아직 보호받지 않는다" in doc
