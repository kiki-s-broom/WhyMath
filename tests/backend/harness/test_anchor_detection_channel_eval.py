"""앵커 탐지 채널 변별력 측정의 계약 동결 (MISC-07).

이 파일이 있는 이유 — **배선 실재성**
-------------------------------------
측정 CLI를 만들어 두고 아무도 돌리지 않으면 "저장소에 존재함"이지 "돌아감"이 아니다
(CLAUDE.md: 검증 장치를 만들고 배선 확인 없이 완료 선언 금지). `tests/backend`는 CI backend
잡이 매 PR 실행하므로, 여기서 `main([])`을 부르는 것이 곧 **게이트의 CI 배선**이다.

무엇을 동결하는가
-----------------
  1. 게이트가 지금 통과한다(exit 0) — 채널 회귀 시 적색.
  2. 게이트가 **통과 가능**하다 — 음성 표본이 적으면 오검출 0건에서도 상한을 못 넘어 완벽한
     채널이 FAIL한다. 그 상태를 "채널 실패"로 오독하지 않도록 별도 축으로 검사한다.
  3. 커버 회계가 정직하다 — 채널을 못 붙인 2종이 리포트에서 사라지지 않는다("3종 부여"를
     "5종 커버"로 읽지 못하게).
  4. 픽스처가 비어 있지 않다 — 0건 스캔은 공허한 통과다.
"""

from __future__ import annotations

from whymath_backend.harness.anchor_detection_channel_eval import (
    DETECTION_FLOOR,
    FALSE_POSITIVE_CEILING,
    UNCHANNELABLE,
    _channel_fired,
    _gate_is_reachable,
    _survives_serving_gate,
    build_fixtures,
    build_report,
    main,
)
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID


class TestGatePasses:
    def test_cli_exits_zero(self) -> None:
        """CLI_게이트_통과 — 이 단언이 곧 CI 배선이다."""
        assert main([]) == 0

    def test_report_passed_flag(self) -> None:
        """리포트_통과_플래그"""
        assert build_report().passed is True


class TestGateIsReachable:
    """통과 가능성 — 완벽한 채널도 떨어뜨리는 게이트는 변별이 아니라 위장이다."""

    def test_every_channel_gate_can_be_passed(self) -> None:
        """모든_채널의_게이트가_도달_가능"""
        for fx in build_fixtures():
            assert _gate_is_reachable(len(fx.positives), len(fx.negatives)), (
                f"{fx.kebab_id}: 양성 {len(fx.positives)}·음성 {len(fx.negatives)}건으로는 "
                f"완벽한 채널도 경계 {DETECTION_FLOOR}/{FALSE_POSITIVE_CEILING}을 통과할 수 없다"
            )

    def test_small_sample_is_reported_unreachable(self) -> None:
        """작은_표본은_도달불가로_판정된다 — 이 검사 자체의 변별력 확인"""
        # n=20에서 Wilson 상한(0/20)=0.1192 > 0.10 이므로 도달 불가여야 한다. 이 단언이
        # 없으면 `_gate_is_reachable`이 항상 True를 돌려줘도 위 테스트가 통과한다.
        assert not _gate_is_reachable(27, 20)
        assert _gate_is_reachable(27, 30)


class TestFixtureIntegrity:
    def test_no_channel_has_empty_fixtures(self) -> None:
        """픽스처_공백_없음 — 0건 스캔은 실패"""
        assert build_report().empty_fixture_channels == ()
        for fx in build_fixtures():
            assert fx.positives and fx.negatives, fx.kebab_id

    def test_fixture_targets_actually_have_channels(self) -> None:
        """픽스처_대상이_실제로_채널을_가진다"""
        for fx in build_fixtures():
            assert CATALOG_BY_ID[fx.kebab_id].regex_signals, fx.kebab_id

    def test_fixtures_are_deterministic(self) -> None:
        """픽스처_결정론 — 같은 입력에 같은 출력(난수·시각 의존 0)"""
        assert build_fixtures() == build_fixtures()


