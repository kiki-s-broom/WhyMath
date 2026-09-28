"""HARN-184 — 게이트 대기 분류의 단일 판정: 계약 동결.

배경(2026-09-28 · HARN-177 착지 후 정상작동 점검 · 판정 기준 main 919865d4):
  HARN-177 ②는 "판정이 기록되지 않은 상태를 사람 차례로 안내하지 않는다"를 원칙으로 적고
  next·status·gates list/show 에 판정 기록 상태를 실었다. 그런데 그 acceptance 는 **화면을
  열거**했고, 그 뒤 착지한 작업 흐름 그래프(HARN-182 · #1345)는 게이트 창의 상태를 "열린
  선행이 있는가"로만 갈랐다 — 입력이 done 이고 판정 기록이 없는 decision 게이트가 상태
  gate_turn · 라벨 '사람 차례' · 집계 '사람 차례 1'로, PASS 기록 대조군과 똑같이 그려졌다.
  보드 카드 라벨('사람 게이트 대기')과 정지 사유(human_gate)도 같은 축을 보지 않았다.
  공용 판정이 있는데 새 화면이 자체 판정을 한 것이다.

이 파일이 절(節)마다 동결하는 것 — 각 클래스는 "그 절이 없으면 무엇이 통과하는가"의 반례를
담는다(CLAUDE.md 「픽스처가 그 절을 실제로 밟는가」):
  ① 단일 판정      — store.gate_wait_kind: inputs · verdict · person (통과한 게이트는 None)
  ② 작업 흐름 그래프 — 게이트 창 상태·라벨·집계·텍스트 요약·화면 템플릿이 ①을 따른다
  ③ 보드·정지 사유  — 카드 라벨·게이트 카드·정지 사유(gate_verdict)·세션 브리핑이 ①을 따른다
  ④ 전 화면 대조    — 사고 대장 상태 하나로 모든 화면을 대조하고(PASS 기록 대조군 포함), 사람
                     차례 문구를 내는 하네스 모듈이 전부 등재됐는지 본다(새 화면이 계약 밖으로
                     새지 않게 — HARN-177 ②가 뚫린 입구)
뮤테이션 하네스 `scripts/harness/verify_gate_wait_kind_discrimination.py`가 이 파일을 대상으로 돌린다.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import date
from pathlib import Path

import board
import pytest
import report
import selector
import store
import work_graph
from models import Backlog, Gate, Task, Track

import backlog as cli

TODAY = date(2026, 9, 28)
_GATE = "G-h184-entry"
_JUDGMENT = "S1-50-rejudgment"  # 게이트 입력 — 재판정 태스크
_BEHIND = ("S1-51-phase-1", "S1-52-phase-2")  # 게이트 뒤에서 기다리는 태스크
_EVIDENCE = "docs/reviews/h184_fixture.md · 판정 기준 main 919865d4"
_ARTIFACT = "PR #1323 (테스트 픽스처)"

#: 사람 차례를 말하는 문구 — ④의 두 검사(전 화면 대조 · 모듈 등재)가 같은 목록을 쓴다.
HUMAN_TURN_PHRASES = ("사람 차례", "사람 판정 대기", "사람 게이트 대기", "Kiki 차례", "행동 대기")
#: 판정 결과 미기록을 말하는 문구 — 화면마다 조금씩 다르지만 이 글자는 공통이다.
VERDICT_MARK = "판정 결과 미기록"


# ── 픽스처 (메모리 대장) ──────────────────────────────────────────────────────


def _task(tid: str, **fields: object) -> Task:
    fields.setdefault("track", "main")
    fields.setdefault("stage", "S1")
    return Task(id=tid, title=f"HARN-184 테스트 {tid}", **fields)  # type: ignore[arg-type]


def _pass_line(inputs: list[str]) -> str:
    return "[2026-09-28] " + store.format_pass_verdict(inputs, _EVIDENCE)


def _fail_line(owners: list[str], inputs: list[str]) -> str:
    return "[2026-09-28] " + store.format_fail_verdict(owners, _EVIDENCE, inputs)


def _backlog(
    *,
    input_status: str | None = "done",
    kind: str = "decision",
    corrections: tuple[str, ...] = (),
) -> Backlog:
    """게이트 1개(입력 = 재판정 태스크 J) + 그 뒤에서 기다리는 태스크 2개.

    `input_status=None`이면 입력 없는 게이트(판정 개념 없음)다.
    """
    b = Backlog(stage_order=["S1"])
    b.tracks["main"] = Track(id="main", title="기본")
    gate = Gate(
        id=_GATE,
        title="진입 게이트",
        kind=kind,
        assignee="kiki",
        requested="2026-09-20",
        corrections=list(corrections),
    )
    if input_status is None:
        gate.no_inputs_reason = "테스트 픽스처 — 입력 없음"
    else:
        gate.depends_on = [_JUDGMENT]
        b.tasks[_JUDGMENT] = _task(
            _JUDGMENT,
            status=input_status,
            artifacts=[_ARTIFACT] if input_status == "done" else [],
        )
    b.gates[_GATE] = gate
    for tid in _BEHIND:
        b.tasks[tid] = _task(tid, requires_gates=[_GATE])
    return b


def _incident() -> Backlog:
    """2026-09-25 사고의 대장 상태 — 판정 태스크가 인계 없이 done, 판정 기록 없음."""
    return _backlog()


def _passed() -> Backlog:
    """대조군 — 같은 상태에 PASS 기록(스냅샷 = 지금 done 입력)이 있다. 정말 사람 차례다."""
    return _backlog(corrections=(_pass_line([_JUDGMENT]),))


def _kind(b: Backlog, gate_id: str = _GATE) -> str | None:
    return store.gate_wait_kind(b, b.gates[gate_id])


# ── ① 단일 판정 ───────────────────────────────────────────────────────────────


class TestGateWaitKind:
    @pytest.mark.parametrize("status", ["todo", "in_progress", "review", "blocked"])
    def test_open_input_waits_for_inputs(self, status: str):
        """입력이 미종결이면 판정 기록과 무관하게 inputs — 판정할 때가 아니다."""
        assert _kind(_backlog(input_status=status)) == store.GATE_WAITS_INPUTS

    def test_open_input_of_a_human_gate_also_waits_for_inputs(self):
        """inputs 는 게이트 종류와 무관하다 — 사람 게이트도 입력이 남았으면 사람 차례가 아니다."""
        assert _kind(_backlog(input_status="todo", kind="human")) == store.GATE_WAITS_INPUTS

    def test_incident_state_is_verdict_not_person(self):
        """사고 4의 대장 상태 — 입력 done · 판정 기록 없음 → verdict (사람 차례가 아니다)."""
        b = _incident()
        assert store.gate_judgment_state(b, b.gates[_GATE]) == store.JUDGMENT_UNRECORDED
        assert _kind(b) == store.GATE_WAITS_VERDICT

    def test_pass_record_makes_it_the_persons_turn(self):
        """대조군 — 같은 상태에 현행 PASS 기록이 있으면 person."""
        assert _kind(_passed()) == store.GATE_WAITS_PERSON

    def test_stale_pass_snapshot_is_verdict(self):
        """스냅샷이 지금 done 입력과 다르면 그 PASS는 현행이 아니다 — 새 판정 없이는 verdict."""
        assert _kind(_backlog(corrections=(_pass_line([]),))) == store.GATE_WAITS_VERDICT

    def test_detached_fail_is_verdict(self):
        """입력이 다 끝났는데 FAIL 기록이 현행이면(소유 태스크가 열린 경로에 없다) verdict.

        판정은 났지만 대장이 다음 작업을 잇지 못한 상태 — 사람 차례가 아니라 기록 정정 차례다.
        """
        b = _backlog(corrections=(_fail_line(["S1-60-owner"], [_JUDGMENT]),))
        b.tasks["S1-60-owner"] = _task("S1-60-owner")
        assert store.gate_judgment_state(b, b.gates[_GATE]) == "judged:FAIL"
        assert _kind(b) == store.GATE_WAITS_VERDICT

    @pytest.mark.parametrize("kind", ["decision", "human", "external"])
    def test_gate_without_inputs_is_the_persons_turn(self, kind: str):
        assert _kind(_backlog(input_status=None, kind=kind)) == store.GATE_WAITS_PERSON

    def test_human_gate_with_done_input_is_the_persons_turn(self):
        """판정 기록은 decision 게이트의 개념 — 사람 게이트는 입력이 끝나면 정말 사람 차례다."""
        assert _kind(_backlog(kind="human")) == store.GATE_WAITS_PERSON

    def test_cancelled_input_falls_to_person_and_validate_names_the_dead_end(self):
        """취소된 입력은 열린 입력이 아니다 — 분류는 person, 막다른 길은 validate가 따로 잡는다."""
        b = _backlog(input_status="cancelled")
        assert _kind(b) == store.GATE_WAITS_PERSON
        assert any(_GATE in e and "cancelled" in e for e in store.validate_backlog(b))

    @pytest.mark.parametrize("status", ["cleared", "waived"])
    def test_passed_gate_waits_for_nothing(self, status: str):
        b = _incident()
        b.gates[_GATE].status = status
        assert _kind(b) is None


# ── ② 작업 흐름 그래프 ───────────────────────────────────────────────────────


def _graph(b: Backlog) -> dict:
    return work_graph.build_graph(b, [], TODAY)  # type: ignore[arg-type]


def _gate_node(payload: dict) -> dict:
    return payload["nodes"][f"g:{_GATE}"]


def _graph_template() -> str:
    head, tail = work_graph._template()
    return head + tail


class TestWorkGraphGateWindows:
    def test_incident_gate_window_is_not_the_humans_turn(self):
        """종전 결함 그대로의 반례 — 판정 결과 미기록 게이트가 gate_turn('사람 차례')이면 RED."""
        node = _gate_node(_graph(_incident()))
        assert node["state"] == "gate_verdict"
        assert node["label"] == work_graph.STATE_LABEL["gate_verdict"] == VERDICT_MARK
        assert VERDICT_MARK in node["reason"]

    def test_pass_control_window_is_the_humans_turn(self):
        node = _gate_node(_graph(_passed()))
        assert node["state"] == "gate_turn"
        assert node["label"] == "사람 차례"

    def test_open_input_window_waits(self):
        assert _gate_node(_graph(_backlog(input_status="todo")))["state"] == "gate_wait"

    def test_open_input_human_gate_window_says_work_remains(self):
        """판정 개념이 없는 게이트의 사유 문구도 분류를 따른다 — 입력이 남았으면 작업 차례다."""
        node = _gate_node(_graph(_backlog(input_status="todo", kind="human")))
        assert (node["state"], node["reason"]) == (
            "gate_wait",
            "이 게이트를 여는 작업이 아직 남았다",
        )
        control = _gate_node(_graph(_backlog(kind="human")))
        assert (control["state"], control["reason"]) == ("gate_turn", "담당 kiki의 행동을 기다린다")

    def test_counts_keep_verdict_out_of_the_humans_turn(self):
        counts = _graph(_incident())["counts"]
        assert counts["gate_verdict"] == 1
        assert counts["gate_turn"] == 0
        control = _graph(_passed())["counts"]
        assert (control["gate_turn"], control["gate_verdict"]) == (1, 0)

    def test_counts_add_up_with_a_verdict_window(self):
        """새 상태가 집계에서 빠지면 합이 창 수와 어긋난다 — 픽스처가 그 상태를 실제로 밟는다."""
        payload = _graph(_incident())
        assert any(n["state"] == "gate_verdict" for n in payload["nodes"].values())
        assert sum(payload["counts"].values()) == len(payload["nodes"])

    def test_text_summary_counts_and_flow_lines(self):
        text = work_graph.render_text(_graph(_incident()))
        assert f"사람 차례 0 · {VERDICT_MARK} 1" in text
        assert f"  {VERDICT_MARK}: {_GATE}" in text
        assert f"사람 차례: {_GATE}" not in text
        control = work_graph.render_text(_graph(_passed()))
        assert f"사람 차례 1 · {VERDICT_MARK} 0" in control
        assert f"  사람 차례: {_GATE}" in control

    def test_unconnected_verdict_gate_joins_the_gate_group_with_its_own_label(self):
        """이어진 창이 없는 판정 미기록 게이트도 창은 그리되(무손실) 상태는 그대로 verdict다."""
        b = _incident()
        for tid in _BEHIND:
            del b.tasks[tid]
        payload = _graph(b)
        node = _gate_node(payload)
        assert node["state"] == "gate_verdict"
        group = next(f for f in payload["frames"] if f"g:{_GATE}" in f["keys"])
        assert group["kind"] == "group" and group["group"] == "human"

    def test_template_names_the_state(self):
        assert f"gate_verdict: '{VERDICT_MARK}'" in _graph_template()

    def test_template_keeps_verdict_out_of_the_humans_turn_list(self):
        """사이드 패널 '사람 차례' 목록의 상태 집합 — gate_verdict가 들어가면 RED."""
        m = re.search(
            r"const human = KEYS\.filter\(k => \[([^\]]*)\]\.includes\(NODES\[k\]\.state\)\)",
            _graph_template(),
        )
        assert m, "사이드 패널 '사람 차례' 목록 필터를 찾지 못했다 — 템플릿 구조가 바뀌었다"
        states = {s.strip().strip("'") for s in m.group(1).split(",")}
        assert states == {"gate_turn", "human"}

    def test_template_lists_verdict_gates_in_their_own_section(self):
        template = _graph_template()
        assert "NODES[k].state === 'gate_verdict'" in template
        assert f"section('{VERDICT_MARK}'" in template

    def test_template_counts_every_gate_window_in_the_people_chip_and_group(self):
        """'사람 작업' 칩·걸러 보기 묶음은 게이트 창 세 상태를 전부 센다(칩 합 = 창 수)."""
        template = _graph_template()
        assert "c.human + c.gate_turn + c.gate_verdict + c.gate_wait" in template
        m = re.search(r"const stateGroup = n => \[([^\]]*)\]\.includes\(n\.state\)", template)
        assert m, "걸러 보기 묶음(stateGroup)을 찾지 못했다"
        assert "'gate_verdict'" in m.group(1)


# ── ③ 보드 · 정지 사유 · 세션 브리핑 ──────────────────────────────────────────


def _card_label(b: Backlog, tid: str = _BEHIND[0]) -> str:
    column, label, _detail = board.classify(b, b.tasks[tid])
    assert column == "waiting"
    return label


def _stalled(b: Backlog) -> Backlog:
    """게이트 뒤 태스크만 남긴 대장 — 착수 가능 후보가 0이 되어 정지 사유가 난다."""
    stalled = copy.deepcopy(b)
    for tid in list(stalled.tasks):
        if tid not in _BEHIND and tid != _JUDGMENT:
            del stalled.tasks[tid]
    return stalled


def _stall(b: Backlog) -> tuple[str, list[str]]:
    ready, excluded = selector.candidates(b)
    assert ready == [], [t.id for t in ready]
    return selector.stall_reason(b, excluded)


class TestBoardAndStall:
    def test_card_behind_an_incident_gate_is_not_labelled_human(self):
        assert _card_label(_incident()) == board.GATE_WAIT_LABEL[store.GATE_WAITS_VERDICT]
        assert _card_label(_incident()) == f"게이트 {VERDICT_MARK}"

    def test_card_behind_a_pass_gate_is_labelled_human(self):
        assert _card_label(_passed()) == "사람 게이트 대기"

    def test_card_behind_a_gate_with_open_inputs_waits_for_work(self):
        assert _card_label(_backlog(input_status="todo")) == "게이트 선행 작업 대기"

    def test_card_behind_mixed_gates_says_person_only_when_all_are_person(self):
        """여러 게이트가 막으면 사람 차례가 아닌 쪽을 먼저 말한다(verdict > inputs > person)."""
        b = _incident()
        b.gates["G-h184-person"] = Gate(
            id="G-h184-person", title="사람", no_inputs_reason="테스트 픽스처 — 입력 없음"
        )
        b.tasks["S1-51-phase-1"].requires_gates = ["G-h184-person", _GATE]
        assert board.gate_wait_label(b, ["G-h184-person", _GATE]) == f"게이트 {VERDICT_MARK}"
        assert _card_label(b) == f"게이트 {VERDICT_MARK}"
        b.tasks[_JUDGMENT].status = "todo"
        b.tasks[_JUDGMENT].artifacts = []
        assert board.gate_wait_label(b, ["G-h184-person", _GATE]) == "게이트 선행 작업 대기"
        assert board.gate_wait_label(b, ["G-h184-person"]) == "사람 게이트 대기"

    def test_gate_card_carries_the_wait_kind(self):
        incident, passed = _incident(), _passed()
        detail = board.gate_detail(incident, incident.gates[_GATE], TODAY)
        assert (detail["wait_kind"], detail["wait_label"]) == ("verdict", f"게이트 {VERDICT_MARK}")
        control = board.gate_detail(passed, passed.gates[_GATE], TODAY)
        assert (control["wait_kind"], control["wait_label"]) == ("person", "사람 게이트 대기")

    def test_board_page_does_not_call_every_pending_gate_a_human_action(self):
        html = board.render_html(board.build_board(_incident(), [], TODAY))
        assert "사람 게이트 — 행동 대기" not in html
        assert "byKind('verdict')" in html and "byKind('person')" in html
        assert "g.wait_label" in html

    def test_stall_on_an_incident_gate_is_gate_verdict(self):
        assert _stall(_stalled(_incident())) == ("gate_verdict", [_GATE])

    def test_stall_on_a_pass_gate_is_human_gate(self):
        assert _stall(_stalled(_passed())) == ("human_gate", [_GATE])

    def test_stall_names_only_the_verdict_gates_when_mixed(self):
        b = _stalled(_incident())
        b.gates["G-h184-person"] = Gate(
            id="G-h184-person", title="사람", no_inputs_reason="테스트 픽스처 — 입력 없음"
        )
        b.tasks["S1-52-phase-2"].requires_gates = ["G-h184-person"]
        assert _stall(b) == ("gate_verdict", [_GATE])

    @pytest.mark.parametrize(
        ("make", "expected"),
        [(_incident, "gate_verdict"), (_passed, "human_gate")],
        ids=["incident", "pass-control"],
    )
    def test_stall_with_other_blockers_takes_the_second_site(self, make, expected):
        """정지 사유가 게이트를 말하는 **두 번째 지점**(선행 대기가 섞여도 게이트로 접는 경로).

        선행 대기 태스크가 하나라도 있으면 첫 지점(게이트만 남음)을 건너뛰고 두 번째 지점으로
        간다 — 그 지점만 종전 human_gate 로 남으면 이 반례가 RED를 낸다.
        """
        b = _stalled(make())
        b.tasks["S1-54-after"] = _task("S1-54-after", depends_on=[_BEHIND[0]])
        _, excluded = selector.candidates(b)
        assert {e.reason for e in excluded} == {"gates", "deps"}  # 픽스처가 두 번째 지점을 밟는다
        assert _stall(b) == (expected, [_GATE])

    def test_session_brief_does_not_announce_a_human_gate(self):
        text = report.render_brief(_stalled(_incident()), [], "claude/h184", TODAY)
        line = next(ln for ln in text.splitlines() if ln.startswith("착수 가능 태스크 없음"))
        assert f"게이트 {VERDICT_MARK}" in line and _GATE in line
        assert not any(p in line for p in HUMAN_TURN_PHRASES)
        control = report.render_brief(_stalled(_passed()), [], "claude/h184", TODAY)
        assert "사람 게이트 대기 중" in control


# ── ④ 전 화면 대조 (디스크 대장 · CLI) ─────────────────────────────────────────


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
            f"HARN-184 테스트 {task_id}",
            "--track",
            "math-completion",
            "--stage",
            "S1",
            *extra,
        ]
    )
    assert rc == 0, f"픽스처 태스크 등재 실패: {task_id}"


def _set_status(root: Path, task_id: str, status: str) -> None:
    """판정 인계를 **거치지 않고** 태스크를 닫는다 — HARN-177 ⑤의 한계가 만드는 바로 그 상태."""
    backlog, errors = store.load_backlog(root)
    assert errors == [], errors
    task = backlog.tasks[task_id]
    task.status = status
    if status == "done":
        task.artifacts = [_ARTIFACT]
    store.save_task(root, task)


def _disk_incident(root: Path, *, pass_recorded: bool) -> Backlog:
    """③ 재현 픽스처(HARN-177과 같은 형태)를 디스크 대장에 만든다 — 모든 CLI 화면이 이것을 읽는다."""
    _add(_JUDGMENT)
    assert (
        cli.main(
            ["gates", "add", _GATE, "--title", "진입 게이트", "--kind", "decision"]
            + ["--depends", _JUDGMENT]
        )
        == 0
    )
    for tid in _BEHIND:
        _add(tid, "--gates", _GATE)
    _set_status(root, _JUDGMENT, "done")
    if pass_recorded:
        rc = cli.main(
            ["gates", "amend", _GATE, "--verdict", "PASS", "--evidence", _EVIDENCE]
            + ["--reason", "대조군 PASS"]
        )
        assert rc == 0
    backlog, errors = store.load_backlog(root)
    assert errors == [], errors
    return backlog


def _out(capsys, *argv: str) -> str:
    capsys.readouterr()
    assert cli.main(list(argv)) == 0
    return capsys.readouterr().out


def _block(text: str, start: str, stop: tuple[str, ...]) -> str:
    """`start`로 시작하는 줄부터 `stop` 중 하나로 시작하는 다음 줄 직전까지 (앞 공백 무시)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith(start):
            block = [line]
            for nxt in lines[i + 1 :]:
                if not nxt.strip() or nxt.lstrip().startswith(stop):
                    break
                block.append(nxt)
            return "\n".join(block)
    raise AssertionError(f"'{start}' 로 시작하는 줄이 없다:\n{text}")


