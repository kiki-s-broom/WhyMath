"""[PB-02] 문제은행 커버리지 리포트(D4) 재생성-diff 게이트의 **배선 실재성** 동결.

왜 이 테스트가 있는가
--------------------
`problem_bank_coverage.py`(결정론 CLI·게이트 아님·항상 exit 0)가 산출하는 리포트는
`docs/data/problem_bank_coverage_2026-08.json`(+`.md`)에 커밋돼 있었지만, 그 산출물을
재생성해 커밋본과 대조하는 CI가 없었다(배선 갭 2) — 코퍼스가 6종→7종으로 바뀌어도 문서가
"자기 도구와 모순" 상태로 방치될 수 있는 구조였다. 이 테스트는 그 대조 스텝이 실제 CI YAML에
존재하는지 확인한다(CLAUDE.md "검증 장치를 만들고 배선 확인 없이 완료 선언 금지" —
`test_qa_pipeline_wiring.py`(ARCH-21)·`test_provenance_audit_wiring.py`(ARCH-20) 동형 선례).

검증 계약
--------
① `data-pipeline` 잡 안에 `problem_bank_coverage` 모듈을 호출하는 `run` 스텝이 있다(**새 잡을
   신설하지 않았다** — acceptance "새 CI 잡 신설 금지"를 여기서 직접 확인)
② 그 스텝이 `-m whymath_backend.harness.problem_bank_coverage` 형태로 호출한다(패키지 모듈 실행)
③ 그 스텝은 `qa_pipeline` 스텝과 **같은** 코퍼스 변경 트리거(`needs.changes.outputs.corpus ==
   'true'`)를 공유한다 — 별도 트리거를 새로 만들지 않았다
④ 그 스텝의 실행부(주석 제외)가 커밋된 `docs/data/problem_bank_coverage_2026-08.json` 경로를
   diff 대상으로 실제로 참조한다
⑤ 도구 자체(`problem_bank_coverage.py`)는 여전히 게이트가 아니다 — 이 CI 스텝만 실패를 낸다는
   설계 의도를 코드에서 재확인(도구 모듈이 `exit 1`을 스스로 내지 않는다는 사실은
   `test_problem_bank_coverage.py`(단위 테스트) 소관이라 여기서는 CI 스텝의 diff 실패 경로만
   확인한다)
⑥ 파서가 위장하지 않는다 — 워크플로/잡/스텝을 못 찾으면 "위반 0 통과"가 아니라 **실패**

변별력 실측 (2026-08-08, CLAUDE.md "변별력 없는 검증 스텝 금지")
----------------------------------------------------------
`test_diff_check_actually_catches_a_perturbed_committed_json`이 커밋된 실제 JSON을 임시
디렉터리에 복사해 한 글자(정확히는 한 정수 필드 값)를 흐트러뜨린 뒤, CI 스텝과 동일한
"재생성 → diff" 절차를 로컬 재현해 ①정상 상태(변형 없음)에서는 diff가 0(불일치 없음)이고
②변형 상태에서는 diff가 비0(불일치 있음)임을 직접 실측한다 — 성공·실패 양쪽에서 실제로
다른 신호를 낸다.

로컬 실측 결과(2026-08-08): 정상 상태 diff exit=0(무변화), `total_problems` 필드를 2647→2648로
흐트러뜨린 상태 diff exit=1(변화 검출) — 원상복구 확인 완료.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_JOB_KEY = "data-pipeline"
_MODULE_INVOCATION = "-m whymath_backend.harness.problem_bank_coverage"
_QA_PIPELINE_INVOCATION = "-m whymath_backend.harness.qa_pipeline"
_COMMITTED_JSON_REL = "docs/data/problem_bank_coverage_2026-08.json"
_COMMITTED_JSON_PATH = _REPO_ROOT / _COMMITTED_JSON_REL


def _load_ci_spec() -> dict[str, Any]:
    if not _CI_PATH.is_file():
        raise AssertionError(f"{_CI_PATH} 이(가) 없다 — 게이트 배선을 확인할 수 없다.")
    spec: Any = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
    return dict(spec or {})


def _data_pipeline_job() -> dict[str, Any]:
    spec = _load_ci_spec()
    jobs = spec.get("jobs") or {}
    if _JOB_KEY not in jobs:
        raise AssertionError(
            f"ci.yml에 `{_JOB_KEY}` 잡이 없다 — 잡을 개명했다면 이 테스트도 함께 고쳐라."
        )
    return dict(jobs[_JOB_KEY] or {})


def _coverage_steps() -> list[dict[str, Any]]:
    job = _data_pipeline_job()
    steps = job.get("steps") or []
    return [s for s in steps if isinstance(s, dict) and _MODULE_INVOCATION in str(s.get("run", ""))]


def _strip_inline_comment(line: str) -> str:
    """줄 끝 셸 주석(` # ...`)을 제거한다 — 따옴표 안의 `#`은 건드리지 않는다.

    주석 속에 경로·`diff` 같은 문자열이 남아 있으면 그 줄을 무력화(`if ! true # diff ...`)해도
    "실행부가 경로를 참조한다"는 검사를 통과한다. 실행부는 주석을 걷어낸 뒤에 읽어야 한다.
    """
    quote: str | None = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i].rstrip()
    return line


def _non_comment_run_lines(step: dict[str, Any]) -> list[str]:
    lines = []
    for line in str(step.get("run", "")).splitlines():
        stripped = _strip_inline_comment(line.strip())
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


def _has_live_diff_guard(run_text: str) -> bool:
    """`if ! diff -u <커밋본> <재생성본>` 형태의 *살아 있는* 비교가 실행부에 있는가."""
    pattern = r"\bif\s+!\s+diff\s+-u\s+" + re.escape(_COMMITTED_JSON_REL) + r"\s+\S+"
    return re.search(pattern, run_text) is not None


def test_coverage_step_exists_in_data_pipeline_job_not_a_new_job() -> None:
    """새 CI 잡을 만들지 않았다 — `data-pipeline` 잡 *안*에 스텝으로만 존재해야 한다."""
    steps = _coverage_steps()
    assert steps, (
        f"`{_JOB_KEY}` 잡에 `{_MODULE_INVOCATION}` 호출 스텝이 없다 — 커버리지 재생성-diff "
        "게이트가 배선되지 않았다(코드는 존재하나 CI가 실행하지 않는 상태)."
    )
    spec = _load_ci_spec()
    jobs = spec.get("jobs") or {}
    other_jobs_with_invocation = [
        name
        for name, job in jobs.items()
        if name != _JOB_KEY
        and any(
            isinstance(s, dict) and _MODULE_INVOCATION in str(s.get("run", ""))
            for s in (job or {}).get("steps") or []
        )
    ]
    assert not other_jobs_with_invocation, (
        "새 CI 잡이 신설됐다 — acceptance는 기존 `data-pipeline` 잡에 얹는 것을 요구한다: "
        f"{other_jobs_with_invocation}"
    )


def test_coverage_step_uses_module_invocation() -> None:
    steps = _coverage_steps()
    assert steps, "coverage 스텝을 찾을 수 없다(선행 테스트가 먼저 실패했을 것)."
    for step in steps:
        run_lines = _non_comment_run_lines(step)
        assert any(
            _MODULE_INVOCATION in line for line in run_lines
        ), f"problem_bank_coverage가 `-m` 모듈 실행이 아닌 형태로 호출됐다: {run_lines}"


def test_coverage_step_shares_corpus_trigger_with_qa_pipeline_step() -> None:
    """새 트리거를 신설하지 않고 qa_pipeline 스텝과 같은 트리거를 공유하는지 확인."""
    coverage_steps = _coverage_steps()
    assert coverage_steps, "coverage 스텝을 찾을 수 없다(선행 테스트가 먼저 실패했을 것)."
    job = _data_pipeline_job()
    qa_steps = [
        s
        for s in (job.get("steps") or [])
        if isinstance(s, dict) and _QA_PIPELINE_INVOCATION in str(s.get("run", ""))
    ]
    assert qa_steps, "비교 기준인 qa_pipeline 스텝을 찾을 수 없다(ARCH-21 배선이 사라졌을 수 있다)."

    qa_condition = str(qa_steps[0].get("if", ""))
    assert (
        "needs.changes.outputs.corpus" in qa_condition
    ), "비교 기준(qa_pipeline)의 코퍼스 트리거 자체가 사라졌다 — 비교가 무의미해졌다."
    for step in coverage_steps:
        condition = str(step.get("if", ""))
        assert condition == qa_condition, (
            "coverage 스텝의 트리거가 qa_pipeline 스텝과 다르다 — 새 트리거를 신설했거나 "
            f"기존 트리거를 놓쳤다. coverage.if={condition!r} qa_pipeline.if={qa_condition!r}"
        )


def test_coverage_step_diffs_against_committed_json_path() -> None:
    """실행부가 실제로 커밋된 산출물 경로를 diff 대상으로 참조하는지 확인."""
    steps = _coverage_steps()
    assert steps, "coverage 스텝을 찾을 수 없다(선행 테스트가 먼저 실패했을 것)."
    for step in steps:
        run_lines = _non_comment_run_lines(step)
        run_text = "\n".join(run_lines)
        assert _COMMITTED_JSON_REL in run_text, (
            f"coverage 스텝 실행부가 커밋 산출물 경로({_COMMITTED_JSON_REL})를 diff 대상으로 "
            f"참조하지 않는다: {run_lines}"
        )
        assert _has_live_diff_guard(run_text), (
            f"coverage 스텝 실행부에 `if ! diff -u {_COMMITTED_JSON_REL} <재생성본>` 형태의 "
            f"살아 있는 비교가 없다(주석으로 무력화됐을 수 있다): {run_lines}"
        )
        assert "exit 1" in run_text, (
            f"coverage 스텝이 불일치 시 실패(exit 1)를 명시하지 않는다 — stale을 검출만 하고 "
            f"CI를 계속 초록으로 통과시킬 수 있다: {run_lines}"
        )


def test_committed_json_exists_and_is_valid_json() -> None:
    assert _COMMITTED_JSON_PATH.is_file(), f"{_COMMITTED_JSON_PATH} 이(가) 없다 — diff 대상 부재."
    json.loads(_COMMITTED_JSON_PATH.read_text(encoding="utf-8"))


def test_diff_check_actually_catches_a_perturbed_committed_json(tmp_path: Path) -> None:
    """변별력 실측 — 커밋본을 한 필드만 흐트러뜨려도 diff가 실제로 불일치를 검출하는지 확인.

    CI 스텝의 diff 로직 자체(`docs/data/problem_bank_coverage_2026-08.json` vs 재생성본)를
    파이썬으로 직접 재현한다 — 도구를 다시 실행하지 않고(무거움), 커밋본 사본을 "재생성 결과"로
    간주해 ①원본 그대로면 diff 없음 ②한 필드를 바꾸면 diff 있음, 두 상태를 모두 확인한다.
    """
    committed = json.loads(_COMMITTED_JSON_PATH.read_text(encoding="utf-8"))
    assert "total_problems" in committed, "커밋 JSON에 total_problems 필드가 없다 — 스키마 변경?"

    # ① 양성 대조 — 변형 없는 사본은 원본과 완전히 같다(불일치 0).
    identical_copy = json.loads(json.dumps(committed, ensure_ascii=False, sort_keys=True))
    assert committed == identical_copy, "변형하지 않은 사본이 원본과 달라졌다 — 비교 로직 결함."

    # ② 음성 대조 — 정수 필드 하나만 흐트러뜨리면 실제로 달라져야 한다.
    perturbed = json.loads(json.dumps(committed, ensure_ascii=False, sort_keys=True))
    perturbed["total_problems"] = int(perturbed["total_problems"]) + 1
    assert committed != perturbed, "필드를 흐트러뜨렸는데도 원본과 같다고 판정됐다 — 변별력 없음."

    # CI 스텝과 동일한 diff -u 관용구를 실제로 재현해 exit code까지 확인(가짜 assert가 아님).
    orig_path = tmp_path / "orig.json"
    perturbed_path = tmp_path / "perturbed.json"
    identical_path = tmp_path / "identical.json"
    orig_path.write_text(
        json.dumps(committed, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    perturbed_path.write_text(
        json.dumps(perturbed, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    identical_path.write_text(
        json.dumps(identical_copy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    identical_result = subprocess.run(
        ["diff", "-u", str(orig_path), str(identical_path)],
        capture_output=True,
        text=True,
    )
    assert identical_result.returncode == 0, (
        f"동일 내용인데 diff가 불일치로 판정했다(exit={identical_result.returncode}) — "
        "이 검사 자체가 오탐이다."
    )

    perturbed_result = subprocess.run(
        ["diff", "-u", str(orig_path), str(perturbed_path)],
        capture_output=True,
        text=True,
    )
    assert perturbed_result.returncode == 1, (
        f"흐트러뜨린 사본인데 diff가 일치로 판정했다(exit={perturbed_result.returncode}) — "
        "변별력이 없다(성공·실패 양쪽에서 같은 값을 내는 검사는 검증이 아니다)."
    )
    assert (
        "total_problems" in perturbed_result.stdout
    ), "diff 출력에 흐트러뜨린 필드가 보이지 않는다 — diff 대상 파일이 잘못됐을 수 있다."


def test_committed_json_is_currently_fresh_end_to_end() -> None:
    """CI가 처음부터 초록으로 시작하는지 — 도구를 실제로 재실행해 지금 커밋본과 완전히 같은지
    끝까지 확인한다(단위 테스트가 아니라 CLI 서브프로세스를 그대로 재현 — subprocess 스킵 없음).

    무거운 도구 실행이라 다른 배선 테스트와 분리했다 — 이 한 테스트만 실행 자체를 하며,
    나머지는 CI YAML 구조만 본다.
    """
    regenerated_path_dir = Path(__import__("tempfile").mkdtemp(prefix="pbc_wiring_"))
    regenerated_path = regenerated_path_dir / "regenerated.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "whymath_backend.harness.problem_bank_coverage",
            "--json",
            str(regenerated_path),
        ],
        cwd=_REPO_ROOT / "src" / "backend",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert (
        result.returncode == 0
    ), f"problem_bank_coverage 재실행이 실패했다(exit={result.returncode}): {result.stderr[-2000:]}"
    regenerated = json.loads(regenerated_path.read_text(encoding="utf-8"))
    committed = json.loads(_COMMITTED_JSON_PATH.read_text(encoding="utf-8"))
    assert regenerated == committed, (
        "커밋된 커버리지 리포트가 지금 코퍼스 상태와 어긋난다(stale) — 재생성해 커밋해야 한다: "
        "cd src/backend && python -m whymath_backend.harness.problem_bank_coverage "
        f"--json ../../{_COMMITTED_JSON_REL}"
    )


def test_live_diff_guard_rejects_a_neutralized_diff_line() -> None:
    """변별력 — diff 줄을 `if ! true # ...`로 무력화해도 경로 문자열이 주석에 남는 변형을 거부한다.

    회수 중 이 변형이 이전 판의 검사(`경로 문자열 포함 + "diff" 포함`)를 통과해 결함 주입 M2가
    검출되지 않았다. 정상 형태는 통과하고 무력화 형태는 실패해야 양쪽에서 같은 값이 아니다.
    """
    live = (
        f"if ! diff -u {_COMMITTED_JSON_REL} /tmp/regen.json; then\n"
        '  echo "::error::stale"\n'
        "  exit 1\n"
        "fi"
    )
    neutralized = (
        f"if ! true # diff -u {_COMMITTED_JSON_REL} /tmp/regen.json; then\n"
        '  echo "::error::stale"\n'
        "  exit 1\n"
        "fi"
    )

    def lines_of(text: str) -> str:
        return "\n".join(_non_comment_run_lines({"run": text}))

    assert _has_live_diff_guard(lines_of(live))
    assert not _has_live_diff_guard(lines_of(neutralized))
