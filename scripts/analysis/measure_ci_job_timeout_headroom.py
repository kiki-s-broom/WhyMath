#!/usr/bin/env python3
"""OPS-100 — CI 잡별 타임아웃 여유 상시 감시 (OPS-47 측정기의 전 잡 일반화).

**왜 이 도구인가**: CI 잡의 시간 예산(`timeout-minutes`) 소진이 4회 반복됐고 매번
그 자리 조치(상향·분할)로만 끝났다 — 2026-07-25 backend 25분 초과 · 08-21 backend
여유 16%(OPS-47) · 09-01 backend 37.5분 > 35 · 09-28 harness-integrity 5분 초과로
머지 큐 전면 차단(OPS-69). 상시 감시 장치는 없었다. 정적 테스트(OPS-69)는 *상한이
되돌려지는 것*만 막을 뿐, 실제 소요가 상한에 다가가는 것은 실행 이력 없이는 못 본다.

**무엇을 재는가**: 최근 실행들에서 잡별 최대 소요를 구해 `timeout-minutes` 대비
여유율을 낸다. 상한은 `ci.yml`에서 직접 읽는다(하드코딩 금지 — 상한이 바뀌면 측정도
따라간다). 여유율이 기준(기본 30% — OPS-47 기준) 미만인 잡이 있으면 exit 1.

실측으로 확인한 API 사실 (2026-10-08, 실제 응답)
-----------------------------------------------
· 잡의 `name`은 `ci.yml`의 `name:`과 글자 그대로 일치한다.
· 건너뛴 잡(`skipped`)은 `started_at`이 `completed_at`보다 1초 늦은 행이 있다
  (음수 소요) — 소요를 계산하기 전에 결론으로 거르고, 음수 소요는 표본으로 쓰지 않는다.
· 머지 큐 실행의 `head_branch`는 `gh-readonly-queue/main/...`이다 — `branch=main`을
  걸면 머지 큐 실행이 통째로 빠진다. 그래서 이벤트별로 따로 조회하고 `merge_group`엔
  브랜치 필터를 걸지 않는다.
· 동시성 취소(`cancel-in-progress`)로 잘린 잡도 결론이 `cancelled`다(야간 직렬 스위트가
  상한 45분의 14분에서 취소된 실측) — 타임아웃과 결론만으로는 구별되지 않는다.

설계 계약 (CLAUDE.md 준수)
-------------------------
① **생존자 편향 금지**: 기존 측정기는 `status=success` 실행·`conclusion=success` 잡만
   봤다 — 타임아웃으로 죽은 잡이 표본에서 빠져 *가장 위험한 표본이 사라진다*. 여기서는
   완료된 실행 전부를 보고, 상한의 95% 이상 달린 취소·실패 잡(과 `timed_out`)을
   '상한 도달'로 센다. 짧게 끊긴 취소·실패는 표본이 아니다(전체 길이를 모른다).
② **모른다 ≠ 아니다**: API 거부(403)·실행 이력 0건·잡 이름 불일치·표본 0건·상한 미선언은
   '여유 충분'으로 접지 않고 UNMEASURED(exit 2)로 드러낸다.
③ **실패해도 증거가 남는다**: `--jsonl`을 주면 잡 관측을 실행 1건마다 즉시 flush한다.
④ **실패 원인이 남는다**: HTTP 상태·응답 본문 앞부분·예외 타입명을 담는다.
⑤ **모든 외부 호출에 타임아웃**을 건다.
⑥ **판정은 exit code**: 0 정상 / 1 여유 부족 / 2 측정 불가. 예기치 않은 예외도 2로
   흡수한다 — 파이썬의 미처리 예외 종료 코드가 1이라 '여유 부족'으로 오독되기 때문이다.

이벤트에 `schedule`을 넣은 이유: `e2e-nightly`·`backend-serial-nightly`(상한 45분)는
`schedule`에서만 돈다. 빼면 두 잡이 영구 UNMEASURED가 되어 이 감시가 상시 적색이 된다.

사용:
    python3 scripts/analysis/measure_ci_job_timeout_headroom.py [owner/repo] [옵션]
    (repo 생략 시 환경변수 GITHUB_REPOSITORY)

exit code
    0 — 모든 잡이 기준 이상의 여유
    1 — 여유 부족 잡 있음(상한 도달 포함)
    2 — 측정 자체가 불가하거나 일부 잡을 못 쟀음 — "여유 충분"으로 읽지 말 것
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import traceback
from collections import Counter
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

import yaml

API = "https://api.github.com"
TIMEOUT = 30
_CA_PATH = "/root/.ccr/ca-bundle.crt"  # 에이전트 프록시 CA (있을 때만 사용)
_CI_YML = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"

DEFAULT_EVENTS = ("push", "merge_group", "schedule")
DEFAULT_RUNS_PER_EVENT = 20
MIN_HEADROOM_RATIO = 0.30  # OPS-47 기준: 최대 표본 소요가 상한의 70% 이하(여유 30% 이상)
SATURATION_RATIO = 0.95  # 취소·실패 잡이 상한의 이 비율 이상 달렸으면 타임아웃 도달로 본다
_EPS = 1e-9  # 경계(정확히 30%)를 부동소수점 오차 없이 '충분'으로 판정하기 위한 여유
_MAX_JOB_PAGES = 10
_PER_PAGE_CAP = 100

EXIT_OK = 0
EXIT_LOW = 1
EXIT_UNMEASURED = 2

OK = "OK"
LOW = "LOW"
UNMEASURED = "UNMEASURED"

Getter = Callable[[str], object]


class MeasureError(Exception):
    """측정 자체가 불가능한 상태 — '여유 충분'으로 읽히면 안 되는 모든 실패."""


# ── 자료 구조 ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class JobSpec:
    """ci.yml이 선언한 잡 하나. limit_minutes가 None이면 상한을 알 수 없는 잡이다."""

    key: str
    name: str
    limit_minutes: int | None


@dataclass(frozen=True)
class Sample:
    run_id: int
    event: str
    minutes: float
    saturated: bool  # 상한에 닿아 끊긴 관측이면 True


@dataclass(frozen=True)
class JobReport:
    key: str
    name: str
    limit_minutes: int | None
    status: str
    samples: int
    saturated: int
    max_minutes: float | None
    median_minutes: float | None
    headroom_minutes: float | None
    headroom_ratio: float | None
    note: str


@dataclass
class Measurement:
    reports: list[JobReport]
    runs_by_event: dict[str, int]
    unmatched_names: list[str] = field(default_factory=list)


# ── GitHub API (HARN-02·ARCH 거버넌스: 인증 헬퍼·CA 가드·curl 인자 스플라이스) ──


def _auth_args() -> list[str]:
    """토큰이 있으면 `["-H", "Authorization: Bearer <token>"]`, 없으면 `[]`.

    미인증 한도(IP당 60req/h)는 GitHub 러너처럼 IP를 공유하는 환경에서 상시
    소진 상태다 — `measure_merge_gate_latency.py`와 동일 사유.
    """
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    return ["-H", f"Authorization: Bearer {token}"] if token else []


def _ca_args() -> list[str]:
    """프록시 CA를 쓸 수 있으면 `["--cacert", <경로>]`, 아니면 `[]`.

    존재 검사를 예외로 감싼다 — `Path.exists()`는 EACCES를 전파한다(2026-09-01
    main red 실측 교훈).
    """
    try:
        with open(_CA_PATH, "rb"):
            return ["--cacert", _CA_PATH]
    except OSError:
        return []


def _get(path: str) -> object:
    """GitHub API GET — 실패 시 HTTP 상태·본문·예외 타입을 남긴다(원인 없는 실패 금지)."""
    cmd = [
        "curl",
        "-sS",
        "-L",  # 이관 리다이렉트 추종 — 301 본문을 데이터로 오독하지 않기 위해
        "--max-time",
        str(TIMEOUT),
        *_ca_args(),
        *_auth_args(),
        "-H",
        "Accept: application/vnd.github+json",
        "-w",
        "\n%{http_code}",  # 본문 뒤 마지막 줄에 HTTP 상태를 붙인다
        f"{API}{path}",
    ]
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",  # HARN-19 — 로케일(cp949) 디코드 금지
            timeout=TIMEOUT + 10,
        )
    except subprocess.TimeoutExpired as exc:
        raise MeasureError(f"{type(exc).__name__}: 타임아웃({TIMEOUT}s) — {path}") from exc
    except OSError as exc:  # curl 미설치·실행 불가
        raise MeasureError(f"{type(exc).__name__}: curl 실행 실패 — {path}") from exc
    if out.returncode != 0:
        raise MeasureError(f"curl 실패(rc={out.returncode}) — {path}\n{out.stderr[:500]}")
    body, _, code = out.stdout.rpartition("\n")
    if not code.startswith("2"):
        raise MeasureError(f"HTTP {code or '?'} — {path}\n본문 앞 300자: {body[:300]}")
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise MeasureError(
            f"{type(exc).__name__}: JSON 파싱 실패 — {path}\n본문 앞 300자: {body[:300]}"
        ) from exc


# ── ci.yml 파싱 ─────────────────────────────────────────────────────────────


def load_job_specs(text: str, source: str = "ci.yml") -> list[JobSpec]:
    """워크플로 텍스트에서 잡 이름·상한을 읽는다. 읽을 수 없으면 예외(통과로 위장 금지)."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise MeasureError(f"{type(exc).__name__}: {source} YAML 파싱 실패") from exc
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    if not isinstance(jobs, dict) or not jobs:
        raise MeasureError(f"{source}: jobs 블록이 비었다 — 워크플로 구조 변경?")
    specs: list[JobSpec] = []
    seen: dict[str, str] = {}
    for key, job in jobs.items():
        if not isinstance(job, dict):
            raise MeasureError(f"{source}: 잡 '{key}'가 매핑이 아니다")
        raw_name = job.get("name")
        name = raw_name if isinstance(raw_name, str) and raw_name.strip() else str(key)
        if name in seen:
            raise MeasureError(
                f"{source}: 잡 이름 '{name}'이 '{seen[name]}'와 '{key}'에 중복 — "
                "API는 이름으로만 잡을 구별하므로 측정이 모호해진다"
            )
        seen[name] = str(key)
        raw_limit = job.get("timeout-minutes")
        # bool은 int의 하위 타입이다 — `true`를 1분으로 읽지 않는다.
        valid = isinstance(raw_limit, int) and not isinstance(raw_limit, bool) and raw_limit > 0
        specs.append(JobSpec(key=str(key), name=name, limit_minutes=raw_limit if valid else None))
    return specs


