#!/usr/bin/env python3
"""위헌 심사 래칫 — 차단 사유가 기준선보다 늘면 실패 (CONST-02 · 표준북 11장 래칫).

**왜 래칫인가**: 코딩 헌법을 설치한 첫날부터 위헌 심사(audit.py)는 원본 등록부 차단을 낸다
(제안 경로가 이 저장소 구조와 달라서 — 정정은 Kiki 게이트 `G-const-sources-registry-adopt`의
몫이고 AI는 constitution/ 을 고칠 수 없다). 이 상태에서 "차단 0"을 CI 게이트로 걸면 상시 red라
사람이 게이트를 끄고, 걸지 않으면 헌법이 산문으로 남는다. 그래서 **지금보다 나빠지는 것만**
막는다: 기준선에 없는 차단 사유가 새로 생기면 exit 1.

**왜 개수가 아니라 항목 집합인가**: 개수만 비교하면 하나를 고치는 사이 다른 위반이 새로 생겨도
숫자가 같아 통과한다(바꿔치기). 기준선은 차단 항목 ID 목록을 들고 있고, 목록에 없는 차단이
하나라도 나오면 실패다.

**만료 지점**: 기준선은 줄어드는 방향으로만 갱신된다(`--update-baseline`). 늘리려면 헌법 개정
기록이 필요하다(제11조 ③) — 이 도구는 증가 갱신을 거부한다. 기준선을 0으로 만드는 일은
`G-const-sources-registry-adopt`(원본 등록부 정정 채택)가 소유한다.

사용법
  python3 scripts/constitution/audit_ratchet.py                   # 판정 (CI)
  python3 scripts/constitution/audit_ratchet.py --json            # 판정 + 기계가 읽는 결과
  python3 scripts/constitution/audit_ratchet.py --update-baseline # 기준선 하향 (감소만 허용)
  python3 scripts/constitution/audit_ratchet.py --init            # 기준선 파일이 없을 때 1회

종료 코드: 0 = 기준선 이하 / 1 = 새 차단 사유 또는 증가 갱신 거부 / 2 = 측정 실패
(심사 불가·기준선 없음·단계 불일치 — "0건 통과"로 위장하지 않는다)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "scripts" / "constitution" / "audit.py"
DEFAULT_BASELINE = ROOT / "metrics" / "coding_constitution_audit_baseline.json"
TIMEOUT_SEC = 300


class MeasureError(Exception):
    """측정 자체가 실패했다 — 판정할 수 없다(exit 2)."""


def run_audit(stage: int | None, do_run: bool) -> dict:
    """audit.py를 --json 으로 실행해 결과 dict를 돌려준다. 심사 불가면 MeasureError."""
    if not AUDIT.is_file():
        raise MeasureError(f"audit.py 없음: {AUDIT}")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "audit.json"
        cmd = [sys.executable, str(AUDIT), "--json", str(out)]
        if not do_run:
            cmd.append("--no-run")
        if stage is not None:
            cmd += ["--stage", str(stage)]
        try:
            proc = subprocess.run(
                cmd,
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired as exc:
            raise MeasureError(f"audit.py {TIMEOUT_SEC}초 시간 초과") from exc
        if proc.returncode not in (0, 1):
            tail = (proc.stderr or proc.stdout).strip()[-600:]
            raise MeasureError(f"위헌 심사 불가(exit {proc.returncode}): {tail}")
        try:
            data = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MeasureError(f"audit.py JSON 결과를 읽지 못함({type(exc).__name__})") from exc
    if not isinstance(data.get("results"), list) or not data["results"]:
        raise MeasureError("심사 항목 0개 — 등록부를 못 읽었거나 비어 있다(0건 통과 위장 금지)")
    return data


def blocking_items(data: dict) -> list[str]:
    return sorted(r["rule_id"] for r in data["results"] if r.get("blocking"))


def load_baseline(path: Path) -> dict:
    try:
        base = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MeasureError(f"기준선 없음: {path} — 처음 한 번 --init 으로 만든다") from exc
    except json.JSONDecodeError as exc:
        raise MeasureError(f"기준선 JSON 파손: {path} ({type(exc).__name__})") from exc
    for key, kind in (("stage", int), ("blocking", int), ("items", list)):
        if not isinstance(base.get(key), kind):
            raise MeasureError(f"기준선 필드 '{key}' 누락 또는 형식 오류")
    if base["blocking"] != len(base["items"]):
        raise MeasureError("기준선 blocking 수와 items 개수가 다르다(손편집 의심)")
    return base


def judged_at() -> str:
    """판정 기준(커밋 해시·날짜) — 해시 없는 판정은 재현할 수 없다."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        sha = ""
    return f"HEAD {sha or '(해시 미확인)'} · {date.today().isoformat()}"


