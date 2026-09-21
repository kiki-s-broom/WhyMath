# WhyMath 인시던트 대응 런북 + 최소 SLO — OPS-04

> **정본 범위**: 이 문서가 SLO 수치·인시던트 트리거·대응 절차의 정본이다. 탐지 신호의 *구현* 정본은 OPS-01(`src/backend/whymath_backend/ops/service_health.py` · `app.py`의 `/health/ready`), 임계 기본값 정본은 `src/backend/whymath_backend/config.py`(`Settings`)다.
> **드리프트 방지**: 이 문서의 §1-5 [기계 판독] 계약 블록은 `tests/backend/ops/test_slo_contract.py`가 파싱해 코드 기본값과 대조한다. 임계를 코드에서 바꾸고 문서를 안 고치면(또는 그 반대면) **테스트가 실패한다**. 문서에 등장하는 엔드포인트 경로도 실제 라우트 표와 대조된다 — 없는 경로를 안내하는 런북이 될 수 없다.
> **전제**: 현재 배포는 단일 머신(Phaiakes9 = Kiki의 Windows PC) + Docker Desktop + uvicorn 1프로세스다. 컨테이너 오케스트레이션·프로덕션 토폴로지는 OPS-03 진행 중이라 이 런북은 **현재 실재하는 것만** 다룬다(가정 기반 런북 금지).

---

## 사전 브리핑 (CLAUDE.md 6항목 템플릿)

