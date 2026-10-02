"""개념 콘텐츠 런타임 조회(async) — code PK 단건.

`l1/concept_visualization/overlay.py::get_visualizability`와 같은 규약이다: 같은 계열의 code-PK
projection 테이블에서 **런타임 조회는 async**, **시드 적재는 sync**(`projection.py`)로 나눈다.

이 모듈이 생기기 전까지 `concept_content`에는 *쓰기 경로만* 있었다(코퍼스 적재). CACHE-01의 공급
경로가 첫 읽기 소비자이며, L3 렌더(`l3/render/dsl.py::from_concept_content`)가 ORM 세션에 묶이지
않도록 **조회는 여기(L1)에서 하고 행만 넘긴다** — 렌더 계층의 db-free 불변식을 지키는 배치다.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.concept_content import CONTENT_SCOPE_K12, ConceptContent


async def get_concept_content(session: AsyncSession, code: str) -> ConceptContent | None:
    """개념 code로 콘텐츠 행을 조회한다(런타임·async). 행 부재→None(미적재 개념).

    PK(code) 단건 조회라 `session.get`으로 충분하다(overlay.py 선례). 호출자는 None을 "이 개념은
    아직 콘텐츠가 없다"로 해석해 생성 경로로 폴백한다 — 예외를 던지지 않는다.
    """
    return await session.get(ConceptContent, code)


async def find_k12_contents_by_atom(session: AsyncSession, atom_code: str) -> list[ConceptContent]:
    """원자 code를 `atom_codes`에 포함하는 K-12 콘텐츠 행 전부 — 크로스워크 역조회(CONT-06).

    K-12 콘텐츠의 PK는 구 437 개념코드라 학습목표의 원자 코드와 겹치지 않는다. 연결은 크로스워크가
    채운 `atom_codes`뿐이므로(S0-2 · `l1/concept_atom_crosswalk/transfer.py`) PK 조회가 비었을 때
    이 함수가 그 연결을 거꾸로 따라간다. 대학 행은 code 자체가 원자 소단원 코드라 PK로 이미 닿고
    `atom_codes`가 비어 있으므로 `scope` 조건으로 명시적으로 제외한다.

    정렬은 `code` 오름차순이다 — 호출자가 대표 행을 고르는 규칙의 결정론 기반이다(DB 반환 순서에
    기대면 같은 요청이 때마다 다른 콘텐츠를 받을 수 있다). 행이 없으면 빈 리스트(예외 없음).
    전수 스캔이지만 K-12 437행이라 PK 미스 때만 치르는 비용으로 충분하다(인덱스·마이그레이션 0).
    """
    stmt = (
        select(ConceptContent)
        .where(
            ConceptContent.scope == CONTENT_SCOPE_K12,
            # `:atom = ANY(atom_codes)` — 배열 원소 포함(ORM `.any()`는 관계용 타입이라 `any_()`).
            sa.literal(atom_code, type_=sa.Text) == sa.any_(ConceptContent.atom_codes),
        )
        .order_by(ConceptContent.code)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


__all__ = ["find_k12_contents_by_atom", "get_concept_content"]
