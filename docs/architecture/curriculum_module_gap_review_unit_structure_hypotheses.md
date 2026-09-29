# 교육과정 모듈 — EOS 『2_단원 구조 관리』 수용 후속: 가설 3종 관측·명세 (CUR-09)

> **성격**: `curriculum_module_gap_review_r2.md` §후속(2026-08-23)이 내린 수용 결정 —
> "제안서의 Curriculum→Subject→Course→UnitNode 1급 트리는 도입하지 않고, 충돌하지 않는
> 가설 3종만 관측으로 선행한다" — 의 **본체 문서**다. 신규 스키마·마이그레이션·런타임
> 변경은 없다(범위 밖). 산출물은 ⑴ 현행 부재의 기계 동결 테스트
> `tests/backend/l1/test_unit_structure_hypothesis_freeze.py` ⑵ 이 명세다.
> **판정 기준**: WhyMath 구축 플레이북 8대 구조 원칙과 AI 질문 프로토콜 4축(존재 이유·경계·
> 붕괴·분리)이 이 문서의 심사 틀 그 자체다 — 명세가 원칙을 위반하는 제안을 통과시키면
> 그것이 결함이다(CLAUDE.md 🧱).
>
> **출처 명기(외부 문서)**: 외부 설계안 『2_단원 구조 관리』(116항)는 Kiki 제공 외부 문서로
> **저장소 밖**에 있다. 본 세션에서 접근 가능한 원문 근거는 ⑴ 수용 결정과 제안 요지를 기록한
> `curriculum_module_gap_review_r2.md` §후속(2026-08-23 — 정렬점 표·미채택 5종·후속 3종)
> ⑵ EOS 전환 설계서(2026-08-30, 별첨 『260830_WhyMath_EOS_개발기준_추적표.xlsx』 02_개발항목
> 시트 B2 행 "단원 구조 관리 — 앵커 단원 8개가 트리에 실제 노드로 존재")다. 116항 원문
> 전문은 이 세션 자료에 없었으며, 본 문서는 r2 §후속에 기록된 수용 범위를 정본으로 삼는다
> (원문 재대조가 필요해지면 Kiki에게 원문 재제공을 요청하라 — 추론으로 원문을 재구성하지
> 않는다).

관련 정본: `curriculum_module_gap_review.md`(v1) · `curriculum_module_gap_review_r2.md`(r2 —
§후속이 이 문서의 모체) · `01_data_foundation.md`(L1) · `03d_dsl_content_generator.md`(소단원
DSL) · `cur-16-concept-edge-prerequisite-meta-design.md`(EOS 검토 수용 후속의 형식 선례 —
prerequisite 메타) · `eos_curriculum_semantic_backbone_adr.md` · CLAUDE.md 🧱(8대 원칙·하드
게이트) · `backlog/tasks/CUR-09-eos-unit-structure-review-adoption.yaml`

---

## §0. 현행 실측 — 5측정 (2026-08-30~31 실측 · 기계 동결)

