"""태스크 번호의 원격 관측·예약 — 번호 가드의 사각 두 개를 닫는다 (HARN-111).

## 사고 (같은 유형 4회 + 의미 축 1회)

- **3회차(2026-09-18 · EOS-108)** — 내 `add`가 06:28:11Z, 타 세션의 같은 번호 claim이
  **24초 뒤** 06:28:35Z. 내 태스크는 push 전이라 번호 가드의 세 출처(로컬·claim 대장·원격
  브랜치 파일명) 어디에도 없었다. 검사가 못 본 게 아니라 **볼 것이 없었다.**
- **4회차(2026-09-20 · EOS-128)** — 선착 브랜치가 **19분 먼저** origin에 있었는데 못 봤다.
  `remote_claims.scan_remote_task_files(root)`의 두 호출부가 모두 `fetch=False` 기본값이라
  **이 클론에 remote-tracking ref가 없는 브랜치는 0건**으로 보였고, 0건은 '없음'과 같은
  색이었다. 이번엔 **볼 것이 있었는데 못 봤다.**
- **의미 축(2026-09-28 · HARN-183↔OPS-69)** — 번호가 아니라 같은 문제의 이중 등재(슬러그까지
  동일). ⑴ 의미 고지(HARN-51)가 fetch 없는 ref만 읽었고 ⑵ 번호 가드가 방금 읽은 claim 대장에
  그 full ID가 있었는데 **번호만** 대조했으며 ⑶ 신선도 고지(HARN-43 ②)는 번호 가드의 claim
  fetch가 `FETCH_HEAD`를 다시 써서 `add` 안에서 **구조적으로 켜지지 않았다.**

## 판정 (acceptance ②) — ⓐ + ⓓ 채택 · ⓑ 기각 (2026-09-29 실측)

- **ⓓ 채택(하한)** — 스캔 직전에 `+refs/heads/*` 전체 fetch. 19분 간격이던 4회차는 이것만으로
  잡힌다. 비용: 원격 39브랜치 실측 **1.4초**(웜 클론) · 상한 `SCAN_FETCH_TIMEOUT` 90초.
  24초 경합(3회차)은 못 막는다 — 상대가 아직 push하지 않았으므로 fetch할 것이 없다.
- **ⓐ 채택(예방)** — `add`/`rename`이 번호를 `harness-claims` 브랜치의 `reservations/<번호>.json`
  에 **CAS로 예약**한다. push 전 창을 닫는 유일한 원자적 수단이다: 두 세션이 같은 번호를
  동시에 예약하면 `--force-with-lease`가 정확히 한쪽만 통과시킨다. 경합에서 지면 fail-open이
  아니라 **거부 + 다음 빈 번호 제안**(번호 재선택)이다. `refs/claims/*`가 아니라 claim 브랜치의
  하위 디렉터리인 이유는 HARN-09와 같다 — 이 환경의 프록시가 그 네임스페이스 push와 ref
  삭제를 거부한다. 새 브랜치를 만들지 않으므로 브랜치 관측기(`flow_health`·HARN-47)의
  제외 목록도 건드리지 않는다.
- **ⓑ 기각** — `adr_number_check.py`식 원격 전 브랜치 번호 스캔을 CI 게이트로 두면 **첫날부터
  red**다. 실측(2026-09-29 · origin 39브랜치 중 backlog 보유 38 · 번호 1,010개): 서로 다른
  슬러그가 같은 번호를 쓰는 교차 브랜치 충돌 **27건**, 그중 main 내부 1건(`ARCH-13` —
  이미 그랜드파더)을 뺀 **26건이 전부 방치 브랜치의 옛 사본**이다. 컨테이너 세션은 원격
  브랜치를 지울 수 없어(HARN-16 · 프록시 삭제 403) 스스로 green으로 돌릴 수 없고, 통과시키려면
  만료 없는 면제 목록이 필요하다 — acceptance ⑤와 "만료 없는 유예 금지"가 금지하는 형태다.
  사후 검출이라 충돌 자체를 막지도 못한다. main 안의 충돌은 이미 `validate`(2선)가 잡는다.
- ⓒ(ⓐ+ⓑ)는 ⓑ 기각으로 성립하지 않는다.

## 모르는 것을 '없음'으로 접지 않는다 (acceptance ② 후단)

종전 호출부 실측: `_taken_id_numbers`가 `list_claims`의 상태를 `_status`로 **버렸다** —
`list_claims`는 예외를 스스로 삼키고 `([], "offline"|"error")`를 돌려주므로 claim 대장 조회
실패가 '원격 claim 0건'으로 조용히 접혔다(바깥 `except`는 한 번도 발화할 수 없는 구조).
파일명 스캔의 `offline`도 조용히 넘겼는데, 그 값은 "원격 없음"과 "타임아웃"을 함께 뜻했다.
그리고 `cmd_add`의 "로컬만 통과" 안내는 `return` **뒤**에 있어 실행될 수 없었다.
이 모듈은 출처별 상태를 따로 들고(`RemoteView`), 원격이 아예 없는 것(`no-remote`)과 조회
실패를 구분하며, 실패는 상태 문자열(예외 타입명 포함)로 경고한다. 스캔이 ref를 하나도 못
찾으면 `empty` — **스캔 0건은 '충돌 없음'이 아니라 판정 불가**다.

네트워크 실패 시 `add`는 진행한다(fail-open) — `start`의 CAS와 같은 원칙이다: 확정 신호
(conflict)만 막고 offline/error는 **경고 + 이벤트**(`number_reserve_unavailable` ·
`remote_heads_refresh_failed`)로 남긴다. 이벤트가 있어야 "상시 실패하는 보호"를 셀 수 있다.

## 신선도 스탬프 (⑦(다))

`remote_claims.remote_refs_age_seconds`는 `FETCH_HEAD`·`refs/remotes/origin` 디렉터리 mtime을
본다 — claim fetch·표적 fetch(`git fetch origin main`)도 그것을 갱신하므로 **브랜치 발견 시각**을
재지 못한다. 그 함수는 main 낡음을 재는 `main_watch`가 그대로 쓰므로(표적 fetch가 거기서는 정당한
신선도다) 바꾸지 않고, 여기서 **전체 브랜치 fetch 전용 스탬프**를 따로 둔다
(`<git-common-dir>/whymath-branch-scan.json`). `--no-write-fetch-head`(git ≥ 2.29) 대신 스탬프를
고른 이유: claim fetch 옵션을 바꾸면 그 옵션을 모르는 git에서 claim 조회 전체가 죽는다.

## 한계 (명시)

- 예약은 **이 코드가 도는 세션끼리만** 원자적이다. 구버전 하네스로 `add`하는 세션은 예약을 안
  남긴다 — 그 번호는 브랜치가 push된 뒤 ⓓ로만 보인다.
- 예약 쓰기가 네트워크로 실패하면 24초 사각은 그 `add`에 대해 열린 채다(경고·이벤트로 드러낸다).
- 예약은 TTL(`policy.claim_ttl_hours`, 기본 72시간) 뒤 무효다 — 그때까지 브랜치를 push하지 않은
  세션의 번호는 다시 비어 보인다(실측 72시간 초과 세션 0건 · HARN-26).
- `harness-claims` 브랜치는 삭제되지 않는다는 전제를 쓴다(프록시가 ref 삭제를 거부한다 ·
  해제는 파일 삭제 커밋). 예약 읽기는 번호 가드의 claim fetch가 갱신한 로컬 미러를 재사용한다.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import remote_claims
import similar
import store

_LOG = logging.getLogger("whymath.harness.number_guard")

# 예약 디렉터리 — claim 브랜치(`harness-claims`) 루트 아래. `claims/`와 형제다.
RESERVATIONS_DIR = "reservations"
# 예약 유효 시간 기본값 — claim TTL과 같은 값(policy.claim_ttl_hours가 있으면 그쪽을 쓴다).
RESERVATION_TTL_HOURS = 72
# ⓓ 전체 브랜치 갱신 — `scan_remote_in_progress`·`scan_remote_task_files(fetch=True)`와
# 같은 refspec.
HEADS_REFSPEC = "+refs/heads/*:refs/remotes/origin/*"
HEADS_FETCH_TIMEOUT = remote_claims.SCAN_FETCH_TIMEOUT
# ⑦(다) 브랜치 발견 스탬프 — 공용 git 디렉터리(worktree가 remote-tracking ref를 공유하므로).
STAMP_FILE = "whymath-branch-scan.json"
# 번호 가드가 남긴 관측을 같은 프로세스의 뒤 단계(고지)가 재사용하는 유효 시간.
VIEW_MAX_AGE_SECONDS = 600

NO_REMOTE = "no-remote"
# 경고할 것이 없는 상태 — ok와 "원격 자체가 없음"(로컬 전용 클론 · 병렬 세션이 없다).
QUIET_STATES = frozenset({"ok", NO_REMOTE})

# 경고에 싣는 stderr 한 줄에서 URL을 가린다 — 자격 증명이 URL에 박힌 원격도 있을 수 있다.
_URL = re.compile(r"[a-z][a-z0-9+.-]*://[^\s'\"]+", re.IGNORECASE)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _stderr_line(stderr: str) -> str:
    """실패 원인 한 줄(마지막 비어 있지 않은 줄) — URL 가림 · 160자 절단."""
    lines = [ln.strip() for ln in (stderr or "").splitlines() if ln.strip()]
    return _URL.sub("<url>", lines[-1])[:160] if lines else ""


# ── ⑦(다) 브랜치 발견 스탬프 ───────────────────────────────────────────────


def _common_dir(root: Path) -> Path | None:
    out = remote_claims._git(root, "rev-parse", "--git-common-dir", timeout=10)
    raw = (out.stdout or "").strip() if out.returncode == 0 else ""
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else root / path


def _write_stamp(root: Path) -> None:
    """전체 브랜치 fetch가 **성공한 직후에만** 부른다 — 이 파일의 의미가 곧 그것이다."""
    try:
        common = _common_dir(root)
        if common is None:
            raise RuntimeError("git-common-dir 해소 실패")
        payload = {"ts": _iso(_utcnow()), "refspec": HEADS_REFSPEC}
        (common / STAMP_FILE).write_text(json.dumps(payload), encoding="utf-8")
    except Exception as exc:  # 관측 기록 실패가 등재를 막지는 않는다 — 단 타입명은 남긴다
        _LOG.warning("브랜치 발견 스탬프 기록 실패: %s", type(exc).__name__)


def branch_snapshot_age(root: Path) -> tuple[float | None, str]:
    """마지막 **전체 브랜치 fetch** 이후 경과 초. 반환 `(초, 상태)` — 네트워크 0.

    `None` = 판정 불가(`no-stamp`·`error:<타입>`). claim fetch·표적 fetch는 이 값을 바꾸지 않는다
    — 그것이 이 함수가 `remote_refs_age_seconds`와 따로 있는 이유다(모듈 docstring §신선도).
    """
    try:
        common = _common_dir(root)
        if common is None:
            return None, "error:git-common-dir"
        path = common / STAMP_FILE
        if not path.exists():
            return None, "no-stamp"
        stamp = _parse_iso(str(json.loads(path.read_text(encoding="utf-8")).get("ts", "")))
        if stamp is None:
            return None, "error:stamp-ts"
        return max(0.0, (_utcnow() - stamp).total_seconds()), "ok"
    except Exception as exc:
        return None, f"error:{type(exc).__name__}"


# ── ⓓ 원격 heads 갱신 ─────────────────────────────────────────────────────


def refresh_remote_heads(root: Path) -> tuple[str, str]:
    """스캔 직전 `+refs/heads/*` 전체 fetch (ⓓ). 반환 `(상태, 실패 원인 한 줄)`.

    `--prune`: origin에서 지워진 브랜치의 옛 ref가 남아 있으면 그 사본의 번호가 거짓 충돌을 낸다.
    상태: `ok` · `no-remote` · `offline` · `timeout` · `error` · `error:<예외 타입>`.
    """
    if not remote_claims.has_remote(root):
        return NO_REMOTE, ""
    try:
        out = remote_claims._git(
            root,
            "fetch",
            "--quiet",
            "--prune",
            "origin",
            HEADS_REFSPEC,
            timeout=HEADS_FETCH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return "timeout", f"{HEADS_FETCH_TIMEOUT}초 초과"
    except Exception as exc:
        return f"error:{type(exc).__name__}", ""
    if out.returncode != 0:
        kind = remote_claims._classify_failure(out.stderr or "")
        return ("error" if kind == "lease" else kind), _stderr_line(out.stderr or "")
    _write_stamp(root)
    return "ok", ""


# ── ⓐ 번호 예약 ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Reservation:
    """`reservations/<번호>.json` 1건. 파손 레코드는 `task_id`가 비어 있다."""

    number: str
    task_id: str
    branch: str
    ts: str
    blob_sha: str = ""

    def expired(self, now: datetime, ttl_hours: int) -> bool:
        """TTL을 넘겼는가. **시각을 모르면 만료가 아니다**(모른다 ≠ 아니다) — 파손 레코드가
        번호를 풀어 주면 살아 있는 예약을 지울 수 있다."""
        stamp = _parse_iso(self.ts)
        return stamp is not None and now - stamp > timedelta(hours=ttl_hours)


def _reservations_at(root: Path, sha: str) -> list[Reservation]:
    """커밋 `sha`의 `reservations/` 전건(만료 포함) — 로컬 객체만 읽는다. 실패는 예외."""
    if not sha:
        return []
    ls = remote_claims._git(root, "ls-tree", "-r", "-z", sha, timeout=15)
    if ls.returncode != 0:
        raise RuntimeError(f"예약 트리 조회 실패: {_stderr_line(ls.stderr or '')}")
    wanted: list[tuple[str, str]] = []  # (번호, blob sha)
    prefix = f"{RESERVATIONS_DIR}/"
    for entry in (ls.stdout or "").split("\0"):
        info, _, path = entry.partition("\t")
        fields = info.split()
        if len(fields) < 3 or fields[1] != "blob":
            continue
        if path.startswith(prefix) and path.endswith(".json"):
            wanted.append((path[len(prefix) : -len(".json")], fields[2]))
    if not wanted:
        return []
    batch = remote_claims._git(
        root, "cat-file", "--batch", input_text="".join(f"{s}\n" for _, s in wanted), timeout=30
    )
    if batch.returncode != 0:
        raise RuntimeError(f"예약 본문 조회 실패: {_stderr_line(batch.stderr or '')}")
    found: list[Reservation] = []
    for (number, blob_sha), body in zip(
        wanted, remote_claims._iter_batch_blobs(batch.stdout or ""), strict=False
    ):
        meta: dict = {}
        try:
            meta = json.loads(body) if body is not None else {}
        except json.JSONDecodeError:
            meta = {}
        found.append(
            Reservation(
                number=number,
                task_id=str(meta.get("task") or ""),
                branch=str(meta.get("branch") or ""),
                ts=str(meta.get("ts") or ""),
                blob_sha=blob_sha,
            )
        )
    return found


def _write_reservations(
    root: Path, base_sha: str, kept: list[Reservation], mine: dict, message: str
) -> str:
    """예약 디렉터리만 갈아 끼운 커밋 — `claims/` 등 나머지 루트 항목은 base에서 옮긴다."""
    lines = [f"100644 blob {r.blob_sha}\t{r.number}.json" for r in kept if r.blob_sha]
    payload = json.dumps(mine, ensure_ascii=False, sort_keys=True)
    blob = remote_claims._git(root, "hash-object", "-w", "--stdin", input_text=payload)
    if blob.returncode != 0:
        raise RuntimeError(f"예약 blob 생성 실패: {_stderr_line(blob.stderr or '')}")
    lines.append(f"100644 blob {blob.stdout.strip()}\t{mine['number']}.json")
    sub = remote_claims._git(root, "mktree", input_text="\n".join(lines) + "\n")
    if sub.returncode != 0:
        raise RuntimeError(f"예약 트리 생성 실패: {_stderr_line(sub.stderr or '')}")
    entries = remote_claims.preserved_root_entries(root, base_sha, RESERVATIONS_DIR)
    entries.append(f"040000 tree {sub.stdout.strip()}\t{RESERVATIONS_DIR}\n")
    tree = remote_claims._git(root, "mktree", input_text="".join(entries))
    if tree.returncode != 0:
        raise RuntimeError(f"루트 트리 생성 실패: {_stderr_line(tree.stderr or '')}")
    argv = ["commit-tree", tree.stdout.strip()]
    if base_sha:
        argv += ["-p", base_sha]
    argv += ["-m", message]
    commit = remote_claims._git(root, *argv, env_extra=remote_claims._COMMIT_IDENTITY)
    if commit.returncode != 0:
        raise RuntimeError(f"예약 커밋 생성 실패: {_stderr_line(commit.stderr or '')}")
    return commit.stdout.strip()


@dataclass
class ReserveResult:
    """예약 시도 결과. status = ok | conflict | no-remote | skipped | disabled | offline | error…"""

    status: str
    holder: str = ""  # conflict 상대 full ID
    holder_branch: str = ""
    source: str = ""  # conflict 출처: "예약" | "claim"
    message: str = ""


def _same_session(a: str, b: str) -> bool:
    """같은 브랜치 = 같은 세션(1 세션 = 1 브랜치 규약). 브랜치를 모르면 같다고 보지 않는다."""
    return bool(a) and a == b and a not in ("unknown", "HEAD")


def reserve(
    root: Path, task_id: str, branch: str, *, ttl_hours: int = RESERVATION_TTL_HOURS
) -> ReserveResult:
    """`task_id`의 번호를 원격에 CAS로 예약한다 (ⓐ).

    충돌 판정은 **같은 스냅샷**(CAS base)에서 두 곳을 본다:
      · 살아 있는 같은 번호 예약 — full ID도 브랜치도 다르면 경합에서 진 것이다.
      · 같은 번호의 claim(착수·차단 홀드) — 번호 가드가 읽은 뒤 누가 착수했을 수 있다.
    같은 full ID의 재예약(다른 클론의 시딩·재실행)과 같은 브랜치의 번호 재사용(실패한 add의
    잔재를 다른 슬러그로 다시 잡는 것)은 충돌이 아니다 — 번호 가드의 "슬러그가 다를 때만
    충돌" 규칙(HARN-10)과 같은 판정이다.

    쓰기마다 만료 예약을 걷는다(지연 청소) — 별도 청소 잡 없이 대장이 TTL 안의 것만 담는다.
    """
    task_id = remote_claims._sanitize_ident(task_id)
    branch = remote_claims._sanitize_ident(branch)
    number = store.id_number_of(task_id)
    if not number:
        return ReserveResult("skipped", message="번호 없는 ID — 예약 대상 아님")
    if not remote_claims.has_remote(root):
        return ReserveResult(NO_REMOTE)
    last = ""
    try:
        for _attempt in range(remote_claims.CAS_RETRIES):
            now = _utcnow()
            base_sha, status = remote_claims._fetch_claims_branch(root)
            if status != "ok":
                return ReserveResult(status, message=f"claim 브랜치 조회 실패: {status}")
            current = _reservations_at(root, base_sha)
            for held in current:
                if held.number != number or held.expired(now, ttl_hours):
                    continue
                if held.task_id == task_id or _same_session(held.branch, branch):
                    continue
                return ReserveResult(
                    "conflict",
                    holder=held.task_id or "홀더 불명(예약 레코드 파손)",
                    holder_branch=held.branch,
                    source="예약",
                )
            for claim in remote_claims._read_claims(root, base_sha):
                if claim.task_id != task_id and store.id_number_of(claim.task_id) == number:
                    return ReserveResult(
                        "conflict", holder=claim.task_id, holder_branch=claim.branch, source="claim"
                    )
            kept = [r for r in current if r.number != number and not r.expired(now, ttl_hours)]
            mine = {
                "task": task_id,
                "number": number,
                "branch": branch,
                "ts": _iso(now),
                "harness": "2.0",
                "kind": "reserve",
            }
            commit = _write_reservations(
                root, base_sha, kept, mine, f"reserve {number} ({task_id} · {branch})"
            )
            push = remote_claims._push_claims(root, base_sha, commit)
            if push.returncode == 0:
                return ReserveResult("ok")
            last = _stderr_line(push.stderr or "")
            kind = remote_claims._classify_failure(push.stderr or "")
            if kind != "lease":
                return ReserveResult(kind, message=last)
            # lease 경합 — 그 사이 누가 claim 브랜치를 갱신했다. 재fetch 후 다시 판정한다.
        return ReserveResult(
            "error", message=f"CAS 재시도 {remote_claims.CAS_RETRIES}회 초과(lease 경합): {last}"
        )
    except subprocess.TimeoutExpired:
        return ReserveResult("timeout", message="git 타임아웃")
    except Exception as exc:
        return ReserveResult(f"error:{type(exc).__name__}", message=_stderr_line(str(exc)))


def reserve_for(root: Path, task_id: str, policy: object, *, verb: str = "add") -> ReserveResult:
    """CLI 진입점 — 정책 확인 · 예약 · 비정상 상태의 경고와 이벤트까지 한 번에.

    conflict는 여기서 거부 문구를 만들지 않는다 — 호출부가 번호 가드를 다시 돌려 **다음 빈
    번호 제안이 담긴 표준 거부 문구**를 낸다(예약을 방금 본 번호 가드는 그 번호를 점유로 센다).
    """
    if not getattr(policy, "remote_claims", False):
        return ReserveResult("disabled")
    result = reserve(
        root,
        task_id,
        store.current_branch(root),
        ttl_hours=int(getattr(policy, "claim_ttl_hours", RESERVATION_TTL_HOURS)),
    )
    number = store.id_number_of(task_id) or task_id
    if result.status == "ok":
        print(
            f"  · 번호 예약 {number} — harness-claims/{RESERVATIONS_DIR}/ "
            "(push 전에도 다른 세션의 add·rename이 이 번호를 거부한다 · HARN-111)"
        )
    elif result.status == "conflict":
        store.append_event(
            root,
            "number_reserve_conflict",
            task_id,
            verb=verb,
            holder=result.holder,
            holder_branch=result.holder_branch,
            source=result.source,
        )
    elif result.status not in QUIET_STATES and result.status not in ("skipped", "disabled"):
        detail = f" — {result.message}" if result.message else ""
        print(
            f"  ⚠ 번호 예약 실패({result.status}){detail}. 이 번호는 **push 전까지 병렬 세션의 "
            "add·rename으로부터 보호되지 않는다**(24초 사각 · EOS-108). 이 명령은 그대로 "
            f"진행한다({verb}) — 머지 시 validate가 2선 방어한다",
            file=sys.stderr,
        )
        store.append_event(
            root,
            "number_reserve_unavailable",
            task_id,
            verb=verb,
            status=result.status,
            detail=result.message,
        )
    return result


def describe_conflict(task_id: str, result: ReserveResult) -> str:
    """번호 가드 재판정이 통과로 나온 드문 경우의 폴백 거부 문구."""
    number = store.id_number_of(task_id) or task_id
    where = f" · {result.holder_branch}" if result.holder_branch else ""
    return (
        f"태스크 ID 번호 충돌: '{number}' 를 {result.holder}({result.source}{where}) 가 방금 "
        "원격에 잡았다 — 번호 예약 경합에서 졌다(HARN-111). 다른 번호로 다시 실행하라"
    )


# ── 관측 한 번 — 번호 가드와 고지가 같은 스냅샷을 쓴다 ────────────────────────


@dataclass
class RemoteView:
    """번호 가드 한 번의 원격 관측. 출처마다 상태를 따로 든다 — 한 출처의 실패가 다른
    출처의 결과를 버리게 하지 않고, 어느 출처를 못 봤는지 말할 수 있게."""

    heads_status: str = "disabled"
    heads_detail: str = ""
    claims: list = field(default_factory=list)
    claims_status: str = "disabled"
    reservations: list = field(default_factory=list)
    reservations_status: str = "disabled"
    task_files: list = field(default_factory=list)
    files_status: str = "disabled"
    refs_seen: int = 0

    @property
    def complete(self) -> bool:
        """네 출처가 전부 봤는가(또는 원격이 아예 없는가). False면 번호 가드는 부분 판정이다."""
        return all(
            s in QUIET_STATES
            for s in (
                self.heads_status,
                self.claims_status,
                self.reservations_status,
                self.files_status,
            )
        )

    def warnings(self) -> list[str]:
        """못 본 출처마다 한 줄 — 무엇을 못 보는지까지 말한다(0건 통과 위장 금지)."""
        out: list[str] = []
        if self.heads_status not in QUIET_STATES:
            detail = f" · {self.heads_detail}" if self.heads_detail else ""
            out.append(
                f"원격 브랜치 목록 갱신 실패({self.heads_status}{detail}) — 이 클론이 이미 가진 "
                "remote-tracking ref로만 판정한다. 그 뒤 origin에 올라온 브랜치의 번호는 못 본다"
                "(EOS-128 형태 · HARN-111 ⓓ)"
            )
        if self.claims_status not in QUIET_STATES:
            out.append(
                f"원격 claim 대장 조회 실패({self.claims_status}) — 착수 중인 타 세션의 번호와 "
                "번호 예약을 못 본다(병렬 세션의 인플라이트 번호는 로컬 백로그로 축소된 판정)"
            )
        elif self.reservations_status not in QUIET_STATES:
            out.append(
                f"번호 예약 대장 읽기 실패({self.reservations_status}) — push 전 타 세션이 잡은 "
                "번호를 못 본다"
            )
        if self.files_status == "empty":
            out.append(
                f"원격 ref {self.refs_seen}개에서 backlog/tasks/를 하나도 찾지 못했다 — **스캔 "
                "0건은 '충돌 없음'이 아니라 판정 불가**다(등재만 된 원격 번호를 못 본다)"
            )
        elif self.files_status not in QUIET_STATES:
            out.append(
                f"원격 브랜치 backlog/tasks/ 파일명 스캔 실패({self.files_status}) — 등재만 되고 "
                "아직 claim되지 않은 원격 번호는 놓칠 수 있다"
            )
        return out


_VIEWS: dict[str, tuple[float, RemoteView]] = {}


def _key(root: Path) -> str:
    return str(Path(root).resolve())


def _guarded(fn, root: Path) -> tuple[list, str]:
    """관측 함수 호출 — 어떤 식으로 죽어도 `([], "error:<타입>")`로 받는다(타입명 보존)."""
    try:
        items, status = fn(root)
        return list(items), str(status)
    except Exception as exc:
        return [], f"error:{type(exc).__name__}"


def _mirror_reservations(root: Path, claims_status: str, ttl_hours: int) -> tuple[list, str]:
    """번호 가드의 claim fetch가 방금 갱신한 로컬 미러에서 예약을 읽는다(추가 네트워크 0).

    **이 세션(같은 브랜치)의 예약은 뺀다** — 로컬 백로그에 있는 태스크면 로컬 출처가 이미
    잡고, 없으면 실패한 add의 잔재다. 잔재를 점유로 세면 같은 세션이 번호를 다시 잡지 못하고
    자기 자신을 충돌 상대로 보게 된다(`reserve`의 같은 세션 허용과 같은 판정).
    """
    if claims_status != "ok":
        return [], claims_status
    try:
        rev = remote_claims._git(
            root, "rev-parse", "--verify", "--quiet", remote_claims.LOCAL_MIRROR_REF, timeout=10
        )
        if rev.returncode != 0:
            return [], "ok"  # claim 브랜치가 아직 없다 = 예약 0건
        now = _utcnow()
        mine = store.current_branch(root)
        live = [
            r
            for r in _reservations_at(root, rev.stdout.strip())
            if not r.expired(now, ttl_hours) and not _same_session(r.branch, mine)
        ]
        return live, "ok"
    except Exception as exc:
        return [], f"error:{type(exc).__name__}"


def observe(root: Path, *, ttl_hours: int = RESERVATION_TTL_HOURS) -> RemoteView:
    """번호 가드의 원격 관측 한 번 — ⓓ 갱신 → claim 대장(+예약) → 브랜치 파일명 스캔.

    결과는 같은 프로세스의 뒤 단계(의미 고지·가시성 고지)가 `current_view`로 재사용한다 —
    고지가 claim 대장을 다시 fetch하지 않는다(⑦(나) · 추가 네트워크 0).
    """
    view = RemoteView()
    remote = remote_claims.has_remote(root)
    view.heads_status, view.heads_detail = refresh_remote_heads(root) if remote else (NO_REMOTE, "")
    if view.heads_status not in QUIET_STATES:
        # 측정 가능해야 '상시 실패하는 보호'를 셀 수 있다 — 경고만으로는 습관화된다.
        store.append_event(
            root,
            "remote_heads_refresh_failed",
            "-",
            status=view.heads_status,
            detail=view.heads_detail,
        )
    view.claims, view.claims_status = _guarded(remote_claims.list_claims, root)
    if not remote and view.claims_status == "offline":
        view.claims_status = NO_REMOTE
    if remote:
        view.reservations, view.reservations_status = _mirror_reservations(
            root, view.claims_status, ttl_hours
        )
    else:
        view.reservations_status = NO_REMOTE
    view.task_files, view.files_status = _guarded(remote_claims.scan_remote_task_files, root)
    if not remote and view.files_status == "offline":
        view.files_status = NO_REMOTE
    if view.files_status == "ok" and remote:
        view.refs_seen = _count_remote_refs(root)
        if not view.task_files:
            view.files_status = "empty"
    _VIEWS[_key(root)] = (time.monotonic(), view)
    return view


def _count_remote_refs(root: Path) -> int:
    try:
        out = remote_claims._git(root, "for-each-ref", "--format=%(refname)", "refs/remotes/origin")
        return sum(1 for r in (out.stdout or "").split() if not r.endswith("/HEAD"))
    except Exception as exc:  # 경고 문구의 개수일 뿐이다 — 판정은 files_status가 한다
        _LOG.warning("원격 ref 개수 조회 실패: %s", type(exc).__name__)
        return 0


def current_view(root: Path) -> RemoteView | None:
    """이 프로세스에서 방금(VIEW_MAX_AGE_SECONDS 안) 남긴 관측. 없으면 None(판정 불가)."""
    entry = _VIEWS.get(_key(root))
    if entry is None or time.monotonic() - entry[0] > VIEW_MAX_AGE_SECONDS:
        return None
    return entry[1]


def forget(root: Path) -> None:
    """관측 기록 제거 — 테스트·장수 프로세스용."""
    _VIEWS.pop(_key(root), None)


def slug_candidates(
    root: Path, task_id: str, known_ids: set[str]
) -> tuple[list[similar.SimilarTask], str]:
    """본문이 없는 원격 claim·예약을 슬러그로 대조한다 (⑦(가)).

    대조군 = 번호 가드가 **방금 읽은** claim 대장·예약 중 본문을 가진 쪽(로컬·원격 사본)에 없는
    full ID. 본문이 있는 태스크는 IDF 본문 대조가 더 정확하므로 여기서 빼 중복 고지를 막는다.
    반환 상태가 `ok`가 아니면 claim 대조는 판정 불가다(`not-observed` = 관측 기록 없음).
    """
    view = current_view(root)
    if view is None:
        return [], "not-observed"
    pool: dict[str, str] = {}
    for claim in view.claims:
        if claim.task_id in known_ids or claim.task_id == task_id:
            continue
        label = "원격 차단 홀드" if getattr(claim, "kind", "claim") == "block" else "원격 claim"
        pool.setdefault(claim.task_id, f"{label}·{claim.branch or '홀더 불명'} · 슬러그 대조")
    for held in view.reservations:
        if not held.task_id or held.task_id in known_ids or held.task_id == task_id:
            continue
        pool.setdefault(held.task_id, f"원격 번호 예약·{held.branch or '홀더 불명'} · 슬러그 대조")
    status = view.claims_status if view.claims_status not in QUIET_STATES else "ok"
    if status == "ok" and view.reservations_status not in QUIET_STATES:
        status = view.reservations_status
    if not pool:
        return [], status
    index = similar.SlugIndex([*known_ids, *pool, task_id])
    hits: list[similar.SimilarTask] = []
    for other, origin in pool.items():
        score, shared = index.score(task_id, other)
        if score >= similar.SLUG_FLOOR:
            hits.append(similar.SimilarTask(other, score, origin, shared))
    hits.sort(key=lambda h: (-h.score, h.task_id))
    return hits[: similar.MAX_CANDIDATES], status
