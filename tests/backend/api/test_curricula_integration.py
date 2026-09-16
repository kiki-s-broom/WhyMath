"""curricula·alignments API 통합테스트 — 실제 PostgreSQL 왕복 (기본 SKIP, Phaiakes9/로컬 전용).

`WHYMATH_RUN_INTEGRATION=1` + 살아있는 PG(마이그레이션 head — CUR-10의 curriculum_framework/
curriculum_version 테이블 포함)에서만 실행한다. CI는 이 변수를 설정하지 않아 conftest 게이트가
자동 skip한다. PG 미도달 시에도 graceful skip(test_concepts_integration.py 동일 패턴).

검증: CUR-11 다섯 표면(/v1/curricula 목록·단건+버전·nodes·/v1/learning-outcomes·/v1/alignments)
이 실 PG에서 HTTP→get_session→PG로 왕복하는지 — 특히 hermetic이 못 보는 *SQL 실체*(정렬·
필터 WHERE·cardinality 빈 배열 가드·배열 ANY 대조·404)를 본다. 다섯 표면은 전부 GET·무인증이라
인증 픽스처가 없다(헤더 없는 200 자체가 무인증 계약 확인).

시드는 직접 엔진 ORM insert(다섯 표면에 쓰기 라우트가 없음), 실행마다 고유 suffix로 실 DB의
기존 데이터와 충돌·오염을 피하고 finally에서 역FK 순서로 정리한다. 목록(/v1/curricula)만은
전역 카탈로그라 *포함 여부*로 검증한다(기존 행 공존 허용 — test_concepts_integration의
LIST 멤버십 패턴).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# 전 모델 등록 — `Concept.current_published_version_id`가 `concept_version`을 FK로
# 참조하므로 개별 import만으로는 Base.metadata가 불완전해 NoReferencedTableError가 난다
# (모델 패키지 `__init__`이 전 테이블 등록의 정본 경로다 — env.py도 이것을 쓴다).
import whymath_backend.db.models  # noqa: F401
from whymath_backend.app import create_app
from whymath_backend.config import Settings
from whymath_backend.db.models.achievement_standard import AchievementStandard
from whymath_backend.db.models.atom_node import AtomNode
from whymath_backend.db.models.concept import Concept
from whymath_backend.db.models.concept_standard_link import ConceptStandardLink
from whymath_backend.db.models.curriculum_entry import CurriculumEntry
from whymath_backend.db.models.curriculum_framework import CurriculumFramework
from whymath_backend.db.models.curriculum_version import CurriculumVersion
from whymath_backend.db.models.misconception_catalog import MisconceptionCatalog
from whymath_backend.db.models.skill_node import SkillNode
from whymath_backend.schema.curriculum_entry import CurriculumEntry as CurriculumEntrySchema
from whymath_backend.schema.curriculum_framework import (
    CurriculumFramework as CurriculumFrameworkSchema,
)
from whymath_backend.schema.curriculum_version import (
    CurriculumVersion as CurriculumVersionSchema,
)
from whymath_backend.schema.enums import BehaviorArea, ConceptLevel, CurriculumLicense
from whymath_backend.schema.standard import (
    AchievementStandard as AchievementStandardSchema,
)
from whymath_backend.schema.standard import (
    ConceptStandardLink as ConceptStandardLinkSchema,
)

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)


async def _pg_reachable() -> bool:
    """독립 엔진으로 SELECT 1 — 도달 가능하면 True(실패는 False)."""
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


class _Seed:
    """실행 고유 suffix로 만든 시드 식별자 묶음(테스트가 경로·필터에 그대로 사용)."""

    def __init__(self) -> None:
        sfx = uuid.uuid4().hex[:8]
        self.framework_id = f"IT_CUR11_{sfx}"
        self.version_labels = ["IT_REV_A", "IT_REV_B"]  # framework 내 라벨이라 suffix 불요
        self.entry_ids = [f"it-ce-{sfx}-1", f"it-ce-{sfx}-2"]
        self.concept_ids = [f"it.cur11.{sfx}.a", f"it.cur11.{sfx}.b"]
        self.official_code = f"[IT{sfx}-99-01]"
        self.norm_id = f"IT_{sfx}_STD"
        self.concept_code = f"IT.UC.{sfx}"
        self.atom_code = f"it-atom-{sfx}"
        # ── 학습맵 체인(EOS-05) ──
        self.concept_uuid = uuid.uuid4()
        self.skill_id = f"skill.it-{sfx}"
        self.problem_uuid = uuid.uuid4()
        self.mis_id = f"ITM{sfx[:6]}"
        # 오개념은 **두 경로**로 걸린다(concept_src_id / behavior_skills). 한쪽만 심으면
        # 다른 절을 픽스처가 한 번도 밟지 않아 그 절은 검증된 적 없이 초록이 된다.
        self.mis_id_by_skill = f"ITS{sfx[:6]}"


async def _insert_seed(seed: _Seed) -> None:
    """CUR-11 다섯 표면이 읽는 여섯 테이블에 시드 적재 — FK 순서(framework 먼저)."""
    engine = create_async_engine(Settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                CurriculumFramework.from_schema(
                    CurriculumFrameworkSchema(
                        framework_id=seed.framework_id,
                        authority="통합테스트 기관",
                        country="KR",
                        title="CUR-11 통합테스트 프레임워크",
                        created_at=_NOW,
                        updated_at=_NOW,
                    )
                )
            )
            await session.commit()

            # 버전은 라벨 *역순* 삽입 — 응답의 오름차순 정렬이 SQL ORDER BY 실체임을 증명.
            for label in reversed(seed.version_labels):
                session.add(
                    CurriculumVersion.from_schema(
                        CurriculumVersionSchema(
                            version_id=uuid.uuid4(),
                            framework_id=seed.framework_id,
                            version_label=label,
                            effective_from=date(2025, 3, 1),
                            created_at=_NOW,
                            updated_at=_NOW,
                        )
                    )
                )
            # 셀 2건: 1번은 성취기준 코드 보유, 2번은 *빈 배열*(alignments cardinality 가드 표적).
            for entry_id, concept_id, codes in zip(
                seed.entry_ids,
                seed.concept_ids,
                [[seed.official_code], []],
                strict=True,
            ):
                session.add(
                    CurriculumEntry.from_schema(
                        CurriculumEntrySchema(
                            entry_id=entry_id,
                            concept_id=concept_id,
                            country_code="KR",
                            source_name="NCIC",
                            source_url="https://ncic.re.kr/example",
                            license_id=CurriculumLicense.KR_NCIC,
                            framework_id=seed.framework_id,
                            domain_label="변화와 관계",
                            introduced_grade=10,
                            is_present=True,
                            confidence=0.9,
                            national_standard_codes=codes,
                            created_at=_NOW,
                            updated_at=_NOW,
                        )
                    )
                )
            session.add(
                AchievementStandard.from_schema(
                    AchievementStandardSchema(
                        norm_id=seed.norm_id,
                        official_code=seed.official_code,
                        curriculum_revision="IT 개정",
                        framework_id=seed.framework_id,
                        grade_band="고등학교",
                        school_type="고등학교",
                        subject="공통수학1",
                        domain="변화와 관계",
                        statement="통합테스트용 성취기준 본문.",
                        official_statement="통합테스트용 성취기준 본문.",
                        source_url="https://ncic.re.kr/example",
                        version_id=uuid.uuid4(),
                    )
                )
            )
            session.add(
                AtomNode(
                    code=seed.atom_code,
                    name_ko="통합테스트 원자",
                    level="세부개념",
                    standard_codes=[seed.official_code],
                    behavior_skills=[],
                    review_status="ai_estimated",
                    updated_at=_NOW,
                )
            )
            await session.commit()

            # ── 학습맵 체인(EOS-05) — 1축(concept_standard_link)부터 오개념까지 ──
            # 1축은 norm_id 어휘를 쓰고 2·3축은 고시코드를 쓴다. 두 어휘를 다 심어야
            # "핸들러가 축별로 나눠 묻는가"가 실 SQL에서 판정된다(hermetic이 못 보는 축).
            session.add(
                Concept(
                    concept_id=seed.concept_uuid,
                    code=seed.concept_code,
                    name_ko="통합테스트 개념",
                    level=ConceptLevel.세부개념,
                    behavior_skills=[seed.skill_id],
                    created_at=_NOW,
                )
            )
            session.add(
                SkillNode(
                    skill_id=seed.skill_id,
                    name_ko="통합테스트 스킬",
                    behavior_area=BehaviorArea.TRANSFORM,
                    family="it-family",
                    mastery_estimable=True,
                    prerequisite_skill_ids=[],
                    standard_codes=[],
                    review_status="ai_estimated",
                    updated_at=_NOW,
                )
            )
            session.add(
                MisconceptionCatalog(
                    mis_id=seed.mis_id,
                    canonical_statement="통합테스트 오개념",
                    error_type="절차",
                    severity="high",
                    concept_src_id=seed.concept_code,
                    behavior_skills=[],
                )
            )
            # behavior_skills ARRAY overlap 경로 전용 — concept_src_id는 **일부러 다른 값**이라
            # 이 행은 overlap 절이 없으면 결과에서 사라진다(그 절의 반례).
            session.add(
                MisconceptionCatalog(
                    mis_id=seed.mis_id_by_skill,
                    canonical_statement="통합테스트 오개념(스킬 경로)",
                    error_type="절차",
                    severity="low",
                    concept_src_id=f"{seed.concept_code}.무관",
                    behavior_skills=[seed.skill_id],
                )
            )
            await session.commit()

            # 링크는 성취기준 FK가 선행돼야 하므로 마지막에.
            # (EOS-05 학습맵 1축도 이 링크를 그대로 쓴다 — 같은 행을 두 번 심지 않는다.)
            session.add(
                ConceptStandardLink.from_schema(
                    ConceptStandardLinkSchema(
                        concept_code=seed.concept_code,
                        norm_id=seed.norm_id,
                        link_type="직접",
                    )
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _delete_seed(seed: _Seed) -> None:
    """역FK 순서 정리 — 링크→성취기준→셀→버전→프레임워크→원자(잔여 방지)."""
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM concept_standard_link WHERE norm_id = :nid"),
                {"nid": seed.norm_id},
            )
            await conn.execute(
                text("DELETE FROM achievement_standard WHERE norm_id = :nid"),
                {"nid": seed.norm_id},
            )
            await conn.execute(
                text("DELETE FROM curriculum_entry WHERE entry_id = ANY(:ids)"),
                {"ids": seed.entry_ids},
            )
            await conn.execute(
                text("DELETE FROM curriculum_version WHERE framework_id = :fid"),
                {"fid": seed.framework_id},
            )
            await conn.execute(
                text("DELETE FROM curriculum_framework WHERE framework_id = :fid"),
                {"fid": seed.framework_id},
            )
            await conn.execute(
                text("DELETE FROM atom_node WHERE code = :code"),
                {"code": seed.atom_code},
            )
            # ── 학습맵 체인(EOS-05) — 역FK 순서: problem_concept → problem/concept ──
            await conn.execute(
                text("DELETE FROM problem_concept WHERE concept_id = :cid"),
                {"cid": seed.concept_uuid},
            )
            await conn.execute(
                text("DELETE FROM misconception_catalog WHERE mis_id = ANY(:mids)"),
                {"mids": [seed.mis_id, seed.mis_id_by_skill]},
            )
            await conn.execute(
                text("DELETE FROM concept WHERE concept_id = :cid"),
                {"cid": seed.concept_uuid},
            )
            await conn.execute(
                text("DELETE FROM skill_node WHERE skill_id = :sid"),
                {"sid": seed.skill_id},
            )
    finally:
        await engine.dispose()


@pytest.fixture
def seed() -> Iterator[_Seed]:
    """시드 적재 → yield → 정리. PG 미도달이면 skip(불필요한 삽입 시도 없음)."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")
    s = _Seed()
    asyncio.run(_insert_seed(s))
    try:
        yield s
    finally:
        asyncio.run(_delete_seed(s))


