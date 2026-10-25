# 데이터셋: 개념 연결 그래프 (Concept Graph)

> **L1 구조화 레이어.** *왜 이 개념을 배우는가*를 그래프로 답하는 자산. NCIC 성취기준(`docs/data/ncic.md`)을 truth source로 두고, 그 위에 개념·관계를 얹는다.
>
> **상태(2026-08-03 정정): 적재 완료.** 애초 이 카드가 서술한 "미구축·목표 500노드·2,000엣지·
> Phase 1 고1 미적분 ~100개념"은 stale이다 — 실측 `data/corpus/concept_graph_v1/graph.json`
> concepts <!-- fact:concept_graph.concepts -->437<!-- /fact -->건·edges <!-- fact:concept_graph.edges -->581<!-- /fact -->건(2026-06-20 e2e 승격), `data/corpus/atom_graph_v1/graph.json`
> concepts <!-- fact:atom_graph.nodes -->2,683<!-- /fact -->건·edges <!-- fact:atom_graph.edges -->2,278<!-- /fact -->건이 이미 커밋·적재됐다(`knowledge_module_gap_review.md`가
> 원자 백본(당시 2,697건)을 runtime truth source로 정본화). 아래 §2 이하 개별 스펙(9계층 taxonomy·
> ID 규약 등)은 2026-07-02 P2d까지 갱신돼 있어 이 리드 문단만 낡아 있었다
> (`curriculum_module_gap_review.md` §정정 참조).

---

## 1. 메타데이터

| 항목 | 값 |
|---|---|
| 정식 명칭 | WhyMath 개념 연결 그래프 (Concept Graph) |
| PRD 출처 | MathScope PRD v1.1 신규 자산 9번 (`MEMORY.md` 2026-05-14 결정 로그) |
| 자산 성격 | **자체 구축 자산** — 외부 데이터를 *수집*하는 게 아니라 기존 자산을 *연결* |
| 1차 입력 | NCIC 성취기준(공공누리 1유형), 오개념 카탈로그(자체), 다국 커리큘럼 매트릭스(`curriculum_matrix.md`) |
| 라이선스 | **자체 자산** (WhyMath 소유). 1차 입력 NCIC의 공공누리 1유형 출처 표시 의무는 그래프에도 승계 |
| 상업 활용 | 허용 (자체 자산) |
| 저장소 | Neo4j 5.x (배포 토폴로지 DB 블록 — `docs/architecture/00_overview.md` 5블록 참조) |
| 데이터 카드 작성일 | 2026-05-14 |
| 다음 검토일 | Phase 1 종료 시점 (2026-11) |
| 목표 규모 | **500 노드 · 2,000 엣지** (Phase 3 도달 목표) |
| Phase 1 범위 | 고1 미적분 영역 **~100 개념** (첫 진입 = 고1 내신 트랙 정렬) |

### 라이선스 출처 표시 (의무 — 승계분)

개념 노드의 성취기준 참조(`standard_codes`)가 NCIC에서 유래하므로, 그래프를 외부에 노출·라이선싱할 때 NCIC 출처 문구를 동봉한다:

```
개념-성취기준 매핑 근거: 교육부 고시 제2022-33호 [수학과 교육과정],
국가교육과정정보센터(NCIC, https://www.ncic.go.kr)
```

`data_pipeline.concept_graph.models.SOURCE_CITATION` 상수로 강제 (NCIC 모듈과 동일 패턴).

---

## 2. 스키마

> 엔티티 필드 명세의 정본은 `schemas/v1.1/` (PRD v1.1 9개 엔티티 명세). 아래는 데이터 카드용 요약.

### 2.1 `Concept` 노드 (Pydantic — Phase 1 운영 모델)

`src/data-pipeline/data_pipeline/concept_graph/models.py` (미구현 — 시그니처만):

