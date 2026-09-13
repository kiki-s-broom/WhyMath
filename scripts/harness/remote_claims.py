"""원격 claim — 단일 `harness-claims` 브랜치, git ref push의 CAS 원자성 이용.

배경: 태스크 claim(Task.session)은 각 세션 worktree의 backlog/ 사본에만 기록되어
merge 전까지 병렬 세션끼리 서로 보이지 않는다(TOCTOU 레이스). 이 모듈은 origin의
`refs/heads/harness-claims` 브랜치에 `claims/<task-id>.json`을 두어 claim을 실시간
공유한다.

왜 브랜치인가 (HARN-09 — 네임스페이스 이전):
    원래 설계는 `refs/claims/<id>`였으나 **이 실행 환경의 git 프록시가 그 네임스페이스
    push를 거부**한다(HTTP 403 → hung up). 2026-07-28 실측이 원인을 좁혔다:

        refs/claims/<id>  blob push  → 거부
        refs/heads/<id>   커밋 push  → **성공**

    권한이 아니라 네임스페이스 문제였다. 그래서 브랜치 네임스페이스로 옮긴다.
    **태스크당 브랜치가 아니라 단일 브랜치**인 이유는 같은 프록시가 ref *삭제*도
    거부하기 때문이다 — 태스크당 브랜치면 해제가 불가능해 93개+가 영구 누적된다.
    단일 브랜치면 해제가 그냥 "파일을 지우는 커밋"이라 삭제 push가 아예 불필요하다.

원자성 (CAS — compare-and-swap):
    git push --force-with-lease=refs/heads/harness-claims:<base-sha> \
             origin <commit>:refs/heads/harness-claims
    lease가 base sha와 다르면(= 그 사이 남이 push했으면) 서버가 거부한다. 서버는 ref
    갱신을 트랜잭션 처리하므로 두 세션이 동시에 push해도 정확히 한쪽만 성공한다 —
    lock 파일 없는 진짜 원자적 claim. 브랜치 최초 생성은 lease를 빈 값으로 준다
    (= "그 ref가 아직 없어야만 성공").

    **경합 재시도**: lease 거부는 "이 태스크가 남에게 잡혔다"가 아니라 "그 사이 *누군가*
    브랜치를 갱신했다"는 뜻이다(대개 다른 태스크의 claim). 그래서 재fetch 후 재시도하며,
    재시도 중 내 태스크가 실제로 잡혔음을 트리에서 확인했을 때만 conflict로 판정한다.
    **태스크 점유 판정은 push stderr가 아니라 트리 내용이 결정한다** — 이 분리가
    "남의 claim"과 "동시 갱신"을 혼동하지 않게 한다.

    트리는 `git mktree`로 직접 만든다(인덱스 미사용) — 사용자의 인덱스·작업 트리를
    건드릴 수 없는 구조라 GIT_INDEX_FILE 오염 위험이 원천 차단된다.

폴백 (fail-open — 훅·CLI가 개발을 볼모로 잡지 않는다):
    - offline/error(네트워크·권한): 경고 + 이벤트 로그 후 아래 *읽기측 탐지*로 폴백.
    - conflict(다른 세션이 이미 claim): 정보가 확정적이므로 이것만 차단.

읽기측 교차 세션 탐지 (HARN-07 — CAS가 막힌 환경의 부분 방어):
    HARN-09 이전에는 CAS가 **한 번도 성공한 적이 없어**(위 403) fail-open이 모든
    start를 통과시켰고, 중복 방지가 상시 무력이었다 — 그 결과가 병렬 중복 구현 2회
    (OPS-07 → #611, OPS-12 → #618)다. 쓰기가 막혀도 **읽기는 됐으므로**
    `scan_remote_in_progress()`가 원격 브랜치들의 backlog 사본을 읽어 같은 태스크가
    이미 in_progress인지 탐지한다.

    HARN-09로 CAS가 복구된 뒤에도 이 경로는 **제거하지 않는다** — 진짜 오프라인·권한
    문제로 CAS가 실패하는 환경에서 여전히 2선 방어다. 다만 CAS가 성공하면 읽기측
    스캔은 돌지 않는다(중복이며 느리다).

    이것은 CAS의 대체가 아니라 *부분* 방어다 (과장 금지):
      · 상대 세션이 **브랜치를 push한 뒤에만** 보인다 — push 전 로컬에서 작업 중인
        세션은 이 방법으로 절대 잡히지 않는다.
      · **원자성이 없다** — 두 세션이 동시에 스캔하면 둘 다 "충돌 없음"을 볼 수 있다.
    그러므로 CAS 경로는 제거하지 않는다. 프록시 정책이 다른 환경(로컬 개발·다른 러너)
    에서는 CAS가 작동하며 원자성은 그쪽이 우월하다. 읽기측은 CAS 실패 시에만 돈다.

stale 홀더 처리 (HARN-08 — 읽기측의 과탐 해소):
    머지·폐기된 브랜치에 남은 in_progress가 그 태스크를 **영구 차단**하던 문제를
    2개 규칙으로 해소한다(SQUASH 머지 저장소라 조상 검사는 쓸 수 없다 — 머지된
    브랜치도 trunk의 조상이 아니다. 2026-07-27 5건 전수 실측):
      · 규칙 A(트렁크 권위) — 트렁크(origin/HEAD)의 사본이 done/cancelled면 그 작업은
        이미 착륙했다. 다른 브랜치 사본의 in_progress는 역사적 잔재 → 홀더 전부 무시.
      · 규칙 B(트렁크는 세션이 아니다) — claim의 의미는 "어떤 *세션*이 그 브랜치에서
        작업 중"이다. 트렁크는 머지된 결과지 작업 세션이 아니므로 홀더 후보에서 제외.
        트렁크에 남은 in_progress는 활성 claim이 아니라 대장 위생 실패(done 미기입 머지)다.
    나이(최종 커밋 경과일) 휴리스틱은 **의도적으로 넣지 않았다** — 실측 5건이 A+B로
    전부 해소되며, 나이 컷오프는 느리게 진행하는 실 세션을 오탐 해제할 위험만 더한다.
    걸러낸 홀더는 버리지 않고 ScanResult.skipped에 사유와 함께 남긴다(관측 가능성).

stale claim 청소: 세션이 release 없이 죽으면 claim 파일이 남는다 → `claims reap`이
3중 기준(TTL 초과·태스크 이미 done/cancelled·태스크 미존재)으로 감지·삭제.

    ⚠️ `list_claims`의 **상태값을 반드시 확인하라**. "claim 0건"과 "조회 실패"를
    구분하지 않으면 인프라가 죽었을 때 "0건 통과"로 위장된다 — HARN-09 착수 실측에서
    CI의 교차검증 스텝이 정확히 그 상태였다(refs/claims/*가 0건이라 `reap`이 늘
    "stale claim 없음"을 보고). 빈 목록은 상태가 ok일 때만 "없음"을 의미한다.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from models import Backlog, Task

# claim 저장소 = origin의 단일 브랜치. 태스크당 파일 1개.
CLAIMS_BRANCH = "harness-claims"
CLAIMS_REF = f"refs/heads/{CLAIMS_BRANCH}"
CLAIMS_DIR = "claims"
# 로컬 미러 ref (로컬 브랜치와 충돌 없는 전용 공간 — 체크아웃 대상이 아니다)
LOCAL_MIRROR_REF = "refs/whymath-claims/head"
# lease 거부 후 재시도 횟수. 경합은 "남이 *다른* 태스크를 claim했다"가 대부분이라
# 몇 번이면 수렴한다. 무한 재시도는 start를 볼모로 잡으므로 유한하게 자른다.
CAS_RETRIES = 3

# push 거부 = **lease 경합**(그 사이 남이 브랜치를 갱신) 판별 패턴.
# 주의: 이것은 "내 태스크가 잡혔다"가 아니다 — 태스크 점유는 트리에서만 판정한다.
_LEASE_MARKERS = ("[rejected]", "stale info", "already exists", "non-fast-forward", "fetch first")
# 네트워크·환경 문제 판별 패턴
_OFFLINE_MARKERS = (
    "could not resolve",
    "unable to access",
    "connection",
    "timed out",
    "no such remote",
    "does not appear to be a git repository",
    "could not read from remote",
)


@dataclass
class RemoteClaim:
    """원격 claim 1건 = refs/claims/<task_id> ref 1개."""

    task_id: str
    sha: str
    branch: str = ""  # 메타 fetch 후 채워짐
    ts: str = ""  # UTC ISO8601
    meta: dict | None = None

    @property
    def kind(self) -> str:
        """`claim`(착수 점유) 또는 `block`(차단 홀드 — HARN-42).

        `kind` 없는 레코드는 전부 claim이다(구버전 호환) — 차단 홀드는 이 필드를
        명시적으로 넣은 것만 인정한다. 반대로 하면 메타 파손이 차단으로 읽힌다.
        """
        return str((self.meta or {}).get("kind") or "claim")

    @property
    def reason(self) -> str:
        return str((self.meta or {}).get("reason") or "")


@dataclass
class ClaimResult:
    """claim/release 시도 결과."""

    status: str  # ok | conflict | offline | error
    claim: RemoteClaim | None = None  # conflict 시 상대 claim 정보 (메타 조회 성공 시)
    message: str = ""


class GitOutputDecodeError(RuntimeError):
    """git 출력 디코드 실패 (HARN-19).

    이 이름이 존재하는 이유는 *분류* 때문이다. 디코드는 subprocess의 reader 스레드에서
    터지므로 호출측에는 예외가 아니라 `stdout=None`으로 도착하고, 그대로 두면 소비자가
    None을 만져 `AttributeError`가 된다 — 경고에 찍히는 타입명이 원인을 오도한다.
    """


def _git(
    root: Path,
    *argv: str,
    timeout: int = 15,
    input_text: str | None = None,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """git 실행 — 테스트 monkeypatch 지점. 인증 프롬프트 행 방지.

    `env_extra`는 `commit-tree`의 신원(author/committer)용이다. CI 러너나 갓 만든
    클론에는 `user.email`이 없어 commit-tree가 실패할 수 있는데, claim 커밋은 사람의
    저작물이 아니라 하네스의 기록이므로 전역 git 설정에 의존하지 않는다.
    """
    import os

    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env_extra or {})}
    # HARN-36: stdin은 **바이트로** 넘긴다. text 모드 stdin은 TextIOWrapper의 개행 변환을
    # 타서 Windows에서 '\n'이 '\r\n'으로 바뀌고, mktree가 그 '\r'를 파일명에 포함시켰다
    # (실측: harness-claims 트리의 "claims\r/MISC-16.json\r" — 2026-08-25 Windows 세션 기록).
    # 바이트 stdin은 변환 계층 자체가 없어 구조적으로 차단된다.
    raw = subprocess.run(
        ["git", *argv],
        cwd=root,
        capture_output=True,
        timeout=timeout,
        input=None if input_text is None else input_text.encode("utf-8"),
        env=env,
    )
    # HARN-19: 출력 디코드는 utf-8 고정 — locale 기본(한국어 Windows=cp949)은 git의
    # UTF-8 출력(태스크 YAML 한글 등)에서 붕괴한다. errors='replace' 근거: strict면
    # 바이트 하나 때문에 호출 *전체*가 실패하고, 소비자들은 fail-open이라 보호가 통째로
    # 죽는다(HARN-11 상시 무력 선례). 한 항목만 깨진 문자로 남기는 편이 낫다.
    # HARN-19 ②(마스킹 제거)의 stdout=None 축은 수동 디코드로 구조가 바뀌었지만 계약은
    # 유지한다 — capture_output 바이너리 모드에서 stdout이 None이면 원인 불명의 큰 실패다.
    if raw.stdout is None and raw.returncode == 0:
        raise GitOutputDecodeError(f"git {argv[0]}: stdout 캡처 실패 (stdout=None)")
    return subprocess.CompletedProcess(
        args=raw.args,
        returncode=raw.returncode,
        stdout=None if raw.stdout is None else raw.stdout.decode("utf-8", errors="replace"),
        stderr=None if raw.stderr is None else raw.stderr.decode("utf-8", errors="replace"),
    )


# claim 커밋의 고정 신원 — 전역 git 설정 부재 환경에서도 commit-tree가 성립하게 한다.
_COMMIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "whymath-harness",
    "GIT_AUTHOR_EMAIL": "harness@whymath.invalid",
    "GIT_COMMITTER_NAME": "whymath-harness",
    "GIT_COMMITTER_EMAIL": "harness@whymath.invalid",
}


def has_remote(root: Path) -> bool:
    """origin 원격이 설정되어 있는가."""
    try:
        return _git(root, "remote", "get-url", "origin", timeout=10).returncode == 0
    except Exception:
        return False


def list_remote_branches(root: Path) -> tuple[frozenset[str] | None, str]:
    """origin의 브랜치 단축명 집합. 반환 `(집합, 상태)` — 상태 `ok|offline|error`.

    **반환값이 `None`인 것과 `frozenset()`인 것은 완전히 다르다**:
      · `None`   = 조회 실패 → 이 집합에 기대는 판정은 **건너뛴다**(판정 보류).
      · 빈 집합  = 조회 성공했고 브랜치가 정말 하나도 없다.

    이 구분이 없으면 네트워크 한 번 끊긴 것이 "원격에 브랜치가 전멸했다"로 읽혀
    살아 있는 claim을 전부 지운다 — 측정 실패가 판정으로 위장되는 전형이다
    (CLAUDE.md AI·신뢰 / HARN-09 CI 공전 선례와 같은 축).

    왕복은 **1회**다. claim 건당 `ls-remote`를 부르면 대장이 커질수록 SessionStart가
    느려지므로, 호출부가 이 집합을 한 번 받아 `stale_claims`에 그대로 넘긴다.
    """
    if not has_remote(root):
        return None, "offline"
    try:
        result = _git(root, "ls-remote", "--heads", "origin", timeout=20)
    except subprocess.TimeoutExpired:
        return None, "offline"
    except Exception as exc:  # pragma: no cover - 환경 의존
        # 침묵 실패 금지 — 예외 타입명을 남긴다(시크릿·값은 제외).
        logging.getLogger("whymath.harness.claims").warning(
            "원격 브랜치 조회 실패: %s", type(exc).__name__
        )
        return None, "error"
    if result.returncode != 0:
        return None, _classify_failure(result.stderr or "")
    branches: set[str] = set()
    for line in (result.stdout or "").splitlines():
        _, _, ref = line.partition("\t")
        ref = ref.strip()
        if ref.startswith("refs/heads/"):
            branches.add(ref[len("refs/heads/") :])
    if not branches:
        # rc=0인데 브랜치가 0개 = 정상 저장소에서 나올 수 없는 출력(최소 트렁크는 있다).
        # 파싱 실패·응답 절단을 "원격에 브랜치가 전멸했다"로 읽으면 대장을 통째로 지운다.
        return None, "error"
    return frozenset(branches), "ok"


def is_shallow_repo(root: Path) -> bool:
    """이 저장소가 shallow 클론인가 — 트렁크 히스토리 기반 판정의 전제 조건.

    2026-08-11 사고: CCR 컨테이너 클론이 shallow(`origin/main` 50커밋·경계 2026-08-06)
    였는데 `scan_stale_branches`가 그걸 모른 채 판정했다. 결과는 브리핑 "미해결 19건"
    중 10건 오분류 — 예컨대 `claude/whymath-ai-tutor-design-953m1e`는 PR #705로 이미
    trunk에 흡수됐는데도 "Kiki 결정 필요"로 떴다(흡수 커밋이 절단면 밖이라 grep이 못 봄).
    `ahead` 수치도 같은 이유로 667까지 부풀었다.

    실패를 실패로 신고하지 않으면 "근거 없음"과 "히스토리가 없어 못 봄"이 같은 화면이
    된다 — CLAUDE.md "침묵 실패 금지"·"변별력 없는 검증 스텝 금지"의 직접 위반이다.

    폴백이 True(=판정 보류)인 이유: 판정 불가를 신뢰로 오해하는 쪽이 사고를 만든다.
    worktree 세션에서는 `.git`이 파일이라 `root/".git"/"shallow"` 직접 조회가 틀리므로
    2차 판정도 `--git-common-dir`를 경유한다.
    """
    try:
        result = _git(root, "rev-parse", "--is-shallow-repository", timeout=10)
        if result.returncode == 0 and result.stdout is not None:
            return result.stdout.strip().lower() == "true"
    except Exception:
        pass
    # 2차 — git < 2.15 등 `--is-shallow-repository` 미지원 환경
    try:
        common = _git(root, "rev-parse", "--git-common-dir", timeout=10)
        if common.returncode == 0 and common.stdout:
            return (root / common.stdout.strip() / "shallow").exists()
    except Exception:
        pass
    return True


SHALLOW_PENDING_MESSAGE = (
    "shallow 클론 — 트렁크 히스토리가 잘려 ahead 수치·포팅 근거를 신뢰할 수 없다. "
    "`git fetch --unshallow origin` 후 재실행하면 판정이 복원된다."
)


def _classify_failure(stderr: str) -> str:
    """git 실패 stderr → lease | offline | error.

    `lease`는 **경합 재시도** 신호이지 태스크 점유가 아니다(모듈 docstring 참조).
    태스크 점유는 오직 claim 브랜치의 트리를 읽어 판정한다.
    """
    low = stderr.lower()
    if any(m in low for m in _LEASE_MARKERS):
        return "lease"
    if any(m in low for m in _OFFLINE_MARKERS):
        return "offline"
    return "error"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── claim 캐시 — check-edit 훅용 (편집마다 네트워크 조회 금지) ────────────────
# brief/next/start가 원격 조회에 성공할 때마다 스냅샷을 남기고, 훅은 이것만 읽는다.
# .git/ 아래라 커밋 대상이 아니며 세션(클론)별 독립이다.


def _cache_path(root: Path) -> Path:
    return root / ".git" / "whymath-claims-cache.json"


def save_cache(root: Path, claims: list[RemoteClaim]) -> None:
    """원격 claim 스냅샷 저장 (best-effort — 실패 무시)."""
    try:
        payload = [{"task": c.task_id, "branch": c.branch, "ts": c.ts} for c in claims]
        _cache_path(root).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def load_cache(root: Path) -> dict[str, str]:
    """캐시된 claim 스냅샷 로드 — task_id → branch (실패 시 빈 dict)."""
    try:
        raw = json.loads(_cache_path(root).read_text(encoding="utf-8"))
        return {str(e["task"]): str(e.get("branch", "?")) for e in raw}
    except Exception:
        return {}


def _sanitize_ident(value: str) -> str:
    """task_id·branch에서 CR/LF·양끝 공백 제거 — 트리 경로·메타에 개행이 스미는 것을 차단.

    HARN-36: Windows에서 `git branch --show-current` 류 출력이 CR을 달고 오거나 호출측
    문자열에 개행이 섞이면, 그 값이 그대로 claim 파일명·메타가 되어 Linux 세션의 경로
    대조(`claims/<id>.json`)가 조용히 어긋난다. 이름은 식별자다 — 개행은 내용일 수 없다.
    """
    return value.replace("\r", "").replace("\n", "").strip()


def _claim_path(task_id: str) -> str:
    return f"{CLAIMS_DIR}/{task_id}.json"


def _fetch_claims_branch(root: Path) -> tuple[str, str]:
    """claim 브랜치를 로컬 미러로 가져온다 → (base_sha, 상태).

    base_sha가 빈 문자열이면 **브랜치가 아직 없다**(= claim 0건). 이것은 정상 상태이며
    상태 ok로 보고한다 — 조회 실패(offline/error)와 구분되어야 한다. 그 구분이 없으면
    인프라 장애가 "0건 통과"로 위장된다.
    """
    ls = _git(root, "ls-remote", "origin", CLAIMS_REF, timeout=20)
    if ls.returncode != 0:
        return "", _classify_failure(ls.stderr)
    if not ls.stdout.strip():
        return "", "ok"  # 브랜치 미존재 = claim 0건
    fetch = _git(
        root,
        "fetch",
        "--quiet",
        "--force",
        "origin",
        f"+{CLAIMS_REF}:{LOCAL_MIRROR_REF}",
        timeout=30,
    )
    if fetch.returncode != 0:
        return "", _classify_failure(fetch.stderr)
    rev = _git(root, "rev-parse", LOCAL_MIRROR_REF, timeout=10)
    if rev.returncode != 0:
        return "", "error"
    return rev.stdout.strip(), "ok"


def _read_claims(root: Path, base_sha: str) -> list[RemoteClaim]:
    """base 커밋의 트리에서 claim 전건을 읽는다 — 왕복 없이 로컬 객체만 본다."""
    if not base_sha:
        return []
    # HARN-36: pathspec을 걸지 않는다 — 구버전 Windows 세션이 남긴 오염 디렉터리
    # ("claims\r/")는 pathspec "claims/"에 매칭되지 않아 git 단계에서 통째로 사라진다.
    # claim 브랜치 트리는 _write_claims가 claims 디렉터리만 담게 만들므로 전체 나열이 싸고,
    # 대조는 아래 코드측 필터(CR 정규화 경유)가 단일 지점으로 수행한다.
    ls = _git(root, "ls-tree", "-r", "-z", base_sha, timeout=15)
    if ls.returncode != 0:
        return []
    claims: list[RemoteClaim] = []
    for entry in ls.stdout.split("\0"):
        if not entry.strip():
            continue
        info, _, path = entry.partition("\t")
        fields = info.split()
        if len(fields) < 3 or fields[1] != "blob":
            continue
        blob_sha = fields[2]
        # HARN-36: 경로의 CR을 정규화하고 나서 대조한다 — 구버전 Windows 세션이 남긴
        # 오염 레코드("claims\r/MISC-16.json\r")도 활성 claim으로 계속 인식돼야
        # 브랜치 보호(중복 구현 차단)가 끊기지 않는다. 다음 뮤테이션이 전체 트리를
        # 다시 쓰므로 오염은 그 시점에 자연 치유된다.
        path = path.replace("\r", "")
        if not path.startswith(f"{CLAIMS_DIR}/") or not path.endswith(".json"):
            continue
        task_id = path[len(CLAIMS_DIR) + 1 : -len(".json")]
        cat = _git(root, "cat-file", "blob", blob_sha, timeout=10)
        meta: dict | None = None
        if cat.returncode == 0:
            try:
                meta = json.loads(cat.stdout)
            except json.JSONDecodeError:
                meta = None
        claims.append(
            RemoteClaim(
                task_id=task_id,
                sha=blob_sha,
                branch=str((meta or {}).get("branch", "")),
                ts=str((meta or {}).get("ts", "")),
                meta=meta,
            )
        )
    return claims


def _write_claims(root: Path, base_sha: str, claims: list[RemoteClaim], message: str) -> str:
    """claim 목록을 담은 커밋을 만들어 sha를 돌려준다 (push는 하지 않는다).

    트리는 `git mktree`로 직접 만든다 — **인덱스를 쓰지 않으므로** 사용자의 스테이징
    영역·작업 트리를 건드릴 수 없다(구조적 차단).
    """
    entries: list[str] = []
    for c in sorted(claims, key=lambda x: x.task_id):
        payload = json.dumps(c.meta or {}, ensure_ascii=False, sort_keys=True)
        blob = _git(root, "hash-object", "-w", "--stdin", input_text=payload)
        if blob.returncode != 0:
            raise RuntimeError(f"blob 생성 실패: {blob.stderr.strip()}")
        entries.append(f"100644 blob {blob.stdout.strip()}\t{c.task_id}.json")

    if entries:
        sub = _git(root, "mktree", input_text="\n".join(entries) + "\n")
        if sub.returncode != 0:
            raise RuntimeError(f"claims 트리 생성 실패: {sub.stderr.strip()}")
        root_entries = f"040000 tree {sub.stdout.strip()}\t{CLAIMS_DIR}\n"
    else:
        root_entries = ""  # claim 0건 = 빈 트리 (해제로 마지막 claim이 사라진 경우)

    tree = _git(root, "mktree", input_text=root_entries)
    if tree.returncode != 0:
        raise RuntimeError(f"루트 트리 생성 실패: {tree.stderr.strip()}")

    argv = ["commit-tree", tree.stdout.strip()]
    if base_sha:
        argv += ["-p", base_sha]
    argv += ["-m", message]
    commit = _git(root, *argv, env_extra=_COMMIT_IDENTITY)
    if commit.returncode != 0:
        raise RuntimeError(f"커밋 생성 실패: {commit.stderr.strip()}")
    return commit.stdout.strip()


def _push_claims(root: Path, base_sha: str, commit_sha: str) -> subprocess.CompletedProcess:
    """CAS push — lease가 base_sha와 다르면 서버가 거부한다."""
    return _git(
        root,
        "push",
        "--quiet",
        f"--force-with-lease={CLAIMS_REF}:{base_sha}",
        "origin",
        f"{commit_sha}:{CLAIMS_REF}",
        timeout=30,
    )


def _mutate_claims(
    root: Path,
    task_id: str,
    message: str,
    apply: "callable",
) -> ClaimResult:
    """fetch → 검사 → 커밋 → CAS push를 lease 경합에 대해 재시도하는 공통 루프.

    `apply(existing, current_claims)`는 (새 목록, 조기반환 ClaimResult|None)을 돌려준다.
    조기반환이 있으면 push 없이 그대로 반환한다(예: 남의 claim이라 conflict).
    """
    last = ""
    for _attempt in range(CAS_RETRIES):
        base_sha, status = _fetch_claims_branch(root)
        if status != "ok":
            return ClaimResult(status, message=f"claim 브랜치 조회 실패: {status}")
        current = _read_claims(root, base_sha)
        existing = next((c for c in current if c.task_id == task_id), None)
        new_claims, early = apply(existing, current)
        if early is not None:
            return early
        try:
            commit_sha = _write_claims(root, base_sha, new_claims, message)
        except RuntimeError as exc:
            return ClaimResult("error", message=str(exc))
        push = _push_claims(root, base_sha, commit_sha)
        if push.returncode == 0:
            return ClaimResult("ok")
        last = push.stderr.strip()
        kind = _classify_failure(push.stderr)
        if kind != "lease":
            return ClaimResult(kind, message=last)
        # lease 경합 — 그 사이 남이 브랜치를 갱신했다. 재fetch 후 다시 시도한다.
        # (내 태스크가 실제로 잡혔는지는 다음 회차의 트리 검사가 판정한다.)
    return ClaimResult(
        "error",
        message=f"CAS 재시도 {CAS_RETRIES}회 초과 (lease 경합 지속): {last}",
    )


def claim(root: Path, task_id: str, branch: str) -> ClaimResult:
    """태스크를 원자적으로 원격 claim. 이미 다른 세션이 잡고 있으면 conflict."""
    task_id, branch = _sanitize_ident(task_id), _sanitize_ident(branch)  # HARN-36
    if not has_remote(root):
        return ClaimResult("offline", message="origin 원격 없음 — 로컬 claim만 사용")
    meta = {
        "task": task_id,
        "branch": branch,
        "ts": _utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "harness": "2.0",
    }
    mine = RemoteClaim(task_id, "", branch, str(meta["ts"]), meta)

    def apply(
        existing: RemoteClaim | None, current: list[RemoteClaim]
    ) -> tuple[list[RemoteClaim], ClaimResult | None]:
        if existing is not None and existing.branch != branch:
            # 태스크 점유 판정은 **트리 내용**이 한다 — push stderr가 아니라.
            #
            # `existing.branch`가 비어 있어도(메타 파손·구버전 기록) **conflict로 친다**.
            # "홀더를 특정할 수 없으니 통과"는 조용한 탈취이고, 그건 이 모듈이 막으려는
            # 바로 그 사고다. 막힌 경우의 복구 경로는 `claims release --force`로 명시한다.
            holder = existing.branch or "홀더 불명(메타 파손)"
            return [], ClaimResult(
                "conflict",
                claim=existing,
                message=f"'{holder}'가 이미 claim (ts={existing.ts or '?'})"
                + ("" if existing.branch else f" — 복구: claims release {task_id} --force"),
            )
        others = [c for c in current if c.task_id != task_id]
        return [*others, mine], None

    try:
        result = _mutate_claims(root, task_id, f"claim {task_id} ({branch})", apply)
        if result.status == "ok" and result.claim is None:
            result.claim = mine
        return result
    except subprocess.TimeoutExpired:
        return ClaimResult("offline", message="git 타임아웃")
    except Exception as exc:  # pragma: no cover - 환경 의존
        return ClaimResult("error", message=f"{type(exc).__name__}: {exc}")


def hold(root: Path, task_id: str, branch: str, reason: str) -> ClaimResult:
    """차단(block)을 원격 대장에 게시한다 — 병렬 세션의 `start`가 즉시 보게 (HARN-42).

    **왜 필요한가** (2026-08-31 실측 사고): `cmd_block`은 태스크 YAML에 `blocked`를
    쓰고 원격 claim을 *해제*했다. 그런데 YAML은 **main에 머지돼야** 병렬 세션에
    보이고, 이 저장소의 머지 지연은 CI(~30분)+base 전진 경합(HARN-32)으로 시간
    단위다. 즉 차단은 **보호를 거는 순간 오히려 원격 신호를 지웠고**, 그 창에서
    다른 세션이 아무 마찰 없이 착수했다.

    실사고: `CUR-11` block 00:28:07 → 13분 뒤 타 세션 claim 00:41:24 → 그 세션이
    구현·머지 완료(PR #920). 차단은 대장에 실재했고 `next`에서도 사라졌지만
    미머지 브랜치에 있었기에 아무것도 막지 못했다.

    `harness-claims` 브랜치는 **머지 없이 즉시 push**되는 유일한 교차 세션 채널이다.
    차단을 그 채널에 실으면 보호가 조치 시점에 발효한다.

    점유 규칙은 claim과 동일하다 — 다른 브랜치가 이미 잡고 있으면 conflict를 낸다.
    남의 착수를 차단으로 덮어쓰지 않는다(적대적 탈취 방지).
    """
    task_id, branch = _sanitize_ident(task_id), _sanitize_ident(branch)  # HARN-36
    if not has_remote(root):
        return ClaimResult("offline", message="origin 원격 없음 — 로컬 차단만 적용")
    meta = {
        "task": task_id,
        "branch": branch,
        "ts": _utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "harness": "2.0",
        "kind": "block",
        "reason": reason[:500],
    }
    mine = RemoteClaim(task_id, "", branch, str(meta["ts"]), meta)

    def apply(
        existing: RemoteClaim | None, current: list[RemoteClaim]
    ) -> tuple[list[RemoteClaim], ClaimResult | None]:
        if existing is not None and existing.branch != branch and existing.kind == "claim":
            holder = existing.branch or "홀더 불명(메타 파손)"
            return [], ClaimResult(
                "conflict",
                claim=existing,
                message=f"'{holder}'가 착수 claim 중이라 차단 홀드를 게시하지 않았다 "
                f"(ts={existing.ts or '?'}) — 그 세션과 조율이 먼저다",
            )
        others = [c for c in current if c.task_id != task_id]
        return [*others, mine], None

    try:
        result = _mutate_claims(root, task_id, f"block hold {task_id} ({branch})", apply)
        if result.status == "ok" and result.claim is None:
            result.claim = mine
        return result
    except subprocess.TimeoutExpired:
        return ClaimResult("offline", message="git 타임아웃")
    except Exception as exc:  # pragma: no cover - 환경 의존
        return ClaimResult("error", message=f"{type(exc).__name__}: {exc}")


def release(root: Path, task_id: str, branch: str, force: bool = False) -> ClaimResult:
    """원격 claim 해제 = claim 파일을 지우는 커밋. 남의 claim은 force 필수.

    ref 삭제 push를 쓰지 않는다 — 이 환경의 프록시가 삭제를 거부하기 때문이며,
    그 제약이 단일 브랜치 설계를 고른 이유다(모듈 docstring 참조).
    """
    task_id, branch = _sanitize_ident(task_id), _sanitize_ident(branch)  # HARN-36
    if not has_remote(root):
        return ClaimResult("offline", message="origin 원격 없음")

    def apply(
        existing: RemoteClaim | None, current: list[RemoteClaim]
    ) -> tuple[list[RemoteClaim], ClaimResult | None]:
        if existing is None:
            return [], ClaimResult("ok", message="원격 claim 없음 (해제 불필요)")
        if not force and existing.branch and existing.branch != branch:
            return [], ClaimResult(
                "error",
                claim=existing,
                message=f"'{existing.branch}'의 claim — 강제 해제는 --force 필수",
            )
        return [c for c in current if c.task_id != task_id], None

    try:
        return _mutate_claims(root, task_id, f"release {task_id}", apply)
    except subprocess.TimeoutExpired:
        return ClaimResult("offline", message="git 타임아웃")
    except Exception as exc:  # pragma: no cover - 환경 의존
        return ClaimResult("error", message=f"{type(exc).__name__}: {exc}")


def list_claims(root: Path, with_meta: bool = False) -> tuple[list[RemoteClaim], str]:
    """원격 claim 목록. (목록, 상태) — 상태 ok|offline|error.

    ⚠️ 호출자는 **상태를 반드시 확인**하라. 빈 목록은 상태가 ok일 때만 "claim 없음"을
    뜻한다. 상태를 무시하면 조회 실패가 "0건"으로 위장된다(모듈 docstring 참조).

    `with_meta`는 이제 무의미하다 — 브랜치 트리를 읽는 순간 메타가 함께 온다
    (구 구현은 ref마다 왕복했다). 호출부 호환을 위해 인자만 남긴다.
    """
    if not has_remote(root):
        return [], "offline"
    try:
        base_sha, status = _fetch_claims_branch(root)
        if status != "ok":
            return [], status
        return _read_claims(root, base_sha), "ok"
    except subprocess.TimeoutExpired:
        return [], "offline"
    except Exception:  # pragma: no cover - 환경 의존
        return [], "error"


def fetch_claim_meta(root: Path, claims: list[RemoteClaim]) -> None:
    """구 API 호환 — 메타는 `list_claims`가 이미 채운다(별도 왕복 불요)."""
    return


# ── 읽기측 교차 세션 탐지 (HARN-07) ─────────────────────────────────────────
# CAS push가 막힌 환경의 폴백. 쓰기는 403이어도 읽기(fetch/ls-remote)는 통과한다는
# 실측(2026-07-27)에 근거한다. 한계는 모듈 docstring 참조 — CAS 대체 아님.

# 원격 브랜치 스캔 상한 — 브랜치가 폭증한 저장소에서 start가 볼모가 되지 않게 자른다.
# 최근 커밋순으로 자르며, 잘렸으면 결과에 명시한다(조용한 축소 금지).
SCAN_MAX_REFS = 300
# 전체 브랜치 fetch 타임아웃 — 44브랜치 기준 실측 ~5초. 콜드 클론 여유 포함.
SCAN_FETCH_TIMEOUT = 90
REMOTE_REF_PREFIX = "refs/remotes/origin/"
# 트렁크 ref 해소 실패 시의 최종 폴백 브랜치명 (_resolve_trunk_ref 주석 참조)
FALLBACK_TRUNK_BRANCH = "main"
# 규칙 A — 트렁크에서 이 상태면 작업이 착륙한 것으로 본다 (둘 다 models.py 종결 상태)
TRUNK_SETTLED_STATUSES = ("done", "cancelled")


@dataclass
class InProgressHolder:
    """원격 브랜치의 backlog 사본에서 발견한 타 세션 in_progress claim 1건."""

    task_id: str
    ref: str  # refs/remotes/origin/<branch>
    branch: str  # <branch>
    session: str  # 태스크 YAML의 session 값 (claim한 세션 브랜치)


@dataclass
class SkippedHolder:
    """stale 판정으로 홀더에서 제외한 1건 (HARN-08).

    조용히 버리지 않는다 — 무엇을 왜 무시했는지 호출자가 보고할 수 있어야
    "보호가 걸렸다"와 "보호를 스스로 껐다"가 구분된다.
    """

    task_id: str
    ref: str
    branch: str
    session: str
    reason: str  # trunk_done | trunk_cancelled | trunk_not_session


@dataclass
class ScanResult:
    """읽기측 탐지 결과. status: ok | offline | error (ok가 아니면 판정 불가)."""

    status: str
    holders: list[InProgressHolder] = field(default_factory=list)
    skipped: list[SkippedHolder] = field(default_factory=list)
    scanned_refs: int = 0
    truncated: bool = False
    message: str = ""
    trunk_ref: str = ""  # 규칙 A·B의 기준 ref (refs/remotes/origin/<기본브랜치>)
    trunk_branch: str = ""  # 기준 ref의 브랜치명 (메시지용)
    trunk_status: str = ""  # 트렁크 사본의 태스크 status ("" = 파일 없음 → 규칙 A 신호 없음)
    trunk_source: str = ""  # symbolic-ref | ls-remote | fallback (해소 경로 — 관측용)


def _top_level_field(text: str, key: str) -> str:
    """태스크 YAML 본문에서 최상위 스칼라 키 1개를 뽑는다 (PyYAML 비의존).

    store.dump_task는 1단 매핑만 쓰고 리스트는 '  - ' 들여쓰기로 내므로,
    들여쓰기 없는 '<key>: ' 줄만 보면 값 안의 콜론과 충돌하지 않는다.
    손편집으로 형식이 어긋난 파일은 못 읽고 넘어간다 — 탐지 실패는 미탐이며,
    미탐은 호출측이 '부분 방어'로 이미 선언한 한계 안에 있다.
    """
    prefix = f"{key}:"
    for line in text.splitlines():
        if not line.startswith(prefix):
            continue
        value = line[len(prefix) :].strip()
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = value[1:-1]
        return "" if value in ("null", "~", "") else value
    return ""


def _top_level_list_field(text: str, key: str) -> list[str]:
    """태스크 YAML 본문에서 최상위 리스트 필드를 뽑는다 (`_top_level_field`의 리스트 버전).

    `store.dump_task`가 내는 두 형태만 지원한다: `key: []`(빈 리스트) 또는 `key:` 다음
    `  - value` 들여쓰기 줄들. 손편집으로 형식이 어긋난 파일(플로우 스타일 `[a, b]` 등)은
    못 읽고 빈 리스트를 반환한다 — 탐지 실패는 미탐이며, `_top_level_field`와 같은 한계를
    그대로 승계한다(우리가 원격에서 읽는 파일은 전부 `store.dump_task`가 쓴 것이므로
    정상 경로에서는 이 한계에 걸리지 않는다).
    """
    prefix = f"{key}:"
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith(prefix):
            continue
        rest = line[len(prefix) :].strip()
        if rest == "[]":
            return []
        if rest:
            return []  # 인라인 스칼라 — 리스트 형태가 아님(미탐)
        values: list[str] = []
        for item_line in lines[i + 1 :]:
            if not item_line.startswith("  - "):
                break
            item = item_line[4:].strip()
            if len(item) >= 2 and item.startswith('"') and item.endswith('"'):
                try:
                    item = json.loads(item)
                except json.JSONDecodeError:
                    item = item[1:-1]
            values.append(item)
        return values
    return []


def _resolve_trunk_ref(root: Path) -> tuple[str, str]:
    """기본(트렁크) 브랜치의 원격 ref를 해소한다 — (ref, 해소 경로).

    기본 브랜치명을 하드코딩하지 않는다 (main/master/trunk 어느 쪽이든 따라간다).
    **원격 권위를 먼저 묻는다** — 순서가 핵심이다:
      1) `git ls-remote --symref origin HEAD` — 원격이 지금 무엇을 HEAD로 두는지
         직접 묻는다(실측 0.3초). 읽기측 스캔은 어차피 전체 fetch(~5초)를 하므로
         왕복 1회는 예산 안이다.
      2) `git symbolic-ref refs/remotes/origin/HEAD` — 로컬 캐시(네트워크 0).
         **stale일 수 있어 2순위다**: 이 값은 clone 시점(또는 마지막
         `git remote set-head`) 스냅샷이라 origin을 갈아끼우면 그대로 남는다.
         2026-07-27 실측에서 **세션 브랜치를 가리키는 클론**이 관측됐다 — 그 상태로
         1순위였다면 규칙 A가 남의 세션 브랜치를 '트렁크 권위'로 삼아 **미탐(보호
         무력화)** 을 냈다. 원격이 대답하지 못할 때만 쓰는 폴백으로 강등한 이유다.
      3) 둘 다 실패(오프라인·권한) → 폴백 'main'.

    폴백이 틀린 경우(기본 브랜치가 master 등)의 방향: 그 ref가 존재하지 않아 규칙 A의
    신호가 '없음'이 되고 규칙 B는 아무것도 거르지 않는다 — HARN-07의 과탐(차단 과다)
    상태로 되돌아갈 뿐 미탐은 만들지 않는다. 해소 경로는 ScanResult.trunk_source로
    노출되어 '어느 근거로 판정했는가'가 매번 보인다.
    """
    try:
        ls = _git(root, "ls-remote", "--symref", "origin", "HEAD", timeout=15)
        if ls.returncode == 0:
            for line in ls.stdout.splitlines():
                # 형식: "ref: refs/heads/main\tHEAD"
                if line.startswith("ref:") and "HEAD" in line:
                    head = line[len("ref:") :].split("\t")[0].strip()
                    if head.startswith("refs/heads/"):
                        return REMOTE_REF_PREFIX + head[len("refs/heads/") :], "ls-remote"
    except Exception:  # pragma: no cover - 환경 의존
        pass
    try:
        sym = _git(root, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", timeout=10)
        ref = sym.stdout.strip()
        if sym.returncode == 0 and ref.startswith(REMOTE_REF_PREFIX):
            return ref, "symbolic-ref"
    except Exception:  # pragma: no cover - 환경 의존 (git 부재 등)
        pass
    return REMOTE_REF_PREFIX + FALLBACK_TRUNK_BRANCH, "fallback"


def _trunk_task_status(root: Path, trunk_ref: str, task_id: str) -> str:
    """트렁크 사본의 태스크 status. 파일이 없거나 못 읽으면 "" (= 규칙 A 신호 없음)."""
    try:
        show = _git(root, "show", f"{trunk_ref}:backlog/tasks/{task_id}.yaml", timeout=10)
    except Exception:  # pragma: no cover - 환경 의존
        return ""
    if show.returncode != 0:
        return ""  # 브랜치에서 신설된 태스크 — 트렁크에 아직 없다
    return _top_level_field(show.stdout, "status")


def _trunk_gate_status(root: Path, trunk_ref: str, gate_id: str) -> str:
    """트렁크 사본 gates.yaml에서 특정 게이트의 status. 없거나 못 읽으면 "" (신호 없음).

    `store.dump_gates`의 고정 출력 형태(`  - id: <id>` 다음 `    <key>: <value>` 들여쓰기
    블록)만 파싱한다 — `_trunk_task_status`와 같은 한계 선언(손편집 어긋남은 미탐).
    """
    try:
        show = _git(root, "show", f"{trunk_ref}:backlog/gates.yaml", timeout=10)
    except Exception:  # pragma: no cover - 환경 의존
        return ""
    if show.returncode != 0:
        return ""
    id_prefix = "  - id:"
    in_block = False
    for line in show.stdout.splitlines():
        if line.startswith(id_prefix):
            in_block = line[len(id_prefix) :].strip() == gate_id
            continue
        if not in_block:
            continue
        if not line.startswith("    "):
            in_block = False
            continue
        if line.strip().startswith("status:"):
            return line.split("status:", 1)[1].strip()
    return ""


@dataclass(frozen=True)
class TrunkDrift:
    """트렁크 사본이 로컬보다 착수 조건을 강화한 항목 1건 (HARN-91).

    `kind`: "dep"(트렁크에만 있는 미충족 의존) | "gate"(트렁크에만 있는 미통과 게이트).
    `trunk_state`: 그 항목의 트렁크 관점 상태(의존 태스크의 status·게이트의 status) —
        관측 자체가 안 됐으면 "?"(파일 없음·파싱 실패 — 모른다 ≠ 아니다이므로 미충족으로
        간주해 여전히 drift로 센다: 신규 항목의 부재는 안전 방향이 아니다).
    """

    kind: str
    ref_id: str
    trunk_state: str


@dataclass(frozen=True)
class TrunkDriftResult:
    """트렁크 의존·게이트 시차 탐지 결과. status가 `ok`가 아니면 판정 불가(HARN-91 ④-ⓓ)."""

    status: str  # ok | offline | error:<Type>
    drift: list[TrunkDrift] = field(default_factory=list)
    trunk_ref: str = ""


def scan_trunk_task_drift(root: Path, task: Task) -> TrunkDriftResult:
    """트렁크 사본의 태스크 파일에 로컬 사본엔 없는 미충족 의존·게이트가 있는지 본다.

    (HARN-91) `start`의 착수 자격 판정(`selector.classify_todo`)은 **로컬 작업 트리의
    백로그 사본**만 읽는다 — 내 클론이 마지막으로 fetch한 뒤 origin/<트렁크>에 새로
    착지한 의존·게이트(조건이 *강화*되는 방향)는 그 판정에 반영되지 않는다. 이 함수는
    트렁크 사본의 같은 태스크 파일을 직접 읽어 그 시차를 좁힌다.

    네트워크 비용: 이 함수 자체는 fetch하지 않는다 — 호출측(`cmd_start`)이 HARN-11의
    `scan_remote_done(fetch=True)`로 이미 remote-tracking ref를 최신화한 뒤 같은 fetch에
    편승한다(추가 왕복은 `_resolve_trunk_ref`의 `ls-remote` 1회뿐). 오프라인 환경에서
    쓰려면 호출측이 먼저 fetch 여부/상태를 판정해 이 함수 호출 여부를 결정한다.

    비교 대상은 **로컬에 없는 항목만**이다 — 로컬에 이미 있는 의존·게이트는
    `selector.classify_todo`가 이미 검사했다(중복 판정 금지). 로컬·트렁크가 같으면
    drift 0건이다(대조군 — 모든 착수를 막는 검사는 검사가 아니다).
    """
    if not has_remote(root):
        return TrunkDriftResult("offline")
    try:
        trunk_ref, _source = _resolve_trunk_ref(root)
        show = _git(root, "show", f"{trunk_ref}:backlog/tasks/{task.id}.yaml", timeout=10)
        if show.returncode != 0:
            # 트렁크에 이 태스크 파일이 없다 — 로컬에서 신설된 태스크(아직 트렁크 미착지).
            # 이 축의 관심사는 "트렁크가 조건을 강화했는가"이므로 신설 자체는 drift가 아니다.
            return TrunkDriftResult("ok", trunk_ref=trunk_ref)

        trunk_deps = _top_level_list_field(show.stdout, "depends_on")
        trunk_gates = _top_level_list_field(show.stdout, "requires_gates")

        drift: list[TrunkDrift] = []
        for dep_id in trunk_deps:
            if dep_id in task.depends_on:
                continue
            dep_status = _trunk_task_status(root, trunk_ref, dep_id)
            if dep_status != "done":
                drift.append(TrunkDrift("dep", dep_id, dep_status or "?"))

        for gate_id in trunk_gates:
            if gate_id in task.requires_gates:
                continue
            gate_status = _trunk_gate_status(root, trunk_ref, gate_id)
            if gate_status not in ("cleared", "waived"):
                drift.append(TrunkDrift("gate", gate_id, gate_status or "?"))

        return TrunkDriftResult("ok", drift, trunk_ref)
    except subprocess.TimeoutExpired:
        return TrunkDriftResult("offline")
    except Exception as exc:  # pragma: no cover - 환경 의존
        # 침묵 실패 금지 — 예외 타입명을 남긴다 (CLAUDE.md AI·신뢰)
        return TrunkDriftResult(f"error:{type(exc).__name__}")


def scan_remote_in_progress(
    root: Path, task_id: str, session: str, max_refs: int = SCAN_MAX_REFS
) -> ScanResult:
    """원격 브랜치들의 backlog 사본에서 이 태스크의 타 세션 in_progress를 찾는다.

    CAS claim(refs/claims/*)이 offline/error일 때만 호출하는 폴백이다
    (CAS 성공 시에는 불필요 — 전체 fetch 비용을 물지 않는다).

    한계 — 이것은 CAS의 원자성을 대체하지 못하는 *부분* 방어다:
        · 상대 세션이 **브랜치를 push한 뒤에만** 보인다.
        · 두 세션이 동시에 스캔하면 둘 다 '충돌 없음'을 볼 수 있다(원자성 없음).

    stale 처리 (HARN-08): 트렁크가 done/cancelled면 홀더 전부 무시(규칙 A),
    트렁크 ref 자신은 홀더가 될 수 없다(규칙 B). 걸러낸 건은 버리지 않고
    result.skipped에 사유와 함께 남긴다.

    반환 status가 'ok'가 아니면 **판정 자체가 불가**했다는 뜻이며, 빈 holders를
    '충돌 없음'으로 읽어서는 안 된다(측정 실패와 통과는 같은 색이면 안 된다).
    """
    if not has_remote(root):
        return ScanResult("offline", message="origin 원격 없음 — 교차 세션 탐지 불가")
    try:
        fetch = _git(
            root,
            "fetch",
            "--quiet",
            "--prune",
            "origin",
            "+refs/heads/*:refs/remotes/origin/*",
            timeout=SCAN_FETCH_TIMEOUT,
        )
        if fetch.returncode != 0:
            return ScanResult(
                _classify_failure(fetch.stderr),
                message=f"원격 브랜치 fetch 실패: {fetch.stderr.strip()}",
            )
        listing = _git(
            root,
            "for-each-ref",
            "--sort=-committerdate",
            "--format=%(refname)",
            "refs/remotes/origin",
        )
        if listing.returncode != 0:
            return ScanResult(
                _classify_failure(listing.stderr),
                message=f"원격 ref 열거 실패: {listing.stderr.strip()}",
            )
        refs = [
            r.strip()
            for r in listing.stdout.splitlines()
            if r.strip() and not r.strip().endswith("/HEAD")
        ]
        truncated = len(refs) > max_refs
        refs = refs[:max_refs]

        # 규칙 A·B의 기준점 — 기본 브랜치는 해소하고 하드코딩하지 않는다.
        trunk_ref, trunk_source = _resolve_trunk_ref(root)
        trunk_status = _trunk_task_status(root, trunk_ref, task_id)
        trunk_settled = trunk_status in TRUNK_SETTLED_STATUSES

        holders: list[InProgressHolder] = []
        skipped: list[SkippedHolder] = []
        for ref in refs:
            show = _git(root, "show", f"{ref}:backlog/tasks/{task_id}.yaml", timeout=10)
            if show.returncode != 0:
                continue  # 그 브랜치엔 이 태스크 파일이 없다 (태스크 신설 이전 시점 등)
            if _top_level_field(show.stdout, "status") != "in_progress":
                continue
            holder = _top_level_field(show.stdout, "session")
            if not holder or holder == session:
                continue  # 내 세션의 claim은 나를 막지 않는다
            branch = ref[len(REMOTE_REF_PREFIX) :] if ref.startswith(REMOTE_REF_PREFIX) else ref
            # [규칙 B] 트렁크는 머지된 결과지 작업 세션이 아니다 — 홀더가 될 수 없다.
            # 트렁크의 in_progress는 활성 claim이 아니라 done 미기입 머지(대장 위생 실패)다.
            if ref == trunk_ref:
                skipped.append(SkippedHolder(task_id, ref, branch, holder, "trunk_not_session"))
                continue
            # [규칙 A] 트렁크가 done/cancelled면 작업은 이미 착륙 — 사본의 in_progress는 잔재.
            if trunk_settled:
                skipped.append(SkippedHolder(task_id, ref, branch, holder, f"trunk_{trunk_status}"))
                continue
            holders.append(
                InProgressHolder(
                    task_id=task_id,
                    ref=ref,
                    branch=branch,
                    session=holder,
                )
            )
        return ScanResult(
            "ok",
            holders=holders,
            skipped=skipped,
            scanned_refs=len(refs),
            truncated=truncated,
            trunk_ref=trunk_ref,
            trunk_branch=(
                trunk_ref[len(REMOTE_REF_PREFIX) :]
                if trunk_ref.startswith(REMOTE_REF_PREFIX)
                else trunk_ref
            ),
            trunk_status=trunk_status,
            trunk_source=trunk_source,
        )
    except subprocess.TimeoutExpired:
        return ScanResult("offline", message="원격 브랜치 조회 타임아웃")
    except Exception as exc:  # pragma: no cover - 환경 의존
        # 침묵 실패 금지 — 예외 타입명을 반드시 남긴다 (CLAUDE.md AI·신뢰)
        return ScanResult("error", message=f"{type(exc).__name__}: {exc}")


def _claim_older_than(c: RemoteClaim, now: datetime, hours: int) -> bool | None:
    """claim이 `hours`보다 오래됐는가. `None` = 나이 불명(ts 없음·파싱 불가).

    "모른다"를 "오래됐다"로 반올림하면 방금 만들어진 claim을 지운다(HARN-21 결함③).
    그래서 bool이 아니라 3값을 돌려주고, 판정부가 명시적으로 보수 처리하게 한다.
    """
    if not c.ts:
        return None
    try:
        ts = datetime.strptime(c.ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return now - ts > timedelta(hours=hours)


def stale_claims(
    claims: list[RemoteClaim],
    backlog: Backlog,
    ttl_hours: int,
    now: datetime | None = None,
    *,
    existing_branches: frozenset[str] | None = None,
    branch_grace_hours: int = 24,
) -> list[tuple[RemoteClaim, str]]:
    """stale claim 판정 — (claim, 사유) 목록.

    사유: ttl | task_done | task_missing | task_missing_recent
          | branch_gone | branch_gone_recent.

    **`branch_gone`(HARN-26)**: claim의 홀더 브랜치가 origin에 더 이상 없다. 세션
    컨테이너는 수명이 짧고 브랜치를 스스로 지우지 못하는데(HARN-16), 그래도 홀더
    브랜치가 없다는 것은 그 세션의 작업이 원격에 도달한 적조차 없다는 뜻이다 —
    TTL 72시간을 기다릴 이유가 없는 확정 신호다.

    실측 근거(2026-08-11 03:00Z): 대장 5건 중 3건이 존재하지 않는 브랜치를 홀더로
    지목했다(MATH-01·MATH-02·HARN-20). 셋 다 "다른 세션이 작업 중"으로 표시돼 새 세션의
    착수가 막혀 있었다. HARN-20은 홀더 브랜치가 사라진 데다 로컬에서 이미 `done`이었다.

    **그런데 40분 뒤 재측정에서 MATH-01·MATH-02의 브랜치는 존재했다**(원격 브랜치
    44→47개). 두 세션은 죽은 게 아니라 `start`와 첫 push 사이의 정상 구간에 있었다.
    유예 없이 이 기준을 집행했다면 살아 있는 세션 2건의 claim을 지워 CAS가 막아둔
    중복 착수를 우리 손으로 열어줬을 것이다 — `branch_grace_hours`가 이론이 아니라
    관측된 경합에 대한 방어인 이유다. 실제 고아는 5건 중 1건(HARN-20)뿐이었다.

    **`existing_branches`가 `None`이면 이 기준 자체를 건너뛴다.** 조회 실패로 얻은 빈
    집합을 "브랜치 전멸"로 읽으면 살아 있는 claim을 모두 지운다 — `list_remote_branches`가
    `None`과 빈 집합을 구분해 돌려주는 이유이며, 이 함수는 그 구분을 그대로 존중한다.

    **`branch_grace_hours`(기본 24)**: `start`(claim)와 첫 push 사이에는 브랜치가 원격에
    없는 정상 구간이 있다. 그 창에서 남의 claim을 지우면 CAS로 막아둔 중복 착수를 우리가
    직접 열어주는 셈이다.

    TTL(72h)을 재사용하지 **않는** 이유는 그러면 이 기준의 변별력이 0이 되기 때문이다.
    `backlog/events.ndjson`의 start→done/block 쌍 199건 실측(2026-08-11):

        p50 0.46h · p75 0.89h · p90 1.50h · p95 5.15h · p99 54.0h · max 66.4h
        4h 초과 10건(5.0%) · 24h 초과 4건(2.0%) · **72h 초과 0건(0.0%)**

    72h를 넘긴 세션이 하나도 없으므로 grace=72h면 `branch_gone`이 잡는 집합은 이미
    `ttl`이 잡는 집합의 부분집합이 된다 — 성공/실패에 같은 값을 내는 검사와 같은 위장이다
    (CLAUDE.md "변별력 없는 검증 스텝 금지"). 24h는 오탐 상한이 2.0%로 측정됐고 TTL보다
    48시간 빠르다. 실제 오탐은 이보다 낮다 — 분포가 재는 것은 "완료까지 걸린 시간"인데
    이 기준이 요구하는 건 그보다 좁은 "24시간 동안 push를 단 한 번도 안 함"이다.

    `task_missing`(로컬 백로그에 해당 태스크가 아예 없음) 판정은 **경합 조건**을 낳을 수
    있었다(HARN-21 결함③): 세션 A가 `add`+`start`(claim)를 원격에 방금 반영했는데, 그
    직후 세션 B가 `claims reap`을 돌리면 — B의 로컬 클론엔 A가 방금 추가한 태스크 파일이
    아직 없다(A가 아직 안 머지했으므로). 구 구현은 이때 claim의 나이(`c.ts`)를 전혀 안
    보고 즉시 stale로 판정했다 — 몇 초 전에 생성된 claim도 지워버릴 수 있었다.

    수정: `ttl` 분기가 이미 쓰는 "나이 비교" 패턴을 `task_missing`에도 그대로 적용한다.
      - claim이 TTL 이내로 신선하면 → `task_missing_recent`(reap 대상 **아님** — 호출부가
        경고로만 노출한다. 완전히 침묵시키지 않는다 — CLAUDE.md 침묵 실패 금지).
      - claim에 ts가 없거나 파싱 불가면 → 나이를 모르므로 보수적으로 `task_missing_recent`
        (기존 `ttl` 분기의 "파싱 불가 메타는 판정 보류" 관례와 동형).
      - claim이 TTL을 넘겨 오래됐으면 → 기존대로 `task_missing`(진짜 삭제·취소된 태스크의
        잔재를 정리하는 정상 기능은 유지).
    """
    now = now or _utcnow()
    result: list[tuple[RemoteClaim, str]] = []
    for c in claims:
        task = backlog.tasks.get(c.task_id)
        if task is None:
            # 나이 불명(None)·TTL 이내는 모두 `_recent`(경합 조건 가능성 — 즉시 삭제 금지).
            older_than_ttl = _claim_older_than(c, now, ttl_hours)
            result.append((c, "task_missing" if older_than_ttl else "task_missing_recent"))
            continue
        if task.status in ("done", "cancelled"):
            result.append((c, "task_done"))
            continue
        # 홀더 브랜치 부재 (HARN-26) — TTL보다 앞에 둔다. 둘 다 해당하면 "브랜치가 없다"가
        # "오래됐다"보다 구체적이고 조치도 명확하기 때문이다.
        # `c.branch`가 비어 있으면(메타 파손) 판정하지 않는다 — 홀더를 특정할 수 없는 것과
        # 홀더가 사라진 것은 다르며, 전자는 `claims release --force`가 다루는 영역이다.
        if existing_branches is not None and c.branch and c.branch not in existing_branches:
            older = _claim_older_than(c, now, branch_grace_hours)
            # 나이 불명(None)은 유예 쪽으로 반올림한다 — 즉시 삭제 금지(보수적).
            result.append((c, "branch_gone" if older else "branch_gone_recent"))
            continue
        older_than_ttl = _claim_older_than(c, now, ttl_hours)
        if older_than_ttl:
            result.append((c, "ttl"))
    return result


# 자동 청소가 허용되는 사유 — **확정 신호만**(HARN-27).
#
# 이 집합을 워크플로 YAML의 문자열 인자로 두지 않는 이유: 안전 범위의 정의가 YAML에
# 살면 워크플로를 고치는 누구든 `ttl`을 끼워 넣어 넓힐 수 있고, 그 변경은 파이썬
# 테스트가 아니라 인프라 배선 테스트로만 잡힌다. 집합을 코드에 두면 단위 테스트가
# 직접 동결한다(`test_auto_reap_reasons_contains_only_confirmed_signals`).
#
# 제외한 사유와 근거:
#   · `ttl`          — 72h 무소식이 세션 사망은 아니다(실측 max 지속 66.4h로 경계에
#                      매우 가깝다). 살아 있는 장기 세션의 claim을 밤중에 지울 수 있다.
#   · `task_missing` — 판정 입력이 *실행 주체의 로컬 백로그*다. CI 러너는 main만 보므로
#                      다른 브랜치에서 등재된 태스크는 구조적으로 "missing"이다
#                      (HARN-15가 기록한 비가시 부채 맹점). 자동 삭제 대상으로 부적합.
#   · `*_recent`     — 정의상 유예 중.
AUTO_REAP_REASONS = frozenset({"task_done", "branch_gone"})


def reap(
    root: Path,
    backlog: Backlog,
    ttl_hours: int,
    dry_run: bool = True,
    *,
    branch_grace_hours: int = 24,
    reasons: frozenset[str] | None = None,
) -> tuple[list[str], str, list[str]]:
    """stale claim 청소. dry_run이면 목록만 반환, 아니면 실제 삭제.

    반환: (["task_id (사유)", ...], 조회 상태 ok|offline|error, ["경고 문자열", ...]).

    **`reasons`(HARN-27)**: 삭제 대상을 이 사유 집합으로 좁힌다. `None`이면 전체(기존
    동작 — 사람이 직접 `--apply`를 치는 경우). 자동 집행 경로는 `AUTO_REAP_REASONS`를
    넘겨 확정 신호만 지운다. 걸러진 건은 버리지 않고 경고 목록으로 올라간다.

    **홀더 브랜치 조회(HARN-26)**: `list_remote_branches`를 **1회** 호출해 `stale_claims`에
    넘긴다. 조회가 실패하면 `None`이 넘어가 `branch_gone` 판정만 조용히 빠지고 나머지
    기준(ttl·task_done·task_missing)은 그대로 작동한다 — 한 축의 조회 실패가 reap 전체를
    멈추게 하지도, 반대로 살아 있는 claim을 쓸어버리지도 않는다. 다만 침묵하지는 않는다:
    실패 시 경고 목록에 그 사실을 싣는다.

    **상태를 함께 돌려주는 이유**(HARN-09): 구 구현은 조회 실패 시 빈 목록만 돌려줘서
    호출자가 "stale 없음"과 "판정 불가"를 구분할 수 없었다. CI의 교차검증 스텝이 정확히
    그 상태로 공전했다 — 인프라가 죽어도 "0건 통과"로 보였다. 측정·게이트 도구가 실패를
    통과로 위장하면 안 된다(CLAUDE.md AI·신뢰).

    **세 번째 반환값(경고 목록, HARN-21)**: `stale_claims`가 `task_missing_recent`로
    분류한 claim은 reap 대상에서 제외되지만(경합 조건 방지), 그 사실을 조용히 넘기지
    않는다 — 방금 생성된 claim이 로컬에 안 보인다고 침묵하면, 그게 진짜 경합 조건인지
    다음 reap 실행자가 알 방법이 없다(CLAUDE.md 침묵 실패 금지).
    """
    claims, status = list_claims(root)
    if status != "ok":
        return [], status, []
    reaped: list[str] = []
    warnings: list[str] = []
    branches, branch_status = list_remote_branches(root)
    if branch_status != "ok":
        warnings.append(
            f"홀더 브랜치 조회 불가({branch_status}) — "
            "branch_gone 판정을 이번 실행에서 수행하지 않았다"
        )
    stale = stale_claims(
        claims,
        backlog,
        ttl_hours,
        existing_branches=branches,
        branch_grace_hours=branch_grace_hours,
    )
    for c, reason in stale:
        label = f"{c.task_id} ({reason}" + (f", {c.branch}" if c.branch else "") + ")"
        if reason.endswith("_recent"):
            # 유예 구간(경합 조건 가능성) — 삭제하지 않고 경고로만 노출한다.
            # `task_missing_recent`(HARN-21)·`branch_gone_recent`(HARN-26) 공통 규칙:
            # 둘 다 "다른 세션의 상태가 아직 내게 보이지 않는 창"이고, 해답도 같다.
            warnings.append(label)
            continue
        if reasons is not None and reason not in reasons:
            # 자동 집행에서 제외된 사유 — 사람 판단이 필요하다는 뜻이지 "없음"이 아니다.
            warnings.append(f"{label} — 자동 청소 제외 사유(사람 판단 필요)")
            continue
        if not dry_run:
            result = release(root, c.task_id, branch="", force=True)
            if result.status != "ok":
                # 삭제하지 못했으면 삭제했다고 보고하지 않는다. 다만 조용히 넘기지도
                # 않는다 — 토큰·권한 문제로 자동 청소가 상시 무력화되면 그 사실 자체가
                # 보여야 한다(CLAUDE.md 침묵 실패 금지·상시 실패 fail-open 금지).
                warnings.append(f"{label} — 해제 실패({result.status})")
                continue
        reaped.append(label)
    return reaped, "ok", warnings


# ── 미머지 done 탐지 (HARN-11) ────────────────────────────────────────────────
#
# HARN-07/08이 다룬 축의 **반대 방향**이다.
#   · HARN-08(과탐): 머지된 브랜치에 남은 in_progress가 착수를 영구 차단 → 규칙 A·B로 무시
#   · HARN-11(미탐): 타 세션이 **done 처리했으나 아직 머지 안 된** 태스크가 어디에도 안 보임
#
# 왜 안 보이는가: done 처리 시 원격 claim은 release되어 대장에서 사라지고, 트렁크의 백로그
# 사본은 그 브랜치가 머지되기 전까지 여전히 todo다. 즉 **claim 대장·로컬 백로그 양쪽 모두
# '가용'** 으로 보인다 — `next`가 이미 끝난 일을 최우선으로 추천한다.
#
# 사고 경위(2026-07-29 근접사고): /drive가 S3-09를 1순위로 계산해 claim까지 진행했으나, 타
# 세션이 이미 720문 검수를 마치고 done 처리한 상태였다(브랜치 미머지). 후속 태스크 notes의
# 감사 결과 인용을 우연히 보고 발견 — 중복 구현 직전 회피.
#
# 비용: ref 53개 × 태스크 N건을 `git cat-file --batch` **단일 프로세스**로 조회한다
# (실측 12ms). `next`처럼 자주 도는 경로에도 붙일 수 있는 이유다.


@dataclass
class DoneElsewhere:
    """어떤 브랜치가 이 태스크를 done으로 들고 있는가 (미머지 완료분)."""

    task_id: str
    ref: str
    branch: str


def scan_remote_done(
    root: Path,
    task_ids: Sequence[str],
    *,
    fetch: bool = False,
    max_refs: int = SCAN_MAX_REFS,
) -> tuple[dict[str, list[DoneElsewhere]], str]:
    """원격 브랜치 사본에서 `status: done`인 태스크를 찾는다 → {task_id: [DoneElsewhere]}.

    `fetch=False`(기본)는 **이미 있는 remote-tracking ref만** 본다 — 네트워크 0.
    `next`처럼 자주 도는 경로용이며, 그만큼 stale할 수 있다(마지막 fetch 시점 기준).
    `start`처럼 되돌리기 비싼 확정 지점은 `fetch=True`로 최신 상태를 본다.

    제외 규칙(기존 스캔과 동형):
        · 트렁크 ref는 제외 — 트렁크가 done이면 로컬 백로그도 done이라 애초에 후보가 아니다.
        · 파일이 없는 브랜치(태스크 신설 이전 시점)는 조용히 건너뛴다.

    두 번째 반환값은 status(`ok`/`offline`/`error`)다. `ok`가 아니면 **판정 불가**이며,
    빈 결과를 '완료분 없음'으로 읽어서는 안 된다(측정 실패와 통과는 같은 색이면 안 된다).
    """
    if not task_ids:
        return {}, "ok"
    if not has_remote(root):
        return {}, "offline"
    try:
        if fetch:
            fetched = _git(
                root,
                "fetch",
                "--quiet",
                "--prune",
                "origin",
                "+refs/heads/*:refs/remotes/origin/*",
                timeout=SCAN_FETCH_TIMEOUT,
            )
            if fetched.returncode != 0:
                return {}, _classify_failure(fetched.stderr)
        listing = _git(
            root,
            "for-each-ref",
            "--format=%(refname)",
            "refs/remotes/origin",
        )
        if listing.returncode != 0:
            return {}, _classify_failure(listing.stderr)
        refs = [
            r.strip()
            for r in listing.stdout.splitlines()
            if r.strip() and not r.strip().endswith("/HEAD")
        ][:max_refs]
        trunk_ref, _ = _resolve_trunk_ref(root)
        refs = [r for r in refs if r != trunk_ref]
        if not refs:
            return {}, "ok"

        # (ref, task) 전 조합을 한 프로세스로 — 개별 `git show` N×M회를 피한다.
        pairs = [(ref, tid) for ref in refs for tid in task_ids]
        request = "".join(f"{ref}:backlog/tasks/{tid}.yaml\n" for ref, tid in pairs)
        batch = _git(root, "cat-file", "--batch", input_text=request, timeout=SCAN_FETCH_TIMEOUT)
        if batch.returncode != 0:
            return {}, _classify_failure(batch.stderr)

        found: dict[str, list[DoneElsewhere]] = {}
        for (ref, task_id), blob in zip(pairs, _iter_batch_blobs(batch.stdout), strict=False):
            if blob is None or _top_level_field(blob, "status") != "done":
                continue
            branch = ref[len(REMOTE_REF_PREFIX) :] if ref.startswith(REMOTE_REF_PREFIX) else ref
            found.setdefault(task_id, []).append(DoneElsewhere(task_id, ref, branch))
        return found, "ok"
    except subprocess.TimeoutExpired:
        return {}, "offline"
    except Exception as exc:  # pragma: no cover - 환경 의존
        # 침묵 실패 금지 — 예외 타입명을 남긴다 (CLAUDE.md AI·신뢰)
        return {}, f"error:{type(exc).__name__}"


# ── 원격 브랜치 backlog/tasks/ 파일명 스캔 (HARN-15) ──────────────────────────
#
# HARN-10 가드(`cmd_add`의 번호 충돌 검사)의 3회차 결함 교정이다. 기존 `_taken_id_numbers`는
# ①로컬 백로그 ②원격 claim 대장(harness-claims 브랜치, in_progress만 기록)만 본다. 그런데
# "다른 브랜치에 이미 backlog/tasks/<ID>.yaml로 **등재만 되고 아직 claim(in_progress)되지
# 않은** 번호"는 claim 대장에 실리지 않으므로 구조적으로 안 보인다 — OPS-17·OPS-18이 main과
# 미머지 브랜치에 각각 다른 슬러그로 중복 등재된 사고(2026-08-03)가 정확히 이 맹점이다.
#
# scan_remote_done과 원칙을 공유한다: `fetch=False`(기본)는 **이미 있는 remote-tracking
# ref만** 본다 — 네트워크 비용 없음. cmd_add는 next처럼 자주 도는 경로는 아니지만, 그래도
# 사람이 대화형으로 호출하는 명령이 매번 원격 fetch(초 단위)로 지연되는 것은 바람직하지
# 않다 — 이미 세션 시작·next 등에서 최신화된 remote-tracking ref를 재사용한다.


@dataclass(frozen=True)
class RemoteTaskFile:
    """원격 브랜치 사본의 backlog/tasks/ 아래에서 발견한 태스크 파일 1건."""

    task_id: str  # 파일명에서 .yaml 을 뗀 값 = 그 브랜치가 실제로 쓰는 full task id
    ref: str  # refs/remotes/origin/<branch>
    branch: str  # <branch>


def read_remote_task_texts(
    root: Path,
    files: "list[RemoteTaskFile]",
    *,
    skip: "set[str] | None" = None,
    limit: int = 300,
) -> tuple[dict[str, str], dict[str, str], str]:
    """원격 브랜치 사본의 태스크 YAML **본문**을 읽는다 (HARN-51).

    반환은 `({task_id: 원문}, {task_id: branch}, status)`.

    `scan_remote_task_files`는 *파일명*만 준다 — 번호 충돌 판정에는 그것으로 충분하지만
    **의미 중복** 판정에는 제목·acceptance·notes 본문이 있어야 한다.

    **`skip`을 읽기 *앞*에서 적용한다** — 로컬 백로그에 이미 있는 ID의 원격 사본은
    같은 태스크의 다른 사본이지 의미 중복 후보가 아니므로 읽을 이유가 없다. 이 필터가
    없으면 실측상 원격 고유 ID 595건을 전부 읽어 상한(300)에 걸리고, 정상 상태에서
    매번 '판정 불가'가 떠 경고가 소음이 된다 — 필터를 넣으면 실제 읽기는 110건이다.

    읽기는 `git cat-file --batch` **1회 프로세스**로 끝낸다(브랜치당·파일당 `git show`를
    돌리면 수백 개 프로세스가 뜬다). `scan_remote_done`이 이미 쓰는 패턴과 동형이다.

    **네트워크 0** — 이미 있는 remote-tracking ref만 읽는다(`scan_remote_task_files`의
    `fetch=False` 계약 승계). 같은 task_id가 여러 브랜치에 있으면 처음 것만 남긴다.

    status가 `ok`가 아니면 **판정 불가**다 — 빈 결과를 '중복 없음'으로 읽으면 안 된다.
    """
    skip = skip or set()
    wanted: dict[str, RemoteTaskFile] = {}
    for item in files:
        if item.task_id in skip or item.task_id in wanted:
            continue
        wanted[item.task_id] = item
        if len(wanted) >= limit:
            break
    truncated = len({f.task_id for f in files} - skip) > len(wanted)
    if not wanted:
        return {}, {}, "truncated" if truncated else "ok"

    specs = [f"{item.ref}:backlog/tasks/{tid}.yaml" for tid, item in wanted.items()]
    try:
        out = _git(root, "cat-file", "--batch", input_text="\n".join(specs) + "\n", timeout=60)
    except Exception as exc:  # pragma: no cover - 환경 의존
        return {}, {}, f"error:{type(exc).__name__}"
    if out.returncode != 0:
        return {}, {}, _classify_failure(out.stderr or "")

    texts: dict[str, str] = {}
    branches: dict[str, str] = {}
    # 파싱은 `_iter_batch_blobs`에 맡긴다 — `<size>`가 **문자 수가 아니라 바이트 수**라는
    # 함정을 이미 다루고 있다(2026-07-29 실측으로 밝혀진 것). 여기서 다시 구현했다가
    # 정확히 같은 함정에 빠졌었다: 한국어 본문에서 오프셋이 밀려 3건 요청에 1건만,
    # 그것도 다음 blob의 sha가 섞인 채 돌아오면서 status는 ok였다(PR #947 리뷰가 포착).
    blobs = _iter_batch_blobs(out.stdout or "")
    for (tid, item), blob in zip(wanted.items(), blobs, strict=False):
        if blob is None:
            continue  # missing — 그 브랜치에 그 파일이 없다(경합 중 삭제 등)
        texts[tid] = blob
        branches[tid] = item.branch
    return texts, branches, "truncated" if truncated else "ok"


def scan_remote_task_files(
    root: Path, *, fetch: bool = False, max_refs: int = SCAN_MAX_REFS
) -> tuple[list[RemoteTaskFile], str]:
    """원격 브랜치들의 `backlog/tasks/*.yaml` 파일명 전부를 스캔한다 (HARN-15).

    `cmd_add`의 번호 충돌 가드가 "등재만 되고 아직 claim되지 않은 원격 번호"까지
    보게 하는 것이 목적이다 — 원격 claim 대장은 in_progress 상태만 기록하므로,
    등재만 하고 아직 손대지 않은 태스크 파일은 그 대장에 원천적으로 안 잡힌다.

    `scan_remote_done`(cat-file --batch로 *알고 있는* task_id들의 파일 하나씩을 조회)과
    달리, 여기서는 애초에 어떤 파일이 있는지 자체를 몰라 나열해야 한다 — 그래서
    `git ls-tree`로 브랜치별 backlog/tasks/ 디렉터리를 직접 나열한다
    (`scan_remote_in_progress`가 이미 쓰는 "브랜치당 git 프로세스 1회" 패턴과 동형).

    `fetch=False`(기본)는 **이미 있는 remote-tracking ref만** 본다 — 네트워크 0.
    `fetch=True`는 최신 상태가 필요한 호출부(테스트 등)용.

    트렁크 ref를 특별 취급하지 않는다(스킵하지 않음) — 어차피 로컬 백로그가 이미
    트렁크 사본을 기준으로 로드돼 있으므로, 트렁크 브랜치가 여기서도 잡혀 중복
    판정되는 것은 무해하다(호출부가 "같은 full ID면 충돌 아님" 규칙으로 걸러낸다).

    두 번째 반환값은 status(`ok`/`offline`/`error`)다. `ok`가 아니면 **판정 불가**이며,
    빈 결과를 '없음'으로 읽으면 안 된다(측정 실패와 통과는 같은 색이면 안 된다).
    """
    if not has_remote(root):
        return [], "offline"
    try:
        if fetch:
            fetched = _git(
                root,
                "fetch",
                "--quiet",
                "--prune",
                "origin",
                "+refs/heads/*:refs/remotes/origin/*",
                timeout=SCAN_FETCH_TIMEOUT,
            )
            if fetched.returncode != 0:
                return [], _classify_failure(fetched.stderr)
        listing = _git(
            root,
            "for-each-ref",
            "--format=%(refname)",
            "refs/remotes/origin",
        )
        if listing.returncode != 0:
            return [], _classify_failure(listing.stderr)
        refs = [
            r.strip()
            for r in listing.stdout.splitlines()
            if r.strip() and not r.strip().endswith("/HEAD")
        ][:max_refs]

        found: list[RemoteTaskFile] = []
        for ref in refs:
            # <ref>:backlog/tasks 를 트리 자체로 지정 — 나오는 이름엔 경로 접두가 안
            # 붙는다(_trunk_task_status가 쓰는 <ref>:<path> blob 조회와 동형 문법).
            tree = _git(root, "ls-tree", "--name-only", f"{ref}:backlog/tasks", timeout=10)
            if tree.returncode != 0:
                continue  # backlog/tasks/ 자체가 없는 브랜치(구세대 등) — 조용히 건너뜀
            branch = ref[len(REMOTE_REF_PREFIX) :] if ref.startswith(REMOTE_REF_PREFIX) else ref
            for line in tree.stdout.splitlines():
                name = line.strip()
                if not name.endswith(".yaml"):
                    continue
                found.append(RemoteTaskFile(task_id=name[: -len(".yaml")], ref=ref, branch=branch))
        return found, "ok"
    except subprocess.TimeoutExpired:
        return [], "offline"
    except Exception as exc:  # pragma: no cover - 환경 의존
        # 침묵 실패 금지 — 예외 타입명을 남긴다 (CLAUDE.md AI·신뢰)
        return [], f"error:{type(exc).__name__}"


# ── 등재 가시성 고지 (HARN-43) ─────────────────────────────────────────────
#
# **이것은 탐지가 아니라 고지다.** 미push 브랜치를 실제로 관측하는 수단은 없다 —
# 그 브랜치는 이 클론의 remote-tracking ref에도, `harness-claims` 대장에도, 원격
# 브랜치 파일명 스캔에도 나타나지 않는다. 즉 `cmd_add`의 번호 가드가 통과했다는 것은
# "충돌이 없다"가 아니라 "가드가 볼 수 있는 범위 안에는 없다"는 뜻이다.
#
# 근거(HARN-38 실측 2026-08-31): 가드의 관측 표면 3종을 전수 호출해 36브랜치·11,975
# 파일을 훑었으나 충돌 상대 브랜치는 0건 관측됐다 — 그 브랜치가 push된 적이 없었기
# 때문이다(GitHub API도 해당 커밋을 `No commit found`로 응답). 3출처 모두 `status=ok`
# 였으므로 조회 실패가 아니라 **관측 범위 밖**이었다.
#
# 같은 병목이 그날 5회 관측됐고(태스크 ID·게이트 ID·문서 버전 ×2·중복 작업), 가드가
# 있는 축에서는 CLI가 5번 다 실거부했지만 가드가 없는 축에서는 git 충돌·사람·운이
# 유일한 방어선이었다. 그래서 이 고지의 대상은 '번호'가 아니라 **"내가 지금 하는 일이
# 다른 세션에 보이지 않는다"는 사실 자체**다.
#
# 두 함수 모두 **네트워크를 타지 않는다**(로컬 ref·파일 mtime만 읽는다).
# `scan_remote_task_files`의 `fetch=False` 계약과 같은 원칙이다.


def branch_has_remote_ref(root: Path, branch: str) -> tuple[bool | None, str]:
    """`branch`의 remote-tracking ref가 **이 클론에** 있는가. 반환 `(판정, 상태)`.

    판정 `None` = **판정 불가**(상태가 이유) — 빈 결과를 '없음'으로 읽으면 안 된다.

    **정직한 한계 2가지**(고지 문안이 '추정'이라고 말하는 근거):
      · 이것은 *이 클론의 로컬 관점*이다. 다른 클론에서 push된 브랜치는 여기서 fetch
        하기 전까지 ref가 없어 '미push'로 보인다(거짓 경고). 고지일 뿐 차단이 아니므로
        허용되는 방향의 오차다.
      · 반대 방향은 오차가 없다 — `git push`가 remote-tracking ref를 갱신하므로,
        이 세션이 직접 push했다면 ref는 반드시 있다. 즉 **"보인다"는 신뢰할 수 있고
        "안 보인다"만 추정**이다.
    """
    if not branch or branch == "unknown":
        return None, "unknown-branch"
    if not has_remote(root):
        return None, "offline"
    try:
        probe = _git(
            root, "rev-parse", "--verify", "--quiet", f"{REMOTE_REF_PREFIX}{branch}", timeout=10
        )
    except Exception as exc:  # pragma: no cover - 환경 의존
        # 침묵 실패 금지 — 예외 타입명을 남긴다 (CLAUDE.md AI·신뢰)
        return None, f"error:{type(exc).__name__}"
    # rev-parse --verify --quiet: 존재하면 0, 없으면 1(무출력). 그 외는 판정 불가.
    if probe.returncode == 0:
        return True, "ok"
    if probe.returncode == 1:
        return False, "ok"
    return None, _classify_failure(probe.stderr or "")


def remote_refs_age_seconds(root: Path) -> tuple[float | None, str]:
    """원격 ref 스냅샷의 나이(초) — 네트워크 0. 반환 `(초, 상태)`.

    `None` = 판정 불가 → 호출부는 **침묵한다**(추측 출력 금지).

    **왜 `FETCH_HEAD` 하나로는 안 되는가**(2026-08-31 테스트가 잡은 결함): 갓 클론한
    저장소에는 `FETCH_HEAD`가 없다. 그것을 '오래됨'으로 읽으면 *가장 신선한* 상태인
    클론 직후에 고지가 항상 뜨고, 그러면 이 기능은 보호가 아니라 소음이 된다.
    그래서 **원격 ref가 마지막으로 갱신된 흔적 중 가장 최근 것**을 본다:
      · `FETCH_HEAD`         — 마지막 `git fetch`/`git pull` (**worktree별**)
      · `packed-refs`        — 클론 시점(및 gc·pack 갱신) (**공용**)
      · `refs/remotes/origin`— 개별 ref 파일이 풀려 있는 경우의 갱신 (**공용**)
    셋 다 없으면 판정 불가다 — 없는 것을 '오래됐다'로 접지 않는다.

    **linked worktree에서 두 디렉터리를 나눠 보는 이유**(Codex P2 · PR #940 실측): 이
    저장소는 병렬 세션에 worktree를 의무화한다(`docs/standards/parallel_sessions.md`
    "1 세션 = 1 브랜치 = 1 worktree" · `scripts/new-session-worktree.sh`). 그런데
    linked worktree에서 `--git-dir`는 `.git/worktrees/<name>`을 가리키고 **공용 ref는
    거기 없다** — 실측: 갓 만든 worktree의 `--git-dir`에는 흔적 3종이 *전부* 부재해
    이 함수가 `no-ref-stamp`로 침묵했다. 즉 **보호가 필요한 바로 그 환경에서 무력**
    했다. 공용 흔적은 `--git-common-dir`에서, worktree 고유 `FETCH_HEAD`는 `--git-dir`
    에서 읽어 합친다(둘은 일반 클론에서 같은 경로로 수렴하므로 분기 없이 동작한다).

    왜 이 값을 고지하는가: 번호 가드의 세 번째 출처(`scan_remote_task_files`)는
    **이미 있는 remote-tracking ref만** 읽고 네트워크를 타지 않는다(의도된 비용
    트레이드오프). 그래서 그 ref가 낡았으면 가드는 *그 시점 이후 원격에 등재된 번호를
    구조적으로 보지 못한다*. 대가를 치를 때 사람에게 말하지 않는 것이 결함이므로
    경과 시간을 함께 띄운다 — `fetch=False` 기본값 자체는 바꾸지 않는다.
    """

    def _resolve(flag: str) -> Path | None:
        out = _git(root, "rev-parse", flag, timeout=10)
        if out.returncode != 0:
            return None
        raw = (out.stdout or "").strip()
        if not raw:
            return None
        path = Path(raw)
        return path if path.is_absolute() else root / path

    try:
        git_dir = _resolve("--git-dir")
        if git_dir is None:
            return None, "error:git-dir"
        # linked worktree면 공용 디렉터리가 다르다. 일반 클론에서는 같은 경로로 수렴.
        common_dir = _resolve("--git-common-dir") or git_dir
        candidates = (
            git_dir / "FETCH_HEAD",  # worktree별 fetch 기록
            common_dir / "FETCH_HEAD",  # 주 체크아웃에서의 fetch 기록
            common_dir / "packed-refs",  # 공용 — 클론 시점
            common_dir / "refs" / "remotes" / "origin",  # 공용 — 풀린 ref 갱신
        )
        stamps = [c.stat().st_mtime for c in candidates if c.exists()]
        if not stamps:
            return None, "no-ref-stamp"
        return max(0.0, time.time() - max(stamps)), "ok"
    except Exception as exc:  # pragma: no cover - 환경 의존
        return None, f"error:{type(exc).__name__}"


# ── 장기 미머지 브랜치 감지 (HARN-13) ──────────────────────────────────────
#
# HARN-11(미머지 done)이 다루는 축과 가깝지만 다른 신호다 — HARN-11은 "이 태스크,
# 어디선가 이미 끝났나"(status: done 여부)를 backlog 사본에서 읽는 반면, 이 스캔은
# 태스크 상태와 무관하게 "이 *브랜치*가 트렁크에 아직 안 흡수된 채 얼마나 오래
# 방치됐는가"를 커밋 그래프 자체(committerdate·ahead count)로 잰다. 2026-07-30
# 사고(claude/shadow-data-s3-pilot-nh5kbz 9일·40+커밋 고립)는 태스크 status와
# 무관하게 벌어졌다 — 텍스트 재발방지 규칙("머지 타이밍은 Kiki의 pr 지시 대기")이
# 2회 반복 무력화된 뒤에야 이 스캔을 코드로 대체한다(CLAUDE.md "시스템 실수 재발
# 시 재발방지대책은 규칙 텍스트가 아니라 코드·CI로 등재").
#
# HARN-08이 claim(in_progress) 판정에 "나이" 휴리스틱을 **의도적으로 빼둔 것**과
# 모순되지 않는다 — 그건 "아직 활성 세션인가"를 나이로 오판하지 않기 위한 결정이었고,
# 여기는 "사람에게 존재 자체를 알릴 가치가 있는가"를 판정한다. 전자는 자동 판정을
# 내리면 안 되는 축이고, 후자는 정보성 경고일 뿐 태스크 진행을 막지 않는다.

STALE_BRANCH_DEFAULT_DAYS = 3


@dataclass(frozen=True)
class StaleBranch:
    """N일 이상 트렁크에 흡수되지 않은 원격 브랜치 1건.

    status(HARN-13 잔여 — 2026-08-05 3분류 확장 · HARN-47 2026-08-31 4분류 ·
    HARN-78 2026-09-07 5분류):
      · "isolated"   — **PR로 노출된 적이 한 번도 없다**. 이 브랜치의 작업은 GitHub
                        어디에서도 보이지 않으므로 이 브리핑 줄이 유일한 존재 증거다.
                        진짜 고립이며 즉시 조치 대상. 기본값.
      · "pr_filed"   — 이 tip으로 PR이 열린 이력이 있다(`refs/pull/<N>/head` 일치)
                        **그리고** (a) GitHub API로 그 PR이 지금 열려 있음을 확인했거나
                        (b) 열림/닫힘을 확인할 수단(GITHUB_TOKEN/GH_TOKEN)이 없다.
                        (a)면 처분은 그 PR에서 이뤄진다 — evidence "PR #<N>". (b)면
                        상태를 모른다는 사실 자체가 evidence에 " (상태 미확인)"로
                        붙는다(모른다 ≠ 열려 있다 — CLAUDE.md "모른다 ≠ 아니다"의
                        3상태 원칙과 동형).
      · "pr_closed"  — (HARN-78) `pr_filed`였던 PR을 GitHub API로 대조했더니
                        **닫혔고 머지되지 않았다**. `isolated`와 행동 요구가 같다
                        (재작업 또는 폐기 판단) — PR이 있었다는 사실이 "처분 완료"를
                        뜻하지 않는다. evidence "PR #<N> 닫힘(미머지)".
      · "ported"     — 이 브랜치의 유용한 부분이 이미 별도 소형 PR로 trunk에
                        흡수된 흔적(커밋 메시지에 브랜치 세션 접미사 언급)이 있다.
                        원본은 정리 대상일 뿐 결정 대기가 아니다.
      · "active"     — 다른 세션이 지금 이 브랜치에서 태스크를 claim 중(원격
                        claim 맵에 존재). 방치가 아니라 진행 중인 정상 작업.

    isolated/pr_filed 분리 근거(HARN-47 실측 2026-08-31): 브리핑이 18건을 전부
    "Kiki 결정 필요"로 부르고 있었는데 실측하니 11건은 **이미 PR이 열려 있고 처분
    라벨(eos-rework/postpone/close/merge)까지 붙어 있었다**. 즉 경고의 61%가 이미
    결정된 것을 다시 결정하라고 요구하고 있었다 — CLAUDE.md가 금지하는 "상시 실패하는
    fail-open 보호"의 경고 습관화 형태다. 진짜 고립은 7건뿐이었고 그 7건이 11건의
    소음 속에 숨어 24일간 방치됐다.

    pr_closed 신설 근거(HARN-78 실측 2026-09-07): 위 분리가 "PR이 있으면 처분됐다"고
    가정했는데, `gates/deploy-environment-approval`(PR #967)·`whymath-curriculum-
    design-6eejrv`(PR #802)·`whymath-pedagogy-review-uqyg79`(PR #675) 3건은 PR이
    **닫혔지만 머지되지 않았다** — 즉 처분되지 않고 그대로 버려졌는데도 `pr_filed`로
    분류돼 "결정 불요"처럼 보였다. `refs/pull/<N>/head`는 닫힌 PR에도 남으므로
    오프라인 git만으로는 이 구분이 원천적으로 불가능하다(아래 열림/닫힘 판정 참조).

    evidence: ported면 근거 커밋(짧은 sha + 제목) · pr_filed면 "PR #<N>"(상태 확인
    시) 또는 "PR #<N> (상태 미확인)"(미확인 시) · pr_closed면 "PR #<N> 닫힘(미머지)"
    · 그 외 "".
    """

    branch: str
    ref: str
    last_commit_at: datetime
    age_days: float
    ahead: int
    status: str = "unresolved"
    evidence: str = ""
    port_scan_error: str = ""
    """포팅 판정 **불가** 사유(예외 타입명 포함) — 분모(브랜치 코드 파일) 산출이 실패했다.

    이 값이 있으면 ported로 분류되지 않는다. 판정을 못 한 것과 근거가 없는 것은 다르므로
    브리핑이 그 사실을 따로 말한다 — 조용히 넘기면 "검사했는데 근거 없음"으로 읽힌다.
    """
    partial_port: str = ""
    """부분 착지 단서 — 근거 커밋이 이 브랜치의 코드 파일을 *일부만* 옮겼을 때 채워진다.

    "N/M 파일" 형태. 이 값이 있으면 status는 **ported가 아니다**(잔여 고유 코드가 있으므로
    '결정 불요'로 부를 수 없다) — 대신 브리핑이 이 단서를 함께 보여 사람이 나머지를 볼 수
    있게 한다. 흡수 흔적을 버리지도, 흡수됐다고 단정하지도 않는 중간 상태다.
    """
    disposal_labels: tuple[str, ...] = ()
    """(HARN-93 ②) `pr_filed`인 이 PR에 붙은 처분 라벨(`DISPOSAL_LABELS`) 중 실재분.

    `status == "pr_filed"`이고 GITHUB_TOKEN/GH_TOKEN이 있을 때만 채워진다 — 라벨은
    "언젠가 닫는다/미룬다"는 결정이고 `age_days`는 그 결정 이후로도 계속 흐른 방치
    기간의 근사치다(정확한 라벨 부착 시각이 아니라 최종 커밋 기준 — HARN-93 acceptance
    ①이 "8일간 갱신 0"을 이 근사로 실측했다). 빈 튜플은 "라벨 없음"과 "조회 안 함/실패"
    양쪽을 뜻할 수 있으므로, 후자는 `StaleBranchScanResult.pr_label_lookup_ok`로 가른다.
    """


# 근거 needle 길이 하한 — 짧은 문자열은 우연 매칭 생성기다.
_MIN_EVIDENCE_NEEDLE = 12

# "원장" 최상위 경로 — 이것만 고친 커밋은 브랜치를 *언급*했을 뿐 *흡수*하지 않았다.
_LEDGER_ONLY_TOPS = frozenset(
    {"MEMORY.md", "backlog", "docs", ".github", "ROADMAP.md", "README.md", "CLAUDE.md"}
)

# git log 레코드 구분자(RS) — 커밋 제목에 개행이 없다는 가정에 의존하지 않기 위함.
_EVIDENCE_RECORD_SEP = "\x1e"


# PR ref 조회 타임아웃 — ls-remote 1회. 스캔 전체가 이것 하나로 멈추면 안 된다.
_PR_REF_TIMEOUT = 20


def _fetch_pr_head_shas(root: Path) -> tuple[dict[str, int] | None, str]:
    """원격의 `refs/pull/<N>/head`를 sha → PR 번호로 읽는다.

    반환: `(매핑, 실패사유)`. 성공이면 `(dict, "")`, 실패면 `(None, "<예외타입>: <상세>")`.
    실패 사유에 **예외 타입명을 반드시 담는다** — 무타입 경고는 타임아웃·git 미설치·
    권한 오류를 운영자에게 같은 글자로 보이게 만든다(CLAUDE.md 침묵 실패 금지).

    **왜 API가 아니라 git인가**: 이 스캔은 Kiki의 Windows 머신 SessionStart 훅과 CI
    양쪽에서 돈다. GitHub 토큰·`gh` CLI·네트워크 API 권한을 전제하면 그 중 하나만
    없어도 판정이 통째로 사라진다. `refs/pull/*/head`는 **인증 없는 평범한 git
    ls-remote로 읽힌다**(2026-08-31 실측: 토큰 0으로 935건 열람). 판정을 외부 관측
    인프라에 의존시키지 않는다는 CLAUDE.md 이중 회계 원칙과 같은 방향이다.

    **실패는 0건이 아니다**: 조회가 실패하면 `None`을 돌려준다 — 호출부는 이것을
    "PR 이력 없음"(= 고립)으로 읽으면 **안 된다**. 인프라가 죽었을 때 11건이 통째로
    "고립"으로 승격되면 그건 측정 실패가 경보로 위장된 것이다.

    ⚠ 정직한 한계 — **이 함수 자체는 열림/닫힘을 구분하지 못한다.** `refs/pull/<N>/head`는
    닫힌 PR에도 남는다. `refs/pull/<N>/merge`가 열린 PR에만 생긴다는 통설로 이를
    가르려다 실측에서 폐기했다(2026-08-31: 열린 PR 14건 중 merge ref 보유는 8건뿐이고,
    이미 머지된 #922도 head만 남아 있었다 — 성공/실패 양쪽에서 같은 값을 내는 검사는
    검증이 아니라 위장이다. CLAUDE.md "변별력 없는 검증 스텝 금지"). 그래서 이 함수는
    오프라인 git만으로 "PR로 노출된 적이 있는가"라는 **답할 수 있는 질문만** 답한다.

    (HARN-78 갱신) 열림/닫힘 자체는 이제 `_fetch_pr_states`가 **GitHub API로**
    가른다 — 다만 그건 `GITHUB_TOKEN`/`GH_TOKEN`이 있을 때만 가능한 별도 축이다.
    이 함수는 여전히 토큰 없이 도는 1차 스캔이고, `_fetch_pr_states`는 그 결과 중
    `pr_filed` 후보만 골라 선택적으로 정밀화하는 2차 스캔이다.
    """
    try:
        result = _git(root, "ls-remote", "origin", "refs/pull/*/head", timeout=_PR_REF_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, f"TimeoutExpired: PR ref 조회 {_PR_REF_TIMEOUT}초 초과"
    except Exception as exc:  # noqa: BLE001 - 환경 의존(FileNotFoundError·OSError 등)
        # 침묵 실패 금지 — 예외 타입명을 반드시 남긴다(CLAUDE.md AI·신뢰). 타입명이 없으면
        # 타임아웃·git 미설치·파일시스템 오류가 운영자에게 전부 같은 글자로 보인다.
        return None, f"{type(exc).__name__}: {exc}"
    if result.returncode != 0:
        return None, f"git ls-remote 비0 종료({result.returncode}): {result.stderr.strip()}"
    mapping: dict[str, int] = {}
    for line in result.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        sha, ref = sha.strip(), ref.strip()
        if not sha or not ref.startswith("refs/pull/") or not ref.endswith("/head"):
            continue
        number = ref[len("refs/pull/") : -len("/head")]
        if not number.isdigit():
            continue
        # 같은 sha로 PR이 여러 번 열렸으면 가장 최신(큰 번호)을 남긴다.
        prev = mapping.get(sha)
        if prev is None or int(number) > prev:
            mapping[sha] = int(number)
    return mapping, ""


# GitHub API PR 상태 조회 타임아웃 — 번호당 1회.
_PR_STATE_TIMEOUT = 20

# 스캔 전체 예산(초) — 후보 수와 무관하게 SessionStart 훅·CI 잡을 무한정 묶어 두지
# 않는다. `pr_filed` 후보가 많으면 번호당 순차 curl 호출이 누적돼 총 소요가
# 무제한으로 늘어날 수 있다(Codex 리뷰 지적, PR #1043). 예산을 넘으면 남은 조회를
# 건너뛰고 실패로 낸다 — 이미 이 함수는 단일 PR 조회 실패에도 전체를 실패로 내는
# 전부-또는-전무 계약이므로, 예산 초과도 같은 모양의 실패일 뿐 새 분기를 만들지 않는다.
_PR_STATE_SCAN_BUDGET_SECONDS = 60.0


def _attribute_api_failure(data: object) -> str | None:
    """API 응답이 *정책 거부*면 그 사유를 귀속해 돌려준다 — 아니면 `None`(HARN-04).

    왜 필요한가: 프록시가 막은 응답도 `{"message": ...}` 모양이라 `"state" not in data`
    분기에 함께 떨어지고, 거기 붙은 문구는 **"응답 형식 이상"**이었다. 형식이 이상한 게
    아니라 정책이 막은 것이며, 둘은 처방이 완전히 다르다 — 전자는 코드 결함이고 후자는
    **이 세션에서는 고칠 수 없는 환경 조건**이다. 그 구분이 없어서 같은 조사가 세 세션
    반복됐다(2026-09-11·09-12 ×2 비재현 기록이 이 태스크 acceptance에 쌓여 있다).

    실측(2026-09-12 · 이 컨테이너)이 확정한 것은 **이름을 고쳐도 안 뚫린다**는 사실이다.
    두 이름을 각각 `curl -w '%{http_code} %{url_effective}'`로 재 본 결과(원문 수치는
    `HARN-04` acceptance에 있다 — 여기에 옛 owner 리터럴을 적으면 정본 참조 가드가
    실행 표면 위반으로 잡는다):

      이관 *전* 이름 → 301 → 숫자 ID 경로   → 403 (프록시가 숫자 경로를 막는다)
      **정본** 이름  → 리다이렉트 없음      → 403 (이 세션 스코프에 저장소가 없다)

    그러므로 이 함수는 해법을 권하지 않고 **무엇이 막았는지만** 정확히 말한다. 여기서
    "origin을 정본으로 바꾸라"고 안내하면 실패 문구만 바뀌고 결과는 그대로다 — 이 태스크
    acceptance ④가 이름 붙인 함정("오류 문구가 바뀌었다는 해결의 증거가 아니다")이다.
    """
    if not isinstance(data, dict):
        return None
    message = data.get("message")
    if not isinstance(message, str):
        return None
    if "Numeric-ID repository paths" in message:
        return (
            "ProxyNumericPathBlocked: 저장소 이관으로 요청이 숫자 ID 경로로 301 리다이렉트되고 "
            "에이전트 프록시가 그 경로를 막는다. **정본 이름으로 바꿔도 뚫리지 않는다**"
            "(실측 2026-09-12: 정본 이름은 리다이렉트 없이 '세션 미활성' 403) — "
            "정본 이름을 스코프에 포함하는 세션에서만 조회된다"
        )
    if "not enabled for this session" in message:
        return (
            "SessionScopeBlocked: 이 세션 스코프에 이 저장소가 없다 — "
            "세션 시작 시 소스로 부착된 저장소만 API로 조회된다"
        )
    return None


# 에이전트 프록시 CA (있을 때만 사용) — 모듈 상수여야 거버넌스 테스트가
# `monkeypatch.setattr(mod, "_CA_PATH", ...)`로 갈아끼울 수 있다.
_CA_PATH = "/root/.ccr/ca-bundle.crt"


def _auth_args() -> list[str]:
    """토큰이 있으면 `["-H", "Authorization: Bearer <token>"]`, 없으면 `[]`.

    `scripts/ops/pr_merge_readiness.py`·`flow_health.py`·`pr_delivery_audit.py`와
    동일한 패턴을 그대로 따른다(이 저장소에서 이미 3곳이 각자 들고 있는 관용구 —
    공유 모듈로 뽑는 것은 이 4번째 사용만으로는 과공학이라 보류).

    **왜 필수인가** (2026-09-01 main red 실측): GitHub API의 **미인증** 한도는
    IP당 60req/h인데, 공유 러너/프록시 환경에서는 실질적으로 상시 소진 상태다.
    그래서 `_fetch_pr_states`는 토큰이 없으면 이 함수를 호출하는 지점까지도
    가지 않는다(호출부의 `if not token: return None, ...` 조기 반환) — 이 함수
    자체는 그 계약과 무관하게, 거버넌스 테스트가 요구하는 독립된 헬퍼로 존재한다.
    """
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    return ["-H", f"Authorization: Bearer {token}"] if token else []


def _ca_args() -> list[str]:
    """프록시 CA를 쓸 수 있으면 `["--cacert", <경로>]`, 아니면 `[]`.

    `scripts/ops/flow_health.py`·`pr_merge_readiness.py`·`pr_delivery_audit.py`와
    동일한 패턴을 그대로 따른다(이 저장소에서 이미 3곳이 각자 들고 있는 관용구 —
    공유 모듈로 뽑는 것은 이 4번째 사용만으로는 과공학이라 보류).

    **왜 존재 검사를 예외로 감싸는가** (2026-09-01 main red 실측): `Path.exists()`는
    실패를 False로 돌려주지 **않는다** — `pathlib._IGNORED_ERRNOS`는
    `(ENOENT, ENOTDIR, EBADF, ELOOP)`뿐이라 **EACCES는 전파된다**. 러너의 `runner`
    유저는 `/root`(mode 700)를 통과할 수 없어 검사 자체가 `PermissionError`로 죽는다.
    """
    try:
        with open(_CA_PATH, "rb"):
            return ["--cacert", _CA_PATH]
    except OSError:
        return []


def _fetch_pr_states(
    root: Path, pr_numbers: Sequence[int]
) -> tuple[dict[int, tuple[str, bool]] | None, str]:
    """주어진 PR 번호들의 `(state, merged)` — **GitHub API**, `GITHUB_TOKEN`/`GH_TOKEN` 필요.

    반환: `(번호 → (state, merged) 매핑, 실패사유)`. 성공이면 `(dict, "")`.
    실패(토큰 없음 포함)면 `(None, "<사유>")` — **빈 dict가 아니다**. `pr_numbers`가
    비었으면 조회할 것이 없으므로 `({}, "")`을 즉시 돌려준다(호출부가 "빈 입력은
    성공"으로 처리할 수 있게 — 조회 시도 자체가 없었던 것과 API가 실패한 것은 다르다).

    `_fetch_pr_head_shas`(오프라인 git)가 "PR로 노출된 적이 있는가"만 답하는 것과
    달리, 이 함수는 "그 PR이 지금 열려 있는가·머지됐는가"를 답한다 — 그 답은
    오프라인 git으로는 원천적으로 못 낸다(위 `_fetch_pr_head_shas` 정직한 한계
    참조). 그래서 이 함수만 GitHub API를 쓰고, 토큰이 없으면 **호출 자체를 하지
    않는다**(미인증 요청은 IP당 60req/h로 상시 소진 상태 — CLAUDE.md 2026-09-01
    main red 실측과 같은 함정).

    토큰이 있어도 이 조회는 **선택적 정밀화**다 — 실패해도 `pr_filed` 1차 분류
    자체는 이미 서 있으므로(오프라인 git), 브리핑은 "상태 미확인"으로 낮춰 계속
    보여준다(측정 실패를 침묵으로 덮지 않는다).
    """
    if not pr_numbers:
        return {}, ""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return None, "NoTokenError: GITHUB_TOKEN/GH_TOKEN 미설정 — 열림/닫힘 조회 생략"
    try:
        remote = _git(root, "remote", "get-url", "origin", timeout=15)
    except subprocess.TimeoutExpired:
        return None, "TimeoutExpired: origin 조회 타임아웃"
    except Exception as exc:  # noqa: BLE001 - 환경 의존
        return None, f"{type(exc).__name__}: {exc}"
    if remote.returncode != 0:
        return None, f"git remote get-url 비0 종료({remote.returncode}): {remote.stderr.strip()}"
    match = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", remote.stdout.strip())
    if not match:
        return None, f"RemoteParseError: origin이 GitHub이 아니다({remote.stdout.strip()[:60]})"
    owner, repo = match.group(1), match.group(2)

    states: dict[int, tuple[str, bool]] = {}
    scan_started = time.monotonic()
    for number in sorted(set(pr_numbers)):
        if time.monotonic() - scan_started > _PR_STATE_SCAN_BUDGET_SECONDS:
            return None, (
                f"ScanBudgetExceededError: {_PR_STATE_SCAN_BUDGET_SECONDS:.0f}초 예산 초과 — "
                f"{len(states)}/{len(pr_numbers)}건만 조회 후 중단"
            )
        cmd = [
            "curl",
            "-sS",
            "-L",  # 이관 리다이렉트 추종 — 301 본문을 데이터로 오독하지 않기 위해
            "--max-time",
            str(_PR_STATE_TIMEOUT),
            *_ca_args(),
            *_auth_args(),
            "-H",
            "Accept: application/vnd.github+json",
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}",
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",  # HARN-19 — 로케일(cp949) 디코드 금지
                errors="replace",
                timeout=_PR_STATE_TIMEOUT + 10,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return None, f"{type(exc).__name__}: {exc} (PR #{number} 조회 중)"
        if proc.returncode != 0:
            return None, (
                f"CurlExitError({proc.returncode}): {proc.stderr.strip()[:160]} (PR #{number})"
            )
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            return None, f"JSONDecodeError: {exc} — 본문 {proc.stdout[:120]!r} (PR #{number})"
        if not isinstance(data, dict) or "state" not in data:
            blocked = _attribute_api_failure(data)
            if blocked:
                return None, f"{blocked} (PR #{number})"
            return None, f"APIError: PR #{number} 응답 형식 이상 — {str(data)[:120]}"
        states[number] = (str(data["state"]), bool(data.get("merged", False)))
    return states, ""


# HARN-42가 부착하는 처분 라벨 4종. 이 라벨은 "언젠가 닫는다/미룬다"는 *결정*인데
# 만료·재확인 지점이 없다(CLAUDE.md 2026-08-03 "만료 없는 유예·제외 금지"). HARN-93 ②는
# 이 결정을 `branches` 브리핑에서 사람 눈에 보이게 하는 축이다 — 결정 자체를 바꾸지 않는다.
DISPOSAL_LABELS = frozenset({"eos-merge", "eos-rework", "eos-postpone", "eos-close"})


def _fetch_pr_labels(
    root: Path, pr_numbers: Sequence[int]
) -> tuple[dict[int, tuple[str, ...]] | None, str]:
    """주어진 PR 번호들의 라벨 이름 목록 — GitHub API, `GITHUB_TOKEN`/`GH_TOKEN` 필요(HARN-93).

    `_fetch_pr_states`와 같은 엔드포인트(`GET /pulls/{n}`)를 별도로 다시 부른다 — 한
    응답에 `state`·`labels`가 같이 들어 있지만, 기존 `_fetch_pr_states`의 반환 튜플
    모양(`(state, merged)`)을 바꾸면 그 계약을 봉인한 기존 테스트·호출부가 전부
    갈아엎여야 한다. 이 저장소는 같은 판단을 `_auth_args`/`_ca_args`에도 이미
    적용했다(4번째 사용만으로는 공유 추출이 과공학 — 각 파일이 자기 사본을 든다).
    대상이 10건 안팎(HARN-93 실측)이라 API 왕복이 갑절이 되어도 인증 한도(5000/h)에
    영향이 없다.

    반환·실패 계약은 `_fetch_pr_states`와 동형이다: 실패(토큰 없음 포함)는
    `(None, "<사유>")` — **빈 dict가 아니다**. 라벨이 하나도 없는 PR은 `{번호: ()}`로
    채워진다(조회 성공·라벨 없음과 조회 실패는 다른 사실 — CLAUDE.md "모른다 ≠ 아니다").
    """
    if not pr_numbers:
        return {}, ""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return None, "NoTokenError: GITHUB_TOKEN/GH_TOKEN 미설정 — 라벨 조회 생략"
    try:
        remote = _git(root, "remote", "get-url", "origin", timeout=15)
    except subprocess.TimeoutExpired:
        return None, "TimeoutExpired: origin 조회 타임아웃"
    except Exception as exc:  # noqa: BLE001 - 환경 의존
        return None, f"{type(exc).__name__}: {exc}"
    if remote.returncode != 0:
        return None, f"git remote get-url 비0 종료({remote.returncode}): {remote.stderr.strip()}"
    match = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", remote.stdout.strip())
    if not match:
        return None, f"RemoteParseError: origin이 GitHub이 아니다({remote.stdout.strip()[:60]})"
    owner, repo = match.group(1), match.group(2)

    labels: dict[int, tuple[str, ...]] = {}
    scan_started = time.monotonic()
    for number in sorted(set(pr_numbers)):
        if time.monotonic() - scan_started > _PR_STATE_SCAN_BUDGET_SECONDS:
            return None, (
                f"ScanBudgetExceededError: {_PR_STATE_SCAN_BUDGET_SECONDS:.0f}초 예산 초과 — "
                f"{len(labels)}/{len(pr_numbers)}건만 조회 후 중단"
            )
        cmd = [
            "curl",
            "-sS",
            "-L",  # 이관 리다이렉트 추종 — 301 본문을 데이터로 오독하지 않기 위해
            "--max-time",
            str(_PR_STATE_TIMEOUT),
            *_ca_args(),
            *_auth_args(),
            "-H",
            "Accept: application/vnd.github+json",
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}",
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",  # HARN-19 — 로케일(cp949) 디코드 금지
                errors="replace",
                timeout=_PR_STATE_TIMEOUT + 10,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return None, f"{type(exc).__name__}: {exc} (PR #{number} 조회 중)"
        if proc.returncode != 0:
            return None, (
                f"CurlExitError({proc.returncode}): {proc.stderr.strip()[:160]} (PR #{number})"
            )
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            return None, f"JSONDecodeError: {exc} — 본문 {proc.stdout[:120]!r} (PR #{number})"
        if not isinstance(data, dict) or "labels" not in data:
            blocked = _attribute_api_failure(data)
            if blocked:
                return None, f"{blocked} (PR #{number})"
            return None, f"APIError: PR #{number} 응답 형식 이상 — {str(data)[:120]}"
        names = tuple(
            item["name"]
            for item in data.get("labels", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        )
        labels[number] = names
    return labels, ""


@dataclass(frozen=True)
class PortEvidence:
    """포팅 근거 판정 — 근거 커밋과 **그 커밋이 이 브랜치의 코드를 얼마나 옮겼는가**.

    `landed`/`total`이 이 클래스의 존재 이유다. 이전 구현은 "브랜치명을 인용하면서 원장 밖
    파일을 하나라도 건드린 커밋"을 흡수 근거로 받았는데, 그러면 **다른 파일을 건드린 커밋**이
    포팅 근거가 된다 — 실제로 `#770`은 7n9n72의 고립을 *실측·문서화*한 커밋인데 그 브랜치를
    "이미 포팅됨·결정 불요"로 만들었고, main 부재 15파일이 그 라벨 뒤에 숨었다(HARN-37 ①).
    """

    header: str
    landed: int
    total: int
    scan_error: str = ""
    """분모(브랜치 코드 파일) 산출 실패 사유 — 있으면 **포팅 여부를 판정하지 못했다**."""

    @property
    def is_full_port(self) -> bool:
        """브랜치 고유 코드가 전부 트렁크에 착지했는가 — 이때만 '결정 불요'다.

        분모 산출에 실패했으면(`scan_error`) 언제나 False다 — 판정 불가는 통과가 아니다.
        """
        if self.scan_error:
            return False
        return bool(self.header) and (self.total == 0 or self.landed == self.total)

    @property
    def is_partial(self) -> bool:
        return bool(self.header) and 0 < self.landed < self.total


def _branch_code_files(root: Path, trunk_ref: str, ref: str) -> tuple[frozenset[str] | None, str]:
    """브랜치가 트렁크 대비 건드린 **코드** 파일 집합(원장·문서 최상위 제외) + 실패 사유.

    포팅 판정의 **분모**다 — "이 브랜치가 트렁크에 남겨야 할 것"이 무엇인지.

    반환 `None`은 **판정 불가**이고 빈 집합과 다르다(#962 codex P1). 초판은 둘을 같은
    `frozenset()`으로 돌려줬는데, 그러면 호출부가 diff 실패를 "남길 코드가 없는 브랜치"로
    읽어 `0/0` 전건 착지 = ported로 판정한다 — 즉 **git이 잠깐 실패하면 이 PR이 막으려던
    구멍이 그대로 다시 열린다**(미검증 브랜치가 '삭제해도 안전'으로 표시). 미측정을 0으로
    바꾸지 않는다는 이 저장소의 규칙이 정확히 이 자리에 적용된다.

    실패 사유에는 **예외 타입명**을 담는다(무타입 경고 금지 — CLAUDE.md 침묵 실패 금지).
    """
    try:
        res = _git(root, "diff", "--name-only", f"{trunk_ref}...{ref}", timeout=30)
    except Exception as exc:  # pragma: no cover - 환경 의존
        return None, f"{type(exc).__name__}: {exc}"
    if res.returncode != 0:
        detail = (res.stderr or "").strip().splitlines()
        reason = detail[0] if detail else "no stderr"
        return None, f"git diff exit {res.returncode}: {reason[:120]}"
    files = {line.strip() for line in res.stdout.splitlines() if line.strip()}
    return frozenset(f for f in files if f.split("/", 1)[0] not in _LEDGER_ONLY_TOPS), ""


def _find_ported_evidence(
    root: Path, trunk_ref: str, branch: str, ref: str | None = None
) -> PortEvidence:
    """브랜치명을 trunk 커밋 로그에서 찾는다 — 코드를 실제로 옮긴 커밋만 "포팅됨" 근거.

    브랜치의 유용한 부분을 trunk에 흡수할 때 커밋 메시지가 브랜치명을 인용하는 패턴이
    반복 관측됐다(`merge: claude/whymath-curriculum-design-b7qav0 (PATH-02)` #706,
    `PATH-05: … 고아 브랜치 회수` #728의 본문 등). needle은 네임스페이스를 뗀 basename
    전체다 — 제목뿐 아니라 본문도 훑는다.

    ⚠ 여기서 가장 위험한 오류는 미탐이 아니라 **오탐**이다. 잘못된 "포팅됨" 강등은
    브리핑에서 "결정 불요"로 표시돼 실작업이 든 브랜치를 삭제 대상으로 만든다. 그래서
    두 겹으로 막는다:

      ① needle 길이 하한(12자) — 옛 구현은 `-([a-z0-9]{6})$` 6자 접미사를 needle로
         썼는데, 이건 세션 해시뿐 아니라 평범한 영단어도 잡았다(`…-metrics-writer`의
         "writer"가 무관한 커밋에 매칭돼 그 브랜치를 오강등한 것이 실측됐다). 동시에
         6자 접미사가 *없는* 브랜치(`claude/harn-14-…`, `worktree-agent-…`)는 아예
         시도조차 못 해 항구적 "미해결"이었다 — 좁으면서 동시에 헐거웠다.
      ② 원장 전용 커밋 배제 — `MEMORY.md`/`backlog`/`docs`만 고친 커밋은 버린다.
         *"이 브랜치들은 미해결이다"*라고 적은 판정 문서가 바로 그 브랜치를 "해결됨"
         으로 뒤집던 사고를 막는다(2026-08-11 실측: 오탐 5건이 전부 이 형태였고,
         `claude/whymath-solution-review-40xspg`는 미회수 S4-09를 안은 채 "포팅됨"으로
         분류돼 있었다).

    정직한 잔존 한계:
      · 순수 문서·백로그 PR로 정리된 브랜치는 미탐된다(→ unresolved로 남음). 과보고는
        사람이 훑으면 되고 과소보고는 사고가 되므로 **의도된 비대칭**이다.
      · trunk에 진짜 머지 커밋이 있으면 `--name-only`가 빈 목록을 내 원장 취급으로
        버려진다(미탐·안전 방향).
      · 코드 커밋이 다른 브랜치를 *충돌 상대*로 언급하는 경우는 텍스트로 구분 불가라
        통과한다 — 그래서 브리핑은 `ported` 항목에 근거 커밋을 항상 함께 노출한다.

    예외·비0 종료는 `""`로 안전 폴백한다(이 브랜치만 unresolved로 남고 전체 스캔은
    실패하지 않는다).
    """
    empty = PortEvidence("", 0, 0)
    needle = branch.split("/", 1)[-1]
    if len(needle) < _MIN_EVIDENCE_NEEDLE:
        return empty
    try:
        found = _git(
            root,
            "log",
            trunk_ref,
            f"--grep={needle}",
            "--fixed-strings",
            "--name-only",
            f"--format={_EVIDENCE_RECORD_SEP}%h%x09%s",
            "-n",
            "5",
            timeout=30,
        )
    except Exception:  # pragma: no cover - 환경 의존
        return empty
    if found.returncode != 0 or not found.stdout:
        return empty
    branch_files: frozenset[str] | None = frozenset()
    scan_error = ""
    if ref:
        branch_files, scan_error = _branch_code_files(root, trunk_ref, ref)
    if branch_files is None:
        # 분모를 못 구했다 = 포팅 여부 **판정 불가**. 근거 있음으로 넘기면 미검증 브랜치가
        # '결정 불요'가 되고, 그것이 이 태스크가 막는 바로 그 사고다(codex P1).
        return PortEvidence("", 0, 0, scan_error=scan_error)

    # 브랜치명을 인용한 커밋들을 **모아서** 본다 — 회수는 종종 여러 소형 PR로 나뉘고,
    # 커밋 하나가 파일 A를, 다른 하나가 파일 B를 옮긴다. 각각을 따로 재면 둘 다 부분
    # 착지로 보여 전건 회수된 브랜치가 계속 고립으로 남는다(codex P2).
    contributions: list[tuple[str, frozenset[str]]] = []
    for record in found.stdout.split(_EVIDENCE_RECORD_SEP):
        header, _, files_blob = record.strip("\n").partition("\n")
        header = header.strip()
        if not header:
            continue
        commit_files = {line.strip() for line in files_blob.splitlines() if line.strip()}
        tops = {f.split("/", 1)[0] for f in commit_files}
        if not tops - _LEDGER_ONLY_TOPS:
            continue  # 원장·문서만 고친 커밋 = 언급이지 흡수가 아니다
        title = header.replace("\t", " ")
        if not branch_files:
            # 브랜치에 고유 코드가 없다(순수 문서 브랜치) — 남길 코드가 없으면 고립될
            # 코드도 없으므로 교집합을 요구할 대상이 자체가 없다.
            return PortEvidence(title, 0, 0)
        contributions.append((title, branch_files & frozenset(commit_files)))

    landed_union: set[str] = set()
    for _title, overlap in contributions:
        landed_union |= overlap
    if not landed_union:
        return empty
    contributing = [title for title, overlap in contributions if overlap]
    header = contributing[0]
    if len(contributing) > 1:
        header = f"{header} (외 {len(contributing) - 1}건)"
    return PortEvidence(header, len(landed_union), len(branch_files))


@dataclass
class StaleBranchScanResult:
    """장기 미머지 브랜치 스캔 결과.

    status: ok | offline | error | shallow (판정 불가는 stale 무시 금지).
    pr_lookup_ok: PR ref 조회 성공 여부(HARN-47) — status가 ok여도 이것이 False면
    고립/PR대기 분리는 수행되지 않았다.
    `shallow`는 트렁크 히스토리가 잘려 판정 자체가 불가능한 상태다 — `is_shallow_repo`.
    """

    status: str
    stale: list[StaleBranch] = field(default_factory=list)
    scanned_refs: int = 0
    truncated: bool = False
    message: str = ""
    # PR ref 조회가 성공했는가(HARN-47). False면 isolated/pr_filed 분리가 수행되지
    # **않았다**는 뜻이며, 그 경우 브랜치는 보수적으로 unresolved로 남는다. 소비처는
    # 이 값이 False일 때 "고립 0건"이라고 말해서는 안 된다 — 측정 실패와 통과는
    # 같은 색이면 안 된다(CLAUDE.md 이중 회계).
    pr_lookup_ok: bool = False
    # PR 조회 실패 사유 — **예외 타입명을 포함**한다. 빈 문자열이면 실패가 없었다는 뜻.
    pr_lookup_error: str = ""
    # (HARN-78) pr_filed 후보의 열림/닫힘 조회가 성공했는가 — GitHub API, 선택적
    # 정밀화. True는 "시도했고 성공"뿐 아니라 "조회할 pr_filed 후보가 애초에 0건"도
    # 포함한다(조회 대상이 없으면 실패할 것도 없다). False면 pr_filed 항목들의
    # 열림/닫힘이 미확인 상태로 남았다는 뜻 — evidence에 "(상태 미확인)"이 붙는다.
    pr_state_lookup_ok: bool = True
    # 상태 조회 실패 사유 — **예외 타입명을 포함**한다(NoTokenError 포함).
    # 빈 문자열이면 실패가 없었다는 뜻(조회 불요 또는 조회 성공).
    pr_state_lookup_error: str = ""
    # (HARN-93) pr_filed 후보의 처분 라벨 조회가 성공했는가 — GitHub API, 선택적
    # 정밀화. True는 pr_state_lookup_ok와 같은 의미로 "시도 성공" 또는 "대상 0건"을
    # 뜻한다. False면 disposal_labels가 전부 빈 튜플이더라도 그것이 "라벨 없음"이
    # 아니라 "모른다"는 뜻 — 소비처는 이 값이 False일 때 라벨 부재를 단정하면 안 된다.
    pr_label_lookup_ok: bool = True
    # 라벨 조회 실패 사유 — **예외 타입명을 포함**한다(NoTokenError 포함).
    pr_label_lookup_error: str = ""
    trunk_ref: str = ""
    trunk_branch: str = ""
    trunk_source: str = ""


def scan_stale_branches(
    root: Path,
    *,
    days_threshold: int = STALE_BRANCH_DEFAULT_DAYS,
    fetch: bool = True,
    max_refs: int = SCAN_MAX_REFS,
    now: datetime | None = None,
    active_branches: frozenset[str] = frozenset(),
) -> StaleBranchScanResult:
    """트렁크에 `days_threshold`일 이상 흡수되지 않은 원격 브랜치를 찾는다.

    "흡수되지 않음"의 판정은 두 조건의 AND다 — 둘 다 필요하다:
      1. 최종 커밋(`committerdate`)이 `days_threshold`일 이상 경과.
      2. 트렁크 기준 `ahead count > 0`(SQUASH 머지 저장소이므로 커밋 그래프 조상
         관계가 아니라 `rev-list --count trunk..ref`로 판정 — `scan_remote_in_progress`
         의 규칙 A·B가 같은 이유로 조상 검사 대신 트렁크 사본 상태를 쓰는 것과 동형
         근거: SQUASH 머지 후에도 원본 브랜치의 커밋들은 트렁크의 조상이 되지 않는다).
      ahead==0이면 실질적으로 머지됐거나 애초에 커밋이 없는 것이므로 stale이 아니다.

    `fetch=True`(기본)는 이 스캔이 세션당 드물게(SessionStart 1회 또는 CI 1회) 도는
    것을 전제로 한다 — `scan_remote_done`의 `fetch=False` 기본(고빈도 `next` 경로용)과
    반대 선택이다. 최신 브랜치 목록이 없으면 "9일째 아무도 모른다"는 이 스캔의
    존재 이유 자체가 무너진다(캐시된 오래된 remote-tracking ref만 보면 새로 생긴
    방치 브랜치를 못 본다).

    반환 status가 'ok'가 아니면 **판정 자체가 불가**했다는 뜻이며, 빈 stale 목록을
    '방치 브랜치 없음'으로 읽어서는 안 된다(측정 실패와 통과는 같은 색이면 안 된다).

    active_branches(HARN-13 잔여 — 2026-08-05): 호출부가 이미 계산해둔 원격 claim
    맵의 브랜치 집합(`remote_claimed.values()`)을 그대로 넘긴다 — 새 스캔을 추가하지
    않고 기존 데이터를 재사용해 "타 세션이 지금 이 브랜치에서 작업 중"을 판별한다.
    """
    if not has_remote(root):
        return StaleBranchScanResult("offline", message="origin 원격 없음 — 브랜치 스캔 불가")
    # shallow 가드는 fetch *앞*에 둔다 — 어차피 못 믿을 결과를 위해 SessionStart마다
    # 90초 예산의 전체 fetch를 물지 않는다(fetch는 shallow를 해제하지 않는다).
    if is_shallow_repo(root):
        return StaleBranchScanResult("shallow", message=SHALLOW_PENDING_MESSAGE)
    now = now or _utcnow()
    try:
        if fetch:
            fetched = _git(
                root,
                "fetch",
                "--quiet",
                "--prune",
                "origin",
                "+refs/heads/*:refs/remotes/origin/*",
                timeout=SCAN_FETCH_TIMEOUT,
            )
            if fetched.returncode != 0:
                return StaleBranchScanResult(
                    _classify_failure(fetched.stderr),
                    message=f"원격 브랜치 fetch 실패: {fetched.stderr.strip()}",
                )
        listing = _git(
            root,
            "for-each-ref",
            "--sort=-committerdate",
            # objectname을 함께 받는다 — PR ref 대조에 tip sha가 필요한데, 브랜치마다
            # rev-parse를 돌면 git 호출이 N회 늘어난다(HARN-47). 이미 도는 열거에 얹는다.
            "--format=%(refname)%09%(committerdate:iso-strict)%09%(objectname)",
            "refs/remotes/origin",
        )
        if listing.returncode != 0:
            return StaleBranchScanResult(
                _classify_failure(listing.stderr),
                message=f"원격 ref 열거 실패: {listing.stderr.strip()}",
            )

        entries: list[tuple[str, str, str]] = []
        for line in listing.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            ref, date_str, tip_sha = parts[0].strip(), parts[1].strip(), parts[2].strip()
            if not ref or ref.endswith("/HEAD"):
                continue
            entries.append((ref, date_str, tip_sha))
        truncated = len(entries) > max_refs
        entries = entries[:max_refs]

        # PR ref는 스캔당 **1회**만 읽는다 — 브랜치마다 ls-remote를 돌리면 원격
        # 왕복이 N배가 되어 SessionStart 예산을 넘긴다.
        pr_heads, pr_lookup_error = _fetch_pr_head_shas(root)

        trunk_ref, trunk_source = _resolve_trunk_ref(root)
        trunk_branch = (
            trunk_ref[len(REMOTE_REF_PREFIX) :]
            if trunk_ref.startswith(REMOTE_REF_PREFIX)
            else trunk_ref
        )

        stale: list[StaleBranch] = []
        # (HARN-78) pr_filed로 잠정 분류된 항목의 stale 인덱스 → PR 번호. 루프가 끝난
        # 뒤 한 번에 GitHub API로 열림/닫힘을 조회해 정밀화한다(브랜치마다 API를 부르면
        # 왕복이 N배가 된다 — 위 pr_heads의 "스캔당 1회" 원칙과 같은 이유).
        pr_filed_index_to_number: dict[int, int] = {}
        for ref, date_str, tip_sha in entries:
            if ref == trunk_ref:
                continue
            branch = ref[len(REMOTE_REF_PREFIX) :] if ref.startswith(REMOTE_REF_PREFIX) else ref
            # 하네스가 스스로 만드는 claim 저장 브랜치는 사람이 결정할 작업 브랜치가
            # 아니다 — 정의상 대상 밖이지 유예가 아니다. claim이 3일만 조용하면
            # "Kiki 결정 필요"로 뜨는 것을 막는다.
            if branch == CLAIMS_BRANCH:
                continue
            try:
                last_commit_at = datetime.fromisoformat(date_str)
            except ValueError:
                continue  # 파싱 불가 — 이 브랜치만 조용히 제외(전체 스캔은 실패시키지 않음)
            age_days = (now - last_commit_at).total_seconds() / 86400
            if age_days < days_threshold:
                continue
            ahead_result = _git(root, "rev-list", "--count", f"{trunk_ref}..{ref}", timeout=15)
            if ahead_result.returncode != 0:
                continue
            try:
                ahead = int(ahead_result.stdout.strip() or "0")
            except ValueError:
                continue
            if ahead <= 0:
                continue  # 트렁크에 이미 흡수됨(또는 커밋 0) — 방치 아님
            partial_port = ""
            port_scan_error = ""
            if branch in active_branches:
                status, evidence = "active", ""
            else:
                port = _find_ported_evidence(root, trunk_ref, branch, ref)
                evidence = port.header if port.is_full_port else ""
                port_scan_error = port.scan_error
                if port.is_partial:
                    # 흡수 흔적은 있으나 **잔여 고유 코드가 남았다** — '결정 불요'가 아니다.
                    # 흔적을 버리지도(사람이 다시 찾게 됨) 흡수로 단정하지도(고립이 숨음)
                    # 않고, 아래 정상 분류를 그대로 태우되 단서를 함께 싣는다(HARN-37 ②).
                    partial_port = f"{port.landed}/{port.total} 파일 · {port.header}"
                if evidence:
                    status = "ported"
                elif pr_heads is None:
                    # PR 조회 실패 — "PR 이력 없음"으로 단정하지 않는다. 고립으로
                    # 승격하면 측정 실패가 경보로 위장된다. 기존 3분류 시절의
                    # 보수적 라벨(unresolved)로 남기고, 브리핑이 조회 실패 사실을
                    # 별도로 말한다.
                    status = "unresolved"
                else:
                    pr_number = pr_heads.get(tip_sha) if tip_sha else None
                    if pr_number is not None:
                        status, evidence = "pr_filed", f"PR #{pr_number}"
                        pr_filed_index_to_number[len(stale)] = pr_number
                    else:
                        status = "isolated"
            stale.append(
                StaleBranch(
                    branch=branch,
                    ref=ref,
                    last_commit_at=last_commit_at,
                    age_days=age_days,
                    ahead=ahead,
                    status=status,
                    evidence=evidence,
                    partial_port=partial_port,
                    port_scan_error=port_scan_error,
                )
            )

        # (HARN-78) 2차 정밀화 — pr_filed 후보의 열림/닫힘을 GitHub API로 가른다.
        # 조회 대상이 0건이면 시도할 것도 실패할 것도 없으므로 lookup_ok=True(기본값)
        # 그대로 둔다 — "조회 안 함"과 "조회 실패"는 다른 사실이다.
        pr_state_lookup_ok = True
        pr_state_lookup_error = ""
        if pr_filed_index_to_number:
            pr_states, state_err = _fetch_pr_states(root, list(pr_filed_index_to_number.values()))
            if pr_states is None:
                # 상태를 모른다 — evidence에 그 사실 자체를 남긴다(모른다 ≠ 열려
                # 있다). 기존 1차 분류(pr_filed)는 그대로 유지 — 오프라인 git 근거는
                # 여전히 유효하다.
                pr_state_lookup_ok = False
                pr_state_lookup_error = state_err
                for idx in pr_filed_index_to_number:
                    stale[idx] = replace(
                        stale[idx], evidence=f"{stale[idx].evidence} (상태 미확인)"
                    )
            else:
                for idx, number in pr_filed_index_to_number.items():
                    state_info = pr_states.get(number)
                    if state_info is None:
                        # API가 이 번호를 못 찾음(드묾 — 삭제된 PR 등) — 미확인으로 낮춘다.
                        stale[idx] = replace(
                            stale[idx], evidence=f"{stale[idx].evidence} (상태 미확인)"
                        )
                        continue
                    pr_state, pr_merged = state_info
                    if pr_state == "closed" and not pr_merged:
                        stale[idx] = replace(
                            stale[idx],
                            status="pr_closed",
                            evidence=f"PR #{number} 닫힘(미머지)",
                        )
                    # open, 또는 closed+merged=True — pr_filed 그대로 둔다. 후자(닫힘+
                    # 머지됨)는 이 태스크의 명시 acceptance 범위 밖이다(정직한 공백 —
                    # HARN-78은 "닫힘·미머지"만 새 분류로 승격하라고 요구했다).

        # (HARN-93 ②) 3차 정밀화 — 여전히 열려 있는 pr_filed 후보의 처분 라벨을
        # GitHub API로 붙인다. "닫아도 되는데 아무도 모르는" 축은 열린 PR에만 성립한다
        # — 위 2차 정밀화가 pr_closed로 승격시킨 항목은 처분이 이미 집행됐으므로
        # 라벨 조회 대상에서 뺀다(대상 자체가 없으면 lookup_ok는 True로 남는다).
        pr_label_lookup_ok = True
        pr_label_lookup_error = ""
        still_open = {
            idx: number
            for idx, number in pr_filed_index_to_number.items()
            if stale[idx].status == "pr_filed"
        }
        if still_open:
            pr_labels, label_err = _fetch_pr_labels(root, list(still_open.values()))
            if pr_labels is None:
                # 라벨을 모른다 — disposal_labels는 빈 튜플로 남기고 lookup_ok로
                # "모른다"를 별도로 알린다(모른다 ≠ 라벨 없음).
                pr_label_lookup_ok = False
                pr_label_lookup_error = label_err
            else:
                for idx, number in still_open.items():
                    names = pr_labels.get(number, ())
                    disposal = tuple(n for n in names if n in DISPOSAL_LABELS)
                    if disposal:
                        stale[idx] = replace(stale[idx], disposal_labels=disposal)

        return StaleBranchScanResult(
            "ok",
            stale=stale,
            scanned_refs=len(entries),
            truncated=truncated,
            pr_lookup_ok=pr_heads is not None,
            pr_lookup_error=pr_lookup_error,
            pr_state_lookup_ok=pr_state_lookup_ok,
            pr_state_lookup_error=pr_state_lookup_error,
            pr_label_lookup_ok=pr_label_lookup_ok,
            pr_label_lookup_error=pr_label_lookup_error,
            trunk_ref=trunk_ref,
            trunk_branch=trunk_branch,
            trunk_source=trunk_source,
        )
    except subprocess.TimeoutExpired:
        return StaleBranchScanResult("offline", message="원격 브랜치 조회 타임아웃")
    except Exception as exc:  # pragma: no cover - 환경 의존
        # 침묵 실패 금지 — 예외 타입명을 반드시 남긴다 (CLAUDE.md AI·신뢰)
        return StaleBranchScanResult("error", message=f"{type(exc).__name__}: {exc}")


# ──────────────────────────────────────────────────────────────────────────
# 설계 문서 중복 착수 탐지 (HARN-14 — HARN-13 나이 임계의 사각 보완)
# ──────────────────────────────────────────────────────────────────────────
# 2026-08-04 사고: 세션이 외부 틀(21. 운영 플랫폼)로 독립 착수했다가, 조사 중 미머지 브랜치
# claude/whymath-operations-platform-cn6dxi(당시 1일 경과)가 같은 산출물을 이미 만든 것을
# 발견했다 — 착수 전에 발견해 폐기 0줄로 끝났지만, HARN-13의 3일 나이 임계 아래였다면 브리핑에
# 안 떴을 것이다(운으로 회피). 설계 문서 중복은 *나이가 아니라 존재 자체*가 위험 신호다
# (착수 당일이 가장 위험 — 아무도 아직 모른다). 그래서 이 스캔은 나이 임계를 두지 않는다.
_DOC_SERIES_PREFIX = "docs/"
_DOC_SERIES_SUFFIX = "_review.md"  # *_gap_review.md도 이 접미어로 커버(예: "..._gap_review.md")


def _is_doc_series_path(path: str) -> bool:
    return path.startswith(_DOC_SERIES_PREFIX) and path.endswith(_DOC_SERIES_SUFFIX)


@dataclass(frozen=True)
class DocSeriesCandidate:
    """미머지 원격 브랜치가 트렁크에 없는 설계 문서 시리즈 파일을 추가한 1건."""

    branch: str
    ref: str
    files: tuple[str, ...]
    last_commit_at: datetime


@dataclass
class DocSeriesScanResult:
    """설계 문서 중복 착수 스캔 결과. status: ok | offline | error(판정 불가는 무시 금지)."""

    status: str
    candidates: list[DocSeriesCandidate] = field(default_factory=list)
    scanned_refs: int = 0
    truncated: bool = False
    message: str = ""
    trunk_ref: str = ""
    trunk_branch: str = ""
    trunk_source: str = ""


def scan_doc_series_duplicates(
    root: Path,
    *,
    fetch: bool = True,
    max_refs: int = SCAN_MAX_REFS,
) -> DocSeriesScanResult:
    """트렁크에 없는 `docs/**/*_review.md`(`*_gap_review.md` 포함)를 추가한 미머지 원격
    브랜치를 나이 무관하게 전부 찾는다.

    "추가"의 판정은 **트렁크 커밋과 브랜치 커밋의 직접 트리 비교**(`git diff A B`, 점 없는
    두 ref 형태)여야 한다 — `A...B`(공통 조상 기준 3점 diff)를 쓰면, 이미 SQUASH 머지돼
    트렁크에 실제로 존재하는 파일도 그 브랜치의 오래된 merge-base 기준으로는 "새 파일"처럼
    보여 **오탐**한다(SQUASH 머지는 원 브랜치 커밋을 트렁크의 조상으로 만들지 않으므로
    merge-base가 머지 시점보다 훨씬 이전에 머무른다 — `scan_stale_branches`가 조상 관계
    대신 `ahead` count를 쓰는 것과 같은 이유의 재발). 실측: 이미 머지된
    `claude/whymath-gamification-design-n3mf50`이 `A...B`로는 오탐되고 `A B`(직접 비교)로는
    정상적으로 빠짐을 이 스캔 설계 중 실제로 확인했다.

    반환 status가 'ok'가 아니면 판정 자체가 불가했다는 뜻이며, 빈 candidates 목록을
    '중복 없음'으로 읽어서는 안 된다(측정 실패와 통과는 같은 색이면 안 된다 — CLAUDE.md).
    """
    if not has_remote(root):
        return DocSeriesScanResult("offline", message="origin 원격 없음 — 문서 스캔 불가")
    try:
        if fetch:
            fetched = _git(
                root,
                "fetch",
                "--quiet",
                "--prune",
                "origin",
                "+refs/heads/*:refs/remotes/origin/*",
                timeout=SCAN_FETCH_TIMEOUT,
            )
            if fetched.returncode != 0:
                return DocSeriesScanResult(
                    _classify_failure(fetched.stderr),
                    message=f"원격 브랜치 fetch 실패: {fetched.stderr.strip()}",
                )
        listing = _git(
            root,
            "for-each-ref",
            "--sort=-committerdate",
            "--format=%(refname)%09%(committerdate:iso-strict)",
            "refs/remotes/origin",
        )
        if listing.returncode != 0:
            return DocSeriesScanResult(
                _classify_failure(listing.stderr),
                message=f"원격 ref 열거 실패: {listing.stderr.strip()}",
            )

        entries: list[tuple[str, str]] = []
        for line in listing.stdout.splitlines():
            ref, _, date_str = line.partition("\t")
            ref, date_str = ref.strip(), date_str.strip()
            if not ref or ref.endswith("/HEAD"):
                continue
            entries.append((ref, date_str))
        truncated = len(entries) > max_refs
        entries = entries[:max_refs]

        trunk_ref, trunk_source = _resolve_trunk_ref(root)
        trunk_branch = (
            trunk_ref[len(REMOTE_REF_PREFIX) :]
            if trunk_ref.startswith(REMOTE_REF_PREFIX)
            else trunk_ref
        )

        candidates: list[DocSeriesCandidate] = []
        for ref, date_str in entries:
            if ref == trunk_ref:
                continue
            # 나이 임계 없음(HARN-14 존재 이유) — 직접 트리 비교(점 없는 두 ref)로 트렁크에
            # 없는 신규 파일만 "추가"로 잡는다(3점 diff 오탐 회피, 함수 docstring 참조).
            diff = _git(
                root,
                "diff",
                "--diff-filter=A",
                "--name-only",
                trunk_ref,
                ref,
                timeout=30,
            )
            if diff.returncode != 0:
                continue  # 이 브랜치만 조용히 제외(전체 스캔은 실패시키지 않음 — stale 선례 동형)
            files = tuple(
                sorted(p for p in diff.stdout.splitlines() if _is_doc_series_path(p.strip()))
            )
            if not files:
                continue
            try:
                last_commit_at = datetime.fromisoformat(date_str)
            except ValueError:
                continue
            branch = ref[len(REMOTE_REF_PREFIX) :] if ref.startswith(REMOTE_REF_PREFIX) else ref
            candidates.append(
                DocSeriesCandidate(
                    branch=branch, ref=ref, files=files, last_commit_at=last_commit_at
                )
            )

        return DocSeriesScanResult(
            "ok",
            candidates=candidates,
            scanned_refs=len(entries),
            truncated=truncated,
            trunk_ref=trunk_ref,
            trunk_branch=trunk_branch,
            trunk_source=trunk_source,
        )
    except subprocess.TimeoutExpired:
        return DocSeriesScanResult("offline", message="원격 브랜치 조회 타임아웃")
    except Exception as exc:  # pragma: no cover - 환경 의존
        # 침묵 실패 금지 — 예외 타입명을 반드시 남긴다 (CLAUDE.md AI·신뢰)
        return DocSeriesScanResult("error", message=f"{type(exc).__name__}: {exc}")


def _iter_batch_blobs(stdout: str):
    """`git cat-file --batch` 출력을 요청 순서대로 blob 본문(또는 None)으로 흘린다.

    형식: 존재하면 `<sha> blob <size>\\n<본문>\\n`, 없으면 `<요청> missing\\n`.
    **요청 1건당 정확히 1개**를 내보내야 zip 정렬이 어긋나지 않는다.

    ⚠ `<size>`는 **문자 수가 아니라 바이트 수**다. 이 저장소의 태스크 YAML은 한국어라
    문자 길이로 세면 헤더 위치가 밀려 결과가 **엉뚱한 브랜치에 붙는다**(2026-07-29 실측:
    S3-09의 done 보유 브랜치를 problem-bank 대신 teaching-strategy로 오보고). 그래서
    바이트로 디코드해 오프셋을 잡고, 본문만 다시 문자열로 되돌린다.
    """
    data = stdout.encode("utf-8", errors="surrogateescape")
    pos = 0
    total = len(data)
    while pos < total:
        newline = data.find(b"\n", pos)
        if newline == -1:
            break
        header = data[pos:newline]
        pos = newline + 1
        if not header:
            continue
        parts = header.rsplit(b" ", 2)
        if len(parts) == 3 and parts[1] == b"blob" and parts[2].isdigit():
            size = int(parts[2])
            body = data[pos : pos + size]
            pos += size + 1  # 본문 뒤 개행
            yield body.decode("utf-8", errors="surrogateescape")
        else:
            yield None  # missing / ambiguous
