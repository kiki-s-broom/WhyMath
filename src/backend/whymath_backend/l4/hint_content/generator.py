"""검증된 풀이 단계 → graded 힌트 1~3 오프라인 템플릿 생성기 (S4-11 · D3 · 순수·결정론).

설계 정본: `docs/architecture/solution_module_gap_review.md` §3 D3 — "SolutionStep을 원천으로
graded 1~3 힌트를 **오프라인 사전 생성·검수**한다. 검증 앵커(sympy_verified 단계) 없는 즉석
LLM 힌트는 §2-③ 위반". 이 모듈은 **LLM 호출 0**이다 — 본문은 템플릿 + 검증된 단계 본문의 결정론
조립이며, 같은 입력에 같은 출력(재실행 멱등·헌법 R3-01)을 낸다. 라우터·프로바이더 import 0.

원천(acceptance "SolutionStep(sympy_verified) 원천"):
  - 한 풀이 경로의 단계 본문 전체(`problem_step.expected_answer` — S4-09 승격 어댑터가
    `SolutionStep.content`를 싣는 좌석)와 단계별 `sympy_verified` 플래그.
  - **sympy_verified=True인 단계만** 힌트를 만든다. 그 플래그의 뜻은 "직전 단계 → 이 단계
    전이가 기계 검증을 통과했다"(`whs/path_promotion.py`)이므로, L3가 시연하는 바로 그 전이가
    검증된 전이다. 검증 안 된 단계(승격 경로의 1단계 등)는 건너뛰고 사유를 센다.
  - ※ 정정 기록(ARCH-39 §3-B ② "원천 지목 불일치"): 실제 힌트 *텍스트*가 흐르는 곳은
    `l3/dsl`의 `HintSpec.text`이고 `SolutionStep.hint`는 생산자·소비자가 0건이다. 이 생성기는
    `SolutionStep.hint`(빈 좌석)도 `HintSpec`(DSL 저작 경로·검증 앵커 없음)도 쓰지 않는다 —
    acceptance가 지목한 **검증된 단계 본문**을 원천으로 삼아 힌트 본문을 *새로* 조립한다.

레벨별 노출(acceptance "L1=개념 이름만·L2=단계 흐름·L3=부분 시연"):
  - **L1** 개념 이름만 — 단계 구조·계산을 말하지 않는다. 개념이 없으면 만들지 않는다(날조 금지).
    개념 출처 2종(이름은 둘 다 원자 백본 축에서 해석 — `store.load_path_inputs`):
    ① 단계에 매칭된 개념(`problem_step.concept_node_id` — 사람 검수로 채워짐)
    ② 없으면 문제의 대표 개념(PRIMARY→TESTED). 출처에 따라 문장이 다르다("이번 단계에서는" vs
    "이 문제는 …이 중심") — 문제 단위 개념을 단계 개념처럼 말하지 않는다.
  - **L2** 단계 흐름 — 전체 단계 수·현재 위치·남은 단계를 말하되 **계산 결과는 싣지 않는다**.
    개념이 있으면 함께 댄다(누적 척도 L1 ⊂ L2).
  - **L3** 부분 시연 — 직전 단계의 식과 이번 단계의 식(검증된 전이 1개)을 보여 주고, 그다음은
    학생에게 넘긴다. **마지막 단계는 만들지 않는다** — 마지막 전이의 시연은 곧 전체 풀이이고, 그
    칸은 Hint 엔티티 밖(Level 4 안전망)이다. 게이트 A가 같은 규칙을 독립적으로 다시 강제한다.

소크라테스 전달 카테고리(기존 6종 재사용 — 신규 힌트 유형 enum 미도입):
  L1 → `PERSPECTIVE`(이 개념의 관점으로 보면?) · L2 → `IMPLICATION`(그러면 다음은?) ·
  L3 → `EVIDENCE`(왜 이렇게 바뀌는지 근거는?). 문서 6유형(개념·공식·계산·그림·질문형·오개념 교정)
  은 기존 3축 crosswalk(`solution_module_gap_review.md` §3 D3 표)로 표현된다 — 개념·공식 =
  `reveals_concept_names`, 계산 = `reveals_partial_computation`, 질문형 = `socratic_category`,
  오개념 교정 = `l4/misconception/intervene.py`(reactive 독립 축 — 여기서 만들지 않는다), 그림 =
  시각화 참조 축(여기서 만들지 않는다).

본문 규약: 식은 단계 본문 문자열을 *그대로* 싣는다(표현≠의미 — 렌더는 클라 몫, steps API와 같은
표현). 조사는 `lang.josa`로 붙이고, 식 뒤에는 조사를 붙이지 않도록 콜론 뒤에 둔다(식의 읽기
받침을 추측하지 않는다).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from whymath_backend.l4.hint_content.models import (
    GENERATOR_VERSION,
    Hint,
    HintLevel,
    HintReveals,
    SolutionStepRef,
    hint_id_for,
)
from whymath_backend.l4.socratic.categories import SocraticCategory
from whymath_backend.lang.josa import eul_reul, i_ga

__all__ = [
    "LEVEL_SOCRATIC_CATEGORY",
    "SKIP_FINAL_STEP_PARTIAL",
    "SKIP_NO_CONCEPT",
    "SKIP_UNVERIFIED_STEP",
    "ConceptRef",
    "StepGeneration",
    "StepSource",
    "generate_step_hints",
]

ConceptSource = Literal["step", "problem_primary"]

# 레벨 → 전달 카테고리(기존 6종에서 고른다 — 근거는 모듈 docstring).
LEVEL_SOCRATIC_CATEGORY: dict[int, SocraticCategory] = {
    1: SocraticCategory.PERSPECTIVE,
    2: SocraticCategory.IMPLICATION,
    3: SocraticCategory.EVIDENCE,
}

# 건너뜀 사유(리포트 집계 키 — 조용한 생략 금지).
SKIP_UNVERIFIED_STEP = "unverified_step"
SKIP_NO_CONCEPT = "no_concept"
SKIP_FINAL_STEP_PARTIAL = "final_step_partial"


@dataclass(frozen=True)
class ConceptRef:
    """L1에 댈 개념 — ID(원자 코드)·한국어 이름(원자 축 메타)·출처(단계 매칭/문제 대표)."""

    concept_id: str
    name: str
    source: ConceptSource


@dataclass(frozen=True)
class StepSource:
    """힌트 1묶음의 원천 — 한 경로의 한 단계 + 그 경로의 단계 본문 전체.

    `step_contents`는 경로의 단계 본문을 order 1..n 순서로 담는다(L2의 흐름·L3의 직전 식·
    게이트 A의 최종 결과 판정이 모두 여기서 나온다).
    """

    solution_path_id: str
    problem_id: uuid.UUID
    step_order: int
    step_contents: tuple[str, ...]
    # 직전 단계 → 이 단계 전이가 기계 검증을 통과했는가(`problem_step.sympy_verified` 승계).
    transition_verified: bool
    concept: ConceptRef | None

    @property
    def total_steps(self) -> int:
        return len(self.step_contents)


@dataclass(frozen=True)
class StepGeneration:
    """한 단계의 생성 결과 — 초안(검증 전 Hint)과 건너뛴 (레벨, 사유) 목록."""

    drafts: tuple[Hint, ...]
    skipped: tuple[tuple[int, str], ...]


def _concept_phrase_l1(concept: ConceptRef) -> str:
    """L1 본문 — 개념 이름만(구조·계산 0). 출처에 따라 '이번 단계'와 '이 문제'를 구분한다."""
    name = concept.name
    if concept.source == "step":
        return (
            f"이번 단계에서는 「{name}」{eul_reul(name)} 떠올려 볼까? "
            "이 개념의 어떤 성질을 여기서 쓸 수 있을지 먼저 생각해 보자."
        )
    return (
        f"이 문제는 「{name}」{i_ga(name)} 중심에 있어. "
        "지금 멈춘 곳에서 이 개념의 어떤 성질을 쓸 수 있을까?"
    )


def _flow_text(source: StepSource) -> str:
    """L2 본문 — 전체 단계 수·현재 위치·남은 단계(계산 결과는 싣지 않는다)."""
    n = source.total_steps
    k = source.step_order
    parts: list[str] = []
    if source.concept is not None:
        name = source.concept.name
        parts.append(f"「{name}」{eul_reul(name)} 쓰는 흐름이야.")
    parts.append(f"풀이는 모두 {n}단계로 이어져.")
    if k == 1:
        parts.append("지금은 첫 단계 — 문제의 조건을 식으로 옮겨 적는 자리야.")
    else:
        parts.append(
            f"지금은 {k}번째 단계 — {k - 1}번째 단계에서 얻은 식을 한 번 더 바꿔 "
            "다음 모양으로 옮기는 자리야."
        )
    if k >= n:
        parts.append("이 단계가 마지막 단계야.")
    else:
        parts.append(f"이 단계를 마치면 {n - k}단계가 더 남아.")
    parts.append("앞 단계의 식에서 무엇을 바꾸면 다음으로 나아갈 수 있을까?")
    return " ".join(parts)


def _partial_text(source: StepSource) -> str:
    """L3 본문 — 검증된 전이 1개(직전 식 → 이번 식)를 시연하고 그다음은 학생에게 넘긴다."""
    k = source.step_order
    contents = source.step_contents
    parts: list[str] = ["한 단계를 같이 해 볼게."]
    if source.concept is not None:
        name = source.concept.name
        parts.append(f"「{name}」{eul_reul(name)} 떠올리며 따라와 봐.")
    if k == 1:
        parts.append(f"첫 단계에서 적는 식은 다음과 같아: {contents[0]}")
    else:
        parts.append(f"{k - 1}번째 단계까지 정리한 식은 다음과 같아: {contents[k - 2]}")
        parts.append(f"이것을 한 번 바꾸면 {k}번째 단계의 식이 돼: {contents[k - 1]}")
    parts.append("왜 이렇게 바뀌는지 근거를 말해 줄 수 있을까? 그다음 단계는 네가 이어 가 보자.")
    # 식이 문장 중간에 조사 없이 끼지 않도록 줄 단위로 잇는다(식은 각 줄의 끝에만 온다).
    return "\n".join(parts)


def _draft(
    source: StepSource,
    level: HintLevel,
    content: str,
    *,
    concept_names: bool,
    step_flow: bool,
    partial_computation: bool,
) -> Hint:
    """검증 전 초안(verified=False·gate_report 빈 dict) — 게이트가 판정을 채운다."""
    concept_ids: tuple[str, ...] = ()
    if concept_names and source.concept is not None:
        concept_ids = (source.concept.concept_id,)
    return Hint(
        hint_id=hint_id_for(source.solution_path_id, source.step_order, level),
        solution_step_ref=SolutionStepRef(
            solution_path_id=source.solution_path_id,
            step_order=source.step_order,
            problem_id=source.problem_id,
        ),
        level=level,
        reveals=HintReveals.from_flags(
            concept_names=concept_names,
            step_flow=step_flow,
            partial_computation=partial_computation,
            revealed_concept_ids=concept_ids,
        ),
        content=content,
        socratic_category=LEVEL_SOCRATIC_CATEGORY[level],
        verified=False,
        gate_report={},
        generator_version=GENERATOR_VERSION,
    )


def generate_step_hints(source: StepSource) -> StepGeneration:
    """한 단계의 L1~L3 초안을 만든다(순수·결정론·LLM 0).

    건너뜀(사유를 반드시 남긴다):
      - 단계 전이가 검증되지 않았으면(`transition_verified` False) 레벨 전부
        (`SKIP_UNVERIFIED_STEP`).
      - 개념이 없으면 L1(`SKIP_NO_CONCEPT`) — 개념 이름 힌트를 개념 없이 만들 수 없다.
      - 마지막 단계면 L3(`SKIP_FINAL_STEP_PARTIAL`) — 마지막 전이의 시연 = 전체 풀이(Level 4).
    단계 order가 경로 밖이면 ValueError — 원천 조립 결함이지 건너뛸 사유가 아니다.
    """
    k = source.step_order
    n = source.total_steps
    if not 1 <= k <= n:
        raise ValueError(f"step_order={k}가 경로 단계 범위 [1, {n}] 밖이다 — 원천 조립 결함")
    if not source.transition_verified:
        return StepGeneration(
            drafts=(),
            skipped=tuple((level, SKIP_UNVERIFIED_STEP) for level in (1, 2, 3)),
        )

    drafts: list[Hint] = []
    skipped: list[tuple[int, str]] = []
    has_concept = source.concept is not None

    if source.concept is not None:
        drafts.append(
            _draft(
                source,
                1,
                _concept_phrase_l1(source.concept),
                concept_names=True,
                step_flow=False,
                partial_computation=False,
            )
        )
    else:
        skipped.append((1, SKIP_NO_CONCEPT))

    drafts.append(
        _draft(
            source,
            2,
            _flow_text(source),
            concept_names=has_concept,
            step_flow=True,
            partial_computation=False,
        )
    )

    if k < n:
        drafts.append(
            _draft(
                source,
                3,
                _partial_text(source),
                concept_names=has_concept,
                step_flow=True,
                partial_computation=True,
            )
        )
    else:
        skipped.append((3, SKIP_FINAL_STEP_PARTIAL))

    return StepGeneration(drafts=tuple(drafts), skipped=tuple(skipped))
