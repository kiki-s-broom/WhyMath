"""오개념 카탈로그 정합성 단위테스트 — doc 정본 32종(Phase 1 30 + S2-p 2).

스코프 정직(False-attribute 금기): doc에 명시·상세화된 32종만 등록(기존 22 + §5.4
교차검증 후보 8: 대수+2·기하+1·확률통계+1·함수+2·미적분+2 + S2-p 대수 2: 반대 근 선택·
인수 부호 반전), 미상세 항목 추정 작성 없음.
"""

from __future__ import annotations

import re

from whymath_backend.l3.symbolic_equivalence import IdentityVerdict, identity_status
from whymath_backend.l4.misconception import (
    CATALOG,
    CATALOG_BY_ID,
    Misconception,
    diagnose,
)
from whymath_backend.l4.misconception.match_gate import _DEFAULT_CONFIDENCE_FLOOR


class TestCatalogShape:
    def test_thirty_two_entries_doc_explicit_only(self) -> None:
        # doc 명시·상세화: 대수 37 + 기하 8 + 확률통계 7 + 함수 3
        #                 + 미적분 8 + 수열 2 + 삼각함수 2 + 벡터 1 = 68
        #                 (Phase 1 30 + S2-p 2 + 극값 MC 2 + 843 트랜치1~4 각 6 + 트랜치5 6
        #                  + MISC-21 3(앵커 A1·A2·A3 좌석 보강 — doc #65-67)
        #                  + MISC-40 1(미분 대단원 좌석 판정 — 미적분 doc #68))
        assert len(CATALOG) == 68

    def test_all_ids_unique(self) -> None:
        ids = [m.id for m in CATALOG]
        assert len(ids) == len(set(ids))

    def test_catalog_by_id_dict_consistent(self) -> None:
        assert set(CATALOG_BY_ID.keys()) == {m.id for m in CATALOG}
        for m in CATALOG:
            assert CATALOG_BY_ID[m.id] is m


class TestCanonicalIdsFromDoc:
    """doc L24-50에 *명시*된 ID가 모두 존재 — 정본 정합."""

    def test_algebra_seventeen(self) -> None:
        # 기존 7 + 슬 §5.4 추가 2(discriminant·root-loss) + S2-p 추가 2(반대 근·부호 반전)
        # + 843 트랜치1 6(분수덧셈·음수곱·음수빼기·절댓값·제곱근분배·합차공식 혼동)
        # + 843 트랜치2 6(거듭제곱 곱셈/거듭제곱·음수 제곱·분배 뒷항·음수 분배·차의 제곱) = 23
        algebra_ids = {
            "distribution-over-power",
            "sign-flip-in-inequality",
            "division-by-zero",
            "square-root-positivity",
            "exponent-zero",
            "fraction-cancellation",
            "log-distribution",
            "discriminant-negative-no-real-root",
            "root-loss-by-dividing",
            "opposite-root-selected",
            "factor-sign-flip",
            "fraction-addition-naive",
            "negative-times-negative",
            "subtract-negative-sign",
            "absolute-value-keeps-sign",
            "sqrt-distributes-over-sum",
            "difference-of-squares-confused",
            "exponent-product-multiplies",
            "power-of-power-adds",
            "negative-square-precedence",
            "distribute-first-term-only",
            "negative-distribute-sign",
            "square-of-difference-no-cross",
            "midpoint-sum-only",
            "scale-area-linear",
            "negative-even-power-sign",
            "combine-unlike-terms",
            "complete-square-naive",
            "conjugate-product-sum",
            "transpose-no-sign-change",
            "gcd-lcm-confused",
            "decimal-mult-place",
            "mixed-number-mult-whole",
            "remainder-theorem-sign",
            "vieta-sign-error",
        }
        assert algebra_ids.issubset(CATALOG_BY_ID.keys())
        for mid in (
            "discriminant-negative-no-real-root",
            "root-loss-by-dividing",
            "opposite-root-selected",
            "factor-sign-flip",
        ):
            assert CATALOG_BY_ID[mid].domain == "대수"

    def test_geometry_four(self) -> None:
        # 기존 3 + 슬 §5.4 추가 1(circle-radius-squared) + 843 트랜치5 4(비대수 확장)
        for mid in (
            "angle-sum-non-triangle",
            "similarity-vs-congruence",
            "area-perimeter-confusion",
            "circle-radius-squared",
            "trapezoid-area-no-half",
            "scale-volume-linear",
            "cone-volume-no-third",
            "circle-area-circumference",
        ):
            assert mid in CATALOG_BY_ID
        assert CATALOG_BY_ID["circle-radius-squared"].domain == "기하"
        for mid in (
            "trapezoid-area-no-half",
            "scale-volume-linear",
            "cone-volume-no-third",
            "circle-area-circumference",
        ):
            assert CATALOG_BY_ID[mid].domain == "기하"

    def test_probstat_four(self) -> None:
        # 기존 3 + 슬 §5.4 추가 1(mutually-exclusive-implies-independent) + 843 트랜치5 2
        for mid in (
            "gambler-fallacy",
            "prosecutor-fallacy",
            "mean-vs-median",
            "mutually-exclusive-implies-independent",
            "combination-no-denominator",
            "same-item-permutation-no-divide",
        ):
            assert mid in CATALOG_BY_ID
        assert CATALOG_BY_ID["mutually-exclusive-implies-independent"].domain == "확률통계"
        for mid in ("combination-no-denominator", "same-item-permutation-no-divide"):
            assert CATALOG_BY_ID[mid].domain == "확률통계"

    def test_function_three(self) -> None:
        # 기존 1 + 슬 §5.4 추가 2(composite·translation)
        for mid in (
            "invertibility-without-1-1",
            "composite-function-commutes",
            "translation-sign-flip",
        ):
            assert mid in CATALOG_BY_ID
            assert CATALOG_BY_ID[mid].domain == "함수"


