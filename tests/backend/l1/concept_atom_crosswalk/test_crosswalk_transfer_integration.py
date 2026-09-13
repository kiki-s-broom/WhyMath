"""437-키 자산 원자 축 이전 *통합테스트* — S0-2 (WHYMATH_RUN_INTEGRATION·실 PG).

마이그레이션 head(`b2c3d4e5f0a1`) 적용 실 PostgreSQL에서 이전 갱신을 end-to-end 검증한다.
합성 행(고유 접두 `S02IT-`)만 삽입·갱신·정리하므로 기존 데이터·전량 코퍼스 적재에 의존하지
않는다(형제 통합테스트의 graceful skip 규약 동형 — PG 미도달/마이그레이션 미적용 시 skip).

검증:
  ① atom_node.behavior_skills 갱신 — 값·이전 외 컬럼 무접촉·재실행 멱등
  ② concept.behavior_skills 갱신(SKB-01) — atom_node와 같은 mapping·대상 행 부재 missing 보고
  ③ concept_content.atom_codes(K-12) 갱신 — 값·대학 행 '{}' 불변(scope 필터)
  ④ 대상 행 부재 → missing 보고(조용히 넘기지 않음)
"""

from __future__ import annotations

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.concept_atom_crosswalk.transfer import (
    CrosswalkTransferStore,
    transfer_atom_behavior_skills,
    transfer_concept_behavior_skills,
    transfer_k12_content_atom_codes,
)

pytestmark = pytest.mark.integration

_ATOM_CODE = "S02IT-A1"
_ATOM_CODE_2 = "S02IT-A2"
_CONCEPT_CODE = "S02IT-C1"
_K12_CODE = "S02IT-N1"
_UNIV_CODE = "S02IT-U1"


def _sync_engine() -> object:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    settings = Settings()
    url = settings.sync_database_url
    if settings.db_disable_pool:
        return create_engine(url, poolclass=NullPool)
    return create_engine(url)


def _reachable() -> bool:
    """실 PG 도달 + 이전 컬럼 존재(마이그레이션 `b2c3d4e5f0a1` 적용) 여부."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            conn.execute(text("SELECT behavior_skills FROM atom_node LIMIT 0"))
            conn.execute(text("SELECT atom_codes FROM concept_content LIMIT 0"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _skip_guard() -> None:
    if not _reachable():
        pytest.skip("PG 미도달 또는 마이그레이션 미적용(b2c3d4e5f0a1) — 통합 건너뜀")


def _seed() -> None:
    """합성 대상 행 삽입 — atom_node 2행 + concept_content K-12 1행·대학 1행(고유 접두)."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(
                text(
                    "INSERT INTO atom_node (code, name_ko, level, review_status) "
                    "VALUES (:c, :n, '세부개념', 'ai_estimated') ON CONFLICT (code) DO NOTHING"
                ),
                [
                    {"c": _ATOM_CODE, "n": "S0-2 통합 합성 원자 1"},
                    {"c": _ATOM_CODE_2, "n": "S0-2 통합 합성 원자 2"},
                ],
            )
            conn.execute(
                text(
                    "INSERT INTO concept (code, name_ko, level) "
                    "VALUES (:c, :n, '세부개념') ON CONFLICT (code) DO NOTHING"
                ),
                [{"c": _CONCEPT_CODE, "n": "S0-2 통합 합성 concept 1"}],
            )
            conn.execute(
                text(
                    "INSERT INTO concept_content (code, scope, name, subject, review_status) "
                    "VALUES (:c, :s, :n, '통합테스트', 'ai_estimated') "
                    "ON CONFLICT (code) DO NOTHING"
                ),
                [
                    {"c": _K12_CODE, "s": "K-12", "n": "S0-2 통합 합성 K-12 콘텐츠"},
                    {"c": _UNIV_CODE, "s": "대학", "n": "S0-2 통합 합성 대학 콘텐츠"},
                ],
            )
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _cleanup() -> None:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(
                text("DELETE FROM atom_node WHERE code = ANY(:k)"),
                {"k": [_ATOM_CODE, _ATOM_CODE_2]},
            )
            conn.execute(
                text("DELETE FROM concept WHERE code = ANY(:k)"),
                {"k": [_CONCEPT_CODE]},
            )
            conn.execute(
                text("DELETE FROM concept_content WHERE code = ANY(:k)"),
                {"k": [_K12_CODE, _UNIV_CODE]},
            )
    finally:
        engine.dispose()  # type: ignore[attr-defined]


