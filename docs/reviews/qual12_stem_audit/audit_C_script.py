#!/usr/bin/env python3
"""QUAL-12 감사 슬라이스 C — 발문 자연어 해석 vs 저장 정답 독립 재계산 대조.

원칙
- 생성기 모듈(whymath_backend.*)을 import/호출하지 않는다. data/corpus/*/problems.jsonl 의
  question_text 만 파싱해 SymPy 로 정답을 다시 계산하고 저장된 answer 와 대조한다.
- 샘플링 없음: 전 행 대조. 파싱 실패/독립계산 불가는 '미검증(unverified)'로 따로 센다(통과 아님).
- 판정 상태: match / mismatch / ambiguous(해석 둘로 갈림: 두 해석 건수를 각각 기록) / unverified
- 재실행: python3 audit_C_script.py [--repo /home/user/WhyMath] [--json out.json]
"""
import argparse
import collections
import json
import re
import sys
from fractions import Fraction

import sympy as sp

X, T, K = sp.symbols("x t k")

CORPORA = [
    "problem_bank_calculus1_integral_v0",
    "problem_bank_calculus2_trig_integral_v0",
    "problem_bank_p3_calculus1_diff_v0",
    "problem_bank_highschool_quotient_rule_v0",
    "problem_bank_university_calc1_v0",
    "problem_bank_university_calc1_chain_quotient_v0",
    "problem_bank_sequence_sigma_v0",
]

# ---------------------------------------------------------------- 의미 어휘 사전
# 라벨 -> 실제 단어 정규식 (매치된 단어를 기록해 보고서에 그대로 싣는다)
VOCAB = {
    "구간(폐/개)": r"닫힌구간|열린구간|구간",
    "정적분 상·하한/적분구간": r"정적분|\[[^\]]*\] 구간|구간 \[|x = \d+, x = \d+|t = \S+에서 t = ",
    "넓이": r"넓이|둘러싸",
    "이동거리": r"움직인 거리|이동 거리",
    "속도/가속도/위치/속력": r"속도|가속도|위치가|속력|운동 방향|멈추",
    "증가/감소": r"증가|감소|작아지는|커질 때",
    "극값/최대최소": r"극대|극소|극값|극댓값|극솟값|최댓값|최솟값|가장 큰|가장 작은",
    "접선/법선": r"접선|법선|접할|접점",
    "평균값/변화율/미분계수": r"평균값|평균변화율|평균속도|평균 속도|롤의 정리|변화량|미분계수",
    "시그마/항/합": r"합을 구하|모두 더|총합|제곱의 합|세제곱|자연수를 각각|자연수 각각|k=1부터|1부터 \d+까지",
    "f(a)/f'(a) 표기": r"f'\(|y'|g'\(",
    "도함수/계수/상수항": r"도함수|계수|상수항",
    "개수/실근/교점": r"개수|실근|교점|서로 다른",
    "양수/범위/부등식": r"양수|범위|이상|이하|≥|≤|보이려",
}


def vocab_of(q):
    hit = {}
    for k, rx in VOCAB.items():
        ws = re.findall(rx, q)
        if ws:
            hit[k] = sorted(set(ws))
    return hit


def skeleton(q):
    return re.sub(r"[ -~]+", "#", q)


# ---------------------------------------------------------------- 수식 파서(독립 구현)
_TOK = re.compile(r"\d+(?:\.\d+)?|sin|cos|tan|pi|[A-Za-z]|[()+\-*/^,]")


def to_py(s):
    """수학 표기 문자열 -> sympy 가 읽는 파이썬 식 문자열. 암묵적 곱 삽입, ^ -> **"""
    s = s.replace("≥", ">=").replace("≤", "<=").replace("·", "*")
    toks = _TOK.findall(s)
    # 토큰 외 문자가 남았는지 확인
    if "".join(toks) != re.sub(r"\s+", "", s):
        raise ValueError("파싱 불가 문자: %r" % s)
    out = []
    funcs = {"sin", "cos", "tan"}
    for i, tk in enumerate(toks):
        if out:
            prev = toks[i - 1]
            prev_val = prev[0].isdigit() or prev == ")" or prev == "pi" or (prev.isalpha() and prev not in funcs)
            cur_start = tk[0].isdigit() or tk == "(" or tk in funcs or tk == "pi" or (tk.isalpha() and tk not in funcs)
            # 함수 뒤의 '(' 는 호출. 숫자 뒤 숫자는 있을 수 없음.
            if prev_val and cur_start:
                out.append("*")
        out.append("**" if tk == "^" else tk)
    return "".join(out)


def P(s, extra=None):
    ns = {"x": X, "t": T, "k": K, "pi": sp.pi, "sin": sp.sin, "cos": sp.cos, "tan": sp.tan}
    for ch in "abcdefghijklmnopqrsuvwyz":
        ns.setdefault(ch, sp.Symbol(ch))
    if extra:
        ns.update(extra)
    return sp.sympify(to_py(s), locals=ns, rational=True)


def parse_ans(a):
    a = str(a).strip()
    return sp.Rational(Fraction(a)) if re.fullmatch(r"-?\d+(/\d+)?", a) else None


def same(a, b):
    return sp.simplify(sp.nsimplify(a) - sp.nsimplify(b)) == 0


class Unverified(Exception):
    pass


# ---------------------------------------------------------------- 공통 유틸
def abs_integral(expr, var, a, b):
    """∫_a^b |expr| d var. 다항식/사인 한정. 영점에서 구간을 나눈다."""
    if a > b:
        a, b = b, a
    pts = {sp.Integer(0) + a, sp.Integer(0) + b}
    if expr.has(sp.sin) or expr.has(sp.cos):
        # sin/cos 의 영점 후보: pi/2 의 정수배 (sin x 한정이면 pi 정수배지만 보수적으로 pi/2 간격)
        n0 = int(sp.floor(a / (sp.pi / 2))) - 1
        n1 = int(sp.ceiling(b / (sp.pi / 2))) + 1
        for n in range(n0, n1 + 1):
            p = n * sp.pi / 2
            if a < p < b and sp.simplify(expr.subs(var, p)) == 0:
                pts.add(p)
    else:
        for r in sp.Poly(expr, var).real_roots():
            if a < r < b:
                pts.add(r)
    pts = sorted(pts, key=lambda z: float(z))
    tot = 0
    for lo, hi in zip(pts, pts[1:]):
        mid = (lo + hi) / 2
        sgn = sp.sign(sp.nsimplify(expr.subs(var, mid)))
        tot += sgn * sp.integrate(expr, (var, lo, hi))
    return sp.nsimplify(sp.simplify(tot))


def result(status, indep=None, note="", alt=None):
    return {"status": status, "indep": None if indep is None else str(indep), "note": note, "alt": alt}


def compare(stored, indep, note=""):
    s = parse_ans(stored)
    if s is None:
        # 저장 answer 가 정수/분수 문자열이 아니면 sympy 로 시도
        try:
            s = sp.nsimplify(sp.sympify(str(stored)))
        except Exception:
            return result("unverified", indep, "저장 answer 파싱 불가: %r" % stored)
    return result("match" if same(s, indep) else "mismatch", indep, note)


# ================================================================ 코퍼스 1/2: 적분
RE_INDEF = re.compile(r"^다항함수 f\(x\) = ([ -~]+?)의 부정적분 중 F\(0\) = (-?\d+)인 함수를 F\(x\)라 할 때, F\((-?\d+)\)의 값을 구하시오\.$")
RE_DEF_A = re.compile(r"^정적분 \[(-?[ -~]+?), (-?[ -~]+?)\] 구간에서 f\(x\) = ([ -~]+?)의 정적분 값을 구하시오\.$")
RE_DEF_B = re.compile(r"^(?:다항)?함수 f\(x\) = ([ -~]+?)에 대하여 정적분 \(구간 \[([ -~]+?), ([ -~]+?)\]에서의\) 값을 구하시오\.$")
RE_AREA = re.compile(r"^곡선 y = ([ -~]+?)와 x축 및 두 직선 x = ([ -~]+?), x = ([ -~]+?)로 둘러싸인 도형의 넓이를 구하시오\.$")
RE_DIST = re.compile(r"^수직선 위를 움직이는 점 P의 시각 t에서의 속도가 v\(t\) = ([ -~]+?)일 때, 시각 t = ([ -~]+?)에서 t = ([ -~]+?)까지 점 P가 움직인 거리를 구하시오\.$")


def check_integral(row):
    q = row["question_text"]
    ans = row["answer"]
    expl = row["answer_explanation"]
    m = RE_INDEF.match(q)
    if m:
        f = P(m.group(1))
        c = sp.Integer(m.group(2))
        mm = sp.Integer(m.group(3))
        v = c + sp.integrate(f, (X, 0, mm))
        return "부정적분 F(0)=c → F(m)", compare(ans, v)
    m = RE_DEF_A.match(q)
    if m:
        a, b, f = P(m.group(1)), P(m.group(2)), P(m.group(3))
        v = sp.integrate(f, (X, a, b))
        r = compare(ans, v)
        if a >= b:
            r["note"] += " [구간 [a,b]에서 a>=b]"
        return "정적분 [a,b] 구간(전위형)", r
    m = RE_DEF_B.match(q)
    if m:
        f, a, b = P(m.group(1)), P(m.group(2)), P(m.group(3))
        v = sp.integrate(f, (X, a, b))
        r = compare(ans, v)
        if a >= b:
            r["note"] += " [구간 [a,b]에서 a>=b]"
        return "정적분 (구간 [a,b]에서의)", r
    m = RE_AREA.match(q)
    if m:
        f, a, b = P(m.group(1)), P(m.group(2)), P(m.group(3))
        signed = sp.integrate(f, (X, a, b))
        absv = abs_integral(f, X, a, b)
        s = parse_ans(ans)
        note = ""
        # 설명문 "곡선이 항상 x축 위에 있으므로" 주장 검증
        if "항상 x축 위" in expl:
            pos = _nonneg_on(f, X, a, b)
            note = "설명 '항상 x축 위' 주장=%s" % ("참" if pos else "거짓")
        probe("넓이: ∫|f|(통상) vs 부호있는 ∫f", absv, signed)
        if same(signed, absv):
            return "넓이(곡선·x축·두 직선)", dict(compare(ans, absv, note), alt={"signed": str(signed), "abs": str(absv)})
        # 부호 변화 → 넓이는 ∫|f| 가 한국 교과 통상 해석. 저장값이 어느 쪽인지 기록
        r = compare(ans, absv, note)
        r["alt"] = {"signed": str(signed), "abs": str(absv), "stored_equals_signed": same(s, signed) if s is not None else None}
        return "넓이(곡선·x축·두 직선)", r
    m = RE_DIST.match(q)
    if m:
        f, a, b = P(m.group(1), {"t": X}), P(m.group(2)), P(m.group(3))
        # v(t) 는 변수 t -> X 로 통일해 파싱
        signed = sp.integrate(f, (X, a, b))
        absv = abs_integral(f, X, a, b)
        s = parse_ans(ans)
        note = ""
        if "항상 양수" in expl:
            pos = _nonneg_on(f, X, a, b, strict=True)
            note = "설명 '속도가 항상 양수' 주장=%s" % ("참" if pos else "거짓")
        r = compare(ans, absv, note)
        probe("이동거리: ∫|v|(통상) vs 위치변화량 ∫v", absv, signed)
        if not same(signed, absv):
            r["alt"] = {"displacement(위치변화량)": str(signed), "distance(∫|v|)": str(absv),
                        "stored_equals_displacement": same(s, signed) if s is not None else None}
        return "이동 거리(속도 v(t), t=a→b)", r
    raise Unverified("템플릿 미인식")


def _nonneg_on(f, var, a, b, strict=False):
    if a > b:
        a, b = b, a
    pts = {a, b}
    if f.has(sp.sin) or f.has(sp.cos):
        n0 = int(sp.floor(a / (sp.pi / 2))) - 1
        n1 = int(sp.ceiling(b / (sp.pi / 2))) + 1
        for n in range(n0, n1 + 1):
            p = n * sp.pi / 2
            if a < p < b:
                pts.add(p)
    else:
        for r in sp.Poly(f, var).real_roots():
            if a < r < b:
                pts.add(r)
    pts = sorted(pts, key=lambda z: float(z))
    for lo, hi in zip(pts, pts[1:]):
        if f.subs(var, (lo + hi) / 2) < 0:
            return False
    if strict:
        # 양 끝에서 0 이 되는 것은 허용(열린 구간 내부에서 양수)
        pass
    return True


# ================================================================ 코퍼스: 미분(곱·몫·연쇄)
RE_DER_A = re.compile(r"^함수 f\(x\) = ([ -~]+?)의 도함수 f'\(x\)에 대하여 f'\((-?\d+)\)[을를] 구하시오\.$")
RE_DER_B = re.compile(r"^f\(x\) = ([ -~]+?)일 때, f'\((-?\d+)\)의 값을 구하시오\.$")


def check_deriv_point(row):
    q = row["question_text"]
    m = RE_DER_A.match(q) or RE_DER_B.match(q)
    if not m:
        raise Unverified("템플릿 미인식")
    f = P(m.group(1))
    a = sp.Integer(m.group(2))
    den = None
    if "/" in m.group(1):
        # 분모 0 검사
        top, bot = _split_quot(m.group(1))
        den = P(bot).subs(X, a)
        if den == 0:
            return "f'(a) 도함수 값", result("unverified", None, "분모가 0 → f'(a) 정의 불가")
    v = sp.diff(f, X).subs(X, a)
    return "f'(a) 도함수 값", compare(row["answer"], sp.nsimplify(v))


def _split_quot(s):
    """'(A)/(B)' 형태에서 분자/분모 문자열 분리 (최상위 '/' 한 개)."""
    depth = 0
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "/" and depth == 0:
            return s[:i], s[i + 1:]
    raise Unverified("분수 구조 분리 실패")


# ================================================================ 코퍼스: 시그마
RE_SIG_A = re.compile(r"^1부터 (\d+)까지의 자연수를 k라 할 때, ([ -~]+?)의 값을 k=1부터 (\d+)까지 모두 더한 합을 구하시오\.$")
RE_SIG_B = re.compile(r"^1부터 (\d+)까지의 자연수 각각을 (\d+)배 하고 (\d+)씩 더한 다음, 그 값들의 총합을 구하시오\.$")
RE_SIG_C = re.compile(r"^1부터 (\d+)까지의 자연수 각각에 (\d+)[을를] 곱한 후 (\d+)[을를] 더한 값들을 모두 합을 구하시오\.$")
RE_SIG_D = re.compile(r"^1부터 (\d+)까지의 자연수(?:의|를 각각) (제곱|세제곱)(?:의 합을 구하시오|하여 모두 더한 값을 구하시오)\.$")


def check_sigma(row):
    q = row["question_text"]
    m = RE_SIG_A.match(q)
    if m:
        n, e, n2 = int(m.group(1)), P(m.group(2)), int(m.group(3))
        v = sum(e.subs(K, i) for i in range(1, n + 1))
        r = compare(row["answer"], v)
        if n != n2:
            r = result("mismatch", v, "발문 상한 불일치 %d vs %d" % (n, n2))
        return "Σ_{k=1}^{N}(식)", _expl_sigma(row, r, n)
    m = RE_SIG_B.match(q)
    if m:
        n, a, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        v = sum(a * i + b for i in range(1, n + 1))
        return "각각 A배 하고 B씩 더한 총합", _expl_sigma(row, compare(row["answer"], v), n)
    m = RE_SIG_C.match(q)
    if m:
        n, a, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        v = sum(a * i + b for i in range(1, n + 1))
        return "각각 A를 곱한 후 B를 더한 합", _expl_sigma(row, compare(row["answer"], v), n)
    m = RE_SIG_D.match(q)
    if m:
        n, p = int(m.group(1)), (2 if m.group(2) == "제곱" else 3)
        v = sum(i ** p for i in range(1, n + 1))
        return "제곱/세제곱의 합", _expl_sigma(row, compare(row["answer"], v), n)
    raise Unverified("템플릿 미인식")


def _expl_sigma(row, r, n):
    ex = row["answer_explanation"]
    mm = re.search(r"1부터 (\d+)까지의 합은 (-?\d+)", ex)
    if mm and (int(mm.group(1)) != n or mm.group(2) != str(row["answer"])):
        r["note"] += " [설명문 불일치]"
        r["expl_mismatch"] = True
    return r


