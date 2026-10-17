"""Feature/Code Freeze 검사의 **판정 경계·문서 일치·배선** 동결 (HARN-103).

판정 절마다 '그 절이 없으면 통과하는 입력'을 픽스처로 둔다(CLAUDE.md 2026-09-01·09-07):
  · 단계 경계 절 → 경계 전날/당일 (11/29·11/30, 12/13·12/14, 1/14·1/15)
  · 만료 절 → RELEASED에서 동결 경로 변경이 통과
  · 라벨 AND 절 → Code Freeze에서 라벨 하나만 있는 경우
  · 경로 절 → 동결 안 되는 경로(docs/, tests/)와 Code Freeze 전용 `data/`
  · 측정 실패 절 → 존재하지 않는 base ref는 통과가 아니라 exit 2
"""

from __future__ import annotations

import importlib.util
import re
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "ops" / "check_release_freeze.py"
_DOC = _REPO_ROOT / "docs" / "standards" / "release_freeze.md"
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "release-freeze.yml"


def _load():
    spec = importlib.util.spec_from_file_location("check_release_freeze", _SCRIPT)
    assert spec and spec.loader, f"로드 실패: {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_release_freeze"] = module
    spec.loader.exec_module(module)
    return module


m = _load()
BLOCKER = m.LABEL_RELEASE_BLOCKER
APPROVED = m.LABEL_CODE_FREEZE_APPROVED
SRC = ["src/backend/whymath_backend/app.py"]


class TestPhaseBoundaries:
    @pytest.mark.parametrize(
        ("day", "phase"),
        [
            (date(2026, 11, 29), m.PHASE_OPEN),
            (date(2026, 11, 30), m.PHASE_FEATURE_FREEZE),
            (date(2026, 12, 13), m.PHASE_FEATURE_FREEZE),
            (date(2026, 12, 14), m.PHASE_CODE_FREEZE),
            (date(2027, 1, 14), m.PHASE_CODE_FREEZE),
            (date(2027, 1, 15), m.PHASE_RELEASED),
        ],
    )
    def test_boundary(self, day: date, phase: str) -> None:
        assert m.phase_of(day) == phase

    def test_schedule_contradiction_is_measurement_failure(self, monkeypatch) -> None:
        monkeypatch.setattr(m, "CODE_FREEZE_START", date(2026, 11, 1))
        with pytest.raises(m.MeasurementError):
            m.phase_of(date(2026, 12, 1))


class TestVerdict:
    def test_open_passes_without_label(self) -> None:
        assert m.evaluate(date(2026, 11, 29), set(), SRC).ok

    def test_feature_freeze_blocks_src_without_label(self) -> None:
        v = m.evaluate(date(2026, 11, 30), set(), SRC)
        assert not v.ok and v.missing_labels == (BLOCKER,)

    def test_feature_freeze_passes_with_blocker(self) -> None:
        assert m.evaluate(date(2026, 11, 30), {BLOCKER}, SRC).ok

    def test_code_freeze_requires_both_labels(self) -> None:
        only_blocker = m.evaluate(date(2026, 12, 14), {BLOCKER}, SRC)
        assert not only_blocker.ok and only_blocker.missing_labels == (APPROVED,)
        only_approved = m.evaluate(date(2026, 12, 14), {APPROVED}, SRC)
        assert not only_approved.ok and only_approved.missing_labels == (BLOCKER,)
        assert m.evaluate(date(2026, 12, 14), {BLOCKER, APPROVED}, SRC).ok

    def test_released_passes_frozen_paths_without_label(self) -> None:
        assert m.evaluate(date(2027, 1, 15), set(), SRC).ok

    def test_docs_and_tests_never_frozen(self) -> None:
        files = ["docs/standards/x.md", "tests/infra/test_x.py", "backlog/tasks/a.yaml"]
        assert m.evaluate(date(2026, 12, 20), set(), files).ok

    def test_data_frozen_only_from_code_freeze(self) -> None:
        data = ["data/corpus/x.json"]
        assert m.evaluate(date(2026, 12, 1), set(), data).ok
        assert not m.evaluate(date(2026, 12, 14), {BLOCKER}, data).ok

    def test_prefix_is_directory_boundary(self) -> None:
        # `src/`가 아닌 `srcx/`·`docs/src/`를 동결로 오판하지 않는다.
        assert m.evaluate(date(2026, 12, 1), set(), ["srcx/a.py", "docs/src/a.md"]).ok


