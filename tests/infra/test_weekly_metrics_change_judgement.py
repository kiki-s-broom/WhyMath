"""[OPS-151] weekly-metrics PR 단계의 변경 판정 — 미추적 파일을 보는가 · 0행이면 실패하는가.

왜 이 테스트가 있는가
--------------------
`metrics/weekly.json`은 어느 브랜치에도 커밋된 적이 없는 *미추적* 파일이다. 종전 판정
`git diff --quiet -- <파일>`은 미추적 파일에 항상 exit 0이라 PR 스텝이 매번 "변경 없음"으로
빠졌고, 워크플로는 5회 success인데 산출물은 0회 커밋됐다(침묵 실패). 이 파일은 그 판정을
문면과 **실행** 두 축으로 동결한다 — 문면만 보면 "문자열은 맞는데 경로가 틀려 어떤 상태에서도
빈 출력"인 형태(스텝 working-directory가 src/backend라 `metrics/weekly.json`이 저장소 루트가
아닌 src/backend/metrics/로 해석된다)를 못 잡기 때문이다.

검증 계약 (각 항목은 결함 주입에서 RED가 확인된 것만)
----------------------------------------------------
① PR 스텝에 종전 `git diff --quiet` 판정이 없다.
② 판정은 `git status --porcelain`이며 대상 경로는 `../../metrics/weekly.json` 상대다.
③ 0행 가드(파일 없음·빈 배열 → `exit 1`)가 있다.
④ 실행 축: 스텝 스크립트의 판정 부분을 실제 임시 git 저장소(src/backend 아래에서 실행)에서
   돌려 (가)미추적 (나)수정된 추적 (다)무변경 (마)0행 각각의 종료 코드·출력을 대조한다.
⑤ 변별력: 종전 식 복원·경로 오기·가드 무력화 3종을 주입해 위 검사가 RED가 되는지, 그리고
   주입이 실제로 적용됐는지(`mutated != original`)를 매번 재확인한다.

의도적으로 검증하지 않는 것 (정직한 공백)
--------------------------------------
- `git checkout -b`·`git push`·`gh pr create`·auto-merge 이후 구간은 실행하지 않는다 —
  GitHub API 실호출이 필요하다. 실행 축은 "변경 감지" 출력 직후까지만 본다.
- 첫 실제 산출물 커밋은 다음 cron 또는 workflow_dispatch 실행에서만 확인된다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "weekly-metrics.yml"
_PR_STEP_PREFIX = "PR 생성"
# 이 줄부터는 push·gh 호출 구간이라 실행 축에서 잘라 낸다.
_CUT_MARKER = 'git config user.name "github-actions[bot]"'

_OLD_JUDGEMENT = "if git diff --quiet -- ../../metrics/weekly.json 2>/dev/null; then"


def _load_pr_step_script(workflow_text: str) -> str:
    spec: Any = yaml.safe_load(workflow_text)
    if not isinstance(spec, dict) or not spec.get("jobs"):
        raise AssertionError("weekly-metrics.yml을 읽지 못했거나 jobs가 비었다(위장 통과 금지).")
    scripts: list[str] = []
    for job in spec["jobs"].values():
        for step in job.get("steps", []):
            if str(step.get("name", "")).startswith(_PR_STEP_PREFIX):
                scripts.append(str(step.get("run", "")))
    if len(scripts) != 1:
        raise AssertionError(f"'{_PR_STEP_PREFIX}' 스텝이 {len(scripts)}개다(1개여야 한다).")
    return scripts[0]


def _code_only(script: str) -> str:
    """주석 전용 줄을 뺀 코드 — 설명 주석이 옛 식을 인용해도 위반으로 읽지 않는다."""
    return "\n".join(ln for ln in script.splitlines() if not ln.lstrip().startswith("#"))


def _frozen_violations(raw_script: str) -> list[str]:
    """문면 축 ①②③ — 위반 문장 목록(비면 통과). 주석은 보지 않는다."""
    script = _code_only(raw_script)
    v: list[str] = []
    if "git diff --quiet" in script:
        v.append("종전 `git diff --quiet` 판정이 남아 있다(미추적 파일에 exit 0).")
    if "git status --porcelain" not in script:
        v.append("`git status --porcelain` 판정이 없다.")
    if 'LEDGER="../../metrics/weekly.json"' not in script:
        v.append("대상 경로가 `../../metrics/weekly.json`이 아니다(working-directory=src/backend).")
    if '[ "$ROWS" -eq 0 ]' not in script:
        v.append('0행 가드(`[ "$ROWS" -eq 0 ]`)가 없다.')
    else:
        guard_tail = script.split('[ "$ROWS" -eq 0 ]', 1)[1].split("fi", 1)[0]
        if "exit 1" not in guard_tail:
            v.append("0행 가드가 `exit 1`로 실패하지 않는다(fail-open).")
    return v


def _run_judgement(script: str, tmp_path: Path, state: str) -> subprocess.CompletedProcess[str]:
    """스크립트의 판정 구간만 임시 저장소(src/backend 아래 cwd)에서 실행한다."""
    assert _CUT_MARKER in script, "실행 축의 절단 표지가 사라졌다 — 스크립트 구조가 바뀌었다."
    head = script.split(_CUT_MARKER, 1)[0]
    repo = tmp_path / state
    (repo / "src" / "backend").mkdir(parents=True)
    (repo / "metrics").mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": _path(),
        "HOME": str(tmp_path),
    }

    def git(*a: str) -> None:
        subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, env=env)

    git("init", "-q", ".")
    (repo / "src" / "backend" / "a.txt").write_text("x", encoding="utf-8")
    (repo / "metrics" / "keep.json").write_text("[]", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    ledger = repo / "metrics" / "weekly.json"
    if state == "untracked":
        ledger.write_text('[{"a":1}]\n', encoding="utf-8")
    elif state == "modified":
        ledger.write_text('[{"a":1}]\n', encoding="utf-8")
        git("add", "metrics/weekly.json")
        git("commit", "-q", "-m", "track")
        ledger.write_text('[{"a":1},{"a":2}]\n', encoding="utf-8")
    elif state == "unchanged":
        ledger.write_text('[{"a":1}]\n', encoding="utf-8")
        git("add", "metrics/weekly.json")
        git("commit", "-q", "-m", "track")
    elif state == "empty_array":
        ledger.write_text("[]\n", encoding="utf-8")
    elif state == "missing":
        pass
    else:  # pragma: no cover
        raise AssertionError(state)
    return subprocess.run(
        ["bash", "-c", head],
        cwd=repo / "src" / "backend",
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _path() -> str:
    import os

    return os.environ.get("PATH", "/usr/bin:/bin")


# 상태 → (기대 종료코드, 출력에 반드시 들어갈 문구)
_EXPECT: dict[str, tuple[int, str]] = {
    "untracked": (0, "변경 감지"),
    "modified": (0, "변경 감지"),
    "unchanged": (0, "변경 없음"),
    "empty_array": (1, "0행"),
    "missing": (1, "0행"),
}


def _behavior_violations(script: str, tmp_path: Path) -> list[str]:
    v: list[str] = []
    for state, (code, needle) in _EXPECT.items():
        r = _run_judgement(script, tmp_path, state)
        out = r.stdout + r.stderr
        if r.returncode != code or needle not in out:
            v.append(
                f"{state}: exit={r.returncode}(기대 {code}) · '{needle}' {'있음' if needle in out else '없음'}"
            )
    return v


@pytest.fixture(scope="module")
def pr_script() -> str:
    return _load_pr_step_script(_WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_frozen_text_of_workflow(pr_script: str) -> None:
    assert _frozen_violations(pr_script) == []


def test_behavior_in_real_git_repo(pr_script: str, tmp_path: Path) -> None:
    """미추적도 변경으로 보고, 0행은 실패한다 — 실제 git에서 실행한 결과."""
    assert _behavior_violations(pr_script, tmp_path) == []


def _mutations(script: str) -> dict[str, str]:
    status_line = 'CHANGED=$(git status --porcelain -- "$LEDGER")'
    assert script.count(status_line) == 1
    guard_head = '[ "$ROWS" -eq 0 ]; then'
    assert script.count(guard_head) == 1
    # 0행 가드 블록 안의 첫 `exit 1`만 `exit 0`으로 — 가드가 있어도 잡이 초록인 fail-open.
    k = script.index(guard_head)
    tail = script[k:]
    assert "exit 1" in tail
    return {
        "종전 diff --quiet 판정 복원": script.replace(
            status_line,
            'if git diff --quiet -- "$LEDGER"; then CHANGED=""; else CHANGED="changed"; fi',
            1,
        ),
        "경로 오기(metrics/weekly.json)": script.replace(
            'LEDGER="../../metrics/weekly.json"', 'LEDGER="metrics/weekly.json"', 1
        ),
        "0행 가드 fail-open(exit 1→exit 0)": script[:k] + tail.replace("exit 1", "exit 0", 1),
    }


@pytest.mark.parametrize(
    "name",
    [
        "종전 diff --quiet 판정 복원",
        "경로 오기(metrics/weekly.json)",
        "0행 가드 fail-open(exit 1→exit 0)",
    ],
)
def test_injected_defects_are_detected(pr_script: str, tmp_path: Path, name: str) -> None:
    """⑤ 주입이 실제로 적용됐고(원본과 다름), 문면 또는 실행 축 중 하나가 RED가 된다."""
    mutated = _mutations(pr_script)[name]
    assert mutated != pr_script, f"{name}: 주입이 적용되지 않았다(치환 대상 0건)."
    found = _frozen_violations(mutated) + _behavior_violations(mutated, tmp_path)
    assert found, f"{name}: 결함을 주입했는데 두 축 모두 GREEN — 보호가 위장이다."


def test_old_expression_misjudges_untracked_file(tmp_path: Path) -> None:
    """원 결함의 재현 — 종전 식은 미추적 파일을 '무변경'으로 판정한다(이 저장소 git 기준)."""
    repo = tmp_path / "old"
    (repo / "src" / "backend").mkdir(parents=True)
    (repo / "metrics").mkdir()
    subprocess.run(["git", "init", "-q", "."], cwd=repo, check=True)
    (repo / "metrics" / "weekly.json").write_text("[1]\n", encoding="utf-8")
    old = subprocess.run(
        ["git", "diff", "--quiet", "--", "../../metrics/weekly.json"],
        cwd=repo / "src" / "backend",
        capture_output=True,
        check=False,
    )
    new = subprocess.run(
        ["git", "status", "--porcelain", "--", "../../metrics/weekly.json"],
        cwd=repo / "src" / "backend",
        capture_output=True,
        text=True,
        check=False,
    )
    assert old.returncode == 0  # 종전 식: '무변경'
    assert new.stdout.strip() != ""  # 새 식: 변경으로 본다
