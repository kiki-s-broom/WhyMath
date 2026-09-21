"""Neo4j 런타임 도입 금지 정책 동결 테스트.

AGENTS.md/CLAUDE.md 2026-08-03 결정:
"Neo4j는 런타임 미도입 — 개념 그래프 정본은 PG 단일 평면, Neo4j는 data-pipeline
옵셔널 extra의 적재 실험 경로뿐."

이 테스트는 런타임 핵심 경로(src/backend/whymath_backend)에서 Neo4j 드라이버나
Neo4j 관련 import가 존재하지 않음을 AST 기반으로 검증한다.

data-pipeline의 graph_analytics(extra)는 본 테스트 범위 밖 — 별도 optional extra
설치 환경에서만 import되며, 기본 설치 시에는 collection/mypy 깨짐 없이 동작해야
한다(AGENTS.md "무거운 optional 의존성" 원칙).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _python_sources_under(root: Path) -> list[Path]:
    """주어진 루트 아래 모든 Python 소스를 수집한다."""
    return list(root.rglob("*.py"))


def _has_neo4j_import(path: Path) -> list[str]:
    """파일에서 neo4j 관련 import 문을 찾아 (line, text) 형태로 반환."""
    findings: list[str] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        pytest.fail(f"구문 오류: {path}: {exc}")
        return findings

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("neo4j"):
                    findings.append(f"{path}:{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("neo4j"):
                findings.append(f"{path}:{node.lineno}: from {module} import ...")
    return findings


@pytest.mark.parametrize(
    "runtime_root",
    [
        pytest.param(
            Path(__file__).parents[2] / "src" / "backend" / "whymath_backend",
            id="backend",
        ),
    ],
)
def test_no_neo4j_import_in_runtime(runtime_root: Path) -> None:
    """백엔드 런타임 코드에 Neo4j import가 없어야 한다."""
    assert runtime_root.exists(), f"경로가 없습니다: {runtime_root}"

    findings: list[str] = []
    for src in _python_sources_under(runtime_root):
        findings.extend(_has_neo4j_import(src))

    assert not findings, (
        "백엔드 런타임에서 Neo4j import가 발견됨:\n"
        + "\n".join(findings)
        + "\n\nAGENTS.md: Neo4j는 런타임 미도입. "
        "개념 그래프 정본은 PostgreSQL 단일 평면."
    )


def test_agents_md_neo4j_runtime_ban_mentioned() -> None:
    """AGENTS.md에 Neo4j 런타임 미도입 문구가 남아 있어야 한다."""
    agents_md = Path(__file__).parents[2] / "AGENTS.md"
    text = agents_md.read_text(encoding="utf-8")
    assert "Neo4j는 런타임 미도입" in text, "AGENTS.md의 Neo4j 정책 문구가 누락됨"
