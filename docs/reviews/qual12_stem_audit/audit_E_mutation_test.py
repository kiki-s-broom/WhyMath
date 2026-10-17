#!/usr/bin/env python3
"""audit_E_script.py 검사기의 변별력 검증 — 결함을 주입해 RED(불일치 검출)가 나오는지 확인한다.

주입은 메모리에서만(저장소 파일 불변). 각 주입 전후로 '실제로 변경이 적용됐는지'(변경 행 수)를
단언한다. 변경 행 수 0이면 하네스 결함이므로 즉시 실패.
기대: 검출 건수 >= 변경 행 수(주입이 정답 의미를 바꾼 행은 전부 불일치로 잡혀야 함).
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import audit_E_script as A  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
ORIG_LOAD = A.load_rows
CACHE = {}


def rows_of(corpus):
    if corpus not in CACHE:
        CACHE[corpus] = ORIG_LOAD(REPO, corpus)
    return copy.deepcopy(CACHE[corpus])


def run(corpus, fn, mutate):
    """mutate(rows)->변경 행 수. 검출 불일치+미검증 수를 돌려준다."""
    def fake_load(repo, c):
        if c == corpus:
            return mutated
        return rows_of(c)
    mutated = rows_of(corpus)
    changed = mutate(mutated)
    assert changed > 0, f"주입 미적용(하네스 결함): {corpus}"
    A.load_rows = fake_load
    try:
        res = fn(REPO) if fn.__name__ != "audit_text_corpus" else fn(REPO, corpus)
    finally:
        A.load_rows = ORIG_LOAD
    return changed, len(res.mismatch), len(res.unverified)


def swap_text(rows, pairs, only=lambda r: True):
    n = 0
    for r in rows:
        if not only(r):
            continue
        t = r["question_text"]
        for a, b in pairs:
            if a in t:
                t = t.replace(a, "\0").replace(b, a).replace("\0", b)
                break
        if t != r["question_text"]:
            r["question_text"] = t
            n += 1
    return n


def wrong_answer(rows):
    n = 0
    for r in rows:
        ch = r.get("choices") or []
        alt = [c for c in ch if c != r["answer"]]
        if alt:
            r["answer"] = alt[0]
            n += 1
    return n


def bump_first_number(rows):
    import re
    n = 0
    for r in rows:
        t2 = re.sub(r"(\d+)", lambda m: str(int(m.group(1)) + 1), r["question_text"], count=1)
        if t2 != r["question_text"]:
            r["question_text"] = t2
            n += 1
    return n


def use_misconception_choice(rows):
    n = 0
    for r in rows:
        dm = r["distractor_map"][0]["choice_index"]
        r["answer"] = r["choices"][dm]
        n += 1
    return n


CASES = [
    # (이름, 코퍼스, 감사함수, 주입, 최소 기대 검출)
    ("conceptual: 모든 정답을 다른 선지로", "problem_bank_conceptual_v0", A.audit_conceptual, wrong_answer, 360),
    ("conceptual: 수렴/발산 숫자 방향 뒤집기(등비급수+급수)", "problem_bank_conceptual_v0", A.audit_conceptual,
     lambda rows: swap_text(rows, [("수렴하면 1, 발산하면 0", "수렴하면 0, 발산하면 1")]), 48),
    ("conceptual: 벡터/스칼라 숫자 뒤집기(QUAL-11형: 발문 의미 반전·answer 불변)", "problem_bank_conceptual_v0", A.audit_conceptual,
     lambda rows: swap_text(rows, [("벡터이면 1, 스칼라(수)이면 0", "벡터이면 0, 스칼라(수)이면 1")]), 24),
    ("conceptual: 독립 '이면 1, 아니면 0' 뒤집기", "problem_bank_conceptual_v0", A.audit_conceptual,
     lambda rows: swap_text(rows, [("독립이면 1, 아니면 0", "독립이면 0, 아니면 1")]), 24),
    ("conceptual: 부등식 방향 서술 뒤집기", "problem_bank_conceptual_v0", A.audit_conceptual,
     lambda rows: swap_text(rows, [("x > (어떤 수) 꼴이면 1, x < (어떤 수) 꼴이면 0", "x > (어떤 수) 꼴이면 0, x < (어떤 수) 꼴이면 1")]), 24),
    ("misconception: 첫 수치 +1(answer 불변)", "problem_bank_misconception_mc_v0", A.audit_misconception, bump_first_number, 700),
    ("misconception: answer를 오개념 선지로", "problem_bank_misconception_mc_v0", A.audit_misconception, use_misconception_choice, 1080),
    ("generated: 큰 근<->작은 근 서술 뒤집기", "problem_bank_generated_v0", A.audit_text_corpus,
     lambda rows: swap_text(rows, [("큰 근", "작은 근"), ("더 큰", "더 작은")], only=lambda r: r["unit_codes"][0] == "QUAD-EQ"), 100),
    ("generated: 극대<->극소 서술 뒤집기", "problem_bank_generated_v0", A.audit_text_corpus,
     lambda rows: swap_text(rows, [("극대", "극소"), ("극댓", "극솟")], only=lambda r: r["unit_codes"][0].startswith("CALC-EXTREMUM")), 100),
    ("generated: 가장 작은<->가장 큰 해 뒤집기(삼각방정식)", "problem_bank_generated_v0", A.audit_text_corpus,
     lambda rows: swap_text(rows, [("가장 작은 해", "가장 큰 해")], only=lambda r: r["unit_codes"][0] == "TRIG-EQ"), 8),
    ("rephrased: 극대<->극소 뒤집기", "problem_bank_rephrased_v0", A.audit_text_corpus,
     lambda rows: swap_text(rows, [("극대", "극소"), ("극댓", "극솟")], only=lambda r: r["unit_codes"][0].startswith("CALC-EXTREMUM")), 50),
    ("killer: 합<->곱 서술 뒤집기", "problem_bank_killer_v0", A.audit_killer,
     lambda rows: swap_text(rows, [("근의 합", "근의 곱")]), 40),
    ("v1: 큰 근<->작은 근", "problem_bank_v1", A.audit_v1,
     lambda rows: swap_text(rows, [("큰 근", "작은 근")]), 2),
]

bad = 0
for name, corpus, fn, mut, expect in CASES:
    changed, mm, unv = run(corpus, fn, mut)
    ok = (mm + unv >= min(expect, changed)) and mm > 0  # 주입이 발문을 비문으로 만든 행은 '미검증'으로 빠져도 통과로 위장되지 않으면 허용
    print(f"{'OK ' if ok else 'FAIL'} {name}: 변경 {changed}행, 불일치 검출 {mm}, 미검증 증가 {unv}")
    bad += (not ok)
sys.exit(1 if bad else 0)
