"""CONST-12 — 헌법 가드·자가시험·채택 도우미의 cp949↔UTF-8 출력 해독 불일치 동결.

왜 이 테스트가 있는가
--------------------
한국어 Windows 에서 파이프·리다이렉트의 stdout/stderr 는 로캘 인코딩(cp949)을 쓴다. 콘솔은 별도
경로라 멀쩡해 보여서 결함이 가려진다. 2026-10-03 Kiki 머신에서 세 곳이 같은 계열로 드러났다.

  ① 가드(.claude/hooks/guard_constitution.py)의 차단 안내문 stderr 가 cp949 로 나간다
  ② 자가시험(scripts/constitution/selftest_guard.py)이 그것을 UTF-8 로 읽다가 reader 스레드에서
     UnicodeDecodeError — 차단 픽스처 28건마다 찍혔는데 판정(종료 코드만 본다)은 초록이었다
  ③ 채택 도우미(scripts/constitution/adopt_amendment.py)의 run_merge 가 merge_rules.py 출력을
     같은 방식으로 읽다가 첫 미리보기가 죽었다(PR #1447 본문)

재현은 Windows 가 필요 없다 — Linux 에서 PYTHONIOENCODING=cp949 로 출력 인코딩을 강제하면 같은
바이트(위치 7·0xc4)가 나온다. 그래서 이 파일은 CI(Linux)에서 환경변수 하나로 양방향을 잰다:
수정본은 통과하고, **수정 전 동작을 재현한 사본(mutated != original 단언)은 실패한다**.

의도적으로 검증하지 않는 것
-------------------------
- Claude Code 가 훅 stderr 를 실제로 어떻게 해독하는지(런타임 밖 — 미확인).
- 한국어 Windows 콘솔 자체(별도 경로). 파이프 축만 잰다.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUARD = _REPO_ROOT / ".claude" / "hooks" / "guard_constitution.py"
_SELFTEST = _REPO_ROOT / "scripts" / "constitution" / "selftest_guard.py"
_ADOPT = _REPO_ROOT / "scripts" / "constitution" / "adopt_amendment.py"
_MERGE = _REPO_ROOT / "scripts" / "constitution" / "merge_rules.py"

_BLOCK_PAYLOAD = {
    "tool_name": "Edit",
    "tool_input": {"file_path": "constitution/STAGE"},
    "cwd": str(_REPO_ROOT),
}


def _cp949_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """파이프 출력 인코딩을 cp949 로 강제한 환경(한국어 Windows 파이프 모사)."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env["PYTHONIOENCODING"] = "cp949"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["CLAUDE_PROJECT_DIR"] = str(_REPO_ROOT)
    env["CLAUDE_GUARD_LOG_DIR"] = tempfile.mkdtemp(prefix="const12_guardlog_")
    env.update(extra or {})
    return env


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mutated_copy(src: Path, dst: Path, old: str, new: str) -> Path:
    """수정 전 동작을 재현한 사본을 만든다. 주입이 실제로 적용됐는지 단언한다(미적용이면 위장)."""
    original = src.read_text(encoding="utf-8")
    mutated = original.replace(old, new, 1)
    assert mutated != original, f"주입 미적용 — 치환 대상 없음: {old!r}"
    dst.write_text(mutated, encoding="utf-8", newline="\n")
    return dst


def _run_guard(guard: Path, env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(guard)],
        input=json.dumps(_BLOCK_PAYLOAD).encode("utf-8"),
        capture_output=True,
        timeout=30,
        env=env,
    )


# ── ① 가드: 출력 측 ──────────────────────────────────────────────────────────────


def test_guard_block_advice_is_utf8_even_when_pipe_locale_is_cp949() -> None:
    proc = _run_guard(_GUARD, _cp949_env())
    assert proc.returncode == 2  # 차단은 유지된다
    text = proc.stderr.decode("utf-8")  # 엄격 해독 — 수정 전에는 위치 7·0xc4 에서 실패했다
    assert "⛔" in text and "제9조" in text and "차단 사유" in text


