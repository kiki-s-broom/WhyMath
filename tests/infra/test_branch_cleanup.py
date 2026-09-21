"""브랜치 정리 (HARN-01) 계약 — 스크립트를 **실제로 실행해** 판정한다.

이 잡은 3회 연속 red였고(run #7·#8·#9), 그 red는 실제 삭제 실패가 아니라 이미 삭제된
과거 배치를 재시도하며 난 잡음이었다. 상시 red는 신호를 습관화시켜 **진짜 실패를 같은 색에
묻는다**(CLAUDE.md "상시 실패하는 fail-open 보호를 '보호 있음'으로 신뢰 금지").

왜 문자열 검사가 아니라 실행인가: 쉘을 `"부재" in text`로 검사하면 **정확히 이 사고가
통과한다** — 원래 코드에도 부재 가드 문자열은 있었다. 없었던 것은 그 가드의 *발화*다
(`gh api`가 오류 본문을 stdout으로 뱉어 `[ -z "$sha" ]`가 한 번도 참이 되지 않았다).
그래서 `gh`를 스텁으로 갈아끼우고 **구성된 결과**(어떤 호출이 실제로 났는가·종료 코드가
무엇인가)를 본다. CLAUDE.md 2026-09-01 ①의 쉘 적용.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / ".github" / "scripts" / "branch_cleanup.sh"
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "branch-cleanup.yml"

# 실제 `gh`의 재현이 이 스텁의 핵심이다 — 특히 **오류 본문을 stdout으로 뱉는** 성질.
# 그 성질이 없으면 이 사고 자체가 재현되지 않아 모든 테스트가 공허하게 통과한다.
_STUB_GH = r"""#!/usr/bin/env python3
import json, os, sys

args = sys.argv[1:]
refs = json.loads(os.environ.get("STUB_REFS", "{}"))       # 브랜치 -> sha (또는 특수값)
undeletable = set(json.loads(os.environ.get("STUB_UNDELETABLE", "[]")))

def record(line):
    with open(os.environ["STUB_CALLS"], "a", encoding="utf-8") as fh:
        fh.write(line + "\n")

# 삭제:  gh api -X DELETE repos/<repo>/git/refs/heads/<branch>
if args[:2] == ["api", "-X"] and args[2] == "DELETE":
    target = args[3]
    branch = target.split("/git/refs/heads/", 1)[1]
    record("DELETE " + branch)
    if branch in undeletable:
        # 보호 브랜치 등 — gh는 오류 본문을 stdout으로 낸다.
        sys.stdout.write('{"message":"Reference cannot be deleted","status":"422"}')
        sys.exit(1)
    sys.exit(0)

# 스냅샷 조회: gh api repos/<repo>/git/ref/heads/<branch> --jq .object.sha
if args[:1] == ["api"]:
    target = args[1]
    branch = target.split("/git/ref/heads/", 1)[-1]
    record("GET " + branch)

    # 조회 실패 모드 주입 — 404가 아닌 실패(인증·rate limit·5xx)를 재현한다.
    # 실제 gh는 이때도 non-zero로 끝나므로, "비-0 = 부재"로 접으면 여기서 뚫린다.
    mode = os.environ.get("STUB_LOOKUP_FAILURE", "")
    if mode == "auth":
        # gh help exit-codes: 4 = 인증 필요. stderr에 HTTP 상태가 **없다**.
        sys.stderr.write(
            "gh: To use GitHub CLI in a GitHub Actions workflow, "
            "set the GH_TOKEN environment variable.\n"
        )
        sys.exit(4)
    if mode == "ratelimit":
        sys.stdout.write('{"message":"API rate limit exceeded","status":"403"}')
        sys.stderr.write("gh: API rate limit exceeded (HTTP 403)\n")
        sys.exit(1)
    if mode == "server":
        sys.stdout.write('{"message":"Server Error","status":"500"}')
        sys.stderr.write("gh: Server Error (HTTP 500)\n")
        sys.exit(1)

    if branch not in refs:
        # 실제 gh의 결정적 성질 둘 다 재현한다:
        #   ⓐ 오류 응답 **본문을 stdout으로** 뱉는다 — `--jq`도 `2>/dev/null`도 못 막는다.
        #     이것이 HARN-01의 원래 원인이다(부재 가드가 발화하지 못했다).
        #   ⓑ HTTP 상태를 담은 요약을 **stderr로** 낸다 — 404와 그 밖의 실패를 가르는
        #     유일한 재료이며, `2>/dev/null`은 이것을 버린다.
        sys.stdout.write(
            '{"message":"Not Found","documentation_url":"https://docs.github.com/rest","status":"404"}'
        )
        sys.stderr.write("gh: Not Found (HTTP 404)\n")
        sys.exit(1)
    sys.stdout.write(refs[branch] + "\n")
    sys.exit(0)

