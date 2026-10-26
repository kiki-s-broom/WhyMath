"""적재 후 canonical 경쟁 거부 — 실 PostgreSQL 관통 (WHYMATH_RUN_INTEGRATION, HARN-216 ③).

**정본 사고의 재현** (2026-10-07 `G-crosslink-live-drift-disposition` 추가 검토): 라이브에 코퍼스에 없는
오귀속 행이 남아 있으면 코퍼스를 그대로 다시 적재해도 canonical이 고쳐지지 않는다. 같은 입력을 실 PG에
넣어 고정한다:

  ① 실측 4건(`angle-sum-non-triangle`·`period-of-scaled-sine` → wrong_winner,
     `division-by-zero`·`circle-radius-squared` → tie)을 실제 kebab·M-id·신뢰도로 재현하고 거부한다.
  ② 거부 시 **아무것도 쓰지 않는다** — 라이브 행은 그대로이고 코퍼스 행도 들어가지 않는다.
  ③ 대조군: 라이브 행이 코퍼스와 같은 트리플이면 업서트가 덮으므로 통과한다.
  ④ 해소 경로: 사람이 잔존 행을 삭제하면 같은 입력이 통과하고 canonical이 코퍼스 의도로 선다.
  ⑤ `promote --load` CLI가 종료 코드 4로 거부한다.

**안전장치**: 실측 kebab·M-id는 운영 데이터와 같은 이름이다. 그 kebab에 크로스링크 행이 이미 있는 DB
(= 운영/실데이터 DB)에서는 **건드리지 않고 건너뛴다** — 이 파일의 정리(cleanup)가 실행 행을 지우기 때문이다.
카탈로그 행은 *없을 때만* 넣고 이 테스트가 넣은 것만 지운다.

PG 미도달 시 graceful skip(`test_crosslink_fk_precheck_integration.py` 미러).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.misconception.crosslink_loader import (
    CanonicalFlipError,
    MisconceptionCrosslinkStore,
    load_crosslinks,
)
from whymath_backend.l1.misconception.crosslink_resolve import MisconceptionCrosslinkResolver
from whymath_backend.l4.misconception import crosslink_review
from whymath_backend.schema.misconception_crosslink import MisconceptionCrosslink

pytestmark = pytest.mark.integration

_SIGNED = "검수:Kiki 2026-10-13"
_CONTROL = "hflip-control-kebab"  # 합성 — 운영 데이터와 겹치지 않는다

# (kebab, 라이브 잔존 M-id·신뢰도, 코퍼스 M-id·신뢰도, 기대 판정) — 2026-10-07 실측 그대로.
_INCIDENT = [
    ("angle-sum-non-triangle", ("M0863", 0.95), ("M0493", 0.85), "wrong_winner"),
    ("period-of-scaled-sine", ("M0862", 0.95), ("M0152", 0.85), "wrong_winner"),
    ("division-by-zero", ("M0146", 0.85), ("M0003", 0.85), "tie"),
    ("circle-radius-squared", ("M0630", 0.93), ("M0848", 0.93), "tie"),
]
_KEBABS = [row[0] for row in _INCIDENT] + [_CONTROL]
_MIS_IDS = sorted({m for _, live, corpus, _ in _INCIDENT for m in (live[0], corpus[0])})


def _sync_engine() -> Any:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    settings = Settings()
    url = settings.sync_database_url
    return (
        create_engine(url, poolclass=NullPool) if settings.db_disable_pool else create_engine(url)
    )


def _skip_if_unusable() -> None:
    """PG 미도달이거나, 대상 kebab에 이미 행이 있는 DB(실데이터)면 건너뛴다."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:
            existing = conn.execute(
                text("SELECT count(*) FROM misconception_crosslink WHERE kebab_id = ANY(:k)"),
                {"k": _KEBABS},
            ).scalar_one()
            conn.execute(text("SELECT count(*) FROM misconception_catalog"))
    except Exception:
        pytest.skip("PostgreSQL 미도달(또는 마이그레이션 미적용) — 통합 테스트 건너뜀")
    finally:
        engine.dispose()
    if existing:
        pytest.skip(
            f"대상 kebab에 크로스링크 {existing}건이 이미 있다(실데이터 DB) — 건드리지 않는다"
        )


class _Seeded:
    """이 테스트가 카탈로그에 새로 넣은 M-id를 기억해 그것만 정리한다."""

    def __init__(self) -> None:
        self.inserted_catalog: list[str] = []


