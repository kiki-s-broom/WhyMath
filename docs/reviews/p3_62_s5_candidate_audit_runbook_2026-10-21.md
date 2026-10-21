# P3-62 후보 은행 S5 감사·승격 런북 (지휘 세션용)

판정 기준: main 25898155 (+ 이 브랜치 `claude/p3-62-solution-qa-structuring`의 P3-62 코드 커밋)

이 문서는 규칙 (가) **후보 은행**(감사 전)을 새 회차 S5 감사에 올리고, 통과하면 승인 은행으로 승격하는 절차다.
실행 주체는 **에이전트를 띄울 수 있는 지휘 세션**이다. 판정자 A·B가 Claude 에이전트 판정자이기 때문이다(qualification/README
"격리의 한계" 서술). 이 컨테이너에는 LLM 키가 없고 로컬 LLM(Ollama)도 없다. P3-62 서브에이전트는 하위 에이전트를 띄울 수 없다.
**Kiki 머신(Phaiakes9)은 필요 없다.** 모든 단계가 세션 안에서 돌고, Kiki의 몫은 승격 승인(결정)뿐이다.

판정 규칙은 기존 회차와 같다. 지침 `docs/data/p3_calculus1_diff_audit/qualification/rater_protocol.md`
(sha256 `3046a901…`, 매니페스트에 기록됨)를 쓰고, 프로토콜 합집합(기계 ∪ 판정자 A ∪ 판정자 B)으로 결함을 센다.
S5 = Wilson 단측 97.5% 상한(k, n) ÷ 검출률 단측 97.5% 하한(0.96898) ≤ 0.02이다.

| 은행 | n | 통과 조건 | 묶음 |
|---|---|---|---|
| `problem_bank_p3_calculus1_diff_v0` 후보 | 504 | k ≤ 3 | 63건 × 8 |
| `problem_bank_p3_fill_v0` 후보 | 204 | **k = 0만** 통과 | 51건 × 4 |

## 0. 사전 확인

- 실행 코드가 P3-62 커밋을 포함하는지 본다. `git log -1 --oneline`과 `python -c "import whymath_backend, sys; print(whymath_backend.__file__)"`로 확인한다.
  - 미머지 상태면 이 브랜치 HEAD에서 `git worktree add --detach <임시경로> <커밋>`으로 돌린다.
- 승인 은행 두 개는 **이 런북에서 한 바이트도 바꾸지 않는다.** 바꾸는 것은 §5 승격 단계(별도 태스크·PR)뿐이다.

## 1. 후보 재생성 (결정론)

```bash
cd <저장소>/src/backend
export PYTHONPATH=$PWD:$PWD/../data-pipeline
OUT=/tmp/p362_candidate   # 저장소 밖 — 승인 은행 자리에는 CLI 가 쓰기를 거부한다(WRITE_REFUSED, exit 2)
python -m whymath_backend.harness.p3_calculus1_diff_batch --structure-final-step --out-dir $OUT/problem_bank_p3_calculus1_diff_v0; echo "CALC_EXIT=$?"
python -m whymath_backend.harness.p3_fill_batch --structure-final-step --out-dir $OUT/problem_bank_p3_fill_v0; echo "FILL_EXIT=$?"
sha256sum $OUT/problem_bank_p3_calculus1_diff_v0/problems.jsonl $OUT/problem_bank_p3_fill_v0/problems.jsonl
```

- **성공 기준**: 두 명령 모두 exit 0이고(수용 게이트 거부 0건), sha256이 보고서 §B-2의 값과 같아야 한다.
- **실패 시**: 해시가 다르면 실행 코드가 다른 것이다. 감사로 넘어가지 않는다(감사받은 바이트와 승격할 바이트가 갈라진다).
- 소요 시간: 약 3.5분이다(calc 약 2분 20초, fill 약 1분 10초).

## 2. 판정자 묶음·기계 라벨

