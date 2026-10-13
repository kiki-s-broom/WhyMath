"""시도 버전 고정 배선 동결 (EOS-47) — "계약을 만들었다"가 아니라 "모든 적재 경로가 부른다".

`problem_attempt`를 만드는 서빙 경로는 셋이다(`api/me.py::submit_attempt` ·
`api/coach.py::_complete_problem` · `api/coach.py::_record_first_wrong_submission`). 컬럼과 헬퍼를
만들어도 이 중 하나가 호출을 빼먹으면 그 경로의 시도는 판을 못 가리킨다 — 그리고 그 누락은 어떤
기능 테스트도 빨갛게 만들지 않는다(NULL은 정상 값이므로). 그래서 **산출물(AST)**을 검사한다:

- `ProblemAttempt(...)` 생성 노드가 `problem_version_id`·`evaluation_context` 키워드를 넘기는가.
- 그 값이 **`resolve_attempt_version_pin` 결과에서 온 것인가**(상수·다른 변수가 아니라). 키워드만
  있고 값이 `None` 리터럴이면 배선한 것처럼 보이지만 아무것도 고정하지 않는다.
- `ProblemAttempt.from_schema(...)` 경유 생성은 이 두 값을 우회하므로 **거부**한다(현재 0건).
- 스캔 0건은 실패다 — 대상을 못 찾으면 위 단언은 공허하게 통과한다.

값이 실제 ORM 행으로 흐르는지는 `_complete_problem` 직접 호출로, `submit_attempt`는
`test_me.py::TestAttemptVersionPinWiring`이 잰다.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from whymath_backend.api import coach as coach_module
from whymath_backend.schema.enums import Curriculum

_PKG = Path(__file__).resolve().parents[3] / "src" / "backend" / "whymath_backend"
_ACTIVITY_MODULE = "whymath_backend.db.models.activity"
_RESOLVER = "resolve_attempt_version_pin"
_REQUIRED_KW = {"problem_version_id", "evaluation_context"}


def _attempt_aliases(tree: ast.AST) -> set[str]:
    """이 파일에서 `ProblemAttempt` ORM을 가리키는 이름들(`as ProblemAttemptORM` 포함)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == _ACTIVITY_MODULE:
            for alias in node.names:
                if alias.name == "ProblemAttempt":
                    names.add(alias.asname or alias.name)
    return names


def _resolver_result_names(func: ast.AST) -> set[str]:
    """함수 안에서 `X = await resolve_attempt_version_pin(...)`으로 묶인 변수 이름들."""
    names: set[str] = set()
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Await)
            and isinstance(node.value.value, ast.Call)
            and isinstance(node.value.value.func, ast.Name)
            and node.value.value.func.id == _RESOLVER
        ):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def _comes_from(value: ast.expr, names: set[str], attr: str) -> bool:
    """`<resolver 결과 변수>.<attr>` 형태인가."""
    return (
        isinstance(value, ast.Attribute)
        and value.attr == attr
        and isinstance(value.value, ast.Name)
        and value.value.id in names
    )


def _scan() -> tuple[list[str], list[str]]:
    """(생성 지점 목록, 위반 목록) — 생성 지점은 `파일:함수` 식별자."""
    sites: list[str] = []
    violations: list[str] = []
    for path in sorted(_PKG.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases = _attempt_aliases(tree)
        if not aliases:
            continue
        rel = path.relative_to(_PKG).as_posix()
        for func in ast.walk(tree):
            if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            resolver_vars = _resolver_result_names(func)
            for node in ast.walk(func):
                if not isinstance(node, ast.Call):
                    continue
                # from_schema 경유 생성은 두 컬럼을 우회한다.
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "from_schema"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in aliases
                ):
                    violations.append(f"{rel}:{func.name} — from_schema 경유 생성(두 컬럼 우회)")
                    continue
                if not (isinstance(node.func, ast.Name) and node.func.id in aliases):
                    continue
                site = f"{rel}:{func.name}"
                sites.append(site)
                kws = {k.arg: k.value for k in node.keywords if k.arg}
                missing = _REQUIRED_KW - set(kws)
                if missing:
                    violations.append(f"{site} — 키워드 누락 {sorted(missing)}")
                    continue
                for kw in sorted(_REQUIRED_KW):
                    if not _comes_from(kws[kw], resolver_vars, kw):
                        violations.append(f"{site} — `{kw}` 값이 {_RESOLVER} 결과에서 오지 않는다")
    return sites, violations


