"""[OPS-83] backend 잡 단위 샤딩의 배선 동결 — 집계 잡이 샤드 실패를 삼키지 않는가.

왜 이 테스트가 있는가
--------------------
OPS-83은 `backend — lint·type·test` 단일 잡을 정적 검사 1잡(`backend`) + pytest 샤드 N잡
(`backend-pytest-K`) + 집계 1잡(`backend-verdict`)으로 나눴다. 필수 체크 이름은 집계 잡이
물려받았다. 이 구조에서 조용히 새는 형태는 전부 *초록으로 보인다*:

* 집계 잡의 `needs`에서 샤드 하나가 빠진다 → 그 샤드가 red여도 집계 잡은 초록이다.
* 집계 잡에서 `always()`가 빠진다 → 샤드가 실패하면 GitHub가 집계 잡을 *건너뛰고*, 건너뛴
  required check는 **충족**으로 센다. 실패한 PR이 머지된다.
* 샤드 하나의 `--shard`가 `2/3`으로 중복되거나 `3/4`로 어긋난다 → 어떤 파일은 두 번, 어떤 파일은
  0번 돈다. (런타임에서는 `backend_shard_verdict.py reports`가 잡는다 — 여기서는 정적으로도 잡는다.)
* 합산 목록에서 샤드 하나의 커버리지 파일이 빠진다 → 커버리지가 조용히 낮아질 뿐 실패하지 않을 수
  있다(계층 floor 위에 여유가 있으면).
* 샤드 하나에 `continue-on-error`가 붙는다 → 그 샤드는 실패해도 success로 보고된다.

검증 계약 (각 항목은 아래 결함 주입으로 변별력을 확인)
----------------------------------------------------
① 샤드 잡이 K=1..N 전수로 있고, 이름·`--shard K/N`·보고서·산출물 이름의 K·N이 일치한다.
② 샤드들의 pytest 명령은 K만 다르고 동형이다(한 샤드만 `-m` 필터·`--cov` 대상이 다르면 안 된다).
③ 샤드와 정적 잡의 실행 조건(`if`)·`needs`·상한이 서로 같다.
④ 집계 잡이 필수 체크 이름을 가진 **유일한** 잡이고, `needs`가 정적 잡·전 샤드·changes를 전수
   포함하며, `if`가 `always() && (<샤드 조건>)`이다.
⑤ 집계 잡의 첫 판정 스텝이 `toJSON(needs)`를 판정기에 넘기고, 분할 완전성·합산(전 샤드)·
   집계 70%·계층 floor 스텝이 이어진다.
⑥ 이 다섯 잡 어디에도 `continue-on-error`가 없다.
⑦ 파서가 위장하지 않는다 — ci.yml이 없거나 샤드가 0개면 통과가 아니라 실패다.

정직한 공백
-----------
- 판정기 자체의 판정(어떤 needs 조합이 exit 1인가)은 `test_backend_shard_verdict.py`가 본다.
- 실제 CI에서 샤드 하나를 실패시켰을 때 required check가 red가 되는지는 저장소 안에서 확인할 수
  없다 — OPS-83 ⑥의 PR 주입 실험이 맡는다.
"""

from __future__ import annotations

import copy
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

REQUIRED_NAME = "backend — lint·type·test"
STATIC_JOB = "backend"
VERDICT_JOB = "backend-verdict"
_SHARD_KEY_RE = re.compile(r"^backend-pytest-(\d+)$")


def _load_workflow() -> dict[str, Any]:
    if not _CI_PATH.is_file():
        raise AssertionError(f"{_CI_PATH}이(가) 없다 — 배선을 확인할 수 없다(위장 통과 금지).")
    spec: Any = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not spec.get("jobs"):
        raise AssertionError("ci.yml에 jobs가 없다 — 판정 불가.")
    return spec


def _run_scripts(job: Mapping[str, Any]) -> list[str]:
    return [str(s["run"]) for s in job.get("steps") or [] if isinstance(s, dict) and s.get("run")]


def _pytest_script(job: Mapping[str, Any]) -> str | None:
    for script in _run_scripts(job):
        if re.search(r"python[\d.]*\s+-m\s+pytest\b", script):
            return script
    return None


def _flat(script: str) -> str:
    return re.sub(r"\s+", " ", script.replace("\\\n", " ")).strip()


def _needs(job: Mapping[str, Any]) -> list[str]:
    raw = job.get("needs")
    if isinstance(raw, str):
        return [raw]
    return [str(x) for x in raw or []]


