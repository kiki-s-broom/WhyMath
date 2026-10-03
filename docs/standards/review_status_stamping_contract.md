# review_status 각인 계약 — 두 도구의 적용 대상 · 충돌 규칙 · 승격 게이트 ④단 분모 (EOS-136)

> **판정 기준**: main `0e7b4f6b`(§1~§8 · EOS-136). 코퍼스 수치는 그 커밋의 `data/corpus/problem_bank_*/problems.jsonl`
> 전수 실측이고, Wilson 수치는 저장소 `harness/wilson.wilson_upper_bound`(단측 · 신뢰 0.95) 실측이다.
> §9(EOS-27 · 검수 후 내용 지문)의 판정 기준은 main `381ec106`이다.
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
| 검수 후 내용 편집 | 검수 이벤트가 **검수자가 본 레코드의 지문**을 싣고, 각인 도구와 승격 게이트가 코퍼스 현재 지문과 대조한다. 다르거나 **지문이 없으면** 각인·승격하지 않는다(§9). |

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

- **각인 전 지문 대조**(EOS-27): 위 표의 각인값이 있는 판정(approved·rejected)은 검수 이벤트의 내용 지문이
  코퍼스 현재 레코드의 지문과 같을 때만 각인한다(§9). 손질 승인은 각인값이 없어 대조 대상이 아니다.
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
| 검수 지문 정규화(단일 정본) · 3상태 대조 | `schema/review_timer.review_content_fingerprint` · `review_fingerprint_state` | `test_review_timer.py::TestFingerprintNormalization` · `TestFingerprintState` |
| 검수 CLI가 지문을 기록한다 | `review_session.run_review_session` | `test_review_session.py::TestContentFingerprintIsRecorded` |
| 각인 전 지문 대조 · 내용 변경·지문 없음 버킷 | `review_status_verdict_bridge.plan_stamps` | `test_review_status_verdict_bridge.py::TestContentFingerprint` |
| 승격 게이트 ②단 지문 대조 | `golden_promotion_gate.evaluate_promotion` · `main` | `test_golden_promotion_gate.py::TestContentFingerprintStage` · `TestContentFingerprintCli` |
| ④단 분모 = 검수 배치 · 분자 = 이력 | `golden_promotion_gate.PromotionGateReport` | `test_golden_promotion_gate.py::TestReviewBatchDenominator` |
| 판정 파일 ≠ 감사로그 | `golden_promotion_gate._load_backfill_audit` | `test_review_status_verdict_bridge.py::TestReviewVerdictFileIsNotTheAudit` |
| 실 파이프라인 관통(축적 → 검수 → 각인 → 게이트) · 음성 대조(승인 → 내용 손편집 → 차단 포함) | 위 전부 | `test_eos_anchor_e2e_a4.py::TestGoldenPromotionGateOnPipelineOutput` |

---

## 8. 한계 (명시)

- ~~**검수 후 내용 편집은 탐지하지 못한다.**~~ → **해소(EOS-27 · §9).** 판정 기준 `0e7b4f6b`의 서술은
  "검수 이벤트에 검수자가 본 내용의 지문이 없어, 승인 뒤 문항 내용을 손으로 고쳐도 각인 도구는 approved를
  찍고 게이트는 값(`review_status`)만 대조해 통과시킨다"였다. 지금은 두 도구가 지문을 대조한다.
  **남은 한계**는 §9.5.
- **코퍼스 단위 백필의 감사로그는 실행마다 덮어쓴다(append가 아니다).** 고정 코퍼스에 레코드를 더하고
  다시 돌리면 이전 각인 기록이 감사 파일에서 사라진다(git 이력에는 남는다). 그 감사로그로 게이트를
  돌리면 이전 레코드가 `review_status_not_backfilled`로 보인다. 실측(판정 기준 커밋의 코드): 3건 각인 →
  1건 추가 → 재실행하면 감사 파일에 새 1건만 남았다. 사람 판정 각인 도구의 감사로그는 append 전용이라
  해당하지 않는다. 추적 태스크: `PB-16-corpus-backfill-audit-append`.
- **배치는 운영자가 넘긴 기록이다.** 여러 회차의 기록을 함께 넘기면 합친 배치로 잰다(§5.4).
- **골든 벤치는 CU별 최신 판정 1건만 쓴다**(`docs/standards/golden_benchmark_contract.md` — EOS-60).
  정답지 라벨은 QA 엔진이 볼 내용의 라벨이라 목적이 다르며, 이 계약의 ④단 이력 규칙과 섞지 않는다.

---

## 9. 검수 후 내용 편집 — 내용 지문 (EOS-27)

