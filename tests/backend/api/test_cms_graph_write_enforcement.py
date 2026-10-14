"""개념 그래프 쓰기 집행 지점 동결 — P3-26 (정본화 ≠ 집행).

규칙을 만들었다는 것과 **모든 쓰기가 그 규칙을 지난다**는 것은 다르다. 이 파일은 운영 패키지
(`src/backend/whymath_backend`)를 AST로 훑어 다음을 막는다. 스캔 대상 0건은 실패이고, 스캐너 자신도
위반을 주입해 변별력을 확인한다.

  E1  **살아있는 `Concept` 행을 만드는 곳은 정해진 자리뿐이다** — `Concept(...)`·`Concept.from_schema(...)`
      호출은 허용 목록의 모듈에서만. 새 모듈이 개념 행을 만들면 발행 게이트를 우회하는 길이 된다.
      (`api/concepts.py`의 PATCH는 *기존 행*을 병합하는 갱신이다 — 생성 핸들러는 410이라 행을 만들지 않는다.)
  E2  **`ConceptEdge` 행을 만드는 곳은 정해진 자리뿐이다** — CMS 관계 추가(`admin_cms_graph.create_edge`)와
      적재기 4종뿐.
  E3  **CMS 관계 추가는 `잠금 → 순환 검사 → 쓰기` 순서다** — 한 함수 안에서 `lock_prerequisite_graph`
      호출이 `find_cycle_if_added` 호출보다, 그것이 `ConceptEdge(` 생성보다 앞서야 하고 소유 표지를 채운다.
  E4  **적재기 4종은 엣지를 쓰기 전에 잠금·DB 인지 순환 검사·소유 가드를 지난다** — `pg_insert(ConceptEdge)`가
      있는 모듈은 `lock_prerequisite_graph_sync`·`assert_acyclic_with_db`·`upsert_guard`를 모두 부른다.
  E5  **CMS 그래프 쓰기 라우트(쓰기 메서드)는 DB 접근 전에 권한을 검사한다** — 각 핸들러의 첫 `_require(...)`
      호출이 첫 `session` 사용보다 앞서야 한다.
  E6  **이 CMS 모듈들은 `ConceptVersion` ORM을 import하지 않고 발행 포인터를 쓰지 않는다**(AST 동결 R1·R2와
      별개로, 새 모듈이 생기는 것을 이 파일이 직접 막는다).

한계(명시): 동적 import·`getattr`·런타임 조립 SQL은 보지 못한다. alembic·테스트는 대상 밖이다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_PKG = Path(__file__).resolve().parents[3] / "src" / "backend" / "whymath_backend"

#: 살아있는 `Concept` 행을 *만들 수 있는* 모듈(E1). 근거를 함께 적는다 — 목록이 늘면 리뷰가 이유를 본다.
_CONCEPT_ROW_BUILDERS = {
    "db/models/concept.py": "ORM 정의 — from_schema 헬퍼 자체",
    "l3/publish_gate.py": "신규 개념 제안이 발행되는 순간 행을 실체화하는 유일한 자리(P3-26)",
    "api/concepts.py": "PATCH가 기존 행을 병합하는 갱신(생성 핸들러는 410 — 행을 만들지 않는다)",
    "ops/loop_kpi_sample_load.py": "KPI 표본을 전용 DB에 쌓는 운영 도구 — CMS가 고치는 운영 행과 무관",
    # graph.json 적재기 — 원천 파일이 소유한 행을 upsert한다. CMS 소유 행은 `upsert_guard`가 건너뛴다(P3-26).
    "l1/atom_graph/atom_backend_concept.py": "원자 백본 적재기(CMS 소유 가드 적용)",
    "l1/concept_graph/backend_concept.py": "레거시 개념 그래프 적재기(CMS 소유 가드 적용)",
}

#: `ConceptEdge` 행을 *만들 수 있는* 모듈(E2).
_EDGE_ROW_BUILDERS = {
    "db/models/concept.py": "ORM 정의",
    "api/admin_cms_graph.py": "CMS 선수 관계 추가 — 잠금·순환 검사 뒤(E3)",
    "l1/atom_graph/atom_backend_edge.py": "원자 백본 적재기(E4)",
    "l1/concept_graph/backend_edge.py": "레거시 개념 그래프 적재기(E4)",
}

_CMS_GRAPH_MODULES = ("api/admin_cms_graph.py", "api/_concept_graph_rules.py")
_WRITE_METHODS = {"post", "put", "patch", "delete"}


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _builds(tree: ast.AST, class_name: str) -> list[int]:
    """`Cls(...)`·`Cls.from_schema(...)`·`pg_insert(Cls)`·`insert(Cls)` 호출 줄 번호."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == class_name:
            lines.append(node.lineno)
        elif (
            isinstance(func, ast.Attribute)
            and func.attr == "from_schema"
            and isinstance(func.value, ast.Name)
            and func.value.id == class_name
        ):
            lines.append(node.lineno)
        elif (
            _call_name(node) in {"pg_insert", "insert"}
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == class_name
        ):
            lines.append(node.lineno)
    return lines


