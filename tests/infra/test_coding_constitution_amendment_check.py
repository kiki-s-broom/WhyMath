"""R0-02 (제11조 ②) 개정 기록 동반 검사 — scripts/constitution/check_amendment.py 계약 동결.

진짜 임시 git 저장소를 만들어 시나리오별로 종료 코드(0 통과 / 1 위반 / 2 측정 불가)를 확인한다.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "constitution" / "check_amendment.py"

VALID_RECORD = (
    "# A0004 — 시험 개정\n\n"
    "- 채택일: 2026-10-05\n\n"
    "## 사유\n시험용 개정 기록이다. 사유를 충분히 적어 빈 껍데기가 아님을 보인다.\n\n"
    "## 영향 범위\n규칙 한 건의 단계를 바꾼다. 영향 범위를 충분히 적어 둔다. 영향 범위 설명을 길게 이어 적는다. 영향 범위 설명을 길게 이어 적는다. 영향 범위 설명을 길게 이어 적는다. 영향 범위 설명을 길게 이어 적는다. 영향 범위 설명을 길게 이어 적는다. \n"
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
    )


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, msg: str = "c") -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """main 에 기존 헌법 파일 + 개정 기록 A0001 + 판례 1건이 있는 저장소. HEAD 는 feature 브랜치."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _write(tmp_path, "constitution/CONSTITUTION.md", "# 헌법\n")
    _write(tmp_path, "constitution/rules.yaml", "rules: []\n")
    _write(tmp_path, "constitution/STAGE", "2\n")
    _write(
        tmp_path, "constitution/amendments/A0001_first.md", VALID_RECORD.replace("A0004", "A0001")
    )
    _write(tmp_path, "constitution/precedents/P0001_x.md", "# P0001\n")
    _write(tmp_path, "src/app.py", "x = 1\n")
    _commit(tmp_path, "base")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    return tmp_path


