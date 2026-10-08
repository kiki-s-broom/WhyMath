"""OPS-82 — 구조화 에러코드 체계 거버넌스.

정본화(레지스트리)와 집행(응답이 실제로 코드를 싣는가)을 별항으로 잰다. 전수 검사는 문자열이
아니라 AST로 한다 — 소스 속 `WM-XXX-NNN` 리터럴과 `CodedHTTPException(...)` 첫 인자를 모두
수집해 레지스트리와 양방향 대조한다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from whymath_backend.api._error_codes import (
    CODE_PATTERN,
    ERROR_CODES,
    FAMILIES,
    UNCLASSIFIED,
    CodedHTTPException,
    error_code_of,
)
from whymath_backend.schema.enums import GenerationFailureCode

_SRC = Path(__file__).resolve().parents[3] / "src" / "backend" / "whymath_backend"
_REGISTRY_FILE = _SRC / "api" / "_error_codes.py"
_LITERAL = re.compile(r"^WM-[A-Z]+-\d{3}$")


def _scan() -> tuple[set[str], set[str], int]:
    """(소스 속 코드 리터럴 전건, CodedHTTPException 첫 인자 리터럴, 스캔한 파일 수)."""
    literals: set[str] = set()
    raised: set[str] = set()
    files = 0
    for path in _SRC.rglob("*.py"):
        files += 1
        if path == _REGISTRY_FILE:
            continue  # 등록부 자신은 정의 쪽이다 — 사용 쪽만 센다
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if _LITERAL.match(node.value):
                    literals.add(node.value)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "CodedHTTPException"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                raised.add(str(node.args[0].value))
    return literals, raised, files


class TestRegistryShape:
    def test_every_code_matches_pattern_and_closed_family(self) -> None:
        assert ERROR_CODES, "레지스트리가 비었다"
        for code, entry in ERROR_CODES.items():
            m = CODE_PATTERN.match(code)
            assert m is not None, code
            assert m.group("family") in FAMILIES, code
            assert entry.code == code

    def test_unclassified_is_not_a_registered_code(self) -> None:
        # '분류 안 됨'은 등록된 의미가 아니라 자리표시다 — 등록되면 미분류가 정상처럼 보인다.
        assert UNCLASSIFIED not in ERROR_CODES

    def test_does_not_collide_with_generation_failure_code(self) -> None:
        # acceptance ②: F1~F8(콘텐츠 실패)과 형식이 겹치지 않는다.
        f_values = {c.value for c in GenerationFailureCode}
        assert f_values.isdisjoint(ERROR_CODES)
        assert not any(re.fullmatch(r"F\d+", c) for c in ERROR_CODES)

    def test_http_status_is_a_real_error_status(self) -> None:
        for entry in ERROR_CODES.values():
            assert 400 <= entry.http_status <= 599, entry.code


class TestGovernanceByAst:
    def test_scan_is_not_vacuous(self) -> None:
        literals, raised, files = _scan()
        assert files > 100, "스캔 대상이 비정상적으로 적다(공허 통과 방지)"
        assert literals, "코드 리터럴을 하나도 못 찾았다 — 배선이 0이다"
        assert raised, "CodedHTTPException 사용이 0건 — 정의만 있고 집행이 없다"

    def test_every_literal_in_source_is_registered(self) -> None:
        literals, raised, _ = _scan()
        assert (literals | raised) <= set(ERROR_CODES), (literals | raised) - set(ERROR_CODES)

    def test_every_registered_code_is_actually_used(self) -> None:
        # 정본화≠집행: 등록만 하고 어떤 응답도 싣지 않는 코드는 허수다.
        literals, raised, _ = _scan()
        unused = {c for c, e in ERROR_CODES.items() if not e.deprecated} - (literals | raised)
        assert not unused, unused


class TestBehavior:
    def test_unregistered_code_cannot_be_raised(self) -> None:
        with pytest.raises(KeyError):
            CodedHTTPException("WM-RATE-999")

    def test_status_comes_from_registry(self) -> None:
        exc = CodedHTTPException("WM-RATE-001", detail="x", headers={"Retry-After": "5"})
        assert exc.status_code == 429
        assert exc.error_code == "WM-RATE-001"
        assert exc.headers == {"Retry-After": "5"}

    def test_error_code_of_distinguishes_unclassified(self) -> None:
        assert error_code_of(CodedHTTPException("WM-RATE-001")) == "WM-RATE-001"
        assert error_code_of(RuntimeError("boom")) == UNCLASSIFIED

        class Stale(Exception):
            error_code = "WM-RATE-777"  # 미등록 — 조용히 통과시키지 않는다

        assert error_code_of(Stale()) == UNCLASSIFIED
