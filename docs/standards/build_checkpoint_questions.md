# 구축 플레이북 단계별 진행 점검 질문 세트

> **목적**: WhyMath **구축 플레이북 v1.0**(Part 1·8·10·12)을 기준으로, 지금 프로젝트가 *"어디까지 왔고 · 불변식을 어기지 않았고 · 무엇을 고쳐야 하는가"*를 단계별로 자기점검하기 위한 핵심 질문지.
> **연계 문서**: `CLAUDE.md`(2대 철칙·8대 구조원칙·질문 프로토콜) · `docs/standards/playbook_part_review_questions.md`(Part 0~12 **설계-준수** 축 — 이 문서는 **진행** 축) · `docs/standards/prompt_engineering.md` · `MEMORY.md`(결정 로그).

---

## 사용법 규약

- 각 단계마다 **3박자**로 묻는다: `① 지금 어디까지? → ② 플레이북 불변식 위반은? → ③ 무엇을 고칠까?`
- 단계 끝마다 반드시 **메타 질문**(맨 아래)을 붙인다.
- `/review`·`/status` 세션 시작 시 이 문서를 로드해 훑고, ❌ 뜨는 항목은 **`MEMORY.md` 결정 로그**로 남긴다.
- 이 문서는 *질문지*다. 답(현재 상태)은 코드·`MEMORY.md`가 진실 원천이며, 여기 적힌 현재 상태 태그(`[완료]`/`[구현]`/`[진행]`/`[프로토타입]`)는 점검 시작점일 뿐 — **점검할 때마다 실제 코드로 재확인**한다.

### 현재 상태 스냅샷 (2026-07-15 8회차 갱신 · Phase 1 MVP · 감사: `arch_audit_2026-07-15_r8.md`)

