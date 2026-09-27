# review_status 각인 계약 — 두 도구의 적용 대상 · 충돌 규칙 · 승격 게이트 ④단 분모 (EOS-136)

> **판정 기준**: main `0e7b4f6b`. 코퍼스 수치는 그 커밋의 `data/corpus/problem_bank_*/problems.jsonl`
> 전수 실측이고, Wilson 수치는 저장소 `harness/wilson.wilson_upper_bound`(단측 · 신뢰 0.95) 실측이다.
>
> 이 문서는 문항 코퍼스의 `review_status`를 **쓰는** 도구들의 계약 정본이다. 코드 쪽 정본은
> `harness/review_status_domains.py`(적용 대상)와 `harness/golden_promotion_gate.py`(판정 해석 ·
> ④단)이며, `tests/backend/harness/test_review_status_domains.py`가 이 문서와 코드를 대조한다.

---

## 1. 요약

| 축 | 결론 |
|---|---|
| 적용 대상 | 고정 코퍼스 7종은 **코퍼스 단위 백필**, 축적 CLI의 회차 코퍼스는 **사람 판정 각인**, 그 밖은 **어느 도구의 대상도 아니다**. 두 도구 모두 남의 대상을 exit 2로 거부한다(§2). |
| 충돌 규칙 | 이미 채워진 `review_status`는 어떤 도구도 덮어쓰지 않는다. 같은 값이면 감사 행도 만들지 않고, 다른 값이면 충돌로 보고한다(§3). |
| 각인값 | `approved` → approved · `rejected` → rejected · `approved_with_edit` → **각인 보류**(손질 전 내용이라 재검수 필요)(§4). |
| ④단 분모 | **생성 배치 품질**로 판정한다 — 분모는 검수 배치 전체, 분자는 판정 이력의 반려·손질 승인(§5). |
| CI 드리프트 가드 | `--all --check`는 고정 7종만 보며, 회차 코퍼스가 그 목록에 들어오면 exit 2로 빨개진다(§6). |

---

## 2. 적용 대상 — 코퍼스 부류 5종

부류 판정은 `review_status_domains.classify_corpus` 하나다.

| 부류 | 식별 | `review_status`를 쓰는 도구 | 판정 근거 | 현황(판정 기준 커밋) |
|---|---|---|---|---|
| `fixed` | `KNOWN_CORPORA` 7종 경로 | `problem_corpus_review_status_backfill` | 감사 라벨 표본(n ≥ 200)의 코퍼스 판정 1개 | 7종 2,638건 — approved 2,480 · pending 158 |
| `round` | 회차 대장 사이드카 `<corpus>.rounds.jsonl` 실재 | `review_status_verdict_bridge` | slug별 사람 최신 종결 판정 | 레포 밖(운영자 머신의 축적 `--out`) |
| `other` | 위 둘 다 아님 | **없음** | — | 레포 배치 코퍼스 30종 11,396건 전부 공백 |
| `conflict` | 고정 경로인데 회차 대장도 있음 | 없음(두 도구 모두 거부) | — | 0종 |
| `unknown` | 대장 실재를 확인할 수 없음(권한 등) | 없음(모른다 ≠ 아니다) | — | — |

**회차 식별이 사이드카인 이유**: 회차 코퍼스는 레포에 상주하지 않고 파일 이름도 자유다. 축적 CLI가
끌 수 없게 남기는 회차 대장(`anchor_round_ledger.default_round_ledger_path`)만이 "이 파일은 축적
회차의 산출물이다"를 말하는 내구 표식이다. 대장을 지운 회차 코퍼스는 `other`가 되어 두 도구 모두
거부한다(fail-closed).

**`other`의 공백은 결함이 아니다.** `l6/_shared.is_review_cleared`는 `approved`만 통과시키므로 공백은
노출 차단이고, 사람도 감사 표본도 보지 않은 문항에 대해 그것이 정상 상태다. 이 부류를 해금하는 정본
경로는 감사 라벨 표본을 만들어 `KNOWN_CORPORA`·`AUDIT_LABEL_MAP`에 편입하는 것(코퍼스 단위)이며,
그 결정은 이 계약 밖이다.

**근거 차용 금지**: 코퍼스 키 K의 판정은 K의 코퍼스에만 쓴다. 다른 고정 코퍼스나 레포
`data/corpus/` 아래의 다른 코퍼스에 K의 감사 근거를 쓰면 코퍼스 단위 백필이 거부한다
(`corpus_backfill_refusal`). 이것이 막는 사고: 감사 라벨이 없는 1,500건짜리 배치 코퍼스에
`--corpus generated_v0`를 주면 아무도 보지 않은 1,500건이 한 번에 노출 가능해진다.

---

