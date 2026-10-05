# OPS-107 — 저작·배치 경로의 `provider.generate` 직접 호출 전수와 판정

> **판정 기준**: 브랜치 `claude/eloquent-bohr-1da6mq`(main `381ec106` 기반 + 미머지 커밋 위) 작업 사본에서 AST 스캔·테스트를 돌렸다. 이 문서의 수치는 **브랜치 기준**이며, 이 PR이 머지되기 전까지 main에는 없다. (이 문서를 쓰는 시점의 `origin/main`은 이 세션에서 다시 fetch하지 못했다 — shallow 클론 `fatal: Needed a single revision`.)
> **실행 일자**: 2026-10-05 · Python 3.12.3.
> **재현**: `tests/backend/l3/test_authoring_traffic_surface_inventory.py`의 `_scan_direct_calls()`가 이 문서의 표를 코드로 다시 만든다.

## 0. 용어 풀이 (초보자용)

| 용어 | 뜻 |
|---|---|
| **파이프라인(`l3.pipeline.generate`)** | LLM을 부르는 표준 길. 라우터 결정·캐시·결과 검증·비용 기록을 한 번에 한다. 학생 대면 코드는 전부 이 길을 탄다 |
| **우회** | 파이프라인을 거치지 않고 `provider.generate(...)`를 직접 부르는 것 |
| **저작 경로** | 학생이 아니라 우리가 오프라인으로 문항·설명을 대량 생성하는 배치 |
| **`traffic_surface` 표지** | 관측 이벤트에 붙는 꼬리표. `authoring`이면 "저작 배치가 낸 이벤트"라는 뜻 |
| **게이트②** | 학생 대면 루프당 비용·로컬 비율을 재는 합격 기준. 저작 배치가 섞이면 수치가 위장된다 |

## 1. 정정 — OPS-84 ①의 "마지막 우회 1건"은 사실이 아니었다 (acceptance ③)

OPS-84 ①은 `rephrase.py`를 "라우터 결과를 손으로 재조립해 provider를 직접 부르는 **마지막 우회 1건**"이라 적었다. 실측은 다르다.

- 패키지 전체 AST 스캔(수신자가 `provider`·`self._provider`인 `.generate(`)에서 **12개 함수·16개 호출 자리**가 나온다. 그중 파이프라인 코어(`l3/pipeline.py`, 호출 4분기)를 빼면 **11개 함수**가 파이프라인 밖에서 provider를 직접 부른다.
- 이 태스크 등재 시점의 후보 6곳에 **`l3/pedagogy/analogy_generator.py`가 빠져 있었다**(설명 생성기와 같은 형태). 후보 목록 자체도 불완전했다.
- 더 중요한 발견은 우회 *자체*가 아니라 **관측 표지 누락**이다(§3).

이 문서가 그 정정의 소유자다(태스크 acceptance ③). OPS-84의 해당 서술에는 정정 항을 덧붙였다.

## 2. 전수표 (스캔 범위: 수신자 이름이 `provider`·`self._provider`)

| # | 자리(함수) | 분류 | 호출 수 | 싣는 인자 | trace 경로 |
|---|---|---|---|---|---|
| 0 | `l3/pipeline.py` `generate` | 파이프라인 코어 — 우회가 아니라 그 길 | 4 | images·temperature 분기 | 파이프라인 자신 |
| 1 | `l3/equivalent/llm_generator.py` `_invoke` | 저작 생성기 | 1 | **temperature·json_schema·seed·top_p** | 자체 `_record_trace` |
| 2 | `l3/multi_solution.py` `generate_candidates` | 저작 생성기 | 1 | temperature·**json_schema** | 모듈 함수 `_record_trace` |
| 3 | `l3/pedagogy/explanation_generator.py` `agenerate_draft` | 저작 생성기 | 1 | temperature | 자체 `_record_trace` |
| 4 | `l3/pedagogy/analogy_generator.py` `_invoke` | 저작 생성기(**목록 누락분**) | 1 | temperature | 자체 `_record_trace` |
| 5 | `l3/cross_verify.py` `_run_perspective` | 교차검증 | 1 | (없음) | 자체 `_record_trace` |
| 6 | `l3/pregenerate/prewarmer.py` `_prewarm_with_decision` | 런타임 캐시 쓰기 주체 | 2 | **seed**(있을 때만) | **없음**(§4-③) |
| 7 | `harness/concept_content_review_batch.py` `_assess_one` | 측정·평가 하네스 | 1 | json_schema | 없음 |
| 8 | `harness/deepseek_live_probe.py` `_run` | 측정·진단 | 1 | — | 없음 |
| 9 | `harness/generation_seed_replay_probe.py` `probe_one` | 측정·진단 | 1 | — | 없음 |
| 10 | `harness/provider_accuracy_battle.py` `_one` | 측정·진단 | 1 | — | 없음 |
| 11 | `harness/quality_tier_moe_accuracy_battle.py` `_evaluate_one` | 측정·진단 | 1 | — | 없음 |