def write_baseline(path: Path, data: dict, items: list[str], history: list, reason: str) -> None:
    record = {
        "stage": data["stage"],
        "blocking": len(items),
        "items": items,
        "judged_at": judged_at(),
        "note": (
            "코딩 헌법 위헌 심사 래칫 기준선(CONST-02). 감소 방향으로만 갱신된다 — "
            "scripts/constitution/audit_ratchet.py --update-baseline. 0으로 만드는 일은 "
            "게이트 G-const-sources-registry-adopt 가 소유한다."
        ),
        "history": history + [{"blocking": len(items), "judged_at": judged_at(), "reason": reason}],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="위헌 심사 래칫")
    ap.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    ap.add_argument(
        "--stage", type=int, choices=range(1, 7), help="audit.py에 전달할 미리보기 단계"
    )
    ap.add_argument("--run", action="store_true", help="집행 장치를 실제로 실행(기본은 --no-run)")
    ap.add_argument("--update-baseline", action="store_true", help="기준선 하향 갱신(감소만)")
    ap.add_argument("--init", action="store_true", help="기준선 파일이 없을 때 최초 생성")
    ap.add_argument("--json", action="store_true", help="판정 결과를 JSON으로 출력")
    args = ap.parse_args()

    try:
        data = run_audit(args.stage, args.run)
        current = blocking_items(data)
        if args.init:
            if args.baseline.exists():
                print(
                    f"⛔ 기준선이 이미 있다: {args.baseline} — --init 은 최초 1회만",
                    file=sys.stderr,
                )
                return 1
            write_baseline(args.baseline, data, current, [], "최초 생성(--init)")
            print(f"✅ 기준선 생성: 단계 {data['stage']} · 차단 {len(current)}건 → {args.baseline}")
            return 0
        base = load_baseline(args.baseline)
        # 단계 상향은 --update-baseline 으로만 기준선을 옮긴다(아래에서 '새 차단 없음'을 요구).
        # 판정 모드에서 단계가 다르면 다른 눈금의 수치를 비교하지 않는다 — 측정 실패로 멈춘다.
        if base["stage"] != data["stage"] and not args.update_baseline:
            raise MeasureError(
                f"단계 불일치: 기준선 {base['stage']}단계 vs 심사 {data['stage']}단계 — 다른 단계의"
                " 수치를 같은 눈금으로 비교하지 않는다. 단계를 올렸다면 --update-baseline 으로"
                " 기준선을 새 단계로 옮긴다(새 차단 사유가 없을 때만 허용 — 부록 C '한 단계의"
                " 규칙이 모두 준수가 된 뒤 다음 단계로')"
            )
    except MeasureError as exc:
        print(f"⛔ 래칫 측정 실패: {exc}", file=sys.stderr)
        return 2

    new = sorted(set(current) - set(base["items"]))
    fixed = sorted(set(base["items"]) - set(current))
    verdict = {
        "stage": data["stage"],
        "baseline_blocking": base["blocking"],
        "current_blocking": len(current),
        "new_blocking": new,
        "fixed": fixed,
        "judged_at_baseline": base.get("judged_at"),
    }

    if args.update_baseline:
        if new:
            print(
                f"⛔ 기준선 증가 갱신 거부 — 새 차단 {len(new)}건: {new}. 기준선을 늘리려면 "
                "헌법 개정 기록이 필요하다(제11조 ③)",
                file=sys.stderr,
            )
            return 1
        stage_moved = base["stage"] != data["stage"]
        if not fixed and not stage_moved:
            print(f"기준선 변화 없음(차단 {len(current)}건)")
            return 0
        reason = f"하향: 해소 {fixed}" if fixed else ""
        if stage_moved:
            reason = f"단계 이동 {base['stage']}→{data['stage']} (새 차단 없음)" + (
                f" · {reason}" if reason else ""
            )
        write_baseline(args.baseline, data, current, base.get("history", []), reason)
        print(
            f"✅ 기준선 갱신: 단계 {base['stage']}→{data['stage']} · "
            f"차단 {base['blocking']} → {len(current)}건 (해소 {fixed})"
        )
        return 0

    if args.json:
        print(json.dumps(verdict, ensure_ascii=False, indent=1))
    if new:
        print(
            f"⛔ 위헌 심사 래칫 위반 — 기준선에 없는 차단 사유 {len(new)}건: {new}\n"
            f"   (기준선 {base['blocking']}건 · 현재 {len(current)}건 · 단계 {data['stage']})\n"
            "   해결하거나, 해결할 수 없으면 멈추고 사람에게 보고한다(헌법 제10조).",
            file=sys.stderr,
        )
        return 1
    msg = f"✅ 위헌 심사 래칫 통과 — 단계 {data['stage']} · 차단 {len(current)}건"
    msg += f" ≤ 기준선 {base['blocking']}건"
    if fixed:
        msg += f" · 해소 {len(fixed)}건 → --update-baseline 으로 기준선을 낮출 수 있다"
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
