# OPS-107 — 저작·배치 경로의 `provider.generate` 직접 호출 전수와 판정

> **판정 기준**: 브랜치 `claude/eloquent-bohr-1da6mq`에 `origin/main` `b165e53b`(CONST-03 P1, #1464)를 병합한 작업 사본에서 AST 스캔·테스트를 돌렸다. 이 문서의 수치는 **브랜치 기준**이며, 이 PR이 머지되기 전까지 main에는 없다. (OPS-105 `2b324cdc`(#1452)가 그 병합에 포함돼 있다 — §3-1.)
> **실행 일자**: 2026-10-05 · Python 3.12.3.
> **재현**: `tests/backend/l3/test_authoring_traffic_surface_inventory.py`의 `_scan_direct_calls()`가 이 문서의 표를 코드로 다시 만든다.

## 0. 용어 풀이 (초보자용)

| 용어 | 뜻 |
|---|---|
| **파이프라인(`l3.pipeline.generate`)** | LLM을 부르는 표준 길. 라우터 결정·캐시·결과 검증·비용 기록을 한 번에 한다. 학생 대면 코드는 전부 이 길을 탄다 |
| **우회** | 파이프라인을 거치지 않고 `provider.generate(...)`를 직접 부르는 것 |
| **저작 경로** | 학생이 아니라 우리가 오프라인으로 문항·설명을 대량 생성하는 배치 |
| **`traffic_surface` 표지** | 관측 이벤트에 붙는 꼬리표. `serving`(학생 대면)·`authoring`(저작)·`probe`(측정) 중 하나이며 OPS-105가 정한 어휘다 |
| **게이트②** | 학생 대면 루프당 비용·로컬 비율을 재는 합격 기준. 저작 배치가 섞이면 수치가 위장된다 |

## 1. 정정 — OPS-84 ①의 "마지막 우회 1건"은 사실이 아니었다 (acceptance ③)

OPS-84 ①은 `rephrase.py`를 "라우터 결과를 손으로 재조립해 provider를 직접 부르는 **마지막 우회 1건**"이라 적었다. 실측은 다르다.

- 패키지 전체 AST 스캔(수신자가 `provider`·`self._provider`인 `.generate(`)에서 **12개 함수·16개 호출 자리**가 나온다. 그중 파이프라인 코어(`l3/pipeline.py`, 호출 4분기)를 빼면 **11개 함수**가 파이프라인 밖에서 provider를 직접 부른다.
- 이 태스크 등재 시점의 후보 6곳에 **`l3/pedagogy/analogy_generator.py`가 빠져 있었다**(설명 생성기와 같은 형태). 후보 목록 자체도 불완전했다.

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
| 6 | `l3/pregenerate/prewarmer.py` `_prewarm_with_decision` | 런타임 캐시 쓰기 주체 | 2 | **seed**(있을 때만) | **없음**(§4-3) |
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
| 3 `explanation_generator` | **의도적 제외** | 인자는 `temperature`뿐이라 기술적으로 전환 가능하다. 그러나 캐시를 끄는 `_NoStoreCache` 결선과 표지 래퍼가 필요하고(OPS-84 ① 형태), 얻는 것은 이미 갖고 있는 비용·trace 기록의 중복이다 |
| 4 `analogy_generator` | **의도적 제외** | 3과 같다 |
| 5 `cross_verify` | **의도적 제외** | 한 번 라우팅한 `decision`을 관점별 호출에 재사용한다. 파이프라인은 호출마다 라우팅하므로 결정이 달라질 수 있어 관점 간 비교 조건이 흔들린다(**읽어서 그렇게 보인다** — 실측하지 않았다) |
| 6 `prewarmer` | **의도적 제외 — 제외가 이 모듈의 정의** | 이 모듈은 파이프라인이 읽는 캐시 키(`cache_key_for(prompt, system, decision)`)에 **미리 적재**하는 쓰기 주체다. `pipeline.generate`를 거치면 캐시 적중 때 생성이 일어나지 않아 목적이 사라진다 |
| 7~11 하네스 | **의도적 제외** | 일회성 측정·진단 CLI다. 서빙 표본과 같은 스트림에 낼 이벤트가 없다(trace 경로 0) |

**캐시 의미 판정(OPS-84 ② 형식)**: 전환하는 자리가 0건이므로 새로 판정할 캐시 의미가 없다. 다양성 목적 경로를 파이프라인에 태우는 경우의 규칙(캐시를 끄고 근거를 실측으로 남긴다)은 OPS-84의 `rephrase.py` 판정이 그대로 소유한다. 태스크 acceptance ②의 "전환 자리는 `traffic_surface=authoring` 표지를 싣는다"는 전환한 자리에 대한 문장이며, 전환이 0건이므로 이 태스크가 새로 싣는 표지는 없다.

### 3-1. 표지 문제 — 이 세션이 한 번 잘못 짚고 철회한 곳

**처음 판단(철회)**: 위 표의 1~5번이 `l3_routing` 이벤트를 `traffic_surface` 표지 없이 낸다는 것을 보고, "표지 없는 이벤트는 서빙 표본으로 세므로 게이트②가 위장된다 — 5곳을 모두 `authoring`으로 표지해야 한다"고 판단해 공용 래퍼를 만들어 5곳에 붙였다(16건 테스트·뮤테이션 10종 전건 검출까지 마쳤다).

**철회 사유 — 병합 때 드러난 `OPS-105`(main `2b324cdc`, #1452)의 기존 판정**: 이 세션이 쓰던 브랜치는 `OPS-105`가 착지하기 전의 main 위에 있었다. 병합하자 `OPS-105`가 이미 같은 문제를 일반화해 놓았고(`TrafficSurface{serving, authoring, probe}`·`SurfaceTaggingTraceSink`·`cost_report`의 표면 분리), 그 docstring이 **이 5곳을 일부러 표지하지 않는다**고 적고 있었다.

> 싣지 않는 지점(의도적 미표기): 비동기 큐 워커(`l3/queue/tasks.py`)와 자체 `LangfuseSink`를 만드는 오프라인 생성기들(`cross_verify`·`multi_solution`·`pedagogy/*`·`llm_generator`) — 표면을 추측해 채우면 틀린 표지가 '관측'으로 위장되므로 비워 두고 미표기 비율로 드러낸다.

그리고 `cost_report`는 미표기 이벤트를 **숨기지 않고** 건수와 표지 적용률(`surface_labeled_rate`)로 보고하며, `--strict-surface`로 서빙 표본에서 분리할 수 있다. 즉 "표지 누락이 게이트②를 조용히 위장한다"는 이 세션의 진단은 **이미 설계로 다뤄진 사안**이었다.

**호출부 추적으로 확인한 사실** (저작이라는 단정이 사실인지 — 이 세션이 처음에 하지 않은 확인):

| 생성기 | 호출부 | 오프라인 확정? |
|---|---|---|
| `llm_generator` | `harness/problem_corpus_accumulate.py`(배치) | 코드상 유일한 호출부가 배치다 |
| `multi_solution` | 자기 모듈의 배치 러너(`generate_candidates` 호출 1곳) | 코드상 유일한 호출부가 배치다 |
| `explanation_generator` | `l4/pedagogy/age_band_explanation.py`의 `explain_concept_at_age_band(session, code, band)` | **확정 불가** — DB 세션을 받는 async 함수이고 docstring이 "이미 실행 중인 이벤트 루프(FastAPI 요청 핸들러 등) 안"에서의 호출을 명시한다. 이 저장소에서 그 함수의 호출부는 찾지 못했다(미배선) |
| `analogy_generator` | `l3/pedagogy/example_generator.py`가 엔진으로 사용 | 확정하지 못함(그 모듈의 호출부도 찾지 못함) |
| `cross_verify` | `harness/residue_*` 평가·배틀 스크립트 | 하네스 호출부는 확인, 그 외 경로는 확인하지 않음 |

**왜 철회가 맞는가**: 3번(`explanation_generator`)처럼 **서빙 호출 가능성이 열려 있는 자리를 `authoring`으로 단정해 표지하면**, 그 호출이 게이트② 표본에서 빠져 **실제 서빙 비용을 가린다** — 표지 누락의 위장보다 방향이 반대인 위장이다. `OPS-105`가 경계한 것이 바로 이것이다. 또 이 태스크의 acceptance가 요구한 것은 "전환한 자리의 표지"뿐이었고 전환은 0건이었다 — 5곳 표지는 요구 범위를 넘은 변경이었다.

**남기는 것(Kiki 판단 입력)**: 위 표에서 호출부가 **배치뿐으로 확인된 자리**(`llm_generator`·`multi_solution`)에 한해 `SurfaceTaggingTraceSink(…, TrafficSurface.AUTHORING)`를 다는 것은 추측이 아니다. 그러나 이는 `OPS-105`가 Kiki 확인을 요청해 둔 "미표기 기본 처리" 판단과 같은 결의 판단이라 이 세션이 앞질러 정하지 않았다 — 적용률을 올리는 별건으로 남긴다(별도 태스크를 등재하지는 않았다: 표지를 달 가치는 `surface_labeled_rate`의 라이브 실측을 본 뒤 정하는 편이 낫다).

## 4. 발견 — 판정 범위 밖으로 남긴 것

1. **스캔 범위의 한계**: 수신자 이름이 `provider`·`self._provider`인 호출만 셌다. 이름이 다른 호출(`generator.generate`·`engine.generate`·`deps.generate`·`cloud.generate`·`model.generate`·`client.generate`·`resolved.generate`·`llm.generate`·`self._seam.generate`)은 **이 스캔의 바깥**이다. 그중 학생 대면 좌석 쪽(`l4/misconception/judge.py`·`l4/polya/engine.py`·`harness/wh1_*`)은 OPS-36이 소유한다고 알고 있으나, 이 세션은 각각이 파이프라인을 경유하는지 **열어서 확인하지 않았다**.
2. **`harness/concept_content_review_batch.py`는 `Router`를 거치지 않고 `RoutingDecision`을 손으로 조립한다**(`_assess_one`). CLAUDE.md의 "LLM 호출은 항상 라우터 경유" 원칙과 맞는지는 CLI가 모델 티어를 인자로 고정하는 평가 하네스라는 점에서 의도일 수 있으나 확인하지 못했다 → `OPS-110`.
   - **해소 (OPS-110 · 2026-10-06)**: **의도다 — Router 경유로 바꾸지 않는다.** 이 배치는 `--model`이 지정한 *한 모델*의 판정력(주입 결함 검출률·Wilson 상한)을 재므로, 표본마다 모델을 고를 수 있는 `Router.route()`를 끼우면 수치가 섞인 모집단의 것이 된다. 비용 통제·학생 대면 관측이라는 원칙의 취지에도 해당하지 않는다(티어 표 전부 로컬, provider는 `OllamaProvider`만). 근거는 `_assess_one` docstring이 소유하고, 클라우드로 새지 않는 경계는 `tests/backend/harness/test_concept_content_review_batch_router_intent.py`(뮤테이션 7종 전건 RED)가 동결한다. 분류(`measurement-harness`)는 그대로 유지. 정직한 한계: 이 호출은 Langfuse에 남지 않는다(JSONL 감사 리포트가 레코드별 모델·지연·판정을 대신 남긴다).
3. **`prewarmer`는 `l3_routing` 이벤트를 내지 않는다** — pregenerate 패키지에 `TraceSink` 사용이 0건임을 코드로 확인했다. 비용은 `provenance_bridge`가 별도로 기록한다. 사전생성 호출이 Langfuse에 남지 않는 것이 의도인지는 확인하지 못했다 → `OPS-109`.

문서 속 계획은 백로그를 대신하지 못하므로 2·3은 태스크로 추적한다.

## 5. 실행하지 못한 것 · 남은 불확실성

- **라이브 데이터는 없다.** 이 환경에는 Langfuse·Ollama가 없다. 저작 생성기 이벤트가 라이브에서 실제로 얼마나 서빙 표본에 섞이는지(= `surface_labeled_rate`)는 측정하지 못했다.
- 판정 1~5의 "전환 비용" 서술은 코드를 **읽고** 낸 것이다. 전환을 시도해 보지 않았다. `cross_verify`의 "결정 재사용이 관점 비교를 보장한다"도 읽어서 그렇게 보이는 것이다.
- 호출부 추적(§3-1)은 이 저장소의 정적 검색이다. 이 저장소 밖(운영 스크립트·런북 명령)에서의 호출은 보지 못했다.
- **이 문서의 첫 판은 잘못된 결론이었다**(5곳 표지 부착). 원인은 병합 전 main을 기준으로 삼은 것과, "저작 배치"라는 가정을 호출부로 확인하지 않은 것이다. 결론 철회를 문서에 남기는 이유는 같은 가정이 다시 반복되지 않게 하려는 것이다.

## 6. 산출물

- `tests/backend/l3/test_authoring_traffic_surface_inventory.py` — `provider.generate` 직접 호출 전수·호출 수 동결(3건)
- 이 문서
- 소스 변경 0건(표지 부착은 철회 — §3-1)
- 대장: `OPS-109`·`OPS-110` 등재, `OPS-84` 정정 항
