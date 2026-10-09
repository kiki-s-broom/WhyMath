"""푸시·PR 생성 시점 CI 미러 고지 (HARN-209) — 판정 로직과 PR 본문 섹션의 동결.

왜 이 파일이 있는가: `done`의 미러 게이트(HARN-173)는 완료 선언 시점에만 서서 red 푸시를 못 막았다
(2026-09-25 EOS-24 · PR #1316). 정본 판정은 `docs/reviews/harn209_push_time_mirror_notice_judgment_2026-10-08.md`
이고, 이 파일은 그 판정이 **문서가 아니라 코드로 집행되는지**를 셀 단위로 동결한다. 훅 배선은
`test_push_mirror_notice_wiring.py`가 맡는다.

각 절마다 "그 절이 없으면 통과해 버리는 반례"를 픽스처로 둔다 (이름이 의도를 말한다고 코드가 그 의도를
실행하는 것은 아니다):

  절                                  그 절이 없으면 통과해 버리는 반례
  ──────────────────────────────────────────────────────────────────────────────────────────
  미러 결과 없음 → 고지               결과 파일 없는 코드 푸시가 침묵
  다른 커밋의 결과 → 고지             옛 커밋의 통과 결과가 새 커밋을 통과시킴
  같은 커밋 통과 → 침묵(대조군)       모든 푸시에 고지 — 상시 경고로 습관화
  실패 결과 → 고지                    fail이 침묵
  미실행 → 침묵                       조건 스텝 잡을 건드리는 모든 푸시에 고지(HARN-181 전)
  면제 A 대장 기록만                  `done` 뒤 대장 커밋 푸시마다 고지
  문서만 → 고지(반대 대조군)          문서가 면제 — 런북 한 장이 infra-shell을 깬 실측(2026-10-07)을 놓침
  면제 B 미러 뒤 대장만 추가          미러 통과 뒤 대장 커밋 푸시마다 고지
  면제 B의 blob 비교                  같은 경로를 다른 내용으로 고쳐도 면제
  면제 B 병합만                       미러 뒤 `origin/main` 병합 푸시마다 고지
  면제 B의 이전 결과 상태             실패로 측정된 내용이 대장 커밋 뒤 면제됨
  복합 명령 보정                      `commit && push`가 커밋 전 HEAD의 통과 결과로 침묵
  푸시 형태 분류                      삭제·dry-run·다른 refspec에 고지
  PR 본문 섹션                        본문에 도달 잡이 없어도 침묵
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import ci_mirror
import push_mirror_notice as pmn
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="실제 git이 필요하다")


# ── 픽스처: 실제 git 저장소 ──────────────────────────────────────────────────
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
    """`origin/main` 참조가 있고 `feature` 브랜치에 올라 있는 저장소 (기여 = feature가 더한 것)."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _write(root, ".gitignore", ".claude/cache/\n.claude/logs/\n")
    _write(root, "README.md", "base\n")
    _write(root, "docs/guide.md", "guide\n")
    _write(root, "src/app.py", "a = 1\nb = 2\nc = 3\n")
    _write(root, "backlog/events/s.ndjson", '{"a": 1}\n')
    _write(root, "backlog/tasks/T-1.yaml", "id: T-1\n")
    if _REAL_CI.exists():
        _write(root, ".github/workflows/ci.yml", _REAL_CI.read_text(encoding="utf-8"))
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(root, "checkout", "-q", "-b", "feature")
    return root


