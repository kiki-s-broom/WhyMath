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

import io
import json
from dataclasses import dataclass, field
from pathlib import Path

import jit_rules
import pytest

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
                FakeIncident(date="2026-09-01", title="무해", fix_ref="HARN-99", damage_class="none"),
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


# ── ④ 인덱스 직렬화 ─────────────────────────────────────────────────────────


class TestIndex:
    def test_dump_is_deterministic(self) -> None:
        """같은 대장이면 같은 바이트 — 아니면 `jit check`가 상시 red가 된다."""
        backlog = _backlog(FakeTask(id="HARN-99-fix", paths=["src/x/**"]))
        made = lambda: jit_rules.build_notes(  # noqa: E731
            backlog,
            [FakeRule(id="R-001", title="규칙", enforced_by=["HARN-99"])],
            [FakeIncident(date="2026-09-01", title="사고", fix_ref="HARN-99")],
        )
        assert jit_rules.dump_index(made()) == jit_rules.dump_index(made())

    def test_roundtrip(self, tmp_path: Path) -> None:
        backlog = _backlog(FakeTask(id="HARN-99-fix", paths=["src/x/**"]))
        notes = jit_rules.build_notes(
            backlog, [], [FakeIncident(date="2026-09-01", title="사고", fix_ref="HARN-99")]
        )
        (tmp_path / "backlog").mkdir()
        jit_rules.index_path(tmp_path).write_text(jit_rules.dump_index(notes), encoding="utf-8")
        assert jit_rules.load_index(tmp_path) == notes

    @pytest.mark.parametrize("body", ["{broken", "[]", '{"version": 1}', '{"notes": "nope"}'])
    def test_corrupt_index_is_empty_not_an_exception(self, tmp_path: Path, body: str) -> None:
        """훅이 읽는 파일이다 — 깨졌다고 편집을 막으면 안 된다."""
        (tmp_path / "backlog").mkdir()
        jit_rules.index_path(tmp_path).write_text(body, encoding="utf-8")
        assert jit_rules.load_index(tmp_path) == []

    def test_missing_index_is_empty(self, tmp_path: Path) -> None:
        assert jit_rules.load_index(tmp_path) == []


# ── ⑤ 저장소 현재 상태 ──────────────────────────────────────────────────────


class TestLiveRepo:
    def test_index_matches_the_ledgers(self) -> None:
        """인덱스는 대장의 렌더 결과다 — 손편집·표류는 여기서 잡힌다."""
        import incidents as incidents_mod
        import rules as rules_mod
        import store

        backlog, _ = store.load_backlog(REPO_ROOT)
        rule_list, rule_errors = rules_mod.load_rules(REPO_ROOT)
        incident_list, incident_errors = incidents_mod.load_incidents(REPO_ROOT)
        assert rule_errors == [] and incident_errors == []
        expected = jit_rules.dump_index(
            jit_rules.build_notes(backlog, rule_list, incident_list)
        )
        assert jit_rules.index_path(REPO_ROOT).read_text(encoding="utf-8") == expected

    def test_index_is_not_empty(self) -> None:
        """스캔 0건은 실패다 — 빈 인덱스는 '사고가 없다'가 아니라 '미구축'이다."""
        assert len(jit_rules.load_index(REPO_ROOT)) > 50

    def test_a_hot_path_injects_and_a_cold_one_is_silent(self) -> None:
        """실제 대장에서의 변별력 — 합성 픽스처만으로는 실물에서 도는지 모른다."""
        notes = jit_rules.load_index(REPO_ROOT)
        assert jit_rules.notes_for_path(notes, "scripts/harness/backlog.py")
        assert jit_rules.notes_for_path(notes, "README.md") == []


# ── ⑥ 훅 경로 ───────────────────────────────────────────────────────────────


