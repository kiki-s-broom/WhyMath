"""학생 대면 LLM 발화의 **검증 통과** 동결 (ARCH-60).

무엇을 지키는가
--------------
설계 규율 한 줄: **학생에게 나가는 응답은 검증을 통과한 것만이다.** LLM이 만든 문자열은
하네스 verify 의무(§3.1)·정답 억제 백스톱(§3.4)·프로즈 정책 게이트·L4 톤필터를 차례로
통과한 뒤에만 학생 대면 발화로 승격된다.

Phase 2 실행계획 P-10(AI Tutor v1)이 요구하는 주입 3축 중 **세 번째 축**이다. 자매 축은
이미 서 있다 — ①LLM→mastery 경로는 `test_llm_state_authority_boundary.py`(ARCH-59)가,
②라우터 우회 직접 호출은 `test_provider_seat_contract.py`(ARCH-46)가 동결한다. 이 축만
소유자가 0이었다: 게이트는 코드에 실재하는데(2026-09-19 실측 5좌석) **그 게이트를 지우거나
반환값을 버려도 아무것도 빨개지지 않는 상태**였다.

동결하는 7절
-----------
  A. **최종 노출 게이트 도달** — `run_wh1_primary_turn`이 돌려주는 값은 `None`(폴백) 아니면
     `filter_tone`이 만든 이름뿐이다. 원문 `utterance`를 그대로 반환하는 형태를 막는다.
  B. **프로즈 게이트 반환값 소비** — `gate_policy_prose`의 결과가 *분기 조건*으로 쓰이고 그
     분기가 폴백(`return None`)으로 간다. 호출만 하고 결과를 버리는 형태를 막는다.
  C. **verify 의무의 선행** — `_exec_end_turn`의 `verify_called` 거부 분기가 `state.utterance`
     산출보다 **앞**에 있다. 게이트가 남아 있어도 뒤로 밀리면 발화는 이미 나간 뒤다.
  D. **정답 억제 백스톱** — `_uses_explicit_utterance`의 반환식이 억제항을 `and not …` 으로
     품고 있고, 억제 대상 verdict 집합이 baseline 그대로다.
  E. **Polya 엔진 최종 게이트** — `PolyaCoach.coach`가 `filter_tone` 산출물을 돌려주고 LLM
     원문(`llm.generate` 결과)은 반환 튜플에 실리지 않는다.
  F. **톤 게이트 좌석 전수** — `filter_tone`을 *호출*하는 모듈 집합을 baseline으로 동결한다.
     학생 대면 LLM 발화 좌석이 새로 생기면 이 대조가 먼저 빨개진다(의도적 추가면 baseline을
     갱신하라 — 조용히 늘어나는 것만 막는다).
  G. **승격 값의 출처** — `_wh1_primary_decision_or`가 `prompt`에 넣는 값은
     `run_wh1_primary_turn`이 돌려준 이름이다. ARCH-59 ①이 *어떤 키*를 갈아끼우는지 동결한다면
     이 절은 *그 값이 어디서 왔는지*를 동결한다 — 두 절이 함께 있어야 "검증을 통과한 문자열만
     승격된다"가 성립한다.

판정 방식 — 문자열이 아니라 **구성된 산출물**
--------------------------------------------
`test_llm_state_authority_boundary.py`(ARCH-59)·`test_proxy_ca_optional.py`(AST 거버넌스 선례)를
따른다. 금지 문자열 열거는 표기 변형에서 뚫리므로 `ast`로 구성된 결과를 본다 — 반환문의 값
노드, 분기 조건이 참조하는 이름, 호출 노드의 callee.

**의존성 제약(중요)**: 이 파일이 도는 `infra-contracts` 잡은 백엔드 패키지를 설치하지 않는다
(실측 7종: pytest·pytest-asyncio·pytest-randomly·pyyaml·sqlalchemy·ruff·black). 따라서
`import whymath_backend`를 쓸 수 없다 — 전부 `ast` + 표준 라이브러리로만 판정한다.

**스캔 0건은 실패다** — 대상을 하나도 못 찾은 전수 가드는 공허하게 통과한다. 일곱 절 모두
대상 실재를 먼저 단언한다.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _REPO_ROOT / "src" / "backend" / "whymath_backend"

# ── 좌석 ──────────────────────────────────────────────────────────────
_PRIMARY_FILE = _BACKEND / "harness" / "wh1_primary.py"
_PRIMARY_FUNC = "run_wh1_primary_turn"
_LOOP_FILE = _BACKEND / "harness" / "wh1_loop.py"
_END_TURN_FUNC = "_exec_end_turn"
_EXPLICIT_PREDICATE = "_uses_explicit_utterance"
_POLYA_FILE = _BACKEND / "l4" / "polya" / "engine.py"
_POLYA_FUNC = "coach"
_PROMOTION_FILE = _BACKEND / "api" / "coach.py"
_PROMOTION_FUNC = "_wh1_primary_decision_or"

# ── 게이트 이름 ───────────────────────────────────────────────────────
_TONE_GATE = "filter_tone"  # L4 톤필터 — 노출 직전 최종 게이트
_PROSE_GATE = "gate_policy_prose"  # 정책 자유발화 정답-안전 게이트
_LLM_GENERATE = "generate"  # LLM seam — 이 결과가 *원문*이다
_VERIFY_FLAG = "verify_called"  # verify 의무(§3.1) 플래그
_SUPPRESSED_CONST = "_ANSWER_SUPPRESSED_VERDICTS"
_PRODUCER = "run_wh1_primary_turn"  # 검증을 마친 발화를 돌려주는 유일한 생산자
_UTTERANCE_FIELD = "prompt"  # 학생 대면 발화 본문 필드(ARCH-59와 같은 좌석)

# 2026-09-19 실측 baseline — `filter_tone`을 *호출*하는 프로덕션 모듈 전수.
# 재수출(`l4/__init__.py`)·docstring 언급은 호출이 아니므로 대상이 아니다.
_TONE_GATE_SEATS = frozenset({"harness/wh1_primary.py", "l4/polya/engine.py"})

# 2026-09-19 실측 baseline — 정책 명시 발화를 억제하는 verdict 집합(§3.4).
# 줄어들면 LLM이 정답을 실어 보낼 수 있는 턴이 늘어난다.
_SUPPRESSED_VERDICTS_BASELINE = frozenset({"incorrect", "unverifiable"})


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _find_func(tree: ast.Module, name: str, *, where: Path) -> ast.AST:
    """이름으로 함수를 찾는다 — 못 찾으면 스캔이 깨진 것이므로 곧바로 실패(스캔 0건 방어)."""
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    assert found, (
        f"{name!r}를 {where.name}에서 못 찾았다 — 스캔이 깨졌다"
        " (함수명이 바뀌었으면 이 가드의 좌석도 함께 옮겨야 한다)"
    )
    return found[0]


def _own_nodes(func: ast.AST) -> list[ast.AST]:
    """함수 *자신*의 노드 — 중첩 정의(내부 함수·클래스) 본문은 제외한다.

    `ast.walk`를 그대로 쓰면 내부 헬퍼의 `return`이 바깥 함수의 반환으로 계상돼 판정이
    흐려진다. 여기서는 중첩 정의를 만나면 그 가지로 내려가지 않는다.
    """
    collected: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        collected.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return collected


def _callee_name(node: ast.AST) -> str | None:
    """호출 노드의 callee 이름 — `await f(...)`·`obj.f(...)` 둘 다 푼다."""
    if isinstance(node, ast.Await):
        node = node.value
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _names_bound_from_call(
    func: ast.AST, callee: str, *, tuple_index: int | None = None
) -> set[str]:
    """`callee(...)` 결과가 대입된 이름들.

    `tuple_index`를 주면 튜플 언패킹에서 그 위치의 이름만 취한다 —
    `filtered, report = filter_tone(x)`에서 *필터된 텍스트*는 0번이고 report는 게이트 산출물이
    아니다(둘을 섞으면 `return report`가 절 A를 통과한다).
    """
    names: set[str] = set()
    for node in _own_nodes(func):
        if not isinstance(node, ast.Assign) or _callee_name(node.value) != callee:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Tuple):
                elements = list(target.elts)
                picked = (
                    [elements[tuple_index]]
                    if tuple_index is not None and tuple_index < len(elements)
                    else elements
                )
                names.update(e.id for e in picked if isinstance(e, ast.Name))
    return names


def _returns(func: ast.AST) -> list[ast.Return]:
    return [node for node in _own_nodes(func) if isinstance(node, ast.Return)]


def _is_none(value: ast.expr | None) -> bool:
    return value is None or (isinstance(value, ast.Constant) and value.value is None)


def _refers_to(expr: ast.AST, names: set[str]) -> bool:
    return any(isinstance(n, ast.Name) and n.id in names for n in ast.walk(expr))


def _mentions_attribute(expr: ast.AST, attr: str) -> bool:
    return any(isinstance(n, ast.Attribute) and n.attr == attr for n in ast.walk(expr))


def _body_returns_none(body: list[ast.stmt]) -> bool:
    """분기 본문이 폴백(`return None`)으로 빠지는가 — 중첩 정의는 보지 않는다."""
    for stmt in body:
        for node in [stmt, *_own_nodes(stmt)]:
            if isinstance(node, ast.Return) and _is_none(node.value):
                return True
    return False


def _assigns_attribute(node: ast.AST, attr: str) -> bool:
    return isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Attribute) and t.attr == attr for t in node.targets
    )


# ──────────────────────────────────────────────────────────────────────
# A. 최종 노출 게이트 도달 — 돌려주는 것은 `None` 아니면 톤필터 산출물뿐
# ──────────────────────────────────────────────────────────────────────
class TestPrimaryReturnsOnlyToneFilteredText:
    """A. `run_wh1_primary_turn`의 성공 경로 반환값은 반드시 게이트를 거친 이름이다."""

    def test_tone_gate_call_was_found(self) -> None:
        """스캔 0건 방어 — 톤필터 호출을 못 찾으면 아래 검사가 공허하게 통과한다."""
        func = _find_func(_parse(_PRIMARY_FILE), _PRIMARY_FUNC, where=_PRIMARY_FILE)
        assert _names_bound_from_call(func, _TONE_GATE, tuple_index=0), (
            f"{_PRIMARY_FUNC!r} 안에서 {_TONE_GATE!r} 호출 결과 대입을 한 건도 못 찾았다 —"
            " 최종 노출 게이트가 사라졌거나 스캔이 깨졌다"
        )

    def test_returns_were_found(self) -> None:
        func = _find_func(_parse(_PRIMARY_FILE), _PRIMARY_FUNC, where=_PRIMARY_FILE)
        assert _returns(func), f"{_PRIMARY_FUNC!r}에서 return을 한 건도 못 찾았다 — 스캔이 깨졌다"

    def test_every_non_fallback_return_is_gated(self) -> None:
        func = _find_func(_parse(_PRIMARY_FILE), _PRIMARY_FUNC, where=_PRIMARY_FILE)
        gated = _names_bound_from_call(func, _TONE_GATE, tuple_index=0)
        for node in _returns(func):
            if _is_none(node.value):
                continue  # 결정론 폴백 — 학생에게 LLM 문자열이 나가지 않는다.
            assert isinstance(node.value, ast.Name) and node.value.id in gated, (
                f"{_PRIMARY_FILE.name}:{node.lineno} — 학생 대면 발화가 {_TONE_GATE!r}를 거치지"
                f" 않은 값으로 반환된다(게이트 산출 이름: {sorted(gated)}). 미검증 응답 노출이다"
            )


# ──────────────────────────────────────────────────────────────────────
# B. 프로즈 게이트 — 반환값이 실제로 분기 조건이다(호출만 하고 버리기 금지)
# ──────────────────────────────────────────────────────────────────────
class TestProseGateVerdictIsActuallyEnforced:
    """B. `gate_policy_prose` 거부 사유가 폴백 분기를 구동한다."""

    def test_prose_gate_call_was_found(self) -> None:
        func = _find_func(_parse(_PRIMARY_FILE), _PRIMARY_FUNC, where=_PRIMARY_FILE)
        assert _names_bound_from_call(func, _PROSE_GATE), (
            f"{_PRIMARY_FUNC!r} 안에서 {_PROSE_GATE!r} 호출 결과 대입을 못 찾았다 —"
            " 정책 자유발화 게이트가 사라졌거나 스캔이 깨졌다"
        )

    def test_prose_gate_result_drives_a_fallback_branch(self) -> None:
        func = _find_func(_parse(_PRIMARY_FILE), _PRIMARY_FUNC, where=_PRIMARY_FILE)
        verdicts = _names_bound_from_call(func, _PROSE_GATE)
        enforced = [
            node
            for node in _own_nodes(func)
            if isinstance(node, ast.If)
            and _refers_to(node.test, verdicts)
            and _body_returns_none(node.body)
        ]
        assert enforced, (
            f"{_PROSE_GATE!r}의 거부 사유({sorted(verdicts)})가 폴백 분기를 구동하지 않는다 —"
            " 게이트를 호출만 하고 결과를 버리면 거부된 발화가 그대로 학생에게 나간다"
        )


# ──────────────────────────────────────────────────────────────────────
# C. verify 의무(§3.1)가 발화 산출보다 **앞**에 있다
# ──────────────────────────────────────────────────────────────────────
class TestVerifyObligationPrecedesUtterance:
    """C. 풀이 제출 턴의 verify 미호출 거부는 `state.utterance` 대입 전에 일어난다."""

    def test_utterance_assignment_was_found(self) -> None:
        """스캔 0건 방어 — 발화 산출 지점을 못 찾으면 순서 판정이 성립하지 않는다."""
        func = _find_func(_parse(_LOOP_FILE), _END_TURN_FUNC, where=_LOOP_FILE)
        assert [n for n in _own_nodes(func) if _assigns_attribute(n, "utterance")], (
            f"{_END_TURN_FUNC!r}에서 발화 대입(`state.utterance = ...`)을 못 찾았다 —"
            " 스캔이 깨졌다"
        )

    def test_verify_guard_exists_and_rejects(self) -> None:
        func = _find_func(_parse(_LOOP_FILE), _END_TURN_FUNC, where=_LOOP_FILE)
        guards = [
            node
            for node in _own_nodes(func)
            if isinstance(node, ast.If)
            and _mentions_attribute(node.test, _VERIFY_FLAG)
            and any(isinstance(n, ast.Return) for n in [*node.body, *_own_nodes(node)])
        ]
        assert guards, (
            f"{_END_TURN_FUNC!r}에 verify 의무 거부 분기(`{_VERIFY_FLAG}` 검사 + return)가 없다 —"
            " 풀이 제출 턴이 검증 없이 발화할 수 있다(§3.1 미집행)"
        )

    def test_verify_guard_comes_before_the_utterance(self) -> None:
        func = _find_func(_parse(_LOOP_FILE), _END_TURN_FUNC, where=_LOOP_FILE)
        guard_lines = [
            node.lineno
            for node in _own_nodes(func)
            if isinstance(node, ast.If)
            and _mentions_attribute(node.test, _VERIFY_FLAG)
            and any(isinstance(n, ast.Return) for n in [*node.body, *_own_nodes(node)])
        ]
        assign_lines = [
            node.lineno for node in _own_nodes(func) if _assigns_attribute(node, "utterance")
        ]
        assert guard_lines and assign_lines
        assert min(guard_lines) < min(assign_lines), (
            "verify 의무 거부 분기가 발화 산출보다 뒤에 있다 — 게이트가 남아 있어도 발화는"
            " 이미 만들어진 뒤라 §3.1이 집행되지 않는다"
        )


# ──────────────────────────────────────────────────────────────────────
# D. 정답 억제 백스톱(§3.4)
# ──────────────────────────────────────────────────────────────────────
class TestAnswerSuppressionBackstop:
    """D. 오답·막힘 턴에서 정책 명시 발화를 존중하지 않는다."""

    def test_suppressed_verdicts_baseline_is_intact(self) -> None:
        """억제 대상 verdict 집합 동결 — 줄어들면 정답이 새어 나갈 턴이 늘어난다."""
        tree = _parse(_LOOP_FILE)
        literals: set[str] = set()
        found = False
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            if not any(isinstance(t, ast.Name) and t.id == _SUPPRESSED_CONST for t in targets):
                continue
            found = True
            value = node.value
            assert isinstance(value, (ast.Tuple, ast.List, ast.Set)), (
                f"{_SUPPRESSED_CONST}가 리터럴 시퀀스가 아니다 — 정적으로 내용을 알 수 없으면"
                " 이 동결은 성립하지 않는다"
            )
            literals = {e.value for e in value.elts if isinstance(e, ast.Constant)}
        assert found, f"{_SUPPRESSED_CONST}를 {_LOOP_FILE.name}에서 못 찾았다 — 스캔이 깨졌다"
        assert literals == _SUPPRESSED_VERDICTS_BASELINE, (
            f"정답 억제 대상 verdict 집합이 baseline과 다르다: {sorted(literals)} !="
            f" {sorted(_SUPPRESSED_VERDICTS_BASELINE)} — 줄었다면 그 턴에서 LLM 명시 발화가"
            " 정답을 실어 학생에게 나갈 수 있다"
        )

    def test_predicate_conjoins_the_suppression_term(self) -> None:
        func = _find_func(_parse(_LOOP_FILE), _EXPLICIT_PREDICATE, where=_LOOP_FILE)
        suppressed = {
            target.id
            for node in _own_nodes(func)
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Compare)
            and _refers_to(node.value, {_SUPPRESSED_CONST})
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        assert suppressed, (
            f"{_EXPLICIT_PREDICATE!r}에서 {_SUPPRESSED_CONST} 대조 결과 대입을 못 찾았다 —"
            " 억제 판정이 사라졌거나 스캔이 깨졌다"
        )
        returns = _returns(func)
        assert returns, f"{_EXPLICIT_PREDICATE!r}에서 return을 못 찾았다 — 스캔이 깨졌다"
        for node in returns:
            value = node.value
            assert isinstance(value, ast.BoolOp) and isinstance(value.op, ast.And), (
                f"{_EXPLICIT_PREDICATE!r}의 반환식이 and 결합이 아니다 — 억제항이 선택적으로"
                " 바뀌면(or) 오답 턴에서도 정책 명시 발화가 존중된다"
            )
            assert any(
                isinstance(v, ast.UnaryOp)
                and isinstance(v.op, ast.Not)
                and _refers_to(v.operand, suppressed)
                for v in value.values
            ), (
                f"{_EXPLICIT_PREDICATE!r}의 반환식에 `not <억제>` 항이 없다 — 정답 억제"
                " 백스톱(§3.4)이 집행되지 않는다"
            )


# ──────────────────────────────────────────────────────────────────────
# E. Polya 엔진 — LLM 원문이 아니라 톤필터 산출물을 돌려준다
# ──────────────────────────────────────────────────────────────────────
class TestPolyaCoachReturnsFilteredText:
    """E. `PolyaCoach.coach`는 LLM 원문을 그대로 돌려주지 않는다."""

    def test_raw_and_gated_names_were_found(self) -> None:
        func = _find_func(_parse(_POLYA_FILE), _POLYA_FUNC, where=_POLYA_FILE)
        assert _names_bound_from_call(
            func, _LLM_GENERATE
        ), f"{_POLYA_FUNC!r}에서 LLM 원문 대입(`{_LLM_GENERATE}`)을 못 찾았다 — 스캔이 깨졌다"
        assert _names_bound_from_call(func, _TONE_GATE, tuple_index=0), (
            f"{_POLYA_FUNC!r}에서 {_TONE_GATE!r} 산출 대입을 못 찾았다 — 최종 게이트가"
            " 사라졌거나 스캔이 깨졌다"
        )

    def test_returns_gated_text_and_never_the_raw_llm_output(self) -> None:
        func = _find_func(_parse(_POLYA_FILE), _POLYA_FUNC, where=_POLYA_FILE)
        raw = _names_bound_from_call(func, _LLM_GENERATE)
        gated = _names_bound_from_call(func, _TONE_GATE, tuple_index=0)
        returns = _returns(func)
        assert returns, f"{_POLYA_FUNC!r}에서 return을 못 찾았다 — 스캔이 깨졌다"
        for node in returns:
            returned = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            assert returned & gated, (
                f"{_POLYA_FILE.name}:{node.lineno} — 반환값에 {_TONE_GATE!r} 산출물"
                f"({sorted(gated)})이 없다. 미검증 응답 노출이다"
            )
            assert not (returned & raw), (
                f"{_POLYA_FILE.name}:{node.lineno} — LLM 원문({sorted(returned & raw)})이"
                " 그대로 반환된다. 톤필터를 우회한 학생 노출이다"
            )


# ──────────────────────────────────────────────────────────────────────
# F. 톤 게이트 좌석 전수 동결
# ──────────────────────────────────────────────────────────────────────
class TestToneGateSeatBaseline:
    """F. `filter_tone`을 호출하는 모듈 집합은 baseline 그대로다."""

    @staticmethod
    def _seats() -> set[str]:
        seats: set[str] = set()
        for path in sorted(_BACKEND.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = _parse(path)
            if any(_callee_name(n) == _TONE_GATE for n in ast.walk(tree)):
                seats.add(path.relative_to(_BACKEND).as_posix())
        return seats

    def test_scan_found_seats(self) -> None:
        """스캔 0건 방어 — 좌석을 못 찾은 전수 가드는 공허하게 통과한다."""
        assert self._seats(), (
            f"{_TONE_GATE!r} 호출 좌석을 한 건도 못 찾았다 — 최종 게이트가 통째로 사라졌거나"
            " 스캔이 깨졌다"
        )

    def test_seats_match_baseline(self) -> None:
        seats = self._seats()
        assert seats == set(_TONE_GATE_SEATS), (
            f"학생 대면 톤 게이트 좌석이 baseline과 다르다: {sorted(seats)} !="
            f" {sorted(_TONE_GATE_SEATS)} — 새 학생 대면 LLM 발화 좌석이 생겼다면 이 가드의"
            " 절 A·E에 해당하는 검사도 함께 만들고 baseline을 갱신하라"
        )


# ──────────────────────────────────────────────────────────────────────
# G. 승격 값의 출처 — 검증을 마친 생산자가 돌려준 이름만 승격된다
# ──────────────────────────────────────────────────────────────────────
class TestPromotedValueComesFromTheValidatedProducer:
    """G. `prompt`에 들어가는 값은 `run_wh1_primary_turn`의 반환 이름이다."""

    @staticmethod
    def _promotion_pairs() -> list[tuple[str, ast.expr]]:
        func = _find_func(_parse(_PROMOTION_FILE), _PROMOTION_FUNC, where=_PROMOTION_FILE)
        pairs: list[tuple[str, ast.expr]] = []
        for node in _own_nodes(func):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Attribute) and node.func.attr == "model_copy"):
                continue
            update = next((kw.value for kw in node.keywords if kw.arg == "update"), None)
            assert isinstance(update, ast.Dict), (
                "발화 승격이 리터럴이 아닌 update= 로 필드를 바꾼다 — 무엇이 승격되는지 정적으로"
                " 알 수 없으면 이 경계는 검사 불가다"
            )
            for key, value in zip(update.keys, update.values, strict=True):
                assert isinstance(key, ast.Constant) and isinstance(key.value, str)
                pairs.append((key.value, value))
        return pairs

    def test_promotion_site_was_found(self) -> None:
        assert self._promotion_pairs(), (
            f"{_PROMOTION_FUNC!r}에서 발화 승격(`model_copy(update=...)`)을 못 찾았다 —"
            " 스캔이 깨졌다"
        )

    def test_producer_binding_was_found(self) -> None:
        func = _find_func(_parse(_PROMOTION_FILE), _PROMOTION_FUNC, where=_PROMOTION_FILE)
        assert _names_bound_from_call(func, _PRODUCER), (
            f"{_PROMOTION_FUNC!r}에서 {_PRODUCER!r} 호출 결과 대입을 못 찾았다 —"
            " 검증된 생산자를 거치지 않는 승격 경로가 생겼거나 스캔이 깨졌다"
        )

    def test_utterance_value_comes_from_the_producer(self) -> None:
        func = _find_func(_parse(_PROMOTION_FILE), _PROMOTION_FUNC, where=_PROMOTION_FILE)
        produced = _names_bound_from_call(func, _PRODUCER)
        for key, value in self._promotion_pairs():
            if key != _UTTERANCE_FIELD:
                continue  # 키 집합 자체는 ARCH-59 ①이 동결한다.
            assert isinstance(value, ast.Name) and value.id in produced, (
                f"학생 대면 발화 {key!r}에 {_PRODUCER!r}의 반환값이 아닌 값이 승격된다"
                f"(검증된 이름: {sorted(produced)}) — 게이트를 거치지 않은 문자열이 학생에게"
                " 나가는 경로다"
            )