def _line_with(text: str, needle: str) -> str:
    hits = [line for line in text.splitlines() if needle in line]
    assert len(hits) == 1, (needle, hits)
    return hits[0]


def _surfaces(root: Path, backlog: Backlog, capsys) -> dict[str, str]:
    """화면 이름 → 그 화면이 **이 게이트**에 대해 내는 글자(다른 게이트 줄은 섞지 않는다)."""
    status = _out(capsys, "status")
    status_json = json.loads(_out(capsys, "status", "--json"))
    judgment = next(g for g in status_json["pending_gates"] if g["id"] == _GATE)["judgment"]
    payload = _graph(backlog)
    node = _gate_node(payload)
    stalled = _stalled(backlog)
    code, detail = _stall(stalled)
    brief = report.render_brief(stalled, [], "claude/h184", TODAY)
    return {
        "next 대기 경로": _line_with(_out(capsys, "next", "--no-remote"), f"← {_GATE} ("),
        "status 대기 경로": _line_with(status, f"← {_GATE} ("),
        "status 게이트 목록": _block(status, f"⏳ {_GATE} ", ("⏳ ", "──")),
        "status --json": {
            store.JUDGMENT_UNRECORDED: VERDICT_MARK,
            "judged:PASS": "사람 판정 대기",
        }.get(judgment, f"judgment={judgment}"),
        "gates list": _block(_out(capsys, "gates", "list"), f"· {_GATE} ", ("· G-", "──")),
        "gates show": _out(capsys, "gates", "show", _GATE),
        "작업 흐름 그래프 창": f"{node['label']} · {node['reason']}",
        "작업 흐름 그래프 요약": _line_with(work_graph.render_text(payload), f": {_GATE}"),
        "보드 카드": _card_label(backlog),
        "보드 게이트 카드": str(
            board.gate_detail(backlog, backlog.gates[_GATE], TODAY)["wait_label"]
        ),
        "정지 사유": f"{code} {detail}".replace("human_gate", "사람 게이트 대기").replace(
            "gate_verdict", VERDICT_MARK
        ),
        "세션 브리핑": _line_with(brief, "착수 가능 태스크 없음"),
    }


