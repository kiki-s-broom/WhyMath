# Math DSL 구조 리스크 레지스터 — 10대 실패모드 분석

> **상태**: 분석(analysis) · **계층**: 횡단(L1·L3·L4·L5) · **작성일**: 2026-06-30
> **정본 상위**: `math_dsl_principles_review.md`(플레이북 검토 — 정합/충돌/공백). 본 문서는 그
> "공백" 절을 *현 코드 근거(파일·라인)*로 구체화한 리스크 레지스터다.
> **근거**: 코드 정밀 조사 3축(L1 원자 그래프 / L5 시각화·LearningScene / 오개념·AST·retrieval), 2026-06-30.
> **범위**: 분석만 — 수정은 *방향*만 제시(작업 항목화는 별도 `/plan`).
> **동반(retrieval 심화)**: `math_dsl_retrieval_analysis.md` — 본 레지스터의 "AI retrieval failure" 축을 검색 10렌즈+4전략으로 심화(2026-07-01).

> ✅ **2026-07-08 개정 완료(Phase 5a) — ③ FormulaNode·리스크 8**: "③ 미도입 FormulaNode가 정답"·
> 리스크 8(node explosion) 판정은 리치 Part 2 스펙 **전면 채택**(사용자 확정·`concept_node_layering_
> decision.md` §0)으로 재판정돼 **Phase 5a에서 정식 개정됐다** — FormulaNode를 **canonical-only**
> (변형식 노드화 금지)로 도입했고 SymPy 검증커널·AST 참조전용 경계는 유지한다. node explosion 방어는
> "canonical 단위 승격 + 신규 엣지 타입 0 + 변형은 SymPy 런타임 동치 위임" 원칙으로 대체. 반대 논거
> ("변형식 노드화 즉시 폭발"·"자체 CAS/재작성규칙 트리=즉사")는 **canonical-only·재구현 금지 불변식의
> 근거로 보존**(반대→조건부 허용). 아래 ③·리스크 8 본문은 그 결정으로 정정됐다(거버넌스
> `test_formula_governance`가 canonical-only·SymPy 재구현 금지 경계를 코드로 동결).

---

## 0. 구조 스냅샷 (2026-06-30 작성 기준)

| 항목 | 현황 | 근거 |
|---|---|---|
| L1 그래프 규모 | (2026-06-30) 노드 2,697(단원 217·소단원 643·원자 1,837) | `data/corpus/atom_graph_v1/graph.json` |
| 엣지 | (2026-06-30) 2,213 — **전량 `PREREQUISITE`**, strength **0.8 균일** | `l1/atom_graph/atom_backend_edge.py` |
| Branching | 평균 out 1.25 / max out 7 / max in 4 (희소) | graph.json 실측 |
| 순환 | 현재 **acyclic** — 단 적재 파이프라인에 **cycle 검출 게이트 없음**(self-loop만 차단) | `schema/concept.py:228-299`·`l1/atom_graph/populate.py` |
| 시각화 spec | 렌더러 종속 필드 **0**(no fps/shader/canvas/pixel/color)·`extra="forbid"` | `schema/visualization.py:132-199` |
| LearningScene | 6 element kind·불변식 3종·참조 무결성 게이트·interaction state 누출 **0** | `l4/learning_scene.py:79-312` |
| 오개념 | (2026-06-30) **3중 표현**: kebab 30종(런타임)·M-id 839종(콘텐츠)·개념노드 JSONB 자유서술 — **FK 없음** | `l4/misconception/catalog.py`·`schema/misconception_catalog.py:9-12`·`schema/concept.py:213` |
| 수식 동치 | 명시 AST 없음 — SymPy(py)·mathjs(js) **각자 파싱·정규화**. py 측 *입력 표기 정규화*(implicit mult·전각/NFKC·연산자·그리스·chained eq)는 `to_sympy_source` **단일 권위**로 일원화(2026-07-02·Part 4 항목4) | `l3/symbolic_equivalence.py`·`l3/verify_step.py`·`src/web/graphing-calculator/src/lib/graph2dSpec.js` |

**한 줄 평**: *표현 계층은 invariant가 스키마로 박혀 견고, 그래프 위생은 아직 무방비, 오개념
정체성은 이미 부채.* 폭발은 대부분 *시작 전* — 지금이 invariant를 박을 적기다.

---

## 1. 10대 실패모드 위험도

