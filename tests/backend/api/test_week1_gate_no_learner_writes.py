"""Week 1 Gate 판정 하네스의 **자기 규율을 기계로 집행**한다 — 주장이 아니라 검사.

`test_week1_gate_closed_loop.py`는 "학습자 상태를 DB에 직접 쓰지 않는다"를 전제로 게이트를
판정한다. 그 전제가 산문 주석으로만 있으면, 나중에 누군가 단계 하나를 통과시키려고
`session.add(ProblemAttempt(...))` 한 줄을 넣는 순간 **판정은 초록인데 게이트 문면은 거짓**이 된다.
이 모듈이 그 한 줄을 막는다.

검사 방식은 **문자열 열거가 아니라 산출물 검사**다(CLAUDE.md "금지 패턴 열거 대신 산출물 검사"):
- 금지 이름을 grep하지 않는다 — 학습자 상태 모델을 **생성**하는 노드(`X(...)`·`X.from_schema(...)`)를
  AST에서 찾는다. 읽기(`select(UserProfile)`)는 통과해야 하므로 *이름의 등장*으로는 판정할 수 없다.
- 원시 SQL은 **동사**로 본다 — 정리(`DELETE`)는 허용하고 `INSERT`/`UPDATE`/`UPSERT`는 거부한다.

**스캔 0건은 실패**로 계상한다 — 대상 모듈을 못 찾거나 AST 순회가 아무것도 못 보면 이 가드는
공허하게 통과할 수 있다. 그래서 ①모듈 존재 ②콘텐츠 시딩 호출이 실제로 보이는지 ③게이트 7단계
라벨이 전부 남아 있는지를 함께 단언한다(단계가 조용히 사라지면 판정 범위가 줄어든다).
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_HARNESS = pathlib.Path(__file__).with_name("test_week1_gate_closed_loop.py")

# 학습자 상태 좌석 — 이 모델을 *생성*하면 게이트 문면("DB 직접 수정 없이")이 깨진다.
# 콘텐츠 좌석(Concept·Problem·ProblemConcept)은 원 문서 §4가 허용한 전제라 목록에 없다.
_LEARNER_STATE_MODELS = frozenset(
    {
        "UserProfile",
        "ProblemAttempt",
        "AttemptEvent",
        "ConceptMasteryHistory",
        "SkillMasteryHistory",
        "MisconceptionHypothesis",
        "Dialogue",
        "DialogueTurn",
        "LearnerState",
        "LearningStateTransition",
        "Assessment",
    }
)

# 게이트 7단계 — 판정 하네스가 실제로 남기는 라벨. 하나라도 사라지면 판정 범위가 줄어든다.
_REQUIRED_STEPS = (
    "1-user-created",
    "2-diagnosis",
    "3-concept-selected",
    "4-problem-fetched",
    "5-wrong-answer-submitted",
    "6-mastery-changed",
    "7-next-problem-recommended",
)

_WRITE_VERBS = ("INSERT", "UPDATE", "UPSERT", "MERGE")


@pytest.fixture(scope="module")
def harness_tree() -> ast.Module:
    """판정 하네스 소스의 AST — 모듈 부재는 실패다(스캔 0건 금지)."""
    assert _HARNESS.is_file(), f"판정 하네스가 없다: {_HARNESS}"
    source = _HARNESS.read_text(encoding="utf-8")
    assert source.strip(), f"판정 하네스가 비었다: {_HARNESS}"
    return ast.parse(source)


def _constructed_names(tree: ast.Module) -> set[str]:
    """AST에서 *생성*되는 이름들 — `X(...)`와 `X.from_schema(...)` 두 형태를 모은다.

    `select(UserProfile)`처럼 인자로 *언급*되는 것은 포함하지 않는다(읽기는 허용). 즉 이 함수는
    "무엇이 쓰였는가"가 아니라 "무엇이 만들어졌는가"를 돌려준다.
    """
    made: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            made.add(func.id)
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            # `Concept.from_schema(...)` 형태 — 생성자 역할을 하는 클래스메서드.
            made.add(func.value.id)
    return made


def test_harness_constructs_no_learner_state_rows(harness_tree: ast.Module) -> None:
    """판정 하네스가 학습자 상태 ORM 행을 하나도 만들지 않는다."""
    made = _constructed_names(harness_tree)
    # 스캔 변별력 확인 — 순회가 살아 있으면 콘텐츠 좌석은 반드시 보인다(0건이면 가드가 공허하다).
    assert "Concept" in made, "AST 순회가 콘텐츠 시딩을 못 봤다 — 이 가드는 무효다(0건=실패)."
    offenders = sorted(made & _LEARNER_STATE_MODELS)
    assert not offenders, (
        "판정 하네스가 학습자 상태를 DB에 직접 만든다 — 게이트 문면(DB 직접 수정 없이)이 "
        f"깨진다: {offenders}. 그 상태는 HTTP 호출의 부수효과로만 생겨야 한다."
    )


def _raw_sql_literals(tree: ast.Module) -> list[str]:
    """`text("...")` 호출에 넘어간 SQL 문자열만 모은다.

    리터럴 *전수*를 훑지 않는 이유: 산문(docstring)에 "upsert" 같은 낱말이 있으면 정상 상태에서
    오탐이 난다 — 그러면 사람이 가드를 끈다. 검사 대상은 "코드에 적힌 글자"가 아니라
    **DB에 실제로 넘어가는 SQL**이므로, 호출 구조로 좁히는 것이 변별력을 지키는 방향이다.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name != "text":
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.append(arg.value)
    return found


def test_harness_raw_sql_is_teardown_only(harness_tree: ast.Module) -> None:
    """판정 하네스가 DB에 넘기는 원시 SQL은 정리(DELETE/SELECT)뿐 — 쓰기 동사는 거부한다."""
    sql = _raw_sql_literals(harness_tree)
    # 스캔 0건은 실패 — `text()` 호출을 하나도 못 찾았다면 이 가드는 무엇도 보지 않은 것이다.
    assert sql, "`text()`에 넘어가는 SQL을 하나도 못 찾았다 — 이 가드의 스캔이 실패했다(0건=실패)."
    bad = [s for s in sql if any(v in s.upper() for v in _WRITE_VERBS)]
    assert not bad, f"정리 목적 밖의 SQL 쓰기 동사가 있다: {bad}"


def test_harness_still_judges_all_seven_steps(harness_tree: ast.Module) -> None:
    """게이트 7단계 라벨이 전부 살아 있다 — 단계가 사라지면 판정 범위가 조용히 줄어든다."""
    literals = {
        node.value
        for node in ast.walk(harness_tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    missing = [s for s in _REQUIRED_STEPS if s not in literals]
    assert not missing, f"사라진 단계: {missing} — 7단계 전건이 판정 대상이다(원 문서 §4)."
