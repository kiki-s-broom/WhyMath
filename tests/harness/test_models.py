"""models.py — 스키마 검증 규칙 테스트."""

from __future__ import annotations

from models import Gate, Task, Track


def _valid_task(**overrides) -> Task:
    base = dict(
        id="S1-01-sample-task",
        title="샘플 태스크",
        track="math-completion",
        stage="S1",
        updated="2026-07-08",
    )
    base.update(overrides)
    return Task(**base)


class TestTaskValidation:
    def test_valid_task_has_no_errors(self):
        """test_정상_태스크는_오류_없음"""
        assert _valid_task().validate() == []

    def test_invalid_id_format_rejected(self):
        """test_잘못된_ID_형식_거부"""
        assert any("ID 형식" in e for e in _valid_task(id="s1_bad_id").validate())

    def test_unregistered_layer_rejected(self):
        """test_미등록_layer_거부"""
        # worktree 화이트리스트 7종 밖의 layer는 거부 (7계층 경계 강제)
        assert any("layer" in e for e in _valid_task(layer="frontend").validate())

    def test_unregistered_subject_rejected(self):
        """test_미등록_subject_거부"""
        assert any("subject" in e for e in _valid_task(subject="astrology").validate())

    def test_all_registered_subjects_pass(self):
        """test_등록된_전과목은_통과"""
        # 다과목 확장: 물리~세계사까지 전부 스키마가 수용해야 한다
        for subject in (
            "physics",
            "chemistry",
            "biology",
            "earth-science",
            "economics",
            "history",
            "world-history",
            "korean",
            "english",
        ):
            assert _valid_task(subject=subject).validate() == []

    def test_priority_out_of_range_rejected(self):
        """test_priority_범위_밖_거부"""
        assert any("priority" in e for e in _valid_task(priority=0).validate())
        assert any("priority" in e for e in _valid_task(priority=6).validate())

    def test_done_without_artifacts_rejected(self):
        """test_done인데_증적_없으면_거부"""
        errors = _valid_task(status="done", artifacts=[]).validate()
        assert any("artifacts" in e for e in errors)

    def test_done_with_artifacts_passes(self):
        """test_done이고_증적_있으면_통과"""
        assert _valid_task(status="done", artifacts=["PR #500"]).validate() == []

    def test_in_progress_without_session_rejected(self):
        """test_in_progress인데_session_없으면_거부"""
        errors = _valid_task(status="in_progress", session=None).validate()
        assert any("session" in e for e in errors)

    def test_invalid_updated_format_rejected(self):
        """test_잘못된_updated_형식_거부"""
        assert any("updated" in e for e in _valid_task(updated="07/08/2026").validate())

    def test_gate_id_format_violation_rejected(self):
        """test_게이트_ID_형식_위반_거부"""
        errors = _valid_task(requires_gates=["phaiakes9"]).validate()
        assert any("게이트 ID" in e for e in errors)


class TestGateValidation:
    def test_valid_gate(self):
        """test_정상_게이트"""
        # HARN-174: pending 게이트는 여는 작업 또는 입력 없음 사유 중 하나가 필수다
        gate = Gate(
            id="G-sample-gate",
            title="샘플",
            requested="2026-07-08",
            no_inputs_reason="테스트 픽스처",
        )
        assert gate.validate() == []

    def test_cleared_without_evidence_rejected(self):
        """test_cleared인데_evidence_없으면_거부"""
        gate = Gate(id="G-sample-gate", title="샘플", status="cleared")
        assert any("evidence" in e for e in gate.validate())

    def test_passed_determination(self):
        """test_passed_판정"""
        assert not Gate(id="G-a", title="t").passed
        assert Gate(id="G-a", title="t", status="cleared", evidence="PR").passed
        assert Gate(id="G-a", title="t", status="waived").passed


class TestTrackValidation:
    def test_valid_track(self):
        """test_정상_트랙"""
        assert Track(id="math-completion", title="수학 완성").validate() == []

    def test_entry_gate_format_violation_rejected(self):
        """test_entry_gate_형식_위반_거부"""
        track = Track(id="t", title="제목", entry_gate="not-a-gate")
        assert any("entry_gate" in e for e in track.validate())


class TestTaskPaths:
    """paths 필드 — 파일 범위 선언 검증 (harness v1.1)."""

    def test_paths_defaults_to_empty_list_for_legacy_task(self):
        """test_paths_기본값은_빈_리스트_기존_태스크_하위호환"""
        task = _valid_task()
        assert task.paths == []
        assert task.validate() == []

    def test_valid_paths_pass(self):
        """test_정상_paths_통과"""
        task = _valid_task(paths=["src/backend/**", "docs/data/*.md"])
        assert task.validate() == []

    def test_absolute_path_rejected(self):
        """test_절대경로_거부"""
        errors = _valid_task(paths=["/etc/passwd"]).validate()
        assert any("절대경로" in e for e in errors)

    def test_parent_reference_rejected(self):
        """test_상위참조_거부"""
        errors = _valid_task(paths=["../outside/**"]).validate()
        assert any("상위 참조" in e for e in errors)

    def test_backslash_rejected(self):
        """test_백슬래시_거부"""
        errors = _valid_task(paths=["src\\backend\\**"]).validate()
        assert any("백슬래시" in e for e in errors)

    def test_paths_outside_layer_domain_only_warns(self):
        """test_layer_도메인_밖_paths는_경고만"""
        # backend 태스크가 mobile 폴더를 선언 — error가 아닌 warning (횡단 태스크 허용)
        task = _valid_task(layer="backend", paths=["src/mobile/**"])
        assert task.validate() == []
        assert any("도메인" in w for w in task.layer_drift_warnings())

    def test_paths_inside_layer_domain_has_no_warning(self):
        """test_layer_도메인_안_paths는_경고_없음"""
        task = _valid_task(layer="backend", paths=["src/backend/api/**"])
        assert task.layer_drift_warnings() == []
