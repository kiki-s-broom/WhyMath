"""parametrize 수집 순서 결정성 거버넌스 — AST 전수 (OPS-144 ③).

**무엇을 막는가**: `@pytest.mark.parametrize`의 값·`ids`가 *프로세스마다 달라지는 원천*에서 나오면
pytest-xdist 워커끼리 수집한 테스트 목록이 순서까지 비교되어 "Different tests were collected"로
**수집 단계에서** 실패한다. 실례는 `db/test_to_schema_null_seam.py`가 `Base.registry.mappers`
(= `frozenset[Mapper]`, 순회 순서가 객체 주소 해시에 의존)를 순회해 목록을 만든 것이다.

**왜 CI가 못 봤나(OPS-144 ⑤ 실측)**: pytest-randomly 3.16.0이 항목을 `md5(seed::nodeid)`로 다시
정렬한다. 이 키는 nodeid만의 함수라 워커마다 수집 순서가 달라도 정렬 결과가 같아져 결함이
가려진다. `-p no:randomly`로 돌리면 즉시 재현된다. 즉 이 부류는 **플러그인 하나가 가리고 있던**
것이므로 그 플러그인이 아니라 테스트 쪽에서 막아야 한다.

**판정 기준은 실측표다**(2026-10-17, `-n 2 -p no:randomly`, 형태마다 3회 — 이 표가 탐지기의 정답):

    깨짐  문자열 집합을 argvalues로 쓴 경우   {"a","b",...}        (PYTHONHASHSEED 의존)
    깨짐  uuid4를 문자열로 만든 값            [str(uuid.uuid4())]  (값이 곧 id)
    깨짐  ids 안의 time/random                ids=lambda v: f"{v}-{time.time_ns()}"
    안전  uuid4 *객체* 값                    [uuid.uuid4()]       (객체는 id가 x0·x1 순번)
    안전  집합이 *원소*로 든 경우             [{"a","b"}, {"c"}]   (순회되지 않음)
    안전  정수 집합                          {1, 2, 3, 40}        (정수 해시는 결정적)
    안전  sorted(...)로 감싼 경우             sorted({"a","b"})

그래서 탐지기는 두 가지를 따로 본다.
  ① **순회 순서가 비결정인 이터러블** — 집합(문자열 등 해시가 무작위인 원소)·`frozenset`·`.mappers`가
     *argvalues/ids의 순서를 정하는 자리*(그대로·`list()`·컴프리헨션의 `in`·루프로 채운 목록)에 흘러든
     경우. `sorted(...)`는 순서를 고정하므로 하위를 보지 않는다. 원소로 든 집합은 순회되지 않아 무해하다.
  ② **id로 렌더링되는 비결정 값** — `time`·`random`·`secrets`·`os.urandom`·`id()`·`hash()`는 원시값이라
     어디에 있든 id가 된다. `uuid1/uuid4`는 *문자열화*(`str`·f-string·`.hex` 등)될 때만 id가 된다.

같은 모듈 안의 변수·함수는 따라간다. 함수는 본문이 아니라 **반환식**을 평가하므로 `return sorted(...)`
는 본문에서 무엇을 순회하든 깨끗하다.

**한계(정직)**: ① 다른 모듈에서 임포트한 이름·메서드 호출 결과는 따라가지 않는다(불투명 — 같은 모듈
해석만) ② 파일시스템 목록(`glob`·`iterdir`)의 순서는 같은 머신에서는 워커 간에 같으므로 대상이 아니다
③ 집합 원소의 타입은 리터럴 상수일 때만 판별한다 — 정수·실수·불리언·None만 든 리터럴은 결정적으로
보고, 그 밖(문자열·이름·호출)은 무작위로 본다. 이 탐지기가 못 보는 원천은 `-p no:randomly -n 2`
수집 일치로만 잡힌다(OPS-144 notes의 전수 실측 방법).
"""

from __future__ import annotations

import ast
import functools
import hashlib
import textwrap
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCAN_ROOT = _ROOT / "tests" / "backend"

# 스캔 0건 가드의 바닥선 — 실측(2026-10-17) parametrize/fixture 자리가 790건대였다. 대폭 낮춘 값이라
# 정상적인 테스트 정리로는 닿지 않고, 파서가 대상을 못 보는 사고(디렉터리 오지정·훅 누락)는 잡는다.
_MIN_SITES = 300

