#!/usr/bin/env python3
"""audit_B_script.py 의 변별력 검증: 발문 의미를 일부러 바꾼 사본에서 대조기가 RED(불일치/설명불일치)를 내는지 확인.
각 뮤테이션은 (a) 적용 행 수>0, (b) 변경 후 텍스트 != 원본 을 단언한다(주입 자체의 실재)."""
import importlib.util, json, re, sys, tempfile, shutil
from pathlib import Path
here = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ab", here / "audit_B_script.py"); ab = importlib.util.module_from_spec(spec); spec.loader.exec_module(ab)
ROOT = Path(__file__).resolve().parents[3] / "data" / "corpus"

def sub1(rx, rep):
    def f(q):
        n = re.sub(rx, rep, q, count=1)
        return n
    return f

MUT = {
 "problem_bank_polynomial_arithmetic_v0": {
   "연산 +→-": lambda q: q.replace("P(x) + Q(x)", "P(x) - Q(x)") if "P(x) + Q(x)" in q else q,
   "연산 -→+": lambda q: q.replace("P(x) - Q(x)", "P(x) + Q(x)") if "P(x) - Q(x)" in q else q,
   "상수↔x의 계수": lambda q: q.replace("상수의 계수", "@@").replace("x의 계수", "상수의 계수").replace("@@", "x의 계수") if "x^" not in q.split("대하여")[1] else q,
 },
 "problem_bank_polynomial_factoring_v0": {"큰↔작은": lambda q: q.replace("더 큰", "@").replace("더 작은", "더 큰").replace("@", "더 작은")},
 "problem_bank_linear_inequality_system_v0": {
   "큰↔작은": lambda q: q.replace("더 큰", "@").replace("더 작은", "더 큰").replace("@", "더 작은"),
   "첫 부등호 반전": lambda q: re.sub(r"(: .+?) > ", r"\1 < ", q, count=1),
 },
 "problem_bank_quad_ineq_v0": {
   "부등호 반전(합은 불변: 설명이 잡아야)": lambda q: q.replace(" > ", " @ ").replace(" < ", " > ").replace(" @ ", " < "),
   "x 계수 부호반전": lambda q: re.sub(r"([+-]) (\d*)x ", lambda m: ("- " if m[1] == "+" else "+ ") + m[2] + "x ", q, count=1),
 },
 "problem_bank_middle_function_v0": {"f(a)의 a를 +1": lambda q: re.sub(r"f\((-?\d+)\)", lambda m: f"f({int(m[1])+1})", q)},
 "problem_bank_radian_conversion_v0": {"각도 +1": lambda q: re.sub(r"일반각 (-?\d+)°", lambda m: f"일반각 {int(m[1])+1}°", q)},
 "problem_bank_complex_number_arithmetic_v0": {
   "실수부↔허수부": lambda q: q.replace("실수부", "@").replace("허수부", "실수부").replace("@", "허수부"),
   "z1-z2 → z2-z1(순서)": lambda q: q.replace("z1 - z2", "z2 - z1"),
 },
 "problem_bank_matrix_ops_v0": {
   "(r행 c열) 전치": lambda q: re.sub(r"\((\d)행 (\d)열\)", lambda m: f"({m[2]}행 {m[1]}열)", q),
   "합→차 기호": lambda q: q.replace("A + B", "A - B"),
 },
}
tmp = Path(tempfile.mkdtemp(prefix="mut_", dir=here))
fail = 0
for d, muts in MUT.items():
    rows = [json.loads(l) for l in (ROOT / d / "problems.jsonl").read_text(encoding="utf-8").splitlines()]
    for name, fn in muts.items():
        out = []; changed = 0
        for r in rows:
            r2 = dict(r); nq = fn(r["question_text"]); r2["question_text"] = nq
            changed += nq != r["question_text"]; out.append(r2)
        assert changed > 0, f"주입 실패(0행 변경): {d} {name}"
        (tmp / d).mkdir(parents=True, exist_ok=True)
        (tmp / d / "problems.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out), encoding="utf-8")
        # 변경된 행만 분모로 쓰기 위해 변경 행 부분 집합 재평가
        chk = ab.CHECKERS[d]; det = 0
        for r, r2 in zip(rows, out):
            if r["question_text"] == r2["question_text"]: continue
            v, _, _, ev = chk(r2)
            det += (v != "OK") or (ev == "EXPL_BAD")
        print(f"{d[13:-3]:32s} {name:34s} 변경 {changed:4d}행 중 검출 {det:4d} ({det/changed:.0%})")
        # 원본 무변경 보장
shutil.rmtree(tmp)
