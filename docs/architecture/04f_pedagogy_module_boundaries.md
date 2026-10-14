# 04f. EOS 교수전략 라이브러리 갭 설계 — 14/15/16/17 모듈 경계 정리

> **성격**: L4(교수학 엔진) 서브 설계 — `04`(교수학 결정)·`04a`(WH-1 하네스)·`04b/04c`(오개념)·`04d`(교수법 선택·학습)·`04g`(교수전략 카탈로그)에 이어 **외부 EOS ⑭교수전략 라이브러리 검토와 WhyMath 현행 구현을 대조**하고, ⑮설명 방식 선택·⑯힌트 전략·⑰교정 전략의 WhyMath 좌석과 책임 경계를 정리한다.
>
> **한 줄**: ⑭번은 이미 `PedagogyStrategy` enum 10종·YAML 카탈로그·`select→gate→decide` 런타임으로 Phase 1 수준에서 구현됐으나, `StrategyDecision`/`StrategyExecutionPlan`/`StrategyOutcome`, `PedagogicalAction`, `StrategyStep`, 구조화된 `ApplicabilityRule`, Pedagogy Graph, State Machine, Event System 연결 등은 아직 미구현이다.
>
> **버전**: 1.0 | **작성**: 2026-08-25 | **다음 검토**: PED-31 완료 시점

---

## 1. 외부 ⑭번 검토 핵심 요약

외부 EOS 관점에서 제시된 핵심 원칙은 다음과 같다.

1. **Design Pedagogy ↔ Runtime Pedagogy 분리** — 전략 정의와 실행 시 선택을 분리.
2. **Strategy ≠ Prompt ≠ Tutor Action ≠ UI** — 교수학 의도·렌더 명세·실제 생성·화면 표현을 분리.
3. **Applicability Rule 중심** — "어떤 전략이 있는가"보다 "언제 그 전략을 쓰는가"가 가치.
4. **PedagogicalAction 원자화** — `EXPLAIN`·`ASK`·`HINT`·`SHOW_EXAMPLE` 등 재사용 가능한 행동 단위.
5. **StrategyStep 별도 Entity** — 복합 전략의 순서·분기·재시도 표현.
6. **StrategyDecision / StrategyExecutionPlan / StrategyOutcome 분리** — 왜 선택했는가·무엇을 실행하는가·실제 효과는 무엇인가.
7. **Concept Graph / Misconception DB 연결** — 전략이 개념·오개념·목표에 binding.
8. **Education Event System 연결** — `strategy.selected`·`strategy.step.started` 등 lifecycle 이벤트.
9. **Effectiveness Model (조건부)** — (학생군 × 개념 × 오개념 × 전략) 단위 효과.
10. **Fading / Composition / Pedagogy Graph / State Machine** — 장기 EOS 확장 요소.

---

## 2. WhyMath 현행 구현 대조

