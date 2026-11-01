# EOS-205 동등문제 생성기 산출 결함 — 생성 단계 거부 규칙과 수정 전 실측

- 판정 기준: main `15364290` (2026-11-01) + 이 PR 브랜치 `claude/eos-205-generator-output-defects`
- 입력 실측: EOS-197 A6 저작 회차 산출물 `data/runs/eos197-a6-openrouter/cu.jsonl`(27 CU)·
  `data/runs/eos197-a6-local/cu.jsonl`(3 CU) = **30 CU** (PR #1765로 main 착지)
- 검수 기준: 같은 회차 `data/runs/eos197-a6-review/canary_review_verdicts.jsonl`(Kiki 확정 판정·메모)

## 1. 무엇을 바꿨나

| 항목 | 결함(실측) | 처방 | 집행 지점 |
|---|---|---|---|
| ① 검산식 동어반복 | 정답 상수 재진술 17건(`n = 3`·`v - 24 = 0`) + 중간값 하드코딩·역산 식 9건(`b = 7*(0 - 2)`·`M**2 - M - 182 = 0`) | 검산식에 **문항 함수 P(또는 P′·P″)를 점에 대입한 부분식**이 있어야 통과. 재진술은 기존 판정기 `verify_bypass`(EOS-207) 재사용 | `l3/equivalent/authoring_guard.grounding_verdict` ← `llm_generator._assemble` (거부 = `TautologicalConditionError`) |
| ② 정답 키 혼재 | `b` 11 · `v` 6 · `y` 5 · `n` 4 · `M` 2 · `x` 1 · `answer` 1 | 답이 근이 아닌 문항은 `answer`로 고정(근 문항의 `x`처럼 발문 수식의 변수는 유지) | `authoring_guard.normalize_answer_key` |
| ③ 단원 코드 비표준 | 회차 하나에 **17종**(`CALC1-TANGENT`·`CAL-TANGENT`·`MI-CALC-EXTREMA`·`미적Ⅰ-02-05` …) | LLM 출력을 읽지 않고 성취기준에서 유도(`[12미적Ⅰ-02-05]` → `12미적Ⅰ-02-05`). 운영자 지정(`unit_codes=`)이 있으면 그것 | `llm_generator._unit_codes_for` · JSON 스키마에서 `unit_codes` 제거 |
| ④ 교육과정 밖 해설 | 미적분Ⅰ 극값 해설이 이계도함수로 판정(수정승인 2건) | 성취기준 접두 `12미적Ⅰ`이면 이계도함수 표현(`이계도함수`·`f''`·`f″`·second derivative 등) 거부, 프롬프트에 f′ 부호 변화 지시 | `authoring_guard.curriculum_method_violation` (거부 = `CurriculumScopeError`) |
| ⑤ 프롬프트 | — | 정본 `docs/prompts/l3_equivalent_gen.md`에 ①②③④ 규칙·예시 추가 | `prompt_version` `l3.equivalent@sha256:4da254e24507` → 새 해시(테스트가 변경을 고정) |

거부는 모두 `ValueError` 하위 예외라 기존 생성 실패 경로(None 폴백)를 타고, GenerationLog `error_detail`에
`후보 조립 실패: TautologicalConditionError` / `후보 조립 실패: CurriculumScopeError`로 남는다.
`g3_content_measures.classify_failure`의 앞머리(`후보 조립 실패:`) 분류는 그대로다.

## 2. 수정 전 실측 — 회차 30 CU에 새 규칙을 적용하면

| 판정 | openrouter (27) | local (3) | 합계 (30) |
|---|---|---|---|
| 재진술(RESTATEMENT) — 거부 | 17 | 0 | **17** |
| 근거 없음(UNGROUNDED) — 거부 | 9 | 0 | **9** |
| 문항 함수 재계산(GROUNDED) — 통과 | 1 | 3 | **4** |
| 교육과정 밖(이계도함수) — 거부 | 2 | 0 | **2** (`0b70422616db`·`e7c73d651ae3` — Kiki 메모와 동일 2건) |

- **수정 전 동어반복 비율 = 26/30 (86.7%)** — 재진술만 세면 17/30(56.7%)으로 acceptance ①의 "17건"과 일치.
- 통과 4건 중 3건(local)은 Kiki가 그대로 승인했거나 키 이름만 고치라고 한 식(`v = 4*3 + 7` 등)이다.
- Kiki 교체안 6종(`answer == (2**3 - 5*2 + 2) - 2*(3*2**2 - 5)` 등)은 전부 GROUNDED — 회귀 테스트가 양성 대조군으로 고정한다.

## 3. 수정 후 실측 — 아직 하지 않았다(미측정)

acceptance ⑤의 "같은 스펙 표본으로 수정 전후 **수락률**" 비교는 새 프롬프트로 실제 생성을 돌려야 한다.
이 세션(클라우드)에는 LLM 키·Ollama가 없어 **라이브 생성을 하지 않았다**. 위 2절은 *수정 전 산출물에 새
거부 규칙을 적용한* 오프라인 측정이지 수정 후 수락률이 아니다. 수정 후 측정은 같은 레인의 EOS-203
Kiki PC 실측 블록(로컬 좌석 사고 모드 on/off 비교)에 같은 스펙 표본으로 합쳐 수행하고, 결과를 이
문서 3절에 덧붙인다. 그 전까지 EOS-205는 done이 아니다.

## 4. 한계

- 발문 함수 추출은 다항·유리식 표기(`f(x) = …`·`y = …`·`… = 0`)만 읽는다. 못 읽으면 UNKNOWN(거부 안 함·경고 로그).
- 구조 일치는 "P에 a를 대입한 식이 검산식 안에 있다"까지만 보장한다. 대입식을 정답과 엮은 공식이 옳은지는 Tier1 대입 검산과 사람 검수 몫이다.
- 교육과정 범위 표는 미적분Ⅰ(이계도함수) 1행뿐이다 — 실측된 결함만 넣었다.
- 실패 주입 12종(값 일치만으로 통과·재진술 판정 제거·키 정규화 조건 제거·배선 제거 등) 전건 RED, 원복 바이트 동일 단언.
