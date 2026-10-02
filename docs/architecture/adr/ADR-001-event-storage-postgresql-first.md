# ADR-001 — 이벤트 저장소: PostgreSQL 우선, 확장은 실측 후 결정

- **상태:** 채택
- **결정일:** 2026-08-02
- **대상:** EOS #84 이벤트 분석 · #85 품질 모니터링
- **관련:** `docs/architecture/00_overview.md`, `docker-compose.prod.yml`, `src/backend/alembic/versions/20260529_0224_bb30b816083d_activity_dialogue_assessment_timeseries_.py`

## 맥락

WhyMath의 장기 아키텍처 문서는 PostgreSQL·TimescaleDB·ClickHouse를 데이터 저장소 후보로 언급한다. 그러나 배포 구성과 migration을 실측하면 현재 운영 DB는 `pgvector/pgvector:pg16` 기반의 일반 PostgreSQL 16이다.

`attempt_event` 등 시계열 테이블의 `create_hypertable()` 호출은 TimescaleDB extension이 존재할 때만 실행된다. 현재 compose는 TimescaleDB extension을 제공하지 않으므로 해당 테이블은 일반 PostgreSQL 테이블이다. 이전 migration은 extension이 추가된 뒤 자동으로 다시 실행되지 않는다.

학생 학습 이벤트는 미성년자 개인정보와 연결될 수 있다. 저장소를 추가하면 보존·삭제·접근 제어·백업·이관 책임도 함께 늘어난다. 아직 ClickHouse 소비자, 운영 dashboard, 분석 SLO 위반, 이벤트 처리량 근거가 없다.

## 결정

1. P0/P1 데이터 플랫폼의 원본 이벤트 저장소는 **현재 PostgreSQL 16**으로 한다.
2. 이벤트 원천은 기존 `attempt_event`를 계약·멱등성·보존 규칙에 맞게 확장한다. 원본 clickstream을 집계 테이블에 무분별하게 복제하지 않는다.
3. TimescaleDB, ClickHouse, 범용 Event Bus는 이번 단계에서 도입하지 않는다.
4. 새 저장소로 데이터를 복제하기 전에 해당 저장소의 보존·삭제·백업·접근통제·정합성 검증 경로를 구현하고 검증한다.

## 근거

| 실측 대상 | 사실 | 근거 |
|---|---|---|
| 운영 DB 이미지 | `pgvector/pgvector:pg16`; TimescaleDB 서비스 없음 | `docker-compose.prod.yml:85-102` |
| hypertable 변환 | extension 존재 시에만 `create_hypertable()` 실행 | `src/backend/alembic/versions/20260529_0224_bb30b816083d_activity_dialogue_assessment_timeseries_.py:412-432` |
| 이벤트 원천 | `AttemptEvent`가 `event_at`, `event_type`, `event_data`를 보유 | `src/backend/whymath_backend/schema/activity.py:303-358` |
| 보존 파기 | `AttemptEvent`와 `UserBehaviorMetrics`는 PostgreSQL 보존 파기 계획에 포함 | `src/backend/whymath_backend/privacy/retention.py:43-90` |
| 기존 관측성 | 앱 SLI는 `ServiceMetrics`/readiness/alerting으로 이미 측정 | `src/backend/whymath_backend/app.py:486-612` |

## TimescaleDB 전환 조건과 필수 작업

다음 중 하나가 실측으로 확인될 때만 TimescaleDB 전환 ADR을 새로 작성한다.

- PostgreSQL 시간 범위 분석 쿼리가 합의된 SLO를 지속적으로 위반한다.
- 이벤트 보존량과 시간 범위 집계 비용이 일반 PostgreSQL 운영 한계를 넘는다.
- 실제 제품 기능이 시계열 chunk pruning 또는 continuous aggregate를 필요로 한다.

전환 ADR과 구현은 최소한 아래를 포함해야 한다.

1. pgvector와 TimescaleDB extension을 함께 제공하는 **검증된 커스텀 이미지 또는 빌드 절차**와 extension 활성화 검증
2. 이미 존재하는 일반 테이블을 hypertable로 전환하는 **별도 migration**
3. 기존 데이터 백업, 복구, rollback 리허설
4. unique constraint/파티션 키 호환성, retention job, 쿼리 성능 측정
5. staging에서 migration upgrade/downgrade와 실제 데이터 검증

