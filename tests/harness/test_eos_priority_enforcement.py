"""EOS 등급(P0~P3) 집행 — 계획서 100 Rule 1·3·4의 CLI 종단 계약 (HARN-55).

계획서 100은 세 규칙을 **산문으로** 요구했고 저장소는 그것을 선언 §0-5에 옮겨 적기만
했다. 준수 감사가 "신규 기능 게이트가 집행 지점 0 — 산문 규칙만 존재"를 심각도 **높음**
으로 적은 것이 A1이다. 이 스위트가 지키는 것은 그 집행이 *실제로 거부하는가*다.

**왜 exit code로 판정하는가**: 경고는 집행이 아니다. 이 저장소는 상시 실패하는 fail-open
경고가 습관화돼 보호가 통째로 무력해진 사고를 이미 겪었다(`refs/claims/*` push 403 →
모든 세션이 경고를 보고 진행 → 두 세션이 같은 태스크를 병렬 구현, 735줄 폐기).

**변별력(양방향)**: 각 규칙마다 *거부되는 호출*과 *통과하는 호출*을 쌍으로 둔다. 한쪽만
검증하면 "항상 거부"·"항상 통과"가 그대로 통과한다 — 성공/실패 양쪽에서 같은 값을 내는
검사는 검증이 아니라 위장이다(2026-07-17 logconfig 사고의 일반형).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import store
from models import EOS_PRIORITY_BACKFILL_GATE

import backlog as cli


@pytest.fixture
def seeded_repo(git_repo: Path, monkeypatch) -> Path:
    monkeypatch.chdir(git_repo)
    assert cli.main(["seed"]) == 0
    return git_repo


def _open_track(repo: Path) -> str:
    backlog, _ = store.load_backlog(repo)
    for name, track in backlog.tracks.items():
        if not getattr(track, "entry_gate", None):
            return name
    pytest.skip("시드에 게이트 없는 트랙이 없다")


def _add_argv(task_id: str, track: str, grade: str | None, *extra: str) -> list[str]:
    argv = [
        "add",
        "--id",
        task_id,
        "--title",
        f"{task_id} 픽스처",
        "--track",
        track,
        "--stage",
        "S2",
    ]
    if grade is not None:
        argv += ["--eos-priority", grade]
    return argv + list(extra)


def _task(repo: Path, task_id: str):
    backlog, _ = store.load_backlog(repo)
    return backlog.tasks[task_id]


class TestGradeIsRequired:
    """Rule 1·3 — 등급 없는 신규 등재는 **거부**된다(감사 A1의 집행 지점)."""

    def test_add_without_grade_is_rejected(self, seeded_repo: Path, capsys) -> None:
        track = _open_track(seeded_repo)
        assert cli.main(_add_argv("S2-81-no-grade", track, None)) == 1
        # 거부만으로는 부족하다 — 사람이 *무엇을 판정해야 하는지* 알아야 재시도가 가능하다.
        err = capsys.readouterr().err
        assert "--eos-priority" in err
        assert "폐쇄루프가 깨지는가" in err, "거부 메시지에 판정 질문이 없다"
        assert not (seeded_repo / "backlog" / "tasks" / "S2-81-no-grade.yaml").exists()

    def test_add_with_unknown_grade_is_rejected(self, seeded_repo: Path) -> None:
        track = _open_track(seeded_repo)
        assert cli.main(_add_argv("S2-82-bad-grade", track, "P9")) == 1

    def test_add_with_grade_succeeds_and_persists_it(self, seeded_repo: Path) -> None:
        """변별력의 반대쪽 — 등급을 주면 통과하고, 그 값이 YAML에 남는다."""
        track = _open_track(seeded_repo)
        assert cli.main(_add_argv("S2-83-graded", track, "P1")) == 0
        assert _task(seeded_repo, "S2-83-graded").eos_priority == "P1"


class TestOneInOneOut:
    """Rule 4 — P0 예산에 닿으면 교환 없이는 P0를 늘릴 수 없다."""

    def _fill_budget(self, repo: Path, track: str, n: int) -> list[str]:
        """예산을 n건까지 채운다(예산 = policy.eos_p0_budget)."""
        ids = []
        for i in range(n):
            tid = f"S2-{40 + i}-p0-fill"
            assert cli.main(_add_argv(tid, track, "P0")) == 0
            ids.append(tid)
        return ids

    def _set_budget(self, repo: Path, budget: int) -> None:
        policy, _ = store.load_policy(repo)
        policy.eos_p0_budget = budget
        store.save_policy(repo, policy)

    def test_p0_under_budget_needs_no_swap(self, seeded_repo: Path) -> None:
        """예산 여유 구간에서는 교환이 필요 없다 — 규칙이 상시 차단이면 등재가 봉쇄된다."""
        self._set_budget(seeded_repo, 3)
        track = _open_track(seeded_repo)
        assert cli.main(_add_argv("S2-40-p0-fill", track, "P0")) == 0

    def test_p0_at_budget_without_swap_is_rejected(self, seeded_repo: Path, capsys) -> None:
        self._set_budget(seeded_repo, 2)
        track = _open_track(seeded_repo)
        self._fill_budget(seeded_repo, track, 2)
        assert cli.main(_add_argv("S2-60-over-budget", track, "P0")) == 1
        err = capsys.readouterr().err
        assert "예산 소진" in err and "--swap-out" in err

    def test_swap_admits_the_new_p0_and_demotes_the_old(self, seeded_repo: Path) -> None:
        """교환의 본체 — 들어온 만큼 나간다. 양쪽 모두 디스크에 남아야 회계가 맞는다."""
        self._set_budget(seeded_repo, 2)
        track = _open_track(seeded_repo)
        filled = self._fill_budget(seeded_repo, track, 2)
        assert cli.main(_add_argv("S2-61-swapped-in", track, "P0", "--swap-out", filled[0])) == 0
        assert _task(seeded_repo, "S2-61-swapped-in").eos_priority == "P0"
        out = _task(seeded_repo, filled[0])
        assert out.eos_priority == "P1", "교환 대상이 강등되지 않았다 — 예산 회계가 어긋난다"
        assert "One In" in out.notes, "강등 사유가 notes에 남지 않았다"

    def test_swap_out_must_name_a_live_p0(self, seeded_repo: Path) -> None:
        """종결 P0는 예산을 점유하지 않으므로 내줄 자리가 없다(무상 추가 방지)."""
        self._set_budget(seeded_repo, 2)
        track = _open_track(seeded_repo)
        filled = self._fill_budget(seeded_repo, track, 2)
        assert cli.main(["start", filled[0]]) == 0
        assert cli.main(["done", filled[0], "--artifact", "#1"]) == 0
        assert cli.main(_add_argv("S2-62-bad-swap", track, "P0", "--swap-out", filled[0])) == 1

    def test_swap_out_rejects_a_non_p0_target(self, seeded_repo: Path) -> None:
        self._set_budget(seeded_repo, 1)
        track = _open_track(seeded_repo)
        self._fill_budget(seeded_repo, track, 1)
        assert cli.main(_add_argv("S2-63-p1", track, "P1")) == 0
        assert cli.main(_add_argv("S2-64-x", track, "P0", "--swap-out", "S2-63-p1")) == 1

    def test_swap_out_is_rejected_when_budget_has_room(self, seeded_repo: Path) -> None:
        """여유가 있는데 교환하면 P0가 *줄어든다* — 규칙의 의도와 반대다."""
        self._set_budget(seeded_repo, 5)
        track = _open_track(seeded_repo)
        filled = self._fill_budget(seeded_repo, track, 1)
        assert cli.main(_add_argv("S2-65-x", track, "P0", "--swap-out", filled[0])) == 1

    def test_swap_out_is_rejected_for_non_p0_additions(self, seeded_repo: Path) -> None:
        track = _open_track(seeded_repo)
        assert cli.main(_add_argv("S2-66-x", track, "P2", "--swap-out", "S2-40-p0-fill")) == 1


class TestBackfillPathIsTheCli:
    """기존 태스크의 등급 지정은 amend를 통해서만 — 대장 손편집 금지의 대응 경로."""

    def test_amend_sets_the_grade_and_records_the_reason(self, seeded_repo: Path) -> None:
        track = _open_track(seeded_repo)
        assert cli.main(_add_argv("S2-70-backfill", track, "P3")) == 0
        assert (
            cli.main(
                ["amend", "S2-70-backfill", "--eos-priority", "P1", "--reason", "관여도 재판정"]
            )
            == 0
        )
        task = _task(seeded_repo, "S2-70-backfill")
        assert task.eos_priority == "P1"
        assert "관여도 재판정" in task.notes

    def test_amend_rejects_a_noop_grade(self, seeded_repo: Path) -> None:
        track = _open_track(seeded_repo)
        assert cli.main(_add_argv("S2-71-noop", track, "P1")) == 0
        assert cli.main(["amend", "S2-71-noop", "--eos-priority", "P1", "--reason", "무변경"]) == 1


class TestGrandfatherExpiresByMachine:
    """만료 없는 유예 금지 — 유예의 끝을 날짜가 아니라 **게이트 상태**가 정한다.

    선례: import-linter `unmatched_ignore_imports_alerting`(빚을 갚으면 CI가 줄을 지우라고
    말한다). 여기서는 관여도 트리아지가 끝나는 순간 미분류가 위반이 된다 — 그 시점부터
    "아직 분류 근거가 없다"는 변명이 사실이 아니게 되기 때문이다.
    """

    def _gate(self, repo: Path, status: str) -> None:
        backlog, _ = store.load_backlog(repo)
        gates = list(backlog.gates.values())
        from models import Gate

        gates.append(
            Gate(
                id=EOS_PRIORITY_BACKFILL_GATE,
                title="관여도 트리아지 (테스트 픽스처)",
                kind="decision",
                status=status,
                requested="2026-08-31",
                evidence="테스트 픽스처" if status != "pending" else None,
                # HARN-174: pending 게이트는 여는 작업 또는 입력 없음 사유 중 하나가 필수다
                no_inputs_reason="테스트 픽스처" if status == "pending" else None,
            )
        )
        store.save_gates(repo, gates)

    def test_ungraded_tasks_are_tolerated_while_the_gate_is_pending(
        self, seeded_repo: Path
    ) -> None:
        """유예 유효 구간 — 시드 태스크는 전부 등급이 없고, 그래도 green이어야 한다."""
        self._gate(seeded_repo, "pending")
        backlog, errs = store.load_backlog(seeded_repo)
        assert any(t.eos_priority is None for t in backlog.tasks.values()), "픽스처 전제 붕괴"
        assert store.validate_backlog(backlog, errs) == []

    def test_clearing_the_gate_turns_ungraded_tasks_into_a_violation(
        self, seeded_repo: Path
    ) -> None:
        """만료 — 게이트가 clear되면 같은 대장이 red가 된다(변별력의 반대쪽)."""
        self._gate(seeded_repo, "cleared")
        backlog, errs = store.load_backlog(seeded_repo)
        errors = store.validate_backlog(backlog, errs)
        assert errors, "그랜드파더가 만료되지 않았다 — 유예가 영구화된다"
        joined = "\n".join(errors)
        assert "eos_priority 미지정" in joined
        assert "amend" in joined, "처방(정정 명령)이 없으면 판정이 막다른 골목이 된다"

    def test_expiry_reports_one_error_not_one_per_task(self, seeded_repo: Path) -> None:
        """태스크 수만큼 오류를 쏟으면 판정이 아니라 소음이 된다."""
        self._gate(seeded_repo, "cleared")
        backlog, errs = store.load_backlog(seeded_repo)
        hits = [e for e in store.validate_backlog(backlog, errs) if "eos_priority 미지정" in e]
        assert len(hits) == 1

    def test_terminal_tasks_are_exempt_from_the_expiry(self, seeded_repo: Path) -> None:
        """끝난 일에 등급을 소급하는 것은 분류가 아니라 장부 청소다."""
        track = _open_track(seeded_repo)
        assert cli.main(_add_argv("S2-72-live", track, "P2")) == 0
        backlog, _ = store.load_backlog(seeded_repo)
        for task in backlog.tasks.values():
            if task.eos_priority is None:
                task.status = "done"
                task.session = None
                task.artifacts = ["#1"]
                store.save_task(seeded_repo, task)
        self._gate(seeded_repo, "cleared")
        backlog, errs = store.load_backlog(seeded_repo)
        hits = [e for e in store.validate_backlog(backlog, errs) if "eos_priority 미지정" in e]
        assert hits == [], f"종결 태스크가 만료 대상에 잡혔다: {hits}"
