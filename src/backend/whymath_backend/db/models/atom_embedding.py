"""원자 임베딩 영속 ORM — L1 원자 백본 의미검색 백킹 테이블 (원자 마이그레이션 Phase 2b).

`concept_embedding`(개념 의미검색 pgvector 좌석·슬3)의 *원자 백본* 짝이다. Phase 1이 원자
코퍼스(`data/corpus/atom_graph_v1/graph.json`)를 backend `concept`/`concept_edge`에 적재했고,
Phase 2a가 풍부 원자 메타를 `atom_node`(code 키 PG 프로젝션)에 투영했다. 이 테이블은 그
*세부개념(원자)의 의미 임베딩 벡터*를 **같은 code 키로** pgvector에 한 행씩 보관한다 — backend
`concept`/`atom_node`(code 키)와 *동일 키 공간*이라 그래프·프로젝션·벡터가 한 키로 join된다.

이 모듈은 `concept_embedding.py`를 원자용으로 *미러링*한다. 차이는 ① PK가 `code`(원자 code TEXT —
예 `12미적Ⅰ-01-01-1`·`atom_node.code`와 동일 공간) ② **세부개념(원자)만 임베딩**(단원/소단원
노드 제외 — 적재 책임은 로더가 진다) ③ **임베딩 입력이 name+transfer만**(개념판의
name_ko+metaphor+accepted와 달리 원자엔 그 필드가 없다 — 적재 책임은 텍스트 합성기가 진다)이다.
나머지(provider/model/dim 메타·고정 차원 `vector(N)`·HNSW 인덱스 없음·원문 비저장)는 동일 규약이다.

설계 결정(concept_embedding 미러):
- **PK는 code(TEXT)**: Phase 1 `concept.code`·Phase 2a `atom_node.code`와 *동일 키 공간*(UC 아님).
  upsert가 PK 충돌로 멱등 동작한다(`ON CONFLICT(code) DO UPDATE`) — 같은 원자 재적재가 행을 갱신.
- **embedding은 `pgvector.sqlalchemy.Vector(dim)`**(차원 고정·`config.embedding_dim` 기본 1024·
  bge-m3): `concept_embedding`과 *같은 컬럼 차원 규약*. SQLAlchemy `Vector` 타입·마이그레이션이
  차원을 박으므로 config와 동기화한다(모델 교체[Fake 64·bge-m3 1024·te-3-large 3072] 시
  config+마이그레이션 함께 조정).
- **provider/model/dim 메타**: 같은 임베딩 공간만 비교하려고 보관한다(서로 다른 모델 벡터
  혼재 방지 — 검색이 현재 provider/model 행만 본다). dim은 디버그·정합 점검용.
- **text_hash(TEXT)**: 임베딩 *원본 표현*(원자 표현 = name + transfer)의 해시 — 표현이 바뀌면
  재임베딩이 필요함을 감지하는 신호. **원문 자체는 저장하지 않고 해시만** 둔다(아래 redaction).
- **source_text 비저장(redaction·프라이버시·중복 — CLAUDE.md 우선순위 #2)**: 임베딩 *원문*은
  컬럼으로 두지 않는다. ① 임베딩 입력은 안전 필드(name·transfer)뿐이라 본문 누수는 없으나,
  *원문 재저장을 구조적으로 차단*해 두면 향후 입력이 오염돼도 이 테이블엔 본문이 못 들어온다
  (방어). ② 임베딩 벡터만이 의미검색에 필요하고 원문은 `concept`/`atom_node`에 이미 있다
  (중복 제거). 변경 감지는 `text_hash`로 충분하다.
- **subject(TEXT·NOT NULL·server_default '수학')**: 임베딩 namespace의 *교과 축*(과목 확장 S1 —
  `l1/embedding_primitives.py` namespace 불변식 "namespace = 테이블(kind) × subject"). 축 구분 명문:
  ① `concept_node.domain`류 *수학 내부* 영역 축과 **직교**한다 — subject는 교과('수학'·'물리')
  경계다. ② 교육과정 스코핑의 진실 출처는 `CurriculumEntry.subject`(Overlay 정본)다 — 임베딩
  행의 subject는 **콘텐츠 팩 태그**(적재기가 적재 시점에 `DEFAULT_EMBEDDING_SUBJECT` 상수를
  주입하는 스코프 라벨)이지 교육과정 매핑 주장이 아니다(이중 진실 아님). ③ server_default
  '수학'으로 기존 행이 무손상 백필된다(재임베딩 0 — subject는 컬럼/스코프에만 들어가고 임베딩
  *텍스트*에는 안 들어간다).
- **updated_at**: 마지막 upsert 시각(운영·신선도 추적). server_default now().
- **HNSW/IVFFlat 인덱스 없음**: `concept_embedding`과 동일 — 현 규모(세부개념 원자 — 건수는
  `docs/data/corpus_facts.md`의 `atom_graph.atoms`)는 seq-scan이 최적. 스케일 코퍼스는
  *fixed-dim + HNSW cosine 인덱스*가 정석이나, 이 테이블은 *영속화 +
  의미검색 groundwork*이지 스케일 검색 최적화가 아니다(과장 금지).
- **schema/ 상응물 없음**: 서버 내부 의미검색 인덱스라 Pydantic schema 표면이 없다
  (`concept_embedding`·`concept_node`·`atom_node` 선례 — 검색 결과는 좌석 인터페이스에 흡수).

7계층: 이 테이블은 L1 데이터 기반의 *영속/검색 인프라*다. **L1은 임베딩 저장소·적재만** 소유하고,
의미검색 *로직*(L2/L3/L4가 이 벡터로 무엇을 하는지)은 후속 슬라이스에서 조회 좌석으로 얹는다.
게이팅도 적재가 아니라 *조회* 몫이다 — 이 테이블엔 전 세부개념(원자)을 적재한다(recall 보존).
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.config import get_settings
from whymath_backend.db.base import Base

# 컬럼 차원은 모듈 로드 시점의 Settings에서 읽는다(기본 1024). 적재기·마이그레이션과 *같은
# 값*을 써야 정합한다(config.embedding_dim 단일 출처·concept_embedding 동일 규약).
# lru_cache라 프로세스 1회 해석.
_EMBEDDING_DIM = get_settings().embedding_dim


class AtomEmbedding(Base):
    """원자 의미 임베딩 영속 — pgvector `vector` 백킹 행(code 키·Phase 2b).

    한 행 = 한 세부개념(원자)의 표현 임베딩. PK(code) upsert로 멱등 적재하고, provider/model로
    임베딩 공간을 구분해 *같은 공간 행끼리만* 코사인 비교한다. 원문은 저장하지 않고 표현 해시
    (text_hash)만 둔다(redaction·중복 — docstring 참조).
    """

    __tablename__ = "atom_embedding"

    # PK = 원자 code(Phase 1 `concept.code`·Phase 2a `atom_node.code`와 동일 공간). upsert 충돌 키.
    code: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    # pgvector vector(N) — config.embedding_dim 고정 차원. 코사인 거리 <=> 로 검색.
    embedding: Mapped[list[float]] = mapped_column(Vector(_EMBEDDING_DIM), nullable=False)
    # 임베딩 공간 식별 — provider(local/openai/fake)·model(bge-m3 등). 같은 공간만 비교.
    provider: Mapped[str] = mapped_column(sa.Text, nullable=False)
    model: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 교과 축(namespace = 테이블 × subject) — 콘텐츠 팩 태그(정본은 CurriculumEntry.subject).
    # server_default는 DEFAULT_EMBEDDING_SUBJECT('수학')와 동일해야 한다(거버넌스 테스트 동결).
    subject: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default="수학")
    # 임베딩 차원(디버그·정합 점검). 컬럼 타입 차원과 일치해야 한다.
    dim: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    # 임베딩 원본 표현(name + transfer)의 해시 — 표현 변경(재임베딩 필요) 감지 신호. **원문은
    # 미저장**(해시만).
    text_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 마지막 upsert 시각 — 운영·신선도. server_default now()(upsert 시 코드가 갱신).
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


__all__ = ["AtomEmbedding"]