# ================================================================ 코퍼스: P3 미분(7개 단원 · 템플릿 232종)
# 각 핸들러: 정규식(발문 전체 매칭) → 독립 계산값(sympy) 또는 result dict.
E = r"([ -~]+?)"
H = []


def h(pattern, name):
    rx = re.compile(pattern)

    def deco(fn):
        H.append((rx, name, fn))
        return fn
    return deco


def D(f, v=X):
    return sp.diff(f, v)


def amb(stored, values, note):
    """해가 여러 개 → 단일 정답을 요구하는 발문이 모호. stored 가 values 에 속하는지만 기록."""
    s = parse_ans(stored)
    inn = any(same(s, v) for v in values) if s is not None else None
    return result("ambiguous", values, note + " (저장값이 해집합에 %s)" % ("포함" if inn else "불포함"))


def real_roots_set(expr, var=X):
    p = sp.Poly(sp.together(expr).as_numer_denom()[0], var)
    return sorted(set(p.real_roots()), key=lambda z: float(z))


def sign_at(expr, val):
    v = sp.nsimplify(expr.subs(X, val))
    return 1 if v > 0 else (-1 if v < 0 else 0)


def crit_info(f):
    """다항식 f 의 f'=0 실근과 극대/극소/무변화 분류."""
    d = D(f)
    rts = real_roots_set(d)
    info = []
    for i, r in enumerate(rts):
        lo = (rts[i - 1] + r) / 2 if i > 0 else r - 1
        hi = (r + rts[i + 1]) / 2 if i + 1 < len(rts) else r + 1
        sl, sr = sign_at(d, lo), sign_at(d, hi)
        kind = "max" if (sl > 0 and sr < 0) else ("min" if (sl < 0 and sr > 0) else "none")
        info.append((r, kind, sp.nsimplify(f.subs(X, r))))
    return info


def intervals_sign(d, want):
    """f'(=d) 의 부호가 want(+1/-1)인 구간들의 [(lo,hi)] (lo/hi 는 sympy, ±oo 포함)."""
    rts = real_roots_set(d)
    pts = [-sp.oo] + rts + [sp.oo]
    out = []
    for lo, hi in zip(pts, pts[1:]):
        if lo == -sp.oo and hi == sp.oo:
            mid = sp.Integer(0)
        elif lo == -sp.oo:
            mid = hi - 1
        elif hi == sp.oo:
            mid = lo + 1
        else:
            mid = (lo + hi) / 2
        if sign_at(d, mid) == want:
            out.append((lo, hi))
    return out


def ints_in(intervals, closed):
    s = set()
    for lo, hi in intervals:
        a = -50 if lo == -sp.oo else int(sp.floor(lo))
        b = 50 if hi == sp.oo else int(sp.ceiling(hi))
        for k in range(a, b + 1):
            kk = sp.Integer(k)
            inside = (lo <= kk <= hi) if closed else (lo < kk < hi)
            if inside:
                s.add(k)
    return s


def tangent_line(f, a):
    s = D(f).subs(X, a)
    return s, sp.nsimplify(f.subs(X, a) - s * a)  # 기울기, y절편


def on_curve(f, px, py):
    prem("점이 곡선 위에 있는가")
    return same(f.subs(X, px), py)



# ---------------------------------------------------------------- POWER
@h(r"^함수 f\(x\) = " + E + r"에 대하여 f'\((-?\d+)\)의 값(?:을 구하시오\.|은\?)$", "f'(a) 값(함수 직접)")
def _p1(m, q):
    return D(P(m.group(1))).subs(X, int(m.group(2)))


@h(r"^f\(x\) = " + E + r", g\(x\) = " + E + r"일 때, f'\((-?\d+)\) \+ g'\((-?\d+)\)의 값을 구하시오\.$", "f'(a)+g'(a)")
def _p2(m, q):
    a = int(m.group(3))
    return D(P(m.group(1))).subs(X, a) + D(P(m.group(2))).subs(X, int(m.group(4)))


@h(r"^함수 f\(x\) = x\^n \(n은 2 이상의 자연수\)에 대하여 f'\((\d+)\)의 값이 (-?\d+)일 때, n의 값을 구하시오\.$", "x^n: f'(a)=v → n(n>=2)")
def _p3(m, q):
    a, v = int(m.group(1)), int(m.group(2))
    sols = [n for n in range(2, 80) if n * a ** (n - 1) == v]
    if len(sols) != 1:
        return amb(row_stored(q), sols, "n 해 개수 %d" % len(sols)) if sols else result("mismatch", None, "해 없음")
    return sp.Integer(sols[0])


def _cm(f, var, op):
    d = sp.Poly(D(f, var), var)
    if len(d.terms()) != 1:
        raise Unverified("도함수가 단항 아님")
    (mon, c), = d.terms()
    mexp = mon[0]
    return c + mexp if op == "sum" else c * mexp




# c,m 꼴 계열은 개별 정규식으로 처리
@h(r"^함수 f\(x\) = " + E + r"의 도함수 f'\(x\)를 ([ck])x\^m \(\2, m은 상수\) 꼴로 나타낼 때, \2 \+ m의 값을 구하시오\.$", "도함수 cx^m 꼴 c+m")
def _p4a(m, q):
    return _cm(P(m.group(1)), X, "sum")


@h(r"^(?:함수 )?f\(x\) = " + E + r"의 도함수 f'\(x\)를 ([ck])x\^m \(\2, m은 상수\) 꼴로 나타낼 때, \2와 m의 곱을 구하시오\.$", "도함수 cx^m 꼴 c·m")
def _p4b(m, q):
    return _cm(P(m.group(1)), X, "prod")


@h(r"^함수 g\(t\) = " + E + r"[을를] t에 대하여 미분한 도함수를 ([ck])t\^m \(\2, m은 상수\) 꼴로 나타낼 때, \2 \+ m의 값을 구하시오\.$", "g(t) 미분 도함수 ct^m 꼴 c+m")
def _p4c(m, q):
    return _cm(P(m.group(1), {"t": T}), T, "sum")


@h(r"^함수 y = " + E + r"의 도함수를 y' = ([ck])x\^m \(\2, m은 상수\) 꼴로 나타낼 때, \2와 m의 곱을 구하시오\.$", "y' = cx^m 꼴 c·m")
def _p4d(m, q):
    return _cm(P(m.group(1)), X, "prod")


@h(r"^함수 f\(x\) = " + E + r"[을를] x에 대하여 미분했을 때 도함수의 계수 c와 지수 m의 합 c \+ m을 구하시오\. \(도함수는 cx\^m 꼴이고, c, m은 상수이다\.\)$", "도함수의 계수 c·지수 m의 합")
def _p4e(m, q):
    return _cm(P(m.group(1)), X, "sum")


@h(r"^함수 f\(x\) = " + E + r"에 대하여 f'\((-?\d+)\)의 값은 f\(\2\)의 값의 몇 배인지 구하시오\.$", "f'(a)는 f(a)의 몇 배")
def _p5a(m, q):
    f = P(m.group(1))
    a = int(m.group(2))
    return sp.nsimplify(D(f).subs(X, a) / f.subs(X, a))


@h(r"^함수 f\(x\) = x\^n \(n은 자연수\)에 대하여 f'\((-?\d+)\)의 값이 f\(\1\)의 값의 (\d+)배일 때, n의 값을 구하시오\.$", "x^n: f'(a)=k·f(a) → n")
def _p5b(m, q):
    a, k = int(m.group(1)), int(m.group(2))
    sols = [n for n in range(1, 80) if n * sp.Integer(a) ** (n - 1) == k * sp.Integer(a) ** n]
    if len(sols) != 1:
        return amb(row_stored(q), sols, "n 해 개수 %d" % len(sols)) if sols else result("mismatch", None, "해 없음")
    return sp.Integer(sols[0])


@h(r"^함수 f\(x\) = " + E + r"에 대하여 방정식 f'\(x\) = " + E + r"의 0이 아닌 실근을 구하시오\.$", "f'(x)=g(x)의 0이 아닌 실근")
def _p6(m, q):
    f, g = P(m.group(1)), P(m.group(2))
    rts = [r for r in real_roots_set(D(f) - g) if r != 0]
    if len(rts) != 1:
        return amb(row_stored(q), rts, "0이 아닌 실근 개수 %d" % len(rts)) if rts else result("mismatch", None, "해 없음")
    return rts[0]


@h(r"^(?:함수 )?y = " + E + r"의 x = (-?\d+)에서의 미분계수(?:를 구하시오|로 옳은 것은\?)\.?$", "y의 x=a에서의 미분계수")
def _p7a(m, q):
    return D(P(m.group(1))).subs(X, int(m.group(2)))


@h(r"^함수 y = " + E + r"의 x = a에서의 미분계수가 (-?\d+)일 때, 양수 a의 값을 구하시오\.$", "x=a 미분계수=v → 양수 a")
def _p7b(m, q):
    f = P(m.group(1))
    a = sp.Symbol("a")
    rts = [r for r in sp.solve(D(f).subs(X, a) - int(m.group(2)), a) if r.is_real and r > 0]
    return _single(q, rts)


def row_stored(q):
    return CUR["stored"]


CUR = {}
PROBES = []
PREMS = []


def prem(label):
    """발문이 스스로 주장하는 전제(점∈곡선·'하나뿐'·'두 개'·f(a)=f(b)·분모 표기 등)를 실제로 검증했음을 기록."""
    PREMS.append(label)


def probe(label, primary, alt):
    """해석이 갈릴 수 있는 어휘에 대해 '통상 해석(primary)'과 '대안 해석(alt)'의 값을 기록.
    alt 가 None 이면 '대안 해석에서는 단일 답이 정해지지 않음'(= 해석에 따라 답이 갈림)으로 본다."""
    if alt is None:
        differs = True
    else:
        try:
            differs = not same(primary, alt)
        except Exception:
            differs = None
    PROBES.append({"label": label, "primary": str(primary), "alt": "(단일답 불가)" if alt is None else str(alt), "differs": differs})


def _single(q, vals):
    if len(vals) == 1:
        return sp.nsimplify(vals[0])
    if not vals:
        return result("mismatch", None, "조건을 만족하는 해 없음")
    return amb(row_stored(q), vals, "해 개수 %d" % len(vals))


@h(r"^함수 f\(x\) = " + E + r"에 대하여 f'\(a\) = (-?\d+)[을를] 만족시키는 (양수 a의 값(?:을 구하시오\.|은\?)|a의 값은\?)$", "f'(a)=v를 만족시키는 (양수) a")
def _p8a(m, q):
    f = P(m.group(1))
    a = sp.Symbol("a")
    sols = [r for r in sp.solve(D(f).subs(X, a) - int(m.group(2)), a) if r.is_real]
    if m.group(3).startswith("양수"):
        sols = [r for r in sols if r > 0]
    return _single(q, sols)


@h(r"^함수 f\(x\) = " + E + r"에 대하여 f'\(a\) = f\(a\)를 만족시키는 0이 아닌 실수 a의 값을 구하시오\.$", "f'(a)=f(a) 0이 아닌 실수 a")
def _p8b(m, q):
    f = P(m.group(1))
    a = sp.Symbol("a")
    sols = [r for r in sp.solve(D(f).subs(X, a) - f.subs(X, a), a) if r.is_real and r != 0]
    return _single(q, sols)


@h(r"^함수 f\(x\) = " + E + r"에 대하여 f'\(a\)의 값이 f'\((-?\d+)\)의 값보다 (\d+)만큼 클 때, 양수 a의 값을 구하시오\.$", "f'(a) = f'(p)+d → 양수 a")
def _p8c(m, q):
    f = P(m.group(1))
    a = sp.Symbol("a")
    sols = [r for r in sp.solve(D(f).subs(X, a) - D(f).subs(X, int(m.group(2))) - int(m.group(3)), a) if r.is_real and r > 0]
    return _single(q, sols)


@h(r"^함수 f\(x\) = x\^n \(n은 2 이상의 자연수\)의 도함수가 f'\(x\) = kx\^(\d+) \(k는 상수\)일 때, k의 값을 구하시오\.$", "f=x^n, f'=kx^p → k")
def _p9(m, q):
    p = int(m.group(1))
    n = p + 1
    if n < 2:
        raise Unverified("n<2")
    return sp.Integer(n)


@h(r"^함수 f\(x\) = " + E + r"의 도함수 f'\(x\)에 x = (-?\d+)[을를] 대입한 값(?:으로 옳은 것은\?|을 구하시오\.)$", "도함수에 x=a 대입")
def _p10a(m, q):
    return D(P(m.group(1))).subs(X, int(m.group(2)))


@h(r"^함수 y = " + E + r"의 도함수 y'에 대하여 x = (-?\d+)일 때 y'의 값은\?$", "y'의 x=a에서 값")
def _p10b(m, q):
    return D(P(m.group(1))).subs(X, int(m.group(2)))


@h(r"^f\(x\) = " + E + r"일 때, 미분계수 f'\((-?\d+)\)[을를] 구하시오\.$", "미분계수 f'(a)")
def _p10c(m, q):
    return D(P(m.group(1))).subs(X, int(m.group(2)))


# ---------------------------------------------------------------- POLYNOMIAL-RULES
@h(r"^함수 f\(x\) = " + E + r"에 대하여 f'\((-?\d+)\)의 값이 (-?\d+)일 때, 상수 a의 값을 구하시오\.$", "f'(p)=v → 상수 a")
def _q1(m, q):
    f = P(m.group(1))
    a = sp.Symbol("a")
    sols = sp.solve(D(f).subs(X, int(m.group(2))) - int(m.group(3)), a)
    return _single(q, sols)




@h(r"^함수 f\(x\) = " + E + r"의 도함수 f'\(x\)의 상수항(?:을 구하시오|으로 옳은 것은\?)\.?$", "도함수의 상수항")
def _q2(m, q):
    return D(P(m.group(1))).subs(X, 0)


@h(r"^함수 g\(t\) = " + E + r"[을를] t에 대하여 미분한 도함수 g'\(t\)의 상수항을 구하시오\.$", "g(t) 도함수의 상수항")
def _q2b(m, q):
    g = P(m.group(1), {"t": T})
    return D(g, T).subs(T, 0)




@h(r"^함수 f\(x\) = ax\^2 \+ bx \(a, b는 상수\)에 대하여 f'\((-?\d+)\)의 값이 (-?\d+)이고 f'\((-?\d+)\)의 값이 (-?\d+)일 때, a의 값을 구하시오\.$", "f=ax^2+bx: 두 f' 조건 → a")
def _q3(m, q):
    a, b = sp.symbols("a b")
    f = a * X ** 2 + b * X
    sol = sp.solve([D(f).subs(X, int(m.group(1))) - int(m.group(2)), D(f).subs(X, int(m.group(3))) - int(m.group(4))], [a, b], dict=True)
    if len(sol) != 1:
        raise Unverified("연립해 %d" % len(sol))
    return sol[0][a]


@h(r"^두 함수 f\(x\) = " + E + r", g\(x\) = " + E + r"에 대하여 f'\((-?\d+)\) \+ g'\((-?\d+)\)의 값을 구하시오\.$", "두 함수 f'(a)+g'(a)")
def _q4(m, q):
    return D(P(m.group(1))).subs(X, int(m.group(3))) + D(P(m.group(2))).subs(X, int(m.group(4)))


@h(r"^두 함수 f\(x\) = " + E + r", g\(x\) = " + E + r"에 대하여 함수 h\(x\) = (-?\d+)f\(x\) - (-?\d+)g\(x\)의 x = (-?\d+)에서의 미분계수를 구하시오\.$", "h=αf-βg 의 x=a 미분계수")
def _q5(m, q):
    f, g = P(m.group(1)), P(m.group(2))
    a = int(m.group(5))
    return (int(m.group(3)) * D(f) - int(m.group(4)) * D(g)).subs(X, a)


@h(r"^함수 f\(x\) = x\^3 \+ ax\^2 \+ bx \(a, b는 상수\)에 대하여 방정식 f'\(x\) = 0의 두 실근이 (-?\d+), (-?\d+)일 때, 상수 a의 값을 구하시오\.$", "f'(x)=0 두 실근 → a")
def _q6(m, q):
    a, b = sp.symbols("a b")
    f = X ** 3 + a * X ** 2 + b * X
    r1, r2 = int(m.group(1)), int(m.group(2))
    sol = sp.solve([D(f).subs(X, r1), D(f).subs(X, r2)], [a, b], dict=True)
    return sol[0][a]


