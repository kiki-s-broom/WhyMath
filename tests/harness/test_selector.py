"""selector.py — 순차 조율 알고리즘 테스트 (필터 6종·정렬 결정성·정지 사유)."""

from __future__ import annotations

import selector
from models import Backlog, Gate, Task, Track


def _backlog(
    tasks: list[Task],
    gates: list[Gate] | None = None,
    tracks: list[Track] | None = None,
    stage_order: list[str] | None = None,
) -> Backlog:
    backlog = Backlog(stage_order=stage_order or ["S1", "S2", "E1"])
    for track in tracks or [Track(id="main", title="기본 트랙")]:
        backlog.tracks[track.id] = track
    for gate in gates or []:
        backlog.gates[gate.id] = gate
    for task in tasks:
        backlog.tasks[task.id] = task
    return backlog


def _task(**overrides) -> Task:
    base = dict(id="S1-01-alpha", title="알파", track="main", stage="S1", updated="2026-07-08")
    base.update(overrides)
    return Task(**base)


class TestCandidateFilters:
    def test_unresolved_dependency_excludes_task(self):
        """test_의존성_미해소_제외"""
        backlog = _backlog(
            [
                _task(id="S1-01-alpha", depends_on=["S1-02-beta"]),
                _task(id="S1-02-beta", title="베타"),
            ]
        )
        ready, excluded = selector.candidates(backlog)
        assert [t.id for t in ready] == ["S1-02-beta"]
        assert excluded[0].reason == "deps"

    def test_dependency_done_includes_in_candidates(self):
        """test_의존성_done이면_후보_포함"""
        backlog = _backlog(
            [
                _task(id="S1-01-alpha", depends_on=["S1-02-beta"]),
                _task(id="S1-02-beta", title="베타", status="done", artifacts=["PR#1"]),
            ]
        )
        ready, _ = selector.candidates(backlog)
        assert [t.id for t in ready] == ["S1-01-alpha"]

    def test_pending_gate_excludes_task(self):
        """test_pending_게이트_제외"""
        backlog = _backlog(
            [_task(requires_gates=["G-key"])],
            gates=[Gate(id="G-key", title="키")],
        )
        ready, excluded = selector.candidates(backlog)
        assert ready == []
        assert excluded[0].reason == "gates"

    def test_waived_gate_passes(self):
        """test_waived_게이트는_통과"""
        backlog = _backlog(
            [_task(requires_gates=["G-key"])],
            gates=[Gate(id="G-key", title="키", status="waived")],
        )
        ready, _ = selector.candidates(backlog)
        assert len(ready) == 1

    def test_human_owned_task_excluded(self):
        """test_사람_소유_태스크_제외"""
        backlog = _backlog([_task(owner="kiki")])
        ready, excluded = selector.candidates(backlog)
        assert ready == []
        assert excluded[0].reason == "owner"

    def test_track_entry_gate_hard_locks(self):
        """test_트랙_entry_gate_하드락"""
        # E축 트랙은 S5 게이트 통과 전 후보에서 알고리즘 수준으로 제외
        backlog = _backlog(
            [_task(id="E1-01-physics", stage="E1", track="expansion", subject="physics")],
            gates=[Gate(id="G-s5", title="확장 게이트")],
            tracks=[Track(id="expansion", title="E축", entry_gate="G-s5")],
        )
        ready, excluded = selector.candidates(backlog)
        assert ready == []
        assert excluded[0].reason == "track_gate"

    def test_entry_gate_cleared_unlocks_track(self):
        """test_entry_gate_통과_후_해금"""
        backlog = _backlog(
            [_task(id="E1-01-physics", stage="E1", track="expansion", subject="physics")],
            gates=[Gate(id="G-s5", title="확장 게이트", status="cleared", evidence="판정 문서")],
            tracks=[Track(id="expansion", title="E축", entry_gate="G-s5")],
        )
        ready, _ = selector.candidates(backlog)
        assert [t.id for t in ready] == ["E1-01-physics"]

    def test_other_session_claim_excluded(self):
        """test_타_세션_claim_제외"""
        backlog = _backlog([_task(session="other-branch")])
        ready, excluded = selector.candidates(backlog)
        assert ready == []
        assert excluded[0].reason == "claimed"

    def test_layer_and_subject_filters(self):
        """test_layer_subject_필터"""
        backlog = _backlog(
            [
                _task(id="S1-01-alpha", layer="backend"),
                _task(id="S1-02-beta", title="베타", layer="mobile", subject="physics"),
            ]
        )
        ready, _ = selector.candidates(backlog, layer="mobile")
        assert [t.id for t in ready] == ["S1-02-beta"]
        ready, _ = selector.candidates(backlog, subject="physics")
        assert [t.id for t in ready] == ["S1-02-beta"]


