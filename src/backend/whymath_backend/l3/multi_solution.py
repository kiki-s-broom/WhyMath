"""다중 풀이 생성 파이프라인 — `multi_solution_gen.md` 프롬프트의 **첫 소비처** (S4-10·D2).

설계 정본: `docs/architecture/solution_module_gap_review.md` §3 D2("전략 탐색→전략별 풀이→검증을
'라우터 경유 생성 → SymPy 전건 검증 → 통과분만 뱅크'로 실행화")·`docs/prompts/multi_solution_gen.md`
(프롬프트 정본 — 접근 카테고리는 `ApproachType` 6종과 1:1 정합·S4-10). ROADMAP:67 "SolutionPath
다중 풀이" 체크박스의 실행화. **오프라인 콘텐츠 공장 축** — 학생 대면 노출("본인 풀이 후 대안")은
§4-⑥ 유보이며, 이 모듈은 학생 대면 서빙 결선을 하나도 만들지 않는다(LLM 응답 직접 노출 코드 0).

흐름(문제 1건):
  시드(문제 발문 + canonical 정답) → 프롬프트 어셈블 → **라우터 경유** 생성(`Router().route()` →
  `provider.generate` — 직접 provider 구성 호출 금지 계약·CLAUDE.md) → JSON 방어 파싱(실패는
  카운트·로그) → 후보 풀이별 검증:
    ① **최종답 SymPy 동치** — `l3/verify_answer.verify_answer` 재사용: canonical 정답값을 조건
       (`wm_ans_i = (정답)`)으로, 생성 답을 치환맵으로 넣어 잔차 검산(수치·고정 시드 샘플링 —
       파라미터 답도 커버). 시드가 검증된 코퍼스(canonical 정답 보유)라 "조건 대입"보다 강한
       판정이다(다근 문제에서 조건만 만족하는 *다른* 근을 걸러낸다).
    ② **단계 검증** — `l3/verify_solution.verify_solution`(→`verify_step`) 재사용: 인접 전이 연쇄
       검증. incorrect 전이 존재 → 거부. unverifiable 전이(산문 스텝 등 — S2-k 실측상 다수)는
       거부하지 않되 해당 스텝 `sympy_verified=False`로 **정직 기록**(과잉 주장 금지).
  → **전건 통과분만**(①pass AND ②incorrect 0) `l3.SolutionPath` Pydantic 구성 → 뱅크 적재.

뱅크 적재(S4-09 promotion과 같은 적재 경로 — 같은 테이블·같은 결정론 ID 체계·같은 write 형상):
  - `verified_solutions` — 풀이 본문 자산(§2.4 "다중 풀이 다양성 자체가 자산"·문제당 N행 허용).
    `solution_path` JSONB는 FinalizeAction 계약 형상(`{conditions, answer, steps}`) 그대로,
    `strategy_tag`에는 **`ApproachType` enum 값**을 기록한다(acceptance — 자유 텍스트 승격).
    grade는 §4 판정 규칙을 정직 적용: 전 전이 correct+답 pass → `verified` / 답 pass인데 일부
    전이 unverifiable → `unverified`(격리 — R-S2상 자기진화 학습에서 자동 배제. 뱅크 게이트와
    등급은 별개 축: 뱅크는 "SymPy가 거짓을 증명하지 못했고 답은 증명됨", verified 등급은 "전
    단계가 결정론 증명됨"). 이 등급 규칙은 `whs/verdict.final_verdict`(§4)와 동일하며 드리프트는
    테스트가 동결한다(l3→whs 상향 import 회피 — 코어 계층을 하네스 의존에서 자유롭게 유지).
  - `solution_paths` 헤더 — `solution_path_id = "sp-{verified_solutions.id}"`(promotion과 동일
    체계 — `whs/path_promotion.solution_path_id_for`와 형식 일치를 테스트로 동결). 같은 체계라
    후속 promotion 재실행이 이 행들을 `already_promoted`로 자연 스킵한다(이중 헤더 0). 문제당
    N경로 허용(S4-10 재론 — `path_promotion` 모듈 docstring 근거).
  - `problem_step` 단계 — **대표 1경로만**(UNIQUE(problem_id, step_order) 불변·재론 확정):
    단계 좌석이 빈 문제의 첫 뱅크 경로가 대표가 되어 스텝 행을 실체화하고(스텝별
    `sympy_verified`는 실측 전이 판정 그대로 — S4-09의 일괄 승계와 달리 전이별 실값), 추가
    경로·레거시 선점 문제는 헤더만 적재한다.
  - `gen_meta`(solution_paths JSONB 1컬럼) — 주관 메타(elegance·educational_value·difficulty·
    key_insight·comparison)를 `review_status="ai_estimated"`와 함께 저장만 한다. **학생 대면
    노출 경로 0**(api/ 소스가 gen_meta를 참조하지 않음을 거버넌스 테스트로 동결·§4-⑥ 유보).
    comparison은 응답(문제) 단위 텍스트라 같은 배치의 각 경로에 동일 기록한다(별도 테이블
    신설 회피 — 좌석 최소).
  - 개념 매칭(`concept_node_id`·`concept_sequence`)은 **미시도** — 별도 호출지점 ④(match)의
    소비처가 서는 후속 몫이라 NULL/빈 배열 + 사람 검수 큐로 정직 처리(날조 금지·S4-09 동일).
  - 멱등: 적재 전 같은 문제의 기존 `verified_solutions.solution_path`와 **내용 지문**(정렬 키
    canonical JSON sha256 — `whs/solution_bank.solution_fingerprint`와 동일 알고리즘·테스트
    동결)을 대조해 동일 내용 재실행을 스킵한다(`duplicates_skipped`).

검증 실패 뱅크 유입 0(acceptance 동결): ① 답 fail ② 답 unverifiable(판정 불가 — pass로 위장
금지) ③ incorrect 전이 존재 후보는 **어느 테이블에도 적재하지 않는다**(테스트가 실패 주입으로
동결). `failed`는 `WhsSolutionGrade`에 애초에 없어(enum 구조 차단·R-S2) 구조적으로도 막힌다.

관측(CLAUDE.md "모든 LLM 호출 → Langfuse 추적"): 생성 1건마다 라우팅 결정+실측 usage를
`langfuse_fields`로 sink에 기록한다(`LLMEquivalentProblemGenerator._record_trace` 동형 —
never-break·예외 *타입명*만 경고). 키 미설정 환경에서는 sink가 no-op(네트워크 0·hermetic).

실행 표면(ops CLI — `whs/path_promotion` 컨벤션 미러):
    python -m whymath_backend.l3.multi_solution --seed-scope verified --limit 5        # dry-run
    python -m whymath_backend.l3.multi_solution --seed-scope verified --limit 5 --apply  # 적재
    python -m whymath_backend.l3.multi_solution --seed-scope verified --fake-provider   # 대체 실행
stdout = 사람 검수 큐 JSONL(뱅크 경로 1건/줄 — ai_estimated 메타·개념 매칭·verified_by_human
검수 대상), stderr = 실측 리포트 JSON 한 줄(시도 수·생성률·검증 통과율·approach 다양성 분포·
뱅크 적재 수·ai_estimated 건수 — 정직 회계·0/0은 None).

provider 정직성(2026-07-29 오케스트레이터 실측 방침):
  - **기본은 라이브**(CompositeProvider: Ollama 로컬 + Anthropic 클라우드 — 라우터 결정에 따름.
    기본 구독 free라 사실상 LOCAL 전용·0원). 라이브 도달 불가는 침묵 폴백하지 않고 호출별
    `provider_errors`로 카운트하며 **예외 타입명**을 failures·로그에 남긴다. 전 호출이 provider
    오류면 exit 1 — "측정 실패"가 "0건 통과"로 위장되지 않게 한다(CLAUDE.md 이중 회계 금기).
  - `--fake-provider`는 **명시 플래그로만** 결정론 가짜(`DeterministicFakeProvider`)를 쓴다 —
    조용히 기본이 되지 않는다. 가짜는 시드의 canonical 정답을 되먹인 응답이라 그 수치는
    **파이프라인 무결성 지표이지 풀이 능력·실 생성률이 아니다**(S2-02 자기답 되먹임 순환성
    정직 고지 선례) — 리포트 `fake_disclosure`에 같은 고지를 항상 동반한다.

범위 밖(후속): 학생 대면 노출·비교 UI(§4-⑥)·동치 군집(S4-12·D4)·개념 ID 매칭 결선(호출지점 ④)·
Wolfram 등 추가 도구 검증. 7계층 경계: 본 모듈은 L3 안에서 완결한다(L4/L5 import 0·결선 0).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
import uuid
from collections.abc import Callable, Coroutine, Mapping, Sequence
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
from whymath_backend.l3.data_grade_defaults import SELF_AUTHORED_CORPUS
from whymath_backend.l3.interfaces import LLMProvider, TraceSink
from whymath_backend.l3.models import (
    CostTier,
    GenerationResult,
    RoutingDecision,
    RoutingRequest,
    Usage,
)
from whymath_backend.l3.router import (
    Router,
    _as_cost_tier,
    actual_cost_krw,
    langfuse_fields,
)
from whymath_backend.l3.solution_path import (
    ApproachType,
    SolutionPath,
    parse_approach_label,
)
from whymath_backend.l3.verify_answer import AnswerVerdict, verify_answer
from whymath_backend.l3.verify_solution import (
    SolutionVerificationResult,
    verify_solution,
)
from whymath_backend.l3.verify_step import VerifyStepState
from whymath_backend.schema.problem import ProblemStep as ProblemStepSchema

__all__ = [
    "BankCandidate",
    "DeterministicFakeProvider",
    "MultiSolutionReport",
    "RunConfig",
    "RunOutcome",
    "SeedProblem",
    "answer_equivalence_verdict",
    "bank_candidates",
    "build_generated_path",
    "content_fingerprint",
    "evaluate_response",
    "extract_json",
    "generate_candidates",
    "generated_path_id",
    "generation_routing_request",
    "load_seeds",
    "main",
]

_LOGGER = logging.getLogger("whymath.l3.multi_solution")

# 검수 큐 레코드 식별 키 — 다른 큐/로더 형식과 *일부러* 다르다(자동 적재 차단 —
# `path_promotion._QUEUE_KIND` 선례 동형). 검수 대상: ai_estimated 메타·개념 매칭·
# verified_by_human(사람 검수 통과 여부).
_QUEUE_KIND = "multi_solution_generation_review"

# ai_estimated 게이팅 값 — gen_meta 내부에 항상 동반(학생 노출 전 사람 검수 필수 표식).
AI_ESTIMATED = "ai_estimated"

# 최종답 동치 검산용 내부 심볼 접두사 — `wm_ans_{i} = (canonical)` 조건에 생성 답을 치환한다.
# 시드/생성 값에 이 접두사가 등장하면(사실상 불가능·방어) 충돌로 보고 unverifiable 처리.
_ANS_SYM_PREFIX = "wm_ans_"

# 난이도 허용값(주관 메타) — 프롬프트 스펙과 1:1. 밖의 값은 저장하지 않는다(오염 방지).
_META_DIFFICULTIES: frozenset[str] = frozenset({"easy", "medium", "hard"})

# ──────────────────────────────────────────────────────────────────────────
# 시스템 프롬프트 — `docs/prompts/multi_solution_gen.md`(정본)의 오프라인 공장 인스턴스.
# 학생 풀이 슬롯은 없다(사전 생성 — "본인 풀이 후 대안" 노출 원칙은 서빙 시점 몫·§4-⑥ 유보).
# ──────────────────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """당신은 한국 중·고 수학 문제 풀이 다양화 전문가입니다.

