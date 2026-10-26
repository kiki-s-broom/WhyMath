"""P3-03 미분 문항 은행 — 발문·해설·선지 *문면* 결함 스캐너(순수 함수·결정론·LLM 0).

원래 `tests/backend/l3/equivalent/test_p3_diff_text_defects.py` 안에 있던 판정 함수 3종을 재사용
가능한 위치로 올린 것이다(2026-10-08 · P3-03 감사자 자격 측정 강등전). 강등전 도구
(`harness/p3_audit_qualification`)가 **기계 게이트의 한 구성요소**로 이 스캐너를 시험지 문항에
돌려야 하는데, 하네스가 테스트 모듈을 import하는 것은 배포 경로에 테스트 코드를 끌어들이는 일이라
라이브러리 모듈로 승격했다. 판정 규칙은 **한 글자도 바꾸지 않았다** — 은행 504건 0건 단언·감사
원문 RED 대조군·교정 문장 GREEN 대조군은 그대로 테스트 파일에 남아 이 모듈을 import해 돈다.

바뀐 것은 두 가지뿐이다.
  · SymPy 문자열 파싱을 `l3.safe_parse.safe_sympify`로 바꿨다(CONST-09 단일 진입점 —
    `src/backend` 아래에서는 `sympy.sympify` 직접 호출이 거버넌스 테스트에 걸린다).
    결과는 원 호출과 같다.
  · 테스트용 `assert isinstance(...)` 타입 좁히기를 명시적 분기로 바꿨다(형식이 다른 행은
    해당 부류를 보지 않는다 — 은행 행은 늘 그 형식이라 판정은 같다).

부류
----
  · `josa_and_notation_defects(text)` — 1차 감사 부류: 한국어 조사 받침 불일치('계수은'·
    '108가'·'-6와'), 수식 표기('+ -'·'- -'·계수 1·0 표기·'^1'·'+ +').
  · `undefined_function_defects(question, explanation)` — 발문(또는 해설)이 소개하지 않은
    함수 기호(f·g·h).
  · `round2_defects(row)` — 2차 감사(90건) 부류 + bad_tag 처분 동결 서명(행 단위).

정직 범위: 정규식 *어휘*로 읽는 스캐너다. 같은 결함을 다른 표기로 쓰면(예: 조사 중복 '값을을'·
맞춤법 '구하시요') 놓친다 — 강등전이 그 한계를 측정한다.

7계층: L3 지역. `lang.josa`(받침 판별 — 같은 계층 헬퍼)·`l3.safe_parse`만 import한다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

import sympy

from whymath_backend.l3.safe_parse import safe_sympify
from whymath_backend.lang.josa import has_batchim_hangul, has_batchim_text

__all__ = [
    "josa_and_notation_defects",
    "round2_defects",
    "undefined_function_defects",
]

# 조사 → 받침 필요 여부(True=받침 뒤 형태).
_PARTICLE_NEEDS_BATCHIM = {
    "은": True,
    "을": True,
    "과": True,
    "이": True,
    "는": False,
    "를": False,
    "와": False,
    "가": False,
}
_TOKEN_JOSA = re.compile(
    r"([A-Za-z0-9_'^()\-+/.|]+|[가-힣])(은|는|이|가|을|를|와|과)(?=[\s,.?)]|$)"
)
_COPULA_NEXT = re.compile(r"이(?:다|므|며|고|어|라|면|지|니)")
_NOTATION = {
    "plus_minus": re.compile(r"\+ -|\+-"),
    "minus_minus": re.compile(r"- -|--"),
    "coef_one": re.compile(r"(?<![A-Za-z0-9_.^/])-?1[a-z](?![A-Za-z0-9_(^])"),
    "coef_zero": re.compile(r"(?<![A-Za-z0-9_.^/])0[a-z](?![A-Za-z0-9_(^])"),
    "exp_one_zero": re.compile(r"\^[01](?![0-9])"),
    "plus_plus": re.compile(r"\+ \+|\+\+"),
}
_FN_USE = {n: re.compile(rf"(?<![A-Za-z0-9_']){n}\s*[(']") for n in "fgh"}


def josa_and_notation_defects(text: str) -> list[tuple[str, str]]:
    """문장 1개의 조사·표기 결함 (부류, 문맥) 목록."""
    out: list[tuple[str, str]] = []
    for m in _TOKEN_JOSA.finditer(text):
        token, particle = m.group(1), m.group(2)
        if re.fullmatch(r"[가-힣]", token):
            # 한글 낱말 뒤는 명사형 오용만 본다(받침 無 뒤 은·을·과 / 받침 有 뒤 를·와).
            # '그은'(긋다 활용)은 조사가 아니다.
            batchim = has_batchim_hangul(token)
            wrong = (particle in ("은", "을", "과") and not batchim) or (
                particle in ("를", "와") and batchim
            )
            if wrong and m.group(0) != "그은":
                out.append(("josa_hangul", text[max(0, m.start() - 6) : m.end() + 6]))
            continue
        batchim_or_none = has_batchim_text(token)
        if batchim_or_none is None:
            continue
        if particle == "이" and _COPULA_NEXT.match(text[m.start(2) :]):
            continue
        if _PARTICLE_NEEDS_BATCHIM[particle] != batchim_or_none:
            out.append(("josa_token", text[max(0, m.start() - 8) : m.end() + 8]))
    for name, rx in _NOTATION.items():
        for m in rx.finditer(text):
            out.append((name, text[max(0, m.start() - 10) : m.end() + 10]))
    return out


def _defines(question: str, name: str) -> bool:
    return (
        re.search(
            rf"(?<![A-Za-z0-9_']){name}\((?:x|t)\)|(?<![가-힣])함수 {name}(?![A-Za-z0-9_'(])",
            question,
        )
        is not None
    )


# 해설이 함수 기호를 *쓰기 전에* 정의하는 문장 — 곡선 식에 이름 붙이기
# ('곡선의 식을 y = f(x)라 하자', 구판 '…로 놓으면')와 명시 정의
# ('f(x) = x^3 - 3x + 2라 하자'·'h(x) = f(x) - g(x) = …라 하자').
_EXPL_DEF = {
    n: re.compile(
        rf"y = {n}\(x\)(?:로 놓으면|라 하자)|(?<![A-Za-z0-9_']){n}\((?:x|t)\) = [^.]*?라 하자"
    )
    for n in "fgh"
}


def _explanation_defines(explanation: str, name: str) -> bool:
    """해설이 `name`을 정의하고, 그 정의가 첫 사용보다 앞서는가(정의 전 사용은 미정의다)."""
    match = _EXPL_DEF[name].search(explanation)
    if match is None:
        return False
    first_use = _FN_USE[name].search(explanation)
    return first_use is None or first_use.start() >= match.start()


def undefined_function_defects(question: str, explanation: str) -> list[str]:
    """발문이 소개하지 않은 함수 기호가 발문(또는 해설)에 쓰이면 기호 목록."""
    bad: list[str] = []
    for name in "fgh":
        if _defines(question, name):
            continue
        if _FN_USE[name].search(question):
            bad.append(f"{name}:발문")
        elif _FN_USE[name].search(explanation) and not _explanation_defines(explanation, name):
            bad.append(f"{name}:해설")
    return bad


# ──────────────────────────────────────────────────────────────────────────
# 2차 감사(2026-10 · 90건) 결함 부류 — 문항(행) 단위 스캐너
# ──────────────────────────────────────────────────────────────────────────
#: 발문·해설 공통 표기 부류.
_R2_TEXT = {
    # 프라임 기호 바로 뒤 조사 — 'f'는'·'g'를'은 독법(프라임/대시)에 따라 조사가 갈린다.
    "prime_josa": re.compile(r"'(은|는|이|가|을|를|와|과|으로|로|라)(?![a-zA-Z0-9(])"),
    # 양수를 괄호로 감싼 연산 '- (3)' — 음수만 괄호('2 - (-3)')가 규약이다.
    "paren_nonneg": re.compile(r"[-+] \(\d+(?:/\d+)?\)"),
    # 문면의 별표 곱셈(기계 표기 노출).
    "star_in_text": re.compile(r"\*"),
    # 지수 뒤에 변수가 붙어 '(x + 3)^(2x)'로 읽히는 표기 '2(x + 3)^2x'.
    "exp_then_var": re.compile(r"\^\d+[a-z](?![a-z(^])"),
    # '…로 놓으면 …하면' — 연결어미 '-면' 중첩(1차 교정 머리말의 부작용).
    "double_myeon": re.compile(r"놓으면 [^.]*?하면 "),
}
#: 발문 전용 부류.
_R2_QUESTION = {
    "curve_derivative": re.compile(r"곡선 y = [^,.]*?의 도함수"),
    "curve_graph_dup": re.compile(r"곡선 y = [^,]*?의 그래프"),
    "const_curve_named_curve": re.compile(r"곡선 y = -?\d+ 위"),
    "ab_awkward": re.compile(r"\(a, f\(a\)\), \(b, f\(b\)\)에서 a ="),
    "rolle_circular": re.compile(
        r"f\(-?\d+\) = f\(-?\d+\)일 때, 닫힌구간 .*롤의 정리의 조건이 성립하도록"
    ),
    "ambiguous_count": re.compile(r"평균변화율과 같은 미분계수를 갖는 서로 다른 실수 x의 개수"),
}
#: 해설 전용 부류.
_R2_EXPLANATION = {
    "formula_leak_expl": re.compile(r"앞에 오는 계수가 지수와 같으므로"),
    "deriv_root_misstated": re.compile(r"도함수 [^.]*?에서 [^ .]+ 아닌 근은"),
}
# 토큰에 '^'를 포함한다 — 'x^2'는 '엑스 제곱'(받침 있음)으로 읽힌다(`lang.josa.has_batchim_text`·
# 같은 파일 `_TOKEN_JOSA`와 같은 토큰 경계). '^'를 빼면 '9x^2이라'의 마지막 '2'만 읽어 정답 표기를
# 결함으로, '9x^2라'를 정상으로 뒤집어 판정한다(P3-03 우회로 재설계에서 실측 — 대조군 아래 추가).
_IRA = re.compile(r"([0-9A-Za-z)'^]+)(이라|라) (?=할|하자|하면|놓|두)")
_NEG_TIME = re.compile(r"t = -\d")
_CONCLUSION_SIG = re.compile(
    r"되도록 (?P<v>[a-z])를 정하면|만족하도록 (?P<v2>[a-z])를 정하면|"
    r"이 조건에서 (?P<v3>[a-z])의 값은|"
    r"두 조건에서 (?P<v4>[a-z])는|대입해 풀면|이를 풀면|이를 (?P<v5>[a-z])에 대해 풀면"
)
_LETTER_USE = (
    r"(?:(?<![A-Za-z])\d*{L}(?:x|t)(?![A-Za-z])|(?<![A-Za-z])\d*{L}(?:x|t)\^|"
    r"[-+] {L}(?![A-Za-z(']))"
)
_DECL = (
    r"상수 {L}(?![A-Za-z])|(?<![A-Za-z]){L}(?:는|은) 상수|"
    r"(?<![A-Za-z]){L}(?:, [a-z])+(?:는|은) 상수|"
    r"(?<![A-Za-z])[a-z](?:, [a-z])*, {L}(?:는|은) 상수|"
    r"(?<![A-Za-z]){L}(?:는|은) (?:\d+ 이상의 )?자연수|양수 {L}(?![A-Za-z])|실수 {L}(?![A-Za-z])|"
    # 정의 구문 — '접선의 방정식을 y = mx + n이라 할 때'의 m·n은 그 구문이 정의한다.
    r"y = [^,.]*?(?<![A-Za-z]){L}[^,.]*?라 할 때"
)
#: bad_tag 처분 동결 서명 — 미분 행위 없이 선수 계산(대입·근과 계수·이차식)만으로 풀리던 템플릿의
#: 발문 서명이다. 처분(삭제·재설계)된 뒤 같은 서명이 다시 나오면 RED다.
_BADTAG = {
    "06_avg_rate_only": ("[12미적Ⅰ-02-06]", r"에서의 평균변화율을 구하시오"),
    "06_chord_slope_only": ("[12미적Ⅰ-02-06]", r"지나는 직선의 기울기를 구하시오"),
    "06_value_difference": ("[12미적Ⅰ-02-06]", r"평균값 정리의 양변을 비교하기"),
    "06_slope_plus_k_count": ("[12미적Ⅰ-02-06]", r"직선 AB의 기울기보다 \d+만큼"),
    "06_two_intervals": (
        "[12미적Ⅰ-02-06]",
        r"평균변화율과 구간 \[.*\]에서의 평균변화율이 같을",
    ),
    "06_tangent_to_given_line": ("[12미적Ⅰ-02-06]", r"접선이 직선 y = [^ ]+x"),
    "06_vieta_sum": ("[12미적Ⅰ-02-06]", r"구간 밖의 값도 포함\)의 합|c \+ e의 값"),
    "06_larger_candidate": ("[12미적Ⅰ-02-06]", r"이 중 큰 값을 구하시오"),
    "06_all_real_count": ("[12미적Ⅰ-02-06]", r"구간은 제한하지 않는다|서로 다른 실수 x의 개수"),
    # 02-08 — 위치·종류를 발문이 모두 주는 대입형(고정 하나 + 종류 명시).
    "08_pinned_kind_value": (
        "[12미적Ⅰ-02-08]",
        r"x = -?\d+에서 극(솟|댓)?값을 갖는다\. (이때의|그)|"
        r"의 x = -?\d+에서의 극(솟|댓)값을 구하시오",
    ),
    # 상수항 k — f'(r) = 0이 k와 무관해 대입 한 번(감사: 순환 해설). 계수 a·b형은 02-08 행위라 제외.
    "08_pinned_kind_param": (
        "[12미적Ⅰ-02-08]",
        r"\+ k[가이] x = -?\d+에서 극(솟|댓)값 -?\d+[을를] 가질 때",
    ),
    "09_quadratic_only": (
        "[12미적Ⅰ-02-09]",
        r"이차부등식|이차방정식 .*양의 실근|포물선 y = .*두 교점의 x좌표의 합",
    ),
    "09_fprime_roots_only": (
        "[12미적Ⅰ-02-09]",
        r"f'\(x\) = 0을 만족시키는 두 실수|f'\(x\) = 0의 두 실근 중|방정식 f'\(x\) = 0의 서로 다른",
    ),
    "09_vieta": ("[12미적Ⅰ-02-09]", r"근의 (합|곱)을 구하시오|교점의 x좌표의 합"),
    "09_root_selection_algebra": (
        "[12미적Ⅰ-02-09]",
        r"실근 중 가장 (큰|작은) 것|x좌표 중 가장 작은 값|x좌표가 가장 큰 점의 x좌표|"
        r"오직 하나이다\. 그 값|0 이상의 실수일 때, 방정식",
    ),
    "09_thrown_object_cubic": ("[12미적Ⅰ-02-09]", r"던진"),
}


def _ira_defects(text: str) -> list[str]:
    """'(이)라' 서술격 — 받침 있는 값 뒤 '라'·받침 없는 값 뒤 '이라'('3라 할 때'·'2이라 하자')."""
    out = []
    for m in _IRA.finditer(text):
        batchim = has_batchim_text(m.group(1))
        if batchim is None:
            continue
        if (m.group(2) == "라" and batchim) or (m.group(2) == "이라" and not batchim):
            out.append(text[max(0, m.start() - 8) : m.end() + 6])
    return out


def _format_ok(answer: str, fmt: str) -> bool:
    """은행 단일 규칙 — 양의 정수 → 자연수, 정수 아닌 유리수 → 분수, 0·음의 정수·무리수 → 실수."""
    value = sympy.Rational(answer) if re.fullmatch(r"-?\d+(/\d+)?", answer) else None
    if value is None:
        return fmt == "실수"
    if fmt == "자연수":
        return bool(value.is_integer and value > 0)
    if fmt == "분수":
        return not value.is_integer
    return fmt == "실수" and bool(value.is_integer and value <= 0)


def _first_poly(row: Mapping[str, object]) -> sympy.Expr | None:
    verify = row.get("verify")
    if not isinstance(verify, Mapping):
        return None
    cond = verify.get("conditions")
    if isinstance(cond, list) and cond:
        first = str(cond[0])
    elif isinstance(cond, str):
        first = cond
    else:
        return None
    if "Derivative" in first or " = " not in first:
        return None
    lhs, rhs = first.split(" = ", 1)
    try:
        return sympy.expand(safe_sympify(lhs) - safe_sympify(rhs))
    except (sympy.SympifyError, TypeError, SyntaxError):
        return None


def _single_symbol_poly(expr: sympy.Expr) -> sympy.Poly | None:
    syms = sorted(expr.free_symbols, key=str)
    if len(syms) != 1:
        return None
    return sympy.Poly(expr, syms[0])


def _has_double_root(expr: sympy.Expr) -> bool:
    poly = _single_symbol_poly(expr)
    return poly is not None and poly.degree() > 0 and sympy.degree(sympy.gcd(poly, poly.diff())) > 0


def _has_irreducible_quadratic(expr: sympy.Expr) -> bool:
    poly = _single_symbol_poly(expr)
    if poly is None:
        return False
    symbol = poly.gens[0]
    _, factors = sympy.factor_list(expr)
    return any(sympy.degree(f, symbol) >= 2 and not sympy.real_roots(f) for f, _ in factors)


def _equation_with_unknown(explanation: str, var: str) -> bool:
    """해설에 미지수가 *다른 항과 함께* 든 등식이 있는가(결론 'a = 3'만 있는 것은 아니다)."""
    for seg in re.split(r"[가-힣]+", explanation):
        if "=" not in seg or not re.search(rf"(?<![A-Za-z]){var}(?![A-Za-z])", seg):
            continue
        if re.fullmatch(rf"{var} = -?\d+(/\d+)?", seg.strip(" ,.()")):
            continue
        return True
    return False


def round2_defects(row: Mapping[str, object]) -> list[str]:
    """2차 감사 결함 부류 — 행 1개가 걸리는 부류 이름 목록(빈 리스트면 통과)."""
    q, e = str(row.get("question_text") or ""), str(row.get("answer_explanation") or "")
    raw_verify = row.get("verify")
    verify: Mapping[str, object] = raw_verify if isinstance(raw_verify, Mapping) else {}
    raw_choices = row.get("choices")
    choices = [str(c) for c in raw_choices] if isinstance(raw_choices, list) else []
    texts = [q, e, *choices]
    found: set[str] = set()
    for text in texts:
        if _R2_TEXT["prime_josa"].search(text):
            found.add("prime_josa")
        if _ira_defects(text):
            found.add("ira_josa")
    for text in (q, e):
        for name, rx in _R2_TEXT.items():
            if name != "prime_josa" and rx.search(text):
                found.add(name)
    found |= {name for name, rx in _R2_QUESTION.items() if rx.search(q)}
    found |= {name for name, rx in _R2_EXPLANATION.items() if rx.search(e)}
    if not _format_ok(str(row.get("answer") or ""), str(row.get("answer_format") or "")):
        found.add("format_mismatch")
    if "시각 t" in q and _NEG_TIME.search(q):
        found.add("negative_time")
    car = re.search(r"이동 거리가 s\(t\) = (.+?) \(km\)", q)
    if car:
        expr = safe_sympify(re.sub(r"(\d)t", r"\1*t", car.group(1)).replace("^", "**"))
        if expr.subs(sympy.Symbol("t"), 0) != 0:
            found.add("car_distance_nonzero_at_start")
    if "두 점 P, Q" in q and q.count("x = ") >= 2:
        found.add("two_points_same_symbol")
    if re.search(r"점 P", q) and re.search(r"상수 p(?![A-Za-z])", q):
        found.add("p_and_point_P")
    poly = _first_poly(row)
    if ("중근은 중복하여" in q or "중근을 중복하여" in e) and poly is not None:
        if not _has_double_root(poly):
            found.add("multiplicity_note_without_double_root")
    raw_amap = verify.get("answer_map")
    amap: Mapping[str, object] = raw_amap if isinstance(raw_amap, Mapping) else {}
    unknowns = [k for k in amap if k not in ("x", "y")] or list(amap)
    if _CONCLUSION_SIG.search(e) and unknowns:
        if not any(_equation_with_unknown(e, u) for u in unknowns):
            found.add("explanation_conclusion_only")
    if verify.get("answer_kind") == "real_root_count":
        factored = re.search(r"\)\(|\)\^\d|\d\((?:x|t) [-+]|(?:x|t)\((?:x|t) [-+]", e)
        if not factored and not re.search(r"'\(|극댓값|극솟값", e):
            found.add("count_explanation_conclusion_only")
        raw_tags = row.get("tags")
        tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else []
        if "p3-slot:misconception_trigger" in tags and poly is not None:
            if _has_double_root(poly) and not re.search(r"중근|접", e):
                found.add("mc_trap_double_root_unexplained")
            if _has_irreducible_quadratic(poly) and "실근이 없" not in e and "양수" not in e:
                found.add("mc_trap_irreducible_unexplained")
    for letter in "abkpmnqrs":
        if re.search(_LETTER_USE.format(L=letter), q) and not re.search(_DECL.format(L=letter), q):
            found.add("undeclared_constant")
            break
    raw_codes = row.get("achievement_standard_codes")
    codes = [str(c) for c in raw_codes] if isinstance(raw_codes, list) else []
    for name, (code, pattern) in _BADTAG.items():
        if code in codes and re.search(pattern, q):
            found.add(f"badtag:{name}")
    return sorted(found)
