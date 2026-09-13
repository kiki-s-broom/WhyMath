#!/usr/bin/env python3
"""HARN-30 ③ — PR 배송 상태 관측 좌석: '체크런 0건'과 'green인데 미머지'를 구분한다.

두 상태의 **처방이 다르다**:
  · `NO_CHECKS`      — 트리거가 안 걸렸다 → 깨워야 한다(base 재동기화 push 등)
  · `READY_UNMERGED` — 조건 충족인데 안 붙었다 → 사람 결정/머지 실행 대기

**런 부재의 원인을 가른다 (OPS-77 · 2026-09-12)**: 충돌한 PR은 GitHub이
`refs/pull/N/merge`를 계산하지 못해 `pull_request` 워크플로를 **아예 발화시키지
않는다**. PR #1075 실측(판정 기준 main `7408c4fd`): 21:55·22:17 두 푸시가 런을
0건 만들었고(마지막 런은 6시간 전 16:48), 충돌 해소 후 22:22 푸시는 1분 내 런
생성. 그동안 PR 화면에는 *이전* sha의 낡은 실패가 남아 **"CI가 안 돈다"가 "CI가
실패했다"로 보인다** — 침묵이 아니라 위장이다. 이때 `NO_CHECKS`의 처방(재푸시)은
틀린 처방이므로 `STALLED_CONFLICT`로 따로 세운다.

**미판정을 확정으로 접지 않는다**: `mergeable_state`는 지연 계산이라 `unknown`
이거나 목록 응답에 **필드가 없을 수 있다**. 초판은 `str(None)`이 `"None"`이 되어
어느 분기에도 안 걸린 채 맨 아래 `READY_UNMERGED`("머지만 남음")로 떨어졌다 —
모르는 데이터로 확정 신호를 내던 경로다(CLAUDE.md 2026-09-01 ③).

이 둘을 한 덩어리("미머지 PR")로 보면 처방을 못 고른다. 실제로 이 저장소에서
`NO_CHECKS`는 무증상이다 — 아무도 보지 않으면 PR이 조용히 방치된다(PR #779가
57분, #751이 1일 넘게).

**도구 함정 (acceptance ①)**: `GET /repos/{repo}/statuses|status`(MCP의
`pull_request_read method=get_status`)는 이 저장소에서 **항상 total_count 0**을
낸다 — commit status API인데 이 저장소는 check runs를 쓴다. 체크런 16건이 확실한
PR에서도 0이다(2026-08-31 재확인). **판정에 쓰지 말 것.**
대신 쓸 신호: `GET /commits/{sha}/check-runs` 또는 `/actions/runs?head_sha=`.

**fail-open 판정 (acceptance ④)**: 조회 실패는 "이상 없음"이 아니라 **측정 실패**로
보인다. 상시 무력 보호를 만들지 않기 위해(CLAUDE.md 2026-07-27 금기) 이 도구는
조회에 실패하면 exit 1과 함께 실패 사유를 낸다 — 조용히 빈 목록을 반환하지 않는다.

사용:
    python3 scripts/ops/pr_delivery_audit.py "$GITHUB_REPOSITORY"

exit code
    0 — 열린 PR 전부가 정상 배송 중(대기·진행)
    1 — 주의 필요(NO_CHECKS 또는 READY_UNMERGED 존재) 또는 **측정 실패**
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

API = "https://api.github.com"
TIMEOUT = 30
_CA_PATH = "/root/.ccr/ca-bundle.crt"  # 에이전트 프록시 CA (있을 때만 사용)
SATISFYING = frozenset({"success", "skipped", "neutral"})

# 상태 → (라벨, 처방). 처방을 함께 들고 다니는 이유: 상태만 알려주면
# 다음 세션이 다시 판단해야 하고, 그 판단이 이 태스크가 고치려는 오판 지점이다.
PRESCRIPTION = {
    "STALLED_CONFLICT": (
        "충돌이 CI 발화를 막고 있다 — **재푸시로는 안 깨어난다**. 충돌을 먼저 해소한다"
    ),
    "NO_CHECKS": "트리거 미발화 — origin/main 재병합 push로 깨운다(빈 커밋·재개폐 금지)",
    "NO_CHECKS_CAUSE_UNKNOWN": (
        "런 부재는 확실하나 원인 미상(머지 상태 미판정) — 원인을 먼저 확인한다. "
        "재푸시를 처방하지 않는다"
    ),
    "REQUIRED_FAILING": "필수 체크 실패 — 고쳐서 다시 push",
    "REQUIRED_PENDING": "필수 체크 진행 중 — 대기(전체 CI는 기다리지 않는다·HARN-32)",
    "BEHIND": "base 전진 — origin/main 재병합 후 push(strict policy)",
    "CONFLICT": "머지 충돌 — 해소 필요",
    "MERGE_STATE_UNKNOWN": (
        "체크는 충족인데 머지 상태를 재지 못했다 — READY로 읽지 말 것(모른다 ≠ 준비됨)"
    ),
    "READY_UNMERGED": "조건 충족 · 머지만 남음 — 사람 결정 대기",
}
# 미판정(`*_UNKNOWN`)도 주의에 넣는다: "재지 못했다"를 조용히 넘기면 그 PR은
# 화면에서 사라지고, 사라진 것은 정상과 구별되지 않는다(측정 실패 ≠ 통과).
ATTENTION = frozenset(
    {
        "STALLED_CONFLICT",
        "NO_CHECKS",
        "NO_CHECKS_CAUSE_UNKNOWN",
        "MERGE_STATE_UNKNOWN",
        "READY_UNMERGED",
    }
)

# 머지 상태가 "모른다"로 읽혀야 하는 값들. GitHub은 머지 가능성을 **지연 계산**하며,
# 계산 전에는 `mergeable_state`가 `unknown`이거나 응답에 아예 없다(그러면 호출측이
# `None`을 받는다). 이것을 `clean`으로 접으면 *모르는* 데이터로 확정 신호를 낸다.
# `"none"`·`"null"`이 들어 있는 것은 오타 방지가 아니라 **호출측 표기**를 받기
# 위해서다: 값이 없을 때 `str(None)`은 `"None"`이 되고 JSON null을 문자열화하면
# `"null"`이 된다. 둘 다 여기서 미판정으로 접히므로 별도의 None 분기는 두지
# 않는다 — 어떤 입력으로도 구별되지 않는 절은 검증할 수 없고, 검증되지 않은 절은
# "검증된 가드"의 일부로 조용히 계상된다(2026-09-12 뮤테이션 M4 생존으로 발각).
UNKNOWN_MERGE_STATES = frozenset({"", "none", "null", "unknown"})


def _norm_merge_state(value: object) -> str:
    """머지 상태를 소문자 문자열로 정규화하고 미판정을 하나의 값으로 모은다.

    `str(None)`이 `"None"`이 되어 어떤 분기에도 안 걸리고 조용히 맨 아래로
    떨어지는 경로를 막는 것이 목적이다 — 그 경로의 종착지가 하필
    `READY_UNMERGED`("머지만 남음")라 **미판정이 준비 완료로 보고된다**.
    """
    text = str(value).strip().lower()
    return "unknown" if text in UNKNOWN_MERGE_STATES else text


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

    **왜 존재 검사를 예외로 감싸는가** (2026-09-01 main red 실측): `Path.exists()`는
    실패를 False로 돌려주지 **않는다** — `pathlib._IGNORED_ERRNOS`는
    `(ENOENT, ENOTDIR, EBADF, ELOOP)`뿐이라 **EACCES는 전파된다**. GitHub 러너의
    `runner` 유저는 `/root`(mode 700)를 통과할 수 없으므로 검사 자체가
    `PermissionError`로 죽는다.

    그리고 CA를 **무조건** `--cacert`로 넘기면 러너에서 `curl (77) error setting
    certificate file`이 난다. 이 경로는 에이전트 프록시가 있는 실행 환경에만
    존재하므로, 없으면 시스템 신뢰저장소를 쓰는 것이 정상 동작이다.
    """
    try:
        with open(_CA_PATH, "rb"):  # 존재 + 읽기 권한을 한 번에 확인한다
            return ["--cacert", _CA_PATH]
    except OSError:
        return []


