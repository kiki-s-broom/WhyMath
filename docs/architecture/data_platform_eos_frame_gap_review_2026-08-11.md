> **[OPS-41 회수 2026-10-05 — 이식 주석]** 이 문서는 고립 브랜치 `t608mk`(원 파일명 `data_platform_module_gap_review_r2.md`, 판정 기준 HEAD `d088ae77`)에서 회수했다. 같은 파일명의 다른 문서(`q8tvcx`의 r1 판정 진실성 재검증, OPS-38 ③ 소유)와 충돌하지 않도록 이름을 바꿨다. 본문의 태스크 번호는 등재 당시 값이며 main 동번호 별건과의 충돌로 **OPS-35 → OPS-114 · OPS-36 → OPS-115**로 재발급됐다(`OPS-37`·`QUAL-05`는 유지). 본문 판정은 수정하지 않았다.

# 데이터 플랫폼(Data Platform) 모듈 — 외부 EOS 틀 대조 **r2** (2026-08-11)

> **범위**: 외부 참고 문서 『20. 데이터 플랫폼』(기능 **84 이벤트 분석** · **85 품질 모니터링**
> — **WhyMath 전용이 아닌 일반적인 EOS(Education Operating System) 틀**, Kiki 제공 docx)를
> merged 정본에 대조한 기록. 설계는 WhyMath 불변식(미성년 PII 최소수집 · 침묵 실패 금지 ·
> 날조 금지 · 이중 회계 · 만료 없는 유예 금지 · 정본화≠집행 금지 · 과공학 금지) 안에서만 한다.
>
> **성격 — 왜 `r2`인데 v1의 후속이 아닌가**: 같은 이름의 `data_platform_module_gap_review.md`
> (2026-08-07)가 이미 있으나 그 문서는 **OPS-22 "선언≠배선" 탐지기의 구현 기록**이지 틀 대조가
> 아니다(그 문서 §4가 스스로 *"OPS-22는 '선언≠배선' 축만 다룬다"*고 한정). 즉 **기능 84/85에
> 대한 대조는 이 문서가 최초**다 — `docs/` 전수 grep에서 두 기능명이 **0건**이다(부록 A-0).
> 파일명 충돌을 피하려 `_r2`를 쓴 것이지 v1의 판정을 승계·재판정하는 문서가 아니다.
>
> **결론 4줄**:
> 1. **적재 배관은 과할 만큼 완비돼 있고 라이브 배선돼 있다.** `attempt_event` hypertable ·
>    `event_data_contract.py` 페이로드 계약 · 프라이버시 3배관(반출·삭제·파기) · writer 6종이
>    모바일 채팅 경유로 실제로 돈다. **갭은 "수집기가 없다"가 아니다.**
> 2. **관통하는 단일 진단 = "측정하는 코드는 두꺼운데, 측정 결과가 사람·시간을 건너 살아남는
>    경로가 없다."** 품질 모니터링의 세 홉 — 알림→사람 · **이력→저장소** · 스케줄→실행 —
>    이 전부 끊겨 있고, 그중 **이력 축만 소유자가 없었다**(→ **D3**).
> 3. **선언된 데이터 토폴로지가 실재하지 않는다.** ClickHouse·Prefect/Airflow가 스택 표·
>    5블록 표·24/7 운영 런북에 가동 중 서비스로 적혀 있으나 실물 0건(→ **D4**). 동일 유형
>    정정이 이미 두 번(Neo4j·OTel) 있었는데 **데이터 플랫폼 자신의 백본만 빠져 있었다.**
> 4. 진짜 갭 4건(D1~D4)을 설계하고 태스크 4건을 등재했다. 의도적 미채택 4건 · 정정 4곳 ·
>    반복 실수 1건(**SEC-12 결함의 1주 뒤 재발**) 등재.

관련 정본: `data_platform_module_gap_review.md`(동명 문서 — OPS-22 구현 기록, 이 문서와 다른 축) ·
`operations_module_gap_review.md`~`_r3.md`(운영 3부작 — 알림·백업·CI 강제 축의 소유처) ·
`ai_recommendation_module_gap_review.md`(§4-9 ClickHouse 미배선 최초 관측) ·
`learning_analytics_gap_review.md`(미머지 브랜치 — 중복 착수 확인 완료·부록 A-5) ·
`docs/standards/incident_response_slo.md`(SLO 5종·§6 정직한 공백) ·
`declared_unwired_audit.py`(선언≠배선 4축 감사기 — 이 문서의 판정 상당수가 이 대장을 읽는다).