| 단계 | 영역 | 상태 |
|---|---|---|
| 1 교육철학 · 2 기능분리 | 정체성·7계층 (백엔드 import-linter CI 강제) | ✅ 완료 |
| 3 개념구조화 | 개념 <!-- fact:concept_graph.concepts -->437<!-- /fact -->노드 (legacy_snapshot·audit_only) / **원자 백본 <!-- fact:atom_graph.nodes -->2,683<!-- /fact -->(세부 <!-- fact:atom_graph.atoms -->1,823<!-- /fact -->) = runtime truth source 단일**. problem_concept·curriculum·성취기준 조인 전부 원자 축 정착(S2-03·S2-07) | 🟢 구현 |
| 4 오개념 DB | <!-- fact:misconceptions.count -->843<!-- /fact -->개 카탈로그 + 판정 엔진 (reactive만·preload 0 실측). 탐지 카탈로그 64종·kebab↔M-id crosswalk 라이브 <!-- fact:misconception_crosslinks.count -->69<!-- /fact -->건(전건 사람 서명·기계 reject-only·`G-crosswalk-approval` **cleared**[7회차 적대 검증: 스탬프가 clear 14h 선존·evidence 결함 3건 상환]·적재/노출 플립 전 단계) | 🟢 구현 |
| 9 평가·개인화 | BKT·IRT·mastery·학습경로 (문제 태깅 원자 축 재연결로 mastery→enrich hit) | 🟢 구현 |
| 5 시각화 · 6 Math UI DSL · 8 AI튜터 · 10 자동화 | Graph2dSpec·L3 라우터·WH-1·파이프라인 (8: max_nodes≤20·tokens≤3000 CI 동결·depth≤2 유예). **L3 라이브 개통**(Phaiakes9·READY:True·6모델·rephrase 184/590). **S1-12 비용 실측 완료**(로컬 72.7%<80% as-measured·S1-13 보정 74/358·8회차 §3-A). **S1-11 shadow verdict 라이브 실측**(n=10·검출력 4/4·verify 게이트 승격 부결 유지·실트래픽 재판정 대기·8회차 §3-B) | 🟡 진행 |
| 7 렌더링 | Flutter/web 계산기·three.js·MathLive | 🟡 프로토타입 |
| 보류/리스크 | DSL 자기진화(Lean4)·Manim 동영상·WH-1 전략단계(Lv2~3)·**개념↔원자 입도 통합**(런타임 축은 S0-4로 해소 완료, 잔여=<!-- fact:concept_graph.concepts -->437<!-- /fact -->↔<!-- fact:atom_graph.nodes -->2,683<!-- /fact --> 세분도 병합). ~~전문가 검수 대기~~ → **AI 검수 전환**(2026-07-10·`G-domain-partner` clear·검수 큐 가동·MEMORY 결정 로그). ~~클라이언트 무-수학로직 CI 게이트 부재~~ → **ARCH-10으로 해소**(게이트 2종 가동·2026-07-12 감사 4회차 재검증, QuizMode 예외는 **ARCH-12 (a) 데모 전용 예외 공식 존치**(2026-07-13 Kiki 결정·화이트리스트 2건 동결·강제 트리거=학생 노출)). S1 탈출 게이트 ① 실기기 시연 `G-kiki-device-demo` clear·라이브 실측 S1-12(kiki)·저작권 `G-crosswalk-approval` **cleared**(7회차 §3-A). ~~생성 파이프라인 계통 결함 3종~~ → **S2-08 상환 완료**(PR #512·6회차 감사 이행 실측·deferred 표본 29·30 해소). ~~crosswalk 대장 비정합~~ → **S2-10 이행 완료 + 게이트 clear**(7회차 §3-A). 신규: **콘텐츠 공장 가동 완료**(S2-01 620문·Wilson 상한 1.11% PASS[as-found 병기]·S2-02 WH-S replay·PRM 1,282쌍·상시 게이트 Tier1+Tier2 승격). acceptance sampling 엄밀화 **S2-11 done**(§4.5 재채점 금지 규약·`--rotation` 독립 재표본·8회차 §3-C 적대 검증 적정). as-found 병기 기계 게이트화는 `S2-12`(신설·저우선) | 🔴/⏸ |

---

## 🔴 최우선 점검 2곳 (현재 상태상 붕괴 위험 최고)

- **단계 3** — ~~단일 진실 원천 붕괴~~ → **런타임 축 해소 완료**(2026-07-04 S0-4: 원자 단일 truth source·구 437 legacy_snapshot 격하·`test_legacy_snapshot_governance.py` 동결) → **런타임 드리프트도 봉인**(2026-07-25 ARCH-13: 마지막 남았던 L2 추천의 교차 엔진 code 문자열 조인을 제거하고 선수 traversal에 **쿼리 수준 원자 축 울타리**를 세움·제외 사유 계상·`test_atom_axis_fence_governance.py` 동결). 잔여 = **입도 통합의 콘텐츠 축**(860 단원/소단원 계층 브리지·난이도 척도 통일[tier 0~24↔intrinsic 1~5]·crosswalk 인간 검수 — ARCH-13이 명시적으로 범위 밖으로 둔 4건·`G-domain-partner` clear 2026-07-10) & 노드 폭발 상시 감시
- **단계 8** — LLM에 **전체 그래프 노출** — 감사(2026-07-09) 재확인: max_nodes≤20·max_tokens≤3000은 첫 소비처(`wh1_llm_policy.py`)에서 **준수·CI 동결**, 전체 그래프 미주입 경계는 `test_llm_subgraph_budget_invariant.py` 동결. **depth≤2만 유예**(traversal 소비처 부재·해제 트리거 = coach→하네스 수렴 시 `ARCH-11`). 상세: `build_roadmap_part10_review.md`·`arch_audit_2026-07-09.md`

---

## 단계 1. 교육철학 · 정체성 `[완료]`

- [ ] 최근 3개월 의사결정이 **"답이 아닌 이유"** · 3대 핵심(①오개념 ②시각화 ③개인화)에서 이탈한 것은 없나?
- [ ] Phase 1 페르소나(**고3**)에 집중돼 있나, 미착수 페르소나(검정고시·학종 등)로 범위가 새고 있나?
- [ ] "정답을 빠르게"·정답률 우열·중독성 게임화가 KPI·설계에 스며들지 않았나?

## 단계 2. 핵심 기능 분리 `[완료]`

- [ ] 필수 15기능 중 **실코드 vs 문서만**을 구분했나? (특히 #5 단계별 힌트 · #13 풀이 비교 · #14 메타인지 피드백이 실제로 도나?)
- [ ] 7계층 경계 침범(L_n → L_{n+1} **역참조**)이 import-linter로 실제 차단되나?
- [ ] 수학 로직이 클라(L5)로 새지 않고 L1–L4 독립 코어에만 있나?

## 단계 3. 개념 구조화 (ConceptNode·AST) `[구현·최우선]` — <!-- fact:concept_graph.concepts -->437<!-- /fact -->노드 / <!-- fact:atom_graph.atoms -->1,823<!-- /fact -->원자

- [ ] **노드 폭발 검문**: 각 노드/원자가 "학생 사고가 바뀌는 최소 단위 = **독립 오개념 발생 단위**"인가? <!-- fact:atom_graph.atoms -->1,823<!-- /fact --> 원자에 '기울기의 x증가량' 급 **과세분**이 섞이지 않았나?
- [ ] **Concept Purity**: 노드에 renderer·curriculum·prompt·misconception·embedding이 **혼입**되지 않았나? (`graph.json` 필드 감사)
- [ ] **파일 크기**: 노드가 1~4KB 이내인가? `graph.json` 단일 대용량 파일이 retrieval precision을 떨어뜨리지 않나(chunk 분리 여부)?
- [ ] **ID 독립**: ID가 `math.calculus.limit` 형태로 파일명·언어·교육과정과 독립인가?
- [ ] **⚠️ 단일 진실 원천**: 개념그래프(<!-- fact:concept_graph.concepts -->437<!-- /fact -->)와 원자그래프(<!-- fact:atom_graph.atoms -->1,823<!-- /fact -->)의 truth source가 둘로 갈라져 **"유지보수 지옥"**이 시작되지 않았나? 어느 쪽이 canonical이고, 둘의 동기화 규칙이 **코드로 강제**되나?

## 단계 3-관계. Edge 설계 `[구현]` — <!-- fact:concept_graph.edges -->581<!-- /fact -->엣지 / <!-- fact:atom_graph.prerequisite_total -->3,251<!-- /fact -->선수엣지

- [ ] **관계 폭발**: Edge 타입이 5~8개로 제한되나? `similar_to`/`related_to`가 **traversal에 쓰이나**?
- [ ] **순환참조**: `prerequisite`이 DAG를 유지하나? <!-- fact:atom_graph.prerequisite_total -->3,251<!-- /fact --> 선수엣지에 **Reachability(순환) Check**가 CI로 도나?
- [ ] 단방향 **canonical edge**로 저장됐나?

## 단계 4. 오개념 DB (Misconception) `[구현 · 3대핵심①]` — <!-- fact:misconceptions.count -->843<!-- /fact -->개

- [ ] 오개념이 개념과 **독립 DB**인가(Concept≠Misconception)? 개념 노드에 **preload 안 되고 reactive retrieval**인가?
- [ ] concept / misconception **embedding index가 분리**돼 있나?
- [ ] <!-- fact:misconceptions.count -->843<!-- /fact -->개가 실제 학생 응답으로 검증되나, **LLM 생성 카탈로그로만** 남았나? (오개념 = 실패 패턴이지 개념이 아님)

## 단계 5. 시각화 (VisualizationNode) `[구현 · 3대핵심②]` — Graph2dSpec

> **검토 완료(2026-07-02)**: 정본 `docs/architecture/05b_visualization_classification.md`. 4분류
> 판별(`Visualizability`)·Renderer 독립·5상태 분리 모두 충족·CI 강제.

- [x] **개념 4분류 판별**(직접/동적/추상/불가): 시각화 Overlay `concept_visualization`(노드 비내장) + `l4/visualization_policy.py` 게이트(추상·불가→보류·소크라테스 폴백). "전부 똑같이 그리려" 방지
- [x] **Renderer는 Plugin**: VisualizationNode에 Desmos/Canvas/three.js **구현체 이름**이 없나? (Concept → Visualization Intent → Renderer Adapter) — 노드·스키마 0, 구현체명은 `render_contract.json`·L5 어댑터
- [x] Math / Pedagogy / Interaction / Animation / UI **5상태가 분리**되고 의존 방향이 **Math → … → UI 단방향**인가? — `test_visualization_state_separation.py` + import-linter 7계층 계약 CI 강제

## 단계 6. Math UI DSL `[진행 · 리스크]`

- [ ] **Core를 작게** 유지하나? UI·AI·렌더러·런타임 상태가 **Minimal Core로 새어들지** 않았나?
- [ ] DSL 12개 불변식이 **CI로 강제**되나?
- [ ] **자기진화(Lean4 Tier3) 보류**가 Phase 1 범위에서 옳은가, 아니면 DSL이 **"명세 생성기"에 머물러** 3대 핵심을 못 받치나? (보류의 **재검토 트리거 조건**은 무엇인가?)

## 단계 7. 렌더링 엔진 `[프로토타입]`

- [ ] **표현 ≠ 의미**: 렌더는 클라(Flutter/web/PDF)가 소비하고 **수학 로직이 클라로 새지** 않았나?(독립 코어 API)
- [ ] **Manim 동영상 보류**가 3대 핵심(시각화)을 약화시키지 않나? 정적 그래프만으로 Phase 1 충분한가, **재개 조건**은?

## 단계 8. AI 튜터 · Context `[진행·최우선]` — L3 라우터 / WH-1

- [ ] **⚠️ 전체 그래프 금지**: LLM에 **Minimal Reasoning Subgraph**(depth ≤ 2, max_nodes ≤ 12~20, max_tokens ≤ 3000)만 주나? 이 상한이 **context builder 코드에 실제로 박혀** 있나?
- [ ] traversal에 **visited set · timeout · token budget guard**가 있나?
- [ ] **2-Stage Context**(오개념 reactive 로딩)가 구현됐나, 초기 context에 오개념이 섞이나?
- [ ] 모든 학생 응답이 **PRM/도구(SymPy) 검증** 통과 후 제공되나? `verify_step`/`verify_answer`가 실제 배선됐나?
- [ ] **정답 즉답 금지 · Polya 우선**을 WH-1 전략단계(Lv2~3) 보류가 **깨지 않나**?

## 단계 9. 평가 · 개인화 `[구현 · 3대핵심③]` — BKT / IRT / Mastery

- [ ] 개인화가 "약점·오개념·행동 패턴"을 누적하나, **정답률·시간만** 보나? (우열 게임화 금지)
- [ ] 다개념 원자화 후 mastery 추정이 **원자 단위로 독립**되나?
- [ ] 행동영역(조건해석·경우분할·역추적·추론 — 수능 핵심)이 실제 태깅되나?

## 단계 10. 자동화 · 데이터 `[진행]`

- [ ] 콘텐츠 백본이 **법적 안전조합**(NCIC·공공누리 AI유형·AIHub 등)만인가? 교과서·평가원·EBS 본문이 **자체 동등문제**로 대체됐나?
- [ ] 동등문제 생성이 **SymPy 동치성 게이트**를 통과하나?
- [ ] 테스트 커버리지 70%+ 유지되나?

---

## 횡단 검문 (매 점검 공통 4문)

1. [ ] **5대 분리** 위반 없나 — Concept ≠ (Curriculum · Renderer · Prompt · Misconception), **AI ≠ 전체 그래프**
2. [ ] **7대 붕괴 연쇄**(노드폭발 → 관계폭발 → 순환참조 → 유지보수지옥 → 성능병목 → AI추론실패 → 교육일관성붕괴) 중 지금 **어느 징후**가 보이나
3. [ ] **단일 진실 원천**이 지켜지나 (특히 개념 vs 원자 그래프)
4. [ ] AI를 **답변기가 아니라 "구조 붕괴 감지기"**로 쓰고 있나

## 메타 질문 (각 단계 끝 필수)

> **"이 단계 구조가 실제 서비스에서 실패하는 이유를, 노드폭발·관계폭발·순환참조·유지보수·성능·AI추론실패·교육일관성붕괴 관점에서, 표면 표현이 아니라 인지 행동(cognitive action) 기준으로 분석하라."**

---

*출처: WhyMath 구축 플레이북 v1.0 — Part 1(5대 분리·핵심20·3대핵심) · Part 8(Context) · Part 10(10단계 로드맵) · Part 12(7대 붕괴·게이트).*
