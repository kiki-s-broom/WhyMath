"""요청 단계 범위 대조 (HARN-321) — UserPromptSubmit 훅이 매 요청 앞에 놓는 기준선.

왜 필요한가: 하네스는 세션 시작(brief)·편집 직후(check-edit scope_drift)·종료(check-stop)
에서 검사하지만, **요청을 받는 순간**에는 아무것도 대조하지 않았다. 그래서 "아 그리고
이것도" 같은 범위 밖 요청은 파일을 고친 *뒤에야* 경고로 드러났다. 이 모듈은 요청마다
"이 세션이 무엇을 잡았고 범위가 어디까지인가"를 Claude 앞에 놓는다.

설계 원칙:
- **결정적**: LLM 판정이 아니라 대장 사실만 쓴다(같은 입력 → 같은 출력·비용 0).
- **가볍다**: 대장 전체 로드(실측 3.1초)를 하지 않는다. `session:` 줄 텍스트 스캔으로
  후보를 고르고, 내 claim 파일과 요청이 언급한 ID 파일만 YAML로 파싱한다.
- **막지 않는다**: 판정은 안내일 뿐이다. 어떤 실패에서도 호출측은 exit 0으로 끝난다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

# 요청 속 태스크 ID 후보. 실제 태스크 접두어(HARN·EOS·P3…)에 해당할 때만 쓴다 —
# 그래야 UTF-8·R18-02 같은 비태스크 표기가 "대장에 없음"으로 오보되지 않는다.
_ID_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{0,6}-\d{1,4})(?![0-9])")
_MAX_MENTIONS = 5
_MAX_PATHS = 4
_TITLE_CHARS = 70


def _tasks_dir(root: Path) -> Path:
    return root / "backlog" / "tasks"


def _parse(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _short(text: str, limit: int = _TITLE_CHARS) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def find_my_claims(root: Path, branch: str) -> list[dict[str, Any]]:
    """이 브랜치가 잡은 in_progress 태스크. 텍스트 스캔으로 후보를 좁힌 뒤에만 파싱한다."""
    if not branch or branch in ("main", "unknown"):
        return []
    needle = f"\nsession: {branch}\n"
    claims = []
    for path in sorted(_tasks_dir(root).glob("*.yaml")):
        if needle not in path.read_text(encoding="utf-8"):
            continue
        data = _parse(path)
        if data.get("status") == "in_progress" and data.get("session") == branch:
            claims.append(data)
    return claims


def known_prefixes(root: Path) -> set[str]:
    """대장에 실재하는 태스크 접두어(파일명 기준 — 파싱 없음)."""
    prefixes = set()
    for path in _tasks_dir(root).glob("*.yaml"):
        match = re.match(r"([A-Z][A-Z0-9]*)-\d", path.name)
        if match:
            prefixes.add(match.group(1))
    return prefixes


def mentioned_ids(prompt: str, prefixes: set[str]) -> list[str]:
    seen: list[str] = []
    for raw in _ID_RE.findall(prompt or ""):
        if raw.split("-")[0] in prefixes and raw not in seen:
            seen.append(raw)
        if len(seen) >= _MAX_MENTIONS:
            break
    return seen


def lookup(root: Path, task_id: str) -> dict[str, Any] | None:
    """번호 ID(`HARN-12`)로 태스크 파일을 찾는다. `HARN-12-slug.yaml`·`HARN-12.yaml` 둘 다."""
    tasks = _tasks_dir(root)
    for path in [tasks / f"{task_id}.yaml", *sorted(tasks.glob(f"{task_id}-*.yaml"))]:
        if not path.is_file():
            continue
        data = _parse(path)
        found = str(data.get("id", ""))
        if found == task_id or found.startswith(task_id + "-"):
            return data
    return None


def _describe_mention(task_id: str, data: dict[str, Any] | None, branch: str) -> str | None:
    if data is None:
        return (
            f"언급 ID {task_id}: 로컬 대장에 없음 — 오타이거나 미머지 브랜치에만 있는 태스크다. "
            f"'없다'로 단정하지 말고 `git log --all --grep={task_id}`로 확인하라"
        )
    status = data.get("status")
    session = data.get("session")
    if status == "in_progress" and session == branch:
        return None  # 내 claim은 위 줄에서 이미 보여 줬다
    if status == "in_progress":
        return f"언급 ID {task_id}: 다른 세션이 claim 중({session} · 로컬 대장 기준) — 착수 금지"
    if status in ("done", "cancelled"):
        return f"언급 ID {task_id}: {status} — 다시 손대려면 재착수가 아니라 후속 태스크로 등재하라"
    if status in ("todo", "blocked", "review"):
        return (
            f"언급 ID {task_id}: {status} (이 세션 claim 아님) — "
            f"손대기 전에 `backlog.py start {task_id}`"
        )
    return f"언급 ID {task_id}: 상태 {status}"


def build_context(root: Path, branch: str, prompt: str) -> list[str]:
    """훅이 출력할 줄 목록. 첫 줄은 표제."""
    lines = ["[요청 범위 대조 · HARN-321] (안내 전용 — 차단하지 않음)"]
    claims = find_my_claims(root, branch)
    if claims:
        for task in claims:
            paths = [str(p) for p in task.get("paths") or []]
            extra = len(paths) - _MAX_PATHS
            shown = ", ".join(paths[:_MAX_PATHS]) + (f" 외 {extra}" if extra > 0 else "")
            lines.append(
                f"- 이 세션 claim: {task.get('id')} — {_short(task.get('title', ''))}"
                f" · 범위: {shown or '(paths 미지정)'}"
            )
        lines.append(
            "- 요청이 위 범위 밖의 변경을 요구하면, 손대기 전에 사용자에게 "
            "'새 태스크로 등록(add)할지 / 현재 범위를 넓힐지(amend)'를 먼저 물어라"
        )
    else:
        lines.append(
            "- 이 세션 claim 없음 — 코드·문서를 바꾸는 요청이면 첫 행위는 "
            "`backlog.py start <id>`(대장에 없으면 `add` 후 start). 조사·질문이면 해당 없음"
        )
    for task_id in mentioned_ids(prompt, known_prefixes(root)):
        line = _describe_mention(task_id, lookup(root, task_id), branch)
        if line:
            lines.append("- " + line)
    return lines
