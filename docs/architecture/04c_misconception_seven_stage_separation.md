# 04c. 오개념 7레벨 분리 — Part 6 검토 + 정본 명세

> **상태**: 정본 (2026-07-02, 재검토 교정) · **계층**: L4 교수학 엔진 (횡단: L1 저장·L2 그래프·L3 임베딩·L5 렌더)
> **관련**: `04_pedagogy_engine.md` · `04b_misconception_judge_graduation.md` · `04e_misconception_remediation_design.md`(§6 갭 장부의 후속 실행 설계) · `misconception_module_gap_review.md`(외부 EOS 틀 대조) · `math_dsl_principles_review.md`(§3.4·§3.6) · `math_dsl_risk_register.md`(Q1·Q8) · `docs/standards/playbook_part_review_questions.md`(Part 6) · `CLAUDE.md`(§오개념 독립 DB·§8대 구조원칙 #6)

---

## 0. 이 문서가 존재하는 이유 (+ 재검토 교정 이력)

구축 플레이북 **Part 6**는 오개념 시스템의 세 불변을 요구한다: ① 오개념이 concept node에
**preload되지 않음** ② **7레벨 분리** ③ **reactive retrieval만** + concept/misconception 인덱스
분리.

**정본 7레벨(플레이북 Part 6 §6-2 표)**은 다음이다:

> **Storage · Relation · Embedding · Retrieval · Runtime Context · Repair Strategy · Renderer**

> **⚠️ 교정 이력(2026-07-02 재검토)**: 이 문서 초판은 정본 표를 확보하기 전, 7레벨을
> `Storage/Retrieval/Embedding/Context/Runtime gate/**Judge**/**Identity**`로 *자체 파생*했다.
> 이는 (a) **Relation 레벨을 누락**하고 (b) 정본에 없는 Judge/Identity를 6·7로 넣은 **오류**였다.
> 본 개정은 §2를 **정본 7레벨로 교정**하고, Judge/Validation·Identity/Canonical은 실재하는
> *추가 방어*(정본 7레벨 밖)로 §5에 강등한다.

코드상 정본 레벨은 **대부분 이미 구현**돼 있다 — 초판의 잘못은 방어의 부재가 아니라 *라벨링*이었다.
`tests/backend/l4/test_misconception_seven_stage_manifest.py`가 이 정본 매핑을 코드에서 동결한다.

---

## 1. 6-1 오염 메커니즘 (왜 분리가 협상 불가인가)

오개념을 concept node 안에 넣으면 초기엔 편하지만 거의 반드시:

```
AI reasoning 오염 → retrieval precision 붕괴 → relation explosion → tutoring drift → context explosion
```

**핵심 원칙: "Misconception은 개념이 아니다. 개념에 대한 실패 패턴이다."** LLM은 정답과 오답을
완벽히 분리하지 못하므로, 오개념이 노드에 있으면 misconception도 attention을 소비하고 semantic
embedding이 오염되어 AI가 *오개념 문장을 정상 개념의 일부처럼* 사용하기 시작한다(환각·모순·drift).

---

## 2. 정본 7레벨 분리 — 실측 매핑

각 레벨 → 구현 앵커 → 동결 테스트. 실측(2026-07-02 3-에이전트 탐사)으로 상태를 표기한다.

| # | 정본 레벨 | 상태 | 개념 ↔ 오개념 분리 지점 | 구현 앵커 | 동결 테스트 |
|---|---|---|---|---|---|
| 1 | **Storage** | ✅ | 오개념 4테이블 개념과 별도·FK로 개념에 결합 안 됨(loose ref)·노드에 자유텍스트 비내장(런타임 `common_misconceptions` 컬럼도 Phase 1b로 제거) | `db/models/misconception_{catalog,hypothesis,crosslink,embedding}.py` | `test_concept_node_purity.py` · `test_concept.py`(`_FORBIDDEN_NODE_FIELDS`) |
| 2 | **Relation** | ✅ traversal 진입 차단 / ⚠️ 관계셋 미구현 | 오개념이 개념 traversal에 진입 불가(키공간·FK·edge_type 삼중 차단)·약한 토큰 금지 | `schema/enums.py`(EdgeType) · `l1/concept_graph/backend_edge.py:145` · `data_pipeline/concept_graph/relation_crosswalk.py:62-68` · `l2/prerequisite_recommendation.py`(PREREQUISITE-only CTE) | `test_edge_relation_governance.py` |
| 3 | **Embedding** | ✅ | 3 임베딩 테이블 물리 분리 + cross-table 코사인 금지 | `l4/misconception/semantic/pgvector_index.py` · `l1/concept_graph/embedding.py` · `l1/atom_graph/embedding.py` | `test_embedding_namespace_governance.py` · `test_misconception_namespace_gate.py` |
| 4 | **Retrieval** | ✅ reactive + classifier-first | reactive `diagnose()`(요청 시)·규칙 분류기 우선·vector는 보조 recall | `l4/misconception/diagnose.py` · `combined.py` · `match_gate.py` | `test_misconception_diagnose.py` |
| 5 | **Runtime Context** | ✅ | 초기 context에 오개념 미탑재·2-stage·노출 게이트 off 기본 | `api/coach.py` · `api/_misconception_state.py` · `config.py`(gate 기본값) | `test_misconception_state.py` |
| 6 | **Repair Strategy** | ✅ 분리 / ⚠️ 잔여 | Misconception(카탈로그) ≠ Repair(intervene) ≠ Visualization — 별도 모듈·느슨결합 | `l4/misconception/intervene.py` · `distractor.py` | manifest(좌석 실재 동결) |
| 7 | **Renderer** | ✅ | 오개념에 animation 직결 없음 — Visualization Intent → L3 선언적 spec → L5 렌더러 | `l4/misconception/visualize.py` · `schema/visualization.py` | manifest(좌석 실재 동결) |

### 레벨별 주석

- **1 Storage** — 오개념 콘텐츠(`misconception_catalog`, PK=`mis_id`)·학생별 활성 가설
  (`misconception_hypothesis`)·crosswalk(`misconception_crosslink`)·임베딩(`misconception_embedding`)이
  전부 개념 테이블과 별개다. crosslink는 `mis_id`만 실 FK, kebab-id·`concept_src_id`는 느슨참조.
- **2 Relation** — 오개념은 개념 그래프 traversal에 **진입할 수 없다**: `concept_edge`는 concept↔
  concept UUID FK 전용이라 오개념이 노드/엣지로 낄 스키마 여지가 없고, 선수 순회 CTE
  (`prerequisite_recommendation.py`)는 `edge_type==PREREQUISITE`만 필터하며, 적재기
  (`backend_edge.py:145`)는 비-선수 관계를 전부 skip한다. 약한 총칭 관계는 상수로 금지 —
  `FORBIDDEN_RELATION_TOKENS={similar_to, related_to}`·`TRAVERSAL_EXCLUDED_BACKEND_EDGE_TYPES=
  {ANALOGOUS_TO, TRIGGERS_DISTRACTOR}`(`relation_crosswalk.py:62-68`). **⚠️ 갭**: 정본이 기대한
  오개념 전용 소수 관계셋(`misconception_of/caused_by/repaired_by/variant_of`)은 아직 없다 — 오개념은
  개념 참조만 가진 *평면 카탈로그*이고 노드화는 후속 보류(§6 참조).
- **3 Embedding** — 같은 pgvector store 안에서도 kind가 *테이블*로 분리되고, 서로 다른 kind 테이블
  간 SQL 코사인 join이 allowlist(3모듈)로 금지된다. "방향맹 매처"(둘레↔넓이 코사인 동일)가 실측된
  리스크(`04b` §2)라 이 분리는 측정으로 정당화된다.
- **4 Retrieval** — 진단은 학생 입력이 들어올 때 규칙 분류기(`diagnose()` substring+regex)로 *당겨
  온다*. 개념 조회(`l1/concept_graph/retrieval.py`)는 오개념을 함께 싣지 않는다(§4 classifier-first).
- **5 Runtime Context** — 오개념은 LLM 초기 프롬프트에 preload되지 않는다. 개념으로 1차 추론하고,
  오개념은 *탐지된 뒤*에만 reactive로 결선(2-stage). `misconception_semantic_mode` 기본 `off`·
  `misconception_judge_enabled` 기본 `False`로 보수적 노출(거짓 낙인 RS2 차단).
- **6 Repair Strategy** — 교정 전략은 오개념 카탈로그에 내장되지 않고 `intervene.py`의 결정 트리
  (confidence>0.8 반례·≥0.5 거꾸로·<0.5 보류)가 결정한다. 오개념은 *재료*(canonical_statement·
  counterexample)만 제공. `distractor.py`도 op-code→오개념 매핑(참조)일 뿐 교정 로직이 아니다.
- **7 Renderer** — 오개념은 렌더하지 않는다. `visualize.py`가 *무엇을·언제* 시각화할지(Visualization
  Intent)만 정하고 생성·검증은 L3 `generate_visualization_spec`에 위임한다. 산출물 `Visualization`은
  선언적 JSON 명세이고 렌더러(L5: three.js/Desmos/Plotly)는 명세를 받아 렌더만 한다(구현체 비내장).

---

## 3. Part 6 감사 결과 (항목 ①③ 근거)

### 항목 ① 오개념 concept node preload 금지 — ✅ 다중 방어
- data-pipeline 노드에서 자유텍스트 `misconception_text` **제거**(commit `500b0cc`) + 순수성 동결
  `tests/data_pipeline/concept_graph/test_concept_node_purity.py`.
- backend 적재기가 오개념 컬럼을 아예 쓰지 않음 — Phase 1b로 레코드·ORM에서 제거
  (`l1/concept_graph/backend_concept.py`).
- 검색 서빙 프로젝션 `concept_node`에 오개념 필드 없음. 프로브가 노드 자유서술을 근거로 안 씀
  (`l4/scene_generation.py`) — 활성 가설 ∩ 카탈로그만.
- **청산(cleared·2026-07-03 Phase 1b)**: backend `Concept` ORM/schema가 보유하던
  `common_misconceptions: JSONB` 컬럼(+ 본문 3종)을 **제거**했다(`db/models/concept.py`·
  `schema/concept.py`·Alembic `f0a1b2c3d4e5`). 런타임 소비처 0·전량 `[]`이라 breaking 아님. 재유입은
  `test_concept.py::_FORBIDDEN_NODE_FIELDS`·schema↔ORM 정합 테스트가 차단(정적 소스스캔 가드는 불요).

### 항목 ③ reactive retrieval만 + 인덱스 분리 — ✅ (레벨 3·4·5 참조)
게이트 off면 substring `diagnose()`만·의미 매처 미호출·임베딩 로드 0(`config.py`·`api/coach.py`).
3 임베딩 물리 분리 + cross-table 코사인 금지(`test_embedding_namespace_governance.py`).

---

## 4. 6-3 Reactive + Classifier-first (정본 원칙 준수)

정본 6-3은 "오개념 retrieval은 vector similarity보다 **classifier(분류기) 우선**"을 요구한다.
코드가 이를 아키텍처로 못 박았다:

- **규칙 분류기 우선**: `diagnose.py`의 `signals`(AND substring 공출현)+`regex_signals`(거짓 항등식
  수치 대입 탐지, 예 `(3+4)²=3²+4²`)가 1차. 의미(vector) 매처는 **보조 recall만**(방향맹 한계 자인).
- **재정렬 금지 불변식**: `combined.py`의 `combine_diagnoses`가 substring 블록을 위·semantic-only를
  아래로 병합하고 **두 confidence 축을 섞어 재정렬하지 않는다** — `matches[0]`은 substring이 하나라도
  있으면 반드시 substring(개입은 항상 규칙 진단 기준으로 구동).
- **floor 게이트 축 분리**: `match_gate.py`가 top-1 `confidence`(진단 신뢰) < 0.65면 후보 전체를
  비운다 — floor 판정에 `semantic_similarity`(표면 근접도)는 배제한다(vector가 rule을 추월 불가).

---

## 5. 정본 7레벨 외 — 추가 WhyMath 방어 (7레벨 아님)

아래 둘은 실재하는 오개념 방어이나 **정본 7레벨에는 포함되지 않는다**(초판이 6·7로 오등록했던 것을
여기로 강등):

- **Judge / Validation** — `l4/misconception/judge.py`·`judge_seam.py`. LLM-judge가 방향(⇒역)·부정
  (≠)·등치(=)가 어긋난 후보만 *걸러* 오도된 가르침을 줄인다(제거만·생성 안 함·shadow→canary→full).
  ~~현재 coach 미배선(측정 하니스만·`04b`)~~ → **정정(2026-08-11 실측)**: `api/coach.py:780`에
  `judge_filter`가 결선돼 있다 — 게이트(`misconception_judge_enabled`)가 기본 off라 발동하지
  않을 뿐 배선은 완료다. 동결: `test_misconception_judge.py`.
- **Identity / Canonical** — 런타임 탐지 정본(kebab-id **64종**·`CATALOG_BY_ID`)과 콘텐츠 카탈로그
  (M-id **<!-- fact:misconceptions.count -->843<!-- /fact -->건**)를 의도적으로 FK 미결합·crosswalk로 연결. 개념과 별 키공간이라 정체성 오염 없음.
  동결: `test_misconception_crosslink.py`.
  *(정정 2026-08-11 — 종전 표기 "30종·839종"은 stale이었다. 탐지 카탈로그는 34→40→46→52→58→64로
  5회 트랜치 확장됐고 M-id는 Phase 4a에서 841→843이 됐다. 1차 대조
  `misconception_module_gap_review.md` §0-②가 지적했으나 미정정으로 남아 있던 것을
  `misconception_module_gap_review_r2.md` §5-1이 재등재해 여기서 반영한다.)*

---

## 6. 갭 장부 (미구현·후속 — 정직 회계)

정본 프레임워크 대비 *아직 없는* 방어를 정직하게 기록한다(조용한 누락 금지·CLAUDE.md 신뢰 원칙).

- **[Level 2] 오개념 전용 관계셋 + 노드화** — 정본이 기대한 `misconception_of/caused_by/repaired_by/
  variant_of` 소수 관계와 오개념 간 관계 그래프가 없다. 오개념은 개념 참조(`concept_src_id`)·kebab↔
  M-id crosswalk만 가진 평면 카탈로그다. traversal 진입 차단은 이미 강제되므로 오염 위험은 없고, 이
  관계셋은 오개념 노드화 착수 시 도입한다(현 보류가 정당 — `enums.py:562`·`distractor.py`·
  `relation_crosswalk.py` 후속 노트).
  **후속 설계(2026-08-03)**: `04e_misconception_remediation_design.md` §2가 이 갭을 실행 설계로
  좁혔다 — 4종 중 `misconception_of`는 `edge_design_part3_review.md`가 이미 엣지화를 기각하고
  참조 키로 확정한 축이라 재론하지 않고, `repaired_by`는 본 문서 Level6("Repair Strategy — ✅
  분리")와 중복이라 제외했다. 실제로 여는 것은 `caused_by`·`variant_of` 2종뿐이며, `concept_edge`와
  물리 격리된 신규 테이블 `misconception_relation`(M-id↔M-id FK만)로 설계했다 — 이 문서의 traversal
  진입 차단 불변식은 그대로 유지된다. 백로그: `MISC-04-misconception-relation-isolated-schema`.
- **[Level 6] 잔여** — M-id 콘텐츠 카탈로그가 `distractor_rule`·`correction_point`를 레코드에 병저장
  (런타임 엔진과 별개 체계·FK 무결·오염 아님·순수성 관점 잔여). `InterventionPattern.VISUALIZATION`
  (패턴3) 게이트는 미결선(신뢰도 게이트 재사용으로 우회·후속).
- **[6-4] root vs symptom · slip 판별 — 최대 미구현 갭**: `error_type`(8종: 부호오류·분배누락·
  순서오류·해석오류 등)은 전부 *증상축*이고, root vs symptom·conceptual/procedural/symbolic/visual/
  linguistic 분류·diagnostic signature 필드·transfer/persistence 축은 **전무**. **단순 실수(slip)와
  진짜 오개념을 구분하는 로직도 없다** — 모든 오답을 후보화한다.
  - **CLAUDE.md 정책과의 화해**: CLAUDE.md "모든 오답은 *오개념 후보* 분석 시도"는 *후보화*를
    요구하고, 정본 6-4 "단순 실수를 오개념으로 처리 말라"는 *지속 가설 승격*을 제한한다 — 둘은
    양립한다. 현 설계는 candidate 분석(정책 준수) 후 **confidence floor 0.65 + judge 방향판별 +
    가설 감쇠(decay·반감기 5턴)**로 slip을 자연 배제한다(지속 증거 없으면 가설이 소멸).
  - **후속 트리거**: root/symptom·slip 축을 명시 도입할지는 라이브 오진단(slip을 오개념으로 오코칭)이
    실측될 때 결정(별도 설계 슬라이스). 현 미구현은 정당하되 *측정 대상*으로 기록.
  - **후속 설계(2026-08-03)**: `04e_misconception_remediation_design.md` §3 — 새 분류축은 만들지
    않고, 기존 신호(가설 감쇠·강화·judge 방향판별)만으로 slip-like/지속오개념-like를 구분하는
    읽기전용 관측 리포트만 설계했다(위 후속 트리거를 발화 가능하게 만드는 것이 목적).
    백로그: `MISC-05-root-symptom-slip-observation-report`.

---

## 7. 동결 (manifest 테스트)

`tests/backend/l4/test_misconception_seven_stage_manifest.py`가 본 명세를 코드에서 동결한다.
기존 governance 테스트(namespace·purity·runtime·edge-relation)와 **단언을 중복하지 않고**, 정본
7레벨 앵커가 *전부 실재*함을 hermetic하게 확인한다:

- 정본 7레벨(Storage·Relation·Embedding·Retrieval·Runtime Context·Repair·Renderer) 각 앵커 모듈이
  import 가능(존재).
- 오개념 4 ORM 테이블명이 개념 테이블과 disjoint·개념에 FK 비결합(Level 1·2 loose ref).
- 약한 관계 금지 상수(`FORBIDDEN_RELATION_TOKENS ⊇ {similar_to, related_to}`) 실재(Level 2).
- 런타임 게이트 기본값이 reactive(`semantic_mode="off"`·`judge_enabled=False`)로 동결(Level 5).
- 항목 ①③·preload 동결을 담당하는 기존 테스트 파일 실재(연결 무결성).

명세를 바꾸면(레벨 추가·앵커 이동) 이 테스트가 red가 되어 문서와 코드가 함께 움직이도록 강제한다.