class TestMisc21AnchorSeatIds:
    """MISC-21(2026-09-08) — G0 앵커 A1·A2·A3 좌석 보강 3종(doc #65-67)."""

    def test_algebra_two(self) -> None:
        for mid in ("bigger-denominator-bigger-fraction", "ratio-order-swapped"):
            assert mid in CATALOG_BY_ID
            assert CATALOG_BY_ID[mid].domain == "대수"

    def test_probstat_one(self) -> None:
        assert "addition-multiplication-rule-confused" in CATALOG_BY_ID
        assert CATALOG_BY_ID["addition-multiplication-rule-confused"].domain == "확률통계"

    def test_a5_not_promoted(self) -> None:
        """A5(고1 이차함수 최대·최소) 후보 M-id는 omission형이라 의도적 미승격 — 회귀 가드."""
        for mid in ("domain-restricted-vertex-only", "quadratic-max-min-endpoint-ignored"):
            assert mid not in CATALOG_BY_ID


class TestMisc40PowerRuleSeat:
    """MISC-40(2026-10-02) — 미적분Ⅰ '미분' 대단원 좌석 판정으로 신설된 1종(doc #68·M0671)."""

    _ID = "power-rule-step-omitted"

    def test_entry_shape(self) -> None:
        m = CATALOG_BY_ID[self._ID]
        assert m.domain == "미적분"
        # 신호는 **한 덩어리**다 — `("(x³)′", "= x²")` 두 토막 AND로 쪼개면 `= x²`가 흔한 토막이라 올바른
        # 풀이에도 발화한다(아래 test_correct_solutions_mentioning_both_fragments_stay_below_gate).
        assert m.signals == ("(x³)′ = x²",)
        # 정규식 채널은 일부러 두지 않았다 — 정규식 보유 항목은 동결 집합이고 새 채널은 측정 통과를
        # 함께 요구한다(TestRegexSignals). 이 항목의 본 용도는 객관식 distractor 역추적 좌석이다.
        assert m.regex_signals == ()

    def test_appended_after_existing_calculus_entries(self) -> None:
        # 순서 안정성 — 신규 항목은 도메인 기존 항목 *뒤*에 붙인다(진단 동률 정렬 회귀 가드).
        calculus = [m.id for m in CATALOG if m.domain == "미적분"]
        assert calculus[0] == "chain-rule-inner-derivative-omitted"
        assert calculus[-1] == self._ID
        assert len(calculus) == 8

    def test_counterexample_numbers_are_correct(self) -> None:
        # 반례의 수치(12·4·24)는 손으로 쓴 값이다 — SymPy로 실제 값을 확인해 문자열과 대조한다.
        import sympy as sp

        x = sp.symbols("x")
        assert sp.diff(x**3, x).subs(x, 2) == 12  # 정답 3x² 의 x=2 값
        assert (x**2).subs(x, 2) == 4  # 첫째 틀린 형태(계수 누락)
        assert (3 * x**3).subs(x, 2) == 24  # 둘째 틀린 형태(지수 감소 누락)
        counterexample = CATALOG_BY_ID[self._ID].counterexample
        for value in ("12", "4", "24"):
            assert value in counterexample, value

    def test_counterexample_does_not_reveal_the_answer(self) -> None:
        # 반례 문자열은 개입 발화 템플릿(`intervene._assemble_counterexample`)에 그대로 들어가 학생에게
        # 닿을 수 있다 — 정답식·규칙 문장을 적으면 답 미루기를 어긴다(독립 비판 F7). 값 비교만 남긴다.
        counterexample = CATALOG_BY_ID[self._ID].counterexample
        assert "정답" not in counterexample
        assert "3x²" not in counterexample  # 정답식(숫자·x² 값 비교에 쓰인 `3x³`과 구별)
        assert "내려오" not in counterexample and "줄어야" not in counterexample  # 규칙 문장

    def test_wrong_form_fires_and_correct_forms_stay_below_gate(self) -> None:
        # 틀린 첫째 형태는 표기 변이(위첨자·^·^{})와 무관하게 게이트 이상으로 발화한다.
        wrong = ("(x³)′ = x²", "f(x)=x^3일 때 (x^3)′=x^2 이다", "(x^{3})′ = x^{2}")
        # 정답 형태·정답 해설은 자기 오개념으로 게이트(0.65) 이상 발화하면 안 된다 — 정답에 틀렸다고 말하는
        # 오류가 놓치는 오류보다 해롭다(결정 우선순위 #1).
        correct = (
            "(x³)′ = 3x²",
            "(x^3)′=3x^2",
            "(x^{3})′ = 3x^{2}",
            "x의 세제곱을 미분하면 지수 3이 앞으로 내려와 3x의 제곱이 된다",
        )

        def conf(text: str) -> float:
            hit = next((d for d in diagnose(text, top_k=8) if d.misconception.id == self._ID), None)
            return 0.0 if hit is None else hit.confidence

        for text in wrong:
            assert conf(text) >= _DEFAULT_CONFIDENCE_FLOOR, text
        for text in correct:
            assert conf(text) < _DEFAULT_CONFIDENCE_FLOOR, text

    def test_explicit_correction_of_the_wrong_form_is_not_diagnosed(self) -> None:
        # 학생이 틀린 형태를 인용해 *부정*하면 확신 진단이 나가지 않는다(정정 억제 축이 이 항목에도 닿는다).
        text = "(x³)′ = x² 라는 풀이는 틀렸다"
        hit = next((d for d in diagnose(text, top_k=8) if d.misconception.id == self._ID), None)
        assert hit is None or hit.confidence < _DEFAULT_CONFIDENCE_FLOOR

    def test_correct_solutions_mentioning_both_fragments_stay_below_gate(self) -> None:
        # 실측 회귀(2026-10-02) — 신호가 `(x³)′`·`= x²` 두 토막 AND였을 때 아래 *올바른* 풀이 중 앞의 셋이
        # conf 1.0으로 발화했다(`= x²`는 `f(x) = x²`·`x³ = x²·x`처럼 올바른 풀이에도 흔한 토막이라 같은 글
        # 어딘가에 따로 있기만 해도 맞았다). 정답에 틀렸다고 말하는 오류가 놓치는 오류보다 해롭다
        # (결정 우선순위 #1). 한 덩어리 신호는 좌변 *바로 뒤*의 `= x²`만 잡으므로 전부 게이트 미만이다.
        correct_solutions = (
            "x³ = x²·x 이므로 (x³)′ = (x²·x)′ = 2x·x + x²·1 = 3x²",  # 곱의 미분으로 유도
            "f(x) = x² 이고 g(x) = x³ 일 때 (x³)′ = 3x² 이다",  # 무관한 `f(x) = x²` 병기
            "y = x² 의 그래프에서 (x³)′ = 3x² 이므로 기울기는 12",  # 무관한 `y = x²` 병기
            "(x³)′ + (x²)′ = 3x² + 2x",
            "(x²)′ = 2x, (x³)′ = 3x²",
            "x² = 4 이고 (x³)′ = 3x² 이다",
        )
        for text in correct_solutions:
            hit = next((d for d in diagnose(text, top_k=8) if d.misconception.id == self._ID), None)
            assert hit is None or hit.confidence < _DEFAULT_CONFIDENCE_FLOOR, text

    def test_wrong_form_inside_a_sentence_still_fires(self) -> None:
        # 한 덩어리로 좁힌 대가가 재현율 손실이 아님을 확인 — 문장 속에 박힌 틀린 형태는 여전히 잡힌다.
        text = "f(x)=x³ 이므로 f′(x) = (x³)′ = x² 이다"
        hit = next((d for d in diagnose(text, top_k=8) if d.misconception.id == self._ID), None)
        assert hit is not None and hit.confidence >= _DEFAULT_CONFIDENCE_FLOOR

    def test_known_limits_are_documented_not_hidden(self) -> None:
        # 한계(§5.3·문서 #68에 명시)를 *단언으로* 고정한다.
        # ① 미검출 — 둘째 형태(3x³)·아스키 아포스트로피는 못 잡는다.
        for text in ("(x³)′ = 3x³", "(x³)' = x²"):
            hit = next((d for d in diagnose(text, top_k=8) if d.misconception.id == self._ID), None)
            assert hit is None or hit.confidence < _DEFAULT_CONFIDENCE_FLOOR, text
        # ② 오탐 — 계수를 뒤에 쓴 *올바른* `(x³)′ = x²·3`은 접두가 같아 발화한다(희귀 표기·측정 전까지 한계).
        # 이 단언이 적색이 되면 누군가 이 오탐을 고친 것이니 문서 #68의 한계 ②와 카탈로그 주석을 함께 갱신하라.
        text = "(x³)′ = x²·3 이다"
        hit = next((d for d in diagnose(text, top_k=8) if d.misconception.id == self._ID), None)
        assert hit is not None and hit.confidence >= _DEFAULT_CONFIDENCE_FLOOR
        # ③ 오탐 — 틀린 형태를 대조 표지("가 아니라")로 인용한 올바른 풀이도 발화한다. 종결형 정정 어휘
        # (틀렸다·아니다)가 아니면 억제되지 않는 것은 substring 매처 **공통** 한계다(`diagnose.py`
        # `_CORRECTION_NEAR_SIGNAL` 주석 — "A가 아니라 B다"는 부정이 아니라 주장의 흔한 형식이라 일부러 안 막는다).
        # 이 단언이 적색이 되면 공통 한계가 풀린 것이니 문서 #68의 한계 ③과 판정 문서 §8을 함께 갱신하라.
        text = "(x³)′ = x² 가 아니라 (x³)′ = 3x² 이다"
        hit = next((d for d in diagnose(text, top_k=8) if d.misconception.id == self._ID), None)
        assert hit is not None and hit.confidence >= _DEFAULT_CONFIDENCE_FLOOR


