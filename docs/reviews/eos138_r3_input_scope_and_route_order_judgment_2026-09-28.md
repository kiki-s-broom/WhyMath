# EOS-138 판정 — 상태 머신 R3의 입력 범위(②)와 오답 직후 경로 순서 충돌(③)

> **판정 기준: main `78a8edff`** (의뢰 기준 `919865d4`와 비교해 `l2/remediation_policy.py`·`l2/learning_state_policy.py`는 바이트 변화 0 — `git diff --stat 919865d4 origin/main -- src/backend/whymath_backend/l2/` 실측. 그 사이 main에 착지한 `EOS-123`(정답 회차도 같은 조건으로 스캔·후보 없으면 1턴 감쇠)은 이 판정의 결론을 바꾸지 않는다.)
> **태스크**: `EOS-138-r3-misconception-input-scope` (acceptance ①~⑥)
> **작성**: ③ 교수학 판정 초안 = pedagogy-designer(L4 관점) · ② 처분과 집행 = backend-engineer
> **실행 환경**: 컨테이너 · PostgreSQL 16 + pgvector 0.6.0 · `alembic upgrade head` EXIT=0 · `WHYMATH_RUN_INTEGRATION=1`

---

## §0. 결론

1. **② R3 입력 = 이번 응답의 스캔 후보 중 신뢰 > `MISCONCEPTION_REMEDIATION_FLOOR`(0.7)**. `turns_since_evidence = 0`으로 좁히는 안(acceptance ② 원안)은 **기각**한다 — ⑥ 반례에서 뚫린다(§1).
2. **③ 정본 = 상태 머신 순서(`learning_state_policy.V1_RULES`: R5 > R3 > R4 > …)**. 오답 직후 경로 결정자는 이것 하나다.
3. **`select_route` 경로 표는 폐기(삭제)**한다 — 하한 상수 `MISCONCEPTION_REMEDIATION_FLOOR`와 반복 사다리(`select_rung`·`EscalationRung`)만 남긴다. 정렬(a)이 아니라 삭제(b)를 고른다(§4).
4. **R4가 R3를 이기는 예외는 있다** — "선수 결손이 *직접 측정*으로 확인됨" **그리고** "같은 오개념이 교정을 받고도 버팀"이 **동시에** 성립할 때만이다. 단 R4 생산자가 미배선이라 이 저장소에 규칙으로 넣지 않고 **`EOS-127`로 이관**한다(§5).
5. EOS-24가 추천 쪽에 둔 안전장치 ①②(`l2/learning_state_recommendation.py`)는 **유지**한다 — 중복이지만 해가 없고, 배포 전 원장에 적힌 옛 R3 결정의 방어선이다(§2).

---

## §1. ② 처분 — R3 입력을 "이번 응답의 스캔 후보"로 좁힌다

### 1-1. 무엇이 문제였나 (acceptance ① 실측)

`AttemptEvidence.confirmed_misconception_ids`는 규칙 R3(`R3-wrong-misconception`)의 유일한 입력이다. 종전에는 `l2/learning_state_evidence.py::_active_misconception_ids`가 이 필드를 채웠고, 그 함수는 **학생 전체의 활성 가설 전부**를 신뢰 하한 없이 읽었다. 그래서 다른 개념에서 생긴 옛 가설 1건만 남아 있어도 이번 오답에 R3가 발화했다. 그때 `target_misconception_id`는 신뢰가 가장 높은 옛 가설을 가리켰다(EOS-24 판정문 §4 반례 S1).

### 1-2. 기각한 안 — `turns_since_evidence = 0`

acceptance ② 원안은 "이번 회차에 증거를 받은 가설(tse 0)"으로 좁히는 것이었다. ⑥ 정정(EOS-140 실측)이 이 안의 전제를 깨뜨렸다.