---

## §0. 대조 기준 — 무엇을 "있다"로 세는가

이 문서는 **존재**와 **배선**과 **집행**을 구분한다. 세 층위가 섞이면 "코드가 있다"가
"돌아간다"로, "돌아간다"가 "막는다"로 잘못 읽힌다 — 이 저장소가 최소 6회 반복한 사고다.

| 층위 | 판정 기준 |
|---|---|
| **존재** | 모듈·함수·테이블이 저장소에 있다 |
| **배선** | 서빙 경로(HTTP·미들웨어) 또는 CI 잡이 실제로 그것을 부른다 |
| **집행** | 실패가 exit 1 또는 사람에게 도달하는 신호가 된다 |

판정 근거는 전건 실측이며 재현 명령은 **부록 A**에 병기한다(추론 등재 금지).

---

## §1. 기능 84 「이벤트 분석」 전수 대조

### 요약 표

| 틀 하위항목 | 판정 | 근거 |
|---|---|---|
| ① 학습 이벤트 수집 | **△ 2/8** | 8종 중 실제로 학생 트래픽이 행을 만드는 것은 힌트사용·AI대화 2종 |
| ② 사용자 행동 분석 | **🚫 의도적 미채택** | 범용 클릭스트림은 미성년 PII 최소수집과 충돌 — §3-① |
| ③ 학습 퍼널 분석 | **❌ 0** | 원천(`learning_session`) writer 영구 미신설이 선행 안건 |
| ④ 실시간 이벤트 스트림 | **🚫 의도적 미채택** | Phase 1 실사용자 0·단일 워커 — §3-② |
| ⑤ AI 분석 활용 | **△** | 추천↔결과 조인 키 부재·A/B 프레임워크 0 |

### ①의 정밀 — "적재 배관"과 "유입"을 구분한다

**배관은 완비돼 있다.** `AttemptEvent`(`db/models/activity.py:238` · 복합 PK
`(event_id, event_at)` · hypertable화 `20260529_0224_bb30b816083d`)에 writer **6종**이 있고,
전부 라이브 배선돼 있다:

| writer | 위치 | EventType | 적재 게이트 |
|---|---|---|---|
| `_log_verify_event` | `api/coach.py:1014` | 검산결과 | `student_solution` 비공백 |
| `_log_hint_event` | `:1099` | 힌트제공 | `hint_level is not None` |
| `_log_demand_event` | `:1154` | 힌트요청 | `is_answer_demand` True |
| `_log_stuck_event` | `:1190` | 막힘 | `is_stuck_turn_count`(5회+) True |
| `_log_response_latency_event` | `:1226` | 답입력 | 직전 학생 턴 `spoken_at` 존재 |
| `post_interaction` | `api/interactions.py:64` | 시각화조작 | 게이트 없음(요청 1건 = 1행) |

모바일 채팅(`chat_controller.dart:189,193` → `coach_api.dart:47,67`)이 stateless `/v1/coach`가
아니라 **stateful 세션 경로**를 쓰므로 **턴마다 조건부로 적재된다**. 게이트가 있는 것은 결함이
아니라 **날조 회피 설계**다 — 신호가 없을 때 행을 만들지 않는다.

**유입은 2/8이다.**

| 틀 요구 | 저장 좌석 | 실제 유입 |
|---|---|---|
| 힌트 사용 | `attempt_event`(힌트제공/힌트요청) | ✅ **유일하게 완전 배선**(supply·demand 양쪽) |
| AI Tutor 대화 | `Dialogue`+`DialogueTurn` | ✅ `coach.py:1891,1994,2307` |
| 문제 제출 | `ProblemAttempt` | ❌ writer는 `api/me.py:724`에 있으나 **클라 호출 0**(부록 A-2) |
| 정답/오답 | `ProblemAttempt.is_correct` | ❌ 동상 |
| 풀이 시간 | `ProblemAttempt.duration_seconds` | ❌ 동상 |
| 개념 학습 완료 | `ConceptMasteryHistory` | ❌ `POST /v1/me/attempts` 종속 → 실질 0 |
| 문제 시작 | `LearningSession.started_at` | ❌ **writer 영구 미신설**(2026-07-29·S3-16 소유) |
| 복습 완료 | — | ❌ **스키마 자체 부재** |

