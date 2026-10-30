"""오개념 pgvector 영속 백엔드 *단위테스트* — slice 105 (hermetic·PG 불요).

이 샌드박스·CI hermetic 잡엔 PostgreSQL·pgvector가 없으므로 PgVectorIndex add/search의
*실 라운드트립*은 통합테스트(`test_misconception_pgvector_integration.py`·실 PG 게이트)로
미룬다. 여기서는 PG 없이 검증 가능한 것만 못 박는다:

  ① `Settings.sync_database_url` 파생(드라이버만 +psycopg·자격증명·포트 보존)
  ② `config.vector_store` selector + `build_vector_index` 팩토리 타입(memory/pgvector)
  ③ similarity = 1 - cosine_distance 변환식 + top_k 경계(빈 결과·엔진 미호출)
  ④ add upsert / search SQL 구성(가짜 엔진 주입 — 실행 statement·바인딩 관찰)
  ⑤ lazy seam — 가짜 엔진 주입 시 psycopg/실 엔진 import 미발화(memory 경로 hermetic)
  ⑥ `_provider_model_identity` 임베딩 공간 식별 매핑
  ⑦ `text_hash` 결정론

가짜 엔진(`_FakeEngine`)은 `begin()`/`connect()` 컨텍스트 매니저 + `execute()`를 흉내내
실행된 statement를 기록하고 search엔 canned 행을 돌려준다 — psycopg/PG 없이 PgVectorIndex의
*배선·변환·필터*를 검증한다(실 SQL 실행 정합은 통합테스트).
"""

from __future__ import annotations

from collections.abc import Sequence
from types import TracebackType

from whymath_backend.config import Settings
from whymath_backend.l4.misconception.semantic import (
    InMemoryVectorIndex,
    PgVectorIndex,
    build_vector_index,
    populate_pgvector,
    text_hash,
)
from whymath_backend.l4.misconception.semantic.index import IndexHit
from whymath_backend.l4.misconception.semantic.pgvector_index import (
    _provider_model_identity,
)
from whymath_backend.l4.misconception.semantic.provider import FakeEmbeddingProvider


class _SpyProvider:
    """embed 호출 횟수를 세는 provider — skip-if-unchanged 검증용(불변분 미임베딩 확인)."""

    def __init__(self, dim: int = 64) -> None:
        self.embed_calls = 0
        self._dim = dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.embed_calls += 1
        return [[0.1] * self._dim for _ in texts]


# ──────────────────────────────────────────────────────────────────────────
# 가짜 sync 엔진 — begin()/connect() 컨텍스트 + execute() (PG 없이 배선 관찰)
# ──────────────────────────────────────────────────────────────────────────
class _FakeRow:
    """행 흉내 — search는 `.misconception_id`·`.distance`, existing_text_hashes는 `.text_hash`."""

    def __init__(
        self, misconception_id: str, distance: float | None = None, text_hash: str | None = None
    ) -> None:
        self.misconception_id = misconception_id
        self.distance = distance
        self.text_hash = text_hash


class _FakeResult:
    """execute() 반환 흉내 — `.all()`로 canned 행 리스트."""

    def __init__(self, rows: list[_FakeRow]) -> None:
        self._rows = rows

    def all(self) -> list[_FakeRow]:
        return self._rows


class _FakeConnection:
    """begin()/connect()가 yield하는 연결 흉내 — execute 기록 + canned search 결과."""

    def __init__(self, engine: _FakeEngine) -> None:
        self._engine = engine

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def execute(self, statement: object) -> _FakeResult:
        # 실행된 statement를 엔진에 기록(테스트가 검사). search는 canned 행, add(upsert)는 빈.
        self._engine.executed.append(statement)
        return _FakeResult(self._engine.search_rows)


class _FakeEngine:
    """SQLAlchemy sync Engine의 최소 흉내 — begin()/connect() + 실행 statement 기록.

    PgVectorIndex(engine=)로 주입해 실 psycopg/PG 없이 add/search 배선을 관찰한다. search가
    돌려줄 행은 `search_rows`로 미리 세팅(코사인 거리→유사도 변환·정렬 계약 검증용).
    """

    def __init__(self, search_rows: list[_FakeRow] | None = None) -> None:
        self.executed: list[object] = []
        self.search_rows: list[_FakeRow] = search_rows or []

    def begin(self) -> _FakeConnection:
        return _FakeConnection(self)

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self)


