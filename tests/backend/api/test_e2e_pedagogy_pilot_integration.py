"""PED-01 파일럿 E2E 통합 증명 — 컴파일→생성→예심→검수→릴리스→evidence→런타임 관통(기본 SKIP).

이차함수 소단원 1개를 5단계 파이프라인 전 구간으로 *실 PG*에서 1회 관통해, DSL 스키마가 전 단계를
지탱함을 증명한다(acceptance "1회 완주 후 스키마 동결"). 관통이 성립하면 스키마 동결 lock 테스트
(`test_pedagogy_dsl_schema_freeze.py`)가 필드셋을 잠근다.

- **실 PG** — `WHYMATH_DATABASE_URL` 소싱. 미도달이면 skip(`test_e2e_vertical_slice_integration.py`
  self-skip 패턴 동형). CI 통합 잡에서 실행.
- **LLM 0** — 생성은 결정론 SymPy 검증 픽스처(hermetic 생성 단계). 런타임은 팩 주입 조립만.
- **자체 저작** — 파일럿 콘텐츠·팩은 WhyMath 자체 저작(provenance_id=NULL 정당).

정리는 try/finally로 FK 안전 순서 보장(evidence → unit_spec CASCADE).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from whymath_backend.api._crypto import (
    build_evidence_payload_cipher,
    encrypt_evidence_payload,
    resolve_evidence_payload,
)
from whymath_backend.composition import default_expression_equivalence
from whymath_backend.config import Settings
from whymath_backend.l1.pedagogy.pack_loader import PedagogyPackStore, load_packs
from whymath_backend.l1.pedagogy.unit_compiler import (
    UnitSpecStore,
    compile_unit,
    load_statements_by_code,
    load_valid_atom_codes,
)
from whymath_backend.l1.pedagogy.unit_compiler import (
    load_packs as load_packs_mem,
)
from whymath_backend.l2.evidence_event_store import EvidenceEventStore
from whymath_backend.l3.pedagogy.prescreen import PrescreenStore, prescreen_rows
from whymath_backend.l3.pedagogy.review import (
    ReviewStore,
    review_rows,
    verb_confirms_k_type,
)
from whymath_backend.l3.pedagogy.slot_generator import ContentSlotStore, build_slot_rows
from whymath_backend.l4.pedagogy.k_type_resolver import KTypeResolver
from whymath_backend.l4.pedagogy.pack_registry import get_pack, reset_pack_cache
from whymath_backend.l4.pedagogy.prompt_assembler import build_system_prompt

pytestmark = pytest.mark.integration

_SECRET = "integration-jwt-secret-0123456789abcdef"
# 테스트용 evidence 암호화 키(base64 32바이트) — 라운드트립 증명용(시크릿 아님·로컬 결정론).
_EVIDENCE_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = _REPO_ROOT / "data" / "corpus"
_UNIT_YAML = _CORPUS / "units_v1" / "quadratic_maxmin.unit.yaml"
_PACKS_DIR = _CORPUS / "pedagogy_packs_v1"
_GRAPH = _CORPUS / "atom_graph_v1" / "graph.json"
_STANDARDS = _CORPUS / "standards_v1" / "standards.json"

_UNIT_ID = "10공수1-이차함수-최대최소"


def _settings() -> Settings:
    return Settings(
        jwt_secret_key=SecretStr(_SECRET),
        evidence_payload_encryption_key=SecretStr(_EVIDENCE_KEY),
    )


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
    """FK 안전 정리 — evidence(느슨참조) 먼저, unit_spec 삭제로 목표·슬롯 CASCADE."""
    with engine.begin() as conn:  # type: ignore[attr-defined]
        conn.execute(
            text("DELETE FROM evidence_event WHERE objective_id LIKE :p"),
            {"p": f"{_UNIT_ID}:%"},
        )
        conn.execute(text("DELETE FROM unit_spec WHERE unit_id = :u"), {"u": _UNIT_ID})


def test_pilot_pipeline_e2e() -> None:
    if not asyncio.run(_pg_reachable()):
        pytest.skip("실 PG 미도달 — WHYMATH_DATABASE_URL 확인(통합 잡에서 실행)")

    settings = _settings()
    engine = create_engine(settings.sync_database_url)
    try:
        _cleanup(engine)

        # ── ① 팩 시드 ─────────────────────────────────────────────────
        pack_store = PedagogyPackStore(engine=engine)
        seeded = load_packs(None, _PACKS_DIR, store=pack_store)
        assert seeded == 7  # 7 지식유형 팩

        # ── ② 컴파일 + 시드(unit_spec 1 + learning_objective 4·status=DRAFT) ──
        compiled = compile_unit(
            _UNIT_YAML.read_text(encoding="utf-8"),
            packs=load_packs_mem(_PACKS_DIR),
            valid_atom_codes=load_valid_atom_codes(_GRAPH),
            statements_by_code=load_statements_by_code(_STANDARDS),
        )
        assert compiled.unit_spec_row["status"] == "DRAFT"
        assert len(compiled.objective_rows) == 4
        UnitSpecStore(engine=engine).seed(compiled)

        # ── ③ 생성(work_order 전 슬롯 DRAFT·숫자형 sympy_verified) ──────
        all_rows: list[dict] = []
        for obj in compiled.objective_rows:
            all_rows.extend(
                build_slot_rows(
                    obj["id"], obj["slot_manifest"], equivalence=default_expression_equivalence()
                )
            )
        assert all_rows and all(r["status"] == "DRAFT" for r in all_rows)
        ContentSlotStore(engine=engine).seed(all_rows)

        # ── ④ 예심(0~3·PRESCREENED) ─────────────────────────────────
        scored = prescreen_rows(all_rows)
        assert all(0 <= s <= 3 for _id, s in scored)
        PrescreenStore(engine=engine).apply(scored)

        # ── ⑤ 검수(APPROVED·reviewed_by 기계·k_type_verified 정직) ─────
        # EOS-89: 생성 단계와 같은 항등 판정 능력을 검수 단계에도 넘긴다 — 주입된 행은
        # `verification` 주장을 가지므로 능력 없이 검수하면 LookupError다(Codex P1 #1024).
        verdicts = review_rows(all_rows, equivalence=default_expression_equivalence())
        assert all(v.approved for _id, v in verdicts)  # 정상 픽스처 전건 승인
        ReviewStore(engine=engine).apply(verdicts)
        verified = [
            obj["id"]
            for obj in compiled.objective_rows
            if verb_confirms_k_type(obj["source_verb"], obj["k_type"])
        ]
        ReviewStore(engine=engine).set_k_type_verified(verified)

        with engine.begin() as conn:
            # 검수 각인 확인.
            reviewed = conn.execute(
                text(
                    "SELECT count(*) FROM pedagogy_content_slot "
                    "WHERE objective_id LIKE :p AND status='APPROVED' "
                    "AND reviewed_by LIKE 'machine:%'"
                ),
                {"p": f"{_UNIT_ID}:%"},
            ).scalar_one()
            assert reviewed == len(all_rows)
            # 정직 gradient — 3 성숙 목표 확정·MODELING(OBJ-04) 스텁 미확정.
            verified_cnt = conn.execute(
                text(
                    "SELECT count(*) FROM learning_objective "
                    "WHERE unit_id = :u AND k_type_verified"
                ),
                {"u": _UNIT_ID},
            ).scalar_one()
            assert verified_cnt == 3

            # ── ⑥ 릴리스 게이트(fill_pct=100·releasable) → ACTIVE 승격 ──
            worst = conn.execute(
                text("SELECT min(fill_pct) FROM v_manifest_fill WHERE unit_id = :u"),
                {"u": _UNIT_ID},
            ).scalar_one()
            assert float(worst) == 100.0
            releasable = conn.execute(
                text("SELECT releasable FROM v_unit_release_gate WHERE unit_id = :u"),
                {"u": _UNIT_ID},
            ).scalar_one()
            assert releasable is True
            conn.execute(
                text("UPDATE unit_spec SET status='ACTIVE' " "WHERE unit_id = :u AND :ok"),
                {"u": _UNIT_ID, "ok": True},
            )
            status = conn.execute(
                text("SELECT status FROM unit_spec WHERE unit_id = :u"),
                {"u": _UNIT_ID},
            ).scalar_one()
            assert status == "ACTIVE"

        # ── ⑦ evidence 봉투 암호화 라운드트립(B1·평문 유출 0) ─────────
        obj0 = compiled.objective_rows[0]["id"]
        cipher = build_evidence_payload_cipher(settings)
        original = json.dumps({"utterance": "학생 원문 발화", "step": 1}, ensure_ascii=False)
        ct, nonce = encrypt_evidence_payload(cipher, original)
        assert ct is not None and nonce is not None
        ev_store = EvidenceEventStore(engine=engine)
        ev_store.log(
            session_id=uuid.uuid4(),
            objective_id=obj0,
            k_type="CONCEPT",
            event_type="COUNTEREXAMPLE_GEN",
            meta={"item": "diag_item:0"},  # 비민감 메타만 평문
            payload_encrypted=ct,
            payload_nonce=nonce,
        )
        fetched = ev_store.fetch_by_objective(obj0)
        assert len(fetched) == 1
        f_ct, f_nonce, f_meta = fetched[0]
        assert resolve_evidence_payload(cipher, f_ct, f_nonce) == original  # 복호 왕복
        assert "학생 원문 발화" not in json.dumps(f_meta, ensure_ascii=False)  # 평문 유출 0

        # ── ⑧ 런타임 — resolve→get_pack→4계층 주입(OFF 바이트동일) ────
        k = KTypeResolver(engine=engine).resolve("10공수1-02-06-1")
        assert k == "CONCEPT"
        reset_pack_cache()
        pack = get_pack(k)
        assert pack is not None
        base = "BASE_SYSTEM_PROMPT"
        assembled = build_system_prompt(base_system=base, pack=pack)
        assert assembled.startswith(base)  # 1계층 base 보존
        assert "예와 비예" in assembled  # 팩 socratic 계층 주입(CONCEPT 발문 fragment)
        # OFF/무팩 회귀 0 계약 — pack None이면 base와 바이트동일.
        assert build_system_prompt(base_system=base, pack=None) == base
    finally:
        _cleanup(engine)
        engine.dispose()
