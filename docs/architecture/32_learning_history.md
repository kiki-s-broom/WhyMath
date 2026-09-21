# 32. EOS 학습 이력(Learning History) 설계

> **범위**: 학생 행동 이벤트에서 학습자 상태 추정에 이르는 학습 데이터 기반의 구조 확정 — Raw Event / Learning History / Learner State 3계층 분리, Evidence와 Mastery 분리, 버전 고정, 시간 모델, 개인정보 경계.
> **상태**: 설계 확정(2026-08-25). 외부 EOS 설계안(32_학습 이력)을 WhyMath 현행 구현과 대조 검토하여 정정 수용. 후속 구현 태스크 5종 등재(EOS-32, EOS-45~48).
> **관련**: `docs/architecture/02_learner_model.md`, `docs/architecture/44_eos_version_management.md`, `docs/architecture/04a_wh1_tutoring_harness.md`, `docs/standards/eos_identity_layer_011_1_decision.md`, `schemas/v1.0/schema_v1.0.md` 도메인 4~7, `docs/strategy/subject_expansion_readiness.md`

---

## 1. 핵심 설계 원칙 8가지

1. **Raw Event와 Learning History를 분리한다.**
2. **Learning History와 Learner State를 분리한다.** 학습 이력은 사실의 시간축 기록이고, Learner State는 그것으로부터 추론한 현재 추정값이다. 같은 테이블에 섞지 않는다.
3. **원본 이벤트는 갱신하지 않는다(append-only).** 단 "영구 불변"이 아니라, 삭제는 오직 개인정보 절차(삭제권·보존기한 파기)로만 수행하고 감사는 잔존한다(§6).
4. **Mastery는 결과이며 Evidence가 원본이다.** `mastery = 0.76`만 저장하지 않고, 왜 그 값인지 추적 가능한 증거 시계열을 유지해 모델 교체 시 재계산할 수 있게 한다.
5. **Problem ID뿐 아니라 Version ID를 기록한다.** 학습 기록은 당시 사용한 콘텐츠 버전에 고정된다(44번 문서 원칙 6과 동일).
6. **Attempt / Submission / Hint / Step을 구분한다.**
7. **Subject-neutral core + Subject extension 구조를 원칙으로 확정한다.** 단 실구현은 과목 확장 착수 트리거 전까지 보류한다(§9).
8. **파생 learner state는 언제든 history로부터 재계산 가능해야 한다.**

이 8가지는 Architecture Decision으로 확정한다.

---

## 2. WhyMath 맥락에서의 조율

### 2.1 전제 문서의 실재성 정정

외부 EOS 설계안이 참조하는 `204_교육 이벤트 시스템`, `205_공통 메타데이터` 문서는 이 저장소에 **문서로 존재하지 않는다**. 해당하는 실질 정본은 코드에 있다:

- 이벤트 payload 계약 정본: `src/backend/whymath_backend/schema/event_data_contract.py`(EVENT_DATA_CONTRACT)
- 이벤트 envelope·멱등키·PII 금지키 차단: `src/backend/whymath_backend/schema/analytics_event.py`
- 감사 이벤트: `src/backend/whymath_backend/db/models/audit.py`(deletion_audit·privacy_audit·defect_report — append-only, UPDATE/DELETE 라우터 없음)

따라서 본 문서는 "204/205 선행 문서에 기반한다"가 아니라, **위 코드 계약을 정본으로 삼아 32번 계층을 그 위에 정의**한다. 204/205를 별도 문서로 착지시킬 필요가 생기면 그때 이 코드 계약을 문서화하는 방향으로 작성한다(코드가 선, 문서가 후).

### 2.2 ID 체계

외부안의 `LS_01JXYZ...`, `ATT_...` 같은 프리픽스+ULID 예시는 채택하지 않는다. `docs/standards/eos_identity_layer_011_1_decision.md`에서 확정한 대로 **UUID PK(`gen_random_uuid` server_default) + 의미적 canonical ID(`math.<area>.<slug>`) 혼합**을 유지한다. "ID는 무의미하다"는 원칙은 이미 거부된 바 있다. 본 문서의 모든 예시 ID는 UUID로 읽는다.

