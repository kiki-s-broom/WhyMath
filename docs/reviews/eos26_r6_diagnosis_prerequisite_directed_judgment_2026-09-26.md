# EOS-26 정책 설계 판정 — 원인 미상 오답(R6) 직후 진단을 선수 개념으로 향하게

> **판정 기준: main `bd87b30d`** (2026-09-26 · `G-kg02 게이트 전제 재점검 — 보류+대장 정정(Kiki 판정) · CONT-05 등재 · HARN-170 재발 기록 (#1332)`)
> **소유 태스크**: `EOS-26-r6-diagnosis-prerequisite-directed` (acceptance ③ "설계 판정 선행")
> **독립 비판**: pedagogy-designer 서브에이전트 1회(적대적 비판) — 반영 내역은 §5
> **이 문서의 위치**: 구현보다 **먼저** 쓰였다. §9(검증)만 구현 뒤에 채운다.

---

## §0. 결론

**R6를 집행한다 — 연속 오답의 첫 R6는 직접 선수 1문항을 탐침하고, 연속 두 번째 R6는 상태 머신 문면(같은 개념 연습)대로 간다.**

- **첫 R6**(직전 정책 결정이 R6가 아님): 후보를 오답 개념 C의 **직접 선수 중 아직 숙달되지 않은(미측정 포함) 개념**의 문항으로 **제한**한다. 선택 연산(가중 축·선택기·EOS-124 의도 해소·이름표)은 기본 경로 그대로다 — 달라지는 것은 후보 집합뿐이다. Kiki 기준 ⓐ가 여기서 구조적으로 선다.
- **연속 두 번째 R6**(직전 정책 결정도 R6): 방금 틀린 개념 X로 제한한다 — R6 결정(`PRACTICE_SAME_CONCEPT`)의 문면 그대로다. 탐침 문항을 틀린 경우 X는 선수 P이고, EOS-124 (나)가 `practice_prerequisite`(근거 = 막힌 C · 목표 = P)를 붙인다. Kiki 기준 ⓑ가 여기서 구조적으로 선다.
- **셋째 연속 오답은 R5**(임계 3)라 이 경로를 타지 않는다. 그래서 R6 개입은 **구조적으로 최대 2문항**이다(안전장치를 따로 두지 않아도 상태 머신 규칙 순서가 끊는다).
- 첫 R6인데 탐침할 선수가 없으면(엣지 없음 · 전부 숙달 · 출제 가능 문항 없음 · 그래프 시간 초과) 역시 같은 개념 연습으로 간다 — R6 문면이다. 같은 개념에도 문항이 없을 때만 기본 경로로 돌아간다.
- **R2(정답+미측정 확신)는 집행하지 않는다**(ⓓ). 판독 함수가 R6 트리거를 요구하므로 R2의 PRACTICING은 지시가 아니다.
- 이 판정은 **ⓐ만이 아니라 ⓑ도 새로 세운다.** §1-2의 실측이 ⓑ 역시 픽스처·요청 형태에 기대고 있었음을 보였기 때문이다.

---

## §1. 실측 사실 (acceptance ①)

> 실행 환경: 컨테이너 · PostgreSQL 16.13 + pgvector · `alembic upgrade head` EXIT=0 · Python 3.12 venv(`pip install -e ".[dev]"` EXIT=0)

### 1-1. 기준선 — 태스크 문면 재현

main `bd87b30d` 그대로 `test_e2e_three_consecutive_loops.py` + `test_eos24_recommendation_follows_learning_state.py`를 실 PG로 돌렸다 — **41 passed · 1 xfailed · EXIT=0**. 프로브 판정은 태스크 문면과 같다.

> 「실측」 `DIAGNOSIS_PROBE :: 폐루프=PASS 선수지향=FAIL` · 선수 지향 프로브의 첫 추천 = `문항소속=side · action=diagnose · reason=unmeasured · target=side` · `THREE_LOOP_VERDICT[general] :: LOOP1=FAIL LOOP2=PASS LOOP3=PASS`

