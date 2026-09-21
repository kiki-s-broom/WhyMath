#!/usr/bin/env python3
"""HARN-32 ① — 머지 차단 지연 실측 (재현 가능 명령).

**왜 이 스크립트인가**: HARN-32는 "CI 소요 ~28분이 main 머지 간격 ~31분과 맞먹는다"로
등재됐다. 그런데 머지를 막는 것은 *전체 CI*가 아니라 브랜치 보호가 지정한
**필수 체크(required status checks)** 뿐이다. 이 저장소의 최장 잡
(`backend — lint·type·test`, ~30분)은 **필수 목록에 없다**. 따라서 등재 당시의
프레이밍은 차단 시간을 과대평가한다 — 실제 경합 창은 필수 체크 완주까지다.

두 수치를 함께 낸다:
  ① 필수 체크 6종이 전부 끝나는 시각 (= 머지 가능 시점)
  ② 전체 CI가 끝나는 시각 (= 세션이 관행적으로 기다리던 시점)
그 차이가 이 태스크가 회수할 수 있는 시간이다.

사용:
    python3 scripts/analysis/measure_merge_gate_latency.py <owner/repo> <branch>

필수 체크 목록은 하드코딩하지 않고 **런타임에 브랜치 보호에서 읽는다** — 규칙이
바뀌면 이 측정도 따라 바뀌어야 하고, 하드코딩하면 조용히 낡는다.

실패 경로 설계(2026-08-22 규칙): 단계마다 즉시 출력하고, 실패는 원인(HTTP 본문·
예외 타입)을 남기며, 모든 외부 호출에 타임아웃을 건다. 표본 0건은 "통과"가 아니라
명시적 실패다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime

API = "https://api.github.com"
TIMEOUT = 30
_CA_PATH = "/root/.ccr/ca-bundle.crt"  # 에이전트 프록시 CA (있을 때만 사용)


def _auth_args() -> list[str]:
    """토큰이 있으면 `["-H", "Authorization: Bearer <token>"]`, 없으면 `[]`.

    **왜 필수인가** (2026-09-01 main red 실측): GitHub API의 **미인증** 한도는
    IP당 60req/h인데, GitHub 러너는 IP를 공유하므로 실질적으로 상시 소진 상태다.
    실제 실패: `API rate limit exceeded for 52.157.2.240`.

    더 나쁜 것은 이 실패가 **간헐적**이라는 점이다 — 같은 코드가 앞선 실행에서는
    통과했다(그때는 한도가 남아 있었다). 그래서 "한 번 초록이었다"가 안전의 증거가
    되지 못한다. 워크플로가 `GITHUB_TOKEN` 환경변수를 넘겨도 **스크립트가 읽지
    않으면 아무 효과가 없다** — 환경변수 설정과 실제 소비는 다른 일이다.
    """
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    return ["-H", f"Authorization: Bearer {token}"] if token else []


def _ca_args() -> list[str]:
    """프록시 CA를 쓸 수 있으면 `["--cacert", <경로>]`, 아니면 `[]`.

    존재 검사를 예외로 감싼다 — `Path.exists()`는 EACCES를 전파하고(2026-09-01
    main red 실측), CA를 무조건 넘기면 그 파일이 없는 환경에서 `curl (77)`이 난다.
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


def required_checks(repo: str) -> set[str]:
    rules = _get(f"/repos/{repo}/rules/branches/main")
    if not isinstance(rules, list):
        raise SystemExit(f"❌ 규칙 조회 응답이 목록이 아니다: {str(rules)[:300]}")
    names = {
        c["context"]
        for r in rules
        if r.get("type") == "required_status_checks"
        for c in r.get("parameters", {}).get("required_status_checks", [])
    }
    if not names:
        raise SystemExit("❌ 필수 체크가 0건 — 규칙이 없거나 조회 권한 부족(측정 불가)")
    return names


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def main() -> int:
    if len(sys.argv) < 3:
        raise SystemExit(f"사용: {sys.argv[0]} <owner/repo> <branch>")
    repo, branch = sys.argv[1], sys.argv[2]

    req = required_checks(repo)
    print(f"필수 체크 {len(req)}종 (런타임 조회):")
    for name in sorted(req):
        print(f"  · {name}")

    runs = _get(f"/repos/{repo}/actions/workflows/ci.yml/runs?branch={branch}&per_page=20")
    items = runs.get("workflow_runs", []) if isinstance(runs, dict) else []
    done = [r for r in items if r.get("status") == "completed"]
    if not done:
        raise SystemExit(f"❌ 완료된 CI 실행 0건 (branch={branch}) — 표본 없음, 측정 실패")

    print(f"\n{'run':>6} {'필수완주':>9} {'전체완주':>9} {'회수가능':>9}  결론")
    samples = []
    for run in done[:10]:
        jobs = _get(f"/repos/{repo}/actions/runs/{run['id']}/jobs?per_page=50")
        jl = jobs.get("jobs", []) if isinstance(jobs, dict) else []
        if not jl:
            print(f"{run['run_number']:>6}  잡 조회 0건 — 건너뜀(원인 미상)")
            continue
        start = _ts(run.get("run_started_at"))
        req_done = [_ts(j.get("completed_at")) for j in jl if j.get("name") in req]
        all_done = [_ts(j.get("completed_at")) for j in jl if j.get("completed_at")]
        if not start or not req_done or None in req_done or not all_done:
            print(f"{run['run_number']:>6}  시각 결손 — 건너뜀")
            continue
        r_min = (max(req_done) - start).total_seconds() / 60
        a_min = (max(all_done) - start).total_seconds() / 60
        samples.append((r_min, a_min))
        print(
            f"{run['run_number']:>6} {r_min:>8.1f}분 {a_min:>8.1f}분 {a_min - r_min:>8.1f}분"
            f"  {run.get('conclusion')}"
        )

    if not samples:
        raise SystemExit("❌ 유효 표본 0건 — 측정 실패(통과 아님)")
    import statistics

    r = statistics.median(s[0] for s in samples)
    a = statistics.median(s[1] for s in samples)
    print(f"\n중앙값 — 필수 완주 {r:.1f}분 · 전체 완주 {a:.1f}분 · **회수 가능 {a - r:.1f}분**")
    print(f"표본 {len(samples)}건 (branch={branch})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