def test_curricula_surfaces_roundtrip_on_live_pg(seed: _Seed) -> None:
    """목록 멤버십·단건+버전 정렬·404·nodes 필터/정렬/페이지네이션이 실 PG에서 왕복한다."""
    with TestClient(create_app()) as client:
        # LIST — 전역 카탈로그라 멤버십으로 확인(기존 행 공존 허용).
        listed = client.get("/v1/curricula", params={"country": "KR", "limit": 200})
        assert listed.status_code == 200, listed.text
        assert seed.framework_id in {f["framework_id"] for f in listed.json()}

        # DETAIL — 본체 에코 + 버전이 라벨 오름차순(역순 삽입했으므로 ORDER BY 실체 증명).
        detail = client.get(f"/v1/curricula/{seed.framework_id}")
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["framework"]["title"] == "CUR-11 통합테스트 프레임워크"
        assert [v["version_label"] for v in body["versions"]] == seed.version_labels

        # DETAIL 404 — 없는 framework_id.
        assert client.get(f"/v1/curricula/IT_NOPE_{uuid.uuid4().hex[:8]}").status_code == 404

        # NODES — 우리 framework로 스코프되어 정확히 시드 2건, entry_id 오름차순.
        nodes = client.get(f"/v1/curricula/{seed.framework_id}/nodes")
        assert nodes.status_code == 200, nodes.text
        assert [n["entry_id"] for n in nodes.json()] == seed.entry_ids

        # NODES 필터 — subject는 데이터 축: 기본값 '수학'이라 일치 2건, 타 과목 0건.
        assert (
            len(
                client.get(
                    f"/v1/curricula/{seed.framework_id}/nodes", params={"subject": "수학"}
                ).json()
            )
            == 2
        )
        assert (
            client.get(
                f"/v1/curricula/{seed.framework_id}/nodes", params={"subject": "물리"}
            ).json()
            == []
        )

        # NODES 페이지네이션 — limit/offset이 SQL로 내려간다.
        first = client.get(f"/v1/curricula/{seed.framework_id}/nodes", params={"limit": 1})
        second = client.get(
            f"/v1/curricula/{seed.framework_id}/nodes", params={"limit": 1, "offset": 1}
        )
        assert [n["entry_id"] for n in first.json()] == [seed.entry_ids[0]]
        assert [n["entry_id"] for n in second.json()] == [seed.entry_ids[1]]


