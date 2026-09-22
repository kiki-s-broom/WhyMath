"""AI 생성물 문항의 provenance 동반 강제 — **집행 지점 단일 관문**(LIC-03).

**무엇을 막는가**: `source_type=자체생성`(= 본문을 우리가 보유하는 생성물 — 이 저장소에서
계획서 문언 `origin='ai_*'`에 대응하는 유일한 실재 표지)인 문항이 `content_provenance`
행 없이 `problem` 테이블에 들어가는 것.

**왜 DB CHECK가 아닌가**(판정 정본 = `docs/standards/provenance_enforcement_layer_decision.md`):
스키마 정본(`schemas/v1.0/schema_v1.0.md` §10.1)의 링크는 `content_provenance.problem_id →
problem` **역방향 nullable FK**다. 따라서 ①`problem` 한 행만 보는 CHECK는 타 테이블의 행
존재를 볼 수 없고 ②FK 방향상 provenance 행은 problem이 *생긴 뒤에야* 삽입 가능하므로
"INSERT 시점 거부"가 시간적으로도 성립하지 않는다. 표현 가능한 DB 대안(역방향 NOT NULL
FK 신설·DEFERRABLE 제약 트리거)의 비용·배제 근거는 판정 문서 §3에 실측으로 적었다.

**이 모듈의 계약**:
  - `require_provenance()`는 생성물이면 *검증된* `schema.ContentProvenance`를 돌려주고,
    provenance가 없거나 법적 불변식을 못 지나면 `ProvenanceMissingError`로 **거부**한다.
  - 생성물이 아닌 출처(평가원·EBS·교과서 등 메타 전용)는 `None`을 돌려준다 — 이 축은
    `schema.Problem`이 이미 본문 보유를 막고 있어 provenance 원장의 대상이 아니다.
  - 법적 불변식(ORIGINAL 차단·EBS_LICENSED 차단·메타 전용 출처 3규칙)은 여기서 재구현하지
    않는다. `schema.ContentProvenance`의 `@model_validator`가 정본이고, 이 관문은 그것을
    *반드시 경유하게* 만드는 역할만 한다(침묵 실패 금지 — 예외를 삼키지 않고 사유를 싣는다).

**집행 확인**: 이 관문 밖에서 `problem` 행을 쓰는 코드가 생기면
`tests/backend/db/test_problem_write_provenance_single_gate.py`가 AST 전수 스캔으로 RED를
낸다(EOS-103 `test_learner_state_single_writer.py` 선례 — 문자열 금지 목록이 아니라
구성된 결과를 본다).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from whymath_backend.schema.enums import GenerationType, LicenseType, SourceType
from whymath_backend.schema.provenance import ContentProvenance

# "AI 생성물"의 조작적 정의 — 본문을 우리가 보유하는 유일한 출처값. `problem` 테이블에는
# 생성원(모델·프롬프트) 컬럼이 없고 `source_type` 하나만 NOT NULL이므로, DB가 아는 범위에서
# 생성물을 가리키는 표지는 이 값뿐이다(판정 문서 §2 실측).
GENERATED_SOURCE_VALUE: str = SourceType.자체생성.value


class ProvenanceMissingError(ValueError):
    """생성물 문항인데 provenance 원장 재료가 없거나 무효 — 적재 거부(fail-closed)."""


@dataclass(frozen=True, slots=True)
class ProvenanceInput:
    """관문 입력 — 저작 계층이 보유한 provenance 3축(원장 컬럼과 1:1).

    `l1/problem_bank/populate.ProblemProvenanceMeta`와 같은 모양이지만 *계층이 다르다*:
    그쪽은 코퍼스 파싱 산출물이고 이쪽은 관문의 입력 계약이다. 둘을 한 타입으로 합치면
    관문이 코퍼스 포맷에 묶여 REST 등 다른 쓰기 경로가 이 관문을 못 쓴다.
    """

    generation_type: str | None
    license: str | None
    original_source: str | None = None


def is_generated_content(source_type_value: object) -> bool:
    """이 출처값이 *생성물*인가 — enum/문자열 양쪽 정규화(use_enum_values=True 환경)."""
    value = (
        source_type_value.value if isinstance(source_type_value, SourceType) else source_type_value
    )
    return value == GENERATED_SOURCE_VALUE


def require_provenance(
    *,
    slug: str,
    source_type_value: object,
    provenance: ProvenanceInput | None,
    problem_id: uuid.UUID | None = None,
) -> ContentProvenance | None:
    """생성물이면 검증된 provenance를 돌려주고, 없거나 무효면 거부한다.

    Args:
        slug: 거부 메시지의 지목 대상(어느 문항이 막혔는지 — 침묵 실패 금지).
        source_type_value: `problem.source_type`(enum 또는 문자열).
        provenance: 저작 계층이 보유한 원장 재료. 생성물인데 `None`이면 거부.
        problem_id: 이미 확보된 문항 식별자(upsert RETURNING 등). 미확보 단계(파싱 시점)면
            `None`으로 두고 판정만 받는다 — 원장 행 조립은 식별자 확보 후 다시 부른다.

    Returns:
        생성물이면 검증 통과한 `ContentProvenance`, 생성물이 아니면 `None`.

    Raises:
        ProvenanceMissingError: 생성물인데 재료 부재·필수 축 결손·법적 불변식 위반.
    """
    if not is_generated_content(source_type_value):
        return None

    if provenance is None:
        raise ProvenanceMissingError(
            f"provenance 부재: slug={slug} 는 source_type={GENERATED_SOURCE_VALUE!r}"
            "(생성물)인데 출처 원장 재료가 없다 — 생성물은 content_provenance 행을 반드시 "
            "동반한다(A4 DoD·판정 문서 §4). 저작 계층에서 generation_type/license를 실어라."
        )

    # 필수 축 — 원장의 존재 이유가 "무엇이 이 본문을 만들었는가"이므로 둘 중 하나라도 비면
    # 행을 만들어도 추적 불가다. 빈 문자열을 통과시키면 무-provenance가 원장에 *있는 것처럼*
    # 위장된다(현행 코퍼스 파서가 generation_type 부재를 ""로 접던 구멍 — 판정 문서 §4-①).
    if not provenance.generation_type:
        raise ProvenanceMissingError(
            f"provenance 결손: slug={slug} 의 generation_type이 비어 있다 — 무엇이 이 본문을 "
            "만들었는지(VARIANT_*/COMPOSED/FULLY_GENERATED)가 원장의 필수 축이다."
        )
    if not provenance.license:
        raise ProvenanceMissingError(
            f"provenance 결손: slug={slug} 의 license가 비어 있다 — 지배 라이선스 없이는 "
            "노출·재사용 판정을 할 수 없다(저작권 레일)."
        )

    try:
        # enum 승격 — 저작 계층은 문자열을 싣는다(JSONL·REST 양쪽). 미지 값은 여기서
        # ValueError가 되어 아래 except로 합류한다: "아는 값 중 하나"가 아니면 원장에
        # 들어가선 안 되고, 조용히 문자열로 남기면 나중에 아무도 집계할 수 없다.
        return ContentProvenance(
            problem_id=problem_id,
            original_source=(
                SourceType(provenance.original_source)
                if provenance.original_source is not None
                else None
            ),
            generation_type=GenerationType(provenance.generation_type),
            license=LicenseType(provenance.license),
        )
    except ValueError as exc:  # 법적 불변식(A·B·C-1~3) 위반 또는 미지 enum 값.
        raise ProvenanceMissingError(
            f"provenance 무효: slug={slug} — {type(exc).__name__}: {exc}"
        ) from exc


__all__ = [
    "GENERATED_SOURCE_VALUE",
    "ContentProvenance",
    "ProvenanceInput",
    "ProvenanceMissingError",
    "is_generated_content",
    "require_provenance",
]
