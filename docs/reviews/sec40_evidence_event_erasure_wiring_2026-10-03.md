# SEC-40 — 삭제권 이행 시 `evidence_event` 함께 삭제 (판정·배선·증거)

> **판정 기준: main `12242694a6bf7e2f457f1418d893e958b341053d` 위의 *미머지 작업 사본*** (브랜치
> `claude/gallant-euler-blngpj`, 커밋 전). 이 문서의 "있다/없다"는 그 작업 사본 기준이며, trunk(main)에는
> 아직 없다. 머지 전에는 "main 기준 충족"으로 읽지 않는다. 로컬 DB = PostgreSQL 16(`pgvector` 확장만 있고
> **TimescaleDB 없음**), alembic head `b4d8e2a6c0f3`.

## 0. 초보자용 용어 풀이

- **삭제권(PIPA)**: 정보주체(학생)가 자기 개인정보를 지우라고 요구할 수 있는 권리. 이 앱에서는 "계정 전체
  삭제"(`DELETE /v1/me`)와 "학습 세션 하나 삭제"(`DELETE /v1/me/sessions/{id}`) 두 갈래가 있다.
- **`evidence_event`**: 학생에게 어떤 교수법·추천을 보여줬고 그 뒤 결과가 어땠는지 시간순으로 쌓는 기록
  테이블. 학생 ID 컬럼이 **없고** `session_id`(어느 학습 세션인가)로만 학생과 이어진다.
- **느슨참조(loose reference)**: 값은 다른 테이블의 ID와 같지만 DB가 "그 행이 실제로 있는지" 검사하지
  않는 연결. DB가 연결을 모르므로 부모를 지워도 자식이 **자동으로 안 지워진다**(CASCADE 불가).
- **`deletion_audit`**: "누가 무엇을 지웠다"는 증빙 로그. 삭제 후에도 남아야 증빙이 되므로 (user_id,
  resource_id)를 남긴다. 이 키가 곧 **재연결의 출발점**이 된다.
- **HMAC 바인딩(`meta.user_binding`)**: `HMAC(서버 비밀키, "도메인:session_id:user_id")`. 비밀키를 가진
  서버는 user_id 하나만 알아도 모든 행의 바인딩을 다시 계산해 "이 학생의 행"을 골라낼 수 있다.
- **재연결(re-link)**: 지웠다고 생각한 학생의 기록을 남은 단서(증빙 로그의 키·바인딩)로 다시 찾아내는 것.
- **하이퍼테이블(TimescaleDB)**: 시간 기준으로 조각(청크)을 나눠 저장하는 시계열 테이블.

## 1. 재연결 경로 2건과 닫는 증거

| 경로 | 이전 상태 | 지금 | 닫힌 증거(테스트) |
|---|---|---|---|
| ⓐ 개별 세션 삭제 | `_delete_owned_resource`가 `learning_session`만 지우고 `deletion_audit`에 (소유자, 세션 ID)를 남김 → 그 세션 ID의 `evidence_event`가 남아 증빙과 맞대면 처치 기록을 찾음 | 같은 트랜잭션에서 그 세션의 `evidence_event`를 먼저 지움 | `test_erasure_relink_integration.py::TestSessionDeletionRelink::test_no_evidence_event_is_relinkable_after_session_deletion` |
| ⓑ 계정 삭제 | `erase_user`가 `evidence_event`를 안 지움 + `deletion_audit`에 user_id가 남음 → 비밀키 보유 주체가 잔존 user_id로 전 행 바인딩을 재계산해 세션을 되찾음 | 학습 세션 ID ∪ HMAC 일치 세션 ID로 지움(아래 §2) | `test_erasure_relink_integration.py::TestAccountErasureRelink::test_no_evidence_event_is_relinkable_after_account_erasure` |

공통 보강 증거:

- **원자성(부분 삭제 0)**: `TestAccountErasureRelink::test_account_erasure_is_atomic_when_a_later_step_fails`
  (증빙 삭제 *뒤* 단계가 실패해도 증빙·세션·계정·감사 행 전부 롤백),
  `TestSessionDeletionRelink::test_session_deletion_is_atomic_when_commit_fails`(커밋 실패 시 세션과 증빙이
  함께 남음).