# ── 관측 → 표본 (순수 함수) ─────────────────────────────────────────────────


def _ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def job_minutes(job: dict[str, Any]) -> float | None:
    """잡의 러너 실행 시간(분). 시각 결손·역전(음수)이면 None — 표본으로 쓰지 않는다."""
    start, done = _ts(job.get("started_at")), _ts(job.get("completed_at"))
    if start is None or done is None:
        return None
    minutes = (done - start).total_seconds() / 60
    return minutes if minutes >= 0 else None


def classify_job(job: dict[str, Any], limit_minutes: int) -> tuple[str, float | None]:
    """잡 관측 1건을 분류한다 → (종류, 소요분).

    종류: `sample`(정상 완주) · `saturated`(상한 도달) · `excluded:<사유>`(표본 아님).
    취소·실패는 *얼마나 달렸는지*로 가른다 — 상한 가까이 달렸으면 타임아웃이고, 짧게
    끊겼으면 전체 길이를 모르는 관측이라 표본이 될 수 없다(동시성 취소 등).
    """
    if job.get("status") != "completed":
        return "excluded:incomplete", None
    conclusion = job.get("conclusion")
    minutes = job_minutes(job)
    if conclusion == "success":
        return ("sample", minutes) if minutes is not None else ("excluded:no_time", None)
    if conclusion == "timed_out":
        return "saturated", minutes if minutes is not None else float(limit_minutes)
    if conclusion in ("cancelled", "failure"):
        if minutes is not None and minutes >= SATURATION_RATIO * limit_minutes:
            return "saturated", minutes
    return f"excluded:{conclusion}", None