## 3. 판정 (acceptance ②) — 전환할 것인가, 의도적으로 제외할 것인가

**원칙**: 파이프라인이 주는 것은 ①라우터 결정 ②런타임 캐시 ③shadow 검증 ④런타임 LOCAL 강등(ARCH-69, 학생 대면 한정) ⑤비용·trace 기록이다. 저작 경로에서 ②는 다양성을 죽이고(OPS-84 ② — 같은 프롬프트의 재사용), ③④는 학생 대면 안전장치라 의미가 없으며, ⑤는 이미 각 생성기가 같은 형태(`actual_cost_krw` + `langfuse_fields`)로 갖고 있다. 그래서 **전환의 이득은 작고, 전환의 비용은 자리마다 다르다**.

| # | 판정 | 근거 |
|---|---|---|
| 1 `llm_generator` | **의도적 제외** | 파이프라인 시그니처는 `images`·`temperature`만 받는다. 이 자리는 `json_schema`(LOCAL 제약 디코딩)·`seed`(생성 재현 좌표, EOS-73)·`top_p`(EOS-121)를 싣는다. 전환하려면 학생 대면 코어(`pipeline.generate`)의 시그니처를 늘려야 하고, 그 변경의 영향은 서빙 전 경로에 닿는다 — 이 태스크 범위 밖이며 이득이 비용을 정당화하지 않는다 |
| 2 `multi_solution` | **의도적 제외** | 같은 이유(`json_schema`) |
| 3 `explanation_generator` | **의도적 제외** | 인자는 `temperature`뿐이라 기술적으로 전환 가능하다. 그러나 캐시를 끄는 `_NoStoreCache` 결선과 저작 표지 래퍼가 필요하고(OPS-84 ① 형태), 얻는 것은 이미 갖고 있는 비용·trace 기록의 중복이다 |
| 4 `analogy_generator` | **의도적 제외** | 3과 같다 |
| 5 `cross_verify` | **의도적 제외** | 한 번 라우팅한 `decision`을 관점별 호출에 재사용한다. 파이프라인은 호출마다 라우팅하므로 결정이 달라질 수 있어 관점 간 비교 조건이 흔들린다(**읽어서 그렇게 보인다** — 실측하지 않았다) |
| 6 `prewarmer` | **의도적 제외 — 제외가 이 모듈의 정의** | 이 모듈은 파이프라인이 읽는 캐시 키(`cache_key_for(prompt, system, decision)`)에 **미리 적재**하는 쓰기 주체다. `pipeline.generate`를 거치면 캐시 적중 때 생성이 일어나지 않아 목적이 사라진다 |
| 7~11 하네스 | **의도적 제외** | 일회성 측정·진단 CLI다. 서빙 표본과 같은 스트림에 낼 이벤트가 없다(trace 경로 0) |

**캐시 의미 판정(OPS-84 ② 형식)**: 전환하는 자리가 0건이므로 새로 판정할 캐시 의미가 없다. 다양성 목적 경로를 파이프라인에 태우는 경우의 규칙(캐시를 끄고 근거를 실측으로 남긴다)은 OPS-84의 `rephrase.py` 판정이 그대로 소유한다.

**그런데 "제외"가 면죄부는 아니다 — 표지**: 전환하지 않아도 **저작 경로가 낸 `l3_routing` 이벤트에는 `traffic_surface="authoring"` 표지가 붙어야 한다**(§3-1).

### 3-1. 실제 결함 — 저작 생성기 5곳이 표지 없이 이벤트를 냈다

`ops/cost_report.aggregate_l3_events`는 `traffic_surface == "authoring"`인 이벤트만 게이트② 표본에서 빼고, **표지가 없는 이벤트는 서빙 표본으로 센다**(구 이벤트 하위호환 — 코드 주석에 명시). 그런데 위 표의 1~5번은 `langfuse_fields(...)`로 만든 `l3_routing` 이벤트를 표지 없이 기록했다(OPS-84 ③은 `rephrase.py` 한 곳에만 표지를 걸었다). 이 저작 배치가 라이브로 돌아 같은 Langfuse 스트림에 쓰면 게이트②의 로컬 비율·토큰 p50이 위장된다.