```bash
M=whymath_backend.harness.p3_audit_qualification
A=/tmp/p362_audit
python -m $M bank-sheets --bank $OUT/problem_bank_p3_calculus1_diff_v0/problems.jsonl --seed 20261008 --shards 8 --out-dir $A/calc/sheets --manifest $A/calc/manifest.json --expected-size 504 --task P3-62-solution-qa-unverifiable-structuring --bank-label candidate/problem_bank_p3_calculus1_diff_v0/problems.jsonl; echo "SHEETS_CALC_EXIT=$?"
python -m $M bank-sheets --bank $OUT/problem_bank_p3_fill_v0/problems.jsonl --seed 20261008 --shards 4 --out-dir $A/fill/sheets --manifest $A/fill/manifest.json --expected-size 204 --task P3-62-solution-qa-unverifiable-structuring --bank-label candidate/problem_bank_p3_fill_v0/problems.jsonl; echo "SHEETS_FILL_EXIT=$?"
python -m $M machine --input $OUT/problem_bank_p3_calculus1_diff_v0/problems.jsonl --out $A/calc/machine_labels.jsonl --id-field problem_id; echo "MACHINE_CALC_EXIT=$?"
python -m $M machine --input $OUT/problem_bank_p3_fill_v0/problems.jsonl --out $A/fill/machine_labels.jsonl --id-field problem_id; echo "MACHINE_FILL_EXIT=$?"
```

- P3-62 실측(2026-10-21): 네 명령 모두 exit 0이었다. 기계 결함 판정은 calc 0/504, fill 0/204였다(보고서 §B-4).
- 판정자 라벨 없이 `s5`를 부르면 `QualificationInputError`(판정자 2명 미만)로 exit 2가 난다. 통과로 위장하지 않는다는 뜻이다.

## 3. 판정자 실행 (지휘 세션이 서브에이전트로)

판정자는 **calc 16명(8묶음 × A·B)과 fill 8명(4묶음 × A·B)**이다. 묶음마다 서로 다른 두 판정자가 따로 판정한다.

**격리 규칙(어기면 측정 무효):**
- 판정자 폴더에는 `rater_protocol.md` 사본과 그 판정자의 묶음 파일 하나만 둔다. 저장소 밖 빈 폴더여야 한다.
- 판정자는 저장소·은행·생성기·판정기·기계 라벨·다른 판정자 결과를 읽지 않는다.
- 같은 묶음의 A와 B는 서로의 결과를 보지 않는다.

**판정자 지시문 (모든 판정자 공통 — 폴더 경로만 바꾼다):**

> 당신은 수학 문항 감사 판정자다. 이 폴더의 `rater_protocol.md`를 먼저 끝까지 읽고 그 지침만 따른다.
> 같은 폴더의 `shardN.jsonl`에 든 문항을 한 건씩 판정한다. 정답은 발문만 보고 직접 새로 푼다.
> 이 폴더 밖의 어떤 파일도 열지 않는다(저장소·코드·다른 판정 결과 금지).
> 산출물은 둘이다.
> ① `labels.jsonl` — 줄마다 `{"item_id": "…", "verdict": "ok" | "defect", "defect_class": "…"}`. 받은 문항 전부를 중복 없이 적는다.
> ② `evidence.md` — 결함마다 문항 id·분류·확신도(확실/중간/불확실)·근거(발문 인용 + 직접 푼 값과 문항 값).
> 확신이 낮은 의심도 `defect`로 표시하고 근거에 "불확실"이라고 적는다.

**산출 검사(세션):**
- 판정자별 줄 수가 묶음 크기(63 또는 51)와 같은지 본다.
- id가 고유하고 입력 집합과 같은지 본다.
- `verdict` 값이 ok 또는 defect뿐인지 본다.
- 묶음별 A 라벨을 합쳐 `rater_A.jsonl`을, B 라벨을 합쳐 `rater_B.jsonl`을 만든다(은행별).

## 4. S5 판정

