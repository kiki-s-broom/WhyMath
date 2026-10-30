#!/usr/bin/env python3
"""QUAL-12 감사 슬라이스 E — 6개 코퍼스 발문<->정답 의미 정합 전수 감사 (읽기 전용).

대상: problem_bank_conceptual_v0 · problem_bank_misconception_mc_v0 · problem_bank_generated_v0 ·
      problem_bank_rephrased_v0 · problem_bank_killer_v0 · problem_bank_v1

원칙
  * 생성기 모듈(whymath_backend.*)을 import하지 않는다. 오직 data/corpus/*/problems.jsonl과
    _provenance.json만 읽고, 발문 텍스트를 정규식으로 파싱해 독립 구현으로 정답을 재계산한다.
  * 저장된 verify.conditions/answer_map은 생성기가 만든 것이라 '독립'이 아니다 -> 대조 근거로 쓰지 않는다
    (misconception은 참고용 '내부 정합'만 별도 집계).
  * 파싱 실패/독립 계산 불가 = '미검증'(통과 아님). 샘플링 없음, 전 행 대조.

사용법:  python3 audit_E_script.py [--repo /home/user/WhyMath] [--out result.json] [--verbose]
종료 코드: 불일치(MISMATCH) 1건 이상이면 1, 아니면 0 (미검증·모호·구조결함은 종료 코드에 영향 없음).
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from fractions import Fraction
from math import comb, factorial, gcd
from pathlib import Path

import sympy
from sympy import Rational, S, cos, log, pi, sin, sqrt, symbols, tan

X = symbols("x", real=True)

# --------------------------------------------------------------------------------------
# 공통 유틸
# --------------------------------------------------------------------------------------


def load_rows(repo: Path, corpus: str):
    p = repo / "data" / "corpus" / corpus / "problems.jsonl"
    rows = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def load_prov(repo: Path, corpus: str):
    p = repo / "data" / "corpus" / corpus / "_provenance.json"
    return json.loads(p.read_text(encoding="utf-8"))


def template_of(text: str) -> str:
    """숫자를 N으로 접은 발문 템플릿(조사 변이는 접지 않음)."""
    return re.sub(r"-?\d+", "N", text)


def to_sym(s: str):
    """저장 answer/choice 문자열 -> sympy. 실패 시 None."""
    try:
        t = s.strip().replace("^", "**").replace("√", "sqrt").replace("π", "pi")
        return sympy.sympify(t, rational=True)
    except Exception:
        return None


def same(a, b) -> bool:
    """두 sympy 값이 같은가(정확 -> 수치 폴백)."""
    if a is None or b is None:
        return False
    try:
        d = sympy.simplify(a - b)
        if d == 0:
            return True
        return abs(sympy.N(a - b, 40)) < sympy.Float("1e-25")
    except Exception:
        return False


def isreal(z) -> bool:
    if z.is_real is True:
        return True
    if z.is_real is False:
        return False
    return abs(sympy.im(sympy.N(z, 30))) < 1e-20


def fr(a: str) -> Fraction:
    if "/" in a:
        n, d = a.split("/")
        return Fraction(int(n), int(d))
    return Fraction(int(a))


def sup_to_int(s: str) -> int:
    tbl = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
    return int(s.translate(tbl))


class Result:
    """한 코퍼스의 감사 집계."""

    def __init__(self, name: str, rows):
        self.name = name
        self.n = len(rows)
        self.templates = collections.Counter(template_of(r["question_text"]) for r in rows)
        self.compared = 0  # 독립 계산으로 정답을 재계산해 저장 answer와 대조한 행
        self.match = 0
        self.mismatch = []  # (slug, 사유, 발문, 저장답, 독립답)
        self.ambiguous = []  # (slug, 사유, 발문)
        self.unverified = []  # (slug, 사유, 발문)
        self.struct_fail = []  # 선지/정답 위치 구조 결함
        self.published = sum(1 for r in rows if r.get("is_published") is True)
        self.published_missing_field = sum(1 for r in rows if "is_published" not in r)
        self.notes = collections.Counter()

    def ok(self):
        self.compared += 1
        self.match += 1

    def bad(self, r, why, indep):
        self.compared += 1
        self.mismatch.append((r.get("slug"), why, r["question_text"], r.get("answer"), str(indep)))

    def amb(self, r, why):
        self.ambiguous.append((r.get("slug"), why, r["question_text"]))

    def unv(self, r, why):
        self.unverified.append((r.get("slug"), why, r["question_text"]))

    def summary(self):
        unv_reasons = collections.Counter(w for _, w, _ in self.unverified)
        amb_reasons = collections.Counter(w for _, w, _ in self.ambiguous)
        mm_reasons = collections.Counter(w for _, w, _, _, _ in self.mismatch)
        sf_reasons = collections.Counter(w for _, w, _ in self.struct_fail)
        return {
            "corpus": self.name,
            "rows": self.n,
            "templates_digit_folded": len(self.templates),
            "compared": self.compared,
            "match": self.match,
            "mismatch": len(self.mismatch),
            "ambiguous": len(self.ambiguous),
            "unverified": len(self.unverified),
            "struct_fail": len(self.struct_fail),
            "is_published_true": self.published,
            "is_published_field_missing": self.published_missing_field,
            "mismatch_reasons": dict(mm_reasons),
            "ambiguous_reasons": dict(amb_reasons),
            "unverified_reasons": dict(unv_reasons),
            "struct_fail_reasons": dict(sf_reasons),
            "notes": dict(self.notes),
        }


def check_choices(res: Result, r, ans_sym):
    """선택지 구조: 정답이 선택지에 정확히 1개, 선택지 상호 상이, distractor_map 대상이 정답이 아님."""
    ch = r.get("choices")
    if not ch:
        return
    syms = [to_sym(c) for c in ch]
    ans_hits = [i for i, c in enumerate(ch) if c == r["answer"]]
    sym_hits = [i for i, s in enumerate(syms) if s is not None and ans_sym is not None and same(s, ans_sym)]
    if len(ans_hits) != 1:
        res.struct_fail.append((r["slug"], f"answer 문자열이 선택지에 {len(ans_hits)}개", r["question_text"]))
    if ans_sym is not None and len(sym_hits) != 1:
        res.struct_fail.append((r["slug"], f"독립 정답과 같은 값의 선택지 {len(sym_hits)}개", r["question_text"]))
    if len(set(ch)) != len(ch):
        res.struct_fail.append((r["slug"], "선택지 문자열 중복", r["question_text"]))
    for d in r.get("distractor_map") or []:
        i = d.get("choice_index")
        if not isinstance(i, int) or not (0 <= i < len(ch)):
            res.struct_fail.append((r["slug"], f"distractor_map choice_index 범위 밖 {i}", r["question_text"]))
        elif ch[i] == r["answer"] or (ans_sym is not None and syms[i] is not None and same(syms[i], ans_sym)):
            res.struct_fail.append((r["slug"], "오개념 선택지가 정답과 같은 값", r["question_text"]))


# --------------------------------------------------------------------------------------
# 1) conceptual_v0 — 15 템플릿 독립 구현
# --------------------------------------------------------------------------------------


def conceptual_solve(r):
    """발문 -> (kind, 독립 정답 str | None, 모호/사유 표지). 생성기 코드 미사용.

    '1/0' 판정형은 발문에 적힌 숫자(예: '수렴하면 1, 발산하면 0')를 읽어 독립 진리값에 대응시킨다.
    """
    t = r["question_text"]
    # 1 이차방정식 실근 개수
    m = re.fullmatch(r"이차방정식 x\^2(?: \+ (\d+)x)? \+ (\d+) = 0 의 서로 다른 실근의 개수를 구하시오\.", t)
    if m:
        b = int(m.group(1) or 0)
        c = int(m.group(2))
        d = b * b - 4 * c
        return "real_root_count", str(2 if d > 0 else 1 if d == 0 else 0), None
    # 2 삼차함수 극값 개수: 임계점에서 도함수 부호변화를 sympy로 계산
    m = re.fullmatch(r"삼차함수 f\(x\) = \(x - (\d+)\)\^3(?: \+ (\d+))? 의 극값의 개수를 구하시오\.", t)
    if m:
        a = int(m.group(1))
        c = int(m.group(2) or 0)
        f = (X - a) ** 3 + c
        fp = sympy.diff(f, X)
        roots = sympy.real_roots(sympy.Poly(fp, X))
        cnt = 0
        for rt in set(roots):
            eps = Rational(1, 1000)
            if sympy.sign(fp.subs(X, rt - eps)) != sympy.sign(fp.subs(X, rt + eps)):
                cnt += 1
        return "extremum_count", str(cnt), None
    # 3 일대일대응
    m = re.fullmatch(
        r"함수 f\(x\) = (x\^2(?: \+ \d+x)?(?: \+ \d+)?) (?:가|이) 실수 전체에서 일대일대응이면 (\d), 아니면 (\d)을 쓰시오\.", t)
    if m:
        poly = sympy.sympify(re.sub(r"(\d)x", r"\1*x", m.group(1).replace("^", "**")), locals={"x": X})
        fp = sympy.diff(poly, X)
        roots = sympy.real_roots(sympy.Poly(fp, X)) if fp.free_symbols else []
        sign_change = False
        for rt in set(roots):
            eps = Rational(1, 1000)
            if sympy.sign(fp.subs(X, rt - eps)) != sympy.sign(fp.subs(X, rt + eps)):
                sign_change = True
        return "is_one_to_one", m.group(2) if not sign_change else m.group(3), None
    # 4 등비급수 수렴
    m = re.fullmatch(r"공비가 r = (\d+)(?:/(\d+))? 인 등비급수가 수렴하면 (\d), 발산하면 (\d)을 쓰시오\.", t)
    if m:
        rr = Fraction(int(m.group(1)), int(m.group(2) or 1))
        return "geometric_convergence", m.group(3) if abs(rr) < 1 else m.group(4), None
    # 5 극한 = 함숫값
    m = re.fullmatch(
        r"함수 f\(x\) = \(x\^2 - (\d+)x \+ (\d+)\) / \(x - (\d+)\) 에서 lim\(x→(\d+)\) f\(x\) = f\((\d+)\) "
        r"(?:가|이) 성립하면 (\d), 아니면 (\d)을 쓰시오\.", t)
    if m:
        b, c, a, a2, a3, yes, no = (int(m.group(i)) for i in range(1, 8))
        if not (a == a2 == a3):
            return "limit_equals_value", None, "발문 내 점 불일치(파싱)"
        num = X**2 - b * X + c
        den = X - a
        defined = den.subs(X, a) != 0
        if defined:
            holds = sympy.limit(num / den, X, a) == (num / den).subs(X, a)
            return "limit_equals_value", str(yes if holds else no), None
        return "limit_equals_value", str(no), "f(a) 미정의를 '성립 안 함'으로 읽는 관례 의존"
    # 6 미분가능
    m = re.fullmatch(
        r"함수 f\(x\) = \|x - (\d+)\|(?: \+ (\d+))? (?:가|이) 실수 전체에서 미분가능하면 (\d), 아니면 (\d)을 쓰시오\.", t)
    if m:
        a = int(m.group(1))
        f = sympy.Abs(X - a)
        q = (f - f.subs(X, a)) / (X - a)
        dif = sympy.limit(q, X, a, "-") == sympy.limit(q, X, a, "+")
        return "is_differentiable", m.group(3) if dif else m.group(4), None
    # 7 급수 수렴 (p-급수 비교)
    m = re.fullmatch(
        r"일반항이 a_n = (\d+)/(√?)\(?n(?: \+ (\d+))?\)? 인 급수 Σa_n 이 수렴하면 (\d), 발산하면 (\d)을 쓰시오\.", t)
    if m:
        k = int(m.group(1))
        p = Fraction(1, 2) if m.group(2) == "√" else Fraction(1)
        conv = (k == 0) or p > 1
        return "series_converges", m.group(4) if conv else m.group(5), None
    # 8 제외되는 실수 개수
    m = re.fullmatch(r"함수 f\(x\) = (\d+)/\(((?:\(x - \d+\))+)\) 의 정의역에서 제외되는 실수의 개수를 구하시오\.", t)
    if m:
        roots = {int(v) for v in re.findall(r"\(x - (\d+)\)", m.group(2))}
        return "excluded_point_count", str(len(roots)), None
    # 9 평균 = 중앙값
    m = re.fullmatch(r"자료 ([\d, ]+) 의 평균과 중앙값이 같으면 (\d), 다르면 (\d)을 쓰시오\.", t)
    if m:
        v = sorted(int(z) for z in m.group(1).split(","))
        mean = Fraction(sum(v), len(v))
        n = len(v)
        med = Fraction(v[n // 2]) if n % 2 else Fraction(v[n // 2 - 1] + v[n // 2], 2)
        return "mean_equals_median", m.group(2) if mean == med else m.group(3), None
    # 10 배반사건 독립
    m = re.fullmatch(
        r"두 배반사건 A, B에 대하여 P\(A\) = (\d+/\d+), P\(B\) = (\d+/\d+) 일 때, A와 B가 서로 독립이면 (\d), 아니면 (\d)을 쓰시오\.", t)
    if m:
        pa, pb = fr(m.group(1)), fr(m.group(2))
        if pa + pb > 1:
            return "events_independent", None, "배반인데 P(A)+P(B)>1 (불가능 설정)"
        indep = (pa * pb == 0)  # 배반 -> P(A∩B)=0, 독립 <=> P(A)P(B)=P(A∩B)=0
        return "events_independent", m.group(3) if indep else m.group(4), None
    # 11 조건부확률 P(A|B) = P(B|A)
    m = re.fullmatch(
        r"P\(A\) = (\d+/\d+), P\(B\) = (\d+/\d+), P\(A\|B\) = (\d+/\d+) 일 때, P\(A\|B\) = P\(B\|A\) 이면 (\d), 아니면 (\d)을 쓰시오\.", t)
    if m:
        pa, pb, pab = fr(m.group(1)), fr(m.group(2)), fr(m.group(3))
        inter = pab * pb
        if not (pa > 0 and inter <= min(pa, pb)):
            return "conditional_equal", None, "P(A∩B)>min(P(A),P(B)) 불가능 설정"
        pba = inter / pa
        return "conditional_equal", m.group(4) if pab == pba else m.group(5), None
    # 12 닮음비 -> 합동
    m = re.fullmatch(r"닮음비가 (\d+)(?:/(\d+))? 인 두 도형이 합동이면 (\d), 아니면 (\d)을 쓰시오\.", t)
    if m:
        ratio = Fraction(int(m.group(1)), int(m.group(2) or 1))
        return "congruent_by_ratio", m.group(3) if ratio == 1 else m.group(4), None
    # 13 내적은 벡터인가 스칼라인가 (정의상 두 벡터의 내적은 실수 = 스칼라)
    m = re.fullmatch(
        r"두 벡터 a = \((\d+), (\d+)\), b = \((\d+), (\d+)\) 의 내적 a·b 가 벡터이면 (\d), 스칼라\(수\)이면 (\d)을 쓰시오\.", t)
    if m:
        return "dot_product_scalar", m.group(6), None
    # 14 부등식 방향
    m = re.fullmatch(
        r"부등식 (-?\d+)x < (-?\d+) 의 해가 x > \(어떤 수\) 꼴이면 (\d), x < \(어떤 수\) 꼴이면 (\d)을 쓰시오\.", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        sol = sympy.solve_univariate_inequality(a * X < b, X, relational=False)
        if sol.sup == sympy.oo:
            return "inequality_direction", m.group(3), None
        if sol.inf == -sympy.oo:
            return "inequality_direction", m.group(4), None
        return "inequality_direction", None, "해 구간 형태 불명"
    # 15 근 소실(양변을 x로 나눔) — 서로 다른 실근 개수
    m = re.fullmatch(r"방정식 (\d*)x\^2 = (\d*)x 의 서로 다른 실근의 개수를 구하시오\.", t)
    if m:
        a = int(m.group(1) or 1)
        b = int(m.group(2) or 1)
        sols = sympy.solve(sympy.Eq(a * X**2, b * X), X)
        return "root_loss_count", str(len({s for s in sols if s.is_real})), None
    return None, None, "템플릿 파싱 실패"


BINARY_KINDS = {"is_one_to_one", "geometric_convergence", "limit_equals_value", "is_differentiable",
                "series_converges", "mean_equals_median", "events_independent", "conditional_equal",
                "congruent_by_ratio", "dot_product_scalar", "inequality_direction"}


def audit_conceptual(repo: Path) -> Result:
    rows = load_rows(repo, "problem_bank_conceptual_v0")
    res = Result("problem_bank_conceptual_v0", rows)
    kinds = collections.Counter()
    ans_dist = collections.defaultdict(collections.Counter)
    binary_dead = 0
    kind_mismatch = 0
    for r in rows:
        kind, indep, flag = conceptual_solve(r)
        if kind is None or indep is None:
            res.unv(r, flag or "독립 계산 불가")
            continue
        kinds[kind] += 1
        if (r.get("verify") or {}).get("answer_kind") != kind:
            kind_mismatch += 1
        ans_dist[kind][r["answer"]] += 1
        if flag:
            res.amb(r, flag)
        if r["answer"] == indep:
            res.ok()
        else:
            res.bad(r, f"[{kind}] 독립 재계산 != 저장 answer", indep)
        ek = re.search(r"—\s*(\d)이다|극값은 (\d)개|이라 (\d)이다|(\d)개이다|\((\d)개\)|(\d)개다", r["answer_explanation"])
        if ek:
            claim = [g for g in ek.groups() if g][0]
            res.notes["해설 주장 숫자 추출 성공"] += 1
            if claim != indep:
                res.notes["해설 주장 숫자 != 독립 정답"] += 1
                res.struct_fail.append((r["slug"], f"해설이 주장하는 값 {claim} != 독립 정답 {indep}", r["question_text"]))
        else:
            res.notes["해설 주장 숫자 추출 실패(미확인)"] += 1
        ch = r["choices"]
        if ch != ["0", "1", "2", "3"] or r["answer"] not in ch:
            res.struct_fail.append((r["slug"], "선택지가 0..3 아님/정답 미포함", r["question_text"]))
        if len(r.get("distractor_map") or []) != 1:
            res.struct_fail.append((r["slug"], "distractor_map 건수 != 1", r["question_text"]))
        else:
            ci = r["distractor_map"][0]["choice_index"]
            if ch[ci] == r["answer"]:
                res.struct_fail.append((r["slug"], "오개념 선지가 정답과 동일", r["question_text"]))
        if kind in BINARY_KINDS:
            binary_dead += 1
    res.notes["verify.answer_kind != 독립 판정 kind"] = kind_mismatch
    res.notes["판정형(0/1 답) 문항인데 선택지에 무의미한 2,3 존재"] = binary_dead
    res.notes["kind별 정답 분포"] = {k: dict(v) for k, v in ans_dist.items()}
    res.notes["정답이 한 값으로 퇴화한 kind(>=20문항 전부 동일 정답)"] = [
        k for k, v in ans_dist.items() if len(v) == 1 and sum(v.values()) >= 20]
    res.notes["kind별 대조 행"] = dict(kinds)
    return res


# --------------------------------------------------------------------------------------
# 2) misconception_mc_v0 — 45 템플릿 독립 구현
# --------------------------------------------------------------------------------------

_N = r"(-?\d+)"
_J = r"[을를은는이가와과으로]*"  # 조사 변이 허용


def _misc_table():
    """(이름, 정규식, 계산 람다) 목록. 정규식은 fullmatch."""
    T = []

    def add(name, rx, fn):
        T.append((name, re.compile(rx), fn))

    add("distribution", rf"두 수 a, b에 대하여 a = {_N}, b = {_N} 일 때, \(a\+b\)\^{_N} 의 값을 구하시오\.",
        lambda a, b, e: S(a + b) ** e)
    add("chain_rule", rf"함수 f\(x\) = \({_N}x \+ {_N}\)\^{_N} 의 x = {_N} 에서의 미분계수 f'\({_N}\) 의 값을 구하시오\.",
        lambda k, c, n, x0, x1: S(n) * k * S(k * x0 + c) ** (n - 1) if x0 == x1 else None)
    add("sine_sum", r"두 각 A = (\d+)π/(\d+), B = (\d+)π/(\d+) 에 대하여 (?:(\d+) )?sin\(A \+ B\) 의 값을 구하시오\.",
        lambda a, d1, b, d2, k: (S(k) if k else S(1)) * sin(pi * Rational(a, d1) + pi * Rational(b, d2)))
    add("exp_zero", rf"자연수 a = {_N} 에 대하여 {_N} \+ a\^{_N} 의 값을 구하시오\.",
        lambda a, n, e: S(n) + S(a) ** e)
    add("sqrt_pos", rf"√\(\(-{_N}\)\^{_N}\) 의 값을 구하시오\.",
        lambda a, e: sqrt(S(-a) ** e))
    add("log_dist", rf"log_{_N}\({_N}\^{_N} \+ {_N}\^{_N}\) 의 값을 구하시오\.",
        lambda b0, b1, k1, b2, k2: log(S(b1) ** k1 + S(b2) ** k2, b0) if b0 > 1 else None)
    add("func_compose", rf"두 함수 f\(x\) = x \+ {_N}, g\(x\) = {_N}x 에 대하여 \(f∘g\)\({_N}\) 의 값을 구하시오\.",
        lambda a, b, c: S(b * c + a))  # (f∘g)(c) = f(g(c)) = g(c) + a
    add("sine_period", rf"함수 y = sin\({_N}x\) 의 주기를 구하시오\.",
        lambda k: 2 * pi / k)
    add("translate", rf"함수 f\(x\) = x\^{_N} \+ {_N}x 에 대하여 g\(x\) = f\(x - {_N}\) 일 때, g\({_N}\) 의 값을 구하시오\.",
        lambda n, b, s, t: S(t - s) ** n + b * S(t - s))  # g(t) = f(t - s)
    add("product_rule", rf"두 함수 f\(x\) = x\^{_N}, g\(x\) = x\^{_N} 에 대하여 함수 f\(x\)g\(x\) 의 x = {_N} 에서의 미분계수를 구하시오\.",
        lambda m, n, x0: S(m + n) * S(x0) ** (m + n - 1))
    add("fraction_cancel", rf"두 자연수 a = {_N}, b = {_N} 에 대하여 \(a \+ b\) / a 의 값을 구하시오\.",
        lambda a, b: Rational(a + b, a))
    add("polygon_angle_sum", rf"{_N}각형의 내각의 크기의 합을 구하시오\. \(단위: 도\)",
        lambda n: S((n - 2) * 180))
    add("area_perimeter", rf"가로가 {_N}, 세로가 {_N} 인 직사각형의 넓이를 구하시오\.",
        lambda a, b: S(a * b))
    add("circle_radius", rf"원 x\^2 \+ y\^2 = {_N} 의 반지름의 길이를 구하시오\.",
        lambda r2: sqrt(S(r2)))
    add("gambler_streak", rf"앞면이 나올 확률이 {_N}/{_N} 인 동전을 던져 앞면이 {_N}번 연속 나왔다\. 다음 시행에서 앞면이 나올 확률을 구하시오\.",
        lambda p, q, k: Rational(p, q))  # 독립시행: 이전 결과와 무관
    add("fraction_addition", rf"{_N}/{_N} \+ {_N}/{_N} 의 값을 구하시오\.",
        lambda a, b, c, d: Rational(a, b) + Rational(c, d))
    add("negative_product", rf"\(-{_N}\) × \(-{_N}\) 의 값을 구하시오\.",
        lambda a, b: S(a * b))
    add("subtract_negative", rf"{_N} - \(-{_N}\) 의 값을 구하시오\.",
        lambda a, b: S(a + b))
    add("absolute_value", rf"\|-{_N}\| \+ {_N} 의 값을 구하시오\.",
        lambda a, b: S(abs(a) + b))
    add("sqrt_sum", rf"√\({_N} \+ {_N}\) 의 값을 구하시오\.",
        lambda a, b: sqrt(S(a + b)))
    add("difference_of_squares", rf"x = {_N}, a = {_N} 일 때 x² - a² 의 값을 구하시오\.",
        lambda x, a: S(x * x - a * a))
    add("exponent_product", rf"{_N} × {_N}² 의 값을 구하시오\.",
        lambda a, b: S(a) * S(b) ** 2)
    add("power_of_power", rf"\({_N}\^{_N}\)\^{_N} 의 값을 구하시오\.",
        lambda a, m, n: S(a) ** (m * n))
    add("negative_square", rf"-{_N}² \+ {_N} 의 값을 구하시오\.",
        lambda a, b: S(-(a * a) + b))
    add("distribute_partial", rf"{_N}\(x \+ {_N}\) 에서 x = {_N} 일 때의 값을 구하시오\.",
        lambda k, c, x: S(k * (x + c)))
    add("negative_distribute", rf"-\(x - {_N}\) 에서 x = {_N} 일 때의 값을 구하시오\.",
        lambda a, x: S(-(x - a)))
    add("square_difference", rf"\({_N} - {_N}\)² 의 값을 구하시오\.",
        lambda a, b: S((a - b) ** 2))
    add("midpoint", rf"수직선 위 두 점 {_N}, {_N} 의 중점의 좌표를 구하시오\.",
        lambda a, b: Rational(a + b, 2))
    add("scale_area", rf"닮음비가 {_N} 인 두 도형의 넓이의 비를 구하시오\.",
        lambda k: S(k) ** 2)
    add("negative_even_power", rf"\(-{_N}\)\^{_N} 의 값을 구하시오\.",
        lambda a, n: S(-a) ** n)
    add("combine_unlike", rf"{_N}x \+ {_N}x² 에서 x = {_N} 일 때의 값을 구하시오\.",
        lambda a, b, x: S(a * x + b * x * x))
    add("complete_square", rf"x² \+ {_N}x 에서 x = {_N} 일 때의 값을 구하시오\.",
        lambda a, x: S(x * x + a * x))
    add("conjugate_product", rf"\(√{_N} \+ {_N}\)\(√{_N} - {_N}\) 의 값을 구하시오\.",
        lambda a, c1, a2, c2: (sqrt(S(a)) + c1) * (sqrt(S(a2)) - c2))
    add("transpose", rf"일차방정식 x \+ {_N} = {_N} 의 해를 구하시오\.",
        lambda a, b: S(b - a))
    add("gcd_lcm", rf"{_N} {_J} {_N} 의 최소공배수를 구하시오\.",
        lambda a, b: S(a * b // gcd(a, b)))
    add("decimal_mult", r"(\d+)\.(\d+) × (\d+)\.(\d+) 의 값을 구하시오\.",
        lambda a1, a2, b1, b2: Rational(f"{a1}.{a2}") * Rational(f"{b1}.{b2}"))
    add("mixed_mult", rf"{_N}{_J} {_N}/{_N} \(대분수\)에 {_N} {_J} 곱한 값을 구하시오\.",
        lambda w, n, d, k: (S(w) + Rational(n, d)) * k)
    add("remainder_sign", rf"다항식 x² \+ {_N}x \+ {_N} {_J} \(x - {_N}\){_J} 나눈 나머지를 구하시오\.",
        lambda b, c, a: S(a * a + b * a + c))  # 나머지정리: f(a)
    add("vieta_sum", rf"x² \+ {_N}x \+ {_N} = 0 의 두 근의 합을 구하시오\.",
        lambda b, c: S(-b))
    add("trapezoid_area", rf"윗변이 {_N}, 아랫변이 {_N}, 높이가 {_N} 인 사다리꼴의 넓이를 구하시오\.",
        lambda a, b, h: Rational((a + b) * h, 2))
    add("scale_volume", rf"닮음비가 {_N}:{_N} 인 두 입체도형의 부피비는 {_N}:\? 이다\. \? 의 값을 구하시오\.",
        lambda p, q, one: (S(q) ** 3 / S(p) ** 3) * one if p != 0 else None)
    add("cone_volume", rf"밑면의 반지름이 {_N}, 높이가 {_N} 인 원뿔의 부피를 원주율 π로 나눈 값을 구하시오\.",
        lambda r, h: Rational(r * r * h, 3))
    add("circle_area", rf"반지름이 {_N} 인 원의 넓이를 원주율 π로 나눈 값을 구하시오\.",
        lambda r: S(r * r))
    add("combination", rf"서로 다른 {_N} 개에서 {_N} 개를 뽑는 조합의 수 {_N}C{_N} {_J} 구하시오\.",
        lambda n, r, n2, r2: S(comb(n, r)) if (n == n2 and r == r2) else None)
    add("same_item_permutation", rf"{_N} 개의 A 와 {_N} 개의 B, 모두 {_N} 개의 문자를 일렬로 배열하는 경우의 수를 구하시오\.",
        lambda a, b, tot: S(factorial(a + b) // (factorial(a) * factorial(b))) if a + b == tot else None)
    return T


MISC_TABLE = _misc_table()


def misc_solve(text: str):
    hits = [(name, rx.fullmatch(text), fn) for name, rx, fn in MISC_TABLE if rx.fullmatch(text)]
    if len(hits) != 1:
        return None, None, f"템플릿 매칭 {len(hits)}개"
    name, m, fn = hits[0]
    g = m.groups()
    try:
        if name == "decimal_mult":
            vals = list(g)
        else:
            vals = [int(v) if v is not None and re.fullmatch(r"-?\d+", v) else v for v in g]
        v = fn(*vals)
    except Exception as e:
        return name, None, f"계산 예외 {type(e).__name__}"
    if v is None:
        return name, None, "발문 내 반복 수치 불일치/계산 불가"
    return name, sympy.sympify(v), None


def audit_misconception(repo: Path) -> Result:
    rows = load_rows(repo, "problem_bank_misconception_mc_v0")
    res = Result("problem_bank_misconception_mc_v0", rows)
    per_tpl = collections.Counter()
    internal_mismatch = 0
    for r in rows:
        name, indep, flag = misc_solve(r["question_text"])
        if indep is None:
            res.unv(r, flag or "독립 계산 불가")
            continue
        per_tpl[name] += 1
        ans = to_sym(r["answer"])
        if ans is None:
            res.unv(r, "저장 answer 파싱 불가")
            continue
        if same(ans, indep):
            res.ok()
        else:
            res.bad(r, f"[{name}] 독립 재계산 != 저장 answer", indep)
        if name == "scale_area":
            res.amb(r, "'넓이의 비'를 단일 수(k^2)로 답 — 비 표기(k^2:1 또는 1:k^2) 관례 의존")
        if name == "vieta_sum":
            mv = re.fullmatch(rf"x² \+ {_N}x \+ {_N} = 0 의 두 근의 합을 구하시오\.", r["question_text"])
            if mv and int(mv.group(1)) ** 2 - 4 * int(mv.group(2)) < 0:
                res.amb(r, "판별식<0: '두 근'이 허근(복소수 범위 가정 필요) — 합은 -b로 동일")
        if not re.search(r"(?<![\d.])" + re.escape(r["answer"]) + r"(?!\d)", r.get("answer_explanation", "")):
            res.notes["해설 본문에 정답 문자열이 없음(해설-정답 정합 미확인)"] += 1
        check_choices(res, r, indep)
        syms = [to_sym(c) for c in r["choices"]]
        if len(r["choices"]) != 4 or any(s is None for s in syms) or \
                len({str(sympy.N(s, 20)) for s in syms}) != 4:
            res.struct_fail.append((r["slug"], "4개 선택지가 수치적으로 서로 다르지 않음", r["question_text"]))
        cond = (r.get("verify") or {}).get("conditions", "")
        mm = re.fullmatch(r"x = (.+)", cond)
        if mm:
            try:
                rhs = sympy.sympify(mm.group(1).replace("^", "**"), rational=True)
                if not same(rhs, ans):
                    internal_mismatch += 1
            except Exception:
                res.notes["verify.conditions 파싱 불가(내부정합 미확인)"] += 1
    res.notes["독립 solver 템플릿 수"] = len(MISC_TABLE)
    res.notes["매칭된 서로 다른 템플릿 수"] = len(per_tpl)
    res.notes["verify.conditions 우변 != answer (비독립 내부정합 위반)"] = internal_mismatch
    res.notes["템플릿별 대조 행"] = dict(per_tpl)
    return res


# --------------------------------------------------------------------------------------
# 3) generated_v0 / rephrased_v0 / killer_v0 / v1 — 발문 파서 + 독립 계산
# --------------------------------------------------------------------------------------


def parse_poly(expr: str):
    e = expr.replace("^", "**").replace(" ", "")
    e = re.sub(r"(\d)x", r"\1*x", e)
    e = re.sub(r"\)\(", ")*(", e)
    return sympy.sympify(e, locals={"x": X}, rational=True)


def cubic_from_text(t: str):
    m = re.search(r"f\(x\) = (x\^3[^가-힣]*)", t)
    if not m:
        return None
    return parse_poly(m.group(1).strip())


_TRIGV = {"√2/2": sqrt(2) / 2, "√3/2": sqrt(3) / 2, "1/2": Rational(1, 2)}


def solve_text(t: str):
    """발문 -> (독립 정답 sympy|None, 미검증 사유). 텍스트 패턴 기반(unit 코드 미사용)."""
    # 점화식(귀납) 수열
    m = re.search(r"a₁ = (\d+)\n\(나\) aₙ₊₁ = (?:aₙ \+ (\d+)|(\d+)·aₙ) \(n ≥ 1\)\na([₀-₉]+)의 값", t)
    if m:
        v = int(m.group(1))
        for _ in range(sup_to_int(m.group(4)) - 1):
            v = v + int(m.group(2)) if m.group(2) else v * int(m.group(3))
        return S(v), None
    # 삼각방정식 0°<=x<360°
    m = re.search(r"0° ≤ x < 360°.*?(sin|cos) x = (-?)(1/2|√2/2|√3/2).*?(가장 작은|가장 큰) 해", t, re.S)
    if m:
        fn = sin if m.group(1) == "sin" else cos
        val = _TRIGV[m.group(3)] * (-1 if m.group(2) else 1)
        sols = [d for d in range(360) if abs(sympy.N(fn(d * pi / 180) - val, 30)) < 1e-20]
        if not sols:
            return None, "구간 내 해 없음"
        return S(min(sols) if m.group(4) == "가장 작은" else max(sols)), None
    # 삼각함수 값
    m = re.fullmatch(r"(?:삼각함수 )?(sin|cos|tan) (\d+)°\s*(?:의 값을 구하시오|를 계산하시오)\.", t)
    if m:
        fn = {"sin": sin, "cos": cos, "tan": tan}[m.group(1)]
        return sympy.simplify(fn(int(m.group(2)) * pi / 180)), None
    # 지수/로그 방정식
    m = re.search(r"(\d+)\^x\s*=\s*(\d+)", t)
    if m and "log" not in t:
        return sympy.simplify(log(int(m.group(2)), int(m.group(1)))), None
    m = re.search(r"log_(\d+) x\s*=\s*(\d+)", t)
    if m:
        return S(int(m.group(1))) ** int(m.group(2)), None
    # 등차/등비 수열 (항·합)
    if "첫째항" in t and ("공차" in t or "공비" in t):
        a = re.search(r"첫째항(?:이|은)?\s*(\d+)", t)
        arith = "공차" in t
        d = re.search(r"공차(?:가|는)?\s*(\d+)" if arith else r"공비(?:가|는)?\s*(\d+)", t)
        if not (a and d):
            return None, "수열 수치 파싱 실패"
        a, d = int(a.group(1)), int(d.group(1))
        nm = (re.search(r"처음 (\d+)개 항", t) or re.search(r"제(\d+)항(?:까지|을|\s)", t)
              or re.search(r"(\d+)번째", t) or re.search(r"S_(\d+)", t))
        if not nm:
            return None, "항 번호 파싱 실패"
        n = int(nm.group(1))
        if "합" in t:
            return (S(n * (2 * a + (n - 1) * d)) / 2 if arith else S(a * (d**n - 1)) / (d - 1)), None
        return (S(a + (n - 1) * d) if arith else S(a * d ** (n - 1))), None
    # 삼차함수 극값/접선
    if "f(x) = x^3" in t:
        f = cubic_from_text(t)
        if f is None:
            return None, "삼차식 파싱 실패"
        fp = sympy.diff(f, X)
        if "접선의 기울기" in t:
            mm = re.search(r"기울기가 (-?\d+)인", t)
            if not mm:
                return None, "기울기 파싱 실패"
            roots = sorted([z for z in sympy.solve(sympy.Eq(fp, int(mm.group(1))), X) if isreal(z)],
                           key=lambda z: sympy.N(z))
            if len(roots) != 2:
                return None, f"접점 {len(roots)}개"
            big, small = ("큰" in t), ("작은" in t)
            if big == small:
                return None, "큰/작은 방향어 판별 불가"
            return (roots[1] if big else roots[0]), None
        want_max = "극대" in t or "극댓" in t
        want_min = "극소" in t or "극솟" in t
        if want_max == want_min:
            return None, "극대/극소 방향어 판별 불가"
        fpp = sympy.diff(fp, X)
        crit = [z for z in sympy.solve(fp, X) if isreal(z)]
        pick = [z for z in crit if (sympy.N(fpp.subs(X, z)) < 0 if want_max else sympy.N(fpp.subs(X, z)) > 0)]
        if len(pick) != 1:
            return None, "극점 유일하지 않음"
        z = pick[0]
        return (sympy.simplify(z) if "x의 값" in t else sympy.simplify(f.subs(X, z))), None
    # 이차방정식: 근 선택
    m = re.search(r"(\(x [+-] \d+\)\^2|\d*x\^2(?: [+-] \d*x)?(?: [+-] \d+)?)\s*=\s*(-?\d+)", t)
    if m and ("방정식" in t or re.match(r"^\s*\d*x\^2", t)):
        sols = sympy.solve(sympy.Eq(parse_poly(m.group(1)), int(m.group(2))), X)
        sols = sorted({sympy.simplify(z) for z in sols if isreal(z)}, key=lambda z: sympy.N(z))
        big = ("큰" in t) or ("크" in t)
        small = ("작은" in t) or ("작" in t)
        if len(sols) == 1:
            return sols[0], None
        if big == small:
            return None, "두 근인데 큰/작은 방향어 없음(또는 모순)"
        return (sols[-1] if big else sols[0]), None
    return None, "해당 패턴 없음"


# 재진술(LLM) 발문 중 정답은 일치하나 문장이 비문이거나 값을 요구하지 않는 표현의 수동 식별 마커
GARBLE_MARKERS = ["크면서", "작게", "크다는", "판단하시오", "찾아야 합니다"]
REQUEST_TOKENS = ["구하", "찾", "얼마", "무엇", "고르시오", "계산", "은?", "인가", "일까", "?", "구해"]


def audit_text_corpus(repo: Path, corpus: str) -> Result:
    rows = load_rows(repo, corpus)
    res = Result(corpus, rows)
    if corpus == "problem_bank_rephrased_v0":
        gen = {r["slug"]: r for r in load_rows(repo, "problem_bank_generated_v0")}
        unchanged = missing_parent = num_changed = parent_ans_diff = 0
        for r in rows:
            ps = (r.get("relations") or [{}])[0].get("parent_slug")
            p = gen.get(ps)
            if not p:
                missing_parent += 1
                continue
            if p["question_text"] == r["question_text"]:
                unchanged += 1
            nums = lambda s: sorted(re.findall(r"-?\d+(?:/\d+)?", s))  # noqa: E731
            if nums(p["question_text"]) != nums(r["question_text"]):
                num_changed += 1
                res.amb(r, "재진술 발문의 숫자 다중집합이 부모(결정론) 발문과 다름")
            if r["answer"] != p["answer"] or r.get("choices") != p.get("choices"):
                parent_ans_diff += 1
        res.notes["부모(generated_v0) 미발견"] = missing_parent
        res.notes["발문이 부모와 글자까지 동일(무변화 사본)"] = unchanged
        res.notes["부모와 answer/choices 불일치"] = parent_ans_diff
        res.notes["발문 숫자 다중집합이 부모와 다름"] = num_changed
        res.notes["slug가 '-rephrased'로 끝나는 행"] = sum(1 for r in rows if r["slug"].endswith("-rephrased"))
        res.notes["authored_by 값 분포"] = dict(collections.Counter(str(r.get("authored_by")) for r in rows))
    unit_cnt = collections.Counter()
    for r in rows:
        t = r["question_text"]
        unit = (r.get("unit_codes") or [""])[0]
        ans_sym = to_sym(r["answer"])
        try:
            indep, why = solve_text(t)
        except Exception as e:
            indep, why = None, f"독립 계산 예외 {type(e).__name__}"
        if indep is None or ans_sym is None:
            res.unv(r, f"[{unit}] {why or '저장 answer 파싱 불가'}")
            continue
        unit_cnt[unit] += 1
        if corpus == "problem_bank_rephrased_v0" and (
                not any(k in t for k in REQUEST_TOKENS) or any(k in t for k in GARBLE_MARKERS)):
            res.amb(r, "재진술 발문이 비문이거나 값을 요구하는 문장이 아님(정답 방향어는 일치)")
        if same(ans_sym, indep):
            res.ok()
        else:
            res.bad(r, f"[{unit}] 독립 재계산 != 저장 answer", indep)
        check_choices(res, r, indep)
    res.notes["unit별 대조 행"] = dict(unit_cnt)
    res.notes["unit별 전체 행"] = dict(collections.Counter((r.get("unit_codes") or [""])[0] for r in rows))
    return res


def audit_killer(repo: Path) -> Result:
    corpus = "problem_bank_killer_v0"
    rows = load_rows(repo, corpus)
    res = Result(corpus, rows)
    distinct_phrase = double_root = nonreal_rows = 0
    for r in rows:
        t = r["question_text"]
        m = re.fullmatch(r"(이차|삼차)방정식 ([^=]+?) = 0 의 (서로 다른 )?(두|세|모든) 근의 (합|곱)(?:의 값)?을 구하시오\.", t)
        if not m:
            res.unv(r, "템플릿 파싱 실패")
            continue
        deg = 2 if m.group(1) == "이차" else 3
        poly = sympy.Poly(parse_poly(m.group(2)), X)
        if poly.degree() != deg:
            res.unv(r, "차수 불일치(파싱)")
            continue
        distinct = bool(m.group(3))
        agg = m.group(5)
        distinct_phrase += distinct
        coeffs = poly.all_coeffs()
        vieta_sum = -coeffs[1] / coeffs[0]
        vieta_prod = ((-1) ** deg) * coeffs[-1] / coeffs[0]
        roots_c = sympy.roots(sympy.Poly(poly.as_expr(), X, domain="QQ").as_expr(), X, multiple=False)
        if sum(roots_c.values()) != deg:
            res.unv(r, "근을 닫힌형으로 못 구함")
            continue
        has_double = any(mu > 1 for mu in roots_c.values())
        nonreal = [z for z in roots_c if not isreal(z)]
        if distinct:
            val = sum(roots_c.keys()) if agg == "합" else sympy.prod(list(roots_c.keys()))
        else:
            val = vieta_sum if agg == "합" else vieta_prod
        val = sympy.simplify(val)
        ans = to_sym(r["answer"])
        if same(ans, val):
            res.ok()
        else:
            res.bad(r, "독립 재계산 != 저장 answer", val)
        if has_double:
            double_root += 1
            if distinct:
                res.amb(r, "'서로 다른 두 근'인데 중근 존재")
        if nonreal:
            nonreal_rows += 1
            real_roots = [z for z in roots_c if isreal(z)]
            rv = (sum(z * roots_c[z] for z in real_roots) if agg == "합"
                  else sympy.prod([z ** roots_c[z] for z in real_roots]))
            if not same(sympy.simplify(rv), ans):
                res.amb(r, "허근 포함 방정식: '근'을 실근으로만 읽으면 정답이 달라짐")
    res.notes["'서로 다른' 문구 행"] = distinct_phrase
    res.notes["중근 존재 행"] = double_root
    res.notes["허근 포함 행"] = nonreal_rows
    return res


def audit_v1(repo: Path) -> Result:
    corpus = "problem_bank_v1"
    rows = load_rows(repo, corpus)
    res = Result(corpus, rows)
    for r in rows:
        t = r["question_text"]
        ans = to_sym(r["answer"])
        indep = None
        m = re.fullmatch(r"이차방정식 ([^=]+) = 0 의 두 근 중 (큰|작은) 근을 구하시오\.", t)
        if m:
            sols = sorted(sympy.solve(parse_poly(m.group(1)), X), key=lambda z: sympy.N(z))
            indep = sols[-1] if m.group(2) == "큰" else sols[0]
        m = re.fullmatch(r"이차함수 y = ([^의]+) 의 그래프의 축이 직선 x = a 일 때, a 의 값을 구하시오\.", t)
        if m:
            indep = sympy.solve(sympy.diff(parse_poly(m.group(1)), X), X)[0]
        m = re.fullmatch(r"이차방정식 x\^2 = 2x 의 서로 다른 실근의 개수는\?", t)
        if m:
            indep = S(len({z for z in sympy.solve(X**2 - 2 * X, X) if z.is_real}))
        if indep is None:
            res.unv(r, "템플릿 파싱 실패")
            continue
        if same(ans, indep):
            res.ok()
        else:
            res.bad(r, "독립 재계산 != 저장 answer", indep)
        check_choices(res, r, indep)
    return res


# --------------------------------------------------------------------------------------
# 어휘 스캔(부정·한정·방향 표현) / provenance
# --------------------------------------------------------------------------------------

VOCAB = [
    "아닌", "않은", "옳은", "옳지", "틀린", "모두", "모든", "반드시", "항상", "적어도", "이상", "이하", "초과", "미만",
    "제외", "없는", "최대", "최소", "가장 큰", "가장 작은", "큰 근", "작은 근", "서로 다른", "개수", "수렴", "발산",
    "같으면", "다르면", "벡터", "스칼라", "합동", "독립", "극대", "극소", "극댓", "극솟", "중근", "고르시오", "것은?",
    "옳은 것", "나머지", "최소공배수", "반올림", "버림", "올림",
]


def vocab_scan(rows_by_corpus):
    out = {}
    for name, rows in rows_by_corpus.items():
        c = collections.Counter()
        for r in rows:
            q = r["question_text"]
            for w in VOCAB:
                if w in q:
                    c[w] += 1
        out[name] = dict(c)
    return out


def provenance_summary(repo: Path, corpus: str):
    rows = load_rows(repo, corpus)
    p = load_prov(repo, corpus)
    return {
        "generation_method": p.get("generation_method", "")[:160],
        "generation_cli": p.get("generation_cli"),
        "record_count_declared": p.get("record_count"),
        "rows_actual": len(rows),
        "authored_by": dict(collections.Counter(str(r.get("authored_by")) for r in rows)),
        "generation_type": dict(collections.Counter(str(r.get("generation_type")) for r in rows)),
        "review_status": dict(collections.Counter(str(r.get("review_status")) for r in rows)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[3]))
    ap.add_argument("--out", default=None)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    repo = Path(a.repo)
    corpora = [
        "problem_bank_conceptual_v0",
        "problem_bank_misconception_mc_v0",
        "problem_bank_generated_v0",
        "problem_bank_rephrased_v0",
        "problem_bank_killer_v0",
        "problem_bank_v1",
    ]
    results = {
        "problem_bank_conceptual_v0": audit_conceptual(repo),
        "problem_bank_misconception_mc_v0": audit_misconception(repo),
        "problem_bank_generated_v0": audit_text_corpus(repo, "problem_bank_generated_v0"),
        "problem_bank_rephrased_v0": audit_text_corpus(repo, "problem_bank_rephrased_v0"),
        "problem_bank_killer_v0": audit_killer(repo),
        "problem_bank_v1": audit_v1(repo),
    }
    rows_by = {c: load_rows(repo, c) for c in corpora}
    out = {
        "provenance": {c: provenance_summary(repo, c) for c in corpora},
        "summary": {c: results[c].summary() for c in corpora},
        "vocab_scan": vocab_scan(rows_by),
        "mismatch_detail": {c: results[c].mismatch for c in corpora},
        "ambiguous_detail": {c: results[c].ambiguous for c in corpora},
        "unverified_detail": {c: results[c].unverified for c in corpora},
        "struct_fail_detail": {c: results[c].struct_fail for c in corpora},
    }
    for c in corpora:
        s = out["summary"][c]
        print(f"{c}: rows={s['rows']} tpl={s['templates_digit_folded']} compared={s['compared']} "
              f"match={s['match']} mismatch={s['mismatch']} ambiguous={s['ambiguous']} "
              f"unverified={s['unverified']} struct_fail={s['struct_fail']} published={s['is_published_true']}")
        if a.verbose:
            for k in ("mismatch_reasons", "ambiguous_reasons", "unverified_reasons", "struct_fail_reasons", "notes"):
                print("   ", k, s[k])
    if a.out:
        Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    total_mm = sum(len(results[c].mismatch) for c in corpora)
    print("TOTAL_MISMATCH", total_mm)
    return 1 if total_mm else 0


if __name__ == "__main__":
    sys.exit(main())
