"""골든 전용 DB 엔진 — 옛 `whymath_backend.db.session.get_engine`의 NullPool 분기 복사본(S20A).

왜 복사했나(전이 의존 절단 · 개정판 S20+1)
- 골든은 옛 `get_engine`을 `db_disable_pool=True` 사본 설정으로만 불렀다(S4 · store.py) — 즉
  NullPool 분기 하나만 쓴다.
- 그런데 `whymath_backend.db.session`을 import하면 패키지 `whymath_backend/db/__init__.py`가
  ORM 모델 전체를 import해 옛 모듈 102개(`db` 64 · `schema` 35 · 기타 3)가 함께 끌려왔다(실측).
  이 한 줄 때문에 골든이 쓰는 옛 모듈이 120개였다.
- 그래서 그 분기만 여기로 복사하고 원본 import를 지운다(HARVEST.md "복사: 의존 과다").

연결 주소는 지금처럼 옛 설정(`whymath_backend.config.get_settings().database_url` —
환경변수 `WHYMATH_DATABASE_URL`)에서 읽는다. config는 LLM 라우터 경로가 어차피 쓰므로
복사해도 줄어드는 모듈이 0개다(S20A 실측) — 설정 해석 규칙(기본값·.env)을 두 벌로 만들지 않는다.

원본과 같은 동작인지는 `tests/golden/characterization/test_s20a_db.py`가 입력 10개로 고정한다.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from whymath_backend.config import get_settings

# 첫 호출에서 만든 엔진을 기억한다(원본과 같은 "첫 호출이 이긴다" 캐시)
_engine: AsyncEngine | None = None


def build_engine(database_url: str) -> AsyncEngine:
    """주소 하나로 연결 풀 없는(NullPool) async 엔진을 만든다.

    원본 `get_engine`의 `db_disable_pool=True` 분기와 같은 호출이다. 엔진 생성은 풀만 준비하므로
    살아 있는 PostgreSQL이 없어도 된다(실제 연결은 첫 쿼리에서).
    NullPool인 이유: `with` 없는 TestClient가 요청마다 새 이벤트 루프를 만들어, 풀에 남은
    asyncpg 연결이 죽은 루프에 묶여 다음 요청에서 터진다(S4).
    """
    return create_async_engine(database_url, poolclass=NullPool)


def get_engine() -> AsyncEngine:
    """골든 프로세스의 엔진을 돌려준다. 처음 부를 때 옛 설정의 주소로 만든다."""
    global _engine
    if _engine is None:
        _engine = build_engine(get_settings().database_url)
    return _engine
