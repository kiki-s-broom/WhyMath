"""[OPS-150] 야간 S6 재검증(`corpus_reverify`)의 **배선 실재성 + 학생 표기 대조 도달** 동결.

왜 이 테스트가 있는가
--------------------
OPS-150 은 `corpus_reverify` 가 레코드의 `answer` 필드(학생에게 보이는 정답)를 `verify.answer_map`
(검산 재료)과 대조하게 했다. 그런데 "코드에 대조가 있다"와 "야간 잡이 그 코드를 매일 밤 실제로
부르고, 부른 코퍼스에 대조할 문항이 있다"는 다르다(CLAUDE.md "검증 장치를 만들고 배선 확인 없이
완료 선언 금지"). 이 저장소에는 야간 재검증 스텝의 배선을 동결하는 테스트가 없었다(2026-10-21 실측
— `tests/infra` 의 `corpus_reverify` 언급 0건).

특히 마지막 축이 이 파일의 고유 기여다: 야간 스텝이 도는 코퍼스가 전부 근 집계·개념형이면
(예: killer 은행 120건은 전부 `answer_aggregate`) 학생 표기 대조는 **대상 0건**으로 매일 밤 초록이다.
그러면 대조가 배선은 됐는데 아무것도 대조하지 않는 상태가 된다.

검증 계약
--------
① `python -m whymath_backend.harness.corpus_reverify` 를 호출하는 `run` 스텝이 있다
② 그 스텝을 담은 잡이 schedule 발화 잡이다(야간 상시성 — S6 의 뜻)
③ `continue-on-error` 가 스텝에도 잡에도 없다 — 돌아감 ≠ 막음
④ 인자로 준 코퍼스 경로가 전부 실재한다(작업 디렉터리 기준) — 없는 파일은 야간에 예외로 끝난다
⑤ 그 코퍼스들에 **Tier1 경로 + `answer` 보유** 문항이 1건 이상 있다 — 학생 표기 대조가 실제로 돈다
⑥ 파서가 위장하지 않는다 — 워크플로·잡을 못 찾으면 통과가 아니라 실패

infra 잡에는 백엔드 패키지가 설치돼 있지 않으므로 ⑤는 JSON 필드만으로 센다(import 0). Tier1 경로의
정의는 `corpus_reverify._reverify_one` 의 분기와 같다: `answer_aggregate` 가 sum/product 가 아니고,
`answer_kind` 가 없고, `answer_map` 이 비어 있지 않다.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_MODULE = "whymath_backend.harness.corpus_reverify"


def _load_ci() -> dict[str, Any]:
    if not _CI_PATH.is_file():
        raise AssertionError(f"{_CI_PATH} 이(가) 없다 — 배선을 확인할 수 없다(위장 통과 금지).")
    spec: Any = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not isinstance(spec.get("jobs"), dict) or not spec["jobs"]:
        raise AssertionError("ci.yml 에 jobs 맵이 없다 — 파서가 위장하지 않도록 실패시킨다.")
    return dict(spec)


def _invocation_args(run: str) -> list[str] | None:
    """`run` 블록에서 모듈 호출 줄의 위치 인자. 호출이 없으면 None(주석·설명 속 이름은 무시)."""
    lines: list[str] = []
    for raw in run.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped[:-1].rstrip() if stripped.endswith("\\") else stripped)
    tokens = shlex.split(" ".join(lines))
    for i, token in enumerate(tokens):
        if token == "-m" and i + 1 < len(tokens) and tokens[i + 1] == _MODULE:
            if i == 0 or not tokens[i - 1].startswith("python"):
                return None
            return [t for t in tokens[i + 2 :] if not t.startswith("-")]
    return None


def _is_tier1_with_answer(record: Mapping[str, Any]) -> bool:
    verify = record.get("verify")
    if not isinstance(verify, dict):
        return False
    if verify.get("answer_aggregate") in ("sum", "product") or verify.get("answer_kind"):
        return False
    answer = record.get("answer")
    return bool(verify.get("answer_map")) and isinstance(answer, str) and bool(answer.strip())


def _tier1_answer_count(path: Path) -> int:
    count = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and _is_tier1_with_answer(json.loads(line)):
            count += 1
    return count


def reverify_wiring_violations(spec: Mapping[str, Any], *, repo_root: Path) -> list[str]:
    """야간 재검증 배선 계약 위반 목록(빈 리스트 = 정상) — 순수 함수라 합성 워크플로로 봉인한다."""
    jobs = spec.get("jobs") or {}
    if not isinstance(jobs, dict) or not jobs:
        return ["ci.yml에 jobs가 없다 — 판정 불가(위장 통과 금지)."]

    found: list[tuple[str, dict[str, Any], dict[str, Any], list[str]]] = []
    for job_key, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if not isinstance(step, dict) or not step.get("run"):
                continue
            args = _invocation_args(str(step["run"]))
            if args is not None:
                found.append((job_key, job, step, args))
    if not found:
        return [f"`python -m {_MODULE}` 을 호출하는 스텝이 없다 — 야간 S6 재검증이 미배선이다."]

    violations: list[str] = []
    total_targets = 0
    scheduled = False
    for job_key, job, step, args in found:
        if "== 'schedule'" in str(job.get("if", "")).replace('"', "'"):
            scheduled = True
        if step.get("continue-on-error") or job.get("continue-on-error"):
            violations.append(f"`{job_key}` 의 재검증 스텝이 continue-on-error 다 — 돌아감 ≠ 막음.")
        if not args:
            violations.append(f"`{job_key}` 의 재검증 스텝에 코퍼스 인자가 없다.")
        workdir = step.get("working-directory") or (
            ((job.get("defaults") or {}).get("run") or {}).get("working-directory") or "."
        )
        for arg in args:
            corpus = (repo_root / str(workdir) / arg).resolve()
            if not corpus.is_file():
                violations.append(f"`{job_key}` 의 재검증 인자 `{arg}` 가 실재하지 않는다.")
                continue
            total_targets += _tier1_answer_count(corpus)
    if not scheduled:
        violations.append("재검증 스텝이 schedule 발화 잡에 없다 — 야간 상시성(S6)이 아니다.")
    if total_targets == 0:
        violations.append(
            "야간 재검증 코퍼스에 Tier1 경로 + answer 보유 문항이 0건이다 — 학생 표기 대조"
            "(OPS-150)가 배선은 됐는데 매일 밤 대상 0건으로 초록이다."
        )
    return violations


# ══════════════════════════════════════════════════════════════════════════
# 실 워크플로 판정
# ══════════════════════════════════════════════════════════════════════════
def test_nightly_reverify_is_wired_and_reaches_answer_comparison() -> None:
    violations = reverify_wiring_violations(_load_ci(), repo_root=_REPO_ROOT)
    assert violations == [], "야간 재검증 배선 위반:\n" + "\n".join(f"- {v}" for v in violations)


def test_parser_refuses_to_pass_on_broken_workflow() -> None:
    """⑥ 파서가 위장하지 않는다 — jobs 없는 워크플로는 '위반 0'이 아니다."""
    assert reverify_wiring_violations({"jobs": {}}, repo_root=_REPO_ROOT) != []
    assert reverify_wiring_violations({}, repo_root=_REPO_ROOT) != []


# ══════════════════════════════════════════════════════════════════════════
# 변별력 봉인 — 축마다 반례를 주입해 검출을 확인한다(양성 대조군 포함)
# ══════════════════════════════════════════════════════════════════════════
_TIER1 = {"answer": "5", "verify": {"conditions": "x - 5 = 0", "answer_map": {"x": "5"}}}
_AGG = {
    "answer": "10",
    "verify": {"conditions": "x**2 - 10 = 0", "answer_map": {}, "answer_aggregate": "product"},
}


def _corpus(tmp: Path, name: str, records: list[dict[str, Any]]) -> str:
    path = tmp / name
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return name


def _workflow(
    run: str, *, schedule: bool = True, continue_on_error: bool = False
) -> dict[str, Any]:
    step: dict[str, Any] = {"name": "재검증", "run": run}
    if continue_on_error:
        step["continue-on-error"] = True
    job: dict[str, Any] = {"defaults": {"run": {"working-directory": "."}}, "steps": [step]}
    if schedule:
        job["if"] = "github.event_name == 'schedule'"
    return {"jobs": {"e2e-nightly": job}}


def test_positive_control_has_no_violation(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path, "c.jsonl", [_TIER1])
    spec = _workflow(f"python -m {_MODULE} \\\n  {corpus}")
    assert reverify_wiring_violations(spec, repo_root=tmp_path) == []


def test_missing_step_is_detected(tmp_path: Path) -> None:
    spec = _workflow("python -m whymath_backend.harness.solution_qa")
    assert reverify_wiring_violations(spec, repo_root=tmp_path)


def test_commented_out_invocation_is_not_counted(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path, "c.jsonl", [_TIER1])
    spec = _workflow(f"# python -m {_MODULE} {corpus}\necho skip")
    assert reverify_wiring_violations(spec, repo_root=tmp_path)


def test_unscheduled_job_is_detected(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path, "c.jsonl", [_TIER1])
    spec = _workflow(f"python -m {_MODULE} {corpus}", schedule=False)
    assert any("schedule" in v for v in reverify_wiring_violations(spec, repo_root=tmp_path))


def test_continue_on_error_is_detected(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path, "c.jsonl", [_TIER1])
    spec = _workflow(f"python -m {_MODULE} {corpus}", continue_on_error=True)
    found = reverify_wiring_violations(spec, repo_root=tmp_path)
    assert any("continue-on-error" in v for v in found)


def test_missing_corpus_file_is_detected(tmp_path: Path) -> None:
    spec = _workflow(f"python -m {_MODULE} nowhere.jsonl")
    assert any("실재하지" in v for v in reverify_wiring_violations(spec, repo_root=tmp_path))


def test_corpora_without_tier1_answers_are_detected(tmp_path: Path) -> None:
    """⑤ 근 집계만 있는 코퍼스는 학생 표기 대조 대상 0건 — 배선됐어도 위반이다."""
    corpus = _corpus(tmp_path, "agg.jsonl", [_AGG, _AGG])
    spec = _workflow(f"python -m {_MODULE} {corpus}")
    assert any("0건" in v for v in reverify_wiring_violations(spec, repo_root=tmp_path))


def test_tier1_records_without_answer_do_not_count(tmp_path: Path) -> None:
    no_answer = {"verify": _TIER1["verify"]}
    corpus = _corpus(tmp_path, "na.jsonl", [no_answer])
    spec = _workflow(f"python -m {_MODULE} {corpus}")
    assert any("0건" in v for v in reverify_wiring_violations(spec, repo_root=tmp_path))