| 외부 항목 | WhyMath 현행 좌석 | 구현 수준 | 주요 갭 |
|---|---|---|---|
| **PedagogicalStrategy 정의** | `schema/enums.py` `PedagogyStrategy` enum 10종 + `data/corpus/pedagogy_strategies_v1/*.yaml` + `schema/pedagogy_strategy.py` `PedagogyStrategyCard` | Phase 1 MVP | 카탈로그는 서술 자산. 실행 가능한 DB Entity·lifecycle·version 관리 부재. |
| **Design/Runtime 분리** | 04d §1 2단계 교수법 분리 + `l4/pedagogy/runtime_selector.py` `select()`/`gate()`/`decide()` | 부분적 | 실행 계획(`StrategyExecutionPlan`) Entity 부재. 선택 결과는 즉시 `PedagogyDecision`으로 소멸. |
| **PedagogicalAction** | `l4/models.py` `PedagogyDecision.suggested_actions: list[str]` + `prompt`/`system` | 매우 미흡 | 원자적 action enum/type 부재. 문자열 라벨만 존재. |
| **StrategyStep** | 없음 (`PedagogyStrategyCard`에 없음) | 없음 | 별도 entity 부재. 전략은 단일 결정 단위. |
| **ApplicabilityRule** | `PedagogyStrategyCard.target_grade_bands`·`difficulty_range`·`target_k_types`·`suitable_error_types` + `runtime_selector.narrow_candidates()` | 부분적 | mastery 범위·misconception confidence·attempt_count·error_pattern 등 구조화 조건 부재. |
| **StrategyDecision** | 없음 (`decide()`는 `GateResult` 반환) | 없음 | 별도 decision entity 부재. 선택 근거(reason_code)는 logger/감사용 구조화 메타데이터로 미지속. |
| **StrategyExecutionPlan** | 없음 | 없음 | 별도 entity 부재. `PolyaCoach`가 내부적으로 단발 결정. |
| **StrategyOutcome** | `l4/pedagogy/adaptive/effectiveness.py` `EffectivenessReport` + `l2/pedagogy_evidence.py` `EVENT_TYPE_TREATMENT`/`OUTCOME` | 초기 | learner_state_before/after snapshot·outcome entity 부재. 축은 (strategy × k_type × objective_id)만. |
| **Strategy Family** | `PedagogyStrategy` enum 자체가 family 역할 | Phase 1 | `MISCONCEPTION_REMEDIATION`·`SCAFFOLDING` 등 family grouping 부재. |
| **Concept Graph 연결** | `target_k_types`로 지식유형 단위 간접 연결 | 부분적 | strategy→`concept_node`·strategy→`skill_node` 직접 edge 부재. |
| **Misconception DB 연결** | `suitable_error_types`(6종 오류 유형)으로 간접 연결 | 부분적 | kebab/M-id ↔ strategy 직접 binding 부재. |
| **Event System 연결** | `evidence_event` TREATMENT/OUTCOME | 초기 | `strategy.selected`·`strategy.step.started`·`strategy.fallback` 등 세부 lifecycle 이벤트 부재. |
| **Effectiveness Model** | Wilson 단측 하한, (strategy × k_type × objective_id) 집계 | 초기 | (learner_state × concept × misconception × strategy) 조건부 모델 부재. |
| **Fading** | `PedagogyPack.fading_schedule`(k_type 축) | 부분적 | strategy 단위 fading policy·success/failure streak 반응 부재. |
| **State Machine** | `PolyaState`(4단계) | 부분적 | 복합 교수전략 단위 상태 머신 부재. |
| **Pedagogy Graph** | 없음 | 없음 | strategy→strategy 관계 edge 부재. |
| **Composition** | 없음 | 없음 | `precedes`·`follows`·`fallback_to` 등 관계 부재. |
| **Exit/Fallback 조건** | `gate()` 2축 + `_FALLBACK_STRATEGY = SOCRATIC` | 부분적 | entry/continuation/success/failure/exit/fallback 조건의 구조화 부재. |
| **Explainability** | `GateResult.reason_code` + `logger.info` | 부분적 | LLM/교사 대시보드용 decision reason 객체 부재. |
| **Teacher Policy** | 없음 | 없음 | 선호/금지/최대 hint level 등 교사 제약 부재. |
| **Learner Preference** | `StudentSignals`에 없음(생산자 부재) | 없음 | preference vs effectiveness 분리 부재. |
| **Caching 계층** | `lru_cache(maxsize=1)` 카탈로그 캐시 | Phase 1 | candidate/decision/generated explanation 별 캐시 적합성 명시 부재. |

---

## 3. 갭 우선순위 (Phase 1~2)

| 우선순위 | 항목 | WhyMath 맥락 | 후속 태스크 |
|---|---|---|---|
| **P0** | `StrategyDecision` / `StrategyExecutionPlan` / `StrategyOutcome` 분리 | ⑭번 핵심. AI가 전략을 자유 생성하지 않도록 감사·구조화. | PED-32 |
| **P0** | `PedagogicalAction` 원자화 + `StrategyStep` | AI 에이전트 실행·재사용·테스트 가능성. | PED-33 |
| **P0** | `ApplicabilityRule` 구조화 | "언제"가 전략 라이브러리의 실질 가치. | PED-34 |
| **P1** | Event System 연결 (`strategy.*`) | 측정·최적화·A/B의 기초 데이터. | PED-35 |
| **P1** | Fading/Scaffolding 정책 (strategy 단위) | 메타인지·AI 의존 방지. | PED-36 |
| **P1** | Concept/Misconception binding 강화 | ⑭번과 ⑪/⑫/⑬/⑥ 연결. | PED-37 |
| **P2** | Pedagogy Graph / Composition | 장기 EOS. | PED-38 |
| **P2** | State Machine | 복합 전략 표현. | PED-39 |
| **P2** | Teacher/Learner policy | Phase 3 대시보드·B2B. | PED-40 |

