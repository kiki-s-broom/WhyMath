"""CONST-10 — 훅 스크립트는 stdin 을 로캘 텍스트 모드로 읽지 않는다 (등록된 훅 전수 AST 가드).

**왜 이 가드가 있는가**: Claude Code 는 훅 입력을 UTF-8 JSON 으로 보낸다. `json.load(sys.stdin)` 은
그것을 **프로세스 로캘 인코딩**(한국어 Windows = cp949)으로 해독한다 — 한글이나 '—'(UTF-8
E2 80 94)가 섞이면 `UnicodeDecodeError` 이고, 이 저장소의 훅은 그 예외를 `except ValueError` 로
받아 **"입력 파싱 실패 — 통과"** 로 끝냈다. 가드가 조용히 꺼진 것이다(2026-09-28 CONST-02 이식 중
`guard_constitution.py` 에서 발견 → 같은 형태의 기존 훅 3종이 전부 그랬다).

**왜 개별 테스트만으로는 부족한가**: 훅마다 cp949 회귀 테스트를 두면(각 `test_*_guard.py`) 그 훅은
지켜지지만, **다음에 추가되는 훅**은 같은 실수를 새로 한다. 이 파일은 개별 훅이 아니라 *형태*를 막는다.

**금지 문자열 열거가 아니라 구성된 결과를 본다**: `json.load(sys.stdin)` 만 찾으면
`sys.stdin.read()` · `for line in sys.stdin` · `input()` 으로 뚫린다. 그래서 AST 에서 `sys.stdin`
참조 중 `.buffer` · `.isatty` · `.fileno` 가 아닌 것 전부를 위반으로 센다.

정직한 공백(못 보는 것)
- `import sys as s` 같은 **별칭**으로 부른 `s.stdin` 은 못 본다(현재 훅에는 없다).
- `open(0)` · `os.fdopen(0)` 처럼 파일 기술자로 여는 텍스트 읽기는 못 본다.
- `sys.stdin.reconfigure(encoding="utf-8")` 도 올바른 수정이지만 **위반으로 센다** — 이 저장소의
  표준을 `.buffer` + 명시 해독 한 가지로 고정하기 위해서다(`guard_constitution.py` 와 같은 형태).

**열외는 스스로 만료된다**: 아직 고치지 않은 훅 진입점은 `_OPEN_SITES` 에 소유 태스크와 함께
이름으로 적는다. 그 파일이 더는 위반하지 않으면 `test_open_sites_are_still_violations` 가 실패해
열외를 지우게 만든다 — 만료 없는 유예를 두지 않는다(CLAUDE.md "만료 없는 유예·제외 금지").
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TASKS_DIR = _REPO_ROOT / "backlog" / "tasks"

#: 아직 고치지 않은 훅 진입점 → 그것을 소유한 태스크(full id). 이 표가 비면 CONST-10 의 목표가 끝난 것이다.
#: `backlog.py` 는 check-edit·check-stop 이 stdin 을 읽는데, 이 두 명령을 부르는 테스트 대역
#: (`io.StringIO` — `.buffer` 없음)가 5개 파일 10곳이라 CONST-10 범위 밖으로 분리했다.
_OPEN_SITES: dict[str, str] = {
    "scripts/harness/backlog.py": "HARN-196-hook-stdin-utf8-backlog-cli-audit",
}

#: `sys.stdin.<attr>` 중 **해독을 하지 않는** 사용 — 바이트 계층 · 대화형 판정 · 기술자 번호.
_NON_DECODING_ATTRS = frozenset({"buffer", "isatty", "fileno"})

_SCRIPT_RE = re.compile(r'\$CLAUDE_PROJECT_DIR/([^"\s]+\.py)')


def text_mode_stdin_reads(source: str) -> list[int]:
    """stdin 을 로캘 텍스트 모드로 읽는 줄 번호 — AST (순수 함수)."""
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {
        child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
    }
    found: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in ("stdin", "__stdin__")
            and isinstance(node.value, ast.Name)
            and node.value.id == "sys"
        ):
            parent = parents.get(node)
            if isinstance(parent, ast.Attribute) and parent.attr in _NON_DECODING_ATTRS:
                continue
            found.add(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module == "sys":
            if any(alias.name in ("stdin", "__stdin__") for alias in node.names):
                found.add(node.lineno)
        elif isinstance(node, ast.Call):
            func = node.func
            # `input()` 은 내부에서 sys.stdin 을 텍스트로 읽는다
            if isinstance(func, ast.Name) and func.id == "input":
                found.add(node.lineno)
            # 바이트 계층을 얻어도 로캘 기본값 `TextIOWrapper` 로 다시 감싸면 같은 결함이다
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name == "TextIOWrapper" and not any(kw.arg == "encoding" for kw in node.keywords):
                found.add(node.lineno)
    return sorted(found)


def registered_hook_scripts(root: Path = _REPO_ROOT) -> list[str]:
    """`settings.json` 의 훅 명령이 실행하는 `.py` 스크립트 — 저장소 상대 경로."""
    cfg = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    found: set[str] = set()
    for entries in cfg.get("hooks", {}).values():
        for entry in entries:
            for hook in entry.get("hooks", []):
                found.update(_SCRIPT_RE.findall(hook.get("command", "")))
    return sorted(found)


def scanned_scripts(root: Path = _REPO_ROOT) -> list[str]:
    """스캔 대상 = 등록된 훅 ∪ `.claude/hooks/*.py` — 등록을 빠뜨린 훅 스크립트도 본다."""
    on_disk = {p.relative_to(root).as_posix() for p in (root / ".claude" / "hooks").glob("*.py")}
    return sorted(on_disk | set(registered_hook_scripts(root)))


def _violations(rel: str) -> list[int]:
    return text_mode_stdin_reads((_REPO_ROOT / rel).read_text(encoding="utf-8"))


# ===========================================================================
# 스캔이 공허하지 않다 — 대상을 하나도 못 찾은 전수 가드는 공허하게 통과한다
# ===========================================================================


def test_scan_is_not_vacuous() -> None:
    scanned = scanned_scripts()
    assert len(scanned) >= 5, f"스캔 대상이 너무 적다 — 공허 통과 금지: {scanned}"
    for name in ("git_revert_guard", "fence_guard", "chat_block_guard", "guard_constitution"):
        assert f".claude/hooks/{name}.py" in scanned, f"{name} 이 스캔에서 빠졌다"
    assert "scripts/harness/backlog.py" in scanned, "settings.json 등록 훅(backlog.py)이 빠졌다"


def test_registered_hook_scripts_exist() -> None:
    """등록만 있고 파일이 없으면 배선이 거짓이다."""
    for rel in registered_hook_scripts():
        assert (_REPO_ROOT / rel).is_file(), f"settings.json 이 없는 파일을 훅으로 등록했다: {rel}"


def _fake_repo(tmp_path: Path) -> Path:
    """등록된 훅 하나(`.claude/hooks` 밖) + 등록을 빠뜨린 훅 하나(`.claude/hooks` 안)를 가진 저장소."""
    (tmp_path / ".claude" / "hooks").mkdir(parents=True)
    (tmp_path / ".claude" / "hooks" / "orphan.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "registered.py").write_text("x = 1\n", encoding="utf-8")
    settings = {
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {"command": 'python3 "$CLAUDE_PROJECT_DIR/scripts/registered.py" check'}
                    ]
                }
            ]
        }
    }
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    return tmp_path


def test_scan_includes_unregistered_scripts_on_disk(tmp_path: Path) -> None:
    """**합집합의 디스크 절** — 실제 저장소에서는 두 집합이 같아 이 절을 지워도 통과한다.

    등록을 빠뜨린 훅 스크립트가 스캔에서 빠지면, 나중에 등록되는 순간 검사를 한 번도 받지
    않은 훅이 켜진다. 임시 저장소로 그 절을 실제로 밟는다.
    """
    assert ".claude/hooks/orphan.py" in scanned_scripts(_fake_repo(tmp_path))


def test_scan_includes_registered_scripts_outside_hooks_dir(tmp_path: Path) -> None:
    """**합집합의 등록 절** — `backlog.py` 처럼 `.claude/hooks` 밖에서 등록된 훅도 본다."""
    assert "scripts/registered.py" in scanned_scripts(_fake_repo(tmp_path))


# ===========================================================================
# 본 가드 — 훅 스크립트는 stdin 을 바이트로 읽어 UTF-8 로 직접 해독한다
# ===========================================================================


@pytest.mark.parametrize("rel", [r for r in scanned_scripts() if r not in _OPEN_SITES])
def test_hook_scripts_read_stdin_as_utf8_bytes(rel: str) -> None:
    lines = _violations(rel)
    assert lines == [], (
        f"{rel}:{lines} 가 stdin 을 로캘 인코딩 텍스트 모드로 읽는다 — 한국어 Windows(cp949)에서 "
        "한글·'—' 입력이 UnicodeDecodeError 가 되어 훅이 조용히 꺼진다(CONST-10). "
        '`json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))` 로 읽어라.'
    )


def test_open_sites_are_still_violations() -> None:
    """열외의 **자기 만료** — 고쳐졌으면 열외를 지워야 한다(만료 없는 유예 금지)."""
    scanned = set(scanned_scripts())
    for rel, owner in _OPEN_SITES.items():
        assert rel in scanned, f"열외 {rel} 가 스캔 대상이 아니다 — 죽은 열외다"
        assert _violations(
            rel
        ), f"열외 {rel} 는 이제 위반하지 않는다 — `_OPEN_SITES` 에서 지워라(소유 태스크 {owner})"
        assert (
            _TASKS_DIR / f"{owner}.yaml"
        ).is_file(), f"열외의 소유 태스크가 대장에 없다: {owner}"


# ===========================================================================
# 검사기의 변별력 — 절마다 그 절이 없으면 통과하는 반례를 둔다
# ===========================================================================


@pytest.mark.parametrize(
    "source",
    [
        "import json, sys\njson.load(sys.stdin)",  # 종전 형태
        "import sys\nsys.stdin.read()",  # json.load 가 아니어도
        "import sys\nfor line in sys.stdin:\n    pass",  # 순회
        "import sys\nsys.stdin.reconfigure(encoding='utf-8')",  # 표준을 .buffer 한 가지로 고정
        "from sys import stdin",  # from-import 우회
        "data = input()",  # 내부에서 sys.stdin 텍스트 읽기
        "import io, sys\nio.TextIOWrapper(sys.stdin.buffer)",  # 바이트를 로캘 기본값으로 다시 감쌈
        "import sys\nsys.__stdin__.read()",  # 원본 스트림
    ],
)
def test_checker_flags_text_mode_reads(source: str) -> None:
    assert len(text_mode_stdin_reads(source)) == 1, source


@pytest.mark.parametrize(
    "source",
    [
        "import sys\nsys.stdin.buffer.read().decode('utf-8', errors='replace')",  # 올바른 형태
        "import sys\nsys.stdin.isatty()",  # 해독을 하지 않는다
        "import io, sys\nio.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')",  # 명시 인코딩
        "import sys\nprint('x', file=sys.stderr)",  # stdin 이 아니다
    ],
)
def test_checker_passes_byte_level_and_non_decoding_uses(source: str) -> None:
    assert text_mode_stdin_reads(source) == [], source
