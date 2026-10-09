"""[OPS-100] CI 잡별 타임아웃 여유 감시 — 계약 동결 + 결함 주입.

왜 이 테스트가 있는가
--------------------
CI 잡 시간 예산 소진이 4회 반복됐고(2026-07-25·08-21·09-01·09-28) 매번 그 자리 조치로만
끝났다. `scripts/analysis/measure_ci_job_timeout_headroom.py`가 그 상시 감시다. 감시 도구가
**틀린 안심**을 내면 4회 반복이 5회가 되므로, 도구의 판정 절마다 그 절이 없으면 실패하는
반례를 픽스처로 둔다. 모든 입력은 합성 이력이며 네트워크에 접속하지 않는다(헌법 R17 계열).

검증 계약 (각 항목은 결함 주입으로 변별력을 확인했다 — 아래 `_MUTATIONS`)
-------------------------------------------------------------------------
① 상한은 ci.yml에서 읽는다(하드코딩 아님) · 읽을 수 없으면 예외.
② 생존자 편향 없음 — 타임아웃으로 죽은 실행이 표본에서 빠지지 않는다. 반대로 동시성 취소처럼
   짧게 끊긴 실행은 표본이 아니다. 건너뛴 잡·음수 소요는 표본이 될 수 없다.
③ 모른다 ≠ 아니다 — 표본 0건·이름 불일치·상한 미선언·API 거부·이력 0건은 OK가 아니다.
④ 판정은 최대 표본 기준이고 경계(정확히 30%)는 충분이다(부동소수점 오차 포함).
⑤ exit code: 0 정상 / 1 여유 부족(측정 불가보다 우선) / 2 측정 불가 · 미처리 예외도 2.
⑥ 증거는 실행 1건마다 flush — 중간에 죽어도 그 시점까지가 남는다.
⑦ 워크플로 배선 — 예약 실행·`actions: read`·토큰 전달·실패 은닉 없음·쓰기 권한 없음.
⑧ 기존 OPS-47 진입점은 구 CLI 그대로 받아 일반화 도구에 위임한다.

실제 API 응답으로 확인한 사실(2026-10-08)이 픽스처의 근거다 — 건너뛴 잡의 시각 역전, 동시성
취소(야간 직렬 스위트 14분/45분), 머지 큐 head_branch의 gh-readonly-queue 접두.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock
from urllib.parse import parse_qs

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "analysis" / "measure_ci_job_timeout_headroom.py"
_SHIM = _ROOT / "scripts" / "analysis" / "measure_backend_job_timeout_headroom.py"
_CI_YML = _ROOT / ".github" / "workflows" / "ci.yml"
_WORKFLOW = _ROOT / ".github" / "workflows" / "ci-timeout-headroom.yml"


# ── 로더 ────────────────────────────────────────────────────────────────────


def _load_path(path: Path, name: str) -> ModuleType:
    """`path`를 독립 모듈로 로드한다(형제 import를 위해 그 디렉터리를 임시로 sys.path에 넣는다)."""
    parent = str(path.parent)
    inserted = parent not in sys.path
    if inserted:
        sys.path.insert(0, parent)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        if inserted:
            sys.path.remove(parent)


@pytest.fixture(scope="module")
def mod() -> ModuleType:
    return _load_path(_SCRIPT, "_ops100_real")


# ── 합성 이력 픽스처 ────────────────────────────────────────────────────────

_T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
BACKEND = "backend — lint·type·test"
POLICY = "policy-guard — 금기 가드"
NIGHTLY = "e2e-nightly — 야간"
JOBS_YAML = {"backend": (BACKEND, 35), "policy": (POLICY, 2), "nightly": (NIGHTLY, 12)}


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def api_job(
    name: str, conclusion: str, minutes: float, *, status: str = "completed"
) -> dict[str, Any]:
    """GitHub 잡 응답 모양. minutes가 음수면 completed_at이 started_at보다 앞선다(실측 모양)."""
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "started_at": _iso(_T0),
        "completed_at": _iso(_T0 + timedelta(minutes=minutes)),
    }


def healthy_jobs() -> list[dict[str, Any]]:
    return [
        api_job(BACKEND, "success", 20),
        api_job(POLICY, "success", 0.3),
        api_job(NIGHTLY, "skipped", -1 / 60),  # 건너뛴 잡: 시각 역전(실측)
    ]


def healthy_history() -> dict[str, list[tuple[int, list[dict[str, Any]]]]]:
    return {
        "push": [(11, healthy_jobs()), (12, healthy_jobs())],
        "merge_group": [(21, healthy_jobs())],
        "schedule": [
            (
                31,
                [
                    api_job(BACKEND, "skipped", -1 / 60),
                    api_job(POLICY, "success", 0.3),
                    api_job(NIGHTLY, "success", 3),
                ],
            )
        ],
    }


class FakeGitHub:
    """경로 → 합성 응답. 기대하지 않은 경로는 실패시킨다(URL 조립 오류를 잡는다)."""

    def __init__(
        self,
        history: dict[str, list[tuple[int, list[dict[str, Any]]]]],
        on_jobs_call: Callable[[int], None] | None = None,
    ) -> None:
        self.history = history
        self.on_jobs_call = on_jobs_call
        self.paths: list[str] = []
        self.jobs_calls = 0

    def __call__(self, path: str) -> object:
        self.paths.append(path)
        runs = re.match(r"^/repos/[^/]+/[^/]+/actions/workflows/[^/]+/runs\?(.*)$", path)
        if runs:
            event = parse_qs(runs.group(1))["event"][0]
            return {"workflow_runs": [{"id": rid} for rid, _ in self.history.get(event, [])]}
        jobs = re.match(r"^/repos/[^/]+/[^/]+/actions/runs/(\d+)/jobs\?(.*)$", path)
        if jobs:
            self.jobs_calls += 1
            if self.on_jobs_call:
                self.on_jobs_call(self.jobs_calls)
            run_id = int(jobs.group(1))
            for entries in self.history.values():
                for rid, job_list in entries:
                    if rid == run_id:
                        return {"total_count": len(job_list), "jobs": job_list}
        raise AssertionError(f"예상하지 못한 경로: {path}")


def write_ci(tmp: Path, jobs: dict[str, tuple[str | None, Any]] | None = None) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    spec: dict[str, Any] = {}
    for key, (name, limit) in (jobs or JOBS_YAML).items():
        job: dict[str, Any] = {"runs-on": "ubuntu-latest"}
        if name is not None:
            job["name"] = name
        if limit is not None:
            job["timeout-minutes"] = limit
        spec[key] = job
    path = tmp / "ci.yml"
    path.write_text(yaml.safe_dump({"jobs": spec}, allow_unicode=True), encoding="utf-8")
    return path


def run_main(
    m: ModuleType,
    tmp: Path,
    history: dict[str, list[tuple[int, list[dict[str, Any]]]]],
    *extra: str,
    fake: Callable[[str], object] | None = None,
    jobs: dict[str, tuple[str | None, Any]] | None = None,
) -> tuple[int, str, str]:
    ci = write_ci(tmp, jobs)
    getter = fake or FakeGitHub(history)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = m.main(["acme/repo", "--ci-yml", str(ci), *extra], get=getter)
    return rc, out.getvalue(), err.getvalue()


def _raises(exc_type: type[BaseException], fn: Callable[[], object], contains: str = "") -> None:
    """pytest.raises를 쓰지 않는다 — 결함 주입 하네스가 `Exception`으로 검출을 판정하는데
    `pytest.fail`의 Failed는 BaseException이라 빠져나간다."""
    try:
        fn()
    except exc_type as exc:
        assert contains in str(exc), f"예외 메시지에 '{contains}'가 없다: {exc}"
        return
    raise AssertionError(f"{exc_type.__name__}가 나야 하는데 나지 않았다")


def _spec(m: ModuleType, key: str = "j", limit: int | None = 10) -> Any:
    return m.JobSpec(key, f"{key} name", limit)


def _smp(m: ModuleType, minutes: float, saturated: bool = False) -> Any:
    return m.Sample(1, "push", minutes, saturated)


# ── 시나리오: 각각 실제 모듈에서 통과해야 하고, 해당 결함 주입에서 실패해야 한다 ──────────────


def scn_success_is_a_sample(m: ModuleType, tmp: Path) -> None:
    assert m.classify_job(api_job("x", "success", 10), 35) == ("sample", 10.0)


def scn_timeout_cancel_is_saturated(m: ModuleType, tmp: Path) -> None:
    """② 생존자 편향 금지 — 상한 가까이 달린 취소·실패·timed_out은 '상한 도달'이다."""
    for conclusion, minutes in (("cancelled", 35.0), ("failure", 34.0), ("cancelled", 33.5)):
        kind, got = m.classify_job(api_job("x", conclusion, minutes), 35)
        assert kind == "saturated" and got == minutes, (conclusion, minutes, kind)
    assert m.classify_job(api_job("x", "timed_out", 35.0), 35)[0] == "saturated"
    no_time = api_job("x", "timed_out", 35.0)
    no_time["completed_at"] = None  # 시각이 결손이어도 timed_out은 상한 도달이다
    assert m.classify_job(no_time, 35) == ("saturated", 35.0)


def scn_short_cancel_is_not_a_sample(m: ModuleType, tmp: Path) -> None:
    """② 대조군 — 동시성 취소처럼 짧게 끊긴 잡은 전체 길이를 모르므로 표본이 아니다."""
    for conclusion, minutes, limit in (
        ("cancelled", 14.0, 45),  # 야간 직렬 스위트가 14분에 취소된 실측
        ("cancelled", 33.0, 35),  # 95% 바로 아래
        ("failure", 3.0, 35),
    ):
        kind, got = m.classify_job(api_job("x", conclusion, minutes), limit)
        assert (kind, got) == (f"excluded:{conclusion}", None), (conclusion, minutes, kind)


def scn_skipped_and_reversed_time_are_never_samples(m: ModuleType, tmp: Path) -> None:
    skipped = api_job("x", "skipped", -1 / 60)  # started_at이 completed_at보다 1초 늦다(실측)
    assert m.classify_job(skipped, 35) == ("excluded:skipped", None)
    assert m.job_minutes(api_job("x", "success", -1.0)) is None
    assert m.classify_job(api_job("x", "success", -1.0), 35) == ("excluded:no_time", None)
    missing = api_job("x", "success", 5)
    missing["started_at"] = None
    assert m.classify_job(missing, 35) == ("excluded:no_time", None)


def scn_incomplete_job_is_excluded(m: ModuleType, tmp: Path) -> None:
    job = api_job("x", "success", 5, status="in_progress")
    assert m.classify_job(job, 35) == ("excluded:incomplete", None)


def scn_boundary_is_ok_and_just_below_is_low(m: ModuleType, tmp: Path) -> None:
    """④ 정확히 30%는 충분, 그 아래는 LOW."""
    assert m.evaluate_job(_spec(m), [_smp(m, 7.0)], Counter(), 1).status == "OK"
    assert m.evaluate_job(_spec(m), [_smp(m, 7.01)], Counter(), 1).status == "LOW"


def scn_float_noise_at_the_boundary_is_ok(m: ModuleType, tmp: Path) -> None:
    """상한 7분·최대 294초(=4.9분)는 수학적으로 정확히 30%인데 float 계산은 0.2999…93이다."""
    report = m.evaluate_job(_spec(m, limit=7), [_smp(m, 294 / 60)], Counter(), 1)
    assert report.status == "OK", report


def scn_threshold_is_applied(m: ModuleType, tmp: Path) -> None:
    low = m.evaluate_job(_spec(m), [_smp(m, 9.5)], Counter(), 1)
    ok = m.evaluate_job(_spec(m), [_smp(m, 2.0)], Counter(), 1)
    assert (low.status, ok.status) == ("LOW", "OK")
    custom = m.evaluate_job(_spec(m), [_smp(m, 9.5)], Counter(), 1, threshold=0.01)
    assert custom.status == "OK"  # 기준은 인자로 바뀐다


def scn_low_follows_the_max_not_the_median(m: ModuleType, tmp: Path) -> None:
    samples = [_smp(m, 5.0)] * 9 + [_smp(m, 9.0)]
    report = m.evaluate_job(_spec(m), samples, Counter(), 10)
    assert report.status == "LOW" and report.max_minutes == 9.0 and report.median_minutes == 5.0


def scn_saturated_sample_is_low_and_names_the_finished_max(m: ModuleType, tmp: Path) -> None:
    """한 번 멈춘 잡과 서서히 느려진 잡은 처방이 다르다 — 완주 표본 최대가 둘을 가른다."""
    spec = _spec(m, limit=35)
    samples = [_smp(m, 10.0)] * 5 + [_smp(m, 35.0, saturated=True)]
    report = m.evaluate_job(spec, samples, Counter(), 6)
    assert report.status == "LOW" and report.saturated == 1
    assert "상한 도달 1회" in report.note and "완주 표본 최대 10.00분" in report.note
    only = m.evaluate_job(spec, [_smp(m, 35.0, saturated=True)], Counter(), 1)
    assert only.status == "LOW" and "완주 표본 없음" in only.note


def scn_unmeasured_is_never_ok(m: ModuleType, tmp: Path) -> None:
    """③ 모른다 ≠ 아니다."""
    never = m.evaluate_job(_spec(m), [], Counter(), 0)
    assert never.status == "UNMEASURED" and "이름" in never.note, never
    skipped = m.evaluate_job(_spec(m), [], Counter({"excluded:skipped": 5}), 5)
    assert skipped.status == "UNMEASURED" and "excluded:skipped×5" in skipped.note, skipped
    assert "이름" not in skipped.note  # 관측은 됐으므로 이름 불일치가 아니다
    no_limit = m.evaluate_job(_spec(m, limit=None), [_smp(m, 3.0)], Counter(), 1)
    assert no_limit.status == "UNMEASURED", no_limit


def scn_urls_are_built_to_see_every_run(m: ModuleType, tmp: Path) -> None:
    fake = FakeGitHub(healthy_history())
    m.run_measurement(fake, "acme/repo", [m.JobSpec("backend", BACKEND, 35)], out=io.StringIO())
    run_paths = [p for p in fake.paths if "/workflows/" in p]
    assert len(run_paths) == 3, run_paths
    for p in run_paths:
        assert "status=completed" in p and "status=success" not in p, p  # 생존자 편향 금지
    by_event = {re.search(r"event=(\w+)", p).group(1): p for p in run_paths}  # type: ignore[union-attr]
    assert "branch=main" in by_event["push"] and "branch=main" in by_event["schedule"]
    assert "branch=" not in by_event["merge_group"]  # 머지 큐 head_branch는 gh-readonly-queue/...
    job_paths = [p for p in fake.paths if "/jobs?" in p]
    assert job_paths and all("filter=latest" in p for p in job_paths)


def scn_events_are_pooled(m: ModuleType, tmp: Path) -> None:
    history = {
        "push": [(1, [api_job(BACKEND, "success", 15)])],
        "merge_group": [(2, [api_job(BACKEND, "success", 30)])],
        "schedule": [],
    }
    result = m.run_measurement(
        FakeGitHub(history), "acme/repo", [m.JobSpec("backend", BACKEND, 35)], out=io.StringIO()
    )
    report = result.reports[0]
    assert (report.samples, report.max_minutes, report.status) == (2, 30.0, "LOW"), report


def scn_zero_history_is_a_failure(m: ModuleType, tmp: Path) -> None:
    spec = [m.JobSpec("backend", BACKEND, 35)]
    _raises(
        m.MeasureError,
        lambda: m.run_measurement(FakeGitHub({}), "acme/repo", spec, out=io.StringIO()),
        "0건",
    )
    one_event = {"push": [(1, [api_job(BACKEND, "success", 10)])]}  # 대조군: 일부 비어도 실패 아님
    result = m.run_measurement(FakeGitHub(one_event), "acme/repo", spec, out=io.StringIO())
    assert result.reports[0].status == "OK"


def scn_exit_zero_when_everything_has_room(m: ModuleType, tmp: Path) -> None:
    rc, out, _ = run_main(m, tmp, healthy_history())
    assert rc == 0, out


def scn_exit_one_when_a_job_is_low(m: ModuleType, tmp: Path) -> None:
    history = healthy_history()
    history["merge_group"] = [
        (21, [api_job(BACKEND, "success", 30), api_job(POLICY, "success", 0.3)])
    ]
    rc, out, _ = run_main(m, tmp, history)
    assert rc == 1, out
    assert "backend" in out and "LOW" in out


def scn_exit_two_when_a_job_cannot_be_measured(m: ModuleType, tmp: Path) -> None:
    history = healthy_history()
    renamed = {
        k: [(rid, [j for j in jobs if j["name"] != NIGHTLY]) for rid, jobs in v]
        for k, v in history.items()
    }
    rc, out, _ = run_main(m, tmp, renamed)
    assert rc == 2, out
    assert "UNMEASURED" in out and "이름 변경" in out


def scn_low_outranks_unmeasured(m: ModuleType, tmp: Path) -> None:
    history = {
        k: [(rid, [j for j in jobs if j["name"] != NIGHTLY]) for rid, jobs in v]
        for k, v in healthy_history().items()
    }
    history["push"].append((13, [api_job(BACKEND, "success", 33)]))
    rc, out, _ = run_main(m, tmp, history)
    assert rc == 1, out  # 둘 다 있으면 행동이 필요한 쪽을 먼저 낸다(둘 다 표에 나온다)
    assert "LOW" in out and "UNMEASURED" in out


def scn_api_failure_is_exit_two(m: ModuleType, tmp: Path) -> None:
    def boom(path: str) -> object:
        raise m.MeasureError("HTTP 403 — 시뮬레이션")

    rc, _, err = run_main(m, tmp, {}, fake=boom)
    assert rc == 2 and "403" in err, err


def scn_unexpected_exception_is_exit_two(m: ModuleType, tmp: Path) -> None:
    """미처리 예외의 파이썬 종료 코드는 1 — '여유 부족'으로 오독되므로 2로 흡수한다."""

    def crash(path: str) -> object:
        raise RuntimeError("예기치 않은 버그")

    with contextlib.redirect_stderr(io.StringIO()):  # traceback 소음 억제
        rc, _, err = run_main(m, tmp, {}, fake=crash)
    assert rc == 2 and "RuntimeError" in err, err


def scn_only_filter_does_not_report_known_jobs_as_unmatched(m: ModuleType, tmp: Path) -> None:
    rc, out, _ = run_main(m, tmp, healthy_history(), "--only", "backend")
    assert rc == 0, out
    assert "ci.yml에 없는" not in out, out  # 필터로 빠진 잡은 불일치가 아니다
    rc, out, _ = run_main(
        m, tmp / "x", healthy_history(), jobs={"backend": (BACKEND, 35)}  # 정말 모르는 이름
    )
    assert "ci.yml에 없는 잡 이름" in out and POLICY in out, out
    rc, _, err = run_main(m, tmp / "y", healthy_history(), "--only", "nope")
    assert rc == 2 and "nope" in err


def scn_http_failures_carry_the_cause(m: ModuleType, tmp: Path) -> None:
    def fake_run(body: str, rc: int = 0) -> Callable[..., Any]:
        return lambda cmd, **kw: subprocess.CompletedProcess(cmd, rc, stdout=body, stderr="oops")

    denied = '{"message":"Resource not accessible by integration"}\n403'
    with mock.patch.object(m.subprocess, "run", fake_run(denied)):
        _raises(m.MeasureError, lambda: m._get("/x"), "403")
        _raises(m.MeasureError, lambda: m._get("/x"), "Resource not accessible")
    with mock.patch.object(m.subprocess, "run", fake_run('{"workflow_runs": []}\n200')):
        assert m._get("/x") == {"workflow_runs": []}
    with mock.patch.object(m.subprocess, "run", fake_run("<html>\n200")):
        _raises(m.MeasureError, lambda: m._get("/x"), "JSON")
    with mock.patch.object(m.subprocess, "run", fake_run("", rc=6)):
        _raises(m.MeasureError, lambda: m._get("/x"), "curl 실패")

    def timeout(cmd: Any, **kw: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd, 1)

    with mock.patch.object(m.subprocess, "run", timeout):
        _raises(m.MeasureError, lambda: m._get("/x"), "TimeoutExpired")


def scn_response_shape_is_checked(m: ModuleType, tmp: Path) -> None:
    def not_found(path: str) -> object:
        return {"message": "Not Found"}

    _raises(
        m.MeasureError,
        lambda: m.list_runs(not_found, "o/r", "ci.yml", "push", "main", 5),
        "Not Found",
    )
    _raises(m.MeasureError, lambda: m.list_jobs(not_found, "o/r", 1), "Not Found")


def scn_jobs_are_paginated_and_truncation_is_an_error(m: ModuleType, tmp: Path) -> None:
    jobs = [api_job(f"j{i}", "success", 1) for i in range(3)]

    def two_pages(path: str) -> object:
        # `per_page=100`의 `page=100`에 걸리지 않도록 쪽 번호 앞의 구분자까지 본다.
        page = int(re.search(r"[?&]page=(\d+)", path).group(1))  # type: ignore[union-attr]
        return {"total_count": 3, "jobs": {1: jobs[:2], 2: jobs[2:]}.get(page, [])}

    assert len(m.list_jobs(two_pages, "o/r", 7)) == 3

    def endless(path: str) -> object:
        return {"total_count": 1000, "jobs": jobs[:1]}

    _raises(m.MeasureError, lambda: m.list_jobs(endless, "o/r", 7), "절단")


def scn_evidence_is_flushed_per_run(m: ModuleType, tmp: Path) -> None:
    """⑥ 실행 2건째를 조회하는 *도중*에 파일을 읽는다 — flush가 없으면 아직 비어 있다."""
    tmp.mkdir(parents=True, exist_ok=True)
    evidence = tmp / "obs.jsonl"
    seen: dict[str, str] = {}

    def hook(call_no: int) -> None:
        if call_no == 2:
            seen["mid"] = evidence.read_text(encoding="utf-8")
            raise m.MeasureError("중간 실패 시뮬레이션")

    history = {"push": [(1, healthy_jobs()), (2, healthy_jobs())]}
    rc, _, _ = run_main(
        m, tmp, history, "--jsonl", str(evidence), fake=FakeGitHub(history, on_jobs_call=hook)
    )
    assert rc == 2
    rows = [json.loads(line) for line in seen["mid"].splitlines()]
    assert len(rows) == 3 and {r["job"] for r in rows} == {"backend", "policy", "nightly"}, rows


def scn_annotation_is_escaped(m: ModuleType, tmp: Path) -> None:
    assert m._annotation("t", "a%b\nc") == "::error title=t::a%25b%0Ac"


def scn_specs_come_from_the_workflow_text(m: ModuleType, tmp: Path) -> None:
    """① 상한·이름은 텍스트에서 읽는다 — 값이 바뀌면 측정도 따라간다."""
    text = """