### 2.3 3계층 분리는 신규 도입이 아니라 기존 구조의 명문화

외부안의 "Raw Event → Learning History → Learner State" 분리는 WhyMath 코드에 **이름 없이 이미 존재**한다. 본 문서의 역할은 이 분리를 ADR로 동결하고, 확인된 갭만 보강하는 것이다.

| 계층 | 의미 | 기존 구현 |
|---|---|---|
| Raw Event | 원자적 행동 사실, 갱신 없음 | `attempt_event`(TimescaleDB hypertable, BIGSERIAL+event_at 복합 PK, INSERT 전용 — `db/models/activity.py:238`), `evidence_event`(payload 봉투 암호화) |
| Learning History | 교육적 의미가 부여된 시계열·이력 | `learning_session`·`problem_attempt`(`db/models/activity.py`), `concept_mastery_history`·`skill_mastery_history`(append-only 측정 시계열 — `db/models/assessment.py`), `daily_learning_metrics` 등 롤업 3종(`db/models/timeseries.py`) |
| Learner State | 추론된 현재 학습자 상태 | `UserStateSnapshot`(`db/models/user.py:282`), `l2/learner_state.py` 조립기, `MisconceptionHypothesisRecord` |

> **다른 축 1건 (EOS-79)**: 위 3계층은 "얼마나 가공됐는가"를 묻는다. "무엇에 대한 증거인가"
> (Attempt·Evaluation·Assessment·Mastery)는 별도 축이며 `evidence_layer_boundary.md`가 정본이다.
> 한 축의 배정으로 다른 축을 추론할 수 없다 — 예: `concept_mastery_history`는 여기서 Learning
> History이고 그쪽에서 Mastery다. **충돌 시 이 문서(선행 정본)가 우선한다.**

주의: Learning History는 단일 정규화 테이블이 아니라 **목적별 다중 테이블**(이벤트 로그·측정 시계열·롤업·증거)이다. hypertable 시계열 + 삭제권 오케스트레이션이라는 이 workload에는 이 구조가 맞으며, 단일 거대 history 테이블을 새로 만들지 않는다.

---

## 3. 데이터 흐름

```
학생 행동
   ↓
Raw Event (attempt_event / evidence_event — append-only)
   ↓ semanticization
Learning History (learning_session / problem_attempt / mastery_history / rollups)
   ↓ evidence
Evidence (evidence_links / concept_mastery_history / pedagogy_evidence)
   ↓ inference (순수 추정 커널: l2/bkt.py, irt.py)
Learner State (UserStateSnapshot / LearnerState 조립 / MisconceptionHypothesis)
   ↓
AI Tutor · Learning Path · Analytics · Teacher Dashboard
```

L2 구현은 이미 이 파이프라인 형태다: `l2/mastery_tracking.py`는 "직전 측정 SELECT → 순수 BKT 계산 → `concept_mastery_history` append-only INSERT"의 얇은 DB 래퍼이고, `l2/learning_metrics_rollup.py`는 3개 원천 테이블만으로 일별 멱등 upsert를 수행한다("측정된 것만 적재, 추론 지표 날조 금지").

---

## 4. 엔티티 모델 — 기존과 신규의 구분