@h(r"^y = " + E + r"일 때, dy/dx의 모든 계수의 합을 구하시오\.$", "dy/dx 모든 계수의 합")
def _q7(m, q):
    return D(P(m.group(1))).subs(X, 1)  # 전개된 다항식의 계수합 = p(1)




@h(r"^두 함수 f\(x\) = " + E + r", g\(x\) = " + E + r"에 대하여 함수 y = f\(x\) \+ g\(x\)의 도함수의 모든 계수의 합을 구하시오\.$", "y=f+g 도함수의 모든 계수의 합")
def _q8(m, q):
    return D(P(m.group(1)) + P(m.group(2))).subs(X, 1)




@h(r"^함수 f\(x\) = " + E + r"에 대하여 f'\(a\)의 값이 (-?\d+)이 되도록 하는 양수 a의 값을 구하시오\.$", "f'(a)=v 되도록 하는 양수 a")
def _q9(m, q):
    f = P(m.group(1))
    a = sp.Symbol("a")
    return _single(q, [r for r in sp.solve(D(f).subs(X, a) - int(m.group(2)), a) if r.is_real and r > 0])


@h(r"^(?:함수 )?y = " + E + r"의 도함수의 모든 계수의 합으로 옳은 것은\?$", "도함수 모든 계수의 합(객관식)")
def _q10(m, q):
    return D(P(m.group(1))).subs(X, 1)


@h(r"^함수 f\(x\) = " + E + r"의 도함수 f'\(x\)의 모든 계수의 합을 구하시오\.$", "f' 모든 계수의 합")
def _q11(m, q):
    return D(P(m.group(1))).subs(X, 1)


@h(r"^두 함수 f\(x\), g\(x\)에 대하여 f'\((-?\d+)\)의 값이 (-?\d+), g'\(\1\)의 값이 (-?\d+)일 때, 함수 h\(x\) = (-?\d+)f\(x\) - (-?\d+)g\(x\)의 x = \1에서의 미분계수를 구하시오\.$", "f',g' 값 주어짐 → h 미분계수")
def _q12(m, q):
    return int(m.group(4)) * int(m.group(2)) - int(m.group(5)) * int(m.group(3))


@h(r"^함수 f\(x\) = " + E + r"의 도함수가 f'\(x\) = " + E + r"일 때, 상수 k의 값을 구하시오\.$", "f 도함수가 주어진 꼴 → 상수 k")
def _q13(m, q):
    f = P(m.group(1))
    g = P(m.group(2))
    k = sp.Symbol("k")
    sol = sp.solve(sp.Poly(sp.expand(D(f) - g), X).all_coeffs(), k, dict=True)
    return _single(q, [s[k] for s in sol])


@h(r"^함수 f\(x\) = " + E + r"에 대하여 g\(x\) = f\(x\) \+ (\d+)이?라 할 때, g'\((-?\d+)\) - f'\(\3\)의 값을 구하시오\.$", "g=f+c: g'(a)-f'(a)")
def _q14(m, q):
    f = P(m.group(1))
    a = int(m.group(3))
    g = f + int(m.group(2))
    return (D(g) - D(f)).subs(X, a)




# ---------------------------------------------------------------- TANGENT-LINE
def _slope_of_line(s):
    """'y = -52x - 158' 또는 'x + 8y = 9' 형태 직선의 기울기(수직선 제외)."""
    lhs, rhs = s.split("=")
    Y = sp.Symbol("y")
    e = P(lhs, {"y": Y}) - P(rhs, {"y": Y})
    sol = sp.solve(e, Y)
    if len(sol) != 1:
        raise Unverified("직선 기울기 파싱 실패")
    return sp.diff(sol[0], X)


@h(r"^곡선 y = " + E + r" 위의 점 \((-?\d+), (-?\d+)\)에서의 접선의 y절편을 구하시오\.$", "접선의 y절편(점 지정)")
def _t1(m, q):
    f = P(m.group(1))
    a = int(m.group(2))
    if not on_curve(f, a, int(m.group(3))):
        return result("mismatch", None, "점 (%s,%s)가 곡선 위에 없음 (f(%d)=%s)" % (m.group(2), m.group(3), a, f.subs(X, a)))
    return tangent_line(f, a)[1]


@h(r"^곡선 y = " + E + r" 위의 점 \((-?\d+), (-?\d+)\)에서의 접선이 y축과 만나는 점의 y좌표를 구하시오\.$", "접선이 y축과 만나는 점의 y좌표")
def _t1b(m, q):
    f = P(m.group(1))
    a = int(m.group(2))
    if not on_curve(f, a, int(m.group(3))):
        return result("mismatch", None, "점이 곡선 위에 없음")
    return tangent_line(f, a)[1]


@h(r"^곡선 y = " + E + r" 위의 점 \((-?\d+), (-?\d+)\)에서의 접선의 y절편은\?$", "접선의 y절편(객관식)")
def _t1c(m, q):
    f = P(m.group(1))
    a = int(m.group(2))
    if not on_curve(f, a, int(m.group(3))):
        return result("mismatch", None, "점이 곡선 위에 없음")
    return tangent_line(f, a)[1]


@h(r"^곡선 y = " + E + r" 위의 점 \((-?\d+), (-?\d+)\)에서의 접선의 기울기(?:를 구하시오\.|는\?)$", "접선의 기울기(점 지정)")
def _t2(m, q):
    f = P(m.group(1))
    a = int(m.group(2))
    if not on_curve(f, a, int(m.group(3))):
        return result("mismatch", None, "점이 곡선 위에 없음")
    return D(f).subs(X, a)


@h(r"^함수 f\(x\) = " + E + r"의 그래프 위의 점 \((-?\d+), f\(\2\)\)에서의 접선의 기울기를 구하시오\.$", "그래프 위 점 (a,f(a))의 접선 기울기")
def _t2b(m, q):
    return D(P(m.group(1))).subs(X, int(m.group(2)))


@h(r"^곡선 y = " + E + r"의 x좌표가 (-?\d+)인 점에서의 접선의 기울기(?:를 구하시오\.|로 옳은 것은\?)$", "x좌표 a인 점의 접선 기울기")
def _t3(m, q):
    return D(P(m.group(1))).subs(X, int(m.group(2)))


@h(r"^곡선 y = " + E + r" 위의 점 \(a, a\^3 \+ 6a\) \(a > 0\)에서의 접선의 기울기가 (-?\d+)일 때, a의 값은\?$", "(a,a^3+6a) 접선 기울기=v → a>0")
def _t4(m, q):
    f = P(m.group(1))
    a = sp.Symbol("a")
    if not same(f.subs(X, a), a ** 3 + 6 * a):
        return result("mismatch", None, "점 (a,a^3+6a)가 곡선 위에 없음")
    return _single(q, [r for r in sp.solve(D(f).subs(X, a) - int(m.group(2)), a) if r.is_real and r > 0])


@h(r"^곡선 y = " + E + r" 위의 점 중 y좌표가 (-?\d+)인 점은 하나뿐이다\. 이 점에서의 접선의 기울기를 구하시오\.$", "y좌표가 v인 점(하나뿐) 접선 기울기")
def _t5(m, q):
    prem("발문 '하나뿐' 주장(실근 개수=1)")
    f = P(m.group(1))
    rts = real_roots_set(f - int(m.group(2)))
    if len(rts) != 1:
        return result("mismatch", None, "'하나뿐' 주장 위배: 해 %d개" % len(rts))
    return D(f).subs(X, rts[0])


@h(r"^곡선 y = " + E + r" 위의 점 \((-?\d+), (-?\d+)\)에서의 접선의 방정식을 y = g\(x\)라 할 때, g\((-?\d+)\)의 값(?:을 구하시오\.|은\?)$", "접선 y=g(x) → g(c)")
def _t6(m, q):
    f = P(m.group(1))
    a = int(m.group(2))
    if not on_curve(f, a, int(m.group(3))):
        return result("mismatch", None, "점이 곡선 위에 없음")
    s, b = tangent_line(f, a)
    return s * int(m.group(4)) + b


@h(r"^곡선 y = " + E + r" 위의 x좌표가 (-?\d+)인 점에서의 접선의 기울기가 (-?\d+)일 때, 상수 (\w)의 값을 구하시오\.$", "x좌표 a 접선 기울기=v → 상수")
def _t7(m, q):
    f = P(m.group(1))
    c = sp.Symbol(m.group(4))
    return _single(q, sp.solve(D(f).subs(X, int(m.group(2))) - int(m.group(3)), c))


@h(r"^곡선 y = " + E + r" 위의 x좌표가 a인 점에서의 접선의 기울기가 (-?\d+)일 때, 양수 a의 값을 구하시오\.$", "x좌표 a 접선 기울기=v → 양수 a")
def _t8(m, q):
    f = P(m.group(1))
    a = sp.Symbol("a")
    return _single(q, [r for r in sp.solve(D(f).subs(X, a) - int(m.group(2)), a) if r.is_real and r > 0])


@h(r"^곡선 y = " + E + r" 위의 x좌표가 (-?\d+)인 점과 (-?\d+)인 점에서의 접선의 기울기의 합을 구하시오\.$", "두 점 접선 기울기의 합")
def _t9(m, q):
    d = D(P(m.group(1)))
    return d.subs(X, int(m.group(2))) + d.subs(X, int(m.group(3)))


@h(r"^곡선 y = " + E + r" 위의 x좌표가 (-?\d+)인 점에서의 접선의 기울기에서 x좌표가 (-?\d+)인 점에서의 접선의 기울기를 뺀 값을 구하시오\.$", "접선 기울기의 차(앞-뒤)")
def _t10(m, q):
    d = D(P(m.group(1)))
    return d.subs(X, int(m.group(2))) - d.subs(X, int(m.group(3)))


@h(r"^곡선 y = " + E + r" 위의 점 \((-?\d+), (-?\d+)\)에서의 접선의 방정식을 y = mx \+ n이라 할 때, m \+ n의 값을 구하시오\.$", "접선 y=mx+n → m+n")
def _t11(m, q):
    f = P(m.group(1))
    a = int(m.group(2))
    if not on_curve(f, a, int(m.group(3))):
        return result("mismatch", None, "점이 곡선 위에 없음")
    s, b = tangent_line(f, a)
    return s + b


@h(r"^함수 f\(x\) = " + E + r"에 대하여 곡선 y = f\(x\) 위의 점 \(a, f\(a\)\)에서의 접선이 직선 " + E + r"에 (평행|수직)(?:할|일) 때, 양수 a의 값을 구하시오\.$", "접선이 직선에 평행/수직 → 양수 a")
def _t12(m, q):
    f = P(m.group(1))
    sl = _slope_of_line(m.group(2))
    a = sp.Symbol("a")
    if m.group(3) == "평행":
        eq = D(f).subs(X, a) - sl
    else:
        eq = D(f).subs(X, a) * sl + 1
    return _single(q, [r for r in sp.solve(eq, a) if r.is_real and r > 0])


@h(r"^곡선 y = " + E + r" \(c는 상수\) 위의 x좌표가 (-?\d+)인 점에서의 접선의 y절편이 (-?\d+)일 때, c의 값을 구하시오\.$", "접선 y절편=v → 상수 c")
def _t13(m, q):
    c = sp.Symbol("c")
    f = P(m.group(1))
    a = int(m.group(2))
    s, b = tangent_line(f, a)
    return _single(q, sp.solve(b - int(m.group(3)), c))


@h(r"^함수 f\(x\) = " + E + r"에 대하여 곡선 y = f\(x\) 위의 점 \(a, f\(a\)\)에서의 접선이 원점을 지날 때, 양수 a의 값을 구하시오\.$", "접선이 원점 통과 → 양수 a")
def _t14(m, q):
    f = P(m.group(1))
    a = sp.Symbol("a")
    eq = f.subs(X, a) - a * D(f).subs(X, a)
    return _single(q, [r for r in sp.solve(eq, a) if r.is_real and r > 0])


@h(r"^곡선 y = " + E + r" 위의 x좌표가 (-?\d+)인 점에서의 접선과 평행한 접선을 갖는 또 다른 점의 x좌표를 b라 할 때, b의 값을 구하시오\.$", "평행한 접선을 갖는 또 다른 점의 x좌표")
def _t15(m, q):
    f = P(m.group(1))
    a0 = int(m.group(2))
    b = sp.Symbol("b")
    sols = [r for r in sp.solve(D(f).subs(X, b) - D(f).subs(X, a0), b) if r.is_real and r != a0]
    return _single(q, sols)


@h(r"^곡선 y = " + E + r"(?:이|가) x축과 만나는 점 중 x좌표가 가장 큰 점에서의 접선의 기울기(?:를 구하시오\.)$", "x축과 만나는 점 중 가장 큰 x좌표의 접선 기울기")
def _t16(m, q):
    f = P(m.group(1))
    return D(f).subs(X, real_roots_set(f)[-1])


@h(r"^곡선 y = " + E + r" 위의 점 중 접선의 기울기가 (-?\d+)(?:이|가) 되는 점은 하나뿐이다\. 그 점의 x좌표를 구하시오\.$", "접선 기울기=v 인 점(하나뿐)의 x좌표")
def _t17(m, q):
    prem("발문 '하나뿐' 주장(실근 개수=1)")
    f = P(m.group(1))
    rts = real_roots_set(D(f) - int(m.group(2)))
    if len(set(rts)) != 1:
        return result("mismatch", None, "'하나뿐' 주장 위배: 해 %d개" % len(set(rts)))
    return rts[0]


@h(r"^직선 y = (\d+)x \+ k가 곡선 y = " + E + r" 위의 x좌표가 양수인 점에서 이 곡선에 접할 때, 상수 k의 값을 구하시오\.$", "직선이 곡선에 접함(x>0) → k")
def _t18(m, q):
    f = P(m.group(2))
    a = sp.Symbol("a")
    sols = [r for r in sp.solve(D(f).subs(X, a) - int(m.group(1)), a) if r.is_real and r > 0]
    if len(sols) != 1:
        return _single(q, [])
    r0 = sols[0]
    return sp.nsimplify(f.subs(X, r0) - int(m.group(1)) * r0)


@h(r"^곡선 y = " + E + r" 위의 점 \((-?\d+), (-?\d+)\)에서의 접선이 이 곡선과 만나는 점 중 접점이 아닌 점의 x좌표를 구하시오\.$", "접선이 곡선과 다시 만나는 점의 x좌표")
def _t19(m, q):
    f = P(m.group(1))
    a = int(m.group(2))
    if not on_curve(f, a, int(m.group(3))):
        return result("mismatch", None, "점이 곡선 위에 없음")
    s, b = tangent_line(f, a)
    rts = [r for r in real_roots_set(f - (s * X + b)) if r != a]
    return _single(q, rts)


@h(r"^점 \((-?\d+), (-?\d+)\)에서 곡선 y = " + E + r"에 그은 접선은 하나뿐이다\. 이 접선의 기울기를 구하시오\.$", "외부점에서 곡선에 그은 접선(하나뿐)의 기울기")
def _t20(m, q):
    prem("발문 '하나뿐' 주장(접점 개수=1)")
    px, py = int(m.group(1)), int(m.group(2))
    f = P(m.group(3))
    a = sp.Symbol("a")
    # 접점 a: f(a) + f'(a)(px-a) = py
    eq = f.subs(X, a) + D(f).subs(X, a) * (px - a) - py
    rts = real_roots_set(eq, a) if False else sorted(set(sp.Poly(eq, a).real_roots()), key=float)
    if len(rts) != 1:
        return result("mismatch", None, "'하나뿐' 주장 위배: 접점 %d개" % len(rts))
    return D(f).subs(X, rts[0])


@h(r"^곡선 y = " + E + r" 위의 점 \((-?\d+), (-?\d+)\)에서의 접선과 x축, y축으로 둘러싸인 삼각형의 넓이를 구하시오\.$", "접선과 x축·y축 삼각형 넓이")
def _t21(m, q):
    f = P(m.group(1))
    a = int(m.group(2))
    if not on_curve(f, a, int(m.group(3))):
        return result("mismatch", None, "점이 곡선 위에 없음")
    s, b = tangent_line(f, a)
    if s == 0 or b == 0:
        return result("unverified", None, "삼각형 퇴화")
    xi = -b / s
    return sp.Abs(xi * b) / 2