def test_learning_outcome_roundtrip_on_live_pg(seed: _Seed) -> None:
    """성취기준 단건 200(본문·출처 동봉)·404가 실 PG에서 왕복한다."""
    with TestClient(create_app()) as client:
        got = client.get(f"/v1/learning-outcomes/{seed.norm_id}")
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["official_code"] == seed.official_code
        assert body["official_statement"] == "통합테스트용 성취기준 본문."
        assert body["source_url"] == "https://ncic.re.kr/example"  # 공공누리 출처 표시

        assert (
            client.get(f"/v1/learning-outcomes/IT_NOPE_{uuid.uuid4().hex[:6]}").status_code == 404
        )


def test_alignments_three_axes_on_live_pg(seed: _Seed) -> None:
    """3축 합성이 실 SQL(ANY 대조·cardinality 빈 배열 가드)로 왕복한다.

    시드 official_code는 실행 고유 문자열이라 standard_ref 필터 결과가 정확히 우리 것이다.
    빈 배열 셀(entry 2번)은 cardinality 가드로 제외돼야 한다.
    """
    with TestClient(create_app()) as client:
        # official_code 어휘 필터 → 2축(셀)·3축(원자)만 매칭(1축은 norm_id 어휘라 불일치 — 정직).
        by_code = client.get("/v1/alignments", params={"standard_ref": seed.official_code})
        assert by_code.status_code == 200, by_code.text
        items = by_code.json()
        assert [i["axis"] for i in items] == ["curriculum_entry", "atom_node"]
        assert {i["standard_ref"] for i in items} == {seed.official_code}
        assert {i["standard_ref_kind"] for i in items} == {"official_code"}
        # 2축 항목은 셀의 framework_id를 동봉한다.
        assert items[0]["framework_id"] == seed.framework_id
        # 빈 배열 셀의 concept(b)는 나타나지 않는다(cardinality 가드).
        assert seed.concept_ids[1] not in {i["concept_key"] for i in items}

        # norm_id 어휘 필터 → 1축만 매칭.
        by_norm = client.get("/v1/alignments", params={"standard_ref": seed.norm_id})
        assert by_norm.status_code == 200
        norm_items = by_norm.json()
        assert [i["axis"] for i in norm_items] == ["concept_standard_link"]
        assert norm_items[0]["concept_key"] == seed.concept_code
        assert norm_items[0]["link_type"] == "직접"

        # concept_key 필터(2축 어휘) → 코드 보유 셀 1건만.
        by_concept = client.get("/v1/alignments", params={"concept_key": seed.concept_ids[0]})
        assert by_concept.status_code == 200
        concept_items = by_concept.json()
        assert [i["axis"] for i in concept_items] == ["curriculum_entry"]
        assert concept_items[0]["standard_ref"] == seed.official_code

        # 빈 배열 셀의 concept_key로는 어떤 축에서도 항목이 없다(가드의 대우 방향).
        assert (
            client.get("/v1/alignments", params={"concept_key": seed.concept_ids[1]}).json() == []
        )


