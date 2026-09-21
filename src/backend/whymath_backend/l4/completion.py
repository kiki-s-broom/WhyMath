"""L4 완료 상태머신 — 풀이 제출로만 완료, Polya 돌아보기(메타인지) 1턴 경유 (S3-32).

**배경·철학(Kiki 교수학 지적)**: 종래 앱은 풀이과정(코치 대화·단계 풀이)과 완료판정(별도 "정답
제출" 버튼)이 *분리*돼 있었다. 그러면 풀이과정이 "이게 답인지"조차 모르니 신뢰가 안 가고, 학생은
버튼만 눌러 **Polya 돌아보기(review)를 우회**한다 — 풀이과정이 공염불이 되고 WhyMath 금기
("정답 빠르게 KPI 금지"·"막힘시 바로 정답 금지·Polya 우선")를 위반한다.

**목표(확정)**: 완료를 **오직 풀이 제출을 통해서**만 일어나게 한다. 풀이의 마지막 단계가
기대정답이면 서버가 감지하고(L3 `verify_final_answer`), *바로 넘기지 않고* 코치가 **Polya 돌아보기
= "왜 이 답이 나왔는지" 메타인지 확인 1턴**을 한 뒤에야 완료→다음 문항으로 간다.

**이 모듈의 책임(순수 L4·DB 0·LLM 0)**: 완료 *상태 전이*만 결정한다. 정답/오답 도달 감지(L3
verify)와 attempt 적재·숙달 전파(L2 헬퍼 재사용)·세션 상태 영속(dialogue)은 *L5 오케스트레이션*
(coach.py) 책임이다 — 계층 경계를 지킨다(L4는 "무엇을 말하고 완료할지"만, 부작용은 L5).

**상태(턴 간)**: 세션(dialogue)에 *남은 돌아보기 턴 수*(`review_turns_remaining`)와 *완료 여부*
(dialogue.attempt_id 존재)만 둔다. 흐름:
  - **정답 첫 도달**(prior=0·미완료·마지막 단계 correct) → `ENTER_REVIEW`: 돌아보기 대기 진입,
    `review_turns_remaining = REFLECTION_TURNS`(기본 1), 코치 발화=메타인지 프롬프트. **아직 완료
    아님**(attempt 미적재).
  - **돌아보기 응답 턴**(prior>0) → 감소. 0에 닿으면 `COMPLETE`(완료 확정·attempt 적재 신호·
    인정 발화), 아직 남았으면 `CONTINUE_REVIEW`(다음 메타인지 프롬프트·2턴 확장 여지).
  - **명확한 오답 첫 제출**(prior=0·미완료·final incorrect) → `REDIRECT`: 완료 없이 재고
    유도 발화(정답 비노출·부정 정서강화 0)로 학생이 오답에 갇히지 않게 *방향*을 준다.
  - **그 외**(미검증·사변·완료됨) → `NONE`: 완료 무관·기존 코칭 그대로(회귀 불변).

**정직·안전(CLAUDE.md)**: 이 모듈은 correct·incorrect *판정 결과*만 불리언으로 받는다 —
unverifiable(사변·파싱불가)을 correct/incorrect로 위장할 경로가 없다(호출자가 각각
`FinalAnswerState.correct`·`.incorrect`일 때만 True를 넘기고 unverifiable은 둘 다 False). 모든
발화는 결정론 템플릿(메타인지·재고 유도·정서안전·부정 강화 금지·톤필터 금지패턴 0)이며 기대정답
원문을 담지 않는다(정답 비노출 계약).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.l4.socratic.categories import SocraticCategory

__all__ = [
    "REFLECTION_TURNS",
    "CompletionAction",
    "CompletionDecision",
    "decide_completion",
    # 재고 발화 상수 2종 — 테스트가 exact 비교용 단일 진실원천으로 import한다.
    "_REDIRECT_PROMPT",
    "_REDIRECT_PROMPT_SPECIFIC",
]


# 기본 돌아보기 턴 수 — MVP는 정확히 1턴(왜→학생답→완료). "1~2차례"의 2턴 확장은 이 상수만
# 올리면 되도록 설계했다(`decide_completion(reflection_turns=2)`·상태머신은 감소 루프라 N턴 일반).
REFLECTION_TURNS: int = 1


class CompletionAction(str, Enum):
    """완료 상태머신의 5전이 — 호출자(L5)가 발화·부작용을 이 값으로 분기한다.

    `str, Enum`이라 멤버가 문자열과 동등 비교된다(코드베이스 enum 컨벤션). 값은 로그·테스트에서
    직접 읽힌다.
    """

    NONE = "none"
    """완료 무관 — 기존 코칭 발화 그대로(미검증·사변·이미 완료된 세션). 부작용 0."""

    ENTER_REVIEW = "enter_review"
    """정답 첫 도달 → 돌아보기 대기 진입. 메타인지 프롬프트 발화·attempt 미적재(아직 완료 아님)."""

    CONTINUE_REVIEW = "continue_review"
    """돌아보기 다회(2턴 확장) 중 — 아직 남음. 다음 메타인지 프롬프트·attempt 미적재."""

    COMPLETE = "complete"
    """돌아보기 끝 → 완료 확정. 인정 발화 + attempt(is_correct=True) 적재·숙달 전파 신호."""

    REDIRECT = "redirect"
    """명확한 오답(final incorrect) → 재고 유도. 일반 소크라테스 반복 대신 "그 답이 맞을지
    다시 확인·과정 재점검"을 유도하는 결정론 발화·**완료/attempt/돌아보기 없음**. 정답을 노출하지
    않고 부정 정서강화(틀렸다 등)도 하지 않는다 — 학생이 오답에 갇히지 않게 *방향*을 준다."""


class CompletionDecision(BaseModel):
    """완료 상태머신의 1턴 결정 — 순수(부작용 0). 호출자가 이 지시대로 발화·영속·적재한다.

    - `action`: 5전이 중 하나(부작용 분기).
    - `review_turns_remaining_after`: 이 턴 처리 *후* 세션(dialogue)에 저장할 남은 돌아보기 턴 수
      (`ENTER_REVIEW`=REFLECTION_TURNS·`CONTINUE_REVIEW`=감소값·`COMPLETE`/`NONE`=0).
    - `problem_complete`: 이 턴에 문제가 *완료*됐는지(다음 문항으로 갈 신호). `COMPLETE`만 True.
    - `awaiting_reflection`: 돌아보기 응답 대기 중인지("돌아보기 1턴" UX 신호). ENTER/CONTINUE True.
    - `prompt`: 결정론 발화 override(메타인지 프롬프트·인정 발화). `NONE`이면 None(기존 발화 유지).
    - `socratic_category`: 발화의 소크라테스 카테고리 override(돌아보기는 META). `NONE`이면 None.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: CompletionAction = Field(description="완료 5전이(부작용 분기).")
    review_turns_remaining_after: int = Field(
        ge=0, description="이 턴 처리 후 세션에 저장할 남은 돌아보기 턴 수."
    )
    problem_complete: bool = Field(description="이 턴에 문제 완료 확정 여부(COMPLETE만 True).")
    awaiting_reflection: bool = Field(description="돌아보기 응답 대기 중인지(ENTER/CONTINUE True).")
    prompt: str | None = Field(
        default=None, description="결정론 발화 override. NONE이면 None(기존 코칭 발화 유지)."
    )
    socratic_category: str | None = Field(
        default=None, description="발화 소크라테스 카테고리 override(돌아보기=meta). NONE이면 None."
    )


