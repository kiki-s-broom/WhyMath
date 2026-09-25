"""store.py — 직렬화 왕복·무결성 검증 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import store
from models import Gate, Task, Track


def _write_minimal_backlog(
    root: Path,
    tasks: list[Task],
    gates: list[Gate] | None = None,
    stage_order: list[str] | None = None,
) -> None:
    store.save_tracks(
        root,
        stage_order or ["S1", "S2"],
        [
            Track(id="math-completion", title="수학 완성"),
            Track(id="locked-track", title="잠긴 트랙", entry_gate="G-lock"),
        ],
    )
    store.save_gates(
        root,
        (
            gates
            if gates is not None
            else [
                Gate(
                    id="G-lock",
                    title="잠금 게이트",
                    requested="2026-07-01",
                    no_inputs_reason="테스트 픽스처 — 입력 태스크 없음(HARN-174)",
                ),
            ]
        ),
    )
    for task in tasks:
        store.save_task(root, task)


def _task(**overrides) -> Task:
    base = dict(
        id="S1-01-alpha", title="알파", track="math-completion", stage="S1", updated="2026-07-08"
    )
    base.update(overrides)
    return Task(**base)


class TestRoundtrip:
    def test_task_save_then_load_is_identical(self, tmp_path: Path):
        """test_태스크_저장_후_로드_동일"""
        original = _task(
            title='제목: 콜론·"인용"·한글 포함',
            depends_on=["S1-02-beta"],
            acceptance=["항목 1: 콜론 포함", "항목 2"],
            notes="비고",
            priority=2,
        )
        _write_minimal_backlog(tmp_path, [original, _task(id="S1-02-beta", title="베타")])
        backlog, errors = store.load_backlog(tmp_path)
        assert errors == []
        loaded = backlog.tasks["S1-01-alpha"]
        assert loaded == original

    def test_gate_save_then_load_is_identical(self, tmp_path: Path):
        """test_게이트_저장_후_로드_동일"""
        gate = Gate(
            id="G-sample",
            title="샘플 게이트",
            requested="2026-07-05",
            remind_after_days=7,
            notes="비고",
        )
        _write_minimal_backlog(
            tmp_path,
            [_task()],
            gates=[
                Gate(id="G-lock", title="잠금"),
                gate,
            ],
        )
        backlog, _ = store.load_backlog(tmp_path)
        assert backlog.gates["G-sample"] == gate

    def test_serialized_output_is_deterministic(self, tmp_path: Path):
        """test_직렬화_출력은_결정적"""
        # 같은 태스크를 두 번 저장하면 바이트 단위로 동일해야 한다 (diff 안정)
        task = _task()
        first = store.dump_task(task)
        second = store.dump_task(task)
        assert first == second


class TestLoadErrors:
    def test_id_and_filename_mismatch_detected(self, tmp_path: Path):
        """test_id와_파일명_불일치_검출"""
        _write_minimal_backlog(tmp_path, [])
        path = tmp_path / "backlog" / "tasks" / "S1-99-wrong-name.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(store.dump_task(_task(id="S1-01-alpha")), encoding="utf-8")
        _, errors = store.load_backlog(tmp_path)
        assert any("파일명" in e for e in errors)

    def test_unknown_field_detected(self, tmp_path: Path):
        """test_미지_필드_검출"""
        _write_minimal_backlog(tmp_path, [])
        path = tmp_path / "backlog" / "tasks" / "S1-01-alpha.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(store.dump_task(_task()) + "renderer: manim\n", encoding="utf-8")
        _, errors = store.load_backlog(tmp_path)
        assert any("미지 필드" in e for e in errors)


class TestValidateBacklog:
    def test_valid_backlog_is_green(self, tmp_path: Path):
        """test_정상_백로그는_green"""
        _write_minimal_backlog(tmp_path, [_task()])
        backlog, schema_errors = store.load_backlog(tmp_path)
        assert store.validate_backlog(backlog, schema_errors) == []

    def test_nonexistent_dependency_detected(self, tmp_path: Path):
        """test_미존재_의존성_검출"""
        _write_minimal_backlog(tmp_path, [_task(depends_on=["S1-99-ghost"])])
        backlog, schema_errors = store.load_backlog(tmp_path)
        errors = store.validate_backlog(backlog, schema_errors)
        assert any("미존재" in e for e in errors)

    def test_nonexistent_gate_detected(self, tmp_path: Path):
        """test_미존재_게이트_검출"""
        _write_minimal_backlog(tmp_path, [_task(requires_gates=["G-ghost"])])
        backlog, schema_errors = store.load_backlog(tmp_path)
        assert any("G-ghost" in e for e in store.validate_backlog(backlog, schema_errors))

    def test_undefined_track_detected(self, tmp_path: Path):
        """test_미정의_track_검출"""
        _write_minimal_backlog(tmp_path, [_task(track="ghost-track")])
        backlog, schema_errors = store.load_backlog(tmp_path)
        assert any("track" in e for e in store.validate_backlog(backlog, schema_errors))

    def test_stage_outside_stage_order_detected(self, tmp_path: Path):
        """test_stage_order_밖_stage_검출"""
        _write_minimal_backlog(tmp_path, [_task(stage="S9")])
        backlog, schema_errors = store.load_backlog(tmp_path)
        assert any("stage_order" in e for e in store.validate_backlog(backlog, schema_errors))

    def test_roadmap_order_violation_detected(self, tmp_path: Path):
        """test_로드맵_순서_위반_검출"""
        # S1 태스크가 S2(후행) 태스크에 의존하면 로드맵 순서 위반
        _write_minimal_backlog(
            tmp_path,
            [
                _task(id="S1-01-alpha", depends_on=["S2-01-later"]),
                _task(id="S2-01-later", stage="S2"),
            ],
        )
        backlog, schema_errors = store.load_backlog(tmp_path)
        assert any("순서 위반" in e for e in store.validate_backlog(backlog, schema_errors))

    def test_circular_dependency_detected(self, tmp_path: Path):
        """test_순환_참조_검출"""
        _write_minimal_backlog(
            tmp_path,
            [
                _task(id="S1-01-alpha", depends_on=["S1-02-beta"]),
                _task(id="S1-02-beta", depends_on=["S1-01-alpha"], title="베타"),
            ],
        )
        backlog, schema_errors = store.load_backlog(tmp_path)
        errors = store.validate_backlog(backlog, schema_errors)
        assert any("순환" in e for e in errors)

    def test_single_session_multiple_claims_detected(self, tmp_path: Path):
        """test_1세션_다중_claim_검출"""
        _write_minimal_backlog(
            tmp_path,
            [
                _task(id="S1-01-alpha", status="in_progress", session="branch-x"),
                _task(id="S1-02-beta", title="베타", status="in_progress", session="branch-x"),
            ],
        )
        backlog, schema_errors = store.load_backlog(tmp_path)
        errors = store.validate_backlog(backlog, schema_errors)
        assert any("동시 claim" in e for e in errors)


class TestEvents:
    def test_event_appended_as_ndjson(self, tmp_path: Path, git_repo: Path):
        """test_이벤트는_ndjson으로_append — HARN-46: 세션(브랜치) 샤드에 기록된다.

        git_repo 픽스처의 브랜치는 main이므로 샤드는 backlog/events/main.ndjson이다.
        레거시 events.ndjson 미기록·샤딩 상세 계약은 test_event_ledger_sharding.py가
        전담 동결한다 — 여기서는 기본 append 형식만 본다.
        """
        store.append_event(git_repo, "start", "S1-01-alpha", session="b1")
        store.append_event(git_repo, "done", "S1-01-alpha", artifacts=["PR#1"])
        shard = git_repo / "backlog" / "events" / "main.ndjson"
        lines = shard.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["action"] == "start"
        assert first["id"] == "S1-01-alpha"
        assert "ts" in first and "actor" in first
