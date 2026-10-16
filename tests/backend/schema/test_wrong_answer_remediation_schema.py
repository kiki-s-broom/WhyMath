"""오답 서명 규칙표·교정 전략표 데이터 계약(P3-06) — 형식 게이트가 실제로 거부하는가.

정상 입력이 통과하는 것은 보호의 증거가 아니다. 이 파일은 **계약이 막으려는 상태를 주입해 거부를
확인**한다: 간접 증거의 신뢰도 과대, 후보 인정선 미만 규칙, 형식이 틀린 M-id·개념 코드, 중복 id,
알 수 없는 필드, 빈 픽스처.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from whymath_backend.schema.wrong_answer_remediation import (
    RemediationRow,
    RemediationSpec,
    SignatureRule,
    SignatureSpec,
)


def _fixture(problem_id: str = "p-1", answer: str = "7") -> dict[str, str]:
    return {"problem_id": problem_id, "answer": answer, "note": "근거"}


def _rule(**override: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "rule_id": "sig.test",
        "mis_ids": ["M0001"],
        "ask": "derivative_at",
        "wrong_transform": "power_rule_step_omitted",
        "confidence": 0.9,
        "evidence": "direct",
        "note": "이유",
        "fixtures": {"wrong": [_fixture()], "not_wrong": [_fixture(answer="9")]},
    }
    base.update(override)
    return base


def _row(**override: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "mis_id": "M0001",
        "corrective_explanation": {
            "rule_statement": "규칙",
            "counterexample": "반례",
            "guiding_question": "되묻기",
        },
        "easier_problem": {"concept_code": "[12미적Ⅰ-02-03]", "max_difficulty": 2.0},
        "prerequisite_concept": {"concept_code": "[12미적Ⅰ-02-03]"},
        "authoring_status": "draft",
    }
    base.update(override)
    return base


class TestSignatureRule:
    def test_valid_rule_loads(self) -> None:
        assert SignatureRule.model_validate(_rule()).confidence == 0.9

    def test_indirect_evidence_cannot_claim_direct_level_confidence(self) -> None:
        """같은 값이 다른 원인으로도 나오는 증거를 0.9로 올리면 R3 하한(0.7 초과)을 쉽게 넘는다."""
        with pytest.raises(ValidationError, match="간접 증거"):
            SignatureRule.model_validate(_rule(evidence="indirect", confidence=0.9))
        # 경계: 정확히 상한(0.8)은 허용 — 경계 픽스처가 그 절을 실제로 밟는다.
        assert SignatureRule.model_validate(_rule(evidence="indirect", confidence=0.8))

    def test_confidence_below_gate_floor_is_rejected(self) -> None:
        """후보 인정선(0.65) 미만 규칙은 게이트가 항상 비우므로 데이터에 둘 이유가 없다."""
        with pytest.raises(ValidationError, match="후보 인정선"):
            SignatureRule.model_validate(_rule(confidence=0.5))
        assert SignatureRule.model_validate(_rule(confidence=0.65))

    @pytest.mark.parametrize("bad", ["M001", "m0001", "M00011", "0001", "M-0001", ""])
    def test_mis_id_format(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            SignatureRule.model_validate(_rule(mis_ids=[bad]))

    def test_duplicate_mis_ids_rejected(self) -> None:
        with pytest.raises(ValidationError, match="중복"):
            SignatureRule.model_validate(_rule(mis_ids=["M0001", "M0001"]))

    def test_rule_without_wrong_fixture_is_rejected(self) -> None:
        """오답 픽스처가 없는 규칙은 '잡는다'는 주장을 검증할 수 없다."""
        with pytest.raises(ValidationError):
            SignatureRule.model_validate(_rule(fixtures={"wrong": [], "not_wrong": []}))

    def test_unknown_field_is_rejected(self) -> None:
        """extra=forbid — 소비처 없는 필드(착시 필드)를 조용히 받지 않는다."""
        with pytest.raises(ValidationError):
            SignatureRule.model_validate(_rule(kebab_id="product-rule-naive"))

    def test_schema_never_names_a_kebab(self) -> None:
        """kebab을 데이터에 적을 자리가 없다 — 두 번째 매핑 표를 만들지 않는다(크로스워크가 소유)."""
        assert "kebab_id" not in SignatureRule.model_fields
        assert "kebab_id" not in RemediationRow.model_fields


class TestSignatureSpec:
    def test_duplicate_rule_id_rejected(self) -> None:
        doc = {
            "schema_version": "1.0.0",
            "spec_id": "wrong_answer_signatures_v1",
            "rules": [_rule(), _rule()],
        }
        with pytest.raises(ValidationError, match="rule_id가 중복"):
            SignatureSpec.model_validate(doc)

    def test_schema_version_is_required(self) -> None:
        """R6-03: 경계를 넘는 데이터 스키마에는 schema_version이 있다."""
        with pytest.raises(ValidationError):
            SignatureSpec.model_validate(
                {"spec_id": "wrong_answer_signatures_v1", "rules": [_rule()]}
            )

    def test_unknown_schema_version_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SignatureSpec.model_validate(
                {
                    "schema_version": "9.9.9",
                    "spec_id": "wrong_answer_signatures_v1",
                    "rules": [_rule()],
                }
            )


class TestRemediationRow:
    def test_valid_row_loads(self) -> None:
        assert RemediationRow.model_validate(_row()).authoring_status == "draft"

    def test_no_pedagogy_strategy_field(self) -> None:
        """교수전략의 소유자는 런타임 셀렉터다 — 이 표에 전략 필드가 생기면 진실 원천이 둘이 된다."""
        assert not any("strategy" in name for name in RemediationRow.model_fields)
        with pytest.raises(ValidationError):
            RemediationRow.model_validate(_row(pedagogy_strategy="SOCRATIC"))

    @pytest.mark.parametrize(
        "bad", ["12미적Ⅰ-02-03", "[12미적Ⅰ-02]", "[12미적Ⅰ-2-3]", "[미적Ⅰ-02-03]", ""]
    )
    def test_concept_code_format(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            RemediationRow.model_validate(
                _row(easier_problem={"concept_code": bad, "max_difficulty": 2.0})
            )

    @pytest.mark.parametrize("bad", [0, -1.0, 5.1])
    def test_max_difficulty_range(self, bad: float) -> None:
        with pytest.raises(ValidationError):
            RemediationRow.model_validate(
                _row(easier_problem={"concept_code": "[12미적Ⅰ-02-03]", "max_difficulty": bad})
            )

    def test_empty_explanation_text_rejected(self) -> None:
        """빈 문자열 교정 설명은 '있는 척'이다 — 정직하게 거부한다."""
        with pytest.raises(ValidationError):
            RemediationRow.model_validate(
                _row(
                    corrective_explanation={
                        "rule_statement": "",
                        "counterexample": "반례",
                        "guiding_question": "되묻기",
                    }
                )
            )

    def test_authoring_status_is_closed_vocabulary(self) -> None:
        with pytest.raises(ValidationError):
            RemediationRow.model_validate(_row(authoring_status="approved"))


class TestRemediationSpec:
    def test_duplicate_mis_id_rejected(self) -> None:
        doc = {
            "schema_version": "1.0.0",
            "spec_id": "misconception_remediation_v1",
            "rows": [_row(), _row()],
        }
        with pytest.raises(ValidationError, match="mis_id가 중복"):
            RemediationSpec.model_validate(doc)
