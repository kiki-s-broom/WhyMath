"""HARN-177 — 게이트 입력 태스크의 done이 판정 결과를 게이트에 넘긴다: 계약 동결.

배경(2026-09-25 · 계열 `gate-resolution-path-unlinked` **4회차**):
  HARN-174(#1324)가 21:41 UTC에 main에 착지한 뒤 22:10 UTC에 2차 재판정 결과(#1323)가 착지했다.
  판정은 FAIL이고 판정 세션은 3차 재판정 태스크를 새로 등재했다. 그러나 게이트
  `G-p3-entry-gate2-pass`에는 FAIL 판정도 3차 재판정 입력도 기록되지 않았다 — FAIL 기록 장치
  (`gates amend --verdict FAIL`)는 이미 main에 있었지만, 판정 태스크를 done으로 닫는 경로가
  그 호출을 요구하지 않았다. 대장은 게이트의 입력이 전부 끝났다고 보고 next·status가
  `(사람 판정 대기)`로 안내했고, 3차 재판정의 해금 수는 0으로 계산됐다(연결 시 15).
  **도구 존재 ≠ 호출 강제.** 1~3회차의 대책(HARN-174)은 도구를 만들었고, 이 파일이 동결하는
  것은 그 도구를 부르게 만드는 집행 지점이다.

이 파일이 절(節)마다 동결하는 것 — 각 클래스는 "그 절이 없으면 무엇이 통과하는가"의 반례를
담는다(CLAUDE.md 「픽스처가 그 절을 실제로 밟는가」). 뮤테이션 하네스
`scripts/harness/verify_gate_verdict_handoff_discrimination.py`가 이 파일을 대상으로 돌린다.
  ① done 인계    — pending decision 게이트의 입력을 닫는 done은 FAIL / PASS / 판정 무관 중 하나를
                   같은 호출에 실어야 한다. 아무것도 없으면 exit 1 + 대장 바이트 동일.
                   판정 결과는 태스크 증적이 아니라 게이트 corrections에 남는다.
  ② 표시 정직성  — 입력이 전부 done인데 그 상태의 판정 기록이 없으면 next·status·gates show가
                   '(사람 판정 대기)' 대신 '판정 결과 미기록'을 낸다.
  ③ 재현 픽스처  — 2026-09-25 실측 상태: 재판정 태스크가 FAIL 판정문과 함께 done이 되고 후속
                   재판정 태스크가 게이트에 연결되지 않은 상태. ①은 그 done을 거부하고 ②는 경고를
                   낸다. 정상 인계(FAIL + 소유 태스크 연결) 대조군은 GREEN.
  ⑥ 열린 상류 소유 — 이미 게이트의 열린 상류에 있는 미종결 태스크를 `--owner`로 지목해 새 부착
                   없이 FAIL을 기록한다. 열린 상류에 소유 태스크가 하나도 없으면 여전히 거부.
거부는 전부 **대장 바이트 동일**까지 확인한다 — exit 1만 보면 "쓰고 나서 실패"도 통과한다.

⑤ 한계(명시): 이 집행은 판정 태스크가 `done`을 거칠 때만 작동한다. 판정문만 쓰고 태스크를
닫지 않거나(`_set_status` 주입이 정확히 그 상태다) 대장 밖에서 판정한 경우는 막지 못한다 —
그 상태는 ②의 표시가 드러낼 뿐이다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import store

import backlog as cli

_EVIDENCE = "docs/reviews/eos_phase2_gate2_rejudgment_2026-09-25.md · 판정 기준 main 841ee77d"
_ARTIFACT = "PR #1323 (테스트 픽스처)"
_GATE = "G-h177-entry"
_JUDGMENT = "S1-50-rejudgment"  # 2차 재판정 — 게이트 입력
_NEXT_JUDGMENT = "S1-53-third-rejudgment"  # 3차 재판정 — 사고 시점에 게이트에 연결되지 않았다
_NO_INPUTS = "테스트 픽스처 — 입력 태스크 없음"


@pytest.fixture
def repo(git_repo: Path, monkeypatch) -> Path:
    monkeypatch.chdir(git_repo)
    assert cli.main(["seed"]) == 0
    return git_repo


def _add(task_id: str, *extra: str) -> None:
    rc = cli.main(
        [
            "add",
            "--eos-priority",
            "P2",
            "--id",
            task_id,
            "--title",
            f"HARN-177 테스트 {task_id}",
            "--track",
            "math-completion",
            "--stage",
            "S1",
            *extra,
        ]
    )
    assert rc == 0, f"픽스처 태스크 등재 실패: {task_id}"


def _gate_add(gate_id: str, *extra: str, kind: str = "decision") -> None:
    rc = cli.main(
        ["gates", "add", gate_id, "--title", f"테스트 게이트 {gate_id}", "--kind", kind, *extra]
    )
    assert rc == 0, f"픽스처 게이트 등재 실패: {gate_id}"


def _load(root: Path):
    backlog, errors = store.load_backlog(root)
    assert errors == [], errors
    return backlog


def _set_status(root: Path, task_id: str, status: str) -> None:
    """상태 주입 — 판정 인계를 **거치지 않고** 태스크를 닫는 경로(⑤의 한계 그 자체)."""
    backlog = _load(root)
    task = backlog.tasks[task_id]
    task.status = status
    if status == "done":
        task.artifacts = [_ARTIFACT]
    store.save_task(root, task)


def _done(task_id: str, *extra: str) -> int:
    return cli.main(["done", task_id, "--artifact", _ARTIFACT, *extra])


def _gates_bytes(root: Path) -> bytes:
    return (root / "backlog" / "gates.yaml").read_bytes()


def _task_bytes(root: Path, task_id: str) -> bytes:
    return (root / "backlog" / "tasks" / f"{task_id}.yaml").read_bytes()


def _errors(root: Path) -> list[str]:
    backlog, schema = store.load_backlog(root)
    return store.validate_backlog(backlog, schema)


def _state(root: Path, gate_id: str = _GATE) -> str | None:
    backlog = _load(root)
    return store.gate_judgment_state(backlog, backlog.gates[gate_id])


def _incident_fixture(repo: Path, *, judgment_depends_on_next: bool = False) -> None:
    """2026-09-25 실측 상태(③) — 판정 태스크 J가 진입 게이트의 유일한 입력이고 in_progress,
    후속 재판정 O는 등재만 됐을 뿐 게이트에 연결되지 않았다. P1·P2가 게이트 뒤에 있다.

    `judgment_depends_on_next`: 사고 시점 대장의 또 다른 축 — 소유 태스크가 판정 태스크의
    *선행*에만 있다(EOS-130.depends_on). 선행 부착은 in_progress 전환 **전**에 한다 —
    claim 없이 주입한 in_progress는 validate가 "session 없음"으로 잡아 amend를 거부한다.
    """
    _add(_NEXT_JUDGMENT)
    _add(_JUDGMENT, *(("--depends", _NEXT_JUDGMENT) if judgment_depends_on_next else ()))
    _set_status(repo, _JUDGMENT, "in_progress")
    _gate_add(_GATE, "--depends", _JUDGMENT)
    _add("S1-51-phase-1", "--gates", _GATE)
    _add("S1-52-phase-2", "--gates", _GATE)


def _next_text(capsys) -> str:
    capsys.readouterr()
    assert cli.main(["next", "--no-remote"]) == 0
    return capsys.readouterr().out


def _status_json(capsys) -> dict:
    capsys.readouterr()
    assert cli.main(["status", "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def _gate_json(capsys, gate_id: str = _GATE) -> dict:
    return next(g for g in _status_json(capsys)["pending_gates"] if g["id"] == gate_id)


# ── ① done 인계 ───────────────────────────────────────────────────────────────


class TestHandoffRequired:
    def test_incident4_done_without_verdict_rejected_writes_nothing(self, repo: Path, capsys):
        """사고 4의 그 순간 — 재판정을 판정 없이 닫는다. 거부되고 대장은 바이트 동일."""
        _incident_fixture(repo)
        capsys.readouterr()
        gates_before, task_before = _gates_bytes(repo), _task_bytes(repo, _JUDGMENT)
        assert _done(_JUDGMENT) == 1
        err = capsys.readouterr().err
        assert "판정 결과를 넘겨야" in err and "--no-verdict" in err
        assert _gates_bytes(repo) == gates_before
        assert _task_bytes(repo, _JUDGMENT) == task_before
        assert _load(repo).tasks[_JUDGMENT].status == "in_progress"

    def test_fail_without_owner_rejected(self, repo: Path, capsys):
        """FAIL만 적고 여는 작업을 잇지 않으면 거부 — 사고 3의 형태를 done 경로에서도 막는다."""
        _incident_fixture(repo)
        capsys.readouterr()
        before = _gates_bytes(repo)
        assert _done(_JUDGMENT, "--verdict", "FAIL", "--evidence", _EVIDENCE) == 1
        assert "소유 태스크가 없다" in capsys.readouterr().err
        assert _gates_bytes(repo) == before
        assert _load(repo).tasks[_JUDGMENT].status == "in_progress"

    def test_control_fail_with_attached_owner_is_green(self, repo: Path, capsys):
        """대조군(③) — FAIL + 후속 재판정 부착. 기록·간선·validate·대기 경로가 전부 맞아야 한다."""
        _incident_fixture(repo)
        rc = _done(
            _JUDGMENT, "--verdict", "FAIL", "--evidence", _EVIDENCE, "--attach", _NEXT_JUDGMENT
        )
        assert rc == 0
        backlog = _load(repo)
        assert backlog.tasks[_JUDGMENT].status == "done"
        gate = backlog.gates[_GATE]
        assert gate.depends_on == [_JUDGMENT, _NEXT_JUDGMENT]
        assert gate.status == "pending"
        assert (
            f"verdict FAIL · owners: {_NEXT_JUDGMENT} · inputs: {_JUDGMENT} · evidence: {_EVIDENCE}"
            in gate.corrections[-1]
        )
        assert _errors(repo) == []
        assert _state(repo) == store.JUDGMENT_OPEN
        out = _next_text(capsys)
        assert f"2건 ← {_GATE} ← {_NEXT_JUDGMENT}" in out
        assert "미기록" not in out

    def test_verdict_lands_in_gate_corrections_not_task_artifacts(self, repo: Path):
        """판정 결과는 태스크 증적이 아니라 게이트 corrections에 — 증적에만 있으면 그래프가 못 읽는다."""
        _incident_fixture(repo)
        assert (
            _done(
                _JUDGMENT, "--verdict", "FAIL", "--evidence", _EVIDENCE, "--attach", _NEXT_JUDGMENT
            )
            == 0
        )
        backlog = _load(repo)
        assert backlog.tasks[_JUDGMENT].artifacts == [_ARTIFACT]
        assert not any("verdict" in a for a in backlog.tasks[_JUDGMENT].artifacts)
        assert any("verdict FAIL" in c for c in backlog.gates[_GATE].corrections)

    def test_fail_owner_reachable_only_through_closing_task_rejected(self, repo: Path, capsys):
        """소유 태스크가 닫히는 판정 태스크의 선행에만 있으면 거부 — 끝난 태스크 너머는 연결이 아니다.

        2026-09-25 사고의 대장 형태: EOS-130(done)의 depends_on에만 소유 태스크가 있었다.
        """
        _incident_fixture(repo, judgment_depends_on_next=True)
        capsys.readouterr()
        before = _gates_bytes(repo)
        rc = _done(
            _JUDGMENT, "--verdict", "FAIL", "--evidence", _EVIDENCE, "--owner", _NEXT_JUDGMENT
        )
        assert rc == 1
        err = capsys.readouterr().err
        # 쓰기 전 거부 절의 서명 — 후보 목록("지금 열린 상류:")은 그 절만 낸다. 뒤따르는 validate도
        # 같은 상태를 잡지만 후보 목록이 없으므로, 이 단언이 없으면 그 절을 끊어도 통과한다
        # (뮤테이션 H15 생존으로 발각 · CLAUDE.md 「픽스처가 그 절을 실제로 밟는가」).
        assert "열린 상류에 없다" in err and "지금 열린 상류:" in err
        assert _gates_bytes(repo) == before
        assert _load(repo).tasks[_JUDGMENT].status == "in_progress"

    def test_fail_owner_already_an_open_input_accepted(self, repo: Path):
        """⑥ done 경로 — 소유 태스크가 이미 게이트의 (열린) 입력이면 새 부착 없이 FAIL을 기록한다."""
        _incident_fixture(repo)
        assert (
            cli.main(["gates", "amend", _GATE, "--depends", _NEXT_JUDGMENT, "--reason", "재지정"])
            == 0
        )
        assert (
            _done(
                _JUDGMENT, "--verdict", "FAIL", "--evidence", _EVIDENCE, "--owner", _NEXT_JUDGMENT
            )
            == 0
        )
        gate = _load(repo).gates[_GATE]
        assert gate.depends_on == [_JUDGMENT, _NEXT_JUDGMENT]
        assert (
            f"verdict FAIL · owners: {_NEXT_JUDGMENT} · inputs: {_JUDGMENT} ·"
            in gate.corrections[-1]
        )
        assert _errors(repo) == []

    def test_pass_is_recorded_and_gate_stays_pending(self, repo: Path, capsys):
        """PASS는 근거를 기록할 뿐 게이트를 닫지 않는다 — clear는 담당자 몫. 화면은 '사람 판정 대기'."""
        _incident_fixture(repo)
        assert _done(_JUDGMENT, "--verdict", "PASS", "--evidence", _EVIDENCE) == 0
        gate = _load(repo).gates[_GATE]
        assert gate.status == "pending"
        assert f"verdict PASS · inputs: {_JUDGMENT} · evidence: {_EVIDENCE}" in gate.corrections[-1]
        assert _state(repo) == "judged:PASS"
        out = _next_text(capsys)
        assert f"2건 ← {_GATE} (사람 판정 대기" in out
        assert "미기록" not in out

    def test_pass_with_owner_or_attach_rejected(self, repo: Path, capsys):
        _incident_fixture(repo)
        capsys.readouterr()
        before = _gates_bytes(repo)
        assert (
            _done(
                _JUDGMENT, "--verdict", "PASS", "--evidence", _EVIDENCE, "--attach", _NEXT_JUDGMENT
            )
            == 1
        )
        assert "PASS 판정에는 소유 태스크가 없다" in capsys.readouterr().err
        assert _gates_bytes(repo) == before
        assert _load(repo).tasks[_JUDGMENT].status == "in_progress"

    def test_verdict_needs_judgment_base(self, repo: Path):
        _incident_fixture(repo)
        before = _gates_bytes(repo)
        assert _done(_JUDGMENT, "--verdict", "PASS", "--evidence", "판정문 참고") == 1
        assert _gates_bytes(repo) == before

    @pytest.mark.parametrize("reason", ["", "   "])
    def test_no_verdict_needs_a_reason(self, repo: Path, capsys, reason: str):
        _incident_fixture(repo)
        capsys.readouterr()
        before = _gates_bytes(repo)
        assert _done(_JUDGMENT, "--no-verdict", reason) == 1
        assert "사유가 비어" in capsys.readouterr().err
        assert _gates_bytes(repo) == before

    def test_no_verdict_is_recorded_and_state_stays_unrecorded(self, repo: Path, capsys):
        """판정 무관 입력은 사유와 함께 corrections에 남지만 판정으로 세지 않는다 — 판정은 여전히 남는다."""
        _incident_fixture(repo)
        assert _done(_JUDGMENT, "--no-verdict", "수정 태스크 — 재판정은 별도 태스크가 한다") == 0
        gate = _load(repo).gates[_GATE]
        assert "판정 무관: 수정 태스크" in gate.corrections[-1]
        assert store.latest_verdict(gate) is None
        assert _state(repo) == store.JUDGMENT_UNRECORDED
        assert "판정 결과 미기록" in _next_text(capsys)

    def test_no_verdict_with_verdict_material_rejected(self, repo: Path, capsys):
        _incident_fixture(repo)
        capsys.readouterr()
        before = _gates_bytes(repo)
        assert _done(_JUDGMENT, "--no-verdict", "무관", "--evidence", _EVIDENCE) == 1
        assert "--no-verdict 에는" in capsys.readouterr().err
        assert _gates_bytes(repo) == before

    def test_both_verdict_and_no_verdict_rejected(self, repo: Path, capsys):
        _incident_fixture(repo)
        capsys.readouterr()
        before = _gates_bytes(repo)
        rc = _done(_JUDGMENT, "--verdict", "PASS", "--evidence", _EVIDENCE, "--no-verdict", "무관")
        assert rc == 1
        assert "함께 쓸 수 없다" in capsys.readouterr().err
        assert _gates_bytes(repo) == before
        assert _load(repo).tasks[_JUDGMENT].status == "in_progress"

    def test_verdict_flags_on_non_input_task_rejected(self, repo: Path, capsys):
        """게이트 입력이 아닌 태스크에 판정 플래그를 주면 거부 — 플래그 없는 done은 종전 그대로."""
        _incident_fixture(repo)
        _add("S1-60-plain")
        _set_status(repo, "S1-60-plain", "in_progress")
        capsys.readouterr()
        assert _done("S1-60-plain", "--verdict", "PASS", "--evidence", _EVIDENCE) == 1
        assert "입력이 아니다" in capsys.readouterr().err
        assert _load(repo).tasks["S1-60-plain"].status == "in_progress"
        assert _done("S1-60-plain") == 0
        assert _load(repo).tasks["S1-60-plain"].status == "done"

    def test_human_gate_input_needs_no_handoff(self, repo: Path):
        """판정 개념은 decision 게이트에만 — 사람 게이트의 입력은 종전대로 닫힌다."""
        _add("S1-61-runbook")
        _set_status(repo, "S1-61-runbook", "in_progress")
        _gate_add("G-h177-human", "--depends", "S1-61-runbook", kind="human")
        assert _done("S1-61-runbook") == 0
        assert _load(repo).tasks["S1-61-runbook"].status == "done"

    def test_multi_gate_requires_gate_flag_and_warns_about_the_rest(self, repo: Path, capsys):
        _incident_fixture(repo)
        _gate_add("G-h177-second", "--depends", _JUDGMENT)
        capsys.readouterr()
        before = _gates_bytes(repo)
        assert _done(_JUDGMENT, "--verdict", "PASS", "--evidence", _EVIDENCE) == 1
        assert "--gate <G-id>" in capsys.readouterr().err
        assert _gates_bytes(repo) == before
        rc = _done(_JUDGMENT, "--gate", _GATE, "--verdict", "PASS", "--evidence", _EVIDENCE)
        assert rc == 0
        captured = capsys.readouterr()
        assert "G-h177-second" in captured.err and "따로 기록" in captured.err
        assert _state(repo, _GATE) == "judged:PASS"
        assert _state(repo, "G-h177-second") == store.JUDGMENT_UNRECORDED

    def test_gate_flag_must_name_an_input_gate(self, repo: Path, capsys):
        _incident_fixture(repo)
        _gate_add("G-h177-other", "--no-inputs", _NO_INPUTS)
        capsys.readouterr()
        before = _gates_bytes(repo)
        rc = _done(
            _JUDGMENT, "--gate", "G-h177-other", "--verdict", "PASS", "--evidence", _EVIDENCE
        )
        assert rc == 1
        assert "입력으로 둔 pending decision 게이트가 아니다" in capsys.readouterr().err
        assert _gates_bytes(repo) == before


# ── ② 표시 정직성 ─────────────────────────────────────────────────────────────


class TestDisplayHonesty:
    def test_incident4_ledger_state_shows_unrecorded_everywhere(self, repo: Path, capsys):
        """③의 대장 상태 — 판정 태스크가 인계 없이 done. 세 화면 + JSON이 '판정 결과 미기록'."""
        _incident_fixture(repo)
        _set_status(repo, _JUDGMENT, "done")
        assert _state(repo) == store.JUDGMENT_UNRECORDED
        out = _next_text(capsys)
        gate_line = next(line for line in out.splitlines() if f"← {_GATE}" in line)
        assert f"2건 ← {_GATE} (판정 결과 미기록" in gate_line
        assert "(사람 판정 대기" not in gate_line  # 시드 대장의 다른 게이트 줄은 무관
        capsys.readouterr()
        assert cli.main(["status"]) == 0
        assert "판정 결과 미기록" in capsys.readouterr().out
        capsys.readouterr()
        assert cli.main(["gates", "show", _GATE]) == 0
        assert "판정 결과 미기록" in capsys.readouterr().out
        capsys.readouterr()
        assert cli.main(["gates", "list"]) == 0
        assert "판정 결과 미기록" in capsys.readouterr().out
        assert _gate_json(capsys)["judgment"] == store.JUDGMENT_UNRECORDED

    def test_pass_recorded_via_amend_shows_person_next(self, repo: Path, capsys):
        """대조군 — 같은 대장에 PASS를 기록하면 정말 사람 차례다."""
        _incident_fixture(repo)
        _set_status(repo, _JUDGMENT, "done")
        rc = cli.main(
            [
                "gates",
                "amend",
                _GATE,
                "--verdict",
                "PASS",
                "--evidence",
                _EVIDENCE,
                "--reason",
                "PASS",
            ]
        )
        assert rc == 0
        out = _next_text(capsys)
        assert f"2건 ← {_GATE} (사람 판정 대기" in out
        assert "미기록" not in out
        assert _gate_json(capsys)["judgment"] == "judged:PASS"

    def test_human_gate_without_inputs_still_says_person(self, repo: Path, capsys):
        _gate_add("G-h177-human", "--no-inputs", _NO_INPUTS, kind="human")
        _add("S1-62-waiting", "--gates", "G-h177-human")
        out = _next_text(capsys)
        assert "1건 ← G-h177-human (사람 판정 대기)" in out
        assert _gate_json(capsys, "G-h177-human")["judgment"] is None

    def test_human_gate_with_done_input_is_person_wait_not_unrecorded(self, repo: Path, capsys):
        """판정 기록은 decision 게이트의 개념 — 사람 게이트는 입력이 끝나면 정말 사람 차례다."""
        _add("S1-63-runbook")
        _set_status(repo, "S1-63-runbook", "done")
        _gate_add("G-h177-human", "--depends", "S1-63-runbook", kind="human")
        _add("S1-64-waiting", "--gates", "G-h177-human")
        out = _next_text(capsys)
        assert "1건 ← G-h177-human (사람 판정 대기)" in out
        assert "미기록" not in out
        assert _gate_json(capsys, "G-h177-human")["judgment"] is None

    def test_stale_fail_after_owner_finished_is_unrecorded(self, repo: Path, capsys):
        """FAIL의 소유 태스크가 끝나면 그 FAIL은 소화된 것 — 새 판정 없이는 '미기록'이다(스냅샷 불일치)."""
        _incident_fixture(repo)
        assert (
            _done(
                _JUDGMENT, "--verdict", "FAIL", "--evidence", _EVIDENCE, "--attach", _NEXT_JUDGMENT
            )
            == 0
        )
        _set_status(repo, _NEXT_JUDGMENT, "done")
        assert _state(repo) == store.JUDGMENT_UNRECORDED
        assert f"2건 ← {_GATE} (판정 결과 미기록" in _next_text(capsys)
        assert _errors(repo) == []  # 끝난 소유 태스크는 validate 대조 대상이 아니다

    def test_open_inputs_are_not_reported_as_a_judgment_state(self, repo: Path, capsys):
        _incident_fixture(repo)
        assert _state(repo) == store.JUDGMENT_OPEN
        out = _next_text(capsys)
        assert f"2건 ← {_GATE} ← {_JUDGMENT}" in out
        assert "판정" not in out.split(_GATE, 1)[1].split("\n", 1)[0]
        assert _gate_json(capsys)["judgment"] == store.JUDGMENT_OPEN


# ── ⑥ 열린 상류 소유 태스크 (gates amend 경로) ────────────────────────────────


class TestAmendOwnerPath:
    def _fail(self, *extra: str) -> int:
        return cli.main(
            [
                "gates",
                "amend",
                _GATE,
                "--verdict",
                "FAIL",
                "--evidence",
                _EVIDENCE,
                "--reason",
                "재판정 FAIL",
                *extra,
            ]
        )

    def test_fail_with_already_attached_owner_passes(self, repo: Path):
        """2026-09-25 #1321 상태 — 사람이 먼저 입력을 재지정한 게이트에 FAIL을 남길 수 있어야 한다."""
        _add(_NEXT_JUDGMENT)
        _gate_add(_GATE, "--depends", _NEXT_JUDGMENT)
        assert self._fail("--owner", _NEXT_JUDGMENT) == 0
        gate = _load(repo).gates[_GATE]
        assert gate.depends_on == [_NEXT_JUDGMENT]
        assert f"verdict FAIL · owners: {_NEXT_JUDGMENT} · inputs: - ·" in gate.corrections[-1]
        assert _errors(repo) == []

    def test_fail_with_no_open_upstream_rejected(self, repo: Path, capsys):
        """상류에 미종결 태스크가 하나도 없으면 여전히 거부 — 사고 3 방지 축 유지."""
        _add(_JUDGMENT)
        _set_status(repo, _JUDGMENT, "done")
        _gate_add(_GATE, "--depends", _JUDGMENT)
        capsys.readouterr()
        before = _gates_bytes(repo)
        assert self._fail("--owner", _JUDGMENT) == 1
        assert "끝난 태스크는 미충족 항목을 소유할 수 없다" in capsys.readouterr().err
        assert self._fail() == 1
        assert "소유 태스크가 없다" in capsys.readouterr().err
        assert _gates_bytes(repo) == before

    def test_owner_not_upstream_rejected(self, repo: Path, capsys):
        _add(_JUDGMENT)
        _add(_NEXT_JUDGMENT)
        _gate_add(_GATE, "--depends", _JUDGMENT)
        capsys.readouterr()
        before = _gates_bytes(repo)
        assert self._fail("--owner", _NEXT_JUDGMENT) == 1
        err = capsys.readouterr().err
        assert "열린 상류에 없다" in err and "지금 열린 상류:" in err  # 쓰기 전 거부 절의 서명
        assert _gates_bytes(repo) == before

    def test_owner_upstream_via_open_judgment_task_passes(self, repo: Path):
        _add(_NEXT_JUDGMENT)
        _add(_JUDGMENT, "--depends", _NEXT_JUDGMENT)
        _gate_add(_GATE, "--depends", _JUDGMENT)
        assert self._fail("--owner", _NEXT_JUDGMENT) == 0
        assert _errors(repo) == []

    def test_owner_without_verdict_rejected(self, repo: Path, capsys):
        _add(_JUDGMENT)
        _gate_add(_GATE, "--depends", _JUDGMENT)
        capsys.readouterr()
        before = _gates_bytes(repo)
        rc = cli.main(["gates", "amend", _GATE, "--owner", _JUDGMENT, "--reason", "x"])
        assert rc == 1
        assert "--owner 는 --verdict FAIL 과 함께만" in capsys.readouterr().err
        assert _gates_bytes(repo) == before

    def test_validate_flags_owner_only_reachable_through_done_task(self, repo: Path):
        """대장 상태 대조 — FAIL이 지목한 소유 태스크가 끝난 판정 태스크의 선행에만 있으면 validate RED."""
        _add(_NEXT_JUDGMENT)
        _add(_JUDGMENT, "--depends", _NEXT_JUDGMENT)
        _gate_add(_GATE, "--depends", _JUDGMENT)
        backlog = _load(repo)
        backlog.gates[_GATE].corrections = [
            "[2026-09-25] "
            + store.format_fail_verdict([_NEXT_JUDGMENT], _EVIDENCE, [_JUDGMENT])
            + " — 재판정"
        ]
        store.save_gates(repo, sorted(backlog.gates.values(), key=lambda g: g.id))
        assert _errors(repo) == []  # J가 열려 있는 동안은 O에 닿는다
        _set_status(repo, _JUDGMENT, "done")
        errors = [e for e in _errors(repo) if _GATE in e]
        assert len(errors) == 1 and "열린 상류" in errors[0] and _NEXT_JUDGMENT in errors[0]

    def test_amend_pass_recorded_and_rejects_owners(self, repo: Path, capsys):
        _add(_JUDGMENT)
        _set_status(repo, _JUDGMENT, "done")
        _gate_add(_GATE, "--depends", _JUDGMENT)
        _add(_NEXT_JUDGMENT)
        capsys.readouterr()
        before = _gates_bytes(repo)
        rc = cli.main(
            [
                "gates",
                "amend",
                _GATE,
                "--verdict",
                "PASS",
                "--evidence",
                _EVIDENCE,
                "--depends",
                _NEXT_JUDGMENT,
                "--reason",
                "x",
            ]
        )
        assert rc == 1
        assert "PASS 판정에는 소유 태스크가 없다" in capsys.readouterr().err
        assert _gates_bytes(repo) == before
        rc = cli.main(
            ["gates", "amend", _GATE, "--verdict", "PASS", "--evidence", _EVIDENCE, "--reason", "x"]
        )
        assert rc == 0
        gate = _load(repo).gates[_GATE]
        assert f"verdict PASS · inputs: {_JUDGMENT} · evidence:" in gate.corrections[-1]
        assert _state(repo) == "judged:PASS"