class TestAllSurfaces:
    """④ — 사고 대장 상태 하나로 **모든 화면**을 대조한다. 화면이 늘면 여기와 아래 등재표에 넣는다."""

    def test_no_surface_calls_the_incident_gate_a_humans_turn(self, repo: Path, capsys):
        surfaces = _surfaces(repo, _disk_incident(repo, pass_recorded=False), capsys)
        wrong = {name: text for name, text in surfaces.items() if VERDICT_MARK not in text}
        assert not wrong, f"판정 결과 미기록을 말하지 않는 화면: {wrong}"
        human = {
            name: text
            for name, text in surfaces.items()
            if any(phrase in text for phrase in HUMAN_TURN_PHRASES)
        }
        assert not human, f"판정 결과 미기록 게이트를 사람 차례로 부르는 화면: {human}"

    def test_every_surface_calls_the_pass_gate_a_humans_turn(self, repo: Path, capsys):
        """대조군 — 같은 게이트에 PASS를 기록하면 모든 화면이 사람 차례로 부른다(과잉 수정 방지)."""
        surfaces = _surfaces(repo, _disk_incident(repo, pass_recorded=True), capsys)
        not_human = {
            name: text
            for name, text in surfaces.items()
            if not any(phrase in text for phrase in HUMAN_TURN_PHRASES)
        }
        assert not not_human, f"PASS 기록 게이트를 사람 차례로 부르지 않는 화면: {not_human}"
        stale = {name: text for name, text in surfaces.items() if VERDICT_MARK in text}
        assert not stale, f"PASS 기록 뒤에도 판정 결과 미기록이라고 하는 화면: {stale}"


