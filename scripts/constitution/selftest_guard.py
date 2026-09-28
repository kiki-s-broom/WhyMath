#!/usr/bin/env python3
"""헌법 보호 가드 자가시험 — 코딩 헌법 규칙 R0-01 의 run 명령 (CONST-02).

.claude/hooks/guard_constitution.py 를 실제 훅과 같은 방식(stdin JSON → 종료 코드)으로
픽스처마다 실행해 기대값과 대조한다. **양방향**을 잰다 — 막아야 할 것을 막는가(차단 2)와
막으면 안 되는 것을 통과시키는가(통과 0). 한쪽만 재면 전건 차단·전건 통과 구현이 초록이 된다.

종료 코드: 0 = 전건 일치 / 1 = 불일치 있음(목록 출력) / 2 = 가드 파일 없음(측정 실패)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / ".claude" / "hooks" / "guard_constitution.py"

BLOCK, ALLOW = 2, 0

#: 자가시험의 차단 기록은 실제 로그(.claude/logs)가 아니라 임시 폴더로 보낸다
LOG_DIR = tempfile.mkdtemp(prefix="guard_selftest_")

#: (설명, tool_name, tool_input, 기대 종료 코드) — 변별력을 위해 차단·통과를 함께 둔다
FIXTURES: list[tuple[str, str, dict[str, str], int]] = [
    ("Edit 규칙 등록부", "Edit", {"file_path": "constitution/rules.yaml"}, BLOCK),
    ("Write 새 개정 기록", "Write", {"file_path": "constitution/amendments/A0009.md"}, BLOCK),
    ("MultiEdit 헌법 본문", "MultiEdit", {"file_path": "constitution/CONSTITUTION.md"}, BLOCK),
    ("Edit 절대경로", "Edit", {"file_path": "{root}/constitution/STAGE"}, BLOCK),
    ("Edit 대소문자 변형", "Edit", {"file_path": "Constitution/STAGE"}, BLOCK),
    ("Edit 일반 문서(대조군)", "Edit", {"file_path": "docs/standards/x.md"}, ALLOW),
    (
        "Edit 이름만 같은 폴더(대조군)",
        "Edit",
        {"file_path": "scripts/constitution/audit.py"},
        ALLOW,
    ),
    ("Edit 제안 폴더(대조군)", "Write", {"file_path": "docs/constitution_proposals/A.md"}, ALLOW),
    ("rm -rf", "Bash", {"command": "rm -rf constitution"}, BLOCK),
    ("sed -i", "Bash", {"command": "sed -i s/a/b/ constitution/rules.yaml"}, BLOCK),
    ("리다이렉트", "Bash", {"command": "echo 3 > constitution/STAGE"}, BLOCK),
    ("붙은 리다이렉트", "Bash", {"command": "echo 3 >>constitution/STAGE"}, BLOCK),
    ("git mv", "Bash", {"command": "git mv constitution old_constitution"}, BLOCK),
    (
        "git checkout --",
        "Bash",
        {"command": "git checkout HEAD~1 -- constitution/rules.yaml"},
        BLOCK,
    ),
    ("cd 후 rm", "Bash", {"command": "cd constitution && rm rules.yaml"}, BLOCK),
    ("cp 대상", "Bash", {"command": "cp /tmp/x.yaml constitution/rules.yaml"}, BLOCK),
    ("mv 밖으로", "Bash", {"command": "mv constitution/STAGE /tmp/STAGE"}, BLOCK),
    ("tee", "Bash", {"command": "echo x | tee -a constitution/CONSTITUTION.md"}, BLOCK),
    ("find -delete", "Bash", {"command": "find constitution -name '*.md' -delete"}, BLOCK),
    ("xargs rm", "Bash", {"command": "ls constitution/amendments/* | xargs rm -f"}, BLOCK),
    ("bash -c 안쪽", "Bash", {"command": "bash -c 'rm -f constitution/STAGE'"}, BLOCK),
    (
        "python -c 쓰기",
        "Bash",
        {"command": "python3 -c \"open('constitution/STAGE','w').write('3')\""},
        BLOCK,
    ),
    (
        "python heredoc 쓰기",
        "Bash",
        {
            "command": (
                "python3 - <<'EOF'\nimport pathlib\n"
                "pathlib.Path('constitution/STAGE').write_text('3')\nEOF"
            )
        },
        BLOCK,
    ),
    (
        "출력 옵션",
        "Bash",
        {"command": "python3 scripts/constitution/audit.py --report constitution/a.md"},
        BLOCK,
    ),
    ("sudo 접두", "Bash", {"command": "sudo rm constitution/STAGE"}, BLOCK),
    ("../ 경로", "Bash", {"command": "cd docs && rm ../constitution/STAGE"}, BLOCK),
    ("읽기 cat(대조군)", "Bash", {"command": "cat constitution/rules.yaml"}, ALLOW),
    ("읽기 grep(대조군)", "Bash", {"command": "grep -rn 제9조 constitution/"}, ALLOW),
    (
        "심사 실행(대조군)",
        "Bash",
        {"command": "python3 scripts/constitution/audit.py --no-run"},
        ALLOW,
    ),
    ("복사해 나가기(대조군)", "Bash", {"command": "cp -r constitution /tmp/const_copy"}, ALLOW),
    ("git add(대조군)", "Bash", {"command": "git add constitution/ && git status --short"}, ALLOW),
    ("sha256(대조군)", "Bash", {"command": "sha256sum constitution/*.md"}, ALLOW),
    (
        "다른 폴더 rm(대조군)",
        "Bash",
        {"command": "rm -rf /tmp/x scripts/constitution/__pycache__"},
        ALLOW,
    ),
    (
        "문서 heredoc 본문(대조군)",
        "Bash",
        {"command": "cat > docs/x.md <<'EOF'\n예: rm -rf constitution 은 막힌다\nEOF"},
        ALLOW,
    ),
    ("git diff(대조군)", "Bash", {"command": "git diff --stat -- constitution/"}, ALLOW),
    # ── 인라인 코드 AST 판정 (2026-09-28 오탐 교정 회귀 봉인) ──
    (
        "설정 수정 heredoc — 헌법 언급·다른 파일 쓰기(대조군 · 실제 오탐 재현)",
        "Bash",
        {
            "command": (
                "python3 - <<'EOF'\nimport json, pathlib\n"
                "p = pathlib.Path('.claude/settings.json')\nd = json.loads(p.read_text())\n"
                "d['deny'] = [r.replace('(constitution/**)', '(/constitution/**)')"
                " for r in d['deny']]\n"
                "assert 'constitution' in str(d)\np.write_text(json.dumps(d))\nEOF"
            )
        },
        ALLOW,
    ),
    (
        "헌법 읽기 전용 파이썬(대조군)",
        "Bash",
        {"command": "python3 -c \"print('제9조' in open('constitution/CONSTITUTION.md').read())\""},
        ALLOW,
    ),
    (
        "헌법에서 복사해 나가기 파이썬(대조군)",
        "Bash",
        {
            "command": 'python3 -c "import shutil; '
            "shutil.copy('constitution/rules.yaml', '/tmp/r')\""
        },
        ALLOW,
    ),
    (
        "변수 경유 쓰기",
        "Bash",
        {
            "command": (
                "python3 - <<'EOF'\nfrom pathlib import Path\nROOT = Path('.')\n"
                "target = ROOT / 'constitution' / 'STAGE'\ntarget.write_text('3')\nEOF"
            )
        },
        BLOCK,
    ),
    (
        "os.remove",
        "Bash",
        {"command": "python3 -c \"import os; os.remove('constitution/STAGE')\""},
        BLOCK,
    ),
    (
        "shutil.copy 대상",
        "Bash",
        {
            "command": 'python3 -c "import shutil; '
            "shutil.copy('/tmp/r', 'constitution/rules.yaml')\""
        },
        BLOCK,
    ),
    (
        "subprocess 목록 명령",
        "Bash",
        {
            "command": 'python3 -c "import subprocess; '
            "subprocess.run(['rm', 'constitution/STAGE'])\""
        },
        BLOCK,
    ),
    (
        "node 쓰기",
        "Bash",
        {"command": "node -e \"require('fs').writeFileSync('constitution/STAGE', '3')\""},
        BLOCK,
    ),
    (
        "node 읽기(대조군)",
        "Bash",
        {
            "command": "node -e \"console.log(require('fs')"
            ".readFileSync('constitution/STAGE', 'utf8'))\""
        },
        ALLOW,
    ),
]


def run_fixture(tool: str, tool_input: dict[str, str]) -> int:
    """가드를 훅처럼 실행해 종료 코드를 돌려준다."""
    filled = {k: v.replace("{root}", str(ROOT)) for k, v in tool_input.items()}
    payload = json.dumps({"tool_name": tool, "tool_input": filled, "cwd": str(ROOT)})
    proc = subprocess.run(
        [sys.executable, str(GUARD)],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        # 환경은 상속한다 — Windows 는 SYSTEMROOT 가 없으면 파이썬이 시작조차 못 한다(초판은 PATH 만
        # 남겨 비웠는데, 그러면 Kiki 머신의 위헌 심사 R0-01 이 전건 불일치로 red 가 된다).
        env={
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(ROOT),
            "CLAUDE_GUARD_LOG_DIR": LOG_DIR,
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        timeout=30,
    )
    return proc.returncode


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    if not GUARD.is_file():
        print(f"⛔ 가드 파일 없음(측정 실패): {GUARD}", file=sys.stderr)
        return 2
    mismatches = []
    for desc, tool, tool_input, expected in FIXTURES:
        got = run_fixture(tool, tool_input)
        if got != expected:
            mismatches.append(f"{desc}: 기대 {expected} · 실제 {got} · {tool} {tool_input}")
    blocks = sum(1 for f in FIXTURES if f[3] == BLOCK)
    print(
        f"가드 자가시험: 픽스처 {len(FIXTURES)}건"
        f"(차단 기대 {blocks} · 통과 기대 {len(FIXTURES) - blocks})"
    )
    for m in mismatches:
        print(f"  ✗ {m}")
    if mismatches:
        print(f"⛔ 불일치 {len(mismatches)}건")
        return 1
    print("✅ 전건 일치")
    return 0


if __name__ == "__main__":
    sys.exit(main())