1. **과제 명칭** — WhyMath 백엔드 장애 탐지·대응·회고 + 최소 SLO 운영.
2. **목적** — "서비스가 이상하다"를 감(感)이 아니라 **측정된 신호**로 판정하고, 판정에서 조치까지의 경로를 고정한다. 결과가 쓰이는 곳: 인시던트 발생 시 이 문서를 위에서 아래로 따라간다(§4-0 → 해당 시나리오 → §5 회고).
3. **구체적 절차** — 평상시엔 읽을 필요 없다. 이상 징후(앱이 안 됨·응답이 느림·알림 로그)가 있을 때 §4-0 공통 1차 진단(30초, 명령 2개) → §2 트리거 표로 신호 해석 → §3 SEV 판정 → §4의 해당 시나리오 절차(각 3~5분) → 복구 후 §5 회고.
4. **성공 기준** — 각 절차 블록마다 자가검증 스텝·성공/실패 판별·실패 시 대처 1개를 병기했다. 총괄 기준: `/health/ready`가 **HTTP 200**이고 body의 `alerts`가 **빈 배열**이면 정상 복귀.
5. **실행 환경** — **Windows PowerShell**(= Phaiakes9 이 PC 자체 · SSH 불요), 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`. 선행 조건: Docker Desktop 실행 중. 진단 명령은 전부 읽기 전용이라 서비스에 영향이 없다(조치 명령은 명시적으로 표기).
6. **창 구분** — 진단·조치는 **새 PowerShell 창 1개**로 전부 가능하다. 단 백엔드(uvicorn)를 포그라운드로 재기동하는 §4-9는 **그 창을 점유**하므로 반드시 별도 창을 쓰고, 그 창에서는 이후 아무 명령도 입력하지 않는다.

---

## §0. 이 문서를 지배하는 3원칙

1. **측정 없는 SLO는 선언하지 않는다.** 목표만 있고 재는 수단이 없으면 표에 `미측정`으로 적는다 — 달성했다고 말할 수 없는 숫자는 SLO가 아니라 희망이다.
2. **간접 신호를 장애 판정 근거로 쓰지 않는다.** pid 파일(`.demo_uvicorn.pid`)·프로세스 존재·"어제까지 됐음"은 판정이 아니다. 판정은 ①`/health/ready`의 HTTP 상태코드 ②그 body의 `components`/`alerts` ③로그의 예외 타입명 — 이 셋뿐이다. (2026-07-17 좀비 uvicorn 사고: pid 파일은 죽은 pid를 가리켰고 `/health`는 *다른 프로세스*가 응답했다.)
3. **미측정(`null`)을 정상(`0`)으로 읽지 않는다.** `metrics.window_error_rate: null`은 "오류 없음"이 아니라 "표본 없음"이다. 표본이 없다는 건 *학생 트래픽이 0*이라는 뜻이고, 그 자체가 장애 신호일 수 있다.

---

## §1. 최소 SLO

### 1-1. 핵심 사용자 경로 (2026-07-26 실측 라우트 표 기준)

`create_app()`의 실제 라우트에서 학생 대면 경로만 추린 것이다. 티어는 "이 경로가 죽으면 학생에게 무슨 일이 일어나는가"로 나눈다.

| 티어 | 경로(실측) | 죽으면 학생에게 | DB 필요 | LLM 필요 |
|---|---|---|---|---|
| **T1 학습 코어** | `/v1/coach`, `/v1/coach/sessions`, `/v1/coach/sessions/{dialogue_id}/turns`, `/v1/verify-answer`, `/v1/verify-step`, `/v1/me/next-problem` | 튜터링 자체가 불가 — 앱의 존재 이유가 사라짐 | ✅ | 대부분 ✅ |
| **T2 진입·콘텐츠** | `/v1/auth/{provider}/callback`, `/v1/auth/refresh`, `/v1/problems`, `/v1/problems/{problem_id}`, `/v1/problems/{problem_id}/steps`, `/v1/me/diagnosis/summary`, `/v1/me/mastery/current` | 로그인 불가 또는 "문제를 불러오지 못했어요" | ✅ | ❌ |
| **T3 보조** | `/v1/ocr`, `/v1/ocr/pages`, `/v1/visualizations/spec`, `/v1/scenes/weak-concept`, `/v1/speech/latex` | 손글씨·시각화만 실패, 텍스트 학습은 계속 가능 | ✅ | 일부 |
| **T4 법정 권리** | `/v1/me/export`, `/v1/me/deletions`, `/v1/users/me/parental-consent` | 열람·삭제·동의 처리 지연 | ✅ | ❌ |

**T4의 특칙**: 이 경로들은 *가용성*보다 **정확성·감사 기록**이 우선이다. 의심스러우면 잘못 처리하느니 **멈춘다**(개인정보보호법 유래 절차는 기계 대체·추측 처리 금지 — CLAUDE.md).

### 1-2. SLO 표 — 목표·측정 수단·측정 상태

| # | 대상 | 목표 | 측정 수단 | 상태 |
|---|---|---|---|---|
| **S1** | 학생 트래픽 5xx 에러율 (최근 창) | **≤ 1%** 평상 / **> 5%** = 즉시 조치선 | `/health/ready` → `metrics.window_error_rate` (인프로세스·SaaS 독립) | ✅ **측정 가능** |
| **S2** | 학생 트래픽 p95 지연 (최근 창) | **≤ 3,000ms** 평상 / **> 5,000ms** = 즉시 조치선 | `/health/ready` → `metrics.window_p95_latency_ms` | ✅ **측정 가능** |
| **S3** | 레디니스 (트래픽 수용 가능) | `/health/ready` **HTTP 200** | 같은 엔드포인트의 상태코드 | ✅ **측정 가능**(순간값) |
| **S4** | 학습 창 가용성 (매일 15:00–24:00 KST) | **99%** — 월 허용 다운 약 2.7시간 | 외부 업타임 프로브 **미도입** | ❌ **미측정 목표** |
| **S5** | 경로별(T1/T2/T3) 지연·에러율 | T1 p95 ≤ 5s / T2 p95 ≤ 1s / T3 p95 ≤ 10s (설계 목표) | 계측이 **경로 차원을 갖지 않음**(`ServiceMetrics`는 전역 창) | ❌ **미측정 목표** |
| **S6** | LLM 호출 지연·비용 | 동기 즉답 p50 < 2,000ms | Langfuse `l3_routing` + `ops/cost_report.py`, 이중 회계는 `ops/cost_probe.py` | ⚠️ **부분 측정**(라이브 트래픽 축적 대기) |

**수치 근거 (과대 약속 금지)**

- **S1 = 1% / 5%**: 5%는 코드 기본 임계(`ops_error_rate_alert_threshold`)로 *즉시 조치선*이다. 평상 목표는 그 1/5인 1%로 둔다 — 창 500요청 기준 **5xx 5건**. 두 선을 벌려 둔 이유: 알림이 울리기 *전에* 품질 저하를 볼 여지를 남기기 위함이다.
- **S2 = 3,000ms / 5,000ms**: 라우터의 동기 즉답 게이트가 p50 < 2,000ms(`SLA_GATE_MS`)이고, 실측 p50은 로컬 FAST 1,010ms·CLOUD_MID 1,020ms다(SSM 2026-Q3 스모크). p95는 캐시 미스·큐잉·콜드스타트를 포함하므로 p50의 약 3배를 평상 목표로, 5,000ms(코드 기본 임계)를 조치선으로 둔다.
- **S4 = 99%**: 단일 머신·HA 0·야간 온콜 0(1인 개발)·작업 스케줄러가 로그온 세션에 의존하는 현실에서 **99.9%(월 43분)는 수동 복구로 달성 불가**하므로 선언하지 않는다. 24×7이 아니라 학생이 실제로 쓰는 창(평일 방과후~심야)만 목표로 삼는 것도 같은 정직함이다. 창 밖 시간대는 best-effort이며 목표를 선언하지 않는다.
- **S5**: 숫자는 *설계 기준*일 뿐이다. 잴 수 없으므로 "달성/미달"을 주장하지 않는다.

### 1-3. 오류 예산 (경량 — 과공학 금지)

인프로세스 지표는 **프로세스 재시작 시 0으로 리셋**되고 시계열로 저장되지 않는다. 따라서 월간 예산 소진율 같은 집계는 **현재 계산 불가**다. 대신 창 단위로만 운영한다.

| 관측(최근 500요청 창) | 판정 | 행동 |
|---|---|---|
| 5xx 0~5건 (≤1%) | 예산 내 | 없음 |
| 5xx 6~24건 (1~5%) | **예산 초과** | 조사 착수(§4-4). 인시던트 선언은 아직 아님 |
| 5xx 25건 이상 (>5%) | **breach** | 인시던트 선언 → §3 SEV 판정 |

### 1-4. 측정 수단 인벤토리 (무엇이 실제로 재어지는가)

| 지표 | 원천 | SaaS 의존 | 비고 |
|---|---|---|---|
| `metrics.window_error_rate` · `window_p95_latency_ms` | `/health/ready` body | ❌ 없음(인프로세스) | 최근 `ops_metrics_window_size` 요청 창 |
| `metrics.total_requests` · `total_5xx` · `latency_max_ms` | 같은 body | ❌ | 프로세스 시작 이후 누적 |
| `metrics.uptime_seconds` | 같은 body | ❌ | **가용성 이력이 아니다** — 재시작하면 0 |
| `components.*` (database/redis/llm_router) | 같은 body | ❌ | 실패 시 `error`에 **예외 타입명**만 |
| LLM 호출 지연·토큰·비용 | Langfuse `l3_routing` | ✅ 있음 | 죽으면 "측정 실패"로 드러나야 함 |
| 로컬/클라우드 비율·캐시 적중률 | `ops/cost_probe.py`(인프로세스) + `ops/cost_report.py` | ❌/✅ 이중 회계 | |
| **시간 기준 가용성** | — | — | **없음**(§6 공백) |
| **경로별 지연·에러율** | — | — | **없음**(§6 공백) |

### 1-5. [기계 판독] 계약 상수 블록

<!-- SLO-CONTRACT-BEGIN — tests/backend/ops/test_slo_contract.py가 이 표를 파싱해 코드 기본값과 대조한다. 행 형식(| `키` | `값` |)을 바꾸면 테스트가 실패한다. -->

| 계약 키 | 문서 기재값 | 코드 정본(단일 진실 원천) |
|---|---|---|
| `ops_error_rate_alert_threshold` | `0.05` | `Settings.ops_error_rate_alert_threshold` (config.py) |
| `ops_latency_p95_alert_ms` | `5000` | `Settings.ops_latency_p95_alert_ms` (config.py) |
| `ops_metrics_window_size` | `500` | `Settings.ops_metrics_window_size` (config.py) |
| `l3_sla_gate_ms` | `2000` | `l3.router.SLA_GATE_MS` |

<!-- SLO-CONTRACT-END -->

> 이 표의 값은 **기본값**이다. 운영 중 env(`WHYMATH_OPS_ERROR_RATE_ALERT_THRESHOLD` 등)로 덮어썼다면 *실제 적용 임계*는 `/health/ready` body의 `alerts[].threshold`가 알려준다 — 알림은 항상 자기 임계를 실측치와 함께 싣는다(무맥락 경고 없음).

---

## §2. 탐지 — OPS-01 신호와 대응 트리거 1:1 매핑

### 2-1. 신호 원천은 셋뿐이다

| 원천 | 무엇 | 어떻게 본다 |
|---|---|---|
| **A. `/health/ready` HTTP 상태코드** | 200 = 트래픽 수용 가능, **503 = 불가** | §4-0 명령 |
| **B. `/health/ready` body** | `components`(컴포넌트별 도달성) · `metrics`(창 지표) · `alerts`(현재 breach 목록) | 같은 명령의 출력 |
| **C. 서버 로그** | breach 상태 전이 warning · 계측 실패 warning(예외 타입명 포함) | §4-4 명령 |

`/health/live`는 **프로세스 생존만** 본다(의존성 0). 살아 있어도 DB가 죽었으면 200을 준다 — **`/health/live` 200을 정상 판정에 쓰지 말 것.** 판정은 `/health/ready`다.

### 2-2. 트리거 매핑 표 (신호 → 의미 → 행동)

| 신호(실측 필드/값) | 의미 | SEV | 즉시 행동 |
|---|---|---|---|
| `/health/ready` **HTTP 503** | `ready=false` ⇔ `components.database.reachable != true`. **DB 미도달만이 503을 만든다** | SEV-2 | §4-1 (DB 복구) |
| `/health/ready` **HTTP 000/무응답** | 서버 프로세스 미가동 또는 포트 미리슨 | SEV-2 | §4-9 (기동 + 포트 점유자 확인) |
| `components.database.error` = 예외 타입명 | DB 실패 유형(값·DSN은 절대 로그되지 않음) | — | §4-1 진단 입력 |
| `components.redis.reachable=false` (`required=false`) | L3 캐시·디바이스 캐시는 미스 강등, rate limit는 인메모리 폴백(한도 유지·워커별 계수). **디바이스 등록·폐기만 5xx 가능 — 아래 함정 ④** | SEV-3 | §4-2 |
| `components.llm_router.reachable=false` (`required=false`) | 로컬 Ollama 미도달 — 코치 응답 품질·경로 강등 | SEV-3 | §4-3 |
| `components.*.configured=false` | **미구성 = 오류 아님**(확인 수단 미노출). `reachable`은 `null`(판정 불가) | 없음 | **트리거 아님** |
| `alerts[]`에 `metric="error_rate"` | 최근 창 5xx 비율이 임계 **초과**. 임계값은 알림 자신이 싣는 `threshold` 필드를 읽는다(기본값은 §1-5 `ops_error_rate_alert_threshold`, env로 덮였으면 그 값) | SEV-2 또는 3 | §4-4 |
| `alerts[]`에 `metric="latency_p95_ms"` | 최근 창 p95(ms)가 임계 **초과**. 임계값은 같은 방식으로 `threshold` 필드에서 읽는다(기본값은 §1-5 `ops_latency_p95_alert_ms`) | SEV-3 | §4-5 |
| 로그 `... breach 진입 — metric=<이름> observed=<수> threshold=<수>` (WARNING) | breach **진입 순간**(상태 전이 시 1회만) | 위와 동일 | 시각 = 인시던트 시작 시각 |
| 로그 `... 해소 — metric=<이름>` (INFO) | breach 해소 | — | 인시던트 종료 판정 보조 |
| 로그 `... 예외 타입: <타입명>` (계측 실패 WARNING) | **관측 자체가 실패 중** — 지표를 믿지 말 것 | 메타 | §4-4 마지막 항목 |
| `metrics.window_error_rate = null` | 표본 0 = **미측정**(정상 아님) | 판정 보류 | 학생 트래픽 0인지 먼저 확인 |

### 2-3. 신호를 읽을 때의 함정 (전부 코드 실측 근거)

① **DB가 죽어도 에러율은 안 오를 수 있다.** ops 프로브 경로(`/health`·`/health/live`·`/health/ready`·`/status`)는 계측에서 제외된다(`_OPS_PROBE_PATHS`). 503 폭주가 에러율을 자기증폭하지 않도록 한 의도적 설계다. 따라서 **DB 다운은 에러율이 아니라 503으로 탐지한다.**

② **`uptime_seconds`는 가용성 이력이 아니다.** 재시작하면 0부터 다시 센다. 반대로 이 값은 **좀비 프로세스 판별에 쓸 수 있다** — 방금 재기동했는데 `uptime_seconds`가 수만 초라면, 당신이 대화하고 있는 것은 새 서버가 아니라 **포트를 쥐고 있는 옛 프로세스**다(2026-07-17 사고의 직접 신호판).

③ **지표는 워커(프로세스)별이다.** 다중 워커로 띄우면 `/health/ready` 한 번 조회는 **워커 하나**를 표본한 것이다. 현재 배포는 1프로세스라 문제없지만, 워커를 늘리는 순간 이 표의 해석이 바뀐다.

④ **`redis.required=false`는 여전히 "Redis 없어도 학생 경로가 멀쩡하다"는 *보증*이 아니다** — 다만 2026-07-26(OPS-05·OPS-06) 이후로는 대체로 그렇게 *동작*한다. 레디니스 표시는 판정 정책일 뿐이고 실제 동작은 코드가 정하므로, 아래 실측을 경로별로 읽는다.

  - **L3 응답 캐시**(`l3/cache/redis_cache.py`, OPS-05): `get` 실패 → 캐시 미스, `set` 실패 → no-op. 생성 경로는 재생성으로 완주한다(대가는 LLM 재호출 비용). *예전에 이 함정이 지목했던 5xx 경로는 닫혔다.*
  - **디바이스 서명 캐시**(`api/_device_store.py`, OPS-06): 조회·적재 실패 → DB 검증으로 폴백. 이 캐시는 성공만 담는 positive cache라 강등은 승인을 *줄이는* 방향으로만 움직인다(느슨해지지 않는다). **단 무효화(DEL)만은 강등하지 않는다** — 폐기·등록·정리(`revoke`/`register`/`cleanup_stale`)의 캐시 무효화가 유한 재시도 후에도 실패하면 **예외를 올린다(=그 요청은 5xx)**. 의도된 fail-loud다: 폐기된 디바이스의 서명이 캐시에 남아 계속 통과하는 것보다, 실패를 알리는 편이 안전하다.
  - **rate limit**(`api/_rate_limit.py`, OPS-06): Redis 실패 → 프로세스-로컬 인메모리 백엔드로 **폴백**. 요청은 살고 한도도 계속 걸리지만 **계수가 워커별로 갈라진다** — 다중 워커면 실효 한도가 최대 워커 수 배까지 느슨해질 수 있다(무제한은 아니다). fail-open(무제한)도 fail-closed(전면 차단)도 아닌 제3의 길이며, 그 대가가 이 분산 정확도 저하다.
  - 세 경로 모두 흡수든 전파든 **예외 타입명**을 로그에 남긴다 — `operation=` 토큰으로 검색한다(함정 ⑤).

  따라서 지금 남아 있는 "레디니스 200인데 학생은 실패" 조합은 **디바이스 등록·폐기 요청의 캐시 무효화 실패**뿐이다(의도된 설계). 그래도 Redis 다운 의심 시에는 상태코드가 아니라 `alerts`의 `error_rate`를 함께 본다 — 남은 공백은 §6에 정직하게 적어 둔다.

⑤ **로그 검색은 ASCII 토큰으로 한다.** 로그 메시지는 한국어지만 콘솔·파일 인코딩에 따라 한글이 깨져 보일 수 있다. `metric=`·`threshold=`·`WARNING` 같은 **ASCII 조각으로 검색**하면 인코딩과 무관하게 잡힌다.

---

## §3. 심각도 분류 (SEV) — 학생 대면 영향 기준

분류 순서는 CLAUDE.md 의사결정 우선순위(①학생 안전·웰빙 ②법적·윤리 ③교수학적 정확성 … ⑤UX ⑥비용)를 그대로 따른다. **따라서 "틀린 수학을 자신 있게 가르치는 상태"와 "미성년 데이터가 새는 상태"는 서비스가 아예 안 되는 것보다 위다.** 느린 서비스보다 **틀린 서비스가 더 나쁘다.**

| SEV | 정의 | 예 | 대응 시한 | 첫 행동 |
|---|---|---|---|---|
| **SEV-1** | **학생 안전·법익 침해**. 서비스가 *동작하면서* 해를 끼치는 상태 | 검증 우회된 오답·환각이 학생에게 노출 / 미성년 PII 노출·유출 / 부모 동의 게이트 무력화 / 정서적으로 해로운 응답 / 데모 인증이 프로덕션 호스트에서 켜짐 | **즉시(발견 즉시)** | **봉쇄 우선** — §4-7. 서비스를 *끄는 것*이 켜 두는 것보다 안전하다 |
| **SEV-2** | 학생 대면 **전면 불능** | `/health/ready` 503(DB 다운) / 서버 무응답 / T1·T2 전면 5xx | 학습 창 내 30분 | §4-1 또는 §4-9 |
| **SEV-3** | **부분 기능 저하** | Redis·LLM 라우터 미도달 / `latency_p95_ms` breach / T3(OCR·시각화)만 실패 | 학습 창 내 당일 | §4-2·4-3·4-5 |
| **SEV-4** | 학생 영향 없음 | 배치·비용 계측 이상 / 백업 스케줄 누락 / 관측 파이프라인만 실패 | 주 단위 | 백로그 태스크로 등재 |

**판정 규칙 2개**
- 애매하면 **한 단계 높게** 잡는다. 과잉 대응의 비용(#6)은 학생 안전(#1)보다 싸다.
- SEV-1은 **다른 SEV와 동시에 성립할 수 있다.** 이때 SEV-1 봉쇄가 항상 먼저다 — 가용성 복구를 위해 위험한 응답 경로를 다시 켜지 않는다.

---

## §4. 완화·복구 절차

> 모든 진단 명령은 **읽기 전용**이다. 조치 명령에는 `[조치]` 표시가 있다.
> 아래 블록의 `$out` 변수는 응답 본문을 임시 파일로 받는 용도다(리포지토리를 더럽히지 않는다).

### 4-0. 공통 1차 진단 (30초 — 무슨 일이 있어도 여기서 시작)

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$out = Join-Path $env:TEMP "whymath_ready.json"
curl.exe -s -o $out -w "HTTP=%{http_code}`n" http://127.0.0.1:8000/health/ready
Get-Content $out -Raw | ConvertFrom-Json | ConvertTo-Json -Depth 6
```

**판독 (이 네 줄이 인시던트의 8할을 가른다)**

| 출력 | 판정 | 다음 |
|---|---|---|
| `HTTP=200` + `alerts` 빈 배열 | 정상 | 학생이 이상을 겪는다면 §4-8(클라이언트 도달성) 의심 |
| `HTTP=200` + `alerts` 비어 있지 않음 | 가동 중 품질 저하 | `metric` 값에 따라 §4-4(error_rate) / §4-5(latency) |
| `HTTP=503` | 트래픽 수용 불가 = DB 미도달 | §4-1 |
| `HTTP=000` + JSON 파싱 오류 | 서버 무응답 | §4-9 |

- **변별력**: 서버가 죽어 있으면 `curl.exe`가 `HTTP=000`을 찍고 `$out`이 비어 `ConvertFrom-Json`이 **실제로 오류를 낸다**(정상 상태에서는 절대 나지 않는 신호). 즉 이 검증은 성공·실패에서 서로 다른 출력을 낸다.
- **실패 시 대처**: 포트가 8000이 아닐 수 있다(`WHYMATH_DEMO_PORT`로 바꾼 경우). §4-9의 포트 점유자 확인으로 실제 리슨 포트를 먼저 특정한다.

### 4-1. DB 다운 — `/health/ready` 503 (SEV-2)

**대상 확인 먼저**: prod DB는 docker `whymath-pg`(호스트 포트 **5433**)다. `whymath-demo-db`(55432)는 시연용 일회용이고, 5432는 타 프로젝트가 점유한다 — **혼동 금지**. systemd/네이티브 PostgreSQL은 이 머신에 없다.

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath
docker ps -a --filter "name=whymath-pg" --format "{{.Names}}`t{{.Status}}`t{{.Ports}}"
docker exec whymath-pg pg_isready -U whymath -d whymath
```

