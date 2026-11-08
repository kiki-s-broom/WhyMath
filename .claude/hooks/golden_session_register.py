#!/usr/bin/env python3
"""골든 패스 지시문 세션 이름 자동 등록 — UserPromptSubmit 훅.

무엇을 하는가
-------------
`golden/prompts/`·`golden/prompts_no_students/`의 지시문은 첫 줄이
`세션 이름: GP-단계03-S4-…` 형태다.
사용자가 그 파일을 통째로 붙여 넣으면 이 훅이 첫 줄을 읽어
  ① `golden/SESSIONS.md` 등록부에 한 줄을 추가하고(같은 세션·같은 이름이면 중복 추가 없음),
  ② AI에게 "첫 행위로 세션 제목을 이 이름으로 바꿔라"를 stdout으로 알려 준다.
클라우드 세션(claude.ai/code)은 `claude-code-remote`의 `set_session_title` 도구로 AI가 스스로 제목을
바꿀 수 있고, 터미널 Claude Code는 사용자가 `/rename <이름>`을 쳐야 하므로 안내문에 둘 다 적는다.

막지 않는다
-----------
어떤 경우에도 exit 0이다. 등록부 쓰기 실패·입력 파싱 실패는 **예외 타입명**을 stderr에 남기고
통과한다(CLAUDE.md 침묵 실패 금지). 등록부는 저장소 안 파일이라 세션이 커밋하면 남고, 안 하면
로컬에만 남는다.

입력 계약
---------
stdin: Claude Code 훅 JSON(`prompt`·`session_id`·`cwd`). UTF-8 **바이트**로 읽어 직접 해독한다
(CONST-10 — 로캘 텍스트 모드 금지). stdout: 안내문(UTF-8). 지시문이 아니면 아무것도 내지 않는다.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

#: 지시문 첫 줄 — 접두(GP=원본 묶음 · GPN=학생 없는 변형) · 단계 두 자리 · 작업 번호 · 짧은 이름.
_NAME_RE = re.compile(r"^세션 이름:\s*((GPN|GP)-단계(\d{2})-([A-Z]+\d+)-(\S+))\s*$")
_BUNDLE = {"GP": "원본 묶음(golden/prompts)", "GPN": "학생 없는 변형(golden/prompts_no_students)"}
_REGISTRY_REL = Path("golden") / "SESSIONS.md"
_HEADER = (
    "# 골든 패스 작업 세션 등록부\n\n"
    "지시문(`세션 이름:` 첫 줄)을 붙여 넣으면 `.claude/hooks/golden_session_register.py`가 "
    "자동으로 한 줄을 추가한다. 세션 제목 자체는 AI가 `set_session_title`로 바꾸거나(클라우드), "
    "사용자가 `/rename`으로 바꾼다(터미널).\n\n"
    "| 등록 시각(UTC) | 세션 이름 | 작업 | 묶음 | session_id(앞 12자) |\n"
    "| --- | --- | --- | --- | --- |\n"
)


def parse_session_name(prompt: str) -> tuple[str, str, str] | None:
    """프롬프트 첫 3줄에서 (세션 이름, 작업 번호, 묶음 접두)를 찾는다. 지시문이 아니면 None."""
    for line in prompt.splitlines()[:3]:
        m = _NAME_RE.match(line.strip())
        if m:
            return m.group(1), m.group(4), m.group(2)
    return None


def register(repo_root: Path, name: str, task: str, bundle: str, session_id: str) -> bool:
    """등록부에 한 줄을 추가한다. 이미 같은 (이름, session_id) 줄이 있으면 False(추가 없음)."""
    path = repo_root / _REGISTRY_REL
    short_id = (session_id or "")[:12]
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if f"| {name} |" in existing and f"| {short_id} |" in existing:
        return False
    row = (
        f"| {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} | {name} | {task} | "
        f"{_BUNDLE.get(bundle, bundle)} | {short_id} |\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        if not existing:
            fh.write(_HEADER)
        fh.write(row)
    return True


def advice(name: str, registered: bool, registry: Path) -> str:
    """AI에게 보여 줄 안내문 — 등록 결과 + 세션 제목을 맞추는 첫 행위."""
    status = "새로 기록" if registered else "이미 기록돼 있음"
    return (
        f"[골든 패스 세션 등록] 세션 이름 '{name}' → {registry.as_posix()}에 {status}.\n"
        "  첫 행위: claude-code-remote의 set_session_title 도구를 session_id 생략·"
        f"title='{name}'으로 호출해 이 세션의 제목을 바꾼다. "
        "결과(성공/도구 없음)를 보고 첫 줄에 적는다.\n"
        "  그 도구가 없는 환경(터미널 Claude Code)이면 사용자에게 "
        f"`/rename {name}` 한 줄을 안내하고 계속 진행한다."
    )


def run(stdin_bytes: bytes, repo_root: Path) -> tuple[int, str]:
    """훅 본체(순수 함수에 가깝게) — (exit code, stdout 문자열). 테스트가 직접 부른다."""
    try:
        data = json.loads(stdin_bytes.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, ValueError) as exc:
        print(
            f"[golden_session_register] 입력 파싱 실패({type(exc).__name__}) — 통과",
            file=sys.stderr,
        )
        return 0, ""
    if not isinstance(data, dict):
        return 0, ""
    parsed = parse_session_name(str(data.get("prompt") or ""))
    if parsed is None:
        return 0, ""
    name, task, bundle = parsed
    try:
        registered = register(repo_root, name, task, bundle, str(data.get("session_id") or ""))
    except OSError as exc:
        print(
            f"[golden_session_register] 등록부 쓰기 실패({type(exc).__name__}) — 통과",
            file=sys.stderr,
        )
        registered = False
    return 0, advice(name, registered, _REGISTRY_REL)


def _repo_root(data_cwd: str | None) -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    if data_cwd:
        return Path(data_cwd)
    return Path(__file__).resolve().parents[2]


def main() -> int:
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):  # 재구성 불가한 스트림은 그대로 둔다
        pass
    raw = sys.stdin.buffer.read()
    # 저장소 루트는 환경변수 우선, 없으면 훅 입력의 cwd, 그것도 없으면 이 파일 위치에서 역산한다
    cwd: str | None = None
    try:
        peek = json.loads(raw.decode("utf-8", errors="replace"))
        if isinstance(peek, dict):
            cwd = peek.get("cwd")
    except (json.JSONDecodeError, ValueError):
        cwd = None
    code, out = run(raw, _repo_root(cwd))
    if out:
        sys.stdout.buffer.write((out + "\n").encode("utf-8"))
        sys.stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