# ── 결정론 메타인지 템플릿 (Polya 돌아보기·정서안전·톤필터 금지패턴 0) ──────────────────
# 금지 6패턴(틀렸·못 하·잘못된·실수·바보·포기)을 포함하지 않는다(`tone_filter._REPLACEMENTS`).
# 기대정답 원문을 담지 않는다 — 학생이 *스스로 제출한* 답에 도착했음을 확인하고 근거를 묻는다
# (정답 노출이 아니라 "네 답이 나온 이유"를 묻는 메타인지 확인이 핵심).

# 정답 첫 도달·돌아보기 진입 발화 — "왜 이 답이 나왔는지" 메타인지 확인(Kiki 확정 문구 취지).
_REFLECTION_PROMPT = (
    "답에 도착했네! 넘어가기 전에 한 가지만 같이 볼까? "
    "이 답이 *어떻게* 나왔는지, *왜* 그렇게 풀었는지 너의 말로 설명해줄래?"
)

# 완료 확정·인정 발화 — 근거 *품질*을 평가하지 않는다(S3-22 회수·원 커밋 edd0ab3).
#
# 사고(2026-07-22 Kiki 실기기): 정답 후 돌아보기에 엉뚱한 근거("3")를 내도 이 발화가
# "좋아, 근거가 분명하네. 스스로 풀어내고 왜 그런지까지 설명했어"로 *거짓 칭찬*했다. 돌아보기
# 응답을 검증하지 않는 MVP인데 발화만 설명 품질을 단언한 것이다(CLAUDE.md 금기: 확실하지
# 않을 때 자신 있게 말함).
#
# 정직화: 이 시점에 *검증된* 사실은 하나다 — 완료는 final_answer_correct에서만 나오므로
# "스스로 풀어냈다"는 참이다. 돌아보기의 *내용*은 무엇도 참으로 주장하지 않는다. 톤 안전
# (금지 6패턴 0)·정답 미노출은 그대로다. LLM 근거 검증·재유도는 후속 옵션이며, 그때까지는
# 검증하지 않는 것을 말하지 않는 쪽이 정직하다(발화만 정직화 — Kiki 선택).
_COMPLETION_ACK_PROMPT = "좋아, 여기까지 스스로 풀어냈어 — 다음 문제로 가보자!"

