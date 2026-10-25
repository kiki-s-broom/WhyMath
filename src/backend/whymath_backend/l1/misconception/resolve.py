"""L1 오개념 카탈로그 *느슨참조 해소* — 읽기 전용 런타임 헬퍼 (해소 슬라이스).

B 아크(#290~#292)가 적재한 `misconception_catalog`(적재 당시 839행 — 현재 코퍼스 건수는
`docs/data/corpus_facts.md`의 `misconceptions.count`)의 `concept_src_id`·`standard_code`는
*느슨참조*(FK 아님·원천 문자열 그대로)로 남아 있다. 이 모듈은 그 느슨참조를 실 `Concept`·
`AchievementStandard` 행에 잇는 **읽기 전용 해소 헬퍼**다(마이그레이션 0·로더 변경 0 — FK 컬럼· 링크
테이블을 만들지 않고 조회 시 조인).

해소 규칙(탐색으로 못 박은 키 공간):
  - `concept_src_id`(원 source_id 예 `N1`·`10기수1-01-01`) → `Concept.source_id` *직접 조인*
    (NOT `code` — code는 재ID된 새 코드·`standard_loader`의 `{source_id: code}` 선례와 동일
    키 공간). 100% 해소 예상.
  - `standard_code`(`[2수01-01]` 형식·대부분 단일·소수 다중`;` — 작성 당시 835 단일·4 다중) →
    `AchievementStandard.official_code` *직접 일치*. 한 official_code가 2015·2022 두 개정에 존재
    가능 → 다중 norm_id를 *정직 반환* (revision 강제 선택 안 함 — catalog의 standard_code엔 revision
    신호가 없어 자동 선택은 의도 날조다. 소비처가 하류 필터).

설계 분리(코드베이스 패턴):
  - **순수 코어**(`_split_standard_codes`·`_assemble_links`) — 매칭/분할은 DB 무관·I/O 0.
  - **얇은 DB 시암**(`_fetch_concept_map`·`_fetch_standard_map`) — 일괄 2 IN쿼리(N+1 회피·
    읽기 전용·`session.execute`/`scalars`만).
  - 호출자가 row를 미리 로드해 넘긴다(`resolve_many(session, rows)`) — 헬퍼는
    `misconception_catalog`를 조회하지 않는다(읽기 전용·로더 무관).

정직 회계(`standard_loader` orphan 보고 선례):
  - `concept_orphan`: `concept_src_id`가 있는데 map miss. `concept_src_id` None은 orphan 아님
    (`concept_resolved=False`만 — "참조 없음" ≠ "미해소 참조").
  - `standard_orphan_codes`: 분할 코드별 standards 빈 list. 다중코드 행은 부분 해소 가능
    (코드별 정직 집계).
  - 다중 revision(같은 코드 2015+2022)은 orphan 아님 — 둘 다 반환·norm_id 정렬·revision 강제 안 함.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.achievement_standard import AchievementStandard
from whymath_backend.db.models.concept import Concept
from whymath_backend.db.models.misconception_catalog import MisconceptionCatalog


# ──────────────────────────────────────────────────────────────────────────
# 결과 모델 (frozen pydantic — 불변 해소 결과)
# ──────────────────────────────────────────────────────────────────────────
class ConceptRef(BaseModel):
    """해소된 개념 참조 — `concept_src_id` → `Concept`(source_id 조인)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    concept_id: uuid.UUID
    code: str


class StandardRef(BaseModel):
    """해소된 성취기준 참조 — `standard_code` → `AchievementStandard`(official_code 일치)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    norm_id: str
    official_code: str
    curriculum_revision: str


class ResolvedStandardCode(BaseModel):
    """하나의 성취기준 코드 해소 결과 — standards 빈 list면 orphan(코드별 정직 집계)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    # norm_id 정렬·다중 revision(2015+2022)이면 2개 이상·빈 list면 orphan.
    standards: tuple[StandardRef, ...]


