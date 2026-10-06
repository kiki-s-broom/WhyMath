# Problem Quarantine Contract — 결함 문항의 비파괴 격리 정본

> 운영 중 사후 결함 판정(정답 오류·복수 정답·모호 문장 등)을 받은 문항을 **삭제하지 않고 격리**하는
> 경로의 계약 정본이다. 상태값 정본은 `src/backend/whymath_backend/schema/enums.py`의
> `ReviewStatus.quarantined`·`is_review_status_quarantined()`이고, 이 문서와 코드의 정합은 §6의
> 테스트가 기계로 동결한다. 태스크: `EOS-71-problem-quarantine-status`(검토_18 §24 채택).

## 왜 이 계약이 있는가 (사고 경위)

이 상태값이 없던 시기에 **파괴적 처분이 실제로 일어났다**. `docs/data/problem_duplicate_disposition_2026-08.md`
§3은 실중복 9쌍의 한쪽을 은퇴시키면서 `problems.jsonl`에서 **레코드 라인 9건을 물리 제거**했고, 그 근거를
이렇게 자인한다 — *"감사 도구는 `review_status`를 필터하지 않는다 → 마킹만으로는 목록에서 사라지지
않는다."* 즉 **비파괴 격리 경로가 없어서** 파괴적 수단이 선택됐다. 이 계약은 그 선택지를 구조화된
대안으로 대체한다.

같은 공백은 서빙 쪽에도 있었다. `api/problems.py`의 무인증 GET 4종(단건·목록·steps·relations)은
`review_status`를 **전혀 보지 않아서**, 결함 판정을 받은 문항이 풀이 단계까지 그대로 나갔다. §4가 그
구멍을 닫는 집행 지점이다.

## 1. 상태 정의 — `quarantined` ≠ `rejected`

| 값 | 뜻 | 서빙된 적이 있나 | 딸린 `problem_attempt` |
|---|---|---|---|
| `pending` | 미검수(기본) | 공개 카탈로그에는 노출(§4 주석 참조) | 있을 수 있음 |
| `approved` | 검수 통과 — 학생 노출 대상(§13.3) | 예 | 있음 |
| `rejected` | **애초에 승인받지 못함**(검수 기준 미달) | 아니오 | 통상 없음 |
| `quarantined` | **한때 `approved`로 서빙되던 문항의 사후 결함 판정 → 회수** | 예 | **있고, 보존한다** |

두 값을 **합치지 않는 이유**: `rejected`는 "들여보내지 않았다", `quarantined`는 "들여보냈다가
되돌렸다"이다. 하나로 합치면 *학생이 이미 풀어 본 결함 문항*과 *한 번도 나간 적 없는 탈락 문항*이 같은
글자가 되어, 딸린 학습 기록을 재채점·θ 재계산 대상으로 볼지 사후에 구분할 수 없게 된다.

`quarantined`는 스펙 스냅샷(`schemas/v1.0/schema_v1.0.md` §3.1 `review_status_enum` 주석)의 원안
3종 **이후에 더한 운영 확장**이다. 스냅샷은 원안 그대로 두고 확장은 enum docstring이 이고 간다 —
`EventType`이 §6.1 주석 8종에 검산결과·힌트제공·시각화조작·문제시도를 더한 것과 같은 방식이다.

## 2. 비파괴 원칙 (협상 불가)

격리가 끊는 것은 **노출뿐**이다.

1. `problem` 레코드를 삭제하지 않는다 — 상태값과 사유만 바뀐다.
2. 그 문항에 딸린 `problem_attempt`·`attempt_event` 학습 기록을 삭제·수정하지 않는다.
3. 학생의 **과거 이력 조회는 그대로 유지**된다 — `GET /v1/me/ability/history`는 `review_status`를
   필터하지 않는다(§4 표의 "의도적 미집행" 행). 격리 이전에 푼 문항이 성장 곡선에서 사라지면 학생이
   "내가 푼 게 없어졌다"를 보게 되고, 그건 결함 문항이 만든 피해에 데이터 소실을 더하는 것이다.
4. 코퍼스 JSONL에서 레코드 라인을 제거하는 처분은 **이 경로가 있는 한 기본 수단이 아니다**. 물리 제거를
   택하려면 왜 격리로 불충분한지를 판정 기록에 남긴다.