def shard_wiring_violations(spec: Mapping[str, Any]) -> list[str]:
    """배선 계약 위반 목록(빈 리스트 = 정상). 순수 함수 — 합성 결함 주입으로 봉인한다."""
    jobs = spec.get("jobs")
    if not isinstance(jobs, Mapping) or not jobs:
        return ["jobs가 없다 — 판정 불가(위장 통과 금지)"]
    v: list[str] = []

    shards: dict[int, Mapping[str, Any]] = {}
    for key, job in jobs.items():
        m = _SHARD_KEY_RE.match(str(key))
        if m and isinstance(job, Mapping):
            shards[int(m.group(1))] = job
    if not shards:
        return ["backend-pytest-K 샤드 잡이 하나도 없다 — 스캔 0건은 통과가 아니다"]
    n = len(shards)
    if sorted(shards) != list(range(1, n + 1)):
        v.append(f"샤드 번호가 1..N 연속이 아니다: {sorted(shards)}")

    static = jobs.get(STATIC_JOB)
    verdict = jobs.get(VERDICT_JOB)
    if not isinstance(static, Mapping):
        v.append(f"정적 잡 `{STATIC_JOB}`이 없다")
    if not isinstance(verdict, Mapping):
        v.append(f"집계 잡 `{VERDICT_JOB}`이 없다")
        return v

    # ① ② 샤드별 이름·명령·산출물
    normalized: dict[int, str] = {}
    for k, job in sorted(shards.items()):
        if job.get("name") != f"backend — pytest 샤드 {k}/{n}":
            v.append(f"샤드 {k}: 이름 {job.get('name')!r} ≠ 'backend — pytest 샤드 {k}/{n}'")
        script = _pytest_script(job)
        if script is None:
            v.append(f"샤드 {k}: `python -m pytest` 스텝이 없다")
            continue
        flat = _flat(script)
        required_tokens = [
            "-p backend_shard_plugin",
            f"--shard {k}/{n}",
            f"--shard-report pytest-shard/report-{k}.json",
            '-m "not corpus_authoring"',
            "-n auto --dist loadfile",
            "--cov=whymath_backend",
            f"mv .coverage pytest-shard/coverage-{k}.data",
        ]
        for token in required_tokens:
            if token not in flat:
                v.append(f"샤드 {k}: pytest 스텝에 `{token}`이 없다")
        if "--cov-fail-under" in flat:
            v.append(f"샤드 {k}: --cov-fail-under는 샤드에 두지 않는다(부분 커버리지 — 집계 잡 몫)")
        normalized[k] = flat.replace(f"{k}/{n}", "K/N").replace(f"-{k}.", "-K.")
        uploads = [
            s
            for s in job.get("steps") or []
            if isinstance(s, Mapping)
            and str(s.get("uses", "")).startswith("actions/upload-artifact")
        ]
        ok_upload = any(
            (u.get("with") or {}).get("name") == f"backend-shard-{k}"
            and (u.get("with") or {}).get("path") == "src/backend/pytest-shard/"
            and (u.get("with") or {}).get("if-no-files-found") == "error"
            for u in uploads
        )
        if not ok_upload:
            v.append(
                f"샤드 {k}: 산출물 업로드(name=backend-shard-{k}·path=src/backend/pytest-shard/·"
                "if-no-files-found=error)가 없다"
            )
    if len(set(normalized.values())) > 1:
        v.append("샤드들의 pytest 명령이 K 말고도 다르다 — 동형이어야 한다")

    # ③ 실행 조건·needs·상한 동일
    reference = static if isinstance(static, Mapping) else next(iter(shards.values()))
    for label, job in [*((f"샤드 {k}", j) for k, j in sorted(shards.items()))]:
        if job.get("if") != reference.get("if"):
            v.append(f"{label}: if가 정적 잡과 다르다 — {job.get('if')!r}")
        if _needs(job) != _needs(reference):
            v.append(f"{label}: needs가 정적 잡과 다르다 — {_needs(job)}")
    if len({j.get("timeout-minutes") for j in shards.values()}) != 1:
        v.append("샤드들의 timeout-minutes가 서로 다르다")

    # ④ 집계 잡 — 필수 체크 이름·needs 전수·always()
    holders = [
        k for k, j in jobs.items() if isinstance(j, Mapping) and j.get("name") == REQUIRED_NAME
    ]
    if holders != [VERDICT_JOB]:
        v.append(
            f"필수 체크 이름 `{REQUIRED_NAME}`의 보유 잡이 [{VERDICT_JOB}]가 아니다: {holders}"
        )
    expected_needs = {"changes", STATIC_JOB, *(f"backend-pytest-{k}" for k in shards)}
    missing = sorted(expected_needs - set(_needs(verdict)))
    if missing:
        v.append(f"집계 잡 needs에 빠진 잡: {missing} — 그 잡의 실패를 집계 잡이 보지 못한다")
    expected_if = f"always() && ({reference.get('if')})"
    if str(verdict.get("if", "")).strip() != expected_if:
        v.append(
            f"집계 잡 if가 `{expected_if}`가 아니다 — always()가 없으면 선행 실패 시 건너뛰어지고 "
            f"건너뛴 required는 충족으로 센다: {verdict.get('if')!r}"
        )

    # ⑤ 집계 잡 판정 스텝
    steps = [s for s in verdict.get("steps") or [] if isinstance(s, Mapping)]
    runs = [(s, _flat(str(s.get("run", "")))) for s in steps if s.get("run")]
    if not runs or "backend_shard_verdict.py needs" not in runs[0][1]:
        v.append("집계 잡의 첫 run 스텝이 `backend_shard_verdict.py needs`가 아니다")
    elif (runs[0][0].get("env") or {}).get("NEEDS_JSON") != "${{ toJSON(needs) }}":
        v.append("needs 판정 스텝의 env NEEDS_JSON이 `${{ toJSON(needs) }}`가 아니다")
    joined = "\n".join(r for _, r in runs)
    if "backend_shard_verdict.py reports pytest-shard" not in joined:
        v.append("집계 잡에 분할 완전성 판정(`backend_shard_verdict.py reports`)이 없다")
    combine = next((r for _, r in runs if "coverage combine" in r), None)
    if combine is None:
        v.append("집계 잡에 `coverage combine` 스텝이 없다")
    else:
        listed = set(re.findall(r"pytest-shard/coverage-(\d+)\.data", combine))
        if listed != {str(k) for k in shards}:
            v.append(
                f"합산 목록 {sorted(listed)} ≠ 샤드 {sorted(shards)} — 빠진 샤드 커버리지가 사라진다"
            )
        if "--fail-under=70" not in combine:
            v.append("합산 스텝에 집계 하한 `--fail-under=70`이 없다")
    if "check_layer_coverage.py coverage.xml" not in joined:
        v.append("집계 잡에 계층별 커버리지 게이트가 없다")
    downloads = [s for s in steps if str(s.get("uses", "")).startswith("actions/download-artifact")]
    if not any(
        (d.get("with") or {}).get("pattern") == "backend-shard-*"
        and (d.get("with") or {}).get("merge-multiple") is True
        for d in downloads
    ):
        v.append("집계 잡이 backend-shard-* 산출물을 merge-multiple로 내려받지 않는다")

    # ⑥ fail-open 금지
    for key in [STATIC_JOB, VERDICT_JOB, *(f"backend-pytest-{k}" for k in shards)]:
        job = jobs.get(key)
        if not isinstance(job, Mapping):
            continue
        if job.get("continue-on-error"):
            v.append(f"`{key}` 잡에 continue-on-error — 실패가 success로 보고된다")
        for s in job.get("steps") or []:
            if isinstance(s, Mapping) and s.get("continue-on-error"):
                v.append(f"`{key}` 스텝 {s.get('name')!r}에 continue-on-error")
    return v


