"""오개념 의미 매칭 — pgvector 영속 백엔드 (slice 105).

슬104 `VectorIndex` 좌석의 *영속(pgvector) 백엔드*다. 슬104 Protocol이 *동기*(`add`·
`search`)라 이 구현은 *sync SQLAlchemy 엔진*(psycopg3 드라이버)으로 그대로 드롭인된다 —
슬104 매처·Protocol 리팩터 0. 슬98 결정(벡터 DB=pgvector·Postgres 16 통합)의 첫 실 결선.

────────────────────────────────────────────────────────────────────────────
정직 스코프 (CLAUDE.md "확실하지 않을 때 자신 있게 말함 금지")
────────────────────────────────────────────────────────────────────────────
카탈로그 30종엔 **in-memory 선형 스캔(InMemoryVectorIndex)이 최적**이다 — pgvector는 *영속화
+ 스케일 코퍼스 groundwork*이지 30종에서 더 빠른 검색이 아니다(이 테이블엔 HNSW/IVFFlat
인덱스도 두지 않는다 — seq-scan이 최적). 스케일 코퍼스(개념그래프 401+·문제은행·학생 풀이)는
*fixed-dim + HNSW cosine 인덱스*가 정석이고, 그건 이 좌석을 그대로 쓰되 인덱스·차원만 다는
후속이다. PgVectorIndex의 가치는 ① 사전 임베딩을 *프로세스 밖에 영속*(재기동·다중 워커 공유)
② 슬98 pgvector 결정의 실 결선 ③ 스케일 패턴 자리 확보다.

────────────────────────────────────────────────────────────────────────────
sync 엔진 (async 전용 코드베이스에 *벡터 store 좌석에 한정*된 sync 드라이버)
────────────────────────────────────────────────────────────────────────────
앱 본체는 async 전용(asyncpg)이고, 이 모듈만 sync 엔진(psycopg)을 쓴다. 엔진·psycopg import는
*지연*(lazy)이라 모듈 import만으로는 드라이버 로드·연결이 없다(provider.py lazy seam·
session.py lazy 엔진 패턴 미러링). 기본(memory) 경로는 이 모듈을 import하지 않으므로 psycopg
의존이 없다(pgvector 선택 시에만 발화). sync URL은 `Settings.sync_database_url`(async URL에서
드라이버만 `+psycopg`로 파생)에서 오고 자격증명은 코드에 0(env).

7계층: 이 인덱스도 L4 매처가 호출하는 *하위 인프라 좌석*(영속/검색). L4 SemanticMatcher는
이 구현을 모르고 `VectorIndex` Protocol만 본다(인메모리·pgvector 무관).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from whymath_backend.config import Settings, get_settings
from whymath_backend.l1.embedding_primitives import (
    DEFAULT_EMBEDDING_SUBJECT,
    embed_changed,
    text_hash,
)

# 레이어-중립 L1 프리미티브 재사용(역방향 의존 제거) — 표현 해시·skip-if-unchanged 코어·공간 식별자.
# `_provider_model_identity`는 기존 사용처(matcher 지연 import·아래 populate)를 위해 같은 이름으로
# 별칭한다. `text_hash`는 아래 `__all__`로 re-export(기존 import 경로 유지).
from whymath_backend.l1.embedding_primitives import (
    build_sync_engine as _build_sync_engine,
)
from whymath_backend.l1.embedding_primitives import (
    provider_model_identity as _provider_model_identity,
)
from whymath_backend.l4.misconception.catalog import CATALOG, body_detectable
from whymath_backend.l4.misconception.semantic.index import IndexHit
from whymath_backend.l4.misconception.semantic.matcher import catalog_text

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from whymath_backend.l4.misconception.models import Misconception
    from whymath_backend.l4.misconception.semantic.provider import EmbeddingProvider


class PgVectorIndex:
    """pgvector 영속 벡터 인덱스 — `VectorIndex` 구현(slice 104 Protocol·sync 드롭인).

    `add`는 upsert(`INSERT ... ON CONFLICT(misconception_id) DO UPDATE`)로 멱등 적재하고,
    `search`는 코사인 거리(`<=>`)로 상위 후보를 찾는다(`similarity = 1 - distance`). **같은
    임베딩 공간(provider·model) 행만** 비교한다(서로 다른 모델 벡터 혼재 방지). sync 엔진은
    지연 생성·캐시(session.py lazy 엔진 패턴)하고, psycopg 연결마다 pgvector 어댑터를
    등록한다(`register_vector` — vector 바인딩/디코딩).

    provider/model은 *임베딩 공간 식별자*다 — 같은 provider라도 model이 다르면 다른 공간으로
    본다. 호출자(populate·매처)는 add/search에 *같은* provider·model을 일관되게 넘겨야 한다
    (혼용 시 search가 빈 결과 — 같은 공간 행이 없으므로). 차원 불일치는 pgvector가 적재 시점에
    오류로 막는다(컬럼 `vector(N)`).

    `subject`는 임베딩 namespace의 *교과 축*이다(namespace = 테이블 × subject —
    `l1/embedding_primitives.py` 불변식). upsert·search·existing_text_hashes 전부가 이 스코프를
    건다 — 다른 교과 행은 서로 보이지 않는다. 기본값 `DEFAULT_EMBEDDING_SUBJECT`('수학')라
    기존 호출자(populate·matcher)는 무수정으로 수학 스코프를 흡수한다(파라미터 관통 금지).
    """

    def __init__(
        self,
        *,
        provider_name: str,
        model_name: str,
        subject: str = DEFAULT_EMBEDDING_SUBJECT,
        engine: Engine | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._provider_name = provider_name
        self._model_name = model_name
        self._subject = subject
        self._engine = engine
        self._settings = settings

    @property
    def _resolved_settings(self) -> Settings:
        """설정 지연 해석 — 주입 우선, 없으면 캐시된 전역 Settings(provider.py 패턴)."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_engine(self) -> Engine:
        """sync 엔진 지연 해석 — 주입 우선, 없으면 psycopg 격리 엔진 생성(session.py 패턴).

        첫 호출에서 `create_engine(settings.sync_database_url)`로 sync 엔진을 만들고 인스턴스에
        캐시한다(이후 재사용). psycopg/SQLAlchemy import는 *이 시점*에만 일어난다(모듈 import
        깨짐 방지). 각 raw 연결에 pgvector 어댑터를 등록하는 connect 리스너를 건다.
        """
        if self._engine is None:
            self._engine = _build_sync_engine(self._resolved_settings)
        return self._engine

    def add(self, key: str, vector: Sequence[float]) -> None:
        """단일 (키, 벡터) upsert (VectorIndex 구현·멱등).

        `INSERT ... ON CONFLICT(misconception_id) DO UPDATE` — provider/model/dim/text_hash/
        updated_at을 함께 적재한다. 같은 키 재적재는 행을 갱신(멱등). text_hash는 *키 자체*가
        아니라 호출자가 임베딩한 원본 표현의 해시여야 의미가 있으나, add 시그니처(Protocol)는
        (key, vector)뿐이라 여기서는 key를 해시한다 — 표현 단위 stale 감지가 필요하면 populate가
        `upsert_entry`로 표현 해시를 직접 넘긴다(아래).
        """
        self.upsert_entry(key, vector, source_text=key)

    def upsert_entry(self, key: str, vector: Sequence[float], *, source_text: str) -> None:
        """표현(source_text)을 명시한 upsert — text_hash가 *임베딩 원본 표현*을 반영.

        `add`(Protocol)는 source_text=key로 위임하고, populate는 카탈로그 표현(`catalog_text`)을
        넘겨 표현 변경 감지(text_hash)가 정확하도록 한다.
        """
        from sqlalchemy import func
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from whymath_backend.db.models.misconception_embedding import MisconceptionEmbedding

        values = list(float(x) for x in vector)
        stmt = pg_insert(MisconceptionEmbedding).values(
            misconception_id=key,
            embedding=values,
            provider=self._provider_name,
            model=self._model_name,
            subject=self._subject,
            dim=len(values),
            text_hash=text_hash(source_text),
        )
        # PK 충돌 시 갱신 — updated_at은 now()로 새로 찍는다(server_default는 INSERT 전용).
        stmt = stmt.on_conflict_do_update(
            index_elements=[MisconceptionEmbedding.misconception_id],
            set_={
                "embedding": stmt.excluded.embedding,
                "provider": stmt.excluded.provider,
                "model": stmt.excluded.model,
                "subject": stmt.excluded.subject,
                "dim": stmt.excluded.dim,
                "text_hash": stmt.excluded.text_hash,
                "updated_at": func.now(),
            },
        )
        with self._get_engine().begin() as conn:
            conn.execute(stmt)

    def search(self, vector: Sequence[float], *, top_k: int) -> list[IndexHit]:
        """질의 벡터에 대한 코사인 상위 top_k IndexHit(유사도 내림차순, VectorIndex 구현).

        `1 - (embedding <=> :q)`(코사인 거리→유사도)로 점수를 내고 *같은 provider·model 행만*
        본다(임베딩 공간 일치). top_k<=0이면 빈 리스트(인메모리 인덱스와 동일 계약). 거리
        오름차순 = 유사도 내림차순으로 정렬·LIMIT.
        """
        if top_k <= 0:
            return []
        from sqlalchemy import select

        from whymath_backend.db.models.misconception_embedding import MisconceptionEmbedding

        query = list(float(x) for x in vector)
        distance = MisconceptionEmbedding.embedding.cosine_distance(query)
        stmt = (
            select(
                MisconceptionEmbedding.misconception_id,
                distance.label("distance"),
            )
            .where(
                MisconceptionEmbedding.provider == self._provider_name,
                MisconceptionEmbedding.model == self._model_name,
                # 교과 스코프 — 다른 subject 행은 랭킹에 안 잡힌다(namespace 불변식).
                MisconceptionEmbedding.subject == self._subject,
            )
            .order_by(distance)
            .limit(top_k)
        )
        with self._get_engine().connect() as conn:
            rows = conn.execute(stmt).all()
        # similarity = 1 - cosine_distance. pgvector cosine distance ∈ [0, 2] → similarity ∈
        # [-1, 1](인메모리 코사인과 같은 축). NULL 거리(영벡터 등 정의 불가)는 0 유사도로 안전.
        return [
            IndexHit(
                key=row.misconception_id,
                similarity=(1.0 - float(row.distance)) if row.distance is not None else 0.0,
            )
            for row in rows
        ]

    def existing_text_hashes(self, keys: Sequence[str]) -> dict[str, str]:
        """주어진 misconception_id들의 *현행* text_hash 조회 — {key: text_hash}(단일 SELECT).

        같은 임베딩 공간(provider·model)의 행만 본다(다른 공간은 재임베딩 필요라 미포함=변경 취급).
        populate skip-if-unchanged용(concept/atom embedding 동형). 빈 입력은 쿼리 없이 {}.
        """
        if not keys:
            return {}
        from sqlalchemy import select

        from whymath_backend.db.models.misconception_embedding import MisconceptionEmbedding

        stmt = select(
            MisconceptionEmbedding.misconception_id, MisconceptionEmbedding.text_hash
        ).where(
            MisconceptionEmbedding.misconception_id.in_(list(dict.fromkeys(keys))),
            MisconceptionEmbedding.provider == self._provider_name,
            MisconceptionEmbedding.model == self._model_name,
            # 교과 스코프 — 다른 subject 행은 조회에 안 잡혀 "변경"으로 취급(재임베딩).
            MisconceptionEmbedding.subject == self._subject,
        )
        with self._get_engine().connect() as conn:
            rows = conn.execute(stmt).all()
        return {row.misconception_id: row.text_hash for row in rows}