def test_learning_map_chain_roundtrip_on_live_pg(seed: _Seed) -> None:
    """계획서 200 §18의 단일 질의가 실 PG에서 4홉 전부 관통한다 (EOS-05).

    hermetic(`test_curricula.py`·`tests/backend/l1/standards/test_learning_map.py`)이 못 보는
    **SQL 실체**를 본다:
      - 1축(`concept_standard_link`)은 **norm_id 어휘**로, 3축(`atom_node.standard_codes`)은
        **고시코드 어휘**로 각각 걸린다 — 한 어휘로 3축을 다 물으면 한쪽이 조용히 0이 된다.
      - `concept.code` ↔ `atom_node.code` 두 키 공간 조회가 실제 `in_` 대조로 성립한다.
      - `behavior_skills` 참조 배열 → `skill_node` 조인(신규 엣지 타입 0 설계).
      - `problem_concept` N:M 조인.
      - 오개념의 `concept_src_id` 느슨참조(FK 없음) 대조.
    """
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/learning-outcomes/{seed.norm_id}/learning-map")
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["norm_id"] == seed.norm_id
        assert body["official_code"] == seed.official_code

        # 1홉 — 두 어휘가 각자의 축에서 걸렸는가. concept_code는 1축(norm_id)에서,
        # atom_code는 3축(고시코드)에서만 나올 수 있다 — 둘 다 있으면 어휘 분기가 작동했다.
        keys = {c["concept_key"]: c for c in body["concepts"]}
        assert seed.concept_code in keys, "1축(norm_id 어휘)이 걸리지 않았다"
        assert seed.atom_code in keys, "3축(고시코드 어휘)이 걸리지 않았다"
        assert keys[seed.concept_code]["axes"] == ["concept_standard_link"]
        assert keys[seed.atom_code]["axes"] == ["atom_node"]

        # 키 공간 두 곳 — 각자 자기 테이블에서 해소됐는가.
        assert keys[seed.concept_code]["resolved_from"] == ["concept"]
        assert keys[seed.atom_code]["resolved_from"] == ["atom_node"]
        assert keys[seed.concept_code]["concept_id"] == str(seed.concept_uuid)
        assert body["concept_stats"]["resolved"] == 2
        assert body["concept_stats"]["join_blackout"] is False

        # 2홉 — behavior_skills 배열이 skill_node에 조인됐는가.
        skills = {s["skill_id"]: s for s in body["skills"]}
        assert seed.skill_id in skills, "behavior_skills → skill_node 조인이 성립하지 않았다"
        assert skills[seed.skill_id]["behavior_area"] == "TRANSFORM"
        assert skills[seed.skill_id]["via_concept_keys"] == [seed.concept_code]

        # 4홉 — 오개념의 concept_src_id 느슨참조(FK 없음)가 개념 키로 대조됐는가.
        mis = {m["mis_id"]: m for m in body["misconceptions"]}
        assert seed.mis_id in mis, "concept_src_id 대조가 성립하지 않았다"
        assert mis[seed.mis_id]["matched_by"] == ["concept_src_id"]
        # ARRAY overlap 경로 — 이 행의 concept_src_id는 개념 키와 다르므로 overlap 절이
        # 없으면 아예 나오지 않는다(절의 반례를 픽스처가 실제로 밟는다).
        assert seed.mis_id_by_skill in mis, "behavior_skills ARRAY overlap이 성립하지 않았다"
        assert mis[seed.mis_id_by_skill]["matched_by"] == ["behavior_skills"]

        # 3홉 — 이 시드는 문제를 심지 않았다. 그 0은 "없음"이지 "안 봄"이 아니어야 한다
        # (미측정 ≠ 0 — scanned>0이 그것을 증명한다).
        assert body["problems"] == []
        assert (
            body["problem_stats"]["scanned"] == 1
        ), "개념 UUID 1건을 훑었는데 scanned가 0이면 '없음'과 '안 봄'이 구분되지 않는다"
        assert body["problem_stats"]["produced"] == 0


def test_learning_map_unknown_standard_returns_404_on_live_pg(seed: _Seed) -> None:
    """없는 성취기준은 404 — 실 PG에서도 조기 반환이 성립한다(seed는 PG 도달성 게이트용)."""
    assert seed.norm_id  # 픽스처가 PG 도달을 보장한다는 사실의 명시적 사용
    with TestClient(create_app()) as client:
        missing = f"IT_NOPE_{uuid.uuid4().hex[:8]}"
        assert client.get(f"/v1/learning-outcomes/{missing}/learning-map").status_code == 404