```python
class Concept(BaseModel):
    concept_id: str                  # PK(canonical). 'math.<area>.<slug>' — 매트릭스와 공유. 'math.calculus.epsilon-delta-geukhan-jeongui'
    source_id: str                   # 원천 src_id(파생 추적·롤백). 'H:12미적Ⅰ01-01'
    aliases: list[str]               # 옛 키 — [교육과정축 코드, 옛 UC, src_id]. 하위호환 join·matrix 개념축 오버레이
    # 표시이름(name_ko/en/ja)은 노드 비내장 — locale 계층(locales/{lang}.json·canonical 키)이 단일 진실(P2d·Concept Purity)
    domain: str                      # '미적분' 등 (NCIC 영역명과 정렬)
    grade_band_hint: str | None      # 전형적 도입 학년군 (NCIC grade_band 어휘 재사용)
    prerequisite_concept_ids: list[str]   # 선수개념 — Edge(prerequisite)와 *중복 저장* (조회 편의)
    misconception_codes: list[str]   # 오개념 카탈로그(docs/data/misconceptions) 참조 키
    visualization_card_keys: list[str]    # L5 시각화 자산 키. L1은 *참조만* — 렌더링은 L5
    standard_codes: list[str]        # 매핑된 NCIC 성취기준 코드. truth source 연결
    notes: str | None                # 전문가 검수 메모
```

### 2.2 `Edge` (관계) — 7가지 유형

```python
class ConceptEdge(BaseModel):
    src_concept_id: str
    dst_concept_id: str
    relation: Literal[
        "prerequisite",      # 선수 — src를 알아야 dst를 배움
        "generalization",    # 일반화 — dst는 src의 더 일반적 형태
        "specialization",    # 특수화 — dst는 src의 특수 사례
        "contrast",          # 대조 — src·dst는 헷갈리기 쉬워 구분 학습 필요
        "application",       # 응용 — src를 dst 상황에 적용
        "composition",       # 합성 — dst는 여러 개념(src 포함)의 결합
        "notation_variant",  # 표기 변형 — 같은 개념의 다른 표기
    ]
    strength: float                  # 0.0~1.0. 관계가 얼마나 강한지
    evidence: str                    # 그 판단의 근거 (성취기준 인접·교육학 문헌·다국 교차검증 등)
    evidence_source: Literal["ncic", "curriculum_matrix", "math_education_literature", "expert_review"]
```

### 2.3 Neo4j Cypher DDL (Phase 1 — 운영)

```cypher
// 노드 제약
CREATE CONSTRAINT concept_id_unique IF NOT EXISTS
  FOR (c:Concept) REQUIRE c.concept_id IS UNIQUE;

// 조회 인덱스 (표시이름은 노드 비내장 — name_ko 인덱스 제거·P2d. 표시 조회는 locale 계층 소관)
CREATE INDEX concept_domain IF NOT EXISTS FOR (c:Concept) ON (c.domain);

// 관계는 7개 타입을 Cypher 관계 타입으로 직접 사용:
// (:Concept)-[:PREREQUISITE {strength, evidence, evidence_source}]->(:Concept)
// (:Concept)-[:GENERALIZATION {...}]->(:Concept)  등
```

`relation` enum 7종은 `data_pipeline/concept_graph/models.py`의 `Relation`(→ `RELATION_TYPES`)로 단일 관리. 관계 추가 시 *이 한 곳만* 갱신. (산문 "6종"은 stale — `notation_variant` 포함 7종이 정본. enum 값이 산문 카운트에 우선.)

### 2.2b 관계 어휘 crosswalk — pipeline `Relation` ↔ backend `EdgeType`

관계 어휘가 계층별로 나뉘어 있다(이름·개수 상이). **단일 진실 원천은 아래 표**이며,
`data_pipeline/concept_graph/relation_crosswalk.py`가 코드로, 양쪽 거버넌스 테스트가 동결한다.

- **L1 pipeline `Relation`**(models.py·7종·소문자) = **canonical 데이터 어휘**.
- **L2 backend `EdgeType`**(`whymath_backend/schema/enums.py`·6종·대문자) = **런타임 투영 어휘**.
- **atom `AtomRelation`**(atom_graph·1종 `prerequisite`) = 원자 백본.

| pipeline `Relation` | backend `EdgeType` 투영 | 적재 | 비고 |
|---|---|---|---|
| `prerequisite` | `PREREQUISITE` | ✅ 적재 | traversal 대상(유일). DAG 강제·`prerequisite_concept_ids` 캐시 동기 |
| `generalization` | `EXTENDS` | ⏸ deferred | A→일반화 |
| `specialization` | `EXTENDS` | ⏸ deferred | EXTENDS의 역방향 해석 |
| `contrast` | `CONTRASTS` | ⏸ deferred | 대조 학습 |
| `composition` | `COMPOSED_OF` | ⏸ deferred | 합성 |
| `application` | *(deferred)* | ⏸ deferred | backend 런타임 대응 없음 |
| `notation_variant` | *(deferred)* | ⏸ deferred | backend 런타임 대응 없음 |

