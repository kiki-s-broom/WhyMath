"""work_graph.py — 작업 흐름 그래프(HARN-182)의 계약 테스트 (날짜 고정).

이 그래프는 board.py와 같은 읽기 전용 투영이지만, 칸반과 달리 **좌표**를 만든다. 그래서
테스트가 고정하는 계약은 판정·집계뿐 아니라 기하까지 넓다(아래 절 제목의 번호는 파일 안 순서다):
    · 무손실 — 열린 작업·미통과 게이트·미머지 브랜치가 전부 정확히 한 프레임에 들어간다
    · 간선 전수 — 열린 노드끼리 잇는 간선이 하나도 빠지지 않는다(끝난 선행은 상세에만)
    · 결정성 — 같은 입력이면 같은 좌표(삽입 순서·해시 시드와 무관)
    · 배치 기하 — 창·프레임이 겹치지 않고, 연결선은 출력 포트 → 입력 포트로 왼→오
    · 판정 무복제 — 창 상태는 board/selector 판정을 그대로 쓴다
    · 판정 불가 표기 — 원격 스캔을 안 했거나 못 했으면 "없음"이 아니라 "판정 불가"다
    · 순환 내성 — validate가 거부할 대장도 무한 루프 없이 그리고, 순환 간선을 표시한다
    · 읽기 전용 — CLI는 backlog/ 를 일절 쓰지 않는다

픽스처는 합성 Backlog다(실저장소 데이터 의존 금지 — CLI·읽기 전용·해시 시드 검사만 예외).
기하 계약은 작은 픽스처로는 절을 밟지 못하는 경우가 있어(줄바꿈되는 프레임 선반·2줄 이상
격자·두 층 이상 건너는 연결선) 큰 합성 픽스처와 순환 픽스처로도 같은 검사를 돌리고, 각
픽스처가 그 절을 실제로 밟는지를 따로 단언한다(`TestFixtureContact`).
"""

from __future__ import annotations

import copy
import itertools
import json
import os
import random
import subprocess
import sys
import threading
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path

import board
import pytest
import remote_claims
import selector
import store
import work_graph
from models import TERMINAL_STATUSES, Backlog, Gate, Task, Track

TODAY = date(2026, 9, 28)
OPEN_TASK_STATUSES = ("todo", "in_progress", "review", "blocked")
PAYLOAD_MARKER = '<script id="payload" type="application/json">'
INJECTED = "</script><script>alert(1)</script>"


# ── 픽스처 ───────────────────────────────────────────────────────────────────


def _task(tid: str, title: str, **fields: object) -> Task:
    """스테이지는 ID 접두(`S1-…` → `S1`)에서, 트랙은 기본 `main`."""
    fields.setdefault("track", "main")
    fields.setdefault("stage", tid.split("-")[0])
    return Task(id=tid, title=title, **fields)  # type: ignore[arg-type]


def _backlog() -> Backlog:
    """흐름 3개 + 연결 없는 창 여러 상태 + 끝난 태스크·통과한 게이트.

    흐름 A (게이트 포함 사슬 + 두 층 이상 건너는 간선):
        S1-10-alpha → S1-11-beta → G-alpha → S2-10-gamma
                    ↘ S2-19-delta, S2-20-eps (같은 층에 창 3개 — 세로 쌓기)
        alpha → gamma 는 3층을 건너 빈 자리(dummy) 2개를 지난다.
        beta는 끝난 S1-12-done도 선행으로 가진다(그리지 않고 상세에만).
    흐름 B: G-key(입력 없음 = 사람 차례) → S2-11-keyed → S2-12-human(사람 소유)
    흐름 C: 트랙 진입 게이트 G-e-axis(담당 claude) → E1-01-track, E1-02-track
    연결 없는 창: 진행·검토·차단·시작 가능 3·사람 소유·다른 세션 claim, 그리고
        끝난 태스크만 입력으로 가진 G-solo(열린 선행이 없으므로 사람 차례).
    """
    b = Backlog(stage_order=["S1", "S2", "E1"])
    b.tracks["main"] = Track(id="main", title="기본")
    b.tracks["e-axis"] = Track(id="e-axis", title="확장", entry_gate="G-e-axis")

    b.gates["G-alpha"] = Gate(
        id="G-alpha",
        title="알파 관문",
        requested="2026-09-01",
        depends_on=["S1-11-beta"],
        notes="알파 판정 런북 첫 문단\n\n둘째 문단",
    )
    b.gates["G-key"] = Gate(
        id="G-key",
        title="키 투입",
        requested="2026-08-11",
        remind_after_days=7,
        no_inputs_reason="Kiki 머신에서 직접 투입",
    )
    b.gates["G-e-axis"] = Gate(
        id="G-e-axis",
        title="E축 진입",
        kind="decision",
        assignee="claude",
        no_inputs_reason="에이전트 판정",
    )
    b.gates["G-solo"] = Gate(
        id="G-solo", title="홀로 남은 관문", assignee="partner", depends_on=["S1-16-done"]
    )
    b.gates["G-cleared"] = Gate(
        id="G-cleared", title="통과한 관문", status="cleared", evidence="PR #1", cleared_by="kiki"
    )
    b.gates["G-waived"] = Gate(id="G-waived", title="면제된 관문", status="waived")

    # 흐름 A
    b.tasks["S1-10-alpha"] = _task(
        "S1-10-alpha",
        "알파 시작",
        acceptance=["가" * 200, "   ", "둘째 조건\n  줄바꿈 포함", "셋째 조건"],
    )
    b.tasks["S1-12-done"] = _task("S1-12-done", "끝난 선행", status="done", artifacts=["#10"])
    b.tasks["S1-11-beta"] = _task("S1-11-beta", "베타", depends_on=["S1-10-alpha", "S1-12-done"])
    b.tasks["S2-10-gamma"] = _task(
        "S2-10-gamma", "감마", depends_on=["S1-10-alpha"], requires_gates=["G-alpha"]
    )
    b.tasks["S2-19-delta"] = _task("S2-19-delta", "델타", depends_on=["S1-10-alpha"])
    b.tasks["S2-20-eps"] = _task("S2-20-eps", "엡실론", depends_on=["S1-10-alpha"])

    # 흐름 B
    b.tasks["S2-11-keyed"] = _task("S2-11-keyed", "키 필요", requires_gates=["G-key"])
    b.tasks["S2-12-human"] = _task(
        "S2-12-human", "사람 후속", owner="kiki", depends_on=["S2-11-keyed"]
    )

    # 흐름 C
    b.tasks["E1-01-track"] = _task("E1-01-track", "트랙 첫 작업", track="e-axis")
    b.tasks["E1-02-track"] = _task("E1-02-track", "트랙 둘째 작업", track="e-axis")

    # 연결 없는 창
    b.tasks["S1-13-run"] = _task("S1-13-run", "진행건", status="in_progress", session="claude/x")
    b.tasks["S1-14-review"] = _task("S1-14-review", "검토건", status="review")
    b.tasks["S1-15-blocked"] = _task(
        "S1-15-blocked", "차단건", status="blocked", notes="[차단 2026-09-20] 외부 회신 대기"
    )
    b.tasks["S2-13-ready"] = _task(
        "S2-13-ready",
        "착수가능",
        notes="첫 문단 첫 줄\n첫 문단 둘째 줄\n\n둘째 문단",
    )
    b.tasks["S2-14-ready2"] = _task("S2-14-ready2", "착수가능 우선", priority=1)
    b.tasks["S2-15-human"] = _task("S2-15-human", "사람 소유 단독", owner="kiki")
    b.tasks["S2-17-claimed"] = _task("S2-17-claimed", "다른 세션 잡음", session="claude/y")
    b.tasks["S2-18-after-cleared"] = _task(
        "S2-18-after-cleared", "통과 게이트 뒤", requires_gates=["G-cleared"]
    )
    b.tasks["S2-16-cancel"] = _task("S2-16-cancel", "취소건", status="cancelled")
    b.tasks["S1-16-done"] = _task("S1-16-done", "끝난 입력", status="done", artifacts=["#11"])
    return b


