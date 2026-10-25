"""콘텐츠 4종 PG 프로젝션 *통합테스트* — Phase 3 Slice 1 (WHYMATH_RUN_INTEGRATION·실 PG).

마이그레이션 head 적용 실 PostgreSQL(`concept_content` 테이블)에 콘텐츠 코퍼스(K-12 437 + 대학
409)를 end-to-end 적재한다. CI `backend — 마이그레이션·통합 (실 PG)` 잡이 `alembic upgrade head`
(→ `concept_content` 포함) 후 `WHYMATH_RUN_INTEGRATION=1`로 수집·실행한다. PG 미도달 또는 코퍼스
미존재 시 graceful skip(원자 프로젝션 통합테스트 동형).

검증:
  ① 적재 — concept_content 846행(K-12 437 + 대학 409)·scope 분포
  ② flashcards JSONB 왕복(리스트 보존)·standard_codes TEXT[] 왕복
  ③ review_status 전건 'ai_estimated'(콘텐츠는 AI 추정·검수필요)
  ④ redaction — 본문 컬럼(core_proposition·description·statement) 부재(조회 시 오류)
  ⑤ 멱등 — 재적재 시 concept_content 행수 불변
구 437 concept·concept_node(UC 키)·atom_node와 별개(신규 테이블·additive)를 건드리지 않는다.
정리는 concept_content code 전건.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.config import Settings
from whymath_backend.db.models.concept_content import (
    CONTENT_SCOPE_K12,
    CONTENT_SCOPE_UNIVERSITY,
)
from whymath_backend.l1.concept_content.projection import (
    load_concept_content_from_json,
    populate_concept_content,
)

pytestmark = pytest.mark.integration

# 레포 루트 앵커(tests/backend/l1/concept_content/ → parents[4]) — CWD 상대 경로는
# CI(cwd=src/backend)에서 항상 "코퍼스 미존재" skip(침묵 skip 결함 수정).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_K12_CORPUS = _REPO_ROOT / "data" / "corpus" / "concept_content_v1" / "content.json"
_UNIV_CORPUS = _REPO_ROOT / "data" / "corpus" / "concept_content_university_v1" / "content.json"

# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
_FACTS = json.loads((_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8"))
# 적재 총행 = K-12 콘텐츠 + 대학 콘텐츠(계산식이 드러나게 사실의 합으로 쓴다).
_EXPECTED_TOTAL = _FACTS["concept_content.k12"] + _FACTS["concept_content.university"]


def _sync_engine() -> object:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    settings = Settings()
    url = settings.sync_database_url
    if settings.db_disable_pool:
        return create_engine(url, poolclass=NullPool)
    return create_engine(url)


def _reachable() -> bool:
    """실 PG 도달 + `concept_content` 테이블 존재(마이그레이션 적용) 여부."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            conn.execute(text("SELECT count(*) FROM concept_content"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _codes_from(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [str(c["code"]) for c in payload["content"]]


def _skip_guard() -> list[str]:
    if not _reachable():
        pytest.skip("PG 미도달 또는 마이그레이션 미적용(concept_content) — 통합 건너뜀")
    if not _K12_CORPUS.exists() or not _UNIV_CORPUS.exists():
        pytest.skip("콘텐츠 코퍼스 미존재(concept_content_v1·university)")
    return _codes_from(_K12_CORPUS) + _codes_from(_UNIV_CORPUS)


def _cleanup(codes: list[str]) -> None:
    """concept_content 적재 행 정리(code 전건). FK 0이라 단순 DELETE."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(text("DELETE FROM concept_content WHERE code = ANY(:k)"), {"k": codes})
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _load_all() -> int:
    """K-12 + 대학 코퍼스를 적재하고 총 적재 행 수를 반환."""
    k12 = load_concept_content_from_json(_K12_CORPUS, scope=CONTENT_SCOPE_K12)
    univ = load_concept_content_from_json(_UNIV_CORPUS, scope=CONTENT_SCOPE_UNIVERSITY)
    total = populate_concept_content(k12, settings=Settings())
    total += populate_concept_content(univ, settings=Settings())
    return total


class TestConceptContentProjectionLoad:
    def test_end_to_end_load_idempotent(self) -> None:
        codes = _skip_guard()
        from sqlalchemy import text
        from sqlalchemy.exc import SQLAlchemyError

        try:
            # ① 적재 — K-12 + 대학 = 사실 파일의 두 건수 합.
            total = _load_all()
            assert total == _EXPECTED_TOTAL

            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    count = conn.execute(
                        text("SELECT count(*) FROM concept_content WHERE code = ANY(:k)"),
                        {"k": codes},
                    ).scalar_one()
                    assert count == _EXPECTED_TOTAL

                    # ① scope 분포(K-12·대학 — 사실 파일의 건수).
                    scope_rows = conn.execute(
                        text(
                            "SELECT scope, count(*) AS n FROM concept_content "
                            "WHERE code = ANY(:k) GROUP BY scope"
                        ),
                        {"k": codes},
                    ).all()
                    by_scope = {r.scope: r.n for r in scope_rows}
                    assert by_scope.get(CONTENT_SCOPE_K12) == _FACTS["concept_content.k12"]
                    assert by_scope.get(CONTENT_SCOPE_UNIVERSITY) == _FACTS["concept_content.university"]

                    # ② flashcards JSONB·standard_codes TEXT[] 왕복(타입 보존).
                    sample = conn.execute(
                        text(
                            "SELECT flashcards, standard_codes, review_status "
                            "FROM concept_content WHERE code = :c"
                        ),
                        {"c": codes[0]},
                    ).one()
                    assert isinstance(sample.flashcards, list)
                    assert isinstance(sample.standard_codes, list)
                    # ③ review_status 전건 'ai_estimated'.
                    statuses = conn.execute(
                        text(
                            "SELECT DISTINCT review_status FROM concept_content "
                            "WHERE code = ANY(:k)"
                        ),
                        {"k": codes},
                    ).all()
                    assert [r.review_status for r in statuses] == ["ai_estimated"]

                    # ④ redaction — 본문 컬럼 부재(존재하면 SELECT 성공·부재면 오류).
                    for col in ("core_proposition", "description", "statement"):
                        with pytest.raises(SQLAlchemyError):
                            with engine.connect() as c2:  # type: ignore[attr-defined]
                                c2.execute(
                                    text(f"SELECT {col} FROM concept_content LIMIT 1")  # noqa: S608
                                )
            finally:
                engine.dispose()  # type: ignore[attr-defined]

            # ⑤ 멱등 — 재적재 후 행수 불변.
            total2 = _load_all()
            assert total2 == _EXPECTED_TOTAL
            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    count2 = conn.execute(
                        text("SELECT count(*) FROM concept_content WHERE code = ANY(:k)"),
                        {"k": codes},
                    ).scalar_one()
                    assert count2 == _EXPECTED_TOTAL  # 중복 0(멱등)
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup(codes)
