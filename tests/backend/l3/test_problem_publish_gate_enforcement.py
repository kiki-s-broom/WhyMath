"""Problem Publish Gate 집행 지점 동결 — EOS-190 (정본화 ≠ 집행) + 축 경계 B1·B2.

게이트 모듈이 존재하는 것과 **모든 문항 발행이 그것을 지나는 것**은 다르다. 이 파일은 운영 패키지
(`src/backend/whymath_backend`) 전체를 AST로 훑어 다음을 막는다 (짝 파일: `test_publish_gate_
enforcement.py` — 개념 판):

  R1  ORM `ProblemVersion` import — `db/models/`의 정의·등록 파일과 `l3/problem_publish_gate.py`
      에서만. (이 클래스를 import하지 못하면 판 행을 만들거나 상태를 바꿀 수 없다.)
  R2  `problem.problem_version_id`(발행 포인터)에 값을 쓰는 코드 — 속성 대입·`setattr`·키워드
      인자·dict 키 — `l3/problem_publish_gate.py`에서만. 같은 이름의 `problem_attempt` 컬럼(EOS-47
      고정값)은 `ProblemAttempt(...)` 생성자 키워드로 쓰이므로 그 호출만 예외다.
  R3  `problem_version` 쓰기 SQL 문자열 · `UPDATE problem … problem_version_id` — 어디서도 금지.
  B1  `l3/problem_publish_gate.py`는 문항 노출 축(`ReviewStatus`·`review_status`·`is_published`·
      `publish_at`)을 참조하지 않는다.
  B2  문항 노출 경로는 판 축(`problem_version`·`version_header`·게이트 모듈)을 참조하지 않는다.
  L   잠금 순서 = 문항 → 판 (교착 방지).
  C   코퍼스 재적재(`l1/problem_bank/populate.py`)는 발행 포인터를 갱신 대상에서 뺀다 — 이 규칙은
      컬럼 집합을 mapper에서 동적으로 뽑는 코드라 R2의 AST로는 **보이지 않는다**(아래 C 절).

스캐너 자신도 검증한다 — 위반 코드를 주입하면 RED, 대상 0건이면 RED(공허 통과 금지).
한계(명시): 동적 import·`getattr`·런타임 조립 SQL은 보지 못한다. alembic·테스트는 대상 밖이다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_PKG = Path(__file__).resolve().parents[3] / "src" / "backend" / "whymath_backend"

_GATE_MODULE = "l3/problem_publish_gate.py"
_ORM_MODULE = "whymath_backend.db.models.problem_version"
_ORM_IMPORT_ALLOWED = frozenset(
    {"db/models/problem_version.py", "db/models/__init__.py", _GATE_MODULE}
)
_POINTER = "problem_version_id"
_POINTER_WRITE_ALLOWED = frozenset({_GATE_MODULE})
#: `problem_attempt.problem_version_id`(EOS-47)를 쓰는 ORM 클래스 — 발행 포인터가 아니라 시도 행의
#: 고정값이다. import 별칭(`coach.py`의 `ProblemAttemptORM`)은 파일마다 `_attempt_ctor_names`가
#: 원이름으로 추적한다 — 다른 클래스의 별칭은 이 예외를 얻지 못한다.
_ATTEMPT_CLASS = "ProblemAttempt"
#: 값을 *나르기만* 하는 객체 — DB를 쓰지 않는다(`l2/attempt_version_pin.AttemptVersionPin`).
_VALUE_CARRIERS = frozenset({"AttemptVersionPin"})

# `\bproblem_version\b`는 `problem_version_id`에 걸리지 않는다(`_`가 단어 문자라 경계가 없다).
_WRITE_SQL = re.compile(
    r"\b(?:UPDATE|INSERT\s+INTO|DELETE\s+FROM)\s+problem_version\b"
    r"|\bUPDATE\s+problem\b[^;]*\b" + _POINTER,
    re.IGNORECASE | re.DOTALL,
)

# B1 — 노출 축 이름. 판 게이트가 이 이름을 읽거나 쓰면 두 축이 섞인다.
_EXPOSURE_NAMES = frozenset({"ReviewStatus", "review_status", "is_published", "publish_at"})

# B2 — 문항 노출 경로(개념 판정 문서 §1 A·B행의 소비처와 같은 목록).
_EXPOSURE_MODULES = (
    "l2/next_problem_selection.py",
    "l6/_shared.py",
    "api/problems.py",
)
_VERSION_AXIS_MODULE_PARTS = ("problem_version", "version_header", "problem_publish_gate")


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """모듈·클래스·함수 docstring 노드 id — 설명 산문을 SQL로 오인하지 않게 뺀다."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def _callee_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _attempt_ctor_names(tree: ast.AST) -> frozenset[str]:
    """이 파일에서 `ProblemAttempt` ORM 클래스를 가리키는 이름들(원이름 + import 별칭)."""
    names = {_ATTEMPT_CLASS}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == _ATTEMPT_CLASS and alias.asname:
                    names.add(alias.asname)
    return frozenset(names)


