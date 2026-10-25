# Math DSL — AI Retrieval 관점 심층 분석

> **상태**: 분석(analysis) · **계층**: 횡단(L1 데이터 · L3 RAG · L4 오개념) · **작성일**: 2026-07-01
> **정본 상위**: `math_dsl_risk_register.md`(10대 실패모드 일반 레지스터). 본 문서는 그중
> *retrieval / RAG* 축만 떼어 **AI 검색 관점 10개 렌즈 + 4개 전략**으로 심화한 동반 문서다.
> **근거**: L1 개념그래프·임베딩·오개념 코드 정밀 조사(2026-07-01, 파일:라인 인용).
> **범위**: 분석 + *이번 PR 안전 결선*(§전략 D 일부 실제 반영). 대규모·조기 항목은 §후속 권고로 분리.

> ✅ **2026-08-10 개정 배너(DSL 통합 점검 — `dsl_integration_gap_review.md` §5)**: §4의 전제
> **"skill 엔티티는 존재하지 않는다"는 무효**가 됐다 — 리치 Part 2 전면 채택
> (`concept_node_layering_decision.md` §0·2026-07-03)으로 `skill_node`·`problem_type_node`·
> `formula_node`·`strategy_node`·`solution_node` 5종 ORM 노드가 실재한다("승격 여부는
> `principles_review` 결정 대기" 포인터도 그 결정으로 종결). §4의 *혼동 시나리오 분석* 자체는
> 여전히 유효하나, 처방("cognitive_type 분산으로 감당")은 노드 승격 이후 체계로 대체됐다.
> §0 "traversal 조회 코드 부재"도 이후 `l2/prerequisite_recommendation.py`(depth 5·breadth 64
> 가드 동반)로 대체 — 본 문서가 요구한 가드-선행 원칙은 지켜졌다.

## 0. 현재 retrieval 스택 스냅샷

| 축 | 현황 | 근거 |
|---|---|---|
| 벡터 store | pgvector(Postgres 16 통합·슬98) — 개념/오개념 **테이블 분리** | `l1/.../embedding.py`(`concept_embedding`)·`l4/.../pgvector_index.py`(`misconception_embedding`) |
| 임베딩 입력 | 개념은 **안전필드 3개만**(`name_ko`·`metaphor`·`accepted_expressions`) | `embedding.py:63` `_SAFE_TEXT_FIELDS` |
| 검색 랭킹 | 코사인 유사도 top_k — **임계값 없음**(점수 컷 = 소비처 몫) | `retrieval.py`(원본 주석) |
| 검색 게이팅 | `reviewed_only`(검수)만 존재 → **본 PR에서 `min_similarity`·`domain` 추가** | `retrieval.py:search_concepts` |
| 공간 격리 | `(provider, model)` 행만 비교(모델 혼재 방지) | `embedding.py:233-236` |
| 관계 조회 | `concept_edge` **1-hop 선수만**, 그래프 traversal 조회 코드 **부재** | `backend_edge.py:23-26` |
| 키 공간 | 개념=UC `{TRACK}-{AREA}-{NNN}`·오개념=**3중 네임스페이스**(kebab/`ATOM:`/`M####`, FK 0) | `schema/enums.py`·`misconception_catalog_v1.md` |
| AST | 명시 AST 없음 — SymPy(py)·mathjs(js) 각자 파싱, `notation_contract.json`가 유일 계약 | `data/notation_contract.json` |

**한 줄 평**: *임베딩·격리는 견고, 그러나 검색은 "무임계 top_k"라 실패가 침묵하고, 오개념 키 공간과 관계 순회는 무방비.* retrieval 계층은 대부분 *시작 전*이라 지금이 안전 계약을 박을 적기다.

---

## 1. Retrieval ambiguity가 발생할 node 종류

**현재 구조 근거**
- Concept `code`는 `{TRACK}-{AREA}-{NNN}`(`schema/concept.py`). 동일 수학 대상이 학년별로 **별도 노드**로 존재한다: `ELEM-FUNC-*`("함수"·직관), `MID-FUNC-*`, `HIGH-FUNC-*`. `name_ko`는 셋 다 "함수"일 수 있다.
- 오개념은 3중 네임스페이스 병존(2026-07-01 작성 당시 kebab 30 · `ATOM:` 1,837 · `M####` 839, FK 0). 같은 오개념이 서로 다른 키로 최대 3번 존재.
- SolutionPath.`concept_sequence`는 **순서 있는 list**(`solution_path.schema.yaml`). 검색이 이를 set으로 취급하면 대수풀이/기하풀이가 같은 이웃으로 뭉친다.
- Hint는 동일 step에 `level` 1·2·3 세 행(`hint.schema.yaml`). level 무시 회수 시 "거의 정답"(level 3)이 조기 노출될 수 있다.

**실패 시나리오**: 고1 학생이 "함수가 뭐야"를 물음 → `search_concepts`가 `name_ko="함수"` 세 트랙 노드를 유사도 동률로 회수 → L3가 초등 직관 카드와 고교 정의를 섞어 주입 → 학년 부정합 설명.

**심각도**: 🟠 중상 — 교수학 정확성(우선순위 3) 침해. 안전(1)까지는 아니나 학년 오정합은 잦다.

**완화책**
- (즉시·본 PR) `search_concepts(domain=...)` 도메인 스코프로 호출자가 트랙/영역을 좁힘.
- (후속) `concept_sequence`·Hint는 *순서/level을 키에 포함*한 회수 계약. 오개념 네임스페이스 단일화(§전략 A).

---

## 2. Embedding collision 가능성이 높은 concept

**현재 구조 근거**: 임베딩 입력이 `join_embedding_text(name_ko, metaphor, accepted_expressions)` 뿐(`embedding.py:63, 92`). description·formal_definition은 redaction으로 **의도적 배제**(본문 저작권). 결과적으로 임베딩 벡터가 얹히는 텍스트가 **매우 짧다** → 판별 신호 부족.

**collision 고위험 3군**
1. **학년 변형** — "함수"(초/중/고), "극한"(수Ⅱ/미적분): `name_ko` 동일 + 은유 유사 → 코사인 근접.
2. **표기 변형** — `EdgeType.notation_variant`/`EXTENDS`로 이어질 개념쌍(예: `∑` 표기 vs 전개식)이 임베딩상 거의 동일.
3. **technique 개념 vs skill 명칭** — `cognitive_type=TECHNIQUE` 개념("부분분수 분해")이 문제풀이 "스킬" 질의와 충돌(§4).

**실패 시나리오**: L4가 오답에서 "극한" 개념을 회수하려 함 → 수Ⅱ "극한"과 미적분 "극한"이 유사도 0.98/0.97로 반환 → 잘못된 선수그래프로 진단.

**심각도**: 🔴 높음 — collision은 §3·§5의 하류 실패를 모두 증폭하는 근원.

**완화책**
- (즉시·본 PR) `domain` 스코프로 collision 창을 도메인 내로 축소.
- (후속·A/B 후) 임베딩 텍스트에 domain/level *안전 문맥* 보강(전량 재임베딩 유발 + within-domain 판별력 저하 우려 → §후속 권고).

---

## 3. Semantic search 실패 가능성이 높은 relation

**현재 구조 근거**: `search_concepts`는 원래 **임계값이 없었다** — "임계값 필터는 없다(순수 랭킹 — 점수 컷은 소비처 몫)". 매칭이 사실상 없어도 top_k를 채워 반환.

**위험 relation**
- `CONTRASTS`(혼동쌍) — "정의역 vs 치역"처럼 *일부러 헷갈리는* 개념은 임베딩상 가깝다. 무임계 회수는 대조개념을 **동의개념으로 오제공**.
- `ANALOGOUS_TO`(유사 사고) — 유추는 유용하나 무차별 회수 시 무관 개념 유입.
- 오개념 substring-AND 매칭의 거짓양성(`concept_graph_dataset_v1.md` — NFKC 정규화 미도입).

**실패 시나리오**: 학생 질의에 진짜 근접 개념이 없음(off-topic) → 그래도 top_k=5가 채워짐 → L3 RAG가 무관 개념을 근거로 "환각적" 설명 생성. **검증 없는 노출**(CLAUDE.md 절대 금기)로 직결.

**심각도**: 🔴 높음 — 안전(우선순위 1: 환각 노출) + 교수학(3) 동시 침해.

**완화책 (즉시·본 PR)**: `search_concepts(min_similarity=...)` — 근접도 미만 히트 제외로 semantic 실패의 **침묵 전파를 좌석에서 차단**. 정렬은 유지, 게이팅은 필터(결과가 top_k보다 적을 수 있음 = 정직 신호). CONTRASTS는 §전략 B(관계 프루닝)로 임베딩 회수와 분리.

---

## 4. concept vs skill vs problemType 혼동 가능성

**현재 구조 근거**
- **skill 엔티티는 존재하지 않는다.** 그 역할은 성취기준(NCIC 코드)·`cognitive_type`(DEFINITION/THEOREM/**TECHNIQUE**/PATTERN/VISUAL_REASONING)으로 분산.
- problemType = `QuestionFormat` 10유형(`schema/enums.py` — 객관식/단답형/…/재수전용형) + `ProblemConcept.role`(PRIMARY/SUPPORTING/IMPLICIT/TESTED).
- 세 축이 **같은 임베딩 공간을 공유하지 않지만**, 회수 결과에 타입 표식이 없다(`ConceptSearchHit`엔 concept_id·similarity·안전메타만).

**실패 시나리오**: "부분분수 분해하는 법"(skill/technique 질의) → 개념 노드 "부분분수"(DEFINITION)만 회수 → 절차(TECHNIQUE) 개념·해당 problemType이 누락되어 "정의만 알려주고 방법은 안 알려주는" 응답.

**심각도**: 🟠 중상 — 교수학 정확성(3)·UX(5).

**완화책**
- (부분·본 PR) `domain` 스코프로 최소한 영역 혼동 축소.
- (후속) 회수 결과에 `cognitive_type`·`role` 표식 노출(안전필드) → 소비처가 concept/technique/problemType을 구분. skill을 별 엔티티로 승격할지는 `math_dsl_principles_review.md` 결정 대기.

---

## 5. Misconception retrieval failure 가능성

**현재 구조 근거**
- 오개념 **3중 네임스페이스**(2026-07-01 작성 당시 kebab 30·`ATOM:` 1,837·`M####` 839), 상호 **FK 0**. `Concept.misconception_codes`의 dangling 참조는 **경고만**(`schema/concept.py`, Phase 1 30개만 실재).
- 오개념 임베딩은 **별 테이블**(`misconception_embedding`), 개념 임베딩(`concept_embedding`)과 **교차조회 좌석 부재**. 두 인덱스는 서로를 모른다.

**실패 시나리오**: L4가 학생 오답 → 오개념 회수 → `M0123` 반환. 그런데 개념↔오개념 연결이 kebab 코드로만 걸려 있어 그 오개념이 어느 개념 노드에 붙는지 해석 불가 → 개념 점화 지도·소크라테스 카테고리 선택에 반영 실패(오개념을 찾고도 못 쓴다).

**심각도**: 🔴 높음 — 교수학 핵심(오개념 진단)이 무력화. "모든 오답은 오개념 후보 분석"(CLAUDE.md ALWAYS) 위반.

**완화책 (후속·대규모)**: 단일 네임스페이스 수렴(§전략 A) + 개념/오개념 인덱스 교차조회 좌석. 데이터 마이그레이션이라 본 PR 범위 밖(§후속 권고).

---

## 6. Graph traversal depth 폭발 위험

**현재 구조 근거**: traversal 조회 코드는 **아직 없다**(`backend_edge.py`는 *적재*만, 선수 1-hop). 그러나 `EdgeType`은 6종 선언(PREREQUISITE·COMPOSED_OF·ANALOGOUS_TO·EXTENDS·CONTRASTS·notation_variant)이고, 현재 graph.json은 전량 prerequisite다. **6종 전량 적재 후 무제한 순회하면** 폭발한다.

**폭발 동인**
- PREREQUISITE·COMPOSED_OF는 DAG(방향·비순환)지만, ANALOGOUS_TO·CONTRASTS는 **대칭적 성격**(A~B면 B~A) → 혼합 transitive closure는 사실상 완전그래프로 발산.
- 적재 파이프라인에 **사이클 검출 게이트 없음**(self-loop만 차단, `risk_register` §0). 향후 CONTRASTS가 사이클을 유입.

**실패 시나리오**: "이 개념의 관련 개념 전부"를 무제한 BFS → ANALOGOUS_TO 경유로 그래프 절반 회수 → context window 폭발(§7) + 무의미.

**심각도**: 🟡 낮음(현재·미구현) → 🔴 높음(구현 시 무방비).

**완화책 (후속·traversal 구현 시)**: §전략 C — `max_depth`·`max_fanout`·`edge_type` allowlist·사이클 가드를 조회 좌석에 *구현 전에* 계약으로 박기.

---

## 7. AI context window 낭비 요소

**현재 구조 근거**
- 무임계 top_k(§3) → 무관 개념까지 프롬프트 주입.
- `concept_sequence` 순서열 전량 주입(SolutionPath) — 긴 풀이는 수십 개념.
- Hint 3 level 중복 주입 가능(§1).
- `Problem` 50+필드(IRT·다차원 난이도·persona_fit 등)를 선별 없이 주입하면 대부분이 RAG에 무의미.

**실패 시나리오**: L3 RAG가 top_k=10 × (개념 안전메타 + concept_sequence + Hint 3단계)를 통째로 주입 → 토큰 폭증·핵심 신호 희석 → 응답 품질 저하 + 비용 증가.

**심각도**: 🟠 중간 — 비용(6)·UX(5), 그리고 신호 희석으로 정확성(3) 간접 침해.

**완화책**
- (즉시·본 PR) `min_similarity`로 무관 히트 컷 → 주입량 자연 감소.
- (후속) 회수 결과 프로젝션 최소화(안전메타만·이미 `ConceptSearchHit`가 본문 0), Hint는 요청 level만, Problem은 RAG 전용 요약 뷰.

---

## 8. Symbolic similarity vs educational similarity 충돌

**현재 구조 근거**: `notation_contract.json`이 **SymPy를 동치·정오의 단일 권위**로 못박음(`authority: backend SymPy`). 반면 개념 유사성은 embedding/`concept_sequence`가 담당(교육적 유사). 둘은 **다른 축**이다.
- `equivalence_cases`: `(x+1)^2` ≡ `x^2+2x+1`(symbolic 동치) — 그러나 교육적으로는 "전개"라는 *다른 스킬*.
- `freshman_dream`: `(a+b)^2` ≠ `a^2+b^2` — symbolic 비동치지만 **오개념으로는 매우 가까움**(§5 회수 대상).

**실패 시나리오**: 다중풀이 동치 판정에서 symbolic 동치(SymPy)만 보면 "전개 전/후"를 같은 풀이로 병합 → 교육적으로 다른 접근을 하나로 뭉갬. 반대로 embedding만 보면 오답 `a^2+b^2`를 정답 근처로 회수. MEMORY PRD 허점 ⑤("concept_sequence는 동치의 필요·충분조건 아님") 그대로.

**심각도**: 🟠 중상 — 교수학(3). 다중풀이 본질적 동치 체험은 제품 핵심 가치.

**완화책 (후속)**: 두 유사도를 *분리 저장·분리 회수*하고 결합은 명시 규칙 + 사람 검수(MEMORY 권고). symbolic 동치는 SymPy 게이트, educational 유사는 embedding — 절대 한 점수로 융합하지 않는다.

---

## 9. AST retrieval vs semantic retrieval 충돌 가능성

**현재 구조 근거**: 명시 수식 AST가 없다 — SymPy(py)·mathjs(js)가 **각자 파싱·정규화**하고 `notation_contract.json`가 canonical만 좁게 계약(caret `^`·명시 `*`, **implicit multiplication 미지원**). `figure.spec`(도형 구조 명세)도 별도 구조 검색 축.

**실패 시나리오**: 같은 문항에 대해 (a) AST/구조 검색은 "같은 도형·같은 수식 형태" 이웃을 반환하고 (b) 벡터 의미검색은 "같은 개념" 이웃을 반환 → **서로 다른 추천 집합**. 게다가 `2x`(implicit)는 계약 밖이라 AST 정규화와 embedding 입력 정규화가 어긋나면 같은 수식이 다른 키로 색인.

**심각도**: 🟡 낮음(현재·AST 미구현) → 🟠 중간(구현 시).

**완화책 (후속)**: AST 회수와 semantic 회수의 *역할 분담 명문화*(구조 일치 vs 개념 일치), 정규화 파이프라인 단일화(`notation_contract` 확장 — implicit mult·unicode를 계약 안으로).

---

## 10. Future RAG system에서 가장 위험한 구조 (종합 랭킹)

| 순위 | 위험 | 왜 최악인가 | 연쇄 영향 |
|---|---|---|---|
| ① | **무임계 top_k**(§3) | 실패가 *침묵*한다 — off-topic 질의에도 결과가 채워져 환각을 검증처럼 포장 | 안전(1) 직접 침해 → §7 낭비 증폭 |
| ② | **오개념 3중 네임스페이스**(§5) | 이미 진 부채(FK 0) — 오개념을 찾고도 개념에 못 붙임 | 교수학 핵심 무력화 |
| ③ | **짧은 임베딩 텍스트 collision**(§2) | §1·§3·§5의 하류 실패를 모두 증폭하는 근원 | 전 위험의 공통 인자 |

**핵심 통찰**: ①은 *좌석 한 곳*(이번 PR)에서 막을 수 있는 가장 값싼 안전장치였고, ②③은 데이터/재임베딩이 걸린 구조 부채라 별도 슬라이스가 필요하다. **"싼 안전장치 먼저, 구조 부채는 계획적으로"** 가 retrieval 로드맵의 원칙.

---

## 전략 A — Retrieval-safe naming

- **개념**: UC `{TRACK}-{AREA}-{NNN}` 유지(이미 좋음). collision 방어는 *이름*이 아니라 *도메인 스코프*(§전략 D)로.
- **오개념**: 3중 네임스페이스 → **단일 접두 규약**(`ns:` 예: `mis:kebab:...`·`mis:atom:...`·`mis:m:...`)으로 수렴하고, 정본 1개 + alias 매핑. dangling을 Phase 2에 **경고→에러**로 승격(`schema/concept.py` 참조무결성).
- **표기 변형**: 절대 임베딩으로 병합하지 말고 `notation_variant` relation으로만 표현(§전략 B).
- **타입 표식**: 회수 결과에 `cognitive_type`·`role`을 안전필드로 노출해 concept/skill/problemType 혼동(§4) 차단.

## 전략 B — Relation pruning

- **EdgeType 분류**: *순회용 DAG*(PREREQUISITE·COMPOSED_OF) vs *비순회 태그*(ANALOGOUS_TO·CONTRASTS·notation_variant). 태그 관계는 traversal에 넣지 않고 *조회 시 1-hop 참조*로만.
- **강도 프루닝**: `edge_strength` 임계 미만 엣지는 순회 제외. 적용 지점 = `backend_edge.py` 조회 확장 시 `WHERE edge_strength >= :floor`.
- **적재 게이트**: 비선수 관계 적재(`backend_edge.py:23-26`가 현재 skip) 시 EdgeType별 **분리 적재 + 사이클 검출**을 함께 도입.

## 전략 C — Traversal 제한

traversal 조회 *구현 전에* 계약을 박는다(무방비 상태 진입 금지):
- `max_depth`(예: 선수그래프 3), `max_fanout`(노드당 확장 상한), `edge_type` **allowlist**(기본 PREREQUISITE만), **visited set 사이클 가드**.
- 상수·가드 위치: 향후 `l1/concept_graph/traversal.py`(신규) 또는 `l2` 선수추천 좌석. Neo4j 경로면 Cypher `*1..3` depth 캡 + `apoc.path.expandConfig` limit.

## 전략 D — Semantic indexing

- **(본 PR 반영)** `search_concepts`에 `min_similarity`(무임계 실패 차단) + `domain`(collision 스코프) 게이팅 추가. 기본 None → 후방호환.
- 개념/오개념/문항 **인덱스 분리 유지**(이미 그러함) + 교차조회 좌석(§5) 추가.
- (후속·A/B 후) 임베딩 텍스트 domain/level 안전문맥 보강. query-time track 스코프.
- symbolic vs educational 유사도 **분리 회수·비융합**(§8).

---

## 이번 PR에서 실제 반영한 변경

| 변경 | 파일 | 성격 |
|---|---|---|
| `search_concepts(min_similarity=None)` — semantic 실패 임계 게이팅 | `l1/concept_graph/retrieval.py` | 순수 가산·후방호환 |
| `search_concepts(domain=None)` — 도메인 스코프 collision 게이팅 | `l1/concept_graph/retrieval.py` | 순수 가산·후방호환 |
| 필터 단위테스트(임계/도메인/조합·기본 불변) | `tests/backend/l1/test_concept_retrieval.py` | hermetic |

두 필터 모두 **기본 None → 기존 호출·기존 테스트 전량 무영향**. §10-①(무임계 top_k)을 좌석에서 즉시 완화.

## 후속 권고 (조기/대규모 — 별도 슬라이스)

1. **오개념 네임스페이스 단일화**(§5·전략 A) — 데이터 마이그레이션. 최우선 구조 부채.
2. **Traversal 조회 + depth/fanout 가드**(§6·전략 C) — 조회 코드 자체가 미구현이라 *구현과 동시에* 가드 도입.
3. **비선수 EdgeType 적재 + EdgeType별 순회 분리 + 사이클 게이트**(§전략 B) — `backend_edge.py` 확장.
4. **개념↔오개념 교차조회 좌석**(§5) · **임베딩 텍스트 문맥 보강 A/B**(§2).
5. **symbolic/educational 유사도 분리 회수**(§8) · **AST/semantic 역할 분담 + 정규화 단일화**(§9).

---

**버전**: 0.1.0 | **작성일**: 2026-07-01 | **동반 문서**: `math_dsl_risk_register.md`·`math_dsl_principles_review.md`