def _stale(branch: str, status: str = "isolated", evidence: str = "") -> remote_claims.StaleBranch:
    return remote_claims.StaleBranch(
        branch=branch,
        ref=f"refs/remotes/origin/{branch}",
        last_commit_at=datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc),
        age_days=12.46,
        ahead=4,
        status=status,
        evidence=evidence,
    )


def _remote_kwargs() -> dict[str, object]:
    """원격 스캔 3종 — 창이 생겨야 하는 브랜치 4개와 생기면 안 되는 브랜치 3개를 섞는다.

    생긴다: claude/done-br(미머지 완료 2건 — 순서 검사용) · claude/other(claim + 고립 스캔 pr_filed) ·
            claude/foreign(로컬 대장에 없는 태스크 claim) · claude/stale-only(고립 스캔만)
    안 생긴다: claude/old(끝난 태스크의 완료분) · claude/ghost(대장에 없는 태스크의 완료분) ·
            claude/closed(로컬에서 끝난 태스크의 claim)
    """
    return {
        "remote_done": {
            "S2-20-eps": ["claude/done-br"],
            "S2-14-ready2": ["claude/done-br"],
            "S1-16-done": ["claude/old"],
            "ZZ-98-gone": ["claude/ghost"],
        },
        "remote_done_status": "ok",
        "remote_claimed": {
            "S2-13-ready": "claude/other",
            "ZZ-99-foreign": "claude/foreign",
            "S2-16-cancel": "claude/closed",
        },
        "remote_claim_status": "ok",
        "stale_branches": [
            _stale("claude/stale-only"),
            _stale("claude/other", status="pr_filed", evidence="PR #12"),
        ],
        "stale_status": "ok",
    }


EXPECTED_BRANCHES = {"claude/done-br", "claude/other", "claude/foreign", "claude/stale-only"}


def _big_backlog(flows: int = 14, singles: int = 40, blocked: int = 6) -> Backlog:
    """기하 스트레스용 — 프레임 선반이 여러 줄로 꺾이고 그룹 격자가 2줄 이상이 되는 크기.

    흐름마다 a → b → c → d 사슬 + a → d(3층 건넘) + a → e(갈래). 세 흐름에 한 번은
    c → 게이트 → d 를 끼워 층을 하나 더 늘린다(흐름 크기가 달라 정렬 순서도 밟는다).
    """
    b = Backlog(stage_order=["S1", "S2"])
    b.tracks["main"] = Track(id="main", title="기본")
    for i in range(flows):
        a, bb, c, d, e = (f"F{i:02d}-{n:02d}-node" for n in (1, 2, 3, 4, 5))
        b.tasks[a] = _task(a, f"흐름 {i} 시작", stage="S1")
        b.tasks[bb] = _task(bb, f"흐름 {i} 둘째", stage="S1", depends_on=[a])
        b.tasks[c] = _task(c, f"흐름 {i} 셋째", stage="S1", depends_on=[bb])
        b.tasks[e] = _task(e, f"흐름 {i} 갈래", stage="S2", depends_on=[a])
        gates: list[str] = []
        if i % 3 == 0:
            gid = f"G-flow{i:02d}"
            b.gates[gid] = Gate(id=gid, title=f"흐름 {i} 관문", depends_on=[c])
            gates = [gid]
        b.tasks[d] = _task(d, f"흐름 {i} 끝", stage="S2", depends_on=[a, c], requires_gates=gates)
    for k in range(singles):
        tid = f"R1-{k:02d}-solo"
        b.tasks[tid] = _task(tid, f"단독 {k}", stage="S2", priority=1 + k % 5)
    for k in range(blocked):
        tid = f"B1-{k:02d}-stuck"
        b.tasks[tid] = _task(tid, f"차단 {k}", stage="S2", status="blocked", notes="[차단] 사유")
    return b


def _cyclic_backlog() -> Backlog:
    """validate가 거부할 대장 — 태스크 3-순환 + 게이트 경유 2-순환 + 순환 밖 후속."""
    b = Backlog(stage_order=["S1"])
    b.tracks["main"] = Track(id="main", title="기본")
    b.tasks["S1-01-ring"] = _task("S1-01-ring", "고리 1", depends_on=["S1-03-ring"])
    b.tasks["S1-02-ring"] = _task("S1-02-ring", "고리 2", depends_on=["S1-01-ring"])
    b.tasks["S1-03-ring"] = _task("S1-03-ring", "고리 3", depends_on=["S1-02-ring"])
    b.tasks["S1-04-after"] = _task("S1-04-after", "고리 뒤", depends_on=["S1-03-ring"])
    b.gates["G-loop"] = Gate(id="G-loop", title="고리 관문", depends_on=["S1-05-loop"])
    b.tasks["S1-05-loop"] = _task("S1-05-loop", "관문 고리", requires_gates=["G-loop"])
    return b


RING = {"t:S1-01-ring", "t:S1-02-ring", "t:S1-03-ring"}
GATE_LOOP = {"g:G-loop", "t:S1-05-loop"}


def _graph(backlog: Backlog | None = None, **kwargs: object) -> dict:
    return work_graph.build_graph(backlog or _backlog(), [], TODAY, **kwargs)  # type: ignore[arg-type]


def _frames_by_id(payload: dict) -> dict[str, dict]:
    return {frame["id"]: frame for frame in payload["frames"]}


def _drawn(payload: dict) -> list[tuple[str, str, str]]:
    return [(e["src"], e["dst"], e["kind"]) for e in payload["edges"]]


def _link(item: dict, side: str, key: str) -> dict:
    return next(link for link in item[side] if link["key"] == key)


def _within_deadline(fn: Callable[[], object], seconds: float = 30.0) -> object:
    """무한 루프가 스위트 전체를 멈추지 않게 — 기한 안에 안 끝나면 실패로 판정한다."""
    box: dict[str, object] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # 예외도 호출측으로 넘긴다(삼키지 않는다)
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(seconds)
    assert not worker.is_alive(), f"{seconds}초 안에 끝나지 않았다 — 순환에서 무한 루프 의심"
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]


# ── ① 무손실 ─────────────────────────────────────────────────────────────────