# 호출 결과가 *원시값*(int/float/bytes/str)이라 어디에 있든 id가 되는 비결정 호출.
_BARE_PRIMITIVE = frozenset(
    {"urandom", "token_hex", "token_bytes", "token_urlsafe", "getrandbits", "randint", "randrange"}
    | {"id", "hash"}
)
_ATTR_PRIMITIVE: dict[str, frozenset[str]] = {
    "random": frozenset(
        {
            "random",
            "randint",
            "randrange",
            "choice",
            "choices",
            "sample",
            "shuffle",
            "uniform",
            "getrandbits",
            "gauss",
        }
    ),
    "secrets": frozenset(
        {"token_hex", "token_bytes", "token_urlsafe", "randbelow", "choice", "randbits"}
    ),
    "os": frozenset({"urandom"}),
    "time": frozenset({"time", "time_ns", "monotonic", "perf_counter"}),
    "datetime": frozenset({"now", "utcnow", "today"}),
    "date": frozenset({"today"}),
}
# 호출 결과가 *객체*(UUID)라 그대로면 id가 순번이 되고, 문자열화될 때만 값이 id가 된다.
_UUID_OBJECT = frozenset({"uuid1", "uuid4"})
# 이 호출·속성을 거치면 값이 문자열/정수로 렌더링된다.
_STRINGIFY_CALLS = frozenset({"str", "repr", "format", "int", "bytes", "hex"})
_STRINGIFY_ATTRS = frozenset({"hex", "urn", "int", "bytes"})
# 인자의 순서를 그대로 이어받는 호출 — 인자가 비결정이면 결과도 비결정이다.
_ORDER_PRESERVING = frozenset(
    {
        "list",
        "tuple",
        "iter",
        "reversed",
        "enumerate",
        "zip",
        "chain",
        "from_iterable",
        "islice",
        "product",
        "combinations",
        "permutations",
        "dict",
        "OrderedDict",
        "fromkeys",
        "deque",
    }
)
_ORDER_PRESERVING_SKIP_FIRST = frozenset({"map", "filter"})  # 첫 인자는 함수
_SET_METHODS = frozenset(
    {
        "union",
        "intersection",
        "difference",
        "symmetric_difference",
        "copy",
        "keys",
        "values",
        "items",
    }
)
_MUTATORS = frozenset({"append", "extend", "add", "update", "insert", "setdefault"})
_ITER_MUTATORS = frozenset({"extend", "update"})  # 인자를 *순회해* 이어 붙이는 것들
_DETERMINISTIC_CONSTANT_TYPES = (int, float, bool, complex, type(None))

_Found = tuple[int, str, str]  # (줄, 종류, 경유)


@dataclass(frozen=True)
class Hit:
    """비결정 원천이 parametrize 자리로 흘러든 지점."""

    path: str
    site_line: int  # parametrize/fixture 호출 위치
    source_line: int  # 원천 위치
    kind: str
    via: str  # 어떤 이름·함수를 거쳐 왔는지

    def __str__(self) -> str:
        return (
            f"{self.path}:{self.site_line} parametrize ← {self.kind} "
            f"(원천 :{self.source_line}, 경유 {self.via})"
        )


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _root_name(node: ast.AST) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _walk_no_nested_scope(node: ast.AST) -> Iterator[ast.AST]:
    """함수·클래스·람다 안쪽은 들어가지 않는 순회 — 한 층(모듈/함수 본문)의 문장만 본다."""
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        yield from _walk_no_nested_scope(child)