> **판정 기준**: main `381ec106`. §8이 인정한 사각("승인 뒤 문항 내용을 손으로 고쳐도 탐지하지 못한다")을 닫는다.

### 9.1 무엇이 비어 있었나

게이트 ②단은 최신 사람 판정이 `approved`인지만, ③단은 `review_status` **값**(감사 각인값 = 코퍼스 값)만
봤다. 둘 다 문항 *내용*은 보지 않는다. 그래서 승인·각인을 정상으로 마친 문항의 정답·해설·조건을 누군가
손으로 고쳐도 사람 판정·감사로그·코퍼스 값이 전부 그대로여서 게이트가 통과시켰다. 승격이 시작되면
(MP-03 판정 시점 실승격 0건) 사람 승인 이후의 변경이 재검수 없이 학생에게 나가는 경로다.

### 9.2 지문 — 무엇을 해시하는가

정본은 `schema/review_timer.review_content_fingerprint` **한 함수**다(검수 CLI = 기록, 각인 도구·게이트 = 대조).

| 규칙 | 내용 | 근거 |
|---|---|---|
| 대상 | 검수자에게 보인 레코드 전체(코퍼스 모드는 행 자신, 큐 모드는 `candidate_payload`) | 검수 화면은 본문 10개 축만 렌더하고 나머지는 키 이름만 고지한다. 렌더 축만 해시하면 *안 보인 필드*(힌트·검산 조건)의 사후 편집이 조용히 통과한다 — 테스트 `미렌더_힌트` 행이 고정 |
| 제외 | 최상위 `review_status` · `review_score` · `quarantine_reason` · `quarantined_at` · `updated_at` | 검수 **뒤에** 정당한 도구(각인·격리)가 쓰는 운영 메타. `review_status`를 넣으면 각인 직후 전건이 "내용 변경"으로 보인다. 집합은 좁게 동결(`test_excluded_set_is_exactly_the_documented_one`) — 넓히면 그만큼 구멍이다 |
| 정규화 | 최상위 `None` 값 키를 뺀다(키 없음 ≡ null) · 키 정렬 · `ensure_ascii=False` · 최소 구분자 | 직렬화 순서·널 표기에 의한 거짓 "변경" 방지. 빈 문자열·빈 목록·중첩 `None`은 **내용**이다 |
| 표기 | `sha256:` + 소문자 hex 64자 | `l3/publish_gate`의 `content_hash`와 같은 표기 |
| 직렬화 불가 값 | `TypeError`(`str()`로 접지 않는다) | 접으면 서로 다른 객체가 같은 지문을 낼 수 있다 |

**EOS-50(`content_hash`)과의 관계 판정**: 같은 *레시피*(키 정렬 JSON → sha256)이되 **다른 물건의 해시**다.
`compute_content_hash`는 개념 버전 payload(`ConceptVersionPayload`)의 게시 전이 검증(재계산 == 승인 시점
각인값)이고, 이쪽은 문항(CU) 코퍼스 레코드의 *검수 시점* 지문이다. 입력 모델이 달라 함수를 공유하지 않는다
(공유하면 개념 payload 스키마 변경이 문항 지문을 흔든다). 표기 접두만 맞췄다.

### 9.3 3상태 대조 — 모름은 일치가 아니다

`review_fingerprint_state(검수 시점 지문, 현재 지문)` → `match` · `changed` · `unknown`(어느 한쪽이라도 없음).

| 상태 | 각인 도구 (`review_status_verdict_bridge`) | 승격 게이트 (②단) |
|---|---|---|
| `match` | 기존 규칙대로 각인 | 통과(③단 이하로 진행) |
| `changed` | **각인 거부** → `content_changed` (exit 1). 코퍼스에 노출 통과값이 이미 있으면 `exposure_risk` — 같은 값이 이미 찍혀 있어도(`already_stamped`가 될 레코드) 내용 변경이 먼저다 | `review_content_changed` |
| `unknown` | 빈 칸이면 **각인 보류** → `fingerprint_unverifiable` (exit 1). 이미 채워진 레코드는 쓸 것이 없으므로 기존 버킷을 따른다 | `review_fingerprint_unverifiable` |

게이트 사유 순서: 코퍼스 부재 → 판정 없음 → 반려 → 손질 승인 → **내용 변경 → 지문 없음** → 각인 기록 없음 →
감사/코퍼스 불일치 → 각인값 비승인. 지문 단이 ③단(값 대조) 앞에 있는 이유: 내용이 바뀐 건은 값 대조가 전부
초록이어도 막혀야 한다 — 그것이 사각이었다(`test_fingerprint_stage_precedes_the_audit_stages`가 고정).