class TestHonestCoverageAccounting:
    """'채널 3종 부여'가 '앵커 커버 5종 해결'로 읽히지 않게 한다."""

    def test_unchannelable_entries_are_reported_with_reasons(self) -> None:
        """채널_불가_2종이_사유와_함께_보고된다"""
        coverage = build_report().to_json()["coverage"]
        assert isinstance(coverage, dict)
        listed = {u["kebab_id"] for u in coverage["unchannelable"]}
        assert listed == {"opposite-root-selected", "extremum-max-min-confused"}
        for u in coverage["unchannelable"]:
            assert u["reason"].strip(), u["kebab_id"]

    def test_unchannelable_entries_really_have_no_channel(self) -> None:
        """채널_불가로_적은_항목은_실제로_채널이_없다 — 선언과 사실의 대조"""
        for u in UNCHANNELABLE:
            assert not CATALOG_BY_ID[u.kebab_id].regex_signals, u.kebab_id
            assert CATALOG_BY_ID[u.kebab_id].canonical_wrong_form is None, u.kebab_id

    def test_coverage_total_is_channelled_plus_unchannelable(self) -> None:
        """커버_합계가_채널+불가와_일치"""
        coverage = build_report().to_json()["coverage"]
        assert isinstance(coverage, dict)
        assert coverage["anchor_covered_total"] == len(coverage["channelled"]) + len(
            coverage["unchannelable"]
        )


class TestThresholdsAreNamed:
    def test_thresholds_appear_in_report(self) -> None:
        """임계값이_리포트에_실린다 — 판정 기준이 숨지 않게"""
        thresholds = build_report().to_json()["thresholds"]
        assert thresholds == {
            "detection_floor": DETECTION_FLOOR,
            "false_positive_ceiling": FALSE_POSITIVE_CEILING,
        }


class TestJsonMirrorsObject:
    def test_json_passed_matches_object(self) -> None:
        """JSON과_객체의_판정이_일치 — 두 출력 경로가 갈라지지 않게"""
        report = build_report()
        assert report.to_json()["passed"] is report.passed

    def test_json_channel_count_matches(self) -> None:
        """JSON_채널수가_객체와_일치"""
        report = build_report()
        channels = report.to_json()["channels"]
        assert isinstance(channels, list)
        assert len(channels) == len(report.channels)


class TestZeroRootExclusionIsNotLiteralOnly:
    """PR #1032 Codex P1 회귀 동결 — 0을 근으로 적는 방법은 `x=0` 하나가 아니다.

    최초 판의 배제 조건은 리터럴 `x=0`뿐이라, **완전히 올바른 설명**인
    "…x=2만 나와서 안 되고 해는 0과 2다"가 그 리터럴을 포함하지 않아 매치됐다. 그 문장은
    substring 두 신호도 함께 발화하므로 confidence 1.0 — 정답에 확신 오진단이 나가는 자리였다.
    """

    _CORRECT_EXPLANATIONS = (
        "x²=2x에서 양변을 x로 나누면 x=2만 나와서 안 되고 해는 0과 2다",
        "x²=3x 의 해는 0과 3이다",
        "x²=7x, 양변을 x로 나누면 x=7 만 남아 x=0 을 잃는다",
        "x²=10x 의 두 근은 0이나 10 이다",
        "x²=5x 양변을 x로 나누면 x=5 이지만 근이 0인 경우를 빠뜨리면 안 된다",
    )

    def test_correct_explanations_do_not_fire_the_channel(self) -> None:
        """제로근을_다른_표기로_적은_정답은_채널을_발화시키지_않는다"""
        for text in self._CORRECT_EXPLANATIONS:
            assert not _channel_fired("root-loss-by-dividing", text), text

    def test_intended_omission_still_fires(self) -> None:
        """진짜_근_손실은_여전히_검출된다 — 배제를 넓히다 채널을 죽이지 않았는지"""
        assert _channel_fired("root-loss-by-dividing", "x²=2x 양변을 x로 나누면 x=2")


