"""HARN-22 — 번호 **제안** 경쟁(TOCTOU)의 재현 고정 · 양방향 변별 · 머지 시점 안전망.

사고 (2026-08-11 · OPS-29)
--------------------------
두 세션이 각각 `backlog.py add`로 `OPS-26`을 시도해 둘 다 타 세션 원격 브랜치의 인플라이트
번호 때문에 거부됐고, 가드가 **양쪽에 똑같이 `OPS-29`를 제안**해 둘 다 수용했다. 한쪽이 먼저
머지되자 다른 쪽 PR이 main을 병합한 순간 `validate`가 번호 충돌을 exit 1로 잡았고, 이쪽을
`OPS-33`으로 개명해 풀었다(개명 비용: 문서 7곳·MEMORY 3곳·태스크 1건).

판정 (acceptance ②) — 완화책은 새로 만들지 않고 **이미 착지한 두 장치를 채택**한다
-------------------------------------------------------------------------------
이 태스크가 등재된 뒤 같은 구간을 HARN-111(done)이 닫았다(번호 예약). 그래서 이 파일은 새
메커니즘을 더하지 않고, 두 장치가 **이 사고를 실제로 갈라놓는지**를 양방향으로 못박는다.

  · (a) 채택 · 예방 — `add`/`rename`이 번호를 `harness-claims/reservations/<번호>.json`에
    CAS로 예약한다. 집행 지점 = `backlog.py` `cmd_add`·`cmd_rename`이 부르는
    `number_guard.reserve_for`. push 전 창을 닫는 유일한 원자적 수단이다.
  · (c) 채택 · 2선 — 머지 시점 충돌 검출. 집행 지점 = `store.validate_backlog`의
    `_id_number_collisions` → `backlog.py validate` → CI `harness-integrity` 잡
    (`tests/infra/test_number_collision_backstop_wiring.py`가 그 배선을 동결한다).
  · (b) 기각 — 번호를 세션 오프셋·해시로 분산하면 충돌 **확률**만 낮출 뿐 예방이 아니고,
    `_suggest_number`의 연속 번호 규약(다음 빈 번호 · 소진 판정)을 깬다.

정직한 경계 (acceptance ④) — 아래는 **by design으로 남는 성질**이며 각각 테스트가 있다
-------------------------------------------------------------------------------------
  1. **제안은 예약이 아니다.** 거부 문구의 '다음 빈 번호 제안'은 읽기 전용 계산이라, 두 세션이
     예약 전에 같은 번호를 제안받는다. 막히는 지점은 제안이 아니라 **수용(add)**이다
     (`TestSuggestionIsAdvisoryNotReserved`). 제안을 예약하면 거부된 시도마다 번호가 소모된다.
  2. **예약을 못 남긴 세션은 보호되지 않는다**(구버전 하네스·네트워크 실패의 fail-open). 그
     구간의 충돌은 예방이 아니라 머지 시점에 `validate`가 잡는다 — 개명 비용이 드는 사후 검출이다
     (`TestBothArms` 완화 전 · `TestMergeTimeBackstop`).
  3. 예약은 TTL(기본 72시간) 뒤 무효다 — 이 경계는 `test_number_guard.py`가 동결한다.

모든 시나리오는 시임이 아니라 로컬 bare 원격의 실제 git push/fetch를 쓴다(`bare_remote`).
같은 시나리오(`_replay`)를 완화 on/off로 두 번 돌려 **결과가 갈리는지**를 단언한다 —
성공·실패 양쪽에서 같은 값을 내는 검증은 검증이 아니다(CLAUDE.md 2026-07-17).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import number_guard
import remote_claims

import backlog as cli

# 거부 문구의 제안 — `_check_new_id_number`가 "다음 빈 번호 제안: S9-41." 형태로 낸다
_SUGGESTION = re.compile(r"다음 빈 번호 제안: (S9-\d+)")
# 세 번째 세션이 원격 브랜치에 올려 둔 인플라이트 번호 — OPS-26 역할
_TAKEN_ID = "S9-40-inflight-by-third-session"
_TAKEN_NUMBER = "S9-40"


def _add(task_id: str) -> int:
    return cli.main(
        [
            "add",
            "--eos-priority",
            "P2",
            "--id",
            task_id,
            "--title",
            "번호 제안 경쟁 테스트 태스크",
            "--track",
            "math-completion",
            "--stage",
            "S2",
        ]
    )


def _add_without_reservation(monkeypatch, task_id: str) -> int:
    """예약을 남기지 않는 add — 구버전 하네스·예약 실패 세션(fail-open)의 모사.

    번호 가드(관측)는 그대로 돌고 **예약만** 건너뛴다 — 완화 전 상태의 정확한 재현이다.
    """
    with monkeypatch.context() as patch:
        patch.setattr(
            number_guard, "reserve", lambda *a, **k: number_guard.ReserveResult("skipped")
        )
        return _add(task_id)


def _session(clone, monkeypatch, name: str) -> Path:
    repo = clone(name)
    monkeypatch.chdir(repo)
    assert cli.main(["seed"]) == 0
    return repo


def _git(repo: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *argv], cwd=repo, capture_output=True, text=True)


def _push(repo: Path, branch: str) -> None:
    for argv in (
        ["checkout", "-q", "-B", branch],
        ["add", "."],
        ["commit", "-q", "-m", "등재만 한 상태"],
        ["push", "--quiet", "-u", "origin", branch],
    ):
        assert _git(repo, *argv).returncode == 0, argv


def _suggestion(err: str) -> str:
    found = _SUGGESTION.search(err)
    assert found, f"거부 문구에 다음 빈 번호 제안이 없다:\n{err}"
    return found.group(1)


@dataclass
class Replay:
    """사고 한 번의 재현 결과 — 두 세션의 거부·제안·수용을 순서대로 담는다."""

    a: Path
    b: Path
    number: str  # 두 세션이 함께 제안받은 번호 (S9-41)
    told_a: str
    told_b: str
    rc_a: int
    rc_b: int
    err_b: str
    retry_number: str = ""  # B가 거부된 뒤 다시 제안받은 번호
    retry_rc_b: int | None = None


def _replay(clone, monkeypatch, capsys, *, reservation: bool) -> Replay:
    """OPS-29 사고를 그대로 재생한다. `reservation`이 완화(번호 예약) on/off 스위치다.

    ① 세 번째 세션 c가 `S9-40`을 원격 브랜치에 올려 둔다(파일명 스캔으로만 보이는 인플라이트)
    ② 세션 a·b가 각각 `S9-40`을 시도 → 둘 다 거부 + **같은 제안**을 받는다
    ③ a가 제안 번호로 등재(push 안 함) → ④ b가 같은 제안 번호로 등재를 시도한다
    """
    c = _session(clone, monkeypatch, "c")
    assert _add_without_reservation(monkeypatch, _TAKEN_ID) == 0
    _push(c, "claude/c")
    a = _session(clone, monkeypatch, "a")
    b = _session(clone, monkeypatch, "b")

    told: dict[str, str] = {}
    for name, repo in (("a", a), ("b", b)):
        monkeypatch.chdir(repo)
        capsys.readouterr()
        assert _add(f"{_TAKEN_NUMBER}-session-{name}") == 1, "전제: 인플라이트 번호는 거부된다"
        told[name] = _suggestion(capsys.readouterr().err)
    assert told["a"] == told["b"], "전제가 깨졌다: 두 세션이 서로 다른 제안을 받았다"
    number = told["a"]

    def add(task_id: str) -> int:
        return _add(task_id) if reservation else _add_without_reservation(monkeypatch, task_id)

    monkeypatch.chdir(a)
    rc_a = add(f"{number}-session-a")
    # 전제(변별력): a는 push하지 않았다 — b의 파일명 스캔에는 원리상 보이지 않는다.
    # 이 전제가 깨지면 완화가 없어도 b가 거부되어 아래 '완화 전' 단언이 공허해진다.
    files, status = remote_claims.scan_remote_task_files(b, fetch=True)
    assert status == "ok"
    assert not [f for f in files if f.task_id.startswith(number)], "전제가 깨졌다"

    monkeypatch.chdir(b)
    capsys.readouterr()
    rc_b = add(f"{number}-session-b")
    result = Replay(
        a=a,
        b=b,
        number=number,
        told_a=told["a"],
        told_b=told["b"],
        rc_a=rc_a,
        rc_b=rc_b,
        err_b=capsys.readouterr().err,
    )
    if rc_b == 1:  # 거부된 b는 새 번호를 제안받아 다시 시도한다 — 사람이 하는 그대로
        result.retry_number = _suggestion(result.err_b)
        capsys.readouterr()
        result.retry_rc_b = add(f"{result.retry_number}-session-b")
    return result


class TestSuggestionIsAdvisoryNotReserved:
    """① 재현 고정 — 제안이 예약이 아니라는 설계상 성질을 먼저 명시한다."""

    def test_two_sessions_are_told_the_same_number_before_anyone_reserves(
        self, bare_remote, monkeypatch, capsys
    ):
        """예약이_켜져_있어도_거부된_두_세션이_받는_제안은_같다 — 막히는_곳은_수용이다"""
        _, clone = bare_remote
        replay = _replay(clone, monkeypatch, capsys, reservation=True)
        assert replay.told_a == replay.told_b == "S9-41", (
            "제안은 읽기 전용 계산이다 — 이것이 같다는 사실이 사고의 출발점이고, "
            "예약이 막는 지점은 제안이 아니라 add다(모듈 docstring 경계 1)"
        )


class TestBothArms:
    """③ 변별력 — 같은 시나리오를 완화 off/on으로 돌려 결과가 갈리는지 본다."""

    def test_without_reservation_both_sessions_accept_the_same_number(
        self, bare_remote, monkeypatch, capsys
    ):
        """완화_전(예약 없음): 두_세션이_같은_번호를_수용한다 — OPS-29 사고 그대로"""
        _, clone = bare_remote
        replay = _replay(clone, monkeypatch, capsys, reservation=False)
        assert (replay.rc_a, replay.rc_b) == (0, 0), (
            "예약이 없으면 push 전 번호는 어디에도 보이지 않아 b도 같은 번호를 수용한다 — "
            "이 단언이 깨지면 이 파일의 '완화 후' 단언이 아무것도 증명하지 못한다"
        )
        assert replay.retry_rc_b is None

    def test_with_reservation_the_second_session_is_refused_and_numbers_split(
        self, bare_remote, monkeypatch, capsys
    ):
        """완화_후(예약 있음): 두번째_세션은_거부되고_다음_번호로_갈린다"""
        _, clone = bare_remote
        replay = _replay(clone, monkeypatch, capsys, reservation=True)
        assert replay.rc_a == 0
        assert replay.rc_b == 1, "같은 번호를 수용했다면 예약이 사고를 못 막은 것이다"
        assert "원격 번호 예약(claude/a)" in replay.err_b
        assert replay.retry_number == "S9-42"
        assert replay.retry_number != replay.number
        assert replay.retry_rc_b == 0, "거부 뒤 새 번호로는 등재돼야 한다(과잉 차단 방지)"


class TestMergeTimeBackstop:
    """④ 예약이 닿지 않는 구간의 충돌은 머지 시점에 `validate`가 반드시 잡는다."""

    @staticmethod
    def _validate_after_branches_meet(replay: Replay, monkeypatch, capsys) -> tuple[int, str]:
        """두 세션 브랜치를 한 트리에서 만나게 한 뒤 validate — PR이 main을 병합하는 순간의 모사."""
        _push(replay.a, "claude/a")
        _push(replay.b, "claude/b")
        assert _git(replay.a, "fetch", "--quiet", "origin").returncode == 0
        merged = _git(replay.a, "merge", "--no-edit", "origin/claude/b")
        assert (
            merged.returncode == 0
        ), f"전제: 파일이 달라 git 병합은 충돌 없이 된다\n{merged.stderr}"
        monkeypatch.chdir(replay.a)
        capsys.readouterr()
        rc = cli.main(["validate"])
        return rc, capsys.readouterr().err

    def test_duplicate_number_that_slipped_past_is_caught_by_validate(
        self, bare_remote, monkeypatch, capsys
    ):
        """예약이_없었던_중복은_두_브랜치가_만나는_순간_validate가_exit_1로_잡는다"""
        _, clone = bare_remote
        replay = _replay(clone, monkeypatch, capsys, reservation=False)
        rc, err = self._validate_after_branches_meet(replay, monkeypatch, capsys)
        assert rc == 1, "중복 번호가 머지돼도 validate가 통과하면 안전망이 없는 것이다"
        assert f"태스크 ID 번호 충돌 '{replay.number}'" in err
        assert f"{replay.number}-session-a" in err and f"{replay.number}-session-b" in err

    def test_split_numbers_pass_validate(self, bare_remote, monkeypatch, capsys):
        """번호가_갈린_경우는_validate가_통과한다 — 대조군(무조건_실패하는_검사_방지)"""
        _, clone = bare_remote
        replay = _replay(clone, monkeypatch, capsys, reservation=True)
        rc, err = self._validate_after_branches_meet(replay, monkeypatch, capsys)
        assert rc == 0, err
        assert "번호 충돌" not in err
