# 계획서 200 「Phase 1 — EOS Core Contract」 재대조 (2026-09-16)

> **판정 기준: main `2520a27c`** (2026-09-15 23:45 UTC · 이 문서의 모든 판정은 이 커밋의 trunk 상태를 근거로 한다)
>
> **성격**: 재대조(조사) + 갭 등재. 초판은 `eos_phase1_plan_200_gap_review_2026-09-01.md`(2026-09-01·358줄)이며 **본 문서는 그것을 대체하지 않고 이어 쓴다** — 초판이 내린 판정과 Kiki 결정(§8 「지향성 참고본」)은 그대로 유효하고, 이 문서는 그 뒤 **2주간의 착지**를 반영한 시점 갱신이다.
>
> **왜 다시 하는가**: 2026-09-16 Kiki가 계획서 200 **원본 docx를 세션에 반입**하며 "항목별 반영여부 확인 + 항목을 순서대로 순차적으로 도입 완성"을 지시했다. 초판은 원본 없이 인용만으로 쓰였고(§31 ADR 매핑표 7칸이 그 사유로 비어 있었다), 원본 반입으로 비로소 채울 수 있게 된 칸이 있다.

---

## §0. 결론 3줄

1. **초판이 지목한 "진짜 갭 3건"은 전부 해소됐다.** `EOS-49`(Entity Version)·`EOS-78`(HIT 계측기)·`EOS-79`(Assessment 4층 경계)가 모두 done이고, 초판 시점에 없던 **데이터 무결성 게이트**(`OPS-55` 6종 CLI + CI 배선)와 **핵심 엔티티 19종 동결**(`canonical_entity_model_v1.md` · 80테이블 전수 귀속 기계 동결)이 추가로 착지했다.
2. **오늘 남은 구조 갭은 5건**이며 그중 계획서가 **Week 2의 성공 기준으로 직접 지목한 §18 단일 API 질의**가 가장 크다 — 라우트 97개 전건 확인 결과 0건이고, `Concept→Skill[]`·`→Misconception[]` 두 홉은 공개 API 자체가 없다. 나머지 4건은 §5 금지어 축의 **집행 부재**(계측기는 있으나 게이트가 아님), §27 검사 ①⑤ **강제 검사 0건**, §36 5개 숫자 **단일 화면 도구 0건**, 그리고 stale 사실 정정이다.
3. **"미충족"으로 보이지만 건드리면 안 되는 것이 그보다 많다.** 아래 §3이 그 목록이며, 전부 저장소가 **근거를 남기고 다르게 판정한 축**이다(ID 재설계·`related_to`·영어 이벤트 12종·디렉터리 물리 이동·Epic 재편·`remediation_strategy_ids`·RendererAdapter·ContentNormalizer). 계획서 문면만 보고 "없으니 만든다"로 가면 **작동 중인 어휘를 제2 어휘로 덮는다.**

---

## §1. 방법과 그 한계

- 판정 근거는 **실파일 경로·명령 출력·태스크 ID** 중 하나여야 한다. 문서 언급만으로 "충족"한 행은 없다.
- **"trunk 부재 ≠ 미구현"** 절차 준수 — 갭 판정 전 원격 브랜치·claim 대장(`refs/heads/harness-claims`)을 교차 조회했다. 이 클론은 착수 시점 shallow였고 `git fetch --unshallow origin`으로 전체 이력을 받은 뒤 판정했다(shallow 상태에서는 번호·이력 판정이 성립하지 않는다 — `backlog.py add`가 그 이유로 번호 제안을 거부했다).
- **"식별자 부재 ≠ 기능 부재"** 절차 준수 — 계획서가 제안한 *이름*으로 0건인 항목은 **역할로 재검색**한 뒤에 판정했다.
- enum·집합의 개수는 **멤버를 전건 열거**한 뒤에 셌다(절단 출력로 판정 금지 — 초판 §9-②가 `EventType` 11 vs 12를 틀린 경위가 이것이다).

