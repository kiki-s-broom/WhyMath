#!/usr/bin/env python3
"""OPS-47 ① — backend 잡 타임아웃 여유 실측 (재현 가능 명령).

**왜 이 스크립트인가**: OPS-47 등재 시(2026-08-21) 측정은 커밋 01ff6041 무렵
main push 11표본을 손으로 GitHub API 조회해 얻은 1회성 수치였다 — 최소/중앙/최대
20.9/28.2/29.4분, 상한 35분 대비 최대 표본 기준 여유 5.6분(16%). 그 직후
pytest-xdist 병렬화(OPS-58, 2026-08-31~09-01 착지, `-n auto --dist loadfile`)가
pytest 스텝을 26분대에서 14~15분대로 줄였는데, 그 효과가 *타임아웃 여유*에
실제로 반영됐는지는 다시 재야 안다 — "적용 후만 재고 통과 선언 금지"
(CLAUDE.md 변별력 양방향 규칙). 이 스크립트는 그 재측정을 반복 가능하게 만든다.

timeout-minutes는 하드코딩하지 않고 **로컬 워크플로 파일에서 직접 읽는다** —
상한이 다시 바뀌면(올리거나 내리면) 이 측정도 조용히 낡지 않고 따라간다.

사용:
    python3 scripts/analysis/measure_backend_job_timeout_headroom.py <owner/repo> [branch] [--n N]

실패 경로 설계(2026-08-22 규칙): 단계마다 즉시 출력하고, 실패는 원인(HTTP 본문·
예외 타입)을 남기며, 모든 외부 호출에 타임아웃을 건다. 표본 0건은 "통과"가 아니라
명시적 실패다.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path

API = "https://api.github.com"
TIMEOUT = 30
_CA_PATH = "/root/.ccr/ca-bundle.crt"  # 에이전트 프록시 CA (있을 때만 사용)
_CI_YML = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
_JOB_NAME = "backend — lint·type·test"


def _auth_args() -> list[str]:
    """토큰이 있으면 `["-H", "Authorization: Bearer <token>"]`, 없으면 `[]`.

    미인증 한도(IP당 60req/h)는 GitHub 러너처럼 IP를 공유하는 환경에서 상시
    소진 상태다 — HARN-32의 `measure_merge_gate_latency.py`와 동일 사유.
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
    """GitHub API GET — 실패 시 원인을 본문째 남긴다(예외 타입만으로는 구별 불가)."""
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
        raise SystemExit(f"❌ 타임아웃({TIMEOUT}s): {path}") from exc
    if out.returncode != 0:
        raise SystemExit(f"❌ curl 실패(rc={out.returncode}): {path}\n{out.stderr[:500]}")
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"❌ JSON 파싱 실패: {path}\n응답 앞 500자: {out.stdout[:500]}") from exc


def backend_timeout_minutes() -> int:
    """ci.yml에서 backend 잡의 timeout-minutes를 직접 읽는다(하드코딩 금지)."""
    if not _CI_YML.exists():
        raise SystemExit(f"❌ 워크플로 파일을 찾을 수 없음: {_CI_YML}")
    text = _CI_YML.read_text(encoding="utf-8")
    # `backend:` 잡 블록 시작부터 다음 최상위(2칸 들여쓰기) 잡 정의 전까지만 본다.
    m = re.search(r"\n  backend:\n(.*?)(?=\n  [a-zA-Z][\w-]*:\n)", text, re.S)
    if not m:
        raise SystemExit("❌ ci.yml에서 'backend:' 잡 블록을 찾지 못함 — 워크플로 구조 변경?")
    block = m.group(1)
    tm = re.search(r"timeout-minutes:\s*(\d+)", block)
    if not tm:
        raise SystemExit("❌ backend 잡 블록에서 timeout-minutes를 찾지 못함")
    return int(tm.group(1))


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit(f"사용: {sys.argv[0]} <owner/repo> [branch] [--n N]")
    repo = sys.argv[1]
    rest = [a for a in sys.argv[2:] if not a.startswith("--n")]
    branch = rest[0] if rest else "main"
    n = 11
    for a in sys.argv[2:]:
        if a.startswith("--n="):
            n = int(a.split("=", 1)[1])
        elif a == "--n" and sys.argv.index(a) + 1 < len(sys.argv):
            n = int(sys.argv[sys.argv.index(a) + 1])

    timeout_min = backend_timeout_minutes()
    print(f"backend 잡 timeout-minutes = {timeout_min}분 (ci.yml 실측 — 하드코딩 아님)")

    runs = _get(
        f"/repos/{repo}/actions/workflows/ci.yml/runs"
        f"?branch={branch}&event=push&status=success&per_page={max(n * 2, 20)}"
    )
    items = runs.get("workflow_runs", []) if isinstance(runs, dict) else []
    if not items:
        raise SystemExit(f"❌ 완료된 push CI 실행 0건 (branch={branch}) — 표본 없음, 측정 실패")

    print(f"\n{'run':>10} {'소요(분)':>9} {'여유(분)':>9} {'여유율':>7}  head_sha")
    samples: list[float] = []
    for run in items:
        if len(samples) >= n:
            break
        jobs = _get(f"/repos/{repo}/actions/runs/{run['id']}/jobs?per_page=50")
        jl = jobs.get("jobs", []) if isinstance(jobs, dict) else []
        job = next((j for j in jl if j.get("name") == _JOB_NAME), None)
        if job is None:
            print(f"{run['id']:>10}  '{_JOB_NAME}' 잡 없음(skip 또는 이름 변경) — 건너뜀")
            continue
        if job.get("conclusion") != "success":
            print(f"{run['id']:>10}  backend 잡 결론={job.get('conclusion')} — 표본 제외")
            continue
        start, done = _ts(job.get("started_at")), _ts(job.get("completed_at"))
        if not start or not done:
            print(f"{run['id']:>10}  시각 결손 — 건너뜀")
            continue
        dur_min = (done - start).total_seconds() / 60
        headroom_min = timeout_min - dur_min
        samples.append(dur_min)
        sha = (run.get("head_sha") or "")[:8]
        print(
            f"{run['id']:>10} {dur_min:>8.2f}분 {headroom_min:>8.2f}분 "
            f"{headroom_min / timeout_min * 100:>6.1f}%  {sha}"
        )

    if not samples:
        raise SystemExit("❌ 유효 표본 0건 — 측정 실패(통과 아님)")

    lo, med, hi = min(samples), statistics.median(samples), max(samples)
    hr_max = timeout_min - hi  # 최대 표본(가장 오래 걸린 실행) 기준 여유 — 보수적 지표
    print(
        f"\n표본 {len(samples)}건 — 소요 최소/중앙/최대 = {lo:.2f}/{med:.2f}/{hi:.2f}분"
        f" · 상한 {timeout_min}분"
    )
    print(f"최대 표본 기준 여유 = {hr_max:.2f}분 ({hr_max / timeout_min * 100:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