# ── ④ 사람 차례 문구를 내는 모듈 전수 등재 ─────────────────────────────────────

HARNESS = Path(__file__).resolve().parents[2] / "scripts" / "harness"

#: 사람 차례 문구를 담은 하네스 모듈 → 위 전 화면 대조의 어느 화면인지, 또는 화면이 아닌 사유.
#: 새 모듈이 사람 차례를 말하기 시작하면 아래 검사가 RED가 된다 — 등재하면서 그 화면을
#: `_surfaces`에 넣을지(판정 결과 미기록 게이트를 어떻게 부르는지) 결정하라는 뜻이다.
SURFACE_REGISTRY: dict[str, str] = {
    "store.py": "판정 문구·분류의 정본(judgment_state_label · gate_wait_kind) — 화면은 이것을 부른다",
    "selector.py": "next·status 대기 경로 꼬리(gate_tail_suffix) · 정지 사유(_gate_stall)",
    "report.py": "status 게이트 목록·gates list/show 여는 작업 줄 · 세션 브리핑 정지 사유",
    "backlog.py": "done 인계 거부 메시지·주석이 사고를 설명할 뿐 게이트를 분류하지 않는다",
    "board.py": "보드 카드 라벨 · 게이트 카드 · 게이트 패널 제목",
    "work_graph.py": "작업 흐름 그래프 게이트 창 상태 · 집계 · 텍스트 요약",
    "work_graph_page.html": "작업 흐름 그래프 화면(사이드 패널 '사람 차례' 목록 · 칩 · 범례)",
}