# ── 판정 (순수 함수) ────────────────────────────────────────────────────────


def evaluate_job(
    spec: JobSpec,
    samples: Sequence[Sample],
    excluded: Counter[str],
    seen: int,
    threshold: float = MIN_HEADROOM_RATIO,
) -> JobReport:
    """잡 하나의 판정. 표본이 없거나 상한을 모르면 UNMEASURED — OK로 접지 않는다."""

    def unmeasured(note: str) -> JobReport:
        return JobReport(
            key=spec.key,
            name=spec.name,
            limit_minutes=spec.limit_minutes,
            status=UNMEASURED,
            samples=len(samples),
            saturated=0,
            max_minutes=None,
            median_minutes=None,
            headroom_minutes=None,
            headroom_ratio=None,
            note=note,
        )

    limit = spec.limit_minutes
    if limit is None:
        return unmeasured("timeout-minutes를 정수로 선언하지 않았다 — 상한을 알 수 없다")
    if not samples:
        if seen == 0:
            return unmeasured(
                "API 응답에서 이 잡 이름이 한 번도 관측되지 않았다 — 이름 변경·불일치 의심"
            )
        reasons = ", ".join(f"{k}×{v}" for k, v in sorted(excluded.items())) or "없음"
        return unmeasured(f"관측 {seen}건이나 유효 표본 0건 (제외: {reasons})")
    max_minutes = max(s.minutes for s in samples)
    median = statistics.median(s.minutes for s in samples)
    headroom = limit - max_minutes
    ratio = headroom / limit
    saturated = sum(1 for s in samples if s.saturated)
    low = ratio < threshold - _EPS
    note = ""
    if saturated:
        # 서서히 느려진 잡(처방: 상한·분할)과 한 번 멈춘 잡(처방: 스텝 타임아웃)은 완주
        # 표본이 갈라 준다 — 정상 실행이 상한에서 멀면 후자다(2026-10-06 data-pipeline 실측).
        finished = [s.minutes for s in samples if not s.saturated]
        tail = f" · 완주 표본 최대 {max(finished):.2f}분" if finished else " · 완주 표본 없음"
        note = f"상한 도달 {saturated}회 — 타임아웃으로 끊긴 실행이 있다{tail}"
    return JobReport(
        key=spec.key,
        name=spec.name,
        limit_minutes=limit,
        status=LOW if low else OK,
        samples=len(samples),
        saturated=saturated,
        max_minutes=max_minutes,
        median_minutes=median,
        headroom_minutes=headroom,
        headroom_ratio=ratio,
        note=note,
    )


