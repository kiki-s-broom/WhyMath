# OPS-116 — 원가 계산 호출 6곳의 좌석 생략: 자리별 판정과 영향 범위

> 판정 기준: `origin/main` `42018d87`(HARN-54, #1498) 위 브랜치 `claude/funny-maxwell-j2nuyy` 기준(미머지).
> 머지 뒤 main 해시로 바뀌는 것이 아니다 — 이 문서의 코드 서술은 그 커밋의 코드를 **읽어서** 낸 것이다.

## 1. 결함

`actual_cost_usd`·`actual_cost_usd_or_none`·`actual_cost_krw`의 `seat` 기본값은 `SERVING_CLOUD_SEAT`
(`"anthropic"`)다(`l3/router.py`). 좌석을 말하지 않은 호출은 anthropic 단가표로 원가가 적힌다. ARCH-64가
학생 대면·저작 좌석 기본을 openrouter로 바꾼 뒤에도 6곳이 이 기본값에 기대어 좌석을 생략했다.
OPS-109(`prewarmer`)가 같은 결함을 고치다 전수 스캔(원가 함수 호출 13곳 중 6곳)으로 발견했다.

크기: 코드 주석이 적은 실측은 CLOUD_MID에서 openrouter 호출이 anthropic 단가로 **22.5배**(`prewarmer.py`)
혹은 **24.4배**(`pipeline.py` — 8.612원 대 0.354원)로 적힌다는 것이다. 두 주석의 수치가 다르며 이 문서는
어느 쪽이 맞는지 재측정하지 않았다(좌석 간 값이 크게 다르다는 사실만 이 PR의 테스트가 `!=`로 동결한다).

## 2. 자리별 판정 (acceptance ①)

| 자리 | 클라우드를 부르는가 | 좌석의 근거 | 처리 |
|---|---|---|---|
| `l3/cross_verify.py` `_record_trace` | 예 — 교차검증은 `task_type=verify`·비동기 요청이며 구독에 따라 클라우드 가능 | `self._provider`(`CompositeProvider.cloud_seat`) | `served_cloud_seat(self._provider)` |
| `l3/multi_solution.py` `_record_trace` | 예 — 구독이 free가 아니면 클라우드 가능(free는 라우터가 LOCAL 강제) | 호출을 받은 `provider` 인자 | `_record_trace`가 `provider`를 받는다(시그니처 변경 — 호출처 1곳) |
| `l3/pedagogy/analogy_generator.py` | 예 — 동 | `self._provider` | `served_cloud_seat(self._provider)` |
| `l3/pedagogy/explanation_generator.py` | 예 — 동 | `self._provider` | `served_cloud_seat(self._provider)` |
| `l3/queue/tasks.py` | **아니오** — QUALITY(27b)는 불변식상 LOCAL이고, provider는 `OllamaProvider`(좌석 표면 없음) | 없음 | `seat=None`(미상) 명시. LOCAL이면 좌석과 무관하게 0.0이고, 불변식이 깨져 클라우드 결정이 들어와도 anthropic으로 접지 않고 **미측정(None)** |
| `ops/live_preflight.py` | 예 — 스모크는 항상 CLOUD_MID 1콜 | 호출을 받은 `cloud`(기본 `AnthropicProvider.seat="anthropic"`) | `pipeline.served_cloud_seat(cloud)` |

`tasks.py`만 `served_cloud_seat`를 쓰지 않은 이유: 읽을 좌석 표면이 없는 provider이고 호출은 LOCAL 전용이다.
`seat=anthropic`을 꽂으면 거짓 단가가 되고, `seat=None`은 "모른다"를 정직하게 남긴다.

`served_cloud_seat(provider)`의 매개변수 타입을 `LLMProvider`에서 `object`로 넓혔다 — 이 함수는
`getattr`로 `cloud_seat`·`seat` 표면만 읽으므로, `live_preflight`의 `_CloudProvider` Protocol 같은 좁은 경계
객체도 받아야 해서다. 동작은 그대로다.

## 3. 같은 좌석을 trace에도 (acceptance ②)

`cross_verify`·`multi_solution`·`analogy_generator`·`explanation_generator`는 `langfuse_fields(cloud_seat=…)`를
싣는다("어느 단가표로 계상했나"를 같은 레코드가 말한다). LOCAL 결정은 `cloud_seat=None`이다.
`tasks.py`는 `cloud_seat`를 싣지 않는다(좌석 미상이라 실을 값이 없다). `live_preflight`의 스모크 기본 경로는
trace를 남기지 않는다(`SmokeResult`에 좌석 필드를 새로 만들지 않았다 — 범위 밖).

## 4. 집행 지점 (acceptance ③)

`tests/backend/l3/test_cost_calc_seat_explicit.py`가 패키지 전체를 AST로 스캔해 원가 함수 호출이 `seat`
키워드를 싣지 않으면 RED로 만든다(`**kwargs` 전개도 좌석 보장 불가로 위반). 검사기 자신의 변별력은 합성
소스 5건과 **실제 소스에서 결함을 복원**하는 주입으로 단언한다. 소스 뮤테이션 10종(6자리의 좌석 생략 복원 6 ·
trace `cloud_seat` 누락 1 · 미상 좌석을 anthropic으로 접기 2 · 좌석을 상수로 고정 1)은 전건 RED였고,
주입이 적용됐음(`mutated != original`)과 원복의 바이트 동일을 매번 단언했다. 이 하네스는 커밋하지 않았다
(세션 스크래치패드) — 재현하려면 위 6곳에서 `seat=` 인자를 지우면 된다.

## 5. 영향 범위 (acceptance ④ — 소급 정정하지 않는다)

**영향을 받을 수 있는 조건은 둘이 동시에 성립할 때뿐이다.** ① 그 호출이 클라우드(CLOUD_MID·CLOUD_HIGH)로
결정됐다 ② 호출을 받은 좌석이 anthropic이 아니었다. LOCAL 결정은 0원 확정이라 영향이 없다.

| 경로 | 영향 가능성 | 근거 |
|---|---|---|
| `multi_solution`·`analogy`·`explanation` | 낮음 — 기본 구독 `free`는 라우터가 LOCAL로 강제한다 | 모듈 docstring(`multi_solution.generation_routing_request`) 및 생성기 기본 `subscription="free"` |
| `cross_verify` | 구독·난이도에 따라 클라우드 가능 | 라우팅 요청이 `student_subscription=self._subscription`, `requires_reasoning=True` |
| `live_preflight` 스모크 | 기본 구성에서는 **영향 없음**(기본 provider가 `AnthropicProvider`라 anthropic 단가가 맞다). 좌석이 다른 provider를 주입한 경우만 해당 | `_default_cloud_provider`가 `AnthropicProvider` 고정 |
| `queue/tasks.py` | 없음 — LOCAL 전용 | QUALITY 불변식 |

기간: 좌석 축은 ARCH-62가 도입하고 ARCH-64가 기본 좌석을 openrouter로 컷오버했다(CLAUDE.md 스택 표 기준
2026-09). 정확한 컷오버 시각과 그 뒤 실제로 클라우드 결정이 나간 호출 수는 **미측정**이다 — 이 환경에는
Langfuse·라이브 이벤트가 없다. 이미 적재된 trace·생성 로그는 고치지 않았다.

**OPS-105와의 상호작용**: 저작 생성기 4곳(`cross_verify`·`multi_solution`·`analogy`·`explanation`)은 OPS-105가
`traffic_surface`를 **의도적 미표기**로 판정했다. `ops/cost_report`는 표지 없는 이벤트를 기본(`strict_surface=False`)에서
**서빙 표본에 남기고** 미표기로 따로 센다(`aggregate_l3_events`). 그러므로 위 클라우드 호출이 있었다면 그 `cost_krw`는
과대 계상된 채 게이트② 표본 원가를 부풀렸을 수 있다. 이번 수정은 그 값의 **정확도**를 고치지만, 표본 포함 여부(표지
판정)는 건드리지 않았다 — 그것은 OPS-105의 결정이다. 실제로 부풀었는지는 라이브 이벤트로만 알 수 있다(미측정).

## 6. 하지 않은 것

- 단가표 값 자체, `SERVING_CLOUD_SEAT` 기본값, 학생 대면 파이프라인(`l3/pipeline.py`의 `generate`)은 건드리지 않았다.
- 소급 정정 없음. `live_preflight` 보고서 스키마(`SmokeResult`)에 좌석 필드를 추가하지 않았다.
- 다음 사항은 읽어서만 판정했고 실행으로 확인하지 않았다: 위 §5의 "구독 free → LOCAL" 서술, 라이브 클라우드 호출의
  실제 좌석 표면(`CompositeProvider.cloud_seat`)이 운영 조립에서 채워지는지(`test_cloud_mid_seat_cutover.py`가
  동결한다고 주석이 말한다).