| 외부안 엔티티 | 판정 | 근거 |
|---|---|---|
| LearningSession | ✅ 기존 유지 | `learning_session`(session_type, 카운트, focus/engagement 점수) |
| ProblemAttempt | ✅ 기존 유지 + 보강 | `problem_attempt`(is_correct, student_answer, used_hint, stuck_at_step, step_times JSONB). 버전 고정은 EOS-47에서 보강 |
| AnswerSubmission | 🆕 신규 (EOS-32) | 다회 제출의 정규 기록이 없음. attempt_event로의 재구성도 불가 — `답입력` 이벤트 payload(`ResponseLatencyEventData`, `schema/event_data_contract.py`)는 응답 본문·채점 결과를 담지 않는 지연 신호다. 과거분 백필 없이 신규 수집 시작 |
| HintUsage | 🆕 신규 (EOS-45) | 현재 `used_hint` 불리언뿐. 횟수·레벨·엔람시간 필요(무힌트 정답과 힌트 3회 정답의 숙련도 해석 구분) |
| SolutionStep(학생 풀이) | 🆕 신규 (EOS-46) | 현재 `step_times` JSONB + attempt_event 분산. 23_단계별 풀이와 정합 필요. **단 `db/models/solution_node.py`의 `SolutionNode`는 WH-S AI 솔버의 MCTS 노드(학생 데이터 아님)이므로 명칭·책임을 명시 구분한다** |
| MasteryEvidence | ✅ 기존 유지 | `concept_mastery_history`/`skill_mastery_history` append-only 시계열 + `evidence_links`(polarity ±1) |
| MisconceptionObservation | ✅ 기존 유지 | `MisconceptionHypothesisRecord`(활성 가설) + `evidence_links`(지지/반박 누적). suspected→likely→confirmed→remediated 상태 전이 정신과 일치 |
| LearningHistorySummary | ✅ 기존 유지 | `daily_learning_metrics`·`user_behavior_metrics` 롤업 + `UserStateSnapshot` |
| LearningActivity(활동 단위) | ⚠️ 부분 | 세션→attempt 직결 + attempt_event가 활동 분해를 담당. 문제풀이 외 활동(개념학습·시각화 조작 등)이 1급 엔티티로 필요해지면 그때 분리 검토. 현재는 이벤트로 충분 |

### AnswerSubmission 분리의 근거

학생은 문제 하나에 답을 여러 번 제출할 수 있다(오답 → 오답 → 정답). Attempt에 최종 답만 남기면 "두 번째 시도의 오답이 어떤 오개념을 시사하는가"가 손실된다. 분리된 submission 시퀀스는 오개념 시스템(`evidence_links`)의 핵심 입력이다.

**과거 이력 백필은 불가하다.** `attempt_event`의 `답입력` 이벤트는 응답 본문·채점 결과를 담지 않는 지연 신호(`ResponseLatencyEventData` = `server_latency_ms`·`mode`·`persona`뿐)이므로, 과거 제출 시퀀스를 이벤트 로그에서 재구성하는 것은 대화 타이밍으로 제출 레코드를 *날조*하는 일이다. 따라서 과거분은 `problem_attempt.student_answer`의 최종값만 복구 대상이고, 시퀀스 수집은 신규 엔티티 배포 시점부터 시작한다.

### 이관·병행 전략 — EOS-32 구현 확정 (2026-08-30)

EOS-32가 `answer_submission` 테이블(ORM `db/models/answer_submission.py` · schema `schema/answer_submission.py` · alembic `8f0b8e906362`)을 착지시키며, 위 백필 불가 판정을 다음 운영 전략으로 명문화한다:

1. **데이터 이관 0건(의도적)** — 마이그레이션 `8f0b8e906362`는 빈 테이블만 만든다. 과거 attempt의 `student_answer` 최종값을 `answer_submission`으로 *복제 적재하지 않는다*: 최종값 1건을 `sequence_no=1`로 넣으면 "제출이 1회뿐이었다"는 시퀀스를 날조하게 된다(실제 제출 횟수는 소실됐고 복원 불가). 과거분의 정본은 계속 `problem_attempt.student_answer`다.
2. **신규 수집 시작점** — 시퀀스 수집은 이 마이그레이션이 적용되고 제출 writer가 배선된 시점부터다. **writer 배선은 EOS-32 범위 밖**(EOS-32 = L1 영속 좌석 + privacy 3종 배선까지·정본화와 집행의 별항 구분): 제출 처리 서빙 경로가 이 테이블에 적재를 시작하는 것은 후속 태스크 몫이며, 그 전까지 이 테이블은 빈 좌석이다 — 좌석 존재를 수집 작동으로 오인하지 않는다("작동 신호 없는 알고리즘 부착 금지"의 데이터 축).
3. **병행 기록(이중 기록·정본 구분)** — writer 배선 후에도 `problem_attempt.student_answer`는 *최종값 캐시*로 계속 기록한다(기존 소비자·롤업·export 호환 — 제거·개명 0). 시퀀스의 정본은 `answer_submission`이고, 정합 계약은 "attempt의 `student_answer` == 그 attempt의 `max(sequence_no)` 제출의 응답"이다. 두 기록이 어긋나면 writer 결함이다(조용히 넘기지 않고 로그).
4. **시퀀스 부재의 해석(정직)** — `answer_submission` 0건인 attempt는 「배포·배선 이전 과거분」 또는 「writer 미경유 경로」다. *"제출이 없었다"로 해석 금지* — 시퀀스 유무로 과거/신규를 가를 뿐, 부재를 행동 신호로 쓰지 않는다.
5. **privacy 3종 배선(§11 acceptance 이행)** — 삭제권 `_ERASURE_PLAN`(user_id·attempt보다 먼저), 보존 파기 `_RETENTION_PLAN`(`submitted_at` NOT NULL 축), 반출 `_EXPORT_PLAN`(`answer_submissions` 카테고리) 등재 완료. 완결성은 `test_erasure_plan_completeness`가 metadata 전수 스윕으로 동결한다.
6. **봉투 암호화(§11-4 "적용 검토"의 판정)** — `raw_response`·`latex`·`canonical_ast`는 `problem_attempt.student_answer`·`handwriting_uri`와 같은 계층의 *미성년 풀이 데이터*다. 이 테이블만 선행 암호화하면 같은 데이터가 두 테이블에서 다른 보호를 받는 비대칭이 생기므로, 봉투 암호화 컬럼은 `student_answer` 계열과 **일괄 판단**한다(SEC 계열 후속 — `dialogue_turn` 봉투 암호화 선례의 확장 축). 그때까지의 평문 저장 책임 경계는 `problem_attempt` 기존 방침과 동일(저장·동의 계층 문서화).

### 이관·병행 전략 — EOS-45 HintUsage 구현 확정 (2026-08-30)

EOS-45가 `hint_usage` 테이블(ORM `db/models/hint_usage.py` · schema `schema/hint_usage.py` · alembic `0e148995e6e9`)을 착지시킨다. EOS-32 전략과 동형이되 과거 이력의 사정이 다르다:

1. **과거 힌트 이력은 attempt_event에 *부분* 존재하나 백필하지 않는다(의도적)** — 실측: `힌트제공` 이벤트(`HintEventData`)는 hint_level을 담고 `힌트요청` 이벤트는 레벨조차 없다. 둘 다 hint_id·view_duration_ms가 없고, 무엇보다 `힌트제공`은 AI *공급*(supply) 신호이지 학생 *열람*(usage) 기록이 아니다 — 이벤트를 usage 행으로 승격하면 절반(식별자·열람시간)을 날조하고 의미(공급≠열람)를 오염시킨다. 과거 분석은 attempt_event를 그대로 쓰면 되고(하네스 지표 ⑤·⑫), `hint_usage` 수집은 배포·writer 배선 시점부터다.
2. **used_hint 병행(대체 아님)** — `problem_attempt.used_hint`와 기존 소비자(`l2/learning_metrics_rollup`의 `daily_hint_reliance_rate`)는 불변. `hint_usage`는 불리언이 잃는 축(횟수·최대 레벨·열람시간)의 원천이며, 파생 불리언과 기록 used_hint의 일치는 검증 가능한 병행 신호다(가용성 증명 = `tests/backend/l2/test_hint_rate_mastery_input.py` — L2 알고리즘 무변경, mastery 추정·rollup 배선 확장은 후속).
3. **소유 정합·privacy** — EOS-32 PR #902 P1의 (attempt_id, user_id) 복합 FK 관례를 신설 시점부터 적용(참조 대상 UNIQUE는 EOS-32 것 재사용). privacy 3종(erasure `user_id`·retention `requested_at`·export `hint_usages`) 등재 완료, 완결성은 `test_erasure_plan_completeness`가 동결.
4. **writer 배선은 범위 밖** — 힌트 서빙 경로가 이 테이블에 적재를 시작하는 것은 후속 몫이며, 그 전까지 빈 좌석이다(좌석 존재 ≠ 수집 작동).