- tse는 **스캔한 회차에만** 움직인다. 정답·답안 없는 오답·지문 없는 문항은 스캔하지 않는다(`api/me.py::_scan_attempt_misconceptions` → `NOT_RUN` → 가설 행동 `NONE`).
- 실 PG 반례: C 오개념 오답(tse 0) → C 정답(미스캔) → P 답안 없는 오답(미스캔). 이 흐름에서 옛 가설의 tse는 **0으로 남는다**. tse 0으로만 좁히면 이 반례에서 R3가 여전히 발화한다.
- 원장 회차 경계(`_evidence_since_previous_attempt`)를 재사용하는 절충안도 있었다. 이 안은 두 응답 **사이의** 코치 대화 턴에서 매치된 가설을 여전히 "이번 회차"로 센다. EOS-140이 스스로 적어 둔 남는 한계와 같은 구멍이다.

### 1-3. 채택한 안 — 이번 응답의 스캔 후보

| 위치 | 변경 |
|---|---|
| `l2/learning_state_evidence.py::build_attempt_evidence` | `this_attempt_misconceptions: Sequence[tuple[str, float]] = ()` 인자를 받는다. 신뢰 **> 0.7**만 남기고, 신뢰 내림차순으로 정렬하되 동률은 id 오름차순이다. 중복 id는 최고 신뢰 하나로 합친다. [0,1] 밖·NaN은 `ValueError`로 거부한다(조용히 "하한 이하"로 떨어지지 않게). 정답이면 빈 튜플이다. **가설 테이블을 조회하지 않는다** — `_active_misconception_ids`는 삭제했다. |
| `api/me.py::submit_attempt` | `APPLY`(오답·스캔함) 분기에서 `apply_candidates`가 **반환한** 갱신 세트 중, 이번 스캔의 `gate_passed` 후보 id에 든 것만 `(misconception_id, 갱신 후 confidence)`로 넘긴다. 그 밖의 분기(미스캔 `NONE`·정답 `DECAY_ONLY`·`HOLD_CONFLICT`)는 빈 값이다 → R3 미발화. |

**왜 원시 쌍인가**: 가설 타입 `MisconceptionHypothesis`는 L4에 있고, L2는 L4를 import할 수 없다(역방향 의존 금지).
**왜 갱신 후 신뢰인가**: 같은 오개념이 앞서 쌓였다면, 이번 증거로 강화된 값이 교정의 근거가 된다. 후보 원값을 쓰면 반복 관측의 누적이 사라진다.
**왜 갱신 세트 전부가 아니라 이번 후보 id로 거르는가**: 갱신 세트에는 이번에 증거를 못 받고 감쇠만 한 옛 가설도 들어 있다. 이 필터를 빼면 반례 (b)·(c)가 뚫린다(§6 M5).

**결과**:
- 옛 가설만 남은 학생의 오답은 R3로 가지 않는다. 미스캔 오답이든, 스캔됐지만 다른 오개념이 하한 이하로 매치됐든 마찬가지다.
- 코치 대화 턴에서 매치된 가설도 더는 R3 입력이 아니다. EOS-24 판정문 §4의 "남는 한계"가 해소된다.
- `schema/learning_state.py`의 필드 설명("이번 오답에서 *확인된* 오개념 id. 후보(가설)가 아니라 확인분만")에 코드가 처음으로 일치한다.

### 1-4. 오개념 preload 금지와의 관계

조립기는 이제 과거 가설을 **읽는 경로 자체가 없다**. 정책 입력에 실리는 오개념은 이번 응답이 방금 관측한 후보뿐이다. 정답 회차에는 넘겨받은 값이 있어도 싣지 않는다(`test_misconceptions_are_not_preloaded_on_a_correct_answer`).

---

## §2. EOS-24 안전장치 ①②를 유지하는 근거

EOS-24는 추천이 R3를 집행하기 전에 근거를 두 번 확인하는 방어선을 뒀다. ①은 이번 회차에 증거를 받은 가설(tse 0 + 원장 회차 경계)이 있는지, ②는 그 신뢰가 0.7 초과인지다. §1 이후 새로 적재되는 R3 결정은 정의상 ①②를 이미 만족한다. 이번 스캔으로 갱신된 가설은 직전 원장 전이보다 늦고, 신뢰는 0.7을 넘는다. 그래서 두 안전장치는 **중복**이다.