class TestCli:
    def test_violation_exit_1(self, tmp_path: Path) -> None:
        f = tmp_path / "files.txt"
        f.write_text("\n".join(SRC), encoding="utf-8")
        assert m.main(["--files-from", str(f), "--today", "2026-12-01"]) == 1

    def test_pass_exit_0(self, tmp_path: Path) -> None:
        f = tmp_path / "files.txt"
        f.write_text("\n".join(SRC), encoding="utf-8")
        assert m.main(["--files-from", str(f), "--today", "2026-12-01", "--labels", BLOCKER]) == 0

    def test_bad_date_exit_2(self, tmp_path: Path) -> None:
        f = tmp_path / "files.txt"
        f.write_text("x", encoding="utf-8")
        assert m.main(["--files-from", str(f), "--today", "12/01"]) == 2

    def test_missing_base_ref_is_measurement_failure_not_pass(self) -> None:
        assert (
            m.main(["--base", "refs/heads/no-such-ref-for-freeze-test", "--today", "2026-12-01"])
            == 2
        )

    def test_missing_files_from_exit_2(self, tmp_path: Path) -> None:
        assert m.main(["--files-from", str(tmp_path / "nope.txt"), "--today", "2026-12-01"]) == 2


class TestDocMatchesCode:
    def test_dates_in_doc_table(self) -> None:
        text = _DOC.read_text(encoding="utf-8")
        for d in (m.FEATURE_FREEZE_START, m.CODE_FREEZE_START, m.FREEZE_EXPIRES):
            assert d.isoformat() in text, f"문서에 {d} 가 없다 — 코드와 문서의 일정이 갈라졌다"

    def test_labels_in_doc(self) -> None:
        text = _DOC.read_text(encoding="utf-8")
        assert f"`{BLOCKER}`" in text and f"`{APPROVED}`" in text

    def test_doc_names_expiry_and_gate(self) -> None:
        text = _DOC.read_text(encoding="utf-8")
        assert "만료" in text and "G-release-freeze-labels-and-required" in text

    def test_frozen_prefixes_listed_in_doc(self) -> None:
        text = _DOC.read_text(encoding="utf-8")
        for p in m.FROZEN_PREFIXES + m.CODE_FREEZE_EXTRA_PREFIXES:
            assert f"`{p}`" in text, f"문서 §3에 동결 경로 {p} 가 없다"


class TestWorkflowWiring:
    def _spec(self) -> dict:
        return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))

    def test_runs_the_script_on_pull_request(self) -> None:
        spec = self._spec()
        triggers = spec.get("on") or spec.get(True)  # PyYAML은 `on`을 True로 읽는다
        assert "pull_request" in triggers
        assert {"labeled", "unlabeled"} <= set(triggers["pull_request"]["types"])
        steps = spec["jobs"]["release-freeze"]["steps"]
        assert any("scripts/ops/check_release_freeze.py" in (s.get("run") or "") for s in steps)

    def test_checkout_has_full_history(self) -> None:
        steps = self._spec()["jobs"]["release-freeze"]["steps"]
        co = next(s for s in steps if "actions/checkout" in (s.get("uses") or ""))
        assert co["with"]["fetch-depth"] == 0

    def test_labels_not_interpolated_into_run(self) -> None:
        # 라벨 이름이 셸 명령이 되는 주입 경로를 막는다: run 본문에 ${{ }} 금지.
        for step in self._spec()["jobs"]["release-freeze"]["steps"]:
            assert not re.search(r"\$\{\{", step.get("run") or ""), step.get("name")

    def test_merge_group_does_not_hang_queue(self) -> None:
        spec = self._spec()
        assert "merge_group" in (spec.get("on") or spec.get(True))
