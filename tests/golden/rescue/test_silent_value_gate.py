"""RS 조용한 값 삼키기 게이트 — `except` 핸들러가 예외를 **값도 신호도 없이** 삼키는 자리를 AST로 잠근다.

무엇을 막는가
- ruff의 조용한 실패 규칙(`BLE001`·`S110`·`S112`·`E722`)이 **보지 못하는** 자리다.
  `BLE001`은 넓은 `except`만 보고 타입명은 보지 않으며, `S110`은 `pass`, `S112`는 `continue`만 본다.
  그래서 `except Exception: return None` · `except (AttributeError, ValueError): return None` ·
  `except OSError: x = None` 은 넷 다 통과한다(`golden/RUFF_STRICTNESS_DECISION.md` §5-1 표).

어떻게 재는가
- 파일마다 `ast.parse` 한 번. 모든 `except` 핸들러(`except*` 포함)에 대해:
  - **신호가 있으면 통과** — `type(<exc>).__name__` · `exc_info=True` · `.exception(` 호출 · `raise`(재전파).
  - 신호가 없고 **본문 전부가 값 없이 넘어가는 문장**이면 **위반**이다.
    그 문장은 `pass` · `continue` · `break` · `...` · `return` · `return None` · `return False` ·
    `x = None` · `x = False` 다.
  - 신호는 없지만 무언가를 만들어 넘기면(`return ""` · `return fallback()` …) **오탐 후보**로만 모은다.
    설계된 강등과 무음의 경계가 여기다 — 게이트는 무음만 잠그고, 강등은 사람이 판정한다.

실패를 통과로 위장하지 않는 장치
- 검사 대상 .py가 0개면 실패한다(빈 스캔은 공허한 통과다).
- UTF-8로 읽지 못하는 파일은 건너뛰지 않고 실패로 올린다(대상이 조용히 줄어드는 것을 막는다).
- 허용 목록과 **정확히** 같아야 통과한다 — 새 건도, 남은 줄도 실패다.
- 합성 소스로 위반/통과 경계를 먼저 확인한다(규칙이 꺼진 검사기는 늘 0건을 낸다).

한계(명시)
- 데이터 흐름 분석이 아니다. 같은 핸들러 안에 타입명 표현이 있는지만 본다.
- 핸들러가 다른 함수로 위임하면(`_handle(exc)`) 신호를 볼 수 없다 → 오탐 후보로 나온다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# 저장소 루트 — tests/golden/rescue/이 파일 → parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]
# 경로 표기의 기준(허용 목록이 `golden/…` 형태인 이유)
_BACKEND = _REPO_ROOT / "src" / "backend"
# 게이트 대상 — 새 코드가 쌓이는 골든 구역
_GOLDEN = _BACKEND / "golden"
# 기록만 하는 옛 구역(게이트 없음 · 골든 기간 읽기 전용)
_OLD = _BACKEND / "whymath_backend"
# 허용 목록(경로:줄 · 규칙 · 이유) — G2 게이트와 같은 형식
_ALLOW = Path(__file__).with_name("silent_value_allow.txt")
# 옛 구역 기준선(패키지별 건수 · 게이트 아님)
_BASELINE = _REPO_ROOT / "golden" / "reports_rescue" / "G3" / "옛구역_값삼키기_기준선.tsv"

#: 게이트 규칙 이름 — 허용 목록의 규칙 칸에 들어간다.
RULE = "SILENT-VALUE"

#: 핸들러가 "값 없이 넘어가는" 문장으로 볼 대입·반환 상수.
_SILENT_CONSTANTS: tuple[object, ...] = (None, False)


def _is_silent_constant(node: ast.AST) -> bool:
    """`None`·`False` 리터럴인가."""
    return isinstance(node, ast.Constant) and node.value in _SILENT_CONSTANTS


def _is_silent_statement(stmt: ast.stmt) -> bool:
    """이 문장 하나가 "값도 신호도 없이" 넘어가는 문장인가."""
    if isinstance(stmt, (ast.Pass, ast.Continue, ast.Break)):
        return True
    if isinstance(stmt, ast.Expr):
        # `...`(Ellipsis) 또는 문서 문자열 — 아무 일도 하지 않는다.
        return isinstance(stmt.value, ast.Constant)
    if isinstance(stmt, ast.Return):
        return stmt.value is None or _is_silent_constant(stmt.value)
    if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
        return stmt.value is not None and _is_silent_constant(stmt.value)
    return False


def _scope_nodes(handler: ast.ExceptHandler) -> list[ast.AST]:
    """핸들러 본문을 훑되 **중첩 함수·클래스 안으로 들어가지 않는다**.

    들어가면 안쪽 `raise`가 바깥 핸들러의 신호로 잡혀 위반을 놓친다.
    """
    found: list[ast.AST] = []
    stack: list[ast.AST] = list(handler.body)
    while stack:
        node = stack.pop()
        found.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return found


def _is_type_name_expr(node: ast.AST) -> bool:
    """`type(x).__name__` — 예외 타입명을 남기는 대표 표현."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "__name__"
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "type"
    )