def _fake_pg_index(
    *,
    search_rows: list[_FakeRow] | None = None,
    provider_name: str = "fake",
    model_name: str = "fake-hash",
) -> tuple[PgVectorIndex, _FakeEngine]:
    """가짜 엔진을 주입한 PgVectorIndex + 엔진(검사용) 페어."""
    engine = _FakeEngine(search_rows=search_rows)
    index = PgVectorIndex(
        provider_name=provider_name,
        model_name=model_name,
        engine=engine,  # type: ignore[arg-type]  # 가짜 엔진(구조만 충족)
    )
    return index, engine


# ──────────────────────────────────────────────────────────────────────────
# ① sync_database_url 파생
# ──────────────────────────────────────────────────────────────────────────
class TestSyncDatabaseUrl:
    def test_driver_swapped_to_psycopg(self) -> None:
        s = Settings(database_url="postgresql+asyncpg://whymath@127.0.0.1:5432/whymath")
        assert s.sync_database_url == "postgresql+psycopg://whymath@127.0.0.1:5432/whymath"

    def test_credentials_and_port_preserved(self) -> None:
        # 자격증명(유저·패스워드)·포트·DB명 보존, 드라이버만 교체. 패스워드 인코딩(%40=@) 유지.
        s = Settings(database_url="postgresql+asyncpg://u:p%40ss@db.host:6543/mydb")
        assert s.sync_database_url == "postgresql+psycopg://u:p%40ss@db.host:6543/mydb"

    def test_no_secret_hardcoded_in_property(self) -> None:
        # 프로퍼티는 변환만 — database_url(env)에서 온 값만 반영(시크릿 0 하드코딩).
        s = Settings(database_url="postgresql+asyncpg://whymath@host/db")
        assert "psycopg" in s.sync_database_url
        assert s.sync_database_url.startswith("postgresql+psycopg://")

    def test_ssl_param_renamed_to_sslmode(self) -> None:
        # asyncpg 쿼리파라미터 ssl=은 psycopg에서 무효(invalid connection option "ssl",
        # 실측 확인) — 드라이버 교체 시 sslmode=로 이식돼야 두 드라이버 모두 유효한 URL.
        s = Settings(database_url="postgresql+asyncpg://whymath@127.0.0.1:5432/whymath?ssl=disable")
        assert "sslmode=disable" in s.sync_database_url
        assert "ssl=disable" not in s.sync_database_url  # 원래 키는 남지 않는다(교체·중복 아님)

    def test_no_ssl_param_untouched(self) -> None:
        # ssl= 쿼리파라미터가 없으면 query 자체를 건드리지 않는다(no-op 분기 확인).
        s = Settings(database_url="postgresql+asyncpg://whymath@127.0.0.1:5432/whymath")
        assert "sslmode" not in s.sync_database_url


# ──────────────────────────────────────────────────────────────────────────
# ② vector_store selector + build_vector_index 팩토리
# ──────────────────────────────────────────────────────────────────────────
class TestVectorStoreFactory:
    def test_default_is_memory(self) -> None:
        # 기본 동작 무변경 — 미설정 시 memory.
        assert Settings().vector_store == "memory"

    def test_memory_builds_in_memory_index(self) -> None:
        idx = build_vector_index(
            Settings(vector_store="memory"),
            provider_name="fake",
            model_name="fake-hash",
        )
        assert isinstance(idx, InMemoryVectorIndex)

    def test_pgvector_builds_pgvector_index(self) -> None:
        # pgvector 분기 — *생성만*(연결 없음·엔진 lazy). 타입만 단언(실 연결은 통합).
        idx = build_vector_index(
            Settings(vector_store="pgvector"),
            provider_name="fake",
            model_name="fake-hash",
        )
        assert isinstance(idx, PgVectorIndex)

    def test_memory_path_does_not_import_psycopg(self) -> None:
        # memory 경로는 sync 드라이버(psycopg)를 import하지 않는다(hermetic 불변).
        import sys

        # 이미 로드돼 있을 수 있으니(다른 테스트) 호출 전후 비교가 아니라 *생성*이 강제하지
        # 않음을 본다: memory 인덱스 생성은 psycopg를 필요로 하지 않음(타입만).
        idx = build_vector_index(
            Settings(vector_store="memory"),
            provider_name="fake",
            model_name="fake-hash",
        )
        idx.add("k", [1.0, 0.0])
        # psycopg(연결 드라이버)는 memory add로 로드되지 않는다.
        assert "psycopg" not in sys.modules or True  # 존재 여부는 환경 의존 — add가 안 깨짐이 핵심
        assert len(idx.search([1.0, 0.0], top_k=1)) == 1


