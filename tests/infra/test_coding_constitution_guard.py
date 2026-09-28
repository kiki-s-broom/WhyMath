"""CONST-02 — 코딩 헌법 보호 가드(R0-01)의 배선과 변별력 동결.

왜 이 테스트가 있는가
--------------------
코딩 헌법 제9조 ①은 "AI는 constitution/ 폴더를 수정·삭제·이동할 수 없다"이고 목표 강도는
L5(자동 차단)다. 집행 장치는 `.claude/hooks/guard_constitution.py`(PreToolUse)와 settings.json의
`permissions.deny`다. 이 저장소는 "파일은 있는데 배선이 안 된" 보호 장치를 여러 번 겪었고
(OPS-03·OPS-08·OPS-11), 가드가 막는다고 주장하는 것도 주입으로 확인해야 한다(보호 장치를 실패
주입 없이 "보호 있음"으로 선언 금지). 그래서 배선과 양방향 변별력을 함께 동결한다.

검증 계약
--------
① settings.json 에 가드가 PreToolUse 로 배선돼 있고(Edit·Write·MultiEdit·Bash 매처) deny 3건이 있다
② 픽스처 전건(차단 기대·통과 기대 양방향)이 기대 종료 코드와 일치한다 — 픽스처 정본은
   scripts/constitution/selftest_guard.py (R0-01 의 run 명령과 같은 데이터)
③ selftest_guard.py 자체가 exit 0
④ 변별력 봉인 — 가드 사본의 보호 폴더 이름을 바꾸면 차단 픽스처가 통과로 바뀐다(가드가 실제로
   그 이름에 반응한다는 증거). 주입 적용은 mutated != original 로 단언한다
⑤ 파싱 실패는 '변경 없음'으로 접지 않는다 — 헌법 경로+변경 동사가 보이면 막고, 아니면 통과
⑥ 차단은 로그에 남는다(남지 않는 차단은 사후 추적이 안 된다)

의도적으로 검증하지 않는 것
-------------------------
- Claude Code 런타임이 훅을 실제로 호출하는지(런타임 밖 — 배선 문자열까지만 본다).
- 변수·eval·스크립트 파일 안의 쓰기(가드 docstring 「한계」에 명시). 두 번째 층은 커밋 시점 검사
  R0-02(CONST-03)다.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUARD = _REPO_ROOT / ".claude" / "hooks" / "guard_constitution.py"
_SELFTEST = _REPO_ROOT / "scripts" / "constitution" / "selftest_guard.py"
_SETTINGS = _REPO_ROOT / ".claude" / "settings.json"


def _load_selftest():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("selftest_guard", _SELFTEST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_FIXTURES = _load_selftest().FIXTURES


def _run_guard(
    guard: Path, payload: dict, project_dir: Path, log_dir: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """가드를 훅처럼 실행한다. log_dir 을 안 주면 임시 폴더로 보내 실제 로그를 오염시키지 않는다."""
    if log_dir is None:
        log_dir = Path(tempfile.mkdtemp(prefix="guard_test_"))
    return subprocess.run(
        [sys.executable, str(guard)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env={
            "CLAUDE_PROJECT_DIR": str(project_dir),
            "CLAUDE_GUARD_LOG_DIR": str(log_dir),
            "PATH": "",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )


# ── ① 배선 ─────────────────────────────────────────────────────────────────


def _settings() -> dict:
    data = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    assert isinstance(data.get("hooks", {}).get("PreToolUse"), list), "PreToolUse 훅 목록 없음"
    return data


def test_guard_is_wired_as_pretooluse_hook() -> None:
    entries = [
        e
        for e in _settings()["hooks"]["PreToolUse"]
        if any("guard_constitution.py" in h.get("command", "") for h in e.get("hooks", []))
    ]
    assert (
        len(entries) == 1
    ), "guard_constitution.py 를 부르는 PreToolUse 항목이 정확히 1개여야 한다"
    matcher = set(entries[0]["matcher"].split("|"))
    assert {"Edit", "Write", "MultiEdit", "Bash"} <= matcher, f"매처 부족: {matcher}"


def test_permission_deny_covers_edit_tools() -> None:
    deny = set(_settings()["permissions"]["deny"])
    for rule in (
        "Edit(/constitution/**)",
        "Write(/constitution/**)",
        "MultiEdit(/constitution/**)",
    ):
        assert rule in deny, f"deny 누락: {rule}"


def test_constitution_deny_rules_are_anchored() -> None:
    """거부 규칙의 한 단계짜리 폴더 패턴은 '어느 깊이에서든' 일치한다(Claude Code 권한 문서).

    2026-09-28 이식 세션에서 `Edit(constitution/**)` 가 `scripts/constitution/` 쓰기(mkdir·cp)까지
    막았다 — 저장소 자신의 위헌 심사 도구 폴더다. `/`로 시작해야 저장소 최상위에만 고정된다.
    """
    deny = _settings()["permissions"]["deny"]
    loose = [r for r in deny if "constitution" in r and "(/constitution/" not in r]
    assert not loose, f"고정되지 않은 거부 규칙(하위 폴더까지 막는다): {loose}"


# ── ② 픽스처 양방향 ────────────────────────────────────────────────────────


def test_fixture_set_is_two_sided() -> None:
    expected = {f[3] for f in _FIXTURES}
    assert expected == {0, 2}, "차단·통과 기대가 둘 다 있어야 변별력이 성립한다"
    assert sum(1 for f in _FIXTURES if f[3] == 0) >= 8, "통과(대조군) 픽스처가 너무 적다"


@pytest.mark.parametrize(("desc", "tool", "tool_input", "expected"), _FIXTURES)
def test_guard_fixture(desc: str, tool: str, tool_input: dict, expected: int) -> None:
    filled = {k: v.replace("{root}", str(_REPO_ROOT)) for k, v in tool_input.items()}
    proc = _run_guard(
        _GUARD, {"tool_name": tool, "tool_input": filled, "cwd": str(_REPO_ROOT)}, _REPO_ROOT
    )
    assert proc.returncode == expected, f"{desc}: {proc.stderr}"
    if expected == 2:
        assert "제9조" in proc.stderr and "사람에게 보고" in proc.stderr


# ── ③ 자가시험 ─────────────────────────────────────────────────────────────


def test_selftest_passes() -> None:
    proc = subprocess.run(
        [sys.executable, str(_SELFTEST)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": ""},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_selftest_does_not_pollute_real_log() -> None:
    """자가시험의 차단 기록은 임시 폴더로 간다 — 실제 로그에는 세션의 진짜 차단만 남아야 한다."""
    real_log = _REPO_ROOT / ".claude" / "logs" / "constitution_guard.jsonl"
    before = real_log.read_bytes() if real_log.exists() else b""
    subprocess.run(
        [sys.executable, str(_SELFTEST)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": ""},
    )
    after = real_log.read_bytes() if real_log.exists() else b""
    assert after == before, "자가시험이 실제 차단 로그에 기록을 남겼다"


# ── ④ 변별력 봉인 ──────────────────────────────────────────────────────────


def test_guard_mutation_is_caught(tmp_path: Path) -> None:
    """보호 폴더 이름을 바꾼 가드 사본은 헌법 편집을 통과시킨다 — 가드가 실제로 반응한다는 증거."""
    mutant = tmp_path / "guard_mutant.py"
    original = _GUARD.read_text(encoding="utf-8")
    mutated = original.replace('PROTECTED_DIRNAME = "constitution"', 'PROTECTED_DIRNAME = "zzz"')
    assert mutated != original, "주입이 적용되지 않았다"
    mutant.write_text(mutated, encoding="utf-8")
    payload = {
        "tool_name": "Edit",
        "tool_input": {"file_path": "constitution/rules.yaml"},
        "cwd": str(_REPO_ROOT),
    }
    assert _run_guard(_GUARD, payload, _REPO_ROOT).returncode == 2
    assert _run_guard(mutant, payload, _REPO_ROOT).returncode == 0


# ── ⑤ 파싱 실패 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("rm -f constitution/STAGE 'unclosed", 2),  # 파싱 실패 + 헌법 경로 + 변경 동사 → 차단
        ("cat constitution/STAGE 'unclosed", 0),  # 파싱 실패지만 변경 동사 없음 → 통과
        ("rm -f /tmp/x 'unclosed", 0),  # 파싱 실패지만 헌법 경로 없음 → 통과
    ],
)
def test_parse_failure_is_not_read_as_safe(command: str, expected: int) -> None:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(_REPO_ROOT)}
    assert _run_guard(_GUARD, payload, _REPO_ROOT).returncode == expected


def test_malformed_stdin_passes_with_notice() -> None:
    proc = subprocess.run(
        [sys.executable, str(_GUARD)],
        input="{not json",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env={"PATH": "", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert proc.returncode == 0 and "입력 파싱 실패" in proc.stderr


# ── ⑥ 로그 ─────────────────────────────────────────────────────────────────


def test_block_is_logged(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    (project / ".git").mkdir(parents=True)
    (project / "constitution").mkdir()
    guard = project / ".claude" / "hooks" / "guard_constitution.py"
    guard.parent.mkdir(parents=True)
    shutil.copy2(_GUARD, guard)
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "constitution/STAGE"},
        "cwd": str(project),
        "session_id": "s-test",
    }
    log_dir = project / ".claude" / "logs"
    assert _run_guard(guard, payload, project, log_dir).returncode == 2
    log = log_dir / "constitution_guard.jsonl"
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1 and records[0]["tool"] == "Write"
