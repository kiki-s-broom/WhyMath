#!/usr/bin/env python3
"""고립 브랜치 스캔 리포트 — CI가 발행하고 세션이 소비한다 (HARN-28).

왜 필요한가
-----------
`remote_claims.scan_stale_branches`는 shallow 클론이면 판정을 포기한다(`status="shallow"`).
**모든 CCR 세션 컨테이너가 shallow다.** 즉 이 탐지기는 세션 환경에서 한 번도 목록을 낸 적이
없다(2026-08-11 실측 · 미측정 상태의 규모: 미머지 커밋 392·열린 PR 없는 브랜치 27·최장 고립
8일). `docs/reviews/unmerged_branch_verdict_2026-08-11.md`는 이 상태를 예언했고 `--unshallow`
자동 실행은 타당한 사유로 기각했다 — 그 기각을 뒤집지 않고 **실행 위치를 옮긴다**.

구조
----
    [CI 야간 · full clone]                                   [세션 · shallow clone]
    scan_stale_branches() ──▶ isolation.json ──▶ harness-reports ──▶ cmd_brief ──▶ 브리핑
             (publish)        (build_report)     (orphan 브랜치)    (fetch_report)

· 발행은 `harness-audit.yml`의 `isolation-scan` 잡이 야간에 한다(`publish`).
· 소비는 `backlog.py brief`가 **세션 스캔이 shallow일 때만** 한다. 전체 클론(Kiki 머신)은
  라이브 스캔이 더 신선하므로 리포트를 읽지 않는다.

왜 `harness-claims`에 얹지 않는가
--------------------------------
`harness-claims`는 세션이 claim을 쓸 때마다 CAS로 갱신하는 고경합 브랜치다. 쓰기 주체(야간
CI 1개 vs 세션 N개)·주기(일 1회 vs 수시)·실패 영향(리포트 지연 vs 착수 차단)이 전부 달라
섞으면 서로의 CAS 재시도·실패를 유발한다. (초안은 "`_write_claims()`가 `claims/` 밖 경로를
삭제한다"를 근거로 들었으나 그 결함은 HARN-111 `preserved_root_entries`로 이미 해소됐다 —
근거가 사라져도 분리 자체는 위 이유로 여전히 옳다.)

설계 결정 (실패 경로 — CLAUDE.md "측정·수집 도구를 성공 경로만 보고 설계 금지")
-------------------------------------------------------------------------
· **측정 실패 ≠ 통과.** 스캔 status가 `ok`가 아니면 *발행하지 않고* exit 2로 잡을 red로 만든다.
  `shallow`/`offline`/`error` 스캔을 빈 목록으로 발행하면 소비자가 "고립 0건"으로 읽는다.
  발행을 거부하면 직전 정상 리포트가 남고, 그 **생성 시각이 소비 쪽에 항상 보이므로** 낡음이
  숨지 않는다(`STALE_AFTER_HOURS` 초과 시 경고).
· **소비 쪽은 4상태를 구분한다.** `ok`/`absent`(브랜치 없음)/`corrupt`(파싱·스키마 실패)/
  `unreachable`(네트워크). 셋 다 "미측정"이지만 처방이 다르다(잡 실행 / 잡 점검 / 재시도).
  "리포트 없음"을 "고립 없음"으로 읽는 경로는 구조적으로 없다.
· **`git fetch --depth`를 쓰지 않는다.** full 클론에서 depth를 주면 그 클론이 shallow로 바뀌어
  이 태스크가 고치려는 바로 그 결함을 스스로 만든다. 리포트 브랜치는 루트 커밋 1개짜리라
  depth 없이도 O(1)이다(발행이 부모 없는 커밋을 force-with-lease로 덮어쓴다).
· 추이는 브랜치에 쌓지 않는다 — 워크플로가 `isolation.json`을 아티팩트(30일)로도 올린다.
· 예외는 타입명을 남긴다(침묵 실패 금지). 소비 쪽 함수는 **절대 raise하지 않는다**(훅 진입점).

CLI
---
    isolation_report.py publish [--days N] [--out PATH] [--dry-run]
        0 발행 성공 · 1 쓰기/푸시 실패 · 2 스캔 불가(측정 못 함 — 발행 안 함)
    isolation_report.py show
        0 정상 리포트 · 3 absent · 4 corrupt · 5 unreachable
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import remote_claims  # noqa: E402  (경로 삽입 후 임포트)

REPORTS_BRANCH = remote_claims.REPORTS_BRANCH
REPORTS_REF = f"refs/heads/{REPORTS_BRANCH}"
# 소비 쪽 로컬 미러 — 로컬 브랜치와 충돌 없는 전용 공간(체크아웃 대상이 아니다).
LOCAL_MIRROR_REF = "refs/whymath-reports/head"
REPORT_FILE = "isolation.json"
SCHEMA_VERSION = 1

# 야간(24h) + 슬랙 12h. 이보다 오래된 리포트는 "야간 잡이 멎었다"는 신호이므로 소비 쪽이 경고한다.
STALE_AFTER_HOURS = 36
# 시계 어긋남 허용 — 이보다 미래의 생성 시각은 신뢰하지 않는다(낡음을 영구히 가린다).
FUTURE_TOLERANCE = timedelta(hours=1)

# 리포트가 품을 수 있는 분류 — `remote_claims.StaleBranch.status` 어휘와 일치해야 한다.
KNOWN_STATUSES = frozenset({"isolated", "pr_filed", "pr_closed", "unresolved", "ported", "active"})

STATE_OK = "ok"
STATE_ABSENT = "absent"
STATE_CORRUPT = "corrupt"
STATE_UNREACHABLE = "unreachable"

_LS_REMOTE_TIMEOUT = 20
_FETCH_TIMEOUT = 30
_PUSH_TIMEOUT = 60


# ──────────────────────────────────────────────────────────────────────────
# 직렬화 (①계약)
# ──────────────────────────────────────────────────────────────────────────


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _resolve_sha(root: Path, ref: str) -> str:
    """ref의 커밋 sha — 판정 기준(어느 트렁크 시점에서 쟀는가). 못 구하면 빈 문자열."""
    try:
        out = remote_claims._git(root, "rev-parse", "--verify", "--quiet", ref, timeout=10)
    except Exception:  # 판정 기준 병기일 뿐 — 못 구해도 리포트는 만든다(빈 값이 사실을 말한다)
        return ""
    return out.stdout.strip() if out.returncode == 0 and out.stdout else ""


def build_report(
    scan: remote_claims.StaleBranchScanResult,
    *,
    root: Path,
    days_threshold: int,
    now: datetime,
) -> dict[str, Any]:
    """스캔 결과 → 기계 판독 리포트. `scan.status == "ok"`일 때만 호출한다.

    브랜치마다 **최종 커밋 시각(절대값)** 을 싣고 나이는 싣지 않는다 — 나이는 읽는 시점마다
    달라지므로 소비 쪽이 `last_commit_at`에서 다시 계산한다(어제 잰 "3일"이 오늘도 3일로
    읽히는 것을 막는다). `age_days_at_generation`은 사람이 JSON을 눈으로 볼 때만 쓴다.
    """
    if scan.status != "ok":
        raise ValueError(f"스캔 status={scan.status!r} — ok가 아닌 결과로는 리포트를 만들지 않는다")
    counts: dict[str, int] = {}
    branches: list[dict[str, Any]] = []
    for s in scan.stale:
        counts[s.status] = counts.get(s.status, 0) + 1
        branches.append(
            {
                "branch": s.branch,
                "status": s.status,
                "ahead": s.ahead,
                "last_commit_at": _iso(s.last_commit_at),
                "age_days_at_generation": round(s.age_days, 2),
                "evidence": s.evidence,
                "partial_port": s.partial_port,
                "port_scan_error": s.port_scan_error,
                "disposal_labels": list(s.disposal_labels),
                # 3상태 — None은 "미측정/판정 불가"이지 0이 아니다. 그대로 null로 싣는다.
                "impl_new": s.impl_new,
                "impl_changed": s.impl_changed,
                "impl_scan_error": s.impl_scan_error,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(now),
        "scan_status": scan.status,
        "basis": {
            "days_threshold": days_threshold,
            "trunk_ref": scan.trunk_ref,
            "trunk_branch": scan.trunk_branch,
            "trunk_source": scan.trunk_source,
            "trunk_sha": _resolve_sha(root, scan.trunk_ref) if scan.trunk_ref else "",
            "scanned_refs": scan.scanned_refs,
            "truncated": scan.truncated,
            "pr_lookup_ok": scan.pr_lookup_ok,
            "pr_lookup_error": scan.pr_lookup_error,
            "pr_state_lookup_ok": scan.pr_state_lookup_ok,
            "pr_state_lookup_error": scan.pr_state_lookup_error,
            "pr_label_lookup_ok": scan.pr_label_lookup_ok,
            "pr_label_lookup_error": scan.pr_label_lookup_error,
            "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        },
        "counts": counts,
        "branches": branches,
    }


def _parse_dt(value: object) -> datetime | None:
    """tz가 있는 ISO 시각만 인정한다. naive는 None — 나이 계산이 로컬 시간대에 오염된다."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else None


