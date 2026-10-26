"""[OPS-138 ④] 상대경로 모듈 상수를 cwd 의존 연산에 쓰는 가드가 더 없는가 — AST 전수 스캔 동결.

왜 이 테스트가 있는가
--------------------
`review_status_domains`는 `_REPO_CORPUS_DIR = Path("data/corpus")`(상대경로)를 `.resolve()`로 비교해
"레포 코퍼스 아래인가"를 판정했다. 작업 디렉터리가 레포 루트가 아니면(CI 백엔드 잡의 cwd =
`src/backend`) 같은 입력에 거부 대신 `None`을 돌려줘 **가드가 에러 없이 꺼졌다**. 이 부류는 정상
입력(레포 루트 실행)에서 초록이라 평소엔 보이지 않으므로, 같은 모양이 다른 곳에 생기지 않게
소스를 구조(AST)로 훑어 동결한다.

스캔이 잡는 모양 (두 가지 — 둘 다 양성 대조군으로 확인한다)
  ① 같은 모듈이 `Path("a/b")`(상대 리터럴)를 상수로 들고, 그 상수에 `.resolve()`·
     `.is_relative_to()` 등 cwd 의존 연산을 직접 건다.
  ② 다른 모듈이 정의한 그런 상수(예: `KNOWN_CORPORA` 딕트)를 import해 `for x in NAME.values():
     x.resolve()` / `any(... x.resolve() ... for x in NAME.values())`로 순회하며 건다.
     — 수정 전 `_is_known_fixed`가 정확히 이 모양이었다. ①만 보는 스캐너는 이것을 놓친다.

한계(명시): 상수를 별칭·함수 인자로 우회해 연산하는 모양은 이 스캔이 보지 못한다. 그래서 스캔
통과를 "cwd 의존 없음의 증명"으로 읽지 않고, 알려진 모양이 새로 생기지 않았다는 회귀 가드로만 쓴다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCAN_ROOTS = ("src/backend/whymath_backend", "scripts")

# cwd에 붙어 결과가 달라지는 `Path` 연산.
_CWD_OPS = frozenset({"resolve", "absolute", "is_relative_to", "samefile", "relative_to"})
_DICT_VIEWS = frozenset({"values", "items"})
_COMPREHENSIONS = (ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)


def _is_relative_path_literal(node: ast.expr) -> bool:
    """`Path("a/b")` 또는 `Path("a") / "b"` — 첫 인자가 절대경로·변수가 아닌 문자열 리터럴."""
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Path" and node.args:
        first = node.args[0]
        return (
            isinstance(first, ast.Constant)
            and isinstance(first.value, str)
            and not first.value.startswith(("/", "~"))
            and ":" not in first.value[:3]  # 윈도 드라이브(`C:\`) 리터럴 제외
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _is_relative_path_literal(node.left)
    return False


def _relative_path_consts(tree: ast.Module) -> dict[str, int]:
    """모듈 최상위에서 상대 Path 리터럴을 직접/딕트·튜플 값으로 들고 있는 상수 → 정의 줄."""
    consts: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        hit = _is_relative_path_literal(value)
        if not hit and isinstance(value, ast.Dict):
            hit = any(v is not None and _is_relative_path_literal(v) for v in value.values)
        if not hit and isinstance(value, (ast.Tuple, ast.List, ast.Set)):
            hit = any(_is_relative_path_literal(v) for v in value.elts)
        if hit:
            for target in targets:
                if isinstance(target, ast.Name):
                    consts[target.id] = node.lineno
    return consts


def scan_source(source: str, imported: frozenset[str] = frozenset()) -> list[tuple[str, int, str]]:
    """한 소스에서 (상수 이름, 줄, 연산) 위반 지점을 모은다. `imported`는 다른 모듈이 정의한 상수명."""
    tree = ast.parse(source)
    consts = _relative_path_consts(tree)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in imported:
                    consts.setdefault(alias.asname or alias.name, 0)
    found: set[tuple[str, int, str]] = set()
    for node in ast.walk(tree):
        # ① NAME.resolve() / NAME.is_relative_to(...) — 상수를 직접 연산
        if isinstance(node, ast.Attribute) and node.attr in _CWD_OPS:
            name = getattr(node.value, "id", None)
            if name in consts:
                found.add((name, node.lineno, node.attr))
        # ② for x in NAME.values(): ... x.resolve() — 순회 본문 전체(컴프리헨션은 elt가 generators
        #    밖에 있으므로 바깥 노드 전체를 훑는다)
        loops: list[tuple[ast.expr, ast.AST]] = []
        if isinstance(node, ast.For):
            loops.append((node.iter, node))
        if isinstance(node, _COMPREHENSIONS):
            loops.extend((gen.iter, node) for gen in node.generators)
        for iterable, scope in loops:
            if (
                isinstance(iterable, ast.Call)
                and isinstance(iterable.func, ast.Attribute)
                and iterable.func.attr in _DICT_VIEWS
                and isinstance(iterable.func.value, ast.Name)
                and iterable.func.value.id in consts
            ):
                for sub in ast.walk(scope):
                    if isinstance(sub, ast.Attribute) and sub.attr in _CWD_OPS:
                        found.add(
                            (
                                f"{iterable.func.value.id}.{iterable.func.attr}()",
                                sub.lineno,
                                sub.attr,
                            )
                        )
    return sorted(found)


def _sources() -> dict[Path, str]:
    files = [p for root in _SCAN_ROOTS for p in sorted((_REPO_ROOT / root).rglob("*.py"))]
    return {p: p.read_text(encoding="utf-8") for p in files}


# ══════════════════════════════════════════════════════════════════════════
class TestScannerIsNotVacuous:
    """스캔 0건이 '문제 없음'이 아니라 '못 봄'일 수 있다 — 양성 대조군으로 스캐너를 먼저 검증한다."""

    def test_direct_constant_resolve_is_flagged(self) -> None:
        """모양 ① — 수정 전 `_REPO_CORPUS_DIR` 그대로."""
        src = (
            "from pathlib import Path\n"
            '_DIR = Path("data/corpus")\n'
            "def f(p):\n"
            "    return p.resolve().is_relative_to(_DIR.resolve())\n"
        )
        assert [(n, op) for n, _, op in scan_source(src)] == [("_DIR", "resolve")]

    def test_imported_constant_iterated_in_a_generator_is_flagged(self) -> None:
        """모양 ② — 수정 전 `_is_known_fixed` 그대로(제너레이터 식의 elt가 generators 밖에 있다)."""
        src = (
            "from other import KNOWN\n"
            "def g(p):\n"
            "    return any(p == k.resolve() for k in KNOWN.values())\n"
        )
        assert scan_source(src) == []  # import 정보 없이는 이름을 상수로 알 수 없다(사각의 실증)
        flagged = scan_source(src, imported=frozenset({"KNOWN"}))
        assert [(n, op) for n, _, op in flagged] == [("KNOWN.values()", "resolve")]

    def test_for_loop_over_dict_values_is_flagged(self) -> None:
        src = (
            "from pathlib import Path\n"
            'TABLE = {"a": Path("data/a.jsonl")}\n'
            "def g(p):\n"
            "    for k in TABLE.values():\n"
            "        if p == k.resolve():\n"
            "            return True\n"
        )
        assert [(n, op) for n, _, op in scan_source(src)] == [("TABLE.values()", "resolve")]

    def test_anchored_constants_are_not_flagged(self) -> None:
        """음성 대조군 — 모듈 파일 위치로 앵커한 상수를 쓰면 잡지 않는다(과잉 탐지 방지)."""
        src = (
            "from pathlib import Path\n"
            "_REPO_ROOT = Path(__file__).resolve().parents[4]\n"
            '_DIR = _REPO_ROOT / "data" / "corpus"\n'
            "def f(p):\n"
            "    return p.resolve().is_relative_to(_DIR.resolve())\n"
        )
        assert scan_source(src) == []

    def test_the_real_pre_fix_module_shape_is_covered(self) -> None:
        """수정 전 `review_status_domains`의 두 지점을 합성 소스로 재현해도 둘 다 잡힌다."""
        src = (
            "from pathlib import Path\n"
            "from m import KNOWN_CORPORA\n"
            '_REPO_CORPUS_DIR = Path("data/corpus")\n'
            "def a(p):\n"
            "    return any(p == k.resolve() for k in KNOWN_CORPORA.values())\n"
            "def b(p):\n"
            "    return p.is_relative_to(_REPO_CORPUS_DIR.resolve())\n"
        )
        names = {n for n, _, _ in scan_source(src, imported=frozenset({"KNOWN_CORPORA"}))}
        assert names == {"KNOWN_CORPORA.values()", "_REPO_CORPUS_DIR"}

    def test_scan_sees_a_real_population(self) -> None:
        """대상이 0이면 전수 가드는 공허하게 통과한다 — 실제 파일·상수가 보여야 한다."""
        sources = _sources()
        assert len(sources) > 500, f"스캔 대상이 비정상적으로 적다: {len(sources)}"
        defined: set[str] = set()
        for text in sources.values():
            defined |= set(_relative_path_consts(ast.parse(text)))
        assert "KNOWN_CORPORA" in defined, "알려진 상대 Path 딕트 상수를 못 본다 — 스캐너 사각"
        assert len(defined) >= 20, f"상대 Path 상수가 비정상적으로 적다: {len(defined)}"


class TestNoRelativePathConstantIsUsedWithCwdDependentOps:
    def test_repository_has_no_such_guard(self) -> None:
        """OPS-138 ④ 전수 결과 — 0건. 새로 생기면 cwd 앵커(`parents[N]`)로 고치거나 사유를 적어 허용한다."""
        sources = _sources()
        defined: set[str] = set()
        for text in sources.values():
            defined |= set(_relative_path_consts(ast.parse(text)))
        imported = frozenset(defined)
        violations = {
            str(path.relative_to(_REPO_ROOT)): hits
            for path, text in sources.items()
            if (hits := scan_source(text, imported))
        }
        assert violations == {}, (
            "상대경로 모듈 상수에 cwd 의존 연산(.resolve() 등)을 거는 지점이 있다 — 작업 디렉터리가 "
            "레포 루트가 아니면 가드가 침묵으로 꺼질 수 있다(OPS-138). `Path(__file__).resolve()."
            "parents[N]` 기준으로 앵커하라:\n"
            f"{violations}"
        )


@pytest.mark.parametrize(
    "module",
    ["review_status_domains"],
)
def test_the_fixed_module_has_a_file_anchored_repo_root(module: str) -> None:
    """수정 대상 모듈이 실제로 파일 위치 기준 루트를 들고 있다(스캔 통과가 우연이 아님을 이중 확인)."""
    text = (_REPO_ROOT / "src/backend/whymath_backend/harness" / f"{module}.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(text)
    anchored = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_REPO_ROOT" for t in node.targets)
        and "__file__" in ast.unparse(node.value)
    ]
    assert anchored, f"{module}: `_REPO_ROOT = Path(__file__)...` 앵커가 없다"
