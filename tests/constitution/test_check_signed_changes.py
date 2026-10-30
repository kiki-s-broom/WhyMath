"""헌법 서명 검증(CONST-17) — 실제 SSH 서명 커밋으로 만든 임시 저장소에서 판정을 잰다.

모의(가짜 git 출력)를 쓰지 않는다: 서명 상태 코드 의미(G·U·N)는 실물 `ssh-keygen`+`git` 조합이
내는 값이어야 하고, 그 의미를 잘못 읽는 가드가 이 검사의 가장 큰 위험이기 때문이다.

**변별력**: 정상(대조군)·위반·공격 시나리오를 함께 둔다. 변이 주입(5종)은 가드 사본에 결함을
넣고 시나리오 전체를 다시 돌려 *최소 1건이 기대를 어기는지* 본다 — 주입이 실제로 적용됐는지
(`mutated != original`)도 단언한다.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "constitution" / "check_signed_changes.py"

PASS, FAIL, UNMEASURABLE = 0, 1, 2

_VERIFIER_RUN = "python scripts/constitution/check_signed_changes.py"
_CI_YML = f"""\
name: CI
on:
  pull_request:
    branches: [main]
jobs:
  other-job:
    runs-on: ubuntu-latest
    steps:
      - run: echo hello
  harness-integrity:
    runs-on: ubuntu-latest
    steps:
      - name: 검증
        run: {_VERIFIER_RUN}
"""


def _load(path: Path, name: str = "check_signed_changes_under_test") -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclass 가 모듈을 이름으로 찾는다
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _isolated_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """전역 git 설정(샌드박스·개발 머신의 자동 서명 등)이 시나리오를 오염시키지 못하게 막는다."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    for key, value in {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }.items():
        monkeypatch.setenv(key, value)


def _require_tools() -> None:
    # 도구가 없으면 건너뛰지 않고 실패한다 — 스캔 0건 통과는 위장이다(CLAUDE.md '실패 주입')
    assert shutil.which("ssh-keygen"), "ssh-keygen 이 없다 — 이 테스트는 실물 서명이 필요하다"
    assert shutil.which("git"), "git 이 없다"


class World:
    """임시 저장소 + 키 2개(kiki·other). main 에 기준을 만들고 feat 가지에서 시나리오를 쌓는다."""

    def __init__(self, root: Path) -> None:
        _require_tools()
        self.repo = root / "repo"
        self.keys = root / "keys"
        self.repo.mkdir(parents=True)
        self.keys.mkdir(parents=True)
        for name in ("kiki", "other"):
            subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", f"{name}@test",
                 "-f", str(self.keys / name)],
                check=True,
            )  # fmt: skip
        self.git("init", "-q", "-b", "main")

    # ── 도구 ──
    def git(self, *args: str, config: tuple[str, ...] = ()) -> str:
        cmd = ["git", "-C", str(self.repo)]
        for item in config:
            cmd += ["-c", item]
        proc = subprocess.run([*cmd, *args], capture_output=True, text=True, encoding="utf-8")
        assert proc.returncode == 0, f"git {' '.join(args)}: {proc.stderr}"
        return proc.stdout

    def pubkey_line(self, name: str) -> str:
        key = (self.keys / f"{name}.pub").read_text(encoding="utf-8").split()
        return f"{name}@test {key[0]} {key[1]}\n"

    def write(self, files: dict[str, str | None]) -> None:
        for rel, content in files.items():
            path = self.repo / rel
            if content is None:
                path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def commit(self, files: dict[str, str | None], msg: str, key: str | None = None) -> str:
        self.write(files)
        self.git("add", "-A")
        if key is None:
            config: tuple[str, ...] = ("commit.gpgsign=false",)
            self.git("commit", "-q", "-m", msg, config=config)
        else:
            config = (
                "gpg.format=ssh",
                "gpg.ssh.program=ssh-keygen",
                f"user.signingkey={self.keys / (key + '.pub')}",
            )
            self.git("commit", "-q", "-S", "-m", msg, config=config)
        return self.git("rev-parse", "HEAD").strip()

    def base(self, *, signers: str | None = "kiki", extra: dict[str, str | None] | None = None):
        """main 위의 기준 커밋. signers=None → 미무장, '' → 빈 파일, 'kiki' → kiki 키 등록."""
        files: dict[str, str | None] = {
            "constitution/rules.yaml": "rules: []\n",
            "constitution/STAGE": "2\n",
            "docs/x.md": "x\n",
            ".github/workflows/ci.yml": _CI_YML,
            "scripts/constitution/check_signed_changes.py": "# verifier\n",
        }
        if signers == "kiki":
            files["constitution_signers/allowed_signers"] = self.pubkey_line("kiki")
        elif signers is not None:
            files["constitution_signers/allowed_signers"] = signers
        files.update(extra or {})
        self.commit(files, "base")
        self.git("checkout", "-q", "-b", "feat")

    def run(self, event: str = "pull_request") -> int:
        mod = _load(_SCRIPT)
        return run_module(mod, self.repo, event)[0]