[목표]
주어진 문제를 *서로 다른 접근* 2~3개로 풀어 JSON 하나로만 출력하세요. 각 풀이는:
1. 서로 다른 *발상·전략* 사용
2. 학생 수준에 맞는 *교육적 가치*
3. 단계별로 *명확하게* 설명

[접근 카테고리 — 아래 6종의 영문 키만 사용, 가능한 2~3개 선택]
- algebraic (대수적): 방정식·식 변형
- geometric (기하적): 그림·도형·좌표
- combinatorial (조합적): 경우의 수·열거
- inductive (귀납적): 작은 사례·패턴
- visual (시각적): 그림·다이어그램으로 통찰
- backward (역방향): 결론에서 거꾸로

[응답 형식 — JSON 객체 하나만 (코드펜스·설명 없이)]
{
  "solutions": [
    {
      "approach": "algebraic",
      "key_insight": "핵심 발상 한 줄",
      "steps": ["단계 1", "단계 2", "단계 3"],
      "final_answer": "4",
      "educational_value": "이 접근이 가르치는 것",
      "difficulty": "easy",
      "elegance": 3
    }
  ],
  "comparison": "각 접근의 장단점 비교"
}

[원칙]
- approach는 위 6종 영문 키만 (한글 라벨 금지).
- final_answer는 반드시 *정확값*(정수 3, 분수 4/3, 무리수 sqrt(2) — SymPy 표기). 반올림 소수 금지.
- 수식은 SymPy 표기(`**`=거듭제곱·`*`=곱)로. LaTeX 백슬래시 금지(JSON이 깨집니다).
- 모든 풀이는 같은 최종 답에 도달해야 합니다(답이 다르면 그 풀이는 틀린 것).
- 첫 풀이는 *가장 직관적*, 후속 풀이는 *더 우아하거나 다른 발상*.
"""

# ──────────────────────────────────────────────────────────────────────────
# 출력 JSON 스키마(S2-j structured output 선례) — LOCAL(Ollama) 결정일 때 format= 제약
# 디코딩으로 형식을 문법 강제한다. 클라우드 경로는 프롬프트+방어 파서만(스키마 미지원 계약).
# 형식만 보장 — 내용의 수학적 진실은 하류 SymPy 검증이 판정한다(이중 방어).
# ──────────────────────────────────────────────────────────────────────────
_OUTPUT_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "solutions": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "approach": {
                        "type": "string",
                        "enum": [member.value for member in ApproachType],
                    },
                    "key_insight": {"type": "string"},
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "final_answer": {"type": "string"},
                    "educational_value": {"type": "string"},
                    "difficulty": {
                        "type": "string",
                        "enum": sorted(_META_DIFFICULTIES),
                    },
                    "elegance": {"type": "number", "minimum": 1, "maximum": 5},
                },
                "required": ["approach", "steps", "final_answer"],
            },
        },
        "comparison": {"type": "string"},
    },
    "required": ["solutions"],
}

# 유효하지 않은 JSON 백슬래시 이스케이프(LaTeX 등) — `llm_generator._INVALID_JSON_ESCAPE` 미러.
_INVALID_JSON_ESCAPE = re.compile(r'\\(?!["\\/bfnrtu])')


# ──────────────────────────────────────────────────────────────────────────
# 시드·후보·리포트 자료형
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SeedProblem:
    """생성 대상 시드 1건 — 문제 발문 + canonical 정답(검증 앵커).

    `conditions`·`answer_map`은 검증된 코퍼스(`verified_solutions` VERIFIED 행의
    `solution_path` JSONB `{conditions, answer}`)에서 온다 — 최종답 동치 판정의 앵커이자
    뱅크 payload의 조건 보존 좌석. 발문(`question_text`)은 problem 코퍼스에서 조인한다.
    """

    problem_id: uuid.UUID
    question_text: str
    conditions: tuple[str, ...]
    answer_map: Mapping[str, str]


@dataclass(frozen=True)
class BankCandidate:
    """검증 전건 통과·적재 대기 후보 1건 — `bank_candidates`의 입력 단위.

    `path`는 placeholder ID(`sp-pending`)로 invariant 검증을 마친 Pydantic 모델이다 —
    실제 ID(`sp-{verified_solutions.id}`)는 vs 행 flush 후에야 결정되므로 적재 시점에
    `model_copy(update=...)`로 치환한다(재검증 불요 — ID는 invariant 대상이 아님).
    `grade`는 §4 규칙 정직 적용(모듈 docstring — final_verdict와 드리프트 동결 테스트).
    """

    seed: SeedProblem
    approach: ApproachType
    steps: tuple[str, ...]
    step_flags: tuple[bool, ...]  # 스텝별 sympy_verified — 실측 전이 판정(첫 스텝 False)
    final_answer_map: Mapping[str, str]
    grade: WhsSolutionGrade
    gen_meta: Mapping[str, Any]
    path: SolutionPath
    fingerprint: str


@dataclass
class MultiSolutionReport:
    """생성·검증·적재 배치 정직 회계 — 수치 전부 실측·조용한 생략 0(`PromotionReport` 선례).

    `failures`는 사람 가독 사유(예외 *타입명* 포함 — 침묵 실패 금지). 다양성 분포는
    `approach_distribution`(전역)·`problem_distinct_approaches`(문제→상이 approach 수)로
    집계해 summary가 "문제당 상이 approach 수" 히스토그램을 낸다(acceptance 실측 리포트).
    """

    provider_kind: str = "live"  # "live" | "fake" — fake는 정직 고지 동반(모듈 docstring)
    seeds_total: int = 0  # 시드 후보 행(문제) 수
    seeds_skipped_malformed: int = 0  # conditions/answer 형식 위반 시드(스킵·사유 기록)
    seeds_skipped_no_question: int = 0  # 발문 없는 문제(메타 전용 출처 등 — 프롬프트 불가)
    problems_attempted: int = 0  # 생성 시도 문제 수
    generation_calls: int = 0  # LLM 호출 수(문제당 1)
    provider_errors: int = 0  # provider 예외(라이브 도달 불가 등 — 타입명 기록)
    parse_failures: int = 0  # 응답 JSON 파싱 실패
    candidates_total: int = 0  # 파싱된 후보 풀이 수
    approach_invalid: int = 0  # approach 6종 밖(폐쇄집합 거부)
    duplicate_approach: int = 0  # 같은 응답 안 중복 approach(첫 후보만 채택)
    steps_invalid: int = 0  # steps 결측·형식 위반
    final_answer_invalid: int = 0  # final_answer 결측·형식 위반
    answer_failed: int = 0  # 최종답 SymPy 동치 fail(오답 — 뱅크 유입 0)
    answer_unverifiable: int = 0  # 최종답 판정 불가(pass 위장 금지 — 뱅크 유입 0)
    step_incorrect: int = 0  # incorrect 전이 존재(틀린 과정 — 뱅크 유입 0)
    pydantic_rejected: int = 0  # SolutionPath invariant 위반(방어적)
    verified_pass: int = 0  # 전건 통과(뱅크 대상) 후보 수
    duplicates_skipped: int = 0  # 멱등 재실행 내용 지문 일치 스킵
    banked_paths: int = 0  # solution_paths 헤더 적재 수
    banked_verified: int = 0  # 그중 grade=verified(전 전이 correct)
    banked_unverified: int = 0  # 그중 grade=unverified(일부 전이 unverifiable — 정직)
    banked_steps_rows: int = 0  # problem_step 적재 행 수(대표 경로)
    banked_header_only: int = 0  # 단계 좌석 선점으로 헤더만 적재
    ai_estimated_meta: int = 0  # gen_meta(review_status=ai_estimated) 기록 수
    approach_distribution: dict[str, int] = field(default_factory=dict)
    problem_distinct_approaches: dict[str, set[str]] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def note_banked_approach(self, problem_id: uuid.UUID, approach: ApproachType) -> None:
        """뱅크된 경로의 approach 다양성 집계(전역 분포 + 문제별 상이 approach 집합)."""
        self.approach_distribution[approach.value] = (
            self.approach_distribution.get(approach.value, 0) + 1
        )
        self.problem_distinct_approaches.setdefault(str(problem_id), set()).add(approach.value)

    def summary(self) -> dict[str, Any]:
        """리포트 JSON — 카운트 + 비율(생성률·검증 통과율·다양성 분포). 0/0은 None(위장 금지)."""
        parsed_ok = self.generation_calls - self.provider_errors - self.parse_failures
        # 문제당 상이 approach 수 히스토그램 — {"1": n문제, "2": m문제, ...}.
        diversity_histogram: dict[str, int] = {}
        for approaches in self.problem_distinct_approaches.values():
            key = str(len(approaches))
            diversity_histogram[key] = diversity_histogram.get(key, 0) + 1
        summary: dict[str, Any] = {
            "provider": self.provider_kind,
            "seeds_total": self.seeds_total,
            "seeds_skipped_malformed": self.seeds_skipped_malformed,
            "seeds_skipped_no_question": self.seeds_skipped_no_question,
            "problems_attempted": self.problems_attempted,
            "generation_calls": self.generation_calls,
            "provider_errors": self.provider_errors,
            "parse_failures": self.parse_failures,
            "candidates_total": self.candidates_total,
            "approach_invalid": self.approach_invalid,
            "duplicate_approach": self.duplicate_approach,
            "steps_invalid": self.steps_invalid,
            "final_answer_invalid": self.final_answer_invalid,
            "answer_failed": self.answer_failed,
            "answer_unverifiable": self.answer_unverifiable,
            "step_incorrect": self.step_incorrect,
            "pydantic_rejected": self.pydantic_rejected,
            "verified_pass": self.verified_pass,
            "duplicates_skipped": self.duplicates_skipped,
            "banked_paths": self.banked_paths,
            "banked_verified": self.banked_verified,
            "banked_unverified": self.banked_unverified,
            "banked_steps_rows": self.banked_steps_rows,
            "banked_header_only": self.banked_header_only,
            "ai_estimated_meta": self.ai_estimated_meta,
            # 생성률(파싱 성공) — 호출 대비 파싱 성공 응답 비율. 호출 0이면 None.
            "generation_rate": (
                round(parsed_ok / self.generation_calls, 4) if self.generation_calls else None
            ),
            # 검증 통과율 — 파싱된 후보 대비 전건 통과 비율. 후보 0이면 None.
            "verification_pass_rate": (
                round(self.verified_pass / self.candidates_total, 4)
                if self.candidates_total
                else None
            ),
            "approach_distribution": dict(sorted(self.approach_distribution.items())),
            "problems_with_multi_approach": sum(
                1
                for approaches in self.problem_distinct_approaches.values()
                if len(approaches) >= 2
            ),
            "distinct_approaches_per_problem": dict(sorted(diversity_histogram.items())),
            "failures": list(self.failures),
        }
        if self.provider_kind == "fake":
            # 자기답 되먹임 순환성 정직 고지(S2-02 선례) — fake 수치의 의미 한정.
            summary["fake_disclosure"] = (
                "결정론 가짜 provider — 시드의 canonical 정답을 되먹인 응답이라 이 수치는 "
                "파이프라인 무결성 지표이지 풀이 능력·실 생성률이 아니다"
            )
        return summary


# ──────────────────────────────────────────────────────────────────────────
# 순수 부품 — 파싱·검증·조립 (DB·네트워크 0)
# ──────────────────────────────────────────────────────────────────────────
def extract_json(raw: str) -> dict[str, Any] | None:
    """원시 텍스트에서 JSON 객체를 방어적으로 추출 — 코드펜스·주변 산문·LaTeX 백슬래시 허용.

    `LLMEquivalentProblemGenerator._extract_json`(S2-e·실 LLM 실측 검증) 미러 — 후보(통째로 /
    첫 `{`…마지막 `}`)를 원문·이스케이프 sanitize본 순으로 파싱 시도한다. 실패는 None(호출자가
    `parse_failures`로 카운트 — 조용한 통과 금지).
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    candidates = [text]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        for attempt in (candidate, _INVALID_JSON_ESCAPE.sub(r"\\\\", candidate)):
            try:
                obj = json.loads(attempt)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
    return None


