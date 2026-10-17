# OPS-89 — 캐시 브레이크포인트 위치: 최상위 자동 캐싱 → system 블록 끝

> **판정 기준**: `main a994a3457059ef938a8dfc8ab29db07662cc6f8e` + **미머지 작업 사본**(브랜치 `claude/gallant-euler-blngpj`의 OPS-89 변경, 이 문서 작성 시점 미커밋).
> 아래 "수정 후" 수치·판정은 전부 *그 미머지 작업 사본* 기준이며 trunk에 있다는 뜻이 아니다. "현행(수정 전)" 열은 `a994a3457`의 `l3/providers/anthropic.py` 기준이다.
> **라이브 축(실측 `cache_read_input_tokens > 0`)은 수행하지 않았다.** ARCH-66(2026-09-24~2026-12-31 Anthropic API 사용 중단)에 따라 라이브 호출 0건·키 없음. 이 문서의 "적중"은 전부 **시뮬레이션**이며 라이브 증거가 아니다.

## 0. 용어 풀이 (초보자용)

| 용어 | 뜻 |
|---|---|
| 프리픽스(prefix) | 요청 맨 앞에서부터 어느 지점까지의 내용. Anthropic은 요청을 `tools → system → messages` 순서로 이어 붙여 읽는다. |
| 프롬프트 캐싱 | 같은 프리픽스를 다시 보내면 서버가 처음부터 다시 읽지 않고 저장해 둔 것을 쓰는 기능. 읽기는 입력 단가의 약 0.1배, **쓰기는 약 1.25배**(할증)다. |
| 브레이크포인트(breakpoint) | "여기까지를 캐시해 달라"는 표시(`cache_control`). 표시 **앞쪽 전부**가 캐시 대상 프리픽스가 된다. |
| 자동 캐싱 | 요청 *최상위*에 `cache_control`을 한 번 쓰면 서버가 **마지막 캐시 가능 블록**에 브레이크포인트를 알아서 놓는 방식. |
| 가변 꼬리 | 호출마다 달라지는 부분(문항마다 다른 user 프롬프트). 꼬리 뒤에 표시를 놓으면 그 프리픽스는 다음 호출에서 같지 않아 **다시 읽히지 않는다**. |
| 최소 캐시 프리픽스 | 프리픽스가 이 토큰 수보다 짧으면 표시를 붙여도 **조용히 캐시되지 않는다**(오류 없음, `creation=0`·`read=0`). |
| 시뮬레이션 | 문서화된 규칙을 코드로 옮긴 모사. 규칙을 옳게 옮겼는지는 라이브로만 확인된다 — 라이브 증거가 아니다. |

## 1. 결함과 수정

**결함(코드를 읽어 판정, 라이브 관측 아님)**: `a994a3457`의 `AnthropicProvider.generate`는 캐싱 ON이면 `messages.create(system=<문자열>, cache_control={"type":"ephemeral"}, ...)`를 보냈다. 자동 캐싱의 브레이크포인트는 마지막 블록 = **가변 user 프롬프트의 끝**이다. 안정 system + 가변 user 꼬리 경로(`cross_verify._run_perspective`, `multi_solution.generate_candidates`)에서는 매 호출 새 프리픽스를 쓰기 할증으로 기록하고 적중은 0이다.

**수정**: 새 `_system_param()`(`l3/providers/anthropic.py`)이 캐싱 ON일 때 system을 블록 리스트로 보내 **system 블록 끝에 명시 브레이크포인트**를 둔다. 최상위 `cache_control`은 더 이상 싣지 않고 user 메시지에는 표시가 없다.

| | 수정 전(`a994a3457`) | 수정 후(미머지 작업 사본) |
|---|---|---|
| 캐싱 ON `system=` | `"공유 system"` (문자열) | `[{"type":"text","text":"공유 system","cache_control":{"type":"ephemeral"}}]` |
| 캐싱 ON 최상위 | `cache_control={"type":"ephemeral"}` | 없음 |
| 캐싱 ON `messages` | `[{"role":"user","content":prompt}]` | 동일(표시 없음) |
| 캐싱 OFF(기본) | `system=<문자열>`, `cache_control` 키 없음 | **동일**(기본값 회귀 0 — `test_defaults_send_system_as_plain_string`) |
| 빈/공백 `system` + ON | 문자열 `""` + 최상위 키 | 문자열 그대로, **브레이크포인트 생략**(빈 텍스트 블록을 만들지 않음) |