class TestSuneungCanonicalIds:
    """doc #16-23에 *명시·상세화*된 수능 핵심 오개념 — domain별 정합."""

    def test_calculus_five(self) -> None:
        # 기존 3 + 슬 §5.4 추가 2(continuity·critical-point).
        # continuity-implies-differentiability는 doc 함수 슬롯 #15에 상세되나
        # domain은 미적분([H:12미적Ⅰ02-02] 정착)이라 본 도메인 집합에 포함.
        for mid in (
            "chain-rule-inner-derivative-omitted",
            "product-rule-naive",
            "limit-equals-function-value",
            "continuity-implies-differentiability",
            "critical-point-implies-extremum",
        ):
            assert mid in CATALOG_BY_ID
            assert CATALOG_BY_ID[mid].domain == "미적분"

    def test_sequence_two(self) -> None:
        for mid in (
            "geometric-series-always-converges",
            "term-to-zero-implies-convergence",
        ):
            assert mid in CATALOG_BY_ID
            assert CATALOG_BY_ID[mid].domain == "수열"

    def test_trig_two(self) -> None:
        for mid in ("sine-distributes-over-sum", "period-of-scaled-sine"):
            assert mid in CATALOG_BY_ID
            assert CATALOG_BY_ID[mid].domain == "삼각함수"

    def test_vector_one(self) -> None:
        assert CATALOG_BY_ID["dot-product-is-vector"].domain == "벡터"