class TestLossless:
    @pytest.mark.parametrize("remote", [False, True], ids=["no-remote", "remote"])
    def test_every_open_window_is_placed_exactly_once(self, remote):
        """test_열린_작업·미통과_게이트·브랜치가_전부_정확히_한_프레임에_들어간다"""
        backlog = _backlog()
        payload = _graph(backlog, **(_remote_kwargs() if remote else {}))
        expected = {f"t:{t.id}" for t in backlog.tasks.values() if t.status in OPEN_TASK_STATUSES}
        expected |= {f"g:{g.id}" for g in backlog.gates.values() if g.status == "pending"}
        if remote:
            expected |= {f"b:{name}" for name in EXPECTED_BRANCHES}
        assert set(payload["nodes"]) == expected

        placed = [key for frame in payload["frames"] for key in frame["keys"]]
        assert len(placed) == len(set(placed)), "한 창이 두 프레임에 들어갔다"
        assert set(placed) == set(payload["nodes"]), "프레임에 없는 창(또는 유령 키)이 있다"
        for frame in payload["frames"]:
            assert frame["size"] == len(frame["keys"])
            for key in frame["keys"]:
                assert payload["nodes"][key]["frame"] == frame["id"]

        assert payload["open_tasks"] == sum(1 for k in expected if k.startswith("t:"))
        assert payload["open_gates"] == sum(1 for k in expected if k.startswith("g:"))
        assert payload["branch_total"] == sum(1 for k in expected if k.startswith("b:"))
        assert payload["flow_node_total"] + payload["independent_total"] == len(expected)

    def test_finished_items_have_no_window(self):
        """test_done·cancelled_태스크와_cleared·waived_게이트는_창이_없다"""
        backlog = _backlog()
        nodes = _graph(backlog, **_remote_kwargs())["nodes"]
        for task in backlog.tasks.values():
            if task.status in TERMINAL_STATUSES:
                assert f"t:{task.id}" not in nodes
        for gate in backlog.gates.values():
            if gate.passed:
                assert f"g:{gate.id}" not in nodes
        # 픽스처 접촉 — 위 루프가 공허하지 않다
        assert {t.status for t in backlog.tasks.values()} >= {"done", "cancelled"}
        assert {g.status for g in backlog.gates.values()} >= {"cleared", "waived"}

    def test_counts_add_up_to_windows(self):
        """test_상태_집계의_합이_창_수와_같다"""
        payload = _graph(**_remote_kwargs())
        assert sum(payload["counts"].values()) == len(payload["nodes"])


# ── ② 간선 전수 ──────────────────────────────────────────────────────────────


class TestEdges:
    def _expected(self, backlog: Backlog, with_branches: bool) -> set[tuple[str, str, str]]:
        graph = store.dependency_graph(backlog)
        expected = {
            (work_graph.node_key(src), work_graph.node_key(dst), kind)
            for (src, dst), kind in graph.edge_kind.items()
            if work_graph.is_open(backlog, src) and work_graph.is_open(backlog, dst)
        }
        if with_branches:
            expected |= {
                ("b:claude/done-br", "t:S2-14-ready2", "done_on_branch"),
                ("b:claude/done-br", "t:S2-20-eps", "done_on_branch"),
                ("b:claude/other", "t:S2-13-ready", "claimed_on_branch"),
            }
        return expected

    @pytest.mark.parametrize("remote", [False, True], ids=["no-remote", "remote"])
    def test_every_open_edge_is_drawn_once(self, remote):
        """test_열린_노드끼리의_간선이_전부_한_번씩_그려진다"""
        backlog = _backlog()
        payload = _graph(backlog, **(_remote_kwargs() if remote else {}))
        expected = self._expected(backlog, remote)
        drawn = _drawn(payload)
        assert len(drawn) == len(set(drawn))
        assert set(drawn) == expected
        assert payload["edge_total"] == len(expected) == len(payload["edges"])

    def test_edge_kinds_come_from_the_ledger_graph(self):
        """test_간선_종류_4종이_대장_그래프_그대로다 (픽스처가_네_종류를_모두_밟는다)"""
        drawn = set(_drawn(_graph()))
        assert ("t:S1-10-alpha", "t:S2-10-gamma", "depends_on") in drawn
        assert ("t:S1-11-beta", "g:G-alpha", "gate_input") in drawn
        assert ("g:G-alpha", "t:S2-10-gamma", "requires_gates") in drawn
        assert ("g:G-e-axis", "t:E1-01-track", "entry_gate") in drawn

    def test_finished_predecessor_is_listed_but_not_drawn(self):
        """test_끝난_선행은_그리지_않고_상세에만_open_False로_남는다"""
        payload = _graph()
        nodes = payload["nodes"]
        beta = nodes["t:S1-11-beta"]
        done_link = _link(beta, "preds", "t:S1-12-done")
        assert done_link["open"] is False
        assert done_link["status"] == "done"
        assert done_link["edge"] == work_graph.EDGE_LABEL["depends_on"]
        assert _link(beta, "preds", "t:S1-10-alpha")["open"] is True  # 대조군
        solo = nodes["g:G-solo"]
        assert _link(solo, "preds", "t:S1-16-done")["open"] is False
        # 통과한 게이트 뒤의 태스크도 선행으로 그 게이트를 남긴다
        after = nodes["t:S2-18-after-cleared"]
        assert _link(after, "preds", "g:G-cleared")["open"] is False
        drawn_ends = {end for src, dst, _ in _drawn(payload) for end in (src, dst)}
        assert not drawn_ends & {"t:S1-12-done", "t:S1-16-done", "g:G-cleared"}

    def test_edges_stay_inside_one_flow_frame(self):
        """test_연결선은_양끝이_속한_흐름_프레임_안에_있다"""
        payload = _graph(**_remote_kwargs())
        frames = _frames_by_id(payload)
        for edge in payload["edges"]:
            frame = frames[edge["frame"]]
            assert frame["kind"] == "flow"
            assert edge["src"] in frame["keys"] and edge["dst"] in frame["keys"]


# ── ③ 결정성 ─────────────────────────────────────────────────────────────────


def _reinserted(backlog: Backlog, seed: int) -> Backlog:
    """같은 내용을 다른 삽입 순서로 — dict 순서에 기대는 판정이 있으면 좌표가 달라진다."""
    rng = random.Random(seed)
    source = copy.deepcopy(backlog)
    out = Backlog(stage_order=list(source.stage_order))
    for mapping_name in ("tracks", "gates", "tasks"):
        items = list(getattr(source, mapping_name).items())
        rng.shuffle(items)
        getattr(out, mapping_name).update(items)
    return out


def _shuffled_remote(seed: int) -> dict[str, object]:
    rng = random.Random(seed)
    kwargs = _remote_kwargs()
    for name in ("remote_done", "remote_claimed"):
        items = list(kwargs[name].items())  # type: ignore[attr-defined]
        rng.shuffle(items)
        kwargs[name] = dict(items)
    stale = list(kwargs["stale_branches"])  # type: ignore[call-overload]
    rng.shuffle(stale)
    kwargs["stale_branches"] = stale
    return kwargs


class TestDeterminism:
    @pytest.mark.parametrize("factory", [_backlog, _big_backlog, _cyclic_backlog])
    def test_same_input_gives_identical_payload(self, factory):
        """test_같은_입력이면_좌표·프레임·연결선이_완전히_같다"""
        first = json.dumps(_graph(factory(), **_remote_kwargs()), ensure_ascii=False)
        second = json.dumps(_graph(factory(), **_remote_kwargs()), ensure_ascii=False)
        assert first == second

    @pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
    @pytest.mark.parametrize("factory", [_backlog, _big_backlog])
    def test_insertion_order_does_not_move_anything(self, factory, seed):
        """test_태스크·게이트·원격_입력의_삽입_순서가_좌표를_바꾸지_않는다"""
        baseline = json.dumps(_graph(factory(), **_remote_kwargs()), ensure_ascii=False)
        shuffled = json.dumps(
            _graph(_reinserted(factory(), seed), **_shuffled_remote(seed)), ensure_ascii=False
        )
        assert shuffled == baseline

    def test_hash_seed_does_not_move_anything(self):
        """test_해시_시드가_달라도_같은_페이로드다 (집합 순회 순서에 기대는_배치_금지)"""
        harness_dir = Path(work_graph.__file__).resolve().parent
        tests_dir = Path(__file__).resolve().parent
        script = (
            "import json, sys\n"
            f"sys.path[:0] = [{str(harness_dir)!r}, {str(tests_dir)!r}]\n"
            "import test_work_graph as t\n"
            "import work_graph\n"
            "out = [work_graph.build_graph(f(), [], t.TODAY, **t._remote_kwargs())\n"
            "       for f in (t._backlog, t._big_backlog, t._cyclic_backlog)]\n"
            "print(json.dumps(out, ensure_ascii=False))\n"
        )
        outputs = []
        for seed in ("1", "2", "3"):
            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                encoding="utf-8",
                env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONIOENCODING": "utf-8"},
                timeout=120,
            )
            assert result.returncode == 0, result.stderr
            outputs.append(result.stdout)
        # 빈 출력끼리의 일치는 공허하다 — 세 페이로드가 실제로 실렸는지 먼저 본다
        parsed = json.loads(outputs[0])
        assert len(parsed) == 3 and all(p["nodes"] and p["edges"] for p in parsed)
        assert outputs[0] == outputs[1] == outputs[2]


