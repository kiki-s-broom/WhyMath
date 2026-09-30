"""사전생성 시드 검증 게이트 — Protocol + 최소 기본 구현.

설계 정본: MEMORY.md 2026-05-20 "고난도 검증·시드 품질 = Max-Claude". 슬라이스 1은
*최소 시드 위생*(비어있음·짧음·명백 오류 마커)만 본다. PRM·SymPy·Lean·LLM-judge는
후속 슬라이스(03 환각 방어 파이프라인). 본 게이트는 *시드 품질 위생*이지 학생 노출
경계가 아니다 — 학생 직접 노출 경계는 L4/L5 환각 방어가 책임진다(CLAUDE.md 금기).

검증 통과만 캐시에 적재된다 — 통과 못 한 시드는 *영원히 캐시에 안 들어가서* 런타임
이 그 요청에서 다시 provider를 호출하게 된다(즉, 실패는 안전한 폴백이지 노출 위험이
아니다).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

import sympy
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication,
    standard_transformations,
)

from whymath_backend.l3.pregenerate.models import PregenItem, ValidationSignal

# CONST-09(코딩 헌법 R22-03): 이 검증기는 *LLM 응답*을 파싱한다 — 런타임 생성물은 학생 발화를
# 되풀이할 수 있으므로(`9^9^9 = 1`을 따라 쓰게 하면 그대로 계산된다) 신뢰 입력이 아니다. 또
# `_parse_expr`는 해집합 경로(`solution_set`)를 통해 학생 최종답에도 쓰인다. 거부는 아래 보수
# 회피(통과)로 접힌다.
from whymath_backend.l3.safe_parse import safe_parse_expr, safe_sympify

# 침묵실패 금지(CLAUDE.md) — 이 모듈의 보수 회피는 "통과(None)"로 귀결되므로 sympy 계통
# 장애 시 산술 게이트가 무증상 전부-통과가 될 수 있다(langfuse 사고와 동형 위험). 예외
# *타입명*을 debug로 남겨 계통 장애를 관측 가능하게 한다(메시지 본문은 생성물 식이 섞여 제외).
logger = logging.getLogger("whymath.l3.pregenerate.validator")


@runtime_checkable
class SeedValidator(Protocol):
    """사전생성 응답 검증 경계 — 통과 시 None, 실패 시 `ValidationSignal`(종류·사유·위치).

    `item`은 *선택적 컨텍스트*(`PregenItem | None`)다. 현재 구현은 모두 `response`만
    보지만, 향후 item을 쓰는 검증기(예: 응답이 기대 답과 일치하는지)를 위해 인자를
    남긴다. item이 None이면 *응답 단독 검증* — 빌드타임 시드뿐 아니라 런타임 생성물에도
    같은 검증기를 재사용할 수 있다(`validate_response` 헬퍼 참조).

    반환은 구조화 `ValidationSignal`(slice 59) — `kind`는 검증기가 직접 선언(L4가 산문
    파싱 없이 종류를 읽음)·`reason`은 종전과 같은 사유 문자열(문자열 경계로 `.reason` 흘림).
    """

    def validate(self, item: PregenItem | None, response: str) -> ValidationSignal | None:
        """응답을 검증한다. 통과 = `None`, 실패 = `ValidationSignal`(kind·reason·span)."""
        ...


class BasicSeedValidator:
    """최소 시드 위생 — 비어있음·최소 길이·명백 오류 마커. PRM 등은 후속.

    `min_length`는 *strip 후* 문자열 길이. `error_markers`는 응답에 포함되면 즉시
    탈락시키는 부분 문자열들(예: 모델이 토해낸 명시적 오류 표시). 케이스 무시.
    """

    def __init__(
        self,
        *,
        min_length: int = 1,
        error_markers: tuple[str, ...] = (),
    ) -> None:
        if min_length < 0:
            raise ValueError("min_length는 0 이상이어야 합니다")
        self._min_length = min_length
        # 정규화는 1회 — 비교는 lowercase로
        self._error_markers = tuple(m.lower() for m in error_markers if m)

    def validate(self, item: PregenItem | None, response: str) -> ValidationSignal | None:
        """비어있음·짧음·오류 마커 검사 — 통과면 None, 실패면 `ValidationSignal`.

        위생 실패는 *슬립*이 아니므로 `kind="other"`로 분류한다(기존 `_classify_slip`이
        위생 신호를 "other"로 분류하던 동작 보존 — error_kind 값 계약 무변경).
        """
        stripped = response.strip()
        if not stripped:
            return ValidationSignal(kind="other", reason="empty response")
        if len(stripped) < self._min_length:
            return ValidationSignal(
                kind="other",
                reason=f"response too short (<{self._min_length} chars after strip)",
            )
        if self._error_markers:
            lowered = stripped.lower()
            for marker in self._error_markers:
                if marker in lowered:
                    return ValidationSignal(
                        kind="other", reason=f"error marker present: {marker!r}"
                    )
        return None


# ──────────────────────────────────────────────────────────────────────────
# SymPy 산술 검증 — 03 환각 방어의 *도구 검증*(스키마→SymPy/Lean→PRM→…) 첫 조각.
# 응답에 *명시된 순수 수치 등식*만 검사하고, 거짓임이 *증명*될 때만 탈락시킨다(보수적).
# ──────────────────────────────────────────────────────────────────────────
# 흔한 수학 유니코드 연산자 → ASCII 정규화 (LLM 출력이 ×·÷·−을 자주 씀).
_MATH_OP_NORMALIZE = {
    ord("×"): "*",
    ord("÷"): "/",
    ord("·"): "*",
    ord("−"): "-",  # U+2212 MINUS SIGN (하이픈-마이너스 아님)
}

# 순수 수치 산술식 토큰: 숫자/괄호로 시작·끝, 중간은 숫자·연산자·괄호·스페이스/탭·소수점.
# 변수(x)·함수·산문은 매칭하지 않는다(심볼릭·자연어 false positive 방지).
# 내부 공백은 *스페이스·탭만*(개행 제외) — 등식은 한 줄이며, 줄을 넘어 다음 등식의
# 숫자를 빨아들이지 않게 한다("2=4\n5=11"이 한 토큰으로 병합되는 버그 방지).
# 선두 부호(`[+-]?`)는 *음수 피연산자*("3 - 10 = -7"의 우변 -7)를 잡기 위함 — 이게
# 없으면 음수 결과를 가진 거짓 등식/부등식이 검사에서 누락된다(false negative). 뺄셈
# 연산자와의 혼동("x - 5 = 3"의 "- 5")은 `_is_standalone` 인접 검사가 막는다(좌측이
# alnum·연산자면 *더 큰 식의 일부*로 보고 건너뜀). 부호 뒤 공백 없이 숫자/괄호가
# 와야 토큰이 성립한다(예: "- 5"는 부호로 안 잡힘 — 뺄셈으로 남는다).
_NUM_TOKEN = r"[+-]?(?:[0-9(][0-9 \t+\-*/^().]*[0-9)]|[0-9])"
# 우변을 *룩어헤드*(소비 안 함)로 잡아 연쇄 등식 "a = b = c"의 인접 쌍(a=b, b=c)을
# 모두 검사할 수 있게 한다 — 일반 매칭은 우변을 소비해 다음 쌍을 놓친다(finditer 비중첩).
# group(1)=좌변, group(2)=우변(룩어헤드 내부). match.end(2)로 우변 끝 위치를 얻는다.
_EQUALITY_RE = re.compile(rf"({_NUM_TOKEN})[ \t]*=[ \t]*(?=({_NUM_TOKEN}))")

# 매치 양옆(스페이스·탭 건너 첫 글자)에 이게 인접하면 *더 큰 식의 일부*라 건너뛴다 —
# 예: "x + 1 = 2"에서 "1 = 2"만 떼어 거짓 판정하는 false positive를 막는다.
# 개행(\n)은 *강한 구분자*로 보아 독립으로 인정한다(연속된 등식 줄을 각각 검사).
# 소수점(.)은 제외 — 소수는 정규식 토큰이 통째로 잡으므로 인접 검사가 불필요하고,
# 문장 종지부 "= 4."를 잘못 건너뛰지 않게 한다.
_ADJACENT_MATH = frozenset("+-*/^=()")

# 연쇄 관계 인접 검사용 집합 — *순수 산술 연산자만*(관계 연산자 =·<·>는 제외).
# 인접한 관계 연산자는 *더 큰 식*이 아니라 *연쇄*("a = b = c"·"2 < 5 < 3")이므로 건너뛰지
# 않고 각 인접 쌍을 검사한다. 산술 연산자(+−*/^())는 여전히 차단 — "x + 1 = 2"의
# "1 = 2"는 좌측 `+` 인접이라 그대로 skip(더 큰 산술식의 일부). 등식·부등식 연쇄 공용.
_CHAIN_ADJACENT = frozenset("+-*/^()")


def _is_hangul(ch: str) -> bool:
    """한글 음절·자모인가 — 수식 변수가 아닌 *산문 문자*라 단어 경계로 취급(slice 54).

    한국어 풀이는 "계산하면 2 + 3 = 6 입니다"처럼 수식이 한글에 인접한다. 한글은 결코
    수식 변수(x·a)가 아니므로, 공백을 건너뛴 뒤 한글을 만나면 *더 큰 식의 일부*가 아니라
    독립 수치 식의 경계로 본다(라틴 문자 변수 "x2"는 여전히 경계로 안 봄 — false-positive
    0 유지). 음절(가–힣)·조합 자모·호환 자모를 포함한다.
    """
    return (
        "가" <= ch <= "힣"  # 한글 음절 (가–힣)
        or "ᄀ" <= ch <= "ᇿ"  # 한글 자모 (조합용)
        or "㄰" <= ch <= "㆏"  # 호환 자모 (ㄱ, ㅏ 등)
    )


def _breaks_standalone(ch: str, adjacent: frozenset[str]) -> bool:
    """인접 문자가 매치를 *더 큰 식의 일부*로 만드는가.

    개행·한글은 *산문 경계*라 식을 끊지 않는다(False). 그 외에는 연산자(`adjacent`)이거나
    영숫자(라틴 변수·이어지는 숫자)면 더 큰 식의 일부로 본다. 한글을 경계로 보는 것이
    slice 54의 핵심 — 한국어 산문에 인접한 수치 관계도 검출 대상에 들어온다.
    """
    if ch in "\r\n" or _is_hangul(ch):
        return False
    return ch in adjacent or ch.isalnum()


def _is_standalone(
    text: str, start: int, end: int, adjacent: frozenset[str] = _ADJACENT_MATH
) -> bool:
    """매치 양옆(스페이스·탭 제외 첫 글자)이 연산자·피연산자·변수가 아니면 독립 수치 식.

    스페이스·탭만 건너뛰고 개행·한글은 *산문 경계*로 취급한다 — 연산자 인접("x + 1")은
    잡되, 줄이 다른/한글 산문에 인접한 식은 독립으로 인정한다(slice 54: 한국어 풀이 지원).
    `adjacent`는 "더 큰 식의 일부"로 볼 인접 문자 집합(등식=`_ADJACENT_MATH`·연쇄는 `<>=`
    제외 — 연쇄 관계 조각 허용). 한글 경계 판정은 `_breaks_standalone`에 위임.
    """
    i = start - 1
    while i >= 0 and text[i] in " \t":
        i -= 1
    if i >= 0 and _breaks_standalone(text[i], adjacent):
        return False
    j = end
    while j < len(text) and text[j] in " \t":
        j += 1
    if j < len(text) and _breaks_standalone(text[j], adjacent):
        return False
    return True


def _span_if_preserved(
    normalized: str, response: str, span: tuple[int, int]
) -> tuple[int, int] | None:
    """정규화가 길이를 보존했을 때만 (start, end) span — 아니면 None (slice 59b).

    검증기는 `response.translate(...)` 후 매칭하므로 match 오프셋은 *normalized* 좌표다.
    `_MATH_OP_NORMALIZE`(×÷−·)는 1:1(길이 보존)이라 normalized==원문 좌표지만,
    `_INEQ_NORMALIZE`(≤→"<=")·`_NOTEQ_NORMALIZE`(≠→"!=")는 1→2라 유니코드 부등호가 있으면
    오프셋이 어긋난다. `len(normalized)==len(response)` ⟺ 1→2 치환 0회 ⟺ 오프셋 보존
    (맵은 1→N(N≥1)만·길이 축소 매핑 금지 — 추가 시 이 명제가 깨짐). 보존이 아니면 None을
    돌려 *틀린 하이라이트보다 무하이라이트*를 택한다(span은 비-load-bearing 힌트·검출 불변).
    """
    return span if len(normalized) == len(response) else None


def _equality_is_false(lhs_s: str, rhs_s: str) -> str | None:
    """수치 등식 `lhs=rhs`가 *거짓으로 증명*되면 사유, 아니면(참/미정/파싱불가) None.

    보수적 원칙: 파싱 실패·심볼릭·판정 불가는 *통과*(None)시키고, SymPy가 차이를
    *0이 아니라고 확정*할 때만 실패시킨다 — 자연어·심볼릭 표현을 잘못 탈락시키지 않게.
    """
    try:
        lhs = safe_sympify(lhs_s)
        rhs = safe_sympify(rhs_s)
        # 자유 변수(심볼릭)·비수치는 판정 불가 → 건너뜀(통과).
        if lhs.free_symbols or rhs.free_symbols:
            return None
        is_zero = sympy.simplify(lhs - rhs).is_zero
    except Exception as exc:  # noqa: BLE001 — 파싱·계산 실패는 보수적으로 건너뜀(통과)
        logger.debug("pregenerate.validator 보수 회피(통과): %s", type(exc).__name__)
        return None
    if is_zero is False:  # 차이가 0이 *아님*이 확정 → 등식 거짓
        return f"arithmetic error: '{lhs_s} = {rhs_s}' (sympy: {lhs} != {rhs})"
    return None  # is_zero True(참) 또는 None(미정) → 통과


class SymPyArithmeticValidator:
    """응답에 명시된 순수 수치 등식을 SymPy로 검증 — 거짓이면 탈락 (SeedValidator 충족).

    수학 콘텐츠의 *산술 환각*(예: "3 × 4 = 11")을 빌드타임에 거른다. 보수적이라
    심볼릭 등식(`x+1=2`)·파싱 불가·판정 불가는 통과시키고, *거짓 증명* 시에만 실패.
    검사 수는 `max_checks`로 제한(악의적·초장문 응답의 ReDoS/과부하 방지).
    연쇄 등식("2+3 = 5 = 6")은 룩어헤드로 각 인접 쌍(2+3=5·5=6)을 모두 검사한다.
    """

    def __init__(self, *, max_checks: int = 100) -> None:
        if max_checks < 1:
            raise ValueError("max_checks는 1 이상이어야 합니다")
        self._max_checks = max_checks

    def validate(self, item: PregenItem | None, response: str) -> ValidationSignal | None:
        normalized = response.translate(_MATH_OP_NORMALIZE)
        checked = 0
        for match in _EQUALITY_RE.finditer(normalized):
            if checked >= self._max_checks:
                break
            # 우변은 룩어헤드(group 2)라 미소비 — 독립 검사 span은 좌변 시작~우변 끝.
            # 인접 `=`는 연쇄 등식이므로 허용(`_CHAIN_ADJACENT`), 산술 연산자는 차단.
            if not _is_standalone(normalized, match.start(1), match.end(2), _CHAIN_ADJACENT):
                continue  # 더 큰 식의 일부 → 건너뜀(false positive 방지)
            reason = _equality_is_false(match.group(1).strip(), match.group(2).strip())
            if reason is not None:
                span = _span_if_preserved(normalized, response, (match.start(1), match.end(2)))
                return ValidationSignal(kind="arithmetic", reason=reason, span=span)
            checked += 1
        return None


# ──────────────────────────────────────────────────────────────────────────
# SymPy 부등식 검증 — 산술 등식 검증의 *부등식 판*(거짓 부등식 "5 < 3" 환각 차단).
# 등식과 동일 보수 원칙: 심볼릭·파싱 불가·판정 불가는 통과, *거짓 증명* 시에만 탈락.
# ──────────────────────────────────────────────────────────────────────────
# 유니코드 부등호(≤·≥)를 ASCII로 정규화(LLM 출력이 자주 씀) + 기본 연산자 정규화.
_INEQ_NORMALIZE = {**_MATH_OP_NORMALIZE, ord("≤"): "<=", ord("≥"): ">="}
# 부등식 정규식 — 수치 토큰 사이의 <·>·<=·>=(긴 연산자 우선 매칭). 우변은 *룩어헤드*
# (등식 slice 45와 동형)라 연쇄 부등식 "2 < 5 < 3"의 인접 쌍(2<5, 5<3)을 모두 검사한다.
# group(1)=좌변·group(2)=연산자·group(3)=우변(룩어헤드 내)·`match.end(3)`로 우변 끝.
_INEQUALITY_RE = re.compile(rf"({_NUM_TOKEN})[ \t]*(<=|>=|<|>)[ \t]*(?=({_NUM_TOKEN}))")
# 부등호 → SymPy 관계 생성자(수치 인자면 S.true/S.false로 평가).
_INEQ_FUNC = {"<": sympy.Lt, "<=": sympy.Le, ">": sympy.Gt, ">=": sympy.Ge}


def _inequality_is_false(lhs_s: str, rhs_s: str, op: str) -> str | None:
    """수치 부등식 `lhs op rhs`가 *거짓으로 증명*되면 사유, 아니면 None(참/미정/파싱불가).

    `_equality_is_false`와 동형 보수 원칙: 자유 변수(심볼릭)·파싱 실패·판정 불가는 통과,
    SymPy가 관계를 `S.false`로 *확정*할 때만 실패.
    """
    try:
        lhs = safe_sympify(lhs_s)
        rhs = safe_sympify(rhs_s)
        if lhs.free_symbols or rhs.free_symbols:
            return None  # 심볼릭 → 판정 불가(통과)
        rel = _INEQ_FUNC[op](lhs, rhs)
    except Exception as exc:  # noqa: BLE001 — 파싱·계산 실패는 보수적으로 건너뜀(통과)
        logger.debug("pregenerate.validator 보수 회피(통과): %s", type(exc).__name__)
        return None
    if rel is sympy.false:  # 거짓 확정
        return f"inequality error: '{lhs_s} {op} {rhs_s}' (sympy: false)"
    return None


class SymPyInequalityValidator:
    """응답에 명시된 순수 수치 부등식을 SymPy로 검증 — 거짓이면 탈락 (SeedValidator 충족).

    `SymPyArithmeticValidator`의 부등식 판: "5 < 3"·"7 ≥ 9" 같은 *부등식 환각*을 거른다.
    심볼릭(`x < 2`)·파싱 불가·판정 불가는 통과(보수적)·`max_checks`로 검사 수 상한.
    연쇄 부등식("2 < 5 < 3")은 룩어헤드로 각 인접 쌍(2<5·5<3)을 모두 검사한다.
    """

    def __init__(self, *, max_checks: int = 100) -> None:
        if max_checks < 1:
            raise ValueError("max_checks는 1 이상이어야 합니다")
        self._max_checks = max_checks

    def validate(self, item: PregenItem | None, response: str) -> ValidationSignal | None:
        normalized = response.translate(_INEQ_NORMALIZE)
        checked = 0
        for match in _INEQUALITY_RE.finditer(normalized):
            if checked >= self._max_checks:
                break
            # 우변은 룩어헤드(group 3)라 미소비 — 독립 검사 span은 좌변 시작~우변 끝.
            # 인접 관계 연산자(<>=)는 연쇄이므로 허용(`_CHAIN_ADJACENT`), 산술 연산자는 차단.
            if not _is_standalone(normalized, match.start(1), match.end(3), _CHAIN_ADJACENT):
                continue
            reason = _inequality_is_false(
                match.group(1).strip(), match.group(3).strip(), match.group(2)
            )
            if reason is not None:
                span = _span_if_preserved(normalized, response, (match.start(1), match.end(3)))
                return ValidationSignal(kind="inequality", reason=reason, span=span)
            checked += 1
        return None


# ──────────────────────────────────────────────────────────────────────────
# SymPy 부등(≠) 검증 — 관계 연산자 패밀리 완성(=·<·>·≤·≥ 다음 ≠). 등식 검증의 *역*:
# "a ≠ b"는 a와 b가 *같음*이 증명될 때 거짓("12/4 ≠ 3"·"0.5 ≠ 0.50" 류 환각 차단).
# ──────────────────────────────────────────────────────────────────────────
# 유니코드 ≠ → ASCII "!=" 정규화 + 기본 연산자 정규화(피연산자의 ×·÷ 등).
_NOTEQ_NORMALIZE = {**_MATH_OP_NORMALIZE, ord("≠"): "!="}
# 부등(≠) 정규식 — 수치 토큰 사이의 "!="(정규화 후 단일 표기).
_NOTEQUAL_RE = re.compile(rf"({_NUM_TOKEN})[ \t]*(!=)[ \t]*({_NUM_TOKEN})")
# 인접 판정에 "!"도 포함 — 연쇄 "5 != 3 != 5" 조각·팩토리얼("5!") 인접 오판정 차단.
_NOTEQ_ADJACENT = _ADJACENT_MATH | frozenset("!")


def _not_equal_is_false(lhs_s: str, rhs_s: str) -> str | None:
    """수치 부등 `lhs != rhs`가 *거짓으로 증명*되면 사유, 아니면 None(참/미정/파싱불가).

    `_equality_is_false`의 *역* — 등식은 차이≠0일 때 거짓이지만, 부등(≠)은 두 값이
    *같음*(차이=0)이 확정될 때 거짓이다. 보수 원칙 동일: 심볼릭·파싱 실패·판정 불가는
    통과, SymPy가 차이를 *0이라고 확정*할 때만 실패.
    """
    try:
        lhs = safe_sympify(lhs_s)
        rhs = safe_sympify(rhs_s)
        if lhs.free_symbols or rhs.free_symbols:
            return None  # 심볼릭 → 판정 불가(통과)
        is_zero = sympy.simplify(lhs - rhs).is_zero
    except Exception as exc:  # noqa: BLE001 — 파싱·계산 실패는 보수적으로 건너뜀(통과)
        logger.debug("pregenerate.validator 보수 회피(통과): %s", type(exc).__name__)
        return None
    if is_zero is True:  # 두 값이 같음이 확정 → "a != b" 거짓
        return f"not-equal error: '{lhs_s} != {rhs_s}' (sympy: {lhs} == {rhs})"
    return None  # is_zero False(다름·참) 또는 None(미정) → 통과


class SymPyNotEqualValidator:
    """응답에 명시된 순수 수치 부등(≠)을 SymPy로 검증 — 거짓이면 탈락 (SeedValidator 충족).

    관계 연산자 패밀리(`=`·`<`·`>`·`≤`·`≥`)를 `≠`로 완성: "12/4 ≠ 3"·"8 ≠ 8" 같은
    *거짓 부등 환각*을 거른다. 심볼릭(`x ≠ 2`)·파싱 불가·판정 불가는 통과(보수적)·
    `max_checks`로 검사 수 상한. 팩토리얼("5!")·연쇄("a≠b≠c") 인접은 보수적 skip.
    """

    def __init__(self, *, max_checks: int = 100) -> None:
        if max_checks < 1:
            raise ValueError("max_checks는 1 이상이어야 합니다")
        self._max_checks = max_checks

    def validate(self, item: PregenItem | None, response: str) -> ValidationSignal | None:
        normalized = response.translate(_NOTEQ_NORMALIZE)
        checked = 0
        for match in _NOTEQUAL_RE.finditer(normalized):
            if checked >= self._max_checks:
                break
            if not _is_standalone(normalized, match.start(), match.end(), _NOTEQ_ADJACENT):
                continue
            reason = _not_equal_is_false(match.group(1).strip(), match.group(3).strip())
            if reason is not None:
                span = _span_if_preserved(normalized, response, (match.start(1), match.end(3)))
                return ValidationSignal(kind="not_equal", reason=reason, span=span)
            checked += 1
        return None


# ──────────────────────────────────────────────────────────────────────────
# SymPy 풀이(해) 검증 — 단변수 방정식 + 주장된 해를 *대입*으로 확인 (slice 56).
# "2x + 1 = 7 이므로 x = 5"처럼 *대수* 슬립(방정식의 해를 틀리게 주장)을 잡는다 —
# 산술 검증기(순수 수치)가 못 보던 변수 방정식의 해를 검증한다. false-positive 0 설계:
# 줄 단위 페어링(소문제 변수 재사용 안전)·단변수·단일값(두 근 등 건너뜀)·거짓 증명 시에만 탈락.
# ──────────────────────────────────────────────────────────────────────────
# 변수를 포함하는 식 토큰(정규화 후 ASCII): 숫자·라틴문자·연산자·괄호. 한글 등 산문은 경계.
_EXPR_TOKEN = r"[+-]?(?:[0-9A-Za-z(][0-9A-Za-z \t+\-*/^().]*[0-9A-Za-z)]|[0-9A-Za-z])"
_RELATION_RE = re.compile(rf"({_EXPR_TOKEN})[ \t]*=[ \t]*({_EXPR_TOKEN})")


# 암묵적 곱셈("2x"→2*x)·"^"→거듭제곱 변환 포함 — 학생/LLM이 계수 병치를 자주 씀.
# `implicit_multiplication`은 *계수 병치*만(함수 적용 "sin x"는 제외 — 더 보수적).
_PARSE_TRANSFORMS = standard_transformations + (implicit_multiplication, convert_xor)


def _parse_expr(text: str) -> Any:
    """문자열을 SymPy 식으로 파싱(암묵 곱셈·^거듭제곱) — 실패하면 None(보수적 건너뜀).

    반환은 SymPy 식(untyped → Any) 또는 None. 호출지가 None 검사 후 식 연산을 한다.
    """
    try:
        return safe_parse_expr(text, transformations=_PARSE_TRANSFORMS)
    except Exception as exc:  # noqa: BLE001 — 파싱 실패는 보수적으로 건너뜀(통과)
        logger.debug("pregenerate.validator 보수 회피(통과): %s", type(exc).__name__)
        return None


def _num_equal(a: Any, b: Any) -> bool:
    """두 수치가 같은가 — 타입(정수/유리/실수) 차이를 simplify로 흡수."""
    try:
        return bool(sympy.simplify(a - b).is_zero is True)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover — 수치 비교는 사실상 실패 없음
        logger.debug("pregenerate.validator 보수 회피(통과): %s", type(exc).__name__)
        return False


def _format_solset(solset: set[Any]) -> str:
    """해집합을 정렬된 문자열로 표기(결정론·테스트 안정)."""
    return "{" + ", ".join(str(sol) for sol in sorted(solset, key=str)) + "}"


def _common_solution(var: Any, eqs: list[tuple[Any, Any, str]]) -> set[Any] | None:
    """일관된 방정식들의 *공통 해집합*(유한·실수). 풀이 불가·비다항·비유한·복소면 None.

    각 단변수 방정식을 풀어 해집합을 교집합한다 — 교집합이 비면(상호 모순=소문제·내부
    오류) 호출자가 skip한다. 보수적: is_polynomial 아닌(초월·유리) 식·매개변수/복소 해는
    검증 대상에서 제외(false-positive 0 — 풀 수 없는 건 틀렸다 하지 않는다).
    """
    common: set[Any] | None = None
    for lhs, rhs, _ in eqs:
        # is_polynomial로 비다항을 먼저 거르므로 solve는 사실상 실패하지 않는다 — except는
        # 예기치 못한 SymPy 내부 오류만 흡수하는 방어선(보수적 skip).
        try:
            if not (lhs - rhs).is_polynomial(var):
                return None  # 비다항(초월·유리)은 보수적 skip
            sols = sympy.solve(sympy.Eq(lhs, rhs), var)
        except Exception as exc:  # noqa: BLE001  # pragma: no cover
            logger.debug("pregenerate.validator 보수 회피(통과): %s", type(exc).__name__)
            return None
        numeric: set[Any] = set()
        for sol in sols:
            if not (getattr(sol, "is_number", False) and getattr(sol, "is_real", False)):
                return None  # 비수치·복소 해 → 보수적 skip
            numeric.add(sol)
        common = numeric if common is None else (common & numeric)
    return common


def _check_variable(
    var: Any, eqs: list[tuple[Any, Any, str]], claims: dict[Any, tuple[int, int]] | None
) -> tuple[str, tuple[int, int]] | None:
    """변수 하나의 방정식들·주장 해를 *일관성 기반* 검증 — 틀린 해면 (사유, 해주장 span).

    주장 해가 *정확히 하나*일 때만(다중값=두 근·가설 재사용은 보수적 skip) 검증한다.
    방정식들의 공통 해집합(일관 시 비어있지 않음)에 그 값이 없으면 탈락. 비일관(공통 해
    없음)·비다항·비유한 해는 skip — 다단계 정답 유도(일관)는 검증하고, 소문제 변수 재사용
    (비일관)은 건너뛰어 false-positive 0을 지킨다.

    `claims`는 {해값: 원문 span}(slice 59b — first-wins). 검출 시 (사유, *그 해 주장*의 span)을
    돌려 L5가 틀린 *주장*(예: "x = 5")을 하이라이트하게 한다(방정식은 맞고 주장이 오류 지점).
    """
    if claims is None or len(claims) != 1:
        return None
    (value,) = tuple(claims)
    solset = _common_solution(var, eqs)
    if not solset:  # None(풀이 불가·비다항) 또는 빈 집합(상호 모순) → 보수적 skip
        return None
    if any(_num_equal(value, sol) for sol in solset):
        return None  # 주장 해가 공통 해집합에 있음 → 정해
    reason = (
        f"solution error: '{eqs[0][2]}' has solution {var}={_format_solset(solset)}, "
        f"not claimed {var}={value}"
    )
    return (reason, claims[value])


class SymPySolutionValidator:
    """단변수 방정식의 주장된 해를 *일관성 기반*으로 검증 — 틀리면 탈락 (SeedValidator 충족).

    "2x + 1 = 7 이므로 x = 5"(정해 3) 같은 *대수* 슬립을 잡는다. 전체 텍스트에서 변수별로
    방정식과 해 주장을 모아, 방정식들의 *공통 해집합*(일관 시 비어있지 않음)에 주장 해가
    없으면 탈락한다. 줄을 넘는 *다단계 정답 유도*("2x+1=7\\n2x=6\\nx=3")도 검증하되, 핵심은
    **false-positive 0 보수 설계**:
    - *공통 해집합(일관성) 검사* — 방정식들이 상호 모순(공통 해 없음)이면 *서로 다른 소문제*
      로 보고 건너뜀(같은 변수 재사용의 오발화 차단). 일관된 방정식들만 해를 검증한다.
    - *단변수만* — 관계의 자유변수가 정확히 1개일 때만(다변수 연립은 건너뜀).
    - *단일값만* — 같은 변수가 2개 이상 값으로 주장되면 건너뜀(이차식 두 근·가설 재사용 안전).
    - *다항·유한·실수 해만* — 비다항(초월·유리)·복소·매개변수 해는 풀이 보류(건너뜀).

    `max_checks`는 스캔할 관계 수 상한(초장문 응답 과부하 방지). 정규화(×÷−·)는 산술 검증과 공유.
    """

    def __init__(self, *, max_checks: int = 100) -> None:
        if max_checks < 1:
            raise ValueError("max_checks는 1 이상이어야 합니다")
        self._max_checks = max_checks

    def validate(self, item: PregenItem | None, response: str) -> ValidationSignal | None:
        normalized = response.translate(_MATH_OP_NORMALIZE)
        # 전체 텍스트에서 단변수 관계를 모아 변수별로 (방정식, 해 주장) 분류한다.
        # 줄을 넘어 모으되, 일관성 검사(_check_variable)가 소문제 변수 재사용을 걸러낸다.
        # 해값 → 원문 span (slice 59b — 검출 시 틀린 *주장*을 L5가 하이라이트).
        assignments: dict[Any, dict[Any, tuple[int, int]]] = {}
        equations: dict[Any, list[tuple[Any, Any, str]]] = {}
        checked = 0
        for match in _RELATION_RE.finditer(normalized):
            if checked >= self._max_checks:
                break
            checked += 1
            lhs = _parse_expr(match.group(1).strip())
            rhs = _parse_expr(match.group(2).strip())
            if lhs is None or rhs is None:
                continue
            syms = lhs.free_symbols | rhs.free_symbols
            if len(syms) != 1:
                continue  # 순수 수치(0개)·다변수(2+)는 이 검증기 범위 밖
            (var,) = tuple(syms)
            # 해 주장("x = 5" 또는 "5 = x"): 한쪽이 그 변수 심볼·다른 쪽이 수치.
            # 해값→span 기록(first-wins) — `match.span()`은 관계 전체("x = 5") 위치.
            if lhs == var and not rhs.free_symbols:
                assignments.setdefault(var, {}).setdefault(rhs, match.span())
            elif rhs == var and not lhs.free_symbols:
                assignments.setdefault(var, {}).setdefault(lhs, match.span())
            else:
                eq_str = f"{match.group(1).strip()} = {match.group(2).strip()}"
                equations.setdefault(var, []).append((lhs, rhs, eq_str))
        for var, eqs in equations.items():
            result = _check_variable(var, eqs, assignments.get(var))
            if result is not None:
                reason, claim_span = result
                span = _span_if_preserved(normalized, response, claim_span)
                return ValidationSignal(kind="solution", reason=reason, span=span)
        return None


class ChainValidator:
    """여러 SeedValidator를 순서대로 실행하는 AND 게이트 — 첫 실패 사유 반환.

    예: `ChainValidator([BasicSeedValidator(), SymPyArithmeticValidator()])` —
    위생(비어있음·길이) 통과 후 산술 검증까지 모두 통과해야 캐시에 적재된다.
    빈 체인은 항상 통과(None) — no-op.
    """

    def __init__(self, validators: Sequence[SeedValidator]) -> None:
        self._validators: tuple[SeedValidator, ...] = tuple(validators)

    def validate(self, item: PregenItem | None, response: str) -> ValidationSignal | None:
        for validator in self._validators:
            signal = validator.validate(item, response)
            if signal is not None:
                return signal
        return None


def default_seed_validator(*, min_length: int = 1) -> ChainValidator:
    """기본 사전적재 검증 체인 — 위생 → 산술 → 부등식 → 부등(≠) → 풀이(해) AND 게이트.

    CLI(`__main__`)와 후속 호출자가 *같은 게이트*를 쓰도록 단일 정본으로 묶는다.
    순서: `BasicSeedValidator`(비어있음·길이 위생) → `SymPyArithmeticValidator`
    (거짓 등식 "3×4=11") → `SymPyInequalityValidator`(거짓 부등식 "5<3") →
    `SymPyNotEqualValidator`(거짓 부등 "12/4≠3") → `SymPySolutionValidator`(틀린 해
    "2x+1=7 이므로 x=5"). 다섯 다 보수적이라 심볼릭·파싱 불가는 통과시키고, *거짓 증명*된
    수치 관계(=·<·>·≤·≥·≠)·*틀린 단변수 해*만 탈락시킨다.
    """
    return ChainValidator(
        [
            BasicSeedValidator(min_length=min_length),
            SymPyArithmeticValidator(),
            SymPyInequalityValidator(),
            SymPyNotEqualValidator(),
            SymPySolutionValidator(),
        ]
    )


def arithmetic_validator(*, max_checks: int = 100) -> ChainValidator:
    """수치 관계 + 단변수 해 오류 검출 전용 체인 — 위생 없이 SymPy 검증기만.

    `default_seed_validator`와 달리 `BasicSeedValidator`(비어있음·길이·오류 마커 위생)를
    *빼고* SymPy 검증기만 묶는다. 용도가 *학생 풀이의 계산/대수 슬립*("2+3=6"·"2x+1=7
    이므로 x=5") 검출이라 위생 신호("empty response")는 의미가 없기 때문이다 — 빈 풀이·
    짧은 풀이는 *슬립이 아니다*. 통과=None·*거짓이 증명된 수치 관계/틀린 해*만 사유 문자열
    (보수적: 심볼릭·파싱 불가·판정 불가는 통과). L3→L4 오케스트레이터
    (`l4.solution_coaching.recommend_coaching_for_solution`)가 이 신호 유무를
    `arithmetic_error` bool로 환산해 L4 검산(verify) 코칭을 처방한다(slice 51).
    """
    return ChainValidator(
        [
            SymPyArithmeticValidator(max_checks=max_checks),
            SymPyInequalityValidator(max_checks=max_checks),
            SymPyNotEqualValidator(max_checks=max_checks),
            SymPySolutionValidator(max_checks=max_checks),
        ]
    )


def validate_response(validator: SeedValidator, response: str) -> ValidationSignal | None:
    """`PregenItem` 없이 응답 문자열만 검증 — 런타임 재사용 진입점.

    빌드타임 검증기(`item`을 무시)를 *런타임 생성물*에 그대로 적용할 수 있게 한다.
    `validator.validate(None, response)`의 얇은 래퍼 — 호출지가 빌드타임 전용 타입
    `PregenItem`을 알 필요 없이(레이어 결합 회피) 결정론 검증을 돌린다. 통과=None·
    실패=`ValidationSignal`(kind·reason·span). 문자열 경계로는 `.reason`을 흘린다.
    L3 런타임 shadow 검증(`pipeline.generate` 비차단 관측)의 결선 지점.
    """
    return validator.validate(None, response)


# ──────────────────────────────────────────────────────────────────────────
# 중간 step 등가성 검출 — *shadow 전용 진단 도구* (slice 62). **SeedValidator가 아니다**:
# `validate(item, response)` 시그니처를 구현하지 않으므로 `ChainValidator`·`default_seed_validator`·
# `arithmetic_validator`에 들어갈 수 없다(mypy가 강제·student-facing 체인과 타입상 분리). 이 도구의
# 신호는 학생-경유가 아니며 L4 shadow(비노출 로그·slice 63)만 소비한다. pedagogy-designer 결론:
# 순차유도(A)와 변수재사용(B)은 정보이론적으로 구문 분리 불가 → *위치 지목은 student-facing 금지*,
# 본 도구는 진단 데이터(노이즈 허용)만 낸다(게이팅은 노이즈 저감일 뿐 A/B를 가르지 못함).
# ──────────────────────────────────────────────────────────────────────────
# 순차 유도 명시 마커 — 인접 두 관계가 *등가 변환 단계*임을 시사(없으면 변수재사용 가능성 배제 불가
# → 보수적 비검출). 연결어(한글)·화살표(유니코드/ASCII).
_DERIVATION_CONNECTIVES = ("따라서", "그러므로", "이므로", "즉")
_DERIVATION_ARROWS = ("⟹", "⇒", "→", "=>", "->")


@dataclass(slots=True, frozen=True)
class StepBreak:
    """인접 단계 간 해집합 비보존 의심 — shadow 진단 신호(비노출). 불변(frozen).

    `step_index`는 앞 관계의 0-based 소스 순서. `span`은 *뒤* 관계의 원문 위치(비보존이 드러난
    지점). `solset_before/after`는 두 관계의 해집합(`_format_solset` 문자열·SymPy 객체 미보관·mypy
    `Any` 누출 차단). `var`는 변수명, `marker`는 검출된 순차유도 마커(로그 가독). **student-facing
    아님** — (A)순차유도오류/(B)변수재사용 구문 분리 불가라 학생 노출 금지·L4 shadow만 소비.
    """

    step_index: int
    span: tuple[int, int]
    solset_before: str
    solset_after: str
    var: str
    marker: str


def _derivation_marker(between: str) -> str | None:
    """인접 두 관계 *사이* 텍스트에 순차유도 마커가 있으면 그 마커, 없으면 None.

    NFC 정규화 후 검사 — 조합형(NFD) 한글 연결어("따라서")도 잡는다. 마커가 없으면 두 관계가 순차
    유도인지 변수 재사용(독립 소문제)인지 알 수 없어 *보수적 None*(비검출·shadow 노이즈 저감).
    """
    text = unicodedata.normalize("NFC", between)
    for marker in (*_DERIVATION_CONNECTIVES, *_DERIVATION_ARROWS):
        if marker in text:
            return marker
    return None


def _linear_solution(lhs: Any, rhs: Any, var: Any) -> Any | None:
    """단변수 *선형*(차수 1) 방정식의 유일 실근 — 비선형·비다항·예외면 None(보수적 skip).

    선형으로 한정해 *제곱·인수곱 등 차수 변경 변환*(해집합 보존을 깨는 정당 변환)을 배제한다 —
    제곱한 식은 차수 2라 여기서 None이 되어 단계 비교에서 빠진다(false-positive 노이즈 차단).
    """
    try:
        diff = lhs - rhs
        if not diff.is_polynomial(var) or sympy.degree(diff, var) != 1:
            return None
        sols = sympy.solve(diff, var)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover — 보수적 skip(방어선)
        logger.debug("pregenerate.validator 보수 회피(통과): %s", type(exc).__name__)
        return None
    if len(sols) != 1:  # 선형은 단일근 — 방어
        return None  # pragma: no cover
    sol = sols[0]
    if not (getattr(sol, "is_number", False) and getattr(sol, "is_real", False)):
        return None  # pragma: no cover — 선형 실계수는 실근
    return sol


def detect_step_breaks(response: str, *, max_relations: int = 100) -> list[StepBreak]:
    """다단계 풀이의 *인접* 단계 간 해집합 비보존 검출 — shadow 전용(비노출·SeedValidator 아님).

    인접한 두 단변수 *선형* 관계가 ① 같은 변수 ② 사이에 순차유도 마커(연결어/화살표) ③ 둘 다 차수 1
    이고 ④ 해집합이 다르면 `StepBreak`. 마커 없음·비선형·비다항·다변수·해집합 동일은 보수적 skip.

    **false-positive(노이즈) 한계 명시**: 순차유도 오류(A)와 변수재사용(B)은 마커가 있어도 구문상
    분리 불가하므로 (B)가 검출될 수 있다 — 그래서 이 신호는 student-facing이 아니라 L4 shadow 로그만
    소비한다(slice 63·pedagogy-designer 결론). 게이팅은 노이즈를 줄일 뿐 (A)/(B)를 가르지 못한다.
    """
    normalized = response.translate(_MATH_OP_NORMALIZE)
    # 단변수 관계를 소스 순서로 수집: (var, lhs, rhs, span). 마커는 원문에서 떼되 좌표는 normalized
    # — `_MATH_OP_NORMALIZE`는 1:1 길이보존이라 좌표 동일·화살표는 정규화 대상이 아니다.
    relations: list[tuple[Any, Any, Any, tuple[int, int]]] = []
    for match in _RELATION_RE.finditer(normalized):
        if len(relations) >= max_relations:
            break
        lhs = _parse_expr(match.group(1).strip())
        rhs = _parse_expr(match.group(2).strip())
        if lhs is None or rhs is None:
            continue
        syms = lhs.free_symbols | rhs.free_symbols
        if len(syms) != 1:
            continue  # 순수 수치(0)·다변수(2+)는 단계 등가 비교 밖
        (var,) = tuple(syms)
        relations.append((var, lhs, rhs, match.span()))
    breaks: list[StepBreak] = []
    for i in range(len(relations) - 1):
        var_a, lhs_a, rhs_a, span_a = relations[i]
        var_b, lhs_b, rhs_b, span_b = relations[i + 1]
        if var_a != var_b:
            continue  # 다른 변수 — 인접 단계 아님
        marker = _derivation_marker(response[span_a[1] : span_b[0]])
        if marker is None:
            continue  # 순차유도 마커 없음 → 변수재사용 배제 불가 → 보수적 비검출
        sol_a = _linear_solution(lhs_a, rhs_a, var_a)
        sol_b = _linear_solution(lhs_b, rhs_b, var_b)
        if sol_a is None or sol_b is None:
            continue  # 비선형·비다항(제곱·인수곱 포함) → skip
        if not _num_equal(sol_a, sol_b):
            breaks.append(
                StepBreak(
                    step_index=i,
                    span=span_b,
                    solset_before=_format_solset({sol_a}),
                    solset_after=_format_solset({sol_b}),
                    var=str(var_a),
                    marker=marker,
                )
            )
    return breaks


# ──────────────────────────────────────────────────────────────────────────
# A/B 수렴 후보 휴리스틱 — step break를 *문항 기대정답* 대비 분류 (shadow·slice 65)
# ──────────────────────────────────────────────────────────────────────────
# `detect_step_breaks`는 문항-free(원문만)다. 여기서 L4가 DB로 주입한 *기대정답*을 받아 각
# break의 해집합 변화가 정답에 *수렴/이탈*하는지 본다. (A)순차유도오류/(B)변수재사용은 구문상
# 완전 분리 불가하나(정책 2026-06-06), "정답에서 이탈"은 (A) 후보의 *양성 증거*다. verdict는
# *사실 판정*(L3 결정론)이고 verdict→A/B *후보* 해석은 L4(step_shadow) 소관·여전히 비노출.
StepAnswerVerdict = Literal[
    "diverged_from_answer",  # after≠정답 + before=정답 → 정답서 이탈((A) 후보 양성)
    "reached_answer",  # after=기대정답 → 정답 도달(양성 아님)
    "unrelated",  # before·after 둘 다 정답 아님 → (A)/(B) 미분리(모호)
    "indeterminate",  # 기대정답 없음·정답/해집합 파싱 불가 → 판정 불가(보수적)
]


def _extract_answer_solset(expected_answer: str) -> set[Any] | None:
    """자유텍스트 기대정답 → 수치 해집합. *순수 수치*로 깔끔히 파싱될 때만, 아니면 None(보수적).

    유니코드 연산자 정규화 후 ① "="가 있으면 *마지막* `=` 뒤(우변)만 취하고("x = 3"→"3")
    ② `,`·"또는"·"or"로 분리 ③ 각 조각을 `_parse_expr`해 *전부* 수치(`.is_number`)면 집합
    반환. 하나라도 파싱 실패·비수치면 None — 산문·객관식("③")·빈문자열은 후보에서 빠진다
    (거짓 라벨 0: 못 읽는 정답으로는 후보를 만들지 않는다).
    """
    normalized = expected_answer.translate(_MATH_OP_NORMALIZE).strip()
    if "=" in normalized:
        normalized = normalized.rsplit("=", 1)[1].strip()  # 마지막 `=` 뒤 = 우변(값)
    solset: set[Any] = set()
    for piece in re.split(r",|또는|\bor\b", normalized):
        piece = piece.strip()
        if not piece:
            continue
        value = _parse_expr(piece)
        if value is None or not getattr(value, "is_number", False):
            return None  # 비수치·파싱 실패 → 전체 보수적 None
        solset.add(value)
    return solset or None


def _parse_solset_str(solset_str: str) -> set[Any] | None:
    """`_format_solset` 문자열("{3}"·"{-1, 2}")을 수치 해집합으로 역파싱. 실패·형식오류면 None.

    `_format_solset`이 `str(sol)`로 만든 값이라 단변수 실근은 round-trip한다("3"→3·"1/2"→1/2).
    중괄호를 떼고 `,`로 분리해 각 조각을 `_parse_expr`. 하나라도 실패·비수치(또는 비중괄호)면 None.
    """
    inner = solset_str.strip()
    if not (inner.startswith("{") and inner.endswith("}")):
        return None
    solset: set[Any] = set()
    for piece in inner[1:-1].split(","):
        value = _parse_expr(piece.strip())
        if value is None or not getattr(value, "is_number", False):
            return None
        solset.add(value)
    return solset


def _solset_value_in(value: Any, solset: set[Any]) -> bool:
    """value가 해집합의 어느 원소와 수치적으로 같은가(`_num_equal`·정수/유리/실수 타입차 흡수)."""
    return any(_num_equal(value, member) for member in solset)


def classify_step_break(break_: StepBreak, expected_answer: str | None) -> StepAnswerVerdict:
    """step break의 해집합 변화를 *기대정답* 대비 분류 — A/B 후보의 양성 증거(사실 판정·L3).

    `reached_answer`(after 전부 정답)·`diverged_from_answer`(after≠정답·before 전부 정답)·
    `unrelated`(둘 다 정답 아님)·`indeterminate`(기대정답 None·정답/해집합 파싱 불가). verdict→
    A/B *후보* 해석은 L4(step_shadow) 소관 — 여긴 사실만 낸다. detect_step_breaks가 단일근
    해집합을 만들어 비교는 사실상 단일값이다(다중값 expected도 부분집합 매칭으로 일반 처리).
    """
    expected = _extract_answer_solset(expected_answer) if expected_answer is not None else None
    before = _parse_solset_str(break_.solset_before)
    after = _parse_solset_str(break_.solset_after)
    if expected is None or before is None or after is None:
        return "indeterminate"
    if all(_solset_value_in(v, expected) for v in after):
        return "reached_answer"
    if all(_solset_value_in(v, expected) for v in before):
        return "diverged_from_answer"
    return "unrelated"
