"""HARN-199 — 대장에 쓰는 verb가 다른 세션 claim 아래의 태스크를 경고 없이 쓰던 사각.

사고(2026-09-29): 다른 세션이 HARN-170을 claim(07:00:48Z)한 뒤 이 세션의 `amend`가 같은 태스크를
경고 없이 정정했다(종료 코드 0·출력에 단서 없음). 발견은 도구가 아니라 수동 재조회였다.

이 파일이 계약으로 동결하는 것:
  ① 4상태 — 다른 세션 claim(`foreign`)·내 claim(`own`)·claim 없음(`none`)·확인 불가(`unknown`).
     경고는 `foreign`과 `unknown`에서만 나고 `own`·`none`은 침묵한다.
  ② '모른다 ≠ 아니다' — 조회 실패(offline·error·비활성·메타 파손)는 `none`이 아니라 `unknown`이다.
  ③ 거부하지 않는다 — 경고가 나도 정정은 성공(exit 0)하고 이벤트에 `foreign_claim` 근거가 남는다.
  ④ 범위 전수 — 대장 태스크 파일을 쓰는 `cmd_*`는 전부 claim 조회에 닿는다. 예외 2건(add·seed)은
     대상이 기존 태스크가 아니라 이유와 함께 허용 목록에 있다. 새 쓰기 verb가 조회 없이 추가되면 RED.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import remote_claims
import store

import backlog as cli

_BACKLOG_PY = Path(__file__).resolve().parents[2] / "scripts" / "harness" / "backlog.py"


@pytest.fixture
def seeded_repo(git_repo: Path, monkeypatch) -> Path:
    monkeypatch.chdir(git_repo)
    assert cli.main(["seed"]) == 0
    return git_repo


def _add(task_id: str) -> None:
    assert (
        cli.main(
            [
                "add",
                "--eos-priority",
                "P1",
                "--id",
                task_id,
                "--title",
                "HARN-199 테스트 태스크",
                "--track",
                "math-completion",
                "--stage",
                "S1",
                "--acceptance",
                "원래 조건 ①",
            ]
        )
        == 0
    )


def _claims(monkeypatch, claims: list, status: str = "ok") -> None:
    monkeypatch.setattr(remote_claims, "list_claims", lambda root, **kw: (claims, status))


def _claim(task_id: str, branch: str, ts: str = "2026-10-03T00:00:00+00:00", meta=None):
    return remote_claims.RemoteClaim(
        task_id=task_id, sha="deadbeef", branch=branch, ts=ts, meta=meta
    )


def _events(repo: Path, action: str, task_id: str) -> list[dict]:
    return [
        e
        for path in store.event_paths(repo)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for e in [json.loads(line)]
        if e.get("action") == action and e.get("id") == task_id
    ]


def _amend(task_id: str) -> int:
    return cli.main(
        ["amend", task_id, "--acceptance", "정정 조건 ②", "--reason", "HARN-199 테스트"]
    )


class TestAmendFourStates:
    def test_foreign_claim_warns_but_still_writes(self, seeded_repo, monkeypatch, capsys):
        """상태 1 — 다른 세션 claim: 경고(보유 브랜치·시각 포함) + 정정은 성공 + 이벤트 근거."""
        _add("T9-01-foreign")
        _claims(monkeypatch, [_claim("T9-01-foreign", "claude/other-session")])
        capsys.readouterr()
        assert _amend("T9-01-foreign") == 0  # 거부하지 않는다
        err = capsys.readouterr().err
        assert "다른 세션이 claim 중" in err
        assert "claude/other-session" in err and "2026-10-03T00:00:00" in err
        backlog, _ = store.load_backlog(seeded_repo)
        assert "정정 조건 ②" in " ".join(backlog.tasks["T9-01-foreign"].acceptance)  # 실제로 썼다
        event = _events(seeded_repo, "amend", "T9-01-foreign")[-1]
        assert event["foreign_claim"]["state"] == "foreign"
        assert event["foreign_claim"]["holder"] == "claude/other-session"

    def test_own_claim_is_silent(self, seeded_repo, monkeypatch, capsys):
        """상태 2 — 내 claim: 경고 없음·이벤트에 foreign_claim 없음."""
        _add("T9-02-own")
        me = store.current_branch(seeded_repo)
        _claims(monkeypatch, [_claim("T9-02-own", me)])
        capsys.readouterr()
        assert _amend("T9-02-own") == 0
        assert "claim" not in capsys.readouterr().err
        assert "foreign_claim" not in _events(seeded_repo, "amend", "T9-02-own")[-1]

    def test_no_claim_is_silent(self, seeded_repo, monkeypatch, capsys):
        """상태 3 — 조회 성공 + claim 없음: 경고 없음. (다른 태스크의 claim은 무관하다.)"""
        _add("T9-03-none")
        _claims(monkeypatch, [_claim("T9-99-other-task", "claude/someone")])
        capsys.readouterr()
        assert _amend("T9-03-none") == 0
        assert "claim" not in capsys.readouterr().err
        assert "foreign_claim" not in _events(seeded_repo, "amend", "T9-03-none")[-1]

    @pytest.mark.parametrize("status", ["offline", "error"])
    def test_lookup_failure_is_unknown_not_none(self, seeded_repo, monkeypatch, capsys, status):
        """상태 4 — 조회 실패는 '없음'이 아니라 '확인 불가'로 알린다(모른다 ≠ 아니다)."""
        _add("T9-04-unknown")
        _claims(monkeypatch, [], status=status)
        capsys.readouterr()
        assert _amend("T9-04-unknown") == 0
        err = capsys.readouterr().err
        assert "확인 불가" in err and status in err
        assert "다른 세션이 claim 중" not in err  # foreign 문구와 구분된다
        event = _events(seeded_repo, "amend", "T9-04-unknown")[-1]
        assert event["foreign_claim"] == {"state": "unknown", "reason": status}

    def test_claim_without_branch_meta_is_unknown(self, seeded_repo, monkeypatch, capsys):
        """메타 파손(브랜치 없음) claim은 누구 것인지 모른다 — own·foreign 어느 쪽으로도 접지 않는다."""
        _add("T9-05-nometa")
        _claims(monkeypatch, [_claim("T9-05-nometa", "")])
        capsys.readouterr()
        assert _amend("T9-05-nometa") == 0
        err = capsys.readouterr().err
        assert "확인 불가" in err and "다른 세션이 claim 중" not in err

    def test_disabled_policy_is_unknown(self, seeded_repo, monkeypatch, capsys):
        """policy.remote_claims=False — 조회하지 않았으므로 '없음'이 아니라 '확인 불가'다."""
        _add("T9-06-disabled")
        monkeypatch.setattr(
            cli.store, "load_policy", lambda root: (SimpleNamespace(remote_claims=False), [])
        )
        # 활성이었다면 foreign으로 읽혔을 claim을 둔다 — 조회가 일어났다면 이 테스트가 RED다.
        _claims(monkeypatch, [_claim("T9-06-disabled", "claude/other-session")])
        capsys.readouterr()
        assert _amend("T9-06-disabled") == 0
        err = capsys.readouterr().err
        assert "확인 불가" in err and "disabled" in err

    def test_block_kind_hold_by_other_session_is_foreign(self, seeded_repo, monkeypatch, capsys):
        """차단 홀드(kind=block)도 다른 세션의 점유다 — 경고에 kind가 드러난다."""
        _add("T9-07-hold")
        _claims(
            monkeypatch,
            [_claim("T9-07-hold", "claude/other", meta={"kind": "block", "reason": "게이트 대기"})],
        )
        capsys.readouterr()
        assert _amend("T9-07-hold") == 0
        assert "kind=block" in capsys.readouterr().err


class TestReviewVerbSameWarning:
    """③ 범위 전수 — `review`도 대상 태스크 파일을 쓰므로 같은 경고를 붙였다."""

    def _in_progress(self, task_id: str) -> None:
        _add(task_id)
        assert cli.main(["start", task_id, "--no-remote"]) == 0

    def test_review_warns_on_foreign_claim_and_still_transitions(
        self, seeded_repo, monkeypatch, capsys
    ):
        self._in_progress("T9-10-review-foreign")
        _claims(monkeypatch, [_claim("T9-10-review-foreign", "claude/other-session")])
        capsys.readouterr()
        assert cli.main(["review", "T9-10-review-foreign"]) == 0
        assert "다른 세션이 claim 중" in capsys.readouterr().err
        backlog, _ = store.load_backlog(seeded_repo)
        assert backlog.tasks["T9-10-review-foreign"].status == "review"
        event = _events(seeded_repo, "review", "T9-10-review-foreign")[-1]
        assert event["foreign_claim"]["state"] == "foreign"

    def test_review_is_silent_for_own_claim(self, seeded_repo, monkeypatch, capsys):
        self._in_progress("T9-11-review-own")
        _claims(monkeypatch, [_claim("T9-11-review-own", store.current_branch(seeded_repo))])
        capsys.readouterr()
        assert cli.main(["review", "T9-11-review-own"]) == 0
        assert "claim" not in capsys.readouterr().err
        assert "foreign_claim" not in _events(seeded_repo, "review", "T9-11-review-own")[-1]


# ── ④ 범위 전수 — 대장 태스크 파일을 쓰는 cmd_* 는 전부 claim 조회에 닿는다 ─────────────────────
# 범위 전수 결과 (2026-10-03 · AST 호출 그래프 3단계 · `store.save_task` 호출 기준 — 태스크 YAML을 쓰는
# 유일한 경로다. `store.save_gates`·`save_tracks`·`save_policy`는 다른 파일이다):
#   · 이미 claim 판정이 있던 verb(홀더 불일치를 conflict로 거부) — start(claim·scan_remote_in_progress)·
#     done·block·cancel·unblock·rename(`remote_claims.release/claim`). 이 태스크의 변경 없음.
#   · claim 조회가 *없던* verb — **amend·review 두 개뿐**. 둘 다 이 PR에서 같은 경고를 붙였다.
#   · 허용 목록(아래) — add(신규 생성)·seed(초기 시딩).
# 확인하지 않은 것(안 본 것을 통과로 세지 않는다): `gates` 계열은 `gates.yaml`을 쓰며 태스크 YAML을 쓰지
# 않으므로 이 가드의 대상이 아니다 — 다만 *게이트 파일*을 두 세션이 동시에 고치는 충돌은 별건(HARN-207
# 게이트 부착 푸시 창)이 소유하고 여기서는 조사하지 않았다.
# 허용 목록 = 대상이 *기존 태스크가 아닌* verb. 이유 없는 항목 추가 금지.
_EXEMPT_WRITERS = {
    "cmd_add": "신규 태스크 생성 — 번호 선점은 별도 가드(number_guard)가 본다",
    "cmd_seed": "빈 대장 초기 시딩 — 기존 태스크를 대상으로 하지 않는다",
}
_CLAIM_ENTRYPOINTS = {"_warn_foreign_claim", "_foreign_claim_state"}


def _module_funcs() -> dict[str, ast.FunctionDef]:
    tree = ast.parse(_BACKLOG_PY.read_text(encoding="utf-8"))
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def _writers(funcs: dict[str, ast.FunctionDef]) -> set[str]:
    return {
        name
        for name, fn in funcs.items()
        if name.startswith("cmd_")
        and any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "save_task"
            for n in ast.walk(fn)
        )
    }


def _reaches_claim_lookup(funcs, name: str, depth: int = 3, seen: set[str] | None = None) -> bool:
    seen = seen if seen is not None else set()
    if name in seen or depth < 0 or name not in funcs:
        return False
    seen.add(name)
    for n in ast.walk(funcs[name]):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if (
            isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and f.value.id == "remote_claims"
        ):
            return True
        if isinstance(f, ast.Name):
            if f.id in _CLAIM_ENTRYPOINTS:
                return True
            if _reaches_claim_lookup(funcs, f.id, depth - 1, seen):
                return True
    return False


class TestEveryWritingVerbReachesClaimLookup:
    def test_writer_scan_finds_the_known_verbs(self) -> None:
        """스캔 0건은 실패 — 전수 가드가 공허하게 통과하는 것을 막는다."""
        writers = _writers(_module_funcs())
        assert {"cmd_amend", "cmd_review", "cmd_start", "cmd_done", "cmd_rename"} <= writers
        assert len(writers) >= 8

    def test_no_writing_verb_is_blind_to_foreign_claims(self) -> None:
        funcs = _module_funcs()
        blind = sorted(
            w
            for w in _writers(funcs)
            if w not in _EXEMPT_WRITERS and not _reaches_claim_lookup(funcs, w)
        )
        assert blind == [], f"claim 조회 없이 태스크 파일을 쓰는 verb: {blind}"

    def test_exempt_list_is_real_and_reasoned(self) -> None:
        funcs = _module_funcs()
        writers = _writers(funcs)
        for name, why in _EXEMPT_WRITERS.items():
            assert name in writers, f"{name}는 더 이상 태스크를 쓰지 않는다 — 허용 목록에서 뺀다"
            assert why.strip()
