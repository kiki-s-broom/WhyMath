"""개념 생애 상태 쓰기 거버넌스 — 상태를 바꾸는 코드는 전환 함수 한 곳뿐이다 (PED-17 A1, AST 동결).

공통 규칙 3(2026-11-06 확정): "개념의 공개 상태는 B6, D4, D5가 정한 경로로만 바꾼다."
전환 함수(`l1/concept_content/lifecycle.py::transition_concept_state`)가 그 경로이고, 다른 코드가
`concept_content.lifecycle_status`를 직접 쓰거나 기록 원장(`ConceptStateTransition`)을 직접 만들면
전환표·권한 검사·기록 1건 보증을 우회한다. 이 테스트가 그런 코드를 CI에서 막는다.

가드 자신의 변별력(CLAUDE.md "보호 장치를 실패 주입 없이 보호 있음으로 선언 금지"):
  - 위반 조각을 주입해 **탐지되는지**(RED) 본다 — 5가지 쓰기 형태 각각.
  - 읽기·술어 호출 조각이 **오탐되지 않는지**(GREEN 대조) 본다.
  - 합법 쓰기 지점(전환 함수 파일)이 **탐지되는지** 본다 — 스캐너가 눈이 먼 상태가 아님의 증거.
  - 스캔 대상이 0건이면 실패한다(공허한 통과 금지).

한계(명시): 문자열을 조립해 SQL을 만드는 동적 우회(`"SET " + col`)는 잡지 못한다. DB 트리거가
허용 전환 5쌍 밖의 UPDATE를 막고(통합 테스트), 이 테스트는 *정직한 실수*를 막는 데 목적이 있다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_PKG = Path(__file__).resolve().parents[3] / "src" / "backend" / "whymath_backend"
_WRITER = _PKG / "l1" / "concept_content" / "lifecycle.py"

# SQL 문자열 속의 쓰기: "... SET lifecycle_status ..." / "lifecycle_status = " (UPDATE 문맥).
_SQL_WRITE = re.compile(r"\bSET\b[^;]*\blifecycle_status\b", re.IGNORECASE | re.DOTALL)


def find_writes(source: str) -> list[str]:
    """소스에서 `lifecycle_status`·`ConceptStateTransition`을 **쓰는** 지점의 설명 목록."""
    tree = ast.parse(source)
    hits: list[str] = []
    for node in ast.walk(tree):
        # (a)(b) 호출의 키워드 인자: .values(lifecycle_status=...) · ConceptContent(lifecycle_status=...)
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if any(kw.arg == "lifecycle_status" for kw in node.keywords) and name in {
                "values",
                "ConceptContent",
                "update",
                "insert",
            }:
                hits.append(f"line {node.lineno}: {name}(lifecycle_status=...)")
            # (c') 딕셔너리 인자: .values({"lifecycle_status": ...})
            if name == "values":
                for arg in node.args:
                    if isinstance(arg, ast.Dict) and any(
                        isinstance(k, ast.Constant) and k.value == "lifecycle_status"
                        for k in arg.keys
                    ):
                        hits.append(f"line {node.lineno}: values({{'lifecycle_status': ...}})")
            # (d) setattr(x, "lifecycle_status", v)
            if name == "setattr" and len(node.args) >= 2:
                attr = node.args[1]
                if isinstance(attr, ast.Constant) and attr.value == "lifecycle_status":
                    hits.append(f"line {node.lineno}: setattr(..., 'lifecycle_status', ...)")
            # 기록 원장을 직접 만드는 코드: ConceptStateTransition(...)
            if name == "ConceptStateTransition":
                hits.append(f"line {node.lineno}: ConceptStateTransition(...) 직접 생성")
        # (c) 속성 대입: row.lifecycle_status = ...
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for t in targets:
            if isinstance(t, ast.Attribute) and t.attr == "lifecycle_status":
                hits.append(f"line {node.lineno}: .lifecycle_status 대입")
        # (e) SQL 문자열
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _SQL_WRITE.search(node.value)
        ):
            hits.append(f"line {node.lineno}: SQL 문자열이 lifecycle_status를 SET")
    return hits


def _scan_package() -> tuple[int, dict[Path, list[str]]]:
    scanned = 0
    found: dict[Path, list[str]] = {}
    for path in sorted(_PKG.rglob("*.py")):
        scanned += 1
        hits = find_writes(path.read_text(encoding="utf-8"))
        if hits:
            found[path] = hits
    return scanned, found


class TestGovernanceOverTheRealPackage:
    def test_only_the_transition_function_file_writes_lifecycle_state(self) -> None:
        scanned, found = _scan_package()
        assert (
            scanned > 200
        ), f"스캔 대상이 너무 적다({scanned}) — 경로가 틀렸거나 스캐너가 눈이 멀었다"
        offenders = {p.relative_to(_PKG).as_posix(): h for p, h in found.items() if p != _WRITER}
        assert offenders == {}, (
            "전환 함수 밖에서 생애 상태를 쓰는 코드가 있다 — 전환표·권한 검사·기록 보증을 우회한다: "
            f"{offenders}"
        )

    def test_scanner_sees_the_legitimate_writer(self) -> None:
        # 양성 대조 — 합법 쓰기 지점이 탐지되지 않으면 위 '위반 0건'은 아무 의미가 없다.
        _scanned, found = _scan_package()
        assert _WRITER in found
        kinds = " | ".join(found[_WRITER])
        assert "update(lifecycle_status" in kinds or "values(lifecycle_status" in kinds
        assert "ConceptStateTransition(...) 직접 생성" in kinds


class TestScannerDiscriminativePower:
    """위반 조각을 주입하면 잡히고, 읽기는 안 잡힌다."""

    @pytest.mark.parametrize(
        "snippet",
        [
            "session.execute(sa.update(ConceptContent).values(lifecycle_status='공개됨'))",
            "session.execute(sa.update(ConceptContent).values({'lifecycle_status': '공개됨'}))",
            "row.lifecycle_status = '공개됨'",
            "row.lifecycle_status += 'x'",
            "setattr(row, 'lifecycle_status', '공개됨')",
            "ConceptContent(code='X', lifecycle_status='공개됨')",
            "session.execute(text(\"UPDATE concept_content SET lifecycle_status = '공개됨' WHERE code = 'X'\"))",
            "session.add(ConceptStateTransition(concept_code='X'))",
        ],
    )
    def test_injected_writes_are_detected(self, snippet: str) -> None:
        assert find_writes(snippet), f"탐지 실패: {snippet}"

    @pytest.mark.parametrize(
        "snippet",
        [
            "x = row.lifecycle_status",
            "is_student_visible(lifecycle_status=row.lifecycle_status, content_origin=o, review_status=r)",
            "select(ConceptContent.lifecycle_status).where(ConceptContent.code == c)",
            "logger.info('lifecycle_status=%s', row.lifecycle_status)",
            'text("SELECT lifecycle_status FROM concept_content")',
            "lifecycle_status: Mapped[str] = mapped_column(sa.Text)",  # 모델 컬럼 정의(Name 대상)
        ],
    )
    def test_reads_and_predicate_calls_are_not_flagged(self, snippet: str) -> None:
        assert find_writes(snippet) == [], f"오탐: {snippet}"
