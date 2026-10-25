"""L1 오개념 카탈로그 — 코퍼스 → backend 영속/적재 인프라 (Phase B.3 코퍼스 로더).

L1 데이터 기반 적재 아크의 *오개념* 부분이다. Phase B.2(#291)가 카탈로그의 ORM
(`db/models/misconception_catalog.py`)·계약(`schema/misconception_catalog.py`)·마이그레이션만 세우고
코퍼스 로더는 *후속 몫*으로 보류했는데, 이 패키지가 그 로더를 담는다 — #290 코퍼스
(`data/corpus/misconceptions_v1/misconceptions.json`·Collection JSON·커밋 당시 839 레코드 — 현재
건수는 `docs/data/corpus_facts.md`의 `misconceptions.count`)를 backend 영속 `misconception_catalog`
테이블로 멱등 적재한다.

`l1/standards`(성취기준 적재)의 오개념 짝이며 같은 sync 좌석·멱등 규약을 따른다. 단 성취기준
로더가 메우던 두 seam(코퍼스 `code`→`official_code` rename·`concept_src_id`→새 code 해석)은
*둘 다 없다* — 코퍼스 키=schema 필드라 rename 0, `concept_src_id`·`standard_code`는 느슨참조라
원천 그대로 저장(해소 없음). 단일 PK(`mis_id`) 충돌 upsert만 한다.

(주의: 기존 `l4/misconception`는 *탐지 엔진*(kebab-id)으로 별개 체계다 — FK로 잇지 않는다.)

7계층: L1 데이터 기반의 *영속/적재 인프라*. 소비(진단·distractor 생성)는 이 좌석을 호출하되
여기서 구현하지 않는다(후속·역방향 의존 금지).
"""

from __future__ import annotations

from whymath_backend.l1.misconception.catalog_loader import (
    MisconceptionCatalogStore,
    load_misconceptions,
)
from whymath_backend.l1.misconception.populate import main as populate_main
from whymath_backend.l1.misconception.resolve import (
    ConceptRef,
    ResolvedMisconceptionLinks,
    ResolvedStandardCode,
    StandardRef,
    resolve_many,
    resolve_one,
    summarize,
)

__all__ = [
    "MisconceptionCatalogStore",
    "load_misconceptions",
    "populate_main",
    "ConceptRef",
    "StandardRef",
    "ResolvedStandardCode",
    "ResolvedMisconceptionLinks",
    "resolve_many",
    "resolve_one",
    "summarize",
]