@h(r"^곡선 y = " + E + r" 위의 x좌표가 (-?\d+)인 점에서의 접선의 y절편이 0일 때, 상수 p의 값을 구하시오\.$", "접선 y절편=0 → 상수 p")
def _t22(m, q):
    f = P(m.group(1))
    p = sp.Symbol("p")
    s, b = tangent_line(f, int(m.group(2)))
    return _single(q, sp.solve(b, p))


@h(r"^곡선 y = x\^2 \+ px \+ q가 곡선 y = " + E + r"와 x = (-?\d+)인 점에서 접할 때, 상수 q의 값을 구하시오\. \(단, p, q는 상수이다\.\)$", "두 곡선이 x=a에서 접함 → q")
def _t23(m, q):
    p, qq = sp.symbols("p q")
    f = X ** 2 + p * X + qq
    g = P(m.group(1))
    a = int(m.group(2))
    sol = sp.solve([f.subs(X, a) - g.subs(X, a), D(f).subs(X, a) - D(g).subs(X, a)], [p, qq], dict=True)
    if len(sol) != 1:
        raise Unverified("연립해 %d" % len(sol))
    return sol[0][qq]


@h(r"^함수 f\(x\) = " + E + r"에 대하여 곡선 y = f\(x\) 위의 점 \(a, f\(a\)\)에서의 접선이 점 \((-?\d+), (-?\d+)\)[을를] 지날 때, 양수 a의 값을 구하시오\.$", "접선이 점을 지남 → 양수 a")
def _t24(m, q):
    f = P(m.group(1))
    a = sp.Symbol("a")
    px, py = int(m.group(2)), int(m.group(3))
    eq = f.subs(X, a) + D(f).subs(X, a) * (px - a) - py
    return _single(q, [r for r in sp.Poly(eq, a).real_roots() if r > 0])


# ---------------------------------------------------------------- MEAN-VALUE-THEOREM

def _mvt_c(f, lo, hi):
    """f'(c) = (f(hi)-f(lo))/(hi-lo) 의 해 중 열린구간 (lo,hi) 안의 해, 닫힌구간 경계 해 포함 여부."""
    sl = sp.nsimplify((f.subs(X, hi) - f.subs(X, lo)) / (hi - lo))
    rts = real_roots_set(D(f) - sl)
    inside = [r for r in rts if lo < r < hi]
    boundary = [r for r in rts if r in (lo, hi)]
    return rts, inside, boundary


def _mvt_result(q, f, lo, hi, kind="값"):
    rts, inside, bd = _mvt_c(f, lo, hi)
    probe("평균값 정리 c: 열린구간(통상) vs 닫힌구간 포함 시 해 개수", len(inside), len(inside) + len(bd))
    if kind == "개수":
        return sp.Integer(len(inside)) if not bd else result("ambiguous", None, "경계 해 포함 여부로 개수가 갈림")
    if len(inside) != 1:
        return _single(q, inside)
    return inside[0]


@h(r"^함수 f\(x\) = " + E + r"에 대하여 (?:닫힌구간|열린구간) \[?\(?(-?\d+), (-?\d+)[\])]에서 평균값 정리(?:를 만족시키는 (?:상수 |실수 )?c의 값(?:을 구하시오\.(?: \(단, -?\d+ < c < -?\d+\))?|은\?)|의 결론을 만족시키는 c의 값으로 옳은 것은\?)$", "평균값 정리 c의 값")
def _m1(m, q):
    return _mvt_result(q, P(m.group(1)), int(m.group(2)), int(m.group(3)))




@h(r"^함수 f\(x\) = x\^3 \+ kx\^2에 대하여 닫힌구간 \[(-?\d+), (-?\d+)\]에서 평균값 정리를 만족시키는 c의 값이 (-?\d+/?\d*)일 때, 상수 k의 값을 구하시오\.$", "MVT c 주어짐 → k")
def _m3(m, q):
    k = sp.Symbol("k")
    f = X ** 3 + k * X ** 2
    lo, hi = int(m.group(1)), int(m.group(2))
    c = P(m.group(3))
    sl = (f.subs(X, hi) - f.subs(X, lo)) / (hi - lo)
    sols = [s for s in sp.solve(D(f).subs(X, c) - sl, k) if lo < c < hi]
    return _single(q, sols)


@h(r"^함수 f\(x\) = " + E + r"의 그래프 위의 x좌표가 (-?\d+), (-?\d+)인 두 점을 각각 A, B라 하자\. 열린구간 \(\2, \3\)에서 곡선 y = f\(x\) 위의 점 P\(c, f\(c\)\)에서의 접선이 직선 AB와 평행할 때, c의 값을 구하시오\.$", "AB와 평행한 접선의 접점 c")
def _m4(m, q):
    return _mvt_result(q, P(m.group(1)), int(m.group(2)), int(m.group(3)))


@h(r"^함수 f\(x\) = " + E + r"에 대하여 곡선 y = f\(x\) 위의 두 점 A\((-?\d+), (-?\d+)\), B\((-?\d+), (-?\d+)\)이 있다\. 열린구간 \(\2, \4\)에서 곡선 위의 점 P\(c, f\(c\)\)에서의 접선이 직선 AB와 평행할 때, c의 값을 구하시오\.$", "A,B 지정 AB와 평행한 접선의 c")
def _m5(m, q):
    f = P(m.group(1))
    a1, y1, b1, y2 = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
    if not (on_curve(f, a1, y1) and on_curve(f, b1, y2)):
        return result("mismatch", None, "A 또는 B가 곡선 위에 없음")
    return _mvt_result(q, f, a1, b1)


@h(r"^함수 f\(x\) = " + E + r"에 대하여 f'\(x\) = \(f\((-?\d+)\) - f\((-?\d+)\)\)/\(\2 - \3\)을 만족시키는 실수 x는 두 개이다\. 이 중 열린구간 \(\3, \2\)에 속하는 것을 c라 할 때, c의 값을 구하시오\.$", "f'(x)=기울기 해 2개 중 열린구간 속하는 c")
def _m6(m, q):
    prem("발문 '실수 x는 두 개' 주장")
    f = P(m.group(1))
    hi, lo = int(m.group(2)), int(m.group(3))
    rts, inside, bd = _mvt_c(f, lo, hi)
    if len(rts) != 2:
        return result("mismatch", None, "'두 개' 주장 위배: 실근 %d개" % len(rts))
    return _single(q, inside)


@h(r"^닫힌구간 \[(-?\d+), (-?\d+)\]에서 함수 f\(x\) = " + E + r"의 평균변화율과 x = c에서의 미분계수가 같아지는 c \(\1 < c < \2\)의 값을 구하시오\.$", "평균변화율=미분계수 c")
def _m7(m, q):
    return _mvt_result(q, P(m.group(3)), int(m.group(1)), int(m.group(2)))




@h(r"^함수 f\(x\) = " + E + r"에 대하여 f\((-?\d+)\) = f\((-?\d+)\)이다\. 닫힌구간 \[\2, \3\]에서 롤의 정리를 만족시키는 c의 값을 구하시오\.$", "롤의 정리 c (f(a)=f(b) 전제 검증)")
def _m9(m, q):
    prem('롤의 정리 전제 f(a)=f(b)')
    f = P(m.group(1))
    a, b = int(m.group(2)), int(m.group(3))
    if not same(f.subs(X, a), f.subs(X, b)):
        return result("mismatch", None, "전제 f(%d)=f(%d) 불성립" % (a, b))
    rts = [r for r in real_roots_set(D(f)) if a < r < b]
    return _single(q, rts)


@h(r"^직선 위를 움직이는 점 P의 시각 t에서의 위치가 x\(t\) = " + E + r"일 때, 시각 t = (-?\d+)부터 t = (-?\d+)까지의 평균속도와 순간속도가 같아지는 시각 t = c \(\2 < c < \3\)의 값을 구하시오\.$", "평균속도=순간속도 시각 c")
def _m10(m, q):
    f = P(m.group(1), {"t": X})
    return _mvt_result(q, f, int(m.group(2)), int(m.group(3)))


@h(r"^삼차함수 f\(x\) = " + E + r"에 대하여 f\((-?\d+)\) = f\((-?\d+)\)이므로 롤의 정리에 의하여 f'\(c\) = 0인 c가 열린구간 \(\2, \3\)에 존재한다\. 이 c의 값을 구하시오\.$", "롤의 정리 c(삼차)")
def _m11(m, q):
    prem('롤의 정리 전제 f(a)=f(b)')
    f = P(m.group(1))
    a, b = int(m.group(2)), int(m.group(3))
    if not same(f.subs(X, a), f.subs(X, b)):
        return result("mismatch", None, "전제 f(a)=f(b) 불성립")
    return _single(q, [r for r in real_roots_set(D(f)) if a < r < b])


@h(r"^함수 f\(x\)는 모든 실수 x에서 미분가능하고 f'\(x\) (≥|≤) (-?\d+)이다\. f\((-?\d+)\) = (-?\d+)일 때, f\((-?\d+)\)의 값이 될 수 있는 가장 (큰|작은) 값을 구하시오\.$", "f' 한쪽 경계 → f(b)의 최대/최소")
def _m12(m, q):
    op, bound = m.group(1), int(m.group(2))
    a, fa, b = int(m.group(3)), int(m.group(4)), int(m.group(5))
    want = m.group(6)
    d = b - a
    # f(b) = f(a) + ∫f' ; f' >= B 이면 f(b) >= f(a)+B*d (d>0) 또는 <= (d<0)
    # 가능한 값의 집합은 닫힌 반직선(선형함수로 경계 달성)
    val = fa + bound * d
    # f'>=B & d>0 → f(b) ∈ [val, ∞) : 최소만 존재 / f'<=B & d>0 → (-∞, val] : 최대만 존재
    if op == "≥":
        lower_exists = d > 0
    else:
        lower_exists = d < 0
    if want == "작은" and lower_exists:
        return sp.Integer(val)
    if want == "큰" and not lower_exists:
        return sp.Integer(val)
    return result("mismatch", None, "요구한 극값이 존재하지 않음(상/하한 방향 불일치)")


@h(r"^함수 f\(x\)는 모든 실수 x에서 미분가능하고 (-?\d+) ≤ f'\(x\) ≤ (-?\d+)이다\. f\((-?\d+)\) = (-?\d+)일 때, f\((-?\d+)\)의 값이 될 수 있는 가장 큰 값과 가장 작은 값의 합을 구하시오\.$", "f' 양쪽 경계 → f(b) 최대+최소")
def _m13(m, q):
    lo, hi = int(m.group(1)), int(m.group(2))
    a, fa, b = int(m.group(3)), int(m.group(4)), int(m.group(5))
    d = b - a
    vals = [fa + lo * d, fa + hi * d]
    return sp.Integer(sum(vals))


@h(r"^함수 f는 닫힌구간 \[(-?\d+), (-?\d+)\]에서 연속이고 열린구간 \(\1, \2\)에서 미분가능하며 f\(\1\) = (-?\d+), f\(\2\) = (-?\d+)이다\. 평균값 정리에 의하여 f'\(c\) = k인 c가 이 열린구간에 존재할 때, k의 값을 구하시오\.$", "MVT: f(a),f(b) 주어짐 → k")
def _m14(m, q):
    a, b, fa, fb = (int(m.group(i)) for i in range(1, 5))
    return sp.Rational(fb - fa, b - a)


@h(r"^함수 f\(x\) = " + E + r"에 대하여 닫힌구간 \[(-?\d+), (-?\d+)\]에서 평균값 정리를 만족시키는 실수 c의 개수를 구하시오\.$", "MVT 만족하는 실수 c의 개수")
def _m15(m, q):
    f = P(m.group(1))
    return _mvt_result(q, f, int(m.group(2)), int(m.group(3)), "개수")


@h(r"^곡선 y = " + E + r" 위의 두 점 A\((-?\d+), (-?\d+)\), B\((-?\d+), (-?\d+)\)에 대하여, \2 < x < \4인 범위에서 접선이 직선 AB와 평행한 점의 개수를 구하시오\.$", "AB와 평행한 접선을 갖는 점의 개수")
def _m16(m, q):
    f = P(m.group(1))
    a1, y1, b1, y2 = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
    if not (on_curve(f, a1, y1) and on_curve(f, b1, y2)):
        return result("mismatch", None, "A 또는 B가 곡선 위에 없음")
    return _mvt_result(q, f, a1, b1, "개수")


@h(r"^함수 f\(x\) = " + E + r"에 대하여 곡선 y = f\(x\) 위의 두 점 A\((-?\d+), (-?\d+)\), B\((-?\d+), (-?\d+)\) 사이의 곡선 위에서 직선 AB와 평행한 접선을 갖는 점의 x좌표는\?$", "A,B 사이 AB와 평행한 접선의 접점 x좌표")
def _m17(m, q):
    f = P(m.group(1))
    a1, y1, b1, y2 = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
    if not (on_curve(f, a1, y1) and on_curve(f, b1, y2)):
        return result("mismatch", None, "A 또는 B가 곡선 위에 없음")
    return _mvt_result(q, f, a1, b1)


@h(r"^함수 f\(x\) = " + E + r"에 대하여 f\((-?\d+)\)과 f\((-?\d+)\)의 값은 서로 다르다\. 구간 \[\2, \3\]에서 평균값 정리를 만족시키는 c를 구하려 할 때, 올바른 방정식을 세워 구한 c의 값은\?$", "MVT c(오개념 유발 문항)")
def _m18(m, q):
    prem("발문 'f(a)와 f(b)는 서로 다르다' 전제")
    f = P(m.group(1))
    a, b = int(m.group(2)), int(m.group(3))
    if same(f.subs(X, a), f.subs(X, b)):
        return result("mismatch", None, "전제 '서로 다르다' 위배")
    return _mvt_result(q, f, a, b)


@h(r"^수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x\(t\) = " + E + r"이다\. 0 < t < (\d+)에서 점 P의 순간속도가 t = 0부터 t = \2까지의 평균속도와 같아지는 (시각을 t = c라 할 때, c의 값을 구하시오|시각의 개수를 구하시오)\.$", "순간속도=평균속도 시각/개수")
def _m19(m, q):
    f = P(m.group(1), {"t": X})
    hi = int(m.group(2))
    kind = "개수" if "개수" in m.group(3) else "값"
    return _mvt_result(q, f, 0, hi, kind)


@h(r"^수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x\(t\) = " + E + r"일 때, 0 < t < (\d+)에서 점 P의 순간속도가 t = 0부터 t = \2까지의 평균속도와 같아지는 시각의 개수를 구하시오\.$", "순간속도=평균속도 시각의 개수")
def _m19b(m, q):
    return _mvt_result(q, P(m.group(1), {"t": X}), 0, int(m.group(2)), "개수")


@h(r"^직선 위를 움직이는 점의 시각 t에서의 위치가 x\(t\) = " + E + r"일 때, t = (-?\d+)부터 t = (-?\d+)까지의 평균속도와 같은 순간속도를 갖는 시각 t = c의 값은\? \(단, \2 < c < \3\)$", "평균속도와 같은 순간속도 시각 c(객관식)")
def _m20(m, q):
    return _mvt_result(q, P(m.group(1), {"t": X}), int(m.group(2)), int(m.group(3)))




@h(r"^함수 f\(x\) = " + E + r"에 대하여 방정식 f'\(x\) = \(f\((-?\d+)\) - f\((-?\d+)\)\)/\(\2 - \3\)의 두 실근 중 열린구간 \(\3, \2\)에 속하지 않는 근을 구하시오\.$", "MVT 방정식 두 실근 중 구간 밖 근")
def _m21(m, q):
    prem("발문 '두 실근' 주장")
    f = P(m.group(1))
    hi, lo = int(m.group(2)), int(m.group(3))
    rts, inside, bd = _mvt_c(f, lo, hi)
    outside = [r for r in rts if r not in inside]
    if len(rts) != 2:
        return result("mismatch", None, "'두 실근' 주장 위배: %d개" % len(rts))
    return _single(q, outside)