class TestEntryFields:
    def test_every_entry_has_required_fields(self) -> None:
        for m in CATALOG:
            assert m.id
            assert m.name_kr
            assert m.canonical_statement
            assert m.counterexample
            assert m.signals
            assert len(m.signals) >= 1

    def test_immutable_frozen_pydantic(self) -> None:
        # `frozen=True` — catalog 엔트리 수정 차단(런타임 변경 회귀 가드)
        m = CATALOG[0]
        try:
            m.id = "mutated"  # type: ignore[misc]
        except (TypeError, ValueError):
            return  # 예상 — frozen
        raise AssertionError("frozen=True인데 수정됨")

    def test_domain_is_valid_literal(self) -> None:
        valid = {
            "대수",
            "기하",
            "확률통계",
            "함수",
            "미적분",
            "수열",
            "삼각함수",
            "벡터",
        }
        for m in CATALOG:
            assert m.domain in valid


class TestNameClarity:
    """`name_kr`은 짧고 부정 표현 없음(직접 라벨링 회피 — doc 절대 금지 §)."""

    def test_no_negative_labeling_words(self) -> None:
        banned = ("바보", "틀린", "잘못", "실수")
        for m in CATALOG:
            assert not any(b in m.name_kr for b in banned), m.id


class TestRegexSignals:
    """v1.2 `regex_signals` — 선택 필드(기본 빈 튜플)·현행 7종·전부 컴파일 가능(슬 102·후속 확장).

    슬 102 후속 보수적 확장: log-distribution(로그 합 분배·`log(2+3)=log2+log3`)를 추가했다.
    이 넷은 모두 *거짓 수치 항등식*만 매치하는 disjoint 정규식(명명그룹 역참조·`\\d+` 피연산자)이다.

    MISC-07 앵커 채널 3종 추가: 앵커 커버 오개념의 기계 채널이 0이던 상태를 해소한다. 앞의 넷과
    달리 *항등식*이 아니라 **풀이 흐름**(근의 부호 반전·근 손실·값↔좌표 혼동)을 겨냥하므로 판정
    축이 다르다 — 변별력은 `harness.anchor_detection_channel_eval`이 양성/음성 픽스처와 Wilson
    경계로 매 실행 측정한다(`tests/backend/harness/test_anchor_detection_channel_eval.py` 배선).

    이 집합이 *동결*인 이유: 정규식은 조용히 늘리기 쉬운데, 늘어난 채널이 정답을 오검출하면
    학생에게 "틀렸다"고 말하는 방향의 오류가 된다(결정 우선순위 #1). 그래서 새 채널은 이 목록에
    등재 + 측정 통과를 **함께** 요구한다.
    """

    #: 정규식 채널을 *가진* 항목의 동결 집합 — 여기 없는 항목이 채널을 얻으면 테스트가 적색.
    _DEMO_IDS = {
        # v1.2 거짓 수치 항등식 4종
        "distribution-over-power",
        "square-root-positivity",
        "fraction-cancellation",
        "log-distribution",
        # MISC-07 앵커 채널 3종 (A4 2 · A6 1)
        "root-loss-by-dividing",
        "factor-sign-flip",
        "extremum-value-vs-point-confused",
    }

    def test_field_defaults_empty_and_is_tuple(self) -> None:
        # 미설정 항목은 빈 튜플(하위호환 — substring 동작 불변)
        for m in CATALOG:
            assert isinstance(m.regex_signals, tuple)
            if m.id not in self._DEMO_IDS:
                assert m.regex_signals == (), m.id

    def test_demo_entries_have_regex(self) -> None:
        for mid in self._DEMO_IDS:
            assert CATALOG_BY_ID[mid].regex_signals, mid

    def test_all_regex_signals_compile(self) -> None:
        # 카탈로그의 모든 정규식은 컴파일 가능해야(런타임 re.error 회귀 가드)
        for m in CATALOG:
            for pat in m.regex_signals:
                re.compile(pat)  # 실패 시 re.error → 테스트 실패