## 3. 충돌 규칙 — 이미 채워진 값은 불가침

두 도구 모두 `review_status`가 이미 채워진 레코드는 **원문 줄 그대로** 둔다. 그 결과 같은 레코드에
두 도구가 닿으면 **먼저 쓴 쪽이 영구히 이긴다** — §2의 부류 분리를 코드로 강제하는 이유다. 코퍼스
단위 백필이 회차 코퍼스에 먼저 닿으면 빈 칸이 남지 않아 사람 판정은 그 뒤 영영 각인될 수 없다.

사람 판정 각인 도구의 레코드별 처리(판정이 있는 레코드만 — 판정 없는 레코드는 바이트 그대로):

| 채워진 값 | 각인할 값 | 처리 | exit 영향 |
|---|---|---|---|
| 없음 | approved·rejected | **각인** + 감사 행 1건 | — |
| 없음 | 보류(손질 승인) | `held_edit_pending` — 무변경 | — |
| 있음 = 각인할 값 | — | `already_stamped` — 무변경, **감사 행도 만들지 않는다** | — |
| 있음 ≠ 각인할 값 | — | `conflict` — 무변경 · 보고 | 1 |
| approved | rejected·보류 | `conflict` + **`exposure_risk`** | 1 |
| approved 아닌 값 | 보류 | `held_edit_pending` — 이미 노출 차단 | — |

**세탁 금지**: 손으로 approved를 찍어 둔 레코드에 도구가 감사 행을 만들어 주면, 게이트 ③단의
`review_status_not_backfilled`(손각인 의심)가 무력해진다. 그래서 같은 값이어도 감사 행을 쓰지 않는다.

**노출 위험은 반려로 덮지 않는다**: 이미 노출 통과값인 문항을 최신 사람 판정이 막았다면 그것은
"들여보냈다가 되돌리는" 일이라 격리 계약(`docs/standards/problem_quarantine_contract.md`)의 사람
절차 대상이다. 도구는 exit 1과 함께 그 사실을 알릴 뿐이다.

**각인 감사로그**: 회차 코퍼스 곁 사이드카 `<corpus>.review_status_audit.jsonl`(append 전용 — 회차가
쌓여도 이전 각인 기록이 지워지지 않는다). 행 = `slug` · `review_status` · 근거 이벤트 id · 검수자 ·
검수 시각 · 각인 시각 · `stamp_source`. 게이트 `--backfill-audit`에 이 파일을 넘긴다.

**쓰기 순서**: 감사로그 append(flush · fsync) → 코퍼스 원자 교체(`os.replace`). 둘 사이에서 죽으면
감사는 approved · 코퍼스는 공백이 되고, 게이트는 그 상태를 `review_status_audit_mismatch`로 막으며
재실행이 빈 칸을 다시 각인한다. 순서를 뒤집으면 코퍼스에만 값이 남고, 재실행은 세탁 금지 때문에 감사
행을 만들지 않으므로 복구되지 않는다.

**exit 코드**(사람 판정 각인 도구): 0 = 정상 · 1 = 충돌 1건 이상(비충돌분은 각인) 또는 코퍼스와 짝이
맞는 판정 0건 · 2 = 입력 오류(파일 부재 · 적용 대상 위반 · 입력 손상 1행 이상 · 쓰기 실패).
쓰기 실패를 뺀 exit 2는 **무기록**이다. 코퍼스 단위 백필은 적용 대상 위반에 exit 2(무기록)를 낸다.

---

## 4. 사람 판정 → 각인값

| 최신 종결 판정 | 각인값 | 게이트 ②단 |
|---|---|---|
| `approved` | approved | 통과 |
| `rejected` | rejected | `human_verdict_rejected` |
| `approved_with_edit` | **보류** | `human_verdict_needs_edit` |

- **판정 해석은 한 함수다** — `golden_promotion_gate.read_human_verdict_ledger`(파일 순서상 마지막
  종결이 최신 판정 · started/aborted는 판정 아님). 게이트 ②④단, 제안 파생(`golden_inputs`), 각인
  도구가 모두 이것으로 읽는다.
- **값 변환은 한 함수다** — `schema/review_timer.review_status_for_verdict`.
- **손질 승인을 보류하는 이유**: 검수 CLI(`harness/review_session`)의 `e`는 "손질하면 쓸 수 있다"이고
  그 도구는 손질 내용을 저장하지 않는다. 코퍼스에는 손질 전 내용이 있고, 골든 계약도 그 내용을
  as-found `defective`로 라벨링한다. `review_status_for_verdict`가 이 판정을 approved로 옮기는 것은
  *손질이 반영된* 내용의 노출 어휘 변환이며(EOS-62), 여기서 막는 것은 *반영되지 않은* 내용이다.
  술어는 `certifies_current_content` 하나를 게이트와 각인 도구가 공유한다. 승격 경로 = 손질 반영 →
  재검수(`approved`).