def _seed_catalog(seeded: _Seeded, mis_ids: list[str]) -> None:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from whymath_backend.db.models.misconception_catalog import MisconceptionCatalog

    engine = _sync_engine()
    try:
        with engine.begin() as conn:
            for mis_id in mis_ids:
                stmt = (
                    pg_insert(MisconceptionCatalog)
                    .values(
                        mis_id=mis_id,
                        canonical_statement="통합테스트 오개념.",
                        error_type="개념오류",
                        difficulty="중",
                    )
                    .on_conflict_do_nothing(index_elements=[MisconceptionCatalog.mis_id])
                    .returning(MisconceptionCatalog.mis_id)
                )
                if conn.execute(stmt).first() is not None:
                    seeded.inserted_catalog.append(mis_id)
    finally:
        engine.dispose()


def _seed_live(*rows: tuple[str, str, float]) -> None:
    """라이브 잔존 행 시딩 — 순수 쓰기 원시 함수(`populate`)로 직접 넣는다."""
    records = [
        MisconceptionCrosslink(
            kebab_id=kebab,
            mis_id=mis,
            link_type="직접매핑",
            confidence=conf,
            method="manual",
            note=_SIGNED,
        )
        for kebab, mis, conf in rows
    ]
    engine = _sync_engine()
    try:
        MisconceptionCrosslinkStore(engine=engine).populate(records)
    finally:
        engine.dispose()


def _db_rows() -> list[tuple[str, str, float]]:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT kebab_id, mis_id, confidence FROM misconception_crosslink "
                    "WHERE kebab_id = ANY(:k) ORDER BY kebab_id, mis_id"
                ),
                {"k": _KEBABS},
            ).all()
    finally:
        engine.dispose()
    return [(r.kebab_id, r.mis_id, float(r.confidence)) for r in rows]


def _cleanup(seeded: _Seeded) -> None:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM misconception_crosslink WHERE kebab_id = ANY(:k)"),
                {"k": _KEBABS},
            )
            if seeded.inserted_catalog:
                conn.execute(
                    text("DELETE FROM misconception_catalog WHERE mis_id = ANY(:ids)"),
                    {"ids": seeded.inserted_catalog},
                )
    finally:
        engine.dispose()


@pytest.fixture
def seeded() -> Any:
    _skip_if_unusable()
    state = _Seeded()
    try:
        _seed_catalog(state, [*_MIS_IDS, "HFLIP_C1", "HFLIP_C2"])
        yield state
    finally:
        _cleanup(state)


def _payload(*rows: tuple[str, str, float]) -> dict[str, Any]:
    return {
        "crosslinks": [
            {
                "kebab_id": kebab,
                "mis_id": mis,
                "link_type": "직접매핑",
                "confidence": conf,
                "note": _SIGNED,
            }
            for kebab, mis, conf in rows
        ]
    }


# ── ① 실측 4건 재현 + ② 쓰기 0건 ──────────────────────────────────────────────
@pytest.mark.parametrize(("kebab", "live", "corpus", "expected"), _INCIDENT)
def test_incident_case_is_refused_and_nothing_is_written(
    seeded: _Seeded,
    kebab: str,
    live: tuple[str, float],
    corpus: tuple[str, float],
    expected: str,
) -> None:
    _seed_live((kebab, *live))
    before = _db_rows()

    with pytest.raises(CanonicalFlipError) as info:
        load_crosslinks(None, _payload((kebab, *corpus)), engine=_sync_engine())

    (verdict,) = info.value.verdicts
    assert verdict.kebab_id == kebab and verdict.verdict == expected
    assert [r.mis_id for r in verdict.rivals] == [live[0]]
    assert live[0] in str(info.value) and kebab in str(info.value)
    assert _db_rows() == before, "거부했으면 코퍼스 행을 쓰면 안 된다(쓰기 0건)"


def test_all_four_incidents_in_one_load_are_listed_and_the_clean_row_is_not_written(
    seeded: _Seeded,
) -> None:
    """68건 적재의 축소판 — 4건 전부 열거하고, 같이 실린 정상 행(대조군)도 쓰지 않는다."""
    _seed_live(*[(k, *live) for k, live, _, _ in _INCIDENT])
    before = _db_rows()
    rows = [(k, *corpus) for k, _, corpus, _ in _INCIDENT] + [(_CONTROL, "HFLIP_C1", 0.9)]

    with pytest.raises(CanonicalFlipError) as info:
        load_crosslinks(None, _payload(*rows), engine=_sync_engine())

    assert {v.kebab_id: v.verdict for v in info.value.verdicts} == {
        k: expected for k, _, _, expected in _INCIDENT
    }
    assert _CONTROL not in str(info.value)
    assert _db_rows() == before, "정상 kebab도 같은 적재에 실렸다면 쓰지 않는다(부분 적재 0)"