def _mirror(repo: Path, commit: str, kind: str = "pass") -> None:
    """`.claude/cache/ci_mirror.json`에 해당 커밋의 미러 결과를 쓴다."""
    step = {"name": "s", "status": "passed", "reason": ""}
    exit_code = 0
    job_exit = 0
    if kind == "fail":
        step = {"name": "s", "status": "failed", "reason": ""}
        exit_code = job_exit = 1
    elif kind == "not_executed":
        step = {"name": "s", "status": "not_executed", "reason": "조건 스텝"}
        exit_code = ci_mirror.EXIT_NOT_EXECUTED
    payload = {
        "schema": ci_mirror.RESULT_SCHEMA,
        "commit": commit,
        "jobs": [{"name": "harness-integrity", "exit": job_exit, "steps": [step]}],
        "not_executed": 1 if kind == "not_executed" else 0,
        "exit": exit_code,
        "tainted": False,  # schema 3(HARN-194): 실행 도중 트리가 안 바뀌었다고 명시된 결과만 믿는다
    }
    path = repo / ci_mirror.DEFAULT_RESULT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


# ── 판정: 미러 결과 대조 (acceptance ③ 픽스처 3종 + 대조군) ───────────────────────
class TestMirrorComparison:
    def test_no_result_notifies(self, repo: Path) -> None:
        """미러 결과 없음 — 코드 푸시는 고지."""
        _commit(repo, "src/app.py", "x = 2\n")
        a = pmn.assess(repo)
        assert a.code == pmn.NOTIFY_NO_RESULT and a.notify
        assert a.mirror_state == pmn.STATE_UNKNOWN and a.changed == 1

    def test_result_of_another_commit_notifies(self, repo: Path) -> None:
        """다른 커밋의 결과 — 옛 통과 결과가 새 내용을 통과시키면 안 된다."""
        old = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, old)
        _commit(repo, "src/other.py", "y = 1\n")  # 내용이 달라졌다
        a = pmn.assess(repo)
        assert a.code == pmn.NOTIFY_OTHER_COMMIT and a.notify
        assert a.mirror_commit == old

    def test_result_of_the_same_commit_is_silent_control(self, repo: Path) -> None:
        """대조군 — 같은 커밋의 통과 결과면 고지 없음(모든 푸시에 고지하면 습관화된다)."""
        head = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, head)
        a = pmn.assess(repo)
        assert a.code == pmn.SILENT_PASS and not a.notify
        assert a.mirror_state == pmn.STATE_PASS

    def test_failed_result_of_the_same_commit_notifies(self, repo: Path) -> None:
        head = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, head, "fail")
        a = pmn.assess(repo)
        assert a.code == pmn.NOTIFY_FAILED and a.mirror_state == pmn.STATE_FAIL

    def test_not_executed_is_silent(self, repo: Path) -> None:
        """미실행은 `done` 게이트처럼 고지하지 않는다 — 조건 스텝 잡은 HARN-181 전까지 항상 exit 3."""
        head = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, head, "not_executed")
        a = pmn.assess(repo)
        assert a.code == pmn.SILENT_NOT_EXECUTED and not a.notify

    def test_unusable_result_for_this_commit_notifies(self, repo: Path) -> None:
        """커밋은 맞지만 잡이 0건인 결과 — 스캔 0건은 통과가 아니다."""
        head = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, head)
        path = repo / ci_mirror.DEFAULT_RESULT_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["jobs"] = []
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert pmn.assess(repo).code == pmn.NOTIFY_RESULT_UNUSABLE

    @pytest.mark.parametrize("tainted", [True, None, "false"])
    def test_result_not_proven_stable_is_not_a_measurement(self, repo: Path, tainted) -> None:
        """schema 3(HARN-194) — `tainted`가 명시적 False가 아닌 결과(오염·미확인·모양 이탈)는 통과가 아니다."""
        head = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, head)
        path = repo / ci_mirror.DEFAULT_RESULT_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["tainted"] = tainted
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert pmn.assess(repo).code == pmn.NOTIFY_RESULT_UNUSABLE

    def test_result_without_the_stability_flag_is_not_a_measurement(self, repo: Path) -> None:
        head = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, head)
        path = repo / ci_mirror.DEFAULT_RESULT_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        del payload["tainted"]
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert pmn.assess(repo).code == pmn.NOTIFY_RESULT_UNUSABLE