**판정: 걷어내지 않는다.**
- **해가 없다** — 새 결정에서는 항상 통과하므로 추천 결과를 바꾸지 않는다. 조회는 R3 지시가 있을 때만 1건이다.
- **배포 경계의 방어선이다** — 배포 전에 원장에 적힌 R3 결정은 좁히기 전 입력(학생 전체 가설)으로 내려진 것이다. 추천은 원장 최신 결정을 읽으므로, 배포 직후 그 옛 결정을 집행할 때 ①②가 유일한 근거 재확인이다.
- 걷어내는 비용(코드·테스트 삭제)에 비해 얻는 것이 없다. 원장이 충분히 회전한 뒤 재판정할 수 있다.

코드에는 `l2/learning_state_recommendation.py` 모듈 docstring 2줄로 이 근거를 남겼다. 로직은 무변경이다(편집 전후 AST 동일 — docstring 제외 — 를 단언했다).

**측정 표면 변화(정직 표기)**: `test_stale_hypothesis_does_not_pin_remediation_to_another_concept`는 종전에 "옛 가설로 R3 재발화 → 추천 안전장치 ①이 막음"을 쟀다. 이제는 R3 자체가 발화하지 않으므로(R6) "추천 지시 없음"을 잰다. 안전장치 ①의 회차 경계는 HTTP 경로로는 더 이상 도달하지 않는다. 남는 것은 hermetic SQL 계약(`tests/backend/l2/test_learning_state_recommendation.py` — `max(learning_state_transition.occurred_at)`)이다.

---

## §3. ③ 판정 근거 — 상태 머신(R3 > R4)이 정본인 이유

| # | 근거 | 요지 |
|---|---|---|
| G1 | **입력 강도의 비대칭** | §1 이후 R3는 "이번 응답에서 신뢰 > 0.7로 매치된 오개념"이다. RT1의 입력은 현재 개념 C의 숙달 < 0.4인데, 오답 1회 뒤 0.15는 BKT 신뢰도 0.17짜리다(EOS-24 §4). **강한 증거를 약한 증거 뒤에 두는 순서**는 증거 기반 결정의 역전이다. |
| G2 | **RT1은 사실상 RT2를 사문화한다** | 콜드스타트 학생의 첫 오답은 거의 전부 숙달 < 0.4에 떨어진다. RT1 > RT2면 초기 학습자에게 오개념 교정 경로는 거의 도달할 수 없다. "모든 오답은 오개념 후보 분석 시도"(CLAUDE.md 교수학)가 분석은 하되 *행동으로는 버리는* 형태가 된다. |
| G3 | **표 자신의 주석이 RT1 입력의 약함을 자인했다** | 삭제 전 `V1_ROUTE_RULES` 위 주석: "지목된 결손이 있다는 것은 이미 원인 분석이 끝났다는 뜻이고, **숙달 0.3은 아직 원인을 모른다는 뜻**이다." 원인 미상 신호(RT1)가 원인 확인 신호(RT2)를 이기는 순서는 그 주석과 모순된다. 또한 RT1은 "어느 선수로" 갈지 지목하지 못한다 — C 숙달은 P에 대한 증거가 아니다. |
| G4 | **오개념은 방치하면 따라온다(개념 변화 이론의 dissatisfaction 조건)** | 확인된 오개념을 둔 채 선수로 내려가면, 복귀 시 같은 오개념이 재발한다(오개념의 강건성). 교정의 첫 단계는 기존 개념에 대한 불만족 유발이며, 반례 유도 1턴(`intervene` COUNTEREXAMPLE)으로 싸게 실행된다. Polya 4단계 관점에서도 반례 질문은 "이해/검토" 단계 소크라테스 발화라 답을 주지 않는다. |
| G5 | **오판 비용의 비대칭 + 기존 상한** | R3가 틀렸을 때(실은 선수 결손)의 비용은 반례 1턴 + 1문항이다. `EOS-24` ③(교정 고정 1문항 후 해제)과 R5(연속 3회 → 설명·힌트)가 이미 상한을 건다. RT1이 틀렸을 때(실은 오개념)의 비용은 이미 아는 선수 개념으로의 하강이다. 지루함과 자기효능감 손상을 부르고(의사결정 우선순위 1), 오개념도 해소되지 않는다. 단일 진실 원천도 이미 상태 머신 쪽에 있다(EOS-24 §2 ②: 추천이 상태 머신을 *집행*). |