# ── 오답 재고 유도 발화 (결정론·정서안전·톤필터 금지패턴 0·정답 비노출) ────────────────
# 학생이 *명확한 오답*(final incorrect)을 냈을 때, 일반 소크라테스 반복 대신 "그 답이 맞을지 다시
# 확인하고 과정을 처음부터 짚어보자"는 *방향*을 준다. 금지 6패턴(틀렸·못 하·잘못된·실수·바보·포기)을
# 담지 않고(부정 정서강화 금지·CLAUDE.md 금기), 기대정답 원문도 담지 않는다(정답 비노출 계약).
# 핵심은 "네 답이 아니다"라고 단정하지 않고 *스스로 재검토*하도록 메타인지를 여는 것.

# 1회차(첫 재고) — 부드럽게 "그 답이 맞는지 다시 확인·값이 어떻게 나왔는지 처음부터".
_REDIRECT_PROMPT = (
    "음, 그 답이 맞는지 우리 한 번만 더 같이 확인해 볼까? "
    "그 값이 *어떻게* 나왔는지 처음부터 차근차근 짚어보자."
)

# 2회차 이후(재고 반복) — 같은 발화 반복을 피하고, *어느 부분*을 다시 볼지 살짝 더 구체화한다.
# 세션에 별도 카운터를 새로 만들지 않고, 이미 있는 *턴 번호*(redirect_turn_index)로만 변주한다.
_REDIRECT_PROMPT_SPECIFIC = (
    "이번엔 조금 다른 눈으로 볼까? 지금까지 답을 구한 과정에서 "
    "*어느 부분*이 가장 확신이 안 서는지 먼저 짚어보고, 그 단계부터 다시 확인해 보자."
)