sys.stderr.write("스텁이 모르는 gh 호출: %r\n" % (args,))
sys.exit(90)
"""


def _run(
    tmp_path: Path,
    branches: str,
    *,
    refs: dict[str, str] | None = None,
    undeletable: list[str] | None = None,
    request_file: str | None = None,
    lookup_failure: str = "",
) -> tuple[int, str, list[str]]:
    """스텁 `gh`를 PATH 앞에 두고 스크립트를 실행한다. (exit code, 출력, gh 호출 목록)"""
    import json as _json

    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    gh.write_text(_STUB_GH, encoding="utf-8")
    gh.chmod(0o755)

    calls = tmp_path / "calls.txt"
    calls.write_text("", encoding="utf-8")

    env = dict(os.environ)
    env.update(
        PATH=f"{bindir}{os.pathsep}{env['PATH']}",
        REPO="doldori7/WhyMath",
        BRANCHES=branches,
        GH_TOKEN="stub",
        STUB_REFS=_json.dumps(refs or {}),
        STUB_UNDELETABLE=_json.dumps(undeletable or []),
        STUB_CALLS=str(calls),
        STUB_LOOKUP_FAILURE=lookup_failure,
        REQUEST_FILE=request_file if request_file is not None else str(tmp_path / "absent.txt"),
    )
    proc = subprocess.run(
        ["bash", str(_SCRIPT)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    made = [line for line in calls.read_text(encoding="utf-8").splitlines() if line]
    return proc.returncode, proc.stdout + proc.stderr, made


_SHA = "9d5f81b2c3d4e5f60718293a4b5c6d7e8f901234"


# ---------------------------------------------------------------------------
# 계약 ① — HARN-01의 본체: 이미 부재는 실패가 아니다
# ---------------------------------------------------------------------------


def test_already_absent_branch_does_not_fail_the_job(tmp_path: Path) -> None:
    """**이 태스크가 존재하는 이유.** 404 대상만 있는 배치는 exit 0이어야 한다.

    수정 전 코드는 여기서 exit 1을 냈다 — `gh api`가 404 *본문*을 stdout으로 뱉어
    `sha` 변수가 비지 않았고, 부재 가드가 발화하지 못한 채 DELETE로 진행해 실패했다.
    그러므로 이 단언이 이 수정의 True→False 변별을 낸다(acceptance ①-a).
    """
    rc, out, calls = _run(tmp_path, "claude/gone-1,claude/gone-2", refs={})
    assert rc == 0, f"이미 삭제된 브랜치뿐인데 잡이 red다:\n{out}"
    assert [c for c in calls if c.startswith("DELETE")] == [], f"부재인데 DELETE를 불렀다: {calls}"
    assert "이미 부재 2건" in out, out


def test_absent_branches_do_not_mask_a_real_failure(tmp_path: Path) -> None:
    """부재를 성공 계상해도 **진짜 실패는 여전히 red**여야 한다.

    ①을 '무조건 exit 0'으로 구현하면 이 단언이 깨진다 — 그것이 이 태스크가 막으려던
    바로 그 상태(진짜 실패가 묻히는 것)를 코드에 박는 셈이기 때문이다.
    """
    rc, out, calls = _run(
        tmp_path,
        "claude/gone-1,claude/protected,claude/gone-2",
        refs={"claude/protected": _SHA},
        undeletable=["claude/protected"],
    )
    assert rc == 1, f"삭제 실패가 있는데 초록으로 끝났다:\n{out}"
    assert "claude/protected" in out, "실패한 ref 이름이 로그에 없다"
    assert "이미 부재 2건" in out and "실패 1건" in out, out


def test_snapshot_uses_singular_ref_endpoint(tmp_path: Path) -> None:
    """조회는 단수형 `git/ref/heads/<b>`여야 한다 — 복수형은 **접두 일치**로 배열을 준다.

    복수형(`git/refs/heads/claude/foo`)은 `claude/foobar`에도 걸려 "그 브랜치가 있다"는
    판정이 흐려진다. 단수형은 정확히 하나이거나 404라 부재 의미가 모호하지 않다.
    스텁은 단수형 경로로만 파싱하므로, 복수형으로 회귀하면 호출 기록이 어긋난다.
    """
    rc, out, calls = _run(tmp_path, "claude/foo", refs={"claude/foo": _SHA})
    assert rc == 0, out
    assert calls[0] == "GET claude/foo", f"단수형 조회가 아니다: {calls}"


# ---------------------------------------------------------------------------
# 계약 ①-b — 부재는 **404일 때만**이다 (Codex P1 · PR #1070)
#
# 초판은 `if ! sha=$(gh api ...)`로 **비-0 종료 전부**를 부재로 접었다. 그러면 토큰이
# 죽거나 rate limit에 걸린 실행에서 전 대상이 "이미 부재"가 되고 잡은 exit 0으로 끝난다 —
# 브랜치를 하나도 못 지운 실행이 성공으로 보고된다. 원래 버그(거짓 red)보다 나쁘다:
# red는 사람이 보지만 정리 잡의 green은 아무도 안 본다.
#
# 2026-09-08 실측(수정 전): 인증 실패 스텁에 `이미 부재 3건 · 실패 0건 · EXIT=0`.
# ---------------------------------------------------------------------------


def test_auth_failure_is_not_mistaken_for_absent(tmp_path: Path) -> None:
    """토큰이 죽은 실행이 **거짓 green**으로 끝나면 안 된다 (Codex P1의 반례).

    `gh`는 인증 실패를 exit 4로 내고 stderr에 HTTP 상태를 **적지 않는다** — 그래서
    "비-0이면 부재"도 "404 문자열이 있으면 부재"도 아닌, *404가 확인될 때만* 부재다.
    """
    rc, out, calls = _run(
        tmp_path,
        "claude/a,claude/b,claude/c",
        refs={},
        lookup_failure="auth",
    )
    assert rc == 1, f"인증이 죽었는데 잡이 초록으로 끝났다:\n{out}"
    assert "이미 부재 0건" in out, f"조회 실패를 부재로 계상했다:\n{out}"
    assert "실패 3건" in out, out
    assert [c for c in calls if c.startswith("DELETE")] == [], "조회도 못 했는데 삭제를 시도했다"
    assert "GH_TOKEN" in out, "실패 원인이 로그에 없다 — 원인 없는 실패는 8개가 같아 보인다"


def test_rate_limit_is_a_failure_not_absence(tmp_path: Path) -> None:
    """403은 4xx이지만 404가 아니다 — acceptance ③-ⓐ의 '404 외만 실패로 계상'."""
    rc, out, _ = _run(tmp_path, "claude/a", refs={}, lookup_failure="ratelimit")
    assert rc == 1, out
    assert "이미 부재 0건" in out and "실패 1건" in out, out
    assert "rate limit" in out, "응답 본문이 로그에 없다"


def test_server_error_is_a_failure_not_absence(tmp_path: Path) -> None:
    """5xx도 마찬가지 — GitHub이 아플 때 배치를 '전부 이미 삭제됨'으로 보고하면 안 된다."""
    rc, out, _ = _run(tmp_path, "claude/a", refs={}, lookup_failure="server")
    assert rc == 1, out
    assert "이미 부재 0건" in out and "실패 1건" in out, out
    assert "500" in out, out


def test_404_is_still_absent_and_green(tmp_path: Path) -> None:
    """대조군 — 위 셋을 실패로 만들면서 **404는 여전히 성공**이어야 한다.

    이 단언이 없으면 "전부 실패로 계상"이라는 과잉 수정이 통과한다(그건 HARN-01이
    고치려던 상시 red 그 자체다).
    """
    rc, out, _ = _run(tmp_path, "claude/gone", refs={})
    assert rc == 0, f"404인데 red다 — HARN-01 회귀:\n{out}"
    assert "이미 부재 1건" in out and "실패 0건" in out, out


# ---------------------------------------------------------------------------
# 계약 ② — 진짜 실패는 반드시 red (정상에서 초록인 것은 보호의 증거가 아니다)
# ---------------------------------------------------------------------------


def test_happy_path_deletes_and_snapshots(tmp_path: Path) -> None:
    """기준선 — 이것이 초록이어야 아래 '막는다'들이 의미를 갖는다."""
    rc, out, calls = _run(tmp_path, "claude/live", refs={"claude/live": _SHA})
    assert rc == 0, out
    assert calls == ["GET claude/live", "DELETE claude/live"], calls
    assert _SHA in out, "복구 경로인 head SHA 스냅샷이 로그에 없다"
    assert "삭제 1건" in out, out


def test_undeletable_ref_is_fatal_and_named(tmp_path: Path) -> None:
    """존재하지만 삭제 불가한 ref → exit 1 + 그 이름이 로그에 (acceptance ④-ⓑ)."""
    rc, out, _ = _run(
        tmp_path,
        "claude/protected",
        refs={"claude/protected": _SHA},
        undeletable=["claude/protected"],
    )
    assert rc == 1, f"삭제 실패인데 초록으로 끝났다:\n{out}"
    assert "claude/protected" in out
    assert "Reference cannot be deleted" in out, "실패 원인(응답 본문)이 로그에 없다"


def test_main_is_refused(tmp_path: Path) -> None:
    rc, out, calls = _run(tmp_path, "main", refs={"main": _SHA})
    assert rc == 1, out
    assert calls == [], f"main인데 API를 불렀다: {calls}"


def test_branch_outside_allowed_patterns_is_refused(tmp_path: Path) -> None:
    """허용 패턴 밖은 조회조차 하지 않는다 — 거부는 red다(오타를 조용히 넘기지 않는다)."""
    rc, out, calls = _run(tmp_path, "release/v1", refs={"release/v1": _SHA})
    assert rc == 1, out
    assert calls == [], f"허용 패턴 밖인데 API를 불렀다: {calls}"
    assert "거부 1건" in out, out


def test_non_sha_snapshot_refuses_to_delete(tmp_path: Path) -> None:
    """gh가 exit 0으로 비-SHA를 뱉으면 **삭제하지 않는다**(fail-closed).

    이 잡의 유일한 복구 보장은 "삭제 직전 head SHA를 로그에 남긴다"다. 스냅샷이 쓰레기면
    그 보장이 조용히 사라진 채 삭제만 집행된다 — 복구 경로 없는 삭제는 되돌릴 수 없으므로,
    모르는 상태에서는 지운다가 아니라 멈춘다. 부재(①)와 달리 이것은 성공이 아니라 측정 실패다.
    """
    rc, out, calls = _run(tmp_path, "claude/weird", refs={"claude/weird": "Welcome to GitHub CLI!"})
    assert rc == 1, f"스냅샷이 SHA가 아닌데 초록으로 끝났다:\n{out}"
    assert [c for c in calls if c.startswith("DELETE")] == [], "복구 경로 없이 삭제했다"
    assert "SHA가 아니다" in out, out


# ---------------------------------------------------------------------------
# 계약 ③ — 0건도 값으로 읽힌다 · 요약이 실제 입력을 따라 움직인다
# ---------------------------------------------------------------------------


def test_summary_counts_are_real_not_hardcoded(tmp_path: Path) -> None:
    """분모가 고정 문자열이면 이 단언에서 깨진다 — 요약이 신호이려면 값이 움직여야 한다."""
    rc, out, _ = _run(
        tmp_path,
        "claude/live-a,claude/live-b,claude/gone,release/nope",
        refs={"claude/live-a": _SHA, "claude/live-b": _SHA},
    )
    assert rc == 1, out  # 거부 1건 때문에 red
    assert "대상 4건" in out, out
    assert "삭제 2건" in out, out
    assert "이미 부재 1건" in out, out
    assert "거부 1건" in out, out


def test_empty_list_is_noop_not_failure(tmp_path: Path) -> None:
    rc, out, calls = _run(tmp_path, "", refs={})
    assert rc == 0, out
    assert calls == []
    assert "no-op" in out, out


def test_request_file_comments_and_blanks_are_ignored(tmp_path: Path) -> None:
    """요청 파일 경로(push 트리거)도 실제로 동작하는지 — 주석·빈 줄이 대상이 되면 안 된다."""
    req = tmp_path / "request.txt"
    req.write_text(
        "# 주석\n\nclaude/from-file\n# 또 주석\n",
        encoding="utf-8",
    )
    rc, out, calls = _run(tmp_path, "", refs={"claude/from-file": _SHA}, request_file=str(req))
    assert rc == 0, out
    assert calls == ["GET claude/from-file", "DELETE claude/from-file"], calls
    assert "대상 1건" in out, out


# ---------------------------------------------------------------------------
# 계약 ④ — 배선 (만들어 두고 아무도 안 부르는 상태 차단)
# ---------------------------------------------------------------------------


def _workflow() -> dict[str, Any]:
    raw = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    # YAML 1.1에서 `on:`은 boolean True로 파싱된다.
    raw["on"] = raw.get("on", raw.get(True))
    return raw


def test_workflow_actually_invokes_the_script() -> None:
    """스크립트가 저장소에 존재하는 것과 워크플로가 그것을 부르는 것은 다르다."""
    steps = _workflow()["jobs"]["delete-branches"]["steps"]
    runs = " ".join(str(s.get("run", "")) for s in steps)
    assert ".github/scripts/branch_cleanup.sh" in runs, "워크플로가 스크립트를 부르지 않는다"


def test_workflow_still_passes_repo_and_token() -> None:
    """스크립트는 REPO 미설정 시 즉시 죽는다 — 배선이 끊기면 '항상 red'로 나타난다."""
    steps = _workflow()["jobs"]["delete-branches"]["steps"]
    envs = [s.get("env", {}) for s in steps if s.get("env")]
    merged = {k: v for e in envs for k, v in e.items()}
    assert "REPO" in merged and "GH_TOKEN" in merged, merged


def test_workflow_keeps_both_triggers_and_write_permission() -> None:
    wf = _workflow()
    assert "workflow_dispatch" in wf["on"], "수동 트리거가 없으면 세션이 즉시 검증할 방법이 없다"
    assert "push" in wf["on"], "요청 파일 머지 경로가 없으면 PR 감사 기록이 끊긴다"
    assert wf["permissions"].get("contents") == "write", wf["permissions"]


def test_script_is_executable_and_syntactically_valid() -> None:
    assert _SCRIPT.exists(), "스크립트 파일이 없다"
    assert os.access(_SCRIPT, os.X_OK), "실행 권한이 없다"
    proc = subprocess.run(["bash", "-n", str(_SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