**반대 근거와 기각 사유**

- **R1: intelligibility 조건(Posner 등)** — "선수 개념이 없으면 새 개념이 이해 가능하지 않다." → *조건 자체는 인정한다.* 그러나 RT1의 입력(C 숙달 < 0.4)은 그 조건을 측정하지 않는다. intelligibility 실패를 주장하려면 **P에 대한 직접 증거**가 있어야 한다. 이 근거는 RT1이 아니라 §5의 예외(R4-측정 결손)를 정당화하며, 그리로 흡수한다.
- **R2: "바닥 없는 교정 설명"(RT1 description)** — 교정 설명이 딛고 설 선수가 없다는 주장이다. → R3의 첫 개입은 설명이 아니라 반례 계산 요청이다(학생이 직접 (1+1)²을 계산). 반례가 선수를 요구하는 경우는 §5 예외 조건 ⓑ와 §7 반례 S-A로 다룬다.
- **R3: 계획서 §9가 선수 → 오개념 순서를 적었다** — 계획서 순서는 *숙달 구간 경로 어휘*의 나열이다. 오개념 신호 강도를 좁힌 뒤의 우선순위 판정이 아니다. 그 순서를 코드로 옮긴 MISC-30도 소비처 0건으로 "별도 판단 필요"를 자인했다(MISC-30 [배선 범위]).

---

## §4. 다른 쪽 처리안 — (b) 삭제 채택

| 안 | 내용 | 판정 |
|---|---|---|
| (a) 정렬 | `V1_ROUTE_RULES`를 RT2 > RT1로 뒤집어 상태 머신과 맞춤 | **기각.** 소비처 0건인 두 번째 순서 선언을 유지하면 "같은 질문의 진실 원천 둘"(플레이북 붕괴 연쇄 ④ 유지보수 지옥)이 그대로다. 두 표는 입력 어휘가 달라(숙달 구간 vs 증거 목록) "맞췄다"를 기계로 확인할 방법도 없다. |
| (c-1) 어댑터 | `select_route`가 상태 머신을 불러 경로 어휘로 번역 | **기각.** 소비처 0건에 대한 투기적 이음매. 교체 가능성 Protocol은 `LearningStatePolicy`가 이미 가진다. |
| (c-2) 현행 유지 + 비권위 표기 | docstring에 "비권위·참고용" 명기 | **기각.** 선언만 있고 발화하지 않는 결정 로직은 `EOS-127`이 R4에 대해 없애려는 바로 그 형태다. |
| **(b) 삭제** | 경로 표 전부 삭제, 하한·사다리만 유지 | **채택·집행.** |

### 4-1. 집행 내역

**삭제 전 소비처 전수 검색** — `select_route|V1_ROUTE_RULES|RouteRule|RemediationRoute|RemediationSignals|RemediationDecision|decide_remediation|RemediationPolicy|_mastery_route|prerequisite_mastery_ceiling|weak_concept_mastery_ceiling`, 저장소 전체(`.git` 제외):

| 위치 | 성격 | 처리 |
|---|---|---|
| `l2/remediation_policy.py` | 정의 자신 | 삭제 |
| `tests/backend/l2/test_remediation_policy.py` | 전용 테스트 | 경로·미러·Protocol 테스트 삭제, 사다리·불변식·고정 테스트 유지 |
| `scripts/analysis/eos_feature_inventory_v2.py` (`WM-E-214` 설명) | 인벤토리 **생성기 소스**(산출 장부 `backlog/inventory/feature_inventory_v2.yaml`은 저장소에 없음 — 설명의 정본이 이 `_e(...)` 호출) | 설명 정정 |
| `backlog/tasks/MISC-30-*.yaml`·`backlog/tasks/EOS-138-*.yaml` | 대장 산문 | 무수정(대장은 CLI 소관) |
| `docs/reviews/eos24_recommendation_reads_learning_state_judgment_2026-09-25.md` | 과거 판정 기록 | 무수정(판정 시점 기록) |