| # | 실패모드 | 위험도 | 핵심 동인 (코드 근거) |
|---|---|---|---|
| 1 | **misconception overlap** | 🔴 높음 | 3중 표현(kebab/M-id/JSONB) FK 없음·방향맹 매처 (`catalog.py`·`misconception_catalog.py:9-12`) |
| 2 | **semantic ambiguity** | 🔴 높음 | 위 + "객체 vs 해석" 미구분·원자 임베딩 신호 얇음 (`atom_graph/embedding.py:81`) |
| 3 | **curriculum inconsistency** | 🟠 중상 | 교육과정 정보 **노드 내장 + Overlay 이중**·atom code에 개정연도 박힘 (`schema/concept.py:147-160`) |
| 4 | **AI retrieval failure** | 🟠 중간 | 방향맹 임베딩·hybrid fusion 전략 부재·가설 store 미연결 (`semantic/matcher.py:9-18`·`api/scene.py`) |
| 5 | **relation explosion** | 🟠 중간(잠재) | `ANALOGOUS_TO`·`CONTRASTS`·`TRIGGERS_DISTRACTOR` 선언·미적재 → 적재 시 N² (`enums.py` EdgeType) |
| 6 | **AST duplication** | 🟠 중간(완화) | SymPy(py)·mathjs(js) 병렬 정규화 → drift. py 입력 정규화는 `to_sympy_source` 단일 권위로 일원화돼 py 내부 drift 표면 축소(2026-07-02·`math_dsl_part4_ast_review.md`) — py↔js 계약은 golden test가 계속 방어 (`symbolic_equivalence.py`·`graph2dSpec.js`) |
| 7 | **cyclic dependency** | 🟡 낮음(무방비) | 현재 acyclic이나 reachability/SCC 게이트 없음 (`populate.py`) |
| 8 | **node explosion** | 🟡 낮음 | 입도 판정 규칙 미명문(과분할). **Formula는 canonical-only 도입(P5a)**·변형 노드화 금지 불변식으로 폭발 차단(Proof는 미도입 유지) |
| 9 | **renderer coupling** | 🟢 낮음 | spec 렌더러 독립·`extra="forbid"` (`visualization.py:186-199`) |
| 10 | **interaction state leakage** | 🟢 낮음 | spec stateless·런타임 분리 (`learning_scene.py`·`scene_models.dart`) |

---

## 2. 10개 질문 답변

### Q1. 지금 가장 위험한 노드 종류
- **① `ConceptNode.common_misconceptions`(JSONB 자유서술, `schema/concept.py:213`)** — 플레이북이
  "노드에 절대 넣지 말 것" 1순위로 꼽은 *오개념 리스트 노드 내장*이 실재. 카탈로그(kebab)와 FK
  없이 같은 오개념을 다르게 표현 → 오염원. (진단 경로에서는 이미 미사용 — `05a` RS2.)
- **② 집계 노드(단원·소단원 860개)** — 최대 out-degree 7. retrieval에 쓰이면 hub로 attention
  오염(플레이북: L1/L2 노드는 "검색 핵심으로 쓰지 말 것").
- **③ `FormulaNode`(canonical-only·P5a 승격)** — 변형식(변수명·항순서) 노드화하면 즉시 폭발하므로
  **canonical 표현만** 노드화하고 변형은 노드화하지 않는다(변형↔canonical 동치는 런타임 SymPy 위임).
  `formula_id`는 사람 관리 안정 code(ID≠Signature)·동치 권위는 l3 SymPy 단일(재구현 금지). 플레이북
  "공식은 맨 마지막·canonical만"을 이 경계로 실현(2026-07-08 Phase 5a·`test_formula_governance` 동결).

### Q2. 미래에 폭발할 relation 종류
enum에 **선언만 되고 미적재**인 셋이 정확한 위험원(`enums.py` EdgeType):
- **`ANALOGOUS_TO`(유비/related)** — 약한 semantic. 적재 시작 시 N² 폭발·traversal 붕괴.
- **`CONTRASTS`(frequently_confused)** — 양방향·dense화 경향.
- **`TRIGGERS_DISTRACTOR`(개념↔오개념 다리)** — 두 그래프 연결 순간 cycle·context explosion 진입로.

PREREQUISITE만 쓰는 지금이 가장 건강. 위 셋은 "구조적으로 제거 불가능"할 때만, traversal=0(ranking
전용)으로 도입해야 한다.

### Q3. retrieval ambiguity가 가장 높은 영역
**오개념 매칭**(`l4/misconception/semantic/matcher.py:9-18` 자체 명시). "연속이면 미분가능" vs
올바른 "미분가능하면 연속", "f∘g=g∘f" vs "≠", "둘레↔넓이" — substring·임베딩 **모두 방향·부정·
등치를 못 가림**. judge(LLM)가 "제거만" 해서 완화하나 잔여 FP 45.5%(`04b`). 개념 retrieval은 임베딩
namespace 분리·희소 그래프라 상대적으로 안전.

