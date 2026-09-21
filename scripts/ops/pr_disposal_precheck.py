#!/usr/bin/env python3
"""HARN-93 ③ — 처분 라벨 붙은 PR을 닫기 전 안전 확인 (집행 지점).

**결함**: HARN-42가 열린 PR에 처분 라벨(eos-merge/rework/postpone/close)을 붙였지만,
그 라벨은 "언젠가 닫는다/미룬다"는 *결정*일 뿐 만료·재확인 지점이 없다(CLAUDE.md
"만료 없는 유예·제외 금지"). 실측(2026-09-08 main `4abacdce`): 열린 PR 10건이 라벨을
단 채 8일간 갱신 0이었고, 그중 6건은 trunk에 없는 파일(main 부재 파일)이 실재한다
— 이 상태로 PR을 닫으면 그 파일들은 어떤 브랜치·PR에서도 보이지 않게 된다(미머지
고립 5회차: 앞 4회는 *PR을 열지 않아서*, 이 형태는 **PR을 열어 두고 닫아서** 생긴다).

지금은 어떤 태스크·게이트·코드도 "닫기 전에 파일 단위 대조 + 회수 좌석 등재"를
소유하지 않는다(HARN-93 acceptance ③ 역할 기준 검색 실측). 이 스크립트가 그 지점이다
— **코드를 옮기지 않는다**(이식은 stray-code 소관 분리, HARN-78 ⑤ 동형). 옮겨야 할
것이 있는지, 있다면 회수 좌석이 이미 등재됐는지만 닫기 *전에* 알려준다.

판정 (순수 함수 `decide` — 네트워크 없음):
    trunk 부재 파일 0건               → 안전(닫아도 고아 코드 없음)
    trunk 부재 파일 >0 · 회수 좌석 있음 → 안전(회수 좌석이 이미 그 코드를 추적)
    trunk 부재 파일 >0 · 회수 좌석 없음 → 차단 — 먼저 `backlog.py add`로 회수 태스크를
                                          등재하고 notes/artifacts에 이 PR 번호를 남길 것

회수 좌석 판정은 backlog 태스크의 `notes`·`artifacts`에 `#<PR번호>` 문자열이 있는지로
본다 — 이 저장소가 이미 PR 참조를 그 형태로 남기는 관례를 그대로 재사용한다(CLAUDE.md
"완료·병합" PR 증적 표기와 동일 패턴: `#12`·`.../pull/12`).

사용:
    python3 scripts/ops/pr_disposal_precheck.py <owner/repo> <pr-number>

exit code (게이트 CLI 관례 — 판정은 항상 0/1, CLAUDE.md "검증 권위"):
    0 — 지금 닫아도 안전(측정 성공 + 무고아 또는 회수 좌석 확인)
    1 — 아직 아님(사유를 stdout에 명시) 또는 측정 실패(토큰 없음·네트워크·git 오류 등 —
        측정 실패와 "안전 확인됨"은 같은 색이면 안 된다)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

API = "https://api.github.com"
TIMEOUT = 30
_CA_PATH = "/root/.ccr/ca-bundle.crt"  # 에이전트 프록시 CA (있을 때만 사용)
_ROOT = Path(__file__).resolve().parents[2]

# HARN-42가 부착하는 처분 라벨 4종. `remote_claims.DISPOSAL_LABELS`와 같은 값을
# 여기서도 독립적으로 든다 — `_auth_args`/`_ca_args`와 같은 이유로(이 저장소 관용구:
# 4번째 사용만으로는 공유 추출이 과공학) `scripts/ops`가 `scripts/harness`를 import
# 하지 않고도 이 스크립트 하나만으로 동작하게 한다.
DISPOSAL_LABELS = frozenset({"eos-merge", "eos-rework", "eos-postpone", "eos-close"})

# "main 부재 파일" 판정 프리픽스 — docs/reviews/unmerged_branch_audit_2026-09-08.md
# §3.3이 실측에 쓴 것과 동일(재현성 — 그 문서의 수치와 이 스크립트의 수치가 어긋나면
# 어느 쪽이 틀렸는지 판단할 기준이 사라진다).
CODE_PREFIXES = ("src/", "tests/", "scripts/", "data/")


def _auth_args() -> list[str]:
    """토큰이 있으면 `["-H", "Authorization: Bearer <token>"]`, 없으면 `[]`."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    return ["-H", f"Authorization: Bearer {token}"] if token else []


