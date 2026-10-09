"""오개념 crosswalk 해석 *통합테스트* — kebab→M-id resolver 실 PG 조회 (WHYMATH_RUN_INTEGRATION).

마이그레이션 head가 적용된 **실 PostgreSQL**에서 `MisconceptionCrosslinkResolver`가 실 쿼리로
kebab-id를 M-id(들)·canonical M-id로 해석하는지 검증한다. 이 해석은 Kiki가 `promote --load`
직후 돌릴 **shadow 측정 윈도의 핵심 연산**(`crosslink_shadow.observe_crosslink_shadow` 경로)이며,
기존 resolver 테스트는 `_FakeEngine` hermetic이라 실 SQL(`WHERE kebab_id IN`·`confidence >=` 필터·
NULL 제외·정렬·Numeric→float)을 검증하지 못했다. #441(적재 write 경로)의 짝 — read 경로를 실 PG로
동결해 적재→해석 전 구간의 안전망을 완성한다. PG 미도달 시 graceful skip.

검증(계획 §Context):
  ① resolve/resolve_many — confidence 내림차순·NULL 마지막·그룹화·미존재 kebab 키 부재
  ② min_confidence — 실 SQL `>=` 필터 + NULL 제외(보수)
  ③ resolve_canonical — 실 행 위 정책 4분기(ok·tie·no_direct·no_links·오귀속 방지)
  ④ Numeric(Decimal)→float 정규화

적재 키는 실 데이터와 충돌하지 않도록 합성 mis_id(`MITRS...`)·`it` 슬러그 kebab(`zzit-...`)을 쓴다.
"""

from __future__ import annotations

from typing import Any

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.misconception.catalog_loader import load_misconceptions
from whymath_backend.l1.misconception.crosslink_loader import (
    MisconceptionCrosslinkStore,
    load_crosslinks,
)
from whymath_backend.l1.misconception.crosslink_resolve import MisconceptionCrosslinkResolver
from whymath_backend.schema.misconception_crosslink import MisconceptionCrosslink

pytestmark = pytest.mark.integration

# kebab_id — 느슨참조(FK 아님)라 시딩 자유. it 슬러그로 실 데이터 비충돌.
_KEBAB_A = "zzit-resolve-a"
_KEBAB_B = "zzit-resolve-b"
_KEBAB_MISSING = "zzit-resolve-none"
# mis_id — 합성. misconception_catalog에 먼저 시딩(FK).
_MIS_A1 = "MITRS01"
_MIS_A2 = "MITRS02"
_MIS_A3 = "MITRS03"
_MIS_B1 = "MITRS04"
_ALL_MIS = [_MIS_A1, _MIS_A2, _MIS_A3, _MIS_B1]