### 이관·병행 전략 — EOS-46 StudentSolutionStep 구현 확정 (2026-08-30)

EOS-46이 `student_solution_step` 테이블(ORM `db/models/student_solution_step.py` · schema `schema/student_solution_step.py` · alembic `a926d39f126a`)을 착지시킨다. **저장 형태 판정(attempt_event 확장 기각·별도 정규 엔티티 채택)의 정본은 `docs/architecture/adr/ADR-002-student-solution-step-entity.md`**(hypertable 정본·실측 대조, 기각 대안·검토 결함 포함).

1. **백필 없음(의도적)** — 과거 step *내용*의 원천이 존재하지 않는다: `problem_attempt.step_times` JSONB는 단계별 *시간*만 담고, `attempt_event`의 `계산`·`그래프그리기` 등은 본문 없는 telemetry다. expression·canonical_ast·validation을 과거분에 만들어 넣는 것은 재구성이 아니라 날조다. 수집은 배포·writer 배선 시점부터.
2. **명칭·책임 구분** — `student_solution_step`(학생 제출물·미성년 PII 계열) ↔ `solution_nodes`(WH-S MCTS 탐색 노드·시스템 상태) ↔ `problem_step`(문항 저작 정본). 혼동 금지는 ADR-002 3자 대조표 + ORM docstring + 기계 동결(`test_distinct_from_whs_solution_node`).
3. **기존 흔적과의 병행** — `problem_attempt.step_times`(시간)·attempt_event telemetry(행위 신호)는 불변 유지. `student_solution_step`은 *내용·검증·개념 태그* 축의 신규 원천이며 셋은 서로 대체하지 않는다.
4. **소유 정합·privacy** — EOS-32 복합 FK 관례 적용(참조 대상 UNIQUE 재사용). privacy 3종(erasure `user_id`·retention `submitted_at`·export `student_solution_steps`) 등재 완료·완결성 스윕 동결.
5. **writer 배선은 범위 밖** — step 제출 서빙 경로의 적재 시작은 후속 몫(빈 좌석·좌석 존재 ≠ 수집 작동). validation 채움도 그 writer가 SymPy 검증 경유로 수행한다(검증 계약 불변).

### 이관·병행 전략 — EOS-48 시간 모델 구현 확정 (2026-08-31)

EOS-48이 §7의 두 갭을 착지시킨다(신규 테이블 없음 — 기존 3테이블 nullable 컬럼 추가·alembic `c9bc2555282e`):