def validate_report(data: object, *, now: datetime | None = None) -> list[str]:
    """리포트 스키마 검증 → 위반 목록(빈 목록 = 정상). 예외를 던지지 않는다.

    **부분 정상을 정상으로 읽지 않는다**: 필수 키 하나라도 없으면 전체를 손상으로 본다 —
    일부 필드만 맞는 리포트에서 "고립 0건"을 읽는 쪽이 사고를 만든다.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return [f"최상위가 객체가 아니다({type(data).__name__})"]
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version={data.get('schema_version')!r} (기대 {SCHEMA_VERSION})")
    generated = _parse_dt(data.get("generated_at"))
    if generated is None:
        errors.append("generated_at이 tz 있는 ISO 시각이 아니다")
    elif now is not None and generated > now + FUTURE_TOLERANCE:
        errors.append("generated_at이 미래다 — 낡음 판정을 영구히 가릴 수 있어 신뢰하지 않는다")
    if data.get("scan_status") != "ok":
        errors.append(f"scan_status={data.get('scan_status')!r} — ok만 발행 대상이다")
    basis = data.get("basis")
    if not isinstance(basis, dict):
        errors.append("basis가 객체가 아니다")
    else:
        for key, typ in (
            ("days_threshold", int),
            ("trunk_ref", str),
            ("trunk_sha", str),
            ("scanned_refs", int),
            ("pr_lookup_ok", bool),
            ("pr_state_lookup_ok", bool),
        ):
            if not isinstance(basis.get(key), typ):
                errors.append(f"basis.{key}가 {typ.__name__}가 아니다")
    branches = data.get("branches")
    counts = data.get("counts")
    if not isinstance(branches, list):
        errors.append("branches가 목록이 아니다")
        return errors
    if not isinstance(counts, dict):
        errors.append("counts가 객체가 아니다")
        counts = {}
    tally: dict[str, int] = {}
    for i, b in enumerate(branches):
        if not isinstance(b, dict):
            errors.append(f"branches[{i}]가 객체가 아니다")
            continue
        if not isinstance(b.get("branch"), str) or not b.get("branch"):
            errors.append(f"branches[{i}].branch가 비었다")
        status = b.get("status")
        if status not in KNOWN_STATUSES:
            errors.append(f"branches[{i}].status={status!r}는 알 수 없는 분류다")
        else:
            tally[str(status)] = tally.get(str(status), 0) + 1
        if not isinstance(b.get("ahead"), int) or isinstance(b.get("ahead"), bool):
            errors.append(f"branches[{i}].ahead가 정수가 아니다")
        if _parse_dt(b.get("last_commit_at")) is None:
            errors.append(f"branches[{i}].last_commit_at이 tz 있는 ISO 시각이 아니다")
    if counts != tally:
        # 요약과 본문이 어긋나면 어느 쪽도 못 믿는다 — 부분 쓰기·수기 편집의 지문.
        errors.append(f"counts({counts})가 branches 집계({tally})와 다르다")
    return errors


# ──────────────────────────────────────────────────────────────────────────
# 발행 (②집행 지점 — CI 야간 잡이 부른다)
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class PublishResult:
    status: str  # ok | lease | offline | error
    commit: str = ""
    message: str = ""


def _remote_tip(root: Path) -> tuple[str | None, str]:
    """원격 `harness-reports`의 tip → (sha, 상태). sha 빈 문자열 = 브랜치 없음, None = 조회 실패."""
    ls = remote_claims._git(root, "ls-remote", "origin", REPORTS_REF, timeout=_LS_REMOTE_TIMEOUT)
    if ls.returncode != 0:
        return None, remote_claims._classify_failure(ls.stderr or "")
    line = (ls.stdout or "").strip().splitlines()
    return (line[0].split()[0] if line else ""), "ok"


def _build_commit(root: Path, payload: str, message: str) -> str:
    """리포트 1건을 담은 **부모 없는** 커밋을 만든다 — 인덱스·작업 트리를 건드리지 않는다.

    부모를 두지 않는 이유: 브랜치가 영구히 커밋 1개라 소비 쪽 fetch가 클론 종류(full/shallow)와
    무관하게 O(1)이고, 이력이 자라 소비 비용이 늘 일이 없다. 추이는 워크플로 아티팩트가 맡는다.
    """
    blob = remote_claims._git(root, "hash-object", "-w", "--stdin", input_text=payload)
    if blob.returncode != 0:
        raise RuntimeError(f"blob 생성 실패: {(blob.stderr or '').strip()}")
    tree = remote_claims._git(
        root, "mktree", input_text=f"100644 blob {blob.stdout.strip()}\t{REPORT_FILE}\n"
    )
    if tree.returncode != 0:
        raise RuntimeError(f"트리 생성 실패: {(tree.stderr or '').strip()}")
    commit = remote_claims._git(
        root,
        "commit-tree",
        tree.stdout.strip(),
        "-m",
        message,
        env_extra=remote_claims._COMMIT_IDENTITY,
    )
    if commit.returncode != 0:
        raise RuntimeError(f"커밋 생성 실패: {(commit.stderr or '').strip()}")
    return commit.stdout.strip()


def publish(root: Path, report: dict[str, Any]) -> PublishResult:
    """리포트를 `harness-reports`에 발행한다(CAS). 검증을 통과하지 못한 리포트는 쓰지 않는다."""
    problems = validate_report(report)
    if problems:
        # 자기 산출물이 자기 검증을 못 넘는 것은 코드 결함이다 — 소비자에게 손상본을 넘기지 않는다.
        return PublishResult("error", message="발행 전 검증 실패: " + "; ".join(problems))
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    last = ""
    for _attempt in range(remote_claims.CAS_RETRIES):
        tip, state = _remote_tip(root)
        if tip is None:
            return PublishResult(state, message="harness-reports 조회 실패")
        try:
            commit = _build_commit(root, payload, f"isolation report {report['generated_at']}")
        except RuntimeError as exc:
            return PublishResult("error", message=str(exc))
        push = remote_claims._git(
            root,
            "push",
            "--quiet",
            # tip이 빈 문자열이면 "브랜치가 아직 없어야 한다"는 기대값 — 최초 발행.
            f"--force-with-lease={REPORTS_REF}:{tip}",
            "origin",
            f"{commit}:{REPORTS_REF}",
            timeout=_PUSH_TIMEOUT,
        )
        if push.returncode == 0:
            return PublishResult("ok", commit=commit)
        last = (push.stderr or "").strip()
        kind = remote_claims._classify_failure(push.stderr or "")
        if kind != "lease":
            return PublishResult(kind, message=last)
    return PublishResult("error", message=f"CAS 재시도 {remote_claims.CAS_RETRIES}회 초과: {last}")


# ──────────────────────────────────────────────────────────────────────────
# 소비 (③소비 지점 — cmd_brief가 부른다)
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class ReportFetch:
    """리포트 조회 결과. `state`가 `ok`일 때만 `report`가 있다."""

    state: str  # ok | absent | corrupt | unreachable
    report: dict[str, Any] | None = None
    detail: str = ""  # 비-ok 사유 — 예외 타입명 포함


def fetch_report(root: Path, *, now: datetime | None = None) -> ReportFetch:
    """원격 리포트를 읽어 4상태로 분류한다. **절대 raise하지 않는다**(훅 진입점).

    shallow 클론에서도 성립한다 — 리포트 브랜치는 부모 없는 루트 커밋 1개이고 `--depth`를 주지
    않으므로(주면 full 클론이 shallow로 바뀐다) 클론 종류와 무관하다.
    """
    now = now or datetime.now(timezone.utc)
    try:
        tip, state = _remote_tip(root)
        if tip is None:
            return ReportFetch(STATE_UNREACHABLE, detail=f"ls-remote 실패({state})")
        if not tip:
            return ReportFetch(STATE_ABSENT, detail=f"원격에 {REPORTS_BRANCH} 브랜치가 없다")
        fetched = remote_claims._git(
            root,
            "fetch",
            "--quiet",
            "--force",
            "origin",
            f"+{REPORTS_REF}:{LOCAL_MIRROR_REF}",
            timeout=_FETCH_TIMEOUT,
        )
        if fetched.returncode != 0:
            kind = remote_claims._classify_failure(fetched.stderr or "")
            return ReportFetch(STATE_UNREACHABLE, detail=f"fetch 실패({kind})")
        shown = remote_claims._git(
            root, "show", f"{LOCAL_MIRROR_REF}:{REPORT_FILE}", timeout=_FETCH_TIMEOUT
        )
        if shown.returncode != 0 or shown.stdout is None:
            return ReportFetch(STATE_CORRUPT, detail=f"{REPORT_FILE} 파일이 브랜치 트리에 없다")
        try:
            data = json.loads(shown.stdout)
        except json.JSONDecodeError as exc:
            return ReportFetch(STATE_CORRUPT, detail=f"JSONDecodeError: {exc.msg}")
        problems = validate_report(data, now=now)
        if problems:
            return ReportFetch(STATE_CORRUPT, detail="스키마 위반: " + "; ".join(problems[:3]))
        return ReportFetch(STATE_OK, report=data)
    except Exception as exc:  # 훅 진입점 — 어떤 실패도 브리핑을 막지 않는다. 타입명은 반드시 남긴다
        return ReportFetch(STATE_UNREACHABLE, detail=f"{type(exc).__name__}: {exc}")


@dataclass
class BriefIsolation:
    """`render_brief`에 넘길 값 묶음 — 리포트 조회 결과를 브리핑 어휘로 번역한 것."""

    stale_branches: list[tuple[Any, ...]] = field(default_factory=list)
    status: str = "ok"
    message: str = ""
    source_line: str = ""
    pr_state_lookup_ok: bool = True
    pr_state_lookup_error: str = ""


# 미측정 사유별 처방 — 상태마다 **달라야** 한다(같은 문구면 상태를 나눈 의미가 없다).
_UNMEASURED_HINT = {
    STATE_ABSENT: "CI 야간 리포트가 아직 한 번도 발행되지 않았다 — harness-audit의 "
    "isolation-scan 잡을 실행(workflow_dispatch)해야 한다",
    STATE_CORRUPT: "CI 야간 리포트가 손상됐다 — isolation-scan 잡 점검 필요",
    STATE_UNREACHABLE: "CI 야간 리포트를 읽지 못했다(네트워크) — 재시도",
}


def _unmeasured(fetched: ReportFetch, local_status: str, local_message: str) -> BriefIsolation:
    """리포트를 못 쓰는 경우 — "고립 0건"이 아니라 **"미측정"** 이라고 말한다.

    status를 `ok`로 올리지 않고 세션 스캔의 원 status(`shallow`)를 유지해, `render_brief`의
    판정 보류 줄이 뜨게 한다. 세션 스캔 쪽 복구 안내(`--unshallow`)도 버리지 않고 잇는다.
    """
    hint = _UNMEASURED_HINT.get(fetched.state, "CI 야간 리포트를 사용할 수 없다")
    parts = [f"고립 브랜치 미측정 — 세션 스캔 불가({local_status})이고 {hint}"]
    if fetched.detail:
        parts.append(fetched.detail)
    if local_message:
        parts.append(f"수동 복구: {local_message}")
    return BriefIsolation(status=local_status, message=" · ".join(parts))


def to_brief(
    fetched: ReportFetch, *, local_status: str, local_message: str = "", now: datetime
) -> BriefIsolation:
    """리포트 조회 결과 → 브리핑 입력.

    `ok`면 라이브 스캔이 낸 것과 **같은 튜플 계약**으로 변환해 기존 렌더 경로를 그대로 탄다.
    비-ok이거나 변환 중 하나라도 어긋나면 미측정으로 돌린다 — 일부만 변환한 목록을
    정상 리포트로 내보내지 않는다.
    """
    if fetched.state != STATE_OK or fetched.report is None:
        return _unmeasured(fetched, local_status, local_message)
    try:
        report = fetched.report
        generated = _parse_dt(report["generated_at"])
        if generated is None:
            raise ValueError("generated_at 해독 불가")
        basis = report["basis"]
        tuples: list[tuple[Any, ...]] = []
        for b in report["branches"]:
            committed = _parse_dt(b["last_commit_at"])
            if committed is None:
                raise ValueError("last_commit_at 해독 불가")
            tuples.append(
                (
                    b["branch"],
                    max((now - committed).total_seconds() / 86400, 0.0),
                    b["ahead"],
                    b["status"],
                    b.get("evidence", ""),
                    b.get("partial_port", ""),
                    b.get("port_scan_error", ""),
                    b.get("impl_new"),
                    b.get("impl_changed"),
                    b.get("impl_scan_error", ""),
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        # 검증을 통과한 리포트에서 여기까지 오면 검증과 소비의 계약이 어긋난 것이다 — 숨기지 않는다.
        broken = ReportFetch(STATE_CORRUPT, detail=f"{type(exc).__name__}: {exc}")
        return _unmeasured(broken, local_status, local_message)

    age_h = max((now - generated).total_seconds() / 3600, 0.0)
    stale_warn = (
        f" ⚠ {STALE_AFTER_HOURS}시간 초과 — 야간 isolation-scan 잡이 멎었을 수 있다(점검 필요)"
        if age_h > STALE_AFTER_HOURS
        else ""
    )
    trunk_sha = str(basis.get("trunk_sha") or "")[:8] or "해시 미상"
    source_line = (
        f"📡 고립 브랜치 {len(tuples)}건 — 세션 스캔 불가({local_status})라 "
        f"CI 야간 리포트로 대체 · "
        f"측정 {generated.strftime('%Y-%m-%d %H:%MZ')}({age_h:.0f}시간 전) · "
        f"기준 {basis.get('trunk_branch') or basis.get('trunk_ref')}@{trunk_sha} · "
        f"측정 이후의 머지·삭제는 미반영{stale_warn}"
    )
    return BriefIsolation(
        stale_branches=tuples,
        status="ok",
        source_line=source_line,
        pr_state_lookup_ok=bool(basis.get("pr_state_lookup_ok", True)),
        pr_state_lookup_error=str(basis.get("pr_state_lookup_error") or ""),
    )


def brief_for_session(root: Path, *, local_status: str, local_message: str = "") -> BriefIsolation:
    """`cmd_brief`의 진입점 — 조회와 번역을 한 번에. 시각 처리를 여기 두어 호출부를 얇게 한다.

    호출 조건은 호출부가 정한다: **세션 스캔이 `shallow`일 때만** 부른다(전체 클론은 라이브
    스캔이 더 신선하고, offline이면 이 조회도 같은 이유로 실패한다).
    """
    now = datetime.now(timezone.utc)
    return to_brief(
        fetch_report(root, now=now), local_status=local_status, local_message=local_message, now=now
    )


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────


def _summary(report: dict[str, Any]) -> str:
    counts = report["counts"]
    body = " · ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "0건"
    return (
        f"고립 스캔 {report['generated_at']} — {body} (스캔 ref {report['basis']['scanned_refs']})"
    )


def cmd_publish(root: Path, args: argparse.Namespace) -> int:
    now = datetime.now(timezone.utc)
    scan = remote_claims.scan_stale_branches(root, days_threshold=args.days)
    if scan.status != "ok":
        # 측정 실패는 통과가 아니다 — 발행하지 않고 잡을 red로 만든다(직전 정상 리포트 보존).
        print(
            f"✖ 스캔 불가({scan.status}): {scan.message}\n"
            "  발행하지 않는다 — 측정 못 한 결과를 '고립 0건'으로 올리면 소비자가 통과로 읽는다.",
            file=sys.stderr,
        )
        return 2
    report = build_report(scan, root=root, days_threshold=args.days, now=now)
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    print(_summary(report))
    if args.dry_run:
        print("(dry-run — 발행하지 않았다)")
        return 0
    result = publish(root, report)
    if result.status != "ok":
        print(f"✖ 발행 실패({result.status}): {result.message}", file=sys.stderr)
        return 1
    print(f"✔ {REPORTS_BRANCH} 발행 완료 — {result.commit[:8]}")
    return 0


_SHOW_EXIT = {STATE_OK: 0, STATE_ABSENT: 3, STATE_CORRUPT: 4, STATE_UNREACHABLE: 5}


def cmd_show(root: Path, args: argparse.Namespace) -> int:
    now = datetime.now(timezone.utc)
    fetched = fetch_report(root, now=now)
    brief = to_brief(fetched, local_status="shallow", now=now)
    if fetched.state == STATE_OK:
        print(brief.source_line)
        print(f"  분류 집계: {_summary(fetched.report or {})}")
    else:
        print(f"[{fetched.state}] {brief.message}")
    return _SHOW_EXIT[fetched.state]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="고립 브랜치 스캔 리포트 발행·조회 (HARN-28)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("publish", help="full clone에서 스캔해 harness-reports에 발행한다")
    p.add_argument("--days", type=int, default=remote_claims.STALE_BRANCH_DEFAULT_DAYS)
    p.add_argument("--out", help="리포트 JSON을 이 경로에도 쓴다(아티팩트 보존용)")
    p.add_argument("--dry-run", action="store_true", help="스캔·직렬화만 하고 발행하지 않는다")
    sub.add_parser("show", help="원격 리포트를 읽어 상태를 보인다")
    args = parser.parse_args(argv)
    root = Path(
        remote_claims._git(Path.cwd(), "rev-parse", "--show-toplevel").stdout.strip() or "."
    )
    return {"publish": cmd_publish, "show": cmd_show}[args.cmd](root, args)


if __name__ == "__main__":
    import _stdio  # 스크립트 실행이면 이 디렉터리가 sys.path[0]이다 (OPS-53)

    # 한국어 Windows의 파이프·리다이렉트는 cp949라 '—'·'📡' 출력에서 UnicodeEncodeError로 죽는다
    _stdio.ensure_utf8_stdio()
    sys.exit(main())
