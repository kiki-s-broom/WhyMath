# 계획서 300 「Phase 2 — EOS Closed Learning Loop」 ↔ 빌드 하네스 백로그 변환 대조표

> **판정 기준: main `2e1220b4`** (2026-09-16) · 백로그 655건(미완 208) · 원 문서 = Kiki 제공 외부 `.docx`
> `300_Phase 2 — EOS Closed Learning Loop 실행계획`(2026-09-28~10-25 · §1~§22 · 본문 전량 확보)
>
> **태스크**: `EOS-09-plan300-phase2-backlog-conversion`
> **성격**: 대장 변환 + 대조 기록. **실행 승인이 아니다**(§0-2 참조).
>
> **판정 후 재확인(2026-09-16)**: 작성 중 main이 `2e1220b4` → `259b802f`로 1커밋 전진했다(ARCH-46 · 라우터 좌석 계약 게이트). 그 커밋의 변경 파일에 본 문서의 판정 축(`l2/**`·`api/**`·learner_state·recommend·mastery·assessment)이 **0건** 포함돼 있어 아래 판정은 그대로 유효하다. 기준 해시는 판정 시점의 것을 유지한다.

---

## §0. 먼저 읽을 것 — 이 변환의 지위

### 0-1. 이 문서가 하는 일

계획서 300의 §22 우선순위 20건과 §1·§13·§16·§17·§19의 횡단 요구를 **착수 단위로 분해하고**, 각 단위를 기존 655건과 대조해 ①이미 있는가 ②일부만 있는가 ③정말 없는가를 판정한다. 없는 것만 등재한다.

### 0-2. 이 변환은 실행 지시가 아니다 (가장 중요)

선언 정본 `docs/strategy/eos_transition_declaration_2026-08-30.md` §1.3이 **2026-09-03 Kiki 결정**을 이미 정본화했다 (MEMORY 결정 로그 `2026-09-03 (Kiki 결정·계획서 300 대조)`):

> 계획서 300의 4주 Phase 2는 **실행하지 않고 참고 문서로 강등**한다. 폐쇄루프는 독립 목표가 아니라 **콘텐츠 생산성·학습 효과를 재는 기반 계측기**이며, 10월의 공식 목표는 **G2 앵커 콘텐츠 생산**으로 유지한다. 단 CL-WIRING 2건은 G2·G4 공통 선결조건이므로 수일 규모로 즉시 수행한다. 8상태 학습 상태 머신 신설은 **보류**(재확인 지점 = G4 12/13).

그때의 변환 결과가 3건이었고, 현재 상태는:

| 태스크 | status | eos_priority |
|---|---|---|
| `MOB-20-cl-wiring-attempt-submission` | **done** | P0 |
| `EOS-81-cl-wiring-closed-loop-e2e` | **done** | P0 |
| `HARN-61-p0-swap-exemption-clause` | todo | P2 |

**본 문서는 그 결정을 뒤집지 않는다.** 09-03 대조는 Gate 2 조건·API·경계 축에 집중했고 §22 20건의 전건 분해는 하지 않았으므로, 본 문서는 그 **잔여를 더 높은 해상도로 기록**한다. 여기 등재된 태스크의 *착수*는 09-03 결정의 갱신을 전제로 한다 — 등재는 대장에 올리는 것이고 착수는 별개다.

### 0-3. 원 문서 §3에 `P-01~P-16` 목록은 없다 (실측 정정)

