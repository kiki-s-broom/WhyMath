"""CI 미러의 계약 동결 — HARN-119.

이 파일이 지키는 것:
  · 앞 스텝이 실패하면 뒤 스텝을 **skipped로 계상**하는가 (2026-09-10 축의 핵심)
  · 실행할 수 없는 스텝을 **통과로 세지 않는가** (액션·식·조건 스텝)
  · 잡 이름 오타·스텝 0건을 사용 오류(exit 2)로 거부하는가
  · 출력이 억제·절단된 스텝도 **exit code로만** 판정하는가 (2026-08-09 축)
  · done 프리플라이트가 커밋 불일치를 "모른다"로 말하는가

각 절마다 그 절이 없으면 통과하는 입력을 픽스처로 둔다.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIRROR_PATH = _REPO_ROOT / "scripts" / "harness" / "ci_mirror.py"
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_DRIVE_DOC = _REPO_ROOT / ".claude" / "commands" / "drive.md"
_BACKLOG_CLI = _REPO_ROOT / "scripts" / "harness" / "backlog.py"


def _load_mirror():
    sys.path.insert(0, str(_MIRROR_PATH.parent))
    spec = importlib.util.spec_from_file_location("ci_mirror", _MIRROR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["ci_mirror"] = module
    spec.loader.exec_module(module)
    return module


mirror = _load_mirror()


def _wf(steps: list[dict], job_name: str = "demo", **job_extra) -> dict:
    job = {"steps": steps}
    job.update(job_extra)
    return {"jobs": {job_name: job}}


# ── ① 스텝 순차 실행 · skipped 계상 ───────────────────────────────────────
class TestStepSequencing:
    def test_failure_marks_following_steps_as_skipped(self, tmp_path):
        """앞 스텝 실패 → 뒤 스텝은 실행되지 않고 skipped로 계상된다.

        이 절이 없으면 뒤 스텝이 그냥 실행되거나 결과에서 사라진다. 둘 다
        "이번 실행에서 아무것도 모르는 검사"의 수를 말해 주지 못한다.
        """
        wf = _wf(
            [
                {"name": "ok", "run": "true"},
                {"name": "boom", "run": "exit 3"},
                {"name": "after-1", "run": "true"},
                {"name": "after-2", "run": "true"},
            ]
        )
        result = mirror.run_job(wf, "demo", tmp_path)
        by_name = {s.name: s for s in result.steps}
        assert by_name["ok"].status == mirror.PASSED
        assert by_name["boom"].status == mirror.FAILED
        assert by_name["boom"].exit_code == 3
        assert by_name["after-1"].status == mirror.SKIPPED_AFTER_FAILURE
        assert by_name["after-2"].status == mirror.SKIPPED_AFTER_FAILURE
        assert len(result.skipped_after_failure) == 2
        assert result.exit_code == 1

    def test_all_pass_means_zero_skipped(self, tmp_path):
        """대조군 — 전부 통과하면 skipped가 0이어야 한다(모두 skip 처리하는 과잉 수정 방지)."""
        wf = _wf([{"name": "a", "run": "true"}, {"name": "b", "run": "true"}])
        result = mirror.run_job(wf, "demo", tmp_path)
        assert result.exit_code == 0
        assert result.skipped_after_failure == []
        assert len([s for s in result.steps if s.status == mirror.PASSED]) == 2

    def test_timeout_is_recorded_as_failure_with_reason(self, tmp_path):
        """멈춘 사실 자체가 증거다 — 타임아웃은 원인이 남는 실패다."""
        wf = _wf([{"name": "hang", "run": "sleep 30"}])
        result = mirror.run_job(wf, "demo", tmp_path, timeout=1)
        step = result.steps[0]
        assert step.status == mirror.FAILED
        assert "타임아웃" in step.reason

    def test_step_results_flushed_immediately(self, tmp_path):
        """스텝마다 즉시 flush — 중간에 멈춰도 거기까지의 증거가 남는다."""
        log = tmp_path / "steps.ndjson"
        wf = _wf([{"name": "a", "run": "true"}, {"name": "b", "run": "exit 1"}])
        with log.open("w", encoding="utf-8") as handle:
            mirror.run_job(wf, "demo", tmp_path, log_handle=handle)
        lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        assert [entry["name"] for entry in lines] == ["a", "b"]
        assert lines[1]["exit_code"] == 1

    def test_stderr_tail_preserved_on_failure(self, tmp_path):
        """실패 *원인*이 남는가 — exit code만으로는 8개의 실패가 같은 글자로 보인다."""
        wf = _wf([{"name": "noisy", "run": "echo 구체적원인 >&2; exit 7"}])
        step = mirror.run_job(wf, "demo", tmp_path).steps[0]
        assert step.exit_code == 7
        assert "구체적원인" in step.stderr_tail


# ── ② 실행 불가 스텝은 통과로 계상하지 않는다 ─────────────────────────────
class TestNotRunnable:
    def test_uses_action_is_not_counted_as_passed(self, tmp_path):
        wf = _wf([{"name": "checkout", "uses": "actions/checkout@v4"}])
        step = mirror.run_job(wf, "demo", tmp_path).steps[0]
        assert step.status == mirror.NOT_RUNNABLE
        assert step.status != mirror.PASSED
        assert "액션" in step.reason

    def test_expression_step_is_not_run(self, tmp_path):
        """${{ }}를 빈 문자열로 치환해 돌리면 *다른 명령*의 결과를 이 스텝 것으로 보고한다."""
        wf = _wf([{"name": "secret", "run": "echo ${{ secrets.TOKEN }}"}])
        step = mirror.run_job(wf, "demo", tmp_path).steps[0]
        assert step.status == mirror.NOT_RUNNABLE
        assert "식" in step.reason

    def test_conditional_step_is_not_silently_passed(self, tmp_path):
        wf = _wf([{"name": "cond", "run": "true", "if": "failure()"}])
        step = mirror.run_job(wf, "demo", tmp_path).steps[0]
        assert step.status == mirror.NOT_RUNNABLE

    def test_missing_working_directory_is_not_runnable(self, tmp_path):
        wf = _wf([{"name": "x", "run": "true"}], defaults={"run": {"working-directory": "nope"}})
        step = mirror.run_job(wf, "demo", tmp_path).steps[0]
        assert step.status == mirror.NOT_RUNNABLE
        assert "작업 디렉터리" in step.reason

    def test_not_runnable_does_not_fail_the_job(self, tmp_path):
        """실행 불가는 실패가 아니다 — 그렇게 세면 사람이 도구를 끈다."""
        wf = _wf([{"name": "a", "uses": "actions/checkout@v4"}, {"name": "b", "run": "true"}])
        result = mirror.run_job(wf, "demo", tmp_path)
        assert result.exit_code == 0
        assert len(result.not_runnable) == 1


# ── ③ 사용 오류는 통과가 아니다 ───────────────────────────────────────────
class TestUsageErrors:
    def test_unknown_job_name_raises(self, tmp_path):
        with pytest.raises(mirror.MirrorUsageError):
            mirror.run_job(_wf([{"name": "a", "run": "true"}]), "오타난잡", tmp_path)

    def test_zero_steps_is_failure_not_pass(self, tmp_path):
        with pytest.raises(mirror.MirrorUsageError):
            mirror.run_job(_wf([]), "demo", tmp_path)

    def test_main_returns_two_on_unknown_job(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(_REPO_ROOT)
        rc = mirror.main(
            [
                "--workflow",
                str(_CI_PATH),
                "--result",
                str(tmp_path / "r.json"),
                "run",
                "--job",
                "없는잡",
            ]
        )
        assert rc == 2, "잡 이름 오타는 사용 오류(exit 2)여야 한다"
        assert "없는잡" in capsys.readouterr().err


# ── ④ 출력 억제·절단 스텝도 exit code로 판정 ──────────────────────────────
class TestExitCodeIsTheVerdict:
    def test_quiet_and_tail_do_not_hide_failure(self, tmp_path):
        """2026-08-09 축 재현 — `-q`와 `| tail`이 섞여도 판정은 exit code다.

        pipefail이 걸려 있어야 파이프 앞단의 실패가 보존된다. 이 절이 없으면
        tail의 exit 0이 앞 명령의 실패를 덮는다.
        """
        wf = _wf([{"name": "quiet-fail", "run": "bash -c 'echo x >&2; exit 5' | tail -1"}])
        step = mirror.run_job(wf, "demo", tmp_path).steps[0]
        assert step.status == mirror.FAILED, "파이프가 실패를 삼켰다 — pipefail 미적용"
        assert step.exit_code == 5

    def test_silent_success_is_still_pass(self, tmp_path):
        """대조군 — 조용한 성공은 성공이다."""
        wf = _wf([{"name": "quiet-ok", "run": "true | tail -1"}])
        assert mirror.run_job(wf, "demo", tmp_path).steps[0].status == mirror.PASSED

    def test_shell_flags_match_github_actions(self):
        """`-u`를 더하면 CI보다 엄격해져 거짓 실패를 낸다 — 플래그를 형태로 동결한다."""
        source = _MIRROR_PATH.read_text(encoding="utf-8")
        assert '"--noprofile", "--norc", "-eo", "pipefail"' in source
        assert '"-euo"' not in source, "CI 기본에 없는 -u를 쓰면 거짓 실패가 난다"


# ── ⑤ 결과 JSON · done 프리플라이트 ───────────────────────────────────────
class TestVerdict:
    def test_missing_result_is_unknown_not_pass(self, tmp_path):
        ok, reason = mirror.verdict_for_commit(tmp_path / "absent.json", "abc123")
        assert ok is False
        assert "없음" in reason

    def test_commit_mismatch_is_reported(self, tmp_path):
        path = tmp_path / "r.json"
        path.write_text(json.dumps({"commit": "0" * 40, "exit": 0, "jobs": []}), encoding="utf-8")
        ok, reason = mirror.verdict_for_commit(path, "f" * 40)
        assert ok is False
        assert "다른 커밋" in reason, "커밋 불일치를 '통과'로 접으면 이전 실행의 증거를 재사용한다"

    def test_failed_run_is_not_pass(self, tmp_path):
        path = tmp_path / "r.json"
        path.write_text(
            json.dumps({"commit": "a" * 40, "exit": 1, "jobs": [{"name": "backend", "exit": 1}]}),
            encoding="utf-8",
        )
        ok, reason = mirror.verdict_for_commit(path, "a" * 40)
        assert ok is False and "backend" in reason

    def test_matching_commit_and_zero_exit_passes(self, tmp_path):
        path = tmp_path / "r.json"
        path.write_text(
            json.dumps(
                {"commit": "a" * 40, "exit": 0, "jobs": [{"name": "infra-shell", "exit": 0}]}
            ),
            encoding="utf-8",
        )
        ok, reason = mirror.verdict_for_commit(path, "a" * 40)
        assert ok is True and "infra-shell" in reason

    def test_corrupt_json_is_unknown_not_crash(self, tmp_path):
        path = tmp_path / "r.json"
        path.write_text("{깨진", encoding="utf-8")
        ok, _ = mirror.verdict_for_commit(path, "a" * 40)
        assert ok is False


# ── ⑥ 배선 실재 — 정본화와 집행 지점의 분리 ───────────────────────────────
class TestWiring:
    def test_drive_runbook_calls_the_mirror(self):
        """정본화 축 — 런북이 미러를 부르는가(존재만으로는 배선이 아니다)."""
        text = _DRIVE_DOC.read_text(encoding="utf-8")
        assert "ci_mirror.py run" in text
        assert (
            "pytest` (+해당 시 `flutter test`) · `ruff` green" not in text
        ), "종전 문구가 남아 있으면 사람이 그쪽을 읽는다"

    def test_done_command_calls_preflight(self):
        """집행 지점 축 — done이 실제로 프리플라이트를 호출하는가."""
        source = _BACKLOG_CLI.read_text(encoding="utf-8")
        assert "def _warn_if_ci_mirror_missing" in source
        done_body = source.split("def cmd_done(", 1)[1].split("\ndef ", 1)[0]
        assert (
            "_warn_if_ci_mirror_missing(root)" in done_body
        ), "헬퍼를 정의만 하고 호출하지 않으면 정본화를 집행으로 착각한 것이다"

    def test_preflight_failure_does_not_block_done(self):
        """1단계는 warn이다 — 거부로 바뀌면 이 단언이 깨져 의도적 승격임을 드러낸다."""
        source = _BACKLOG_CLI.read_text(encoding="utf-8")
        helper = source.split("def _warn_if_ci_mirror_missing(", 1)[1].split("\ndef ", 1)[0]
        assert "_fail(" not in helper
        assert "return" in helper


# ── ⑦ 뮤테이션 — 도구를 깨뜨리면 테스트가 RED인가 ─────────────────────────
class TestMutationSelfCheck:
    """실행 파일을 건드리지 않고, 동일 로직을 깨뜨린 사본으로 변별력을 확인한다."""

    _counter = 0

    @classmethod
    def _mutated_module(cls, tmp_path: Path, old: str, new: str):
        original = _MIRROR_PATH.read_text(encoding="utf-8")
        assert original.count(old) == 1, f"치환 대상이 1건이 아니다: {old[:50]!r}"
        mutated = original.replace(old, new, 1)
        assert mutated != original, "주입이 적용되지 않았다 — 하네스 결함"
        cls._counter += 1
        name = f"ci_mirror_mutant_{cls._counter}"
        target = tmp_path / f"{name}.py"
        target.write_text(mutated, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(name, target)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        # exec_module *전에* 등록해야 한다 — dataclass가 sys.modules[cls.__module__]를
        # 조회하므로 미등록 상태로 실행하면 AttributeError로 죽는다(하네스 결함이
        # 뮤테이션 결과를 가리는 형태).
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(name, None)
        return module, original

    def test_m1_skipping_not_counted_is_detected(self, tmp_path):
        """M1: 실패 후 뒤 스텝을 그냥 실행하면 skipped 계상이 0이 된다."""
        mutant, original = self._mutated_module(
            tmp_path, "        if failed:\n", "        if False:\n"
        )
        wf = _wf([{"name": "boom", "run": "exit 1"}, {"name": "after", "run": "true"}])
        result = mutant.run_job(wf, "demo", tmp_path)
        assert len(result.skipped_after_failure) == 0, "뮤테이션이 적용되지 않았다"
        assert _MIRROR_PATH.read_text(encoding="utf-8") == original

    def test_m2_unknown_job_silently_passing_is_detected(self, tmp_path):
        """M2: 잡 이름 오타를 거부하지 않으면 빈 결과가 '통과'로 보인다."""
        mutant, original = self._mutated_module(
            tmp_path,
            '        raise MirrorUsageError(f"ci.yml에 없는 잡 이름: {job_name}")',
            "        return JobResult(name=job_name)",
        )
        result = mutant.run_job(_wf([{"name": "a", "run": "true"}]), "오타", tmp_path)
        assert result.exit_code == 0 and result.steps == [], "뮤테이션이 적용되지 않았다"
        with pytest.raises(mirror.MirrorUsageError):
            mirror.run_job(_wf([{"name": "a", "run": "true"}]), "오타", tmp_path)
        assert _MIRROR_PATH.read_text(encoding="utf-8") == original

    def test_m3_dropping_pipefail_hides_failure(self, tmp_path):
        """M3: pipefail을 빼면 `| tail`이 앞 명령의 실패를 삼킨다(2026-08-09 축)."""
        mutant, original = self._mutated_module(
            tmp_path,
            '["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]]',
            '["bash", "--noprofile", "--norc", "-c", step["run"]]',
        )
        wf = _wf([{"name": "quiet-fail", "run": "bash -c 'exit 5' | tail -1"}])
        assert (
            mutant.run_job(wf, "demo", tmp_path).steps[0].status == mutant.PASSED
        ), "뮤테이션이 적용되지 않았다 — pipefail 제거가 반영되어야 한다"
        assert mirror.run_job(wf, "demo", tmp_path).steps[0].status == mirror.FAILED
        assert _MIRROR_PATH.read_text(encoding="utf-8") == original

    def test_mutations_leave_source_byte_identical(self, tmp_path):
        digest = hashlib.sha256(_MIRROR_PATH.read_bytes()).hexdigest()
        self._mutated_module(tmp_path, 'PASSED = "passed"', 'PASSED = "PASSED"')
        assert hashlib.sha256(_MIRROR_PATH.read_bytes()).hexdigest() == digest


# ── ⑧ 실제 ci.yml 연동 ────────────────────────────────────────────────────
class TestAgainstRealWorkflow:
    def test_auto_job_selection_uses_coverage_tool(self, monkeypatch, tmp_path):
        """--job 미지정이면 HARN-109 열거기가 대상을 계산한다(계약 계승)."""
        monkeypatch.chdir(_REPO_ROOT)
        workflow = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
        args = mirror.build_parser().parse_args(
            ["--workflow", str(_CI_PATH), "--result", str(tmp_path / "r.json"), "run"]
        )
        monkeypatch.setattr(
            mirror.coverage, "changed_files_from_git", lambda base, root: ["docs/reviews/x.md"]
        )
        names = mirror._resolve_jobs(args, workflow, _REPO_ROOT)
        assert "harness-integrity" in names and "policy-guard" in names
        assert "backend" not in names, "문서 변경인데 backend를 대상으로 골랐다"

    def test_irreproducible_jobs_excluded_from_auto(self, monkeypatch, tmp_path, capsys):
        monkeypatch.chdir(_REPO_ROOT)
        workflow = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
        args = mirror.build_parser().parse_args(
            ["--workflow", str(_CI_PATH), "--result", str(tmp_path / "r.json"), "run"]
        )
        monkeypatch.setattr(
            mirror.coverage,
            "changed_files_from_git",
            lambda base, root: ["src/backend/whymath_backend/l3/router.py"],
        )
        names = mirror._resolve_jobs(args, workflow, _REPO_ROOT)
        assert "docker-build" not in names
        assert "재현 불가" in capsys.readouterr().out, "제외 사실을 침묵하면 사람이 통과로 읽는다"
