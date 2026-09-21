#!/usr/bin/env python3
"""채팅 출력 펜스 가드 — Stop 훅 (HARN-114).

**무엇을 막는가**: Kiki에게 보내는 답변에서 코드 펜스를 *실행용이 아닌* 용도로 쓰는 것.
CLAUDE.md 「실행용 블록과 증거 블록의 분리」(2026-08-31 신설 · 2026-09-10 확장)가 세 번
뚫렸고(HARN-38 → OPS-72 → 2026-09-18), 셋 다 Kiki가 그 펜스를 통째로 붙여넣어
PowerShell 파싱 오류를 냈다. 셋 다 읽기 전용이라 피해는 0이었지만 파괴적 명령이었다면
달랐다.

**왜 "펜스 유무"가 아니라 "실행 의도 태그"인가**: 규칙 본문이 "펜스는 실행용 **전용**"이라고
하므로 실행 블록은 *허용 대상*이다. 줄 맨 앞 백틱 전건을 잡으면 Kiki께 드리는 런북 실행
블록이 전부 막혀 핵심 워크플로가 깨진다. 3회 위반은 **전부 태그 없는 펜스**였고, 그것이
이 기준의 실측 근거다.

**닫는 펜스를 여는 펜스로 오인하지 않는다**: 닫는 줄은 태그가 없으므로, 상태 추적 없이
정규식만 쓰면 *모든 정상 블록이* 태그 없는 펜스 1건을 낳는다 — 가드가 상시 발화해 사람이
게이트를 꺼 버린다. 그래서 열림/닫힘을 추적한다.

**실패 시 막지 않는다**: transcript를 못 읽거나 구조가 바뀌면 조용히 통과시킨다. 관측
실패가 작업 실패가 되면 안 된다(CLAUDE.md 「fail-open 보호」의 취지 — 단 그 경우 로그에
사유를 남겨 무증상 무력화를 피한다).

**한계(예방 아님)**: 이미 화면에 나간 답변은 지울 수 없다. 이것은 탐지 + 강제 재작성 +
기록이며, 예방은 CLAUDE.md 규칙 문장(대체형)과 UserPromptSubmit 상기가 맡는다.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from typing import Any

# 실행 의도 태그 — 이 태그가 붙은 펜스는 "Kiki가 붙여넣어 실행할 것"이므로 허용한다.
# 목록을 늘릴 때는 "그것을 붙여넣어 실행하는가"를 기준으로 판단한다(보여주기용은 늘리지 않는다).
EXECUTION_TAGS: frozenset[str] = frozenset(
    {"powershell", "pwsh", "ps1", "bash", "sh", "shell", "zsh", "cmd", "batch", "bat",
     "python", "py", "sql"}
)

# 사용자가 이 턴에서 명시적으로 코드/파일 내용을 요청한 경우의 탈출구. 사용되면 로그에
# 남긴다 — 남지 않는 탈출구는 게이트를 끄는 것과 같다.
ESCAPE_MARKERS: tuple[str, ...] = ("#코드허용", "#fence-ok")

_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*([A-Za-z0-9_+-]*)\s*$")


def opening_fence_tags(text: str) -> list[str]:
    """답변 텍스트에서 **여는** 펜스들의 언어 태그를 순서대로 돌려준다(닫는 펜스 제외).

    태그가 없으면 빈 문자열이 들어간다. 열림/닫힘을 추적하므로 닫는 줄은 세지 않는다 —
    추적이 없으면 정상 블록마다 태그 없는 펜스가 1건씩 잡혀 가드가 상시 발화한다.
    """
    tags: list[str] = []
    open_marker: str | None = None
    for line in text.splitlines():
        match = _FENCE_RE.match(line)
        if match is None:
            continue
        marker, tag = match.group(1), match.group(2)
        if open_marker is None:
            open_marker = marker[0] * 3  # 백틱/틸드 종류만 기억(길이는 4개 이상도 허용)
            tags.append(tag.lower())
        elif marker[0] * 3 == open_marker and not tag:
            open_marker = None  # 닫는 펜스는 태그가 없다
    return tags


def violating_tags(text: str) -> list[str]:
    """실행 의도 태그가 아닌 여는 펜스들의 태그(태그 없으면 빈 문자열)."""
    return [tag for tag in opening_fence_tags(text) if tag not in EXECUTION_TAGS]


def _is_real_user_prompt(entry: dict[str, Any]) -> bool:
    """도구 실행 결과가 아닌 *진짜* 사용자 메시지인가."""
    if entry.get("type") != "user":
        return False
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return True
    if not isinstance(content, list):
        return False
    return not any(
        isinstance(block, dict) and block.get("type") == "tool_result" for block in content
    )


def _user_text(entry: dict[str, Any]) -> str:
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def last_turn_reply(entries: list[dict[str, Any]]) -> tuple[str, str]:
    """(이번 턴 내 답변 텍스트, 이번 턴 사용자 메시지 텍스트).

    `thinking`·`tool_use` 블록은 제외한다 — Kiki 화면에 가는 것은 `text` 블록뿐이다.
    서브에이전트(`isSidechain`) 출력도 제외한다: 그것은 내 채팅이 아니다.
    """
    last_user = max(
        (i for i, e in enumerate(entries) if _is_real_user_prompt(e)), default=-1
    )
    prompt = _user_text(entries[last_user]) if last_user >= 0 else ""
    texts: list[str] = []
    for entry in entries[last_user + 1 :]:
        if entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue
        for block in entry.get("message", {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
    return "\n".join(texts), prompt


def _log(payload: dict[str, Any]) -> None:
    log_dir = os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", "."), ".claude", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "fence_violations.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError as exc:  # 로그 실패가 작업을 막지 않는다(타입명은 남긴다)
        print(f"[fence_guard] 로그 기록 실패({type(exc).__name__})", file=sys.stderr)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[fence_guard] 입력 파싱 실패({type(exc).__name__}) — 통과", file=sys.stderr)
        return 0

    path = data.get("transcript_path")
    if not path:
        _log({"time": datetime.now(UTC).isoformat(), "skipped": "no_transcript_path"})
        return 0

    entries: list[dict[str, Any]] = []
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # 한 줄이 깨져도 나머지로 판정한다
    except OSError as exc:
        # 관측 실패가 작업 실패가 되면 안 된다 — 다만 무증상으로 두지 않는다.
        _log({"time": datetime.now(UTC).isoformat(), "skipped": f"read_error:{type(exc).__name__}"})
        return 0

    if not entries:
        _log({"time": datetime.now(UTC).isoformat(), "skipped": "empty_transcript"})
        return 0

    reply, prompt = last_turn_reply(entries)
    bad = violating_tags(reply)
    if not bad:
        return 0

    escaped = any(marker in prompt for marker in ESCAPE_MARKERS)
    already_retried = bool(data.get("stop_hook_active"))
    _log(
        {
            "time": datetime.now(UTC).isoformat(),
            "session": data.get("session_id"),
            "tags": bad,
            "count": len(bad),
            "retry": already_retried,
            "escaped": escaped,
        }
    )
    if escaped or already_retried:
        return 0

    print(
        f"[fence_guard] 채팅 펜스 규칙 위반 {len(bad)}건(태그: {bad or ['(없음)']}). "
        "같은 내용을 펜스 없이 다시 쓰라 — 해시·식별자는 인라인 백틱, 명령 결과는 요약 "
        "문장과 인용문, 구조체는 '필드명: 값' 산문. 실행용 블록은 언어 태그"
        f"({', '.join(sorted(EXECUTION_TAGS))})를 붙이면 허용된다.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
