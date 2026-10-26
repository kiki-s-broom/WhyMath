"""원자 의미 임베딩 적재 — pgvector 영속 좌석 (L1 원자 백본 아크·Phase 2b).

`l1/concept_graph/embedding.py`(개념 의미 임베딩 pgvector 좌석·슬3)의 *원자 백본* 짝이다.
Phase 1 산출 `graph.json`(원자 코퍼스·code 키)의 각 *세부개념(원자)*을 *안전 필드 표현*으로
임베딩해 `atom_embedding` 테이블(pgvector)에 멱등 upsert한다. Phase 1 `concept`·Phase 2a
`atom_node`와 *동일 code 키*라 그래프·프로젝션·벡터가 한 키로 join된다. **임베딩 provider seam·
sync 엔진·해시·식별 헬퍼는 슬3(또는 그 출처 L4)에서 그대로 import 재사용한다**(신규 seam 0 —
같은 임베딩 공간 규약·Fake 주입·지연 로드·CLAUDE.md 로컬 우선).

────────────────────────────────────────────────────────────────────────────
redaction (CLAUDE.md 우선순위 #2 — 협상 불가)
────────────────────────────────────────────────────────────────────────────
임베딩 입력 표현은 **자체 작성 안전 필드만** 쓴다 — `name`(원자명)·`transfer`(④전이·자체 작성
교수 주석). 개념판의 metaphor·accepted_expressions에 대응하지만 원자엔 그 필드가 없으므로
name+transfer뿐이다. **`core_proposition`·`description`·`formal_definition`·4요소(`misconception`·
`diagnostic_*`·`socratic`)는 절대 읽지 않는다**: 성취기준 *본문* 근접/검수 책임 필드이고,
이 모듈은 그 키를 *읽지도 않으므로* 입력이 오염돼도 본문이 임베딩에 유입되지 않는다(이중 방어).
임베딩 *벡터*만 적재하고 원문은 `atom_embedding`에 저장하지 않는다(ORM docstring·중복·프라이버시).

────────────────────────────────────────────────────────────────────────────
대상 = 세부개념(원자)만
────────────────────────────────────────────────────────────────────────────
`graph.json` `concepts` 중 **`level=="세부개념"`인 원자만**(건수는 `docs/data/corpus_facts.md`의
`atom_graph.atoms`) 임베딩한다 — 단원/소단원 노드는 의미검색 대상이 아니라 제외한다(`atom_node`
프로젝션은 전 노드를 담지만, 임베딩은 원자만).
키는 `code`(원자 code). 안전 필드가 전부 빈(name·transfer 모두 공백) 원자는 제외(빈 벡터 방지).

────────────────────────────────────────────────────────────────────────────
sync 엔진 (async 전용 코드베이스에 *벡터 store 좌석에 한정*된 sync 드라이버)
────────────────────────────────────────────────────────────────────────────
앱 본체는 async 전용(asyncpg)이고, 이 좌석만 sync 엔진(psycopg)을 쓴다. 슬3 `_build_sync_engine`을
*그대로 재사용*한다(신규 빌더 0 — 지연 import·`db_disable_pool` NullPool 가드·register_vector
리스너). sync URL은 `Settings.sync_database_url`·자격증명은 코드에 0(env).

7계층: 이 적재기는 L1 데이터 기반의 *영속/적재 인프라*다. 의미검색 *조회*(L2/L3/L4)는 후속
슬라이스에서 좌석으로 얹는다 — 여기선 저장소·적재만 소유한다.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from whymath_backend.config import Settings, get_settings

# 슬3 sync 엔진 빌더 재사용(신규 seam 0) — node_projection·atom_node_projection과 동일 규약.
from whymath_backend.l1.concept_graph.embedding import _build_sync_engine

# 임베딩 provider seam·해시·식별 헬퍼 재사용(신규 금지·CLAUDE.md 로컬 우선) — 개념판과 *같은*
# 좌석을 쓴다. text_hash(표현 변경 감지)·provider_model_identity(공간 식별)는 레이어-중립 L1
# 프리미티브(`l1/embedding_primitives.py`)에서 가져온다(L1→L1·역방향 의존 0·seam 0·동일 규약).
from whymath_backend.l1.embedding_primitives import (
    DEFAULT_EMBEDDING_SUBJECT,
    embed_changed,
    join_embedding_text,
    provider_model_identity,
    text_hash,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from whymath_backend.l1.embedding_primitives import EmbeddingProvider

# graph.json `concepts` 중 임베딩 대상 level(세부개념=원자만). 단원/소단원 노드는 의미검색
# 대상이 아니라 제외한다(atom_node 프로젝션과 달리 임베딩은 원자만).
_ATOM_LEVEL: str = "세부개념"


@dataclass(frozen=True, slots=True)
class AtomText:
    """임베딩 대상 한 원자 — code + 안전 필드(name+transfer)로 합성한 표현.

    `text`는 `atom_embedding_text`가 안전 필드만으로 만든 표현이다(본문 미포함). 적재기가 이
    표현을 임베딩하고 code 키로 upsert한다(`ConceptText`의 원자 짝).
    """

    code: str
    text: str


def atom_embedding_text(
    *,
    name_ko: str | None,
    transfer: str | None = None,
) -> str:
    """원자를 임베딩할 자연어 표현으로 직렬화 — **안전 필드만**(name + transfer).

    `concept_embedding_text`(name_ko·metaphor·accepted)의 원자판이다. 원자엔 metaphor·accepted가
    없으므로 명칭(name)과 전이(transfer)만 잇는다. **description·formal_definition·core_proposition·
    4요소는 인자로 받지도 않는다**(redaction — 본문/검수 책임 필드 구조적 차단). 비어 있는 필드는
    건너뛰고, 남은 조각을 `". "`로 잇는다(개념판과 동일 결합 규칙·구분자·strip·빈값 처리). name이
    비면(이론상 graph.json은 name 필수) 나머지만으로 표현을 만든다(빈 표현 가능 — 호출자[로더]가
    빈 표현을 거른다).
    """
    return join_embedding_text(name_ko, transfer)


def load_atoms_from_graph_json(path: Path) -> list[AtomText]:
    """Phase 1 산출 `graph.json` → 임베딩 대상 (원자 code, 안전 표현) 목록(세부개념만).

    `concepts` 배열에서 **`level=="세부개념"`인 원자만** 골라 `code`와 **안전 필드(name·transfer)
    만** 읽어 표현을 합성한다 — 단원/소단원 노드는 제외한다(의미검색 대상 아님). `core_proposition`·
    `description`·`formal_definition`·4요소(`misconception`·`diagnostic_*`·`socratic`)·`redacted_fields`
    는 *읽지 않는다*(redaction — 있더라도 이 함수가 무시·구조적 차단).

    표현이 빈(name·transfer 전부 공백) 원자는 제외한다(임베딩 무의미 — 빈 벡터 적재 방지). 단원/
    소단원·그래프 외 자산은 임베딩 대상이 아니므로 읽지 않는다.

    Raises:
        FileNotFoundError: graph.json 부재.
        ValueError: 세부개념인데 code 없는 항목(Phase 1 산출은 항상 code를 갖는다 — 방어).
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: list[AtomText] = []
    for record in payload.get("concepts", []):
        if record.get("level") != _ATOM_LEVEL:
            # 단원/소단원 노드 — 의미검색 임베딩 대상이 아니다(원자만).
            continue
        code = str(record.get("code", "")).strip()
        if not code:
            raise ValueError(f"graph.json 세부개념(원자)에 code가 없습니다: {record!r}")
        text = atom_embedding_text(
            name_ko=record.get("name"),
            transfer=record.get("transfer"),
        )
        if not text:
            # 안전 필드(name·transfer)가 전부 비어 임베딩할 표현이 없는 원자 — 제외(빈 벡터 방지).
            continue
        out.append(AtomText(code=code, text=text))
    return out


