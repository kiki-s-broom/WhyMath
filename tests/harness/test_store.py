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


def _gate(gate_id: str, title: str) -> Gate:
    return Gate(
        id=gate_id,
        title=title,
        requested="2026-07-01",
        no_inputs_reason="테스트 픽스처 — 입력 태스크 없음(HARN-174)",
    )


class TestGateIdDuplicate:
    """HARN-192 — gates.yaml에 같은 id 블록이 둘이면 뒤 정의가 앞 정의를 조용히 덮어썼다.

    태스크 쪽은 '태스크 ID 중복'으로 잡는데 게이트 쪽은 사전 대입(`gates[id] = gate`)이라
    validate가 exit 0으로 통과했다(2026-09-28 실측 — PR #1352·#1358이 같은 게이트 ID를
    서로 다른 정의로 따로 추가했고, 충돌을 '둘 다 유지'로 풀면 통과했다).
    """

    def test_duplicate_gate_id_is_reported_at_load(self, tmp_path: Path):
        """test_같은_게이트_ID_두_블록은_로드_오류"""
        _write_minimal_backlog(
            tmp_path,
            [_task()],
            gates=[
                _gate("G-lock", "앞 정의"),
                _gate("G-dup", "먼저 온 정의"),
                _gate("G-dup", "나중에 온 정의"),
            ],
        )
        backlog, errors = store.load_backlog(tmp_path)
        dup_errors = [e for e in errors if "게이트 ID 중복" in e]
        assert len(dup_errors) == 1
        assert "G-dup" in dup_errors[0]
        # 오류를 내더라도 로드는 계속된다(뒤 정의가 이긴다) — 다른 무결성 검사를 막지 않는다
        assert backlog.gates["G-dup"].title == "나중에 온 정의"

    def test_duplicate_gate_id_makes_validate_red(self, tmp_path: Path):
        """test_게이트_ID_중복은_validate_오류로_승격"""
        _write_minimal_backlog(
            tmp_path,
            [_task()],
            gates=[_gate("G-lock", "잠금"), _gate("G-dup", "가"), _gate("G-dup", "나")],
        )
        backlog, schema_errors = store.load_backlog(tmp_path)
        errors = store.validate_backlog(backlog, schema_errors)
        assert any("게이트 ID 중복" in e and "G-dup" in e for e in errors)

    def test_distinct_gate_ids_are_green(self, tmp_path: Path):
        """test_서로_다른_게이트_ID_두_개는_대조군_green — 과잉 검출(전부 실패) 방지"""
        _write_minimal_backlog(
            tmp_path,
            [_task()],
            gates=[_gate("G-lock", "잠금"), _gate("G-one", "하나"), _gate("G-two", "둘")],
        )
        backlog, schema_errors = store.load_backlog(tmp_path)
        assert not [e for e in schema_errors if "게이트 ID 중복" in e]
        assert store.validate_backlog(backlog, schema_errors) == []

    def test_three_blocks_of_same_id_reports_each_extra_once(self, tmp_path: Path):
        """test_같은_ID_세_블록은_초과분_2건을_각각_보고"""
        _write_minimal_backlog(
            tmp_path,
            [_task()],
            gates=[
                _gate("G-lock", "잠금"),
                _gate("G-dup", "1"),
                _gate("G-dup", "2"),
                _gate("G-dup", "3"),
            ],
        )
        _, errors = store.load_backlog(tmp_path)
        assert len([e for e in errors if "게이트 ID 중복" in e]) == 2

    def test_cli_validate_exits_1_on_duplicate_gate_id(self, git_repo: Path, monkeypatch, capsys):
        """test_validate_CLI는_게이트_ID_중복에서_exit_1 — acceptance ①의 종단 확인"""
        import backlog as cli

        monkeypatch.chdir(git_repo)
        _write_minimal_backlog(
            git_repo,
            [_task()],
            gates=[_gate("G-lock", "잠금"), _gate("G-dup", "가"), _gate("G-dup", "나")],
        )
        assert cli.main(["validate", "--quiet"]) == 1
        assert "게이트 ID 중복" in capsys.readouterr().err


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


