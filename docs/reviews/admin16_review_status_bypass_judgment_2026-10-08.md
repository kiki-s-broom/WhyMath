# ADMIN-16 판정 — PATCH 검수 상태 우회 폐쇄와 부수 항목 3종의 처분

> **판정 기준: main `8a5ea4d1`** (2026-10-08) · 이 문서의 코드 사실은 이 커밋 + ADMIN-16 브랜치 변경분
> 기준이다. 아래 "내가 찾은 방법으로는 0건"이라고 적은 부재 주장은 검색 범위를 함께 적었다.

## 0. 한 줄 결론

`PATCH /v1/problems/{id}`가 검수 상태를 전이표 없이 바꾸던 우회를 닫았다(§1). 부수 3항목 중
**문서 동기화는 이 PR에서 끝냈고(§4)**, **`privacy_audit` 불변 트리거는 "필요함 — 별도 태스크로 분리"**
(§2, `ADMIN-17`), **반려코드·HIT 타이머 강제는 "이 PR에서 하지 않음 — 별도 태스크로 분리"**(§3,
`ADMIN-18`)로 판정했다. 조사 중 발견한 두 건은 `ADMIN-19`·`ADMIN-20`으로 등재했다(§5).

## 1. 우회 폐쇄 — 무엇을, 왜 이 방식으로

### 1-1. 설계 선택: "전이표를 경유"(채택) vs "PATCH에서 상태 변경을 거부"(기각)

인수조건이 둘 다 허용했다("전이표를 경유하거나 거부"). 거부가 더 단순하지만 **기각**했다. 근거는 실측이다.

- `ops/generation_recall.py::apply_quarantine`(EOS-97 리콜 도구)이 **운영 중인 PATCH 호출자**다.
  `review_status`·`quarantine_reason`·`quarantined_at` 3필드를 PATCH로 보낸다. PATCH가 상태 변경을 일률
  거부하면 이 도구가 `approved` 문항에 대해서도 전부 실패한다.
- 격리 계약 §5가 PATCH를 정본 격리 절차로 명시하고 §7이 전용 격리 엔드포인트를 의도적으로 미채택했다.
- 전이표 경유는 이 두 가지를 깨지 않고, 같은 표를 두 표면이 읽게 해 규칙이 한 벌로 남는다.

대가는 §3·§5에 적었다(PATCH가 `reject`를 받는 한 반려코드 강제를 PATCH에도 걸어야 한다).

### 1-2. 구현 요약

- `schema/review_transition.py` — 표를 읽는 공개 함수만으로 **역해석**(`action_for_status_change`)하고, PATCH
  판정(`plan_review_field_change`)을 순수 함수로 둔다. 표를 두 벌 만들지 않는다.
- `api/problems.py::patch_problem` — 본문에 `review_status`가 있으면 `SELECT … FOR UPDATE`로 잠그고 최신
  값으로 판정한다. 불허는 409 `illegal_transition`, 격리 사유 부재는 422 `reason_required`, 격리 기록 변조는
  409 `quarantine_record_immutable`. 합법 전이는 감사 1행의 동작이 `update`가 아니라 전이 액션이다.
- 격리 시각은 서버 시계로 기록한다(클라이언트 값 무시) — 소급 격리 차단.
- 격리 사유는 **이번 요청 본문의 값**으로 판정한다. 병합 결과로 판정하면 과거 격리의 낡은 사유가 새 격리를
  통과시킨다(POST 경로는 매번 새 사유를 요구하므로 두 표면이 갈라진다).

### 1-3. "감사 1행" 해석 — 판단이 들어간 곳이다

인수조건 문장은 "전이표를 경유하거나 거부하고 감사 1행을 남긴다"이다. 나는 **합법 전이는 감사 정확히
1행, 거부는 감사 0행 + WARNING 로그**로 구현했다. 거부에도 감사 행을 남기는 읽기도 가능하다. 채택하지
않은 이유: `privacy_audit`의 `content_mutation`은 "변경이 일어났다"는 사실의 기록이고, 루프 KPI ④(운영자
수동 개입)가 이 종류 행 수를 센다(`docs/standards/loop_kpi_contract.md`). 거부를 같은 종류로 적으면
일어나지 않은 일을 원장이 말하고 KPI가 부풀려진다. 거부를 별도 `event_kind`로 적는 방법은 폐쇄
택소노미 확장(스키마·`GET /v1/me/privacy-audit` 응답·열거 테스트 파급)이 필요해 이 PR에서 하지 않았다.
**이 해석이 의도와 다르면 알려 달라** — 바꾸는 비용은 `ADMIN-17`과 같은 크기다.

