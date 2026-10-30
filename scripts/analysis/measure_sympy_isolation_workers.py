"""SymPy 격리 워커 풀의 상주 메모리 실측 — 운영 용량 판정 근거 (OPS-126 ③).

`sympy_isolation_max_workers`(기본 2)개의 워커 프로세스가 SymPy를 import한 채 상주한다. 서버 워커
(uvicorn 프로세스) 수 × 이 값만큼 프로세스가 뜨므로, 개당 메모리를 **감이 아니라 실측**해 기본값이
배포 형상에 맞는지 판정한다(설정 주석의 옛 추정치 "100~150MB/개"는 이 도구로 정정됐다).

측정 방식: 실제 `IsolatedCallPool`(설정 기본값과 같은 `timeout_s`·`preload`)을 띄워 워커를 모두
기동한 직후와, 서로 다른 무거운 방정식 단계(차수 10~13·약 0.5~3초)를 연속 계산한 뒤의 워커별
RSS(상주 집합)·PSS(공유 페이지를 나눠 센 값)를 읽는다. 워커 pid는 풀의 비공개 집합에서 가져온다 —
풀에 공개 접근자가 없고, 이 도구만 쓰는 값이라 접근자를 코어에 새로 만들지 않았다.

플랫폼: Linux는 `/proc/<pid>/status`·`smaps_rollup`을 읽고, 그 밖에는 `psutil`이 있으면 RSS만 읽는다
(PSS는 Linux 전용). 둘 다 안 되면 **측정 불가로 종료 코드 1**이다 — 못 잰 것을 0MB로 통과시키지
않는다.

사용: `python scripts/analysis/measure_sympy_isolation_workers.py [--workers N] [--rounds R]
[--json 경로]`
종료 코드: 0 = 워커 전원 측정 완료, 1 = 측정 불가 또는 워커 수 불일치(공허 통과 금지).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src" / "backend"))

from whymath_backend.config import Settings  # noqa: E402
from whymath_backend.l3.isolated_call import BudgetExceededError, IsolatedCallPool  # noqa: E402
from whymath_backend.l3.verify_step import verify_step  # noqa: E402

_FAST = ("2*(x+1)", "2*x+2")


def _proc_kb(pid: int, field: str, filename: str) -> int | None:
    """Linux `/proc/<pid>/<filename>`에서 `field: N kB` 값을 읽는다. 없으면 None."""
    try:
        for line in Path(f"/proc/{pid}/{filename}").read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{field}:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def read_memory_mb(pid: int) -> dict[str, float | None]:
    """프로세스 1개의 RSS·PSS(MB). 읽을 수 없는 항목은 None — 0으로 접지 않는다."""
    rss_kb = _proc_kb(pid, "VmRSS", "status")
    pss_kb = _proc_kb(pid, "Pss", "smaps_rollup")
    if rss_kb is None:
        try:  # Linux 밖(Windows·macOS) — psutil이 있을 때만 RSS를 읽는다
            import psutil

            return {"rss_mb": psutil.Process(pid).memory_info().rss / 1048576, "pss_mb": None}
        except Exception as exc:  # 미설치·권한·프로세스 소멸 — 타입명만 남긴다
            print(f"메모리 읽기 실패 pid={pid} ({type(exc).__name__})", file=sys.stderr)
            return {"rss_mb": None, "pss_mb": None}
    return {
        "rss_mb": rss_kb / 1024,
        "pss_mb": pss_kb / 1024 if pss_kb is not None else None,
    }


def _unique_heavy(degree: int) -> tuple[str, str]:
    """프로세스 안에서 *처음 보는* 방정식 단계 — SymPy 캐시 적중으로 빨라지는 것을 막는다."""
    k = time.time_ns() % 1_000_000 + 2
    return f"x^{degree}+{k}*x+1=0", f"x^{degree - 1}+{k}*x+2=0"


def _worker_pids(pool: IsolatedCallPool) -> list[int]:
    return sorted(int(w.process.pid) for w in pool._all)  # 비공개 접근 — 모듈 docstring 참조


async def measure(workers: int, rounds: int) -> dict[str, Any]:
    # 설정 *기본값*을 필드에서 직접 읽는다 — Settings 인스턴스(시크릿 필요)를 만들지 않는다.
    fields = Settings.model_fields
    pool = IsolatedCallPool(
        max_workers=workers,
        timeout_s=fields["sympy_isolation_timeout_s"].get_default(),
        preload=tuple(
            fields["sympy_isolation_preload_modules"].get_default(call_default_factory=True)
        ),
    )
    try:
        # 워커는 동시 호출이 있어야 전원 기동한다(지연 기동) — 워커 수보다 넉넉히 겹쳐 호출한다.
        await asyncio.gather(*[pool.run(verify_step, *_FAST) for _ in range(workers * 3)])
        pids = _worker_pids(pool)
        startup = {pid: read_memory_mb(pid) for pid in pids}

        folded = 0
        for i in range(rounds):  # 서로 다른 무거운 입력(차수 10~13)을 한 워커씩 번갈아 먹인다
            try:
                await pool.run(verify_step, *_unique_heavy(10 + (i % 4)))
            except BudgetExceededError:
                folded += 1  # 상한 초과로 워커가 교체되면 pid가 바뀐다 — 아래에서 다시 읽는다
        pids_after = _worker_pids(pool)
        after_heavy = {pid: read_memory_mb(pid) for pid in pids_after}
        return {
            "workers_requested": workers,
            "heavy_rounds": rounds,
            "heavy_rounds_folded": folded,
            "parent": read_memory_mb(os.getpid()),
            "startup": {str(pid): mem for pid, mem in startup.items()},
            "after_heavy": {str(pid): mem for pid, mem in after_heavy.items()},
            "pool_stats": pool.stats(),
        }
    finally:
        pool.shutdown()


def _summarize(result: dict[str, Any]) -> dict[str, Any]:
    """워커별 RSS를 합·평균으로 요약한다. 값이 하나라도 None이면 해당 합은 None(측정 불가)."""

    def agg(block: dict[str, dict[str, float | None]]) -> dict[str, float | None]:
        rss = [m["rss_mb"] for m in block.values()]
        pss = [m["pss_mb"] for m in block.values()]
        return {
            "workers": float(len(block)),
            "rss_mb_each_mean": (sum(rss) / len(rss)) if rss and None not in rss else None,  # type: ignore[arg-type]
            "rss_mb_total": sum(rss) if rss and None not in rss else None,  # type: ignore[arg-type]
            "pss_mb_total": sum(pss) if pss and None not in pss else None,  # type: ignore[arg-type]
        }

    return {"startup": agg(result["startup"]), "after_heavy": agg(result["after_heavy"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SymPy 격리 워커 풀 상주 메모리 실측.")
    parser.add_argument("--workers", type=int, default=2, help="워커 수(기본 2 = 설정 기본값).")
    parser.add_argument("--rounds", type=int, default=12, help="무거운 계산 횟수(기본 12).")
    parser.add_argument("--json", default=None, help="결과 JSON 저장 경로(선택).")
    args = parser.parse_args(argv)

    result = asyncio.run(measure(args.workers, args.rounds))
    result["summary"] = _summarize(result)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.json:
        Path(args.json).write_text(text + "\n", encoding="utf-8")

    started = result["summary"]["startup"]
    measured = started["rss_mb_total"] is not None and int(started["workers"]) == args.workers
    if not measured:
        print("측정 불가 — 워커 전원의 RSS를 읽지 못했다(플랫폼·권한).", file=sys.stderr)
    return 0 if measured else 1


if __name__ == "__main__":
    sys.exit(main())