@h(r"^함수 f\(x\) = x\^3 \+ kx\^2에 대하여 곡선 y = f\(x\) 위의 두 점 \((-?\d+), f\(\1\)\), \((-?\d+), f\(\2\)\)을 잇는 직선과 평행한 접선의 접점의 x좌표가 (-?\d+/?\d*)일 때, 상수 k의 값을 구하시오\.$", "AB 평행 접선의 접점 x좌표 주어짐 → k")
def _m22(m, q):
    k = sp.Symbol("k")
    f = X ** 3 + k * X ** 2
    lo, hi = int(m.group(1)), int(m.group(2))
    c = P(m.group(3))
    sl = (f.subs(X, hi) - f.subs(X, lo)) / (hi - lo)
    sols = [s for s in sp.solve(D(f).subs(X, c) - sl, k) if lo < c < hi]
    return _single(q, sols)


@h(r"^함수 f\(x\) = " + E + r"에 대하여 닫힌구간 \[1, k\] \(k > 1\)에서 평균값 정리를 만족시키는 c의 값이 (-?\d+/?\d*)일 때, k의 값을 구하시오\.$", "MVT c 주어짐 → k (구간 [1,k])")
def _m23(m, q):
    f = P(m.group(1))
    k = sp.Symbol("k")
    c = P(m.group(2))
    sl = (f.subs(X, k) - f.subs(X, 1)) / (k - 1)
    sols = [s for s in sp.solve(sp.together(D(f).subs(X, c) - sl), k) if s.is_real and s > 1 and 1 < c < s]
    return _single(q, sols)


@h(r"^함수 f\(x\) = " + E + r"에 대하여 구간 \[a, 0\] \(a < 0\)에서 평균값 정리를 만족시키는 c의 값이 (-?\d+/?\d*)일 때, a의 값을 구하시오\.$", "MVT c 주어짐 → a (구간 [a,0])")
def _m24(m, q):
    f = P(m.group(1))
    a = sp.Symbol("a")
    c = P(m.group(2))
    sl = (f.subs(X, 0) - f.subs(X, a)) / (0 - a)
    sols = [s for s in sp.solve(sp.together(D(f).subs(X, c) - sl), a) if s.is_real and s < 0 and s < c < 0]
    return _single(q, sols)


@h(r"^자동차가 출발한 지 t시간 후의 이동 거리가 s\(t\) = " + E + r" \(km\)이다\. (출발 후 (\d+)시간부터 (\d+)시간까지|출발 시각부터 (\d+)시간 후까지)의 평균 속도와 순간 속도가 같아지는 시각 t = c \((\d+) < c < (\d+)\)의 값을 구하시오\.$", "자동차 평균속도=순간속도 시각 c")
def _m25(m, q):
    prem('발문 구간과 괄호 구간 일치')
    f = P(m.group(1), {"t": X})
    if m.group(3):
        lo, hi = int(m.group(3)), int(m.group(4))
    else:
        lo, hi = 0, int(m.group(5))
    r = _mvt_result(q, f, lo, hi)
    # 발문 괄호 구간 일치 확인
    if (int(m.group(6)), int(m.group(7))) != (lo, hi):
        return result("mismatch", None, "발문 구간과 괄호 구간 불일치")
    return r


@h(r"^함수 f\(x\) = x\^3 \+ kx\^2 \+ (-?\d+)x \+ (-?\d+)(?:이|가) 닫힌구간 \[(-?\d+), (-?\d+)\]에서 롤의 정리의 가정을 만족시키도록 상수 k의 값을 정할 때, 롤의 정리를 만족시키는 c의 값을 구하시오\.$", "롤의 정리 가정 만족 k → c")
def _m26(m, q):
    k = sp.Symbol("k")
    f = X ** 3 + k * X ** 2 + int(m.group(1)) * X + int(m.group(2))
    a, b = int(m.group(3)), int(m.group(4))
    ks = sp.solve(f.subs(X, a) - f.subs(X, b), k)
    if len(ks) != 1:
        raise Unverified("k 해 %d" % len(ks))
    g = f.subs(k, ks[0])
    return _single(q, [r for r in real_roots_set(D(g)) if a < r < b])


# ---------------------------------------------------------------- GRAPH-SHAPE
_FDEF = r"(?:삼차함수|사차함수|함수|곡선) (?:f\(x\)|y) = "


def _ext_xs(f, kind):
    info = crit_info(f)
    if kind == "any":
        CUR["alt_xs"] = [r for r, k, v in info]
        return [r for r, k, v in info if k in ("max", "min")]
    return [r for r, k, v in info if k == kind]


def _pick_core(xs, pick):
    xs = sorted(xs, key=float)
    if not xs:
        return None
    if pick == "큰":
        return xs[-1]
    if pick == "작은":
        return xs[0]
    return xs[0] if len(xs) == 1 else None


def _pick(q, xs, pick):
    alt_xs = CUR.pop("alt_xs", None)
    xs = sorted(xs, key=float)
    if alt_xs is not None:
        pv, av = _pick_core(xs, pick), _pick_core(alt_xs, pick)
        if pv is not None and av is not None:
            probe("극값 x좌표: 부호변화 점만(통상) vs f'=0 근 전부", pv, av)
        elif pv is not None and av is None:
            probe("극값 x좌표: 부호변화 점만(통상) vs f'=0 근 전부", pv, None)
    if not xs:
        return result("mismatch", None, "해당 극점 없음")
    if pick == "큰":
        return xs[-1]
    if pick == "작은":
        return xs[0]
    if len(xs) != 1:
        return amb(row_stored(q), xs, "극점 %d개인데 단일 답 요구" % len(xs))
    return xs[0]


@h(r"^" + _FDEF + E + r"(?:이|가) 극값을 갖는 x좌표(?:는\?|를 구하시오\.| 중 (큰|작은) 값을 구하시오\.)$", "극값을 갖는 x좌표")
def _g1(m, q):
    return _pick(q, _ext_xs(P(m.group(1)), "any"), m.group(2))


@h(r"^" + _FDEF + E + r"(?:에서 증가·감소가 바뀌는 점의 x좌표는\?|의 증가·감소가 바뀌는 점의 x좌표 중 (큰|작은) 값을 구하시오\.)$", "증가·감소가 바뀌는 점의 x좌표")
def _g2(m, q):
    return _pick(q, _ext_xs(P(m.group(1)), "any"), m.group(2))


@h(r"^" + _FDEF + E + r"(?:이|가) 극(소|대)가 되는 x좌표(?:를 구하시오\.| 중 (큰|작은) 값을 구하시오\.)$", "극소/극대가 되는 x좌표")
def _g3(m, q):
    return _pick(q, _ext_xs(P(m.group(1)), "min" if m.group(2) == "소" else "max"), m.group(3))


@h(r"^" + _FDEF + E + r"(?:이|가) (증가하다가 감소|감소하다가 증가)로 바뀌는 점의 x좌표를 구하시오\.$", "증가→감소/감소→증가 전환점")
def _g4(m, q):
    return _pick(q, _ext_xs(P(m.group(1)), "max" if m.group(2).startswith("증가") else "min"), None)


@h(r"^사차함수 f\(x\) = " + E + r"의 그래프 위의 점 \(a, f\(a\)\)에서 함수 f\(x\)가 극값을 가질 때, 이 점의 x좌표 a의 값은\?$", "그래프 위 점에서 극값 → a")
def _g5(m, q):
    return _pick(q, _ext_xs(P(m.group(1)), "any"), None)


@h(r"^방정식 f'\(x\) = 0의 해 중에서 함수 f\(x\) = " + E + r"(?:이|가) 극값을 갖는 x좌표는\?$", "f'=0의 해 중 극값을 갖는 x좌표")
def _g6(m, q):
    return _pick(q, _ext_xs(P(m.group(1)), "any"), None)


def _int_range(q, f, want, expect_word):
    prem("'정수는 하나뿐' 주장(열린/닫힌 양쪽)")
    """증가(want=+1)/감소(-1) 구간에 속하는 정수가 하나뿐이라는 발문 검증."""
    ivs = intervals_sign(D(f), want)
    op, cl = ints_in(ivs, False), ints_in(ivs, True)
    probe("증가/감소 구간 속 정수: 열린구간 vs 닫힌구간", len(op), len(cl))
    if len(op) == 1 and op == cl:
        return sp.Integer(next(iter(op)))
    if len(op) == 1 or len(cl) == 1:
        return result("ambiguous", sorted(cl | op), "열린/닫힌 구간 해석에 따라 정수 집합이 다름 open=%s closed=%s" % (sorted(op), sorted(cl)))
    return result("mismatch", None, "'정수는 하나뿐' 주장 위배: open=%s closed=%s" % (sorted(op), sorted(cl)))


@h(r"^함수 f\(x\) = " + E + r"(?:이|가) (감소|증가)하는 x의 값의 범위에 속하는 정수는 하나뿐이다\. 그 정수를 구하시오\.$", "감소/증가하는 x 범위의 정수")
def _g7(m, q):
    return _int_range(q, P(m.group(1)), -1 if m.group(2) == "감소" else 1, m.group(2))


@h(r"^곡선 y = " + E + r"에서 x의 값이 커질 때 y의 값이 작아지는 x의 값의 범위에 속하는 정수는 하나뿐이다\. 그 정수를 구하시오\.$", "x 커질 때 y 작아지는 범위의 정수")
def _g8(m, q):
    return _int_range(q, P(m.group(1)), -1, "감소")


def _param_syms(f):
    return sorted([s for s in f.free_symbols if s != X], key=str)


def _is_ext(f, p, kind):
    """x=p 가 kind('max'/'min'/'any') 극점인가(f' 부호 변화)."""
    d = D(f)
    rts = real_roots_set(d)
    if p not in rts:
        return False
    i = rts.index(p)
    lo = (rts[i - 1] + p) / 2 if i > 0 else p - 1
    hi = (p + rts[i + 1]) / 2 if i + 1 < len(rts) else p + 1
    sl, sr = sign_at(d, lo), sign_at(d, hi)
    k = "max" if (sl > 0 and sr < 0) else ("min" if (sl < 0 and sr > 0) else "none")
    return k == kind if kind != "any" else k in ("max", "min")



@h(r"^" + _FDEF + E + r"(?:이|가) x = (-?\d+)에서 극(솟|댓)값 (-?\d+)[을를] 가질 때, 상수 (\w)의 값을 구하시오\. \(단, [a-z], [a-z]는 상수이다\.\)$", "x=p에서 극솟/극댓값 v → 상수(2개 미지수)")
def _g9(m, q):
    f = P(m.group(1))
    p, kind, v, tgt = int(m.group(2)), ("min" if m.group(3) == "솟" else "max"), int(m.group(4)), m.group(5)
    syms = _param_syms(f)
    sols = sp.solve([D(f).subs(X, p), f.subs(X, p) - v], syms, dict=True)
    good = []
    for s in sols:
        g = f.subs(s)
        if _is_ext(g, sp.Integer(p), kind):
            good.append(s[sp.Symbol(tgt)])
    if len(sols) != len(good):
        pass
    return _single(q, good) if len(good) == 1 else (_single(q, good) if good else result("mismatch", None, "극%s값 조건을 만족하는 해 없음(극대/극소 구분 불일치)" % m.group(3)))


@h(r"^함수 y = " + E + r"는 x = (-?\d+)에서 극값을 갖는다\. 이 함수의 극(솟|댓)값이 (-?\d+)일 때, 상수 (\w)의 값을 구하시오\. \(단, a는 상수이다\.\)$", "x=p에서 극값, 극솟값=v → 상수 k")
def _g10(m, q):
    f = P(m.group(1))
    p = int(m.group(2))
    kind = "min" if m.group(3) == "솟" else "max"
    v = int(m.group(4))
    tgt = sp.Symbol(m.group(5))
    a = sp.Symbol("a")
    out = []
    for av in sp.solve(D(f).subs(X, p), a):
        g = f.subs(a, av)
        info = [i for i in crit_info(g) if i[1] == kind]
        if len(info) != 1:
            return result("unverified", None, "극%s점 %d개" % (m.group(3), len(info)))
        # 극값 = info 값(k 포함) → k
        out += sp.solve(info[0][2] - v, tgt)
    return _single(q, out)


@h(r"^함수 f\(x\) = " + E + r"(?:이|가) x = (-?\d+)에서 극값을 갖고 f\(x\)의 극(솟|댓)값이 (-?\d+)일 때, 상수 (\w)의 값을 구하시오\. \(단, a는 상수이다\.\)$", "x=p에서 극값, f의 극댓값=v → 상수 k")
def _g10b(m, q):
    return _g10.__wrapped__(m, q) if hasattr(_g10, "__wrapped__") else _g10(m, q)


@h(r"^(?:삼차함수|함수) f\(x\) = " + E + r"(?:이|가|은|는) x = (-?\d+)에서 극값(?:을 갖는다|을 가질 때)[\.,] f\(x\)의 극(솟|댓)값을 구하시오\. \(단, a는 상수이다\.\)$", "x=p에서 극값 → 극솟/극댓값")
def _g11(m, q):
    return _ext_value_after(q, P(m.group(1)), int(m.group(2)), "min" if m.group(3) == "솟" else "max")


@h(r"^함수 f\(x\) = " + E + r"(?:이|가) x = (-?\d+)에서 극값을 가질 때, f\(x\)의 극(솟|댓)값을 구하시오\. \(단, a는 상수이다\.\)$", "x=p에서 극값을 가질 때 극값")
def _g11b(m, q):
    return _ext_value_after(q, P(m.group(1)), int(m.group(2)), "min" if m.group(3) == "솟" else "max")


@h(r"^함수 y = " + E + r"(?:이|가) x = (-?\d+)에서 극값을 가질 때, 이 함수의 극(솟|댓)값을 구하시오\. \(단, a는 상수이다\.\)$", "x=p에서 극값 → 이 함수의 극값")
def _g11c(m, q):
    return _ext_value_after(q, P(m.group(1)), int(m.group(2)), "min" if m.group(3) == "솟" else "max")


@h(r"^함수 f\(x\) = " + E + r"에 대하여 방정식 f'\(x\) = 0의 한 근이 x = (-?\d+)이다\. f\(x\)의 극(솟|댓)값을 구하시오\. \(단, a는 상수이다\.\)$", "f'=0의 한 근 x=p → 극값")
def _g12(m, q):
    return _ext_value_after(q, P(m.group(1)), int(m.group(2)), "min" if m.group(3) == "솟" else "max")


def _ext_value_after(q, f, p, kind):
    syms = _param_syms(f)
    if len(syms) != 1:
        raise Unverified("미지수 %d개" % len(syms))
    sols = sp.solve(D(f).subs(X, p), syms[0])
    if len(sols) != 1:
        raise Unverified("미지수 해 %d개" % len(sols))
    g = f.subs(syms[0], sols[0])
    info = [i for i in crit_info(g) if i[1] == kind]
    if len(info) != 1:
        return amb(row_stored(q), [i[2] for i in info], "극%s점 %d개(단일 답 요구)" % (kind, len(info))) if info else result("mismatch", None, "극%s점 없음" % kind)
    return info[0][2]


@h(r"^사차함수 f\(x\) = " + E + r"(?:이|가|은) x = (-?\d+)에서 극값을 (?:가질 때|갖는다)[\.,] (?:f\(x\)의 )?(?:두 )?극(솟|댓)값(?:을 구하시오|들? 중 (큰|작은) 값을 구하시오)\. \(단, k는 상수이다\.\)$", "사차 x=p 극값 → 극값(들)")
def _g13(m, q):
    f = P(m.group(1))
    p = int(m.group(2))
    kind = "min" if m.group(3) == "솟" else "max"
    syms = _param_syms(f)
    if len(syms) != 1:
        raise Unverified("미지수 %d개" % len(syms))
    sols = sp.solve(D(f).subs(X, p), syms[0])
    if len(sols) != 1:
        raise Unverified("미지수 해 %d" % len(sols))
    g = f.subs(syms[0], sols[0])
    info = [i for i in crit_info(g) if i[1] == kind]
    if m.group(4):
        vals = sorted([i[2] for i in info], key=float)
        if not vals:
            return result("mismatch", None, "극%s점 없음" % kind)
        return vals[-1] if m.group(4) == "큰" else vals[0]
    if len(info) != 1:
        return amb(row_stored(q), [i[2] for i in info], "극%s점 %d개" % (kind, len(info))) if info else result("mismatch", None, "극%s점 없음" % kind)
    return info[0][2]