backend 전용 타입 `ANALOGOUS_TO`(유사)·`TRIGGERS_DISTRACTOR`(오개념 유발 선지)는 pipeline 원천이
없다 — 각각 traversal 배제(약한 관계·N² dense화 방어)·오개념 op-code 카탈로그 어휘다.
**현 범위는 `prerequisite`만 backend `concept_edge`에 적재**한다(약한 관계 유입 차단 —
`tests/backend/l1/test_edge_relation_governance.py`). `similar_to`/`related_to`는 어느 어휘에도
없다(관계 타입 폭발 방어 — 8대 원칙 ③).

### 2.2c AI Graph vs Runtime Graph 분리 (Concept Purity)

플레이북 Part 3 "AI용 Graph ↔ Runtime Graph 분리"는 이 프로젝트에서 **Concept Purity + 3중 store**로
구현된다(같은 원칙, 다른 명칭). 대응:

| 플레이북 라벨 | 구성 | 저장 위치 |
|---|---|---|
| **AI Graph** | 개념 + 최소 relation(prerequisite) + 오개념 subset(reactive) + AST | Neo4j(구조) + PG `concept_node`(안전 메타) |
| **Runtime Graph** | renderer·animation·layout·UI state | `data/render_contract.json`(렌더 계열 맵) + L5 클라이언트(Flutter·웹)·Learning Scene DSL |
| (별도 축) | embedding 벡터 | pgvector `concept_embedding`(노드에 미저장 — 참조만) |

노드(`Concept`)는 **순수 개념만** 보유한다 — renderer·animation·layout·UI·embedding·prompt를
필드로 갖지 않는다(모델 필드 화이트리스트 동결: `test_models.py::TestConceptPurity`). 시각화·오개념은
*참조 키*(`visualization_card_keys`·`misconception_codes`)만 두고 실체는 노드 밖에 산다.

### 2.4 ID 규약 — concept_id (`math.<area>.<slug>`)

> **2026-07-02 전환(P2d·Part 9 엄격 시정)**: 정본 ID를 `{TRACK}-{AREA}-{NNN}`(P2a·학년대=교육과정 결합·비의미론 순번)에서 아래 **교육과정·언어·렌더러 무관 의미론** 형식으로 *전환*했다(breaking). 옛 `{TRACK}-{AREA}-{NNN}`(교육과정축 오버레이 코드)·옛 UC·원천 `src_id`는 `aliases`에, `src_id`는 `source_id`에 보존한다(롤백·하위호환·matrix 개념축 join). 결정 로그: `MEMORY.md` 2026-07-02 P2d. (P2a `{TRACK}-{AREA}-{NNN}`은 플레이북 Part 9가 경고하는 `KR2022.math2.limit` 안티패턴이라 폐기 — `docs/standards/part9_id_policy_review.md`.)

```
math.<area>.<slug>      예: math.geometry.hapdong-daeching-idong
```

- **`math`** = 고정 subject 도메인(Phase 1 전건 수학·향후 확장 시 추가).
- **`<area>`** = 교육과정-독립 영역어(소문자·`[a-z]`+하이픈) — `category`(레벨 접두사 `[고]`/`[중]`/`[공통]` 제거 후 토픽)를 AREA 코드로 매핑(`idmap._TOPIC_AREA_MAP`·전수)한 뒤 영역어로 사상(`idmap._AREA_SLUG_MAP`·GEO→geometry·CALC→calculus·ALG→algebra 등). area는 이미 학년-독립이라(`[중]기하`·`[고]기하`→`geometry`) **학년/교육과정 결합이 ID에서 사라진다**(Part 9 핵심). 미수록 category는 *침묵 폴백 없이 KeyError*(taxonomy 누수 가드).
- **`<slug>`** = `name_ko`의 결정론적 로마자화(`hangul_romanize.romanize`·국립국어원 표기법 기반 간이 음역·외부 lib 0). `name_en` 저작 후에도 canonical은 불변(locale만 개선·동결 정책).
- **충돌**: grade 제거로 `(area, slug)`가 겹치면(기본수학↔공통수학 22쌍) `(int(difficulty_tier), src_id)` 정렬로 첫 항목 무접미·이후 `-2`/`-3`(멱등). 접미 사실은 `ids.yaml`에 기록.
- 예: `math.place-value.su-gaenyeomgwa-segi`(수 개념과 세기)·`math.equation.dahangsigui-sachik-yeonsan`(다항식의 사칙연산).
- **matrix "개념 축" join**: 정본 키는 canonical이고, 옛 `{TRACK}-{AREA}-{NNN}`은 `aliases`의 교육과정축 오버레이 코드로 보존돼 alias 조회로 계속 join 가능(`curriculum_matrix.md`·curriculum overlay 원칙·'WM-C-…' 표기는 stale).

