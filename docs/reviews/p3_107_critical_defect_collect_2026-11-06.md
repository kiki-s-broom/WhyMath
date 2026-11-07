# P3-107 — 지표 ⑥ Critical Defect 입력 수집 실측 (2026-11-06)

> **판정 기준(입력 데이터)**: main `ce8c2165` (2026-11-06 · `data/runs/` 회차 산출물은 이 커밋의 바이트)
> **집행 코드**: `ops/critical_defect_collector.py`(신규) + `ops/phase3_metrics.py --critical-defect-from-runs`(신규 플래그) — 이 PR 브랜치. 머지 뒤 main 에서 아래 명령을 다시 돌려 같은 출력이 나오는지 확인하는 것이 J1 의 몫이다.
> **증적 폴더**: `docs/reviews/p3_107_critical_defect_collect_2026-11-06/` (수집기 JSON·표, phase3_metrics 표·JSON)
> **게이트**: `G-p3-w3-release-merged` 입력 (P3-17 판정 `docs/reviews/p3_17_week3_release_judgment_2026-11-05.md` 의 ⑥ "측정 불가(payload 없음)" 결손)

## 1. 결과 한 줄

⑥ 은 **여전히 측정 실패**다. 다만 이제 이유가 "수집기가 없다"가 아니라 **"F-Ⅱ 원천의 판정이 0건이다"**로 출력에 박힌다. F-Ⅴ 는 0/30 으로 측정됐고 미해당(Wilson 단측 95% 상한 8.27% < 10%)이다.

| 항목 | 값 | 목표 | 판정 |
| --- | --- | --- | --- |
| ⑥ Critical Defect | 측정 불가 (분자/분모 0/2 · 판정 불가 F-Ⅱ) | 해당 0건 | **측정 실패** (exit 2) |
| F-Ⅱ 검수 통과 CU 수학 오류율 | 판정 0건 — 검수 통과 28건 전부 SymPy 재검증 **검증 불가**(`C2_NO_STEPS` 28) | Wilson 상한 ≤ 2% | 판정 불가 |
| F-Ⅴ 힌트 의미 누설(사람 표본) | 0/30 · Wilson 상한 8.27% | 상한 < 10% | 미해당 |

## 2. 입력 원천 실측 (원천마다 건수 · 0건도 그대로)

검색 범위: `git ls-files data/runs` 전수, `fn_by_failure_code`·`hint_leak_hits` 생산자 grep(`src`·`scripts`·`docs`).

| 원천 | 위치 | 건수 | ⑥ 에 쓰는가 |
| --- | --- | --- | --- |
| 회차 폴더(`*-review` 를 가진 회차) | `data/runs/eos197-a6-review` | **1회차** | 예 |
| 그 밖의 `data/runs` 폴더 | `eos203-thinking-probe`·`p3_78-live`·`p3_94` | 3 (검수 판정·힌트 표본 없음) | 아니오 — 원천 아님 |
| CU 레코드 | `eos197-a6-local/cu.jsonl`·`eos197-a6-openrouter/cu.jsonl` | 3 + 27 = 30 | F-Ⅱ |
| CU 검수 판정 | `eos197-a6-review/canary_review_verdicts.jsonl` | 30 (통과 28 = approved 1 + approved_with_edit 27 · 반려 2) · 지문 일치 30/30 | F-Ⅱ |
| 검수 통과 CU 의 Solution QA 재검증 | `harness.solution_qa.run_solution_qa` | PASS 0 · FAIL 0 · **검증 불가 28**(전부 `C2:C2_NO_STEPS` — 풀이 단계 없음) | F-Ⅱ (판정 0건) |
| 골든 혼동행렬 산출물(`qa_confusion_matrix --json`) | 커밋 0건 (`git ls-files` 에 골든 JSON·혼동행렬 리포트 없음) | **0건** | 아니오(아래 §4-2) |
| 힌트 내보내기 | `eos197-a6-*/cu.hints.jsonl` | 2파일 · 89건(L1 30·L2 30·L3 29) | F-Ⅴ |
| 힌트 사람 판정 | `eos197-a6-review/hint_verdicts.jsonl` | 45행(의미 표본 30 · 기계 판정 불가 폴백 15) | F-Ⅴ |
| 힌트 표본 매니페스트 | `eos197-a6-review/hint_sample_manifest.json` | 1 (`hvs-6bfbb1baa75f6e34` · 모집단 60 · 표본 30) | F-Ⅴ |
| 의미 축 재계산(`g3_content_measures`) | main 원 자료에서 다시 계산 | n=30 · k=0 · PASS — 커밋된 `g3_content_measures_g3prep_2026-11-05.json` 의 semantic 과 **완전 일치** | F-Ⅴ |
| CU 검수 F8 라벨(힌트 정답 누설) | `canary_review_verdicts.jsonl` | 2 (둘 다 **반려된 중복 문항** — 사유는 "중복이라 풀지 않고 맞힐 수 있다") | **아니오** — 표본 검수가 아님. 사실로만 출력 |