# ── 판정: 면제 (코드 없는 푸시를 가려내는 방법) ───────────────────────────────────
class TestExemptions:
    def test_ledger_only_branch_is_silent_even_without_a_result(self, repo: Path) -> None:
        """면제 A — 대장 기록만 바뀐 푸시는 미러 결과가 없어도 침묵."""
        _commit(repo, "backlog/events/s.ndjson", '{"a": 1}\n{"a": 2}\n')
        _commit(repo, "backlog/tasks/T-1.yaml", "id: T-1\nstatus: done\n")
        a = pmn.assess(repo)
        assert a.code == pmn.SILENT_BOOKKEEPING_ONLY and not a.notify

    def test_docs_only_branch_still_notifies(self, repo: Path) -> None:
        """반대 대조군 — 문서는 면제하지 않는다(런북 한 장이 상시 잡 infra-shell을 깬 실측)."""
        _commit(repo, "docs/guide.md", "guide v2\n")
        assert pmn.assess(repo).code == pmn.NOTIFY_NO_RESULT

    def test_ledger_commit_after_a_passing_mirror_is_silent(self, repo: Path) -> None:
        """면제 B — 미러 통과 뒤 `done`의 대장 커밋을 푸시해도 고지하지 않는다(가장 흔한 형태)."""
        mirrored = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, mirrored)
        _commit(repo, "backlog/events/s.ndjson", '{"a": 1}\n{"done": true}\n')
        a = pmn.assess(repo)
        assert a.code == pmn.SILENT_SAME_CONTRIBUTION and not a.notify
        assert a.mirror_commit == mirrored and a.head != mirrored

    def test_same_path_with_different_content_is_not_exempt(self, repo: Path) -> None:
        """면제 B의 blob 비교 — 경로 집합이 같아도 내용이 다르면 미러가 본 것이 아니다."""
        mirrored = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, mirrored)
        _commit(repo, "src/app.py", "x = 3  # 미러 뒤에 바꿨다\n")
        a = pmn.assess(repo)
        assert a.code == pmn.NOTIFY_OTHER_COMMIT

    def test_new_code_file_after_the_mirror_is_not_exempt(self, repo: Path) -> None:
        mirrored = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, mirrored)
        _commit(repo, "src/extra.py", "z = 1\n")
        assert pmn.assess(repo).code == pmn.NOTIFY_OTHER_COMMIT

    def test_merge_of_trunk_only_is_silent(self, repo: Path) -> None:
        """면제 B — 미러 뒤 `origin/main`을 병합만 한 푸시. 브랜치 자체 기여가 그대로라 침묵."""
        mirrored = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, mirrored)
        _git(repo, "checkout", "-q", "main")
        _commit(repo, "README.md", "base v2 — main이 앞서갔다\n")
        _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        _git(repo, "checkout", "-q", "feature")
        _git(repo, "merge", "-q", "--no-edit", "main")
        a = pmn.assess(repo)
        assert a.head != mirrored
        assert a.code == pmn.SILENT_SAME_CONTRIBUTION and not a.notify

    def test_merge_that_changes_the_branch_contribution_notifies(self, repo: Path) -> None:
        """병합이 브랜치가 건드린 파일의 내용을 바꾸면(main이 같은 파일의 다른 줄을 고침) 고지."""
        mirrored = _commit(repo, "src/app.py", "a = 10\nb = 2\nc = 3\n")
        _mirror(repo, mirrored)
        _git(repo, "checkout", "-q", "main")
        _commit(repo, "src/app.py", "a = 1\nb = 2\nc = 30\n")  # main이 같은 파일의 다른 줄을 고쳤다
        _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        _git(repo, "checkout", "-q", "feature")
        _git(repo, "merge", "-q", "--no-edit", "main")  # 충돌 없이 합쳐진다(실패하면 픽스처 오류)
        assert (repo / "src/app.py").read_text(encoding="utf-8") == "a = 10\nb = 2\nc = 30\n"
        assert pmn.assess(repo).code == pmn.NOTIFY_OTHER_COMMIT

    def test_content_already_measured_as_failed_still_notifies(self, repo: Path) -> None:
        """면제 B의 이전 결과 상태 — 실패로 측정된 내용은 대장 커밋 뒤에도 고지(미측정과 다른 사유)."""
        mirrored = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, mirrored, "fail")
        _commit(repo, "backlog/events/s.ndjson", '{"a": 1}\n{"done": true}\n')
        a = pmn.assess(repo)
        assert a.code == pmn.NOTIFY_FAILED and a.mirror_commit == mirrored

    def test_branch_equal_to_trunk_is_silent(self, repo: Path) -> None:
        """기여가 0건(트렁크로 되돌린 브랜치) — 알릴 것이 없다."""
        assert pmn.assess(repo).code == pmn.SILENT_NO_BRANCH_CHANGES


