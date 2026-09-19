"""HARN-114 — 채팅 출력 펜스 가드의 변별력 동결.

**왜 이 가드가 있는가**: CLAUDE.md 「실행용 블록과 증거 블록의 분리」가 세 번 뚫렸다
(HARN-38 2026-08-31 → OPS-72 2026-09-10 → 2026-09-18). 세 번 다 Kiki가 그 펜스를 통째로
붙여넣어 PowerShell 파싱 오류를 냈고, 세 번 다 "결과가 이렇게 보입니다"를 보여주려던
순간이었다. 텍스트 규칙이 3회 실패했으므로 코드로 내린다.

**이 파일이 지키는 급소 둘**:
  ① 닫는 펜스를 여는 펜스로 오인하지 않는다 — 오인하면 *정상 블록마다* 태그 없는 펜스가
     1건씩 잡혀 가드가 상시 발화하고, 상시 발화하는 게이트는 사람이 꺼 버린다.
  ② 실행 태그 펜스는 통과한다 — 규칙 본문이 "펜스는 실행용 **전용**"이므로 실행 블록은
     허용 대상이다. 전건 차단하면 Kiki께 드리는 런북이 전부 막혀 핵심 워크플로가 깨진다.

hermetic: 순수 함수 + 임시 파일만 — 네트워크·DB 0.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUARD = _REPO_ROOT / ".claude" / "hooks" / "fence_guard.py"


def _load_guard():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("fence_guard", _GUARD)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


def test_guard_file_exists_and_is_executable() -> None:
    """스캔 0건은 실패 — 가드 파일이 없으면 아래 단언들이 공허해진다."""
    assert _GUARD.is_file(), f"가드가 없다: {_GUARD}"


@pytest.mark.parametrize("tag", sorted(guard.EXECUTION_TAGS))
def test_execution_tagged_fences_are_allowed(tag: str) -> None:
    """② 대조군 — 실행 태그 펜스는 위반이 아니다.

    이 단언이 없으면 "전건 차단"이라는 과잉 수정이 아래 위반 테스트들을 전부 통과한다.
    """
    text = f"실행하세요\n```{tag}\nGet-Date\n```\n끝"
    assert guard.violating_tags(text) == []


@pytest.mark.parametrize("tag", ["", "json", "text", "yaml", "output", "log", "diff"])
def test_non_execution_fences_are_violations(tag: str) -> None:
    """태그 없음·비실행 태그는 위반 — 3회 사고가 전부 태그 없는 펜스였다."""
    text = f"결과입니다\n```{tag}\nabc1234\n```\n끝"
    assert guard.violating_tags(text) == [tag]


def test_closing_fence_is_not_counted_as_an_untagged_opening() -> None:
    """① 급소 — 닫는 펜스 오인 방지. 오인하면 정상 블록마다 위반 1건이 잡혀 상시 발화한다."""
    text = "```bash\nls\n```\n산문\n```powershell\nGet-Date\n```"
    assert guard.opening_fence_tags(text) == ["bash", "powershell"]
    assert guard.violating_tags(text) == []


def test_inline_backticks_are_not_fences() -> None:
    """인라인 백틱은 대체 형식이다 — 그것을 위반으로 잡으면 규칙이 자기 대안을 금지한다."""
    assert guard.violating_tags("커밋 `abc1234` 를 보세요") == []


def test_thinking_and_tool_blocks_are_not_chat_output() -> None:
    """Kiki 화면에 가는 것은 text 블록뿐 — thinking/tool_use의 펜스는 위반이 아니다."""
    entries = [
        {"type": "user", "message": {"content": "해줘"}},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "```\n내부 메모\n```"},
                    {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                    {"type": "text", "text": "끝났습니다"},
                ]
            },
        },
    ]
    reply, _ = guard.last_turn_reply(entries)
    assert reply == "끝났습니다"
    assert guard.violating_tags(reply) == []


def test_sidechain_output_is_excluded() -> None:
    """서브에이전트 출력은 내 채팅이 아니다 — 그쪽 펜스로 내 답변이 막히면 안 된다."""
    entries = [
        {"type": "user", "message": {"content": "해줘"}},
        {
            "type": "assistant",
            "isSidechain": True,
            "message": {"content": [{"type": "text", "text": "```\n서브 출력\n```"}]},
        },
        {
            "type": "assistant",
            "isSidechain": False,
            "message": {"content": [{"type": "text", "text": "정리했습니다"}]},
        },
    ]
    reply, _ = guard.last_turn_reply(entries)
    assert guard.violating_tags(reply) == []


def test_tool_result_user_rows_do_not_reset_the_turn() -> None:
    """도구 결과는 '새 사용자 턴'이 아니다 — 리셋되면 턴 중간 답변만 검사하게 된다."""
    entries = [
        {"type": "user", "message": {"content": "해줘"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "시작"}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "```\nx\n```"}]}},
    ]
    reply, prompt = guard.last_turn_reply(entries)
    assert prompt == "해줘"
    assert guard.violating_tags(reply) == [""], "도구 결과 이후 답변이 검사 범위에서 빠졌다"


# ===========================================================================
# end-to-end — 훅을 실제 프로세스로 돌려 exit code를 본다(판정은 exit code로)
# ===========================================================================


def _run_hook(tmp_path: Path, reply: str, *, prompt: str = "해줘", retried: bool = False) -> int:
    transcript = tmp_path / "t.jsonl"
    rows = [
        {"type": "user", "message": {"content": prompt}},
        {
            "type": "assistant",
            "isSidechain": False,
            "message": {"content": [{"type": "text", "text": reply}]},
        },
    ]
    transcript.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8"
    )
    payload = {
        "transcript_path": str(transcript),
        "session_id": "test",
        "stop_hook_active": retried,
    }
    result = subprocess.run(
        [sys.executable, str(_GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"CLAUDE_PROJECT_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
        check=False,
    )
    return result.returncode


def test_hook_blocks_on_violation(tmp_path: Path) -> None:
    """주입 — 태그 없는 펜스면 exit 2(종료 차단)."""
    assert _run_hook(tmp_path, "결과\n```\nabc1234\n```") == 2


def test_hook_passes_execution_block(tmp_path: Path) -> None:
    """대조군 — 실행 태그 펜스면 exit 0."""
    assert _run_hook(tmp_path, "실행\n```powershell\nGet-Date\n```") == 0


def test_hook_does_not_loop_when_already_retried(tmp_path: Path) -> None:
    """무한 반복 방지 — 한 번 되돌려 보낸 뒤에는 기록만 하고 통과."""
    assert _run_hook(tmp_path, "결과\n```\nx\n```", retried=True) == 0


def test_hook_honours_escape_marker(tmp_path: Path) -> None:
    """탈출구 — 사용자가 명시적으로 코드를 요청한 턴은 통과."""
    assert _run_hook(tmp_path, "```\nx\n```", prompt="보여줘 #코드허용") == 0


def test_hook_fails_open_when_transcript_is_missing(tmp_path: Path) -> None:
    """관측 실패가 작업 실패가 되면 안 된다 — 읽을 수 없으면 막지 않는다."""
    payload = {"transcript_path": str(tmp_path / "없음.jsonl"), "session_id": "x"}
    result = subprocess.run(
        [sys.executable, str(_GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"CLAUDE_PROJECT_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert result.returncode == 0
    log = tmp_path / ".claude" / "logs" / "fence_violations.jsonl"
    assert log.is_file(), "관측 실패가 무증상으로 통과했다 — 사유가 로그에 남아야 한다"
    assert "read_error" in log.read_text(encoding="utf-8")


def test_violation_is_logged_with_retry_and_escape_flags(tmp_path: Path) -> None:
    """측정 지표 — 완료 기준이 이 로그의 retry:false 건수이므로 필드가 실제로 남아야 한다."""
    _run_hook(tmp_path, "```\nx\n```")
    log = tmp_path / ".claude" / "logs" / "fence_violations.jsonl"
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]
    assert rows and rows[-1]["retry"] is False and rows[-1]["escaped"] is False
    assert rows[-1]["tags"] == [""]