jobs:
  a:
    name: "Alpha 잡"
    timeout-minutes: 7
  b:
    timeout-minutes: 12
  c:
    name: "   "
    timeout-minutes: true
  d:
    timeout-minutes: "${{ vars.T }}"
"""
    got = {s.key: (s.name, s.limit_minutes) for s in m.load_job_specs(text)}
    assert got == {
        "a": ("Alpha 잡", 7),
        "b": ("b", 12),  # name 생략 → 키가 표시 이름
        "c": ("c", None),  # 공백 이름 → 키 · bool은 1분이 아니라 미선언
        "d": ("d", None),  # 표현식 → 상한을 알 수 없다
    }, got
    other = m.load_job_specs(text.replace("timeout-minutes: 7", "timeout-minutes: 99"))
    assert other[0].limit_minutes == 99


def scn_unreadable_workflows_are_errors(m: ModuleType, tmp: Path) -> None:
    dup = 'jobs:\n  a:\n    name: "same"\n  b:\n    name: "same"\n'
    _raises(m.MeasureError, lambda: m.load_job_specs(dup), "중복")
    _raises(m.MeasureError, lambda: m.load_job_specs("jobs: {}"), "jobs")
    _raises(m.MeasureError, lambda: m.load_job_specs("a: ["), "YAML")
    _raises(m.MeasureError, lambda: m.load_job_specs("jobs:\n  a: 3\n"), "매핑")


_SCENARIOS: list[Callable[[ModuleType, Path], None]] = [
    scn_success_is_a_sample,
    scn_timeout_cancel_is_saturated,
    scn_short_cancel_is_not_a_sample,
    scn_skipped_and_reversed_time_are_never_samples,
    scn_incomplete_job_is_excluded,
    scn_boundary_is_ok_and_just_below_is_low,
    scn_float_noise_at_the_boundary_is_ok,
    scn_threshold_is_applied,
    scn_low_follows_the_max_not_the_median,
    scn_saturated_sample_is_low_and_names_the_finished_max,
    scn_unmeasured_is_never_ok,
    scn_urls_are_built_to_see_every_run,
    scn_events_are_pooled,
    scn_zero_history_is_a_failure,
    scn_exit_zero_when_everything_has_room,
    scn_exit_one_when_a_job_is_low,
    scn_exit_two_when_a_job_cannot_be_measured,
    scn_low_outranks_unmeasured,
    scn_api_failure_is_exit_two,
    scn_unexpected_exception_is_exit_two,
    scn_only_filter_does_not_report_known_jobs_as_unmatched,
    scn_http_failures_carry_the_cause,
    scn_response_shape_is_checked,
    scn_jobs_are_paginated_and_truncation_is_an_error,
    scn_evidence_is_flushed_per_run,
    scn_annotation_is_escaped,
    scn_specs_come_from_the_workflow_text,
    scn_unreadable_workflows_are_errors,
]


class TestScenariosOnTheRealModule:
    """대조군 — 시나리오 28개가 실제 소스에서 전부 통과한다(결함 주입의 '통과해야 할 쪽')."""

    @pytest.mark.parametrize("scenario", _SCENARIOS, ids=lambda s: s.__name__)
    def test_scenario_passes(self, scenario, mod, tmp_path):
        scenario(mod, tmp_path / "s")


# ── 결함 주입 — 각 절을 깨뜨리면 지정한 시나리오가 실패해야 한다 ────────────────────────────


def _load_source(text: str, tmp: Path, name: str) -> ModuleType:
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / f"{name}.py"
    path.write_text(text, encoding="utf-8")
    return _load_path(path, name)


_MUTATIONS: list[tuple[str, str, str, Callable[[ModuleType, Path], None]]] = [
    (
        "M01 상한 도달 판정 삭제(생존자 편향 복원)",
        "minutes is not None and minutes >= SATURATION_RATIO * limit_minutes",
        "False",
        scn_timeout_cancel_is_saturated,
    ),
    (
        "M02 짧은 취소도 상한 도달로 계상",
        "minutes >= SATURATION_RATIO * limit_minutes",
        "minutes >= 0",
        scn_short_cancel_is_not_a_sample,
    ),
    (
        "M03 timed_out 결론 무시",
        'if conclusion == "timed_out":',
        "if False:",
        scn_timeout_cancel_is_saturated,
    ),
    (
        "M04 음수 소요 허용",
        "return minutes if minutes >= 0 else None",
        "return minutes",
        scn_skipped_and_reversed_time_are_never_samples,
    ),
    (
        "M05 경계를 LOW로(<=)",
        "low = ratio < threshold - _EPS",
        "low = ratio <= threshold",
        scn_boundary_is_ok_and_just_below_is_low,
    ),
    (
        "M06 부동소수점 보정 삭제",
        "low = ratio < threshold - _EPS",
        "low = ratio < threshold",
        scn_float_noise_at_the_boundary_is_ok,
    ),
    (
        "M07 기준 무시(LOW 불가)",
        "low = ratio < threshold - _EPS",
        "low = False",
        scn_threshold_is_applied,
    ),
    (
        "M08 최대 대신 중앙값",
        "max_minutes = max(s.minutes for s in samples)",
        "max_minutes = statistics.median(s.minutes for s in samples)",
        scn_low_follows_the_max_not_the_median,
    ),
    (
        "M09 완주 표본 안내 삭제",
        'tail = f" · 완주 표본 최대 {max(finished):.2f}분" if finished else " · 완주 표본 없음"',
        'tail = ""',
        scn_saturated_sample_is_low_and_names_the_finished_max,
    ),
    (
        "M10 측정 불가를 OK로 접기",
        "status=UNMEASURED,",
        "status=OK,",
        scn_unmeasured_is_never_ok,
    ),
    (
        "M11 상한 미선언 잡을 계산에 넣기",
        "if limit is None:",
        "if False:",
        scn_unmeasured_is_never_ok,
    ),
    (
        "M12 이름 불일치와 표본 부족을 같은 문구로",
        "if seen == 0:",
        "if False:",
        scn_unmeasured_is_never_ok,
    ),
    (
        "M13 성공 실행만 조회(생존자 편향)",
        "status=completed",
        "status=success",
        scn_urls_are_built_to_see_every_run,
    ),
    (
        "M14 머지 큐에 브랜치 필터",
        'if branch and event != "merge_group":',
        "if branch:",
        scn_urls_are_built_to_see_every_run,
    ),
    (
        "M15 실행 이력 0건을 통과로",
        "if sum(runs_by_event.values()) == 0:",
        "if False:",
        scn_zero_history_is_a_failure,
    ),
    (
        "M16 여유 부족을 exit 0으로",
        "    if low:\n        return EXIT_LOW",
        "    if False:\n        return EXIT_LOW",
        scn_exit_one_when_a_job_is_low,
    ),
    (
        "M17 측정 불가를 exit 0으로",
        "    if unmeasured:\n        return EXIT_UNMEASURED",
        "    if False:\n        return EXIT_UNMEASURED",
        scn_exit_two_when_a_job_cannot_be_measured,
    ),
    (
        "M18 미처리 예외를 흡수하지 않음(exit 1로 샘)",
        "except Exception as exc:",
        "except KeyError as exc:",
        scn_unexpected_exception_is_exit_two,
    ),
    (
        "M19 HTTP 상태 확인 삭제",
        'if not code.startswith("2"):',
        "if False:",
        scn_http_failures_carry_the_cause,
    ),
    (
        "M20 응답 형식 검사 삭제",
        "if not isinstance(body, dict) or key not in body:",
        "if False:",
        scn_response_shape_is_checked,
    ),
    (
        "M21 쪽수 순회 중단(첫 쪽만)",
        "len(collected) >= total",
        "True",
        scn_jobs_are_paginated_and_truncation_is_an_error,
    ),
    (
        "M22 즉시 flush 삭제",
        "jsonl.flush()",
        "pass",
        scn_evidence_is_flushed_per_run,
    ),
    (
        "M23 필터로 빠진 잡도 불일치로 계상",
        "if name not in known_names:",
        "if True:",
        scn_only_filter_does_not_report_known_jobs_as_unmatched,
    ),
    (
        "M24 주석 이스케이프 삭제",
        '.replace("%", "%25")',
        '.replace("%", "%")',
        scn_annotation_is_escaped,
    ),
    (
        "M25 중복 잡 이름 허용",
        "if name in seen:",
        "if False:",
        scn_unreadable_workflows_are_errors,
    ),
    (
        "M26 bool을 1분 상한으로 읽기",
        " and not isinstance(raw_limit, bool)",
        "",
        scn_specs_come_from_the_workflow_text,
    ),
    (
        "M27 name 무시(키만 사용)",
        "name = raw_name if isinstance(raw_name, str) and raw_name.strip() else str(key)",
        "name = str(key)",
        scn_specs_come_from_the_workflow_text,
    ),
    (
        "M28 미완료 잡 허용",
        'if job.get("status") != "completed":',
        "if False:",
        scn_incomplete_job_is_excluded,
    ),
    (
        "M29 LOW와 측정 불가의 우선순위 뒤집기",
        "    if low:\n        return EXIT_LOW\n    if unmeasured:\n        return EXIT_UNMEASURED",
        "    if unmeasured:\n        return EXIT_UNMEASURED\n    if low:\n        return EXIT_LOW",
        scn_low_outranks_unmeasured,
    ),
    (
        "M30 첫 이벤트만 조회(이벤트 합산 삭제)",
        "for event in events:\n        runs = list_runs(",
        "for event in events[:1]:\n        runs = list_runs(",
        scn_events_are_pooled,
    ),
    (
        "M31 측정 실패를 exit 1(여유 부족)로 보고",
        "    return EXIT_UNMEASURED\n\n\nif __name__",
        "    return EXIT_LOW\n\n\nif __name__",
        scn_api_failure_is_exit_two,
    ),
    (
        "M32 성공한 잡을 표본에서 제외",
        'return ("sample", minutes) if minutes is not None else ("excluded:no_time", None)',
        'return "excluded:success", None',
        scn_success_is_a_sample,
    ),
    (
        "M33 정상 상태를 여유 부족 코드로",
        "    return EXIT_OK\n",
        "    return EXIT_LOW\n",
        scn_exit_zero_when_everything_has_room,
    ),
]


class TestMutationsAreDetected:
    @pytest.mark.parametrize("case", _MUTATIONS, ids=lambda c: c[0][:3])
    def test_mutation_turns_its_scenario_red(self, case, tmp_path):
        label, old, new, scenario = case
        original = _SCRIPT.read_bytes()
        src = original.decode("utf-8")
        # 주입의 실재 — 치환 대상이 정확히 1건이고 결과가 원본과 다르다(조용한 미적용 금지).
        assert src.count(old) == 1, f"{label}: 치환 대상이 {src.count(old)}건이다"
        mutated = src.replace(old, new)
        assert mutated != src, f"{label}: 주입이 적용되지 않았다"
        name = f"_ops100_mut_{label[:3].lower()}"
        mutant = _load_source(mutated, tmp_path / "mut", name)  # 임포트 실패는 '검출'이 아니다
        try:
            with pytest.raises(Exception):  # noqa: B017 — 어떤 실패든 검출로 본다
                scenario(mutant, tmp_path / "scn")
        finally:
            sys.modules.pop(name, None)
        assert _SCRIPT.read_bytes() == original, "원본 소스가 변했다"

    def test_every_scenario_is_exercised_by_a_mutation(self):
        """밟히지 않는 시나리오가 없다 — 주입이 닿지 않는 시나리오는 보호가 아니다."""
        covered = {case[3] for case in _MUTATIONS}
        missing = [s.__name__ for s in _SCENARIOS if s not in covered]
        assert not missing, f"결함 주입이 닿지 않는 시나리오: {missing}"


# ── 실제 ci.yml 과의 관계 ───────────────────────────────────────────────────


class TestAgainstTheRealWorkflow:
    def test_every_ci_job_declares_an_integer_timeout(self, mod):
        """상한을 모르는 잡은 측정할 수 없다(기본 360분이 폭주를 가린다) — 신규 잡 추가 시 걸린다."""
        specs = mod.load_job_specs(_CI_YML.read_text(encoding="utf-8"), "ci.yml")
        assert specs, "ci.yml에서 잡을 하나도 못 읽었다 — 파서가 깨졌다"
        undeclared = [s.key for s in specs if s.limit_minutes is None]
        assert not undeclared, f"timeout-minutes를 정수로 선언하지 않은 잡: {undeclared}"

    def test_limits_match_an_independent_parse(self, mod):
        raw = yaml.safe_load(_CI_YML.read_text(encoding="utf-8"))["jobs"]
        specs = {s.key: s for s in mod.load_job_specs(_CI_YML.read_text(encoding="utf-8"))}
        assert set(specs) == set(raw)
        for key, job in raw.items():
            assert specs[key].limit_minutes == job["timeout-minutes"], key

    def test_nightly_only_jobs_are_reachable_through_the_default_events(self, mod):
        """schedule을 빼면 야간 전용 잡이 영구 UNMEASURED가 된다 — 기본 이벤트가 그것을 덮는다."""
        text = _CI_YML.read_text(encoding="utf-8")
        raw = yaml.safe_load(text)["jobs"]
        nightly_only = [
            k
            for k, j in raw.items()
            if str(j.get("if", "")).strip() == "github.event_name == 'schedule'"
        ]
        assert nightly_only, "야간 전용 잡을 하나도 못 찾았다 — 이 검사가 공허하다"
        assert "schedule" in mod.DEFAULT_EVENTS

    def test_the_script_is_covered_by_the_repo_wide_api_and_ca_governance(self):
        """test_github_api_auth·test_proxy_ca_optional은 '리터럴을 가진 스크립트'를 자동 스캔한다.
        헬퍼를 다른 파일로 옮겨 이 스크립트가 스캔에서 빠지면 보호가 조용히 사라진다."""
        src = _SCRIPT.read_text(encoding="utf-8")
        assert "api.github.com" in src and "/root/.ccr/ca-bundle.crt" in src


# ── 워크플로 배선 ───────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    if not _WORKFLOW.exists():
        pytest.fail(f"워크플로 부재: {_WORKFLOW} — 감시가 고아 상태다")
    doc = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(doc, dict) and doc.get(
        "jobs"
    ), "워크플로가 비었다 — 파싱 성공을 통과로 읽지 않는다"
    return doc


def _steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    steps = [s for job in workflow["jobs"].values() for s in job.get("steps", [])]
    assert steps, "스텝이 없다"
    return steps


def _measure_step(workflow: dict[str, Any]) -> dict[str, Any]:
    found = [
        s for s in _steps(workflow) if "measure_ci_job_timeout_headroom.py" in str(s.get("run"))
    ]
    assert len(found) == 1, f"측정 스텝이 {len(found)}개다 — 고아이거나 중복이다"
    return found[0]


class TestWorkflowWiring:
    def test_runs_on_a_schedule_and_on_demand_only(self, workflow):
        triggers = workflow.get("on", workflow.get(True))  # PyYAML은 `on:`을 True 키로 읽는다
        assert isinstance(triggers, dict), triggers
        assert set(triggers) == {
            "schedule",
            "workflow_dispatch",
        }, "push·pull_request로 돌리면 main 커밋마다 적색이 반복돼 습관화된다: " + str(
            set(triggers)
        )
        crons = [c["cron"] for c in triggers["schedule"]]
        assert crons and all(len(c.split()) == 5 for c in crons), crons

    def test_can_read_actions_and_cannot_write(self, workflow):
        """권한을 명시하면 나머지는 none이다 — actions: read가 없으면 실행 목록 조회가 403이다."""
        perms = workflow["permissions"]
        assert perms.get("actions") == "read" and perms.get("contents") == "read", perms
        for job in workflow["jobs"].values():
            assert "write" not in str(
                job.get("permissions", {})
            ), "관측 잡에 쓰기 권한이 새면 안 된다"
        assert "write" not in str(perms)

    def test_the_token_reaches_the_measure_step(self, workflow):
        """스크립트가 읽을 준비가 돼 있어도 워크플로가 안 넘기면 미인증(60req/h)이다."""
        env = _measure_step(workflow).get("env") or {}
        assert "github.token" in str(env.get("GITHUB_TOKEN")), env

    def test_failure_is_not_hidden(self, workflow):
        text = yaml.safe_dump(workflow)
        for forbidden in ("continue-on-error", "|| true", "set +e"):
            assert forbidden not in text, f"실패 은닉 구문: {forbidden}"
        run = str(_measure_step(workflow)["run"])
        assert "| tail" not in run and " -q" not in run, "출력을 자르거나 죽이고 판정하지 않는다"

    def test_evidence_and_summary_are_kept(self, workflow):
        run = str(_measure_step(workflow)["run"])
        assert "--jsonl" in run and "--summary" in run and "GITHUB_STEP_SUMMARY" in run
        upload = [s for s in _steps(workflow) if "upload-artifact" in str(s.get("uses"))]
        assert upload and upload[0].get("if") == "always()", "측정이 실패해도 증거는 남아야 한다"

    def test_repository_comes_from_the_environment(self, workflow):
        text = _WORKFLOW.read_text(encoding="utf-8")
        assert "doldori7/" not in text and "kiki-s-broom/" not in text, "저장소 리터럴 금지"

    def test_the_job_has_a_bounded_budget_and_its_own_concurrency_group(self, workflow):
        job = next(iter(workflow["jobs"].values()))
        assert isinstance(job["timeout-minutes"], int) and job["timeout-minutes"] <= 15
        assert workflow["concurrency"]["group"] == "ci-timeout-headroom"
        assert workflow["concurrency"]["cancel-in-progress"] is False

    def test_dependency_is_upper_bounded(self, workflow):
        installs = [str(s["run"]) for s in _steps(workflow) if "pip install" in str(s.get("run"))]
        assert installs and all(re.search(r"<\d", i) for i in installs), installs


# ── 호환 진입점 ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def shim() -> ModuleType:
    return _load_path(_SHIM, "_ops100_shim")


class TestCompatibilityEntryPoint:
    def test_old_cli_maps_to_the_generalized_tool(self, shim):
        assert shim.build_argv(["o/r"]) == ["o/r", "--branch", "main", "--only", "backend"]
        assert shim.build_argv(["o/r", "dev", "--n", "7"]) == [
            "o/r", "--branch", "dev", "--only", "backend", "--n", "7",
        ]  # fmt: skip

    def test_main_delegates_and_returns_the_exit_code(self, shim):
        seen: list[Any] = []

        def fake_main(argv: Any = None, **kw: Any) -> int:
            seen.append(list(argv))
            return 7

        with mock.patch.object(shim._generalized, "main", fake_main):
            assert shim.main(["o/r"]) == 7
        assert seen == [["o/r", "--branch", "main", "--only", "backend"]]

    def test_the_old_path_still_exists_for_the_documents_that_name_it(self):
        assert _SHIM.exists()
