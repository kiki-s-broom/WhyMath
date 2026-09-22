"""동등문제 생성 오케스트레이터 *통합테스트* — S2-d end-to-end(integration 마커·실 PG+pgvector).

마이그레이션 head가 적용된 **실 PostgreSQL+pgvector**(`problem`·`problem_concept`·`concept`·
`problem_embedding`)에 자작 자체생성 후보를 흘려 S2 파이프라인이 실제로 닫히는지 본다:
  ① 개념 선적재(source_id) → 후보 생성(ScriptedGenerator) → S2-a 게이트 통과 → S2-c dedup fresh
     → **S2-b 실 저장(problem+problem_concept)+S2-c 임베딩 적재**(problem_embedding) 실증.
  ② **같은 후보 2회차는 rejected_duplicate** — 1회차가 발문 벡터를 index에 실어, 과유사 게이트가
     실제로 코퍼스 중복을 막는다(생성→게이트→dedup→저장→2회차 중복거부 전 구간 실증).

`FakeEmbeddingProvider(dim=settings.embedding_dim)`로 마이그레이션 컬럼 `vector(embedding_dim)`과
차원을 맞춘다(라이브 모델 불요·hermetic하면서 실 pgvector 왕복). Fake는 어휘 해시라 같은 발문은
동일 벡터→코사인 1.0이 되어 2회차 중복을 결정론적으로 재현한다. PG/pgvector 미도달 시 graceful
skip. 저작권: 후보는 자작(자체생성·WHYMATH_GENERATED)이다.
"""

from __future__ import annotations

