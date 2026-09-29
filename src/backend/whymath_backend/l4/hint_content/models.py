"""Hint 엔티티 Pydantic 정본 — graded 1~3·노출량(reveals)·reveal_score (S4-11 · D3).

설계 정본: `schemas/v1.1/hint.schema.yaml`(entity Hint·layer L4). 영속 ORM은
`db/models/hint.py`(`hints`), 매핑은 `l4/hint_content/store.py`가 한다.

Level 4는 이 엔티티에 **표현될 수 없다**: `HintLevel = Literal[1, 2, 3]`. 답 미루기 4단계의
마지막 칸(전체 풀이)은 `l4/hint_deferral.HintLevel`(1~4)에만 있고, 그 칸은 이 카탈로그 밖의
안전망으로 남는다(yaml `level` note·`04_pedagogy_engine.md` "PRD Hint 엔티티와의 정렬").

reveal_score 정의(이 모듈이 단일 정본):
  힌트가 실제로 노출한 **최고 단계(tier)**를 3으로 나눈다 —
    부분 시연(partial_computation) → 3 · 단계 흐름(step_flow) → 2 · 개념 이름(concept_names) → 1
    · 아무것도 → 0.  즉 reveal_score ∈ {0, 1/3, 2/3, 1}.
  왜 가산(가중 합)이 아니라 최고 단계인가: graded 척도는 누적이다(L1 ⊂ L2 ⊂ L3) — 흐름을 보여준
  힌트가 개념 이름을 함께 댔는지는 '얼마나 답에 가까워졌나'를 바꾸지 않는다. 가중 합은 "흐름만
  보여준 L2"를 "개념만 댄 L1"과 같은 점수로 만드는 역전을 낳는다. 단계 내 세분(예: 부분 시연이
  경로의 몇 %까지 갔나)은 **도입하지 않는다** — 파일럿 실측(S3-01) 없이 가중을 정하면 측정이
  아니라 추측이다(CLAUDE.md "측정 없는 도입 없음").
  깊이 환산: `reveal_depth_equivalent(score) = 3 × score` — KPI '평균 답 미루기 도달 깊이
  2.5+'(`harness/wh1_evaluation` ⑧, hint_level 1~4 척도)와 같은 눈금으로 읽기 위한 변환이다.

정직한 한계(있는 척 금지): 게이트 A(`gates.check_level_reveals`)가 "레벨 = 노출 단계"를 강제하므로
**검수 통과(verified) 힌트의 reveal_score는 항상 level/3이다**. 그래서 KPI 정밀화의 실체는 점수의
미세 눈금이 아니라 ① 본문에서 *파생·검증된* 노출(선언이 아님)이라는 점 ② 결정된 hint_level이
아니라 *실제로 전달된* 검수 힌트에만 기록된다는 점(정적 템플릿 턴은 None — 문제 특화 노출이
없으므로 0으로 날조하지 않는다)이다.
"""

from __future__ import annotations

import math
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from whymath_backend.l4.socratic.categories import SocraticCategory

__all__ = [
    "GENERATOR_VERSION",
    "HINT_LEVELS",
    "REVEAL_TIER_COUNT",
    "Hint",
    "HintLevel",
    "HintReveals",
    "ServedHint",
    "SolutionStepRef",
    "compute_reveal_score",
    "disclosure_tier",
    "hint_id_for",
    "reveal_depth_equivalent",
]

HintLevel = Literal[1, 2, 3]
"""graded 힌트 레벨 — 1=가장 은근(개념 이름)·2=단계 흐름·3=부분 시연. 4는 엔티티 밖."""

HINT_LEVELS: tuple[HintLevel, ...] = (1, 2, 3)
"""서빙·생성이 순회하는 레벨 전수(Literal과 같은 집합 — 테스트가 동치를 동결한다)."""

REVEAL_TIER_COUNT = 3
"""노출 단계 수(개념 이름·단계 흐름·부분 시연) — reveal_score의 분모."""

GENERATOR_VERSION = "s4-11-template-v1"
"""오프라인 템플릿 생성기 판 — 본문 템플릿을 바꾸면 올린다(재생성 추적)."""


def disclosure_tier(*, concept_names: bool, step_flow: bool, partial_computation: bool) -> int:
    """노출 플래그 → 최고 노출 단계(0~3). 누적 척도라 가장 깊은 노출이 단계를 정한다."""
    if partial_computation:
        return 3
    if step_flow:
        return 2
    if concept_names:
        return 1
    return 0


def compute_reveal_score(
    *, concept_names: bool, step_flow: bool, partial_computation: bool
) -> float:
    """노출 플래그 → reveal_score(0~1). 정의는 모듈 docstring(최고 단계 / 3)."""
    tier = disclosure_tier(
        concept_names=concept_names,
        step_flow=step_flow,
        partial_computation=partial_computation,
    )
    return tier / REVEAL_TIER_COUNT


def reveal_depth_equivalent(score: float) -> float:
    """reveal_score → hint_level 척도의 깊이(0~3). KPI '도달 깊이 2.5+'와 같은 눈금 비교용."""
    return score * REVEAL_TIER_COUNT


def hint_id_for(solution_path_id: str, step_order: int, level: int) -> str:
    """결정론 힌트 ID — 생성 자리(경로·단계·레벨)가 곧 정체성이다(재실행 멱등)."""
    return f"hint-{solution_path_id}-s{step_order}-l{level}"