def classify(
    required: set[str],
    check_runs: dict[str, str | None],
    *,
    mergeable_state: str | None,
) -> str:
    """PR 1건의 배송 상태 — **순수 함수**(네트워크 없음).

    순서가 곧 처방 우선순위다. `NO_CHECKS` 계열을 가장 먼저 보는 이유: 체크런이
    0건이면 다른 판정이 전부 무의미하기 때문이다(진행 중인지 실패인지 알 수 없다).

    **런 부재를 한 덩어리로 보지 않는다 (OPS-77)**. 충돌한 PR은 GitHub이
    `refs/pull/N/merge`를 계산하지 못해 `pull_request` 워크플로를 **아예 발화시키지
    않는다** — 새 head sha에 런이 0건이 되고, PR 화면에는 *이전* sha의 낡은 결과가
    남는다. 그래서 "CI가 안 돈다"가 "CI가 실패했다"로 보인다(침묵이 아니라 위장).
    이때 `NO_CHECKS`의 처방("재푸시로 깨운다")을 그대로 주면 **틀린 처방**이다:
    충돌이 서 있는 동안에는 몇 번을 밀어도 런이 생기지 않는다. 원인이 충돌로
    확인되면 `STALLED_CONFLICT`, 원인을 모르면 `NO_CHECKS_CAUSE_UNKNOWN`으로 가른다.

    미판정(`unknown`·응답에 필드 없음)은 **어떤 확정 상태로도 접지 않는다**.
    """
    ms = _norm_merge_state(mergeable_state)
    missing_required = any(name not in check_runs for name in required)
    if not check_runs or missing_required:
        # 부분 미발화도 미발화다 — 다만 *왜* 안 돌았는지는 나눠서 말한다.
        if ms == "dirty":
            return "STALLED_CONFLICT"
        if ms == "unknown":
            return "NO_CHECKS_CAUSE_UNKNOWN"
        return "NO_CHECKS"
    if any(check_runs.get(n) not in SATISFYING and check_runs.get(n) is not None for n in required):
        return "REQUIRED_FAILING"
    if any(check_runs.get(n) is None for n in required):
        return "REQUIRED_PENDING"
    if ms == "dirty":
        return "CONFLICT"
    if ms == "behind":
        return "BEHIND"
    if ms == "unknown":
        return "MERGE_STATE_UNKNOWN"
    return "READY_UNMERGED"


