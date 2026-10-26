"""transform 단위테스트 — 필드 매핑·redaction 부재·evidence 합성·review_status 분류·UC 변환.

정본: docs/data/concept_graph.md §2·§4 + docs/data/concept_graph_dataset_v1.md §2·§3·§4.
"""

from __future__ import annotations

import json
from pathlib import Path

from data_pipeline.concept_graph.idmap import build_id_map
from data_pipeline.concept_graph.models import EvidenceSource, Relation, ReviewStatus
from data_pipeline.concept_graph.transform import (
    build_locales,
    transform_concepts,
    transform_dataset,
    transform_edges,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
# 고정 지점이 사실 파일 한 곳이다 — 값이 바뀌면 그 파일의 diff가 의식적 리뷰 지점이다.
_FACTS = json.loads(
    (_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
)

# 합성 픽스처용 고정 canonical ID(math.<area>.<slug>·pattern 통과). HK01·HK02는 [공통]식·방정식·
# 부등식(area=equation)이라 area는 equation으로 고정하고 slug만 임의 부여한다.
_ID_A = "math.equation.dahangsigui-yeonsan"
_ID_B = "math.equation.nameojijeongni"

# 최소 합성 레코드(단위테스트용 — 실데이터는 fixture).
_CONCEPT_A = {
    "src_id": "HK01",
    "name_ko": "다항식의 연산",
    "category": "[공통]식·방정식·부등식",
    "difficulty_tier": "6",
    "standard_codes": ["[10공수1-01-01]"],
    "ccss_code": "A-APR.A.1",
    "metaphor": "수처럼 더하고 곱하기",
    "misconception": "(a+b)²=a²+b²로 전개",
    "accepted_expressions": "동류항끼리 정리",
    "definition_provenance": "수기 검수",
    "flashcard_count": "0",
    "_redacted_fields": ["description", "formal_definition"],
}
_CONCEPT_B = {
    "src_id": "HK02",
    "name_ko": "나머지정리",
    "category": "[공통]식·방정식·부등식",
    "difficulty_tier": "7",
    "standard_codes": ["[10공수1-01-02]"],
    "ccss_code": "A-APR.B.2",
    "metaphor": "",
    "misconception": "",
    "accepted_expressions": "",
    "definition_provenance": "자동(설명기반)·검수필요",
    "flashcard_count": "0",
}


def _id_map() -> dict[str, str]:
    """HK01·HK02 → canonical ID. 합성 픽스처용 고정 매핑(transform_concepts는 이 값을 직결)."""
    return {"HK01": _ID_A, "HK02": _ID_B}


def _alias_map() -> dict[str, list[str]]:
    """HK01·HK02 별칭([교육과정축 코드, 옛 UC, src_id]) — source_id·aliases 단언용."""
    return {
        "HK01": ["HIGH-EQN-001", "UC.common1.a01.hk01", "HK01"],
        "HK02": ["HIGH-EQN-002", "UC.common1.a01.hk02", "HK02"],
    }


class TestTransformConcepts:
    def test_maps_core_fields(self) -> None:
        concepts, skipped = transform_concepts([_CONCEPT_A], _id_map(), _alias_map())
        assert skipped == []
        c = concepts[0]
        assert c.concept_id == _ID_A  # canonical ID 변환
        assert c.source_id == "HK01"  # 원천 보존
        assert c.aliases == [
            "HIGH-EQN-001",
            "UC.common1.a01.hk01",
            "HK01",
        ]  # 축코드·옛 UC·src_id
        assert c.domain == "식·방정식·부등식"  # category → domain(교육과정 접두 `[공통]` 제거·P2e)
        assert c.standard_codes == ["[10공수1-01-01]"]

    def test_maps_enriched_fields(self) -> None:
        c = transform_concepts([_CONCEPT_A], _id_map())[0][0]
        assert c.ccss_code == "A-APR.A.1"
        assert c.difficulty_tier == 6  # 문자열 "6" → int

    def test_maps_semantic_layer(self) -> None:
        """semantic 복원(Phase 1): raw metaphor→intuition·accepted_expressions→representations."""
        c = transform_concepts([_CONCEPT_A], _id_map())[0][0]
        assert c.intuition == "수처럼 더하고 곱하기"  # raw metaphor
        assert c.representations == "동류항끼리 정리"  # raw accepted_expressions

    def test_maps_behavior_skills(self) -> None:
        """concept→skill 매핑(Phase 2b-1): raw behavior_skills → 노드 참조 키
        (standard_codes 미러)."""
        record = dict(_CONCEPT_A)
        record["behavior_skills"] = ["skill.polynomial-arithmetic", "skill.factorization"]
        c = transform_concepts([record], _id_map())[0][0]
        assert c.behavior_skills == ["skill.polynomial-arithmetic", "skill.factorization"]

    def test_behavior_skills_absent_defaults_empty(self) -> None:
        """behavior_skills 키 부재 → 빈 목록(초등 산술 등 미매핑 개념·정직·dangling 허용)."""
        record = dict(_CONCEPT_A)
        record.pop("behavior_skills", None)
        c = transform_concepts([record], _id_map())[0][0]
        assert c.behavior_skills == []

    def test_input_misconception_freetext_not_mapped(self) -> None:
        """자유텍스트 오개념(raw misconception)은 노드로 흘리지 않는다(독립 DB·CLAUDE.md #6)."""
        c = transform_concepts([_CONCEPT_A], _id_map())[0][0]
        # _CONCEPT_A는 misconception 키를 갖지만 노드엔 슬롯 자체가 없다
        # (intuition/representations는 매핑됨).
        assert not hasattr(c, "misconception_text")
        assert not hasattr(c, "metaphor")  # 옛 필드명(intuition으로 대체)
        assert not hasattr(c, "accepted_expressions")  # 옛 필드명(representations로 대체)

    def test_grade_band_hint_inferred(self) -> None:
        """첫 standard_code 학년 → NCIC 학년군 추론."""
        c = transform_concepts([_CONCEPT_A], _id_map())[0][0]
        assert c.grade_band_hint == "고등학교"  # [10...] → 고등학교

    def test_display_names_not_on_node(self) -> None:
        """표시이름(name_ko/en/ja)은 노드 비내장(P2d Concept Purity) — locale 레이어로 분리."""
        c = transform_concepts([_CONCEPT_A], _id_map())[0][0]
        assert not hasattr(c, "name_ko")
        assert not hasattr(c, "name_en")
        assert not hasattr(c, "name_ja")
        assert "name_ko" not in c.model_dump()

    def test_empty_enriched_become_none(self) -> None:
        """빈 문자열 풍부 필드(ccss_code)는 None으로 정규화(`_opt`)."""
        record = dict(_CONCEPT_A)
        record["ccss_code"] = ""
        c = transform_concepts([record], _id_map())[0][0]
        assert c.ccss_code is None

    def test_review_status_reviewed_for_manual(self) -> None:
        """definition_provenance='수기 검수' → reviewed."""
        c = transform_concepts([_CONCEPT_A], _id_map())[0][0]
        assert c.review_status == ReviewStatus.REVIEWED.value

    def test_review_status_pending_for_auto(self) -> None:
        """그 외(자동·검수필요) → pending."""
        c = transform_concepts([_CONCEPT_B], _id_map())[0][0]
        assert c.review_status == ReviewStatus.PENDING.value

    def test_review_status_reviewed_for_ai_marker(self) -> None:
        """출처 보존 + '·AI 검수' 마커 → reviewed (출처 문자열은 그대로 살림)."""
        record = {
            **_CONCEPT_A,
            "definition_provenance": "2022 개정 교육과정 별책8(기본수학)·AI 검수(수식·오개념 정합)",
        }
        c = transform_concepts([record], _id_map())[0][0]
        assert c.review_status == ReviewStatus.REVIEWED.value

    def test_skips_unmapped_src_id(self) -> None:
        """id_map에 없는 src_id → skip."""
        concepts, skipped = transform_concepts([_CONCEPT_A], {})
        assert concepts == []
        assert len(skipped) == 1

    def test_redacted_keys_not_read(self) -> None:
        """입력에 description/formal_definition이 있어도 산출 모델엔 미포함(슬롯 부재)."""
        record = dict(_CONCEPT_A)
        record["description"] = "성취기준 본문 근접 복제"
        record["formal_definition"] = "교과서 정의"
        c = transform_concepts([record], _id_map())[0][0]
        dump = c.model_dump()
        assert "description" not in dump
        assert "formal_definition" not in dump

    def test_non_integer_difficulty_tier_becomes_none(self) -> None:
        """비정수 difficulty_tier는 None(검증은 Pydantic ge/le에 위임)."""
        record = dict(_CONCEPT_A)
        record["difficulty_tier"] = "N/A"
        c = transform_concepts([record], _id_map())[0][0]
        assert c.difficulty_tier is None

    def test_grade_band_hint_none_when_unparseable(self) -> None:
        """파싱 불가 standard_code만 있으면 grade_band_hint=None(단정 아닌 힌트)."""
        record = dict(_CONCEPT_A)
        record["standard_codes"] = ["not-a-code"]
        id_map = {"HK01": _ID_A}
        c = transform_concepts([record], id_map)[0][0]
        assert c.grade_band_hint is None

    def test_missing_name_ko_absent_from_locale(self) -> None:
        """name_ko 빈 레코드는 노드는 만들되(표시이름 비내장) locale(ko)에서 제외된다."""
        record = dict(_CONCEPT_A)
        record["name_ko"] = ""
        concepts, skipped = transform_concepts([record], _id_map())
        assert len(concepts) == 1  # 표시이름은 노드에 없으므로 노드 생성은 성공
        assert skipped == []
        locales = build_locales([record], _id_map())
        assert _ID_A not in locales["ko"]  # 빈 name_ko → locale 제외

    def test_record_without_src_id_skipped(self) -> None:
        concepts, skipped = transform_concepts([{"name_ko": "x"}], _id_map())
        assert concepts == []
        assert len(skipped) == 1


class TestTransformEdges:
    def test_maps_prerequisite_with_synthesized_evidence(self) -> None:
        """선수 엣지 → PREREQUISITE + evidence/strength/source 합성."""
        records = [
            {
                "from_id": "HK01",
                "from_name": "다항식의 연산",
                "relation": "선수(prereq)",
                "to_id": "HK02",
                "to_name": "나머지정리",
            }
        ]
        edges, skipped = transform_edges(records, _id_map())
        assert skipped == []
        e = edges[0]
        assert e.src_concept_id == _ID_A  # canonical ID 변환
        assert e.dst_concept_id == _ID_B
        assert e.relation == Relation.PREREQUISITE.value
        assert e.evidence  # 비공백(합성)
        assert e.evidence_source == EvidenceSource.EXPERT_REVIEW.value
        assert 0.0 <= e.strength <= 1.0

    def test_skips_unsupported_relation(self) -> None:
        records = [
            {"from_id": "HK01", "relation": "일반화", "to_id": "HK02"},
        ]
        edges, skipped = transform_edges(records, _id_map())
        assert edges == []
        assert len(skipped) == 1

    def test_skips_dangling_endpoint(self) -> None:
        """id_map에 없는 끝점 → skip(억지 매핑 금지)."""
        records = [
            {"from_id": "HK01", "relation": "선수(prereq)", "to_id": "ZZZ"},
        ]
        edges, skipped = transform_edges(records, _id_map())
        assert edges == []
        assert len(skipped) == 1


class TestTransformDataset:
    def test_prerequisite_cache_filled(self) -> None:
        """엣지(src=선수→dst=후행) → dst 개념의 prerequisite_concept_ids 캐시 채움."""
        edge = {
            "from_id": "HK01",
            "relation": "선수(prereq)",
            "to_id": "HK02",
        }
        result = transform_dataset(
            concept_records=[_CONCEPT_A, _CONCEPT_B],
            edge_records=[edge],
        )
        # transform_dataset은 name_ko 파생 canonical ID를 쓴다 — 하드코딩 대신 매핑을 재계산해 조회.
        id_map = build_id_map([_CONCEPT_A, _CONCEPT_B])
        a_id, b_id = id_map["HK01"], id_map["HK02"]
        by_id = {c.concept_id: c for c in result.concepts}
        assert by_id[b_id].prerequisite_concept_ids == [a_id]
        assert by_id[a_id].prerequisite_concept_ids == []

    def test_passthrough_redacts_intl(self) -> None:
        """intl 패스스루는 redaction 키(ccss_statement_en) 제외."""
        intl = [
            {
                "node_id": "US:HSG-MG.A.1",
                "ccss_code": "HSG-MG.A.1",
                "ccss_statement_en": "LEAKED",
                "_redacted_fields": ["ccss_statement_en"],
            }
        ]
        result = transform_dataset(
            concept_records=[_CONCEPT_A],
            edge_records=[],
            intl_records=intl,
        )
        assert "ccss_statement_en" not in result.passthrough_intl[0]

    def test_flashcards_passthrough_preserved(self) -> None:
        cards = [{"src_id": "HK01", "front": "Q", "back": "A"}]
        result = transform_dataset(
            concept_records=[_CONCEPT_A],
            edge_records=[],
            flashcard_records=cards,
        )
        assert len(result.passthrough_flashcards) == 1


class TestTransformRealData:
    """실데이터 1회 전체 정형화 — 카운트·분류·redaction 단언."""

    def test_full_counts(
        self,
        concept_records: list[dict[str, object]],
        edge_records: list[dict[str, object]],
        flashcard_records: list[dict[str, object]],
        intl_records: list[dict[str, object]],
    ) -> None:
        result = transform_dataset(
            concept_records=concept_records,
            edge_records=edge_records,
            flashcard_records=flashcard_records,
            intl_records=intl_records,
        )
        assert len(result.concepts) == _FACTS["concept_graph.concepts"]
        assert len(result.edges) == _FACTS["concept_graph.edges"]
        assert result.skipped == []  # 실데이터는 전량 매핑

    def test_review_status_distribution_148_289(
        self, concept_records: list[dict[str, object]]
    ) -> None:
        """§4 분포: reviewed 148(수기 검수 114 + 기본수학 34 AI 검수)·pending 289."""
        concepts, _ = transform_concepts(concept_records, _real_id_map(concept_records))
        reviewed = sum(1 for c in concepts if c.review_status == ReviewStatus.REVIEWED.value)
        assert reviewed == 148
        assert len(concepts) - reviewed == 289

    def test_no_redaction_leak_in_full_dump(self, concept_records: list[dict[str, object]]) -> None:
        """전체 개념 dump에 description/formal_definition 키 0건."""
        concepts, _ = transform_concepts(concept_records, _real_id_map(concept_records))
        keys: set[str] = set()
        for c in concepts:
            keys.update(c.model_dump().keys())
        assert "description" not in keys
        assert "formal_definition" not in keys

    def test_all_concepts_have_standard_code(
        self, concept_records: list[dict[str, object]]
    ) -> None:
        """모든 개념은 성취기준 코드 1개+ 태그(CLAUDE.md ALWAYS)."""
        concepts, _ = transform_concepts(concept_records, _real_id_map(concept_records))
        assert all(len(c.standard_codes) >= 1 for c in concepts)


class TestDomainPurity:
    """domain 교육과정 접두 정화(P2e·Part 9 [C]) — 표시·필터 문자열의 커리큘럼 결합 제거."""

    def test_strip_domain_prefix_all_levels(self) -> None:
        """`[고]/[중]/[공통]/[기본]` 접두 제거·접두 없는 값은 그대로."""
        from data_pipeline.concept_graph.transform import _strip_domain_prefix

        assert _strip_domain_prefix("[고]미적분") == "미적분"
        assert _strip_domain_prefix("[중]수와 연산") == "수와 연산"
        assert _strip_domain_prefix("[공통]식·방정식·부등식") == "식·방정식·부등식"
        assert _strip_domain_prefix("[기본]다항식") == "다항식"  # idmap과 달리 [기본]도 벗김
        assert _strip_domain_prefix("자연수·자릿값") == "자연수·자릿값"  # 접두 없음

    def test_real_corpus_domains_have_no_curriculum_prefix(
        self, concept_records: list[dict[str, object]]
    ) -> None:
        """실데이터 전 개념의 domain에 교육과정 레벨 접두(`[…]`) 0건 — 정화 잠금."""
        concepts, _ = transform_concepts(concept_records, _real_id_map(concept_records))
        prefixed = [c.domain for c in concepts if c.domain.startswith("[")]
        assert prefixed == [], f"교육과정 접두 잔존 domain: {sorted(set(prefixed))}"


def _real_id_map(records: list[dict[str, object]]) -> dict[str, str]:
    from data_pipeline.concept_graph.idmap import build_id_map

    return build_id_map(records)