---

## 4. ⑮/⑯/⑰ 모듈 책임 경계

### 4.1 ⑮ 설명 방식 선택 (Explanation Strategy)

> 외부: "어떻게 설명할 것인가?"

WhyMath는 ⑮을 **독립 enum/축으로 만들지 않고** 기존 3축의 사영으로 흡수했다(04g §2.2 판정).

| 외부 설명 방식 | WhyMath 좌석 | 책임 계층 |
|---|---|---|
| 직접 설명·비유·예시 | `PedagogyStrategy` enum(`DIRECT`·`ANALOGY`·`WORKED_EXAMPLE`) + `PedagogyPack.socratic_prompt` + `prompt_assembler` | L4 결정·L3 생성 |
| 시각적 설명 | `Visualization`/`LearningScene` 선언적 명세 | L4 장면 조립·L5 렌더 |
| 단계별 설명 | `SolutionPath` + `StepPanelElement` + 답 미루기 | L3 검증·L4 선택·L5 점층 노출 |
| 실생활 예시 | `example_generator` 슬롯(04g §6) | L3 콘텐츠 생성 |

**경계**: L4는 "어떤 전략"을 결정하고, L3는 "어떻게 생성", L5는 "어떻게 보여줄지"를 담당. ⑮은 L4와 L3 사이의 **렌더 전략 매개체**이지 별도 모듈이 아니다.

### 4.2 ⑯ 힌트 전략 (Hint Strategy)

> 외부: "어떻게 도움을 줄 것인가?"

WhyMath는 ⑯을 **지원 강도 조절 메커니즘**으로 L4 골격에 내재시켰다.

- **답 미루기 4단계**: `l4/hint_deferral.py` `HintLevel` 1~4.
- **결정 함수**: `decide_hint_level()`이 학생 발화·턴 수·mastery로 단계를 산출.
- **전달**: `PedagogyDecision.hint_level`로 L3/L5에 전달.
- **페이딩**: `PedagogyPack.fading_schedule`이 지식유형(k_type) 단위 페이딩 정책.
- **안전망**: `mode_guard` + `gate()`가 냉담 정답 제공 차단.

**경계**: ⑯은 "전략"이 아니라 **모든 전략에 걸쳐 적용되는 지원 강도 메커니즘**이다. 힌트 자체는 `PedagogicalAction.HINT` 원자로 표현할 수 있으나(후속 PED-33), 단계 결정은 `hint_deferral` 고유 책임.

### 4.3 ⑰ 교정 전략 (Remediation Strategy)

> 외부: "잘못 이해한 것을 어떻게 고칠 것인가?"

WhyMath는 ⑰을 **오개념 개입 패턴**으로 이미 구현했다.

- **개입 패턴 4종**: `l4/misconception/models.py` `InterventionPattern`
  - `COUNTEREXAMPLE` — 반례 유도
  - `CONCRETE_CASE` — 구체 사례
  - `VISUALIZATION` — 시각화 유도
  - `REVERSE_REASONING` — 거꾸로 사고
- **선택**: `l4/misconception/intervene.py` 결정트리.
- **소크라테스 오버라이드**: `l4/socratic/select.py` `ASSUMPTION` 카테고리(활성 오개념 가설 반영).
- **장면 요소**: `LearningScene.MisconceptionProbeElement`(낙인·정답 필드 없음).

**⑬ 맞춤 교정과 ⑭ 교수전략의 관계**: 외부 검토는 "⑬은 ⑭의 전문화"로 보는 것이 자연스럽다고 제안했다. WhyMath 현행에서는 `InterventionPattern`이 `PedagogyStrategy`와 **별도 축**이지만, ⑭번의 `MISCONCEPTION_REMEDIATION` family 아래에서 교정 전략을 표현할 수 있다. 이 통합은 PED-37에서 설계한다.

### 4.4 통합 경계도

