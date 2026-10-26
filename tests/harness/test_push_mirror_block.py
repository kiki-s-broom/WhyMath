"""푸시 직전 고지를 차단으로 — 상시 잡 미러 없이는 푸시를 거부한다 (HARN-308).

왜 이 파일이 있는가: HARN-209 푸시 직전 고지는 "막지 않는 알림"이라 세션이 고지를 보고도 푸시할 수
있다. 2026-10-09 P3-03(PR #1512)에서 고지를 **두 번** 지나쳐 푸시했고, 두 번째 푸시(9daddd6b)가
로컬에서 한 번도 돌리지 않은 상시 잡 `infra-contracts`(헌법 R3-01 가드 `tests/test_idempotency.py`)에서
red가 됐다. 고지는 같은 (HEAD·사유)를 한 번만 알리므로 **두 번째 시도는 침묵했다** — 알림이 습관화되는
것이 아니라 설계상 두 번째부터는 아예 안 나온다. 산문·고지가 2회 이상 뚫리면 코드로 막는다
(CLAUDE.md 실수 관리).

이 파일은 등록된 훅 명령 문자열을 **그대로** 실행해 종료 코드로 판정한다 (단위 함수가 아니라 실제
도구 호출이 지나는 경로). 각 절마다 "그 절이 없으면 통과해 버리는 반례"를 픽스처로 둔다:

  절                                          그 절이 없으면 통과해 버리는 반례
  ──────────────────────────────────────────────────────────────────────────────────────────
  결과 없음·다른 커밋·실패 → 차단              고지만 나가고 푸시가 진행(P3-03 원 사고)
  차단은 중복 억제 대상이 아님                 두 번째 시도가 침묵으로 통과(P3-03 두 번째 푸시)
  필수 상시 잡 전부가 결과에 있어야 통과       잡 하나만 돌린 통과 결과가 상시 6잡을 면제
  통과한 스텝이 0개인 잡은 돌지 않은 잡        환경 전제만 있는 잡 기록이 통과로 계상
  같은 커밋 전 잡 통과 → 허용(대조군)           모든 푸시를 차단 — 사람이 훅을 끈다
  미실행 스텝 → 허용(HARN-181 전)              조건 스텝 잡을 건드리는 모든 푸시가 차단
  면제 A·B(대장 기록·같은 기여)                 `done` 뒤 대장 커밋 푸시마다 차단
  문서만 → 차단(반대 대조군)                    문서가 면제 — 런북 한 장이 infra-shell을 깬 실측
  복합 `commit && push` → 차단                 아직 없는 커밋이 미러 없이 통과
  PR 생성은 차단하지 않음                      본문 섹션 고지가 PR 생성을 막는 훅으로 변질
  측정 불가(unavailable) → 허용                 훅 자신의 고장이 모든 푸시를 막음
  우회: 사유 필수·대장 기록·내용 한정            남지 않는 탈출구 / 한 번의 우회가 이후 모든 푸시를 면제
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import ci_job_coverage as coverage
import ci_mirror
import push_mirror_notice as pmn
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SETTINGS = _REPO_ROOT / ".claude" / "settings.json"
_HOOK = _REPO_ROOT / ".claude" / "hooks" / "push_mirror_notice.py"
_MODULE = _REPO_ROOT / "scripts" / "harness" / "push_mirror_notice.py"
_REAL_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_PR_TOOL = "mcp__github__create_pull_request"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="실제 git이 필요하다")


# ── 픽스처: 실제 git 저장소 + 실제 워크플로 ────────────────────────────────────
def _git(repo: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", *argv],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    ).stdout.strip()


def _write(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit(repo: Path, rel: str, content: str, msg: str = "c") -> str:
    _write(repo, rel, content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """실제 `ci.yml`을 가진 저장소 — `feature` 브랜치에 코드 커밋이 하나 올라 있다."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _write(root, ".gitignore", ".claude/cache/\n.claude/logs/\n")
    _write(root, "README.md", "base\n")
    _write(root, "docs/guide.md", "guide\n")
    _write(root, "src/app.py", "a = 1\n")
    _write(root, "backlog/events/s.ndjson", '{"a": 1}\n')
    _write(root, "backlog/tasks/T-1.yaml", "id: T-1\n")
    _write(root, ".github/workflows/ci.yml", _REAL_CI.read_text(encoding="utf-8"))
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(root, "checkout", "-q", "-b", "feature")
    _commit(root, "src/app.py", "a = 2\n", "feature")
    return root