def scan_source(rel: str, source: str) -> list[str]:
    """한 파일의 위반 목록(R1·R2·R3). 빈 목록 = 위반 없음."""
    tree = ast.parse(source)
    violations: list[str] = []
    docstrings = _docstring_nodes(tree)
    exempt_ctors = _attempt_ctor_names(tree) | _VALUE_CARRIERS
    for node in ast.walk(tree):
        # R1 — ORM ProblemVersion import
        if rel not in _ORM_IMPORT_ALLOWED:
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                if node.module == _ORM_MODULE or (
                    node.module == "whymath_backend.db.models"
                    and any(a.name in ("ProblemVersion", "problem_version") for a in node.names)
                ):
                    violations.append(f"R1 {rel}:{node.lineno} ORM ProblemVersion import")
            if isinstance(node, ast.Import):
                if any(a.name == _ORM_MODULE for a in node.names):
                    violations.append(f"R1 {rel}:{node.lineno} ORM ProblemVersion import")
        # R2 — 발행 포인터 쓰기
        if rel not in _POINTER_WRITE_ALLOWED:
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AugAssign | ast.AnnAssign):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr == _POINTER:
                    violations.append(f"R2 {rel}:{node.lineno} 발행 포인터 속성 대입")
            if isinstance(node, ast.Call):
                if _callee_name(node) not in exempt_ctors:
                    for kw in node.keywords:
                        if kw.arg == _POINTER:
                            violations.append(f"R2 {rel}:{node.lineno} 발행 포인터 키워드 인자")
                if _callee_name(node) == "setattr":
                    if (
                        len(node.args) >= 2
                        and isinstance(node.args[1], ast.Constant)
                        and node.args[1].value == _POINTER
                    ):
                        violations.append(f"R2 {rel}:{node.lineno} 발행 포인터 setattr")
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and key.value == _POINTER:
                        violations.append(f"R2 {rel}:{node.lineno} 발행 포인터 dict 키")
        # R3 — 쓰기 SQL 문자열
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
            and _WRITE_SQL.search(node.value)
        ):
            violations.append(f"R3 {rel}:{node.lineno} problem_version 쓰기 SQL 문자열")
    return violations


