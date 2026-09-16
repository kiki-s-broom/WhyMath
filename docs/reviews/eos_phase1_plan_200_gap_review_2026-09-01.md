# 계획서 200 「Phase 1 — EOS Core Contract」 ↔ 저장소 실측 대조 (2026-09-01)

> **📌 후속 재대조 고지 (2026-09-16 추가·본문 무수정)**: 이 문서 이후 2주간 `EOS-49`·`EOS-78`·`EOS-79`·`OPS-55`가 착지해 **§5가 지목한 진짜 갭 3건이 전부 해소**됐다. 오늘 시점 판정은 `eos_phase1_plan_200_reverify_2026-09-16.md`(판정 기준 main `2520a27c`)가 이어 쓴다 — 본 문서의 판정과 Kiki 결정(§8)은 그대로 유효하고, 재대조본은 그것을 **대체하지 않고 갱신**한다.

> **📌 스냅샷 고지 (2026-09-05 추가·본문 무수정)**: 이 문서는 **2026-09-01 시점 스냅샷**이다. 여기서 Subject Contract v1을 "확정"·"초과 달성"·"합격"으로 적은 판정은 그 시점의 것이며, **정본은 계약 모듈** `src/backend/whymath_backend/schema/subject_adapter.py`다 — 2026-09-05 `EOS-91`로 상태가 **Provisional (pending cross-subject probe 9/27)**로 명시됐다. 본문은 기록 보존을 위해 손대지 않았다.