def _required(repo: Path) -> list[str]:
    """독립 기준(oracle) — 판정 모듈을 거치지 않고 워크플로에서 직접 뽑은 필수 상시 잡.

    미러가 자동 선택으로 돌리는 잡과 같다: 상시이고 로컬 재현 가능하며 필터 계산 잡(`changes`)이 아닌 것.
    """
    scopes = coverage.classify_jobs(coverage.load_workflow(repo / ".github/workflows/ci.yml"), [])
    return [
        s.name
        for s in scopes
        if s.status == coverage.ALWAYS
        and s.env.reproducible_locally
        and s.name != coverage.FILTER_JOB
    ]


def _job(name: str, *, exit_code: int = 0, steps: list[dict] | None = None) -> dict:
    default = [{"name": "실행 스텝", "status": "passed", "reason": ""}]
    return {"name": name, "exit": exit_code, "steps": default if steps is None else steps}


def _mirror(
    repo: Path,
    commit: str,
    *,
    jobs: list[dict] | None = None,
    exit_code: int = 0,
    tainted: bool | None = False,
) -> None:
    """`.claude/cache/ci_mirror.json`에 해당 커밋의 미러 결과를 쓴다. 기본값 = 필수 상시 잡 전부 통과."""
    if jobs is None:
        jobs = [_job(name) for name in _required(repo)]
    payload = {
        "schema": ci_mirror.RESULT_SCHEMA,
        "commit": commit,
        "jobs": jobs,
        "not_executed": 0,
        "exit": exit_code,
        "tainted": tainted,
    }
    path = repo / ci_mirror.DEFAULT_RESULT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


# ── 등록된 훅 명령 문자열 그대로 실행 ───────────────────────────────────────────
def _registered_command() -> str:
    settings = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for block in settings["hooks"]["PreToolUse"]
        for hook in block["hooks"]
        if "push_mirror_notice.py" in hook.get("command", "")
    ]
    assert len(commands) == 1
    return commands[0]


def _run_hook(
    repo: Path, event: dict, *, env_extra: dict | None = None
) -> subprocess.CompletedProcess[bytes]:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(_REPO_ROOT), **(env_extra or {})}
    payload = json.dumps({"cwd": str(repo), "session_id": "s1", **event}).encode("utf-8")
    return subprocess.run(
        _registered_command(), shell=True, input=payload, capture_output=True, cwd=repo, env=env
    )


def _push(command: str = "git push -u origin feature") -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _stderr(proc: subprocess.CompletedProcess[bytes]) -> str:
    return proc.stderr.decode("utf-8", "replace")


def _log_rows(repo: Path) -> list[dict]:
    path = repo / ".claude" / "logs" / "push_mirror_notices.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _waive(repo: Path, reason: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_MODULE), "waive", "--reason", reason, "--root", str(repo)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=repo,
    )


def _waiver_events(repo: Path) -> list[dict]:
    rows: list[dict] = []
    events = repo / "backlog" / "events"
    for path in sorted(events.glob("*.ndjson")) if events.is_dir() else []:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                if record.get("action") == pmn.WAIVER_ACTION:
                    rows.append(record)
    return rows