- **소유 검증**: `test_foreign_session_id_deletes_nothing`(타인 세션 ID → 404, 증빙 0건 삭제).
- **대조군(과삭제 방지)**: 계정 삭제는 다른 학생의 세션·처치 행 3건이 그대로이고 같은 재연결 계산이 그
  행을 실제로 찾는다(검사기 위장 방지). 세션 삭제는 같은 학생의 다른 세션·임의 UUID 처치·다른 학생 행이
  그대로다.
- **구조·순서(DB 없이 항상 실행)**: `test_erasure_relink_wiring.py` 6건 — 계획 편입·허용목록 제거, 세션 ID
  수집 SELECT가 `learning_session` 삭제보다 앞, `settings` 필수 키워드, 세션 삭제 경로의 증빙 DELETE가 세션
  행 삭제보다 앞이고 commit 1회, 대화·진단 삭제는 증빙 불접촉.

**발견: 실 `/study` 처치는 학습 세션이 아니다.** `api/study.py`는 처치마다 `session_id = uuid.uuid4()`를
새로 만들어 `learning_session`에 없는 ID를 쓴다. 학습 세션 조인만으로 지우면 교수법 처치·결과 행이 전부
남고, 정확히 ⓑ(HMAC 재계산)로만 학생에 이어진다. 그래서 계정 삭제는 **두 갈래의 합집합**을 지운다 —
ⓐ 학생의 `learning_session.session_id` ⓑ 저장된 `user_binding`이 `HMAC(현재 비밀키, session_id, user_id)`와
일치하는 행의 `session_id`. 결과 행(`pedagogy_outcome`)은 `meta`가 없지만 처치와 같은 `session_id`를 쓰므로
합집합으로 함께 지워진다(통합 테스트가 처치+결과 1쌍으로 확인).

## 2. before/after — 삭제 순서와 트랜잭션 경계

**계정 삭제 `erase_user(session, user_id, settings)`** (commit은 호출자 — `erase_my_account`가 1회)

- before: `_ERASURE_PLAN` 루프(`dialogue` … `learning_session` … 기타) → `DeletionAudit` add →
  `user_profile` 삭제 → flush. `evidence_event` 미접촉.
- after: **① 세션 축 ID 수집**(`learning_session` SELECT + 바인딩 보유 `evidence_event` SELECT 후 파이썬에서
  HMAC 재계산·`hmac.compare_digest` 비교) → ② 계획 루프. `evidence_event`는 `_SESSION_AXIS_MODELS` 분기로
  `== user_id`가 아니라 `session_id IN (수집 목록)`(5,000개 청크)으로 삭제, `learning_session`보다 앞 위치 →
  ③ `DeletionAudit` → ④ `user_profile` → flush. 전부 한 트랜잭션. `settings`는 필수 키워드(기본값 없음 —
  비밀키 없이 호출해 HMAC 갈래가 조용히 빠지는 것을 시그니처가 막는다). `erase_my_account`는
  `SettingsDep`로 받아 넘긴다.
- 수집을 세션 삭제 뒤로 미루면 목록이 비어 증빙이 남는다(뮤테이션 b로 RED 확인).

**개별 세션 삭제 `_delete_owned_resource`** (`model is LearningSession`일 때만)

- before: 소유 확인 → `session.delete(row)` → `DeletionAudit` add → commit.
- after: 소유 확인 → **`DELETE FROM evidence_event WHERE session_id = :pk`** → `session.delete(row)` →
  `DeletionAudit` add → commit(1회). 소유 확인 뒤라 타인 세션 ID로 남의 증빙을 지우는 경로가 없고, 증빙
  DELETE가 예외를 내면 그대로 올라가 세션 삭제도 커밋되지 않는다(삼키는 except 없음). 분기를 플래그
  인자가 아니라 `model is LearningSession`으로 둬서 이 헬퍼의 새 호출자도 기본으로 따라온다.

## 3. SEC-39 허용목록 제거

- `erasure.py`: `_ERASURE_PLAN_EXEMPTIONS["evidence_event"]`와 `_ERASURE_PLAN_EXEMPTION_EXPIRY["evidence_event"]
  = "SEC-40"`을 제거(만료 맵은 `{}` — 임시 예외 0건). `(EvidenceEvent, "session_id")`를 `_ERASURE_PLAN`에 편입.
- 완전성 테스트 결과: `test_erasure_plan_completeness.py` 47건 통과(exit 0). 허용목록을 남긴 채로는 RED:
  뮤테이션 f(허용목록·만료 항목을 되살림)에서 `test_evidence_event_is_erased_or_temporarily_exempted_with_expiry`·
  `test_exemptions_are_subset_of_actual_owner_tables` RED. 또 같은 항목을 `SEC-40.status=done` 합성 백로그로
  판정하면 `_exemption_expiry_violations`가 "이미 done인데 임시 예외가 남아 있다 — 만료됐다"를 낸다(in_progress면
  빈 목록). 태스크 파일 자체는 건드리지 않았다.