# ── 판정: 조회 실패는 침묵하지 않는다 ───────────────────────────────────────────
class TestUnavailable:
    def test_missing_trunk_ref_is_not_a_pass(self, repo: Path) -> None:
        """`origin/main`이 없으면 기여를 모른다 — 모른다를 면제로 접지 않는다."""
        _commit(repo, "src/app.py", "x = 2\n")
        a = pmn.assess(repo, base="origin/does-not-exist")
        assert a.code == pmn.NOTIFY_NO_RESULT and a.changed is None
        assert a.error_type == "GitQueryError"

    def test_missing_trunk_ref_with_passing_mirror_is_silent(self, repo: Path) -> None:
        """대조군 — 기여를 몰라도 같은 커밋의 통과 결과가 있으면 고지하지 않는다."""
        head = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, head)
        assert pmn.assess(repo, base="origin/does-not-exist").code == pmn.SILENT_PASS

    def test_not_a_repository_reports_unavailable_with_error_type(self, tmp_path: Path) -> None:
        a = pmn.assess(tmp_path / "nowhere")
        assert a.code == pmn.NOTIFY_UNAVAILABLE and a.notify
        assert a.error_type in {"FileNotFoundError", "NotADirectoryError", "GitQueryError"}


# ── 판정: 복합 명령(커밋과 푸시를 한 번에) ───────────────────────────────────────
class TestHeadMoves:
    def test_uncommitted_code_about_to_be_committed_notifies(self, repo: Path) -> None:
        """`commit && push` — 새 커밋에는 미러 결과가 있을 수 없다. 커밋 전 HEAD의 통과로 침묵하면 안 된다."""
        head = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, head)
        _write(repo, "src/new_module.py", "n = 1\n")  # 커밋되지 않은 코드
        a = pmn.assess(repo, head_moves=True)
        assert a.code == pmn.NOTIFY_HEAD_MOVES
        assert a.pending_substantive == ("src/new_module.py",)

    def test_without_head_moves_dirty_files_are_ignored(self, repo: Path) -> None:
        """대조군 — 푸시만 하는 명령이면 작업 트리의 미커밋 변경은 푸시되지 않는다."""
        head = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, head)
        _write(repo, "src/new_module.py", "n = 1\n")
        assert pmn.assess(repo, head_moves=False).code == pmn.SILENT_PASS

    def test_uncommitted_ledger_only_is_exempt(self, repo: Path) -> None:
        """`done` 뒤 `git add -A && git commit && git push` — 대장 기록만이면 면제 판정으로 이어진다."""
        head = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, head)
        _write(repo, "backlog/events/s.ndjson", '{"a": 1}\n{"done": true}\n')
        _write(repo, "backlog/tasks/T-1.yaml", "id: T-1\nstatus: done\n")
        assert pmn.assess(repo, head_moves=True).code == pmn.SILENT_PASS