# ── ③ 대조군 ─────────────────────────────────────────────────────────────────
def test_live_row_with_the_same_triplet_is_overwritten_and_loads(seeded: _Seeded) -> None:
    """라이브가 코퍼스와 같은 kebab·M-id·link_type이면 경쟁이 아니라 갱신이다 — 판정이 막으면 고장."""
    _seed_live((_CONTROL, "HFLIP_C1", 0.99))
    n = load_crosslinks(None, _payload((_CONTROL, "HFLIP_C1", 0.85)), engine=_sync_engine())
    assert n == 1
    assert _db_rows() == [(_CONTROL, "HFLIP_C1", 0.85)], "코퍼스 값으로 갱신되어야 한다"


def test_lower_confidence_survivor_does_not_block_the_load(seeded: _Seeded) -> None:
    _seed_live((_CONTROL, "HFLIP_C2", 0.40))
    assert load_crosslinks(None, _payload((_CONTROL, "HFLIP_C1", 0.85)), engine=_sync_engine()) == 1
    assert _db_rows() == [(_CONTROL, "HFLIP_C1", 0.85), (_CONTROL, "HFLIP_C2", 0.40)]


# ── ④ 해소 경로: 잔존 행 삭제(사람 확인) 뒤 같은 입력이 통과하고 canonical이 선다 ─────────
def test_deleting_the_survivor_resolves_the_refusal(seeded: _Seeded) -> None:
    from sqlalchemy import text

    kebab, live, corpus, _ = _INCIDENT[0]
    _seed_live((kebab, *live))
    with pytest.raises(CanonicalFlipError):
        load_crosslinks(None, _payload((kebab, *corpus)), engine=_sync_engine())

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # 사람이 오귀속을 확인하고 지우는 단계
            conn.execute(
                text("DELETE FROM misconception_crosslink WHERE kebab_id = :k AND mis_id = :m"),
                {"k": kebab, "m": live[0]},
            )
        assert load_crosslinks(None, _payload((kebab, *corpus)), engine=engine) == 1
        selection = MisconceptionCrosslinkResolver(engine=engine).resolve_canonical(kebab)
    finally:
        engine.dispose()
    assert selection.canonical_mis_id == corpus[0] and selection.reason == "ok"


# ── ⑤ CLI 종료 코드 ──────────────────────────────────────────────────────────
def _queue_file(tmp_path: Path, kebab: str, mis_id: str, conf: float) -> Path:
    row = {
        "kebab_id": kebab,
        "mis_id": mis_id,
        "link_type": "직접매핑",
        "confidence": conf,
        "rationale": "통합테스트 근거",
        "status": "approved",
        "reviewer": "kiki",
        "reviewed_on": "2026-10-13",
        "note": None,
    }
    path = tmp_path / "queue.json"
    path.write_text(json.dumps({"review_queue": [row]}, ensure_ascii=False), encoding="utf-8")
    return path


def test_promote_load_exits_4_listing_the_rival_and_writes_nothing(
    seeded: _Seeded, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    kebab, live, corpus, _ = _INCIDENT[0]
    _seed_live((kebab, *live))
    before = _db_rows()

    code = crosslink_review.main(
        ["promote", "--queue", str(_queue_file(tmp_path, kebab, *corpus)), "--load"]
    )
    out = capsys.readouterr().out

    assert code == 4
    assert kebab in out and "M0863(0.95)" in out and "아무것도 쓰지 않았습니다" in out
    assert _db_rows() == before


def test_promote_load_exits_0_when_nothing_competes(
    seeded: _Seeded, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    kebab, _, corpus, _ = _INCIDENT[0]
    code = crosslink_review.main(
        ["promote", "--queue", str(_queue_file(tmp_path, kebab, *corpus)), "--load"]
    )
    assert code == 0 and "적재 완료" in capsys.readouterr().out
    assert _db_rows() == [(kebab, corpus[0], corpus[1])]