- **SEC-39 테스트 파일 수정 2곳(근거 필요)**: `owner_column_names()`와 그 파생 검사를 *세션 축 계획 항목은 (B)
  user 축 이름에서 뺀다*로 고쳤다. 계획에 `("session_id")`가 들어오면 (B)가 `session_id` 컬럼을 가진 모든 테이블을
  잡아 (C)를 지워도 가드가 초록인 상태(SEC-39 사각 핀 2건이 RED로 먼저 알려 줌)가 되기 때문이다. 분리는
  `test_owner_column_names_are_derived_from_plan_not_hardcoded`가 동결한다.

## 4. `attempt_event` 처분 판정 — **유지 (이번 태스크에서 삭제하지 않음)**

판정 근거(코드 판독 + 통합 테스트로 동결):

1. **재연결 키가 구조적으로 없다.** `attempt_event`에는 세션 컬럼이 없고(`attempt_id`·`user_id`·`problem_id`뿐),
   시도↔세션 연결은 `problem_attempt` 행에만 있으며 그 행은 세션 삭제 CASCADE로 사라진다. `deletion_audit`의
   (user_id, resource_id=세션 ID)로 이 행을 가리킬 방법이 없다 — `evidence_event`와 근본이 다르다. 전제는
   `test_attempt_event_remains_after_session_deletion_and_has_no_session_axis`가 동결(세션 컬럼이 생기면 RED →
   재판정 강제).
2. **세션 단위로 완전하게 지울 수 없다.** 세션에 묶이는 것은 `attempt_id`가 있는 행뿐이고, 시각화 조작 등
   `attempt_id`가 NULL인 행은 어느 세션 것인지 알 수 없다. 일부만 지우면 "세션 삭제로 행동 로그가 지워졌다"는
   오해를 만든다.
3. **처분 범위 판단이 이 태스크의 게이트 밖이다.** 게이트 `G-eos37-erasure-kpi-disposition`은 `evidence_event`에
   대한 결정이었다. `attempt_event`는 학습 지표 롤업·하네스 지표의 직접 입력이라 지우면 그 결정이 다루지 않은
   KPI 영향이 생기고, 계정 삭제 시에는 이미 `_ERASURE_PLAN`이 user_id로 전량 지운다.
4. 이 판정은 "가명 보존이 적법하다"는 주장이 **아니다.** 남는 행은 user_id가 직접 달린 식별 정보이며(가명화
   아님), 계정이 살아 있는 동안의 사용자 단위 데이터라는 점만 구분한다. 법적 적정성은 변호사 판단.

**후속 태스크 후보(미등재 — 부모 판단)**: 세션 삭제 시 `problem_attempt`의 `attempt_id`를 CASCADE 전에 모아
`attempt_event`를 함께 지울지(attempt_id 연결분 한정) 결정 게이트와 함께 판정. 구현은 약 6줄이며
`_delete_owned_resource`의 `model is LearningSession` 분기에 같은 방식으로 얹을 수 있다. 판정을 '삭제'로 바꾸려면
위 통합 테스트의 마지막 단언(`remaining == 1`)을 함께 갱신해야 한다.

## 5. 하이퍼테이블 실측

- 마이그레이션(`20260724_1210_e6f1a2b3c4d5_evidence_event.py`): `timescaledb` 확장이 **있을 때만**
  `create_hypertable('evidence_event','time', chunk_time_interval => '7 days')`. `alembic/` 전체에 압축·보존
  정책 설정은 **0건**(`grep compress` 무결과).
- 이 환경 실측: `pg_extension` = `plpgsql`·`vector`뿐 — TimescaleDB 없음, `timescaledb_information.hypertables` 부재.
  따라서 **하이퍼테이블 DELETE·압축 청크 동작은 여기서 검증하지 못했다(모른다).** 통합 테스트는 일반 테이블
  위에서 통과했다.
- 근거 있는 사실: 이 모듈은 이미 다른 하이퍼테이블(`attempt_event`·`concept_mastery_history` 등)에 같은
  형태의 `DELETE ... WHERE <비파티션 컬럼>`을 발행한다. 압축 청크가 생기는 운영 환경이면 그 위의 DML 지원은
  TimescaleDB 버전에 달려 있으니(미확인) 운영 반영 전에 확인이 필요하다.