**런타임 소비처 0건**을 확인했다. 실사용 심볼 3종(`MISCONCEPTION_REMEDIATION_FLOOR`·`select_rung`·`EscalationRung`)의 import처는 모두 무변경으로 계속 동작한다 — `l2/learning_state_recommendation.py`·`l2/learning_state_evidence.py`(신규)·`l4/misconception/intervene.py`·`l4/misconception/models.py`·`harness/wh1_loop.py`.

**처리 항목**:
1. 숙달 미러 2필드(0.4/0.7)는 경로 판정만을 위해 있었으므로 함께 삭제했다. `l2.recommendation_contract` import도 사라졌다. 옛 테스트가 쥐고 있던 `PREREQUISITE_MASTERY_CEILING == 0.4` 리터럴 고정은 `tests/backend/l2/test_recommendation_contract.py::test_prerequisite_ceiling_value_is_pinned`로 옮겼다(보호가 줄지 않게).
2. 모듈 docstring 머리에 판정 요지 3줄과 이 판정문 경로를 적었다.
3. `EscalationRung.PREREQUISITE_CONCEPT` docstring에 한 줄을 추가했다: "이 등급은 반복 오류 사다리의 강도 표기이지 경로 순서가 아니다. 선수 경로 전환은 상태 머신 R4(와 EOS-127의 R4a 예외)가 소유한다."
4. 재등장 방지 코드 가드 `tests/backend/l2/test_remediation_policy.py::TestNoRouteVocabulary`를 추가했다. 가드는 네 가지를 본다. 삭제 심볼 8종 부재, `__all__` 정확 일치, 최상위 정의 이름의 `route` 어휘 AST 전수(개명 부활 차단·스캔 0건이면 실패), `recommendation_contract` import 부재.
5. `learning_state_policy.py` docstring에 "이 순서가 유일한 정본" 한 문단을 추가했다.
6. MISC-30 acceptance ①~⑥은 사다리·하한·작동 비율만 요구한다. 그래서 이 삭제는 done 계약을 깨지 않는다. 경로 표는 acceptance 밖의 부수 산출물이었다.

**사다리 4칸의 이름**: `EscalationRung.PREREQUISITE_CONCEPT`(같은 오개념 증거 ≥ 4)는 "강도"로 선언됐지만 이름은 경로다. 경로 표가 사라지면 R3와 어긋나는 **세 번째 순서 신호**처럼 읽힐 수 있다. 이 판정은 그 칸을 §5 예외의 입력 ⓑ로 흡수해 의미를 고정한다. 사다리 4칸은 단독으로 경로를 바꾸지 않고, 측정된 선수 결손과 동시에 성립할 때만 R4 예외를 연다. 위 3번의 docstring이 이를 명기한다.

---

## §5. R4가 R3를 이겨야 하는 예외 — **EOS-127로 이관**

이 저장소에는 구현하지 않는다. R4 입력 `prerequisite_gap_concept_ids`의 생산자가 미배선(`EOS-127`)이라, 지금 넣으면 발화 0건 규칙이 하나 더 생긴다(선언만 있고 발화하지 않는 규칙 금지). 아래 조건을 `EOS-127`의 착지 조건으로 넘긴다.

**규칙 초안 `R4a-measured-gap-after-resistant-misconception`** (R5 다음, R3 앞):

