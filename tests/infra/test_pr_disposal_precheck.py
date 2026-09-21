"""HARN-93 ③ — 처분 라벨 PR 닫기 전 안전 확인 도구의 계약 동결.

**왜**: 이 도구가 안전(exit 0)이라고 말하는 순간이 실제로 "닫아도 고아 코드가 남지
않는다"는 뜻이어야 한다. 반대로 측정 자체가 실패했는데 exit 0을 내면 그 실패가
"안전 확인됨"으로 위장된다(CLAUDE.md "측정 실패와 통과는 같은 색이면 안 된다"). 이
파일은 두 축을 각각 봉인한다 — ① 순수 판정 함수 `decide`가 4가지 입력 조합에서
정확한 안전/차단을 내는가 ② `main()`이 조회 실패(토큰 없음·PR 없음·git 실패)를
"안전"과 다른 exit code·문구로 내는가.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "pr_disposal_precheck",
    Path(__file__).resolve().parents[2] / "scripts" / "ops" / "pr_disposal_precheck.py",
)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod  # @dataclass 조회 대비 — exec 전 등록
_spec.loader.exec_module(_mod)

decide = _mod.decide
main = _mod.main
DISPOSAL_LABELS = _mod.DISPOSAL_LABELS
CODE_PREFIXES = _mod.CODE_PREFIXES


class TestDecideNoAbsentFiles:
    """trunk 부재 파일이 0건이면 회수 좌석 유무와 무관하게 항상 안전."""

    def test_zero_absent_is_safe_without_recovery(self):
        v = decide([], [])
        assert v.safe is True
        assert "0건" in v.reasons[0]

    def test_zero_absent_is_safe_even_with_recovery_noise(self):
        """분모가 0이면 회수 좌석 존재 여부는 판정에 영향이 없다(첫 가드가 우선)."""
        v = decide([], ["HARN-99-recovered-thing"])
        assert v.safe is True


class TestDecideWithAbsentFiles:
    """trunk 부재 파일이 있으면 회수 좌석 등재 여부가 판정을 가른다."""

    def test_absent_with_recovery_seat_is_safe(self):
        v = decide(["src/a.py", "tests/test_a.py"], ["HARN-99-recovery"])
        assert v.safe is True
        assert "HARN-99-recovery" in v.reasons[0]

    def test_absent_without_recovery_seat_is_blocked(self):
        v = decide(["src/a.py"], [])
        assert v.safe is False
        assert any("회수 좌석 없음" in r for r in v.reasons)

    def test_blocked_reason_lists_absent_files(self):
        v = decide(["src/a.py", "data/b.json"], [])
        joined = "\n".join(v.reasons)
        assert "src/a.py" in joined
        assert "data/b.json" in joined

    def test_blocked_reason_truncates_long_file_list(self):
        many = [f"src/file_{i}.py" for i in range(25)]
        v = decide(many, [])
        joined = "\n".join(v.reasons)
        assert "외 5건" in joined  # 25 - 20 = 5


class TestConstants:
    """라벨·프리픽스 상수가 실측 문서(unmerged_branch_audit_2026-09-08.md)와 일치."""

    def test_disposal_labels_match_harn42(self):
        assert DISPOSAL_LABELS == {"eos-merge", "eos-rework", "eos-postpone", "eos-close"}

    def test_code_prefixes_match_audit_methodology(self):
        assert CODE_PREFIXES == ("src/", "tests/", "scripts/", "data/")


_HARNESS_DIR = str(Path(__file__).resolve().parents[2] / "scripts" / "harness")
if _HARNESS_DIR not in sys.path:
    sys.path.insert(0, _HARNESS_DIR)
import store as _store  # noqa: E402 - sys.path 조정 후 import (하네스 모듈 관례)
from models import Backlog as _Backlog  # noqa: E402
from models import Task as _Task  # noqa: E402


def _task(
    task_id: str,
    *,
    notes: str = "",
    artifacts: list[str] | None = None,
    paths: list[str] | None = None,
) -> _Task:
    return _Task(
        id=task_id,
        title=task_id,
        track="infra-debt",
        stage="S3",
        notes=notes,
        artifacts=artifacts or [],
        paths=paths or [],
    )


class TestRecoveryTaskIdsDiscriminatesMentionFromCoverage:
    """`recovery_task_ids`는 '#PR 언급'만으로 회수 좌석을 인정하지 않는다.

    자기발견 결함(HARN-93 구현 중 실측): 실 PR #858로 첫 구현을 실행했더니
    `HARN-42`(이 PR을 CLOSE로 *판정*만 한 태스크)가 notes에 `#858`을 남긴다는
    이유만으로 "회수 좌석 있음"으로 오탐됐다 — 판정한 사실과 코드를 옮기기로 한
    사실이 같은 문자열로 뭉개진 것이다. `paths` 커버리지 요구를 추가해 고쳤고,
    이 클래스가 그 회귀를 봉인한다. `store.load_backlog`를 monkeypatch해 실 YAML
    파일 없이(PyYAML 없는 하네스에서도) 판정 로직만 검증한다.
    """

    def _backlog_of(self, *tasks: _Task) -> _Backlog:
        b = _Backlog()
        for t in tasks:
            b.tasks[t.id] = t
        return b

    def test_mention_only_task_is_not_a_recovery_seat(self, monkeypatch, tmp_path):
        """HARN-42 재현 — PR 번호를 언급하지만 paths가 부재 파일과 무관한 판정 태스크."""
        backlog = self._backlog_of(
            _task(
                "HARN-42-open-pr-eos-reclassification",
                notes="CLOSE 판정 사유 코멘트: #858",
                artifacts=["docs/reviews/open_pr_eos_triage.md"],
                paths=["docs/reviews/open_pr_eos_triage.md"],
            )
        )
        monkeypatch.setattr(_store, "load_backlog", lambda root: (backlog, []))
        ids, err = _mod.recovery_task_ids(tmp_path, 858, ["src/backend/x/josa.py"])
        assert err == ""
        assert ids == [], "PR 번호를 언급할 뿐 그 파일을 커버하지 않는 태스크는 회수 좌석이 아니다"

    def test_task_covering_absent_file_and_mentioning_pr_is_a_recovery_seat(
        self, monkeypatch, tmp_path
    ):
        backlog = self._backlog_of(
            _task(
                "HARN-99-recover-josa",
                notes="#858의 josa.py를 이 태스크가 이식한다",
                paths=["src/backend/x/**"],
            )
        )
        monkeypatch.setattr(_store, "load_backlog", lambda root: (backlog, []))
        ids, err = _mod.recovery_task_ids(tmp_path, 858, ["src/backend/x/josa.py"])
        assert err == ""
        assert ids == ["HARN-99-recover-josa"]

    def test_task_covering_path_without_mentioning_pr_is_not_a_seat(self, monkeypatch, tmp_path):
        """paths가 겹쳐도 PR 언급이 없으면 이 PR의 회수 좌석이라 볼 근거가 없다."""
        backlog = self._backlog_of(
            _task(
                "HARN-50-unrelated-refactor", notes="무관한 리팩터 작업", paths=["src/backend/x/**"]
            )
        )
        monkeypatch.setattr(_store, "load_backlog", lambda root: (backlog, []))
        ids, err = _mod.recovery_task_ids(tmp_path, 858, ["src/backend/x/josa.py"])
        assert ids == []

    def test_task_without_paths_declared_is_never_a_seat(self, monkeypatch, tmp_path):
        backlog = self._backlog_of(_task("HARN-51-no-paths", notes="#858 언급"))
        monkeypatch.setattr(_store, "load_backlog", lambda root: (backlog, []))
        ids, err = _mod.recovery_task_ids(tmp_path, 858, ["src/backend/x/josa.py"])
        assert ids == []

    def test_backlog_load_failure_is_measurement_failure_not_empty(self, monkeypatch, tmp_path):
        def boom(root):
            raise RuntimeError("disk full")

        monkeypatch.setattr(_store, "load_backlog", boom)
        ids, err = _mod.recovery_task_ids(tmp_path, 858, ["src/backend/x/josa.py"])
        assert ids is None
        assert "RuntimeError" in err


class TestMainMeasurementFailureIsNotSafe:
    """조회 실패는 절대 exit 0(안전)이 아니다 — 측정 실패를 통과로 위장하지 않는다."""

    def test_no_token_pr_lookup_fails_exits_nonzero(self, monkeypatch, capsys):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        rc = main(["owner/repo", "858"])
        assert rc != 0
        out = capsys.readouterr().out
        assert "PR #858 조회 실패" in out

    def test_pr_not_found_exits_nonzero(self, monkeypatch, capsys):
        monkeypatch.setattr(_mod, "_get", lambda path: (None, "CurlExitError(22): 404"))
        rc = main(["owner/repo", "999999"])
        assert rc != 0

    def test_malformed_pr_number_exits_nonzero(self, capsys):
        rc = main(["owner/repo", "not-a-number"])
        assert rc != 0
        assert "정수가 아니다" in capsys.readouterr().err

    def test_trunk_absent_measurement_failure_exits_nonzero_not_safe(self, monkeypatch, capsys):
        monkeypatch.setattr(
            _mod,
            "_get",
            lambda path: ({"head": {"sha": "abc123"}, "state": "open", "labels": []}, ""),
        )
        monkeypatch.setattr(
            _mod, "trunk_absent_files", lambda root, pr: (None, "TimeoutExpired: git fetch")
        )
        rc = main(["owner/repo", "858"])
        assert rc != 0
        out = capsys.readouterr().out
        assert "trunk 부재 파일 측정 실패" in out

    def test_recovery_lookup_failure_exits_nonzero_not_safe(self, monkeypatch, capsys):
        monkeypatch.setattr(
            _mod,
            "_get",
            lambda path: ({"head": {"sha": "abc123"}, "state": "open", "labels": []}, ""),
        )
        monkeypatch.setattr(_mod, "trunk_absent_files", lambda root, pr: (["src/x.py"], ""))
        monkeypatch.setattr(
            _mod,
            "recovery_task_ids",
            lambda root, pr, absent: (None, "ImportError: store 로드 실패"),
        )
        rc = main(["owner/repo", "858"])
        assert rc != 0
        out = capsys.readouterr().out
        assert "회수 좌석 조회 실패" in out

    def test_recovery_lookup_not_called_when_nothing_absent(self, monkeypatch, capsys):
        """부재 파일이 0건이면 회수 좌석 조회 자체를 시도하지 않는다(무의미한 호출 생략)."""
        monkeypatch.setattr(
            _mod,
            "_get",
            lambda path: ({"head": {"sha": "abc123"}, "state": "open", "labels": []}, ""),
        )
        monkeypatch.setattr(_mod, "trunk_absent_files", lambda root, pr: ([], ""))

        def _boom(root, pr, absent):
            raise AssertionError("absent 0건인데 recovery_task_ids가 호출됐다")

        monkeypatch.setattr(_mod, "recovery_task_ids", _boom)
        rc = main(["owner/repo", "846"])
        assert rc == 0


class TestMainEndToEnd:
    """조회 3단계(PR·trunk 대조·회수 좌석)가 전부 성공했을 때만 exit code가 `decide`를 따른다."""

    def _stub_pr(self, monkeypatch, labels: list[str]):
        monkeypatch.setattr(
            _mod,
            "_get",
            lambda path: (
                {
                    "head": {"sha": "abc123"},
                    "state": "open",
                    "title": "예시",
                    "labels": [{"name": n} for n in labels],
                },
                "",
            ),
        )

    def test_safe_when_no_absent_files(self, monkeypatch, capsys):
        self._stub_pr(monkeypatch, ["eos-close"])
        monkeypatch.setattr(_mod, "trunk_absent_files", lambda root, pr: ([], ""))
        monkeypatch.setattr(_mod, "recovery_task_ids", lambda root, pr, absent: ([], ""))
        rc = main(["owner/repo", "846"])
        assert rc == 0
        assert "닫아도 안전" in capsys.readouterr().out

    def test_blocked_when_absent_files_and_no_recovery(self, monkeypatch, capsys):
        self._stub_pr(monkeypatch, ["eos-close"])
        monkeypatch.setattr(_mod, "trunk_absent_files", lambda root, pr: (["src/x.py"] * 28, ""))
        monkeypatch.setattr(_mod, "recovery_task_ids", lambda root, pr, absent: ([], ""))
        rc = main(["owner/repo", "858"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "지금 닫지 말 것" in out

    def test_safe_when_absent_files_but_recovery_seat_registered(self, monkeypatch, capsys):
        self._stub_pr(monkeypatch, ["eos-rework"])
        monkeypatch.setattr(_mod, "trunk_absent_files", lambda root, pr: (["src/x.py"], ""))
        monkeypatch.setattr(
            _mod, "recovery_task_ids", lambda root, pr, absent: (["HARN-99-recovered-x"], "")
        )
        rc = main(["owner/repo", "882"])
        assert rc == 0
        assert "닫아도 안전" in capsys.readouterr().out

    def test_disposal_label_is_printed_as_context(self, monkeypatch, capsys):
        self._stub_pr(monkeypatch, ["eos-postpone"])
        monkeypatch.setattr(_mod, "trunk_absent_files", lambda root, pr: ([], ""))
        monkeypatch.setattr(_mod, "recovery_task_ids", lambda root, pr, absent: ([], ""))
        main(["owner/repo", "844"])
        assert "eos-postpone" in capsys.readouterr().out

    def test_missing_args_exits_nonzero(self, capsys):
        rc = main(["owner/repo"])
        assert rc != 0