def test_scan_finds_the_known_writers_not_vacuous() -> None:
    """스캔 0건은 실패 — 알려진 서빙 적재 경로 3곳이 실제로 잡혀야 아래 단언이 의미를 갖는다."""
    sites, _ = _scan()
    assert len(sites) >= 3, f"생성 지점 {len(sites)}건만 발견: {sites}"
    assert {
        "api/me.py:submit_attempt",
        "api/coach.py:_complete_problem",
        "api/coach.py:_record_first_wrong_submission",
    } <= set(sites)


def test_every_problem_attempt_writer_pins_version_from_the_resolver() -> None:
    _, violations = _scan()
    assert violations == [], "버전 고정 배선 누락:\n" + "\n".join(violations)


# ── 값이 실제 ORM 행으로 흐르는가 (_complete_problem 직접 호출) ──────────────────────


class _EmptyResult:
    def all(self) -> list[Any]:
        return []

    def scalars(self) -> _EmptyResult:
        return self


class _PinSession:
    """`get`이 문항 스텁을 돌려주는 가짜 세션 — 고정 값이 시도 행까지 흐르는지 본다."""

    def __init__(self, problem: Any) -> None:
        self._problem = problem
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        return None

    async def get(self, _model: Any, _pk: Any) -> Any:
        return self._problem

    async def execute(self, _stmt: Any) -> _EmptyResult:
        return _EmptyResult()


async def _noop(*_a: Any, **_k: Any) -> list[Any]:
    return []


async def _noop_none(*_a: Any, **_k: Any) -> None:
    return None


async def _noop_machine(*_a: Any, **_k: Any) -> SimpleNamespace:
    return SimpleNamespace(rejected_transition=None)


@pytest.fixture(autouse=True)
def _stub_downstream(monkeypatch: pytest.MonkeyPatch) -> None:
    """이 파일의 관심은 버전 고정이다 — 숙달 전파·상태 머신은 DB 무접근 no-op으로 대체."""
    monkeypatch.setattr(coach_module, "record_problem_attempt_mastery", _noop)
    monkeypatch.setattr(coach_module, "record_problem_attempt_skill_mastery", _noop)
    monkeypatch.setattr(coach_module, "record_attempt_skill_event", _noop_none)
    monkeypatch.setattr(coach_module, "advance_on_graded_attempt", _noop_machine)


def _problem_stub(version_id: uuid.UUID | None) -> SimpleNamespace:
    return SimpleNamespace(
        answer="3",
        answer_constraint=None,
        choices=None,
        question_format=None,
        answer_format=None,
        multiple_answers=None,
        domain=None,
        subunit=None,
        curriculum_version=Curriculum.REVISION_2022,
        problem_version_id=version_id,
    )


@pytest.mark.asyncio
async def test_complete_problem_stores_the_problems_current_version_on_the_attempt() -> None:
    vid = uuid.uuid4()
    session = _PinSession(_problem_stub(vid))

    await coach_module._complete_problem(
        session,  # type: ignore[arg-type]
        user_id=uuid.uuid4(),
        problem_id=uuid.uuid4(),
        final_answer="3",
        started_at=None,
    )

    attempt = session.added[0]
    assert attempt.problem_version_id == vid
    assert attempt.evaluation_context is not None
    assert attempt.evaluation_context["curriculum_version"] == "2022_REVISION"


@pytest.mark.asyncio
async def test_complete_problem_without_a_version_stores_none_but_keeps_the_context() -> None:
    """대조군 — 판 포인터가 없으면 id는 None(상수가 아니다), 환경 스냅숏은 그래도 남는다."""
    session = _PinSession(_problem_stub(None))

    await coach_module._complete_problem(
        session,  # type: ignore[arg-type]
        user_id=uuid.uuid4(),
        problem_id=uuid.uuid4(),
        final_answer="3",
        started_at=None,
    )

    attempt = session.added[0]
    assert attempt.problem_version_id is None
    assert attempt.evaluation_context is not None
