"""HARN-174 — 게이트를 태스크 그래프의 노드로 편입: 계약 동결.

배경(2026-09-22~24 · 계열 `gate-resolution-path-unlinked` 3회 — 세 번 모두 사람이 읽다가 발견):
  사고 1 (09-22) P3-00 이 자기가 증거를 대야 할 진입 게이트를 `requires_gates`로 걸어, 게이트를
         여는 작업이 그 게이트를 기다리는 교착이 됐다.
  사고 2 (09-23) 게이트 병합 뒤 EOS-50 이 자기를 판정 대상으로 삼는 통합 게이트를 요구했다.
  사고 3 (09-24) 재판정문이 PASS 경로로 EOS-24·EOS-124 를 지목했지만 재판정 태스크에 연결되지
         않았다(FAIL 판정 기록에 소유 태스크가 없었다).
세 사고 모두 **게이트가 그래프 밖에 있어서** 어떤 검사도 볼 대상이 없었다. 순환 검사와 선택기가
태스크끼리만 봤다.

이 파일이 절(節)마다 동결하는 것 — 각 클래스는 "그 절이 없으면 무엇이 통과하는가"의 반례를
담는다(CLAUDE.md 「픽스처가 그 절을 실제로 밟는가」). 뮤테이션 하네스는
`scripts/harness/verify_gate_graph_discrimination.py`가 이 파일을 대상으로 돌린다.
  v2-1·v2-6 입력 필수     — pending 게이트는 depends_on / no_inputs_reason 중 정확히 하나
  v2-2      순환          — 게이트를 지나는 고리를 쓰기 시점에 거부 + validate가 경로로 보고
  v2-3      막다른 길     — 대장에 없거나 cancelled인 입력
  v2-4      전이 해금 수  — 게이트 너머까지 끝까지 센 미종결 후속
  v2-5      대기 경로     — 게이트 뒤의 여는 작업까지 보인다
  v2-7      clear 집행    — 입력 미완이면 clear 거부(waive 예외)
  v2-8      FAIL 기록     — 소유 태스크 없는 FAIL 판정 거부 + 지목·미연결을 validate가 잡는다
거부는 전부 **대장 바이트 동일**까지 확인한다 — exit 1만 보면 "쓰고 나서 실패"도 통과한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import selector
import store
from models import Gate

import backlog as cli

_NO_INPUTS = "테스트 픽스처 — 입력 태스크 없음"


@pytest.fixture
def repo(git_repo: Path, monkeypatch) -> Path:
    monkeypatch.chdir(git_repo)
    assert cli.main(["seed"]) == 0
    return git_repo


def _add(task_id: str, *extra: str, track: str = "math-completion", stage: str = "S1") -> None:
    rc = cli.main(
        [
            "add",
            "--eos-priority",
            "P2",
            "--id",
            task_id,
            "--title",
            f"HARN-174 테스트 {task_id}",
            "--track",
            track,
            "--stage",
            stage,
            *extra,
        ]
    )
    assert rc == 0, f"픽스처 태스크 등재 실패: {task_id}"


def _gate_add(gate_id: str, *extra: str, kind: str = "decision") -> int:
    return cli.main(
        ["gates", "add", gate_id, "--title", f"테스트 게이트 {gate_id}", "--kind", kind, *extra]
    )


def _load(root: Path):
    backlog, errors = store.load_backlog(root)
    assert errors == [], errors
    return backlog


def _set_status(root: Path, task_id: str, status: str) -> None:
    """상태 주입 — 전이 CLI(start/done)는 PR 증적·claim까지 요구해 이 파일의 관심사가 아니다."""
    backlog = _load(root)
    task = backlog.tasks[task_id]
    task.status = status
    if status == "done":
        task.artifacts = ["PR #1 (테스트 픽스처)"]
    store.save_task(root, task)


def _save_gates(root: Path, backlog) -> None:
    store.save_gates(root, sorted(backlog.gates.values(), key=lambda g: g.id))


def _gates_bytes(root: Path) -> bytes:
    return (root / "backlog" / "gates.yaml").read_bytes()


def _task_bytes(root: Path, task_id: str) -> bytes:
    return (root / "backlog" / "tasks" / f"{task_id}.yaml").read_bytes()


def _errors(root: Path) -> list[str]:
    backlog, schema = store.load_backlog(root)
    return store.validate_backlog(backlog, schema)


# ── v2-1 · v2-6 입력 필수 ─────────────────────────────────────────────────────


class TestInputsRequired:
    def test_add_without_inputs_rejected_and_writes_nothing(self, repo: Path, capsys):
        before = _gates_bytes(repo)
        assert _gate_add("G-harn174-bare") == 1
        # 선검사 고유 문구로 판정한다 — validate 폴백도 "여는 작업이 없다"를 내므로 그 문구로는
        # 선검사가 빠져도 통과한다(어느 방어선이 잡았는지 구별해야 절의 변별력이 생긴다).
        assert "(반복 지정)" in capsys.readouterr().err
        assert _gates_bytes(repo) == before

    def test_add_with_both_rejected(self, repo: Path, capsys):
        _add("S1-40-opener")
        capsys.readouterr()
        before = _gates_bytes(repo)
        assert _gate_add("G-harn174-both", "--depends", "S1-40-opener", "--no-inputs", "x") == 1
        assert "함께 줄 수 없다" in capsys.readouterr().err  # 선검사 고유 문구(폴백과 구별)
        assert _gates_bytes(repo) == before

    def test_blank_no_inputs_reason_is_not_a_reason(self, repo: Path):
        before = _gates_bytes(repo)
        assert _gate_add("G-harn174-blank", "--no-inputs", "   ") == 1
        assert _gates_bytes(repo) == before

    def test_add_with_reason_accepted(self, repo: Path):
        """대조군 — 사유가 있으면 통과하고 사유가 대장에 남는다."""
        assert _gate_add("G-harn174-human", "--no-inputs", _NO_INPUTS, kind="human") == 0
        assert _load(repo).gates["G-harn174-human"].no_inputs_reason == _NO_INPUTS

    def test_add_with_depends_round_trips(self, repo: Path):
        """대조군 — 입력이 대장에 리스트로 남고 되읽힌다."""
        _add("S1-40-opener")
        _add("S1-41-opener-b")
        rc = _gate_add("G-harn174-in", "--depends", "S1-40-opener", "--depends", "S1-41-opener-b")
        assert rc == 0
        gate = _load(repo).gates["G-harn174-in"]
        assert gate.depends_on == ["S1-40-opener", "S1-41-opener-b"]
        assert gate.no_inputs_reason is None
        assert _errors(repo) == []

    def test_validate_flags_pending_gate_without_inputs(self, repo: Path):
        backlog = _load(repo)
        backlog.gates["G-harn174-bare"] = Gate(id="G-harn174-bare", title="입력 없음")
        _save_gates(repo, backlog)
        assert any("G-harn174-bare" in e and "여는 작업이 없다" in e for e in _errors(repo))

    def test_validate_flags_both_fields(self, repo: Path):
        _add("S1-40-opener")
        backlog = _load(repo)
        backlog.gates["G-harn174-both"] = Gate(
            id="G-harn174-both",
            title="둘 다",
            depends_on=["S1-40-opener"],
            no_inputs_reason="x",
        )
        _save_gates(repo, backlog)
        assert any("G-harn174-both" in e and "둘 다 있다" in e for e in _errors(repo))

    def test_cleared_gate_without_inputs_is_not_flagged(self, repo: Path):
        """대조군 — 통과한 게이트는 아무것도 막지 않으므로 소급하지 않는다."""
        backlog = _load(repo)
        backlog.gates["G-harn174-old"] = Gate(
            id="G-harn174-old", title="과거", status="cleared", evidence="PR #1"
        )
        _save_gates(repo, backlog)
        assert not any("G-harn174-old" in e for e in _errors(repo))

    def test_empty_input_fields_are_not_serialized(self, repo: Path):
        """입력 두 칸은 비어 있으면 쓰지 않는다 — 통과 게이트 전건에 빈 줄을 퍼뜨리지 않는다."""
        text = _gates_bytes(repo).decode("utf-8")
        assert "depends_on: []" not in text
        assert "no_inputs_reason: null" not in text


# ── v2-2 순환 — 사고 1·2 재현 ─────────────────────────────────────────────────


class TestCycleThroughGate:
    def test_incident1_opener_cannot_wait_on_its_own_gate(self, repo: Path, capsys):
        """사고 1 — 진입 게이트의 증거를 대는 태스크가 그 게이트를 요구하면 교착이다."""
        _add("S1-40-acceptance-check")
        assert _gate_add("G-harn174-entry", "--depends", "S1-40-acceptance-check") == 0
        capsys.readouterr()
        before = _task_bytes(repo, "S1-40-acceptance-check")
        rc = cli.main(
            ["amend", "S1-40-acceptance-check", "--gate", "G-harn174-entry", "--reason", "x"]
        )
        assert rc == 1
        err = capsys.readouterr().err
        assert "순환을 만든다" in err
        # 경로에 게이트 ID가 보여야 한다(v2-2) — 게이트가 끼었다는 사실이 이 사고의 본질이다
        assert "G-harn174-entry → S1-40-acceptance-check → G-harn174-entry" in err
        assert _task_bytes(repo, "S1-40-acceptance-check") == before

    def test_incident1_reverse_order_rejected(self, repo: Path, capsys):
        """같은 고리를 반대 순서로 만들어도(게이트 먼저 부착 → 입력 나중) 거부된다."""
        assert _gate_add("G-harn174-entry", "--no-inputs", _NO_INPUTS) == 0
        _add("S1-40-acceptance-check", "--gates", "G-harn174-entry")
        capsys.readouterr()
        before = _gates_bytes(repo)
        rc = cli.main(
            [
                "gates",
                "amend",
                "G-harn174-entry",
                "--depends",
                "S1-40-acceptance-check",
                "--reason",
                "x",
            ]
        )
        assert rc == 1
        assert "순환을 만든다" in capsys.readouterr().err
        assert _gates_bytes(repo) == before

    def test_incident2_indirect_cycle_through_judgment_task(self, repo: Path, capsys):
        """사고 2 — 통합 게이트를 판정하는 태스크가 그 게이트를 요구하는 태스크에 의존한다."""
        _add("S1-50-release-merge")
        _add("S1-51-integrated-judgment")
        assert _gate_add("G-harn174-w3", "--depends", "S1-51-integrated-judgment") == 0
        assert (
            cli.main(["amend", "S1-50-release-merge", "--gate", "G-harn174-w3", "--reason", "x"])
            == 0
        )
        capsys.readouterr()
        before = _task_bytes(repo, "S1-51-integrated-judgment")
        rc = cli.main(
            [
                "amend",
                "S1-51-integrated-judgment",
                "--depends",
                "S1-50-release-merge",
                "--reason",
                "x",
            ]
        )
        assert rc == 1
        err = capsys.readouterr().err
        assert "순환을 만든다" in err and "G-harn174-w3" in err
        assert _task_bytes(repo, "S1-51-integrated-judgment") == before

    def test_add_path_rejects_cycle_closed_by_new_task(self, repo: Path, capsys):
        """`add --gates`도 같은 그래프로 판정한다 — 게이트 입력이 아직 없는 ID를 가리킨 상태에서
        그 ID로 새 태스크를 만들며 게이트를 요구하면 고리가 닫힌다."""
        backlog = _load(repo)
        backlog.gates["G-harn174-pre"] = Gate(
            id="G-harn174-pre", title="선등재", depends_on=["S1-60-future"]
        )
        _save_gates(repo, backlog)
        capsys.readouterr()
        rc = cli.main(
            [
                "add",
                "--eos-priority",
                "P2",
                "--id",
                "S1-60-future",
                "--title",
                "미래 태스크",
                "--track",
                "math-completion",
                "--stage",
                "S1",
                "--gates",
                "G-harn174-pre",
            ]
        )
        assert rc == 1
        assert "순환" in capsys.readouterr().err
        assert not (repo / "backlog" / "tasks" / "S1-60-future.yaml").exists()

    def test_validate_reports_cycle_path_with_gate_id(self, repo: Path):
        _add("S1-40-acceptance-check")
        backlog = _load(repo)
        backlog.gates["G-harn174-entry"] = Gate(
            id="G-harn174-entry", title="진입", depends_on=["S1-40-acceptance-check"]
        )
        backlog.tasks["S1-40-acceptance-check"].requires_gates = ["G-harn174-entry"]
        _save_gates(repo, backlog)
        store.save_task(repo, backlog.tasks["S1-40-acceptance-check"])
        cycle_errors = [e for e in _errors(repo) if "순환 참조 검출" in e]
        assert len(cycle_errors) == 1
        assert "G-harn174-entry" in cycle_errors[0]
        assert "S1-40-acceptance-check" in cycle_errors[0]

    def test_track_entry_gate_is_an_edge(self, repo: Path, capsys):
        """진입 게이트 → 그 트랙의 모든 태스크 — 진입 게이트의 입력이 트랙 안에 있으면 교착이다."""
        _add("E1-95-expansion-judgment", track="subject-expansion", stage="E1")
        capsys.readouterr()
        before = _gates_bytes(repo)
        rc = cli.main(
            [
                "gates",
                "amend",
                "G-s5-subject-expansion",
                "--depends",
                "E1-95-expansion-judgment",
                "--reason",
                "x",
            ]
        )
        assert rc == 1
        assert "순환을 만든다" in capsys.readouterr().err
        assert _gates_bytes(repo) == before

    def test_task_only_cycle_still_detected(self, repo: Path):
        """회귀 — 태스크끼리의 고리도 같은 그래프가 잡는다(검사기는 하나)."""
        _add("S1-70-a")
        _add("S1-71-b", "--depends", "S1-70-a")
        backlog = _load(repo)
        backlog.tasks["S1-70-a"].depends_on = ["S1-71-b"]
        store.save_task(repo, backlog.tasks["S1-70-a"])
        assert store.detect_cycle(_load(repo)) == ["S1-70-a", "S1-71-b"]
        assert any("순환 참조 검출" in e for e in _errors(repo))

    def test_healthy_chain_is_green(self, repo: Path):
        """대조군 — 정상 사슬(여는 작업 → 게이트 → 기다리는 작업)은 GREEN."""
        _add("S1-40-opener")
        assert _gate_add("G-harn174-ok", "--depends", "S1-40-opener") == 0
        _add("S1-41-waiter", "--gates", "G-harn174-ok")
        assert _errors(repo) == []


# ── v2-3 막다른 길 ────────────────────────────────────────────────────────────


class TestDeadEnd:
    def test_missing_input_rejected_at_write(self, repo: Path, capsys):
        before = _gates_bytes(repo)
        assert _gate_add("G-harn174-ghost", "--depends", "NOPE-99-ghost") == 1
        # 선검사 고유 문구 — validate 폴백은 "depends_on '…' 미존재"라고 한다
        assert "입력 'NOPE-99-ghost' 가 대장에 없다" in capsys.readouterr().err
        assert _gates_bytes(repo) == before

    def test_cancelled_input_rejected_at_write(self, repo: Path, capsys):
        _add("S1-40-dropped")
        _set_status(repo, "S1-40-dropped", "cancelled")
        before = _gates_bytes(repo)
        assert _gate_add("G-harn174-dead", "--depends", "S1-40-dropped") == 1
        # 선검사 고유 문구 — validate 폴백은 "depends_on '…' 가 cancelled"라고 한다
        assert "입력 'S1-40-dropped' 는 cancelled" in capsys.readouterr().err
        assert _gates_bytes(repo) == before

    def test_validate_flags_missing_input(self, repo: Path):
        backlog = _load(repo)
        backlog.gates["G-harn174-ghost"] = Gate(
            id="G-harn174-ghost", title="유령", depends_on=["NOPE-99-ghost"]
        )
        _save_gates(repo, backlog)
        assert any("G-harn174-ghost" in e and "미존재" in e for e in _errors(repo))

    def test_validate_flags_cancelled_input_of_pending_gate(self, repo: Path):
        _add("S1-40-dropped")
        _set_status(repo, "S1-40-dropped", "cancelled")
        backlog = _load(repo)
        backlog.gates["G-harn174-dead"] = Gate(
            id="G-harn174-dead", title="막힘", depends_on=["S1-40-dropped"]
        )
        _save_gates(repo, backlog)
        assert any("G-harn174-dead" in e and "cancelled" in e for e in _errors(repo))

    def test_cancelled_input_of_cleared_gate_is_not_flagged(self, repo: Path):
        """대조군 — 이미 통과한 게이트는 입력이 취소돼도 막는 것이 없다."""
        _add("S1-40-dropped")
        _set_status(repo, "S1-40-dropped", "cancelled")
        backlog = _load(repo)
        backlog.gates["G-harn174-done"] = Gate(
            id="G-harn174-done",
            title="통과",
            status="cleared",
            evidence="PR #1",
            depends_on=["S1-40-dropped"],
        )
        _save_gates(repo, backlog)
        assert not any("G-harn174-done" in e for e in _errors(repo))

    def test_cancel_of_pending_gate_input_rejected(self, repo: Path, capsys):
        _add("S1-40-opener")
        assert _gate_add("G-harn174-in", "--depends", "S1-40-opener") == 0
        capsys.readouterr()
        before = _task_bytes(repo, "S1-40-opener")
        assert cli.main(["cancel", "S1-40-opener", "--reason", "불필요"]) == 1
        err = capsys.readouterr().err
        assert "G-harn174-in" in err and "--remove-depends S1-40-opener" in err
        assert _task_bytes(repo, "S1-40-opener") == before

    def test_cancel_after_input_detached_passes(self, repo: Path):
        """대조군 — 게이트 입력을 먼저 바꾸면 취소된다(정정 경로가 실재한다)."""
        _add("S1-40-opener")
        _add("S1-41-replacement")
        assert _gate_add("G-harn174-in", "--depends", "S1-40-opener") == 0
        rc = cli.main(
            [
                "gates",
                "amend",
                "G-harn174-in",
                "--remove-depends",
                "S1-40-opener",
                "--depends",
                "S1-41-replacement",
                "--reason",
                "입력 교체",
            ]
        )
        assert rc == 0
        assert cli.main(["cancel", "S1-40-opener", "--reason", "불필요"]) == 0
        assert _errors(repo) == []

    def test_rename_carries_gate_input(self, repo: Path):
        _add("S1-40-opener")
        assert _gate_add("G-harn174-in", "--depends", "S1-40-opener") == 0
        assert cli.main(["rename", "S1-40-opener", "S1-42-opener-renamed", "--reason", "x"]) == 0
        gate = _load(repo).gates["G-harn174-in"]
        assert gate.depends_on == ["S1-42-opener-renamed"]
        assert _errors(repo) == []


# ── v2-7 clear 집행 ───────────────────────────────────────────────────────────


class TestClearEnforcement:
    def _setup(self, repo: Path) -> None:
        _add("S1-40-opener")
        assert _gate_add("G-harn174-in", "--depends", "S1-40-opener") == 0

    def test_clear_rejected_while_input_unfinished(self, repo: Path, capsys):
        self._setup(repo)
        capsys.readouterr()
        before = _gates_bytes(repo)
        rc = cli.main(["gates", "clear", "G-harn174-in", "--evidence", "main abc1234 기준 확인"])
        assert rc == 1
        assert "S1-40-opener(todo)" in capsys.readouterr().err
        assert _gates_bytes(repo) == before

    def test_clear_passes_after_input_done(self, repo: Path):
        """대조군 — 입력이 done이면 통과한다(검사가 항상 거부하는 위장이 아니다)."""
        self._setup(repo)
        _set_status(repo, "S1-40-opener", "done")
        rc = cli.main(["gates", "clear", "G-harn174-in", "--evidence", "main abc1234 기준 확인"])
        assert rc == 0
        assert _load(repo).gates["G-harn174-in"].status == "cleared"

    def test_waive_is_exempt(self, repo: Path):
        """waive는 Kiki의 예외 경로 — 입력 미완이어도 면제할 수 있다."""
        self._setup(repo)
        assert cli.main(["gates", "waive", "G-harn174-in", "--reason", "요건 면제"]) == 0
        assert _load(repo).gates["G-harn174-in"].status == "waived"


# ── v2-8 FAIL 판정 기록 — 사고 3 재현 ─────────────────────────────────────────


class TestFailVerdict:
    _EVIDENCE = "docs/reviews/judgment.md · main abc1234"

    def _setup(self, repo: Path) -> None:
        _add("S1-40-rejudgment")
        assert _gate_add("G-harn174-gate2", "--depends", "S1-40-rejudgment") == 0

    def _fail(self, *extra: str) -> int:
        return cli.main(
            [
                "gates",
                "amend",
                "G-harn174-gate2",
                "--verdict",
                "FAIL",
                "--reason",
                "재판정 FAIL",
                *extra,
            ]
        )

    def test_incident3_fail_without_owner_rejected(self, repo: Path, capsys):
        """사고 3 — FAIL만 적고 미충족 항목의 소유 태스크를 잇지 않으면 거부한다."""
        self._setup(repo)
        capsys.readouterr()
        before = _gates_bytes(repo)
        assert self._fail("--evidence", self._EVIDENCE) == 1
        assert "소유 태스크가 없다" in capsys.readouterr().err
        assert _gates_bytes(repo) == before

    def test_done_owner_does_not_count(self, repo: Path):
        """이미 끝난 태스크는 미충족 항목의 소유자가 될 수 없다."""
        self._setup(repo)
        _add("S1-41-finished")
        _set_status(repo, "S1-41-finished", "done")
        before = _gates_bytes(repo)
        assert self._fail("--evidence", self._EVIDENCE, "--depends", "S1-41-finished") == 1
        assert _gates_bytes(repo) == before

    def test_fail_with_open_owner_is_recorded(self, repo: Path):
        """대조군 — 미종결 소유 태스크를 새로 붙이면 기록되고 입력 간선이 생긴다."""
        self._setup(repo)
        _add("S1-42-fix-a")
        assert self._fail("--evidence", self._EVIDENCE, "--depends", "S1-42-fix-a") == 0
        gate = _load(repo).gates["G-harn174-gate2"]
        assert gate.depends_on == ["S1-40-rejudgment", "S1-42-fix-a"]
        assert gate.status == "pending"
        assert "verdict FAIL · owners: S1-42-fix-a · evidence: " in gate.corrections[-1]
        assert _errors(repo) == []

    def test_verdict_rejected_on_human_gate(self, repo: Path):
        _add("S1-42-fix-a")
        assert _gate_add("G-harn174-human", "--no-inputs", _NO_INPUTS, kind="human") == 0
        before = _gates_bytes(repo)
        rc = cli.main(
            [
                "gates",
                "amend",
                "G-harn174-human",
                "--verdict",
                "FAIL",
                "--evidence",
                self._EVIDENCE,
                "--depends",
                "S1-42-fix-a",
                "--reason",
                "x",
            ]
        )
        assert rc == 1
        assert _gates_bytes(repo) == before

    def test_verdict_needs_judgment_base(self, repo: Path):
        self._setup(repo)
        _add("S1-42-fix-a")
        before = _gates_bytes(repo)
        assert self._fail("--evidence", "판정문 참고", "--depends", "S1-42-fix-a") == 1
        assert _gates_bytes(repo) == before

    def test_evidence_without_verdict_rejected(self, repo: Path, capsys):
        self._setup(repo)
        capsys.readouterr()
        before = _gates_bytes(repo)
        rc = cli.main(
            ["gates", "amend", "G-harn174-gate2", "--evidence", self._EVIDENCE, "--reason", "x"]
        )
        assert rc == 1
        # 이 절이 없어도 "정정할 것이 없다"로 거부되므로 exit code만으로는 절을 밟지 않는다
        assert "--verdict FAIL 과 함께만" in capsys.readouterr().err
        assert _gates_bytes(repo) == before

    def _inject_record(self, repo: Path, owners: list[str]) -> None:
        backlog = _load(repo)
        gate = backlog.gates["G-harn174-gate2"]
        gate.corrections = [
            "[2026-09-24] " + store.format_fail_verdict(owners, self._EVIDENCE) + " — 재판정"
        ]
        _save_gates(repo, backlog)

    def test_validate_flags_owner_named_but_not_linked(self, repo: Path):
        """사고 3의 대장 상태 — 판정은 소유 태스크를 지목했는데 게이트 상류에 연결이 없다."""
        self._setup(repo)
        _add("S1-42-fix-a")
        self._inject_record(repo, ["S1-42-fix-a"])
        errors = [e for e in _errors(repo) if "G-harn174-gate2" in e]
        assert len(errors) == 1 and "S1-42-fix-a" in errors[0]

    def test_validate_flags_zero_owner_record(self, repo: Path):
        self._setup(repo)
        self._inject_record(repo, [])
        assert any("G-harn174-gate2" in e and "0건" in e for e in _errors(repo))

    def test_owner_linked_through_rejudgment_task_is_green(self, repo: Path):
        """대조군 — 소유 태스크가 재판정 태스크의 선행이면(게이트 입력이 아니어도) 연결이다."""
        self._setup(repo)
        _add("S1-42-fix-a")
        assert (
            cli.main(["amend", "S1-40-rejudgment", "--depends", "S1-42-fix-a", "--reason", "x"])
            == 0
        )
        self._inject_record(repo, ["S1-42-fix-a"])
        assert _errors(repo) == []


# ── v2-4 전이 해금 수 ─────────────────────────────────────────────────────────


def _bottleneck_fixture(repo: Path) -> None:
    """A → J(판정) → G → P1·P2·P3.  B → C1·C2(직접 후속 2건)."""
    _add("S1-80-fix-a")
    _add("S1-81-judgment", "--depends", "S1-80-fix-a")
    assert _gate_add("G-harn174-bottleneck", "--depends", "S1-81-judgment") == 0
    for i in (1, 2, 3):
        _add(f"S1-8{1 + i}-phase-{i}", "--gates", "G-harn174-bottleneck")
    _add("S1-90-fix-b")
    _add("S1-91-child-1", "--depends", "S1-90-fix-b")
    _add("S1-92-child-2", "--depends", "S1-90-fix-b")


class TestTransitiveUnlock:
    def test_count_follows_through_gate(self, repo: Path):
        _bottleneck_fixture(repo)
        backlog = _load(repo)
        # 종전 정의(직접 후속)라면 1 — J 하나. 게이트 너머 P1~P3까지 따라가면 4.
        assert selector.unblock_count(backlog, backlog.tasks["S1-80-fix-a"]) == 4
        assert selector.unblock_count(backlog, backlog.tasks["S1-90-fix-b"]) == 2

    def test_passed_gate_stops_the_walk(self, repo: Path):
        """이미 통과한 게이트 너머는 이 태스크를 기다리지 않는다."""
        _bottleneck_fixture(repo)
        backlog = _load(repo)
        gate = backlog.gates["G-harn174-bottleneck"]
        gate.status, gate.evidence = "waived", None
        gate.notes = "테스트 면제"
        _save_gates(repo, backlog)
        backlog = _load(repo)
        assert selector.unblock_count(backlog, backlog.tasks["S1-80-fix-a"]) == 1

    def test_finished_task_stops_the_walk(self, repo: Path):
        _bottleneck_fixture(repo)
        _set_status(repo, "S1-81-judgment", "done")
        backlog = _load(repo)
        assert selector.unblock_count(backlog, backlog.tasks["S1-80-fix-a"]) == 0

    def test_ordering_prefers_the_real_bottleneck(self, repo: Path):
        """같은 stage·priority에서 게이트 너머 4건을 여는 A가 직접 2건인 B보다 앞선다.
        종전 정의라면 B(2) > A(1)로 순서가 반대였다 — 이 단언이 정의 변경을 동결한다."""
        _bottleneck_fixture(repo)
        ready, _ = selector.candidates(_load(repo))
        ids = [t.id for t in ready]
        assert ids.index("S1-80-fix-a") < ids.index("S1-90-fix-b")

    def test_board_uses_the_same_value(self, repo: Path):
        import board

        _bottleneck_fixture(repo)
        cards = {c.id: c for c in board.build_tasks(_load(repo))}
        assert cards["S1-80-fix-a"].unlocks == 4


# ── v2-5 대기 경로 ────────────────────────────────────────────────────────────


class TestWaitChain:
    def test_chain_reaches_the_opening_work(self, repo: Path):
        _bottleneck_fixture(repo)
        backlog = _load(repo)
        chain = selector.wait_chain(backlog, backlog.tasks["S1-82-phase-1"])
        assert chain == ["S1-82-phase-1", "G-harn174-bottleneck", "S1-81-judgment", "S1-80-fix-a"]

    def test_next_prints_the_chain(self, repo: Path, capsys):
        _bottleneck_fixture(repo)
        capsys.readouterr()
        assert cli.main(["next", "--no-remote"]) == 0
        out = capsys.readouterr().out
        assert "3건 ← G-harn174-bottleneck ← S1-81-judgment ← S1-80-fix-a" in out

    def test_chain_ending_at_gate_says_a_person_is_next(self, repo: Path, capsys):
        """입력이 모두 끝난 게이트에서 경로가 멈추면, 막고 있는 것은 작업이 아니라 사람 판정이다."""
        _bottleneck_fixture(repo)
        _set_status(repo, "S1-80-fix-a", "done")
        _set_status(repo, "S1-81-judgment", "done")
        capsys.readouterr()
        assert cli.main(["next", "--no-remote"]) == 0
        out = capsys.readouterr().out
        assert "3건 ← G-harn174-bottleneck (사람 판정 대기)" in out

    def test_status_json_carries_chain_and_inputs(self, repo: Path, capsys):
        _bottleneck_fixture(repo)
        capsys.readouterr()
        assert cli.main(["status", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        chains = {tuple(g["chain"]): g["tasks"] for g in payload["gate_waits"]}
        assert chains[("G-harn174-bottleneck", "S1-81-judgment", "S1-80-fix-a")] == [
            "S1-82-phase-1",
            "S1-83-phase-2",
            "S1-84-phase-3",
        ]
        gate = next(g for g in payload["pending_gates"] if g["id"] == "G-harn174-bottleneck")
        assert gate["inputs"] == [{"id": "S1-81-judgment", "status": "todo"}]

    def test_gates_show_prints_inputs_and_unlocks(self, repo: Path, capsys):
        _bottleneck_fixture(repo)
        capsys.readouterr()
        assert cli.main(["gates", "show", "G-harn174-bottleneck"]) == 0
        out = capsys.readouterr().out
        assert "S1-81-judgment(todo)" in out
        assert "대기 경로: G-harn174-bottleneck ← S1-81-judgment ← S1-80-fix-a" in out
        assert "3건" in out
