# P3-03 미분 은행 감사(S5) 6회차 — P3-62 규칙 (가) 후보 은행 504건

> 태스크 `P3-62-solution-qa-unverifiable-structuring` · 2026-10-31 · 판정 기준 main `3a83ed64`
> (P3-62 코드는 #1714로 착지 — 후보 모드 `--structure-final-step`) · 5회차 `../bank_audit_r5/`(k = 1, 통과 · **현재 승인 근거**) ·
> 짝 은행 `../../p3_fill_audit/bank_audit_r4/`(같은 날 같은 런북 · 불합격)

## 무엇을 감사했나

P3-62 규칙 (가)(풀이 끝에 근 선택·정답 변수 값 두 줄을 덧붙이고, 선택 근거를 도메인 부등식으로 싣는다)를 켠 후보 은행이다.
승인 은행 대비 문항 id·순서·발문·정답·해설·선지는 그대로이고, 바뀐 것은 25건의 `verify.conditions`·`verify.solution_steps`뿐이다
(보고서 `docs/reviews/p3_62_solution_qa_structuring_2026-10-20.md` §B-2).

## 사전 등록 (판정자 라벨을 받기 전에 고정)

- **은행**: sha256 `c4f3ad11232cdafd4b02e29e454e7c74ffb42d655a9d7c28f7227536d07786a9` — 보고서 §B-2 값과 같다(같은 코드로 재생성해 바이트 동일 확인).
- **프로토콜**: 1~5회차와 같다 — 기계 게이트 ∪ 판정자 A ∪ 판정자 B, 지침 `../qualification/rater_protocol.md`
  (sha256 `3046a901…` 그대로), 판정자 지시문은 런북 `docs/reviews/p3_62_s5_candidate_audit_runbook_2026-10-21.md` §3 그대로.
- **묶음**: CLI `bank-sheets`, 같은 시드(20261008)·63건 × 8묶음. 묶음별 sha256은 `manifest.json`.
- **판정자**: 묶음마다 서로 다른 Claude 서브에이전트 2명(A·B) — 16명. 각자 저장소 밖 빈 폴더에 지침 사본과 자기 묶음만 두었다.
  이전 회차와 같은 격리의 한계(`../qualification/README.md`)가 그대로 적용된다.
- **판정 규칙**: S5 = Wilson 단측 97.5% 상한(k, 504) ÷ 검출률 단측 97.5% 하한(0.96898) ≤ 0.02 → k ≤ 3이면 통과.

## 결과 (2026-10-31) — S5 통과 · as-found k = 1

판정자 16명 전원 완료 — 출력 16개 모두 63줄 · id 고유 · 입력 집합 일치 · `verdict`는 ok/defect뿐(세션 산출 검사).

| 구성요소 | 결함 판정 |
|---|---|
| 기계 게이트 | 0 / 504 |
| 판정자 A | 1 / 504 |
| 판정자 B | 0 / 504 |
| **프로토콜 합집합 k** | **1 / 504** |

CLI `s5` exit 0 — U = 0.01115, L = 0.96898, **보정 상한 0.01151(기준 ≤ 0.02) — 승인 근거 성립**(`s5_result.txt`).

| 문항 | 분류 | 확신 | 내용 |
|---|---|---|---|
| `3294c5cf…` | 미분 없이 풀림 | 불확실 | x = t^2, t = 2에서의 가속도 — 상수 가속도 2가 평가 시각과 같아 혼동 경로도 같은 값. 정답은 옳다. 5회차에서 판정자 A가 같은 문항을 같은 사유로 짚었다(구조화와 무관 — 이 문항의 `verify`는 바뀌지 않았다) |

**측정 타당성 단서**: 짝 fill 회차에서 같은 템플릿 문장의 검출이 부분적이었다(`../../p3_fill_audit/bank_audit_r4/README.md`). 자격 측정 검출률 하한(주입 결함 120/120)이 문장 표기 결함에 그대로 성립한다고 볼 수 없으므로, 이 회차의 "통과"도 문장 표기 축에서는 같은 단서를 단다.

## 승격하지 않았다

런북 §5는 **두 은행이 모두 exit 0일 때만** 승격한다. 짝 은행(fill)이 불합격이라 이 회차로는 승격하지 않았다.
그래서 이 폴더는 승인 근거가 아니다 — 승인 결속(`tests/backend/l1/test_p3_calculus1_diff_bank_coverage_link.py`의 `_AUDITED_BANK`)은
여전히 `../bank_audit_r5/`를 가리킨다. 이 은행만 먼저 승격할지는 Kiki 결정 사항이다(런북 조건의 예외).

## 파일

`audited_bank.jsonl`(감사받은 후보 동결 사본) · `machine_labels.jsonl` · `manifest.json` · `llm_labels/`(판정자별 합본
`rater_A.jsonl`·`rater_B.jsonl`, 묶음별 근거 `shard*_rater*_evidence.md`) · `s5_result.txt`(저장소 사본으로 재현한 `s5` 출력).
