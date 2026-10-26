"""EvaluationContext 기록 계약 동결 (EOS-47).

이 계약의 핵심 약속은 하나다 — **출처가 없는 키는 값을 지어내지 않는다.** 그 약속이 코드 한 줄(표 항목)
로 쉽게 깨지므로, 표(`EVALUATION_CONTEXT_SOURCES`)와 모델 필드와 직렬화 결과가 서로 어긋나지 않음을
여기서 동결한다. 헬퍼가 실제로 채우는 키와 표의 일치는 `tests/backend/l2/test_attempt_version_pin.py`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from whymath_backend.schema.evaluation_context import (
    EVALUATION_CONTEXT_SCHEMA_VERSION,
    EVALUATION_CONTEXT_SOURCES,
    EvaluationContext,
)

_VALUE_KEYS = frozenset(EvaluationContext.model_fields) - {"schema_version"}


def test_sources_table_covers_exactly_the_value_fields() -> None:
    """표의 키 집합 = 모델의 값 필드 집합 — 필드를 추가하고 출처 표를 빼먹을 수 없다."""
    assert set(EVALUATION_CONTEXT_SOURCES) == _VALUE_KEYS


def test_scan_is_not_vacuous() -> None:
    """공허 통과 방지 — 표가 비었거나 값 필드가 0개면 위 동치 단언이 의미 없이 초록이 된다."""
    assert len(_VALUE_KEYS) >= 5
    assert any(src for src in EVALUATION_CONTEXT_SOURCES.values()), "출처가 있는 키가 하나도 없다"
    assert any(
        src is None for src in EVALUATION_CONTEXT_SOURCES.values()
    ), "출처 없는 키가 하나도 없다 — 이 테스트의 '모름' 분기가 검증 대상을 잃었다"


def test_every_value_field_defaults_to_none_not_to_a_made_up_constant() -> None:
    """기본값은 전부 None(모름) — 출처가 없는 키에 '1.0' 같은 임의 상수를 박지 않는다."""
    ctx = EvaluationContext()
    for key in _VALUE_KEYS:
        assert getattr(ctx, key) is None, key
    assert ctx.schema_version == EVALUATION_CONTEXT_SCHEMA_VERSION


def test_unknown_key_is_rejected() -> None:
    """extra=forbid — 오타·미등록 키가 조용히 JSONB에 섞이지 않는다."""
    with pytest.raises(ValidationError):
        EvaluationContext.model_validate({"curriculum_versoin": "2022_REVISION"})


def test_json_dump_is_a_plain_dict_with_every_key_present() -> None:
    """JSONB에 들어갈 직렬화는 평범한 dict이고 모든 키가 존재한다(None도 키로 남는다).

    키가 빠지면 '모름(None)'과 '이 판 이전 행이라 키 자체가 없음'이 구별되지 않는다.
    """
    dumped = EvaluationContext(curriculum_version="2022_REVISION").model_dump(mode="json")
    assert set(dumped) == _VALUE_KEYS | {"schema_version"}
    assert dumped["curriculum_version"] == "2022_REVISION"
    assert dumped["grading_policy_version"] is None


def test_dump_roundtrips_through_validation() -> None:
    """저장된 JSON을 다시 읽어도 같은 값 — 읽기 경로(to_schema·export)가 깨지지 않는다."""
    original = EvaluationContext(curriculum_version="2015_REVISION")
    assert EvaluationContext.model_validate(original.model_dump(mode="json")) == original