빈 system 생략 사유: 빈 텍스트 블록을 API가 거부할 수 있다는 알려진 동작에 대한 **보수적 회피**다. 실물 SDK는 이 값을 검증하지 않고 라이브가 막혀 실제 400 여부는 **라이브 미검증**이다. 그때는 브레이크포인트가 아예 없어 캐싱이 일어나지 않는다(user에 옮겨 다는 것이 곧 이 태스크가 막는 배치).

부수 변경: `config.py`의 `anthropic_prompt_caching` 설명 문자열이 "top-level cache_control"이라고 적어 거짓이 되므로 한 문장 정정했다(코드 의미 변경 없음).

## 2. 모사 결과 — 같은 system·다른 user의 연속 2회 호출 (시뮬레이션)

시뮬레이터 `PrefixCacheSim`(테스트 안): 렌더 순서 `tools → system → messages`, 브레이크포인트까지 프리픽스(모델+블록 바이트)가 같으면 읽기·아니면 쓰기, 최상위 `cache_control`은 마지막 블록에 브레이크포인트. 종전 배치는 수정 provider의 출력을 종전 형태(system 문자열+최상위 키)로 변환하는 어댑터로 재현했다. 세 경로 모두 **실제 코드**(`CrossVerifier._run_perspective`·`generate_candidates`·`AnthropicProvider.generate`)가 만든 (system, user)로 구동했다.

| 경로 | 현행(최상위) 2회차 read / creation | 수정(system 끝) 2회차 read / creation |
|---|---|---|
| 일반 `generate` | 0 / 쓰기 할증 재발생(>0) | >0 (= 1회차 creation) / 0 |
| `cross_verify._run_perspective` (관점 3종 각각) | 0 / >0 | >0 / 0 |
| `multi_solution.generate_candidates` | 0 / >0 | >0 / 0 |

대조군(시뮬레이터가 항상 0·항상 적중이 아님): 종전 배치도 **user가 완전히 같으면** 적중(2026-09-21 라이브 89.9%가 성립한 이유 — 그 회차 user가 사실상 상수); 수정 배치도 system이 다르면 적중 0; 최소 프리픽스 미만이면 두 배치 모두 `creation=0·read=0`. 테스트: `tests/backend/l3/test_cache_breakpoint_placement.py`.

**모사가 말하지 않는 것(라이브 미검증)**: 실제 API가 문서 규칙 그대로 동작하는지, 5분 TTL 만료, 병렬 호출 시 첫 쓰기 완료 전 경합, 20블록 룩백. 시뮬레이터는 TTL·동시성을 모델링하지 않는다(순차 호출 가정).

## 3. ④ 최소 캐시 프리픽스 — 위/아래/불명 (오프라인 보수적 추정)

정확한 토크나이저·`count_tokens`(라이브)가 없어 두 경계로 판정한다. **상한** = UTF-8 바이트 수(토큰이 바이트보다 많을 수 없다). **하한** = 문자 수/6(토큰당 문자가 6을 넘지 않는다는 *가정* — 영어 산문 약 4, 한글·수식은 더 낮다; 이 가정이 깨지면 '위' 판정이 틀릴 수 있다). 상한<최소 → **아래**, 하한≥최소 → **위**, 사이 → **불명**(통과로 접지 않음).

핀된 모델별 최소(공개 문서 표를 옮긴 값, 라이브 미검증): `claude-sonnet-4-6`(CLOUD_MID) = 1024 · `claude-opus-4-7`(CLOUD_HIGH) = **2048**(1024 아님).