def run_module(mod: ModuleType, repo: Path, event: str = "pull_request") -> tuple[int, str]:
    try:
        return mod.check(repo, "main", "HEAD", event)
    except mod.MeasureError as exc:
        return UNMEASURABLE, str(exc)


# ── 시나리오: (이름, 구성 함수, 기대 종료 코드) ────────────────────────────────
Scenario = tuple[str, Callable[[World], None], int]


def _s_plain_unsigned_nonprotected(w: World) -> None:
    w.base()
    w.commit({"docs/x.md": "y\n"}, "문서만")


def _s_signed_constitution(w: World) -> None:
    w.base()
    w.commit({"constitution/STAGE": "3\n"}, "헌법 개정", key="kiki")


def _s_unsigned_constitution(w: World) -> None:
    w.base()
    w.commit({"constitution/STAGE": "3\n"}, "헌법 개정")


def _s_other_key_constitution(w: World) -> None:
    w.base()
    w.commit({"constitution/STAGE": "3\n"}, "헌법 개정", key="other")


def _s_signed_then_unsigned_touch(w: World) -> None:
    w.base()
    w.commit({"constitution/STAGE": "3\n"}, "서명된 개정", key="kiki")
    w.commit({"constitution/STAGE": "9\n"}, "서명 없이 덧쓰기")


def _s_signed_then_unsigned_other_file(w: World) -> None:
    w.base()
    w.commit({"constitution/STAGE": "3\n"}, "서명된 개정", key="kiki")
    w.commit({"docs/x.md": "z\n"}, "서명 없는 무관한 변경")


def _s_unsigned_deletion(w: World) -> None:
    w.base()
    w.commit({"constitution/STAGE": None}, "헌법 삭제")


def _s_attacker_adds_own_key(w: World) -> None:
    """공격: PR 이 자기 키를 서명자 목록에 넣고 그 키로 서명한다. 기준 트리 목록만 믿어야 막힌다."""
    w.base()
    both = w.pubkey_line("kiki") + w.pubkey_line("other")
    w.commit(
        {"constitution_signers/allowed_signers": both, "constitution/STAGE": "3\n"},
        "내 키 등록 + 헌법 개정",
        key="other",
    )


def _s_rotation_by_existing_key(w: World) -> None:
    w.base()
    both = w.pubkey_line("kiki") + w.pubkey_line("other")
    w.commit({"constitution_signers/allowed_signers": both}, "키 추가", key="kiki")


def _s_unsigned_signers_edit(w: World) -> None:
    w.base()
    both = w.pubkey_line("kiki") + w.pubkey_line("other")
    w.commit({"constitution_signers/allowed_signers": both}, "서명 없는 키 추가")


def _s_unsigned_verifier_edit(w: World) -> None:
    w.base()
    w.commit({"scripts/constitution/check_signed_changes.py": "# weakened\n"}, "검증기 수정")


