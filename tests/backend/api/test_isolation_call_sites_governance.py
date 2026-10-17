"""학생 대면 SymPy 검증 호출의 격리 경유 거버넌스 — AST 전수 (OPS-96 ① · OPS-123 ③ · OPS-125 ⑤).

`l3/isolated_call.py`·`api/_isolated_call.py`가 *존재함*과 서빙 경로가 그것을 *경유함*은 다르다
(CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지"). 이 파일은 후자를 소스 구조로 동결한다.

단언:
  ① `api/verify.py`의 모든 `async def`와 `api/coach.py::_final_answer_state`에서 SymPy 검증 함수
     (`verify_step`·`verify_solution`·`verify_answer`·`verify_final_answer`·`verify_answer_form`)는
     **오직 `isolated(...)`의 첫 인자로만** 등장한다. 직접 호출뿐 아니라 `to_thread`·`partial`·
     `run_in_executor`로 감싼 우회도 같은 참조 규칙으로 걸린다(상한 없는 우회로 차단).
  ② 위 두 자리에 `isolated(...)` 호출이 실제로 존재한다 — 스캔 0건 공허 통과 금지.
  ③ **코치 턴의 풀이 단계 연쇄 검증**(OPS-125) — `api/coach.py`의 모든 `async def`에서
     `verify_chain`은 오직 `isolated(...)`의 첫 인자로만 등장하고, `_build_response_payload`(동기)를
     부르는 모든 핸들러는 먼저 `await _verify_chain_isolated(...)`로 계산한 값을
     `chain_verification=`으로 넘긴다. 핸들러가 이 인자를 빼면 L4가 조용히 동기 폴백으로 SymPy를
     이벤트 루프 안에서 돌리므로, 인자 누락 자체를 구조로 잡는다.
  ④ **시도 오개념 훑기**(OPS-125) — 두 채점 경로(코치·`/v1/me/attempts`)가 공유하는
     `_attempt_misconception_scan.py::scan_attempt_misconceptions`에서 `scan_attempt_answer`는
     오직 `isolated(...)`의 첫 인자로만 등장한다.

OPS-125 이전에는 ③④가 "알려진 미격리 지점 동결"(개수 고정)이었다. 승계 태스크가 닫히면 그 동결이
스스로 실패해 제거를 강제하도록 설계돼 있었고(만료 없는 유예 금지 — CLAUDE.md), 이 파일이 그
제거의 결과다.

검사기는 소스 텍스트가 아니라 AST를 본다 — 표기 변형(줄바꿈·별칭 호출)에 뚫리지 않는다.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_API = _ROOT / "src" / "backend" / "whymath_backend" / "api"

_VERIFY_NAMES = frozenset(
    {"verify_step", "verify_solution", "verify_answer", "verify_final_answer", "verify_answer_form"}
)
_CHAIN_NAMES = frozenset({"verify_chain"})
_SCAN_NAMES = frozenset({"scan_attempt_answer"})


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


def _scan(
    fns: list[ast.AsyncFunctionDef], names: frozenset[str] = _VERIFY_NAMES
) -> tuple[list[tuple[str, int]], int]:
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
            if name in names and id(node) not in allowed:
                violations.append((name, getattr(node, "lineno", -1)))
    return violations, isolated_calls


def _payload_callers_missing_precomputed_chain(
    fns: list[ast.AsyncFunctionDef],
) -> tuple[list[str], int]:
    """`_build_response_payload`를 부르면서 선계산 연쇄 검증을 안 넘기는 핸들러 이름과 호출 핸들러 수.

    "넘긴다"의 정의: ⓐ 같은 핸들러 안에 `await _verify_chain_isolated(...)`가 있고 ⓑ 모든
    `_build_response_payload(...)` 호출이 `chain_verification=` 키워드를 갖는다.
    """
    missing: list[str] = []
    callers = 0
    for fn in fns:
        payload_calls = [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_build_response_payload"
        ]
        if not payload_calls:
            continue
        callers += 1
        awaits_chain = any(
            isinstance(n, ast.Await)
            and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Name)
            and n.value.func.id == "_verify_chain_isolated"
            for n in ast.walk(fn)
        )
        passes_kw = all(
            any(k.arg == "chain_verification" for k in c.keywords) for c in payload_calls
        )
        if not (awaits_chain and passes_kw):
            missing.append(fn.name)
    return missing, callers


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


class TestCoachStepChainIsolation:
    """③ 코치 턴의 풀이 단계 연쇄 검증 — 이벤트 루프 안에서 SymPy를 돌릴 길이 없다(OPS-125)."""

    def test_verify_chain_only_via_isolated_in_coach_handlers(self) -> None:
        fns = _async_defs(_tree("coach.py"))
        violations, isolated_calls = _scan(fns, _CHAIN_NAMES)
        assert not violations, f"격리 밖 verify_chain 참조(줄): {violations}"
        assert isolated_calls >= 1
        # 스캔 0건 공허 통과 금지 — 격리 호출의 첫 인자가 실제로 verify_chain이어야 한다.
        helper = _async_defs(_tree("coach.py"), only="_verify_chain_isolated")
        assert len(helper) == 1, "coach.py::_verify_chain_isolated를 찾지 못했다(이름 변경?)"
        refs = [n for n in ast.walk(helper[0]) if _ref_name(n) in _CHAIN_NAMES]
        assert refs, "_verify_chain_isolated가 verify_chain을 참조하지 않는다 — 검사가 공허하다"

    def test_every_payload_caller_precomputes_the_chain(self) -> None:
        missing, callers = _payload_callers_missing_precomputed_chain(
            _async_defs(_tree("coach.py"))
        )
        # 코치 3경로(stateless·세션 생성·턴 추가) — 0건 공허 통과 금지.
        assert callers >= 3, f"_build_response_payload를 부르는 핸들러가 {callers}개뿐이다"
        assert not missing, (
            f"선계산 연쇄 검증(`await _verify_chain_isolated` + `chain_verification=`)을 빠뜨린 "
            f"핸들러: {missing} — L4가 동기 폴백으로 SymPy를 이벤트 루프 안에서 돌린다."
        )

    def test_scanner_detects_missing_precomputation(self) -> None:
        """검사기 자신의 변별력 — 계산만 하고 안 넘기거나, 넘기기만 하고 계산을 안 하는 핸들러를 잡는다."""
        bad = {
            "no_kw": (
                "async def h():\n"
                "    chain = await _verify_chain_isolated(b, v)\n"
                "    return _build_response_payload(b)\n"
            ),
            "no_await": (
                "async def h():\n    return _build_response_payload(b, chain_verification=chain)\n"
            ),
            "sync_call": (
                "async def h():\n"
                "    chain = _verify_chain_isolated(b, v)\n"
                "    return _build_response_payload(b, chain_verification=chain)\n"
            ),
        }
        for label, src in bad.items():
            missing, callers = _payload_callers_missing_precomputed_chain(
                _async_defs(ast.parse(src))
            )
            assert callers == 1 and missing == ["h"], f"우회 {label!r}를 검출하지 못했다"
        good = (
            "async def h():\n"
            "    chain = await _verify_chain_isolated(b, v)\n"
            "    return _build_response_payload(b, chain_verification=chain)\n"
        )
        assert _payload_callers_missing_precomputed_chain(_async_defs(ast.parse(good))) == ([], 1)

    def test_chain_scanner_detects_injected_bypasses(self) -> None:
        for label, src in {
            "direct": "async def h(v):\n    return v.verify_chain(s, t)\n",
            "to_thread": "async def h(v):\n    return await asyncio.to_thread(v.verify_chain, s)\n",
            "partial": "async def h(v):\n    return partial(v.verify_chain, s)\n",
        }.items():
            violations, _ = _scan(_async_defs(ast.parse(src)), _CHAIN_NAMES)
            assert violations, f"우회 {label!r}를 검출하지 못했다"


class TestAttemptMisconceptionScanIsolation:
    """④ 시도 오개념 훑기 — 코치(EOS-146)와 `/v1/me/attempts`가 함께 쓰는 한 곳(OPS-125)."""

    def test_scan_attempt_answer_only_via_isolated(self) -> None:
        fns = _async_defs(
            _tree("_attempt_misconception_scan.py"), only="scan_attempt_misconceptions"
        )
        assert len(fns) == 1, "scan_attempt_misconceptions를 찾지 못했다(이름 변경?)"
        violations, isolated_calls = _scan(fns, _SCAN_NAMES)
        assert not violations, f"격리 밖 scan_attempt_answer 참조(줄): {violations}"
        assert isolated_calls == 1, "텍스트 채널 훑기 한 곳이 격리돼야 한다"
        refs = [n for n in ast.walk(fns[0]) if _ref_name(n) in _SCAN_NAMES]
        assert refs, "scan_attempt_answer를 참조하지 않는다 — 검사가 공허하다"

    def test_callers_do_not_scan_directly(self) -> None:
        """호출자(coach·me)가 능력을 직접 부르는 두 번째 길이 없다 — 훑기는 공유 함수 한 곳뿐."""
        for name in ("coach.py", "me.py"):
            violations, _ = _scan(_async_defs(_tree(name)), _SCAN_NAMES)
            assert not violations, f"{name}에서 격리 밖 scan_attempt_answer 참조(줄): {violations}"

    def test_scan_scanner_detects_injected_bypasses(self) -> None:
        for label, src in {
            "direct": "async def h(d):\n    return d.scan_attempt_answer(question_text=q, student_answer=a)\n",
            "to_thread": (
                "async def h(d):\n"
                "    return await asyncio.to_thread(d.scan_attempt_answer, question_text=q)\n"
            ),
        }.items():
            violations, _ = _scan(_async_defs(ast.parse(src)), _SCAN_NAMES)
            assert violations, f"우회 {label!r}를 검출하지 못했다"
