"""Phase 3 지표 CLI를 **DB 읽기 전용 접속**으로 감싸 실행한다 (P3-106 · 운영 DB 실측용).

왜 필요한가
-----------
`python -m whymath_backend.ops.phase3_metrics`의 ⑤ 수집은 코드상 SELECT만 쓴다. 그러나
운영 DB(`whymath-pg`)에서 돌릴 때 "코드를 읽어 보니 쓰기가 없다"는 주장일 뿐 보호가 아니다.
이 실행기는 접속 자체를 PostgreSQL 읽기 전용 세션(`default_transaction_read_only=on`)으로
열어, 어떤 경로든 쓰기를 시도하면 DB가 `ReadOnlySQLTransactionError`로 거부하게 만든다.

실측으로 기각한 두 방법(2026-11-06 P3-106 세션 · 같은 실 PG에서 UPDATE 주입):
  · `PGOPTIONS="-c default_transaction_read_only=on"` — asyncpg는 이 환경 변수를 읽지 않는다.
    주입한 UPDATE가 그대로 성공했다.
  · SQLAlchemy `connect` 이벤트에서 `SET SESSION CHARACTERISTICS … READ ONLY` — 접속 직후
    풀이 롤백하며 설정이 되돌려진다. 역시 UPDATE가 성공했다(변별력 0).
  · 채택: asyncpg `server_settings` — 접속 시작 파라미터로 실리므로 롤백되지 않는다.
    같은 UPDATE가 `ReadOnlySQLTransactionError`로 막혔다.

동작
----
1. 설정의 `database_url`로 엔진을 만들되 `server_settings={"default_transaction_read_only": "on"}`
   을 싣고, `whymath_backend.db.session`의 전역 엔진 자리에 먼저 꽂는다(이후 `get_engine()`은
   이 엔진을 돌려준다).
2. 실행 전에 **스스로 확인한다**: `SHOW transaction_read_only`가 `on`이 아니면 측정하지 않고
   exit 3(실행 오류)로 거부한다. DB에 닿지 못하면 확인을 건너뛰지 않고 그대로 phase3_metrics에
   넘긴다 — 그 경우 ⑤는 phase3_metrics 계약대로 '측정 불가'가 된다(접속 실패는 쓰기가 아니다).
3. 실제로 import된 코드 파일 경로를 `CODE_FILE=`로 출력한다(워크트리 코드가 돌았는지 확인용).
4. 나머지 인자를 그대로 `phase3_metrics.main()`에 넘기고 그 종료 코드를 돌려준다.
5. `--json`을 줬으면 그 파일에서 ⑤ 결과만 뽑아 `P5_SUMMARY=`로 **ASCII 한 줄**을 낸다
   (한국어 Windows 콘솔의 cp949 디코딩을 거쳐도 깨지지 않게 — 세션에 그대로 회신하는 줄).

사용:
    python scripts/ops/phase3_metrics_readonly.py --json out/p3_metrics.json
"""

from __future__ import annotations

import asyncio
import sys

#: 접속 시작 파라미터 — 이 세션의 모든 트랜잭션을 읽기 전용으로 연다.
READ_ONLY_SERVER_SETTINGS = {"default_transaction_read_only": "on"}

#: 읽기 전용 확인 실패 시 종료 코드 — phase3_metrics 의 '실행 오류'(3)와 같다.
EXIT_REFUSED = 3


def install_read_only_engine() -> None:
    """읽기 전용 접속 엔진을 전역 엔진 자리에 꽂는다(이후 get_engine()이 이것을 돌려준다)."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from whymath_backend.config import Settings
    from whymath_backend.db import session as db_session

    db_session._engine = create_async_engine(  # noqa: SLF001 - 전역 엔진 캐시를 의도적으로 선점
        Settings().database_url,
        poolclass=NullPool,
        connect_args={"server_settings": dict(READ_ONLY_SERVER_SETTINGS)},
    )


async def probe_read_only() -> str | None:
    """`SHOW transaction_read_only` 값. DB에 닿지 못하면 None(예외 타입명은 stderr로)."""
    from sqlalchemy import text

    from whymath_backend.db.session import get_engine

    try:
        async with get_engine().connect() as conn:
            value = (await conn.execute(text("SHOW transaction_read_only"))).scalar()
            return str(value)
    except Exception as exc:  # noqa: BLE001 - 접속 실패는 ⑤의 미측정으로 넘긴다
        print(f"[phase3_metrics_readonly] 확인 접속 실패: {type(exc).__name__}", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    install_read_only_engine()
    state = asyncio.run(probe_read_only())
    if state is not None and state != "on":
        print(
            f"READ_ONLY=False — transaction_read_only={state}. 측정하지 않고 거부한다.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    print(f"READ_ONLY={'True' if state == 'on' else 'Unknown(DB 미도달)'}")

    from whymath_backend.ops import phase3_metrics

    print(f"CODE_FILE={phase3_metrics.__file__}")
    args = sys.argv[1:] if argv is None else argv
    code = phase3_metrics.main(args)
    summary = p5_summary(args, code)
    if summary is not None:
        print("P5_SUMMARY=" + summary)
    return code


def p5_summary(args: list[str], exit_code: int) -> str | None:
    """`--json` 파일에서 ⑤만 뽑은 ASCII JSON 한 줄. `--json`이 없거나 못 읽으면 None."""
    import json
    from pathlib import Path

    if "--json" not in args or args.index("--json") + 1 >= len(args):
        return None
    try:
        report = json.loads(Path(args[args.index("--json") + 1]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[phase3_metrics_readonly] 요약 읽기 실패: {type(exc).__name__}", file=sys.stderr)
        return None
    loop = next(
        (m for m in report.get("metrics", []) if m.get("key") == "learning_loop_success"), {}
    )
    picked = {
        "exit_code": exit_code,
        "run_id": report.get("run_id"),
        "observed_at": report.get("observed_at"),
        "sample_basis": report.get("sample_basis"),
        "state": loop.get("state"),
        "met": loop.get("met"),
        "numerator": loop.get("numerator"),
        "denominator": loop.get("denominator"),
        "value": loop.get("value"),
        "target": loop.get("target"),
        "facts": loop.get("facts"),
        "reason": loop.get("reason"),
    }
    return json.dumps(picked, ensure_ascii=True, sort_keys=True)


if __name__ == "__main__":  # pragma: no cover - 엔트리포인트
    raise SystemExit(main())
