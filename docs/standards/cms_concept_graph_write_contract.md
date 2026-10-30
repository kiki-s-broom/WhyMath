# CMS 개념 그래프 쓰기 계약 (P3-26)

> **정본 문서.** 관리자 CMS가 개념을 **새로 만들고**, 선수 관계(엣지)를 **쓰고**, 개념을 **지울** 때의 규칙을 정한다.
> 코드 어휘는 `whymath_backend/db/cms_edit_marker.py`·`api/_concept_graph_rules.py`·`l3/publish_gate.py`,
> 집행 증거는 §7의 테스트다. 편집(수정)이 적재를 이기는 문제는 별도 계약 `cms_edit_vs_loader_contract.md`(P3-25)다.

- 태스크: `P3-26-cms-concept-create-delete-edge-write` · 선행 `P3-12-cms-minimal-screens`(done) · 출처 `docs/reviews/p3_12_cms_12_survey_2026-10-08.md` §6
- 판정 기준: 이 브랜치의 분기 커밋 위 작업분(미머지 — 병합 전에는 main에 이 계약이 없다)

## 1. 문제

P3-12는 개념 **조회·수정(새 초안)·스킬 연결**을 열었고 다음 셋을 의도적으로 열지 않았다.

| 열지 않은 것 | 왜 위험했나 |
|---|---|
| 신규 개념 생성 | `concept` 테이블에는 숨김 상태 컬럼이 없다 — **행이 생기는 즉시 학생 경로가 읽는다.** 검수 없이 생기는 길이 된다 |
| 관계(엣지) 쓰기 | 정본이 `graph.json`이라 DB를 고치면 **다음 적재가 덮어쓴다.** 그리고 선수 관계는 DAG여야 한다(순환 = 학습 경로 구성 불가) |
| 개념 삭제 | 발행본이 있는 개념, 적재가 되살리는 개념, 다른 데이터가 쓰는 개념을 지울 수 있다 |

## 2. 결정 ① — 원천 정본: **행 단위로 갈린다**

"graph.json이 정본인가, DB가 정본인가"는 둘 중 하나로 고르면 반드시 한쪽이 거짓이 된다. 파일만 정본이면 CMS가
만든 행은 영원히 비정본이고, DB만 정본이면 파일 적재가 의미를 잃는다. 실측한 사실 두 개가 답을 정한다.

1. **적재기는 `INSERT … ON CONFLICT DO UPDATE`뿐이고 삭제를 하지 않는다**(4종: `atom_backend_concept`·`atom_backend_edge`·
   `backend_concept`·`backend_edge`). 파일에 없는 행은 적재가 건드리지 않는다.
2. 따라서 충돌은 **같은 키(개념 코드·`(선수,후행,유형)`)가 파일과 CMS 양쪽에 있을 때만** 생긴다.

그래서 정본은 **행이 어디서 왔는가**로 정한다. 소유 표지는 P3-25와 같은 컬럼 `cms_edited_at`을 `concept`·`concept_edge`에 둔다.

| 행 | 표지 | 정본 | CMS가 지울 수 있나 | 적재가 덮어쓸 수 있나 |
|---|---|---|---|---|
| graph.json에서 온 개념·관계 (대다수) | `NULL` | **파일** | ✗ (`file_owned` 409 — 지워도 다음 적재가 되살린다) | ✓ |
| CMS가 만든 개념·관계 | 시각 | **DB** | ✓ (규칙 §4 충족 시) | ✗ (건너뛰고 충돌로 보고) |

- 표지가 있는 행에 같은 키의 파일 레코드가 오면 적재는 **건너뛰고** `CMS 편집 보호로 건너뜀: N건 […]`을 낸다.
  `--overwrite-cms-edits`가 덮어쓰고 표지를 비운다(P3-25와 같은 유일한 해제 경로 — 이후 파일이 다시 소유).
- 마이그레이션은 **`server_default`도 백필도 두지 않는다.** 기본값을 달면 PG가 기존 행 전체를 마이그레이션 시각으로 채워
  "전 행을 CMS가 만들었다"는 날조가 되고, 삭제·적재 보호가 거꾸로 작동한다.

## 3. 결정 ② — 신규 개념은 **버전 워크플로우만** 경유한다

요구: 살아있는 `concept` 행을 직접 만들지 않는다. 막힌 곳: 초안(`concept_version`)이 `concept.code`를 **FK로 참조**해 행이
없으면 초안 자체를 못 만든다. (2026-10-12 사용자 결정: **FK를 풀고, 발행하는 순간 게이트가 행을 만든다.**)

