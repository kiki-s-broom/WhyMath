# 44. EOS 버전 관리(Version Management) 설계

> **범위**: 교육 콘텐츠(교육과정, 성취기준, 개념, 문제, 풀이, 오개념, 교수전략, 프롬프트, 정책 등)의 변경 이력과 재현성을 보장하는 버전 관리 Foundation.
> **상태**: 설계 확정(2026-08-25). MVP 필수 항목 + 2단계 확장 범위.
> **관련**: `docs/standards/eos_identity_layer_011_1_decision.md`, `docs/architecture/01_data_foundation.md`, `docs/architecture/system_deep_dive.md`, `docs/architecture/04g_pedagogy_strategy_catalog.md`, `backlog/tasks/ARCH-20-content-provenance-enforcement-gate.yaml`

---

## 1. 핵심 설계 원칙 10가지

1. **Entity ID와 Version ID를 반드시 분리한다.** `problem_id`는 논리적 객체, `version_id`는 특정 시점의 불변 스냅숏.
2. **Published Version은 Immutable하게 유지한다.** 수정이 필요하면 새 버전을 생성한다.
3. **수정은 기존 row를 UPDATE하지 않는다.** `version_id`가 새로 발급되고 이전 버전은 그대로 보존된다.
4. **Draft Revision과 Published Version을 분리한다.** Autosave는 revision, 검토를 거쳐 확정된 것만 version.
5. **Node뿐만 아니라 Relationship/Edge도 버전 관리한다.** ConceptEdge, PrerequisiteEdge, MisconceptionEdge, Problem-Concept Mapping 포함.
6. **학습 이벤트에는 현재 Entity가 아니라 실제 사용한 Version을 고정한다.**
7. **AI 결과에는 Model + Prompt + Policy + Knowledge + Retrieval Version을 기록한다.**
8. **개별 Version과 별도로 Knowledge/Content Release Snapshot을 둔다.**
9. **Version History와 Audit Log를 분리하되 연결한다.**
10. **EOS Runtime은 VersionContext 하나로 당시 교육 환경을 재현할 수 있어야 한다.**

---

## 2. WhyMath 맥락에서의 조율

### 2.1 `011_1 EOS Identity & ID Domain`과의 관계

`docs/standards/eos_identity_layer_011_1_decision.md`는 다음을 이미 확정했다.

- **Unified `Entity` 슈퍼테이블은 보류**: 7계층 독립성 해치고 마이그레이션 비용이 큼. WhyMath는 도메인별 독자 UUID PK를 유지한다.
- **"ID는 무의미하다"는 거부**: WhyMath는 curriculum/language/renderer에 종속되지 않으되, 수학 개념의 의미적 정체성(`math.<area>.<slug>`)은 ID에 담는다.
- **Content ID ≠ Content Version ID는 채택**: `Problem`에 nullable `content_version_id` 추가, `ContentVersion` 스키마/ORM/마이그레이션 설계가 후속 태스크로 등재되어 있다.

따라서 본 설계에서는 **물리적 Unified `entity` 슈퍼테이블을 도입하지 않는다**. 대신 논리적으로는 `entity_id` namespace를 인정하고, 물리적으로는 각 도메인(`Problem`, `Concept`, `Solution`, `PedagogyStrategy`, `PromptTemplate` 등)이 독자 UUID PK를 유지하면서 버전 헤더를 공유 contract로 맞춘다.

### 2.2 WhyMath 현행 상태

| 영역 | 현재 | 향후 |
|---|---|---|
| `Problem.problem_id` | UUID PK | 유지 + `content_version_id` 추가 |
| `Problem.curriculum_version` | 교육과정 버전 문자열 | `CurriculumRelease` 버전 객체로 정리 |
| `EvidenceEvent.pack_version` | 팩 버전 | `PedagogyStrategy`/`PromptBundle` 버전으로 확장 |
| `Concept.concept_id` | `math.<area>.<slug>` | 유지 + `concept_version_id` 추가(2단계) |
| `schema_version` | `S1-16`에서 `Problem/PublicProblem`에 추가 중 | 모든 버전 관리 대상으로 확장 |
| 출처/감사 | `ARCH-20` provenance 게이트 | 버전 이력과 연결 |