---

## 3. 알려진 제약

### 3.1 자체 구축 = 수집 자동화 불가

- 이 자산은 크롤링 대상이 아니다. *노드·엣지 작성 자체가 사람(수학교육 전문가) 작업*이다.
- 자동화 가능한 부분은 (a) NCIC 성취기준에서 후보 노드 *시드* 생성, (b) 성취기준 학년·영역 인접성에서 `prerequisite` 후보 엣지 *제안*뿐. **확정은 전문가 검수.**
- 따라서 "9단계 워크플로우"가 NCIC와 다르게 적용된다 (4절 참조).

### 3.2 관계 판정의 주관성

- `generalization` vs `specialization`은 방향만 반대 — 작성자 혼동 위험. 검증 단계에서 *역방향 쌍 존재 시 경고*.
- `contrast`·`application`은 교육학적 판단 — 동일 개념쌍에 작성자마다 다른 엣지를 달 수 있음. `evidence` 필드 필수화로 *근거 없는 엣지 차단*.
- PRD v1.1 허점 ⑤("개념 시퀀스 동치성 판정 난이도 과소평가", `MEMORY.md`)와 같은 계열의 리스크 — **휴리스틱 제안 + 사람 검수**가 유일한 방어선.

### 3.3 오개념·시각화 참조의 dangling key

- `misconception_codes`·`visualization_card_keys`는 *아직 존재하지 않는* 자산을 가리킬 수 있음 (오개념 카탈로그는 Phase 1에 30개만, L5 시각화는 별도 일정).
- 대응: 검증 단계는 dangling 참조를 *에러가 아닌 경고*로 처리 (보수적 — 그래프 구축이 다른 자산 일정에 막히면 안 됨). Phase 2에 참조 무결성 검사로 승격.

### 3.4 계층 경계 — L1은 그래프를 *보유*만

- 그래프를 *순회*해 학습 경로를 만드는 로직은 L1이 아니다 (L4 교수학 엔진 / L6 응용 모드 소관).
- L1은 `Concept`·`Edge` 데이터와 단순 조회 API(`get_concept`, `get_edges`)까지만 책임. `00_overview.md` 컴포넌트 매트릭스 경계 준수.

### 3.5 concept_id 안정성

- 한 번 발급한 `concept_id`는 *변경 금지* (매트릭스·교과서 매핑이 이 키로 join). 개념을 합치거나 쪼갤 때는 ID 폐기·신규 발급 + `notes`에 이력 기록. canonical의 `<slug>`는 발급 시 동결 — `name_en` 저작 등으로 표시이름이 바뀌어도 canonical은 불변(locale만 개선). slug 교체는 명시적 rename 마이그레이션 이벤트로만(침묵 변경 금지·`ids.yaml` migrations 기록).
- **예외 — 2회 전환(추적성 무손실)**: ⑴ **P2a(2026-06-16)** `UC.*` → `{TRACK}-{AREA}-{NNN}`, ⑵ **P2d(2026-07-02·Part 9)** `{TRACK}-{AREA}-{NNN}` → `math.<area>.<slug>`(교육과정 결합 제거). 두 전환 모두 "변경금지"를 일괄로 깬 단발 마이그레이션이며, 추적성은 깨지 않았다 — 모든 노드가 옛 `{TRACK}-{AREA}-{NNN}`(교육과정축 코드)·옛 UC·원천 `src_id`를 **`aliases`**로, `src_id`를 **`source_id`**로 보존하고 `ids.yaml`이 P2a·P2d 이관 이력을 기록한다(옛 키로도 join·롤백). 코퍼스가 `src_id` 기반이고 모든 ID가 *파생*이라(idmap), 재발급이 안전했다. 전환 *이후*엔 다시 발급 후 불변 원칙이 적용된다.
- 검증: `data_pipeline.concept_graph.validate`의 `id_conformance`·`curriculum_independence`·`id_unique`·`alias_roundtrip`(그래프 레벨)·`validate_registry`(ids.yaml)·`validate_locales`(locales)와 `validate_idmap`의 `area_map_total`(원천 레코드 레벨)이 재ID·registry·locale 불변식을 강제한다.