## 3. 재현 명령 (main 머지 뒤)

```bash
cd src/backend && python -m whymath_backend.ops.critical_defect_collector --json ../../out/p3_107_collector.json
```

```bash
cd src/backend && python -m whymath_backend.ops.phase3_metrics --no-db --critical-defect-from-runs --json ../../out/p3_metrics.json
```

기대: 수집기 exit 2, phase3_metrics exit 2, ⑥ 블록에 `F-Ⅱ 입력: unmeasured · 판정 0건 …` · `F-Ⅴ 입력: measured · 0/30 …`. 수집기 JSON 은 같은 입력이면 같은 바이트다(시각·절대 경로 없음 · 입력 파일 7개의 sha256 동봉) — `collector.json` 과 `cmp` 로 대조할 수 있다.

## 4. 해석과 단서

1. **F-Ⅱ 는 표본이 모자라 판정이 0건이다 — 그리고 판정이 나도 지금 표본으로는 통과할 수 없다.** 스코어카드의 F-Ⅱ 는 Wilson 단측 95% **상한**을 2% 와 비교한다(동결 문언). 오류 0건으로 통과하려면 판정된 검수 통과 CU 가 **133건 이상** 있어야 한다(`evaluate_hard_gates` 로 계산). 이 회차 28건이 모두 판정되고 오류가 0이어도 상한은 8.81% 로 **해당(위반)**이다. 즉 ⑥ PASS 의 선행 조건은 ①풀이 단계가 있어 SymPy 재검증이 결정되는 ②검수 통과 CU 133건 이상이다.
2. **골든 FN 경로(`validation_scorecard.adapt_qa_confusion_matrix`)는 이 수집기에 넣지 않았다.** 스코어카드는 그 경로로도 F-Ⅱ 를 채울 수 있지만 커밋된 혼동행렬 산출물이 0건이고, 두 도구를 한 숫자에 섞으면 "어느 도구의 오류율인가"가 결정 불가가 된다. 골든 산출물이 생기면 별도 결정으로 편입한다.
3. **검증 불가를 오류 0으로 세지 않는다.** 28건은 C1(정답 ↔ 조건 검산)은 통과했지만 C2(풀이 단계)가 없어 Solution QA 판정이 `UNVERIFIABLE` 이다. C1 만 골라 PASS 로 세면 ⑥ 을 움직일 수 있지만, 그것은 판정 규칙을 바꿔 지표를 올리는 것이라 하지 않았다.
4. **F8 라벨 2건과 F-Ⅴ 는 모순이 아니다.** 같은 CU 의 L1·L2 힌트 사람 판정은 `not_leaked` 이고, F8 은 반려 사유(중복 문항)에 붙은 코드다. ⑥ 출력의 사실 줄에 "F8 라벨(F-Ⅴ 미산입) 2건"으로 남는다.
5. 수집기는 판정하지 않는다 — PASS/FAIL 은 `phase3_metrics` 의 ⑥(`evaluate_hard_gates` F-Ⅱ·F-Ⅴ 흡수)이 낸다. 새 정의 0건.