```
LearnerState (L2)
  ↓
PedagogicalStrategy Library (L4)
  ├─ PedagogyStrategy enum + YAML catalog
  ├─ runtime_selector.select() → "효과"
  └─ runtime_selector.gate()  → "허용"
  ↓
StrategyDecision — (미구현) 왜 이 전략인가? + reason_codes
  ↓
StrategyExecutionPlan — (미구현) PedagogicalAction[] + step sequence + exit/fallback
  ↓
⑮ Explanation / ⑯ Hint / ⑰ Misconception Intervention
  ↓
TutorAction (L4 결정) → LLM Renderer (L3) → UI (L5)
  ↓
Education Event (L2/L4) → StrategyOutcome (L2/L4)
```

---

## 5. 물리 스키마 제안 (Phase 2)

### 5.1 PostgreSQL 테이블

| 테이블 | 역할 | 비고 |
|---|---|---|
| `pedagogical_strategy` | 전략 정의 | 현행 YAML 카탈로그를 DB로 이관 또는 동기화. lifecycle·version·provenance 포함. |
| `strategy_family` | 전략 family | `MISCONCEPTION_REMEDIATION`·`SCAFFOLDING` 등. |
| `pedagogical_action` | 원자적 행동 | `EXPLAIN`·`ASK`·`HINT`·`SHOW_EXAMPLE`·`SHOW_COUNTEREXAMPLE`·`COMPARE`·`VISUALIZE`·`DEMONSTRATE`·`PRACTICE`·`REVIEW`·`RECALL`·`REFLECT`·`VERIFY`·`REMEDIATE`. |
| `strategy_step` | 전략 실행 단계 | `strategy_id`·`step_order`·`action_id`·`entry_condition`·`success_next`·`failure_next`·`max_retries`. |
| `strategy_rule` | 적용 조건 | `mastery_range`·`misconception_confidence`·`attempt_count`·`error_pattern` 등 JSONB. |
| `strategy_binding` | 교육 entity 연결 | concept·skill·misconception·objective·problem_type. |
| `strategy_transition` | 전략 간 전환 | `precedes`·`follows`·`fallback_to`·`escalates_to`. |
| `strategy_decision` | 런타임 선택 결과 | learner_state snapshot·selected_strategy·confidence·reason_codes·fallback. |
| `strategy_execution` | 실제 실행 | step별 시작/완료·action log. |
| `strategy_outcome` | 효과 평가 | before/after mastery·correct·hint_count·duration·Δmastery. |

### 5.2 L4 모듈 추가 지점

| 모듈 | 책임 |
|---|---|
| `l4/pedagogy/decision.py` | `StrategyDecision` 빌더 + explainability. |
| `l4/pedagogy/plan.py` | `StrategyExecutionPlan` 빌더. |
| `l4/pedagogy/action.py` | `PedagogicalAction` enum + L3 renderer mapping. |
| `l4/pedagogy/step.py` | `StrategyStep` 모델 + branching 검증. |
| `l4/pedagogy/rule.py` | `ApplicabilityRule` 평가. |
| `l4/pedagogy/graph.py` | Pedagogy Graph(PG edge table). |
| `l4/pedagogy/state_machine.py` | 복합 전략 상태 머신. |

---

## 6. Phase 1~2 MVP 범위

### Phase 1 (MVP)

- 04f 문서 승인 + PED-31 완료.
- `PedagogicalAction` enum 14종 도입(`l4/pedagogy/action.py`).
- `StrategyStep` Pydantic 모델(`PedagogyStrategyCard` 내부 child로 시작). branching은 하위호환 None.
- `ApplicabilityRule` JSONB 확장: `mastery_range`·`misconception_confidence_min`·`attempt_count`·`error_pattern`.
- `StrategyDecision` Pydantic 모델 + `reason_codes`·`fallback_strategy_id`.
- `StrategyExecutionPlan` Pydantic 모델(step list).

### Phase 2 (풀 K-12)

- 위 테이블들에 대한 Alembic 마이그레이션.
- Event System 연결: `strategy.selected`·`strategy.started`·`strategy.step.started`·`strategy.step.completed`·`strategy.fallback`·`strategy.completed`.
- 효과성 집계 축 확장: `misconception_id`·`learner_level` 추가.
- Fading 정책(strategy 단위): success_streak·failure_streak·support_level 조절.
- Teacher policy constraint 기초: `prefer`·`avoid`·`max_support_level`.

