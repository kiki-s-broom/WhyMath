"""Polya 4단계 프롬프트 정본 — `docs/prompts/polya_4step.md` L5-71·L101-103 정본 인용.

**드리프트 방지 원칙**: 문구는 `docs/prompts/polya_4step.md` 원문을 *그대로* 옮긴다.
스타일·표현 변경은 그 문서를 먼저 갱신한 뒤 동기화한다(pedagogy-designer 위임).

system 프롬프트는 L4 spec §"5가지 절대 원칙"(L23-29)·§"정서 안전"(L129-138)에서 추출 —
답 미루기·소크라테스 우선·금기 표현 차단을 *모델에 명시*해 응답이 코칭 방향에서 이탈하지
않게 한다. 톤필터(`tone_filter.filter_tone`)는 그 *마지막 방어선*.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.l4.models import PolyaStage


class StagePrompt(BaseModel):
    """단계별 (system, prompt) 쌍 — `PedagogyDecision.system/prompt`로 그대로 노출."""

    model_config = ConfigDict(extra="forbid")

    system: str = Field(description="시스템 프롬프트(역할·원칙·금기·톤 지시).")
    prompt: str = Field(description="사용자 프롬프트(학생에게 던질 발화 본문).")


# 모든 단계 공통 시스템 프롬프트 — L4 절대 원칙 5종 + 인지부하 관리(원칙 6, PED-34 —
# `docs/standards/prompt_engineering.md` §"6. 인지부하 관리" 정본, LearnLM 루브릭 차용)를
# 모델에 *명시* 주입. 학생을 *수동적으로* 만들지 않는 톤(CLAUDE.md "학생을 수동적으로
# 만드는 설계 금지").
#
# 정체성 문구의 학년 register(W0 — S-2: 학년축 최단경로 계획 §2.3)만 `{register}`로 열어둔다.
# 원칙·금기·톤 본문은 학년 무관(4축 공용) — 학년축 = 오버레이 파라미터 원칙(구조 분기 아님).
_BASE_SYSTEM_TEMPLATE = """너는 한국 {register}을 돕는 *수학 메타인지 코치*다. \
다음 원칙을 절대 지킨다:

1. **답을 직접 주지 않는다** — 학생이 *생각하는 법*을 배우게 한다(Polya 단계 우선).
2. **소크라테스 우선** — 답 대신 *질문*으로 이끈다.
3. **메타인지 명시화** — "어떻게·왜 그렇게 생각했어?"를 자주 묻는다.
4. **정서 안전** — 다음 표현 금지: 틀렸·못 하·잘못된·실수·바보·포기. 대신 "흥미로운 시도",
   "거의 다 왔어", "다른 각도로 봐볼까" 같은 표현 사용.
5. **학생의 자기표현 존중** — 학생 입력의 어휘를 임의로 바꾸지 않는다.
6. **인지부하 관리** — 한 발화에 *질문은 정확히 1개*만. 응답은 *3문장 이내*로 짧게.
   여러 단계를 한꺼번에 던지지 말고 *하나씩 나눠* 관리 가능한 크기로 제시한다.
   이미 말한 내용을 반복하거나 지금 단계와 무관한 정보를 덧붙이지 않는다.
   설명보다 *먼저 유도 질문*을 던지고, 필요한 보충 설명은 그 *다음*에만 짧게
   덧붙인다(선 유도→후 보강).

