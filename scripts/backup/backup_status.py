#!/usr/bin/env python3
"""백업 회차 상태 기록·판정 — 조용한 누락을 관측 가능하게 (OPS-31 acceptance ③).

무엇을 고치나
-------------
`db_backup_dr_runbook.md` §2가 자인한 한계: 백업 스케줄이 **로그온 의존**이라 Kiki가
로그아웃하거나 PC가 꺼져 있으면 회차가 통째 누락되는데, **누락됐다는 사실이 어디에도
남지 않는다**. 백업이 안 도는 것과 백업이 필요 없던 것이 화면에서 같은 모양이다 —
CLAUDE.md "침묵 실패 금지"의 백업 축이다.

이 모듈은 성공 회차마다 상태 파일에 시각을 각인하고(`record`), 그 시각이 너무 오래됐으면
**exit 1**로 알린다(`check`). 누락은 이제 "아무 일도 안 일어남"이 아니라 **판정 가능한 사건**이다.

왜 상태 파일인가(설계 근거)
---------------------------
"마지막 성공 백업 시각"을 백업 *파일 목록*에서 유추할 수도 있다(가장 최신 mtime). 그러나
그 방식은 세 가지를 구분하지 못한다:
  · 백업이 성공했는가 vs 파일이 남아 있을 뿐인가(부분 실패 후 잔존물)
  · 그 산출물이 **암호화됐는가**(오프사이트 반출 가부 — §4-1)
  · 보존 정책이 옛 파일을 지워 목록이 비었을 때 "누락"인가 "정상 정리"인가
그래서 파일 시스템 추론이 아니라 **성공 경로가 스스로 각인**한다.

실패 경로 설계 (CLAUDE.md 2026-08-22)
-------------------------------------
  · 상태 파일 부재는 "정상"이 아니라 **판정 불가**(`never_recorded`) — 0회 기록과
    "오래됨"을 구분한다. 둘 다 exit 1이지만 사유가 다르다.
  · 파싱 실패는 예외 타입명과 함께 보고한다(무타입 경고 금지).
  · 기록은 원자적(tmp -> replace)이라 중단돼도 반쪽 JSON이 남지 않는다.

계층 경계: 순수 파일 I/O. backend·harness를 import하지 않는다(운영 스크립트 격리).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_MAX_AGE_HOURS",
    "BackupStatus",
    "StalenessVerdict",
    "evaluate_staleness",
    "load_status",
    "main",
    "record_success",
]

_EXIT_OK = 0
_EXIT_FAIL = 1

#: 기본 허용 나이 — 주 2회(월·목) 스케줄의 최대 간격 4일 + 여유 1일.
#: 이 값을 늘리면 누락 탐지가 그만큼 늦어진다(트레이드오프를 아는 채로 조정할 것).
DEFAULT_MAX_AGE_HOURS = 120

STATUS_FILENAME = "backup_status.json"


class BackupStatusError(RuntimeError):
    """상태 파일 적재 실패 — 조용한 기본값 대신 던진다."""


@dataclass(frozen=True, slots=True)
class BackupStatus:
    """마지막 성공 회차 1건."""

    last_success_utc: datetime
    artifact: str
    size_bytes: int
    encrypted: bool
    """산출물이 암호화됐는가 — **오프사이트 반출 가부의 판정 입력**(런북 §4-1)."""
    recipients_fingerprint: str | None = None
    """암호화 수신자 식별 단서(공개키 접미 8자) — 어느 키로 잠갔는지 추적용.

    개인키·패스프레이즈는 **절대** 여기 담지 않는다(§4-5 키 분리).
    """
    offsite_requested: bool = False
    """이 회차가 `-OffsiteDir`로 오프사이트 미러를 요청했는가(OPS-64).

    기본값 `False`는 두 경우를 **의도적으로 뭉친다** — ①오프사이트를 아예 안 쓰는
    운용 ②이 필드가 생기기 전에 기록된 옛 상태 파일(`load_status`가 없는 키를
    `False`로 기본 처리). 둘 다 "오프사이트 실패로 판정할 근거가 없다"는 같은
    결론이라 구분할 필요가 없다 — `never_recorded`처럼 별도 사유를 둘 이유가 없다.
    """
    offsite_ok: bool = False
    """오프사이트 미러가 *이 회차에서* 성공했는가. `offsite_requested=False`면 무의미."""
    offsite_destination: str | None = None
    """오프사이트 목적지 경로 — 진단용(어디로 보내려 했는지)."""
    offsite_size_bytes: int | None = None
    """오프사이트 사본의 바이트 수 — 로컬 크기와 대조해 진단할 때 쓴다."""


@dataclass(frozen=True, slots=True)
class StalenessVerdict:
    """신선도 판정 — 통과/미달과 **사유**를 함께."""

    ok: bool
    reason: str
    age_hours: float | None
    """마지막 성공으로부터 경과 시간. `never_recorded`면 None(0이 아니다)."""


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    """tmp -> replace 원자적 기록 — 중단돼도 반쪽 JSON이 남지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def record_success(
    status_path: Path,
    *,
    artifact: str,
    size_bytes: int,
    encrypted: bool,
    recipients_fingerprint: str | None = None,
    offsite_requested: bool = False,
    offsite_ok: bool = False,
    offsite_destination: str | None = None,
    offsite_size_bytes: int | None = None,
    moment: datetime | None = None,
) -> BackupStatus:
    """성공 회차를 각인한다 — 백업 스크립트의 마지막 단계가 호출한다.

    **성공 경로에서만** 호출한다. 실패한 회차가 시각을 갱신하면 신선도 판정이
    "돌긴 돌았다"로 위장되어 이 모듈의 존재 이유가 사라진다.

    `offsite_requested=True, offsite_ok=False`(기본값)로 먼저 쓰고 오프사이트가 실제로
    성공한 뒤에야 `offsite_ok=True`로 다시 쓰는 것이 호출부(PS1)의 계약이다(OPS-64) —
    그래야 오프사이트 단계에서 죽어도 이미 적힌 레코드가 실패를 정직하게 담고 있다.
    """
    stamped = (moment or datetime.now(UTC)).astimezone(UTC)
    status = BackupStatus(
        last_success_utc=stamped,
        artifact=artifact,
        size_bytes=int(size_bytes),
        encrypted=bool(encrypted),
        recipients_fingerprint=recipients_fingerprint,
        offsite_requested=bool(offsite_requested),
        offsite_ok=bool(offsite_ok),
        offsite_destination=offsite_destination,
        offsite_size_bytes=offsite_size_bytes,
    )
    _atomic_write(
        status_path,
        {
            "last_success_utc": stamped.isoformat(timespec="seconds"),
            "artifact": status.artifact,
            "size_bytes": status.size_bytes,
            "encrypted": status.encrypted,
            "recipients_fingerprint": status.recipients_fingerprint,
            "offsite_requested": status.offsite_requested,
            "offsite_ok": status.offsite_ok,
            "offsite_destination": status.offsite_destination,
            "offsite_size_bytes": status.offsite_size_bytes,
        },
    )
    return status


