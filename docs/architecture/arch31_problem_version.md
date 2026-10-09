# ARCH-31 — Problem 버전 분리 (`problem_version`)

> **판정 기준**: 작업 브랜치 `claude/awesome-allen-qmy3yi` (main `ec1f9dc7` 위). 근거 코드는 전부 이 트리에서 실측.
> **결정 출처**: `docs/standards/eos_identity_layer_011_1_decision.md` 3번 표 4행 — "Content ID ≠ Content Version ID ✅ 채택, 별도 태스크로 구현".
> **좌석 판정**: `canonical_entity_model_v1.md` §3-D "판정 2026-09-06"(게이트 `G-eos49-content-version-seat` D안).
> **설계 정본**: `44_eos_version_management.md` §6.1(Hybrid)·§6.2(VersionHeader)·§6.3(도메인별 버전 테이블)·§6.4(Entity의 현재 버전 포인터)·§7(Lifecycle).

## 1. 핵심 결론 — 범용 `ContentVersion`은 만들지 않는다

원 태스크 제목은 "Content Version 분리: `Problem.content_version_id` + `ContentVersion` 모델"이었다. 게이트 판정(D안)과 태스크 승계 대조표가 이를 아래처럼 **읽는다**:

| 원문 | 이 PR에서 읽는 형태 | 이유 |
|---|---|---|
| `Problem.content_version_id` nullable FK | **`Problem.problem_version_id`** nullable FK → `problem_version.version_id` | 범용 `content_version`은 예약 이름(`RESERVED_ABSENT_TABLE_NAMES`)이라 생성 시 RED. 대상은 도메인 버전 테이블이다 |
| `ContentVersion` Pydantic·ORM | **ORM = `ProblemVersion` 하나**(Problem 좌석 편입), **Pydantic = `VersionHeader` 공통 계약 재사용** | 슈퍼테이블은 `011_1` 보류 + 44 §14-8 금기. 공통 축은 헤더 *계약*으로만 공유(§6.1 Hybrid) |

결과: 엔티티 19종 불변, `ContentVersion` 좌석은 비어 있다. `problem_version`은 Problem 좌석의 3번째 테이블(`problem` · `problem_step` · `problem_version`)이며, `concept_version`이 Concept 좌석의 4번째 테이블인 선례(EOS-49)와 동형이다.

## 2. `identity_id`와의 관계 — 직교하는 두 축

두 컬럼은 이름이 비슷해 보이지만 **다른 질문에 답한다**.

| | `problem.identity_id` (S4-18) | `problem_version` (ARCH-31) |
|---|---|---|
| 묻는 것 | "이 문항과 *같은 문제의 다른 표현*은?" | "이 *한 문항*의 지난 판은?" |
| 방향 | **수평** — 개체 사이 | **수직** — 한 개체의 시간 |
| 키 | `identity_id` 공유 (개체마다 `problem_id`가 다르다) | `problem_id` 동일, `version_no`만 증가 |
| 예 | 원본 + rephrase 3건이 같은 `identity_id` | `problem_id=P`의 v1(초안)·v2(해설 정정)·v3(발행) |
| FK 여부 | FK 아님(계열의 공유값) | `problem_version.problem_id` → `problem.problem_id` FK |

결론 세 가지:

1. **`identity_id`는 버전 스냅숏에 복제하지 않는다.** 계열 소속의 정본은 `problem.identity_id` 하나다. payload에 박으면 두 곳이 갈라진다(판이 쌓이는 동안 계열이 바뀌면 어느 쪽이 맞는가).
2. **rephrase는 새 버전이 아니라 새 개체다.** rephrase는 `problem_id`가 새로 생기고 `identity_id`로만 원본과 묶인다. 한 문항의 오타를 고치는 것은 새 `problem_version`(같은 `problem_id`)이다. 둘을 섞지 않는다 — 섞으면 "변형 계열 전체의 판"이라는 정의 불가능한 개념이 생긴다.
3. **`problem_id`는 개체마다 불변**이라는 S4-18 규약이 그대로 유지된다. 이 PR은 `problem_id`의 의미를 바꾸지 않는다 — 판이 바뀌어도 `problem_id`는 그대로이고 바뀌는 것은 `problem.problem_version_id` 포인터와 `problem_version` 행이다.

식별자 4종의 역할(011_1 Content ID ≠ Content Version ID의 구현 대응):

| 011_1 도메인 | 컬럼 | 의미 |
|---|---|---|
| Content ID | `problem.problem_id` | 한 문항 개체 (불변) |
| Content ID (계열) | `problem.identity_id` | 같은 문제의 다른 표현 묶음 |
| Content ID (외부) | `problem.external_id` | 외부 원본 식별자 (평가원/EBS) |
| **Version ID** | **`problem_version.version_id`** | **한 문항의 한 판** (이 PR) |

## 3. 스키마

### `problem_version` (리비전 `c5e1f9a3b7d2`)

44 §6.2 VersionHeader를 **평탄화**해 컬럼과 1:1로 둔다(`concept_version`과 같은 이유 — `from_schema`/`to_schema` 교집합 필터가 컬럼명 대응에 의존한다). 엔티티 FK만 다르다: Concept는 의미 ID(`code`)를, Problem은 **UUID PK**(`problem_id`)를 참조한다 — Problem의 의미 식별자(`slug`·`external_id`)는 nullable이라 FK 대상이 될 수 없고 44 §6.3이 `problem_id: UUID`로 못 박았다.