| system 프롬프트(경로) | 문자 | UTF-8 바이트(상한) | 문자/6(하한) | Sonnet 4.6 (1024) | Opus 4.7 (2048) |
|---|---:|---:|---:|---|---|
| cross_verify probability / independent_reconstruction | 276 | 559 | 46 | 아래 | 아래 |
| cross_verify probability / adversarial_falsification | 331 | 703 | 55 | 아래 | 아래 |
| cross_verify probability / model_grounding | 306 | 632 | 51 | 아래 | 아래 |
| cross_verify statistical / statistical_reconstruction | 273 | 568 | 46 | 아래 | 아래 |
| cross_verify statistical / statistical_falsification | 305 | 647 | 51 | 아래 | 아래 |
| cross_verify statistical / statistical_grounding | 272 | 560 | 45 | 아래 | 아래 |
| cross_verify missing_condition / checklist | 510 | 909 | 85 | 아래 | 아래 |
| cross_verify missing_condition / model_grounding | 520 | 970 | 87 | 아래 | 아래 |
| cross_verify missing_condition / student_reading | 460 | 833 | 77 | 아래 | 아래 |
| cross_verify multiple_valid_answers / counterexample | 441 | 745 | 74 | 아래 | 아래 |
| cross_verify multiple_valid_answers / alternative_model | 344 | 580 | 57 | 아래 | 아래 |
| cross_verify multiple_valid_answers / boundary | 445 | 795 | 74 | 아래 | 아래 |
| multi_solution `_SYSTEM_PROMPT` | 961 | 1633 | 160 | **불명** | 아래 |
| equivalent `llm_generator._system_prompt()` | 3974 | 7061 | 662 | **불명** | **불명** |

(측정 시점 = 판정 기준 작업 사본. 프롬프트가 바뀌면 값이 바뀐다. `test_real_system_prompts_are_classified_never_assumed`는 분류가 *가능함*만 고정하고 값을 고정하지 않는다.)

**함의(라이브 미검증, 판정 근거 = 위 표의 확정 '아래')**: `cross_verify` 12개 관점은 system 프롬프트만으로는 *어떤 모델 최소치에도 못 미친다*(바이트 상한조차 1024 미만). 위치를 고치면 이 경로의 캐시는 **조용한 무효**가 되어 쓰기 할증은 사라지지만 적중도 생기지 않는다(`test_below_minimum_prefix_is_a_silent_noop_even_with_correct_placement`). 반면 종전 최상위 배치는 프리픽스가 *system+user 전체*라서 합계가 최소를 넘으면 쓰기 할증을 매번 냈을 수 있다(합계가 최소 미만이면 종전도 무효). 즉 이 경로에서 캐싱을 효과 있게 하려면 위치 수정만으로는 부족하고 공유 프리픽스(system 또는 공통 예시)를 최소 이상으로 키우거나 캐싱을 끄는 판단이 필요하다 — **이 태스크는 그 판단을 하지 않았다**(보고만). `multi_solution`은 Sonnet에서 불명이라 '효과 있음'으로 접지 않는다.

## 4. ⑤ 실물 SDK 표면 · pin

설치된 실물 anthropic 0.125.0과 PyPI 구버전을 `pip install --no-deps --target`으로 따로 설치해 `typing.get_type_hints`로 확인했다(시임 아님).

| 확인 | 결과 |
|---|---|
| `AsyncMessages.create`의 `system` | `Union[str, Iterable[TextBlockParam]]` — 0.40.0·0.83.0·0.125.0 모두 동일 |
| `TextBlockParam.cache_control` | 0.40.0 **없음**, **0.41.0부터 있음**(0.41.0~0.45.0·0.50~0.80(5간격)·0.83.0·0.125.0 확인) |
| 최상위 `cache_control` 인자 | 0.83.0부터(OPS-87 실측) — 이제 보내지 않음 |
| pin `anthropic>=0.83.0,<1` | 새 형태(system 블록)는 **0.41.0이면 충분** → 하한 0.83.0이 허용한다(부족하지 않음). 남은 최상위 인자 중 최고 하한은 `output_config`(0.77.0)이라 하한을 0.77.0까지 낮출 수 있으나 **pyproject를 바꾸지 않았다**(제안만) |
| 상한 `<1` | PyPI에 1.0.0~1.11.0이 이미 존재하나 `<1`이라 설치되지 않는다. 1.x에서 이 표면이 유지되는지는 **미확인**(이 태스크 범위 밖) |

테스트(`tests/backend/l3/test_anthropic_sdk_surface.py`): 최상위 `cache_control` 음성 대조군, `create(system=)`이 블록 리스트를 받는 시그니처, `TextBlockParam`의 `cache_control` 필드, 우리가 싣는 블록의 모든 키가 SDK TypedDict에 있음, 하한 대조(`SYSTEM_BLOCK_FIRST_VERSION = 0.41.0`), 그리고 실물 `AsyncAnthropic`을 `httpx.MockTransport`(네트워크 없음)에 물려 **실제 직렬화된 요청 본문**의 `system` 블록 표시·최상위 키 부재와 응답 usage의 `cache_read_input_tokens` 파싱을 확인한다.