class TestServingReachIsMeasured:
    """정규식이 *발화했다*와 학생 경로에 *도달했다*는 다른 사실이다(Codex P2)."""

    def test_serving_reach_is_reported_per_channel(self) -> None:
        """채널별_서빙_도달이_보고된다"""
        for ch in build_report().channels:
            assert 0 <= ch.serving_reach <= ch.positives

    def test_factor_sign_flip_now_reaches_serving(self) -> None:
        """factor_sign_flip은_서빙_게이트를_넘는다 — MISC-22 해소를 동결한다(스스로 만료 알림).

        기호 substring 신호(`(x-a)`·`x=-a`)는 수치 입력에 매치되지 않지만, MISC-22(v1.5)가
        confidence 공식을 정정해 정규식 매치 1건을 신호 전체와 동등한 완결 증거로 가산한다 —
        conf=1.0 → floor 0.65 통과. 이전(v1.2 원식)에는 0.5에 갇혀 **한 번도 학생에게 도달하지
        못했다**(작동 신호 없는 알고리즘 부착). 이 테스트는 그 해소를 동결한다 — 회귀(다시 0.5로
        떨어짐)가 생기면 이 테스트가 실패해 알린다.
        """
        assert _survives_serving_gate("factor-sign-flip", "(x-2)=0 이므로 x=-2")
        reach = {c.kebab_id: c.serving_reach for c in build_report().channels}
        assert reach["factor-sign-flip"] == 27

    def test_root_loss_by_dividing_reaches_serving(self) -> None:
        """root_loss_by_dividing은_서빙에_도달한다 — 위 0이 측정 결함이 아님을 대조로 보인다"""
        reach = {c.kebab_id: c.serving_reach for c in build_report().channels}
        assert reach["root-loss-by-dividing"] > 0

    def test_extremum_no_longer_reaches_serving_via_regex_alone(self) -> None:
        """extremum은_MISC-24_이후_regex단독으로는_서빙에_도달하지_않는다 — 회귀가 아니라 의도.

        `_extremum_value_vs_point()`의 `positives` 픽스처는 전부 "좌표 숫자 == 값 숫자"
        형태(예: `극대는 x=-1 … 극댓값은 -1`)라 `ambiguous` 픽스처와 **텍스트 구조가 동일**하다
        — f(x₀)=x₀ 우연의 일치와 원리상 구별 불가능한 자리다. MISC-24 이전에는 이 구조 때문에
        `positives`도 `ambiguous`도 똑같이 conf 1.0으로 서빙에 도달했다(확신 오진단 위험).
        `ambiguous_regex_signals`(MISC-24)가 이 정규식 채널의 confidence 가산을 0으로 만들어
        이제 `positives`·`ambiguous` 둘 다 conf 0.5(게이트 미만)에 멈춘다 — serving_reach=0은
        측정 결함이 아니라 "이 텍스트 형태로는 확신할 수 없다"는 설계 의도의 정확한 반영이다.
        학생이 명시적으로 "x좌표"라는 말을 써 값을 좌표로 답한 경우는 정규식과 무관한 substring
        AND 경로로 여전히 conf 1.0에 도달한다(아래 `TestExtremumSubstringPathUnaffected`).
        """
        reach = {c.kebab_id: c.serving_reach for c in build_report().channels}
        assert reach["extremum-value-vs-point-confused"] == 0
        # 정규식은 여전히 *발화*한다(검출은 유지) — 다만 confidence 가산이 0이라 게이트를 못 넘을 뿐.
        assert _channel_fired(
            "extremum-value-vs-point-confused", "극대는 x=-1 에서 나오고 극댓값은 -1"
        )
        assert not _survives_serving_gate(
            "extremum-value-vs-point-confused", "극대는 x=-1 에서 나오고 극댓값은 -1"
        )


