# ARCH-71 — 학생 대면 CLOUD_MID 좌석 라이브 1회차 (Kiki 실행)

> `ARCH-64`(PR #1370)가 학생 대면 서빙의 클라우드 좌석을 `build_cloud_provider()` 경유로 바꾸고
> 기본 좌석을 `openrouter`로 옮겼다. 그 PR은 acceptance ⑤(라이브 대조 1회)를 컨테이너에 키가
> 없어 수행하지 못했고, `ARCH-71`이 그것을 승계했다. 이 런북은 그중 **학생 대면 1회차**다.
> 저작 1회차는 `docs/ops/eos118_seat_signal_live_runbook.md`(2026-09-29 갱신판)가 맡는다.
>
> 판정 기준: main `a28a8d08`. `ARCH-64` 착지 커밋 `16e9bf89`와 **`ARCH-69`(런타임 LOCAL 강등)
> 착지 커밋 `eb633ee1`**을 둘 다 포함한다. 아래 "0절"의 코드 사실은 전부 이 커밋에서 읽었다.
> 이 런북이 읽는 서빙 코드(`app.py`·`api/_model_status.py`·`config.py`·`l3/models.py`·
> `l3/router.py`·`l3/pipeline.py`·`l3/providers/`)는 `eb633ee1`부터 `a28a8d08`까지 바뀌지 않았다
> (`git diff --stat` 0건).
>
> **초판에서 고친 것(2026-09-29)**: 초판은 ARCH-69 착지 이전 main(`ab9f29f2`)으로 쓰이고 검증됐다.
> 그래서 ⓐ 1차 좌석이 실패해도 LOCAL이 대신 답해 **HTTP 200이 되는 회차**를 몰랐고 ⓑ 프로브가
> 제공자 예외를 기록하지 않아 그런 회차에서 **실패 원인이 한 글자도 남지 않았다**(검토자 재현:
> 429 + Ollama 가동 회차의 JSON에 오류가 없다). 이 판은 프로브가 제공자 예외·강등 필드·강등
> 계수를 싣고, 성공 기준·실패 대처·부록을 main 기준으로 다시 썼다.

## 0. 먼저 알아 둘 사실 — 이 회차가 무엇을 재고 무엇을 재지 않는가

### 0-1. 실제 학생 엔드포인트는 LOCAL로만 간다

학생 대면 호출부(장면·시각화·오개념 판정·교차검증·동등문제·재진술 등)는
`l3/escalation_defaults.default_student_escalation_signals()`가 주는 **구독 `free`·예산 0원**을
라우팅 신호로 싣는다. 구독이 인자로 들어오는 `api/_concept_orchestration.generate_routing_request`도
예산은 0원 고정이다. 라우터 규칙 1(`budget_krw <= 0` → LOCAL)·규칙 2(`free` → LOCAL)에 걸리므로
**오늘의 학생 요청은 클라우드 좌석에 닿지 않는다**(결제 배선 전 — OPS-18). 이 런북의 [A]가 그
사실을 코드로 다시 계산한다 — `ROUTES(...)` 줄의 첫 값이 `local`이다.

범위(명시): 이 판정은 `src/backend`에서 `student_subscription=`·`budget_krw=`를 검색해 나온
호출부(하네스·ops 제외)를 읽은 결과다. 그 방법으로 찾지 못한 경로가 있을 수 있다.

그러므로 이 회차는 **"학생이 CLOUD_MID를 받는다"를 재는 것이 아니다.** 학생 대면 앱이 조립한
좌석이 클라우드 결정을 받았을 때 **어디로 가고, 어떻게 기록되는가**를 잰다.

### 0-2. `/v1/generate`가 CLOUD_MID로 가는 본문 조건

`/v1/generate`는 호출자가 라우팅 신호(`RoutingRequest`)를 그대로 싣는 저수준 L3 표면이다
(`app.py`의 `post_generate` · 인증 필수·역할 불문). 라우터(`l3/router.py`의 `business_cost_tier` →
`guard_cloud` → `guard_data_export`)가 CLOUD_MID를 내는 조건은 아래 표와 같다.

| 필드 | 이 회차의 값 | 왜 이 값인가 |
|---|---|---|
| `student_subscription` | `premium` | 규칙 4 — `premium`·`gifted`만 CLOUD_MID. `free`는 규칙 2로 LOCAL |
| `requires_reasoning` | `true` | 규칙 4의 다른 조건 |
| `budget_krw` | `1000.0` | 규칙 1(0 이하 → LOCAL)과 `guard_cloud` 임계를 둘 다 넘어야 한다. **임계는 0.354원이 아니라 8.612원이다** — 아래 0-3 |
| `difficulty`·`task_type` | `hard`·`coach` | `killer`나 `prove`면 규칙 3으로 CLOUD_HIGH가 된다(그 좌석 핀 `deepseek/deepseek-v4-pro`는 미확인이고 단가 미등재) |
| `data_licenses` | `["INTERNAL_OWNED"]` | 반출 가능 등급. 생략하면 기본값 `UNKNOWN`이 fail-closed로 LOCAL 강등한다(EOS-59) |

`requires_vision`은 생략한다(기본 `false`). `true`면 무조건 LOCAL 비전 경로다.

### 0-3. 응답 본문에 있는 것과 없는 것

`/v1/generate`의 동기 응답(`GenerateResponseBody`)은 `text`·`cache_hit`·`decision`·
`validation_signal`에 **ARCH-69가 더한 강등 3필드**(`local_degraded`·`degraded_from_seat`·
`degrade_reason`)를 싣는다. 좌석(`cloud_seat`)·기록 원가·관측 모델은 여전히 없다.

- `decision.est_cost_krw`는 **8.612원**으로 나온다. 라우터의 사전 추정이 좌석을 모르고
  anthropic 단가로 계산하기 때문이다(`router.SERVING_CLOUD_SEAT` docstring ② — ARCH-64 판정문이
  "남은 간극"으로 적은 것 · 상환 = `ARCH-70`). **이 값을 기록 원가로 읽지 않는다.**
- 기록 원가(`cost_krw`)와 좌석(`cloud_seat`)은 `l3/pipeline.generate`가 trace 레코드
  (`router.langfuse_fields`)에만 싣는다. 운영 서버에서는 그 레코드가 `LangfuseSink`(외부 SaaS)로만
  나간다. 같은 레코드에 강등 5필드(`local_degraded`·`degraded_from_seat`·`degrade_reason`·
  `degraded_to_local`·`degrade_cloud_attempt_ms`)도 실린다.
- 관측 모델(`Usage.served_model`)은 제공자가 응답에서 읽어 오지만 **학생 대면 경로의 어떤 기록에도
  남지 않는다** — `langfuse_fields`가 그 필드를 싣지 않는다(코드 판독 · `a28a8d08`). 프로브가
  trace 레코드에 그 키가 없다는 절반은 실측한다(`served.in_trace_record`). 저작 경로는 genlog에 남긴다.

### 0-4. 1차 좌석이 실패하면 — ARCH-69 런타임 LOCAL 강등

학생 대면 앱은 `CompositeProvider(..., runtime_local_degrade=True)`로 조립된다(`app.py`). 저작·측정
조립에는 이 인자가 없다. 그래서 이 회차에서 1차 좌석(openrouter)이 실패하면 결과가 **세 갈래**다.

| 1차 좌석 실패 | 이 머신의 Ollama | 결과 | 프로브의 `verdict` |
|---|---|---|---|
| 429·5xx·408/타임아웃·미설정 | 떠 있다 | **LOCAL이 대신 답하고 HTTP 200**. 응답·trace에 `local_degraded=true`와 사유가 실린다 | `degraded_cause_recorded` |
| 429·5xx·408/타임아웃·미설정 | 없다(또는 LOCAL도 실패) | 원래의 클라우드 예외가 올라간다(운영 uvicorn = 500) | `error` |
| 그 밖의 4xx(401 키·402 잔액·404 모델 ID 등) | 무관 | 강등하지 않는다. 예외가 올라간다(운영 uvicorn = 500) | `error` |

**즉 실패 회차의 결과는 이 머신의 Ollama 상태에 달려 있다.** 성공 회차는 Ollama와 무관하다.
분류는 예외의 **타입과 상태코드 속성**으로 한다(`l3/providers/seat_failure.classify_seat_failure` —
메시지를 읽지 않는다). 강등 계수는 `/status`의 `cloud_local_degrade`가 프로세스 안에서 센다
(`armed`·`cloud_attempts`·`local_degrades`·`local_degrade_failures`·`by_reason`·
`seat_local_degrade_rate`).

### 0-5. 그래서 이 런북은 서버를 띄우지 않는다

운영 서버(uvicorn)에 HTTP로 보내면 좌석·기록 원가는 Langfuse에서만, 관측 모델은 어디에서도 읽을 수
없다. CLAUDE.md 「측정·게이트 도구가 판정치를 외부 관측 인프라에만 의존 금지」에 걸린다. 그래서
이 런북은 **`create_app()`이 만든 앱 객체에 같은 프로세스 안에서 HTTP(ASGI) 요청을 보낸다.**
좌석은 손대지 않고 앱이 조립한 기본값 그대로 쓴다.

| 축 | 운영 서버 | 이 런북 |
|---|---|---|
| 앱 팩토리 `create_app()` | 같음 | 같음 |
| 클라우드 좌석 조립(`CompositeProvider(cloud=build_cloud_provider(...), runtime_local_degrade=True)`) | 같음 | **같음(주입 안 함)** |
| LOCAL(Ollama) | 실제 | **실제** — 성공 회차에서는 닿지 않는다. 1차 좌석이 실패한 회차에서 강등 대상이 된다(0-4) |
| 라우트 `/v1/generate`·`/status` 핸들러·본문 검증·라우터·파이프라인 | 같음 | 같음 |
| OpenRouter 실호출(모델·`provider.only`·`allow_fallbacks=false`·`data_collection=deny`) | 같음 | 같음 |
| 앱 밖으로 전파된 예외 | HTTP 500 | 프로브의 `error`로 잡힌다(HTTP 코드 없음 — 부록에서 500임을 따로 확인했다) |
| 인증(JWT→DB 사용자 조회) | 실제 | 대체 — 메모리 사용자 1명(`dependency_overrides`, `tests/backend/test_app.py`와 같은 방식) |
| DB 세션 | 실제 | 대체 — 없음(성인·미상 사용자는 동의 판정에 DB를 읽지 않는다) |
| 응답 캐시 | `RedisCache` | `InMemoryCache`(새 프로세스라 적중 0) |
| trace | `LangfuseSink` | `RecordingTraceSink`(같은 레코드를 프로세스 안에서 읽는다 · Langfuse 전송 없음) |
| 관측 모델·제공자 예외 | 기록 안 됨 | 제공자 `generate`의 반환값과 예외를 관찰 래퍼로 읽는다(예외는 기록한 뒤 **그대로 다시 던진다** — 동작 불변) |

대체한 네 축(인증·DB·캐시·trace 전송)은 ARCH-64·ARCH-69가 건드리지 않은 축이다. 운영 서버 경로
자체의 라이브 확인은 이 회차의 범위가 아니다(5절 끝 "이 회차가 닫지 않는 것").

## 1. 과제 명칭

학생 대면 앱(`create_app()`)의 `/v1/generate`에 CLOUD_MID 본문을 1회 보내, 좌석·관측 모델·기록
원가를 확인하고, 실패하면 그 원인과 강등 여부를 남긴다.

## 2. 목적

ARCH-64 ⑤의 학생 대면 몫을 닫는다. 지금까지 확인된 것은 가짜 HTTP 전송층으로 돈 동작 계약
(`tests/backend/l3/test_cloud_mid_seat_cutover.py`)뿐이고, **실제 OpenRouter 호출이 학생 대면
조립에서 나가 그 좌석의 단가로 기록되는지**는 아무도 보지 않았다. 결과는 ARCH-71 acceptance ①의
학생 대면 증적이 되고, 실패하면 그 실패가 증적이다(폐기하지 않는다). ARCH-69 이후에는 실패가
HTTP 200 뒤에 숨을 수 있으므로, 실패 회차에서도 **원인이 파일에 남는 것**이 이 회차의 조건이다.

## 3. 구체적 절차

블록 5개(키가 이미 있으면 4개). **[C-2]만 유료 호출을 한다.**

- **[A] 준비·조회** (약 30초 · 호출 0건) — 전용 worktree를 main으로 맞추고, 실행 코드가 그
  트리에서 오는지, 앱이 조립한 좌석이 `openrouter`이고 런타임 LOCAL 강등이 장착돼 있는지,
  Anthropic API가 꺼져 있는지, 학생 기본 신호가 LOCAL로 가고 이 회차 본문이 CLOUD_MID로 가는지를
  **호출 없이** 계산한다.
- **[B] 키 자가검증** (약 10초 · 호출 0건) — OpenRouter 키가 구성돼 있는지 길이·생략 문자·접두만
  본다. 키 값은 출력하지 않는다.
- **[K-1]·[K-2] 키 등록** — **[B]가 `CONFIGURED=False`일 때만.** 이미 있으면 건너뛴다.
- **[C-1] 프로브 적재** (즉시 · 호출 0건) — 프로브 코드를 창 변수에 담기만 한다.
- **[C-2] 학생 대면 1회차** (10초~5분 · OpenRouter 호출 1건, 재시도 포함) — [A]의 판정 전부와 키·
  프로브 적재를 **스스로 다시 계산해** 하나라도 어긋나면 호출하지 않고 `WRITE_REFUSED` 한 줄을 낸다.
  통과하면 `/status` → `/v1/generate` → `/status`를 차례로 부르고 결과 JSON을 화면과 파일에 남긴다.

지연은 크게 흔들린다 — ARCH-55 4회차 실측 p50 36.9초 / p95 212.6초. 1차 좌석이 실패해 LOCAL이
대신 답하는 회차는 LOCAL 생성 시간이 더해진다. 타임아웃은 1회 시도당 60초다
(`openrouter_request_timeout_s`).

비용은 보통 1원 안팎이다(좌석 단가 추정 0.354원/회 — 가정 토큰 입력 74·출력 358 기준, 실측
토큰에 따라 달라진다). **상한은 약 15원**이다 — 출력이 `openrouter_max_tokens=16000`까지 나오는
경우의 좌석 단가 산식(입력 60~200토큰 기준 14.8원).

## 4. 성공 기준

**[A]**: `SETUP_OK=True`. False면 같은 줄에 어느 항이 어긋났는지 적힌다.

**[B]**: `CONFIGURED=True` · `KEY_HAS_ELLIPSIS=False` · `KEY_LENGTH`가 20 이상. `CONFIGURED=False`면
실패가 아니라 [K-1]·[K-2]로 가라는 신호다(단, 아래 [B] 절의 "새 창" 경우를 먼저 본다).

**[C-2]**: `PROBE_EXIT=0` · `PROBE_FILE_EXISTS=True`, 그리고 출력 JSON 끝의 `"verdict": "pass"`
(= `"all_pass": true`). 프로브의 판정은 다섯 가지다.

| `verdict` | `PROBE_EXIT` | 뜻 | 이 회차의 처리 |
|---|---|---|---|
| `pass` | 0 | 아래 9개 검사가 모두 참이고, 제공자 예외(`provider_errors`)가 0건이며 `error`가 없다 | ARCH-71 ① 학생 대면 증적 |
| `degraded_cause_recorded` | 2 | 1차 좌석이 실패해 **LOCAL이 대신 답했다(HTTP 200)**. 원인이 `provider_errors`에 있다 | **통과가 아니다.** 기록 대상 회차 — 원인과 함께 회신 |
| `degraded_cause_missing` | 1 | 강등됐는데 좌석 예외가 기록되지 않았다 | 프로브 결함 — 세션에 알린다 |
| `error` | 1 | 예외가 앱 밖으로 나왔다(운영 uvicorn = 500) 또는 제공자 예외가 있었다 | 기록 대상 회차 — `failure_path`가 갈래를 말한다 |
| `check_failed` | 1 | 예외도 강등도 없는데 검사가 거짓이다 | 회귀 의심 — 거짓인 검사가 산출물 |

| 검사(`checks`) | 참이어야 하는 이유 | 거짓이면 |
|---|---|---|
| `tier_is_cloud_mid` | 본문이 실제로 CLOUD_MID로 라우팅됐다 | 라우팅 조건이 바뀌었다 — 0-2 표 재검토(예외 회차에서는 응답이 없어 거짓) |
| `not_degraded` | 응답·trace 양쪽이 `local_degraded=false`다 — 클라우드 좌석이 직접 답했다 | 강등 회차다(0-4) — `degrade_reason`·`provider_errors`를 본다 |
| `trace_seat_is_openrouter` | 기록이 말하는 좌석이 openrouter다 | 강등 회차면 `null`이 정상. 아니면 학생 대면 좌석 조립(`app.py` → `build_cloud_provider`) 회귀 의심 |
| `openrouter_generate_entered` | OpenRouter 제공자가 요청을 받았다 | 좌석 조립 회귀 |
| `anthropic_not_called` | ARCH-66 중단 기간에 Anthropic이 불리지 않았다 | 좌석 누수 — 즉시 세션에 알린다 |
| `deepseek_not_called` | 다른 클라우드 좌석으로 새지 않았다(2차 좌석 없음) | 대체 좌석이 생겼다 — 세션에 알린다 |
| `local_not_called` | LOCAL로 새지 않았다 | 강등 회차면 거짓이 정상(`failure_path`로 확인) |
| `cost_is_openrouter_price` | 기록 원가 = 실측 토큰 × openrouter 단가 · anthropic 단가와 다르다 | 강등 회차면 원가가 LOCAL 0원이라 거짓. 아니면 원가 좌석(`pipeline.served_cloud_seat`) 회귀 |
| `served_model_observed` | 응답이 실제 모델명을 돌려줬다 | 강등·예외 회차면 OpenRouter 응답이 없어 거짓. 아니면 관측 축이 라이브에서 죽었다 |

**`failure_path`(제공자 예외에서 구조적으로 계산 — 메시지를 읽지 않는다)**

- `none` — 제공자 예외 0건
- `degraded_local_answered` — 1차 좌석 실패 → LOCAL이 답함(HTTP 200)
- `degraded_local_failed` — 1차 좌석 실패 → LOCAL 강등 시도 → LOCAL도 실패(`provider_errors`에
  `ollama` 항목이 있다) → 원래의 클라우드 예외가 올라감
- `not_degraded_raised` — 1차 좌석 실패, LOCAL 진입 0건 → 강등 비대상(4xx)으로 예외가 올라감
- `other` — 위에 해당하지 않음(세션이 JSON 전체로 판정)

**함께 읽을 값(판정 칸에 적는다)**

- `seat_primary_success_rate`는 **`null`이 정상이다.** 이 지표를 계산하는 코드는 ARCH-63 전까지
  없다(코드 판독 · `a28a8d08` — 학생 대면 경로에는 계산 자리 자체가 없다). `null`은 "모른다"이지
  "0%"가 아니다 — **0으로 접어 적지 않는다.**
- `seat_local_degrade_rate`는 **실측**이다 — 호출 뒤 `/status`의 `cloud_local_degrade`에서 읽는다.
  이 회차는 호출 1건이라 `0.0`(강등 없음) 또는 `1.0`(강등 경로를 탔음)이다. `null`이면 강등이
  장착되지 않았거나 필드가 없다는 뜻이다. 강등 경로를 탔으나 LOCAL도 실패했으면
  `local_degrade_failures=1`이 함께 찍힌다.
- `generate_http.est_cost_krw`는 8.612가 정상이다(0-3). 기록 원가는 `trace.cost_krw`다.
- `price_check.recorded_krw`가 0.354와 정확히 같지 않은 것은 정상이다. 0.354원은 가정 토큰에서의
  추정이고, 기록 원가는 이 회차의 실측 토큰으로 계산된다. 판정은 `recorded_matches`가
  `openrouter`인가로 한다.
- `served.equals_pin`이 `false`면 실패가 아니라 **사람 판정 대상**이다(별칭→버전 해소인가, 진짜
  폴백인가 — EOS-112가 기계 판정에서 뺀 축). `served.recorded_anywhere_on_this_path=false`는
  코드 판독 기준(`a28a8d08`)이고, 그중 trace 레코드 절반은 `served.in_trace_record`가 실측한다.
- `status_http.local_reachable`은 호출 **전**의 Ollama 도달 여부다 — 실패 회차가 어느 갈래로 갈지
  미리 말한다(0-4).
- `provider_errors[].message` 끝의 `(시도 3회)`는 **설정된 최대 시도 횟수**다. 실제 전송 횟수가
  아니다 — 401 같은 비재시도 상태는 1회만 보내고도 `(시도 3회)`로 적힌다(부록 ⑦ 실측).

**실패 시 대처**: `verdict`가 `pass`가 아니면 **JSON 전체를 그대로** 회신한다. 재시도하지 말고
먼저 회신한다(재시도 여부는 세션이 판정한다). 갈래별로 읽는 자리는 이렇다.

- `degraded_cause_recorded` — `generate_http.degrade_reason`이 사유다. `rate_limited`(429)는 공유 풀
  과부하로 기대 범위이며 그 자체가 기록 대상이다. `server_error`(5xx)·`timeout`(408 또는 60초
  타임아웃)도 같다. `not_configured`는 [C-2] 재검사(`KEY_READY`)를 통과했다면 일어나면 안 되는
  값이다 — 세션에 알린다. 원 예외(타입·상태코드·공급사 응답 본문)는
  `provider_errors`의 `openrouter` 항목에 있다.
- `error` + `failure_path=degraded_local_failed` — 1차 좌석도, LOCAL(Ollama)도 실패했다.
  `provider_errors`에 두 항목이 있다. 이 머신에서 Ollama를 켜고 다시 하면 같은 1차 좌석 실패가
  `degraded_cause_recorded`로 바뀐다 — **Ollama를 켜서 결과를 바꾸는 것은 세션이 판정한 뒤에** 한다.
- `error` + `failure_path=not_degraded_raised` — 강등 비대상 4xx다. `error.status_code`가 401이면
  키, 402면 잔액, 404면 모델 ID를 본다. `error.notes`에 "2차 클라우드 좌석 없음"이 보이는 것은
  ARCH-66 기간의 설계대로다.
- 화면에 JSON보다 먼저 `클라우드 좌석 실패 → LOCAL 강등 (...)` 같은 한국어 경고 줄이 나올 수
  있다 — 서버 로그(stderr)이며 판정은 JSON으로 한다.

## 5. 실행 환경

- 머신: **Phaiakes9** (= 평소 쓰는 이 PC). 별도 접속 불요.
- 시스템: **Windows PowerShell**
- 작업 디렉터리: `C:\Users\kiki\Desktop\__AI\WhyMath` (코드는 전용 worktree
  `C:\Users\kiki\Desktop\__AI\WhyMath-arch71`에서 읽는다)
- 선행 조건: 인터넷 연결 · OpenRouter 키(User 환경변수 `OPENROUTER_API_KEY` 또는
  `WHYMATH_OPENROUTER_API_KEY`). **Docker·DB·Redis·서버 불요.** Anthropic 키도 불요하다(있어도
  쓰지 않는다 — ARCH-66).
- **Ollama는 성공 경로에서만 불요하다.** 1차 좌석이 실패한 회차의 결과는 Ollama 상태에 달려
  있다(0-4). 켜거나 끌 필요는 없다 — 그 회차의 상태가 `status_http.local_reachable`에 찍힌다.
- 좌석·키·Anthropic 스위치 판정은 작업 디렉터리의 `.env`까지 포함한 실효값이다(`Settings`가
  `.env`도 읽는다). 창의 `WHYMATH_CLOUD_PROVIDER`는 자식 프로세스에서 지우지만 `.env`의 값은
  남는다 — [A]의 `APP_SEAT`가 openrouter가 아니면 `.env`부터 본다.
- 전용 worktree를 쓰는 이유: Kiki 클론은 여러 세션이 공유하는 단일 작업 사본이라 브랜치를
  옮기면 다른 세션의 실행이 깨진다. worktree는 원 작업 사본의 브랜치·미커밋 변경을 하나도
  건드리지 않는다. 결과 JSON도 그 worktree 안(`WhyMath-arch71\.arch71-out\`)에 쓴다 — 공유
  클론에는 아무것도 쓰지 않는다.

**이 회차가 닫지 않는 것(명시)**: 운영 서버(uvicorn) 경로의 JWT·DB·Redis·Langfuse 전송은 재지
않는다(0-5 표). 관측 모델이 학생 대면 기록에 남지 않는 것은 이 회차가 고칠 일이 아니라 기록할
사실이다.

## 6. 창 구분

**새 PowerShell 창 1개**(이하 "창①")에서 [A]→[B]→([K-1]→[K-2])→[C-1]→[C-2]를 순서대로
붙여넣는다. 서버를 띄우지 않으므로 **점유 창이 없다.** `$Py`·`$Tree`·`$env:PYTHONPATH`는 [A]가,
`$ProbeCode`는 [C-1]이 창①에 설정하고 [C-2]가 물려받으므로 **창을 바꾸지 않는다.** [C-2]는 최대
5분쯤 걸릴 수 있으니 끝날 때까지 창①을 건드리지 않는다.

---

## [A] 준비·조회 (호출 0건)

> **자기 트리 확인**: `TREE_HAS_THIS_RUNBOOK`은 worktree에 이 런북 파일이 있는가다. 이 런북이
> main에 머지되기 전이라면 False가 나오고 `SETUP_OK=False`가 된다 — 그때는 멈추고 세션에 알린다.
> 좌석 판정이 "어느 트리의 코드인가"에 달려 있으므로 해시 대신 파일 존재로 트리를 고정한다.
> `APP_SEAT`의 네 번째 값 `True`는 런타임 LOCAL 강등 장착(ARCH-69)이다 — ARCH-69 이전 트리면
> 그 속성이 없어 줄이 비고 `SETUP_OK=False`가 된다.
>
> **기본 좌석을 잴 때 자식 프로세스에서 변수를 지우는 이유**: 창은 앞서 붙여넣은 블록이 설정한
> `$env:` 값을 들고 있다. "설정 전에 재면 기본값"이라고 가정하면 재실행한 창에서 **남아 있는 값을
> 기본값으로 오독한다**(2026-09-18 실측). 그래서 부재를 가정하지 않고 자식 프로세스에서
> `os.environ.pop`으로 만들어 잰다.

```powershell
# [창① A 준비·조회] Windows PowerShell (Phaiakes9) — 새 창 · 호출 0건
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Ref = "origin/main"
$Tree = "C:\Users\kiki\Desktop\__AI\WhyMath-arch71"
git fetch origin
if (-not (Test-Path $Tree)) { git worktree add --detach $Tree $Ref } else { git -C $Tree fetch origin; git -C $Tree checkout --detach $Ref }
git -C $Tree log -1 --oneline
$HasRunbook = Test-Path "$Tree\docs\ops\arch71_student_facing_cloud_mid_live_runbook.md"
"TREE_HAS_THIS_RUNBOOK=$HasRunbook"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe" }
if (Test-Path $Py) { "PY=$Py" } else { $Py = "python"; "PY=system — venv를 찾지 못해 PATH의 python을 씁니다" }
$env:PYTHONPATH = "$Tree\src\backend"
$Source = (& $Py -c "import whymath_backend.app as m; print(m.__file__)")
"SOURCE=$Source"
$FromTree = ($Source -like "*WhyMath-arch71*")
"FROM_TREE=$FromTree"
$Deps = (& $Py -c "import fastapi.testclient, httpx; print(True)")
"DEPS_OK=$Deps"
"PRE_SHELL_VAR=$($env:WHYMATH_CLOUD_PROVIDER)"
"PRE_USER_VAR=$([Environment]::GetEnvironmentVariable('WHYMATH_CLOUD_PROVIDER','User'))"
$AppSeat = (& $Py -c "import os; os.environ.pop('WHYMATH_CLOUD_PROVIDER', None); from whymath_backend.api._l3_state import PROVIDER_KEY; from whymath_backend.app import create_app; p=getattr(create_app().state, PROVIDER_KEY); print(p.cloud_seat, type(p._cloud).__name__, p.cloud_failover_seat, p.local_degrade_armed)")
"APP_SEAT=$AppSeat"
$AnthropicOff = (& $Py -c "from whymath_backend.config import get_settings; print(get_settings().anthropic_api_enabled is False)")
"ANTHROPIC_OFF=$AnthropicOff"
$Routes = (& $Py -c "from whymath_backend.l3.router import Router; from whymath_backend.l3.models import RoutingRequest; from whymath_backend.l3.escalation_defaults import default_student_escalation_signals as dflt; d=dflt(); base=dict(task_type='coach', difficulty='hard', requires_reasoning=True, sync=True, data_licenses=['INTERNAL_OWNED']); s=Router().route(RoutingRequest(student_subscription=d.student_subscription, budget_krw=d.budget_krw, **base)); p=Router().route(RoutingRequest(student_subscription='premium', budget_krw=1000.0, **base)); print(s.cost_tier, p.cost_tier, p.est_cost_krw)")
"ROUTES(student_default probe probe_est_krw)=$Routes"
$SetupOk = $HasRunbook -and $FromTree -and ($Deps -eq "True") -and ($AppSeat -eq "openrouter OpenRouterProvider None True") -and ($AnthropicOff -eq "True") -and ($Routes -like "local cloud_mid *")
if ($SetupOk) { "SETUP_OK=True" } else { "SETUP_OK=False — TREE_HAS_THIS_RUNBOOK=$HasRunbook FROM_TREE=$FromTree DEPS_OK=$Deps APP_SEAT=[$AppSeat](openrouter OpenRouterProvider None True여야 함 — 마지막 True는 ARCH-69 강등 장착) ANTHROPIC_OFF=$AnthropicOff ROUTES=[$Routes](local cloud_mid로 시작해야 함). 이 줄과 위 worktree 줄을 회신해 주십시오." }
```

**`SETUP_OK=True`를 눈으로 확인한 다음에만 [B]를 붙여넣으십시오.** (확인을 건너뛰어도 [C-2]가
[A]의 여섯 항을 모두 다시 계산해 스스로 거부한다.)

## [B] 키 자가검증 (호출 0건 · 키 값 미출력)

```powershell
# [창① B 키 자가검증] Windows PowerShell — 같은 창 · 호출 0건 · 키 값은 출력하지 않는다
cd C:\Users\kiki\Desktop\__AI\WhyMath
& $Py -c "import asyncio; from whymath_backend.l3.providers.openrouter import OpenRouterProvider; s=asyncio.run(OpenRouterProvider().check_status()); print(f'CONFIGURED={s.configured} PROVIDERS={s.allowed_providers} JURISDICTION={s.jurisdiction} ERROR={s.error}')"
"CHECK_EXIT=$LASTEXITCODE"
& $Py -c "from whymath_backend.config import get_settings; k=get_settings().openrouter_api_key.get_secret_value(); print('KEY_LENGTH=%d KEY_HAS_ELLIPSIS=%s KEY_PREFIX_SK_OR=%s' % (len(k), chr(8230) in k, k.startswith('sk-or-')))"
"USER_VAR_OPENROUTER_API_KEY_SET=$([bool][Environment]::GetEnvironmentVariable('OPENROUTER_API_KEY','User'))"
"USER_VAR_WHYMATH_OPENROUTER_API_KEY_SET=$([bool][Environment]::GetEnvironmentVariable('WHYMATH_OPENROUTER_API_KEY','User'))"
```

- `CONFIGURED=True`면 [K-1]·[K-2]를 **건너뛰고** [C-1]로 간다.
- `CONFIGURED=False`인데 `USER_VAR_..._SET=True`가 하나라도 있으면 **키 등록 전에 연 창**이다
  (User 환경변수는 등록 뒤에 연 창만 물려받는다). [K]로 가지 말고 **새 창을 열어 [A]부터** 다시
  붙여넣는다.
- `CONFIGURED=False`이고 `USER_VAR_..._SET`이 둘 다 False면 [K-1]로 간다.
- `CONFIGURED=True`인데 `KEY_HAS_ELLIPSIS=True`거나 `KEY_LENGTH`가 20 미만이면 **멈추고 이 네 줄을
  회신한다**(자리표시자 문자열이 키로 등록된 상태일 수 있다 — 2026-07-16 사고 유형). 이 런북은
  기존 키를 덮어쓰지 않는다.

## [K-1] 키 입력 — [B]가 `CONFIGURED=False`일 때만

> ⚠ **이 블록만 단독으로 붙여넣는다.** `Read-Host`는 뒤에 붙여넣은 줄을 입력값으로 삼킨다
> (2026-09-18 실측). 입력은 화면에 보이지 않는다(별표도 없다). 입력 길이는 같은 줄이 바로
> 출력한다 — 0이면 붙여넣기가 실패한 것이다.

```powershell
# [창① K-1 키 입력] Windows PowerShell — 같은 창 · 이 블록만 단독으로 붙여넣는다 · 입력은 화면에 보이지 않는다
cd C:\Users\kiki\Desktop\__AI\WhyMath
$KeySecure = Read-Host "OpenRouter 키(sk-or- 로 시작)를 붙여넣고 Enter" -AsSecureString; "KEY_INPUT_LENGTH=$($KeySecure.Length)"
```

## [K-2] 키 등록 — [K-1] 다음에만

이 블록은 입력 형태를 **스스로 다시 검사해** 어긋나면 쓰지 않는다. 기존 User 키가 있으면
덮어쓰지 않는다(교체가 필요하면 세션에 알린다). 쓴 뒤에는 User 환경변수를 되읽어 **길이만**
출력한다.

```powershell
# [창① K-2 키 등록] Windows PowerShell — 같은 창 · User 환경변수 1개를 쓴다 · 키 값은 출력하지 않는다
cd C:\Users\kiki\Desktop\__AI\WhyMath
$KeyBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($KeySecure)
$KeyPlain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($KeyBstr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($KeyBstr)
$KeyLength = ([string]$KeyPlain).Length
$KeyShapeOk = ($KeyLength -ge 20) -and ([string]$KeyPlain).StartsWith("sk-or-") -and (-not ([string]$KeyPlain).Contains([string][char]0x2026))
$ExistingUserKey = [bool][Environment]::GetEnvironmentVariable("OPENROUTER_API_KEY", "User")
"KEY_LENGTH=$KeyLength KEY_SHAPE_OK=$KeyShapeOk EXISTING_USER_KEY=$ExistingUserKey"
if ($KeyShapeOk -and (-not $ExistingUserKey)) { [Environment]::SetEnvironmentVariable("OPENROUTER_API_KEY", $KeyPlain, "User"); $env:OPENROUTER_API_KEY = $KeyPlain; "WRITTEN_USER_KEY_LENGTH=$(([string][Environment]::GetEnvironmentVariable('OPENROUTER_API_KEY','User')).Length)" } else { "WRITE_REFUSED=True — 키를 쓰지 않았다. KEY_SHAPE_OK=$KeyShapeOk(True여야 함 — 20자 이상·sk-or- 시작·생략 문자 없음) EXISTING_USER_KEY=$ExistingUserKey(False여야 함 — 있으면 덮어쓰지 않는다)" }
Remove-Variable KeyPlain, KeySecure
```

`WRITTEN_USER_KEY_LENGTH`가 `KEY_LENGTH`와 같으면 등록된 것이다. **[B]를 다시 붙여넣어
`CONFIGURED=True`를 확인한 뒤** [C-1]로 간다(이 창에는 `$env:OPENROUTER_API_KEY`도 설정됐다 —
새 창은 User 환경변수를 자동으로 물려받는다).

## [C-1] 프로브 적재 (호출 0건)

코드를 창 변수 `$ProbeCode`에 담기만 한다. 실행은 [C-2]가 한다. 코드가 하는 일:

1. 좌석 환경변수를 지워 **기본 좌석**으로 앱을 만든다(`create_app(cache=InMemoryCache(),
   trace=RecordingTraceSink())` — 좌석은 주입하지 않는다).
2. 인증·DB 세션만 메모리 대역으로 바꾼다(0-5 표).
3. 제공자 4종의 `generate`를 관찰한다 — 진입을 세고, OpenRouter는 반환값의 `usage`(관측 모델·
   재시도)를 읽고, **어느 제공자든 예외를 던지면 타입·상태코드·메시지(2000자)를 기록한 뒤 그대로
   다시 던진다.** 기록 즉시 결과 파일을 다시 쓴다 — LOCAL 강등이 오래 걸리다 멈춰도 1차 좌석의
   실패 원인은 파일에 남는다. 동작은 바꾸지 않는다.
4. 호출 전에 같은 본문을 라우터에 **건조 실행**해 CLOUD_MID가 아니면 부르지 않는다.
5. `/status` → `/v1/generate` → `/status` 순으로 부른다. 응답 본문과 trace 레코드에서 좌석·기록
   원가·토큰·강등 필드를 읽고, 호출 뒤 `/status`에서 강등 계수(`cloud_local_degrade`)를 읽는다.
   앱 밖으로 나온 예외는 `error`로 잡고 뒤 단계를 계속한다.
6. 기록 원가를 좌석 단가 산식과 대조하고, `failure_path`·`checks`·`verdict`를 계산한다.
7. 호출 직전·제공자 예외 직후·호출 직후·끝에 결과 JSON을 파일에 쓴다 — 도중에 멈춰도 증거가 남는다.

> **왜 ASCII 전용인가**: 코드는 `$ProbeCode | & $Py -`로 파이썬 표준입력에 넘긴다. Windows
> PowerShell 5.1은 그 파이프를 `$OutputEncoding`(기본 US-ASCII)으로 인코딩하므로 한글이 있으면
> `?`로 깨진다. 출력도 `ensure_ascii`라 cp949 콘솔 왕복에서 깨지지 않는다(한글 오류 문구·note는
> `\uXXXX`로 나온다 — 세션이 복원한다). 프롬프트가 영어인 것도 같은 이유이며, 이 회차는 품질이
> 아니라 좌석을 잰다. 같은 이유로 코드에 작은따옴표가 없다(here-string 안전).

```powershell
# [창① C-1 프로브 적재] Windows PowerShell — 같은 창 · 변수 대입만 · 호출 0건
cd C:\Users\kiki\Desktop\__AI\WhyMath
$ProbeCode = @'
import datetime, json, math, os, sys, uuid
os.environ.pop("WHYMATH_CLOUD_PROVIDER", None)
OUT = os.environ.get("ARCH71_PROBE_OUT")
BASIS = "code reading at main a28a8d08"
report = {"probe": "arch71-student-facing-cloud-mid", "probe_rev": "arch69-degrade-aware", "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "stage": "import"}
calls = {"openrouter": 0, "anthropic": 0, "deepseek": 0, "ollama": 0}
usages = []
failures = []
def flush():
    text = json.dumps(report, ensure_ascii=True, indent=2, default=str)
    if OUT:
        with open(OUT, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return text
def describe(exc):
    code = getattr(exc, "status_code", None)
    return {"type": type(exc).__name__, "status_code": code if isinstance(code, int) and not isinstance(code, bool) else None, "message": str(exc)[:2000], "notes": [str(note)[:2000] for note in getattr(exc, "__notes__", [])]}
def provider_errors():
    return [dict({"provider": name}, **describe(exc)) for name, exc in failures]
def spy(cls, name, keep):
    original = cls.generate
    async def wrapped(self, *args, **kwargs):
        calls[name] += 1
        try:
            result = await original(self, *args, **kwargs)
        except Exception as exc:
            failures.append((name, exc))
            report["provider_errors"] = provider_errors()
            flush()
            raise
        if keep:
            usages.append(result.usage)
        return result
    cls.generate = wrapped
try:
    import whymath_backend.app as app_module
    from fastapi.testclient import TestClient
    from whymath_backend.api._auth import get_current_user
    from whymath_backend.api._l3_state import PROVIDER_KEY
    from whymath_backend.config import get_settings
    from whymath_backend.db.models.user import UserProfile
    from whymath_backend.db.session import get_session
    from whymath_backend.l3.escalation_defaults import default_student_escalation_signals
    from whymath_backend.l3.interfaces import InMemoryCache, RecordingTraceSink
    from whymath_backend.l3.models import CostTier, RoutingRequest
    from whymath_backend.l3.providers.anthropic import AnthropicProvider
    from whymath_backend.l3.providers.deepseek import DeepSeekProvider
    from whymath_backend.l3.providers.ollama import OllamaProvider
    from whymath_backend.l3.providers.openrouter import OpenRouterProvider
    from whymath_backend.l3.router import CLOUD_MIN_COST_KRW, CLOUD_TOKEN_PRICE_USD_PER_1M, USD_TO_KRW, Router
    report["source"] = app_module.__file__
    settings = get_settings()
    report["settings"] = {"cloud_provider": settings.cloud_provider, "anthropic_api_enabled": settings.anthropic_api_enabled, "openrouter_model_mid": settings.openrouter_model_mid, "openrouter_allowed_providers": list(settings.openrouter_allowed_providers), "openrouter_max_tokens": settings.openrouter_max_tokens, "openrouter_request_timeout_s": settings.openrouter_request_timeout_s}
    spy(OpenRouterProvider, "openrouter", True)
    spy(AnthropicProvider, "anthropic", False)
    spy(DeepSeekProvider, "deepseek", False)
    spy(OllamaProvider, "ollama", False)
    body = {
        "request": {
            "task_type": "coach",
            "difficulty": "hard",
            "requires_reasoning": True,
            "student_subscription": "premium",
            "budget_krw": 1000.0,
            "sync": True,
            "data_licenses": ["INTERNAL_OWNED"],
        },
        "prompt": "In two short sentences, explain why the sum of two odd integers is always even. Probe " + report["started_utc"],
        "system": "You are a concise math tutor. Answer in plain English.",
    }
    report["body_request"] = body["request"]
    defaults = default_student_escalation_signals()
    student_request = dict(body["request"], student_subscription=defaults.student_subscription, budget_krw=defaults.budget_krw)
    report["student_default_route"] = {"student_subscription": defaults.student_subscription, "budget_krw": defaults.budget_krw, "cost_tier": Router().route(RoutingRequest(**student_request)).cost_tier}
    dry = Router().route(RoutingRequest(**body["request"]))
    report["dry_route"] = {"cost_tier": dry.cost_tier, "est_cost_krw": dry.est_cost_krw, "reason": dry.reason, "data_export_reason": dry.data_export_reason}
    report["est_krw_per_call_at_assumed_tokens"] = {"openrouter": CLOUD_MIN_COST_KRW[(CostTier.CLOUD_MID, "openrouter")], "anthropic": CLOUD_MIN_COST_KRW[(CostTier.CLOUD_MID, "anthropic")]}
    if dry.cost_tier != CostTier.CLOUD_MID.value:
        raise RuntimeError("dry route is not cloud_mid - no call was made")
    trace = RecordingTraceSink()
    app = app_module.create_app(cache=InMemoryCache(), trace=trace)
    provider = getattr(app.state, PROVIDER_KEY)
    report["app"] = {"provider_class": type(provider).__name__, "cloud_class": type(getattr(provider, "_cloud", None)).__name__, "cloud_seat": getattr(provider, "cloud_seat", "absent"), "cloud_failover_seat": getattr(provider, "cloud_failover_seat", "absent"), "local_degrade_armed": getattr(provider, "local_degrade_armed", "absent")}
    probe_user = UserProfile(user_id=uuid.uuid4())
    app.dependency_overrides[get_current_user] = lambda: probe_user
    async def no_database():
        yield None
    app.dependency_overrides[get_session] = no_database
    client = TestClient(app)
    status_response = client.get("/status")
    status_body = status_response.json()
    report["status_http"] = {"code": status_response.status_code, "cloud_seat": status_body.get("cloud_seat", "absent"), "cloud_failover_seat": status_body.get("cloud_failover_seat", "absent"), "cloud_configured": status_body.get("cloud_configured"), "cloud_error": status_body.get("cloud_error"), "local_reachable": status_body.get("reachable"), "local_ready": status_body.get("ready"), "cloud_local_degrade": status_body.get("cloud_local_degrade", "absent")}
    report["provider_errors"] = []
    report["stage"] = "call"
    flush()
    try:
        response = client.post("/v1/generate", json=body)
    except Exception as exc:
        report["error"] = dict(describe(exc), where="exception escaped the app from /v1/generate - the app has no handler for it, so uvicorn answers 500")
        response = None
    report["stage"] = "called"
    if response is None:
        report["generate_http"] = {"code": None, "escaped_exception": report["error"]["type"]}
    if response is not None:
        try:
            response_body = response.json()
        except ValueError:
            response_body = {"detail": response.text[:2000]}
        decision = response_body.get("decision") or {}
        text = response_body.get("text") or ""
        report["generate_http"] = {"code": response.status_code, "cost_tier": decision.get("cost_tier"), "reason": decision.get("reason"), "est_cost_krw": decision.get("est_cost_krw"), "cache_hit": response_body.get("cache_hit"), "local_degraded": response_body.get("local_degraded", "absent"), "degraded_from_seat": response_body.get("degraded_from_seat", "absent"), "degrade_reason": response_body.get("degrade_reason", "absent"), "text_chars": len(text), "text_head": text[:80], "detail": response_body.get("detail")}
    flush()
    record = trace.records[-1] if trace.records else {}
    report["trace_records"] = len(trace.records)
    report["trace"] = {key: record.get(key, "absent") for key in ("cost_tier", "cloud_seat", "cost_krw", "input_tokens", "output_tokens", "latency_ms", "content_source", "cache_hit", "data_export_reason", "local_degraded", "degraded_from_seat", "degrade_reason", "degraded_to_local", "degrade_cloud_attempt_ms")}
    status_after = client.get("/status")
    after_degrade = status_after.json().get("cloud_local_degrade", "absent")
    report["status_after_http"] = {"code": status_after.status_code, "cloud_local_degrade": after_degrade}
    report["seat_local_degrade_rate"] = after_degrade.get("seat_local_degrade_rate") if isinstance(after_degrade, dict) else None
    report["seat_local_degrade_rate_note"] = "measured in this process from /status cloud_local_degrade after the call (ARCH-69) - one call, so 0.0 or 1.0; None means not armed or absent, not 0"
    tokens_in, tokens_out, recorded = record.get("input_tokens"), record.get("output_tokens"), record.get("cost_krw")
    measurable = None not in (tokens_in, tokens_out, recorded)
    def seat_krw(seat):
        price_in, price_out = CLOUD_TOKEN_PRICE_USD_PER_1M[(CostTier.CLOUD_MID, seat)]
        return (tokens_in * price_in + tokens_out * price_out) / 1000000 * USD_TO_KRW
    price = {"recorded_krw": recorded, "if_openrouter_krw": seat_krw("openrouter") if measurable else None, "if_anthropic_krw": seat_krw("anthropic") if measurable else None, "recorded_matches": "unmeasured"}
    if measurable and math.isclose(recorded, price["if_openrouter_krw"], rel_tol=1e-9):
        price["recorded_matches"] = "openrouter"
    if measurable and math.isclose(recorded, price["if_anthropic_krw"], rel_tol=1e-9):
        price["recorded_matches"] = "anthropic"
    if measurable and price["recorded_matches"] == "unmeasured":
        price["recorded_matches"] = "neither"
    report["price_check"] = price
    usage = usages[-1] if usages else None
    served = getattr(usage, "served_model", None)
    report["served"] = {"served_model": served, "declared_pin": settings.openrouter_model_mid, "equals_pin": None if served is None else served == settings.openrouter_model_mid, "retries": getattr(usage, "retries", None), "in_trace_record": "served_model" in record, "recorded_anywhere_on_this_path": False, "recorded_anywhere_basis": BASIS + " - langfuse_fields has no served_model key; in_trace_record is the measured half"}
    report["stage"] = "done"
except Exception as exc:
    report["error" if "error" not in report else "probe_error"] = dict(describe(exc), where="probe stage " + str(report.get("stage")))
report["provider_generate_entries"] = calls
report["provider_generate_entries_note"] = "counts entries into each provider generate method, not network requests"
report["provider_errors"] = provider_errors()
report["provider_errors_note"] = "every exception raised by a provider generate method, recorded then re-raised; notes are read at the end so the CompositeProvider note is included"
report["seat_primary_success_rate"] = None
report["seat_primary_success_rate_note"] = "not computed: no code on this path computes it until ARCH-63 (" + BASIS + ") - None means unmeasured, not 0"
gen = report.get("generate_http", {})
tr = report.get("trace", {})
seat_failed = any(name == "openrouter" for name, exc in failures)
local_failed = any(name == "ollama" for name, exc in failures)
path = "other"
if not failures:
    path = "none"
elif seat_failed and gen.get("local_degraded") is True:
    path = "degraded_local_answered"
elif seat_failed and calls["ollama"] >= 1 and local_failed:
    path = "degraded_local_failed"
elif seat_failed and calls["ollama"] == 0 and gen.get("local_degraded") is not True:
    path = "not_degraded_raised"
report["failure_path"] = path
checks = {
    "tier_is_cloud_mid": gen.get("cost_tier") == "cloud_mid",
    "not_degraded": gen.get("local_degraded") is False and tr.get("local_degraded") is False,
    "trace_seat_is_openrouter": tr.get("cloud_seat") == "openrouter",
    "openrouter_generate_entered": calls["openrouter"] >= 1,
    "anthropic_not_called": calls["anthropic"] == 0,
    "deepseek_not_called": calls["deepseek"] == 0,
    "local_not_called": calls["ollama"] == 0,
    "cost_is_openrouter_price": report.get("price_check", {}).get("recorded_matches") == "openrouter",
    "served_model_observed": report.get("served", {}).get("served_model") is not None,
}
report["checks"] = checks
report["all_pass"] = all(checks.values()) and not failures and "error" not in report and "probe_error" not in report
verdict = "check_failed"
if report["all_pass"]:
    verdict = "pass"
elif gen.get("local_degraded") is True:
    verdict = "degraded_cause_recorded" if seat_failed else "degraded_cause_missing"
elif failures or "error" in report or "probe_error" in report:
    verdict = "error"
report["verdict"] = verdict
print(flush())
sys.exit({"pass": 0, "degraded_cause_recorded": 2}.get(verdict, 1))
'@
$ProbeLines = ($ProbeCode -split "\n").Count
"PROBE_CODE_LINES=$ProbeLines"
```

`PROBE_CODE_LINES=182`이 보이면 적재된 것이다.

## [C-2] 학생 대면 1회차 (OpenRouter 호출 1건)

이 블록은 [A]의 여섯 항(런북 존재·트리 출처·의존성·좌석 조립·Anthropic 스위치·라우팅)과 키 준비·
프로브 적재를 **스스로 다시 계산해** 하나라도 어긋나면 호출하지 않고 `WRITE_REFUSED` 한 줄을 낸다.
그 줄에 무엇이 어긋났는지 적힌다. 결과 폴더는 통과했을 때만 만든다.

```powershell
# [창① C-2 학생 대면 1회차] Windows PowerShell — 같은 창 · OpenRouter 유료 호출 1건(재시도 포함) · 보통 1원 안팎 · 상한 약 15원
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$HasRunbook = Test-Path "$Tree\docs\ops\arch71_student_facing_cloud_mid_live_runbook.md"
$Source = (& $Py -c "import whymath_backend.app as m; print(m.__file__)")
$FromTree = ($Source -like "*WhyMath-arch71*")
$Deps = (& $Py -c "import fastapi.testclient, httpx; print(True)")
$AppSeat = (& $Py -c "import os; os.environ.pop('WHYMATH_CLOUD_PROVIDER', None); from whymath_backend.api._l3_state import PROVIDER_KEY; from whymath_backend.app import create_app; p=getattr(create_app().state, PROVIDER_KEY); print(p.cloud_seat, type(p._cloud).__name__, p.cloud_failover_seat, p.local_degrade_armed)")
$AnthropicOff = (& $Py -c "from whymath_backend.config import get_settings; print(get_settings().anthropic_api_enabled is False)")
$Routes = (& $Py -c "from whymath_backend.l3.router import Router; from whymath_backend.l3.models import RoutingRequest; from whymath_backend.l3.escalation_defaults import default_student_escalation_signals as dflt; d=dflt(); base=dict(task_type='coach', difficulty='hard', requires_reasoning=True, sync=True, data_licenses=['INTERNAL_OWNED']); s=Router().route(RoutingRequest(student_subscription=d.student_subscription, budget_krw=d.budget_krw, **base)); p=Router().route(RoutingRequest(student_subscription='premium', budget_krw=1000.0, **base)); print(s.cost_tier, p.cost_tier, p.est_cost_krw)")
$KeyReady = (& $Py -c "import asyncio; from whymath_backend.config import get_settings; from whymath_backend.l3.providers.openrouter import OpenRouterProvider; k=get_settings().openrouter_api_key.get_secret_value(); print(asyncio.run(OpenRouterProvider().check_status()).configured and len(k) >= 20 and chr(8230) not in k)")
$ProbeLoaded = ([string]$ProbeCode).Contains("arch69-degrade-aware")
"RECHECK TREE_HAS_THIS_RUNBOOK=$HasRunbook FROM_TREE=$FromTree DEPS_OK=$Deps APP_SEAT=[$AppSeat] ANTHROPIC_OFF=$AnthropicOff ROUTES=[$Routes] KEY_READY=$KeyReady PROBE_LOADED=$ProbeLoaded"
if ($HasRunbook -and $FromTree -and ($Deps -eq "True") -and ($AppSeat -eq "openrouter OpenRouterProvider None True") -and ($AnthropicOff -eq "True") -and ($Routes -like "local cloud_mid *") -and ($KeyReady -eq "True") -and $ProbeLoaded) { $OutDir = Join-Path $Tree ".arch71-out"; New-Item -ItemType Directory -Force -Path $OutDir | Out-Null; $ProbeFile = Join-Path $OutDir "student-facing-$Stamp.json"; $env:ARCH71_PROBE_OUT = $ProbeFile; $ProbeCode | & $Py -; "PROBE_EXIT=$LASTEXITCODE"; "PROBE_FILE=$ProbeFile"; "PROBE_FILE_EXISTS=$(Test-Path $ProbeFile)" } else { "WRITE_REFUSED=True — 호출 0건. TREE_HAS_THIS_RUNBOOK=$HasRunbook(True여야 함) FROM_TREE=$FromTree(True여야 함) DEPS_OK=$Deps(True여야 함) APP_SEAT=[$AppSeat](openrouter OpenRouterProvider None True여야 함) ANTHROPIC_OFF=$AnthropicOff(True여야 함 — ARCH-66) ROUTES=[$Routes](local cloud_mid로 시작해야 함) KEY_READY=$KeyReady(True여야 함 — [B]·[K]) PROBE_LOADED=$ProbeLoaded(True여야 함 — 이 판의 [C-1]을 먼저). [A]부터 다시 붙여넣고 그 출력을 회신해 주십시오." }
```

화면에 JSON이 먼저 나오고 그 아래 `PROBE_EXIT=`·`PROBE_FILE=`·`PROBE_FILE_EXISTS=` 세 줄이
나온다. JSON 원본은 worktree 안의 `C:\Users\kiki\Desktop\__AI\WhyMath-arch71\.arch71-out\student-facing-<시각>.json`에
남는다(`.gitignore` 등재 폴더 — 커밋되지 않는다). 재실행하면 새 시각의 파일이 생기고 앞 파일은
그대로 남는다(실패 회차 폐기 금지). **세션이 회신을 기록하기 전에는 worktree를 지우지 않는다** —
`git worktree remove`는 그 폴더도 함께 지운다.

## 회신해 주실 것 (보고 양식)

아래를 **순서대로** 복사해 세션 채팅에 붙여 주십시오. 출력 그대로가 좋습니다(설명은 불요).

1. [A]: `git -C $Tree log -1 --oneline`이 찍은 한 줄, 그리고 `SETUP_OK` 줄(False면 그 줄 전체와
   `APP_SEAT`·`ROUTES` 줄)
2. [B]: `CONFIGURED=`로 시작하는 줄과 `KEY_LENGTH=`로 시작하는 줄([K]를 했다면 `WRITTEN_USER_KEY_LENGTH`
   줄도)
3. [C-2]: `RECHECK` 줄, 그리고 **JSON 전체**(`{`부터 `}`까지), 그리고 `PROBE_EXIT`·`PROBE_FILE_EXISTS` 줄
4. `WRITE_REFUSED`가 나왔다면 그 한 줄만

## 판정 후 처리 (세션 몫)

- `verdict=pass`면 ARCH-71 acceptance ①의 학생 대면 1회차 증적으로 적는다 — 판정 칸에
  `seat_primary_success_rate=None(미산출 · ARCH-63 전 정상)`을 **그대로** 적고 0으로 쓰지 않는다.
  `seat_local_degrade_rate=0.0`(실측 · 분모 1)을 함께 적는다.
- `verdict=degraded_cause_recorded`면 **통과로 적지 않는다.** 학생 대면 강등 경로가 라이브에서
  작동한 1회로 적고(`degrade_reason`·원 예외·`degrade_cloud_attempt_ms`), 좌석 자체의 라이브 확인은
  다음 회차로 넘긴다.
- `verdict=error`·`check_failed`면 거짓인 검사·`error`·`provider_errors`가 이 회차의 산출물이다.
  원인을 실측 규명해 수정 태스크로 분리 등재하고, 회차를 폐기하지 않는다(재시도 회차는 새 파일로
  남는다 — 앞 파일을 지우지 않는다).
- `served.equals_pin=false`면 `served_model`을 보고 별칭→버전 해소인지 진짜 폴백인지 사람이 판정해
  기록한다.
- 관측 모델이 학생 대면 기록에 남지 않는다는 사실(0-3)은 이 회차의 결과와 무관하게 후속 등재
  대상이다(세션 몫).

## 부록 — 이 런북의 사전 검증 (컨테이너 · 판정 기준 main `a28a8d08`)

「검증 없는 실행 안내 금지」에 따라, 안내 전에 각 블록이 기대 산출물을 실제로 내는 코드 경로인지
확인했다. **라이브 호출은 이 컨테이너에서 불가하므로**(키 없음) 확인 범위는 가짜 전송층까지다.
실제 OpenRouter 응답 형태·지연·429는 이 회차가 처음 본다.

재현 방법: `git archive origin/main`(`a28a8d08`)의 `src/backend`·`docs` 사본에서, [C-1]의
here-string 본문을 **이 파일에서 그대로 떼어내** 실행했다(ASCII 전용·작은따옴표 0개도 같은
추출본으로 단언). 실제 `HttpxChatTransport`(재시도·백오프 포함)를 그대로 타고 `httpx.AsyncClient.post`
하나만 대역으로 바꿨다. "Ollama 가동"은 `OllamaProvider.generate`만 대역으로 바꾼 것이라, 그
시나리오에서도 `status_http.local_reachable`은 False로 찍힌다(상태 점검은 바꾸지 않았다). 실 키·
실 OpenRouter 호출은 쓰지 않았다.

| # | 시나리오 | HTTP | 강등 | `degrade_reason` | `provider_errors` 요지 | `verdict` / `PROBE_EXIT` |
|---|---|---|---|---|---|---|
| ① | 정상 | 200 | 아니오(`local_degraded=false`) | `null` | 없음(`[]`) | `pass` / 0 |
| ② | 429 + Ollama 가동 | 200 | **예** — LOCAL이 답함 | `rate_limited` | openrouter `SeatHttpError` 429, 공급사 본문 포함, 전송 3회(백오프 2회) | `degraded_cause_recorded` / 2 |
| ③ | 429 + Ollama 부재 | 없음(예외 전파 · 운영 500) | 시도했으나 LOCAL 실패 | 응답 없음 | openrouter `SeatHttpError` 429 + ollama `ConnectionError`, openrouter note에 LOCAL 실패 사유 | `error` / 1 |
| ④ | 5xx(503) + Ollama 가동 | 200 | **예** | `server_error` | openrouter `SeatHttpError` 503, 전송 3회 | `degraded_cause_recorded` / 2 |
| ⑤ | 타임아웃 + Ollama 가동 | 200 | **예** | `timeout` | openrouter `ReadTimeout`(`status_code=null`), 전송 1회(예외는 재시도하지 않는다) | `degraded_cause_recorded` / 2 |
| ⑥ | 미설정(키 없음) + Ollama 가동 | 200 | **예** | `not_configured` | openrouter `SeatNotConfiguredError`, 전송 0회 · `/status`의 `cloud_configured=false` | `degraded_cause_recorded` / 2 |
| ⑦ | 4xx(401) — 비강등 대조군 | 없음(예외 전파 · 운영 500) | 아니오(강등 비대상) | 응답 없음 | openrouter `SeatHttpError` 401, 전송 1회, note에 "강등 대상이 아니라" | `error` / 1 |

시나리오별로 함께 확인한 값:

- ① 9개 검사 전건 참 · 실제로 나간 본문이 `deepseek/deepseek-v4.1-flash` · `provider.only=["deepinfra"]`·
  `allow_fallbacks=false`·`data_collection=deny` · `max_tokens=16000` · 기록 원가 0.04004원이
  openrouter 산식과 일치(anthropic 산식 0.8778원과 불일치) · `student_default_route.cost_tier=local` ·
  `dry_route.est_cost_krw=8.61168`(0-3의 간극) · 호출 전 `/status`의 강등 블록 `armed=true`·
  `cloud_attempts=0`·`seat_local_degrade_rate=null`, 호출 뒤 `cloud_attempts=1`·`local_degrades=0`·
  `seat_local_degrade_rate=0.0` · `served.in_trace_record=false`.
- ②④⑤⑥ `failure_path=degraded_local_answered` · 응답 `local_degraded=true`·`degraded_from_seat=openrouter` ·
  trace `cloud_seat=null`·`cost_krw=0.0`·`degraded_to_local=math/mid`·`degrade_cloud_attempt_ms` 값 있음 ·
  호출 뒤 `/status`의 `local_degrades=1`·`by_reason`에서 해당 사유 1·`seat_local_degrade_rate=1.0` ·
  거짓 검사 5개(`not_degraded`·`trace_seat_is_openrouter`·`local_not_called`·`cost_is_openrouter_price`·
  `served_model_observed`). **즉시 기록 확인**: LOCAL 대역이 불리는 순간 결과 파일을 열어 보니
  1차 좌석 예외가 이미 적혀 있었다(4개 시나리오 전부).
- ③ `failure_path=degraded_local_failed` · 호출 뒤 `/status`의 `local_degrades=1`·
  `local_degrade_failures=1`·`seat_local_degrade_rate=1.0` · `error`에 원래의 429 예외와 note.
  초판 부록이 "429 → error"로 적은 결과는 **이 갈래(Ollama 부재)에서만** 참이다.
- ⑦ `failure_path=not_degraded_raised` · ollama 진입 0 · 호출 뒤 `seat_local_degrade_rate=0.0`
  (분모 1·분자 0). 메시지는 `(시도 3회)`인데 실제 전송은 1회였다 — 4절 "함께 읽을 값" 참조.
- **운영 HTTP 코드 확인**: ③⑦을 `TestClient(raise_server_exceptions=False)`로 다시 돌리자
  둘 다 `500 Internal Server Error`였다(앱에 이 예외들의 핸들러가 없다 — `app.py`에
  `exception_handler` 0건). 그 모드에서도 `provider_errors`가 원인을 그대로 담았다.
- **[A][B][C-2]의 `-c` 한 줄 코드**도 이 파일에서 떼어내 같은 사본에서 돌려 기대 출력
  (`openrouter OpenRouterProvider None True`·`local cloud_mid 8.61168`·`True`)을 확인했다. 변별력:
  ARCH-69 이전 트리(`ab9f29f2`)에서는 `APP_SEAT`가 `AttributeError`로 비고,
  `WHYMATH_ANTHROPIC_API_ENABLED=true`면 `ANTHROPIC_OFF=False`, 키가 없으면 `KEY_READY=False`다.

### 이 런북에 대한 CI 가드의 실제 적용 범위 (정직한 공백)

`check_runbook_blocks.py`(infra-contracts)·`check_ps_scripts.py`(infra-shell)·`cp949_guard.py`
(policy-guard)가 이 파일을 통과시킨다. **다만 [C-2]의 자가거부 가드는 사람이 쓴 것이고 기계가
지키지 않는다** — 가드 스캐너의 쓰기 어휘에 "유료 외부 호출" 축이 없어 [C-2]가 쓰기 블록으로
분류되지 않는다(EOS-118 런북 부록과 같은 공백 · 상환 = `HARN-116`). 기계가 실제로 지키는 쓰기
블록은 User 환경변수를 쓰는 [K-2]뿐이다. 이 런북을 고치는 사람은 [C-2]의 가드를 CI가 지켜 준다고
가정하지 말 것.
