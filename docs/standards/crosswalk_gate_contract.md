# Crosswalk Gate Contract — 오개념 kebab↔M-id 승인·적재 조건 정본

> 이 문서는 오개념 crosswalk 매핑의 **승인·적재 조건을 코드와 함께 단일 관리**하는 정본이다.
> 코드 정본은 `src/backend/whymath_backend/l1/misconception/crosslink_gate.py`이고,
> `tests/backend/l1/test_crosslink_gate_contract.py`가 이 문서와 코드 상수의 일치를 **동결**한다
> (한쪽만 바뀌면 red). 수백~수천 건으로 규모가 커져도 운영 방식이 흔들리지 않게 하기 위함이다.

## 왜 사람 게이트인가

crosswalk 매핑(런타임 탐지 kebab-id → 리포트에 뜨는 canonical M-id)이 틀리면 **오귀속된 진단 =
오도된 학부모/학생 코칭**이 된다(CLAUDE.md 의사결정 우선순위 #1 학생 웰빙·#2 법적·윤리적,
`math_dsl_remediation_design.md` §1.4). ai_estimated 콘텐츠는 "미검수" 배지로 사용자가 인지할 수
있으나 오귀속 진단은 검증 불가하다. 따라서 **AI 자기승인·검수 없는 적재를 금지**하고, 승인·적재·
노출 플립은 사람(4b-2)이 한다. AI는 제안(후보 생성)·측정(shadow)·리포트(커버리지)·가드 강화만 한다.

## 상태 어휘 (`REVIEW_STATUSES`)

| status | 뜻 |
|---|---|
| `pending` | 미검수(기본) |
| `approved` | 승인 — 적재 대상 |
| `rejected` | 반려 |
| `deferred` | 보류 |

## 필수 서명 (`REQUIRED_SIGNATURE_FIELDS`)

승인(`approved`) 행은 다음 2필드가 **필수**다(검수 책임 추적):

- `reviewer` — 검수자
- `reviewed_on` — 검수일(ISO `YYYY-MM-DD`)

서명 stamp 정본 형식: `검수:{reviewer} {reviewed_on}` (`sign()`이 찍고 `is_signed()`가 검증).

## 승격 규칙 (`promotion_rule` — promote 단계·l4)

검수 큐 → 승인분 승격 시 아래를 **모두** 만족해야 한다(위반은 전건 열거로 실패):

1. `status == approved`
2. `reviewer` present **AND** `reviewed_on` present (서명)
3. `link_type == 직접매핑`이면 `confidence >= DIRECT_MIN_CONFIDENCE`(= **0.6**) — 미만은 인접 오개념·승격 금지
4. `kebab_id ∈ 카탈로그`(`CATALOG_BY_ID` — 전사 왜곡 가드)

## 적재 규칙 (`load_gate` — load 단계·l1)

라이브 `misconception_crosslink` 적재(`load_crosslinks`) 시 각 행은 아래를 **모두** 만족해야 한다
(검수 우회·AI 자기승인을 *코드로* 차단 — candidate 도구 출력·손수 만든 미서명 JSON 거부):

1. `method == LOADABLE_METHOD`(= **`manual`**) — 사람 채택 산출물만(embedding/standard_code 미적재)
2. `is_signed(note)` — note에 검수 서명 stamp(`검수:{reviewer} {날짜}`)가 있어야 함

> 저수준 `MisconceptionCrosslinkStore.populate`는 이 게이트를 거치지 않는다(resolve/shadow 단위의
> 합성 시딩 좌석). 게이트는 sanctioned 진입(`load_crosslinks` = `promote --load`가 호출)에만 있다.
> 한계: 서명 검증은 note 문자열 매칭이라 *고의 위조*(가짜 서명 삽입·DB 직접 편집)를 막지 못한다 —
> 목적은 우발적·관례적 우회(candidate 출력 직접 적재 등) 차단이며, 위조는 도구 밖 행위다.

## 기계 자율 거부 규칙 (`machine_reject` — 측정된 안전 자율 행동·초인간 검증 §3.3)

승인(approve)은 여전히 **사람 전용**이다(AI 자기승인 금지 불변). 그러나 강등전으로 *성취기준
가로지르는 오매핑 거부*가 측정된 구간(cross-standard 거부 240/240·Wilson 하한 0.989)에서는, 기계가
pending 후보를 **자율 거부**할 수 있다(`crosslink_standard_signal.machine_rejectable` +
`crosslink_machine_reject`). 거부는 아래를 **모두** 만족할 때만 허용된다:

1. `standard_agreement == disagree` — kebab 역유도 성취기준과 M-id `standard_code`가 겹치지 않음
2. kebab 증거량 ≥ `MACHINE_REJECT_EVIDENCE_FLOOR`(= **20문항**) — 얇은 역유도는 신뢰 안 함

> **비대칭(핵심)**: 기계는 *거부만* 하고 *승인은 절대 안 한다*. 거부 실패 모드는 보수적(correct
> 매핑을 놓쳐도 오매핑 적재가 아니라 *누락* — resolver는 no_links로 graceful). `agree`·`no_signal`·
> 증거 미달은 전부 인간 폴백. 이 도구는 커밋 큐 템플릿을 **변경하지 않는다**(전행 pending 봉인 유지·
> `test_real_queue_all_pending_unsigned` 무손상) — 거부 대상 *산출*만 하고 반영은 ops가 검토 적용.

## 상수 요약 (코드 = 이 문서)

| 상수 | 값 |
|---|---|
| `REVIEW_STATUSES` | `pending`, `approved`, `rejected`, `deferred` |
| `APPROVED_STATUS` | `approved` |
| `REQUIRED_SIGNATURE_FIELDS` | `reviewer`, `reviewed_on` |
| `DIRECT_MIN_CONFIDENCE` | `0.6` |
| `DIRECT_LINK_TYPE` | `직접매핑` |
| `LOADABLE_METHOD` | `manual` |
| `MACHINE_REJECT_METHOD` | `structural_reject` |
| `MACHINE_REJECT_REVIEWER` | `machine` |
| `MACHINE_REJECT_EVIDENCE_FLOOR` | `20` |

## 흐름 (4b-2 사람 게이트)

```
후보 생성(AI·crosslink_candidates)      → top key "candidates"(미적재)
검수 큐 전사(사람)                        → docs/data/..._review_queue.json (status=pending)
갭 리포트(AI·crosslink_coverage)         → 어디를 볼지(no_candidate/ambiguous/below_threshold)
검수 보조(AI·crosslink_review_aid)       → kebab별 근거 조인(판정 없음)
승인(사람)                                → status=approved + reviewer + reviewed_on
승격·적재(promote --load)                → promotion_rule + load_gate 통과 → misconception_crosslink
shadow 측정 → canary/full 노출 플립(사람) → canonical M-id 리포트 노출
```

## 대장 동기화 (backlog 게이트 `G-crosswalk-approval`)

> 배경: 6회차 아키텍처 감사(`arch_audit_2026-07-13_r6.md` §3)가 발견한 대장 비정합 —
> 사람 서명된 적재 가능 corpus가 커밋됐는데 backlog 게이트는 pending·evidence:null로 남았다.
> 코드 게이트(load_gate)와 backlog 대장이 따로 놀면 "대기 중"의 의미가 흐려진다.

- **동기 이동 규약**: 적재 가능 crosswalk corpus(`data/corpus/misconception_crosslinks_v1/`)에
  행을 추가·승격하는 커밋은 **같은 PR에서** backlog 게이트 대장을 동기 이동해야 한다 —
  ⑴ 전량 승인 완료면 `backlog.py gates clear G-crosswalk-approval --as kiki --evidence ...`(kiki 행동),
  ⑵ 부분 진행이면 게이트 `notes`에 현재 라이브 건수·서명 근거 위치를 갱신.
  대장이 실태를 뒤따라가지 못하는 커밋은 감사 대상이다.
- **clear evidence 요건**: `G-crosswalk-approval` clear 시 evidence는 다음을 포함해야 한다 —
  ⑴ `data/corpus/misconception_crosslinks_v1/_provenance.json`의 `signatures[]` 블록 참조
  ⑵ 서명 당사자(Kiki)의 **진위 확인**(서명 stamp가 본인 승인임을 확인하는 명시 문구).
  본 계약이 스스로 인정하듯(§적재 규칙 한계) 서명 위조는 도구가 탐지할 수 없으므로,
  진위 확인은 게이트 clear의 사람 몫이다.

---

**버전**: v1.1 (대장 동기화 § 추가 — S2-10·2026-07-13) · v1 (Phase 4b-1·2026-07-08) · 코드 정본 `crosslink_gate.py` · 동결 `test_crosslink_gate_contract.py`