def _bound_or_mutated_names(stmt: ast.stmt) -> set[str]:
    """문장이 값을 정하거나 바꾸는 이름들(대입·`N.append(...)`·`N[k] = ...`)."""
    names: set[str] = set()
    for node in _walk_no_nested_scope(stmt):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                        names.add(sub.id)
                    if isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Name):
                        names.add(sub.value.id)
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            if isinstance(node.target, ast.Name):
                names.add(node.target.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in _MUTATORS and isinstance(node.func.value, ast.Name):
                names.add(node.func.value.id)
    return names


def _is_hash_stable_literal(node: ast.AST) -> bool:
    """원소가 전부 정수·실수·불리언·None 상수인 집합 리터럴/호출 — 순회 순서가 프로세스에 무관하다."""
    if isinstance(node, ast.Set):
        return all(
            isinstance(e, ast.Constant) and isinstance(e.value, _DETERMINISTIC_CONSTANT_TYPES)
            for e in node.elts
        )
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in {"set", "frozenset"}:
            # 빈 `set()`은 허용하지 않는다 — 뒤에서 `.add("문자열")`로 채우면 문자열 집합이 된다.
            if not node.args:
                return False
            arg = node.args[0]
            if len(node.args) == 1 and isinstance(arg, ast.List | ast.Tuple | ast.Set):
                return all(
                    isinstance(e, ast.Constant)
                    and isinstance(e.value, _DETERMINISTIC_CONSTANT_TYPES)
                    for e in arg.elts
                )
            if (
                len(node.args) == 1
                and isinstance(arg, ast.Call)
                and isinstance(arg.func, ast.Name)
                and arg.func.id == "range"
            ):
                return True
    return False


class _Scope:
    """한 층(모듈 또는 함수 본문)의 이름 → 그 이름을 정하거나 바꾸는 문장들."""

    def __init__(
        self, body: list[ast.stmt], parent: _Scope | None, params: frozenset[str] = frozenset()
    ) -> None:
        self.parent = parent
        self.params = params
        self.binders: dict[str, list[ast.stmt]] = defaultdict(list)
        for stmt in body:
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            for name in _bound_or_mutated_names(stmt):
                self.binders[name].append(stmt)

    def resolve(self, name: str) -> list[tuple[ast.stmt, _Scope]]:
        scope: _Scope | None = self
        while scope is not None:
            if name in scope.params:
                return []  # 인자는 호출자 몫 — 불투명
            if name in scope.binders:
                return [(stmt, scope) for stmt in scope.binders[name]]
            scope = scope.parent
        return []


class _Scanner:
    """한 모듈 안에서 이름·함수를 따라가며 비결정 원천을 찾는다."""

    def __init__(self, tree: ast.Module) -> None:
        self.module = _Scope(tree.body, None)
        self.funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {
            n.name: n for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        }

    # ── 함수 해석 ───────────────────────────────────────────────────────
    def _fn_scope(self, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> _Scope:
        args = fn.args
        names = {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
        for extra in (args.vararg, args.kwarg):
            if extra is not None:
                names.add(extra.arg)
        return _Scope(fn.body, self.module, frozenset(names))

    @staticmethod
    def _returns(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.expr]:
        return [
            n.value
            for stmt in fn.body
            for n in _walk_no_nested_scope(stmt)
            if isinstance(n, ast.Return) and n.value is not None
        ]

    # ── ① 순회 순서가 비결정인 이터러블 ─────────────────────────────────
    def unordered(
        self, node: ast.AST, scope: _Scope, via: str, stack: frozenset[str]
    ) -> Iterator[_Found]:
        # `sorted(...)`는 순서 보존 호출 목록(`_ORDER_PRESERVING`)에 없어 아래 어느 갈래에도 걸리지
        # 않는다 — 별도 면제 절이 아니라 "순서를 이어받지 않는 호출"로 자연히 빠진다. 함수의
        # `return sorted(...)`도 같은 이유로 깨끗하다(본문이 아니라 *반환식*을 평가한다).
        # 이 성질은 뮤테이션 M01('sorted'를 순서 보존 목록에 추가)이 동결한다.
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Set):
            if not _is_hash_stable_literal(node):
                yield (line, "집합 리터럴", via)
            return
        if isinstance(node, ast.SetComp):
            yield (line, "집합 컴프리헨션", via)
            return
        if isinstance(node, ast.Attribute) and node.attr == "mappers":
            yield (line, "registry.mappers(frozenset)", via)
            return
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load) and f"u:{node.id}" not in stack:
                for stmt, owner in scope.resolve(node.id):
                    yield from self._stmt_unordered(
                        stmt, node.id, owner, f"{via}→{node.id}", stack | {f"u:{node.id}"}
                    )
            return
        if isinstance(node, ast.ListComp | ast.GeneratorExp | ast.DictComp):
            for gen in node.generators:
                yield from self.unordered(gen.iter, scope, via, stack)
            return
        if isinstance(node, ast.List | ast.Tuple):
            for elt in node.elts:  # 원소는 순회되지 않는다 — `*S` 펼침만 순서를 정한다
                if isinstance(elt, ast.Starred):
                    yield from self.unordered(elt.value, scope, via, stack)
            return
        if isinstance(node, ast.BinOp):
            yield from self.unordered(node.left, scope, via, stack)
            yield from self.unordered(node.right, scope, via, stack)
            return
        if isinstance(node, ast.IfExp):
            yield from self.unordered(node.body, scope, via, stack)
            yield from self.unordered(node.orelse, scope, via, stack)
            return
        if isinstance(node, ast.Subscript):
            # 슬라이스는 순서를 이어받고, 인덱스는 원소 하나라 순서와 무관하다.
            if isinstance(node.slice, ast.Slice):
                yield from self.unordered(node.value, scope, via, stack)
            return
        if isinstance(node, ast.Call):
            yield from self._call_unordered(node, scope, via, stack)

    def _call_unordered(
        self, node: ast.Call, scope: _Scope, via: str, stack: frozenset[str]
    ) -> Iterator[_Found]:
        func = node.func
        name = _call_name(node)
        if isinstance(func, ast.Name) and func.id in {"set", "frozenset"}:
            if not _is_hash_stable_literal(node):
                yield (node.lineno, f"{func.id}()", via)
            return
        if isinstance(func, ast.Name) and func.id in self.funcs:
            if f"f:{func.id}" in stack:
                return
            fn = self.funcs[func.id]
            returns = self._returns(fn)
            fn_scope = self._fn_scope(fn)
            for ret in returns:
                yield from self.unordered(
                    ret, fn_scope, f"{via}→{func.id}()", stack | {f"f:{func.id}"}
                )
            return
        if isinstance(func, ast.Attribute) and func.attr in _SET_METHODS:
            yield from self.unordered(func.value, scope, via, stack)
            return
        if name in _ORDER_PRESERVING:
            for arg in node.args:
                yield from self.unordered(arg, scope, via, stack)
            return
        if name in _ORDER_PRESERVING_SKIP_FIRST:
            for arg in node.args[1:]:
                yield from self.unordered(arg, scope, via, stack)

    def _stmt_unordered(
        self, stmt: ast.stmt, name: str, scope: _Scope, via: str, stack: frozenset[str]
    ) -> Iterator[_Found]:
        """`name`의 *순서*를 정하는 문장 — 대입의 값, 루프의 이터러블, extend/update의 인자."""
        for node in _walk_no_nested_scope(stmt):
            if isinstance(node, ast.For | ast.AsyncFor):
                yield from self.unordered(node.iter, scope, via, stack)
            elif isinstance(node, ast.Assign):
                if any(
                    isinstance(t, ast.Name) and t.id == name
                    for target in node.targets
                    for t in ast.walk(target)
                ):
                    yield from self.unordered(node.value, scope, via, stack)
            elif isinstance(node, ast.AnnAssign | ast.AugAssign):
                if isinstance(node.target, ast.Name) and node.target.id == name and node.value:
                    yield from self.unordered(node.value, scope, via, stack)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if (
                    node.func.attr in _ITER_MUTATORS
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == name
                ):
                    for arg in node.args:
                        yield from self.unordered(arg, scope, via, stack)

    # ── ② id로 렌더링되는 비결정 값 ─────────────────────────────────────
    def rendered(
        self,
        node: ast.AST,
        scope: _Scope,
        via: str,
        stack: frozenset[str],
        stringified: bool = False,
    ) -> Iterator[_Found]:
        if isinstance(node, ast.Dict | ast.DictComp | ast.Set | ast.SetComp):
            # dict·집합이 *값 하나*면 pytest는 id를 `argname+순번`으로 붙인다(`_idval`은 str·bytes·
            # 수·불리언·Enum·클래스/함수만 값으로 렌더링한다). 안쪽 `str(uuid4())`는 id가 아니다.
            # 실측: `{"k": str(uuid4())}`를 값으로 쓴 7곳이 -n 2 -p no:randomly에서 안전했다.
            return
        if isinstance(node, ast.Call):
            kind = self._random_kind(node, stringified)
            if kind:
                yield (node.lineno, kind, via)
            name = _call_name(node)
            if isinstance(node.func, ast.Name) and node.func.id in self.funcs:
                fn_name = node.func.id
                if f"rf:{fn_name}" not in stack:
                    fn = self.funcs[fn_name]
                    fn_scope = self._fn_scope(fn)
                    for ret in self._returns(fn):
                        yield from self.rendered(
                            ret,
                            fn_scope,
                            f"{via}→{fn_name}()",
                            stack | {f"rf:{fn_name}"},
                            stringified,
                        )
            inner = stringified or name in _STRINGIFY_CALLS
            for child in ast.iter_child_nodes(node):
                yield from self.rendered(child, scope, via, stack, inner)
            return
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load) and f"r:{node.id}" not in stack:
                for stmt, owner in scope.resolve(node.id):
                    yield from self.rendered(
                        stmt, owner, f"{via}→{node.id}", stack | {f"r:{node.id}"}, stringified
                    )
            return
        inner = stringified
        if isinstance(node, ast.JoinedStr | ast.FormattedValue):
            inner = True
        elif isinstance(node, ast.Attribute) and node.attr in _STRINGIFY_ATTRS:
            inner = True
        elif (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Mod)
            and isinstance(node.left, ast.Constant)
            and isinstance(node.left.value, str)
        ):
            inner = True  # "%s" % uuid4()
        for child in ast.iter_child_nodes(node):
            yield from self.rendered(child, scope, via, stack, inner)

    @staticmethod
    def _random_kind(node: ast.Call, stringified: bool) -> str | None:
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in _BARE_PRIMITIVE:
                return f"{func.id}()"
            if func.id in _UUID_OBJECT and stringified:
                return f"문자열화된 {func.id}()"
        elif isinstance(func, ast.Attribute):
            root = _root_name(func)
            if root in _ATTR_PRIMITIVE and func.attr in _ATTR_PRIMITIVE[root]:
                return f"{root}.{func.attr}()"
            if root == "uuid" and func.attr in _UUID_OBJECT and stringified:
                return f"문자열화된 uuid.{func.attr}()"
        return None


