"""NCIC 성취기준 코퍼스 → backend 적재 *통합테스트* — P1 코퍼스 로더 (WHYMATH_RUN_INTEGRATION).

마이그레이션 head가 적용된 **실 PostgreSQL**(`achievement_standard`·`concept_standard_link`
테이블)에 코퍼스 Collection을 적재해 P1 로더가 실제로 서는지 본다.
CI `backend — 마이그레이션·통합 (실 PG)` 잡이
`pgvector/pgvector:pg16` + `alembic upgrade head` 후 `WHYMATH_RUN_INTEGRATION=1`로 수집·실행한다
(기존 잡이 `tests/backend/l1/`를 수집 — 신규 CI 잡 불요). PG 미도달 시 graceful skip
(`test_concept_backend_load_integration.py` 미러).

검증:
  ① 성취기준 적재 → row 존재·코퍼스 `code`→`official_code` rename
     ·본문(statement) 적재(공공누리 1유형)
  ② official_code 충돌쌍 — 같은 code(2022·2015)·다른 norm_id → 2행(PK 충돌 아님)
  ③ 멱등 — 같은 norm_id 재적재 시 행 1개·값 갱신
  ④ 링크 적재 → **P2b**: `concept_src_id`(src_id)→`{source_id: code}` 맵 해석·실 FK norm_id 결선·
     의미키 멱등(link_id 보존). 적재된 concept_code가 *해석된 새 code*(원천 src_id 아님)임을 확인.
  ⑤ orphan 링크 — ⓐ 적재 안 된 norm_id(성취기준 FK 위반)·ⓑ 맵에 없는 src_id(개념 미해석) 둘 다 skip
"""

from __future__ import annotations

import uuid

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.concept_graph.backend_concept import (
    BackendConceptRecord,
    populate_backend_concepts,
)
from whymath_backend.l1.standards.standard_loader import (
    ConceptStandardLinkStore,
    load_links,
    load_standards,
)
from whymath_backend.schema.enums import ConceptLevel

pytestmark = pytest.mark.integration

# 통합테스트 적재 키 — 실 데이터와 충돌하지 않도록 it 슬러그 norm_id(NORM_ID_PATTERN 통과 토큰).
_NORM_A = "2022_99it_01_01"
_NORM_B = "2015_99it_01_01"  # 같은 official_code·다른 개정(충돌쌍)
_CODE_AB = "[99it01-01]"  # 2022·2015 양쪽에 동일(official_code 비유일)
# P2b: 코퍼스 링크 concept_src_id(src_id)는 backend concept을 통해 새 code로 *해석*된다.
# _SRC_ID(원천)→_CODE(해석된 새 형식 concept.code·느슨참조).
# _SRC_ID_ORPHAN은 적재 개념에 없는 src_id.
_SRC_ID = "ZZIT01"  # 링크 concept_src_id(원천 src_id·해석 전)
_CODE = "HIGH-ZZIT-001"  # _SRC_ID가 해석되는 backend concept.code(적재 시드)
_SRC_ID_ORPHAN = "ZZIT99"  # 적재 개념에 없는 src_id(개념 orphan)
_NORM_ORPHAN = "2022_99it_09_09"  # 적재 안 된 norm_id(성취기준 orphan)


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
    """실 PG 도달 + `achievement_standard` 테이블 존재(마이그레이션 적용) 여부."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            conn.execute(text("SELECT count(*) FROM achievement_standard"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _cleanup(norm_ids: list[str]) -> None:
    """성취기준·링크 정리 — 링크 먼저(norm_id FK CASCADE이나 명시 순서로 정리)."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(
                text("DELETE FROM concept_standard_link WHERE norm_id = ANY(:ids)"),
                {"ids": norm_ids},
            )
            conn.execute(
                text("DELETE FROM achievement_standard WHERE norm_id = ANY(:ids)"),
                {"ids": norm_ids},
            )
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _seed_concept(*, code: str = _CODE, source_id: str = _SRC_ID) -> None:
    """링크 해석용 backend concept 시드(멱등 upsert) — `{source_id: code}` 맵을 채운다(P2b).

    링크 적재 전 이 개념이 있어야 `concept_src_id`(src_id)가 새 code로 해석된다(backend_edge가
    엣지 적재 전 노드를 적재해야 UC→UUID가 풀리는 것의 짝). 적재기를 그대로 써 source_id 컬럼을
    채운다(P2b가 추가한 컬럼). name_ko 등은 더미.
    """
    populate_backend_concepts(
        [
            BackendConceptRecord(
                code=code,
                name_ko="통합테스트 개념",
                source_id=source_id,
                aliases=[],
                level=ConceptLevel.세부개념,
                intrinsic_difficulty=None,
                behavior_skills=[],
            )
        ],
        settings=Settings(),
    )