def _has_signal(handler: ast.ExceptHandler) -> bool:
    """핸들러가 예외 사실을 남기는가 — 타입명 · `exc_info=True` · `.exception(` · `raise`."""
    for node in _scope_nodes(handler):
        if _is_type_name_expr(node):
            return True
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "exception":
                return True
            if any(
                kw.arg == "exc_info"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in node.keywords
            ):
                return True
    return False


def _describe_silent_kind(handler: ast.ExceptHandler) -> str:
    """무음 문장의 대표 형태 — 사람이 허용 목록에 이유를 적을 때 참고한다."""
    for stmt in handler.body:
        if isinstance(stmt, ast.Return):
            return "return" if stmt.value is None else "return None/False"
        if isinstance(stmt, ast.Continue):
            return "continue"
        if isinstance(stmt, ast.Pass):
            return "pass"
        if isinstance(stmt, ast.Break):
            return "break"
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            return "= None/False"
    return "silent"


def _handlers(tree: ast.AST) -> list[ast.ExceptHandler]:
    """파일 전체의 `except` 핸들러를 소스 순서대로."""
    try_nodes: tuple[type[ast.AST], ...] = (ast.Try,)
    try_star = getattr(ast, "TryStar", None)
    if try_star is not None:
        try_nodes = (ast.Try, try_star)
    found = [node.handlers for node in ast.walk(tree) if isinstance(node, try_nodes)]
    flat = [handler for handlers in found for handler in handlers]
    return sorted(flat, key=lambda h: (h.lineno, h.col_offset))


def analyze_source(
    source: str, path: str = "<source>"
) -> tuple[list[tuple[str, int, str]], list[int]]:
    """소스 하나를 분석해 (위반 `(경로, 줄, 형태)`, 오탐 후보 줄)을 낸다."""
    tree = ast.parse(source, filename=path)
    violations: list[tuple[str, int, str]] = []
    fallbacks: list[int] = []
    for handler in _handlers(tree):
        if _has_signal(handler):
            continue
        if handler.body and all(_is_silent_statement(stmt) for stmt in handler.body):
            violations.append((path, handler.lineno, _describe_silent_kind(handler)))
        else:
            fallbacks.append(handler.lineno)
    return violations, fallbacks


def analyze_files(paths: list[Path]) -> tuple[list[tuple[str, int, str]], list[tuple[str, int]]]:
    """여러 파일을 분석한다. 경로는 `src/backend` 기준 상대 경로로 낸다."""
    violations: list[tuple[str, int, str]] = []
    fallbacks: list[tuple[str, int]] = []
    for path in paths:
        rel = path.resolve().relative_to(_BACKEND.resolve()).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            # 조용히 건너뛰면 검사 대상이 줄어든 것을 아무도 모른다 — 실패로 올린다.
            raise ValueError(f"{rel}: UTF-8로 읽을 수 없다({type(exc).__name__})") from exc
        found, candidates = analyze_source(source, rel)
        violations.extend(found)
        fallbacks.extend((rel, line) for line in candidates)
    return (
        sorted(violations, key=lambda v: (v[0], v[1])),
        sorted(fallbacks, key=lambda c: (c[0], c[1])),
    )


def _load_allow(path: Path) -> list[tuple[str, int, str]]:
    """허용 목록을 읽는다. 형식이 틀리거나 이유가 비었거나 중복이면 실패로 올린다."""
    entries: list[tuple[str, int, str]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(" · ")]
        if len(parts) < 3 or not all(parts[:3]):
            pytest.fail(f"허용 목록 {lineno}줄 형식 오류(경로:줄 · 규칙 · 이유): {raw!r}")
        loc, rule = parts[0], parts[1]
        file_part, sep, line_part = loc.rpartition(":")
        if not sep or not line_part.isdigit() or rule != RULE:
            pytest.fail(f"허용 목록 {lineno}줄 위치·규칙 오류(규칙은 {RULE}): {raw!r}")
        key = (file_part, int(line_part), rule)
        if key in entries:
            pytest.fail(f"허용 목록 {lineno}줄 중복: {raw!r}")
        entries.append(key)
    return sorted(entries)


def _fmt(items: list[tuple[str, int, str]]) -> str:
    """위반 목록을 사람이 읽는 줄로."""
    return "\n".join(f"  {p}:{n} · {k}" for p, n, k in items) or "  (없음)"