def _param_exprs(call: ast.Call) -> list[ast.AST]:
    """순서·id에 영향을 주는 인자(값·ids)만 뽑는다. `argnames`·`indirect`는 무관하다."""
    name = _call_name(call)
    exprs: list[ast.AST] = []
    if name == "parametrize":
        exprs.extend(call.args[1:2])
        exprs.extend(kw.value for kw in call.keywords if kw.arg in {"argvalues", "ids"})
    elif name == "fixture":
        exprs.extend(kw.value for kw in call.keywords if kw.arg in {"params", "ids"})
    return exprs


def scan_source(source: str, path: str = "<memory>") -> tuple[int, list[Hit]]:
    """소스 한 벌을 검사한다. (parametrize/fixture 자리 수, 위반 목록)."""
    tree = ast.parse(source)
    scanner = _Scanner(tree)
    sites = 0
    hits: set[Hit] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        exprs = _param_exprs(node)
        if _call_name(node) == "parametrize" or exprs:
            sites += 1
        for expr in exprs:
            found = [
                *scanner.unordered(expr, scanner.module, "직접", frozenset()),
                *scanner.rendered(expr, scanner.module, "직접", frozenset()),
            ]
            hits.update(Hit(path, node.lineno, line, kind, via) for line, kind, via in found)
    return sites, sorted(hits, key=lambda h: (h.path, h.site_line, h.source_line, h.kind))