class TestYamlDuplicateKey:
    """HARN-203 — 한 매핑 안에서 같은 키가 둘이면 앞 값이 조용히 사라졌다.

    `yaml.safe_load`는 중복 키에서 뒤 값이 이기고 오류가 없다(2026-09-29 실측: title이 둘인 게이트
    블록이 뒤 값 하나로 로드됨). 블록 단위 ID 중복(HARN-192)은 *블록 안의* 키 중복을 못 본다.
    병렬 브랜치가 같은 블록의 같은 키를 따로 고치고 충돌을 '둘 다 유지'로 풀면 통과했다.
    """

    _MARK = "같은 매핑 안에서"

    @staticmethod
    def _append(path: Path, text: str) -> None:
        path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")

    def test_duplicate_key_in_task_file_is_reported_with_file_and_key(self, tmp_path: Path):
        """test_태스크_파일의_중복_키는_파일명과_키_이름을_담아_보고"""
        _write_minimal_backlog(tmp_path, [_task()])
        path = tmp_path / "backlog" / "tasks" / "S1-01-alpha.yaml"
        self._append(path, "priority: 2\n")
        backlog, errors = store.load_backlog(tmp_path)
        dup = [e for e in errors if self._MARK in e]
        assert len(dup) == 1, errors
        assert "S1-01-alpha.yaml" in dup[0] and "'priority'" in dup[0]
        # 오류를 내더라도 로드는 계속된다(뒤 값이 이긴다) — 다른 무결성 검사를 가리지 않는다
        assert backlog.tasks["S1-01-alpha"].priority == 2

    def test_duplicate_key_inside_gate_block_is_reported(self, tmp_path: Path):
        """test_게이트_블록_안의_중복_title은_보고 — 블록 ID는 같지 않아도 잡혀야 한다"""
        _write_minimal_backlog(tmp_path, [_task()])
        path = tmp_path / "backlog" / "gates.yaml"
        text = path.read_text(encoding="utf-8")
        marker = "    title: 잠금 게이트\n"
        assert text.count(marker) == 1, text  # 주입 대상 실재 단언
        path.write_text(
            text.replace(marker, marker + "    title: 뒤에 온 제목\n"), encoding="utf-8"
        )
        backlog, errors = store.load_backlog(tmp_path)
        dup = [e for e in errors if self._MARK in e]
        assert len(dup) == 1, errors
        assert "gates.yaml" in dup[0] and "'title'" in dup[0]
        assert backlog.gates["G-lock"].title == "뒤에 온 제목"  # 뒤 값이 이긴다(결함의 실체)

    def test_duplicate_key_in_tracks_yaml_is_reported(self, tmp_path: Path):
        """test_tracks_yaml의_중복_키도_보고"""
        _write_minimal_backlog(tmp_path, [_task()])
        self._append(tmp_path / "backlog" / "tracks.yaml", "stage_order: [S9]\n")
        _, errors = store.load_backlog(tmp_path)
        dup = [e for e in errors if self._MARK in e]
        assert len(dup) == 1 and "tracks.yaml" in dup[0] and "'stage_order'" in dup[0], errors

    def test_duplicate_key_in_policy_yaml_is_reported(self, tmp_path: Path):
        """test_policy_yaml의_중복_키도_보고 — 같은 대장 계열 로더라 범위에 넣었다"""
        (tmp_path / "backlog").mkdir(parents=True, exist_ok=True)
        (tmp_path / "backlog" / "policy.yaml").write_text(
            "path_overlap: warn\npath_overlap: block\n", encoding="utf-8"
        )
        _, errors = store.load_policy(tmp_path)
        dup = [e for e in errors if self._MARK in e]
        assert len(dup) == 1 and "policy.yaml" in dup[0] and "'path_overlap'" in dup[0], errors

    def test_duplicate_key_makes_validate_red(self, tmp_path: Path):
        """test_중복_키는_validate_오류로_승격"""
        _write_minimal_backlog(tmp_path, [_task()])
        self._append(tmp_path / "backlog" / "tasks" / "S1-01-alpha.yaml", "priority: 2\n")
        backlog, schema_errors = store.load_backlog(tmp_path)
        errors = store.validate_backlog(backlog, schema_errors)
        assert any(self._MARK in e and "'priority'" in e for e in errors), errors

    def test_nested_duplicate_key_is_reported(self, tmp_path: Path):
        """test_중첩_매핑의_중복_키도_보고 — 최상위만 보는 검사가 아니다"""
        path = tmp_path / "nested.yaml"
        path.write_text("outer:\n  inner: 1\n  inner: 2\nother: 3\n", encoding="utf-8")
        errors: list[str] = []
        data = store._load_yaml(path, errors)
        assert len(errors) == 1 and "'inner'" in errors[0] and "nested.yaml" in errors[0], errors
        assert data["outer"]["inner"] == 2

    def test_distinct_keys_are_green(self, tmp_path: Path):
        """test_키가_서로_다르면_대조군_green — 과잉 검출(전부 실패) 방지"""
        _write_minimal_backlog(tmp_path, [_task(priority=2, notes="비고")])
        backlog, schema_errors = store.load_backlog(tmp_path)
        assert not [e for e in schema_errors if self._MARK in e]
        assert store.validate_backlog(backlog, schema_errors) == []

    def test_same_key_in_different_mappings_is_not_a_duplicate(self, tmp_path: Path):
        """test_서로_다른_매핑의_같은_키는_중복이_아니다 — 블록마다 title이 있는 게 정상"""
        path = tmp_path / "ok.yaml"
        path.write_text("a:\n  title: 가\nb:\n  title: 나\n", encoding="utf-8")
        errors: list[str] = []
        store._load_yaml(path, errors)
        assert errors == []

    def test_repeated_merge_key_is_not_flagged(self, tmp_path: Path):
        """test_병합_키가_한_매핑에_둘이어도_제외 — 앵커 병합은 의도된 합성이라 중복이 아니다

        면제 절의 반례: `<<`가 **두 번** 나오는 매핑이다. 키가 하나뿐인 병합(`<<: *b` + `k: 2`)은
        면제 절이 없어도 중복이 아니라서 이 절을 밟지 못한다(뮤테이션 M6이 살아남아 발각).
        """
        path = tmp_path / "merge.yaml"
        path.write_text(
            "a: &a {x: 1}\nb: &b {y: 2}\nc:\n  <<: *a\n  <<: *b\n  z: 3\n", encoding="utf-8"
        )
        errors: list[str] = []
        data = store._load_yaml(path, errors)
        assert errors == []
        assert data["c"] == {"x": 1, "y": 2, "z": 3}

    def test_errors_argument_is_optional_and_keeps_old_behavior(self, tmp_path: Path):
        """test_errors_인자를_안_주면_종전_동작 — 뒤 값이 이기고 예외 없음(하위호환)"""
        path = tmp_path / "dup.yaml"
        path.write_text("k: 앞\nk: 뒤\n", encoding="utf-8")
        assert store._load_yaml(path) == {"k": "뒤"}

    def test_real_backlog_has_no_duplicate_keys(self):
        """test_실제_backlog_전체에_중복_키_0건 — ③ 켜는 순간 main이 red가 되지 않음을 상시 동결

        이 테스트가 red면 누군가 대장 YAML에 같은 키를 두 번 적었다(병합 충돌을 둘 다 유지로 푼
        흔적). 검사 대상이 0건이면 공허하게 통과하므로 파일 수 하한도 함께 단언한다.
        """
        root = Path(__file__).resolve().parents[2]
        backlog, errors = store.load_backlog(root)
        assert len(backlog.tasks) > 100, "실제 대장을 못 읽었다 — 이 검사가 공허해졌다"
        assert not [e for e in errors if self._MARK in e], errors
