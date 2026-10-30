"""금지모드 가드 폴백 재질문 단위테스트 — PED-23 회수(원 PED-07·정본 04g §9·04d §2.2 선례).

`fallback_reply_for`는 위반 발화를 *대체*하는 안전한 소크라테스식 재질문(결정론 템플릿)을 낸다.
핵심 봉인: ① 반환값은 전량 `EXAMPLE_QUESTION` 기존 자산(신규 학생-대면 프로즈 0) ② 전역함수
(미정의 모드에도 안전 기본값·예외 0) ③ 폴백 자체가 가드·톤필터를 다시 위반하지 않는다(폴백
루프·2차 치환 없음 — 실 코퍼스 7팩 전수 확인).
"""

from __future__ import annotations

from whymath_backend.l4.pedagogy.mode_guard import check_forbidden_modes, fallback_reply_for
from whymath_backend.l4.pedagogy.pack_registry import get_pedagogy_packs, reset_pack_cache
from whymath_backend.l4.socratic.categories import EXAMPLE_QUESTION, SocraticCategory
from whymath_backend.l4.tone_filter import filter_tone
from whymath_backend.schema.pedagogy_pack import FORBIDDEN_MODE_VOCAB


class TestFallbackReply:
    def test_worked_example_first_maps_to_clarification(self) -> None:
        """WORKED_EXAMPLE_FIRST(정의·정답 단정) → 명료화 재질문 — 말하기 대신 묻기(04d §2.2)."""
        assert fallback_reply_for("WORKED_EXAMPLE_FIRST") == (
            EXAMPLE_QUESTION[SocraticCategory.CLARIFICATION]
        )

    def test_total_over_vocab_and_reuses_canonical_assets_only(self) -> None:
        """7개 금지 모드 전부에 대해 비어있지 않은 *기존 자산* 문자열을 반환(신규 프로즈 0)."""
        canonical = set(EXAMPLE_QUESTION.values())
        for mode in FORBIDDEN_MODE_VOCAB:
            reply = fallback_reply_for(mode)
            assert reply  # 비어있지 않음 — 폴백은 항상 서빙 가능해야 한다.
            assert reply in canonical  # 스펙 정본 예시 질문만(교수학 검수 통과 자산).

    def test_unknown_mode_gets_safe_default(self) -> None:
        """미정의 모드(방어적 경계)도 안전 기본값(명료화) — 예외 0·전역함수."""
        assert fallback_reply_for("NOT_A_MODE") == (
            EXAMPLE_QUESTION[SocraticCategory.CLARIFICATION]
        )

    def test_fallback_is_tone_clean(self) -> None:
        """폴백 재질문은 톤필터 무치환(금지 6패턴 미포함) — 2차 재작성 없는 안전 자산."""
        for mode in FORBIDDEN_MODE_VOCAB:
            reply = fallback_reply_for(mode)
            filtered, report = filter_tone(reply)
            assert filtered == reply
            assert report.rewritten is False

    def test_fallback_never_retriggers_guard(self) -> None:
        """폴백 재질문은 실 코퍼스 7팩 어느 것에도 재위반하지 않는다 — 폴백 루프 불가 봉인."""
        reset_pack_cache()
        packs = get_pedagogy_packs()
        assert len(packs) == 7  # 전수(7 지식유형) — 부분 확인 아님.
        for pack in packs.values():
            for mode in FORBIDDEN_MODE_VOCAB:
                assert check_forbidden_modes(pack, fallback_reply_for(mode)) is None