> **사후 보강(§11)**: 그 목록은 원 문서가 아니라 **다른 세션이 만든 집행 지시문 세트**(`docs/ops/phase2_eos_closed_loop_execution_prompts.md` · PR #1176 · **미머지**)에 있다. 본 변환은 그 세트의 `P-00a`가 지목한 후속 작업이며, 16종과의 교차 검증과 그 세트가 빠뜨린 2축은 **§11**에 있다.

이 변환을 지시한 프롬프트는 "§3 목록(P-01~P-16)을 기준 분해안으로 삼되 그대로 믿지 말고 대조하라"고 했다. **대조 결과 그 목록은 존재하지 않는다.** 원 문서 §3은 「Phase 2의 핵심 상태 머신」(8상태 전이)이다. 항목 목록의 실체는 **§22 우선순위 20건**(P0 7 · P1 5 · P2 3 · P3 5)이며, 프롬프트 3번이 "우선순위는 §22를 그대로 옮기라"고 지목한 바로 그 절이다. 따라서 §22를 분해 기준으로 삼고, §22가 덮지 않는 축(§1 계약 · §13 경계 · §16 시나리오 · §17 Event Trace · §19 KPI · §12 API · §18 Gate · §20 PR 규약 · §11 페르소나)을 추가했다.

---

## §1. 방법

- 판정 근거는 **실파일 경로·명령 출력·태스크 ID** 중 하나여야 한다. 문서 언급만으로 "충족"한 행은 없다.
- **"식별자 부재 ≠ 기능 부재"**(CLAUDE.md) 준수 — 계획서가 쓴 이름으로 0건인 항목은 **역할로 재검색**하고 **소비자(호출측)를 역추적**한 뒤 판정했다. 재검색으로도 0인 것만 갭이다.
- **"trunk 부재 ≠ 미구현"** 준수 — 클론이 shallow였으므로 `git fetch --unshallow origin`(EXIT=0 · 1,148 커밋 복원) 후 `git log --all --grep=<ID>`로 미머지 구현을 확인했다.
- **판정 시점** — 위 기준 커밋 해시 고정. 미머지 근거는 별도 표기한다.
- 재현 명령:

```bash
git fetch --unshallow origin
git rev-parse origin/main                               # 판정 기준 해시
python3 scripts/harness/backlog.py next --n 655 --json   # 전건(절단 금지)
python3 scripts/harness/backlog.py gates list
grep -h "^eos_priority:" backlog/tasks/*.yaml | sort | uniq -c
```

---

## §2. 등재하지 않은 것 ① — §15 동결 13종 (production code 금지)

원 문서 §15는 10월에 **production code 구현을 동결**할 13종을 지정한다("설계 문서는 남겨둘 수 있습니다. 하지만 production code 구현은 동결합니다"). 이들은 **등재 자체가 §15 위반**이므로 신규 태스크를 만들지 않았다. 대신 **현재 준수 상태를 실측**했다 — 동결 대상이 코드에 없다는 것은 갭이 아니라 **준수의 증거**다.

| # | §15 동결 대상 | production code 실측 | 대장 상태 | 판정 |
|---|---|---|---|---|
| 1 | 신규 EOS 기능 번호 추가 | — | `HARN-55` **done** — `backlog.py add`가 `--eos-priority` 미지정 시 **exit 1** | **기계 집행 중** |
| 2 | 새로운 Agent architecture | `agent_framework\|AgentExecutor\|multi_agent` **0 파일** | 대응 태스크 0 | 준수 |
| 3 | 고급 Digital Twin | `digital.?twin\|디지털 트윈` **0 파일** | 대응 태스크 0 | 준수 |
| 4 | 다과목 Adapter 구현 | `SubjectAdapter` 실재하나 **계약 수준**(`schema/subject_adapter.py`·`l4/subject_adapter_math.py`) | `EOS-66` done(계약) · 확장 실구현은 E1~E6 **todo·P3** | 준수(계약≠구현) |
| 5 | Physics/Chemistry/Biology 실제 확장 | 과목 팩 구현 0 | `E1-01`~`E6-01` 전건 **todo·P3·stage E1~E6** + 게이트 `G-s5-subject-expansion`[kiki/decision] | **게이트로 동결 중** |
| 6 | 고급 Knowledge Graph 분석 | `graph_analysis\|centrality\|pagerank\|community_detect` **0 파일** | 대응 태스크 0 | 준수 |
| 7 | 자동 교수법 개선 | `auto.*pedagog\|자동.*교수법` **0 파일** | 대응 태스크 0 | 준수 |
| 8 | 가상 학습 실험 | `virtual.?(learning\|experiment)\|가상 학습` **0 파일** | 대응 태스크 0 | 준수 |
| 9 | 성장 경로 예측 | `growth.?(path\|traject)\|성장 경로` **0 파일** | 대응 태스크 0 | 준수 |
| 10 | 자동 콘텐츠 리팩토링 | `auto.*refactor\|콘텐츠 리팩` **0 파일** | 대응 태스크 0 | 준수 |
| 11 | 연구자 협업 | `researcher\|연구자` **0 파일** | 대응 태스크 0 | 준수 |
| 12 | 고급 A/B framework | `ab_test\|abtest\|experiment_arm` **0 파일** | 대응 태스크 0 | 준수 |
| 13 | 복잡한 ML 추천 | 추천은 IRT CAT·규칙 기반 | `REC-*` 전건이 규칙·회계 축 | 준수 |

> **검색 범위 명시**: 위 실측은 `src/backend/whymath_backend/`·`src/mobile/lib/`를 대상으로 한 **역할 기반 정규식 전수**다. 각 행의 정규식을 그대로 적어 두었으므로 재현·반증이 가능하다. 12번의 초회 검색은 문자열 `A/B`가 한국어 주석에 섞여 17파일을 냈으나, 식별자(`ab_test`·`experiment_arm`)로 좁히면 0이다 — **표기가 아니라 식별자로 판정**했다.

**§14 분류와의 관계**: 원 문서 §14는 기존 기능을 LOOP/SUPPORT/FUTURE로 나누고 "가장 위험한 것은 FUTURE 기능을 계속 개발하면서 LOOP가 완성되지 않는 상황"이라고 경고한다. **이 저장소에서 그 위험은 실현되지 않았다** — FUTURE 7종(교사 협업·연구자 협업·디지털 트윈·가상 학습 실험·자동 콘텐츠 리팩토링·성장 경로 예측·다과목 자동 확장) 중 코드가 있는 것은 0이고, 다과목만 **P3 + stage E1~E6 + 사람 게이트**로 세 겹 동결돼 있다. 프롬프트가 지시한 "FUTURE는 등재하되 priority를 낮추고 10월 착수 금지를 notes에 적는다"는 처방은 **이미 더 강한 형태로 집행 중**이므로(notes 산문이 아니라 stage·게이트), 중복 등재하지 않았다.

## §3. 등재하지 않은 것 ② — 선행 결정이 이미 처분한 항목

| 원 문서 항목 | 처분 | 근거 |
|---|---|---|
| **§3 학습 상태 머신 8상태**<br>(NEW→DIAGNOSING→READY→LEARNING→PRACTICING→ASSESSING→REMEDIATING→ADVANCING) | **보류 — 등재 제외** | 2026-09-03 Kiki 결정(선언 §1.3). 저장소는 상태를 *머신*이 아니라 *이력*으로 모델링한다(`*MasteryHistory` append-only + `attempt_event` 시계열) — 8상태를 세우면 **같은 사실의 두 번째 진실 원천**이 생긴다(붕괴 연쇄 "유지보수 지옥 ← truth source가 하나가 아님"). **만료 없는 유예가 아니다**: 재확인 게이트가 대장에 실재하며(`remind-after-days=101` → G4 2026-12-13 SessionStart 브리핑 노출) 판정 3택(보류 유지 / ADR 채택 / 영구 미채택)까지 적혀 있다 |
| **§18 계획서 300 Gate 2** | **명칭 폐기** | 선언 §1.3-②: `G2` = Anchor Content Production 한 뜻으로만 쓴다. 계획서 300의 `Gate 2`는 사용하지 않는다(이름 충돌 3회차) |
| **CL-WIRING 2건** | **이미 완료** | `MOB-20` done · `EOS-81` done (09-03 결정의 즉시 수행분) |

---

## §4. 대조표 ① — §22 P0 7건

> 판정 어휘: **기존충족**(done이고 계획서 요구를 덮음) / **기존부분**(일부만 덮음 → acceptance 덧붙임 후보) / **신규필요**(대응물 0건)
>
> **P0 7건 중 "신규필요"는 0건이다.** 부품은 전부 서 있고, 빠진 것은 일관되게 **호출 계약의 형태**다 — 원 문서 §2가 "알고리즘보다 Contract"라고 못박은 바로 그 축.

| # | 계획서 항목 | 판정 | 근거 태스크(status) | 코드 실재 | 잔여 갭 |
|---|---|---|---|---|---|
| 1 | **Learning Loop Contract** (§1 14객체+관계) | 기존부분 | `ARCH-37`(done) · `EOS-79`(done) | `docs/architecture/canonical_entity_model_v1.md:172-190`(19종 좌석 귀속표) · `tests/backend/db/test_canonical_entity_model_freeze.py`(기계 집행 4검사) | 14객체 ↔ 19종 정본이 1:1이 아니다(`Recommendation` 좌석 없음 · `Attempt`·`LearningSession`은 `LearningEvent` 좌석에 흡수). **객체 간 관계 계약 미고정** — ARCH-37은 엣지 테이블을 전부 '핵심 외'로 배제했고 EOS-79는 4층 *순서*만 정의하며 스스로 "기계 집행 없음"을 명기 |
| 2 | **LearnerState** (§4 작업1 · 7필드 + 단일 조회) | 기존부분 | `PED-05`(done) | `l2/learner_state.py:53`(class LearnerState v0 8필드)·`:150`(`get_state()`) | 필드 3종 부재(`curriculum_id`·`current_objective_id`·`skill_mastery{}` — 스킬 축은 `l2/skill_mastery_tracking.py`에 분리). **단일 조회 표면 `GET /learner-state` 0건** — 학생 표면은 조각 3개(`/me/mastery/current`·`/me/ability`·`/me/diagnosis/summary`)로 분산. 소비처는 `api/study.py:173` **1곳뿐**. 정본이 배정한 좌석 `user_state_snapshot`(db/models/user.py:294)은 **writer 0** |
| 3 | **Learning Event + Event Trace** (§4 작업2·§17) | 기존부분 | `S3-16`·`EOS-57`·`DP-02`·`EOS-48`(done) · `DP-03`·`DP-04`·`S4-22`(todo) | `db/models/activity.py:311`(AttemptEvent hypertable) · `schema/enums.py:1223-1262`(EventType 11종) · `schema/event_data_contract.py` | 이벤트 *적재*는 충족. **Event Trace(한 학생 전 과정 시간순 재구성)는 0건** — 실 소비처가 집계 롤업(`l2/learning_metrics_rollup.py:301`)·기록률 리포트뿐이고 **per-learner 시계열 조회 표면이 없다** |
| 4 | **Attempt** | **기존충족** | `S3-32`·`MOB-20`·`EOS-81`·`EOS-32`·`PED-37`(done) | `db/models/activity.py:145`(ProblemAttempt) · `api/coach.py:1099-1140`(`_complete_problem` — 학생 경로의 실 생산자) | 신규 등재 불필요. 잔여는 별건 등재됨(`EOS-47` 버전 고정 · `DP-03` 멱등성). **교차 원자성 미해결**은 `EOS-81` acceptance ⑦이 정직 표기로 동결 |
| 5 | **Assessment Engine** (§5.1 Answer→Evidence→State) | 기존부분 | `ASM-03`·`ARCH-38`·`ASM-13`(done) · `ARCH-40`(todo) | `api/me.py:728-748`(AttemptSubmitResponse) · `api/me.py:2890`(POST /assessments/capture) · `l4/misconception/diagnose.py:479` | 계획서의 **3종 묶음(`concept_evidence{}`·`skill_evidence{}`·`possible_misconceptions[]`) 0건**(백엔드 전수 grep). 현행은 (가) 개념·스킬이 '증거'가 아니라 **이미 갱신된 mastery delta**로 반환돼 중간 Evidence 객체가 없고 (나) 오개념은 채점 응답에 합류하지 않고 coach 대화 경로에서만 갱신되며 (다) Assessment 조립이 per-answer가 아니라 CAT 중단 경계 배치다 |
| 6 | **Mastery Update** (§6 인터페이스 분리) | 기존부분 | `EOS-63`(todo·**타 세션 claim**) · `MISC-06`(todo) · `SKB-01`·`PED-14`(todo) | `l2/mastery_tracking.py:52`(`compute_mastery_record(prior_mastery, prior_sample_size, correct, model, elapsed_days)`)·`:202` · `l2/bkt.py:135`(BktModel) | 계획서 시그니처 `update_mastery(learner_state, assessment_evidence) -> mastery_update`의 **계약 분리 0건** — 현행 입력은 **스칼라**(prior, correct)이고 `assessment_evidence` 타입 자체가 없으며 개념 축·스킬 축 두 함수로 갈라져 있다. 교체 가능성은 `BktModel` 클래스 수준까지만(Protocol·레지스트리 미정의·구현 1종) — DKT 대체는 호출부 전수 수정이 필요하다 |
| 7 | **Recommendation** (§8 결과+이유 동반) | 기존부분 | `REC-01`·`REC-11`·`REC-03`·`REC-06`·`REC-04`·`PATH-09`(done) · `REC-10`(todo) | `api/me.py:2106-2165`(NextProblemResponse 5필드)·`:2169` · `l2/recommendation_evidence.py:116-148`(`gate_reason`·`candidates[]`·`policy_version` 영속) | `recommend(learner_state, learning_context)` **호출 계약 부재** — 추천은 HTTP 핸들러가 `user_id`+쿼리 파라미터로 내부 재계산하며 **LearnerState를 입력으로 받지 않는다**. 동반 반환되는 '이유'는 **관측 메타**(적용 축·후보 0 사유·gate_reason)이지 선택된 문항의 추천 근거(지목 개념·왜 이 문항인가)가 아니다 |

**미머지 구현 확인**(`git fetch --unshallow` 후 `git log --all --grep`): EOS-57(#913)·ASM-03(#723)·REC-11(#1126)·EOS-79(#985)·ARCH-37(#984)·EOS-81(#980)·ARCH-38(#997) 전부 main 도달. **7단위 어디에도 고립 미머지 구현은 없다.**

---

## §5. 대조표 ② — §22 P1 5건 · P2 3건

| # | 계획서 항목 | 판정 | 근거 태스크(status) | 잔여 갭 |
|---|---|---|---|---|
| 8 | **Misconception Detection** (§7) | 기존부분 | `MISC-21`·`MISC-17`·`MISC-23~29`·`MISC-07`·`REC-02`·`ASM-09`(done) · `ASM-06`(**blocked**)·`MISC-13`·`MISC-14`(todo) | 풀이 서술(텍스트) 입력축은 완비 — `l4/misconception/diagnose.py:479` → `match_gate.py:91`(신뢰도 하한 0.65) → `hypothesis.py:110` → `hypothesis_store.py:151` → `l2/learner_state.py:89`. 카탈로그에 계획서 예시(완전제곱식 오인)도 실재(`catalog.py:458-464`). **미배선은 오답 선택지(distractor) 입력축뿐** — `distractor_map` 1,616건이 사장돼 있고 역방향 배선 `ASM-06`이 blocked |
| 9 | **Remediation** (§9) | 기존부분 | `MISC-15`(todo·**미착수 확정**)·`MISC-06`·`MISC-01`·`MISC-03`·`PATH-12`(todo) · `MISC-02`(blocked) | mastery·confidence 축 분기는 실재(`l4/misconception/intervene.py:59` · `l4/prerequisite_coaching.py:32` ← `api/me.py:1674-1720`). **"같은 오류 ≥2/≥3/≥4" 반복 사다리는 reader 0건** — `evidence_count`(`hypothesis.py:79`)를 읽어 강도를 올리는 코드 0. `MISC-06`은 acceptance가 "코칭 강도 결정엔 미사용"으로 **명시 제외** → 어느 태스크도 소유하지 않음. 임계도 3모듈 분산(0.65/0.7/0.4·0.8) |
| 10 | **Diagnostic** | **기존충족** | `ASM-01`·`ASM-03`·`ASM-04`·`ASM-05`·`ASM-07`·`ASM-12`·`REC-04`·`MOB-10`·`PATH-05`(done) | 신규 등재 불필요. 잔여는 별건 등재됨(`ASM-10` 시행 귀속·`ASM-11` 학생 화면) |
| 11 | **Content Retrieval** | 기존부분 | `PED-03`·`PED-07`·`PED-23`·`MOB-13`·`EOS-98`·`VIZ-01`(done) · **`CUR-18`(blocked)**·`KG-02`(blocked) | 목록·공급 좌석 완비(`api/concepts.py:242` · `l4/content_supply.py:93`). **개념 단건 ↔ 관계·선수·오개념·문항·목표·설명·시각화 묶음 조회가 `CUR-18`(blocked)에 묶여 미착지** |
| 12 | **AI Tutor v1** (§10) | 기존부분 | `PED-04`·`PED-34`·`EOS-86`·`MISC-17`(done) · `PED-18`·`PED-19`·`OPS-36`·`S4-11`(todo) | **계획서 §10의 핵심 제약("LLM이 학습 상태를 직접 결정하지 않는다")은 이미 코드로 집행 중** — `harness/wh1_llm_policy.py:496 _enforce_invariants`가 미검증 종료턴을 verify로 재지정하고 오답·막힘 종료를 소크라테스로 강등한다. 갭: ①**RAG 미배선**(`wh1_llm_policy.py:222-226`이 "실제 graph traversal 없음"을 자인 · `l1/atom_graph/retrieval.py:92` 소비자 0) ②학생 개념질문 라우팅 0(`PED-19`) ③작동 비율 미관측(`PED-18`) ④힌트 본문 생성기 부재(`S4-11`) |
| 13 | **Analytics** (P2) | 기존부분 | `COLLAB-03`·`DP-02`·`S3-16`·`PED-06`·`PED-13`·`ARCH-17`(done) · `COLLAB-06`·`OPS-19`(todo) | 집계 함수·이벤트 계약 완비(`l2/learning_metrics_rollup.py:301,386,460,693`). **부르는 주체가 0건** — 롤업 CLI 호출처가 `scripts/`·`.github/`·compose·celery beat 전부 0이라 미집계와 무활동이 `days_counted==0`으로 같게 보인다(`COLLAB-06` 소유) |
| 14 | **관리자 관찰 기능** (P2) | 기존부분 → **1축 신규필요** | `ADMIN-04`·`ADMIN-05`·`ADMIN-06`·`ADMIN-07`·`ADMIN-12`(todo·**코드 0건**) | `/v1/admin/*` 라우터 자체가 0건. 유일한 운영자 게이트 학습 표면 `GET /v1/me/harness-metrics`는 docstring이 **self-scoped**를 명시. `ADMIN-05`의 '사용자 조회'는 **계정** 조회이지 학습 상태 조회가 아님 → **"운영자가 특정 학생의 학습 상태를 조회"는 소유자 0건** |
| 15 | **Recommendation Explanation** (P2) | 기존부분 | `REC-01`·`REC-04`·`REC-06`·`REC-11`·`PATH-02`·`PATH-09`·`PATH-10`(done) · `REC-10`(todo) | 서버측 정직 표기 완비, **학생 도달 0**(클라가 신규 5필드 전건 미파싱). 더 중요한 구분: 노출되는 것은 **계측 축**(가중 축·풀 크기·사유 코드)이지 계획서가 말하는 **교수적 이유**("이 오개념 때문에 이 문항")가 아니다 |

## §6. 대조표 ③ — §22가 덮지 않는 횡단 8축

| # | 축 | 판정 | 근거 | 잔여 갭 |
|---|---|---|---|---|
| 16 | **§3 8상태 상태 머신** | **등재 제외**(신규필요이나 보류 결정) | 어휘 5종 전수 검색 → `src/`·`schemas/` **코드 0건**. 대응물 실재: `ConceptMasteryHistory`·`SkillMasteryHistory`(append-only) · `AttemptEvent` hypertable · `l2/learner_state.py:53` | §3 참조 — 09-03 보류 + G4 재확인 게이트 |
| 17 | **§13 EOS 내부 경계** | **기존충족** | `EOS-65·66·67·69·84·85·86·88·89·90`(전건 done·main 도달). import-linter **3계약**(`src/backend/pyproject.toml:215~`) + CI 상시 `lint-imports`(`ci.yml:373-374`) + 위험신호 AST 스캐너 `scripts/analysis/eos_core_boundary_probe.py:47`(`SUBJECT_LITERALS`) + 동결 테스트 4종 | 합성 루트 경유 면제 1건(`l4.solution_coaching -> composition`) — `ARCH-99` 소유·G1 재확인. **계획서가 위험신호로 지목한 `if subject == "math"`는 이미 기계가 감시 중** |
| 18 | **§16 SCENARIO-001~010** | 기존부분 | 관통 테스트 2종 각 13단계(`test_e2e_vertical_slice_integration.py:455` · `e2e_loop_flow_test.dart:296-464`) | SCENARIO 식별자 집합 **0건**. 미커버 6종(002·004·005·008·009·010) — 009·010의 공통 원인은 **`LearningSession` writer 0**이고 테스트가 `session_id is None`을 단언해 공백을 계약으로 동결 중. **"CI 상시" 미충족** — nightly(`ci.yml:1566` `if: schedule`) 전용이라 PR·push에서 안 돈다 |
| 19 | **§12 API 12종** | **11/12 대응 · 1 갭** | 107 엔드포인트/22 라우터 전수 추출 후 역할 대조 | 유일 갭 = **`GET /learner-state` 합성 표면**(소유자 0건). 나머지 11종은 경로 이름이 달라도 역할 대응물 실재 |
| 20 | **§19 KPI 5축** | 기존부분 | ②`ops/integrity_violations_gate.py`(6종+CI) ③`REC-11`(done) ⑤`EOS-79`+`evidence_link`+`attempt_event` | **①Loop Completion·④Manual Intervention 소유자 0건**. ①은 `LearningSession` writer 0이라 **분모가 구조적으로 미정의**. ④는 저장소가 G4(12/13) 배정. ⚠ 저장소 KPI 정본은 **12종**(`ops/validation_scorecard.py:129`)이라 계획서 5축과 **다른 축** — 병합 시 이중 정본 위험 |
| 21 | **§18 Gate 2 10+1** | 기존부분 | 10조건 중 9개 대응물 실재(상세 = 09-03 대조 §2) | 조건10 "반복 가능"은 **1회 관통까지만** 실증 — 연속 3루프 테스트 0건. ★조건(운영자 개입 0으로 3연속)은 `backlog/gates.yaml` 54건 중 **게이트 항목 0건**(선언 본문에만 존재·G4 배정) |
| 22 | **§20 Vertical Slice PR 규약** | **신규필요** | 소유 태스크 0건. `.github/pull_request_template.md:9`에 슬라이스 칸 0 | 09-03 대조 §8-③이 "부분 채택·P2"로 권고했으나 **등재된 적이 없다** — 소유자 없는 권고로 13일째 부유 |
| 23 | **§11 Persona A/B/C 완주** | **신규필요** | 소유 태스크 0건 | E2E 2종 모두 **합성 학습자 1인**(`uuid4` 단일). B축(선수결손)은 부분 실재하나 완주 미도달, C축(오개념)은 실증 0. ⚠ `l1/problem_bank/persona_fit_rules.py`의 페르소나는 **문항 적격 필터**용이지 학습자 여정 페르소나가 아니다 |

---

## §7. 산출 ① — 등재·수정된 태스크 전체 목록

### 7.1 신규 등재 9건

| 태스크 ID | 원 문서 항목 | §14 | priority | eos_priority |
|---|---|---|---|---|
| `EOS-10-learner-state-single-surface` | §4 작업1 · §12 #2 | LOOP | 1 | P1 |
| `EOS-11-learning-event-trace-read-surface` | §4 작업2 · §17 | LOOP | 1 | P2 |
| `EOS-12-assessment-evidence-contract` | §5.1 | LOOP | 1 | P1 |
| `EOS-13-mastery-update-call-contract` | §6 · §2 | LOOP | 1 | P1 |
| `EOS-14-recommend-call-contract` | §8 · §2 | LOOP | 1 | P1 |
| `MISC-30-repeat-error-intervention-ladder` | §9 | LOOP | 2 | P2 |
| `ADMIN-13-operator-learner-state-view` | §22 P2 | SUPPORT | 3 | P2 |
| `EOS-15-loop-completion-and-manual-intervention-kpi` | §19 ①④ | SUPPORT | 3 | P2 |
| `HARN-107-vertical-slice-task-decomposition-convention` | §20 | SUPPORT | 3 | P2 |

**선행 집행 1건**: `EOS-14` → `depends_on: EOS-10`(산문 아님 · HARN-52 · `audit-deps` green).

### 7.2 기존 태스크 수정(amend) 2건

| 태스크 ID | 덧붙인 축 | 변경 |
|---|---|---|
| `PED-36-learning-scenario-bank-schema` | §16 SCENARIO-001~010 · §11 페르소나 3인 완주 · §18 연속 3루프 | acceptance ⑧~⑫ · priority 3→2 |
| `REC-10-next-problem-honesty-fields-render` | §8 "계측 축 ≠ 교수적 이유" 경계 + 사유 라벨 어휘 설계 | acceptance ⑤~⑦ |

### 7.3 변환 태스크 자신

`EOS-09-plan300-phase2-backlog-conversion`(in_progress) — 본 문서의 소유 태스크.

> **우선순위 매핑 주의**: 프롬프트가 지시한 §22 매핑(P0=1·P1=2·P2=3·P3=보류)은 **`priority`(1~5 스케줄링 축)** 에 적용했다. `eos_priority`는 **저장소의 12월 검증 관여도**라는 다른 축이며(P0 = 없으면 G0~G5가 성립하지 않는다), 09-03 결정으로 12월 경로가 G2 앵커 콘텐츠 생산인 이상 계획서 P0를 저장소 P0로 옮기면 거짓이 된다. 두 축을 섞지 않았다. P0 예산은 이 변환 전후 모두 **5/50**이라 One In → One Out은 발동하지 않았다.

## §8. 산출 ② — 겹침으로 등재하지 않은 항목

| 원 문서 항목 | 등재하지 않은 근거 |
|---|---|
| §22 P0 **Attempt** | `S3-32`·`MOB-20`·`EOS-81`·`EOS-32`·`PED-37`(done)이 덮는다. 잔여는 `EOS-47`·`DP-03`이 이미 소유 |
| §22 P1 **Diagnostic** | `ASM-01/03/04/05/07/12`·`REC-04`·`PATH-05`(done). 잔여는 `ASM-10`·`ASM-11` 소유 |
| §22 P1 **Content Retrieval** | `CUR-18`(blocked)이 묶음 조회를 소유 — blocked 해소가 경로이지 신규 등재가 아니다 |
| §22 P1 **Misconception Detection** | 텍스트 입력축 완비. 잔여(distractor 입력축)는 `ASM-06`(blocked)·`MISC-13`·`MISC-14` 소유 |
| §22 P1 **AI Tutor** | `PED-18`·`PED-19`·`OPS-36`·`S4-11` 소유. 핵심 제약은 이미 코드 집행 중 |
| §22 P2 **Analytics** | `COLLAB-06`(호출 주체 0)·`OPS-19` 소유 |
| §13 **EOS 내부 경계** | `EOS-65~90` 10건 done + import-linter 3계약 + CI 상시. 잔여 감시는 `ARCH-41`·`ARCH-99`·`EOS-70` 소유 |
| §12 **API 11종** | 107 엔드포인트 안에 역할 대응물 실재 |
| §19 **KPI ②③⑤** | `integrity_violations_gate`·`REC-11`·`EOS-79` 소유 |
| §1 **14객체 관계 계약** | `ARCH-37`(done)이 엣지 테이블을 **의도적으로 '핵심 외'로 배제**한 판정이 있다. 재개는 등재가 아니라 **그 판정의 갱신**이 선행이다(§9-② 참조) |
| §15 동결 13종 · §14 FUTURE 7종 | §2 참조 — 등재 자체가 §15 위반이고, 다과목은 이미 P3+stage E+게이트로 3중 동결 |
| §3 8상태 머신 · §18 계획서 Gate 2 · CL-WIRING | §3 참조 — 선행 결정이 이미 처분 |

## §9. 산출 ③ — 원 문서가 요구하지만 등재할 수 없었던 것

| # | 요구 | 등재 불가 사유 |
|---|---|---|
| ① | **§18 ★조건 — 운영자 DB 개입 0으로 3연속 루프** | **일정 충돌이 미해소**라 태스크가 아니라 **결정**이 선행한다. 계획서는 이것을 10/25 Gate 2 최중요 조건으로 두지만 저장소는 **G4(12/13)** 에 배정했다(선언 부록 E). 어느 날짜가 정본인지 정해지기 전에는 태스크의 기한·게이트를 쓸 수 없다. 현재 `backlog/gates.yaml` 54건 중 이 조건의 게이트는 **0건**이다 |
| ② | **§1 14객체 관계 계약 고정** | `ARCH-37`(done)이 19종 좌석 정본을 세우며 엣지 테이블(`concept_edge`·`evidence_links` 등)을 **'핵심 외'로 명시 배제**했고, `EOS-79`는 4층 *순서*만 정의하며 스스로 "기계 집행 없음"을 적었다. 관계 계약을 지금 등재하면 **이미 내려진 배제 판정을 태스크가 조용히 뒤집는다**. 필요한 것은 "관계 계약을 세울 것인가"라는 결정이지 착수 단위가 아니다 |
| ③ | **§19 KPI 5축의 저장소 편입** | `EOS-15`로 ①④에 소유자는 줬으나, **5축 전체를 저장소 KPI로 삼을지는 결정 사항**이다. 저장소 정본은 12종(기술 6 + 내용 6)이고 계획서 5축과 축이 다르다 — 그냥 얹으면 KPI 정본이 둘이 된다. `EOS-15` acceptance ④가 그 판정을 강제하지만, 판정 자체는 태스크가 아니라 Kiki 몫이다 |
| ④ | **"10월에 이것을 한다"는 일정 자체** | 본 변환은 **착수 단위**를 만들 뿐 일정을 배정하지 않았다. 09-03 결정이 10월을 G2 앵커 콘텐츠 생산으로 고정했으므로, 등재분에 10월 기한을 박으면 그 결정과 충돌한다. 기한은 결정 갱신 후에 붙인다 |
| ⑤ | **§4 "가짜 데이터라도 전체 흐름이 한 번 돌아가게"(Week 1 Gate)** | 등재 불필요 — **이미 돈다**. `test_e2e_vertical_slice_integration.py` 13단계가 온보딩→진단 CAT→문제→코치 오답→다턴→verify→정답턴→돌아보기→attempt·개념숙달·스킬숙달·이벤트 4커밋 개별 단언→추천 갱신까지 관통한다(`EOS-81` done). 계획서가 Week 1에 배정한 것이 저장소에는 9/5에 이미 있다 |

## §10. 이 변환이 드러낸 것 — 한 문단

계획서 300이 4주에 걸쳐 만들려는 부품은 **거의 다 서 있다**. §22 P0 7건 중 "대응물 0건"은 하나도 없었고, §12 API 12종 중 11종에 대응물이 있으며, §13 경계는 import-linter 3계약과 CI 상시 검사로 이미 기계가 지킨다. 빠진 것은 부품이 아니라 **형태**다 — `update_mastery(state, evidence)`·`recommend(state, context)`처럼 계획서 §2가 "알고리즘보다 Contract"라고 못박은 **호출 계약의 모양**, 그리고 흩어진 조각을 하나로 돌려주는 **합성 표면**(`GET /learner-state`). 신규 등재 9건 중 5건이 정확히 그 축이다. 반대로 계획서가 §15에서 금지한 13종은 **이미 전부 코드 0건**이고, §14가 "가장 위험하다"고 경고한 "FUTURE를 개발하느라 LOOP가 미완성"인 상태도 실현되지 않았다. 남은 진짜 병목은 계획서가 강조하지 않은 곳에 몰려 있다 — **`LearningSession` writer 0**이 KPI ① 분모와 SCENARIO 009·010을 동시에 막고 있고, 관통 테스트가 **nightly 전용**이라 PR에서 돌지 않으며, 분석 롤업은 **부르는 주체가 없어** 미집계와 무활동이 같은 숫자로 보인다.

---

**작성**: 2026-09-16 · `EOS-09-plan300-phase2-backlog-conversion` · 판정 기준 main `2e1220b4`
---

## §11. 추가 대조 — `P-01~P-16` 지시문 세트와의 교차 검증 (2026-09-16 · 사후 추가)

### 11.1 `P-01~P-16`의 실제 소재 — §0-3의 정정

§0-3은 "원 문서 §3에 `P-01~P-16` 목록은 없다"고 적었다. **그 판정은 유효하나, 목록 자체는 실재한다** — 다른 세션이 만든 **집행 지시문 세트**에 있다:

> 「실측」 `docs/ops/phase2_eos_closed_loop_execution_prompts.md:116` — `## 3. 항목별 순차 지시문 (P-01 ~ P-16)`
> 소재: PR #1176(`claude/lucid-keller-3vb49j` @ `0d8e848c`) · **상태: open·미머지**(main 기준 0건)
> 그 PR 본문: *"태스크 id 없음(요청 응답 산출물). 후속으로 **P-00a 지시문이 원 문서를 백로그 태스크로 변환**하게 되어 있다."*

즉 본 변환(`EOS-09`)은 그 지시문 세트의 `P-00a`가 지목한 후속 작업이다. 그 PR의 「정직한 공백」도 *"원 문서 항목 ↔ 기존 태스크 겹침을 이 PR에서 해소하지 않았다 … 해소는 P-00a 지시문이 실행될 때로 넘겼다"* 라고 적어 이 문서에 그 몫을 넘긴다.

**판정 시점 주의**: `P-01~P-16` 지시문 세트는 **미머지**다. 본 문서의 다른 모든 판정이 main `2e1220b4` 기준인 것과 달리, 이 §11만 **브랜치 포함 기준**이다. 열을 나눠 적는 이유가 이것이다 — 지시문 세트가 머지되지 않으면 아래 대조의 좌열은 저장소에 존재하지 않는다.

### 11.2 `P-01~P-16` ↔ 본 변환 산출물 대조

| 지시문 | 원 문서 절 | 본 변환의 처분 | 태스크 |
|---|---|---|---|
| `P-01` Learning Loop Contract v1 | §1·§2 | ~~등재 제외~~ → **신규 등재**(2026-09-16 정정 — 아래 §11.4) | `EOS-100` |
| `P-02` Learning Event 정본화 | §4-작업2·§17 | 신규 등재 | `EOS-11` |
| `P-03` LearnerState v1 | §4-작업1 | 신규 등재 | `EOS-10` |
| `P-04` 학습 상태 머신 | §3 | **등재 제외** — 09-03 보류 + G4 재확인 게이트 실재 | §3 표 |
| `P-05` Assessment Engine v1 | §5 | 신규 등재 | `EOS-12` |
| `P-06` Mastery Engine v1 | §6 | 신규 등재 | `EOS-13` |
| `P-07` Misconception 연결 | §7 | **기존충족** — 텍스트 입력축 완비. 잔여(distractor)는 `ASM-06`(blocked) 소유 | §5 단위8 |
| `P-08` Recommendation + Reason | §8 | 신규 등재 + amend | `EOS-14` · `REC-10` |
| `P-09` Remediation 정책 | §9 | 신규 등재 | `MISC-30` |
| `P-10` AI Tutor v1 | §10 | **기존부분** — 핵심 제약은 이미 코드 집행 중. 잔여는 `PED-18`·`PED-19`·`OPS-36`·`S4-11` 소유 | §5 단위12 |
| `P-11` 필수 API 표면 | §12 | 신규 등재(12종 중 유일 갭) | `EOS-10` |
| `P-12` EOS 경계 기계 집행 | §13 | **기존충족** — import-linter 3계약 + CI 상시 + AST 스캐너 | §6 단위17 |
| `P-13` SCENARIO-001~010 + CI 배선 | §16 | amend | `PED-36` |
| `P-14` KPI 5종 계측 | §19 | 신규 등재(②③⑤는 기존 소유자 실재, ①④만) | `EOS-15` |
| `P-15` 페르소나 3종 안정화 | §11 | amend | `PED-36` |
| `P-16` Gate 2 최종 판정(10/25) | §18 | **등재 제외** — 빌드 항목이 아니라 게이트 판정. 게다가 §9-① 일정 충돌 미해소 | §9-① |

**16종 전건에 처분이 대응한다** — 신규 등재 **8건** · amend 2건 · 기존충족 3건 · 등재 제외 **2건** · (P-11은 P-03과 같은 태스크로 수렴). *`P-01`은 2026-09-16 정정으로 등재 제외 → 신규 등재(§11.4).*

### 11.3 대조가 드러낸 것 — 지시문 세트가 빠뜨린 2축

`P-00a`는 "§3 목록을 기준 분해안으로 삼되 **그대로 믿지 말고 대조하라**"고 지시했다. 대조 결과, `P-01~P-16`은 **원 문서 §22·§20의 2축을 담지 않는다**:

| 누락 축 | 원 문서 근거 | 본 변환이 등재한 태스크 |
|---|---|---|
| **관리자 관찰 기능** | §22가 **P2로 명시 배정**한 3종 중 하나("Analytics · 관리자 관찰 기능 · Recommendation Explanation"). `P-01~P-16` 어디에도 대응 항목이 없다 | `ADMIN-13` — `/v1/admin/*` 라우터 0건이고 유일한 운영자 학습 표면은 self-scoped |
| **Vertical Slice PR 규약** | §20 전체. `P-01~P-16`은 이 절을 항목화하지 않았다(마스터 프리앰블의 산출 규율에만 반영) | `HARN-107` — 09-03 대조 §8-③의 권고가 13일째 미등재였다 |

즉 §22 20건을 분해 기준으로 삼은 것이 결과적으로 옳았다 — 16종 지시문만 따랐다면 **§22가 P2로 명시한 축 하나와 §20 전체를 놓쳤을 것**이다.

---

## §11.4. `P-01` 처분 정정 (2026-09-16 · 같은 날 후속)

§11.2가 `P-01`을 **등재 제외**로 적은 근거는 §9-②였다:

> 관계 계약을 지금 등재하면 **이미 내려진 배제 판정**(`ARCH-37`이 엣지 테이블을 '핵심 외'로 명시
> 배제)을 **태스크가 조용히 뒤집는다.** 필요한 것은 "관계 계약을 세울 것인가"라는 **결정**이지
> 착수 단위가 아니다.

그 결정이 같은 날 내려졌다 — **Kiki 지시(계획서 300 집행 지시문 `P-01` 실행)**. 따라서 처분을
`EOS-100-learning-loop-relation-contract` **신규 등재**로 정정한다.

**§9-②의 우려는 해소됐다 — 축이 다르기 때문이다.**

| 축 | `ARCH-37`이 배제한 것 | `EOS-100`이 고정한 것 |
|---|---|---|
| 대상 | **저장 좌석** — 관계를 담는 *테이블* | **호출 어휘** — 관계의 *이름과 방향* |
| 산출 | 80테이블 전수 귀속표 | 14객체·18관계 삼중항 레지스트리 |
| 신규 테이블 | — | **0건** |

`EOS-100`은 엣지 테이블에 좌석을 주지 않는다. 좌석이 없는 객체(`Recommendation`)는 `no_seat`으로
적고 끝내며, 20번째 엔티티를 만들면 `ARCH-37` 검사 ②가 RED다. 좌석 축의 정본은 여전히
`canonical_entity_model_v1.md` 하나다. 상세는 `docs/architecture/learning_loop_contract_v1.md` §0.

§9-②의 표는 이 정정으로 **1행이 줄어** ①③④ 3건이 남는다(②는 해소).