class TestCheckEditHook:
    @staticmethod
    def _run(monkeypatch, capsys, rel: str) -> tuple[int, str]:
        monkeypatch.chdir(REPO_ROOT)
        payload = json.dumps({"tool_input": {"file_path": str(REPO_ROOT / rel)}})
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
        code = cli.main(["check-edit"])
        return code, capsys.readouterr().err

    def test_hot_path_injects(self, monkeypatch, capsys) -> None:
        code, err = self._run(monkeypatch, capsys, "scripts/harness/backlog.py")
        assert code == 0
        assert "[적시 규칙]" in err

    def test_cold_path_is_silent(self, monkeypatch, capsys) -> None:
        code, err = self._run(monkeypatch, capsys, "README.md")
        assert code == 0
        assert "[적시 규칙]" not in err

    def test_broken_index_never_blocks_the_edit(self, monkeypatch, capsys) -> None:
        """fail-open — 관측성 코드가 개발을 볼모로 잡으면 사람이 훅을 끈다."""
        path = jit_rules.index_path(REPO_ROOT)
        original = path.read_bytes()
        try:
            path.write_text("{broken\n", encoding="utf-8")
            code, err = self._run(monkeypatch, capsys, "scripts/harness/backlog.py")
            assert code == 0
            assert "[적시 규칙]" not in err  # 빈 인덱스 = 침묵 (예외가 아니다)
        finally:
            path.write_bytes(original)
        assert path.read_bytes() == original

    def test_injection_failure_names_the_exception_type(self, monkeypatch, capsys) -> None:
        """침묵 실패 금지 — 무타입 경고가 langfuse 8일 무증상 전멸의 원인이었다."""
        monkeypatch.chdir(REPO_ROOT)

        def boom(_root: Path) -> list[jit_rules.Note]:
            raise RuntimeError("터짐")

        monkeypatch.setattr(jit_rules, "load_index", boom)
        payload = json.dumps({"tool_input": {"file_path": str(REPO_ROOT / "scripts/harness/backlog.py")}})
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
        assert cli.main(["check-edit"]) == 0
        assert "RuntimeError" in capsys.readouterr().err

    def test_outside_repo_path_is_ignored(self, monkeypatch, capsys, tmp_path: Path) -> None:
        monkeypatch.chdir(REPO_ROOT)
        payload = json.dumps({"tool_input": {"file_path": str(tmp_path / "elsewhere.py")}})
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
        assert cli.main(["check-edit"]) == 0
        assert "[적시 규칙]" not in capsys.readouterr().err


# ── ⑦ CLI ───────────────────────────────────────────────────────────────────


class TestCli:
    def test_check_passes_on_the_live_repo(self, monkeypatch, capsys) -> None:
        monkeypatch.chdir(REPO_ROOT)
        assert cli.main(["jit", "check"]) == 0
        assert "일치" in capsys.readouterr().out

    def test_check_detects_a_stale_index(self, monkeypatch, capsys) -> None:
        monkeypatch.chdir(REPO_ROOT)
        path = jit_rules.index_path(REPO_ROOT)
        original = path.read_bytes()
        try:
            path.write_text('{"version": 1, "max_notes": 5, "notes": []}\n', encoding="utf-8")
            assert cli.main(["jit", "check"]) == 1
            assert "어긋났다" in capsys.readouterr().err
        finally:
            path.write_bytes(original)
        assert path.read_bytes() == original

    def test_show_previews_a_hot_path(self, monkeypatch, capsys) -> None:
        monkeypatch.chdir(REPO_ROOT)
        assert cli.main(["jit", "show", "scripts/harness/backlog.py"]) == 0
        assert "[적시 규칙]" in capsys.readouterr().out

    def test_show_says_zero_rather_than_printing_nothing(self, monkeypatch, capsys) -> None:
        """CLI는 사람이 직접 묻는 경로다 — 여기서의 침묵은 '고장'과 구별되지 않는다."""
        monkeypatch.chdir(REPO_ROOT)
        assert cli.main(["jit", "show", "README.md"]) == 0
        assert "주입 0건" in capsys.readouterr().out