### 9.4 판정 두 건

**(a) 지문 없는 판정의 처리 — '보류'(현행 유지 아님).** 선택지는 두 개였다. *현행 유지*(지문이 없으면 옛 방식대로
각인·승격)는 "모름"을 "일치"로 읽는 것이라 이 필드가 막으려는 사각을 **옛 이벤트 전체에 대해 영구히 연다**
— 지문이 없는 승인은 정의상 편집 여부를 알 수 없다. *보류*는 옛 이벤트의 승인을 재검수로 갱신해야 한다는
비용이 든다. 비용이 작다고 판단했다: ① 판정 시점 실승격 0건이라 막힐 승격이 없고 ② 재검수는 항목 표시 + 키 1회
이며 ③ 재검수 종결이 새 지문을 싣는 정본 해소 경로다(`test_rereview_with_a_fingerprint_unblocks_the_held_record`).
만료 없는 유예(그랜드파더)를 만들지 않는다 — 우회 플래그도 없다(`--force` 류 부재 테스트 유지).
영향: 이 변경 이전에 만든 검수 이벤트(예: MP-03 15건)는 전부 `fingerprint_unverifiable`이며 재검수 전까지
각인·승격되지 않는다.

**(b) 손질 승인(`approved_with_edit`) 해금 — 해금하지 않는다(재검수 유지).** 질문은 "검수 도구가 손질 후 내용의
지문까지 기록할 수 있으면 재검수 없이 각인할 수 있는가"였다. 판정:

1. **지금 도구는 손질 후 내용을 보지도 저장하지도 않는다.** `e`는 "손질하면 쓸 수 있다"는 표시일 뿐이고 편집
   기능이 없다. 이벤트가 싣는 지문은 검수자가 *본*(= 손질 전) 내용의 지문이다. 이 값은 "코퍼스가 아직
   손질 전 내용인가"를 알려 줄 뿐, 손질 후 내용의 승인 근거가 아니다.
2. 지문이 `changed`로 바뀐 손질 승인 레코드는 "누군가 코퍼스를 고쳤다"까지만 안다. **그 최종 텍스트를 사람이
   본 기록이 없다** — 이것은 재검수가 만드는 증거(최종 내용의 지문을 단 새 승인)와 같은 물건을 다른 근거로
   대체하려는 시도다. 무검증 승인 경로를 새로 여는 것이므로 채택하지 않는다.
3. 그래서 각인 도구는 손질 승인을 지문과 무관하게 `held_edit_pending`으로 둔다(내용이 바뀌었어도 — 테스트
   `test_edit_pending_verdict_is_still_just_held`).
4. **해금의 조건(미래 판정용)**: 검수 도구가 *도구 안에서* 손질을 받고 손질 **후** 내용의 지문을 별도 필드로
   싣고, 그 내용을 사람이 확인하는 단계가 있을 때만 재판정할 수 있다. 그것은 사실상 "재검수가 도구 안에서
   일어난다"이므로 지금의 "손질 → 재검수(approved)" 경로와 증거 수준이 같다 — 얻는 것은 왕복 절감뿐이다.

### 9.5 남은 한계 (명시)

- **지문은 JSONL 매체에서만 운반된다.** `review_timer_event`(DB)에는 지문 컬럼 좌석이 없다.
  `ORM.from_schema`는 지문이 실린 이벤트를 **조용히 버리지 않고 `ValueError`로 거부**한다(침묵 실패 금지).
  DB 영속 좌석(마이그레이션 + 프로브 + 인벤토리 귀속)은 후속 태스크 `EOS-174-review-timer-fingerprint-db-seat`다.
- **지문은 변조 방지가 아니라 변경 탐지다.** 누군가 코퍼스와 검수 이벤트 JSONL을 **둘 다** 고치면(이벤트의 지문까지
  다시 계산해 넣으면) 이 장치는 못 본다. 이 한계는 이벤트 파일을 쓰는 경로가 검수 CLI 하나라는 운영 전제와
  `append` 전용 관례에 기대며, 서명·해시 체인은 이 태스크의 범위 밖이다.
- **큐 모드 검수의 지문은 `candidate_payload` 기준이다.** 큐 후보는 수용 전 비수용 후보라 코퍼스에 없고(§2·게이트
  ① 서로소), 수용 뒤 코퍼스 레코드와 직렬화가 다르면 `changed`로 보수적으로 막힌다 — 재검수가 해소한다.
- **여러 회차 이벤트를 합칠 때** 파일 순서상 마지막 종결의 지문이 쓰인다(판정 해석 규칙과 같다).
