#!/usr/bin/env python3
"""QUAL-12 슬라이스 B — 발문(question_text) 자연어 해석 vs 저장 answer 독립 재계산 대조.

원칙
- 생성기(whymath_backend.*) 모듈을 import/호출하지 않는다. 오직 data/corpus/*/problems.jsonl 의
  question_text(+answer_explanation 일관성 점검용)만 파싱한다. 독립 계산은 SymPy/Fraction.
- 전 행 대조(샘플링 없음). 파싱 실패·독립 계산 불가 행은 '미검증'으로 따로 센다(통과 아님).
- 스캔 0건 코퍼스는 실패 표기.
- 판정 분류 (행 단위):
    OK        독립 계산 == 저장 answer
    MISMATCH  독립 계산 != 저장 answer (표준 해석 기준)
    AMBIG     해석이 둘로 갈릴 수 있는 어휘 — 해석별 일치 여부를 각각 기록
    UNVER     파싱 실패 / 독립 계산 불가(예: 발문이 성립하지 않아 정답이 정의되지 않음은 ILLPOSED 로 분리)
    ILLPOSED  발문 자체가 표준 해석으로 정답을 정의하지 못함(예: 실근 없음, 해집합 공집합)
- 발문↔answer_explanation 일관성은 별도 열(EXPL_OK / EXPL_BAD / EXPL_UNPARSED)로 센다.

사용: python3 audit_B_script.py [--corpus-root DIR] [--json OUT.json] [--examples N]
종료 코드: 불일치/발문 성립 불가/설명 불일치/스캔 0건 중 하나라도 있으면 1, 모두 0이면 0.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

TRANSFORMS = standard_transformations + (implicit_multiplication_application, convert_xor)
X = sp.Symbol("x")

CORPORA = [
    "problem_bank_polynomial_arithmetic_v0",
    "problem_bank_polynomial_factoring_v0",
    "problem_bank_linear_inequality_system_v0",
    "problem_bank_quad_ineq_v0",
    "problem_bank_middle_function_v0",
    "problem_bank_radian_conversion_v0",
    "problem_bank_complex_number_arithmetic_v0",
    "problem_bank_matrix_ops_v0",
]

# ---------------------------------------------------------------- 공통 유틸

def sym(s: str):
    """수식 문자열 → SymPy (암묵 곱셈·^ 허용). 실패 시 예외."""
    return parse_expr(s.strip(), transformations=TRANSFORMS, local_dict={"x": X, "pi": sp.pi}, evaluate=True)


def to_q(s: str):
    """저장 answer 문자열 → 유리수/식. 실패 시 None."""
    try:
        v = sp.nsimplify(parse_expr(s.strip(), transformations=TRANSFORMS, local_dict={"pi": sp.pi}), rational=True)
        return v
    except Exception:  # noqa: BLE001 — 감사 스크립트: 파싱 불가는 UNVER 로 계상
        return None


def poly_of(s: str):
    """'-3x + 3' 형태 다항식 → sp.Poly(x). 실패 시 예외."""
    return sp.Poly(sym(s), X)


# 템플릿(발문 유형) 정규화: 리터럴(다항식·복소수·행렬·부등식 좌변)을 토큰으로, 숫자는 #
def template(q: str) -> str:
    t = q
    t = re.sub(r"\[\[[^\]]*\],\s*\[[^\]]*\]\]", "<MAT>", t)
    t = re.sub(r"\b([PQf])\(x\) = (.+?)(?=,\s*Q\(x\)|에 대하여|일 때|$)", r"\1(x) = <POLY>", t)
    t = re.sub(r"\bz(\d) = (.+?)(?=,\s*z\d|에 대하여)", r"z\1 = <CX>", t)
    t = re.sub(r"(?<=이차식 )(.+?)(?=를 인수분해)", "<QUADRATIC>", t)
    t = re.sub(r"(?<=이차부등식 )(.+?)(?=\s[<>]\s)", "<QUAD>", t)
    # 연립부등식 좌변
    if "연립부등식" in t:
        head, _, tail = t.partition(": ")
        tail = re.sub(r"[^,]+?(?=\s[<>]\s)", "<LIN>", tail)
        t = head + ": " + tail
    t = re.sub(r"-?\d+", "#", t)
    t = re.sub(r"(?<=\()\#(?=\))", "#", t)
    t = re.sub(r"\s+", " ", t)
    return t


VOCAB = {
    "부등호방향(>,<)": r"(?<![-=\w])[<>](?![-=])",
    "이상/이하/초과/미만": r"이상|이하|초과|미만",
    "더큰/더작은(대소 선택)": r"더 큰|더 작은",
    "경계(값)/해의 범위": r"경계|범위",
    "정수해 개수/개수": r"정수|개수",
    "합/차/곱/전개(연산어)": r"의 합|의 차|의 곱|곱한|전개|P\(x\) [+\-*] Q\(x\)|z\d [+\-*] z\d|A [+\-] B|AB",
    "계수/상수(항)": r"계수|상수",
    "실수부/허수부": r"실수부|허수부",
    "행/열(성분 위치)": r"\d행 \d열",
    "도(°)/호도법/라디안/일반각": r"°|호도법|라디안|일반각|도\(°\)",
    "f(a)의 값(대입)": r"f\(-?\d+\)",
    "인수/인수분해 꼴 (x+p)(x+q)": r"인수",
    "포함/제외": r"포함|제외",
    "교점/정의역/치역": r"교점|정의역|치역",
}


# ---------------------------------------------------------------- 코퍼스별 독립 계산기
# 반환: (verdict, indep_value_str, tags, expl_verdict)
#   verdict ∈ OK/MISMATCH/AMBIG/UNVER/ILLPOSED, tags: 문자열 리스트

def num(s) -> Fraction | None:
    try:
        return Fraction(str(s).strip())
    except Exception:  # noqa: BLE001
        return None


def same(a: Fraction | None, b) -> bool:
    return a is not None and Fraction(int(sp.numer(b)), int(sp.denom(b))) == a if isinstance(b, sp.Rational) else False


def f2s(v) -> str:
    return str(v)


# ---- 1. polynomial_arithmetic
RE_PA = re.compile(
    r"P\(x\) = (?P<p>.+?), Q\(x\) = (?P<q>.+?)에 대하여 P\(x\) (?P<op>[+\-*]) Q\(x\)"
    r"(?:에서|를 전개했을 때) (?P<tgt>x\^\d+|x|상수)의 계수를 구하시오\.$"
)


def check_polyarith(r):
    m = RE_PA.search(r["question_text"])
    if not m:
        return "UNVER", None, ["파싱실패"], "EXPL_UNPARSED"
    try:
        P, Q = sym(m["p"]), sym(m["q"])
        e = {"+": P + Q, "-": P - Q, "*": sp.expand(P * Q)}[m["op"]]
        poly = sp.Poly(e, X)
        deg = {"상수": 0, "x": 1}.get(m["tgt"]) if m["tgt"] in ("상수", "x") else int(m["tgt"].split("^")[1])
        val = poly.coeff_monomial(X**deg)
    except Exception as ex:  # noqa: BLE001
        return "UNVER", None, [f"계산실패:{type(ex).__name__}"], "EXPL_UNPARSED"
    stored = to_q(r["answer"])
    tags = []
    if m["tgt"] == "상수":
        tags.append("비표준용어:상수의 계수(=상수항)")
    # 대안 해석 진단: 저장값이 Q-P 이거나 항 위치가 바뀐 경우 태그
    verdict = "OK" if stored == val else "MISMATCH"
    if verdict == "MISMATCH":
        alts = {
            "Q-P": sp.Poly(Q - P, X).coeff_monomial(X**deg) if m["op"] == "-" else None,
            "인접차수": [poly.coeff_monomial(X**d) for d in range(0, 3) if d != deg],
        }
        if alts["Q-P"] is not None and stored == alts["Q-P"]:
            tags.append("저장값=Q-P")
        if stored in alts["인접차수"]:
            tags.append("저장값=다른차수계수")
    # 설명 일관성: 연산어 + 최종수
    ex = r["answer_explanation"]
    word_ok = {"+": "더하면" in ex, "-": "빼면" in ex, "*": "분배법칙" in ex}[m["op"]]
    mnum = re.search(r"(-?\d+) 이다\.$", ex)
    num_ok = bool(mnum) and num(mnum[1]) == Fraction(str(r["answer"]))
    ev = "EXPL_OK" if (word_ok and num_ok) else "EXPL_BAD"
    if ev == "EXPL_BAD":
        tags.append(f"설명불일치(word_ok={word_ok},num_ok={num_ok})")
    return verdict, str(val), tags, ev


# ---- 2. polynomial_factoring
RE_PF = re.compile(
    r"이차식 (?P<poly>.+?)를 인수분해하면 \(x \+ p\)\(x \+ q\)\(p > q\) 꼴이다\. "
    r"두 인수의 상수항 중 더 (?P<w>큰|작은) 값을 구하시오\.$"
)


def check_polyfactor(r):
    m = RE_PF.search(r["question_text"])
    if not m:
        return "UNVER", None, ["파싱실패"], "EXPL_UNPARSED"
    try:
        f = sym(m["poly"])
        roots = sp.roots(sp.Poly(f, X))
        # (x+p)(x+q) = f  ⇒ p = -근. 정수 단근 두 개여야 발문이 성립
        rs = []
        for rt, mult in roots.items():
            rs += [rt] * mult
        if len(rs) != 2 or any(not rt.is_integer for rt in rs):
            return "ILLPOSED", None, ["정수 두 근으로 인수분해 불가"], "EXPL_UNPARSED"
        ps = sorted([-rt for rt in rs], reverse=True)
        if ps[0] == ps[1]:
            return "ILLPOSED", None, ["p>q 불성립(중근)"], "EXPL_UNPARSED"
        val = ps[0] if m["w"] == "큰" else ps[1]
    except Exception as ex:  # noqa: BLE001
        return "UNVER", None, [f"계산실패:{type(ex).__name__}"], "EXPL_UNPARSED"
    stored = to_q(r["answer"])
    verdict = "OK" if stored == val else "MISMATCH"
    tags = []
    if verdict == "MISMATCH":
        # 대안: 절댓값 기준으로 큰/작은 / 근(=-p) 값
        absvals = sorted([abs(p) for p in ps], reverse=True)
        if stored in ([absvals[0]] if m["w"] == "큰" else [absvals[1]]):
            tags.append("저장값=절댓값 기준")
        if stored == (-ps[0] if m["w"] == "큰" else -ps[1]):
            tags.append("저장값=근(부호반전)")
    # 설명 일관성: (x+a)(x+b) 전개가 발문 이차식과 같고, 두 정수 = p,q 이며, 결론값 == answer
    ex = r["answer_explanation"]
    me = re.search(r"두 정수 (-?\d+), (-?\d+)는 .*\(x ([+-]) (\d+)\)\(x ([+-]) (\d+)\)로 인수분해되고, 구하는 값은 (-?\d+) 이다\.", ex)
    ev = "EXPL_UNPARSED"
    if me:
        a, b = int(me[1]), int(me[2])
        fa = int(me[4]) * (1 if me[3] == "+" else -1)
        fb = int(me[6]) * (1 if me[5] == "+" else -1)
        prod_ok = sp.expand((X + fa) * (X + fb) - f) == 0
        pq_ok = {a, b} == {fa, fb} and a > b
        end_ok = num(me[7]) == Fraction(str(r["answer"]))
        ev = "EXPL_OK" if (prod_ok and pq_ok and end_ok) else "EXPL_BAD"
        if ev == "EXPL_BAD":
            tags.append(f"설명불일치(prod={prod_ok},pq={pq_ok},end={end_ok})")
    return verdict, str(val), tags, ev


# ---- 3. linear_inequality_system
RE_LS = re.compile(
    r"다음 연립부등식을 만족하는 x의 값의 범위에서 두 경계값 중 더 (?P<w>큰|작은) 값을 구하시오: "
    r"(?P<l1>.+?) (?P<o1>[<>]) (?P<r1>-?\d+), (?P<l2>.+?) (?P<o2>[<>]) (?P<r2>-?\d+)$"
)


def check_linsys(r):
    m = RE_LS.search(r["question_text"])
    if not m:
        return "UNVER", None, ["파싱실패"], "EXPL_UNPARSED"
    try:
        cons = []  # (kind, bound)  kind ∈ {'gt','lt'}  : x > bound / x < bound
        for i in (1, 2):
            p = sp.Poly(sym(m[f"l{i}"]), X)
            a, b = p.coeff_monomial(X), p.coeff_monomial(1)
            c = sp.Integer(int(m[f"r{i}"]))
            if a == 0:
                return "UNVER", None, ["x항 없음"], "EXPL_UNPARSED"
            bound = (c - b) / a
            gt = (m[f"o{i}"] == ">") == (a > 0)  # a<0 이면 부등호 반전
            cons.append(("gt" if gt else "lt", bound, a))
        lows = [b for k, b, _ in cons if k == "gt"]
        ups = [b for k, b, _ in cons if k == "lt"]
        tags = []
        if any(a < 0 for *_, a in cons):
            tags.append("음수계수(부등호 반전 필요)")
        if not lows or not ups:
            # 해집합이 한쪽만 유계 → '두 경계값'이 정의되지 않음(교집합의 경계는 하나)
            v_naive = (max if m["w"] == "큰" else min)([b for _, b, _ in cons])
            stored = to_q(r["answer"])
            tags.append("해집합의 경계가 1개뿐(같은 방향 두 부등식)")
            tags.append(f"저장값=두 단독 경계의 {'max' if m['w']=='큰' else 'min'}:{stored == v_naive}")
            return "ILLPOSED", str(v_naive), tags, "EXPL_UNPARSED"
        lo, up = max(lows), min(ups)
        if not lo < up:
            return "ILLPOSED", None, tags + ["해집합 공집합"], "EXPL_UNPARSED"
        val = up if m["w"] == "큰" else lo
    except Exception as ex:  # noqa: BLE001
        return "UNVER", None, [f"계산실패:{type(ex).__name__}"], "EXPL_UNPARSED"
    stored = to_q(r["answer"])
    verdict = "OK" if stored == val else "MISMATCH"
    if verdict == "MISMATCH":
        other = lo if m["w"] == "큰" else up
        if stored == other:
            tags.append("저장값=반대쪽 경계")
    # 설명: '첫째 부등식을 풀면 x > A, 둘째 ... x < B ... A < x < B ... 구하는 값은 V'
    ex = r["answer_explanation"]
    me = re.search(r"첫째 부등식을 풀면 x > (-?\d+(?:/\d+)?), 둘째 부등식을 풀면 x < (-?\d+(?:/\d+)?)이므로 .*범위는 (-?[\d/]+) < x < (-?[\d/]+)이고, 구하는 값은 (-?[\d/]+) 이다\.", ex)
    ev = "EXPL_UNPARSED"
    if me:
        A, B = sp.Rational(me[1]), sp.Rational(me[2])
        # 설명의 '첫째=x>A, 둘째=x<B' 가 실제 발문 부등식 풀이와 같은 방향인가
        first_ok = cons[0][0] == "gt" and cons[0][1] == A
        second_ok = cons[1][0] == "lt" and cons[1][1] == B
        end_ok = num(me[5]) == Fraction(str(r["answer"]))
        ev = "EXPL_OK" if (first_ok and second_ok and end_ok) else "EXPL_BAD"
        if ev == "EXPL_BAD":
            tags.append(f"설명불일치(first={first_ok},second={second_ok},end={end_ok})")
    return verdict, str(val), tags, ev


# ---- 4. quad_ineq
RE_QI = re.compile(
    r"이차부등식 (?P<poly>.+?) (?P<o>[<>]) (?P<rhs>-?\d+)(?:을 만족하는 x의 범위의 두 경계값의 합|의 해의 경계가 되는 두 값의 합)을 구하시오\.$"
)


def check_quadineq(r):
    m = RE_QI.search(r["question_text"])
    if not m:
        return "UNVER", None, ["파싱실패"], "EXPL_UNPARSED"
    try:
        f = sym(m["poly"]) - sp.Integer(int(m["rhs"]))
        p = sp.Poly(f, X)
        if p.degree() != 2:
            return "ILLPOSED", None, ["이차식 아님"], "EXPL_UNPARSED"
        a, b, c = p.coeff_monomial(X**2), p.coeff_monomial(X), p.coeff_monomial(1)
        disc = b * b - 4 * a * c
        tags = []
        if disc <= 0:
            return "ILLPOSED", None, [f"실근 없음/중근(D={disc})"], "EXPL_UNPARSED"
        val = sp.Rational(-b, a)  # 두 근의 합 = -b/a (두 서로 다른 실근이 있을 때)
        # 근을 실제로 구해 합산(공식 대신 직접)
        rts = sp.solve(f, X)
        assert len(rts) == 2
        val = sp.nsimplify(sum(rts))
        outside = (a > 0) == (m["o"] == ">")
    except Exception as ex:  # noqa: BLE001
        return "UNVER", None, [f"계산실패:{type(ex).__name__}"], "EXPL_UNPARSED"
    stored = to_q(r["answer"])
    verdict = "OK" if stored == val else "MISMATCH"
    ex = r["answer_explanation"]
    ev = "EXPL_UNPARSED"
    if "바깥쪽" in ex or "안쪽" in ex:
        side_ok = ("바깥쪽" in ex) == outside and ("안쪽" in ex) != outside
        mnum = re.search(r"두 근의 합의 값은 (-?\d+(?:/\d+)?)이다\.$", ex)
        end_ok = bool(mnum) and num(mnum[1]) == Fraction(str(r["answer"]))
        ev = "EXPL_OK" if (side_ok and end_ok) else "EXPL_BAD"
        if ev == "EXPL_BAD":
            tags.append(f"설명불일치(side_ok={side_ok},end_ok={end_ok})")
    return verdict, str(val), tags, ev


# ---- 5. middle_function
RE_MF = re.compile(r"^(?:일차함수 )?f\(x\) = (?P<f>.+?)(?:에 대하여|일 때,) f\((?P<a>-?\d+)\)(?:을|를|의 값을) 구하시오\.$")


def check_midfunc(r):
    m = RE_MF.search(r["question_text"])
    if not m:
        return "UNVER", None, ["파싱실패"], "EXPL_UNPARSED"
    try:
        f = sym(m["f"])
        a = int(m["a"])
        val = f.subs(X, a)
        slope = sp.Poly(f, X).coeff_monomial(X)
    except Exception as ex:  # noqa: BLE001
        return "UNVER", None, [f"계산실패:{type(ex).__name__}"], "EXPL_UNPARSED"
    tags = []
    if r["question_text"].startswith("일차함수") and slope == 0:
        tags.append("일차함수인데 기울기 0")
    stored = to_q(r["answer"])
    verdict = "OK" if stored == val else "MISMATCH"
    ex = r["answer_explanation"]
    me = re.search(r"^f\(x\) = (.+?)에 x = (-?\d+)(?:을|를) 대입하면 f\((-?\d+)\)의 값은 (-?\d+)이다\.$", ex)
    ev = "EXPL_UNPARSED"
    if me:
        same_f = sp.simplify(sym(me[1]) - f) == 0
        ok = same_f and int(me[2]) == a and int(me[3]) == a and num(me[4]) == Fraction(str(r["answer"]))
        ev = "EXPL_OK" if ok else "EXPL_BAD"
        if not ok:
            tags.append("설명불일치")
    return verdict, str(val), tags, ev


# ---- 6. radian_conversion
RE_R1 = re.compile(r"^일반각 (?P<d>-?\d+)°를 호도법으로 나타내면 얼마인가\?$")
RE_R2 = re.compile(r"^일반각의 호도법 표시 (?P<e>.+?)를 도\(°\) 단위로 나타내면 얼마인가\?$")


def check_radian(r):
    q = r["question_text"]
    stored = to_q(r["answer"])
    m1, m2 = RE_R1.search(q), RE_R2.search(q)
    tags = []
    if m1:
        d = int(m1["d"])
        val = sp.Rational(d, 180) * sp.pi
        verdict = "OK" if (stored is not None and sp.simplify(stored - val) == 0) else "MISMATCH"
        # 기약분수 표기 점검: a*pi/b 에서 gcd(a,b)=1 이어야 설명("기약분수로 약분")과 일치
        ms = re.fullmatch(r"(-?)(?:(\d+)\*)?pi(?:/(\d+))?", r["answer"].strip())
        red_ok = False
        if ms:
            an = int(ms[2] or 1)
            bd = int(ms[3] or 1)
            red_ok = sp.gcd(an, bd) == 1
        if not red_ok:
            tags.append("기약 표기 아님/파싱불가")
        ex = r["answer_explanation"]
        me = re.search(r"^호도법 값은 도 × pi/180으로 구한다\. (-?\d+)°는 기약분수로 약분하면 (.+?) 이다\.$", ex)
        ev = "EXPL_OK" if (me and int(me[1]) == d and me[2] == r["answer"]) else ("EXPL_BAD" if me else "EXPL_UNPARSED")
        if ev == "EXPL_BAD":
            tags.append("설명불일치")
        return verdict, str(val), tags, ev
    if m2:
        try:
            e = sym(m2["e"].replace("−", "-"))
            val = sp.nsimplify(e * 180 / sp.pi)
        except Exception as ex_:  # noqa: BLE001
            return "UNVER", None, [f"계산실패:{type(ex_).__name__}"], "EXPL_UNPARSED"
        verdict = "OK" if (stored is not None and stored == val) else "MISMATCH"
        ex = r["answer_explanation"]
        me = re.search(r"^도 값은 라디안 분수 × 180/pi으로 구한다\. (.+?)는 도 단위로 환산하면 (-?\d+) 이다\.$", ex)
        ev = "EXPL_OK" if (me and me[1] == m2["e"] and num(me[2]) == Fraction(str(r["answer"]))) else ("EXPL_BAD" if me else "EXPL_UNPARSED")
        if ev == "EXPL_BAD":
            tags.append("설명불일치")
        return verdict, str(val), tags, ev
    return "UNVER", None, ["파싱실패"], "EXPL_UNPARSED"


# ---- 7. complex_number_arithmetic
RE_CX = re.compile(r"^두 복소수 z1 = (?P<a>.+?), z2 = (?P<b>.+?)에 대하여 z1 (?P<op>[+\-*]) z2의 (?P<part>실수부|허수부)를 구하시오\.$")


def cx(s: str):
    s = re.sub(r"(\d)i\b", r"\1*I", s)
    s = re.sub(r"(?<![\w*])i\b", "I", s)
    return sp.sympify(s.replace("^", "**"), locals={"I": sp.I})


def check_complex(r):
    m = RE_CX.search(r["question_text"])
    if not m:
        return "UNVER", None, ["파싱실패"], "EXPL_UNPARSED"
    try:
        a, b = cx(m["a"]), cx(m["b"])
        z = sp.expand({"+": a + b, "-": a - b, "*": a * b}[m["op"]])
        val = sp.re(z) if m["part"] == "실수부" else sp.im(z)
    except Exception as ex:  # noqa: BLE001
        return "UNVER", None, [f"계산실패:{type(ex).__name__}"], "EXPL_UNPARSED"
    stored = to_q(r["answer"])
    verdict = "OK" if stored == val else "MISMATCH"
    tags = []
    if verdict == "MISMATCH":
        other = sp.im(z) if m["part"] == "실수부" else sp.re(z)
        if stored == other:
            tags.append("저장값=반대 부(실수부↔허수부)")
        if m["op"] == "-" and stored == (sp.re(b - a) if m["part"] == "실수부" else sp.im(b - a)):
            tags.append("저장값=z2-z1")
    ex = r["answer_explanation"]
    word_ok = {"+": "더하면" in ex, "-": "빼면" in ex, "*": "분배법칙" in ex}[m["op"]]
    part_ok = True
    if m["op"] == "*":
        part_ok = (f"구하는 {m['part']}는" in ex) and ("i^2 = -1" in ex)
    mnum = re.search(r"(-?\d+) 이다\.$", ex)
    end_ok = bool(mnum) and num(mnum[1]) == Fraction(str(r["answer"]))
    ev = "EXPL_OK" if (word_ok and part_ok and end_ok) else "EXPL_BAD"
    if ev == "EXPL_BAD":
        tags.append(f"설명불일치(word={word_ok},part={part_ok},end={end_ok})")
    return verdict, str(val), tags, ev


# ---- 8. matrix_ops
RE_MAT = re.compile(r"\[\[(-?\d+), (-?\d+)\], \[(-?\d+), (-?\d+)\]\]")


def check_matrix(r):
    q = r["question_text"]
    mats = [sp.Matrix([[int(g[0]), int(g[1])], [int(g[2]), int(g[3])]]) for g in RE_MAT.findall(q)]
    pos = re.search(r"\((\d)행 (\d)열\)", q.rsplit("(", 1)[0] + "(" + q.rsplit("(", 1)[1]) if False else None
    mpos = list(re.finditer(r"\((\d)행 (\d)열\)", q))
    if not mpos or not mats:
        return "UNVER", None, ["파싱실패"], "EXPL_UNPARSED"
    ri, ci = int(mpos[-1][1]) - 1, int(mpos[-1][2]) - 1
    # 연산 식별 (발문 속 연산 표기 + 연산어 일관성)
    tags = []
    A = mats[0]
    B = mats[1] if len(mats) > 1 else None
    op = None
    if re.search(r"A \+ B", q):
        op, M = "+", (A + B if B is not None else None)
        word_ok = ("의 합" in q) or ("에 대하여" in q)
    elif re.search(r"A - B", q):
        op, M = "-", (A - B if B is not None else None)
        word_ok = ("의 차" in q) or ("에 대하여" in q)
    elif re.search(r"(?<![A-Za-z])AB", q):
        op, M = "AB", (A * B if B is not None else None)
        word_ok = ("의 곱" in q) or ("에 대하여" in q)
    else:
        mk = re.search(r"(?<![\w])(-?\d+)A", q)
        if mk and B is None:
            k = int(mk[1])
            op, M = f"{k}A", k * A
            word_ok = True
        else:
            return "UNVER", None, ["연산 식별 실패"], "EXPL_UNPARSED"
    if M is None:
        return "UNVER", None, ["행렬 개수 불일치"], "EXPL_UNPARSED"
    # 연산어('합/차/곱') 가 연산 기호와 어긋나는지
    if ("의 합" in q and op != "+") or ("의 차" in q and op != "-") or ("의 곱 " in q and op != "AB"):
        tags.append("연산어-기호 불일치")
    val = M[ri, ci]
    stored = to_q(r["answer"])
    verdict = "OK" if stored == val else "MISMATCH"
    if verdict == "MISMATCH":
        alts = {"행열 전치(c행 r열)": M[ci, ri]}
        if op == "AB":
            alts["BA"] = (B * A)[ri, ci]
            alts["원소별 곱"] = A[ri, ci] * B[ri, ci]
        for name, v in alts.items():
            if stored == v:
                tags.append(f"저장값={name}")
    # 설명 일관성
    ex = r["answer_explanation"]
    ev = "EXPL_UNPARSED"
    nums = [int(v) for v in re.findall(r"(?<![\d(])-?\d+", re.sub(r"\(\d행 \d열\)", "", ex))]
    posn = re.findall(r"\((\d)행 (\d)열\)", ex)
    pos_ok = all((int(a) - 1, int(b) - 1) == (ri, ci) for a, b in posn) if posn else True
    if op == "+":
        ev_ok = nums == [int(A[ri, ci]), int(B[ri, ci]), int(val)] and "합" in ex
    elif op == "-":
        ev_ok = nums == [int(A[ri, ci]), int(B[ri, ci]), int(val)] and "뺀" in ex
    elif op == "AB":
        # 'A의 R행과 B의 C열의 내적: a × b + c × d = v'
        mrc = re.search(r"A의 (\d)행과 B의 (\d)열", ex)
        rc_ok = bool(mrc) and (int(mrc[1]) - 1, int(mrc[2]) - 1) == (ri, ci)
        ev_ok = rc_ok and nums[-5:] == [int(A[ri, 0]), int(B[0, ci]), int(A[ri, 1]), int(B[1, ci]), int(val)]
    else:
        k = int(op[:-1])
        ev_ok = nums == [k, k, int(A[ri, ci]), int(val)] and "스칼라배" in ex  # 설명문에 k가 두 번 등장('에 k를 곱한다: k × a = v')
    ev = "EXPL_OK" if (ev_ok and pos_ok) else "EXPL_BAD"
    if ev == "EXPL_BAD":
        tags.append("설명불일치")
    return verdict, str(val), tags, ev


CHECKERS = {
    "problem_bank_polynomial_arithmetic_v0": check_polyarith,
    "problem_bank_polynomial_factoring_v0": check_polyfactor,
    "problem_bank_linear_inequality_system_v0": check_linsys,
    "problem_bank_quad_ineq_v0": check_quadineq,
    "problem_bank_middle_function_v0": check_midfunc,
    "problem_bank_radian_conversion_v0": check_radian,
    "problem_bank_complex_number_arithmetic_v0": check_complex,
    "problem_bank_matrix_ops_v0": check_matrix,
}


# ---------------------------------------------------------------- answer_format 부차 점검
def fmt_issue(r) -> str | None:
    f, a = r.get("answer_format"), str(r["answer"])
    v = to_q(a)
    if v is None:
        return "answer 파싱불가"
    if f == "자연수":
        if not (v.is_integer and v >= 1):
            return f"자연수 형식인데 answer={a}"
    elif f == "실수":
        if not v.is_real:
            return f"실수 형식인데 answer={a}"
    return None


# ---------------------------------------------------------------- 실행
def run(root: Path, n_examples: int):
    out = {}
    for d in CORPORA:
        path = root / d / "problems.jsonl"
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        chk = CHECKERS[d]
        res = Counter()
        expl = Counter()
        tpl = Counter()
        tpl_vocab = defaultdict(set)
        vocab_rows = Counter()
        tagc = Counter()
        examples = defaultdict(list)
        fmt = Counter()
        fmt_ex = []
        for r in rows:
            q = r["question_text"]
            t = template(q)
            tpl[t] += 1
            hit = {k for k, rx in VOCAB.items() if re.search(rx, q)}
            tpl_vocab[t] |= hit
            for k in hit:
                vocab_rows[k] += 1
            verdict, val, tags, ev = chk(r)
            res[verdict] += 1
            expl[ev] += 1
            for tg in tags:
                tagc[tg.split("(")[0].split(":")[0]] += 1
            if verdict in ("MISMATCH", "ILLPOSED", "AMBIG", "UNVER") or ev == "EXPL_BAD":
                key = verdict if verdict != "OK" else ev
                if len(examples[key]) < n_examples:
                    examples[key].append(
                        {"question_text": q, "stored_answer": r["answer"], "indep": val, "tags": tags, "explanation": r["answer_explanation"], "verdict": verdict, "expl": ev}
                    )
            fi = fmt_issue(r)
            if fi:
                fmt[fi.split("인데")[0] if "인데" in fi else fi] += 1
                if len(fmt_ex) < 3:
                    fmt_ex.append({"q": q, "answer": r["answer"], "answer_format": r.get("answer_format")})
        out[d] = {
            "rows": len(rows),
            "published": sum(1 for r in rows if r.get("is_published") is True),
            "templates": len(tpl),
            "template_list": [(t, n, sorted(tpl_vocab[t])) for t, n in tpl.most_common()],
            "vocab_rows": dict(vocab_rows),
            "verdict": dict(res),
            "expl": dict(expl),
            "tags": dict(tagc),
            "examples": dict(examples),
            "format_issues": dict(fmt),
            "format_examples": fmt_ex,
            "scanned": len(rows) > 0 and sum(res.values()) == len(rows),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-root", default=str(Path(__file__).resolve().parents[3]) + "/data/corpus")
    ap.add_argument("--json", default=None)
    ap.add_argument("--examples", type=int, default=5)
    a = ap.parse_args()
    out = run(Path(a.corpus_root), a.examples)
    bad = 0
    print(f"{'corpus':48s} rows tpl  OK  MISM ILLP UNVER AMBIG | expl OK/BAD/UNP | pub")
    for d, o in out.items():
        v, e = o["verdict"], o["expl"]
        print(
            f"{d:48s} {o['rows']:4d} {o['templates']:3d} {v.get('OK',0):4d} {v.get('MISMATCH',0):4d} {v.get('ILLPOSED',0):4d} "
            f"{v.get('UNVER',0):4d} {v.get('AMBIG',0):4d} | {e.get('EXPL_OK',0):4d}/{e.get('EXPL_BAD',0):4d}/{e.get('EXPL_UNPARSED',0):4d} | {o['published']}"
        )
        if o["rows"] == 0 or not o["scanned"]:
            print("  !! 스캔 0건 또는 미완 — 실패")
            bad += 1
        bad += v.get("MISMATCH", 0) + v.get("ILLPOSED", 0) + e.get("EXPL_BAD", 0) + v.get("UNVER", 0)
        if o["tags"]:
            print("   tags:", o["tags"])
        if o["format_issues"]:
            print("   answer_format 부차 이슈:", o["format_issues"])
    # 해석 모호 후보 프로브(판정에는 불포함 — 표준 해석이 교과서상 유일하다고 판단한 어휘의 대안 해석 영향 건수)
    pf = [json.loads(l) for l in (Path(a.corpus_root) / "problem_bank_polynomial_factoring_v0" / "problems.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    diff_abs = 0
    for r in pf:
        m = RE_PF.search(r["question_text"])
        if not m:
            continue
        rs = [-rt for rt in sp.roots(sp.Poly(sym(m["poly"]), X))]
        sg = max(rs) if m["w"] == "큰" else min(rs)
        ab = max(rs, key=abs) if m["w"] == "큰" else min(rs, key=abs)
        diff_abs += sg != ab
    print(f"[프로브] factoring: '상수항의 크기=절댓값' 대안 해석이 부호 해석과 다른 행 {diff_abs}/{len(pf)} (발문이 (x+p)(x+q),(p>q)로 부호 해석을 못박으므로 AMBIG 미계상)")
    if a.json:
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