# ── 푸시 계획 파싱 ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("command", "kind", "refspecs", "head_moves"),
    [
        ("git push", pmn.PLAN_PUSH, (), False),
        ("git push -u origin claude/feature", pmn.PLAN_PUSH, ("claude/feature",), False),
        ("GIT_SSH_COMMAND=ssh git push origin HEAD", pmn.PLAN_PUSH, ("HEAD",), False),
        ("git push -o ci.skip origin HEAD", pmn.PLAN_PUSH, ("HEAD",), False),
        ("git push --force-with-lease origin +HEAD:x", pmn.PLAN_PUSH, ("+HEAD:x",), False),
        ('git commit -m "msg push" && git push', pmn.PLAN_PUSH, (), True),
        ("git add -A && git commit -qm x && git push -u origin b", pmn.PLAN_PUSH, ("b",), True),
        ("git fetch && git push", pmn.PLAN_PUSH, (), False),
        ("git push origin :old-branch", pmn.PLAN_DELETE, (":old-branch",), False),
        ("git push --delete origin old", pmn.PLAN_DELETE, ("old",), False),
        ("git push --dry-run", pmn.PLAN_DRY_RUN, (), False),
        ("git push --tags", pmn.PLAN_TAGS_ONLY, (), False),
        ("git -C /elsewhere push", pmn.PLAN_OTHER_REPO, (), False),
        ("echo git push", pmn.PLAN_NOT_PUSH, (), False),
        ("grep -n push scripts/x.py", pmn.PLAN_NOT_PUSH, (), False),
        ("git status && git log", pmn.PLAN_NOT_PUSH, (), False),
        # 2026-10-08 실사용 반례: 단어에 붙은 `;`·리다이렉션이 실제 푸시를 놓치게 했다
        ("ls a b 2>&1 | head; git push -u origin x 2>&1 | tail -3", pmn.PLAN_PUSH, ("x",), False),
        ("git fetch; git commit -qm x; git push", pmn.PLAN_PUSH, (), True),
        ("git status&&git push origin HEAD", pmn.PLAN_PUSH, ("HEAD",), False),
        ("git add -A\ngit commit -m a\ngit push", pmn.PLAN_PUSH, (), True),
        ("git commit -m msg \\\n  && git push", pmn.PLAN_PUSH, (), True),
        ("(cd sub; git push)", pmn.PLAN_PUSH, (), False),
        # 줄 잇기가 인자로 새면 원격 이름이 refspec이 되어 HEAD 아닌 푸시로 오분류된다
        ("git push \\\n  origin", pmn.PLAN_PUSH, (), False),
        # 괄호가 구분자가 아니면 맨 앞 `(` 때문에 git이 명령 첫머리로 안 보인다
        ("(git push origin HEAD)", pmn.PLAN_PUSH, ("HEAD",), False),
        ("git push origin HEAD > out.txt 2>&1", pmn.PLAN_PUSH, ("HEAD",), False),
        ("git push 2>/dev/null", pmn.PLAN_PUSH, (), False),
        # 푸시처럼 보이지만 명령이 아닌 글귀
        ('echo "x; git push"', pmn.PLAN_NOT_PUSH, (), False),
        ("cat > f <<'EOF'\ngit push body line\nEOF\necho done", pmn.PLAN_NOT_PUSH, (), False),
        ("git commit -m 'a\ngit push'", pmn.PLAN_NOT_PUSH, (), False),
        ("git pull", pmn.PLAN_NOT_PUSH, (), False),
    ],
)
def test_plan_from_command(
    command: str, kind: str, refspecs: tuple[str, ...], head_moves: bool
) -> None:
    plan = pmn.plan_from_command(command)
    assert (plan.kind, plan.refspecs, plan.head_moves) == (kind, refspecs, head_moves)
    assert not plan.parse_failed


