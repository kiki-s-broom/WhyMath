"""골든 패스 전용 DB 엔진 — 옛 `whymath_backend.db.session.get_engine`을 복사해 의존을 잘랐다.

S20A(전이 의존 절단): 옛 `db.session`을 import하면 `db/__init__.py`가 ORM 모델 전체를 불러
옛 모듈 102개가 함께 로드된다(실측). 골든은 엔진 하나만 쓰므로 그 함수만 옮겼다
(HARVEST.md "복사: 의존 과다"). 옛 모듈은 import하지 않는다.

옛 코드와 같게 둔 것(특성화 테스트 `tests/golden/characterization/test_s20a_db.py`가 고정):
- 엔진은 처음 부를 때 만들고 그 뒤로는 같은 것을 돌려준다(import만으로는 DB에 접속하지 않는다)
- 연결 풀을 쓰지 않는다(NullPool) — 옛 설정의 `db_disable_pool=True` 경로와 같다.
  TestClient를 `with` 없이 쓰면 요청마다 새 이벤트 루프가 생기고, 풀에 남은 asyncpg 연결은
  죽은 루프에 묶여 다음 요청에서 터진다(S4 실측).

옮기지 않은 것: 세션 팩토리(`get_sessionmaker`)·FastAPI 의존성(`get_session`)·풀 사용 경로 —
골든 저장소(`store.py`)는 엔진에서 직접 연결을 연다.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from golden.settings import get_settings

# 프로세스에 하나뿐인 엔진 — 처음 쓸 때 만들고 재사용한다. dispose_engine()이 비운다.
_engine: AsyncEngine | None = None


def make_engine(database_url: str) -> AsyncEngine:
    """연결 풀 없는 async 엔진을 새로 만든다(접속은 첫 쿼리에서 일어난다)."""
    return create_async_engine(database_url, poolclass=NullPool)


def get_engine() -> AsyncEngine:
    """골든 엔진을 돌려준다. 없으면 설정의 연결 주소로 만든다."""
    global _engine
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
    return _engine


async def dispose_engine() -> None:
    """엔진을 닫고 비운다(테스트·앱 종료용). 다음 get_engine()이 새로 만든다."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
    _engine = None
