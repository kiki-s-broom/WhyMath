"""통계 자료형 검증기 — SymPy 불가 영역 v2 단계 A 실증 도메인(S4-53 · 정확값 정책 S4-58).

주어진 유한 데이터 표에 대한 평균·중앙값·분산·사분위수·상관계수 등을 전수 결정론으로 검증.
데이터가 주어지면 값은 확정되므로 기계 검증 가능 축이며, 잔여는 발문↔자료 정합·자료 해석
모호성·표본 추출 방법 등이다.

정확값 원칙(S4-58 — 설계서 verifier_v2_domains.md §3.5-2 "부동소수점 사용 금지"):
    데이터·주장값은 JSON/문자열에서 곧바로 `Fraction`(정확 유리수)으로 읽는다(float 경유 0건).
    평균·중앙값·분산·사분위수는 유리수 정확값이다. 표준편차·상관계수는 제곱근이 유리수일 때만
    정확값이고, 아니면 정수 제곱근(`math.isqrt`)으로 10^-60 이내 근사를 만들어 판정한다
    (판정 해상도 한계 = 10^-60 — 정책 경계가 그보다 가까운 무리수는 다루지 않는다).

DSL(`verify.conditions`):
    data=[1,2,3,4,5]; stat=mean
    data=[[1,2],[3,4],[5,6]]; stat=corr; columns=[0,1]
    data=[10,20,30,40]; stat=median
    data=[1,2,4]; stat=mean; tolerance=round:2     # 주장값 == 계산값의 소수 2자리 반올림

지원 stat: mean(평균), median(중앙값), variance(분산·기본 n-1), std(표준편차·기본 n-1),
           q1(1사분위수), q3(3사분위수), corr(피어슨 상관계수·2열).
선택 절: columns=[...]·variance_kind=sample|population·tolerance=<정책>.

허용오차 정책(`tolerance`):
    exact      주장값이 계산값과 정확히 같아야 한다(무리수면 unverifiable).
    abs:<양수>  |계산값-주장값| <= 양수 (경계 포함).
    rel:<0~1>  |계산값-주장값| <= 비율 x |계산값| (경계 포함 · 계산값이 0이면 정확 일치).
    round:<k>  주장값 == 계산값을 소수 k자리(0~15)로 반올림한 값(half-up · 0에서 먼 쪽).
    (절 생략) 계산값이 유한소수면 exact, 무한소수·무리수면 abs:0.000000001.
미지 절 이름·중복 절은 조용히 무시하지 않고 unverifiable로 돌려보낸다 — 철자가 틀린 정책 절이
검증 강도를 몰래 바꾸는 것을 막기 위함이다.

7계층: L3 지역. DB 0·LLM 0(순수 계산). import-linter L3 내부.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from whymath_backend.l3.verify_answer import AnswerVerdict

__all__ = [
    "StatisticalClaimError",
    "StatisticalResult",
    "TolerancePolicy",
    "describe_statistical_model_ko",
    "parse_statistical_model",
    "verify_statistical_claim",
]


class StatisticalClaimError(ValueError):
    """DSL 파싱·모델 구성 실패 — 조용한 통과 금지(호출자가 unverifiable로 변환)."""


StatKind = Literal["mean", "median", "variance", "std", "q1", "q3", "corr"]
VarianceKind = Literal["sample", "population"]
ToleranceKind = Literal["exact", "abs", "rel", "round"]

_STAT_KINDS: tuple[str, ...] = ("mean", "median", "variance", "std", "q1", "q3", "corr")
_KNOWN_CLAUSES: frozenset[str] = frozenset(
    {"data", "stat", "columns", "variance_kind", "tolerance"}
)


@dataclass(frozen=True, slots=True)
class TolerancePolicy:
    """허용오차 정책 — kind에 따라 bound(abs·rel) 또는 places(round)를 쓴다."""

    kind: ToleranceKind
    bound: Fraction = Fraction(0)
    places: int = 0

    @property
    def label(self) -> str:
        """DSL 표기와 같은 정책 라벨(결과·사유 노출용)."""
        if self.kind == "exact":
            return "exact"
        if self.kind == "round":
            return f"round:{self.places}"
        return f"{self.kind}:{_format_number(self.bound)}"


@dataclass(frozen=True, slots=True)
class StatisticalModel:
    """형식 모델 = 1차원 값 + corr용 2차원 표 + 요청 통계량 + 열 인덱스 + 허용오차 정책."""

    values: tuple[Fraction, ...]
    table: tuple[tuple[Fraction, ...], ...] | None
    stat: StatKind
    columns: tuple[int, ...] | None
    variance_kind: VarianceKind | None
    source: str
    tolerance: TolerancePolicy | None = None


@dataclass(frozen=True, slots=True)
class StatisticalResult:
    """전수 계산 결과.

    `value`는 하위 호환용 float(교차검증 `machine_value` 계약) — 판정에는 쓰지 않는다.
    `exact_value`는 유리수 정확값(무리수면 None), `policy`는 실제로 적용된 정책 라벨이다.
    `approx_value`는 10^-60 이내 근사(유리수면 정확값과 같다) — 교차검증이 float을 거치지 않고
    같은 정책으로 대조하도록 넘기는 재료다(S4-70).
    """

    value: float | None
    n: int
    description: str
    exact_value: Fraction | None = None
    policy: str = ""
    approx_value: Fraction | None = None


@dataclass(frozen=True, slots=True)
class _Stat:
    """통계량 — 유리수면 exact가 정확값, 무리수면 exact=None이고 approx만 10^-60 이내 근사."""

    exact: Fraction | None
    approx: Fraction


_MAX_DATA_POINTS = 10_000
_MAX_TOKEN_CHARS = 64  # 수 토큰 최대 길이 — 거대 정수/소수 입력의 자원 고갈 차단
_MAX_EXPONENT = 30  # 과학 표기 지수 절댓값 상한 — `Fraction("1e999999999")` 폭탄 차단
_MAX_ROUND_PLACES = 15
_IRRATIONAL_DIGITS = 60

_EXACT_POLICY = TolerancePolicy("exact")
# 무한소수·무리수 기본 정책 — 절대오차만 쓴다. 상대오차를 섞으면 큰 값에서 허용 폭이
# 값에 비례해 커져(평균 1조에서 1000) 어긋난 주장을 통과시킨다(S4-58 실측 결함 B).
_DEFAULT_APPROX_POLICY = TolerancePolicy("abs", bound=Fraction(1, 10**9))

_NUMBER_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE](?P<exp>[+-]?[0-9]+))?")
# 숫자와 숫자 사이의 공백 — "1 1/2"를 "11/2"로 붙여 읽는 오독 차단
_SPLIT_DIGITS_RE = re.compile(r"[0-9]\s+[0-9]")


def _exact_number(text: str) -> Fraction:
    """십진 수 토큰 → 정확 유리수. float 경유 금지 · 길이·지수 상한으로 자원 고갈 차단.

    `float()`·`Fraction()`이 받아주는 `inf`·`nan`·밑줄(`1_000`)·비 ASCII 숫자는 정규식으로
    먼저 거른다.
    """
    if len(text) > _MAX_TOKEN_CHARS:
        raise StatisticalClaimError(f"수 토큰이 {_MAX_TOKEN_CHARS}자 한도 초과: {text[:16]!r}…")
    match = _NUMBER_RE.fullmatch(text)
    if match is None:
        raise StatisticalClaimError(f"숫자로 읽을 수 없음: {text!r}")
    exponent = match.group("exp")
    if exponent is not None and abs(int(exponent)) > _MAX_EXPONENT:
        raise StatisticalClaimError(f"지수가 한도 ±{_MAX_EXPONENT} 초과: {text!r}")
    return Fraction(text)


def _parse_data(raw: str) -> object:
    """data=[...] 문자열을 안전하게 JSON 배열로 파싱. eval 금지 · 수는 정확 유리수로 읽는다."""
    try:
        # NaN·Infinity는 json이 float으로 받지만 Fraction이 아니므로 _as_number가 거절한다.
        parsed = json.loads(raw, parse_int=_exact_number, parse_float=_exact_number)
    except json.JSONDecodeError as exc:
        raise StatisticalClaimError(f"data JSON 파싱 실패: {raw!r}") from exc
    except RecursionError as exc:
        raise StatisticalClaimError("data 중첩이 너무 깊음") from exc
    if not isinstance(parsed, list):
        raise StatisticalClaimError(f"data는 배열이어야 함: {parsed!r}")
    return parsed


def _as_number(item: object) -> Fraction:
    """data 요소 1개 검증 — JSON 수는 이미 Fraction이다. bool·문자열·null·중첩은 거절."""
    if isinstance(item, bool):
        raise StatisticalClaimError("data에 bool 값은 허용되지 않음")
    if not isinstance(item, Fraction):
        raise StatisticalClaimError(f"data 요소가 숫자가 아님: {item!r}")
    return item


def _flatten_numbers(parsed: object) -> tuple[Fraction, ...]:
    """1차원 숫자 배열 검증/변환."""
    if not isinstance(parsed, list):
        raise StatisticalClaimError(f"1차원 data는 리스트여야 함: {parsed!r}")
    if not parsed:
        raise StatisticalClaimError("data가 비어 있음")
    if len(parsed) > _MAX_DATA_POINTS:
        raise StatisticalClaimError(f"data 포인트 수 {len(parsed)}가 한도 {_MAX_DATA_POINTS} 초과")
    return tuple(_as_number(item) for item in parsed)


def _flatten_table(parsed: object) -> tuple[tuple[Fraction, ...], ...]:
    """2차원 숫자 표 검증/변환."""
    if not isinstance(parsed, list):
        raise StatisticalClaimError(f"2차원 data는 리스트여야 함: {parsed!r}")
    if not parsed:
        raise StatisticalClaimError("data가 비어 있음")
    rows: list[tuple[Fraction, ...]] = []
    expected_len: int | None = None
    for row in parsed:
        if not isinstance(row, list):
            raise StatisticalClaimError(f"data 행이 배열이 아님: {row!r}")
        if not row:
            raise StatisticalClaimError("data 행이 비어 있음")
        if expected_len is None:
            expected_len = len(row)
        elif len(row) != expected_len:
            raise StatisticalClaimError(f"data 행 길이 불일치: {len(row)} != {expected_len}")
        rows.append(tuple(_as_number(item) for item in row))
    if len(rows) > _MAX_DATA_POINTS:
        raise StatisticalClaimError(f"data 포인트 수 {len(rows)}가 한도 {_MAX_DATA_POINTS} 초과")
    return tuple(rows)


def _is_1d(data: object) -> bool:
    """파싱된 data가 1차원인가."""
    return isinstance(data, list) and (not data or not isinstance(data[0], list))


def _parse_tolerance(raw: str) -> TolerancePolicy:
    """`tolerance=` 절 값 → 정책. 형식 오류는 조용히 기본 정책으로 떨어지지 않고 거절한다."""
    text = raw.strip().lower()
    if text == "exact":
        return _EXACT_POLICY
    kind, sep, argument = text.partition(":")
    argument = argument.strip()
    if not sep or kind not in ("abs", "rel", "round"):
        raise StatisticalClaimError(
            f"미지 tolerance: {raw!r} (exact | abs:<양수> | rel:<0~1> | round:<0~15>)"
        )
    if kind == "round":
        if not re.fullmatch(r"[0-9]{1,2}", argument):
            raise StatisticalClaimError(f"round 자릿수는 0~{_MAX_ROUND_PLACES} 정수: {raw!r}")
        places = int(argument)
        if places > _MAX_ROUND_PLACES:
            raise StatisticalClaimError(f"round 자릿수가 한도 {_MAX_ROUND_PLACES} 초과: {raw!r}")
        return TolerancePolicy("round", places=places)
    bound = _exact_number(argument)
    if bound <= 0:
        raise StatisticalClaimError(f"{kind} 한계는 양수여야 함(정확 일치는 exact): {raw!r}")
    if kind == "rel" and bound >= 1:
        raise StatisticalClaimError(f"rel 한계는 1 미만이어야 함: {raw!r}")
    return TolerancePolicy("rel" if kind == "rel" else "abs", bound=bound)


def _parse_columns(raw: str) -> tuple[int, ...]:
    """columns=[...] → 열 인덱스 튜플. bool이 아닌 JSON 정수만 허용한다.

    `int(c)` 변환은 쓰지 않는다 — `1.5`를 1로 자르고 `"1"`·`true`를 1로 읽어, 다른 열의 값으로
    조용히 판정하기 때문이다. 파싱 단계에서 새는 예외(깊은 중첩·4300자리 초과 정수)도 모두
    StatisticalClaimError로 돌려 verify_statistical_claim이 unverifiable로 처리하게 한다.
    """
    try:
        cols = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StatisticalClaimError(f"columns JSON 파싱 실패: {raw!r}") from exc
    except RecursionError as exc:
        raise StatisticalClaimError("columns 중첩이 너무 깊음") from exc
    except ValueError as exc:
        # 정수 문자열 변환 한도(4300자리) 초과 — JSONDecodeError가 아닌 ValueError로 새던 경로.
        raise StatisticalClaimError(f"columns 수를 읽을 수 없음: {raw[:16]!r}…") from exc
    if not isinstance(cols, list):
        raise StatisticalClaimError(f"columns는 배열이어야 함: {cols!r}")
    for c in cols:
        # bool은 int의 하위 클래스라 isinstance(True, int)가 참이다 — 따로 걸러야 한다.
        if isinstance(c, bool) or not isinstance(c, int):
            raise StatisticalClaimError(f"columns는 정수 인덱스만 허용함: {c!r}")
    return tuple(cols)


def parse_statistical_model(conditions: str) -> StatisticalModel:
    """`verify.conditions` 문자열 → StatisticalModel."""
    parts = conditions.split(";")
    kwargs: dict[str, str] = {}
    for part in parts:
        piece = part.strip()
        if not piece:
            continue
        if "=" not in piece:
            raise StatisticalClaimError(f"조건 절 형식 오류: {piece!r}")
        key, _, value = piece.partition("=")
        key = key.strip()
        value = value.strip()
        if key in kwargs:
            raise StatisticalClaimError(f"조건 절 중복: {key}")
        if key not in _KNOWN_CLAUSES:
            raise StatisticalClaimError(f"미지 조건 절: {key!r}")
        kwargs[key] = value

    if "data" not in kwargs or "stat" not in kwargs:
        raise StatisticalClaimError("data·stat 절은 필수")

    raw_data = _parse_data(kwargs["data"])
    stat_raw = kwargs["stat"].strip().lower()
    if stat_raw not in _STAT_KINDS:
        raise StatisticalClaimError(f"미지 stat: {stat_raw!r}")
    stat: StatKind = stat_raw  # type: ignore[assignment]

    columns: tuple[int, ...] | None = None
    if "columns" in kwargs:
        columns = _parse_columns(kwargs["columns"])

    variance_kind: VarianceKind | None = None
    if "variance_kind" in kwargs:
        vk = kwargs["variance_kind"].strip().lower()
        if vk not in ("sample", "population"):
            raise StatisticalClaimError(f"미지 variance_kind: {vk!r}")
        variance_kind = vk  # type: ignore[assignment]

    tolerance = _parse_tolerance(kwargs["tolerance"]) if "tolerance" in kwargs else None

    table: tuple[tuple[Fraction, ...], ...] | None = None
    if _is_1d(raw_data):
        values = _flatten_numbers(raw_data)
        if stat == "corr":
            raise StatisticalClaimError("corr는 2차원 data가 필요함")
    else:
        table = _flatten_table(raw_data)
        if stat == "corr":
            if columns is None or len(columns) != 2:
                raise StatisticalClaimError("corr는 columns=[i,j]가 필요함")
            i, j = columns
            n_cols = len(table[0])
            if not (0 <= i < n_cols and 0 <= j < n_cols):
                raise StatisticalClaimError(f"columns 인덱스 범위 초과: {columns}")
            values = tuple(row[i] for row in table)
        elif columns is not None:
            if len(columns) != 1:
                raise StatisticalClaimError(f"2차원 data에서 {stat}는 columns=[단일열]이 필요함")
            col_idx = columns[0]
            n_cols = len(table[0])
            if not (0 <= col_idx < n_cols):
                raise StatisticalClaimError(f"columns 인덱스 범위 초과: {col_idx}")
            values = tuple(row[col_idx] for row in table)
            columns = None
        else:
            # 2차원 data인데 열 지정이 없으면 첫 번째 열 사용
            values = tuple(row[0] for row in table)

    return StatisticalModel(
        values=values,
        table=table,
        stat=stat,
        columns=columns,
        variance_kind=variance_kind,
        source=conditions,
        tolerance=tolerance,
    )


# ──────────────────────────────────────────────────────────────────────────
# 정확 유리수 통계량
# ──────────────────────────────────────────────────────────────────────────
def _exact_stat(value: Fraction) -> _Stat:
    return _Stat(exact=value, approx=value)


def _negate(stat: _Stat) -> _Stat:
    return _Stat(exact=None if stat.exact is None else -stat.exact, approx=-stat.approx)


def _sqrt_stat(value: Fraction) -> _Stat:
    """음이 아닌 유리수의 제곱근 — 완전제곱 유리수면 정확값, 아니면 10^-60 이내 근사(내림)."""
    num_root = math.isqrt(value.numerator)
    den_root = math.isqrt(value.denominator)
    if num_root * num_root == value.numerator and den_root * den_root == value.denominator:
        return _exact_stat(Fraction(num_root, den_root))
    scale = 10**_IRRATIONAL_DIGITS
    root = math.isqrt(value.numerator * scale * scale // value.denominator)
    return _Stat(exact=None, approx=Fraction(root, scale))


def _mean(values: tuple[Fraction, ...]) -> Fraction:
    return sum(values, Fraction(0)) / len(values)


def _sum_sq_dev(values: tuple[Fraction, ...]) -> Fraction:
    """편차 제곱합 — 분산 분자."""
    mean_v = _mean(values)
    return sum(((x - mean_v) ** 2 for x in values), Fraction(0))


def _median(values: tuple[Fraction, ...]) -> Fraction:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _percentile(values: tuple[Fraction, ...], p: Fraction) -> Fraction:
    """선형 보간법 percentile (0 <= p <= 1) — 정확 유리수."""
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    pos = (len(ordered) - 1) * p
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    weight = pos - lo
    return ordered[lo] * (1 - weight) + ordered[hi] * weight


def _variance(values: tuple[Fraction, ...], kind: VarianceKind | None) -> Fraction:
    n = len(values)
    if kind == "population":
        return _sum_sq_dev(values) / n
    if n < 2:
        # 표본분산의 분모 n-1 이 0 이다. S4-53 은 이를 0 으로 계산해 주장값 0 을 pass 시켰다.
        raise StatisticalClaimError(
            "표본분산·표본표준편차는 n=1 에서 정의되지 않음(분모 n-1=0) "
            "— 모집단 값이면 variance_kind=population"
        )
    return _sum_sq_dev(values) / (n - 1)


def _correlation(col_x: tuple[Fraction, ...], col_y: tuple[Fraction, ...]) -> _Stat | None:
    """피어슨 상관계수 = sign(Sxy) x sqrt(Sxy^2 / (Sxx x Syy)). 상수 열이면 None."""
    mean_x = _mean(col_x)
    mean_y = _mean(col_y)
    sxx = sum(((x - mean_x) ** 2 for x in col_x), Fraction(0))
    syy = sum(((y - mean_y) ** 2 for y in col_y), Fraction(0))
    if sxx == 0 or syy == 0:
        return None
    sxy = sum(((x - mean_x) * (y - mean_y) for x, y in zip(col_x, col_y, strict=True)), Fraction(0))
    magnitude = _sqrt_stat(sxy * sxy / (sxx * syy))
    return magnitude if sxy >= 0 else _negate(magnitude)


# ──────────────────────────────────────────────────────────────────────────
# 표기 — 정확값(유한소수·분수)을 주 표기로 하고, float은 무한소수·무리수의 보조 근사로만 덧붙인다
# ──────────────────────────────────────────────────────────────────────────
def _decimal_digits_needed(value: Fraction) -> int | None:
    """유한소수면 소수점 아래 필요한 자릿수, 아니면 None(분모에 2·5 이외의 소인수)."""
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    return max(twos, fives) if denominator == 1 else None


def _format_number(value: Fraction) -> str:
    """유한소수는 정확한 십진 표기, 아니면 분수 `a/b`."""
    digits = _decimal_digits_needed(value)
    if digits is None:
        return f"{value.numerator}/{value.denominator}"
    if digits == 0:
        return str(value.numerator)
    scaled = abs(value.numerator) * 10**digits // value.denominator
    text = str(scaled).rjust(digits + 1, "0")
    return f"{'-' if value < 0 else ''}{text[:-digits]}.{text[-digits:]}"


def _format_stat(stat: _Stat) -> str:
    if stat.exact is None:
        return f"≈ {float(stat.approx)!r} (무리수)"
    text = _format_number(stat.exact)
    if _decimal_digits_needed(stat.exact) is None:
        return f"{text} (≈ {float(stat.exact)!r})"
    return text


def _compute(model: StatisticalModel) -> tuple[_Stat | None, str]:
    """요청 통계량 전수 계산 — (값, 설명). 값이 None이면 계산 불가(설명이 사유)."""
    values = model.values
    n = len(values)
    if n == 0:
        return None, "데이터가 비어 있음"

    if model.stat == "corr":
        if model.columns is None or len(model.columns) != 2 or model.table is None:
            return None, "corr는 2차원 data와 columns=[i,j]가 필요함"
        i, j = model.columns
        col_i = tuple(row[i] for row in model.table)
        col_j = tuple(row[j] for row in model.table)
        if len(col_i) < 2:
            return None, "상관계수 계산에 필요한 데이터 포인트가 2개 미만"
        corr = _correlation(col_i, col_j)
        if corr is None:
            return None, "상관계수 계산 불가: 상수 열(분산 0)"
        return (
            corr,
            f"피어슨 상관계수(n={len(col_i)}, columns={model.columns}) = {_format_stat(corr)}",
        )

    kind = model.variance_kind or "sample"
    result: _Stat
    if model.stat == "mean":
        result = _exact_stat(_mean(values))
        return result, f"평균(n={n}) = {_format_stat(result)}"
    if model.stat == "median":
        result = _exact_stat(_median(values))
        return result, f"중앙값(n={n}) = {_format_stat(result)}"
    if model.stat == "variance":
        result = _exact_stat(_variance(values, model.variance_kind))
        return result, f"분산(n={n}, variance_kind={kind}) = {_format_stat(result)}"
    if model.stat == "std":
        result = _sqrt_stat(_variance(values, model.variance_kind))
        return result, f"표준편차(n={n}, variance_kind={kind}) = {_format_stat(result)}"
    if model.stat == "q1":
        result = _exact_stat(_percentile(values, Fraction(1, 4)))
        return result, f"1사분위수(n={n}) = {_format_stat(result)}"
    if model.stat == "q3":
        result = _exact_stat(_percentile(values, Fraction(3, 4)))
        return result, f"3사분위수(n={n}) = {_format_stat(result)}"
    raise StatisticalClaimError(f"미지 stat: {model.stat}")


def describe_statistical_model_ko(model: StatisticalModel, result: StatisticalResult) -> str:
    """형식 모델 + 계산 결과를 한국어 산문으로 — LLM 교차검증 관점 입력."""
    if model.stat == "corr" and model.table is not None:
        return (
            f"데이터는 {len(model.table)}개 행의 표이며, "
            f"열 {model.columns} 간 피어슨 상관계수를 계산한다. {result.description}."
        )
    shown = ", ".join(_format_number(v) for v in model.values)
    return f"데이터: [{shown}]. {result.description}."


# ──────────────────────────────────────────────────────────────────────────
# 주장값 파싱 · 판정
# ──────────────────────────────────────────────────────────────────────────
def _parse_claimed(answer: str) -> tuple[Fraction | None, str | None]:
    """주장값 파싱 — '3.5', 'mean=3.5', 'a/b' 등. 정확 유리수로 읽고 모호하면 거절."""
    stripped = answer.strip()
    if not stripped:
        return None, "주장값이 비어 있음"
    if _SPLIT_DIGITS_RE.search(stripped):
        # "1 1/2"(혼합수)·"1 000"을 공백 제거로 붙여 읽으면 전혀 다른 수가 된다.
        return None, f"주장값 {answer!r}에 공백으로 갈라진 숫자가 있어 읽지 않음"
    text = re.sub(r"\s+", "", stripped)
    # 'mean=3.5' 형태에서 값 부분만 추출
    value_text = text.partition("=")[2] if "=" in text else text
    try:
        # 분수 'a/b' 지원
        if "/" in value_text:
            num, den = value_text.split("/", 1)
            denominator = _exact_number(den)
            if denominator == 0:
                return None, f"주장값 {answer!r}의 분모가 0"
            return _exact_number(num) / denominator, None
        return _exact_number(value_text), None
    except StatisticalClaimError as exc:
        return None, f"주장값 {answer!r}을 읽을 수 없음 — {exc}"


def _is_terminating(stat: _Stat) -> bool:
    return stat.exact is not None and _decimal_digits_needed(stat.exact) is not None


def _effective_policy(stat: _Stat, declared: TolerancePolicy | None) -> TolerancePolicy:
    """선언된 정책이 있으면 그것, 없으면 계산값 성질로 기본 정책을 고른다."""
    if declared is not None:
        return declared
    return _EXACT_POLICY if _is_terminating(stat) else _DEFAULT_APPROX_POLICY


def _round_half_up(value: Fraction, places: int) -> Fraction:
    """소수 places자리 반올림 — half-up(0에서 먼 쪽), 정확 유리수 연산."""
    scale = 10**places
    scaled = abs(value) * scale
    rounded = (2 * scaled.numerator + scaled.denominator) // (2 * scaled.denominator)
    return Fraction(rounded if value >= 0 else -rounded, scale)


def _judge(
    stat: _Stat, claimed: Fraction, policy: TolerancePolicy, label: str
) -> tuple[Literal["pass", "fail", "unverifiable"], str | None]:
    """정책에 따른 판정 — (상태, 사유). pass이면 사유 None. label은 사유 표기용."""
    if policy.kind == "exact":
        if stat.exact is None:
            return (
                "unverifiable",
                "계산값이 무리수라 정확값 비교 불가 — tolerance=abs:·rel:·round: 중 하나를 지정",
            )
        matched = claimed == stat.exact
        expected_text = _format_number(stat.exact)
    elif policy.kind == "abs":
        matched = abs(stat.approx - claimed) <= policy.bound
        expected_text = _format_stat(stat)
    elif policy.kind == "rel":
        matched = abs(stat.approx - claimed) <= policy.bound * abs(stat.approx)
        expected_text = _format_stat(stat)
    else:
        rounded = _round_half_up(stat.approx, policy.places)
        matched = claimed == rounded
        expected_text = (
            f"{_format_stat(stat)} → 소수 {policy.places}자리 반올림 {_format_number(rounded)}"
        )
    if matched:
        return "pass", None
    return (
        "fail",
        f"계산값 {expected_text}와 주장 {_format_number(claimed)} 불일치(정책 {label})",
    )


def verify_statistical_claim(
    conditions: str, answer: str
) -> tuple[AnswerVerdict, tuple[str, ...], StatisticalResult]:
    """통계 자료형 검증 — (AnswerVerdict, residual_axes, StatisticalResult) 반환.

    pass: 계산값과 주장값이 허용오차 정책 내 일치.
    fail: 주장값이 계산값과 다름.
    unverifiable: DSL 파싱 실패·계산 불가·주장값 파싱 불가·정책이 계산값에 적용 불가.
    """
    residual_axes: tuple[str, ...] = ("자료↔발문 정합", "표본 추출 방법", "자료 해석의 모호성")
    try:
        model = parse_statistical_model(conditions)
        stat, description = _compute(model)
    except StatisticalClaimError as exc:
        return (
            AnswerVerdict(state="unverifiable", reason=f"통계검증 — {exc}", samples_checked=0),
            residual_axes,
            StatisticalResult(value=None, n=0, description=""),
        )

    if stat is None:
        return (
            AnswerVerdict(state="unverifiable", reason="통계검증 — 계산 불가", samples_checked=0),
            residual_axes,
            StatisticalResult(value=None, n=0, description=description),
        )

    policy = _effective_policy(stat, model.tolerance)
    policy_label = policy.label if model.tolerance is not None else f"기본→{policy.label}"
    result = StatisticalResult(
        value=float(stat.approx),
        n=len(model.values),
        description=description,
        exact_value=stat.exact,
        policy=policy_label,
        approx_value=stat.approx,
    )

    claimed, reason = _parse_claimed(answer)
    if claimed is None:
        return (
            AnswerVerdict(
                state="unverifiable",
                reason=f"통계검증 — {reason}",
                samples_checked=result.n,
            ),
            residual_axes,
            result,
        )

    state, judge_reason = _judge(stat, claimed, policy, policy_label)
    return (
        AnswerVerdict(
            state=state,
            reason=None if judge_reason is None else f"통계검증 — {judge_reason}",
            samples_checked=result.n,
        ),
        residual_axes,
        result,
    )
