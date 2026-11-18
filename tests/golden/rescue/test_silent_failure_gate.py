"""RS-G2 조용한 실패 게이트 — 골든 구역의 오류 삼키기 건수를 허용 목록과 정확히 맞춘다.

무엇을 막는가
- 조용한 실패(오류를 `except`로 삼키고 멀쩡한 척하는 코드)가 새 구역 `src/backend/golden/`에
  들어오는 것. 백엔드 린트 설정(`pyproject.toml`)에는 이 규칙이 없어서 따로 검사한다.

어떻게 재는가
- ruff를 하위 프로세스로 돌린다(타임아웃 60초 · 출력 인코딩 utf-8).
  규칙 세 개: BLE001(광범위 except) · S110(try-except-pass) · E722(맨 except).
- `--ignore-noqa` : 코드의 `# noqa` 표시로 게이트를 비켜 갈 수 없게 한다.
- `--isolated`    : pyproject 설정(per-file-ignores 등)이 바뀌어도 게이트가 조용히 꺼지지 않게 한다.
- 결과 `경로:줄 · 규칙` 집합이 허용 목록 `silent_failure_allow.txt`와 정확히 같아야 통과한다.
  새 건이 생겨도 실패하고, 목록에만 있고 실제로는 없는 줄이 남아도 실패한다.

실패를 통과로 위장하지 않는 장치
- ruff가 없거나 비정상 종료하면(종료 코드 0·1이 아님) 건너뛰지 않고 실패한다.
- 검사 대상 .py가 0개면 실패한다(빈 스캔은 공허한 통과다).
- 합성 파일로 세 규칙이 실제로 켜져 있는지 먼저 확인한다(규칙이 꺼진 ruff는 늘 0건을 낸다).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# 저장소 루트 — tests/golden/rescue/이 파일 → parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]
# ruff를 돌리는 작업 폴더(경로를 `golden/…` 형태로 맞추려고 src/backend에서 돈다)
_BACKEND = _REPO_ROOT / "src" / "backend"
# 검사 대상 — 새 코드가 쌓이는 골든 구역
_GOLDEN = _BACKEND / "golden"
# 허용 목록(경로:줄 · 규칙 · 이유)
_ALLOW = Path(__file__).with_name("silent_failure_allow.txt")

# 검사하는 규칙 세 개
_RULES = ("BLE001", "S110", "E722")
# ruff 하위 프로세스 타임아웃(초)
_TIMEOUT_S = 60
# ruff 종료 코드: 0 = 위반 없음 · 1 = 위반 있음. 그 밖(2 등)은 도구 오류다.
_RUFF_OK_CODES = (0, 1)


def _ruff_cmd(module: str = "ruff") -> list[str]:
    """ruff 실행 명령. 테스트와 같은 파이썬으로 부른다(다른 인터프리터에 붙지 않게)."""
    return [
        sys.executable,
        "-m",
        module,
        "check",
        "--isolated",
        "--no-cache",
        "--ignore-noqa",
        "--select",
        ",".join(_RULES),
        "--output-format",
        "json",
    ]


def _run_ruff(target: Path, cwd: Path, module: str = "ruff") -> list[tuple[str, int, str]]:
    """ruff를 돌려 (경로, 줄, 규칙) 목록을 돌려준다. 도구 오류는 실패로 올린다(건너뛰지 않음)."""
    try:
        proc = subprocess.run(
            [*_ruff_cmd(module), str(target)],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"ruff가 {_TIMEOUT_S}초 안에 끝나지 않았다 — 게이트 판정 불가")
    # 주의: `python -m <없는 모듈>`도 종료 코드 1을 낸다(실측). 그래서 종료 코드만으로는
    # "위반 있음"과 "ruff 없음"을 가르지 못한다 — 출력이 JSON인지, 코드와 건수가 맞는지 함께 본다.
    stderr = proc.stderr.strip()[:500]
    if proc.returncode not in _RUFF_OK_CODES:
        pytest.fail(f"ruff 실행 오류(종료 코드 {proc.returncode}) — 통과로 치지 않는다.\n{stderr}")
    try:
        records = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"ruff 실행 오류(출력이 JSON이 아님 · {type(exc).__name__}) — ruff가 없거나 고장이다. "
            f"통과로 치지 않는다.\nstderr: {stderr}"
        )
    if not isinstance(records, list) or (proc.returncode == 1) != bool(records):
        pytest.fail(
            f"ruff 실행 오류(종료 코드 {proc.returncode}와 결과 건수가 맞지 않음) — "
            f"통과로 치지 않는다.\nstderr: {stderr}"
        )
    found: list[tuple[str, int, str]] = []
    for rec in records:
        path = Path(rec["filename"]).resolve()
        try:
            rel = path.relative_to(cwd.resolve()).as_posix()
        except ValueError:
            rel = path.as_posix()
        found.append((rel, int(rec["location"]["row"]), str(rec["code"])))
    return sorted(found)


def _load_allow(path: Path) -> list[tuple[str, int, str]]:
    """허용 목록을 읽는다. 형식이 틀리거나 이유가 비었거나 중복이면 실패로 올린다."""
    entries: list[tuple[str, int, str]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(" · ")]
        if len(parts) < 3 or not all(parts[:3]):
            pytest.fail(f"허용 목록 {lineno}줄 형식 오류(경로:줄 · 규칙 · 이유): {raw!r}")
        loc, rule = parts[0], parts[1]
        file_part, sep, line_part = loc.rpartition(":")
        if not sep or not line_part.isdigit() or rule not in _RULES:
            pytest.fail(f"허용 목록 {lineno}줄 위치·규칙 오류: {raw!r}")
        key = (file_part, int(line_part), rule)
        if key in entries:
            pytest.fail(f"허용 목록 {lineno}줄 중복: {raw!r}")
        entries.append(key)
    return sorted(entries)


def _fmt(items: list[tuple[str, int, str]]) -> str:
    """(경로, 줄, 규칙) 목록을 사람이 읽는 줄로."""
    return "\n".join(f"  {p}:{n} · {r}" for p, n, r in items) or "  (없음)"


def test_rules_are_live_on_synthetic_file(tmp_path: Path) -> None:
    """변별력 확인: 같은 명령이 합성 파일에서 세 규칙을 모두 잡아야 한다."""
    sample = tmp_path / "swallow.py"
    sample.write_text(
        "def a() -> None:\n"
        "    try:\n"
        "        pass\n"
        "    except Exception:  # noqa: BLE001\n"
        "        pass\n"
        "\n\n"
        "def b() -> None:\n"
        "    try:\n"
        "        pass\n"
        "    except:  # noqa: E722\n"
        "        pass\n",
        encoding="utf-8",
    )
    codes = {rule for _, _, rule in _run_ruff(sample, tmp_path)}
    assert codes == set(_RULES), f"ruff가 규칙을 다 잡지 못했다(--ignore-noqa 포함): {codes}"


def test_missing_ruff_is_an_error_not_a_pass(tmp_path: Path) -> None:
    """도구가 없을 때 0건(통과)이 아니라 실패가 나야 한다."""
    with pytest.raises(pytest.fail.Exception, match="ruff 실행 오류"):
        _run_ruff(tmp_path, tmp_path, module="ruff_module_that_does_not_exist")


def test_golden_silent_failures_match_allow_list() -> None:
    """골든 구역의 세 규칙 건수가 허용 목록과 정확히 같아야 한다."""
    py_files = list(_GOLDEN.rglob("*.py"))
    assert py_files, f"검사 대상 .py가 0개다 — 경로가 틀렸다: {_GOLDEN}"

    actual = _run_ruff(_GOLDEN, _BACKEND)
    allowed = _load_allow(_ALLOW)

    new = sorted(set(actual) - set(allowed))
    stale = sorted(set(allowed) - set(actual))
    assert not new and not stale, (
        "조용한 실패 게이트 불일치\n"
        f"[새 건 — 허용 목록에 없음] 고치거나, Kiki 결정 후 이유와 함께 목록에 올린다:\n{_fmt(new)}\n"
        f"[남은 줄 — 실제로는 없음] 목록에서 지운다(줄 번호가 옮겨졌으면 고친다):\n{_fmt(stale)}"
    )
