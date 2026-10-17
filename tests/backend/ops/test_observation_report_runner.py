"""[OPS-19] 관측 리포트 러너 — "0을 보고함"과 "돌지 못함"이 서로 다른 값으로 남는가.

가짜 리포트 모듈을 임시 디렉터리에 만들어 `module_prefix=""`로 부른다(실제 리포트 20개를
돌리지 않는다 — 그건 CI 스텝·compose 서비스의 몫이고, 여기서는 러너 자신의 판정을 본다).
네트워크·DB는 쓰지 않는다(헌법 R12-01).

검증 계약 (각 항목은 실패 상태를 주입해 RED가 되는 것만)
-------------------------------------------------------
① 종료 0이면 본문이 0건이어도 `ran_ok` — 관측 전용이라 수치의 좋고 나쁨을 판정하지 않는다.
② 종료 비-0이면 `run_failed` + stderr 꼬리(원인). ①과 **다른 값**이다.
③ 제한 시간 초과는 `run_timeout`, 프로세스를 못 띄우면 `spawn_error`.
④ 리포트 도중 러너가 죽어도 `running` 줄이 증거로 남는다(시작 전 flush).
⑤ 한 리포트의 실패가 뒤 리포트를 막지 않는다.
⑥ 접속 문자열 비밀번호는 매니페스트에 남지 않는다.
⑦ 자식 출력은 UTF-8로 저장·해시된다(Windows 로케일 cp949 방지).
⑧ 부류가 비었거나 알 수 없으면 통과가 아니라 실패다.
"""

from __future__ import annotations

import hashlib
import json
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.ops import observation_report_runner as runner
from whymath_backend.ops.observation_report_runner import (
    STATUS_FAILED,
    STATUS_OK,
    STATUS_RUNNING,
    STATUS_SPAWN,
    STATUS_TIMEOUT,
    ReportSpec,
)