def load_status(status_path: Path) -> BackupStatus | None:
    """상태 파일 적재. 파일 부재는 `None`(= 기록된 적 없음), 손상은 예외.

    **`utf-8-sig`로 읽는 이유(BOM)**: 생산자가 둘이다 — 이 모듈의 `record_success`(BOM 없음)와
    Windows의 `backup_whymath_pg.ps1`. PowerShell 5.1은 `Set-Content -Encoding UTF8`에
    **BOM을 붙인다**. 순수 `utf-8`로 읽으면 실제 스케줄 백업이 만든 상태 파일이 전부
    `JSONDecodeError: Unexpected UTF-8 BOM`으로 죽고, 그러면 **성공한 백업마다 신선도 검사가
    실패**한다 — 누락 탐지기가 정상 상태를 사고로 신고하는, 방향이 반대인 무증상 실패다.
    쓰기 쪽도 BOM 없이 쓰도록 고쳤지만(PS1 `UTF8Encoding $false`), 읽기 쪽이 BOM을 견디는 것이
    본질적 방어다 — 구버전 스크립트가 만든 파일도 읽어야 하고, 읽기 관용성은 잃을 것이 없다.
    `utf-8-sig`는 BOM이 없는 파일도 그대로 읽는다.
    (2026-09-01 PR #968 Codex P1 지적 수용 — 텍스트 동결이 잡지 못하는 축이었다: 계약 테스트가
     *필드명*은 대조했으나 PS1이 쓴 바이트를 파이썬이 읽는 경로는 실행된 적이 없다.)
    """
    if not status_path.exists():
        return None
    try:
        raw = json.loads(status_path.read_text(encoding="utf-8-sig"))
        moment = datetime.fromisoformat(str(raw["last_success_utc"]))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise BackupStatusError(
            f"백업 상태 파일 판독 실패 ({status_path}): {type(exc).__name__}: {exc}"
        ) from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return BackupStatus(
        last_success_utc=moment.astimezone(UTC),
        artifact=str(raw.get("artifact", "")),
        size_bytes=int(raw.get("size_bytes", 0)),
        encrypted=bool(raw.get("encrypted", False)),
        recipients_fingerprint=raw.get("recipients_fingerprint"),
        # 없는 키는 False/None 기본값 — OPS-64 이전에 기록된 상태 파일도 그대로 읽힌다
        # (오프사이트를 안 쓰는 회차와 구분할 수 없지만, 둘 다 "판정 근거 없음"으로 같다).
        offsite_requested=bool(raw.get("offsite_requested", False)),
        offsite_ok=bool(raw.get("offsite_ok", False)),
        offsite_destination=raw.get("offsite_destination"),
        offsite_size_bytes=raw.get("offsite_size_bytes"),
    )