- 성능: `evidence_event` 인덱스는 PK `(event_id, time)`과 `idx_ev_obj_time (objective_id, time DESC)`뿐이라
  `session_id` 조건 DELETE와 바인딩 SELECT는 **전 청크 순차 스캔**이다(마이그레이션은 이 태스크 범위 밖 —
  인덱스 추가는 후속 후보).

## 6. 뮤테이션 (cp 백업 → 주입[원본≠변경·치환 count==1 단언] → 테스트 → cp 원복[sha 동일 단언])

대상 테스트 = 신규 2파일 + `test_erasure.py` + 완전성 + `test_me_erasure.py`(통합 포함 실행). 원복 후 sha 일치 단언 통과.

| 주입 | 결과 | RED가 된 테스트 |
|---|---|---|
| a. `erase_user`의 evidence 삭제 호출 제거 | RED(5건) | 통합 계정 삭제 · 수집 순서 wiring · `test_covers_all_planned_tables` · `test_report_aggregates_counts` · `test_me_erasure` 총 행수 |
| b. 세션 ID 수집을 세션 삭제 뒤로(계획 순서도 뒤집음) | RED(2건) | wiring 순서 · 통합 계정 삭제 |
| c. 개별 세션 삭제 경로의 증빙 삭제 제거 | RED(2건) | wiring 순서 · 통합 세션 삭제 |
| d1. `erase_user` 삭제 필터 완화(전 행 삭제) | RED(1건) | 통합 계정 삭제(대조군 3건 소실) |
| d2. 세션 삭제 경로 필터 완화(전 행 삭제) | RED(1건) | 통합 세션 삭제(대조군 소실) |
| e. HMAC 바인딩 갈래 제거 | RED(2건) | wiring(바인딩 SELECT 없음) · 통합 계정 삭제(임의 UUID 처치 잔존) |
| f. 허용목록·만료 항목 되살림 | RED(3건) | 계획 편입 wiring · 완전성 2건 |

7/7 검출. 참고: 주입 b는 계획 순서만 뒤집어서는 안 잡힌다(목록을 미리 모으므로) — 그래서 "수집 시점"을 함께
옮긴 형태가 실제 위험(구현자가 세션 삭제 뒤 수집)이다.

## 7. 검사 결과(exit code)

`ruff check . ../../tests/backend` 0 · `black --check --line-length 100 . ../../tests/backend` 0 ·
`mypy --strict whymath_backend` 0 · `lint-imports` 0(4 kept) · privacy 전체+연관 테스트(통합 포함) 323 passed ·
infra 4파일 101 passed 1 skipped · db/api `-k "evidence or session or study or me_"` 352 passed 67 skipped.
**전체 스위트는 확인하지 못했다**(부모가 ci_mirror로 실행).

## 8. 남은 불확실성

1. **비밀키 회전**: 바인딩 일치는 *현재* jwt 비밀키로만 계산된다. 회전 뒤에는 옛 키 바인딩을 못 알아봐 ⓑ 갈래가
   그 행을 못 지운다(그 행은 키 보유자도 더는 재연결할 수 없다는 점에서 위험이 줄 뿐 삭제된 것은 아님).
2. **placeholder 행**: 세션 기록 실패 경로의 결합 불가 UUID 추천 행은 어떤 학생에도 이을 키가 없어 지울 근거가 없다.
3. **규모**: 바인딩 갈래는 바인딩 보유 행을 전부 읽어 재계산한다(선형·결과 집합 메모리 상주). 현재 규모에서는 수용,
   커지면 후속(시간 하한·키드 인덱스 등).
4. **하이퍼테이블·압축 청크 DELETE 미검증**(§5).
5. **`evidence_event` 이외의 세션 연결 데이터**(예: 개별 세션 삭제 후 `attempt_event`)는 §4 판정대로 남는다.
6. `deletion_audit`의 user_id·resource_id 보존 연한은 정하지 않았다(MGMT-02 변호사 회신 선행 — acceptance ⑥). 이 태스크는
   `privacy/retention.py` ADMIN-03 문단·`evidence_event.retention_until`을 건드리지 않았다.
7. `erase_user` 시그니처에 `settings` 필수가 추가됐다 — 호출자는 `api/me.py` 1곳과 테스트뿐임을 확인했다(전수 grep).
