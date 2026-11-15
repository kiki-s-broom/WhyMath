"""논리 격리 검사 — golden은 LEGACY_MANIFEST의 옛 코드를 새로 import하지 않는다(GOLD-17 · S15 결정).

Kiki 결정(2026-11-15): /legacy로 옮기지 않고 논리적으로 격리한다. 옛 코드는 한 줄도 고치지 않는다.
- `golden/LEGACY_MANIFEST.txt` = S15 측정(커밋 a9cff6ec)에서 golden이 한 번도 쓰지 않은 백엔드 722모듈 ·
  Flutter 74파일. 삭제는 3단계 S74에서 패키지 단위로 한다.
- 파이썬 쪽 1차 방어는 import-linter 계약 `golden-no-legacy`(src/backend/pyproject.toml)다.
  이 파일은 그 계약이 매니페스트와 어긋나지 않는지, 그리고 계약이 못 보는 곳을 직접 검사한다.
  - import-linter는 그래프에 없는 모듈 이름을 오류 없이 통과시킨다(실측). __init__.py 없는
    whymath_backend/l1/rights/ 모듈이 그렇다 → golden 소스를 AST로 직접 검사해 보완한다.
  - import-linter는 Dart를 모른다 → golden Flutter 파일의 import를 직접 따라가 검사한다.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_MANIFEST = _REPO / "golden" / "LEGACY_MANIFEST.txt"
_PYPROJECT = _REPO / "src" / "backend" / "pyproject.toml"
_GOLDEN_PY = _REPO / "src" / "backend" / "golden"
_MOBILE = _REPO / "src" / "mobile"
_CONTRACT_KEY = "golden-no-legacy"

# Dart import/export/part 지시문의 URI
_DART_DIRECTIVE = re.compile(r"""^\s*(?:import|export|part)\s+['"]([^'"]+)['"]""", re.MULTILINE)


def _manifest_lines() -> list[str]:
    return _MANIFEST.read_text(encoding="utf-8").splitlines()


def _manifest_backend_paths() -> list[str]:
    return [ln for ln in _manifest_lines() if ln.startswith("src/backend/")]


def _manifest_flutter_paths() -> list[str]:
    return [ln for ln in _manifest_lines() if ln.startswith("src/mobile/")]


def path_to_module(path: str) -> str:
    """src/backend/whymath_backend/a/b.py → whymath_backend.a.b (패키지면 __init__ 생략)."""
    parts = path.removeprefix("src/backend/").removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def imported_modules(source: str) -> set[str]:
    """파이썬 소스가 import하는 모듈 이름 후보 전부.

    `from a.b import c`는 `a.b`와 `a.b.c`(c가 하위 모듈일 수 있음) 둘 다 후보로 낸다.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _legacy_contract() -> dict[str, object]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    contracts = data["tool"]["importlinter"]["contracts"]
    matches = [c for c in contracts if _CONTRACT_KEY in c["name"]]
    assert len(matches) == 1, f"계약 '{_CONTRACT_KEY}'가 정확히 1개여야 한다: {len(matches)}개"
    return matches[0]


def test_manifest_header_and_counts() -> None:
    lines = _manifest_lines()
    # 첫 줄에 측정 커밋과 날짜 — 어느 시점의 측정인지 모르면 목록을 믿을 수 없다
    assert "a9cff6ec" in lines[0] and "2026-11-15" in lines[0]
    backend, flutter = _manifest_backend_paths(), _manifest_flutter_paths()
    assert len(backend) == 722 and len(set(backend)) == 722
    assert len(flutter) == 74 and len(set(flutter)) == 74
    # 주석·경로 말고는 아무것도 없다(오타 줄이 조용히 빠지는 것 방지)
    assert all(ln.startswith(("#", "src/backend/", "src/mobile/")) for ln in lines)


def test_contract_matches_manifest_exactly() -> None:
    contract = _legacy_contract()
    assert contract["type"] == "forbidden"
    assert contract["source_modules"] == ["golden"]
    expected = {path_to_module(p) for p in _manifest_backend_paths()}
    actual = set(contract["forbidden_modules"])  # type: ignore[arg-type]
    assert (
        actual - expected == set()
    ), f"매니페스트에 없는데 계약에 있다: {sorted(actual - expected)}"
    assert (
        expected - actual == set()
    ), f"매니페스트에 있는데 계약에 없다: {sorted(expected - actual)}"


def test_golden_python_does_not_import_legacy_directly() -> None:
    legacy = {path_to_module(p) for p in _manifest_backend_paths()}
    files = sorted(_GOLDEN_PY.glob("*.py"))
    assert (
        len(files) >= 5
    ), f"검사할 golden 파이썬 파일이 너무 적다: {len(files)}개"  # 공허 통과 금지
    violations = [
        f"{f.relative_to(_REPO)}: {m}"
        for f in files
        for m in sorted(imported_modules(f.read_text(encoding="utf-8")))
        if m in legacy or any(m.startswith(x + ".") for x in legacy)
    ]
    assert violations == [], "golden이 LEGACY_MANIFEST 모듈을 import한다:\n" + "\n".join(violations)


def _golden_dart_reach() -> set[str]:
    """golden Flutter 진입점에서 import/export/part로 닿는 lib/ 파일(저장소 상대 경로)."""
    pkg_match = re.search(
        r"^name:\s*(\S+)", (_MOBILE / "pubspec.yaml").read_text(encoding="utf-8"), re.M
    )
    assert pkg_match is not None
    pkg = pkg_match.group(1)
    lib = _MOBILE / "lib"
    stack = [lib / "main_golden.dart", *sorted((lib / "golden").glob("*.dart"))]
    seen: set[Path] = set()
    while stack:
        path = stack.pop().resolve()
        if path in seen or not path.exists():
            continue
        seen.add(path)
        for uri in _DART_DIRECTIVE.findall(path.read_text(encoding="utf-8")):
            if uri.startswith(f"package:{pkg}/"):
                stack.append(lib / uri[len(f"package:{pkg}/") :])
            elif not uri.startswith(("package:", "dart:")):
                stack.append(path.parent / uri)
    return {p.relative_to(_REPO).as_posix() for p in seen}


def test_golden_flutter_does_not_reach_legacy() -> None:
    reach = _golden_dart_reach()
    assert len(reach) >= 7, f"golden dart 도달 파일이 너무 적다: {len(reach)}개"  # 공허 통과 금지
    hits = sorted(reach & set(_manifest_flutter_paths()))
    assert hits == [], "golden Flutter가 LEGACY_MANIFEST 파일에 닿는다:\n" + "\n".join(hits)


def test_detectors_have_discrimination() -> None:
    """검출 함수 자체의 변별력 — 걸려야 할 것은 걸리고, 아닌 것은 안 걸린다."""
    src = "import whymath_backend.app\nfrom whymath_backend.l1.rights import gateway\nimport os\n"
    found = imported_modules(src)
    assert "whymath_backend.app" in found
    assert "whymath_backend.l1.rights.gateway" in found  # 그래프 밖 모듈도 AST는 본다
    assert "os" in found
    # 상대 import(golden 내부)는 옛 모듈 후보로 세지 않는다
    assert imported_modules("from . import grade\n") == set()
    assert path_to_module("src/backend/whymath_backend/api/__init__.py") == "whymath_backend.api"
    assert (
        path_to_module("src/backend/whymath_backend/l3/cache/x.py") == "whymath_backend.l3.cache.x"
    )