class AtomEmbeddingIndex:
    """원자 pgvector 영속 인덱스 — `atom_embedding` 테이블 upsert/검색(code PK·sync).

    `ConceptEmbeddingIndex`(concept_embedding)의 *원자 백본* 짝이다. `upsert`는 PK 충돌 upsert
    (`INSERT ... ON CONFLICT(code) DO UPDATE`)로 멱등 적재하고, `search`는 코사인 거리(`<=>`)로
    상위 후보를 찾는다(`similarity = 1 - distance`). **같은 임베딩 공간(provider·model) 행만**
    비교한다(서로 다른 모델 벡터 혼재 방지). sync 엔진은 슬3 `_build_sync_engine`을 재사용해 지연
    생성·캐시한다(신규 seam 0 — psycopg 연결마다 pgvector 어댑터 등록).

    provider/model은 *임베딩 공간 식별자*다 — 같은 provider라도 model이 다르면 다른 공간으로
    본다. 호출자(적재기)는 upsert/search에 *같은* provider·model을 일관되게 넘겨야 한다. 차원
    불일치는 pgvector가 적재 시점에 오류로 막는다(컬럼 `vector(N)`).

    `subject`는 임베딩 namespace의 *교과 축*이다(namespace = 테이블 × subject —
    `l1/embedding_primitives.py` 불변식). upsert·search·existing_text_hashes 전부가 이 스코프를
    건다 — 다른 교과 행은 서로 보이지 않는다. 기본값 `DEFAULT_EMBEDDING_SUBJECT`('수학')라
    기존 호출자(populate)는 무수정으로 수학 스코프를 흡수한다(파라미터 관통 금지).
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
        """설정 지연 해석 — 주입 우선, 없으면 캐시된 전역 Settings(concept embedding 패턴)."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_engine(self) -> Engine:
        """sync 엔진 지연 해석 — 주입 우선, 없으면 슬3 빌더로 생성·캐시(신규 seam 0).

        첫 호출에서 `_build_sync_engine(settings)`로 sync 엔진을 만들고 인스턴스에 캐시한다.
        psycopg/SQLAlchemy/pgvector import는 *이 시점*에만 일어난다(모듈 import 깨짐 방지).
        """
        if self._engine is None:
            self._engine = _build_sync_engine(self._resolved_settings)
        return self._engine

    def upsert(self, code: str, vector: Sequence[float], *, source_text: str) -> None:
        """단일 (원자 code, 벡터) upsert (멱등·표현 해시 기록).

        `INSERT ... ON CONFLICT(code) DO UPDATE` — provider/model/dim/text_hash/updated_at을
        함께 적재한다. 같은 키 재적재는 행을 갱신(멱등). `source_text`는 임베딩한 *표현*(안전
        필드 합성)이고, 그 해시만 `text_hash`로 보관한다(원문 미저장 — 변경 감지용 해시만).
        """
        from sqlalchemy import func
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from whymath_backend.db.models.atom_embedding import AtomEmbedding

        values = [float(x) for x in vector]
        stmt = pg_insert(AtomEmbedding).values(
            code=code,
            embedding=values,
            provider=self._provider_name,
            model=self._model_name,
            subject=self._subject,
            dim=len(values),
            text_hash=text_hash(source_text),
        )
        # PK 충돌 시 갱신 — updated_at은 now()로 새로 찍는다(server_default는 INSERT 전용).
        stmt = stmt.on_conflict_do_update(
            index_elements=[AtomEmbedding.code],
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

    def search(self, vector: Sequence[float], *, top_k: int) -> list[tuple[str, float]]:
        """질의 벡터에 대한 코사인 상위 top_k (code, similarity)(유사도 내림차순).

        `1 - (embedding <=> :q)`(코사인 거리→유사도)로 점수를 내고 *같은 provider·model 행만*
        본다(임베딩 공간 일치). top_k<=0이면 빈 리스트. 거리 오름차순 = 유사도 내림차순으로
        정렬·LIMIT. NULL 거리(영벡터 등 정의 불가)는 0 유사도로 안전 처리.

        반환 타입은 단순 튜플 목록이다 — 이 좌석은 L1 의미검색 groundwork이고 조회 인터페이스
        (L2/L4 결선)는 후속에서 정의한다(현재는 적재 검증·통합 라운드트립 용도). 조회 좌석이
        생기면 그 타입으로 흡수한다(concept_embedding 동형).
        """
        if top_k <= 0:
            return []
        from sqlalchemy import select

        from whymath_backend.db.models.atom_embedding import AtomEmbedding

        query = [float(x) for x in vector]
        distance = AtomEmbedding.embedding.cosine_distance(query)
        stmt = (
            select(
                AtomEmbedding.code,
                distance.label("distance"),
            )
            .where(
                AtomEmbedding.provider == self._provider_name,
                AtomEmbedding.model == self._model_name,
                # 교과 스코프 — 다른 subject 행은 랭킹에 안 잡힌다(namespace 불변식).
                AtomEmbedding.subject == self._subject,
            )
            .order_by(distance)
            .limit(top_k)
        )
        with self._get_engine().connect() as conn:
            rows = conn.execute(stmt).all()
        return [
            (
                row.code,
                (1.0 - float(row.distance)) if row.distance is not None else 0.0,
            )
            for row in rows
        ]

    def existing_text_hashes(self, codes: Sequence[str]) -> dict[str, str]:
        """주어진 code들의 *현행* text_hash를 조회한다 — {code: text_hash}(단일 SELECT).

        같은 임베딩 공간(provider·model)의 행만 본다(다른 공간은 재임베딩 필요라 미포함=변경 취급).
        적재기 skip-if-unchanged용(concept_embedding 동형). 빈 입력은 쿼리 없이 {}.
        """
        if not codes:
            return {}
        from sqlalchemy import select

        from whymath_backend.db.models.atom_embedding import AtomEmbedding

        stmt = select(AtomEmbedding.code, AtomEmbedding.text_hash).where(
            AtomEmbedding.code.in_(list(dict.fromkeys(codes))),
            AtomEmbedding.provider == self._provider_name,
            AtomEmbedding.model == self._model_name,
            # 교과 스코프 — 다른 subject 행은 조회에 안 잡혀 "변경"으로 취급(재임베딩).
            AtomEmbedding.subject == self._subject,
        )
        with self._get_engine().connect() as conn:
            rows = conn.execute(stmt).all()
        return {row.code: row.text_hash for row in rows}


def populate_atom_embeddings(
    atoms: Sequence[AtomText],
    provider: EmbeddingProvider,
    *,
    settings: Settings | None = None,
    index: AtomEmbeddingIndex | None = None,
) -> int:
    """원자 표현을 임베딩해 `AtomEmbeddingIndex`에 멱등 upsert 적재(영속 사전 임베딩).

    `populate_concept_embeddings`의 *원자 백본* 짝이다 — 각 원자의 안전 표현(`AtomText.text`)을
    임베딩해 code 키로 upsert한다. provider/model은 임베딩 공간 식별자로 행에 박히고, 같은 공간만
    search가 본다. 멱등(재실행 시 갱신).

    **skip-if-unchanged(비용 절감·CLAUDE.md #6·concept_embedding 동형)**: 적재 전 현행 `text_hash`를
    조회해 표현이 *바뀐 원자만* 임베딩·upsert한다(`text_hash`는 포맷된 표현 해시라 포맷 변경도
    반영·format_version 불필요). provider/model이 다르면 재임베딩. 반환은 *실제 적재한(변경분)* 수.

    provider의 model 이름은 *Settings*에서 해석한다(`provider_model_identity` 재사용 —
    local→embedding_model_local·openai→embedding_model_openai·fake→fake-hash). provider 객체가
    model을 노출하지 않으므로(좌석은 embed만), 같은 규약을 upsert/search 양쪽이 공유하도록
    여기서 결정한다(concept_embedding과 동일). review_status 무관 전량 적재(게이팅은 조회 몫).
    """
    resolved = settings if settings is not None else get_settings()
    provider_name, model_name = provider_model_identity(provider, resolved)
    idx = (
        index
        if index is not None
        else AtomEmbeddingIndex(
            provider_name=provider_name, model_name=model_name, settings=resolved
        )
    )
    # skip-if-unchanged 코어는 레이어-중립 프리미티브가 소유(개념·원자·오개념 공유·3중복 제거).
    return embed_changed(
        [(a.code, a.text) for a in atoms],
        provider=provider,
        existing_hashes=idx.existing_text_hashes,
        upsert=lambda key, vec, text: idx.upsert(key, vec, source_text=text),
        item_noun="원자",
    )


__all__ = [
    "AtomEmbeddingIndex",
    "AtomText",
    "atom_embedding_text",
    "load_atoms_from_graph_json",
    "populate_atom_embeddings",
]
