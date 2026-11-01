"""Tier 0~3 ↔ LicenseType 대응표와 enum의 어긋남 검사 — EOS-224 (D6 = (b)).

`docs/data/licensing_safety.md`의 「Tier 0~3 ↔ LicenseType 매핑」 절에 있는 두 표(LicenseType 23값 · pool 3값)가
`schema/enums.py`의 `LicenseType`·`ContentPool` 값 집합과 **정확히 같은지** 본다. enum에 값이 추가·삭제됐는데 표를
안 고치면 RED다.

tests/infra 잡은 백엔드를 설치하지 않으므로 enums.py를 import하지 않고 AST로 읽는다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_ENUMS = _REPO / "src" / "backend" / "whymath_backend" / "schema" / "enums.py"
_DOC = _REPO / "docs" / "data" / "licensing_safety.md"

# 표의 Tier 칸에 올 수 있는 값 — 빈칸·임의 표기를 막는다
_ALLOWED_TIER = {"Tier 0", "Tier 1", "Tier 2", "Tier 3", "판정 필요", "대응 없음"}


def enum_values(source: str, class_name: str) -> set[str]:
    """클래스 본문의 `NAME = "값"` 대입에서 문자열 값을 모은다."""
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            values = {
                stmt.value.value
                for stmt in node.body
                if isinstance(stmt, ast.Assign)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            }
            assert values, f"{class_name} 값 0건 — 파싱 실패(공허한 통과 방지)"
            return values
    raise AssertionError(f"{class_name} 클래스를 찾지 못함")


def table_rows(doc: str, block: str) -> dict[str, str]:
    """`<!-- tier-map:<block>:begin/end -->` 사이 표에서 {값: Tier}를 읽는다."""
    m = re.search(rf"<!-- tier-map:{block}:begin -->(.*?)<!-- tier-map:{block}:end -->", doc, re.S)
    assert m, f"tier-map:{block} 표식이 없음"
    rows: dict[str, str] = {}
    for line in m.group(1).splitlines():
        cell = re.match(r"\|\s*`([^`]+)`\s*\|\s*([^|]*?)\s*\|", line)
        if cell:
            key, tier = cell.group(1), cell.group(2)
            assert key not in rows, f"표에 {key} 중복"
            rows[key] = tier
    assert rows, f"tier-map:{block} 표 행 0건 — 파싱 실패"
    return rows


def mismatch(enum_set: set[str], rows: dict[str, str]) -> list[str]:
    """빠진 값·남는 값·허용 밖 Tier 표기를 설명 문자열로 돌려준다(없으면 빈 목록)."""
    problems = [f"표에 없음: {v}" for v in sorted(enum_set - rows.keys())]
    problems += [f"enum에 없음: {v}" for v in sorted(rows.keys() - enum_set)]
    problems += [
        f"Tier 표기 오류: {k}={t!r}" for k, t in sorted(rows.items()) if t not in _ALLOWED_TIER
    ]
    return problems


@pytest.mark.parametrize(("cls", "block"), [("LicenseType", "license"), ("ContentPool", "pool")])
def test_doc_table_matches_enum(cls: str, block: str) -> None:
    values = enum_values(_ENUMS.read_text(encoding="utf-8"), cls)
    rows = table_rows(_DOC.read_text(encoding="utf-8"), block)
    problems = mismatch(values, rows)
    assert not problems, f"licensing_safety.md Tier 표 ↔ {cls} 어긋남:\n  " + "\n  ".join(problems)


def test_license_type_has_23_values() -> None:
    """지시문·문서가 전제한 23값 — 바뀌면 표와 문서 서술을 함께 고친다."""
    assert len(enum_values(_ENUMS.read_text(encoding="utf-8"), "LicenseType")) == 23


def test_d6_decision_header_present() -> None:
    doc = _DOC.read_text(encoding="utf-8")
    assert "D6 = (b) Kiki 결정" in doc and "2026-11-02" in doc


def test_mismatch_detects_each_defect_kind() -> None:
    """판정 함수 변별력 — 값 하나 빠짐 · 값 하나 남음 · Tier 표기 오류를 각각 잡고, 정상은 통과."""
    good = {"A": "Tier 1", "B": "판정 필요"}
    assert mismatch({"A", "B"}, good) == []
    assert mismatch({"A", "B", "C"}, good) == ["표에 없음: C"]
    assert mismatch({"A"}, good) == ["enum에 없음: B"]
    assert mismatch({"A", "B"}, {"A": "Tier 1", "B": ""}) == ["Tier 표기 오류: B=''"]