```
POST /concept-proposals  ──▶ concept_version v1 (DRAFT, change_type=cms_create)   ※ concept 행 없음
        │ 제출 → 검토 통과 → 승인   (기존 POST /versions/{id}/transitions · 행 없이 전이 가능)
        ▼
  발행(publish)  ──▶ publish_gate가 concept 행을 만든다 (cms_edited_at 채움 · 포인터 설정)   ← 행이 생기는 유일한 순간
```

- 개념 행을 만드는 곳은 `l3/publish_gate.py::_materialize_concept` **하나**다(적재기 4종은 파일 행의 upsert). 새 모듈이
  `Concept`를 만들면 AST 동결 E1이 RED다.
- **FK를 푼 자리를 DB 트리거 2종이 대신 지킨다**(마이그레이션 `a8c4e1f7b3d9`, 둘 다 `SET search_path` 하드닝):
  ① `PUBLISHED` 판은 살아있는 `concept` 행이 있어야 쓸 수 있다 ② 발행본이 있는 개념 행은 지울 수 없다.
  서버 검사가 유일한 방어선이 아니다 — 서버를 거치지 않는 직접 SQL도 막힌다(실 DB 주입으로 확인, §7).
- **코드는 영구 예약된다**: 판 이력이 남은 코드는 개념 행이 지워져도 다른 제안이 재사용할 수 없다(옛 판이 가리키는 코드를
  다른 개념이 쓰면 이력이 거짓이 된다).
- 심사 중 같은 코드를 graph.json 적재가 선점하면 발행은 `concept_code_free` 게이트 실패로 거부된다(적재 소유 개념을 덮지 않는다).
- **기존 개념의 수정 판은 여전히 개념 행을 바꾸지 않는다** — 서빙 경로가 `concept_version`을 읽지 않는 상태(P3-12 F2·B5)는
  이 태스크가 바꾸지 않았다. 발행으로 행이 *생기는* 것은 신규 개념뿐이다.
- 직접 생성 경로 `POST /v1/concepts`는 **폐지(410)**했다 — 남겨 두면 위 모든 것을 우회한다. 인증·권한은 먼저 검사되므로
  권한 없는 호출자는 410이 아니라 401/403을 본다.

## 4. 결정 ③ — 개념 삭제

`DELETE /v1/admin/cms/concepts/{id}`(그리고 같은 규칙을 쓰는 기존 `DELETE /v1/concepts/{id}`)는 아래를 **앞에서부터** 판정한다.

| 순서 | 조건 | 거부 코드 |
|---|---|---|
| 1 | 표지 없음(graph.json 소유) | `file_owned` |
| 2 | 발행 포인터가 있거나 `PUBLISHED` 판이 하나라도 있다 (포인터만 보지 않는다) | `has_published_version` |
| 3 | 이 개념에 연결된 관계가 있다 | `has_edges` |
| 4 | 이 개념을 부모로 삼는 하위 개념이 있다 | `has_children` |
| — | 그 밖의 참조(학습 기록·문항 연결 등) | DB 외래키 → `referenced` 409 |

허용되는 것은 **CMS가 만들었고, 폐기(deprecate)돼 발행본이 없고, 더는 참조되지 않는 개념**뿐이다. 판 이력은 지우지 않는다.

## 5. 결정 ④ — 선수 관계 쓰기와 비순환(DAG)

- 쓸 수 있는 유형은 **`PREREQUISITE`뿐**이다(다른 유형은 `edge_type_not_writable` 422 — 구축 플레이북은 관계 유형을 5~8개로
  묶고 `related_to`류를 traversal에 쓰지 말라고 한다. 나머지는 쓰기 설계가 없다).
- 추가 요청 `A→B`("A를 알아야 B를 안다")는 **`B`에서 선수 방향으로 `A`에 닿으면 순환**이다(Reachability Check). 순환이면
  422 `prerequisite_cycle`이고 응답에 **순환 경로를 개념 코드로** 싣는다(`[C, A, B, C]` — 어디를 끊을지 보이게). 행·감사·commit은 0이다.
- **검사와 쓰기 사이 틈을 어드바이저리 잠금으로 닫는다.** 각각은 비순환인 두 요청(`a→b`, `b→a`)이 동시에 오면 둘 다
  "검사 시점엔 비순환"이라 통과해 순환이 DB에 들어간다. 모든 선수 엣지 쓰기는 같은 키
  (`PREREQUISITE_GRAPH_LOCK_KEY`)의 트랜잭션 잠금 안에서 검사한다 — **CMS와 적재 CLI가 같은 키를 쓴다.**
