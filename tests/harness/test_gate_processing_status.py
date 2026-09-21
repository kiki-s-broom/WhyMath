"""HARN-94 — 게이트 화면이 **처리 상황**을 말한다 (경과 / 독촉 기한 / 대기 태스크 / 급한 순).

배경(2026-09-08 `/gates` 실측): 세 화면(`gates list` · `status` 텍스트 · `status --json`)이
pending 게이트에 대해 **경과일만** 냈다. `remind_after_days`는 어디에도 나오지 않았고 정렬은
id순이었다. 그래서 이런 일이 벌어졌다:

    G-eos63-skill-event-reach-sample      — 7일 경과   (기한 7일  → **초과**)
    G-eos-ip-separation-evidence          — 9일 경과   (기한 14일 → 미도래·5일 남음)

화면에서 둘은 "7일 경과"와 "9일 경과"였고, **덜 급한 쪽이 더 급해 보였다**. 경과일만 크면
급해 보이기 때문이다. 게다가 목록에는 재확인 지점이 미래인 예약 게이트가 섞여 있어
(2026-10-26 · 2026-09-27 · 2026-12-13), 그것들이 "N일 방치"로 읽히면 목록 전체가 소음이 된다 —
소음이 된 목록은 사람이 읽지 않는다.

이 파일이 계약으로 동결하는 것:
  ① 초과/미도래 판정이 **경과일과 기한 둘 다**를 본다 (경과일만으로 급함을 정하지 않는다).
  ② 셋 다 낸다 — 경과 · 기한 · 초과/잔여. 하나라도 빠지면 두 게이트가 같아 보인다.
  ③ 정렬이 급한 순이다 (id순은 급한 것을 아래로 민다).
  ④ 대기 태스크 건수는 `selector.gate_dependent_tasks` 하나에서 온다 (두 화면이 갈라지지 않게).
  ⑤ **모르면 단정하지 않는다** — 기한 미설정·경과일 미상을 '초과'로 접지 않는다.
  ⑥ JSON도 같은 사실을 낸다 (텍스트만 고치면 기계 소비자는 여전히 구분 못 한다).

픽스처는 **세 상태를 모두 밟는다**(초과 · 미도래 · 기한없음). 하나라도 빠지면 그 절이
뮤테이션에서 살아남는다 — CLAUDE.md 2026-09-07 "픽스처가 그 절을 실제로 밟는가".
"""

from __future__ import annotations

import json
from datetime import date

import report
from models import Backlog, Gate, Task

_TODAY = date(2026, 9, 8)


def _gate(gid: str, *, requested: str = "2026-09-01", remind: int | None = 7) -> Gate:
    return Gate(
        id=gid,
        title=f"{gid} 제목",
        kind="human",
        assignee="kiki",
        status="pending",
        requested=requested,
        remind_after_days=remind,
    )


def _backlog(*gates: Gate, tasks: list[Task] | None = None) -> Backlog:
    return Backlog(
        stage_order=["S1"],
        gates={g.id: g for g in gates},
        tasks={t.id: t for t in (tasks or [])},
    )


def _task(task_id: str, *, gates: list[str], status: str = "blocked") -> Task:
    return Task(
        id=task_id,
        title=f"{task_id} 제목",
        track="math-completion",
        stage="S1",
        status=status,
        requires_gates=gates,
    )


# ---------------------------------------------------------------------------
# 계약 ① — 급함은 경과일이 아니라 **경과일 대 기한**이다 (이 태스크의 본체)
# ---------------------------------------------------------------------------


def test_fewer_elapsed_days_can_still_be_overdue() -> None:
    """**이 태스크가 존재하는 이유** — 실측 그대로의 두 게이트.

    7일 경과/기한 7일은 초과이고, 9일 경과/기한 14일은 미도래다. 경과일만 보면 뒤집힌다.
    """
    short = _gate("G-short", requested="2026-09-01", remind=7)  # 7일 경과 / 기한 7
    long_ = _gate("G-long", requested="2026-08-30", remind=14)  # 9일 경과 / 기한 14
    views = {v.gate.id: v for v in report.pending_gate_views(_backlog(short, long_), _TODAY)}

    assert views["G-short"].days == 7 and views["G-long"].days == 9
    assert views["G-short"].overdue is True, "기한 7일에 7일 경과인데 초과가 아니다"
    assert views["G-long"].overdue is False, "기한 14일에 9일 경과인데 초과로 판정했다"