# ── 실 PG 좌석(loader 통합 테스트 미러) ────────────────────────────────────
def _sync_engine() -> Any:
    """통합테스트용 sync(psycopg) 엔진 — 시딩·정리·resolver 주입용 raw 엔진."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    settings = Settings()
    url = settings.sync_database_url
    if settings.db_disable_pool:
        return create_engine(url, poolclass=NullPool)
    return create_engine(url)


def _reachable() -> bool:
    """실 PG 도달 + crosswalk·카탈로그 테이블 존재(마이그레이션 적용) 여부."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT count(*) FROM misconception_crosslink"))
            conn.execute(text("SELECT count(*) FROM misconception_catalog"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


def _skip_if_unreachable() -> None:
    if not _reachable():
        pytest.skip(
            "PostgreSQL 미도달(또는 마이그레이션 미적용) — 통합 테스트 건너뜀 "
            "(WHYMATH_DATABASE_URL·alembic upgrade head 확인)"
        )


def _cleanup() -> None:
    """적재 행 정리 — FK 역순(crosslink 먼저·그다음 catalog). 실 데이터 비충돌 키 스코프."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM misconception_crosslink WHERE mis_id = ANY(:ids)"),
                {"ids": _ALL_MIS},
            )
            conn.execute(
                text("DELETE FROM misconception_catalog WHERE mis_id = ANY(:ids)"),
                {"ids": _ALL_MIS},
            )
    finally:
        engine.dispose()


# ── 시드 헬퍼 ──────────────────────────────────────────────────────────────
def _seed_catalog(*mis_ids: str) -> None:
    """crosslink FK(mis_id→misconception_catalog) 충족용 카탈로그 시딩(멱등 upsert)."""
    load_misconceptions(
        None,
        {
            "misconceptions": [
                {
                    "mis_id": m,
                    "canonical_statement": "통합테스트 오개념.",
                    "error_type": "개념오류",
                    "difficulty": "중",
                }
                for m in mis_ids
            ]
        },
        settings=Settings(),
    )


def _link(
    *,
    kebab_id: str,
    mis_id: str,
    link_type: str = "직접매핑",
    confidence: float | None = 0.9,
) -> dict[str, Any]:
    """crosslink 시드 1행 dict(로더 형식) — method=manual + 검수 서명(load 게이트 통과)."""
    return {
        "kebab_id": kebab_id,
        "mis_id": mis_id,
        "link_type": link_type,
        "confidence": confidence,
        "method": "manual",
        # load 게이트(Gate Contract)가 검수 서명 stamp를 요구 — promote 산출물 형태로 시드한다.
        "note": "검수:통합테스트 2026-07-08",
    }


def _seed_crosslinks(rows: list[dict[str, Any]]) -> None:
    """검증된 적재기(load_crosslinks)로 crosslink 시딩(실 ON CONFLICT 경로)."""
    load_crosslinks(None, {"crosslinks": rows}, engine=_sync_engine())


def _seed_crosslinks_ungated(rows: list[dict[str, Any]]) -> None:
    """load 게이트를 거치지 않는 저수준 시딩 — 적재 자격(MISC-63) 이전에 이미 쌓인 비직접 행의 재현용.

    부분매핑·개념겹침은 이제 `load_crosslinks`가 거부한다. 그러나 리졸버의 `no_direct` 분기는 이미
    테이블에 들어가 있는 비직접 행(정책 이전 적재분·직접 편집)에 대해 여전히 정직해야 하므로, 계약이
    합성 시딩 좌석으로 명시한 `MisconceptionCrosslinkStore.populate`로 그 상태를 만든다.
    """
    MisconceptionCrosslinkStore(engine=_sync_engine()).populate(
        [MisconceptionCrosslink.model_validate(r) for r in rows]
    )


# ── 테스트: resolve / resolve_many ─────────────────────────────────────────
def test_resolve_returns_mids_confidence_desc() -> None:
    """한 kebab 3링크(0.95/0.8/NULL) → resolve가 confidence 내림차순·NULL 마지막(실 정렬)."""
    _skip_if_unreachable()
    try:
        _cleanup()
        _seed_catalog(_MIS_A1, _MIS_A2, _MIS_A3)
        _seed_crosslinks(
            [
                _link(kebab_id=_KEBAB_A, mis_id=_MIS_A2, confidence=0.8),
                _link(kebab_id=_KEBAB_A, mis_id=_MIS_A1, confidence=0.95),
                _link(kebab_id=_KEBAB_A, mis_id=_MIS_A3, confidence=None),
            ]
        )
        resolver = MisconceptionCrosslinkResolver(engine=_sync_engine())
        # confidence 내림차순(0.95→0.8)·NULL 마지막.
        assert resolver.resolve(_KEBAB_A) == [_MIS_A1, _MIS_A2, _MIS_A3]
    finally:
        _cleanup()


def test_resolve_many_groups_and_missing() -> None:
    """2 kebab 시드 + 1 미시드 → resolve_many가 kebab별 그룹화·미존재 kebab 키 부재."""
    _skip_if_unreachable()
    try:
        _cleanup()
        _seed_catalog(_MIS_A1, _MIS_B1)
        _seed_crosslinks(
            [
                _link(kebab_id=_KEBAB_A, mis_id=_MIS_A1, confidence=0.9),
                _link(kebab_id=_KEBAB_B, mis_id=_MIS_B1, confidence=0.7),
            ]
        )
        resolver = MisconceptionCrosslinkResolver(engine=_sync_engine())
        result = resolver.resolve_many([_KEBAB_A, _KEBAB_B, _KEBAB_MISSING])
        assert result == {_KEBAB_A: [_MIS_A1], _KEBAB_B: [_MIS_B1]}
        assert _KEBAB_MISSING not in result  # 미존재 kebab은 키 부재
    finally:
        _cleanup()


def test_resolve_min_confidence_filter() -> None:
    """0.9·0.5·NULL 링크 + min_confidence=0.7 → 실 SQL `>=`로 0.9만(0.5·NULL 제외·보수)."""
    _skip_if_unreachable()
    try:
        _cleanup()
        _seed_catalog(_MIS_A1, _MIS_A2, _MIS_A3)
        _seed_crosslinks(
            [
                _link(kebab_id=_KEBAB_A, mis_id=_MIS_A1, confidence=0.9),
                _link(kebab_id=_KEBAB_A, mis_id=_MIS_A2, confidence=0.5),
                _link(kebab_id=_KEBAB_A, mis_id=_MIS_A3, confidence=None),
            ]
        )
        resolver = MisconceptionCrosslinkResolver(engine=_sync_engine())
        assert resolver.resolve(_KEBAB_A, min_confidence=0.7) == [_MIS_A1]
    finally:
        _cleanup()


# ── 테스트: resolve_canonical (정책 4분기·실 행 위) ────────────────────────
def test_resolve_canonical_ok_single_direct() -> None:
    """단독 직접매핑 → reason='ok'·canonical=그 mis(Numeric→float 정규화 포함)."""
    _skip_if_unreachable()
    try:
        _cleanup()
        _seed_catalog(_MIS_A1)
        _seed_crosslinks([_link(kebab_id=_KEBAB_A, mis_id=_MIS_A1, confidence=0.85)])
        resolver = MisconceptionCrosslinkResolver(engine=_sync_engine())
        sel = resolver.resolve_canonical(_KEBAB_A)
        assert sel.reason == "ok"
        assert sel.canonical_mis_id == _MIS_A1
        assert sel.ambiguous is False
        assert sel.direct_count == 1
    finally:
        _cleanup()


def test_resolve_canonical_tie_ambiguous() -> None:
    """직접매핑 2건 동일 최고 conf → canonical None·ambiguous·reason='tie'(오귀속 방지)."""
    _skip_if_unreachable()
    try:
        _cleanup()
        _seed_catalog(_MIS_A1, _MIS_A2)
        _seed_crosslinks(
            [
                _link(kebab_id=_KEBAB_A, mis_id=_MIS_A1, confidence=0.9),
                _link(kebab_id=_KEBAB_A, mis_id=_MIS_A2, confidence=0.9),
            ]
        )
        resolver = MisconceptionCrosslinkResolver(engine=_sync_engine())
        sel = resolver.resolve_canonical(_KEBAB_A)
        assert sel.reason == "tie"
        assert sel.canonical_mis_id is None
        assert sel.ambiguous is True
        assert sel.direct_count == 2
    finally:
        _cleanup()


def test_resolve_canonical_no_direct() -> None:
    """부분매핑/개념겹침만(직접매핑 부재) → canonical None·reason='no_direct'."""
    _skip_if_unreachable()
    try:
        _cleanup()
        _seed_catalog(_MIS_A1, _MIS_A2)
        _seed_crosslinks_ungated(
            [
                _link(kebab_id=_KEBAB_A, mis_id=_MIS_A1, link_type="부분매핑", confidence=0.9),
                _link(kebab_id=_KEBAB_A, mis_id=_MIS_A2, link_type="개념겹침", confidence=0.8),
            ]
        )
        resolver = MisconceptionCrosslinkResolver(engine=_sync_engine())
        sel = resolver.resolve_canonical(_KEBAB_A)
        assert sel.reason == "no_direct"
        assert sel.canonical_mis_id is None
        assert sel.direct_count == 0
    finally:
        _cleanup()


def test_resolve_canonical_no_links() -> None:
    """미시드 kebab → reason='no_links'·resolve=[](graceful·정직)."""
    _skip_if_unreachable()
    try:
        _cleanup()
        resolver = MisconceptionCrosslinkResolver(engine=_sync_engine())
        sel = resolver.resolve_canonical(_KEBAB_MISSING)
        assert sel.reason == "no_links"
        assert sel.canonical_mis_id is None
        assert resolver.resolve(_KEBAB_MISSING) == []
    finally:
        _cleanup()
