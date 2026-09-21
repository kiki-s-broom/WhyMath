"""PR 자동 재동기화 (HARN-85) 계약 — 스크립트를 **실제로 실행해** 판정한다.

merge queue는 조직 소유 저장소 전용이라 이 저장소(owner.type=User)에서 쓸 수 없다.
그 대체가 `.github/scripts/pr_auto_resync.sh`이며, 이 파일은 그 스크립트가 *성공 경로뿐
아니라 실패 경로에서도* 설계대로 동작하는지를 동결한다.

왜 문자열 검사가 아니라 실행인가: 쉘 스크립트를 `"BEHIND" in text`로 검사하면 조건을
반대로 뒤집어도(`!=` → `=`) 통과한다 — 문자열은 그대로 남기 때문이다. CLAUDE.md
2026-09-01 ①("금지 패턴 열거 대신 산출물 검사")를 쉘에 적용하면 *구성된 결과*는
"이 입력에서 이 호출이 실제로 났는가"다. 그래서 `gh`를 스텁으로 갈아끼우고 돌린다.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / ".github" / "scripts" / "pr_auto_resync.sh"
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "pr-auto-resync.yml"
_DOC = _REPO_ROOT / ".github" / "branch-protection-setup.md"

_STUB_GH = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if args[:2] == ["pr", "list"]:
    sys.stdout.write(os.environ.get("STUB_PR_JSON", "[]"))
    sys.exit(int(os.environ.get("STUB_LIST_RC", "0")))
if args[:2] == ["pr", "view"]:
    # HARN-99 — 단건 재조회 스텁. STUB_VIEW_SEQUENCES는 {"<번호>": [상태, ...]}로,
    # 같은 PR을 여러 번 부를 때마다 다음 값을 준다(짧은 재시도 시뮬레이션). 마지막
    # 값을 넘어서면 그 값을 반복한다. 호출마다 STUB_VIEW_STATE_DIR 아래 인덱스 파일로
    # 진행 상황을 기억한다(서로 다른 gh 프로세스 호출 간 상태 공유).
    n = args[2]
    seqs = json.loads(os.environ.get("STUB_VIEW_SEQUENCES", "{}"))
    seq = seqs.get(n) or ["UNKNOWN"]
    state_dir = os.environ.get("STUB_VIEW_STATE_DIR", "")
    idx = 0
    idx_path = os.path.join(state_dir, "idx_" + n) if state_dir else None
    if idx_path and os.path.exists(idx_path):
        with open(idx_path, encoding="utf-8") as fh:
            idx = int(fh.read().strip() or "0")
    val = seq[min(idx, len(seq) - 1)]
    if idx_path:
        with open(idx_path, "w", encoding="utf-8") as fh:
            fh.write(str(idx + 1))
    rc = int(os.environ.get("STUB_VIEW_RC", "0"))
    if rc != 0:
        sys.stderr.write(os.environ.get("STUB_VIEW_ERROR_BODY", "gh: view failed"))
        sys.exit(rc)
    sys.stdout.write(json.dumps({"number": int(n), "mergeStateStatus": val}))
    sys.exit(0)
if args[:1] == ["api"]:
    target = args[-1]
    with open(os.environ["STUB_CALLS"], "a", encoding="utf-8") as fh:
        fh.write(target + "\\n")
    sys.stderr.write(os.environ.get("STUB_UPDATE_BODY", ""))
    sys.exit(int(os.environ.get("STUB_UPDATE_RC", "0")))
sys.stderr.write("스텁이 모르는 gh 호출: %r\\n" % (args,))
sys.exit(90)
"""


def _pr(number: int, state: str = "BEHIND", automerge: bool = True) -> dict[str, Any]:
    return {
        "number": number,
        "headRefName": f"claude/branch-{number}",
        "mergeStateStatus": state,
        "autoMergeRequest": {"enabledAt": "2026-09-07T00:00:00Z"} if automerge else None,
    }


# 계약 ⑤(HARN-89)용 기본 토큰 — pat 형식 검사(github_pat_ 접두·길이 60~255)를 만족하는
# 깨끗한 값. token_kind가 "pat"가 아닌 테스트에서도 문자 위생은 그대로 통과해야 하므로
# 굳이 다른 값을 쓸 이유가 없다 — 대조군(g)의 기준값이기도 하다.
_CLEAN_PAT = "github_pat_" + "A" * 70