# ═════════════════════════════════════════════════════════════════════════════
# ① 실패 고정 — P3-03 경로 (고지를 보고도 푸시가 진행된다)
# ═════════════════════════════════════════════════════════════════════════════
class TestP303Reproduction:
    def test_workflow_requires_the_job_that_went_red_in_p303(self, repo: Path) -> None:
        """독립 기준 점검 — 실제 워크플로의 필수 상시 잡에 P3-03이 깨뜨린 잡이 들어 있다."""
        required = _required(repo)
        assert "infra-contracts" in required and "harness-integrity" in required

    def test_push_with_a_stale_mirror_result_is_refused(self, repo: Path) -> None:
        """P3-03 첫 푸시 경로 — 미러 결과가 **다른 커밋의 것**이면 고지로 끝나지 않고 거부된다."""
        old = _head(repo)
        _mirror(repo, old)
        _commit(repo, "src/other.py", "y = 1\n")  # 미러가 본 적 없는 코드
        proc = _run_hook(repo, _push())
        assert proc.returncode == 2, "고지만 나가고 푸시가 진행된다 — HARN-209의 구멍 그대로"
        assert proc.stdout == b"", "exit 2에서 stdout은 무시된다 — 이유는 stderr에 있어야 한다"
        message = _stderr(proc)
        assert "ci_mirror.py run" in message, "다음 행동(실행할 명령)이 없다"
        assert "waive" in message and "--reason" in message, "우회 경로가 안내되지 않는다"

    def test_second_attempt_of_the_same_push_is_refused_again(self, repo: Path) -> None:
        """P3-03 **두 번째** 푸시 — 고지는 같은 (HEAD·사유)를 한 번만 알려 두 번째는 침묵했다.

        차단이 같은 중복 억제를 따르면 첫 시도에서만 막히고 재시도는 통과한다.
        """
        first = _run_hook(repo, _push())
        second = _run_hook(repo, _push())
        assert first.returncode == 2
        assert second.returncode == 2, "재시도가 통과한다 — 차단이 고지의 중복 억제를 따르고 있다"
        assert _stderr(second), "재시도 차단에도 이유가 있어야 한다(침묵 거부 금지)"

    def test_mirror_that_ran_only_some_always_jobs_is_refused(self, repo: Path) -> None:
        """미러가 이 커밋에 대해 통과였어도 **상시 잡 일부만** 돌렸다면 돌리지 않은 잡은 측정되지 않았다."""
        required = _required(repo)
        _mirror(repo, _head(repo), jobs=[_job("harness-integrity")])
        proc = _run_hook(repo, _push())
        assert proc.returncode == 2
        message = _stderr(proc)
        for name in required:
            if name != "harness-integrity":
                assert name in message, f"돌지 않은 상시 잡 {name}이 이유에 없다"


# ═════════════════════════════════════════════════════════════════════════════
# ③ 변별력 — 차단 쪽
# ═════════════════════════════════════════════════════════════════════════════
class TestBlocks:
    def test_no_result_blocks(self, repo: Path) -> None:
        proc = _run_hook(repo, _push())
        assert proc.returncode == 2
        (row,) = _log_rows(repo)
        assert row["code"] == "no_result" and row["blocked"] is True

    def test_failed_mirror_of_the_same_commit_blocks(self, repo: Path) -> None:
        jobs = [_job(name) for name in _required(repo)]
        jobs[0] = _job(jobs[0]["name"], exit_code=1, steps=[{"name": "s", "status": "failed"}])
        _mirror(repo, _head(repo), jobs=jobs, exit_code=1)
        proc = _run_hook(repo, _push())
        assert proc.returncode == 2
        assert "실패" in _stderr(proc)

    def test_polluted_result_blocks(self, repo: Path) -> None:
        """실행 도중 트리가 바뀐 결과(`tainted`)는 어느 상태의 측정도 아니다 — 통과 취급 금지."""
        _mirror(repo, _head(repo), tainted=True)
        assert _run_hook(repo, _push()).returncode == 2

    def test_job_without_any_passed_step_counts_as_not_run(self, repo: Path) -> None:
        """통과한 스텝이 하나도 없는 잡 기록은 그 잡이 돈 증거가 아니다(스캔 0건은 통과가 아니다)."""
        jobs = [_job(name) for name in _required(repo)]
        jobs[0] = _job(
            jobs[0]["name"],
            steps=[{"name": "Checkout", "status": "not_runnable", "reason": "액션 스텝"}],
        )
        _mirror(repo, _head(repo), jobs=jobs)
        proc = _run_hook(repo, _push())
        assert proc.returncode == 2 and jobs[0]["name"] in _stderr(proc)

    def test_docs_only_branch_without_a_mirror_blocks(self, repo: Path) -> None:
        """반대 대조군 — 문서는 면제하지 않는다(런북 한 장이 상시 잡 infra-shell을 깬 실측 2026-10-07)."""
        _git(repo, "reset", "-q", "--hard", "origin/main")
        _commit(repo, "docs/guide.md", "guide v2\n")
        assert _run_hook(repo, _push()).returncode == 2

    def test_compound_commit_and_push_with_substantive_changes_blocks(self, repo: Path) -> None:
        """아직 없는 커밋은 미러를 거칠 수 없다 — 같은 명령이 만드는 커밋의 푸시는 거부."""
        _mirror(repo, _head(repo))
        _write(repo, "src/new_module.py", "z = 1\n")
        proc = _run_hook(repo, _push('git add -A && git commit -m "x" && git push'))
        assert proc.returncode == 2

    def test_refusal_is_logged_for_the_habituation_audit(self, repo: Path) -> None:
        """거부도 평가 한 건이다 — 차단 비율이 우회 습관화 감시(판정 문서 §6)의 입력이다."""
        _run_hook(repo, _push())
        _run_hook(repo, _push())
        rows = _log_rows(repo)
        assert [(r["trigger"], r["blocked"], r["notified"]) for r in rows] == [
            ("git_push", True, False),
            ("git_push", True, False),
        ]