def evaluate_staleness(
    status: BackupStatus | None,
    *,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    now: datetime | None = None,
) -> StalenessVerdict:
    """신선도 판정 — 기록 없음과 오래됨을 **다른 사유로** 구분한다.

    둘 다 exit 1이지만 대처가 다르다: 기록 없음은 "한 번도 안 돌았거나 상태 경로가 다르다",
    오래됨은 "스케줄이 죽었거나 최근 회차가 실패했다". 한 사유로 뭉치면 조사 방향을 잃는다.
    """
    if status is None:
        return StalenessVerdict(False, "never_recorded", None)
    reference = (now or datetime.now(UTC)).astimezone(UTC)
    age_hours = (reference - status.last_success_utc).total_seconds() / 3600.0
    if age_hours > max_age_hours:
        return StalenessVerdict(False, "stale", age_hours)
    return StalenessVerdict(True, "fresh", age_hours)


def evaluate_backup_health(
    status: BackupStatus | None,
    *,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    require_encrypted: bool = False,
    now: datetime | None = None,
) -> StalenessVerdict:
    """신선도 + 암호화 요구를 합친 **단일 판정**.

    왜 합쳤나: 이전 판은 신선도만 판정해 `ok`/`reason`을 만들고, 암호화 위반은 종료코드에서만
    따로 걸렀다. 그러면 `--json --require-encrypted`로 평문 백업을 검사할 때 JSON이
    `{"ok": true, "reason": "fresh"}`인데 exit는 1이 된다 — **같은 실행이 두 개의 다른 답을
    내고**, JSON을 읽는 기계는 반출 금지 산출물을 정상으로 판정한다. 판정을 한 곳에서 만들어
    두 소비자가 같은 것을 보게 한다.
    (2026-09-01 PR #968 Codex P2 지적 수용)

    신선도가 먼저다 — 기록이 없거나 오래됐으면 암호화 여부·오프사이트 여부는 물을 대상이
    없다. 오프사이트 실패(OPS-64)는 `--require-encrypted` 플래그와 무관하게 항상 본다 —
    로컬 백업의 암호화 요구 정책과 오프사이트 미러가 실제로 도착했는가는 별개 사실이다.
    """
    verdict = evaluate_staleness(status, max_age_hours=max_age_hours, now=now)
    if not verdict.ok:
        return verdict
    if status is not None and status.offsite_requested and not status.offsite_ok:
        # backup_whymath_pg.ps1 Step 9(오프사이트 미러)가 실패한 회차 — Step 7이 이미 쓴
        # "성공" 레코드만 보면 이 회차가 정상으로 위장된다(OPS-64 발단 사고). PS1은
        # offsite_ok=False를 먼저 쓰고 미러가 실제로 끝난 뒤에만 True로 다시 쓰므로,
        # 여기 도달했다는 것 자체가 Step 9가 성공적으로 끝나지 못했다는 뜻이다.
        return StalenessVerdict(False, "offsite_failed", verdict.age_hours)
    if require_encrypted and status is not None and not status.encrypted:
        return StalenessVerdict(False, "plaintext_artifact", verdict.age_hours)
    return verdict