> ⚠ **위 두 줄만으로는 부족하다(2026-09-08 실측).** 둘 다 통과하는데 호스트에서는 못 붙는
> 상태가 실재했다 — 컨테이너는 `Up`, `pg_isready`는 `accepting connections`, 그런데 5433은
> 닫혀 있었다. 두 명령이 **전부 컨테이너 안쪽**을 보기 때문이다(`docker exec`는 호스트
> 네트워크를 경유하지 않는다). 아래 도달성 판정을 **함께** 돌린다:
>
> ```powershell
> # [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
> cd C:\Users\kiki\Desktop\__AI\WhyMath
> $env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
> $env:PYTHONPATH = (Resolve-Path "src\backend").Path
> & src\backend\.venv\Scripts\python.exe -m whymath_backend.ops.db_host_reachability
> "EXIT=$LASTEXITCODE"
> ```
>
> exit **0=도달 가능 / 1=도달 불가 / 2=측정 불가**. 이 도구는 `HostConfig.PortBindings`(만들 때
> 요청한 **설정**)와 `NetworkSettings.Ports`(실제로 성립한 **게시**)를 구분해 읽는다 — 사고
> 당시 전자는 멀쩡했고 후자가 비어 있었다. 설정만 보면 고장을 정상으로 읽는다.