### Q4. 유지보수 지옥 가능성이 높은 구조
"Single change → global rebuild" 후보 3:
- **오개념 3중 표현**(2026-06-30 작성 당시 kebab 30 / M-id 839 / JSONB) FK 없음 — 하나 고치면 나머지 침묵 drift.
- **교육과정 이중**(노드 내장 `grade_introduced`·`curriculum_version` + `CurriculumEntry` overlay)
  — 진실 출처 2개.
- **수식 파서 이중**(SymPy + mathjs) — 동치 규칙이 두 언어에 따로.

### Q5. 교육과정 변경 시 가장 취약한 부분
**노드 내장 교육과정 필드**(`Concept.grade_introduced`·`semester_introduced`·`curriculum_version`·
`subject`, `schema/concept.py:147-160`)와 **atom code 자체**('2수01-01-2'에 2022 개정 의미 박힘).
플레이북 철칙은 "concept_id는 영속, curriculum은 Overlay". 지금은 Overlay(`CurriculumEntry`)가
있으면서도 노드가 교육과정을 들고 있어, 2028 개정·다국 확장 시 둘이 충돌. → **방향**: 노드 내장
필드를 동결/제거하고 Overlay를 단일 진실로.

### Q6. visualization/plugin 교체 시 깨질 부분
대부분 안전(spec 렌더러 독립). 깨질 좁은 지점만:
- **`graph2dSpec.js`의 mathjs 변환**(`**`→`^`·`toTex`) — 렌더러별 정규화가 웹 플러그인에 살아있어
  Desmos→타 엔진 교체 시 `graph2dSpecToState` 재구현 필요.
- **`AnimationSpec.asset_id`** — Manim 사전렌더 파이프라인 종속(렌더러 변경 시 자산 재생성).
- **base64 `spec_param` 공유링크** — 고정 wire 포맷(호환성 부채).

### Q7. AI가 semantic distinction을 실패할 가능성
- **방향/부정/등치**(Q3) — 구조적.
- **"객체 vs 해석"** — atom 백본은 "기울기"는 있어도 "기울기 해석"을 별도 노드로 두지 않음 →
  LLM이 변화율/방향/속도 융합. 게다가 원자는 redaction으로 `name_ko + transfer`만 임베딩
  (`atom_graph/embedding.py:81`) → 신호가 얇아 구분 실패 위험↑.
- **canonical 오개념 판별** — 3중 표현 중 LLM이 정본을 못 가림.

### Q8. 지금 반드시 분리해야 하는 layer
- **교육과정 Overlay 완전 분리** — 노드에서 교육과정 필드를 떼고 `CurriculumEntry`를 단일 진실로.
- **오개념 정체성(identity) layer** — kebab/M-id/JSONB를 *하나의 canonical id*로 통합. 카탈로그=
  진실, 노드 `common_misconceptions`는 "시드 텍스트"로 강등(이미 진단 경로 미사용).
- **canonical 동치 authority 1개** — SymPy를 단일 권위로, mathjs/Lean은 그에 수렴(병렬 진실 금지).

### Q9. 지금 절대 premature abstraction 하면 안 되는 부분
- **AST 5계층 엔진** — SymPy로 충분. 단계검증 코퍼스·WH-S Tier3(Lean) 성숙 전 full AST는 과설계.
- **약한 semantic relation**(ANALOGOUS_TO/related) — 구체 수요 전 추가 금지.
- **TheoremNode·ProofNode** — 증명은 scope 제외(`05a` RS4·WH-S Tier3). **FormulaNode는 Phase 5a로
  canonical-only 승격됨**(공식은 마지막·canonical만·변형은 SymPy 위임 — 이 경계로 premature 회피).
- **LearningScene element의 typed union 코드젠 강제(Dart)** — 현 flat+kind가 정답(선례 0·코드젠 리스크).
- **interaction state 영속화를 spec에 흡수** — 별도 테이블로.

### Q10. 장기 생존 최소 invariant (협상 불가)
1. **ID 영속·curriculum은 ID에 없음**(code/UUID immutable).
2. **dependency 계열 엣지는 acyclic** — load 시 reachability/SCC 게이트(현재 self-loop만).
3. **노드는 의미만** — renderer/prompt/runtime/user/curriculum/오개념리스트 비내장(현재
   `common_misconceptions`·내장 교육과정이 위반).
4. **Visualization spec 렌더러 독립**(no pixel/fps/shader·`extra="forbid"` 유지).
5. **Math state ⊥ interaction/animation/UI state**(spec stateless 유지).
6. **오개념 = 단일 canonical 정체성·독립 그래프·reactive 로드만**(정상 추론 경로 진입 금지).
7. **동치 권위 1개**(SymPy 단일 진실).
8. **LLM은 전체 그래프 미열람** — bounded traversal(depth≤2·max_nodes~12) 명문화.
9. **학생 노출 전 검증 게이트 필수**(정답·낙인 필드 부재 — 현재 충족).