원인도 문면과 같다: 기본 경로의 1차 선택(`l2/next_problem_selection.py::candidate_pool_order_by` θ 근방 정렬 + 정보량 최대)은 선수 그래프를 보지 않는다. 오답 1회 뒤 θ는 하한 -4.0이고, 가장 쉬운 문항이 선수가 아닌 개념에 있으면 진단은 그쪽으로 간다.

### 1-2. 새 사실 — 기준 ⓑ도 구조적이지 않았다

EOS-139가 잰 폐루프(ⓑ)는 방해 개념 **없는** 배치에서, 하네스 기본 요청(`prioritize_weak_concepts=true`)으로만 쟀다. 스크래치 프로브(커밋하지 않음)로 방해 개념 배치에서 학습자가 **선수 문항을 틀린** 뒤의 추천을 두 요청 형태로 쟀다.

| 요청 형태 | 선수 문항 오답 뒤 추천 | ⓑ |
|---|---|---|
| `prioritize_weak_concepts=true` (3루프 하네스 기본값) | `pre · practice_prerequisite · served` | 성립 |
| 파라미터 미전송 (**실제 모바일 앱**) | `side · diagnose · direct` | **붕괴** |

첫 줄이 성립한 이유는 약점 가중이다 — 방금 틀린 선수(숙달 0.15)의 문항이 가중 1.85배를 받아 방해 개념(가중 1.0)의 정보량 우위를 이겼다. 둘째 줄은 가중이 없어 다시 가장 쉬운 문항(방해 개념)으로 간다.

**실제 앱은 둘째 줄이다.** `src/mobile/lib/features/problems/data/problems_api.dart::getNextProblem`의 `prioritizeWeakConcepts` 기본값이 `false`이고, 유일한 호출부 `problem_screen.dart`는 `load()`를 인자 없이 부른다(이 검색 방법 기준). 즉 EOS-139의 "폐루프 True"는 **방해 개념 부재 + 하네스 전용 요청 형태**라는 두 우연 위에 서 있었다. 사고 대장 `nondiscriminating-check` 부류의 재발이다(§7-3). 이 태스크가 ⓐ만 고치고 프로브의 ⓖ만 True로 올렸다면 `general` Loop 1 `보정`은 거짓 해소가 됐을 것이다.

### 1-3. 태스크 notes의 부수 관측은 현재 main에서 재현되지 않는다

notes는 "무관 개념 진단 문항까지 틀리면 `practice_prerequisite · prerequisite_gap · target=무관 개념`"을 적었다(main `81070ed5` 시점). 지금은 다르다.

> 「실측」 방해 개념 진단을 그대로 따라 틀린 뒤의 추천 = `side · practice_current · current_concept · intent unsupported` (두 요청 형태 동일)