1. **event_time/ingested_at 분리(실측 기반 비대칭 배치)** — `attempt_event.event_at`은 실측상 전 writer가 서버 now(UTC)를 넣는 **수신 시각**이라 *발생* 쪽(`event_time`)만 추가, `problem_attempt.started_at/ended_at`은 클라 신고 **발생 시각**이라 *수신* 쪽(`ingested_at`)만 추가했다(기존 컬럼 재정의 0). 귀속 계약(발생 우선·시계 왜곡=발생>수신은 수신 폴백·미신고는 수신)은 `l2.learning_metrics_rollup.effective_event_moment`가 정본·테스트 동결. **롤업 소비 배선 완료(PR #903 P2)**: `_fetch_events`가 event_time을 읽고 창 필터를 SQL 등가식(`LEAST(COALESCE(event_time, event_at), event_at)`)으로 걸며 소크라테스 귀속이 `EventFact.effective_at()`을 경유한다 — writer 부재(전행 NULL)에서는 기존 산출과 비트동일(회귀 테스트 동결)이라 배선이 no-op 안전이고, writer가 붙는 순간 지연 도착이 발생일 롤업 재실행에 잡힌다.
2. **백필 없음(의도적)** — 기존 행의 `event_time`/`ingested_at` 백필은 수신 시각 복제 = 날조라 하지 않는다(마이그레이션도 server_default를 달지 않아 ALTER 시점 백필 날조를 구조적으로 차단 — 테스트 동결). NULL=미기록이 정직한 상태.
3. **active/idle 실측 좌석 + 병행 지표** — `learning_session`/`problem_attempt`에 `active_seconds`/`idle_seconds`(NULL=미측정·0 날조 금지·경과 승격 백필 금지 — §7 "측정된 것만 적재"). 롤업은 기존 `daily_active_minutes`(경과 기반)를 **재정의하지 않고** `daily_measured_active_minutes`(실측 세션만 합산)·`daily_active_measured_ratio`(계측 작동 비율 상시 보고 — "작동한 비율" 원칙)를 병행 추가했다.
4. **privacy 3종 무변경 검토(검증 가능)** — 신규 테이블 0이라 플랜 변경 0. 3테이블의 기존 플랜 커버 유지·파기 축 불변·신규 컬럼의 export payload 노출은 `tests/backend/privacy/test_event_time_active_time_privacy.py`가 기계로 동결.
5. **ADR-001 무충돌** — attempt_event 컬럼 추가는 파티션 키·복합 PK 불변이라 hypertable 전환 절차와 무충돌(ADR-001 추기 2026-08-31).
6. **writer 배선은 범위 밖** — event_time 신고·ingested_at 기록·heartbeat 기반 active/idle 계측의 클라·서버 배선은 후속 몫(빈 좌석·ratio 지표가 그 작동률을 상시 드러낸다).
   - **부분 착지 (PED-37 · 2026-09-07)**: `problem_attempt` 축의 서버 writer 2종이 배선됐다 — `api/me.py::submit_attempt`가 요청의 선택 필드 `started_at`(클라 신고 발생 시각)을 *그대로* 적재하고 수신 시각을 `ingested_at`에 분리 기록하며, `api/coach.py::_complete_problem`은 `dialogue.started_at`을 이관받는다. 미신고는 NULL 유지(서버 now 폴백 금지 — §EOS-48-2 '수신 시각 복제 = 날조'). 배경은 `started_at`이 상시 NULL이라 `harness/wh1_evaluation`의 since/until 집계와 `privacy/retention` 파기가 조용히 0행이었던 것이고, 집행은 `tests/backend/api/test_attempt_started_at_integration.py`(실 PG·개수 단언)가 동결한다. **남은 몫**: `attempt_event.event_time` 신고, heartbeat 기반 active/idle 계측, 그리고 클라이언트(Flutter)가 실제로 `started_at`을 보내는 배선.

---

## 5. 버전 고정 (44번 문서와의 연계)

학습 기록은 논리적 Entity가 아니라 **당시 사용한 Version에 고정**한다(44번 원칙 6).

- 설계는 `docs/architecture/44_eos_version_management.md`가 정본: Entity ID ≠ Version ID, Published immutable, Runtime VersionContext(problem_version_id·solution_version_id·pedagogy_version_id·prompt_version_id 등).
- 현재 미구현: `Problem.content_version_id`는 011_1 후속 태스크(ARCH-31)로 등재돼 있으나 미착지. **EOS-47**이 이를 `problem_attempt`까지 착지시킨다(선행: EOS-44 설계 + ARCH-31 실구현).
- 문제 수정 후에도 과거 기록이 원 version을 가리켜 재현 가능해야 한다(재현성 테스트가 acceptance).

## 6. 불변성과 삭제권 — "immutable"의 정정

외부안의 "Raw Event = immutable"은 미성년자 삭제권과 충돌하므로 WhyMath에서는 다음으로 정정한다:

1. 이벤트·이력 테이블은 **갱신하지 않는다**(append-only 관행 — 코드 전반에 존재).
2. **삭제는 오직 개인정보 절차로만** 수행한다:
   - 삭제권: `privacy/erasure.py`의 `_ERASURE_PLAN`(user 연결 테이블 명시 삭제, 완전성은 `tests/backend/privacy/test_erasure_plan_completeness.py`가 동결)
   - 보존 파기: `privacy/retention.py`의 `_RETENTION_PLAN`(`pii_retention_years` 초과분 파기, `retention_until` 경과 증거 purge)
   - hypertable 느슨참조 고아 방지: attempt_event orphan DELETE 트리거(`alembic/versions/20260604_0200`)
3. 삭제 후에도 **감사는 잔존**한다(`deletion_audit`은 user FK 없이 잔존).
4. DB 수준 WORM 강제(UPDATE/DELETE 차단 트리거)는 두지 않는다 — 삭제권 배관과 충돌하기 때문. 불변성은 API 부재와 관행으로 지키고, 파괴 행위는 감사로 잡는다.
5. 분석 제외는 삭제가 아니라 상태로 표현한다(excluded_from_analysis류). 테스트 계정 오염은 삭제 대상이 아니라 분석 플래그 대상.

## 7. 시간 모델

외부안 지적대로 두 가지가 현재 스키마의 실제 갭이며, **EOS-48**로 보강한다:

- **event_time / ingested_at 분리**: 오프라인 태블릿이 하루 뒤 sync하는 시나리오에서 서버 수신 시각을 사건 시각으로 착각하면 안 된다.
- **active / idle / elapsed 구분**: `session_end - session_start`를 학습 시간으로 쓰지 않는다(자리 비움 오염). 단 롤업의 "측정된 것만 적재" 원칙을 유지한다 — 클라이언트 heartbeat 등 **실측 신호가 있을 때만** active를 적재하고, 없으면 추정치를 날조하지 않는다.

## 8. Evidence와 Learner State의 분리

`mastery = 0.76`만 저장하지 않는다. 현행 구조가 이미 이 원칙을 구현한다:

- Evidence(원본): `evidence_links`(학습 이벤트 → 오개념 가설의 지지/반박, polarity ±1, retention_until), `concept_mastery_history` append-only 시계열, `l2/pedagogy_evidence.py`(처치·결과 이벤트, HMAC 키드 해시 가명화)
- 추정(순수): `l2/bkt.py`·`irt.py`·`ability_estimation.py`(DB 무관 순수 계산)
- State(출력): `UserStateSnapshot`, `l2/learner_state.py` 조립기

모델 교체 시 history로부터 재계산 가능해야 한다는 원칙 8의 근거가 이 분리다. 신규 evidence writer를 추가할 때는 **암호화 바이트만 수신하고 cipher에 접촉하지 않는** `evidence_event_store.py` 패턴을 따른다.

## 9. Subject-neutral 원칙 — 설계 확정, 구현 보류

과목 중립 core + 과목별 extension(response payload를 `response_type + payload`로 일반화)은 방향으로 **확정**한다. 단:

- WhyMath는 현재 수학 고정이며, `docs/strategy/subject_expansion_readiness.md`의 보류 대장 원칙(**착수 트리거 전 구현 금지**)이 적용된다.
- 따라서 본 문서에서는 "신규 학습 이력 엔티티를 설계할 때 수학 전용 필드를 핵심 스키마에 박지 않는다"는 **설계 제약**으로만 강제한다. `math_problem_id` 같은 수학 전용 컬럼을 핵심 테이블에 추가하는 것은 금지, 수학 특화 내용은 payload/확장 컬럼으로 격리.
- 물리·역사용 response_type 실구현은 과목 확장 트리거 이후다.

## 10. 저장소 분리 원칙

- 운영 이력: PostgreSQL(TimescaleDB hypertable 포함)
- 개념 관계: PG 단일 평면 개념 그래프(Neo4j 런타임 미도입 — 기존 결정)
- 학생 이벤트를 Knowledge Graph에 넣지 않는다. 그래프에서 쓰는 것은 `mastered / learning / struggling` 같은 **요약된 learner-state edge**까지다.
- AI Tutor 대화 전문은 Learning History에 넣지 않는다. 현행 구조 유지: `dialogue`/`dialogue_turn`(본문 AES-256-GCM 봉투 암호화)에 보존하고, 교육적으로 의미 있는 상호작용만 이벤트로 추출한다.

## 11. 개인정보 경계

학습 이력은 성취도·오개념·행동 패턴이 장기 누적되는 고민감 데이터다. 신규 엔티티 추가 시 다음 배선이 **acceptance의 필수 항목**이다:

1. `privacy/erasure.py` `_ERASURE_PLAN` — 삭제 대상 포함(완전성 테스트가 metadata 전수 스윕으로 강제)
2. `privacy/retention.py` `_RETENTION_PLAN` — 보존기한 파기 대상 포함
3. `privacy/export.py` — 반출 대상 포함(성적 예측 필드의 학생 표면 제외 정책 준수)
4. 본문류(payload·응답 원문)는 봉투 암호화 컬럼 패턴(`payload_encrypted` + nonce) 적용 검토
5. learner 참조는 pseudonymous `user_id`만 — PII 직접 컬럼 금지(envelope의 PII 금지키 차단과 동일 정신)

## 12. MVP 범위

- **MVP(현재 유지)**: learning_session / problem_attempt / attempt_event / mastery_history 계열 / 롤업 / evidence_links — 이미 존재.
- **이번 확정으로 보강(후속 태스크)**: AnswerSubmission(EOS-32) · HintUsage(EOS-45) · 학생 풀이 step(EOS-46) · 버전 고정(EOS-47) · 시간 모델(EOS-48).
- **EOS 단계(보류)**: cross-subject history, longitudinal record, KT 계열(BKT/DKT/Transformer) 교체 가능 구조는 원칙 4·8의 evidence 분리로 이미 확보 — 전용 인프라는 착수 트리거 후.

## 13. 후속 태스크

아래 5종은 `scripts/harness/backlog.py add`로 등재 완료(2026-08-25):

1. **EOS-32-answer-submission-entity** — AnswerSubmission 분리: attempt 내 다회 제출 시퀀스 정규화(스키마+ORM+alembic + 이관 전략 + privacy 3종 배선). **구현 착지 2026-08-30** — 이관·병행 전략은 §4 "이관·병행 전략" 확정(데이터 이관 0건·병행 기록·writer 배선은 범위 밖 후속).
2. **EOS-45-hint-usage-entity** — HintUsage 정규화: 힌트 횟수·레벨·엔람시간 1급 데이터화 + mastery 입력 테스트. **구현 착지 2026-08-30** — 이관·병행 판단은 §4 "이관·병행 전략 — EOS-45"(백필 없음·used_hint 병행·writer 배선은 범위 밖 후속).
3. **EOS-46-solution-step-event** — 학생 풀이 step 수준 이벤트: 23_단계별 풀이와 정합, SolutionNode와 명칭 구분, 테이블 분리 여부 ADR. **구현 착지 2026-08-30** — 판정 = 별도 정규 엔티티 `student_solution_step`(ADR-002·attempt_event 확장 기각), 백필 판정은 §4 "이관·병행 전략 — EOS-46".
4. **EOS-47-attempt-version-pinning** — problem_attempt 버전 고정: problem_version_id + evaluation_context(EOS-44 설계 + ARCH-31 Content Version 실구현 선행).
5. **EOS-48-event-time-active-time** — 시간 모델: event_time/ingested_at 분리 + active/idle 구분(롤업 "측정된 것만 적재" 원칙 유지). **구현 착지 2026-08-31** — 실측 기반 비대칭 컬럼 배치·귀속 계약(`effective_event_moment`)·병행 지표 2종, 상세는 §4 "이관·병행 전략 — EOS-48".

공통 acceptance: 신규 테이블은 §11의 privacy 3종 배선 + `test_erasure_plan_completeness` 통과.

---

## 14. 참고 문서

- `docs/architecture/02_learner_model.md` — LearnerState/MasteryState 정의(MasteryState는 미구현 명시)
- `docs/architecture/44_eos_version_management.md` — 버전 분리·VersionContext 정본
- `docs/architecture/04a_wh1_tutoring_harness.md` — evidence_links 설계 정본
- `docs/standards/eos_identity_layer_011_1_decision.md` — ID 체계 확정안
- `schemas/v1.0/schema_v1.0.md` 도메인 4~7 — 학습 활동 데이터 DDL 정본(hypertable 선언 포함)
- `docs/strategy/subject_expansion_readiness.md` — 과목 확장 보류 대장 원칙
- `src/backend/whymath_backend/schema/event_data_contract.py` — 이벤트 payload 계약 정본
- `src/backend/whymath_backend/privacy/erasure.py` / `retention.py` / `export.py` — 개인정보 3종 배선