@functools.cache  # 같은 워커에서 두 전수 테스트가 같은 결과를 쓴다 — 1058개 파일 파싱을 한 번만
def _scan_tree() -> tuple[int, int, list[Hit]]:
    files = sorted(_SCAN_ROOT.rglob("*.py"))
    total_sites = 0
    hits: list[Hit] = []
    for file in files:
        sites, found = scan_source(file.read_text(encoding="utf-8"), str(file.relative_to(_ROOT)))
        total_sites += sites
        hits.extend(found)
    return len(files), total_sites, hits


# ──────────────────────────────────────────────────────────────────────────
# 1) 저장소 전수 — 비결정 원천이 parametrize 자리로 흘러든 곳이 없다
# ──────────────────────────────────────────────────────────────────────────
def test_scan_reaches_parametrize_sites() -> None:
    """스캔 0건 가드 — 대상을 못 본 전수 검사는 *공허하게* 통과한다."""
    n_files, n_sites, _ = _scan_tree()
    assert n_files > 100, f"스캔한 파일이 {n_files}개 — 스캔 루트({_SCAN_ROOT})를 확인하라"
    assert (
        n_sites >= _MIN_SITES
    ), f"parametrize/fixture 자리가 {n_sites}건뿐 — 탐지기가 대상을 못 보고 있다(바닥선 {_MIN_SITES})"


def test_no_nondeterministic_parametrize_sources() -> None:
    """parametrize 값·ids가 프로세스마다 달라지는 원천에서 나오면 red.

    고치는 법: 원천을 `sorted(..., key=...)`로 감싸거나(예: ORM 클래스는 모듈·한정명·컬럼명 키),
    id를 값에서 결정적으로 만든다(UUID는 고정 리터럴). 이 오류는 `-p no:randomly`에서만
    보이므로 pytest-randomly가 켜진 CI에서는 *통과하는 채로* 숨는다 — 이 테스트가 그 사각이다.
    """
    _, _, hits = _scan_tree()
    assert not hits, "xdist 수집 불일치를 낳는 parametrize 원천:\n" + "\n".join(
        f"  - {h}" for h in hits
    )


