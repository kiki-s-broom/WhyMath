# OPS-109 — 사전적재기(prewarmer)의 LLM 호출 관측 부재: 의도 판정·연결·원가 좌석 정정

> **판정 기준**: `main` `9a80f462` (2026-10-06). 아래 사실은 이 커밋의 소스를 읽고 실제 코드를 돌려
> 얻은 값이며, 미머지 브랜치의 내용은 근거로 쓰지 않았다.

## 1. 질문

`l3/pregenerate/prewarmer.py`는 provider를 *직접* 부르면서 `l3_routing` trace 이벤트를 내지 않는다
(pregenerate 패키지에 `TraceSink` 사용 0건 — OPS-107 §4-3). 사전생성 호출이 Langfuse·게이트② 관측에
남지 않는 것이 **의도**인가, **공백**인가.

## 2. 판정 — 공백이다 (근거 4건)

OPS-107 §4가 이 모듈을 파이프라인에서 *의도적으로 제외*한 것은 사실이다("제외가 이 모듈의 정의" —
파이프라인을 거치면 캐시 적중 때 생성이 일어나지 않아 사전적재의 목적이 사라진다). 그러나 **파이프라인
제외와 관측 제외는 다른 사안**이다. 제외의 근거는 관측까지 닿지 않는다.

1. **의도라는 기록을 찾지 못했다.** 모듈 docstring·OPS-107 문서·`MEMORY.md`에서 사전적재(prewarm)와
   추적·trace·관측·Langfuse를 함께 다루는 줄을 grep했고, 나온 것은 환각 검증 슬라이스(40·47·48) 기록뿐이고
   "사전적재는 관측하지 않는다"는 결정은 없었다(**내가 찾은 방법으로는 0건** — 다른 이름의 기록이
   있을 수 있어 단정하지 않는다). 침묵은 의도가 아니다.
2. **프로젝트 규칙이 반대로 말한다.** CLAUDE.md "모든 LLM 호출 → Langfuse 추적". 예외 조항이 없다.
3. **같은 저작 계열이 이미 같은 공백을 메웠다.** `l3/llm_generator`는 "추적 0이던 공백 보정(2026-07-21
   정합성 검토)"으로 trace를 단다. 같은 부류인 사전적재만 빠진 것은 설계 차이가 아니라 누락이다.
4. **비용이 실재한다.** 사전적재는 CLOUD_MID·CLOUD_HIGH 호출을 낼 수 있어(`__main__.py`가 클라우드
   provider를 조립) 관측 부재는 비용 부재가 아니라 **비용의 비가시성**이다.

판정이 "의도"였다면 근거를 docstring에 적고 끝이었을 것이다. 공백이므로 acceptance가 정한 대로 저작 표지
(`TrafficSurface.AUTHORING`)를 단 trace를 연결한다.

## 3. 부수 발견 — 원가 좌석 생략 (이 PR이 고친 곳 + 고치지 않은 곳)

연결 도중 같은 모듈이 이미 틀린 원가를 내고 있음을 실측했다. 생성 로그(`GenerationLog.cost_usd`)를 계산하는
호출이 **좌석(`seat`)을 생략**해, 기본값 `SERVING_CLOUD_SEAT`(anthropic) 단가로 적혔다. 기본 좌석이
openrouter인 지금(ARCH-64) 이것은 과대 계상이다.

실측(`actual_cost_usd_or_none`, 1M 입력 + 1M 출력 토큰, 셀렉터 좌석 = openrouter):

| 티어 | 좌석 생략(수정 전) | 셀렉터 좌석 명시(수정 후) | 비율 |
|---|---|---|---|
| CLOUD_MID | **$18.0** | **$0.8** | **22.5배 과대** |
| CLOUD_HIGH | **$30.0** | **None(미측정)** | 단가 미등재 좌석에 지어낸 금액 |

CLOUD_HIGH의 openrouter 핀(`deepseek/deepseek-v4-pro`)은 단가가 미등재라 기록 원가는 *미측정*이어야 한다
(CLAUDE.md "모른다 ≠ 아니다"). 좌석을 생략하면 그 모름이 anthropic 단가로 접혀 $30이라는 값이 된다.

**좌석은 꽂힌 provider에서 읽는다**(`pipeline.served_cloud_seat` — ARCH-64 단일 원천). 설정 셀렉터를
다시 읽지 않는다: 주입된 provider와 셀렉터가 다를 수 있고(테스트·재현 프로브), 학생 대면·저작 경로가 모두
같은 원천을 읽어야 "어느 단가표로 계상했나"가 일치한다. 생성 로그와 trace는 같은 좌석을 읽어 서로 다른
원가를 말하지 않는다(테스트가 동결).

### 같은 결함이 다른 곳에 있다 → `OPS-116`

원가 계산 호출을 AST로 전수 스캔했다(`whymath_backend` 736개 파일): 원가 계산 호출 **13곳 중 좌석 명시 7곳 ·
생략 6곳**(`l3/cross_verify.py`·`l3/multi_solution.py`·`l3/pedagogy/analogy_generator.py`·
`l3/pedagogy/explanation_generator.py`·`l3/queue/tasks.py`·`ops/live_preflight.py`). ARCH-62가
`llm_generator` 한 곳만 고친 "한 곳에서만 고침" 계열이다. 이 6곳이 실제로 클라우드를 부르는지는 호출부로
확인하지 못했다 — 영향 유무를 단정하지 않고 판정부터 하도록 **`OPS-116`**으로 등재했다(범위 확장 금지:
이 PR은 사전적재기만 고친다).

## 4. 변경

