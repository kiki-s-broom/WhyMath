#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QUAL-12 감사 슬라이스 A — 템플릿 코퍼스 발문↔정답 의미 대조 (독립 구현).

원칙
- 생성기 모듈(l3/equivalent/*_skeleton_generator.py, harness/*_batch.py)은 import/호출하지 않는다.
- 표준 라이브러리만 사용(정수/Decimal 산술로 충분해 sympy 불요).
- 정답은 question_text 만 파싱해 재계산한다(answer·verify 는 대조 대상으로만 읽는다).
- 샘플링 없음: 전 행 대조. 파싱 실패/독립 계산 불가 행은 'unverified' 로 따로 센다.
- 스캔 0건 코퍼스는 FAIL.

사용: python3 audit_A_script.py [--json out.json] [--repo /home/user/WhyMath]
종료 코드: 불일치/미검증/설명불일치/스캔 0건이 있으면 1, 아니면 0.
"""
import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

CORPORA = [
    "problem_bank_elementary_v0",
    "problem_bank_elementary_area_measure_v0",
    "problem_bank_elementary_division_remainder_v0",
    "problem_bank_elementary_gcd_lcm_v0",
    "problem_bank_elementary_rounding_v0",
    "problem_bank_elementary_volume_measure_v0",
    "problem_bank_measurement_unit_conversion_v0",
]

# ---------------------------------------------------------------- 의미 어휘
VOCAB = {
    "자릿수지시": r"자리",
    "방향어(올림/버림/반올림)": r"반올림|올림|버림",
    "이상이하초과미만": r"이상|이하|초과|미만",
    "~까지/~에서": r"까지|에서",
    "몫/나머지/나눗셈": r"몫|나머지|÷|나누",
    "약수/배수": r"최대공약수|최소공배수",
    "변/둘레/넓이/부피/원주": r"겉넓이|넓이|부피|원주|둘레",
    "도형 치수어(가로/세로/높이/지름)": r"가로|세로|높이|지름|반지름",
    "단위": r"cm|mm|km|kg|mL|L|m\^|\bm\b|\bg\b|\^",
    "연산 방향어(합/차/더하/뺀)": r"합|차를|더하|뺀|\+|\-",
}


def vocab_of(text):
    return sorted(k for k, p in VOCAB.items() if re.search(p, text))


# ---------------------------------------------------------------- 유틸
def D(s):
    return Decimal(str(s))


def dnorm(x):
    x = D(x)
    if x == x.to_integral_value():
        return str(int(x))
    return format(x.normalize(), "f")


def same_number(a, b):
    try:
        return D(a) == D(b)
    except (InvalidOperation, ValueError):
        return False


def last_number_before_ida(expl):
    m = re.search(r"(\d[\d.]*?)(?:cm)?\s*이다\.$", expl.strip())
    return m.group(1) if m else None


# 단위 환산(교과서 통상 해석) : from -> to 의 1차 배율
UNIT_FACTOR = {
    ("m", "cm"): 100,
    ("km", "m"): 1000,
    ("cm", "mm"): 10,
    ("L", "mL"): 1000,
    ("kg", "g"): 1000,
}

PLACES = {"일": 1, "십": 10, "백": 100, "천": 1000, "만": 10000}
PLACE_LOWER = {"십": "일", "백": "십", "천": "백", "만": "천"}


class R:
    def __init__(self, status, expected=None, alt=None, note="", kind=""):
        self.status = status  # compute | unverified
        self.expected = expected
        self.alt = alt  # 해석이 갈리는 경우 대안 해석값
        self.info_alt = None  # 모호 판정에는 쓰지 않는 정보용 대안값
        self.note = note
        self.kind = kind


# ---------------------------------------------------------------- 코퍼스별 독립 계산
def calc_addsub(q):
    m = re.fullmatch(r"다음을 계산하시오: (\d+) \+ (\d+)", q)
    if m:
        return R("compute", D(int(m[1]) + int(m[2])), kind="add-expr"), (int(m[1]), int(m[2]), "add")
    m = re.fullmatch(r"다음을 계산하시오: (\d+) - (\d+)", q)
    if m:
        return R("compute", D(int(m[1]) - int(m[2])), kind="sub-expr"), (int(m[1]), int(m[2]), "sub")
    m = re.fullmatch(r"(\d+)에서 (\d+)[을를] 뺀 값을 구하시오\.", q)
    if m:
        return R("compute", D(int(m[1]) - int(m[2])), kind="A에서B를뺀"), (int(m[1]), int(m[2]), "sub")
    m = re.fullmatch(r"(\d+)[과와] (\d+)의 차를 구하시오\.", q)
    if m:
        a, b = int(m[1]), int(m[2])
        # 통상: 두 수의 차 = 큰 수 - 작은 수(양수). 대안: 앞 - 뒤(부호 포함)
        r = R("compute", D(abs(a - b)), kind="A와B의차")
        if a < b:
            r.alt = D(a - b)
            r.note = "ambig-차(A<B)"
        return r, (a, b, "diff")
    m = re.fullmatch(r"(\d+)에 (\d+)[을를] 더하면 얼마입니까\?", q)
    if m:
        return R("compute", D(int(m[1]) + int(m[2])), kind="A에B를더하면"), (int(m[1]), int(m[2]), "add")
    m = re.fullmatch(r"(\d+)[과와] (\d+)의 합을 구하시오\.", q)
    if m:
        return R("compute", D(int(m[1]) + int(m[2])), kind="A와B의합"), (int(m[1]), int(m[2]), "add")
    return None, None


def expl_addsub(expl, ctx, ans):
    a, b, op = ctx
    nums = re.findall(r"\d+", expl)
    kw_add = "더하" in expl
    kw_sub = "빼" in expl
    want_add = op == "add"
    if (want_add and not kw_add) or (not want_add and not kw_sub):
        return False, "연산어 불일치"
    if nums[:2] != [str(a), str(b)] and set(nums[:2]) != {str(a), str(b)}:
        return False, "피연산자 불일치"
    return True, ""


UNITS = r"(km|m|cm|mm|L|mL|kg|g)"


def parse_unit(q):
    pats = [
        rf"(\d+){UNITS}(?:\^(\d))?[를을] {UNITS}(?:\^(\d))?[로으]로? ?나타내면 얼마인지 구하시오\.",
        rf"(\d+){UNITS}(?:\^(\d))?[는은] 몇 {UNITS}(?:\^(\d))?인지 구하시오\.",
        rf"(\d+){UNITS}(?:\^(\d))?[를을] {UNITS}(?:\^(\d))?로 나타내면 얼마인지 구하시오\.",
    ]
    for p in pats:
        m = re.fullmatch(p, q)
        if m:
            v, f, e1, t, e2 = m.groups()
            return int(v), f, t, int(e1) if e1 else 1, int(e2) if e2 else 1
    return None


def calc_unit(q):
    u = parse_unit(q)
    if not u:
        return None, None
    v, f, t, e1, e2 = u
    if e1 != e2 or (f, t) not in UNIT_FACTOR:
        return R("unverified", note="단위/지수 불일치 또는 표 밖 단위쌍"), None
    return R("compute", D(v) * D(UNIT_FACTOR[(f, t)]) ** e1, kind=f"{f}^{e1}->{t}^{e1}"), (v, f, t, e1)


def expl_unit(expl, ctx, ans):
    v, f, t, e1 = ctx
    sup = f"^{e1}" if e1 > 1 else ""
    pat = rf"{re.escape(f)}{re.escape(sup)}[를은는] {re.escape(t)}{re.escape(sup)}[로으]+ 바꿀 때는 정해진 배율을 곱하므로"
    if not re.match(pat, expl):
        return False, "설명의 단위쌍이 발문과 다름"
    return True, ""


def calc_area(q):
    m = re.fullmatch(r"가로가? (\d+)cm, 세로가? (\d+)cm, 높이가? (\d+)cm인 직육면체(?: 모양 상자)?의 겉넓이를 구하시오\.", q)
    if m:
        a, b, c = map(int, m.groups())
        return R("compute", D(2 * (a * b + b * c + c * a)), kind="직육면체겉넓이"), ("surface", a, b, c)
    return calc_unit(q)


def calc_volume(q):
    m = re.fullmatch(r"가로가? (\d+)cm, 세로가? (\d+)cm, 높이가? (\d+)cm인 직육면체(?: 모양 상자)?의 부피를 구하시오\.", q)
    if m:
        a, b, c = map(int, m.groups())
        return R("compute", D(a * b * c), kind="직육면체부피"), ("vol", a, b, c)
    m = re.fullmatch(r"지름이 (\d+)cm인 원이 있다\. 원주율을 ([\d.]+)로 할 때, 이 원의 원주를 구하시오\.", q)
    if not m:
        m = re.fullmatch(r"지름이 (\d+)cm인 원의 원주를 구하시오\. \(원주율은 ([\d.]+)로 계산한다\.\)", q)
    if m:
        d, pi = int(m[1]), m[2]
        return R("compute", D(d) * D(pi), kind="원주=지름x원주율"), ("circ", d, pi)
    return calc_unit(q)


def expl_area(expl, ctx, ans):
    if ctx[0] == "surface":
        ok = "겉넓이" in expl and "2배" in expl
        return ok, "" if ok else "겉넓이/2배 문구 불일치"
    return expl_unit(expl, ctx, ans)


def expl_volume(expl, ctx, ans):
    if ctx[0] == "vol":
        ok = "부피" in expl and "곱하" in expl
        return ok, "" if ok else "부피/곱 문구 불일치"
    if ctx[0] == "circ":
        ok = "원주" in expl and "지름" in expl and f"({ctx[2]})" in expl
        return ok, "" if ok else "원주/지름/원주율 값 문구 불일치"
    return expl_unit(expl, ctx, ans)


def calc_div(q):
    m = re.fullmatch(r"(\d+)÷(\d+)의 (몫|나머지)[을를] 구하시오\.", q)
    if not m:
        m = re.fullmatch(r"(\d+)[을를] (\d+)(?:으로|로) 나누었을 때의 (몫|나머지)[을를] 구하시오\.", q)
    if m:
        a, b, k = int(m[1]), int(m[2]), m[3]
        if b == 0:
            return R("unverified", note="0으로 나눔"), None
        qq, rr = divmod(a, b)
        return R("compute", D(qq if k == "몫" else rr), kind=k), (a, b, k)
    return None, None


def expl_div(expl, ctx, ans):
    k = ctx[2]
    m = re.search(r"구하는 (몫|나머지)[은는]", expl)
    if not m or m[1] != k:
        return False, "설명의 대상(몫/나머지)이 발문과 다름"
    return True, ""


def calc_gcd(q):
    m = re.fullmatch(r"(?:두 수 )?(\d+)[과와] (\d+)의 (최대공약수|최소공배수)를 구하시오\.", q)
    if m:
        a, b, k = int(m[1]), int(m[2]), m[3]
        g = math.gcd(a, b)
        return R("compute", D(g if k == "최대공약수" else a * b // g), kind=k), (a, b, k)
    return None, None


def expl_gcd(expl, ctx, ans):
    k = ctx[2]
    m = re.search(r"구하는 (최대공약수|최소공배수)는", expl)
    if not m or m[1] != k:
        return False, "설명 대상 불일치"
    if k == "최대공약수" and "가장 큰 수" not in expl:
        return False, "정의 문구 불일치"
    if k == "최소공배수" and "가장 작은 수" not in expl:
        return False, "정의 문구 불일치"
    return True, ""


def round_std(n, op, pv):
    """표준 해석: 'X의 자리까지 나타내면' = X의 자리 숫자까지 남김(결과는 pv 의 배수)."""
    if op == "버림":
        return n // pv * pv
    if op == "올림":
        return -(-n // pv) * pv
    low = n % pv
    base = n - low
    return base + pv if low * 2 >= pv else base


def calc_rounding(q):
    m = re.fullmatch(r"(\d+)[을를] (올림|버림|반올림)하여 (일|십|백|천|만)의 자리까지 나타내면 얼마인지 구하시오\.", q)
    if not m:
        return None, None
    n, op, pl = int(m[1]), m[2], m[3]
    pv = PLACES[pl]
    r = R("compute", D(round_std(n, op, pv)), kind=f"{op}/{pl}")
    # 대안(QUAL-11 사고형 해석): 'X의 자리에서 ~' = X 자리 숫자 자체를 처리 → 결과는 pv/10 의 배수
    # 발문이 '~까지'로 명시돼 해석이 갈리지 않으므로 상태(ambiguous) 판정에는 쓰지 않고 정보 집계(info_alt)로만 쓴다.
    r.info_alt = D(round_std(n, op, pv // 10)) if pv >= 10 else D(n)
    return r, (n, op, pl)


def expl_rounding(expl, ctx, ans):
    n, op, pl = ctx
    m = re.match(r"(\S)의 자리까지 나타낼 때는 (\S)의 자리 (이하를 무조건 (올려|버려)서|숫자가 5 이상이면 올리고 5 미만이면 버려서)", expl)
    if not m:
        return False, "설명 문형 파싱 불가"
    if m[1] != pl:
        return False, "설명 자리 ≠ 발문 자리"
    if m[2] != PLACE_LOWER.get(pl, ""):
        return False, "설명 기준 자리가 발문 자리의 바로 아래가 아님"
    want = {"올림": "올려", "버림": "버려", "반올림": "5 이상"}[op]
    if want not in m[3]:
        return False, "설명의 처리 방향이 발문과 다름"
    return True, ""


CONF = {
    "problem_bank_elementary_v0": (calc_addsub, expl_addsub),
    "problem_bank_elementary_area_measure_v0": (calc_area, expl_area),
    "problem_bank_elementary_division_remainder_v0": (calc_div, expl_div),
    "problem_bank_elementary_gcd_lcm_v0": (calc_gcd, expl_gcd),
    "problem_bank_elementary_rounding_v0": (calc_rounding, expl_rounding),
    "problem_bank_elementary_volume_measure_v0": (calc_volume, expl_volume),
    "problem_bank_measurement_unit_conversion_v0": (calc_unit, expl_unit),
}


# ---------------------------------------------------------------- 메인 감사
def audit(repo):
    out = {}
    for d in CORPORA:
        path = Path(repo) / "data" / "corpus" / d / "problems.jsonl"
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        calc, expl_fn = CONF[d]
        tmpl = Counter()
        tmpl_vocab = {}
        s = Counter()
        samples = defaultdict(list)
        vocab_rows = 0
        vocab_compared = Counter()
        expl_c = Counter()
        meta = Counter()
        alt_hits = Counter()
        edge = Counter()
        info = Counter()  # 변별력(비변별 행)·서술 관찰 등 정보 지표(판정 아님)
        pair_kinds = defaultdict(set)
        for r in rows:
            q, ans, ex = r["question_text"], r["answer"], r.get("answer_explanation", "")
            t = re.sub(r"\d+(?:\.\d+)?", "#", q)
            tmpl[t] += 1
            vv = vocab_of(t)
            tmpl_vocab[t] = vv
            has_v = bool(vv)
            vocab_rows += has_v
            if r.get("is_published"):
                meta["published"] += 1
            try:
                dv = D(ans)
                if r.get("answer_format") == "자연수" and not (dv == dv.to_integral_value() and dv >= 0):
                    meta["answer_format_자연수인데_비자연수"] += 1
                if dnorm(dv) != ans:
                    meta["answer_문자열_비정규"] += 1
            except InvalidOperation:
                meta["answer_비수치"] += 1
            vm = (r.get("verify") or {}).get("answer_map", {})
            if vm and not same_number(vm.get("x", "nan"), ans):
                meta["verify.answer_map_x_≠_answer"] += 1

            res, ctx = calc(q)
            if res is None or res.status == "unverified":
                s["unverified"] += 1
                if has_v:
                    vocab_compared["unverified"] += 1
                samples["unverified"].append((q, ans, None, "발문 파싱 실패" if res is None else res.note))
                continue
            exp = res.expected
            alt = res.alt
            if alt is not None and same_number(alt, exp):
                alt = None
            if same_number(exp, ans):
                if alt is not None:
                    st = "ambiguous"
                    alt_hits["표준 해석과 일치"] += 1
                    samples["ambiguous"].append((q, ans, f"표준={dnorm(exp)} / 대안={dnorm(alt)}", res.note + " (저장값=표준)"))
                else:
                    st = "match"
            elif alt is not None and same_number(alt, ans):
                st = "ambiguous"
                alt_hits["대안 해석과 일치(표준과 불일치)"] += 1
                samples["ambiguous"].append((q, ans, f"표준={dnorm(exp)} / 대안={dnorm(alt)}", res.note + " (저장값=대안)"))
            else:
                st = "mismatch"
                samples["mismatch"].append((q, ans, dnorm(exp), res.kind))
            s[st] += 1
            if has_v:
                vocab_compared[st] += 1
            # 반올림 계열: 사고형(‘~에서’식) 해석과 일치하는 행 수(정보), 자리 배수 경계행
            if d.endswith("rounding_v0"):
                n, op, pl = ctx
                pv = PLACES[pl]
                if res.info_alt is not None and same_number(res.info_alt, ans) and not same_number(exp, ans):
                    alt_hits["QUAL-11형(자리에서) 해석 일치(표준 불일치)"] += 1
                if res.info_alt is not None and same_number(res.info_alt, ans):
                    alt_hits["저장값이 QUAL-11형 해석값과도 같음(두 해석이 겹침)"] += 1
                if op == "올림" and n % pv == 0:
                    edge["올림 대상이 이미 자리 배수 ('무조건 올려서' 문자 해석과 ceiling 이 갈리는 경계행)"] += 1
                if op == "버림" and n % pv == 0:
                    edge["버림 대상이 이미 자리 배수"] += 1
            # 정보 지표: 해석을 바꿔도 같은 정답이 나오는(=오해석을 못 잡는) 행
            if d.endswith("division_remainder_v0"):
                a_, b_, k_ = ctx
                if a_ // b_ == a_ % b_:
                    info["몫==나머지(몫/나머지 취급을 뒤바꿔도 정답이 같은 행)"] += 1
                pair_kinds[(a_, b_)].add(k_)
            if d.endswith("rounding_v0"):
                n, op, pl = ctx
                pv = PLACES[pl]
                variants = {o: round_std(n, o, pv) for o in ("올림", "버림", "반올림")}
                if len({variants[o] for o in variants}) == 1:
                    info["올림=버림=반올림 동값(방향어를 바꿔도 정답이 같은 행)"] += 1
                if sum(1 for o in variants if variants[o] == int(D(ans))) >= 2:
                    info["방향어 2개 이상이 같은 정답을 내는 행"] += 1
            if d.endswith("elementary_v0") and "빼면" in ex:
                info["뺄셈 설명이 'A과/와 B를 빼면' 형태(순서·'에서' 표지 없음, 수치는 정확)"] += 1
            # 설명 대조
            if expl_fn:
                ok, why = expl_fn(ex, ctx, ans)
                num = last_number_before_ida(ex)
                if ok and num is not None and not same_number(num, ans):
                    ok, why = False, "설명 속 결과값 ≠ answer"
                if ok and num is None:
                    ok, why = False, "설명에서 결과값 추출 불가"
                if ok and not same_number(num, exp):
                    ok, why = False, "설명 속 결과값 ≠ 독립계산"
                if ok:
                    expl_c["ok"] += 1
                else:
                    expl_c["bad"] += 1
                    samples["expl_bad"].append((q, ans, ex, why))
        if pair_kinds:
            info["고유 (A,B) 쌍"] = len(pair_kinds)
            info["몫·나머지 둘 다 출제된 쌍"] = sum(1 for v in pair_kinds.values() if len(v) == 2)
            info["몫==나머지인 쌍"] = sum(1 for (a_, b_) in pair_kinds if a_ // b_ == a_ % b_)
        out[d] = dict(
            info=dict(info),
            rows=len(rows),
            templates=len(tmpl),
            template_table=[(t, n, tmpl_vocab[t]) for t, n in tmpl.most_common()],
            vocab_templates=[(t, n, tmpl_vocab[t]) for t, n in tmpl.most_common() if tmpl_vocab[t]],
            vocab_rows=vocab_rows,
            vocab_compared=dict(vocab_compared),
            status=dict(s),
            expl=dict(expl_c),
            meta=dict(meta),
            alt_hits=dict(alt_hits),
            edge=dict(edge),
            samples={k: v[:5] for k, v in samples.items()},
            sample_counts={k: len(v) for k, v in samples.items()},
            published=meta.get("published", 0),
        )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[3]))
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    res = audit(a.repo)
    bad = False
    for d, v in res.items():
        st = v["status"]
        compared = st.get("match", 0) + st.get("mismatch", 0) + st.get("ambiguous", 0)
        print(f"== {d}: rows={v['rows']} templates={v['templates']} compared={compared} "
              f"match={st.get('match', 0)} mismatch={st.get('mismatch', 0)} ambiguous={st.get('ambiguous', 0)} "
              f"unverified={st.get('unverified', 0)} published={v['published']}")
        print(f"   vocab_rows={v['vocab_rows']} vocab_compared={v['vocab_compared']} expl={v['expl']}")
        print(f"   meta={v['meta']} alt_hits={v['alt_hits']} edge={v['edge']}")
        print(f"   info={v['info']}")
        for k, lst in v["samples"].items():
            for s_ in lst:
                print(f"   [{k} x{v['sample_counts'][k]}] {s_}")
        if v["rows"] == 0 or compared == 0:
            print("   FAIL: 스캔 0건")
            bad = True
        if st.get("mismatch", 0) or st.get("unverified", 0) or v["expl"].get("bad", 0):
            bad = True
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
