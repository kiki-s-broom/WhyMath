"""provenance 관문 변별력 — 생성물 무-provenance 기록이 실제로 거부되는가 (LIC-03 acceptance ②).

**왜 정상 통과만으로는 부족한가**(CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로 선언
금지"): 정상 입력에서 초록인 것은 보호의 증거가 아니다 — *모든* 입력에서 초록인 관문도 같은
화면을 낸다. 그래서 이 파일은 **거부 방향 픽스처를 축마다** 두고, 그 축의 절을 지우면
살아남지 않도록 짝을 맞춘다(절마다 그 절의 반례 — "픽스처가 그 절을 실제로 밟는가").

거부 축 7종과 그것을 지키는 절:
  ① 재료 부재(`provenance is None`)        ← `if provenance is None`
  ② generation_type 빈값                    ← `if not provenance.generation_type`
  ③ license 빈값                            ← `if not provenance.license`
  ④ 미지 enum 값                            ← `GenerationType(...)`/`LicenseType(...)` 승격
  ⑤ ORIGINAL 차단                           ← schema 불변식 (A)
  ⑥ EBS_LICENSED 차단                       ← schema 불변식 (B)
  ⑦ 메타 전용 출처 + 비-WHYMATH license      ← schema 불변식 (C-1)

**성공 방향 대조군**(`test_real_corpus_shape_passes`)이 함께 있어야 "전부 거부"라는 과잉
수정이 통과하지 않는다 — 코퍼스 실분포(FULLY_GENERATED / WHYMATH_GENERATED / 출처 없음)를
그대로 쓴다.
"""

from __future__ import annotations

import uuid

import pytest

from whymath_backend.l1.problem_bank.provenance_gate import (
    GENERATED_SOURCE_VALUE,
    ProvenanceInput,
    ProvenanceMissingError,
    is_generated_content,
    require_provenance,
)
from whymath_backend.schema.enums import SourceType

# 코퍼스 실분포(2026-09-21 실측: 14,034건 전부 이 조합) — 성공 방향 대조군의 근거.
_CORPUS_SHAPE = ProvenanceInput(generation_type="FULLY_GENERATED", license="WHYMATH_GENERATED")


def test_real_corpus_shape_passes() -> None:
    """대조군 — 실 코퍼스 분포는 통과한다(과잉 수정 방지: '전부 거부'는 보호가 아니다)."""
    problem_id = uuid.uuid4()
    result = require_provenance(
        slug="corpus-shape",
        source_type_value=SourceType.자체생성,
        provenance=_CORPUS_SHAPE,
        problem_id=problem_id,
    )
    assert result is not None, "코퍼스 실분포가 거부되면 적재가 전면 중단된다"
    assert result.problem_id == problem_id
    assert result.generation_type == "FULLY_GENERATED"
    assert result.license == "WHYMATH_GENERATED"


def test_non_generated_source_is_not_in_scope() -> None:
    """메타 전용 출처는 원장 대상이 아니다 — None을 돌려주되 예외를 던지지 않는다.

    이 축이 없으면 관문이 평가원·EBS 문항 적재까지 막아 저작권 레일과 충돌한다
    (그쪽은 `schema.Problem`이 본문 보유를 이미 막는다).
    """
    assert (
        require_provenance(slug="meta-only", source_type_value=SourceType.평가원, provenance=None)
        is None
    )


def test_source_type_accepts_enum_and_string() -> None:
    """`use_enum_values=True` 환경이라 enum/문자열이 둘 다 들어온다 — 양쪽 다 생성물 판정."""
    assert is_generated_content(SourceType.자체생성) is True
    assert is_generated_content(GENERATED_SOURCE_VALUE) is True
    assert is_generated_content("평가원") is False
    assert is_generated_content(None) is False


@pytest.mark.parametrize(
    ("axis", "provenance", "expected_fragment"),
    [
        ("① 재료 부재", None, "출처 원장 재료가 없다"),
        # ②·③은 **절별 반례**다. 기대 문면을 함께 단언하지 않으면 그 절을 지워도 enum 승격
        # (`GenerationType("")`)이 대신 ValueError를 내서 테스트가 통과한다 — 뮤테이션 M2·M3
        # 생존으로 실측된 구멍이며, 픽스처가 그 절을 *밟지 않은* 것이 원인이었다
        # (CLAUDE.md "픽스처가 그 절을 실제로 밟는가").
        (
            "② generation_type 빈값",
            ProvenanceInput("", "WHYMATH_GENERATED"),
            "generation_type이 비어 있다",
        ),
        (
            "② generation_type None",
            ProvenanceInput(None, "WHYMATH_GENERATED"),
            "generation_type이 비어 있다",
        ),
        ("③ license 빈값", ProvenanceInput("FULLY_GENERATED", ""), "license가 비어 있다"),
        ("③ license None", ProvenanceInput("FULLY_GENERATED", None), "license가 비어 있다"),
        (
            "④ 미지 generation_type",
            ProvenanceInput("MADE_UP", "WHYMATH_GENERATED"),
            "provenance 무효",
        ),
        ("④ 미지 license", ProvenanceInput("FULLY_GENERATED", "MADE_UP"), "provenance 무효"),
        (
            "④ 미지 original_source",
            ProvenanceInput("FULLY_GENERATED", "WHYMATH_GENERATED", "어디선가"),
            "provenance 무효",
        ),
        ("⑤ ORIGINAL 차단", ProvenanceInput("ORIGINAL", "WHYMATH_GENERATED"), "provenance 무효"),
        (
            "⑥ EBS_LICENSED 차단",
            ProvenanceInput("FULLY_GENERATED", "EBS_LICENSED"),
            "provenance 무효",
        ),
        (
            "⑦ 메타 출처 + 비-WHYMATH",
            ProvenanceInput("FULLY_GENERATED", "CC_BY", "평가원"),
            "provenance 무효",
        ),
    ],
)
def test_generated_content_without_valid_provenance_is_rejected(
    axis: str, provenance: ProvenanceInput | None, expected_fragment: str
) -> None:
    """생성물인데 원장 재료가 없거나 무효면 거부 — 축마다 반례 1건 + 기대 문면."""
    with pytest.raises(ProvenanceMissingError) as excinfo:
        require_provenance(
            slug=f"reject-{axis}", source_type_value=GENERATED_SOURCE_VALUE, provenance=provenance
        )
    message = str(excinfo.value)
    assert f"reject-{axis}" in message, (
        "거부 메시지가 어느 문항인지 지목하지 않는다 — 침묵 실패 금지(CLAUDE.md). "
        f"실제 메시지: {message}"
    )
    assert expected_fragment in message, (
        f"{axis} 를 막은 절이 의도한 절이 아니다 — 기대 문면 {expected_fragment!r} 부재. "
        f"실제 메시지: {message}"
    )


def test_metadata_only_source_with_whymath_license_passes() -> None:
    """⑦의 대조군 — 메타 전용 출처라도 WHYMATH_GENERATED 변형이면 합법이다.

    이 대조군이 없으면 ⑦ 절을 "메타 전용 출처면 무조건 거부"로 과잉 수정해도 통과한다 —
    그러면 평가원 기출 기반 *동등문제*(우리 주력 생산 형태)가 통째로 막힌다.
    """
    result = require_provenance(
        slug="variant-of-kice",
        source_type_value=GENERATED_SOURCE_VALUE,
        provenance=ProvenanceInput("VARIANT_NUMBER", "WHYMATH_GENERATED", "평가원"),
    )
    assert result is not None
    assert result.original_source == "평가원"
