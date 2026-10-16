"""OPS-133 — run_demo.ps1의 낡은 데모 DB 진단·초기화 동결 (양방향 + 운영 DB 불가침).

**사고 경위** (2026-10-12 G-ops106-gate2-live-sample 실행, Phaiakes9 실측): `run_demo.ps1` [2/6]이
`Can't locate revision identified by '79de95331710'`로 throw 한 줄만 남기고 죽었다. 로그에 `Container
whymath-demo-db Started`가 찍혀 있어 새 DB가 아니라 **예전 컨테이너의 재기동**이었고, 그 DB의
`alembic_version`이 닫힌 PR #880 브랜치의 마이그레이션을 가리키고 있었다. 원인이 화면에 없어 Kiki가
왕복했다.

**무엇을 동결하는가** (acceptance 대응):
  ① 감지·안내·초기화 경계 — `TestMigrationBehavior`(pwsh로 실제 제어 흐름을 실행)·`TestStaticContract`
  ② 런북 — `TestRunbook`(§2 절 + §1 빨리감기 블록을 **임시 git 저장소에서 실제 실행**)
  ③ 실패 주입 양방향 — 낡은 DB는 RED(`TestMigrationBehavior::test_stale_*`), 정상 DB는 GREEN
     (`test_fresh_db_*`·`test_db_at_known_head_*`), 그리고 **모름/정상은 초기화하지 않는다**
     (`test_clean_*`·`test_unknown_*` — "모른다 ≠ 아니다")
  ④ 오염 경로 실측은 태스크 notes에 있다(이 파일의 대상 아님).

**검증 방식의 한계 (과신 금지)**: 실행은 PowerShell 7(`pwsh`) + bash 스텁(`docker`·`alembic`)이다.
Kiki 머신의 Windows PowerShell 5.1과 같은 인터프리터가 아니며, 실제 Docker·실제 alembic·실제 PG는
쓰지 않는다. 즉 이 테스트가 보증하는 것은 **분기 논리(언제 진단하고, 언제 지우고, 언제 거부하는가)**와
**운영 DB 불가침 경계**이지 5.1 고유 동작이나 실 DB 상태가 아니다.

**pwsh 부재 정책**: 로컬(미설치)에서는 skip하지만 CI에서는 **실패**한다 — skip만 있는 테스트는
보호가 아니다(infra-contracts 잡은 ubuntu-latest라 pwsh가 기본 탑재돼 있다).
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_DEMO = _REPO / "scripts" / "demo"
_RECOVERY = _DEMO / "demo_db_recovery.ps1"
_RUN_DEMO = _DEMO / "run_demo.ps1"
_HELPER = _DEMO / "diagnose_stale_demo_db.py"
_RUNBOOK = _REPO / "docs" / "ops" / "ops106_gate2_live_sample_runbook.md"
_VERSIONS = _REPO / "src" / "backend" / "alembic" / "versions"
_GUARD = _REPO / "scripts" / "ops" / "check_ps_scripts.py"

_STALE_REV = "79de95331710"  # 2026-10-12 실측 — 닫힌 PR #880의 audit_event 마이그레이션
_DEMO_URL = "postgresql+asyncpg://whymath@127.0.0.1:55432/whymath?ssl=disable"
_OTHER_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


helper = _load(_HELPER, "diagnose_stale_demo_db")
ps_guard = _load(_GUARD, "check_ps_scripts_for_ops133")


def _pwsh() -> str:
    """pwsh 경로. 로컬 부재는 skip, CI 부재는 실패(변별력 없는 skip 금지)."""
    exe = shutil.which("pwsh")
    if exe is None:
        if os.environ.get("CI"):
            pytest.fail("CI에 pwsh가 없다 — 이 테스트의 PowerShell 실행 검증이 통째로 빠진다")
        pytest.skip("pwsh 미설치(로컬) — CI에서는 실패로 처리된다")
    if sys.platform == "win32":
        pytest.skip("bash 스텁 기반 테스트 — Windows 러너 미지원")
    return exe


def _real_revisions() -> tuple[set[str], set[str]]:
    """(리비전 ID 집합, down_revision 집합) — 헬퍼와 **독립된** 구현(순환 검증 방지)."""
    revs: set[str] = set()
    downs: set[str] = set()
    for f in _VERSIONS.glob("*.py"):
        if f.name.startswith("__"):
            continue
        text = f.read_text(encoding="utf-8")
        m = re.search(r'^revision(?:: str)? = "([0-9a-f]+)"', text, re.M)
        assert m, f"리비전 선언을 못 읽음: {f.name}"
        revs.add(m.group(1))
        d = re.search(r'^down_revision(?:: [^=]+)? = "([0-9a-f]+)"', text, re.M)
        if d:
            downs.add(d.group(1))
    return revs, downs


def _a_head() -> str:
    revs, downs = _real_revisions()
    heads = sorted(revs - downs)
    assert heads, "head 리비전이 없다 — 리비전 스캔이 공허하다"
    return heads[0]


# ═════════════════════════════════════════════════════════════════════════════
# 1. 판정 헬퍼 — 3상태
# ═════════════════════════════════════════════════════════════════════════════
class TestJudge:
    def test_unknown_revision_is_stale(self) -> None:
        verdict, unknown = helper.judge([_STALE_REV], {"aaaa1111", "bbbb2222"})
        assert (verdict, unknown) == ("STALE", [_STALE_REV])

    def test_all_known_is_clean(self) -> None:
        verdict, unknown = helper.judge(["aaaa1111"], {"aaaa1111", "bbbb2222"})
        assert (verdict, unknown) == ("CLEAN", [])

    def test_mixed_reports_only_the_unknown(self) -> None:
        verdict, unknown = helper.judge(["aaaa1111", _STALE_REV], {"aaaa1111"})
        assert (verdict, unknown) == ("STALE", [_STALE_REV])

    def test_no_db_revisions_is_unknown_not_clean(self) -> None:
        """DB에서 아무것도 못 읽었다 = 모른다. CLEAN으로 접으면 낡은 DB를 놓친다."""
        assert helper.judge([], {"aaaa1111"})[0] == "UNKNOWN"
        assert helper.judge(["  ", ""], {"aaaa1111"})[0] == "UNKNOWN"

    def test_zero_known_revisions_is_unknown_not_stale(self) -> None:
        """스캔 0건은 실패 — 코드 쪽을 못 읽었는데 'DB가 전부 낡았다'고 말하면 위장이다."""
        assert helper.judge([_STALE_REV], set())[0] == "UNKNOWN"

    @pytest.mark.parametrize("garbage", ['ERROR: relation "alembic_version"', "a b", "x", "ab;rm"])
    def test_garbage_token_is_unknown_not_stale(self, garbage: str) -> None:
        """psql 오류 문구가 리비전 자리에 섞여도 '낡은 DB'로 오판하지 않는다."""
        assert helper.judge([garbage], {"aaaa1111"})[0] == "UNKNOWN"


class TestKnownRevisions:
    def test_scan_reads_every_real_revision_file(self) -> None:
        files = [f for f in _VERSIONS.glob("*.py") if not f.name.startswith("__")]
        known = helper.known_revisions(_VERSIONS)
        assert len(files) > 50, "리비전 디렉터리 스캔이 공허하다"
        assert len(known) == len(files), "리비전 파일마다 정확히 1개 ID여야 한다"

    def test_agrees_with_independent_parse(self) -> None:
        assert helper.known_revisions(_VERSIONS) == _real_revisions()[0]

    def test_real_head_is_known_and_stale_rev_is_not(self) -> None:
        known = helper.known_revisions(_VERSIONS)
        assert _a_head() in known
        assert _STALE_REV not in known, "main에 이미 들어온 리비전이면 이 사고 재현 전제가 무너진다"

    def test_down_revision_lines_do_not_leak_into_known(self, tmp_path: Path) -> None:
        (tmp_path / "20260101_0000_aaaa1111_x.py").write_text(
            'revision: str = "aaaa1111"\ndown_revision: str | None = "ghost9999"\n',
            encoding="utf-8",
        )
        assert helper.known_revisions(tmp_path) == {"aaaa1111"}

    def test_missing_dir_is_empty_set(self, tmp_path: Path) -> None:
        assert helper.known_revisions(tmp_path / "nope") == set()


class TestHelperCli:
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(_HELPER), *args], capture_output=True, text=True, encoding="utf-8"
        )

    def test_exit_codes_per_verdict(self) -> None:
        assert self._run("--db-revisions", _STALE_REV).returncode == 1
        assert self._run("--db-revisions", _a_head()).returncode == 0
        assert self._run().returncode == 2

    def test_output_is_ascii_and_names_the_unknown_revision(self) -> None:
        out = self._run("--db-revisions", _STALE_REV).stdout
        out.encode("ascii")  # cp949 중계 안전 — 비ASCII면 UnicodeEncodeError
        assert f"UNKNOWN_REVISIONS={_STALE_REV}" in out


# ═════════════════════════════════════════════════════════════════════════════
# 2. 정적 계약
# ═════════════════════════════════════════════════════════════════════════════
class TestStaticContract:
    @pytest.mark.parametrize("path", [_RUN_DEMO, _RECOVERY])
    def test_ps_files_have_bom_and_pass_the_ps_guard(self, path: Path) -> None:
        """한국어가 든 .ps1은 BOM 필수(PS 5.1이 cp949로 읽는다) — 가드가 그 외 구조도 본다."""
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")
        assert ps_guard.check_file(path) == []

    @pytest.mark.parametrize("path", [_RUN_DEMO, _RECOVERY])
    def test_ps_files_parse_without_errors(self, path: Path) -> None:
        pwsh = _pwsh()
        cmd = (
            "$e=$null;$t=$null;"
            f"[void][System.Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$t,[ref]$e);"
            "'PARSE_ERRORS=' + $e.Count; $e | ForEach-Object { $_.Message }"
        )
        out = subprocess.run(
            [pwsh, "-NoProfile", "-Command", cmd], capture_output=True, text=True, encoding="utf-8"
        )
        assert "PARSE_ERRORS=0" in out.stdout, out.stdout + out.stderr

    def test_production_db_never_appears_in_the_recovery_code(self) -> None:
        """운영 DB 불가침: 운영 DB의 포트·컨테이너 이름이 복구 코드에 **한 번도** 나오지 않는다."""
        text = _RECOVERY.read_text(encoding="utf-8-sig")
        for needle in (
            "5433",
            "whymath-pg",
            "docker-compose.prod",
            "docker-compose.pilot",
            "pilot-db",
        ):
            assert (
                needle not in text
            ), f"복구 코드에 {needle!r} — 운영/파일럿 DB를 건드릴 수 있는 경로"

    def test_run_demo_wires_the_recovery_and_has_explicit_reset_flag(self) -> None:
        text = _RUN_DEMO.read_text(encoding="utf-8-sig")
        assert re.search(
            r"^\[CmdletBinding\(\)\]\s*\r?\nparam\(\s*\r?\n\s*\[switch\]\$ResetStaleDemoDb",
            text,
            re.M,
        )
        assert "demo_db_recovery.ps1" in text and re.search(
            r"^\. \(Join-Path \$PSScriptRoot", text, re.M
        )
        assert re.search(r"Invoke-DemoMigration[^\n]*`", text), "[2/6]이 진단 함수를 거치지 않는다"
        assert "-ResetStaleDemoDb:$ResetStaleDemoDb" in text
        assert "-DatabaseUrl $env:WHYMATH_DATABASE_URL" in text

    def test_run_demo_does_not_regress_to_the_bare_throw_oneliner(self) -> None:
        """종전 형태(alembic 호출 직후 throw 한 줄)로 되돌아가면 원인이 다시 안 보인다."""
        text = _RUN_DEMO.read_text(encoding="utf-8-sig")
        assert not re.search(r"^\s*alembic -c alembic\.ini upgrade head", text, re.M)
        assert 'throw "alembic upgrade 실패."' not in text

    def test_run_demo_itself_never_deletes_the_database(self) -> None:
        """파괴 동작(down -v)은 복구 함수 안, 그것도 명시 플래그 뒤에만 있다."""
        assert "down -v" not in _RUN_DEMO.read_text(encoding="utf-8-sig")
        rec = _RECOVERY.read_text(encoding="utf-8-sig")
        # 주석·안내 문구가 아니라 **실행되는 줄**만 센다(줄 맨 앞이 docker 호출).
        destructive = [
            ln
            for ln in rec.splitlines()
            if ln.lstrip().startswith("docker ") and " down " in f" {ln} "
        ]
        assert len(destructive) == 1, destructive
        assert "-f $ComposeFile" in destructive[0]
        down_at = rec.index(destructive[0])
        gate_at = rec.index("if (-not $ResetStaleDemoDb)")
        assert gate_at < down_at, "플래그 검사가 파괴 동작보다 앞서야 한다"


# ═════════════════════════════════════════════════════════════════════════════
# 3. 행동 — pwsh로 Invoke-DemoMigration을 실제 실행 (docker·alembic은 bash 스텁)
# ═════════════════════════════════════════════════════════════════════════════
_DOCKER_STUB = r"""#!/usr/bin/env bash
# docker 스텁 — 호출 기록 + 데모 DB 상태 흉내. 인자: compose -f FILE <sub> ...
echo "$*" >> "$STUB_DIR/docker.log"
sub="$4"   # compose(1) -f(2) FILE(3) <서브커맨드>(4)
case "$sub" in
  down) : > "$STUB_DIR/state"; exit 0 ;;            # 볼륨째 제거 -> DB가 비게 된다
  up) exit 0 ;;
  exec)
    if [[ "$*" == *pg_isready* ]]; then exit 0; fi
    if [[ "$*" == *psql* ]]; then
      rev="$(cat "$STUB_DIR/state")"
      if [ -z "$rev" ]; then echo 'ERROR:  relation "alembic_version" does not exist' >&2; exit 1; fi
      echo "$rev"; exit 0
    fi ;;