@h(r"^사차함수 f\(x\) = " + E + r"에 대하여 방정식 f'\(x\) = 0의 실근은 x = (-?\d+)과 x = (-?\d+)이다\. f\(x\)의 극값을 구하시오\.$", "f'=0 실근 주어짐 → 극값")
def _g14(m, q):
    prem("발문 'f\\'=0 실근은 …이다' 주장")
    f = P(m.group(1))
    rts = real_roots_set(D(f))
    given = sorted([sp.Integer(int(m.group(2))), sp.Integer(int(m.group(3)))])
    if rts != given:
        return result("mismatch", None, "발문의 실근 {%s}이 실제 f'=0 실근 %s와 다름" % (given, rts))
    vals = [i[2] for i in crit_info(f) if i[1] in ("max", "min")]
    return _single(q, vals)


@h(r"^함수 f\(x\) = " + E + r"에 대하여 f'\(x\) = 0이지만 증가·감소가 바뀌지 않는 x의 값을 구하시오\.$", "f'=0이지만 부호 불변 x")
def _g15(m, q):
    f = P(m.group(1))
    xs = [i[0] for i in crit_info(f) if i[1] == "none"]
    return _single(q, xs)






# ---------------------------------------------------------------- EQUATION-APPLICATION
def _count_roots(f, cond=None):
    rts = real_roots_set(f)
    allr = sp.Poly(sp.together(f).as_numer_denom()[0], X).real_roots()
    if cond:
        rts = [r for r in rts if cond(r)]
        allr = [r for r in allr if cond(r)]
    probe("실근 개수: 서로 다른(통상) vs 중근 중복 포함", len(rts), len(allr))
    return sp.Integer(len(rts))


@h(r"^(?:삼차)?방정식 " + E + r" = (-?\d+)의 서로 다른 실근의 개수(?:를 구하시오\.|로 옳은 것은\?)$", "방정식 서로 다른 실근의 개수")
def _e1(m, q):
    return _count_roots(P(m.group(1)) - int(m.group(2)))


@h(r"^함수 f\(x\) = " + E + r"에 대하여 방정식 f\(x\) = (-?\d+)의 서로 다른 실근의 개수(?:를 구하시오\.|는\?)$", "f(x)=v 서로 다른 실근 개수")
def _e2(m, q):
    return _count_roots(P(m.group(1)) - int(m.group(2)))


@h(r"^사차함수 f\(x\) = " + E + r"에 대하여 방정식 f\(x\) = (-?\d+)의 서로 다른 실근의 개수를 구하시오\.$", "사차 f(x)=v 서로 다른 실근 개수")
def _e2b(m, q):
    return _count_roots(P(m.group(1)) - int(m.group(2)))


@h(r"^두 곡선 y = " + E + r", y = " + E + r"의 (?:서로 다른 )?교점의 개수(?:를 구하시오\.|로 옳은 것은\?)$", "두 곡선의 교점 개수")
def _e3(m, q):
    return _count_roots(P(m.group(1)) - P(m.group(2)))


@h(r"^곡선 y = " + E + r"(?:와|과) 직선 y = " + E + r"의 교점의 개수로 옳은 것은\?$", "곡선과 직선 교점 개수(객관식)")
def _e4(m, q):
    return _count_roots(P(m.group(1)) - P(m.group(2)))


@h(r"^곡선 y = " + E + r"(?:와|과) 직선 y = " + E + r"(?:이|가) 만나는 서로 다른 점의 개수를 구하시오\.$", "곡선과 직선이 만나는 서로 다른 점 개수")
def _e4b(m, q):
    return _count_roots(P(m.group(1)) - P(m.group(2)))


@h(r"^함수 f\(x\) = " + E + r"의 극댓값과 극솟값을 구하여 방정식 f\(x\) = (-?\d+)의 서로 다른 실근의 개수를 구하시오\.$", "극값 이용 방정식 실근 개수")
def _e5(m, q):
    return _count_roots(P(m.group(1)) - int(m.group(2)))


@h(r"^함수 f\(x\) = " + E + r"의 극댓값, 극솟값과 (-?\d+)을 비교하여 방정식 f\(x\) = \2의 서로 다른 실근의 개수를 구하시오\.$", "극값과 비교 방정식 실근 개수")
def _e5b(m, q):
    return _count_roots(P(m.group(1)) - int(m.group(2)))


@h(r"^함수 y = " + E + r"의 그래프가 x축과 만나는 점의 개수는\?$", "그래프가 x축과 만나는 점의 개수")
def _e6(m, q):
    return _count_roots(P(m.group(1)))


def _min_on(expr, dom):
    """expr(다항) 의 dom('R','>=0','>0') 에서의 최솟값. (값, 달성여부) 반환."""
    d = D(expr)
    cand = [r for r in real_roots_set(d)]
    if dom == "R":
        pts = cand
        vals = [sp.nsimplify(expr.subs(X, r)) for r in pts]
        # 차수 짝수·최고항 양수면 전역 최솟값 존재
        pol = sp.Poly(expr, X)
        if pol.degree() % 2 == 1 or pol.LC() < 0:
            return None, False
        return min(vals, key=float), True
    pts = [r for r in cand if (r > 0 if dom == ">0" else r >= 0)]
    bvals = [sp.nsimplify(expr.subs(X, 0))]
    vals = [sp.nsimplify(expr.subs(X, r)) for r in pts]
    pol = sp.Poly(expr, X)
    if pol.LC() < 0 and pol.degree() >= 1:
        return None, False  # 아래로 유계 아님(최고차항 음수) — 발문 유형상 없음
    allv = vals + bvals
    best = min(allv, key=float)
    attained = (dom == ">=0") or (any(same(best, v) for v in vals))
    return best, attained


def _min_res(q, expr, dom, label):
    prem("최솟값 달성 여부")
    best, ok = _min_on(expr, dom)
    if best is None:
        return result("mismatch", None, label + ": 최솟값 정의 불가(아래로 유계 아님)")
    if not ok:
        return result("mismatch", best, label + ": 최솟값이 정의역 경계(열린 구간)에서만 하한 → 달성되지 않음(하한=%s)" % best)
    return best


def _dom_of(s):
    return {"x ≥ 0": ">=0", "x > 0": ">0", "t ≥ 0": ">=0"}.get(s, "R")


@h(r"^모든 실수 x에 대하여 부등식 " + E + r" > 0이 성립함을 보이려 한다\. 좌변의 최솟값을 구하시오\.$", "모든 실수 부등식 좌변 최솟값")
def _e7(m, q):
    return _min_res(q, P(m.group(1)), "R", "좌변")






@h(r"^수직선 위를 움직이는 점 P의 시각 t \(t ≥ 0\)에서의 위치가 x\(t\) = " + E + r"이다\. 점 P의 위치가 (-?\d+)(?:이|가) 되는 서로 다른 시각의 개수를 구하시오\.$", "위치가 v가 되는 서로 다른 시각 개수(t≥0)")
def _e10(m, q):
    f = P(m.group(1), {"t": X})
    return _count_roots(f - int(m.group(2)), lambda r: r >= 0)


@h(r"^두 함수 f\(x\) = " + E + r", g\(x\) = " + E + r"에 대하여 (x ≥ 0)에서 f\(x\) > g\(x\)임을 보이려 한다\. x ≥ 0에서 f\(x\) - g\(x\)의 최솟값을 구하시오\.$", "x≥0에서 f-g 최솟값")
def _e11(m, q):
    return _min_res(q, P(m.group(1)) - P(m.group(2)), ">=0", "f-g")


@h(r"^모든 실수 x에 대하여 " + E + r"의 값은 " + E + r"의 값보다 크다\. 두 식의 값의 차 \(" + E + r"\) - \(" + E + r"\)의 최솟값을 구하시오\.$", "모든 실수: A>B, A-B 최솟값")
def _e12(m, q):
    return _min_res(q, P(m.group(1)) - P(m.group(2)), "R", "A-B")


@h(r"^수직선 위를 움직이는 두 점 P, Q의 시각 t \(t ≥ 0\)에서의 위치가 각각 p\(t\) = " + E + r", q\(t\) = " + E + r"이다\. t ≥ 0에서 점 P는 항상 점 Q보다 오른쪽에 있음을 보이려 한다\. t ≥ 0에서 p\(t\) - q\(t\)의 최솟값을 구하시오\.$", "p(t)-q(t) 최솟값(t≥0)")
def _e13(m, q):
    return _min_res(q, P(m.group(1), {"t": X}) - P(m.group(2), {"t": X}), ">=0", "p-q")


@h(r"^사차함수 y = " + E + r"의 그래프가 x축과 만나지 않음을 보이려 한다\. 이 함수의 최솟값을 구하시오\.$", "그래프가 x축과 만나지 않음 → 최솟값")
def _e14(m, q):
    return _min_res(q, P(m.group(1)), "R", "y")


@h(r"^사차함수 f\(x\) = " + E + r"에 대하여 방정식 f\(x\) = 0이 실근을 갖지 않음을 보이려 한다\. f\(x\)의 두 극솟값 중 작은 값을 구하시오\.$", "두 극솟값 중 작은 값")
def _e15(m, q):
    prem("발문 '두 극솟값' 주장")
    f = P(m.group(1))
    vals = sorted([i[2] for i in crit_info(f) if i[1] == "min"], key=float)
    if len(vals) != 2:
        return result("mismatch", None, "'두 극솟값' 주장 위배: 극소점 %d개" % len(vals))
    return vals[0]


@h(r"^사차함수 f\(x\) = " + E + r"에 대하여 모든 실수 x에서 f\(x\) > 0임을 보이려 한다\. f\(x\)의 최솟값을 구하시오\.$", "모든 실수 f>0 → 최솟값")
def _e16(m, q):
    return _min_res(q, P(m.group(1)), "R", "f")


@h(r"^모든 실수 x에 대하여 곡선 y = " + E + r"은 직선 y = " + E + r"보다 위쪽에 있음을 보이려 한다\. 두 그래프의 y좌표의 차의 최솟값을 구하시오\.$", "곡선-직선 y좌표 차 최솟값(모든 실수)")
def _e17(m, q):
    return _min_res(q, P(m.group(1)) - P(m.group(2)), "R", "차")




@h(r"^곡선 y = " + E + r"(?:이|가) x축보다 위쪽에 있음을 보이려 한다\. 이 곡선 위의 점의 y좌표의 최솟값을 구하시오\.$", "곡선이 x축 위쪽 → y좌표 최솟값")
def _e19(m, q):
    return _min_res(q, P(m.group(1)), "R", "y")








@h(r"^함수 f\(x\) = " + E + r"에 대하여 (x ≥ 0)에서 f\(x\) > 0임을 보이려 한다\. x ≥ 0에서 f\(x\)의 최솟값을 구하시오\.$", "x≥0에서 f>0 → 최솟값")
def _e22(m, q):
    return _min_res(q, P(m.group(1)), ">=0", "f")


# ---------------------------------------------------------------- VELOCITY-ACCELERATION
_VP = r"^수직선 위(?:를 움직이는|의)? 점 P의 시각 t(?: \(t > 0\))?에서의 위치가 x = "



def _tf(s):
    return P(s, {"t": T})



@h(_VP + E + r"일 때, (?:출발한 후 )?(?:시각 )?t = (-?\d+)(?:일 때|인 순간|에서)(?:의|,)? ?(?:점 P의 )?(속도|가속도|순간속도)(?:를 구하시오\.|는\?|로 옳은 것은\?)$", "t=a에서 속도/가속도")
def _v1(m, q):
    f = _tf(m.group(1))
    a = int(m.group(2))
    return (sp.diff(f, T) if m.group(3) != "가속도" else sp.diff(f, T, 2)).subs(T, a)


@h(_VP + E + r"일 때, t = (-?\d+)에서(?:의)? 점 P의 (속도|가속도)(?:를 구하시오\.|는\?)$", "t=a에서 점 P의 속도/가속도")
def _v1b(m, q):
    f = _tf(m.group(1))
    return (sp.diff(f, T) if m.group(3) == "속도" else sp.diff(f, T, 2)).subs(T, int(m.group(2)))


@h(_VP + E + r"일 때, 시각 t = (-?\d+)에서의 (순간속도)(?:를 구하시오\.|로 옳은 것은\?)$", "시각 t=a 순간속도")
def _v1c(m, q):
    return sp.diff(_tf(m.group(1)), T).subs(T, int(m.group(2)))


@h(_VP + E + r"일 때, t = (-?\d+)에서 점 P의 가속도를 구하시오\.$", "t=a 가속도")
def _v1d(m, q):
    return sp.diff(_tf(m.group(1)), T, 2).subs(T, int(m.group(2)))


@h(_VP + E + r"일 때, t = (-?\d+)일 때와 t = (-?\d+)일 때의 점 P의 속도의 합을 구하시오\.$", "두 시각 속도의 합")
def _v2(m, q):
    v = sp.diff(_tf(m.group(1)), T)
    return v.subs(T, int(m.group(2))) + v.subs(T, int(m.group(3)))


@h(_VP + E + r"일 때, 점 P의 속도가 (-?\d+)(?:이|가) 되는 시각 t \(t > 0\)의 값을 구하시오\.$", "속도가 v가 되는 시각 t>0")
def _v3(m, q):
    f = _tf(m.group(1))
    v = sp.diff(f, T)
    return _single(q, [r for r in sp.Poly(v - int(m.group(2)), T).real_roots() if r > 0])


@h(_VP + E + r"일 때, 점 P가 순간적으로 멈추는 시각 t \(t > 0\)의 값을 구하시오\.$", "순간적으로 멈추는 시각(v=0) t>0")
def _v4(m, q):
    v = sp.diff(_tf(m.group(1)), T)
    return _single(q, [r for r in sp.Poly(v, T).real_roots() if r > 0])


@h(_VP + E + r"이다\. t = (-?\d+)에서(?:의)? 점 P의 속도가 (-?\d+)일 때, 상수 k의 값을 구하시오\.$", "t=a 속도=v → k")
def _v5(m, q):
    f = _tf(m.group(1))
    k = sp.Symbol("k")
    return _single(q, sp.solve(sp.diff(f, T).subs(T, int(m.group(2))) - int(m.group(3)), k))


@h(_VP + E + r"일 때, t = (-?\d+)에서의 점 P의 속도와 가속도의 합(?:을 구하시오|은)[\.\?]$", "속도와 가속도의 합")
def _v6(m, q):
    f = _tf(m.group(1))
    a = int(m.group(2))
    return (sp.diff(f, T) + sp.diff(f, T, 2)).subs(T, a)


@h(_VP + E + r"일 때, t = (-?\d+)에서 t = (-?\d+)까지 점 P의 속도의 변화량을 구하시오\.$", "속도의 변화량(v(b)-v(a))")
def _v7(m, q):
    v = sp.diff(_tf(m.group(1)), T)
    return v.subs(T, int(m.group(3))) - v.subs(T, int(m.group(2)))


@h(_VP + E + r"일 때, t = (-?\d+)에서의 점 P의 속력\(속도의 절댓값\)을 구하시오\.$", "속력(|v|)")
def _v8(m, q):
    return sp.Abs(sp.diff(_tf(m.group(1)), T).subs(T, int(m.group(2))))


@h(_VP + E + r"일 때, 점 P의 가속도가 0이 되는 시각 t를 구하시오\.$", "가속도=0 시각")
def _v9(m, q):
    a = sp.diff(_tf(m.group(1)), T, 2)
    return _single(q, list(sp.solve(a, T)))


def _dir_changes(f, order, t_lo=0):
    v = sp.diff(f, T)
    rts = sorted(set(sp.Poly(v, T).real_roots()), key=float)
    ch = []
    for i, r in enumerate(rts):
        lo = (rts[i - 1] + r) / 2 if i > 0 else r - 1
        hi = (r + rts[i + 1]) / 2 if i + 1 < len(rts) else r + 1
        sl, sr = sp.sign(sp.nsimplify(v.subs(T, lo))), sp.sign(sp.nsimplify(v.subs(T, hi)))
        if sl * sr < 0:
            ch.append(r)
    return ch