def _merge_state(repo: str, pr: dict) -> tuple[str, int]:
    """PR 1건의 머지 상태와 **단건 재조회를 했는지**(0/1)를 돌려준다.

    왜 목록 응답을 그대로 믿지 않는가: GitHub은 머지 가능성을 지연 계산하므로
    목록 조회 응답의 `mergeable_state`는 `unknown`이거나 **필드 자체가 없을 수
    있다**. 형제 도구 `pr_merge_readiness.py`가 같은 필드를 위해 단건
    (`/pulls/{n}`)을 따로 부르는 것도 같은 이유다. 그런데 이 도구는 목록 값을
    그대로 써 왔고, 값이 없으면 `str(None)`이 `"None"`이 되어 어느 분기에도 안
    걸린 채 맨 아래 `READY_UNMERGED`로 떨어졌다 — **미판정이 "머지만 남음"으로
    보고되는** 경로다.

    비용: 단건 조회는 열린 PR 수만큼 늘 수 있으므로 **미판정일 때만** 부른다
    (HARN-99 ②의 "후보 축소 후 재확인"과 같은 계약). 조회가 실패하면 예외를
    삼키지 않고 `_get`의 '측정 실패'가 그대로 올라간다 — 여기서 조용히
    `unknown`으로 낮추면 실패가 정상 판정으로 위장된다.
    """
    listed = _norm_merge_state(pr.get("mergeable_state"))
    if listed != "unknown":
        return listed, 0
    status, data = _get(f"/repos/{repo}/pulls/{pr['number']}")
    # 오류 본문도 dict다(`{"message": "rate limit"}`). `isinstance(dict)`만 보고
    # `.get()`하면 없는 키가 None → "unknown"이 되어 **실패가 미판정으로 위장된다**
    # (2026-09-12 이 태스크의 회귀 테스트가 내 초판에서 실제로 잡은 결함).
    # 진짜 PR 응답은 계산 전이라도 `mergeable_state` 키를 **항상 들고 온다**(값이
    # null일 뿐). 그래서 키의 존재가 "응답이 PR인가"의 변별점이 된다.
    if status != 200 or not isinstance(data, dict) or "mergeable_state" not in data:
        raise SystemExit(
            f"❌ 측정 실패 — PR #{pr['number']} 단건 조회(HTTP {status}): " f"{str(data)[:200]}"
        )
    return _norm_merge_state(data.get("mergeable_state")), 1


def _get(path: str) -> tuple[int, object]:
    """GET 후 `(마지막 응답의 HTTP 상태코드, 파싱된 JSON)`을 돌려준다.

    **`-L`(리다이렉트 추종)이 필수다** — 저장소가 다른 owner로 *이관*되면 GitHub은
    301과 함께 새 위치를 알려주는데, 따라가지 않으면 본문이 규칙 배열이 아니라
    `{"message": "Moved Permanently", ...}` 딕셔너리로 온다. 그러면 호출측의
    집합 컴프리헨션이 조용히 공집합을 만들어 **"필수 체크 0건"으로 위장된다**
    (2026-09-10 실측 — 조직 이관 후 harness-audit run 34425627951이 이 경로로 red).

    상태코드를 함께 돌려주는 이유는 실패했을 때 *원인*을 구분해 남기기 위해서다 —
    301(이동)·403/404(권한·부재)·200(진짜 0건)이 같은 문구로 보이면 안 된다
    (CLAUDE.md "측정·수집 도구를 성공 경로만 보고 설계 금지" ②).
    """
    marker = "\n<<<HTTP:%{http_code}>>>"
    cmd = [
        "curl",
        "-sS",
        "-L",  # 이관 리다이렉트 추종 — 없으면 301 본문을 데이터로 오독한다
        "--max-time",
        str(TIMEOUT),
        *_ca_args(),
        *_auth_args(),
        "-H",
        "Accept: application/vnd.github+json",
        "-w",
        marker,
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
        raise SystemExit(f"❌ 측정 실패(타임아웃 {TIMEOUT}s): {path}") from exc
    if out.returncode != 0:
        raise SystemExit(
            f"❌ 측정 실패(curl rc={out.returncode}): {path}\n{out.stderr[:400]}"
        ) from None
    body, status = _split_status(out.stdout)
    try:
        return status, json.loads(body)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"❌ 측정 실패(JSON · HTTP {status}): {path}\n앞 400자: {body[:400]}"
        ) from exc