class TestCrosswalkTransferEndToEnd:
    def test_transfer_updates_and_scope_guard(self) -> None:
        _skip_guard()
        from sqlalchemy import text

        _seed()
        try:
            store = CrosswalkTransferStore(settings=Settings())

            # ① behavior_skills 갱신 — 사전순 값 그대로 영속·부재 code는 missing 보고.
            atom_report = transfer_atom_behavior_skills(
                {
                    _ATOM_CODE: ("skill.s1", "skill.s2"),
                    _ATOM_CODE_2: (),
                    "S02IT-NOPE": ("skill.s9",),
                },
                store=store,
            )
            assert atom_report.updated == 2
            assert atom_report.missing == ("S02IT-NOPE",)

            # ② concept.behavior_skills 갱신(SKB-01) — atom_node와 같은 mapping 재사용.
            concept_report = transfer_concept_behavior_skills(
                {_CONCEPT_CODE: ("skill.s1", "skill.s2"), "S02IT-NOPE": ("skill.s9",)},
                store=store,
            )
            assert concept_report.updated == 1
            assert concept_report.missing == ("S02IT-NOPE",)

            # ③ K-12 atom_codes 갱신 — 대학 code는 scope 필터로 차단(missing 보고·행 불변).
            content_report = transfer_k12_content_atom_codes(
                {_K12_CODE: (_ATOM_CODE, _ATOM_CODE_2), _UNIV_CODE: (_ATOM_CODE,)},
                store=store,
            )
            assert content_report.updated == 1
            assert content_report.missing == (_UNIV_CODE,)

            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    skills = conn.execute(
                        text("SELECT behavior_skills FROM atom_node WHERE code = :c"),
                        {"c": _ATOM_CODE},
                    ).scalar_one()
                    assert skills == ["skill.s1", "skill.s2"]
                    empty_skills = conn.execute(
                        text("SELECT behavior_skills FROM atom_node WHERE code = :c"),
                        {"c": _ATOM_CODE_2},
                    ).scalar_one()
                    assert empty_skills == []
                    # 이전 외 컬럼 무접촉 — name_ko·review_status 불변.
                    row = conn.execute(
                        text("SELECT name_ko, review_status FROM atom_node WHERE code = :c"),
                        {"c": _ATOM_CODE},
                    ).one()
                    assert row.name_ko == "S0-2 통합 합성 원자 1"
                    assert row.review_status == "ai_estimated"

                    concept_skills = conn.execute(
                        text("SELECT behavior_skills FROM concept WHERE code = :c"),
                        {"c": _CONCEPT_CODE},
                    ).scalar_one()
                    assert concept_skills == ["skill.s1", "skill.s2"]

                    k12_atoms = conn.execute(
                        text("SELECT atom_codes FROM concept_content WHERE code = :c"),
                        {"c": _K12_CODE},
                    ).scalar_one()
                    assert k12_atoms == [_ATOM_CODE, _ATOM_CODE_2]
                    # 대학 행 '{}' 불변(이미 원자 정합 — 다리 불요·scope 필터 차단).
                    univ_atoms = conn.execute(
                        text("SELECT atom_codes FROM concept_content WHERE code = :c"),
                        {"c": _UNIV_CODE},
                    ).scalar_one()
                    assert univ_atoms == []
            finally:
                engine.dispose()  # type: ignore[attr-defined]

            # ③ 멱등 — 같은 매핑 재실행 시 결과 동일(갱신 수 동일·값 불변).
            rerun = transfer_atom_behavior_skills(
                {_ATOM_CODE: ("skill.s1", "skill.s2")}, store=store
            )
            assert rerun.updated == 1
            assert rerun.missing == ()
        finally:
            _cleanup()