## 5. 뮤테이션(변별력)

`cp` 백업 → 주입(원본≠변경·치환 count==1 단언) → 새 3개 테스트 파일 실행 → `cp` 원복(sha 동일 단언). 7종 전건 RED, 원복 sha 동일.

| # | 주입 | 결과 |
|---|---|---|
| M1 | 종전(최상위 `cache_control` + system 문자열)으로 복귀 | RED 18건 |
| M2 | 브레이크포인트를 user 메시지로 이동 | RED 15건 |
| M3 | 캐싱 ON인데 system을 문자열 그대로 | RED 15건 |
| M4 | system 블록에서 `cache_control` 제거 | RED 14건 |
| M5 | system 블록 + 최상위 `cache_control` 동시 | RED 15건 |
| M6 | 빈 system에 빈 텍스트 블록 생성 | RED 4건 |
| M7 | 캐싱 OFF인데도 블록 리스트 | RED 2건 |

## 6. acceptance 자기평가

| 항 | 판정 | 근거 |
|---|---|---|
| ① 현행 형태 고정 | 충족 | 시뮬레이션 테스트가 종전 형태를 어댑터로 재현·고정, `a994a3457` 기준 서술 |
| ② 문제 실증 | **부분(시뮬레이션만)** | 모사에서 현행 2회차 적중 0·할증 재발생을 경로 3종(일반·`_run_perspective`·multi_solution)에서 확인. **캐시 ON 라이브로 cache_read 0을 관측한 것은 아니다** |
| ③ 수정 | 충족(코드) | system 블록 끝 명시 브레이크포인트, 시그니처 `str | list[dict]` 확장, 기본값 회귀 0 |
| ④ 최소 토큰 | 충족(오프라인 3상태) | §3. cross_verify 12종 확정 '아래', multi_solution Sonnet '불명'. `count_tokens`는 라이브라 **미수행** |
| ⑤ 검증 | **부분** | "경로별 2회차 `cache_read_input_tokens > 0`" 단언은 **시뮬레이터의 usage**(provider의 실제 `_extract_usage`를 통과)에 대해서만 성립. **실제 API의 `cache_read_input_tokens > 0`은 미수행·미측정**이며 통과로 계상하지 않는다. 실물 SDK 표면 축은 §4로 충족(OPS-87 계열 파일에 추가; 별도 조율 없이 같은 파일을 확장했으므로 OPS-87 소유자에게 통지 필요) |
| ⑥ 선행 관계 | 해당 없음(미해소) | EOS-02 ③ 기본값 전환 재판정은 게이트 `G-eos02-default-flip-recheck`가 소유. 이 태스크가 코드 선행을 닫았으나 **라이브 적중 증거가 없어** 재판정 입력으로는 불충분 |
| ARCH-66 라이브 축 | 미수행(명시) | 재판정 게이트 `G-arch66-anthropic-api-pause-review` 전까지 수행 안 함 |

## 7. 남은 불확실성

1. 시뮬레이터 규칙의 실제 API 일치(라이브 미검증). 특히 "브레이크포인트 앞 프리픽스가 같으면 읽기"와 "빈 텍스트 블록 거부".
2. §3의 '아래' 판정은 바이트 상한(견고), '위' 판정은 문자/6 하한(가정). 최소치 표(Sonnet 4.6=1024, Opus 4.7=2048)는 공개 문서 표를 옮긴 값이다.
3. 이 변경은 **Anthropic 좌석**에만 해당한다. 현재 기본 클라우드 좌석은 OpenRouter(ARCH-64)이며, 그 좌석의 캐싱 구성은 이 태스크에서 확인하지 않았다.
4. `pyproject.toml`의 anthropic 하한 주석은 "최상위 인자 9종·cache_control 0.83.0"을 서술해 이제 낡았다(수정 안 함 — 제안: 8종·system 블록 `cache_control` 0.41.0 병기).
5. TTL(5분)·동시 호출 경합 미모사.
