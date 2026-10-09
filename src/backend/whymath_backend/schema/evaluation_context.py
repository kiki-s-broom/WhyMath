"""EvaluationContext Pydantic 계약 — 채점 시점의 교육 환경 스냅숏 (EOS-47).

설계 정본: `docs/architecture/44_eos_version_management.md` §10.2(Runtime VersionContext)·§11(AI
재현성)·§14-3. 이 모델은 `problem_attempt.evaluation_context`(JSONB)에 **한 시도(attempt)가 채점된
순간의 환경**을 적는 기록 계약이다. 목적은 하나 — "그때 그 채점이 어떤 환경에서 나왔는가"를 나중에
재현·이의 검토할 수 있게 하는 것(`docs/architecture/28_mathlive_input.md` §35 "채점 이의 재현").

**VersionContext 전체가 아니다.** 44 §10.2의 VersionContext는 Release Snapshot(§13 Phase 2)을 전제로
수십 개 Version ID를 한 참조로 묶는다. 그 Release 체계는 아직 없다(`version_header.py` 범위 축소
문단). 그래서 이 계약은 "지금 런타임이 실제로 알 수 있는 값"만 담는 **축소판**이고, 키는 나중에
VersionContext 참조로 승격될 때 그 구성원과 이름이 대응하도록 정했다.

────────────────────────────────────────────────────────────────────────────
핵심 규율 — 출처가 없는 키는 채우지 않는다 (날조 금지)
────────────────────────────────────────────────────────────────────────────
키 5개 중 **지금 런타임에 실제 출처가 있는 것은 하나뿐**이다(`EVALUATION_CONTEXT_SOURCES`가 키마다
출처 또는 `None`을 적는다 — 이 표가 정본이고 `l2/attempt_version_pin.py`와 테스트가 대조한다).
나머지 4개는 코드베이스에 **그 값을 만드는 곳이 아직 없다**(2026-10-09 실측: `grading_policy`·
`concept_graph_version`·파서 버전 상수·notation contract 로더 모두 0건). 값이 없는 키에 임의 상수를
박으면 "버전을 기록했다"는 외양만 남고 실제로는 아무 변경도 추적하지 못한다 — 그 상수가 의미 변경에
맞춰 올라간다는 보증이 없기 때문이다. 그러므로 출처가 생길 때까지 `None`(= 기록 불가)으로 둔다.
`None`은 "기본 버전"이 아니라 **"모른다"**다.

출처를 연결하는 일은 키마다 별도 작업이다(해당 키의 정본 소유자가 값을 만든 뒤 `SOURCES` 항목과
`resolve_attempt_version_pin`을 **같이** 고친다 — 둘이 어긋나면
`test_evaluation_context.py`가 빨개진다).
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

#: 이 계약의 형상 버전 — 키를 더하거나 의미를 바꿀 때 올린다. JSONB에 함께 저장되어
#: 옛 행을 읽는 쪽이
#: 어떤 키 집합을 기대해야 하는지 알 수 있다.
EVALUATION_CONTEXT_SCHEMA_VERSION: Final[str] = "1"

#: 키 → 런타임 출처 설명(실제 출처가 있으면 문자열, **없으면 `None`**). 정본 표다 — 키를 추가·연결할
#: 때 여기부터 고친다. `None` 키는 어떤 writer도 값을 채우면 안 된다(테스트가 동결).
EVALUATION_CONTEXT_SOURCES: Final[dict[str, str | None]] = {
    # 문항 행의 교육과정 개정 라벨(`problem.curriculum_version`, NOT NULL). 문항이 어느
    # 개정판을 위해
    # 저작됐는가 — 값은 `Curriculum` enum 값(예 "2022_REVISION")이다. 주의: 44 §10.2의
    # `curriculum_version_id`(교육과정 Release 버전 테이블 행)가 **아니라 라벨**이다 — 그 테이블과
    # 문항을 잇는 매핑은 아직 없다.
    "curriculum_version": (
        "problem.curriculum_version (Curriculum enum 값 — 라벨, 버전 테이블 id 아님)"
    ),
    # 개념 그래프의 한 시점을 가리키는 식별자. 그래프 단위 Release/스냅숏이 없다(44 §13 Phase 2 —
    # `concept_version`은 개념 *개별* 판일 뿐 그래프 전체의 판이 아니다).
    "concept_graph_version": None,
    # 채점 정책(정오 판정 규칙)의 버전. `AssessmentPolicy` 버전 체계는 44 §13 2단계 확장이고 코드에
    # 정책 버전 상수가 없다 — 채점 권위(`l3.verify_final_answer`)는 존재하나 그 규칙에 번호가 없다.
    "grading_policy_version": None,
    # 수식 표기 계약(`data/notation_contract.json` "version") — 28 §35 요구. 그 JSON은 테스트만 읽고
    # 백엔드 런타임에 로더가 없다(배포 산출물에도 포함되지 않는다).
    "notation_contract_version": None,
    # 정규화 파서(입력 수식 → 비교 가능한 형태)의 버전 — 28 §35 요구. 파서 버전 상수가 없다.
    "normalizer_version": None,
}


class EvaluationContext(BaseModel):
    """한 시도가 채점된 순간의 환경 스냅숏 — `problem_attempt.evaluation_context` JSONB의 형상.

    모든 값 키는 `str | None`이다. `None` = **기록 불가(모름)**이지 기본값이 아니다 —
    위 모듈 docstring.
    `schema_version`만 항상 채워진다(형상 식별자). 키 집합 정본은 `EVALUATION_CONTEXT_SOURCES`.
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    schema_version: str = Field(
        default=EVALUATION_CONTEXT_SCHEMA_VERSION,
        description="이 JSON의 형상 버전(키 집합을 해석하는 기준)",
    )
    curriculum_version: str | None = Field(
        default=None,
        description="문항이 저작된 교육과정 개정 라벨(`Curriculum` 값). 버전 테이블 id가 아니다.",
    )
    concept_graph_version: str | None = Field(
        default=None,
        description="개념 그래프 시점 식별자. 출처 없음 → 현재 항상 None(기록 불가)",
    )
    grading_policy_version: str | None = Field(
        default=None,
        description="채점 정책 버전. 출처 없음 → 현재 항상 None(기록 불가)",
    )
    notation_contract_version: str | None = Field(
        default=None,
        description="수식 표기 계약 버전(28 §35). 런타임 로더 없음 → 현재 항상 None(기록 불가)",
    )
    normalizer_version: str | None = Field(
        default=None,
        description="정규화 파서 버전(28 §35). 버전 상수 없음 → 현재 항상 None(기록 불가)",
    )


__all__ = [
    "EVALUATION_CONTEXT_SCHEMA_VERSION",
    "EVALUATION_CONTEXT_SOURCES",
    "EvaluationContext",
]