# ═════════════════════════════════════════════════════════════════════════════
# ③ 변별력 — 허용 쪽 (대조군: 없으면 "전부 차단"이 초록이 된다)
# ═════════════════════════════════════════════════════════════════════════════
class TestAllows:
    def test_full_always_job_coverage_for_head_allows(self, repo: Path) -> None:
        _mirror(repo, _head(repo))
        proc = _run_hook(repo, _push())
        assert proc.returncode == 0 and proc.stdout == b"" and proc.stderr == b""
        (row,) = _log_rows(repo)
        assert row["code"] == "mirror_pass" and row["blocked"] is False

    def test_extra_path_jobs_in_the_result_do_not_hurt(self, repo: Path) -> None:
        jobs = [_job(name) for name in _required(repo)] + [_job("backend")]
        _mirror(repo, _head(repo), jobs=jobs)
        assert _run_hook(repo, _push()).returncode == 0

    def test_not_executed_steps_still_allow(self, repo: Path) -> None:
        """미실행 스텝은 허용(HARN-181 전 — 조건 스텝 잡은 항상 미실행이라 막으면 영구 차단)."""
        jobs = [_job(name) for name in _required(repo)]
        jobs[0]["steps"].append(
            {"name": "if 스텝", "status": "not_executed", "reason": "조건 스텝"}
        )
        _mirror(repo, _head(repo), jobs=jobs, exit_code=ci_mirror.EXIT_NOT_EXECUTED)
        proc = _run_hook(repo, _push())
        assert proc.returncode == 0

    def test_ledger_commit_after_a_full_mirror_allows(self, repo: Path) -> None:
        """면제 B — 미러 통과 뒤 `done`의 대장 커밋만 더한 푸시는 가장 흔한 형태다."""
        _mirror(repo, _head(repo))
        _commit(repo, "backlog/events/s.ndjson", '{"a": 1}\n{"done": true}\n')
        assert _run_hook(repo, _push()).returncode == 0

    def test_ledger_only_branch_allows_without_any_mirror(self, repo: Path) -> None:
        """면제 A — 대장 기록만 바뀐 푸시는 미러가 없어도 허용."""
        _git(repo, "reset", "-q", "--hard", "origin/main")
        _commit(repo, "backlog/events/s.ndjson", '{"a": 1}\n{"b": 2}\n')
        assert _run_hook(repo, _push()).returncode == 0

    def test_code_change_after_the_mirror_still_blocks(self, repo: Path) -> None:
        """면제 B의 blob 비교 — 미러 뒤 코드를 바꿨다면 그 내용은 측정되지 않았다."""
        _mirror(repo, _head(repo))
        _commit(repo, "src/app.py", "a = 3  # 미러 뒤에 바꿨다\n")
        assert _run_hook(repo, _push()).returncode == 2

    def test_compound_with_ledger_only_pending_changes_allows(self, repo: Path) -> None:
        _mirror(repo, _head(repo))
        _write(repo, "backlog/events/s.ndjson", '{"a": 1}\n{"x": 1}\n')
        proc = _run_hook(repo, _push('git add -A && git commit -m "ledger" && git push'))
        assert proc.returncode == 0

    @pytest.mark.parametrize(
        "command",
        [
            "git push --dry-run origin feature",
            "git push origin --delete feature",
            "git push origin other:other",
            "git push --tags",
            "git -C /elsewhere push",
        ],
    )
    def test_push_forms_that_are_not_evaluated_are_not_blocked(
        self, repo: Path, command: str
    ) -> None:
        """평가 대상이 아닌 형태(HARN-209 한계)는 차단도 하지 않는다 — 판정 못 한 것을 막지 않는다."""
        assert _run_hook(repo, _push(command)).returncode == 0

    def test_pr_creation_is_never_blocked(self, repo: Path) -> None:
        """PR 생성 훅은 고지 전용이다 — 푸시가 이미 이 게이트를 지나왔다."""
        event = {
            "tool_name": _PR_TOOL,
            "tool_input": {"head": "feature", "base": "main", "title": "t", "body": "요약만"},
        }
        proc = _run_hook(repo, event)
        assert proc.returncode == 0
        context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "[CI 미러 고지 · PR 생성 직전]" in context

    def test_unrelated_bash_is_not_evaluated(self, repo: Path) -> None:
        proc = _run_hook(repo, _push("ls -la"))
        assert proc.returncode == 0 and _log_rows(repo) == []