def _write_module(root: Path, name: str, body: str) -> None:
    (root / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")


@pytest.fixture
def fakes(tmp_path: Path) -> Path:
    """가짜 리포트 모듈 모음. 이름이 곧 동작이다."""
    root = tmp_path / "fakes"
    root.mkdir()
    _write_module(root, "fake_ok", "print('# 리포트\\n행 수: 0건')\n")
    _write_module(
        root,
        "fake_fail",
        """
        import sys
        sys.stderr.write("DB 오류 — 조회 실패(ConnectionRefusedError): postgresql://u:s3cr3t@h:5432/d\\n")
        sys.exit(2)
        """,
    )
    _write_module(root, "fake_hang", "import time\ntime.sleep(30)\n")
    _write_module(
        root,
        "fake_peek",
        """
        import os, pathlib
        print(pathlib.Path(os.environ["OBS_OUT"], "manifest.json").read_text(encoding="utf-8"))
        """,
    )
    _write_module(root, "fake_korean", "print('한글 본문 — 가나다')\n")
    return root


def _run(fakes: Path, out: Path, modules: list[str], **kwargs: Any) -> dict[str, Any]:
    specs = [ReportSpec(m, runner.CLASS_CI) for m in modules]
    env = {"PYTHONPATH": str(fakes), "OBS_OUT": str(out)}
    return runner.run_reports(
        specs,
        out,
        klass=runner.CLASS_CI,
        module_prefix="",
        extra_env=env,
        timeout_s=kwargs.pop("timeout_s", 20),
        **kwargs,
    )


def test_exit_zero_with_zero_rows_is_ran_ok(fakes: Path, tmp_path: Path) -> None:
    """① 본문이 '0건'이어도 종료 0이면 ran_ok — 수치는 판정하지 않는다."""
    manifest = _run(fakes, tmp_path / "o", ["fake_ok"])
    item = manifest["reports"][0]
    assert item["status"] == STATUS_OK
    assert item["returncode"] == 0
    assert item["stderr_tail"] is None
    assert manifest["summary"] == {"total": 1, "ran_ok": 1, "not_ok": 0}


def test_output_file_and_hash_are_recorded(fakes: Path, tmp_path: Path) -> None:
    out = tmp_path / "o"
    manifest = _run(fakes, out, ["fake_ok"])
    item = manifest["reports"][0]
    saved = (out / item["output_file"]).read_bytes()
    assert item["output_bytes"] == len(saved) > 0
    assert item["output_sha256"] == hashlib.sha256(saved).hexdigest()


def test_nonzero_exit_is_run_failed_and_distinct_from_ok(fakes: Path, tmp_path: Path) -> None:
    """② 같은 '0건'처럼 보여도 돌지 못한 것은 다른 값 + 원인이 남는다."""
    manifest = _run(fakes, tmp_path / "o", ["fake_ok", "fake_fail"])
    ok, failed = manifest["reports"]
    assert ok["status"] == STATUS_OK
    assert failed["status"] == STATUS_FAILED
    assert failed["returncode"] == 2
    assert "ConnectionRefusedError" in failed["stderr_tail"]
    assert ok["status"] != failed["status"]
    assert manifest["summary"] == {"total": 2, "ran_ok": 1, "not_ok": 1}


def test_timeout_is_recorded_not_hung(fakes: Path, tmp_path: Path) -> None:
    """③ 멈춘 리포트는 제한 시간에 끊기고 그 사실이 남는다(무한 대기 금지)."""
    manifest = _run(fakes, tmp_path / "o", ["fake_hang"], timeout_s=1)
    item = manifest["reports"][0]
    assert item["status"] == STATUS_TIMEOUT
    assert item["returncode"] is None
    assert "초과" in item["stderr_tail"]


def test_spawn_error_when_interpreter_missing(fakes: Path, tmp_path: Path) -> None:
    """③ 프로세스 자체를 못 띄우는 경우도 예외로 새지 않고 기록된다."""
    manifest = _run(fakes, tmp_path / "o", ["fake_ok"], python=str(tmp_path / "no-such-python"))
    item = manifest["reports"][0]
    assert item["status"] == STATUS_SPAWN
    assert item["stderr_tail"]


def test_running_entry_is_flushed_before_the_report_finishes(fakes: Path, tmp_path: Path) -> None:
    """④ 리포트가 도는 중에 디스크의 매니페스트를 읽으면 그 리포트가 `running`이고 미완료다.

    마지막에 한 번만 저장하는 방식이면 이 값이 없다 — 중간에 죽으면 증거가 통째로 사라진다.
    """
    out = tmp_path / "o"
    manifest = _run(fakes, out, ["fake_ok", "fake_peek"])
    item = manifest["reports"][1]
    seen = json.loads((out / item["output_file"]).read_text(encoding="utf-8"))
    assert seen["complete"] is False
    assert seen["reports"][-1]["report"] == "fake_peek"
    assert seen["reports"][-1]["status"] == STATUS_RUNNING
    # 앞 리포트의 최종 상태는 뒤 리포트가 도는 동안 이미 디스크에 있다(마지막에 몰아 쓰지 않는다).
    assert seen["reports"][0]["status"] == STATUS_OK
    # 끝난 뒤에는 running이 남지 않는다.
    final = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert final["complete"] is True
    assert all(r["status"] != STATUS_RUNNING for r in final["reports"])


def test_one_failure_does_not_stop_later_reports(fakes: Path, tmp_path: Path) -> None:
    """⑤ 앞 리포트가 실패해도 뒤 리포트는 돈다 — 전부 돌린 뒤 종료 코드로 판정한다."""
    manifest = _run(fakes, tmp_path / "o", ["fake_fail", "fake_ok"])
    assert [r["status"] for r in manifest["reports"]] == [STATUS_FAILED, STATUS_OK]


def test_password_is_redacted_in_manifest(fakes: Path, tmp_path: Path) -> None:
    """⑥ 원인은 남기되 접속 문자열의 비밀번호는 남기지 않는다."""
    out = tmp_path / "o"
    _run(fakes, out, ["fake_fail"])
    raw = (out / "manifest.json").read_text(encoding="utf-8")
    assert "s3cr3t" not in raw
    assert "u:***@h" in raw


def test_redact_leaves_text_without_credentials_untouched() -> None:
    assert runner.redact("연결 실패: host=db port=5432") == "연결 실패: host=db port=5432"
    assert runner.redact("postgresql+asyncpg://who:pw@db:5432/x") == (
        "postgresql+asyncpg://who:***@db:5432/x"
    )


def test_child_output_is_utf8_even_if_parent_locale_is_not(fakes: Path, tmp_path: Path) -> None:
    """⑦ 부모 환경이 UTF-8을 강제하지 않아도 자식 출력은 UTF-8 바이트로 저장된다."""
    out = tmp_path / "o"
    manifest = _run(fakes, out, ["fake_korean"])
    saved = (out / manifest["reports"][0]["output_file"]).read_bytes()
    assert "한글 본문" in saved.decode("utf-8")


def test_child_env_forces_utf8_regardless_of_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    """⑦ 이 환경의 로케일은 이미 UTF-8이라 위 출력 테스트는 설정을 지워도 통과한다 — 변별력이
    없는 부분을 환경 구성 자체의 직접 단언으로 보강한다(부모가 cp949 계열을 줘도 덮어쓴다)."""
    monkeypatch.setenv("PYTHONUTF8", "0")
    monkeypatch.setenv("PYTHONIOENCODING", "cp949")
    env = runner._child_env({"EXTRA": "1"})
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["EXTRA"] == "1"


def test_two_runs_give_the_same_statuses(fakes: Path, tmp_path: Path) -> None:
    """읽기 전용 관측이라 재실행해도 상태·해시가 같다(시계·run_id 필드만 다르다)."""
    first = _run(fakes, tmp_path / "a", ["fake_ok", "fake_fail"])
    second = _run(fakes, tmp_path / "b", ["fake_ok", "fake_fail"])
    keep = ("report", "status", "returncode", "output_sha256")
    assert [{k: r[k] for k in keep} for r in first["reports"]] == [
        {k: r[k] for k in keep} for r in second["reports"]
    ]
    assert first["run_id"] != second["run_id"]


def test_select_rejects_unknown_class() -> None:
    """⑧ 알 수 없는 부류는 빈 목록(=조용한 통과)이 아니라 예외다."""
    with pytest.raises(ValueError):
        runner.select("typo")


def test_real_registry_has_every_class_populated() -> None:
    """⑧ 부류가 비면 그 부류의 스텝은 아무것도 돌리지 않고 초록이 된다."""
    for klass in runner.CLASSES:
        assert runner.select(klass), klass


def test_main_exit_codes(monkeypatch: pytest.MonkeyPatch, fakes: Path, tmp_path: Path) -> None:
    """전부 ran_ok면 0, 하나라도 못 돌면 1, 대상 0건이면 1."""
    monkeypatch.setenv("PYTHONPATH", str(fakes))
    real_run = runner.run_reports

    def with_fakes(specs: Any, out: Path, **kw: Any) -> dict[str, Any]:
        return real_run(specs, out, module_prefix="", **kw)

    monkeypatch.setattr(runner, "run_reports", with_fakes)

    monkeypatch.setattr(runner, "REPORTS", (ReportSpec("fake_ok", runner.CLASS_CI),))
    assert runner.main(["--class", "ci", "--out", str(tmp_path / "ok")]) == 0

    monkeypatch.setattr(
        runner,
        "REPORTS",
        (ReportSpec("fake_ok", runner.CLASS_CI), ReportSpec("fake_fail", runner.CLASS_CI)),
    )
    assert runner.main(["--class", "ci", "--out", str(tmp_path / "bad")]) == 1

    monkeypatch.setattr(runner, "REPORTS", ())
    assert runner.main(["--class", "ci", "--out", str(tmp_path / "empty")]) == 1


def test_default_python_is_the_current_interpreter(fakes: Path, tmp_path: Path) -> None:
    """실행기 단독 호출 금지 — 러너를 띄운 인터프리터와 같은 것으로 자식을 띄운다."""
    manifest = _run(fakes, tmp_path / "o", ["fake_ok"])
    assert manifest["reports"][0]["status"] == STATUS_OK
    assert sys.executable
