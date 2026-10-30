# 와이매스 스킬 그래프 v1 (`skill_graph`) — 데이터 카드

> **요약**: Skill을 `CognitiveType` enum 속성에서 **1급 노드로 승격**하는 정본 스킬 택소노미(리치
> Part 2 Phase 2a·2026-07-03). 스킬은 개념이 *어떻게* 작동하는지(cognitive action)를 mastery
> 독립추정 단위로 표현한다 — 개념(무엇)과 직교하는 축(어떻게). 폐쇄 6종 `BehaviorArea`와 그 아래
> Skill Family로 조직된 **<!-- fact:skill_graph.skills -->27<!-- /fact -->개 스킬**(v1·compact·canonical). 전량 **와이매스 자체작성**(택소노미).
>
> **현황(Phase 2a)**: data-pipeline `data_pipeline.skill_graph`(models·transform·validate·CLI)가
> 자체작성 `skills.jsonl`을 `graph.json`으로 정형화하고, backend `skill_node`(PG 프로젝션·skill_id
> 키·`behavior_area_enum` native)에 멱등 투영한다. **skill mastery + concept→skill 매핑은 Phase 2b**
> (데이터 원천 확보 후·dead code 회피). 개념측 `behavior_skills` 참조 키는 여전히 dangling(정본
> 스킬 실재하나 개념이 아직 미참조).

---

## 1. 출처·프로비넌스

| 항목 | 값 |
|---|---|
| 형태 | 자체작성 `skills.jsonl`(스킬 1행/줄) → `graph.json`(스킬 노드 배열) |
| 저작 | **와이매스 자체작성**(행동영역·스킬 택소노미·검수필요) |
| 규모 | **<!-- fact:skill_graph.skills -->27<!-- /fact --> 스킬** · <!-- fact:skill_graph.behavior_areas -->6<!-- /fact --> 행동영역 · <!-- fact:skill_graph.families -->16<!-- /fact --> Skill Family |
| 산출 | `python -m data_pipeline.skill_graph transform-v1 -o data/corpus/skill_graph_v1` |
| 결정성 | 동일 `skills.jsonl`(sha256) 2회 transform → byte 동일 `graph.json` |

> 라이선스: 전량 자체작성이라 **redaction 대상 아님**(성취기준·교과서 본문 미포함). `standard_codes`
> (선택)는 연결 NCIC *코드*만 담고 본문은 담지 않는다(코드는 사실정보·공공).

---

## 2. 스키마 (`skills.jsonl` 키 → `skill_node` 컬럼)

| 키 | 컬럼 | 비고 |
|---|---|---|
| `skill_id` | **PK** `skill_id` | `skill.<slug>` 의미론 id(교육과정·언어 무관·27 유일) |
| `name_ko` | `name_ko` | 스킬 표시명(NOT NULL) |
| `behavior_area` | `behavior_area` | 6종 폐쇄 **PG native enum** `behavior_area_enum`(인덱스) |
| `family` | `family` | Skill Family 연속체 그룹(인덱스) |
| `mastery_estimable` | `mastery_estimable` | mastery 독립추정 게이트(BOOL·기본 true) |
| `description` | `description` | 짧은 설명(자체작성·선택) |
| `prerequisite_skill_ids` | `prerequisite_skill_ids` | 선수 스킬 참조 키(TEXT[]·DAG·엣지 타입 0) |
| `standard_codes` | `standard_codes` | 연결 NCIC 코드(TEXT[]·선택·본문 미포함) |
| — | `review_status` | 상수 `'ai_estimated'`(v1 자체작성이나 전문 검수 전·정직 표기) |
| — | `updated_at` | 마지막 upsert 시각 |

> **본문·오개념·프롬프트 슬롯 없음**(순수 스킬 택소노미·concept_node·atom_node 동형). 스킬 연결은
> 참조 키만 — 별도 SkillEdge·그래프 없음(**신규 엣지 타입 0**·anti-explosion).

---

## 3. BehaviorArea 6종 (폐쇄·2026-07-03 확정·사용자 결정)

| 값 | 한글 | 뜻 |
|---|---|---|
| `COMPUTE` | 계산실행 | 절차·연산 수행(예: 다항식 나눗셈) |
| `TRANSFORM` | 식변형 | 표현을 등가 형태로 변형(예: 인수분해) |
| `INTERPRET` | 조건해석 | 조건·문제를 수학 구조로 해석 |
| `REPRESENT` | 표상/표현 | 그래프·도형·다중표현 전환 |
| `REASON` | 추론 | 연역·논리적 근거 전개 |
| `VERIFY` | 검증 | 결과 점검·반례·타당성(Polya 반성) |

> English enum value(backend `CognitiveType` 스타일). data-pipeline·backend 두 정의가 값이 정확히
> 일치한다(`test_skill_governance` 동결). 확장은 ADR `concept_node_layering_decision.md` 갱신 전제.

---

## 4. 검증 (그래프 레벨 invariant)

- **skill_id_unique**(error) — 스킬 code 유일.
- **prerequisite_dangling**(error) — 선수 참조가 코퍼스에 존재(자기완결).
- **prerequisite_cycle**(error) — 선수 참조 DAG(순환 불가).
- **behavior_area_coverage**(warning) — 6종 각각 ≥1개(v1 커버리지).

v1 코퍼스: error 0·warning 0(6종 전부 커버). 테스트: `tests/data_pipeline/skill_graph/`(모델·
transform·validate·corpus)·`tests/backend/l1/skill_graph/`(프로젝션 단위·@integration 실 PG).

---

## 5. 계층·경계 (7계층 아키텍처)

- **L1 데이터 기반**: 이 코퍼스·프로젝션(`skill_node`)은 검색 enrichment·필터·(2b) skill mastery
  조인 백킹. 소비(L2 mastery·L4 결선)는 이 좌석을 쓰되 여기서 구현하지 않는다(역방향 의존 금지).
- **anti-explosion**: SkillNode는 canonical·mastery 독립추정 단위만(개념마다 스킬 남발 금지). v1은
  compact(27)·명시적 확장 가능.
- **additive**: 기존 concept_node·atom_node·검색·임베딩과 무충돌(신규 테이블·신규 enum).