def decide_completion(
    *,
    prior_review_remaining: int | None,
    already_completed: bool,
    final_answer_correct: bool,
    final_answer_incorrect: bool = False,
    redirect_turn_index: int = 1,
    reflection_turns: int = REFLECTION_TURNS,
) -> CompletionDecision:
    """완료 상태머신 1턴 전이 — 순수·결정론(DB 0·LLM 0). 호출자(L5)가 이 지시로 발화·부작용 수행.

    입력:
      - `prior_review_remaining`: 세션에 저장된 *직전* 남은 돌아보기 턴 수(None/0이면 돌아보기 전).
      - `already_completed`: 이 세션이 *이미 완료*됐는지(dialogue.attempt_id 존재 → 재완료 금지).
      - `final_answer_correct`: 이 턴 최종답 후보가 기대정답과 동치인지(L3 verify correct).
        호출자는 `FinalAnswerState.correct`일 때만 True를 넘긴다(incorrect/unverifiable→False).
      - `final_answer_incorrect`: 이 턴 최종답 후보가 기대정답과 *명확히 불일치*하는지
        (L3 verify incorrect). 호출자는 `FinalAnswerState.incorrect`일 때만 True를 넘긴다 —
        unverifiable(긴 사변·파싱불가)은 False(사변에 false redirect 금지). correct와 상호배타이며
        만약 둘 다 True로 들어와도 correct가 우선(아래 순서).
      - `redirect_turn_index`: 재고 발화 변주용 *1-기반 턴 번호*(세션의 몇 번째 교환인지).
        세션에 새 카운터를 만들지 않고 이미 있는 턴 번호로만 변주한다 — 1이면 일반 재고, 2 이상이면
        "어느 부분을 다시 볼지" 살짝 더 구체적인 재고(같은 발화 반복 완화). REDIRECT일 때만 쓰인다.
      - `reflection_turns`: 완료 전 요구 돌아보기 턴 수(기본 1·2턴 확장 여지).

    전이(우선순위 순):
      1. **이미 완료** → `NONE`(재완료·중복 attempt 금지·발화 불변).
      2. **돌아보기 중**(prior>0) → 감소. 0 도달 시 `COMPLETE`(완료·인정), 남으면 `CONTINUE_REVIEW`
         (다음 메타인지 프롬프트). *이 분기는 이 턴 풀이 내용과 무관* — 돌아보기 응답 턴은 자연어
         근거일 뿐이라 재검증하지 않는다(MVP: 왜→학생답→완료).
      3. **돌아보기 전 + 정답 첫 도달** → `ENTER_REVIEW`(돌아보기 대기·메타인지 프롬프트·미완료).
      4. **돌아보기 전 + 명확한 오답** → `REDIRECT`(재고 유도 발화·완료/attempt/돌아보기 없음).
      5. **그 외**(미검증·사변) → `NONE`(기존 코칭 그대로·false redirect 회피).
    """
    # ① 이미 완료된 세션 — 재완료·중복 attempt 금지(발화 불변).
    if already_completed:
        return CompletionDecision(
            action=CompletionAction.NONE,
            review_turns_remaining_after=0,
            problem_complete=False,
            awaiting_reflection=False,
        )

    prior = prior_review_remaining or 0

    # ② 돌아보기 응답 턴 — 남은 턴 감소(이 턴 풀이 내용 무관·자연어 근거).
    if prior > 0:
        after = prior - 1
        if after <= 0:
            # 돌아보기 끝 → 완료 확정(인정 발화·attempt 적재 신호).
            return CompletionDecision(
                action=CompletionAction.COMPLETE,
                review_turns_remaining_after=0,
                problem_complete=True,
                awaiting_reflection=False,
                prompt=_COMPLETION_ACK_PROMPT,
                socratic_category=SocraticCategory.META.value,
            )
        # 아직 돌아보기 남음(2턴 확장) → 다음 메타인지 프롬프트.
        return CompletionDecision(
            action=CompletionAction.CONTINUE_REVIEW,
            review_turns_remaining_after=after,
            problem_complete=False,
            awaiting_reflection=True,
            prompt=_REFLECTION_PROMPT,
            socratic_category=SocraticCategory.META.value,
        )

    # ③ 돌아보기 전 + 정답 첫 도달 → 돌아보기 대기 진입(미완료·메타인지 프롬프트).
    if final_answer_correct:
        return CompletionDecision(
            action=CompletionAction.ENTER_REVIEW,
            review_turns_remaining_after=max(1, reflection_turns),
            problem_complete=False,
            awaiting_reflection=True,
            prompt=_REFLECTION_PROMPT,
            socratic_category=SocraticCategory.META.value,
        )

    # ④ 돌아보기 전 + 명확한 오답 → 재고 유도(완료/attempt/돌아보기 없음·정답 비노출).
    #    unverifiable(사변)은 여기 도달하지 않는다(호출자가 incorrect일 때만 True·false redirect 0).
    if final_answer_incorrect:
        prompt = _REDIRECT_PROMPT if redirect_turn_index <= 1 else _REDIRECT_PROMPT_SPECIFIC
        return CompletionDecision(
            action=CompletionAction.REDIRECT,
            review_turns_remaining_after=0,
            problem_complete=False,
            awaiting_reflection=False,
            prompt=prompt,
            # 재점검("그 값이 어떻게 나왔는지 짚어보자")은 도달 과정에 대한 메타인지 질문이다.
            socratic_category=SocraticCategory.META.value,
        )

    # ⑤ 미검증·사변 → 완료 무관(기존 코칭 그대로·회귀 불변·false redirect 회피).
    return CompletionDecision(
        action=CompletionAction.NONE,
        review_turns_remaining_after=0,
        problem_complete=False,
        awaiting_reflection=False,
    )