---

## 7. 후속 태스크 분해

| 태스크 | 제목 | 범위 |
|---|---|---|
| PED-32 | `StrategyDecision`/`StrategyExecutionPlan`/`StrategyOutcome` Pydantic 모델 설계 | ⑭번 핵심 4분리 중 3개 |
| PED-33 | `PedagogicalAction` 원자화 및 `StrategyStep` 모델 | AI 실행기 밑바탕 |
| PED-34 | `ApplicabilityRule` 구조화 및 `runtime_selector` 통합 | "언제" 판정 강화 |
| PED-35 | Event System 연결 — strategy lifecycle events | 측정·최적화 기초 |
| PED-36 | Fading/Scaffolding 정책 (strategy 단위) | 의존 방지 |
| PED-37 | Concept/Misconception binding 강화 | ⑪/⑫/⑬/⑭/⑥ 연결 |
| PED-38 | Pedagogy Graph / Composition | 장기 EOS |
| PED-39 | State Machine for compound strategies | 복합 전략 |
| PED-40 | Teacher/Learner policy constraints | Phase 3 대시보드 |

---

## 8. 외부 ⑭번 핵심 권고 vs WhyMath 적용 판정

| 외부 권고 | WhyMath 판정 | 근거 |
|---|---|---|
| 교수전략을 독립 Entity로 관리 | ✅ Phase 2 DB 이관 | 현재 YAML catalog로 Phase 1 충분. |
| 과목 중립 설계 | ✅ 이미 적용 | `target_k_types`·`target_grade_bands`로 수학 중심이나 확장 가능. |
| Strategy와 Prompt 분리 | ✅ 이미 적용 | `prompt_assembler` 4계층 조립. |
| Strategy와 생성 콘텐츠 분리 | ✅ 이미 적용 | L4 결정·L3 생성·L5 렌더 분리. |
| Strategy와 Tutor Action 분리 | ⚠️ 부분적 | `PedagogyDecision`이 두 역할을 겸함 → PED-32에서 분리. |
| Design/Runtime Pedagogy 분리 | ✅ 개념상 적용 | 04d §1. 실행 계획 entity만 추가. |
| 적용 조건 구조화 | ⚠️ 부분적 | 카드에 단순 리스트 → PED-34에서 JSONB rule 강화. |
| 전략 전환/Fallback | ✅ 개념상 적용 | `gate()` 2축·`_FALLBACK_STRATEGY`. 구조화는 PED-32. |
| Concept/Misconception 연결 | ⚠️ 부분적 | k_type/error_type 간접 연결 → PED-37에서 강화. |
| Event 기록 | ⚠️ 초기 | TREATMENT/OUTCOME만 → PED-35에서 lifecycle events 확장. |
| Strategy Version 관리 | ❌ 미구현 | YAML은 버전이 암묵적. Phase 2 `pedagogical_strategy.version_id` 도입. |
| 근거/출처 관리 | ✅ 이미 적용 | `research_basis` + `provenance`. |
| LLM 제한적 실행 | ✅ 이미 적용 | `select→gate→decide` + 폐쇄 enum. |
| 전략 효과성 학습 | ⚠️ 초기 | PED-03 스캐폴드 있으나 표본 미달 → PED-32/33/35 후 재승격. |
| Pedagogy Graph | ❌ 미구현 | PED-38. |
| Contextual Bandit/RL | ⏸️ 보류 | PED-03 adaptive policy가 스캐폴드. 데이터 충분 후 승격(04d §3.3). |

---

## 9. 교차링크

- `docs/architecture/04_pedagogy_engine.md` — Polya·소크라테스·오개념·LTHC
- `docs/architecture/04d_adaptive_pedagogy_engine.md` — Runtime Pedagogy Selector
- `docs/architecture/04g_pedagogy_strategy_catalog.md` — 교수전략 카탈로그
- `docs/architecture/02_learner_model.md` — 학습자 모델 입력
- `docs/architecture/05_interaction.md` — L5 렌더 경계
- `docs/architecture/03c_content_strategy_cache.md` — 콘텐츠 전략 캐시
- `docs/data/misconception_catalog_v1.md` — 오개념 카탈로그
- `backlog/tasks/PED-31-eos-pedagogy-strategy-library-gap-design.yaml`