---

## 3. 종합

- **표현 계층(시각화·장면)은 안전** — invariant가 스키마(`extra="forbid"`·불변식·검증 게이트)로
  박혀 renderer coupling·interaction leakage·premature abstraction이 모두 낮음.
- **진짜 부채 4곳**: ① 그래프 위생(cycle 게이트 부재·약한 관계 잠재 폭발) ② 교육과정 이중화
  ③ 오개념 3중 정체성 ④ 병렬 수식 파서.
- **폭발은 시작 전** — 약한 relation 미적재·Formula/Proof 미도입·그래프 희소. 따라서 *지금이
  invariant(§2 Q10)를 코드 게이트로 박을 최적기*다. 이 부채들의 작업 항목화는 본 문서 범위 밖
  (별도 `/plan`).

---

## 4. 구현 후속 — invariant 코드 게이트 동결 (2026-06-30·PR #357)

§2 Q10 invariant 중 *회귀·미래 폭발 경로*를 코드 게이트(테스트/가드)로 동결했다. **이미 구현된
방어선은 재구현하지 않고**(적재 시점 cycle DFS·교육과정 4필드 제거·약한 relation load-time skip·
crosswalk 골격+resolver·증거저장소 shadow), **premature한 것은 도입하지 않았다**(소비처/경로 부재).

| invariant | 게이트 | 좌석 |
|---|---|---|
| Q10-③ 노드는 의미만 | 금지 필드 + 허용 화이트리스트 동결 | `tests/.../schema/test_concept.py` |
| Q1/Q8 오개념 자유서술 | `common_misconceptions` 런타임 미사용(행동+정적) + seed 전용 주석 | `test_scene_generation.py`·`test_concept_misconception_runtime.py`·`schema/concept.py` |
| Q2 약한 relation 폭발 | EdgeType 약한 값 전부 스윕→PREREQUISITE만 적재 + traversal 배제 + 어휘 보존 | `test_edge_relation_governance.py`·`test_prerequisite_traversal_integration.py` |
| Q10-⑥ 오개념 단일 정체성 | `_persist_active_set` crosswalk shadow 배선(비노출·비차단) | `l4/misconception/hypothesis_store.py` |
| Q10-⑧(부분) traversal 예산 | `MAX_PREREQUISITE_DEPTH` 단일 출처 | `l2/prerequisite_recommendation.py`·`api/me.py` |
| Q10-⑧ "전체 그래프 미열람" | LLM 경계 그래프-컬렉션 주입 금지 + traversal 예산 단일 출처 (Part 10 검토·2026-07-03) | `tests/backend/l3/test_llm_subgraph_budget_invariant.py` |

**미채택(premature/dead)**: LLM subgraph **예산 guard**(능동 max_nodes·max_tokens 절단 builder — 트리거:
graph→LLM 컨텍스트 소비처 최초 등장 시 `l2/reasoning_subgraph.py` canonical seam 신설. *불변식 자체*는
위 표에서 CI 동결됨 — Part 10 검토 §4·`docs/standards/build_roadmap_part10_review.md`)·증분 edge-add
reachability·SCC 크론·약한 타입 reject
validator·crosswalk 매핑 *자동* 적재(사람 검수 산출물·우선순위 #1·#3). **잔여(사람 검수 게이트)**:
오개념 crosswalk 매핑 채택·적재(`docs/data/misconception_crosslink_candidates.md` 검수→로더 적재→
shadow 측정→canary)·교육과정 Overlay US/IMO·`required_depth` 큐레이션.

---

## 참고
- 정본 상위: `docs/architecture/math_dsl_principles_review.md`(플레이북 검토)
- 선행: `docs/architecture/05a_learning_scene_dsl.md`·`04b_misconception_judge_graduation.md`
- 코드: `schema/concept.py`·`schema/enums.py`·`schema/visualization.py`·`l4/learning_scene.py`·
  `l4/scene_generation.py`·`l4/misconception/`·`l1/atom_graph/`·`l3/verify_step.py`·`l3/verify_answer.py`·
  `src/web/graphing-calculator/src/lib/graph2dSpec.js`·`schema/misconception_catalog.py`
- 데이터: `data/corpus/atom_graph_v1/graph.json` · 스키마: `schemas/v1.1/curriculum_entry.schema.yaml`
- 원칙: `CLAUDE.md`(의사결정 우선순위·절대 금기·표현≠의미)
- 변경 이력: v0.1 (2026-06-30 초안 — 분석만·코드/스키마 변경 0) · v0.2 (2026-06-30 — §4 구현 후속
  추가: invariant 코드 게이트 5종 동결·PR #357)