**이 문서가 하지 않은 것(정직 표기)**: 실 PG에 붙어 데이터 건수를 재지 않았다. 코퍼스 수치(개념 437·엣지 581·Skill 27·오개념 843)는 `data/corpus/**`의 파일 실측이고, **prod DB의 실제 적재량과 같다는 보장은 이 문서에 없다.**

---

## §2. Gate 1 10조건 — 초판(09-01) 대비 변동

| # | 계획서 Gate 1 조건 | 09-01 판정 | **09-16 판정** | 변동 근거 |
|---|---|---|---|---|
| 1 | EOS Entity ID 체계 고정 | 충돌 | **충돌(유지) + 강화** | ID 어휘 충돌은 그대로(2026-08-17 결정이 전면 수용 거부). 다만 `canonical_entity_model_v1.md`가 **핵심 엔티티 19종 + 80테이블 전수 귀속**을 기계 동결(`test_canonical_entity_model_freeze.py` 4검사) — 계획서가 요구한 "고정"의 실질은 ID 표기가 아니라 이쪽에서 달성됐다 |
| 2 | Entity Version 규칙 고정 | **부분(진짜 갭)** | **충족** ✅ | `EOS-49` **done**. `concept_version` 테이블 착지(80번째 테이블) + `VersionStatus` 6종(DRAFT·IN_REVIEW·APPROVED·PUBLISHED·DEPRECATED·RETIRED — 계획서 5단계를 포함) + PUBLISHED payload 불변·PUBLISHED→DRAFT 금지 **plpgsql 트리거**(`20260914_0000_67cf48ad3bce`) |
| 3 | Subject Contract v1 확정 | 초과 달성 | **Provisional(라벨 정확)** | `EOS-91`이 상태 라벨을 Provisional로 명시하고 `EOS-92` 교차 과목 프로브가 **done**(Physics 15/15 ○·강등 0·Core 확장 0 — `subject_contract_cross_probe.md`). Frozen 승격은 **9/27 판정 대기**(게이트 `ARCH-41`) |
| 4 | Curriculum Contract 작동 | 충족 | **충족(유지)** | `curriculum_framework`·`curriculum_version`·`achievement_standard`·`UnitSpec`·`LearningObjective`. "Concept에 교육과정을 박아 넣지 말라"는 준수 — `schema/concept.py:136-143`이 과거 내장 필드 제거를 명시하고 재내장 차단 테스트가 있다 |
| 5 | Concept/Skill Graph 작동 | 충족·Skill 얇음 | **충족(유지)·Skill 여전히 27** | 개념 437·엣지 581(`concept_graph_v1`)·원자 백본 별도·`EdgeType` **6종 전건**(PREREQUISITE·COMPOSED_OF·ANALOGOUS_TO·EXTENDS·CONTRASTS·TRIGGERS_DISTRACTOR). Skill 27건 — `EOS-63` **타 세션 원격 claim 중**(착수 금지) |
| 6 | Problem/Misconception 연결 작동 | 충족 | **충족(유지)** | 오개념 843(M-id) + kebab 67 + `misconception_crosslink`·`_relation`. Problem→can_detect는 `Problem.distractor_map`이 담당 |
| 7 | Learner State 최소 모델 작동 | 충족 | **부분(하향 정정)** ⚠ | `l2/learner_state.py`는 **메모리 조립기**이고 영속 좌석 `user_state_snapshot`은 **writer 0**(`evidence_layer_boundary.md:131` 전수 grep 실측). `recent_activity[]` 없음. 초판이 "충족"으로 본 것은 `*MasteryHistory` 테이블 실재 축이며, 그 축은 지금도 맞다 |
| 8 | EOS Event Schema 실제 저장 | 충족·어휘 충돌 | **충족(유지)·어휘 충돌 유지** | `attempt_event`(hypertable) + `EVENT_DATA_CONTRACT` 7종. `EventType` **12종 전건**. 계획서 영어 12종은 제2 어휘 제안이며 초판 판정(부분 채택 — 필요한 값은 기존 enum에 추가) 유지 |
| 9 | Math Adapter Core와 분리 | 부분(경유 잔여 **2건**) | **부분 · 잔여 1건으로 감소** ⬇ | 직접 CORE→ADAPTER import **0건**(스캔 실측: CORE 319모듈·sympy 0·수학어휘 0.9/kloc vs ADAPTER 27.0/kloc). `EOS-89`가 기존 2건을 0으로 줄였고 `EOS-86`이 신규 1건 추가 → **현재 1건**(`l4.solution_coaching -> composition`). 재확인 지점은 **G1(9/27)** |
| 10 | Contract Test CI 자동 검증 | 충족·이름 다름 | **충족(유지)·검사 2건 공백** | `tests/contract`·`tests/architecture` 디렉터리는 없고 역할은 파일명 규약 + `tests/infra`가 수행. 계획서 §27 6검사 중 **①⑤만 강제 검사 0건**(§4-D) |