- ⓐ **선수 결손이 직접 측정으로 확인됨** — R4 입력의 선수 P에 대해 세 조건이 모두 성립해야 한다. `l2.prerequisite_recommendation`의 `PrerequisiteGap`이 `weakness < PREREQUISITE_MASTERY_CEILING`(0.4, 기존 상수 재사용)이고, `agreement == "agree"`(BKT·IRT 양쪽 측정·일치 — `insufficient` 제외)이며, P 자체의 `response_count ≥ k`다(초안 k=3, **신규 수치 → 실측 보정 대상**). 즉 C 오답에서 유도된 추정이 아니라 P에서 직접 관측된 결손이어야 한다.
- ⓑ **같은 오개념이 교정을 받고도 버팀** — 이번 R3 후보 오개념의 `evidence_count ≥ 4`(사다리 `PREREQUISITE_CONCEPT` 칸 도달)이거나, 직전 결정이 같은 오개념에 대한 R3였고 이번에 다시 같은 오개념으로 오답인 경우다(EOS-24 ③의 고정 해제 조건과 같은 사실).
- **ⓐ ∧ ⓑ일 때만** R4(대상 P)로 간다. ⓐ만 있으면 P 결손이 이 오개념의 원인이라는 근거가 없고, R3 1턴은 싸다(G5). ⓑ만 있으면 어느 선수로 갈지 지목할 수 없고, R5·설명 경로가 맡는다.
- **교수학적 해석**: 반례로 불만족을 유발했는데도 오개념이 유지되고(ⓑ), 새 개념의 이해 가능성을 떠받칠 선수가 측정상 없다(ⓐ). 이때 intelligibility 실패가 최선의 설명이다. 반대 근거 R1이 정당하게 적용되는 유일한 구간이다.
- **EOS-127 분기별 처리**: `EOS-127`이 (가) 배선을 고르면, 이 예외를 **같은 PR의 착지 조건**으로 걸 것을 권고한다. 또 `AttemptEvidence`에 ⓐ의 측정 메타와 ⓑ의 `evidence_count`를 함께 싣도록 acceptance를 보강할 것을 권고한다. `EOS-127`이 (나) R4 제거를 고르면 이 예외도 소멸하고, ⓑ의 "교정 저항" 신호는 R5·조회형 선수 좌석이 받는다.
- k=3은 근거 없는 초안 수치다. 새 임계는 `RemediationPolicyTable`에 두고 실측으로 보정한다.

---

## §6. 검증

### 6-1. 실 PG 반례 3건 (`tests/backend/api/test_eos138_r3_input_scope.py`)

옛 가설은 실 탐지기로 만든다(C 오개념 오답 → `distribution-over-power` 0.9 · R3). (b)·(c)의 이번 후보는 탐지기 의존성만 주입해 만든다. 실 탐지기의 후보 신뢰는 상수(텍스트 0.9·선지 0.8)라 HTTP로는 하한 근방 후보를 만들 수 없다. 가설 갱신·상태 머신·원장은 운영 코드 그대로 돈다.

| 픽스처 | 흐름 | 결과 규칙 | 종전 코드 |
|---|---|---|---|
| (a) | 옛 가설(0.90·tse 0) → P **답안 없는 오답**(`not_run`) | **R6-wrong-undiagnosed** · target 없음 | R3(옛 가설 대상) — RED |
| (b) | 옛 가설 → P 오답, 이번 후보 `combine-unlike-terms` **0.7 정확히**(옛 가설 감쇠 후 ≈0.78 > 0.7도 공존) | **R6-wrong-undiagnosed** · target 없음 | R3(옛 가설 대상) — RED |
| (c) 대조 | 옛 가설 → P 오답, 이번 후보 **0.75**(옛 가설 ≈0.78이 더 높게 배치) | **R3-wrong-misconception** · target = `combine-unlike-terms`(이번 후보) | R3지만 target이 옛 가설 — RED |

회귀: `test_week3_gate_remediation_loop.py` 3건과 `test_eos24_recommendation_follows_learning_state.py` 6건(파라미터 포함)이 전건 통과했다. 후자의 stale 테스트는 §2 끝에 적은 대로 기대를 옮겼다. 흐름과 tse 전제는 그대로다.

### 6-2. 뮤테이션 (cp 백업 → 주입 1건·변경 단언 → 테스트 → cp 원복·sha256 동일 단언)

