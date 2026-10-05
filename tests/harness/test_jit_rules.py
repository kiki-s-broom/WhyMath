"""HARN-121 ③ — 적시 규칙 주입의 계약 동결.

acceptance ③이 요구하는 변별력은 한 문장이다: **"대장에 경로 X의 사고를 넣고 X 편집
→ 주입 1건, Y 편집 → 0건."** 그 쌍이 이 파일의 중심이고, 나머지는 그 쌍이 *우연히*
성립하지 않도록 막는 것들이다.

특히 조심한 것 둘:
  · **침묵이 기본값이다.** 관련 없는 경로에 한 줄이라도 새면 곧 습관화되어 소음이
    되고(이 저장소의 `policy_warn` 89% 선례), 소음이 된 경고는 보호가 아니다.
  · **훅은 개발을 볼모로 잡지 않는다.** 인덱스가 깨져도 편집은 통과해야 한다 —
    다만 예외 타입명은 남긴다(침묵 실패 금지).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import jit_rules
import pytest
from _hook_stdin import set_hook_stdin

import backlog as cli

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class FakeTask:
    id: str
    paths: list[str] = field(default_factory=list)


@dataclass
class FakeBacklog:
    tasks: dict[str, FakeTask] = field(default_factory=dict)


@dataclass
class FakeRule:
    id: str
    title: str
    enforced_by: list[str] = field(default_factory=list)


@dataclass
class FakeIncident:
    date: str
    title: str
    fix_ref: str = ""
    damage_class: str = "none"


def _backlog(*tasks: FakeTask) -> FakeBacklog:
    return FakeBacklog(tasks={t.id: t for t in tasks})


# ── ① acceptance ③의 변별력 문면 그대로 ────────────────────────────────────


class TestAcceptanceDiscrimination:
    """경로 X의 사고를 넣고 X 편집 → 주입 1건, Y 편집 → 0건."""

    @staticmethod
    def _notes() -> list[jit_rules.Note]:
        backlog = _backlog(FakeTask(id="HARN-99-fix", paths=["src/x/**"]))
        incidents = [FakeIncident(date="2026-09-01", title="X에서 난 사고", fix_ref="HARN-99")]
        return jit_rules.build_notes(backlog, [], incidents)

    def test_editing_x_injects_one(self) -> None:
        matched = jit_rules.notes_for_path(self._notes(), "src/x/thing.py")
        assert len(matched) == 1
        assert matched[0].text == "X에서 난 사고"

    def test_editing_y_injects_zero(self) -> None:
        """대조군 — 이것이 0이 아니면 위 1건은 '전부 주입'이라 변별력이 없다."""
        assert jit_rules.notes_for_path(self._notes(), "src/y/thing.py") == []

    def test_zero_matches_render_to_silence(self) -> None:
        assert jit_rules.render_injection([], "src/y/thing.py") == ""


# ── ② 경로 해소 ─────────────────────────────────────────────────────────────


class TestPathResolution:
    def test_incident_resolves_through_its_remediation_task(self) -> None:
        backlog = _backlog(FakeTask(id="OPS-07-guard", paths=["scripts/a.py", "tests/b.py"]))
        notes = jit_rules.build_notes(
            backlog, [], [FakeIncident(date="2026-08-01", title="사고", fix_ref="OPS-07(가드)")]
        )
        assert notes[0].paths == ["scripts/a.py", "tests/b.py"]

    def test_rule_resolves_a_literal_path(self) -> None:
        notes = jit_rules.build_notes(
            _backlog(), [FakeRule(id="R-001", title="규칙", enforced_by=["tests/x.py::test_y"])], []
        )
        assert notes[0].paths == ["tests/x.py"]

    def test_rule_resolves_a_task_reference(self) -> None:
        backlog = _backlog(FakeTask(id="HARN-10-collision", paths=["scripts/harness/**"]))
        notes = jit_rules.build_notes(
            _backlog(*backlog.tasks.values()),
            [FakeRule(id="R-002", title="규칙", enforced_by=["HARN-10"])],
            [],
        )
        assert notes[0].paths == ["scripts/harness/**"]

    def test_unresolvable_entries_are_dropped_not_made_global(self) -> None:
        """경로를 모르는 항목을 빈 paths로 남기면 *모든* 편집에 뜬다 — 그것이 소음이다."""
        notes = jit_rules.build_notes(
            _backlog(),
            [FakeRule(id="R-003", title="경로 모름", enforced_by=[])],
            [FakeIncident(date="2026-01-01", title="경로 모름", fix_ref="")],
        )
        assert notes == []

    def test_unknown_task_reference_resolves_to_nothing(self) -> None:
        notes = jit_rules.build_notes(
            _backlog(), [], [FakeIncident(date="2026-01-01", title="사고", fix_ref="ZZZ-99")]
        )
        assert notes == []

    def test_a_note_with_empty_paths_never_matches(self) -> None:
        """`build_notes`를 우회해 들어온 빈 paths — 매칭 절의 **반례**.

        위 테스트들은 전부 `build_notes`를 거치는데 그 함수가 빈 paths를 이미 버리므로,
        매칭측의 `n.paths and ...` 가드는 한 번도 밟히지 않는다. 그 가드를 지워도
        초록이면 가드가 관대한 게 아니라 픽스처가 그 자리를 안 지나간 것이다
        (뮤테이션 J5 생존으로 발각 · CLAUDE.md 2026-09-07).

        손편집된 인덱스·구버전 스키마가 빈 paths를 실어 올 수 있고, 그것이 통과하면
        **모든 편집에 그 줄이 뜬다** — 이 모듈이 피하려는 소음 그 자체다.
        """
        leaked = jit_rules.Note(kind="rule", ref="R-999", paths=[], text="경로 없음")
        assert jit_rules.notes_for_path([leaked], "src/x/a.py") == []
        assert jit_rules.notes_for_path([leaked], "README.md") == []

    def test_an_empty_edit_path_matches_nothing_even_against_a_catch_all(self) -> None:
        """빈 경로 입력의 **반례** — 대조 대상이 `**`일 때만 이 절이 밟힌다.

        훅이 `file_path`를 못 읽으면 빈 문자열이 온다. 그때 `**`를 선언한 태스크가
        하나라도 있으면 전건이 매칭돼 아무 맥락도 없는 5줄이 뜬다(뮤테이션 J11).
        """
        catch_all = jit_rules.Note(kind="rule", ref="R-998", paths=["**"], text="전역")
        assert jit_rules.notes_for_path([catch_all], "src/x/a.py")  # 대조군: 정상 경로는 매칭
        assert jit_rules.notes_for_path([catch_all], "") == []


# ── ③ 순위와 상한 ───────────────────────────────────────────────────────────


class TestRankingAndCap:
    @staticmethod
    def _many(n: int) -> list[jit_rules.Note]:
        backlog = _backlog(FakeTask(id="HARN-99-fix", paths=["src/x/**"]))
        incidents = [
            FakeIncident(date=f"2026-09-{i + 1:02d}", title=f"사고{i}", fix_ref="HARN-99")
            for i in range(n)
        ]
        return jit_rules.build_notes(backlog, [], incidents)

    def test_injection_is_capped_at_five(self) -> None:
        assert len(jit_rules.notes_for_path(self._many(12), "src/x/a.py")) == jit_rules.MAX_NOTES

    def test_rules_outrank_incidents(self) -> None:
        """규칙은 일반화된 교훈이라 개별 사고보다 지면을 먼저 받는다."""
        backlog = _backlog(FakeTask(id="HARN-99-fix", paths=["src/x/**"]))
        notes = jit_rules.build_notes(
            backlog,
            [FakeRule(id="R-001", title="규칙", enforced_by=["HARN-99"])],
            [
                FakeIncident(
                    date="2026-09-01", title="사고", fix_ref="HARN-99", damage_class="data_loss"
                )
            ],
        )
        assert jit_rules.notes_for_path(notes, "src/x/a.py")[0].kind == "rule"

    def test_costlier_incidents_come_first(self) -> None:
        backlog = _backlog(FakeTask(id="HARN-99-fix", paths=["src/x/**"]))
        notes = jit_rules.build_notes(
            backlog,
            [],
            [
                FakeIncident(
                    date="2026-09-01", title="무해", fix_ref="HARN-99", damage_class="none"
                ),
                FakeIncident(
                    date="2026-09-02", title="소실", fix_ref="HARN-99", damage_class="data_loss"
                ),
            ],
        )
        assert jit_rules.notes_for_path(notes, "src/x/a.py")[0].text == "소실"

    def test_render_states_the_count_and_the_path(self) -> None:
        text = jit_rules.render_injection(
            jit_rules.notes_for_path(self._many(2), "src/x/a.py"), "src/x/a.py"
        )
        assert "src/x/a.py" in text and "2건" in text


# ── ④ 커밋 인덱스 없음 (HARN-130) ───────────────────────────────────────────


class TestNoCommittedIndex:
    """주입 후보는 편집 시 대장에서 계산한다 — 커밋 파생물이 다시 생기면 충돌·낡음이 돌아온다.

    커밋하던 시절의 두 사고: 사고를 등재한 PR끼리 `backlog/jit_index.json`에서 충돌했고
    (main에서 이 파일을 바꾼 커밋 26건 중 25건이 사고 대장도 바꿨다), 재생성을 잊으면 CI가
    red였다(HARN-179). 아래 둘이 그 파일의 귀환을 막는다.
    """

    def test_index_file_is_not_tracked(self) -> None:
        out = subprocess.run(
            ["git", "ls-files", "--", "backlog/jit_index.json"],
            cwd=REPO_ROOT,
            capture_output=True,
            encoding="utf-8",
            check=True,
        )
        assert (
            out.stdout.strip() == ""
        ), "적시 주입 인덱스가 다시 커밋됐다 — 편집 시 계산이 정본이다"

    def test_index_file_is_ignored(self) -> None:
        """옛 코드의 `jit build`가 남긴 파일이 `git add -A`로 다시 들어가지 않는다.

        `check-ignore`는 무시되면 0, 아니면 1, 오류면 128이다 — 0만 통과시킨다.
        """
        out = subprocess.run(["git", "check-ignore", "-q", "backlog/jit_index.json"], cwd=REPO_ROOT)
        assert out.returncode == 0

    def test_ci_runs_the_computation_check(self) -> None:
        """집행 지점 — 커밋 인덱스가 사라진 뒤 '대장에서 계산되는가'를 CI가 실제로 본다.

        `harness-integrity` 잡에 `backlog.py jit check` 스텝이 있고 fail-open이 아니어야 한다.
        스텝이 빠지면 0건(경로 해소 전멸)이 어느 곳에서도 red가 되지 않는다.
        """
        import yaml

        spec = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
        steps = [s for s in spec["jobs"]["harness-integrity"]["steps"] if isinstance(s, dict)]
        hits = [
            s for s in steps if "scripts/harness/backlog.py jit check" in str(s.get("run") or "")
        ]
        assert len(hits) == 1, "harness-integrity 잡에 jit check 스텝이 정확히 1개여야 한다"
        assert str(hits[0].get("continue-on-error", "false")).lower() != "true"

    def test_build_is_deterministic(self) -> None:
        """같은 대장이면 같은 후보 — 편집마다 결과가 흔들리면 주입이 소음이 된다."""
        backlog = _backlog(FakeTask(id="HARN-99-fix", paths=["src/x/**"]))
        made = lambda: jit_rules.build_notes(  # noqa: E731
            backlog,
            [FakeRule(id="R-001", title="규칙", enforced_by=["HARN-99"])],
            [FakeIncident(date="2026-09-01", title="사고", fix_ref="HARN-99")],
        )
        assert made() == made()


# ── ⑤ 저장소 현재 상태 ──────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def live_notes() -> list[jit_rules.Note]:
    """실제 대장에서 계산한 주입 후보 — 훅·CLI와 같은 함수(`_build_jit_notes`)를 쓴다."""
    notes, errors = cli._build_jit_notes(REPO_ROOT)
    assert errors == [], errors[:5]
    return notes


class TestLiveRepo:
    def test_live_notes_are_not_empty(self, live_notes) -> None:
        """스캔 0건은 실패다 — 빈 후보는 '사고가 없다'가 아니라 '계산 실패'다."""
        assert len(live_notes) > 50

    def test_a_hot_path_injects_and_a_cold_one_is_silent(self, live_notes) -> None:
        """실제 대장에서의 변별력 — 합성 픽스처만으로는 실물에서 도는지 모른다."""
        assert jit_rules.notes_for_path(live_notes, "scripts/harness/backlog.py")
        assert jit_rules.notes_for_path(live_notes, "README.md") == []


# ── ⑥ 훅 경로 ───────────────────────────────────────────────────────────────


class TestCheckEditHook:
    @staticmethod
    def _run(monkeypatch, capsys, rel: str) -> tuple[int, str]:
        monkeypatch.chdir(REPO_ROOT)
        payload = json.dumps({"tool_input": {"file_path": str(REPO_ROOT / rel)}})
        set_hook_stdin(monkeypatch, payload)
        code = cli.main(["check-edit"])
        return code, capsys.readouterr().err

    def test_hot_path_injects(self, monkeypatch, capsys) -> None:
        code, err = self._run(monkeypatch, capsys, "scripts/harness/backlog.py")
        assert code == 0
        # "[적시 규칙]"만 보면 실패 문구("[적시 규칙] 주입 실패 — …")도 통과한다 — 주입 본문을 본다.
        assert "경로에서 실제로 났던 것" in err
        assert "주입 실패" not in err

    def test_cold_path_is_silent(self, monkeypatch, capsys) -> None:
        code, err = self._run(monkeypatch, capsys, "README.md")
        assert code == 0
        assert "[적시 규칙]" not in err

    def test_injection_failure_never_blocks_and_names_the_exception_type(
        self, monkeypatch, capsys
    ) -> None:
        """fail-open + 침묵 실패 금지 — 계산이 터져도 편집은 통과하고, 타입명은 남는다.

        종전 판은 실제 인덱스 파일을 깨뜨렸다가 복원했다(중단되면 실파일이 깨진 채 남는다 —
        HARN-170 ③). 이제 파일이 없으므로 계산 함수 자체를 터뜨린다. 무타입 경고가 langfuse
        쓰기 8일 무증상 전멸의 원인이었다.
        """

        def boom(_root: Path, _backlog: object | None = None) -> tuple[list, list]:
            raise RuntimeError("터짐")

        monkeypatch.setattr(cli, "_build_jit_notes", boom)
        code, err = self._run(monkeypatch, capsys, "scripts/harness/backlog.py")
        assert code == 0
        assert "RuntimeError" in err
        assert "경로에서 실제로 났던 것" not in err  # 실패가 주입처럼 보이지 않는다

    def test_outside_repo_path_is_ignored(self, monkeypatch, capsys, tmp_path: Path) -> None:
        monkeypatch.chdir(REPO_ROOT)
        payload = json.dumps({"tool_input": {"file_path": str(tmp_path / "elsewhere.py")}})
        set_hook_stdin(monkeypatch, payload)
        assert cli.main(["check-edit"]) == 0
        assert "[적시 규칙]" not in capsys.readouterr().err


# ── ⑥-b 훅은 저장 파일이 아니라 대장을 읽는다 (HARN-130 · hermetic) ─────────


def _ledger_repo(git_repo: Path, monkeypatch) -> Path:
    """시드 + 상환 태스크 1건(`src/x/**`)을 가진 임시 저장소 — main 브랜치라 정책 검사는 조기 반환."""
    monkeypatch.chdir(git_repo)
    assert cli.main(["seed"]) == 0
    assert (
        cli.main(
            [
                "add",
                "--id",
                "HARN-901-fix",
                "--title",
                "픽스처 상환 태스크",
                "--track",
                "math-completion",
                "--stage",
                "S2",
                "--path",
                "src/x/**",
                "--eos-priority",
                "P3",
            ]
        )
        == 0
    )
    return git_repo


def _edit(root: Path, rel: str, monkeypatch, capsys) -> tuple[int, str]:
    capsys.readouterr()
    payload = json.dumps({"tool_input": {"file_path": str(root / rel)}})
    set_hook_stdin(monkeypatch, payload)
    code = cli.main(["check-edit"])
    return code, capsys.readouterr().err


def _add_incident(title: str) -> int:
    return cli.main(
        [
            "incident",
            "add",
            "--title",
            title,
            "--cat",
            "G",
            "--fix-form",
            "task",
            "--fix-ref",
            "HARN-901",
        ]
    )


class TestHookReadsLedgersNotAFile:
    def test_a_leftover_index_file_is_not_read(self, git_repo, monkeypatch, capsys) -> None:
        """옛 코드가 남긴 낡은 인덱스 파일이 있어도 훅은 대장에서 계산한다.

        반례 픽스처: 파일에만 있는 사고(무게 최대)를 심는다. 훅이 파일을 읽으면 그 줄이 뜨고,
        대장에서 계산하면 대장의 사고만 뜬다 — 두 경로가 서로 다른 글자를 내야 변별된다.
        """
        root = _ledger_repo(git_repo, monkeypatch)
        assert _add_incident("대장에 있는 사고") == 0
        stale = {
            "version": 1,
            "max_notes": 5,
            "notes": [
                {
                    "kind": "incident",
                    "ref": "2020-01-01",
                    "paths": ["src/x/**"],
                    "text": "파일에만 있는 낡은 사고",
                    "weight": 6,
                }
            ],
        }
        (root / "backlog" / "jit_index.json").write_text(
            json.dumps(stale, ensure_ascii=False), encoding="utf-8"
        )
        code, err = _edit(root, "src/x/a.py", monkeypatch, capsys)
        assert code == 0
        assert "대장에 있는 사고" in err
        assert "파일에만 있는 낡은 사고" not in err

    def test_cold_path_stays_silent_in_the_same_repo(self, git_repo, monkeypatch, capsys) -> None:
        """대조군 — 위 주입이 '모든 편집에 뜬다'가 아님을 같은 저장소에서 보인다."""
        root = _ledger_repo(git_repo, monkeypatch)
        assert _add_incident("대장에 있는 사고") == 0
        code, err = _edit(root, "docs/elsewhere.md", monkeypatch, capsys)
        assert code == 0
        assert "[적시 규칙]" not in err


# ── ⑥-c 대장 쓰기 뒤 재생성 단계가 없다 (HARN-179) ─────────────────────────


class TestLedgerWritesNeedNoRebuild:
    """쓰기 CLI 다음 편집이 곧바로 새 기록을 본다 — 사이에 사람이 돌릴 명령이 없다.

    종전(커밋 인덱스)에는 `incident add` 뒤 `jit build`를 잊으면 CI `jit check`가 red였다
    (계열 derived-index-not-rebuilt 3회 · 뒤 스텝 7건 미실행). 쓰기 CLI마다 재생성 배선을 다는
    대신 읽는 쪽이 대장을 직접 보게 했으므로(HARN-130), 여기서는 그 결과를 쓰기 쪽에서 본다:
    쓰고 → 다른 명령 없이 → 다음 편집. 훅이 저장된 파일을 읽게 되돌리면(뮤테이션 J01) RED다.
    """

    def test_incident_add_is_visible_to_the_next_edit(self, git_repo, monkeypatch, capsys) -> None:
        root = _ledger_repo(git_repo, monkeypatch)
        assert _add_incident("방금 등재한 사고") == 0
        code, err = _edit(root, "src/x/a.py", monkeypatch, capsys)
        assert code == 0
        assert "방금 등재한 사고" in err
        assert cli.main(["jit", "check"]) == 0

    def test_task_path_amend_moves_the_injection_immediately(
        self, git_repo, monkeypatch, capsys
    ) -> None:
        """태스크 쪽 쓰기도 같다 — 상환 태스크의 paths를 옮기면 주입도 그 자리로 옮겨 간다.

        대조: 옛 경로에서는 사라진다. 옛 설계에서는 이 정정도 재생성을 요구했다(사고 대장이
        아니라 태스크를 고쳐도 인덱스가 낡았다).
        """
        root = _ledger_repo(git_repo, monkeypatch)
        assert _add_incident("경로가 옮겨 갈 사고") == 0
        assert (
            cli.main(
                [
                    "amend",
                    "HARN-901-fix",
                    "--path",
                    "src/y/**",
                    "--drop-scope",
                    "--reason",
                    "픽스처 — 상환 범위 이동",
                ]
            )
            == 0
        )
        _, err_new = _edit(root, "src/y/b.py", monkeypatch, capsys)
        _, err_old = _edit(root, "src/x/a.py", monkeypatch, capsys)
        assert "경로가 옮겨 갈 사고" in err_new
        assert "경로가 옮겨 갈 사고" not in err_old

    def test_rule_enforcer_path_amend_moves_the_injection_immediately(
        self, git_repo, monkeypatch, capsys
    ) -> None:
        """규칙 축도 같다 — `enforced_by`가 가리키는 태스크의 paths를 옮기면 규칙 주입도 따라간다.

        사고의 상환 태스크(위 테스트)와 규칙의 집행 태스크는 같은 `_task_paths`를 거치지만
        별개 입력이다. 옛 설계에서는 규칙 쪽 태스크 paths 정정도 재생성을 요구했다
        (2026-09-29 두 세션이 HARN-179 ④로 따로 실측). 대조: 옮기기 전에는 옛 경로에 뜬다.
        """
        root = _ledger_repo(git_repo, monkeypatch)
        title = "집행 태스크 경로를 따라 옮겨 가는 픽스처 규칙"
        rule = {
            "id": "R-901",
            "slug": "fixture-rule",
            "title": title,
            "origin": "incident",
            "status": "task",
            "enforced_by": ["HARN-901"],
        }
        (root / "backlog" / "rules.ndjson").write_text(
            json.dumps(rule, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        _, err_before = _edit(root, "src/x/a.py", monkeypatch, capsys)
        assert title in err_before  # 양성 대조 — 규칙이 집행 태스크 경로로 주입된다
        assert (
            cli.main(
                [
                    "amend",
                    "HARN-901-fix",
                    "--path",
                    "src/y/**",
                    "--drop-scope",
                    "--reason",
                    "픽스처 — 집행 범위 이동",
                ]
            )
            == 0
        )
        _, err_new = _edit(root, "src/y/b.py", monkeypatch, capsys)
        _, err_old = _edit(root, "src/x/a.py", monkeypatch, capsys)
        assert title in err_new
        assert title not in err_old


# ── ⑦ CLI ───────────────────────────────────────────────────────────────────


class TestCli:
    def test_check_passes_on_the_live_repo(self, monkeypatch, capsys) -> None:
        monkeypatch.chdir(REPO_ROOT)
        assert cli.main(["jit", "check"]) == 0
        assert "계산됨" in capsys.readouterr().out

    def test_check_fails_on_zero_candidates(self, git_repo, monkeypatch, capsys) -> None:
        """스캔 0건은 실패 — 경로가 풀리는 사고·규칙이 하나도 없으면 red(조용한 통과 금지).

        CI의 `jit check` 스텝이 지키는 것이 이것이다. 커밋 인덱스가 사라진 뒤 이 스텝이
        '파일이 없으니 볼 것 없음'으로 늘 초록이면 검사가 아니라 위장이다.
        """
        monkeypatch.chdir(git_repo)
        assert cli.main(["seed"]) == 0
        capsys.readouterr()
        assert cli.main(["jit", "check"]) == 1
        assert "0건" in capsys.readouterr().err

    def test_check_passes_once_one_candidate_resolves(self, git_repo, monkeypatch, capsys) -> None:
        """위 0건 RED의 대조군 — 같은 저장소에 경로가 풀리는 사고 1건을 넣으면 GREEN."""
        _ledger_repo(git_repo, monkeypatch)
        assert _add_incident("경로가 풀리는 사고") == 0
        capsys.readouterr()
        assert cli.main(["jit", "check"]) == 0
        assert "1건 계산됨" in capsys.readouterr().out

    def test_check_fails_on_a_corrupt_ledger_line(self, git_repo, monkeypatch, capsys) -> None:
        """샤드의 깨진 줄도 잡는다 — 오류 위치가 어느 샤드인지 말한다."""
        _ledger_repo(git_repo, monkeypatch)
        assert _add_incident("정상 사고") == 0
        shard = git_repo / "backlog" / "incidents" / "zz_broken.ndjson"
        shard.write_text("{broken\n", encoding="utf-8")
        capsys.readouterr()
        assert cli.main(["jit", "check"]) == 1
        err = capsys.readouterr().err
        assert "JSONDecodeError" in err and "incidents/zz_broken.ndjson:1" in err

    def test_legacy_build_writes_no_file(self, git_repo, monkeypatch, capsys) -> None:
        """옛 안내(사고 등재 뒤 `jit build`)를 따라도 파일이 생기지 않고 같은 검사를 한다."""
        root = _ledger_repo(git_repo, monkeypatch)
        assert _add_incident("경로가 풀리는 사고") == 0
        capsys.readouterr()
        assert cli.main(["jit", "build"]) == 0
        assert "파일을 만들지 않는다" in capsys.readouterr().out
        assert not (root / "backlog" / "jit_index.json").exists()

    def test_show_previews_a_hot_path(self, monkeypatch, capsys) -> None:
        monkeypatch.chdir(REPO_ROOT)
        assert cli.main(["jit", "show", "scripts/harness/backlog.py"]) == 0
        assert "[적시 규칙]" in capsys.readouterr().out

    def test_show_says_zero_rather_than_printing_nothing(self, monkeypatch, capsys) -> None:
        """CLI는 사람이 직접 묻는 경로다 — 여기서의 침묵은 '고장'과 구별되지 않는다."""
        monkeypatch.chdir(REPO_ROOT)
        assert cli.main(["jit", "show", "README.md"]) == 0
        assert "주입 0건" in capsys.readouterr().out
