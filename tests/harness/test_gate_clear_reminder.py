"""HARN-74 — 게이트 해소 시점의 후속 집행: 부착 blocked 태스크·산문 참조·brief 되묻기.

배경(2026-09-06 /status 세션 실측): G-prod-dead-column-check(8/31 clear)·G-eos-verification-
relevance-triage(9/1 clear)가 닫힌 뒤에도 ADMIN-02·CUR-17·CUR-18이 **blocked로 5일 이상** 남아
`/status`가 이를 Kiki 대기로 오보고했다. `gates clear` 핸들러는 `✔ 게이트 → cleared` 한 줄만 찍고
부착 태스크를 계산하지 않았다 — 보드(HARN-41)는 계산했지만 CLI·브리핑에는 없었다.

이 파일이 계약으로 동결하는 것 (acceptance ①~④):
  ① `gates clear|waive` 직후 그 게이트를 `requires_gates`로 건 **blocked** 태스크 전건을 id 정렬로
     나열하고 각각 `python3 scripts/harness/backlog.py unblock <id>` 명령을 낸다. 남은 pending 게이트가
     있으면 `(다른 게이트 대기: G-x)`를 병기한다. **0건도 `부착 blocked 태스크 0건`으로 명시**한다 —
     결과 보고에서 침묵은 "검사 안 함"과 구별되지 않는다. 이벤트에 `blocked_attached=[ids]`.
  ② notes 산문에만 게이트 ID를 적은(requires_gates 미부착) blocked 태스크는 `산문 참조` 절에 따로 —
     기계는 의도를 모르므로 unblock 명령 대신 부착/해제 두 갈래를 안내한다. 이벤트에
     `blocked_notes_ref=[ids]`. 부분 문자열(`G-x` ⊂ `G-x-y`)은 참조가 아니다.
  ③ `brief --format hook`(stdout)·`status`·`status --json`(`gate_stale_blocked`)이 "해소된 게이트를
     기다리는 blocked 태스크"를 매 세션 보인다 — clear 화면을 놓쳐도 다음 세션이 본다. unblock 뒤에는
     사라진다(변별력).
  ④ 뮤테이션 3종(①의 목록 계산을 빈 리스트로 · ②의 notes 참조 판정 제거 · ③의 brief 배선 제거)이
     각각 이 파일을 RED로 만든다 — 실측은 태스크 보고에 남긴다(주입 적용·원복 바이트 동일 단언 포함).

게이트 해소는 태스크 status를 **바꾸지 않는다** — 차단 사유가 게이트뿐인지 기계는 모른다(모른다 ≠
아니다). 이 파일이 잡는 것은 자동 해제가 아니라 *알림의 부재*다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import selector
import store
from models import Backlog, Gate, Task, Track

import backlog as cli

_GATE = "G-harn74-test"
_GATE2 = "G-harn74-second"
# HARN-68 계약: clear의 evidence에는 판정 기준(커밋 해시·PR 참조)이 있어야 한다. 이 파일의 관심사는
# 해소 *뒤*의 알림이지 판정 기준이 아니므로 해시는 통과용 최소 표기다(test_gate_clear_attribution 관례).
_EVIDENCE = "세션 확인 (main 3b007e23 기준)"
_STALE_LINE = "해소된 게이트를 기다리는 blocked 태스크"


@pytest.fixture
def seeded_repo(git_repo: Path, monkeypatch) -> Path:
    """seed까지 끝난 저장소 (cwd 고정)."""
    monkeypatch.chdir(git_repo)
    assert cli.main(["seed"]) == 0
    return git_repo


def _add(task_id: str) -> int:
    return cli.main(
        [
            "add",
            "--eos-priority",
            "P2",
            "--id",
            task_id,
            "--title",
            "HARN-74 테스트 태스크",
            "--track",
            "math-completion",
            "--stage",
            "S1",
        ]
    )


def _gate_add(gate_id: str) -> None:
    assert cli.main(["gates", "add", gate_id, "--title", "HARN-74 테스트 게이트"]) == 0


def _attach(task_id: str, gate_id: str) -> None:
    assert cli.main(["amend", task_id, "--gate", gate_id, "--reason", "게이트 부착"]) == 0


def _block(task_id: str, reason: str = "외부 결정 대기") -> None:
    assert cli.main(["block", task_id, "--reason", reason]) == 0


def _task(repo: Path, task_id: str) -> Task:
    backlog, errors = store.load_backlog(repo)
    assert not errors, f"대장 스키마 오류: {errors}"
    return backlog.tasks[task_id]


def _events(repo: Path, action: str) -> list[dict]:
    """이벤트 대장(레거시 + 세션 샤드 — HARN-46)에서 action이 일치하는 기록만."""
    return [
        json.loads(line)
        for path in store.event_paths(repo)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("action") == action
    ]


def _clear(gate_id: str, capsys) -> str:
    """gates clear 실행 → 그 실행만의 stdout. 직전 출력을 먼저 비워 판정을 이 실행에 한정한다."""
    capsys.readouterr()
    assert cli.main(["gates", "clear", gate_id, "--evidence", _EVIDENCE]) == 0
    return capsys.readouterr().out


def _unblock_cmd(task_id: str) -> str:
    """①이 내는 복사-실행용 줄 — ②의 안내(`backlog.py unblock`)와 접두로 구별된다."""
    return f"python3 scripts/harness/backlog.py unblock {task_id}"


def _blocked_gated(task_id: str, gate_id: str = _GATE) -> None:
    """게이트를 건 blocked 태스크 한 건 — 사고의 최소 재현(ADMIN-02 형태)."""
    assert _add(task_id) == 0
    _attach(task_id, gate_id)
    _block(task_id)


# ── ① 부착 blocked 태스크 — 전건 + unblock 명령 · 0건 명시 ────────────────────


class TestClearListsAttachedBlocked:
    """① clear 직후 그 게이트를 건 blocked 태스크가 unblock 명령과 함께 보인다."""

    def test_attached_blocked_task_and_unblock_command_are_printed(self, seeded_repo, capsys):
        _gate_add(_GATE)
        _blocked_gated("T74-01-waiting")
        out = _clear(_GATE, capsys)
        assert "부착 blocked 태스크 1건" in out
        assert _unblock_cmd("T74-01-waiting") in out
        # 해소는 태스크를 풀지 않는다 — 알림이지 자동 unblock이 아니다(차단 사유는 기계가 모른다)
        assert _task(seeded_repo, "T74-01-waiting").status == "blocked"
        # 화면은 휘발되지만 대장은 남는다
        events = [e for e in _events(seeded_repo, "gate_clear") if e["id"] == _GATE]
        assert len(events) == 1
        assert events[0]["blocked_attached"] == ["T74-01-waiting"]
        assert events[0]["blocked_notes_ref"] == []
        # 기존 필드는 유지된다(HARN-60 주체 기록이 이 변경으로 사라지면 안 된다)
        assert events[0]["cleared_by"] == "claude"

    def test_zero_attached_is_stated_not_silent(self, seeded_repo, capsys):
        """0건도 '0건'으로 찍는다 — 결과 보고에서 침묵은 '검사 안 함'과 같은 화면이다."""
        _gate_add(_GATE)
        out = _clear(_GATE, capsys)
        assert "부착 blocked 태스크 0건" in out
        assert "산문 참조(requires_gates 미부착) 0건" in out
        assert "unblock" not in out, "0건인데 unblock 명령이 나오면 날조다"
        events = [e for e in _events(seeded_repo, "gate_clear") if e["id"] == _GATE]
        assert events[0]["blocked_attached"] == []
        assert events[0]["blocked_notes_ref"] == []

    def test_attached_but_not_blocked_task_is_not_listed(self, seeded_repo, capsys):
        """변별력 — 부착돼 있어도 todo면 목록에 없다(부착 = 의존 관계, 목록 = 현재 차단)."""
        _gate_add(_GATE)
        assert _add("T74-02-todo") == 0
        _attach("T74-02-todo", _GATE)
        out = _clear(_GATE, capsys)
        assert "부착 blocked 태스크 0건" in out
        assert "T74-02-todo" not in out

    def test_all_attached_blocked_tasks_are_listed_in_id_order(self, seeded_repo, capsys):
        """전건 — 상위 N건이 아니다. 잘린 목록은 부재 판정을 무효로 만든다(CLAUDE.md 절단 규칙)."""
        _gate_add(_GATE)
        for task_id in ("T74-13-c", "T74-11-a", "T74-12-b"):
            _blocked_gated(task_id)
        out = _clear(_GATE, capsys)
        assert "부착 blocked 태스크 3건" in out
        positions = [out.index(_unblock_cmd(t)) for t in ("T74-11-a", "T74-12-b", "T74-13-c")]
        assert positions == sorted(positions), "id 정렬이어야 결정적이다"
        events = [e for e in _events(seeded_repo, "gate_clear") if e["id"] == _GATE]
        assert events[0]["blocked_attached"] == ["T74-11-a", "T74-12-b", "T74-13-c"]


# ── ①-b 남은 pending 게이트 — unblock해도 후보가 되지 않는 이유를 미리 알린다 ──


class TestRemainingPendingGatesAreAnnounced:
    def test_other_pending_gate_is_named_on_the_same_line(self, seeded_repo, capsys):
        _gate_add(_GATE)
        _gate_add(_GATE2)
        assert _add("T74-20-two-gates") == 0
        _attach("T74-20-two-gates", _GATE)
        _attach("T74-20-two-gates", _GATE2)
        _block("T74-20-two-gates")
        out = _clear(_GATE, capsys)
        line = next(ln for ln in out.splitlines() if _unblock_cmd("T74-20-two-gates") in ln)
        assert f"(다른 게이트 대기: {_GATE2}" in line
        # 두 번째 게이트까지 닫히면 병기가 사라진다 — 항상 붙는 병기는 정보가 아니다
        out2 = _clear(_GATE2, capsys)
        line2 = next(ln for ln in out2.splitlines() if _unblock_cmd("T74-20-two-gates") in ln)
        assert "다른 게이트 대기" not in line2

    def test_single_gate_task_has_no_annotation(self, seeded_repo, capsys):
        _gate_add(_GATE)
        _blocked_gated("T74-21-one-gate")
        out = _clear(_GATE, capsys)
        assert "다른 게이트 대기" not in out


# ── ② 산문 참조 — requires_gates 미부착인데 notes에 게이트 ID를 적은 blocked ──


class TestNotesOnlyReferenceIsListedSeparately:
    def test_notes_reference_gets_choice_not_command(self, seeded_repo, capsys):
        """CUR-17·CUR-18 형태 — block --reason에 게이트를 적었을 뿐 부착하지 않았다."""
        _gate_add(_GATE)
        assert _add("T74-30-prose") == 0
        _block("T74-30-prose", f"{_GATE} 해소까지 대기")
        assert _task(seeded_repo, "T74-30-prose").requires_gates == []
        out = _clear(_GATE, capsys)
        assert "산문 참조(requires_gates 미부착) 1건" in out
        assert "부착 blocked 태스크 0건" in out
        # 두 갈래 안내 — 기계가 의도를 모르므로 명령 하나를 확정하지 않는다
        assert f"amend T74-30-prose --gate {_GATE}" in out
        assert "backlog.py unblock T74-30-prose" in out
        # ①의 복사-실행용 줄에는 없다(부착 절과 산문 절이 섞이면 사람이 unblock을 확정으로 읽는다)
        assert _unblock_cmd("T74-30-prose") not in out
        events = [e for e in _events(seeded_repo, "gate_clear") if e["id"] == _GATE]
        assert events[0]["blocked_notes_ref"] == ["T74-30-prose"]
        assert events[0]["blocked_attached"] == []

    def test_attached_task_is_not_double_counted_as_prose(self, seeded_repo, capsys):
        """부착된 태스크가 notes에도 게이트를 적었으면 ①에만 — 같은 태스크를 두 절에 내지 않는다."""
        _gate_add(_GATE)
        assert _add("T74-31-both") == 0
        _attach("T74-31-both", _GATE)
        _block("T74-31-both", f"{_GATE} 대기")
        out = _clear(_GATE, capsys)
        assert "부착 blocked 태스크 1건" in out
        assert "산문 참조(requires_gates 미부착) 0건" in out
        events = [e for e in _events(seeded_repo, "gate_clear") if e["id"] == _GATE]
        assert events[0]["blocked_attached"] == ["T74-31-both"]
        assert events[0]["blocked_notes_ref"] == []

    def test_todo_task_mentioning_gate_is_not_a_prose_reference(self, seeded_repo, capsys):
        """변별력 — blocked가 아니면 notes에 게이트가 있어도 산문 참조가 아니다."""
        _gate_add(_GATE)
        assert _add("T74-32-todo-mention") == 0
        assert (
            cli.main(
                [
                    "amend",
                    "T74-32-todo-mention",
                    "--acceptance",
                    "추가 항",
                    "--reason",
                    f"{_GATE} 참고",
                ]
            )
            == 0
        )
        assert _GATE in _task(seeded_repo, "T74-32-todo-mention").notes
        out = _clear(_GATE, capsys)
        assert "산문 참조(requires_gates 미부착) 0건" in out

    def test_partial_id_match_is_not_a_reference(self, seeded_repo, capsys):
        """`G-harn74` ⊂ `G-harn74-test` — 짧은 ID의 게이트를 닫을 때 긴 ID를 적은 태스크가 잡히면 오탐.

        양방향으로 잰다: 짧은 게이트 clear → 0건, 긴 게이트 clear → 1건. 한쪽만 보면 '항상 0건'
        구현도 통과한다.
        """
        _gate_add("G-harn74")
        _gate_add(_GATE)
        assert _add("T74-33-long-ref") == 0
        _block("T74-33-long-ref", f"{_GATE} 대기")
        out_short = _clear("G-harn74", capsys)
        assert "산문 참조(requires_gates 미부착) 0건" in out_short
        assert "T74-33-long-ref" not in out_short
        out_long = _clear(_GATE, capsys)
        assert "산문 참조(requires_gates 미부착) 1건" in out_long
        assert "T74-33-long-ref" in out_long


# ── waive 경로 — clear와 같은 알림·같은 이벤트 필드 ──────────────────────────


class TestWaivePathBehavesTheSame:
    def test_waive_prints_reminder_and_records_event(self, seeded_repo, capsys):
        _gate_add(_GATE)
        _blocked_gated("T74-40-waived")
        assert _add("T74-41-prose") == 0
        _block("T74-41-prose", f"{_GATE} 결과 보고 대기")
        capsys.readouterr()
        assert cli.main(["gates", "waive", _GATE, "--reason", "범위에서 제외"]) == 0
        out = capsys.readouterr().out
        assert f"✔ {_GATE} → waived" in out
        assert "부착 blocked 태스크 1건" in out
        assert _unblock_cmd("T74-40-waived") in out
        assert "산문 참조(requires_gates 미부착) 1건" in out
        assert "T74-41-prose" in out
        events = [e for e in _events(seeded_repo, "gate_waive") if e["id"] == _GATE]
        assert len(events) == 1
        assert events[0]["blocked_attached"] == ["T74-40-waived"]
        assert events[0]["blocked_notes_ref"] == ["T74-41-prose"]
        assert events[0]["reason"] == "범위에서 제외"


# ── ③ brief·status — 해소된 게이트를 기다리는 blocked를 매 세션 보인다 ─────────


class TestBriefAndStatusShowStaleGateBlocked:
    """③ clear 화면을 놓쳐도 다음 세션이 본다 — 집행 지점은 brief(stdout)·status·status --json."""

    def _brief(self, capsys) -> str:
        capsys.readouterr()
        assert cli.main(["brief", "--format", "hook"]) == 0
        return capsys.readouterr().out

    def _status(self, capsys) -> str:
        capsys.readouterr()
        assert cli.main(["status"]) == 0
        return capsys.readouterr().out

    def _status_json(self, capsys) -> dict:
        capsys.readouterr()
        assert cli.main(["status", "--json"]) == 0
        return json.loads(capsys.readouterr().out)

    def test_line_appears_after_clear_and_disappears_after_unblock(self, seeded_repo, capsys):
        _gate_add(_GATE)
        _blocked_gated("T74-50-stale")
        # clear 전: 게이트가 pending이므로 '해소된 게이트를 기다리는' 상태가 아니다(변별력)
        assert _STALE_LINE not in self._brief(capsys)
        assert _STALE_LINE not in self._status(capsys)
        assert self._status_json(capsys)["gate_stale_blocked"] == []

        _clear(_GATE, capsys)
        expected = f"{_STALE_LINE} 1건: T74-50-stale(←{_GATE}) — 확인: backlog.py unblock <id>"
        # brief는 훅이 stderr를 버리므로(`2>/dev/null`) **stdout**에 있어야 실제로 보인다
        assert expected in self._brief(capsys)
        assert expected in self._status(capsys)
        assert self._status_json(capsys)["gate_stale_blocked"] == [
            {"id": "T74-50-stale", "gates": [_GATE]}
        ]

        # unblock 뒤에는 사라진다 — 항상 뜨는 줄은 경고가 아니라 소음이다
        assert cli.main(["unblock", "T74-50-stale"]) == 0
        assert _STALE_LINE not in self._brief(capsys)
        assert _STALE_LINE not in self._status(capsys)
        assert self._status_json(capsys)["gate_stale_blocked"] == []

    def test_blocked_without_gates_is_not_stale(self, seeded_repo, capsys):
        """requires_gates가 비어 있으면 '게이트를 기다리는' 차단이 아니다."""
        assert _add("T74-51-plain") == 0
        _block("T74-51-plain")
        assert _STALE_LINE not in self._brief(capsys)
        assert self._status_json(capsys)["gate_stale_blocked"] == []

    def test_partially_passed_gates_are_not_stale(self, seeded_repo, capsys):
        """게이트 둘 중 하나만 닫히면 아직 기다릴 게이트가 있다 — 전부 passed일 때만 stale."""
        _gate_add(_GATE)
        _gate_add(_GATE2)
        assert _add("T74-52-two") == 0
        _attach("T74-52-two", _GATE)
        _attach("T74-52-two", _GATE2)
        _block("T74-52-two")
        _clear(_GATE, capsys)
        assert _STALE_LINE not in self._brief(capsys)
        assert self._status_json(capsys)["gate_stale_blocked"] == []
        _clear(_GATE2, capsys)
        assert f"T74-52-two(←{_GATE},{_GATE2})" in self._brief(capsys)
        assert self._status_json(capsys)["gate_stale_blocked"] == [
            {"id": "T74-52-two", "gates": [_GATE, _GATE2]}
        ]


# ── 헬퍼 단위 계약 — 호출 순서 독립·보드와의 단일 진실 원천 ────────────────────


def _backlog() -> Backlog:
    backlog = Backlog(stage_order=["S1"])
    backlog.tracks["main"] = Track(id="main", title="기본")
    backlog.gates["G-a"] = Gate(id="G-a", title="a", requested="2026-09-01")
    backlog.gates["G-b"] = Gate(id="G-b", title="b", requested="2026-09-01")
    backlog.tasks["S1-01-x"] = Task(
        id="S1-01-x",
        title="둘 다 건 차단",
        track="main",
        stage="S1",
        status="blocked",
        requires_gates=["G-a", "G-b"],
        updated="2026-09-01",
    )
    return backlog


class TestHelperContracts:
    def test_other_gates_exclude_target_regardless_of_its_status(self):
        """gate_id를 명시적으로 뺀다 — pending일 때 불러도 cleared일 때 불러도 같은 답."""
        backlog = _backlog()
        before = selector.gate_attached_blocked(backlog, "G-a")
        backlog.gates["G-a"].status = "cleared"
        backlog.gates["G-a"].evidence = "e"
        after = selector.gate_attached_blocked(backlog, "G-a")
        assert [(t.id, others) for t, others in before] == [("S1-01-x", ["G-b"])]
        assert [(t.id, others) for t, others in after] == [("S1-01-x", ["G-b"])]

    def test_board_and_cli_share_the_dependent_list(self):
        """보드의 게이트 상세와 CLI 알림이 같은 헬퍼를 본다 — 한쪽만 고쳐지는 이중 진실 원천 금지."""
        import board

        backlog = _backlog()
        backlog.tasks["S1-02-y"] = Task(
            id="S1-02-y",
            title="todo로 건 것",
            track="main",
            stage="S1",
            requires_gates=["G-a"],
            updated="2026-09-01",
        )
        tasks, _tracks = board.gate_dependents(backlog, "G-a")
        assert [t["id"] for t in tasks] == [
            t.id for t in selector.gate_dependent_tasks(backlog, "G-a")
        ]
        assert [t["id"] for t in tasks] == ["S1-01-x", "S1-02-y"]
        # CLI 알림은 그 목록을 blocked로 좁힌 것이다
        assert [t.id for t, _ in selector.gate_attached_blocked(backlog, "G-a")] == ["S1-01-x"]

    def test_stale_requires_every_gate_passed(self):
        backlog = _backlog()
        assert selector.stale_gate_blocked(backlog) == []
        backlog.gates["G-a"].status = "waived"
        assert selector.stale_gate_blocked(backlog) == []
        backlog.gates["G-b"].status = "cleared"
        backlog.gates["G-b"].evidence = "e"
        assert [(t.id, g) for t, g in selector.stale_gate_blocked(backlog)] == [
            ("S1-01-x", ["G-a", "G-b"])
        ]
        # 대장에 없는 게이트 ID는 미통과로 친다(unmet_gates와 같은 의미) — 모른다 ≠ 통과
        backlog.tasks["S1-01-x"].requires_gates.append("G-missing")
        assert selector.stale_gate_blocked(backlog) == []