def test_overdue_sorts_before_more_elapsed_but_not_due() -> None:
    """정렬이 급한 순인가 — id순이면 G-long이 먼저 온다(알파벳)."""
    short = _gate("G-short", requested="2026-09-01", remind=7)
    long_ = _gate("G-long", requested="2026-08-30", remind=14)
    order = [v.gate.id for v in report.pending_gate_views(_backlog(long_, short), _TODAY)]
    assert order == ["G-short", "G-long"], f"급한 순이 아니다: {order}"


def test_more_overdue_sorts_first_among_overdue() -> None:
    """초과분끼리는 많이 지난 순."""
    a = _gate("G-a", requested="2026-09-01", remind=7)  # 0일 지남
    b = _gate("G-b", requested="2026-08-01", remind=7)  # 31일 지남
    order = [v.gate.id for v in report.pending_gate_views(_backlog(a, b), _TODAY)]
    assert order == ["G-b", "G-a"], order


def test_sooner_deadline_sorts_first_among_pending() -> None:
    """미도래끼리는 임박한 순 — 경과일이 아니라 **남은 일수**로."""
    soon = _gate("G-soon", requested="2026-09-07", remind=3)  # 1일 경과, 2일 남음
    later = _gate("G-later", requested="2026-08-30", remind=30)  # 9일 경과, 21일 남음
    order = [v.gate.id for v in report.pending_gate_views(_backlog(later, soon), _TODAY)]
    assert order == ["G-soon", "G-later"], order


# ---------------------------------------------------------------------------
# 계약 ② — 셋 다 낸다 (경과 · 기한 · 초과/잔여)
# ---------------------------------------------------------------------------


def test_status_text_carries_all_three_numbers_when_overdue() -> None:
    view = report.pending_gate_views(
        _backlog(_gate("G-x", requested="2026-08-01", remind=7)), _TODAY
    )[0]
    text = view.status_text()
    assert "38일 경과" in text, text  # 경과
    assert "기한 7일" in text, text  # 분모
    assert "31일 지남" in text, text  # 초과분
    assert "독촉 초과" in text, text


def test_status_text_carries_all_three_numbers_when_pending() -> None:
    view = report.pending_gate_views(
        _backlog(_gate("G-x", requested="2026-09-05", remind=14)), _TODAY
    )[0]
    text = view.status_text()
    assert "3일 경과" in text and "기한 14일" in text and "11일 남음" in text, text


def test_exactly_on_deadline_reads_as_today_not_zero_days() -> None:
    """`0일 지남`은 사람에게 안 읽힌다 — 오늘이 기한임을 말로 낸다."""
    view = report.pending_gate_views(
        _backlog(_gate("G-x", requested="2026-09-01", remind=7)), _TODAY
    )[0]
    assert view.over_by == 0
    assert "오늘 기한 도달" in view.status_text(), view.status_text()


# ---------------------------------------------------------------------------
# 계약 ⑤ — 모른다 ≠ 초과 (3상태를 truthiness로 접지 않는다)
# ---------------------------------------------------------------------------


def test_gate_without_deadline_is_not_overdue() -> None:
    """기한 미설정은 '초과 아님'이지 '급하지 않음'을 단정하는 것도 아니다 — 사실만 낸다."""
    view = report.pending_gate_views(
        _backlog(_gate("G-x", requested="2026-01-01", remind=None)), _TODAY
    )[0]
    assert view.overdue is False, "기한이 없는데 초과로 판정했다"
    assert view.over_by is None and view.remaining is None
    assert "독촉 기한 없음" in view.status_text(), view.status_text()


def test_gate_without_requested_date_reports_unknown_not_zero() -> None:
    """requested 미기재를 '0일 경과'로 접으면 갓 등재된 게이트처럼 보인다."""
    view = report.pending_gate_views(_backlog(_gate("G-x", requested="", remind=7)), _TODAY)[0]
    assert view.days is None
    assert view.overdue is False
    assert "미상" in view.status_text(), view.status_text()


def test_undated_gates_sort_last() -> None:
    """판정할 수 없는 것이 급한 것을 밀어내지 않는다."""
    order = [
        v.gate.id
        for v in report.pending_gate_views(
            _backlog(
                _gate("G-a-undated", requested="", remind=None),
                _gate("G-z-overdue", requested="2026-08-01", remind=7),
            ),
            _TODAY,
        )
    ]
    assert order == ["G-z-overdue", "G-a-undated"], order


# ---------------------------------------------------------------------------
# 계약 ④ — 대기 태스크는 단일 진실 원천에서 온다
# ---------------------------------------------------------------------------