class TestOrdering:
    def test_stage_takes_priority_over_priority_field(self):
        """test_스테이지가_우선순위보다_우선"""
        # S1 잔여(priority 5)가 S2(priority 1)보다 먼저
        backlog = _backlog(
            [
                _task(id="S2-01-later", stage="S2", priority=1),
                _task(id="S1-01-alpha", priority=5),
            ]
        )
        ready, _ = selector.candidates(backlog)
        assert [t.id for t in ready] == ["S1-01-alpha", "S2-01-later"]

    def test_same_stage_orders_by_priority(self):
        """test_같은_스테이지는_priority_우선"""
        backlog = _backlog(
            [
                _task(id="S1-02-beta", title="베타", priority=1),
                _task(id="S1-01-alpha", priority=3),
            ]
        )
        ready, _ = selector.candidates(backlog)
        assert [t.id for t in ready] == ["S1-02-beta", "S1-01-alpha"]

    def test_bottleneck_with_more_dependents_ordered_first(self):
        """test_해금_후속_수가_많은_병목_우선"""
        backlog = _backlog(
            [
                _task(id="S1-01-alpha", priority=2),
                _task(id="S1-02-bottleneck", title="병목", priority=2),
                _task(id="S1-03-child-a", title="a", depends_on=["S1-02-bottleneck"]),
                _task(id="S1-04-child-b", title="b", depends_on=["S1-02-bottleneck"]),
            ]
        )
        ready, _ = selector.candidates(backlog)
        assert ready[0].id == "S1-02-bottleneck"

    def test_ordering_is_deterministic(self):
        """test_정렬은_결정적"""
        tasks = [_task(id=f"S1-{i:02d}-t{i}", title=str(i)) for i in range(1, 6)]
        backlog = _backlog(tasks)
        first = [t.id for t in selector.candidates(backlog)[0]]
        second = [t.id for t in selector.candidates(backlog)[0]]
        assert first == second == sorted(first)


class TestStallReason:
    def test_all_tasks_done_reports_all_done(self):
        """test_전부_완료"""
        backlog = _backlog([_task(status="done", artifacts=["PR#1"])])
        _, excluded = selector.candidates(backlog)
        code, _ = selector.stall_reason(backlog, excluded)
        assert code == "all_done"

    def test_pending_human_gate_reports_human_gate(self):
        """test_사람_게이트_대기"""
        backlog = _backlog(
            [_task(requires_gates=["G-key"])],
            gates=[Gate(id="G-key", title="키")],
        )
        _, excluded = selector.candidates(backlog)
        code, detail = selector.stall_reason(backlog, excluded)
        assert code == "human_gate"
        assert detail == ["G-key"]

    def test_track_gate_classified_as_human_gate(self):
        """test_트랙_게이트도_사람_대기로_분류"""
        backlog = _backlog(
            [_task(id="E1-01-physics", stage="E1", track="expansion")],
            gates=[Gate(id="G-s5", title="확장 게이트")],
            tracks=[Track(id="expansion", title="E축", entry_gate="G-s5")],
        )
        _, excluded = selector.candidates(backlog)
        code, detail = selector.stall_reason(backlog, excluded)
        assert code == "human_gate"
        assert detail == ["G-s5"]

    def test_other_session_in_progress_reported(self):
        """test_다른_세션_진행_중"""
        backlog = _backlog(
            [
                _task(status="in_progress", session="other-branch"),
            ]
        )
        _, excluded = selector.candidates(backlog)
        code, detail = selector.stall_reason(backlog, excluded)
        assert code == "in_progress"
        assert "S1-01-alpha (other-branch)" in detail