def content_fingerprint(solution_path: dict[str, Any]) -> str:
    """풀이 payload의 내용 지문 — 정렬 키 canonical JSON sha256(멱등 재실행 dedup 키).

    `whs/solution_bank.solution_fingerprint`와 **동일 알고리즘**이다(정확 일치 dedup — 본질적
    동치는 못 잡는 한계도 동일·S4-12 몫). l3→whs 상향 import를 피하려 여기 재정의하며,
    드리프트는 테스트가 두 구현의 출력 일치로 동결한다.
    """
    canonical = json.dumps(solution_path, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def generated_path_id(verified_solution_id: uuid.UUID) -> str:
    """뱅크 경로 결정론 ID — `sp-{verified_solutions.id}`.

    `whs/path_promotion.solution_path_id_for`와 **같은 체계**(테스트로 형식 일치 동결) —
    후속 promotion 재실행이 이 행을 `already_promoted`로 자연 스킵하게 하는 열쇠다.
    """
    return f"sp-{verified_solution_id}"


def _normalize_final_answer(raw: object, known_vars: Sequence[str]) -> dict[str, str] | None:
    """응답 `final_answer` → 치환맵 정규화. 형식 위반이면 None(카운트 — 조용한 통과 금지).

    허용 형식: ① 문자열(단일 변수 시드만 — `"4"` 또는 `"x = 4"`처럼 자기 변수 등호 접두 허용)
    ② 객체 맵(`{"x": "4"}` — 키 집합이 시드 변수와 일치해야 함·불일치는 동치 판정 단계에서
    unverifiable 처리). 값은 전부 str로 강제한다(수치 리터럴 허용 — str(값)).
    """
    if isinstance(raw, dict):
        result: dict[str, str] = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not key.strip():
                return None
            if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                return None
            result[key.strip()] = str(value).strip()
        return result if result else None
    if isinstance(raw, (str, int, float)) and not isinstance(raw, bool):
        text = str(raw).strip()
        if not text or len(known_vars) != 1:
            return None  # 빈 값·다변수 시드의 단일 문자열 답은 형식 위반(변수 귀속 불명)
        if "=" in text:
            return _strip_var_prefix(text, known_vars[0])
        return {known_vars[0]: text}
    return None


def _strip_var_prefix(text: str, var: str) -> dict[str, str] | None:
    """`"x = 4"` 형태 문자열에서 자기 변수 등호 접두를 벗겨 치환맵으로 — 그 외 등호는 None."""
    lhs, _, rhs = text.partition("=")
    if lhs.strip() == var and rhs.strip() and "=" not in rhs:
        return {var: rhs.strip()}
    return None


def answer_equivalence_verdict(
    known: Mapping[str, str], generated: Mapping[str, str]
) -> AnswerVerdict:
    """최종답 SymPy 동치 판정 — canonical 정답 ↔ 생성 답을 `verify_answer` 잔차 검산으로.

    변수별 조건 `wm_ans_i = (canonical_i)`에 생성 값을 `wm_ans_i`로 치환해 잔차 0을 본다 —
    `l3/verify_answer` **재사용**(수치 평가 + 자유변수 고정 시드 샘플링이라 파라미터 정답도
    커버·정직성 3상태 상속). 변수 집합 불일치·내부 심볼 충돌은 unverifiable(보수 — pass 위장
    금지·뱅크 유입 0 축).
    """
    if set(known) != set(generated):
        return AnswerVerdict(
            state="unverifiable",
            reason="최종답 변수 집합 불일치 — 동치 판정 불가·안전 회피",
            samples_checked=0,
        )
    values = list(known.values()) + list(generated.values())
    if any(_ANS_SYM_PREFIX in value for value in values):
        return AnswerVerdict(
            state="unverifiable",
            reason="내부 검산 심볼 충돌 — 동치 판정 불가·안전 회피",
            samples_checked=0,
        )
    conditions: list[str] = []
    substitution: dict[str, str] = {}
    for index, var in enumerate(sorted(known)):
        symbol = f"{_ANS_SYM_PREFIX}{index}"
        conditions.append(f"{symbol} = ({known[var]})")
        substitution[symbol] = generated[var]
    return verify_answer(conditions, substitution)


def build_generated_path(
    *,
    solution_path_id: str,
    problem_id: uuid.UUID,
    approach: ApproachType,
    steps: Sequence[str],
    step_flags: Sequence[bool],
    created_at: datetime,
) -> SolutionPath:
    """검증 통과 후보 → `l3.SolutionPath`(Pydantic invariant 전건). 위반은 ValidationError.

    스텝 구성(정직 — `path_promotion.build_solution_path`와 형상 동형·플래그만 실측):
      - `sympy_verified`: **전이별 실측 판정**(스텝 i의 유입 전이 i-1이 correct일 때만 True·
        첫 스텝 False) — S4-09의 "verified 등급 일괄 승계"보다 세밀한 정직 기록.
      - `concept_node_id`/`reasoning_type`/`justification`: None(매칭·태깅 미시도 — 날조 금지).
      - `concept_sequence`: 빈 배열(매칭 확정분만 담는 좌석).
    """
    return SolutionPath.model_validate(
        {
            "solution_path_id": solution_path_id,
            "problem_id": str(problem_id),
            "approach_type": approach.value,
            "concept_sequence": [],
            "steps": [
                {"order": index, "content": content, "sympy_verified": flag}
                for index, (content, flag) in enumerate(
                    zip(steps, step_flags, strict=True), start=1
                )
            ],
            "verified_by_human": False,  # 적재 직후 항상 미검수(AI 자기승인 금지)
            "equivalence_cluster_id": None,  # 군집 부여는 S4-12(D4) 몫
            "created_at": created_at,
        }
    )


def _step_flags(steps_result: SolutionVerificationResult, n_steps: int) -> tuple[bool, ...]:
    """전이 판정 → 스텝별 sympy_verified 플래그(첫 스텝 False·스텝 i는 유입 전이 판정).

    전이 j(steps[j]→steps[j+1])가 correct면 스텝 j+1이 True다 — "검증된 것은 직전 스텝→이
    스텝 전이"라는 S4-09 정직 승계 의미를 전이별 실값으로 구현한다.
    """
    flags = [False] * n_steps
    for index, result in enumerate(steps_result.steps):
        flags[index + 1] = result.state == VerifyStepState.correct
    return tuple(flags)


def _bank_grade(
    answer: AnswerVerdict, steps_result: SolutionVerificationResult
) -> WhsSolutionGrade | None:
    """뱅크 게이트 + 등급 — §4 판정 규칙(`whs/verdict.final_verdict`)의 뱅크 제한 적용.

    None = **뱅크 유입 금지**(답 fail/unverifiable 또는 incorrect 전이 — acceptance "검증 실패
    뱅크 유입 0"·판정 불가도 pass로 위장하지 않는다). 등급은 §4 그대로: 전 전이 correct →
    verified / 일부 unverifiable → unverified(격리 — 학습 배제·R-S2). failed는
    `WhsSolutionGrade`에 없어 구조적으로도 적재 불가. 드리프트는 final_verdict 대조 테스트가
    동결한다(l3→whs 상향 import 회피 근거는 모듈 docstring).
    """
    if answer.state != "pass" or steps_result.has_incorrect:
        return None
    if steps_result.n_unverifiable == 0:
        return WhsSolutionGrade.VERIFIED
    return WhsSolutionGrade.UNVERIFIED


def _clean_meta_str(value: object) -> str | None:
    """주관 메타 문자열 필드 정리 — 비문자열·빈 값은 None(저장 생략)."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _build_gen_meta(raw: Mapping[str, Any], comparison: str | None) -> dict[str, Any]:
    """주관 메타 조립 — `review_status="ai_estimated"` 항상 동반(학생 노출 게이팅 표식).

    허용 밖 값(difficulty 3종 밖·elegance 범위 밖·비문자열)은 **버린다**(자유 텍스트 오염
    방지 — 없는 값을 지어내지도, 이상값을 눙치지도 않는다). comparison은 응답(문제) 단위
    텍스트를 각 경로에 동일 기록한다(모듈 docstring — 좌석 최소).
    """
    meta: dict[str, Any] = {"review_status": AI_ESTIMATED}
    key_insight = _clean_meta_str(raw.get("key_insight"))
    if key_insight is not None:
        meta["key_insight"] = key_insight
    educational_value = _clean_meta_str(raw.get("educational_value"))
    if educational_value is not None:
        meta["educational_value"] = educational_value
    difficulty = _clean_meta_str(raw.get("difficulty"))
    if difficulty is not None and difficulty in _META_DIFFICULTIES:
        meta["difficulty"] = difficulty
    elegance = raw.get("elegance")
    if isinstance(elegance, (int, float)) and not isinstance(elegance, bool):
        value = int(round(float(elegance)))
        if 1 <= value <= 5:
            meta["elegance"] = value
    if comparison is not None:
        meta["comparison"] = comparison
    return meta


def evaluate_response(
    seed: SeedProblem,
    data: Mapping[str, Any],
    *,
    now: datetime,
    report: MultiSolutionReport,
) -> list[BankCandidate]:
    """파싱된 응답 1건의 후보 풀이 전건을 검증해 **통과분만** BankCandidate로 — 순수·결정론.

    후보별 판정 순서(각 거부는 리포트 카운트 — 조용한 통과 금지):
      approach 폐쇄 6종 → 응답 내 중복 approach(첫 후보만) → steps 형식 → final_answer 형식
      → ① 최종답 SymPy 동치(fail/unverifiable 거부) → ② 단계 검증(incorrect 거부·unverifiable
      정직 플래그) → SolutionPath Pydantic invariant → 통과.
    """
    solutions = data.get("solutions")
    comparison = _clean_meta_str(data.get("comparison"))
    if not isinstance(solutions, list):
        report.parse_failures += 1
        report.failures.append(f"parse_failure problem={seed.problem_id}: solutions 배열 결측")
        return []

    known_vars = sorted(seed.answer_map)
    seen_approaches: set[str] = set()
    banked: list[BankCandidate] = []
    for raw in solutions:
        if not isinstance(raw, dict):
            report.candidates_total += 1
            report.steps_invalid += 1
            continue
        report.candidates_total += 1

        # ── approach: 폐쇄 6종 — 밖이면 거부(추측 금지·한글 라벨은 단일 번역표만 허용). ──
        approach_raw = raw.get("approach")
        approach = parse_approach_label(approach_raw if isinstance(approach_raw, str) else None)
        if approach is None:
            report.approach_invalid += 1
            continue
        # ── 같은 응답 안 중복 approach — 다양성 자산 취지상 첫 후보만 채택. ──
        if approach.value in seen_approaches:
            report.duplicate_approach += 1
            continue

        # ── steps: 비어있지 않은 문자열 리스트만. ──
        steps_raw = raw.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            report.steps_invalid += 1
            continue
        steps = tuple(str(step).strip() for step in steps_raw if isinstance(step, str))
        if len(steps) != len(steps_raw) or not all(steps):
            report.steps_invalid += 1
            continue

        # ── final_answer: 치환맵 정규화(문자열/객체 — 형식 위반 거부). ──
        final_answer = _normalize_final_answer(raw.get("final_answer"), known_vars)
        if final_answer is None:
            report.final_answer_invalid += 1
            continue

        # ── ① 최종답 SymPy 동치 — fail/unverifiable 모두 뱅크 유입 금지(정직 분리 카운트). ──
        answer_verdict = answer_equivalence_verdict(seed.answer_map, final_answer)
        # ── ② 단계 검증 — incorrect 거부·unverifiable 정직 플래그(verify_solution 재사용). ──
        steps_result = verify_solution(list(steps))
        grade = _bank_grade(answer_verdict, steps_result)
        if grade is None:
            if answer_verdict.state == "fail":
                report.answer_failed += 1
            elif answer_verdict.state == "unverifiable":
                report.answer_unverifiable += 1
            else:  # 답은 pass인데 incorrect 전이(틀린 과정 — 답 무관 차단·§4 이중 체크)
                report.step_incorrect += 1
            continue

        # ── SolutionPath Pydantic invariant(placeholder ID — 실제 ID는 적재 시 치환). ──
        step_flags = _step_flags(steps_result, len(steps))
        try:
            path = build_generated_path(
                solution_path_id="sp-pending",
                problem_id=seed.problem_id,
                approach=approach,
                steps=steps,
                step_flags=step_flags,
                created_at=now,
            )
        except ValidationError as exc:
            report.pydantic_rejected += 1
            report.failures.append(
                f"pydantic_rejected problem={seed.problem_id}: "
                f"{type(exc).__name__}: {str(exc)[:300]}"
            )
            continue

        seen_approaches.add(approach.value)
        report.verified_pass += 1
        payload = _solution_payload(seed, final_answer, steps)
        banked.append(
            BankCandidate(
                seed=seed,
                approach=approach,
                steps=steps,
                step_flags=step_flags,
                final_answer_map=final_answer,
                grade=grade,
                gen_meta=_build_gen_meta(raw, comparison),
                path=path,
                fingerprint=content_fingerprint(payload),
            )
        )
    return banked


def _solution_payload(
    seed: SeedProblem, final_answer: Mapping[str, str], steps: Sequence[str]
) -> dict[str, Any]:
    """`verified_solutions.solution_path` JSONB payload — FinalizeAction 계약 형상 그대로.

    `{conditions, answer, steps}` — `path_promotion.extract_plain_steps`가 그대로 읽을 수
    있는 형상(적재 경로 호환). answer는 *검증 통과한 생성 답*(canonical과 SymPy 동치 확인됨).
    """
    return {
        "conditions": list(seed.conditions),
        "answer": dict(final_answer),
        "steps": list(steps),
    }


# ──────────────────────────────────────────────────────────────────────────
# 라우팅·생성 (라우터 경유 — 직접 provider 호출 금지)
# ──────────────────────────────────────────────────────────────────────────
def generation_routing_request(subscription: str = "free") -> RoutingRequest:
    """다중 풀이 생성 호출의 라우팅 신호 — task_type='generate'·동기·추론 필요.

    기본 구독 free → 라우터가 LOCAL 강제(Phaiakes9 0원·클라우드 승급 없음 — 로컬 우선).
    sync=True + difficulty=medium이라 라우터 규칙 8이 LOCAL/MATH/MID로 귀결한다(풀이 생성은
    수학 태스크 — 저작 특화 GENERAL 전환은 동등문제 *발문 저작* 축의 선례이고, 여기는 *풀이*
    생성이라 MATH 패밀리가 맞다). QUALITY 비동기 경로를 타지 않아 큐 없이 CLI 완결.
    """
    return RoutingRequest(
        task_type="generate",
        difficulty="medium",
        requires_reasoning=True,
        student_subscription=subscription,
        sync=True,
        # 등급: 다중 풀이 생성의 입력 시드는 자체 저작 코퍼스의 문항이다(오프라인 공장 —
        # 학생 자료 없음). 코퍼스에 AIHub 유래가 들어오면 단일 좌석에서 함께 잠긴다.
        data_licenses=SELF_AUTHORED_CORPUS,
    )


def _record_trace(trace: TraceSink, decision: RoutingDecision, usage: Usage | None) -> None:
    """생성 1건의 라우팅·실측을 sink에 기록 — never-break(배치 비차단·타입명만 경고).

    비용 회계는 `pipeline.generate` 동형: usage 없음·클라우드 토큰 미상이면 None('미상'과
    0원 구분 — 지어내지 않음). 오프라인 공장이라 student_id_hash 없음.
    """
    actual_krw: float | None
    is_cloud = _as_cost_tier(decision.cost_tier) is not CostTier.LOCAL
    if usage is None:
        actual_krw = None
    elif is_cloud and (usage.input_tokens is None or usage.output_tokens is None):
        actual_krw = None
    else:
        actual_krw = actual_cost_krw(decision, usage)
    try:
        trace.record(langfuse_fields(decision, cache_hit=False, usage=usage, cost_krw=actual_krw))
    except Exception as exc:  # noqa: BLE001 — 관측 장애가 생성 배치를 깨면 안 됨
        # 침묵실패 금지 — 예외 *타입명*만 경고(필드·키 값 미출력·langfuse_sink 방침 동형).
        _LOGGER.warning("다중 풀이 생성 관측 기록 실패(%s) — 무시하고 계속", type(exc).__name__)


def _flush_trace(trace: TraceSink) -> None:
    """배치 종료 시 관측 전송 확정 — flush 없는 sink(테스트 대역)는 조용히 통과(duck-typing)."""
    flush = getattr(trace, "flush", None)
    if not callable(flush):
        return
    try:
        flush()
    except Exception as exc:  # noqa: BLE001 — 전송 확정 실패가 배치 결과를 깨면 안 됨
        _LOGGER.warning("다중 풀이 생성 관측 flush 실패(%s) — 무시하고 계속", type(exc).__name__)


def _build_user_prompt(seed: SeedProblem) -> str:
    """사용자 프롬프트 — 문제 발문만 싣는다(Minimal context·플레이북 Part 8).

    canonical 정답·조건은 **싣지 않는다** — 모델이 실제로 풀어야 하고(결론 되먹임 방지),
    정오는 하류 SymPy 검증이 판정한다(정직한 콘텐츠 공장). 발문은 자체생성 코퍼스
    문항이다(저작권 게이트를 통과한 자산 — 외부 본문 아님).
    """
    return (
        "다음 문제를 서로 다른 접근 2~3개로 풀어 JSON 하나로만 출력하세요.\n\n"
        f"[문제]\n{seed.question_text}"
    )


async def generate_candidates(
    seeds: Sequence[SeedProblem],
    provider: LLMProvider,
    *,
    trace: TraceSink,
    report: MultiSolutionReport,
    subscription: str = "free",
    temperature: float | None = None,
    now: datetime | None = None,
) -> list[BankCandidate]:
    """시드 전건 생성·검증 — 라우터 경유 호출 + 응답 파싱 + 전건 검증(통과분만 반환).

    provider 예외는 **삼키지 않고 카운트**한다(호출별 `provider_errors` + 예외 타입명 기록 —
    라이브 도달 불가의 침묵 폴백 금지). JSON 스키마는 LOCAL 결정일 때만 싣는다(Ollama
    format= 제약 디코딩 — 클라우드는 방어 파서만·S2-j 이중 방어 동형).
    """
    decided_at = now if now is not None else datetime.now(tz=UTC)
    decision = Router().route(generation_routing_request(subscription))
    is_local = decision.cost_tier == CostTier.LOCAL.value
    schema = _OUTPUT_JSON_SCHEMA if is_local else None

    banked: list[BankCandidate] = []
    for seed in seeds:
        report.problems_attempted += 1
        report.generation_calls += 1
        prompt = _build_user_prompt(seed)
        try:
            generated: GenerationResult = await provider.generate(
                prompt,
                _SYSTEM_PROMPT,
                decision,
                temperature=temperature,
                json_schema=schema,
            )
        except Exception as exc:  # noqa: BLE001 — 도달 불가를 정직 카운트(전멸 시 exit 1)
            report.provider_errors += 1
            report.failures.append(
                f"provider_error problem={seed.problem_id}: {type(exc).__name__}: {str(exc)[:200]}"
            )
            _LOGGER.warning(
                "다중 풀이 생성 provider 호출 실패(%s) — problem=%s 스킵",
                type(exc).__name__,
                seed.problem_id,
            )
            continue
        # LLM 호출 성공 = 비용 발생 — 하류 파싱 성패와 무관하게 관측을 먼저 남긴다.
        _record_trace(trace, decision, generated.usage)
        data = extract_json(generated.text)
        if data is None:
            report.parse_failures += 1
            report.failures.append(f"parse_failure problem={seed.problem_id}: JSON 추출 실패")
            continue
        banked.extend(evaluate_response(seed, data, now=decided_at, report=report))
    return banked


# ──────────────────────────────────────────────────────────────────────────
# 뱅크 적재 (DB 래퍼 — commit은 호출자·저장소 패턴)
# ──────────────────────────────────────────────────────────────────────────
async def bank_candidates(
    session: AsyncSession,
    candidates: Sequence[BankCandidate],
    *,
    report: MultiSolutionReport,
) -> list[dict[str, Any]]:
    """검증 통과 후보를 3좌석(vs·헤더·대표 스텝)에 적재하고 사람 검수 큐 레코드를 반환.

    적재 순서(후보 1건): 내용 지문 dedup → `verified_solutions` add+flush(id 확보) → 헤더
    (`sp-{vs.id}`·gen_meta) → 단계 좌석이 빈 문제의 첫 경로만 `problem_step` 실체화(UNIQUE
    불변·클로버 금지 — S4-10 재론 규약·`path_promotion`과 동일). commit은 호출자(CLI가
    dry-run/apply를 commit/rollback으로 결정).
    """
    queue_entries: list[dict[str, Any]] = []
    if not candidates:
        return queue_entries

    problem_ids = {candidate.seed.problem_id for candidate in candidates}
    # 멱등 dedup 재료 — 같은 문제의 기존 풀이 내용 지문(전 grade — 동일 내용이면 등급도 동일).
    existing_result = await session.execute(
        select(VerifiedSolution).where(VerifiedSolution.problem_id.in_(problem_ids))
    )
    existing_fingerprints: set[tuple[uuid.UUID, str]] = {
        (row.problem_id, content_fingerprint(row.solution_path))
        for row in existing_result.scalars().all()
    }
    # 단계 좌석 선점 재료 — 레거시 Socratic·기존 대표 경로의 problem_step 실재(클로버 금지).
    steps_result = await session.execute(
        select(ProblemStep.problem_id).where(ProblemStep.problem_id.in_(problem_ids)).distinct()
    )
    problems_with_steps: set[uuid.UUID] = {
        problem_id for problem_id in steps_result.scalars().all() if problem_id is not None
    }

    for candidate in candidates:
        key = (candidate.seed.problem_id, candidate.fingerprint)
        if key in existing_fingerprints:
            report.duplicates_skipped += 1
            continue
        existing_fingerprints.add(key)

        # ── ① 풀이 본문 자산(verified_solutions) — strategy_tag는 enum 값(승격). ──
        payload = _solution_payload(candidate.seed, candidate.final_answer_map, candidate.steps)
        answer_text = ", ".join(
            f"{var}={value}" for var, value in sorted(candidate.final_answer_map.items())
        )
        solution = VerifiedSolution(
            problem_id=candidate.seed.problem_id,
            grade=candidate.grade,
            solution_path=payload,
            strategy_tag=candidate.approach.value,
            answer=answer_text,
        )
        session.add(solution)
        await session.flush()  # server_default id 확보 — 헤더 결정론 ID의 재료

        # ── ② 경로 헤더(solution_paths) — promotion과 같은 ID 체계·gen_meta 동반. ──
        path_id = generated_path_id(solution.id)
        path = candidate.path.model_copy(update={"solution_path_id": path_id})
        session.add(
            SolutionPathOrm(
                solution_path_id=path_id,
                problem_id=candidate.seed.problem_id,
                approach_type=candidate.approach.value,
                concept_sequence=[],
                verified_by_human=False,
                equivalence_cluster_id=None,
                gen_meta=dict(candidate.gen_meta),
                created_at=path.created_at,
            )
        )
        report.banked_paths += 1
        report.ai_estimated_meta += 1
        if candidate.grade is WhsSolutionGrade.VERIFIED:
            report.banked_verified += 1
        else:
            report.banked_unverified += 1
        report.note_banked_approach(candidate.seed.problem_id, candidate.approach)

        # ── ③ 대표 경로 단계(problem_step) — 좌석이 빈 문제의 첫 경로만(UNIQUE 불변). ──
        if candidate.seed.problem_id not in problems_with_steps:
            problems_with_steps.add(candidate.seed.problem_id)
            for step in path.steps:
                session.add(
                    ProblemStep.from_schema(
                        ProblemStepSchema(
                            problem_id=candidate.seed.problem_id,
                            step_order=step.order,
                            expected_answer=step.content,
                            solution_path_id=path_id,
                            concept_node_id=None,  # 매칭 검수 대기(날조 금지)
                            reasoning_type=None,
                            justification=None,
                            common_errors=None,
                            sympy_verified=step.sympy_verified,
                        )
                    )
                )
            report.banked_steps_rows += len(path.steps)
        else:
            report.banked_header_only += 1

        # ── 사람 검수 큐 — ai_estimated 메타·개념 매칭·verified_by_human 검수 대상. ──
        queue_entries.append(
            {
                "queue": _QUEUE_KIND,
                "reason": "ai_estimated_generation",
                "problem_id": str(candidate.seed.problem_id),
                "solution_path_id": path_id,
                "approach_type": candidate.approach.value,
                "grade": candidate.grade.value,
                "steps": list(candidate.steps),
                "unmatched_step_orders": [step.order for step in path.steps],
                "gen_meta": dict(candidate.gen_meta),
            }
        )

    await session.flush()
    return queue_entries


# ──────────────────────────────────────────────────────────────────────────
# 시드 로딩 (verified 코퍼스 — 발문 + canonical 정답 앵커)
# ──────────────────────────────────────────────────────────────────────────
async def load_seeds(
    session: AsyncSession,
    *,
    limit: int,
    problem_ids: Sequence[uuid.UUID] | None = None,
    report: MultiSolutionReport,
) -> list[SeedProblem]:
    """시드 스코프 로딩 — verified_solutions VERIFIED 행이 있는 문제 중 N건(결정적 순서).

    문제당 **첫** VERIFIED 행(`problem_id, created_at, id` 정렬)의 `{conditions, answer}`를
    검증 앵커로 쓰고, 발문은 problem 코퍼스에서 조인한다. 형식 위반(conditions/answer 결측)·
    발문 부재(메타 전용 출처)·코퍼스 부재 문제는 스킵·카운트한다(조용한 통과 금지).
    """
    stmt = select(VerifiedSolution).where(VerifiedSolution.grade == WhsSolutionGrade.VERIFIED)
    if problem_ids:
        stmt = stmt.where(VerifiedSolution.problem_id.in_(list(problem_ids)))
    stmt = stmt.order_by(
        VerifiedSolution.problem_id, VerifiedSolution.created_at, VerifiedSolution.id
    )
    rows_result = await session.execute(stmt)
    rows: list[VerifiedSolution] = list(rows_result.scalars().all())

    # 문제당 첫 행만(결정적 대표) — limit는 *문제 수* 기준.
    first_by_problem: dict[uuid.UUID, VerifiedSolution] = {}
    for row in rows:
        if row.problem_id not in first_by_problem:
            first_by_problem[row.problem_id] = row
    selected = list(first_by_problem.values())[: max(0, limit)]
    report.seeds_total = len(selected)
    if not selected:
        return []

    problems_result = await session.execute(
        select(Problem).where(Problem.problem_id.in_({row.problem_id for row in selected}))
    )
    question_by_id: dict[uuid.UUID, str | None] = {
        problem.problem_id: problem.question_text for problem in problems_result.scalars().all()
    }

    seeds: list[SeedProblem] = []
    for row in selected:
        question = question_by_id.get(row.problem_id)
        if question is None or not question.strip():
            # 코퍼스 부재 또는 본문 미보유(메타 전용 출처) — 발문 없이 생성 불가.
            report.seeds_skipped_no_question += 1
            continue
        seed = _seed_from_row(row, question.strip())
        if seed is None:
            report.seeds_skipped_malformed += 1
            report.failures.append(
                f"seed_malformed vs={row.id}: solution_path의 conditions/answer 형식 위반"
            )
            continue
        seeds.append(seed)
    return seeds


def _seed_from_row(row: VerifiedSolution, question_text: str) -> SeedProblem | None:
    """VERIFIED 행 → SeedProblem. conditions/answer 형식 위반이면 None(호출자가 카운트)."""
    payload = row.solution_path
    conditions_raw = payload.get("conditions")
    if isinstance(conditions_raw, str) and conditions_raw.strip():
        conditions: tuple[str, ...] = (conditions_raw.strip(),)
    elif isinstance(conditions_raw, list) and all(
        isinstance(item, str) and item.strip() for item in conditions_raw
    ):
        conditions = tuple(item.strip() for item in conditions_raw)
    else:
        return None
    answer_raw = payload.get("answer")
    if not isinstance(answer_raw, dict) or not answer_raw:
        return None
    answer_map: dict[str, str] = {}
    for var, value in answer_raw.items():
        if not isinstance(var, str) or not var.strip():
            return None
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            return None
        answer_map[var.strip()] = str(value).strip()
    return SeedProblem(
        problem_id=row.problem_id,
        question_text=question_text,
        conditions=conditions,
        answer_map=answer_map,
    )


# ──────────────────────────────────────────────────────────────────────────
# 결정론 가짜 provider — `--fake-provider` 명시 시·hermetic 테스트 전용
# ──────────────────────────────────────────────────────────────────────────
class DeterministicFakeProvider:
    """결정론 가짜 LLM provider — 시드의 canonical 정답을 되먹인 고정 응답(LLMProvider 충족).

    ⚠️ **자기답 되먹임 정직 고지(S2-02 선례)**: 이 가짜의 생성률·검증 통과율은 파이프라인
    무결성 지표이지 풀이 능력·실 생성률이 아니다 — 리포트가 `fake_disclosure`로 항상 고지한다.
    응답은 시드당 2후보(① algebraic — 산문 스텝 포함 → 전이 unverifiable → 정직 False 플래그
    경로 ② backward — 동일 표현식 전이 → correct → 전 검증 경로)로 두 뱅크 분기를 모두
    태운다(결정론). 프롬프트에 등장하는 발문 부분 문자열로 시드를 식별한다.
    """

    def __init__(self, canned: Mapping[str, str]) -> None:
        """canned: 발문 텍스트 → 원시 응답 JSON 문자열."""
        self._canned = dict(canned)

    @classmethod
    def for_seeds(cls, seeds: Sequence[SeedProblem]) -> DeterministicFakeProvider:
        """시드 집합에서 결정론 응답을 조립한 가짜 provider 구성."""
        return cls({seed.question_text: _fake_response_for_seed(seed) for seed in seeds})

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
        temperature: float | None = None,
        # EOS-121: top_p 좌석도 seed와 같은 이유로 받되 무시한다(결정론 가짜라 샘플링이 무의미).
        top_p: float | None = None,
        json_schema: Mapping[str, object] | None = None,
        # EOS-73: seed 좌석은 받되 무시한다 — 이 가짜는 이미 결정론이라 시드가 바꿀 것이 없다
        # (LLMProvider 계약 정합용 인자·값은 캡처하지 않는다).
        seed: int | None = None,
    ) -> GenerationResult:
        """프롬프트에 포함된 발문으로 시드를 식별해 canned 응답 반환(미지 프롬프트는 명확 오류)."""
        for question, response in self._canned.items():
            if question in prompt:
                return GenerationResult(text=response, usage=None)
        raise LookupError("결정론 가짜 provider — 프롬프트가 알려진 시드 발문과 매칭되지 않음")


def _fake_response_for_seed(seed: SeedProblem) -> str:
    """시드 1건의 결정론 canned 응답 — 두 접근(unverifiable 스텝 경로 + 전 검증 경로)."""
    var = sorted(seed.answer_map)[0]
    value = seed.answer_map[var]
    answer_obj = dict(seed.answer_map)
    identity_expr = f"({var}) - ({value})"  # 동일 표현식 전이 → verify_step correct
    return json.dumps(
        {
            "solutions": [
                {
                    "approach": ApproachType.algebraic.value,
                    "key_insight": "조건을 정리해 답에 도달한다",
                    "steps": ["주어진 조건을 정리한다", f"{var} = {value}"],
                    "final_answer": answer_obj,
                    "educational_value": "기본 절차의 확인",
                    "difficulty": "easy",
                    "elegance": 2,
                },
                {
                    "approach": ApproachType.backward.value,
                    "key_insight": "결론에서 거꾸로 확인한다",
                    "steps": [identity_expr, identity_expr],
                    "final_answer": answer_obj,
                    "educational_value": "역방향 검산 습관",
                    "difficulty": "medium",
                    "elegance": 3,
                },
            ],
            "comparison": "첫 접근은 직관적이고, 둘째 접근은 결론 검산을 보여준다.",
        },
        ensure_ascii=False,
    )


# ──────────────────────────────────────────────────────────────────────────
# CLI (ops — stdout=검수 큐 JSONL·stderr=리포트·기본 dry-run·전멸 시 exit 1)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RunConfig:
    """CLI 실행 구성 — main이 파싱해 run_fn에 넘긴다(테스트 주입 좌석)."""

    apply: bool
    fake_provider: bool
    limit: int
    problem_ids: tuple[uuid.UUID, ...] | None
    seed_scope: str


@dataclass
class RunOutcome:
    """실행 결과 — 리포트 + 검수 큐 레코드(CLI가 stdout/stderr로 분리 출력)."""

    report: MultiSolutionReport
    queue_entries: list[dict[str, Any]] = field(default_factory=list)


async def _default_run(
    config: RunConfig,
) -> RunOutcome:  # pragma: no cover — 실 DB·라이브
    """기본 실행 — 세션 1개로 시드 로딩→생성→적재, apply면 commit·아니면 rollback(dry-run).

    provider: 기본 **라이브**(CompositeProvider — 라우터 결정 존중·지연 연결). 도달 불가는
    호출별 provider_errors로 정직 카운트된다(침묵 폴백 금지). `--fake-provider`일 때만
    결정론 가짜(정직 고지 동반). trace는 LangfuseSink(키 미설정=no-op·네트워크 0).
    """
    report = MultiSolutionReport(provider_kind="fake" if config.fake_provider else "live")
    async with get_sessionmaker()() as session:
        seeds = await load_seeds(
            session,
            limit=config.limit,
            problem_ids=list(config.problem_ids) if config.problem_ids else None,
            report=report,
        )
        provider: LLMProvider
        if config.fake_provider:
            provider = DeterministicFakeProvider.for_seeds(seeds)
        else:
            # 표준 저작 구성 — 지연 연결이라 구성만으로 네트워크 0. 클라우드 좌석은
            # `settings.cloud_provider`가 정한다(ARCH-57). **app.py와는 의도적으로
            # 다르다** — 학생 대면 서빙은 셀렉터를 타지 않는다(ARCH-56 게이트 ⓐ).
            from whymath_backend.l3.providers.composite import CompositeProvider
            from whymath_backend.l3.providers.factory import build_cloud_provider
            from whymath_backend.l3.providers.ollama import OllamaProvider

            provider = CompositeProvider(local=OllamaProvider(), cloud=build_cloud_provider())
        from whymath_backend.l3.trace.langfuse_sink import LangfuseSink

        trace = LangfuseSink()
        candidates = await generate_candidates(seeds, provider, trace=trace, report=report)
        queue_entries = await bank_candidates(session, candidates, report=report)
        if config.apply:
            await session.commit()
        else:
            await session.rollback()
        _flush_trace(trace)
    return RunOutcome(report=report, queue_entries=queue_entries)


RunFn = Callable[[RunConfig], Coroutine[Any, Any, RunOutcome]]


def main(argv: list[str] | None = None, *, run_fn: RunFn = _default_run) -> int:
    """CLI 엔트리 — stdout=검수 큐 JSONL·stderr=실측 리포트 JSON 한 줄(`path_promotion` 미러).

    기본 **dry-run**(생성·검증·리포트만 — rollback으로 미적재. 단 라이브 provider면 LLM 호출
    자체는 발생한다 — 기본 free 구독이라 LOCAL 0원). `--apply`일 때만 commit. 종료 코드:
    정상 0 / **provider 전멸**(호출 전부 provider 오류·측정 실패) 1 — "0건 통과"로 위장하지
    않는다(CLAUDE.md 측정 실패 가시화).
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.l3.multi_solution",
        description=(
            "다중 풀이 생성 파이프라인(S4-10·D2) — 라우터 경유 생성 → SymPy 전건 검증 → "
            "통과분만 solution_path 뱅크. stdout=검수 큐 JSONL·stderr=실측 리포트."
        ),
    )
    parser.add_argument(
        "--seed-scope",
        choices=["verified"],
        default="verified",
        help="시드 스코프 — verified: verified_solutions VERIFIED 행 보유 문제(현재 유일 스코프).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="시드 문제 수 상한(결정적 순서 앞에서부터·기본 10).",
    )
    parser.add_argument(
        "--problem-ids",
        type=str,
        default=None,
        help="쉼표 구분 problem UUID 목록 — 시드 스코프 안에서 이 문제들로 한정(선택).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제 적재(commit). 미지정 시 dry-run(생성·검증·리포트만·rollback).",
    )
    parser.add_argument(
        "--fake-provider",
        action="store_true",
        help=(
            "결정론 가짜 provider로 대체 실행(명시 플래그 전용 — 기본은 라이브). "
            "수치는 파이프라인 무결성 지표이지 실 생성률이 아니다(리포트에 정직 고지)."
        ),
    )
    args = parser.parse_args(argv)

    problem_ids: tuple[uuid.UUID, ...] | None = None
    if args.problem_ids:
        try:
            problem_ids = tuple(
                uuid.UUID(token.strip()) for token in args.problem_ids.split(",") if token.strip()
            )
        except ValueError:
            parser.error("--problem-ids 는 쉼표 구분 UUID 목록이어야 합니다")

    config = RunConfig(
        apply=bool(args.apply),
        fake_provider=bool(args.fake_provider),
        limit=int(args.limit),
        problem_ids=problem_ids,
        seed_scope=str(args.seed_scope),
    )
    outcome = asyncio.run(run_fn(config))

    for entry in outcome.queue_entries:
        print(json.dumps(entry, ensure_ascii=False))
    summary = {
        "mode": "apply" if config.apply else "dry-run",
        **outcome.report.summary(),
    }
    print(json.dumps(summary, ensure_ascii=False), file=sys.stderr)

    report = outcome.report
    if report.generation_calls > 0 and report.provider_errors == report.generation_calls:
        # 전 호출 provider 오류 = 측정 실패 — "0건 통과/미달"로 위장하지 않는다(exit 1).
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트, main이 테스트 대상
    sys.exit(main())
