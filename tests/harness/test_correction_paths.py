"""HARN-67 — 정정 경로 3축(depends 제거·gate 탈착·notes 치환) + 취소된 선행의 차단·가시화.

배경(2026-09-05 실측): EOS-94(오등재)를 cancel하자 EOS-96이 후보에서 **아무 경고 없이**
사라졌다 — selector는 cancelled 선행을 해소로 치지 않는데(done만 해소) amend에는 depends
*제거* 경로가 없어 정정이 불가능했고, EOS-96을 cancel해 EOS-97로 재등재해야 했다(번호 2개·
왕복 1회 소모). HARN-57(done 증적)·HARN-59(paths)에 이은 정정 경로 부재 3번째 사례.

이 파일이 계약으로 동결하는 것 (acceptance ①~⑥):
  ② 취소된 선행 = **결정 불가 → 차단 유지 + 가시 경고**. cancelled가 "불필요해서"인지 "잘못
     등재돼서"인지 기계는 모른다(모른다 ≠ 아니다). 차단은 유지하되 next(매번, stderr)·status·
     brief·validate·cancel 시점 5곳에서 보이게 한다. 조용한 차단만은 금지.
  ③ `amend --remove-depends <full-id>` — 없는 id는 exit 1 + 파일 바이트 동일 · 이벤트에
     removed_depends 기록 · 같은 호출의 --depends와 겹치면 exit 1.
  ⑤ `amend --remove-gate <G-id>` — 미부착은 exit 1 · gates.yaml 무변경(게이트 status 불변).
  ⑥ `amend --notes-replace 구문자 신문자` — 구문자는 정확히 1회(0회·2회+ 거부 + 파일 바이트
     동일) · 신문자 '' 허용 · 원문은 이벤트에만(notes에 OLD 원문이 남지 않음) · 치환은 사유
     append **전**의 notes에 적용.
  ④ 변별력 — 후보 판정은 반드시 `next --n 500 --json` **전건 모드**로 한다. 상위 N건 기본
     출력은 priority가 낮은 태스크에서 정상·뮤테이션 양쪽 모두 "후보에 없음"이라 변별력이
     0이다(EOS-62 선례). 뮤테이션 3종(next 경고 제거·deps_cancelled 분기 제거·count==1 검사
     제거)의 RED 실측은 태스크 보고에 남긴다.

`audit-deps`는 시드 저장소에서 실 대장용 `SOFT_DECLARED` 항목(시드에 없는 태스크) 때문에
**항상 exit 1**이라 그대로는 변별력이 없다 — notes 치환 테스트는 그 표를 비워(monkeypatch)
0 → 1 → 0 세 상태를 실측한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import dep_declaration
import pytest
import selector
import store
from models import Backlog, Gate, Task, Track

import backlog as cli


@pytest.fixture
def seeded_repo(git_repo: Path, monkeypatch) -> Path:
    monkeypatch.chdir(git_repo)
    assert cli.main(["seed"]) == 0
    return git_repo


def _add(task_id: str, *extra: str) -> int:
    return cli.main(
        [
            "add",
            "--eos-priority",
            "P2",
            "--id",
            task_id,
            "--title",
            "HARN-67 테스트 태스크",
            "--track",
            "math-completion",
            "--stage",
            "S1",
            *extra,
        ]
    )


def _add_with_legacy_notes(repo: Path, task_id: str, notes: str) -> None:
    """위반 어구가 든 notes를 가진 태스크를 *레거시 상태*로 만든다.

    왜 store로 쓰는가: HARN-71(#1026) 이후 `add --notes`는 위반 문장을 쓰기 전에 거부한다 —
    그래서 CLI로는 더 이상 이 상태를 만들 수 없다. 그런데 `--notes-replace`가 존재하는 이유가
    바로 그 가드 *이전*에 기록된 레거시 위반(실 대장에 실재했던 형태)이므로, 테스트는 그 상태를
    저장소 수준에서 주입한다. add는 정상 경로로 통과시켜 등재 자체는 CLI 규약을 따른다.
    """
    assert _add(task_id) == 0
    backlog, _ = store.load_backlog(repo)
    task = backlog.tasks[task_id]
    task.notes = notes
    store.save_task(repo, task)


def _task(repo: Path, task_id: str):
    backlog, _ = store.load_backlog(repo)
    return backlog.tasks[task_id]


def _task_bytes(repo: Path, task_id: str) -> bytes:
    return (repo / "backlog" / "tasks" / f"{task_id}.yaml").read_bytes()


def _events(repo: Path, action: str) -> list[dict]:
    """이벤트 대장(레거시 + 세션 샤드 — HARN-46)에서 action이 일치하는 기록만."""
    return [
        json.loads(line)
        for path in store.event_paths(repo)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("action") == action
    ]


def _next_all(capsys) -> tuple[list[str], str]:
    """`next --n 500 --json` **전건** 판정 — (후보 id 목록, 같은 실행의 stderr).

    stdout은 JSON이어야 한다(경고가 stdout을 오염하면 기계 소비자가 깨진다) — 파싱 자체가
    검사다. 직전 출력을 먼저 비워 stderr 판정이 이 실행에 한정되게 한다.
    """
    capsys.readouterr()
    assert cli.main(["next", "--n", "500", "--json"]) == 0
    captured = capsys.readouterr()
    return [item["id"] for item in json.loads(captured.out)], captured.err


def _seed_cancelled_pair(capsys) -> None:
    """A(todo) ← B(todo, depends_on=[A]) 등재 후 A를 cancel — 사고 재현의 공통 전제."""
    assert _add("T7-01-blocker") == 0
    assert _add("T7-02-dependent", "--depends", "T7-01-blocker") == 0
    capsys.readouterr()
    assert cli.main(["cancel", "T7-01-blocker", "--reason", "오등재"]) == 0


# ── ② 취소된 선행 — 차단 유지 + 가시 경고 ───────────────────────────────────


class TestCancelledDependencyStaysBlockedButVisible:
    """② 취소된 선행은 해소가 아니다. 그러나 조용해서도 안 된다 — 5곳에서 보인다."""

    def test_dependent_stays_out_of_candidates_before_and_after_cancel(self, seeded_repo, capsys):
        assert _add("T7-01-blocker") == 0
        assert _add("T7-02-dependent", "--depends", "T7-01-blocker") == 0
        ids, err = _next_all(capsys)
        assert "T7-01-blocker" in ids
        assert "T7-02-dependent" not in ids, "의존 미충족인데 후보에 있다"
        assert "취소된 선행" not in err, "취소 전에는 취소 경고가 없어야 한다(변별력)"

        capsys.readouterr()
        assert cli.main(["cancel", "T7-01-blocker", "--reason", "오등재"]) == 0
        ids, err = _next_all(capsys)
        assert "T7-02-dependent" not in ids, "취소된 선행이 해소로 취급됐다 — 결정 불가는 차단 유지"
        # 같은 실행의 경고 스트림 — 어느 태스크가 어느 취소 선행에 막혔는지 + 정정 명령
        assert "T7-02-dependent" in err and "취소된 선행" in err
        assert "--remove-depends T7-01-blocker" in err

    def test_next_warns_every_time_even_when_candidates_exist(self, seeded_repo, capsys):
        """후보 0건 여부와 무관하게 **매번** — 한 번만 내면 다음 세션은 못 본다."""
        _seed_cancelled_pair(capsys)
        for _ in range(2):
            ids, err = _next_all(capsys)
            assert ids, "시드에는 다른 후보가 있어야 이 테스트가 '후보 있음' 축을 본다"
            assert "T7-02-dependent" in err and "취소된 선행" in err

    def test_next_text_mode_also_warns(self, seeded_repo, capsys):
        _seed_cancelled_pair(capsys)
        capsys.readouterr()
        assert cli.main(["next", "--n", "500"]) == 0
        err = capsys.readouterr().err
        assert "후보 제외 T7-02-dependent" in err and "취소된 선행 T7-01-blocker" in err

    def test_cancel_prints_dependents_that_become_blocked(self, seeded_repo, capsys):
        assert _add("T7-01-blocker") == 0
        assert _add("T7-02-dependent", "--depends", "T7-01-blocker") == 0
        capsys.readouterr()
        assert cli.main(["cancel", "T7-01-blocker", "--reason", "오등재"]) == 0
        out = capsys.readouterr().out
        assert "취소" in out
        assert "1건이 차단된다" in out and "T7-02-dependent" in out
        assert "--remove-depends T7-01-blocker" in out
        # 취소 자체는 막지 않는다
        assert _task(seeded_repo, "T7-01-blocker").status == "cancelled"
        # 이벤트에도 남는다 — 화면은 휘발되지만 대장은 남는다
        cancels = [e for e in _events(seeded_repo, "cancel") if e["id"] == "T7-01-blocker"]
        assert cancels and cancels[0]["blocked_dependents"] == ["T7-02-dependent"]

    def test_cancel_without_dependents_does_not_warn(self, seeded_repo, capsys):
        """변별력 — 의존자가 없으면 경고도 없다(항상 경고하는 검사는 위장이다)."""
        assert _add("T7-03-lonely") == 0
        capsys.readouterr()
        assert cli.main(["cancel", "T7-03-lonely", "--reason", "불필요"]) == 0
        assert "차단된다" not in capsys.readouterr().out

    def test_status_and_brief_show_one_line_summary(self, seeded_repo, capsys):
        # 취소 전: 요약 줄이 없어야 한다(0건이면 아무것도 내지 않는다)
        assert _add("T7-01-blocker") == 0
        assert _add("T7-02-dependent", "--depends", "T7-01-blocker") == 0
        capsys.readouterr()
        assert cli.main(["status"]) == 0
        assert "취소된 선행에 차단된 태스크" not in capsys.readouterr().out
        assert cli.main(["brief", "--format", "hook"]) == 0
        assert "취소된 선행에 차단된 태스크" not in capsys.readouterr().out

        assert cli.main(["cancel", "T7-01-blocker", "--reason", "오등재"]) == 0
        capsys.readouterr()
        assert cli.main(["status"]) == 0
        out = capsys.readouterr().out
        assert "취소된 선행에 차단된 태스크 1건: T7-02-dependent(←T7-01-blocker)" in out
        # brief는 훅이 stderr를 버리므로(`2>/dev/null`) **stdout**에 있어야 실제로 보인다
        assert cli.main(["brief", "--format", "hook"]) == 0
        out = capsys.readouterr().out
        assert "취소된 선행에 차단된 태스크 1건: T7-02-dependent(←T7-01-blocker)" in out

    def test_status_json_exposes_the_same_fact(self, seeded_repo, capsys):
        _seed_cancelled_pair(capsys)
        capsys.readouterr()
        assert cli.main(["status", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["cancelled_dep_blocked"] == [
            {"id": "T7-02-dependent", "cancelled": ["T7-01-blocker"]}
        ]

    def test_validate_stays_green_but_warns(self, seeded_repo, capsys):
        """validate를 red로 만들지 않는다(CI 의미 불변) — 경고 줄로만, 있을 때만."""
        assert _add("T7-04-plain") == 0
        capsys.readouterr()
        assert cli.main(["validate"]) == 0
        assert "취소된 선행에 차단" not in capsys.readouterr().err
        _seed_cancelled_pair(capsys)
        capsys.readouterr()
        assert cli.main(["validate"]) == 0
        err = capsys.readouterr().err
        assert "취소된 선행에 차단된 태스크 1건" in err and "T7-02-dependent" in err

    def test_start_refuses_with_the_specific_reason(self, seeded_repo, capsys):
        """start도 같은 판정을 쓴다 — 'deps'가 아니라 'deps_cancelled'로 거부 사유가 보인다."""
        _seed_cancelled_pair(capsys)
        capsys.readouterr()
        assert cli.main(["start", "T7-02-dependent", "--no-remote"]) == 1
        assert "deps_cancelled" in capsys.readouterr().err


class TestSelectorCancelledDependencies:
    """② selector 단위 — classify_todo가 취소 선행을 일반 deps와 **구별**한다."""

    @staticmethod
    def _backlog(dep_status: str) -> Backlog:
        backlog = Backlog(stage_order=["S1"])
        backlog.tracks["main"] = Track(id="main", title="기본")
        backlog.tasks["S1-01-dep"] = Task(
            id="S1-01-dep",
            title="선행",
            track="main",
            stage="S1",
            updated="2026-09-07",
            status=dep_status,
            artifacts=["#1"] if dep_status == "done" else [],
        )
        backlog.tasks["S1-02-follow"] = Task(
            id="S1-02-follow",
            title="후속",
            track="main",
            stage="S1",
            updated="2026-09-07",
            depends_on=["S1-01-dep"],
        )
        return backlog

    def test_cancelled_dep_yields_deps_cancelled(self):
        backlog = self._backlog("cancelled")
        exc = selector.classify_todo(backlog, backlog.tasks["S1-02-follow"])
        assert exc is not None
        assert exc.reason == "deps_cancelled" and exc.detail == ["S1-01-dep"]
        assert selector.cancelled_dependencies(backlog, backlog.tasks["S1-02-follow"]) == [
            "S1-01-dep"
        ]

    def test_todo_dep_is_plain_deps_and_done_dep_is_clear(self):
        """변별력 — 취소가 아닌 미충족은 종전대로 'deps', done은 후보."""
        todo = self._backlog("todo")
        exc = selector.classify_todo(todo, todo.tasks["S1-02-follow"])
        assert exc is not None and exc.reason == "deps"
        done = self._backlog("done")
        assert selector.classify_todo(done, done.tasks["S1-02-follow"]) is None

    def test_unmet_dependencies_semantics_unchanged(self):
        """unmet_dependencies는 여전히 done만 해소로 친다 — cancelled도 미충족에 포함."""
        backlog = self._backlog("cancelled")
        assert selector.unmet_dependencies(backlog, backlog.tasks["S1-02-follow"]) == ["S1-01-dep"]

    def test_stall_reason_labels_cancelled_dependency(self):
        backlog = self._backlog("cancelled")
        _ready, excluded = selector.candidates(backlog)
        code, detail = selector.stall_reason(backlog, excluded)
        assert code == "blocked"
        assert "S1-02-follow (취소된 선행: S1-01-dep)" in detail

    def test_summary_helper_includes_human_owned_tasks(self):
        """요약은 owner 제외에 가려지지 않는다 — 결정이 필요한 태스크를 빠짐없이 보여 준다."""
        backlog = self._backlog("cancelled")
        backlog.tasks["S1-02-follow"].owner = "kiki"
        blocks = selector.cancelled_dependency_blocks(backlog)
        assert [(t.id, deps) for t, deps in blocks] == [("S1-02-follow", ["S1-01-dep"])]


# ── ③ amend --remove-depends ────────────────────────────────────────────────


class TestRemoveDepends:
    """③ 취소·오등재된 선행을 떼는 유일한 CLI 경로 — 차단이 영구가 아니게 만드는 정정."""

    def test_remove_restores_candidacy_and_records_event(self, seeded_repo, capsys):
        _seed_cancelled_pair(capsys)
        ids, _ = _next_all(capsys)
        assert "T7-02-dependent" not in ids
        capsys.readouterr()
        assert (
            cli.main(
                [
                    "amend",
                    "T7-02-dependent",
                    "--remove-depends",
                    "T7-01-blocker",
                    "--reason",
                    "오등재 선행 제거",  # 사유에 '선행'이 들어가는 가장 자연스러운 경우
                ]
            )
            == 0
        )
        out = capsys.readouterr().out
        assert "depends_on -T7-01-blocker" in out and "착수 가능 후보가 됐다" in out

        ids, err = _next_all(capsys)
        assert "T7-02-dependent" in ids, "제거가 장식이다 — 후보로 돌아오지 않았다"
        assert "T7-02-dependent" not in err, "제거했는데 취소 경고가 남아 있다"

        task = _task(seeded_repo, "T7-02-dependent")
        assert task.depends_on == []
        assert "[정정" in task.notes and "오등재 선행 제거" in task.notes
        assert "depends_on 제거 1건" in task.notes
        amends = [e for e in _events(seeded_repo, "amend") if e["id"] == "T7-02-dependent"]
        assert amends and amends[-1]["removed_depends"] == ["T7-01-blocker"]
        assert "depends_on -T7-01-blocker" in amends[-1]["changed"]

    def test_unknown_dependency_removal_rejected_without_writing(self, seeded_repo, capsys):
        _seed_cancelled_pair(capsys)
        before = _task_bytes(seeded_repo, "T7-02-dependent")
        events_before = len(_events(seeded_repo, "amend"))
        assert (
            cli.main(
                ["amend", "T7-02-dependent", "--remove-depends", "T7-99-nope", "--reason", "x"]
            )
            == 1
        )
        assert "depends_on에 없다" in capsys.readouterr().err
        assert _task_bytes(seeded_repo, "T7-02-dependent") == before, "거부인데 파일이 바뀌었다"
        assert len(_events(seeded_repo, "amend")) == events_before

    def test_attach_and_remove_same_id_in_one_call_rejected(self, seeded_repo, capsys):
        _seed_cancelled_pair(capsys)
        assert _add("T7-05-other") == 0
        before = _task_bytes(seeded_repo, "T7-02-dependent")
        assert (
            cli.main(
                [
                    "amend",
                    "T7-02-dependent",
                    "--depends",
                    "T7-05-other",
                    "--remove-depends",
                    "T7-05-other",
                    "--reason",
                    "x",
                ]
            )
            == 1
        )
        assert "부착하면서 제거할 수 없다" in capsys.readouterr().err
        assert _task_bytes(seeded_repo, "T7-02-dependent") == before

    def test_attach_and_remove_different_ids_in_one_call_allowed(self, seeded_repo, capsys):
        """양성 대조 — 겹치지 않으면 같은 호출에서 부착+제거가 함께 된다."""
        _seed_cancelled_pair(capsys)
        assert _add("T7-05-other") == 0
        assert (
            cli.main(
                [
                    "amend",
                    "T7-02-dependent",
                    "--depends",
                    "T7-05-other",
                    "--remove-depends",
                    "T7-01-blocker",
                    "--reason",
                    "선행 교체",
                ]
            )
            == 0
        )
        assert _task(seeded_repo, "T7-02-dependent").depends_on == ["T7-05-other"]

    def test_removal_that_orphans_a_notes_declaration_is_refused_with_hint(
        self, seeded_repo, capsys, monkeypatch
    ):
        """HARN-53 가드 적용 — notes에 '선행: X'가 남은 채 X를 떼면 미집행 선언이 된다.

        거부 메시지는 같은 호출의 --notes-replace를 안내하고, 그 조합은 통과해야 한다
        (고칠 수 없는 위반을 지적하는 게이트는 사람이 게이트를 끄게 만든다).
        """
        monkeypatch.setattr(dep_declaration, "SOFT_DECLARED", {})
        assert _add("T7-01-blocker") == 0
        assert (
            _add(
                "T7-02-dependent",
                "--depends",
                "T7-01-blocker",
                "--notes",
                "선행: T7-01 착지 후 착수",
            )
            == 0
        )
        assert cli.main(["cancel", "T7-01-blocker", "--reason", "오등재"]) == 0
        before = _task_bytes(seeded_repo, "T7-02-dependent")
        capsys.readouterr()
        assert (
            cli.main(
                [
                    "amend",
                    "T7-02-dependent",
                    "--remove-depends",
                    "T7-01-blocker",
                    "--reason",
                    "정정",
                ]
            )
            == 1
        )
        err = capsys.readouterr().err
        assert "새 의존 선언을 만든다" in err and "--notes-replace" in err
        assert _task_bytes(seeded_repo, "T7-02-dependent") == before

        assert (
            cli.main(
                [
                    "amend",
                    "T7-02-dependent",
                    "--remove-depends",
                    "T7-01-blocker",
                    "--notes-replace",
                    "선행: T7-01 착지 후 착수",
                    "T7-01은 취소됨 — 참고 기록",
                    "--reason",
                    "오등재 정정",
                ]
            )
            == 0
        )
        assert cli.main(["audit-deps"]) == 0
        ids, _ = _next_all(capsys)
        assert "T7-02-dependent" in ids


# ── ⑤ amend --remove-gate ───────────────────────────────────────────────────


class TestRemoveGate:
    """⑤ 오부착 게이트 탈착 — gates clear(통과)와 다른 일이며 게이트 status는 불변."""

    def _gated(self, capsys) -> None:
        assert _add("T7-10-gated") == 0
        assert cli.main(["gates", "add", "G-harn67-test", "--title", "테스트 게이트"]) == 0
        assert (
            cli.main(["amend", "T7-10-gated", "--gate", "G-harn67-test", "--reason", "부착"]) == 0
        )
        ids, _ = _next_all(capsys)
        assert "T7-10-gated" not in ids, "부착이 장식이다"

    def test_remove_gate_restores_candidacy_without_touching_gate(self, seeded_repo, capsys):
        self._gated(capsys)
        gates_before = (seeded_repo / "backlog" / "gates.yaml").read_bytes()
        assert (
            cli.main(
                [
                    "amend",
                    "T7-10-gated",
                    "--remove-gate",
                    "G-harn67-test",
                    "--reason",
                    "오부착 정정",
                ]
            )
            == 0
        )
        assert _task(seeded_repo, "T7-10-gated").requires_gates == []
        ids, _ = _next_all(capsys)
        assert "T7-10-gated" in ids
        # 게이트 자체는 그대로 — 탈착은 태스크 쪽 작업이다
        assert (seeded_repo / "backlog" / "gates.yaml").read_bytes() == gates_before
        backlog, _ = store.load_backlog(seeded_repo)
        assert backlog.gates["G-harn67-test"].status == "pending"
        amends = [e for e in _events(seeded_repo, "amend") if e["id"] == "T7-10-gated"]
        assert amends[-1]["removed_gates"] == ["G-harn67-test"]
        assert "requires_gates -G-harn67-test" in _task(seeded_repo, "T7-10-gated").notes

    def test_unattached_gate_removal_rejected_without_writing(self, seeded_repo, capsys):
        assert _add("T7-11-plain") == 0
        assert cli.main(["gates", "add", "G-harn67-test", "--title", "테스트 게이트"]) == 0
        before = _task_bytes(seeded_repo, "T7-11-plain")
        assert (
            cli.main(["amend", "T7-11-plain", "--remove-gate", "G-harn67-test", "--reason", "x"])
            == 1
        )
        assert "requires_gates에 없다" in capsys.readouterr().err
        assert _task_bytes(seeded_repo, "T7-11-plain") == before

    def test_attach_and_remove_same_gate_in_one_call_rejected(self, seeded_repo, capsys):
        self._gated(capsys)
        before = _task_bytes(seeded_repo, "T7-10-gated")
        assert (
            cli.main(
                [
                    "amend",
                    "T7-10-gated",
                    "--gate",
                    "G-harn67-test",
                    "--remove-gate",
                    "G-harn67-test",
                    "--reason",
                    "x",
                ]
            )
            == 1
        )
        assert "부착하면서 제거할 수 없다" in capsys.readouterr().err
        assert _task_bytes(seeded_repo, "T7-10-gated") == before


# ── ⑥ amend --notes-replace ─────────────────────────────────────────────────


class TestNotesReplace:
    """⑥ notes 치환 — audit-deps 위반을 CLI로 고칠 수 있게 한다(구문자 정확히 1회)."""

    @pytest.fixture(autouse=True)
    def _empty_soft_table(self, monkeypatch):
        # 시드 저장소에서 audit-deps가 변별력을 갖게 실 대장용 소프트 분류표를 비운다
        monkeypatch.setattr(dep_declaration, "SOFT_DECLARED", {})

    def test_replace_fixes_audit_deps_and_keeps_old_text_out_of_notes(self, seeded_repo, capsys):
        assert cli.main(["audit-deps"]) == 0, "전제: 시드는 green이어야 0→1→0 변별이 성립한다"
        assert _add("T7-20-ref-target") == 0
        _add_with_legacy_notes(seeded_repo, "T7-21-declarer", "선행: T7-20 착지 후 착수")
        assert cli.main(["audit-deps"]) == 1, "위반 주입이 적용되지 않았다(주입 자체의 실재)"

        old = "선행: T7-20 착지 후 착수"
        new = "T7-20의 산출물을 참고한다"
        assert (
            cli.main(
                [
                    "amend",
                    "T7-21-declarer",
                    "--notes-replace",
                    old,
                    new,
                    "--reason",
                    "의존 아님 — 참조로 정정",
                ]
            )
            == 0
        )
        assert cli.main(["audit-deps"]) == 0

        notes = _task(seeded_repo, "T7-21-declarer").notes
        assert old not in notes, "notes에 원문이 남으면 스캐너가 인용문을 다시 잡는다(되먹임)"
        assert new in notes
        assert "[정정" in notes and "notes 치환" in notes and "의존 아님 — 참조로 정정" in notes
        amends = [e for e in _events(seeded_repo, "amend") if e["id"] == "T7-21-declarer"]
        assert amends[-1]["notes_replace"] == {"old": old, "new": new}

    def test_zero_hits_rejected_without_writing(self, seeded_repo, capsys):
        assert _add("T7-22-notes", "--notes", "본문 그대로") == 0
        before = _task_bytes(seeded_repo, "T7-22-notes")
        assert (
            cli.main(["amend", "T7-22-notes", "--notes-replace", "없는 문장", "x", "--reason", "y"])
            == 1
        )
        assert "구문자가 notes에 없다" in capsys.readouterr().err
        assert _task_bytes(seeded_repo, "T7-22-notes") == before

    def test_two_hits_rejected_as_ambiguous_without_writing(self, seeded_repo, capsys):
        assert _add("T7-23-dup", "--notes", "AB 다음 AB") == 0
        before = _task_bytes(seeded_repo, "T7-23-dup")
        assert cli.main(["amend", "T7-23-dup", "--notes-replace", "AB", "x", "--reason", "y"]) == 1
        assert "2회 등장" in capsys.readouterr().err
        assert _task_bytes(seeded_repo, "T7-23-dup") == before

    def test_empty_old_rejected_but_empty_new_deletes_phrase(self, seeded_repo, capsys):
        assert _add("T7-24-del", "--notes", "앞 [지울 어구] 뒤") == 0
        before = _task_bytes(seeded_repo, "T7-24-del")
        assert cli.main(["amend", "T7-24-del", "--notes-replace", "", "x", "--reason", "y"]) == 1
        assert "비어 있다" in capsys.readouterr().err
        assert _task_bytes(seeded_repo, "T7-24-del") == before
        assert (
            cli.main(
                ["amend", "T7-24-del", "--notes-replace", "[지울 어구]", "", "--reason", "삭제"]
            )
            == 0
        )
        notes = _task(seeded_repo, "T7-24-del").notes
        assert "[지울 어구]" not in notes and notes.startswith("앞  뒤")

    def test_replacement_applies_before_reason_is_appended(self, seeded_repo, capsys):
        """순서 계약 — 사유가 구문자를 담고 있어도 그 사유는 치환되지 않는다.

        append 뒤에 치환했다면 구문자가 2회(본문+사유)가 되어 거부되거나 사유가 깨졌을 것이다.
        """
        assert _add("T7-25-order", "--notes", "본문: 원문 어구 끝") == 0
        assert (
            cli.main(
                [
                    "amend",
                    "T7-25-order",
                    "--notes-replace",
                    "원문 어구",
                    "새 어구",
                    "--reason",
                    "원문 어구를 고쳤다",
                ]
            )
            == 0
        )
        notes = _task(seeded_repo, "T7-25-order").notes
        assert "본문: 새 어구 끝" in notes
        assert "원문 어구를 고쳤다" in notes, "사유 문장이 치환에 휘말렸다"

    def test_replacement_creating_a_new_declaration_is_refused(self, seeded_repo, capsys):
        """HARN-53 가드가 치환에도 적용된다 — 신문자가 새 위반을 만들면 exit 1 + 파일 무변경."""
        assert _add("T7-20-ref-target") == 0
        assert _add("T7-26-clean", "--notes", "T7-20을 참고한다") == 0
        before = _task_bytes(seeded_repo, "T7-26-clean")
        assert (
            cli.main(
                [
                    "amend",
                    "T7-26-clean",
                    "--notes-replace",
                    "T7-20을 참고한다",
                    "선행: T7-20 착지 후 착수",
                    "--reason",
                    "y",
                ]
            )
            == 1
        )
        assert "새 의존 선언을 만든다" in capsys.readouterr().err
        assert _task_bytes(seeded_repo, "T7-26-clean") == before


# ── cancel 경고의 계상 범위 ────────────────────────────────────────────────


class TestCancelCountsInflightDependents:
    """cancel 경고는 todo만이 아니라 in_progress·review 의존자도 센다 — 종결(done/cancelled)은 제외."""

    def test_in_progress_and_review_dependents_are_counted(self, seeded_repo, capsys):
        assert _add("T7-30-root") == 0
        assert _add("T7-31-active") == 0
        assert cli.main(["start", "T7-31-active", "--no-remote"]) == 0
        assert cli.main(["amend", "T7-31-active", "--depends", "T7-30-root", "--reason", "x"]) == 0
        assert _add("T7-32-reviewing") == 0
        assert cli.main(["start", "T7-32-reviewing", "--no-remote"]) == 0
        assert cli.main(["review", "T7-32-reviewing"]) == 0
        assert (
            cli.main(["amend", "T7-32-reviewing", "--depends", "T7-30-root", "--reason", "x"]) == 0
        )
        # 종결 의존자 — 세지 않아야 한다(변별력)
        assert _add("T7-33-gone", "--depends", "T7-30-root") == 0
        assert cli.main(["cancel", "T7-33-gone", "--reason", "불필요"]) == 0

        capsys.readouterr()
        assert cli.main(["cancel", "T7-30-root", "--reason", "오등재"]) == 0
        out = capsys.readouterr().out
        assert "2건이 차단된다: T7-31-active, T7-32-reviewing" in out
        assert "T7-33-gone" not in out


# ── PR #1025 Codex 리뷰 P2 3건 — 회귀 동결 ─────────────────────────────────────


class TestCodexReview1025:
    """PR #1025 리뷰(chatgpt-codex-connector P2 ×3)가 잡은 구멍 3개를 계약으로 고정한다.

    셋 다 "보호 장치를 만들었는데 특정 경로에서 조용히 무력"한 형태다 — 초판에서 RED를 확인한
    뒤 수정했다(보호 장치 실패 주입 규칙 2026-09-01).
    """

    @pytest.fixture(autouse=True)
    def _empty_soft_table(self, monkeypatch):
        monkeypatch.setattr(dep_declaration, "SOFT_DECLARED", {})

    @staticmethod
    def _mixed_backlog() -> Backlog:
        """취소된 선행에 막힌 태스크 + pending 게이트를 기다리는 태스크가 **함께** 있는 대장."""
        backlog = Backlog(stage_order=["S1"])
        backlog.tracks["main"] = Track(id="main", title="기본")
        backlog.gates["G-x"] = Gate(id="G-x", title="사람 게이트")
        common = dict(track="main", stage="S1", updated="2026-09-07")
        backlog.tasks["S1-01-dep"] = Task(
            id="S1-01-dep", title="선행", status="cancelled", **common
        )
        backlog.tasks["S1-02-follow"] = Task(
            id="S1-02-follow", title="후속", depends_on=["S1-01-dep"], **common
        )
        backlog.tasks["S1-03-gated"] = Task(
            id="S1-03-gated", title="게이트 대기", requires_gates=["G-x"], **common
        )
        return backlog

    def test_mixed_stall_is_blocked_not_human_gate(self):
        """P2-1: 게이트를 전부 열어도 취소된 선행은 남는다 — 정지 사유가 human_gate면 거짓이다."""
        backlog = self._mixed_backlog()
        _ready, excluded = selector.candidates(backlog)
        code, detail = selector.stall_reason(backlog, excluded)
        assert code == "blocked", (code, detail)
        assert "S1-02-follow (취소된 선행: S1-01-dep)" in detail
        # 게이트 대기 태스크도 사유를 잃지 않는다 — human_gate를 포기한 대가로 게이트 ID가
        # 목록에서 사라지면 안 된다
        assert "S1-03-gated (게이트 대기: G-x)" in detail

    def test_pure_gate_stall_is_still_human_gate(self):
        """변별력 — 취소된 선행이 없으면 종전대로 human_gate."""
        backlog = self._mixed_backlog()
        backlog.tasks["S1-01-dep"].status = "todo"  # 취소 아님 → 일반 deps
        del backlog.tasks["S1-02-follow"]
        _ready, excluded = selector.candidates(backlog)
        code, detail = selector.stall_reason(backlog, excluded)
        assert (code, detail) == ("human_gate", ["G-x"])

    def test_next_warns_for_human_owned_task_with_cancelled_dep(self, seeded_repo, capsys):
        """P2-2: owner 제외가 먼저라 classify가 deps_cancelled를 못 내도 경고는 나와야 한다."""
        assert _add("T7-01-blocker") == 0
        assert _add("T7-02-dependent", "--depends", "T7-01-blocker", "--owner", "kiki") == 0
        capsys.readouterr()
        assert cli.main(["cancel", "T7-01-blocker", "--reason", "오등재"]) == 0
        ids, err = _next_all(capsys)
        assert "T7-02-dependent" not in ids
        assert "T7-02-dependent" in err and "취소된 선행 T7-01-blocker" in err

    def test_reason_recreating_the_replaced_declaration_is_refused(self, seeded_repo, capsys):
        """P2-3: 치환으로 없앤 선언을 --reason이 다시 만들면 amend는 성공이 아니다.

        종전에는 치환 *전* findings로 마스크해 '기존 위반'으로 오판 → exit 0인데 audit-deps는
        여전히 red — 대장은 손편집 금지라 정정 경로가 거짓 성공을 내면 갈 곳이 없다.
        """
        assert _add("T7-10-x") == 0
        _add_with_legacy_notes(seeded_repo, "T7-11-y", "선행: T7-10-x 착지 후 착수")
        assert cli.main(["audit-deps"]) == 1  # 위반 상태에서 시작한다(변별력)
        before = _task_bytes(seeded_repo, "T7-11-y")
        capsys.readouterr()
        rc = cli.main(
            [
                "amend",
                "T7-11-y",
                "--notes-replace",
                "선행: T7-10-x 착지 후 착수",
                "T7-10-x 참고",
                "--reason",
                "선행 T7-10-x 선언을 일반 참조로 정정",
            ]
        )
        err = capsys.readouterr().err
        assert rc == 1, "사유가 같은 선언을 재생성했는데 통과했다"
        assert "새 의존 선언을 만든다" in err
        assert _task_bytes(seeded_repo, "T7-11-y") == before  # 부분 쓰기 없음
        # 어구 없는 사유로는 통과하고 audit-deps가 green이 된다 — 정정 경로 자체는 살아 있다
        assert (
            cli.main(
                [
                    "amend",
                    "T7-11-y",
                    "--notes-replace",
                    "선행: T7-10-x 착지 후 착수",
                    "T7-10-x 참고",
                    "--reason",
                    "일반 참조로 정정",
                ]
            )
            == 0
        )
        assert cli.main(["audit-deps"]) == 0
