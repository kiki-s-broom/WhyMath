"""골든 패스 전용 설정 — 옛 `whymath_backend.config.Settings`에서 골든이 쓰는 필드만 복사했다.

S20A(전이 의존 절단): 옛 설정은 2,211줄인데 골든이 읽는 것은 DB 연결 주소 하나다.
옛 모듈을 import하지 않도록 그 필드 하나만 같은 규칙으로 다시 읽는다(HARVEST.md "복사: 의존 과다").

옛 설정과 같게 둔 것(특성화 테스트 `tests/golden/characterization/test_s20a_settings.py`가 고정):
- 환경변수 이름 `WHYMATH_DATABASE_URL`(접두사 `WHYMATH_` · 대소문자 구분 없음)
- 현재 작업 폴더의 `.env` 파일도 읽는다(환경변수가 있으면 환경변수가 이긴다)
- 모르는 키는 무시한다
- 기본값(자격증명 없는 로컬 주소 — 시크릿이 아니다)
- 프로세스에서 한 번만 읽고 재사용한다(`get_settings`)
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GoldenSettings(BaseSettings):
    """골든 패스가 읽는 환경 설정. 필드는 DB 연결 주소 1개뿐이다."""

    model_config = SettingsConfigDict(
        env_prefix="WHYMATH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # 옛 설정용 환경변수(WHYMATH_*)가 같이 있어도 무시한다
    )

    # PostgreSQL 연결 주소(asyncpg 드라이버). 기본값은 옛 설정과 같은 로컬 주소다.
    database_url: str = Field(default="postgresql+asyncpg://whymath@127.0.0.1:5432/whymath")


@lru_cache
def get_settings() -> GoldenSettings:
    """프로세스에서 한 번만 만들어 재사용하는 설정(옛 `get_settings`와 같은 방식)."""
    return GoldenSettings()