## 3. 격리 사유 기록 의무

격리 표시(`review_status = quarantined`)는 다음 두 컬럼과 **함께** 기록한다.

| 컬럼 | 타입 | 의무 |
|---|---|---|
| `quarantine_reason` | `TEXT` (nullable) | 결함의 구체 서술(정답 오류·복수 정답·모호 문장·중복 등) |
| `quarantined_at` | `TIMESTAMPTZ` (nullable) | 격리 시각 — 이 시각 *이전* attempt는 결함 문항 응답일 수 있다 |

두 컬럼 모두 **nullable·server_default 없음**이다. `DEFAULT now()`를 달면 마이그레이션 시각이 기존 행
전체에 백필되어 "격리된 적 없음"과 "이 시각에 격리됨"이 같은 값이 된다(날조 방지 — `activity.py`
`ingested_at`·`attempt_event.skill_ids` 규약과 동형).

상태값만 있고 사유가 없으면 "왜 회수됐는가"가 사람 기억에만 남아 해제 판단도 재발 방지도 불가능해진다.
두 컬럼은 **운영 메타이므로 공개 투영에 자리가 없다** — `PUBLIC_HIDDEN_OPS_FIELDS`(§4).

## 4. 집행 지점 — 어느 표면이 무엇으로 차단하는가

