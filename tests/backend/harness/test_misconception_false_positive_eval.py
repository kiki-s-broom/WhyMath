"""정답 해설 오진단 측정 테스트 (MISC-27).

코퍼스 전수를 도는 테스트는 1건만 둔다(9초). 나머지는 합성 입력으로 순수 로직을 밟는다 —
분류 규칙·분모 없는 0 금지·CLI 종료 코드 3종.
"""

from __future__ import annotations

import pytest

from whymath_backend.harness.misconception_false_positive_eval import (
    FalsePositive,
    FalsePositiveReport,
    classify_cause,
    evaluate,
    format_report,
    load_answer_explanations,
    main,
    weak_signal_gap,
)


def _fp(
    *,
    kebab_id: str = "division-by-zero",
    signals: tuple[str, ...] = ("분모", "0"),
    correction: bool = False,
) -> FalsePositive:
    return FalsePositive(
        kebab_id=kebab_id,
        confidence=1.0,
        matched_signals=signals,
        mentions_correction=correction,
        text="합성",
    )


class TestClassifyCause:
    """원인을 나누는 이유: 고칠 자리가 서로 다르다. 한 숫자에 섞으면 처방이 사라진다."""

    def test_regex_only_when_no_substring_matched(self) -> None:
        assert classify_cause(_fp(signals=())) == "regex-only"

    def test_weak_signals_only(self) -> None:
        """숫자-only signal만으로 full match된 경우 — 가장 순수한 신호 정밀도 결함."""
        assert classify_cause(_fp(kebab_id="exponent-zero", signals=("0",))) == "weak-signals-only"

    def test_weak_signal_mixed(self) -> None:
        """내용성 신호에 약한 토큰이 끼어 full match를 *완성*한 경우."""
        assert classify_cause(_fp(signals=("분모", "0"))) == "weak-signal-mixed"

    def test_two_signal_cooccurrence_when_all_contentful(self) -> None:
        """내용성 신호 2개짜리 항목 — 우연 공출현이 구조적으로 쉽다."""
        assert (
            classify_cause(_fp(kebab_id="composite-function-commutes", signals=("f∘g", "g∘f")))
            == "two-signal-cooccurrence"
        )

    def test_correction_mention_is_a_separate_axis_not_a_replacement(self) -> None:
        """정정 어휘 유무는 원인을 *대체*하지 않고 접미로 붙는다.

        해설이 오개념을 가르치려고 언급한 경우("…로 하면 틀린다")와 순수 오탐은 처방이
        다르다. 그런데 신호 유형 자체도 여전히 알아야 하므로 덮어쓰지 않고 덧붙인다 —
        접미가 아니라 치환이면 "약한 신호 때문인지"가 통계에서 사라진다.
        """
        assert classify_cause(_fp(correction=True)) == "weak-signal-mixed+correction-mention"
        assert classify_cause(_fp(signals=(), correction=True)) == "regex-only+correction-mention"


class TestReportArithmetic:
    def test_empty_population_ratio_is_none_not_zero(self) -> None:
        """모집단 0이면 비율은 `None`이다 — 0.0으로 두면 '완벽'으로 위장한다."""
        assert FalsePositiveReport(total=0, false_positives=()).fp_ratio is None

    def test_zero_false_positives_with_population_is_a_real_zero(self) -> None:
        """[대조군] 모집단이 있는데 오진단 0이면 그건 진짜 0이다(None이 아니다)."""
        assert FalsePositiveReport(total=10, false_positives=()).fp_ratio == 0.0

    def test_counts_group_by_cause_and_misconception(self) -> None:
        report = FalsePositiveReport(
            total=3,
            false_positives=(_fp(), _fp(), _fp(kebab_id="exponent-zero", signals=("0",))),
        )
        assert report.by_cause["weak-signal-mixed"] == 2
        assert report.by_misconception["division-by-zero"] == 2
        assert report.fp_ratio == 1.0