---

## 4. 가공 단계 (data-engineer 워크플로우 — 자체 구축 변형)

> NCIC의 "수집→정제" 단계가 여기서는 "시드 생성→전문가 작성"으로 바뀐다.

| 단계 | 모듈 / 주체 | 책임 |
|---|---|---|
| 1. 라이선스 확인 | `docs/data/licensing_safety.md` | 자체 자산 + NCIC 승계 출처 의무 확인 |
| 2. 데이터 카드 | 이 문서 | 본 .md |
| 3. 시드 생성 | `seed.py` | NCIC 성취기준 → 후보 `Concept` 노드 + `prerequisite` 후보 엣지 자동 제안 |
| 4. 전문가 작성 | 수동 (수학교육 도메인 파트너 — `MEMORY.md` M1.3 게이트) | name_ko(→locale)·7종 관계·strength·evidence 작성 (name_en/ja는 후속 locale 저작) |
| 5. 정형화 | `transform.py` | 작성 시트 → `Concept` / `ConceptEdge` Pydantic |
| 6. 검증 | `validate.py` | ID 규약·enum·역방향 쌍 경고·dangling 참조 경고·고립 노드 탐지 |
| 7. 저장 | `load.py` | Neo4j 적재 (Cypher MERGE — 멱등) + JSON 백업 |
| 8. 데이터 상관 검수 | 수동 | 전문가 검수 + NCIC 인접성과의 상관 점검 (5절) |
| 9. MEMORY.md | 수동 | 결과 기록 + 매트릭스·교과서 매핑 join 가능 여부 확인 |

---

## 5. 검증 결과 (목표 invariants — 미구현)

> `tests/data_pipeline/concept_graph/` 스위트가 보장할 invariant. **아직 테스트 없음.**

| Invariant | 테스트 (예정) |
|---|---|
| `concept_id`가 `math.<area>.<slug>` 규약 준수·유일·교육과정 무관 | `test_idmap.py`(regex·충돌0)·`test_id_registry_governance.py`·`validate`의 `id_conformance`·`curriculum_independence`·`id_unique` |
| 모든 `category`가 AREA로 매핑(미매핑 0)·`src_id`→새 ID 가역·옛 UC 별칭 보존 | `validate_idmap`의 `area_map_total`·`alias_roundtrip` + `test_idmap.py::TestBuildAliasMap` |
| `relation`이 7종 enum 밖이면 ValidationError | `test_edge_rejects_unknown_relation` |
| `strength`가 0.0~1.0 범위 밖이면 거부 | `test_edge_strength_bounds` |
| `evidence`가 빈 문자열이면 거부 (근거 없는 엣지 차단) | `test_edge_requires_evidence` |
| `generalization`↔`specialization` 역방향 쌍 존재 시 경고 | `test_validate_warns_inverse_pair` |
| `prerequisite` 사이클 탐지 (선수개념이 순환하면 학습 경로 불능) | `test_validate_detects_prerequisite_cycle` |
| 고립 노드(엣지 0개) 탐지 → 경고 | `test_validate_warns_isolated_node` |
| dangling `misconception_codes` → 경고(에러 아님) | `test_validate_warns_dangling_misconception` |
| Neo4j 적재가 멱등 (MERGE 2회 = 1회) | **구현됨**(슬2): 단위 `test_load.py::TestIdempotency`(FAKE 드라이버·발행 Cypher 동일)·통합 `test_load_neo4j_integration.py::test_load_is_idempotent_on_live_neo4j`(실 Neo4j·2회 적재 → 노드 403·엣지 541 불변·기본 SKIP·CI/Phaiakes9) |
| 데이터 상관: `prerequisite` 엣지의 src·dst 성취기준 학년이 역전되지 않음 | `test_prerequisite_grade_monotonic` |

### 데이터 상관 검수 (전문가 + 자동 — 단계 8)

