"""기호 항등성 판정 — 동치 권위 *단일 primitive* (SymPy·순수·결정론·DB 0).

`math_dsl_risk_register.md` Q10-⑦ "동치 권위는 SymPy 단일". 두 식이 *항등적으로 같은지*를
판정하는 SymPy 관용구(입력 정규화 `to_sympy_source` + `parse_expr`(암묵곱·`^`) + `expand` +
`simplify().is_zero` + 다항/변수집합 보강)를 **한 곳**에 둔다. 과거엔 이 관용구가 `verify_step`
(단계 검증) 안에 인라인돼 있었고, 오개념 카탈로그는 *문자열 매칭*으로 거짓 항등식을 다뤄 "동치
권위가 둘"이 되는 부채였다(math_dsl 감사 §7). 본 모듈이 그 권위를 일원화한다 — `verify_step`
(단계 3상태 판정)도, 오개념 카탈로그 무결성(거짓 항등식이 *실제로* 거짓인지)도 모두 이 primitive를
거친다. 입력 정규화(위첨자·전각/NFKC·비ASCII 연산자·그리스·암묵곱)는 표기(notation) 계층이지
canonical/CAS 정규화가 아니다(Part 4 항목4·`math_dsl_part4_ast_review.md`).

정직성(CLAUDE.md "확실하지 않으면 모른다"): 판정 불가(SymPy `is_zero is None`·비다항·정의역
의존)·파싱 불가는 *절대* identity/not_identity로 위장하지 않고 `undecidable`/`parse_error`로
보수 처리한다. 예: `√(x²)=x`·`log(a+b)=log a+log b`는 정의역·초월이라 가정 없이 단정 불가 →
`undecidable`(카탈로그가 머신 검증 가능 항등식만 `canonical_wrong_form`을 갖게 하는 근거).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

import sympy
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication,
    standard_transformations,
)

from whymath_backend.l3.safe_parse import ensure_within_budget, safe_parse_expr
from whymath_backend.schema.verification_capabilities import EquivalenceOutcome

# 침묵 실패 금지(CLAUDE.md) — 파싱·계산 실패를 parse_error로 접을 때 예외 *타입명*을 남긴다
# (학생 식은 로그에 싣지 않는다 — 미성년 PII).
logger = logging.getLogger("whymath.l3.symbolic_equivalence")

# 유니코드 위첨자 → SymPy 거듭제곱(소스 정규화). caret(^)은 convert_xor가 처리하고,
# 위첨자는 파서가 못 읽으므로(→ SympifyError) 파싱 전에 치환해야 한다. 학생 손글씨·MathLive
# 입력이 `x²`처럼 위첨자를 담는 경우가 흔하다(0~9 전 범위 매핑 — 부분 매핑은 조용한 parse_error).
_SUPERSCRIPT = {
    "⁰": "**0",
    "¹": "**1",
    "²": "**2",
    "³": "**3",
    "⁴": "**4",
    "⁵": "**5",
    "⁶": "**6",
    "⁷": "**7",
    "⁸": "**8",
    "⁹": "**9",
}

# NFKC가 *접지 않는* 비ASCII 수학 연산자 → ASCII. NFKC는 전각(２ｘ→2x·（）→())은 접지만
# 아래 연산자들은 호환 분해가 없어 그대로 남는다(직접 실측·notation_contract §3 후속 해소).
# `−`(U+2212 MINUS SIGN)은 ASCII 하이픈이 아니라 SymPy가 파싱 못 함이 가장 흔한 함정이다.
_OPERATOR_MAP = {
    "−": "-",  # U+2212 MINUS SIGN
    "×": "*",  # U+00D7 MULTIPLICATION SIGN
    "·": "*",  # U+00B7 MIDDLE DOT
    "⋅": "*",  # U+22C5 DOT OPERATOR
    "∗": "*",  # U+2217 ASTERISK OPERATOR
    "÷": "/",  # U+00F7 DIVISION SIGN
}

# 그리스문자 → SymPy 이름(교육 범위 최소 맵·bounded). SymPy는 `π`를 못 읽고 `pi`만 상수로 안다.
# 학생 입력에 흔한 것만(π·θ·삼각/미적 각). 전 그리스 알파벳 확장은 수요 확인 후 후속.
_GREEK_MAP = {
    "π": "pi",
    "θ": "theta",
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "λ": "lambda",
    "μ": "mu",
}

# 파싱 변환 — 암묵적 곱셈(`2x`→2*x·`(x+1)(x-1)`→곱)·`^`→거듭제곱. `pregenerate/validator.py`의
# `_PARSE_TRANSFORMS`와 *동일한 보수 선택*(`implicit_multiplication`만·`_application` 아님)이다 —
# 함수 적용 병치(`sin x`→sin(x))는 제외해 더 보수적(오해석 회피). 두 파싱 진입점이 같은 관례를
# 쓰게 해 "동치 권위 이원화"(risk_register #6) drift를 막는다. 순수 문자 병치(`xy`)는 단일 심볼로
# 남는다(x*y로 *추정하지 않음* — CLAUDE.md "확실하지 않으면 모른다").
_PARSE_TRANSFORMS = standard_transformations + (implicit_multiplication, convert_xor)

# ── LaTeX 계층 정규화(`latex_to_plain`) 상수 ─────────────────────────────────
# 이 블록은 원래 `l5/ocr/verify.py`의 private `_latex_to_sympifiable`에 있었다.
# `notation_contract.md §3`가 "입력 정규화 단일 권위 = to_sympy_source"라고 선언했는데
# 정작 LaTeX 계층은 그 함수 밖
# (L5·OCR 스코프)에 있었고, 학생 제출 경로의 같은 변환은 Dart에 따로 있었다 — 권위가 사실상
# 클라이언트에 있던 상태다(MATH-01 D1). 여기로 옮겨 선언과 코드의 불일치를 코드 쪽에서 닫는다.

# `\frac(a)(b)` → `((a)/(b))`. 중괄호를 괄호로 바꾼 *뒤* 매칭한다. 인자 내 중첩 괄호는 다루지
# 않는다(`[^()]*`) — 1패스라 중첩 분수(`\frac{\frac{1}{2}}{3}`)는 리터럴이 남아 파싱 실패하고
# 상류가 unverifiable로 보수 처리한다(거짓 판정보다 안전). 웹 mathjs는 6패스라 여기서 갈리며,
# 이는 MATH-01이 범위 밖으로 둔 유보 항목이다(math_engine_gap_review.md 부록 A).
_FRAC_RE = re.compile(r"\\frac\s*\(([^()]*)\)\s*\(([^()]*)\)")

# `\sqrt(x)` → `sqrt((x))`. 괄호를 2겹으로 두는 이유는 인자가 식일 때(`\sqrt{x+1}`) 우선순위를
# 보존하기 위함이다(웹은 렌더 전용이라 1겹 — 수치가 같으므로 계약은 수치로 교차검증한다).
_SQRT_RE = re.compile(r"\\sqrt\s*\(([^()]*)\)")

# `\displaylines{...}`·`\begin{env}...\end{env}` 껍데기 — 래퍼만 벗기고 행 구분자 `\\`는 **남긴다**.
# 행 분해(str→list[str])는 `NLP-03`의 축이고 이 모듈은 표기 정규화(str→str)만 한다(MATH-01 ⑥-d).
_DISPLAYLINES_MARKER = r"\displaylines"
_ENVIRONMENT_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\\begin\{[a-zA-Z*]+\}(\{[^{}]*\})?"),
    re.compile(r"\\end\{[a-zA-Z*]+\}"),
)

# 명시 연산자·구획 명령 — 값이 명시 기호(`*`·`/`·빈문자)라 **뒤따르는 공백 1개를 함께 삼켜도**
# 안전하다(`2\times x`→`2*x`). LaTeX 제어어의 공백 삼킴 관례와도 일치한다.
_OPERATOR_COMMANDS: tuple[tuple[str, str], ...] = (
    (r"\left", ""),
    (r"\right", ""),
    (r"\cdot", "*"),
    (r"\times", "*"),
    (r"\div", "/"),
)

# 식별자·관계로 바뀌는 명령 — 뒤 공백을 삼키면 토큰이 병합돼(`\pi r`→`pir`=단일 심볼) 의미가
# 깨지므로 **공백을 보존**한다. 관계 연산자(`\leq` 등)는 이전엔 py가 아예 처리하지 않아 원문
# 백슬래시가 남고 파싱이 실패 → OCR 신뢰도가 잘못 강등됐다(MATH-01 ① 실측 결함).
_SYMBOL_COMMANDS: tuple[tuple[str, str], ...] = (
    (r"\displaystyle", ""),
    (r"\pi", "pi"),
    (r"\leq", "<="),
    (r"\le", "<="),
    (r"\geq", ">="),
    (r"\ge", ">="),
    (r"\neq", "!="),
    (r"\ne", "!="),
)

# 간격 매크로·정렬 기호 — 표기에 의미 없음(제거 또는 공백). 제어어 경계 검사가 필요 없는
# 리터럴 치환이다(뒤가 알파벳일 수 없는 형태).
_SPACING_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\quad", " "),
    (r"\qquad", " "),
    (r"\,", ""),
    (r"\;", ""),
    (r"\:", ""),
    (r"\!", ""),
    ("\\ ", " "),
    ("~", " "),
    ("&", ""),
)

# 다중 공백 접기 — 단일 공백은 보존한다(식별자 병합 방지).
_MULTI_SPACE_RE = re.compile(r" +")

# 제어어 경계 `(?![A-Za-z])` — 부분매치 오염 방지. 경계가 없으면 `\right`가 `\rightarrow`의
# 앞부분에 매칭돼 `a \rightarrow b`가 `a arrow b`로 오염된다(MATH-01 ① 실측 결함이자 정렬 대상).
# 이 경계 덕에 `\le`가 `\left`·`\leq` 안에서 오탐되지 않아 **치환 순서에 의존하지 않는다**.
# Dart `_commandPattern`과 같은 규칙이다.
_COMMAND_BOUNDARY = r"(?![A-Za-z])"
# 연산자는 뒤 공백 1개까지 삼키고(` ?`), 기호·관계는 공백을 보존한다 — 위 두 상수 블록의 주석이
# 그 비대칭의 이유다. 모듈 임포트 시 1회만 컴파일한다.
_OPERATOR_RES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(re.escape(cmd) + _COMMAND_BOUNDARY + " ?"), repl)
    for cmd, repl in _OPERATOR_COMMANDS
)
_SYMBOL_RES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(re.escape(cmd) + _COMMAND_BOUNDARY), repl) for cmd, repl in _SYMBOL_COMMANDS
)


def _extract_balanced_braces(s: str, open_idx: int) -> str | None:
    """[open_idx]의 여는 `{`부터 짝이 맞는 `}`까지 안쪽 내용 — 불균형이면 None(원문 보존).

    Dart `_extractBalancedBraces` 미러. 중첩 중괄호를 세므로 `\\displaylines{a{b}c}`도 올바로
    벗긴다.
    """
    depth = 0
    for i in range(open_idx, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return s[open_idx + 1 : i]
    return None


def latex_to_plain(latex: str) -> str:
    """LaTeX을 평문 수식 표기로 되돌린다 — LaTeX 계층 정규화 단일 권위(순수·결정론·LLM 0).

    `to_sympy_source`의 **상류**다: 이 함수가 LaTeX 매크로를 평문으로 접고, `to_sympy_source`가
    그 결과의 유니코드·전각·그리스를 접는다. 둘을 합친 것이 "입력 정규화 단일 권위"다.

    **절차(Dart `latexToPlainSolution`과 동일 규칙 — `data/notation_contract.json` `latex_cases`가
    두 구현의 산출 일치를 골든으로 동결한다)**:
      1. `strip()`.
      2. `\\displaylines{...}` 래퍼 해체(균형 중괄호 스캔) — 행 구분자 `\\\\`는 **남긴다**
         (NLP-03 축).
      3. `\\begin{env}`·`\\end{env}` 환경 껍데기 제거.
      4. 중괄호 → 괄호 — `x^{2}`→`x^(2)`로 **caret과 그룹을 보존**한다. 캐럿 없는 지수(`x2`)를
         절대 만들지 않는다(수열 표기 `a1`과 모호해 상류가 unverifiable로 떨군다).
      5. `\\frac`·`\\sqrt` 환원(중괄호 치환 후·각 1패스).
      6. 연산자 명령 치환 — 경계 검사 + 뒤 공백 1개 삼킴.
      7. 기호·관계 명령 치환 — 경계 검사만(뒤 공백 보존).
      8. 간격 매크로·정렬 기호 제거 → 다중 공백 접기 → `strip()`.

    caret(`^`)은 건드리지 않는다 — `_PARSE_TRANSFORMS`의 `convert_xor`가 거듭제곱으로 해석한다.
    표기(notation) 변환일 뿐 **수학 의미 판정이 아니다**(동치·정오는 `identity_status` 권위).
    """
    s = latex.strip()
    # 2) `\displaylines{...}` 래퍼 해체 — 래퍼 밖 텍스트는 버린다(래퍼 전체가 곧 풀이).
    idx = s.find(_DISPLAYLINES_MARKER)
    if idx >= 0:
        brace_start = s.find("{", idx)
        if brace_start >= 0:
            inner = _extract_balanced_braces(s, brace_start)
            if inner is not None:
                s = inner
    # 3) 환경 껍데기 제거.
    for env_re in _ENVIRONMENT_RES:
        s = env_re.sub("", s)
    # 4) 중괄호 → 괄호 (caret 보존).
    s = s.replace("{", "(").replace("}", ")")
    # 5) 분수·근호 환원.
    s = _FRAC_RE.sub(r"((\1)/(\2))", s)
    s = _SQRT_RE.sub(r"sqrt((\1))", s)
    # 6) 연산자 명령 — 경계 + 뒤 공백 1개 삼킴.
    for pattern, repl in _OPERATOR_RES:
        s = pattern.sub(repl, s)
    # 7) 기호·관계 명령 — 경계만(공백 보존).
    for pattern, repl in _SYMBOL_RES:
        s = pattern.sub(repl, s)
    # 8) 간격 매크로 제거 → 공백 접기.
    for token, repl in _SPACING_REPLACEMENTS:
        s = s.replace(token, repl)
    return _MULTI_SPACE_RE.sub(" ", s).strip()


def _parse(src: str) -> sympy.Expr:
    """정규화된 소스를 SymPy 식으로 파싱 — 암묵 곱셈·^거듭제곱(`identity_status` 단일 파싱 경로).

    `sympify(convert_xor=True)`를 대체한다 — `2x`·`(x+1)(x-1)` 같은 계수 병치를 학생/LLM이 흔히
    쓰므로 파싱 단계에서 explicit `*`로 접는다(입력 정규화·Parsing 경계이지 canonical/CAS 아님).

    CONST-09: 학생 식이 곧바로 닿는 자리라 안전 진입점(`safe_parse_expr`)을 거친다 — `9^9^9`·
    전개 폭발·허용 밖 이름(`exec` 등)은 여기서 거부되고 호출부가 parse_error로 접는다.
    """
    return safe_parse_expr(src, transformations=_PARSE_TRANSFORMS)


def parse_unevaluated(src: str) -> sympy.Expr:
    """정규화된 소스를 *계산하지 않고* SymPy 식으로 파싱 — 항·괄호의 모양(구조)을 보존한다.

    `_parse`와 **같은 변환 규칙**(`_PARSE_TRANSFORMS` — 암묵 곱셈·`^`)을 쓰되 `evaluate=False`다.
    구조 정합(오개념 거짓형의 Wild 매칭)은 `(3+4)**2`가 49로 접히면 안 되므로 계산 없는 파싱이
    필요한데, 과거엔 그 자리가 변환 규칙이 다른 `safe_sympify(convert_xor=True)`를 직접 불렀다.
    그래서 같은 함수 안에서 거짓 등식 가드(`identity_status`)는 `2x`를 읽는데 구조 정합은 같은
    `2x`를 거부하는 갈림이 있었다(MISC-33 실측 — `(2x+3)²=4x²+9`가 `(2*x+3)²=4*x²+9`와 구조가
    같은데도 미검출). 파서 정의를 이 모듈이 한 곳에서 소유해 그 갈림을 닫는다(동치 권위 일원화).

    알려진 한계(MISC-62): `_PARSE_TRANSFORMS`가 함수 적용 `f(x)`를 곱 `f*x`로 읽는다 — `_parse`·
    `identity_status`와 같은 읽기이며, 여기서 달라지게 하면 도리어 두 진입점이 갈린다.
    """
    return safe_parse_expr(src, transformations=_PARSE_TRANSFORMS, evaluate=False)


def to_sympy_source(raw: str) -> str:
    """원시 수식 문자열을 SymPy 소스로 정규화 — 입력 정규화 단일 권위(SymPy 진입 전 전처리).

    동치 권위(`identity_status`)와 오개념 거짓항등식 탐지(`l4.wrong_form_match`)가 *같은* 정규화를
    쓰도록 한 곳에 둔다 — 과거엔 위첨자 치환이 L4에만 있어 `identity_status`가 `x²`를 parse_error로
    떨구고 L4가 *미리* 변환해 넘겨야 하는 divergence(파싱 관례 갈림)가 있었다(math_dsl 감사 §7).
    이 함수를 거치면 모든 SymPy 진입점이 messy 입력을 동일 canonical로 접는다.

    **정규화 순서(정확성의 핵심)**:
      1. `strip()`.
      2. **유니코드 위첨자 → `**n`** — ⚠️ NFKC보다 *먼저*. NFKC는 `²`(U+00B2)를 `2`로 분해해
         지수 의미를 파괴하므로(직접 실측), 위첨자를 먼저 `**2`로 접어야 한다. 위첨자 뒤 병치
         (`x²y`→`x**2y`)는 파싱 시 암묵곱으로 `x**2*y`로 올바로 결합된다(`**`가 더 강하게 결합).
      3. **비ASCII 연산자**(`−×·⋅∗÷`) → ASCII — NFKC가 안 접는 것만(`_OPERATOR_MAP`).
      4. **그리스문자** → 이름(`_GREEK_MAP`·교육 범위 최소).
      5. **NFKC** — 전각→ASCII 접기(`２ｘ`→`2x`·`（）`→`()`). 임베딩 NFKC 정규화 선례와 일관.

    caret(`^`)은 건드리지 않는다 — `convert_xor`가 거듭제곱으로 해석하므로 이중 변환을 피한다.
    멱등이다(이미 ASCII canonical이면 무변화). *canonical 정규화(교환·약분)·CAS는 이 함수 밖*이다 —
    여기는 표기(notation) 정규화만(implicit `*`·전각·연산자·유니코드), 의미(semantic) 정규화 아님.
    """
    s = raw.strip()
    # 2) 위첨자 → **n (NFKC 이전 — NFKC가 ²를 2로 분해하므로).
    for sup, repl in _SUPERSCRIPT.items():
        s = s.replace(sup, repl)
    # 3) 비ASCII 연산자 → ASCII (NFKC가 안 접는 U+2212 등).
    for src, repl in _OPERATOR_MAP.items():
        s = s.replace(src, repl)
    # 4) 그리스문자 → 이름.
    for src, repl in _GREEK_MAP.items():
        s = s.replace(src, repl)
    # 5) NFKC — 전각→ASCII 접기.
    return unicodedata.normalize("NFKC", s)


# EOS-69: 항등 4상태를 schema 중립 enum과 공유(별칭 — 매핑 금지).
IdentityVerdict = EquivalenceOutcome
"""두 식의 항등성 4상태 — `EquivalenceOutcome`의 별칭. identity/not_identity는 *확정*,
undecidable/parse_error는 보수(둘을 합치지 않는다)."""


@dataclass(frozen=True, slots=True)
class IdentityDetail:
    """`identity_status_detail`의 결과 — 4상태 verdict + undecidable *세부 라벨*(MATH-03).

    `variable_mismatch`는 verdict가 `undecidable`이고 그 원인이 **다항인데 자유변수 집합이
    달라**(치환 맥락 — 예: `a` vs `b+1`·산문이 심볼로 강제) 비항등 *증명*이 봉인된 경우만
    True다. 비다항 미결정(`√(x²)` vs `x`·미지 함수 등)은 변수와 무관하게 미결정이므로 False
    (일반 undecidable). 이 불리언은 판정이 *이미 계산하던* `is_poly`·`same_symbols`를 반환에
    노출한 것뿐이다 — 신규 판정 로직 0(라벨링 전용·verify_step reason_code
    `variable_mismatch`의 발생 지점 단일 진실).
    """

    verdict: IdentityVerdict
    variable_mismatch: bool = False


def identity_status_detail(lhs: str, rhs: str) -> IdentityDetail:
    """`identity_status`의 세부판 — 같은 판정 + undecidable 원인 라벨(판정 로직 단일 본체).

    4상태 판정 기준은 `identity_status` docstring이 정본이다(그쪽이 이 함수에 위임). 추가로
    undecidable일 때 *다항 + 자유변수 집합 불일치*(치환 맥락)면 `variable_mismatch=True`를
    함께 돌린다 — not_identity 조건 `(is_poly and same_symbols)`의 여집합 불리언을 그대로
    노출하는 라벨이지 새 판정이 아니다(MATH-03 ②).
    """
    lhs_src = to_sympy_source(lhs)
    rhs_src = to_sympy_source(rhs)
    if not lhs_src or not rhs_src:
        return IdentityDetail(IdentityVerdict.parse_error)
    try:
        left = _parse(lhs_src)
        right = _parse(rhs_src)
        # 계산 후 재검사 — 두 변을 빼서 합친 식도 예산(차수·전개 항 수) 안이어야 전개·단순화한다.
        diff = ensure_within_budget(left - right)
        expanded = sympy.expand(diff)  # 다항식은 전개가 완전한 정규형(항등식이면 0).
        is_zero = sympy.simplify(diff).is_zero  # 비다항 항등식(삼각 등)까지 보강 판정.
        is_poly = bool(diff.is_polynomial())  # 다항식이면 전개 0-여부로 결정 가능.
        same_symbols = left.free_symbols == right.free_symbols
    except Exception as exc:  # noqa: BLE001 — 파싱·계산 실패는 보수적으로 parse_error(위장 금지)
        logger.debug("identity_status 보수 회피(parse_error): %s", type(exc).__name__)
        return IdentityDetail(IdentityVerdict.parse_error)

    if expanded == 0 or is_zero is True:
        return IdentityDetail(IdentityVerdict.identity)
    if is_zero is False or (is_poly and same_symbols):
        return IdentityDetail(IdentityVerdict.not_identity)
    # undecidable — 다항인데 변수 집합이 다르면(치환 맥락) 그 불일치가 곧 반증 봉인 원인이다
    # (같은 변수였다면 위 not_identity로 *증명*됐을 것). 비다항이면 변수와 무관한 일반 미결정.
    return IdentityDetail(
        IdentityVerdict.undecidable, variable_mismatch=is_poly and not same_symbols
    )


def identity_status(lhs: str, rhs: str) -> IdentityVerdict:
    """`lhs`와 `rhs`가 *항등적으로 같은지* SymPy로 판정한다 — 동치 권위 단일 primitive.

    입력은 `to_sympy_source`로 정규화(위첨자·전각·연산자·그리스·NFKC) 후 `_parse`로 파싱한다
    (암묵 곱셈 `2x`→2*x·`convert_xor`로 `^`=거듭제곱). 자유변수 OK("2(x+1)" ≡ "2x+2"). 차이
    `diff = lhs - rhs`에서:
      - **identity**: `expand(diff) == 0`(다항 항등식이 0으로 환원) 또는 `simplify(diff).is_zero
        is True`(삼각 등 비다항 항등식).
      - **not_identity**: `simplify(diff).is_zero is False`(상수 차 등 0-아님 확정) 또는 `diff`가
        *같은 자유변수*의 다항식인데 전개가 0이 아님 — 0-아닌 다항식은 영함수가 아니므로 항등식
        아님이 *증명*된다(예: `(a+b)²−(a²+b²)=2ab`는 `a=b=1`에서 거짓). 변수 집합이 다르면(치환
        맥락) 거짓 not_identity를 피하려 undecidable로 둔다.
      - **undecidable**: 비다항·simplify 미정(예: `√(x²)` vs `x`는 정의역 의존) — 위장 없이 보수.
      - **parse_error**: 빈 입력·파싱 예외.

    구현은 `identity_status_detail`에 위임한다(판정 본체 단일·MATH-03 라벨 노출과 동일 경로) —
    4상태 반환 계약은 불변이다.
    """
    return identity_status_detail(lhs, rhs).verdict


# `=` 체인 분리 시 대상이 *아닌* 관계·비교 연산자 — 있으면 등식 체인이 아니므로 명시 거부한다
# (조용히 `=`로 쪼개 `<=`·`==`을 오분리하는 것을 막음·정확성 #1).
_NON_EQUALITY_MARKERS = ("==", "!=", "<=", ">=", "<", ">")


def split_relation_chain(src: str) -> list[tuple[str, str]]:
    """등식 체인 `a=b=c` → 인접 쌍 `[('a','b'),('b','c')]`(정규화 전 원문 조각).

    chained equality(`a=b=c`는 "a·b·c가 모두 같다") 입력을 *인접 등식 쌍*으로 분해한다 — 각 쌍은
    `identity_status`(동치 권위 단일)로 판정하면 되므로, 이 함수는 파싱 경계에서 체인을 접는 순수
    유틸이다(엔드포인트 배선은 후속 — `verify_step` 슬라이스 선례). `=`가 없으면 빈 리스트(체인
    아님). 비교·부등 연산(`==`·`<=`·`<` 등)이 섞이면 등식 체인이 아니므로 `ValueError`(조용한
    오분리 금지). 빈 항(`a==`·`=b`)도 `ValueError`.
    """
    if any(marker in src for marker in _NON_EQUALITY_MARKERS):
        raise ValueError(f"등식(=) 체인만 지원 — 비교/부등 연산 포함: {src!r}")
    parts = [p.strip() for p in src.split("=")]
    if len(parts) < 2:
        return []
    if any(not p for p in parts):
        raise ValueError(f"빈 항이 있는 등식 체인: {src!r}")
    return [(parts[i], parts[i + 1]) for i in range(len(parts) - 1)]


def verify_relation_chain(src: str) -> IdentityVerdict:
    """등식 체인 `a=b=c`가 항등적으로 성립하는지 4상태로 판정 — `identity_status` 재사용.

    `split_relation_chain`으로 인접 쌍을 얻어 각 쌍을 `identity_status`(동치 권위 단일·병렬 진실
    금지)로 판정한다. 집계:
      - 한 링크라도 `not_identity`면 → **not_identity**(체인은 그 지점에서 거짓임이 *증명*됨).
      - 모든 링크가 `identity`면 → **identity**.
      - 그 외(undecidable/parse_error 섞임) → **undecidable**(위장 없이 보수).
    `=`가 없거나 빈 체인이면 `parse_error`. 비교/부등 혼입은 `split_relation_chain`이 ValueError.
    """
    pairs = split_relation_chain(src)
    if not pairs:
        return IdentityVerdict.parse_error
    verdicts = [identity_status(lhs, rhs) for lhs, rhs in pairs]
    if any(v is IdentityVerdict.not_identity for v in verdicts):
        return IdentityVerdict.not_identity
    if all(v is IdentityVerdict.identity for v in verdicts):
        return IdentityVerdict.identity
    return IdentityVerdict.undecidable


__all__ = [
    "IdentityDetail",
    "IdentityVerdict",
    "identity_status",
    "identity_status_detail",
    "latex_to_plain",
    "parse_unevaluated",
    "split_relation_chain",
    "to_sympy_source",
    "verify_relation_chain",
]
