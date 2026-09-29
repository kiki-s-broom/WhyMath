"""CAS 파싱 단일 진입점 거버넌스 — 코딩 헌법 R22-03의 기계 집행(CONST-09).

R22-03: "학생 입력 수식은 허용 문자 검사를 통과한 뒤에만 CAS로 파싱한다."
집행 장치 = `src/backend/whymath_backend/l3/safe_parse.py`(단일 안전 진입점). 이 파일은
**그 진입점 밖에서 CAS 파서를 직접 부르는 자리**를 AST로 전수 조사해 동결한다.

왜 필요한가(재현 실측 2026-09-29): 다섯 글자 `9^9^9`가 학생 답 검증 경로 전부에서 20초
timeout까지 끝나지 않았고, `exec(chr(…)+…)`처럼 영문자·숫자·괄호·`+`만으로 된 입력이 SymPy
파서의 내부 `eval`을 거쳐 **임의 코드로 실행**됐다. 진입점을 하나로 모으지 않으면 새 호출부가
생길 때마다 이 구멍이 다시 열린다.

판정 규칙
---------
- 대상 = `src/backend` 아래 모든 `.py`(`__pycache__` 제외)의 CAS 파서 **사용**:
  ① 호출 — `sympify(…)`·`parse_expr(…)`·`parse_latex(…)`(이름·속성·`import … as` 별칭 모두),
     `S(…)`(sympy에서 온 것 — 숫자 리터럴 하나만 넘기는 `S(2)`는 파싱이 아니라 제외)
  ② 참조 — 호출이 아닌 적재(`f = sympy.sympify`처럼 별칭을 만들어 우회하는 형태)
  ③ 이름 import — `from sympy import sympify` 등(그 모듈이 파서를 직접 쥔다는 뜻)
- 진입점 파일(`safe_parse.py`)은 면제한다 — 단, **실제로 파서 호출을 담고 있어야** 면제가
  유효하다(파일이 비거나 이름이 바뀌면 면제가 공허해진다).
- 그 밖의 ①은 `_ALLOWLIST`에 (파일, 함수, 파서) 키와 **정확한 호출 수·비어 있지 않은 사유**가
  있어야 한다. 사유는 "학생·LLM·API 입력이 닿지 않는 신뢰 입력(코드 상수·저작 코퍼스)"이어야
  한다. ②③은 허용목록 없이 전부 실패다.
- **stale 금지** — 허용목록 항목이 실제 호출과 맞지 않으면(호출이 사라졌거나 수가 다르면) 실패.
  만료 없는 유예 금지(CLAUDE.md): 호출을 지우면 이 테스트가 "허용목록 줄을 지워라"라고 말한다.
- **0건 스캔은 실패** — 대상 파일을 하나도 못 찾으면 공허하게 통과하지 않는다.

이 테스트가 잡지 **않는** 것(있는 척 금지)
------------------------------------------
- `getattr(sympy, "sympify")` 같은 문자열 기반 동적 접근.
- 파서를 *내부적으로* 부르는 다른 SymPy API에 문자열을 넘기는 것(예: `sympy.simplify("…")`,
  `sympy.solve("…")`는 인자를 `sympify`한다) — 이름으로는 구별할 수 없다. 이 저장소의 호출부는
  이미 파싱된 식을 넘기지만, 그 사실은 이 스캔이 아니라 코드 리뷰가 지킨다.

이 모듈은 `infra-contracts` 잡(최소 의존 7종 — sympy·백엔드 미설치)에서 돈다: 표준 라이브러리
`ast`·`pathlib`만 쓴다.
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCAN_ROOT = _REPO_ROOT / "src" / "backend"
_ENTRYPOINT = "src/backend/whymath_backend/l3/safe_parse.py"

# 파싱 진입점 이름 — sympify·parse_expr·parse_latex는 어디서 왔든 이 이름이면 파서로 본다.
_PARSER_NAMES = frozenset({"sympify", "parse_expr", "parse_latex"})
# `S`는 흔한 이름이라 sympy에서 온 것만 본다.
_SYMPY_ONLY_NAMES = frozenset({"S"})
_TARGETS = _PARSER_NAMES | _SYMPY_ONLY_NAMES

# (저장소 기준 경로, 함수 qualname, 파서 이름) → (정확한 호출 수, 사유).
# 사유는 **왜 학생·LLM·API 입력이 닿지 않는가**를 한 줄로 적는다. 비우면 실패한다.
_ALLOWLIST: dict[tuple[str, str, str], tuple[int, str]] = {
    (
        "src/backend/whymath_backend/l4/misconception/wrong_form_match.py",
        "matches_wrong_form",
        "sympify",
    ): (
        2,
        "오개념 카탈로그(CATALOG)의 canonical_wrong_form 템플릿 = 코드 상수 — 학생 식(sl)은 "
        "같은 함수에서 safe_sympify를 거친다",
    ),
    (
        "src/backend/whymath_backend/l3/equivalent/trig_skeleton_generator.py",
        "_TrigSkeleton.value",
        "sympify",
    ): (
        1,
        "문자열이 아니라 코드 상수 특수각으로 만든 SymPy 식(삼각함수 적용 결과)의 재감쌈 — 파싱 없음",
    ),
    (
        "src/backend/whymath_backend/harness/attempt_grading_shadow_report.py",
        "_parse_for_derivation",
        "sympify",
    ): (
        1,
        "오프라인 배치 CLI가 저작 코퍼스 verify 블록의 조건식을 읽는다 — 요청 경로 무변경·학생 "
        "제출값은 grade_attempt에서 verify_answer(안전 진입점 경유)로만 채점",
    ),
    (
        "src/backend/whymath_backend/harness/attempt_grading_shadow_report.py",
        "_derive_from_conditions_parsed",
        "sympify",
    ): (
        1,
        "오프라인 배치 CLI가 적재된 Problem.conditions_parsed(저작·적재 파이프라인 산출)를 "
        "읽는다 — 학생 입력 아님",
    ),
    (
        "src/backend/whymath_backend/harness/selective_grading_demotion_eval.py",
        "_is_numeric_expression",
        "sympify",
    ): (
        1,
        "CI 강등전 하네스가 코퍼스 문항의 저작 정답(trial.correct_answer)이 수치인지 본다 — "
        "학생 입력 아님",
    ),
}


@dataclass(frozen=True, slots=True)
class _Use:
    """파서 사용 1건 — 파일·함수·파서 이름·종류(call/ref/import)·줄."""

    path: str
    qualname: str
    target: str
    kind: str
    line: int


def _root_name(node: ast.expr) -> str | None:
    """속성 사슬의 맨 앞 이름(`sympy.parsing.latex` → `sympy`)."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _is_numeric_literal(node: ast.expr) -> bool:
    """`2`·`-3`·`2.5` 같은 숫자 리터럴인가(S(2)는 파싱이 아니다)."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        node = node.operand
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float))


class _Scanner(ast.NodeVisitor):
    """한 모듈의 파서 사용을 모은다 — import 별칭을 먼저 풀고 호출·참조·import를 센다."""

    def __init__(self, path: str, tree: ast.Module) -> None:
        self.path = path
        self.uses: list[_Use] = []
        self._scope: list[str] = []
        self._module_aliases: set[str] = set()  # sympy 모듈에 묶인 이름(sympy·sp·spp …)
        self._name_aliases: dict[str, str] = {}  # 지역 이름 → 파서 이름(`as` 별칭 포함)
        self._call_funcs: set[int] = set()
        self._chain_bases: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "sympy" or alias.name.startswith("sympy."):
                        self._module_aliases.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "sympy" or module.startswith("sympy."):
                    for alias in node.names:
                        local = alias.asname or alias.name
                        if alias.name in _TARGETS:
                            self._name_aliases[local] = alias.name
                        else:
                            # `from sympy.parsing import sympy_parser` — 모듈일 수 있다
                            self._module_aliases.add(local)
            elif isinstance(node, ast.Call):
                self._call_funcs.add(id(node.func))
            elif isinstance(node, ast.Attribute):
                # `sympy.S.Zero`의 `sympy.S`·`S.true`의 `S`처럼 속성 사슬의 밑 — 값으로 꺼내
                # 쓰는 참조가 아니다(S에만 적용 — 싱글턴 레지스트리 접근은 파싱이 아니다).
                self._chain_bases.add(id(node.value))

    # ── 범위(qualname) 추적 ──
    def _visit_scope(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scope(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scope(node)

    def _qualname(self) -> str:
        return ".".join(self._scope) or "<module>"

    def _record(self, target: str, kind: str, node: ast.AST) -> None:
        self.uses.append(
            _Use(self.path, self._qualname(), target, kind, getattr(node, "lineno", 0))
        )

    def _resolve(self, func: ast.expr) -> str | None:
        """참조식이 파서를 가리키면 파서 이름, 아니면 None."""
        if isinstance(func, ast.Name):
            if func.id in self._name_aliases:
                return self._name_aliases[func.id]
            return func.id if func.id in _PARSER_NAMES else None
        if isinstance(func, ast.Attribute):
            if func.attr in _PARSER_NAMES:
                return func.attr
            if func.attr in _SYMPY_ONLY_NAMES and _root_name(func.value) in self._module_aliases:
                return func.attr
        return None

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if module == "sympy" or module.startswith("sympy."):
            for alias in node.names:
                # `S`는 `S.Zero`·`S(2)`처럼 파싱 없이도 흔히 쓰므로 import 자체는 보지 않는다
                # (문자열 호출·값 참조는 아래 호출/참조 규칙이 본다).
                if alias.name in _PARSER_NAMES:
                    self._record(alias.name, "import", node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        target = self._resolve(node.func)
        if target is not None:
            numeric_only = (
                len(node.args) == 1 and not node.keywords and _is_numeric_literal(node.args[0])
            )
            if not (target in _SYMPY_ONLY_NAMES and numeric_only):
                self._record(target, "call", node)
        self.generic_visit(node)

    def _visit_reference(self, node: ast.Name | ast.Attribute) -> None:
        if id(node) in self._call_funcs or not isinstance(node.ctx, ast.Load):
            return
        target = self._resolve(node)
        if target is None:
            return
        if target in _SYMPY_ONLY_NAMES and id(node) in self._chain_bases:
            return  # `sympy.S.Zero`·`S.true` — 싱글턴 레지스트리 속성 접근(파싱 아님)
        self._record(target, "ref", node)

    def visit_Name(self, node: ast.Name) -> None:
        self._visit_reference(node)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._visit_reference(node)
        self.generic_visit(node)


def _scan_file(path: Path) -> list[_Use]:
    rel = path.relative_to(_REPO_ROOT).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    scanner = _Scanner(rel, tree)
    scanner.visit(tree)
    return scanner.uses


def _source_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _scan(root: Path) -> tuple[int, list[_Use]]:
    files = _source_files(root)
    uses: list[_Use] = []
    for path in files:
        uses.extend(_scan_file(path))
    return len(files), uses


def _violations(
    uses: list[_Use], allowlist: dict[tuple[str, str, str], tuple[int, str]]
) -> list[str]:
    """위반 사유 목록 — 비면 통과. 테스트와 결함 주입 검사가 같은 함수를 쓴다."""
    problems: list[str] = []
    outside = [u for u in uses if u.path != _ENTRYPOINT]
    for use in outside:
        if use.kind != "call":
            problems.append(
                f"{use.path}:{use.line} {use.qualname} — 파서 `{use.target}` {use.kind} "
                "(호출 외 참조·이름 import는 허용목록 대상이 아니다 — safe_parse를 쓰라)"
            )
    calls = Counter((u.path, u.qualname, u.target) for u in outside if u.kind == "call")
    for key, count in sorted(calls.items()):
        entry = allowlist.get(key)
        if entry is None:
            problems.append(
                f"{key[0]} {key[1]} — 파서 `{key[2]}` 직접 호출 {count}건이 안전 진입점 "
                "밖에 있다(safe_parse로 옮기거나, 신뢰 입력이면 사유와 함께 허용목록 등재)"
            )
            continue
        expected, reason = entry
        if not reason.strip():
            problems.append(f"{key} — 허용목록 사유가 비었다")
        if expected != count:
            problems.append(f"{key} — 허용목록 호출 수 {expected} ≠ 실측 {count}")
    for key in sorted(set(allowlist) - set(calls)):
        problems.append(f"{key} — stale 허용목록(대응 호출 0건) — 이 줄을 지워라")
    return problems


def _require_nonempty_scan(n_files: int, uses: list[_Use]) -> None:
    """0건 스캔은 실패 — 대상 파일·파서 사용을 실제로 찾았다는 증거를 요구한다."""
    assert n_files > 500, f"스캔 대상 파일이 너무 적다({n_files}) — 경로가 틀렸다"
    assert uses, "파서 사용을 하나도 못 찾았다 — 스캐너가 고장났다(진입점 자신도 0건)"


# ──────────────────────────────────────────────────────────────────────
# 실저장소 판정
# ──────────────────────────────────────────────────────────────────────


def test_scan_covers_the_backend_tree() -> None:
    """0건 스캔은 실패 — 실저장소 스캔이 대상 파일·파서 사용을 실제로 찾는다."""
    _require_nonempty_scan(*_scan(_SCAN_ROOT))


def test_entrypoint_exists_and_actually_holds_the_parser_calls() -> None:
    """면제의 전제 — 진입점 파일이 실재하고 파서 호출을 실제로 담는다."""
    entry = _REPO_ROOT / _ENTRYPOINT
    assert entry.is_file(), f"안전 진입점 부재: {_ENTRYPOINT}"
    entry_calls = {u.target for u in _scan_file(entry) if u.kind == "call"}
    assert {
        "sympify",
        "parse_expr",
        "parse_latex",
    } <= entry_calls, (
        f"진입점이 세 파서를 모두 감싸지 않는다(실측 {sorted(entry_calls)}) — 면제가 공허하다"
    )


def test_every_cas_parser_use_outside_the_entrypoint_is_allowlisted() -> None:
    """R22-03 집행 — 진입점 밖 직접 파싱 0건(허용목록·사유·정확한 수 예외만)."""
    _n, uses = _scan(_SCAN_ROOT)
    problems = _violations(uses, _ALLOWLIST)
    assert not problems, "CAS 파싱 진입점 위반:\n" + "\n".join(problems)


def test_allowlist_reasons_are_nonempty_and_counts_positive() -> None:
    """허용목록 자체의 형식 — 사유 필수·호출 수 양수."""
    for key, (count, reason) in _ALLOWLIST.items():
        assert reason.strip(), f"{key} — 사유가 비었다"
        assert count > 0, f"{key} — 호출 수가 0 이하다"


# ──────────────────────────────────────────────────────────────────────
# 변별력 — 검사기가 막으려는 상태를 주입하면 실제로 RED가 나는가
# ──────────────────────────────────────────────────────────────────────


def _uses_of(source: str, rel: str = "src/backend/whymath_backend/l3/probe.py") -> list[_Use]:
    tree = ast.parse(source)
    scanner = _Scanner(rel, tree)
    scanner.visit(tree)
    return scanner.uses


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("import sympy\ndef f(t):\n    return sympy.sympify(t)\n", "sympify"),
        ("import sympy as sp\ndef f(t):\n    return sp.sympify(t)\n", "sympify"),
        (
            "from sympy.parsing.sympy_parser import parse_expr as pe\n"
            "def f(t):\n    return pe(t)\n",
            "parse_expr",
        ),
        (
            "from sympy.parsing.latex import parse_latex\ndef f(t):\n    return parse_latex(t)\n",
            "parse_latex",
        ),
        ("import sympy\ndef f(t):\n    return sympy.S(t)\n", "S"),
        ("from sympy import S\ndef f(t):\n    return S(t)\n", "S"),
    ],
)
def test_injected_direct_parse_is_detected(source: str, target: str) -> None:
    """직접 파싱을 주입하면 허용목록 밖 호출로 RED — 이름·별칭·속성 형태 전부."""
    problems = _violations(_uses_of(source), {})
    assert any(f"`{target}`" in p for p in problems), problems


def test_alias_reference_bypass_is_detected() -> None:
    """`f = sympy.sympify; f(t)`처럼 참조로 별칭을 만드는 우회도 RED."""
    source = "import sympy\nparse = sympy.sympify\ndef f(t):\n    return parse(t)\n"
    problems = _violations(_uses_of(source), {})
    assert any("ref" in p for p in problems), problems


def test_numeric_literal_s_is_not_a_parse() -> None:
    """`S(2)`·`S.Zero`는 파싱이 아니다 — 대조군(모든 S를 막으면 가드가 소음이 된다)."""
    source = "import sympy\nfrom sympy import S\nX = sympy.S(2)\nY = sympy.S.Zero\nZ = S.true\n"
    assert _violations(_uses_of(source), {}) == []


def test_allowlisted_call_with_wrong_count_or_empty_reason_is_red() -> None:
    """허용목록 수가 어긋나거나 사유가 비면 RED — 같은 함수에 우회를 추가해도 걸린다."""
    rel = "src/backend/whymath_backend/l3/probe.py"
    source = "import sympy\ndef f(t):\n    return sympy.sympify(t), sympy.sympify(t)\n"
    uses = _uses_of(source, rel)
    assert _violations(uses, {(rel, "f", "sympify"): (2, "코드 상수")}) == []
    assert _violations(uses, {(rel, "f", "sympify"): (1, "코드 상수")})
    assert _violations(uses, {(rel, "f", "sympify"): (2, "   ")})


def test_stale_allowlist_entry_is_red() -> None:
    """대응 호출이 사라진 허용목록 줄은 RED — 유예가 조용히 눌러앉지 않는다."""
    stale = {("src/backend/whymath_backend/l3/gone.py", "f", "sympify"): (1, "코드 상수")}
    problems = _violations([], stale)
    assert any("stale" in p for p in problems), problems


def test_empty_scan_root_is_red(tmp_path: Path) -> None:
    """0건 스캔 가드의 변별력 — 빈 트리·파서 사용 0건 트리 모두 실패로 드러난다."""
    with pytest.raises(AssertionError, match="너무 적다"):
        _require_nonempty_scan(*_scan(tmp_path))
    with pytest.raises(AssertionError, match="하나도 못 찾았다"):
        _require_nonempty_scan(501, [])