def _run(repo: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--base", "main", *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_no_constitution_change_passes(repo: Path) -> None:
    _write(repo, "src/app.py", "x = 2\n")
    _commit(repo)
    assert _run(repo).returncode == 0


def test_no_changes_at_all_passes(repo: Path) -> None:
    assert _run(repo).returncode == 0


@pytest.mark.parametrize(
    "rel", ["constitution/rules.yaml", "constitution/STAGE", "constitution/CONSTITUTION.md"]
)
def test_core_file_change_without_record_fails(repo: Path, rel: str) -> None:
    _write(repo, rel, "바뀜\n")
    _commit(repo)
    res = _run(repo)
    assert res.returncode == 1
    assert "개정 기록이 없다" in res.stderr


def test_unlisted_new_constitution_file_without_record_fails(repo: Path) -> None:
    _write(repo, "constitution/new_thing.yaml", "a: 1\n")
    _commit(repo)
    assert _run(repo).returncode == 1


def test_core_change_with_valid_record_passes(repo: Path) -> None:
    _write(repo, "constitution/rules.yaml", "rules: [a]\n")
    _write(repo, "constitution/amendments/A0004_t.md", VALID_RECORD)
    _commit(repo)
    res = _run(repo)
    assert res.returncode == 0, res.stderr
    assert "A0004_t.md" in res.stdout


def test_record_split_across_commits_passes(repo: Path) -> None:
    """공통 조상 기준이라 같은 PR 의 다른 커밋에 기록이 있어도 통과."""
    _write(repo, "constitution/rules.yaml", "rules: [a]\n")
    _commit(repo, "c1")
    _write(repo, "constitution/amendments/A0004_t.md", VALID_RECORD)
    _commit(repo, "c2")
    assert _run(repo).returncode == 0


def test_record_only_addition_passes(repo: Path) -> None:
    _write(repo, "constitution/amendments/A0004_t.md", VALID_RECORD)
    _commit(repo)
    assert _run(repo).returncode == 0


def test_new_precedent_only_passes(repo: Path) -> None:
    _write(repo, "constitution/precedents/P0002_y.md", "# P0002\n")
    _commit(repo)
    assert _run(repo).returncode == 0


def test_edit_existing_amendment_without_new_record_fails(repo: Path) -> None:
    _write(repo, "constitution/amendments/A0001_first.md", "# A0001\n조용히 고침\n")
    _commit(repo)
    assert _run(repo).returncode == 1


def test_delete_existing_amendment_fails(repo: Path) -> None:
    _git(repo, "rm", "-q", "constitution/amendments/A0001_first.md")
    _commit(repo)
    assert _run(repo).returncode == 1


def test_edit_existing_precedent_fails(repo: Path) -> None:
    _write(repo, "constitution/precedents/P0001_x.md", "# P0001\n고침\n")
    _commit(repo)
    assert _run(repo).returncode == 1


def test_rename_of_amendment_counts_as_delete_plus_add_fails(repo: Path) -> None:
    """이름 바꿈은 삭제(개정 대상)+추가로 본다 — 새 기록 없이는 통과 못 한다."""
    _git(repo, "mv", "constitution/amendments/A0001_first.md", "constitution/amendments/A0001_b.md")
    _commit(repo)
    assert _run(repo).returncode == 1


@pytest.mark.parametrize(
    ("name", "text", "needle"),
    [
        ("notes.md", VALID_RECORD, "A####_*.md"),
        ("A0004_t.md", VALID_RECORD.replace("A0004", "A0009"), "파일명과 제목"),
        ("A0004_t.md", "# A0004\n2026-10-05\n", "빈 껍데기"),
        ("A0004_t.md", VALID_RECORD.replace("2026-10-05", "날짜없음"), "날짜"),
        ("A0004_t.md", "본문만 있고 제목 없음. " * 20 + "2026-10-05", "제목(#)이 아님"),
        ("A0001_dup.md", VALID_RECORD.replace("A0004", "A0001"), "번호 충돌"),
    ],
)
def test_placeholder_records_fail(repo: Path, name: str, text: str, needle: str) -> None:
    _write(repo, "constitution/rules.yaml", "rules: [a]\n")
    _write(repo, f"constitution/amendments/{name}", text)
    _commit(repo)
    res = _run(repo)
    assert res.returncode == 1
    assert needle in res.stderr


def test_non_record_file_beside_a_valid_record_is_ignored(repo: Path) -> None:
    """README.md 같은 기록 아닌 파일이 같이 들어와도 정상 기록이 있으면 통과한다."""
    _write(repo, "constitution/rules.yaml", "rules: [a]\n")
    _write(repo, "constitution/amendments/A0004_t.md", VALID_RECORD)
    _write(repo, "constitution/amendments/README.md", "설명\n")
    _commit(repo)
    res = _run(repo)
    assert res.returncode == 0, res.stderr
    assert "A0004_t.md" in res.stdout and "README.md" not in res.stdout


def test_only_non_record_files_fail_and_name_what_was_ignored(repo: Path) -> None:
    _write(repo, "constitution/rules.yaml", "rules: [a]\n")
    _write(repo, "constitution/amendments/README.md", "설명\n")
    _commit(repo)
    res = _run(repo)
    assert res.returncode == 1
    assert "개정 기록이 없다" in res.stderr and "README.md" in res.stderr


def test_invalid_record_beside_ignored_file_is_still_validated(repo: Path) -> None:
    """무시는 이름이 안 맞는 파일에만 — 이름이 맞는 기록은 빈 껍데기면 여전히 거부된다."""
    _write(repo, "constitution/rules.yaml", "rules: [a]\n")
    _write(repo, "constitution/amendments/A0004_t.md", "# A0004\n2026-10-05\n")
    _write(repo, "constitution/amendments/README.md", "설명\n")
    _commit(repo)
    res = _run(repo)
    assert res.returncode == 1
    assert "빈 껍데기" in res.stderr


def test_duplicate_numbers_within_diff_fail(repo: Path) -> None:
    _write(repo, "constitution/rules.yaml", "rules: [a]\n")
    _write(repo, "constitution/amendments/A0004_a.md", VALID_RECORD)
    _write(repo, "constitution/amendments/A0004_b.md", VALID_RECORD)
    _commit(repo)
    res = _run(repo)
    assert res.returncode == 1
    assert "겹친다" in res.stderr


def test_non_monotonic_number_is_allowed(repo: Path) -> None:
    """A0003 이 A0002 보다 먼저 채택된 실사례 — 번호 단조 증가는 요구하지 않는다."""
    _write(repo, "constitution/rules.yaml", "rules: [a]\n")
    _write(repo, "constitution/amendments/A0003_t.md", VALID_RECORD.replace("A0004", "A0003"))
    _commit(repo)
    assert _run(repo).returncode == 0


def test_korean_filenames_are_handled(repo: Path) -> None:
    _write(repo, "constitution/한글 파일.md", "바뀜\n")
    _commit(repo)
    res = _run(repo)
    assert res.returncode == 1
    assert "한글 파일.md" in res.stderr


def test_missing_base_ref_is_measure_failure(repo: Path) -> None:
    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--base", "no-such-ref"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert res.returncode == 2
    assert "측정 불가" in res.stderr


def test_unrelated_history_is_measure_failure(repo: Path) -> None:
    _git(repo, "checkout", "-q", "--orphan", "orphan")
    _commit(repo, "orphan")
    res = _run(repo)
    assert res.returncode == 2


def test_not_a_git_repo_is_measure_failure(tmp_path: Path) -> None:
    assert _run(tmp_path).returncode == 2


def test_env_base_ref_is_honoured(repo: Path) -> None:
    _write(repo, "constitution/STAGE", "3\n")
    _commit(repo)
    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env={"CONSTITUTION_BASE_REF": "main", "PATH": __import__("os").environ["PATH"]},
    )
    assert res.returncode == 1


