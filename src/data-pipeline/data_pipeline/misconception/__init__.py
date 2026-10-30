"""L1 오개념 코퍼스 — 7계층 본문 JSON → 정규화 오개념 카탈로그(M-id) 추출.

업로드 7계층 본문 JSON(개념 배열·각 `L5_META.오개념` 리스트)의 오개념(업로드 원천 기준 839종)을
*적재 가능한 1급 카탈로그*(고유 `mis_id`·콘텐츠 메타)로 정규화한다. 기존
`l4/misconception/catalog.py`(30종 kebab-id·signals 탐지 엔진)와 **별개 체계**다 — 이 카탈로그는
개념·성취기준·CCSS·distractor 규칙·교정 포인트를 갖춘 콘텐츠 카탈로그이고 탐지 signals가 없다(합치지
않는다). 설계 정본: `docs/data/misconception_catalog_v1.md`·`external_corpus_ingestion_v1.md` §2.

라이선스: 오개념 서술·distractor 규칙·교정포인트는 와이매스 자체 저작(redaction 불요), 성취기준·
CCSS 코드는 구조 메타(공공·사실). 원본 JSON은 커밋 안 하고 추출 산출물이 진실 원천(ncic 선례).
"""

from __future__ import annotations

from data_pipeline.misconception.extract import (
    MisconceptionRecord,
    extract_misconceptions,
    load_json,
)

__all__ = [
    "MisconceptionRecord",
    "extract_misconceptions",
    "load_json",
]
