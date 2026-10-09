"""학생 대면 SymPy 검증 호출의 격리 경유 거버넌스 — AST 전수 (OPS-96 ① · OPS-123 ③ 집행 지점).

`l3/isolated_call.py`·`api/_isolated_call.py`가 *존재함*과 서빙 경로가 그것을 *경유함*은 다르다
(CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지"). 이 파일은 후자를 소스 구조로 동결한다.

단언:
  ① `api/verify.py`의 모든 `async def`와 `api/coach.py::_final_answer_state`에서 SymPy 검증 함수
     (`verify_step`·`verify_solution`·`verify_answer`·`verify_final_answer`·`verify_answer_form`)는
     **오직 `isolated(...)`의 첫 인자로만** 등장한다. 직접 호출뿐 아니라 `to_thread`·`partial`·
     `run_in_executor`로 감싼 우회도 같은 참조 규칙으로 걸린다(상한 없는 우회로 차단).
  ② 위 두 자리에 `isolated(...)` 호출이 실제로 존재한다 — 스캔 0건 공허 통과 금지.
  ③ **알려진 미격리 지점 동결** — 코치 턴의 풀이 단계 연쇄 검증(`step_chain`)과 시도 오개념 훑기
     (`attempt_misconception_detector`)는 같은 SymPy를 동기로 부르지만 이 회수 범위 밖이다. 개수를
     못 박아 *늘지 못하게* 하고, 승계 태스크가 닫히면 이 동결 자신이 실패해 제거를 강제한다
     (만료 없는 유예 금지 — CLAUDE.md).

검사기는 소스 텍스트가 아니라 AST를 본다 — 표기 변형(줄바꿈·별칭 호출)에 뚫리지 않는다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[3]
_API = _ROOT / "src" / "backend" / "whymath_backend" / "api"

_VERIFY_NAMES = frozenset(
    {"verify_step", "verify_solution", "verify_answer", "verify_final_answer", "verify_answer_form"}
)

# 승계 태스크 — 미격리 지점(step_chain·attempt_misconception_detector)을 격리한다.
_SUCCESSOR_TASK = "OPS-125-coach-step-chain-isolation"
_KNOWN_UNISOLATED = {"step_chain": 3, "attempt_misconception_detector": 1}


def _tree(name: str) -> ast.Module:
    return ast.parse((_API / name).read_text(encoding="utf-8"))


def _async_defs(tree: ast.Module, only: str | None = None) -> list[ast.AsyncFunctionDef]:
    found = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]
    return [n for n in found if only is None or n.name == only]


def _is_isolated_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "isolated"
    )


def _ref_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _scan(fns: list[ast.AsyncFunctionDef]) -> tuple[list[tuple[str, int]], int]:
    """(격리 밖 검증 함수 참조 [(이름, 줄)], 격리 호출 수)."""
    violations: list[tuple[str, int]] = []
    isolated_calls = 0
    for fn in fns:
        allowed: set[int] = set()
        for node in ast.walk(fn):
            if _is_isolated_call(node):
                isolated_calls += 1
                assert isinstance(node, ast.Call)
                if node.args:
                    allowed.add(id(node.args[0]))
        for node in ast.walk(fn):
            name = _ref_name(node)
            if name in _VERIFY_NAMES and id(node) not in allowed:
                violations.append((name, getattr(node, "lineno", -1)))
    return violations, isolated_calls


class TestVerificationGoesThroughIsolation:
    def test_verify_router_calls_sympy_only_via_isolated(self) -> None:
        fns = _async_defs(_tree("verify.py"))
        violations, isolated_calls = _scan(fns)
        assert not violations, f"격리 밖 SymPy 검증 참조(줄): {violations}"
        # 단계 1 + 풀이 연쇄(전이 루프) 1 + 답 1 = 3곳 — 0건 공허 통과 금지.
        assert isolated_calls >= 3, f"verify.py의 isolated 호출이 {isolated_calls}건뿐이다"

    def test_coach_final_answer_state_calls_sympy_only_via_isolated(self) -> None:
        fns = _async_defs(_tree("coach.py"), only="_final_answer_state")
        assert len(fns) == 1, "coach.py::_final_answer_state를 찾지 못했다(이름 변경?)"
        violations, isolated_calls = _scan(fns)
        assert not violations, f"격리 밖 SymPy 검증 참조(줄): {violations}"
        assert isolated_calls == 2, "값 판정 + 형태 판정 두 곳이 모두 격리돼야 한다"

    def test_scanner_detects_injected_bypasses(self) -> None:
        """검사기 자신의 변별력 — 직접 호출·to_thread·partial 우회를 실제로 잡는다."""
        bypasses = {
            "direct": "async def h():\n    return verify_step(a, b)\n",
            "attr": "async def h(c):\n    return c.final_answer.verify_final_answer(a, b)\n",
            "to_thread": "async def h():\n    return await asyncio.to_thread(verify_answer, a, b)\n",
            "partial": "async def h():\n    return partial(verify_solution, a)\n",
        }
        for label, src in bypasses.items():
            fns = _async_defs(ast.parse(src))
            violations, _ = _scan(fns)
            assert violations, f"우회 {label!r}를 검출하지 못했다"
        clean = (
            "async def h():\n    return await isolated(verify_step, a, b, on_budget_exceeded=f)\n"
        )
        violations, isolated_calls = _scan(_async_defs(ast.parse(clean)))
        assert not violations and isolated_calls == 1


class TestKnownUnisolatedSitesAreFrozen:
    def test_unisolated_capability_uses_do_not_grow(self) -> None:
        tree = _tree("coach.py")
        counts = {name: 0 for name in _KNOWN_UNISOLATED}
        for fn in _async_defs(tree):
            for node in ast.walk(fn):
                if isinstance(node, ast.Attribute) and node.attr in counts:
                    counts[node.attr] += 1
        assert counts == _KNOWN_UNISOLATED, (
            f"미격리 능력 사용 지점이 바뀌었다: 실측 {counts} ≠ 동결 {_KNOWN_UNISOLATED}. "
            f"늘었다면 격리하라(승계 {_SUCCESSOR_TASK}); 줄었다면 동결값을 갱신하라."
        )

    def test_freeze_expires_when_successor_task_is_done(self) -> None:
        """만료 없는 유예 금지 — 승계 태스크가 닫히면 이 동결은 제거돼야 한다."""
        path = _ROOT / "backlog" / "tasks" / f"{_SUCCESSOR_TASK}.yaml"
        if not path.exists():
            pytest.fail(f"승계 태스크 파일이 없다: {path.name} — 동결의 근거가 사라졌다")
        status = yaml.safe_load(path.read_text(encoding="utf-8"))["status"]
        assert status != "done", (
            f"{_SUCCESSOR_TASK}가 done이다 — 미격리 동결을 제거하고 step_chain·"
            "attempt_misconception_detector를 ① 격리 단언에 편입하라."
        )
