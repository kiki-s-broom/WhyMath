"""PED-05 교수전략 카탈로그 스키마 동결 + 불변식 — 필드셋·폐쇄 어휘·제거 필드 3종 부재 lock.

정본: `docs/architecture/04g_pedagogy_strategy_catalog.md` §3.2(필드 소비처 지정표)·§3.3(제거
필드 3종). `test_pedagogy_dsl_schema_freeze.py`(필드셋 리터럴 동결) 선례 동형 — 필드 추가/개명/
삭제 시 이 테스트가 깨져 "소비처 실재 증명" 검토를 강제한다. 특히 §3.3의 **부재의 동결**이
핵심이다: 외부 프레임워크의 3계열(AI 추천점수·기계 판정용 금지조건·선행/후속·페이딩)이 미래
세션에서 재제안되어 스키마에 스며드는 것을 기계로 막는다(04g §8 영구 기록과 이중 방어).

거부(음성) 케이스는 인라인 dict 픽스처(`test_pack_loader.py` `_pack_dict` 선례)로 검증한다 —
hermetic·실 코퍼스 무관. 실 코퍼스 로드 스모크는 registry 테스트
(`tests/backend/l4/pedagogy/test_strategy_registry.py`) 소관.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from whymath_backend.schema.pedagogy_strategy import (
    DIFFICULTY_VOCAB,
    ERROR_TYPE_VOCAB,
    GRADE_BAND_VOCAB,
    PedagogyStrategyCard,
)

# ── 동결 리터럴 (PED-05 시점 — 변경은 "소비처 실재 증명" 전제·04g §3.2) ──
_CARD_FIELDS = {
    "strategy",
    "name_ko",
    "description",
    "research_basis",
    "target_grade_bands",
    "difficulty_range",
    "target_k_types",
    "suitable_error_types",
    "usage_notes",
}

# 제거 필드 3계열(04g §3.3) — model_fields 어느 이름에도 이 어간이 나타나면 안 된다.
# ①정적 추천점수(ai_score/recommendation_score → PED-03 posterior가 유일 좌석)
# ②기계 판정용 금지조건(forbidden_conditions → 팩 forbidden_modes+gate() 2축이 정본)
# ③선행/후속·페이딩(predecessor/successor/fading → 팩 fading_schedule이 정본)
_REMOVED_FIELD_STEMS = (
    "ai_score",
    "recommendation_score",
    "forbidden_conditions",
    "predecessor",
    "successor",
    "fading",
)


# ──────────────────────────────────────────────────────────────────────────
# raw 카드 dict 픽스처 (인라인 합성 — 유효 카드 1건·오버라이드 가능)
# ──────────────────────────────────────────────────────────────────────────
def _card_dict(**overrides: Any) -> dict[str, Any]:
    """유효 raw 카드 dict — schema.PedagogyStrategyCard가 검증하는 형태."""
    base: dict[str, Any] = {
        "strategy": "ANALOGY",
        "name_ko": "비유",
        "description": "친숙한 상황의 관계 구조에 빗대어 새 개념의 직관을 만든다.",
        "research_basis": ["Gentner (1983) 구조 매핑 이론(structure-mapping theory)"],
        "target_grade_bands": ["중학", "고등"],
        "difficulty_range": ["중", "하"],
        "target_k_types": ["CONCEPT"],
        "suitable_error_types": ["개념혼동", "직관오류"],
        "usage_notes": "개념 직관의 발판을 만든다. 비유는 정의를 대신하지 않는다.",
    }
    base.update(overrides)
    return base


class TestSchemaFieldFreeze:
    """필드셋 리터럴 동결 + 제거 필드 3계열 부재 동결(04g §3.3)."""

    def test_card_fields_frozen(self) -> None:
        assert set(PedagogyStrategyCard.model_fields) == _CARD_FIELDS

    def test_removed_field_stems_absent(self) -> None:
        # 부재의 동결 — 제거 3계열 어간이 어떤 필드명에도 나타나지 않는다(04g §3.3).
        for stem in _REMOVED_FIELD_STEMS:
            offenders = [name for name in PedagogyStrategyCard.model_fields if stem in name]
            assert offenders == [], f"제거 필드 계열 '{stem}' 재유입: {offenders}"

    @pytest.mark.parametrize(
        "forbidden_key,value",
        [
            ("ai_score", 0.9),
            ("recommendation_score", 0.5),
            ("forbidden_conditions", ["막힘 상태"]),
            ("predecessor", "DIRECT"),
            ("successor", "RETRIEVAL"),
            ("fading_schedule", {"worked": 2}),
        ],
    )
    def test_removed_field_rejected_at_runtime(self, forbidden_key: str, value: Any) -> None:
        # extra="forbid" — YAML에 제거 필드 키가 저작돼 들어와도 검증에서 거부된다(런타임 방어).
        with pytest.raises(ValidationError):
            PedagogyStrategyCard.model_validate(_card_dict(**{forbidden_key: value}))


class TestClosedVocabFreeze:
    """폐쇄 어휘 3종 리터럴 동결 — 확장은 상수+이 리터럴 동시 갱신 전제."""

    def test_grade_band_vocab(self) -> None:
        assert GRADE_BAND_VOCAB == frozenset({"초등", "중학", "고등", "대학"})

    def test_difficulty_vocab(self) -> None:
        assert DIFFICULTY_VOCAB == frozenset({"상", "중", "하"})

    def test_error_type_vocab(self) -> None:
        # 오개념 코퍼스 error_type 6종 정본(misconception_catalog_v1.md) —
        # "정의·표기오류"는 가운뎃점 포함 1개 유형이다.
        assert ERROR_TYPE_VOCAB == frozenset(
            {"개념혼동", "절차오류", "정의·표기오류", "과잉일반화", "직관오류", "역방향오류"}
        )


class TestValidCard:
    """양성 케이스 — 유효 카드 통과 + use_enum_values 문자열화."""

    def test_valid_card_passes(self) -> None:
        card = PedagogyStrategyCard.model_validate(_card_dict())
        # use_enum_values=True — 검증 후 enum이 문자열 값으로 접힌다(registry dict 키 정합).
        assert card.strategy == "ANALOGY"
        assert card.target_k_types == ["CONCEPT"]

    def test_empty_suitable_error_types_allowed(self) -> None:
        # R2 정밀화 미참여 신호(정직한 공백) — 빈 리스트는 유효하다.
        card = PedagogyStrategyCard.model_validate(_card_dict(suitable_error_types=[]))
        assert card.suitable_error_types == []


class TestClosedVocabRejection:
    """불변식 (a) — 폐쇄 어휘 밖 값 거부(오탈자·미정의 값 차단)."""

    def test_unknown_grade_band_rejected(self) -> None:
        with pytest.raises(ValidationError, match="target_grade_bands"):
            PedagogyStrategyCard.model_validate(_card_dict(target_grade_bands=["유아", "중학"]))

    def test_unknown_difficulty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="difficulty_range"):
            PedagogyStrategyCard.model_validate(_card_dict(difficulty_range=["최상"]))

    def test_unknown_error_type_rejected(self) -> None:
        # "계산실수"는 error_type 6종 정본 어휘가 아니다(절차오류로 표현해야 함).
        with pytest.raises(ValidationError, match="suitable_error_types"):
            PedagogyStrategyCard.model_validate(_card_dict(suitable_error_types=["계산실수"]))

    def test_unknown_k_type_rejected(self) -> None:
        # k_type 어휘는 KnowledgeType enum이 직접 강제한다(폐쇄 7종).
        with pytest.raises(ValidationError):
            PedagogyStrategyCard.model_validate(_card_dict(target_k_types=["NOT_A_KTYPE"]))

    def test_unknown_strategy_rejected(self) -> None:
        # GAME은 enum에 없다(반게임화 정체성) — 카탈로그로도 못 들어온다.
        with pytest.raises(ValidationError):
            PedagogyStrategyCard.model_validate(_card_dict(strategy="GAME"))


class TestRequiredContentRejection:
    """불변식 (b)·(c)·(d) — 빈 근거·빈 서술·빈 필터 축 거부."""

    def test_empty_research_basis_rejected(self) -> None:
        with pytest.raises(ValidationError, match="research_basis"):
            PedagogyStrategyCard.model_validate(_card_dict(research_basis=[]))

    def test_blank_research_basis_item_rejected(self) -> None:
        # str_strip_whitespace 이후 빈 항목 — 공백-만 인용도 거부된다.
        with pytest.raises(ValidationError, match="research_basis"):
            PedagogyStrategyCard.model_validate(_card_dict(research_basis=["   "]))

    @pytest.mark.parametrize("field", ["name_ko", "description", "usage_notes"])
    def test_blank_text_field_rejected(self, field: str) -> None:
        with pytest.raises(ValidationError, match=field):
            PedagogyStrategyCard.model_validate(_card_dict(**{field: "  "}))

    @pytest.mark.parametrize("field", ["target_grade_bands", "difficulty_range", "target_k_types"])
    def test_empty_filter_axis_rejected(self, field: str) -> None:
        # select() 후보 필터 축이 비면 그 전략이 후보에서 영구 제외된다 — 저작 실수로 거부.
        with pytest.raises(ValidationError, match=field):
            PedagogyStrategyCard.model_validate(_card_dict(**{field: []}))


class TestDuplicateRejection:
    """불변식 (e) — 리스트 중복 항목 거부(어휘 위생)."""

    def test_duplicate_grade_band_rejected(self) -> None:
        with pytest.raises(ValidationError, match="중복"):
            PedagogyStrategyCard.model_validate(_card_dict(target_grade_bands=["중학", "중학"]))

    def test_duplicate_error_type_rejected(self) -> None:
        with pytest.raises(ValidationError, match="중복"):
            PedagogyStrategyCard.model_validate(
                _card_dict(suitable_error_types=["개념혼동", "개념혼동"])
            )