| 위치 | 내용 |
|---|---|
| `l3/pregenerate/prewarmer.py` | provider 응답 직후(검증 전) `_record_trace` — 라우팅·usage·원가를 `l3_routing` 필드로 기록. 안쪽 sink를 `SurfaceTaggingTraceSink(..., AUTHORING)`로 감싼다. `trace` 미지정이면 `LangfuseSink`가 기본(키 미설정=no-op). `flush_trace()` 신설 |
| 같은 파일 | 생성 로그 원가에 `seat=self._served_seat()` 명시. `_served_seat`는 `pipeline.served_cloud_seat`(함수 안 지연 import — 모듈 최상단은 순환) |
| `l3/pregenerate/__main__.py` | `prewarm`을 `try/finally`로 감싸 종료 시 `flush_trace()` — 예외로 끝나도 쌓인 관측을 남긴다 |
| `tests/backend/l3/test_prewarmer_trace.py` | 신규 21건 |

설계 선택과 이유:

- **표지를 단다(추측이 아니라 사실이다).** 이 클래스를 만드는 프로덕션 호출부는 배치 CLI 하나뿐이고
  (소스 스캔 테스트가 동결 — 서빙 경로가 `CachePrewarmer`를 만들면 red) 모듈 정의가 빌드타임 사전생성이다.
  표지가 없으면 이 비용이 게이트② 서빙 표본의 '미표기'로 섞인다(`ops/cost_report`).
- **기록 시점 = 응답 직후·검증 전.** 응답이 오면 비용이 발생했으므로 검증 성패와 무관하게 남긴다
  (`llm_generator` 동형). provider가 예외를 던진 항목·인제스트·스킵은 생성 호출이 없었으므로 기록하지 않는다.
- **원가 회계는 `pipeline.generate`·`llm_generator`와 동형.** usage 없음·클라우드인데 토큰 미상이면 None
  (미상과 0원을 구분), LOCAL은 0원 확정.
- **never-break.** sink 예외는 배치를 깨지 않으며, 침묵하지 않고 **예외 타입명**을 경고로 남긴다
  (CLAUDE.md 침묵 실패 금지).
- **생성 로그와 Langfuse trace는 다른 채널이다** — provenance(재현 좌표)와 운영 관측. 하나가 다른 하나를
  대신하지 않는다.
- **끄는 옵션을 두지 않는다**("모든 LLM 호출 → Langfuse 추적" · EOS-55 생성 로그와 같은 방침).

## 5. 검증

- 신규 테스트 21건: trace 기록·표지, 호출 없는 경로(인제스트·스킵·provider 예외)의 비기록, 검증 실패 항목의
  비용 기록, sink 예외 비차단+타입명 로그, 기본 sink·주입 sink 둘 다 표지로 감쌈, flush 위임·오류 삼킴,
  좌석별 원가(오라클 = 라우터 원가 함수에 좌석을 명시한 값), 미등재 단가 → None, 미상 좌석 → None, 좌석
  표면 없는 provider → anthropic 구판 의미, 미계측·토큰 미상 → None, 전제 스캔(CLI만 `CachePrewarmer`
  생성), CLI의 예외 경로 flush.
- **뮤테이션(주입 적용·컴파일·원복 sha256 동일을 실행 전후 단언)**: 20종(주입 적용·컴파일·원복 sha256 동일을 실행 전후 단언) — **RED 기대 19종 중 19종 검출·이상 0**, 대조군 1종(`CachePrewarmer`를 만들지 않고 타입만 참조하는 모듈)은 기대대로 GREEN. 원복은 전 파일 sha256 동일·신규 파일 0. 주요 변형: trace 기록 제거(11건 RED)·검증 실패 항목 누락·인제스트 과기록·저작 표지 제거/오표기·좌석 생략 복원(생성 로그 4건·trace 4건 RED)·좌석을 셀렉터에서 읽기·미상 좌석을 anthropic으로 접기·usage 없는 호출을 0원으로 기록·CLI flush 누락·`finally` 아님·경고에 예외 메시지 노출·서빙 경로의 `CachePrewarmer` 생성(전제 위반)
- 정적 검사: ruff · black · `mypy --strict` · `lint-imports` 통과(종료 코드로 판정).

## 6. 정직한 공백

- **이미 적재된 생성 로그(`*.genlog.jsonl`)의 과대 계상은 소급 정정하지 않았다.** 이 수정은 앞으로의
  기록만 바로잡는다. 영향을 받았을 수 있는 범위는 "openrouter 좌석이 기본이 된 ARCH-64 컷오버 이후, 사전적재
  CLI로 CLOUD 티어를 부른 모든 실행"이다 — 실제로 그런 실행이 있었는지, 몇 건인지는 **미측정**이다(라이브
  데이터 없음). LOCAL 티어는 원가 0이라 영향이 없다.
- **라이브 Langfuse 전송은 이 세션에서 검증하지 못했다.** 키가 없는 환경이라 `LangfuseSink`는 no-op이다.
  테스트는 sink 계약(필드·표지·flush 호출)까지 검증하며, 실서버 도달은 별도 라이브 확인이 필요하다.
- **테스트에서 기본 `LangfuseSink`가 구성된다**(`llm_generator`와 같은 방식 — 키 미설정이면 네트워크 0).
  기존 사전적재 테스트가 별도 조치 없이 통과한 이유다.
- **OPS-105가 저작 표지를 의도적으로 달지 않은 다른 생성기들은 그대로다.** 이 PR은 사전적재기만 표지를 단다
  (그쪽의 판정은 OPS-105 문서). 그 생성기들의 원가 좌석 문제는 `OPS-116`이 판정한다.
- **게이트② 영향은 방향만 안다.** 사전적재 비용이 이전엔 아예 보이지 않았다 → 이제 저작 표면으로 따로
  보인다. 서빙 표본에서 빠진 양(운영 데이터)은 미측정이다.