class TestCanonicalWrongForm:
    """선택 필드 `canonical_wrong_form` — 거짓 항등식의 *머신 검증* 표현(동치 권위 일원화·감사 §7).

    핵심 불변식: 부여된 (lhs, rhs)는 `identity_status`(SymPy 단일 권위)로 **not_identity**여야
    한다 — 'wrong form이 실제로 틀렸다'를 문자열이 아닌 기호 권위로 못 박는다. 정직 스코프:
    SymPy가 가정 없이 반증 가능한 다항 거짓 항등식에만 부여(정의역 의존·초월·유리식은 미부여).
    """

    # SymPy가 not_identity로 반증 가능한 다항 거짓 항등식만(probe로 확정).
    _AUTHORED_IDS = {"distribution-over-power", "exponent-zero"}

    def test_field_optional_and_typed(self) -> None:
        for m in CATALOG:
            if m.canonical_wrong_form is None:
                continue
            assert isinstance(m.canonical_wrong_form, tuple)
            assert len(m.canonical_wrong_form) == 2
            lhs, rhs = m.canonical_wrong_form
            assert isinstance(lhs, str) and lhs.strip()
            assert isinstance(rhs, str) and rhs.strip()

    def test_authored_set_matches(self) -> None:
        authored = {m.id for m in CATALOG if m.canonical_wrong_form is not None}
        assert authored == self._AUTHORED_IDS

    def test_wrong_form_is_proven_false_by_sympy(self) -> None:
        """★권위 일원화: 부여된 wrong form은 SymPy가 *거짓임을 증명*한다(not_identity)."""
        for mid in self._AUTHORED_IDS:
            lhs, rhs = CATALOG_BY_ID[mid].canonical_wrong_form  # type: ignore[misc]
            verdict = identity_status(lhs, rhs)
            assert verdict is IdentityVerdict.not_identity, (mid, lhs, rhs, verdict)