NCIC 성취기준과의 *상관*을 점검한다 (PRD "데이터 상관" 검증 방식):

- [ ] `prerequisite` 엣지로 연결된 두 개념의 NCIC 성취기준 학년이 단조 증가하는가 (선수개념이 후행 학년에 오지 않는가)
- [ ] 한 성취기준에 매핑된 개념들이 그래프상 *근접*해 있는가 (같은 성취기준인데 그래프상 멀면 매핑 오류 의심)
- [ ] 전문가 검수: 7종 관계 분류가 수학교육학적으로 타당한가, `evidence`가 실제 근거인가

---

## 6. 구축 절차 (Kiki + 도메인 파트너용 — Phase 1)

> **선행 조건**: NCIC 성취기준 디지털화 완료(`data/ncic/standards.json`). 그래프는 그 산출물을 시드로 쓴다.
> **도메인 파트너 의존**: 단계 4(전문가 작성)는 `MEMORY.md` M1.3 게이트의 수학교육 도메인 파트너 영입 이후 본격화. 그 전까지는 단계 3(시드 생성)까지만 준비.

### 6.1 환경 구성 (1회)

```bash
cd src/data-pipeline
source .venv/bin/activate          # NCIC와 동일 가상환경
pip install -e ".[dev]"            # neo4j 드라이버 포함 (pyproject 갱신 예정)
```

Neo4j는 배포 토폴로지의 DB 블록 — 로컬 개발은 Docker로:
```bash
docker run -d --name whymath-neo4j -p 7687:7687 -p 7474:7474 \
  -e NEO4J_AUTH=neo4j/<로컬비밀번호> neo4j:5
```

### 6.2 단계 3 — 시드 생성 (자동)

```bash
# 프로젝트 루트에서. NCIC 산출물 → 고1 미적분 후보 노드/엣지
python -m data_pipeline.concept_graph seed \
  --ncic data/ncic/standards.json \
  --domain-filter "미적분" \
  --output-dir data/concept_graph/seed/
```

출력:
- `data/concept_graph/seed/concepts.csv` — 후보 노드 (전문가가 표기·참조 채울 빈칸 포함)
- `data/concept_graph/seed/edges.csv` — `prerequisite` 후보 엣지 (strength·evidence 빈칸)

### 6.3 단계 4~7 — 전문가 작성 후 적재

전문가가 `concepts.csv`·`edges.csv`를 채운 뒤:
```bash
python -m data_pipeline.concept_graph load \
  --concepts data/concept_graph/seed/concepts.csv \
  --edges data/concept_graph/seed/edges.csv \
  --neo4j-uri bolt://localhost:7687 \
  --output-dir data/concept_graph/
```

출력: Neo4j 적재 + `data/concept_graph/graph.json` (백업·검증용)

### 사람 검수 (필수 — 단계 8)

```python
import json, random
g = json.loads(open("data/concept_graph/graph.json", encoding="utf-8").read())
sample = random.sample(g["edges"], k=max(5, len(g["edges"]) // 20))   # 5% or 최소 5개
for e in sample:
    print(e["src_concept_id"], f"--{e['relation']}({e['strength']})-->",
          e["dst_concept_id"], "|", e["evidence"][:60])
```

체크리스트:
- [ ] 7종 관계 분류가 수학교육학적으로 타당
- [ ] `strength`가 관계 강도를 합리적으로 반영
- [ ] `evidence`가 실제 근거 (NCIC 인접·문헌·다국 교차검증 중 하나)
- [ ] `prerequisite` 사이클 없음
- [ ] `concept_id`가 매트릭스(`curriculum_matrix.md`)와 join 가능한 형태

---

## 7. Phase 2+ 후속 작업 (이번 작업 범위 외)

- [ ] 고1 미적분 → 고1 전 영역 → 중·고 전체로 노드 확장 (목표 500노드)
- [ ] dangling 참조 검사를 *경고 → 에러*로 승격 (오개념 카탈로그 100개·L5 시각화 자산 안정화 후)
- [ ] `curriculum_matrix.md`와의 `concept_id` join 무결성 자동 검사
- [ ] 다국 교차검증 엣지 본격 추가 (`evidence_source = curriculum_matrix`) — 매트릭스 Phase 3 풀스케일 연동
- [ ] L4 교수학 엔진이 그래프를 순회해 학습 경로 생성 (L4 작업 — L1은 조회 API만 제공)