---

## 3. 핵심 개념

| 개념 | 식별자 예 | 의미 |
|---|---|---|
| `entity_id` | `PRB-00001234`, `CON-MATH-QUADRATIC_FUNCTION` | 변하지 않는 논리적 객체 ID |
| `version_id` | `VER-01K...` | 특정 시점의 불변 버전 |
| `revision_id` | `REV-...` | 편집·검토 과정의 수정 이력(Draft mutable) |
| `schema_version` | `problem-schema@2.1` | Entity Version과 별도인 Schema Version |
| `release_id` | `EOS-MATH-2026-08-20` | Domain Snapshot/Release 단위 |
| `version_context_id` | `VC-20260820-001` | Runtime에 고정된 교육 환경 컨텍스트 |

**핵심 공식**: `Problem ID != Problem Version ID`. 현재 `GET /problems/{problemId}`는 Published version을 반환하지만, 특정 버전은 `GET /problems/{problemId}/versions/{versionId}`로 조회한다.

---

## 4. 1급 버전 관리 대상

| 영역 | 객체 |
|---|---|
| 교육과정 | `Curriculum`, `Unit` |
| 성취기준 | `AchievementStandard`, `Objective` |
| 개념 | `Concept`, `Definition`, `Theorem`, `Formula` |
| 그래프 | `ConceptEdge`, `PrerequisiteEdge`, `MisconceptionEdge` |
| 오개념 | `Misconception` |
| 교수전략 | `PedagogyStrategy` |
| 문제 | `Problem`, `ProblemType`, `DifficultyDefinition`, `Rubric` |
| 풀이 | `Solution`, `SolutionStep`, `Hint` |
| 콘텐츠 | `LearningContent`, `Visualization` |
| AI 설정 | `PromptTemplate`, `TutorPolicy`, `AssessmentPolicy`, `RecommendationPolicy` |

**특히 빠뜨리면 안 되는 것**: 엣지와 매핑. `Problem-Concept Mapping`, `Concept-Standard Mapping` 등 relationship 자체도 version 대상이다.

---

## 5. 버전 범위

EOS/WhyMath에는 최소 5종류의 버전이 공존한다.

```
EOS Versioning
├── Application Version        # WhyMath App 3.2.1
├── API Version                # /api/v1/problems
├── Schema Version             # problem-schema@2.3
├── Entity Version             # Problem PRB-001234 v7
├── Knowledge Graph Version    # MATH-KG@87
├── Prompt Version             # PROMPT-GENERATE-PROBLEM v17
├── Model Version              # MODEL_PROFILE_MATH_REASONER_V5
├── Policy Version             # TUTOR-HINT@3
├── Dataset Version            # DATASET-MATH-EVAL v3
└── Release Version            # EOS-MATH-2026.08.20
```

**AI Configuration Version**은 Model, Prompt, System Policy, Tool Config, Retrieval Config를 포함한다.

---

## 6. 스키마/DB 설계

### 6.1 Hybrid 구조

`011_1`에서 Unified Entity 슈퍼테이블은 보류되었으므로, WhyMath는 다음 **Hybrid**를 채택한다.

- **Common Version Header**: 모든 도메인이 공유하는 버전 메타데이터는 공통 contract로 정의한다.
- **Domain-specific Version Payload**: 실제 콘텐츠 payload는 각 도메인 테이블이 독자적으로 관리한다.

### 6.2 공통 버전 헤더 (Pydantic)