class TestUnavailableDoesNotBlock:
    """측정 불가는 막지 않는다 — 훅이나 저장소 상태 고장이 모든 푸시를 막으면 사람이 훅을 끈다."""

    def test_unavailable_assessment_is_allowed_but_named(self, repo: Path) -> None:
        gate = pmn.push_gate(repo, pmn.Assessment(pmn.NOTIFY_UNAVAILABLE, error_type="OSError"))
        assert gate.outcome == pmn.GATE_ALLOW and gate.code == pmn.NOTIFY_UNAVAILABLE

    def test_unknown_required_jobs_does_not_turn_a_good_mirror_into_a_block(
        self, repo: Path
    ) -> None:
        """워크플로를 못 읽어 필수 잡을 모르면 그 축만 건너뛴다(결과 존재·실패 축은 그대로)."""
        head = _head(repo)
        _mirror(repo, head, jobs=[_job("harness-integrity")])
        (repo / ".github" / "workflows" / "ci.yml").write_text("::: 깨진 yaml [", encoding="utf-8")
        assessment = pmn.assess(repo)
        gate = pmn.push_gate(repo, assessment)
        assert gate.outcome == pmn.GATE_ALLOW and gate.required_error is not None


# ═════════════════════════════════════════════════════════════════════════════
# ② 우회 — 사유 필수, 대장에 기록, 내용 한정
# ═════════════════════════════════════════════════════════════════════════════
class TestWaiver:
    def test_blank_reason_is_rejected_and_writes_nothing(self, repo: Path) -> None:
        for reason in ("", "   ", "\t\n"):
            proc = _waive(repo, reason)
            assert proc.returncode != 0, f"무사유 면제가 통과했다: {reason!r}"
        assert _waiver_events(repo) == []
        assert _run_hook(repo, _push()).returncode == 2, "거부된 면제가 푸시를 열었다"

    def test_waiver_records_a_ledger_event_and_opens_that_head(self, repo: Path) -> None:
        proc = _waive(repo, "컨테이너에 Docker가 없어 infra-contracts를 로컬에서 못 돌린다")
        assert proc.returncode == 0, proc.stderr
        (event,) = _waiver_events(repo)
        assert event["head"] == _head(repo)
        assert "Docker" in event["reason"] and event["actor"] == "feature"
        assert event["code"] == "no_result"
        push = _run_hook(repo, _push())
        assert push.returncode == 0, _stderr(push)
        assert [r["gate"] for r in _log_rows(repo)] == ["waived"]

    def test_waiver_does_not_cover_new_code(self, repo: Path) -> None:
        """한 번의 우회가 이후 모든 푸시를 면제하면 탈출구가 게이트를 끄는 것과 같다."""
        assert _waive(repo, "사유").returncode == 0
        _commit(repo, "src/other.py", "y = 1\n")
        assert _run_hook(repo, _push()).returncode == 2

    def test_waiver_survives_a_ledger_only_follow_up_commit(self, repo: Path) -> None:
        """같은 기여(대장 기록만 더함)는 같은 내용이다 — 우회한 푸시 뒤 `done` 대장 커밋이 다시 막히면 안 된다."""
        assert _waive(repo, "사유").returncode == 0
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "ledger")  # 우회 이벤트가 든 대장 파일 커밋
        assert _run_hook(repo, _push()).returncode == 0

    def test_hand_written_waiver_without_a_reason_is_not_honored(self, repo: Path) -> None:
        """대장에 사유 없는 이벤트를 수기로 넣어도 열리지 않는다(손편집 우회 방지)."""
        events = repo / "backlog" / "events" / "feature.ndjson"
        events.parent.mkdir(parents=True, exist_ok=True)
        record = {"action": pmn.WAIVER_ACTION, "head": _head(repo), "reason": "  "}
        events.write_text(json.dumps(record) + "\n", encoding="utf-8")
        assert _run_hook(repo, _push()).returncode == 2

    def test_lookup_ignores_a_blank_reason_record_itself(self, repo: Path) -> None:
        """조회 함수 수준의 반례 — 빈 사유 기록이 `""`로 반환되면 호출측의 거짓 판정에만 기대게 된다."""
        events = repo / "backlog" / "events" / "feature.ndjson"
        events.parent.mkdir(parents=True, exist_ok=True)
        record = {"action": pmn.WAIVER_ACTION, "head": _head(repo), "reason": "  "}
        events.write_text(json.dumps(record) + "\n", encoding="utf-8")
        assert pmn.find_waiver(repo, _head(repo)) == (None, None)

    def test_waiver_of_another_branch_is_not_honored(self, repo: Path) -> None:
        events = repo / "backlog" / "events" / "someone-else.ndjson"
        events.parent.mkdir(parents=True, exist_ok=True)
        record = {"action": pmn.WAIVER_ACTION, "head": _head(repo), "reason": "남의 사유"}
        events.write_text(json.dumps(record) + "\n", encoding="utf-8")
        assert _run_hook(repo, _push()).returncode == 2

    def test_waiver_does_not_open_a_compound_push_that_makes_the_commit(self, repo: Path) -> None:
        """우회는 이미 있는 HEAD에 대한 것이다 — 아직 없는 커밋은 우회할 대상이 없다."""
        assert _waive(repo, "사유").returncode == 0
        _write(repo, "src/new_module.py", "z = 1\n")
        proc = _run_hook(repo, _push('git add -A && git commit -m "x" && git push'))
        assert proc.returncode == 2