@h(_VP + E + r"일 때, 점 P가 (처음으로|처음|두 번째로) 운동 방향을 (?:바꾸는|바꿀) (시각 t를 구하시오|때의 점 P의 위치를 구하시오|순간의 가속도를 구하시오)\.$", "운동 방향을 n번째로 바꾸는 시각/위치/가속도")
def _v10(m, q):
    f = _tf(m.group(1))
    ch = [r for r in _dir_changes(f, 0) if r >= 0]
    idx = 1 if m.group(2) == "두 번째로" else 0
    v_all = sorted(set(sp.Poly(sp.diff(f, T), T).real_roots()), key=float)
    v_pos = [r for r in v_all if r >= 0]
    probe("운동 방향 전환 순번: 속도 부호변화(통상) vs v=0 근 전부(t>=0)", len(ch), len(v_pos))
    probe("운동 방향 전환 순번: t>0 vs t>=0 (t=0 근)", len([r for r in ch if r > 0]), len(ch))
    if len(ch) <= idx:
        return result("mismatch", None, "운동 방향 전환 시각이 %d개뿐" % len(ch))
    r0 = ch[idx]
    note = ""
    if r0 == 0:
        return result("ambiguous", r0, "t=0 에서 방향 전환 — t≥0/t>0 해석에 따라 순번이 달라짐")
    if m.group(3).startswith("시각"):
        return r0
    if m.group(3).startswith("때의"):
        return f.subs(T, r0)
    return sp.diff(f, T, 2).subs(T, r0)


@h(_VP + E + r"이다\. t = (-?\d+)에서 점 P의 속도가 0일 때, 상수 k의 값을 구하시오\.$", "t=a 속도=0 → k")
def _v11(m, q):
    k = sp.Symbol("k")
    f = _tf(m.group(1))
    return _single(q, sp.solve(sp.diff(f, T).subs(T, int(m.group(2))), k))


@h(_VP + E + r"일 때, 점 P의 속도와 가속도가 같아지는 시각 t를 구하시오\.$", "속도=가속도 시각")
def _v12(m, q):
    f = _tf(m.group(1))
    return _single(q, list(sp.solve(sp.diff(f, T) - sp.diff(f, T, 2), T)))


@h(_VP + E + r"일 때, t = (-?\d+)에서의 점 P의 속도와 가속도의 합은\?$", "속도와 가속도의 합(객관식)")
def _v13(m, q):
    f = _tf(m.group(1))
    return (sp.diff(f, T) + sp.diff(f, T, 2)).subs(T, int(m.group(2)))


@h(r"^수직선 위를 움직이는 점 P의 시각 t \(t > 0\)에서의 위치가 x = " + E + r"일 때, 점 P의 속도가 (-?\d+)(?:이|가) 되는 시각 t는\?$", "속도가 v가 되는 시각 t(객관식, t>0)")
def _v14(m, q):
    f = _tf(m.group(1))
    return _single(q, [r for r in sp.Poly(sp.diff(f, T) - int(m.group(2)), T).real_roots() if r > 0])


@h(_VP + E + r"일 때, t = (-?\d+)에서 t = (-?\d+)까지의 평균속도와 순간속도가 같아지는 시각 t \((-?\d+) < t < (-?\d+)\)의 값을 구하시오\.$", "평균속도=순간속도 시각 t (v 문항)")
def _v15(m, q):
    prem('발문 구간과 괄호 구간 일치')
    f = _tf(m.group(1))
    lo, hi = int(m.group(2)), int(m.group(3))
    if (int(m.group(4)), int(m.group(5))) != (lo, hi):
        return result("mismatch", None, "발문 구간과 괄호 구간 불일치")
    return _mvt_result(q, f.subs(T, X), lo, hi)


@h(_VP + E + r"일 때, 점 P의 가속도가 0이 되는 시각의 속도를 구하시오\.$", "가속도=0 시각의 속도")
def _v16(m, q):
    f = _tf(m.group(1))
    ts = list(sp.solve(sp.diff(f, T, 2), T))
    if len(ts) != 1:
        return _single(q, ts)
    return sp.diff(f, T).subs(T, ts[0])


@h(r"^수직선 위를 움직이는 두 점 P, Q의 시각 t에서의 위치가 각각 f\(t\) = " + E + r", g\(t\) = " + E + r"이다\. 두 점의 속도가 같아지는 시각 t \(t > 0\)의 값을 구하시오\.$", "두 점의 속도가 같아지는 시각 t>0")
def _v17(m, q):
    f, g = _tf(m.group(1)), _tf(m.group(2))
    return _single(q, [r for r in sp.Poly(sp.diff(f - g, T), T).real_roots() if r > 0])


@h(_VP + E + r" \(k는 상수\)이다\. t = (-?\d+)에서의 점 P의 가속도가 0일 때, t = (-?\d+)에서의 점 P의 속도를 구하시오\.$", "가속도=0 → k → 다른 시각 속도")
def _v18(m, q):
    f = _tf(m.group(1))
    k = sp.Symbol("k")
    ks = sp.solve(sp.diff(f, T, 2).subs(T, int(m.group(2))), k)
    if len(ks) != 1:
        raise Unverified("k 해 %d" % len(ks))
    return sp.diff(f.subs(k, ks[0]), T).subs(T, int(m.group(3)))


# ---------------------------------------------------------------- 추가 핸들러(2차)
@h(r"^함수 f\(x\) = " + E + r", g\(x\) = " + E + r"에 대하여 f'\((-?\d+)\) - g'\(\3\)의 값을 구하시오\.$", "f'(a)-g'(a)")
def _a1(m, q):
    a = int(m.group(3))
    return D(P(m.group(1))).subs(X, a) - D(P(m.group(2))).subs(X, a)


@h(r"^두 함수 f\(x\) = " + E + r", g\(x\) = " + E + r"에 대하여 f'\((-?\d+)\) - g'\(\3\)의 값을 구하시오\.$", "두 함수 f'(a)-g'(a)")
def _a1b(m, q):
    a = int(m.group(3))
    return D(P(m.group(1))).subs(X, a) - D(P(m.group(2))).subs(X, a)


@h(r"^f\(x\) = " + E + r", g\(x\) = " + E + r", h\(x\) = " + E + r"일 때, f'\((-?\d+)\) \+ g'\(\4\) \+ h'\(\4\)의 값을 구하시오\.$", "f'+g'+h'")
def _a2(m, q):
    a = int(m.group(4))
    return sum(D(P(m.group(i))).subs(X, a) for i in (1, 2, 3))


@h(r"^함수 f\(x\) = x\^n \(n은 2 이상의 자연수\)에 대하여 f'\((-?\d+)\)의 값이 (-?\d+)일 때, f'\((-?\d+)\)의 값을 구하시오\.$", "x^n: f'(a)=v → f'(b)")
def _a3(m, q):
    a, v, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
    sols = [n for n in range(2, 80) if n * sp.Integer(a) ** (n - 1) == v]
    if len(sols) != 1:
        return result("mismatch", None, "n 해 %d개" % len(sols))
    n = sols[0]
    return n * sp.Integer(b) ** (n - 1)


@h(r"^함수 g\(t\) = " + E + r"에 대하여 g'\((-?\d+)\)의 값(?:을 구하시오\.|은\?)$", "g(t) 곱 미분 g'(a)")
def _a4(m, q):
    return D(P(m.group(1), {"t": T}), T).subs(T, int(m.group(2)))


@h(r"^함수 f\(x\) = " + E + r" \(a, b는 상수\)에 대하여 f'\((-?\d+)\)의 값이 (-?\d+)이고 f'\((-?\d+)\)의 값이 (-?\d+)일 때, ([ab])의 값을 구하시오\.$", "f=...+ax^2+bx..: 두 f' 조건 → a/b")
def _a5(m, q):
    f = P(m.group(1))
    a, b = sp.symbols("a b")
    sol = sp.solve([D(f).subs(X, int(m.group(2))) - int(m.group(3)), D(f).subs(X, int(m.group(4))) - int(m.group(5))], [a, b], dict=True)
    if len(sol) != 1:
        raise Unverified("연립해 %d" % len(sol))
    return sol[0][sp.Symbol(m.group(6))]


@h(r"^곡선 y = " + E + r" 위의 점 \((-?\d+), (-?\d+)\)에서의 접선이 x축과 만나는 점의 x좌표를 구하시오\.$", "접선이 x축과 만나는 점의 x좌표")
def _a6(m, q):
    f = P(m.group(1))
    a = int(m.group(2))
    if not on_curve(f, a, int(m.group(3))):
        return result("mismatch", None, "점이 곡선 위에 없음")
    s, b = tangent_line(f, a)
    if s == 0:
        return result("unverified", None, "접선이 x축과 평행")
    return -b / s


@h(r"^곡선 y = " + E + r" 위의 점 \(a, " + E + r"\) \(a > 0\)에서의 접선의 기울기가 (-?\d+)일 때, a의 값은\?$", "(a,g(a)) 접선 기울기=v → a>0")
def _a7(m, q):
    f = P(m.group(1))
    a = sp.Symbol("a")
    if not same(f.subs(X, a), P(m.group(2))):
        return result("mismatch", None, "점 (a,%s)가 곡선 위에 없음" % m.group(2))
    return _single(q, [r for r in sp.solve(D(f).subs(X, a) - int(m.group(3)), a) if r.is_real and r > 0])


@h(r"^곡선 y = " + E + r" 위의 x좌표가 (-?\d+)인 점에서의 접선의 y절편이 (-?\d+)일 때, 상수 (\w)의 값을 구하시오\.$", "접선 y절편=v → 상수")
def _a8(m, q):
    f = P(m.group(1))
    s, b = tangent_line(f, int(m.group(2)))
    return _single(q, sp.solve(b - int(m.group(3)), sp.Symbol(m.group(4))))


@h(r"^함수 f\(x\) = " + E + r"에 대하여, f는 닫힌구간 \[(-?\d+), (-?\d+)\]에서 연속이고 열린구간 \(\2, \3\)에서 미분가능하다\. f'\(c\) = \(f\(\3\) - f\(\2\)\)/\((.+)\)인 c가 열린구간 \(\2, \3\)에 오직 하나 존재할 때, c의 값을 구하시오\.$", "f'(c)=기울기 c (열린구간 오직 하나) [분모 표기 검증]")
def _a9(m, q):
    prem("발문 '오직 하나'+분모 표기 (b-a)")
    f = P(m.group(1))
    lo, hi = int(m.group(2)), int(m.group(3))
    if not same(P(m.group(4)), hi - lo):
        return result("mismatch", None, "분모 '%s' != %d" % (m.group(4), hi - lo))
    rts, inside, bd = _mvt_c(f, lo, hi)
    if len(inside) != 1:
        return result("mismatch", None, "'오직 하나' 주장 위배: 해 %d개" % len(inside))
    return inside[0]


@h(r"^삼차함수 f\(x\) = " + E + r"에 대하여 f\((-?\d+)\) - f\((-?\d+)\) = f'\(c\)\((.+)\)을 만족시키는 c \((-?\d+) < c < (-?\d+)\)의 값을 구하시오\.$", "f(b)-f(a)=f'(c)(b-a) c [인수 검증]")
def _a10(m, q):
    prem('인수 표기 (b-a)+괄호 구간')
    f = P(m.group(1))
    b, a = int(m.group(2)), int(m.group(3))
    if not same(P(m.group(4)), b - a):
        return result("mismatch", None, "인수 '%s' != %d" % (m.group(4), b - a))
    if (int(m.group(5)), int(m.group(6))) != (a, b):
        return result("mismatch", None, "괄호 구간 불일치")
    return _mvt_result(q, f, a, b)


@h(r"^함수 f\(x\) = " + E + r"에 대하여 구간 \[(-?\d+), (b|k)\] \(\3 > (-?\d+)\)에서 평균값 정리를 만족시키는 c의 값이 (-?\d+/?\d*)일 때, \3의 값을 구하시오\.$", "MVT c 주어짐 → 상한 b/k")
def _a11(m, q):
    f = P(m.group(1))
    lo = int(m.group(2))
    kk = sp.Symbol(m.group(3))
    c = P(m.group(5))
    sl = (f.subs(X, kk) - f.subs(X, lo)) / (kk - lo)
    sols = [s for s in sp.solve(sp.together(D(f).subs(X, c) - sl), kk) if s.is_real and s > int(m.group(4)) and lo < c < s]
    return _single(q, sols)


@h(r"^곡선 y = " + E + r"(?:와|과) 직선 y = " + E + r"의 서로 다른 교점의 개수를 구하시오\.$", "곡선과 직선 서로 다른 교점 개수")
def _a12(m, q):
    return _count_roots(P(m.group(1)) - P(m.group(2)))



# 최솟값 문항: 문장에 명시된 최종 식(차)을 그대로 파싱해 최소화하고, 전제 부등식 A>B 가 실제로 성립하는지도 검증
def _min_with_premise(q, expr, dom, premise_expr, label):
    prem("최솟값 달성 여부+전제 부등식(>0) 성립")
    best, ok = _min_on(expr, dom)
    if best is None:
        return result("mismatch", None, label + ": 최솟값 정의 불가")
    if not ok:
        return result("mismatch", best, label + ": 최솟값 비달성(열린 정의역 하한만 존재)")
    if premise_expr is not None and not same(sp.expand(premise_expr - expr), 0):
        return result("mismatch", best, label + ": 발문 전제식과 최소화 대상 식이 다름")
    if best <= 0:
        return result("mismatch", best, label + ": 전제(>0) 위배 — 최솟값 %s <= 0" % best)
    return best


@h(r"^(x > 0|x ≥ 0)에서 곡선 y = " + E + r"[은는] (?:직선|곡선) y = " + E + r"보다 위쪽에 있다\. \1에서 (?:곡선과 직선|두 곡선)의 y좌표의 차 " + E + r"의 최솟값을 구하시오\.$", "x 범위 곡선-(직선/곡선) y좌표 차 최솟값(일반)")
def _a13(m, q):
    A, B = P(m.group(2)), P(m.group(3))
    return _min_with_premise(q, P(m.group(4)), _dom_of(m.group(1)), A - B, "차")


@h(r"^(x ≥ 0|x > 0)일 때 부등식 " + E + r" > " + E + r"[이가] 성립함을 보이려 한다\. (?:x ≥ 0|x > 0)에서 두 변의 차 " + E + r"의 최솟값을 구하시오\.$", "x 범위 부등식 두 변의 차 최솟값(일반)")
def _a14(m, q):
    A, B = P(m.group(2)), P(m.group(3))
    return _min_with_premise(q, P(m.group(4)), _dom_of(m.group(1)), A - B, "차")


@h(r"^모든 실수 x에 대하여 부등식 " + E + r" > " + E + r"[이가] 성립함을 보이려 한다\. 두 변의 차 " + E + r"의 최솟값을 구하시오\.$", "모든 실수 부등식 두 변의 차 최솟값(일반)")
def _a15(m, q):
    A, B = P(m.group(1)), P(m.group(2))
    return _min_with_premise(q, P(m.group(3)), "R", A - B, "차")


@h(r"^모든 실수 x에 대하여 곡선 y = " + E + r"은 직선 y = " + E + r"보다 위쪽에 있음을 보이려 한다\. 두 그래프의 y좌표의 차의 최솟값을 구하시오\.$", "모든 실수 곡선-직선 y좌표 차 최솟값(전제 포함)")
def _a16(m, q):
    A, B = P(m.group(1)), P(m.group(2))
    return _min_with_premise(q, A - B, "R", None, "차")


@h(r"^함수 f\(x\) = " + E + r"에 대하여 (x ≥ 0)에서 방정식 f\(x\) = 0이 실근을 갖지 않음을 보이려 한다\. x ≥ 0에서 f\(x\)의 최솟값을 구하시오\.$", "x≥0 실근 없음 → f 최솟값(전제 포함)")
def _a17(m, q):
    return _min_with_premise(q, P(m.group(1)), ">=0", None, "f")


# 위치 보강: 반드시 일반 핸들러가 먼저 걸리도록 H 앞쪽으로 재배치 (같은 문장에 옛 핸들러와 중복 매치되면 note 로 표시)


