"""Polya 코칭 엔진 — 결정·조립 + L3 호출 좌석.

`PolyaCoach.decide()`는 *순수*(LLM 0회) — 학생 발화·상태 → `PedagogyDecision`.
`PolyaCoach.coach()`는 `LLMSeam`을 주입받아 결정 → 생성 → 톤필터까지 한 번에. L4→L3
호출은 *Protocol* 좌석으로 격리(L3 import 0 — 계층 분리 유지).

설계: 단계 전이 후 *다음 단계*의 프롬프트를 채워 반환(즉, "다음에 할 말"이 결정 결과).
`stay`면 현 단계 프롬프트(같은 질문을 다른 표현으로 재제시는 후속 — 슬라이스 1은 동일 본문).
"""

from __future__ import annotations

from collections.abc import Sequence

from whymath_backend.config import get_settings
from whymath_backend.l4.hint_deferral import REVEALS, decide_base_hint_level, decide_hint_level
from whymath_backend.l4.lthc.models import MasteryLevel
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.l4.models import (
    LLMSeam,
    PedagogyDecision,
    PolyaStage,
    PolyaState,
    ToneReport,
    next_polya_stage,
)
from whymath_backend.l4.pedagogy.prompt_assembler import build_system_prompt
from whymath_backend.l4.polya.prompts import STAGE_PROMPTS, base_system_for_grade
from whymath_backend.l4.polya.transitions import should_advance
from whymath_backend.l4.socratic import SocraticCategory, select_category
from whymath_backend.l4.tone_filter import filter_tone
from whymath_backend.schema.pedagogy_pack import PedagogyPack

# 단계별 보조 행동 라벨 — UI/내부 후속 트리거 후보(스펙 §"인터페이스" L173).
# 슬라이스 1은 정적 매핑(학습자별 동적 조정은 L2 통합 후속).
_STAGE_ACTIONS: dict[PolyaStage, tuple[str, ...]] = {
    PolyaStage.UNDERSTAND: ("조건 나열", "목표 식별", "미지수 표시"),
    PolyaStage.PLAN: ("관점 선택", "전략 후보 나열", "유사 문제 회상"),
    PolyaStage.EXECUTE: ("단계별 적기", "막힘 보고", "중간 점검"),
    PolyaStage.REVIEW: ("검산", "다른 풀이 탐색", "메타인지 회상", "전이 시도"),
}


