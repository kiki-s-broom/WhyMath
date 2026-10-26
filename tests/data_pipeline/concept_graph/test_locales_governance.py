"""표시이름 locale 레이어 거버넌스 — locale⇄node 패리티·비공백·노드 순수성(name_* 슬롯 부재).

정본: docs/standards/part9_id_policy_review.md(P2d ②) + docs/data/concept_graph.md §2.4.

P2d ②로 표시이름(name_ko/en/ja)을 노드에서 분리해 locale 레이어(`locales/ko.json` 등·canonical_id
키)로 옮겼다. 이 테스트는 (a) locale(ko) 키가 graph 노드와 1:1(전량), (b) 모든 ko 표기가 비공백,
(c) Concept 모델에 name_* 슬롯이 없음(Concept Purity)을 강제한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from data_pipeline.concept_graph.models import Concept
from data_pipeline.concept_graph.transform import build_locales, transform_dataset
from data_pipeline.concept_graph.validate import validate_locales

_REPO_ROOT = Path(__file__).resolve().parents[3]
# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
# 고정 지점이 사실 파일 한 곳이다 — 값이 바뀌면 그 파일의 diff가 의식적 리뷰 지점이다.
_FACTS = json.loads(
    (_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
)


class TestNodePurity:
    def test_concept_has_no_name_fields(self) -> None:
        """Concept 모델에 표시이름 슬롯이 없다(name_ko/en/ja는 locale 레이어 소관)."""
        assert "name_ko" not in Concept.model_fields
        assert "name_en" not in Concept.model_fields
        assert "name_ja" not in Concept.model_fields


class TestLocaleParity:
    def test_locale_ko_matches_all_nodes(
        self,
        concept_records: list[dict[str, object]],
        edge_records: list[dict[str, object]],
    ) -> None:
        """locale(ko) 키 집합 == graph concept_id 집합(전량 1:1·고아 0)."""
        result = transform_dataset(concept_records=concept_records, edge_records=edge_records)
        report = validate_locales(result.locales, result.concepts)
        assert report.success is True, report.report_text()
        assert report.errors == []
        node_ids = {c.concept_id for c in result.concepts}
        assert set(result.locales["ko"]) == node_ids
        assert len(result.locales["ko"]) == _FACTS["concept_graph.concepts"]

    def test_every_ko_name_nonblank(self, concept_records: list[dict[str, object]]) -> None:
        """모든 ko 표시이름이 비공백(빈 표기 금지)."""
        result = transform_dataset(concept_records=concept_records, edge_records=[])
        assert all(v.strip() for v in result.locales["ko"].values())

    def test_en_ja_empty_phase1(self, concept_records: list[dict[str, object]]) -> None:
        """Phase 1 KR 전용 — en/ja locale은 빈 dict(후속 저작 시 채움)."""
        result = transform_dataset(concept_records=concept_records, edge_records=[])
        assert result.locales["en"] == {}
        assert result.locales["ja"] == {}

    def test_locale_keyed_by_canonical_id(self) -> None:
        """locale 키는 새 canonical concept_id다(src_id·옛 키 아님)."""
        records = [
            {
                "src_id": "HK01",
                "name_ko": "다항식의 사칙연산",
                "category": "[공통]식·방정식·부등식",
                "standard_codes": ["[10공수1-01-01]"],
            }
        ]
        result = transform_dataset(concept_records=records, edge_records=[])
        cid = result.concepts[0].concept_id
        assert cid.startswith("math.")
        assert result.locales["ko"] == {cid: "다항식의 사칙연산"}


class TestValidateLocalesErrors:
    def test_missing_node_locale_is_error(self, concept_records: list[dict[str, object]]) -> None:
        """노드에 있으나 locale(ko)에 표기가 없으면 locale_node_parity error."""
        result = transform_dataset(concept_records=concept_records, edge_records=[])
        broken = {"ko": dict(result.locales["ko"])}
        broken["ko"].pop(next(iter(broken["ko"])))  # 1건 제거
        report = validate_locales(broken, result.concepts)
        assert "locale_node_parity" in {i.rule for i in report.errors}
        assert report.success is False

    def test_blank_locale_value_is_error(self) -> None:
        """ko 표기가 공백이면 locale_nonblank error."""
        records = [
            {
                "src_id": "N1",
                "name_ko": "수 개념",
                "category": "자연수·자릿값",
                "standard_codes": ["[2수01-01]"],
            }
        ]
        result = transform_dataset(concept_records=records, edge_records=[])
        cid = result.concepts[0].concept_id
        report = validate_locales({"ko": {cid: "   "}}, result.concepts)
        assert "locale_nonblank" in {i.rule for i in report.errors}


class TestBuildLocales:
    def test_build_locales_skips_missing_name(self) -> None:
        """build_locales는 name_ko가 빈 레코드를 ko에서 제외한다(패리티는 validate가 잡음)."""
        id_map = {"A": "math.fraction.aa", "B": "math.fraction.bb"}
        records = [
            {"src_id": "A", "name_ko": "분수", "category": "분수"},
            {"src_id": "B", "name_ko": "", "category": "분수"},
        ]
        locales = build_locales(records, id_map)
        assert locales["ko"] == {"math.fraction.aa": "분수"}
        assert locales["en"] == {}
        assert locales["ja"] == {}