class HintReveals(BaseModel):
    """노출량 정량화 — yaml `HintReveals` 1:1. reveal_score는 플래그에서 *파생*돼야 한다.

    `reveal_score`를 자유 입력으로 두지 않는 이유: 점수가 플래그와 어긋나면 KPI가 선언이 아니라
    오타를 잰다. 검증기가 `compute_reveal_score`와의 일치를 강제한다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reveals_concept_names: bool = Field(default=False, description="개념·도구 이름 노출(L1 전형).")
    reveals_step_flow: bool = Field(default=False, description="단계 흐름 노출(L2 전형).")
    reveals_partial_computation: bool = Field(
        default=False, description="일부 단계 실제 시연(L3 전형)."
    )
    revealed_concept_ids: tuple[str, ...] = Field(
        default=(), description="노출한 개념 ID(UC 코드 공간 — concept_node.concept_id)."
    )
    reveal_score: float = Field(ge=0.0, le=1.0, description="종합 노출 점수 0~1(파생값).")

    @model_validator(mode="after")
    def _score_is_derived_from_flags(self) -> HintReveals:
        expected = compute_reveal_score(
            concept_names=self.reveals_concept_names,
            step_flow=self.reveals_step_flow,
            partial_computation=self.reveals_partial_computation,
        )
        if not math.isclose(self.reveal_score, expected, abs_tol=1e-9):
            raise ValueError(
                f"reveal_score={self.reveal_score}가 노출 플래그에서 파생한 값 {expected}와 "
                "다르다 — 점수는 플래그의 함수다(자유 입력 금지)"
            )
        return self

    @classmethod
    def from_flags(
        cls,
        *,
        concept_names: bool,
        step_flow: bool,
        partial_computation: bool,
        revealed_concept_ids: tuple[str, ...] = (),
    ) -> HintReveals:
        """플래그만 받아 점수를 파생해 채운다(생성기·store의 유일 생성 경로)."""
        return cls(
            reveals_concept_names=concept_names,
            reveals_step_flow=step_flow,
            reveals_partial_computation=partial_computation,
            revealed_concept_ids=revealed_concept_ids,
            reveal_score=compute_reveal_score(
                concept_names=concept_names,
                step_flow=step_flow,
                partial_computation=partial_computation,
            ),
        )


class SolutionStepRef(BaseModel):
    """힌트가 속한 풀이 단계 참조 — yaml `SolutionStepRef`(경로 ID + 단계 order + 문제 ID)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    solution_path_id: str = Field(min_length=1, description="풀이 경로 ID(solution_paths FK).")
    step_order: int = Field(ge=1, description="경로 안 SolutionStep.order(1부터).")
    problem_id: uuid.UUID = Field(description="문제 ID(서빙 조회 키).")


class Hint(BaseModel):
    """graded 힌트 1개 — 본문·노출량·전달 카테고리·검증 상태(yaml entity Hint).

    `level`이 `Literal[1, 2, 3]`이라 4는 검증 단계에서 거부된다(엔티티 밖 안전망).
    `socratic_category`는 기존 L4 6카테고리 enum을 그대로 쓴다 — 신규 힌트 유형 enum 없음.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    hint_id: str = Field(min_length=1, description="PK — hint_id_for 결정론 ID.")
    solution_step_ref: SolutionStepRef
    level: HintLevel = Field(description="1=개념 이름·2=단계 흐름·3=부분 시연(4는 엔티티 밖).")
    reveals: HintReveals
    content: str = Field(min_length=1, description="학생에게 보여줄 본문(톤 게이트 통과 필수).")
    socratic_category: SocraticCategory | None = Field(
        default=None, description="전달 소크라테스 카테고리(기존 6종 — 신규 enum 없음)."
    )
    verified: bool = Field(default=False, description="게이트 3종 전건 통과 여부.")
    gate_report: dict[str, object] = Field(
        default_factory=dict, description="게이트별 판정·사유(거부 이유 보존)."
    )
    generator_version: str = Field(default=GENERATOR_VERSION, min_length=1)


class ServedHint(BaseModel):
    """coach 세션 응답에 싣는 서빙 힌트 — verified=true 카탈로그 행의 학생 대면 투영.

    검증 메타(gate_report·generator_version)와 노출 플래그 원형은 싣지 않는다(학생 대면 표면
    최소화 — `api/solution_paths.SolutionPathStepItem` 선례). `reveal_score`는 싣는다 — 클라가
    "지금 몇 단계 힌트인지" 라벨을 붙이는 입력이며(04 문서 "L5는 단계 라벨만 표시") 정답 정보가
    아니다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    hint_id: str = Field(description="서빙된 힌트 ID(attempt_event 힌트제공에도 함께 적재).")
    level: HintLevel = Field(description="graded 레벨 1~3.")
    step_order: int = Field(ge=1, description="이 힌트가 겨냥한 풀이 단계 order.")
    content: str = Field(min_length=1, description="검수 통과 힌트 본문.")
    socratic_category: SocraticCategory | None = Field(
        default=None, description="전달 소크라테스 카테고리(기존 6종)."
    )
    reveal_score: float = Field(ge=0.0, le=1.0, description="노출 점수(KPI 도달 깊이 정밀화).")