class PolyaCoach:
    """Polya 4단계 코칭 엔진.

    상태 비저장(stateless) — 모든 입력을 인자로 받는다. 세션 상태(`PolyaState`) 영속화는
    호출자(또는 후속 슬라이스의 세션 저장소) 책임.
    """

    def decide(
        self,
        student_input: str,
        state: PolyaState,
        *,
        mastery_level: MasteryLevel | None = None,
        misconception_hypotheses: Sequence[MisconceptionHypothesis] | None = None,
        pack: PedagogyPack | None = None,
        recent_categories: Sequence[SocraticCategory] = (),
        grade: int | None = None,
        standard_code: str | None = None,
    ) -> PedagogyDecision:
        """LLM 없이 *결정*만. 다음 단계·프롬프트·system·권장 티어·보조 행동을 채운다.

        - 전이 판정 → next면 `_next_stage()`의 프롬프트, stay면 현 단계 프롬프트.
        - `socratic_category`: 단계·전이·발화 신호·활성 오개념 가설로 6카테고리 중 하나.
          stay/previous + 명시 신호 없음 + 고신뢰·최근 가설이면 ASSUMPTION으로 가정 표면화.
          `misconception_hypotheses` None → 현 동작 불변(하위호환·맞은 학생 영향 0).
        - `recent_categories`(PED-04 D1 reader ①): 직전 AI 턴들의 카테고리 꼬리 연속열. 세션
          경로가 `DialogueTurn.targeted_step` 이력에서 서버 파생해 넘긴다. 기본 `()`면 회전
          규칙이 잠들어 **현 동작과 비트동일**(stateless `/v1/coach`·직접 호출).
        - `hint_level`: 답 미루기 4단계 — 좌절·답요구·5회+ 막힘 신호로 점진 상승(슬라이스 3).
        - `reveals`: hint_level에서 파생된 노출량 라벨(KPI 입력).
        - `recommended_cost_tier=LOCAL`(기본 — Polya 코칭은 로컬 충분, CLAUDE.md "로컬 LLM 우선").
        - `pack`(PED-01 슬라이스 ③ 옵트인 훅): 지식 유형별 교수법 팩을 명시 주입하고 *동시에*
          `pedagogy_pack_prompt_enabled` 플래그가 켜졌을 때만, base_system 위에 팩 4계층 발문을
          조립해 `system`을 대체한다. **pack None(기본)이거나 플래그 OFF면 조립기 미호출로
          `system=sp.system` 그대로**(바이트 동일·회귀 0). 기존 호출자는 pack 미전달이라 무영향.
        - `grade`(W0 — S-2 학년축 register): base_system 정체성 문구("너는 한국 {register}을
          돕는...")의 학년 register를 직접 결정한다(`base_system_for_grade` — 결정론적 문구
          치환이라 팩 조립과 달리 플래그·fidelity 게이트 불요). `grade=None`(기본·미전달
          호출자 다수)이면 기존 문구("중·고등학생")와 바이트 동일이라 회귀 0.
        - `standard_code`(PED-05 개인화 슬롯): 팩 조립이 실제로 일어날 때(pack 주입 ∧ 플래그
          ON)만 `build_system_prompt`의 계층 4로 thread된다 — 기본 None이라 기존 호출자(팩
          미주입·플래그 OFF)는 완전 회귀 0. PII 가드: `grade`(학년 정수)·`standard_code`(성취
          기준 코드 문자열) 외의 학생 식별 정보는 이 메서드 시그니처에 자리가 없다.
        """
        transition = should_advance(state, student_input, mastery_level=mastery_level)
        target_stage = (
            next_polya_stage(state.current_stage) if transition == "next" else state.current_stage
        )
        sp = STAGE_PROMPTS[target_stage]
        category = select_category(
            state.current_stage,
            transition,
            student_input,
            misconception_hypotheses,
            recent_categories,
        )
        hint_level = decide_hint_level(
            student_input=student_input,
            turn_count=state.turn_count,
            prev_hint_level=state.prev_hint_level,
            mastery_level=mastery_level,
        )
        # EOS-178: 같은 입력에서 라벨 없이 계산한 단계 — 공급 원장이 최종 단계와 나란히 적는다.
        base_hint_level = decide_base_hint_level(
            student_input=student_input,
            turn_count=state.turn_count,
            prev_hint_level=state.prev_hint_level,
        )
        # 학년 register(W0 S-2) — grade=None이면 sp.system과 바이트 동일(_BASE_SYSTEM 폴백).
        base_system = base_system_for_grade(grade)
        # 교수법 팩 4계층 조립(옵트인 + 플래그 게이트) — pack 주입 ∧ 플래그 ON일 때만. 그 외에는
        # base_system(register 반영·팩 미조립) 그대로 — OFF/무팩 회귀 0 계약은 "팩 조립기 미호출"
        # 범위(pedagogy_pack_prompt_enabled 설정 docstring)이지 grade register와는 무관.
        system = base_system
        if pack is not None and get_settings().pedagogy_pack_prompt_enabled:
            system = build_system_prompt(
                base_system=base_system,
                pack=pack,
                misconceptions=misconception_hypotheses,
                student_state=mastery_level,
                grade=grade,
                standard_code=standard_code,
            )
        return PedagogyDecision(
            polya_stage_to_advance=transition,
            hint_level=hint_level,
            socratic_category=category.value,
            prompt=sp.prompt,
            system=system,
            suggested_actions=list(_STAGE_ACTIONS[target_stage]),
            reveals=REVEALS[hint_level],
            base_hint_level=base_hint_level,
            applied_mastery_level=mastery_level,
        )

    async def coach(
        self,
        student_input: str,
        state: PolyaState,
        *,
        llm: LLMSeam,
    ) -> tuple[PedagogyDecision, str, ToneReport]:
        """decide → LLM 생성 → 톤필터까지. 반환 = (결정, 필터된 응답, 톤보고).

        LLM 출력에 금지 패턴이 섞여 와도 `filter_tone`이 *마지막 방어선*으로 치환한다.
        `ToneReport.violations`가 비어있지 않으면 *프롬프트 회귀*(시스템 프롬프트 조정·
        provider 교체 신호 — KPI 추적).
        """
        decision = self.decide(student_input, state)
        raw = await llm.generate(decision.prompt, decision.system)
        filtered, report = filter_tone(raw)
        return decision, filtered, report