**분포 변화**: 충족·초과 6 → **6**(내용 이동: #2가 부분→충족, #7이 충족→부분) · 부분 1 → **3** · 충돌 3 → **2**.

---

## §3. 건드리면 안 되는 것 — 이미 다르게 판정된 축 8건

계획서 문면으로는 "미충족"이나, **저장소가 근거를 남기고 반대로 판정한** 항목이다. 재론하려면 그 결정을 뒤집는 근거가 먼저 필요하다.

| # | 계획서 요구 | 저장소 판정 | 근거 |
|---|---|---|---|
| N1 | ID 재설계(`concept.math.quadratic-function` 등) | **미채택** | 2026-08-17 `eos_identity_layer_011_1_decision.md`가 부분 수용·부분 거부로 판정 완료. 영향 4,000+ 키 + crosswalk 게이트 코드 동결 |
| N2 | 관계 어휘에 `related_to` | **미채택** | CLAUDE.md **절대 금기** 직접 위반(관계 폭발 방어 — traversal 사용 금지) |
| N3 | 영어 이벤트 12종 | **부분 채택** | 계약 이중화 회피. 필요한 생애주기 값은 기존 `EventType`에 **값 추가**로 |
| N4 | `eos/core\|contracts\|adapters\|apps` 물리 이동 | **미채택** | 선언 §1.3-③ 「물리 대이동 보류」. 경계선이 계층 사이가 아니라 `l3` **한가운데**를 지나므로(CORE 39 : ADAPTER 39 동거) 디렉터리로 갈리지 않는다. 대안(`EOS-65` 논리 배정표 64항목)이 이미 착지 |
| N5 | ADR 트리 / Epic 13개 재편 | **제4안 채택** | 2026-09-05 Kiki 결정 — ADR 계열은 저장소 하나만 유지하고 계획서 번호는 **주제 목록**으로 재정의. Epic은 미채택(`selector.py`가 Epic을 읽지 않는다) |
| N6 | Misconception `remediation_strategy_ids` | **의도적 제외** | `misconception_relation.py:23-26` — `repaired_by`를 `intervene.py` 결정트리와의 **이중 진실원천 위험**으로 명시 제외 |
| N7 | Subject Contract의 `RendererAdapter` | **의도적 미채택** | `subject_adapter.py:262` — `render_equation()`·`parse_latex()`는 전부 Math 전용. `VisualizationStyle` 16종이 전량 수학 어휘라 중립 반환 타입 재설계 전엔 계약 불가 |
| N8 | Subject Contract의 `ContentNormalizer` | **미채택** | `ProblemStatement`가 "Core가 들고 있으나 해석하지 않는" **불투명 봉투**로 대체. `eos_opaque_payload_gate.py`가 Core의 payload 값 해석을 AST로 차단 |

**§34 「하지 말아야 할 것」 5종은 전부 저장소 결정과 일치한다** — Graph DB 전환 금지(2026-08-03 Neo4j 런타임 미도입)·완벽 Ontology 금지(EdgeType 6종)·Microservices 금지(modular monolith)·Agent 후순위·선행 추상화 금지. **채택 비용 0이고 재확인만 하면 된다.**

---

## §4. 오늘 남은 진짜 갭 5건 — 등재·착수 대상

| # | 계획서 위치 | 갭 | 실측 | 태스크 |
|---|---|---|---|---|
| **A** | §18 (Week 2 핵심 테스트) | **성취기준 → Concept[] → Skill[] → Problem[] → Misconception[] 를 한 호출로 답하는 API 0건** | 라우트 **97개 전건** 확인. 최소 4회 조합 필요, `Concept→Skill[]`·`→Misconception[]` 두 홉은 공개 API 자체가 없다. 단 5홉 전부 재사용 가능한 L1 좌석 실재(`get_alignments` 3축·`skill_graph/resolve`·`problem_concept`·`misconception_catalog`) | `EOS-05` |
| **B** | §5 (금지어 lint) | **계측기는 있으나 게이트가 아니다** | `eos_core_adapter_boundary_scan.py`가 docstring에 *"게이트가 아니라 계측기"*라 자인하고 위반으로 exit 1을 내지 않으며 `.github/`에서 호출 **0건**. 계획서 7어휘 중 `desmos`·`equation_solver`는 `MATH_TOKEN_RE`에 **없다** | `EOS-04` |
| **C** | §27 검사 ① | **모든 Problem이 최소 1개 Skill과 연결**을 강제하는 검사 0건 | 가장 가까운 `attempt_skill_event_reach_report.py`는 *채점 이력*의 비율 리포트이고 스스로 *"게이트가 아니다 — 비율이 0%여도 exit 1을 내지 않는다"*고 적는다 | `EOS-07` |
| **D** | §27 검사 ⑤ | **published인데 version 행이 없다**를 검사하는 것 0건 | `VersionStatus`·`concept_version`·`current_published_version_id` 전부 실재하나 이 불변식 검사는 없다. 더욱이 `ConceptVersion(...)` 생성이 `src/` 전체 **0건**(정의부만) — 버전 테이블이 아직 **빈 좌석**이다 | `EOS-07` |
| **E** | §36 (5개 숫자) | **5개를 한 화면에 내는 도구 0건** | Data integrity만 충족(`OPS-55`). EOS migration %는 분류 분포만 내고 *이전 완료율* 축이 없다. Broken dependency는 서로 다른 3축이 나눠 갖는다. **Contract coverage·Vertical Slice pass %는 저장소에 정의조차 없다** | `EOS-08` |

### stale 사실 3건 (정정 대상)

| 위치 | 현재 문안 | 실측 |
|---|---|---|
| `eos_core_adapter_boundary_scan.py` 리포트 출력 | *"아무도 막고 있지 않은 상태에서의 0이다 — 집행은 EOS-67"* | `EOS-67`은 **2026-08-31 done**. import-linter 계약 3건이 CI `backend` 잡(`ci.yml:373-374` `lint-imports`)에서 **매 PR 판정**하고, 그 배선 자체를 `test_eos_boundary_contract_wiring.py:148`이 동결한다. 안전한 방향의 오류지만 G1 판정 근거로 인용되면 **집행을 과소 보고**한다 |
| `subject_adapter.py:3` 외 | *"pending cross-subject probe"* + `ADR-004` 관련 줄의 `EOS-92 (todo)` | 프로브는 **실행됐다** — `EOS-92` done · `subject_contract_cross_probe.md` 실재 · Physics 15/15 ○. `Provisional` **라벨 자체는 여전히 정확**하다(Frozen 승격이 9/27 판정 대기이므로). 정정 대상은 "프로브 미실시"로 읽히는 문면뿐이며, 이 파일은 계약 동결 테스트와 **9/27 게이트(`ARCH-41`)의 판정 대상**이라 본 태스크가 건드리지 않는다 — 여기 기록만 남긴다 |
| `adr/README.md` 매핑표 | 7칸 "미확인" + 사유 *"계획서 100 원본은 Kiki 보유이며 저장소에 반입돼 있지 않다"* | 그 표는 **계획서 100 §3.16** 축이므로 200 원본이 반입돼도 채워지지 않는다. 대신 **계획서 200 §31의 10주제 표를 신설**한다(주제 목록 자체가 다르다 — §5) |

---

## §5. 계획서 200 §31 ADR 10주제 ↔ 저장소 정본 (원본 반입으로 신규 작성)

계획서 100 §3.16과 **주제 목록이 다르다.** 200은 Entity Versioning·Curriculum Mapping·Concept/Skill separation·Problem/Answer·Misconception Model을 갖고, 100은 AI Gateway·Math AST·Knowledge Graph·Content Version·Assessment Architecture를 갖는다. 따라서 기존 매핑표에 덧쓰지 않고 **별도 표로 신설**한다(정본은 `docs/architecture/adr/README.md`).

| 계획서 200 §31 주제 | 저장소 정본 | 상태 |
|---|---|---|
| ADR-001 EOS Core Boundary | `docs/architecture/eos_core_adapter_boundary.md` + `eos_core_adapter_boundary_scan.py`(`BOUNDARY_MAP` 64항목) | 충족 — ADR 형식은 아니나 전수 배정으로 정본화(`EOS-65`) |
| ADR-002 Entity ID Strategy | `docs/standards/eos_identity_layer_011_1_decision.md` + [`ADR-003`](../architecture/adr/ADR-003-subject-prefix-is-convention-not-entity.md) | 충족 — 2026-08-17 판정(부분 수용·부분 거부) + 접두사 규약 ADR |
| ADR-003 Entity Versioning | `docs/architecture/44_eos_version_management.md` + `schema/version_header.py`(`VersionStatus` 6종) | 충족 — `EOS-44`(설계)·`EOS-49`(`concept_version` 착지) |
| ADR-004 Subject Contract | [`ADR-004`](../architecture/adr/ADR-004-subject-contract-v1-provisional.md) | **Provisional** — 9/27 Freeze 판정 대기 |
| ADR-005 Curriculum Mapping | `docs/architecture/eos_curriculum_semantic_backbone_adr.md` | 충족 — Overlay 방식 채택(개념 백본 위에 Framework/Version/Alignment 레이어) |
| ADR-006 Concept/Skill separation | `docs/architecture/canonical_entity_model_v1.md` §1-5·§1-6 | 충족 — *"Concept이 무엇을 아는가라면 Skill은 무엇을 할 수 있는가"* 이다/아니다 쌍으로 판정 가능하게 정의 |
| ADR-007 Problem/Answer Contract | `docs/architecture/adr_answer_form_contract.md` + `schema/answer_form.py` | 충족 — `EOS-28` |
| ADR-008 Misconception Model | `docs/standards/crosswalk_gate_contract.md` + `04b`/`04c`/`04e` | 충족 — kebab↔M-id 승인·적재 게이트가 **코드 동결** |
| ADR-009 Event Architecture | [`ADR-001`](../architecture/adr/ADR-001-event-storage-postgresql-first.md) + `schema/event_data_contract.py` | 충족 — 저장소 선택 + payload 계약 단일 진실원 |
| ADR-010 Learner State | `docs/architecture/evidence_layer_boundary.md`(`EOS-79`) + `docs/architecture/02_learner_model.md` | 충족(정본) · **집행 없음**(문서 §3이 스스로 명시 — 새 모델을 엉뚱한 층에 넣어도 CI는 통과한다) |

**10주제 전부 저장소 정본이 실재한다.** 계획서가 "작성할 가치가 크다"고 한 10건은 형식(ADR 파일)이 아닌 형태로 이미 결정돼 있으며, 새로 쓸 ADR은 없다.

---

## §6. §1의 3축 정의로 본 "1과목 완성" — 09-16 기준

초판 §8.2가 채택한 대로, 계획서 §1은 "EOS 1과목 완성"의 **조작적 정의**다. 그 정의로 오늘 재실측하면:

| 축 | 09-01 | **09-16** | 근거 |
|---|---|---|---|
| **시스템** (Core → Subject Contract → Math Adapter → WhyMath 경계가 코드에 존재) | 완료 | **완료(유지)** — 단 잔여 1건 | 직접 위반 0 · 경유 잔여 2→**1건** · import-linter 3계약이 매 PR 판정 |
| **학생** (회원 → 진단 → 추천 → 풀이 → 채점 → 오개념 → 숙련도 → 다음 추천) | 대체로 서 있음 | **대체로 서 있음(유지)** — 2단계 공백 | `test_e2e_vertical_slice_integration.py`가 실 PG로 관통(CI `ci.yml:1624`). 단 **교육과정/Objective 선택 미관통**·**오개념 판정 미관통**(테스트 내 misconception 참조 2건은 전부 cleanup DELETE) |
| **관리자** (교육과정 → … → 검수 → 승인 → 버전 → 배포) | 거의 비어 있음 | **변동 없음** | `ADMIN-04·05·06·07·12`·`EOS-50` **6건 전부 여전히 todo p3**. 2026-09-01 Kiki 결정 (가)에 따라 **판정 대상이 아니라 지표 생산의 수단**이므로 승격하지 않는다 |

**초판 §8.5의 결정 (가)를 유지한다** — 12/31 판정 기준은 선언(`ops/validation_scorecard.py` Hard Gate F-Ⅰ~Ⅴ + KPI 12종)이고 "1과목 완성"은 그 위의 목표 서사다. §4의 갭 5건은 **선언의 판정 기준을 바꾸지 않는다**(구조·계약 축이며 스코어카드 지표를 건드리지 않는다).

---

## §7. 처분

| 갭 | 태스크 | 우선도 | 처분 |
|---|---|---|---|
| A (§18 단일 질의) | `EOS-05-standard-learning-map-single-query` | p1 / EOS **P1** | **착수** — 계획서가 Week 2 성공 기준으로 지목한 유일한 미충족 구조 항목 |
| B (§5 게이트화) | `EOS-04-core-math-vocabulary-ratchet-gate` | p2 / P2 | **착수** |
| C·D (§27 검사 ①⑤) | `EOS-07-contract-test-problem-skill-and-published-version` | p2 / P2 | **착수** |
| E (§36 5개 숫자) | `EOS-08-phase1-five-numbers-reporter` | p3 / P2 | 착수 — `EOS-07` 선행(Contract coverage의 분모가 §27 검사 집합에서 나온다·`depends_on` 집행) |
| stale 정정 | `EOS-03`(본 문서) | p2 / P2 | 본 태스크에서 처리 |
| Skill 27건 얇음 | `EOS-63` | — | **착수 금지** — 타 세션 원격 claim 중(`claude/status-f6qz0c`) |
| `Provisional` 라벨 | `ARCH-41` / 게이트 | — | **착수 금지** — 9/27 G1 판정 대상 |

---

**작성**: 2026-09-16 · 판정 기준 main `2520a27c` · 태스크 `EOS-03-plan200-reverify-and-adr-mapping`
**정본 관계**: 선언(`eos_transition_declaration_2026-08-30.md`) > 초판(`eos_phase1_plan_200_gap_review_2026-09-01.md`) > 본 문서. 충돌 시 위쪽 우선이며, 선언을 바꾸는 것은 Kiki 판단이다.