### 1-4. 검증

- 신규 테스트 80건(API 44 · 스키마 36). 기존 관련 189건 무회귀.
- **결함 주입(뮤테이션) 12건 + 파일 추가형 1건** — 하네스는 순수 Python이고 주입 적용(`count==1`·
  `mutated != original`)과 원복(sha256 동일)을 실행 전후에 단언한다. 결과: 실제 주입 11건 전부 RED,
  대조군(자기 자신으로 치환) 1건 GREEN, 파일 추가형(API 계층에 새 `review_status` 작성기) 1건 RED.
  가장 핵심인 M1(판정기가 목표 상태를 못 봄 = ADMIN-16 이전 동작과 동치)은 **31건 실패**로 잡혔다.
- 한계: 실 PostgreSQL 위의 행 잠금·롤백은 이 환경에 PG가 없어 **돌리지 못했다**(§6).

## 2. 부수 ② — `privacy_audit` DB 불변 트리거 여부 판정

**판정: 필요하다. 이 PR에서는 구현하지 않고 `ADMIN-17`로 분리한다.**

### 사실 (범위: `src/`·`tests/`·`scripts/` 전체)

1. 불변성은 **관례**다. 모델 docstring이 "UPDATE/DELETE 라우터 없음"이라 적을 뿐 DB 장치가 없다 —
   alembic 마이그레이션에서 `CREATE TRIGGER`는 `problem_attempt`·`concept_version` 두 테이블에만
   있고 `privacy_audit`에는 **내가 찾은 방법으로는 0건**이며, `REVOKE`/`GRANT` SQL 문도 0건이다(grep에
   걸린 `revoked` 등은 컬럼명·주석이라 무관). 따라서 앱이 쓰는 DB 계정에 이 테이블 변경을 막는 권한
   제한이 없다고 읽는다.
2. `src/`에서 `privacy_audit`를 **쓰는 코드는 INSERT뿐**이다(6종 writer). ORM `update/delete(PrivacyAudit)`·
   raw SQL `UPDATE|DELETE|TRUNCATE privacy_audit` — **내가 찾은 방법으로는 0건**.
3. 보존·파기에서 **의도적으로 제외**돼 있다(`privacy/retention.py` ADMIN-03 · 보존 연한은 `MGMT-02` 변호사
   회신이 선행). 즉 합법적 삭제 경로가 지금 없다.
4. 반면 **테스트 픽스처 6곳**이 `DELETE FROM privacy_audit`으로 정리한다(실 PG 통합 테스트).
5. 코딩 헌법에 같은 방향의 규칙이 있다 — R23-01(이벤트 테이블 추가 전용·UPDATE/DELETE 차단, 5단계),
   R7-02(상태 전이를 DB가 허용, 5단계).

### 판정 근거

UPDATE 차단은 합법 경로가 0이라 위험이 없다. DELETE 차단도 지금은 합법 경로가 없지만 `MGMT-02` 이후
보존 파기 job이 생기면 승인된 예외 경로(트랜잭션 한정 GUC 등)가 필요하므로 설계에 넣어야 한다. 이
설계·마이그레이션·`KNOWN_REVISIONS`·prod 스키마 프로브·픽스처 6곳 변경은 PATCH 우회 폐쇄와 **다른 축**이고
PR 크기를 키운다 → 분리.

### 한계 (정직)

트리거는 DB 소유자·슈퍼유저가 끌 수 있다. **사고·앱 버그·SQL 주입 방지**이지 내부자 변조 방지가 아니다.
근본 방어는 앱 계정 권한 분리(`REVOKE UPDATE, DELETE`)다. 다만 로컬 compose 파일(`docker-compose.demo.yml`·
`docker-compose.pilot.yml`)이 `POSTGRES_USER: whymath` + `trust` 인증으로 DB를 띄우는 것은 확인했고,
도커 postgres 이미지에서 `POSTGRES_USER`로 만든 계정은 기본적으로 슈퍼유저이므로 권한 분리가 지금은
무의미할 것으로 **추정**한다 — 실제 계정의 권한은 **조회하지 않았다**. `ADMIN-17` acceptance ④에 한계로
적었다.

## 3. 부수 ③ — 반려코드(F1~F8)·HIT 타이머 강제

**판정: 이 PR에서 하지 않는다. `ADMIN-18`로 분리한다.**

### 사실