**복습 축의 비대칭(신규 관측)**: `S4-18`(done)이 `GET /v1/me/review-queue`를 착지시켰으나
`api/me.py:1441`이 명시하듯 **저장 컬럼·마이그레이션 없이 매 호출 순수 재계산**한다. 즉
**복습을 공급하는 쪽은 있고 닫는 쪽(완료 관측)이 없다.** 이것은 결함이라기보다 S4-18이 의도한
경계이지만, 틀의 "복습 완료율"은 이 구조에서 **원리적으로 산출 불가**임을 기록해 둔다.

### ⑤의 정밀 — 조인 키가 없다

`harness/recommendation_outcome_report.py`가 스스로 자인한다: *"결과 결합(추천→정답 여부 조인)은
아직 존재하지 않는다"* — `session_id`가 매 처치마다 새 placeholder라 조인 키가 없다. 이 모듈은
**"결합 0건 ≠ 효과 0"을 같은 화면에 항상 표기**한다(정직 표기의 좋은 선례). A/B 실험
프레임워크는 **0**이다 — 코드의 "A/B"는 전부 `step_break` 분류 라벨이지 실험 배정이 아니다
(부록 A-4).

---

## §2. 기능 85 「품질 모니터링」 전수 대조

### 요약 표

| 틀 하위항목 | 판정 | 소유 |
|---|---|---|
| ① 콘텐츠 품질 | **△** | 중복=`QUAL-01`(done)→`QUAL-02` · 재서술=`QUAL-03`(done)→`QUAL-04` · **이미지 품질 0** · **난이도 이상탐지 0**(`S4-15`) |
| ② AI 품질 | **△** | 단계검증·프로즈 누설은 서빙/CI 배선 · **런타임 PRM·hallucination 전용 탐지기 0** |
| ③ 시스템 품질 | **△** | `ServiceMetrics` 서빙 실배선 · SLO 5종 중 **2종 미측정**(`OPS-30`) |
| ④ 데이터 품질 | **○** | `validate.py` 11종 — 누락·중복·일관성·참조무결성 ✅ / **이상값 ❌** |
| ⑤ 운영 대시보드·알림 | **❌** | 대시보드 0 · 알림 `OPS-30` · **이력 무소유 → D3** |

### 검사 자산은 두꺼운데 집행은 얇다

하네스 62 + ops 12 모듈이 있으나 **CI에서 `python -m`으로 실행되는 것은 8스텝**이고, 그중
`qa_pipeline`은 **`continue-on-error: true`**(`ci.yml:192`)다. 나머지는
`declared_unwired_audit._MANIFEST[AXIS_CLI]`에 `_OFFLINE_REPORT`·`_BATCH_GENERATOR`·
`_LIVE_DEPENDENT` 등으로 **"사람이 손으로 돌리는 것이 의도"라고 선언**돼 있다. 이 대장이
"무엇이 CI에 없는가"의 단일 진실 원천이라는 점은 이 저장소의 강점이다 — 미배선이 **숨어 있지
않고 사유와 함께 등재**돼 있다.

다만 그 결과, 품질 검사의 상당수는 **존재하되 집행되지 않는다**. 대표 사례:
`problem_duplication_audit`(1366줄)는 `_OFFLINE_REPORT`로 *"실중복이 나와도 exit 1을 내지 않는
게이트 아님"*이라 명시돼 있고, `corpus_audit` 축은 `--max-defect-upper` 기본 1.0(=off)이라
**코드가 스스로 실질 게이트가 아님을 자인**한다(`qa_pipeline.py:226-230`).

### ⑤가 완전히 끊긴 지점 — 세 홉

| 홉 | 상태 | 소유 |
|---|---|---|
| 알림 → 사람 | `AlertLogNotifier`(`service_health.py:401`)가 `logger.warning`에서 종료. Slack/webhook/smtp/pagerduty **grep 0건** | `OPS-30`(todo) |
| **이력 → 저장소** | `qa_report.json` **아티팩트 미업로드** · 품질 지표 추세 테이블 **0건** | **무소유 → D3** |
| 스케줄 → 실행 | 호스트 스케줄러 0 · GH Actions nightly 1건(E2E+재검증, 품질 리포트 아님) | 일부 `OPS-31` · 롤업 축은 **무소유 → D1** |

런북이 이미 자인한다: *"breach는 로그에만 남는다. 로그를 보고 있지 않으면 알림이 아니다."*

---

## §3. 의도적 미채택 — 틀을 따르지 않는 것이 WhyMath의 방향인 항목