@pytest.mark.parametrize(
    ("label", "source", "expect_violation"),
    [
        (
            "return None",
            "def f():\n    try:\n        g()\n    except Exception:\n        return None\n",
            True,
        ),
        (
            "return False",
            "def f():\n    try:\n        g()\n    except Exception:\n        return False\n",
            True,
        ),
        (
            "bare return",
            "def f():\n    try:\n        g()\n    except OSError:\n        return\n",
            True,
        ),
        ("pass", "def f():\n    try:\n        g()\n    except ImportError:\n        pass\n", True),
        (
            "continue",
            "def f():\n    for _ in []:\n        try:\n            g()\n        except Exception:\n            continue\n",
            True,
        ),
        (
            "= None",
            "def f():\n    x = 1\n    try:\n        g()\n    except Exception:\n        x = None\n",
            True,
        ),
        (
            "type name",
            "def f():\n    try:\n        g()\n    except Exception as exc:\n        log.warning('%s', type(exc).__name__)\n",
            False,
        ),
        (
            "exc_info",
            "def f():\n    try:\n        g()\n    except Exception:\n        log.warning('실패', exc_info=True)\n",
            False,
        ),
        (
            "logger.exception",
            "def f():\n    try:\n        g()\n    except Exception:\n        log.exception('실패')\n",
            False,
        ),
        ("raise", "def f():\n    try:\n        g()\n    except Exception:\n        raise\n", False),
        (
            "substitute value",
            "def f():\n    try:\n        g()\n    except Exception:\n        return ''\n",
            False,
        ),
        (
            "substitute call",
            "def f():\n    try:\n        g()\n    except Exception:\n        return fallback()\n",
            False,
        ),
    ],
)
def test_boundary_on_synthetic_source(label: str, source: str, expect_violation: bool) -> None:
    """경계 확인 — 무음은 잡고, 신호·대체 값은 통과시킨다(규칙이 꺼진 검사기는 늘 0건을 낸다)."""
    violations, _ = analyze_source(source)
    assert (
        bool(violations) is expect_violation
    ), f"{label}: 위반 판정이 기대와 다르다 — {violations}"


def test_nested_function_raise_is_not_a_signal() -> None:
    """핸들러 안에 정의한 함수의 `raise`를 신호로 오인하지 않는다(중첩 스코프 미진입).

    신호로 오인하면 그 핸들러는 통과(건너뜀)해 오탐 후보 목록에도 남지 않는다.
    그래서 "오탐 후보에 있다"가 곧 "신호를 못 봤다"의 증거다.
    """
    source = (
        "def f():\n"
        "    try:\n"
        "        g()\n"
        "    except Exception:\n"
        "        def inner():\n"
        "            raise ValueError\n"
        "        pass\n"
    )
    violations, fallbacks = analyze_source(source)
    assert violations == [], violations
    assert fallbacks == [4], fallbacks


def test_zero_files_is_an_error() -> None:
    """검사 대상이 0개면 통과가 아니라 실패다(빈 스캔은 공허한 통과다)."""
    py_files = list(_GOLDEN.rglob("*.py"))
    assert py_files, f"검사 대상 .py가 0개다 — 경로가 틀렸다: {_GOLDEN}"


def test_allow_list_format() -> None:
    """허용 목록은 `경로:줄 · 규칙 · 이유` 형식이고 이유가 비면 안 된다."""
    entries = _load_allow(_ALLOW)
    assert entries, f"허용 목록이 비었다: {_ALLOW}"


def test_golden_zone_matches_allow_list() -> None:
    """골든 구역의 무음 삼키기 건수가 허용 목록과 정확히 같아야 한다."""
    py_files = list(_GOLDEN.rglob("*.py"))
    assert py_files, f"검사 대상 .py가 0개다 — 경로가 틀렸다: {_GOLDEN}"

    actual, _fallbacks = analyze_files(py_files)
    allowed = _load_allow(_ALLOW)

    # 비교 열쇠는 (경로, 줄)이다 — 위반 쪽 셋째 칸은 무음 형태, 허용 목록 쪽은 규칙 이름이라 다르다.
    kinds = {(p, n): k for p, n, k in actual}
    new = sorted(set(kinds) - {(p, n) for p, n, _r in allowed})
    stale = sorted({(p, n) for p, n, _r in allowed} - set(kinds))
    new_rows = [(p, n, kinds[(p, n)]) for p, n in new]
    stale_rows = [(p, n, RULE) for p, n in stale]
    assert not new and not stale, (
        "조용한 값 삼키기 게이트 불일치\n"
        f"[새 건 — 허용 목록에 없음] 신호를 남기거나, Kiki 결정 후 이유와 함께 목록에 올린다:\n{_fmt(new_rows)}\n"
        f"[남은 줄 — 실제로는 없음] 목록에서 지운다(줄 번호가 옮겨졌으면 고친다):\n{_fmt(stale_rows)}"
    )


def test_old_zone_baseline_sums_match() -> None:
    """옛 구역 기준선 TSV의 패키지별 합이 합계 행과 같아야 한다(게이트 아님 · 기록의 정합)."""
    lines = [ln for ln in _BASELINE.read_text(encoding="utf-8").splitlines() if ln.strip()]
    header = lines[0].split("\t")
    assert header[:3] == ["패키지", "파일 수", "무음_위반"], f"기준선 TSV 머리말이 다르다: {header}"
    rows = [ln.split("\t") for ln in lines[1:] if not ln.startswith("합계\t")]
    assert rows, "기준선 TSV에 패키지 행이 없다"
    assert all(len(r) == len(header) for r in rows), "기준선 TSV 열 수가 행마다 다르다"
    total = next(ln for ln in lines if ln.startswith("합계\t")).split("\t")
    for i in range(1, len(header)):
        assert sum(int(r[i]) for r in rows) == int(total[i]), f"{header[i]} 패키지 합 != 합계 행"