def test_unparsable_push_is_still_assumed_to_be_a_push() -> None:
    """따옴표가 깨진 명령을 '푸시 아님'으로 읽으면 이 훅이 조용히 꺼진 것과 같다."""
    plan = pmn.plan_from_command("git push origin 'unterminated")
    assert plan.kind == pmn.PLAN_PUSH and plan.parse_failed
    assert pmn.plan_from_command("echo 'unterminated").kind == pmn.PLAN_NOT_PUSH


@pytest.mark.parametrize(
    ("refspecs", "branch", "expected"),
    [
        ((), "feature", True),
        (("HEAD",), "feature", True),
        (("feature",), "feature", True),
        (("HEAD:refs/heads/other",), "feature", True),
        (("other:other",), "feature", False),
        (("other",), None, False),
        (("+feature:feature",), "feature", True),
    ],
)
def test_refspec_targets_head(
    refspecs: tuple[str, ...], branch: str | None, expected: bool
) -> None:
    assert pmn.refspec_targets_head(refspecs, branch) is expected


# ── 트리거별 진입점 ──────────────────────────────────────────────────────────────
class TestNoticeForPush:
    def test_notifies_with_mirror_command_and_reach(self, repo: Path) -> None:
        _commit(repo, "src/app.py", "x = 2\n")
        result = pmn.notice_for_push("git push -u origin feature", repo)
        assert result.text is not None
        assert "[CI 미러 고지 · 푸시 직전]" in result.text
        assert "ci_mirror.py run" in result.text and "막지 않는" in result.text
        assert result.assessment.code == pmn.NOTIFY_NO_RESULT

    def test_silent_when_mirrored(self, repo: Path) -> None:
        head = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, head)
        assert pmn.notice_for_push("git push origin feature", repo).text is None

    def test_not_a_push_is_silent_and_not_assessed(self, repo: Path) -> None:
        _commit(repo, "src/app.py", "x = 2\n")
        result = pmn.notice_for_push("git status", repo)
        assert result.text is None and result.assessment.code == pmn.SILENT_NOT_PUSH

    @pytest.mark.parametrize(
        "command",
        ["git push --dry-run", "git push origin :gone", "git push --tags", "git -C /x push"],
    )
    def test_unsupported_forms_are_silent(self, repo: Path, command: str) -> None:
        _commit(repo, "src/app.py", "x = 2\n")
        result = pmn.notice_for_push(command, repo)
        assert result.text is None and result.assessment.code == pmn.SILENT_UNSUPPORTED_FORM

    def test_push_of_another_ref_is_silent(self, repo: Path) -> None:
        """HEAD가 아닌 것을 푸시하는 명령 — 현재 HEAD의 미러 상태를 들이댈 이유가 없다."""
        _commit(repo, "src/app.py", "x = 2\n")
        result = pmn.notice_for_push("git push origin other-branch:other-branch", repo)
        assert result.text is None and result.assessment.code == pmn.SILENT_NON_HEAD_REF

    def test_commit_and_push_in_one_command_notifies(self, repo: Path) -> None:
        head = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, head)
        _write(repo, "src/new_module.py", "n = 1\n")
        result = pmn.notice_for_push('git add -A && git commit -m "x" && git push', repo)
        assert result.assessment.code == pmn.NOTIFY_HEAD_MOVES and result.text is not None

    def test_parse_failure_is_carried_to_the_result(self, repo: Path) -> None:
        _commit(repo, "src/app.py", "x = 2\n")
        assert pmn.notice_for_push("git push origin 'unterminated", repo).parse_failed


