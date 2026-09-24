#!/usr/bin/env python3
"""채팅 실행 블록의 상태 전환 자가거부 가드 — Stop 훅 (HARN-163).

**무엇을 막는가**: Kiki에게 채팅으로 건네는 PowerShell 블록이 상태 전환 명령(체크아웃·
브랜치 전환·pull·환경 활성화)을 담고 있는데, 그 전환이 **실패해도 뒤 명령이 계속 도는**
형태. PowerShell 대화형 붙여넣기에서 `git checkout main`의 실패는 흐름을 멈추지 않는다 —
뒤따르는 적재·LLM 회차가 엉뚱한 트리에서 돈다.

사고 2회 (같은 브랜치·같은 커밋 `0367fce4`):
  - 2026-09-15 `G-skb03` — 런북 블록. 대책 HARN-106(`scripts/ops/check_runbook_blocks.py`).
  - 2026-09-23 `G-kg02` — **채팅** 블록. `git checkout main`·`git pull`이 미커밋 변경 때문에
    둘 다 실패했는데 dry-run과 실 LLM 회차가 그대로 돌았다. 블록에 있던 확인 3줄
    (`Test-Path` CLI·코퍼스)은 전부 True였는데, 그 파일들은 **두 트리 모두에** 있어 판정력이
    0이었다.

**사각 (acceptance ①)**: HARN-106 스캐너는 저장소 런북 파일(`docs/ops/*runbook*.md`)만 읽고,
판정 축도 *쓰기* 명령뿐이다(`git checkout`·`git pull`은 쓰기 어휘에 없다). HARN-114
(`fence_guard.py`)는 펜스의 **언어 태그**만 본다 — `powershell` 태그면 내용과 무관하게
통과한다. 채팅 블록의 *내용*을 보는 장치는 어느 쪽에도 없었다
(`tests/infra/test_chat_block_guard.py::test_blind_spot_*`가 세 장치에 같은 블록을 넣어 동결).

**계약 (acceptance ②③)** — 전환 명령이 있는 블록에서, 마지막 전환 **뒤**의 동작 명령은:
  ⓐ 실제 상태를 **동일성으로** 되읽은 값(`git rev-parse`·`branch --show-current`·
     `git diff --quiet`·`sys.executable` 등)을 변수에 받아 화면에 출력하고
  ⓑ 그 되읽기 변수에서 파생된 조건(비교 연산자 필수 — 존재·truthy 검사는 판정력이 없다.
     `git rev-parse`는 실패 시 입력 문자열을 그대로 돌려주므로 빈 값 검사로는 못 가른다)의
  ⓒ 단일 최상위 `if (…) { …뒤 단계… } else { …무엇이 달랐는지… }`(같은 줄 `} else {`) 안에
     있어야 한다 — HARN-106 ①과 같은 형태이며 가드 판정 함수는 그 스캐너의 것을 재사용한다.
`Test-Path`는 되읽기로 세지 않는다 — 존재 검사는 잘못된 트리에서도 True를 낸다(③).

**왜 fence_guard.py에 얹지 않고 별도 훅인가 (acceptance ④ 판정 근거 — 소스 확인)**:
  - 얹을 수 **있다**: `fence_guard.last_turn_reply()`가 transcript에서 이번 턴의 채팅 텍스트만
    뽑아 주므로(`thinking`·`tool_use`·사이드체인 제외) 필요한 입력이 이미 있다. 그래서 이 훅은
    그 함수를 **import해서 재사용**한다 — transcript 파서는 하나다.
  - 그러나 지금 얹지 **않는다**: HARN-114는 2주 측정 창(만료 2026-10-02경) 중이고 완료 기준이
    `fence_violations.jsonl`의 `retry:false` 건수다. 그 훅의 `main()`에 판정을 더하면 같은
    로그·같은 exit 경로가 섞여 측정이 오염된다. 로그를 `chat_block_violations.jsonl`로
    분리하고 exit 경로도 독립시켰다. 만료 후 통합 여부는 그때 판정한다(두 훅이 같은
    파서를 쓰므로 통합 비용은 `main()` 병합뿐이다).

**실패 시 막지 않는다**: transcript·의존 모듈을 못 읽으면 사유를 로그에 남기고 통과한다
(HARN-114 ⑥ 선례 — 관측 실패가 작업 실패가 되면 안 된다).

**범위 한계(명시)**: PowerShell 태그(`powershell`·`pwsh`·`ps1`) 블록만 본다 — Kiki 머신
안내는 PowerShell 기준이다(CLAUDE.md). bash 블록의 `set -e`·`&&` 체인은 판정하지 않는다.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from types import ModuleType
from typing import Any

_HERE = pathlib.Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
_RUNBOOK_SCANNER = _REPO_ROOT / "scripts" / "ops" / "check_runbook_blocks.py"
_FENCE_GUARD = _HERE / "fence_guard.py"

POWERSHELL_TAGS: frozenset[str] = frozenset({"powershell", "pwsh", "ps1"})

# 사용자가 이 턴에서 명시적으로 허용한 경우의 탈출구 — 쓰이면 로그에 남는다.
ESCAPE_MARKERS: tuple[str, ...] = ("#전환허용", "#switch-ok")

# ── 상태 전환 어휘 ────────────────────────────────────────────────────────
# 각 항목이 왜 있는가: 실패해도 PowerShell 붙여넣기 흐름이 멈추지 않고, 실패하면 뒤 명령이
# *다른 코드·다른 인터프리터*를 보게 되는 명령들이다.
_TRANSITIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("git checkout", re.compile(r"\bgit\s+checkout\b", re.IGNORECASE)),
    ("git switch", re.compile(r"\bgit\s+switch\b", re.IGNORECASE)),
    ("git pull", re.compile(r"\bgit\s+pull\b", re.IGNORECASE)),
    ("git reset", re.compile(r"\bgit\s+reset\b", re.IGNORECASE)),
    ("git merge", re.compile(r"\bgit\s+merge\b", re.IGNORECASE)),
    ("git rebase", re.compile(r"\bgit\s+rebase\b", re.IGNORECASE)),
    ("git worktree add", re.compile(r"\bgit\s+worktree\s+add\b", re.IGNORECASE)),
    ("환경 활성화", re.compile(r"\bactivate(?:\.ps1)?\b", re.IGNORECASE)),
)

# ── 동일성 되읽기 어휘 ────────────────────────────────────────────────────
# 존재 검사(`Test-Path`·`Get-ChildItem`)는 **의도적으로 없다** — 잘못된 트리에서도 True를
# 낸다(2026-09-23 실측: 확인 3줄 전부 True, 판정력 0).
_READBACK = re.compile(
    r"rev-parse|branch\s+--show-current|symbolic-ref|git\s+diff\s+--quiet|"
    r"git\s+log\s+-1|sys\.executable|__file__|VIRTUAL_ENV|CONDA_DEFAULT_ENV",
    re.IGNORECASE,
)
# 읽기 전용 git — 전환 뒤에 와도 상태를 바꾸지 않는다. 이것까지 가드를 요구하면 정상 블록이
# 위반으로 잡혀 사람이 가드를 끈다(과잉 수정 방지 — 대조군 `test_read_only_git_*`).
_READ_ONLY_GIT = re.compile(
    r"^\s*git\s+(?:status|log|show|fetch|diff|remote|ls-files|cat-file|branch\s+--show-current)\b",
    re.IGNORECASE,
)
_EXISTENCE_ONLY = re.compile(r"\bTest-Path\b|\bGet-ChildItem\b", re.IGNORECASE)
_COMPARISON = re.compile(
    r"-c?(?:eq|ne|like|notlike|match|notmatch|in|notin|contains|notcontains)\b", re.IGNORECASE
)
_ASSIGN = re.compile(r"^\s*(\$[A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)\s*(.*)$")
_VAR = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*([A-Za-z0-9_+-]*)\s*$")
_OUTPUT_ONLY = re.compile(r"^\s*(?:write-host|write-output|echo)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    """위반 1건."""

    block_index: int
    axis: str
    detail: str


def _load(name: str, path: pathlib.Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"모듈 스펙 없음: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclass가 자기 모듈을 찾을 수 있게
    spec.loader.exec_module(module)
    return module


def powershell_blocks(text: str) -> list[list[str]]:
    """채팅 텍스트에서 PowerShell 태그 펜스의 **본문 줄**들을 뽑는다.

    다른 언어 펜스도 열림/닫힘을 추적한다 — 추적하지 않으면 그 펜스의 닫는 줄이 새 펜스의
    여는 줄로 오인돼 뒤따르는 산문이 코드로 읽힌다.
    """
    blocks: list[list[str]] = []
    current: list[str] | None = None
    open_marker: str | None = None
    for line in text.splitlines():
        match = _FENCE.match(line)
        if open_marker is None:
            if match:
                open_marker = match.group(1)[0]
                current = [] if match.group(2).lower() in POWERSHELL_TAGS else None
            continue
        if match and match.group(1)[0] == open_marker and not match.group(2):
            if current is not None:
                blocks.append(current)
            current, open_marker = None, None
            continue
        if current is not None:
            current.append(line)
    if current is not None:  # 닫히지 않은 펜스 — 삼키지 않고 계상한다
        blocks.append(current)
    return blocks


def _transition_lines(bare_lines: list[str]) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for i, bare in enumerate(bare_lines):
        for label, pattern in _TRANSITIONS:
            if pattern.search(bare):
                hits.append((i, label))
                break
    return hits


def _tainted_variables(lines: list[str], bare_lines: list[str], start: int) -> set[str]:
    """`start` 이후 **동일성 되읽기**에서 파생된 변수 집합(대입 전파 고정점).

    `$LASTEXITCODE`는 바로 앞 명령이 되읽기(`git diff --quiet` 등)일 때만 오염으로 본다 —
    그렇지 않으면 아무 명령의 종료 코드나 판정 근거로 통과한다.
    """
    tainted: set[str] = set()
    changed = True
    while changed:
        changed = False
        previous_readback = False
        for i in range(start, len(lines)):
            bare = bare_lines[i]
            if not bare.strip():
                continue
            match = _ASSIGN.match(bare)
            rhs_raw = _ASSIGN.match(lines[i])
            rhs_full = rhs_raw.group(2) if rhs_raw else lines[i]
            if match:
                name = match.group(1).lower()
                rhs_vars = {v.lower() for v in _VAR.findall(match.group(2))}
                derived = bool(_READBACK.search(rhs_full)) or bool(rhs_vars & tainted)
                if "$lastexitcode" in rhs_vars and previous_readback:
                    derived = True
                if derived and name not in tainted:
                    tainted.add(name)
                    changed = True
            previous_readback = bool(_READBACK.search(lines[i])) and not match
    return tainted


def _is_action(line: str, bare: str) -> bool:
    """전환 뒤 이 줄이 **동작**인가 — 빈 줄·주석·출력·순수 대입·되읽기는 동작이 아니다."""
    stripped = bare.strip()
    if not stripped or re.fullmatch(r"[{}\s]*(?:else(?:if)?\b[\s{}]*)?", stripped, re.IGNORECASE):
        return False  # 중괄호·else 뼈대만 남은 줄(문자열은 이미 비워졌다)
    if _OUTPUT_ONLY.match(stripped):
        return False
    if _READ_ONLY_GIT.match(stripped):
        return False
    if _EXISTENCE_ONLY.search(bare) and not re.search(r"&|\bpython\b", bare, re.IGNORECASE):
        return False  # 존재 검사는 조회다 — 판정력이 없을 뿐 상태를 바꾸지 않는다(③ 축이 따로 본다)
    if _READBACK.search(line) and not re.search(r"&\s*\$|\bpython\b", bare, re.IGNORECASE):
        return False  # 되읽기 자체(`git rev-parse HEAD`·`git diff --quiet …`)
    match = _ASSIGN.match(bare)
    if match:
        rhs = match.group(2)
        if "&" in rhs or re.search(r"\b[A-Za-z][\w.-]*-[A-Za-z]\w*\b|\bpython\b", rhs):
            return not _READBACK.search(line)  # 명령 실행을 담은 대입 = 동작
        return False
    # 문자열 리터럴만 있는 줄(`"HEAD=$Head"`)은 출력이다 — bare에서 문자열이 비워진다.
    return bool(re.search(r"[A-Za-z&.]", stripped.replace("$", "")))


def audit_chat_block(scanner: ModuleType, index: int, lines: list[str]) -> list[Finding]:
    """PowerShell 채팅 블록 1개 판정."""
    bare_lines = [scanner.strip_strings_and_comments(line) for line in lines]
    transitions = _transition_lines(bare_lines)
    if not transitions:
        return []
    last, label = transitions[-1]
    after = [i for i in range(last + 1, len(lines)) if _is_action(lines[i], bare_lines[i])]
    if not after:
        return []  # 전환 뒤에 아무 동작도 없다 — 실패해도 잘못 도는 것이 없다

    block = scanner.Block(path=pathlib.Path("<chat>"), index=index, start_line=0, lines=lines)
    regions = scanner.guarded_regions(block)

    # 줄 단위 판정 — true 가지가 걸친 줄이면 가드 안이다(한 줄 가드 포함).
    findings: list[Finding] = []
    if scanner.has_dangling_else(block):
        findings.append(
            Finding(
                index,
                "파서",
                "닫힌 `if` 다음 새 줄의 `else` — 대화형 붙여넣기에서 별개 명령으로 해석돼 거부 "
                "가지가 통째로 미실행된다. 같은 줄의 `} else {`로 붙여라.",
            )
        )
    unguarded = [row for row in after if not any(sr <= row <= er for sr, _c, er, _e in regions)]
    if unguarded:
        findings.append(
            Finding(
                index,
                "가드",
                f"`{label}` 뒤 {unguarded[0] + 1}행이 자가거부 가드 밖에 있다 — 전환이 실패해도 "
                "그대로 실행된다. 전환 직후 실제 상태를 되읽어 변수에 받고, 뒤 단계를 "
                '`if ($Head -eq $Expected) { … } else { "REFUSED — HEAD=$Head" }`(같은 줄 '
                "`} else {`)로 감싸라.",
            )
        )
        return findings

    tainted = _tainted_variables(lines, bare_lines, last + 1)
    conditions = [
        scanner._condition_text(bare)
        for bare in bare_lines[last + 1 :]
        if scanner._IF_OPEN.match(bare)
    ]
    cond_vars = {v.lower() for c in conditions for v in _VAR.findall(c)}
    if not cond_vars & tainted:
        existence = any(_EXISTENCE_ONLY.search(line) for line in lines[last + 1 :])
        findings.append(
            Finding(
                index,
                "변별력",
                "가드 조건이 전환 뒤 **동일성 되읽기**(`git rev-parse`·`branch --show-current`·"
                "`git diff --quiet`·`sys.executable`)에서 파생된 변수를 참조하지 않는다 — "
                + (
                    "`Test-Path` 같은 존재 검사는 잘못된 트리에서도 True를 낸다(판정력 0)."
                    if existence
                    else "선행 판정을 재검사하지 않는 위장 가드다."
                ),
            )
        )
        return findings

    compared = any(_COMPARISON.search(c) for c in conditions) or any(
        _COMPARISON.search(bare_lines[i])
        for i in range(last + 1, len(lines))
        if (m := _ASSIGN.match(bare_lines[i])) and m.group(1).lower() in tainted
    )
    if not compared:
        findings.append(
            Finding(
                index,
                "변별력",
                "되읽기 값을 기대값과 **비교**하지 않는다(`-eq` 등) — `git rev-parse`는 실패 시 "
                "입력 문자열을 그대로 돌려주므로 truthy 검사는 성공·실패를 가르지 못한다.",
            )
        )
        return findings

    printed = any(
        _READBACK.search(lines[i]) and not _ASSIGN.match(bare_lines[i])
        for i in range(last + 1, len(lines))
    ) or any(
        tainted & {v.lower() for v in _VAR.findall(literal)}
        for line in lines[last + 1 :]
        for literal in re.findall(r"\"([^\"]*)\"", line)
    )
    if not printed:
        findings.append(
            Finding(
                index,
                "되읽기 출력",
                "되읽은 실제 상태를 화면에 출력하지 않는다 — 거부됐을 때 사람이 무엇이 "
                '달랐는지 알 수 없다(`"HEAD=$Head"`처럼 값을 끼워 출력하라).',
            )
        )
    if not scanner.has_speaking_else(block):
        findings.append(
            Finding(
                index,
                "가드",
                "가드에 말하는 `else` 가지가 없다 — 침묵하며 건너뛴 블록은 사람이 통과로 "
                "읽는다. 무엇이 기대와 달랐는지 출력하라.",
            )
        )
    return findings


def audit_reply(scanner: ModuleType, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for index, lines in enumerate(powershell_blocks(text), start=1):
        findings.extend(audit_chat_block(scanner, index, lines))
    return findings


def _log(payload: dict[str, Any]) -> None:
    log_dir = os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", "."), ".claude", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(
            os.path.join(log_dir, "chat_block_violations.jsonl"), "a", encoding="utf-8"
        ) as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError as exc:  # 로그 실패가 작업을 막지 않는다(타입명은 남긴다)
        print(f"[chat_block_guard] 로그 기록 실패({type(exc).__name__})", file=sys.stderr)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[chat_block_guard] 입력 파싱 실패({type(exc).__name__}) — 통과", file=sys.stderr)
        return 0

    try:
        scanner = _load("check_runbook_blocks", _RUNBOOK_SCANNER)
        fence = _load("fence_guard", _FENCE_GUARD)
    except Exception as exc:  # noqa: BLE001 — 의존 모듈 부재는 관측 실패다(타입명 기록)
        _log({"time": _now(), "skipped": f"import_error:{type(exc).__name__}"})
        return 0

    path = data.get("transcript_path")
    if not path:
        _log({"time": _now(), "skipped": "no_transcript_path"})
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
                    continue
    except OSError as exc:
        _log({"time": _now(), "skipped": f"read_error:{type(exc).__name__}"})
        return 0
    if not entries:
        _log({"time": _now(), "skipped": "empty_transcript"})
        return 0

    reply, prompt = fence.last_turn_reply(entries)
    findings = audit_reply(scanner, reply)
    if not findings:
        return 0

    escaped = any(marker in prompt for marker in ESCAPE_MARKERS)
    already_retried = bool(data.get("stop_hook_active"))
    _log(
        {
            "time": _now(),
            "session": data.get("session_id"),
            "axes": [f.axis for f in findings],
            "count": len(findings),
            "retry": already_retried,
            "escaped": escaped,
        }
    )
    if escaped or already_retried:
        return 0

    lines = [f"[chat_block_guard] 상태 전환 블록 위반 {len(findings)}건 — 다시 써라:"]
    lines += [f"  · 블록 #{f.block_index} [{f.axis}] {f.detail}" for f in findings]
    print("\n".join(lines), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