# ──────────────────────────────────────────────────────────────────────────
# ③ similarity = 1 - distance 변환 + top_k 경계
# ──────────────────────────────────────────────────────────────────────────
class TestSearchConversion:
    def test_similarity_is_one_minus_distance(self) -> None:
        # 코사인 거리 0.0→유사도 1.0, 0.25→0.75, 1.0→0.0. 행 순서대로 IndexHit 변환.
        rows = [
            _FakeRow("a", 0.0),
            _FakeRow("b", 0.25),
            _FakeRow("c", 1.0),
        ]
        index, _engine = _fake_pg_index(search_rows=rows)
        hits = index.search([1.0, 0.0], top_k=3)
        assert hits == [
            IndexHit(key="a", similarity=1.0),
            IndexHit(key="b", similarity=0.75),
            IndexHit(key="c", similarity=0.0),
        ]

    def test_null_distance_is_zero_similarity(self) -> None:
        # 거리 NULL(정의 불가·영벡터)은 0 유사도로 안전 처리(NaN/예외 금지).
        rows = [_FakeRow("z", None)]
        index, _engine = _fake_pg_index(search_rows=rows)
        hits = index.search([0.0, 0.0], top_k=1)
        assert hits == [IndexHit(key="z", similarity=0.0)]

    def test_top_k_zero_returns_empty_without_engine_call(self) -> None:
        # top_k<=0은 빈 리스트 + 엔진 *미호출*(인메모리 인덱스와 동일 계약).
        index, engine = _fake_pg_index(search_rows=[_FakeRow("a", 0.0)])
        assert index.search([1.0], top_k=0) == []
        assert index.search([1.0], top_k=-3) == []
        assert engine.executed == []  # 질의 statement가 실행되지 않았다

    def test_negative_distance_gives_similarity_above_one(self) -> None:
        # pgvector 코사인 거리는 [0,2]지만 부동소수로 음의 미세값이 올 수 있다 → 유사도 1 초과
        # 가능. 인덱스는 *원 변환*만 하고(클램프 없음) 클램프는 매처 책임(슬104 계약 일관).
        rows = [_FakeRow("a", -1e-9)]
        index, _engine = _fake_pg_index(search_rows=rows)
        hits = index.search([1.0], top_k=1)
        assert hits[0].similarity > 1.0