# ──────────────────────────────────────────────────────────────────────────
# 2) 탐지기 자체의 변별력 — 양성/음성을 쌍으로 둔다(항상 red/항상 green인 탐지기를 막는다)
#    양성·음성 표는 모듈 docstring의 실측표(깨짐/안전)를 그대로 옮긴 것이다.
# ──────────────────────────────────────────────────────────────────────────
_POSITIVE = {
    "문자열 집합을 argvalues로": """
        import pytest
        @pytest.mark.parametrize("x", {"a", "b"})
        def test_a(x): ...
    """,
    "set() 호출": """
        import pytest
        @pytest.mark.parametrize("x", set(["a", "b"]))
        def test_a(x): ...
    """,
    "frozenset 상수를 이름으로 경유": """
        import pytest
        NAMES = frozenset({"a", "b"})
        @pytest.mark.parametrize("x", NAMES)
        def test_a(x): ...
    """,
    "list(집합)": """
        import pytest
        NAMES = {"a", "b"}
        @pytest.mark.parametrize("x", list(NAMES))
        def test_a(x): ...
    """,
    "집합을 순회하는 컴프리헨션": """
        import pytest
        NAMES = {"a", "b"}
        @pytest.mark.parametrize(("x", "y"), [(n, 1) for n in NAMES])
        def test_a(x, y): ...
    """,
    "집합 합집합": """
        import pytest
        A = frozenset({"a"})
        B = frozenset({"b"})
        @pytest.mark.parametrize("x", A | B)
        def test_a(x): ...
    """,
    "문자열화된 uuid4 값": """
        import uuid, pytest
        @pytest.mark.parametrize("x", [str(uuid.uuid4())])
        def test_a(x): ...
    """,
    "bare 임포트한 uuid4 문자열화": """
        import pytest
        from uuid import uuid4
        @pytest.mark.parametrize("x", [str(uuid4())])
        def test_a(x): ...
    """,
    "집합 컴프리헨션": """
        import pytest
        @pytest.mark.parametrize("x", {n.upper() for n in ["a", "b"]})
        def test_a(x): ...
    """,
    "f-string 속 uuid4 값": """
        import uuid, pytest
        @pytest.mark.parametrize("x", [f"case-{uuid.uuid4()}"])
        def test_a(x): ...
    """,
    "uuid4().hex": """
        import uuid, pytest
        ID = uuid.uuid4().hex
        @pytest.mark.parametrize("x", [ID])
        def test_a(x): ...
    """,
    "ids 안의 time": """
        import time, pytest
        @pytest.mark.parametrize("x", [1, 2], ids=lambda v: f"{v}-{time.time_ns()}")
        def test_a(x): ...
    """,
    "값으로 쓰인 time": """
        import time, pytest
        @pytest.mark.parametrize("x", [time.time()])
        def test_a(x): ...
    """,
    "registry.mappers 를 순회하는 함수": """
        import pytest
        def _cases():
            out = []
            for m in Base.registry.mappers:
                out.append(m.class_)
            return out
        @pytest.mark.parametrize("c", _cases())
        def test_a(c): ...
    """,
    "모듈 수준 for 루프로 채운 목록": """
        import pytest
        CASES = []
        for m in Base.registry.mappers:
            CASES.append(m)
        @pytest.mark.parametrize("c", CASES)
        def test_a(c): ...
    """,
    "집합 펼침 *": """
        import pytest
        NAMES = {"a", "b"}
        @pytest.mark.parametrize("x", [*NAMES, "c"])
        def test_a(x): ...
    """,
    "집합에서 만든 목록의 슬라이스": """
        import pytest
        NAMES = {"a", "b", "c"}
        @pytest.mark.parametrize("x", list(NAMES)[:2])
        def test_a(x): ...
    """,
    "map 으로 변환한 집합": """
        import pytest
        NAMES = {"a", "b"}
        @pytest.mark.parametrize("x", list(map(str.upper, NAMES)))
        def test_a(x): ...
    """,
    "집합 메서드 union": """
        import pytest
        NAMES = {"a", "b"}
        @pytest.mark.parametrize("x", NAMES.union({"c"}))
        def test_a(x): ...
    """,
    "삼항식의 한쪽 가지": """
        import pytest
        NAMES = {"a", "b"}
        FLAG = True
        @pytest.mark.parametrize("x", NAMES if FLAG else [1])
        def test_a(x): ...
    """,
    "extend 로 이어 붙인 집합": """
        import pytest
        NAMES = {"a", "b"}
        CASES = []
        CASES.extend(NAMES)
        @pytest.mark.parametrize("x", CASES)
        def test_a(x): ...
    """,
    "주석 달린 대입": """
        import pytest
        NAMES = {"a", "b"}
        CASES: list[str] = list(NAMES)
        @pytest.mark.parametrize("x", CASES)
        def test_a(x): ...
    """,
    "ids 목록이 집합에서 나옴": """
        import pytest
        LABELS = {"p", "q"}
        @pytest.mark.parametrize("x", [1, 2], ids=list(LABELS))
        def test_a(x): ...
    """,
    "함수 안에서 문자열화된 uuid": """
        import uuid, pytest
        def _key():
            return str(uuid.uuid4())
        @pytest.mark.parametrize("x", [_key()])
        def test_a(x): ...
    """,
    "% 포맷 속 uuid": """
        import uuid, pytest
        @pytest.mark.parametrize("x", ["case-%s" % uuid.uuid4()])
        def test_a(x): ...
    """,
    "빈 set() 을 add 로 채움": """
        import pytest
        NAMES = set()
        NAMES.add("a")
        @pytest.mark.parametrize("x", NAMES)
        def test_a(x): ...
    """,
    "bare 임포트한 난수 호출": """
        import pytest
        from os import urandom
        @pytest.mark.parametrize("x", [urandom(4)])
        def test_a(x): ...
    """,
    "id() 호출": """
        import pytest
        OBJ = object()
        @pytest.mark.parametrize("x", [id(OBJ)])
        def test_a(x): ...
    """,
    "정수화된 uuid": """
        import uuid, pytest
        @pytest.mark.parametrize("x", [int(uuid.uuid4())])
        def test_a(x): ...
    """,
    "다중 argnames 행의 원소는 각각 id": """
        import uuid, pytest
        @pytest.mark.parametrize(("name", "key"), [("a", str(uuid.uuid4()))])
        def test_a(name, key): ...
    """,
    "fixture params": """
        import pytest
        @pytest.fixture(params=frozenset({"a", "b"}))
        def f(request): ...
    """,
    "metafunc.parametrize": """
        def pytest_generate_tests(metafunc):
            metafunc.parametrize("x", set("abc"))
    """,
}