def _production_files() -> list[tuple[str, str]]:
    files = []
    for path in sorted(_PKG.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        files.append((path.relative_to(_PKG).as_posix(), path.read_text(encoding="utf-8")))
    return files


# ── 실 트리 ──────────────────────────────────────────────────────────────────
def test_scan_population_is_not_empty() -> None:
    """스캔 0건은 실패다 — 대상을 못 찾은 전수 가드는 공허하게 통과한다."""
    files = _production_files()
    assert len(files) > 500, f"운영 패키지 {len(files)}파일 — 경로 붕괴"
    assert any(rel == _GATE_MODULE for rel, _ in files), "게이트 모듈을 못 찾았다"


def test_no_publish_path_bypasses_the_gate_module() -> None:
    """집행 지점 — problem_version·발행 포인터를 쓰는 운영 코드는 게이트 모듈 하나뿐이다."""
    violations = [v for rel, src in _production_files() for v in scan_source(rel, src)]
    assert not violations, "Problem Publish Gate 우회 경로:\n  " + "\n  ".join(violations)


def test_attempt_pin_writers_are_the_only_allowed_exception() -> None:
    """R2의 예외(`ProblemAttempt` 생성자)가 실제로 쓰이고 있다 — 예외 목록이 공허하지 않다.

    EOS-47 시도 고정 호출부(me·coach)가 사라지면 이 예외도 같이 지워야 한다. 이 검사가 없으면 예외가
    남은 채 무엇이든 `ProblemAttempt(...)`로 위장하는 우회를 허용하는 빈 문이 된다.
    """
    users: set[str] = set()
    for rel, src in _production_files():
        tree = ast.parse(src)
        ctors = _attempt_ctor_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _callee_name(node) in ctors:
                if any(kw.arg == _POINTER for kw in node.keywords):
                    users.add(rel)
    assert {"api/me.py", "api/coach.py"} <= users, sorted(users)


def test_gate_module_is_the_actual_writer() -> None:
    """허용 목록이 공허하지 않다 — 게이트 모듈이 실제로 ORM을 import하고 포인터를 쓴다.

    이 검사가 없으면 게이트 모듈이 쓰기를 전부 잃어도(=아무도 발행하지 못해도) 위 검사는 초록이다.
    """
    source = (_PKG / _GATE_MODULE).read_text(encoding="utf-8")
    found = scan_source("l3/_as_if_not_allowed.py", source)
    assert any(v.startswith("R1") for v in found), found
    assert any(v.startswith("R2") for v in found), found


def test_axis_boundary_b1_gate_does_not_touch_exposure_axis() -> None:
    """B1 — 판 게이트는 문항 노출 축(검수·공개 여부)을 읽지도 쓰지도 않는다."""
    tree = ast.parse((_PKG / _GATE_MODULE).read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    kwargs = {kw.arg for n in ast.walk(tree) if isinstance(n, ast.Call) for kw in n.keywords}
    touched = (names | attrs | imported | kwargs) & _EXPOSURE_NAMES
    assert not touched, f"판 게이트가 노출 축을 참조한다: {sorted(touched)}"


@pytest.mark.parametrize("rel", _EXPOSURE_MODULES)
def test_axis_boundary_b2_exposure_paths_do_not_read_version_axis(rel: str) -> None:
    """B2 — 문항 노출 경로는 판 축(`VersionStatus`·`problem_version`·게이트)을 모른다."""
    path = _PKG / rel
    assert path.exists(), f"노출 경로 {rel}가 사라졌다 — 축 판정을 다시 대조하라"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "VersionStatus" not in imported
    assert "ProblemVersion" not in imported
    assert not any(
        m and any(part in m for part in _VERSION_AXIS_MODULE_PARTS) for m in modules
    ), f"{rel}: 판 축 모듈을 import한다 — {sorted(m for m in modules if m)}"


# ── 스캐너 변별력(주입) ───────────────────────────────────────────────────────
_INJECTIONS = {
    "orm-import-from": (
        "from whymath_backend.db.models.problem_version import ProblemVersion\n",
        "R1",
    ),
    "orm-import-package": ("from whymath_backend.db.models import ProblemVersion as PV\n", "R1"),
    "orm-import-module": ("import whymath_backend.db.models.problem_version\n", "R1"),
    "pointer-attr": ("def f(p, v):\n    p.problem_version_id = v\n", "R2"),
    "pointer-augassign-annassign": ("def f(p, v):\n    p.problem_version_id: object = v\n", "R2"),
    "pointer-kwarg-values": (
        "def f(stmt, v):\n    return stmt.values(problem_version_id=v)\n",
        "R2",
    ),
    "pointer-kwarg-problem-ctor": (
        "def f(v):\n    return Problem(problem_version_id=v)\n",
        "R2",
    ),
    "pointer-dict": ("SET = {'problem_version_id': None}\n", "R2"),
    "pointer-setattr": ("def f(p, v):\n    setattr(p, 'problem_version_id', v)\n", "R2"),
    "pointer-kwarg-alias-of-other-class": (
        "from whymath_backend.db.models.problem import Problem as ProblemAttempt2\n"
        "def f(v):\n    return ProblemAttempt2(problem_version_id=v)\n",
        "R2",
    ),
    "sql-update-version": ("Q = \"UPDATE problem_version SET status = 'PUBLISHED'\"\n", "R3"),
    "sql-insert-version": ("Q = 'insert into problem_version (payload) values (1)'\n", "R3"),
    "sql-delete-version": ("Q = 'DELETE FROM problem_version WHERE 1=1'\n", "R3"),
    "sql-update-pointer": (
        "Q = 'UPDATE problem SET problem_version_id = NULL WHERE slug = 1'\n",
        "R3",
    ),
}


@pytest.mark.parametrize("name", sorted(_INJECTIONS))
def test_scanner_detects_injected_bypass(name: str) -> None:
    source, rule = _INJECTIONS[name]
    found = scan_source("l2/injected_bypass.py", source)
    assert any(v.startswith(rule) for v in found), f"{name}: 주입했는데 {rule} 미검출 — {found}"


def test_scanner_passes_reads_attempt_ctor_and_docstrings() -> None:
    """대조군 — 읽기·시도 행 생성자·docstring 산문·시도 테이블 SQL은 위반이 아니다.

    오탐이면 사람이 가드를 끈다. 특히 `ProblemAttempt(problem_version_id=…)`(EOS-47)와
    `UPDATE problem_attempt`는 이름이 비슷해도 발행 포인터가 아니다.
    """
    source = (
        '"""UPDATE problem_version 을 설명하는 docstring."""\n'
        "Q1 = 'SELECT count(*) FROM problem WHERE problem_version_id IS NOT NULL'\n"
        "Q2 = 'UPDATE problem_attempt SET problem_version_id = NULL WHERE 1 = 0'\n"
        "def f(p, pin):\n"
        "    a = ProblemAttempt(problem_id=1, problem_version_id=pin.problem_version_id)\n"
        "    return p.problem_version_id, a\n"
    )
    assert scan_source("ops/reader.py", source) == []


def test_scanner_follows_attempt_class_import_alias_but_not_other_aliases() -> None:
    """`ProblemAttempt as X` 별칭은 예외를 얻고(coach.py 형태), 다른 클래스의 별칭은 얻지 못한다."""
    aliased = (
        "from whymath_backend.db.models.activity import ProblemAttempt as ProblemAttemptORM\n"
        "def f(pin):\n    return ProblemAttemptORM(problem_version_id=pin)\n"
    )
    assert scan_source("api/coach_like.py", aliased) == []
    # 위장 — 별칭 이름은 시도 클래스처럼 생겼지만 원이름이 `Problem`이다. 예외를 얻으면 안 된다.
    disguised = (
        "from whymath_backend.db.models.problem import Problem as ProblemAttemptORM\n"
        "def f(pin):\n    return ProblemAttemptORM(problem_version_id=pin)\n"
    )
    found = scan_source("api/coach_like.py", disguised)
    assert any(
        v.startswith("R2") for v in found
    ), f"원이름이 다른 별칭이 이름만으로 예외를 얻었다 — 발행 포인터 우회 가능: {found}"


def test_scanner_allowlist_is_per_file_not_global() -> None:
    """게이트 모듈에서는 같은 코드가 허용되고 다른 파일에서는 막힌다 — 허용이 파일 단위임을 고정."""
    source = "def f(p, v):\n    p.problem_version_id = v\n"
    assert scan_source(_GATE_MODULE, source) == []
    assert scan_source("api/anything.py", source) != []


# ── 잠금 순서 동결 — 문항 → 판 (교착 방지) ─────────────────────────────────────
def _lock_call_order(func_name: str) -> list[str]:
    tree = ast.parse((_PKG / _GATE_MODULE).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == func_name:
            calls = [
                n
                for n in ast.walk(node)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id in ("_lock_problem", "_lock_version")
            ]
            return [c.func.id for c in sorted(calls, key=lambda c: (c.lineno, c.col_offset))]  # type: ignore[attr-defined]
    raise AssertionError(f"{func_name} 없음")


def test_problem_row_is_locked_before_version_rows_on_publish() -> None:
    """발행(apply_transition)은 문항을 먼저 잠그고 판을 잠근다 — 역순이면 초안 생성과 교착 가능."""
    order = _lock_call_order("apply_transition")
    assert order, "apply_transition: 잠금 호출 0건 — 스캔 대상이 없다"
    assert order[0] == "_lock_problem", f"첫 잠금이 문항이 아니다 {order}"
    assert order.count("_lock_problem") == 1, f"문항을 두 번 잠근다 {order}"


def test_draft_creation_locks_only_the_problem_row() -> None:
    """초안 생성은 문항 행만 잠가 같은 문항의 동시 판 생성을 직렬화한다(판 행은 아직 없다)."""
    order = _lock_call_order("create_draft")
    assert order == ["_lock_problem"], order


# ── C. 코퍼스 재적재가 발행 포인터를 지우지 않는다 ───────────────────────────────
_POPULATE = "l1/problem_bank/populate.py"


def _populate_tree() -> ast.Module:
    return ast.parse((_PKG / _POPULATE).read_text(encoding="utf-8"))


def test_loader_excludes_publish_pointer_from_upsert_update_set() -> None:
    """적재기의 `ON CONFLICT DO UPDATE` 갱신 집합에서 발행 포인터가 빠진다.

    갱신 집합은 `mapper.column_attrs`에서 **동적으로** 뽑으므로 R2의 AST 스캔이 못 본다(컬럼 이름이
    코드에 나오지 않는다). 그래서 별도로 고정한다: (1) 보존 상수가 포인터를 명시하고 (2) 갱신 집합
    계산이 그 상수를 쓴다. 실제 행동은 실 PG 통합 테스트
    (`test_problem_version_publish_integration.py`)가 재적재 뒤 포인터 생존으로 확인한다.
    """
    tree = _populate_tree()
    const = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AnnAssign)
            and isinstance(n.target, ast.Name)
            and n.target.id == "PUBLISH_POINTER_COLUMN"
        ),
        None,
    )
    assert const is not None, "PUBLISH_POINTER_COLUMN 상수가 없다"
    assert isinstance(const.value, ast.Constant) and const.value.value == _POINTER
    update_keys = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "problem_update_keys" for t in n.targets)
        ),
        None,
    )
    assert update_keys is not None, "problem_update_keys 계산을 못 찾았다"
    used = {n.id for n in ast.walk(update_keys.value) if isinstance(n, ast.Name)}
    assert "PUBLISH_POINTER_COLUMN" in used, "갱신 집합 계산이 포인터 상수를 쓰지 않는다"