# ═════════════════════════════════════════════════════════════════════════════
# 구조·배선 동결
# ═════════════════════════════════════════════════════════════════════════════
def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} 없음")


def _called_names(func: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Attribute):
                names.add(target.attr)
    return names


class TestStructure:
    # 종료 코드 {0, 2}·권한 필드 부재의 동결은 test_push_mirror_notice_wiring.py가 맡는다(옛 never-blocks 자리).

    def test_call_chain_reaches_the_gate_and_the_waiver_lookup(self) -> None:
        module = ast.parse(_MODULE.read_text(encoding="utf-8"))
        assert "push_gate" in _called_names(_function(module, "notice_for_push"))
        gate_calls = _called_names(_function(module, "push_gate"))
        assert {"find_waiver", "jobs_missing", "required_always_jobs"} <= gate_calls
        assert "push_gate" not in _called_names(_function(module, "notice_for_pr_create"))

    def test_refusal_text_survives_a_cp949_console(self, repo: Path) -> None:
        """exit 2의 이유는 stderr 바이트로 도구에 전달된다 — 로캘(cp949) 인코딩으로 쓰면 깨진다."""
        proc = _run_hook(repo, _push(), env_extra={"PYTHONIOENCODING": "cp949", "PYTHONUTF8": "0"})
        assert proc.returncode == 2
        assert "푸시" in proc.stderr.decode("utf-8")  # UTF-8 바이트가 아니면 UnicodeDecodeError

    def test_log_never_contains_the_command_text_or_the_waiver_reason(self, repo: Path) -> None:
        secret = "TOKEN-되면-안-남는-값"
        _run_hook(repo, _push(f"git push https://x:{secret}@example.com/r.git"))
        log = (repo / ".claude" / "logs" / "push_mirror_notices.jsonl").read_text(encoding="utf-8")
        assert secret not in log and "example.com" not in log