class TestCorrectForm:
    """선택 필드 `correct_form` — identity-shaped 오개념의 정정 형태(정밀 −1 반박 신호·tier).

    부여 9종(distribution·a⁰·log·곱미분·sin 합분배 + 슬: 신호 정밀화로 gate-safe화된 square-root·
    fraction-cancellation·chain-rule + MISC-40 power-rule-step-omitted). 핵심 불변식: 정정 형태가 *자기 오개념*으로 신뢰 게이트(0.65)
    이상 confident 오진단되면 안 된다 — `signals`가 *틀린 RHS*를 포함해 정정 형태(올바른 RHS)와
    구분되는 오개념만 부여(LHS-only 느슨 신호는 신호 정밀화로 먼저 좁힌다).
    """

    _AUTHORED_IDS = {
        "distribution-over-power",
        "exponent-zero",
        "log-distribution",
        "product-rule-naive",
        "sine-distributes-over-sum",
        # 슬: 신호 정밀화(LHS식+틀린 RHS)로 gate-safe화 → correct_form 부여(#271 커버리지 완성).
        "square-root-positivity",
        "fraction-cancellation",
        "chain-rule-inner-derivative-omitted",
        # MISC-40: 연쇄법칙과 같은 설계(좌변만 공유·틀린 RHS 미포함)로 gate-safe.
        "power-rule-step-omitted",
    }

    def test_field_optional_and_typed(self) -> None:
        # 대부분 None(대체 불가 conceptual 오개념)·부여 항목은 비어있지 않은 str.
        for m in CATALOG:
            assert m.correct_form is None or isinstance(m.correct_form, str)
            if m.id not in self._AUTHORED_IDS:
                assert m.correct_form is None, m.id

    def test_authored_set_present_and_nonempty(self) -> None:
        # 초기 부여 5종이 실제로 correct_form을 갖는다(≥5 정밀 귀속 좌석).
        authored = {m.id for m in CATALOG if m.correct_form is not None}
        assert authored == self._AUTHORED_IDS
        assert len(authored) >= 5
        for mid in self._AUTHORED_IDS:
            assert CATALOG_BY_ID[mid].correct_form, mid

    def test_correct_form_distinct_from_wrong_statement(self) -> None:
        # 정정 형태 ≠ 학생의 틀린 진술(정정은 올바른 형태라야 의미가 있다).
        for mid in self._AUTHORED_IDS:
            m = CATALOG_BY_ID[mid]
            assert m.correct_form != m.canonical_statement, mid

    def test_correct_form_is_gate_safe(self) -> None:
        # 불변식 — 정정 형태를 진단하면 *자기 오개념*을 신뢰 게이트(0.65) 이상으로 내지 않는다
        # (정정 형태가 자기 오개념으로 confident 오진단되면 student_input에서 거짓 +1을 유발).
        for mid in self._AUTHORED_IDS:
            cf = CATALOG_BY_ID[mid].correct_form
            assert cf is not None
            self_match = next((x for x in diagnose(cf, top_k=8) if x.misconception.id == mid), None)
            assert self_match is None or self_match.confidence < _DEFAULT_CONFIDENCE_FLOOR, mid


class TestExposedSurface:
    def test_misconception_typed_as_basemodel(self) -> None:
        for m in CATALOG:
            assert isinstance(m, Misconception)