def _scan_builders(
    class_name: str, allowed: dict[str, str]
) -> tuple[dict[str, list[int]], list[str]]:
    found: dict[str, list[int]] = {}
    for path in sorted(_PKG.rglob("*.py")):
        rel = path.relative_to(_PKG).as_posix()
        source = path.read_text(encoding="utf-8")
        if class_name not in source:
            continue
        lines = _builds(ast.parse(source), class_name)
        if lines:
            found[rel] = lines
    violations = [f"{rel}:{lines[0]}" for rel, lines in found.items() if rel not in allowed]
    return found, violations


# ── E1·E2 ────────────────────────────────────────────────────────────────────────────


def test_concept_rows_are_built_only_in_the_sanctioned_modules() -> None:
    found, violations = _scan_builders("Concept", _CONCEPT_ROW_BUILDERS)
    assert found, "스캔 0건 — 스캐너가 눈이 멀었다(공허 통과 금지)"
    # ORM 정의 파일은 `cls(**kwargs)`로 만들어 이름 기반 스캔에 잡히지 않는다 — 필수는 게이트뿐이다.
    assert "l3/publish_gate.py" in found
    assert not violations, (
        f"허용 목록 밖에서 Concept 행을 만든다: {violations} — 신규 개념은 `publish_gate`의 발행만이 "
        "개념 행을 만든다(검수 없이 학생이 읽는 행이 생기는 길을 열지 않는다)"
    )


def test_concept_edge_rows_are_built_only_in_the_sanctioned_modules() -> None:
    found, violations = _scan_builders("ConceptEdge", _EDGE_ROW_BUILDERS)
    assert found and "api/admin_cms_graph.py" in found
    assert not violations, f"허용 목록 밖에서 ConceptEdge 행을 만든다: {violations}"


def test_the_legacy_create_handler_builds_nothing() -> None:
    """폐지된 `POST /v1/concepts` 핸들러에는 행 생성·세션 쓰기가 없다(410만 낸다)."""
    tree = ast.parse((_PKG / "api/concepts.py").read_text(encoding="utf-8"))
    handler = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "create_concept"
    )
    names = {_call_name(c) for c in ast.walk(handler) if isinstance(c, ast.Call)}
    assert not names & {"add", "from_schema", "merge", "commit", "Concept"}, names
    assert "HTTPException" in names


# ── E3 ───────────────────────────────────────────────────────────────────────────────


def _first_line(func: ast.AST, name: str) -> int | None:
    lines = [n.lineno for n in ast.walk(func) if isinstance(n, ast.Call) and _call_name(n) == name]
    return min(lines) if lines else None