def test_guard_legacy_copy_emits_non_utf8_under_cp949(tmp_path: Path) -> None:
    """변별력: 재구성 호출을 뗀 사본은 같은 환경에서 UTF-8 해독에 실패한다(수정 전 재현)."""
    legacy = _mutated_copy(_GUARD, tmp_path / "guard_legacy.py", "    _utf8_stderr()\n", "")
    proc = _run_guard(legacy, _cp949_env())
    assert proc.returncode == 2  # 종료 코드는 같아서 종료 코드만 보는 시험은 이 결함을 못 본다
    with pytest.raises(UnicodeDecodeError) as exc:
        proc.stderr.decode("utf-8")
    assert exc.value.start == 7 and proc.stderr[7] == 0xC4  # Kiki 머신 트레이스와 같은 값


def test_guard_default_locale_control_decodes_fine() -> None:
    """대조군: 기본 로캘에서는 처음부터 UTF-8 이다(결함은 파이프 로캘이 cp949 일 때만)."""
    env = {k: v for k, v in _cp949_env().items() if k != "PYTHONIOENCODING"}
    env["PYTHONIOENCODING"] = "utf-8"
    proc = _run_guard(_GUARD, env)
    assert proc.returncode == 2
    assert "제9조" in proc.stderr.decode("utf-8")


# ── ② 자가시험: 읽는 쪽 ──────────────────────────────────────────────────────────


def _selftest_blocks(module: ModuleType) -> int:
    return sum(1 for f in module.FIXTURES if f[3] == module.BLOCK)


def test_selftest_passes_under_cp949_without_thread_noise() -> None:
    proc = subprocess.run(
        [sys.executable, str(_SELFTEST)],
        capture_output=True,
        timeout=120,
        env=_cp949_env(),
    )
    out, err = proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8")
    assert proc.returncode == 0, out + err
    assert "전건 일치" in out
    assert "Exception in thread" not in err and "UnicodeDecodeError" not in err


def test_selftest_reports_undecodable_guard_output_as_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """변별력: UTF-8 이 아닌 안내문을 내는 가드는 스레드 트레이스가 아니라 불일치로 계상된다."""
    legacy = _mutated_copy(_GUARD, tmp_path / "guard_legacy.py", "    _utf8_stderr()\n", "")
    selftest = _load(_SELFTEST, "selftest_guard_under_test")
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    for key, value in _cp949_env().items():
        monkeypatch.setenv(key, value)
    selftest.GUARD = legacy
    assert selftest.main() == 1
    out = capsys.readouterr().out
    assert out.count("가드 stderr 해독 실패") == _selftest_blocks(selftest)  # 차단 픽스처마다 1건
    assert "⛔ 불일치" in out


def test_selftest_flags_block_without_advice_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """변별력: 종료 코드는 2 인데 안내문이 빈 가드는 불일치다(종료 코드만 보면 초록이던 구멍)."""
    silent = _mutated_copy(
        _GUARD,
        tmp_path / "guard_silent.py",
        'print(f"{_ADVICE}\\n  차단 사유: {reason}", file=sys.stderr)',
        "pass",
    )
    selftest = _load(_SELFTEST, "selftest_guard_under_test2")
    selftest.GUARD = silent
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    assert selftest.main() == 1
    out = capsys.readouterr().out
    assert out.count("안내문에") == _selftest_blocks(selftest)
    assert "· 실제" not in out  # 종료 코드 불일치는 없다 — 안내문 단언만이 이 결함을 잡았다


def test_judge_fixture_unit() -> None:
    selftest = _load(_SELFTEST, "selftest_guard_unit")
    block, allow = selftest.BLOCK, selftest.ALLOW
    good = "⛔ 코딩 헌법 제9조 ①: ...\n  차단 사유: Edit 대상이 헌법 경로"
    assert selftest.judge_fixture(block, 2, good) is None
    assert selftest.judge_fixture(allow, 0, "") is None  # 통과 픽스처는 안내문을 요구하지 않는다
    assert "기대 2" in selftest.judge_fixture(block, 0, good)
    assert "안내문" in selftest.judge_fixture(block, 2, "")
    assert "안내문" in selftest.judge_fixture(block, 2, "제9조 만 있고 사유 줄이 없다")