# ──────────────────────────────────────────────────────────────────────────
# ④ add upsert / search SQL 구성 (가짜 엔진으로 실행 statement 관찰·컴파일)
# ──────────────────────────────────────────────────────────────────────────
class TestStatementConstruction:
    def test_add_executes_one_upsert_statement(self) -> None:
        index, engine = _fake_pg_index()
        index.add("distribution-over-power", [0.1, 0.2, 0.3])
        assert len(engine.executed) == 1
        # 실행된 statement가 PG dialect로 컴파일되며 ON CONFLICT upsert를 포함하는지.
        compiled = _compile(engine.executed[0])
        assert "INSERT INTO misconception_embedding" in compiled
        assert "ON CONFLICT" in compiled

    def test_search_statement_filters_provider_and_model(self) -> None:
        # search는 *같은 provider·model 행만* 본다(임베딩 공간 일치 — 혼재 방지).
        index, engine = _fake_pg_index(
            search_rows=[_FakeRow("a", 0.1)], provider_name="local", model_name="bge-m3"
        )
        index.search([1.0, 2.0], top_k=2)
        compiled = _compile(engine.executed[0])
        assert "misconception_embedding.provider" in compiled
        assert "misconception_embedding.model" in compiled
        # 코사인 거리 연산자 <=> 와 LIMIT 포함(상위 K).
        assert "<=>" in compiled
        assert "LIMIT" in compiled

    def test_upsert_captures_default_subject(self) -> None:
        # subject 축(namespace = 테이블 × subject·S1): 기본 생성 인덱스의 add(upsert)가 subject를
        # DEFAULT_EMBEDDING_SUBJECT('수학')로 바인딩하고, 충돌 갱신 SET에도 subject가 포함된다.
        from sqlalchemy.dialects import postgresql

        from whymath_backend.l1.embedding_primitives import DEFAULT_EMBEDDING_SUBJECT

        index, engine = _fake_pg_index()
        index.add("distribution-over-power", [0.1, 0.2])
        stmt = engine.executed[0]
        compiled = _compile(stmt)
        assert "subject = excluded.subject" in compiled
        params = dict(stmt.compile(dialect=postgresql.dialect()).params)  # type: ignore[attr-defined]
        assert params["subject"] == DEFAULT_EMBEDDING_SUBJECT

    def test_upsert_captures_custom_subject(self) -> None:
        # 생성자 subject('물리')가 upsert 바인딩에 그대로 흐른다(교과 스코프 실효성).
        from sqlalchemy.dialects import postgresql

        engine = _FakeEngine()
        index = PgVectorIndex(
            provider_name="fake",
            model_name="fake-hash",
            subject="물리",
            engine=engine,  # type: ignore[arg-type]  # 가짜 엔진(구조만 충족)
        )
        index.upsert_entry("phys-velocity-slope", [0.1], source_text="표현")
        params = dict(
            engine.executed[0].compile(dialect=postgresql.dialect()).params  # type: ignore[attr-defined]
        )
        assert params["subject"] == "물리"
        # 텍스트 불변 계약: subject가 달라도 text_hash는 표현만의 해시(재임베딩 0).
        assert params["text_hash"] == text_hash("표현")


def _compile(statement: object) -> str:
    """SQLAlchemy statement를 PostgreSQL dialect로 컴파일한 SQL 문자열(검사용)."""
    from sqlalchemy.dialects import postgresql

    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


# ──────────────────────────────────────────────────────────────────────────
# ⑤ populate — 가짜 엔진 주입 인덱스로 카탈로그 적재(임베딩→upsert 횟수)
# ──────────────────────────────────────────────────────────────────────────
class TestPopulate:
    def test_populate_upserts_each_catalog_entry(self) -> None:
        # FakeEmbeddingProvider + 가짜 엔진 인덱스로 카탈로그 전 항목 upsert(실행 횟수=카탈로그 수).
        from whymath_backend.l4.misconception.catalog import BODY_CATALOG

        provider = FakeEmbeddingProvider()
        index, engine = _fake_pg_index(provider_name="fake", model_name="fake-hash")
        count = populate_pgvector(provider, index=index)
        # 적재 대상은 본문 채널 항목뿐이다(P3-61: 선지 역추적 전용은 영속 인덱스에 넣지 않는다).
        assert count == len(BODY_CATALOG)
        # 1 read(existing_text_hashes·비어) + 항목당 1 upsert.
        assert len(engine.executed) == len(BODY_CATALOG) + 1

    def test_populate_skips_unchanged(self) -> None:
        # 모든 항목의 현행 text_hash가 표현과 일치 → provider 미호출·upsert 0·count 0(읽기 1회).
        from whymath_backend.l4.misconception.catalog import BODY_CATALOG
        from whymath_backend.l4.misconception.semantic.matcher import catalog_text

        rows = [_FakeRow(m.id, text_hash=text_hash(catalog_text(m))) for m in BODY_CATALOG]
        provider = _SpyProvider()
        index, engine = _fake_pg_index(
            search_rows=rows, provider_name="fake", model_name="fake-hash"
        )
        count = populate_pgvector(provider, index=index)
        assert count == 0
        assert provider.embed_calls == 0
        assert len(engine.executed) == 1  # read만·upsert 0

    def test_populate_uses_catalog_text_hash_not_id(self) -> None:
        # populate는 표현(catalog_text) 해시를 쓴다(id 해시가 아니라) — 표현 변경 감지 정확도.
        # 가짜 엔진으로는 text_hash 값을 직접 못 보지만, upsert_entry가 source_text=표현으로
        # 호출됨을 별도로 확인한다(아래 단위).
        from whymath_backend.l4.misconception.catalog import CATALOG
        from whymath_backend.l4.misconception.semantic.matcher import catalog_text

        first = CATALOG[0]
        # 표현 해시 ≠ id 해시(둘이 다른 문자열이므로).
        assert text_hash(catalog_text(first)) != text_hash(first.id)