- **검수 도구의 판정 파일은 각인 감사로그가 아니다**: `review_session --verdicts` 행(`verdict` 키 보유)을
  게이트 `--backfill-audit`에 넣으면 ②단과 ③단이 같은 증거로 이중 계상된다. 게이트는 그 행을 입력
  손상(exit 2 · `ReviewVerdictRowNotStampAudit`)으로 거부한다. 각인 도구의 감사 행은 사람 판정 원값을
  `human_verdict`에 싣는다.

---

## 5. 승격 게이트 ④단 분모 판정 (acceptance ③)

### 5.1 문제

초판 게이트는 ④단 분모를 **제안 slug 중 사람 판정이 있는 것**으로 잡았다. 반려된 제안은 ②단에서
이미 경로 밖이므로, 통과(exit 0)가 가능한 모든 경우에 결함 수는 0이다
(`docs/reviews/mp03_canary_threshold_and_promotion_path_2026-09-25.md` §4.3). 즉 ④단은 "승인 제안 ≥
133건"이라는 표본 하한으로 퇴화했고, docstring이 말한 "배치 결함율"은 판정에 들어가지 않았다.

### 5.2 두 해석

| 해석 | ④단의 뜻 | 고칠 곳 |
|---|---|---|
| (I) 개별 검증 표본 하한 | 사람이 하나하나 승인한 문항이 충분히 많은가 | docstring·리포트 문언 |
| (II) 생성 배치 품질 | 그 문항들을 낸 배치가 결함을 거의 내지 않았음을 보였는가 | 분모(검수 배치 전체) |

### 5.3 판정 — (II) 생성 배치 품질

1. **(I)은 결함율이 아니다.** 결과로 걸러 낸 집합(승인분)의 결함율은 정의상 0이다 — 선택 편향이다.
   예: 300건을 검수해 30건(10%)을 반려한 배치에서 승인 270건만 제안하면 0/270 → 상한 **0.0099**로
   통과한다. 배치 분모로는 30/300 → 상한 **0.1322**로 거부된다.
2. **게이트가 선언한 교리가 (II)다.** 게이트는 임계 0.02 · 신뢰 0.95를 코퍼스 단위 백필과 "같은 교리"라고
   적었다. 그 교리는 감사 표본의 결함을 분모에 넣어 로트를 판정하는 것이다.
3. **계획 문서의 수치가 (II)에서만 성립한다.** MP-03 판정 문서 §6의 "결함 1건 허용 시 0.02 → 222건"은
   결함이 분자에 들어가야 의미가 있다. (I)에서 결함 1건은 그 제안을 ②단에서 떨어뜨릴 뿐이다.
4. **학생 안전.** 사람 검수는 결함을 놓치는 검출기이고, 놓침의 수는 결함 유병률에 비례한다. 결함이
   많은 배치의 승인분에는 놓친 결함도 더 많다 — 배치 품질이 승인분의 잔여 위험을 대변한다.

### 5.4 정의

- **분모(검수 배치)**: `--review-events`로 넘긴 검수 기록에서 사람 종결 판정이 있는 slug 전건 — 제안
  여부 · 코퍼스 수록 여부와 무관하다(회차 내 구조 중복으로 코퍼스에 없는 문항도 같은 생성기의 산출이다).
  배치는 운영자가 넘긴 기록이 정한다. 리포트는 `defect_scope: review_batch`와 **제안 밖 판정 수**
  (`batch_outside_proposal`)를 함께 실어 무엇을 분모로 삼았는지 자백한다.
- **분자(as-found 결함)**: 종결 판정 **이력** 중 한 번이라도 `rejected`·`approved_with_edit`였던 slug.
  최신 판정이 아니라 이력인 이유 — 손질 → 재검수(approved)는 승격의 정본 경로인데, 최신 판정만 세면
  그 재승인이 원래의 결함을 지워 손질이 잦은 배치가 무결점 배치로 보인다(200건 중 5건 손질 · 재승인:
  최신 기준 0/200 → 0.0133 통과, 이력 기준 5/200 → 0.0505 거부). 리포트는 결함을 최신 판정별로 나눠
  싣는다(`batch_rejected` · `batch_edited` · `batch_reapproved`).
- **②단은 최신 판정을 본다.** ②단과 각인은 *지금 내용*의 판정이고, ④단은 *생성 배치의 품질*이다.

### 5.5 필요한 배치 크기 (임계 0.02 · 신뢰 0.95)

| 배치의 as-found 결함 | 최소 검수 배치 |
|---|---|
| 0 | 133 |
| 1 | 222 |
| 2 | 300 |