class ResolvedMisconceptionLinks(BaseModel):
    """오개념 1행의 느슨참조 해소 결과 — concept·standard_codes·정직 회계 플래그."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mis_id: str
    # concept_src_id가 있고 해소되면 ConceptRef·없거나 미해소면 None.
    concept: ConceptRef | None
    standard_codes: tuple[ResolvedStandardCode, ...]
    # 정직 회계.
    concept_resolved: bool
    standard_resolved: bool
    # concept_src_id가 있는데 map miss(참조 있으나 못 찾음). None 참조는 orphan 아님.
    concept_orphan: bool
    # 분할 코드 중 standards 빈 list인 코드(부분 해소 가능).
    standard_orphan_codes: tuple[str, ...]


# ──────────────────────────────────────────────────────────────────────────
# 순수 코어 — 분할·조립(DB 무관·I/O 0)
# ──────────────────────────────────────────────────────────────────────────
def _split_standard_codes(raw: str | None) -> list[str]:
    """`standard_code` 원천 문자열 → 코드 리스트(`;` 분할·strip·빈값 제거·None→[]).

    단일(`[2수01-01]`)·다중(`[2수03-08]; [2수03-09]`)·후행`;`·None을 모두 정규화한다.
    """
    if raw is None:
        return []
    return [token.strip() for token in raw.split(";") if token.strip()]


def _assemble_links(
    mis: MisconceptionCatalog,
    concept_map: dict[str, ConceptRef],
    standard_map: dict[str, list[StandardRef]],
) -> ResolvedMisconceptionLinks:
    """사전 페치 맵으로 오개념 1행을 해소(순수·I/O 0).

    `concept_map`: source_id → ConceptRef. `standard_map`: official_code → [StandardRef]
    (norm_id 정렬·`_fetch_standard_map`가 보장). 정직 회계는 모듈 docstring 정의를 따른다.
    """
    # ── 개념 해소(concept_src_id → Concept.source_id) ──
    src_id = mis.concept_src_id
    concept = concept_map.get(src_id) if src_id is not None else None
    concept_resolved = concept is not None
    # concept_src_id가 있는데 못 찾으면 orphan. None 참조는 orphan 아님("참조 없음" ≠ "미해소").
    concept_orphan = src_id is not None and concept is None

    # ── 성취기준 해소(standard_code 분할 → official_code 일치) ──
    codes = _split_standard_codes(mis.standard_code)
    resolved_codes: list[ResolvedStandardCode] = []
    orphan_codes: list[str] = []
    for code in codes:
        standards = tuple(standard_map.get(code, []))
        resolved_codes.append(ResolvedStandardCode(code=code, standards=standards))
        if not standards:
            orphan_codes.append(code)
    # 코드가 1개 이상이고 모두 해소(orphan 코드 0)면 standard_resolved.
    standard_resolved = len(codes) > 0 and len(orphan_codes) == 0

    return ResolvedMisconceptionLinks(
        mis_id=mis.mis_id,
        concept=concept,
        standard_codes=tuple(resolved_codes),
        concept_resolved=concept_resolved,
        standard_resolved=standard_resolved,
        concept_orphan=concept_orphan,
        standard_orphan_codes=tuple(orphan_codes),
    )


# ──────────────────────────────────────────────────────────────────────────
# 얇은 DB 시암 — 일괄 2 IN쿼리(N+1 회피·읽기 전용)
# ──────────────────────────────────────────────────────────────────────────
async def _fetch_concept_map(session: AsyncSession, src_ids: set[str]) -> dict[str, ConceptRef]:
    """source_id 집합 → {source_id: ConceptRef} 맵(일괄 IN쿼리·읽기 전용).

    빈 set이면 빈 쿼리를 피해 즉시 {} 반환. `Concept.source_id`는 nullable이라 NULL 행은
    IN 조건에서 자연히 제외된다(NULL은 매칭 안 됨).
    """
    if not src_ids:
        return {}
    stmt = select(Concept.source_id, Concept.code, Concept.concept_id).where(
        Concept.source_id.in_(src_ids)
    )
    result = await session.execute(stmt)
    mapping: dict[str, ConceptRef] = {}
    for source_id, code, concept_id in result.all():
        if source_id is None:
            continue  # 방어적 — NULL source_id skip(IN이 걸러도 명시).
        mapping[source_id] = ConceptRef(concept_id=concept_id, code=code)
    return mapping


async def _fetch_standard_map(
    session: AsyncSession, codes: set[str]
) -> dict[str, list[StandardRef]]:
    """official_code 집합 → {official_code: [StandardRef]} 맵(일괄 IN쿼리·norm_id 정렬).

    같은 official_code가 2015·2022 두 개정에 존재 가능 → official_code별 리스트로 그룹하고
    norm_id로 정렬해 결정적 순서를 보장한다(revision 강제 선택 없음). 빈 set이면 {} 반환.
    """
    if not codes:
        return {}
    stmt = select(AchievementStandard).where(AchievementStandard.official_code.in_(codes))
    result = await session.execute(stmt)
    grouped: dict[str, list[StandardRef]] = {}
    for row in result.scalars().all():
        ref = StandardRef(
            norm_id=row.norm_id,
            official_code=row.official_code,
            curriculum_revision=row.curriculum_revision,
        )
        grouped.setdefault(row.official_code, []).append(ref)
    # norm_id 정렬 — 다중 revision 결정적 순서(셔플 입력 무관).
    for refs in grouped.values():
        refs.sort(key=lambda r: r.norm_id)
    return grouped


# ──────────────────────────────────────────────────────────────────────────
# 공개 진입점 — resolve_many / resolve_one / summarize
# ──────────────────────────────────────────────────────────────────────────
async def resolve_many(
    session: AsyncSession, rows: Sequence[MisconceptionCatalog]
) -> list[ResolvedMisconceptionLinks]:
    """오개념 행들의 느슨참조를 일괄 해소(입력순 보존·2 IN쿼리·읽기 전용).

    distinct `concept_src_id`/`standard_code` 코드를 수집해 2회 IN쿼리로 맵을 만든 뒤 행별로
    순수 `_assemble_links`를 호출한다(N+1 회피). 빈 입력이면 빈 list.
    """
    src_ids: set[str] = set()
    codes: set[str] = set()
    for mis in rows:
        if mis.concept_src_id is not None:
            src_ids.add(mis.concept_src_id)
        codes.update(_split_standard_codes(mis.standard_code))

    concept_map = await _fetch_concept_map(session, src_ids)
    standard_map = await _fetch_standard_map(session, codes)

    return [_assemble_links(mis, concept_map, standard_map) for mis in rows]


async def resolve_one(
    session: AsyncSession, mis: MisconceptionCatalog
) -> ResolvedMisconceptionLinks:
    """단일 오개념 행 해소 — `resolve_many`의 1원소 래퍼."""
    results = await resolve_many(session, [mis])
    return results[0]


def summarize(results: Sequence[ResolvedMisconceptionLinks]) -> dict[str, int]:
    """해소 결과 집계 — 해소율 검증용 카운트(total·해소·orphan).

    `standard_orphan_code_n`은 *행 수*가 아니라 모든 행에 걸친 orphan 코드 *발생 수*다
    (다중코드 행은 코드별로 센다).
    """
    total = len(results)
    concept_resolved_n = sum(1 for r in results if r.concept_resolved)
    standard_resolved_n = sum(1 for r in results if r.standard_resolved)
    concept_orphan_n = sum(1 for r in results if r.concept_orphan)
    standard_orphan_code_n = sum(len(r.standard_orphan_codes) for r in results)
    return {
        "total": total,
        "concept_resolved_n": concept_resolved_n,
        "standard_resolved_n": standard_resolved_n,
        "concept_orphan_n": concept_orphan_n,
        "standard_orphan_code_n": standard_orphan_code_n,
    }


__all__ = [
    "ConceptRef",
    "StandardRef",
    "ResolvedStandardCode",
    "ResolvedMisconceptionLinks",
    "resolve_many",
    "resolve_one",
    "summarize",
]