**측정 방법**: 동결 테스트가 ⑴ ORM 실메타데이터(`Base.metadata` — pkgutil 전 모듈 적재로
**78테이블** 완성 후 컬럼 전수 스캔) ⑵ 소단원 DSL 코퍼스(`data/corpus/units_v1/*.unit.yaml`
glob) ⑶ 원자 백본 코퍼스(`data/corpus/atom_graph_v1/graph.json`)를 **실제로 읽어** 단언한다.
선언 문자열 grep이 아니라 introspection·파싱이다(부분 적재·빈 측정은 명시 실패 — "측정
불능을 통과로 위장하지 않는다").

| # | 측정 | 실측 결과 (2026-08-30~31) | 동결 단언 |
|---|---|---|---|
| **M1** | 순서(ordering) 컬럼 | 제안 이름(`order_index`·`sequence_order`·`sort_order`·`display_order`·`unit_order`) **전 테이블 0개**. ordering-족 광역 패턴(`seq/order/position/rank/sort`) 전수 = **8개**(2026-09-29 S4-11 +1 — 각주 ¹), 전부 런타임 이벤트·콘텐츠 내부 순서(`answer_submission.sequence_no`·`student_solution_step.sequence_no`·`dialogue_turn.turn_order`·`problem_step.step_order`·`hints.step_order`¹·`problem.session_position`·`solution_paths.concept_sequence`·`device_credential.seq`). 커리큘럼 구조 테이블 16종(`unit_spec`·`learning_objective`·`curriculum_entry`·`achievement_standard`·`atom_node`·`concept`·`textbook_unit` 등) 위에는 **0개** | 제안 이름 0 등식 + 광역 전수 allowlist 등식 + 구조 테이블 0 |
| **M2** | 계층 표현 | parent-족 컬럼 전수 = **9개**. 커리큘럼 축은 3개 — `atom_node.parent_code`(백본 트리 원문)·`concept.parent_concept_id`(같은 parent_code의 UUID 해소 **프로젝션** — `l1/atom_graph/atom_backend_concept.py` 2-pass가 채움·제2 원천 아님)·`textbook_unit.parent_unit_id`(교과서 목차 **Overlay** 트리 — 외부 사실의 별도 축). 나머지 6개는 비커리큘럼(선수 코드 배열·풀이 트리·변형 계보·보호자 필드). **1급 트리 테이블(course·unit_node·subject·curriculum_node·unit_edge·unit_alignment·unit_concept) 0개** | parent-족 전수 등식 + 1급 트리 테이블 부재 |
| **M3** | Unit 간 의미 관계 | 코퍼스 실적재 엣지 **2,210건 전건 `relation: prerequisite`**(타 관계 0). 단원급(단원 217·소단원 643) 노드 **사이** 엣지 **0건**(전 엣지가 세부개념 축). `EdgeType` 선언 어휘는 6종(PREREQUISITE·COMPOSED_OF·ANALOGOUS_TO·EXTENDS·CONTRASTS·TRIGGERS_DISTRACTOR)이나 적재는 PREREQUISITE 단일 — 적재기측 동결은 `test_edge_relation_governance.py`(상보) | 관계 타입 = {prerequisite} 등식 + 단원급 간 0 + 어휘 6종 등식 |
| **M4** | unit_concept 역할 | 제안 6값 집합(CORE/SUPPORTING/PREREQUISITE/EXTENSION/ENRICHMENT/REVIEW)과 일치하는 enum **0개**(`schema/enums.py` 62종 전수 스윕·`UnitConceptRole` 이름도 부재). 인접 축은 존재하나 다른 축 — `ConceptRole` 4종(문제-개념)·`KnowledgeType` 7종(목표 유형). `unit_spec.concept_nodes`·`learning_objective.concept_nodes`는 **스칼라 TEXT 배열**(role 동반 불가형)·연결 테이블 부재. DSL(`quadratic_maxmin.unit.yaml`) `role` 키 0개. `UnitDSL`/`ObjectiveDSL` 모델 표면에도 부재 | enum 스윕 0 + 스칼라 배열 타입 + DSL 관측 0 + 모델 표면 0 |
| **M5** | unit↔standard coverage_weight | 컬럼명 `coverage_weight` **전 테이블 0개**. weight-족 전수 = **3개**, 전부 노드/헤더 **속성**(`concept.weight_in_curriculum` 단일축 중요도·`evidence_links.weight` L2 증거·`problem.exam_authority_weight` 기출 권위) — **N:M 링크 배분 가중치는 0개**(`concept_standard_link` 컬럼: link_id·concept_code·norm_id·link_type·note뿐). DSL `coverage_weight` 키 0개. **기반 사실**: 성취기준→원자 1:N은 이미 실재 — 코퍼스에서 성취기준 844종 중 **510종이 복수 원자에 매핑**(최다 [2수01-06] 7원자) → 오늘의 도달률 계산은 균등 가중일 수밖에 없다 | coverage_weight 0 등식 + weight-족 allowlist 등식 + DSL 관측 0 + 1:N 실재(≥1) |

¹ **`hints.step_order` 편입 판정(2026-09-29 · S4-11 · 가설 1 비발화)**: `hints` 테이블(graded
힌트 카탈로그)의 `step_order`는 힌트가 **어느 풀이 단계의 것인지** 가리키는 참조 키다 —
`schemas/v1.1/hint.schema.yaml`의 `SolutionStepRef`(= `solution_path_id` + `step_order`)를 그대로
영속한 것이고, 값의 출처는 기존 allowlist 항목 `problem_step.step_order`(풀이 경로 단계 order)다.
따라서 ⑴ 새 순서 *축*이 아니라 이미 동결된 콘텐츠 내부 순서의 사본이고 ⑵ 커리큘럼 형제(단원
간) 순서·진도와 무관하며 ⑶ `hints`는 커리큘럼 구조 테이블이 아니다(M1 본체 단언 "구조 테이블 위
0개"는 그대로 성립). 가설 1(§1)의 채택 트리거(T1-a·b·c) 어느 것도 발화하지 않았으므로 §6의
스키마 태스크 승격 대상이 아니라 **allowlist 편입**(테스트 docstring이 지시하는 "런타임/콘텐츠
내부 순서면 allowlist에 스코프 주석과 함께 추가")이다. 검토한 대안: 복합 FK
`(solution_path_id, step_order) → problem_step`은 `problem_step`에 해당 UNIQUE가 없어 불가하고,
`problem_step.step_id`(UUID) FK로 바꾸면 yaml 정본 참조 형태(경로+order)와 결정론 `hint_id`·
서빙 범위 조회(`step_order >= k`)가 조인 의존이 된다 — 컬럼을 없애는 쪽이 더 옳다는 근거는 찾지
못했다.

**동결 구조 — red가 나면**: 위 등식·0-단언은 "가설이 현실이 됐다"의 기계 신호다. 누군가
순서 컬럼·역할 필드·가중치를 추가하면 해당 단언이 red가 나고, 단언 메시지가 이 문서를
가리킨다. 그때의 절차는 §6. xfail이 아닌 **명시 단언**을 택했다 — xfail은 "실패를 기대"하는
표현이라 부재 관측(현재 green이어야 함)에 맞지 않고, allowlist **등식**은 추가뿐 아니라
제거·개명도 잡는다(변별력 양방향).

**정밀화 1건(acceptance ① 어구 대비)**: "계층 표현은 `atom_node.parent_code`뿐"은 백본
기준으로 참이되, 실측 전수는 위 M2처럼 **단일 원천(코퍼스 parent_code) + 프로젝션 2개 +
교과서 Overlay 1개**로 정밀화된다. `concept.parent_concept_id`는 같은 parent_code를 UUID로
해소한 적재 산출물이지 제2의 계층 정의가 아니다 — 이 구분을 잃으면 "이중 정본" 오판이 된다.

---

## §1. 가설 1 — Sequence/Prerequisite 분리

> 제안: 공식 커리큘럼 **순서**(진도 — order_index류)와 **선수학습 의존**(PREREQUISITE 엣지)을
> 서로 다른 축으로 관리한다.

### 1.1 존재 이유 (왜 필요한가)

"교과서 진도 순서"와 "인지적 선수 관계"는 **다른 종류의 사실**이다. 진도는 행정·출판 사실
(개정·교과서·학교마다 다르고 바뀐다), 선수는 인지 구조 사실(개정에도 비교적 영속 — Curriculum
Overlay 원칙의 존재 이유와 같은 뿌리). 현재 WhyMath에서 학습경로·게이팅은 PREREQUISITE
2,210엣지로 계산하지만, **"공식 다음 단원" 질의에 답할 기계 정렬 가능한 좌석이 없다**:
`textbook_unit.unit_number`는 표시용 문자열 라벨(사전순 정렬이 "10-1"<"2-1"로 붕괴하는 형),
`curriculum_entry.introduced_grade/grade_band`는 학년 단위 해상도뿐이다. L6 학교진도 모드가
실체화되면 이 공백이 실사용 실패로 드러날 것이다 — 그때가 채택 시점이다(§1.5).

### 1.2 경계 (어디까지인가)

순서는 **Overlay 소속**이다. 순서는 *특정 개정·특정 교과서·특정 코스*의 사실이지 개념/원자
노드의 속성이 아니다. 승격하더라도 자리는 이미 Overlay인 테이블(`curriculum_entry` 셀 또는
`textbook_unit` 목차)의 **추가 컬럼**이지, 새 1급 트리도 새 엣지 타입도 아니다. 스코프 키는
최소 (개정, 부모 단원) — 전역 단일 순서는 성립하지 않는다(학교·교과서마다 진도가 다르다).

### 1.3 붕괴 지점 (어디서 실패하는가)

1. **순서를 PREREQUISITE 엣지로 흉내**("앞 단원→뒤 단원" 선수 엣지 일괄 추가) — 관계 타입
   오염 + DAG에 거짓 의존 유입 → 학습경로가 행정 순서와 인지 의존을 구분 못 하게 된다.
   이 가설의 최대 방어 대상. M3의 "단원급 간 엣지 0건" 단언이 이 유입을 감시한다.
2. **order를 백본 노드에 주입**(`atom_node`/`concept`에 순서 컬럼) — 개정·교과서가 바뀔
   때마다 백본을 다시 쓰게 된다(Curriculum은 Overlay 원칙 붕괴·노드 순수성 위반).
3. **전역 단일 순서 가정** — 순서는 스코프된 사실인데 단일 정수로 두면 두 교과서를 동시
   지원하는 순간 정본이 둘이 된다(유지보수 지옥 연쇄).

### 1.4 분리할 것

| 축 | 오늘의 좌석 | 성격 |
|---|---|---|
| 의존(Prerequisite) | `concept_edge` PREREQUISITE + CUR-16 메타(RequiredStrength·DependencyLevel) | 인지 사실 — traversal 대상 |
| 순서(Sequence) | **부재** (가설) | 행정/출판 사실 — 정렬 대상·traversal 아님 |
| 표시 라벨 | `textbook_unit.unit_number`(문자열) | 원문 사실 — 정렬 불가·표시만 |

**8대 원칙 정합**: Concept Purity ✅(노드 무주입 — 승격 시에도 Overlay 컬럼) · Curriculum
Overlay ✅(순서는 셀/목차 속성) · Relation Typing 최소화 ✅(SEQUENCE류 엣지 타입을 만들지
않는다 — 순서는 엣지가 아니라 컬럼. M3 어휘 6종 동결이 감시) · 나머지 5원칙 무접촉.

### 1.5 채택 트리거 (어떤 관측이 나오면 스키마 태스크로 승격하는가)

- **T1-a (소비자 등장)**: L6 학교진도 모드·학습경로 스케줄러가 "공식 다음 단원" 질의를 실제
  코드 경로로 요구하는 시점(현재 소비자 0 — "작동한 비율" 원칙상 소비자 없는 컬럼은 죽은
  좌석이다).
- **T1-b (정렬 실패 실측)**: `textbook_unit` 적재 실데이터에서 `unit_number` 문자열 정렬이
  실제 목차 순서와 어긋나는 사례 실측.
- **T1-c (EOS 앵커 계측)**: EOS 전환 검증의 앵커 단원 6~8개 등록(전환 설계서 N1)이 단원 간
  순서 비교 계측을 요구할 때.

**승격 형태(트리거 발화 시)**: `curriculum_entry` 또는 `textbook_unit`에 스코프된 순서 컬럼을
추가하는 **별도 스키마 태스크**(CUR-신번호 — `backlog.py add` 경유). `atom_node`/`concept`
주입 금지·SEQUENCE 엣지 타입 신설 금지를 acceptance에 명기하고, M1/M3 동결 테스트의
allowlist·어휘 갱신을 같은 PR에서 한다.

---

## §2. 가설 2 — Unit-Concept 역할 enum

> 제안: 단원↔개념 연결에 역할 라벨 — CORE / SUPPORTING / PREREQUISITE / EXTENSION /
> ENRICHMENT / REVIEW.

### 2.1 존재 이유

단원에 개념이 flat 배열로 붙으면 "이 단원의 **핵심**이 무엇인가"를 기계가 모른다. 소비처
후보: 진단 문항 배분(핵심 개념에 슬롯 가중)·복습 개념 재출제 억제(REVIEW)·영재 모드 한정
노출(EXTENSION/ENRICHMENT)·선수 결손 우선 점검(PREREQUISITE 역할). 현 파일럿(개념 3개·목표당
1개)에서는 이 구분 없이도 성립하나, 단원당 개념 수가 커지면 flat 배열의 정보 손실이 배분
품질로 드러난다.

### 2.2 경계

역할은 **membership(단원→개념 소속 연결)의 속성**이다 — ⑴ 개념 노드의 속성이 아니고(같은
개념이 A단원에서 CORE, B단원에서 REVIEW일 수 있다 — 노드 속성이면 이 문맥성이 표현 불가)
⑵ 개념 간 엣지도 아니다(traversal 그래프와 무관).

**관계 폭발이 아닌 근거(명시)**: 붕괴 연쇄의 "관계 폭발"은 개념 노드 간 의미 엣지가 Edge≈N²
로 증식해 traversal이 dense화되는 문제다. 역할 라벨은 ⑴ `concept_edge`에 엣지 타입을 하나도
추가하지 않고(traversal 관계 타입 6종 불변 — M3 어휘 동결이 감시) ⑵ 이미 존재하는 단원→개념
소속 연결(현 `concept_nodes` ARRAY)의 **원소에 라벨 1개**를 붙일 뿐이며 ⑶ 그 연결 자체는
트리 국소적(단원당 개념 수십 개 상한)이라 N² 축이 아니다. 폭발 위험은 관계 수가 아니라
**역할 어휘 수**에 있고, 그것은 §2.3-①이 다룬다.

### 2.3 붕괴 지점

1. **역할 어휘 폭발** — 6종이 12종이 되는 경로. 특히 기존 축(`ConceptRole` 4종·문제-개념,
   `KnowledgeType` 7종·목표 유형)과 어휘가 겹치기 시작하면(SUPPORTING이 이미 ConceptRole에
   있다) 세 축이 뒤섞인다. 방어: 별 enum·별 좌석, 기존 enum에 값 덧대기 금지(M4 인접 축
   동결이 감시).
2. **역할의 노드 주입** — "이 개념은 CORE다"를 `concept`/`atom_node` 컬럼으로 넣는 순간
   단원 문맥이 사라지고 Concept Purity가 깨진다.
3. **PREREQUISITE 어휘 충돌** — 제안 역할값 PREREQUISITE는 엣지 타입 PREREQUISITE와 글자가
   같다. 채택 시 역할측 개명(예: PREREQ_REVIEW)을 반드시 검토 — 같은 글자가 두 축에 살면
   질의·로그·프롬프트에서 상시 혼동한다.
4. **검증 없는 라벨** — 누가 CORE를 정하는가. AI 추정 라벨이면 `atom_node.review_status`
   'ai_estimated' 정직 표기 선례를 따라야 한다(무표기 라벨은 측정 없는 정밀도 위장).

### 2.4 분리할 것

| 축 | enum | 스코프 | 상태 |
|---|---|---|---|
| 단원↔개념 역할 | (가설 — 미정의) | unit→concept membership | **부재** (M4) |
| 문제↔개념 역할 | `ConceptRole` 4종 | problem→concept | 존재 — 다른 축 |
| 목표 지식 유형 | `KnowledgeType` 7종 | learning_objective 분류 | 존재 — 다른 축 |

**8대 원칙 정합**: Concept Purity ✅(라벨은 연결에·노드 무주입) · Relation Typing 최소화
✅(엣지 타입 0 추가 — §2.2 근거) · Curriculum Overlay ✅(단원 소속 정보는 명세/Overlay 계층
소관) · Layer Separation ✅(L1 명세 데이터 — L4가 소비) · 나머지 무접촉.

### 2.5 채택 트리거

- **T2-a (배분 실패 실측)**: 단원당 `concept_nodes` 규모가 커져(파일럿 3개 → 예: 10개+)
  진단·발주 배분이 flat 배열로는 실패하는 사례 실측.
- **T2-b (소비자 등장)**: L6 모드(영재·복습)나 진단 배분기가 역할 구분을 실제 코드로 소비
  하는 지점 등장.
- **T2-c (발주 차등)**: 콘텐츠 발주서(`work_order`)가 개념별 차등 슬롯 수를 요구할 때
  (현재는 목표 단위 균일).

**승격 형태**: `concept_nodes` 원소 구조화(JSONB `{code, role}` 또는 연결 테이블) + **신설
별도 enum**(어휘 6종 이하 유지·PREREQUISITE 개명 검토·검증 표기 필드 동반)을 별도 스키마
태스크로. `UnitDSL`은 `extra="forbid"`라 필드 추가가 곧 계약 변경이다 — DSL·컴파일러·ORM·
동결 테스트(M4)를 같은 태스크에서 일괄 갱신한다.

---

## §3. 가설 3 — coverage_weight

> 제안: 성취기준이 여러 단원/개념에 걸칠 때 배분 비율(예: 0.3+0.5+0.2)을 저장한다.

### 3.1 존재 이유

성취기준→원자 1:N은 **이미 실재한다**(M5 실측: 844종 중 510종이 복수 원자 매핑·최다 7원자).
그런데 배분 가중치 좌석이 없으므로 도달률류 계산은 **균등 가중을 강제**당한다 — [2수01-06]이
7원자에 걸리면 각 1/7. 실제로는 특정 원자가 그 성취기준의 절반일 수 있다. 영향 지점: 성취기준
도달률(target_progress류)·교사 대시보드 평가 리포트·진단 문항 배분의 정밀도.

### 3.2 경계

가중치는 **링크(N:M 연결)의 속성**이다 — 자리는 `concept_standard_link`(개념↔성취기준) 또는
단원↔성취기준 연결이지, 노드가 아니다. 합=1.0 정규화의 스코프는 성취기준 1건(그 성취기준에
걸린 링크들의 합). 기존 `concept.weight_in_curriculum`(노드 단일축 중요도)·`edge_strength`
(개념 간 엣지 강도)와 **좌석이 다르다** — §3.4 표.

### 3.3 붕괴 지점

1. **출처 없는 수치** — 0.3은 누가 쟀는가. AI 추정 float가 검증 표기 없이 진단에 들어가면
   "측정 없는 정밀도 위장"이다(검증 권위 서열 위반). 방어: CUR-16 선례 — 연속 float보다
   **이산 등급 enum**(RequiredStrength 4종형)이 검증·검수 가능성이 높다. 채택 시 이산 등급을
   1차 후보로 검토하고, float를 쓰면 출처·검증 필드를 동반한다.
2. **정규화 붕괴** — 원자가 추가·병합될 때마다 나머지 가중 재분배가 필요(합=1.0 유지). 이
   재분배를 수작업으로 두면 유지보수 지옥, 자동으로 두면 검증 이력이 사라진다. 방어: 합
   제약을 DB CHECK가 아니라 파이프라인 검증으로(가짜 CHECK 없음 — house style), 재분배는
   적재기 멱등 재계산으로.
3. **이중 정본** — `weight_in_curriculum`(노드 중요도)과 coverage_weight(링크 배분)를 혼용
   하면 "개념의 무게"가 두 곳에 산다. 방어: 이름·좌석·의미를 §3.4처럼 분리 명기, M5 weight-족
   allowlist 등식이 신규 유입을 강제 가시화.

### 3.4 분리할 것

| 좌석 | 무엇의 가중인가 | 상태 |
|---|---|---|
| 링크 배분 가중(가설) | 성취기준 1건이 여러 원자/단원에 걸칠 때의 배분 | **부재** (M5) |
| `concept.weight_in_curriculum` | 개념 노드의 교육과정 내 단일축 중요도 | 존재 — 노드 속성 |
| `concept_edge.edge_strength`·`minimum_mastery` | 개념 간 엣지의 강도·문턱 | 존재 — 엣지 속성 |
| `evidence_links.weight`·`problem.exam_authority_weight` | L2 증거·문제 헤더 | 존재 — 비커리큘럼 |

**8대 원칙 정합**: Concept Purity ✅(노드 무주입 — 링크 속성) · Curriculum Overlay ✅(성취
기준 매핑은 Overlay 축) · Relation Typing 최소화 ✅(엣지 타입 불변 — 기존 링크의 컬럼) ·
단일 진실 원천 ⚠️(§3.3-③ 이중 정본 위험을 명기적으로 관리해야 통과) · 나머지 무접촉.

### 3.5 채택 트리거

- **T3-a (균등 가중 오차 실측)**: 도달률 소비자(target_progress·교사 리포트)에서 균등 가중이
  실제 판단 오차를 낳은 사례 실측(예: 도달 표기와 교사 평가의 불일치 신고).
- **T3-b (링크 적재 실체화)**: `concept_standard_link`가 실제 1:N 다중 링크 데이터를 갖게
  되는 적재 시점(현재 좌석은 있으나 가중 없는 링크만 가능).
- **T3-c (EOS 앵커 계측)**: 앵커 단원 생산성 비교(전환 설계서 N3)가 "성취기준 커버 비중"
  계측을 요구할 때.

**승격 형태**: `concept_standard_link`(또는 단원↔성취기준 링크)에 nullable 가중 좌석 —
이산 등급 우선 검토·출처/검증 표기 동반·합 검증은 파이프라인 책임 — 을 별도 스키마 태스크로.
M5 동결 테스트의 allowlist 갱신을 같은 PR에서 한다.

---

## §4. CI 배선 실재 확인 (acceptance ③ — "존재함"≠"돌아감")

**방법** (OPS-03/OPS-10 선례 — 배선을 주장이 아니라 실측으로):

1. **수집 대상 확인**: backend 잡의 pytest는 `src/backend`를 cwd로 `pyproject.toml`
   `[tool.pytest.ini_options] testpaths = ["../../tests/backend"]`를 쓴다(`ci.yml` backend 잡
   "Pytest (with coverage)" 스텝). 신규 테스트는 `tests/backend/l1/`에 있으므로 testpaths
   트리 안이다.
2. **수집 실측**: `src/backend`에서 `pytest --collect-only`로 신규 파일의 테스트 19건이
   실제 수집되는지 확인(아래 결과). 파일 단위가 아니라 **기본 수집 경로**로 잡히는지를 본다
   — 마커 게이트(`integration`은 기본 skip)에 걸리지 않는 일반 테스트임도 함께 확인.
3. **트리거 경로 확인**: `ci.yml` `changes` 잡의 backend 필터가
   `^(src/backend/|tests/backend/|…|data/corpus/|…)`를 포함 — 이 태스크의 변경 파일
   (`tests/backend/l1/**`)과 감시 대상(`data/corpus/**`) 양쪽 모두 backend 잡을 트리거한다.
4. **린트 배선**: backend 잡의 ruff/black 스텝이 `../../tests/backend`를 명시 검사하므로
   신규 테스트 파일도 린트 대상이다(PR #223 선례).
5. **구조 동결과의 관계**: 배선 실재성 자체는 `tests/infra/test_test_suite_wiring.py`(OPS-10)
   가 기계 동결한다 — 본 확인은 그 위에서 "이 파일이 그 배선에 실제로 올라탔는가"의 실측이다.

**결과** (2026-08-30~31 실측):

```
$ cd src/backend && pytest -c pyproject.toml --collect-only -q \
    ../../tests/backend/l1/test_unit_structure_hypothesis_freeze.py
→ 19 tests collected                                  # 수집 실측(파일 지정)
$ pytest -c pyproject.toml --collect-only -q 2>/dev/null | grep -c unit_structure_hypothesis
→ 19                                                  # 기본 testpaths 수집에도 포함 실측
$ pytest -c pyproject.toml ../../tests/backend/l1/test_unit_structure_hypothesis_freeze.py
→ 19 passed · EXIT=0                                  # green 실측
```

integration 마커 없음 → 기본 실행에서 skip되지 않는다. hermetic(DB 불요)이므로 PG 서비스
유무와 무관하게 backend 잡 어디서든 판정이 나온다.

---

## §5. 범위 밖 — 명시적 비채택 (acceptance ⑤)

아래 5+1종은 이번 수용에 **포함되지 않는다**(r2 §후속 ② 승계 + 태스크 acceptance ⑤).
비채택은 침묵이 아니라 결정이다 — 각 항의 재검토 조건 없이 재도입하지 않는다.

| # | 비채택 항목 | 사유 (WhyMath 정본과의 충돌 지점) |
|---|---|---|
| 1 | **UnitNode 1급 독립 Aggregate**(Curriculum→Subject→Course→UnitNode 트리) | Concept이 영속 원본·Unit은 원자 백본의 파생 뷰(Curriculum은 Overlay). 1급 트리는 truth source를 둘로 만든다. M2 "1급 트리 테이블 0개" 단언이 기계 동결 |
| 2 | **Graph DB(Neo4j) 추가** | 런타임 미도입 확정(2026-08-03 정정 — PG 단일 평면 정본, CLAUDE.md 스택 표). 단원 그래프도 PG 축 |
| 3 | **Drag&Drop CMS**(단원 이동·병합·분리 GUI) | 콘텐츠 파이프라인 정본이 "YAML=소스·DB=산출물·단방향"(unit_compiler) — GUI 편집은 소스 정본을 DB로 옮기는 역방향. 수작업 신호 실측 0 |
| 4 | **다국가 UnitAlignment 즉시 구축** | `curriculum_entry`가 다국 셀 구조를 이미 갖되, 데이터는 Phase 1 KR+US+IMO 3축만(r2 §2-⑤ 승계) |
| 5 | **교과별 확장 metadata를 Unit core schema에 주입** | subject-neutral 코어에 교과 특수 필드를 넣으면 과목 확장 시 코어가 오염된다 — 교과 특수성은 Overlay/어댑터 축(`curriculum_entry.subject` 선례). Concept Purity의 Unit 판 |
| (6) | **관계 타입 12종 전면 채택** | r2 §후속 ②-4 승계 — 약한 관계 traversal 금지·`equivalent`는 SymPy 단일 권위. M3 어휘 6종 동결이 감시 |

---

## §6. 갱신 프로토콜 — 동결 테스트가 red를 내면

1. **red는 오류가 아니라 신호다** — "가설이 현실이 됐다(누군가 해당 필드/테이블/엣지를
   추가했다)". 테스트를 조용히 고쳐 통과시키는 것은 이 장치의 목적 전도다.
2. 해당 가설 절(§1~§3)의 **채택 트리거가 실제로 발화했는지** 대조한다 — 트리거 없이 필드가
   생겼다면 그 변경 자체를 되물어야 한다(소비자 없는 좌석 = "작동한 비율" 원칙 위반).
3. 트리거가 발화했다면: ⑴ 이 문서의 해당 절을 "가설→채택"으로 갱신하고 ⑵ 승격 형태 항의
   제약(노드 무주입·엣지 타입 불변·검증 표기)을 acceptance로 옮긴 **스키마 태스크**를
   `backlog.py add`로 등재하며 ⑶ 동결 테스트의 allowlist/등식을 같은 PR에서 갱신한다.
4. 이 문서와 테스트는 쌍이다 — `test_spec_document_exists_and_covers_five_measurements`가
   문서 실재·절 구성(M1~M5·채택 트리거·범위 밖)을 상호 감시한다.

---

**작성**: 2026-08-30~31 (CUR-09) · **동결 테스트**: `tests/backend/l1/test_unit_structure_hypothesis_freeze.py` (19건)
**모체 결정**: `curriculum_module_gap_review_r2.md` §후속(2026-08-23) · **다음 검토**: 채택 트리거 발화 시 또는 EOS 앵커 단원 등록(전환 계획 N1) 착수 시