class TestEvaluateOnSyntheticText:
    def test_clean_prose_yields_no_false_positive(self) -> None:
        """오개념과 무관한 산문에는 후보가 안 나온다 — 측정기가 아무거나 잡지 않는다."""
        report = evaluate(["삼각형의 넓이는 밑변 곱하기 높이 나누기 2로 구한다."])
        assert report.total == 1
        assert report.false_positives == ()
        assert report.fp_ratio == 0.0

    def test_prose_that_trips_the_gate_is_counted_with_its_cause(self) -> None:
        """[결함 재현] 몫의 미분법 해설이 `division-by-zero`로 잡힌다 — 순수 오탐.

        `분모`와 `0`이 한 문장에 있을 뿐 나눗셈 오개념과 아무 관계가 없다. 이 문장이
        분류에서 `weak-signal-mixed`로 떨어지는 것이 이 도구의 존재 이유다.
        """
        text = "몫의 미분법에 따라 분자와 분모를 각각 미분해 조합하면 f'(-1)의 값은 0이다."
        report = evaluate([text])
        assert len(report.false_positives) == 1
        found = report.false_positives[0]
        assert found.kebab_id == "division-by-zero"
        assert found.cause == "weak-signal-mixed"


class TestRealCorpus:
    """실 코퍼스 1회 — 로더와 모집단이 살아 있는지(스캔 0건은 실패)."""

    def test_loader_finds_a_substantial_population(self) -> None:
        texts = load_answer_explanations()
        assert len(texts) > 5000, len(texts)
        assert len(texts) == len(set(texts)), "중복 제거가 안 됐다 — 비율이 생성기 물량에 좌우된다"

    def test_cli_ratchet_passes_at_the_wired_threshold(self) -> None:
        """CI가 쓰는 인자 그대로 exit 0 — 배선이 상시 red가 아님을 봉인한다."""
        assert main(["--max-fp-ratio", "0.07"]) == 0

    def test_cli_fails_when_threshold_is_unreachable(self) -> None:
        """[대조군] 도달 불가 임계를 주면 실제로 exit 1이 나온다(변별력 앵커).

        이 대조군이 없으면 "임계를 아예 안 본다"도 위 테스트를 통과한다.
        """
        assert main(["--max-fp-ratio", "0.0"]) == 1

    def test_cli_observes_without_a_threshold(self) -> None:
        """임계 미지정이면 관측만 하고 exit 0 — 기본이 게이트가 아님을 고정한다."""
        assert main([]) == 0

    def test_report_states_it_is_a_proxy_metric(self) -> None:
        """리포트가 대리 지표임을 본문에 밝힌다 — 학생 지표로 오인용되지 않게."""
        rendered = format_report(FalsePositiveReport(total=1, false_positives=()))
        assert "대리 지표" in rendered
        assert "학생 입력이 아니다" in rendered


@pytest.mark.parametrize("threshold", [0.0, 0.07])
def test_cli_exit_codes_are_only_zero_or_one_for_measurable_runs(threshold: float) -> None:
    """측정 가능한 실행의 종료 코드는 0/1뿐 — 2(측정 실패)는 모집단 0에만 쓴다."""
    assert main(["--max-fp-ratio", str(threshold)]) in (0, 1)


