"""P3-G2 판정 — 핵심 오개념 12개 중 무작위 3개를 시드 고정으로 뽑는다(재현 가능).

시드 = 판정 기준 main 커밋 해시 앞 8자리(16진수 정수). 결과를 보고 나서 다시 뽑지 않는다.
입력은 python -m whymath_backend.ops.phase3_remediation --json 의 출력 파일이다.
사용: python p3g2_draw.py <remediation.json> <커밋 앞 8자리>
"""

import json
import random
import sys

rows = json.load(open(sys.argv[1], encoding="utf-8"))["rows"]
mids = sorted(r["mis_id"] for r in rows)
seed = int(sys.argv[2], 16)
pick = random.Random(seed).sample(mids, 3)
by = {r["mis_id"]: r for r in rows}
print("seed =", seed, "| 후보", len(mids), "개 | 추출 =", pick)
for m in pick:
    print(m, by[m]["concept_code"], by[m]["status"], by[m]["kebab_id"])