def _split_status(stdout: str) -> tuple[str, int]:
    """`-w` 마커로 붙인 상태코드를 본문에서 떼어낸다.

    마커가 없으면(스텁 curl 등) 상태를 0으로 보고 본문을 그대로 돌려준다 — 상태를
    모르는 것과 200인 것을 같은 값으로 접지 않기 위해서다(모른다 ≠ 아니다).
    """
    head, sep, tail = stdout.rpartition("<<<HTTP:")
    if not sep or not tail.endswith(">>>"):
        return stdout, 0
    code = tail[: -len(">>>")]
    return head.rstrip("\n"), int(code) if code.isdigit() else 0


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit(f"사용: {sys.argv[0]} <owner/repo>")
    repo = sys.argv[1]

    status, rules = _get(f"/repos/{repo}/rules/branches/main")
    if not isinstance(rules, list):
        # 목록이 아니면 규칙을 **읽지 못한 것**이다 — 이동(301)·권한(403)·부재(404)가
        # 여기로 모인다. 원인을 지우고 "0건"으로 뭉개면 다음 세션이 헛다리를 짚는다.
        raise SystemExit(
            f"❌ 측정 실패 — 규칙 응답이 목록이 아니다(HTTP {status} · repo={repo}). "
            "저장소 이동·권한 부족·오타를 의심하라. '이상 없음'이 아니다\n"
            f"응답 앞 300자: {str(rules)[:300]}"
        )
    required = {
        c["context"]
        for r in rules
        if isinstance(r, dict) and r.get("type") == "required_status_checks"
        for c in r.get("parameters", {}).get("required_status_checks", [])
    }
    if not required:
        raise SystemExit(
            f"❌ 측정 실패 — 규칙 {len(rules)}건은 읽혔으나 required_status_checks 0건"
            f"(HTTP {status} · repo={repo}). '이상 없음'이 아니다"
        )

    _, prs = _get(f"/repos/{repo}/pulls?state=open&per_page=50")
    if not isinstance(prs, list):
        raise SystemExit(f"❌ 측정 실패 — PR 목록 조회: {str(prs)[:300]}")
    if not prs:
        print("열린 PR 0건")
        return 0

    buckets: dict[str, list[str]] = {}
    requeried = 0
    for pr in prs:
        sha = pr["head"]["sha"]
        _, cr = _get(f"/repos/{repo}/commits/{sha}/check-runs?per_page=100")
        runs = {
            c["name"]: (c.get("conclusion") if c.get("status") == "completed" else None)
            for c in (cr.get("check_runs", []) if isinstance(cr, dict) else [])
        }
        ms, did_requery = _merge_state(repo, pr)
        requeried += did_requery
        state = classify(required, runs, mergeable_state=ms)
        buckets.setdefault(state, []).append(f"#{pr['number']} {pr['title'][:52]} [merge={ms}]")

    attention = 0
    for state in (
        "STALLED_CONFLICT",
        "NO_CHECKS",
        "NO_CHECKS_CAUSE_UNKNOWN",
        "REQUIRED_FAILING",
        "CONFLICT",
        "BEHIND",
        "REQUIRED_PENDING",
        "MERGE_STATE_UNKNOWN",
        "READY_UNMERGED",
    ):
        items = buckets.get(state)
        if not items:
            continue
        flag = "⚠" if state in ATTENTION else "·"
        print(f"\n{flag} {state} ({len(items)}건) — {PRESCRIPTION[state]}")
        for it in items:
            print(f"    {it}")
        if state in ATTENTION:
            attention += len(items)

    # 호출 비용을 남긴다 — 주기·비용 재판정의 근거가 되도록(HARN-99 ④ 선례).
    print(f"\n열린 PR {len(prs)}건 · 주의 필요 {attention}건 · 머지상태 단건 재조회 {requeried}회")
    print("주의: get_status(commit status API)는 이 저장소에서 항상 0을 낸다 — 판정에 쓰지 말 것")
    return 1 if attention else 0


if __name__ == "__main__":
    raise SystemExit(main())