```python
class VersionHeader(BaseModel):
    version_id: UUID          # VER-...
    entity_id: str            # 논리적 ID (PRB-..., CON-...)
    entity_type: str          # "Problem" | "Concept" | ...
    version_no: int           # 1, 2, 3, ...
    schema_version: str       # problem-schema@2.1
    status: VersionStatus     # DRAFT | IN_REVIEW | APPROVED | PUBLISHED | DEPRECATED | RETIRED
    previous_version_id: UUID | None
    change: VersionChange     # type, impact, reason, ticket_id
    source: VersionSource     # source_ids, derived_from
    governance: VersionGovernance  # created_by, reviewed_by, approved_by
    integrity: VersionIntegrity    # content_hash
    created_at: datetime
    published_at: datetime | None
```

### 6.3 도메인별 버전 테이블

```python
class ProblemVersion(BaseModel):
    version_id: UUID PK       # VersionHeader와 1:1
    problem_id: UUID          # Problem entity FK
    payload: ProblemPayload  # JSONB 또는 정규화된 컬럼
    # problem-specific 메타: stem_hash, answer_hash, difficulty_at_publish

class ConceptVersion(BaseModel):
    version_id: UUID PK
    concept_id: str           # math.<area>.<slug>
    payload: ConceptPayload

class SolutionVersion(BaseModel):
    version_id: UUID PK
    solution_id: UUID
    problem_id: UUID
    payload: SolutionPayload
```

### 6.4 Entity 테이블의 `current_published_version_id`

```python
class Problem(BaseModel):
    problem_id: UUID PK
    current_published_version_id: UUID | None
    entity_status: EntityStatus  # ACTIVE | ARCHIVED
    created_at: datetime
```

Entity 상태(`ACTIVE`)와 Version 상태(`PUBLISHED`/`RETIRED`)는 명확히 분리한다.

---

## 7. Lifecycle 상태 머신

```
DRAFT
  ↓ (submit for review)
IN_REVIEW
  ↓ (request changes)      ↓ (approve)
DRAFT  ←────────────────  APPROVED
  ↓                         ↓ (publish)
PUBLISHED
  ↓ (deprecate)
DEPRECATED
  ↓ (retire)
RETIRED
```

- **PUBLISHED → DRAFT 금지**: 이미 Published 버전을 다시 수정 불가 상태로 되돌리지 않는다. 대신 Published 버전을 clone해 Draft vN+1을 만든다.
- **Soft Delete**: `DELETE FROM problem`을 피하고 `DEPRECATED`/`RETIRED`/`WITHDRAWN` 상태로 처리한다. 법적 삭제 요청은 별도 정책.

---

## 8. Dependency & Reference

### 8.1 Floating vs Pinned Reference

| 구분 | 식별자 | 용도 |
|---|---|---|
| Floating reference | `entity_id` | CMS 편집 화면, 현재 최신 버전을 따라감 |
| Pinned reference | `version_id` | Published 콘텐츠, 평가, 감사, 재현성 |

**원칙**: Draft에서는 Entity reference 허용. Published snapshot에서는 Version reference를 고정한다.

### 8.2 Version Dependency

```python
class VersionDependency(BaseModel):
    source_version_id: UUID   # Problem v7
    target_version_id: UUID   # Concept v5
    dependency_type: str      # ALIGNED_TO | USES | REQUIRES | DERIVED_FROM | VALIDATED_AGAINST | GENERATED_WITH
```

Publish 시 dependency를 lock한다: Draft `Problem → Concept(current)` → Publish `Problem v4 → Concept v7`.

---

## 9. Publish Gate & QA 연계

Publish는 단순 status 변경이 아니라 검증 파이프라인이다.

```
Draft
  ↓ Schema Validation
  ↓ Source Validation
  ↓ License Validation
  ↓ Dependency Validation
  ↓ Math Validation
  ↓ Graph Validation
  ↓ AI Validation
  ↓ Human Review
  ↓ Approval
  ↓ Publish
```

각 버전은 QA 결과를 연결한다.