- **성공**: `Up ...` 상태 **그리고** `... accepting connections` **그리고** 도달성 CLI가
  `REACHABLE`(exit 0). 셋 다 필요하다 — 앞의 둘은 컨테이너 안쪽만 증명한다.
- **실패 유형별 조치**
  - **컨테이너는 Up · `pg_isready` 통과 · 그런데 호스트에서 못 붙음**(도달성 CLI가
    `NOT_PUBLISHED`/`NO_BINDING`/`PUBLISHED_BUT_CLOSED`/`FOREIGN_LISTENER`) → DB가 죽은 것이
    아니라 **문이 안 열린** 것이다. `[조치]` CLI 출력의 「대책」절을 따른다. Windows에서
    실측된 원인은 Hyper-V/WinNAT 동적 포트 제외 범위가 5433을 삼킨 것이며, 진단·영구 조치
    절차는 `/demo-doctor` 카탈로그 **§W1**에 있다. 이 유형이 **무증상으로 오래 갈 수 있는**
    이유도 기억한다 — 백업(`docker exec pg_dump`)도 스키마 프로브(`docker exec psql`)도
    컨테이너 안으로 들어가므로 이 고장을 **구조적으로 볼 수 없다**(OPS-72).
  - `FOREIGN_LISTENER`가 나오면 특히 급하다 — **다른 프로세스가 그 포트를 물고 있다**는
    뜻이라, 붙는 도구들이 성공하면서 엉뚱한 대상에 말을 걸고 있을 수 있다. 점유 프로세스부터
    식별한다(`Get-NetTCPConnection -LocalPort 5433 -State Listen`).
  - 컨테이너가 `Exited` → `[조치]` `docker start whymath-pg`
  - 컨테이너 자체가 없음(`docker ps -a`에 행 없음) → **데이터 소실 가능성** → §4-8(OPS-02 복구 런북)로 이동. 새 컨테이너를 **추측으로 재생성하지 않는다**(포트·볼륨 구성은 OPS-02 §3-4의 `whymath-pg.inspect.json` 스냅샷으로 재현).
  - Docker Desktop 자체가 미가동 → Docker Desktop 실행 후 위 명령 재시도.
  - 컨테이너는 Up인데 `pg_isready`가 `no response` → `[조치]` `docker logs --tail 50 whymath-pg`로 사유 확인(디스크 가득참이면 §4-6).

