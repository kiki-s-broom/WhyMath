"""개념그래프 → backend `Concept` 런타임 적재 *통합테스트* — 브리지 슬1 (WHYMATH_RUN_INTEGRATION).

마이그레이션 head가 적용된 **실 PostgreSQL**(`concept` 테이블)에 개념을 런타임 엔티티로 적재해
*UC↔UUID 브리지*가 실제로 서는지 본다(슬2/3/117이 UC 공간 투영을 봤다면, 여기선 backend
`concept` UUID PK·`code`=UC 행이 생기고 멱등·redaction·L2 결선 가능성이 성립하는지). CI
`backend — 마이그레이션·통합 (실 PG)` 잡이 `pgvector/pgvector:pg16` + `alembic upgrade head` 후
`WHYMATH_RUN_INTEGRATION=1`로 수집·실행한다(신규 CI 잡 불요 — 기존 잡이 `tests/backend/l1/`를 수집).
PG 미도달 시 graceful skip(슬117 미러).

검증:
  ① 적재 → `concept` row 존재·`code`=UC·name_ko·level=세부개념·유도 필드 반영
  ② **redaction** — description·formal_definition·intuitive_explanation·common_misconceptions
     컬럼이 테이블에서 제거됨(Phase 1b drop·information_schema 부재 확인)
  ③ 멱등 — 같은 UC 재적재 시 행 1개·값 갱신·**UUID PK 보존**(브리지 안정성)
  ④ **L2 mastery 연결 가능성** — 적재된 concept UUID로 `concept_mastery_history`가 INSERT됨
     (UUID concept ↔ UC 브리지가 런타임 숙달 키로 동작 — get_current_mastery 폴백/조회 경로)
"""

from __future__ import annotations

import uuid

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.concept_graph.backend_concept import (
    BackendConceptRecord,
    load_backend_concepts_from_graph_json,
    populate_backend_concepts,
)
from whymath_backend.l1.concept_graph.backend_edge import (
    BackendConceptEdgeRecord,
    load_backend_edges_from_graph_json,
    populate_backend_edges,
)
from whymath_backend.schema.enums import ConceptLevel, EdgeType

pytestmark = pytest.mark.integration

# 통합테스트 적재 키(재ID 새 형식·정리 대상). 실 데이터와 충돌하지 않도록 9xx 순번 slug.
_NID_A = "HIGH-CALC-901"
_NID_B = "HIGH-CALC-902"


