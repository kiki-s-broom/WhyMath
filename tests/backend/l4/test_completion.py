"""순수 `decide_completion` 상태머신 단위테스트 — 완료를 풀이 제출에 통합(S3-32·hermetic).

**철학(Kiki 교수학 지적)**: 완료를 *오직 풀이 제출을 통해서*만 일어나게 한다. 풀이 마지막 단계가
기대정답이면 서버가 감지하고, *바로 넘기지 않고* Polya 돌아보기(메타인지) 1턴을 거친 뒤 완료→다음
문항으로 간다. 별도 "정답 제출" 버튼을 대체한다. 명확한 *오답*이면 일반 소크라테스 반복 대신 재고
유도 발화로 방향을 준다(정답 비노출·부정 정서강화 0).

검증 범위(DB·LLM 0 — 순수 함수):
  - 5전이(NONE/ENTER_REVIEW/CONTINUE_REVIEW/COMPLETE/REDIRECT) 전수.
  - correct와 incorrect 동시 True 방어(correct 우선).
  - unverifiable(둘 다 False) → NONE(완료도 재고도 없음·false redirect 금지).
  - 이미 완료된 세션은 정답/오답 신호와 무관하게 항상 NONE(재완료·중복 재고 금지).
  - 돌아보기 중엔 이 턴 정오답 신호를 재검증하지 않는다(review 진행에만 집중).
  - 재고 발화 2종(1회차/2회차+) 변주 + 톤필터 금지패턴 0(정서안전 봉인).

`api/coach.py` 결선(정답/오답 감지·attempt 적재·응답 필드)은 `test_coach_completion.py`가
검증한다 — 여긴 상태머신 primitive만.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from whymath_backend.l4.completion import (
    _REDIRECT_PROMPT,
    _REDIRECT_PROMPT_SPECIFIC,
    REFLECTION_TURNS,
    CompletionAction,
    decide_completion,
)
from whymath_backend.l4.tone_filter import filter_tone

_REFLECTION_MARK = "설명해줄래"  # 돌아보기 프롬프트 표식(문구 취지 검증)
_ACK_MARK = "다음 문제로 가보자"  # 완료 인정 발화 표식


def _assert_tone_safe(text: str) -> None:
    """톤필터 금지 6패턴(틀렸·못 하·잘못된·실수·바보·포기) 0건 — 발화 정서안전 봉인."""
    _, report = filter_tone(text)
    assert report.violations == [], f"금지 패턴 검출: {report.violations}"


class TestEnterReview:
    """돌아보기 전(prior=0)·미완료·정답 첫 도달 → ENTER_REVIEW."""

    def test_enter_review_on_first_correct(self) -> None:
        cd = decide_completion(
            prior_review_remaining=0, already_completed=False, final_answer_correct=True
        )
        assert cd.action is CompletionAction.ENTER_REVIEW
        assert cd.problem_complete is False
        assert cd.awaiting_reflection is True
        assert cd.review_turns_remaining_after == REFLECTION_TURNS
        assert cd.prompt is not None and _REFLECTION_MARK in cd.prompt
        assert cd.socratic_category == "meta"
        _assert_tone_safe(cd.prompt)

    def test_prior_none_treated_as_zero(self) -> None:
        # prior_review_remaining=None(세션 컬럼 NULL·신규) — 0과 동일 취급.
        cd = decide_completion(
            prior_review_remaining=None, already_completed=False, final_answer_correct=True
        )
        assert cd.action is CompletionAction.ENTER_REVIEW

    def test_two_turn_reflection_configurable(self) -> None:
        # reflection_turns=2로 첫 도달 시 2턴이 심어진다(확장성 — 2턴 확장 여지).
        cd = decide_completion(
            prior_review_remaining=0,
            already_completed=False,
            final_answer_correct=True,
            reflection_turns=2,
        )
        assert cd.review_turns_remaining_after == 2
        assert cd.action is CompletionAction.ENTER_REVIEW


class TestReviewProgression:
    """돌아보기 중(prior>0) — 감소 루프, 이 턴 풀이 내용과 무관."""

    def test_complete_on_reflection_response(self) -> None:
        """돌아보기 중(prior=1)·미완료 → COMPLETE(완료·인정 발화). 이 턴 풀이 내용 무관."""
        cd = decide_completion(
            prior_review_remaining=1, already_completed=False, final_answer_correct=False
        )
        assert cd.action is CompletionAction.COMPLETE
        assert cd.problem_complete is True
        assert cd.awaiting_reflection is False
        assert cd.review_turns_remaining_after == 0
        assert cd.prompt is not None and _ACK_MARK in cd.prompt
        assert cd.socratic_category == "meta"
        _assert_tone_safe(cd.prompt)

    def test_continue_review_when_two_turns(self) -> None:
        """2턴 확장 — prior=2면 아직 남음(CONTINUE_REVIEW·완료 아님)."""
        cd = decide_completion(
            prior_review_remaining=2, already_completed=False, final_answer_correct=False
        )
        assert cd.action is CompletionAction.CONTINUE_REVIEW
        assert cd.problem_complete is False
        assert cd.awaiting_reflection is True
        assert cd.review_turns_remaining_after == 1
        assert cd.prompt is not None and _REFLECTION_MARK in cd.prompt

    def test_no_redirect_during_review(self) -> None:
        """돌아보기 중(prior>0)엔 오답 신호여도 재검증하지 않고 review 진행(여기선 COMPLETE)."""
        cd = decide_completion(
            prior_review_remaining=1,
            already_completed=False,
            final_answer_correct=False,
            final_answer_incorrect=True,
        )
        assert cd.action is CompletionAction.COMPLETE


class TestRedirect:
    """돌아보기 전 + 명확한 오답 → REDIRECT(재고 유도·완료/attempt/돌아보기 없음·정답 비노출)."""

    def test_redirect_on_incorrect_first_turn(self) -> None:
        cd = decide_completion(
            prior_review_remaining=0,
            already_completed=False,
            final_answer_correct=False,
            final_answer_incorrect=True,
        )
        assert cd.action is CompletionAction.REDIRECT
        assert cd.problem_complete is False
        assert cd.awaiting_reflection is False
        assert cd.review_turns_remaining_after == 0
        assert cd.prompt == _REDIRECT_PROMPT  # turn_index 기본 1 → 일반 재고
        assert cd.socratic_category == "meta"
        _assert_tone_safe(cd.prompt)

    def test_redirect_variant_on_later_turn(self) -> None:
        """2회차 이후(turn_index≥2) → 같은 발화 반복 대신 구체 재고 발화로 변주."""
        cd = decide_completion(
            prior_review_remaining=0,
            already_completed=False,
            final_answer_correct=False,
            final_answer_incorrect=True,
            redirect_turn_index=2,
        )
        assert cd.action is CompletionAction.REDIRECT
        assert cd.prompt == _REDIRECT_PROMPT_SPECIFIC
        assert cd.prompt != _REDIRECT_PROMPT  # 변주됨(verbatim 반복 아님)
        _assert_tone_safe(cd.prompt)

    def test_redirect_never_reveals_answer_text(self) -> None:
        # 재고 발화는 결정론 고정 템플릿뿐이라 기대정답 원문이 낄 자리가 구조적으로 없다.
        cd = decide_completion(
            prior_review_remaining=0,
            already_completed=False,
            final_answer_correct=False,
            final_answer_incorrect=True,
        )
        assert cd.prompt in (_REDIRECT_PROMPT, _REDIRECT_PROMPT_SPECIFIC)


class TestCorrectWinsOverIncorrect:
    """방어 — correct·incorrect가 동시에 True로 들어와도 correct가 우선한다(설계 문서 명시)."""

    def test_correct_wins_over_incorrect(self) -> None:
        cd = decide_completion(
            prior_review_remaining=0,
            already_completed=False,
            final_answer_correct=True,
            final_answer_incorrect=True,
        )
        assert cd.action is CompletionAction.ENTER_REVIEW


class TestUnverifiableIsInert:
    """미검증·사변(correct도 incorrect도 아님) → NONE(완료도 재고도 없음·false redirect 금지)."""

    def test_none_on_unverifiable(self) -> None:
        cd = decide_completion(
            prior_review_remaining=0,
            already_completed=False,
            final_answer_correct=False,
            final_answer_incorrect=False,
        )
        assert cd.action is CompletionAction.NONE
        assert cd.problem_complete is False
        assert cd.awaiting_reflection is False
        assert cd.prompt is None
        assert cd.review_turns_remaining_after == 0


class TestAlreadyCompletedIsInert:
    """이미 완료된 세션 — 정답/오답 신호와 무관하게 항상 NONE(재완료·중복 재고 금지)."""

    def test_none_when_already_completed_correct(self) -> None:
        cd = decide_completion(
            prior_review_remaining=0, already_completed=True, final_answer_correct=True
        )
        assert cd.action is CompletionAction.NONE
        assert cd.problem_complete is False
        assert cd.prompt is None

    def test_none_when_already_completed_incorrect(self) -> None:
        cd = decide_completion(
            prior_review_remaining=0,
            already_completed=True,
            final_answer_correct=False,
            final_answer_incorrect=True,
        )
        assert cd.action is CompletionAction.NONE
        assert cd.prompt is None

    def test_none_when_already_completed_with_stale_review_remaining(self) -> None:
        # already_completed는 prior_review_remaining보다 우선한다(방어적 순서 — 재완료 절대 금지).
        cd = decide_completion(
            prior_review_remaining=1, already_completed=True, final_answer_correct=False
        )
        assert cd.action is CompletionAction.NONE
        assert cd.problem_complete is False


class TestDecisionShape:
    """`CompletionDecision` 모델 계약 — frozen·extra forbid·review_turns_remaining_after >= 0."""

    def test_all_actions_have_non_negative_review_remaining(self) -> None:
        for cd in (
            decide_completion(
                prior_review_remaining=0, already_completed=False, final_answer_correct=True
            ),
            decide_completion(
                prior_review_remaining=1, already_completed=False, final_answer_correct=False
            ),
            decide_completion(
                prior_review_remaining=2, already_completed=False, final_answer_correct=False
            ),
            decide_completion(
                prior_review_remaining=0,
                already_completed=False,
                final_answer_correct=False,
                final_answer_incorrect=True,
            ),
            decide_completion(
                prior_review_remaining=0, already_completed=True, final_answer_correct=True
            ),
        ):
            assert cd.review_turns_remaining_after >= 0

    def test_decision_is_frozen(self) -> None:
        cd = decide_completion(
            prior_review_remaining=0, already_completed=False, final_answer_correct=True
        )
        with pytest.raises(ValidationError):  # pydantic frozen=True — 필드 재할당 거부.
            cd.action = CompletionAction.NONE  # type: ignore[misc]


class TestCompletionAckClaimsOnlyWhatIsVerified:
    """완료 인정 발화는 *검증된 것*만 말한다 (S3-22 회수 · 원 커밋 edd0ab3).

    사고(2026-07-22 Kiki 실기기): 정답 후 돌아보기에 엉뚱한 근거("3")를 내도 완료 발화가
    "좋아, 근거가 분명하네. 스스로 풀어내고 왜 그런지까지 설명했어"로 *거짓 칭찬*했다. 원인은
    돌아보기 응답을 아무도 검증하지 않는데(rubber-stamp MVP) 발화만 설명 품질을 단언한 것이다.
    CLAUDE.md 금기 "확실하지 않을 때 자신 있게 말함" 위반이 학생에게 그대로 노출된 상태였다.

    이 시점에 *검증된* 사실은 하나뿐이다 — 완료는 `final_answer_correct`에서만 나오므로
    "스스로 풀어냈다"는 참이다. 돌아보기의 *내용*은 무엇도 참으로 주장할 수 없다.

    가드 설계: 금지 어구를 길게 열거하는 대신, 미검증 대상을 가리키는 **명사 두 개**(근거·설명)의
    부재로 본다 — 발화가 돌아보기 내용을 언급하는 순간 그것은 검증되지 않은 주장이기 때문이다.
    표기를 바꿔 되살린 변형("근거가 명확하네"·"잘 설명했어")도 같은 명사를 쓰므로 함께 잡힌다.
    한계(명시): 두 명사를 피해 같은 주장을 하는 문장(예: "이유를 잘 짚었어")은 못 잡는다 —
    그런 변경은 의도적일 수밖에 없고, 그때는 이 테스트가 요구하는 근거 제시가 리뷰 지점이 된다.
    """

    # 돌아보기 *내용*을 가리키는 명사 — 검증되지 않으므로 완료 발화가 언급할 수 없다.
    _UNVERIFIED_CLAIM_NOUNS = ("근거", "설명")

    def _ack_prompt(self) -> str:
        """COMPLETE 전이가 실제로 내보내는 발화 — 상수 직참조가 아니라 상태머신을 통과시킨다."""
        cd = decide_completion(
            prior_review_remaining=1,
            already_completed=False,
            final_answer_correct=True,
        )
        assert cd.action is CompletionAction.COMPLETE
        assert cd.prompt is not None
        return cd.prompt

    def test_ack_does_not_claim_unverified_reflection_quality(self) -> None:
        prompt = self._ack_prompt()
        found = [n for n in self._UNVERIFIED_CLAIM_NOUNS if n in prompt]
        assert found == [], (
            f"완료 발화가 검증되지 않은 돌아보기 내용을 주장한다: {found} — 발화={prompt!r}. "
            "돌아보기 응답은 검증되지 않으므로 그 품질·존재를 단언할 수 없다(S3-22)."
        )

    def test_ack_still_affirms_what_is_verified(self) -> None:
        """대조군 — 주장을 걷어낸 나머지가 공허해지지 않았는가.

        이 단언이 없으면 발화를 빈 문자열로 만드는 과잉 수정도 위 테스트를 통과한다.
        """
        prompt = self._ack_prompt()
        assert "스스로 풀어냈" in prompt, (
            "완료는 정답 도달에서만 나오므로 '스스로 풀어냈다'는 *참*이다 — "
            f"이 인정까지 지우면 격려가 사라진다. 발화={prompt!r}"
        )
        assert _ACK_MARK in prompt, f"다음 문항으로의 이행 안내가 사라졌다: {prompt!r}"

    def test_ack_is_tone_safe(self) -> None:
        """정직화가 부정 강화로 넘어가지 않았는가 — 칭찬을 빼는 것이지 지적을 넣는 것이 아니다."""
        _assert_tone_safe(self._ack_prompt())