class TestHumanOwnerPath:
    """HARN-06 — 사람-소유 태스크: 자동 후보 제외는 불변, 명시 기입 경로만 owner를 통과."""

    def test_owner_exclusion_default_invariant(self):
        """test_owner_제외_기본_불변

        candidates(자동 후보)는 owner!=claude를 계속 제외한다 — 자동 착수 방지."""
        backlog = _backlog([_task(owner="kiki")])
        ready, excluded = selector.candidates(backlog)
        assert ready == []
        assert excluded[0].reason == "owner"

    def test_allow_human_owner_passes_owner_only(self):
        """test_allow_human_owner는_owner만_통과

        allow_human_owner=True면 owner 제외를 건너뛰어 착수 가능(None)."""
        backlog = _backlog([_task(owner="kiki")])
        task = backlog.tasks["S1-01-alpha"]
        assert selector.classify_todo(backlog, task) is not None  # 기본은 제외
        assert selector.classify_todo(backlog, task, allow_human_owner=True) is None

    def test_allow_human_owner_still_checks_deps(self):
        """test_allow_human_owner도_deps는_검사

        사람 기입 경로도 의존성 미해소면 거부 — owner 외 검사는 우회 아님."""
        backlog = _backlog(
            [
                _task(owner="kiki", depends_on=["S1-02-beta"]),
                _task(id="S1-02-beta", title="베타"),
            ]
        )
        task = backlog.tasks["S1-01-alpha"]
        exclusion = selector.classify_todo(backlog, task, allow_human_owner=True)
        assert exclusion is not None and exclusion.reason == "deps"

    def test_allow_human_owner_still_checks_gates(self):
        """test_allow_human_owner도_게이트는_검사

        사람 기입 경로도 pending 게이트면 거부."""
        from models import Gate

        backlog = _backlog(
            [_task(owner="kiki", requires_gates=["G-key"])],
            gates=[Gate(id="G-key", title="키")],
        )
        task = backlog.tasks["S1-01-alpha"]
        exclusion = selector.classify_todo(backlog, task, allow_human_owner=True)
        assert exclusion is not None and exclusion.reason == "gates"


class TestEosPriorityOrdering:
    """EOS 등급이 착수 순서의 첫 키다 (HARN-77).

    변별력(acceptance ②): 아래 첫 테스트의 픽스처는 **stage·priority가 등급과 반대 방향**이라,
    `sort_key`에서 `eos_rank` 항을 빼면(종전 4튜플) 기대 순서가 뒤집혀 RED가 난다 — 필드만
    추가하고 순서가 그대로인 상태는 초록으로 통과하지 못한다. 실측(2026-09-28·착지 전 코드에
    같은 픽스처): `["S1-01-later-p2", "S2-01-must-p0"]` → 이 단언 실패.
    """

    def test_eos_grade_beats_stage_and_priority(self):
        """test_등급이_스테이지와_priority보다_우선 — S2·priority 5의 P0가 S1·priority 1의 P2보다 앞"""
        backlog = _backlog(
            [
                _task(id="S1-01-later-p2", stage="S1", priority=1, eos_priority="P2"),
                _task(id="S2-01-must-p0", stage="S2", priority=5, eos_priority="P0"),
            ]
        )
        ready, _ = selector.candidates(backlog, eos_hide=frozenset())
        assert [t.id for t in ready] == ["S2-01-must-p0", "S1-01-later-p2"]

    def test_within_same_grade_previous_order_holds(self):
        """test_같은_등급_안에서는_종전_순서 — stage → priority 그대로 (대조군)"""
        backlog = _backlog(
            [
                _task(id="S2-01-p1-early", stage="S2", priority=1, eos_priority="P1"),
                _task(id="S1-02-p1-low", stage="S1", priority=4, eos_priority="P1"),
                _task(id="S1-01-p1-high", stage="S1", priority=2, eos_priority="P1"),
            ]
        )
        ready, _ = selector.candidates(backlog)
        assert [t.id for t in ready] == ["S1-01-p1-high", "S1-02-p1-low", "S2-01-p1-early"]

    def test_unspecified_grade_sorts_last(self):
        """test_등급_미지정은_맨_뒤 — 모른다 ≠ 필수"""
        backlog = _backlog(
            [
                _task(id="S1-01-none", stage="S1", priority=1, eos_priority=None),
                _task(id="S1-02-p1", stage="S1", priority=5, eos_priority="P1"),
            ]
        )
        ready, _ = selector.candidates(backlog)
        assert [t.id for t in ready] == ["S1-02-p1", "S1-01-none"]
        assert selector.eos_rank(backlog.tasks["S1-01-none"]) == 4

    def test_eos_rank_mapping_matches_registered_grades(self):
        """test_등급_순위_매핑 — P0<P1<P2<P3<미지정, 예산 게이트가 쓰는 등급 문자열과 같은 집합"""
        from models import EOS_PRIORITIES

        ranks = [selector.eos_rank(_task(eos_priority=g)) for g in EOS_PRIORITIES]
        assert ranks == sorted(ranks) == [0, 1, 2, 3]
        assert set(selector.EOS_DEFERRED) < set(EOS_PRIORITIES)

    def test_rationale_shows_grade_first(self):
        """test_선정_사유에_등급이_첫_자리 (acceptance ⑤ — 순서만 바뀌고 근거가 안 보이면 무효)"""
        backlog = _backlog([_task(eos_priority="P0")])
        rationale = selector.selection_rationale(backlog, backlog.tasks["S1-01-alpha"])
        assert rationale.startswith("eos=P0 · ")
        backlog2 = _backlog([_task()])
        assert selector.selection_rationale(backlog2, backlog2.tasks["S1-01-alpha"]).startswith(
            "eos=미지정 · "
        )