응답은 한국어. 짧고 친근하게.
"""

# 기본 register — grade 미상일 때(호출자 대부분·현행 UserProfile.grade는 고1~N수2[10~14]로만
# 채워짐) 기존 문구를 *바이트 동일*로 보존한다(회귀 0 — 아래 `_grade_register` 폴백과 동일 값).
_DEFAULT_REGISTER = "중·고등학생"

# KR 학년 정수 → 시스템 프롬프트 정체성 register. 번호 공간의 정본은 호출자가 넘기는
# **`UserProfile.grade`**(`api/coach.py` `_grade_for`)이고, 같은 사다리를
# `l4/pedagogy/runtime_selector.py::grade_to_band`가 이미 명문화했다: 1~6=초등·7~9=중학·
# 10~12=고1~고3·**13~14=N수1·2(고교 교육과정·수능 대비 재학습 — 대학 과정이 아니다)**.
# 그래서 10~14를 모두 "고등학생"으로 둔다(`test_polya_prompts`가 grade_to_band와 1~14 전수 대조).
#
# ⚠️ `l1/curriculum/curriculum_loader.py`의 대학 `introduced_grade`(`_UNIV_GRADE_TO_INTRODUCED_GRADE`
# 대학 1~4학년=13~16)는 정렬용 내부 관례라 이 사다리와 13~14에서 번호가 **겹친다**(대학 1~2학년
# ≠ N수1~2). 학생 속성을 소비하는 이 register는 사용자 계약을 따른다 — 로더의 13~14를 그대로
# 가져오면 N수 학생에게 "너는 한국 대학생을 돕는..."이 나간다(2026-10-08 이식 직후 실측 회귀).
# "대학생"은 사용자 grade 계약(ge=10 le=14)에 인코딩이 없어 현 호출자로는 닿지 않는다. 15~16은
# 로더 관례의 대학 3~4학년 값을 받는 후속 호출자를 위한 자리일 뿐이며, 대학 1~2학년(13~14)은 이
# 정수 채널로 표현할 수 없다 — 대학 축을 실제로 연결할 때 모호하지 않은 입력이 필요하다(S4-64).
_GRADE_BAND_RANGES: tuple[tuple[int, int, str], ...] = (
    (1, 6, "초등학생"),
    (7, 9, "중학생"),
    (10, 14, "고등학생"),  # 고1~고3 + N수1·N수2
    (15, 16, "대학생"),
)


def _grade_register(grade: int | None) -> str:
    """학년 정수 → 정체성 문구 register. None·범위 밖은 `_DEFAULT_REGISTER`(회귀 0 폴백).

    현재 `UserProfile.grade`는 스키마상 10~14(고1~N수2·§14.3 MVP 고3 wedge 범위)로만 채워져
    실호출 경로의 값은 전부 "고등학생" register다 — 1~9는 그 스키마 제약이 풀릴 때(온보딩
    확장) 코드 변경 없이 바로 대응한다(학년축 = 오버레이 파라미터).
    """
    if grade is not None:
        for lo, hi, register in _GRADE_BAND_RANGES:
            if lo <= grade <= hi:
                return register
    return _DEFAULT_REGISTER


def base_system_for_grade(grade: int | None) -> str:
    """학년별 register가 반영된 공통 시스템 프롬프트.

    grade=None이면 `_BASE_SYSTEM`과 바이트 동일(회귀 0 폴백).
    """
    return _BASE_SYSTEM_TEMPLATE.format(register=_grade_register(grade))


# 하위호환 상수 — grade 미전달 호출자·`STAGE_PROMPTS` 기본값(기존 동작 무변경).
_BASE_SYSTEM = base_system_for_grade(None)


# Stage 1: 이해 — `docs/prompts/polya_4step.md` L3-17 정본.
_STAGE_1_PROMPT = """이 문제, 잠깐 같이 읽어볼까?

다음 3가지 질문에 답해줘:
1. *주어진 정보*가 뭐야? (조건들)
2. *구해야 하는 게* 뭐야? (목표)
3. *모르는 게* 뭐야? (미지수·미정 요소)

너의 말로 다시 표현해줘.
"""


# Stage 2: 계획 — `docs/prompts/polya_4step.md` L19-34 정본.
_STAGE_2_PROMPT = """좋아, 이제 *어떻게 풀지* 계획을 세워보자.

다음 중 떠오르는 게 있어?
- 비슷한 문제 본 적 있어?
- 어떤 *공식·개념·도구*가 떠올라?
- 더 *작은 경우*부터 시작해볼까?
- *그림·표·도형*으로 정리하면?

먼저 떠오르는 거 하나만 말해줘.
"""


# Stage 3: 실행 — `docs/prompts/polya_4step.md` L36-46 정본.
_STAGE_3_PROMPT = """좋은 계획이야. 한번 그 방법으로 풀어볼래?

천천히 단계별로 적어줘.
중간에 막히면 어디서 막혔는지 말해주면 같이 봐줄게.
"""


# Stage 4: 검토 — `docs/prompts/polya_4step.md` L57-71 정본.
_STAGE_4_PROMPT = """풀이 끝났네. 잠깐, 몇 가지 같이 생각해보자:

1. *답이 합리적이야*? (검산·단위·크기)
2. *다른 방법*으로도 풀릴 거 같아?
3. *어떻게* 이 풀이에 도달했어? (메타인지)
4. 이 *발상*을 다른 비슷한 문제에 쓸 수 있을까? (전이)

먼저 떠오르는 거 하나만.
"""


STAGE_PROMPTS: dict[PolyaStage, StagePrompt] = {
    PolyaStage.UNDERSTAND: StagePrompt(system=_BASE_SYSTEM, prompt=_STAGE_1_PROMPT),
    PolyaStage.PLAN: StagePrompt(system=_BASE_SYSTEM, prompt=_STAGE_2_PROMPT),
    PolyaStage.EXECUTE: StagePrompt(system=_BASE_SYSTEM, prompt=_STAGE_3_PROMPT),
    PolyaStage.REVIEW: StagePrompt(system=_BASE_SYSTEM, prompt=_STAGE_4_PROMPT),
}


# 후퇴 트리거 — `docs/prompts/polya_4step.md` L97-103 정본.
# 학생 명시 후퇴 신호(예: "잘 모르겠어", "다시")에 대해 *이전 단계 질문* 앞에 붙이는 안내.
BACKTRACK_PROMPT = "잠깐, 한 발 뒤로 가서, "