- `schema/review_timer.py`는 `rejected` ⇒ `failure_code` 필수를 **함수 수준에서만** 집행한다. 생산자는
  `harness/review_session` CLI 하나다.
- `POST …/transitions`의 `reject`는 `failure_code`를 받지 않고 `ReviewTimerEvent`도 쓰지 않는다.
  `ReviewTimerEvent.from_schema`의 `src/` 호출처는 **내가 찾은 방법으로는 0건**(`ops/weekly_metrics_report.py`
  주석도 같은 자인).

### 분리 근거

요청 필드 추가(API 계약 변경) + 웹 UI(F1~F8 선택·클라이언트 타이머) + HIT 계측 의미 변경이 한 덩어리다.
기존 웹 거버넌스 테스트가 UI를 고정하고 있어 서버만 먼저 강제하면 **현행 반려 버튼이 즉시 422로 깨진다**.

### 이 PR이 ADMIN-18에 남긴 것

ADMIN-16이 PATCH를 전이표에 연결했으므로, ADMIN-18이 반려코드를 POST에 강제하면 PATCH의
`pending→rejected`도 같은 코드를 실을 자리가 없다. `ADMIN-18` acceptance ④에 "PATCH의 `reject`는 거부하고 POST로
안내"를 적었다. **어떤 경로로도 타이머 없는 판정이 제출되지 않는다**는 문장은 그 태스크가 닫혀야 참이 된다.

## 4. 부수 ⑥ — 감사 action 열거 문서 동기화 (이 PR에서 완료)

`docs/standards/security_privacy.md`의 감사 의사 스키마가 4종에서 멈춰 있었다. 실제는 `event_kind` 6종 ·
`action` 7종(CRUD 3 + 전이 4) · `resource_type` 2종이다. 코드블록 주석을 6종으로 맞추고 열거 동기화 부기를
추가했다. 이 열거를 문서와 코드가 대조하는 테스트는 **없다**(전수 grep) — 드리프트가 다시 생기면 사람이
발견해야 하는 상태이며, 이는 이 PR이 고치지 않은 사각이다.

## 5. 조사 중 발견 (등재)

- **`ADMIN-19`** — `POST /v1/problems`가 `review_status=approved`로 직접 태어난 문항을 만들 수 있다
  (`ProblemCreateRequest`가 스키마 그대로). PATCH 우회와 같은 부류. 호출자 전수 조사가 선행이라 분리했다.
- **`ADMIN-20` (owner=kiki, 결정 사안)** — 전이표는 `approved`에서만 격리를 허용하는데 공개 카탈로그 GET은
  격리 문항**만** 숨긴다. 그래서 **pending·미설정·rejected 문항의 결함은 이제 어떤 관리자 API로도 공개
  카탈로그에서 숨길 수 없다**(이전에는 PATCH가 어느 상태에서든 격리로 보낼 수 있었다). EOS-97 리콜 도구의
  대상(새로 생성된 문항)이 `approved` 이전일 가능성이 높아 영향이 실제적일 수 있다. 세 선택지는 태스크에
  적었고, 전이표 변경이나 D1 공개 정책 변경이라 **세션이 정하지 않았다**.

## 6. 이 판정이 하지 않은 것 (정직한 공백)

1. **실 PostgreSQL 검증 없음.** 이 환경에는 PG·docker 데몬이 없다. 행 잠금(`FOR UPDATE`)이 실제로 전이
   라우트와 직렬화되는지, 감사 flush 실패 시 롤백이 되는지는 hermetic 가짜 세션으로 **인자와 호출 순서만**
   고정했다. 실 PG 통합 테스트는 추가하지 못했고 CI `backend-migrations` 잡이 첫 실행이 된다.
2. **상태가 그대로인 PATCH의 격리 기록 단독 편집은 막지 않았다.** 해제 시 사유에 근거를 덧붙이는 기존 절차
   (격리 계약 §5 해제 3항)가 이 경로를 쓴다. 계약 §7에 한계로 적었다.
3. **리콜 도구 영향은 문서로만 반영했다.** `approved`가 아닌 문항은 건별 409로 실패하며 도구는 이를 삼키지
   않고 보고한다(기존 동작). 도구 코드·테스트는 바꾸지 않았다.
4. **미설정 문항을 `pending`으로 편입하는 경로가 PATCH에서도 막힌다.** 표가 "미설정은 어떤 액션도 불허"로
   고정돼 있어(ADMIN-07) 같은 규칙이 적용된 결과다. 편입은 코퍼스 백필 도구의 몫이다.