**자가검증 (조치 후 반드시)**

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath
docker exec whymath-pg pg_isready -U whymath -d whymath
$out = Join-Path $env:TEMP "whymath_ready.json"
curl.exe -s -o $out -w "HTTP=%{http_code}`n" http://127.0.0.1:8000/health/ready
```

- **성공**: `accepting connections` **그리고** `HTTP=200`. 둘 다 필요하다 — DB가 살아나도 백엔드의 커넥션 풀이 회복되지 않았을 수 있다.
- **실패 시 대처**: `pg_isready`는 통과인데 계속 503이면 백엔드를 재기동한다(§4-9). 이때 `components.database.error`의 예외 타입명을 회고에 남긴다.

### 4-2. Redis 다운 — `components.redis.reachable=false` (SEV-3)

먼저 **함정 ④**를 읽었는지 확인한다: `required=false`는 판정 정책일 뿐이다. 2026-07-26(OPS-05·OPS-06) 이후 생성·검증 경로는 강등으로 살아남지만, **디바이스 등록·폐기의 캐시 무효화 실패는 여전히 5xx로 드러난다**(의도된 fail-loud).

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath
docker ps -a --format "{{.Names}}`t{{.Status}}" | Select-String -Pattern "redis"
$out = Join-Path $env:TEMP "whymath_ready.json"
curl.exe -s -o $out -w "HTTP=%{http_code}`n" http://127.0.0.1:8000/health/ready
(Get-Content $out -Raw | ConvertFrom-Json).components.redis
(Get-Content $out -Raw | ConvertFrom-Json).metrics.window_error_rate
```

- **판독**: `reachable=false`이고 `window_error_rate`가 평상(≤0.01)이면 → 강등·폴백만 일어나는 중, **SEV-3 유지**. 같은 조건에서 `window_error_rate`가 올라가고 있으면 → 강등으로 흡수되지 않는 경로가 실패 중이다. 지금 그 후보는 **디바이스 등록·폐기의 캐시 무효화**(함정 ④)이고, 그 외 상승은 Redis가 아닌 다른 원인을 의심한다. **SEV-2로 격상** 후 §4-4로 로그를 확인한다(`operation=delete` + 예외 타입명).
- **`[조치]`**: Redis 컨테이너를 되살린다(`docker start <이름>`). 즉시 되살릴 수 없으면 **캐시 없이 버티는 편이 낫다** — rate limit 백엔드 기본값은 `memory`(프로세스-로컬)이고, `redis` 백엔드로 운영 중이더라도 실패 시 같은 인메모리 백엔드로 폴백하므로 한도가 통째로 사라지지는 않는다(다만 워커별 계수로 느슨해진다).
- **폐기가 급한 경우**(분실 기기 등 SEV-1 인접): Redis가 죽어 있으면 폐기 요청이 5xx로 실패할 수 있다. 이때 폐기 자체는 DB에 이미 반영되며 캐시의 잔존 승인은 **TTL(기본 60초) 안에 자연 소멸**한다 — 그래도 확실히 하려면 Redis를 되살린 뒤 폐기를 한 번 더 호출한다(무효화가 재실행된다).
- **자가검증**: 위 명령 재실행 → `components.redis.reachable` 이 `true`. (변별력: 되살아나지 않으면 이 값이 그대로 `false`이고 `error`에 예외 타입명이 남는다.)

### 4-3. LLM 라우터 도달 불가 — `components.llm_router.reachable=false` (SEV-3)

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$out = Join-Path $env:TEMP "whymath_status.json"
curl.exe -s -o $out -w "HTTP=%{http_code}`n" http://127.0.0.1:8000/status
Get-Content $out -Raw | ConvertFrom-Json | ConvertTo-Json -Depth 5
ollama list
```

- **판독**: `/status`의 `reachable=false` → Ollama 데몬 미가동. `reachable=true`인데 `missing`에 모델이 있으면 → **모델 미설치**(도달성 문제 아님, `ollama pull <모델>`).
- **`[조치]`**: Ollama 앱(트레이)이 떠 있는지 확인하고 없으면 실행한다. `ollama serve`를 **직접 실행하면 그 창을 영구 점유**하므로 반드시 §4-9의 창 규칙을 따른다.
- **판단**: 코치 경로는 클라우드 디스패치·QUALITY 큐·결정론 템플릿 폴백이 있어 즉시 전면 불능은 아니다. 다만 **클라우드로 쏠리면 비용이 오른다** — 비용(#6)이 학생 경험(#5)보다 아래라는 점을 기억하되, 장시간 방치는 §5 회고 대상이다.
- **자가검증**: `/status` 재조회 시 `reachable=true` + `missing` 빈 배열.

### 4-4. 에러율 급증 — `alerts[]`에 `error_rate` (SEV-2/3)

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$out = Join-Path $env:TEMP "whymath_ready.json"
curl.exe -s -o $out http://127.0.0.1:8000/health/ready
$b = Get-Content $out -Raw | ConvertFrom-Json
$b.alerts | Format-Table metric, observed, threshold
$b.metrics | Format-List
Select-String -Path .\.demo_uvicorn.err.log -Pattern "WARNING|ERROR|Traceback|metric=" |
  Select-Object -Last 40
```