class TestExtremumSubstringPathUnaffected:
    """MISC-24 정정이 substring AND 경로("극댓값"+"x좌표" 명시)는 건드리지 않는다."""

    def test_explicit_x_coordinate_confusion_still_reaches_serving(self) -> None:
        """학생이_x좌표라는_말을_명시하면_여전히_서빙에_도달한다 — 정규식과 무관한 경로"""
        text = "극댓값을 극점의 x좌표라고 답함"
        assert _survives_serving_gate("extremum-value-vs-point-confused", text)


class TestAmbiguousServingReachIsGated:
    """MISC-24 acceptance ③ — ambiguous 계급이 이제 서빙 게이트 통과 여부까지 재고, 0을 강제한다.

    f(x₀)=x₀ 우연의 일치 정답이 확신 오진단으로 학생에게 나가는 것이 이 태스크의 실제 해악
    지점이다. `ambiguous_fired`(정규식 발화)는 여전히 보고만 하지만, `ambiguous_serving_reach`
    (서빙 품질 게이트까지 살아남은 수)는 `ChannelResult.passed`가 0으로 강제한다.
    """

    def test_ambiguous_fixtures_do_not_survive_serving_gate(self) -> None:
        """모호_픽스처는_서빙_게이트를_통과하지_못한다 — MISC-24 실제 해악 지점의 직접 단언"""
        for fx in build_fixtures():
            for text in fx.ambiguous:
                assert not _survives_serving_gate(fx.kebab_id, text), text

    def test_report_ambiguous_serving_reach_is_zero(self) -> None:
        """리포트의_ambiguous_serving_reach가_0이다 — 회귀 시 이 단언이 먼저 깨진다"""
        for ch in build_report().channels:
            assert ch.ambiguous_serving_reach == 0, ch.kebab_id

    def test_ambiguous_serving_reach_gates_passed(self) -> None:
        """ambiguous_serving_reach가_0이_아니면_passed가_False가_된다 — 게이트 자신의 변별력 확인

        뮤테이션 대신 `ChannelResult`를 직접 조립해 0이 아닌 값을 주입한다 — 이 검사가
        실제로 `passed`를 끄는지 확인해야 "게이트가 있다"가 위장이 되지 않는다.
        """
        from whymath_backend.harness.anchor_detection_channel_eval import ChannelResult

        healthy = ChannelResult(
            kebab_id="probe",
            anchor_id="A0",
            detected=27,
            positives=27,
            false_positives=0,
            negatives=30,
            ambiguous_fired=2,
            ambiguous_total=2,
            ambiguous_serving_reach=0,
        )
        assert healthy.passed is True
        contaminated = ChannelResult(
            kebab_id="probe",
            anchor_id="A0",
            detected=27,
            positives=27,
            false_positives=0,
            negatives=30,
            ambiguous_fired=2,
            ambiguous_total=2,
            ambiguous_serving_reach=1,
        )
        assert contaminated.passed is False

    def test_ambiguous_serving_reach_reported_in_json(self) -> None:
        """JSON_출력에도_ambiguous_serving_reach가_실린다"""
        for ch in build_report().to_json()["channels"]:
            assert "ambiguous_serving_reach" in ch


class TestReachabilityChecksBothBounds:
    """한쪽만 검사하는 도달 가능성 검사는 그 자체가 위장이다(Codex P2)."""

    def test_small_positive_sample_is_unreachable(self) -> None:
        """양성_표본이_작으면_도달불가로_판정된다"""
        # 전건 검출이어도 Wilson 하한이 0.80에 못 닿는 구간.
        assert not _gate_is_reachable(5, 40)
        assert _gate_is_reachable(27, 40)

    def test_small_negative_sample_is_unreachable(self) -> None:
        """음성_표본이_작으면_도달불가로_판정된다"""
        assert not _gate_is_reachable(27, 20)
        assert _gate_is_reachable(27, 30)