def test_dependents_come_from_requires_gates() -> None:
    backlog = _backlog(
        _gate("G-x"),
        tasks=[
            _task("AAA-01-alpha", gates=["G-x"]),
            _task("BBB-02-beta", gates=["G-other"]),
        ],
    )
    view = report.pending_gate_views(backlog, _TODAY)[0]
    assert view.dependents == ["AAA-01-alpha"], view.dependents


def test_done_and_cancelled_tasks_are_not_counted_as_waiting() -> None:
    """끝난 태스크가 '대기 중'으로 세어지면 게이트가 실제보다 무겁게 보인다."""
    backlog = _backlog(
        _gate("G-x"),
        tasks=[
            _task("AAA-01-alpha", gates=["G-x"], status="done"),
            _task("BBB-02-beta", gates=["G-x"], status="cancelled"),
            _task("CCC-03-gamma", gates=["G-x"], status="todo"),
        ],
    )
    view = report.pending_gate_views(backlog, _TODAY)[0]
    assert view.dependents == ["CCC-03-gamma"], view.dependents


def test_cleared_gates_are_not_listed() -> None:
    cleared = _gate("G-done")
    cleared.status = "cleared"
    assert report.pending_gate_views(_backlog(cleared), _TODAY) == []


# ---------------------------------------------------------------------------
# 계약 ⑥ — 세 화면이 같은 사실을 낸다 (텍스트 · JSON · gates list)
# ---------------------------------------------------------------------------


def _sample_backlog() -> Backlog:
    """초과 · 미도래 · 기한없음 **세 상태를 모두** 담는다 (픽스처 접촉)."""
    return _backlog(
        _gate("G-overdue", requested="2026-08-01", remind=7),
        _gate("G-waiting", requested="2026-09-05", remind=14),
        _gate("G-nodeadline", requested="2026-09-01", remind=None),
        tasks=[_task("AAA-01-alpha", gates=["G-overdue"])],
    )


def test_status_text_screen_shows_deadline_and_ordering() -> None:
    out = report.render_status(_sample_backlog(), [], _TODAY)
    assert "독촉 초과 1건" in out, out
    assert "기한 7일" in out and "기한 14일" in out, "기한이 화면에 없다"
    assert out.index("G-overdue") < out.index("G-waiting") < out.index("G-nodeadline"), out
    assert "대기 태스크 1건" in out and "대기 태스크 0건" in out, out


def test_status_json_exposes_the_same_facts() -> None:
    """JSON 키는 `dependents`다 — `blocked_tasks`가 아니다 (Codex P2 · PR #1070).

    acceptance ⑦의 `blocked_tasks`라는 이름이 틀렸다: 게이트는 status가 blocked인
    태스크만 붙잡는 게 아니라 `todo`도 requires_gates로 착수 후보에서 제외한다. blocked만
    세면 게이트가 붙잡는 양을 과소 보고하므로, 이름을 값의 의미에 맞추고 계약을 정정했다.
    이 단언이 그 결정을 동결한다 — 되돌리려면 계약부터 다시 손봐야 한다.
    """
    payload = json.loads(report.render_status_json(_sample_backlog(), [], _TODAY))
    by_id = {g["id"]: g for g in payload["pending_gates"]}

    assert by_id["G-overdue"]["overdue"] is True
    assert by_id["G-overdue"]["remind_after_days"] == 7
    assert by_id["G-overdue"]["over_by"] == 31
    assert by_id["G-overdue"]["dependents"] == ["AAA-01-alpha"]

    assert by_id["G-waiting"]["overdue"] is False
    assert by_id["G-waiting"]["remaining"] == 11

    assert by_id["G-nodeadline"]["remind_after_days"] is None
    assert by_id["G-nodeadline"]["overdue"] is False

    order = [g["id"] for g in payload["pending_gates"]]
    assert order == ["G-overdue", "G-waiting", "G-nodeadline"], order


def test_json_and_text_agree_on_overdue_set() -> None:
    """두 화면이 갈라지지 않는지 — 한쪽만 고쳐지는 회귀를 잡는다."""
    backlog = _sample_backlog()
    payload = json.loads(report.render_status_json(backlog, [], _TODAY))
    json_overdue = {g["id"] for g in payload["pending_gates"] if g["overdue"]}
    views_overdue = {v.gate.id for v in report.pending_gate_views(backlog, _TODAY) if v.overdue}
    assert json_overdue == views_overdue == {"G-overdue"}