**판독 순서**
1. `alerts[].observed`가 얼마나 임계(`threshold`)를 넘었는지 본다 — 알림은 항상 실측치와 임계를 함께 싣는다.
2. `metrics.window_count`를 본다. 표본이 적으면(예: 20) 5xx 2건만으로도 10%가 된다 — **작은 표본의 큰 비율에 과잉 반응하지 않는다.**
3. 로그에서 **예외 타입명**을 찾는다. 침묵 실패 금지 규칙 덕분에 best-effort 경로도 타입명을 남긴다.
4. 로그에 `예외 타입:` 계측 실패 warning이 있으면 → **관측 자체가 고장 난 상태**다. 이때 `metrics` 수치를 근거로 판단하지 말고, 먼저 그 원인을 잡는다(지표가 실제보다 좋아 보일 수 있다).

- **`[조치]`**: 원인 코드가 특정되면 롤백/수정. 특정 경로(예: OCR)에 한정되면 §4-7의 기능 차단으로 **그 경로만** 끈다.
- **자가검증**: 창이 새 요청으로 교체되며 `window_error_rate`가 임계 아래로 내려가고, 로그에 **`해소 — metric=error_rate`(INFO)** 가 찍힌다. (변별력: 해소 로그는 상태 *전이* 시에만 나오므로, 이 줄이 없으면 아직 breach 중이다.)

### 4-5. 지연 p95 breach — `alerts[]`에 `latency_p95_ms` (SEV-3)

§4-4와 같은 명령으로 body를 받은 뒤 `metrics.window_p95_latency_ms`·`latency_max_ms`를 본다.

- **원인 후보(위에서부터 확인)**: ①Ollama 미도달로 클라우드/큐 폴백 중(§4-3) ②Redis 미도달로 캐시 적중률 0(§4-2) ③GPU 비활성으로 로컬 추론이 CPU로 떨어짐 ④DB 슬로우 쿼리.
- **③의 확인**: 로컬 p50이 SSM 실측(FAST 약 1,010ms)의 수 배로 벌어졌다면 GPU 활성 여부를 의심한다(`docs/standards/ssm_activation_handoff.md`의 GPU 활성 항목).
- **`[조치]`**: 원인별로 §4-2/4-3. 즉시 원인을 못 잡으면 **SEV-3 유지 + 관찰**이 정답이다 — 느린 것은 틀린 것보다 낫다(우선순위 #3 > #5).
- **자가검증**: 로그에 `해소 — metric=latency_p95_ms`.

### 4-6. 디스크 고갈

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath
Get-PSDrive C | Select-Object Name, @{n='UsedGB';e={[math]::Round($_.Used/1GB,1)}}, @{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}}
docker system df
Get-ChildItem C:\Users\kiki\Desktop\__AI\WhyMath-backups\*.dump -ErrorAction SilentlyContinue |
  Measure-Object Length -Sum | Select-Object Count, @{n='TotalGB';e={[math]::Round($_.Sum/1GB,2)}}