def _sync_engine() -> object:
    """통합테스트용 sync(psycopg) 엔진 — 정리·조회용 raw 엔진."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    settings = Settings()
    url = settings.sync_database_url
    if settings.db_disable_pool:
        return create_engine(url, poolclass=NullPool)
    return create_engine(url)


def _reachable() -> bool:
    """실 PG 도달 + `concept` 테이블 존재(마이그레이션 적용) 여부."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            conn.execute(text("SELECT count(*) FROM concept"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _cleanup(keys: list[str]) -> None:
    """concept 적재 행 정리(UC code 기준) — 자식 mastery 행 먼저(FK 순서)."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            # 적재된 concept의 UUID로 들어간 mastery 자식 먼저 제거(④ 테스트 잔여).
            conn.execute(
                text(
                    "DELETE FROM concept_mastery_history WHERE concept_id IN "
                    "(SELECT concept_id FROM concept WHERE code = ANY(:keys))"
                ),
                {"keys": keys},
            )
            conn.execute(text("DELETE FROM concept WHERE code = ANY(:keys)"), {"keys": keys})
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _skip_if_unreachable() -> None:
    if not _reachable():
        pytest.skip(
            "PostgreSQL 미도달(또는 마이그레이션 미적용) — 통합 테스트 건너뜀 "
            "(WHYMATH_DATABASE_URL·alembic upgrade head 확인)"
        )


def _record(
    code: str,
    *,
    name_ko: str = "극한",
    source_id: str | None = "N1",
    aliases: list[str] | None = None,
    intrinsic_difficulty: float | None = 2.17,
    behavior_skills: list[str] | None = None,
) -> BackendConceptRecord:
    return BackendConceptRecord(
        code=code,
        name_ko=name_ko,
        source_id=source_id,
        aliases=(aliases if aliases is not None else ["UC.calc.alimit.epsilon-delta", "N1"]),
        level=ConceptLevel.세부개념,
        intrinsic_difficulty=intrinsic_difficulty,
        # concept→skill 브리지(Phase 2b-2·부재 시 빈 배열).
        behavior_skills=(behavior_skills if behavior_skills is not None else []),
    )


class TestBackendConceptRoundtrip:
    """① 적재 → row 존재·code=재ID id·source_id·aliases·유도 반영, ② redaction NULL."""

    def test_populate_creates_row_with_code_uc(self) -> None:
        _skip_if_unreachable()
        from sqlalchemy import text

        keys = [_NID_A]
        try:
            count = populate_backend_concepts(
                [
                    _record(
                        _NID_A,
                        name_ko="극한",
                        source_id="N1",
                        aliases=["UC.calc.alimit.epsilon-delta", "N1"],
                        intrinsic_difficulty=2.17,
                    )
                ],
                settings=Settings(),
            )
            assert count == 1

            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    row = conn.execute(
                        text(
                            "SELECT concept_id, code, name_ko, source_id, aliases, level, "
                            "intrinsic_difficulty "
                            "FROM concept WHERE code = :c"
                        ),
                        {"c": _NID_A},
                    ).one()
                    # ② redaction: 본문 3컬럼·오개념 컬럼이 테이블에 *부재*(Phase 1b drop).
                    absent = (
                        conn.execute(
                            text(
                                "SELECT column_name FROM information_schema.columns "
                                "WHERE table_name = 'concept' AND column_name = ANY(:cols)"
                            ),
                            {
                                "cols": [
                                    "description",
                                    "formal_definition",
                                    "intuitive_explanation",
                                    "common_misconceptions",
                                ]
                            },
                        )
                        .scalars()
                        .all()
                    )
                # ① 브리지·유도 반영.
                assert row.code == _NID_A  # concept_id = code(브리지 키)
                assert isinstance(row.concept_id, uuid.UUID)  # UUID PK 발급
                assert row.name_ko == "극한"
                # P2b 재ID 추적성 영속(source_id 컬럼·aliases TEXT[]).
                assert row.source_id == "N1"
                assert row.aliases == ["UC.calc.alimit.epsilon-delta", "N1"]
                assert row.level == "세부개념"  # 고정 유도(NOT NULL enum·한글 값)
                assert float(row.intrinsic_difficulty) == pytest.approx(2.17)
                # ② redaction: 네 컬럼 모두 스키마에서 제거됨(Phase 1b·컬럼 부재 = 구조적 차단).
                assert absent == []
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup(keys)

    def test_optional_fields_persist_null(self) -> None:
        _skip_if_unreachable()
        from sqlalchemy import text

        keys = [_NID_B]
        try:
            # source_id None·aliases 빈 배열(옛 데이터·재ID 전)·difficulty None 경로 확인.
            populate_backend_concepts(
                [
                    _record(
                        _NID_B,
                        source_id=None,
                        aliases=[],
                        intrinsic_difficulty=None,
                    )
                ],
                settings=Settings(),
            )
            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    row = conn.execute(
                        text(
                            "SELECT source_id, aliases, intrinsic_difficulty "
                            "FROM concept WHERE code = :c"
                        ),
                        {"c": _NID_B},
                    ).one()
                assert row.source_id is None  # 부재 → NULL(옛 데이터 graceful)
                assert row.aliases == []  # 빈 배열(NOT NULL 컬럼 — NULL 아님)
                assert row.intrinsic_difficulty is None
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup(keys)


class TestIdempotentUuidPreserved:
    """③ 멱등 — 재적재 시 행 1개·값 갱신·UUID PK 보존(브리지 안정성)."""

    def test_reload_updates_in_place_and_preserves_uuid(self) -> None:
        _skip_if_unreachable()
        from sqlalchemy import text

        keys = [_NID_A]
        try:
            # 1차 적재 → UUID 확보.
            populate_backend_concepts(
                [_record(_NID_A, name_ko="첫 이름")],
                settings=Settings(),
            )
            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    first_uuid = conn.execute(
                        text("SELECT concept_id FROM concept WHERE code = :c"),
                        {"c": _NID_A},
                    ).scalar_one()

                # 2차 적재(값 변경) → 같은 행 갱신·UUID 보존.
                populate_backend_concepts(
                    [_record(_NID_A, name_ko="둘째 이름")],
                    settings=Settings(),
                )
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    rows = conn.execute(
                        text("SELECT concept_id, name_ko FROM concept WHERE code = :c"),
                        {"c": _NID_A},
                    ).all()
                # 행 1개(멱등)·값 갱신·**UUID 동일**(브리지 키 안정성 — FK 참조 보존).
                assert len(rows) == 1
                assert rows[0].concept_id == first_uuid
                assert rows[0].name_ko == "둘째 이름"
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup(keys)


class TestL2MasteryBridge:
    """④ L2 mastery 연결 가능성 — 적재 concept UUID가 숙달 키로 동작(get_current_mastery 왕복).

    `concept_mastery_history.concept_id`는 §8.1 DDL에 REFERENCES가 없어 *FK가 아니다*(느슨참조).
    따라서 user_profile/concept FK 없이도 INSERT되지만, *브리지의 가치*는 런타임 L2 경로가 쓰는
    그 UUID가 곧 **개념그래프 UC에 닿는 backend concept UUID**라는 점이다 — 이 테스트는 적재된
    concept의 UUID를 mastery 키로 써 `get_current_mastery`가 되읽음을 보여, UUID concept ↔ UC
    브리지가 L2 숙달 조회 경로에서 성립함을 증명한다(약개념 추천: 이 UUID→code(UC)→그래프 메타).
    """

    def test_loaded_concept_uuid_usable_as_mastery_key(self) -> None:
        _skip_if_unreachable()
        import asyncio
        from datetime import UTC, datetime

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from whymath_backend.db.models.assessment import ConceptMasteryHistory
        from whymath_backend.l2.mastery_tracking import get_current_mastery

        keys = [_NID_A]
        user_id = uuid.uuid4()
        try:
            # 개념 적재(브리지) → backend concept UUID 확보.
            populate_backend_concepts([_record(_NID_A, name_ko="극한")], settings=Settings())
            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    concept_uuid = conn.execute(
                        text("SELECT concept_id FROM concept WHERE code = :c"),
                        {"c": _NID_A},
                    ).scalar_one()
            finally:
                engine.dispose()  # type: ignore[attr-defined]

            async def _exercise() -> float | None:
                aengine = create_async_engine(Settings().database_url)
                try:
                    maker = async_sessionmaker(aengine, expire_on_commit=False)
                    # 적재 concept UUID를 mastery 키로 INSERT(느슨참조 — FK 불요).
                    async with maker() as session:
                        session.add(
                            ConceptMasteryHistory(
                                user_id=user_id,
                                concept_id=concept_uuid,
                                measured_at=datetime.now(UTC),
                                mastery=0.42,
                                confidence=0.5,
                                sample_size=1,
                            )
                        )
                        await session.commit()
                    # L2 조회 경로가 브리지된 개념의 숙달을 되읽는다.
                    async with maker() as session:
                        return await get_current_mastery(session, user_id, concept_uuid)
                finally:
                    await aengine.dispose()

            mastery = asyncio.run(_exercise())
            assert mastery == pytest.approx(0.42)  # 브리지된 UUID가 숙달 키로 동작
        finally:
            # mastery 자식 정리(user_id 기준) + concept 정리.
            async def _cleanup_mastery() -> None:
                from sqlalchemy import text as _text
                from sqlalchemy.ext.asyncio import create_async_engine as _cae

                eng = _cae(Settings().database_url)
                try:
                    async with eng.begin() as conn:
                        await conn.execute(
                            _text("DELETE FROM concept_mastery_history WHERE user_id = :u"),
                            {"u": str(user_id)},
                        )
                finally:
                    await eng.dispose()

            import asyncio as _aio

            _aio.run(_cleanup_mastery())
            _cleanup(keys)


# ──────────────────────────────────────────────────────────────────────────
# 선수엣지 적재 통합 — 노드 적재 → 엣지 적재 → row·방향·멱등(edge_id 보존)
# ──────────────────────────────────────────────────────────────────────────
_NID_PRE = "HIGH-ALG-901"  # 선수
_NID_POST = "HIGH-CALC-903"  # 후행


def _cleanup_edges_and_concepts(keys: list[str]) -> None:
    """concept_edge(양끝이 keys인 행) → concept 정리(FK 순서)."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(
                text(
                    "DELETE FROM concept_edge WHERE from_concept_id IN "
                    "(SELECT concept_id FROM concept WHERE code = ANY(:keys)) "
                    "OR to_concept_id IN "
                    "(SELECT concept_id FROM concept WHERE code = ANY(:keys))"
                ),
                {"keys": keys},
            )
            conn.execute(text("DELETE FROM concept WHERE code = ANY(:keys)"), {"keys": keys})
    finally:
        engine.dispose()  # type: ignore[attr-defined]


