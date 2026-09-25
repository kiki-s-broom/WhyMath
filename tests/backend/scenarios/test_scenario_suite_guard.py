"""SCENARIO-001~010 회귀 스위트의 **자기 규율을 기계로 집행**한다 (EOS-119 · hermetic).

`test_phase2_scenario_regression_suite.py`는 실 PG가 있어야 도는 통합 테스트다. 그 파일의 *형태*에
관한 약속 — ①10종이 각각 독립 테스트로 존재한다 ②학습자 상태를 DB에 직접 쓰지 않는다
③코드 갭을 `skip`/`xfail`로 위장하지 않는다 — 은 PG 없이도 AST로 판정할 수 있으므로, 이 가드는
PR마다 도는 hermetic backend 잡에서 먼저 본다(통합 잡이 무너져도 형태 계약은 따로 남는다).

검사 방식은 Week 1 가드(`tests/backend/api/test_week1_gate_no_learner_writes.py`)와 같다 — 이름의
*등장*이 아니라 *생성* 노드를 보고, 원시 SQL은 `text()`에 넘어가는 리터럴의 **동사**로 본다.
학습자 상태 모델 목록은 그 가드에서 **읽어 온다**(복제하면 한쪽만 갱신될 때 조용히 갈라진다).

**스캔 0건은 실패** — 대상 파일을 못 찾거나 순회가 아무것도 못 보면 공허하게 통과하므로,
콘텐츠 시딩(`Problem.from_schema`)이 보이는지와 `text()` SQL이 1건 이상인지를 함께 단언한다.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import re
from types import ModuleType

import pytest

_SUITE = pathlib.Path(__file__).with_name("test_phase2_scenario_regression_suite.py")
_WEEK1_GUARD = (
    pathlib.Path(__file__).resolve().parents[1] / "api" / "test_week1_gate_no_learner_writes.py"
)
_SCENARIO_IDS = tuple(f"{n:03d}" for n in range(1, 11))
_WRITE_VERBS = ("INSERT", "UPDATE", "UPSERT", "MERGE")
#: 허용되는 `pytest.skip` 호출 수 — PG 미도달 판정 불가 1곳(`_begin`)뿐이다.
_ALLOWED_SKIP_CALLS = 1


def _load_week1_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_scenario_guard_week1", _WEEK1_GUARD)
    assert spec is not None and spec.loader is not None, _WEEK1_GUARD
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def suite_tree() -> ast.Module:
    """스위트 소스의 AST — 파일 부재는 실패다(스캔 0건 금지)."""
    assert _SUITE.is_file(), f"시나리오 스위트가 없다: {_SUITE}"
    source = _SUITE.read_text(encoding="utf-8")
    assert source.strip(), f"시나리오 스위트가 비었다: {_SUITE}"
    return ast.parse(source)


def _test_functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }


def test_each_scenario_is_its_own_test(suite_tree: ast.Module) -> None:
    """SCENARIO-001~010이 **각각 하나의** 테스트 함수로 존재하고 docstring이 식별자를 단다."""
    funcs = _test_functions(suite_tree)
    for sid in _SCENARIO_IDS:
        owners = [name for name in funcs if re.match(rf"test_scenario_{sid}_\w+$", name)]
        assert len(owners) == 1, f"SCENARIO-{sid}의 테스트가 {len(owners)}개다(기대 1): {owners}"
        doc = ast.get_docstring(funcs[owners[0]]) or ""
        assert doc.startswith(f"SCENARIO-{sid} "), (
            f"{owners[0]}의 docstring이 `SCENARIO-{sid}`로 시작하지 않는다 — 대조표·회귀 주입 "
            "하네스가 이 식별자로 테스트를 찾는다."
        )
    extra = [n for n in funcs if not re.match(r"test_scenario_0(0[1-9]|10)_\w+$", n)]
    assert not extra, f"시나리오 식별자가 없는 테스트가 섞였다: {extra}"


def test_suite_is_integration_marked(suite_tree: ast.Module) -> None:
    """모듈 전체가 `integration` 마커 — CI `backend-migrations` 잡의 `-m integration`이 수집한다."""
    marks = [
        node
        for node in suite_tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets)
    ]
    assert len(marks) == 1, "모듈 수준 `pytestmark`가 정확히 1건이어야 한다."
    assert ast.unparse(marks[0].value) == "pytest.mark.integration", ast.unparse(marks[0].value)


def test_gaps_are_not_disguised_as_skips(suite_tree: ast.Module) -> None:
    """코드 갭을 `skip`·`xfail`로 위장하지 않는다 — 정직한 공백은 현행 동작 단언으로 동결한다."""
    skip_calls = 0
    for node in ast.walk(suite_tree):
        if isinstance(node, ast.Attribute) and node.attr in ("xfail", "skipif"):
            pytest.fail(f"`{ast.unparse(node)}`가 있다 — 공백은 현행 동작 단언으로 동결한다.")
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "pytest.skip":
            skip_calls += 1
    assert skip_calls == _ALLOWED_SKIP_CALLS, (
        f"`pytest.skip` 호출이 {skip_calls}건이다(허용 {_ALLOWED_SKIP_CALLS} — PG 미도달 판정 불가 "
        "1곳). 시나리오 단위 skip은 코드 갭의 위장이다."
    )


def test_suite_constructs_no_learner_state_rows(suite_tree: ast.Module) -> None:
    """스위트가 학습자 상태 ORM 행을 하나도 만들지 않는다(모델 목록은 Week 1 가드가 정본)."""
    week1 = _load_week1_guard()
    learner_models: frozenset[str] = week1._LEARNER_STATE_MODELS
    made: set[str] = week1._constructed_names(suite_tree)
    assert "Problem" in made, "AST 순회가 콘텐츠 시딩을 못 봤다 — 이 가드는 무효다(0건=실패)."
    offenders = sorted(made & learner_models)
    assert not offenders, f"스위트가 학습자 상태를 DB에 직접 만든다: {offenders}"


#: SQL 문자열을 받아 DB로 넘기는 호출 — `text()`(SQLAlchemy)와 스위트의 관측 헬퍼 `_read_rows`.
#: Week 1 가드의 수집기는 `text("...")` 리터럴만 본다. 스위트는 `_read_rows("SELECT ...")`로
#: SQL을 넘기고 헬퍼 안에서 `text(sql)`(변수)를 부르므로, 그 수집기만 쓰면 `_read_rows`에 넘긴
#: SQL이 **통째로 검사 밖**이 된다(2026-09-24 주입 실측: `_read_rows`에 INSERT를 넣어도 GREEN).
_SQL_SINKS = frozenset({"text", "_read_rows"})


def _sql_literals(tree: ast.Module) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        first = node.args[0]
        if name in _SQL_SINKS and isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.append(first.value)
    return found


def test_suite_raw_sql_is_read_or_teardown_only(suite_tree: ast.Module) -> None:
    """스위트가 DB에 넘기는 원시 SQL은 관측(SELECT)·정리(DELETE)뿐이다."""
    sql = _sql_literals(suite_tree)
    # 스캔 변별력 — 두 싱크가 **각각** 최소 1건씩 보여야 한다(한쪽만 보이면 다른 쪽은 미검사).
    assert any(s.lstrip().upper().startswith("SELECT") for s in sql), sql
    assert any(s.lstrip().upper().startswith("DELETE") for s in sql), sql
    bad = [s for s in sql if any(v in s.upper() for v in _WRITE_VERBS)]
    assert not bad, f"관측·정리 목적 밖의 SQL 쓰기 동사가 있다: {bad}"
