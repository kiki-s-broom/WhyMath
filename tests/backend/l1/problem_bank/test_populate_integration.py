"""문제 코퍼스 → backend 적재 *통합테스트*(WHYMATH_RUN_INTEGRATION·실 PG — S2-03 원자 재연결).

마이그레이션 head가 적용된 **실 PostgreSQL**(`problem`·`problem_concept`·`concept`)에 실 코퍼스
(`data/corpus/problem_bank_v1/problems.jsonl`)를 적재해 S2-03 원자 재연결 파이프라인이 실제로
서는지 본다:
  ① 개념 선적재를 **원자 code 행**(크로스워크 primary: HK06→10공수1-02-02-1 등·source_id NULL)
     으로 심고 → 코퍼스 적재 → `problem_concept.concept_id`가 *원자 행 UUID*를 가리킴을 단언
     (구 437 legacy 행 아님 — 크로스워크 해석 체인 실증).
  ② stale 구 링크 삽입 → 재적재 → reconcile DELETE가 그 잔재를 청소함을 실증.
  ③ 멱등 — 2회 적재 후 `problem`·`problem_concept` 행 수 불변(count 안정).
PG 미도달 시 graceful skip(`test_misconception_loader_integration.py` 미러). 정리는 이 테스트가
*만든* 행만 DELETE한다(실 DB에 원자 백본이 이미 적재돼 있으면 그 행은 건드리지 않음).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.problem_bank.populate import ProblemBankStore, populate_problem_bank

pytestmark = pytest.mark.integration

# 코퍼스 태그 src → 크로스워크 primary_atom_code(실 crosswalk.jsonl 실측·재연결 목적지 행 code).
_SRC_TO_ATOM = {
    "HK06": "10공수1-02-02-1",
    "HK10": "10공수1-02-05-1",
    "HK11": "10공수1-02-06-2",
    "HK09": "10공수1-02-04-1",
}
_ATOM_CODES = sorted(_SRC_TO_ATOM.values())
# stale 구 링크 실증용 가짜 legacy 개념(테스트 전용 code — 실 데이터와 충돌 없음).
_STALE_CODE = "IT-PROBBANK-STALE"
_SLUGS = [
    "wm-quad-eq-larger-root",
    "wm-quad-eq-smaller-root",
    "wm-quad-fn-axis",
    "wm-quad-eq-root-count-mc",
]

_ROOT = Path(__file__).resolve().parents[4]


def _corpus_path() -> Path:
    return _ROOT / "data" / "corpus" / "problem_bank_v1" / "problems.jsonl"


def _store() -> ProblemBankStore:
    """실 코퍼스 크로스워크/다리 경로를 레포 앵커로 주입한 store(기본 경로는 CWD 의존)."""
    return ProblemBankStore(
        settings=Settings(),
        crosswalk_path=_ROOT / "data" / "corpus" / "concept_atom_crosswalk_v1" / "crosswalk.jsonl",
        concept_graph_path=_ROOT / "data" / "corpus" / "concept_graph_v1" / "graph.json",
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
        return True
    except Exception:
        return False
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _skip_if_unreachable() -> None:
    if not _reachable():
        pytest.skip(
            "PostgreSQL 미도달(또는 마이그레이션 미적용) — 통합 테스트 건너뜀 "
            "(WHYMATH_DATABASE_URL·alembic upgrade head 확인)"
        )


def _seed_atom_concepts() -> list[str]:
    """원자 code 행 선적재 — 크로스워크 해석이 닿을 목적지 행. *새로 만든* code만 반환(정리용).

    실 DB에 원자 백본(`l1/atom_graph` populate)이 이미 적재돼 있으면 그 행을 그대로 쓰고
    (ON CONFLICT DO NOTHING), 정리 때도 건드리지 않는다(공유 실 데이터 보호).
    """
    from sqlalchemy import text

    engine = _sync_engine()
    created: list[str] = []
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            for code in [*_ATOM_CODES, _STALE_CODE]:
                exists = conn.execute(
                    text("SELECT 1 FROM concept WHERE code = :code"), {"code": code}
                ).first()
                if exists:
                    continue
                conn.execute(
                    text(
                        "INSERT INTO concept (concept_id, code, name_ko, level) "
                        "VALUES (:cid, :code, :name, '세부개념') "
                        "ON CONFLICT (code) DO NOTHING"
                    ),
                    {"cid": uuid.uuid4(), "code": code, "name": f"통합테스트 원자 {code}"},
                )
                created.append(code)
    finally:
        engine.dispose()  # type: ignore[attr-defined]
    return created


def _cleanup(created_codes: list[str] | None = None) -> None:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(
                text(
                    "DELETE FROM problem_concept WHERE problem_id IN "
                    "(SELECT problem_id FROM problem WHERE slug = ANY(:slugs))"
                ),
                {"slugs": _SLUGS},
            )
            # LIC-03 — 원장 선삭제. `content_provenance.problem_id → problem`은
            # ON DELETE 절이 없어(NO ACTION) 원장 행이 남아 있으면 문항 DELETE가
            # IntegrityError로 막힌다(2026-09-21 실 PG 프로브 실측). 감사 추적을 조용히
            # 지우지 않으려는 의도적 설계이므로, 정리하는 쪽이 순서를 맞춘다.
            conn.execute(
                text(
                    "DELETE FROM content_provenance WHERE problem_id IN "
                    "(SELECT problem_id FROM problem WHERE slug = ANY(:slugs))"
                ),
                {"slugs": _SLUGS},
            )
            conn.execute(text("DELETE FROM problem WHERE slug = ANY(:slugs)"), {"slugs": _SLUGS})
            if created_codes:
                # 이 테스트가 *만든* 개념 행만 제거 — 실 원자 백본 행은 보호.
                conn.execute(
                    text("DELETE FROM concept WHERE code = ANY(:codes)"),
                    {"codes": created_codes},
                )
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


def _concept_id_of(code: str) -> uuid.UUID:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            return uuid.UUID(
                str(
                    conn.execute(
                        text("SELECT concept_id FROM concept WHERE code = :code"), {"code": code}
                    ).scalar_one()
                )
            )
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _linked_concept_ids(slug: str) -> set[uuid.UUID]:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                text(
                    "SELECT pc.concept_id FROM problem_concept pc "
                    "JOIN problem p ON p.problem_id = pc.problem_id WHERE p.slug = :slug"
                ),
                {"slug": slug},
            ).all()
        return {uuid.UUID(str(r[0])) for r in rows}
    finally:
        engine.dispose()  # type: ignore[attr-defined]


class TestRealCorpusRelink:
    def test_load_links_to_atom_rows(self) -> None:
        """적재 후 problem_concept.concept_id가 *원자 code 행* UUID를 가리킨다(재연결 실증)."""
        _skip_if_unreachable()
        corpus = _corpus_path()
        if not corpus.exists():
            pytest.skip("실 코퍼스 미존재(data/corpus/problem_bank_v1/problems.jsonl)")
        created = _seed_atom_concepts()
        try:
            _cleanup(None)  # 선행 잔여 문제 제거(개념 행은 유지)
            report = populate_problem_bank(None, problems_path=corpus, store=_store())
            assert report.problems_loaded == 4
            # 원자 행 선재 → 태깅 전건 해석(orphan 0). 시드 태깅 총 6건(HK06×3+HK10+HK11+HK09).
            assert report.concepts_skipped == 0
            assert report.problem_concepts_loaded == 6

            prob_rows = _count(
                "SELECT count(*) FROM problem WHERE slug = ANY(:slugs)", {"slugs": _SLUGS}
            )
            pc_rows = _count(
                "SELECT count(*) FROM problem_concept WHERE problem_id IN "
                "(SELECT problem_id FROM problem WHERE slug = ANY(:slugs))",
                {"slugs": _SLUGS},
            )
            assert prob_rows == 4
            assert pc_rows == 6
            # 재연결 목적지 단언 — larger-root(HK06)의 링크가 원자 행 10공수1-02-02-1 UUID다.
            hk06_atom_id = _concept_id_of(_SRC_TO_ATOM["HK06"])
            assert _linked_concept_ids("wm-quad-eq-larger-root") == {hk06_atom_id}
            # fn-axis(HK10+HK11) — 두 원자 행 UUID.
            assert _linked_concept_ids("wm-quad-fn-axis") == {
                _concept_id_of(_SRC_TO_ATOM["HK10"]),
                _concept_id_of(_SRC_TO_ATOM["HK11"]),
            }
        finally:
            _cleanup(created)

    def test_reconcile_removes_stale_links(self) -> None:
        """구 연결(다른 concept 행) 잔재를 삽입해두면 재적재 reconcile이 삭제한다."""
        _skip_if_unreachable()
        corpus = _corpus_path()
        if not corpus.exists():
            pytest.skip("실 코퍼스 미존재(data/corpus/problem_bank_v1/problems.jsonl)")
        from sqlalchemy import text

        created = _seed_atom_concepts()
        try:
            _cleanup(None)
            populate_problem_bank(None, problems_path=corpus, store=_store())
            # stale 링크 삽입 — 구 437 legacy 행을 모사하는 별도 concept로 연결(구 연결 잔재).
            stale_cid = _concept_id_of(_STALE_CODE)
            engine = _sync_engine()
            try:
                with engine.begin() as conn:  # type: ignore[attr-defined]
                    conn.execute(
                        text(
                            "INSERT INTO problem_concept (problem_id, concept_id, role) "
                            "SELECT problem_id, :cid, 'PRIMARY' FROM problem WHERE slug = :slug"
                        ),
                        {"cid": stale_cid, "slug": "wm-quad-eq-larger-root"},
                    )
            finally:
                engine.dispose()  # type: ignore[attr-defined]
            assert stale_cid in _linked_concept_ids("wm-quad-eq-larger-root")

            # 재적재 → reconcile DELETE가 stale 잔재를 청소(해석 집합 밖 행 삭제).
            report = populate_problem_bank(None, problems_path=corpus, store=_store())
            assert report.problem_concepts_reconciled >= 1
            links = _linked_concept_ids("wm-quad-eq-larger-root")
            assert stale_cid not in links
            assert links == {_concept_id_of(_SRC_TO_ATOM["HK06"])}
        finally:
            _cleanup(created)

    def test_reload_is_idempotent(self) -> None:
        _skip_if_unreachable()
        corpus = _corpus_path()
        if not corpus.exists():
            pytest.skip("실 코퍼스 미존재(data/corpus/problem_bank_v1/problems.jsonl)")
        created = _seed_atom_concepts()
        try:
            _cleanup(None)
            populate_problem_bank(None, problems_path=corpus, store=_store())
            first_prob = _count(
                "SELECT count(*) FROM problem WHERE slug = ANY(:slugs)", {"slugs": _SLUGS}
            )
            first_pc = _count(
                "SELECT count(*) FROM problem_concept WHERE problem_id IN "
                "(SELECT problem_id FROM problem WHERE slug = ANY(:slugs))",
                {"slugs": _SLUGS},
            )
            # 2회차 재적재 — slug/복합 PK 충돌 upsert + reconcile(정합 집합 동일)라 행 수 불변.
            populate_problem_bank(None, problems_path=corpus, store=_store())
            second_prob = _count(
                "SELECT count(*) FROM problem WHERE slug = ANY(:slugs)", {"slugs": _SLUGS}
            )
            second_pc = _count(
                "SELECT count(*) FROM problem_concept WHERE problem_id IN "
                "(SELECT problem_id FROM problem WHERE slug = ANY(:slugs))",
                {"slugs": _SLUGS},
            )
            assert first_prob == 4
            assert second_prob == 4  # 멱등(문제 행 안정)
            assert first_pc == 6
            assert second_pc == 6  # 멱등(태깅 행 안정)
        finally:
            _cleanup(created)