class TestWeakSignalGapRejectsProximityThreshold:
    """MISC-29가 근접 임계를 **기각**한 근거를 동결한다.

    판정을 산문으로만 남기면 다음 세션이 같은 가설을 처음부터 다시 세운다. 여기서
    동결하는 것은 특정 숫자가 아니라 **대소 관계**다 — 코퍼스가 바뀌어 관계가 뒤집히면
    red가 나서 "이제 다시 검토할 만하다"를 알린다.
    """

    #: 진짜 오개념 발화 — `division-by-zero`의 canonical_statement를 학생이 그대로 말한 형태.
    _TRUE_POSITIVE = "분모에 변수가 와도 항상 정의되니까 0을 넣어도 된다"
    #: 순수 오탐 — **실제 코퍼스 문장**(정답 해설). 몫의 미분법 설명이라 나눗셈 오개념과 무관.
    #:
    #: 코퍼스 원문을 그대로 쓰는 것이 중요하다. 처음엔 이 문장을 축약해 적었는데
    #: ("…조합하면 f'(0)의 값은 -14이다") 거리가 12가 아니라 13이 나와, 재려던 분포의
    #: 어느 버킷에도 속하지 않는 합성 문장을 재고 있었다 — 테스트가 그것을 잡았다.
    _FALSE_POSITIVE = (
        "몫의 미분법에 따라 분자와 분모를 각각 미분해 조합한 뒤 "
        "x = 0에서 계산하면 f'(0)의 값은 -14이다."
    )
    #: 정탐과 **같은 거리**에 놓이는 오탐 — 임계 불가의 가장 강한 형태.
    _FALSE_POSITIVE_SAME_GAP = (
        "몫의 미분법에 따라 분자와 분모를 각각 미분해 조합하면 f'(0)의 값은 -14이다."
    )

    def test_a_true_positive_sits_farther_than_a_real_corpus_false_positive(self) -> None:
        """[기각 근거 ①] 잡아야 할 문장이 걸러야 할 코퍼스 문장보다 **멀다**.

        이 부등호가 성립하는 한 어떤 거리 임계도 둘을 동시에 만족시킬 수 없다 —
        낮게 잡으면 정탐이 죽고 높게 잡으면 오탐이 남는다.
        """
        tp_gap = weak_signal_gap("division-by-zero", self._TRUE_POSITIVE)
        fp_gap = weak_signal_gap("division-by-zero", self._FALSE_POSITIVE)
        assert tp_gap is not None and fp_gap is not None
        assert tp_gap > fp_gap, (
            f"정탐 거리 {tp_gap} ≤ 오탐 거리 {fp_gap} — 분포가 갈라졌다면 "
            "MISC-29의 근접 임계 설계를 재검토할 시점이다"
        )

    def test_a_true_positive_and_a_false_positive_can_share_the_same_gap(self) -> None:
        """[기각 근거 ②] 잡아야 할 것과 걸러야 할 것이 **같은 거리**에 있다.

        ①의 역전보다 강한 증거다. 거리가 같으면 임계가 어디에 있든 두 문장은 항상
        같은 판정을 받는다 — 설계가 원리적으로 불가능함을 보인다.
        """
        tp_gap = weak_signal_gap("division-by-zero", self._TRUE_POSITIVE)
        fp_gap = weak_signal_gap("division-by-zero", self._FALSE_POSITIVE_SAME_GAP)
        assert tp_gap == fp_gap, f"정탐 {tp_gap} vs 오탐 {fp_gap}"

    def test_both_fixtures_actually_reach_the_diagnosis(self) -> None:
        """[대조군] 두 문장 모두 실제로 그 오개념을 발화시킨다.

        이 단언이 없으면 위 테스트는 "둘 다 매치 안 됨"으로도 통과할 수 있다 —
        거리만 재고 매치 여부를 안 보면 기각 근거가 공허해진다.
        """
        for text in (self._TRUE_POSITIVE, self._FALSE_POSITIVE, self._FALSE_POSITIVE_SAME_GAP):
            ids = [fp.kebab_id for fp in evaluate([text]).false_positives]
            assert "division-by-zero" in ids, text

    def test_gap_is_none_when_the_item_has_no_weak_signal(self) -> None:
        """약한 신호가 없는 항목은 `None` — '거리 0'과 '해당 없음'을 섞지 않는다."""
        assert weak_signal_gap("composite-function-commutes", "(f∘g)(1)과 (g∘f)(1)") is None

    def test_report_publishes_the_gap_distribution(self) -> None:
        """리포트가 거리 분포를 낸다 — 기각 판정이 매 실행 재현되게."""
        report = evaluate([self._FALSE_POSITIVE])
        rendered = format_report(report)
        assert "약한 신호 거리 분포" in rendered
        assert "겹친다" in rendered