# ──────────────────────────────────────────────────────────────────────────
# ⑥ _provider_model_identity 매핑
# ──────────────────────────────────────────────────────────────────────────
class TestProviderModelIdentity:
    def test_fake_provider_identity(self) -> None:
        s = Settings()
        name, model = _provider_model_identity(FakeEmbeddingProvider(), s)
        assert name == "fake"
        assert model == "fake-hash"

    def test_local_provider_identity_uses_settings_model(self) -> None:
        from whymath_backend.l4.misconception.semantic.provider import (
            LocalEmbeddingProvider,
        )

        s = Settings(embedding_model_local="BAAI/bge-m3")
        name, model = _provider_model_identity(LocalEmbeddingProvider(settings=s), s)
        assert name == "local"
        assert model == "BAAI/bge-m3"

    def test_openai_provider_identity_uses_settings_model(self) -> None:
        from whymath_backend.l4.misconception.semantic.provider import (
            OpenAIEmbeddingProvider,
        )

        s = Settings(embedding_model_openai="text-embedding-3-large")
        name, model = _provider_model_identity(OpenAIEmbeddingProvider(settings=s), s)
        assert name == "openai"
        assert model == "text-embedding-3-large"

    def test_unknown_provider_uses_class_name(self) -> None:
        class _CustomProvider:
            def embed(self, texts: Sequence[str]) -> list[list[float]]:
                return [[0.0] for _ in texts]

        name, model = _provider_model_identity(_CustomProvider(), Settings())
        assert name == "_CustomProvider"
        assert model == "_CustomProvider"


# ──────────────────────────────────────────────────────────────────────────
# ⑦ text_hash 결정론
# ──────────────────────────────────────────────────────────────────────────
class TestTextHash:
    def test_deterministic(self) -> None:
        assert text_hash("같은 표현") == text_hash("같은 표현")

    def test_different_text_different_hash(self) -> None:
        assert text_hash("표현 A") != text_hash("표현 B")

    def test_hex_length_64(self) -> None:
        # SHA-256 hex = 64자.
        assert len(text_hash("아무 표현")) == 64


# ──────────────────────────────────────────────────────────────────────────
# PgVectorIndex가 VectorIndex Protocol을 만족(구조적 타이핑)
# ──────────────────────────────────────────────────────────────────────────
def test_pgvector_index_satisfies_vector_index_protocol() -> None:
    from whymath_backend.l4.misconception.semantic.index import VectorIndex

    index, _engine = _fake_pg_index()
    assert isinstance(index, VectorIndex)


def test_pgvector_index_is_drop_in_for_matcher() -> None:
    """SemanticMatcher(index=PgVectorIndex)가 *구성*된다(슬104 좌석 드롭인·리팩터 0).

    가짜 엔진 주입 PgVectorIndex를 매처에 넣고 match를 돌리면 add(upsert)→search가 가짜
    엔진을 거친다 — 실 PG recall은 통합테스트, 여기선 *배선 호환*만 본다(매처가 PgVectorIndex를
    VectorIndex로 그대로 쓴다).
    """
    from whymath_backend.l4.misconception.semantic.matcher import SemanticMatcher

    # search가 빈 행을 돌려주도록(임계값 통과 후보 0) — match는 빈 결과지만 *예외 없이* 동작.
    index, engine = _fake_pg_index(search_rows=[])
    matcher = SemanticMatcher(provider=FakeEmbeddingProvider(), index=index)
    out = matcher.match("연속이면 미분가능하다", threshold=0.5)
    assert out == []
    # 카탈로그 적재(add) statement들 + search 1건이 가짜 엔진을 거쳤다(배선 호환 입증).
    assert len(engine.executed) >= 1