# ── 측정 (API 경유) ─────────────────────────────────────────────────────────


def _expect_dict(body: object, key: str, path: str) -> dict[str, Any]:
    if not isinstance(body, dict) or key not in body:
        detail = body.get("message") if isinstance(body, dict) else type(body).__name__
        raise MeasureError(f"응답 형식 이상('{key}' 없음) — {path}\n내용: {detail}")
    return body


def list_runs(
    get: Getter, repo: str, workflow: str, event: str, branch: str | None, n: int
) -> list[dict[str, Any]]:
    """한 이벤트의 최근 완료 실행. 성공만 보지 않는다 — 타임아웃 실행이 빠지면 안 된다."""
    query = f"event={event}&status=completed&per_page={min(n, _PER_PAGE_CAP)}"
    # 머지 큐 실행의 head_branch는 gh-readonly-queue/... 다 — branch 필터를 걸면 전부 빠진다.
    if branch and event != "merge_group":
        query += f"&branch={branch}"
    path = f"/repos/{repo}/actions/workflows/{workflow}/runs?{query}"
    runs = _expect_dict(get(path), "workflow_runs", path)["workflow_runs"]
    if not isinstance(runs, list):
        raise MeasureError(f"workflow_runs가 목록이 아니다 — {path}")
    return runs[:n]