def _ca_args() -> list[str]:
    """프록시 CA를 쓸 수 있으면 `["--cacert", <경로>]`, 아니면 `[]`.

    `Path.exists()`는 EACCES를 삼키지 않는다(`/root`가 mode 700인 러너에서 검사
    자체가 죽는다) — 그래서 열어 보고 예외로 판정한다.
    """
    try:
        with open(_CA_PATH, "rb"):
            return ["--cacert", _CA_PATH]
    except OSError:
        return []


def _get(path: str) -> tuple[object | None, str]:
    """GitHub API GET — 실패는 `(None, "<사유>")`, 성공은 `(파싱된 JSON, "")`.

    예외 타입명을 반드시 사유에 담는다(CLAUDE.md 침묵 실패 금지).
    """
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return None, "NoTokenError: GITHUB_TOKEN/GH_TOKEN 미설정 — PR 조회 불가"
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
            errors="replace",
            timeout=TIMEOUT + 10,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc} ({path})"
    if out.returncode != 0:
        return None, f"CurlExitError({out.returncode}): {out.stderr.strip()[:200]} ({path})"
    try:
        return json.loads(out.stdout), ""
    except json.JSONDecodeError as exc:
        return None, f"JSONDecodeError: {exc} — 본문 {out.stdout[:160]!r} ({path})"