def edge_write_order_violations(source: str) -> list[str]:
    """`ConceptEdge(`를 만드는 함수에서 잠금 → 순환 검사 → 생성 → 소유 표지 순서가 아니면 사유를 돌려준다."""
    out: list[str] = []
    tree = ast.parse(source)
    builders = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and _first_line(n, "ConceptEdge")
    ]
    if not builders:
        return ["ConceptEdge를 만드는 함수를 하나도 찾지 못했다"]
    for fn in builders:
        lock = _first_line(fn, "lock_prerequisite_graph")
        check = _first_line(fn, "find_cycle_if_added")
        build = _first_line(fn, "ConceptEdge")
        mark = _first_line(fn, "mark_cms_edited")
        assert build is not None
        if lock is None or lock > build:
            out.append(f"{fn.name}: 선수 그래프 잠금이 관계 생성보다 앞서지 않는다")
        if check is None or check > build:
            out.append(f"{fn.name}: 순환 검사가 관계 생성보다 앞서지 않는다")
        if lock is not None and check is not None and lock > check:
            out.append(f"{fn.name}: 잠금이 순환 검사보다 뒤다(검사와 쓰기 사이 틈)")
        if mark is None:
            out.append(f"{fn.name}: 소유 표지(mark_cms_edited)를 채우지 않는다")
    return out


def test_cms_edge_creation_locks_then_checks_then_writes() -> None:
    source = (_PKG / "api/admin_cms_graph.py").read_text(encoding="utf-8")
    assert edge_write_order_violations(source) == []


_GOOD_EDGE = """
async def create_edge(session):
    await lock_prerequisite_graph(session)
    cycle = await find_cycle_if_added(session, 1, 2)
    edge = ConceptEdge(edge_id=1)
    mark_cms_edited(edge)
"""


@pytest.mark.parametrize(
    ("name", "source", "expect"),
    [
        ("정상 순서는 위반 0", _GOOD_EDGE, None),
        (
            "순환 검사 누락",
            _GOOD_EDGE.replace("    cycle = await find_cycle_if_added(session, 1, 2)\n", ""),
            "순환 검사",
        ),
        (
            "잠금 누락",
            _GOOD_EDGE.replace("    await lock_prerequisite_graph(session)\n", ""),
            "잠금",
        ),
        (
            "잠금이 검사 뒤",
            """
async def create_edge(session):
    cycle = await find_cycle_if_added(session, 1, 2)
    await lock_prerequisite_graph(session)
    edge = ConceptEdge(edge_id=1)
    mark_cms_edited(edge)
""",
            "검사보다 뒤",
        ),
        ("소유 표지 누락", _GOOD_EDGE.replace("    mark_cms_edited(edge)\n", ""), "소유 표지"),
        (
            "검사가 생성 뒤",
            """
async def create_edge(session):
    await lock_prerequisite_graph(session)
    edge = ConceptEdge(edge_id=1)
    cycle = await find_cycle_if_added(session, 1, 2)
    mark_cms_edited(edge)
""",
            "순환 검사가 관계 생성보다",
        ),
    ],
)
def test_the_order_scanner_discriminates(name: str, source: str, expect: str | None) -> None:
    got = edge_write_order_violations(source)
    if expect is None:
        assert got == [], (name, got)
    else:
        assert any(expect in v for v in got), (name, got)


# ── E4 ───────────────────────────────────────────────────────────────────────────────


def loader_guard_violations(source: str) -> list[str]:
    """`pg_insert(ConceptEdge)`가 있는 모듈이 잠금·DB 인지 순환 검사·소유 가드를 모두 부르는가."""
    tree = ast.parse(source)
    if not _builds(tree, "ConceptEdge"):
        return ["pg_insert(ConceptEdge)가 없다 — 스캐너가 눈이 멀었다"]
    called = {_call_name(c) for c in ast.walk(tree) if isinstance(c, ast.Call)}
    needed = {"lock_prerequisite_graph_sync", "assert_acyclic_with_db", "upsert_guard"}
    return [f"{n} 호출이 없다" for n in sorted(needed - called)]