class TestNoticeForPrCreate:
    def test_missing_section_notifies_with_a_pasteable_block(self, repo: Path) -> None:
        head = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, head)
        result = pmn.notice_for_pr_create(repo, body="## 요약\n변경 설명", head_ref="feature")
        assert result.assessment.code == pmn.NOTIFY_BODY_MISSING
        assert result.text is not None
        assert pmn.SECTION_HEADING in result.text and pmn.SECTION_MARKER in result.text

    def test_body_with_the_marker_is_silent(self, repo: Path) -> None:
        """대조군 — 섹션이 이미 있으면 PR 생성마다 되풀이해 알리지 않는다."""
        head = _commit(repo, "src/app.py", "x = 2\n")
        _mirror(repo, head)
        body = f"요약\n\n{pmn.SECTION_HEADING}\n{pmn.SECTION_MARKER}\n- 상시 잡: ..."
        result = pmn.notice_for_pr_create(repo, body=body, head_ref="feature")
        assert result.text is None and result.assessment.code == pmn.SILENT_PASS

    def test_heading_alone_counts_as_a_section(self) -> None:
        assert pmn.body_has_section("x\n## CI 도달 잡\n- 잡")
        assert pmn.body_has_section(f"제목 없이 표지만\n{pmn.SECTION_MARKER}")
        assert not pmn.body_has_section("x\n본문에 CI 도달 잡이라는 말만 있다")
        assert not pmn.body_has_section(None) and not pmn.body_has_section("")

    def test_unmirrored_pr_notifies_once_with_the_block_but_no_duplicate_paste_request(
        self, repo: Path
    ) -> None:
        _commit(repo, "src/app.py", "x = 2\n")
        with_section = f"{pmn.SECTION_HEADING}\n{pmn.SECTION_MARKER}\n"
        result = pmn.notice_for_pr_create(repo, body=with_section, head_ref="feature")
        assert result.text is not None and "[CI 미러 고지 · PR 생성 직전]" in result.text
        assert (
            "붙여 넣으세요" not in result.text
        )  # 본문에 이미 있으니 붙일 블록을 또 요구하지 않는다
        without = pmn.notice_for_pr_create(repo, body="요약", head_ref="feature")
        assert without.text is not None and "붙여 넣으세요" in without.text

    def test_ledger_only_pr_does_not_require_the_section(self, repo: Path) -> None:
        """대조군 — 대장 기록만인 PR은 본문 섹션도 요구하지 않는다(푸시 고지와 같은 이유)."""
        _commit(repo, "backlog/tasks/T-1.yaml", "id: T-1\nstatus: done\n")
        result = pmn.notice_for_pr_create(repo, body="요약", head_ref="feature")
        assert result.text is None and result.assessment.code == pmn.SILENT_BOOKKEEPING_ONLY

    def test_pr_for_another_branch_is_not_assessed(self, repo: Path) -> None:
        _commit(repo, "src/app.py", "x = 2\n")
        result = pmn.notice_for_pr_create(repo, body="요약", head_ref="some-other-branch")
        assert result.text is None and result.assessment.code == pmn.SILENT_NON_HEAD_REF


# ── 도달 잡 (PR 본문 섹션의 내용) ─────────────────────────────────────────────────
@pytest.mark.skipif(not _REAL_CI.exists(), reason="ci.yml 없음")
class TestReach:
    def test_integration_marker_file_reaches_backend_migrations(self, repo: Path) -> None:
        """변별: `tests/backend/` 아래 파일 하나를 넣으면 `backend-migrations`가 목록에 나온다."""
        _commit(repo, "tests/backend/test_x_integration.py", "import pytest\n")
        reach = pmn.compute_reach(repo)
        assert reach.status == pmn.REACH_COMPUTED
        assert "backend-migrations" in reach.path_jobs
        assert dict(reach.irreproducible).get("backend-migrations"), "재현 불가 사유가 비었다"

    def test_docs_only_change_does_not_reach_backend_migrations(self, repo: Path) -> None:
        """대조군 — 문서만 바꾸면 경로 필터 잡이 없고 상시 잡만 남는다."""
        _commit(repo, "docs/guide.md", "guide v2\n")
        reach = pmn.compute_reach(repo)
        assert reach.status == pmn.REACH_COMPUTED
        assert "backend-migrations" not in reach.path_jobs and reach.path_jobs == ()
        assert "harness-integrity" in reach.always_jobs  # 상시 잡은 어떤 diff에도 닿는다

    def test_section_lists_jobs_and_marks_irreproducible_ones(self, repo: Path) -> None:
        head = _commit(repo, "tests/backend/test_x_integration.py", "import pytest\n")
        _mirror(repo, head)
        section = pmn.render_pr_section(pmn.compute_reach(repo), pmn.assess(repo))
        assert section.startswith(pmn.SECTION_HEADING) and pmn.SECTION_MARKER in section
        assert "backend-migrations" in section and "재현 불가" in section
        assert "harness-integrity" in section and "통과" in section

    def test_section_says_when_reach_could_not_be_computed(self, repo: Path) -> None:
        """계산 실패를 빈 섹션으로 위장하지 않는다 — 실패 사실과 예외 타입명을 적는다."""
        reach = pmn.Reach(pmn.REACH_FAILED, error_type="RuntimeError")
        section = pmn.render_pr_section(reach)
        assert "계산하지 못했다(RuntimeError)" in section and "상시 잡:" not in section

    def test_missing_workflow_is_reported_as_no_workflow(self, tmp_path: Path) -> None:
        root = tmp_path / "bare"
        root.mkdir()
        assert pmn.compute_reach(root).status == pmn.REACH_NO_WORKFLOW


