"""CONST-03 P1 — 위헌 심사(audit.py) 판정 논리 정정(⑥ ⓐ~ⓔ)의 변별력 동결.

왜 이 테스트가 있는가
--------------------
코딩 헌법 제10조 ①은 "L4·L5 규칙은 집행 장치가 존재하고 **연결되어** 있어야 효력을 가진다"이다.
원본 audit.py 는 '연결'을 워크플로 파일 전체 텍스트의 **부분 문자열 일치**로 판정했고, 그 판정이
전역 STAGE 에 걸려 있었다. 그 결과 ① 주석·echo 속 문자열이 연결로 셈 ② 디렉터리 단위로 도는 CI 에서
파일 단위 pytest run 이 구조적으로 미연결 ③ 규칙 자신의 단계와 어긋남 ④ L4 는 미연결에 침묵
⑤ 실행이 저장소 루트 cwd·180초·셸 문자열로 고정이었다(이식 정본 §4 '심사 도구의 판정 논리').

검증 계약 (절마다 '그 절이 없으면 통과해 버리는 입력'을 픽스처에 둔다)
------------------------------------------------------------------
ⓐ 규칙 자신의 단계  : 2단계 규칙이 STAGE=2 에서 CI 에 없으면 미연결(옛 판정은 STAGE<3 이라 침묵·통과)
ⓑ 명령 단위 대조    : 주석·echo·step name·heredoc·look-alike 경로·다른 작업 디렉터리는 연결이 아니다
ⓒ 파일 vs 디렉터리  : 디렉터리 pytest 는 그 아래 파일 규칙을 연결한다 — 단 -k/-m/--deselect/--ignore/
                      노드 ID 로 일부만 도는 스텝은 연결이 아니다(모른다 ≠ 아니다)
ⓓ 실행 설정         : timeout_sec·cwd·shell 은 규칙이 정한다. 형식 오류는 심사 불가(2), 셸 연산자는
                      shell: true 없이는 실행하지 않고, python/pytest 는 지금 파이썬으로 고정한다
ⓔ L4/L5 대칭        : 파일 없음·미연결은 L4·L5 모두 차단, 실행 실패만 L5 차단/L4 경고
부수: 스캔 0건은 통과가 아니다 · 읽지 못한 워크플로는 detail 에 남는다 · 래퍼(래칫) 연결은 AST 로 본다

합성 저장소(tmp)를 쓰는 이유
---------------------------
헌법(rules.yaml)은 Kiki 가 개정한다(제11조). 저장소의 현재 규칙·CI 에 기대는 판정은 정상 개정 PR 을
red 로 만든다 — 그래서 판정은 합성 등록부·합성 워크플로로 재고, 저장소 현재 상태는 래칫 테스트
(test_coding_constitution_audit_wiring.py ③)가 맡는다. 단 래칫이 audit.py 를 서브프로세스로 부른다는
사실만은 **실제 audit_ratchet.py 사본**으로 확인한다(R4-01 간접 연결이 그 코드에 기대므로).
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_AUDIT = _REPO / "scripts" / "constitution" / "audit.py"
_RATCHET = _REPO / "scripts" / "constitution" / "audit_ratchet.py"

_OK_SCRIPT = "print('ok')\n"
_PASS_TEST = "def test_ok():\n    assert True\n"


# ── 합성 저장소 ────────────────────────────────────────────────────────────


def _rule(
    rid: str = "RT-01",
    *,
    level: str = "L5",
    stage: int = 3,
    check: str = "tools/check.py",
    run: str | None = "python tools/check.py",
    **extra: object,
) -> dict:
    rule: dict = {
        "id": rid,
        "article": "제10조",
        "chapter": 0,
        "axis": "경계",
        "statement": "합성 규칙",
        "level": level,
        "stage": stage,
        "check": check,
    }
    if run is not None:
        rule["run"] = run
    rule.update(extra)
    return rule


def _wf(steps: list[dict], *, job_wd: str | None = None, wf_wd: str | None = None) -> str:
    job: dict = {"runs-on": "ubuntu-latest", "steps": steps}
    if job_wd:
        job["defaults"] = {"run": {"working-directory": job_wd}}
    doc: dict = {"name": "ci", "jobs": {"j": job}}
    if wf_wd:
        doc["defaults"] = {"run": {"working-directory": wf_wd}}
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)


def _step(run: str, *, name: str = "s", wd: str | None = None) -> dict:
    step: dict = {"name": name, "run": run}
    if wd:
        step["working-directory"] = wd
    return step


def _make_repo(
    tmp_path: Path,
    rules: list[dict],
    *,
    stage: int = 3,
    workflows: dict[str, str] | None = None,
    files: dict[str, str] | None = None,
    precommit: str | None = None,
) -> Path:
    root = tmp_path / "repo"
    (root / "constitution").mkdir(parents=True)
    (root / "constitution" / "rules.yaml").write_text(
        yaml.safe_dump({"version": "test", "rules": rules, "sources": []}, allow_unicode=True),
        encoding="utf-8",
    )
    (root / "constitution" / "STAGE").write_text(f"{stage}\n", encoding="utf-8")
    (root / "scripts" / "constitution").mkdir(parents=True)
    shutil.copy2(_AUDIT, root / "scripts" / "constitution" / "audit.py")
    for rel, text in (files or {}).items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    if workflows is not None:
        (root / ".github" / "workflows").mkdir(parents=True)
        for name, text in workflows.items():
            (root / ".github" / "workflows" / name).write_text(text, encoding="utf-8")
    if precommit is not None:
        (root / ".pre-commit-config.yaml").write_text(precommit, encoding="utf-8")
    return root


def _audit(root: Path, *args: str, bare_path: bool = False) -> tuple[int, dict[str, dict], str]:
    """audit.py 를 합성 저장소에서 실행하고 (종료코드, {규칙ID: 결과}, stderr) 를 돌려준다."""
    out = root / "audit_out.json"
    env = {"PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"}
    env["PATH"] = "" if bare_path else os.environ.get("PATH", "")
    proc = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "constitution" / "audit.py"),
            "--json",
            str(out),
            *args,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env=env,
    )
    results: dict[str, dict] = {}
    if out.exists():
        results = {r["rule_id"]: r for r in json.loads(out.read_text(encoding="utf-8"))["results"]}
    return proc.returncode, results, proc.stderr


def _status(root: Path, rid: str = "RT-01", *extra: str) -> dict:
    _, results, stderr = _audit(root, "--no-run", *extra)
    assert rid in results, f"{rid} 결과가 없다 — stderr: {stderr}"
    return results[rid]


def _one_rule_repo(
    tmp_path: Path,
    ci_steps: list[dict] | None,
    *,
    rule: dict | None = None,
    stage: int = 3,
    job_wd: str | None = None,
    wf_wd: str | None = None,
    files: dict[str, str] | None = None,
) -> Path:
    base_files = {"tools/check.py": _OK_SCRIPT, "tests/infra/test_a.py": _PASS_TEST}
    base_files.update(files or {})
    workflows = None if ci_steps is None else {"ci.yml": _wf(ci_steps, job_wd=job_wd, wf_wd=wf_wd)}
    return _make_repo(
        tmp_path, [rule or _rule()], stage=stage, workflows=workflows, files=base_files
    )


# ── ⓐ 규칙 자신의 단계 ─────────────────────────────────────────────────────


def test_a_rule_stage_2_is_judged_at_stage_2_even_below_global_stage_3(tmp_path: Path) -> None:
    """옛 판정은 `stage >= 3` 일 때만 연결을 봐서 2단계 규칙이 CI 에 없어도 '통과'였다."""
    root = _one_rule_repo(tmp_path, [_step("echo hi")], rule=_rule(stage=2), stage=2)
    result = _status(root)
    assert result["status"] == "미연결" and result["blocking"] is True


def test_a_control_wired_stage_2_rule_passes(tmp_path: Path) -> None:
    root = _one_rule_repo(tmp_path, [_step("python tools/check.py")], rule=_rule(stage=2), stage=2)
    result = _status(root)
    assert result["status"] == "통과" and result["blocking"] is False


def test_a_rule_not_yet_introduced_is_scheduled_not_judged(tmp_path: Path) -> None:
    """도입 단계 전의 규칙은 연결을 따지지 않는다 — 과잉 수정(전건 미연결) 방지용 대조군."""
    root = _one_rule_repo(tmp_path, [_step("echo hi")], rule=_rule(stage=4), stage=3)
    assert _status(root)["status"] == "예정"


# ── ⓑ 명령 단위 대조 ───────────────────────────────────────────────────────

_NOT_WIRED = {
    "주석 속 문자열": [_step("# python tools/check.py\necho hi")],
    "echo 인자": [_step('echo "python tools/check.py"')],
    "step name": [_step("echo hi", name="python tools/check.py")],
    "비슷한 파일명(.pyc)": [_step("python tools/check.pyc")],
    "비슷한 파일명(.py.bak)": [_step("python tools/check.py.bak")],
    "heredoc 본문": [_step("cat > x.sh <<'EOF'\npython tools/check.py\nEOF")],
    "다른 작업 디렉터리": [_step("python tools/check.py", wd="sub")],
    "cd 로 다른 디렉터리": [_step("cd sub && python tools/check.py")],
    "다른 스크립트": [_step("python tools/other.py")],
}


@pytest.mark.parametrize("label", list(_NOT_WIRED))
def test_b_text_that_is_not_a_command_is_not_wiring(tmp_path: Path, label: str) -> None:
    root = _one_rule_repo(tmp_path, _NOT_WIRED[label])
    result = _status(root)
    assert result["status"] == "미연결", (label, result)
    assert result["blocking"] is True


def test_b_other_workflow_comment_is_not_wiring(tmp_path: Path) -> None:
    root = _make_repo(
        tmp_path,
        [_rule()],
        workflows={
            "ci.yml": _wf([_step("echo hi")]),
            "other.yml": "# python tools/check.py\n" + _wf([_step("echo bye")]),
        },
        files={"tools/check.py": _OK_SCRIPT},
    )
    assert _status(root)["status"] == "미연결"


_WIRED = {
    "정확히 같은 명령": [_step("python tools/check.py")],
    "python3 표기": [_step("python3 tools/check.py")],
    "python3.12 표기": [_step("python3.12 tools/check.py")],
    "CI 가 인자를 더 붙임": [_step("python3 tools/check.py --strict")],
    "환경변수 접두": [_step("FOO=1 python tools/check.py")],
    "./ 접두": [_step("python ./tools/check.py")],
    "&& 뒤": [_step("echo a && python tools/check.py")],
    "if 조건": [_step("if python tools/check.py; then echo ok; fi")],
    "줄잇기": [_step("python tools/check.py \\\n  --strict")],
    "파이프 앞": [_step("python tools/check.py | tee out.txt")],
    "리다이렉트": [_step("python tools/check.py 2>&1")],
    "cd . 뒤": [_step("cd . && python tools/check.py")],
    "파이프 뒤": [_step("echo x | python tools/check.py")],
    "세미콜론 뒤": [_step("echo a; python tools/check.py")],
    "서브셸": [_step("(python tools/check.py)")],
    "|| 뒤": [_step("false || python tools/check.py")],
}


@pytest.mark.parametrize("label", list(_WIRED))
def test_b_control_real_command_is_wiring(tmp_path: Path, label: str) -> None:
    root = _one_rule_repo(tmp_path, _WIRED[label])
    result = _status(root)
    assert result["status"] == "통과", (label, result)


def test_b_rule_more_specific_than_ci_is_not_wired(tmp_path: Path) -> None:
    """규칙이 `--downstream standards` 를 요구하는데 CI 는 인자 없이 돌린다 → 그 검사는 안 돈다."""
    root = _one_rule_repo(
        tmp_path,
        [_step("python tools/check.py")],
        rule=_rule(run="python tools/check.py --downstream standards"),
    )
    assert _status(root)["status"] == "미연결"


def test_b_rule_cwd_must_match_ci_workdir(tmp_path: Path) -> None:
    """같은 명령이라도 작업 디렉터리가 다르면 다른 파일을 가리킨다."""
    files = {"sub/tools/check.py": _OK_SCRIPT}
    wired = _one_rule_repo(
        tmp_path / "w",
        [_step("python tools/check.py", wd="sub")],
        rule=_rule(cwd="sub"),
        files=files,
    )
    assert _status(wired)["status"] == "통과"
    unwired = _one_rule_repo(
        tmp_path / "u", [_step("python tools/check.py")], rule=_rule(cwd="sub"), files=files
    )
    assert _status(unwired)["status"] == "미연결"


def test_b_job_level_working_directory_is_honored(tmp_path: Path) -> None:
    root = _one_rule_repo(
        tmp_path,
        [_step("python tools/check.py")],
        rule=_rule(cwd="sub"),
        job_wd="sub",
        files={"sub/tools/check.py": _OK_SCRIPT},
    )
    assert _status(root)["status"] == "통과"


def test_b_workflow_level_working_directory_is_honored(tmp_path: Path) -> None:
    root = _one_rule_repo(
        tmp_path,
        [_step("python tools/check.py")],
        rule=_rule(cwd="sub"),
        wf_wd="sub",
        files={"sub/tools/check.py": _OK_SCRIPT},
    )
    assert _status(root)["status"] == "통과"


def test_b_step_working_directory_overrides_job_and_workflow_defaults(tmp_path: Path) -> None:
    """step > job > workflow 우선순위: 스텝이 `.` 으로 되돌리면 규칙의 cwd(sub)와 맞지 않는다."""
    root = _one_rule_repo(
        tmp_path,
        [_step("python tools/check.py", wd=".")],
        rule=_rule(cwd="sub"),
        job_wd="sub",
        files={"sub/tools/check.py": _OK_SCRIPT},
    )
    assert _status(root)["status"] == "미연결"


def test_b_cd_in_ci_matches_rule_cwd(tmp_path: Path) -> None:
    root = _one_rule_repo(
        tmp_path,
        [_step("cd sub && python tools/check.py")],
        rule=_rule(cwd="sub"),
        files={"sub/tools/check.py": _OK_SCRIPT},
    )
    assert _status(root)["status"] == "통과"


def test_b_operator_run_requires_every_part_wired(tmp_path: Path) -> None:
    """`a && b` 규칙은 두 명령이 모두 CI 에 있어야 연결이다(하나만 있으면 반쪽 집행)."""
    rule = _rule(run="python tools/a.py && python tools/b.py", shell=True)
    files = {"tools/a.py": _OK_SCRIPT, "tools/b.py": _OK_SCRIPT, "tools/check.py": _OK_SCRIPT}
    both = _one_rule_repo(
        tmp_path / "both",
        [_step("python tools/a.py"), _step("python tools/b.py")],
        rule=rule,
        files=files,
    )
    assert _status(both)["status"] == "통과"
    half = _one_rule_repo(tmp_path / "half", [_step("python tools/a.py")], rule=rule, files=files)
    assert _status(half)["status"] == "미연결"


# ── ⓒ 파일 단위 pytest vs 디렉터리 단위 CI ─────────────────────────────────

_PYTEST_RULE = _rule(check="tests/infra/test_a.py", run="pytest -q tests/infra/test_a.py", stage=3)

_PYTEST_WIRED = {
    "디렉터리": ("pytest tests/infra", None),
    "python -m 표기": ("python -m pytest tests/infra -q", None),
    "상위 디렉터리": ("pytest tests", None),
    "파일 그대로": ("pytest tests/infra/test_a.py", None),
    "값 받는 옵션들": ("pytest --cov=pkg --cov-report=xml -n 4 -p no:randomly tests/infra", None),
    "파이프·리다이렉트": ("pytest tests/infra 2>&1 | tee out.txt", None),
    "줄잇기": ("pytest \\\n  tests/infra \\\n  -q", None),
    "cd 후 상대경로": ("cd sub && pytest ../tests/infra", None),
    "working-directory 후 상대경로": ("pytest ../tests/infra", "sub"),
}


@pytest.mark.parametrize("label", list(_PYTEST_WIRED))
def test_c_directory_level_pytest_wires_a_file_rule(tmp_path: Path, label: str) -> None:
    run, wd = _PYTEST_WIRED[label]
    root = _one_rule_repo(tmp_path, [_step(run, wd=wd)], rule=_PYTEST_RULE)
    result = _status(root)
    assert result["status"] == "통과", (label, result)


_PYTEST_NOT_WIRED = {
    "다른 디렉터리": ("pytest tests/other", None),
    "ignore=파일": ("pytest tests/infra --ignore=tests/infra/test_a.py", None),
    "ignore 파일(분리)": ("pytest tests/infra --ignore tests/infra/test_a.py", None),
    "ignore 디렉터리": ("pytest tests/infra --ignore=tests/infra", None),
    "-k 필터": ("pytest tests/infra -k foo", None),
    "-k 붙여쓰기": ("pytest tests/infra -kfoo", None),
    "-m 필터": ("pytest tests/infra -m 'not slow'", None),
    "deselect": ("pytest tests/infra --deselect tests/infra/test_a.py::test_ok", None),
    "ignore-glob": ("pytest tests/infra --ignore-glob='*_a.py'", None),
    "노드 ID 만": ("pytest tests/infra/test_a.py::test_ok", None),
    "경로 없음": ("pytest", None),
    "맨 --cov 가 경로를 값으로 삼킴": ("pytest --cov tests/infra", None),
    "접두만 같은 디렉터리": ("pytest tests/infr", None),
    "루트 밖 상대경로": ("pytest ../tests/infra", None),
    "echo 인자": ("echo pytest tests/infra", None),
    "다른 working-directory": ("pytest tests/infra", "sub"),
}


@pytest.mark.parametrize("label", list(_PYTEST_NOT_WIRED))
def test_c_partial_or_misdirected_pytest_is_not_wiring(tmp_path: Path, label: str) -> None:
    run, wd = _PYTEST_NOT_WIRED[label]
    root = _one_rule_repo(tmp_path, [_step(run, wd=wd)], rule=_PYTEST_RULE)
    result = _status(root)
    assert result["status"] == "미연결", (label, result)
    assert result["blocking"] is True


def test_c_unwired_detail_names_why(tmp_path: Path) -> None:
    root = _one_rule_repo(
        tmp_path, [_step("pytest tests/infra -k foo", name="필터 스텝")], rule=_PYTEST_RULE
    )
    detail = _status(root)["detail"]
    assert "필터 스텝" in detail and "-k" in detail


@pytest.mark.parametrize(
    "run",
    [
        "pytest -q -n 4 tests/infra/test_a.py",
        "pytest --cov-report xml tests/infra/test_a.py",
        "pytest -p no:randomly -c pytest.ini tests/infra/test_a.py",
        "pytest --maxfail 1 tests/infra/test_a.py",
    ],
)
def test_c_rule_side_option_values_are_not_mistaken_for_target_paths(
    tmp_path: Path, run: str
) -> None:
    """규칙의 `-n 4` 에서 '4' 를 대상 경로로 읽으면 CI 가 디렉터리를 돌려도 미연결이 된다."""
    rule = _rule(check="tests/infra/test_a.py", run=run)
    root = _one_rule_repo(tmp_path, [_step("pytest tests/infra")], rule=rule)
    assert _status(root)["status"] == "통과", run


def test_c_rule_own_filter_does_not_matter_when_ci_runs_unfiltered(tmp_path: Path) -> None:
    rule = _rule(check="tests/infra/test_a.py", run="pytest -q tests/infra/test_a.py -k ok")
    root = _one_rule_repo(tmp_path, [_step("pytest tests/infra")], rule=rule)
    assert _status(root)["status"] == "통과"


def test_c_pytest_rule_matching_ci_command_prefix_without_paths(tmp_path: Path) -> None:
    """경로 없는 pytest 규칙(`pytest -q -m unit`)은 CI 가 같은 명령으로 시작할 때만 연결이다."""
    rule = _rule(check="tools/check.py", run="pytest -q -m unit")
    wired = _one_rule_repo(tmp_path / "w", [_step("pytest -q -m unit --disable-socket")], rule=rule)
    assert _status(wired)["status"] == "통과"
    unwired = _one_rule_repo(tmp_path / "u", [_step("pytest -q")], rule=rule)
    assert _status(unwired)["status"] == "미연결"


# ── ⓓ 실행 설정 ────────────────────────────────────────────────────────────


def test_d_timeout_sec_is_per_rule(tmp_path: Path) -> None:
    sleeper = "import time\ntime.sleep(60)\n"
    rule = _rule(check="tools/sleeper.py", run="python tools/sleeper.py", timeout_sec=1)
    root = _one_rule_repo(
        tmp_path, [_step("python tools/sleeper.py")], rule=rule, files={"tools/sleeper.py": sleeper}
    )
    started = time.monotonic()
    rc, results, _ = _audit(root)
    elapsed = time.monotonic() - started
    result = results["RT-01"]
    assert result["status"] == "위반" and "1초 시간 초과" in result["detail"], result
    assert result["blocking"] is True and rc == 1
    assert elapsed < 30, f"timeout_sec=1 이 무시됐다(기본 180초 대기): {elapsed:.1f}s"


def test_d_cwd_is_per_rule(tmp_path: Path) -> None:
    where = "from pathlib import Path\nPath('marker.txt').write_text(Path.cwd().name)\n"
    rule = _rule(check="sub/where.py", run="python where.py", cwd="sub")
    root = _one_rule_repo(
        tmp_path,
        [_step("python where.py", wd="sub")],
        rule=rule,
        files={"sub/where.py": where},
    )
    rc, results, _ = _audit(root)
    assert results["RT-01"]["status"] == "통과" and rc == 0, results
    assert (root / "sub" / "marker.txt").read_text() == "sub"
    assert not (root / "marker.txt").exists(), "cwd 가 저장소 루트로 고정돼 있다"


def test_d_missing_cwd_directory_is_a_violation_not_a_crash(tmp_path: Path) -> None:
    rule = _rule(run="python tools/check.py", cwd="no_such_dir")
    root = _one_rule_repo(tmp_path, [_step("python tools/check.py", wd="no_such_dir")], rule=rule)
    rc, results, _ = _audit(root)
    assert (
        results["RT-01"]["status"] == "위반" and "cwd 디렉터리가 없음" in results["RT-01"]["detail"]
    )
    assert rc == 1


def test_d_cwd_symlink_escaping_repo_is_refused_and_not_executed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "mark.py").write_text("from pathlib import Path\nPath('ran.txt').write_text('x')\n")
    rule = _rule(check="tools/check.py", run="python mark.py", cwd="escape")
    root = _one_rule_repo(tmp_path, [_step("python mark.py", wd="escape")], rule=rule)
    try:
        (root / "escape").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("이 환경은 심볼릭 링크를 만들 수 없다")
    _, results, _ = _audit(root)
    assert results["RT-01"]["status"] == "위반" and "저장소 밖" in results["RT-01"]["detail"]
    assert not (outside / "ran.txt").exists(), "저장소 밖 디렉터리에서 검사가 실행됐다"


_BAD_FIELDS = {
    "cwd ..": {"cwd": ".."},
    "cwd 안의 ..": {"cwd": "a/../../b"},
    "cwd 절대경로": {"cwd": "/etc"},
    "cwd 드라이브": {"cwd": "C:x"},
    "cwd 빈 문자열": {"cwd": " "},
    "cwd 숫자": {"cwd": 3},
    "timeout 0": {"timeout_sec": 0},
    "timeout 문자열": {"timeout_sec": "10"},
    "timeout bool": {"timeout_sec": True},
    "timeout 상한 초과": {"timeout_sec": 1801},
    "shell 문자열": {"shell": "yes"},
}


@pytest.mark.parametrize("label", list(_BAD_FIELDS))
def test_d_malformed_exec_fields_make_the_audit_impossible(tmp_path: Path, label: str) -> None:
    root = _one_rule_repo(
        tmp_path, [_step("python tools/check.py")], rule=_rule(**_BAD_FIELDS[label])
    )
    rc, _, stderr = _audit(root, "--no-run")
    assert rc == 2 and "심사 불가" in stderr, (label, rc, stderr)


@pytest.mark.parametrize(
    "fields",
    [{"timeout_sec": 1800}, {"timeout_sec": 5}, {"shell": False}, {"cwd": "tools"}],
)
def test_d_control_wellformed_exec_fields_are_accepted(tmp_path: Path, fields: dict) -> None:
    rule = _rule(**fields)
    if "cwd" in fields:
        rule["run"] = "python check.py"
    root = _one_rule_repo(tmp_path, [_step("python tools/check.py")], rule=rule)
    rc, _, stderr = _audit(root, "--no-run")
    assert rc != 2, (fields, stderr)


def test_d_shell_operators_are_refused_without_shell_true(tmp_path: Path) -> None:
    files = {
        "tools/a.py": "from pathlib import Path\nPath('ran_a.txt').write_text('x')\n",
        "tools/b.py": "from pathlib import Path\nPath('ran_b.txt').write_text('x')\n",
        "tools/check.py": _OK_SCRIPT,
    }
    steps = [_step("python tools/a.py"), _step("python tools/b.py")]
    run = "python tools/a.py && python tools/b.py"
    refused = _one_rule_repo(tmp_path / "r", steps, rule=_rule(run=run), files=files)
    rc, results, _ = _audit(refused)
    assert results["RT-01"]["status"] == "위반" and "shell: true" in results["RT-01"]["detail"]
    assert rc == 1 and not (refused / "ran_a.txt").exists(), "연산자 run 이 셸 없이 실행됐다"
    allowed = _one_rule_repo(tmp_path / "a", steps, rule=_rule(run=run, shell=True), files=files)
    rc, results, _ = _audit(allowed)
    assert results["RT-01"]["status"] == "통과" and rc == 0, results
    assert (allowed / "ran_a.txt").exists() and (allowed / "ran_b.txt").exists()


def test_d_python_and_pytest_run_on_the_current_interpreter_even_without_path(
    tmp_path: Path,
) -> None:
    """윈도우처럼 PATH 에 python3·pytest 가 없거나 다른 인터프리터에 걸려 있어도 같은 파이썬으로 돈다."""
    rule = _rule(check="tests/infra/test_a.py", run="pytest -q tests/infra/test_a.py")
    root = _one_rule_repo(tmp_path / "p", [_step("pytest tests/infra")], rule=rule)
    rc, results, _ = _audit(root, bare_path=True)
    assert results["RT-01"]["status"] == "통과" and rc == 0, results
    rule3 = _rule(run="python3 tools/check.py")
    root3 = _one_rule_repo(tmp_path / "q", [_step("python3 tools/check.py")], rule=rule3)
    rc, results, _ = _audit(root3, bare_path=True)
    assert results["RT-01"]["status"] == "통과" and rc == 0, results


def test_d_non_python_tools_still_run_through_argv(tmp_path: Path) -> None:
    """python/pytest 가 아닌 도구(여기선 인터프리터 자신을 argv 로)는 셸 없이 그대로 실행된다."""
    rule = _rule(check="tools/check.py", run=f"{sys.executable} tools/check.py")
    root = _one_rule_repo(tmp_path, [_step(f"{sys.executable} tools/check.py")], rule=rule)
    rc, results, _ = _audit(root)
    assert results["RT-01"]["status"] == "통과" and rc == 0, results


# ── ⓔ L4/L5 대칭 ───────────────────────────────────────────────────────────


def test_e_l4_unwired_is_blocking_like_l5(tmp_path: Path) -> None:
    """옛 판정은 L5 만 미연결을 보고 L4 는 침묵 통과였다."""
    root = _one_rule_repo(tmp_path, [_step("echo hi")], rule=_rule(level="L4"))
    result = _status(root)
    assert result["status"] == "미연결" and result["blocking"] is True


def test_e_l4_missing_check_file_is_blocking(tmp_path: Path) -> None:
    root = _one_rule_repo(tmp_path, [_step("echo hi")], rule=_rule(level="L4", check="tools/no.py"))
    result = _status(root)
    assert result["status"] == "집행 장치 없음" and result["blocking"] is True


def test_e_l4_failing_check_warns_but_does_not_block(tmp_path: Path) -> None:
    rule = _rule(level="L4", check="tools/fail.py", run="python tools/fail.py")
    root = _one_rule_repo(
        tmp_path,
        [_step("python tools/fail.py")],
        rule=rule,
        files={"tools/fail.py": "raise SystemExit(1)\n"},
    )
    rc, results, _ = _audit(root)
    assert results["RT-01"]["status"] == "경고" and results["RT-01"]["blocking"] is False
    assert rc == 0


def test_e_l5_failing_check_is_a_blocking_violation(tmp_path: Path) -> None:
    rule = _rule(level="L5", check="tools/fail.py", run="python tools/fail.py")
    root = _one_rule_repo(
        tmp_path,
        [_step("python tools/fail.py")],
        rule=rule,
        files={"tools/fail.py": "raise SystemExit(1)\n"},
    )
    rc, results, _ = _audit(root)
    assert results["RT-01"]["status"] == "위반" and results["RT-01"]["blocking"] is True
    assert rc == 1


# ── 스캔 0건 · 읽지 못한 워크플로 ──────────────────────────────────────────


@pytest.mark.parametrize("variant", ["워크플로 디렉터리 없음", "run 스텝 없음"])
def test_zero_scan_is_not_a_pass(tmp_path: Path, variant: str) -> None:
    if variant == "워크플로 디렉터리 없음":
        root = _one_rule_repo(tmp_path, None)
    else:
        root = _one_rule_repo(tmp_path, [{"name": "uses only", "uses": "actions/checkout@v4"}])
    result = _status(root)
    assert result["status"] == "미연결" and "스캔 0건" in result["detail"], result


def test_unreadable_workflow_is_reported_in_detail_not_swallowed(tmp_path: Path) -> None:
    root = _make_repo(
        tmp_path,
        [_rule()],
        workflows={"ci.yml": "jobs: [\n"},
        files={"tools/check.py": _OK_SCRIPT},
    )
    result = _status(root)
    assert result["status"] == "미연결"
    assert "ci.yml 읽기 실패(" in result["detail"] and "스캔 0건" in result["detail"]


def test_one_broken_workflow_does_not_hide_the_good_one(tmp_path: Path) -> None:
    root = _make_repo(
        tmp_path,
        [_rule()],
        workflows={"ci.yml": _wf([_step("python tools/check.py")]), "bad.yml": "jobs: [\n"},
        files={"tools/check.py": _OK_SCRIPT},
    )
    assert _status(root)["status"] == "통과"


def test_unparsed_script_lines_are_reported(tmp_path: Path) -> None:
    root = _one_rule_repo(tmp_path, [_step("echo 'unbalanced\npython other.py", name="깨진 스텝")])
    detail = _status(root)["detail"]
    assert "깨진 스텝" in detail and "읽지 못함" in detail


# ── pre-commit ─────────────────────────────────────────────────────────────

_PRECOMMIT = yaml.safe_dump(
    {
        "repos": [
            {
                "repo": "local",
                "hooks": [{"id": "gitleaks", "name": "g", "entry": "echo", "language": "system"}],
            }
        ]
    }
)


def test_precommit_hook_id_wires_a_pre_commit_run_rule(tmp_path: Path) -> None:
    rule = _rule(check=".pre-commit-config.yaml", run="pre-commit run gitleaks --all-files")
    wired = _make_repo(
        tmp_path / "w", [rule], workflows={"ci.yml": _wf([_step("echo")])}, precommit=_PRECOMMIT
    )
    assert _status(wired)["status"] == "통과"
    other = _rule(check=".pre-commit-config.yaml", run="pre-commit run other-hook --all-files")
    unwired = _make_repo(
        tmp_path / "u", [other], workflows={"ci.yml": _wf([_step("echo")])}, precommit=_PRECOMMIT
    )
    assert _status(unwired)["status"] == "미연결"


# ── R4-01: 래퍼(래칫)를 거친 간접 연결 ─────────────────────────────────────

_R401 = _rule(
    "R4-01",
    stage=1,
    check="scripts/audit_target.py",
    run="python scripts/audit_target.py --sources-only",
)
_WRAPPER_OK = (
    '"""래퍼."""\n'
    "import subprocess\nimport sys\nfrom pathlib import Path\n\n"
    "ROOT = Path(__file__).resolve().parents[1]\n"
    'TARGET = ROOT / "scripts" / "audit_target.py"\n'
    "subprocess.run([sys.executable, str(TARGET)])\n"
)


def _r401_repo(tmp_path: Path, ci_run: str, wrapper: str | None) -> Path:
    files = {"scripts/audit_target.py": _OK_SCRIPT}
    if wrapper is not None:
        files["scripts/ratchet.py"] = wrapper
    return _make_repo(
        tmp_path, [_R401], stage=1, workflows={"ci.yml": _wf([_step(ci_run)])}, files=files
    )


def test_r401_wrapper_that_subprocesses_the_target_wires_it(tmp_path: Path) -> None:
    result = _status(_r401_repo(tmp_path, "python3 scripts/ratchet.py", _WRAPPER_OK), "R4-01")
    assert result["status"] == "통과" and "간접 연결" in result["detail"]
    assert "ratchet.py" in result["detail"]


def test_r401_direct_ci_step_wires_it(tmp_path: Path) -> None:
    result = _status(_r401_repo(tmp_path, "python scripts/audit_target.py", None), "R4-01")
    assert result["status"] == "통과" and "직접" in result["detail"]


_WRAPPER_BAD = {
    "docstring 이 경로 그 자체": (
        '"""scripts/audit_target.py"""\nimport subprocess\nsubprocess.run(["echo", "x"])\n'
    ),
    "문장형 docstring": (
        '"""audit_target.py 를 부른다고 적어 둔 설명."""\nimport subprocess\n'
        'subprocess.run(["echo", "x"])\n'
    ),
    "주석에만 언급": (
        "import subprocess\n# scripts/audit_target.py 를 부른다\n" 'subprocess.run(["echo", "x"])\n'
    ),
    "subprocess 없이 문자열만": 'TARGET = "scripts/audit_target.py"\nprint(TARGET)\n',
    "문법 오류": "import subprocess\nTARGET = 'audit_target.py'\ndef (\n",
}


@pytest.mark.parametrize("label", list(_WRAPPER_BAD))
def test_r401_wrapper_that_only_mentions_the_target_does_not_wire_it(
    tmp_path: Path, label: str
) -> None:
    result = _status(
        _r401_repo(tmp_path, "python3 scripts/ratchet.py", _WRAPPER_BAD[label]), "R4-01"
    )
    assert result["status"] == "미연결", (label, result)


def test_r401_same_basename_in_another_directory_is_not_the_target(tmp_path: Path) -> None:
    root = _r401_repo(tmp_path, "python other/audit_target.py", None)
    (root / "other").mkdir()
    (root / "other" / "audit_target.py").write_text(_OK_SCRIPT, encoding="utf-8")
    assert _status(root, "R4-01")["status"] == "미연결"


def test_r401_wrapper_exists_but_ci_does_not_run_it(tmp_path: Path) -> None:
    result = _status(_r401_repo(tmp_path, "echo hi", _WRAPPER_OK), "R4-01")
    assert result["status"] == "미연결"


def test_r401_real_ratchet_script_is_recognized_as_reaching_audit(tmp_path: Path) -> None:
    """실제 audit_ratchet.py 사본이 audit.py 를 서브프로세스로 부른다는 코드 사실을 동결한다."""
    rule = _rule(
        "R4-01",
        stage=1,
        check="scripts/constitution/audit.py",
        run="python scripts/constitution/audit.py --sources-only",
    )
    root = _make_repo(
        tmp_path,
        [rule],
        stage=1,
        workflows={"ci.yml": _wf([_step("python3 scripts/constitution/audit_ratchet.py")])},
    )
    shutil.copy2(_RATCHET, root / "scripts" / "constitution" / "audit_ratchet.py")
    result = _status(root, "R4-01")
    assert result["status"] == "통과" and "audit_ratchet.py" in result["detail"], result


# ── 파서 단위 ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def audit_mod() -> Iterator[ModuleType]:
    name = "audit_under_test"
    spec = importlib.util.spec_from_file_location(name, _AUDIT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclass(+__future__ annotations)가 모듈을 이름으로 찾는다
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(name, None)


def _cmds(mod: ModuleType, script: str, wd: str = "") -> list[tuple[str, list[str]]]:
    commands, _ = mod.parse_script(script, wd)
    return commands


def test_parse_heredoc_body_is_not_a_command(audit_mod: ModuleType) -> None:
    got = _cmds(audit_mod, "cat > f <<'EOF'\npython x.py\nEOF\npython y.py")
    assert [t[0] for _, t in got] == ["cat", "python"] and got[-1][1] == ["python", "y.py"]


def test_parse_cd_persists_across_lines(audit_mod: ModuleType) -> None:
    got = _cmds(audit_mod, "cd sub && python x.py\npython y.py")
    assert got == [("sub", ["python", "x.py"]), ("sub", ["python", "y.py"])]


def test_parse_comments_blank_lines_and_continuations(audit_mod: ModuleType) -> None:
    got = _cmds(audit_mod, "# 주석\n\npython x.py \\\n  --flag  # 꼬리 주석\n")
    assert got == [("", ["python", "x.py", "--flag"])]


def test_parse_counts_unparseable_lines(audit_mod: ModuleType) -> None:
    commands, unparsed = audit_mod.parse_script("echo 'oops\npython x.py", "")
    assert unparsed == 1 and commands == [("", ["python", "x.py"])]


def test_parse_strips_control_words(audit_mod: ModuleType) -> None:
    assert _cmds(audit_mod, "if python x.py; then echo ok; fi")[0] == ("", ["python", "x.py"])
    assert _cmds(audit_mod, "while python x.py; do echo; done")[0] == ("", ["python", "x.py"])


def test_normalize_tokens(audit_mod: ModuleType) -> None:
    norm = audit_mod.normalize_tokens
    assert norm(["python3.12", "-m", "pytest", "-q"]) == ["pytest", "-q"]
    assert norm(["FOO=1", "BAR=2", "py", "./x.py"]) == ["python", "x.py"]
    assert norm(["python", "-m", "ruff", "check"]) == ["python", "-m", "ruff", "check"]


def test_parse_pytest_options(audit_mod: ModuleType) -> None:
    spec = audit_mod.parse_pytest(["-n", "4", "-k", "a", "--ignore=tests/x", "tests/a", "-q"], "")
    assert spec.paths == ["tests/a"] and spec.ignores == ["tests/x"] and spec.filtered
    spec = audit_mod.parse_pytest(["--cov", "--cov-report", "xml", "tests"], "sub")
    assert spec.paths == ["sub/tests"] and not spec.filtered
    assert audit_mod.parse_pytest(["tests/a.py::t"], "").filtered
