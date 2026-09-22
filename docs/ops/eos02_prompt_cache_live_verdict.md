# EOS-02 — 프롬프트 캐시 라이브 계측 회차 판정문

> **판정 기준: main `aa7df278`** · 회차 실행 트리도 같은 커밋(worktree `--detach`로 격리 · [B]의
> `HEAD_MATCHES_REMOTE=True`로 자가검증) · 실행 런북 = `docs/ops/eos02_prompt_cache_live_runbook.md` v2
>
> 게이트 `G-eos02-prompt-cache-live-run` · 태스크 `EOS-02-prompt-cache-live-measurement`
> 실행: 2026-09-21 Kiki · Phaiakes9 · 회차 식별자 `a7420b217c7b4cb79532fbab18469030`

---

## 1. 회차 사실 (원문 그대로)

사전검증 [B]는 8항 전건 True(`READY=True`). 그중 이번에 신설한 `SDK_HAS_CACHE_CONTROL`은
`VER=0.116.0;CC=True` — 설치본이 `0.83.0` 하한을 넘어 최상위 `cache_control`이 실재했다.

회차 결과: `attempted` 10 · `accepted` 2 · `outcome_counts`는 `accepted_stored` 2 ·
`rejected_duplicate` 8 · **`generation_failed` 0** · `EXIT=0` · `model_name` `claude-sonnet-4-6` ·
`calls_on_selected_seat` 10/10.

`prompt_cache` 블록: `state` `enabled_working` · `caching_enabled` true · `calls_total` 10 ·
`calls_with_cache_telemetry` 10 · `hit_rate` 0.8988861386138614 · `cache_read_tokens` 21789 ·
`cache_creation_tokens` 2421 · `uncached_input_tokens` 30 · `prompt_tokens_total` 24240 ·
`measured` true · `unmeasured_reason` null.

## 2. acceptance ② 판정 — **정상 작동. 예측값과 일치한다**

`calls_with_cache_telemetry`가 10이므로 1차 관문(측정 성립)을 통과했다. 적중 0%가 아니라
**전 호출이 측정됐다**.

산식이 정확히 맞아떨어진다 — 우연이 아니라는 증거다:

- `21789 + 2421 + 30 = 24240` = `prompt_tokens_total` (합 검산 일치)
- `2421 × 9 = 21789` — 1회차가 **2,421토큰 프리픽스를 쓰고**, 2~10회차가 **각각 정확히 그
  2,421토큰을 읽었다**. 9회 전건 적중이며 부분 적중이 하나도 없다.
- `hit_rate` = 21789/24240 = **0.89889**, acceptance ②가 기대한 `(n-1)/n` = 0.9와 편차 0.0011.

왜 작동했는지도 확인됐다. Sonnet 4.6의 최소 캐시 프리픽스는 **1,024토큰**인데 이 회차의
프리픽스는 2,421토큰으로 그 위다 — 런북 §7이 "아슬아슬하다"고 적었던 축(2,834자 ≈ 1,400~1,900
토큰 추정)이 실측에서 여유를 갖고 넘었다. §7의 원인 후보 ⓐ(최소 토큰 미달)·ⓑ(브레이크포인트가
가변 구간 뒤)는 **둘 다 발동하지 않았다**. ⓑ가 발동하지 않은 이유는 이 회차의 user 프롬프트가
사실상 상수였기 때문이다 — `uncached_input_tokens`가 10회 합계 **30토큰**(호출당 3토큰)이다.
이 점이 §4의 판정을 가른다.

## 3. 경제성 — 실측 토큰 × 공개 단가 (청구서 미대조)

Sonnet 4.6 = 입력 $3 / 출력 $15 per 1M(`router.CLOUD_TOKEN_PRICE_USD_PER_1M`).
캐시 단가는 읽기 0.1× · 쓰기 1.25×(5분 TTL).

| | 입력 비용 | 회차 총액 |
|---|---:|---:|
| 캐시 ON (이번 실측) | $0.015705 | $0.05549 |
| 캐시 OFF (같은 토큰 가정) | $0.072720 | $0.11250 |
| **절감** | **78.4%** | **50.7%** |

출력 토큰은 역산 2,652개로 양쪽 동일 가정이다(캐시는 입력만 건드린다).

### 3-1. 부수 발견 — 회차 비용 표시가 캐시를 모른다

리포트의 `cost_usd_total`은 **$0.03987**인데 위 실제 추정은 **$0.05549**다. **28.1% 과소**다.

원인: `router.actual_cost_usd`가 `usage.input_tokens × 입력단가`만 계산한다. 그런데 Anthropic의
`input_tokens`는 **미캐시 잔량만**이다(이 회차 30토큰). 캐시 읽기 21,789토큰과 쓰기 2,421토큰은
실제로 과금되는데 산식에 항이 없다.

파급이 비용 표시에 그치지 않는다 — 같은 산식이 `actual_cost_krw` → 예산 소진 판정에 쓰이므로,
캐시를 켠 상태에서는 **`--budget-krw` 가드가 실제 지출보다 적게 세고 있다.** 이 회차에서는
캐시가 총액을 낮췄으니 방향이 안전한 쪽이지만, 프리픽스가 재사용되지 않는 경로에서는 쓰기
1.25× 할증이 통째로 누락되어 **반대 방향**이 된다. 승계 = `OPS-88`.

