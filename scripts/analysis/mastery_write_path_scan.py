#!/usr/bin/env python3
"""숙달(mastery) **단일 쓰기 경로** 전수 가드 — AST 스캔 (EOS-108 acceptance ⑥).

무엇을 지키는가
---------------
계획서 300 §6은 "Mastery Engine이 LearnerState를 바꾸는 **유일한 경로**"를 요구한다. 그 요구는
설계 문장으로는 지켜지지 않는다 — 어느 모듈이든 `ConceptMasteryHistory(...)`를 만들어 세션에
add하거나, 읽어 온 행의 `.mastery`를 대입하거나, `update(SkillMasteryHistory)`를 실행하면 계약을
우회해 학생 상태를 바꿀 수 있고, 그 우회는 **테스트가 아니라 새 코드가 생길 때** 일어난다.

이 스캐너는 백엔드 소스 전체를 AST로 읽어 숙달 좌석에 쓰는 지점을 열거하고, **허용 목록 밖의
지점이 하나라도 있으면 exit 1**을 낸다.

왜 문자열 금지 목록이 아니라 AST인가
-------------------------------------
CLAUDE.md 2026-09-01: "금지 패턴 열거 대신 산출물 검사 — 문자열이 아니라 **구성된 결과**를
보라." `grep 'ConceptMasteryHistory('`는 공백(`ConceptMasteryHistory (`)·줄바꿈·별칭 import
(`as CMH`)에서 뚫린다. AST는 그 표기 변형을 전부 같은 노드로 본다. 별칭은 import 해석으로
따라간다.

세 가지 쓰기 축 (전부 검사한다 — 하나라도 빠지면 그 축이 우회로가 된다)
-----------------------------------------------------------------------
  ① **생성**  — 숙달 좌석 ORM 클래스의 인스턴스화 `ConceptMasteryHistory(...)`.
  ② **변조**  — `.mastery` / `.confidence` / `.sample_size` 속성 대입. 이 축은 숙달 좌석 ORM을
     import한 모듈에만 적용한다(이유와 한계는 `_check_attribute_target` 주석).
  ③ **일괄**  — `update(Model)` / `delete(Model)` (SQLAlchemy Core 벌크 문장).

허용 목록의 규율
----------------
허용은 **(파일, 함수/클래스, 축)** 삼중항으로만 준다. 파일 단위 면제는 주지 않는다 — 파일이
커지면 면제 범위가 조용히 넓어지기 때문이다. 그리고 **허용 목록의 항목이 실제로 발견되지
않으면 그것도 실패**다(스캔 0건은 통과가 아니라 실패 — CLAUDE.md 2026-09-01 ④). 면제가 가리키는
코드가 사라졌는데 면제만 남으면, 그 자리는 다음 사람에게 열린 문이 된다.

사용
----
    python3 scripts/analysis/mastery_write_path_scan.py            # 사람용 출력
    python3 scripts/analysis/mastery_write_path_scan.py --json     # 기계 판정용

exit 0 = 위반 0건, exit 1 = 위반 있음(또는 면제가 공허함), exit 2 = 스캔 자체가 실패.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_SRC = _REPO_ROOT / "src" / "backend" / "whymath_backend"

#: 숙달 좌석 ORM 클래스 — 이 둘의 행이 곧 학습자의 숙달 상태다(ARCH-37 `MasteryState`).
MASTERY_MODELS: frozenset[str] = frozenset({"ConceptMasteryHistory", "SkillMasteryHistory"})

#: 숙달 값을 담는 속성 — 대입되면 학생 상태가 바뀐다.
MASTERY_FIELDS: frozenset[str] = frozenset({"mastery", "confidence", "sample_size"})

#: 일괄 쓰기 문장 생성자(SQLAlchemy Core).
BULK_WRITE_CALLS: frozenset[str] = frozenset({"update", "delete"})


@dataclass(frozen=True)
class Allowance:
    """면제 1건 — (파일, 스코프, 축) 삼중항 + **왜 면제인가**.

    `scope`는 그 파일 안의 함수 또는 클래스 이름이다(중첩이면 가장 가까운 것). 파일 전체 면제를
    표현할 방법을 **일부러 두지 않았다**.
    """

    path: str
    scope: str
    axis: str  # "construct" | "assign" | "bulk"
    reason: str


#: 숙달 좌석에 쓰는 것이 **정당한** 유일한 지점들. 늘리려면 이유를 적어야 하고, 이유를 적는
#: 순간 리뷰어가 그것을 읽는다 — 그것이 이 목록의 요점이다.
ALLOWANCES: tuple[Allowance, ...] = (
    Allowance(
        path="l2/mastery_tracking.py",
        scope="_stage_attempt_mastery",
        axis="construct",
        reason=(
            "개념 축 숙달 적재의 유일한 지점. `update_mastery` 호출 계약의 산출만 행으로 만든다."
        ),
    ),
    Allowance(
        path="l2/skill_mastery_tracking.py",
        scope="_stage_skill_attempt_mastery",
        axis="construct",
        reason="스킬 축 숙달 적재의 유일한 지점(개념 축 동형).",
    ),
    Allowance(
        path="l2/learning_event_trace.py",
        scope="_MasteryRowView.__init__",
        axis="assign",
        reason=(
            "쓰기가 아니라 **읽기**다 — 질의 결과 행을 얇은 뷰 객체(`__slots__`)로 옮겨 담는 "
            "투영이며, 그 모듈은 session.add·commit을 한 건도 하지 않는다(모듈 docstring이 그 "
            "사실을 계약으로 선언한다). 같은 이름의 속성이라는 이유로 여기까지 막으면 읽기 축이 "
            "숙달 값을 볼 수 없게 된다."
        ),
    ),
)


@dataclass
class Violation:
    """허용 목록 밖의 숙달 쓰기 1건."""

    path: str
    line: int
    scope: str
    axis: str
    detail: str

    def as_dict(self) -> dict[str, object]:
        """JSON 직렬화용."""
        return {
            "path": self.path,
            "line": self.line,
            "scope": self.scope,
            "axis": self.axis,
            "detail": self.detail,
        }


@dataclass
class ScanResult:
    """스캔 산출 — 위반 목록 + 면제 적중 대장 + 스캔 규모."""

    violations: list[Violation] = field(default_factory=list)
    hits: dict[tuple[str, str, str], int] = field(default_factory=dict)
    files_scanned: int = 0

    @property
    def unused_allowances(self) -> list[Allowance]:
        """한 번도 적중하지 않은 면제 — **공허한 면제**(그 자리는 열린 문이다)."""
        return [a for a in ALLOWANCES if self.hits.get((a.path, a.scope, a.axis), 0) == 0]


class _MasteryWriteVisitor(ast.NodeVisitor):
    """한 모듈의 숙달 쓰기 지점을 모은다 — import 별칭까지 따라간다."""

    def __init__(self, rel_path: str) -> None:
        self._rel_path = rel_path
        #: 이 모듈에서 숙달 좌석 클래스를 가리키는 **로컬 이름**(별칭 포함).
        self._local_model_names: set[str] = set()
        #: 이 모듈에서 SQLAlchemy 일괄 문장 생성자를 가리키는 로컬 이름.
        self._local_bulk_names: set[str] = set()
        self._scope: list[str] = []
        self.found: list[tuple[int, str, str, str]] = []  # (line, scope, axis, detail)

    # ── import 해석 ────────────────────────────────────────────────────────
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """`from ... import X as Y` — 별칭으로 숨는 우회를 막는다."""
        for alias in node.names:
            local = alias.asname or alias.name
            if alias.name in MASTERY_MODELS:
                self._local_model_names.add(local)
            if alias.name in BULK_WRITE_CALLS and (node.module or "").startswith("sqlalchemy"):
                self._local_bulk_names.add(local)
        self.generic_visit(node)

    # ── 스코프 추적 ────────────────────────────────────────────────────────
    def _enter(self, name: str, node: ast.AST) -> None:
        self._scope.append(name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """함수 스코프."""
        self._enter(node.name, node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """async 함수 스코프."""
        self._enter(node.name, node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """클래스 스코프 — 숙달 좌석 클래스 *정의* 자체는 쓰기가 아니다."""
        self._enter(node.name, node)

    @property
    def _current_scope(self) -> str:
        """중첩 스코프를 점 표기로 — `_MasteryRowView.__init__`처럼 클래스까지 구분한다.

        가장 안쪽 이름만 쓰면 `__init__`·`run` 같은 흔한 이름이 서로 다른 클래스에서 같은 면제를
        공유하게 되어, 면제 하나가 의도치 않은 자리까지 열어 준다.
        """
        return ".".join(self._scope) if self._scope else "<module>"

    # ── ① 생성 · ③ 일괄 ────────────────────────────────────────────────────
    def visit_Call(self, node: ast.Call) -> None:
        """`Model(...)`(생성)과 `update(Model)`/`delete(Model)`(일괄)."""
        func = node.func
        name = func.id if isinstance(func, ast.Name) else None
        if name is not None and name in self._local_model_names:
            self.found.append((node.lineno, self._current_scope, "construct", f"{name}(...)"))
        elif name is not None and name in self._local_bulk_names:
            for arg in node.args:
                if isinstance(arg, ast.Name) and arg.id in self._local_model_names:
                    self.found.append(
                        (node.lineno, self._current_scope, "bulk", f"{name}({arg.id})")
                    )
        elif isinstance(func, ast.Attribute) and func.attr in BULK_WRITE_CALLS:
            # `sa.update(Model)` 형태 — 모듈 별칭을 통한 접근.
            for arg in node.args:
                if isinstance(arg, ast.Name) and arg.id in self._local_model_names:
                    self.found.append(
                        (node.lineno, self._current_scope, "bulk", f"{func.attr}({arg.id})")
                    )
        self.generic_visit(node)

    # ── ② 변조 ─────────────────────────────────────────────────────────────
    def visit_Assign(self, node: ast.Assign) -> None:
        """`<무엇이든>.mastery = ...` 속성 대입."""
        for target in node.targets:
            self._check_attribute_target(target, node.lineno)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        """`<무엇이든>.mastery += ...` — 증분 대입도 변조다(`Assign`과 다른 노드라 별도 처리)."""
        self._check_attribute_target(node.target, node.lineno)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """`<무엇이든>.mastery: T = ...` — 주석 붙은 대입.

        클래스 본문의 `mastery: Mapped[...] = mapped_column(...)`은 대상이 `Name`이라 잡히지
        않는다(그것은 컬럼 *선언*이지 값 변조가 아니다).
        """
        if node.value is not None:
            self._check_attribute_target(node.target, node.lineno)
        self.generic_visit(node)

    def _check_attribute_target(self, target: ast.expr, lineno: int) -> None:
        # 축 ②는 **숙달 좌석 ORM을 import한 모듈에만** 적용한다. `confidence`·`sample_size`는
        # 저장소 전역에서 흔한 이름이라(오개념 가설의 신뢰도 등) 이름만으로 판정하면 무관한
        # 모듈이 줄줄이 걸리고, 그러면 사람이 면제를 남발해 가드가 무력해진다.
        # **한계(명시)**: 숙달 행을 *인자로 받아* 변조하는 모듈은 이 축이 보지 못한다. 그런
        # 모듈도 행을 만들거나(①) 일괄 문장을 쓰려면(③) 여전히 걸리며, 두 축은 import 여부와
        # 무관하게 전수 적용된다.
        if not self._local_model_names:
            return
        if isinstance(target, ast.Attribute) and target.attr in MASTERY_FIELDS:
            self.found.append((lineno, self._current_scope, "assign", f".{target.attr} = ..."))
        elif isinstance(target, ast.Tuple):
            for element in target.elts:
                self._check_attribute_target(element, lineno)


def scan(backend_src: Path = _BACKEND_SRC) -> ScanResult:
    """백엔드 소스 전체를 훑어 숙달 쓰기 지점을 판정한다.

    구문 오류가 있는 파일은 **건너뛰지 않고** 예외로 올린다 — 파싱 못 한 파일을 조용히 넘기면
    전수 스캔이 전수가 아니게 된다(위장 가드).
    """
    allowed = {(a.path, a.scope, a.axis) for a in ALLOWANCES}
    result = ScanResult()
    for py_file in sorted(backend_src.rglob("*.py")):
        rel = py_file.relative_to(backend_src).as_posix()
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        result.files_scanned += 1
        visitor = _MasteryWriteVisitor(rel)
        visitor.visit(tree)
        for line, scope, axis, detail in visitor.found:
            key = (rel, scope, axis)
            if key in allowed:
                result.hits[key] = result.hits.get(key, 0) + 1
                continue
            result.violations.append(Violation(rel, line, scope, axis, detail))
    return result


def _render(result: ScanResult) -> list[str]:
    """사람이 읽는 판정문 — 무엇이 왜 걸렸는지와 다음 행동까지."""
    lines = [
        "숙달 단일 쓰기 경로 스캔 (EOS-108)",
        f"  스캔 파일: {result.files_scanned}",
        f"  면제 적중: {sum(result.hits.values())}건 / 면제 선언 {len(ALLOWANCES)}건",
        f"  위반: {len(result.violations)}건",
    ]
    for violation in result.violations:
        lines.append(
            f"  ✗ {violation.path}:{violation.line} [{violation.axis}] "
            f"{violation.scope} — {violation.detail}"
        )
    for allowance in result.unused_allowances:
        lines.append(
            f"  ✗ 공허한 면제: {allowance.path}::{allowance.scope} [{allowance.axis}] — "
            "면제가 가리키는 코드가 없습니다(면제를 지우거나 스코프를 고치십시오)."
        )
    if not result.violations and not result.unused_allowances:
        lines.append("  ✓ 숙달 좌석에 쓰는 지점이 Mastery Engine 계약 경로뿐입니다.")
    else:
        lines.append(
            "  → 숙달 변경은 `l2/mastery_contract.update_mastery` 계약을 경유해야 합니다. "
            "새 쓰기 지점이 정당하다면 ALLOWANCES에 이유와 함께 등재하십시오."
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점 — 판정은 exit code로 낸다."""
    parser = argparse.ArgumentParser(description="숙달 단일 쓰기 경로 AST 전수 스캔 (EOS-108)")
    parser.add_argument("--json", action="store_true", help="기계 판정용 JSON 출력")
    args = parser.parse_args(argv)
    try:
        result = scan()
    except (OSError, SyntaxError) as exc:
        print(f"스캔 실패({type(exc).__name__}): {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(
            json.dumps(
                {
                    "files_scanned": result.files_scanned,
                    "violations": [v.as_dict() for v in result.violations],
                    "unused_allowances": [
                        {"path": a.path, "scope": a.scope, "axis": a.axis}
                        for a in result.unused_allowances
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print("\n".join(_render(result)))
    return 1 if (result.violations or result.unused_allowances) else 0


if __name__ == "__main__":
    raise SystemExit(main())
