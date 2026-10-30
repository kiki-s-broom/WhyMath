# MATH DSL 실패 모드 리스크 — pointed 질문 대응 (Q&A)

> **문서 성격**: 순수 분석 문서(신규 코드 0). 현재 MATH DSL 구조에서 10개 실패
> 모드의 발생 가능성을 실측 근거로 평가하고, 10개 pointed 질문에 직접 답한다.
>
> **작성일**: 2026-07-01 · **근거**: L1~L5 스키마·검증·하네스 코드 실측 조사
> **관계**: `math_dsl_risk_register.md`(10대 실패모드 Q1~Q10)의 **자매 문서**.
> risk_register가 "실패 모드별" 서술이라면, 이 문서는 "질문별" 대응이다. 중복
> 서술 대신 교차참조한다.
> **교차참조**: `math_dsl_risk_register.md` · `math_dsl_remediation_design.md` ·
> `math_dsl_principles_review.md` · `math_dsl_evolution.md` · `notation_contract.md`

> ✅ **2026-08-10 개정 배너(DSL 통합 점검 — `dsl_integration_gap_review.md` §5)**: 본 문서만
> 자매 문서(evolution·risk_register)의 **2026-07-08 FormulaNode 재판정 배너를 누락**해 계열 내
> 정면 충돌 상태였다 — Part A #1("FormulaNode 미도입 = 정답")·Q9-1("premature 금지")은 그
> 재판정으로 **대체**됐다(canonical 참조 노드 도입·경계는 `test_formula_governance`가 동결.
> 상세는 `math_dsl_evolution.md` 상단 배너·`concept_node_layering_decision.md` §0). 또한 Part C
> 우선순위표 중 **invariant ⑫(event_data 타입 스키마)는 완료**(`schema/event_data_contract.py`+
> 게이트), **invariant ⑩(렌더 선택 단일 진실원)은 py/js 2/3 완료**(`data/render_contract.json`
> 계약·잔여 Flutter 1/3은 MOB-14). §0 수치 스냅샷은 stale — 최신 실측은
> `dsl_integration_gap_review.md` §5 정오표(2026-08-10 기준: 그래프 2,683/2,210·kebab 64·M-id 843)가 그 시점 정본이며, 현재 건수는 `docs/data/corpus_facts.md`가 정본.

---

## 0. 배경 사실 (조사 확정 스냅샷 — 2026-07-01 작성 기준)

