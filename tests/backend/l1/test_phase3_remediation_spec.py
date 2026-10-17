"""Phase 3 교정 전략 데이터 로더(`l1/standards/phase3_remediation_spec.py`, P3-06) 테스트.

구조 검증만 한다 — 문항·오개념 실재와 체인 산출은 `tests/backend/ops/test_phase3_remediation.py` 몫이다.
스키마 위반을 하나씩 **실제로 주입**해 거부되는지 본다(정상 파일이 읽히는 것은 증거가 아니다).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from whymath_backend.l1.standards import phase3_remediation_spec as prs

_DATA = prs.default_spec_path().parent


@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    loaded = yaml.safe_load((_DATA / "remediation.yaml").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _mutated(doc: dict[str, Any], edit: Any) -> dict[str, Any]:
    out = copy.deepcopy(doc)
    edit(out)
    assert out != doc, "주입이 적용되지 않았다"
    return out


class TestRealData:
    def test_loads_and_matches_provenance_counts(self) -> None:
        spec = prs.load_remediation_spec()
        prov = json.loads((_DATA / "_provenance.json").read_text(encoding="utf-8"))["counts"]
        assert len(spec.signatures) == prov["signatures"]
        assert sum(len(s.wrong) for s in spec.signatures) == prov["wrong_fixtures"]
        assert sum(len(s.correct) for s in spec.signatures) == prov["correct_fixtures"]

    def test_every_signature_has_both_polarities(self) -> None:
        for s in prs.load_remediation_spec().signatures:
            assert s.wrong and s.correct, s.kebab_id

    def test_refers_to_the_frozen_scope_not_a_copy_of_it(self, doc: dict[str, Any]) -> None:
        """핵심 오개념 목록·kebab↔M-id 를 복제하지 않는다(두 번째 진실 원천 금지) — 키 구조로 판정한다."""
        assert "core_misconceptions" not in doc and "crosslinks" not in doc
        for sig in doc["signatures"]:
            assert set(sig) == {"kebab_id", "channel", "fixtures"}, sig.keys()


class TestRejections:
    def test_empty_signatures_are_not_a_pass(self, doc: dict[str, Any]) -> None:
        with pytest.raises(prs.RemediationSpecError, match="signatures"):
            prs.parse_remediation_spec(_mutated(doc, lambda d: d.__setitem__("signatures", [])))

    def test_unknown_channel_is_rejected(self, doc: dict[str, Any]) -> None:
        """단답형 등 미지원 채널을 조용히 통과시키지 않는다."""
        with pytest.raises(prs.RemediationSpecError, match="지원하지 않는 채널"):
            prs.parse_remediation_spec(
                _mutated(doc, lambda d: d["signatures"][0].__setitem__("channel", "short_answer"))
            )

    def test_empty_fixture_list_is_rejected(self, doc: dict[str, Any]) -> None:
        with pytest.raises(prs.RemediationSpecError, match="0건은 통과가 아니다"):
            prs.parse_remediation_spec(
                _mutated(doc, lambda d: d["signatures"][0]["fixtures"].__setitem__("correct", []))
            )

    def test_bool_choice_index_is_rejected(self, doc: dict[str, Any]) -> None:
        with pytest.raises(prs.RemediationSpecError, match="choice_index"):
            prs.parse_remediation_spec(
                _mutated(
                    doc,
                    lambda d: d["signatures"][0]["fixtures"]["wrong"][0].__setitem__(
                        "choice_index", True
                    ),
                )
            )

    def test_negative_choice_index_is_rejected(self, doc: dict[str, Any]) -> None:
        with pytest.raises(prs.RemediationSpecError, match="choice_index"):
            prs.parse_remediation_spec(
                _mutated(
                    doc,
                    lambda d: d["signatures"][0]["fixtures"]["wrong"][0].__setitem__(
                        "choice_index", -1
                    ),
                )
            )

    def test_duplicate_kebab_is_rejected(self, doc: dict[str, Any]) -> None:
        with pytest.raises(prs.RemediationSpecError, match="kebab_id 중복"):
            prs.parse_remediation_spec(
                _mutated(doc, lambda d: d["signatures"].append(copy.deepcopy(d["signatures"][0])))
            )

    def test_duplicate_fixture_is_rejected(self, doc: dict[str, Any]) -> None:
        with pytest.raises(prs.RemediationSpecError, match="중복"):
            prs.parse_remediation_spec(
                _mutated(
                    doc,
                    lambda d: d["signatures"][0]["fixtures"]["wrong"].append(
                        copy.deepcopy(d["signatures"][0]["fixtures"]["wrong"][0])
                    ),
                )
            )

    def test_wrong_and_correct_pointing_at_the_same_choice_is_rejected(
        self, doc: dict[str, Any]
    ) -> None:
        def clash(d: dict[str, Any]) -> None:
            fx = d["signatures"][0]["fixtures"]
            fx["correct"].append(copy.deepcopy(fx["wrong"][0]))

        with pytest.raises(prs.RemediationSpecError, match="같은 보기"):
            prs.parse_remediation_spec(_mutated(doc, clash))

    def test_unsupported_version_is_rejected(self, doc: dict[str, Any]) -> None:
        with pytest.raises(prs.RemediationSpecError, match="spec_version"):
            prs.parse_remediation_spec(_mutated(doc, lambda d: d.__setitem__("spec_version", 2)))

    def test_missing_decision_record_is_rejected(self, doc: dict[str, Any]) -> None:
        """좌석 없는 오개념의 처분 게이트를 적지 않은 데이터는 거부한다(막힘의 근거가 사라진다)."""
        with pytest.raises(prs.RemediationSpecError, match="unseated_decision"):
            prs.parse_remediation_spec(_mutated(doc, lambda d: d.pop("unseated_decision")))

    def test_unreadable_file_is_an_error_not_an_empty_spec(self, tmp_path: Path) -> None:
        with pytest.raises(prs.RemediationSpecError, match="읽지 못했다"):
            prs.load_remediation_spec(tmp_path / "없는파일.yaml")

    def test_broken_yaml_is_an_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("signatures: [", encoding="utf-8")
        with pytest.raises(prs.RemediationSpecError, match="파싱 실패"):
            prs.load_remediation_spec(bad)