def list_jobs(get: Getter, repo: str, run_id: int) -> list[dict[str, Any]]:
    """실행 1건의 잡 전부(최신 시도). 절단된 목록을 완전한 것처럼 쓰지 않는다."""
    collected: list[dict[str, Any]] = []
    for page in range(1, _MAX_JOB_PAGES + 1):
        path = (
            f"/repos/{repo}/actions/runs/{run_id}/jobs"
            f"?filter=latest&per_page={_PER_PAGE_CAP}&page={page}"
        )
        body = _expect_dict(get(path), "jobs", path)
        jobs = body["jobs"]
        if not isinstance(jobs, list):
            raise MeasureError(f"jobs가 목록이 아니다 — {path}")
        collected.extend(jobs)
        total = body.get("total_count")
        if not jobs or (isinstance(total, int) and len(collected) >= total):
            return collected
    raise MeasureError(f"실행 {run_id}의 잡 목록이 {_MAX_JOB_PAGES}쪽을 넘어 절단됐다")


def run_measurement(
    get: Getter,
    repo: str,
    specs: Sequence[JobSpec],
    *,
    workflow: str = "ci.yml",
    events: Sequence[str] = DEFAULT_EVENTS,
    branch: str | None = "main",
    n: int = DEFAULT_RUNS_PER_EVENT,
    threshold: float = MIN_HEADROOM_RATIO,
    jsonl: TextIO | None = None,
    out: TextIO | None = None,
    known_names: Collection[str] = (),
) -> Measurement:
    # known_names = 필터(--only)로 측정 대상에서 빠졌을 뿐 ci.yml에는 있는 잡 이름들.
    # 이것까지 '불일치'로 세면 이름 변경 탐지(계약 ②)가 소음이 된다.
    by_name = {s.name: s for s in specs}
    samples: dict[str, list[Sample]] = {s.key: [] for s in specs}
    excluded: dict[str, Counter[str]] = {s.key: Counter() for s in specs}
    seen: Counter[str] = Counter()
    unmatched: Counter[str] = Counter()
    runs_by_event: dict[str, int] = {}

    def say(line: str) -> None:
        print(line, file=out or sys.stdout, flush=True)

    for event in events:
        runs = list_runs(get, repo, workflow, event, branch, n)
        runs_by_event[event] = len(runs)
        say(f"[{event}] 완료 실행 {len(runs)}건 조회")
        for run in runs:
            run_id = int(run["id"])
            for job in list_jobs(get, repo, run_id):
                name = job.get("name")
                spec = by_name.get(name) if isinstance(name, str) else None
                if spec is None:
                    if name not in known_names:
                        unmatched[str(name)] += 1
                    continue
                seen[spec.key] += 1
                if spec.limit_minutes is None:
                    kind, minutes = "excluded:no_limit", None
                else:
                    kind, minutes = classify_job(job, spec.limit_minutes)
                if kind in ("sample", "saturated") and minutes is not None:
                    samples[spec.key].append(
                        Sample(run_id, event, minutes, saturated=kind == "saturated")
                    )
                else:
                    excluded[spec.key][kind] += 1
                if jsonl is not None:  # 즉시 flush — 중간에 죽어도 그 시점까지의 증거가 남는다
                    jsonl.write(
                        json.dumps(
                            {
                                "run_id": run_id,
                                "event": event,
                                "job": spec.key,
                                "conclusion": job.get("conclusion"),
                                "kind": kind,
                                "minutes": minutes,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    jsonl.flush()
    if sum(runs_by_event.values()) == 0:
        raise MeasureError(
            f"완료된 실행 이력 0건 (이벤트 {', '.join(events)}) — 표본 없음, 측정 실패"
        )
    reports = [
        evaluate_job(s, samples[s.key], excluded[s.key], seen[s.key], threshold) for s in specs
    ]
    return Measurement(reports, runs_by_event, sorted(unmatched))


# ── 출력 ────────────────────────────────────────────────────────────────────


def _order(report: JobReport) -> tuple[int, float]:
    rank = {LOW: 0, UNMEASURED: 1, OK: 2}[report.status]
    return rank, report.headroom_ratio if report.headroom_ratio is not None else 0.0


def _fmt(value: float | None, spec: str) -> str:
    return "-" if value is None else format(value, spec)


def render_table(reports: Sequence[JobReport], threshold: float) -> str:
    head = (
        f"{'잡':<26} {'상한':>4} {'표본':>4} {'최대(분)':>8} {'중앙(분)':>8} "
        f"{'여유(분)':>8} {'여유율':>7}  판정"
    )
    lines = [head, "-" * len(head)]
    for r in sorted(reports, key=_order):
        ratio = "-" if r.headroom_ratio is None else f"{r.headroom_ratio * 100:.1f}%"
        limit = "-" if r.limit_minutes is None else str(r.limit_minutes)
        lines.append(
            f"{r.key:<26} {limit:>4} {r.samples:>4} {_fmt(r.max_minutes, '.2f'):>8} "
            f"{_fmt(r.median_minutes, '.2f'):>8} {_fmt(r.headroom_minutes, '.2f'):>8} "
            f"{ratio:>7}  {r.status}" + (f"  — {r.note}" if r.note else "")
        )
    lines.append(f"기준: 여유율 {threshold * 100:.0f}% 미만이면 LOW (최대 표본 기준)")
    return "\n".join(lines)


def render_markdown(m: Measurement, threshold: float) -> str:
    rows = [
        "| 잡 | 상한(분) | 표본 | 최대(분) | 여유(분) | 여유율 | 판정 | 비고 |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for r in sorted(m.reports, key=_order):
        ratio = "-" if r.headroom_ratio is None else f"{r.headroom_ratio * 100:.1f}%"
        rows.append(
            f"| `{r.key}` | {r.limit_minutes or '-'} | {r.samples} | "
            f"{_fmt(r.max_minutes, '.2f')} | {_fmt(r.headroom_minutes, '.2f')} | {ratio} | "
            f"**{r.status}** | {r.note} |"
        )
    runs = ", ".join(f"{k} {v}건" for k, v in m.runs_by_event.items())
    return (
        f"## CI 잡 타임아웃 여유 (기준 {threshold * 100:.0f}% 미만이면 LOW)\n\n"
        + "\n".join(rows)
        + f"\n\n조회한 완료 실행: {runs}\n"
    )


def _annotation(title: str, message: str) -> str:
    """GitHub Actions 워크플로 명령 이스케이프(`%`·개행) — 사람 눈에 띄는 오류 표시."""
    esc = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return f"::error title={title}::{esc}"


# ── 진입점 ──────────────────────────────────────────────────────────────────


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="CI 잡별 타임아웃 여유 감시 (OPS-100)")
    p.add_argument("repo", nargs="?", help="owner/repo (생략 시 환경변수 GITHUB_REPOSITORY)")
    p.add_argument("--workflow", default="ci.yml", help="대상 워크플로 파일명")
    p.add_argument("--ci-yml", type=Path, default=_CI_YML, help="상한을 읽을 로컬 워크플로 파일")
    p.add_argument("--events", default=",".join(DEFAULT_EVENTS), help="쉼표 구분 이벤트")
    p.add_argument("--branch", default="main", help="push·schedule 실행의 브랜치")
    p.add_argument("--n", type=int, default=DEFAULT_RUNS_PER_EVENT, help="이벤트별 최근 실행 수")
    p.add_argument("--min-headroom", type=float, default=MIN_HEADROOM_RATIO)
    p.add_argument("--only", default="", help="쉼표 구분 잡 키로 한정(예: backend)")
    p.add_argument("--jsonl", type=Path, help="잡 관측을 즉시 flush할 경로")
    p.add_argument("--summary", type=Path, help="마크다운 요약을 덧붙일 경로($GITHUB_STEP_SUMMARY)")
    return p.parse_args(argv)


def _run(args: argparse.Namespace, get: Getter) -> int:
    repo = args.repo or os.environ.get("GITHUB_REPOSITORY", "")
    if not repo or "/" not in repo:
        raise MeasureError("저장소를 알 수 없다 — owner/repo 인자 또는 GITHUB_REPOSITORY 필요")
    if args.n < 1:
        raise MeasureError(f"--n은 1 이상이어야 한다: {args.n}")
    if not 0 < args.min_headroom < 1:
        raise MeasureError(f"--min-headroom은 0과 1 사이여야 한다: {args.min_headroom}")
    events = [e for e in args.events.split(",") if e]
    if not events:
        raise MeasureError("--events가 비었다")
    try:
        text = args.ci_yml.read_text(encoding="utf-8")
    except OSError as exc:
        raise MeasureError(
            f"{type(exc).__name__}: 워크플로 파일을 읽을 수 없다 — {args.ci_yml}"
        ) from exc
    specs = load_job_specs(text, str(args.ci_yml))
    known_names = {s.name for s in specs}
    only = [k for k in args.only.split(",") if k]
    if only:
        unknown = sorted(set(only) - {s.key for s in specs})
        if unknown:
            raise MeasureError(f"ci.yml에 없는 잡 키: {', '.join(unknown)}")
        specs = [s for s in specs if s.key in only]

    jsonl = args.jsonl.open("w", encoding="utf-8") if args.jsonl else None
    try:
        m = run_measurement(
            get,
            repo,
            specs,
            workflow=args.workflow,
            events=events,
            branch=args.branch,
            n=args.n,
            threshold=args.min_headroom,
            jsonl=jsonl,
            known_names=known_names,
        )
    finally:
        if jsonl is not None:
            jsonl.close()

    print()
    print(render_table(m.reports, args.min_headroom))
    if m.unmatched_names:
        print(f"\nci.yml에 없는 잡 이름(API 관측): {', '.join(m.unmatched_names)}")
    low = [r for r in m.reports if r.status == LOW]
    unmeasured = [r for r in m.reports if r.status == UNMEASURED]
    ok_count = len(m.reports) - len(low) - len(unmeasured)
    print(f"\n요약: LOW {len(low)} · UNMEASURED {len(unmeasured)} · OK {ok_count}")

    if args.summary:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write(render_markdown(m, args.min_headroom))
    in_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    if in_actions:
        for r in low:
            ratio = f"{(r.headroom_ratio or 0) * 100:.1f}%"
            print(
                _annotation(
                    "CI 잡 시간 여유 부족",
                    f"{r.key}: 여유 {ratio} < {args.min_headroom * 100:.0f}% "
                    f"(최대 {r.max_minutes:.2f}분 / 상한 {r.limit_minutes}분) {r.note}".strip(),
                )
            )
        for r in unmeasured:
            print(_annotation("CI 잡 시간 측정 불가", f"{r.key}: {r.note}"))
    if low:
        return EXIT_LOW
    if unmeasured:
        return EXIT_UNMEASURED
    return EXIT_OK


def main(argv: Sequence[str] | None = None, *, get: Getter | None = None) -> int:
    args = _parse(argv)
    try:
        return _run(args, get or _get)
    except MeasureError as exc:
        message = f"측정 실패 — {exc}"
    except Exception as exc:  # noqa: BLE001 — 미처리 예외의 종료 코드(1)가 '여유 부족'과 겹친다
        traceback.print_exc()
        message = f"측정 실패(예기치 않은 {type(exc).__name__}) — {exc}"
    print(f"❌ {message}", file=sys.stderr, flush=True)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(_annotation("CI 잡 시간 측정 불가", message))
    return EXIT_UNMEASURED


if __name__ == "__main__":
    raise SystemExit(main())
