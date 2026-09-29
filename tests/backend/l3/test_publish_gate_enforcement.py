"""Publish Gate 집행 지점 동결 — EOS-50 ③ (정본화 ≠ 집행) + 축 경계 B1·B2.

게이트가 존재하는 것과 **모든 publish가 게이트를 지나는 것**은 다르다. 이 파일은 운영 패키지
(`src/backend/whymath_backend`) 전체를 AST로 훑어 다음을 막는다:

  R1  ORM `ConceptVersion` import — `db/models/`의 정의·등록 파일과 `l3/publish_gate.py`에서만.
      (이 클래스를 import하지 못하면 행을 만들거나 상태를 바꿀 수 없다.)
  R2  `current_published_version_id`에 값을 쓰는 코드(속성 대입·키워드 인자·dict 키)
      — `l3/publish_gate.py`에서만. (발행 포인터를 옮기는 것이 곧 발행이다.)
  R3  `concept_version` 쓰기 SQL 문자열(UPDATE/INSERT INTO/DELETE FROM concept_version,
      UPDATE concept … current_published_version_id) — 어디서도 금지(ORM 우회 차단).
  B1  `l3/publish_gate.py`는 `ReviewStatus`·`review_status`를 참조하지 않는다.
  B2  문항 노출 경로는 `VersionStatus`·`concept_version`을 참조하지 않는다.

판정 문서: `docs/reviews/eos50_publish_gate_axis_judgment_2026-09-29.md` §4·§5.

스캐너 자신도 검증한다 — 위반 코드를 주입하면 RED, 대상 0건이면 RED(공허 통과 금지).
한계(명시): 동적 import·`getattr`·런타임 조립 SQL은 보지 못한다. alembic·테스트는 대상 밖이다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_PKG = Path(__file__).resolve().parents[3] / "src" / "backend" / "whymath_backend"

_GATE_MODULE = "l3/publish_gate.py"
_ORM_MODULE = "whymath_backend.db.models.concept_version"
_ORM_IMPORT_ALLOWED = frozenset(
    {"db/models/concept_version.py", "db/models/__init__.py", _GATE_MODULE}
)
_POINTER = "current_published_version_id"
_POINTER_WRITE_ALLOWED = frozenset({_GATE_MODULE})

_WRITE_SQL = re.compile(
    r"\b(?:UPDATE|INSERT\s+INTO|DELETE\s+FROM)\s+concept_version\b"
    r"|\bUPDATE\s+concept\b[^;]*\b" + _POINTER,
    re.IGNORECASE | re.DOTALL,
)

# B2 — 문항 노출 경로(판정 문서 §1 A·B행의 소비처)
_EXPOSURE_MODULES = (
    "l2/next_problem_selection.py",
    "l6/_shared.py",
    "api/problems.py",
)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """모듈·클래스·함수 docstring 노드 id — 설명 산문을 SQL로 오인하지 않게 뺀다."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def scan_source(rel: str, source: str) -> list[str]:
    """한 파일의 위반 목록(R1·R2·R3). 빈 목록 = 위반 없음."""
    tree = ast.parse(source)
    violations: list[str] = []
    docstrings = _docstring_nodes(tree)
    for node in ast.walk(tree):
        # R1 — ORM ConceptVersion import
        if rel not in _ORM_IMPORT_ALLOWED:
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                if node.module == _ORM_MODULE or (
                    node.module == "whymath_backend.db.models"
                    and any(a.name in ("ConceptVersion", "concept_version") for a in node.names)
                ):
                    violations.append(f"R1 {rel}:{node.lineno} ORM ConceptVersion import")
            if isinstance(node, ast.Import):
                if any(a.name == _ORM_MODULE for a in node.names):
                    violations.append(f"R1 {rel}:{node.lineno} ORM ConceptVersion import")
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
                for kw in node.keywords:
                    if kw.arg == _POINTER:
                        violations.append(f"R2 {rel}:{node.lineno} 발행 포인터 키워드 인자")
                if isinstance(node.func, ast.Name | ast.Attribute) and (
                    getattr(node.func, "attr", None) == "setattr"
                    or getattr(node.func, "id", None) == "setattr"
                ):
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
            violations.append(f"R3 {rel}:{node.lineno} concept_version 쓰기 SQL 문자열")
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
    """③ 집행 지점 — concept_version·발행 포인터를 쓰는 운영 코드는 게이트 모듈 하나뿐이다."""
    violations = [v for rel, src in _production_files() for v in scan_source(rel, src)]
    assert not violations, "Publish Gate 우회 경로:\n  " + "\n  ".join(violations)