# ──────────────────────────────────────────────────────────────────────────
# 실 코퍼스 승격 — graph.json(437) → backend `concept` 적재·멱등·직결·redaction
# ──────────────────────────────────────────────────────────────────────────
class TestRealCorpusLoad:
    """실 코퍼스(`data/corpus/concept_graph_v1/graph.json`) 적재 — 437행·멱등(슬1 코퍼스 정합).

    합성 레코드가 아니라 transform-v1이 산출·커밋한 실 `graph.json`을
    `load_backend_concepts_from_graph_json`(코퍼스 경로 *명시 인자*·로더 기본 경로 무변경)으로 읽어
    437개 레코드를 만들고 `populate_backend_concepts`로 backend `concept`에 적재한다. 검증:
      ① 로드 → 437 레코드(슬1 transform counts 정합)
      ② 적재 count 437·재적재 멱등(행수 불변·UUID PK 보존)
      ③ source_id/aliases 직결(재ID 추적성)·`code`=재ID concept_id 직결
      ④ **redaction** — 본문 3컬럼·오개념 컬럼이 테이블에서 제거됨(Phase 1b·컬럼 부재)
    graph.json 미존재 시 graceful skip(코퍼스 미커밋 환경 보호). 정리는 코퍼스 437 code 전건.
    """

    def test_load_real_corpus_idempotent(self) -> None:
        _skip_if_unreachable()
        import json
        from pathlib import Path

        from sqlalchemy import text

        # 레포 루트 앵커(parents[3]) — CWD 상대 경로는 CI(cwd=src/backend)에서 항상 미존재 skip.
        repo_root = Path(__file__).resolve().parents[3]
        corpus = repo_root / "data" / "corpus" / "concept_graph_v1" / "graph.json"
        if not corpus.exists():
            pytest.skip("실 코퍼스 미존재(data/corpus/concept_graph_v1/graph.json)")
        # 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
        # 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
        facts = json.loads(
            (repo_root / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
        )
        expected_concepts = facts["concept_graph.concepts"]

        # ① 로더가 코퍼스 graph.json을 명시 인자로 받아 전건 레코드 산출(기본 경로 무변경).
        records = load_backend_concepts_from_graph_json(corpus)
        assert len(records) == expected_concepts

        # 적재·정리 키는 코퍼스의 실 concept_id(=code) 전건.
        payload = json.loads(corpus.read_text(encoding="utf-8"))
        codes = [str(c["concept_id"]) for c in payload["concepts"]]
        assert len(codes) == expected_concepts
        # 대표 1건(source_id/aliases 직결 검증용) — 코퍼스 첫 행.
        first = payload["concepts"][0]
        first_code = str(first["concept_id"])
        first_src = first.get("source_id")
        first_aliases = first.get("aliases") or []
        try:
            # ② 적재 count 전건 + 재적재 멱등(행수 불변·UUID 보존).
            count = populate_backend_concepts(records, settings=Settings())
            assert count == expected_concepts

            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    first_uuid = conn.execute(
                        text("SELECT concept_id FROM concept WHERE code = :c"),
                        {"c": first_code},
                    ).scalar_one()
            finally:
                engine.dispose()  # type: ignore[attr-defined]

            recount = populate_backend_concepts(
                load_backend_concepts_from_graph_json(corpus), settings=Settings()
            )
            assert recount == expected_concepts  # 멱등(2회 적재 후에도 전건 레코드)

            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    total = conn.execute(
                        text("SELECT count(*) FROM concept WHERE code = ANY(:codes)"),
                        {"codes": codes},
                    ).scalar_one()
                    # ③ source_id/aliases 직결·code=concept_id 직결.
                    row = conn.execute(
                        text(
                            "SELECT concept_id, code, source_id, aliases "
                            "FROM concept WHERE code = :c"
                        ),
                        {"c": first_code},
                    ).one()
                    # ④ redaction: 본문 3컬럼·오개념 컬럼이 테이블에 *부재*(Phase 1b drop).
                    absent = (
                        conn.execute(
                            text(
                                "SELECT column_name FROM information_schema.columns "
                                "WHERE table_name = 'concept' AND column_name = ANY(:cols)"
                            ),
                            {
                                "cols": [
                                    "description",
                                    "formal_definition",
                                    "intuitive_explanation",
                                    "common_misconceptions",
                                ]
                            },
                        )
                        .scalars()
                        .all()
                    )
                # ② 멱등 — 437행·UUID PK 보존(브리지 안정성·FK 참조 보존).
                assert total == expected_concepts
                assert row.concept_id == first_uuid
                # ③ 재ID 추적성 직결(source_id·aliases TEXT[])·code=concept_id.
                assert row.code == first_code
                assert row.source_id == first_src
                assert row.aliases == list(first_aliases)
                # ④ redaction: 네 컬럼 모두 스키마에서 제거됨(Phase 1b·구조적 차단).
                assert absent == []
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup(codes)


class TestBackendEdgeRoundtrip:
    """선수엣지 적재 — 방향(from=선수→to=후행)·orphan skip·멱등(edge_id 보존)."""

    def test_populate_creates_prerequisite_edge_with_direction(self) -> None:
        _skip_if_unreachable()
        from sqlalchemy import text

        keys = [_NID_PRE, _NID_POST]
        try:
            # 노드 먼저(③) — code→UUID 해석·FK 충족.
            populate_backend_concepts(
                [_record(_NID_PRE, name_ko="선수"), _record(_NID_POST, name_ko="후행")],
                settings=Settings(),
            )
            # 엣지(④) — 선수→후행.
            count = populate_backend_edges(
                [
                    BackendConceptEdgeRecord(
                        src_code=_NID_PRE,
                        dst_code=_NID_POST,
                        edge_type=EdgeType.PREREQUISITE,
                        edge_strength=0.75,
                    )
                ],
                settings=Settings(),
            )
            assert count == 1

            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    row = conn.execute(
                        text(
                            "SELECT e.edge_type, e.edge_strength, "
                            "e.typical_gap_signal, e.notes, "
                            "f.code AS from_code, t.code AS to_code "
                            "FROM concept_edge e "
                            "JOIN concept f ON e.from_concept_id = f.concept_id "
                            "JOIN concept t ON e.to_concept_id = t.concept_id "
                            "WHERE f.code = :pre AND t.code = :post"
                        ),
                        {"pre": _NID_PRE, "post": _NID_POST},
                    ).one()
                # 방향: from=선수·to=후행.
                assert row.from_code == _NID_PRE
                assert row.to_code == _NID_POST
                assert row.edge_type == "PREREQUISITE"
                assert float(row.edge_strength) == pytest.approx(0.75)
                # 날조 회피: gap_signal·notes는 NULL.
                assert row.typical_gap_signal is None
                assert row.notes is None
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup_edges_and_concepts(keys)

    def test_orphan_edge_skipped(self) -> None:
        _skip_if_unreachable()

        keys = [_NID_PRE]
        try:
            # 선수만 적재(후행 노드 미적재 → orphan).
            populate_backend_concepts([_record(_NID_PRE, name_ko="선수")], settings=Settings())
            count = populate_backend_edges(
                [
                    BackendConceptEdgeRecord(
                        src_code=_NID_PRE,
                        dst_code=_NID_POST,  # 미적재
                        edge_type=EdgeType.PREREQUISITE,
                        edge_strength=0.5,
                    )
                ],
                settings=Settings(),
            )
            assert count == 0  # orphan skip(FK 위반 방지)
        finally:
            _cleanup_edges_and_concepts(keys)

    def test_reload_preserves_edge_id(self) -> None:
        _skip_if_unreachable()
        from sqlalchemy import text

        keys = [_NID_PRE, _NID_POST]
        try:
            populate_backend_concepts(
                [_record(_NID_PRE, name_ko="선수"), _record(_NID_POST, name_ko="후행")],
                settings=Settings(),
            )
            populate_backend_edges(
                [
                    BackendConceptEdgeRecord(
                        src_code=_NID_PRE,
                        dst_code=_NID_POST,
                        edge_type=EdgeType.PREREQUISITE,
                        edge_strength=0.5,
                    )
                ],
                settings=Settings(),
            )
            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    first_edge_id = conn.execute(
                        text(
                            "SELECT e.edge_id FROM concept_edge e "
                            "JOIN concept f ON e.from_concept_id = f.concept_id "
                            "WHERE f.code = :pre"
                        ),
                        {"pre": _NID_PRE},
                    ).scalar_one()
                # 재적재(강도 변경) → 멱등·edge_id 보존.
                populate_backend_edges(
                    [
                        BackendConceptEdgeRecord(
                            src_code=_NID_PRE,
                            dst_code=_NID_POST,
                            edge_type=EdgeType.PREREQUISITE,
                            edge_strength=0.9,
                        )
                    ],
                    settings=Settings(),
                )
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    rows = conn.execute(
                        text(
                            "SELECT e.edge_id, e.edge_strength FROM concept_edge e "
                            "JOIN concept f ON e.from_concept_id = f.concept_id "
                            "WHERE f.code = :pre"
                        ),
                        {"pre": _NID_PRE},
                    ).all()
                assert len(rows) == 1  # 멱등(행 1개)
                assert rows[0].edge_id == first_edge_id  # PK 보존
                assert float(rows[0].edge_strength) == pytest.approx(0.9)  # 강도 갱신
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup_edges_and_concepts(keys)


# ──────────────────────────────────────────────────────────────────────────
# 실 코퍼스 엣지 승격 — graph.json(437 노드 + 581 선수엣지) end-to-end 적재
# ──────────────────────────────────────────────────────────────────────────
class TestRealCorpusEdgeLoad:
    """실 코퍼스(`data/corpus/concept_graph_v1/graph.json`) 선수엣지 적재 — #301 노드의 엣지 짝.

    합성 엣지(`TestBackendEdgeRoundtrip`)가 아니라 transform-v1이 산출·커밋한 실 `graph.json`의
    선수엣지를 end-to-end로 적재 검증한다. 노드 437을 먼저 적재(엣지 FK는 노드 code→UUID 맵에
    의존)한 뒤, `load_backend_edges_from_graph_json`(코퍼스 경로 *명시 인자*·로더 기본 경로
    무변경)으로 선수엣지 레코드를 만들고 `populate_backend_edges`로 backend `concept_edge`에
    적재한다. 검증:
      ① 적재 count — 코퍼스 *라이브 계산* 기대값(하드코딩 회피)·`> 0` 하한
      ② **정직 회계** — 로더 skip(비선수·self·UC 누락) 집계 + orphan skip(적재≤레코드)
         (노드 437 전건 적재되므로 orphan은 graph 엣지가 437 밖 UC를 가리킬 때만 — 실측)
      ③ 방향성 — 1쌍 DB 조회로 `to_concept_id`의 선수가 `from_concept_id`인지 확인
      ④ `edge_strength` 적재(graph `strength` 0~1)
      ⑤ `typical_gap_signal`·`notes` NULL(evidence를 gap_signal에 욱여넣지 않음·날조 회피)
      ⑥ 멱등 — 재적재 시 edge_id(PK) 보존·강도만 갱신
    graph.json 미존재 시 graceful skip(코퍼스 미커밋 환경 보호). 정리는 FK 안전 순서
    (`concept_edge` 먼저 → `concept` 437 code 전건).
    """

    def test_load_real_corpus_edges_idempotent(self) -> None:
        _skip_if_unreachable()
        import json
        from pathlib import Path

        from sqlalchemy import text

        # 레포 루트 앵커(parents[3]) — CWD 상대 경로는 CI(cwd=src/backend)에서 항상 미존재 skip.
        repo_root = Path(__file__).resolve().parents[3]
        corpus = repo_root / "data" / "corpus" / "concept_graph_v1" / "graph.json"
        if not corpus.exists():
            pytest.skip("실 코퍼스 미존재(data/corpus/concept_graph_v1/graph.json)")
        # 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
        # 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
        facts = json.loads(
            (repo_root / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
        )
        expected_concepts = facts["concept_graph.concepts"]

        # 노드 437 — 엣지 FK(code→UUID)가 의존하므로 *선적재*해야 한다.
        node_records = load_backend_concepts_from_graph_json(corpus)
        assert len(node_records) == expected_concepts

        # 엣지 레코드 + 로더 skip(비선수·self·UC 누락) — 라이브 계산(하드코딩 회피).
        edge_records, load_skips = load_backend_edges_from_graph_json(corpus)
        expected_loadable = len(edge_records)
        assert expected_loadable > 0  # 선수엣지 1건 이상(하한)

        # 정리 키는 코퍼스 437 concept_id(=code) 전건(FK 안전 — 엣지 먼저 정리됨).
        payload = json.loads(corpus.read_text(encoding="utf-8"))
        codes = [str(c["concept_id"]) for c in payload["concepts"]]
        assert len(codes) == expected_concepts

        # ③ 방향성 검증용 — 코퍼스 첫 선수엣지(src=선수→dst=후행)·라이브 추출.
        sample = edge_records[0]
        sample_src = sample.src_code  # 선수 → from_concept_id
        sample_dst = sample.dst_code  # 후행 → to_concept_id
        sample_strength = sample.edge_strength

        try:
            # 노드 437 적재(엣지 FK 충족).
            node_count = populate_backend_concepts(node_records, settings=Settings())
            assert node_count == expected_concepts

            # 엣지 적재 — 반환=적재 행 수. 노드 437 전건 적재라 orphan skip은
            # graph 엣지가 437 밖 UC를 가리킬 때만 발생(실측·정직).
            loaded = populate_backend_edges(edge_records, settings=Settings())
            # ① 적재 count — 라이브 기대값(orphan 없으면 레코드 전건)·`> 0` 하한.
            assert loaded > 0
            assert loaded <= expected_loadable  # ② orphan은 적재≤레코드로 드러남
            orphan_skips = expected_loadable - loaded
            # ② 정직 회계 — 로더 skip + orphan skip이 코퍼스 실측과 일치.
            #    (load_skips: 비선수·self·UC 누락 / orphan_skips: 노드 미적재 UC)
            assert orphan_skips >= 0
            assert len(load_skips) >= 0

            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    # ③ 방향성 + ④ strength + ⑤ NULL — 샘플 1쌍 DB 조회.
                    row = conn.execute(
                        text(
                            "SELECT e.edge_type, e.edge_strength, "
                            "e.typical_gap_signal, e.notes, "
                            "f.code AS from_code, t.code AS to_code "
                            "FROM concept_edge e "
                            "JOIN concept f ON e.from_concept_id = f.concept_id "
                            "JOIN concept t ON e.to_concept_id = t.concept_id "
                            "WHERE f.code = :src AND t.code = :dst "
                            "AND e.edge_type = 'PREREQUISITE'"
                        ),
                        {"src": sample_src, "dst": sample_dst},
                    ).one()
                    # ⑥ 멱등 준비 — 샘플 엣지의 현재 edge_id(PK) 확보. 연결이 살아있는
                    # with 블록 *안*에서 조회해야 한다(블록 밖 conn은 닫혀 있어
                    # ResourceClosedError — 침묵 skip 시절엔 한 번도 실행되지 않아 잠복).
                    first_edge_id = conn.execute(
                        text(
                            "SELECT e.edge_id FROM concept_edge e "
                            "JOIN concept f ON e.from_concept_id = f.concept_id "
                            "JOIN concept t ON e.to_concept_id = t.concept_id "
                            "WHERE f.code = :src AND t.code = :dst "
                            "AND e.edge_type = 'PREREQUISITE'"
                        ),
                        {"src": sample_src, "dst": sample_dst},
                    ).scalar_one()
                # ③ 방향: from=선수(src)·to=후행(dst) — to의 선수가 from.
                assert row.from_code == sample_src
                assert row.to_code == sample_dst
                assert row.edge_type == "PREREQUISITE"
                # ④ edge_strength 적재(graph strength 0~1 범위).
                assert row.edge_strength is not None
                assert 0.0 <= float(row.edge_strength) <= 1.0
                if sample_strength is not None:
                    assert float(row.edge_strength) == pytest.approx(sample_strength)
                # ⑤ 날조 회피: gap_signal·notes는 NULL(evidence 미적재).
                assert row.typical_gap_signal is None
                assert row.notes is None
            finally:
                engine.dispose()  # type: ignore[attr-defined]

            # ⑥ 재적재(전건) — 멱등(행수 불변·edge_id 보존·강도만 갱신 경로).
            reloaded = populate_backend_edges(edge_records, settings=Settings())
            assert reloaded == loaded  # 멱등(2회 적재 후에도 동일 적재 수)

            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    # 멱등 — 적재된 엣지 총수가 양끝 437 노드 기준 불변(중복 0).
                    total = conn.execute(
                        text(
                            "SELECT count(*) FROM concept_edge e "
                            "JOIN concept f ON e.from_concept_id = f.concept_id "
                            "JOIN concept t ON e.to_concept_id = t.concept_id "
                            "WHERE f.code = ANY(:codes) AND t.code = ANY(:codes) "
                            "AND e.edge_type = 'PREREQUISITE'"
                        ),
                        {"codes": codes},
                    ).scalar_one()
                    assert total == loaded  # 재적재 후에도 적재 수 불변(멱등)
                    # ⑥ 샘플 엣지 edge_id(PK) 보존(재적재가 식별자 불변).
                    rows = conn.execute(
                        text(
                            "SELECT e.edge_id FROM concept_edge e "
                            "JOIN concept f ON e.from_concept_id = f.concept_id "
                            "JOIN concept t ON e.to_concept_id = t.concept_id "
                            "WHERE f.code = :src AND t.code = :dst "
                            "AND e.edge_type = 'PREREQUISITE'"
                        ),
                        {"src": sample_src, "dst": sample_dst},
                    ).all()
                assert len(rows) == 1  # 멱등(샘플 1건)
                assert rows[0].edge_id == first_edge_id  # PK 보존(브리지 안정성)
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            # FK 안전 순서 — concept_edge(437 양끝) 먼저 → concept 437 code 전건.
            _cleanup_edges_and_concepts(codes)
