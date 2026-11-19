"""CAS push의 서버 측 경합 분류 (HARN-400).

사고(2026-11-19): RS-X2·RS-X3 세션이 1초 차이로 `backlog.py add`를 돌려 **둘 다 `RS-34`**를
받았다. X2 이벤트는 `number_reserve_unavailable`(status `error` · detail
`error: failed to push some refs`)였다 — 번호 예약 push가 거부됐는데 그것이 "경합(재시도)"이
아니라 "알 수 없는 오류(경고 후 진행)"로 접혔다.

원인(로컬 bare 저장소 재현 · git 2.43): 두 push가 **둘 다** 클라이언트 쪽 lease 검사를 통과한
뒤 서버에서 ref 잠금을 다투면, 진 쪽 stderr는 `[rejected] … (stale info)`가 아니라
`[remote rejected] … (failed to update ref)` + `cannot lock ref … but expected …`다.
이 문구가 `_LEASE_MARKERS`에 없어 `_classify_failure`가 `error`를 돌려줬다.

이 파일은 ① 분류 자체(실제 git 문구) ② 그 분류를 타는 `number_guard.reserve`의 재시도를
진짜 bare 원격으로 검증한다. ②의 주입은 "남이 먼저 같은 번호를 실제로 push하고, 내 push는
서버 경합 문구로 거부된다"는 실제 순서를 그대로 만든다.
"""

from __future__ import annotations

import subprocess

import number_guard
import pytest
import remote_claims

# 로컬 bare 저장소에서 서버 측 경합을 재현해 받은 stderr 원문(해시만 가림)
_SERVER_RACE_STDERR = (
    "remote: error: cannot lock ref 'refs/heads/harness-claims': is at "
    "4e91b48ccdf294b4ee34823292ba300e385c0726 but expected "
    "941beb11a830b7033d9ce882be0d194d1f0b8c17        \n"
    "To ../remote.git\n"
    " ! [remote rejected] fd0930cc28d31d99b15909ebe4d9873e89000b10 -> harness-claims "
    "(failed to update ref)\n"
    "error: failed to push some refs to '../remote.git'\n"
)


class TestClassifyServerRace:
    def test_server_side_lock_race_is_lease(self) -> None:
        """서버_ref_잠금_경합은_재시도_신호(lease)다 — 사고의 원문 그대로"""
        assert remote_claims._classify_failure(_SERVER_RACE_STDERR) == "lease"

    @pytest.mark.parametrize(
        "line",
        [
            "remote: error: cannot lock ref 'refs/heads/x': is at a but expected b",
            " ! [remote rejected] abc -> x (failed to update ref)",
            " ! [remote rejected] abc -> x (incorrect old value provided)",
        ],
        ids=["cannot-lock-ref", "failed-to-update-ref", "github-incorrect-old-value"],
    )
    def test_each_marker_alone_is_lease(self, line: str) -> None:
        """표지_하나만_있어도_lease — 절마다 그 절의 반례(다른 표지가 없는 입력)"""
        assert remote_claims._classify_failure(line + "\nerror: failed to push some refs\n") == (
            "lease"
        )

    @pytest.mark.parametrize(
        ("stderr", "expected"),
        [
            # 대조군 ① 훅·권한 거부는 경합이 아니다 — `[remote rejected]` 전체를 표지로 삼지 않았다
            (" ! [remote rejected] abc -> x (pre-receive hook declined)\n", "error"),
            (
                "remote: Permission to o/r.git denied.\nfatal: unable to access 'x': 403\n",
                "offline",
            ),
            # 대조군 ② 사고 때 남은 마지막 줄만으로는 여전히 판정하지 못한다(원인 불명은 error)
            ("error: failed to push some refs to '<url>'\n", "error"),
            # 대조군 ③ 기존 클라이언트 측 lease 거부는 그대로 lease
            (" ! [rejected] abc -> x (stale info)\n", "lease"),
        ],
        ids=["hook-declined", "auth-403", "last-line-only", "client-stale-info"],
    )
    def test_controls_keep_their_class(self, stderr: str, expected: str) -> None:
        assert remote_claims._classify_failure(stderr) == expected


def _race_once(monkeypatch, winner_root, winner_task: str, winner_branch: str) -> list[int]:
    """첫 예약 push 직전에 다른 세션(winner)이 실제로 예약을 push하게 하고, 내 push는
    서버 경합 문구로 거부되게 한다. 두 번째 시도부터는 진짜 push. 호출 횟수를 돌려준다."""
    real_push = remote_claims._push_claims
    calls: list[int] = []

    def racing_push(root, base_sha, commit_sha):
        calls.append(1)
        if len(calls) == 1:
            with monkeypatch.context() as inner:
                inner.setattr(remote_claims, "_push_claims", real_push)
                won = number_guard.reserve(winner_root, winner_task, winner_branch)
            assert won.status == "ok", f"경합 상대의 예약이 실제로 들어가지 않았다: {won}"
            return subprocess.CompletedProcess(["git", "push"], 1, "", _SERVER_RACE_STDERR)
        return real_push(root, base_sha, commit_sha)

    monkeypatch.setattr(remote_claims, "_push_claims", racing_push)
    return calls


class TestReserveRetriesServerRace:
    def test_same_number_race_ends_in_conflict_not_error(self, bare_remote, monkeypatch) -> None:
        """같은_번호를_서버에서_다투면_재시도_후_conflict — 사고 재현(전에는 error·fail-open)"""
        _, clone = bare_remote
        a, b = clone("a"), clone("b")
        calls = _race_once(monkeypatch, b, "RS-34-x2-rank2", "golden-rs/X2")
        result = number_guard.reserve(a, "RS-34", "golden-rs/X3")
        assert len(calls) == 1, "경합 뒤 같은 번호가 보이면 다시 push하지 않아야 한다"
        assert result.status == "conflict", f"서버 경합이 오류로 접혔다: {result}"
        assert result.holder == "RS-34-x2-rank2"
        assert result.holder_branch == "golden-rs/X2"

    def test_different_number_race_retries_and_succeeds(self, bare_remote, monkeypatch) -> None:
        """다른_번호와_경합하면_재시도로_둘_다_예약된다(대조군 — 과잉 거부가 아님)"""
        _, clone = bare_remote
        a, b = clone("a"), clone("b")
        calls = _race_once(monkeypatch, b, "RS-33-x1-rank1", "golden-rs/X1")
        result = number_guard.reserve(a, "RS-34", "golden-rs/X3")
        assert result.status == "ok", f"다른 번호 경합이 재시도로 수렴하지 않았다: {result}"
        assert len(calls) == 2
        base, status = remote_claims._fetch_claims_branch(a)
        assert status == "ok"
        numbers = {r.number for r in number_guard._reservations_at(a, base)}
        assert {"RS-33", "RS-34"} <= numbers