- PK `version_id` UUID, `UNIQUE(problem_id, version_no)`, 인덱스 `(problem_id, status)` ("현재 발행 판 찾기").
- `status`: PG enum `problem_version_status_enum` = `VersionStatus` 7종 전량(IN_QA 포함). concept 쪽이 6종으로 시작해 나중에 IN_QA를 끼워 넣은 이력(`9d3e7b1c5a20`)을 반복하지 않으려 처음부터 7종이다.
- `change`·`source`·`governance`·`integrity`·`qa`·`payload` JSONB(`none_as_null=True`). `qa`는 게이트 통과 기록 좌석(nullable, 기록 없음=NULL).
- `previous_version_id` self-FK(버전 체인).

### `problem.problem_version_id`

nullable UUID FK → `problem_version.version_id`. 44 §6.4의 `current_published_version_id`를 Problem 축에서 부르는 이름이다(승계 대조표 ①이 컬럼명을 이렇게 확정). **백필 없음** — NULL=버전 미부여. 기존 행에 판을 날조해 넣지 않는다(DP-03 `event_uuid`·ARCH-32 `source_id` 규약). `concept.current_published_version_id`와 이름이 다른 것은 의도가 아니라 승계 대조표의 문면 때문이다 — 통일은 별건(§6).

`problem` ↔ `problem_version`은 **상호 FK**다. 마이그레이션은 생성 순서(`problem_version` → `problem` 컬럼)와 역순 제거로 순환 없이 왕복한다.

### payload (`ProblemVersionPayload`)

문항의 **내용을 정의하는** 필드만 스냅숏한다: 출처·과목·교육과정 좌표·형식·본문 4종(`question_text`·`choices`·`answer`·`answer_explanation`) + 44 §6.3의 problem-specific 메타(`stem_hash`·`answer_hash`·`difficulty_at_publish`). 난이도 5축·검수/격리 상태·임베딩·`distractor_map`은 각자의 컬럼/테이블이 정본이라 복제하지 않는다. 확장은 `schema_version` 상향으로 한다.

## 4. 불변식과 그 집행 지점 (정본화 ≠ 집행)

| 불변식 | 집행 지점 | 검증 |
|---|---|---|
| PUBLISHED 행의 `payload`는 UPDATE 불가 | DB BEFORE UPDATE 트리거 `trg_problem_version_immutability_guard` | `tests/backend/db/test_problem_version_migration_integration.py` (실 PG, 실패 주입 RED/GREEN 4면) |
| PUBLISHED → DRAFT 금지 | 같은 트리거 | 같은 테스트 |
| 평가원/EBS/교과서 출처는 **버전 payload에도** 본문 불가 | `ProblemVersionPayload` validator — 출처 집합은 `METADATA_ONLY_SOURCES` 한 벌 재사용 | `tests/backend/schema/test_problem_version.py` (버전 경로가 저작권 우회로가 되지 않음) |
| `problem_version_id`는 공개 응답에 나가지 않음 | `PUBLIC_HIDDEN_OPS_FIELDS` 등재(키 부재가 계약) | `tests/backend/api/test_problems_public_projection.py::test_classification_is_total` |
| 공통 헤더 계약 공유 (도메인마다 제각각 버전 시스템 금지) | `VersionHeader` 필드 ⊂ `ProblemVersion`·`ConceptVersion` | `tests/backend/schema/test_problem_version.py` 헤더 정합 |
| 엔티티 19종 불변·`ContentVersion` 좌석 부재 | 좌석 상수 + 정본 §2-A | `tests/backend/db/test_canonical_entity_model_freeze.py` |

## 5. 이 PR이 하지 않는 것 (정직 기술)

- **운영 writer 없음.** `problem_version`에 행을 쓰는 운영 코드가 아직 없다. 전이 실행(게이트)은 `l3/publish_gate.py`가 `ConceptVersion`에 대해서만 갖고 있고, 문항 발행 경로는 별도 태스크다. 그래서 불변성은 DB 트리거(최후 방어)까지만 집행되며 *전이 게이트 경유 강제*는 이 PR 범위 밖이다. 게이트가 생기면 그 모듈이 이 ORM의 유일한 쓰기 자리가 되어야 한다(EOS-50 AST 동결과 동형).
- **`problem_attempt` 버전 고정은 `EOS-47` 소관.** 이 PR로 EOS-47의 선행(ARCH-31)이 풀린다. attempt가 어느 판을 풀었는지의 기록·재현성 테스트는 거기서 한다.
- **기존 `problem` 행 백필 없음.** 판을 만드는 일(v1 스냅숏 생성)은 발행 경로의 책임이다.
- **`curriculum_version` 컬럼과 무관.** `problem.curriculum_version`(교육과정 개정 구분 enum)은 문항의 본질 속성이고 이 판 관리 축과 이름만 비슷하다 — 건드리지 않는다.

## 6. 후속 (이 PR이 소유하지 않는 것)

- 문항 발행 게이트 / 전이 writer — 미등재 시 등재 필요(EOS-47 이후 판단).
- `concept.current_published_version_id`(Concept)와 `problem.problem_version_id`(Problem)의 **컬럼명 통일**은 승계 대조표가 이름을 고정해 이 PR에서 바꾸지 않았다. 통일 여부는 사람이 결정할 사안이다.
