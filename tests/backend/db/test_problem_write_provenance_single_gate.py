"""`problem` 쓰기 단일 관문 동결 — AST 전수 스캔 (LIC-03 acceptance ②·집행 별항).

**무엇을 막는가**: `problem` 테이블에 *행을 만드는* 코드가 허용 목록 밖에 생기는 것.
허용된 writer는 `l1/problem_bank/provenance_gate`를 경유해 "생성물이면 원장 동반"을 판정해야
한다. 관문을 안 거치는 새 쓰기 경로가 하나 생기는 순간 A4 DoD("provenance 없는 AI 생성물
INSERT 거부")는 다시 우회 가능해진다.

**왜 산문 규약이 아니라 AST인가**(CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지"):
판정 문서에 "관문을 경유한다"고 적는 것은 *선언*이고, 이 파일이 *집행*이다. 문자열 금지
목록(`grep "pg_insert(Problem"`)이 아니라 **구성된 결과**(AST 노드)를 본다 — 별칭 import·
줄바꿈·주석 같은 표기 변형에서 뚫리지 않게 하기 위해서다.

**동명이인 주의**: `Problem`이라는 이름은 ORM(`db.models.problem`)과 Pydantic 스키마
(`schema.problem`) 양쪽에 있고, `api/problems.py`는 **둘 다** import한다(`:62` ORM,
`:72` 스키마를 `ProblemSchema`로). 그래서 별칭 해석은 **이름이 아니라 모듈 경로**로 한다 —
이름으로 골랐으면 스키마 생성 수백 건을 쓰기로 오판했을 것이다.

**범위(정직)**: 이 가드가 보는 것은 *저장소 안의 파이썬 코드 경로*다. `psql` 직접 접속·
raw SQL 문자열·다른 서비스의 커넥션은 보지 못한다 — 그래서 판정 문서는 이 집행을
"우회 불가능"이 아니라 **"저장소 코드 경로 전수 차단"**이라고 적는다(§5 한계 명기).
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_SRC = _REPO_ROOT / "src" / "backend" / "whymath_backend"

# ORM 정본 모듈 — 별칭 해석의 기준(이름이 아니라 이 경로로 고른다).
_ORM_MODULE_PATH = "whymath_backend.db.models.problem"
_ORM_CLASS = "Problem"
_MODEL_MODULE = _BACKEND_SRC / "db" / "models" / "problem.py"

# 관문 모듈 — 허용 writer가 실제로 import해야 하는 대상.
_GATE_MODULE_PATH = "whymath_backend.l1.problem_bank.provenance_gate"
_GATE_MODULE = _BACKEND_SRC / "l1" / "problem_bank" / "provenance_gate.py"

# 행을 *만드는* 호출 — 읽기(`select`)·수정(`update`)은 범위 밖이다(DoD는 INSERT 축).
_WRITE_FUNCS = frozenset({"insert", "pg_insert"})
_WRITE_METHODS = frozenset({"from_schema"})

# 허용 writer — 값은 "관문을 경유하는가"이다.
#   True  = 관문 import를 강제한다.
#   False = 면제. 면제는 반드시 승계 태스크 ID를 동반한다(만료 없는 유예 금지 — CLAUDE.md).
_ALLOWED_WRITERS: dict[Path, bool] = {
    Path("src/backend/whymath_backend/l1/problem_bank/populate.py"): True,
    # LIC-09 면제 — 관리자 REST POST는 요청 계약에 provenance 좌석이 없어 관문에 넘길 재료가
    # 없다(`api/problems.py:176-177`). 계약 신설은 LIC-03(집행 지점 결정·배선)의 범위를 넘어
    # 분리 등재했다. 이 면제는 LIC-09 done 시 `test_exemptions_name_a_live_successor_task`가
    # RED가 되어 **제거를 강제**한다 — 스스로 만료하는 면제다.
    Path("src/backend/whymath_backend/api/problems.py"): False,
}

# 면제 writer → 승계 태스크 ID. 위 False 항목과 키가 일치해야 한다(아래 테스트가 대조).
_EXEMPTION_TASKS: dict[Path, str] = {
    Path("src/backend/whymath_backend/api/problems.py"): "LIC-09",
}


def _python_sources() -> list[Path]:
    return sorted(_BACKEND_SRC.rglob("*.py"))


def _orm_aliases(tree: ast.AST) -> set[str]:
    """이 모듈에서 `problem` **ORM 클래스**를 가리키는 이름들(모듈 경로로 판별)."""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == _ORM_MODULE_PATH:
            for alias in node.names:
                if alias.name == _ORM_CLASS:
                    aliases.add(alias.asname or alias.name)
    return aliases


def _write_sites(path: Path) -> list[str]:
    """한 파일에서 `problem` 행 생성 호출을 찾아 사람이 읽을 문자열로."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    aliases = _orm_aliases(tree)
    if not aliases:
        return []

    rel = path.relative_to(_REPO_ROOT)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # ① `pg_insert(ProblemORM)` / `sa.insert(Problem)` — 인자가 ORM 별칭인 경우.
        name = (
            func.id
            if isinstance(func, ast.Name)
            else func.attr if isinstance(func, ast.Attribute) else None
        )
        if name in _WRITE_FUNCS:
            for arg in node.args:
                if isinstance(arg, ast.Name) and arg.id in aliases:
                    found.append(f"{rel}:{node.lineno} — {name}({arg.id}) 행 생성")
        # ② `Problem.from_schema(...)` — ORM 별칭의 seam 헬퍼.
        if (
            isinstance(func, ast.Attribute)
            and func.attr in _WRITE_METHODS
            and isinstance(func.value, ast.Name)
            and func.value.id in aliases
        ):
            found.append(f"{rel}:{node.lineno} — {func.value.id}.{func.attr}() 행 생성")
        # ③ `Problem(...)` 직접 생성 — ORM 인스턴스화.
        if isinstance(func, ast.Name) and func.id in aliases:
            found.append(f"{rel}:{node.lineno} — {func.id}(...) 직접 생성")
    return found


