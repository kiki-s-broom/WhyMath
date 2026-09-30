"""오개념 거짓 항등식 *SymPy 탐지* + shadow 관측 — 학생식이 canonical_wrong_form을 인스턴스화했나.

math_dsl 감사 §7(동치 권위 일원화)의 런타임 결선 1차. 기존 탐지(`diagnose`·substring/regex)는
학생이 친 *문자열*을 본다 — `(a+b)`라는 리터럴 신호라 변수명이 다른 기호 인스턴스(`(x+y)²=x²+y²`·
`(p+q)²=p²+q²`)를 놓친다. 본 모듈은 `canonical_wrong_form`(lhs, rhs 템플릿)을 **SymPy Wild 정합**
으로 풀어, 학생 등식이 그 *거짓 규칙을 적용*했는지 표기·변수명 무관하게 판정한다(`identity_status`
단일 동치 권위로 rhs 확인).

정직 스코프(중요):
- *기호* 인스턴스(`(x+y)²=x²+y²`·변수명 변이)와 *수치* 인스턴스(`(3+4)²=3²+4²`) 둘 다 잡는다 —
  학생 lhs를 `evaluate=False`로 파싱해 구조를 보존하므로(손으로 쓴 `regex_signals` 일반화).
- **거짓 등식 가드**(RS2 낙인 차단): 학생 등식이 *우연히 참*(`(3+0)²=3²+0²`)이거나 *올바른 형태*
  (참 항등식)면 거짓 규칙 적용이 아니므로 제외한다(오개념 인스턴스는 실제로 거짓인 등식이어야 함).
- 템플릿이 상수로 평가되는 오개념(`a⁰`→1)은 구조 정합 불가 → 탐지 대상에서 제외(거짓 주장 금지).
- **shadow 전용**: `observe_wrong_form_shadow`는 *비노출·비차단*으로 로그만 남기고 `diagnose`
  반환·verdict를 바꾸지 않는다(학생 노출 게이트 우선순위 #1/#3·노출 전 측정·shadow.py 규약 계승).
- **프라이버시**: 레코드에 학생 풀이 원문을 담지 않는다(추상 오개념 id·개수만·미성년 PII).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import sympy
from pydantic import BaseModel, ConfigDict, Field
from sympy import Wild

from whymath_backend.config import get_settings
from whymath_backend.l3.safe_parse import safe_sympify
from whymath_backend.l3.symbolic_equivalence import (
    IdentityVerdict,
    identity_status,
    to_sympy_source,
)
from whymath_backend.l4.misconception.catalog import CATALOG
from whymath_backend.l4.misconception.diagnose import diagnose

logger = logging.getLogger("whymath.l4.misconception.wrong_form_shadow")  # shadow.py 네이밍 동형
record_logger = logging.getLogger("whymath.l4.misconception.wrong_form_shadow.record")

# 유니코드 위첨자→거듭제곱 정규화는 L3 `to_sympy_source`(동치 권위와 *단일 소스*)를 재사용한다 —
# 과거 이 모듈의 사설 `_to_sympy_source`가 `identity_status`와 갈려 divergence였다(감사 §7). 등식
# 후보 토큰 정규식은 위첨자(²³⁴⁵⁶⁷⁸⁹⁰¹)를 포함해 추출한 뒤 `to_sympy_source`가 파싱 소스로 변환한다.
_EQ_TOKEN = r"[0-9A-Za-z()+\-*/^.⁰¹²³⁴⁵⁶⁷⁸⁹ ]+"
_EQ_RE = re.compile(rf"({_EQ_TOKEN})=({_EQ_TOKEN})")


def extract_equations(text: str) -> list[tuple[str, str]]:
    """학생 풀이에서 `lhs = rhs` 등식 후보를 추출한다(best-effort·prose 무관·파싱은 호출자).

    수식 문자 토큰만 잇는 `(token)=(token)` 정규식이라 한글 서술 사이의 수식만 고른다. 추출은
    관대하게(거짓양성 허용) 하고, 실제 *수학적* 정합·파싱 필터는 `matches_wrong_form`이 맡는다.
    """
    out: list[tuple[str, str]] = []
    for lhs, rhs in _EQ_RE.findall(text):
        left, right = lhs.strip(), rhs.strip()
        if left and right:
            out.append((left, right))
    return out


def matches_wrong_form(student_lhs: str, student_rhs: str, wrong_form: tuple[str, str]) -> bool:
    """학생 등식(student_lhs = student_rhs)이 거짓 규칙 `wrong_form`을 *인스턴스화*했는지.

    절차: ⓪ 학생 등식이 *실제로 거짓*인지 확인(거짓 낙인 방지 가드). ① wrong_form lhs 템플릿의
    자유변수를 Wild로 바꿔 `student_lhs`와 패턴 정합(변수명 무관 바인딩 획득). ② 그 바인딩을 rhs
    템플릿에 적용해 *기대 거짓 rhs*를 만든 뒤, `student_rhs`가 그와 동치인지 `identity_status`(동치
    권위 단일)로 확인. 셋 다 통과해야 True.

    수치 인스턴스((3+4)²=3²+4²)는 `student_lhs`를 `evaluate=False`로 파싱해 *구조를 보존*하므로
    잡는다(기호 인스턴스와 동일 경로·손으로 쓴 regex_signals 일반화). ⓪ 가드: 학생 등식이 *우연히
    참*(예: `(3+0)²=3²+0²`)이거나 *올바른 형태*(참 항등식)면 거짓 규칙 적용이 아니므로 제외한다
    (RS2 거짓 낙인 차단). 템플릿이 상수로 평가(`a⁰`→1)되거나 파싱 불가면 False(거짓 주장 금지).
    """
    wl, wr = wrong_form
    # ⓪ 거짓 등식 가드 — 학생 등식이 확정적 참(항등식)이면 오개념 인스턴스가 아니다(낙인 방지).
    src_lhs, src_rhs = to_sympy_source(student_lhs), to_sympy_source(student_rhs)
    if identity_status(src_lhs, src_rhs) is IdentityVerdict.identity:
        return False
    try:
        # 템플릿(wl·wr)은 오개념 카탈로그의 *코드 상수*라 신뢰 입력이다 — 직접 파싱(CONST-09
        # 허용목록에 사유 등재: tests/infra/test_cas_parse_entrypoint_governance.py).
        lt = sympy.sympify(to_sympy_source(wl), convert_xor=True)
        rt = sympy.sympify(to_sympy_source(wr), convert_xor=True)
        # evaluate=False로 학생 lhs 구조 보존 — 수치((3+4)²)가 값(49)으로 평가되지 않게.
        # 학생 원문이라 안전 진입점을 거친다(CONST-09·R22-03).
        sl = safe_sympify(src_lhs, convert_xor=True, evaluate=False)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가 학생/템플릿은 정합 안 됨(보수)
        logger.debug("matches_wrong_form 파싱 회피: %s", type(exc).__name__)
        return False

    wilds = {sym: Wild(sym.name) for sym in (lt.free_symbols | rt.free_symbols)}
    if not wilds:
        return False  # 템플릿이 상수로 평가됨(구조 소실) → 구조 정합 불가.

    binding = sl.match(lt.xreplace(wilds))
    if not binding:
        return False  # lhs 패턴 미정합(None) 또는 빈 바인딩(degenerate).

    expected_rhs = rt.xreplace(wilds).xreplace(binding)
    if expected_rhs.has(*wilds.values()):
        return False  # rhs에만 있는 변수가 미바인딩 → 정합 불가.

    return identity_status(src_rhs, str(expected_rhs)) is IdentityVerdict.identity


def detect_wrong_forms(text: str) -> list[str]:
    """학생 풀이에서 SymPy 탐지된 오개념 id(`canonical_wrong_form` 보유분만·카탈로그 순서)."""
    equations = extract_equations(text)
    if not equations:
        return []
    hits: list[str] = []
    for m in CATALOG:
        if m.canonical_wrong_form is None:
            continue
        if any(matches_wrong_form(lhs, rhs, m.canonical_wrong_form) for lhs, rhs in equations):
            hits.append(m.id)
    return hits


class WrongFormShadowObservation(BaseModel):
    """SymPy 거짓 항등식 탐지 shadow 관측 1건 — record_logger JSON emit(harvest·비식별).

    SymPy가 탐지한 오개념 id(`sympy_detected_ids`)와 기존 substring/regex 탐지 id
    (`substring_detected_ids`), 그리고 SymPy만 잡은 것(`sympy_only_ids`·순기여=표기 변이 포착)을
    담는다. **학생 풀이 원문은 담지 않는다**(shadow.py 규약·미성년 PII) — 추상 카탈로그 id만.
    """

    model_config = ConfigDict(extra="forbid")

    sympy_detected_ids: list[str]
    substring_detected_ids: list[str]
    sympy_only_ids: list[str]
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def observe_wrong_form_shadow(student_solution: str) -> None:
    """SymPy 거짓 항등식 탐지를 기존 substring/regex와 비교해 *로그로만* 관측(shadow·비차단·비노출).

    `misconception_wrong_form_mode == "off"`(기본)면 즉시 반환(SymPy 미호출·현행 비트동일). shadow면
    `detect_wrong_forms`(SymPy)와 `diagnose`(substring/regex) 결과를 비교해 SymPy-only 순기여를
    로그로 남긴다 — 반환 `None`이라 호출자(coach)가 신호를 받을 변수가 없어 student-facing 누출이
    구조적으로 차단된다(노출·verdict 불변). 어떤 예외도 본류(코칭 반환)를 깨지 않는다(비차단).
    """
    if get_settings().misconception_wrong_form_mode == "off":
        return
    try:
        sympy_ids = detect_wrong_forms(student_solution)
        substr_ids = [match.misconception.id for match in diagnose(student_solution)]
        substr_set = set(substr_ids)
        sympy_only = [mid for mid in sympy_ids if mid not in substr_set]
        logger.info(
            "wrong_form shadow(비노출) — sympy=%s substr=%s sympy_only=%s",
            sympy_ids,
            substr_ids,
            sympy_only,
        )
        record_logger.info(
            WrongFormShadowObservation(
                sympy_detected_ids=sympy_ids,
                substring_detected_ids=substr_ids,
                sympy_only_ids=sympy_only,
            ).model_dump_json()
        )
    except Exception:  # noqa: BLE001 — 관측은 본류를 안 깬다(비차단 방어선·shadow.py 미러)
        return


__all__ = [
    "WrongFormShadowObservation",
    "detect_wrong_forms",
    "extract_equations",
    "matches_wrong_form",
    "observe_wrong_form_shadow",
]