Get-ChildItem .\.demo_uvicorn*.log -ErrorAction SilentlyContinue | Select-Object Name, Length
```

**`[조치]` — 안전한 순서로만**
1. 오래된 백업 정리: OPS-02의 보존 정책을 짧게 재실행(`.\scripts\backup\backup_whymath_pg.ps1 -RetentionDays 7`). **최신 1개는 스크립트가 절대 지우지 않는다.**
2. uvicorn 로그 파일 정리(`.demo_uvicorn*.log`) — 서버 중지 후 삭제.
3. 도커 정리: `docker image prune -f`(미사용 이미지만).

> ⛔ **절대 금지**: `docker system prune --volumes` · `docker volume prune`. prod DB(`whymath-pg`)의 데이터 볼륨을 날릴 수 있다 — 디스크 확보하려다 서비스 데이터를 잃는 것은 어떤 SEV보다 나쁘다.

- **자가검증**: `Get-PSDrive C`의 `FreeGB` 증가 + `docker exec whymath-pg pg_isready -U whymath -d whymath`가 여전히 `accepting connections`.

### 4-7. SEV-1 봉쇄 — 잘못된 수학 콘텐츠 노출 / 미성년 데이터 노출

**원칙: 봉쇄가 복구보다 먼저다.** 원인 분석은 학생 노출을 멈춘 뒤에 한다.

| 사고 유형 | 봉쇄 수단(실재 확인) | 비고 |
|---|---|---|
| 손글씨·OCR 경로에서 잘못된 인식·노출 | env `WHYMATH_OCR_ENABLED=false` 후 재기동(§4-9) | 기본값이 이미 `false`(opt-in) |
| 토큰 유출·데모 인증이 잘못 켜짐 | env `WHYMATH_DEMO_AUTH_ENABLED=false` + **재기동** | 재기동 시 `WHYMATH_JWT_SECRET_KEY`가 새로 생성되면 **기존 토큰이 전부 무효화**된다(시연 스크립트 동작) |
| 원인 미상 + 학생 노출 지속 | **백엔드 중지** — 앱은 "문제를 불러오지 못했어요"로 graceful 실패한다 | 잘못된 튜터링보다 접속 불가가 낫다 |
| 미성년 PII가 외부로 나갔을 가능성 | 위 봉쇄 + **범위 확정 전 어떤 데이터도 추가 반출 금지**(로그·덤프를 LLM·SaaS에 업로드 금지) | 법정대리인 통지 등 법령 유래 절차는 **기계·AI가 대신 판단하지 않는다** — Kiki 본인 + 필요 시 변호사 |

- **자가검증**: 봉쇄 후 해당 경로를 실제로 호출해 **차단되었음을 확인**한다(예: OCR 차단 시 `/v1/ocr` 호출이 성공하지 않음). "설정을 바꿨다"는 것은 봉쇄의 증거가 아니다 — 재기동되지 않았으면 옛 프로세스가 옛 설정으로 계속 응답한다(§2-3 함정 ②).
- **기록 의무**: SEV-1은 예외 없이 §5 회고 + MEMORY 결정 로그 대상이다.

### 4-8. 데이터 손실·훼손 의심 → OPS-02 복구 런북

DB 컨테이너 소실, 오조작(DROP 등), `pg_restore` 필요 상황은 이 문서가 다루지 않는다. **`docs/architecture/db_backup_dr_runbook.md`** 로 이동한다(§3-5 실전 복구). 그 런북의 전제 두 가지를 기억한다: **RPO는 최대 3~4일**(주 2회 백업·WAL 미도입)이고, 복구 전 구성은 `whymath-pg.inspect.json` 스냅샷으로 재현한다.

### 4-9. 백엔드 재기동 + 포트 점유자 확인 (좀비 서버 방지)

**먼저 점유자를 확인한다 — pid 파일을 믿지 않는다.**

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)  [창 A — 진단용, 계속 사용 가능]
cd C:\Users\kiki\Desktop\__AI\WhyMath
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Get-Process -Id $_.OwningProcess } |
  Select-Object Id, ProcessName, StartTime, Path
```

- **판독**: 행이 없으면 아무도 8000을 안 듣고 있다(서버 미가동 확정). 행이 있는데 `StartTime`이 당신이 띄운 시각보다 **과거**면 → **좀비**다.
- **`[조치]`(좀비인 경우)**: `Stop-Process -Id <위에서 확인한 Id> -Force` 후 위 명령을 재실행해 **행이 사라졌는지** 확인한다. (변별력: pid 파일이나 `/health` 응답은 좀비가 대신 만족시킬 수 있지만, 리슨 소켓의 소유 프로세스는 대신할 수 없다.)