esac
exit 0
"""

_ALEMBIC_STUB = r"""#!/usr/bin/env bash
# alembic 스텁 — 실물처럼: DB가 기억하는 리비전이 versions/에 없으면 실제 문구로 실패한다.
echo "alembic $*" >> "$STUB_DIR/alembic.log"
rev="$(cat "$STUB_DIR/state" 2>/dev/null)"
if [ -n "$rev" ] && ! grep -rqE "^revision(: str)? = \"$rev\"" "$VERSIONS_DIR"; then
  echo "FAILED: Can't locate revision identified by '$rev'" >&2
  exit 255
fi
if [ -n "$STUB_ALEMBIC_ALWAYS_FAIL" ]; then echo "boom" >&2; exit 1; fi
echo "INFO  [alembic.runtime.migration] Running upgrade  -> head"   # stdout 오염 시험(반환값에 섞이면 안 된다)
echo "$HEAD_REV" > "$STUB_DIR/state"
exit 0
"""

_DRIVER = r"""$ErrorActionPreference = "Stop"
. $env:DRV_RECOVERY
$reset = ($env:DRV_RESET -eq "1")
try {
  Invoke-DemoMigration -BackendDir $env:DRV_BACKEND -ComposeFile $env:DRV_COMPOSE `
    -HelperPath $env:DRV_HELPER -DatabaseUrl $env:DRV_DBURL -PythonExe $env:DRV_PY -ResetStaleDemoDb:$reset
  "DRIVER_RESULT=OK"
} catch {
  "DRIVER_RESULT=THROW: " + $_.Exception.Message
}
"""


@dataclass
class Run:
    stdout: str
    stderr: str
    docker_log: list[str]
    alembic_log: list[str]
    state_after: str
    compose: Path

    @property
    def threw(self) -> bool:
        return "DRIVER_RESULT=THROW" in self.stdout

    @property
    def ok(self) -> bool:
        return "DRIVER_RESULT=OK" in self.stdout

    def docker_calls(self, word: str) -> list[str]:
        return [ln for ln in self.docker_log if f" {word} " in f" {ln} "]


def _run_migration(
    tmp_path: Path,
    *,
    state: str,
    reset: bool = False,
    db_url: str = _DEMO_URL,
    compose_name: str = "docker-compose.demo.yml",
    always_fail: bool = False,
) -> Run:
    pwsh = _pwsh()
    bin_dir = tmp_path / "bin"
    stub_dir = tmp_path / "stub"
    backend = tmp_path / "backend"
    for d in (bin_dir, stub_dir, backend):
        d.mkdir()
    for name, body in (("docker", _DOCKER_STUB), ("alembic", _ALEMBIC_STUB)):
        f = bin_dir / name
        f.write_text(body, encoding="utf-8")
        f.chmod(f.stat().st_mode | stat.S_IXUSR)
    (stub_dir / "state").write_text(state, encoding="utf-8")
    compose = tmp_path / compose_name
    compose.write_text("services:\n  demo-db: {}\n", encoding="utf-8")
    driver = tmp_path / "driver.ps1"
    driver.write_text(_DRIVER, encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "STUB_DIR": str(stub_dir),
        "VERSIONS_DIR": str(_VERSIONS),
        "HEAD_REV": _a_head(),
        "DRV_RECOVERY": str(_RECOVERY),
        "DRV_BACKEND": str(backend),
        "DRV_COMPOSE": str(compose),
        "DRV_HELPER": str(_HELPER),
        "DRV_DBURL": db_url,
        "DRV_PY": sys.executable,
        "DRV_RESET": "1" if reset else "0",
        "STUB_ALEMBIC_ALWAYS_FAIL": "1" if always_fail else "",
    }
    proc = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(driver)],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )

    def lines(name: str) -> list[str]:
        p = stub_dir / name
        return p.read_text(encoding="utf-8").splitlines() if p.exists() else []

    return Run(
        stdout=proc.stdout,
        stderr=proc.stderr,
        docker_log=lines("docker.log"),
        alembic_log=lines("alembic.log"),
        state_after=(stub_dir / "state").read_text(encoding="utf-8").strip(),
        compose=compose,
    )


class TestMigrationBehavior:
    # ── GREEN 방향: 정상 DB는 건드리지도 진단하지도 않는다 ─────────────────────────
    def test_fresh_db_migrates_without_any_diagnosis(self, tmp_path: Path) -> None:
        r = _run_migration(tmp_path, state="")
        assert r.ok, r.stdout + r.stderr
        assert r.docker_log == [], "정상 경로에서 docker를 부르면 불필요한 부작용이다"
        assert len(r.alembic_log) == 1

    def test_db_at_known_head_migrates_without_any_diagnosis(self, tmp_path: Path) -> None:
        r = _run_migration(tmp_path, state=_a_head())
        assert r.ok, r.stdout + r.stderr
        assert r.docker_log == []

    # ── RED 방향: 낡은 DB ────────────────────────────────────────────────────────
    def test_stale_db_is_identified_and_reported_with_the_revision(self, tmp_path: Path) -> None:
        r = _run_migration(tmp_path, state=_STALE_REV)
        assert r.threw, r.stdout + r.stderr
        assert "낡은 데모 DB" in r.stdout
        assert _STALE_REV in r.stdout, "코드에 없는 리비전 번호가 화면에 나와야 원인이 보인다"
        assert (
            "Can't locate revision" in r.stderr + r.stdout
        ), "스텁이 실물 오류 문구를 내지 못했다(하네스 결함)"

    def test_stale_db_without_flag_is_not_deleted(self, tmp_path: Path) -> None:
        """초기화는 자동이 아니다 — 플래그 없이는 down도 up도 일어나지 않는다."""
        r = _run_migration(tmp_path, state=_STALE_REV, reset=False)
        assert r.threw
        assert "-ResetStaleDemoDb" in r.stdout, "해소 방법(플래그)이 안내돼야 한다"
        assert r.docker_calls("down") == [] and r.docker_calls("up") == []
        assert r.state_after == _STALE_REV, "데이터가 바뀌었다"

    def test_stale_db_with_flag_resets_only_the_demo_compose_and_recovers(
        self, tmp_path: Path
    ) -> None:
        r = _run_migration(tmp_path, state=_STALE_REV, reset=True)
        assert r.ok, r.stdout + r.stderr
        downs = r.docker_calls("down")
        assert len(downs) == 1 and "-v" in downs[0].split()
        assert downs[0].startswith(
            f"compose -f {r.compose} down"
        ), "데모 컴포즈 파일이 아닌 대상을 지웠다"
        assert len(r.docker_calls("up")) == 1
        assert len(r.alembic_log) == 2, "초기화 뒤 alembic을 정확히 한 번 재시도해야 한다"
        assert r.state_after == _a_head()
        # 순서: 진단(psql) -> down -> up -> pg_isready
        order = [ln for ln in r.docker_log if any(k in ln for k in ("psql", " down ", " up "))]
        assert [("psql" in ln, " down " in ln, " up " in ln) for ln in order] == [
            (True, False, False),
            (False, True, False),
            (False, False, True),
        ]

    def test_every_docker_call_targets_the_demo_compose_file(self, tmp_path: Path) -> None:
        r = _run_migration(tmp_path, state=_STALE_REV, reset=True)
        assert r.docker_log, "docker 호출이 하나도 없다 — 이 검사가 공허하다"
        for ln in r.docker_log:
            assert ln.startswith(f"compose -f {r.compose} "), ln
            assert "5433" not in ln and "whymath-pg" not in ln

    def test_reset_that_still_fails_reports_migration_problem_not_stale_db(
        self, tmp_path: Path
    ) -> None:
        r = _run_migration(tmp_path, state=_STALE_REV, reset=True, always_fail=True)
        assert r.threw
        assert "새로 만든 뒤에도" in r.stdout
        assert len(r.docker_calls("down")) == 1, "실패한 뒤 또 지우는 루프에 빠지면 안 된다"

    # ── 모른다 ≠ 아니다 ──────────────────────────────────────────────────────────
    @pytest.mark.parametrize("reset", [False, True])
    def test_clean_db_failure_is_not_blamed_on_staleness_and_never_resets(
        self, tmp_path: Path, reset: bool
    ) -> None:
        """리비전은 전부 코드에 있는데 alembic이 실패 -> 낡은 DB가 아니다. 플래그가 있어도 지우지 않는다."""
        r = _run_migration(tmp_path, state=_a_head(), reset=reset, always_fail=True)
        assert r.threw
        assert "낡은 DB 문제가 아님" in r.stdout
        assert r.docker_calls("down") == [] and r.docker_calls("up") == []

    @pytest.mark.parametrize("reset", [False, True])
    def test_unreadable_db_is_unknown_and_never_resets(self, tmp_path: Path, reset: bool) -> None:
        """psql이 리비전을 못 읽으면(테이블 없음 등) 낡았다고 단정하지 않고, 플래그가 있어도 지우지 않는다."""
        r = _run_migration(tmp_path, state="", reset=reset, always_fail=True)
        assert r.threw
        assert "판정하지 못했습니다" in r.stdout
        assert r.docker_calls("down") == [] and r.docker_calls("up") == []

    # ── 운영 DB 불가침 경계 ──────────────────────────────────────────────────────
    @pytest.mark.parametrize("reset", [False, True])
    def test_non_demo_database_url_is_neither_diagnosed_nor_reset(
        self, tmp_path: Path, reset: bool
    ) -> None:
        """WHYMATH_DEMO_DATABASE_URL이 다른 DB(예: 5433)를 가리키면 docker를 **한 번도** 부르지 않는다."""
        r = _run_migration(tmp_path, state=_STALE_REV, reset=reset, db_url=_OTHER_URL)
        assert r.threw
        assert "건너뜁니다" in r.stdout
        assert r.docker_log == [], f"데모 DB가 아닌 DB에 대해 docker를 호출했다: {r.docker_log}"
        assert r.state_after == _STALE_REV

    @pytest.mark.parametrize(
        "name", ["docker-compose.prod.yml", "docker-compose.pilot.yml", "compose.yml"]
    )
    def test_non_demo_compose_file_is_neither_diagnosed_nor_reset(
        self, tmp_path: Path, name: str
    ) -> None:
        r = _run_migration(tmp_path, state=_STALE_REV, reset=True, compose_name=name)
        assert r.threw
        assert r.docker_log == [], f"데모용이 아닌 컴포즈 파일로 docker를 호출했다: {r.docker_log}"


# ═════════════════════════════════════════════════════════════════════════════
# 4. 런북
# ═════════════════════════════════════════════════════════════════════════════
def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    nxt = re.search(r"^#{2,3} ", text[start + len(heading) :], re.M)
    return text[start : start + len(heading) + (nxt.start() if nxt else len(text))]


def _first_ps_fence(text: str) -> str:
    m = re.search(r"```powershell\n(.*?)```", text, re.S)
    assert m, "powershell 코드펜스가 없다"
    return m.group(1)


_FF_HEADING = "### 클론이 origin/main보다 뒤처졌을 때"
_REVLESS_HEADING = "### alembic 리비전을 못 찾을 때"
_KIKI_REPO = r"C:\Users\kiki\Desktop\__AI\WhyMath"


class TestRunbook:
    def test_both_new_sections_exist_under_the_right_parents(self) -> None:
        text = _RUNBOOK.read_text(encoding="utf-8")
        assert (
            text.index("## 1. 사전 점검") < text.index(_FF_HEADING) < text.index("## 2. 서버 기동")
        )
        assert (
            text.index("## 2. 서버 기동")
            < text.index(_REVLESS_HEADING)
            < text.index("## 3. 서버 확인")
        )

    def test_section2_points_at_the_explicit_flag_and_the_old_manual_path(self) -> None:
        sec = _section(_RUNBOOK.read_text(encoding="utf-8"), _REVLESS_HEADING)
        assert ".\\scripts\\demo\\run_demo.ps1 -ResetStaleDemoDb" in sec
        assert "stop_demo.ps1" in sec
        assert "운영 DB" in sec and "다른 컨테이너" in sec
        fence = _first_ps_fence(sec)
        assert (
            fence.strip().splitlines()[-1].strip().endswith("-ResetStaleDemoDb")
        ), "서버 점유 블록은 그 명령으로 끝나야 한다"

    def test_ff_block_uses_only_safe_git_verbs(self) -> None:
        block = _first_ps_fence(_section(_RUNBOOK.read_text(encoding="utf-8"), _FF_HEADING))
        assert "git merge --ff-only origin/main" in block
        for banned in (
            "git pull",
            "git checkout",
            "git reset",
            "git clean",
            "git stash",
            "git push",
            "--force",
            "git switch",
            "git rebase",
        ):
            assert banned not in block, f"{banned!r} — 공유 작업 사본을 건드릴 수 있다"
        assert block.count("git merge") == 1

    def test_section1_false_bullet_routes_the_behind_case_to_the_new_section(self) -> None:
        sec = _section(_RUNBOOK.read_text(encoding="utf-8"), "## 1. 사전 점검")
        assert "뒤처졌을 때" in sec and "브랜치를 옮기지" in sec


# ── §1 빨리감기 블록을 임시 git 저장소에서 **실제로 실행** ─────────────────────────
def _git(cwd: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    p = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8"
    )
    assert p.returncode == 0, f"git {args}: {p.stderr}"
    return p.stdout.strip()


def _commit(repo: Path, rel: str, content: str, msg: str) -> None:
    f = repo / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


@dataclass
class Clone:
    origin: Path
    upstream: Path  # 새 커밋을 만들어 origin에 올리는 쪽
    work: Path  # 블록이 실행되는 쪽(Kiki 클론 역)


def _make_clone(tmp_path: Path) -> Clone:
    origin = tmp_path / "origin.git"
    upstream = tmp_path / "upstream"
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(upstream))
    _git(upstream, "checkout", "-q", "-b", "main")
    _commit(upstream, "src/backend/a.txt", "v1\n", "seed")
    _commit(upstream, "notes.txt", "n1\n", "seed notes")
    _git(upstream, "push", "-q", "-u", "origin", "main")
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    return Clone(origin, upstream, work)


def _advance_origin(c: Clone, rel: str = "src/backend/a.txt", content: str = "v2\n") -> None:
    _commit(c.upstream, rel, content, "advance")
    _git(c.upstream, "push", "-q", "origin", "main")


def _run_ff_block(c: Clone, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    pwsh = _pwsh()
    block = _first_ps_fence(_section(_RUNBOOK.read_text(encoding="utf-8"), _FF_HEADING))
    assert (
        block.count(_KIKI_REPO) == 2
    ), "Kiki 경로 치환 대상이 2곳(cd·$Repo)이어야 한다 — 블록 형태가 바뀌었다"
    patched = block.replace(_KIKI_REPO, str(c.work))
    assert patched != block, "치환이 적용되지 않았다(하네스 결함)"
    script = tmp_path / "ff_block.ps1"
    script.write_text(patched, encoding="utf-8")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    return subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(script)],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


class TestFastForwardBlock:
    def test_behind_clone_is_fast_forwarded(self, tmp_path: Path) -> None:
        c = _make_clone(tmp_path)
        _advance_origin(c)
        before = _git(c.work, "rev-parse", "HEAD")
        out = _run_ff_block(c, tmp_path).stdout
        after = _git(c.work, "rev-parse", "HEAD")
        assert "FF_MERGE_EXIT=0" in out, out
        assert after == _git(c.upstream, "rev-parse", "HEAD") and after != before
        assert "FF_REFUSED" not in out

    def test_up_to_date_clone_is_refused_and_untouched(self, tmp_path: Path) -> None:
        c = _make_clone(tmp_path)
        before = _git(c.work, "rev-parse", "HEAD")
        out = _run_ff_block(c, tmp_path).stdout
        assert "FF_REFUSED=True" in out and "BEHIND_POSITIVE=False" in out, out
        assert "FF_MERGE_EXIT" not in out
        assert _git(c.work, "rev-parse", "HEAD") == before

    def test_diverged_clone_is_refused_and_untouched(self, tmp_path: Path) -> None:
        c = _make_clone(tmp_path)
        _commit(c.work, "local.txt", "mine\n", "local commit")  # 내 쪽에만 있는 커밋
        _advance_origin(c)
        before = _git(c.work, "rev-parse", "HEAD")
        out = _run_ff_block(c, tmp_path).stdout
        assert "FF_REFUSED=True" in out and "AHEAD_ZERO=False" in out, out
        assert _git(c.work, "rev-parse", "HEAD") == before

    def test_clone_on_another_branch_is_refused_and_not_switched(self, tmp_path: Path) -> None:
        c = _make_clone(tmp_path)
        _git(c.work, "checkout", "-q", "-b", "claude/other-session")
        _advance_origin(c)
        before = _git(c.work, "rev-parse", "HEAD")
        out = _run_ff_block(c, tmp_path).stdout
        assert "FF_REFUSED=True" in out and "ON_MAIN=False" in out, out
        assert _git(c.work, "rev-parse", "--abbrev-ref", "HEAD") == "claude/other-session"
        assert _git(c.work, "rev-parse", "HEAD") == before

    def test_uncommitted_change_in_compared_paths_is_refused_and_preserved(
        self, tmp_path: Path
    ) -> None:
        c = _make_clone(tmp_path)
        _advance_origin(c, "notes.txt", "n2\n")
        target = c.work / "src" / "backend" / "a.txt"
        target.write_text("my uncommitted work\n", encoding="utf-8")
        before = _git(c.work, "rev-parse", "HEAD")
        out = _run_ff_block(c, tmp_path).stdout
        assert "FF_REFUSED=True" in out and "PATHS_CLEAN=False" in out, out
        assert _git(c.work, "rev-parse", "HEAD") == before
        assert (
            target.read_text(encoding="utf-8") == "my uncommitted work\n"
        ), "미커밋 작업분이 사라졌다"

    def test_untracked_file_in_compared_paths_is_refused(self, tmp_path: Path) -> None:
        c = _make_clone(tmp_path)
        _advance_origin(c)
        (c.work / "scripts" / "demo").mkdir(parents=True)
        (c.work / "scripts" / "demo" / "scratch.txt").write_text("x", encoding="utf-8")
        out = _run_ff_block(c, tmp_path).stdout
        assert "FF_REFUSED=True" in out and "PATHS_CLEAN=False" in out, out

    def test_dirty_file_outside_compared_paths_does_not_block(self, tmp_path: Path) -> None:
        """'경로 한정'의 반대 방향 대조군 — 무관한 미커밋 변경 때문에 해소가 막히면 과잉 거부다."""
        c = _make_clone(tmp_path)
        _advance_origin(c)  # src/backend/a.txt 만 바뀜
        (c.work / "notes.txt").write_text("unrelated dirty\n", encoding="utf-8")
        out = _run_ff_block(c, tmp_path).stdout
        assert "FF_MERGE_EXIT=0" in out, out
        assert (c.work / "notes.txt").read_text(encoding="utf-8") == "unrelated dirty\n"

    def test_fetch_failure_is_refused_even_when_every_other_condition_holds(
        self, tmp_path: Path
    ) -> None:
        """FETCH_OK 절 **단독**을 밟는 픽스처 — 클론이 이미 뒤처짐을 알고(origin/main 갱신 완료)
        다른 네 조건이 전부 참인 상태에서 원격만 끊는다. 뒤처짐을 모르는 채 끊으면 BEHIND_POSITIVE=False로
        어차피 거부돼 FETCH_OK 절이 지워져도 통과한다(뮤테이션 M16 생존으로 발각)."""
        c = _make_clone(tmp_path)
        _advance_origin(c)
        _git(c.work, "fetch", "-q", "origin", "main")  # 뒤처짐을 먼저 알게 한다
        c.origin.rename(tmp_path / "origin.gone")  # 그 뒤 원격 도달 불가
        before = _git(c.work, "rev-parse", "HEAD")
        out = _run_ff_block(c, tmp_path).stdout
        assert "FETCH_OK=False" in out and "BEHIND_POSITIVE=True" in out, out
        assert "ON_MAIN=True" in out and "AHEAD_ZERO=True" in out and "PATHS_CLEAN=True" in out, out
        assert "FF_REFUSED=True" in out and "FF_MERGE_EXIT" not in out, out
        assert _git(c.work, "rev-parse", "HEAD") == before