```python
{
  "qa_status": "PASSED",
  "qa_run_id": "QA-392",
  "validator_bundle_version": "VAL-17"
}
```

---

## 10. Release Snapshot & VersionContext

### 10.1 Domain Snapshot / Release

개별 Entity 버전만으로는 "2026년 8월 1일 시스템 전체가 어떤 상태였는가?"에 답하기 어렵다. 따라서 Release Snapshot을 둔다.

```python
{
  "release_id": "EOS-MATH-2026-08-20",
  "curriculum": "CURR-KR-MATH-2022@12",
  "knowledge_graph": "KG-MATH@87",
  "problem_bank": "PB-MATH@142",
  "misconception_db": "MC-MATH@38",
  "pedagogy": "PED@22",
  "prompt_bundle": "PROMPT@51",
  "policy_bundle": "POLICY@17",
  "schema": "EOS-SCHEMA@9"
}
```

### 10.2 Runtime VersionContext

학습 세션은 `VersionContext`를 고정한다.

```python
{
  "version_context_id": "VC-20260820-001",
  "release_id": "EOS-MATH-2026-08-20",
  "curriculum_version_id": "...",
  "knowledge_graph_version_id": "...",
  "problem_version_id": "...",
  "solution_version_id": "...",
  "pedagogy_version_id": "...",
  "tutor_policy_version_id": "...",
  "prompt_version_id": "...",
  "model_config_version_id": "...",
  "retrieval_version_id": "..."
}
```

이벤트마다 수십 개 Version ID를 반복 저장하지 않고, `VersionContext`를 별도 참조한다.

---

## 11. AI 재현성 (장기)

특정 AI Tutor 답변을 재현하려면 다음이 필요하다.

```
Event
  ↓
VersionContext
  ├─ Curriculum Release
  ├─ Knowledge Release
  ├─ Problem Version
  ├─ Solution Version
  ├─ Rubric Version
  ├─ Pedagogy Version
  ├─ Tutor Policy Version
  ├─ Prompt Version
  ├─ Model Configuration Version
  └─ Retrieval Version
```

AI 생성물에는 반드시 다음을 기록한다.

```python
{
  "generator": {
    "model": "math-model-x",
    "model_version": "2026-08",
    "model_profile_id": "MODEL_PROFILE_MATH_REASONER_V5",
    "prompt_version_id": "PROMPT-GENERATE-PROBLEM@17",
    "temperature": 0.2,
    "retrieval_config_version": "RAG-37",
    "knowledge_snapshot_id": "KG-MATH@87",
    "embedding_model_version": "...",
    "validator_version": "VAL-17",
    "generated_at": "2026-08-20T10:30:00Z"
  }
}
```

MVP에서는 `generator` 메타데이터를 이벤트/콘텐츠에 저장하는 계약만 정의하고, 별도 `ModelProfile`/`PromptBundle` 테이블은 2단계에서 구현한다.

---

## 12. MVP 범위

Phase 1(MVP)에서 반드시 구현해야 할 최소 기능.

- `entity_id` / `version_id` / `version_no` / `previous_version_id`
- Lifecycle: `DRAFT`, `IN_REVIEW`, `APPROVED`, `PUBLISHED`, `RETIRED`
- `change_type` / `change_reason`
- Governance: `created_by`, `reviewed_by`, `approved_by`
- Timestamp: `created_at`, `published_at`
- `content_hash`
- Published = immutable 원칙
- Problem/Concept/Solution 버전 테이블
- 기본 API: 버전 생성, 목록, 조회, Diff
- CMS UI: 현재 버전, 버전 목록, 상태, 변경 이유, 비교, Review/Approve/Publish/Retire
- Audit 연결: `ARCH-20` provenance 게이트와 연계

### MVP API 예시