EOS-124(#1317 · `cat_v2`)가 착지하며 선수 구간 의도가 그래프 근거를 요구하게 됐기 때문이다 — 무관 개념은 선수·후행 엣지가 없어 (다) 정직 강등으로 내려간다. 그래서 ③ⓐ의 폴백에서 "이름표가 거짓말을 하는" 경우는 지금 이 경로에 없다. `practice_prerequisite`는 EOS-124 (가)·(나)의 그래프 근거가 있을 때만 나온다.

### 1-4. 연속 판정은 국면으로 할 수 없다 — EOS-24 안전장치 ③ 모양이 옮겨 오지 않는다

EOS-24는 교정 고정을 "교정 국면(`REMEDIATING`)에서 제출한 응답이 다시 R3면 해제"로 풀었다(`LearningStateSnapshot.assessed_from`). R6에 같은 모양을 쓰면 "`PRACTICING`에서 제출한 R6"가 되는데, `PRACTICING`은 **R2의 도착 국면이기도 하다**. 그리고 모바일 앱은 확신도를 보내지 않는다(`src/mobile/lib/features/problems/data/*.dart`에서 `confidence` 0건) — 확신도 미보고 정답은 전부 R2다(`_is_high_confidence` · 미측정 = 낮음). 그러면 **정답 뒤의 모든 오답이 "연속 R6"로 읽혀** 첫 R6 탐침이 사실상 첫 응답에서만 돈다. 연속 판정은 국면이 아니라 **직전 정책 결정의 트리거**로 해야 한다.

### 1-5. `consecutive_failures`는 개념을 가리지 않는다

`V1_RULES` R5 설명은 "같은 개념에서 연속 오답"이라고 적지만 `l2/learning_state_evidence.py::_count_consecutive_failures`는 학생의 최근 응답을 개념과 무관하게 센다. 그래서 C 오답 → 선수 P 오답 → 셋째 오답이면 셋째에서 R5가 발화한다. §0의 "구조적으로 최대 2문항"은 이 사실에 선다. (설명 문구와 구현의 불일치 자체는 이 태스크 범위 밖이다 — §7-3.)

---

## §2. 판정 — R6를 어떻게 집행하는가 (acceptance ②)

### 2-1. 판정 트리

| 조건 | 후보 제한 | `learning_state_directive` | 이름표(기본 경로 연산) |
|---|---|---|---|
| 첫 R6 · C의 직접 선수 중 미숙달 개념에 출제 가능 문항 있음 | 그 선수들의 문항 | `prerequisite_probe` | 미측정 P → `diagnose · unmeasured` / 막힌 P → `practice_prerequisite`(EOS-124 (가)·(나)) / 학습 구간 P → `practice_current` |
| 연속 두 번째 R6(직전 정책 결정 = R6) | 방금 틀린 개념 X | `same_concept_repeat` | X가 막힌 C의 선수 → `practice_prerequisite`(근거 C · 목표 X) / 그 외 → EOS-124 해소 그대로 |
| 첫 R6 · C에 선수 엣지 없음 | C | `same_concept_probe_unsupported` | EOS-124 해소(대개 `practice_current · unsupported`) |
| 첫 R6 · C의 직접 선수가 전부 숙달(> 0.7) | C | `same_concept_probe_refuted` | 〃 |
| 첫 R6 · 미숙달 선수는 있으나 출제 가능 문항 없음 | C | `same_concept_probe_unavailable` | 〃 |
| 첫 R6 · 선수 조회 시간 예산 초과 | C | `same_concept_graph_timeout` | 〃 |
| 결정 응답·문항·대표 개념 미해소 | (제한 없음) | `anchor_unresolved` | 기본 경로 |
| 같은 개념 제한인데 그 개념에 미시도 문항 없음 | (제한 없음) | `no_candidate_in_concept` | 기본 경로 |

### 2-2. 채택 근거

1. **R6의 결정은 "같은 개념 연습"이고, Kiki가 인정한 것은 그 앞의 선수 탐침 1문항이다.** EOS-24 판정의 원칙은 "추천은 상태 머신을 다시 판정하지 않고 집행한다"였다. 그러니 R6를 집행한다는 것은 기본적으로 같은 개념 연습이다. Kiki 결정 (가)는 그 앞에 한 걸음을 인정했다 — 원인을 모르는 오답이면 가장 가까운 구조적 원인(선수 결손)을 먼저 확인한다. 이 판정은 그 한 걸음을 **연속 오답의 첫 R6에만** 둔다. 두 번째부터는 문면으로 돌아간다.
2. **ⓑ를 문면 집행이 세운다.** 탐침을 틀리면 학생은 두 번째 R6에 있고, 방금 틀린 개념은 선수 P다. R6 문면대로 P로 제한하면, P가 막힌 C의 직접 선수라는 사실을 EOS-124 (나)가 이미 알아본다 — `practice_prerequisite`(근거 = C · 목표 = P). 새 규칙을 만들지 않고 기존 두 좌석(상태 머신 문면 · EOS-124 의도 해소)의 합성으로 ⓑ가 선다. §1-2의 붕괴는 1차 선택이 P를 앵커로 잡지 못해서 생겼으므로, 앵커를 P로 고정하면 방해 개념·요청 형태와 무관해진다.
3. **새 근거 종류(ReasonType)를 만들지 않는다 — 후보 제한만 한다.** EOS-24는 `misconception_remediation`을 신설했다. 숙달 파생 근거가 전달 문항에 대해 **거짓**이 되기 때문이었다(C의 숙달 구간은 선수 하강을 말하는데 전달 문항은 C의 교정 확인이다). R6 경로에서는 전달 문항의 숙달 파생 이름표가 **참**이다 — 미측정 P를 진단하러 P 문항을 내면 `diagnose · unmeasured`가 사실이고, 막힌 C의 선수 P를 연습시키면 `practice_prerequisite`가 사실이다. 상태 머신이 한 일은 *후보 생성*이며, 그것은 `learning_state_directive`와 `policy_version`이 기록한다(EOS-124가 재선택을 `reason.type`이 아니라 `intent_resolution`에 기록한 것과 같은 자리 배분). 규칙으로 적는다: **상태 머신 근거 종류는 숙달 파생 근거가 전달 문항에 대해 거짓이 될 때만 신설한다.** 부수 효과로 행위 어휘가 그대로라 Kiki 결정 문면("`diagnose`를 보정으로 인정")과 3루프 하네스의 판정(`action == "diagnose"`)이 바뀌지 않는다.
4. **판정 위치는 `route_by_learning_state` 하나다**(acceptance ④). EOS-24 R3 집행과 같은 이음매에서 지시를 읽고 후보를 제한한다. 정책(`CatRecommendationPolicy`)은 제한된 후보로 같은 선택을 할 뿐이다.

### 2-3. 이 판정이 만드는 비대칭(정직 표기)

첫 R6에서 추천의 행위(`diagnose` P)는 상태 머신의 `next_action`(`PRACTICE_SAME_CONCEPT`)과 여전히 다르다. 게이트 `G-eos24-loop1-undiagnosed-wrong-criterion`의 evidence가 적은 "남는 부채"(API 수준에서 둘이 다른 말을 한다)는 이 판정으로 **줄어들 뿐 사라지지 않는다** — 연속 두 번째와 탐침 불가 폴백에서는 둘이 같은 말을 하고, 첫 R6 탐침에서만 다르다. 결정자가 둘인 상태(EOS-24 판정문 §2 근거 1이 경계한 형태)가 이 한 경우에 남는다. 탐침 규칙을 상태 머신(`V1_RULES`)으로 올릴지는 별도 판정이며 후속 태스크로 등재한다(§7-2). 그 부채는 게이트 evidence가 "후속 태스크로 등재한다"고 적었으나 대장에 없었다(`grep PRACTICE_SAME_CONCEPT backlog/tasks` → EOS-139 1건 · 이 검색 방법 기준).

---

## §3. 설계 판정 ⓐ~ⓖ (acceptance ③)

### ⓐ 폴백 — 선수가 없거나 선수에 미시도 문항이 없을 때

**같은 개념 연습(R6 문면)으로 간다. 기본 경로로 가지 않는다.** 기본 경로는 θ 근방 최근접이라 오답 직후 무관한 가장 쉬운 문항으로 간다 — 그것이 바로 이 태스크가 고치는 결함이다. 탐침할 선수가 없다는 것은 원인 후보가 C 안에 있다는 뜻이거나(선수가 전부 숙달 — 반증), 우리 쪽 공백이다(엣지 없음 · 문항 없음 · 시간 초과). 어느 쪽이든 C를 이어 연습하는 것이 상태 머신이 말한 그대로다.

사유를 넷으로 나누는 이유는 EOS-124 `IntentResolution`과 같다(모른다 ≠ 아니다): `refuted`는 정상 교수학, `unsupported`는 그래프 커버리지 공백, `unavailable`은 콘텐츠 공백, `graph_timeout`은 성능이다. 고칠 곳이 다르다.

같은 개념에도 미시도 문항이 없을 때만 기본 경로로 돌아가고 `no_candidate_in_concept`을 남긴다(EOS-24와 같은 값 재사용 — 뜻이 같다).

**이름표**: 폴백의 이름표는 EOS-124 의도 해소가 붙인다. 오답 1회 뒤 C의 숙달은 대개 0.15(선수 구간)라 `_prerequisite_intent`가 돈다 — (가) C의 측정된 약한 선수가 있으면 거기로 재선택(이 경우는 `refuted`/`unavailable` 폴백에서만 가능), (나) C가 막힌 후행의 직접 선수면 근거를 그 후행으로, (다) 아니면 `practice_current`로 정직 강등. §1-3의 실측대로 무관 개념에 `practice_prerequisite`가 붙는 일은 없다.

### ⓑ 선수가 여럿일 때 — 직접 선수 · 미숙달만 · 그 안은 CAT이 고른다

- **직접 선수(depth 1)만 탐침한다.** 이유 셋: ① 원인 후보로 가장 가까운 것은 직접 선수다. ② `fetch_prerequisites`의 depth 2 행은 **경로를 싣지 않는다** — 숙달된 직접 선수 뒤에 있는 depth 2 선수(그 직접 선수가 이미 덮는 기초)와 약한 직접 선수 뒤에 있는 것을 구별할 수 없다. 구별 못 하는 것을 탐침 대상에 넣으면 숙달된 기초를 진단하는 문항이 나간다. ③ 더 깊은 하강은 측정이 이끈다 — 탐침을 틀리면 두 번째 R6에서 P가 앵커가 되고, P의 측정된 약한 선수가 있으면 EOS-124 (가)가 거기로 내려간다.
- **숙달된 선수(> 0.7)는 뺀다.** 원인 후보가 아니다(EOS-124 (가)의 "숙달 선수는 목표가 아니다"와 같은 선 · 같은 상수 `WEAK_CONCEPT_MASTERY_CEILING`). 판정은 `learner_state.mastery`(개념코드 키)로 한다 — EOS-124 (가)와 같은 입력이다.
- **미측정 선수와 약한 선수를 모두 넣고, 그 안의 선택은 기본 CAT 선택 연산에 맡긴다**(정보량 × 요청의 가중 축). 약한 선수를 따로 우선하지 않는 이유: 두 경우의 이름표가 다를 뿐(`diagnose` vs `practice_prerequisite`) 둘 다 원인을 좁히는 행위이고, 약점 우선이 필요한 요청은 이미 `prioritize_weak_concepts`로 그 가중을 켤 수 있다. 우선순위 규칙을 하나 더 만들면 "선택 연산은 1차 선택과 같다"(EOS-124 재선택 원칙)가 깨진다.
- 합친 후보는 기본 후보 풀과 같은 키(|b−θ| 오름차순 → `problem_id`)로 정렬한다. 선택기(`select_weighted_item`)가 동률에서 낮은 인덱스를 고르므로, 같은 키여야 동률 처리가 기본 경로와 같아진다.

### ⓒ 고정 범위 — 탐침 1문항, 문면 연습 1문항, 그다음은 R5

- **탐침은 1문항이다.** 연속 오답의 첫 R6에서만 나간다.
- **문면 연습(연속 두 번째)도 1문항이다.** 셋째 연속 오답은 R5(`REPEATED_FAILURE_THRESHOLD = 3`)라 R6가 아니다 — R5는 집행하지 않으므로(EOS-24 판정문 §3) 기본 경로로 돌아간다. 이 경계는 상태 머신 규칙 순서(R5가 R6보다 앞선다)가 이미 보장하므로 추천 쪽에 별도 카운터를 두지 않는다.
- **연속 판정 = 직전 정책 결정의 트리거가 R6인가.** §1-4대로 국면(`assessed_from`)으로는 R2와 R6를 가를 수 없다. 원장에서 "결정 응답이 아닌 응답의 가장 늦은 정책 결정"의 트리거를 1건 읽는다(R6 경로에서만 · 조회 1건). 직전이 R3(교정 문항을 원인 미상으로 또 틀림)면 연속 R6가 아니므로 탐침한다 — 교정이 원인을 못 짚었으니 선수를 확인하는 것이 맞다.
- **"연속"은 상태 머신의 정의를 따른다**(시간 무관 — §8). 어제 R6로 끝나고 오늘 첫 응답이 R6면 두 번째로 읽힌다. `consecutive_failures`도 같은 두 응답을 연속으로 센다(§1-5) — 추천이 상태 머신과 다른 연속 개념을 만들지 않는다.

### ⓓ R2는 집행하지 않는다

판독 함수는 `state is PRACTICING` **이고** `trigger is POLICY_PRACTICE_UNDIAGNOSED`일 때만 지시를 낸다. 국면만 보면 R2의 PRACTICING을 오독하고(확신도 미보고 학생의 모든 정답이 지시가 된다 — EOS-24 판정문 §3), 트리거만 보면 R6 뒤에 생애주기 전이가 끼어도 지시가 살아 있는 것처럼 읽힌다(EOS-24 `read_remediation_directive`와 같은 이유). R2면 지시가 아니므로 조회 0건이다.

### ⓔ R3 경로(EOS-24)와의 합성

- **요청마다 지시는 하나다.** 판독은 원장 최신 결정 하나를 본다 — R3면 `REMEDIATING`, R6면 `PRACTICING`이라 동시에 성립하지 않는다. R3를 먼저 읽는다(기존 순서 유지).
- **R3 → R6**(오개념 교정 문항을 매칭 없이 또 틀림): 직전 결정이 R3이므로 연속 R6가 아니다 → 탐침. 교정이 원인을 짚지 못했다는 신호이므로 선수 확인이 맞다.
- **R6 → R3**(탐침 문항을 오개념 매칭으로 틀림): 최신 결정이 R3 → EOS-24 경로(안전장치 ①② — 이번 회차 가설 · 신뢰 하한). 교정 대상은 탐침 문항의 개념 P다.
- **R3 경로는 한 줄도 바뀌지 않는다.** 이름표(`misconception_remediation`) · 학습 밴드 · `cat_v1_state_remediation` · EOS-124 해소 생략이 그대로다. R6 경로는 반대로 EOS-124 해소를 **돌린다**(이름표가 숙달 파생이므로).

### ⓕ 그래프 예산 — depth ≤ 2 · nodes ≤ 20 · timeout

- **읽는 것은 앵커 1개의 직접 선수뿐이다**(`fetch_prerequisites(C, max_depth=1)`). 전체 그래프 읽기는 없다.
- **예산은 정책이 소유한다.** `route_by_learning_state`는 예산을 건 읽기 함수를 **주입받는다**(정책이 `_within_budget` 시간 예산 + `_apply_node_budget` visited·노드 20 상한을 걸어 넘긴다). 이 모듈이 예산을 다시 정의하면 예산 정의가 두 곳이 된다 — 천장 상수(`_DEPTH_CEILING`·`_NODES_CEILING`)와 그 뮤테이션 하네스(`scripts/analysis/mutate_recommendation_policy_guards.py`)는 `recommendation_policy.py`를 가리킨다. 순환 import(정책 → 이 모듈 → 정책)도 이 주입으로 피한다.
- **시간 초과는 추천을 실패시키지 않는다** — 같은 개념 연습으로 내려가고(`same_concept_graph_timeout`) 예외 타입명을 로그에 남긴다(침묵 실패 금지).
- depth 1은 천장 2 안이다. 탐침이 depth 2를 쓰지 않는 이유는 예산이 아니라 교수학이다(ⓑ).

### ⓖ 작동 비율 기록

- `StateDirectiveOutcome`에 6값을 더한다: `prerequisite_probe` · `same_concept_repeat` · `same_concept_probe_unsupported` · `same_concept_probe_refuted` · `same_concept_probe_unavailable` · `same_concept_graph_timeout`. 미해소·후보 0은 기존 `anchor_unresolved`·`no_candidate_in_concept`을 쓴다.
- 이 값은 기존 응답 필드(`GET /v1/me/next-problem`의 `learning_state_directive`)와 처치 기록 meta 키에 그대로 실린다 — 저장 좌석 신설 0.
- 후보 제한으로 나간 추천은 `policy_version=cat_v2_state_undiagnosed`로 적는다(후보 생성 규칙이 다르다 — REC-11 소급 평가가 섞지 않게). `v2`는 이름표·재선택을 `cat_v2`(EOS-124) 규칙으로 붙인다는 뜻이다. 제한하지 못한 R6(`anchor_unresolved`·`no_candidate_in_concept`)는 기본 경로와 같은 입력·같은 결과라 `cat_v2`를 유지한다.
- 작동 비율: `learning_state_directive`가 R6 값인 행 중 `prerequisite_probe` 비율이 "탐침이 실제로 나간 비율"이고, `same_concept_probe_*`가 그렇지 못한 이유의 분포다.

### 부가 안전장치 — R6 경로에서는 전진하지 않는다

R6 경로의 앵커가 전진 구간(> 0.7)이면 EOS-124 전진 재선택을 돌리지 않고 앵커 개념 연습으로 강등한다(해소값 `refuted`). 상태 머신이 방금 그 앵커 개념(같은 개념 연습일 때)에서 오답을 관측했다 — 그 관측이 "숙달 · 다음으로"를 반증한다. 오답 1회로 숙달이 0.7 아래로 안 떨어지는 학생(사전 숙달이 높음)에게서 실제로 생긴다(BKT 갱신에서 사전 0.95 → 오답 후 약 0.73). 탐침 경로에서는 숙달 선수를 후보에서 빼므로 정상 입력으로는 닿지 않지만, `learner_state.mastery`와 최신 숙달 이력이 어긋나는 경우(EOS-124가 로그로 드러내는 그 불일치)를 막는다.

---

## §4. 선택 축 — 제한은 WHERE를 덧붙일 뿐이다

- **탐침 후보**: `load_target_candidate_rows`(EOS-124 신설 — 노출 게이트 3축 · PRIMARY 매핑 · 미응답 · 형제 배제 · 개념별 θ 근방 상한)를 그대로 쓴다. 게이트를 다시 쓰지 않는다(REC-06 "한 곳에서만 정의").
- **같은 개념 후보**: EOS-24의 `build_concept_candidate_pool_stmt`(기본 후보 SELECT + PRIMARY = X)를 그대로 쓴다.
- **요청의 `purpose`를 유지한다.** EOS-24 R3가 학습 밴드를 강제한 이유는 교정 확인 문항이 측정이 아니었기 때문이다. 탐침은 **측정 자체**라 정보량 최대(요청 기본 `diagnosis`)가 맞다. 같은 개념 연습도 요청 목적을 따른다(제한된 한 개념 안에서 θ -4.0이면 어느 쪽이든 가장 쉬운 문항이다).
- **정렬 계약은 그대로 강제된다.** 전달 문항 = 제한 후보 중 하나, 이름표 = 그 문항의 개념에서 EOS-124가 해소 → `check_intent_alignment`가 `NextProblemOutcome` 생성 시점에 검증한다(R2 target = 전달 개념 · R3 관계 행위면 앵커 ≠ 목표 · R4 비관계면 목표 = 앵커).

---

## §5. 독립 비판 반영

(비판 결과 반영 후 채운다.)

---

## §6. 해소 신호와 하네스 강화 (acceptance ⑤)

- **프로브를 강화한다.** EOS-139 프로브의 폐루프는 방해 개념 없이, 하네스 기본 요청으로만 쟀다(§1-2). 이 태스크 뒤의 프로브는 **방해 개념 배치에서, 두 요청 형태(`prioritize_weak_concepts` true · 미전송)로** 원인 미상 오답 → 첫 추천(ⓖ 선수 지향) → 그 추천도 틀림 → 다음 추천(ⓕ 폐루프)을 잰다. 두 형태 모두 성립해야 True다.
- 변경 전 코드에서 강화된 프로브는 ⓖ·ⓕ 둘 다 False를 낸다(ⓕ의 전제인 "첫 추천이 선수 진단"부터 끊긴다). 변경 뒤 둘 다 True면 `_FROZEN_PROBE`와 `general` Loop 1 `보정` 동결이 해소 신호를 내고, 둘을 True로 승격한다. 그러면 §18 xfail 대상이 공집합이 된다(`_s18_open_variants` 유도).
- **EOS-24 대조군 `test_undiagnosed_wrong_answer_is_not_directed`를 승격한다.** 그 배치(C · 선수 엣지 없는 더 쉬운 P)에서 R6는 이제 지시가 **있고**(`same_concept_probe_unsupported`) 추천은 C 안에 머문다. 이 대조군이 R3 테스트의 변별력("C 안 = 상태 경로 때문")을 대던 역할은 R3 테스트 자신의 근거·지시 단언과 뮤테이션(개념 제한 제거)이 이어받는다.
- 새 통합 테스트(실 PG · HTTP): 선수 탐침(방해 개념 있음) · 탐침 오답 뒤 `practice_prerequisite` 하강(두 요청 형태) · 선수 없음 폴백 · R2 비지시 · R3→R6 합성.

---

## §7. 인접 태스크 경계와 후속

### 7-1. 인접 태스크

| 태스크 | 축 | 관계 |
|---|---|---|
| `EOS-124` (done) | 추천 내부 정렬(정책 축 ↔ 선택 축) | 겹치지 않는다. R6 경로는 EOS-124 해소를 **재사용**한다 — 바꾸는 것은 후보 집합과 R6 경로 안의 전진 금지 가드뿐이다 |
| `EOS-24` (done) | 상태 머신 출력 → 추천 입력(R3) | 같은 이음매에 R6를 더한다. R3 경로 무변경 |
| `EOS-138` | R3 입력 품질 | 겹치지 않는다. R6 판독은 오개념 가설을 읽지 않는다 |
| `EOS-127` | R4 입력 미배선 | R4가 배선되면 선수 결손을 상태 머신이 직접 결정한다 — 그때 R4 집행과 이 탐침의 관계(탐침이 R4를 대신하던 몫)를 다시 판정한다 |
| `EOS-25` | 수능 정책 정렬 | 수능 정책은 상태 머신을 읽지 않는다 — R6 탐침도 기본 CAT에만 선다 |

### 7-2. 후속 태스크로 등재하는 것

- **R6 `next_action` ↔ 추천 행위 불일치의 잔여분**(§2-3): 첫 R6 탐침에서 둘이 다른 말을 한다. 탐침을 상태 머신 규칙으로 올릴지(예: 첫 원인 미상 오답이면 `next_action`이 선수 진단을 말하게) 판정한다. 게이트 evidence가 약속했으나 대장에 없던 부채다.
- **3루프 하네스 본 관통의 요청 형태**: 본 관통은 여전히 `prioritize_weak_concepts=true`만 쓴다(§1-2). R6 프로브는 이 태스크가 두 형태로 강화하지만, 본 관통 전체(Loop 2 숙달 상승·Loop 3 전진)가 실제 앱 요청 형태에서도 서는지는 재지 않았다.

### 7-3. 사고 기록

- `nondiscriminating-check` 부류 재발(§1-2): EOS-139의 폐루프 True가 방해 개념 부재 + 하네스 전용 요청 형태에 기댔다. 대책은 코드(강화된 프로브 — 두 요청 형태 × 방해 개념)와 태스크(§7-2 본 관통 요청 형태). MEMORY 결정 로그와 사고 대장에 기록한다.
- R5 규칙 설명("같은 개념에서")과 `_count_consecutive_failures`(개념 무관)의 불일치(§1-5)는 이 태스크가 고치지 않는다 — 어느 쪽이 의도인지는 상태 머신 소유 판정이다. 후속 태스크로 등재한다.

---

## §8. 이 판정이 하지 않은 것

- **상태 머신은 한 줄도 바꾸지 않는다**(`V1_RULES` · R6 `next_action`). §7-2의 후속이 판정한다.
- **depth 2 탐침은 하지 않는다**(ⓑ).
- **탐침 문항을 "원인을 변별하는 문항"으로 좁히지 않는다.** 지금은 선수 개념의 문항이면 된다(EOS-24 §7-3과 같은 한계).
- **"연속"의 시간 창을 두지 않는다**(ⓒ). 상태 머신의 연속 정의와 다르게 만들면 두 좌석이 다른 연속을 말한다.
- **수능 정책**(§7-1).
- **실데이터의 폴백 빈도는 재지 않았다.** 컨테이너 DB는 마이그레이션만 적용한 빈 DB다. 원자 백본(2,683노드 · 2,210엣지)에서 선수가 있는 개념의 비율과 그 선수에 승인 문항이 있는 비율은 운영 DB의 `learning_state_directive` 분포가 말해 줄 것이다(ⓖ).

---

## §9. 검증

(구현 뒤에 채운다.)
