"""[ARCH-21] QA 파이프라인 오케스트레이터의 **배선 실재성** 동결.

왜 이 테스트가 있는가
--------------------
`harness/qa_pipeline.py`가 저장소에 존재하는 것과 CI가 실제로 그것을 실행하는 것은
다르다(CLAUDE.md "검증 장치를 만들고 배선 확인 없이 완료 선언 금지" — `test_provenance_
audit_wiring.py`(ARCH-20) 동형 선례). 이 테스트가 없으면 `ci.yml`에서 이 스텝이 조용히
삭제돼도 아무 신호가 나지 않는다.

검증 계약
--------
① `data-pipeline` 잡에 `qa_pipeline` 모듈을 호출하는 `run` 스텝이 있다
② 그 스텝이 `-m whymath_backend.harness.qa_pipeline` 형태로 호출한다(파일 경로 직접
   실행 같은 변형이 아니라 패키지 모듈 실행)
③ 그 스텝은 코퍼스 변경 시에만 트리거된다(`if: needs.changes.outputs.corpus == 'true'`)
   — "상시 실행 아님"(acceptance) 규정을 기계로 동결
④ 그 스텝은 `working-directory: .`로 레포 루트를 명시한다 — 잡 기본값이
   `src/data-pipeline`이라(오버라이드 없으면 `ModuleNotFoundError`·상대경로 꼬임)
⑤ 파서가 위장하지 않는다 — 워크플로/잡을 못 찾으면 "위반 0 통과"가 아니라 **실패**
⑥ [ARCH-23] 그 스텝에 `continue-on-error`가 없다 — "돌아감≠막음" 방지(제거 *전* 이
   테스트를 구 ci.yml에 대입해 실제 RED가 남을 실측 확인했다)
⑦ [ARCH-23] `changes` 잡의 corpus 필터가 검사기 소스 경로(harness/·
   provenance_audit.py·l3/equivalent/)도 감시한다 — 검사기만 바뀌고 코퍼스는 무변경인
   PR에서 게이트가 안 도는 구멍 방지
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_JOB_KEY = "data-pipeline"
_MODULE_INVOCATION = "-m whymath_backend.harness.qa_pipeline"


def _load_ci_spec() -> dict[str, Any]:
    if not _CI_PATH.is_file():
        raise AssertionError(f"{_CI_PATH} 이(가) 없다 — 게이트 배선을 확인할 수 없다.")
    spec: Any = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
    return dict(spec or {})


def _data_pipeline_job() -> dict[str, Any]:
    spec = _load_ci_spec()
    jobs = (spec.get("jobs")) or {}
    if _JOB_KEY not in jobs:
        raise AssertionError(
            f"ci.yml에 `{_JOB_KEY}` 잡이 없다 — 잡을 개명했다면 이 테스트도 함께 고쳐라."
        )
    return dict(jobs[_JOB_KEY] or {})


def _qa_pipeline_steps() -> list[dict[str, Any]]:
    job = _data_pipeline_job()
    steps = job.get("steps") or []
    matching = [
        s for s in steps if isinstance(s, dict) and _MODULE_INVOCATION in str(s.get("run", ""))
    ]
    return matching


def test_qa_pipeline_step_exists_in_data_pipeline_job() -> None:
    steps = _qa_pipeline_steps()
    assert steps, (
        f"`{_JOB_KEY}` 잡에 `{_MODULE_INVOCATION}` 호출 스텝이 없다 — QA 파이프라인 "
        "오케스트레이터가 CI에서 조용히 빠졌다(코드는 존재하나 실행되지 않는 상태)."
    )


def test_qa_pipeline_step_uses_module_invocation_not_bare_script() -> None:
    """`python path/to/qa_pipeline.py` 같은 변형은 cwd·PYTHONPATH에 취약하다 —
    `-m` 패키지 실행만 인정한다(provenance_audit 스텝과 동일 관용구).

    라인 단위로 검사한다(주석 라인 제외) — 설명 주석에 "qa_pipeline" 단어가 등장하는
    다른 스텝(예: 의존성 설치 스텝의 설명 주석)까지 오탐하지 않게 한다.
    """
    job = _data_pipeline_job()
    steps = job.get("steps") or []
    offending: list[str] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        for line in str(step.get("run", "")).splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "qa_pipeline" in stripped and _MODULE_INVOCATION not in stripped:
                offending.append(stripped)
    assert _qa_pipeline_steps(), "qa_pipeline을 `-m` 모듈 실행으로 언급하는 라인이 하나도 없다."
    assert not offending, f"qa_pipeline이 `-m` 모듈 실행이 아닌 형태로 호출됐다: {offending}"


def test_qa_pipeline_step_is_conditional_on_corpus_changes() -> None:
    """상시 실행이 아니라 코퍼스 변경 시에만 트리거된다(acceptance "상시 실행 아님")."""
    steps = _qa_pipeline_steps()
    assert steps, "qa_pipeline 스텝을 찾을 수 없다(선행 테스트가 먼저 실패했을 것)."
    for step in steps:
        condition = str(step.get("if", ""))
        assert "needs.changes.outputs.corpus" in condition, (
            f"qa_pipeline 스텝에 코퍼스 변경 조건(`if`)이 없다 — 상시 실행 스텝이 되어 "
            f"acceptance('코퍼스 변경 시 트리거, 상시 실행 아님')를 위반한다: {step}"
        )


def test_qa_pipeline_step_overrides_working_directory_to_repo_root() -> None:
    """잡 기본 working-directory(`src/data-pipeline`)에서는 backend 모듈을 못 찾는다 —
    스텝이 레포 루트로 명시 오버라이드해야 한다(GitHub Actions: step > job defaults)."""
    steps = _qa_pipeline_steps()
    assert steps, "qa_pipeline 스텝을 찾을 수 없다(선행 테스트가 먼저 실패했을 것)."
    for step in steps:
        assert step.get("working-directory") == ".", (
            "qa_pipeline 스텝이 레포 루트로 working-directory를 오버라이드하지 않았다 — "
            f"잡 기본값(src/data-pipeline)에서 실행되면 ModuleNotFoundError: {step}"
        )


def test_changes_job_exposes_corpus_output() -> None:
    """`changes` 잡이 `corpus` output을 노출해야 `data-pipeline` 잡의 `if` 조건이 유효하다."""
    spec = _load_ci_spec()
    jobs = spec.get("jobs") or {}
    if "changes" not in jobs:
        raise AssertionError("ci.yml에 `changes` 잡이 없다.")
    outputs = (jobs["changes"] or {}).get("outputs") or {}
    assert "corpus" in outputs, "`changes` 잡에 `corpus` output이 없다 — 코퍼스 변경 감지 미배선."


def test_qa_pipeline_step_is_a_blocking_gate_not_fail_open() -> None:
    """ARCH-23 — continue-on-error로 무력화된 채였던 게이트를 강제 게이트로 전환한다.

    "돌아감≠막음"(ARCH-23 notes) — 위 5개 계약은 스텝이 *실행되는지*만 확인하고 실행
    결과가 PR을 실제로 막는지는 확인하지 않았다. `continue-on-error: true`가 있으면
    exit 1이 나도 잡은 success로 보고된다(상시 fail-open — CLAUDE.md "상시 실패하는
    fail-open 보호를 보호 있음으로 신뢰 금지"). 제거 *전*에 이 테스트를 구 ci.yml에
    대입해 실제 RED가 나는지 실측 확인했다(변별력 실측 의무 — 성공/실패 양쪽 같은
    값이면 위장이므로).
    """
    steps = _qa_pipeline_steps()
    assert steps, "qa_pipeline 스텝을 찾을 수 없다(선행 테스트가 먼저 실패했을 것)."
    for step in steps:
        value = step.get("continue-on-error")
        assert value in (None, False), (
            "qa_pipeline 게이트가 여전히 continue-on-error로 무력화돼 있다 — "
            f"이 게이트는 PR을 실제로 막아야 한다(ARCH-23): {step}"
        )


_CORPUS_FILTER_BLOCK_RE = re.compile(r"grep\s+-qE\s+'(?P<regex>[^']*)'\s*;\s*then\s*\n\s*cp=true")


def _corpus_filter_regex() -> str:
    spec_text = _CI_PATH.read_text(encoding="utf-8")
    match = _CORPUS_FILTER_BLOCK_RE.search(spec_text)
    if not match:
        raise AssertionError("ci.yml에서 corpus(cp) 플래그의 grep -qE 필터 블록을 찾지 못했다.")
    return match.group("regex")


def test_corpus_flag_filter_includes_qa_pipeline_checker_sources() -> None:
    """ARCH-23 — 검사기 소스가 바뀌어도 corpus 플래그가 깨어나야 한다.

    `data/corpus/`만 감시하면, 같은 코퍼스에 *다른 판정 로직*을 적용하는 검사기 자체의
    변경(harness/qa_pipeline.py·ops/provenance_audit.py·l3/equivalent/canonicalize.py 등)이
    이 플래그를 깨우지 못한다 — "검사기가 바뀌어도 안 돌던 구멍"(acceptance).
    """
    pattern = re.compile(_corpus_filter_regex())
    samples = [
        "src/backend/whymath_backend/harness/qa_pipeline.py",
        "src/backend/whymath_backend/ops/provenance_audit.py",
        "src/backend/whymath_backend/l3/equivalent/canonicalize.py",
    ]
    missing = [s for s in samples if not pattern.search(s)]
    assert not missing, (
        f"corpus 플래그 필터가 검사기 소스 경로를 놓친다 — {missing}. 그 경로만 고치는 PR에서 "
        f"qa_pipeline 게이트가 실행되지 않는다. 현재 필터: {pattern.pattern!r}"
    )