# ── ③ 채택 도우미 + 규칙 병합 도구 ───────────────────────────────────────────────


def _merge_sandbox(tmp_path: Path) -> tuple[Path, Path]:
    """규칙 ID 충돌로 ⛔ 메시지를 내는 최소 입력(저장소의 현재 rules.yaml 에 의존하지 않는다)."""
    (tmp_path / "constitution").mkdir()
    rules = "version: v0\nrules:\n  - id: R1\n    statement: x\nsources: []\n"
    (tmp_path / "constitution" / "rules.yaml").write_text(rules, encoding="utf-8", newline="\n")
    additions = tmp_path / "additions.yaml"
    additions.write_text("rules:\n  - id: R1\n    statement: y\n", encoding="utf-8", newline="\n")
    return tmp_path, additions


def _run_merge_script(
    script: Path, cwd: Path, additions: Path
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(script), str(additions)],
        cwd=cwd,
        capture_output=True,
        timeout=60,
        env=_cp949_env(),
    )


def test_merge_rules_output_is_utf8_under_cp949(tmp_path: Path) -> None:
    cwd, additions = _merge_sandbox(tmp_path)
    proc = _run_merge_script(_MERGE, cwd, additions)
    assert proc.returncode == 1  # 중복 ID 거부(의도된 ⛔ 메시지 경로)
    assert "이미 등록된 규칙 ID" in proc.stdout.decode("utf-8")  # 엄격 해독
    assert b"Traceback" not in proc.stderr


def test_merge_rules_legacy_copy_crashes_on_unencodable_char_under_cp949(tmp_path: Path) -> None:
    """변별력: 재구성을 뗀 사본은 cp949 파이프에서 ⛔ 를 인코딩하지 못해 죽는다(수정 전 재현)."""
    cwd, additions = _merge_sandbox(tmp_path)
    legacy = _mutated_copy(
        _MERGE, tmp_path / "merge_rules_legacy.py", '_stream.reconfigure(encoding="utf-8")', "pass"
    )
    proc = _run_merge_script(legacy, cwd, additions)
    assert b"UnicodeEncodeError" in proc.stderr
    assert "이미 등록된 규칙 ID" not in proc.stdout.decode("cp949", errors="replace")


def test_run_merge_decodes_child_output_under_cp949(monkeypatch: pytest.MonkeyPatch) -> None:
    adopt = _load(_ADOPT, "adopt_amendment_under_test")
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    for key, value in _cp949_env().items():
        monkeypatch.setenv(key, value)
    done = adopt.run_merge(apply=False)  # 현재 rules.yaml 에 A0002 가 이미 병합돼 있어도 ⛔ 경로다
    assert isinstance(done.stdout, str)
    assert done.returncode in (0, 1)
    assert "Traceback" not in done.stderr


def test_run_merge_does_not_swallow_undecodable_child_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """변별력: UTF-8 이 아닌 바이트는 빈 출력으로 사라지지 않고 명시적 거부로 올라온다."""
    stub = tmp_path / "stub_merge.py"
    stub.write_text(
        "import sys\nsys.stdout.buffer.write('한글'.encode('cp949'))\nsys.exit(0)\n",
        encoding="utf-8",
        newline="\n",
    )
    adopt = _load(_ADOPT, "adopt_amendment_under_test2")
    monkeypatch.setattr(adopt, "MERGE_RULES", stub)
    with pytest.raises(adopt.RefusalError, match="해독 실패"):
        adopt.run_merge(apply=False)


def test_decode_helper_rejects_non_utf8_and_accepts_utf8() -> None:
    adopt = _load(_ADOPT, "adopt_amendment_under_test3")
    assert adopt._decode("한글 ⛔".encode(), "x") == "한글 ⛔"
    with pytest.raises(adopt.RefusalError, match="x 해독 실패"):
        adopt._decode("한글".encode("cp949"), "x")