def check_p3(row):
    q = row["question_text"]
    CUR["stored"] = row["answer"]
    CUR.pop("alt_xs", None)
    del PROBES[:]
    hits = [(rx, nm, fn) for rx, nm, fn in H if rx.match(q)]
    if not hits:
        raise Unverified("핸들러 없음(미인식 발문)")
    rx, nm, fn = hits[0]
    m = rx.match(q)
    v = fn(m, q)
    if isinstance(v, dict):
        res = v
    else:
        res = compare(row["answer"], sp.nsimplify(v))
    if len(hits) > 1:
        res["note"] = (res.get("note") or "") + " [핸들러 중복매치 %d]" % len(hits)
    ch = row.get("choices")
    if ch is not None:
        res["choice_issue"] = None
        stored = str(row["answer"])
        if stored not in [str(c) for c in ch]:
            res["choice_issue"] = "저장 answer 가 choices 에 없음"
        elif res["status"] in ("match", "mismatch") and res.get("indep") is not None:
            cnt = 0
            for c in ch:
                pc = parse_ans(c)
                if pc is None:
                    continue  # '8√3' 처럼 정수·분수가 아닌 보기는 비교 대상에서 제외(오답 보기)
                try:
                    if same(pc, sp.sympify(res["indep"])):
                        cnt += 1
                except Exception:
                    pass
            if cnt != 1:
                res["choice_issue"] = "독립 계산값이 choices 에 %d회 등장" % cnt
        if len(set(map(str, ch))) != len(ch):
            res["choice_issue"] = (res.get("choice_issue") or "") + " 보기 중복"
    return nm, res


# ---------------------------------------------------------------- 발문 ↔ 해설 일관성(도함수 식 검사)
_FDEF_Q = re.compile(r"(?<![A-Za-z])(f|g|h|y)(?:\((x|t)\))? = ((?:(?!, [fgh]\()[ -~])+)")
_FDEF_X = re.compile(r"(?<![A-Za-z])(f|g|y)'(?:\((x|t)\))? = ((?:(?! 이| 및)[ -~])+)")


def expl_deriv_check(row):
    """해설에 적힌 'f'(x) = <식>' 이 발문에서 정의된 함수의 실제 도함수와 같은지(다른 기호가 섞이면 비교 생략).
    반환: (검사한 식 수, 불일치 식 수, 불일치 예시 리스트, 파싱불가로 건너뛴 수)"""
    q, ex = row["question_text"], row["answer_explanation"]
    defs = {}
    for m in _FDEF_Q.finditer(q):
        name, var, body = m.group(1), m.group(2) or "x", m.group(3).strip()
        body = re.sub(r"\s*\([^()]*$", "", body)  # '(a, b' 같은 꼬리 제거
        try:
            e = P(body, {"t": T})
            defs.setdefault(name, (var, e))
        except Exception:
            pass
    n = bad = skipped = 0
    ex_bad = []
    for m in _FDEF_X.finditer(ex):
        name, var, body = m.group(1), m.group(2) or "x", m.group(3)
        if name not in defs:
            skipped += 1
            continue
        v0, e0 = defs[name]
        v = T if v0 == "t" else X
        for part in body.split("="):
            part = part.strip()
            part = re.sub(r"\s*\([^()]*$", "", part)
            if not part:
                continue
            if part in ("0", ""):
                continue  # f'(x)=0 은 방정식이지 도함수 식이 아님
            try:
                pe = P(part, {"t": T})
                if not isinstance(pe, sp.Expr):
                    raise ValueError("not expr")
            except Exception:
                skipped += 1
                continue
            if e0.free_symbols - {X, T}:
                skipped += 1  # 발문 함수에 미지 상수가 있으면 식 비교 생략
                continue
            if pe.free_symbols - (e0.free_symbols | {X, T}):
                skipped += 1  # n 등 발문에 없는 기호
                continue
            n += 1
            if not same(sp.expand(pe.subs(T, v) if v is X else pe), sp.expand(sp.diff(e0, v))):
                bad += 1
                ex_bad.append("%s'=%s (실제 %s)" % (name, part, sp.diff(e0, v)))
    return n, bad, ex_bad, skipped


# ================================================================ 드라이버
def expl_contains_answer(row):
    ans = str(row["answer"]).strip()
    ex = row["answer_explanation"]
    toks = re.findall(r"-?\d+(?:/\d+)?", ex)
    return ans in toks


def struct_checks(row):
    """부수 구조 점검: verify.answer_map 값 == answer, 객관식 보기/오답 지도 정합."""
    out = []
    am = (row.get("verify") or {}).get("answer_map")
    a = parse_ans(row["answer"])
    if am and a is not None:
        vals = []
        for v in am.values():
            pv = parse_ans(v)
            if pv is not None:
                vals.append(pv)
        if vals and not any(same(a, v) for v in vals):
            out.append("verify.answer_map 값이 answer 와 다름: %s vs %s" % (am, row["answer"]))
    ch = row.get("choices")
    if ch is not None:
        ch = [str(c) for c in ch]
        if str(row["answer"]) not in ch:
            out.append("answer 가 choices 에 없음")
        else:
            ai = ch.index(str(row["answer"]))
            for d in row.get("distractor_map") or []:
                ci = d.get("choice_index")
                if ci is None or not (0 <= ci < len(ch)):
                    out.append("distractor_map choice_index 범위 밖: %r" % ci)
                elif ci == ai:
                    out.append("distractor_map 이 정답 보기를 오답으로 지목")
    return out


def expl_final_check(row):
    """해설 문장의 '최종 값/평가점'이 발문·저장 answer 와 맞는지(정형 해설 코퍼스 한정). 해당 없음이면 None."""
    q, ex, ans = row["question_text"], row["answer_explanation"], str(row["answer"])
    m = re.search(r"x = (-?\d+)에서 계산하면 f'\((-?\d+)\)의 값은 (-?\d+(?:/\d+)?)이다", ex)
    if m:
        qa = re.search(r"f'\((-?\d+)\)", q)
        probs = []
        if m.group(1) != m.group(2):
            probs.append("해설 x=%s 와 f'(%s) 불일치" % (m.group(1), m.group(2)))
        if qa and qa.group(1) != m.group(1):
            probs.append("해설 평가점 %s != 발문 평가점 %s" % (m.group(1), qa.group(1)))
        if m.group(3) != ans:
            probs.append("해설 최종값 %s != answer %s" % (m.group(3), ans))
        return probs
    m = re.search(r"구하는 (?:값은|넓이는|거리는) (-?\d+(?:/\d+)?) 이다", ex)
    if m:
        return [] if m.group(1) == ans else ["해설 최종값 %s != answer %s" % (m.group(1), ans)]
    m = re.search(r"(\d+)부터 (\d+)까지의 합은 (-?\d+) 이다", ex)
    if m:
        qm = re.search(r"1부터 (\d+)까지", q)
        probs = []
        if qm and qm.group(1) != m.group(2):
            probs.append("해설 상한 %s != 발문 상한 %s" % (m.group(2), qm.group(1)))
        if m.group(3) != ans:
            probs.append("해설 최종값 %s != answer %s" % (m.group(3), ans))
        return probs
    return None


def check_format(row):
    """부수 점검: answer_format 과 answer 값의 형 일치(자연수/분수/실수)."""
    a = parse_ans(row["answer"])
    f = row["answer_format"]
    if a is None:
        return None
    if f == "자연수" and not (a.is_integer and a > 0):
        return "answer_format=자연수 인데 answer=%s" % row["answer"]
    if f == "분수" and a.is_integer:
        return "answer_format=분수 인데 answer=%s(정수)" % row["answer"]
    return None


CHECKERS = {}


def run(repo):
    base = repo + "/data/corpus/"
    out = {}
    for cname in CORPORA:
        rows = [json.loads(l) for l in open(base + cname + "/problems.jsonl", encoding="utf-8")]
        checker = CHECKERS[cname]
        per = []
        for r in rows:
            q = r["question_text"]
            del PROBES[:]
            del PREMS[:]
            try:
                fam, res = checker(r)
            except Unverified as e:
                fam, res = "(미인식)", result("unverified", None, "Unverified: %s" % e)
            except Exception as e:  # 파싱 실패 → 통과가 아니라 미검증
                fam, res = "(예외)", result("unverified", None, "예외 %s: %s" % (type(e).__name__, str(e)[:120]))
            res["family"] = fam
            sv = parse_ans(r["answer"])
            pr = []
            for p in PROBES:
                d = dict(p)
                if p["differs"] and sv is not None:
                    try:
                        d["stored_eq_primary"] = same(sv, sp.sympify(p["primary"]))
                    except Exception:
                        d["stored_eq_primary"] = None
                    try:
                        d["stored_eq_alt"] = same(sv, sp.sympify(p["alt"]))
                    except Exception:
                        d["stored_eq_alt"] = None
                pr.append(d)
            res["probes"] = pr
            res["premises"] = list(PREMS)
            en, eb, eex, esk = expl_deriv_check(r)
            res["expl_deriv"] = {"checked": en, "bad": eb, "examples": eex[:2], "skipped": esk}
            res["problem_id"] = r["problem_id"]
            res["q"] = q
            res["stored"] = r["answer"]
            res["skeleton"] = skeleton(q)
            res["vocab"] = vocab_of(q)
            res["struct"] = struct_checks(r)
            efc = expl_final_check(r)
            res["expl_final"] = efc
            res["is_published"] = r.get("is_published")
            res["expl_has_answer"] = expl_contains_answer(r)
            res["fmt_issue"] = check_format(r)
            res["unit"] = (r.get("unit_codes") or [""])[0]
            per.append(res)
        out[cname] = per
    return out


def _probe_summary(per):
    agg = collections.defaultdict(lambda: {"probed_rows": 0, "differs_rows": 0, "stored_eq_primary": 0, "stored_eq_alt": 0, "count_type": False})
    for p in per:
        for pr in p["probes"]:
            a = agg[pr["label"]]
            a["probed_rows"] += 1
            if "개수" in pr["label"]:
                a["count_type"] = True
            if pr["differs"]:
                a["differs_rows"] += 1
                if not a["count_type"]:
                    if pr.get("stored_eq_primary"):
                        a["stored_eq_primary"] += 1
                    if pr.get("stored_eq_alt"):
                        a["stored_eq_alt"] += 1
    return dict(agg)


def summarize(out):
    summ = {}
    for cname, per in out.items():
        n = len(per)
        sk = collections.Counter(p["skeleton"] for p in per)
        fam = collections.Counter(p["family"] for p in per)
        voc_sk = {}
        for p in per:
            d = voc_sk.setdefault(p["skeleton"], {})
            for k, ws in p["vocab"].items():
                d.setdefault(k, set()).update(ws)
        sem_sk = {k: v for k, v in voc_sk.items() if v}
        vocab_labels = collections.Counter()
        vocab_words = collections.defaultdict(set)
        for v in sem_sk.values():
            for k, ws in v.items():
                vocab_labels[k] += 1
                vocab_words[k].update(ws)
        sem_rows = [p for p in per if p["vocab"]]
        st = collections.Counter(p["status"] for p in per)
        st_sem = collections.Counter(p["status"] for p in sem_rows)
        summ[cname] = dict(
            rows=n, skeletons=len(sk), families=dict(fam),
            published=sum(1 for p in per if p["is_published"] is True),
            sem_templates=len(sem_sk), vocab_template_counts=dict(vocab_labels),
            vocab_words={k: sorted(v) for k, v in vocab_words.items()},
            sem_rows=len(sem_rows), status_all=dict(st), status_sem=dict(st_sem),
            struct_issues=sum(1 for p in per if p["struct"]),
            expl_final_checked=sum(1 for p in per if p["expl_final"] is not None),
            expl_final_bad=sum(1 for p in per if p["expl_final"]),
            expl_deriv_checked=sum(p["expl_deriv"]["checked"] for p in per),
            expl_deriv_bad=sum(p["expl_deriv"]["bad"] for p in per),
            choice_issues=sum(1 for p in per if p.get("choice_issue")),
            probes=_probe_summary(per),
            premise_checks=dict(collections.Counter(x for p in per for x in p["premises"])),
            premise_rows=sum(1 for p in per if p["premises"]),
            expl_missing_answer=sum(1 for p in per if not p["expl_has_answer"]),
            fmt_issues=sum(1 for p in per if p["fmt_issue"]),
        )
    return summ


def selftest(repo):
    """검사기의 변별력 점검(공허 통과 방지): ① 저장 answer 를 +1 로 오염 ② 발문의 의미 어휘를 뒤바꿈."""
    base = repo + "/data/corpus/"
    rep = {}
    swaps = [("극댓값", "극솟값"), ("극솟값", "극댓값"), ("극대가", "극소가"), ("극소가", "극대가"),
             ("큰 값", "작은 값"), ("작은 값", "큰 값"), ("증가하다가 감소", "감소하다가 증가"),
             ("평행할", "수직일"), ("가속도를 구하시오", "속도를 구하시오"), ("처음으로", "두 번째로"),
             ("x ≥ 0", "x > 0")]
    for cname in CORPORA:
        rows = [json.loads(l) for l in open(base + cname + "/problems.jsonl", encoding="utf-8")]
        chk = CHECKERS[cname]
        tamper = ok = 0
        for r in rows:
            r2 = dict(r)
            a = parse_ans(r["answer"])
            r2["answer"] = str(a + 1) if a is not None else r["answer"]
            try:
                _, res = chk(r2)
            except Exception:
                continue
            tamper += 1
            ok += 1 if res["status"] in ("mismatch", "ambiguous") else 0
        sw = {}
        if "p3" in cname:
            for a_, b_ in swaps:
                n = ch = un = 0
                for r in rows:
                    if a_ not in r["question_text"]:
                        continue
                    r2 = dict(r)
                    r2["question_text"] = r["question_text"].replace(a_, b_, 1)
                    n += 1
                    try:
                        _, res = chk(r2)
                        if res["status"] in ("mismatch", "ambiguous"):
                            ch += 1
                        elif res["status"] != "match":
                            un += 1
                    except Exception:
                        un += 1  # 핸들러가 더는 인식하지 못함(미검증으로 떨어짐)
                sw["%s→%s" % (a_, b_)] = {"rows": n, "mismatch_or_ambiguous": ch, "unrecognized": un, "still_match": n - ch - un}
        rep[cname] = {"tamper_rows": tamper, "tamper_detected": ok, "swap": sw}
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(__import__("pathlib").Path(__file__).resolve().parents[3]))
    ap.add_argument("--json", default=None)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        print(json.dumps(selftest(a.repo), ensure_ascii=False, indent=1))
        return
    out = run(a.repo)
    summ = summarize(out)
    tot = collections.Counter()
    print("%-52s %5s %5s %5s %5s %5s %5s %5s" % ("corpus", "rows", "tmpl", "match", "MISM", "AMBIG", "UNVER", "pub"))
    for c, s_ in summ.items():
        st = s_["status_all"]
        tot.update(st)
        print("%-52s %5d %5d %5d %5d %5d %5d %5d" % (c, s_["rows"], s_["skeletons"], st.get("match", 0), st.get("mismatch", 0),
                                                     st.get("ambiguous", 0), st.get("unverified", 0), s_["published"]))
        print("    expl_final %d checked/%d bad, expl_deriv %d checked/%d bad, struct_issues %d, choice_issues %d, fmt_issues %d, expl_missing_answer %d" % (
            s_["expl_final_checked"], s_["expl_final_bad"], s_["expl_deriv_checked"], s_["expl_deriv_bad"],
            s_["struct_issues"], s_["choice_issues"], s_["fmt_issues"], s_["expl_missing_answer"]))
    scanned = sum(s_["rows"] for s_ in summ.values())
    print("TOTAL rows=%d" % scanned, dict(tot))
    if scanned == 0:
        print("FAIL: 스캔 0건")
        sys.exit(2)
    if a.json:
        json.dump({"summary": summ, "rows": out}, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 종료 코드: 불일치/모호 있으면 1, 미검증 있으면 3(공허 통과 금지), 아니면 0
    if tot.get("mismatch", 0) or tot.get("ambiguous", 0):
        sys.exit(1)
    if tot.get("unverified", 0):
        sys.exit(3)
    sys.exit(0)


CHECKERS["problem_bank_calculus1_integral_v0"] = check_integral
CHECKERS["problem_bank_calculus2_trig_integral_v0"] = check_integral
CHECKERS["problem_bank_highschool_quotient_rule_v0"] = check_deriv_point
CHECKERS["problem_bank_university_calc1_v0"] = check_deriv_point
CHECKERS["problem_bank_university_calc1_chain_quotient_v0"] = check_deriv_point
CHECKERS["problem_bank_sequence_sigma_v0"] = check_sigma
CHECKERS["problem_bank_p3_calculus1_diff_v0"] = check_p3


if __name__ == "__main__":
    main()