| # | 주입 | 판정 | 잡은 테스트 |
|---|---|---|---|
| M1 | 필터 `>` → `>=` | RED | 단위 경계 `[0.7-False]`·중복 · 실 PG (b) |
| M2 | 하한 필터 제거 | RED | 단위 경계·이동 뮤테이션 · 실 PG (b) |
| M3 | 호출부 미전달 | RED | 실 PG (a)(b)(c)·EOS-24·Week 3 (R3 자체가 사라짐) |
| M4 | `select_route` 부활 | RED | `TestNoRouteVocabulary` 2건 |
| M5 | 호출부의 "이번 후보 id" 필터 제거 | RED | 실 PG (b)(c)·stale `[scanned-no-match]` |
| M6 | 종전 입력 경로 전체(수정 전 파일 2개) | RED | 실 PG (a)(b)(c)·stale 2건 |

---

## §7. 적대적 자기 비판 — 이 판정이 실패하는 반례

- **S-A: 반례 자체가 선수를 요구하는 오개념.** 예: `sign-flip-in-inequality`의 개입은 "2 > 1 양변에 −1을 곱해 보라"이다. 정수의 곱셈 부호 규칙(선수 P)이 없는 학생에게 이 반례는 이해 불가능하다. R3 > R4면 이 학생은 무의미한 반례 1턴을 받는다. **완화**: 비용이 1턴·1문항으로 상한이고(EOS-24 ③·R5), 재발 시 §5 ⓑ가 성립한다. **남는 구멍**: ⓐ가 성립하려면 P가 *이미 측정돼 있어야* 한다. P를 한 번도 풀지 않은 학생에게는 ⓐ가 영원히 성립하지 않는다(모른다 ≠ 아니다). 이 구간에는 판정이 **답을 주지 못한다**. 후속 후보는 오개념 카탈로그 항목에 "반례가 딛는 선수 개념" 메타를 두는 안이다. 단 오개념 독립 DB·Concept Purity 원칙상 노드가 아니라 오개념 DB 쪽 속성이어야 하며, 이 판정의 범위 밖이다.
- **S-B: "오개념"이 실은 부재 개념(missing conception)인 경우.** 전개를 아예 모르는 학생이 `(a+b)² = a²+b²` 같은 표면형을 내면, 스캔은 `distribution-over-power`를 0.7 초과로 매치할 수 있다. 그러나 이 학생에게는 교정할 "틀린 믿음"이 없고, 필요한 것은 선수(분배법칙) 학습이다. 신뢰 하한 0.7은 *매치 품질*을 잴 뿐 *원인 유형*(오개념 vs 결손)을 재지 않는다. **완화**: 반례 유도는 부재 개념 학생에게도 "같지 않다"는 사실을 전달하며 해를 주지 않는다. 다음 오답에서는 ⓑ로 넘어간다. **반증 조건**: 라이브 실측에서 R3 발화 직후 같은 개념 재오답률이 R6(원인 미상) 직후보다 **높게** 나오면 이 판정의 G4·G5 전제가 틀린 것이다. **반증 계측은 후속 태스크 `EOS-31-r3-vs-r6-reerror-falsification`로 이관한다** — 작동 비율 원칙에 따라, R3 발화 후 교정 확인 문항 정답률을 R6 기준선과 비교한다(판정은 Wilson 단측 경계로).

---

## §8. 이 판정이 하지 않은 것

- §5 R4a 예외는 구현하지 않았다(`EOS-127`로 이관).
- §7 S-B 반증 계측은 구현하지 않았다(후속 태스크 `EOS-31-r3-vs-r6-reerror-falsification`로 이관).
- EOS-24 안전장치 ①②의 로직은 무변경이다(§2).
- "BKT 신뢰도 0.17"은 EOS-24 §4의 인용이다. `l2/*.py`에서 `0.17`·`reliability`로는 해당 산출 코드를 찾지 못했다(내가 찾은 방법으로 0건 — 독립 비판의 계산값으로 보인다). ③의 결론은 이 수치가 아니라 G2·G3(원인 미상 신호라는 구조적 사실)에 더 무게를 둔다.