> **대상 문서**: `200_Phase 1 — EOS Core Contract 상세 실행계획`(Kiki 제공·저장소 외부).
> 기준일 2026-08-27 작성 · 대상기간 2026-09-07~09-27 · Gate 1 10조건 · Week 1~3 · §1~§40.
>
> **대조 시점**: `claude/review-2hi01y` @ `b1cd138f`(#946) · 2026-09-01 · 원격 브랜치 38 · 최신 PR #953.
> **성격**: 조사 전용(코드 변경 0). 대장 변경 없음 — 신규 태스크 등재는 §7의 판단 대기 항목이 정해진 뒤.
>
> **선행 문서와의 관계**: 저장소는 이미 계획서 006·100을 흡수한 정본
> `docs/strategy/eos_transition_declaration_2026-08-30.md`(선언)와 그 대조
> `docs/reviews/eos_source_docs_gap_review_2026-08-31.md`(계획서 006·100 축)를 가진다.
> 본 문서는 그 다음 권(200 = Phase 1)을 **같은 방법으로** 되짚는다.

---

## §0. 결론 3줄

1. **문서의 Gate 1 10조건 중 6건은 이미 충족 또는 초과 달성**, 2건은 부분, **2건은 "미완"이 아니라 어휘 충돌**이다. 특히 문서가 Phase 1의 3주를 걸어 만들려는 **Subject Contract와 Core→Math 경계 분리는 2026-08-31에 이미 착지**했고(`EOS-66`·`EOS-67`·`EOS-69`), 경계의 **직접 import 위반**은 오늘 실측 **0건**이다(합성 루트 경유 잔여 2건은 계약에 명시 예외로 남아 G1에서 재확인 — §2 행 9). 선행 리뷰가 006·100에 내린 진단("첨부 문서가 저장소를 보지 않고 쓰였다")이 200에도 그대로 성립한다.
2. **가장 큰 문제는 미완이 아니라 전제 충돌 3건**이다 — ⓐ 12/31의 정의(문서=출시일 / 선언=내부 검증 판정일) ⓑ 같은 날짜(9/27)에 **서로 다른 Gate 1** ⓒ 주차 번호 1칸 어긋남. 셋 다 문서를 그대로 실행하면 **선언이 최우선으로 못박은 축(AI 콘텐츠 생산 가능성·HIT)이 9월 계획에서 통째로 빠진다.**
3. 문서가 **옳게 짚은 진짜 갭은 3건**(Entity Version 규칙 미착지 · Skill 그래프 27건으로 얇음 · 추천 이유코드 부분)이며, **되돌리기 비싼 제안 5건**(ID 재설계·이벤트 어휘·디렉터리 물리 이동·ADR 트리 신설·Epic 재편)은 이미 저장소가 근거를 남기고 판정한 축을 다시 여는 것이라 채택 전 명시적 결정이 필요하다.

---

## §1. 방법

- 판정 근거는 **실파일 경로·명령 출력·태스크 ID** 중 하나여야 한다. 문서 언급만으로 "충족"한 행은 없다.
- **"trunk 부재 ≠ 미구현"** 절차 준수: 갭 판정 전 `backlog/tasks/**`(491건)·원격 브랜치 38을 교차 조회했다.
- **"식별자 부재 ≠ 기능 부재"** 절차 준수: 문서가 제안한 *이름*으로 0건이 나온 항목(이벤트 12종 등)은 **역할로 재검색**한 뒤에 판정했다. 재검색으로도 0인 항목만 갭이다.
- 재현 명령:

```bash
python3 scripts/analysis/eos_core_adapter_boundary_scan.py          # CORE→ADAPTER 위반
grep -n "importlinter" -A6 src/backend/pyproject.toml               # 정적 계약 3건
sed -n '1223,1275p' src/backend/whymath_backend/schema/enums.py     # EventType 정본
sed -n '994,1020p' src/backend/whymath_backend/schema/enums.py      # EdgeType 정본
python3 scripts/harness/backlog.py next --n 500 --json              # 전건(절단 금지)
```

---

## §2. Gate 1 10조건 대조 (문서 §2)

| # | 문서의 Gate 1 조건 | 판정 | 실측 근거 |
|---|---|---|---|
| 1 | EOS Entity ID 체계 고정 | **충돌** | 정본이 **이미 있다**: concept `math.<area>.<slug>` · skill `skill.<slug>`(`data/corpus/skill_graph_v1/graph.json`) · 오개념 `M0425` + kebab crosswalk. 유사 제안은 2026-08-17 `docs/standards/eos_identity_layer_011_1_decision.md`가 **부분 수용·부분 거부**로 판정 완료. 문서 §7의 `concept.math.quadratic-function`은 접두 순서가 **반대인 제3의 어휘** — §4-A 참조 |
| 2 | Entity Version 규칙 고정 | **부분(진짜 갭)** | `EOS-44` done(설계·foundation schema)·`EOS-72` done(ContentLifecycleState 배선/폐기 판정). 그러나 `EOS-49`(ConceptVersion 계약)는 **todo·priority 3**이고 `concept_node`에 `version` 컬럼이 없다(`review_status` reviewed/pending 2값뿐). 문서 §8의 지적("엔티티마다 별도 버전 시스템을 만들지 말라")은 **유효한 경고** |
| 3 | Subject Contract v1 확정 | **초과 달성** | `EOS-66` done — `schema/subject_adapter.py`가 **2층 계약**(필수층 3메서드 + 선택층 `verification_capabilities.py` Protocol 8종). 계약 표면은 `test_subject_adapter_two_tier_contract.py`가 **기계 동결**. 문서 §9의 5분할 제안보다 세분화가 앞서 있다 |
| 4 | Curriculum Contract 작동 | **충족** | `curriculum_framework`·`curriculum_version`·`curriculum_entry` 3모델 + `api/curricula.py`·`api/alignments.py`. 문서 §13이 경고한 "Concept에 교육과정을 박아 넣지 말라"는 **이미 준수**(`concept_standard_link` 별도 테이블 + `standard_codes` 코드만) |
| 5 | Concept/Skill Graph 작동 | **충족·단 Skill 얇음** | 개념 437 · 원자 백본 2,683노드/2,210엣지 · **Skill 27건**. `EdgeType` 6종 정본(PREREQUISITE·COMPOSED_OF·ANALOGOUS_TO·EXTENDS·CONTRASTS·TRIGGERS_DISTRACTOR). 문서 §14의 5종 제안과 **어휘 불일치** + `related_to`는 CLAUDE.md 명시 금지 — §4-B |
| 6 | Problem/Misconception 연결 작동 | **충족** | 오개념 843건(M-id) · kebab 64 · `misconception_catalog`/`_crosslink`/`_hypothesis`/`_relation` 4모델. 승인·적재 게이트는 `docs/standards/crosswalk_gate_contract.md`가 **코드 동결** |
| 7 | Learner State 최소 모델 작동 | **충족** | `ConceptMasteryHistory`·`SkillMasteryHistory`(append-only 이력). 문서 §23이 "Digital Twin 불요·Contract만"이라 한 수준을 이미 넘는다 |
| 8 | EOS Event Schema 실제 저장 | **충족·어휘 충돌** | `attempt_event`(TimescaleDB hypertable) + `evidence_event`·`hint_usage`·`review_timer_event` + `EVENT_DATA_CONTRACT`(payload 단일 진실원). `EventType`은 **한국어 12종**(풀이 단계축 11 + `EOS-57`이 추가한 `문제시도`). 문서 §22의 영어 12종은 전 저장소 **0건** — 역할 재검색 결과 대응물이 전부 실재하므로 갭이 아니라 **제2 어휘 제안** — §4-C |
| 9 | Math Adapter Core와 분리 | **부분 달성** | `EOS-69` done. **직접** CORE→ADAPTER import는 오늘 실측 **0건**(CORE 305모듈·sympy import 0·수학어휘 0.8/kloc vs ADAPTER 34.3/kloc)이고 `EOS-67` 계약 3건이 CI lint 스텝에서 매 PR 판정한다. **다만 0은 "직접 간선" 기준이다** — 합성 루트 경유 잔여 **2건**(`l3.pedagogy.slot_generator`·`l3.render.adapters` → `whymath_backend.composition`)이 7계층 계약의 `ignore_imports`로 명시 예외돼 있다. `EOS-69` ⑩·경계 문서 §4.1이 *"위반이 없어진 게 아니라 9 → 2로 작아졌다"*고 적었고 재확인 지점은 **G1(9/27)**이다 — §3-B 참조 |
| 10 | Contract Test CI 자동 검증 | **충족·이름 다름** | `tests/contract`·`tests/architecture` 디렉터리는 **없다**. 역할은 ① import-linter 3계약 ② `tests/infra` 배선 동결 ③ `declared_unwired_audit`(선언≠배선 4축 정적 감사) ④ 결함주입 강등전 게이트 8종 ⑤ E2E 관통 슬라이스 잡이 수행. 문서가 요구한 검사(§27 6항·§28 무결성 7항)보다 **강하다** |

**분포**: 충족·초과 **6** · 부분(진짜 갭) **1** · 어휘 충돌 **3**(1·5·8).

> **핵심**: 문서는 Phase 1 3주를 "Core Contract를 만드는 기간"으로 설계했으나, **Gate 1이 요구하는 것의 대부분은 이미 서 있다.** 그 3주를 그대로 쓰면 이미 있는 것을 다시 만들거나, 더 나쁘게는 **작동 중인 어휘를 제2 어휘로 덮는 데** 쓴다.

---

## §3. 전제 충돌 3건 — Kiki 판단이 필요한 항목

### A. 12/31의 정의 (가장 중요)

| | 문서 200 | 저장소 정본 |
|---|---|---|
| 12/31 | **출시일** — "Math EOS v1.0 출시" | **내부 검증 판정일** — 앱스토어·결제·마케팅·CS는 전부 2027 범위 (선언 §0-2) |
| 12월 목표 | 제품 완성 | **Go / Conditional Go / No-Go 판정** (선언 §0-4) |
| 최우선 축 | 학습 폐쇄루프 완성 | **AI 콘텐츠 생산 가능성** — "출시 등급 CU 1건의 인간 개입 시간(HIT) 중앙값 4분 미만인가". **폐쇄루프는 목적이 아니라 계측기로 강등**되어 깊이앵커 1개에서만 완결 (선언 §0-3) |

선언은 근거를 남긴 **의도적 재정의**다(2026-08-30·PR #904, 값 일치는 `test_declaration_canon_consistency.py`가 기계 동결). 문서 200은 그 재정의 **이전**의 전제 위에 서 있다.

이 충돌은 산술적으로 조정되지 않는다. 폐쇄루프를 12월 목표로 되돌리면 HIT·실패코드 측정이 부차가 되고, 그 반대도 마찬가지다. **먼저 정해야 하는 것은 Phase 1 주간계획이 아니라 이 한 줄이다.**

### B. 같은 날짜(9/27), 서로 다른 Gate 1

| | 문서 200의 Gate 1 | 저장소 G1 (선언 부록 E) |
|---|---|---|
| 조건 | Core Contract **10조건** | **3조건** — ① 앵커 1개 E2E ② **HIT·실패코드 이벤트 적재** ③ Core→Math 정적 의존 0 |
| 성격 | 구조 계약의 완성도 | 계측 가능한 파이프라인 |
| 교집합 | 문서 #9 ↔ 저장소 ③ (**직접 간선은 0 · 합성 루트 경유 2건 잔여**) | |

**문서의 Gate 1에는 HIT·실패코드 축이 통째로 없다.** 그것이 선언의 최우선 목표(②)이자 12/31 판정의 유일한 재료인데, 문서대로 9월을 운영하면 **G1 통과 여부를 잴 계측기가 9/27까지 안 선다.** 반대로 저장소 G1에는 Curriculum·Learner·Recommendation 계약 조건이 없다 — 다만 §2가 보였듯 그것들은 이미 작동하므로 실질 손실은 작다.

`EOS-69`가 남긴 잔여의 **재확인 지점도 "G1(2026-09-27)"**로 적혀 있어, 저장소는 이미 저장소판 G1을 참조하는 코드·문서를 갖고 있다. 게이트 정의를 문서판으로 바꾸면 그 참조들이 전부 결정 불가가 된다.

### C. 주차 번호 1칸 어긋남

| 기간 | 문서 200 | 저장소 선언 |
|---|---|---|
| 8/31~9/6 | (Phase 0 꼬리) | **W1** — "헌법 고정" |
| 9/7~9/13 | **Week 1** | **W2** — "되돌릴 수 없는 스키마 확정" |
| 9/14~9/20 | Week 2 | W3 |

이미 대장에 흔적이 있다 — `EOS-57` 제목: *"problem_attempted skill_ids[] 복수 영속 — 소급 불가 스키마(**W2** 되돌릴 수 없는 결정 ①)"*. 문서를 그대로 쓰면 "W2 태스크"가 문서의 Week 2(9/14~)로 읽혀 **일주일 밀린다.** 무해해 보이지만 소급 불가 스키마 결정의 착지 시점이 걸린 항목이다.

---

## §4. 되돌리기 비싼 제안 5건 — 채택 시 실제 비용

### A. ID 체계 재설계 (§7 — Week 1 안에 "반드시 고정")

문서 제안 vs 실재:

| 대상 | 문서 §7 | 저장소 실재 | 영향 규모 |
|---|---|---|---|
| 개념 | `concept.math.quadratic-function` | `math.<area>.<slug>` (접두 순서 반대) | 개념 437 + 원자 2,683 + 엣지 2,210 |
| Skill | `skill.math.factor-quadratic-expression` (subject 세그먼트 있음) | `skill.polynomial-arithmetic` (없음) | 27 |
| 오개념 | `misconception.math.quadratic.zero-product-error` | `M0425` + kebab 64 | 843 + **코드 동결된 crosswalk 게이트** |

문서 자신이 §7에서 "내부 PK는 UUID, 외부는 stable EOS ID를 하나 더 둔다"고 했는데 — **저장소는 이미 그 구조다.** 재설계가 사는 것은 *표기 통일*뿐이고, 잃는 것은 843건 오개념 crosswalk 게이트 계약과 2,683노드 백본의 키다. **2026-08-17 결정이 이미 "전면 수용 거부"로 판정한 축**이므로, 다시 열려면 그 결정을 뒤집는 근거가 필요하다.

### B. 관계 어휘 5종 (§14)

문서: `prerequisite_of` · `part_of` · `related_to` · `equivalent_to` · `contrasts_with`

저장소 `EdgeType`(6종)과 3건은 대응하나(`PREREQUISITE`·`COMPOSED_OF`·`CONTRASTS`), **`related_to`는 CLAUDE.md 절대 금기**다 — *"`similar_to`/`related_to`를 traversal에 사용 금지"*(관계 폭발 방어). 문서는 "제한할 수 있습니다"라는 완화된 표현을 쓰지만, 핵심 5종에 넣는 순간 그것이 정본이 된다. **`equivalent_to`는 저장소에 대응물이 없다** — 신설하려면 `ANALOGOUS_TO`/`EXTENDS`와의 경계를 먼저 정의해야 한다.

### C. 이벤트 어휘 12종 (§22)

문서의 12종(`session_started`~`session_completed`)은 전 저장소 **0건**이다. 그러나 역할로 재검색하면 대응물이 전부 있다:

| 문서 §22 | 저장소 실재 |
|---|---|
| problem_attempted / answer_submitted | **`EventType.문제시도`**(`EOS-57` — 이름만 다른 *직접* 대응) + `attempt_event`(hypertable) + `AnswerSubmission`(`EOS-32` done) |
| answer_evaluated | `검산결과` EventType + `EVENT_DATA_CONTRACT` |
| hint_requested / (hint 제공) | `힌트요청`·`힌트제공` EventType + `hint_usage` |
| misconception_detected | `misconception_hypothesis` |
| mastery_updated | `ConceptMasteryHistory`·`SkillMasteryHistory` |

즉 **갭이 아니라 제2 어휘 제안**이다. 채택하면 payload 계약(`EVENT_DATA_CONTRACT`)·휴면 enum 관리·`analytics_event` 정규화가 전부 두 벌이 된다. 필요한 것이 "생애주기 축 이벤트"라면 기존 `EventType`에 **값을 추가**하는 편이 계약을 하나로 유지한다.

### D. 디렉터리 물리 이동 (§4·W1-1의 `eos/core|contracts|adapters|apps` 트리)

선언 §1.3-③가 **"물리 대이동 보류"**로 이미 판정했고, `EOS-65`가 그 대안(현행 `l1`~`l6`에 Core/Adapter/Infra **표기** 배정)을 실행해 `docs/architecture/eos_core_adapter_boundary.md`로 착지시켰다. 문서 자신도 "중요한 것은 디렉터리명이 아니라 Dependency Direction"이라 적었는데 — **그 Dependency Direction은 이미 기계가 강제한다**(import-linter 3계약·위반 0). 물리 이동은 위반 수를 줄이지 못하고 850+ PR 분량의 blame·미머지 브랜치 38개의 충돌만 만든다.

### E. ADR 10건 트리 신설 (§31) · Epic 13개 재편 (§29)

- **ADR**: 선행 리뷰가 `docs/adr/` 신설을 **"의도적 미채택"**으로 기록했다(이중 진실원천 방지). 저장소의 결정 기록 정본은 `MEMORY.md` 결정 로그 + `docs/architecture/*_adr.md` + 태스크 acceptance다. 문서가 든 10개 주제 중 **ADR-001·004·006·007·008은 이미 그 형태로 존재**한다(경계 문서·subject_adapter docstring·crosswalk 계약 등).
- **Epic**: 작업 정본은 `backlog/`(491태스크·`backlog.py`가 착수 후보를 계산)다. Epic 축을 새로 만들면 **대장이 둘**이 되고, `selector.py`는 Epic을 읽지 않는다(2026-09-01 등재 규칙: "선행 조건을 산문에만 적고 대장에 집행하지 않기 금지"의 같은 함정).

---

## §5. 문서가 옳게 짚은 것 (진짜 갭 3건)

| # | 문서 위치 | 갭 | 실측 |
|---|---|---|---|
| **G-1** | §8 Version 규칙 | Entity 공통 버전·상태 전이가 **미착지** | `EOS-49`(ConceptVersion 계약) **todo·priority 3**. `concept_node`에 `version` 없음. 문서의 경고("엔티티마다 별도 버전 시스템 금지")가 정확히 이 상태를 가리킨다. **우선도 재검토 후보** |
| **G-2** | §15 Skill Graph | Concept/Skill 분리는 됐으나 **Skill이 27건**(개념 437 대비) — "숙련도 추정"의 분모가 얇다 | `SkillNode` 실재·`SkillMasteryHistory` 실재. 그러나 `EOS-63`(attempt_event.skill_ids 소비 전환) **todo**이며 **타 세션 원격 claim 중**(`claude/status-f6qz0c`) — 병렬 착수 금지 |
| **G-3** | §25 Recommendation reason_code | 추천 이유의 **구조화가 부분** | `l6/blueprint/assembly.py:519`에 `reason` Literal 실재. 다만 추천 응답 전반의 `reason_code`+`evidence`+`score` 3종 세트는 아님. CLAUDE.md "작동한 비율" 원칙(알고리즘이 실제로 작동했는지를 응답이 말해야 한다)과 같은 방향의 지적 |

**§34 "하지 말아야 할 것" 5종은 전부 저장소 결정과 일치한다** — ① Graph DB 전환 금지 = 2026-08-03 Neo4j 런타임 미도입 확정 ② 완벽 Ontology 금지 = EdgeType 6종 제한 ③ Microservices 금지 = 현행 modular monolith ④ Agent 후순위 ⑤ 선행 추상화 금지 = `EOS-66`이 `explain`을 v1에서 뺀 바로 그 근거. **이 절은 문서에서 가장 값어치 있는 부분이고 채택에 비용이 없다.**

---

## §6. 사실 오류·stale 수치

| 문서 진술 | 실측 | 성격 |
|---|---|---|
| "현재 시점인 2026년 8월 27일" | 오늘 2026-09-01 — **Phase 0 잔여 5일** | 작성일 기준·정보성 |
| "850 PR 누적" (§30) | 최신 **#953** | stale(작성 후 100+) |
| "기존 120여 개 기능" (§1) | 기계 장부 `backlog/inventory/feature_inventory.yaml` = **서빙 기능 23건**(KEEP 4·REFACTOR 17·HEAVY 1·REPLACE 1) | **모집단 불일치** — 120은 외부 추적표 수치. 선행 리뷰가 "270→53 축소 경위 미문서화"로 이미 지적한 것과 같은 뿌리 |
| "향후 270개 EOS 기능" (§1) | `EOS-53` crosswalk가 **53항목**으로 전수 판정 | 동상 |
| Gate 1 "10개 중 8개가 아니라 10개 모두" (§2) | 취지는 옳으나 **대상 10조건 자체가 저장소 G1과 다르다** | §3-B |

경계 스캔 출력의 *"집행은 EOS-67"* 이라는 자기 주석은 `EOS-67` 완료(2026-08-31) 이후 **stale**이다 — 사소하나 정정 대상.

---

## §7. 권고

### 즉시 (Kiki 판단 — 9/6 G0 판정에 얹을 것)

1. **§3-A 12/31의 정의를 하나로 확정한다.** 선언 유지(내부 검증 판정일)가 권고다 — 실패 정의 F-Ⅰ~Ⅴ가 G0(9/6)에 동결되고 12월에 수정 금지이므로, 이 결정을 미루면 **동결할 대상 자체가 흔들린다.**
2. **§3-B Gate 1을 하나로 병합한다.** 권고안: 저장소 G1 3조건을 **차단 조건**으로 유지하고, 문서의 10조건 중 미충족 2건(#2 Version·#1 ID 표기)만 **비차단 관측 항목**으로 얹는다. 근거 — 나머지 8건은 이미 충족이라 차단 조건으로 세워도 정보가 0이고, HIT 축을 빼면 12월 판정 재료가 없다.
3. **§3-C 주차 번호는 저장소(W1=8/31~9/6)를 정본으로 한다.** 이미 `EOS-57` 제목이 그 번호를 쓴다. 문서를 인용할 때는 "문서 Week 1 = W2"로 환산 표기.

### 채택 전 결정 (§4 — 되돌리기 비싼 순)

| 제안 | 권고 | 사유 |
|---|---|---|
| A. ID 재설계 | **미채택** | 2026-08-17 결정이 이미 판정 · 4,000+ 키 영향 · crosswalk 게이트 코드 동결 |
| B. `related_to` 관계 | **미채택** | CLAUDE.md 절대 금기 직접 위반 |
| C. 이벤트 12종 | **부분 채택** — 필요한 생애주기 축은 기존 `EventType`에 값 추가로 | 계약 이중화 회피 |
| D. 디렉터리 물리 이동 | **미채택** | 선언 §1.3-③ 판정 유지 · `EOS-65` 표기 대안이 이미 착지 · 위반 이미 0 |
| E. ADR 트리 / Epic 재편 | **미채택** | 이중 진실원천 · `selector.py`가 Epic을 읽지 않음 |

### 등재 후보 (§5 — Kiki 승인 시 `backlog.py add`)

- **G-1** `EOS-49` 우선도 재검토(3 → 1~2). Gate 1 #2의 유일한 미충족분이고, 문서 §8이 옳게 짚었다.
- **G-3** 추천 응답의 `reason_code`+`evidence`+`score` 구조화 — 신규 태스크 후보.
- **G-2**는 **등재 금지** — `EOS-63`이 이미 있고 타 세션이 원격 claim 중이다.

### 문서 자체에 대한 평가

문서 200은 **아키텍처 원칙으로는 대체로 옳고**(§5 Dependency Rule의 CI 강제·§10 Core/Adapter 귀속 목록·§24 Attempt≠Evaluation≠Assessment≠Mastery 4분·§34 하지 말 것 5종은 저장소 결정과 독립적으로 같은 결론에 도달했다), **저장소 실상에 대해서만 틀렸다.** 그 결과 3주 계획의 상당 부분이 이미 완료된 일의 재실행이거나 작동 중인 어휘의 교체가 된다.

→ **문서를 Phase 1 실행계획으로 그대로 채택하지 말고, §5의 3건 + §7의 게이트 병합안만 흡수하는 것을 권한다.** 9월 3주는 문서가 비워 둔 축 — **앵커 1개 E2E와 HIT·실패코드 계측기** — 에 쓰는 것이 12/31 판정에 직결된다.

---

**작성**: 2026-09-01 · 조사 전용(코드 변경 0) · 대장 변경 0
**정본 관계**: 선언(`eos_transition_declaration_2026-08-30.md`) > 본 문서. 충돌 시 선언 우선이며, 선언을 바꾸는 것은 Kiki 판단이다.

---

## §8. 계획서 200의 재배치 — "지향성 참고본" (2026-09-01 Kiki 지시)

> **Kiki 판단**: 200은 오래된 문서다. **시스템적 지향성만 참고**한다.
> **12/31 목표**: 외부 출시가 아니라 **내부 EOS 1과목 완성**.
>
> 이 지시로 §3-A(12/31의 정의)는 해소된다 — "내부"가 확정됐다. §3-B·C(게이트·주차)는 §8.3으로 이월.

### 8.1 일정·사실을 걷어내도 살아남는 지향성 7건

| # | 지향성 | 200 위치 | 저장소 상태 | 처분 |
|---|---|---|---|---|
| D1 | **경계는 문서가 아니라 CI가 지킨다** ("Architecture 문서에만 쓰면 반드시 다시 침범한다") | §5 | **이미 집행** — import-linter 3계약 · 위반 0 · `tests/infra` 배선 동결 | 유지 근거로 인용 |
| D2 | **Core/Adapter 귀속을 목록으로 못박는다** | §10 | **이미 정본** — `eos_core_adapter_boundary.md`(CORE 305 / ADAPTER 51 / MIXED 34 / INFRA 178) | 대조표로 인용 |
| D3 | **Attempt ≠ Evaluation ≠ Assessment ≠ Mastery 4분** | §24 | **부분** — 4층이 코드로 실재(`attempt_event`·`AnswerSubmission`·`evidence_event`·`*MasteryHistory`)하나 **네 개념의 경계를 규정한 정본 문서가 없다**. 새 코드가 어느 층에 속하는지 판정할 근거가 사람 머릿속에만 있다 | **채택 가치 있음** |
| D4 | **버전·상태는 엔티티마다 만들지 않고 거버넌스가 공통 관리** | §8 | **미착지** — `EOS-49` todo·p3 · `concept_node`에 `version` 없음 | **채택 가치 있음** |
| D5 | **추천은 이유(reason)를 함께 낸다** | §25 | **부분** — `l6/blueprint/assembly.py:519` `reason` Literal뿐 | **채택 가치 있음** |
| D6 | **하지 말 것 5종** (Graph DB 전환·완벽 Ontology·Microservices·Agent 선행·선행 추상화) | §34 | 저장소 결정과 **전부 일치** | 채택 비용 0 · 재확인용 |
| D7 | **Freeze 이후 변경은 절차를 요구한다** | §40 | **이미 동형** — G0 실패정의 동결 + `test_declaration_canon_consistency.py` 기계 동결 | 유지 근거로 인용 |

**요지**: D1·D2·D6·D7은 저장소가 **독립적으로 같은 결론에 도달한 것**이라 새로 할 일이 없다(원칙의 상호 검증으로서 값어치가 있다). 실제로 남는 일은 **D3·D4·D5 세 건**이다.

### 8.2 가장 값어치 있는 것 — §1이 "1과목 완성"의 조작적 정의다

Kiki가 12/31 목표로 채택한 "EOS 1과목 완성"은 200 §1이 **3축으로 이미 정의**한 그 말이다. 그 정의를 기준으로 오늘 실측하면:

| 축 | 200 §1의 정의 | 실측 | 판정 |
|---|---|---|---|
| **학생** | 회원/프로필 → 교육과정 선택 → 진단 → 학습자 상태 → 개념 추천 → 콘텐츠 → 문제 추천 → 풀이 → 채점 → 오개념 판정 → 힌트/AI 설명 → 숙련도 갱신 → 다음 추천 | `test_e2e_vertical_slice_integration.py`가 온보딩→진단→문제→풀이→코치→verify를 **실 PG로 관통**하고 CI 전용 잡이 매번 돌린다. 오개념(`misconception_hypothesis`)·숙련도(`*MasteryHistory`)·선수 엣지·CAT 추천까지 포함 | **대체로 서 있음** |
| **시스템** | EOS Core → Subject Contract → Math Adapter → WhyMath 경계가 **코드에 존재** | `EOS-66`(2층 계약)·`EOS-67`(정적 강제)·`EOS-69`(경유 배선). 위반 **0건** | **완료** |
| **관리자** | 교육과정 → 개념 → Skill → 문제 → 풀이 → 오개념 → 교수전략 → 콘텐츠 → **검수 → 승인 → 버전 → 배포** | 엔티티는 전부 실재(`StrategyNode` 포함)하나 **운영 경로가 비어 있다** — 아래 표 | **거의 비어 있음** |

관리자 축 실측 (뒤쪽 4단계가 전멸):

| 태스크 | 상태 | 우선도 | 내용 |
|---|---|---|---|
| `ADMIN-04` 모듈 레지스트리 | todo | **3** | 관리 모듈 등록부 |
| `ADMIN-05` Admin BFF read-only | todo | **3** | `/v1/admin/*` 라우터 |
| `ADMIN-06` 백오피스 웹 셸 | todo | **3** | 관리 화면 자체 |
| `ADMIN-07` 검수 큐 UI | todo | **3** | `needs_review_worklist` 소비 UI (큐 자체는 CLI로 실재) |
| `EOS-50` Publish Gate | todo | **3** | Draft→Publish 검증 파이프라인 |
| `EOS-49` ConceptVersion 계약 | todo | **3** | 버전 축 (= D4) |
| `ADMIN-12` `is_published` 소비처 0건 | todo | **3** | 배포(게시) 축이 dead |
| `EOS-62` 검수 판정 해상도 | todo | 2 | `APPROVED_WITH_EDIT` |

**즉 "1과목 완성"을 12/31 목표로 놓는 순간, 지금 전부 priority 3으로 깔려 있는 관리자 축 7건이 목표의 3분의 1을 차지한다.** 200에서 건질 지향성 중 실행 결과를 가장 크게 바꾸는 것이 이것이다 — 문서의 새 제안이 아니라, **문서의 정의가 기존 대장의 우선도를 재배열한다.**

### 8.3 이 재정의가 바꾸는 것 (정직 표기 — 조용히 넘기지 않는다)

선언 §0-3은 목표 2축을 **① EOS 아키텍처 검증 ② AI 콘텐츠 생산 가능성(최우선)**으로 두고, **폐쇄루프를 "목적이 아니라 계측기"로 강등**해 깊이앵커 1개에서만 완결한다고 못박았다. 12/31 판정 실행기(`EOS-61` → `ops/validation_scorecard.py`, PR #953)도 그 축만 잰다 — Hard Gate F-Ⅰ~Ⅴ + KPI 12종(HIT·오류율·정합률·누설 등)이며 **관리자 운영 경로와 폐쇄루프 완결도를 재는 지표는 없다**.

"내부 EOS 1과목 완성"을 목표로 하면 **스코어카드가 재지 않는 축이 목표에 들어온다.** 처리 방식은 둘 중 하나여야 하고, 섞으면 12월에 "무엇을 통과했는가"가 결정 불가가 된다:

- **(가) 판정 기준은 선언 유지, "1과목 완성"은 그 위의 서사** — 스코어카드 12지표가 12/31 판정의 유일한 재료. 관리자 축은 판정 대상이 아니라 그 지표를 내기 위한 수단으로만 산다(검수 UI가 없으면 HIT를 못 재므로 `ADMIN-07`은 자동으로 필요해진다). **변경 비용 0** — 동결된 F-Ⅰ~Ⅴ를 건드리지 않는다.
- **(나) "1과목 완성"을 판정 기준으로 승격** — 200 §1의 3축을 판정 조건으로 올린다. 그러려면 관리자 축의 완료 정의와 측정 방법을 **9/6 G0 전에** 만들어 스코어카드에 넣어야 한다. F-Ⅰ~Ⅴ는 "G0 동결·12월 수정 금지"이므로, **9/6을 넘기면 이 선택지는 닫힌다.**

권고는 **(가)**다. 이유는 두 가지 — ⓐ (나)는 5일 안에 새 판정 기준을 설계·동결해야 하는데 그 자체가 G0의 원래 목적(실패 정의 동결)과 경합한다 ⓑ (가)에서도 관리자 축은 **HIT 측정의 전제**로서 실질적으로 승격되므로, 실제 작업 순서는 (나)와 크게 다르지 않으면서 판정 기준만 흔들리지 않는다.

### 8.4 여전히 버리는 것 (§4 판정 유지 — 지향성이 아니라 구현 지시라서)

ID 재설계 · `related_to` · 영어 이벤트 12종 · 디렉터리 물리 이동 · ADR 트리 · Epic 13개 재편 · **Gate 1 10조건** · **일정표(§38)와 주차 번호**. 이들은 "지향"이 아니라 저장소가 이미 다르게 판정한 **구현 지시**이며, 오래된 사실 인식(120기능·850PR·경계 미분리) 위에 서 있다.

**§3-B(게이트 병합)는 유효하다** — 200의 Gate 1을 버려도 저장소 G1 3조건은 그대로 남으며, §7 권고 2(미충족 2건을 비차단 관측 항목으로 얹기)는 그대로 적용 가능하다.

### 8.5 Kiki 결정 반영 결과 (2026-09-01)

**결정**: §8.3의 **(가)** — 12/31 판정 기준은 선언(스코어카드 12지표) 유지, "1과목 완성"은 그 위의 목표 서사. 대장 조정 3건 지시.

#### ① 관리자 축 7건 우선도 재검토 → **승격 0건** (재검토 자체는 수행)

(가)를 채택한 이상 관리자 축은 **판정 대상이 아니라 지표 생산의 수단**이다. 그 기준으로 7건을 개별 판정한 결과, **HIT 측정을 실제로 가로막는 것은 검수 화면의 부재가 아니었다.**

실측(2026-09-01):

```
start_review        src/ 생산 호출자 0
finish_review       src/ 생산 호출자 0
abort_review        src/ 생산 호출자 0
append_event_jsonl  src/ 생산 호출자 0        (테스트 4파일만 호출)
```

`EOS-54`(done)가 만든 HIT writer는 **자기 테스트만 부르는 계약**이다. 그리고 실제 검수 판정을 기입하는 CLI 3종(`concept_content_review_apply`·`concept_content_review_batch`·`reviewer_sample_package`)의 `review_timer` 참조는 **각각 0건**이다. `harness/review_timer.py` 모듈 docstring이 이를 스스로 자인한다 — *"검수 UI(**ADMIN-07**)가 타이머·반려코드 없이 판정 제출 자체를 불가하게 하는 **UI 결선은 후속 태스크**"*.

(가) 하에서 이것은 사소하지 않다. HIT는 스코어카드 KPI 1순위이고, `EOS-61` acceptance ④가 미측정을 "PASS"가 아니라 **exit 1(측정 실패)**로 처리하므로 — 설계는 옳다 — 생산자 부재는 조용한 오통과가 아니라 **12/31 판정 불가**로 직결된다.

그런데 `ADMIN-07`은 이 공백의 올바른 해소 수단이 **아니다**: stage S4·layer web이며 `ADMIN-04 → ADMIN-05/06(+WEB-01) → ADMIN-07` **4단 체인**이라 9월 안에 서지 않는다. 반면 오늘의 검수 매체는 이미 JSONL/CLI다. 그래서:

| 항목 | 재검토 판정 |
|---|---|
| `ADMIN-07` 검수 큐 UI | **p3 유지** — 판정 대상 아님. 판정 근거를 태스크 acceptance에 교차 기록(재질문 차단) |
| `ADMIN-04`·`05`·`06` | **p3 유지** — 웹 백오피스는 (가) 하에서 판정과 무관 |
| `ADMIN-12`·`EOS-50`·`EOS-49` | **p3 유지** — 완성 서사 축이지 판정 축이 아님 |
| `EOS-62` 검수 판정 해상도 | **p2 유지** — HIT 회계 해상도에 직결하므로 이미 적정 |
| **신규** | **`EOS-78-hit-timer-producer-wiring` (p1)** — 웹 UI 없이 현행 CLI/JSONL에서 HIT를 측정 가능하게. 신규 서빙 라우트 0·웹 화면 0 |

즉 **"관리자 축 7건을 승격한다"가 아니라 "7건 중 0건을 승격하고, 아무도 안 갖고 있던 1건을 새로 세운다"**가 재검토의 결론이다. 일괄 승격했다면 방금 채택한 (가)를 대장이 배신했을 것이다.

#### ② D3 신규 등재 → `EOS-79-evidence-layer-boundary-canon` (p2)

Attempt·Evaluation·Assessment·Mastery 4층 경계 정본. 4층이 코드로는 전부 실재하나(모델 7종) 경계를 규정한 문서가 없어 **새 코드의 귀속 판정 근거가 사람 머릿속에만 있다.** 검색 범위 명시: `docs/architecture/0*.md` 21건 + `docs/standards/` 역할 기반 검색에서 0건.

#### ③ D5 신규 등재 → **등재하지 않음 (중복)** · 앞선 판정 정정

**§5 G-3과 §8.1 D5의 "부분" 판정은 틀렸다.** `l6/blueprint/assembly.py` 한 곳만 보고 내린 판정이었다. 실측하면 `REC-01`(**done**)이 추천 응답의 정직 표기를 이미 착지시켰다:

```
candidate_zero_reason        backend 6건   (api/me.py:2061 정의)
weight_axes_applied          backend 10건
candidate_pool_size          backend 18건
weak_concept_signal_count    backend 10건
```

계획서 200 §25가 요구한 `reason_code`+`evidence`+`score` 세트는 **서버에서 이미 성립한다**. 남은 절반은 렌더 축이며 그것도 이미 좌석이 있다 — `REC-10-next-problem-honesty-fields-render`(todo·p3, 위 4필드의 **mobile 파싱 0건**이 그 태스크의 전제). 새 태스크를 세웠다면 `REC-10`과 중복이었다.

`REC-10`의 우선도는 **건드리지 않았다** — (가) 하에서 학생 대면 렌더는 판정 재료가 아니므로 p3가 맞다. 승격이 필요하다고 보면 별도 지시가 필요하다.

#### 집행 확인

```
python3 scripts/harness/backlog.py validate     → ✔ green (태스크 493·게이트 22)   EXIT=0
python3 scripts/harness/backlog.py audit-deps   → ✔ green (위반 0건)              EXIT=0
```

번호 배정은 전부 `backlog.py add` 경유다(추론 배정 금지). 실제로 첫 시도 `EOS-76`은 **원격 브랜치의 인플라이트 태스크와 충돌**해 CLI가 거부하고 `EOS-78`을 제안했다 — HARN-10 장치가 작동한 사례로 기록해 둔다.

---

## §9. 정정 이력 (PR #958 리뷰 봇 지적 수용 — 2026-09-01)

초판의 사실 오류 **2건**을 실측 확인 후 정정했다. 둘 다 이 문서가 *다른 문서의 부정확을 지적하는* 성격이라 자기 정확도의 기준이 더 높다.

**① 경계 "위반 0건"이 조기 통과를 부를 수 있었다** (§2 행 9 · §0 결론 1 · §3-B)

초판은 `EOS-69` 결과를 **"달성 · 위반 0건"**으로 적었다. 그러나 스캐너와 `EOS-67` 계약이 세는 것은 **직접 CORE→ADAPTER import**이고, 합성 루트 경유 간선 2건은 7계층 계약의 `ignore_imports`로 **명시 예외** 중이다:

```
whymath_backend.l3.pedagogy.slot_generator -> whymath_backend.composition
whymath_backend.l3.render.adapters        -> whymath_backend.composition
```

경계 문서 §4.1과 `EOS-69` acceptance ⑩ 자신이 *"위반이 없어진 게 아니라 9 → 2로 **작아졌다**"* 고 적고 재확인 지점을 **G1(9/27)**로 명시했다. 이 문서가 그 잔여를 빼고 "0건"만 인용하면 **G1의 "Core→Math 정적 의존 0"이 조기 통과**한다 — 게이트를 느슨하게 만드는 방향의 오류라 가장 나쁜 종류다. **부분 달성**으로 고치고 잔여 2건과 재확인 지점을 본문에 넣었다.

**② `EventType` 개수를 11 → 12로** (§2 행 8 · §4-C)

실측 결과 멤버는 12개다 — 기존 11종에 `EOS-57`이 추가한 **`문제시도`**가 있고, 이것이 바로 계획서 200 §22의 `problem_attempted`에 **직접 대응**한다. 초판이 11로 적어 최신 계약을 누락했고, "영어 12종 ↔ 한국어 N종" 비교 근거도 왜곡됐다.

*자기 방법의 한계 기록*: §1이 선언한 "역할 기반 재검색"은 `attempt_event`·`AnswerSubmission` 같은 **주변 좌석**은 찾았지만 **enum 멤버 자체**는 놓쳤다. `grep problem_attempted` 0건이 맞았고 역할 검색도 대응물을 찾았는데, 정작 *같은 enum 안의 한국어 멤버 목록을 끝까지 세지 않은* 것이 원인이다. 부재·개수 주장에는 **그 집합을 전건 열거**하는 단계가 필요하다(절단 출력 부재 판정 금지의 enum 축).

두 지적 모두 `chatgpt-codex-connector`(P2)가 냈고, 저장소 실측으로 확인한 뒤 수용했다.