def test_gate_module_is_the_actual_writer() -> None:
    """허용 목록이 공허하지 않다 — 게이트 모듈이 실제로 ORM을 import하고 포인터를 쓴다.

    이 검사가 없으면 게이트 모듈이 쓰기를 전부 잃어도(=아무도 발행하지 못해도) 위 검사는 초록이다.
    """
    source = (_PKG / _GATE_MODULE).read_text(encoding="utf-8")
    # 게이트 모듈을 허용 목록 밖으로 가정하고 스캔하면 R1·R2가 실제로 잡혀야 한다.
    found = scan_source("l3/_as_if_not_allowed.py", source)
    assert any(v.startswith("R1") for v in found), found
    assert any(v.startswith("R2") for v in found), found


def test_axis_boundary_b1_gate_does_not_read_review_status() -> None:
    """B1 — Publish Gate는 문항 검수 축(`ReviewStatus`)을 읽지도 쓰지도 않는다."""
    tree = ast.parse((_PKG / _GATE_MODULE).read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "ReviewStatus" not in names | imported
    assert "review_status" not in attrs


@pytest.mark.parametrize("rel", _EXPOSURE_MODULES)
def test_axis_boundary_b2_exposure_paths_do_not_read_version_status(rel: str) -> None:
    """B2 — 문항 노출 경로는 버전 축(`VersionStatus`·`concept_version`)을 모른다."""
    path = _PKG / rel
    assert path.exists(), f"노출 경로 {rel}가 사라졌다 — 판정 문서 §1을 다시 대조하라"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "VersionStatus" not in imported
    assert not any(m and ("version_header" in m or "concept_version" in m) for m in modules)


# ── 스캐너 변별력(주입) ───────────────────────────────────────────────────────
_INJECTIONS = {
    "orm-import-from": (
        "from whymath_backend.db.models.concept_version import ConceptVersion\n",
        "R1",
    ),
    "orm-import-package": ("from whymath_backend.db.models import ConceptVersion as CV\n", "R1"),
    "orm-import-module": ("import whymath_backend.db.models.concept_version\n", "R1"),
    "pointer-attr": ("def f(c, v):\n    c.current_published_version_id = v\n", "R2"),
    "pointer-kwarg": (
        "def f(stmt, v):\n    return stmt.values(current_published_version_id=v)\n",
        "R2",
    ),
    "pointer-dict": ("SET = {'current_published_version_id': None}\n", "R2"),
    "pointer-setattr": ("def f(c, v):\n    setattr(c, 'current_published_version_id', v)\n", "R2"),
    "sql-update-version": ("Q = \"UPDATE concept_version SET status = 'PUBLISHED'\"\n", "R3"),
    "sql-insert-version": ("Q = 'insert into concept_version (payload) values (1)'\n", "R3"),
    "sql-update-pointer": (
        "Q = 'UPDATE concept SET current_published_version_id = NULL WHERE code = 1'\n",
        "R3",
    ),
}


@pytest.mark.parametrize("name", sorted(_INJECTIONS))
def test_scanner_detects_injected_bypass(name: str) -> None:
    source, rule = _INJECTIONS[name]
    found = scan_source("l2/injected_bypass.py", source)
    assert any(v.startswith(rule) for v in found), f"{name}: 주입했는데 {rule} 미검출 — {found}"


def test_scanner_passes_reads_and_docstrings() -> None:
    """대조군 — 읽기 SQL·docstring 산문은 위반이 아니다(오탐이면 사람이 가드를 끈다)."""
    source = (
        '"""UPDATE concept_version 을 설명하는 docstring."""\n'
        "Q = 'SELECT count(*) FROM concept WHERE current_published_version_id IS NOT NULL'\n"
        "def f(c):\n    return c.current_published_version_id\n"
    )
    assert scan_source("ops/reader.py", source) == []


# ── 잠금 순서 동결 — 개념 → 판 (교착 방지) ─────────────────────────────────────
def _lock_call_order(func_name: str) -> list[str]:
    tree = ast.parse((_PKG / _GATE_MODULE).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == func_name:
            calls = [
                n
                for n in ast.walk(node)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id in ("_lock_concept", "_lock_version")
            ]
            return [c.func.id for c in sorted(calls, key=lambda c: (c.lineno, c.col_offset))]  # type: ignore[attr-defined]
    raise AssertionError(f"{func_name} 없음")


@pytest.mark.parametrize("func_name", ["apply_transition", "rollback"])
def test_concept_row_is_locked_before_version_rows(func_name: str) -> None:
    """발행(apply_transition)과 롤백(rollback)이 같은 순서로 잠근다 — 역순이면 교착 가능."""
    order = _lock_call_order(func_name)
    assert order, f"{func_name}: 잠금 호출 0건 — 스캔 대상이 없다"
    assert order[0] == "_lock_concept", f"{func_name}: 첫 잠금이 개념이 아니다 {order}"
    assert order.count("_lock_concept") == 1, f"{func_name}: 개념을 두 번 잠근다 {order}"