def _s_unarmed_unsigned_change(w: World) -> None:
    w.base(signers=None)
    w.commit({"constitution/STAGE": "3\n"}, "미무장 중 변경")


def _s_empty_signers_file(w: World) -> None:
    w.base(signers="# 주석만 있다\n")
    w.commit({"constitution/STAGE": "3\n"}, "빈 목록에서 변경")


def _s_clean_merge_of_main(w: World) -> None:
    w.base()
    w.commit({"constitution/STAGE": "3\n"}, "서명된 개정", key="kiki")
    w.git("checkout", "-q", "main")
    w.commit(
        {"docs/y.md": "y\n", "constitution/STAGE": "2\n", "constitution/NEW": "n\n"}, "main 진행"
    )
    w.git("checkout", "-q", "feat")
    w.git("merge", "-q", "--no-ff", "-m", "main 병합", "main", config=("commit.gpgsign=false",))


def _s_evil_merge(w: World) -> None:
    """병합 커밋이 양쪽 부모와 다른 헌법 내용을 끼워 넣는다(충돌 해소 위장)."""
    w.base()
    w.commit({"docs/x.md": "feat\n"}, "feat 변경")
    w.git("checkout", "-q", "main")
    w.commit({"docs/y.md": "y\n"}, "main 진행")
    w.git("checkout", "-q", "feat")
    w.git("merge", "-q", "--no-ff", "--no-commit", "main", config=("commit.gpgsign=false",))
    w.write({"constitution/STAGE": "evil\n"})
    w.git("add", "-A")
    w.git("commit", "-q", "-m", "병합", config=("commit.gpgsign=false",))


def _ci(text: str) -> dict[str, str | None]:
    return {".github/workflows/ci.yml": text}


def _s_ci_other_job_edit(w: World) -> None:
    w.base()
    w.commit(_ci(_CI_YML.replace("echo hello", "echo bye")), "다른 잡 수정")


def _s_ci_remove_step(w: World) -> None:
    w.base()
    w.commit(
        _ci(_CI_YML.replace(f"      - name: 검증\n        run: {_VERIFIER_RUN}\n", "")), "스텝 삭제"
    )


def _s_ci_step_signed_removal(w: World) -> None:
    w.base()
    removed = _CI_YML.replace(f"      - name: 검증\n        run: {_VERIFIER_RUN}\n", "")
    w.commit(_ci(removed), "서명된 스텝 삭제", key="kiki")


def _s_ci_trigger_paths_ignore(w: World) -> None:
    w.base()
    edited = _CI_YML.replace(
        "    branches: [main]\n", "    branches: [main]\n    paths-ignore: ['constitution/**']\n"
    )
    w.commit(_ci(edited), "트리거에 paths-ignore")


def _s_ci_job_if_false(w: World) -> None:
    w.base()
    edited = _CI_YML.replace("  harness-integrity:\n", "  harness-integrity:\n    if: false\n")
    w.commit(_ci(edited), "잡 비활성")


def _s_ci_step_run_changed(w: World) -> None:
    w.base()
    edited = _CI_YML.replace(_VERIFIER_RUN, _VERIFIER_RUN + " || true")
    w.commit(_ci(edited), "검증 스텝 실패 무시")


def _s_ci_garbage(w: World) -> None:
    w.base()
    w.commit(_ci("jobs: [unclosed\n  bad: : :\n"), "ci.yml 깨뜨림")