## 4. acceptance ③ 판정 — **전역 기본값은 지금 켜지 않는다**

결론부터: 이 실측은 **저작 배치 경로에서 캐시가 작동함을 증명하지만, 전역 기본값 전환을
정당화하지는 않는다.** 플래그가 전역이고, 측정한 경로가 전체를 대표하지 않기 때문이다.

### 근거 — 우리는 최상위 자동 캐싱을 쓴다

`l3/providers/anthropic.py`는 `messages.create(cache_control={"type":"ephemeral"})` 형태로
**최상위 자동 캐싱**을 쓴다. 자동 캐싱은 브레이크포인트를 **마지막 캐시 가능 블록**에 놓는다.
렌더 순서가 `tools → system → messages`이므로 그 자리는 **매 호출 달라지는 user 프롬프트 뒤**다.

이번 회차에서 그것이 문제가 되지 않은 이유는 단 하나 — user 프롬프트가 거의 상수였기
때문이다(호출당 미캐시 3토큰). 같은 spec을 10번 돌린 회차의 특수성이다.

### 다른 클라우드 호출 경로는 그 특수성을 갖지 않는다

trunk 실측(`aa7df278`)으로 `AnthropicProvider`를 타는 호출부를 열거했다:

| 호출부 | system | user 프롬프트 | 자동 캐싱에서 |
|---|---|---|---|
| `l3/equivalent/llm_generator.py` (이번 측정 경로) | `_system_prompt()` 상수 | spec 유래 — 같은 spec 반복 시 거의 상수 | **적중** |
| `l3/cross_verify.py` `_run_perspective` | `perspective.system_prompt` 상수 | `perspective.render(subject)` — **문항마다 고유** | 순수 할증 |
| `l3/multi_solution.py` | `_SYSTEM_PROMPT` 모듈 상수 | `_build_user_prompt(seed)` — **seed마다 고유** | 순수 할증 |

뒤 두 경로는 "**안정 프리픽스 + 가변 꼬리**" 형태다. 그 형태에서 브레이크포인트를 꼬리 뒤에
두면 매 요청이 **다시 읽히지 않을 바이트에 쓰기 할증(1.25×)을 낸다** — 적중 0%에 비용만 25%
증가다. 서명(signature)은 `cache_creation_input_tokens`가 매 요청 잡히는데
`cache_read_input_tokens`가 공유 프리픽스를 덮지 못하는 모양이다.

즉 지금 기본값을 켜면 **한 경로에서 아끼고 두 경로에서 손해를 보며, 순증감은 트래픽 비율에
달렸다 — 그 비율은 측정된 적이 없다.** 「계측 없이 켜지 않는다」(EOS-99 ④ 승계)는 이 상태에도
그대로 적용된다.

### 그래서 무엇을 하는가 — 순서가 있다

1. **선결: 브레이크포인트를 안정 구간 끝으로 옮긴다** — 최상위 자동 캐싱 대신 `system`
   블록 마지막에 명시 브레이크포인트를 둔다. 그러면 세 경로 **전부** 공유 system 프리픽스를
   적중시키고, 가변 꼬리는 브레이크포인트 뒤라 할증을 내지 않는다. 승계 = `OPS-89`.
2. **그 다음에 기본값 전환을 재판정한다.** ①이 착지하면 "한 경로만 이득"이라는 이번 판정의
   전제가 사라진다. 재판정 지점 = `G-eos02-default-flip-recheck`.
3. **그동안 저작 배치는 지금도 켜고 쓸 수 있다** — 런북 [B]처럼 그 창에서만
   `WHYMATH_ANTHROPIC_PROMPT_CACHING=true`를 주면 된다. 기본값을 안 바꾼다는 것이 "쓰지
   말라"는 뜻이 아니다.

## 5. 정직한 한계

- **단가 곱셈이며 청구서 미대조다.** §3의 절감률은 공개 단가표 기반 추정이고 실제 청구서와
  대조하지 않았다(리포트 자신의 `cost_note`와 같은 범위).
- **n=10 · spec 1종 · 1회차다.** 적중률 89.9%는 이 조건의 값이다. spec이 여럿 도는 회차
  (EOS-121 형태)에서는 프리픽스가 spec 수만큼 갈려 적중률이 달라진다 — 측정된 적 없다.
- **5분 TTL 안에서만 성립했다.** 10회가 연속으로 돌아 간격이 5분 미만이었다. 호출 간격이
  5분을 넘으면 엔트리가 만료돼 같은 회차라도 재적중하지 않는다.
- **§4의 두 경로는 코드를 읽어 판정했다.** `cross_verify`·`multi_solution`을 실제로 캐시 ON
  상태에서 돌려 `cache_read=0`을 관측한 것은 아니다 — "읽어서 그렇게 보인다" 범위이며,
  `OPS-89`가 그 형태를 고칠 때 주입으로 확인하는 것이 정확하다.
- **카나리 경고는 이 판정과 무관하다.** 회차에 `[카나리 권고·차단력 없음] 카나리 미달:
  2/2 · Wilson 하한 42.5% < 임계 90%`가 떴는데, 이는 표본 2건에서 Wilson 하한이 구조적으로
  낮게 나오는 것이고 `canary_blocked`는 false다. 캐시 계측에 영향이 없다.
