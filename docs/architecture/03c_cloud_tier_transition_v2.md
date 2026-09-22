# 클라우드 티어 전환 설계 v2 — HIGH=Opus 5 · MAIN=DeepSeek V4.1(OpenRouter) · LOW=로컬

> **판정 기준: main `d10ba109`** (2026-09-21 조회). 이 문서의 "현재" 서술은 전부 그 시점 trunk 기준이다.
> **결정 주체**: Kiki (2026-09-21 대화). **설계·실측**: claude 세션.
> 상위 정본: `docs/architecture/03a_l3_router_design.md` · `CLAUDE.md` 기술 스택 표.

## 0. 이 문서가 답하는 것

Kiki가 2026-09-21에 지시한 3단 구성으로 클라우드 좌석을 재배치한다.

| 티어 | 목표 구성 | main `d10ba109` 실체 | 간극 |
|---|---|---|---|
| **LOW** | 로컬 LLM (Phaiakes9 / AMD 395) | `CostTier.LOCAL` → Ollama (`qwen2-math:1.5b/7b`·`qwen2.5:3b/7b`·`qwen3-vl:8b`) | **없음 — 이미 일치** |
| **MAIN** (CLOUD_MID) | DeepSeek V4.1 · OpenRouter · 특정 공급사 고정 · US · fp8 | 좌석 구현 완료, 기본값 아님 (`cloud_provider="anthropic"`) | 기본값 전환 + **비용 회계 축 분리(선행)** |
| **HIGH** (CLOUD_HIGH) | Opus 5 (개발 단계는 Claude Max 구독 경유) | `claude-opus-4-7`, `api_key=` 명시 주입 | 모델 ID 교체 + **자격증명 해소 경로 확장** |

적용 범위는 **저작 경로와 학생 대면 서빙 양쪽**이다 (2026-09-21 Kiki 2회 확인:
"학생 대면까지 한 번에" → "학생대면도 오픈라우터로 전환").

## 1. MAIN 좌석은 이미 존재한다 — 새로 만들 것이 아니라 켜는 문제다

Kiki가 지정한 네 조건이 `config.py`에 **글자 그대로** 구현·동결돼 있다.

| Kiki 조건 | 코드 실체 |
|---|---|
| OpenRouter 경유 | `openrouter_base_url` · `l3/providers/openrouter.py` · `cloud_provider="openrouter"` 분기 |
| DeepSeek V4.1 | `openrouter_model_mid = "deepseek/deepseek-v4.1-flash"` (점 있는 id가 정본 — 2026-09-17 정정) |
| 특정 공급사 | `openrouter_allowed_providers = ("deepinfra",)` + `provider.only` + `allow_fallbacks=false` |
| US · fp8 | deepinfra 실측 등재: `Headquarters: US` · `Precision: FP8` · `Retention: Zero retention` |

호출 계약 3종(`provider.only` · `allow_fallbacks=false` · `data_collection="deny"`)은
옵션이 아니라 계약이며 누락 시 테스트가 RED다.

따라서 MAIN 전환에서 **새로 짤 코드는 없다**. 바꾸는 것은 `cloud_provider` 기본값
`anthropic` → `openrouter` 한 줄이고, 그것은 ARCH-55 판정문이 "기본 핀 불변"으로 못박고
`tests/backend/l3/test_cloud_provider_selector.py`가 동결한 값이므로 **코드 변경이 아니라
판정 번복**이다. 이 문서가 그 판정의 근거 문서다.

## 2. 선행 블로커 — 단가표에 공급자 축이 없다

> **[착지 2026-09-22 · ARCH-62]** 아래 §2.1~2.3이 서술하는 **현상은 해소됐다**. 단가표
> 키가 `(CostTier, CloudSeat)`로 확장됐고(`l3/router.py`), 저작 경로가 실제 좌석을
> 넘겨 비용을 기록한다. 좌석·단가가 미상이면 0원이 아니라 `None`(미측정)으로 떨어진다.
> 아래 서술은 **전환 전 상태의 기록**으로 남긴다 — 왜 이 축이 필요했는지가 설계 근거다.
> 검증: 뮤테이션 6종 전건 RED(좌석 축 제거·좌석 접기·미상 0원화·예산 판정 좌석 무시·
> 미등재 폴백·단가 드리프트). §2.4 설계 대비 **미채택 1건**: `CLOUD_HIGH`의 openrouter·
> deepseek 단가는 등재하지 않았다 — 그 좌석의 HIGH 모델 핀 자체가 미확인이라 단가 근거가
> 없다(근거 없는 값을 넣는 대신 조회가 `None`으로 떨어지게 뒀다).

