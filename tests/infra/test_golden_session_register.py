"""골든 패스 세션 이름 자동 등록 훅(`.claude/hooks/golden_session_register.py`) 계약.

지시문 첫 줄 `세션 이름: GP-단계NN-…`을 붙여 넣으면 `golden/SESSIONS.md`에 한 줄이 추가되고 AI에게
세션 제목을 바꾸라는 안내가 stdout으로 나간다. 지시문이 아니면 아무것도 하지 않고, 어떤 입력에도
막지 않는다(exit 0). 실패 주입(깨진 JSON·쓰기 불가 경로)에서도 exit 0과 stderr 타입명을 확인한다.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _REPO_ROOT / ".claude" / "hooks" / "golden_session_register.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("golden_session_register", _HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = _load()

_PROMPT_GP = "세션 이름: GP-단계03-S4-API3개-튜터\n\n# [WhyMath 골든 패스] 작업 S4: …\n본문"
_PROMPT_GPN = "세션 이름: GPN-단계07-S11-AI시뮬학생3종\n\n# 변형\n본문"


def _stdin(prompt: str, session_id: str = "session_01ABCDEFGHIJKLMNOP") -> bytes:
    return json.dumps({"prompt": prompt, "session_id": session_id, "cwd": "/x"}).encode("utf-8")


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        (_PROMPT_GP, ("GP-단계03-S4-API3개-튜터", "S4", "GP")),
        (_PROMPT_GPN, ("GPN-단계07-S11-AI시뮬학생3종", "S11", "GPN")),
        ("  세션 이름: GP-단계01-H1-학생섭외-Kiki  \n", ("GP-단계01-H1-학생섭외-Kiki", "H1", "GP")),
    ],
)
def test_parse_accepts_instruction_first_line(prompt: str, expected: tuple[str, str, str]) -> None:
    assert hook.parse_session_name(prompt) == expected


@pytest.mark.parametrize(
    "prompt",
    [
        "오늘 할 일 정리해 줘",
        "세션 이름: PED17-단계01-T0-결정기록",  # 다른 묶음 접두 — 이 훅의 대상이 아니다
        "세션 이름: GP-단계3-S4-짧은이름",  # 단계 두 자리가 아니다
        "세션 이름: GP-단계03-S4",  # 짧은 이름 누락
        "본문\n본문\n본문\n세션 이름: GP-단계03-S4-API3개-튜터",  # 첫 3줄 밖
    ],
)
def test_parse_rejects_non_instruction(prompt: str) -> None:
    assert hook.parse_session_name(prompt) is None


def test_run_registers_row_and_advises_title_change(tmp_path: Path) -> None:
    code, out = hook.run(_stdin(_PROMPT_GP), tmp_path)
    assert code == 0
    registry = tmp_path / "golden" / "SESSIONS.md"
    text = registry.read_text(encoding="utf-8")
    assert text.startswith("# 골든 패스 작업 세션 등록부")
    rows = [line for line in text.splitlines() if line.startswith("| 20")]
    assert len(rows) == 1
    assert "| GP-단계03-S4-API3개-튜터 | S4 | 원본 묶음(golden/prompts) | session_01AB |" in rows[0]
    assert "set_session_title" in out and "GP-단계03-S4-API3개-튜터" in out and "/rename" in out
    assert "새로 기록" in out


def test_run_is_idempotent_for_same_session(tmp_path: Path) -> None:
    hook.run(_stdin(_PROMPT_GP), tmp_path)
    _, out2 = hook.run(_stdin(_PROMPT_GP), tmp_path)
    rows = [
        line
        for line in (tmp_path / "golden" / "SESSIONS.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| 20")
    ]
    assert len(rows) == 1
    assert "이미 기록돼 있음" in out2


def test_run_distinguishes_sessions_and_bundles(tmp_path: Path) -> None:
    hook.run(_stdin(_PROMPT_GP, "session_A"), tmp_path)
    hook.run(_stdin(_PROMPT_GP, "session_B"), tmp_path)
    hook.run(_stdin(_PROMPT_GPN, "session_C"), tmp_path)
    text = (tmp_path / "golden" / "SESSIONS.md").read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("| 20")]
    assert len(rows) == 3
    assert "학생 없는 변형(golden/prompts_no_students)" in rows[2]


def test_run_ignores_ordinary_prompt(tmp_path: Path) -> None:
    code, out = hook.run(_stdin("오늘 할 일 정리해 줘"), tmp_path)
    assert (code, out) == (0, "")
    assert not (tmp_path / "golden").exists()


def test_run_survives_broken_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = hook.run(b"\xff{not json", tmp_path)
    assert (code, out) == (0, "")
    assert "JSONDecodeError" in capsys.readouterr().err


@pytest.mark.skipif(
    os.name == "nt" or os.geteuid() == 0, reason="권한 거부 주입은 비-root POSIX에서만"
)
def test_run_survives_unwritable_registry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    golden = tmp_path / "golden"
    golden.mkdir()
    golden.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        code, out = hook.run(_stdin(_PROMPT_GP), tmp_path)
    finally:
        golden.chmod(stat.S_IRWXU)
    assert code == 0
    assert "PermissionError" in capsys.readouterr().err
    assert "set_session_title" in out  # 등록 실패해도 제목 변경 안내는 나간다


def test_hook_is_registered_on_user_prompt_submit() -> None:
    settings = json.loads((_REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [
        h.get("command", "")
        for entry in settings["hooks"]["UserPromptSubmit"]
        for h in entry.get("hooks", [])
    ]
    assert any("golden_session_register.py" in c for c in commands), commands


def test_prompt_bundles_start_with_session_name_line() -> None:
    """생성된 지시문 전부가 훅이 읽는 첫 줄 형식을 실제로 갖는다(배선 공허 방지)."""
    files = sorted((_REPO_ROOT / "golden").glob("prompts*/단계*/*.md"))
    assert files, "지시문 파일이 0개 — 스캔이 공허하다"
    for path in files:
        first = path.read_text(encoding="utf-8").splitlines()[0]
        parsed = hook.parse_session_name(first)
        assert parsed is not None, f"{path.name}: 첫 줄이 '세션 이름:' 형식이 아니다 — {first!r}"
        assert parsed[0] == path.stem, f"{path.name}: 첫 줄 이름과 파일 이름이 다르다"


def test_main_reads_stdin_as_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """엔트리포인트가 stdin을 바이트로 읽고 stdout을 UTF-8 바이트로 쓴다(CONST-10·CONST-12)."""
    import io

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    fake_in = io.TextIOWrapper(io.BytesIO(_stdin(_PROMPT_GP)), encoding="utf-8")
    fake_out = io.TextIOWrapper(io.BytesIO(), encoding="cp949")  # 파이프 로캘이 cp949여도
    monkeypatch.setattr(sys, "stdin", fake_in)
    monkeypatch.setattr(sys, "stdout", fake_out)
    assert hook.main() == 0
    fake_out.buffer.seek(0)
    assert "GP-단계03-S4-API3개-튜터" in fake_out.buffer.read().decode("utf-8")
