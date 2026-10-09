# rephrased_v0 유형 태깅 완결 판정 — CONT-04 실측 기록 (2026-10-09)

> 판정 기준: `main` `30848ab4`(작업 브랜치 `claude/trusting-dirac-jzw7zb`가 이 커밋 위에서 분기). 아래 수치는 전부 이 트리에서 직접 실행한 값이다.

## 0. 결론 한 줄

CONT-04가 상환하려던 "재서술 429문 미태깅"은 **2026-08-11 PB-07이 이미 상환했다**(현재 421/421 태깅). 이 태스크가 새로 한 일은 (a) 그 상환이 실제로 성립하는지 실측 재확인, (b) acceptance ④가 요구한 `zero_coverage_types()` 전후 기록, (c) 그 기록이 드러낸 **더 큰 사각**(전체 14,034문 중 2,638문만 태깅)을 후속 태스크 `CONT-09`로 분리 등재한 것이다.

## 1. acceptance ①② — 전제 실측

| 항목 | 값 | 측정 방법 |
|---|---|---|
| `problem_bank_rephrased_v0` 레코드 | 421 | `problems.jsonl` 전수 순회 |
| `problem_type_codes` 비었거나 없음 | 0 | 동일 |
| `relations`("변형" 부모) 없음 | 0 | 동일 |
| `identity_id` 없음 | 0 | 동일 |

태스크 본문의 "429건"은 작성 시점(2026-08-11) 값이다. 이후 S3-12(483→429)·QUAL-02(429→421)가 코퍼스를 줄여 지금은 421건이다. S3-27이 유예의 근거로 삼은 "원 생성기 추적 불가"는 S4-14/S4-18/S4-21 done과 계보 421/421로 소멸했고, 코드는 `problem_type_mapping.py`의 `LINEAGE_CORPORA`·`classify_rephrased_record`·`EXCLUDED_CORPORA = {}`가 이미 반영한다.

## 2. acceptance ③ — 태깅 실행 상태와 논증

실행은 PB-07(`#797`)이 끝냈으므로 이 태스크는 재실행하지 않았다. 대신 **같은 입력에서 같은 바이트가 나오는지**를 임시 사본에서 확인했다.

- 쓰기 전 / 백필 1회 후 / 백필 2회 후의 `problems.jsonl` sha256이 **전부 동일**하고, 추적 중인 파일과도 동일하다(`run_backfill(write=True)`).
- 즉 현재 저장된 `problem_type_codes`는 계보 유도 값과 전건 일치하며 재실행해도 변하지 않는다.

상속 논거(명문화): 재서술은 `question_text`만 바꾸고 수치·정답·풀이 절차·`unit_codes`는 코드가 소유해 부모와 동일하게 봉인된다(`_provenance.json` contract·`test_corpus_quality.py`). 문항이 요구하는 인지 행동이 부모와 같으므로 유형도 부모의 것이다. 이 판정은 LLM 0·문항 텍스트 추론 0이다.

상속 불가 잔여: **0건**(421/421).

## 3. acceptance ④ — `zero_coverage_types()` 전후

방법: 현재 코퍼스에서 `problem_bank_rephrased_v0`의 `problem_type_codes` 키만 제거한 사본(= PB-07 이전 상태 재현)과 현재 코퍼스에 각각 `problem_bank_coverage` CLI를 돌렸다(둘 다 exit 0).

| | 태깅 합계 | 0커버 유형 수 |
|---|---|---|
| 전(재서술 미태깅) | 2,217 | 9 |
| 후(현재) | 2,638 | 9 |

0커버 9종은 **전후 동일 집합**이다: `condition-satisfaction`, `construct-object`, `existence-decision`, `infer-relationship`, `model-word-problem`, `optimize-constrained`, `prove-statement`, `sketch-graph`, `transform-expression`(접두 `ptype.` 생략).

재서술 421건이 늘린 유형별 문항 수(전→후): `evaluate-expression` 1,322→1,425(+103), `optimize-extremum` 140→237(+97), `solve-for-unknown` 307→528(+221). 합 +421이며 셋 모두 원래 커버되던 유형이다.

**해석**: CONT-04 서두와 `ai_content_generation_gap_review_r3.md` F3의 가설("16.2% 미태깅이면 0커버 판정이 과대 계상된다")은 **재서술 범위에서는 기각**됐다. 재서술 태깅은 0커버 집합을 바꾸지 않았다. 다만 이것이 계측기가 신뢰할 만하다는 뜻은 아니다 — §5 참조.

## 4. acceptance ⑤ — 변별력 검증

임시 사본(7개 코퍼스 복사)에서 `run_backfill`을 실행했다. 주입이 실제로 들어갔는지는 단언으로 확인했다(`relations == []`).

| 상태 | 재서술 total / tagged / untagged |
|---|---|
| 정상(드라이런) | 421 / 421 / 0 |
| 1건의 `relations`를 비우고 `problem_type_codes`를 제거 | 421 / 420 / **1** |

단절한 1건은 `problem_type_codes`를 받지 못했고(`wm-skel-d782cf61cf93-rephrased`) 나머지 420건은 영향이 없었다. 즉 계보가 끊기면 "상속 불가"로 정직하게 계상된다. 실험은 전부 스크래치 사본에서 했으므로 추적 중인 `data/`는 변경되지 않았다(`git status --short data/` 빈 출력) — 그래서 cp 백업 원복이 필요 없었다.

## 5. 새로 드러난 사각 — 계측기가 보는 범위

같은 CLI의 `total_problems`는 **14,034**인데 태깅 합계는 **2,638**(18.8%)이다. 미태깅 11,396문은 30개 코퍼스에 걸쳐 있고 전량 `TARGET_CORPORA`·`LINEAGE_CORPORA` 밖이다(최대: `polynomial_arithmetic_v0` 1,500, `complex_number_arithmetic_v0` 900, `probability_law_v0` 724).

원인: S3-27의 "7종 2,647건"은 당시 코퍼스 **전체**였고, 그 뒤 추가된 코퍼스는 태깅 계약에 편입되지 않았다. 재서술 429건 구멍과 같은 모양(코퍼스는 늘고 계약은 따라가지 않음)이며, 이번 것은 규모가 26배다.

따라서 현재 `zero_coverage_types()`의 9종은 "전체 코퍼스에서 0커버"가 아니라 "태깅된 18.8%에서 0커버"다. 이 값을 §4-① 트리거 발화 판정에 쓰려면 먼저 이 사각을 닫아야 한다. 소유 태스크가 없음을 확인해 `CONT-09-untagged-corpora-type-tagging-contract`로 등재했다(전수 귀속 거버넌스 포함).

## 6. 이 태스크가 바꾼 파일

- `src/backend/whymath_backend/harness/problem_bank_coverage.py` — 모듈 docstring의 stale 수치("2,638건 중 2,217건 태깅")를 실측값으로 정정하고 계측기 범위 한계를 명시(PB-07 인계 잔여). 동작 변경 없음.
- 본 문서.
- `backlog/tasks/CONT-09-…yaml` 신규 등재.