def test_head_option_selects_commit(repo: Path) -> None:
    _write(repo, "constitution/STAGE", "3\n")
    _commit(repo)
    assert _run(repo, "--head", "main").returncode == 0
    assert _run(repo, "--head", "HEAD").returncode == 1


def test_script_is_importable_without_side_effects() -> None:
    spec = importlib.util.spec_from_file_location("check_amendment_probe", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_amendment_probe"] = mod
    spec.loader.exec_module(mod)
    assert mod.MIN_RECORD_CHARS == 200


def test_base_advanced_after_fork_is_not_blamed_on_branch(repo: Path) -> None:
    """main 이 분기 뒤에 헌법을 (정당하게) 바꿔도, 그 변경을 내 브랜치 탓으로 돌리지 않는다."""
    _write(repo, "src/app.py", "x = 3\n")
    _commit(repo, "feature work")
    _git(repo, "checkout", "-q", "main")
    _write(repo, "constitution/STAGE", "3\n")
    _write(repo, "constitution/amendments/A0004_t.md", VALID_RECORD)
    _commit(repo, "main advanced")
    _git(repo, "checkout", "-q", "feature")
    res = _run(repo)
    assert res.returncode == 0, res.stderr
    assert "변경 1건" in res.stdout


def test_ci_runs_registered_commands_verbatim() -> None:
    """R0-02·R1-02 의 등록 명령이 harness-integrity 잡에 글자 그대로 있다(연결 판정과 실행이 같은 것)."""
    import yaml

    root = Path(__file__).resolve().parents[2]
    wf = yaml.safe_load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    runs = [s.get("run", "") for s in wf["jobs"]["harness-integrity"]["steps"]]
    assert "python scripts/constitution/check_amendment.py" in runs
    assert "python scripts/constitution/pipeline_check.py --downstream standards" in runs