이 4건은 **결핍이 아니라 설계된 답**이다. 틀은 일반 EOS 기준이고, WhyMath에는 그 기준을
이기는 상위 제약이 있다.

### ① 범용 클릭스트림·UI 사용 패턴 수집 — **만들지 않는다**

틀 84-②는 "클릭 스트림 분석 · 화면 이동 경로 · 기능 사용 빈도 · UI 사용 패턴"을 요구한다.
WhyMath는 **미성년 개인정보 최소수집**(CLAUDE.md 보안 금기 — *"미성년자 개인정보를 분석·마케팅
외부 공유 금지"* · 의사결정 우선순위 #2 법적·윤리 준수 > #6 비용·효율)을 상위에 둔다.

**대안 설계(이미 착지)**: 범용 클릭스트림 대신 **교수학적으로 의미 있는 이벤트만**을 닫힌
어휘로 고정한다 — `EventType` 11종(`schema/enums.py:836`) + `event_data_contract.py`가 생산 6종의
페이로드 모양을 단일 진실원으로 동결. 즉 *"무엇이든 다 찍고 나중에 분석한다"*가 아니라
*"교수학이 읽을 신호만 계약으로 정의하고 그것만 찍는다"*. 이것이 84-②에 대한 WhyMath의 답이다.

**발화 조건**: 없음(영구). 화면 이동 경로가 필요해지면 개별 이벤트를 계약에 추가하는 방식으로만
확장한다 — 무차별 수집 계층은 도입하지 않는다.

### ② Event Bus·Kafka·실시간 대시보드 — **Phase 1에서 만들지 않는다**

`app.py:716`이 이미 *"Prometheus/StatsD 등은 과공학"*으로 명시 배제했다. 실사용자 0·단일 워커
단계에서 이벤트 버스는 **빈 파이프를 하나 더 만드는 일**이다(플레이북 "과공학 금지").

**발화 조건**: 동시 사용자 발생 + 다중 워커 도입. 다중 워커는 `incident_response_slo.md` §6이
이미 *"다중 워커 시 지표 해석 붕괴"*로 자인한 항목이라 그 시점이 자연 트리거가 된다.

### ③ 학습 중단률·이탈 지점 퍼널 — **퍼널이 아니라 결정이 선행 안건**

퍼널의 원천은 `learning_session`인데 그 writer는 **2026-07-29 영구 미신설 결정**(S3-16 소유)이다.
퍼널을 세우려면 먼저 그 결정을 뒤집어야 하므로, **이 문서는 퍼널을 등재하지 않는다** — 등재하면
소유자 없는 dead task가 된다. 대신 그 결정이 만든 *표기 붕괴*를 D2로 등재한다.

### ④ A/B 테스트 프레임워크 — **표본 이후**

실학생 표본이 0이다(`S3-01` 코호트가 Kiki 소유 게이트). 모델 비교 축은 이미
`agreement_gate_cli`가 **NO_DATA를 exit 2로 인코딩**해 "표본 없음"과 "판정 실패"를 구분한다 —
프레임워크를 새로 만들 것이 아니라 표본이 오면 그것을 쓴다.

---

## §4. 잔여 갭 설계 (D1~D4)

### D1 — by-design 유예가 **실재하지 않는 운영 절차**를 전제한다 (`OPS-35`)

**실측.** `COLLAB-03`(done·2026-08-10)이 `learning_metrics_rollup_cli.py`를 timeseries
3테이블의 실 writer로 착지시켰고, 감사기는 이를 `_OPERATIONS_BATCH`로 유예한다. 유예 사유
(`declared_unwired_audit.py:860-863`):

> *"운영 집계 배치 — 일 1회 크론/수동 실행이 **설계 확정값**이고(COLLAB-03 acceptance ⑥)
> 새 스케줄러 도입은 같은 태스크가 금지했다."*

그런데 그 "확정값"인 크론이 **어디에도 없다**:
- `grep -rn "learning_metrics_rollup" infra/ .github/ docker-compose*.yml scripts/` → **0건**
- `grep -rn "learning_metrics_rollup" docs/` → **0건** (런북에 실행 지시조차 없음)
- 정기 실행 인프라는 `docker-compose.prod.yml:156` `retention-purge`의 셸 루프 **1개뿐**

**왜 페이퍼 갭이 아닌가.** 3테이블이 프로덕션에서 영구 미갱신이면, 그것을 읽는 **학생 대면**
엔드포인트 `GET /v1/me/learning-metrics`(`api/me.py:3382`)가 **영구 빈 응답**이 된다.
서빙 영향이 있다.

**결정적 선례 — 같은 결함이 이미 한 번 고쳐졌다.** `SEC-12`(**done**·2026-08-03)의 제목이
그대로 *"보존 파기 정기 실행 배선 — 로직·CLI 완비인데 스케줄 0(정책 미집행 상태)"*이고,
notes가 결함 유형을 명명해 놨다: *"CLI가 생긴 것으로 문제가 해결됐다고 읽히기 쉬운 형태."*
그 해법이 바로 위에서 "유일한 정기 실행 인프라"로 발견된 `docker-compose.prod.yml:156`이다.

→ **COLLAB-03이 1주 뒤 같은 결함을 재생산했다.** 그리고 "새 스케줄러 도입 금지"를 근거로
유예됐는데, **SEC-12의 해법 자체가 새 스케줄러를 쓰지 않는다**(compose 서비스 + 셸 루프).
**유예 사유가 해법을 배제하지 않는다** — 이것이 이 갭의 핵심이다.

**설계.** SEC-12의 착지 패턴과 acceptance 3항 형태를 그대로 재사용한다: ①compose 진입점 1개
(신규 로직 0·CLI 호출만) ②배선 실재성 테스트 동결("존재함 ≠ 돌아감") ③"집계 0건"과 "실행
실패"가 구분되는 출력(이중 회계 금기). **유예 자체가 틀린 것이 아니라, 유예가 참조하는 절차가
부재한 것**이 갭이다.

### D2 — **구조적 불가**와 **일시적 무데이터**가 같은 `NO_DATA`로 뭉개진다 (`QUAL-05`)

**실측.** 같은 패키지의 형제 모듈이 **같은 죽은 원천을 정반대로 설명한다**:

| 모듈 | 같은 원천(`learning_session`)에 대한 서술 |
|---|---|
| `surrogate_baseline_report.py:143` | `_STRUCTURALLY_IMPOSSIBLE_FIELDS = {"session_completion_rate"}` — 주석이 근거까지 명시: *"LearningSession 생성자 호출이 src/ 전체에서 0건이고, writer는 2026-07-29 **영구 미신설 결정**"* |
| `pilot_kpi_baseline.py:202-208` | NO_DATA note: *"유효 세션 0건 — **파일럿 사용자가 세션을 열면** 리텐션 계측(가짜 0 아님)"* |

후자는 **"곧 온다"고 읽힌다.** 영원히 안 온다 — writer가 없기 때문이다.
`compute_retention` 4지표(`returning_user_rate`·`sessions_per_user`·`active_days_per_user`·
`return_gap_days_median`)가 전부 이 상태다.

**왜 금기 위반인가.** CLAUDE.md는 *"인프라가 죽으면 '측정 실패'가 보여야지 '0건 통과/미달'로
위장되면 안 된다"*고 정한다. 여기서는 **역방향 변형**이 일어났다 — **영구 불가가 '아직'으로
위장**된다. 리포트를 읽는 사람은 "파일럿만 돌리면 이 지표가 채워진다"고 계획을 세우게 된다.

**설계.** 신규 개념 0 — 형제 모듈의 `_STRUCTURALLY_IMPOSSIBLE_FIELDS` 기전을 그대로 재사용한다.
추가로 **만료 지점**을 건다: `learning_session` writer가 생기면 그 표시가 걷혀야 함을 테스트로
고정한다(만료 없는 유예 금지).

### D3 — 측정의 **이력 좌석이 없고, 그 배제의 전제가 방금 소멸했다** (`OPS-36`)

**실측.**
- `qa_report.json`은 **아티팩트 업로드조차 없다**. `ci.yml:193`이 `--json qa_report.json`으로
  리포트를 만들지만 그 잡에 `upload-artifact` 스텝이 없다(전체 워크플로 2건은 coverage 전용)
  → **러너 삭제와 함께 소멸**. 그런데 `ci.yml:190` 주석은 *"리포트는 그대로 남는다"*고 적었다 —
  **남는 곳이 없다.**
- 품질 지표 **추세 테이블 0건**(DB 41종 전수 — `timeseries.py`의 3종은 *학습 분석*이지 품질 아님).

**전제 소멸(이 문서가 만든 상태 변화).** `OPS-30` acceptance ④는 이렇게 적혀 있다:

> *"④ 범위 밖 동결 — **지표 영속화(ClickHouse 적재)**·경로별 지연 분해(S5)·다중 워커 합산
> 스크레이퍼는 포함하지 않는다."*

**2026-08-11 ClickHouse 미도입이 확정되면서(§D4·Kiki 결정) 그 배제가 지목한 기전 자체가
사라졌다.** 즉 영속화 축은 이제 **소유자도 만료 지점도 없는 상태**다 — CLAUDE.md
*"만료 없는 유예·제외 금지"*가 정확히 겨냥하는 형태다. → **PG/TimescaleDB 평면에서 재정위**하고,
두 태스크 notes에 소유 이전을 교차 기록한다.

**왜 중요한가.** 품질 *모니터링*의 정의상 **이력이 없으면 추세(품질 저하)를 볼 수 없다.**
매 실행이 단발 스냅샷이면 "지금 통과"만 알 수 있고 "나빠지고 있다"는 영원히 알 수 없다.

### D4 — 스택 선언 정직화 (`OPS-37`)

**실측.**

| 선언 | 실물 | 선언 위치 |
|---|---|---|
| ClickHouse(행동 로그) | docker-compose 3종 · `pyproject.toml` · `src/` import **전부 0** | `CLAUDE.md:73` 스택 표 · `00_overview.md:165,174` 5블록 표·보충 메모 · `OPERATIONS_24_7.md:29`(서비스 표+헬스체크) `:33`(부팅 의존 순서) `:96`(주 1회 백업) |
| Prefect/Airflow | 저장소 전수 **0건** | `00_overview.md:167` Content Pipeline 블록 |

**왜 지금까지 남았나.** 동일 유형 정정이 **이미 두 번** 있었다 — Neo4j(2026-08-10 통합점검) ·
OpenTelemetry(2026-08-11 운영 r3). 그리고 `ai_recommendation_module_gap_review.md:415`가
**이미 관측했다**: *"ClickHouse 행동 로그는 클라이언트 코드가 0이다 — 스택 표에 있으나 배선이
없다."* 관측이 **스택 표 정정으로 이어지지 않았다.** 데이터 플랫폼 자신의 백본이 두 차례
정정에서 빠져 있었던 셈이다.

**특히 위험한 것은 운영 런북이다.** `OPERATIONS_24_7.md`는 ClickHouse와 neo4j에 대해
**헬스체크 명령·부팅 의존 순서·백업 주기까지 지시**한다 — 존재하지 않는 토폴로지의 운영 절차다.
장애 시 이 런북을 따르는 사람은 없는 서비스를 찾게 된다.

**결정(Kiki·2026-08-11)**: **도입하지 않고 선언을 정직화**한다. **행동 로그 정본 =
PostgreSQL 16 + TimescaleDB 단일 평면**으로 확정 — pgvector가 6번째 store를 회피한 선례와
같은 논리이며, 이미 `attempt_event` hypertable이 그 역할을 하고 있다.

### §4 등재 요약

| 태스크 | 설계 | stage | layer | priority | 근거 |
|---|---|---|---|---|---|
| `OPS-35-learning-metrics-rollup-schedule-wiring` | D1 | S4 | infra | 3 | 유예가 실재하지 않는 크론을 전제 · 학생 대면 엔드포인트 영구 빈 응답 · SEC-12 재발 |
| `QUAL-05-structural-impossibility-vs-nodata` | D2 | S4 | backend | 3 | 형제 모듈이 같은 죽은 원천을 정반대로 설명 · 영구 불가가 '아직'으로 위장 |
| `OPS-36-quality-measurement-history-seat` | D3 | S4 | infra | 3 | 이력 홉 무소유 · OPS-30 ④ 배제의 전제(ClickHouse) 소멸 |
| `OPS-37-stack-declaration-honesty-clickhouse` | D4 | S3 | docs | 2 | 실물 0인 토폴로지를 런북이 운영 절차로 지시 · Neo4j·OTel 정정에서 누락된 백본 |

태스크는 전건 `backlog.py add` CLI 경유로 등재했다(ID 손편집 0).

**번호 배정 실측 기록**: 최초 시도한 `OPS-33`을 CLI가 **거부**했다 — 원격 브랜치
`claude/whymath-05-problem-bank-7en4l8`의 `backlog/tasks/`에 `OPS-33-yaml-spec-unwired-audit-axis`가
이미 있었다. 로컬 백로그만 봤다면 `OPS-33`이 비어 보였을 것이므로, **눈으로 다음 번호를 고르는
방식이었다면 이 문서는 중복 번호를 낳았다.** CLI가 제안한 `OPS-35`부터 배정했다
(HARN-15가 막아낸 실사례 — CLAUDE.md "태스크 ID 번호를 추론으로 배정 금지" 근거 보강).

**중복 회피 확인(전건 실측)**: 이벤트 소비자 배선=`S4-22`(todo) / 알림 last-hop·업타임 프로브=
`OPS-30`(todo·영속화는 ④로 배제) / 백업 스케줄=`OPS-31` / 의존성 선언↔사용=`OPS-32` /
QA fail-open=`ARCH-23`+`S3-28` / CI 강제 선언=`OPS-29` / 결함신고 판독=`RPT-02` /
문항 중복=`QUAL-02` / 재서술=`QUAL-04` / 난이도 이상탐지=`S4-15`+`S3-01` /
롤업 **writer**=`COLLAB-03`(done — **스케줄은 그 태스크에 포함되지 않았다**).
**어느 것도 침범하지 않는다.**

---

## §5. 정직한 공백 — 이 문서가 하지 않은 것

- **실행하지 않았다.** 코드 변경 0·측정 실행 0. 모든 판정은 정적 실측(grep·파일 읽기)이며,
  라이브 DB 행 수는 재지 않았다. "0행"이라 적은 것은 **writer/호출자 부재**에서 연역한 것이지
  프로덕션 카운트가 아니다.
- **미머지 브랜치의 `learning_analytics_gap_review.md`를 읽지 않았다.** 중복 착수 여부만
  확인했고(부록 A-5) 그 문서의 판정을 승계·반박하지 않는다 — 회수 여부는 별건이다.
- **`OPS-30`·`OPS-31`의 범위를 재정의하지 않았다.** D3가 `OPS-30` ④와 경계를 접하므로
  **소유 이전을 notes에 교차 기록**하는 선까지만 했다. 남의 태스크 acceptance는 고치지 않는다.
- **틀의 "AI 분석 활용"(84-⑤) 중 오개념 탐지·난이도 추정은 다루지 않았다** — 각각
  `misconception_module_gap_review.md`·`S4-15`의 소관이며 이 문서가 재판정할 축이 아니다.

---

## §6. 정정 — 다른 문서의 stale (해당 문서를 수정하지 않고 여기 기록)

1. **`ai_recommendation_module_gap_review.md:416`** — *"`attempt_event`도 EventType 11종 중
   **3종**만 생산된다"* → **6종**이 맞다. `S3-16`이 막힘·힌트요청·답입력을 휴면→생산으로
   소생시켰다(`schema/enums.py:844`가 그 경위를 기록). 같은 줄의 ClickHouse 미배선 관측은
   **여전히 유효**하며 이 문서 D4가 그것을 태스크로 승격시켰다.
2. **`operations_module_gap_review_r3.md`** — "런북 자인공백 **25종**" → 실측 **26항**
   (incident §6 표 10행 + backup §6 4불릿 + deployment §8 12항). r3 §3 표는 incident를 11종으로
   적었으나 실제 표 행 수는 10행이고, deployment는 §3 표(10종)와 r3 자신의 부록(12항)이
   **문서 내부에서도 불일치**한다. **트리아지 결론(실갭 2건 → `OPS-30`·`OPS-31`)은 영향 없다** —
   숫자만 승계하면 stale이 전파되므로 기록한다.
3. **`docs/standards/data_pipeline.md:18` · `docs/data/curriculum_matrix.md:197` ·
   `docs/data/textbook_mapping.md:291`** — 세 문서가 검증 도구로 "great_expectations"를 적었으나
   실제 import는 **0건**이고, `src/data-pipeline/data_pipeline/ncic/validate.py:3-4`가
   **미사용을 자인**한다(*"great_expectations 미사용(대형 의존성). 자체 validator로 동일
   invariant 검증"*). 의존성 지옥 실측 기록은 `MEMORY.md:2648`.
   → 부수 발견: `great-expectations`는 `src/backend/pyproject.toml:51` 선언·import 0건인
   **4번째 미사용 선언**인데 `OPS-32`가 opentelemetry 2종+structlog만 지목한다 —
   **`OPS-32` 범위 확장 제안**(신규 태스크 아님·중복 등재 금지).
4. **`qa_pipeline.py:226-230`** — `corpus_audit` 축은 `--max-defect-upper` 기본 **1.0(=off)**과
   같은 기준이라 **항상 `ok`만 보고**한다. 코드가 스스로 자인하고 있으므로 은폐는 아니지만,
   축 목록만 보면 "문제 오류 검출 게이트가 있다"로 읽힌다. `ARCH-23`(QA 게이트 강제 전환) 인접
   사안이라 **신규 등재하지 않고 기록만** 한다.

---

## §7. 반복 실수 — **SEC-12 결함의 1주 뒤 재발** 등재

CLAUDE.md 실수 관리 규정(시스템 실수·반복 실수는 재발방지대책 등재 의무)에 따라 등재한다.

**사고 유형**: *"로직·CLI는 완비인데 그것을 정기적으로 돌리는 좌석이 없어, CLI가 생긴 것으로
문제가 해결됐다고 읽히는"* 결함.

| 회차 | 사례 | 결과 |
|---|---|---|
| 1 | 보존 파기 — `retention_purge_cli` 완비·스케줄 0 | `SEC-12`(2026-08-03 done)가 **결함 유형을 명명**하고 compose 패턴으로 해소 |
| 2 | **일별 학습지표 롤업** — `learning_metrics_rollup_cli` 완비·스케줄 0 | **1주 뒤(2026-08-10) 재발**. 게다가 감사기 유예가 "크론이 설계 확정값"이라 적어 **재발을 정상 상태로 기록** |

**왜 방어에 실패했나.** `declared_unwired_audit`는 "CLI가 CI에서 도는가"를 묻는다. 이 CLI는
**의도적으로 CI 대상이 아니므로** by-design 유예가 정당하게 부여됐다. 그런데 그 유예 문구가
*"일 1회 크론/수동 실행이 설계 확정값"*이라고 **운영 절차의 존재를 주장**했고, **그 주장을
검증하는 축은 감사기에 없다.** 즉 감사기는 "CI에 없음"은 잡지만 **"CI에도 없고 운영에도 없음"은
못 잡는다.**

**대책(등재 형태)**:
- **코드/태스크** — `OPS-35`가 이 건을 해소한다.
- **일반화 후보** — by-design 유예 사유가 *운영 절차의 존재*를 주장할 때 그 절차의 실재를
  요구하는 축은 현재 없다. 이는 `OPS-29`(*"자인한 공백은 추적 ID를 갖거나 사유를 선언해야
  한다"*를 CI 평면에서 강제)와 같은 계열이므로 **`OPS-29` 착수 시 이 축을 함께 검토**하도록
  본 문서에 기록한다(별도 태스크 신설은 중복 위험이라 하지 않는다).

---

## 부록 A — 실측 근거 (2026-08-11 · HEAD `d088ae77`)

**A-0. 기능 84/85가 한 번도 대조된 적 없음**
```bash
grep -rn "이벤트 분석\|품질 모니터링" docs/architecture/*.md docs/strategy/*.md   # → 0건
```

**A-1. ClickHouse·Prefect/Airflow 실물 0**
```bash
grep -rn "clickhouse" docker-compose*.yml src/backend/pyproject.toml   # → EXIT=1 (0건)
grep -rni "prefect\|airflow" --include=*.py --include=*.toml --include=*.yml .   # → EXIT=1 (0건)
grep -rn "clickhouse" infra/phaiakes9/OPERATIONS_24_7.md   # → :29 :33 :96 (서비스·부팅·백업)
```

**A-2. 클라이언트가 `/v1/me/attempts`를 부르지 않음**
```bash
grep -rn "attempts" src/mobile/lib   # → 0건
```

**A-3. 롤업 스케줄 부재 (D1)**
```bash
grep -rn "learning_metrics_rollup" infra/ .github/ docker-compose*.yml scripts/   # → 0건
grep -rn "learning_metrics_rollup" docs/                                          # → 0건
```

**A-4. A/B 실험 프레임워크 부재**
```bash
grep -rn "A/B\|ab_test\|experiment" --include=*.py src/backend/whymath_backend/
# → 전건 step_break 분류 라벨·시각화 spec 필드. 실험 배정·트래픽 분할 0
```

**A-5. 중복 착수 확인**
```
claude/whymath-learning-analytics-9t71oh (2026-07-29·미머지) — learning_analytics_gap_review.md
→ 학습 분석 축(지표·리포트)이며 본 문서는 데이터 플랫폼 축(수집·품질 배관). 겹치지 않음.
```

**A-6. 백로그 무결성 (등재 후)**
```bash
python3 scripts/harness/backlog.py validate
# ✔ 백로그 무결성 green — 태스크 259건, 게이트 10건, 트랙 3건   (EXIT=0)
```