def _imports_gate(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return any(
        isinstance(node, ast.ImportFrom) and node.module == _GATE_MODULE_PATH
        for node in ast.walk(tree)
    )


def test_only_allowed_modules_create_problem_rows() -> None:
    """허용 목록 밖에서 `problem` 행을 만들면 RED."""
    breaches: list[str] = []
    for path in _python_sources():
        if path.resolve() == _MODEL_MODULE.resolve():
            continue  # ORM 정의 자신 — 클래스 선언이지 쓰기가 아니다.
        rel = path.relative_to(_REPO_ROOT)
        if rel in _ALLOWED_WRITERS:
            continue
        breaches.extend(_write_sites(path))
    assert not breaches, (
        f"`problem` 행 생성이 단일 관문을 벗어났다 {len(breaches)}건:\n"
        + "\n".join(f"  · {b}" for b in breaches)
        + "\n\n새 쓰기 경로는 l1/problem_bank/provenance_gate.require_provenance를 경유해야 "
        "한다(LIC-03 판정: docs/standards/provenance_enforcement_layer_decision.md). "
        "경유할 수 없는 사정이면 승계 태스크를 등재하고 _ALLOWED_WRITERS에 False로 올려라."
    )


def test_allowed_writers_actually_route_through_the_gate() -> None:
    """면제되지 않은 허용 writer는 관문을 *실제로* import한다 — 선언이 아니라 집행."""
    missing = [
        str(rel)
        for rel, must_route in _ALLOWED_WRITERS.items()
        if must_route and not _imports_gate(_REPO_ROOT / rel)
    ]
    assert not missing, (
        f"허용 writer가 관문을 경유하지 않는다: {missing}\n"
        "허용 목록에 있다는 것은 '관문을 쓴다'는 뜻이다 — 안 쓸 거면 면제로 내리고 "
        "승계 태스크를 달아라."
    )


def test_scan_actually_reached_sources() -> None:
    """스캔 0건은 실패 — 대상을 못 찾은 전수 가드는 공허하게 통과한다."""
    sources = _python_sources()
    assert len(sources) > 100, f"백엔드 소스 스캔이 {len(sources)}건뿐이다 — 경로 규약이 깨졌다"
    assert _MODEL_MODULE.is_file(), f"ORM 정본 모듈이 없다: {_MODEL_MODULE}"
    assert _GATE_MODULE.is_file(), f"관문 모듈이 없다: {_GATE_MODULE}"
    for rel in _ALLOWED_WRITERS:
        assert (_REPO_ROOT / rel).is_file(), f"허용 writer 경로가 실재하지 않는다: {rel}"
    # 허용 writer에서 실제로 쓰기 노드를 찾았는가 — 0이면 탐지 규칙이 죽은 것이다.
    detected = {rel: len(_write_sites(_REPO_ROOT / rel)) for rel in _ALLOWED_WRITERS}
    assert all(count > 0 for count in detected.values()), (
        f"허용 writer에서 쓰기 노드를 못 찾았다: {detected} — 탐지 규칙(별칭 해석·호출 형태)이 "
        "실제 코드와 어긋났다는 뜻이며, 이 상태에서는 위반도 못 찾는다."
    )


def test_exemptions_name_a_live_successor_task() -> None:
    """면제는 *미완료* 승계 태스크를 지목한다 — 태스크가 done이면 면제를 거두라는 신호.

    만료 없는 유예 금지(CLAUDE.md): 면제가 스스로 만료하지 않으면 영구 구멍이 된다.
    `provenance_audit._KNOWN_GAPS`의 `GrandfatherEntry(task_id + reason)` 만료 계약과 동형.
    """
    import yaml

    exempted = {rel for rel, must_route in _ALLOWED_WRITERS.items() if not must_route}
    assert exempted == set(_EXEMPTION_TASKS), (
        "면제 목록과 승계 태스크 표가 어긋났다 — 면제에만: "
        f"{sorted(str(p) for p in exempted - set(_EXEMPTION_TASKS))} / 표에만: "
        f"{sorted(str(p) for p in set(_EXEMPTION_TASKS) - exempted)}"
    )

    tasks_dir = _REPO_ROOT / "backlog" / "tasks"
    for rel, task_id in _EXEMPTION_TASKS.items():
        matches = sorted(tasks_dir.glob(f"{task_id}.yaml")) + sorted(
            tasks_dir.glob(f"{task_id}-*.yaml")
        )
        assert matches, f"면제 {rel} 의 승계 태스크 {task_id} 가 백로그에 없다 — 가짜 만료 약속이다"
        status = yaml.safe_load(matches[0].read_text(encoding="utf-8")).get("status")
        assert status not in {"done", "cancelled"}, (
            f"승계 태스크 {task_id} 가 {status} 인데 면제({rel})가 남아 있다 — "
            "이제 이 writer를 관문에 배선하고 면제를 제거하라."
        )
