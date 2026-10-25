"""수치 반례 fuzzer — 초인간 검증 §2 *적대성*(문항당 ≥10,000 검산·순수·결정론·LLM 0).

정본: `docs/standards/superhuman_verification_standard.md` §2 "S2 적대성". SymPy 심볼릭
검산(`verify_answer`)과 **원리가 다른 독립 축**이다 — 조건식을 수치 함수로 만들어
구간을 촘촘히(기본 10,000점) 훑어 **모든 실근을 무차별 탐색**한 뒤, 주장된 정답이
정말 근인지·근 선택(큰/작은/유일)이 옳은지를 반례로 공격한다. 심볼릭 단순화의
사각지대(정리 실패·비자명 형태)에서도 수치는 반례를 낸다 — K≥3 독립 검증기의 둘째 축.

판정(3상태·pass 위장 절대 금지):
  - **pass**   : 주장 정답이 수치적으로 근이고, 선택(있으면)도 탐색된 근들 사이에서 옳다.
  - **fail**   : 반례 발견 — 주장 정답이 근이 아니거나(f(답)≠0), 선택을 어기는 근이 존재
                 (예: "큰 근"이라는데 더 큰 근이 있음). 반례 값을 보고한다.
  - **unverifiable** : 단변수 등식이 아님(연립·부등식·다변수)·파싱 불가·정답 수치화 불가·
                 구간에서 근을 못 찾음. 확신 없으면 단정하지 않는다(정직 회피).

독립성: 조건 파싱만 `verify_answer._parse_condition`을 재사용(같은 L3 계층·표기 drift
방지)하고, 근 탐색·판정은 심볼릭 solve를 전혀 쓰지 않는 순수 수치 경로다.

원문 정의역(P3-79): 파싱한 잔차는 평가 파싱이 자동 약분한 식이라(`x*(x - 2)/(x - 2) = 2` → x - 2)
원문에서 정의되지 않는 점(무연근)이 수치 근으로 잡힌다. 그래서 주장 정답과 선택 판정에 쓰는 근은
`verify_answer.condition_definedness`(허용 목록·실행 없는 원문 평가)로 거른다 — 정의되지 않는 정답은
반례, 판정 불가는 pass 로 단정하지 않는다.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import sympy

from whymath_backend.l3.safe_parse import safe_sympify
from whymath_backend.l3.verify_answer import _parse_condition, condition_definedness

__all__ = ["FuzzVerdict", "fuzz_answer"]

# 침묵 실패 금지(CLAUDE.md) — 파싱 회피는 예외 타입명을 남긴다(값은 싣지 않는다).
logger = logging.getLogger("whymath.l3.equivalent.counterexample_fuzz")

# 기본 탐색 시행 수(§2 "≥10,000") — 구간을 이만큼 등분해 각 점에서 잔차를 평가한다.
_DEFAULT_TRIALS = 10_000

# 기본 탐색 반경 — 한국 중·고 수준 근은 이 범위 안(±50). 밖의 근은 unverifiable로 정직 처리.
_DEFAULT_RADIUS = 50.0

# 근 판정 허용오차 — |f(x)|<tol 이면 근, 두 근이 이보다 가까우면 동일 근으로 병합.
_DEFAULT_TOL = 1e-7

Selection = Literal["largest", "smallest", "unique"]

# 수치 근을 정확값으로 맞출 때 차례로 쓰는 허용치(P3-79 — 정확 잔차 0 확인을 거친 값만 쓴다).
_SNAP_TOLERANCES: tuple[float, ...] = (1e-30, 1e-12, 1e-7)


@dataclass(slots=True, frozen=True)
class FuzzVerdict:
    """수치 fuzz 결과 — 상태·사유·탐색 통계. 불변."""

    state: Literal["pass", "fail", "unverifiable"]
    reason: str | None
    trials: int
    """실제 평가한 격자점 수(적대성 척도)."""
    roots_found: tuple[float, ...] = ()
    """수치로 탐색된 서로 다른 실근(정렬)."""


def _to_float(value: str) -> float | None:
    """정답 문자열(정확값 'p + sqrt(q)' 포함)을 float으로 — 실패·비실수면 None."""
    try:
        # CONST-09: 생성물 정답 문자열도 안전 진입점으로 파싱한다
        # (거부는 SympifyError 하위라 아래 except가 받는다).
        evaluated = safe_sympify(value).evalf()
        result = complex(evaluated)
    except (sympy.SympifyError, TypeError, ValueError) as exc:
        logger.debug("counterexample_fuzz 정답 파싱 회피: %s", type(exc).__name__)
        return None
    if abs(result.imag) > 1e-9:
        return None  # 복소수 정답은 이 실수축 fuzzer의 범위 밖(정직)
    return float(result.real)


def _find_roots(func: object, radius: float, trials: int, tol: float) -> tuple[list[float], int]:
    """[-radius, radius]를 trials 등분해 실근을 무차별 탐색(부호 변화 + tangent 국소최솟값).

    반환: (서로 다른 근 정렬 리스트, 유효 평가 점 수). 세 경로로 근을 잡는다:
      · 근접 0(|f|≤tol) · 부호 변화(이분법 정밀화) · **tangent 근**(중근처럼 부호가 안
      바뀌는 근 — |f|의 국소 최솟값을 삼분탐색으로 좁혀 잔차가 0에 수렴하면 근).
    평가 불가(특이점·복소)는 건너뛴다(유효 점에서 제외).
    """
    assert callable(func)
    step = (2.0 * radius) / (trials - 1)
    xs = [-radius + step * i for i in range(trials)]

    def _f(x: float) -> float | None:
        try:
            value = func(x)
        except (ValueError, ZeroDivisionError, ArithmeticError, TypeError):
            return None
        if isinstance(value, complex):
            if abs(value.imag) > tol:
                return None
            value = value.real
        fv = float(value)
        if math.isnan(fv) or math.isinf(fv):
            return None
        return fv

    def _bisect(lo: float, hi: float, flo: float) -> float:
        """부호 변화 구간 [lo,hi]를 이분법으로 좁혀 근 반환(최대 60회)."""
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            fmid = _f(mid)
            if fmid is None or abs(fmid) <= tol:
                return mid
            if flo * fmid < 0:
                hi = mid
            else:
                lo, flo = mid, fmid
        return 0.5 * (lo + hi)

    def _refine_min(lo: float, hi: float) -> float | None:
        """[lo,hi]에서 |f|의 최솟점을 삼분탐색으로 좁혀, 잔차가 tol에 수렴하면 근 반환."""
        for _ in range(80):
            m1 = lo + (hi - lo) / 3.0
            m2 = hi - (hi - lo) / 3.0
            f1, f2 = _f(m1), _f(m2)
            if f1 is None or f2 is None:
                return None
            if abs(f1) < abs(f2):
                hi = m2
            else:
                lo = m1
        mid = 0.5 * (lo + hi)
        fmid = _f(mid)
        return mid if fmid is not None and abs(fmid) <= tol else None

    roots: list[float] = []
    valid = 0
    # (x, fx) 유효 점 3연속 창으로 부호 변화·국소최솟값을 동시에 본다.
    window: list[tuple[float, float]] = []
    for x in xs:
        fx = _f(x)
        if fx is None:
            window.clear()
            continue
        valid += 1
        if abs(fx) <= tol:
            roots.append(x)
            window = [(x, fx)]
            continue
        if window and window[-1][1] * fx < 0:
            roots.append(_bisect(window[-1][0], x, window[-1][1]))
        window.append((x, fx))
        if len(window) == 3:
            (x0, f0), (x1, f1), (x2, f2) = window
            # tangent 근 후보: 가운데가 |f| 국소 최솟값 → 삼분탐색 정밀화.
            if abs(f1) < abs(f0) and abs(f1) < abs(f2):
                candidate = _refine_min(x0, x2)
                if candidate is not None:
                    roots.append(candidate)
            window.pop(0)

    # 근접 근 병합(정렬 후 tol*10 이내 동일 근으로).
    roots.sort()
    merged: list[float] = []
    for r in roots:
        if not merged or abs(r - merged[-1]) > tol * 10:
            merged.append(r)
    return merged, valid


def _exact_residual_nonzero(
    residual: sympy.Expr, symbol: sympy.Symbol, answer_exact: sympy.Expr
) -> bool:
    """정확값 답의 잔차가 정확히 0 이 아닌가(P3-79).

    근사 소수가 섞이면 False(수치 판정에 맡긴다).
    """
    if answer_exact.has(sympy.Float) or residual.has(sympy.Float):
        return False
    try:
        value = residual.subs(symbol, answer_exact)
        return bool(not value.free_symbols and value.is_zero is False)
    except Exception as exc:  # noqa: BLE001 — 정확 잔차 계산 불가는 수치 판정에 맡긴다
        logger.debug("counterexample_fuzz 정확 잔차 회피: %s", type(exc).__name__)
        return False


def _polished(residual: sympy.Expr, symbol: sympy.Symbol, root: float) -> sympy.Expr:
    """수치 근을 50자리로 다듬는다(무연근이면 그 점으로 수렴해 원문 분모가 사실상 0 이 된다)."""
    try:
        return sympy.Float(sympy.nsolve(residual, symbol, root, prec=50, verify=False), 50)
    except Exception as exc:  # noqa: BLE001 — 다듬기 실패는 원래 근사값으로
        logger.debug("counterexample_fuzz 근 다듬기 회피: %s", type(exc).__name__)
        return sympy.Float(root, 50)


def _root_point(residual: sympy.Expr, symbol: sympy.Symbol, root: float) -> sympy.Expr:
    """원문 정의역 평가에 넣을 수치 근의 점 — 다듬은 근이 간단한 정확값(`0`·`2`·`sqrt(2)`)의 근이면
    그 정확값, 아니면 50자리 근사 소수. 근사 소수 점은 0 에 가까운 밑·분모를 '못 가림'으로 둬서
    (`x**2 - 5*x` 의 근 0) 정확값으로 맞출 수 있는 근은 맞춘다."""
    polished = _polished(residual, symbol, root)
    # 중근은 뉴턴 다듬기가 느리게 수렴한다(삼중근 0 이 1e-26 근처에 멈춘다) — 허용치를 넓혀 가며
    # 맞춰 본다. 맞춘 값은 정확 잔차가 0 일 때만 쓰므로 넓은 허용치가 근이 아닌 값을 들이지 않는다.
    for tolerance in _SNAP_TOLERANCES:
        try:
            # nsimplify 는 0 근방의 아주 작은 값을 0 으로 접지 않는다 — 0 은 따로 맞춰 본다.
            snapped = (
                sympy.Integer(0)
                if abs(polished) < tolerance
                else sympy.nsimplify(polished, tolerance=tolerance)
            )
            if not snapped.free_symbols and residual.subs(symbol, snapped).is_zero is True:
                return snapped
        except Exception as exc:  # noqa: BLE001 — 정확값 맞추기 실패는 다음 허용치·근사 소수로
            logger.debug("counterexample_fuzz 정확값 맞추기 회피: %s", type(exc).__name__)
    return polished


def _defined_numeric_roots(
    conditions: str,
    residual: sympy.Expr,
    symbol: sympy.Symbol,
    roots: list[float],
    answer_val: float,
    tol: float,
    step: float,
) -> list[float] | None:
    """수치 근 중 원문에서 정의되는 근만(P3-79). 판정 불가 근이 하나라도 있으면 None.

    주장 정답 근방의 근은 위에서 정확값으로 원문 정의역을 이미 봤으므로 그대로 둔다. 나머지는
    그 근의 점(`_root_point` — 정확값으로 맞춰지면 정확값, 아니면 50자리 근사 소수)에서
    `condition_definedness` 를 본다. 무연근은 자동 약분된 분모의 영점이라 다듬기가 그 점(정확값
    2 등)으로 수렴해 정의되지 않음으로 버려지고, 정확값으로 못 맞춘 근이 영점에 가까우면
    정의됨으로 부르지 않아 판정 불가가 된다. `step` 은 탐색 격자 간격 — 무연근 군집 확인 창의
    하한을 정한다(`_isolation_min_window`).
    """
    min_window = _isolation_min_window(step)
    kept: list[float] = []
    for root in roots:
        if abs(root - answer_val) <= tol * 100:
            kept.append(root)
            continue
        point = _root_point(residual, symbol, root)
        state = condition_definedness(conditions, {str(symbol): point})
        if state == "unknown":
            return None
        if state == "undefined" and not _isolated_exact_root(
            residual, symbol, point, root, min_window
        ):
            # P3-79 재검토 P3-1 — 수치 근이 무연근 정확값으로 맞춰졌는데 그 근방(군집)에 다른 근이
            # 숨어 있을 수 있다(`x*(x-2)**2*(x - 2 - 3*10**(-8))/(x-2)` 의 진짜 근 2 + 3e-8). 그
            # 군집을 통째로 버리면 진짜 근이 사라져 거짓 pass 가 난다 — 판정 불가로 닫는다.
            return None
        if state == "defined":
            kept.append(root)
    return kept


# 무연근 군집 확인(P3-79 재검토 P3-1) — 정확 근 주변을 이 창으로 본다(수치 근과의 거리의 배수·하한).
_ISOLATION_FACTOR = 100
_ISOLATION_MIN_WINDOW = sympy.Rational(1, 10**5)
_ISOLATION_MAX_ORDER = 8
# 창 하한 = 탐색 격자 간격의 이 배수(P3-83). 수치 탐색은 한 격자 칸 안(또는 이웃 두 칸)에 든 두 근을
# 부호 변화로 나누지 못하고 하나로 합친다 — 합쳐진 두 근의 최대 간격을 순중복도 1·2, 격자 위 무연근
# 위치 60곳, 간격 0.05~1.65 격자로 쟀더니 순중복도 1 은 0.95배, 2 는 1.6배(기본 격자 0.01 에서
# 0.016)였다(`test_fuzz_isolation_window_covers_numeric_merge_radius` 가 같은 측정을 줄여 다시
# 한다). 종전 하한(1e-5)은 이보다 천 배 좁아, 무연근과 2e-5~3e-3 떨어진 참 근이 무연근 군집으로
# 취급돼 버려졌다(거짓 pass). 2배면 실측 합쳐짐 반경을 덮고 여유가 있다.
_ISOLATION_GRID_STEPS = 2


def _isolation_min_window(step: float) -> sympy.Expr | None:
    """군집 확인 창의 하한(P3-83) — 종전 절대 하한과 격자 간격의 `_ISOLATION_GRID_STEPS` 배 중 큼.

    격자 간격이 유한한 양수가 아니면(0·음수·NaN·무한) 창을 정할 수 없다 — None(모른다)을 돌려주고
    `_isolated_exact_root` 가 이를 '고립을 확인하지 못함'으로 닫는다(종전 하한으로 돌아가지 않는다).
    """
    if not (math.isfinite(step) and step > 0):
        return None
    return max(_ISOLATION_MIN_WINDOW, sympy.Rational(repr(step * _ISOLATION_GRID_STEPS)))


def _isolated_exact_root(
    residual: sympy.Expr,
    symbol: sympy.Symbol,
    point: sympy.Expr,
    root: float,
    min_window: sympy.Expr | None,
) -> bool:
    """정확값 `point` 가 잔차의 근이고, 그 근방에 다른 근이 없다고 확인되는가(P3-79 재검토 P3-1).

    잔차를 `point` 에서 `(x - point)**m · g(x)`(g(point) ≠ 0, m 은 정확 도함수로 구한 중복도)로
    보고, 수치 근이 있던 군집을 덮는 창 `point ± w` 의 양 끝에서 g 가 g(point) 의 절반 안에 머무는지
    본다. 다른 근이 창 안에 있으면 g(point) 가 그만큼 작아 양 끝 값이 크게 벗어난다. 확인하지
    못하면(중복도·0 여부 미정·평가 불가) False — 호출부가 판정 불가로 닫는다.
    """
    if min_window is None or point.free_symbols or point.has(sympy.Float):
        return False
    try:
        derivative = residual
        order = 0
        lead: sympy.Expr | None = None
        while order < _ISOLATION_MAX_ORDER:
            order += 1
            derivative = sympy.diff(derivative, symbol)
            at_point = derivative.subs(symbol, point)
            zero = at_point.is_zero
            if zero is None:
                return False
            if not zero:
                lead = at_point / sympy.factorial(order)
                break
        if lead is None:
            return False
        offset = sympy.Rational(abs(root - float(sympy.N(point, 30))))
        window = max(offset * _ISOLATION_FACTOR, min_window)
        lead_value = complex(sympy.N(lead, 30))
        reference = abs(lead_value)
        for sign in (1, -1):
            edge = point + sign * window
            value = complex(sympy.N(residual.subs(symbol, edge) / (sign * window) ** order, 30))
            # 창 끝이 잔차의 극점이면 값이 zoo/NaN 이다 — NaN 은 아래 비교를 늘 False 로 만들어
            # '벗어나지 않음'(고립됨)으로 접히므로 먼저 거른다(P3-83 — 모른다 ≠ 아니다).
            if not (math.isfinite(value.real) and math.isfinite(value.imag)):
                return False
            if abs(value - lead_value) > reference / 2:
                return False
    except Exception as exc:  # noqa: BLE001 — 확인 불가는 False(판정 불가로 닫는다)
        logger.debug("counterexample_fuzz 무연근 군집 확인 회피: %s", type(exc).__name__)
        return False
    return True


def fuzz_answer(
    conditions: str,
    answer_map: Mapping[str, str],
    answer_selection: str | None = None,
    *,
    trials: int = _DEFAULT_TRIALS,
    radius: float = _DEFAULT_RADIUS,
    tol: float = _DEFAULT_TOL,
) -> FuzzVerdict:
    """단변수 등식의 정답·근 선택을 수치 무차별 탐색으로 적대 검증(§2).

    단변수 등식만 다룬다 — 연립·부등식·다변수·파싱 불가는 unverifiable(정직). 주장 정답이
    근이 아니거나 선택을 어기는 근이 존재하면 fail(반례 보고), 둘 다 깨끗하면 pass.
    """
    # 파싱은 기존 검증기 재사용(표기 drift 방지). 등식(op="==")만 대상.
    try:
        residual, op = _parse_condition(conditions)
    except (sympy.SympifyError, ValueError, TypeError) as exc:
        return FuzzVerdict("unverifiable", f"파싱 불가: {exc}", 0)
    if op != "==":
        return FuzzVerdict("unverifiable", f"등식이 아님(op={op}) — fuzzer 범위 밖", 0)

    symbols = sorted(residual.free_symbols, key=str)
    if len(symbols) != 1:
        return FuzzVerdict(
            "unverifiable", f"단변수 아님(자유변수 {len(symbols)}개) — fuzzer 범위 밖", 0
        )
    symbol = symbols[0]

    # 주장 정답 수치화 — answer_map에서 이 변수의 값.
    answer_str = answer_map.get(str(symbol))
    if answer_str is None:
        return FuzzVerdict("unverifiable", f"answer_map에 {symbol} 값 없음", 0)
    answer_val = _to_float(answer_str)
    if answer_val is None:
        return FuzzVerdict("unverifiable", f"정답 수치화 불가: {answer_str!r}", 0)

    # P3-79 ⑤(c) — 잔차는 평가 파싱이 자동 약분한 식이라(`x*(x - 2)/(x - 2) = 2` → x - 2) 수치
    # 탐색이 원문에서 정의되지 않는 점(x = 2)을 근으로 찾는다. 주장 정답은 정확값으로 원문 정의역을
    # 먼저 본다(`condition_definedness` — 허용 목록·실행 없음): 정의되지 않음이면 반례(무연근),
    # 판정 불가면 pass 를 단정하지 않는다(반례는 그대로 반례다 — 아래 수치 탐색이 근이 아니라고 하면
    # 정의역과 무관하게 근이 아니다).
    try:
        answer_exact = safe_sympify(answer_str)
    except (sympy.SympifyError, TypeError, ValueError) as exc:
        logger.debug("counterexample_fuzz 정답 정확값 회피: %s", type(exc).__name__)
        return FuzzVerdict("unverifiable", "정답 정확값 파싱 불가", 0)
    claim_state = condition_definedness(conditions, {str(symbol): answer_exact})
    if claim_state == "undefined":
        return FuzzVerdict(
            "fail", "반례 — 주장 정답에서 원문 조건이 정의되지 않음(분모 0 등 — 무연근)", 0
        )

    try:
        func = sympy.lambdify(symbol, residual, "math")
    except Exception as exc:  # noqa: BLE001 — lambdify 실패는 정직 폴백
        return FuzzVerdict("unverifiable", f"수치 함수 변환 불가: {exc}", 0)

    roots, valid = _find_roots(func, radius, trials, tol)
    roots_tuple = tuple(roots)

    if not roots:
        return FuzzVerdict(
            "unverifiable", f"[-{radius},{radius}] 구간에서 근 미발견", valid, roots_tuple
        )

    # ① 주장 정답이 근인가 — 탐색된 근 중 tol 이내가 있어야 한다.
    is_root = any(abs(answer_val - r) <= tol * 100 for r in roots)
    if not is_root:
        return FuzzVerdict(
            "fail",
            f"반례 — 주장 정답 {answer_val:.6g}은 근이 아님. 실제 근: "
            f"{[round(r, 6) for r in roots]}",
            valid,
            roots_tuple,
        )

    # ①-b 수치로 근처럼 보여도 정확값 잔차가 0 이 아니면 근이 아니다(P3-79 — 허수부가 아주
    # 작은 근 `(x - 1)**2 + 10**(-20) = 0` 의 x = 1 을 수치 허용치로 근이라 부르지 않는다.
    # Tier1 과 같은 규칙).
    if _exact_residual_nonzero(residual, symbol, answer_exact):
        return FuzzVerdict(
            "fail",
            f"반례 — 주장 정답 {answer_val:.6g}은 근이 아님(수치 허용치 안이나 정확 잔차 ≠ 0)",
            valid,
            roots_tuple,
        )

    # ② 근 선택이 옳은가 — largest/smallest/unique. 선택 판정에 쓰는 다른 근도 원문에서 정의되는
    # 근만이다(P3-79 — 무연근이 '더 큰 근'·'둘째 근'으로 거짓 반례를 만들지 않게).
    if answer_selection in ("largest", "smallest", "unique"):
        defined_roots = _defined_numeric_roots(
            conditions, residual, symbol, roots, answer_val, tol, (2.0 * radius) / (trials - 1)
        )
        if defined_roots is None:
            return FuzzVerdict(
                "unverifiable",
                "탐색된 근 중 원문 정의역을 확정하지 못한 근이 있음(무연근 가능) — 선택 판정 회피",
                valid,
                roots_tuple,
            )
        roots = defined_roots
    if answer_selection == "largest" and any(r > answer_val + tol * 100 for r in roots):
        bigger = max(roots)
        return FuzzVerdict(
            "fail",
            f"반례 — '큰 근'이라는데 더 큰 근 {bigger:.6g} 존재(주장 {answer_val:.6g})",
            valid,
            roots_tuple,
        )
    if answer_selection == "smallest" and any(r < answer_val - tol * 100 for r in roots):
        smaller = min(roots)
        return FuzzVerdict(
            "fail",
            f"반례 — '작은 근'이라는데 더 작은 근 {smaller:.6g} 존재(주장 {answer_val:.6g})",
            valid,
            roots_tuple,
        )
    if answer_selection == "unique" and len(roots) > 1:
        return FuzzVerdict(
            "fail",
            f"반례 — '유일근'이라는데 서로 다른 근 {len(roots)}개: {[round(r, 6) for r in roots]}",
            valid,
            roots_tuple,
        )

    if claim_state == "unknown":
        return FuzzVerdict(
            "unverifiable",
            "주장 정답에서 원문 정의역을 확정하지 못함(허용 구조 밖) — pass 단정 회피",
            valid,
            roots_tuple,
        )
    return FuzzVerdict("pass", None, valid, roots_tuple)
