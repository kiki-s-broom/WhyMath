# EOS-50 Publish Gate — 기존 검수 축과의 관계 판정 (acceptance ②)

판정 기준: main 120bd7c5

- 태스크: `EOS-50-publish-gate-pipeline` (P3-11 흡수분 ⑨~⑫ 포함)
- 설계 정본: `docs/architecture/44_eos_version_management.md` §7(Lifecycle)·§9(Publish Gate & QA 연계)·§12(MVP)·§16-6
- 선행: `EOS-49-concept-version-contract`(done, PR #1156) — `concept_version` 테이블·`VersionStatus` 어휘·PUBLISHED 불변성 트리거
- 이 문서가 답하는 질문: **새 Publish Gate가 기존 `review_status`(`ReviewStatus`) · PB-03 노출 계약(`candidate_pool_conditions` 등)과 같은 축인가, 다른 축인가.** 같은 축이면 재사용하고, 다른 축이면 경계를 적어 판정이 둘로 갈라지지 않게 한다.

코드보다 이 판정을 먼저 적었다. 아래 §4의 경계 규칙은 코드 동결 테스트가 기계로 집행한다(§5).

---

## 1. 비교 대상 — 저장소에 이미 있는 "승인·노출" 축 (main 120bd7c5 실측)

| 축 | 붙는 엔티티 | 묻는 질문 | 누가 값을 쓰는가 | 값이 바뀌는 방식 | 소비처(서빙 경로) |
|---|---|---|---|---|---|
| **A. `problem.review_status`** (`ReviewStatus`: pending·approved·rejected·quarantined) — `schema/enums.py:703-737`, `db/models/problem.py:262` | `problem` 한 행(엔티티) | "이 **문항**을 학생에게 내보내도 되는가" — 측정 기반 운영 검수 판정 | `harness/problem_corpus_review_status_backfill.py`가 `corpus_audit_eval`의 Wilson 판정값만 각인(사람 입력 경로 0). 격리는 관리자 PATCH(`api/problems.py`) | 같은 행을 제자리 갱신(mutable) | `l2/next_problem_selection.py:137-152` `candidate_pool_conditions()` 축②, `l6/_shared.py:171` `is_review_cleared`, `api/problems.py` 격리 배제 |
| **B. PB-03 축① 저작권 노출** — `candidate_pool_conditions()` 축①(`METADATA_ONLY_SOURCES`), `l6/_shared.py:147` `is_exposable` | `problem` 한 행 | "이 문항의 **출처**가 본문 노출을 허락하는가" — 법적 판정 | 상수(출처 등급) — 판정 입력은 `source_type` | 출처가 바뀔 때만 | 위와 같은 서빙 경로(축②와 **독립 if**) |
| **C. `concept_node.review_status`** (plain text 'reviewed'/'pending') — `db/models/concept_node.py:93-96` | 개념 그래프 **원천 노드**(graph.json 투영) | "이 개념 노드의 **원천 데이터**가 전문가 검수를 거쳤는가" — 데이터 큐레이션 표지 | 적재기(`l1/concept_graph/populate.py`)가 graph.json 값을 그대로 투영 | 재적재 시 덮어씀 | `l1/concept_graph/retrieval.py:96` `reviewed_only` 검색 필터 |
| **D. (신규) `concept_version.status` + Publish Gate** — `schema/version_header.py` `VersionStatus`, `schema/version_lifecycle.py` 전이표, `l3/publish_gate.py` | `concept_version` 한 행(**불변 스냅숏**) | "이 **판(version)**이 발행해도 되는 완결 스냅숏인가" — 스키마 유효·내용 해시 고정·거버넌스(작성·검토·승인자) 완결 | `l3/publish_gate.py`의 서비스 함수만(§5 AST 동결) | 전이표에 선언된 전이로만. PUBLISHED 행의 payload는 DB 트리거가 불변 강제(EOS-49) | **없음** — 서빙 경로 중 `concept_version`을 읽는 곳은 0건(`grep -rn "concept_version" src/backend/whymath_backend --include=*.py` 실측: ORM·스키마·무결성 게이트 ⑦·어드민 레지스트리 경로 문자열뿐) |

## 2. 판정 — **다른 축이다** (A·B·C 셋 모두와)

근거 네 가지. 하나라도 겹치면 같은 축으로 판정했을 것이다.

1. **엔티티가 겹치지 않는다.** A·B는 `problem` 행, C는 `concept_node` 행, D는 `concept_version` 행이다. D는 `problem`에 아무 상태도 쓰지 않고, A·B는 `concept_version`을 읽지 않는다. 현재 저장소에 `problem_version` 테이블은 없다(ARCH-31 미착수).
2. **질문이 다르다.** A는 "학생에게 내보내도 되는가"(노출 판정), B는 "법적으로 보여 줘도 되는가", C는 "원천 데이터가 검수됐는가"다. D는 "이 스냅숏이 **형식적으로 완결되고 내용이 고정됐는가**"다. D를 통과해도 학생 노출이 일어나지 않는다 — D의 결과를 읽는 서빙 경로가 없기 때문이다.
3. **값을 만드는 주체가 다르다.** A는 *사람 입력 경로 0*의 측정값이다(`promotion_gate` 노드 — `pipeline.yaml`). D의 `APPROVED`는 승인자 **신원**(`governance.approved_by`)을 기록하는 거버넌스 행위다. 두 "approved"는 글자만 같고 의미가 다르다. 합치면 "측정으로 통과한 문항"과 "누군가 서명한 판"이 같은 글자가 된다 — EOS-71이 `rejected`와 `quarantined`를 합치지 않은 것과 같은 이유다.
4. **가변성이 다르다.** A·C는 같은 행을 제자리 갱신한다. D는 불변 스냅숏의 상태 전이이며, 수정은 새 버전(vN+1)으로만 한다(44 §1 원칙 2·3).

그래서 **재사용하지 않는다.** A의 어휘(`ReviewStatus`)를 D에 빌려 쓰면 위 3번의 충돌이 코드에 들어온다. D는 EOS-49가 이미 만든 `VersionStatus`를 확장한다(§3).

## 3. EOS-49 상태 머신의 확장 — 두 번째 사본을 만들지 않았다

EOS-49가 남긴 것은 **어휘**(`VersionStatus` 6종)와 **DB 트리거 2규칙**(PUBLISHED payload 불변·PUBLISHED→DRAFT 금지)이었다. 전이 규칙 자체는 `VersionStatus` docstring의 산문에만 있었다(`schema/version_header.py` "전이 규칙 자체의 강제는 도메인별 ORM/DB 트리거 소관"). 이 태스크는 그 산문을 **데이터 한 장**으로 옮겼다.

- 전이표 = `src/backend/whymath_backend/schema/version_lifecycle.py`의 `LIFECYCLE_TRANSITIONS` (단일 튜플). 서비스는 이 표를 조회만 하고 상태를 스스로 고르지 않는다.
- 어휘 = `schema/version_header.py`의 `VersionStatus`(상태) · `TransitionAction`(전이 이름) · `GateKind`(게이트 종류). 어휘는 헤더, 규칙은 표 — 한 파일이 다른 파일을 복제하지 않는다.
- `VersionStatus.IN_QA` 1종 추가 — P3-11 ⑨가 요구한 "Review → QA → Approved" 순서를 상태로 표현하기 위해서다. 44 §9의 "각 버전은 QA 결과를 연결한다"(`qa_status`·`qa_run_id`·`validator_bundle_version`)의 좌석으로 `concept_version.qa` JSONB 컬럼도 함께 추가했다(마이그레이션 `9d3e7b1c5a20`).
- DB 트리거와 표의 정합: 트리거가 막는 PUBLISHED→DRAFT 간선은 표에 없다. 이 정합은 테스트가 동결한다(`tests/backend/schema/test_version_lifecycle.py`).

전이표(요약 — 정본은 코드):

| 전이 | 출발 → 도착 | 게이트 | 기록 | 직접 호출 |
|---|---|---|---|---|
| `submit` | DRAFT → IN_REVIEW | — | — | 가능 |
| `request_changes` | IN_REVIEW → DRAFT | — | — | 가능 |
| `pass_review` | IN_REVIEW → IN_QA | — | `reviewed_by` | 가능 |
| `fail_qa` | IN_QA → DRAFT | — | — | 가능 |
| `approve` | IN_QA → APPROVED | **QA** | `approved_by` | 가능 |
| `publish` | APPROVED → PUBLISHED | **PUBLISH** | `published_at` | 가능 |
| `deprecate` | PUBLISHED → DEPRECATED | — | — | 가능 |
| `retire` | DEPRECATED → RETIRED | — | — | 가능 |
| `supersede` | PUBLISHED → DEPRECATED | — | — | publish의 부수 효과로만 |
| `rollback` | PUBLISHED → RETIRED | — | — | rollback 복합 연산으로만 |
| `restore` | DEPRECATED → PUBLISHED | **RESTORE** | — | rollback 복합 연산으로만 |

"미정의 전이"는 이 표에 (전이 이름, 출발 상태) 쌍이 없는 모든 요청이다. `UndefinedTransitionError`로 거부된다.

**Rollback의 의미**: 현재 발행본을 RETIRED로 내리고(결함 판정), 그보다 앞선 판 중 발행된 적이 있고 지금 DEPRECATED인 가장 최근 판을 PUBLISHED로 되돌린 뒤 발행 포인터를 그 판으로 옮긴다. 새 판을 만들지 않는다 — 복원되는 것은 **그 판 자체**다. 복원 전에 RESTORE 게이트가 payload 해시를 다시 계산해 승인 시점 각인과 비교한다. DEPRECATED 판의 payload는 DB 트리거가 보호하지 않기 때문에(트리거는 PUBLISHED만 본다), 내려가 있는 동안 바뀌었다면 복원을 거부한다. 롤백으로 내린 판을 DEPRECATED가 아니라 RETIRED로 보내는 이유: DEPRECATED로 두면 다음 롤백이 방금 내린 결함 판을 "직전 발행본"으로 되살린다. §7 원 다이어그램에 없는 PUBLISHED→RETIRED 간선은 이 이유로 더했다(DB 트리거는 PUBLISHED→DRAFT만 막으므로 충돌 없음).

## 4. 경계 규칙 — 판정 이원화를 막는 5항

| # | 규칙 | 왜 |
|---|---|---|
| B1 | Publish Gate는 `ReviewStatus`·`review_status`를 **읽지도 쓰지도 않는다**. | D가 A의 값을 조건으로 쓰는 순간 A가 두 곳에서 해석된다. |
| B2 | 문항 노출 경로(`candidate_pool_conditions`·`is_exposable`·`is_review_cleared`·`api/problems.py` 격리 배제)는 `VersionStatus`·`concept_version`을 **읽지 않는다**. | 문항 노출의 정본은 A+B 두 축뿐이다. D가 끼어들면 "문항이 왜 안 나왔나"의 답이 셋이 된다. |
| B3 | `VersionStatus.APPROVED`와 `ReviewStatus.approved`는 **다른 개념**이다. 서로 변환하는 함수를 만들지 않는다. | §2 근거 3. |
| B4 | **ARCH-31(`ProblemVersion`)이 착지할 때** 문항 버전의 발행 게이트는 `review_status == approved`를 **검사 1항으로 소비**해야 하며, 문항 품질을 따로 판정하는 두 번째 "승인" 필드를 만들지 않는다. 그때 B1은 "문항 버전 게이트에 한해 A를 읽기 전용으로 소비"로 좁혀 개정한다. | 장래 이원화가 가장 쉽게 생기는 자리다. 지금 적어 둔다. |
| B5 | `concept_version`을 서빙 경로가 읽기 시작하면(= D가 학생 노출에 닿으면) 헌법 제8조에 따라 **이 판정을 다시 한다** — 그때는 D가 학생 노출 게이트가 되므로 L5(자동 차단) 집행 수준을 다시 따진다. | 현재 판정의 전제는 "D는 학생 노출이 아니다"이다. 전제가 바뀌면 판정도 바뀐다. |

## 5. 집행 지점 (acceptance ③ — 정본화와 별항)

**사실 먼저**: main 120bd7c5 기준으로 `concept_version`에 publish를 거는 **API·CLI는 0건**이다. §12의 `POST /versions/{versionId}/publish`는 미구현이다. 그래서 이 태스크는 **최소 진입점**을 서비스 함수로 두었다.

- 진입점: `src/backend/whymath_backend/l3/publish_gate.py`
  - `create_draft(session, …)` — 새 DRAFT 판 생성의 유일한 경로(`version_no`·`previous_version_id` 자동 결정)
  - `apply_transition(session, version_id, action, *, actor)` — 직접 호출 가능한 전이 8종. publish는 이전 발행본을 `supersede`하고 `concept.current_published_version_id`를 옮긴다.
  - `rollback(session, concept_code, *, actor)` — 현재 발행본 `rollback` + 직전 발행본 `restore`를 한 번에
- **지금 publish를 부르는 것**: 이 태스크의 테스트뿐이다(단위 + 실 PG 통합). 운영 코드에서 부르는 곳은 없다. 이것은 결함이 아니라 현재 상태이며, CMS 버전 API(§12)나 운영 CLI가 생기면 반드시 이 서비스를 경유해야 한다 — 아래 동결이 그것을 강제한다.
- 동결: `tests/backend/l3/test_publish_gate_enforcement.py` (AST 전수 스캔, 운영 패키지 전체)
  1. ORM `ConceptVersion` import는 `db/models/`의 정의·등록 파일과 `l3/publish_gate.py`에서만 허용
  2. `current_published_version_id`에 값을 쓰는 코드(속성 대입·키워드 인자·dict 키)는 `l3/publish_gate.py`에서만 허용
  3. `UPDATE/INSERT INTO/DELETE FROM concept_version` 및 `UPDATE concept … current_published_version_id` SQL 문자열 금지
  4. 경계 규칙 B1·B2의 기계 집행
  5. 스캐너 자신의 변별력: 위반 코드를 주입하면 RED, 대상 0건이면 RED(공허 통과 금지)
- 한계(명시): 동적 import·`getattr`·런타임 조립 SQL은 이 스캔이 보지 못한다. alembic 리비전과 테스트는 스캔 대상이 아니다(테스트는 상태를 일부러 주입해야 하므로).

## 6. 헌법 대조 (`constitution/CONSTITUTION.md` v1.0 · `rules.yaml` v1.0)

| 조문·규칙 | 이 작업에서의 적용 |
|---|---|
| 제4조 ①② · R1-01 (섬 노드 금지) | 새 게이트이므로 `pipeline.yaml`에 노드 `concept_version_publish`(needs: `concept_graph`)를 추가했고, 발행 포인터를 검사하는 `integrity_gate`의 선행에 넣었다. 문항 `publish` 노드와는 별개 노드다(R1-03의 필수 이름 `publish`는 건드리지 않음). |
| 제5조 ② (게이트 결과는 다른 게이트를 대체하지 않는다) | §4 B1·B2가 이 조문의 구체화다. D는 A·B·C 어느 것도 대체하지 않는다. |
| 제5조 ③ · R2-03 (판정자·일시·근거·우회 여부) | 게이트 기록 `GateRecord`가 `judged_by`·`judged_at`·`checks`+`content_hash`(근거)·`bypassed`를 필수 필드로 가진다. `bypassed`는 항상 `False`다 — 우회 경로가 없기 때문이며, 장래에 우회 경로를 만들려면 이 필드를 `True`로 남겨야 한다. |
| 제8조 (되돌릴 수 없는 결함은 L5) | D는 현재 학생 노출이 아니다(§1 D행 소비처 0). 그래도 게이트 미통과 발행은 예외로 **차단**한다(경고가 아님). B5가 재판정 조건이다. |
| 제9조 ② (게이트 우회 금지) | 우회 인자·플래그를 두지 않았다. `supersede`·`rollback`·`restore`는 직접 호출하면 거부된다. |

## 7. 범위 밖 (acceptance ④)

Impact Analysis·Dependency lock(§13, Phase 2)은 다루지 않는다. `VersionDependency` 테이블도 만들지 않았다. §9의 Source·License·Math·Graph·AI Validation 단계는 이 게이트의 검사 목록에 없다 — 개념 버전 payload(`ConceptVersionPayload`)에는 출처·수식·본문이 없어 그 검사들이 볼 대상이 없기 때문이다(저작권 축은 문항 쪽 `copyright` 노드가 소유한다). 문항 버전(ARCH-31)이 생기면 그쪽 게이트가 해당 단계를 소비해야 한다(B4).