# ── ④ 배치 기하 ──────────────────────────────────────────────────────────────


def _overlaps(a: dict, b: dict) -> bool:
    return (
        a["x"] < b["x"] + b["w"]
        and b["x"] < a["x"] + a["w"]
        and a["y"] < b["y"] + b["h"]
        and b["y"] < a["y"] + a["h"]
    )


_GEOMETRY_CASES: dict[str, Callable[[], dict]] = {
    "small-remote": lambda: _graph(**_remote_kwargs()),
    "small": lambda: _graph(),
    "big": lambda: _graph(_big_backlog()),
    "cycles": lambda: _graph(_cyclic_backlog()),
}


@pytest.fixture(params=sorted(_GEOMETRY_CASES))
def geometry_payload(request) -> dict:
    return _GEOMETRY_CASES[request.param]()


class TestGeometry:
    def test_no_two_windows_overlap(self, geometry_payload):
        """test_어떤_두_창도_겹치지_않는다 (전_창_쌍_검사)"""
        nodes = list(geometry_payload["nodes"].values())
        clashes = [
            (a["key"], b["key"]) for a, b in itertools.combinations(nodes, 2) if _overlaps(a, b)
        ]
        assert clashes == []

    def test_windows_sit_inside_their_frame_below_the_title_band(self, geometry_payload):
        """test_창은_자기_프레임의_여백·제목띠_안쪽에_있다"""
        frames = _frames_by_id(geometry_payload)
        pad, head = work_graph.FRAME_PAD, work_graph.FRAME_HEAD
        for node in geometry_payload["nodes"].values():
            frame = frames[node["frame"]]
            assert node["x"] >= frame["x"] + pad, node["key"]
            assert node["y"] >= frame["y"] + head, node["key"]
            assert node["x"] + node["w"] <= frame["x"] + frame["w"] - pad, node["key"]
            assert node["y"] + node["h"] <= frame["y"] + frame["h"] - pad, node["key"]

    def test_frames_never_overlap(self, geometry_payload):
        """test_프레임끼리_겹치지_않는다"""
        frames = geometry_payload["frames"]
        clashes = [
            (a["id"], b["id"]) for a, b in itertools.combinations(frames, 2) if _overlaps(a, b)
        ]
        assert clashes == []

    def test_forward_edges_run_left_to_right_port_to_port(self, geometry_payload):
        """test_순환이_아닌_연결선은_출력포트에서_입력포트로_왼→오_방향이다"""
        nodes = geometry_payload["nodes"]
        forward = [e for e in geometry_payload["edges"] if not e["back"]]
        assert forward, "검사할 연결선이 없다 — 픽스처가 이 절을 밟지 않는다"
        for edge in forward:
            points = edge["points"]
            src, dst = nodes[edge["src"]], nodes[edge["dst"]]
            assert len(points) >= 2 and len(points) % 2 == 0, edge
            assert points[0] == [src["x"] + src["w"], src["y"] + src["h"] // 2], edge
            assert points[-1] == [dst["x"], dst["y"] + dst["h"] // 2], edge
            assert points[0][0] < points[-1][0], edge
            xs = [p[0] for p in points]
            assert xs == sorted(xs), f"연결선이 되돌아간다: {edge}"

    def test_edge_points_stay_inside_their_frame(self, geometry_payload):
        """test_연결선의_모든_점이_자기_프레임_안에_있다"""
        frames = _frames_by_id(geometry_payload)
        for edge in geometry_payload["edges"]:
            frame = frames[edge["frame"]]
            for x, y in edge["points"]:
                assert frame["x"] <= x <= frame["x"] + frame["w"], edge
                assert frame["y"] <= y <= frame["y"] + frame["h"], edge

    def test_canvas_contains_every_frame(self, geometry_payload):
        """test_캔버스가_모든_프레임을_담는다"""
        canvas = geometry_payload["canvas"]
        assert canvas["w"] >= work_graph.CANVAS_MIN_W
        for frame in geometry_payload["frames"]:
            assert frame["x"] >= 0 and frame["y"] >= 0
            assert frame["x"] + frame["w"] <= canvas["w"], frame["id"]
            assert frame["y"] + frame["h"] <= canvas["h"], frame["id"]
        assert canvas["h"] == max(f["y"] + f["h"] for f in geometry_payload["frames"])

    def test_flow_frames_come_before_group_frames(self, geometry_payload):
        """test_흐름_구역이_연결_없는_작업_구역보다_위에_있다"""
        flows = [f for f in geometry_payload["frames"] if f["kind"] == "flow"]
        groups = [f for f in geometry_payload["frames"] if f["kind"] == "group"]
        if flows and groups:
            bottom = max(f["y"] + f["h"] for f in flows)
            assert min(g["y"] for g in groups) >= bottom + work_graph.SECTION_GAP


class TestFixtureContact:
    """기하 계약의 각 절을 픽스처가 실제로 밟는지 — 밟지 않으면 위 검사는 공허하게 통과한다."""

    def test_small_fixture_routes_an_edge_through_dummies(self):
        """test_작은_픽스처는_3층을_건너는_연결선을_빈_자리_2개로_지나간다"""
        payload = _graph()
        edge = next(
            e
            for e in payload["edges"]
            if (e["src"], e["dst"]) == ("t:S1-10-alpha", "t:S2-10-gamma")
        )
        assert len(edge["points"]) == 6  # 출력 포트 + (입구·출구) × 2 + 입력 포트

    def test_small_fixture_stacks_windows_in_one_layer(self):
        """test_작은_픽스처는_한_층에_창_3개를_세로로_쌓는다"""
        nodes = _graph()["nodes"]
        xs = [nodes[k]["x"] for k in ("t:S1-11-beta", "t:S2-19-delta", "t:S2-20-eps")]
        assert len(set(xs)) == 1

    def test_big_fixture_wraps_shelves_and_grids(self):
        """test_큰_픽스처는_프레임_선반이_여러_줄이고_그룹_격자가_2줄_이상이다"""
        payload = _graph(_big_backlog())
        flow_rows = {f["y"] for f in payload["frames"] if f["kind"] == "flow"}
        assert len(flow_rows) >= 2
        ready = _frames_by_id(payload)["group-ready"]
        rows = {payload["nodes"][k]["y"] for k in ready["keys"]}
        assert len(rows) >= 2


# ── ⑤ 판정 무복제 ────────────────────────────────────────────────────────────


def _expected_state(backlog: Backlog, task: Task) -> tuple[str, str, str]:
    column, reason, detail = board.classify(backlog, task)
    if task.status == "review":
        return "review", reason, detail
    if column == "waiting" and reason == board.WAIT_LABEL["owner"]:
        return "human", reason, detail
    return column, reason, detail


class TestJudgmentIsNotDuplicated:
    def test_task_state_follows_board_classify(self):
        """test_작업_창_상태·사유는_board.classify(=selector)_판정_그대로다"""
        backlog = _backlog()
        nodes = _graph(backlog)["nodes"]
        seen_states = set()
        for key, item in nodes.items():
            if item["kind"] != "task":
                continue
            task = backlog.tasks[item["id"]]
            state, reason, detail = _expected_state(backlog, task)
            assert (item["state"], item["reason"], item["detail"]) == (state, reason, detail), key
            if task.status == "todo":
                ready = selector.classify_todo(backlog, task) is None
                assert ready == (item["state"] == "ready"), key
            seen_states.add(item["state"])
        # 픽스처 접촉 — 모든 상태 갈래를 밟는다
        assert seen_states == {"ready", "waiting", "blocked", "in_progress", "review", "human"}

    def test_human_owned_task_is_named_with_its_owner(self):
        """test_사람_소유_태스크는_human_상태와_소유자_라벨을_갖는다"""
        nodes = _graph()["nodes"]
        human = nodes["t:S2-12-human"]
        assert human["state"] == "human"
        assert human["label"] == f"{work_graph.STATE_LABEL['human']} · kiki"
        assert human["cmd"] == ""  # 에이전트 착수 명령을 내밀지 않는다

    def test_remote_claim_moves_ready_task_to_waiting(self):
        """test_원격_claim된_시작_가능_태스크는_대기(원격_claim)로_옮겨진다"""
        backlog = _backlog()
        claimed = {"S2-13-ready": "claude/other", "S2-11-keyed": "claude/other2"}
        baseline = _graph(backlog)["nodes"]
        assert baseline["t:S2-13-ready"]["state"] == "ready"  # 대조군
        payload = _graph(backlog, remote_claimed=claimed, remote_claim_status="ok")
        item = payload["nodes"]["t:S2-13-ready"]
        exclusion = selector.classify_todo(
            backlog, backlog.tasks["S2-13-ready"], remote_claimed=claimed
        )
        assert exclusion is not None and exclusion.reason == "claimed_remote"
        assert item["state"] == "waiting"
        assert item["reason"] == board.WAIT_LABEL["claimed_remote"]
        assert item["detail"] == ", ".join(exclusion.detail) == "claude/other"
        assert item["cmd"] == ""
        assert "t:S2-13-ready" not in payload["ready_order"]
        # 원래 시작 가능이 아니던 태스크의 사유는 바꾸지 않는다(선행 사유가 먼저다)
        keyed = payload["nodes"]["t:S2-11-keyed"]
        assert keyed["reason"] == baseline["t:S2-11-keyed"]["reason"]

    def test_remote_done_matches_board_apply_remote_done(self):
        """test_미머지_완료분_사유는_board.apply_remote_done와_같다"""
        backlog = _backlog()
        remote_done = {
            "S2-14-ready2": ["claude/done-br"],
            "S2-15-human": ["claude/h1", "claude/h2"],
        }
        cards = board.build_tasks(backlog)
        board.apply_remote_done(cards, remote_done)
        by_id = {card.id: card for card in cards}
        nodes = _graph(backlog, remote_done=remote_done, remote_done_status="ok")["nodes"]
        for key, item in nodes.items():
            if item["kind"] != "task":
                continue
            card = by_id[item["id"]]
            assert (item["reason"], item["detail"]) == (card.reason, card.detail), key
        moved = nodes["t:S2-14-ready2"]
        assert moved["state"] == "waiting"
        assert moved["reason"] == board.WAIT_LABEL["done_elsewhere"]
        assert moved["detail"] == "claude/done-br"
        assert nodes["t:S2-15-human"]["reason"] == board.WAIT_LABEL["done_elsewhere"]

    def test_ready_order_follows_next_sort(self):
        """test_시작_가능_순서는_selector.sort_key(next_정렬)다"""
        backlog = _backlog()
        payload = _graph(backlog)
        counts = selector.unblock_counts(backlog)
        ready = [
            t
            for t in backlog.tasks.values()
            if t.status == "todo" and selector.classify_todo(backlog, t) is None
        ]
        ready.sort(key=lambda t: selector.sort_key(backlog, t, counts))
        assert payload["ready_order"] == [f"t:{t.id}" for t in ready]
        assert payload["ready_order"][0] == "t:S1-10-alpha"
        assert payload["nodes"]["t:S1-10-alpha"]["unlocks"] == counts["S1-10-alpha"]
        assert payload["nodes"]["t:S1-10-alpha"]["cmd"].endswith("backlog.py start S1-10-alpha")


# ── ⑥ 브랜치 창 ──────────────────────────────────────────────────────────────


class TestBranchWindows:
    def test_branch_windows_carry_scan_results(self):
        """test_브랜치_창은_세_스캔_결과를_브랜치명으로_합쳐_싣는다"""
        nodes = _graph(**_remote_kwargs())["nodes"]
        other = nodes["b:claude/other"]
        assert other["state"] == "branch"
        assert other["claimed_tasks"] == ["S2-13-ready"]
        assert other["done_tasks"] == [] and other["foreign_tasks"] == []
        assert other["verdict"] == "pr_filed"
        assert other["reason"] == work_graph.BRANCH_LABEL["pr_filed"]
        assert other["detail"] == "PR #12"
        assert other["ahead"] == 4 and other["age_days"] == 12.5
        assert other["last_commit_at"] == "2026-09-15T03:00:00+00:00"
        assert other["short"] == "other"

        done_br = nodes["b:claude/done-br"]
        assert done_br["done_tasks"] == ["S2-14-ready2", "S2-20-eps"]  # 태스크 ID 순
        assert done_br["verdict"] == "unscanned"
        assert done_br["reason"] == work_graph.BRANCH_LABEL["unscanned"]
        assert done_br["ahead"] is None and done_br["last_commit_at"] == ""

        assert nodes["b:claude/foreign"]["foreign_tasks"] == ["ZZ-99-foreign"]
        assert nodes["b:claude/foreign"]["verdict"] == "unscanned"
        assert nodes["b:claude/stale-only"]["verdict"] == "isolated"
        for item in (other, done_br):
            assert item["cmd"].startswith("git fetch origin ")
            assert "push" not in item["cmd"] and "merge" not in item["cmd"]

    def test_branch_is_drawn_as_predecessor_of_its_task(self):
        """test_브랜치_창은_들고_있는_태스크_창의_선행으로_이어진다"""
        payload = _graph(**_remote_kwargs())
        drawn = set(_drawn(payload))
        assert ("b:claude/done-br", "t:S2-14-ready2", "done_on_branch") in drawn
        assert ("b:claude/other", "t:S2-13-ready", "claimed_on_branch") in drawn
        nodes = payload["nodes"]
        task = nodes["t:S2-13-ready"]
        link = _link(task, "preds", "b:claude/other")
        assert link["open"] is True
        assert link["edge"] == work_graph.EDGE_LABEL["claimed_on_branch"]
        assert _link(nodes["b:claude/other"], "succs", "t:S2-13-ready")["open"] is True
        assert nodes["b:claude/other"]["x"] < task["x"]
        assert nodes["b:claude/other"]["frame"] == task["frame"]
        assert task["frame"].startswith("flow-")

    def test_branch_without_open_task_goes_to_branch_group(self):
        """test_태스크_연결_없는_브랜치(고립_스캔만·외부_claim)는_branch_그룹에_들어간다"""
        payload = _graph(**_remote_kwargs())
        group = _frames_by_id(payload)["group-branch"]
        assert group["group"] == "branch"
        assert set(group["keys"]) == {"b:claude/stale-only", "b:claude/foreign"}

    def test_finished_or_unknown_tasks_open_no_branch_window(self):
        """test_끝난_태스크의_완료분·대장에_없는_완료분·끝난_태스크의_claim은_창을_만들지_않는다"""
        nodes = _graph(**_remote_kwargs())["nodes"]
        for name in ("claude/old", "claude/ghost", "claude/closed"):
            assert f"b:{name}" not in nodes

    def test_collect_branches_merges_by_name(self):
        """test_collect_branches는_세_스캔을_브랜치명으로_합친다"""
        kwargs = _remote_kwargs()
        works = work_graph.collect_branches(
            _backlog(),
            kwargs["remote_done"],  # type: ignore[arg-type]
            kwargs["remote_claimed"],  # type: ignore[arg-type]
            kwargs["stale_branches"],  # type: ignore[arg-type]
        )
        assert set(works) == EXPECTED_BRANCHES
        assert works["claude/other"].stale is not None
        assert works["claude/other"].stale.status == "pr_filed"
        assert works["claude/done-br"].stale is None


# ── ⑦ 게이트 창 ──────────────────────────────────────────────────────────────


class TestGateWindows:
    def test_gate_with_open_input_waits(self):
        """test_열린_입력이_있는_게이트는_gate_wait다"""
        gate = _graph()["nodes"]["g:G-alpha"]
        assert gate["state"] == "gate_wait"
        assert gate["label"] == work_graph.STATE_LABEL["gate_wait"]

    def test_gate_without_open_input_is_the_humans_turn(self):
        """test_열린_입력이_없는_게이트는_gate_turn이다 (끝난_입력만_있어도)"""
        nodes = _graph()["nodes"]
        for gid in ("G-key", "G-e-axis", "G-solo"):
            assert nodes[f"g:{gid}"]["state"] == "gate_turn", gid
        # G-solo는 입력이 *있지만* 끝났다 — "선행 존재"가 아니라 "열린 선행"으로 판정해야 한다
        assert nodes["g:G-solo"]["preds"]

    def test_gate_turns_when_its_input_finishes(self):
        """test_입력_태스크가_끝나면_gate_wait가_gate_turn으로_바뀐다"""
        backlog = _backlog()
        backlog.tasks["S1-11-beta"].status = "done"
        backlog.tasks["S1-11-beta"].artifacts = ["#20"]
        assert _graph(backlog)["nodes"]["g:G-alpha"]["state"] == "gate_turn"

    def test_clear_command_names_the_assignee(self):
        """test_clear_명령은_담당자를_--as로_싣고_claude면_생략한다 (HARN-60)"""
        nodes = _graph()["nodes"]
        assert "gates clear G-key --as kiki " in nodes["g:G-key"]["cmd"]
        assert "gates clear G-solo --as partner " in nodes["g:G-solo"]["cmd"]
        claude_cmd = nodes["g:G-e-axis"]["cmd"]
        assert "gates clear G-e-axis " in claude_cmd
        assert "--as" not in claude_cmd
        assert "--evidence" in claude_cmd

    def test_unconnected_gate_joins_the_human_group(self):
        """test_연결_없는_게이트는_사람_작업_그룹에_들어간다"""
        payload = _graph()
        human = _frames_by_id(payload)["group-human"]
        assert "g:G-solo" in human["keys"]
        assert "t:S2-15-human" in human["keys"]

    def test_gate_carries_elapsed_days_and_unlocks(self):
        """test_게이트_창은_경과일·해금_수를_싣는다"""
        nodes = _graph()["nodes"]
        key = nodes["g:G-key"]
        assert key["days"] == 48 and key["overdue"] is True
        # G-key가 풀리면 S2-11-keyed와 그 뒤 S2-12-human이 풀린다
        assert key["unlocks"] == 2


# ── ⑧ 판정 불가 표기 ─────────────────────────────────────────────────────────


class TestIndeterminate:
    def test_default_scan_status_is_skipped_not_ok(self):
        """test_원격_인자를_안_주면_ok가_아니라_skipped다"""
        payload = _graph()
        assert {name: scan["status"] for name, scan in payload["scans"].items()} == {
            "remote_done": "skipped",
            "remote_claim": "skipped",
            "stale_branches": "skipped",
        }
        text = work_graph.render_text(payload)
        assert text.count("판정 불가(skipped)") == 3

    def test_scan_status_is_carried_verbatim(self):
        """test_스캔_상태는_입력_그대로_실리고_ok가_아닌_것만_판정_불가로_표기된다"""
        kwargs = _remote_kwargs()
        kwargs.update(remote_claim_status="offline", stale_status="ok(PR 대조 미수행)")
        payload = _graph(**kwargs)
        scans = payload["scans"]
        assert scans["remote_done"] == {"status": "ok", "count": 4}
        assert scans["remote_claim"] == {"status": "offline", "count": 3}
        assert scans["stale_branches"] == {"status": "ok(PR 대조 미수행)", "count": 2}
        text = work_graph.render_text(payload)
        assert text.count("판정 불가") == 2
        assert "원격 claim 판정 불가(offline)" in text
        assert "고립 브랜치 판정 불가(ok(PR 대조 미수행))" in text
        assert "미머지 완료 판정 불가" not in text

    def test_all_ok_prints_no_indeterminate_line(self):
        """test_세_스캔이_모두_ok면_판정_불가_줄이_없다 (대조군)"""
        text = work_graph.render_text(_graph(**_remote_kwargs()))
        assert "판정 불가" not in text

    def test_text_summary_names_flows_and_turns(self):
        """test_터미널_요약은_흐름과_사람_차례를_말한다"""
        payload = _graph(**_remote_kwargs())
        text = work_graph.render_text(payload)
        assert f"이어진 흐름 {payload['flow_count']}개" in text
        assert "사람 차례: G-key" in text
        assert "미머지: claude/other" in text


# ── ⑨ 순환 내성 ──────────────────────────────────────────────────────────────


class TestCycleTolerance:
    def test_fixture_is_rejected_by_validate(self):
        """test_순환_픽스처는_validate가_거부하는_상태다 (그래프는_그래도_그려야_한다)"""
        errors = store.validate_backlog(_cyclic_backlog(), [])
        assert any("순환" in error for error in errors)

    def test_layout_flow_terminates_and_marks_the_closing_edge(self):
        """test_layout_flow는_순환에서도_끝나고_고리를_닫는_간선을_back으로_표시한다"""
        t = store.TASK_NODE
        nodes = [(t, "A"), (t, "B"), (t, "C"), (t, "D")]
        edges = [
            ((t, "A"), (t, "B"), "depends_on"),
            ((t, "B"), (t, "C"), "depends_on"),
            ((t, "C"), (t, "A"), "depends_on"),
            ((t, "C"), (t, "D"), "depends_on"),
        ]
        layout = _within_deadline(lambda: work_graph.layout_flow(nodes, edges))
        back = [e for e in layout.edges if e["back"]]
        assert len(back) == 1
        assert {back[0]["src"], back[0]["dst"]} <= {"t:A", "t:B", "t:C"}
        by_key = {work_graph.node_key(n): n for n in nodes}
        for edge in layout.edges:
            if not edge["back"]:
                src, dst = by_key[edge["src"]], by_key[edge["dst"]]
                assert layout.layers[src] < layout.layers[dst], edge
        assert set(layout.boxes) == set(nodes)

    def test_build_graph_survives_cycles(self):
        """test_build_graph는_순환_대장에서도_끝나고_간선을_하나도_잃지_않는다"""
        backlog = _cyclic_backlog()
        payload = _within_deadline(lambda: _graph(backlog))
        assert set(payload["nodes"]) == RING | GATE_LOOP | {"t:S1-04-after"}
        assert payload["edge_total"] == len(payload["edges"]) == 6
        back = [(e["src"], e["dst"]) for e in payload["edges"] if e["back"]]
        assert len(back) == 2
        assert sum(1 for src, dst in back if {src, dst} <= RING) == 1
        assert sum(1 for src, dst in back if {src, dst} <= GATE_LOOP) == 1

    def test_self_dependency_edge_is_not_lost(self):
        """test_자기_자신을_기다리는_태스크의_간선도_그려진다

        회귀: 자기 순환 태스크가 다른 연결이 없으면 창 1개짜리 성분으로 분류돼 흐름 배치를
        건너뛰었고, 그 간선이 edge_total에는 세지지만 edges에는 그려지지 않았다.
        """
        backlog = _cyclic_backlog()
        backlog.tasks["S1-06-self"] = _task("S1-06-self", "자기 고리", depends_on=["S1-06-self"])
        payload = _within_deadline(lambda: _graph(backlog))
        assert payload["edge_total"] == len(payload["edges"])
        self_edges = [
            e for e in payload["edges"] if e["src"] == e["dst"] == "t:S1-06-self"  # type: ignore[index]
        ]
        assert len(self_edges) == 1 and self_edges[0]["back"] is True  # type: ignore[index]
        assert payload["nodes"]["t:S1-06-self"]["frame"].startswith("flow-")  # type: ignore[index]


# ── ⑩ 발췌 ───────────────────────────────────────────────────────────────────


class TestExcerpt:
    def test_first_two_acceptance_items_are_clipped(self):
        """test_완료_조건_앞_2개를_각_상한_이하로_말줄임한다"""
        lines = work_graph.excerpt_lines(["가" * 200, "둘째 조건", "셋째 조건"], "노트")
        assert len(lines) == work_graph.EXCERPT_ITEMS == 2
        assert lines[0] == "가" * (work_graph.EXCERPT_CHARS - 1) + "…"
        assert len(lines[0]) == work_graph.EXCERPT_CHARS
        assert lines[1] == "둘째 조건"

    def test_exact_limit_is_not_clipped(self):
        """test_상한과_같은_길이는_자르지_않는다"""
        text = "나" * work_graph.EXCERPT_CHARS
        assert work_graph.excerpt_lines([text], "") == [text]

    def test_blank_items_are_skipped_and_whitespace_folded(self):
        """test_빈_완료_조건은_건너뛰고_공백을_한_칸으로_접는다"""
        lines = work_graph.excerpt_lines(["   ", "첫\n  조건", "", "둘째"], "")
        assert lines == ["첫 조건", "둘째"]

    def test_falls_back_to_first_notes_paragraph(self):
        """test_완료_조건이_없으면_노트_첫_문단을_싣는다"""
        notes = "\n\n  \n\n첫 문단\n이어지는 줄\n\n둘째 문단"
        assert work_graph.excerpt_lines([], notes) == ["첫 문단 이어지는 줄"]
        long_notes = "다" * 500
        (line,) = work_graph.excerpt_lines([], long_notes)
        assert len(line) == work_graph.EXCERPT_CHARS * work_graph.EXCERPT_ITEMS
        assert line.endswith("…")

    def test_nothing_gives_no_lines(self):
        """test_완료_조건도_노트도_없으면_빈_목록이다"""
        assert work_graph.excerpt_lines([], "") == []
        assert work_graph.excerpt_lines(["  "], "\n\n") == []

    def test_window_excerpt_is_excerpt_lines(self):
        """test_창의_발췌는_excerpt_lines_결과_그대로다"""
        backlog = _backlog()
        nodes = _graph(backlog)["nodes"]
        with_acceptance = with_notes_only = 0
        for item in nodes.values():
            if item["kind"] == "task":
                task = backlog.tasks[item["id"]]
                assert item["excerpt"] == work_graph.excerpt_lines(task.acceptance, task.notes)
                with_acceptance += bool(task.acceptance)
                with_notes_only += bool(not task.acceptance and task.notes)
            elif item["kind"] == "gate":
                gate = backlog.gates[item["id"]]
                assert item["excerpt"] == work_graph.excerpt_lines([], gate.notes)
        assert with_acceptance and with_notes_only  # 픽스처 접촉 — 두 갈래를 모두 밟는다
        assert nodes["t:S1-10-alpha"]["excerpt"][1] == "둘째 조건 줄바꿈 포함"
        assert nodes["g:G-alpha"]["excerpt"] == ["알파 판정 런북 첫 문단"]


# ── ⑪ 렌더 ───────────────────────────────────────────────────────────────────


def _payload_blob(html: str) -> str:
    """브라우저처럼 **첫** </script>에서 자른 페이로드 조각."""
    start = html.index(PAYLOAD_MARKER) + len(PAYLOAD_MARKER)
    return html[start : html.index("</script>", start)]


class TestRenderPage:
    """실제 화면 템플릿(work_graph_page.html)으로 렌더 — 템플릿이 있어야 통과한다."""

    def test_html_embeds_parsable_payload(self):
        """test_HTML에_박힌_페이로드가_그대로_파싱된다"""
        payload = _graph(**_remote_kwargs())
        parsed = json.loads(_payload_blob(work_graph.render_html(payload)))
        assert parsed["edge_total"] == payload["edge_total"]
        assert set(parsed["nodes"]) == set(payload["nodes"])

    def test_payload_cannot_close_the_script_tag(self):
        """test_제목의_script_종료_태그가_주입되지_않는다"""
        backlog = _backlog()
        backlog.tasks["S1-13-run"].title = INJECTED
        blob = _payload_blob(work_graph.render_html(_graph(backlog)))
        assert "<" not in blob
        assert json.loads(blob)["nodes"]["t:S1-13-run"]["title"] == INJECTED

    def test_html_is_self_contained(self):
        """test_HTML은_외부_요청을_하지_않는다"""
        html = work_graph.render_html(_graph(**_remote_kwargs()))
        assert "http://" not in html and "https://" not in html

    def test_fragment_omits_document_shell(self):
        """test_조각_모드는_문서_껍데기를_생략한다"""
        fragment = work_graph.render_html(_graph(), fragment=True).lower()
        for tag in ("<!doctype", "<html", "<body"):
            assert tag not in fragment
        assert PAYLOAD_MARKER in fragment


_GOOD_TEMPLATE = (
    "<title>t</title><style>.x{}</style>\n<!--BODY-->\n"
    '<div id="app"></div>' + PAYLOAD_MARKER + "__PAYLOAD__</script>\n"
)


class TestTemplateContract:
    """템플릿 표식 계약 — 실제 템플릿과 무관하게 render_html의 조립 규칙만 검사한다."""

    def _use(self, monkeypatch, tmp_path, text: str) -> None:
        page = tmp_path / "page.html"
        page.write_text(text, encoding="utf-8")
        monkeypatch.setattr(work_graph, "PAGE_TEMPLATE", page)

    def test_well_formed_template_renders(self, monkeypatch, tmp_path):
        """test_표식이_각_1개인_템플릿은_렌더된다 (아래_거부_검사의_대조군)"""
        self._use(monkeypatch, tmp_path, _GOOD_TEMPLATE)
        backlog = _backlog()
        backlog.tasks["S1-13-run"].title = INJECTED
        payload = _graph(backlog)
        document = work_graph.render_html(payload)
        assert document.lower().startswith("<!doctype html>")
        assert "__PAYLOAD__" not in document and "<!--BODY-->" not in document
        blob = _payload_blob(document)
        assert "<" not in blob
        assert json.loads(blob) == json.loads(json.dumps(payload))
        fragment = work_graph.render_html(payload, fragment=True)
        assert fragment.startswith("<title>t</title>")
        for tag in ("<!doctype", "<html", "<body"):
            assert tag not in fragment.lower()
        assert fragment.split("</style>", 1)[1].strip() in document

    @pytest.mark.parametrize(
        "text",
        [
            _GOOD_TEMPLATE.replace("<!--BODY-->", ""),
            _GOOD_TEMPLATE.replace("<!--BODY-->", "<!--BODY--><!--BODY-->"),
            _GOOD_TEMPLATE.replace("__PAYLOAD__", ""),
            _GOOD_TEMPLATE.replace("__PAYLOAD__", "__PAYLOAD____PAYLOAD__"),
        ],
        ids=["body-missing", "body-twice", "payload-missing", "payload-twice"],
    )
    def test_malformed_markers_raise(self, monkeypatch, tmp_path, text):
        """test_표식이_없거나_2개면_ValueError다"""
        self._use(monkeypatch, tmp_path, text)
        with pytest.raises(ValueError):
            work_graph.render_html(_graph())


# ── ⑫ CLI ────────────────────────────────────────────────────────────────────


def _backlog_mtimes() -> dict[Path, int]:
    root = store.find_repo_root()
    return {
        path: path.stat().st_mtime_ns for path in (root / "backlog").rglob("*") if path.is_file()
    }


class TestCli:
    """CLI 3모드 — 모두 `--no-remote`(네트워크 0). 매 실행이 읽기 전용 계약도 함께 검사한다.

    실저장소 대장을 읽는 실행은 한 번에 수 초가 걸려, 읽기 전용 검사를 별도 실행으로 두지 않고
    모드 검사 자체에 싣는다(`_main_read_only`) — 세 모드 전부가 쓰기 0건을 증명한다.
    """

    def _main_read_only(self, argv: list[str], capsys) -> str:
        """main 실행 전후 backlog/ 아래 모든 파일의 mtime_ns가 같아야 한다 (읽기 전용 계약)."""
        before = _backlog_mtimes()
        assert before, "backlog/ 파일을 하나도 못 찾았다 — 이 검사가 공허하다"
        assert work_graph.main([*argv, "--no-remote"]) == 0
        out = capsys.readouterr().out
        assert _backlog_mtimes() == before, "그래프 생성이 백로그 파일을 건드렸다"
        return out

    def test_json_mode_prints_payload_with_skipped_scans(self, capsys):
        """test_json_모드는_페이로드를_내고_no_remote면_세_스캔이_전부_skipped다 (읽기_전용)"""
        printed = json.loads(self._main_read_only(["--json"], capsys))
        assert {scan["status"] for scan in printed["scans"].values()} == {"skipped"}
        backlog, _ = store.load_backlog(store.find_repo_root())
        open_tasks = sum(1 for t in backlog.tasks.values() if t.status in OPEN_TASK_STATUSES)
        assert printed["open_tasks"] == open_tasks
        assert printed["branch_total"] == 0
        placed = [key for frame in printed["frames"] for key in frame["keys"]]
        assert sorted(placed) == sorted(printed["nodes"])

    def test_text_mode_reports_indeterminate_scans(self, capsys):
        """test_text_모드는_no_remote의_판정_불가를_세_줄로_말한다 (읽기_전용)"""
        assert self._main_read_only(["--text"], capsys).count("판정 불가(skipped)") == 3

    def test_writes_html_file(self, tmp_path, capsys):
        """test_HTML_파일을_생성한다 (읽기_전용 — 쓰는_것은_--out_경로_하나뿐)"""
        out = tmp_path / "nested" / "graph.html"
        self._main_read_only(["--out", str(out)], capsys)
        assert out.exists()
        parsed = json.loads(_payload_blob(out.read_text(encoding="utf-8")))
        assert parsed["scans"]["remote_done"]["status"] == "skipped"


# ── ⑬ 보조 함수 ──────────────────────────────────────────────────────────────


class TestHelpers:
    @pytest.mark.parametrize(
        ("task_id", "expected"),
        [
            ("HARN-182-open-work-flow-graph", "HARN-182"),
            ("E1-90-earth-science-placement", "E1-90"),
            ("S1-01-x", "S1-01"),
            ("HARN-182", "HARN-182"),
            ("G-e-axis", "G-e-axis"),
            ("HARN-12x-slug", "HARN-12x-slug"),
            ("claude/branch-name", "claude/branch-name"),
        ],
    )
    def test_short_id(self, task_id, expected):
        """test_short_id는_접두-번호만_남기고_번호_없는_ID는_그대로_둔다"""
        assert work_graph.short_id(task_id) == expected

    def test_node_key_separates_kinds(self):
        """test_같은_ID라도_종류가_다르면_키가_다르다"""
        keys = {
            work_graph.node_key((kind, "X-01"))
            for kind in (store.TASK_NODE, store.GATE_NODE, work_graph.BRANCH_NODE)
        }
        assert keys == {"t:X-01", "g:X-01", "b:X-01"}

    def test_grid_size_properties(self):
        """test_격자는_열_상한_16·빈_줄_없음·가로가_세로_이상이다"""
        assert work_graph.grid_size(0) == (0, 0)
        assert work_graph.grid_size(1) == (1, 1)
        for count in range(1, 600):
            cols, rows = work_graph.grid_size(count)
            assert 1 <= cols <= min(work_graph.GROUP_MAX_COLS, count), count
            assert cols * rows >= count, count
            assert cols * (rows - 1) < count, f"빈 줄이 생긴다: {count}"
            if count <= work_graph.GROUP_MAX_COLS**2:
                assert cols >= rows, count
        assert work_graph.grid_size(1000)[0] == work_graph.GROUP_MAX_COLS

    def test_shelf_pack_wraps_in_order(self):
        """test_선반_배치는_순서를_지키고_폭을_넘으면_다음_줄로_간다"""
        gap = work_graph.FRAME_GAP
        placed = work_graph.shelf_pack([(100, 50), (100, 80), (40, 10), (100, 30)], 250, top=7)
        assert placed == [
            (0, 7),
            (0, 7 + 50 + gap),
            (100 + gap, 7 + 50 + gap),
            (0, 7 + 50 + gap + 80 + gap),
        ]

    def test_shelf_pack_never_exceeds_width_except_oversize_item(self):
        """test_선반_배치는_한_줄_첫_칸이_아니면_폭을_넘지_않는다"""
        rng = random.Random(7)
        sizes = [(rng.randint(50, 900), rng.randint(20, 400)) for _ in range(60)]
        sizes.insert(10, (3000, 100))  # 폭보다 넓은 항목 — 줄 첫 칸에 홀로 놓인다
        width = 2000
        placed = work_graph.shelf_pack(sizes, width)
        rows: dict[int, list[int]] = {}
        for index, ((x, y), (w, _h)) in enumerate(zip(placed, sizes, strict=True)):
            if x > 0:
                assert x + w <= width, index
            rows.setdefault(y, []).append(index)
        ys = [y for _x, y in placed]
        assert ys == sorted(ys), "순서가 바뀌었다"
        for members in rows.values():
            assert members == list(range(members[0], members[-1] + 1))
        oversize = sizes.index((3000, 100))
        assert placed[oversize][0] == 0