# ── 조회 함수 단위 ───────────────────────────────────────────────────────────────
class TestContribution:
    def test_returns_new_blob_per_path_and_zero_id_for_deletion(self, repo: Path) -> None:
        _commit(repo, "src/app.py", "x = 2\n")
        _git(repo, "rm", "-q", "docs/guide.md")
        _git(repo, "commit", "-q", "-m", "rm")
        result = pmn.contribution(repo, "origin/main", "HEAD")
        assert set(result) == {"src/app.py", "docs/guide.md"}
        assert set(result["docs/guide.md"]) == {"0"}
        assert result["src/app.py"] == _git(repo, "rev-parse", "HEAD:src/app.py")

    def test_failure_raises_instead_of_returning_empty(self, repo: Path) -> None:
        with pytest.raises(pmn.GitQueryError):
            pmn.contribution(repo, "origin/nope", "HEAD")

    def test_pending_paths_covers_untracked_and_rename_target_only(self, repo: Path) -> None:
        _write(repo, "src/untracked.py", "u = 1\n")
        _git(repo, "mv", "docs/guide.md", "docs/guide2.md")
        paths = pmn.pending_paths(repo)
        # 목록 전체를 고정한다 — 원래 경로를 건너뛰지 않으면 `entry[3:]`가 잘린 문자열
        # (`s/guide.md`)을 하나 더 낳는데, `"docs/guide.md" not in paths` 같은 부정 단언은 그걸 못 본다.
        assert sorted(paths) == ["docs/guide2.md", "src/untracked.py"]


def test_bookkeeping_prefixes_are_exactly_the_ledger_paths() -> None:
    """면제 경로를 늘리는 변경은 이 동결을 깨뜨려 판정 문서(§4)를 다시 읽게 만든다."""
    assert pmn.BOOKKEEPING_PREFIXES == ("backlog/events/", "backlog/tasks/")
    assert pmn.is_bookkeeping("backlog/events/x.ndjson")
    assert not pmn.is_bookkeeping("docs/x.md") and not pmn.is_bookkeeping("backlog/gates.yaml")


def test_cli_pr_section_prints_a_section_for_the_given_root(repo: Path) -> None:
    head = _commit(repo, "tests/backend/test_x_integration.py", "import pytest\n")
    _mirror(repo, head)
    script = _REPO_ROOT / "scripts" / "harness" / "push_mirror_notice.py"
    proc = subprocess.run(
        ["python3", str(script), "pr-section", "--root", str(repo)],
        capture_output=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith(pmn.SECTION_HEADING)
    if _REAL_CI.exists():
        assert "backend-migrations" in proc.stdout