SCENARIOS: list[Scenario] = [
    ("비보호 경로만 서명 없이 변경", _s_plain_unsigned_nonprotected, PASS),
    ("헌법을 Kiki 서명으로 개정", _s_signed_constitution, PASS),
    ("헌법을 서명 없이 개정", _s_unsigned_constitution, FAIL),
    ("헌법을 목록 밖 키로 서명", _s_other_key_constitution, FAIL),
    ("서명된 개정 뒤 서명 없이 덧쓰기", _s_signed_then_unsigned_touch, FAIL),
    ("서명된 개정 뒤 서명 없는 무관한 변경", _s_signed_then_unsigned_other_file, PASS),
    ("헌법 파일을 서명 없이 삭제", _s_unsigned_deletion, FAIL),
    ("공격: PR 이 자기 키를 등록하고 그 키로 서명", _s_attacker_adds_own_key, FAIL),
    ("기존 키 서명으로 키 추가(교체 경로)", _s_rotation_by_existing_key, PASS),
    ("서명자 목록을 서명 없이 수정", _s_unsigned_signers_edit, FAIL),
    ("검증기 자신을 서명 없이 수정", _s_unsigned_verifier_edit, FAIL),
    ("미무장(목록 파일 없음): 서명 없는 헌법 변경", _s_unarmed_unsigned_change, PASS),
    ("목록 파일은 있으나 유효한 키가 없음", _s_empty_signers_file, UNMEASURABLE),
    ("main 병합(깨끗한 병합 — main 쪽 헌법 변경 포함)", _s_clean_merge_of_main, PASS),
    ("병합 커밋이 헌법 내용을 끼워 넣음(evil merge)", _s_evil_merge, FAIL),
    ("ci.yml 다른 잡만 수정", _s_ci_other_job_edit, PASS),
    ("ci.yml 검증 스텝 삭제(서명 없음)", _s_ci_remove_step, FAIL),
    ("ci.yml 검증 스텝 삭제(Kiki 서명)", _s_ci_step_signed_removal, PASS),
    ("ci.yml 트리거에 paths-ignore 추가", _s_ci_trigger_paths_ignore, FAIL),
    ("ci.yml 검증 잡에 if: false", _s_ci_job_if_false, FAIL),
    ("ci.yml 검증 스텝에 || true", _s_ci_step_run_changed, FAIL),
    ("ci.yml 해석 불가(모른다 ≠ 아니다)", _s_ci_garbage, FAIL),
]


def _run_scenario(tmp_path: Path, build: Callable[[World], None], mod: ModuleType) -> int:
    world = World(tmp_path)
    build(world)
    return run_module(mod, world.repo)[0]


@pytest.mark.parametrize(("name", "build", "expected"), SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_scenario(tmp_path: Path, name: str, build: Callable[[World], None], expected: int) -> None:
    assert _run_scenario(tmp_path, build, _load(_SCRIPT)) == expected, name


def test_scenarios_are_two_sided() -> None:
    codes = {s[2] for s in SCENARIOS}
    assert codes == {PASS, FAIL, UNMEASURABLE}, "통과·위반·측정불가가 모두 있어야 변별력이 성립한다"
    assert sum(1 for s in SCENARIOS if s[2] == PASS) >= 6, "통과(대조군) 시나리오가 너무 적다"


# ── 이벤트·측정 불가·출력 ─────────────────────────────────────────────────────


def test_merge_group_event_is_not_judged(tmp_path: Path) -> None:
    world = World(tmp_path)
    _s_unsigned_constitution(world)
    assert world.run("pull_request") == FAIL
    assert world.run("merge_group") == PASS  # 큐 스쿼시는 GitHub 서명 — PR 시점에 이미 검증됐다
    assert world.run("push") == PASS
    assert world.run("") == FAIL  # 로컬 실행(이벤트 없음)은 판정한다


def test_missing_base_ref_is_unmeasurable(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.base()
    mod = _load(_SCRIPT)
    with pytest.raises(mod.MeasureError):
        mod.check(world.repo, "origin/없는-ref", "HEAD", "pull_request")


def test_missing_ssh_keygen_is_unmeasurable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World(tmp_path)
    _s_signed_constitution(world)
    mod = _load(_SCRIPT)
    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    with pytest.raises(mod.MeasureError):
        mod.check(world.repo, "main", "HEAD", "pull_request")


def test_failure_message_names_commit_status_and_reason(tmp_path: Path) -> None:
    world = World(tmp_path)
    _s_other_key_constitution(world)
    code, message = run_module(_load(_SCRIPT), world.repo)
    assert code == FAIL
    assert "서명 상태 U" in message  # 목록 밖 키는 U 로 보고된다
    assert "constitution/STAGE" in message and "constitution_signing_runbook" in message


def test_unarmed_message_is_loud_and_names_the_gate(tmp_path: Path) -> None:
    world = World(tmp_path)
    _s_unarmed_unsigned_change(world)
    code, message = run_module(_load(_SCRIPT), world.repo)
    assert code == PASS
    assert "미무장" in message and "G-const-signing-key-register" in message


def test_cli_exit_codes_and_streams(tmp_path: Path) -> None:
    """실제 명령행 호출: 위반은 exit 1 + stderr 에 사유, 통과는 exit 0 + stdout."""
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    bad = World(tmp_path / "bad")
    _s_unsigned_constitution(bad)
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--base", "main", "--head", "HEAD",
         "--repo", str(bad.repo), "--event", "pull_request"],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )  # fmt: skip
    assert proc.returncode == FAIL and "서명되지 않은" in proc.stderr and proc.stdout == ""
    ok = World(tmp_path / "ok")
    _s_signed_constitution(ok)
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--base", "main", "--head", "HEAD",
         "--repo", str(ok.repo), "--event", "pull_request"],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )  # fmt: skip
    assert proc.returncode == PASS and "허용된 키로 서명됨" in proc.stdout


