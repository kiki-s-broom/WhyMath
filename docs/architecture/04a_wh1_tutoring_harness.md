# WhyMath 튜터링 하네스(WH-1) 설계안 v0.3

> 하네스-1(UIUC·UC버클리·Chroma, arXiv 2606.02373)의 “상태 기반 인지 오프로딩” 구조를
> WhyMath 소크라테스 튜터링 엔진에 이식하는 설계안.
> **v0.2 변경**: 리스크 검토 반영 — 리스크 레지스터(§9) 신설, 0단계(평가 하네스) 추가,
> verify 탈출구·가설 탐색 규칙·fast path·개인정보 스키마 보강,
> §6 비용 절감과 §7 자체 학습을 “확정 효과”에서 “검증 필요 가설”로 강등.
> **v0.3 변경**: 전략 계층(§11) 신설 — 하네스를 “오류 교정기”에서
> “문제해결능력 성장 엔진”으로 확장. 전략 레퍼토리 상태, 힌트 경제(스캐폴딩 페이딩),
> 확신도 보정 루프, 전이 측정 설계. 도구 3종(#9~#11) 추가,
> 0단계 대리 지표 4종→7종 확장, 리스크 R14~R16 추가.
> 작성일: 2026-06-13 | 버전: 0.3

> **편집자 주 (저장소 정합, 2026-06-12)**: 원안 prose를 보존하되, 잠금된 기술 결정과의 정합을 위해
> 다음 표기를 교정했다 — ① **ChromaDB → pgvector**(4건; 2026-06-10 슬98: PostgreSQL 16 확장으로 벡터
> store 통합·별도 ChromaDB 폐기. 본문의 "신규 인프라 0" 주장은 store 1개 감소로 오히려 강화됨)
> ② **Mathpix OCR → PaddleOCR + Qwen3-VL**(§3.3 1건; 2026-05-28: 로컬 처리·미성년자 프라이버시. 본 문서
> §2.3/§11의 프라이버시 원칙과 정합). 현 구현 좌석과의 매핑은 문서 끝 "현 구현 매핑(편집자 부기)" 절 참조.

-----

## 0. 한 줄 요약

**LLM이 프롬프트 안에서 기억·진단·검증을 모두 하던 방식을 버리고,
외부 하네스가 “학생 상태·오개념 가설·증거”를 관리하며
LLM은 매 턴 “다음 교수학적 행동 판단”만 하는 도구 루프(agent loop)로 전환한다.**

단, 검색과 튜터링은 도메인 성격이 다르므로(§9 R1) 검증 가능한 단원부터
하이브리드로 도입하고, 효과는 0단계에서 정의한 대리 지표로 측정한다.

하네스-1의 검색 도메인 개념을 튜터링 도메인으로 번역하면:

|하네스-1 (검색)              |WH-1 (튜터링)                                          |
|------------------------|----------------------------------------------------|
|후보 문서 저장소               |세션 작업 메모리 (풀이 이력·행동 신호)                             |
|큐레이션 세트 (핵심 문서)         |**활성 오개념 가설 세트** (3~5개 후보 + 신뢰도 + 감쇠)               |
|증거 그래프 (인명·날짜 연결)       |**학습 증거 그래프** (오답 이벤트 → 오개념 → 커리큘럼 노드)              |
|verify (사실 검증)          |verify_step (SymPy 동치 검증 + PRM 점수 + unverifiable 상태)|
|웜 스타트 (1차 검색 결과 시드)     |CAT 진단 + 직전 세션 가설 + 단원 고빈도 오개념 프리로드                 |
|8개 전용 도구                |8개 튜터링 전용 도구 (§3) + 전략 도구 3종 (§11.3)                |
|end_search              |end_turn (질문/힌트/출제 중 택1로 턴 종료)                      |
|(하네스-1에 없음 — WH-1 고유 확장)|**전략 계층**: 전략 레퍼토리·힌트 경제·보정·전이 측정 (§11)             |

-----

## 1. 7계층 아키텍처 내 위치

하네스는 **새 계층이 아니다.** L3(콘텐츠 생성·검증)와 L4(교수학 엔진) 사이의
LLM 호출 방식을 바꾸는 **횡단 인프라**다. 계층 경계 원칙(상위→하위 호출만 허용)은 그대로 유지된다.

```
[현재]  L5 오케스트레이터가 L1·L2·L4 컨텍스트 수집
        → 거대 프롬프트 1개 조립 (프롬프트 스터핑)
        → LLM 1회 생성 → 응답

[WH-1]  L5 오케스트레이터가 하네스 세션 개시 (웜 스타트)
        → [fast path 판정: 풀이 제출 없는 단순 턴이면 루프 생략] (§5.3)
        → LLM이 도구 루프 진입:
           read_student_state → match_misconception → curate_hypothesis
           → verify_step → select_probe → ... → end_turn
        → 하네스가 상태 무결성 보장 + BKT 업데이트 큐에 커밋
```

핵심 차이: **상태(state)가 프롬프트 텍스트가 아니라 DB 레코드**가 된다.
LLM 컨텍스트에는 매 턴 “압축된 현재 상태 뷰”만 주입된다.

-----

## 2. 상태 저장소 설계 (Harness State)

기존 기술 스택(PostgreSQL 16 + TimescaleDB, pgvector, Redis 7)을 그대로 사용한다.
**신규 인프라 도입 없음.**

### 2.1 세션 작업 메모리 — Redis

- 키: `harness:session:{session_id}`
- 내용: 현재 문제 ID, 학생 풀이 단계 스택(최근 N개), Polya 단계, 힌트 레벨(0~3),
  verify 결과 캐시, 행동 신호(힌트 요청까지 시간, 지우개 횟수)
- TTL: 세션 종료 + 24h. **단, 웜 스타트에 필요한 미해결 가설은 TTL 만료 전
  PostgreSQL 스냅샷으로 영속화** (R7 대응 — Redis 휘발로 인한 연속성 단절 방지)

### 2.2 활성 오개념 가설 세트 — Redis + PostgreSQL 스냅샷

하네스-1의 “큐레이션 세트”에 해당. LLM이 임의로 늘리지 못하도록 **최대 5개 강제**.

```json
{
  "hypotheses": [
    {
      "misconception_id": "M-217",
      "label": "이차함수 a<0이면 그래프가 아래로 볼록이라고 착각",
      "confidence": 0.72,
      "last_supported_turn": 14,
      "evidence_refs": ["ev-1031", "ev-1045"],
      "status": "active"
    }
  ]
}
```

**확증편향 방지 규칙 (v0.2 신설, R4 대응):**

1. **시간 감쇠**: 가설 confidence는 새 지지 증거 없이 3턴 경과 시마다 ×0.85 감쇠.
   웜 스타트로 프리로드된 가설도 예외 없음 — 초기 가설이 영구 고착되는 것을 방지.
1. **ε-탐색 강제**: 5턴마다 1회, select_probe는 활성 가설 세트 *밖*의
   오개념(해당 노드에 태깅된 차순위 후보)을 겨냥한 문항을 의무 선택.
   하네스가 카운터를 관리하고 위반 시 probe 요청을 거부한다.
1. **반박 증거 우선 기록**: verify_step이 가설 예측과 모순되는 결과를 내면
   하네스가 자동으로 polarity=-1 증거를 기록 (LLM의 선택적 무시 차단).

### 2.3 학습 증거 그래프 — PostgreSQL

기존 `learning_events` 이벤트 소싱 테이블과 545노드 커리큘럼 그래프 **위에 엣지만 추가**한다.

```sql
-- 증거: 개별 학습 이벤트가 어떤 가설을 지지/반박하는지
CREATE TABLE evidence_links (
  link_id          BIGSERIAL PRIMARY KEY,
  session_id       UUID NOT NULL,
  student_id       UUID NOT NULL,            -- v0.2: 삭제권 연쇄 처리용 명시
  event_id         BIGINT REFERENCES learning_events(event_id) ON DELETE CASCADE,
  misconception_id TEXT REFERENCES misconceptions(id),   -- 400개 오개념 DB
  node_id          INT REFERENCES curriculum_nodes(id),  -- 545노드
  polarity         SMALLINT,      -- +1 지지, -1 반박
  weight           REAL,          -- verify/PRM 기반 가중치
  retention_until  DATE,          -- v0.2: 보존 기한 (기본 졸업+1년, 정책 설정)
  created_at       TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_evidence_student ON evidence_links(student_id);  -- 삭제권 행사 대비
```

이 테이블 하나로 “이 학생이 이차함수를 못 푸는 진짜 원인은 인수분해 노드”라는 진단이
LLM 추론이 아닌 **SQL 조회**로 나온다. 학부모 리포트의 신뢰 근거도 이것이다.

**개인정보 설계 원칙 (v0.2 신설, R11 대응):**

- 증거 그래프는 미성년자의 인지·행동 정밀 프로파일에 해당 →
  만 14세 미만은 법정대리인 동의를 가입 플로우에 통합 (개인정보보호법 §22의2)
- 삭제권 행사 시: student_id 기준 evidence_links → learning_events 연쇄 삭제
  (ON DELETE CASCADE + 배치 검증), BKT 상태 초기화, pgvector 임베딩 삭제까지 한 트랜잭션 단위로
- retention_until 경과 레코드는 야간 배치로 자동 파기
- 이 설계는 나중에 붙이기 어려우므로 **스키마 1차 마이그레이션에 포함** (선택이 아님)

> **구현됨 (2026-06-18·삭제권 오케스트레이션·마이그레이션 0)**: `whymath_backend/privacy/erasure.py`
> `erase_user(session, *, user_id)` — 한 사용자의 *모든* 학생-연결 데이터(증거·가설·BKT
> `concept_mastery_history`·IRT `ability_snapshot`·행동 로그 `attempt_event`·대화·세션·시도·기기·
> 토큰·동의 등 **17개 테이블 + user_profile**)를 **단일 트랜잭션**으로 영구 삭제(부분 삭제 0·commit은
> 호출자). **레포 FK 실태**(전수 조사): `evidence_links`만 user_profile FK `ON DELETE CASCADE`,
> 나머지는 NO ACTION FK(user 삭제 *차단*) 또는 느슨참조·hypertable(*고아 잔존*) → user_profile 한
> 행 삭제론 불충분 → **앱레벨 명시 삭제**(child→parent 순서·`_ERASURE_PLAN`)가 필요. FK 전부 CASCADE
> 대안은 대규모 마이그레이션 + 전역 오삭제 위험이라 배제(명시·감사 가능·마이그레이션 0 선택). 삭제
> 전 `DeletionAudit`(`resource_type="user_profile"`·콘텐츠 미저장) 적재 — user FK가 없어 *잔존*(GDPR
> 증빙·slice 57 동형).
>
> **요청 API (2026-06-18·`DELETE /v1/me`)**: `api/me.py` `erase_my_account` — 인증된 *본인만* 자기
> 계정을 삭제(`user_id`=토큰 subject). **CurrentUser**(동의 게이트 *아님*) — 미성년 동의 미설정자도
> *삭제*는 가능해야 한다(삭제권 우선·수집 동의와 무관). 오삭제 방지 **확인 문구**(`confirmation ==
> "DELETE_MY_ACCOUNT"`) 불일치 시 400. 200 *영수증*(user_id·총 삭제 행수만·내부 테이블 구조 비노출)·
> `erase_user`+commit 원자적. **후속**: 법정대리인 동의 *흐름*(미성년 가디언 승인)·외부 store
> (ClickHouse 행동로그·S3 객체·Redis 세션) 삭제 연계.
>
> **열람·이동권 (2026-06-19·`GET /v1/me/export`·삭제권의 짝·마이그레이션 0)**: `privacy/export.py`
> `export_user_data(session, *, user_id)`(읽기 전용·commit 0) — 삭제권의 `_ERASURE_PLAN` 인벤토리
> *학습/진단 subset*을 **읽기로 재사용**해 본인 데이터를 구조화 JSON으로 모은다. 첫 증분: 5종(학습
> 세션·시도·진단·`concept_mastery_history`·`ability_snapshot`) + `user_profile`(plan-driven 확장).
> **보안 항목 영구 제외**(`device_credential`·`refresh_token_session` — 토큰 노출 위험). 각 행은
> `to_schema().model_dump(mode="json")`. **부분 export 정직**: `not_included`로 미포함 범위(대화·
> 시계열·외부 store 등) 고지(날조 0·완전성). `api/me.py` `export_my_data`(**ConsentedUser**·다른
> /me GET 동형·per-user HTTP — 전역 집계 아님). 외부 store(ClickHouse·S3·Redis)는 RDB 밖이라
> `external_export_pending` 매니페스트를 **ops 로그**로만(store명·user_id·#252 선례·정보 누출 방지·
> student 응답 미노출). **증분 2(2026-06-19·#265)**: `_EXPORT_PLAN`에 동의·트랙·페르소나·상태 이력
> 4종(`parental_consent`·`user_track/persona_history`·`user_state_snapshot`·모두 `to_schema` 보유·
> `user_id` 키) 추가(순수 plan 확장·마이그레이션 0). **증분 3(2026-06-19)**: `_EXPORT_PLAN`에 **오개념
> 가설·진단 증거** 2종(`misconception_hypothesis`·user_id 키 / `evidence_links`·**student_id 키**) 추가.
> #269~272가 라이브 적재하므로 비어있지 않다. 두 모델에 `to_schema()`(+ `schema/` Pydantic 레코드)를
> 부여해 export 패턴(`to_schema().model_dump(mode="json")`)에 합류 — *식별자·극성·가중치·날짜*만이라
> PII 0·redaction 0(증거 그래프 §2.3)·마이그레이션 0(기존 테이블 읽기). **후속**: 대화/turn 조인(미성년
> 채팅 본문 privacy 결정)·시계열(대용량 async)·외부 store 실조회.
>
> **정정 (2026-09-07·SEC-32 — 위 두 증분의 "외부 store" 열거)**: 2026-06-18/19 판이 적은
> `ClickHouse 행동로그·S3 객체·Redis 세션`은 **실재 확인 없이 계획 스택을 그대로 옮겨 적은 것**이었다.
> 실측 결과 ClickHouse·S3는 이 저장소에 도입된 적이 없고(설정 키 0·compose 서비스 0·SDK 0), 정작
> 학생 요청마다 외부 SaaS로 트레이스를 보내는 **Langfuse**가 두 매니페스트에서 빠져 있었다 — 즉
> *없는 곳을 적고 있는 곳을 빠뜨린* 양방향 오류다. 현행 매니페스트는 **Redis(응답 캐시·큐 payload)·
> Langfuse(L3 라우팅 트레이스)** 2종이며, 선언↔실재 대조는 `tests/backend/_external_store_evidence.py`
> 계약이 강제한다(설정 키·compose 서비스를 실제로 조회 — 문자열 금지 목록이 아니다). 두 store 모두
> **현재 user 단위 키가 없다**는 사실도 locator에 명시했다(Redis 캐시 키=프롬프트 해시·Langfuse의
> `student_id_hash`는 서빙 경로 미주입) — "지울 수 있다"는 인상만 남는 체크리스트를 만들지 않기 위함.
> ClickHouse·S3를 실제로 도입하는 날 매니페스트·계약 상수를 함께 갱신한다.

### 2.4 장기 상태 — 기존 L2 그대로

BKT 숙달도 벡터는 변경 없음. 하네스가 `end_turn` 시 업데이트 큐에 푸시하고
비동기 워커가 갱신하는 기존 패턴 유지.

-----

## 3. 전용 도구 8종 명세

|#|도구                   |입력                                |출력                                               |담당 계층|
|-|---------------------|----------------------------------|-------------------------------------------------|-----|
|1|`read_student_state` |node_ids[]                        |BKT 숙달 확률, 오개념 이력, 정서 프록시                        |L2   |
|2|`verify_step`        |expr_before, expr_after, step_type|`correct` / `incorrect` / `unverifiable` + PRM 점수|L3   |
|3|`match_misconception`|학생 풀이 단계 텍스트                      |pgvector 검색 → 오개념 후보 top-5 + 유사도 + **품질 플래그**    |L2/L3|
|4|`curate_hypothesis`  |add/remove, m_id, evidence_refs[] |갱신된 가설 세트 (최대 5개·감쇠·ε-규칙 적용)                     |하네스  |
|5|`query_curriculum`   |node_id, relation(선수/후속/형제)       |관련 노드 + 숙달 확률 조인                                 |L1+L2|
|6|`select_probe`       |hypothesis_id 1~2개                |진단 문항 1개 (§3.2 근사 방식)                            |L4   |
|7|`log_evidence`       |event_id, m_id, polarity          |evidence_links 기록                                |하네스  |
|8|`end_turn`           |action(질문/힌트/출제/격려), payload      |학생에게 전달 + BKT 커밋                                 |L4→L5|

### 3.1 verify_step 3상태 설계 (v0.2 수정, R5 대응)

v0.1의 “verify 없이 end_turn 거부” 규칙은 검증 불가 단원에서 교착을 일으킨다. 수정:

- **3상태 반환**: `correct` / `incorrect` / `unverifiable`
- 식 변형(대수 연산): SymPy 동치 검증 → correct/incorrect
- 서술형 논증·증명·보조선 기하·경우 나누기: `unverifiable` 반환 + step_type 기록
- **강제 규칙 수정**: 풀이 단계 포함 턴은 verify_step *호출*은 의무이되,
  unverifiable이면 통과. 단, 그 턴의 evidence weight를 0.5로 할인하고
  세션 메타에 `unverified_ratio`를 누적 기록한다.
- **솔직한 한계 인정**: unverifiable 비율이 높은 단원(중학 기하 등)에서는
  환각 차단 보장이 부분적이다. 0단계에서 단원별 verify 커버리지를 측정해
  커버리지 70% 이상 단원부터 하네스를 켠다 (§8.4).
- PRM800K는 영어 GSM8K/MATH 분포 → 한국 교육과정 샘플 200문항으로
  오탐/미탐률 사전 측정 후 가중치 결정 (0단계 과제).

### 3.2 select_probe 현실화 (v0.2 수정, R6 대응)

“가설 A·B를 판별하는 전용 문항이 항상 존재”한다는 가정은 조합 폭발로 비현실적.
수정: 문제은행 문항에 오개념 태그(다중)를 부여하고, **정보 이득 근사** —
“가설 A 태그는 있고 B 태그는 없는 문항” 중 학생 숙달도 대비 적정 난이도 문항을
IRT 정보함수로 선택한다. 완전 판별이 아닌 근사임을 진단 신뢰도 표시에 반영
(가설 confidence 상한 0.9 — 시스템이 “확신”을 출력하지 않게).

### 3.3 match_misconception 품질 게이트 (v0.2 신설, R6 대응)

- 입력이 PaddleOCR+Qwen3-VL 산출물이면 OCR confidence < 0.8 시 `low_quality` 플래그 →
  LLM이 학생에게 재확인 질문을 하도록 유도 (오염된 매칭으로 가설 세우는 것 방지)
- 유사도 top-1 < 0.65면 “후보 없음” 반환 — 억지 매칭 금지
- **선결 조건**: 400개 오개념 항목당 예시 오답 최소 5개의 임베딩 적재.
  현재 DB의 예시 충족률을 0단계에서 감사(audit)하고 미달 항목은 합성 예시로 보충.

### 3.4 설계 원칙 (유지)

1. verify_step 호출 의무 (3상태로 완화, §3.1)
1. select_probe는 정보 이득 근사 (§3.2)
1. **end_turn만이 학생에게 말할 수 있다.** 중간 도구 호출은 전부 내부 동작.

> **v0.3**: 전략 계층 도구 3종(#9 log_strategy_event, #10 elicit_prediction,
> #11 assign_transfer_probe)이 추가됨 — 명세는 §11.3 참조.

-----

## 4. 웜 스타트 (Warm Start)

세션 시작 시 하네스가 LLM 개입 없이 자동 구성:

1. **CAT/진단고사 결과** → 해당 단원 노드들의 BKT 사전확률 시드
1. **직전 세션의 미해결 가설** (PostgreSQL 스냅샷에서 복원, §2.1)
1. **해당 단원의 모집단 고빈도 오개념 top-3** — 단, §2.2 감쇠 규칙 적용 대상.
   프리로드 가설은 confidence 0.4로 시작(겸손한 사전확률)하여 고착 방지.

→ LLM은 첫 턴부터 “백지 진단”이 아니라 **“초안 검증·보완”**으로 시작한다.
체감 효과는 “선생님이 지난 시간 내용을 기억하고 있다”는 연속성 경험이다.

-----

## 5. 루프 제어·압축 (하네스 자동 담당)

### 5.1 압축 — 무손실 원칙 (v0.2 수정, R8 대응 / **2026-07-29 편집자 부기로 강등**)

v0.1의 “요약 압축”은 오개념을 드러내는 학생의 정확한 표현
(“음수를 빼면 더 작아지잖아요”)을 유실할 위험. 수정:

- **원문은 절대 삭제하지 않는다.** 10턴 초과 시 원문을 컨텍스트에서만 제외하고
  PostgreSQL에 보존 — ~~`recall_dialogue(turn_range)` 보조 도구로 LLM이 재조회 가능~~
  **(강등, 2026-07-29): 원문 재조회 도구는 만들지 않는다.** 회상은 **구조화 메타
  한정**(턴 인덱스·전략·이해도 신호 — 원문 0·복호 0)으로 축소한다. 근거:
  ① 미성년자 대화 평문 노출 최소화(SEC-01 봉투 암호화)와 정면 충돌 — 재조회 도구가
  암호화 봉투를 열어 원문을 LLM 프롬프트에 넣는 경로가 되므로 "본문은 at-rest
  암호화"의 실효를 무력화한다. ② `harness/wh1_llm_policy.py`의 "학생 원문·정답은
  사적 필드" 격리가 WH-1 primary GA(2026-07-20, `wh1_primary_enabled` 기본 True)로
  더 강해짐 — 그 GA 불변식과 이 도구가 공존할 수 없다. ③ 컨텍스트 오염·예산 가드
  (`_MAX_PROMPT_TOKENS=3000`)와도 상충. 정합 설계는
  `docs/architecture/ai_tutor_module_gap_review.md §2-⑤·§3 D1`(`recall_session_context`
  — 원문 미복호를 테스트로 동결) 참조. 원문 복원이 필요한 경우(교사·연구 감사)는
  이 하네스의 도구가 아니라 별도 축(L7·복호 권한 분리)에서 재론한다(같은 문서 §5-⑥).
  **✅ 구현 완료(2026-08-03, `PED-04`)**: `l4/session_recall.py::SessionRecall`(필드
  전부 enum/id/정수 — 원문을 실을 자리가 타입상 없음) + `api/coach.py::_session_recall_or_none`
  (컬럼 투영·복호 함수 호출 0을 통합테스트로 동결) + `wh1_llm_policy.py`가 예산 초과 시
  회상을 **최우선 절단**(세션 간 맥락은 이번 턴에 가장 덜 급함).
- 컨텍스트에는 하네스가 만든 구조화 인덱스(턴 번호, 이벤트 유형, 가설 변화)만 유지
- 반박된 가설(confidence < 0.2): archived 전환, 증거 그래프엔 보존

### 5.2 루프 가드 (v0.2 신설, R2 대응)

- 턴당 도구 호출 상한 8회 — 초과 시 하네스가 강제 end_turn(안전 응답: 단계 확인 질문)
- 동일 도구 동일 인자 2회 반복 → 거부 + 경고 주입 (thrashing 차단)
- 도구 호출 JSON 스키마 검증 실패 2회 연속 → 해당 턴을 클라우드 모델로 폴백

### 5.3 Fast Path (v0.2 신설, R9 대응)

풀이 제출이 없는 턴(인사, “네”, 격려 요청, 단순 진행 확인)은 하네스가 사전 분류해
도구 루프 없이 경량 생성으로 즉답. 풀이 포함 턴만 풀 루프를 돈다.
→ 평균 체감 레이턴시를 낮추고, “생각 중…” 스트리밍 UI는 풀 루프 턴에만 표시.

-----

## 6. 모델 라우팅 — 【검증 필요 가설】 (v0.2 강등, R2 대응)

v0.1은 “Qwen3 로컬 판단 루프”를 기대 효과로 적었으나, 하네스-1의 성능은
**하네스 환경에서 학습된 모델**의 결과다. 학습 없는 기성 모델의 도구 호출
신뢰성은 미검증이므로 다음 3단계로 강등한다:

|단계    |판단 루프                          |조건                                |
|------|-------------------------------|----------------------------------|
|A (출시)|Claude Haiku                   |즉시 가능, 비용 중간                      |
|B (검증)|Qwen3-Math 로컬 (Phaiakes9) 섀도 모드|Haiku와 병렬 실행, 도구 호출 일치율 ≥ 90% 달성 시|
|C (전환)|Qwen3 주력 + Claude 에스컬레이션       |B 통과 + §7 SFT 완료 후                |

최종 소크라테스 질문 문장 생성은 전 단계에서 Claude API(짧은 호출) 유지.
**비용 절감은 C단계 도달 시에만 실현되는 가설이며, A단계만으로도
긴 세션 품질·설명 가능 진단이라는 효과는 독립적으로 성립한다** — 이것이
하네스 도입의 1차 정당화이고, 비용 절감은 2차다.

-----

## 7. 자체 모델 학습 경로 — 【검증 필요 가설】 (v0.2 강등, R1·R10 대응)

하네스-1 레시피의 직접 이식에는 두 가지 장벽이 있다:

1. **보상 신호 부재 (근본 장벽)**: 검색은 리콜이라는 객관 보상이 있지만,
   “좋은 소크라테스 질문”은 자동 채점 불가. RL 이전에 보상 모델 설계가 별도 과제.
   현실적 대안: (a) 대리 보상 — verify 통과율·가설-실제 일치율·세션 완주율 합성,
   (b) RLHF-lite — 주간 100개 turn 샘플에 본인이 직접 rubric 채점한 선호 데이터.
   둘 다 “노이즈 있는 보상”이므로 RL은 SFT 효과 확인 후로 보류.
1. **약관**: 상용 모델(Claude) 출력으로 자체 모델을 학습시키는 것은
   Anthropic 이용약관의 학습 제한 조항 검토 선행 필수. 위반 소지가 있으면
   교사 모델을 오픈 가중치 대형 모델(예: 하네스-1 자체, Qwen 대형)로 대체.

조건이 충족되면: 교사 모델 trajectory ~1,000개 → Qwen3-Math SFT.
하네스-1이 899개로 충분했다는 점은 여전히 유효한 희망적 근거이나,
**검증 가능 도메인의 결과를 교수학 품질로 외삽한 것**임을 명시해 둔다.

-----

## 8. 현재 WhyMath 시스템과의 차이 분석

### 8.1 무엇이 바뀌는가

|측면      |현재 (프롬프트 스터핑)          |WH-1 적용 후                        |
|--------|-----------------------|---------------------------------|
|학생 상태   |프롬프트 안 텍스트, 턴마다 재조립, 휘발|외부 DB 레코드, 명시적·감사 가능             |
|오개념 진단  |LLM의 턴별 즉흥 추론 (재현 불가)  |가설 세트 + 증거 링크 (설명 가능, SQL 조회)    |
|긴 세션 품질 |컨텍스트 비대 → 일관성 붕괴       |하네스 압축 → 30턴에도 일정 품질             |
|풀이 검증   |LLM 자가 판단 의존 (환각 위험)   |verify_step 의무 호출 (커버리지 한계는 §3.1)|
|모델 의존성  |대형 모델 필수               |단계적 경량화 (§6, 가설)                 |
|단원 확장   |단원별 프롬프트 튜닝 필요         |도구 사용법은 단원 불변 → 일반화 기대           |
|API 비용  |턴당 거대 컨텍스트 호출          |A단계: 소폭 개선 / C단계: 구조적 절감 (가설)    |
|학부모 리포트 |LLM 생성 요약              |증거 그래프 직접 시각화 (근거 제시)            |
|물리/화학 확장|튜터 프롬프트 재설계            |하네스 재사용 + 도메인 도구만 교체             |

### 8.2 무엇이 바뀌지 않는가 (기존 자산 보존)

- **7계층 경계 원칙**: 그대로. 하네스는 L3/L4 구현 방식 변경이지 계층 재편이 아님
- **545노드 그래프, 400개 오개념 DB, CSAT 55+108 패턴**: 하네스 상태 저장소의 재료
- **learning_events 이벤트 소싱**: evidence_links가 위에 조인되는 구조라 무변경
- **기술 스택**: PostgreSQL/pgvector/Redis/Ollama 전부 기존 그대로

### 8.3 새로 감수하는 비용

1. **레이턴시**: 풀 루프 턴 2~5초+ (낙관 추정). 완화: fast path(§5.3), 도구 병렬화, 웜 스타트
1. **엔지니어링 복잡도**: 사실상 분산 시스템. Langfuse 추적을 0단계에 선행 구축 (§8.4)
1. **로컬 모델 신뢰성**: §6의 3단계 게이트로 관리

### 8.4 수정된 도입 로드맵 (v0.2 — 0단계 신설)

|단계          |작업                                                                                                                                                                                                   |산출물 / 게이트                          |
|------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------|
|**0단계** (신설)|① 평가 하네스: 대리 지표 **7종** 정의·계측 (verify 통과율, 진단-실제 오개념 일치율, 세션 완주율, 턴당 토큰 + **도움 감소 곡선 기울기, 보정 점수, 전이 점수** — §11.6) ② 단원별 verify 커버리지 측정 ③ 오개념 DB 예시 충족률 감사 ④ Langfuse 추적 구축 ⑤ PRM800K 한국 문항 200개 오탐률 측정|커버리지 맵 + 베이스라인 수치 (이것 없이는 효과 주장 불가)|
|1단계         |verify_step + match_misconception 2개 도구를 기존 파이프라인에 삽입                                                                                                                                                |verify 커버리지 ≥ 70% 단원에서만 활성         |
|2단계         |활성 가설 세트(감쇠·ε-규칙) + evidence_links (개인정보 스키마 포함)                                                                                                                                                     |진단-실제 일치율이 베이스라인 대비 유의 개선          |
|3단계         |전체 도구 루프 + 웜 스타트 + fast path. 판단 루프는 Claude Haiku (§6 A단계)                                                                                                                                           |세션 완주율·30턴 품질 A/B                  |
|4단계         |(가설) Qwen3 섀도 → 전환 (§6 B·C단계), trajectory 수집 → SFT (§7)                                                                                                                                              |도구 호출 일치율 ≥ 90%, 약관 검토 통과          |

**적용 범위 원칙**: verify 가능한 대수 연산 중심 단원부터 켜고,
기하·서술형은 기존 방식과 병행하는 하이브리드 운영. 전 단원 일괄 전환은 하지 않는다.

-----

## 9. 리스크 레지스터 (v0.2 신설)

|ID |리스크                                                           |심각도|가능성  |대응 (설계 반영 위치)                                          |
|---|--------------------------------------------------------------|---|-----|-------------------------------------------------------|
|R1 |검색≠튜터링: RL 보상 신호 부재, +17%p 일반화 외삽 불가                          |높음 |높음   |§7 강등, 대리 보상 설계, RL 보류                                 |
|R2 |기성 로컬 모델의 도구 호출 신뢰성 미검증 (하네스-1은 학습된 모델)                       |높음 |높음   |§6 3단계 게이트, §5.2 루프 가드·폴백                              |
|R3 |논문이 동료심사 전 프리프린트, 자체 평가                                       |중간 |—    |아키텍처 베팅 최소화: 점진 이식 + 0단계 자체 측정                         |
|R4 |가설 세트 확증편향 고착 (웜 스타트 프리로드의 자기실현)                              |높음 |중간   |§2.2 감쇠·ε-탐색·반박 증거 자동 기록                               |
|R5 |verify_step 교착 (서술형·증명·기하 검증 불가) + PRM 분포 차이                  |높음 |확실   |§3.1 3상태, 커버리지 게이트, 0단계 오탐률 측정                         |
|R6 |match_misconception 오염 (OCR 노이즈, 표면 유사≠인지 원인) / probe 문항 조합 폭발|중간 |중간   |§3.3 품질 게이트, §3.2 정보 이득 근사 + confidence 상한             |
|R7 |상태 무결성: Redis 휘발, 비동기 경쟁 조건, 세션 복구                            |중간 |중간   |§2.1 PostgreSQL 스냅샷, end_turn 단일 커밋 지점                 |
|R8 |압축 손실 — 진단 단서가 되는 학생 원문 표현 유실                                 |중간 |중간   |§5.1 무손실 원칙(원문 PostgreSQL 보존) + **구조화 메타 회상**(2026-07-29 강등 — 원문 재조회 도구 대신 `recall_session_context`, `ai_tutor_module_gap_review.md §3 D1`) |
|R9 |레이턴시 — 단순 턴까지 풀 루프, 학생 이탈                                     |중간 |높음   |§5.3 fast path, 병렬 호출, 스트리밍 UI                         |
|R10|효과 측정 불가 — 학습 성과 A/B는 수개월, 인프라만 짓고 효과 모름                      |높음 |높음   |§8.4 0단계 대리 지표 선행 (게이트 조건화)                            |
|R11|미성년자 행동 프로파일링 — 동의·보존·삭제권 미비 시 법적 리스크                         |높음 |낮음~중간|§2.3 스키마 단계 내장 (동의 플로우·retention·연쇄 삭제)                |
|R12|1인 운영 복잡도 — 도구 루프 디버깅 불가                                      |중간 |높음   |0단계 Langfuse 선행, 루프 가드 로그 표준화                          |
|R13|Claude 출력 기반 학습의 약관 저촉                                        |중간 |중간   |§7 약관 검토 선행, 오픈 가중치 교사 모델 대안                           |
|R14|전략 태깅의 비검증성 — LLM 추론 의존이라 오개념(verify 가능)보다 노이즈 큼              |중간 |높음   |§11.1 증거 가중치 하향·관찰 횟수 기반 갱신, strategy confidence 상한 0.7|
|R15|지표 왜곡 행동 — 힌트 회피를 위한 방치·찍기 등 측정 게이밍                           |중간 |중간   |§11.2 도움 감소를 정답률 유지와 결합 판정, 이탈·무작위 응답 신호 교차 검증         |
|R16|예측 요구의 UX 마찰 — 확신도 질문 피로로 이탈                                  |낮음 |중간   |§11.3 elicit_prediction 세션당 2회 상한, 원탭 이모지 UI           |

-----

## 10. 종합 판단 (v0.2)

- 하네스의 **1차 가치는 비용 절감이 아니라**: ① 설명 가능한 진단(증거 그래프),
  ② 긴 세션 품질(상태 외부화+압축), ③ 구조적 검증(verify 의무화). 이 셋은
  Claude Haiku 판단 루프(A단계)만으로 성립한다.
- 비용 절감(§6 C단계)과 자체 모델(§7)은 **검증 필요 가설**로 관리하고,
  게이트(도구 호출 일치율 90%, 약관 검토)를 통과해야만 진행한다.
- 모든 단계 진입은 0단계에서 정의한 대리 지표의 베이스라인 대비 개선을 조건으로 한다.
  “측정 없는 도입 없음”이 v0.2의 제1원칙이다.
- **v0.3**: 전략 계층(§11)은 하네스를 “오류 교정기”에서 “문제해결능력 성장 엔진”으로
  확장한다. 성장 판정은 **도움 감소 곡선(행동 증거)과 전이 점수(성과 증거) 두 축**으로 하며,
  둘 다 종단 지표이므로 단기 A/B로는 검증 불가함을 명시한다.

-----

## 11. 전략 계층 (Strategy Layer) — v0.3 신설

> **목적**: 오개념 교정(§2~§3)은 도메인 내 숙달을 견인하지만, 문제해결능력
> (낯선 문제에서의 표상 선택·전략 수립·우회)의 지속 상승까지 보장하지 않는다.
> ITS 연구의 일관된 한계가 근전이는 강하고 원전이는 약하다는 것(VanLehn 2011 등).
> 전략 계층은 이 격차를 겨냥한 WH-1 고유 확장으로, 하네스의 상태 관리 능력이
> 있어야만 가능한 설계다 (프롬프트 스터핑 방식에서는 종단 추적 자체가 불가).

### 11.1 전략 레퍼토리 상태 (Strategy Repertoire State)

오개념 가설 세트(§2.2)와 나란히, “이 학생이 보유한 문제해결 휴리스틱”을 추적한다.

**휴리스틱 노드 사전 (~20종, Polya·Schoenfeld 분류 기반):**
거꾸로 풀기(working backwards), 특수화/일반화, 그림·표 그리기(표상 전환),
보조선 도입, 경우 나누기, 패턴 찾기, 변수 도입, 대칭 활용, 극단값 검사,
단순한 문제로 환원, 반례 탐색, 식↔그래프 전환, 검산 습관, 조건 재진술 등.

```sql
-- 전략 노드 사전 (545 커리큘럼 노드와 별도 차원)
CREATE TABLE strategy_nodes (
  strategy_id   TEXT PRIMARY KEY,      -- 'S-03' 등
  name_ko       TEXT NOT NULL,         -- '거꾸로 풀기'
  polya_stage   SMALLINT,              -- 주 발현 단계 (1~4)
  description   TEXT
);

-- 전략 증거 (evidence_links와 동형, 단 가중치 체계가 다름)
CREATE TABLE strategy_evidence (
  link_id      BIGSERIAL PRIMARY KEY,
  student_id   UUID NOT NULL,
  event_id     BIGINT REFERENCES learning_events(event_id) ON DELETE CASCADE,
  strategy_id  TEXT REFERENCES strategy_nodes(strategy_id),
  source       TEXT,    -- 'llm_tag' | 'polya_transition' | 'tool_interaction' | 'self_correction'
  weight       REAL,    -- llm_tag는 상한 0.5 (R14: 추론 의존이라 노이즈 큼)
  created_at   TIMESTAMPTZ DEFAULT now()
);
```

**학생별 strategy_mastery**: BKT 유사 보유 확률. 단 오개념과의 결정적 차이 —
전략 사용은 verify로 직접 검증 불가하므로 **confidence 상한 0.7**, 갱신은
관찰 횟수 기반(단일 강한 증거보다 반복 관찰 우선).

**증거 소스 4종:**

1. Polya 단계 전환 로그 (계획 단계에서 머문 시간, 단계 회귀 패턴)
1. 풀이 텍스트의 전략 태그 — LLM 추론 (`source='llm_tag'`, 노이즈 명시)
1. 그래핑 계산기 등 탐구 도구 조작 (식↔그래프 전환 신호 — 기존 설계의 조작 로그 환류와 결합)
1. 자기 교정 이벤트 (지우개 후 다른 접근으로 전환 = 전략 전환 능력의 직접 증거)

### 11.2 힌트 경제 — 스캐폴딩 페이딩 (Scaffolding Fading)

생산적 어려움(productive struggle)을 보호하고, 도움 의존도를 의도적으로 줄인다.

**상태**: 학생×노드별 `hint_economy = {time_to_first_hint, hints_per_problem, unaided_success_rate}`

**정책 (하네스가 구조적으로 강제):**

1. **개입 금지 타이머**: 학생 수준별 최소 자력 시간(예: 중3 기본 90초, 심화 180초)
   경과 전에는 LLM이 힌트성 end_turn 불가 — 격려·관찰 질문만 허용.
   하네스가 타이머를 관리하므로 LLM의 “친절 본능”이 구조적으로 차단된다.
   단, 정서 가드레일(연속 오답 + 이탈 신호 감지) 발동 시 타이머 해제.
1. **페이딩 스케줄**: 동일 노드 재방문 시 힌트 레벨 상한을 세션마다 한 단계씩
   하향 (3→2→1→0). 학생이 상한 0에서 unaided_success를 기록하면 해당 노드 졸업.
1. **핵심 지표 — 도움 감소 곡선**: 시간축에서 (힌트/문제) 감소 & 정답률 유지가
   동시에 성립할 때만 개선으로 판정 (R15: 힌트 회피만으로는 인정 안 함.
   방치·무작위 응답 신호와 교차 검증).

### 11.3 추가 도구 3종 (#9~#11)

|# |도구                     |입력                                       |출력/효과                                        |사용 규칙                        |
|--|-----------------------|-----------------------------------------|---------------------------------------------|-----------------------------|
|9 |`log_strategy_event`   |event_id, strategy_id, source, confidence|strategy_evidence 기록                         |llm_tag는 weight 상한 0.5       |
|10|`elicit_prediction`    |problem_id 또는 step_id                    |학생 UI에 “맞을 것 같아? (1~5)” 원탭 질문 트리거 → 보정 데이터 수집|**세션당 최대 2회** (R16 UX 마찰 관리) |
|11|`assign_transfer_probe`|pattern_id, surface_constraints          |CSAT 패턴 동일·표면 상이 문항 출제                       |주간 1회 자동 스케줄 + 노드 숙달 2주 후 트리거|

### 11.4 확신도 보정 루프 (Calibration Loop)

메타인지 향상의 검증된 개입 — WhyMath의 “왜” 철학과 직결.

1. verify_step 실행 *전*에 elicit_prediction으로 학생 예측(확신 1~5) 수집
1. 예측 vs verify 결과 → Brier score 류 **보정 점수** 산출, 종단 추적
1. **과신 구간**(틀렸는데 확신 5): 소크라테스 질문 강도 상향 — “왜 그렇게 확신해?”
1. **과소신 구간**(맞았는데 확신 1): 성취 명시 피드백 — 효능감 회복
1. 학부모 리포트에 “자기 평가 정확도” 항목 신설 — 점수 외 성장 지표 제공

### 11.5 전이 측정 — CSAT 패턴 자산 활용

문제해결능력 상승의 **직접 성과 측정치**. 기존 자산(시그니처 패턴 55종 + 하위 108종)이
정확히 이 용도에 들어맞는다.

- **정의**: 학습한 패턴과 심층 구조는 동일하되 표면(소재·숫자·맥락)이 다른
  초견 문항의 정답률 = **전이 점수(transfer score)**
- **출제 주기**: 노드 숙달(BKT ≥ 0.95) 도달 2주 후 자동 출제 — 간격 반복 효과 겸용
- **판정 프레임**: 도움 감소 곡선(행동 증거) × 전이 점수(성과 증거) 두 축.
  둘 다 상승 → 문제해결능력 성장 / 절차 점수만 상승·전이 정체 → “교정기 함정”
  경보로 전략 계층 개입 비중 상향

### 11.6 0단계 대리 지표 확장 (4종 → 7종)

기존 4종(verify 통과율, 진단 일치율, 세션 완주율, 턴당 토큰)에 추가:
**⑤ 도움 감소 곡선 기울기 ⑥ 보정 점수 ⑦ 전이 점수**.
⑤~⑦은 종단 지표이므로 베이스라인 수집 기간을 최소 4주로 설정한다.

### 11.7 전략 계층의 한계 (정직한 명시)

1. 전략 태깅은 LLM 추론 의존 → 오개념(verify 가능)보다 본질적으로 노이즈가 크다.
   confidence 상한 0.7과 관찰 횟수 기반 갱신은 완화책이지 해결책이 아니다.
1. 효과 검증은 전이 점수의 종단 개선으로만 가능 — 단기 A/B로는 증명 불가.
   따라서 전략 계층의 ROI 판정은 도입 후 최소 1분기를 요한다.
1. 끈기·효능감 같은 정의적 측면은 행동 프록시의 한계 내에서만 포착된다.
   설문 기반 정의적 진단(AskMath류)과의 결합은 별도 검토 과제.

-----

## 참고

- 하네스-1 논문: arXiv 2606.02373 (Stateful Search Harness)
- 코드/가중치: github.com/pat-jj/harness-1, huggingface.co/pat-jj/harness-1 (Apache 2.0)
- 기사: AI타임스 2026-06-09, “20B로 GPT-5.4 검색 성능 능가”
- 변경 이력: v0.1 (2026-06-13 초안) → v0.2 (리스크 검토 반영) → v0.3 (전략 계층 신설)
-----

## 현 구현 매핑 (편집자 부기, 2026-06-12)

> 본 설계안은 *목표 상태*다. 아래 표는 현재 백엔드 구현 좌석과의 연결·델타를 정리한다(추적용).

|설계안 좌석                         |현 구현 (가동 중)                                                                 |델타·비고                                            |
|-------------------------------|---------------------------------------------------------------------------|-------------------------------------------------|
|`read_student_state`(BKT·오개념·정서)|L2 `concept_mastery_history`(BKT)·`get_current_mastery`·`compute_concept_diagnoses`|정서 프록시 미구현                                       |
|`match_misconception`(pgvector top-5)|L4 오개념 의미 매처(slice104+·pgvector `misconception` 임베딩)                          |카탈로그 **30종**(설계안 "400"=목표·§3.3 audit으로 보강)         |
|`query_curriculum`(선수/후속)       |`concept_edge` PREREQUISITE + `fetch_prerequisites`(재귀 CTE·다단계)              |후속/형제 EdgeType은 후속 확장(현 데이터 전량 prerequisite)       |
|`curate_hypothesis`/`select_probe`|L4 `hypothesis.py`+`hypothesis_store.py`(`curate_hypothesis`)·`probe_selection.py`(`select_probe`·정보이득·ε-탐색)·`evidence_links`(가동)|둘 다 순수 로직 구현(`curate_hypothesis` 증거 반박·캡·`select_probe` 판별 태깅·ε)·문항 태그 스키마·ε 카운터 영속·coach 결선은 후속|
|`end_turn` 코칭 결정               |L4 `recommend_coaching`·`recommend_prerequisite_coaching`·`GET /v1/me/.../coaching`·`/v1/coach/sessions`|§11.2 힌트 경제(개입 금지 타이머)는 이 코칭 결정의 *집행 런타임*       |
|상태 저장소                        |PostgreSQL 16·Redis 7 (가동)·**벡터=pgvector**                                  |`evidence_links`·`strategy_*`는 향후 alembic 마이그레이션 |
|커리큘럼 노드                       |개념그래프 **403개념**(`concept` code=UC)·NCIC 성취기준                                |설계안 "545노드"와 용어·수치 정합 필요                         |

미구현 테이블(`evidence_links`·`strategy_nodes`·`strategy_evidence`)은 *향후 스키마*다 — 구현 시 alembic 마이그레이션과 §2.3 개인정보 설계(14세 미만 동의·retention·삭제권 연쇄)를 1차에 포함한다. 본 하네스 도입은 ROADMAP상 **0단계(평가 하네스)·verify_step·match_misconception은 Phase 1~2, 전체 도구 루프·전략 계층·자체 모델 학습은 Phase 2~3**으로 단계화한다(1인 capacity 가드·"측정 없는 도입 없음").

### `evidence_links` 스키마 — 실제 테이블 매핑 (편집자 부기)

§2.3의 `evidence_links` DDL은 *설계 시점 추상 스키마*다. 구현 시 실제 backend 테이블에 맞춘다(`learning_events`·`curriculum_nodes` 신설 불요):

|설계 DDL 참조                                       |실제 테이블 (현 backend)                                                       |정합 메모                                                          |
|------------------------------------------------|-----------------------------------------------------------------------|---------------------------------------------------------------|
|`event_id BIGINT REFERENCES learning_events(event_id)`|**`attempt_event`**(BIGSERIAL `event_id` + `event_at` **복합 PK**·TimescaleDB hypertable)|`learning_events` 테이블 *미존재* → `attempt_event`로. 복합 PK라 FK는 (event_id, event_at) 또는 대리키 필요(hypertable 제약)|
|`misconception_id TEXT REFERENCES misconceptions(id)`|오개념 카탈로그 TEXT id(kebab-case)·`misconception_embedding(misconception_id TEXT PK)`|TEXT 일치 ✓·카탈로그 현 **30종**(설계 "400"=목표)                          |
|`node_id INT REFERENCES curriculum_nodes(id)`     |**`concept(concept_id UUID PK·code=UC TEXT)`**                         |`curriculum_nodes(INT)` *미존재* → `concept.concept_id`(UUID) 또는 `concept.code`(UC). **INT→UUID/TEXT 형 변경**|
|`student_id UUID`                                |`user_profile.user_id`(UUID)                                           |명칭만 다름(student_id≈user_id) ✓                                  |

`evidence_links`는 *신규 테이블*이되 FK 타깃을 위 실제 테이블로 정정해 마이그레이션한다.

**구현됨(2026-06-17·마이그레이션 `b3c4d5e6f7a8`)**: `db/models/evidence_link.py` `EvidenceLink`(테이블 `evidence_links`·BIGSERIAL `link_id`). 위 매핑 정정 적용 — `student_id` **FK `user_profile.user_id` ON DELETE CASCADE**(★삭제권 연쇄·1차 마이그레이션 포함)·`event_id` BIGINT **느슨참조**(attempt_event 복합 PK라 단일 FK 불가)·`misconception_id` TEXT(인코드 카탈로그·스토어 `CATALOG_BY_ID` 대조·FK 아님)·`node_id` TEXT 느슨참조(concept_id)·`polarity` SMALLINT **CHECK ∈ {−1,+1}**·`weight`·`retention_until`(보존 배치 파기). 저장소+게이트 `l4/misconception/evidence_store.py`: `log_evidence`(카탈로그·극성 게이트 — 거짓 증거 차단)·`get_evidence_for_student`/`_misconception`·`net_support`(Σ polarity×weight — §2.3 *SQL 진단 신호*)·`purge_expired`(retention 야간 배치).

**구현됨(2026-06-17·마이그레이션 0 — 기존 테이블 재사용)**: `curate_hypothesis`(`l4/misconception/hypothesis_store.py`). 순수 `curate`(`hypothesis.py` — `update_hypotheses` + **반박 제거** + **최대 5 캡**·§2.2) 위에, 후보 오개념(현재 활성 가설 ∪ 새 매치)별 `evidence_store.net_support`를 조회해 *음수(반박 우세)면 archived*하고(§5.1·R4 확증편향 방지 — 반박이 LLM 추론 아닌 증거 그래프 SQL 집계) 최대 5개로 캡한 활성 세트를 `_persist_active_set`(upsert + 탈락 비활성화)으로 영속한다. `apply_matches`(매치만 반영)와 영속 헬퍼 공유(중복 0). **후속**: coach/intervention 결선(`curate_hypothesis`→개입 발화)·`select_probe`(ε-탐색 문항)·단일 트랜잭션 삭제 오케스트레이션(BKT·pgvector 동반).

### 용어·수치 정합: "545 노드" → 구현 403 개념

본문의 "545노드 커리큘럼 그래프"는 *설계 시점 추정치*이며 현 저장소에 해당 실체가 없다(레포 grep 결과 "545"는 본 문서 외 0). 구현된 커리큘럼/개념 계층은 **개념그래프 v1 — 403 개념(`concept`·code=UC) + 541 선수엣지(`concept_edge` PREREQUISITE)** + NCIC 성취기준이다. 성취기준 노드를 별도 차원으로 둘 경우 수치를 실측으로 확정한다("545"는 미반영 추정치).

### 도구 11종 → 실제 좌석 1:1 매핑 (편집자 부기)

§3(8종)·§11.3(전략 3종)의 도구를 *현 backend 좌석*에 매핑한다. 상태: 🟢 가동 · 🟡 부분 · 🔴 미구현.

|# |도구                   |계층    |실 구현 좌석 (현 backend)                                                                                       |상태                                             |
|--|---------------------|------|--------------------------------------------------------------------------------------------------------|-----------------------------------------------|
|1 |`read_student_state` |L2    |`get_current_mastery`(BKT)·`compute_concept_diagnoses`(BKT+IRT)·`get_current_theta`/`compute_concept_abilities`(θ)·`concept_mastery_history`|🟡 정서 프록시 미구현                                  |
|2 |`verify_step`        |L3    |L4 `recommend_coaching_for_solution`(verify_steps 신호)·L3 SymPy 검증·PRM(PRM800K)                            |🟡 3-state(unverifiable)·한국 PRM 보정은 0단계         |
|3 |`match_misconception`|L2/L3 |L4 `misconception/diagnose`(substring+정규식+의미)·pgvector `misconception_embedding`(slice104+)              |🟢 카탈로그 30종·top-1<0.65 게이트                     |
|4 |`curate_hypothesis`  |하네스   |L4 `hypothesis.py`(순수 `decay`·`reinforce`·`update_hypotheses`·**`curate`**·`select_focus`)·`hypothesis_store.py`(`apply_matches`·**`curate_hypothesis`** — `evidence_store.net_support` 반박·최대 5 캡·per-student 영속)|🟢 가설 세트·감쇠(반감기 5턴 지수·설계 ×0.85/3턴과 곡선만 차이·파라미터화)·반박(net_support<0 archived)·최대 5 캡 가동. **개입 발화 결선 가동**(`select_intervention_from_hypotheses`→`/v1/coach/sessions` `intervention`)·`select_probe` ε-탐색은 #6 순수 로직 가동|
|5 |`query_curriculum`   |L1+L2 |`concept_edge` PREREQUISITE·`fetch_prerequisites`(재귀 CTE 다단계)·`recommend_prerequisite_gaps`             |🟢 선수(후속/형제 EdgeType은 후속)                      |
|6 |`select_probe`       |L4    |L4 `probe_selection.py`(순수 `select_probe`·`resolve_probe_target`·`is_exploration_turn`·`plan_probe` — 정보이득 근사·ε-탐색)·L2 `item_information`/`IrtItem`(IRT 정보량 재사용)·`select_weighted_item`(CAT)·**ε 카운터=세션 `dialogue.total_turns` 유도**(`_wh1_turn_state`→`/v1/coach/sessions` `wh1_turn_index`/`wh1_exploration_turn` 노출)|🟡 가설 판별 태깅·ε-탐색(주기 5턴·활성 세트 밖)·정보량 최대 선택 순수 로직 + **ε 카운터 세션 유도·노출** 가동. 문제은행 *태그 스키마*·probe 거부 *집행*(엔드포인트 미호출)·신뢰도 상한 0.9 집행은 후속|
|7 |`log_evidence`       |하네스   |(근접) `record_attempt_mastery`·`attempt_event`(이벤트 소싱·TimescaleDB)                                       |🔴 `evidence_links`(polarity·weight) 미구현        |
|8 |`end_turn`           |L4→L5 |`recommend_coaching`·`recommend_prerequisite_coaching`·`GET /v1/me/.../coaching`·`/v1/coach(/sessions)`·**개입 발화=가설 세트 결선**(`_intervention_from_hypotheses_or`)·**도구 루프 골격**(`harness/wh1_loop.py` `run_tutoring_turn`)·**영속 턴**(`harness/wh1_session.py` `run_persisted_turn` — load→run→가설·증거 커밋)·BKT 커밋 `record_problem_attempt_mastery`|🟢 코칭 결정+커밋·개입 발화 누적 가설 결선·도구 루프 골격(8종+불변식)·영속 턴(웜스타트 로드→실행→evidence_links/misconception_hypothesis 커밋) 가동. BKT 커밋 큐·Redis 작업메모리·LLM 정책·fast path는 후속|
|9 |`log_strategy_event` |전략    |—                                                                                                       |🔴 `strategy_nodes`·`strategy_evidence` 미구현     |
|10|`elicit_prediction`  |전략    |—                                                                                                       |🔴 보정 루프(Brier·과신/과소신) 미구현                   |
|11|`assign_transfer_probe`|전략  |(자산) 시그니처 패턴 55+108(ROADMAP Phase 1)                                                                    |🔴 전이 측정·간격 출제 미구현                            |

**판독**: 코어 진단·코칭·선수 좌석(#1·#3·#5·#8 일부)은 *이미 가동*하며 이번 세션 소비 아크로 강화됐다. 하네스가 추가하는 건 ① **상태 외부화**(가설 세트·evidence_links·#4·#7 — 가동) ② **도구 루프 오케스트레이션**(end_turn 도구 루프·#8 — *골격 가동*: `harness/wh1_loop.py` `run_tutoring_turn` 8종 디스패치+불변식·순수 in-memory·영속/LLM 결선은 후속) ③ **전략 계층**(#9~#11 — 미구현). 즉 WH-1 도입은 *기존 좌석을 도구로 노출 + 상태/루프/전략 신설*이며, 진단·코칭 로직을 새로 짜는 게 아니다.

### 0단계 평가 하네스 — 구현 현황 (2026-06-13, 편집자 부기)

> **현행 정합(2026-08-03 실측 정정)**: 아래 커버리지 맵의 "🟢 ③ 세션 완주율"은 재검토가 필요하다
> — `LearningSession`은 `src/` 전체에서 **생성자 호출이 한 번도 없다**(`api/me.py`는 GET/PATCH/
> DELETE만). ③은 구조적으로 영원히 NO_DATA이고 writer는 2026-07-29 **영구 미신설** 결정
> (`S3-16`). 🟢 표기를 "돌아감"으로 읽지 말 것 — `gamification_module_gap_review.md` §정정.

§8.4 0단계의 *대리 지표 베이스라인 좌석*이 **구현됨** — `whymath_backend/harness/wh1_evaluation.py`(`compute_wh1_surrogate_metrics`)·`GET /v1/me/harness-metrics`. **날조 0 원칙**: 계측 가능분만 실값, 미계측은 `value=None` + `MetricStatus`(NOT_INSTRUMENTED·REQUIRES_DATA·REQUIRES_TOOL) + note로 *커버리지 맵*을 낸다(가짜 0 금지). 현 커버리지: **🟢 ① verify 통과율**(검산결과 `attempt_event` 적재→집계·단 binary 검산[거짓 수치관계 *미적발*]·3-state 아님·unverifiable 미구분)·**🟢 ③ 세션 완주율**·**🟡 ④ 턴당 토큰**·**🟡 ⑤ 도움 감소 곡선**(힌트제공 `attempt_event` 적재→hint_level OLS 기울기·음수=도움 감소)·**🟢 ⑤+R15 결합 판정**(`help_reduction_validated` — ⑤ 도움 기울기 × 정답률[`ProblemAttempt.is_correct`] OLS 추세 × **문항 난이도[IRT b] OLS 추세** 3신호 교차: 도움↓·정답률 유지·난이도 유지/↑→`GENUINE_IMPROVEMENT`·도움↓·정답률↓→`GAMING_SUSPECT`[힌트 회피]·**도움↓·정답률 유지·난이도↓→`GAMING_SUSPECT`[쉬운 문제 회피]**·난이도 데이터 부족→2신호 판정+blind spot 캐비엇·표본 부족→`INSUFFICIENT_DATA`·마이그레이션 0)·**🟢 ⑥ 보정 점수(Brier)**(`ProblemAttempt.confidence_self_reported`[0~1 자기보고 확신도=예측·`POST /v1/me/attempts`로 이미 수집] vs `is_correct` → `mean((confidence−is_correct)²)`·낮을수록 잘 보정·유효 쌍<5 NO_DATA) = 계측. **§11.4 보정 루프 코칭 구현**: `l4/calibration_coaching.recommend_calibration_coaching(confidence, is_correct)`(순수 L4) → 틀림+확신≥0.7→`calibration_overconfident`(소크라테스 강화·ASSUMPTION·"어디서 확신했는지 같이 짚어볼까")·맞음+확신≤0.3→`calibration_underconfident`(효능감·META·"잘 풀었어·좀 더 믿어도 돼")·잘 보정→None·`POST /v1/me/attempts` 응답 `calibration_coaching` 필드로 노출(측정⑥→코칭 행동 연결·톤 가드).·**🟡 ② 진단-실제 오개념 일치율(오프라인 진단정확도)**(라벨 프로브 94건[recall 61·FP 33]을 패키지 데이터 `l4/misconception/probes_v1.jsonl`로 단일화→recall 프로브에 매처[`diagnose`·substring+regex] **top-1 recall**[현 12/61=0.20·보수적 기준선]·**LIVE 학생별 ground-truth 아님**[시스템 진단엔진 품질·전 user 동일·user/기간 무관]·precision/FP는 `semantic_eval` 별도) = 계측.·**🟡 ⑦ 전이 점수(근사)**(`Problem.signature_patterns`[SignaturePattern 태그] 기반·**같은 패턴·다른 problem_id·사전 노출 후 초견 정답률**·전이 프로브<3 NO_DATA·**설계 §11.5 완전판[assign_transfer_probe·BKT≥0.95+2주 스케줄]과 다른 근사**·BKT 게이팅 미반영) = 계측. **미계측 0** — 7지표 전부 측정/근사 커버(①🟢②🟡③🟢④🟡⑤🟡⑥🟢⑦🟡 + R15). 후속: ⑦ 완전판(assign_transfer_probe·BKT 게이팅·2주 스케줄)·② LIVE per-user(문항-오개념 태깅·attempt별 진단 기록)·②⑦ precision/의미 매처 격상·보정 종단 추적·학부모 리포트·R15 추가 정밀화·0단계 나머지(verify 커버리지·Langfuse·PRM 오탐률)(MEMORY 2026-06-13 참조). **0단계 ③ 오개념 카탈로그 충족률 감사(audit) 구현**: `l4/misconception/audit.py` `audit_catalog_coverage() -> CatalogAuditReport`(순수·DB 0·`CATALOG` 30종 순회) — 항목별 `signals_count`·`regex_signals_count`·counterexample/canonical 보유·**신호 포화**(signals≥2 ∧ regex≥1)·도메인별 집계. 실측: canonical/counterexample/signals≥2 = **100%**. **범위**: 카탈로그 *정의* 충족도만 — §8.4 L193 "예시 오답 5개"(학생 풀이 코퍼스·LIVE·`learning_events`/`diagnose`)는 후속. SurrogateMetrics와 결선 안 함(정적·전역 지표·per-user LIVE 의미 충돌 회피·독립 리포트). 마이그레이션 0. **audit 후속 보강**: 드러난 regex 갭에 `log-distribution`(`log(a+b)=log a+log b`) 수치 정규식 *보수적* 추가(명명그룹 역참조·`\d+`로 disjoint — 올바른 곱 법칙·올바른 값·기호식엔 매칭 0[FP 프로브·단위 비매칭 테스트로 증명]) → **regex 커버리지 10%→13.3%·saturation 10%→13.3%**(시연 4종). 표기 변이 큰 삼각·부등식·개념/서술형은 regex 부적합→semantic_eval/LLM-judge 후속.

### 1단계 (도구 삽입) — 진행 (2026-06-13)

§8.4 1단계: `verify_step`·`match_misconception` 2도구를 기존 파이프라인에 삽입(0단계 게이트 통과 후). **2도구 모두 도구화 구현됨.**

**슬라이스 1 — `match_misconception` 도구화(§3.3 품질 게이트)**: `l4/misconception/match_gate.py` `apply_match_quality_gate(matches, *, ocr_confidence, confidence_floor=0.65, ocr_threshold=0.8)` — **top-1 신뢰도<0.65 → 후보 비움**(`no_confident_match`·억지 매칭 금지·R6) · **OCR<0.8 → `low_quality`**(현재 dormant). `api/coach.py` `_compute_matches` 세 모드 공통 출구에 후처리 삽입 — `diagnose`/`combine_diagnoses` **알고리즘 불변**·약한 매칭 하류 차단. 마이그레이션 0·6-튜플 불변.

**슬라이스 2 — `verify_step` 3-state 도구화**: `l3/verify_step.py` `verify_step(expr_before, expr_after, step_type=None) -> VerifyStepResult`(순수·결정론)·`POST /v1/verify-step`(stateless·`ConsentedUser`). **비대수 step_type**(조건해석·케이스분류·그래프스케치)→`unverifiable`; **대수**(계산·검산·None)→SymPy 동치 — `expand(diff)==0`/`simplify.is_zero is True`→**correct**·`is_zero is False`/*같은 자유변수의 0-아닌 다항식*(예: `(a+b)²≠a²+b²`)→**incorrect**·비다항 미정(예 `√(x²)`)·**변수 집합 달라 맥락 의존**(예 치환 `a`→`b+1`)·파싱예외·빈입력→**unverifiable**(weight 0.5). **정확성 #1**: *같은 자유변수* 가드로 치환·산문을 *거짓 incorrect 오판 않음*(학생 올바른 단계 보호). PRM·step 파싱·coach 결선은 후속.

**슬라이스 3 — `verify_solution` 다단계 집계**: `l3/verify_solution.py` `verify_solution(steps, step_types=None) -> SolutionVerificationResult`(순수·결정론)·`POST /v1/verify-solution`(stateless·`ConsentedUser`). *이미 분해된* 단계 시퀀스에 `verify_step`을 **연쇄**(steps[i]→steps[i+1])·집계 — `steps`(전이별 결과)·상태별 카운트·**`unverified_ratio`**(§3.1·unverifiable/전이수)·`first_incorrect_index`·`has_incorrect`. 엣지(<2 steps)→빈 결과(에러 아님). step_types 길이=전이수 불일치→`ValueError`→422. verify_step 보수성 *그대로 상속*(집계만·판정 재구현 0). **정확성 #1**: *텍스트→단계 분해(NLP)는 범위 밖* — 방정식 풀이(`2x+1=7`)와 변형 체인 혼동 시 거짓 incorrect 위험이라 **분해는 L5(OCR·공간정보) 책임**·백엔드는 제공 시퀀스만 검증.

**슬라이스 4 — `verify_solution` coach 결선**: `recommend_coaching_for_solution`에 옵션 `solution_steps`·`solution_step_types`(L5가 공간정보로 분해한 단계 시퀀스) 추가·`CoachRequest`에 동일 필드. 제공 시(len≥2) `verify_solution` 실행→**추가적 OR 결합**: `arithmetic_error = (텍스트 신호) or verification.has_incorrect`·`verify_steps = (kind=="solution") or step_incorrect`→`recommend_coaching`(순수 결정 *불변*·오케스트레이터가 신호→bool 매핑)→단계 incorrect 시 focus=verify(단계 자가검산 발화). `SolutionCoaching.solution_verification`(→`CoachResponse.solution_coaching`)으로 결과 노출(상태 카운트·`unverified_ratio`·`first_incorrect_index`). **하위호환**: 미제공→`solution_verification=None`·모든 기존 동작 완전 불변. **redaction**: 학생 *자기 단계*만 검증(verify_step은 정답을 모름)·정답/본문 노출 0. 마이그레이션 0·6-튜플 불변.

**슬라이스 5 — `match_gate` OCR confidence 활성(§3.3 게이트 ②)**: `CoachRequest.ocr_confidence: float|None`(0~1·L5 OCR 인식 신뢰도) 추가. `_compute_matches`가 드롭하던 `apply_match_quality_gate` 플래그를 `_MatchOutcome`(matches·low_quality·no_confident_match)으로 핸들러까지 thread→`CoachResponse.match_low_quality`·`no_confident_match` 노출. OCR<0.8→`match_low_quality=True`(**매칭 유지·플래그만**·입력 품질 신호지 매칭 오류 아님). 게이트 한 번만 적용(off/shadow/on·폴백 5출구 공통)·매칭 알고리즘·임계(0.65/0.8)·intervention 불변. **하위호환**: ocr_confidence 미제공→`low_quality=False`·완전 불변. **§3.3 범위**: 신호 노출까지 — *재확인 발화·intervention 보류는 L5/후속*(답 미루기 유지). redaction: bool 2개뿐. 마이그레이션 0.

**슬라이스 6 — verify 발화에 `first_incorrect_index` 반영**: `recommend_coaching`에 옵션 `incorrect_step_index: int|None`·`CoachingTrigger.focus_step_index: int|None`(구조화 메타데이터·발화와 별도 채널·L5 하이라이트/교사대시보드) 추가. verify+steps+index 시 **위치 인지 발화**("처음 {k}줄까지는 잘 따라왔어. {m}번째 줄이 바로 윗줄과 같은 값인지 거기서부터 한 줄씩 다시 확인해볼까?"·off-by-one: 전이 i→통과 k=i+1줄·의심 도착 줄 m=i+2). 오케스트레이터가 `verification.has_incorrect` 시 `first_incorrect_index` thread. **교수학 금기 준수**: 정답·수정·"틀렸다" 부재(테스트 가드)·앞 단계 통과 확인(효능감)·LTHC 최소 도움(위치만 좁힘·무엇이 왜 틀렸는지·고치는 법은 학생 몫)·소크라테스 질문형. **하위호환**: index 미제공→기존 위치 비지목 발화·`focus_step_index=None`·완전 불변. `recommend_coaching` 결정 우선순위·verify 판정 불변. 마이그레이션 0.

**슬라이스 7 — OCR confidence ↔ verify 연동(저신뢰 step 보류)**: `recommend_coaching_for_solution`에 옵션 `ocr_confidence` thread(`CoachRequest.ocr_confidence`에서). `ocr_low = ocr_confidence<0.8`(match_gate `_DEFAULT_OCR_THRESHOLD` 재사용)이면 **step-incorrect 신호 보류** — `step_incorrect_trusted = has_incorrect and not ocr_low`만 `arithmetic_error`/`verify_steps`/`incorrect_step_index`에 반영(저신뢰 시 **위치 미지목**). `SolutionCoaching.verification_ocr_gated: bool`(=has_incorrect and ocr_low)로 *보류 사실* 노출(L5 OCR 재확인 유도). **정확성 #1**: OCR 오인식("(a+b)³"→"(a+b)²")을 *학생 오류로 거짓 지적하지 않음*(보류). **투명성**: `solution_verification`(원 verdict)은 그대로 노출·코칭 결정엔 신뢰분만. **텍스트 레벨 신호 불변**: `validate_response`(거짓 등식)는 OCR 무관이라 게이팅 안 함(step만). **하위호환**: ocr_confidence 미제공/≥0.8→완전 불변. 게이팅은 오케스트레이터만(verify_solution/verify_step/recommend_coaching 순수 불변)·마이그레이션 0. 실측: ocr=0.5→focus≠verify·gated=True·step_idx=None·verdict 보존 / 0.9·미제공→verify·위치.

**후속(1단계 잔여)**: 학생 솔루션 텍스트→단계 *분해*(L5 OCR·공간정보) · `match_low_quality`·`verification_ocr_gated` 소비(재확인 발화·intervention 보류·L5) · ~~`focus_step_index` 점층 escalation~~ **구현됨(2026-06-18·아래)** · per-step OCR 신뢰도(전이별 정밀 게이팅) · 단원별 verify 커버리지 ≥70% 게이팅 · PRM800K 한국 분포 보정.

**슬라이스 9 — hint 점층 오케스트레이터 결선**: 슬라이스 8의 L4 좌석을 *실제 발동*시킨다. `api/coach.py _build_response_payload`가 Polya 결정이 *이미 계산한* `decision.hint_level`(`decide_hint_level`·턴/좌절/숙달)을 `recommend_coaching_for_solution`(신규 옵션 `hint_level: HintLevel | None`)→`recommend_coaching`으로 thread. **재계산 0**(decide_hint_level 단일 산정처 재사용·L4 경계). 효과: *단계 자가검산*(verify_steps) 경로에서 hint_level 3·4(예: 같은 단계 5턴+ 막힘 `turn_count≥5`·좌절·답요구)면 과정 재구성 비계로 점층(정답/"틀렸다" 미포함·답 미루기). 1·2단계·verify_steps 아님·미제공이면 발화 불변(하위호환). `SolutionCoaching.trigger.hint_level`(#250 메타데이터)이 `CoachResponse`로 자연 노출(추가 노출 코드 0). 실측: `turn_count=5`+발전중→`decision.hint_level=3`→점층 발화·`turn_count=0`→1→불변. 순수·DB 0·마이그레이션 0.

**슬라이스 8 — verify 자가검산 발화 hint 점층(escalation) 통합**: `metacognitive_trigger.recommend_coaching`에 옵션 `hint_level: HintLevel | None`(호출자가 `hint_deferral.decide_hint_level`로 *미리 계산*해 전달·L4는 raw 입력 재계산 0·레이어 경계) 추가·`_build`로 thread. **verify 자가검산 경로(focus=="verify" ∧ verify_steps)에서만** 점층: `hint_level∈{None,1,2}`→*기존 동작 그대로*(가장 빠른 단계에서 멈춤·스펙 L39), `∈{3,4}`→**과정 재구성 비계 발화**(`_verify_steps_escalated_prompt` — 위치 인지[앞 k줄 통과 효능감 + m번째 줄 규칙 재구성]/비지목 각각·off-by-one k=i+1·m=i+2 기본형 동일). **교수학 금기 엄수(테스트 가드)**: 점층 발화에 정답·정답값·올바른 다음 줄·"틀렸다/잘못/오답/정답은/고치/수정"·`=` 부재·질문형(`?`)·앞단계 효능감 유지 — *무엇이 왜 어긋났는지·고치는 법은 학생 몫*(답 미루기·LTHC 최소도움·정서안전). `CoachingTrigger.hint_level`(구조화 메타데이터·발화와 별도 채널·L5 점층 렌더·교사 대시보드) 노출 — `focus_step_index`와 동일 컨벤션(verify 포커스만 채움). **하위호환**: `hint_level=None`→모든 기존 동작·반환 완전 불변(`==` 핀). 순수 결정론·DB 0·마이그레이션 0.

### 2단계 종료 게이트 (진단 일치율 유의 개선) — 진행 (2026-06-18)

§8.4 2단계 *종료 기준* "진단-실제 일치율이 **베이스라인 대비 유의 개선**"의 **판정 좌석 구현됨** — `whymath_backend/harness/agreement_gate.py`. 후보(candidate) 진단 파이프라인이 베이스라인 대비 라벨 프로브셋에서 *통계적으로 유의하게* 더 높은 top-1 일치율(recall)을 내는지 **McNemar 검정**으로 가린다(단순 "조금 높다"가 아니라 *유의 개선*만 PASS).

- **McNemar(쌍체 정확 이항)**: 같은 프로브셋을 두 매처가 각각 풀므로 *쌍체*다. 불일치쌍만 본다 — b=베이스라인만 맞춤·c=후보만 맞춤. H0(차이 없음) 하 c~Binom(b+c, 0.5)·*단측* 정확 이항(`_mcnemar_one_sided_p` — Σ_{k=c}^{n} C(n,k)·0.5ⁿ)으로 "후보가 더 맞춤(c 큼)" p값을 내고 `alpha`(기본 0.05) 미만이면 유의. 정규근사 대신 정확 이항이라 소표본에도 타당(연속성보정 불요).
- **verdict 3종**: `IMPROVED`(후보 recall>베이스라인 ∧ p<alpha) / `NOT_IMPROVED`(동등·악화·또는 개선이나 비유의·과소표본 포함) / `NO_DATA`(라벨 프로브 `_MIN_PROBES=5` 미만 → 판정 보류·p None). **거짓 PASS 0**: 유의에 *도달 못 하는* 과소표본은 자연히 NOT_IMPROVED(불일치쌍 4건 개선이어도 p=0.0625>0.05 → NOT_IMPROVED).
- **베이스라인 = `substring_matcher`**(`diagnose` top-1·결정론·항상 가용·② 지표와 동일 신호·보수적 기준선). **후보 = 주입**(`run_agreement_gate(candidate=...)` Matcher) — 프로덕션은 의미 매처(pgvector 임베딩·더 높은 recall이나 임베딩 의존)를 주입, 테스트는 합성 매처(임베딩 비의존 검증). 매처가 None 반환(매치 0)이면 그 프로브는 자동 miss(억지 매칭 금지·§3.3).
- **정직 스코프**: *오프라인·시스템 지표*다(② 진단정확도와 동일 라벨 프로브셋·`_iter_recall_probes`). **LIVE 학생별 ground-truth 아님** — 실제 학생 진짜 오개념은 자가보고되지 않아(문항-오개념 태깅·attempt별 진단 기록 부재) LIVE per-user 일치율은 여전히 데이터 기반 없음(후속). 이 게이트는 *진단엔진 품질의 회귀/개선*을 잰다.
- **범위 밖(후속)**: 의미 매처 후보 *결선*(임베딩 provider·integration)·LIVE per-user 일치율(문항-오개념 태깅·attempt 진단 기록)·게이트 결과 API 노출·코호트별 층화. 순수 함수·DB 0·마이그레이션 0.

**의미 매처 후보 결선 (2026-06-18·후속 1)**: 위 게이트의 후보 자리를 *의미 매처*(임베딩)로 채움 — `whymath_backend/harness/agreement_gate_semantic.py`. **어댑터**(`semantic_candidate_matcher`): `SemanticMatcher.match` top-1을 게이트 `Matcher`(진술→top-1 오개념 id·임계값 미달 None)로 감싼다(게이트는 top-1 recall을 재므로 top_k=1만·임계값 통과 후보 0이면 None=miss·억지 매칭 금지). **결선**(`run_semantic_agreement_gate`): `SemanticMatcher`를 *1회* 구축(카탈로그 사전 임베딩 캐시·항목당 재임베딩 0)해 후보로 싣고 `run_agreement_gate`(베이스라인=substring 기본·동일 라벨 프로브셋)에 넘긴다 → "**의미 매처가 substring 기준선을 라벨 프로브셋에서 유의하게 능가하는가**"를 실제 판정. `threshold` 미지정 시 `Settings.misconception_semantic_threshold`(보수적 0.55). **provider 주입 필수**(좌석): 테스트는 `FakeEmbeddingProvider`(결정론·hermetic — 단일 항목 카탈로그+임계값으로 후보 hit/miss 결정론 통제), 라이브 임베딩(bge-m3)·실 프로브셋 결선은 integration(WHYMATH_RUN_INTEGRATION 1건). **정직 스코프 불변**: 게이트는 의미 매처의 substring 대비 *순효과*만 잴 뿐 의미 매처가 *옳다*고 주장하지 않음(임베딩 방향맹 — 방향·부정·등치 못 가림·LLM-judge 후속). 순수 어댑터·DB 0·마이그레이션 0.

**정밀도(거짓양성) 회귀 가드 + 결합 종료 판정 (2026-06-18·후속 2 — 정확성 #1 보호)**: 위 recall 게이트는 후보가 *틀린 진술*을 더 잘 잡는지만 본다 — 그러나 후보가 recall을 올리며 *올바른 진술*에 오개념을 더 많이 오매칭하면(거짓양성↑) **학생을 틀렸다고 오판**한다(CLAUDE.md 의사결정 우선순위 #3 교수학적 정확성 위반·학습효과·UX·비용보다 위). recall만으론 이 축이 *맹점*이다. 보강(`harness/agreement_gate.py`·`l4/misconception/probes.py`): **`_iter_fp_probes`**(FP 프로브 33건 — `expected_id` null·올바른 진술) → **`evaluate_precision_guard`/`run_precision_guard`**: FP 프로브에서 (베이스라인 오매칭, 후보 오매칭) 쌍체로 *같은 단측 McNemar*를 돌리되 방향만 반대 — 후보-우세 거짓양성(c' 큼)이 유의하면 **`REGRESSED`**, 아니면 **`NO_REGRESSION`**(과소표본·동등은 거짓 FAIL 0). **`evaluate_phase2_exit`**(결합·`Phase2Exit`): 2단계 종료를 **recall `IMPROVED` AND 정밀도 `NO_REGRESSION`**일 때만 `READY`로 낸다 — *정밀도 회귀는 recall 개선을 덮어쓴다*(`NOT_READY`·정확성 #1 안전장치). 둘 중 하나라도 `NO_DATA`면 결합도 `NO_DATA`(종료 certify 불가). 의미 매처 결합 결선 **`run_semantic_phase2_exit`**: 후보를 *1회* 구축해 recall 게이트(라벨 프로브)·정밀도 가드(FP 프로브)에 *공유*하고 결합. 실측: substring 베이스라인의 FP율은 **0.848**(28/33·표면 토큰 오매칭) — 후보의 FP 회귀 여부를 비교로 가린다. 순수·DB 0·마이그레이션 0.

**게이트 결과 ops 노출 — CLI (2026-06-18·후속 3)**: 전역/코호트 집계는 admin auth 범위 밖이라 *HTTP로 노출하지 않고*(me.py `get_my_harness_metrics` 주석 "코호트 전체 집계는 ops/스크립트가 직접 호출"·본인 집계만 HTTP) **스크립트가 직접 돌린다** — 그 표면이 `harness/agreement_gate_cli.py`(`python -m whymath_backend.harness.agreement_gate_cli [--alpha 0.05] [--min-probes 5] [--threshold 0.55]`). 설정 provider(`build_provider` — bge-m3/OpenAI)로 의미 매처 후보를 *1회* 구축해 **`run_semantic_phase2_report`**(신규 `Phase2Report` = recall 게이트 + 정밀도 가드 + 결합 판정 *전체 수치*)를 돌리고 결과를 **JSON으로 stdout**에 낸다(머신 파싱). **종료 코드로 판정 인코딩**: 0=READY·1=NOT_READY·2=NO_DATA → `python -m … && <다음 단계>`로 게이트 *집행*(green일 때만 진행). `main(argv, *, runner=...)`의 `runner`는 테스트 주입 좌석(기본 `_default_runner`=라이브 임베딩·`pragma: no cover`)이라 CLI 배선(인자·직렬화·종료 코드)은 합성 리포트로 hermetic 검증, 라이브 결선은 integration 1건. `run_semantic_phase2_exit`은 `run_semantic_phase2_report(...).decision` 얇은 래퍼로 정리. 순수·DB 0·마이그레이션 0.

**의미 매처 사전적재 인덱스 모드 (2026-06-18·후속 4 — pgvector 재사용 primitive)**: 위 "pgvector 사전 임베딩 인덱스 결선"의 *enabling primitive*. `SemanticMatcher(prebuilt_index=True, index=…)`(L4 `semantic/matcher.py`): `prebuilt_index=True`면 카탈로그를 *재임베딩하지 않고* 주입된 인덱스를 그대로 질의한다 — `populate_pgvector`로 한 번 채운 `PgVectorIndex`를 매 프로세스/매 호출이 재임베딩 없이 공유(라이브 진단 경로의 *항목당 재임베딩 비용 0*·프로세스 간 공유). 종전엔 매 `SemanticMatcher`/`semantic_matches` 호출이 카탈로그 30종을 재임베딩했다(`matcher.py` docstring·라이브 모델에선 비쌈). 오용 가드: `prebuilt_index=True` ∧ `index=None` → ValueError(빈 인덱스 질의 무의미). 기존 주입 좌석(`semantic_candidate_matcher(matcher, …)`)으로 게이트에 바로 연결되므로 게이트/CLI thread-through 불요 — 호출자가 `SemanticMatcher(prebuilt_index=True, index=populated_pg)`를 만들어 후보로 싣는다. hermetic(ScriptedEmbeddingProvider+사전적재 InMemoryVectorIndex·embed 카운트로 재임베딩 0 증명)·라이브 pgvector 결선은 integration. 순수·마이그레이션 0.

**의미 매처 좌석 팩토리 (2026-06-18·후속 5 — 구성 체인 단일화)**: `build_semantic_matcher(provider, *, settings=None, catalog=CATALOG, prebuilt_index=False)`(L4 `semantic/matcher.py`) — `_provider_model_identity`→`build_vector_index`→`SemanticMatcher` 좌석 체인을 한 곳에 모은다. **memory(기본)**: `InMemoryVectorIndex` 자체 적재(식별자 불요·`pgvector_index`/psycopg import 회피·dep-free). **pgvector**: 식별자 해석(지연 import)→`build_vector_index`→`prebuilt_index` 전달(위 후속 4 primitive를 *설정 기반*으로 활성). `api/_misconception_state._build_matcher`(라이브 coach 싱글톤)가 풀던 중복 체인을 이 팩토리에 위임(동작 불변·`prebuilt_index` 기본 False로 종전 자체 적재 유지). hermetic(memory 자체 적재·pgvector는 `build_vector_index` 몽키패치로 prebuilt embed-카운트 검증)·`_misconception_state` lazy 빌드 경로도 테스트로 커버(종전 미커버). 순수·DB 0·마이그레이션 0. **여전히 후속(명시적 결정 필요)**: pgvector 배포에서 coach/게이트를 `prebuilt_index=True`로 *활성*(ops `populate_pgvector` 선행·앱 lifespan 적재 보장 동반)해 라이브 진단 경로 재임베딩 제거 — 현재는 활성 안 함(기본 False로 동작 불변)·LIVE per-user 일치율(문항-오개념 태깅·attempt 진단 기록).

**활성 가설 → 소크라테스 카테고리(ASSUMPTION 가정 표면화) 결선 (2026-06-19)**: #266의 *순수 규칙*(`l4/socratic/select.py:select_category(stage, transition, student_input, hypotheses=None)`·`PolyaCoach.decide(..., misconception_hypotheses=)`)을 **라이브 coach 경로에 활성화**한다(그 전엔 `decide`가 가설을 안 받아 규칙 무발동). 쓰기측(`_apply_hypotheses`→`apply_matches`·도구표 #4·#8)은 이미 매 턴 학생 활성 가설 세트를 영속·노출하고 `_intervention_from_hypotheses_or`로 *개입 채널*을 구동했으나, *소크라테스 카테고리* 채널은 가설을 못 봤다. **구현(소스 1파일·마이그레이션 0)**: `api/coach.py`에서 세션/턴 핸들러가 `_apply_hypotheses`를 `_build_response_payload` **앞으로 이동**시키고 돌려받은 `active_hypotheses`(post-apply·confidence 내림차순)를 새 kwarg `misconception_hypotheses`로 넘겨 `decide`까지 thread. 학생이 머무르며(stay/previous) 막혀 있고 명시 신호가 없을 때 고신뢰(≥0.65)+최근(≤2턴) 가설이면 그 턴 Polya 발화의 **질문 종류**가 ASSUMPTION("왜 그렇게 가정했어?")으로 정밀화된다. **개입 채널과 *동일한* post-apply 세트**를 쓰므로 두 채널이 일관(단일 진실원천·턴1 raw 매치 정합·추가 DB 쿼리 0·warm-start 별도 read 기각). **교수학 금기 준수(테스트 가드)**: 결정은 *카테고리 enum*만 — 발화·정답·"틀렸다"·misconception_id 미노출. **하위호환**: stateless `/v1/coach`는 세션·가설 없음→None(불변)·세션 경로도 가설 없음/저신뢰/stale면 단계 기본(맞은 학생 영향 0). **후속**: `get_active_hypotheses` 웜스타트 read를 별경로에 노출·오개념 타입별 카테고리·ASSUMPTION vs EVIDENCE 동적 선택·`socratic_category`의 응답 별도 필드 노출. 순수 재사용(재구현 0)·DB 신규 쿼리 0·마이그레이션 0.

**라이브 coach 가설 갱신 → `curate_hypothesis` 승격(하네스 동치) (2026-06-19)**: 위 결선 후 드러난 갭 — 라이브 학생 경로(`api/coach.py:_apply_hypotheses`)가 `apply_matches`(매치만)를 써, 하네스(`run_persisted_turn`)가 도는 §3 도구4 `curate_hypothesis`의 두 보호가 빠져 있었다: ① **증거그래프 반박**(`net_support<0` archived·R4 확증편향 방지·§5.1) ② **최대 5개 활성 캡**(§2.2). 하네스가 *같은 `student_id`* 증거 그래프(`evidence_links`)에 적재하므로, 하네스 튜터링이 반박한 오개념을 라이브 coach가 계속 ASSUMPTION·개입으로 들이미는 단일 진실원천 위배가 생겼다. **구현(소스 1파일·마이그레이션 0)**: `_apply_hypotheses`를 `apply_matches`→`curate_hypothesis(session, student_id=user_id, matches=matches)`로 1:1 교체(반환 계약 동일·다운스트림 무변경). **하위호환**: 반박 증거 없고 활성 ≤5면 `apply_matches`와 결과 동일(맞은/단순 학생 영향 0)·동작 변화는 반박 증거 존재 또는 활성 6개+ 일 때만(의도된 개선). **비용**: 후보 오개념당 `net_support` SQL 1회 추가(N≤5+few·증거 없으면 0.0 즉답)를 R4 보호·단일 진실원천과 맞바꿈. **후속**: 라이브 경로 *증거 적재*(`log_evidence`를 coach 매치/verify로 호출 — 현재 증거는 하네스만 적재·본 슬라이스는 반박 *소비* 좌석만)·오개념 타입별 카테고리·다중 가설 가중. 순수 재사용(재구현 0)·마이그레이션 0.

**라이브 coach 증거 *생산*(+1 지지) 결선 (2026-06-19)**: 위 승격(소비측)의 짝 — 라이브 coach가 증거를 *생산*(`log_evidence`)하지 않아(하네스만 적재) 실 학생 `evidence_links`가 비어 #268 소비가 0만 봤다(소비↔생산 비대칭). **구현(소스 1파일·마이그레이션 0)**: 신규 `_log_match_evidence(session, *, session_id, student_id, matches)`가 매 턴 *확정 매치*(`outcome.matches`·top-1<0.65 게이트 통과)를 `log_evidence(..., polarity=1, weight=confidence)`로 적재(하네스 영속 패턴 모사·재구현 0). `create_session`/`append_turns`에서 `_apply_hypotheses`(curate·*직전까지* net_support 반박 판정) **뒤**에 호출 — 이번 턴 지지가 같은 턴 반박을 순환 차단 안 하고 *미래* net_support에만 반영(소비=과거·생산=미래). **정직 범위**: +1 지지 *생산*만 — **−1 반박 생산은 후속**(하네스조차 polarity를 LLM 정책으로 고르며 verify-pass→오개념 결정론 귀속 불가·교수학 사인오프 필요). 따라서 라이브-단독 curation 행동은 불변(−1 없음)·그래프만 채운다. **효과**: 실 학생 production 증거 그래프가 §2.3 토대(학부모 리포트·진단·GDPR 증거 export)에 실데이터 공급·하네스+라이브 혼용 시 라이브 +1이 net_support에서 하네스 −1을 정직 상쇄. **개인정보 불변**: `evidence_links`는 식별자·극성·가중치·날짜만(평문 적정)·student_id FK CASCADE·retention 자동. **후속**: −1 반박 생산·`event_id`/`node_id` 느슨참조 채우기·오개념 가설/증거 GDPR export(#265 NOT). 재사용(재구현 0)·마이그레이션 0.

**라이브 coach 증거 *반박*(−1) 생산 결선 — clean 검증 풀이로 의심 오개념 약하게 반박 (2026-06-19·교수학 사인오프)**: 위 +1 생산의 짝 — −1 *반박* 생산이 없어 #268 `curate_hypothesis` archived 가드(`net_support<0`)가 라이브-단독 학생에겐 발동 못 했다(net_support≥0). 이 슬라이스가 그 −1 좌석을 *보수적*으로 결선해 evidence 아크(#266~270)를 닫는다. **보수 귀속 규칙(교수학 사인오프 대상·사용자 승인)**: 풀이 제출 턴이 ① clean 검증(`passed is True`)이고 ② 이번 턴 *확정 매치 없음*(`not outcome.matches`)이면 ③ *현재 active 가설 각각*에 `log_evidence(polarity=-1, weight=_REFUTE_WEIGHT=0.5)`. 04a §2.3 "verify가 가설 *예측*과 모순되면 −1"의 결정론 조작화다. **no-match 게이트(정합)**: 매치 턴(+1)은 반박 안 함 → 한 턴은 지지(매치) 또는 반박(clean 정답) *둘 중 하나*(같은 턴 모순 적재 차단·매치+정답 동시 턴은 +1 우선). **약한 가중(낙인 방지·#1)**: net_support=Σ(polarity×weight)라, 강한 실제 오개념(다회 +1·weight≤1.0 누적)은 clean 한 턴(−0.5)으로 안 죽고 약·stale 의심만 누적 −0.5로 archived → 실신호 보존하며 낙인 방지. 0.5는 KPI 튜닝 대상(#266 floor 0.65 선례·상수 노출). **귀속의 보수성(정직)**: verify 신호는 *일반* 계산정합이라 특정 카탈로그 오개념 귀속이 불가(카탈로그엔 '거짓' 신호만·'올바른 형태' 부재)·하네스조차 polarity를 LLM 정책으로 고른다 → 결정론으로 가능한 가장 보수적 귀속은 *현재 의심(curate ≤5·recency) 전체*의 약한 반박이다. **구현(소스 1파일·마이그레이션 0)**: `_log_verify_event`가 `bool | None` 반환(풀이 아님 None·clean True·거짓관계 False)·신규 `_log_refutation_evidence`·`create_session`/`append_turns`가 `_log_match_evidence`(+1) **뒤**에 호출(소비=과거·생산=미래 순서 유지). **효과**: #268 archived 가드가 라이브-단독 학생에 발동하되 decay(자연 감쇠)에 더해 *능동적 clearing* 제공. **후속(NOT)**: 정밀 귀속(문제 concept domain↔오개념 `domain` 매칭·카탈로그 `canonical_correct_form`)·verify-fail→+1 지지·`_REFUTE_WEIGHT` A/B 튜닝. 재사용(재구현 0)·마이그레이션 0.

**라이브 coach 반박 정밀화 — canonical correct-form 정밀 귀속(tier 강·약) (2026-06-19)**: 위 #270이 남긴 정밀 귀속 NOT의 두 경로 중 하나를 결선. **domain 스코핑은 데이터 부재로 보류**(오개념 `domain`=한글 8-enum ↔ 문제 domain=자유문자열 코드·매핑 부재·disjoint taxonomy) → 남은 경로 **`correct_form`**(사용자 선택). **무엇**: clean+no-match 턴에서 active 가설 각각에 −1을 적재하되 *증거 강도로 가중을 tier* — 풀이에 그 오개념의 *정정 형태*(`Misconception.correct_form`)가 검출되면(`correct_form_present`·`signals`와 동일 `_normalize`) `_REFUTE_STRONG_WEIGHT=1.0`(정밀: "학생이 M의 올바른 형태를 직접 보임"), 아니면 #270의 `_REFUTE_WEIGHT=0.5`(막연한 clean). #270의 광범위 약한 −1을 *tier 정밀화*한 것(active-scoped 유지·비의심 noise row 0). **gate-safety 선정(핵심)**: 정정 형태는 `signals`의 LHS 토큰을 공유하기 쉬워 *잘못된* matcher가 정정 형태를 confident 오진단할 수 있다 → 각 후보를 검사해 `diagnose(correct_form)`이 그 오개념을 floor 0.65 미만으로만 내는 **안전 5종만 부여**(distribution-over-power·exponent-zero·log-distribution·product-rule-naive·sine-distributes-over-sum). 정정에 1.0 오진단되는 unsafe 후보(square-root-positivity·fraction-cancellation·chain-rule-inner-derivative-omitted)는 *제외*하고 **불변식 테스트로 강제**(`TestCorrectForm`). **강 1.0 근거**: 만점 단일 매치(+1.0)와 대칭 — 단발 정정이 confident 진단을 *즉시* 지우진 않고(net 0·archived 아님) 반복·decay와 합쳐 죽인다(신호 보존·#270 철학). **구현(소스 4파일·마이그레이션 0)**: `models.py`(`correct_form: str|None=None` 선택 필드)·`diagnose.py`(`correct_form_present` 순수 함수·`_normalize` 재사용)·`catalog.py`(안전 5종 +`correct_form=`·DB 아님)·`coach.py`(`_REFUTE_STRONG_WEIGHT`·`_log_refutation_evidence`에 `solution_text` 인자·per-hyp tier·`solution_text=body.student_solution`). **효과**: "학생이 막연히 clean 작업을 했다"(약 0.5)와 "M의 올바른 형태를 *실제로* 보였다"(강 1.0)를 증거 강도로 분리 — taxonomy 의존 없이 정밀 귀속(교수학 정확성 #3). 강·약 모두 −1 방향이라 낙인 0. **후속(NOT)**: 나머지 오개념 correct_form 확장(gate-safe 인증 필요)·unsafe 후보용 *전용 정정 신호*(LHS 회피)·비-active 능동 clearing(noise row trade-off)·domain 글로서리(ProblemDomain→MisconceptionDomain)·strong weight A/B. 재사용(재구현 0)·마이그레이션 0.

### 3단계 (primary flip — 발화 승격) — 구현 (2026-07-20, 편집자 부기)

§8.4 3단계·MEMORY 2026-07-20 flip 사인오프(ⓑ verify 게이트 승격 재판정 통과·ⓒ Kiki 사인오프)의 **구현 기록** — S1-11. "완전 수렴=primary flip"(2026-07-14 정의) 중 **학생-대면 발화의 승격**을 플래그 스테이징으로 결선했다.

- **플래그 스테이징(canary)**: `wh1_primary_enabled`(env `WHYMATH_WH1_PRIMARY_ENABLED`·**기본 off**) — off면 기존 결정론 Polya 템플릿 경로와 비트동일(회귀 0·CI 동결 `test_coach_gate3_serving_invariant` 봉인 ③에 기본 off 포함). on이면 coach *세션/턴*(`/v1/coach/sessions`(+`/turns`))의 학생-대면 발화(`decision.prompt`·AI 턴 content)가 하네스 발화로 대체된다. stateless `/v1/coach`는 불변. **기본 on 전환은 Kiki 실기기 확인 후 별도 커밋.**
- **실행 좌석**: 신규 `harness/wh1_primary.py`(`run_wh1_primary_turn`) — shadow(`wh1_shadow.py`)의 자매. 같은 정책 구성(S1-a 사적 주입: 학생 원문·풀이 단계·웜스타트 outside_mids는 LLM 프롬프트 미노출) + 같은 순수 턴 루프(`run_tutoring_turn` — verify 의무 §3.1·정답 억제 백스톱 §3.4·ε-탐색·증거 게이트를 하네스가 강제)를 동기 실행하고, **발화를 호출자에게 반환**한다. `api/coach.py`의 `_wh1_primary_decision_or`가 `decision.prompt`만 `model_copy`로 교체(구조화 결정·가설·증거·이벤트 파이프라인은 기존 결정론 경로 그대로).
- **웜 스타트**: 라이브 경로의 post-apply 활성 가설 세트(`_apply_hypotheses`=`curate_hypothesis` 영속분)를 `initial_hypotheses`로 실어 §2.2 웜 스타트를 충족(shadow와 동일 계약).
- **톤 필터 라이브 배선(KPI3 첫 좌석)**: 노출 직전 `l4/tone_filter.filter_tone` 적용 — 위반 시 rewritten 텍스트만 노출하고 위반 사실을 ① 구조화 WARNING 로그(패턴 라벨·건수만·발화 원문 미포함) ② 관측 레코드 `tone_rewritten`/`tone_violations`로 기록. 톤위반 전용 `attempt_event` 적재는 **후속** — `EventType`이 네이티브 PG enum이라 값 추가=마이그레이션(사인오프 방침 '마이그레이션 없는 경로 우선').
- **결정론 폴백(가용성)**: LLM/하네스 실패·타임아웃(`wh1_primary_timeout_seconds`·기본 15s)·예산 소진(`budget_exhausted`)이면 `None` → 기존 결정론 템플릿 발화 그대로(앱은 죽지 않는다). 모든 실패는 예외 *타입명* 포함 WARNING(침묵 실패 금지). provider 장애는 정책(`LLMTutorPolicy`)이 안전 강등해 하네스 파생 결정론 발화(격려·소크라테스 개입)로 귀결 — 이중 방어.
- **관측 연속성**: primary 경로도 shadow와 *동일 레코드 계약*(`emit_wh1_observation` — shadow·primary 공통 좌석으로 추출)으로 emit해 verdict 원장 축적이 끊기지 않는다. 레코드 신규 필드 `primary: bool`(회계 분리·S3-07 신/구판 선례)·`tone_rewritten`·`tone_violations`(비식별 bool/int). primary on이면 별도 shadow spawn 생략(같은 턴 이중 LLM 호출·중복 레코드 회피).
- **gate3 기계 봉인 확장(사인오프 조건)**: `test_gate3_student_verification_governance.py` (E) 신설 — flip 플래그·러너 소비 모듈을 frozenset allowlist로 정확 일치 동결(무제한 개방 금지) + `wh1_primary.py`의 `run_tutoring_turn`/`filter_tone` 게이트 마커 봉인. `PolyaCoach.coach()` allowlist (A)는 불변(flip은 `.coach()`를 쓰지 않고 하네스 검증 경로 경유).
- **정직 스코프(구현 ≠ 3단계 전부)**: 3단계의 **도구 루프+웜 스타트는 가동**·**fast path(§5.3)는 후속**(전 턴이 풀 루프 — 레이턴시는 타임아웃+폴백으로 방어). §6 A단계 "Claude Haiku 판단 루프"는 현 스택의 라우터 결정(로컬 FAST 우선·2026-07 실측 로컬 90%)으로 대체됨. **상태 오케스트레이션 수렴은 미실행** — 가설·증거·이벤트 영속은 기존 라이브 결정론 파이프라인이 계속 소유하며 `run_persisted_turn`은 의도적 HTTP 미배선 유지(배선 시 같은 턴 이중 curate/영속·단일 진실원천 붕괴 — 해당 docstring 갱신). 실 LLM 품질·프롬프트 튜닝은 flip 후 실사용 관찰 과제.
