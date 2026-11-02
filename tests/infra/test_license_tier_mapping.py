"""Tier 0~3 ↔ LicenseType 대응표와 enum의 어긋남 검사 — EOS-224 (D6 = (b)).

`docs/data/licensing_safety.md`의 「Tier 0~3 ↔ LicenseType 매핑」 절에 있는 두 표(LicenseType · pool)가
`schema/enums.py`의 `LicenseType`·`ContentPool` 값 집합과 **정확히 같은지**, 근거 칸이 채워졌는지, 산문의
'판정 필요 목록'이 표와 같은지를 본다.

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
_PENDING = "판정 필요"


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


def _block(doc: str, block: str) -> str:
    """`<!-- tier-map:<block>:begin/end -->` 사이 본문. 표식은 정확히 1쌍이어야 한다."""
    begin, end = f"<!-- tier-map:{block}:begin -->", f"<!-- tier-map:{block}:end -->"
    assert doc.count(begin) == 1 and doc.count(end) == 1, f"tier-map:{block} 표식이 1쌍이 아님"
    i, j = doc.index(begin), doc.index(end)
    assert i < j, f"tier-map:{block} 표식 순서 뒤바뀜"
    return doc[i + len(begin) : j]


def table_rows(doc: str, block: str) -> dict[str, tuple[str, str]]:
    """표에서 {값: (Tier, 근거)}를 읽는다."""
    rows: dict[str, tuple[str, str]] = {}
    for line in _block(doc, block).splitlines():
        cell = re.match(r"\|\s*`([^`]+)`\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*$", line)
        if cell:
            key = cell.group(1)
            assert key not in rows, f"표에 {key} 중복"
            rows[key] = (cell.group(2), cell.group(3))
    assert rows, f"tier-map:{block} 표 행 0건 — 파싱 실패"
    return rows


def mismatch(enum_set: set[str], rows: dict[str, tuple[str, str]]) -> list[str]:
    """빠진 값·남는 값·허용 밖 Tier·빈 근거를 설명 문자열로 돌려준다(없으면 빈 목록)."""
    problems = [f"표에 없음: {v}" for v in sorted(enum_set - rows.keys())]
    problems += [f"enum에 없음: {v}" for v in sorted(rows.keys() - enum_set)]
    for key, (tier, reason) in sorted(rows.items()):
        if tier not in _ALLOWED_TIER:
            problems.append(f"Tier 표기 오류: {key}={tier!r}")
        if not reason:
            problems.append(f"근거 없음: {key}")
    return problems


def pending_listed(doc: str) -> set[str]:
    """산문 '판정 필요 목록'에 백틱으로 적힌 값들."""
    return set(re.findall(r"`([^`]+)`", _block(doc, "pending")))


def check(doc: str, enums_source: str) -> list[str]:
    """문서·enum 원문 전체에 대한 판정 — 테스트와 결함 주입이 같은 경로를 쓴다."""
    lic = table_rows(doc, "license")
    pool = table_rows(doc, "pool")
    problems = mismatch(enum_values(enums_source, "LicenseType"), lic)
    problems += mismatch(enum_values(enums_source, "ContentPool"), pool)
    pending_in_tables = {k for k, (t, _) in {**lic, **pool}.items() if t == _PENDING}
    listed = pending_listed(doc)
    problems += [f"판정 필요 목록에 빠짐: {v}" for v in sorted(pending_in_tables - listed)]
    problems += [f"판정 필요 목록에만 있음: {v}" for v in sorted(listed - pending_in_tables)]
    return problems


def _doc() -> str:
    return _DOC.read_text(encoding="utf-8")


def _enums() -> str:
    return _ENUMS.read_text(encoding="utf-8")


def test_doc_matches_enums() -> None:
    problems = check(_doc(), _enums())
    assert not problems, "licensing_safety.md Tier 표 ↔ enum 어긋남:\n  " + "\n  ".join(problems)


def test_d6_decision_header_present() -> None:
    doc = _doc()
    assert "D6 = (b) Kiki 결정" in doc and "2026-11-02" in doc


_ROW = "| `CC_BY_ND` | 판정 필요 | ND — 가이드가 ND를 다루지 않음 |\n"


@pytest.mark.parametrize(
    ("label", "target", "old", "new"),
    [
        ("행 하나 삭제", "doc", _ROW, ""),
        ("가짜 값 추가", "doc", _ROW, _ROW + "| `FAKE_LICENSE` | 판정 필요 | x |\n"),
        ("Tier 칸 비움", "doc", _ROW, "| `CC_BY_ND` |  | ND |\n"),
        ("근거 칸 비움", "doc", _ROW, "| `CC_BY_ND` | 판정 필요 |  |\n"),
        ("판정 필요 목록에서 값 삭제", "doc", "`CC_BY_ND`·`CC_BY_NC_SA`", "`CC_BY_NC_SA`"),
        (
            "표식 중복",
            "doc",
            "<!-- tier-map:pool:end -->",
            "<!-- tier-map:pool:end -->\n<!-- tier-map:pool:end -->",
        ),
        (
            "enum 값 추가",
            "enum",
            '    EBS_LICENSED = "EBS_LICENSED"\n',
            '    EBS_LICENSED = "EBS_LICENSED"\n    NEW_ONE = "NEW_ONE"\n',
        ),
    ],
)
def test_injected_defect_is_caught(label: str, target: str, old: str, new: str) -> None:
    """실제 문서·enum 원문에 결함을 넣으면 같은 판정 경로가 RED를 낸다."""
    doc, enums = _doc(), _enums()
    original = doc if target == "doc" else enums
    assert original.count(old) >= 1, f"{label}: 주입 대상 문자열이 원문에 없음(주입 미적용)"
    mutated = original.replace(old, new, 1)
    assert mutated != original
    if target == "doc":
        doc = mutated
    else:
        enums = mutated
    try:
        problems = check(doc, enums)
    except AssertionError:
        return  # 파싱 단계에서 거부(표식 중복 등)도 RED다
    assert problems, f"{label}: 결함을 못 잡음"