_NEGATIVE = {
    "sorted 로 감싼 집합": """
        import pytest
        @pytest.mark.parametrize("x", sorted({"a", "b"}))
        def test_a(x): ...
    """,
    "sorted 로 감싼 상수 이름": """
        import pytest
        NAMES = frozenset({"a", "b"})
        @pytest.mark.parametrize("x", sorted(NAMES))
        def test_a(x): ...
    """,
    "모든 return 이 sorted 인 함수": """
        import pytest
        def _cases():
            out = []
            for m in Base.registry.mappers:
                out.append(m.class_.__name__)
            return sorted(out)
        @pytest.mark.parametrize("c", _cases())
        def test_a(c): ...
    """,
    "고정 리터럴 목록": """
        import pytest
        @pytest.mark.parametrize("x", [1, 2, 3], ids=["a", "b", "c"])
        def test_a(x): ...
    """,
    "정수 집합은 결정적": """
        import pytest
        @pytest.mark.parametrize("x", {1, 2, 3, 40})
        def test_a(x): ...
    """,
    "range 로 만든 집합은 결정적": """
        import pytest
        @pytest.mark.parametrize("x", set(range(4)))
        def test_a(x): ...
    """,
    "집합이 원소로 든 경우": """
        import pytest
        @pytest.mark.parametrize("allowed", [{"a", "b"}, {"c"}])
        def test_a(allowed): ...
    """,
    "uuid4 객체 값은 id 가 순번": """
        import uuid, pytest
        @pytest.mark.parametrize("x", [uuid.uuid4(), uuid.uuid4()])
        def test_a(x): ...
    """,
    "bare 임포트한 uuid4 객체 값": """
        import pytest
        from uuid import uuid4
        @pytest.mark.parametrize("x", [uuid4(), uuid4()])
        def test_a(x): ...
    """,
    "uuid4 로 만든 객체를 이름으로 경유": """
        import uuid, pytest
        class User:
            def __init__(self, uid, role): ...
        def _user(role):
            return User(uid=uuid.uuid4(), role=role)
        STUDENT = _user("student")
        @pytest.mark.parametrize("u", [STUDENT], ids=lambda u: "student")
        def test_a(u): ...
    """,
    "dict 값 안의 str(uuid4)는 id 가 아니다": """
        import uuid, pytest
        @pytest.mark.parametrize(
            "extra",
            [{"version_id": str(uuid.uuid4())}, {"status": "PUBLISHED"}],
            ids=lambda e: next(iter(e)),
        )
        def test_a(extra): ...
    """,
    "dict 의 키만 쓰는 sorted": """
        import uuid, pytest
        FORBIDDEN = {"version_id": str(uuid.uuid4()), "status": "PUBLISHED"}
        @pytest.mark.parametrize("key", sorted(FORBIDDEN))
        def test_a(key): ...
    """,
    "함수 인자가 같은 이름의 모듈 변수를 가린다": """
        import pytest
        NAMES = {"a", "b"}
        def _echo(NAMES):
            return NAMES
        @pytest.mark.parametrize("x", _echo([1, 2]))
        def test_a(x): ...
    """,
    "고정 UUID 리터럴": """
        import uuid, pytest
        @pytest.mark.parametrize("x", [uuid.UUID("00000000-0000-0000-0000-000000000001")])
        def test_a(x): ...
    """,
    "시드 고정 Random": """
        import random, pytest
        @pytest.mark.parametrize("x", [random.Random(0).choice([1, 2, 3])])
        def test_a(x): ...
    """,
    "멤버십 검사만 쓰는 ids": """
        import pytest
        SKIP = frozenset({"b"})
        @pytest.mark.parametrize("x", ["a", "b"], ids=lambda v: "skip" if v in SKIP else v)
        def test_a(x): ...
    """,
    "parametrize 와 무관한 집합 사용": """
        import pytest
        SEEN = set()
        def test_a():
            SEEN.add(1)
        @pytest.mark.parametrize("x", [1, 2])
        def test_b(x): ...
    """,
    "argnames 는 순서와 무관": """
        import pytest
        @pytest.mark.parametrize(("a", "b"), [(1, 2)])
        def test_a(a, b): ...
    """,
}


