"""L6 수능(정시) 모드 게이팅 단위테스트 — 적격성·우선순위·선별·저작권 게이트.

검증:
  ① 대상 페르소나(A·B·C) + 수능 신호(수능 exam_type / 시그니처 패턴 / persona_fit 충족)
     → 적격(True).
  ② 비응시 페르소나(D 학종·E 영재) → 부적격(False).
  ③ 본문 미보유 출처(평가원/EBS/교과서) → 저작권 노출 게이트로 차단(수능 exam_type라도 False).
  ④ 적합 신호 전무(기출 유형 아님·시그니처 없음·적합도 미달) → 부적격(False).
  ⑤ `select_suneung_items` — 혼합 풀에서 권위가중 순(수능>모평>학평)·limit 동작.
  ⑥ `suneung_priority` 단조성 — exam_authority_weight 큰 쪽이 큼·시그니처 가중 등.

합성 픽스처만(실데이터 0). `_problem(**over)` 빌더로 자체생성 최소 문항을 만들고 오버라이드한다
(`tests/backend/l6/retake/test_gating.py`·`tests/backend/schema/test_problem.py` 헬퍼 패턴 답습).

레이어(CLAUDE.md): 테스트는 L1(`schema.problem`·`schema.enums`)·L6(`l6.suneung`)만 import한다.
"""

from __future__ import annotations

import pytest

