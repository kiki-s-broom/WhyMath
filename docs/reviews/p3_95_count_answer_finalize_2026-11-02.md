# P3-95 — 개수형 답 finalize 지원 · 샌드박스 실측 (2026-11-02)

> **판정 기준: main `b55dbdb0`** + 이 PR의 커밋 · 측정 환경 = 클라우드 세션의 로컬 PostgreSQL 16 + pgvector(운영 아님) · 스키마 `a8c4e1f7b3d9`(운영 DB와 같은 head)
> 태스크: `P3-95` — 12미적Ⅰ-02-09(방정식 실근 개수) 재생 풀이 0건 해소. 선행 근거: `p3_32_hint_pipeline_sandbox_2026-11-01.md` §4 ③

## 1. 원인

- 12미적Ⅰ-02-09 문항군(`wm-p3-diff-eqapp-*`)은 답이 근이 아니라 **실근의 개수**다. 그래서 `verify.answer_map`이 비어 있고 `verify.answer_kind = real_root_count`가 붙어 있다.
- `whs/harness.py`의 finalize는 Tier1 답 검산을 항상 `verify_answer(conditions, answer_map)`로 했다. 빈 치환맵이면 검산이 **fail**하고, finalize가 거부돼 재생 39건이 전부 `ended/None`으로 끝났다.
- 개수를 세는 검증기(`verify_real_root_count`)와 개념형 검증기 표(`l3/equivalent/acceptance._CONCEPTUAL_VERIFIERS`)는 이미 있었다. 재생 경로만 그 표를 부르지 않았다.
- 같은 원인으로 미분가능성 판정형(`is_differentiable` 164건 · `nondifferentiable_point_count` 160건)도 막혀 있었다. 샌드박스 문서 §2의 "conceptual 24건 실패"가 그 일부다.

## 2. 수정

- `FinalizeAction`에 `answer_kind`·`claimed_answer`(선택)를 더했다. `answer_kind`가 있으면 Tier1을 `_CONCEPTUAL_VERIFIERS[answer_kind](conditions, claimed_answer)`로 돌린다. 개념형 판정의 검증기 원천은 문항 수용 검사(`acceptance`)와 같은 표 하나다.
- 모르는 검증기 키·주장 답 없음은 pass로 위장하지 않고 **unverifiable**로 둔다. 그러면 `final_verdict`가 unverified(격리·학습 배제)로 매긴다.
- Tier2(단계 동치)는 그대로다. 답 개수가 맞아도 틀린 과정은 failed다.
- `corpus_replay` 로더가 `verify.answer_kind`와 레코드 최상위 `answer`를 읽어 넘긴다. 값형 문항(키 없음)은 종전과 같다.
- 적재 JSONB: 값형은 종전 3키(`conditions`·`answer`·`steps`) 그대로 둔다. dedup이 정확 일치이기 때문이다. 개념형만 `answer_kind`·`claimed_answer`를 더한다.

## 3. 실측

### 3.1 검증만(DB 없음) — 전 문제은행 재생 대상

| | 변경 전 | 변경 후 |
|---|---:|---:|
| verified | 3,470 | **3,833** |
| failed | 363 | **0** |
| 등급이 내려간 문항 | — | **0** |

풀린 363건의 내역은 다음과 같다: `real_root_count` 39 · `is_differentiable` 164 · `nondifferentiable_point_count` 160.

**오답 주입**(같은 363건의 주장 답을 틀리게 바꿈)에서 verified는 **0건**이었다.

| 주입 | 결과 |
|---|---|
| 개수 +1 | failed 305 · unverified 58(0/1 판정 답이 2가 돼 판정 불가) |
| 주장 답 빈 문자열 | 전건 unverified |
| 모르는 검증기 키 | 전건 unverified |

### 3.2 로컬 PG 샌드박스 — 인수 조건 ③

| 단계 | 결과 |
|---|---|
| 적재 | 성취기준 895 · 원자 2,683 · 문항 15,042 |
| 재생(`whs.corpus_replay --no-bad-branch` × 풀이 단계 보유 은행 14개) | **verified 3,833 · 실패 0**(전 은행 exit 0) · eqapp **39/39 verified** |
| 승격(`whs.path_promotion --apply`) | 승격 1,570(이전 샌드박스 1,507 + eqapp 39 + conceptual 24) · eqapp 39건 `algebraic` |
| 힌트(`l4.hint_content.populate --apply`) | 생성 6,803 · 검수 통과 6,395(94.0%) · eqapp verified 힌트 324 |

`phase3_coverage --hints-from-db` 측정에서 바뀐 값은 다음과 같다.

| 지표 | 이전 샌드박스(11-01) | 이번 |
|---|---|---|
| hint 연결 | linked 9 · missing 1 | **linked 10 · missing 0** |
| Concept Completeness | 9/10 (미충족 02-09) | **10/10** |
| hint_strategy(적격 1,121) | present 784 · missing 337 | present 847 · missing 274 |
| prerequisite / misconception / solution / pedagogy | 각 linked 10 | 각 linked 10 (줄지 않음) |
| Graph Connectivity | — | 4/10 (아래 참고) |

**Graph Connectivity 4/10은 이번 변경과 무관하다.** DB 힌트를 쓰지 않는 기본 실행(`phase3_coverage`, 코퍼스만)에서도 같은 4/10이다. 미충족 6건의 사유는 전부 `problem→misconception`(오답 보기가 핵심 오개념에 닿는 문항 없음)이다. 2026-10-14 기준선의 5/10과 차이가 나는 원인은 이 PR의 범위가 아니라서 규명하지 않았다.

## 4. 남은 일

- **운영 DB 적용**은 `P3-32` 소관이며 Kiki 머신(whymath-pg 5433)에서 해야 한다. 운영 `problem`은 1,703행이고 적격 1,121건의 ID 겹침은 아직 모른다(`p3_32` 문서 §4). 런북은 적재 전에 겹침을 세어야 한다.
- 조건이 **목록**인 eqapp 33건(최솟값형 30 · 범위 붙은 개수형 3)은 로더가 `conditions: str`만 받아 재생 대상이 아니다. 이번 실측에서 02-09 hint 연결에는 필요 없었다(39건으로 linked). 별도 결손으로만 기록해 둔다.
