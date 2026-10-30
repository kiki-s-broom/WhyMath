"""Canonical ID Registry(`ids.yaml`) 거버넌스 — registry⇄graph 패리티·교육과정 독립·멱등·충돌 접미.

정본: docs/standards/part9_id_policy_review.md(P2d ①③) + docs/data/concept_graph.md §2.4.

이 테스트는 P2d 재ID(math.<area>.<slug>)의 하드게이트를 자동화한다:
  - registry(ids.yaml)와 graph.json 노드가 전량 1:1(고아 0 · 건수는 사실 파일).
  - canonical에 학년/트랙 토큰·NCIC 코드조각이 없다(교육과정 독립 — Part 9 ①).
  - area가 학년 독립([중]기하·[고]기하 → geometry).
  - 별칭에 교육과정축 코드·옛 UC·src_id 3중 보존, migrations에 P2a·P2d 이벤트.
  - build_registry 재실행·dump→load 왕복이 멱등, 충돌 접미(-2)가 결정론적.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from data_pipeline.concept_graph.idmap import build_id_map
from data_pipeline.concept_graph.models import (
    CONCEPT_ID_PATTERN,
    CURRICULUM_AXIS_PATTERN,
    LEGACY_UC_PATTERN,
)
from data_pipeline.concept_graph.registry import (
    build_registry,
    dump_registry_yaml,
    load_registry_yaml,
)
from data_pipeline.concept_graph.transform import transform_dataset
from data_pipeline.concept_graph.validate import validate_registry

_REPO_ROOT = Path(__file__).resolve().parents[3]
# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
# 고정 지점이 사실 파일 한 곳이다 — 값이 바뀌면 그 파일의 diff가 의식적 리뷰 지점이다.
_FACTS = json.loads(
    (_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
)

# 학년/트랙 토큰(교육과정 배치) — canonical에 등장 금지.
_GRADE_TOKEN = re.compile(r"(?i)\b(elem|mid|high|rt|oly)\b")


def _rec(src_id: str, name_ko: str, category: str, **over: object) -> dict[str, object]:
    rec: dict[str, object] = {
        "src_id": src_id,
        "name_ko": name_ko,
        "category": category,
        "standard_codes": [],
    }
    rec.update(over)
    return rec


class TestRegistryGraphParity:
    def test_registry_matches_graph(
        self,
        concept_records: list[dict[str, object]],
        edge_records: list[dict[str, object]],
    ) -> None:
        """registry canonical_id 집합 == graph concept_id 집합(전량 1:1·고아 0)."""
        result = transform_dataset(concept_records=concept_records, edge_records=edge_records)
        registry = build_registry(concept_records)
        report = validate_registry(registry, result.concepts)
        assert report.success is True, report.report_text()
        assert report.errors == []
        reg_ids = {e["canonical_id"] for e in registry["concepts"]}
        graph_ids = {c.concept_id for c in result.concepts}
        assert reg_ids == graph_ids
        assert len(reg_ids) == _FACTS["concept_graph.concepts"]

    def test_every_canonical_matches_regex(self, concept_records: list[dict[str, object]]) -> None:
        """모든 canonical_id가 신 규약(math.<area>.<slug>) 통과."""
        registry = build_registry(concept_records)
        bad = [
            e["canonical_id"]
            for e in registry["concepts"]
            if not CONCEPT_ID_PATTERN.fullmatch(e["canonical_id"])
        ]
        assert bad == []

    def test_registry_detects_orphan(self, concept_records: list[dict[str, object]]) -> None:
        """graph 노드에서 1건 빠지면 registry_graph_parity error(고아 탐지)."""
        result = transform_dataset(concept_records=concept_records, edge_records=[])
        registry = build_registry(concept_records)
        report = validate_registry(registry, result.concepts[:-1])  # 1개 누락
        rules = {i.rule for i in report.errors}
        assert "registry_graph_parity" in rules
        assert report.success is False


class TestCurriculumIndependence:
    def test_curriculum_independence_guard(self, concept_records: list[dict[str, object]]) -> None:
        """canonical 437개에 학년/트랙 토큰·NCIC 코드조각이 없다(교육과정 독립·Part 9 ①)."""
        registry = build_registry(concept_records)
        for entry in registry["concepts"]:
            cid = entry["canonical_id"]
            assert not _GRADE_TOKEN.search(cid), f"학년/트랙 토큰 누수: {cid}"
            # NCIC 코드조각(예 '[9수01-01]'·대괄호·중점) 부재
            assert "[" not in cid and "]" not in cid
            assert "수" not in cid  # 성취기준 코드 한글 과목자 부재(canonical은 ASCII)

    def test_area_is_grade_independent(self) -> None:
        """[중]기하·[고]기하 개념이 둘 다 area 'geometry'를 쓴다(학년 독립)."""
        records = [
            _rec("MG", "삼각형", "[중]기하", standard_codes=["[9수04-01]"]),
            _rec("HG", "포물선", "[고]기하", standard_codes=["[12기하01-01]"]),
        ]
        id_map = build_id_map(records)
        assert id_map["MG"].split(".")[1] == "geometry"
        assert id_map["HG"].split(".")[1] == "geometry"


class TestAliasAndMigrationRoundtrip:
    def test_alias_has_axis_uc_srcid(self, concept_records: list[dict[str, object]]) -> None:
        """registry 별칭에 교육과정축 코드·옛 UC·src_id가 모두 보존된다."""
        registry = build_registry(concept_records)
        for entry in registry["concepts"]:
            aliases = entry["aliases"]
            assert any(CURRICULUM_AXIS_PATTERN.match(a) for a in aliases)
            assert any(LEGACY_UC_PATTERN.match(a) for a in aliases)
            assert entry["src_id"] in aliases

    def test_migrations_have_p2a_and_p2d(self, concept_records: list[dict[str, object]]) -> None:
        """모든 개념 migrations에 P2a·P2d 이벤트, P2d.to==canonical·P2d.from=축코드."""
        registry = build_registry(concept_records)
        for entry in registry["concepts"]:
            events = {m["event"] for m in entry["migrations"]}
            assert {"P2a", "P2d"} <= events
            p2d = next(m for m in entry["migrations"] if m["event"] == "P2d")
            assert p2d["to"] == entry["canonical_id"]
            assert CURRICULUM_AXIS_PATTERN.match(p2d["from"])
            assert p2d["from"] in entry["aliases"]
            p2a = next(m for m in entry["migrations"] if m["event"] == "P2a")
            assert LEGACY_UC_PATTERN.match(p2a["from"])  # 옛 UC
            assert p2a["to"] == p2d["from"]  # UC→축코드→canonical 사슬


class TestIdempotence:
    def test_registry_regeneration_idempotent(
        self, concept_records: list[dict[str, object]]
    ) -> None:
        """build_registry 두 번 → 동일. dump→load 왕복도 동일(멱등·동결)."""
        r1 = build_registry(concept_records)
        r2 = build_registry(concept_records)
        assert r1 == r2
        roundtrip = load_registry_yaml(dump_registry_yaml(r1))
        assert roundtrip == r1

    def test_dump_has_header_and_version(self, concept_records: list[dict[str, object]]) -> None:
        """ids.yaml 본문에 수기편집 금지 헤더·version·generated_by가 실린다."""
        text = dump_registry_yaml(build_registry(concept_records))
        assert text.startswith("# 자동 생성물 — 수기 편집 금지")
        loaded = load_registry_yaml(text)
        assert loaded["version"] == 1
        assert "gen-ids" in loaded["generated_by"]


class TestCollisionSuffix:
    def test_collision_suffix_deterministic(self) -> None:
        """같은 (area, slug) 충돌군은 (tier, src_id) 정렬로 첫 무접미·이후 -2(재실행 동일)."""
        records = [
            _rec(
                "B",
                "지수법칙",
                "[고]대수",
                difficulty_tier="18",
                standard_codes=["[12대수01-01]"],
            ),
            _rec(
                "A",
                "지수법칙",
                "[중]문자·식·방정식",
                difficulty_tier="9",
                standard_codes=["[9수03-01]"],
            ),
        ]
        id_map = build_id_map(records)
        # 같은 name_ko('지수법칙')·같은 area(algebra/equation? [고]대수=algebra·[중]문자식=equation)
        # → 서로 다른 area면 충돌 아님. 충돌을 강제하려면 같은 category로.
        records2 = [
            _rec(
                "B",
                "지수법칙",
                "[고]대수",
                difficulty_tier="18",
                standard_codes=["[12대수01-02]"],
            ),
            _rec(
                "A",
                "지수법칙",
                "[고]대수",
                difficulty_tier="9",
                standard_codes=["[12대수01-01]"],
            ),
        ]
        m2 = build_id_map(records2)
        assert m2["A"] == "math.algebra.jisubeopchik"  # tier 9 먼저 → 무접미
        assert m2["B"] == "math.algebra.jisubeopchik-2"  # tier 18 → -2
        assert build_id_map(list(reversed(records2))) == m2  # 재실행 동일
        # (records/id_map은 area 분리 케이스 — 충돌 아님을 부수 확인)
        assert id_map["A"].split(".")[1] != id_map["B"].split(".")[1]

    def test_real_corpus_22_collision_groups(
        self, concept_records: list[dict[str, object]]
    ) -> None:
        """실데이터 전량 → 충돌 접미(-N)가 붙은 ID가 정확히 22건(기본↔공통 22군)."""
        id_map = build_id_map(concept_records)
        suffixed = [cid for cid in id_map.values() if re.search(r"-\d+$", cid)]
        assert len(suffixed) == 22
        assert (
            len(set(id_map.values())) == _FACTS["concept_graph.concepts"]
        )  # 충돌 해소 후 전량 유일


@pytest.mark.parametrize(
    "name_ko, expected_area",
    [
        ("삼각형", "geometry"),
        ("미분", "calculus"),
    ],
)
def test_area_segment_from_map(name_ko: str, expected_area: str) -> None:
    """canonical의 area 세그먼트가 _AREA_SLUG_MAP 영역어와 일치."""
    records = [_rec("X", name_ko, "[고]기하" if expected_area == "geometry" else "[고]미적분")]
    cid = build_id_map(records)["X"]
    assert cid.split(".")[1] == expected_area