```
GET    /problems/{problemId}                    # 현재 Published version
GET    /problems/{problemId}/versions             # 버전 이력
GET    /problems/{problemId}/versions/{versionId} # 특정 버전
POST   /problems/{problemId}/versions             # 새 버전 생성
GET    /problems/{problemId}/diff?from=v4&to=v7   # Diff
POST   /versions/{versionId}/publish              # Publish (with validation)
```

---

## 13. 2단계 확장 범위

MVP 다음 단계에서 추가.

- **Dependency Graph**: `VersionDependency` 테이블, Publish 시 dependency lock
- **Impact Analysis**: 버전 Publish 전 영향받는 항목(Learning Paths, Assessments, Concept Nodes, Student Assignments) 계산
- **Release Snapshot**: `Release`, `ReleaseItem` 테이블
- **Schema Version 분리**: Entity Version과 Schema Version 명시적 분리
- **Prompt Version**: `PromptTemplate` Entity + Version
- **AI Policy Version**: `TutorPolicy`, `AssessmentPolicy`, `RecommendationPolicy` Version
- **Model Configuration Version**: 논리적 `ModelProfile` + 실제 provider/model_revision 매핑
- **Dataset Version**: AI 평가/학습용 데이터셋 버전
- **Vector Store / RAG Version**: `vector_index_version`, `embedding_model_version`, `chunking_policy_version`
- **Graph Diff**: Added/Removed/Modified Node & Edge
- **Semantic/Math Diff**: Text Diff + AST Diff + SymPy equivalence

---

## 14. 피해야 할 설계

1. 모든 객체에 `version` 숫자 하나만 추가 (`problem.version = 3`)
2. 기존 Published row를 `UPDATE`로 덮어쓰기
3. 코드 Git으로 교육 콘텐츠까지 관리
4. Version과 Revision을 동일시
5. Node만 버전 관리하고 Edge는 무시
6. AI Prompt/Policy를 코드에만 저장
7. 현재 최신 Entity만 Learning Event에 저장
8. Unified `Entity` 슈퍼테이블 즉시 도입 (WhyMath 7계층 정신과 충돌)

---

## 15. 연결 모듈

```
011_1 Entity ID 정책
       ↓
44     Version Management
       ↓
205    공통 메타데이터
       ↓
42     Source / Copyright (ARCH-20)
       ↓
45     QA
       ↓
43     CMS
       ↓
90     Audit
       ↓
204    Education Event
       ↓
206    Resource Registry
```

특히 `011_1` ID 정책과 `44` 버전 관리 정책은 한 쌍으로 설계한다.

---

## 16. 후속 태스크

1. **S1-16 완료**: `Problem/PublicProblem`에 `schema_version` 추가 (진행 중).
2. **Content Version 분리**: `Problem`에 `content_version_id` 추가, `ProblemVersion` 스키마/ORM/마이그레이션.
3. **Concept Version**: `ConceptVersion` 테이블 및 `concept_id` 기반 버전 계약.
4. **Release Snapshot**: `Release`, `ReleaseItem` 테이블 설계.
5. **VersionContext**: 학습 이벤트에 고정되는 런타임 컨텍스트 모델.
6. **Publish Gate**: Draft → Publish 검증 파이프라인. — [구현 2026-09-29 · EOS-50] 전이표
   `schema/version_lifecycle.py`(데이터 선언 · `IN_QA` 상태 추가) · 검증 파이프라인·전이 실행·
   Rollback `l3/publish_gate.py` · 게이트 기록 좌석 `concept_version.qa`(리비전 `9d3e7b1c5a20`).
   기존 `review_status`·PB-03 노출 계약과는 **다른 축**이며 경계 5항은
   `docs/reviews/eos50_publish_gate_axis_judgment_2026-09-29.md`. 현재 게이트 검사는 스키마·
   content_hash·거버넌스·QA 기록 결속까지이고, §9의 Source·License·Math·Graph·AI Validation은
   개념 payload에 볼 대상이 없어 포함하지 않았다(문항 버전 ARCH-31이 소비). 운영 API·CLI는 미구현.