**실측**(`TestUntaggedAuthoringEventsPolluteTheServingSample`): 서빙 2건(로컬 1·클라우드 1) 위에 로컬 저작 이벤트 8건을 얹으면, 표지가 있을 때 로컬 비율 **0.50**, 표지가 없을 때 **0.90**이다. 이 수치는 합성 입력으로 낸 **리포트 코드의 반응**이지 라이브 트래픽의 실제 오염량이 아니다 — 실제 오염량은 §5에 적었듯 측정하지 못했다.

**조치(이 PR)**: `l3/interfaces.py`에 `AuthoringTraceSink`·`AUTHORING_TRAFFIC_SURFACE`를 공용으로 올리고(신규 모듈 없음 — 기존 `RecordingTraceSink` 옆), `rephrase.py`가 쓰던 지역 정의를 그쪽으로 옮겼으며, 1~5번의 `trace.record(...)`를 모두 이 래퍼로 감쌌다. 동결 테스트가 "저작 모듈의 모든 `trace.record`는 래퍼를 통한다"를 AST로 단언한다.

## 4. 발견 — 판정 범위 밖으로 남긴 것

1. **스캔 범위의 한계**: 수신자 이름이 `provider`·`self._provider`인 호출만 셌다. 이름이 다른 호출(`generator.generate`·`engine.generate`·`deps.generate`·`cloud.generate`·`model.generate`·`client.generate`·`resolved.generate`·`llm.generate`·`self._seam.generate`)은 **이 스캔의 바깥**이다. 그중 학생 대면 좌석 쪽(`l4/misconception/judge.py`·`l4/polya/engine.py`·`harness/wh1_*`)은 OPS-36이 소유한다고 알고 있으나, 이 세션은 각각이 파이프라인을 경유하는지 **열어서 확인하지 않았다**. `ops/live_preflight.py`의 `cloud.generate`(클라우드 스모크)·`ops/cost_probe.py`의 `deps.generate`는 측정 도구로 보이나 확인하지 않았다.
2. **`harness/concept_content_review_batch.py`는 `Router`를 거치지 않고 `RoutingDecision`을 손으로 조립한다**(`_assess_one`). CLAUDE.md의 "LLM 호출은 항상 라우터 경유" 원칙과 맞는지는 CLI가 모델 티어를 인자로 고정하는 평가 하네스라는 점에서 의도일 수 있으나, 이 세션은 의도 여부를 확인하지 못했다.
3. **`prewarmer`는 `l3_routing` 이벤트를 내지 않는다** — pregenerate 패키지에 `TraceSink` 사용이 0건임을 코드로 확인했다. 비용은 `provenance_bridge`가 별도로 기록한다. 그러나 사전생성 호출이 Langfuse에 남지 않는 것이 의도인지는 확인하지 못했다(표지 문제는 아니다 — 이벤트가 없으니 오염도 없다).

2는 `OPS-110`, 3은 `OPS-109`로 등재했다 — 문서 속 계획은 백로그를 대신하지 못하므로 추적은 태스크가 한다.

## 5. 실행하지 못한 것 · 남은 불확실성

- **라이브 오염량은 측정하지 못했다.** 이 환경에는 Langfuse·Ollama가 없다. 표지 누락이 실제로 게이트②를 얼마나 흔들었는지는 라이브 이벤트로만 알 수 있다(OPS-106이 소유한 라이브 표본 실측과 연결된다). 이 PR의 증거는 코드가 표지를 싣는다는 것과 리포트가 표지에 반응한다는 것까지다.
- 판정 1~5의 "전환 비용" 서술은 코드를 **읽고** 낸 것이다. 전환을 실제로 시도해 보지 않았다.
- 자리 5(`cross_verify`)의 "결정 재사용이 관점 비교를 보장한다"는 읽어서 그렇게 보이는 것이다.
- 이 PR은 새 자리가 판정 없이 늘어나지 않게 막는다(전수 동결). 기존 자리의 *동작*은 trace에 필드 하나가 추가된 것 외에 바꾸지 않았다.

## 6. 산출물

- `src/backend/whymath_backend/l3/interfaces.py` — `AUTHORING_TRAFFIC_SURFACE`·`AuthoringTraceSink` 공용화
- `l3/equivalent/rephrase.py`(지역 정의를 공용으로 교체) · `llm_generator.py` · `multi_solution.py` · `pedagogy/explanation_generator.py` · `pedagogy/analogy_generator.py` · `cross_verify.py`(trace.record를 표지 래퍼로 감쌈)
- `tests/backend/l3/test_authoring_traffic_surface_inventory.py` — 전수 동결·표지 AST 불변식·래퍼 의미·리포트 반응(16건)