# ── 변이 주입: 가드가 실제로 반응한다는 증거 ─────────────────────────────────

MUTATIONS: list[tuple[str, str, str]] = [
    # 좋은 서명 코드를 U(유효하나 목록 밖 키)까지 넓히면 다른 키 서명이 통과한다
    ("서명 코드 확대", 'GOOD_SIGNATURE = "G"', 'GOOD_SIGNATURE = "U"'),
    # 서명자 목록을 PR 헤드에서 읽으면 PR 이 자기 키로 통과한다
    ("목록을 헤드에서 읽음", "load_signers(repo, base_commit)", "load_signers(repo, head_commit)"),
    # 서명자 디렉터리를 보호 목록에서 빼면 목록 수정이 서명 없이 통과한다
    (
        "서명자 디렉터리 보호 제외",
        'PROTECTED_DIRS: tuple[str, ...] = ("constitution/", "constitution_signers/")',
        'PROTECTED_DIRS: tuple[str, ...] = ("constitution/",)',
    ),  # noqa: E501
    # 워크플로 변경 판정을 항상 '아님'으로 바꾸면 검증 스텝 삭제가 통과한다
    ("워크플로 변경 무시", "return bool(after != before)", "return False"),
    # 유효 키 없는 목록을 측정 불가가 아니라 통과로 돌리면 빈 파일로 검사를 끌 수 있다
    (
        "빈 목록 허용",
        '    raise MeasureError(\n        f"{SIGNERS_PATH} 가 기준',
        '    return None\n    raise MeasureError(\n        f"{SIGNERS_PATH} 가 기준',
    ),  # noqa: E501
]


@pytest.mark.parametrize(("label", "old", "new"), MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_mutations_are_caught(tmp_path: Path, label: str, old: str, new: str) -> None:
    original = _SCRIPT.read_text(encoding="utf-8")
    assert (
        original.count(old) == 1
    ), f"{label}: 주입 대상이 정확히 1곳이어야 한다({original.count(old)})"
    mutated = original.replace(old, new)
    assert mutated != original, f"{label}: 주입이 적용되지 않았다"
    mutant_path = tmp_path / "mutant" / "check_signed_changes.py"
    mutant_path.parent.mkdir()
    mutant_path.write_text(mutated, encoding="utf-8")
    mutant = _load(mutant_path, name=f"mutant_{abs(hash(label))}")
    broken = []
    for i, (name, build, expected) in enumerate(SCENARIOS):
        if _run_scenario(tmp_path / f"s{i}", build, mutant) != expected:
            broken.append(name)
    assert broken, f"{label}: 결함을 주입했는데 시나리오가 전건 통과했다 — 가드가 위장이다"
