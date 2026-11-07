"""학생 경로 관문 출력 스냅샷 — A1 변경 전/후 비교용 (PED-17 완료 기준 2).

`concept_content`의 모든 행에 대해 학생 `/study` 경로의 유일한 관문(`resolve_concept_content`)을
호출하고, 결과를 JSON으로 낸다. 변경 전 코드(옛 스키마)와 변경 후 코드(새 스키마)에서 같은 스크립트를
돌려 `diff`로 대조한다 — 다르면 학생 화면이 바뀐 것이다.

비교하는 값(코드별):
  - served     : 학생에게 공급 가능한가(DSL이 반환됐는가)
  - reason     : 공급 불가 사유(NO_DSL·UNREVIEWED) 또는 null
  - content_code / lookup_via : 서빙 행과 찾은 경로
  - dsl_sha256 : 공급된 DSL 본문의 SHA-256 — 본문 한 글자라도 다르면 달라진다

사용(DB URL은 환경변수로 주입 — 자격증명을 코드에 두지 않는다):
    WHYMATH_DATABASE_URL=postgresql+asyncpg://... \
    python ped17/산출물/A1/compare_student_gate.py > before.json

exit code: 0 정상 / 1 DB 접속·조회 실패 (실패를 빈 스냅샷으로 위장하지 않는다)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.config import get_settings
from whymath_backend.l3.interfaces import InMemoryCache
from whymath_backend.l4.content_supply import resolve_concept_content


async def _snapshot() -> dict[str, dict[str, object]]:
    engine = create_async_engine(get_settings().database_url)
    out: dict[str, dict[str, object]] = {}
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            codes = [r[0] for r in (await session.execute(text("SELECT code FROM concept_content ORDER BY code")))]
            for code in codes:
                # 코드마다 새 캐시 — 캐시 적중이 게이트 결과를 가리지 않게 한다.
                res = await resolve_concept_content(code, session=session, cache=InMemoryCache())
                out[code] = {
                    "served": res.dsl is not None,
                    "reason": res.reason,
                    "content_code": res.content_code,
                    "lookup_via": res.lookup_via,
                    "dsl_sha256": (
                        hashlib.sha256(res.dsl.model_dump_json().encode("utf-8")).hexdigest()
                        if res.dsl is not None
                        else None
                    ),
                }
    finally:
        await engine.dispose()
    return out


def main() -> int:
    try:
        snap = asyncio.run(_snapshot())
    except Exception as exc:  # noqa: BLE001 — 실패 원인(타입명)을 남기고 비정상 종료한다.
        print(f"스냅샷 실패: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    json.dump(snap, sys.stdout, ensure_ascii=False, indent=1, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