def _cleanup_concepts(codes: list[str]) -> None:
    """링크 정리 후 시드 concept 정리(code 기준) — 링크는 _cleanup이 norm_id로 먼저 지운다."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(
                text("DELETE FROM concept WHERE code = ANY(:codes)"),
                {"codes": codes},
            )
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _skip_if_unreachable() -> None:
    if not _reachable():
        pytest.skip(
            "PostgreSQL 미도달(또는 마이그레이션 미적용) — 통합 테스트 건너뜀 "
            "(WHYMATH_DATABASE_URL·alembic upgrade head 확인)"
        )


def _standard_row(
    norm_id: str,
    code: str = _CODE_AB,
    *,
    curriculum_revision: str = "2022 개정",
    statement: str = "다항식의 사칙연산을 할 수 있다.",
) -> dict[str, object]:
    """코퍼스 성취기준 dict — *코퍼스 키 `code`* 사용."""
    return {
        "norm_id": norm_id,
        "code": code,
        "grade_band": "고등학교",
        "school_type": "고등학교",
        "subject": "공통수학1",
        "domain": "다항식",
        "sub_domain": None,
        "statement": statement,
        "commentary": "해설 본문(공공누리 1유형 — 적재 허용).",
        "big_idea": None,
        "curriculum_revision": curriculum_revision,
        "effective_from": None,
        "parent_codes": [],
        "source_url": "https://www.ncic.go.kr/x",
        "source_document": None,
    }


def _standards_collection(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "collected_at": "2026-06-16T00:00:00+00:00",
        "crawler_version": "0.1.0",
        "standards": rows,
    }


def _link_row(
    concept_src_id: str = _SRC_ID,
    norm_id: str = _NORM_A,
    *,
    link_type: str = "직접",
    note: str | None = None,
) -> dict[str, object]:
    """코퍼스 링크 dict — *코퍼스 키 `concept_src_id`*(src_id·해석 전) 사용."""
    return {
        "concept_src_id": concept_src_id,
        "norm_id": norm_id,
        "link_type": link_type,
        "note": note,
    }


def _links_collection(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "collected_at": "2026-06-16T00:00:00+00:00",
        "crawler_version": "0.1.0",
        "links": rows,
    }


class TestStandardRoundtrip:
    """① 적재 → row·code→official_code rename·본문 적재, ② official_code 충돌쌍 2행."""

    def test_populate_creates_row_with_official_code(self) -> None:
        _skip_if_unreachable()
        from sqlalchemy import text

        norm_ids = [_NORM_A]
        try:
            count = load_standards(
                None,
                _standards_collection([_standard_row(_NORM_A)]),
                settings=Settings(),
            )
            assert count == 1

            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    row = conn.execute(
                        text(
                            "SELECT norm_id, official_code, statement, commentary, "
                            "curriculum_revision FROM achievement_standard WHERE norm_id = :n"
                        ),
                        {"n": _NORM_A},
                    ).one()
                # ① rename: 코퍼스 code → official_code 컬럼.
                assert row.norm_id == _NORM_A
                assert row.official_code == _CODE_AB
                # 본문 적재(공공누리 1유형 — backend_concept redaction과 대비).
                assert row.statement == "다항식의 사칙연산을 할 수 있다."
                assert row.commentary == "해설 본문(공공누리 1유형 — 적재 허용)."
                assert row.curriculum_revision == "2022 개정"
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup(norm_ids)

    def test_official_code_collision_pair_loads_two_rows(self) -> None:
        _skip_if_unreachable()
        from sqlalchemy import text

        norm_ids = [_NORM_A, _NORM_B]
        try:
            count = load_standards(
                None,
                _standards_collection(
                    [
                        _standard_row(_NORM_A, _CODE_AB, curriculum_revision="2022 개정"),
                        _standard_row(_NORM_B, _CODE_AB, curriculum_revision="2015 개정"),
                    ]
                ),
                settings=Settings(),
            )
            assert count == 2

            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    rows = conn.execute(
                        text(
                            "SELECT norm_id, official_code, curriculum_revision "
                            "FROM achievement_standard WHERE official_code = :c "
                            "ORDER BY norm_id"
                        ),
                        {"c": _CODE_AB},
                    ).all()
                # 같은 official_code('[99it01-01]')가 2022·2015 → norm_id 달라 2행(PK 충돌 아님).
                assert len(rows) == 2
                assert {r.norm_id for r in rows} == {_NORM_A, _NORM_B}
                assert {r.curriculum_revision for r in rows} == {
                    "2022 개정",
                    "2015 개정",
                }
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup(norm_ids)


class TestStandardIdempotent:
    """③ 멱등 — 재적재 시 행 1개·값 갱신."""

    def test_reload_updates_in_place(self) -> None:
        _skip_if_unreachable()
        from sqlalchemy import text

        norm_ids = [_NORM_A]
        try:
            load_standards(
                None,
                _standards_collection([_standard_row(_NORM_A, statement="첫 본문")]),
                settings=Settings(),
            )
            load_standards(
                None,
                _standards_collection([_standard_row(_NORM_A, statement="둘째 본문")]),
                settings=Settings(),
            )
            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    rows = conn.execute(
                        text(
                            "SELECT norm_id, statement FROM achievement_standard "
                            "WHERE norm_id = :n"
                        ),
                        {"n": _NORM_A},
                    ).all()
                assert len(rows) == 1  # 멱등(행 1개)
                assert rows[0].statement == "둘째 본문"  # 값 갱신
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup(norm_ids)


class TestLinkRoundtrip:
    """④ 링크 적재 — concept_src_id(src_id)→해석된 새 code·실 FK 결선·멱등(link_id 보존)·P2b."""

    def test_populate_creates_link_with_resolved_code(self) -> None:
        _skip_if_unreachable()
        from sqlalchemy import text

        norm_ids = [_NORM_A]
        try:
            # 개념 시드(src_id→code 맵 채움) + 성취기준 먼저 — 링크의 개념 해석·실 FK norm_id 충족.
            _seed_concept()
            load_standards(
                None,
                _standards_collection([_standard_row(_NORM_A)]),
                settings=Settings(),
            )
            count = load_links(
                None,
                _links_collection([_link_row(_SRC_ID, _NORM_A, note="개념이 곧장 다룸")]),
                settings=Settings(),
            )
            assert count == 1

            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    row = conn.execute(
                        text(
                            "SELECT link_id, concept_code, norm_id, link_type, note "
                            "FROM concept_standard_link WHERE norm_id = :n"
                        ),
                        {"n": _NORM_A},
                    ).one()
                # P2b: concept_src_id(src_id) → 해석된 새 code(원천 src_id 아님).
                assert row.concept_code == _CODE
                assert row.concept_code != _SRC_ID  # store-direct가 아니라 해석됨
                assert row.norm_id == _NORM_A
                assert row.link_type == "직접"
                assert row.note == "개념이 곧장 다룸"
                assert isinstance(row.link_id, uuid.UUID)  # UUID PK 발급
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup(norm_ids)
            _cleanup_concepts([_CODE])

    def test_orphan_link_skipped_unknown_norm(self) -> None:
        _skip_if_unreachable()

        norm_ids = [_NORM_A]
        try:
            # 개념 시드 + 성취기준 _NORM_A만 적재 → _NORM_ORPHAN 참조 링크는 성취기준 orphan.
            _seed_concept()
            load_standards(
                None,
                _standards_collection([_standard_row(_NORM_A)]),
                settings=Settings(),
            )
            count = load_links(
                None,
                _links_collection([_link_row(_SRC_ID, _NORM_ORPHAN)]),
                settings=Settings(),
            )
            assert count == 0  # 성취기준 orphan skip(실 FK 위반 방지)
        finally:
            _cleanup(norm_ids + [_NORM_ORPHAN])
            _cleanup_concepts([_CODE])

    def test_orphan_link_skipped_unresolved_src_id(self) -> None:
        _skip_if_unreachable()

        norm_ids = [_NORM_A]
        try:
            # 개념 시드(_SRC_ID만) + 성취기준 적재 → _SRC_ID_ORPHAN은 맵에 없어 개념 orphan(P2b).
            _seed_concept()
            load_standards(
                None,
                _standards_collection([_standard_row(_NORM_A)]),
                settings=Settings(),
            )
            count = load_links(
                None,
                _links_collection([_link_row(_SRC_ID_ORPHAN, _NORM_A)]),
                settings=Settings(),
            )
            assert count == 0  # 개념 orphan skip(맵에 없는 src_id — 해석 실패)
        finally:
            _cleanup(norm_ids)
            _cleanup_concepts([_CODE])

    def test_reload_preserves_link_id(self) -> None:
        _skip_if_unreachable()
        from sqlalchemy import text

        norm_ids = [_NORM_A]
        try:
            _seed_concept()
            load_standards(
                None,
                _standards_collection([_standard_row(_NORM_A)]),
                settings=Settings(),
            )
            load_links(
                None,
                _links_collection([_link_row(_SRC_ID, _NORM_A, note="첫 근거")]),
                settings=Settings(),
            )
            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    first_link_id = conn.execute(
                        text("SELECT link_id FROM concept_standard_link WHERE norm_id = :n"),
                        {"n": _NORM_A},
                    ).scalar_one()
                # 재적재(note 변경) → 멱등·link_id 보존.
                load_links(
                    None,
                    _links_collection([_link_row(_SRC_ID, _NORM_A, note="둘째 근거")]),
                    settings=Settings(),
                )
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    rows = conn.execute(
                        text(
                            "SELECT link_id, note FROM concept_standard_link " "WHERE norm_id = :n"
                        ),
                        {"n": _NORM_A},
                    ).all()
                assert len(rows) == 1  # 멱등(행 1개)
                assert rows[0].link_id == first_link_id  # PK 보존
                assert rows[0].note == "둘째 근거"  # note 갱신
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup(norm_ids)
            _cleanup_concepts([_CODE])

    def test_link_store_populate_returns_skip_messages(self) -> None:
        """orphan skip 메시지가 store.populate 둘째 반환으로 노출됨(조용한 누락 금지)."""
        _skip_if_unreachable()
        from whymath_backend.schema.standard import ConceptStandardLink

        norm_ids = [_NORM_A]
        try:
            _seed_concept()
            load_standards(
                None,
                _standards_collection([_standard_row(_NORM_A)]),
                settings=Settings(),
            )
            store = ConceptStandardLinkStore(settings=Settings())
            # concept_code 슬롯엔 *해석 전 src_id*를 넣는다(populate가 새 code로 해석).
            loaded, skipped = store.populate(
                [
                    ConceptStandardLink(
                        concept_code=_SRC_ID,
                        norm_id=_NORM_A,
                        link_type="직접",
                        note=None,
                    ),
                    ConceptStandardLink(
                        concept_code=_SRC_ID,
                        norm_id=_NORM_ORPHAN,
                        link_type="직접",
                        note=None,
                    ),
                    ConceptStandardLink(
                        concept_code=_SRC_ID_ORPHAN,
                        norm_id=_NORM_A,
                        link_type="직접",
                        note=None,
                    ),
                ]
            )
            assert loaded == 1  # 유효 1(개념·성취기준 둘 다 해석)
            assert any("orphan" in m and "성취기준" in m for m in skipped)  # 성취기준 orphan 보고
            assert any("orphan" in m and "개념" in m for m in skipped)  # 개념 orphan 보고
        finally:
            _cleanup(norm_ids + [_NORM_ORPHAN])
            _cleanup_concepts([_CODE])


class TestRealCorpusLoad:
    """⑥ 실 코퍼스(`data/corpus/standards_v1`) 적재 — 895행·멱등(#288 코퍼스 정합 검증).

    합성 행이 아니라 `whymath-ncic extract`가 커밋한 실 Collection JSON을 `load_standards`로
    적재해 P1 로더가 실 데이터에 서는지 본다(2022:435+2015:460=895). 정리는 코퍼스 norm_id 전건.
    """

    def test_load_real_standards_corpus_idempotent(self) -> None:
        _skip_if_unreachable()
        import json
        from pathlib import Path

        from sqlalchemy import text

        # 레포 루트 앵커(parents[3]) — CWD 상대 경로는 CI(cwd=src/backend)에서 항상 미존재 skip.
        repo_root = Path(__file__).resolve().parents[3]
        corpus = repo_root / "data" / "corpus" / "standards_v1" / "standards.json"
        if not corpus.exists():
            pytest.skip("실 코퍼스 미존재(data/corpus/standards_v1/standards.json)")
        # 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
        # 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
        facts = json.loads(
            (repo_root / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
        )
        expected = facts["standards.k12"]  # 2022 + 2015 개정
        payload = json.loads(corpus.read_text(encoding="utf-8"))
        norm_ids = [str(s["norm_id"]) for s in payload["standards"]]
        try:
            count = load_standards(None, corpus, settings=Settings())
            assert count == expected
            # 재적재 멱등 — 같은 코퍼스 → DB 행수 불변(중복 적재 없음).
            recount = load_standards(None, corpus, settings=Settings())
            assert recount == expected
            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    total = conn.execute(
                        text(
                            "SELECT count(*) FROM achievement_standard " "WHERE norm_id = ANY(:ids)"
                        ),
                        {"ids": norm_ids},
                    ).scalar_one()
                assert total == expected  # 멱등(2회 적재 후에도 전건)
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup(norm_ids)


class TestUniversityCorpusLoad:
    """⑦ 실 대학 성취기준 코퍼스(`data/corpus/standards_university_v1`) 적재 — 409행·멱등(U3).

    대학 성취기준은 NCIC 아닌 *자체작성*이나 같은 범용 backend 로더로 적재된다(school_type=대학교·
    code=`[CALC1-01-01]`·curriculum_revision='대학'). 링크는 atom 백본 concept이 source_id
    미설정이라 orphan skip될 수 있어(concept_standard_link은 개념그래프 레거시·atom↔성취기준은
    atom.standard_codes가 담당·U2에서 채움) 여기선 *standards 적재*만 검증한다.
    """

    def test_load_real_university_standards_idempotent(self) -> None:
        _skip_if_unreachable()
        import json
        from pathlib import Path

        from sqlalchemy import text

        # 레포 루트 앵커(parents[3]) — CWD 상대 경로는 CI(cwd=src/backend)에서 항상 미존재 skip.
        repo_root = Path(__file__).resolve().parents[3]
        corpus = repo_root / "data" / "corpus" / "standards_university_v1" / "standards.json"
        if not corpus.exists():
            pytest.skip("대학 코퍼스 미존재(data/corpus/standards_university_v1/standards.json)")
        # 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
        # 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
        facts = json.loads(
            (repo_root / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
        )
        expected = facts["standards.university"]  # 대학 성취기준 전건
        payload = json.loads(corpus.read_text(encoding="utf-8"))
        norm_ids = [str(s["norm_id"]) for s in payload["standards"]]
        try:
            count = load_standards(None, corpus, settings=Settings())
            assert count == expected
            recount = load_standards(None, corpus, settings=Settings())
            assert recount == expected  # 멱등
            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    total = conn.execute(
                        text("SELECT count(*) FROM achievement_standard WHERE norm_id = ANY(:ids)"),
                        {"ids": norm_ids},
                    ).scalar_one()
                    univ = conn.execute(
                        text(
                            "SELECT count(*) FROM achievement_standard "
                            "WHERE curriculum_revision = '대학' AND norm_id = ANY(:ids)"
                        ),
                        {"ids": norm_ids},
                    ).scalar_one()
                assert total == expected  # 멱등(2회 적재 후에도 전건)
                assert univ == expected  # 전부 대학 개정 표식
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup(norm_ids)