@pytest.mark.parametrize(
    "rel",
    ["l1/atom_graph/atom_backend_edge.py", "l1/concept_graph/backend_edge.py"],
)
def test_edge_loaders_lock_check_and_guard_before_writing(rel: str) -> None:
    assert loader_guard_violations((_PKG / rel).read_text(encoding="utf-8")) == []


def test_loader_scanner_discriminates() -> None:
    good = (
        "def f(conn):\n    lock_prerequisite_graph_sync(conn)\n    assert_acyclic_with_db(conn, 1, 2)\n"
        "    w, r = upsert_guard(ConceptEdge, overwrite=False)\n    pg_insert(ConceptEdge)\n"
    )
    assert loader_guard_violations(good) == []
    for drop in ("lock_prerequisite_graph_sync", "assert_acyclic_with_db", "upsert_guard"):
        bad = "\n".join(
            ln for ln in good.splitlines() if not ln.strip().startswith(drop) and drop not in ln
        )
        assert loader_guard_violations(bad), drop
    assert loader_guard_violations("def f():\n    pass\n")  # 대상 없음 = 위반(공허 통과 금지)


# ── E5 ───────────────────────────────────────────────────────────────────────────────


def permission_before_db_violations(source: str) -> list[str]:
    """쓰기 라우트 핸들러가 첫 `session` 사용보다 먼저 `_require(...)`를 부르는가."""
    out: list[str] = []
    tree = ast.parse(source)
    handlers = 0
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        methods = {
            d.func.attr
            for d in fn.decorator_list
            if isinstance(d, ast.Call)
            and isinstance(d.func, ast.Attribute)
            and isinstance(d.func.value, ast.Name)
            and d.func.value.id == "router"
        }
        if not methods & _WRITE_METHODS:
            continue
        handlers += 1
        require = _first_line(fn, "_require")
        uses = [
            n.lineno
            for n in ast.walk(fn)
            if isinstance(n, ast.Name) and n.id == "session" and isinstance(n.ctx, ast.Load)
        ]
        # 인자 선언의 `session`은 Arg이지 Name이 아니다 — 본문 사용만 센다.
        if require is None:
            out.append(f"{fn.name}: _require 호출이 없다")
        elif uses and require > min(uses):
            out.append(f"{fn.name}: 권한 검사가 DB 접근보다 뒤다")
    if handlers == 0:
        out.append("쓰기 라우트를 하나도 찾지 못했다")
    return out


def test_cms_graph_write_routes_check_permission_before_touching_the_db() -> None:
    source = (_PKG / "api/admin_cms_graph.py").read_text(encoding="utf-8")
    assert permission_before_db_violations(source) == []


def test_permission_scanner_discriminates() -> None:
    good = (
        "@router.post('/x')\nasync def h(session, user):\n    _require(user, C)\n"
        "    await session.execute(1)\n"
    )
    assert permission_before_db_violations(good) == []
    late = good.replace("    _require(user, C)\n", "").replace(
        "    await session.execute(1)\n", "    await session.execute(1)\n    _require(user, C)\n"
    )
    assert permission_before_db_violations(late)
    missing = good.replace("    _require(user, C)\n", "")
    assert permission_before_db_violations(missing)
    assert permission_before_db_violations("def nothing():\n    pass\n")


# ── E6 ───────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("rel", _CMS_GRAPH_MODULES)
def test_cms_graph_modules_never_touch_the_version_orm_or_the_publish_pointer(rel: str) -> None:
    tree = ast.parse((_PKG / rel).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.endswith("models.concept_version"), (rel, node.lineno)
            assert not (
                node.module == "whymath_backend.db.models"
                and any(a.name == "ConceptVersion" for a in node.names)
            ), (rel, node.lineno)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            assert node.attr != "current_published_version_id", (rel, node.lineno)
        if isinstance(node, ast.keyword):
            assert node.arg != "current_published_version_id", (rel, node.value.lineno)
