# P3-03 미분 은행 감사(S5) 5회차 — 8회차 교정 은행 504건

> 태스크 `P3-03-coverage-fill` · 2026-10-09 · 1회차 `../bank_audit/`(k = 68) · 2회차 `../bank_audit_r2/`(k = 23) ·
> 3회차 `../bank_audit_r3/`(k = 11) · 4회차 `../bank_audit_r4/`(k = 5) · 자격 측정 `../qualification/`(프로토콜 합격: 검출 120/120 · 오경보 6/120)

## 무엇이 바뀌었나

4회차 결함 판정 5건의 원인 4종(`../bank_audit_r4/disposition.json`)을 생성기에서 교정하고 은행을 다시 만들었다
(커밋 `232f8f22` 8회차 규칙 · `56a2662e` 02-06 진단 틀 다양성 복원 · `37caeaa7` 결정론 저작 서명 `authored_by` 추가 —
마지막 것은 판정자 묶음에 들어가지 않는 출처 필드라 문항 내용과 무관하다). 4회차 동결 사본 대비 문항 id 500개 유지(그중
14개 내용 변경), 4개 교체. 4회차 결함 5건 중 원문 그대로 남은 레코드는 0건이다. 1~4회차 결과(불합격)는 as-found로 그대로
남는다.

## 사전 등록 (판정자 라벨을 받기 전에 커밋)

- **은행**: sha256 `3abfc4e65c5d2b809bb849064fee979e5dbf8c30c243b8186334acb75b949bf3`(`manifest.json`).
- **프로토콜**: 1~4회차와 같다 — 기계 게이트 ∪ 판정자 A ∪ 판정자 B, 지침 `../qualification/rater_protocol.md` 그대로,
  판정자 지시문 동일(입력 폴더 경로만 다르다). 기계 투표의 우회로 판정기는 자격 측정을 통과한 4회차 규칙 집합이다
  (`EXCLUDED_GUARD_RULES = POST_QUALIFICATION_RULE_IDS` — 5·6·7·8회차 규칙은 생성기 빌드 가드 전용).
- **묶음**: CLI `bank-sheets`, 같은 시드(20261008)·같은 방식(63건 × 8묶음). 묶음별 sha256은 `manifest.json`.
- **기계 라벨**: `machine_labels.jsonl` — 504건 중 결함 0건.
- **판정 규칙**: S5 = Wilson 단측 97.5% 상한(k, 504) ÷ 검출률 단측 97.5% 하한(0.9690) ≤ 0.02 → **k ≤ 3이면 통과**.
- **as-found**: 이 감사 뒤 결함을 교정해도 같은 504건을 다시 채점해 결과를 바꾸지 않는다.

## 결과 (2026-10-09) — S5 통과 · as-found k = 1

판정자 16명 전원 완료(중단 없음 — 출력 16개 모두 63줄·id 고유·입력 집합 일치·형식 검사 통과). 정답 오류 0건.

| 구성요소 | 결함 판정 |
|---|---|
| 기계 게이트 | 0 / 504 |
| 판정자 A | 1 / 504 |
| 판정자 B | 0 / 504 |
| **프로토콜 합집합 k** | **1 / 504** (1회차 68 · 2회차 23 · 3회차 11 · 4회차 5) |

CLI `s5` exit 0 — U = 0.01115, L = 0.96898, **보정 상한 0.01151(기준 ≤ 0.02) — 승인 근거 성립**.

| 원인 | 건수 | 비고 |
|---|---|---|
| 02-10 속도·가속도 진단 — x = t^2·t = 2라 상수 가속도 2가 평가 시각과 같고 x(2)/2·v(2)/t 혼동도 같은 값 | 1 | 확신 '불확실', 정답은 옳음(변별 약화) |

이 1건은 S5 판정에 그대로 들어가 있다(as-found). 승인 대상은 감사받은 504건 그대로이며(동결 사본 `audited_bank.jsonl`,
sha256 위 사전 등록값과 동일), 이 원인을 교정하려고 은행을 다시 만들면 그 은행은 감사받지 않은 새 은행이 된다. 원인 분류
`disposition.json`(교정용, 판정 불변). 판정자 라벨·근거 `llm_labels/`.

## 승인 각인 (2026-10-09)

S5 통과 뒤 정본 경로(`review_status_stamping_contract.md` §2 — 감사 라벨을 만들어 `KNOWN_CORPORA`·
`AUDIT_LABEL_MAP`에 편입)로 은행을 승인 각인했다.

- **감사 라벨**: `docs/data/corpus_audit_p3_calculus1_diff_v0.jsonl` — 이 회차 프로토콜 합집합(기계 ∪ A ∪ B) 504행 +
  as-found 선언(n = 504, 결함 1). 코퍼스 단위 백필의 판정은 보정 없는 Wilson 95% 상한 0.0088 ≤ 0.02 → `approved`
  (승인의 정본 근거는 위 S5 보정 상한 0.01151이다 — 백필 판정은 같은 라벨의 형식 변환일 뿐 더 느슨한 기준으로 승인한 것이 아니다).
- **편입**: 코퍼스 키 `p3_calculus1_diff_v0` — `KNOWN_CORPORA` 8번째·`AUDIT_LABEL_MAP`. 고정 코퍼스 8종 3,142건
  (approved 2,984 · pending 158).
- **각인**: `persona_fit` 백필(밴드 CORE 240 · MID_HIGH 108 · HIGH 96 · KILLER 60) → `review_status` 백필(504건 `approved`).
  감사로그 `docs/data/persona_fit_backfill_audit/`·`docs/data/review_status_backfill_audit/`의 `problem_bank_p3_calculus1_diff_v0.jsonl`.
- **내용 결속**: 각인 두 키를 생성기 기본값으로 되돌린 은행 바이트(`p3_calculus1_diff_batch.strip_backfill_stamps`) ==
  이 폴더의 `audited_bank.jsonl`(sha256 `3abfc4e6…`). `tests/backend/l1/test_p3_calculus1_diff_bank_coverage_link.py`가
  동결하며, 각인을 둔 채 내용 1글자를 바꾼 주입에서 RED다 — 생성기를 고쳐 내용이 바뀌면 새 회차 감사 없이는 승인이 옮겨 가지 않는다.
  생성기 드리프트 검사(`--check`)는 각인 두 키만 제외하고 비교한다.
- **Coverage 재측정**(P3-02 CLI `phase3_coverage`, 각인 전 `c099f756` → 각인 후): Content Coverage 3/10(30%) → **10/10(100%)**
  (목표 ≥ 95% 충족) · Curriculum Coverage 30% → 100% · 해설 연결 2 → 9 · Graph Connectivity 30% → 50%.
  Concept Completeness는 0/10 그대로다 — 힌트 연결이 10개념 모두 측정 불가(힌트 저장 좌석 부재 · ARCH-39 · P3-04 소관)이고,
  02-02는 다른 코퍼스(`conceptual_v0`)의 승인 문항 24건에 해설·풀이 단계가 없다.
- **is_published**: `False` 유지 — 승인(`review_status`)과 공개(`is_published`)는 다른 축이다.