```bash
Q=<저장소>/docs/data/p3_calculus1_diff_audit/qualification/score.json
python -m $M s5 --bank $OUT/problem_bank_p3_calculus1_diff_v0/problems.jsonl --machine $A/calc/machine_labels.jsonl --llm $A/calc/rater_A.jsonl --llm $A/calc/rater_B.jsonl --qualification $Q --expected-size 504 --label "P3-62 후보 calc"; echo "S5_CALC_EXIT=$?"
python -m $M s5 --bank $OUT/problem_bank_p3_fill_v0/problems.jsonl --machine $A/fill/machine_labels.jsonl --llm $A/fill/rater_A.jsonl --llm $A/fill/rater_B.jsonl --qualification $Q --expected-size 204 --label "P3-62 후보 fill"; echo "S5_FILL_EXIT=$?"
```

- exit 0이면 그 은행의 승인 근거가 성립한다. exit 1이면 불합격이다. exit 2는 입력 오류다.
- **as-found**: 결과를 고치려고 같은 은행을 다시 채점하지 않는다. 결함 문항만 걸러 내고 나머지를 승인하지도 않는다
  (`docs/standards/review_status_stamping_contract.md` §5.3).
- 불합격이면 결함 원인을 생성기에서 고친다. 그러면 새 은행이 되므로 §1부터 새 회차로 다시 한다.
  승인 은행은 그대로 둔다(분모·승인 불변).

## 5. 승격 (두 은행 모두 exit 0일 때만 · 별도 태스크·PR · Kiki 승인)

P3-62의 허용 경로 밖(`docs/data/`·승인 각인 백필)을 건드리므로 **새 태스크로 등재해 진행**한다(`backlog.py add`).
한 PR에서 아래를 함께 바꿔야 결속 테스트·드리프트 검사가 green이다.

1. 감사 기록을 새 회차 폴더에 둔다.
   - calc: `docs/data/p3_calculus1_diff_audit/bank_audit_r6/`
   - fill: `docs/data/p3_fill_audit/bank_audit_r4/`
   - 각 폴더에 `audited_bank.jsonl`(= §1 후보 바이트), `manifest.json`, `machine_labels.jsonl`, `llm_labels/`, `s5_result.txt`, `README.md`를 둔다.
2. 결속 테스트의 동결 사본 경로를 새 회차로 바꾼다.
   - 대상: `tests/backend/l1/test_p3_calculus1_diff_bank_coverage_link.py`·`test_p3_fill_bank_coverage_link.py`의 `_AUDITED_BANK`.
3. 코퍼스 단위 감사 라벨을 새 회차 합집합으로 갱신한다.
   - 대상: `docs/data/corpus_audit_p3_calculus1_diff_v0.jsonl`·`corpus_audit_p3_fill_v0.jsonl`.
4. 은행 자리에 후보를 쓴다.
   - 그 전에 배치의 **기본값을 구조화로** 바꾸는 코드 변경이 필요하다. 1줄 + 거부 가드 조정이다.
   - 이유: `--check`는 기본 모드 출력과 비교하므로, 기본이 꺼져 있으면 승격된 은행이 곧 드리프트가 된다.
5. 두 백필(`problem_corpus_persona_fit_backfill`·`problem_corpus_review_status_backfill`)을 다시 돌려 각인한다.
6. 사이드카 `approval_status` 문구를 새 회차로 바꾼다.
7. 승격 후 `python -m whymath_backend.harness.solution_qa`를 다시 잰다. 기대값은 보고서 §B-3의 후보 실측과 같은 589/0/532다.

## 6. 하지 않는 것

- 승인 은행 자리에 후보를 직접 쓰지 않는다. CLI가 `WRITE_REFUSED`로 거부하고 테스트가 그 거부를 동결한다.
- 판정자 수를 줄이거나 지침을 바꾸지 않는다. 지침이 바뀌면 자격 측정 검출률이 옮겨 가지 않는다.
- 11/15 검증 가능 비율 하한 값은 정하지 않는다. Kiki가 재측정값으로 정한다.