### 2.1 현상

`l3/router.py`의 단가표는 **티어로만** 키가 잡혀 있다.

- `CLOUD_TOKEN_PRICE_USD_PER_1M` = `{CLOUD_MID: (3.0, 15.0), CLOUD_HIGH: (5.0, 25.0)}`
- `actual_cost_usd()`가 `CLOUD_TOKEN_PRICE_USD_PER_1M[cost]` 한 줄로 단가를 꺼낸다 —
  **어느 공급자가 응답했는지 묻지 않는다**
- `CLOUD_MIN_COST_KRW`가 이 표에서 유도되고, 그것이 `guard_cloud()`의 예산 판정 입력이다

즉 단가표는 "CLOUD_MID = Anthropic Sonnet"이라는 **암묵 가정** 위에 서 있다. 좌석을
옮기면 그 가정이 깨지는데 표는 그대로다.

### 2.2 정량 — 24.4배 과대 계상

라우터의 가정 토큰 상수(입력 74 · 출력 358 · 환율 1,540원/USD)로 계산한 1회 호출 비용:

| 구성 | 단가 (USD/1M in·out) | 1회 비용 |
|---|---|---|
| 현행 MID `claude-sonnet-4-6` | $3.00 / $15.00 | **8.612원** |
| 목표 MID DeepSeek v4.1@deepinfra | $0.20 / $0.60 | **0.354원** |
| 현행 HIGH `claude-opus-4-7` | $5.00 / $25.00 | 14.353원 |
| 목표 HIGH `claude-opus-5` | $5.00 / $25.00 | 14.353원 (**동일**) |

MID 과대 계상 **24.4배**. `guard_cloud()`의 예산 판정이 그대로 왜곡된다:

| 구독 | 일일 한도 | 표가 말하는 호출 횟수 | 실제 가능 횟수 |
|---|---|---|---|
| basic | 500원 | 58회 | **1,414회** |
| premium | 2,000원 | 232회 | **5,656회** |

### 2.3 왜 이것이 "선행"인가

과대 계상의 결과는 `budget_krw < cloud_min_cost(desired)` 분기를 통한 **불필요한 LOCAL
강등**이다. 그리고 이 실패는 **무증상**이다 — 강등된 응답도 200이고, 학생은 더 약한 모델의
답을 받았다는 사실을 모르며, 로그에도 "예산 부족"이라는 *정상* 판정으로 남는다.
CLAUDE.md 「작동 신호 없는 알고리즘 부착 금지」가 겨냥하는 형태 그대로다.

그래서 **Phase A를 Phase B보다 먼저 착지시킨다.** 순서를 바꾸면 회계가 거짓이 된 채로 돈다.

### 2.4 설계

- 단가표 키를 `CostTier` → `(CostTier, CloudSeat)`로 확장. `CloudSeat`는 기존
  `cloud_provider` 리터럴(`anthropic`|`openrouter`|`deepseek`)을 재사용한다(새 enum 금지 —
  이중 진실 원천이 된다).
- `actual_cost_usd()`는 **실제 응답한 좌석**을 읽는다. EOS-118이 이미 `cloud_seat` 관측
  블록을 붙여 뒀으므로 값의 출처는 있다.
- 좌석이 미상이면 **0원으로 접지 않는다** — `None`을 돌려주고 리포트가 "미측정"으로 센다
  (CLAUDE.md 「모른다 ≠ 아니다」).
- 변별력 검증: MID를 openrouter로 두고 1회 호출 → 기록된 원가가 8.6원이 아니라 0.35원.
  뮤테이션 — 좌석 축을 지우면 이 테스트가 RED여야 한다.

## 3. 가용성 리스크와 그 해소 — 학생 대면 전환의 핵심

### 3.1 리스크의 실체

