"""논리 격리 검사 — golden은 LEGACY_MANIFEST의 옛 코드를 새로 import하지 않는다(GOLD-17 · S15 결정).

Kiki 결정(2026-11-15): /legacy로 옮기지 않고 논리적으로 격리한다. 옛 코드는 한 줄도 고치지 않는다.
- `golden/LEGACY_MANIFEST.txt` = S15 측정(커밋 a9cff6ec)에서 golden이 한 번도 쓰지 않은 백엔드 722모듈 ·
  Flutter 74파일 + S35 재측정(커밋 bb456fdf)의 추가분 94모듈(S20A 복사로 더는 쓰지 않는 모듈) = 백엔드
  816모듈. 삭제는 3단계 S74에서 패키지 단위로 한다.
- 파이썬 쪽 1차 방어는 import-linter 계약 `golden-no-legacy`(src/backend/pyproject.toml)다.
  이 파일은 그 계약이 매니페스트와 어긋나지 않는지, 그리고 계약이 못 보는 곳을 직접 검사한다.
  - 그래프 밖 모듈(상위 폴더에 __init__.py가 없는 모듈 — 지금은 whymath_backend/l1/rights/ 4개)은
    계약에 넣지 않는다(OPS-164 · Kiki 판정 2026-11-17 B안). import-linter 2.15까지는 그런 이름을 조용히
    통과시켜 아무것도 막지 못했고, 2.16부터는 lint-imports 전체를 exit 1로 만든다(실측).
    → 그 모듈은 golden 소스를 AST로 직접 검사해 막는다. 계약 몫과 AST 몫의 경계는 아래 테스트가 동결한다.
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


def outside_import_graph(module: str, backend_root: Path) -> bool:
    """모듈이 import 그래프 밖인가 — 최상위 패키지 아래 상위 폴더 중 __init__.py 없는 곳이 있으면 True.

    grimp(import-linter의 그래프 엔진)는 __init__.py가 없는 폴더(네임스페이스 패키지)를 따라 내려가지
    않는다. 그래서 그 아래 모듈은 계약이 볼 수 없다. 목록을 손으로 적지 않고 파일 시스템에서 계산하므로,
    누가 rights/에 __init__.py를 더하면 그 4모듈은 자동으로 계약 몫으로 돌아간다.
    """
    parts = module.split(".")
    # 모듈 자신(마지막 조각)은 파일이므로 빼고, 그 위 폴더들만 본다
    for depth in range(1, len(parts)):
        package_dir = backend_root.joinpath(*parts[:depth])
        if not (package_dir / "__init__.py").is_file():
            return True
    return False


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
    assert "bb456fdf" in lines[0] and "2026-11-26" in lines[0]  # S35 재측정
    assert "a9cff6ec" in lines[0] and "2026-11-15" in lines[0]  # S15 첫 측정도 남긴다
    backend, flutter = _manifest_backend_paths(), _manifest_flutter_paths()
    assert len(backend) == 816 and len(set(backend)) == 816  # S15 722 + S35 추가 94
    assert len(flutter) == 74 and len(set(flutter)) == 74
    # 주석·경로 말고는 아무것도 없다(오타 줄이 조용히 빠지는 것 방지)
    assert all(ln.startswith(("#", "src/backend/", "src/mobile/")) for ln in lines)


def test_contract_matches_manifest_exactly() -> None:
    contract = _legacy_contract()
    assert contract["type"] == "forbidden"
    assert contract["source_modules"] == ["golden"]
    backend_root = _REPO / "src" / "backend"
    manifest = {path_to_module(p) for p in _manifest_backend_paths()}
    # 그래프 밖 모듈은 계약 몫이 아니라 AST 검사 몫이다(OPS-164) — 계약에 있으면 2.16에서 exit 1
    outside = {m for m in manifest if outside_import_graph(m, backend_root)}
    expected = manifest - outside
    # 공허 통과 금지: 계약 몫이 거의 전부여야 하고, 그래프 밖으로 빠진 몫이 매니페스트를 먹어 치우면 안 된다
    assert (
        len(expected) >= 700
    ), f"계약 몫이 너무 적다: {len(expected)}개 (그래프 밖 {len(outside)}개)"
    actual = set(contract["forbidden_modules"])  # type: ignore[arg-type]
    assert (
        actual & outside == set()
    ), f"그래프 밖 모듈이 계약에 있다(import-linter 2.16에서 exit 1): {sorted(actual & outside)}"
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


def test_outside_import_graph_has_discrimination(tmp_path: Path) -> None:
    """그래프 밖 판정의 변별력 — 가짜 폴더 구조로 양쪽 방향을 모두 확인한다(OPS-164)."""
    (tmp_path / "pkg" / "inner").mkdir(parents=True)
    (tmp_path / "pkg" / "loose").mkdir()
    (tmp_path / "pkg" / "__init__.py").touch()
    (tmp_path / "pkg" / "inner" / "__init__.py").touch()
    # 대조군: 상위 폴더가 전부 패키지면 그래프 안
    assert outside_import_graph("pkg.inner.mod", tmp_path) is False
    assert outside_import_graph("pkg.mod", tmp_path) is False
    # __init__.py 없는 폴더 아래는 그래프 밖
    assert outside_import_graph("pkg.loose.mod", tmp_path) is True
    # 최상위 패키지 자체에 __init__.py가 없어도 그래프 밖
    assert outside_import_graph("nopkg.mod", tmp_path) is True
    # 실제 저장소: rights 4모듈은 밖, 이웃 l1 모듈은 안
    backend_root = _REPO / "src" / "backend"
    assert outside_import_graph("whymath_backend.l1.rights.gateway", backend_root) is True
    assert outside_import_graph("whymath_backend.l1.standards.populate", backend_root) is False


def test_outside_graph_modules_are_still_guarded_by_ast() -> None:
    """계약에서 뺀 그래프 밖 모듈도 AST 검사가 실제로 잡는다 — 빠진 몫이 무방비가 되지 않게(OPS-164)."""
    backend_root = _REPO / "src" / "backend"
    manifest = {path_to_module(p) for p in _manifest_backend_paths()}
    outside = sorted(m for m in manifest if outside_import_graph(m, backend_root))
    # AST 검사의 대상 집합은 매니페스트 전체이므로(test_golden_python_does_not_import_legacy_directly)
    # 그래프 밖 모듈도 그 집합 안에 있다 — 남은 질문은 검출기가 그 import 문을 실제로 보느냐다
    for module in outside:
        package, _, name = module.rpartition(".")
        found = imported_modules(f"from {package} import {name}\n")
        assert module in found, f"AST 검출기가 그래프 밖 모듈 import를 못 본다: {module}"
        assert imported_modules(f"import {module}\n") == {module}
