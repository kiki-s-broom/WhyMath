"""HARN-163 — 채팅 실행 블록 상태 전환 자가거부 가드의 사각·변별력 동결.

**왜 이 가드가 있는가**: 같은 형태의 사고가 두 번 났다(같은 브랜치·같은 커밋 `0367fce4`).
2026-09-15 `G-skb03`은 런북 블록이었고 대책 HARN-106이 착지했다. 2026-09-23 `G-kg02`는
**채팅** 블록이었다 — `git checkout main`·`git pull`이 둘 다 실패했는데 뒤 명령이 그대로
돌았고, 블록 안의 확인 3줄(`Test-Path`)은 전부 True였다(그 파일들은 두 트리 모두에 있었다).

**이 파일이 지키는 것**:
  ① 사각의 실재 — 사고 블록을 HARN-106 스캐너·HARN-114 펜스 가드·이 가드에 **똑같이**
     넣어, 앞의 둘은 통과시키고 이 가드만 잡는다는 것을 고정한다.
  ② 계약 — 전환 뒤 동작은 동일성 되읽기 + 비교 조건 + 같은 줄 else 가드 안에서만.
  ③ 존재 검사 금지 — `Test-Path`로 만든 조건은 가드로 인정하지 않는다.
  ⑤ 변별력 — 위반 3종(가드 없음·침묵 else·위장 조건) 전건 RED, 정상 블록 GREEN,
     transcript·의존 모듈을 못 읽으면 막지 않고 통과(사유는 로그).

hermetic: 순수 함수 + 임시 파일만 — 네트워크·DB 0.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUARD = _REPO_ROOT / ".claude" / "hooks" / "chat_block_guard.py"
_FENCE_GUARD = _REPO_ROOT / ".claude" / "hooks" / "fence_guard.py"
_SCANNER = _REPO_ROOT / "scripts" / "ops" / "check_runbook_blocks.py"
_SETTINGS = _REPO_ROOT / ".claude" / "settings.json"

F = "```"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


scanner = _load("check_runbook_blocks", _SCANNER)
fence = _load("fence_guard_for_163", _FENCE_GUARD)
guard = _load("chat_block_guard", _GUARD)


def _ps(body: str) -> str:
    return f"다음을 실행하세요.\n{F}powershell\n{body.strip()}\n{F}\n끝."


def _findings(text: str) -> list[tuple[str, str]]:
    return [(f.axis, f.detail) for f in guard.audit_reply(scanner, text)]


# 2026-09-23 G-kg02 사고 블록의 형태 재구성(원문 명령 순서: 체크아웃 → pull → 존재 확인 3줄 →
# dry-run → 실 회차). 경로·모듈명은 형태 보존을 위한 재구성이다.
INCIDENT = _ps(r"""
# Windows PowerShell (Phaiakes9)
cd C:\Users\kiki\Desktop\__AI\WhyMath
git checkout main
git pull origin main
Test-Path .\scripts\kg\kg02_batch.py
Test-Path .\data\kg\corpus.jsonl
Test-Path .\scripts\kg\kg02_report.py
& .\.venv\Scripts\python.exe -m scripts.kg.kg02_batch --dry-run
& .\.venv\Scripts\python.exe -m scripts.kg.kg02_batch --live
""")

GOOD_REV_PARSE = _ps(r"""
# Windows PowerShell (Phaiakes9)
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
git checkout main
$Head = git rev-parse HEAD
$Expected = git rev-parse origin/main
"HEAD=$Head EXPECTED=$Expected"
if ($Head -eq $Expected) { & .\.venv\Scripts\python.exe -m scripts.kg.kg02_batch --dry-run } else { "REFUSED=True — HEAD=$Head EXPECTED=$Expected" }
""")

GOOD_DIFF_QUIET = _ps(r"""
cd C:\Users\kiki\Desktop\__AI\WhyMath
git pull origin main
git diff --quiet origin/main -- scripts/kg data/kg
$Same = ($LASTEXITCODE -eq 0)
"SAME_AS_MAIN=$Same"
if ($Same) {
  & .\.venv\Scripts\python.exe -m scripts.kg.kg02_batch --live
} else { "REFUSED=True — 실행 입력이 main과 다르다(SAME_AS_MAIN=$Same)" }
""")

GOOD_ENV = _ps(r"""
cd C:\Users\kiki\Desktop\__AI\WhyMath
.\.venv\Scripts\Activate.ps1
$Exe = python -c "import sys; print(sys.executable)"
"PYTHON=$Exe"
if ($Exe -like "*WhyMath\.venv*") { python -m scripts.kg.kg02_batch --dry-run } else { "REFUSED=True — PYTHON=$Exe" }
""")


# ===========================================================================
# ① 사각 — 같은 블록을 세 장치에 넣는다
# ===========================================================================


def test_blind_spot_runbook_scanner_scope_is_repository_files_only() -> None:
    """HARN-106 스캐너의 스캔 대상은 저장소 런북 파일이다 — 채팅은 입력 경로 자체가 없다."""
    assert scanner.DEFAULT_GLOB == "docs/ops/*runbook*.md"


def test_blind_spot_runbook_scanner_passes_the_incident_block() -> None:
    """HARN-106의 판정 축(쓰기)으로도 사고 블록은 통과한다 — 전환 명령은 쓰기 어휘가 아니다.

    이 단언이 깨지면(스캐너가 전환 축을 얻으면) 이 가드와 중복이므로 통합을 재판정할 것.
    """
    lines = guard.powershell_blocks(INCIDENT)[0]
    block = scanner.Block(path=Path("<chat>"), index=1, start_line=0, lines=lines)
    assert scanner.audit_block(block) == []


def test_blind_spot_fence_guard_passes_the_incident_block() -> None:
    """HARN-114는 태그만 본다 — `powershell` 태그면 내용과 무관하게 통과한다."""
    assert fence.violating_tags(INCIDENT) == []


def test_this_guard_catches_the_incident_block() -> None:
    found = _findings(INCIDENT)
    assert [axis for axis, _ in found] == ["가드"]
    assert "git pull" in found[0][1]


# ===========================================================================
# ② 정상 형태 — GREEN (대조군이 없으면 "전건 차단"이라는 과잉 수정이 통과한다)
# ===========================================================================


@pytest.mark.parametrize(
    "text",
    [GOOD_REV_PARSE, GOOD_DIFF_QUIET, GOOD_ENV],
    ids=["rev-parse-동일성", "diff-quiet-동등성", "환경-sys.executable"],
)
def test_guarded_transition_blocks_pass(text: str) -> None:
    assert _findings(text) == []


def test_block_without_transition_is_out_of_scope() -> None:
    """전환이 없는 블록은 이 가드의 대상이 아니다(쓰기 축은 HARN-106 소관)."""
    assert _findings(_ps("cd C:\\x\n& .\\.venv\\Scripts\\python.exe -m a.b --live")) == []


def test_transition_as_last_action_is_allowed() -> None:
    """전환 뒤에 동작이 없으면 실패해도 잘못 도는 것이 없다."""
    assert _findings(_ps("cd C:\\x\ngit fetch origin main\ngit checkout main")) == []


def test_readback_after_transition_is_not_an_action() -> None:
    """전환 뒤 되읽기·출력만 있으면 통과 — 되읽기 자체를 가드로 감쌀 필요는 없다."""
    text = _ps('git checkout main\ngit rev-parse HEAD\n$B = git branch --show-current\n"B=$B"')
    assert _findings(text) == []


def test_read_only_git_after_transition_is_not_an_action() -> None:
    """대조군 — 전환 뒤 `git status`·`git log`는 조회다. 이것까지 막으면 사람이 가드를 끈다."""
    text = _ps("git checkout main\ngit status --short\ngit log -1 --oneline\ngit fetch origin")
    assert _findings(text) == []


def test_non_powershell_fences_are_ignored_and_do_not_desync_parsing() -> None:
    """다른 언어 펜스의 닫는 줄을 새 여는 줄로 오인하지 않는다."""
    text = f"{F}bash\ngit checkout main\npython x.py\n{F}\n산문\n{GOOD_REV_PARSE}"
    assert _findings(text) == []
    assert len(guard.powershell_blocks(text)) == 1


# ===========================================================================
# ⑤ 변별력 — 위반 3종 + ③ 존재 검사 + 보조 축
# ===========================================================================


def test_red_no_guard() -> None:
    """① 가드 없는 블록."""
    text = _ps("git checkout main\n& .\\.venv\\Scripts\\python.exe -m a.b --live")
    assert [a for a, _ in _findings(text)] == ["가드"]


def test_red_silent_else() -> None:
    """② 가드는 있으나 실패 가지가 침묵한다 — 사람은 침묵을 통과로 읽는다."""
    text = GOOD_REV_PARSE.replace(' else { "REFUSED=True — HEAD=$Head EXPECTED=$Expected" }', "")
    assert text != GOOD_REV_PARSE, "주입이 적용되지 않았다"
    found = _findings(text)
    assert [a for a, _ in found] == ["가드"] and "else" in found[0][1]


@pytest.mark.parametrize(
    "condition,extra",
    [("$true", ""), ("$Ok", "$Ok = 1\n")],
    ids=["자동상수", "되읽기와-무관한-변수"],
)
def test_red_disguised_guard(condition: str, extra: str) -> None:
    """③ 판정 변수(되읽기 파생)를 참조하지 않는 위장 가드."""
    text = GOOD_REV_PARSE.replace("if ($Head -eq $Expected)", f"if ({condition})").replace(
        "$Expected = git", f"{extra}$Expected = git"
    )
    assert text != GOOD_REV_PARSE
    assert [a for a, _ in _findings(text)] == ["변별력"]


def test_red_existence_check_is_not_a_readback() -> None:
    """acceptance ③ — 사고 블록의 `Test-Path`는 두 트리 모두에서 True였다(판정력 0)."""
    text = GOOD_REV_PARSE.replace("if ($Head -eq $Expected)", "if ($Found)").replace(
        "$Expected = git", "$Found = Test-Path .\\scripts\\kg\\kg02_batch.py\n$Expected = git"
    )
    found = _findings(text)
    assert [a for a, _ in found] == ["변별력"] and "Test-Path" in found[0][1]


def test_red_truthy_readback_is_not_identity() -> None:
    """`git rev-parse`는 실패 시 입력 문자열을 돌려준다 — truthy 검사는 성공·실패를 못 가른다."""
    text = GOOD_REV_PARSE.replace("if ($Head -eq $Expected)", "if ($Head)")
    found = _findings(text)
    assert [a for a, _ in found] == ["변별력"] and "비교" in found[0][1]


def test_red_lastexitcode_without_preceding_readback() -> None:
    """`$LASTEXITCODE`는 바로 앞이 되읽기일 때만 판정 근거다 — 아무 명령의 코드나 통과시키면 위장."""
    text = GOOD_DIFF_QUIET.replace(
        "git diff --quiet origin/main -- scripts/kg data/kg", "git status --short"
    )
    assert text != GOOD_DIFF_QUIET
    assert [a for a, _ in _findings(text)] == ["변별력"]


def test_red_readback_not_printed() -> None:
    """되읽은 값을 출력하지 않으면 거부됐을 때 무엇이 달랐는지 모른다."""
    text = GOOD_REV_PARSE.replace('"HEAD=$Head EXPECTED=$Expected"\n', "").replace(
        '"REFUSED=True — HEAD=$Head EXPECTED=$Expected"', '"REFUSED=True"'
    )
    assert [a for a, _ in _findings(text)] == ["되읽기 출력"]


def test_red_action_between_transition_and_guard() -> None:
    """가드가 있어도 그 **앞**에 끼어든 동작은 보호받지 못한다."""
    text = GOOD_REV_PARSE.replace(
        "$Head = git rev-parse HEAD",
        "& .\\.venv\\Scripts\\python.exe -m scripts.kg.kg02_batch --live\n$Head = git rev-parse HEAD",
    )
    assert [a for a, _ in _findings(text)] == ["가드"]


def test_red_second_transition_resets_the_requirement() -> None:
    """마지막 전환 기준 — 가드 뒤에 또 전환하고 동작하면 다시 가드가 필요하다."""
    text = GOOD_REV_PARSE.replace(
        f"\n{F}\n끝.", f"\ngit checkout other\n& .\\.venv\\Scripts\\python.exe -m a.b\n{F}\n끝."
    )
    assert [a for a, _ in _findings(text)] == ["가드"]


def test_red_dangling_else_on_new_line() -> None:
    """닫힌 `if` 다음 새 줄의 `else`는 대화형 붙여넣기에서 별개 명령이 된다(2026-09-14 실측)."""
    text = _ps(
        "git checkout main\n$Head = git rev-parse HEAD\n$Exp = git rev-parse origin/main\n"
        '"HEAD=$Head"\nif ($Head -eq $Exp) {\n  & .\\.venv\\Scripts\\python.exe -m a.b\n}\n'
        'else { "REFUSED=True HEAD=$Head" }'
    )
    assert "파서" in [a for a, _ in _findings(text)]


# ===========================================================================
# 훅 실행 경로 — exit 코드·로그·fail-open
# ===========================================================================


def _run(
    tmp_path: Path,
    reply: str,
    *,
    prompt: str = "해줘",
    retried: bool = False,
    hook: Path = _GUARD,
    transcript: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    if transcript is None:
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
    payload = {"transcript_path": str(transcript), "session_id": "t", "stop_hook_active": retried}
    return subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"CLAUDE_PROJECT_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
        check=False,
    )


def _log_rows(tmp_path: Path) -> list[dict[str, object]]:
    log = tmp_path / ".claude" / "logs" / "chat_block_violations.jsonl"
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x]


def test_hook_blocks_the_incident(tmp_path: Path) -> None:
    result = _run(tmp_path, INCIDENT)
    assert result.returncode == 2
    assert "chat_block_guard" in result.stderr
    row = _log_rows(tmp_path)[-1]
    assert row["retry"] is False and row["escaped"] is False and row["axes"] == ["가드"]


def test_hook_passes_guarded_block(tmp_path: Path) -> None:
    assert _run(tmp_path, GOOD_REV_PARSE).returncode == 0


def test_hook_does_not_loop_when_already_retried(tmp_path: Path) -> None:
    assert _run(tmp_path, INCIDENT, retried=True).returncode == 0
    assert _log_rows(tmp_path)[-1]["retry"] is True


def test_hook_honours_escape_marker(tmp_path: Path) -> None:
    assert _run(tmp_path, INCIDENT, prompt="그대로 줘 #전환허용").returncode == 0
    assert _log_rows(tmp_path)[-1]["escaped"] is True


def test_hook_log_is_separate_from_fence_guard_measurement(tmp_path: Path) -> None:
    """HARN-114 측정 창(fence_violations.jsonl)을 오염시키지 않는다 — acceptance ④ 판정 근거."""
    _run(tmp_path, INCIDENT)
    assert not (tmp_path / ".claude" / "logs" / "fence_violations.jsonl").exists()


def test_hook_fails_open_when_transcript_is_missing(tmp_path: Path) -> None:
    result = _run(tmp_path, "", transcript=tmp_path / "없음.jsonl")
    assert result.returncode == 0
    assert "read_error" in str(_log_rows(tmp_path)[-1]["skipped"])


def test_hook_fails_open_when_dependencies_are_missing(tmp_path: Path) -> None:
    """의존 모듈(스캐너)을 못 찾는 배치에서도 작업을 막지 않는다 — 사유는 로그에 남는다."""
    isolated = tmp_path / "repo" / ".claude" / "hooks"
    isolated.mkdir(parents=True)
    copy = isolated / "chat_block_guard.py"
    shutil.copy(_GUARD, copy)
    result = _run(tmp_path, INCIDENT, hook=copy)
    assert result.returncode == 0
    assert "import_error" in str(_log_rows(tmp_path)[-1]["skipped"])


def test_hook_is_wired_as_stop_hook() -> None:
    """배선 — 저장소에 있는 것과 도는 것은 다르다."""
    settings = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    commands = [h["command"] for entry in settings["hooks"]["Stop"] for h in entry["hooks"]]
    assert any(".claude/hooks/chat_block_guard.py" in c for c in commands), commands