@pytest.mark.parametrize("label", sorted(_POSITIVE))
def test_detector_flags_each_nondeterministic_source(label: str) -> None:
    _, hits = scan_source(textwrap.dedent(_POSITIVE[label]))
    assert hits, f"탐지기가 놓쳤다: {label}"


@pytest.mark.parametrize("label", sorted(_NEGATIVE))
def test_detector_passes_deterministic_forms(label: str) -> None:
    sites, hits = scan_source(textwrap.dedent(_NEGATIVE[label]))
    assert sites >= 1, f"음성 대조가 공허하다 — parametrize 자리를 하나도 못 봤다: {label}"
    assert not hits, f"과잉 탐지: {label} → {[str(h) for h in hits]}"


# ──────────────────────────────────────────────────────────────────────────
# 3) 실파일 뮤테이션 — 결함을 낳은 바로 그 줄에서 정렬을 빼면 red가 나야 한다
# ──────────────────────────────────────────────────────────────────────────
_SEAM_TEST = _SCAN_ROOT / "db" / "test_to_schema_null_seam.py"
_SORT_LINE = (
    "    return sorted(found, key=lambda hit: (hit[0].__module__, hit[0].__qualname__, hit[2]))"
)


def test_removing_the_sort_from_the_real_file_is_caught() -> None:
    """OPS-144 ④ — 수정 전 상태를 *주입*해 탐지기가 red를 내는지 실파일로 확인한다.

    주입이 실제로 적용됐는지(`mutated != original`)와 대상 줄이 정확히 1건인지를 먼저 단언한다.
    주입이 조용히 실패하면 정상 파일에 대해 "통과"가 *검출*처럼 보이기 때문이다.
    """
    before = hashlib.sha256(_SEAM_TEST.read_bytes()).hexdigest()
    original = _SEAM_TEST.read_text(encoding="utf-8")
    assert original.count(_SORT_LINE) == 1, "주입 대상 줄이 없거나 중복이다 — 파일이 바뀌었다"
    mutated = original.replace(_SORT_LINE, "    return found")
    assert mutated != original, "뮤테이션이 적용되지 않았다"

    _, clean_hits = scan_source(original, "original")
    _, mutated_hits = scan_source(mutated, "mutated")

    assert not clean_hits, f"원본에서 위반: {[str(h) for h in clean_hits]}"
    assert any(
        "mappers" in h.kind for h in mutated_hits
    ), f"정렬을 뺀 파일을 탐지기가 놓쳤다: {[str(h) for h in mutated_hits]}"
    # 메모리 안에서만 주입했으므로 디스크 파일은 바이트 동일해야 한다(원복 불요를 단언으로 고정).
    assert hashlib.sha256(_SEAM_TEST.read_bytes()).hexdigest() == before