> **정본화와 집행은 별항이다**(CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지"). §1~3이 계약의
> 정본화이고, 아래 표가 **그 계약을 실제로 부르는 서빙 코드 경로**다.

| 표면 | 코드 경로 | 차단 술어 | 격리가 차단되는 이유 |
|---|---|---|---|
| L6 6모드 게이팅(retake·suneung·school_progress·thinking·metacognition·gifted) | `l6/*/gating.py::is_*_eligible` → `_shared.is_review_cleared` | `is_review_status_cleared`(허용목록) | `approved`가 아니므로 **자동 배제**(코드 변경 0) |
| L6 blueprint 조립 | `l6/blueprint/assembly.py::is_blueprint_eligible` → `_shared.is_review_cleared` | `is_review_status_cleared` | 동상 — 자동 배제 |
| 기본 CAT 후보 풀(다음 문제 추천) | `api/me.py::candidate_pool_conditions` | SQL `review_status == 'approved'` | 동상 — 자동 배제 |
| 빌드타임 개념 평가 재료 상속 | `harness/concept_assessment_index.py` | `is_review_status_cleared` | 동상 — 자동 배제 |
| **공개 카탈로그 GET 단건** `/v1/problems/{id}` | `api/problems.py::read_problem` | `_reject_if_quarantined` → **404** | 이 표면은 승인을 요구하지 않는다(아래) |
| **공개 카탈로그 GET 목록** `/v1/problems` | `api/problems.py::list_problems` | `quarantine_exclusion_condition()` → SQL `IS DISTINCT FROM` | 〃 |
| **공개 풀이 단계** `/v1/problems/{id}/steps` | `api/problems.py::list_problem_steps` | `_reject_if_quarantined` → **404** | 〃 |
| **공개 문항 관계** `/v1/problems/{id}/relations` | `api/problems.py::list_problem_relations` | `_reject_if_quarantined` → **404** | 〃 |
| 관리자 표면(POST/PATCH/DELETE) | `api/problems.py` — `RequireContentAdmin` | 없음(의도) | 격리 *설정*이 이 표면에서 일어난다(§5) |
| **의도적 미집행**: 학생 이력 조회 `/v1/me/ability/history` | `api/me.py::get_my_ability_history` | 없음(의도) | §2-3 비파괴 — 과거 attempt는 남아야 한다 |

**왜 공개 GET 4종만 새 술어가 필요했나**: 위 표 상단 4개 표면은 전부 "`approved`만 통과"라는
**허용목록**이라, `quarantined`가 새로 생겼다는 이유만으로 이미 fail-closed로 배제된다. 반면
`api/problems.py`의 GET 4종은 **검수 통과를 요구하지 않는** 공개 카탈로그다(SEC-07 D1 — `pending`·
`NULL` 문항도 그대로 나간다). 여기에 `is_review_status_cleared`를 거는 것은 "카탈로그 전체 공개 →
승인분만 공개"라는 **정책 변경**이라 범위 밖이다(§7). 그래서 *격리만* 지목해 차단하는
`is_review_status_quarantined`를 별도로 둔다.

**SQL 3값 논리 함정(중요)**: 목록 배제를 `review_status != 'quarantined'`로 쓰면 `review_status`가
NULL인 행에서 비교 결과가 NULL이 되고 WHERE가 그것을 참으로 치지 않아 **검수 미평가 문항이 전부 목록에서
조용히 사라진다**. 실코퍼스에는 `review_status`가 빈 레코드가 실제로 존재하므로(백필 대상 —
`harness/problem_corpus_review_status_backfill.py`) 이론적 위험이 아니다. 반드시
`IS DISTINCT FROM`(`ColumnOperators.is_distinct_from`)을 쓴다.

**404를 쓰는 이유**: 공개 GET은 무인증이라 403(존재하나 금지)으로 답하면 "그 id에 문항이 있다"를
확인해 주는 오라클이 된다. 대신 **detail 문자열을 일반 404와 다르게** 적어, 비노출이 데이터 부재가
아니라 운영 격리 판정 때문임을 응답과 로그 양쪽에 남긴다(침묵 실패 금지). 사유 본문
(`quarantine_reason`)은 싣지 않는다 — 운영 메타이고 무인증 표면이다.

## 5. 격리·해제 절차

**격리 설정** — 관리자 표면(`PATCH /v1/problems/{id}`, `RequireContentAdmin`)으로 세 필드를 함께 쓴다.
전용 엔드포인트를 따로 두지 않는다(§7).

> **추가 기록 (ADMIN-07 · 2026-10) — 검증된 전용 경로**: 검수 큐 화면용으로
> `POST /v1/admin/review-queue/items/{problem_id}/transitions`(`RequireReviewAdmin` = CONTENT_ADMIN
> 전용·데모 403)가 생겼다. 본문 `{action, expected_status, reason}`의 `action`은
> approve/reject/quarantine/release 4종이며 **허용 전이표**(`schema/review_transition.py` —
> approve: pending→approved · reject: pending→rejected · quarantine: approved→quarantined ·
> release: quarantined→approved, 그 외 전부 불허, 상태 미설정(`None`)은 어떤 액션도 불허)를 서버가
> 집행한다. 한 트랜잭션에서 행 잠금(`SELECT … FOR UPDATE`) → `expected_status` 불일치 시 409
> `stale_status` → 전이표 위반 시 409 `illegal_transition` → 갱신 → `privacy_audit` 1행(`action` =
> 전이 액션 값) → commit 1회이며, 감사 쓰기가 실패하면 상태 변경도 롤백된다. `quarantine`은 `reason`
> (공백 제외 1자 이상)을 필수로 요구하고 `quarantine_reason`·`quarantined_at`을 **상태와 함께** 쓴다
> (§3 이행을 서버가 강제). `release`는 `approved`로 되돌리되 사유·시각을 지우지 않는다(아래 해제 2항과
> 일치). 감사 행에는 사유를 싣지 않는다(PII 불변식 — 사유의 좌석은 `quarantine_reason`).
> 이 기록은 위 PATCH 결정을 **뒤집지 않는다** — 아래 PATCH 경로는 그대로 유효하다.
> **한계(사실대로)**: `PATCH /v1/problems/{id}`는 전이 검증이 없고(예: `rejected`→`approved`,
> 사유 없는 격리가 통과한다) 이번 변경으로 막지 않았다. 그러므로 전이 계약은 **전용 경로를 쓰는 운영
> 흐름**에 대해서만 성립하며, PATCH로의 우회는 남아 있다(범위 밖 — §7 참조).

```
PATCH /v1/problems/{problem_id}
{ "review_status": "quarantined",
  "quarantine_reason": "복수 정답 — 조건 (나)에서 x<0도 해가 된다(2026-08-31 판정)",
  "quarantined_at": "2026-08-31T09:00:00Z" }
```

- 세 필드를 함께 쓰지 않으면 §3 의무 위반이다(현재 스키마 수준 강제는 없다 — §7 참조).
- PATCH는 병합 결과를 `schema.Problem`으로 **재검증**하므로 본문 보유 금지 등 기존 불변식은 유지된다.

**해제(재승인)** — 결함이 실제로 고쳐졌거나 오판으로 밝혀졌을 때만.

1. 결함을 수정하거나 오판 근거를 확보한다.
2. `review_status`를 `approved`로 되돌린다. **`quarantine_reason`·`quarantined_at`은 지우지 않는다** —
   회수 이력은 그 문항의 영구 기록이며, 재발 시 "전에도 같은 이유로 회수됐다"를 말해야 한다.
3. 해제 판단 근거는 격리 사유 문자열에 추가로 적는다(덮어쓰지 않고 덧붙인다).

## 6. 이 계약을 기계로 동결하는 테스트

| 파일 | 동결하는 축 |
|---|---|
| `tests/backend/schema/test_enums.py` | 상태값 집합(4종) · `is_review_status_quarantined` 전수 판정 · `is_review_status_cleared`가 `quarantined`를 배제 |
| `tests/backend/db/test_problem_quarantine_orm.py` | 두 컬럼의 nullable·server_default 없음 · schema↔ORM round-trip · 마이그레이션 리비전/체인/`ALTER TYPE`/add·drop 대칭 |
| `tests/backend/api/test_problem_quarantine_serving.py` | 공개 GET 4종 차단(404·목록 SQL) · `IS DISTINCT FROM` 회귀 방지 · CAT 후보 풀 배제 · `ability/history` 미필터(비파괴) · 격리 PATCH가 삭제를 일으키지 않음 |
| `tests/backend/l6/test_quarantine_exposure_gate.py` | L6 6모드 + blueprint 조립이 격리 문항을 배제(양성 대조 동반) |
| `tests/backend/api/test_problems_public_projection.py` | 운영 메타 2필드가 공개 투영에 자리 없음(분류 완전성) |
| `tests/backend/db/test_schema_version_guard.py` | 런타임 스키마 버전 상수(`db/schema_version.py` `KNOWN_REVISIONS`)가 실제 alembic 이력과 일치 — wheel에 `alembic/versions/`가 없어 런타임은 이 상수를 믿는다 |

## 7. 범위 밖 (명시)

- **`pending`·`NULL` 문항을 공개 GET에서 배제할지** — 이건 격리 축이 아니라 *공개 카탈로그 정책*
  (SEC-07 D1)의 변경이다. 회귀 범위가 크고 Kiki 결정 사항이라 이 태스크에서 손대지 않았다(§4 참조).
- **격리 전용 엔드포인트**(`POST /v1/problems/{id}/quarantine`) — 관리자 PATCH로 충분하고, 표면을 늘리면
  인가·ETag·감사 로그 계약을 한 벌 더 유지해야 한다. *(ADMIN-07 추가 기록: 검수 큐용 전이 라우트가
  `POST /v1/admin/review-queue/items/{id}/transitions`로 별도 착지했다 — §5 참조. 이 항의 판단 자체는
  `/v1/problems` 하위 표면에 대한 것이라 유지된다. PATCH의 전이 검증 부재는 여전히 범위 밖이다.)*
- **세 필드 동시 기록의 스키마 강제**(`review_status == quarantined ⇒ reason·at NOT NULL`) — 교정
  불변식으로 올리면 기존 행·마이그레이션 경로와 충돌한다. 현재는 이 문서의 절차 의무이고, 강제가
  필요해지면 별도 태스크로 등재한다.
- **격리 문항의 attempt 재채점·θ 재계산** — 결함 문항 응답을 학습자 모델에서 어떻게 다룰지는 L2 소관
  판단이다. 이 태스크는 기록을 **보존**할 뿐 재해석하지 않는다.
- **감사 도구(`harness/problem_duplication_audit.py`)의 `review_status` 필터** — 2026-08 처분에서
  물리 제거의 직접 근거가 된 바로 그 공백이다. 도구 수정은 이 태스크(서빙 축) 범위 밖이며, 격리 상태값이
  생겼으므로 이제 필터 추가가 의미를 갖는다.
