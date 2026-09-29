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
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import sympy

from whymath_backend.l3.safe_parse import safe_sympify
from whymath_backend.l3.verify_answer import _parse_condition

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

    # ② 근 선택이 옳은가 — largest/smallest/unique.
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

    return FuzzVerdict("pass", None, valid, roots_tuple)
