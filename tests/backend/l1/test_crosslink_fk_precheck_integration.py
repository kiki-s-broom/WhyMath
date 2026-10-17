"""적재 전 외래키 대상 사전확인 — 실 PostgreSQL 관통 (WHYMATH_RUN_INTEGRATION, HARN-302).

**정본 사고의 재현** (2026-10-07 G-misc40 DB 동기화): 카탈로그에 없는 `mis_id`를 포함한 크로스링크 적재가
첫 행에서 `ForeignKeyViolation`으로 실패했다. 이 파일은 같은 입력을 실 PG에 넣어 세 가지를 고정한다.

  ① 누락 키가 여럿이면 **전건** 열거하고 거부한다(수정 전: 첫 행의 키 하나만 말하는 `IntegrityError`).
  ② 거부 시 **존재하는 키의 행도 쓰지 않는다**(쓰기 0건 — 부분 적재 없음).
  ③ `populate`(순수 쓰기 원시 함수)는 그대로다 — 사전확인을 우회한 직접 쓰기는 DB 외래키가 마지막 방어선이다.
  ④ `promote --load` CLI가 종료 코드 3으로 거부한다(블록이 이 코드를 보고 후속 쓰기를 멈출 수 있다).

PG 미도달 시 graceful skip(`test_misconception_crosslink_integration.py` 미러). 합성 mis_id(`HFK...`)만 쓴다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.fk_precheck import ForeignKeyTargetMissingError
from whymath_backend.l1.misconception.catalog_loader import load_misconceptions
from whymath_backend.l1.misconception.crosslink_loader import (
    MisconceptionCrosslinkStore,
    load_crosslinks,
)
from whymath_backend.l4.misconception import crosslink_review

pytestmark = pytest.mark.integration

_KEBAB_A = "distribution-over-power"
_KEBAB_B = "sign-flip-in-inequality"
_PRESENT = "HFK01"  # 카탈로그에 시딩
_PRESENT_2 = "HFK02"
_GONE_1 = "HFK_GONE1"  # 카탈로그에 없음
_GONE_2 = "HFK_GONE2"
_ALL = [_PRESENT, _PRESENT_2, _GONE_1, _GONE_2]


def _sync_engine() -> Any:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    settings = Settings()
    url = settings.sync_database_url
    return (
        create_engine(url, poolclass=NullPool) if settings.db_disable_pool else create_engine(url)
    )


def _skip_if_unreachable() -> None:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT count(*) FROM misconception_crosslink"))
            conn.execute(text("SELECT count(*) FROM misconception_catalog"))
    except Exception:
        pytest.skip("PostgreSQL 미도달(또는 마이그레이션 미적용) — 통합 테스트 건너뜀")
    finally:
        engine.dispose()


def _cleanup() -> None:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM misconception_crosslink WHERE mis_id = ANY(:ids)"), {"ids": _ALL}
            )
            conn.execute(
                text("DELETE FROM misconception_catalog WHERE mis_id = ANY(:ids)"), {"ids": _ALL}
            )
    finally:
        engine.dispose()


def _seed_catalog(*mis_ids: str) -> None:
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


def _crosslink_count() -> int:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:
            return int(
                conn.execute(
                    text("SELECT count(*) FROM misconception_crosslink WHERE mis_id = ANY(:ids)"),
                    {"ids": _ALL},
                ).scalar_one()
            )
    finally:
        engine.dispose()


def _payload(*mis_ids: str) -> dict[str, Any]:
    """로더 형식 payload — 게이트(method=manual·검수 서명)를 통과하는 promote 산출물 형태."""
    kebabs = [_KEBAB_A, _KEBAB_B]
    return {
        "crosslinks": [
            {
                "kebab_id": kebabs[i % 2],
                "mis_id": mid,
                "link_type": "직접매핑",
                "confidence": 0.9,
                "note": "검수:kiki 2026-10-07",
            }
            for i, mid in enumerate(mis_ids)
        ]
    }


def test_missing_targets_are_all_listed_and_nothing_is_written() -> None:
    """사고 재현 — 존재 2 + 누락 2. 거부하고 누락 2건을 전부 말하며, 존재하는 2건도 쓰지 않는다."""
    _skip_if_unreachable()
    try:
        _cleanup()
        _seed_catalog(_PRESENT, _PRESENT_2)
        payload = _payload(_PRESENT, _GONE_1, _PRESENT_2, _GONE_2)

        with pytest.raises(ForeignKeyTargetMissingError) as info:
            load_crosslinks(None, payload, engine=_sync_engine())

        (item,) = info.value.missing
        assert item.constraint == "misconception_crosslink.mis_id -> misconception_catalog.mis_id"
        assert item.values == (_GONE_1, _GONE_2), "누락 키는 첫 하나가 아니라 전건이어야 한다"
        assert _crosslink_count() == 0, "거부했으면 존재하는 키의 행도 쓰면 안 된다(쓰기 0건)"
    finally:
        _cleanup()


def test_all_targets_present_still_loads() -> None:
    """대조군 — 대상이 전부 있으면 정상 적재(사전확인이 모든 적재를 막으면 고장이다)."""
    _skip_if_unreachable()
    try:
        _cleanup()
        _seed_catalog(_PRESENT, _PRESENT_2)
        assert load_crosslinks(None, _payload(_PRESENT, _PRESENT_2), engine=_sync_engine()) == 2
        assert _crosslink_count() == 2
    finally:
        _cleanup()


def test_precheck_does_not_modify_the_database() -> None:
    """확인 단계는 읽기 전용 — 호출 전후 카탈로그 행 수가 같고 크로스링크는 0건이다."""
    _skip_if_unreachable()
    from sqlalchemy import text

    from whymath_backend.schema.misconception_crosslink import MisconceptionCrosslink

    try:
        _cleanup()
        _seed_catalog(_PRESENT)
        records = [
            MisconceptionCrosslink.model_validate(r)
            for r in _payload(_PRESENT, _GONE_1)["crosslinks"]
        ]
        engine = _sync_engine()
        try:
            with engine.connect() as conn:
                before = conn.execute(
                    text("SELECT count(*) FROM misconception_catalog")
                ).scalar_one()
            missing = MisconceptionCrosslinkStore(engine=engine).missing_fk_targets(records)
            with engine.connect() as conn:
                after = conn.execute(
                    text("SELECT count(*) FROM misconception_catalog")
                ).scalar_one()
        finally:
            engine.dispose()
        assert [m.values for m in missing] == [(_GONE_1,)]
        assert before == after and _crosslink_count() == 0
    finally:
        _cleanup()


def test_populate_is_unchanged_and_the_database_constraint_is_the_last_defense() -> None:
    """사전확인을 우회한 직접 쓰기(populate)는 종전대로 DB 외래키가 막는다 — 제약을 대체하지 않는다."""
    _skip_if_unreachable()
    from sqlalchemy.exc import IntegrityError

    from whymath_backend.schema.misconception_crosslink import MisconceptionCrosslink

    try:
        _cleanup()
        records = [
            MisconceptionCrosslink.model_validate(r) for r in _payload(_GONE_1)["crosslinks"]
        ]
        with pytest.raises(IntegrityError):
            MisconceptionCrosslinkStore(engine=_sync_engine()).populate(records)
        assert _crosslink_count() == 0
    finally:
        _cleanup()


# ── CLI: promote --load 종료 코드 ─────────────────────────────────────────
def _queue_file(tmp_path: Path, *mis_ids: str) -> Path:
    kebabs = [_KEBAB_A, _KEBAB_B]
    rows = [
        {
            "kebab_id": kebabs[i % 2],
            "mis_id": mid,
            "link_type": "직접매핑",
            "confidence": 0.9,
            "rationale": "통합테스트 근거",
            "status": "approved",
            "reviewer": "kiki",
            "reviewed_on": "2026-10-07",
            "note": None,
        }
        for i, mid in enumerate(mis_ids)
    ]
    path = tmp_path / "queue.json"
    path.write_text(json.dumps({"review_queue": rows}, ensure_ascii=False), encoding="utf-8")
    return path


def test_promote_load_exits_3_listing_all_missing_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _skip_if_unreachable()
    try:
        _cleanup()
        _seed_catalog(_PRESENT)
        queue = _queue_file(tmp_path, _PRESENT, _GONE_1, _GONE_2)
        code = crosslink_review.main(["promote", "--queue", str(queue), "--load"])
        out = capsys.readouterr().out
        assert code == 3
        assert _GONE_1 in out and _GONE_2 in out and "아무것도 쓰지 않았습니다" in out
        assert _PRESENT not in out.split("누락")[-1], "존재하는 키를 누락으로 보고하면 안 된다"
        assert _crosslink_count() == 0
    finally:
        _cleanup()


def test_promote_load_exits_0_when_every_target_exists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _skip_if_unreachable()
    try:
        _cleanup()
        _seed_catalog(_PRESENT, _PRESENT_2)
        queue = _queue_file(tmp_path, _PRESENT, _PRESENT_2)
        assert crosslink_review.main(["promote", "--queue", str(queue), "--load"]) == 0
        capsys.readouterr()
        assert _crosslink_count() == 2
    finally:
        _cleanup()