# ── 실 저장소 ──────────────────────────────────────────────────────────────


def test_real_workflow_has_no_shard_wiring_violations() -> None:
    violations = shard_wiring_violations(_load_workflow())
    assert not violations, "OPS-83 샤드 배선 위반:\n" + "\n".join(f"  · {x}" for x in violations)


def test_parser_refuses_missing_workflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑦ ci.yml이 없으면 통과가 아니라 실패다."""
    monkeypatch.setattr(sys.modules[__name__], "_CI_PATH", tmp_path / "없음.yml")
    with pytest.raises(AssertionError):
        _load_workflow()


def test_empty_jobs_and_zero_shards_are_violations() -> None:
    """⑦ 스캔 0건은 실패다."""
    assert shard_wiring_violations({"jobs": {}}) != []
    real = copy.deepcopy(_load_workflow())
    for key in [k for k in real["jobs"] if _SHARD_KEY_RE.match(k)]:
        del real["jobs"][key]
    assert any("하나도 없다" in x for x in shard_wiring_violations(real))


# ── 결함 주입 (실 ci.yml 사본에 주입 — 합성만 맞고 실물이 빠져나가는 것을 배제) ─────


def _mutated(mutate: Any) -> list[str]:
    spec = copy.deepcopy(_load_workflow())
    before = copy.deepcopy(spec)
    mutate(spec["jobs"])
    assert spec != before, "주입이 적용되지 않았다(주입 자체의 실재)"
    return shard_wiring_violations(spec)


def _pytest_step(job: dict[str, Any]) -> dict[str, Any]:
    return next(s for s in job["steps"] if "python -m pytest" in str(s.get("run", "")))


def _set_needs(jobs: dict[str, Any]) -> None:
    jobs[VERDICT_JOB]["needs"] = [n for n in jobs[VERDICT_JOB]["needs"] if n != "backend-pytest-3"]


def _drop_always(jobs: dict[str, Any]) -> None:
    jobs[VERDICT_JOB]["if"] = str(jobs[VERDICT_JOB]["if"]).replace("always() && ", "")


def _cancelled_instead(jobs: dict[str, Any]) -> None:
    jobs[VERDICT_JOB]["if"] = str(jobs[VERDICT_JOB]["if"]).replace("always()", "!cancelled()")


def _duplicate_shard(jobs: dict[str, Any]) -> None:
    step = _pytest_step(jobs["backend-pytest-3"])
    step["run"] = step["run"].replace("--shard 3/3", "--shard 2/3")


def _wrong_total(jobs: dict[str, Any]) -> None:
    step = _pytest_step(jobs["backend-pytest-2"])
    step["run"] = step["run"].replace("--shard 2/3", "--shard 2/4")


def _drop_combine_entry(jobs: dict[str, Any]) -> None:
    for s in jobs[VERDICT_JOB]["steps"]:
        if "coverage combine" in str(s.get("run", "")):
            s["run"] = s["run"].replace(" pytest-shard/coverage-3.data", "")


def _drop_fail_under(jobs: dict[str, Any]) -> None:
    for s in jobs[VERDICT_JOB]["steps"]:
        if "coverage combine" in str(s.get("run", "")):
            s["run"] = s["run"].replace(" --fail-under=70", "")


def _continue_on_error(jobs: dict[str, Any]) -> None:
    _pytest_step(jobs["backend-pytest-1"])["continue-on-error"] = True


def _rename_verdict(jobs: dict[str, Any]) -> None:
    jobs[VERDICT_JOB]["name"] = "backend — 집계"


def _second_holder(jobs: dict[str, Any]) -> None:
    jobs[STATIC_JOB]["name"] = REQUIRED_NAME


def _shard_narrowed_marker(jobs: dict[str, Any]) -> None:
    step = _pytest_step(jobs["backend-pytest-2"])
    step["run"] = step["run"].replace(
        '-m "not corpus_authoring"', '-m "not corpus_authoring and not slow"'
    )


def _shard_if_drift(jobs: dict[str, Any]) -> None:
    jobs["backend-pytest-1"]["if"] = "github.event_name == 'push'"


def _drop_needs_step(jobs: dict[str, Any]) -> None:
    jobs[VERDICT_JOB]["steps"] = [
        s for s in jobs[VERDICT_JOB]["steps"] if "verdict.py needs" not in str(s.get("run", ""))
    ]


def _drop_reports_step(jobs: dict[str, Any]) -> None:
    jobs[VERDICT_JOB]["steps"] = [
        s for s in jobs[VERDICT_JOB]["steps"] if "verdict.py reports" not in str(s.get("run", ""))
    ]


def _drop_layer_gate(jobs: dict[str, Any]) -> None:
    jobs[VERDICT_JOB]["steps"] = [
        s for s in jobs[VERDICT_JOB]["steps"] if "check_layer_coverage" not in str(s.get("run", ""))
    ]


def _shard_fail_under(jobs: dict[str, Any]) -> None:
    step = _pytest_step(jobs["backend-pytest-1"])
    step["run"] = step["run"].replace(
        "--cov=whymath_backend", "--cov=whymath_backend --cov-fail-under=70"
    )


def _upload_tolerates_missing(jobs: dict[str, Any]) -> None:
    for s in jobs["backend-pytest-2"]["steps"]:
        if str(s.get("uses", "")).startswith("actions/upload-artifact"):
            s["with"]["if-no-files-found"] = "warn"


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (_set_needs, "needs에 빠진 잡"),
        (_drop_always, "always()"),
        (_cancelled_instead, "always()"),
        (_duplicate_shard, "--shard 3/3"),
        (_wrong_total, "--shard 2/3"),
        (_drop_combine_entry, "합산 목록"),
        (_drop_fail_under, "--fail-under=70"),
        (_continue_on_error, "continue-on-error"),
        (_rename_verdict, "보유 잡"),
        (_second_holder, "보유 잡"),
        (_shard_narrowed_marker, "동형"),
        (_shard_if_drift, "if가 정적 잡과 다르다"),
        (_drop_needs_step, "첫 run 스텝"),
        (_drop_reports_step, "분할 완전성"),
        (_drop_layer_gate, "계층별 커버리지"),
        (_shard_fail_under, "--cov-fail-under"),
        (_upload_tolerates_missing, "산출물 업로드"),
    ],
)
def test_injected_defect_is_detected(mutate: Any, needle: str) -> None:
    violations = _mutated(mutate)
    assert any(
        needle in x for x in violations
    ), f"주입 {mutate.__name__}이(가) 검출되지 않았다(기대 단서 {needle!r}): {violations}"
