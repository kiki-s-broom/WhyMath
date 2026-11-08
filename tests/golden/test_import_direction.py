"""Flutter 의존 방향 검사 — 옛 화면은 골든 화면을 모른다.

`src/mobile/lib/` 아래에서 `lib/golden/`과 `lib/main_golden.dart`를 뺀 모든 `.dart` 파일이
`golden/` 경로를 import(또는 export·part)하지 않는지 확인한다.
- 골든 쪽(lib/golden/, lib/main_golden.dart)은 옛 코드를 import해도 된다.
- 옛 쪽이 골든을 import하면 실패한다(파이썬 쪽은 import-linter 계약이 같은 방향을 막는다).
- 검사한 파일이 0개면 실패한다(공허한 통과 금지).
"""

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MOBILE_LIB = _REPO_ROOT / "src" / "mobile" / "lib"

# 검사에서 빼는 골든 쪽 경로(lib 기준 상대 경로)
_GOLDEN_DIR = "golden"
_GOLDEN_ENTRY = "main_golden.dart"

# import / export / part 지시문의 URI를 뽑는다. 예: import 'package:x/golden/a.dart';
_DIRECTIVE_URI = re.compile(r"""^\s*(?:import|export|part)\s+['"]([^'"]+)['"]""", re.MULTILINE)

# URI 안에 'golden/'이 경로 조각으로 들어 있는지 본다(앞이 시작·'/'·':'일 때만).
# 'goldenrod/'처럼 이름 일부만 같은 경우나 'my_golden/'은 걸리지 않는다.
_GOLDEN_SEGMENT = re.compile(r"(?:^|[/:])golden/")


def golden_imports(source: str) -> list[str]:
    """dart 소스에서 golden/ 경로를 가리키는 import·export·part URI 목록을 돌려준다."""
    return [uri for uri in _DIRECTIVE_URI.findall(source) if _GOLDEN_SEGMENT.search(uri)]


def _legacy_dart_files() -> list[Path]:
    """골든 쪽을 뺀 옛 dart 파일 전부(정렬)."""
    files = []
    for path in sorted(_MOBILE_LIB.rglob("*.dart")):
        rel = path.relative_to(_MOBILE_LIB)
        if rel.parts[0] == _GOLDEN_DIR or rel.as_posix() == _GOLDEN_ENTRY:
            continue
        files.append(path)
    return files


def test_legacy_dart_files_do_not_import_golden() -> None:
    files = _legacy_dart_files()
    # 공허 통과 금지 — 검사 대상이 하나도 없으면 경로가 틀린 것이다
    assert len(files) > 0, f"검사할 dart 파일이 0개다: {_MOBILE_LIB}"
    print(f"[golden 방향 검사] 옛 dart 파일 {len(files)}개 검사")

    violations = []
    for path in files:
        for uri in golden_imports(path.read_text(encoding="utf-8")):
            violations.append(f"{path.relative_to(_REPO_ROOT).as_posix()}: {uri}")
    assert violations == [], "옛 코드가 golden/을 import한다:\n" + "\n".join(violations)


def test_detector_catches_golden_imports() -> None:
    """검출기 자체가 변별력이 있는지 확인한다 — 걸려야 할 것은 걸리고, 아닌 것은 안 걸린다."""
    must_catch = [
        "import 'package:korean_math_app/golden/answer_screen.dart';",
        "import 'golden/session_screen.dart';",
        "import '../golden/widgets.dart' as g;",
        'export "golden/api.dart";',
        "  part 'golden/part.dart';",
    ]
    must_pass = [
        "import 'package:flutter/material.dart';",
        "import 'core/router.dart';",
        "import 'theme/goldenrod/colors.dart';",
        "import 'my_golden/x.dart';",
        "// import 'golden/commented.dart'; 는 주석이라 지시문이 아니다",
        "final s = 'golden/not_a_directive.dart';",
    ]
    for line in must_catch:
        assert golden_imports(line), f"잡아야 하는데 놓쳤다: {line}"
    for line in must_pass:
        assert not golden_imports(line), f"걸리면 안 되는데 걸렸다: {line}"