import uuid

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.problem_bank.embedding import ProblemEmbeddingIndex
from whymath_backend.l1.problem_bank.populate import ConceptTag, ProblemBankStore
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.generator import CandidateProblem, ScriptedGenerator
from whymath_backend.l3.equivalent.orchestrator import run_equivalent_generation
from whymath_backend.l4.misconception.semantic.provider import FakeEmbeddingProvider
from whymath_backend.schema.enums import (
    AnswerFormat,
    Curriculum,
    GenerationType,
    LicenseType,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import DistractorEntry, Problem
from whymath_backend.schema.provenance import ContentProvenance

pytestmark = pytest.mark.integration

# 통합 전용 결정론 식별자(정리 대상·실 데이터와 충돌 무관한 전용 네임스페이스).
_PID = uuid.UUID("cccc0000-0000-0000-0000-00000000000d")
_SLUG = "it-orch-s2d-quad-root"
_CONCEPT_SRC = "IT-ORCH-S2D"
_STANDARD = "[12미적01-01]"
_MISCONCEPTION = "distribution-over-power"


def _spec() -> EquivalenceSpec:
    return EquivalenceSpec(
        achievement_standard_codes=frozenset({_STANDARD}),
        target_misconception_ids=frozenset({_MISCONCEPTION}),
        difficulty_overall=3.0,
        answer_format=AnswerFormat.자연수,
    )


def _candidate() -> CandidateProblem:
    """자작 자체생성 동등문제 후보 — 전 게이트 통과·발문에 희소 토큰(다른 코퍼스와 직교)."""
    problem = Problem(
        problem_id=_PID,
        slug=_SLUG,
        source_type=SourceType.자체생성,
        curriculum_version=Curriculum.REVISION_2022,
        valid_from_year=2022,
        subject=Subject.미적분,
        unit_codes=["CAL-INT-DEF"],
        difficulty_overall=3.0,
        answer_format=AnswerFormat.자연수,
        achievement_standard_codes=[_STANDARD],
        distractor_map=[DistractorEntry(choice_index=1, misconception_id=_MISCONCEPTION)],
        question_text="에스투디 통합 자작 이차식 자연수 근 을 구하 시오",
        answer="3",
        answer_explanation="주어진 조건을 풀면 정답은 자연수 세 입니다.",
    )
    provenance = ContentProvenance(
        generation_type=GenerationType.FULLY_GENERATED,
        license=LicenseType.WHYMATH_GENERATED,
    )
    return CandidateProblem(
        problem=problem,
        provenance=provenance,
        conditions="x**2 - 5*x + 6 = 0",
        answer_map={"x": "3"},
        concept_tags=[ConceptTag(concept_src_id=_CONCEPT_SRC, role="PRIMARY", relevance=0.9)],
    )


def _sync_engine() -> object:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    settings = Settings()
    url = settings.sync_database_url
    if settings.db_disable_pool:
        return create_engine(url, poolclass=NullPool)
    return create_engine(url)


def _reachable() -> bool:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            conn.execute(text("SELECT count(*) FROM problem"))
            conn.execute(text("SELECT count(*) FROM problem_concept"))
            conn.execute(text("SELECT count(*) FROM concept"))
            conn.execute(text("SELECT count(*) FROM problem_embedding"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _skip_if_unreachable() -> None:
    if not _reachable():
        pytest.skip(
            "pgvector PostgreSQL 미도달(또는 마이그레이션 미적용) — 통합 테스트 건너뜀 "
            "(WHYMATH_DATABASE_URL·alembic upgrade head 확인)"
        )


def _seed_concept() -> None:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(
                text(
                    "INSERT INTO concept (concept_id, code, name_ko, level, source_id) "
                    "VALUES (:cid, :code, :name, '세부개념', :src) "
                    "ON CONFLICT (code) DO NOTHING"
                ),
                {
                    "cid": uuid.uuid4(),
                    "code": f"IT-ORCH-{_CONCEPT_SRC}",
                    "name": "통합테스트 개념 S2D",
                    "src": _CONCEPT_SRC,
                },
            )
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _cleanup() -> None:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(
                text("DELETE FROM problem_embedding WHERE problem_id = :pid"), {"pid": _PID}
            )
            conn.execute(text("DELETE FROM problem_concept WHERE problem_id = :pid"), {"pid": _PID})
            # LIC-03 — 원장 선삭제(FK NO ACTION). 위 test_populate_integration.py 동형.
            conn.execute(
                text("DELETE FROM content_provenance WHERE problem_id = :pid"), {"pid": _PID}
            )
            conn.execute(text("DELETE FROM problem WHERE slug = :slug"), {"slug": _SLUG})
            conn.execute(text("DELETE FROM concept WHERE source_id = :src"), {"src": _CONCEPT_SRC})
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _count(sql: str, params: dict[str, object]) -> int:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            return int(conn.execute(text(sql), params).scalar_one())
    finally:
        engine.dispose()  # type: ignore[attr-defined]


class TestEndToEnd:
    def test_generate_gate_dedup_store_then_second_run_rejected_duplicate(self) -> None:
        _skip_if_unreachable()
        settings = Settings()
        provider = FakeEmbeddingProvider(dim=settings.embedding_dim)
        try:
            _cleanup()  # 선행 잔여 제거
            _seed_concept()

            store = ProblemBankStore(settings=settings)
            index = ProblemEmbeddingIndex(
                provider_name="fake", model_name="fake-hash", settings=settings
            )
            # 같은 후보를 2회 방출 — 1회차 저장·임베딩 적재, 2회차는 과유사 중복거부.
            generator = ScriptedGenerator([_candidate(), _candidate()])

            # ── 1회차: 생성→게이트→dedup(fresh)→저장(problem+problem_concept)+임베딩 적재 ──
            first = run_equivalent_generation(
                _spec(),
                generator,
                dedup_index=index,
                embed_provider=provider,
                store=store,
            )
            assert first.status == "accepted_stored"
            assert first.stored_problem_id == _PID

            # S2-b 실 저장 실증.
            assert _count("SELECT count(*) FROM problem WHERE slug = :slug", {"slug": _SLUG}) == 1
            assert (
                _count(
                    "SELECT count(*) FROM problem_concept WHERE problem_id = :pid", {"pid": _PID}
                )
                == 1
            )
            # S2-c 임베딩 적재 실증(dedup_index.upsert 경유).
            assert (
                _count(
                    "SELECT count(*) FROM problem_embedding WHERE problem_id = :pid", {"pid": _PID}
                )
                == 1
            )

            # ── 2회차: 같은 후보 → 코퍼스 판박이 → 과유사 게이트가 저장 차단 ──
            second = run_equivalent_generation(
                _spec(),
                generator,
                dedup_index=index,
                embed_provider=provider,
                store=store,
            )
            assert second.status == "rejected_duplicate"
            assert _PID in {pid for pid, _ in second.near_duplicates}
            # 저장은 여전히 1건(중복이 코퍼스를 늘리지 않음).
            assert _count("SELECT count(*) FROM problem WHERE slug = :slug", {"slug": _SLUG}) == 1
        finally:
            _cleanup()
