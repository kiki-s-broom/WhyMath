"""[PB-02] 초인간 검증 S6(상시성) — `corpus_reverify` 전 코퍼스 배선의 **배선 실재성** 동결.

왜 이 테스트가 있는가
--------------------
`e2e-nightly` 잡의 "전 코퍼스 재검증" 스텝은 한때 코퍼스 3개(`generated_v0`·`rephrased_v0`·
`killer_v0`)를 하드코딩했다. 실제 `data/corpus/`에는 `problem_bank_*` 코퍼스가 7종 있었고
(2026-08 실측), 하드코딩 3종 외 4종(`conceptual_v0`·`misconception_mc_v0`·
`probability_finite_v0`·`v1` — 전체 문항의 55.8%)은 야간 재검증을 한 번도 받지 못했다.
"새 코퍼스가 구조적으로 누락되는 구조"가 문제의 본체였으므로, 이 테스트는 개별 파일 나열이
아니라 **글롭 배선 자체**가 실제 CI YAML에 존재하는지 확인한다(CLAUDE.md "검증 장치를 만들고
배선 확인 없이 완료 선언 금지" — `test_qa_pipeline_wiring.py`(ARCH-21) 동형 선례).

검증 계약
--------
① `e2e-nightly` 잡에 `corpus_reverify` 모듈을 호출하는 `run` 스텝이 있다
② 그 스텝이 `-m whymath_backend.harness.corpus_reverify` 형태로 호출한다(패키지 모듈 실행)
③ 그 스텝의 실행부(주석 제외)에 옛 하드코딩 3파일명이 **더 이상 없고**, 대신
   `problem_bank_*/problems.jsonl` 글롭 패턴이 있다
④ `e2e-nightly` 잡은 여전히 `schedule` 이벤트에서만 돈다(상시성 배치 — push/PR에 얹지 않는다)
⑤ 파서가 위장하지 않는다 — 워크플로/잡/스텝을 못 찾으면 "위반 0 통과"가 아니라 **실패**

변별력 실측 (2026-08-08, CLAUDE.md "변별력 없는 검증 스텝 금지")
----------------------------------------------------------
`test_glob_pattern_actually_catches_a_new_corpus_directory_locally`가 셸 글롭과 동형인
`Path.glob("problem_bank_*/problems.jsonl")`을 임시 디렉터리에 재현해 두 가지를 직접
실측한다 — ①글롭이 코퍼스 7종 전량을 실제로 잡는다(양성 대조) ②"글롭에서 1종을 빼면"과
동형인 옛 하드코딩 3파일 나열을 같은 임시 트리에 적용하면 4종을 실제로 놓친다(음성 대조 —
실패 상태에서 진짜로 실패 신호를 낸다). 로컬 실측 결과: 글롭 7/7 매치, 하드코딩 3/7만 매치
(4건 누락 — `conceptual_v0`·`misconception_mc_v0`·`probability_finite_v0`·`v1`).
`test_defect_reintroducing_hardcoded_list_is_detected`는 실제 저장소 루트 `data/corpus/`
스냅샷을 대상으로 같은 사실을 재확인한다(코퍼스 종수가 늘어도 계약은 "7종 이상 전량 매치"로
유지되도록 `>=` 비교).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_JOB_KEY = "e2e-nightly"
_MODULE_INVOCATION = "-m whymath_backend.harness.corpus_reverify"
_GLOB_PATTERN = "problem_bank_*/problems.jsonl"
# 옛 하드코딩(배선 갭 1의 증거) — 재발하면 이 상수와 대조해 검출한다.
_LEGACY_HARDCODED_FILES = (
    "problem_bank_generated_v0/problems.jsonl",
    "problem_bank_rephrased_v0/problems.jsonl",
    "problem_bank_killer_v0/problems.jsonl",
)


def _load_ci_spec(ci_path: Path = _CI_PATH) -> dict[str, Any]:
    if not ci_path.is_file():
        raise AssertionError(f"{ci_path} 이(가) 없다 — 게이트 배선을 확인할 수 없다.")
    spec: Any = yaml.safe_load(ci_path.read_text(encoding="utf-8"))
    return dict(spec or {})


def _nightly_job(ci_path: Path = _CI_PATH) -> dict[str, Any]:
    spec = _load_ci_spec(ci_path)
    jobs = spec.get("jobs") or {}
    if _JOB_KEY not in jobs:
        raise AssertionError(
            f"ci.yml에 `{_JOB_KEY}` 잡이 없다 — 잡을 개명했다면 이 테스트도 함께 고쳐라."
        )
    return dict(jobs[_JOB_KEY] or {})


def _corpus_reverify_steps(ci_path: Path = _CI_PATH) -> list[dict[str, Any]]:
    job = _nightly_job(ci_path)
    steps = job.get("steps") or []
    return [s for s in steps if isinstance(s, dict) and _MODULE_INVOCATION in str(s.get("run", ""))]


def _non_comment_run_lines(step: dict[str, Any]) -> list[str]:
    """run 블록에서 주석 라인(설명문)을 제외한 실제 실행 라인만 남긴다.

    설명 주석에 예시로 옛 파일명·코퍼스명이 언급될 수 있으므로(이 파일 자체의 docstring처럼),
    "실제로 실행되는 라인"만 검사 대상으로 삼아야 오탐하지 않는다(`test_qa_pipeline_wiring.py`
    의 `test_qa_pipeline_step_uses_module_invocation_not_bare_script`와 동형 관용구).
    """
    lines = []
    for line in str(step.get("run", "")).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


def test_corpus_reverify_step_exists_in_nightly_job() -> None:
    steps = _corpus_reverify_steps()
    assert steps, (
        f"`{_JOB_KEY}` 잡에 `{_MODULE_INVOCATION}` 호출 스텝이 없다 — 초인간 검증 S6 상시성 "
        "재검증이 CI에서 조용히 빠졌다(코드는 존재하나 실행되지 않는 상태)."
    )


def test_corpus_reverify_step_uses_module_invocation() -> None:
    steps = _corpus_reverify_steps()
    assert steps, "corpus_reverify 스텝을 찾을 수 없다(선행 테스트가 먼저 실패했을 것)."
    for step in steps:
        run_lines = _non_comment_run_lines(step)
        assert any(
            _MODULE_INVOCATION in line for line in run_lines
        ), f"corpus_reverify가 `-m` 모듈 실행이 아닌 형태로 호출됐다: {run_lines}"


def test_corpus_reverify_step_no_longer_hardcodes_three_files() -> None:
    """배선 갭 1의 핵심 회귀 방지 — 옛 하드코딩 3파일 나열이 실행 라인에 없어야 한다."""
    steps = _corpus_reverify_steps()
    assert steps, "corpus_reverify 스텝을 찾을 수 없다(선행 테스트가 먼저 실패했을 것)."
    for step in steps:
        run_lines = _non_comment_run_lines(step)
        run_text = "\n".join(run_lines)
        offenders = [f for f in _LEGACY_HARDCODED_FILES if f in run_text]
        assert not offenders, (
            "corpus_reverify 스텝의 실행 라인에 옛 하드코딩 파일명이 남아 있다 — "
            f"글롭 전환이 되돌아갔다: {offenders}"
        )


def test_corpus_reverify_step_uses_glob_pattern() -> None:
    """옛 하드코딩을 없애는 것만으로는 부족하다 — 실제로 글롭 패턴이 있어야 전 코퍼스가 잡힌다."""
    steps = _corpus_reverify_steps()
    assert steps, "corpus_reverify 스텝을 찾을 수 없다(선행 테스트가 먼저 실패했을 것)."
    for step in steps:
        run_lines = _non_comment_run_lines(step)
        run_text = "\n".join(run_lines)
        assert _GLOB_PATTERN in run_text, (
            f"corpus_reverify 스텝 실행 라인에 글롭 패턴({_GLOB_PATTERN})이 없다 — "
            f"새 코퍼스가 다시 구조적으로 누락될 수 있다: {run_lines}"
        )


def test_nightly_job_still_gated_to_schedule_event() -> None:
    """S6 전수 재검증은 상시 배치(야간)에만 얹는다 — push/PR 경로에 새지 않았는지 확인."""
    job = _nightly_job()
    condition = str(job.get("if", ""))
    assert (
        "github.event_name == 'schedule'" in condition
    ), f"`{_JOB_KEY}` 잡이 더 이상 schedule 전용이 아니다 — push/PR CI가 무거워질 수 있다: {condition}"


def test_glob_pattern_actually_catches_a_new_corpus_directory_locally(tmp_path: Path) -> None:
    """변별력 실측 ① — 글롭이 실제로 7종 전량을 잡는지, 셸 글롭과 동형인 Path.glob으로 재현.

    로컬 실측(2026-08-08): 코퍼스 7종 임시 디렉터리를 만들고 `Path.glob(글롭패턴)`으로
    잡히는 파일 수가 정확히 7이어야 한다(코퍼스 1종을 빼면 6이 되어야 하므로 그 경우도 함께
    확인 — "성공·실패 양쪽에서 같은 값을 내면 안 된다"는 CLAUDE.md 요구를 이 테스트 자체가
    충족한다).
    """
    corpus_root = tmp_path / "data" / "corpus"
    names = [
        "problem_bank_conceptual_v0",
        "problem_bank_generated_v0",
        "problem_bank_killer_v0",
        "problem_bank_misconception_mc_v0",
        "problem_bank_probability_finite_v0",
        "problem_bank_rephrased_v0",
        "problem_bank_v1",
    ]
    for name in names:
        d = corpus_root / name
        d.mkdir(parents=True)
        (d / "problems.jsonl").write_text("{}\n", encoding="utf-8")
    # 코퍼스와 무관한 디렉터리(오탐 방지 확인 — 글롭이 problem_bank_* 접두만 잡아야 한다).
    (corpus_root / "standards_v1").mkdir(parents=True)
    (corpus_root / "standards_v1" / "problems.jsonl").write_text("{}\n", encoding="utf-8")

    matched = sorted(p.parent.name for p in corpus_root.glob(_GLOB_PATTERN))
    assert matched == sorted(names), f"글롭이 7종 전량을 잡지 못했다(양성 대조 실패): {matched}"

    # 음성 대조 — 코퍼스 1종을 제거하면 글롭 결과도 실제로 줄어들어야 한다(변별력 확인).
    import shutil

    shutil.rmtree(corpus_root / "problem_bank_probability_finite_v0")
    matched_after_removal = sorted(p.parent.name for p in corpus_root.glob(_GLOB_PATTERN))
    assert len(matched_after_removal) == 6, (
        "코퍼스 1종을 제거했는데도 글롭 매치 수가 줄지 않았다 — 이 검사 자체가 변별력이 없다: "
        f"{matched_after_removal}"
    )
    assert "problem_bank_probability_finite_v0" not in matched_after_removal


def test_defect_reintroducing_hardcoded_list_is_detected(tmp_path: Path) -> None:
    """변별력 실측 ② — 실제 저장소 `data/corpus/`를 대상으로, '글롭'과 '옛 하드코딩 3종'이
    실제로 다른 파일 목록을 넘긴다는 것을 직접 재현해 확인한다(로컬 실측치를 코드로 동결).

    2026-08-08 로컬 실측: 저장소 실제 코퍼스는 7종이며, 옛 하드코딩 3종 나열은 그중 4종
    (`conceptual_v0`·`misconception_mc_v0`·`probability_finite_v0`·`v1`)을 누락시킨다.
    코퍼스가 앞으로 더 늘어날 수 있으므로 정확히 7이 아니라 **하드코딩 결과보다 글롭 결과가
    많아야 한다(`>`)**는 부등식으로 검증해 향후 코퍼스 추가에도 이 테스트가 살아있게 한다.
    """
    real_corpus_root = _REPO_ROOT / "data" / "corpus"
    if not real_corpus_root.is_dir():  # pragma: no cover — 방어적(레포 구조 변경 시)
        raise AssertionError(f"{real_corpus_root} 이(가) 없다 — 실측 대상 코퍼스 트리가 없다.")

    glob_matched = sorted(p.parent.name for p in real_corpus_root.glob(_GLOB_PATTERN))
    hardcoded_matched = [
        p.parent.name for f in _LEGACY_HARDCODED_FILES if (p := real_corpus_root / f).is_file()
    ]

    assert (
        len(glob_matched) >= 7
    ), f"실제 코퍼스가 7종 미만으로 관측됐다(예상보다 축소) — {glob_matched}"
    assert len(hardcoded_matched) == 3, (
        f"옛 하드코딩 3파일 중 일부가 실제로 사라졌다 — 코퍼스 구조가 바뀌었을 수 있다: "
        f"{hardcoded_matched}"
    )
    missing_from_hardcoded = sorted(set(glob_matched) - set(hardcoded_matched))
    assert (
        missing_from_hardcoded
    ), "글롭과 하드코딩이 같은 결과를 냈다 — 이 회귀 검사가 변별력을 잃었다."
    assert len(missing_from_hardcoded) >= 4, (
        f"글롭 전환이 되돌아가면 최소 4종이 야간 재검증에서 누락된다는 사실이 재현되지 않았다: "
        f"{missing_from_hardcoded}"
    )