### 5.6 MP-03 실측의 재해석

MP-03 1차 시도(§8.2)는 검수 15건 전부를 제안했으므로 제안 분모와 배치 분모가 같았다 — 2/15 · 상한
0.3336은 이 판정 아래에서도 그대로다. 달라지는 것은 **승인분만 제안하는** 다음 시도다: 제안 분모였다면
0/13 · 0.1723, 배치 분모에서는 여전히 2/15 · 0.3336이다.

---

## 6. CI 드리프트 가드와의 관계

- `problem_corpus_review_status_backfill --all --check`(CI `declared-unwired-audit` 잡)는
  `KNOWN_CORPORA` 7종만 순회한다. 회차 코퍼스는 순회 대상이 아니므로 "미백필 드리프트"로 오판될 수 없다.
- 적용 대상 검사(`corpus_backfill_refusal`)는 `--all`의 대상 전건에도 걸린다. 누군가 회차 코퍼스를
  `KNOWN_CORPORA`에 등재하면 가드는 그것을 미백필로 읽고 코퍼스 단위 각인을 권하는 대신 **exit 2로
  빨개진다** — 코퍼스 단위 각인이 먼저 닿으면 그 회차의 사람 판정은 영영 각인될 수 없기 때문이다.
- 판정 기준 커밋에서 고정 7종은 전부 `fixed`(회차 대장 없음)이고, 이 사실을 테스트가 동결한다.

---

## 7. 집행 지점 (정본화와 별항)

| 계약 | 집행 코드 | 동결 테스트 |
|---|---|---|
| 부류 판정 · 두 도구의 거부 | `review_status_domains.classify_corpus` · `corpus_backfill_refusal` · `verdict_bridge_refusal` | `test_review_status_domains.py` |
| 코퍼스 단위 백필의 거부(단일 · `--all`) | `problem_corpus_review_status_backfill.main` | `test_review_status_domains.py` · `test_eos_anchor_e2e_a4.py::…::test_corpus_level_backfill_refuses_pipeline_output` |
| 사람 판정 각인 · 불가침 · 세탁 금지 · 쓰기 순서 | `review_status_verdict_bridge.run_bridge` | `test_review_status_verdict_bridge.py` |
| 판정 해석 단일 권위 · 손질 승인 ②단 차단 | `golden_promotion_gate.read_human_verdict_ledger` · `certifies_current_content` | `test_golden_promotion_gate.py` |
| ④단 분모 = 검수 배치 · 분자 = 이력 | `golden_promotion_gate.PromotionGateReport` | `test_golden_promotion_gate.py::TestReviewBatchDenominator` |
| 판정 파일 ≠ 감사로그 | `golden_promotion_gate._load_backfill_audit` | `test_review_status_verdict_bridge.py::TestReviewVerdictFileIsNotTheAudit` |
| 실 파이프라인 관통(축적 → 검수 → 각인 → 게이트) · 음성 대조 | 위 전부 | `test_eos_anchor_e2e_a4.py::TestGoldenPromotionGateOnPipelineOutput` |

---

## 8. 한계 (명시)

- **검수 후 내용 편집은 탐지하지 못한다.** 검수 이벤트에는 검수자가 본 내용의 지문이 없다. 사람이
  승인한 뒤 누군가 문항 *내용*을 손으로 고치면 각인 도구는 그대로 approved를 찍고, 게이트는 값
  (`review_status`)만 대조하므로 통과시킨다. 추적 태스크: `EOS-27-review-content-fingerprint`.
- **코퍼스 단위 백필의 감사로그는 실행마다 덮어쓴다(append가 아니다).** 고정 코퍼스에 레코드를 더하고
  다시 돌리면 이전 각인 기록이 감사 파일에서 사라진다(git 이력에는 남는다). 그 감사로그로 게이트를
  돌리면 이전 레코드가 `review_status_not_backfilled`로 보인다. 실측(판정 기준 커밋의 코드): 3건 각인 →
  1건 추가 → 재실행하면 감사 파일에 새 1건만 남았다. 사람 판정 각인 도구의 감사로그는 append 전용이라
  해당하지 않는다. 추적 태스크: `PB-16-corpus-backfill-audit-append`.
- **배치는 운영자가 넘긴 기록이다.** 여러 회차의 기록을 함께 넘기면 합친 배치로 잰다(§5.4).
- **골든 벤치는 CU별 최신 판정 1건만 쓴다**(`docs/standards/golden_benchmark_contract.md` — EOS-60).
  정답지 라벨은 QA 엔진이 볼 내용의 라벨이라 목적이 다르며, 이 계약의 ④단 이력 규칙과 섞지 않는다.