from whymath_backend.l6.suneung.gating import (
    METADATA_ONLY_SOURCES,
    SUNEUNG_PERSONAS,
    is_suneung_eligible,
    select_suneung_items,
    suneung_priority,
)
from whymath_backend.schema.enums import (
    Curriculum,
    ExamType,
    Persona,
    ReviewStatus,
    SignaturePattern,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem


def _problem(**over: object) -> Problem:
    """본문 보유가 허용되는 최소 자체생성 Problem 빌더(합성 픽스처).

    기본은 `source_type=자체생성`(저작권 노출 게이트를 통과하는 출처)이라 수능 적합 신호만
    오버라이드하면 적격/부적격을 자유로이 만든다. 본문 미보유 출처(평가원/EBS/교과서)는
    `source_type=...`로 오버라이드해 저작권 게이트를 시험한다.
    (`l6/retake/test_gating.py`의 `_problem` 패턴 답습 — type: ignore도 동일.)
    """
    kwargs: dict[str, object] = {
        "source_type": SourceType.자체생성,
        # PB-03 — 검수 노출 게이트(`is_review_cleared`) 추가로 기본값도 approved가 필요.
        "review_status": ReviewStatus.approved,
        "curriculum_version": Curriculum.REVISION_2022,
        "valid_from_year": 2022,
        "subject": Subject.미적분,
        "unit_codes": ["CAL-INT-DEF"],
        # EOS-31 — 수능 출제 범위 축(범위 안 코드). 주입이 없으면 게이트가 `UNKNOWN`으로 거절한다.
        "achievement_standard_codes": ["[12대수01-01]"],
    }
    kwargs.update(over)
    return Problem(**kwargs)  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────
# 게이팅 상수
# ──────────────────────────────────────────────────────────────────────
class TestConstants:
    def test_suneung_personas_are_a_b_c(self) -> None:
        """수능 대상 페르소나는 정확히 A(일반고고3)·B(자사고N수)·C(검정고시N수) 셋."""
        assert SUNEUNG_PERSONAS == frozenset(
            {Persona.A_일반고고3, Persona.B_자사고N수, Persona.C_검정고시N수}
        )

    def test_suneung_personas_exclude_d_and_e(self) -> None:
        """학종(D)·영재(E)는 정시 모드 대상이 아니다(수시·심화 트랙)."""
        assert Persona.D_학종고2 not in SUNEUNG_PERSONAS
        assert Persona.E_홈스쿨링영재 not in SUNEUNG_PERSONAS

    def test_metadata_only_sources_are_three_no_body_sources(self) -> None:
        """저작권 게이트 차단 집합은 평가원·EBS·교과서(본문 미보유 3종)."""
        assert METADATA_ONLY_SOURCES == frozenset(
            {SourceType.평가원, SourceType.EBS, SourceType.교과서}
        )


# ──────────────────────────────────────────────────────────────────────
# is_suneung_eligible — 적격성 게이트
# ──────────────────────────────────────────────────────────────────────
class TestIsSuneungEligible:
    def test_target_persona_with_suneung_exam_type_eligible(self) -> None:
        """A 페르소나 + 수능 exam_type 자체생성 문항 → 적격(기출 유형 신호로 통과)."""
        problem = _problem(exam_type=ExamType.수능)
        assert is_suneung_eligible(problem, Persona.A_일반고고3) is True

    def test_default_persona_is_a_general_high_grade3(self) -> None:
        """persona 인자 생략 시 기본 A_일반고고3(MVP 정시 정면 대상)."""
        problem = _problem(exam_type=ExamType.모평)
        # persona 미지정 → A로 판정되어 적격.
        assert is_suneung_eligible(problem) is True

    def test_target_persona_with_signature_patterns_eligible(self) -> None:
        """B 페르소나 + 시그니처 패턴 보유면 기출 유형이 아니어도 적격."""
        problem = _problem(
            exam_type=ExamType.자체생성,  # 기출 유형 신호 아님
            signature_patterns=[SignaturePattern.COMPOUND_CHOICES],
        )
        assert is_suneung_eligible(problem, Persona.B_자사고N수) is True

    def test_target_persona_with_sufficient_fit_eligible(self) -> None:
        """C 페르소나 + persona_fit 충족(>=0.5)이면 기출·시그니처 없어도 적격."""
        problem = _problem(persona_fit={Persona.C_검정고시N수: 0.8})
        assert is_suneung_eligible(problem, Persona.C_검정고시N수) is True

    def test_target_persona_fit_at_threshold_is_eligible(self) -> None:
        """경계값 — persona_fit == min_fit(0.5)이면 적격(>= 비교)."""
        problem = _problem(persona_fit={Persona.A_일반고고3: 0.5})
        assert is_suneung_eligible(problem, Persona.A_일반고고3, min_fit=0.5) is True

    def test_mopyeong_and_hakpyeong_exam_types_are_signals(self) -> None:
        """모평·학평도 권위 있는 기출 유형 신호로 인정된다."""
        for exam in (ExamType.모평, ExamType.학평):
            problem = _problem(exam_type=exam)
            assert is_suneung_eligible(problem, Persona.A_일반고고3) is True, exam

    def test_non_suneung_exam_types_are_not_signals(self) -> None:
        """EBS교재·N제·자체생성 exam_type은 그 자체로는 기출 유형 신호가 아니다.

        다른 적합 신호(시그니처·적합도)가 없으면 부적격이어야 한다.
        """
        for exam in (ExamType.EBS교재, ExamType.N제, ExamType.자체생성):
            problem = _problem(exam_type=exam)  # 시그니처·적합도 없음
            assert is_suneung_eligible(problem, Persona.A_일반고고3) is False, exam

    def test_non_target_personas_rejected(self) -> None:
        """비응시 페르소나(D·E) → 부적격 — 수능 신호가 있어도 막힌다."""
        # 수능 exam_type + 시그니처 + 높은 적합도라도 비응시 페르소나면 ① 게이트에서 탈락.
        problem = _problem(
            exam_type=ExamType.수능,
            signature_patterns=[SignaturePattern.CONDITION_LIST],
            persona_fit={Persona.D_학종고2: 0.9, Persona.E_홈스쿨링영재: 0.9},
        )
        for persona in (Persona.D_학종고2, Persona.E_홈스쿨링영재):
            assert is_suneung_eligible(problem, persona) is False, persona

    def test_no_signals_rejected(self) -> None:
        """적합 신호 전무(기출 유형 아님·시그니처 없음·적합도 미달) → 부적격."""
        problem = _problem(
            exam_type=ExamType.자체생성,  # 기출 유형 아님
            signature_patterns=[],  # 시그니처 없음
            persona_fit={Persona.A_일반고고3: 0.3},  # 0.5 미만
        )
        assert is_suneung_eligible(problem, Persona.A_일반고고3) is False

    def test_no_exam_type_and_no_other_signals_rejected(self) -> None:
        """exam_type=None(미지정)이고 다른 신호도 없으면 부적격."""
        problem = _problem()  # exam_type 기본 None·시그니처 빈 리스트·적합도 없음
        assert is_suneung_eligible(problem, Persona.A_일반고고3) is False

    def test_copyright_gate_blocks_metadata_only_sources(self) -> None:
        """저작권 노출 게이트 — 본문 미보유 출처는 A 페르소나·수능 신호라도 차단.

        평가원/EBS/교과서는 본문 미보유(구조 메타 전용)라 학생 노출 불가 →
        ② 게이트에서 무조건 탈락. 수능 모드는 평가원 기출 본문 복제 절대 금지가 핵심이라
        이 게이트가 특히 중요하다(자체생성 동등문제만 노출). 본문 필드(question_text 등)를
        비워 둬야 Problem 검증을 통과하므로 빌더 기본(본문 None)을 그대로 쓰되 source_type만 바꾼다.
        """
        for source in (SourceType.평가원, SourceType.EBS, SourceType.교과서):
            problem = _problem(
                source_type=source,
                exam_type=ExamType.수능,  # 권위 있는 기출 유형이어도
                signature_patterns=[SignaturePattern.GRAPH_SHAPE_INFERENCE],  # 시그니처가 있어도
                persona_fit={Persona.A_일반고고3: 0.99},  # 적합도가 높아도
            )
            assert is_suneung_eligible(problem, Persona.A_일반고고3) is False, source

    def test_use_enum_values_string_keys_handled(self) -> None:
        """use_enum_values=True로 persona_fit 키가 문자열이어도 적합도가 조회된다.

        Problem이 use_enum_values=True라, 키를 enum이 아닌 *문자열 값*으로 줘도
        `_persona_fit`이 문자열 폴백으로 적중해야 한다(정규화 계약).
        """
        problem = _problem(persona_fit={Persona.C_검정고시N수.value: 0.7})
        assert is_suneung_eligible(problem, Persona.C_검정고시N수) is True


# ──────────────────────────────────────────────────────────────────────
# suneung_priority — 우선순위 가중치(단조성)
# ──────────────────────────────────────────────────────────────────────
class TestSuneungPriority:
    def test_higher_authority_weight_increases_priority(self) -> None:
        """exam_authority_weight가 큰 쪽(수능>모평>학평)이 우선순위가 크다(다른 조건 동일)."""
        suneung = _problem(difficulty_overall=3.0, exam_authority_weight=1.0)  # 수능
        mopyeong = _problem(difficulty_overall=3.0, exam_authority_weight=0.8)  # 모평
        hakpyeong = _problem(difficulty_overall=3.0, exam_authority_weight=0.5)  # 학평
        assert suneung_priority(suneung) > suneung_priority(mopyeong)
        assert suneung_priority(mopyeong) > suneung_priority(hakpyeong)

    def test_signature_patterns_increase_priority(self) -> None:
        """시그니처 패턴이 있으면 없을 때보다 우선순위가 크다(다른 조건 동일)."""
        with_sig = _problem(
            difficulty_overall=3.0,
            signature_patterns=[SignaturePattern.CASE_ANALYSIS_DEEP],
        )
        without_sig = _problem(difficulty_overall=3.0)
        assert suneung_priority(with_sig) > suneung_priority(without_sig)

    def test_higher_difficulty_increases_priority(self) -> None:
        """종합 난이도가 높을수록 우선순위가 크다(보조 축·다른 조건 동일)."""
        hard = _problem(difficulty_overall=5.0)
        easy = _problem(difficulty_overall=1.0)
        assert suneung_priority(hard) > suneung_priority(easy)

    def test_none_authority_and_difficulty_treated_as_zero(self) -> None:
        """exam_authority_weight=None·difficulty_overall=None은 0.0으로 취급."""
        bare = _problem()  # 둘 다 기본 None·시그니처 없음
        assert suneung_priority(bare) == 0.0

    def test_authority_outweighs_signature(self) -> None:
        """출처 권위(수능 ×2.0=2.0)가 시그니처 단독(+1.0)보다 크다(상대 순서 계약)."""
        suneung_only = _problem(exam_authority_weight=1.0)  # 1.0×2.0 = 2.0
        signature_only = _problem(signature_patterns=[SignaturePattern.CONDITION_LIST])  # +1.0
        assert suneung_priority(suneung_only) > suneung_priority(signature_only)

    def test_priority_is_deterministic(self) -> None:
        """같은 입력은 같은 가중치(결정적)·가중 합 정확."""
        problem = _problem(
            difficulty_overall=4.0,
            exam_authority_weight=1.0,
            signature_patterns=[SignaturePattern.COMPOUND_CHOICES],
        )
        # 권위(1.0×2.0=2.0) + 시그니처(+1.0) + 난이도(4.0) = 7.0
        assert suneung_priority(problem) == suneung_priority(problem) == 7.0

    def test_empty_signature_patterns_no_bonus(self) -> None:
        """빈 signature_patterns([])는 *존재하지 않음*으로 취급 — 가산 없음."""
        empty = _problem(difficulty_overall=2.0, signature_patterns=[])
        bare = _problem(difficulty_overall=2.0)
        assert suneung_priority(empty) == suneung_priority(bare) == 2.0


# ──────────────────────────────────────────────────────────────────────
# select_suneung_items — 선별·정렬·limit
# ──────────────────────────────────────────────────────────────────────
class TestSelectSuneungItems:
    def test_filters_to_eligible_only(self) -> None:
        """혼합 풀(학종전용·신호없음·수능적합 섞음)에서 수능 적합만 남는다."""
        suneung_item = _problem(
            slug="suneung-fit",
            exam_type=ExamType.수능,
            persona_fit={Persona.A_일반고고3: 0.9},
        )
        # 학종 전용(A 적합도 미달·기출 유형 아님·시그니처 없음) → 탈락.
        haksong_item = _problem(
            slug="haksong-only",
            exam_type=ExamType.자체생성,
            persona_fit={Persona.D_학종고2: 0.9, Persona.A_일반고고3: 0.1},
        )
        # 신호 전무 → 탈락.
        blank_item = _problem(slug="blank", exam_type=ExamType.N제)

        selected = select_suneung_items(
            [haksong_item, suneung_item, blank_item], Persona.A_일반고고3
        )
        assert [p.slug for p in selected] == ["suneung-fit"]

    def test_orders_by_authority_weight_descending(self) -> None:
        """권위가중 순(수능>모평>학평)으로 앞에 온다(우선순위 내림차순)."""
        # 셋 다 A에게 수능 적합(수능 exam_type). 권위 가중치만 다르게 설계.
        hakpyeong = _problem(
            slug="hakpyeong",
            exam_type=ExamType.학평,
            exam_authority_weight=0.5,
        )  # 0.5×2.0 = 1.0
        suneung = _problem(
            slug="suneung",
            exam_type=ExamType.수능,
            exam_authority_weight=1.0,
        )  # 1.0×2.0 = 2.0
        mopyeong = _problem(
            slug="mopyeong",
            exam_type=ExamType.모평,
            exam_authority_weight=0.8,
        )  # 0.8×2.0 = 1.6

        # 입력은 우선순위 역순으로 줘서 정렬이 실제로 일어나는지 본다.
        selected = select_suneung_items([hakpyeong, mopyeong, suneung], Persona.A_일반고고3)
        assert [p.slug for p in selected] == ["suneung", "mopyeong", "hakpyeong"]

    def test_limit_truncates_to_top_n(self) -> None:
        """limit이 상위 N개로 자른다(우선순위 상위부터)."""
        items = [
            _problem(
                slug=f"item-{i}",
                exam_type=ExamType.수능,
                exam_authority_weight=1.0,
                difficulty_overall=float(i),
            )
            for i in (1, 2, 3, 4, 5)
        ]
        # 난이도 5,4가 상위 2개(권위 2.0 동일 + 난이도).
        selected = select_suneung_items(items, Persona.A_일반고고3, limit=2)
        assert [p.slug for p in selected] == ["item-5", "item-4"]

    def test_limit_none_returns_all_eligible(self) -> None:
        """limit=None(기본) → 적격 전부 반환(무제한)."""
        items = [_problem(slug=f"i-{i}", exam_type=ExamType.수능) for i in range(3)]
        selected = select_suneung_items(items, Persona.A_일반고고3)
        assert len(selected) == 3

    def test_limit_zero_returns_empty(self) -> None:
        """limit=0 → 빈 리스트(상위 0개)."""
        items = [_problem(exam_type=ExamType.수능)]
        assert select_suneung_items(items, Persona.A_일반고고3, limit=0) == []

    def test_empty_input_returns_empty(self) -> None:
        """빈 입력 → 빈 결과."""
        assert select_suneung_items([], Persona.A_일반고고3) == []

    def test_non_target_persona_selects_nothing(self) -> None:
        """비응시 페르소나(D)면 적합 문항이 많아도 전부 탈락 → 빈 결과."""
        items = [
            _problem(
                exam_type=ExamType.수능,
                persona_fit={Persona.D_학종고2: 0.9},
            )
            for _ in range(3)
        ]
        assert select_suneung_items(items, Persona.D_학종고2) == []

    def test_copyright_blocked_items_excluded_from_selection(self) -> None:
        """선별에서도 본문 미보유 출처는 빠진다(저작권 게이트가 필터에 적용).

        수능 모드 핵심 — 평가원 기출 본문은 노출 불가(자체생성 동등문제만).
        """
        ok = _problem(slug="ok", exam_type=ExamType.수능)
        # 평가원 출처(본문 미보유) — 수능 기출이어도 노출 불가.
        blocked = _problem(
            slug="blocked",
            source_type=SourceType.평가원,
            exam_type=ExamType.수능,
        )
        selected = select_suneung_items([blocked, ok], Persona.A_일반고고3)
        assert [p.slug for p in selected] == ["ok"]

    def test_default_persona_used_when_omitted(self) -> None:
        """persona 생략 시 기본 A로 선별(MVP 정시 정면 대상)."""
        items = [_problem(slug=f"d-{i}", exam_type=ExamType.수능) for i in range(2)]
        # persona 미지정 → A로 판정되어 둘 다 적격.
        selected = select_suneung_items(items)
        assert {p.slug for p in selected} == {"d-0", "d-1"}

    def test_stable_sort_preserves_input_order_on_ties(self) -> None:
        """동률(같은 우선순위)은 입력 순서를 보존한다(안정정렬 계약)."""
        # 셋 다 수능 exam_type·권위 1.0·난이도 3.0·시그니처 없음 → 동일 우선순위(5.0).
        first = _problem(
            slug="first",
            exam_type=ExamType.수능,
            exam_authority_weight=1.0,
            difficulty_overall=3.0,
        )
        second = _problem(
            slug="second",
            exam_type=ExamType.수능,
            exam_authority_weight=1.0,
            difficulty_overall=3.0,
        )
        third = _problem(
            slug="third",
            exam_type=ExamType.수능,
            exam_authority_weight=1.0,
            difficulty_overall=3.0,
        )
        selected = select_suneung_items([first, second, third], Persona.A_일반고고3)
        assert [p.slug for p in selected] == ["first", "second", "third"]


class TestScopeGate:
    """EOS-31 — 출제 범위 게이트(②-c): 신호(③)가 아니라 **선결 조건**이다.

    각 시험은 정반대 대조군과 쌍이다. 범위 밖만 단언하면 "전부 거절하는 게이트"가 통과하고, 범위 안만
    단언하면 "범위를 안 보는 게이트"가 통과한다.
    """

    _OUT = ["[9수02-01]"]  # 중학교
    _UNKNOWN: list[str] = []

    @pytest.mark.parametrize(
        "signal",
        [
            {"exam_type": ExamType.수능},
            {"signature_patterns": [SignaturePattern.COMPOUND_CHOICES]},
            {"persona_fit": {Persona.A_일반고고3: 0.9}},
        ],
        ids=["exam_type", "signature", "persona_fit"],
    )
    def test_out_of_scope_item_is_rejected_whatever_the_signal(
        self, signal: dict[str, object]
    ) -> None:
        inside = _problem(**signal)
        outside = _problem(achievement_standard_codes=self._OUT, **signal)
        assert is_suneung_eligible(inside, Persona.A_일반고고3) is True  # 대조군
        assert is_suneung_eligible(outside, Persona.A_일반고고3) is False

    def test_unknown_scope_item_is_rejected_not_passed(self) -> None:
        """코드를 모르는 문항은 적격이 아니다(fail-closed) — 대조군은 같은 문항에 범위 안 코드를 단 것."""
        known = _problem(exam_type=ExamType.수능)
        unknown = _problem(exam_type=ExamType.수능, achievement_standard_codes=self._UNKNOWN)
        assert is_suneung_eligible(known, Persona.A_일반고고3) is True
        assert is_suneung_eligible(unknown, Persona.A_일반고고3) is False

    def test_scope_alone_is_not_enough_a_signal_is_still_required(self) -> None:
        """범위는 선결 조건이지 충분 조건이 아니다 — 범위 안이어도 수능 신호가 없으면 부적격이다."""
        in_scope_no_signal = _problem()  # 기출·시그니처·적합도 없음
        assert is_suneung_eligible(in_scope_no_signal, Persona.A_일반고고3) is False

    def test_select_drops_out_of_scope_items(self) -> None:
        keep = _problem(slug="keep", exam_type=ExamType.수능)
        drop = _problem(slug="drop", exam_type=ExamType.수능, achievement_standard_codes=self._OUT)
        selected = select_suneung_items([drop, keep], Persona.A_일반고고3)
        assert [p.slug for p in selected] == ["keep"]