`openrouter_allowed_providers`가 1곳이고 `allow_fallbacks=false`이므로, **그 공급사가
죽으면 호출이 실패한다**. 이것은 버그가 아니라 의도된 선택이다(config 주석: "채택 미판정이라
조용한 품질 변동보다 명확한 실패가 낫다"). 저작 경로에서는 옳은 선택이다 — 실패하면 사람이 본다.

학생 대면에서는 그 계산이 뒤집힌다. 실패가 **학생 화면의 오류**가 되기 때문이다.
그리고 실측된 실패율이 작지 않다:

> 2026-09-17~18 4회차 실측: `429 engine_overloaded` 실패율 **30% → 15% → 0%**
> 실패 원인 전건 `limit_source=upstream_provider_shared_pool` · `is_byok=false` (공유 풀)
> p95 지연이 212초까지 관측

이것이 `G-arch56-availability-trigger`가 학생 대면 전환을 막아 온 근거다.

### 3.2 해소 — 두 종류의 fallback을 구별한다

핵심은 **금지된 fallback과 필요한 fallback이 다른 것**이라는 점이다.

| | OpenRouter의 `allow_fallbacks` | 우리 라우터의 좌석 failover |
|---|---|---|
| 누가 고르나 | OpenRouter가 임의로 | 우리가 명시적으로 |
| 정밀도 | fp8/fp4/unknown이 섞인다 | 좌석마다 고정 |
| 관측 | 어느 공급사가 답했는지 모를 수 있다 | 회차마다 기록·계수 |
| 판정 | **금지 유지** (품질 비교가 무효화됨) | **신설** |

즉 `allow_fallbacks=false`는 그대로 두고, **그 위에** 우리 좌석 단위의 failover를 얹는다:

```
학생 대면 CLOUD_MID 요청
  → openrouter(deepinfra/fp8) 시도
  → 429/5xx/타임아웃이면 → anthropic(claude-sonnet-4-6)로 1회 재시도
  → 그것도 실패하면 → LOCAL 강등 (기존 경로)
  ※ 매 회차 seat_attempted · seat_served · failover_reason을 기록
```

이 설계가 성립하면 **가용성 축이 학생 대면 전환의 차단 사유가 아니게 된다** — 공유 풀이
막혀도 학생은 답을 받고, 우리는 그 비율을 숫자로 본다. ARCH-56이 재려던 "공유 풀 대기열
통계"는 그때 *차단 판정의 입력*이 아니라 *운영 지표*가 된다.

### 3.3 작동 신호 (CLAUDE.md 「작동한 비율」)

failover는 붙였다고 작동하는 것이 아니므로 리포트가 다음을 말해야 한다.

- `seat_primary_success_rate` — openrouter가 1차로 성공한 비율
- `seat_failover_rate` — anthropic으로 넘어간 비율 + 사유 분포(429 / 5xx / timeout)
- `seat_local_degrade_rate` — 둘 다 실패해 LOCAL로 내려간 비율
- `seat_not_measured` — 좌석 미상 (0으로 접지 않는다)

`seat_failover_rate`가 상시 높으면 그것은 "보호가 작동 중"이 아니라 **1차 좌석이 부적합**
하다는 신호이며, 그때 `openrouter_allowed_providers`에 **정밀도가 같은** 곳(`baseten`,
이미 `PROVIDER_*` 표 등재·`Region: US`·`baseten/fp8`)을 추가해 이중화한다. 정밀도가 다른
곳을 넣는 것은 이중화가 아니라 오염이다.

## 4. HIGH 좌석 — Opus 5 + 구독 자격증명

### 4.1 모델 교체는 단순하다

- 정확한 id는 `claude-opus-5` — **날짜 접미사 없음**. 컨텍스트 1M.
- 가격 $5/$25로 현행 핀 `claude-opus-4-7`과 **동일** → 단가표 값 변경 불요.

### 4.2 동작 차이가 비용 상수에 파급된다

Opus 5는 thinking이 **기본 ON(adaptive)** 이다 — `thinking`을 생략하면 adaptive로 돈다.
현행 핀 4.7은 생략 시 thinking 없이 돈다. 즉 **같은 요청에 출력 토큰이 늘 수 있다.**

파급: `_EST_ASSUMED_OUTPUT_TOKENS = 358`(2026-07-14 라이브 p50, n=32)은 4.7 기준 실측이라
Opus 5 전환 후 **과소**가 될 수 있다. 교체 후 `ops.cost_report`의 `suggested_est_*`로
재대입한다(기존 튜닝 절차 그대로 · 코드 변경은 그 두 상수뿐).

부수: `budget_tokens`는 Opus 5에서 **제거**돼 400을 낸다. 현행 코드가 그것을 보내지 않는지
확인하는 것이 교체 acceptance에 들어간다.

### 4.3 자격증명 경로 — 현재 코드로는 구독을 쓸 수 없다

Kiki 판단(2026-09-21): **개발 단계에서는 Claude Max 요금제 구독으로 Opus 5를 쓴다**
(이전 세션에서 사용 가능함을 검토 완료). 이 문서는 그 판단을 전제로 설계한다.

그런데 현재 코드는 그 경로를 탈 수 없다:

> `l3/providers/anthropic.py:265` — `AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())`

API 키를 **명시적으로** 넘긴다. Anthropic SDK의 자격증명 해소 순서는
`ANTHROPIC_API_KEY` → `ANTHROPIC_AUTH_TOKEN` → OAuth 프로파일 → WIF → 기본 프로파일인데,
**명시 `api_key=`는 그 사슬 전체를 가린다.** 구독·OAuth 경로를 쓰려면 키가 비었을 때
인자를 아예 생략해 SDK가 사슬을 타게 해야 한다.

설계:

- `anthropic_api_key`가 비어 있고 `ANTHROPIC_AUTH_TOKEN` 또는 OAuth 프로파일이 있으면
  `AsyncAnthropic()`을 **인자 없이** 생성한다.
- 어느 경로로 인증됐는지 `/status`와 회차 리포트가 말한다(`auth_source: api_key | auth_token
  | oauth_profile | none`). **조용한 폴백 금지** — 경로가 바뀐 것을 사람이 봐야 한다.
- 셋 다 없으면 지금처럼 명확한 오류. `cloud_configured=False`.
- 변별력 검증: 키만 있는 환경 → `api_key`, 토큰만 있는 환경 → `auth_token`, 둘 다 없는
  환경 → 오류. 세 상태가 서로 다른 값을 내야 한다(세 환경 전부에서 테스트).

### 4.4 개발 단계 한정 — 만료 지점을 동반한다

구독 경유는 **개발 단계 한정 승인**이다. 만료·재확인 지점 없는 유예는 CLAUDE.md가 금지하므로
프로덕션 전환 시점에 과금 경로를 재판정하는 게이트를 함께 등재한다
(`G-opus5-billing-path-prod-recheck`).

## 5. 단계 계획

| Phase | 내용 | 판정 필요 | 선행 |
|---|---|---|---|
| **A** | 단가표 공급자 축 분리 + 좌석별 원가 기록 | 불요 | — |
| **B1** | 좌석 failover (openrouter → anthropic → LOCAL) + 작동 신호 4종 | 불요 | A |
| **B2** | `cloud_provider` 기본값 → `openrouter` (저작 경로) | **Kiki 판정** | A |
| **B3** | 학생 대면(`app.py`) 좌석을 팩토리 경유로 전환 | **Kiki 판정 + 게이트** | B1·B2 |
| **C** | HIGH → `claude-opus-5` + 자격증명 사슬 복원 + est 상수 재보정 | 개발단계 승인(완료) | A |

Phase B3은 `test_student_facing_app_does_not_use_the_selector`를 푸는 일이며, 그 가드의
docstring이 순서를 못박는다 — "ARCH-56을 끝내고 → 게이트를 clear하고 → 그 근거로 이 테스트를
고친다. 반대 순서는 게이트를 우회하는 것이다." 이 문서의 §3.2 failover 설계는 ARCH-56이
재려던 리스크를 *구조적으로 해소*하므로, ARCH-56의 acceptance는 "차단 판정"에서 "운영 지표
기준선"으로 재정의하는 것이 맞다. 그 재정의 자체가 Kiki 판정 사안이다.

## 6. 열린 항목

1. `openrouter_model_high` = `deepseek/deepseek-v4-pro`는 **미확인 핀**이다(MID가 `v4.1`로
   정정된 만큼 같은 오류일 수 있다). 이 설계에서 HIGH는 Anthropic이므로 당장 쓰이지 않으나,
   좌석 failover 표에 HIGH 행을 채울 때 `--search`로 확정해야 한다.
2. BYOK 미채택 상태(2026-09-18 Kiki 판단)가 유지되는 한 공유 풀 대기열은 남는다 —
   §3.2 failover가 그 영향을 흡수하지만, 상시 failover가 관측되면 BYOK 재검토 신호다.
3. `_EST_ASSUMED_*` 재보정은 MID·HIGH 양쪽이 동시에 바뀌므로 **좌석별로 따로** 재야 한다.
