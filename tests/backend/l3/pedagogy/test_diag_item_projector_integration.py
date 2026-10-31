"""PED-10 형성평가 diag_item 슬롯 채움 — 실 PG 통합 증명(기본 SKIP).

`test_e2e_pedagogy_pilot_integration.py`(PED-01 파일럿)의 이차함수 소단원 고정물을 재사용해,
컴파일된 4목표(CONCEPT/PROCEDURE/REPRESENT/MODELING) 각각의 `concept_nodes`(atom code 1개씩:
`10공수1-02-06-{1,2,3,2}`)가 실 `atom_probe`(원자 백본 코퍼스에서 적재)와 직접 교집합으로 이어져
`diag_item` 슬롯이 실제로 채워짐을 증명한다 — 04g §7.2가 가정한 crosswalk 없이도 성립함을 라이브로
재확인한다(모듈 docstring의 grain 다리 정정).

- **실 PG** — `WHYMATH_DATABASE_URL` 소싱. 미도달이면 skip.
- **LLM 0** — 투영은 결정론(atom_probe 3필드 그대로 옮김·생성 없음).
- 정리는 try/finally(evidence 무관·unit_spec CASCADE로 objective·슬롯 정리 — atom_probe는 공유
  참조 테이블이라 삭제하지 않는다, `test_atom_probe_integration.py`와 동일 원칙).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from whymath_backend.config import Settings
from whymath_backend.l1.atom_probe.projection import (
    AtomProbeStore,
    load_atom_probes_from_json,
    populate_atom_probes,
)
from whymath_backend.l1.pedagogy.pack_loader import PedagogyPackStore, load_packs
from whymath_backend.l1.pedagogy.unit_compiler import (
    UnitSpecStore,
    compile_unit,
    load_statements_by_code,
    load_valid_atom_codes,
)
from whymath_backend.l1.pedagogy.unit_compiler import load_packs as load_packs_mem
from whymath_backend.l3.pedagogy.diag_item_projector import (
    DIAG_ITEM_PROJECTOR_TAG,
    run_diag_item_fill,
)

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CORPUS = _REPO_ROOT / "data" / "corpus"
_UNIT_YAML = _CORPUS / "units_v1" / "quadratic_maxmin.unit.yaml"
_PACKS_DIR = _CORPUS / "pedagogy_packs_v1"
_GRAPH = _CORPUS / "atom_graph_v1" / "graph.json"
_STANDARDS = _CORPUS / "standards_v1" / "standards.json"

_UNIT_ID = "10공수1-이차함수-최대최소"


def _settings() -> Settings:
    return Settings()


async def _pg_reachable() -> bool:
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


def _cleanup(engine: object) -> None:
    """unit_spec 삭제로 objective·slot CASCADE — atom_probe는 공유 참조 테이블이라 무삭제."""
    with engine.begin() as conn:  # type: ignore[attr-defined]
        conn.execute(text("DELETE FROM unit_spec WHERE unit_id = :u"), {"u": _UNIT_ID})


def _skip_unless_ready() -> None:
    if not asyncio.run(_pg_reachable()):
        pytest.skip("실 PG 미도달 — WHYMATH_DATABASE_URL 확인(통합 잡에서 실행)")
    fixtures_exist = (
        _UNIT_YAML.exists() and _GRAPH.exists() and _STANDARDS.exists() and _PACKS_DIR.exists()
    )
    if not fixtures_exist:
        pytest.skip("파일럿 고정물(units_v1/atom_graph_v1/standards_v1/pedagogy_packs_v1) 미존재")


def _seed_unit(engine: object) -> None:
    """atom_probe·팩·unit_spec/objective를 심는다(4목표 — diag_item count=2씩 발주)."""
    # ── ① atom_probe 시드 — 실 원자 백본 코퍼스(이 소단원의 3개 atom code가 실제로 보유). ──
    probe_records = load_atom_probes_from_json(_GRAPH)
    populate_atom_probes(probe_records, store=AtomProbeStore(engine=engine))

    # ── ② 팩 시드 + 컴파일 + unit_spec/objective 시드. ──────────────────────────────
    load_packs(None, _PACKS_DIR, store=PedagogyPackStore(engine=engine))
    compiled = compile_unit(
        _UNIT_YAML.read_text(encoding="utf-8"),
        packs=load_packs_mem(_PACKS_DIR),
        valid_atom_codes=load_valid_atom_codes(_GRAPH),
        statements_by_code=load_statements_by_code(_STANDARDS),
    )
    assert len(compiled.objective_rows) == 4
    UnitSpecStore(engine=engine).seed(compiled)


def _unit_slot_rows(engine: object) -> list[Any]:
    """**이 소단원**의 diag_item 슬롯 행.

    `run_diag_item_fill`은 learning_objective를 전량 조회하므로 리포트(`filled` 등)는 공유 DB의
    다른 단원까지 센 전역 값이다. 다른 통합 테스트가 단원을 남기면 전역 값이 달라지므로, 이
    파일의 단언은 전역 리포트가 아니라 이 소단원으로 좁힌 DB 행으로 한다(OPS-137 검토 반영).
    """
    with engine.connect() as conn:  # type: ignore[attr-defined]
        return list(
            conn.execute(
                text(
                    "SELECT id, payload, status FROM pedagogy_content_slot "
                    "WHERE objective_id LIKE :p AND slot_type = 'diag_item' "
                    "ORDER BY id"
                ),
                {"p": f"{_UNIT_ID}:%"},
            ).all()
        )


def test_diag_item_slots_filled_from_atom_probe_via_direct_code_bridge() -> None:
    """1회차 — 4목표가 atom code 직접 교집합으로 슬롯 0을 채우고 prescreen까지 통과한다."""
    _skip_unless_ready()
    engine = create_engine(_settings().sync_database_url)
    try:
        _cleanup(engine)
        _seed_unit(engine)

        # ── ③ PED-10 실행 — 슬롯을 미리 만들지 않은 채(블랭크) 직접 채운다. ──────────────
        report = run_diag_item_fill(engine=engine)

        # 각 목표 concept_nodes는 atom code 1개뿐이라(발주 2 中) 부분 채움 1건씩 = 이 단원 4건.
        # 리포트는 전역 값이라 하한만 본다 — 이 단원의 사실은 아래 DB 행이 정본이다.
        assert report.filled >= 4
        rows = _unit_slot_rows(engine)
        assert len(rows) == 4
        for row in rows:
            assert row.id.endswith(":diag_item:0")
            assert row.status == "PRESCREENED"  # prescreen까지 이 함수가 수행.
            payload = row.payload
            assert payload["generated_by"] == DIAG_ITEM_PROJECTOR_TAG
            assert payload["atom_code"].startswith("10공수1-02-06-")
            assert payload["body"]  # 실 atom_probe 발문(빈 문자열 아님).
    finally:
        _cleanup(engine)
        engine.dispose()


# OPS-137이 이 파일을 CI에 편입하며 실 PG 실행으로 확인한 결함: 연속 2회 실행하면 이 단원의
# diag_item 슬롯이 4행 → 8행이 된다(1회차에 PRESCREENED가 된 슬롯 0을 건너뛰되 후보 원자를
# 소비하지 않아 같은 원자가 슬롯 1에 다시 채워진다). 판정·수정은 PED-46이 소유한다.
# 표식은 **재실행 단언만** 덮는다 — 1회차 사실은 위 테스트가 표식 없이 단언하고, 이 테스트의
# 전제(1회차 4행)가 깨지면 `pytest.fail`(AssertionError가 아니다)로 XFAIL이 아닌 FAIL이 된다.
# strict라서 결함이 고쳐져 통과(XPASS)하면 표식을 지우라고 CI가 red로 알린다.
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="PED-46: run_diag_item_fill 재실행이 같은 원자를 다음 슬롯에 중복 채움(4행→8행)",
)
def test_diag_item_fill_rerun_is_idempotent() -> None:
    """④ 멱등 — 재실행해도 이 단원은 같은 4건(같은 id upsert·중복 생성 0)."""
    _skip_unless_ready()
    engine = create_engine(_settings().sync_database_url)
    try:
        _cleanup(engine)
        _seed_unit(engine)
        run_diag_item_fill(engine=engine)
        first = _unit_slot_rows(engine)
        if len(first) != 4:
            pytest.fail(f"전제 붕괴 — 1회차 이 단원 슬롯 {len(first)}행(기대 4). 멱등 판정 불가")

        run_diag_item_fill(engine=engine)
        second = _unit_slot_rows(engine)
        assert len(second) == 4  # 재실행이 새 행을 늘리지 않는다.
        assert [r.id for r in second] == [r.id for r in first]
    finally:
        _cleanup(engine)
        engine.dispose()


def test_reviewed_slot_untouched_on_rerun() -> None:
    """이미 APPROVED로 전이된 diag_item 슬롯은 재실행으로도 갱신되지 않는다(select-vs-generate)."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("실 PG 미도달 — WHYMATH_DATABASE_URL 확인(통합 잡에서 실행)")
    fixtures_exist = (
        _UNIT_YAML.exists() and _GRAPH.exists() and _STANDARDS.exists() and _PACKS_DIR.exists()
    )
    if not fixtures_exist:
        pytest.skip("파일럿 고정물 미존재")

    settings = _settings()
    engine = create_engine(settings.sync_database_url)
    try:
        _cleanup(engine)
        populate_atom_probes(
            load_atom_probes_from_json(_GRAPH), store=AtomProbeStore(engine=engine)
        )
        load_packs(None, _PACKS_DIR, store=PedagogyPackStore(engine=engine))
        compiled = compile_unit(
            _UNIT_YAML.read_text(encoding="utf-8"),
            packs=load_packs_mem(_PACKS_DIR),
            valid_atom_codes=load_valid_atom_codes(_GRAPH),
            statements_by_code=load_statements_by_code(_STANDARDS),
        )
        UnitSpecStore(engine=engine).seed(compiled)

        run_diag_item_fill(engine=engine)
        obj0 = compiled.objective_rows[0]["id"]
        slot0_id = f"{obj0}:diag_item:0"
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(
                text(
                    "UPDATE pedagogy_content_slot SET status='APPROVED', "
                    "payload = payload || '{\"human_edited\": true}'::jsonb "
                    "WHERE id = :id"
                ),
                {"id": slot0_id},
            )

        run_diag_item_fill(engine=engine)  # 재실행 — 사람이 수정한 승인 슬롯을 되돌리면 안 된다.

        with engine.connect() as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                text("SELECT status, payload FROM pedagogy_content_slot WHERE id = :id"),
                {"id": slot0_id},
            ).one()
            assert row.status == "APPROVED"
            assert row.payload.get("human_edited") is True  # 재적재로 덮이지 않았다.
    finally:
        _cleanup(engine)
        engine.dispose()
