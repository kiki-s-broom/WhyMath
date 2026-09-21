# 분석 이벤트 개인정보·보존 정책 (v1)

- **적용 범위:** `AnalyticsEventEnvelope`를 통과하는 신규 분석 생산 이벤트
- **정본 코드:** `src/backend/whymath_backend/schema/analytics_event.py`
- **타입별 payload 정본:** `src/backend/whymath_backend/schema/event_data_contract.py`
- **보존 집행:** `src/backend/whymath_backend/privacy/retention.py`
- **상태:** P0 계약. DB 영속화와 event UUID unique constraint는 DP-03에서 추가한다.

## 목적 제한

이벤트는 제품 품질, 학습 흐름의 집계 분석, 운영 장애 진단에만 사용한다. 학생 원문이나 개인을 재식별할 수 있는 값을 분석 이벤트에 넣지 않는다. 학생 풀이 데이터를 모델 학습에 사용하려면 이 정책과 별도의 명시적 동의·목적·보존 정책을 충족해야 한다.

## 공통 envelope

| 필드 | 분류 | 목적 | 보존/삭제 소유자 |
|---|---|---|---|
| `event_uuid` | 가명 식별자 | 재전송 멱등성 | `privacy.retention.purge_expired_records` (DP-03 영속화 후) |
| `schema_version` | 비개인 | 계약 호환성 | 이벤트 보존과 함께 파기 |
| `occurred_at` | 저위험 메타 | 사건 시각 | 이벤트 보존과 함께 파기 |
| `received_at` | 저위험 메타 | 수신 지연·순서 분석 | 이벤트 보존과 함께 파기 |
| `source` | 비개인 | backend/mobile 신뢰 경계 | 이벤트 보존과 함께 파기 |
| `session_id` | 가명 식별자 | 세션 단위 집계 | 이벤트 보존과 함께 파기 |
| `correlation_id` | 가명 식별자 | 요청/흐름 상관관계 | 이벤트 보존과 함께 파기 |
| `event_type` | 비개인 | 타입별 집계 | 이벤트 보존과 함께 파기 |
| `payload` | 타입별 allowlist | 이벤트 의미 | 이벤트 보존과 함께 파기 |

## payload 규칙

1. `EventType`별 payload는 `EVENT_DATA_CONTRACT`에 등록된 Pydantic 모델만 허용한다.
2. 계약이 없는 휴면 이벤트 타입은 분석 producer가 만들 수 없다.
3. 다음 키와 동등 의미의 중첩 키는 금지한다.
   - 원문: 채팅, 메시지, 학생 답안, 풀이, 수식/LaTex, OCR 결과
   - 파일·링크: 이미지, 손글씨, 이미지 URL, URL query/query string
   - 정밀 행동·식별: x/y 좌표, 영구 기기 ID, 광고 ID, 설치 ID
4. allowlist에 없는 키는 `extra="forbid"`로 거부한다.
5. 이벤트에는 이름, 이메일, 전화번호, 학교/학년 조합 등 직접 식별자도 추가하지 않는다. 해당 데이터가 제품 기능에 필요하면 분석 이벤트와 별도 접근통제 저장소를 사용한다.

## 현재 생산 이벤트의 PII 등급

| EventType | 허용 payload | PII 등급 | 분석 저장 허용 |
|---|---|---|---|
| `검산결과` | `passed`, `error_kind`, `mode`, `persona` | 낮음 — 오류 분류만 | 허용 |
| `힌트제공` | `hint_level`, `mode`, `persona` | 낮음 — 노출 레벨만 | 허용 |
| `시각화조작` | 기존 봉투 계약 | **P0 보류** | payload 내부 자유형이므로 분석 envelope producer에 연결하지 않음 |
| `막힘` | `turn_count`, `mode`, `persona` | 낮음 — 누적 턴 수만(임계 도달 시점 실측값) | 허용 |
| `힌트요청` | `mode`, `persona` | 낮음 — 값 필드 없음(발생 자체가 신호) | 허용 |
| `답입력` | `server_latency_ms`, `mode`, `persona` | 낮음 — 서버 기준 지연 ms만(입력 *내용*은 싣지 않는다) | 허용 |
| `문제시도` | `is_correct`, `source` | 낮음 — 정오 불리언·채점 경로 라벨(답안 원문 미포함) | 허용 |
| 그 외 휴면 EventType | 없음 | 미정 | producer 금지 |

위 4종(`막힘`·`힌트요청`·`답입력`·`문제시도`)은 v1 작성(2026-08-14) 이후 편입된 생산 좌석이다(S3-16: 막힘·힌트요청·답입력 · EOS-57: 문제시도). 넷 다 payload가 **비식별 스칼라와 폐쇄 라벨뿐**이라
등급이 기존 2종과 같다 — 학생 원문·좌표·기기 식별자를 담는 필드가 없다. `mode`·`persona`는 개인이 아니라
**코호트 태그**(예: `suneung`·`A_일반고고3`)이므로 그 자체로는 재식별 축이 아니지만, §payload 규칙 5의
직접 식별자와 결합 저장하지 않는다는 전제에서만 '낮음'이 유지된다.

**이 표는 `EVENT_DATA_CONTRACT`와 동기화 상태를 기계가 강제한다** — 생산 계약에 EventType이 추가됐는데
이 표에 행이 없으면 `test_pii_policy_covers_all_produced_event_types`가 실패한다. v1이 3종만 담은 채
생산 좌석이 7종으로 늘어난 한 달간(2026-08-14~09-15) 아무 검사도 그것을 지적하지 못한 것이 이 가드의 등재 이유다.

`시각화조작`의 기존 `payload`는 조작별 자유형이라 P0의 타입별 allowlist 원칙과 맞지 않는다. 해당 이벤트를 분석 envelope에 연결하기 전에 별도 세부 allowlist와 PII 검토를 추가한다.

## 보존·삭제

- PostgreSQL `AttemptEvent` 보존 파기는 `purge_expired_records()`가 `event_at` 기준으로 집행한다.
- 보존 연수는 `Settings.pii_retention_years`가 정하며 현재 구현 기본값은 3년이다.
- 외부 분석 저장소(ClickHouse, object store 등)를 도입하기 전에는 동일한 보존·삭제·백업·접근통제·정합성 검증 경로를 설계하고 검증해야 한다.
- `event_uuid`/`received_at`의 DB 영속 및 PostgreSQL unique 제약은 DP-03의 migration 전까지 완료로 간주하지 않는다.

## 검증

`tests/backend/schema/test_analytics_event.py`는 다음을 검증한다.

- 필수 envelope, schema version, 발생/수신 시각 의미
- unknown top-level field 거부
- 금지 PII 키 거부
- 타입별 payload allowlist 강제
- mobile source의 session ID 요구
- 수신 시각이 발생 시각보다 빠른 입력 거부
- **위 PII 등급표가 `EVENT_DATA_CONTRACT` 생산 EventType 전건을 덮는가**(문서↔계약 드리프트 차단)