def _run_git(root: Path, *args: str, timeout: int = 30) -> tuple[str | None, str]:
    """`git <args>` — 실패는 `(None, "<사유>")`, 성공은 `(stdout, "")`."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc} (git {' '.join(args)})"
    if proc.returncode != 0:
        return None, f"git {args[0]} 비0 종료({proc.returncode}): {proc.stderr.strip()[:200]}"
    return proc.stdout, ""


def trunk_absent_files(root: Path, pr_number: int) -> tuple[list[str] | None, str]:
    """PR의 head가 trunk(`origin/main`) 대비 남기는, **trunk에 없는** 코드 파일 목록.

    오프라인 git만 쓴다 — `refs/pull/<n>/head`는 인증 없이 fetch된다(HARN-47과
    동일 근거: 이 네임스페이스는 평범한 git으로 열람 가능). PR 열림/닫힘·라벨은
    이 함수의 관심사가 아니다 — head ref가 아직 존재하기만 하면(열린 PR) 계산된다.

    반환 `None`은 **판정 불가**다(빈 리스트와 다르다) — git이 실패하면 "남길 것
    없음"으로 읽어서는 안 된다(CLAUDE.md "미측정을 0으로 바꾸지 않는다").
    """
    # trunk sha를 먼저 확정해 둔다 — 뒤이어 PR head를 fetch하면 `FETCH_HEAD`가
    # 덮어써지므로, "origin/main" 심볼릭 참조가 아니라 이 sha 문자열로 diff·
    # cat-file을 건다(두 fetch 사이 순서에 결과가 흔들리지 않게).
    _, trunk_err = _run_git(root, "fetch", "--quiet", "--depth=1", "origin", "main", timeout=60)
    if trunk_err:
        return None, trunk_err
    trunk_sha_out, sha_err = _run_git(root, "rev-parse", "FETCH_HEAD", timeout=10)
    if sha_err:
        return None, sha_err
    trunk_sha = (trunk_sha_out or "").strip()
    if not trunk_sha:
        return None, "EmptyShaError: FETCH_HEAD가 비어 있다(origin/main fetch 후)"

    _, fetch_err = _run_git(
        root, "fetch", "--quiet", "--depth=1", "origin", f"pull/{pr_number}/head", timeout=60
    )
    if fetch_err:
        return None, fetch_err
    # 점 두 개(`A...B`, merge-base 기준)가 아니라 **두 트리를 직접 비교**한다
    # (`git diff A B`). 양쪽 다 얕은(shallow) fetch라 공통 조상이 로컬에 없을 수
    # 있고("no merge base"), 이 함수가 답하려는 질문("지금 trunk 스냅샷에 이
    # 파일이 있는가")은 애초에 조상 관계와 무관하다 — 두 트리의 파일 목록 차이만
    # 있으면 된다.
    diff_out, diff_err = _run_git(root, "diff", "--name-only", trunk_sha, "FETCH_HEAD", timeout=30)
    if diff_err:
        return None, diff_err
    files = [line.strip() for line in (diff_out or "").splitlines() if line.strip()]
    absent: list[str] = []
    for f in files:
        if not f.startswith(CODE_PREFIXES):
            continue
        _, check_err = _run_git(root, "cat-file", "-e", f"{trunk_sha}:{f}", timeout=10)
        if check_err:  # 조회 실패 = trunk에 그 경로가 없다(존재하면 exit 0·조용)
            absent.append(f)
    return absent, ""


def recovery_task_ids(
    root: Path, pr_number: int, absent_files: list[str]
) -> tuple[list[str] | None, str]:
    """이 PR을 언급하고, 그 언급이 **trunk 부재 파일을 실제로 커버**하는 태스크 ID.

    단순 `#<N>` 텍스트 언급만으로는 회수 좌석을 증명하지 못한다 — 첫 구현이 이
    실수를 저질렀다: `HARN-42`(이 PR을 CLOSE로 *판정*만 한 태스크) 자신이 notes·
    artifacts에 `#858`을 여러 번 남기는데, 그 언급만으로 "회수 좌석 있음"을
    인정하면 **판정을 내린 태스크 자신이 회수 좌석으로 오인된다** — 판정한 사실과
    코드를 옮기기로 한 사실은 다른데 같은 문자열(`#858`)이 둘 다에 나타나므로
    변별력이 없다(CLAUDE.md "변별력 없는 검증 스텝 금지" — 실제 PR #858로 이
    함수를 실행해 HARN-42가 거짓 양성으로 잡히는 것을 확인한 뒤 이 가드를 추가했다).
    그래서 텍스트 언급에 더해 그 태스크의 `paths`가 부재 파일 중 하나 이상을
    실제로 커버하는지까지 본다(`pathscope.path_in_scope` — `backlog.py overlap`이
    쓰는 것과 같은 잣대) — `paths` 미선언 태스크는 무엇도 커버하지 못하므로 항상 제외.

    반환 `None`은 백로그 자체를 못 읽었다는 뜻(측정 불가) — 빈 리스트(회수 좌석
    없음)와 다르다. `absent_files`가 비어 있으면 호출하지 않는다(호출부 책임 —
    부재 파일이 0건이면 회수 좌석 유무가 판정에 영향을 주지 않는다).
    """
    harness_dir = str(root / "scripts" / "harness")
    if harness_dir not in sys.path:
        sys.path.insert(0, harness_dir)
    try:
        import pathscope  # noqa: PLC0415
        import store  # noqa: PLC0415
    except ImportError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    try:
        backlog, _schema_errors = store.load_backlog(root)
    except Exception as exc:  # noqa: BLE001 - 환경 의존(YAML 파싱·파일시스템)
        return None, f"{type(exc).__name__}: {exc}"
    needle = f"#{pr_number}"
    hits: list[str] = []
    for task in backlog.tasks.values():
        if not task.paths:
            continue
        haystacks = [task.notes, *task.artifacts]
        if not any(needle in text for text in haystacks if text):
            continue
        if any(pathscope.path_in_scope(f, task.paths) for f in absent_files):
            hits.append(task.id)
    return sorted(hits), ""


@dataclass
class Verdict:
    """판정 결과 — 순수 함수의 산출물(I/O와 분리해 테스트 가능하게)."""

    safe: bool
    reasons: list[str] = field(default_factory=list)


def decide(absent_files: list[str], recovery_ids: list[str]) -> Verdict:
    """닫아도 안전한가 — **순수 함수**(네트워크·git 없음).

    라벨 종류(rework/postpone/close)는 판정에 관여하지 않는다 — 고아 코드 위험은
    라벨과 무관하게 "trunk에 없는 파일이 있는가"로만 결정된다. 라벨은 main()이
    맥락으로만 출력한다(어떤 처분이 걸려 있는지 보여주되 판정 축에 넣지 않음 —
    라벨 이름이 바뀌거나 늘어도 이 함수는 영향받지 않는다).
    """
    if not absent_files:
        return Verdict(True, ["trunk 부재 파일 0건 — 닫아도 고아 코드가 남지 않는다"])
    if recovery_ids:
        return Verdict(
            True,
            [
                f"trunk 부재 파일 {len(absent_files)}건이나 회수 좌석 확인됨: "
                + ", ".join(recovery_ids)
            ],
        )
    reasons = [
        f"trunk 부재 파일 {len(absent_files)}건, 회수 좌석 없음 — 닫으면 미머지 고립이 된다.",
        "먼저 `backlog.py add`로 회수 태스크를 등재하고 notes 또는 artifacts에 "
        "이 PR 번호(#<N>)를 남긴 뒤 다시 확인할 것.",
    ]
    shown = absent_files[:20]
    reasons.extend(f"  · {f}" for f in shown)
    if len(absent_files) > len(shown):
        reasons.append(f"  · … 외 {len(absent_files) - len(shown)}건")
    return Verdict(False, reasons)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print(f"사용: {sys.argv[0]} <owner/repo> <pr-number>", file=sys.stderr)
        return 1
    repo, pr_arg = argv[0], argv[1]
    try:
        pr_number = int(pr_arg)
    except ValueError:
        print(f"❌ PR 번호가 정수가 아니다: {pr_arg!r}", file=sys.stderr)
        return 1

    pr_data, pr_err = _get(f"/repos/{repo}/pulls/{pr_number}")
    if pr_err or not isinstance(pr_data, dict) or "head" not in pr_data:
        print(f"❌ PR #{pr_number} 조회 실패: {pr_err or str(pr_data)[:200]}")
        return 1
    labels = tuple(
        item["name"]
        for item in pr_data.get("labels", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    )
    disposal = [name for name in labels if name in DISPOSAL_LABELS]
    print(
        f"PR #{pr_number} · {pr_data.get('title', '')!r} · state={pr_data.get('state')} · "
        f"라벨: {', '.join(disposal) if disposal else '(처분 라벨 없음)'}"
    )

    absent, absent_err = trunk_absent_files(_ROOT, pr_number)
    if absent_err:
        print(f"❌ trunk 부재 파일 측정 실패: {absent_err}")
        return 1
    assert absent is not None  # absent_err가 비었으면 항상 채워진다

    if absent:
        recovered, recovered_err = recovery_task_ids(_ROOT, pr_number, absent)
        if recovered_err:
            print(f"❌ 회수 좌석 조회 실패: {recovered_err}")
            return 1
        assert recovered is not None
    else:
        recovered = []  # 부재 파일이 없으면 회수 좌석 조회 자체가 무의미하다

    verdict = decide(absent, recovered)
    for reason in verdict.reasons:
        print(f"  · {reason}" if not reason.startswith("  ") else reason)
    print("✔ 닫아도 안전" if verdict.safe else "✖ 지금 닫지 말 것")
    return 0 if verdict.safe else 1


if __name__ == "__main__":
    raise SystemExit(main())