# ═════════════════════════════════════════════════════════════════════════════
# 절별 반례 — 그 절이 없으면 통과해 버리는 입력 (뮤테이션 검증에서 보강)
# ═════════════════════════════════════════════════════════════════════════════
class TestJobCoverageOnEveryMirroredPath:
    """잡 구성 검사는 통과로 읽히는 **세 경로 모두**에서 선다 — 한 경로만 검사하면 나머지가 구멍이다."""

    def test_partial_jobs_with_not_executed_steps_still_block(self, repo: Path) -> None:
        jobs = [_job("harness-integrity")]
        jobs[0]["steps"].append({"name": "if 스텝", "status": "not_executed", "reason": "조건"})
        _mirror(repo, _head(repo), jobs=jobs, exit_code=ci_mirror.EXIT_NOT_EXECUTED)
        assert pmn.assess(repo).code == pmn.SILENT_NOT_EXECUTED  # 판정 전제: 미실행 경로
        assert _run_hook(repo, _push()).returncode == 2

    def test_partial_jobs_followed_by_a_ledger_commit_still_block(self, repo: Path) -> None:
        """면제 B(같은 기여) 경로 — 일부 잡만 돈 결과가 대장 커밋 하나로 세탁되면 안 된다."""
        _mirror(repo, _head(repo), jobs=[_job("harness-integrity")])
        _commit(repo, "backlog/events/s.ndjson", '{"a": 1}\n{"done": true}\n')
        assert pmn.assess(repo).code == pmn.SILENT_SAME_CONTRIBUTION  # 판정 전제
        assert _run_hook(repo, _push()).returncode == 2


class TestJobsMissingUnit:
    """`jobs_missing`을 직접 — 훅 경로에서는 다른 절이 먼저 막아 보이지 않는 분기까지."""

    def test_job_with_nonzero_exit_is_not_evidence(self) -> None:
        payload = {"jobs": [_job("a", exit_code=1)]}
        assert pmn.jobs_missing(payload, ["a"]) == ("a",)

    def test_job_without_passed_step_is_not_evidence(self) -> None:
        payload = {"jobs": [_job("a", steps=[{"name": "s", "status": "not_executed"}])]}
        assert pmn.jobs_missing(payload, ["a"]) == ("a",)

    def test_malformed_payload_means_nothing_ran(self) -> None:
        for payload in (None, {}, {"jobs": "x"}, {"jobs": [None, 3, {"name": "a"}]}):
            assert pmn.jobs_missing(payload, ["a"]) == ("a",)

    def test_passing_job_and_extra_jobs_are_fine_and_order_follows_required(self) -> None:
        payload = {"jobs": [_job("b"), _job("a"), _job("extra")]}
        assert pmn.jobs_missing(payload, ["a", "b", "c"]) == ("c",)


class TestWaiveRefusals:
    def test_waive_refuses_when_nothing_is_blocked(self, repo: Path) -> None:
        """차단 대상이 아닌 HEAD에는 우회를 기록하지 않는다 — 쓸모없는 이벤트가 감시 신호를 흐린다."""
        _mirror(repo, _head(repo))
        proc = _waive(repo, "미리 열어 둔다")
        assert proc.returncode != 0 and _waiver_events(repo) == []

    def test_second_waive_for_the_same_content_is_refused(self, repo: Path) -> None:
        assert _waive(repo, "첫 사유").returncode == 0
        again = _waive(repo, "두 번째 사유")
        assert again.returncode != 0 and len(_waiver_events(repo)) == 1
        # 거부 이유가 "이미 우회됨"이어야 한다 — "차단 대상이 아님"으로 읽히면 처방(다시 푸시)이 틀린다.
        assert "이미 우회" in again.stderr

    def test_waive_cannot_target_a_commit_that_does_not_exist_yet(self, repo: Path) -> None:
        _write(repo, "src/new_module.py", "z = 1\n")
        assessment = pmn.assess(repo, head_moves=True)
        assert assessment.code == pmn.NOTIFY_HEAD_MOVES
        gate = pmn.push_gate(repo, assessment)
        assert gate.blocked and gate.waiver_reason is None


class TestRequiredJobsScan:
    def test_workflow_without_any_always_job_is_a_scan_failure_not_an_empty_requirement(
        self, tmp_path: Path
    ) -> None:
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(
            "name: x\non: pull_request\njobs:\n  nightly:\n    runs-on: x\n"
            "    if: github.event_name == 'schedule'\n    steps: []\n",
            encoding="utf-8",
        )
        assert pmn.required_always_jobs(tmp_path) == ((), "EmptyAlwaysJobScan")

    def test_repository_without_a_workflow_requires_nothing(self, tmp_path: Path) -> None:
        assert pmn.required_always_jobs(tmp_path) == ((), None)
