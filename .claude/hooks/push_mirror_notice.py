#!/usr/bin/env python3
"""푸시·PR 생성 직전 CI 미러 고지 — PreToolUse(Bash · mcp__github__create_pull_request) 훅 (HARN-209).

**무엇을 알리는가**: `git push` 또는 PR 생성 직전에, 푸시될 HEAD가 로컬 CI 미러를 거치지 않았으면
(결과 없음·다른 커밋의 결과·실패) 알리고, PR 본문에 `## CI 도달 잡` 섹션이 없으면 붙여 넣을 블록을
함께 전한다. `done` 게이트(HARN-173)는 완료 선언 시점에만 서므로 red 푸시는 못 막았다(EOS-24).

**막지 않는다**: 이 훅은 어떤 경우에도 도구 호출을 거부하지 않는다(종료 코드는 항상 0). 판정 근거와
면제 규칙·한계는 `scripts/harness/push_mirror_notice.py`와
`docs/reviews/harn209_push_time_mirror_notice_judgment_2026-10-08.md`가 정본이다. 이 파일은 입력 해독·
로그·중복 억제·출력만 하는 얇은 껍데기다.

**전달 채널**: 종료 코드 0일 때 stdout·stderr 평문은 PreToolUse에서 모델에게 가지 않는다(공식 훅 문서).
모델에게 닿는 경로는 stdout JSON의 `hookSpecificOutput.additionalContext`뿐이다. JSON은
`ensure_ascii=True`로 내보낸다 — 한국어 Windows(cp949) 표준출력에서도 손상되지 않는다.

**침묵 실패 금지**: 평가 중 예외가 나도 도구는 막지 않지만, 예외 **타입명**을 stderr와 로그에 남긴다.
**측정 장치**: 평가한 모든 호출을 `.claude/logs/push_mirror_notices.jsonl`에 한 줄씩 남긴다 — 고지
비율이 푸시 시점 불일치 빈도의 유일한 기록이며 습관화 감시(판정 문서 §6)의 입력이다. 명령 본문은
기록하지 않는다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: 같은 (트리거·HEAD·사유)를 되풀이해 알리지 않기 위한 기억 — 최근 N건만 유지한다.
_DEDUPE_KEEP = 50
_PR_TOOL = "mcp__github__create_pull_request"


def _harness_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "harness"


def _project_root(data: dict[str, Any]) -> Path:
    """작업 저장소 루트. 훅 입력의 cwd에서 git으로 찾고, 실패하면 환경변수·현재 경로로 물러난다."""
    cwd = str(data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".")
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            timeout=15,
        )
        if proc.returncode == 0:
            return Path(proc.stdout.decode("utf-8", errors="replace").strip())
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[push_mirror_notice] 저장소 루트 조회 실패({type(exc).__name__})", file=sys.stderr)
    return Path(cwd)


def _state_path(root: Path) -> Path:
    return root / ".claude" / "cache" / "push_mirror_notice_state.json"


def _already_notified(root: Path, key: str) -> bool:
    try:
        raw = json.loads(_state_path(root).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except (OSError, ValueError) as exc:
        print(
            f"[push_mirror_notice] 중복 억제 상태 읽기 실패({type(exc).__name__})", file=sys.stderr
        )
        return False
    keys = raw.get("keys") if isinstance(raw, dict) else None
    return isinstance(keys, list) and key in keys


def _remember(root: Path, key: str) -> None:
    path = _state_path(root)
    try:
        try:
            keys = json.loads(path.read_text(encoding="utf-8")).get("keys", [])
        except (FileNotFoundError, ValueError, AttributeError):
            keys = []
        keys = [k for k in keys if isinstance(k, str) and k != key] + [key]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"keys": keys[-_DEDUPE_KEEP:]}), encoding="utf-8")
    except OSError as exc:  # 기억 실패는 중복 고지로 끝날 뿐이다 — 막지 않고 타입명을 남긴다
        print(
            f"[push_mirror_notice] 중복 억제 상태 쓰기 실패({type(exc).__name__})", file=sys.stderr
        )


def _log(root: Path, row: dict[str, Any]) -> None:
    path = root / ".claude" / "logs" / "push_mirror_notices.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"[push_mirror_notice] 로그 기록 실패({type(exc).__name__})", file=sys.stderr)


def main() -> int:
    # 훅 입력은 UTF-8 JSON이다. sys.stdin은 로캘 인코딩(한국어 Windows = cp949)으로 해독하므로
    # 바이트로 읽어 직접 해독한다 (tests/infra/test_hook_stdin_utf8.py가 등록된 훅 전수를 검사).
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[push_mirror_notice] 입력 파싱 실패({type(exc).__name__}) — 통과", file=sys.stderr)
        return 0
    if not isinstance(data, dict):
        return 0

    tool = data.get("tool_name")
    tool_input = data.get("tool_input") or {}
    if tool == "Bash":
        command = str(tool_input.get("command") or "")
        if "push" not in command:  # 값싼 선거름 — 대부분의 Bash 호출은 여기서 끝난다
            return 0
    elif tool != _PR_TOOL:
        return 0

    root = _project_root(data)
    now = datetime.now(UTC).isoformat()
    row: dict[str, Any] = {"time": now, "session": data.get("session_id"), "tool": tool}
    try:
        sys.path.insert(0, str(_harness_dir()))
        import push_mirror_notice as pmn  # noqa: PLC0415

        if tool == "Bash":
            result = pmn.notice_for_push(command, root)
        else:
            result = pmn.notice_for_pr_create(
                root, body=tool_input.get("body"), head_ref=tool_input.get("head")
            )
    except (
        Exception
    ) as exc:  # noqa: BLE001  (평가 실패가 푸시·PR을 막으면 안 된다 — 타입명은 남긴다)
        name = type(exc).__name__
        print(f"[push_mirror_notice] 평가 실패({name}) — 통과", file=sys.stderr)
        _log(root, {**row, "code": "hook_error", "notified": False, "error_type": name})
        return 0

    a = result.assessment
    if a.code == pmn.SILENT_NOT_PUSH:
        # "push"라는 낱말만 든 명령(grep·로그 조회 등)은 평가 대상이 아니다 — 로그에 남기면 고지 비율의
        # 분모(평가된 푸시)가 부풀어 습관화 감시(판정 문서 §6)가 왜곡된다.
        return 0
    key = f"{result.trigger}|{a.head}|{a.code}"
    deduped = result.text is not None and _already_notified(root, key)
    notified = result.text is not None and not deduped
    _log(
        root,
        {
            **row,
            "trigger": result.trigger,
            "code": a.code,
            "mirror_state": a.mirror_state,
            "head": a.head,
            "mirror_commit": a.mirror_commit,
            "changed": a.changed,
            "notified": notified,
            "deduped": deduped,
            "error_type": a.error_type,
            "parse_failed": result.parse_failed,
        },
    )
    if not notified or result.text is None:
        return 0
    _remember(root, key)
    payload = {
        "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": result.text}
    }
    print(json.dumps(payload, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