def _run(
    tmp_path: Path,
    prs: list[dict[str, Any]],
    *,
    list_rc: int = 0,
    update_rc: int = 0,
    update_body: str = "",
    dry_run: str = "0",
    raw_payload: str | None = None,
    token_kind: str = "pat",
    gh_token: str | None = None,
    view_sequences: dict[str, list[str]] | None = None,
    view_rc: int = 0,
    view_error_body: str = "",
    recheck_sleep: str = "0",
    recheck_attempts: str | None = None,
) -> tuple[int, str, list[str]]:
    """스텁 `gh`를 PATH 앞에 두고 스크립트를 실행한다. (exit code, 출력, update 호출 목록)

    `view_sequences`(HARN-99)는 UNKNOWN 재조회(`gh pr view`) 스텁의 순차 응답을 준다 —
    `recheck_sleep` 기본값 "0"은 테스트를 실제 대기 없이 빠르게 돌리기 위함이며(운영
    기본값 2초는 스크립트 자체 기본값으로 별도 동결한다), `recheck_attempts`를 지정하지
    않으면 스크립트 기본(2회)을 그대로 쓴다.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    gh.write_text(_STUB_GH, encoding="utf-8")
    gh.chmod(0o755)

    calls = tmp_path / "calls.txt"
    calls.write_text("", encoding="utf-8")

    view_state_dir = tmp_path / "view_state"
    view_state_dir.mkdir(exist_ok=True)

    env = dict(os.environ)
    env.update(
        PATH=f"{bindir}{os.pathsep}{env['PATH']}",
        REPO="doldori7/WhyMath",
        RESYNC_TOKEN_KIND=token_kind,
        DRY_RUN=dry_run,
        GH_TOKEN=gh_token if gh_token is not None else _CLEAN_PAT,
        STUB_PR_JSON=raw_payload if raw_payload is not None else json.dumps(prs),
        STUB_LIST_RC=str(list_rc),
        STUB_UPDATE_RC=str(update_rc),
        STUB_UPDATE_BODY=update_body,
        STUB_CALLS=str(calls),
        STUB_VIEW_SEQUENCES=json.dumps(view_sequences or {}),
        STUB_VIEW_STATE_DIR=str(view_state_dir),
        STUB_VIEW_RC=str(view_rc),
        STUB_VIEW_ERROR_BODY=view_error_body,
        UNKNOWN_RECHECK_SLEEP_SECONDS=recheck_sleep,
    )
    if recheck_attempts is not None:
        env["UNKNOWN_RECHECK_ATTEMPTS"] = recheck_attempts
    proc = subprocess.run(
        ["bash", str(_SCRIPT)], env=env, capture_output=True, text=True, timeout=60
    )
    made = [line for line in calls.read_text(encoding="utf-8").splitlines() if line]
    return proc.returncode, proc.stdout + proc.stderr, made


# ---------------------------------------------------------------------------
# 계약 ① — 후보 선별이 정확한가 (정상 1건 + 주입 3건)
# ---------------------------------------------------------------------------


def test_behind_with_automerge_is_updated(tmp_path: Path) -> None:
    """기준선 — 이것이 초록이어야 아래 '건드리지 않는다'들이 의미를 갖는다."""
    rc, out, calls = _run(tmp_path, [_pr(101)])
    assert rc == 0, out
    assert calls == ["repos/doldori7/WhyMath/pulls/101/update-branch"], out


def test_behind_without_automerge_is_untouched(tmp_path: Path) -> None:
    """auto-merge를 켜지 않은 PR은 건드리지 않는다 — 리뷰 중인 diff를 임의로 전진시키지 않는다."""
    rc, out, calls = _run(tmp_path, [_pr(102, automerge=False)])
    assert rc == 0, out
    assert calls == [], f"auto-merge off인데 update-branch를 불렀다: {calls}"


@pytest.mark.parametrize("state", ["CLEAN", "BLOCKED", "DIRTY", "HAS_HOOKS"])
def test_non_behind_states_are_untouched(state: str, tmp_path: Path) -> None:
    """BEHIND가 아닌 상태는 재동기화 대상이 아니다 — 특히 DIRTY(충돌)는 사람 몫이다."""
    rc, out, calls = _run(tmp_path, [_pr(103, state=state)])
    assert rc == 0, out
    assert calls == [], f"{state}인데 update-branch를 불렀다: {calls}"


def test_unknown_merge_state_is_skipped_and_visible(tmp_path: Path) -> None:
    """모른다 ≠ 아니다 — GitHub이 아직 계산하지 않은 상태를 확정 신호로 접지 않는다.

    UNKNOWN을 '아니다'로 접으면 조용히 건너뛰어 아무도 모르고, 'BEHIND다'로 접으면
    멀쩡한 PR을 전진시킨다. 건너뛰되 **그 사실이 출력에 남아야** 한다.
    """
    rc, out, calls = _run(tmp_path, [_pr(104, state="UNKNOWN")])
    assert rc == 0, out
    assert calls == []
    assert "#104" in out and "미판정" in out, out


# ---------------------------------------------------------------------------
# 계약 ② — 실패 경로가 설계돼 있는가 (성공 경로만 보고 만들지 않았는가)
# ---------------------------------------------------------------------------


def test_conflict_409_is_visible_but_not_fatal(tmp_path: Path) -> None:
    """충돌은 자동 해소 대상이 아니라 건너뛰되, PR 번호와 응답 본문이 남아야 한다."""
    rc, out, calls = _run(
        tmp_path,
        [_pr(105), _pr(106)],
        update_rc=1,
        update_body="gh: merge conflict between base and head (HTTP 409)",
    )
    assert rc == 0, f"409는 잡 전체를 red로 만들지 않는다: {out}"
    assert len(calls) == 2, out
    assert "#105" in out and "409" in out, out
    assert "merge conflict between base and head" in out, "응답 본문이 로그에 없다"
    assert "충돌 2건" in out, out


def test_permission_403_is_fatal(tmp_path: Path) -> None:
    """권한 거부를 경고로 넘기면 자동화가 **상시 무력**인 채 초록으로 보인다.

    CLAUDE.md '상시 실패하는 fail-open 보호를 보호 있음으로 신뢰 금지'의 쓰기측 적용.
    """
    rc, out, _ = _run(
        tmp_path,
        [_pr(107)],
        update_rc=1,
        update_body="gh: Resource not accessible by integration (HTTP 403)",
    )
    assert rc == 1, f"403인데 잡이 초록으로 끝났다: {out}"
    assert "#107" in out and "403" in out, out


def test_unclassified_error_is_reported_with_body(tmp_path: Path) -> None:
    """분류되지 않은 실패도 조용히 사라지지 않는다 — 예외 타입만으론 8개 실패가 같아 보인다."""
    rc, out, _ = _run(tmp_path, [_pr(108)], update_rc=1, update_body="gh: something odd (HTTP 422)")
    assert rc == 0, out
    assert "#108" in out and "422" in out and "something odd" in out, out
    assert "기타실패 1건" in out, out


def test_list_failure_is_measurement_failure_not_zero_candidates(tmp_path: Path) -> None:
    """조회 실패가 '대상 0건 통과'로 위장되면 안 된다 — 인프라가 죽으면 그게 보여야 한다."""
    rc, out, calls = _run(tmp_path, [], list_rc=1)
    assert rc == 1, f"목록 조회 실패인데 초록으로 끝났다: {out}"
    assert calls == []
    assert "측정 실패" in out, out


def test_unparsable_payload_is_measurement_failure(tmp_path: Path) -> None:
    """gh가 exit 0으로 비-JSON을 뱉는 경우(로그인 안내 등)도 0건이 아니라 실패다."""
    rc, out, calls = _run(tmp_path, [], raw_payload="Welcome to GitHub CLI!")
    assert rc == 1, out
    assert calls == []
    assert "파싱 실패" in out, out


# ---------------------------------------------------------------------------
# 계약 ③ — 0건이 침묵이 아니라 값으로 보이는가 + dry-run
# ---------------------------------------------------------------------------


def test_summary_reports_denominator_even_when_nothing_to_do(tmp_path: Path) -> None:
    """스캔 0건 통과는 공허하다 — 분모를 내야 '대상이 없었다'와 '못 봤다'가 구분된다."""
    rc, out, calls = _run(tmp_path, [])
    assert rc == 0 and calls == []
    assert "스캔 0건" in out, out


def test_summary_counts_are_real_not_hardcoded(tmp_path: Path) -> None:
    """분모가 실제 입력을 따라 움직이는지 — 고정 문자열이면 이 단언에서 깨진다."""
    prs = [_pr(201), _pr(202), _pr(203, state="CLEAN"), _pr(204, automerge=False)]
    rc, out, calls = _run(tmp_path, prs)
    assert rc == 0
    assert "스캔 4건" in out, out
    assert "BEHIND+auto-merge 2건" in out, out
    assert "최신화 2건" in out, out
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# 계약 ③-b — "대상 0건"이 세 상태를 한 화면으로 만들지 않는가 (HARN-87)
#
# 원래 요약은 교집합(BEHIND+auto-merge)만 냈다. 그래서 0건이 ⓐauto-merge를 켠 PR이
# 아예 없음(자동화가 구조적으로 발화 불가) ⓑBEHIND 없음(정상 대기) ⓒ둘 다 있으나 서로
# 다른 PR — 셋 모두에서 **같은 글자**로 보였다. 처방이 각각 다른데 화면이 같으면 그
# 요약은 신호가 아니다.
#
# 아래 5건은 각 분기를 **실제로 밟는** 픽스처를 하나씩 두고, 마지막 1건은 대조군이다:
# 대상이 있을 때 진단 줄이 **나오지 않아야** 한다. 모든 입력에서 나오는 줄은 배경 소음이고
# 배경 소음은 사람이 읽지 않는다.
# ---------------------------------------------------------------------------

_DIAGNOSIS_MARK = "대상 0건"


def test_summary_separates_automerge_and_behind_denominators(tmp_path: Path) -> None:
    """세 분모가 각각 독립으로 움직이는지 — 하나라도 교집합을 따라가면 이 단언이 깨진다."""
    prs = [
        _pr(301),  # BEHIND + auto-merge  → 세 축 전부
        _pr(302, automerge=False),  # BEHIND만
        _pr(303, state="CLEAN"),  # auto-merge만
        _pr(304, state="CLEAN", automerge=False),  # 어느 축도 아님
        _pr(305, state="UNKNOWN"),  # 미판정 — 판정 분모에서 빠진다
    ]
    rc, out, _ = _run(tmp_path, prs)
    assert rc == 0, out
    assert "스캔 5건" in out, out
    assert "판정 4건" in out, out  # 5 - 미판정 1
    assert "auto-merge 켜짐 2건" in out, out  # 301, 303
    assert "BEHIND 2건" in out, out  # 301, 302
    assert "BEHIND+auto-merge 1건" in out, out  # 301만


def test_zero_targets_because_nobody_enabled_automerge_is_named(tmp_path: Path) -> None:
    """ⓐ 이 자동화가 **구조적으로 발화할 수 없는** 상태 — 가장 오독하기 쉬운 0건이다.

    BEHIND인 PR은 있는데 auto-merge가 하나도 안 켜져 있다. 예약 주기를 아무리 줄여도
    대상이 생기지 않으므로, 처방은 '주기 조정'이 아니라 운용 관행 또는 설계 변경이다.
    """
    prs = [_pr(311, automerge=False), _pr(312, automerge=False)]
    rc, out, calls = _run(tmp_path, prs)
    assert rc == 0 and calls == []
    assert "::notice::" in out, out  # 이 분기만 annotation으로 올린다
    assert "auto-merge를 켠 PR이 하나도 없다" in out, out
    assert "구조적으로 발화하지 않는다" in out, out


def test_zero_targets_because_nothing_is_behind_is_named(tmp_path: Path) -> None:
    """ⓑ 정상 대기 — auto-merge는 켜져 있는데 아무도 뒤처지지 않았다."""
    prs = [_pr(321, state="CLEAN"), _pr(322, state="BLOCKED")]
    rc, out, calls = _run(tmp_path, prs)
    assert rc == 0 and calls == []
    assert "BEHIND가 0건이다" in out, out
    assert "::notice::" not in out, out  # ⓐ와 구분된다


def test_zero_targets_because_sets_are_disjoint_is_named(tmp_path: Path) -> None:
    """ⓒ 두 축 모두 비어 있지 않은데 교집합만 비었다 — 서로 다른 PR이다."""
    prs = [_pr(331, automerge=False), _pr(332, state="CLEAN")]
    rc, out, calls = _run(tmp_path, prs)
    assert rc == 0 and calls == []
    assert "교집합이 없다" in out, out
    assert "auto-merge를 켠 PR이 하나도 없다" not in out, out


def test_zero_targets_with_nothing_decided_is_named(tmp_path: Path) -> None:
    """판정된 PR이 0건이면 대상 집합 자체를 **모르는** 것이다 — 0을 아니다로 접지 않는다."""
    prs = [_pr(341, state="UNKNOWN"), _pr(342, state="UNKNOWN")]
    rc, out, calls = _run(tmp_path, prs)
    assert rc == 0 and calls == []
    assert "판정된 PR이 0건이다" in out, out
    assert "::notice::" not in out, out


def test_diagnosis_line_is_absent_when_a_target_exists(tmp_path: Path) -> None:
    """대조군 — 대상이 있으면 진단 줄이 **나오지 않는다**.

    이 단언이 이 계약의 핵심이다. 진단이 모든 실행에서 나오면 그것은 상태를 가르는
    신호가 아니라 상시 배경이고, 상시 배경은 습관화돼 읽히지 않는다.
    """
    rc, out, calls = _run(tmp_path, [_pr(351)])
    assert rc == 0 and len(calls) == 1
    assert _DIAGNOSIS_MARK not in out, out


def test_dry_run_makes_no_write_call(tmp_path: Path) -> None:
    """DRY_RUN은 후보를 보여주되 쓰지 않는다 — 배선 확인을 안전하게 할 수 있어야 한다."""
    rc, out, calls = _run(tmp_path, [_pr(109)], dry_run="1")
    assert rc == 0, out
    assert calls == [], out
    assert "#109" in out and "DRY_RUN" in out, out


# ---------------------------------------------------------------------------
# 계약 ④ — 쓸 수 없는 토큰으로는 쓰지 않는다 (Codex P1 · fail-closed)
# ---------------------------------------------------------------------------


def test_github_token_fallback_fails_before_any_mutation(tmp_path: Path) -> None:
    """PAT가 없으면 **아무것도 바꾸지 않고** exit 1.

    변별력 근거: GITHUB_TOKEN이 만든 push는 workflow를 재발화시키지 않는다(GitHub 문서화
    제약). 그 토큰으로 update-branch를 하면 새 head에 required check가 하나도 보고되지
    않아 strict 하에서 PR이 **영구히** 막힌다 — `behind`는 사람이 Update branch를 눌러
    풀 수 있지만(사람 행위는 CI를 재발화시킨다) 체크 없는 head는 그 탈출구마저 없앤다.
    즉 폴백은 "성공을 보고하면서 PR을 좌초시키는" 반쪽 성공이며, 아무것도 안 하느니 나쁘다.

    이 판단은 제약의 성립 여부와 무관하게 옳다 — 제약이 없다면 비용은 PAT 요구 1회이고,
    있다면 폴백의 비용은 좌초된 PR이다.
    """
    rc, out, calls = _run(tmp_path, [_pr(301)], token_kind="github_token")
    assert rc == 1, f"쓸 수 없는 토큰인데 초록으로 끝났다: {out}"
    assert calls == [], f"멈추기 전에 이미 변경했다: {calls}"
    assert "쓰기 자격 없음" in out, out


def test_unset_token_kind_is_also_refused(tmp_path: Path) -> None:
    """미지정도 거부한다 — 모른다를 '괜찮다'로 접지 않는다(3상태 축)."""
    rc, out, calls = _run(tmp_path, [_pr(302)], token_kind="")
    assert rc == 1, out
    assert calls == []


def test_dry_run_is_allowed_without_pat(tmp_path: Path) -> None:
    """읽기 전용 확인 경로는 PAT 없이도 열려 있어야 한다 — 배선 검증을 막지 않는다."""
    rc, out, calls = _run(tmp_path, [_pr(303)], token_kind="github_token", dry_run="1")
    assert rc == 0, out
    assert calls == []
    assert "#303" in out and "DRY_RUN" in out, out


# ---------------------------------------------------------------------------
# 계약 ⑤ — 토큰 위생 사전 검사 (HARN-89)
#
# 2026-09-08 사고: PAT를 시크릿에 붙여넣을 때 끝에 개행이 딸려 들어가, gh 호출이 Go
# net/http의 내부 오류 문면으로만 실패했다. 여기서는 gh를 부르기 전에 그 오염 형태를
# 실제로 주입해 각각 다른 메시지가 나오는지 확인한다(2026-09-01 등재 규칙 — 정상 토큰
# 에서 초록인 것은 보호의 증거가 아니다). (g) 대조군이 핵심이다: 모든 입력에서 경고가
# 나오면 그 경고는 신호가 아니라 배경 소음이다.
# ---------------------------------------------------------------------------


def test_trailing_newline_is_trimmed_and_logged(tmp_path: Path) -> None:
    """(a) 끝 개행 — 제거 후 통과하되, 조용히 고치지 않고 그 사실을 고지한다."""
    rc, out, calls = _run(tmp_path, [_pr(401)], gh_token=_CLEAN_PAT + "\n")
    assert rc == 0, out
    assert calls == ["repos/doldori7/WhyMath/pulls/401/update-branch"], out
    assert "::warning::GH_TOKEN" in out and "제거했다" in out, out
    assert _CLEAN_PAT not in out, "토큰 값 자체가 로그에 출력됐다"


def test_trailing_space_is_trimmed_and_logged(tmp_path: Path) -> None:
    """(b) 끝 공백 — 제거 후 통과 + 고지."""
    rc, out, calls = _run(tmp_path, [_pr(402)], gh_token=_CLEAN_PAT + "  ")
    assert rc == 0, out
    assert len(calls) == 1, out
    assert "::warning::GH_TOKEN" in out and "제거했다" in out, out


def test_leading_space_is_trimmed_and_logged(tmp_path: Path) -> None:
    """(c) 앞 공백 — 제거 후 통과 + 고지."""
    rc, out, calls = _run(tmp_path, [_pr(403)], gh_token="  " + _CLEAN_PAT)
    assert rc == 0, out
    assert len(calls) == 1, out
    assert "::warning::GH_TOKEN" in out and "제거했다" in out, out


def test_internal_newline_is_fail_closed(tmp_path: Path) -> None:
    """(d) 값 내부 개행 — 앞뒤 제거로는 못 없앤다. fail-closed(exit 1) + 이름 붙인 진단."""
    contaminated = _CLEAN_PAT[:40] + "\n" + _CLEAN_PAT[40:]
    rc, out, calls = _run(tmp_path, [_pr(404)], gh_token=contaminated)
    assert rc == 1, f"값 내부 개행인데 초록으로 끝났다: {out}"
    assert calls == [], f"멈추기 전에 이미 gh를 호출했다: {calls}"
    assert "::error::GH_TOKEN 위생 검사 실패" in out, out
    assert "내부에 공백·개행·제어문자·비ASCII" in out, out
    assert _CLEAN_PAT not in out, "토큰 값 자체가 로그에 출력됐다"


def test_non_ascii_byte_is_fail_closed(tmp_path: Path) -> None:
    """(e) 비ASCII 문자 — fail-closed + 이름 붙인 진단."""
    contaminated = _CLEAN_PAT[:40] + "é" + _CLEAN_PAT[41:]
    rc, out, calls = _run(tmp_path, [_pr(405)], gh_token=contaminated)
    assert rc == 1, f"비ASCII 문자인데 초록으로 끝났다: {out}"
    assert calls == []
    assert "::error::GH_TOKEN 위생 검사 실패" in out, out
    assert "내부에 공백·개행·제어문자·비ASCII" in out, out


def test_empty_token_is_fail_closed(tmp_path: Path) -> None:
    """(f) 빈 문자열 — fail-closed. gh를 한 번도 부르지 않는다."""
    rc, out, calls = _run(tmp_path, [_pr(406)], gh_token="")
    assert rc == 1, f"빈 토큰인데 초록으로 끝났다: {out}"
    assert calls == []
    assert "::error::GH_TOKEN 위생 검사 실패" in out and "비어 있다" in out, out


def test_clean_token_triggers_no_hygiene_warning(tmp_path: Path) -> None:
    """(g) 대조군 — 정상 토큰에서는 위생 경고·에러가 전혀 나오지 않는다.

    이 단언이 이 계약의 핵심이다. 모든 입력에서 경고가 나오면 그것은 상태를 가르는
    신호가 아니라 상시 배경이고, 상시 배경은 습관화돼 읽히지 않는다.
    """
    rc, out, calls = _run(tmp_path, [_pr(407)])
    assert rc == 0, out
    assert len(calls) == 1, out
    assert "GH_TOKEN" not in out, f"정상 토큰인데 GH_TOKEN 관련 문구가 나왔다: {out}"


def test_pat_kind_without_prefix_is_fail_closed(tmp_path: Path) -> None:
    """형식 검사 — RESYNC_TOKEN_KIND=pat인데 github_pat_ 접두가 없으면 거부한다."""
    rc, out, calls = _run(tmp_path, [_pr(408)], gh_token="ghp_" + "A" * 66, token_kind="pat")
    assert rc == 1, f"접두 없는 값인데 초록으로 끝났다: {out}"
    assert calls == []
    assert "::error::GH_TOKEN 형식 검사 실패" in out and "'github_pat_' 접두" in out, out


def test_pat_kind_with_abnormal_length_is_fail_closed(tmp_path: Path) -> None:
    """형식 검사 — RESYNC_TOKEN_KIND=pat인데 길이가 비정상이면(잘림·오염 의심) 거부한다."""
    rc, out, calls = _run(tmp_path, [_pr(409)], gh_token="github_pat_ab", token_kind="pat")
    assert rc == 1, f"비정상 길이인데 초록으로 끝났다: {out}"
    assert calls == []
    assert "::error::GH_TOKEN 형식 검사 실패" in out and "길이가 비정상" in out, out


def test_github_token_kind_skips_pat_prefix_check(tmp_path: Path) -> None:
    """ⓔ 대조군 — token_kind=github_token · dry_run=1 · 정상 ghs_ 토큰은 통과해야 한다.

    ①의 fail-closed 목록에서 github_pat_ 접두 부재를 뺀 정정(PR #1062 Codex P2)이 지켜지는지
    판정한다 — 이것이 깨지면 test_dry_run_is_allowed_without_pat도 함께 RED가 된다.
    """
    rc, out, calls = _run(
        tmp_path,
        [_pr(410)],
        gh_token="ghs_" + "B" * 36,
        token_kind="github_token",
        dry_run="1",
    )
    assert rc == 0, out
    assert calls == []
    assert "GH_TOKEN" not in out, f"정상 ghs_ 토큰인데 GH_TOKEN 관련 문구가 나왔다: {out}"


def test_github_token_kind_still_rejects_embedded_newline(tmp_path: Path) -> None:
    """ⓕ 같은 조건에 개행이 섞이면 여전히 거부한다 — 문자 위생은 토큰 종류 무관이다."""
    ghs = "ghs_" + "B" * 36
    contaminated = ghs[:20] + "\n" + ghs[20:]
    rc, out, calls = _run(
        tmp_path,
        [_pr(411)],
        gh_token=contaminated,
        token_kind="github_token",
        dry_run="1",
    )
    assert rc == 1, f"github_token 경로에서 개행 오염이 통과했다: {out}"
    assert calls == []
    assert "::error::GH_TOKEN 위생 검사 실패" in out, out


def test_workflow_passes_token_kind_to_the_script() -> None:
    """워크플로가 토큰 종류를 실제로 넘기지 않으면 스크립트의 게이트는 항상 거부한다.

    배선이 끊기면 '항상 red'라는 다른 고장으로 나타나므로, 표현식의 실재를 동결한다.
    """
    steps = _workflow()["jobs"]["resync"]["steps"]
    envs = [s.get("env", {}) for s in steps if s.get("env")]
    kinds = [e.get("RESYNC_TOKEN_KIND") for e in envs if e.get("RESYNC_TOKEN_KIND")]
    assert kinds, f"RESYNC_TOKEN_KIND를 넘기는 스텝이 없다: {envs}"
    expr = kinds[0]
    assert "PR_AUTO_RESYNC_TOKEN" in expr, expr
    assert "'pat'" in expr and "'github_token'" in expr, expr


# ---------------------------------------------------------------------------
# 계약 ④ — 배선 (만들어 두고 아무도 안 돌리는 상태 차단)
# ---------------------------------------------------------------------------


def _workflow() -> dict[str, Any]:
    raw = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    # YAML 1.1에서 `on:`은 boolean True로 파싱된다.
    raw["on"] = raw.get("on", raw.get(True))
    return raw


def test_workflow_actually_invokes_the_script() -> None:
    """스크립트가 저장소에 존재하는 것과 워크플로가 그것을 부르는 것은 다르다."""
    steps = _workflow()["jobs"]["resync"]["steps"]
    runs = " ".join(str(s.get("run", "")) for s in steps)
    assert ".github/scripts/pr_auto_resync.sh" in runs, "워크플로가 스크립트를 부르지 않는다"


def test_workflow_has_both_triggers_and_write_permissions() -> None:
    wf = _workflow()
    assert "schedule" in wf["on"], "예약 트리거가 없으면 사람이 눌러야만 도는 자동화다"
    assert "workflow_dispatch" in wf["on"], "수동 트리거가 없으면 즉시 검증할 방법이 없다"
    perms = wf["permissions"]
    assert perms.get("contents") == "write", perms
    assert perms.get("pull-requests") == "write", perms


def test_script_is_executable_and_syntactically_valid() -> None:
    assert _SCRIPT.exists(), "스크립트 파일이 없다"
    proc = subprocess.run(["bash", "-n", str(_SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_doc_records_current_merge_queue_state_with_evidence() -> None:
    """문서가 merge queue의 **현행 사실**을 근거와 함께 적어야 한다 (HARN-98).

    원래 이 테스트는 "쓸 수 없다는 사실이 적혀 있다"를 동결했다(2026-09-07). 그 전제는
    2026-09-09 저장소가 조직(kiki-s-broom)으로 전환되면서 **거짓이 됐고**, 테스트는 거짓을
    동결하는 상태가 됐다. 이제 방향을 뒤집어 *현행 사실 + 그것을 뒷받침하는 실측*을 요구한다.

    왜 제목만 보지 않는가: 제목만 검사하면 본문을 지워도 통과한다. 그래서 ①계정 유형이라는
    제공 조건 ②큐가 실제로 일한 증거(merge_group 이벤트) ③전제가 바뀐 이력 셋을 함께 본다.
    ③을 요구하는 이유는 그 절이 CLAUDE.md v0.2.18("설정 부재를 설정 가능으로 단정 금지")의
    발생 근거이기 때문이다 — 사실이 바뀌었다고 사고 기록까지 지우면 규칙의 출처가 사라진다.
    """
    text = _DOC.read_text(encoding="utf-8")
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert any("merge queue" in h for h in headings), f"merge queue 절이 없다: {headings}"

    # ① 제공 조건 — 조직 소유 전용이라는 조건 자체는 변하지 않았다
    assert "owner.type" in text, "계정 유형 축이 문서에 없다"
    assert "Organization" in text, "현행 계정 유형(조직)이 문서에 없다"

    # ② 큐가 **실제로 일한** 증거 — 설정 조회보다 강한 근거이며, 라이브 룰셋을 읽지 못하는
    #    세션에서도 확인 가능한 유일한 축이다.
    #    앵커는 문서에 **한 번만** 나오는 토큰으로 잡는다: `merge_group`은 큐의 잡 스킵을
    #    설명하는 문단에도 나오므로, 그 단어로 검사하면 증거 블록을 통째로 지워도 통과한다
    #    (실측: 뮤테이션 Q3 생존 → 이 형태로 교체). run id와 큐 브랜치명은 각 1회다.
    assert "34318528035" in text, "큐 CI 실행 id(증거)가 문서에 없다"
    assert "gh-readonly-queue" in text, "큐 브랜치 실측이 문서에 없다"

    # ③ 사고 기록 보존 — v0.2.18의 발생 근거가 지워지지 않았는가.
    #    "설정 부재"도 같은 절에 2회 나와 한쪽을 지워도 통과했다(뮤테이션 Q4 생존) —
    #    규칙 버전 문자열은 1회뿐이라 그것을 앵커로 쓴다.
    assert "v0.2.18" in text, "전제가 바뀐 이력(v0.2.18 발생 근거)이 지워졌다"


# ---------------------------------------------------------------------------
# 계약 ⑥ — UNKNOWN 재조회 (HARN-99)
#
# 일괄 조회(list)의 mergeStateStatus는 계산을 유발하지 않아 UNKNOWN으로 자주 온다
# (2026-09-08 관측: PR #1059가 같은 시각 REST 단건 조회로는 `behind`였다). 단건
# 조회(`gh pr view`)는 계산을 촉발하며, 이 태스크의 2026-09-10 실측(같은 저장소 열린 PR
# 6건 REST 단건 재조회)에서도 첫 호출이 종종 `unknown`이지만 반복 호출로 대개 해소됐다.
# auto-merge가 켜진 후보만 재조회해 비용을 절제한다.
# ---------------------------------------------------------------------------


def test_unknown_with_automerge_is_rechecked_and_updated_when_resolved(
    tmp_path: Path,
) -> None:
    """①②의 핵심 — list UNKNOWN + auto-merge on을 단건 재조회로 뚫어 BEHIND를 찾아낸다.

    고치기 전에는 RED다 — 현재 코드는 UNKNOWN을 보는 즉시 건너뛰므로 update-branch
    호출이 0건이다.
    """
    rc, out, calls = _run(
        tmp_path,
        [_pr(501, state="UNKNOWN")],
        view_sequences={"501": ["BEHIND"]},
    )
    assert rc == 0, out
    assert calls == ["repos/doldori7/WhyMath/pulls/501/update-branch"], out
    assert "재조회 1건" in out, out


def test_unknown_resolved_only_after_a_retry(tmp_path: Path) -> None:
    """② 첫 재조회도 UNKNOWN이면 짧게 한 번 더 시도한다."""
    rc, out, calls = _run(
        tmp_path,
        [_pr(502, state="UNKNOWN")],
        view_sequences={"502": ["UNKNOWN", "BEHIND"]},
    )
    assert rc == 0, out
    assert calls == ["repos/doldori7/WhyMath/pulls/502/update-branch"], out
    assert "재조회 2건" in out, out


def test_unknown_still_unknown_after_retries_is_skipped_like_before(
    tmp_path: Path,
) -> None:
    """③ 기존 계약 동결 — 재조회해도 끝까지 UNKNOWN이면 여전히 건드리지 않고 출력에 남긴다."""
    rc, out, calls = _run(
        tmp_path,
        [_pr(503, state="UNKNOWN")],
        view_sequences={"503": ["UNKNOWN", "UNKNOWN"]},
    )
    assert rc == 0, out
    assert calls == []
    assert "#503" in out and "미판정" in out, out
    assert "재조회 2건(해소 0건)" in out, out


def test_unknown_without_automerge_is_never_rechecked(tmp_path: Path) -> None:
    """② 비용 절제 — auto-merge가 꺼진 후보는 재조회 대상이 아니다(어차피 건드리지 않는다)."""
    rc, out, calls = _run(
        tmp_path,
        [_pr(504, state="UNKNOWN", automerge=False)],
        # 재조회됐다면 이 값이 나왔을 것 — 나오면 안 된다.
        view_sequences={"504": ["BEHIND"]},
    )
    assert rc == 0, out
    assert calls == []
    assert "재조회 0건" in out, out


def test_recheck_call_count_is_logged_even_when_zero(tmp_path: Path) -> None:
    """④ 호출 비용 기록 — 재조회가 0건이어도 그 사실이 값으로 보여야 한다."""
    rc, out, calls = _run(tmp_path, [_pr(505)])
    assert rc == 0, out
    assert len(calls) == 1, out
    assert "재조회 0건" in out, out


def test_ruleset_policy_declares_merge_queue() -> None:
    """선언 축에 merge_queue가 있어야 감시가 실효를 갖는다 (HARN-98 집행 지점).

    `ruleset_drift.compare`는 **문서 선언 키만 순회**한다 — 라이브 파서에만 넣으면 그 축은
    한 번도 대조되지 않는다. 큐가 머지 경로를 지탱하는 지금, 감시 축 부재는 "누가 큐를 꺼도
    판정기가 모르는" 상태다.
    """
    text = _DOC.read_text(encoding="utf-8")
    begin, end = text.index("RULESET_POLICY_BEGIN"), text.index("RULESET_POLICY_END")
    assert "`merge_queue` = `true`" in text[begin:end], "정책 선언 블록에 merge_queue가 없다"