**그 다음** 서버를 띄운다. 아래는 **창을 영구 점유**하는 명령이다.

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)  [창 B — 새 창. 서버 전용]
cd C:\Users\kiki\Desktop\__AI\WhyMath
.\scripts\demo\run_demo.ps1
```

> ⚠️ **이 창은 이후 아무 명령도 입력하지 않는다.** 여기서 `Ctrl+C`는 복사가 아니라 **서버 중단 신호**다. 확인·검증 명령은 전부 창 A에서 실행한다.

- **자가검증(창 A에서)**: §4-0 명령 → `HTTP=200`, 그리고 **`metrics.uptime_seconds`가 방금 기동한 값(수십 초 이내)** 인지 확인한다. 이 두 번째 조건이 "새 서버와 대화 중"임을 증명하는 직접 신호다.
- **실패 시 대처**: `HTTP=000`이면 창 B의 출력에서 실패 사유를 읽는다(포트 충돌·Docker 미가동·인코딩 오류 등이 그대로 출력된다).

---

## §5. 회고 — 인시던트가 규칙·코드·태스크로 바뀌는 경로

회고는 선택이 아니다. **시스템 실수**(도구·인프라·프로세스 결함) 또는 **반복 실수**(동일 유형 2회 이상)는 CLAUDE.md상 **재발방지대책 등재가 의무**이며, 해당 세션이 끝나기 전에 완료한다.

### 5-1. 회고 절차 (SEV-1·SEV-2는 필수, SEV-3은 반복 시 필수)

1. **타임라인 확정** — 시작 시각은 로그의 `breach 진입` 줄(또는 503 첫 관측), 종료 시각은 `해소` 줄(또는 200 복귀). 추정하지 말고 로그에서 읽는다.
2. **원인 규명(실측)** — 예외 타입명·컨테이너 로그·`components.*.error`. **추론으로 환경 사실을 단정하지 않는다**(부분 성공을 전체 정상으로 해석 금지).
3. **탐지 지연 평가** — 장애 시작과 *인지* 시각의 간격. 이 간격이 크면 그것 자체가 결함이다(§6의 프로브 부재가 원인일 가능성이 높다).
4. **대책을 형태로 못 박는다** — "다음엔 조심한다"는 대책이 아니다. 아래 셋 중 **하나의 형태**여야 한다.

| 대책 형태 | 어디로 | 예 |
|---|---|---|
| **규칙** | `CLAUDE.md`에 행동 규칙 등재 + 사고 경위 1줄 병기 | "간접 신호를 성공 판정으로 쓰지 말 것" 류 |
| **코드** | 회귀 테스트로 동결 | 임계·경로 드리프트 → `tests/backend/ops/test_slo_contract.py` |
| **태스크** | `backlog/`에 등재(추적 대상) | 설계 공백·도구 부재 |

5. **기록** — 사고 경위를 `MEMORY.md` 결정 로그에 남긴다(미래 세션이 "왜 이 규칙이 생겼는지" 알 수 있게).
6. **이 문서 갱신** — 새 시나리오가 생겼으면 §4에 절차를 추가하고, 임계를 조정했으면 **코드와 §1-5 계약 블록을 함께** 고친다(한쪽만 고치면 테스트가 막는다).

### 5-2. 회고 템플릿 (복사해서 채운다)

```
[인시던트] <한 줄 제목>
SEV: <1~4>   시작: <로그 근거 시각>   종료: <로그 근거 시각>   탐지 지연: <분>
학생 영향: <어떤 티어의 무엇이 / 몇 명이 / 무엇을 못 했는가 — 모르면 "미측정">
탐지 신호: <503 / alerts:error_rate / 로그 예외 타입명 ...>
원인(실측 근거): <예외 타입명·로그 인용>
조치: <실행한 절차 §4-x>
재발방지: [규칙 | 코드 | 태스크] <구체적 등재 위치>
미해결: <남은 것 — 정직하게>
```

---

## §6. 정직한 공백 (현재 없는 것 — 후속 후보)

| 공백 | 지금 무슨 일이 생기는가 | 후속 후보 |
|---|---|---|
| **온콜 인원 없음(1인)** | Kiki가 자거나 자리를 비우면 **탐지도 대응도 0**이다. S4 가용성 목표를 학습 창으로 제한한 실질적 이유 | 학습 창 종료 시 1회 수동 확인 습관화 |
| **외부 업타임 프로브 미도입** | 서버가 죽으면 *아무도 모른다*. 지금의 모든 지표는 **서버가 살아 있을 때만** 나온다 — 죽은 서버는 자기 죽음을 보고하지 못한다. S4가 미측정인 근본 원인 | 별도 호스트/스케줄러에서 `/health/ready` 주기 폴링 + 결과 append |
| **페이지(호출) 알림 채널 미배선** | breach는 **로그에만** 남는다. 로그를 보고 있지 않으면 알림이 아니다 | breach 시 푸시·메신저 전송(OPS-01 `AlertLogNotifier` 옆에 notifier 추가) |
| **경로별 지연·에러율 미분해** | 전역 창 지표라 "코치가 느린 건지 전체가 느린 건지" 구분 불가(S5 미측정) | 미들웨어 계측에 라우트 템플릿 차원 추가 |
| **지표 영속화 없음** | 프로세스 재시작 시 누적치 소멸 → 월간 오류 예산·가용성 집계 불가 | 스크레이퍼 또는 ClickHouse 적재 |
| **디바이스 무효화 실패 시 등록·폐기 5xx** (OPS-06 이후 남은 함정 ④의 잔여) | 캐시 DEL이 유한 재시도 후에도 실패하면 `revoke`/`register`가 오류를 반환한다. DB 변경은 그 전에 커밋돼 있어 **응답(실패)과 상태(반영됨)가 어긋나 보인다** | 의도된 fail-loud라 '해결'이 아니라 *완화* 대상 — 후속 후보는 ①무효화 실패를 큐에 적재해 백그라운드 재시도 ②`register`의 count 캐시 DEL만 분리해 no-op 강등(그쪽은 신선도 문제지 보안 계약이 아니다) |
| **Redis 폴백 시 rate limit 분산 정확도 저하** | 인메모리 폴백은 워커별 계수라 다중 워커에서 실효 한도가 최대 워커 수 배까지 느슨해진다(무제한은 아니다). 폴백 중임은 로그·인프로세스 카운터로만 보인다 | `rate_limit_degradation_snapshot()`을 `/health/ready` body에 노출(응답 스키마 변경이라 별도 태스크) |
| **강등 회계가 `/health/ready`에 미노출** | 인프로세스 카운터(`cache_degradation_snapshot`·`device_cache_degradation_snapshot`·`rate_limit_degradation_snapshot`)는 존재하나 HTTP로는 못 읽는다 — 지금은 로그로만 판정한다 | 세 스냅샷을 `metrics`에 합류(OPS-05·OPS-06 공통 잔여) |
| **다중 워커 시 지표 해석 붕괴** | 워커별 독립 계측이라 `/health/ready` 1회 조회 = 워커 1개 표본 | 프로세스 경계 합산 스크레이퍼 |
| **프로덕션 배포 토폴로지 미확정** | 이 런북의 명령은 전부 *현재의 단일 머신 + Docker Desktop* 전제다. 컨테이너화 배포로 바뀌면 §4의 조치 명령이 달라진다 | **OPS-03**(배포·CD·IaC) 완료 후 이 문서 §4 갱신 |

---

*작성: 2026-07-26 (OPS-04-incident-runbook-slo) · 갱신: 2026-07-26 (OPS-06 — 함정 ④·§2-2 표·§4-2·§6을 Redis 강등 실측에 맞춰 재작성) · 엔드포인트·임계·실패 동작은 `src/backend/whymath_backend/` 2026-07-26 실측 · 드리프트 동결: `tests/backend/ops/test_slo_contract.py`(임계·경로) + `tests/backend/api/test_redis_degradation.py`(강등 동작)*