이미지를 교체하거나 extension을 설치하는 것만으로는 과거 조건부 migration이 재실행되지 않으므로 기존 테이블은 자동 전환되지 않는다.

## ClickHouse 도입 조건과 필수 작업

ClickHouse는 다음 근거가 모두 갖춰질 때만 별도 ADR로 검토한다.

1. 월 이벤트량과 보존기간이 PostgreSQL/TimescaleDB의 비용·성능 한계를 넘는다는 실측
2. 제품·운영의 실제 분석 소비자와 대시보드 요구
3. OLTP 학생 요청과 분석 워크로드 경합의 관측
4. 분석 쿼리 SLO 및 실패 기준
5. 미성년 학습 데이터의 접근통제, 보존, 삭제, 백업, 이관 및 정합성 검증 설계

도입 전에는 PostgreSQL을 원천으로 유지한다. ClickHouse는 원천의 대체가 아니라 분석용 파생 저장소가 될 경우에도 사용자 삭제·보존 요청이 두 저장소에서 모두 집행되는 것을 검증해야 한다.

## 결과

- 단기 운영 복잡도와 개인정보 삭제 공백을 줄인다.
- 이벤트 계약·멱등성·PII 정책을 저장소 확장보다 먼저 완성한다.
- ClickHouse/TimescaleDB는 “계획된 스택”과 “현재 배포됨”을 구분해 표현한다.
- 장기 아키텍처 문서의 다중 저장소 표기는 후보·목표 상태로 유지하되, 현재 배포 상태로 읽히지 않게 한다.

## 재검토

P1 이벤트 writer와 세션/퍼널 집계가 실제 트래픽에서 동작한 뒤, 분석 SLO·이벤트량·보존기간·소비자 근거를 포함한 운영 리포트로 재검토한다.

## 추기 (2026-08-31 — EOS-48)

EOS-48이 `attempt_event`에 nullable `event_time`(클라이언트 신고 발생 시각) 컬럼을 추가했다(마이그레이션 `c9bc2555282e`). 본 ADR의 hypertable 전환 조건·절차와의 충돌 여부를 재확인한 결과 **무충돌**이다: ① 파티션 키(`event_at`)·복합 PK 불변 — `create_hypertable` 전환 절차는 컬럼 목록과 무관하게 동작한다 ② 컬럼은 NULL 지배적(신고 이벤트만 값)이라 압축·chunk 부담 미미 ③ `event_at`의 실측 의미(전 writer가 서버 now — 수신 시각)를 재정의하지 않고 발생 시각을 별도 컬럼으로 분리했으므로, 전환 시 파티션 의미도 그대로다. 귀속 계약(발생 우선·시계 왜곡 시 수신 폴백)은 `l2.learning_metrics_rollup.effective_event_moment`가 정본이다.

## 추기 (2026-10-02 — DP-03)

DP-03이 `attempt_event`에 nullable `event_uuid`(producer 재전송 멱등키)와 부분 UNIQUE 인덱스 `uq_attempt_event_event_uuid`(`WHERE event_uuid IS NOT NULL`)를 추가했다(마이그레이션 `a3f7c9d1e5b2`). 기존 BIGSERIAL `event_id`·복합 PK `(event_id, event_at)`는 불변이다. envelope의 두 시각은 새 컬럼 없이 기존 좌석을 쓴다: `received_at` = `event_at`(서버 수신·파티션 키), `occurred_at` = `event_time`(EOS-48).

**위 "TimescaleDB 전환 필수 작업 4(unique constraint/파티션 키 호환성)"가 이 인덱스로 구체화됐다 — 비호환이다.** hypertable의 UNIQUE 인덱스는 파티션 키 `event_at`을 포함해야 하는데, 재전송은 서버 수신 시각(`event_at`)이 매번 달라 `(event_uuid, event_at)` UNIQUE로는 재전송을 막지 못한다. 그래서 마이그레이션은 `attempt_event`가 hypertable이면 **예외로 중단**한다(조용히 복합 키로 약화하면 "멱등 보호 있음"으로 위장되기 때문). 전환 ADR은 멱등키 전용 비-hypertable 테이블 등 별도 좌석을 설계해야 하며, 그 전까지 재전송 방어의 정본은 이 인덱스 + `db.models.activity.insert_attempt_event_once`(`ON CONFLICT DO NOTHING`)다.
