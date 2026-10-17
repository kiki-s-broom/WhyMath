"""S4-53 — statistical_claim verifier 단위 테스트.

검증 축:
  ① 1차원 데이터의 mean/median/variance/std/q1/q3 계산.
  ② 2차원 데이터의 corr 계산.
  ③ pass/fail/unverifiable 판정.
  ④ DSL 파싱 실패는 unverifiable.

S4-58 추가 축 (파일 하단 `S4-58` 구역):
  ⑤ 정확값 산술 — float 경유 0건(정수 정밀도·대값·소수 오차 입력으로 고정).
  ⑥ 허용오차 정책 — exact·abs·rel·round와 기본 정책, 경계(포함)·half-up 동점·무리수.
  ⑦ 입력 방어 — NaN·지수 폭탄·거대 토큰·혼합수·깊은 중첩·미지 절은 fail 위장 없이 unverifiable.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from whymath_backend.l3.statistical_claim import (
    TolerancePolicy,
    describe_statistical_model_ko,
    parse_statistical_model,
    verify_statistical_claim,
)


def test_mean_pass() -> None:
    verdict, residual, result = verify_statistical_claim("data=[1,2,3,4,5]; stat=mean", "3")
    assert verdict.state == "pass"
    assert result.value == pytest.approx(3.0)
    assert "평균" in result.description


def test_mean_fail() -> None:
    verdict, residual, result = verify_statistical_claim("data=[1,2,3,4,5]; stat=mean", "4")
    assert verdict.state == "fail"


def test_median_odd() -> None:
    verdict, residual, result = verify_statistical_claim("data=[1,2,3,4,5]; stat=median", "3")
    assert verdict.state == "pass"


def test_median_even() -> None:
    verdict, residual, result = verify_statistical_claim("data=[1,2,3,4]; stat=median", "2.5")
    assert verdict.state == "pass"


def test_variance() -> None:
    verdict, residual, result = verify_statistical_claim("data=[1,2,3,4,5]; stat=variance", "2.5")
    assert verdict.state == "pass"
    assert result.value == pytest.approx(2.5)


def test_std() -> None:
    verdict, residual, result = verify_statistical_claim("data=[1,2,3,4,5]; stat=std", "1.5811")
    assert result.value == pytest.approx(1.5811388300841898, rel=1e-4)


def test_q1_q3() -> None:
    verdict, residual, result = verify_statistical_claim("data=[1,2,3,4,5,6,7,8]; stat=q1", "2.75")
    assert verdict.state == "pass"
    verdict, residual, result = verify_statistical_claim("data=[1,2,3,4,5,6,7,8]; stat=q3", "6.25")
    assert verdict.state == "pass"


def test_corr() -> None:
    verdict, residual, result = verify_statistical_claim(
        "data=[[1,1],[2,2],[3,3],[4,4],[5,5]]; stat=corr; columns=[0,1]",
        "1",
    )
    assert verdict.state == "pass"
    assert result.value == pytest.approx(1.0)


def test_corr_2d_without_columns_is_unverifiable() -> None:
    verdict, residual, result = verify_statistical_claim(
        "data=[[1,1],[2,2],[3,3]]; stat=mean",
        "2",
    )
    # 열 지정이 없으면 첫 번째 열을 사용한다.
    assert verdict.state == "pass"
    assert result.value == pytest.approx(2.0)


def test_answer_with_label() -> None:
    verdict, residual, result = verify_statistical_claim("data=[1,2,3,4,5]; stat=mean", "mean=3")
    assert verdict.state == "pass"


def test_fraction_answer() -> None:
    verdict, residual, result = verify_statistical_claim("data=[0,1]; stat=mean", "1/2")
    assert verdict.state == "pass"


def test_unverifiable_missing_stat() -> None:
    verdict, residual, result = verify_statistical_claim("data=[1,2,3]", "2")
    assert verdict.state == "unverifiable"


def test_unverifiable_bad_data() -> None:
    verdict, residual, result = verify_statistical_claim("data=notjson; stat=mean", "2")
    assert verdict.state == "unverifiable"


def test_unverifiable_non_numeric_answer() -> None:
    verdict, residual, result = verify_statistical_claim("data=[1,2,3]; stat=mean", "abc")
    assert verdict.state == "unverifiable"


def test_residual_axes_present() -> None:
    verdict, residual, result = verify_statistical_claim("data=[1,2,3]; stat=mean", "2")
    assert "자료↔발문 정합" in residual
    assert "표본 추출 방법" in residual
    assert "자료 해석의 모호성" in residual


def test_parse_model_round_trip() -> None:
    model = parse_statistical_model("data=[1,2,3]; stat=mean")
    assert model.values == (1.0, 2.0, 3.0)
    assert model.stat == "mean"


# ══════════════════════════════════════════════════════════════════════════
# S4-58 — 정확값 산술 · 허용오차 정책 DSL · 입력 방어
# ══════════════════════════════════════════════════════════════════════════
def _state(conditions: str, answer: str) -> str:
    verdict, _, _ = verify_statistical_claim(conditions, answer)
    return verdict.state


# ── ⑤ 정확값 산술 ─────────────────────────────────────────────────────────
def test_exact_integer_mean_is_not_lost_to_float_rounding() -> None:
    """10^17+1은 float로 표현되지 않는다 — 수정 전에는 어긋난 주장이 pass였다."""
    big = 10**17
    cond = f"data=[{big + 1},{big + 1},{big + 1}]; stat=mean"
    assert _state(cond, str(big + 1)) == "pass"
    assert _state(cond, str(big)) == "fail"


def test_large_mean_is_not_distorted_by_relative_tolerance() -> None:
    """평균 1조에서 rel_tol=1e-9는 폭 1000을 허용했다 — 이제 1 차이도 fail."""
    cond = "data=[1000000000000,1000000000000]; stat=mean"
    assert _state(cond, "1000000000000") == "pass"
    assert _state(cond, "1000000000001") == "fail"
    assert _state(cond, "1000000000500") == "fail"


def test_decimal_data_is_exact_and_float_artifact_is_not_an_answer() -> None:
    """0.1+0.2+0.3의 float 합은 0.6000000000000001 — 정확 평균은 0.2다."""
    cond = "data=[0.1,0.2,0.3]; stat=mean"
    assert _state(cond, "0.2") == "pass"
    assert _state(cond, "0.20000000000000004") == "fail"
    assert _state(cond, "0.2000000001") == "fail"


def test_result_exposes_exact_value_and_float_compat_value() -> None:
    _, _, result = verify_statistical_claim("data=[1,2,4]; stat=mean", "7/3")
    assert result.exact_value == Fraction(7, 3)
    assert result.value == pytest.approx(7 / 3)


@pytest.mark.parametrize(
    ("conditions", "answer"),
    [
        ("data=[1,2,3,4]; stat=variance", "5/3"),
        ("data=[1,2,3,4]; stat=variance; variance_kind=population", "1.25"),
        ("data=[1,2,3,4]; stat=std; variance_kind=population", "1.118033988749895"),
        ("data=[1,2,3,4]; stat=q1", "1.75"),
        ("data=[1,2,3,4]; stat=q3", "3.25"),
        ("data=[7,1,3]; stat=median", "3"),
        ("data=[[1,9],[2,8],[3,7]]; stat=median; columns=[1]", "8"),
    ],
)
def test_exact_statistics_table(conditions: str, answer: str) -> None:
    assert _state(conditions, answer) == "pass"


def test_single_point_quartile_and_population_variance() -> None:
    assert _state("data=[5]; stat=q1", "5") == "pass"
    assert _state("data=[5]; stat=variance; variance_kind=population", "0") == "pass"


def test_claim_forms_accepted() -> None:
    cond = "data=[0.75]; stat=mean"
    for answer in ("0.75", "3/4", "1.5/2", "mean = 0.75", "+0.75", "75e-2", "0.750"):
        assert _state(cond, answer) == "pass", answer
    assert _state("data=[0.5]; stat=mean", ".5") == "pass"
    assert _state("data=[3]; stat=mean", "3.") == "pass"


# ── ⑥ 허용오차 정책 ───────────────────────────────────────────────────────
MEAN_7_3 = "data=[1,2,4]; stat=mean"  # 정확 평균 7/3 (무한소수)


def test_default_policy_for_non_terminating_value_is_absolute_1e9() -> None:
    assert _state(MEAN_7_3, "7/3") == "pass"
    assert _state(MEAN_7_3, "2.3333333333") == "pass"  # 오차 3.3e-11
    assert _state(MEAN_7_3, "2.3333334") == "fail"  # 오차 6.7e-8
    assert _state(MEAN_7_3, "2.333") == "fail"


def test_default_policy_for_terminating_value_is_exact() -> None:
    assert _state("data=[1,2,3,4]; stat=mean", "2.5") == "pass"
    assert _state("data=[1,2,3,4]; stat=mean", "2.5000000001") == "fail"


def test_explicit_exact_on_non_terminating_value() -> None:
    cond = MEAN_7_3 + "; tolerance=exact"
    assert _state(cond, "7/3") == "pass"
    assert _state(cond, "2.3333333333") == "fail"  # 기본 정책이면 pass였을 값


def test_abs_policy_and_inclusive_boundary() -> None:
    cond = MEAN_7_3 + "; tolerance=abs:0.01"
    assert _state(cond, "2.33") == "pass"
    assert _state(cond, "2.32") == "fail"
    edge = "data=[1]; stat=mean; tolerance=abs:0.5"
    assert _state(edge, "1.5") == "pass"  # 경계 포함
    assert _state(edge, "0.5") == "pass"
    assert _state(edge, "1.5000001") == "fail"
    assert _state(edge, "0.4999999") == "fail"


def test_rel_policy_scales_with_value_and_zero_is_exact() -> None:
    cond = "data=[1000]; stat=mean; tolerance=rel:0.001"
    assert _state(cond, "1001") == "pass"  # 경계 포함
    assert _state(cond, "999") == "pass"
    assert _state(cond, "1001.01") == "fail"
    zero = "data=[0]; stat=mean; tolerance=rel:0.5"
    assert _state(zero, "0") == "pass"
    assert _state(zero, "0.1") == "fail"  # 0의 상대 허용폭은 0


def test_round_policy_matches_rounded_value_only() -> None:
    cond = MEAN_7_3 + "; tolerance=round:2"
    assert _state(cond, "2.33") == "pass"
    assert _state(cond, "2.330") == "pass"
    assert _state(cond, "2.3") == "fail"  # 자릿수를 덜 쓴 답
    assert _state(cond, "2.34") == "fail"
    assert _state(cond, "7/3") == "fail"  # 반올림 정책에서 정확 분수는 반올림값이 아니다
    assert _state(MEAN_7_3 + "; tolerance=round:0", "2") == "pass"
    assert _state(MEAN_7_3 + "; tolerance=round:4", "2.3333") == "pass"


@pytest.mark.parametrize(
    ("data", "places", "answer", "expected"),
    [
        ("0.125", 2, "0.13", "pass"),  # 동점은 0에서 먼 쪽(half-up) — 은행가 반올림이면 0.12
        ("0.125", 2, "0.12", "fail"),
        ("-0.125", 2, "-0.13", "pass"),  # 음수 동점도 0에서 먼 쪽
        ("-0.125", 2, "-0.12", "fail"),
        ("2.5", 0, "3", "pass"),
        ("2.5", 0, "2", "fail"),
        ("-2.5", 0, "-3", "pass"),
        ("2.345", 2, "2.35", "pass"),  # float 2.345는 2.34499… — 정확 유리수라야 동점으로 본다
    ],
)
def test_round_half_up_ties(data: str, places: int, answer: str, expected: str) -> None:
    cond = f"data=[{data}]; stat=mean; tolerance=round:{places}"
    assert _state(cond, answer) == expected


def test_policy_names_are_case_insensitive() -> None:
    assert _state(MEAN_7_3 + "; tolerance=ABS:0.01", "2.33") == "pass"
    assert _state(MEAN_7_3 + "; tolerance=Round:2", "2.33") == "pass"


STD_SAMPLE = "data=[1,2,3,4,5]; stat=std"  # sqrt(5/2) = 1.58113883008418966…


def test_irrational_std_default_policy() -> None:
    assert _state(STD_SAMPLE, "1.5811388300841898") == "pass"
    assert _state(STD_SAMPLE, "1.58113883") == "pass"  # 오차 8.4e-11
    assert _state(STD_SAMPLE, "1.58113884") == "fail"  # 오차 9.9e-9
    assert _state(STD_SAMPLE, "1.5811") == "fail"


def test_irrational_with_exact_policy_is_unverifiable_not_fail() -> None:
    verdict, _, result = verify_statistical_claim(STD_SAMPLE + "; tolerance=exact", "1.5811")
    assert verdict.state == "unverifiable"
    assert "무리수" in (verdict.reason or "")
    assert result.exact_value is None
    assert "무리수" in result.description  # 설명 표기도 근사임을 밝힌다


def test_irrational_with_round_and_rel_policies() -> None:
    assert _state(STD_SAMPLE + "; tolerance=round:2", "1.58") == "pass"
    assert _state(STD_SAMPLE + "; tolerance=round:2", "1.59") == "fail"
    assert _state(STD_SAMPLE + "; tolerance=round:6", "1.581139") == "pass"
    root2 = "data=[1,3]; stat=std"  # 표본표준편차 = sqrt(2)
    assert _state(root2 + "; tolerance=rel:0.000001", "1.414214") == "pass"
    assert _state(root2 + "; tolerance=rel:0.000001", "1.41421") == "fail"


def test_std_with_perfect_square_variance_is_exact() -> None:
    cond = "data=[1,3]; stat=std; variance_kind=population; tolerance=exact"
    verdict, _, result = verify_statistical_claim(cond, "1")
    assert verdict.state == "pass"
    assert result.exact_value == Fraction(1)


@pytest.mark.parametrize(
    ("table", "answer", "expected"),
    [
        ("[[1,1],[2,2],[3,3]]", "1", "pass"),
        ("[[1,5],[2,4],[3,3]]", "-1", "pass"),
        ("[[1,5],[2,4],[3,3]]", "1", "fail"),
        ("[[1,2],[2,1],[3,4],[4,3]]", "0.6", "pass"),  # r = 3/5 정확
        ("[[1,2],[2,1],[3,4],[4,3]]", "3/5", "pass"),
        ("[[1,2],[2,1],[3,4],[4,3]]", "0.60000001", "fail"),
        ("[[1,1],[2,2],[3,2]]", "0.8660254037844386", "pass"),  # r = sqrt(3)/2 무리수
        ("[[1,1],[2,2],[3,2]]", "0.866", "fail"),
        ("[[1,2],[2,2],[3,1]]", "-0.8660254037844386", "pass"),
        ("[[1,2],[2,2],[3,1]]", "0.8660254037844386", "fail"),  # 부호가 다르면 fail
    ],
)
def test_correlation_exact_and_irrational(table: str, answer: str, expected: str) -> None:
    assert _state(f"data={table}; stat=corr; columns=[0,1]", answer) == expected


def test_correlation_irrational_exact_policy_and_constant_column() -> None:
    irrational = "data=[[1,1],[2,2],[3,2]]; stat=corr; columns=[0,1]"
    assert _state(irrational + "; tolerance=exact", "0.866") == "unverifiable"
    assert _state(irrational + "; tolerance=round:3", "0.866") == "pass"
    constant = "data=[[1,1],[2,1],[3,1]]; stat=corr; columns=[0,1]"
    assert _state(constant, "0") == "unverifiable"


def test_result_policy_label_reports_which_policy_ran() -> None:
    labels = {
        "data=[1,2,3,4]; stat=mean": "기본→exact",
        MEAN_7_3: "기본→abs:0.000000001",
        MEAN_7_3 + "; tolerance=round:2": "round:2",
        MEAN_7_3 + "; tolerance=abs:0.01": "abs:0.01",
        MEAN_7_3 + "; tolerance=rel:0.001": "rel:0.001",
        MEAN_7_3 + "; tolerance=exact": "exact",
    }
    for conditions, label in labels.items():
        _, _, result = verify_statistical_claim(conditions, "2")
        assert result.policy == label, conditions


def test_fail_reason_names_values_and_policy_without_float_noise() -> None:
    verdict, _, _ = verify_statistical_claim("data=[1,2,3,4]; stat=mean", "2.6")
    assert verdict.reason is not None
    assert "2.5" in verdict.reason
    assert "2.6" in verdict.reason
    assert "기본→exact" in verdict.reason
    rounded, _, _ = verify_statistical_claim(MEAN_7_3 + "; tolerance=round:2", "2.3")
    assert rounded.reason is not None
    assert "반올림 2.33" in rounded.reason


def test_parse_tolerance_into_policy() -> None:
    assert parse_statistical_model("data=[1]; stat=mean").tolerance is None
    model = parse_statistical_model("data=[1]; stat=mean; tolerance=round:2")
    assert model.tolerance == TolerancePolicy("round", places=2)
    model = parse_statistical_model("data=[1]; stat=mean; tolerance=abs:0.01")
    assert model.tolerance == TolerancePolicy("abs", bound=Fraction(1, 100))
    assert parse_statistical_model("data=[1]; stat=mean; tolerance=exact").tolerance == (
        TolerancePolicy("exact")
    )


def test_describe_model_uses_exact_notation() -> None:
    cond = MEAN_7_3
    model = parse_statistical_model(cond)
    _, _, result = verify_statistical_claim(cond, "7/3")
    text = describe_statistical_model_ko(model, result)
    assert "Fraction" not in text
    assert "[1, 2, 4]" in text
    assert "7/3" in text


# ── ⑦ 입력 방어 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "conditions",
    [
        "data=[NaN,1]; stat=mean",
        "data=[Infinity]; stat=mean",
        "data=[-Infinity,1]; stat=mean",
        "data=[true,1]; stat=mean",
        'data=["1",2]; stat=mean',
        "data=[null]; stat=mean",
        "data=[1e31]; stat=mean",  # 지수 상한(30) 초과
        "data=[1e999999999]; stat=mean",  # 지수 폭탄
        "data=[" + "1" * 65 + "]; stat=mean",  # 토큰 길이 상한(64) 초과
        "data=[1,2,3]; stat=mean; tolerence=exact",  # 철자 틀린 정책 절 — 조용히 무시 금지
        "data=[1,2,3]; stat=mean; stat=median",  # 중복 절
        "data=[1,2,3]; stat=mean; tolerance=exact; tolerance=round:2",
        "data=" + "[" * 100_000 + "]" * 100_000 + "; stat=mean",  # 깊은 중첩 — RecursionError
    ],
)
def test_malformed_data_is_unverifiable_not_fail_or_crash(conditions: str) -> None:
    assert _state(conditions, "1") == "unverifiable"


@pytest.mark.parametrize(
    "tolerance",
    [
        "fuzzy",
        "abs",
        "abs:",
        "abs:0",
        "abs:-1",
        "abs:abc",
        "abs:1e999",
        "rel:0",
        "rel:1",
        "rel:1.5",
        "round",
        "round:",
        "round:-1",
        "round:16",
        "round:2.5",
        "round:abc",
        "exact:1",
    ],
)
def test_malformed_tolerance_is_unverifiable(tolerance: str) -> None:
    assert _state(f"data=[1,2,3]; stat=mean; tolerance={tolerance}", "2") == "unverifiable"


@pytest.mark.parametrize(
    "answer",
    [
        "1e999999",  # 지수 폭탄 — 수정 전에는 inf로 읽혀 fail로 위장됐다
        "1e31",
        "inf",
        "-inf",
        "nan",
        "1_000",  # float()는 받아주는 밑줄 숫자
        "١٢٣",  # 아랍-인도 숫자 — float()는 받아주는 비 ASCII 숫자
        "1 1/2",  # 혼합수 — 공백 제거로 11/2(5.5)가 되던 오독
        "1 000",
        "1/0",
        "1/2/3",
        "0x10",
        "1,5",
        "--1",
        "1e",
        "e5",
        ".",
        "",
        "   ",
        "mean=",
        "1" * 65,
    ],
)
def test_malformed_claim_is_unverifiable(answer: str) -> None:
    assert _state("data=[1,2,3]; stat=mean", answer) == "unverifiable"


def test_max_data_points_boundary() -> None:
    at_limit = "data=[" + ",".join(["1"] * 10_000) + "]; stat=mean"
    over_limit = "data=[" + ",".join(["1"] * 10_001) + "]; stat=mean"
    assert _state(at_limit, "1") == "pass"
    assert _state(over_limit, "1") == "unverifiable"


def test_many_decimal_points_variance_stays_exact_and_finite() -> None:
    """한도(10,000)의 소수 데이터도 분산이 정확 유리수로 끝난다 — 폭주 없음."""
    values = [f"{i}.{i % 97:02d}" for i in range(10_000)]
    cond = "data=[" + ",".join(values) + "]; stat=variance"
    verdict, _, result = verify_statistical_claim(cond, "0")
    assert verdict.state == "fail"  # 분산은 0이 아니다 — 계산이 끝나 판정까지 도달했다는 뜻
    assert result.exact_value is not None
    assert result.exact_value > 0


def test_default_policy_for_large_non_terminating_value_stays_absolute() -> None:
    """평균 ≈ 1조 + 1/3 — 상대 허용오차였다면 폭 1000이 열려 어긋난 주장도 통과했다."""
    cond = "data=[1000000000000,1000000000000,1000000000001]; stat=mean"
    assert _state(cond, "1000000000000.3333333333") == "pass"  # 오차 3.3e-11
    assert _state(cond, "3000000000001/3") == "pass"
    assert _state(cond, "1000000000000.33") == "fail"  # 오차 3.3e-3
    assert _state(cond, "1000000000500") == "fail"


def test_round_places_upper_bound_is_inclusive() -> None:
    assert _state("data=[1]; stat=mean; tolerance=round:15", "1") == "pass"
    assert _state("data=[1]; stat=mean; tolerance=round:0", "1") == "pass"


def test_fail_reason_formats_numbers_exactly() -> None:
    """사유의 수 표기는 정확한 십진/분수 — 음수·선행 0·무한소수를 깨뜨리지 않는다."""
    negative, _, _ = verify_statistical_claim("data=[-0.125]; stat=mean", "0.5")
    assert negative.reason is not None
    assert "-0.125" in negative.reason
    small, _, _ = verify_statistical_claim("data=[0.05]; stat=mean", "1")
    assert small.reason is not None
    assert "0.05" in small.reason
    third, _, _ = verify_statistical_claim("data=[1,1,2]; stat=mean", "9")
    assert third.reason is not None
    assert "4/3" in third.reason


# ── S4-71 잔여 결함 ──────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "conditions",
    [
        "data=[5]; stat=variance",  # variance_kind 생략 = 기본 sample
        "data=[5]; stat=std",
        "data=[5]; stat=variance; variance_kind=sample",
        "data=[5]; stat=std; variance_kind=sample",
        "data=[[5]]; stat=variance",  # 2차원 1행 — 열 미지정이면 첫 열(n=1)
    ],
)
def test_single_point_sample_variance_is_unverifiable_not_zero(conditions: str) -> None:
    """n=1 표본분산·표본표준편차는 분모 n-1=0 이라 정의되지 않는다 — S4-53 은 0 으로 pass 시켰다."""
    verdict, _, result = verify_statistical_claim(conditions, "0")
    assert verdict.state == "unverifiable"
    assert verdict.reason is not None
    assert "n=1" in verdict.reason
    assert "정의되지 않음" in verdict.reason
    assert result.value is None
    # 틀린 주장값도 fail 이 아니라 unverifiable — 정의 불가 값을 정답/오답으로 가르지 않는다.
    assert _state(conditions, "7") == "unverifiable"


@pytest.mark.parametrize("stat", ["variance", "std"])
def test_single_point_population_variance_stays_zero(stat: str) -> None:
    """모집단 분산·표준편차는 n=1 에서 0 으로 정의된다 — 위 변경이 이쪽을 건드리면 안 된다."""
    cond = f"data=[5]; stat={stat}; variance_kind=population"
    assert _state(cond, "0") == "pass"
    assert _state(cond, "1") == "fail"


def test_two_point_sample_variance_is_still_defined() -> None:
    """n>=2 경계 — 가드가 n=2 까지 막으면 안 된다(n<2 → n<=2 뮤테이션 방어)."""
    assert _state("data=[1,3]; stat=variance", "2") == "pass"
    assert _state("data=[1,3]; stat=std", "1.4142135623730951") == "pass"


TABLE_2X2 = "data=[[1,2],[3,4]]; stat=mean"  # 열 0 평균 2, 열 1 평균 3


@pytest.mark.parametrize(
    "columns",
    [
        "[abc]",  # JSON 아님
        "[1.5]",  # 소수 — 1 로 조용히 잘리던 입력
        "[1.0]",  # 정수값이어도 JSON 소수 표기는 거절
        "[true]",  # bool — int 의 하위 클래스라 1 로 읽히던 입력
        "[false]",
        '["1"]',  # 문자열 — int("1") 로 변환되던 입력
        "[null]",  # TypeError 로 새던 입력
        "[NaN]",  # ValueError 로 새던 입력
        "[Infinity]",
        "[[1]]",  # 중첩
        '{"0": 1}',  # 배열이 아님
        "1",
    ],
)
def test_columns_non_integer_is_unverifiable_without_exception(columns: str) -> None:
    verdict, _, _ = verify_statistical_claim(f"{TABLE_2X2}; columns={columns}", "2")
    assert verdict.state == "unverifiable"
    assert verdict.reason is not None
    assert "columns" in verdict.reason


def test_columns_truncation_cannot_flip_the_judged_column() -> None:
    """[1.5] 가 열 1 로 잘리면 열 1 의 평균 3 으로 판정된다 — 이제는 어떤 주장값도 판정되지 않는다."""
    for answer in ("2", "3"):
        assert _state(f"{TABLE_2X2}; columns=[1.5]", answer) == "unverifiable"


def test_columns_integer_still_selects_the_column() -> None:
    assert _state(f"{TABLE_2X2}; columns=[0]", "2") == "pass"
    assert _state(f"{TABLE_2X2}; columns=[1]", "3") == "pass"
    assert _state(f"{TABLE_2X2}; columns=[1]", "2") == "fail"
    assert _state("data=[[1,1],[2,2],[3,3]]; stat=corr; columns=[0,1]", "1") == "pass"


def test_columns_parse_exceptions_do_not_leak() -> None:
    """깊은 중첩(RecursionError)·4300자리 초과 정수(ValueError)도 예외 전파 없이 unverifiable."""
    deep = "[" * 100_000
    huge = "[" + "9" * 5_000 + "]"
    for columns in (deep, huge):
        verdict, _, _ = verify_statistical_claim(f"{TABLE_2X2}; columns={columns}", "2")
        assert verdict.state == "unverifiable"
        assert verdict.reason is not None
        assert "columns" in verdict.reason