- **적재도 DB의 CMS 관계와 합쳐 본다.** 기존 적재 검사(`_find_prerequisite_cycle_in_records`)는 파일 엣지만 본다. CMS가 `A→B`를
  만든 뒤 파일이 `B→A`를 가져오면 각각은 비순환이지만 합치면 순환이다. 엣지 적재기는 쓰기 전에 잠금을 잡고 **DB의 모든
  선수 엣지 ∪ 이번 적재분**의 순환을 찾아 `PrerequisiteCycleError`로 거부한다(트랜잭션 롤백 — 부분 적재 없음).
- 관계 삭제는 **CMS가 만든 관계만**(`file_owned` 409 — 파일 관계는 파일에서 고쳐야 한다).

## 6. 권한

`schema/cms_access.py`의 권한 4종(조회·편집·검수·배포)에 새 이름 없이 **기존 권한을 재사용**한다.

| 동작 | 필요 권한 | 이유 |
|---|---|---|
| 제안 목록 | 조회 | |
| 신규 개념 제안·제안 수정 | **편집** | 초안 단계 — 검수·발행이 뒤따른다 |
| 관계 추가·삭제, 개념 삭제 | **배포**(`GRAPH_WRITE_CAPABILITY`) | **초안 단계가 없는 살아있는 쓰기**다. 쓰는 순간 학습 경로 추천이 읽는 데이터가 바뀐다 — 편집 권한이 아니라 살아있는 데이터를 바꿀 수 있는 역할만 쓴다 |

권한은 DB 접근 **전에** 서버가 검사한다(거부는 부작용 0). 화면에서 버튼을 숨기는 것은 보안이 아니다.

## 7. 집행 지점 (정본화와 별항)

| 계약 | 집행 코드 | 이를 고정하는 장치 |
|---|---|---|
| 개념 행은 발행 게이트만 만든다 | `l3/publish_gate.py::apply_transition`·`_materialize_concept` | `test_cms_graph_write_enforcement.py` E1 (AST — 허용 목록 밖 `Concept(...)` 생성 RED) |
| 관계는 잠금 → 순환 검사 → 쓰기 | `api/admin_cms_graph.py::create_edge` | E3 (함수 안 호출 순서 AST) + 주입 |
| 적재기 4종은 소유 가드·잠금·DB 인지 순환 검사를 지난다 | 각 `populate` | E4 + `test_cms_edit_marker.py` 집행 스캔 |
| 쓰기 라우트는 DB 접근 전에 권한 검사 | `_require(...)` | E5 + 권한 매트릭스 30칸 (`test_admin_cms_graph.py`) |
| FK 대신 트리거 2종 | 마이그레이션 `a8c4e1f7b3d9` | 실 PG: `test_admin_cms_graph_integration.py::TestDatabaseTriggers…` |
| 동시 요청이 합쳐 순환을 못 만든다 | `lock_prerequisite_graph` | 실 PG 동시 2요청 테스트(잠금을 빼면 RED) |
| 실 DB 종단(403 포함) | 전체 | `test_admin_cms_graph_integration.py` — **CI `backend-migrations` 잡이 `pytest -m integration`으로 실행** |

## 8. 한계 (정직 고지)

1. **수정 판은 개념 행을 바꾸지 않는다.** 이미 있는 개념을 발행해도 학생이 보는 개념 행은 그대로다(F2). 이 태스크는 *신규* 개념의
   행 생성만 연다. 서빙 연결은 판정 문서 B5에 따라 별도 재판정이 필요하다.
2. **적재 소유 개념은 CMS가 지우지 못한다.** 파일에서 제거해야 한다. CMS에서 "이 개념을 없애고 싶다"는 요구는 이 설계가 풀지 않는다
   (되살아나는 것을 막으려면 파일 쪽 폐기 표시가 필요 — 별도 설계).
3. **관계 유형은 `PREREQUISITE` 하나다.** 다른 유형의 쓰기는 열지 않았다.
4. **이전에 `POST /v1/concepts`로 만든 개념은 표지가 없다** → 적재 소유로 취급돼 CMS가 지울 수 없다. 운영 DB에 그런 행이 있는지는
   확인하지 못했다(이 환경은 prod에 접근하지 않는다).
5. **`downgrade`는 고아 판이 있으면 실패한다**(FK 복원). 신규 개념 제안이 남은 DB를 내리려면 먼저 정리해야 한다 — 이력을 몰래 지우지 않기 위한 의도다.
6. **서버 검사 ↔ 화면**: 화면은 서버가 내린 `can_write_graph`·`delete_blocked_reason`·`cms_owned`를 그대로 그린다(규칙 복제 없음).
7. **무결성 게이트(`integrity_violations_gate`)에 새 kind를 더하지 않았다** — "PUBLISHED 판은 개념 행이 있다"는 DB 트리거가 쓰기 시점에 막으므로
   사후 감사가 중복이다. 트리거를 끈 DB를 감사하려면 별도 kind가 필요하다.