| 구조 | 실측 |
|---|---|
| L1 그래프 | (2026-07-01) 노드 2,697(단원 217·소단원 643·원자 1,837), 엣지 2,213 **전량 `PREREQUISITE`·strength 0.8 균일** |
| EdgeType | 6종 정의(`schema/enums.py`), **PREREQUISITE만 적재** — 약한 5종 load-time skip + 거버넌스 테스트(`test_edge_relation_governance.py`) |
| 오개념 | (2026-07-01) 3중 표현 — kebab 30(런타임 정본 `l4/misconception/catalog.py`)·M-id 839(콘텐츠 `schema/misconception_catalog.py`)·JSONB(`Concept.common_misconceptions`, 런타임 미사용). **FK 없음**, crosswalk N:M + read-time resolver |
| 임베딩 | **단일 pgvector, namespace 분리 없음**(`l1/embedding_primitives.py`) — concept/atom/misconception 동일 벡터공간. 방향맹 매처(둘레↔넓이 코사인 동일) 실측, 과거 FP 45.5% *(→ 정정 2026-07-02 참조 — 두 문제의 융합 서술)* |
| Cycle | load-time DFS 게이트(`l1/atom_graph/populate.py`) + 파이프라인 validate. 모델 불변식은 self-loop만. **런타임 reachability/SCC 게이트 없음** |
| 렌더러 | spec 렌더러 독립(노드에 fps/shader/pixel 필드 0, `extra="forbid"`). 그러나 **렌더 선택 로직 3곳 산재**(`scene_renderer.dart`·`GraphingCalculator.jsx`·WebView) |
| 교육과정 | CurriculumEntry 단일 진실화 완료(PR #350). ~~그러나 `Problem`이 아직 `Curriculum` enum 참조(슬라이싱 미완)~~ *(→ 정정 2026-07-02 — 오등록·문항 본질 속성이라 유지가 정답)* |
| AST | SymPy(권위 `l3/symbolic_equivalence.py`)/mathjs(렌더)/`l3/speech_parse.py`(커스텀 AST)/MathLive. golden test는 SymPy↔mathjs만, ~~speech 파서는 notation_contract 밖~~ *(→ 정정 2026-07-02 — speech는 별도 표기 계층·자체 골든 검증·"계약 밖"이 설계상 정상)* |

---

## Part A. 10개 실패 모드 발생 가능성

범례: 🔴높음 🟠중간 🟡낮음 🟢방어됨

| # | 실패 모드 | 확률 | 방어 현황 | 잔여 위험(축) |
|---|---|---|---|---|
| 1 | **node explosion** | 🟡 | 원자 백본·`extra=forbid`·"노드=의미만" 게이트(`test_concept.py`) | "객체 vs 해석" 미분화 atom 세분화 시 폭발. `FormulaNode` 미도입 = 정답 |
| 2 | **relation explosion** | 🟠(잠재) | 약한 5종 load-time skip + 거버넌스 테스트 | CONTRASTS·TRIGGERS_DISTRACTOR가 오개념 구동으로 N² dense화 |
| 3 | **semantic ambiguity** | 🔴 | 원자 백본 입도 개선 진행 | "객체(기울기) vs 해석(변화율·속도·방향)" 단일 노드 융합 |
| 4 | **renderer coupling** | 🟢spec / 🟠선택 | spec 렌더러 독립·`extra=forbid` | 렌더 **선택** 로직 3곳 산재 → 신규 type/엔진 = 3곳 동기 수정 |
| 5 | **interaction state leakage** | 🟢상태 / 🟠계약 | spec stateless·런타임 분리 | `event_data` JSONB 자유형·concept/scene_id 호스트 주입 무검증 |
| 6 | **curriculum inconsistency** | 🟢 | CurriculumEntry 단일화·Concept 필드 제거(PR #350) | ~~`Problem`의 `Curriculum` enum 잔여~~(정정 2026-07-02 — 문항 본질 속성·유지)·US/IMO overlay 미구축 |
| 7 | **AI retrieval failure** | 🟠→🔴 | 본문 redaction·reviewed_only 게이팅 | **단일 임베딩 namespace**·방향맹·집계 hub 노드 attention 오염 |
| 8 | **cyclic dependency** | 🟡 | load-time DFS + 파이프라인 validate | 런타임 reachability/SCC 부재 → 증분 edge-add 시 다중홉 cycle 무방비 |
| 9 | **AST duplication** | 🟢 | notation_contract golden test(SymPy↔mathjs) + speech 자체 골든(`test_speech_rules.py`) | ~~speech 파서 계약 밖 → 낭독 AST drift~~ *(정정 2026-07-02 — speech는 별도 표기 계층·자체 골든 검증·drift는 유니코드 위첨자 1점·활성 경로 0)* |
| 10 | **misconception overlap** | 🔴 | crosswalk 골격·resolver·shadow 배선 | 3중 표현 FK 없음·매핑 사람검수 미완·canonical 미확정 |

**한 줄 종합**: 표현 계층(시각화·장면·"노드=의미")은 invariant가 스키마로 박혀 견고.
**진짜 위험은 (a) 의미 축**(오개념 3중 표현·방향맹 임베딩·객체 vs 해석)과 **(b) 그래프
위생 축**(런타임 cycle 게이트·relation 폭발 잠재)에 집중된다. 폭발은 대부분 *아직
시작 전* — 지금이 invariant를 박을 적기다.

---

## Part B. 10개 질문 직접 답변

### Q1. 지금 구조에서 가장 위험한 노드 종류

1. **집계(hub) 노드 — 단원 217 + 소단원 643 = 860개.** 검색 배제 규칙이 없어
   retrieval hub로 attention을 흡수, 원자 신호를 오염시킬 수 있다(측정 필요). ← 최우선
2. **`Concept.common_misconceptions`(JSONB 내장 오개념 리스트).** 플레이북 금기 #1.
   현재 런타임 미사용·정적 게이트로 동결됐으나 *존재 자체*가 재유입 유혹이다.
3. **미분화 원자** — "기울기"는 있으나 "기울기 해석"이 없어 LLM이 변화율/속도/방향을
   한 노드로 융합한다(Q7과 직결).

### Q2. 미래에 폭발할 relation 종류

1. **CONTRASTS · TRIGGERS_DISTRACTOR(오개념 구동).** 오개념 진단이 성숙하면 "혼동
   개념"·"유발 선택지" 엣지 수요가 생기고, 이는 개념 × 오개념 곱으로 **N² dense화**
   한다. 현재 load-time skip으로 동결 — 해제 순간이 최대 폭발점.
2. **ANALOGOUS_TO** — "비슷한 사고"는 주관적이라 무한 확장 경향.
- **방어 원칙**: 이 3종은 *적재 금지 유지*, 필요 시 질의 시점 파생(derive)으로만.

### Q3. retrieval ambiguity가 가장 높은 영역

1. **오개념 임베딩 매칭.** 단일 namespace + 얇은 텍스트 + 방향맹(둘레↔넓이 코사인
   동일, "연속 ⇒ 미분가능" vs 정답 "미분가능 ⇒ 연속" 반대 미구분). 과거 FP 45.5%. ← 최고
2. **집계 노드 검색** — hub가 상위 랭크를 점유.
- **근본**: concept/atom/misconception이 **같은 벡터공간·이질 포맷**(개념 =
  name+metaphor, 원자 = name+transfer, 오개념 = canonical+wrong_thinking).

### Q4. 유지보수 지옥이 발생할 가능성이 높은 구조

1. **렌더 선택 로직 3곳 산재**(schema 계약 ≠ 선택 규칙). 신규 `VisualizationType`·렌더
   엔진 교체 시 `scene_renderer.dart`·`GraphingCalculator.jsx`·WebView를 동기 수정
   해야 하며 단일 진실원이 없다 → breaking change 지옥. ← 최우선
2. **`event_data` 자유형 JSONB** — payload 스키마 미명시로 L2/L4 행동분석이 이벤트마다
   개별 해석을 요구한다.

### Q5. 교육과정 변경 시 가장 취약한 부분

1. ~~**`Problem`의 `Curriculum` enum 잔여.** Concept에선 제거됐으나 Problem이 아직
   참조 — 개정 시 outdated 값 잔류·이중 진실. 슬라이싱 완주 필요. ← 최우선~~
   *(→ 정정 2026-07-02: 오등록. 문항은 특정 개정판을 위해 저작된 콘텐츠라 curriculum_version은
   이중 진실이 아니라 본질 속성이며, L6 게이트 ③의 살아있는 소비처다. 제거·Overlay 이관 기각·유지 확정.)*
2. **US/IMO overlay 열 미구축** + `national_standard_codes` 결합 — 다국 확장 시 취약.
- overlay 설계 자체는 견고하다 — 취약점은 *잔여 결합*이지 구조가 아니다.

### Q6. visualization/plugin 교체 시 깨질 부분

1. **렌더 선택 3곳**(Q4) + **inner spec `extra="allow"` 자유 JSON.** `Graph2dSpec`이
   mathjs 표기(`^`)를 가정 → Desmos → Wolfram 교체 시 계약은 유지되나 3곳 구현을
   수정해야 한다. 플랫폼별 동일 type 다른 해석(Flutter = WebView, 웹 = Canvas) 위험.
- **방어**: `VisualizationType` → 플랫폼 capability matrix를 코어 단일 진실원으로.

### Q7. AI가 semantic distinction을 실패할 가능성이 있는 부분

1. **객체 vs 해석** — 기울기/변화율/속도/방향을 한 원자로 융합.
2. **방향·부정·등치** — 오개념 매칭에서 함의 방향("A ⇒ B" vs "B ⇒ A")·부호("−f" vs
   "f") 미구분.
3. **단일 임베딩 namespace** — concept/atom/misconception 혼입으로 의미 경계가 흐려진다.

### Q8. 지금 반드시 분리해야 하는 layer

1. **임베딩 namespace 분리(concept / atom / misconception).** 단일 pgvector store 내
   *논리 namespace*로 격리 — 방향맹·혼입 오염의 근본 해소. ← 최우선 분리
2. **렌더 선택 layer** — 산재 로직을 코어 capability matrix로 추출.
- 참고: 수학 로직의 클라 누출·렌더 라이브러리의 코어 침범은 조사 결과 **0** — 이미
  분리돼 있다(L5는 dumb renderer, 코어에 mathjs/three.js import 없음).

### Q9. 지금 절대로 premature abstraction 하면 안 되는 부분

1. **`FormulaNode` / 재작성규칙 트리**(risk Q3·Q8) — 변형식 노드화 = 즉시 폭발.
2. **AST 5계층 의미 엔진** — `SolutionStep.sympy_verified` + WH-S 3Tier가 이미 함의.
3. **약한 relation 적재** — 소비처 생기기 전 금지.
4. **런타임 SCC 크론 / 증분 edge-add reachability** — 현재 소비처(증분 편집) 부재라 dead.
5. **범용 렌더 플러그인 마켓** — 슬라이스 89 위반.
- **원칙**: *소비처가 생길 때* 도입한다. 지금 없는 게 정답이다.

### Q10. 장기 생존에 필요한 최소 invariant

`risk_register.md` Q10의 8개 + 이번 조사로 추가 4개(총 12):

**기존 8 (유지·강화)**
1. ID 영속·curriculum은 ID에 없음 (code/UUID immutable)
2. dependency 계열 엣지 **acyclic** — load 시 게이트(현재 self-loop + DFS·**런타임
   reachability는 증분 편집 도입 시**)
3. 노드는 의미만 — renderer/prompt/runtime/curriculum/오개념리스트 **비내장**
4. Visualization spec 렌더러 독립
5. Math state ⊥ interaction/animation/UI state
6. 오개념 = **단일 canonical 정체성**·독립 그래프·reactive 로드만
7. 동치 권위 1개 (SymPy 단일)
8. LLM은 전체 그래프 미열람 — bounded traversal(depth ≤ 2·max_nodes ~12) 명문화

**추가 4 (이번 조사 근거)**
9. **임베딩 namespace 분리** — concept/atom/misconception 벡터 경계 불변식 *(→ 정정 2026-07-02 — 물리 분리는 기존재·논리 경계가 실체, 구현 완료)*
10. **렌더 선택 단일 진실원** — 플랫폼 capability matrix를 코어에, 산재 금지
11. ~~**모든 수식 AST는 notation_contract 계약 안** — speech 파서 포함(현재 이탈)~~
    *(→ 정정 2026-07-02: speech는 별도 표기 계층(LaTeX 프레젠테이션)·자체 골든 정본이라 계약 3자
    편입은 카테고리 오류. 경계 명문화로 충족 — notation_contract.md §5·구현 완료.)*
12. **interaction `event_data` 타입 스키마** — 자유 JSONB 금지, payload 타입별 계약

---

## Part C. 우선순위 요약 (무엇부터 박을 것인가)

의사결정 우선순위(CLAUDE.md §의사결정: 학생 안전 > 법·윤리 > 교수학 > 학습효과)에
따라, **오개념 정체성**(잘못된 매핑 = 오도된 코칭 = 학생 안전 직결)이 최우선이다.

| 순위 | 작업 | 근거 실패모드 | 성격 |
|---|---|---|---|
| 1 | 오개념 canonical ID 수렴(crosswalk 사람검수 → canary) | #10·#3 | 부채 상환(진행 중) |
| 2 | 임베딩 namespace 분리(논리 격리) | #7·#3 | invariant 신설(#9) |
| 3 | 렌더 선택 단일 진실원(capability matrix) | #4·#6 | invariant 신설(#10) |
| ~~4~~ | ~~speech 파서를 notation_contract 안으로~~ | #9 | ~~invariant 신설(#11)~~ → **경계 명문화로 충족**(정정 2026-07-02·notation_contract.md §5) |
| ~~5~~ | ~~`Problem.Curriculum` enum 제거(슬라이싱 완주)~~ | #6 | ~~부채 상환~~ → **오등록·유지 확정**(정정 2026-07-02) |
| 6 | interaction `event_data` 타입 스키마 | #5 | invariant 신설(#12) |
| — | 런타임 SCC/reachability | #8 | **미도입**(소비처 생길 때) |

> **핵심**: 이 문서의 발견 대부분은 *지금 코드를 고치라*가 아니라 *지금 invariant를
> 명문화·동결하라*이다. 표현 계층은 이미 스키마 불변식으로 안전하다. 남은 것은
> **의미 축(오개념·임베딩)**과 **그래프 위생 축(cycle·relation)**의 invariant를,
> 폭발이 시작되기 전인 지금 박는 일이다. premature abstraction은 피하되(Q9), invariant
> 게이트는 지금 세운다.

-----

## 정정 (2026-07-02 — invariant ⑨ 실측 교정·구현 랜딩)

원문(작성일 2026-07-01)의 임베딩 행과 invariant ⑨ 서술은 **서로 다른 두 문제를 한 문장에 융합**하고 있어 실측으로 교정한다(원문은 스냅샷 보존).

1. **"namespace 분리 없음·동일 벡터공간"의 실체**: 실측 결과 임베딩 3테이블(`misconception_embedding`·`concept_embedding`·`atom_embedding`)은 **이미 물리 분리**되어 있고 cross-namespace 질의도 0이다(`math_dsl_retrieval_analysis.md` "테이블 분리"·risk_register Q3와 정합). 실제 부채는 ① 논리 판별자(subject 축) 부재 ② cross-table 코사인을 막는 실행 계약 부재였다. **구현 완료(2026-07-02)**: 3테이블 subject 컬럼(server_default '수학'·Alembic `b6c7d8e9f0a1`·재임베딩 0) + 공간 식별 (provider, model, subject) 3축 + 거버넌스 게이트 13건(`tests/backend/l1/test_embedding_namespace_governance.py` — 9지점 대칭·cross-table 코사인 allowlist·텍스트 불변). **불변식 정본은 코드**: `l1/embedding_primitives.py` docstring("namespace = 테이블(kind) × subject") + 거버넌스 테스트.
2. **"방향맹 매처(둘레↔넓이)·FP 45.5%"는 별개 트랙**: 이는 오개념 의미 매칭 *내부*의 임베딩 방향맹 문제(`l4/misconception/semantic/matcher.py` 자체 문서화·완화는 LLM-judge/NLI — `04b` 트랙)이지 namespace 혼입이 아니다. invariant ⑨ 충족 여부와 무관하게 별도로 추적한다.

### 정정 추가 (2026-07-02 — Q5-1 `Problem.Curriculum` enum 오등록)

Q5-1·상단 표(교육과정 행)·상환 목록 #5의 "`Problem`의 `Curriculum` enum 잔여 → 슬라이싱 미완·상환 필요"는 **오등록**이다(원문 스냅샷 보존·해당 지점에 포인터).

- **실측**: `Problem.curriculum_version`은 죽은 필드가 아니라 L6 학교진도 게이트 ③(2015/2022 개정 혼입 방지·`l6/school_progress/gating.py`)의 살아있는 정합 기준이자 L5 API 파라미터(`api/gating.py`)다. Concept의 curriculum 제거가 안전했던 *전제*가 바로 "게이팅은 Problem.curriculum_version을 쓴다(Concept과 독립)"였다(rev `f3a4b5c6d7e8` docstring).
- **원칙 구분**: 플레이북 "개념은 영속·교육과정은 Overlay"는 *개념 노드*(영속 자산) 대상이다. **문항(Problem)은 특정 개정판을 위해 저작된 콘텐츠**라 curriculum_version이 이중 진실이 아니라 문항 고유 속성이다. CurriculumEntry Overlay는 concept 중심이라 Problem이 직접 닿지도 않는다(Problem→concept 다단 조인·KR-only·str/enum 불일치).
- **판정**: 제거·Overlay 이관 **기각**, **유지가 정답**. 정본은 코드 docstring(`Curriculum` enum·`Problem.curriculum_version`)에 못박음. 부채 상환 목록에서 삭제.

### 정정 추가 (2026-07-02 — invariant ⑪ speech 파서 "계약 이탈" 오등록)

상단 AST 행·실패모드 #9·invariant #11·상환 목록 #4의 "speech 파서가 notation_contract 밖 → 낭독
AST drift·계약 안으로 편입 필요"는 **오등록**이다(원문 스냅샷 보존·해당 지점에 포인터).

- **실측**: speech(`l3/speech_parse.py`·`l3/speech.py`)는 *프레젠테이션 LaTeX*(`\frac`·`\sqrt{}`)를
  입력받아 *한국어 낭독 문자열*을 산출하는 **별도 표기 계층**이다. notation_contract는 *ASCII 수식*의
  SymPy↔mathjs *수치 상호운용*(numeric·equivalence)이라 입력 언어·산출·권위가 모두 달라 speech를
  fixture에 넣을 케이스 형(型)이 없다 — 교차검증 원리적 불가.
- **미검증 아님**: speech는 자체 골든 코퍼스(`tests/backend/l3/test_speech_rules.py`
  `HIGH_SCHOOL_GOLDEN` 38케이스 + ≥30 크기 게이트 + 모호성·정직성 테스트)로 검증된다 — 이것이
  speech의 표기 계약이다. 자체 AST·hermetic(SymPy/mathjs 미호출)은 시각 그룹핑의 청각 보존을 위한
  *의도적* 설계(`speech_parse.py` 주석).
- **drift 실증 = 유니코드 위첨자 1점·활성 경로 0**: `to_sympy_source`는 `²`→`**2`로 접지만 speech는
  미지 문자로 "알 수 없는 기호" 처리. 그러나 같은 문자열을 두 경로에 동시에 흘리는 소비처가 없고
  (speech는 LaTeX `x^2` 입력·L4/L5 소비 배선 0) 활성 위험이 아니다. 소비처 생길 때 `_SUPERSCRIPT`
  매핑과 정합(그 전까지 premature).
- **판정**: ⑪은 "계약 3자 확장"(카테고리 오류)이 아니라 **경계 명문화**(`notation_contract.md` §5)로
  충족. speech는 이 계약과 별개의 자족 표기 계층이며 그 계약은 `test_speech_rules.py` 골든이다.
  #9는 🟠→🟢, invariant #11·상환 #4는 경계 명문화로 상환 대체.