# --------------------------------------------------------------------------
# CLI — 판정은 exit 0/1 (게이트 CLI 관례)
# --------------------------------------------------------------------------
def _default_status_path(backup_dir: str) -> Path:
    return Path(backup_dir) / STATUS_FILENAME


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="백업 회차 상태 각인·신선도 판정 (OPS-31 — 조용한 누락 방지)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="성공 회차 각인(백업 스크립트가 호출)")
    rec.add_argument("--backup-dir", required=True)
    rec.add_argument("--artifact", required=True, help="산출물 파일 경로")
    rec.add_argument("--size-bytes", type=int, required=True)
    rec.add_argument(
        "--encrypted",
        choices=("true", "false"),
        required=True,
        help="산출물이 암호화됐는가 — 오프사이트 반출 가부의 입력",
    )
    rec.add_argument("--recipients-fingerprint", default=None)
    rec.add_argument(
        "--offsite-requested",
        choices=("true", "false"),
        default="false",
        help="이 회차가 오프사이트 미러를 요청했는가(OPS-64)",
    )
    rec.add_argument(
        "--offsite-ok",
        choices=("true", "false"),
        default="false",
        help="오프사이트 미러가 이 회차에서 성공했는가",
    )
    rec.add_argument("--offsite-destination", default=None)
    rec.add_argument("--offsite-size-bytes", type=int, default=None)

    chk = sub.add_parser("check", help="신선도 판정(누락 탐지) — exit 0 통과 / 1 미달")
    chk.add_argument("--backup-dir", required=True)
    chk.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS)
    chk.add_argument(
        "--require-encrypted",
        action="store_true",
        help="마지막 산출물이 암호화되지 않았으면 exit 1 — 오프사이트 운용 시 사용",
    )
    chk.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    status_path = _default_status_path(args.backup_dir)

    if args.command == "record":
        status = record_success(
            status_path,
            artifact=args.artifact,
            size_bytes=args.size_bytes,
            encrypted=args.encrypted == "true",
            recipients_fingerprint=args.recipients_fingerprint,
            offsite_requested=args.offsite_requested == "true",
            offsite_ok=args.offsite_ok == "true",
            offsite_destination=args.offsite_destination,
            offsite_size_bytes=args.offsite_size_bytes,
        )
        print(f"[OK] backup status recorded: {status_path} ({status.last_success_utc.isoformat()})")
        return _EXIT_OK

    try:
        status = load_status(status_path)
    except BackupStatusError as exc:
        # 판독 실패를 "신선함"으로 넘기면 상태 파일 손상이 무증상이 된다.
        print(f"[FAIL] {exc}", file=sys.stderr)
        return _EXIT_FAIL

    verdict = evaluate_backup_health(
        status,
        max_age_hours=args.max_age_hours,
        require_encrypted=args.require_encrypted,
    )
    payload = {
        "status_path": str(status_path),
        "ok": verdict.ok,
        "reason": verdict.reason,
        "age_hours": verdict.age_hours,
        "last_success_utc": status.last_success_utc.isoformat() if status else None,
        "encrypted": status.encrypted if status else None,
        "offsite_requested": status.offsite_requested if status else None,
        "offsite_ok": status.offsite_ok if status else None,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if verdict.reason == "never_recorded":
            print(
                f"[FAIL] 백업 성공 기록이 없다 ({status_path}) — 한 번도 안 돌았거나 "
                "상태 경로가 다르다. '0회'와 '오래됨'은 다른 사태다.",
                file=sys.stderr,
            )
        elif verdict.reason == "offsite_failed":
            dest = status.offsite_destination or "목적지 미기록"
            print(
                f"[FAIL] 오프사이트 미러가 이 회차에서 실패했다({dest}) "
                "— 로컬 백업 자체는 유효하지만 반출 사본이 없다(런북 4-3 PIPA 파기창 전제가 "
                f"흔들린다). 기록: {status.last_success_utc.isoformat() if status else '-'}",
                file=sys.stderr,
            )
        elif verdict.reason == "plaintext_artifact":
            print(
                "[FAIL] 마지막 산출물이 평문이다 — 오프사이트 반출 금지(런북 4-1). "
                "recipients.txt를 만든 뒤(런북 1b) 백업을 재실행하라.",
                file=sys.stderr,
            )
        elif verdict.reason == "stale":
            assert verdict.age_hours is not None
            print(
                f"[FAIL] 마지막 성공 백업이 {verdict.age_hours:.1f}시간 전 "
                f"(임계 {args.max_age_hours:.0f}시간 초과) — 스케줄 누락 또는 최근 회차 실패. "
                f"기록: {status.last_success_utc.isoformat() if status else '-'}",
                file=sys.stderr,
            )
        else:
            assert verdict.age_hours is not None and status is not None
            enc = "암호화됨" if status.encrypted else "**평문**"
            print(
                f"[OK] 마지막 성공 백업 {verdict.age_hours:.1f}시간 전 · 산출물 {enc} · "
                f"{status.artifact}"
            )
    return _EXIT_FAIL if not verdict.ok else _EXIT_OK


if __name__ == "__main__":  # pragma: no cover - CLI 진입점
    raise SystemExit(main())