def _modules_with_human_turn_phrases() -> set[str]:
    """하네스 모듈 중 사람 차례 문구를 담은 것 — 뮤테이션 하네스(verify_*)는 화면이 아니라 뺀다."""
    found: set[str] = set()
    for path in sorted(HARNESS.iterdir()):
        if path.suffix not in (".py", ".html") or path.name.startswith("verify_"):
            continue
        text = path.read_text(encoding="utf-8")
        if any(phrase in text for phrase in HUMAN_TURN_PHRASES):
            found.add(path.name)
    return found


class TestSurfaceRegistry:
    """한계(명시): 문구 스캔이다 — 다른 낱말로 사람 차례를 말하는 화면은 못 잡는다. 이 검사가 막는
    것은 "이미 알려진 말로 사람 차례를 말하는 새 모듈이 대조 목록 밖에 생기는 것"이다."""

    def test_scan_is_not_vacuous(self):
        assert len(_modules_with_human_turn_phrases()) >= 3

    def test_every_module_that_speaks_of_a_humans_turn_is_registered(self):
        unregistered = _modules_with_human_turn_phrases() - set(SURFACE_REGISTRY)
        assert not unregistered, (
            f"사람 차례 문구를 내는 모듈이 등재표 밖에 있다: {sorted(unregistered)} — 그 화면이 판정 "
            "결과 미기록 게이트를 어떻게 부르는지 확인하고 _surfaces·SURFACE_REGISTRY 에 넣어라"
        )

    def test_registry_has_no_stale_entries(self):
        stale = set(SURFACE_REGISTRY) - _modules_with_human_turn_phrases()
        assert not stale, f"등재표에 있지만 사람 차례 문구가 없는 모듈: {sorted(stale)}"
