# CMS 편집 ↔ CLI 적재 덮어쓰기 계약 (P3-25)

> **정본 문서.** 관리자 CMS가 DB 행을 고친 뒤 `populate` CLI가 같은 행을 다시 적재할 때, 사람의 편집이
> 어떻게 되는지를 정한다. 코드 어휘는 `whymath_backend/db/cms_edit_marker.py`, 집행 증거는 §6의 테스트다.

- 판정 기준: 브랜치 `claude/nifty-dijkstra-omkcg1`의 분기 커밋 `594ce16b`(PB-21, #1557) 위 작업분 — **미머지**라 병합 전에는 이 계약이 main에 없다. 2절의 파일:줄은 이 분기 커밋 기준이다
- 태스크: `P3-25-cms-edit-vs-loader-contract` · 선행 `P3-12-cms-minimal-screens`(done) · 사후 대조표 `docs/reviews/p3_12_cms_12_survey_2026-10-08.md` §6

## 1. 문제

P3-12는 CMS 제자리 편집 UI를 열었지만 "편집이 다음 적재에 보존된다"는 것은 주장하지 않았다. 개념 외 CMS
리소스 대부분은 파일 정본(`data/corpus/*`)을 `populate` CLI가 키 충돌 upsert(`INSERT … ON CONFLICT … DO
UPDATE`)로 DB에 투영한 것이다. 그래서 **CMS 편집 → 같은 코퍼스를 다시 적재하면 편집이 코퍼스 값으로
되돌아간다.** 예외도 알림도 없다. 문항에서는 한 단계 더 나쁘다 — 사람이 **격리**한 문항의 `review_status`와
`quarantine_*`도 코퍼스 초기값으로 돌아가 격리된 문항이 되살아난다.

## 2. 실측 판정 — 리소스 7종별 적재 경로 (acceptance ①)

검색 방법: 모델·테이블 이름이 아니라 **역할**로 찾았다 — `on_conflict_do_update`·`session.merge`·`ORM 인스턴스 생성`을
`src/` 전체(`l1`·`l3`·`l4`·`whs`·`ops`·`harness`·`api`·`data-pipeline`)와 `scripts/`에서 훑고, 각 모델명으로 쓰는 호출처를
역추적했다. 아래 "0건"은 **이 방법으로 찾은 범위의 0건**이다.

| # | CMS 리소스 | CLI 적재 경로 (파일:줄은 변경 전 기준) | 같은 행을 덮어쓰는가 |
|---|---|---|---|
| 1 | 교육과정 판 `curriculum_version` | 쓰는 코드는 alembic 시드 한 곳(`...cur_10_curriculum_framework_version_.py:138`, `ON CONFLICT (version_id) DO NOTHING`). 앱·CLI 쓰기 0건 | **아니오** — 시드는 마이그레이션 때 1회이고 `DO NOTHING` |
| 2 | 문항 `problem` | `l1/problem_bank/populate.py:693` — `slug` 충돌 시 `problem_id`·`slug`·`created_at` 외 **전 컬럼** 갱신(검수·격리·발행 컬럼 포함) | **예** |
| 3 | 풀이 단계 `problem_step` | `l3/multi_solution.py:967`, `whs/path_promotion.py:486` — 둘 다 **단계 좌석이 빈 문제에만 insert**. upsert 없음 | **아니오** |
| 4 | 오개념 `misconception_catalog` | `l1/misconception/catalog_loader.py:190` — `mis_id` 충돌 시 PK 외 전 컬럼 갱신. atom 경로(`atom_catalog.py`)도 같은 로더에 위임 | **예** |
| 5 | 교수전략 `strategy_node` | `l1/strategy_graph/strategy_node_projection.py:156` — 이름·설명·`review_status`(→`ai_estimated`) 갱신 | **예** |
| 6 | 개념 설명 `concept_content` | `l1/concept_content/projection.py:209` — 설명·비유·오개념·`review_status` 포함 전 컬럼 갱신. 별도로 `mark_review_status`가 검수 라벨 기준으로 `reviewed`를 찍는다 | **예** |
| 7 | 힌트 `hints` | `l4/hint_content/store.py` `write_hints` — `hint_id`가 결정론이라 재생성이 같은 행을 다시 쓰고, 내용이 다르면 전 컬럼을 덮는다 | **예** |

**7종 중 5종이 편집을 지운다**(2·4·5·6·7). 1·3은 덮는 경로가 없어 보호가 필요 없다.

**비대상(사실 기록)**: `ops/loop_kpi_sample_load.py`가 `session.merge(Problem…)`로 문항을 쓰지만 결정론 합성 UUID를
**전용 DB**에 쌓는 KPI 표본 경로라 CMS가 고치는 운영 행과 겹치지 않는다. 계약 밖으로 둔다.

## 3. 결정

**D1 — 표지 컬럼 `cms_edited_at TIMESTAMPTZ NULL`을 5개 테이블에 둔다.** (2026-10-09 사용자 결정: 감사 기록 재사용안 B를
기각하고 컬럼안 A 채택.) `NULL`=사람이 고친 적 없음(적재가 소유), 값=CMS가 마지막으로 고친 시각(사람이 소유).
`server_default`와 백필을 두지 않는다 — 기본값을 달면 PG가 기존 행 전체를 마이그레이션 시각으로 백필해 "전 행을 사람이
고쳤다"는 날조가 되고 다음 적재가 전부 막힌다(`problem.quarantined_at`의 선례). 마이그레이션 `e7b2c4d8a1f6`.
감사 기록(`privacy_audit`)을 쓰지 않은 이유: 코드 스스로 "2차 신호"라 부르는 자료이고, 보존 기간이 MGMT-02에 걸려
있어 정해지면 보호가 조용히 사라지며, append-only라 한 번 편집된 행을 풀어주는 길이 없다.

**D2 — 사람이 쓰면 표지를 채운다.** 문항에는 사람이 쓰는 경로가 4개다. 넷 모두 같은 함수(`mark_cms_edited`)를 쓴다.

| 쓰기 경로 | 채우는 조건 |
|---|---|
| CMS 편집 `PATCH /v1/admin/cms/{리소스}/items/{pk}` | **실제로 바뀐 필드가 있을 때만**(같은 값 저장은 소유권을 가져가지 않는다) |
| CMS 검수 표시 `POST …/review` (전략·개념 설명) | 표시가 바뀔 때. 적재가 `reviewed`를 코퍼스 값으로 되돌리면 검수가 소실된다 |
| 기존 `PATCH /v1/problems/{id}` (문항) | 항상 — 본문과 검수·격리 상태를 모두 쓴다 |
| 검수 큐 전이 `POST /v1/admin/review-queue/items/{id}/transitions` (문항) | 항상 — 격리·승인 등 사람이 정한 상태 |

**D3 — 적재는 표지가 있는 행을 건너뛰고 충돌로 보고한다.** `ON CONFLICT DO UPDATE … WHERE cms_edited_at IS NULL
RETURNING <pk>`. 건너뛴 행은 RETURNING이 비어 있고, 적재 건수에 세지 않으며(적재가 일했다는 증거가 아니므로), CLI가
`CMS 편집 보호로 건너뜀: N건 […]`을 낸다. 문항은 본문·검수 상태만 건너뛰고 개념 태깅·출처 원장·계보는 정상 처리한다.
검수 승격(`mark_review_status`)도 고친 본문에는 `reviewed`를 찍지 않는다 — 파일 기반 검수 라벨은 고치기 *전* 본문을 보고
매긴 것이다.

**D4 — 덮어쓰기는 `--overwrite-cms-edits`로만 일어나고, 그때 표지를 비운다.** 표지를 푸는 유일한 길이다. 풀린 뒤에는
영구 잠금이 아니라 적재가 다시 소유한다(통합 테스트가 확인).

**D5 — 신규 작성을 CMS가 열지 않는 현행 결정을 유지한다.** 새 교육과정/판·풀이 경로·문항·오개념·교수전략의 신규 작성은
적재 파이프라인의 저작권·출처·라이선스 레일(`require_provenance`·`content_provenance` 원장 등)의 소관이다. CMS에서 만들면 그
레일을 우회한다. 이번 계약의 보호도 "고치기"만 다루므로 이 결정과 충돌하지 않는다. 재판정 조건: 신규 작성을 열 때는 그 경로가
같은 출처 관문을 거치도록 하는 설계가 선행돼야 한다.

## 4. 집행 지점 (정본화와 별항 — acceptance ④)

정본(이 문서·`cms_edit_marker.py`)이 있다는 것과 **적재 코드가 실제로 경유한다**는 것은 다르다. 경유 지점은 다음이다.

| 계약 | 서빙/적재 코드의 경유 지점 | 이를 고정하는 장치 |
|---|---|---|
| 적재는 표지 행을 건너뛴다 | `l1/problem_bank/populate.py`·`l1/misconception/catalog_loader.py`·`l1/strategy_graph/strategy_node_projection.py`·`l1/concept_content/projection.py`가 `upsert_guard`를 부르고 `l4/hint_content/store.py`가 `row.cms_edited_at`를 검사 | `tests/backend/db/test_cms_edit_marker.py::TestEnforcementPoint` — AST로 "보호 모델을 `pg_insert`하는 모듈은 `upsert_guard`를 부른다"를 전수 스캔(스캔 0건은 실패·새 적재 경로가 생기면 집합 불일치로 실패) |
| 사람이 쓰면 표지를 채운다 | `api/admin_cms_resources.py::apply_changes`, `api/admin_cms.py::_review_item`, `api/problems.py` PATCH, `api/admin_bff.py` 전이 | 각 라우트의 단위 테스트가 표지 채움/비채움을 단언 |
| 5종 선언이 일치한다 | `CMS_PROTECTED_TABLES` · ORM 컬럼 · `ResourceSpec.loader_protected` · 마이그레이션 | `TestProtectedTablesAgree` 4건 + `check_specs`가 import 시점에 불일치를 거부 |
| 실 DB에서 편집이 살아남는다 | 위 전부 | `tests/backend/l1/test_cms_edit_loader_contract_integration.py` (실 PG) |

## 5. 한계 (정직 고지)

1. **정본 파일은 DB와 달라진 채로 남는다.** 보호는 DB 편집을 지킬 뿐 코퍼스 파일로 역기록하지 않는다. 건너뛴 행의 코퍼스
   값은 계속 옛 값이다. 충돌 보고가 그 신호다. 역기록(편집을 정본으로 내보내기)은 별도 설계가 필요해 이 계약 밖이다.
2. **행 단위 보호다.** 한 필드만 고쳐도 그 행의 모든 필드가 코퍼스 갱신에서 빠진다. 코퍼스의 다른 필드가 정당하게
   바뀌어도 반영되지 않고 충돌로 보고된다(`--overwrite-cms-edits`로 푼다 — 편집 소실을 감수).
3. **문항은 검수 큐 승인·격리도 표지를 채운다.** 따라서 검수를 거친 문항은 이후 코퍼스를 다시 적재할 때 충돌로 보고된다.
   코퍼스 초기값으로 승인·격리가 되돌아가는 것보다 낫다고 판단했다. 보고량이 노이즈가 되면 §7의 개선 후보를 본다.
4. **표지는 `UPDATE` 직접 수정(SQL 손편집)을 모른다.** 사람이 psql로 고친 행은 표지가 없다.
5. **통합 테스트는 `cms_edited_at` 컬럼이 없으면 skip한다**(기존 통합 테스트와 같은 규약). 마이그레이션이 적용되는
   `backend-migrations` 잡에서만 실제로 실행된다.

## 6. 검증 증적 (2026-10-09, 임시 PostgreSQL 16)

**GREEN**: 통합 테스트 5건(문항·오개념·교수전략·개념 설명·힌트)이 실 DB에서 통과 — 각각 ① 두 행 적재 ② 한 행만 CMS 코드
(`validate_changes`+`apply_changes`)로 편집 ③ 재적재 시 편집 행은 보존·충돌 보고, 편집 안 한 행(대조군)은 갱신 ④
`--overwrite-cms-edits`로 덮어쓰기·표지 해제 ⑤ 해제 후 정상 갱신.

**RED(보호를 끈 주입)**: 통합 테스트에 6종을 주입해 모두 RED, 원복은 바이트 동일.

| 주입 | RED가 난 테스트 |
|---|---|
| `upsert_guard`가 보호 where를 안 건다 | 전략·개념 설명·오개념·문항 4건 |
| 힌트 writer가 표지 행을 건너뛰지 않는다 | 힌트 1건 |
| CMS `apply_changes`가 표지를 안 채운다 | 전략·개념 설명·오개념·힌트 4건(문항은 격리 단계에서 표지를 직접 채워 통과 — 이 주입으로는 편집 경로 표지가 문항에서 증명되지 않는다. 문항의 편집 경로 표지는 `test_admin_cms_resources.py`가 증명한다) |
| 검수 승격이 CMS 편집 행을 안 거른다 | 개념 설명 1건 |
| 문항 적재만 보호 where 누락 | 문항 1건(다른 4종은 통과 — 선택적) |
| 덮어쓰기 모드가 표지를 안 비운다 | 문항·오개념·전략·개념 설명 4건 |

단위·거버넌스 주입 4종(가드 호출 제거·CLI 미전달·마이그레이션에 `server_default` 추가·힌트 검사 제거)도 전부 RED다.

**설계가 실측으로 고쳐진 1건**: 처음 판정을 `rowcount == 0`으로 했는데 실 PG(psycopg3)에서 `INSERT … ON CONFLICT`의
`rowcount`는 삽입·갱신·건너뜀 모두 **-1**이라 변별력이 0이었다. 가짜 엔진 테스트는 통과했고 실 DB에서만 예외로 드러났다
(알 수 없으면 예외로 두었기에 조용히 오분류되지 않았다). 지금은 `RETURNING` 결과가 비었는지로 판정한다.

## 7. 운영 절차와 후속

- 적재 CLI 6종(`l1.problem_bank.populate`·`l1.misconception.populate`·`populate_atom`·`l1.strategy_graph.populate`·
  `l1.concept_content.populate`·`l4.hint_content.populate`)이 `--overwrite-cms-edits`를 받는다. 기본은 보호다.
- 충돌 보고를 본 뒤 정본을 고칠지(코퍼스에 편집을 반영) 덮어쓸지(편집 포기)는 사람이 정한다.
- 후속 후보: ① 편집을 코퍼스로 역기록하는 내보내기 ② 문항 승인만으로는 표지를 채우지 않고 본문 편집일 때만 채우는 세분화
  (한계 3의 노이즈가 실측으로 문제될 때) ③ CMS 상세 응답에 `cms_edited_at`을 노출해 화면이 "코퍼스와 달라진 행"임을 말하게 하기.