class TestEosDeferredHidden:
    """이월 등급(P2·P3)은 후보에서 기본 숨김 — 착수 금지가 아니라 화면 규칙 (HARN-77 ④).

    blocked를 파킹으로 쓰던 우회(CUR-17·CUR-18)가 사라지는 조건은 "unblock해도 next 최상위로
    올라가지 않는다"이며, 그것은 정렬이 아니라 숨김이 보장한다.
    """

    def test_deferred_grades_hidden_by_default_with_reason(self):
        """test_이월_등급_기본_숨김 — 제외 사유 eos_deferred·detail에 등급"""
        backlog = _backlog(
            [
                _task(id="S1-01-p1", eos_priority="P1"),
                _task(id="S1-02-p2", eos_priority="P2"),
                _task(id="S1-03-p3", eos_priority="P3"),
            ]
        )
        ready, excluded = selector.candidates(backlog)
        assert [t.id for t in ready] == ["S1-01-p1"]
        hidden = selector.eos_hidden(excluded)
        assert [(e.task_id, e.detail) for e in hidden] == [
            ("S1-02-p2", ["P2"]),
            ("S1-03-p3", ["P3"]),
        ]
        assert "2건은 기본 숨김" in selector.eos_hidden_notice(excluded)

    def test_all_eos_shows_deferred_after_relevant(self):
        """test_전건_모드에서는_이월분이_뒤에_보인다 (대조군 — 숨김을 끄면 순서로만 뒤로 간다)"""
        backlog = _backlog(
            [
                _task(id="S1-01-p2", priority=1, eos_priority="P2"),
                _task(id="S1-02-p1", priority=5, eos_priority="P1"),
            ]
        )
        ready, excluded = selector.candidates(backlog, eos_hide=frozenset())
        assert [t.id for t in ready] == ["S1-02-p1", "S1-01-p2"]
        assert selector.eos_hidden(excluded) == []
        assert selector.eos_hidden_notice(excluded) == "※ 12월 검증 이월 등급(P2·P3) 숨김 0건"

    def test_other_exclusions_take_precedence_over_hiding(self):
        """test_게이트_대기가_숨김보다_먼저 — 이월 등급이라도 게이트 대기 경로 화면에는 남는다"""
        from models import Gate

        backlog = _backlog(
            [_task(id="S1-01-p2-gated", eos_priority="P2", requires_gates=["G-key"])],
            gates=[Gate(id="G-key", title="키")],
        )
        _ready, excluded = selector.candidates(backlog)
        assert [e.reason for e in excluded] == ["gates"]

    def test_stall_reason_is_eos_deferred_when_only_hidden_remain(self):
        """test_정지_사유_eos_deferred — 남은 착수 가능분이 전부 이월 등급이면 차단이 아니다"""
        backlog = _backlog([_task(id="S1-01-p2", eos_priority="P2")])
        ready, excluded = selector.candidates(backlog)
        assert ready == []
        code, detail = selector.stall_reason(backlog, excluded)
        assert code == "eos_deferred"
        assert detail == ["S1-01-p2 (P2)"]

    def test_stall_reason_prefers_gate_over_hidden(self):
        """test_게이트_정지가_숨김보다_우선 (대조군 — 사람 게이트가 있으면 그것이 정지 사유)"""
        from models import Gate

        backlog = _backlog(
            [
                _task(id="S1-01-p2", eos_priority="P2"),
                _task(id="S1-02-gated", eos_priority="P1", requires_gates=["G-key"]),
            ],
            gates=[Gate(id="G-key", title="키")],
        )
        ready, excluded = selector.candidates(backlog)
        assert ready == []
        code, _detail = selector.stall_reason(backlog, excluded)
        assert code != "eos_deferred"
