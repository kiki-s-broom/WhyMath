"""WH-S bank_solution 구조 승격 writer — 평문 풀이 JSONB → SolutionPath 실체화 (S4-09·D1).

`verified_solutions.solution_path` JSONB(`{conditions, answer, steps}` 평문 —
`whs/harness.py::FinalizeAction`이 적재)를 `l3.solution_path.SolutionPath`(Pydantic 검증)로
승격해 `solution_paths`(헤더) + `problem_step`(단계·additive 컬럼)에 적재한다. **이미 흐르는
데이터의 스키마 승격**이다(신규 데이터 창조 아님 — D1 유보 해제 논증).

순수 결정론·LLM 호출 0(CLAUDE.md — 이 태스크는 LLM 0):
  - `plan_promotion`(순수 함수)이 전 판정·검증·큐 분류를 수행하고, DB 래퍼
    (`promote_verified_solutions`)는 조회·적재만 한다(hermetic 테스트 가능 분해).
  - **approach_type 매핑**: 폐쇄 6종 영문 정확 일치 + 한글 라벨(대수적/기하적/조합적/귀납적/
    시각적/역방향 — yaml enum 한글 설명·§2.4 docstring 표기와 1:1) 결정론 번역만. 그 외
    (예: "corpus-replay")는 추측하지 않고 **사람 검수 큐**로(AI 자기승인 금지). 단 "corpus-replay"는
    사람이 승인한 문항군 표(`CORPUS_REPLAY_APPROACH_BY_FAMILY` · P3-94)에 있는 문항만 그 표의 값으로
    매핑한다 — 행마다 추측하는 것이 아니라 생성기 단위로 한 번 판정된 값이다.
  - **개념 ID 매칭**: 표현식 문자열→개념 노드의 결정론 매칭 유틸이 코드베이스에 없고(의미
    매칭은 임베딩·LLM 축 — L3 5개 핵심 호출지점 중 4번), LLM 0 제약이라 **매칭을 시도하지
    않는다** — 전 스텝을 `concept_node_id=NULL`(검수 대기)로 적재하고 전건을 사람 검수 큐에
    기록한다. `concept_sequence`는 매칭 확정분만 담으므로 빈 배열이다(**날조 금지**).

승격 규칙(정직성 명시):
  - **verified만** 승격한다 — `unverified`는 §3 격리 등급(학습·서빙 배제·R-S2)이라
    학생 인접 서빙 표면(`problem_step` → steps API)에 절대 올리지 않는다.
  - `sympy_verified` 승계: verified = "Tier1 pass + 전 *인접 전이* Tier2 correct"
    (`whs/verdict.py`·`l3/verify_solution.py` — 전이 개수는 n-1)이므로, 검증된 것은 "직전
    스텝→이 스텝" 전이다. 따라서 **order≥2 스텝만 True**, 첫 스텝은 전이 검증 대상이
    아니라 False다(과잉 주장 금지 — 원 검증 상태의 정확한 승계).
  - **다중 경로 공존(S4-10 재론 확정)**: S4-09가 유보한 "문제당 1경로" 제약을 재론해
    *분리*했다 — ① `solution_paths` **헤더는 문제당 N경로 허용**(yaml 관계 "N:1 — 한 문제에
    여러 SolutionPath"의 실현·테이블에 problem_id UNIQUE가 애초에 없음·풀이 다양성 자산 §2.4)
    ② `problem_step` **단계는 대표 1경로만** 실체화한다 — `UNIQUE(problem_id, step_order)`
    불변 유지(steps API는 문제당 *한* 정합 시퀀스를 서빙하는 계약이라 두 경로의 단계가 같은
    문제 아래 섞이면 서빙 표면이 붕괴한다). 대표 = *단계 좌석이 비어 있을 때 처음 승격되는
    경로*(선호 유형·검수 우선 등 대표 *선택 정책*은 L2 preferred_solution_style이 서는 §4-⑤
    후속 몫 — `l3/solution_path_store.py` 동일 유보). 추가 경로는 헤더만 적재하고 단계 스킵을
    리포트한다(`steps_skipped_*`). 기존 `problem_step` 행(레거시 Socratic 단계)이 선점한
    문제도 단계는 스킵한다(클로버 금지) — 헤더는 적재한다(경로 자산은 별개 축).
  - 멱등: `solution_path_id = "sp-{verified_solutions.id}"` 결정론 부여 — 재실행 시 기존
    적재분은 `already_promoted`로 스킵된다.
  - `content` 영속 좌석: `problem_step.expected_answer`("이 단계의 기대 답") — WH-S 스텝은
    그 단계에서 도달하는 *중간 상태 표현식*이므로 기존 컬럼 의미와 부합한다(신규 본문 컬럼을
    additive 목록 밖으로 늘리지 않음 — 렌더러-중립 문자열 그대로·표현≠의미).

검수 큐(리포트 산출물 — crosswalk 검수 큐 선례 동형): 큐 레코드의 식별 키
`"queue": "solution_path_promotion_review"`는 어떤 로더도 수용하지 않는 형식이라 검수를
건너뛴 자동 적재가 구조적으로 차단된다(자동 병합·자동 확정 금지). 큐에는 시스템 생성
표현식(steps)·ID만 담고 문제 본문/조건은 담지 않는다(저작권 출처 게이트 불요 경계 —
`self_evolution_export_cli`의 conditions 게이트 필요성 회피).

실행 표면(ops CLI — `self_evolution_export_cli` 컨벤션 미러):
    python -m whymath_backend.whs.path_promotion            # dry-run(기본·미적재)
    python -m whymath_backend.whs.path_promotion --apply    # 실제 적재(commit)
stdout = 검수 큐 JSONL(레코드 1개/줄·`> queue.jsonl` 파이프 가능), stderr = 승격 카운트
리포트 JSON 한 줄(정직 회계 — 총 건수·Pydantic 통과·매칭 성공/검수 큐 비율). 종료 코드 0.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Callable, Coroutine, Mapping, Sequence, Set
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.problem import Problem, ProblemStep
from whymath_backend.db.models.solution_path import SolutionPath as SolutionPathOrm
from whymath_backend.db.models.verified_solution import (
    VerifiedSolution,
    WhsSolutionGrade,
)
from whymath_backend.db.session import get_sessionmaker
from whymath_backend.l3.solution_path import SolutionPath, parse_approach_label
from whymath_backend.schema.problem import ProblemStep as ProblemStepSchema

__all__ = [
    "PlannedPath",
    "PromotionPlan",
    "PromotionReport",
    "build_solution_path",
    "extract_plain_steps",
    "main",
    "map_strategy_tag_to_approach",
    "plan_promotion",
    "promote_verified_solutions",
    "solution_path_id_for",
]

# 검수 큐 레코드 식별 키 — 후보/로더/다른 큐 형식과 *일부러* 다르다(오투입·자동 적재 차단 —
# crosswalk 검수 큐 `"review_queue"` top key 선례 동형).
_QUEUE_KIND = "solution_path_promotion_review"


def map_strategy_tag_to_approach(strategy_tag: str | None) -> str | None:
    """`strategy_tag` 자유 텍스트 → 폐쇄 6종 approach_type 값. 매핑 불가면 None(추측 금지).

    S4-10 좌석 승격: 자체 매핑 상수를 걷어내고 단일 번역 경로
    `l3.solution_path.parse_approach_label`(영문 enum 값 정확 일치 + 한글 라벨 1:1)에
    위임한다(값 중복 제거 — `ApproachType` 단일 좌석·`APPROACH_LABELS_KR` 단일 번역표).
    None 반환 = "사람이 판정할 몫"(검수 큐행 — AI 자기승인 금지·"corpus-replay" 등 620문
    재생 태그가 여기 해당).
    """
    parsed = parse_approach_label(strategy_tag)
    return parsed.value if parsed is not None else None


#: `whs/corpus_replay`가 모든 재생 풀이에 다는 태그 — 풀이 유형이 아니라 *출처* 표지다.
CORPUS_REPLAY_STRATEGY_TAG = "corpus-replay"

#: 코퍼스 재생 풀이의 풀이 유형 — 생성기 문항군(slug 접두) 단위 결정론 표.
#: **사람 승인 표다**(게이트 G-p332-corpus-replay-approach · Kiki 2026-11-01 A안). AI가 행마다
#: 추측하는 것이 아니라, 생성기가 만드는 풀이 단계의 형태를 문항군 단위로 한 번 판정해 고정한다.
#: 범위 = 핵심 개념 은행 5개(p3_calculus1_diff_v0·generated_v0·p3_fill_v0·rephrased_v0·
#: conceptual_v0)의 풀이 단계 보유 문항군 28개 전수. 표에 없는 문항군은 지금처럼 검수 큐로 간다.
#:   - inductive: wm-indseq — 같은 항을 나열한 합에서 일반항 공식으로 일반화한다.
#:   - algebraic: 나머지 — 미분·인수분해·대입·공식 계산의 식 변형 연쇄다.
#: 근거 표본 = docs/reviews/p3_32_hint_pipeline_sandbox_2026-11-01.md §5.
CORPUS_REPLAY_APPROACH_BY_FAMILY: dict[str, str] = {
    # generated_v0 · rephrased_v0 (rephrased는 `<문항군>-<해시>-rephrased` 꼴)
    "wm-skel": "algebraic",
    "wm-calc-ext": "algebraic",
    "wm-calc-extirr": "algebraic",
    "wm-calc-extmc": "algebraic",
    "wm-calc-extv": "algebraic",
    "wm-calc-tan": "algebraic",
    "wm-exp": "algebraic",
    "wm-log": "algebraic",
    "wm-arseq": "algebraic",
    "wm-arsum": "algebraic",
    "wm-geseq": "algebraic",
    "wm-gesum": "algebraic",
    "wm-indseq": "inductive",
    "wm-trig": "algebraic",
    "wm-trigeq": "algebraic",
    # conceptual_v0
    "wm-count-mc": "algebraic",
    # p3_calculus1_diff_v0
    "wm-p3-diff-power": "algebraic",
    "wm-p3-diff-polyrules": "algebraic",
    "wm-p3-diff-tangent": "algebraic",
    "wm-p3-diff-mvt": "algebraic",
    "wm-p3-diff-graphshape": "algebraic",
    "wm-p3-diff-eqapp": "algebraic",
    "wm-p3-diff-velocity": "algebraic",
    # p3_fill_v0
    "wm-p3-diff-coefficient": "algebraic",
    "wm-p3-diff-differentiability": "algebraic",
    "wm-p3-diff-monotonicity": "algebraic",
    "wm-p3-diff-power-pattern": "algebraic",
    "wm-p3-diff-motion-word": "algebraic",
}


def corpus_replay_approach_for_slug(slug: str | None) -> str | None:
    """문항 slug → 승인 표의 풀이 유형. 표에 없으면 None(검수 큐행 — 추측 금지).

    문항군 경계는 `-`다: slug가 문항군 이름과 같거나 `문항군-`로 시작해야 한다. 그래서
    `wm-trig`가 `wm-trigeq-…`를, `wm-calc-ext`가 `wm-calc-extv-…`를 잡지 않는다. 여러 문항군이
    맞으면 가장 긴 것을 쓴다(`wm-p3-diff-power` vs `wm-p3-diff-power-pattern-…`).
    """
    if not slug:
        return None
    matches = [
        family
        for family in CORPUS_REPLAY_APPROACH_BY_FAMILY
        if slug == family or slug.startswith(family + "-")
    ]
    if not matches:
        return None
    return CORPUS_REPLAY_APPROACH_BY_FAMILY[max(matches, key=len)]


def extract_plain_steps(solution_path: dict[str, Any]) -> list[str] | None:
    """평문 `solution_path` JSONB에서 steps(표현식 문자열 리스트)를 추출. 형식 위반이면 None.

    FinalizeAction 계약(`{conditions, answer, steps}` — steps는 list[str])을 그대로 읽는다.
    steps 키 부재·리스트 아님·비문자열 원소 혼입은 전부 None(형식 위반 — 호출자가 리포트에
    사유를 기록한다·조용한 통과 금지).
    """
    steps = solution_path.get("steps")
    if not isinstance(steps, list):
        return None
    if not all(isinstance(step, str) for step in steps):
        return None
    return list(steps)


def solution_path_id_for(verified_solution_id: uuid.UUID) -> str:
    """결정론 solution_path_id — `sp-{verified_solutions.id}`(멱등 재실행의 열쇠)."""
    return f"sp-{verified_solution_id}"


def build_solution_path(
    *,
    solution_path_id: str,
    problem_id: uuid.UUID,
    approach_type: str,
    steps: Sequence[str],
    created_at: datetime,
) -> SolutionPath:
    """평문 steps → 검증된 `l3.SolutionPath`(verified 등급 전제). 위반은 ValidationError 전파.

    스텝 구성(정직 승계 — 모듈 docstring 승격 규칙):
      - order: 1부터 연속(열거 순서 그대로 — Pydantic invariant가 재검증).
      - content: 표현식 문자열 *그대로*(렌더러-중립·AST화 금지).
      - concept_node_id: None(매칭 미시도 — 검수 대기), reasoning_type/justification: None
        (원 데이터에 없음 — 하위호환 축·날조 금지).
      - sympy_verified: order≥2만 True — verified 등급이 보증하는 것은 *인접 전이*(직전
        스텝→이 스텝) Tier2 correct뿐이라 첫 스텝은 승계 근거가 없다(False).
      - concept_sequence: 빈 배열(매칭 확정분만 담는 좌석 — 날조 금지).
    """
    return SolutionPath.model_validate(
        {
            "solution_path_id": solution_path_id,
            "problem_id": str(problem_id),
            "approach_type": approach_type,
            "concept_sequence": [],
            "steps": [
                {
                    "order": index,
                    "content": content,
                    "sympy_verified": index >= 2,  # 첫 스텝은 전이 검증 대상 아님(정직)
                }
                for index, content in enumerate(steps, start=1)
            ],
            "verified_by_human": False,  # 승격 직후 항상 미검수(AI 자기승인 금지)
            "equivalence_cluster_id": None,  # 군집 부여는 S4-12(D4) 몫
            "created_at": created_at,
        }
    )


@dataclass
class PromotionReport:
    """승격 배치 정직 회계 — 수치는 전부 실측·조용한 생략 0(`ReplayReport` 선례).

    `failures`는 사람 가독 사유 목록(예외 타입명 포함 — 침묵 실패 금지). 큐 카운트 2종:
    `queued_approach_unmappable`(승격 *차단* — approach NOT NULL 좌석을 채울 수 없음)·
    `queued_concept_unmatched_steps`(승격은 *진행* — concept 좌석 NULL·사람이 채움).

    S4-10 재론 반영: `promoted`는 *헤더* 적재 계획 수이고, 그중 단계까지 실체화한 대표
    경로가 `promoted_with_steps`·단계 좌석 선점으로 헤더만 적재한 경로가 두 `steps_skipped_*`
    카운트다(불변식: promoted = promoted_with_steps + steps_skipped_additional_path +
    steps_skipped_step_conflict — 구 `skipped_additional_path`/`skipped_step_conflict`는
    경로 전체 스킵이었으나 이제 *단계만* 스킵한다).
    """

    total_input: int = 0  # verified_solutions 전 행(모든 grade)
    excluded_unverified: int = 0  # unverified 제외(격리 유지·R-S2)
    eligible_verified: int = 0  # verified 행 수(승격 후보)
    promoted: int = 0  # solution_paths 헤더 적재 계획 성공(N경로 허용 — S4-10 재론)
    promoted_with_steps: int = 0  # 그중 problem_step 단계까지 실체화한 대표 경로 수
    promoted_steps: int = 0  # 적재 계획된 스텝 행 총수(대표 경로들의 합)
    already_promoted: int = 0  # 멱등 재실행 스킵(기존 sp-id 실재)
    skipped_empty_steps: int = 0  # steps=[](실체화할 단계 없음)
    skipped_malformed: int = 0  # solution_path JSONB 형식 위반(list[str] 아님)
    skipped_problem_missing: int = 0  # 코퍼스에 problem 부재(FK 불가·날조 금지)
    steps_skipped_additional_path: int = 0  # 대표 경로가 이미 단계 실체화 — 헤더만(UNIQUE 불변)
    steps_skipped_step_conflict: int = 0  # 레거시 problem_step 선점 — 헤더만(클로버 금지)
    queued_approach_unmappable: int = 0  # approach 미확정 → 검수 큐(승격 차단)
    # 코퍼스 재생 태그를 승인 표(문항군)로 매핑한 수 — 표가 실제로 작동한 비율의 분자.
    approach_from_corpus_family: int = 0
    queued_concept_unmatched_steps: int = 0  # 개념 매칭 검수 대기 스텝 수(승격은 진행)
    pydantic_rejected: int = 0  # Pydantic invariant 위반(방어적 — 정상 데이터면 0)
    failures: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """리포트 JSON — 카운트 + 비율(총 건수·Pydantic 통과·매칭 성공/검수 큐 비율)."""
        pydantic_attempted = self.promoted + self.pydantic_rejected
        concept_matched_steps = self.promoted_steps - self.queued_concept_unmatched_steps
        return {
            "total_input": self.total_input,
            "excluded_unverified": self.excluded_unverified,
            "eligible_verified": self.eligible_verified,
            "promoted": self.promoted,
            "promoted_with_steps": self.promoted_with_steps,
            "promoted_steps": self.promoted_steps,
            "already_promoted": self.already_promoted,
            "skipped_empty_steps": self.skipped_empty_steps,
            "skipped_malformed": self.skipped_malformed,
            "skipped_problem_missing": self.skipped_problem_missing,
            "steps_skipped_additional_path": self.steps_skipped_additional_path,
            "steps_skipped_step_conflict": self.steps_skipped_step_conflict,
            "queued_approach_unmappable": self.queued_approach_unmappable,
            "approach_from_corpus_family": self.approach_from_corpus_family,
            "queued_concept_unmatched_steps": self.queued_concept_unmatched_steps,
            "pydantic_rejected": self.pydantic_rejected,
            # Pydantic 통과율 — 시도 0건이면 None(0/0을 1.0으로 위장하지 않음).
            "pydantic_pass_rate": (
                round(self.promoted / pydantic_attempted, 4) if pydantic_attempted else None
            ),
            # approach 매핑 성공률(eligible 대비) — 검수 큐 비율의 보수(눈금 동일).
            "approach_mapped_rate": (
                round(1 - self.queued_approach_unmappable / self.eligible_verified, 4)
                if self.eligible_verified
                else None
            ),
            # 개념 매칭 성공률 — 매칭 유틸 부재라 현 슬라이스는 정직하게 0.0(스텝 0이면 None).
            "concept_match_rate": (
                round(concept_matched_steps / self.promoted_steps, 4)
                if self.promoted_steps
                else None
            ),
            "failures": list(self.failures),
        }


@dataclass(frozen=True)
class PlannedPath:
    """적재 계획 1건 — 검증 통과한 경로 모델 + 단계 스키마(래퍼가 ORM으로 변환·적재).

    S4-10 재론: `step_schemas`가 빈 튜플이면 *헤더만* 적재하는 추가 경로다(대표 경로가
    이미 단계 좌석을 차지 — UNIQUE(problem_id, step_order) 불변·클로버 금지).
    """

    path: SolutionPath
    problem_id: uuid.UUID
    step_schemas: tuple[ProblemStepSchema, ...]


@dataclass
class PromotionPlan:
    """`plan_promotion`의 산출 — 적재 계획 + 정직 회계 + 검수 큐 레코드."""

    planned: list[PlannedPath] = field(default_factory=list)
    report: PromotionReport = field(default_factory=PromotionReport)
    queue_entries: list[dict[str, Any]] = field(default_factory=list)


def _queue_approach_entry(row: VerifiedSolution, steps: list[str]) -> dict[str, Any]:
    """approach 미확정 검수 큐 레코드 — 사람이 6종 중 하나로 판정 후 재실행(또는 S4-10 승격).

    문제 본문/조건은 담지 않는다(steps는 시스템 생성 표현식 — 저작권 게이트 불요 경계).
    """
    return {
        "queue": _QUEUE_KIND,
        "reason": "approach_unmappable",
        "verified_solution_id": str(row.id),
        "problem_id": str(row.problem_id),
        "strategy_tag": row.strategy_tag,
        "steps": steps,
    }


def _queue_concept_entry(
    row: VerifiedSolution, solution_path_id: str, steps: list[str]
) -> dict[str, Any]:
    """개념 ID 매칭 검수 큐 레코드 — 전 스텝 매칭 대기(승격은 진행·concept 좌석 NULL).

    사람이 스텝별 concept_node_id를 판정해 채우면 `concept_sequence`도 그 확정분으로
    구성된다(자동 병합·자동 확정 금지 — 큐 형식은 어떤 로더도 수용하지 않는다).
    """
    return {
        "queue": _QUEUE_KIND,
        "reason": "concept_unmatched",
        "verified_solution_id": str(row.id),
        "problem_id": str(row.problem_id),
        "solution_path_id": solution_path_id,
        "unmatched_step_orders": list(range(1, len(steps) + 1)),
        "steps": steps,
    }


def plan_promotion(
    rows: Sequence[VerifiedSolution],
    *,
    existing_problem_ids: Set[uuid.UUID],
    already_promoted_path_ids: Set[str],
    problem_ids_with_steps: Set[uuid.UUID],
    now: datetime,
    slug_by_problem: Mapping[uuid.UUID, str] | None = None,
) -> PromotionPlan:
    """승격 계획 수립 — **순수 결정론**(DB·LLM 0). 판정 순서는 아래 주석 번호 그대로.

    `rows`는 호출자가 결정적 순서(`problem_id, created_at, id`)로 정렬해 넘긴다 — "대표
    경로"(단계 실체화)는 단계 좌석이 빈 문제에서 이 순서의 첫 행으로 정의된다. 프리페치
    집합 3종은 래퍼가 DB에서 모아 넘긴다(참조 실재·멱등·단계 좌석 선점의 판정 재료).

    S4-10 재론: 구 시그니처의 `problem_ids_with_path`(문제당 1경로 가드)는 제거됐다 —
    헤더는 N경로 허용이라 경로 존재가 새 경로를 막지 않고, 단계 좌석만
    `problem_ids_with_steps`(레거시 포함 problem_step 실재)로 가드한다.

    `slug_by_problem`(P3-94): `corpus-replay` 태그 행의 풀이 유형을 승인 표
    (`CORPUS_REPLAY_APPROACH_BY_FAMILY`)에서 찾을 때 쓰는 문항 slug. 없거나 표에 없으면 큐행.
    """
    plan = PromotionPlan()
    report = plan.report
    # 이 런에서 단계 실체화를 계획한 문제 — UNIQUE(problem_id, step_order)의 런 내 가드.
    # (헤더는 N경로 허용이라 가드 없음 — S4-10 재론.)
    step_planned_problems: set[uuid.UUID] = set()

    for row in rows:
        report.total_input += 1
        # ① unverified 격리(R-S2) — 서빙 표면(problem_step)에 절대 올리지 않는다.
        if row.grade != WhsSolutionGrade.VERIFIED:
            report.excluded_unverified += 1
            continue
        report.eligible_verified += 1

        # ② 평문 형식 검사 — steps가 list[str]이 아니면 승격 불가(사유 기록·조용한 통과 금지).
        steps = extract_plain_steps(row.solution_path)
        if steps is None:
            report.skipped_malformed += 1
            report.failures.append(
                f"malformed_steps vs={row.id}: solution_path.steps가 list[str]이 아님"
            )
            continue
        # ③ 빈 steps — 실체화할 단계가 없다(리포트 카운트·큐 아님).
        if not steps:
            report.skipped_empty_steps += 1
            continue
        # ④ 참조 실재(problem) — 코퍼스에 없는 문제는 FK 불가(날조 금지·사유 기록).
        if row.problem_id not in existing_problem_ids:
            report.skipped_problem_missing += 1
            report.failures.append(
                f"problem_missing vs={row.id}: problem={row.problem_id} 코퍼스 부재"
            )
            continue
        # ⑤ 멱등 — 이전 런에서 이미 승격된 경로는 스킵(결정론 sp-id가 열쇠).
        path_id = solution_path_id_for(row.id)
        if path_id in already_promoted_path_ids:
            report.already_promoted += 1
            continue
        # ⑥ approach 매핑 — 불가면 사람 검수 큐(NOT NULL 좌석을 추측으로 채우지 않는다).
        approach = map_strategy_tag_to_approach(row.strategy_tag)
        if approach is None and row.strategy_tag == CORPUS_REPLAY_STRATEGY_TAG:
            # 재생 태그는 출처 표지라 유형을 모른다 — 사람 승인 표(문항군)에서만 찾는다.
            approach = corpus_replay_approach_for_slug((slug_by_problem or {}).get(row.problem_id))
            if approach is not None:
                report.approach_from_corpus_family += 1
        if approach is None:
            report.queued_approach_unmappable += 1
            plan.queue_entries.append(_queue_approach_entry(row, steps))
            continue
        # ⑦ Pydantic 검증(invariant 전건) — 위반은 예외 타입명과 함께 기록(침묵 실패 금지).
        try:
            path = build_solution_path(
                solution_path_id=path_id,
                problem_id=row.problem_id,
                approach_type=approach,
                steps=steps,
                created_at=now,
            )
        except ValidationError as exc:
            report.pydantic_rejected += 1
            report.failures.append(
                f"pydantic_rejected vs={row.id}: {type(exc).__name__}: {str(exc)[:300]}"
            )
            continue
        # ⑧ 단계 좌석 판정(S4-10 재론) — 헤더는 무조건 계획하되, 단계는 좌석이 빈 문제의
        #    첫 경로(대표)만 실체화한다(UNIQUE 불변·레거시 클로버 금지).
        legacy_occupied = row.problem_id in problem_ids_with_steps
        run_occupied = row.problem_id in step_planned_problems
        materialize_steps = not (legacy_occupied or run_occupied)
        step_schemas: tuple[ProblemStepSchema, ...] = ()
        if materialize_steps:
            step_schemas = tuple(
                ProblemStepSchema(
                    problem_id=row.problem_id,
                    step_order=step.order,
                    expected_answer=step.content,  # content 영속 좌석(모듈 docstring 근거)
                    solution_path_id=path_id,
                    concept_node_id=None,  # 매칭 검수 대기
                    reasoning_type=None,  # 원 데이터에 없음(날조 금지)
                    justification=None,
                    common_errors=None,
                    sympy_verified=step.sympy_verified,
                )
                for step in path.steps
            )
            step_planned_problems.add(row.problem_id)
            report.promoted_with_steps += 1
            report.promoted_steps += len(steps)
            # 개념 매칭 검수 대기 스텝 수 — problem_step 행의 NULL concept 좌석 기준
            # (헤더만 적재한 경로의 개념 검수는 concept_sequence 축·큐 레코드로만 흐른다).
            report.queued_concept_unmatched_steps += len(steps)
        elif legacy_occupied:
            report.steps_skipped_step_conflict += 1
        else:
            report.steps_skipped_additional_path += 1
        # ⑨ 적재 계획 + 개념 매칭 검수 큐(승격은 진행 — concept 좌석은 NULL·사람이 채움).
        plan.planned.append(
            PlannedPath(path=path, problem_id=row.problem_id, step_schemas=step_schemas)
        )
        report.promoted += 1
        plan.queue_entries.append(_queue_concept_entry(row, path_id, steps))

    return plan


async def promote_verified_solutions(session: AsyncSession) -> PromotionPlan:
    """전 verified 풀이를 승격 계획·적재한다(commit은 호출자 — 저장소 패턴).

    조회 4종(전 행·problem 실재·기존 경로·기존 단계 선점)을 프리페치해 순수
    `plan_promotion`에 넘기고, 계획분을 ORM으로 변환·add·flush한다. dry-run/apply 분기는
    호출자(CLI)가 commit/rollback으로 결정한다 — 본 함수는 트랜잭션을 닫지 않는다.

    실사용 표면은 execute/add/flush뿐 — 테스트는 Fake를 `cast(AsyncSession, ...)`로 주입한다
    (`test_solution_bank.py` FakeSession 선례).
    """
    # 결정적 순서(단계 좌석이 빈 문제의 "대표(첫) 경로" 정의 기준 — get_all_verified 정렬 미러).
    rows_result = await session.execute(
        select(VerifiedSolution).order_by(
            VerifiedSolution.problem_id,
            VerifiedSolution.created_at,
            VerifiedSolution.id,
        )
    )
    rows: list[VerifiedSolution] = list(rows_result.scalars().all())

    problem_ids = {row.problem_id for row in rows}
    existing_problem_ids: set[uuid.UUID] = set()
    already_promoted_path_ids: set[str] = set()
    problem_ids_with_steps: set[uuid.UUID] = set()
    if problem_ids:
        problems_result = await session.execute(
            select(Problem.problem_id).where(Problem.problem_id.in_(problem_ids))
        )
        existing_problem_ids = set(problems_result.scalars().all())
        # 기존 경로 id만 필요(멱등) — 경로 *존재*는 더 이상 새 경로를 막지 않는다(S4-10 재론).
        paths_result = await session.execute(
            select(SolutionPathOrm.solution_path_id).where(
                SolutionPathOrm.problem_id.in_(problem_ids)
            )
        )
        already_promoted_path_ids = set(paths_result.scalars().all())
        steps_result = await session.execute(
            select(ProblemStep.problem_id).where(ProblemStep.problem_id.in_(problem_ids)).distinct()
        )
        problem_ids_with_steps = {
            step_problem_id
            for step_problem_id in steps_result.scalars().all()
            if step_problem_id is not None
        }

    # 코퍼스 재생 행이 있을 때만 slug를 읽는다 — 승인 표(문항군)로 풀이 유형을 찾는 재료(P3-94).
    slug_by_problem: dict[uuid.UUID, str] = {}
    replay_problem_ids = {
        row.problem_id for row in rows if row.strategy_tag == CORPUS_REPLAY_STRATEGY_TAG
    }
    if replay_problem_ids:
        slug_result = await session.execute(
            select(Problem.problem_id, Problem.slug).where(
                Problem.problem_id.in_(replay_problem_ids)
            )
        )
        slug_by_problem = {
            problem_id: slug for problem_id, slug in slug_result.all() if slug is not None
        }

    plan = plan_promotion(
        rows,
        existing_problem_ids=existing_problem_ids,
        already_promoted_path_ids=already_promoted_path_ids,
        problem_ids_with_steps=problem_ids_with_steps,
        now=datetime.now(tz=UTC),
        slug_by_problem=slug_by_problem,
    )

    for planned in plan.planned:
        # 헤더(solution_paths) — 검증된 l3 모델에서 ORM으로(use_enum_values라 approach는 str).
        session.add(
            SolutionPathOrm(
                solution_path_id=planned.path.solution_path_id,
                problem_id=planned.problem_id,
                approach_type=planned.path.approach_type,
                concept_sequence=list(planned.path.concept_sequence),
                verified_by_human=planned.path.verified_by_human,
                equivalence_cluster_id=planned.path.equivalence_cluster_id,
                created_at=planned.path.created_at,
            )
        )
    # 헤더를 먼저 DB에 보낸다 — `problem_step.solution_path_id`가 `solution_paths`를 외래 키로
    # 가리키는데 ORM에 relationship()이 없어 SQLAlchemy가 두 테이블의 INSERT 순서를 보장하지
    # 않는다. 한 flush에 섞으면 단계가 먼저 나가 외래 키 위반으로 배치 전체가 롤백된다
    # (P3-32 실 PG 실측 · 회귀 동결 = tests/backend/whs/test_path_promotion_integration.py).
    if plan.planned:
        await session.flush()
    # 단계(problem_step additive) — schema↔db seam(from_schema) 경유·검증 통과분만.
    for planned in plan.planned:
        for step_schema in planned.step_schemas:
            session.add(ProblemStep.from_schema(step_schema))
    if any(planned.step_schemas for planned in plan.planned):
        await session.flush()
    return plan


# CLI 주입 좌석 — apply 여부를 받아 승격을 수행(기본 실 DB·테스트는 가짜 주입).
PromoteFn = Callable[[bool], Coroutine[Any, Any, PromotionPlan]]


async def _default_promote(
    apply: bool,
) -> PromotionPlan:  # pragma: no cover — 실 DB(integration)
    """기본 승격 실행 — 세션 1개로 계획·적재 후 apply면 commit, 아니면 rollback(dry-run)."""
    async with get_sessionmaker()() as session:
        plan = await promote_verified_solutions(session)
        if apply:
            await session.commit()
        else:
            await session.rollback()
        return plan


def main(argv: list[str] | None = None, *, promote_fn: PromoteFn = _default_promote) -> int:
    """CLI 엔트리 — 검수 큐 JSONL을 stdout에, 승격 카운트 리포트를 stderr에 낸다(멱등).

    기본은 **dry-run**(계획·검증·리포트만 — rollback으로 미적재), `--apply`일 때만 commit.
    종료 코드 0(승격 0건도 정상 — 빈 큐·정직 리포트). `promote_fn`은 테스트 주입 좌석.
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.whs.path_promotion",
        description=(
            "WH-S 검증 풀이(평문 JSONB) → SolutionPath 구조 승격(S4-09·D1). "
            "stdout=검수 큐 JSONL·stderr=승격 카운트 리포트. 기본 dry-run, --apply로 적재."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제 적재(commit). 미지정 시 dry-run(계획·검증·리포트만·rollback).",
    )
    args = parser.parse_args(argv)

    plan = asyncio.run(promote_fn(args.apply))

    for entry in plan.queue_entries:
        print(json.dumps(entry, ensure_ascii=False))
    summary = {"mode": "apply" if args.apply else "dry-run", **plan.report.summary()}
    print(json.dumps(summary, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트, main이 테스트 대상
    sys.exit(main())