def populate_pgvector(
    provider: EmbeddingProvider,
    *,
    settings: Settings | None = None,
    catalog: tuple[Misconception, ...] = CATALOG,
    index: PgVectorIndex | None = None,
) -> int:
    """카탈로그 표현을 임베딩해 PgVectorIndex에 upsert 적재(영속 사전 임베딩).

    슬104 매처의 `_ensure_built`(인메모리 1회 적재)에 대응하는 *영속* 버전이다 — 카탈로그
    각 항목의 표현(`catalog_text`)을 임베딩해 upsert한다. provider/model은 임베딩 공간 식별자로
    행에 박히고, 같은 공간만 search가 본다. 멱등(재실행 시 갱신).

    **skip-if-unchanged(비용 절감·CLAUDE.md #6·concept/atom embedding 동형)**: 적재 전 현행
    `text_hash`를 조회해 표현이 *바뀐 항목만* 임베딩·upsert한다(`text_hash`는 포맷된 표현 해시라
    포맷 변경도 반영·format_version 불필요). provider/model이 다르면 재임베딩. 반환은 *실제
    적재한(변경분)* 수.

    provider의 model 이름은 *Settings*에서 해석한다(local→embedding_model_local·openai→
    embedding_model_openai·그 외→provider 클래스명) — provider 객체가 model을 노출하지 않으므로
    (좌석은 embed만), 같은 규약을 add/search 양쪽이 공유하도록 여기서 결정한다.
    """
    resolved = settings if settings is not None else get_settings()
    provider_name, model_name = _provider_model_identity(provider, resolved)
    idx = (
        index
        if index is not None
        else PgVectorIndex(provider_name=provider_name, model_name=model_name, settings=resolved)
    )
    # skip-if-unchanged 코어는 레이어-중립 프리미티브가 소유(개념·원자·오개념 공유·3중복 제거).
    # P3-61 — 선지 역추적 전용 항목은 적재하지 않는다(`SemanticMatcher`와 같은 필터). 적재하면
    # 영속 인덱스에 본문 채널 후보 재료가 생긴다. 필터는 순서를 보존하므로 적재 순서 규약은 불변.
    return embed_changed(
        [(m.id, catalog_text(m)) for m in body_detectable(catalog)],
        provider=provider,
        existing_hashes=idx.existing_text_hashes,
        upsert=lambda key, vec, text: idx.upsert_entry(key, vec, source_text=text),
        item_noun="항목",
    )


__all__ = [
    "PgVectorIndex",
    "populate_pgvector",
    "text_hash",
]
