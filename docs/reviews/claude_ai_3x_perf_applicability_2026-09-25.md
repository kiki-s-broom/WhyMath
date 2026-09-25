# Claude.ai 3배 가속 사례의 WhyMath 적용성 검토 (2026-09-25)

> **판정 기준**: main `d5438782` — 이 문서의 "있다/없다"는 전부 이 커밋 기준이다(미머지 브랜치는 보지 않았다).
> **성격**: 조사 문서. 코드 변경 0건. §6의 태스크 후보 9건 중 **최소 묶음 3건(R1·R4·R6)만 등재**했다(2026-09-25 Kiki 지정 — `OPS-95`·`MOB-24`·`OPS-96`). 나머지 6건은 미등재이며 착수 여부는 Kiki 판단 사항이다(§2-E: 의사결정 우선순위상 UX는 5순위이고, 지금은 12/31 내부 완성 집중 기간이다).
> **원문**: claude.dev 「Claude.ai를 2주 만에 3배 빠르게 만든 방법」(GeekNews 한국어 요약본 경유, 2026-09).
> **부재 판정 범위**: "0건"은 모두 **부록 A에 적은 검색어로 찾은 범위에서** 0건이라는 뜻이다(CLAUDE.md「식별자 부재를 기능 부재로 단정 금지」).

---

## 0. 한 줄 결론

글의 핵심은 "**측정할 수 있으면 최적화할 수 있다**"이다. WhyMath에서는 바로 그 **측정 장치가 거의 없다.** 서버 지연은 전역 p95 하나만 잰다. 클라이언트 지연과 CI 성능 게이트는 둘 다 0건이다.

그래서 WhyMath에 먼저 옮길 것은 글의 개별 최적화 기법이 아니라 **측정과 상한 고정(ratchet) 체계**다. 개별 기법은 두 가지 이유로 그대로 옮기면 안 된다.
- **지연의 주성분이 다르다.** 코치 한 턴은 LLM을 최대 16회 직렬로 부르고, 타임아웃이 15초다.
- **교수학 계약과 부딪치는 기법이 있다.** 검증 전 토큰 스트리밍과 부작용 있는 prefetch가 그렇다.

가장 큰 지연(코치 턴)을 줄일 방법은 WhyMath 설계 안에 이미 있다. `04a` §5.3 **fast path**는 단순 턴에서 LLM 루프를 건너뛰는 방식인데, 설계만 있고 구현을 맡은 태스크가 없다(§2-B).

---

## 1. 글에서 옮길 수 있는 원칙 7개

| # | 원칙 | 글의 구체 사례 |
|---|---|---|
| P1 | **사용 비중으로 핵심 흐름을 고른다** | 실행·대화 시작·기존 대화 로딩·메시지 전송의 4흐름이 활동의 95%다. 웹·데스크톱으로 나누면 13개 측정 항목이 된다 |
| P2 | **상호작용부터 렌더 완료까지 전체 구간을 재고, 클라이언트와 서버 구간을 나눈다** | 목표는 p75 기준. 입력 가능 시간이 3.1초에서 0.55초가 됐다 |
| P3 | **잡음 큰 벽시계 대신 결정론적 대리지표를 CI 상한으로 쓴다** | Valgrind 명령어 수·V8 함수 호출 수·React 커밋 수·스타일 재계산 수·DOM 변경 수. **실제 지연과 상관이 검증되지 않은 지표는 폐기**했다 |
| P4 | **개선되면 상한을 낮춰 고정한다(ratchet)** | 명령어 수를 늘리는 PR은 CI에서 실패한다. 일일 작업이 더 낮은 수치를 얻으면 상한을 내린다 |
| P5 | **입력을 먼저 가능하게 한다** | HTML 정적 입력창, 화면 전환 시 입력창 유지, 마우스를 올리면 미리 불러오기 |
| P6 | **안전장치를 먼저 깐다** | 단위 테스트 → 단기 기능 플래그 → 직원 → 1% → 전체. 플래그 약 200개를 추가했고 스프린트 종료 시 절반 이상을 정리했다 |
| P7 | **사람은 야심·안목·방향을 맡는다** | 메시지당 2ms를 줄이는 900줄 PR은 유지보수 비용 대비 이득이 작아 거절했다 |

이 가운데 P3·P4·P6은 WhyMath가 **이미 다른 영역에서 쓰고 있는 문화**다. 커버리지 계층 floor ratchet(`scripts/coverage/check_layer_coverage.py`), 오진단 상한 7% ratchet, 기본 OFF canary 플래그 규약이 그 예다. 새 제도를 들이는 게 아니라 **같은 도구를 성능 축으로 넓히는 일**이다.

---

## 2. 그대로 옮기면 안 되는 것 — WhyMath 조건 차이 6개

### 2-A. 현장 데이터가 없다
글은 Datadog 실사용 데이터로 핵심 흐름을 골랐고 p75를 현장에서 쟀다. WhyMath는 **학생 참여 과정 전체가 12/31 이후로 연기됐다**(`ARCH-66` ⑥, 2026-09-24 Kiki 결정). 그러므로 다음과 같이 한다.
- 핵심 흐름은 **사용 비중이 아니라 설계 문서로 정의**한다. 기준은 `docs/standards/incident_response_slo.md` §1-1의 T1/T2 티어다(§4).
- 지금 가능한 측정은 **실험실 측정뿐**이다. 현장 p75는 12/31 이후 재개 게이트 `G-student-work-after-internal-completion`과 함께 판단한다.
- 현장 계측 인프라(RUM, Datadog 류)를 지금 만드는 것은 **소비자 0인 설정**이다. 이 저장소는 그 부류를 이미 상환 중이다(`ADMIN-02`·`ADMIN-12`).

### 2-B. 지연의 주성분이 다르다
Claude.ai는 LLM 응답을 이미 스트리밍하는 상태에서 **프런트엔드 밀리초**를 깎았다. WhyMath의 가장 무거운 흐름은 코치 턴(`POST /v1/coach/sessions/{id}/turns`)이다.
- **WH-1 primary**(`wh1_primary_enabled` 기본 ON): 도구 1회가 LLM 1회다. 최대 `max_tool_calls=16`회를 직렬로 부른다(`harness/wh1_primary.py:118`).
- 한 턴 전체를 `asyncio.wait_for` **15초**로 감싼다(`config.py` `wh1_primary_timeout_seconds`). 프로즈 rephrase를 켜면 3초가 더해진다.
- 로컬 FAST 티어 p50은 1,010ms다(`l3/router.py` `LOCAL_LATENCY_MS`). 도구를 3회만 불러도 LLM 구간이 약 3초다.
- 목표는 PRD「Socratic 응답 < 3초」(`docs/strategy/prd_v1.2.md`)와 SLO S5「T1 p95 ≤ 5s」다. **타임아웃 상한이 목표의 3~5배**이고, 한 턴에 도구를 실제로 몇 번 부르는지는 **분포를 잰 적이 없다.**

즉 WhyMath에서 **프런트엔드 ms 최적화의 이득은 LLM 구간의 1/10~1/100 수준**이다. 순서가 뒤바뀌면 안 된다.

**WhyMath 설계에는 이미 해법이 있다.** `docs/architecture/04a_wh1_tutoring_harness.md` §5.3 **Fast Path**의 내용은 이렇다. 풀이 제출이 없는 턴(인사, "네", 격려 요청, 단순 진행 확인)은 도구 루프 없이 즉답하고, 풀이가 포함된 턴만 풀 루프를 돈다. 리스크 R9("단순 턴까지 풀 루프 → 학생 이탈")의 완화책으로 설계됐고, 글의 "무거운 경로를 건너뛰어 입력을 먼저 받는다"(P5)와 같은 발상이다. 그런데 같은 문서의 구현 매핑은 "**fast path(§5.3)는 후속**(전 턴이 풀 루프 — 레이턴시는 타임아웃+폴백으로 방어)"이라고 적고 있다. 코드도 같은 말을 한다. `harness/wh1_primary.py:39`에 "범위 밖(후속): fast path(§5.3·비풀이 턴 경량 즉답 — 레이턴시 최적화)"라고 적혀 있다. 반면 `backlog/tasks/`에서 `fast.path`·`fast_path`로 검색하면 **담당 태스크 0건**이다. 설계된 완화책이 docstring 속 계획으로만 남아 있고 소유자가 없다. CLAUDE.md의 「docstring 속 계획은 백로그를 대신하지 못한다 — 추적하려면 태스크로 등재한다」가 정확히 이 경우에 해당한다.

> ⚠ `LOCAL_LATENCY_MS`의 QUALITY 값(2026-08-22 측정)은 Phaiakes9 침해 기간과 겹친다. `docs/ops/amd395_local_llm_performance.md` 정정 박스에 따르면 재측정 전까지 **잠정치**로 읽어야 한다(`SEC-34`·`OPS-75`).

### 2-C. 토큰 스트리밍을 그대로 쓸 수 없다 — 그리고 지금은 줄여 줄 대기도 없다
Claude.ai 체감 속도의 바탕은 토큰 스트리밍이다. WhyMath에는 두 가지 차이가 있다.

- **지금은 스트리밍으로 줄일 대기가 없다.** 현재 코치 턴에서 LLM은 **말할 내용을 쓰는 데가 아니라 다음 행동(도구)을 고르는 데** 쓰인다(`harness/wh1_llm_policy.py` `LLMTutorPolicy.next_action`). 발화 본문은 결정론 템플릿이고, 이를 LLM으로 다듬는 프로즈 rephrase는 기본 OFF다. 대기는 "무엇을 말할지 고르는 루프"에서 생기므로, 토큰 스트리밍을 붙여도 체감 대기는 줄지 않는다. 줄이는 수단은 **루프 횟수 자체**(fast path·도구 호출 수 상한)다.
- **나중에 LLM이 발화를 직접 쓰게 되면 검증 계약에 걸린다.** WhyMath 헌법은 「LLM 응답을 검증 없이 학생에게 제공 금지」다. WH-1 primary의 발화는 **verify 의무 → 정답 억제 백스톱 → L4 톤필터**를 통과한 것만 노출된다(`config.py` `wh1_primary_enabled` 설명문). 토큰 단위로 흘리면 **검증 전 텍스트가 화면에 나간다.**

가능한 대안(교수학 설계 결정 — `pedagogy-designer` 검토 필요):
- (a) **검증을 통과한 단위만 흘린다.** 문장이나 블록 단위로 끊는다.
- (b) **진행 단계를 표시한다.** "지금 네 풀이를 살펴보는 중이야" 같은 문구로 대기를 설명한다. 현재 대기 표시는 2px 진행 막대뿐이다(`src/mobile/lib/features/chat/presentation/chat_screen.dart:350`).
- (c) **결정론 즉답을 먼저 주고 LLM 보강을 뒤에 붙인다.** 결정론 템플릿이 이미 폴백으로 존재한다.

### 2-D. 빨라지면 안 되는 시간이 있다
- **학생의 생각 시간은 최적화 대상이 아니다.** `api/coach.py`의 `_log_response_latency_event`는 학생이 답하기까지 걸린 시간을 기록한다. 이름에 latency가 들어 있지만 **앱 지연이 아니다.** 헌법 「"정답을 빠르게"를 KPI로 사용 금지」와 부딪치지 않도록, 성능 지표는 **"앱 때문에 기다리는 시간"만** 대상으로 한다.
- **prefetch는 부작용 없는 조회에만 쓴다.** 두 가지 제약이 있다.
  - 단계 패널은 prefetch 금지가 **교수학 계약**이다. `step_panel_controller.dart:6-10`, SOL-02 acceptance ⑤에 "미펼침 단계 내용 미보유 — 클라 측 캐시·prefetch 없음"이라고 되어 있다. 힌트와 풀이 단계에 마우스 호버 prefetch를 넣으면 안 된다.
  - `GET /v1/me/next-problem`은 **읽기처럼 보이지만 쓰기가 있다.** 호출할 때마다 `record_learning_activity`와 `record_recommendation_treatment`를 실행하고 commit한다(`api/me.py:2650-2667`). 주석에 "**학생에게 실제로 반환되는 추천만 기록한다(가짜 처치 금지)**"라고 적혀 있다. 다음 문제를 미리 불러오면 학생이 보지 않은 추천이 처치로 기록돼 추천 효과 분석이 오염된다. 이 API를 prefetch하려면 먼저 **조회와 처치 기록을 분리**해야 한다(§5 R4).

### 2-E. 우선순위가 다르다
CLAUDE.md 의사결정 우선순위에서 사용자 경험은 **5순위**다(학생 안전 > 법·윤리 > 교수학 정확성 > 학습 효과 > **UX**). 2026-09-22 결정으로 12/31까지는 **내부 콘텐츠 완성**(`S4-01` 등)이 먼저다. 그러므로 글처럼 2주 스프린트를 할 것이 아니라 두 가지만 권한다.
- **측정 장치**를 싸게 먼저 깐다(R1·R2).
- **실측으로 확인된 값싼 개선**만 한다(R4 일부).

### 2-F. 규모가 다르다
글은 Slack 채널 하나에서 150개 넘는 스레드를 병렬로 돌렸다. 이 저장소는 병렬 세션이 같은 태스크를 중복 구현한 사고 이력이 있다(`OPS-07` 735줄 폐기, `MP-04` 40분 폐기). 규약은 **1 세션 = 1 도메인 = 1 브랜치**(`docs/standards/parallel_sessions.md`)다. 병렬 확장은 흐름 단위로 태스크를 쪼개 claim하는 기존 하네스 방식으로만 한다.

---

## 3. 현황 실측 (main `d5438782`)

### 3-1. 원칙별 판정표

| 원칙 | WhyMath 현황 | 판정 |
|---|---|---|
| P1 핵심 흐름 선정 | SLO 문서가 T1~T4 티어로 경로를 나눴다. 하지만 흐름(여러 API와 화면의 연쇄) 단위 정의는 없다 | ⚠ 부분 |
| P2 전체 구간 계측 | **서버**: `ServiceMetrics`(`ops/service_health.py:280-349`)가 요청 지연을 잰다. 한계는 네 가지다. ①고정 창 500건의 **전역 p95 하나** ②**라우트 차원 없음**(코치 LLM 턴과 가벼운 GET이 한 창에 섞임) ③워커별 계산 ④재시작 시 소실. SLO S5(경로별 p95)는 문서 스스로 ❌ **미측정**이라고 적고 있다. **클라이언트**: 계측 코드 0건. **구간 분리**: Server-Timing·요청 ID 0건, OpenTelemetry는 의존성 선언만 있고 import 0건 | ❌ 대부분 없음 |
| P3 결정론 대리지표 | 재료는 있다. fake session 문장 수를 **정확히 같은지**로 단언하는 테스트가 7개 파일 36곳에 있다(예: `tests/backend/api/test_me.py`의 `_NP_STMT_BASE=5`). 하지만 동작 변별이 목적이고 **상한 예산은 아니다** | ⚠ 재료만 |
| P4 ratchet | 성능 축에는 0건. `.github/workflows/*.yml`에서 bench·perf·latency·p95·budget 검색 0건. pytest-benchmark·pytest-timeout도 없다 | ❌ 없음 |
| P5 입력 먼저 | 채팅 입력은 로컬 컨트롤러라 키 입력이 Riverpod 상태를 건드리지 않는다(양호). 전송 중에는 **입력창 자체가 잠긴다**(`chat_screen.dart:387` `enabled: !state.isSending`). MathLive WebView는 진입할 때마다 새로 띄운다(사전 워밍 0) | ⚠ 부분 |
| P6 안전장치 | 기능 플래그 19개(기본 ON 8개, OFF 11개)와 기본 OFF canary 규약, `WHYMATH_*` 킬스위치가 있다. **사용자 단위 단계 배포**(퍼센트·코호트·직원 먼저)는 0건이다. 다만 실사용자가 0이라 지금은 공백이 아니다(§2-A) | ✅ 현 단계엔 충분 |
| P7 사람의 판단 | 게이트 대장·One In→One Out 교환제(`HARN-55`)·EOS 등급으로 이미 제도화돼 있다 | ✅ |

### 3-2. 핵심 흐름별 직렬 단계 (정적 분석 — 실측 아님)

| 흐름 | 클라이언트 | 서버 |
|---|---|---|
| **진단 진입 → 문제 표시** | `diagnosis_controller.dart:41-59`가 `getNextProblem` → `getProblem` → `getDiagnosisConcepts`를 **3번 순서대로 기다린다.** 3번째 결과 `diagnoses`는 상태에 담기만 하고 **어떤 화면에도 표시되지 않는다**(`lib/features/problems`·`lib/features/chat` 전수 검색 결과 참조 0건. 나 탭은 별도 컨트롤러로 따로 불러온다). 대기 표시는 화면 전체 스피너이고 스켈레톤은 없다 | next-problem은 DB 약 10회 이상 직렬 + commit이다(`EOS-114`가 "먼저 재라"로 이미 등재). LLM 0회 |
| **답·발화 전송 → 코치 응답** | 학생 버블을 먼저 붙인다(낙관적 반영·양호). 응답은 한 번에 온다(스트리밍 0) | 직렬 await 약 25회, DB 읽기 약 13종, WH-1 LLM 최대 16회, SymPy `verify_final_answer`를 이벤트 루프에서 동기 실행한다 |
| **답안 제출** | — | `POST /v1/me/attempts`는 직렬 await 약 12단계와 commit 3~4회로 이뤄진다. LLM 0회, `gather` 0회 |
| **'수식으로 입력' → 입력 가능** | 진입할 때마다 새 WebViewController를 만들고 `mathlive.iife.js`(839,303바이트)를 동기 로드한다. 키 입력마다 화면 전체 setState가 일어난다 | — |
| **모든 API 공통** | `core/auth_interceptor.dart:50`이 **요청마다 보안 저장소에서 액세스 토큰을 읽는다**(플랫폼 채널 왕복·메모리 캐시 0) | — |

### 3-3. 렌더링 (프레임 예산 축)
- **수식 렌더 결과를 저장하지 않는다.** `shared/widgets/math_text.dart`가 build할 때마다 세그먼트 분리와 `Math.tex` 생성을 다시 한다. 이 생성 단계에서 TeX를 파싱하는지는 라이브러리 소스로 **미확인**이다.
- **메시지 버블이 화면 크기 변화 전체를 구독한다.** `chat_screen.dart:832`의 `MediaQuery.of(context).size` 때문에 키보드 애니메이션 **프레임마다** 버블이 다시 그려진다. `MediaQuery.sizeOf`로 좁히면 해소된다.
- **그래프 계산기**(`src/web/graphing-calculator/src/GraphingCalculator.jsx`)는 한 컴포넌트에 `useState`가 42개다. 포인터가 움직일 때마다 `setHover`가 불려 컴포넌트 전체 리렌더와 캔버스 전체 재그리기가 일어난다. requestAnimationFrame으로 묶지 않는다.
- **성능 테스트 0건**: `integration_test/`·`test_driver/` 디렉터리 부재, traceAction·FrameTiming·골든 0건.
- **목표 수치는 문서에만 있다.** `.claude/agents/flutter-engineer.md` §성능 목표에 앱 시작 < 2초, 전송 → 첫 토큰 < 2초, 60fps 95%+가 적혀 있지만 이를 재는 코드는 0건이다.

---

## 4. WhyMath판 핵심 흐름 정의 (제안)

글의 "4흐름 = 활동의 95%"에 해당하는 것을, 사용 데이터 대신 **SLO 티어 + 학생 학습 루프**로 정의한다.

| ID | 흐름 | 시작 → 끝 | 대응 SLO | 1차 측정 수단(실험실) |
|---|---|---|---|---|
| **F1** | 앱 시작 | 콜드 스타트 → 첫 입력 가능 | (없음 — 신설 필요) | Flutter profile 모드 타임라인 |
| **F2** | 문제 받기 | 진단 진입 또는 '다음 문항' 탭 → 문제 발문 표시 | S5 T2 p95 ≤ 1s | 서버: 경로별 지연 + DB 문장 수 / 클라: 왕복 수 |
| **F3** | 코치 응답 | 전송 탭 → 코치 버블 표시 | S5 T1 p95 ≤ 5s · PRD < 3s | 서버: 턴 지연 + **LLM 호출 수·도구 호출 수 분포** |
| **F4** | 수식 입력 | '수식으로 입력' 탭 → MathLive 입력 가능 | (없음) | WebView 로드 완료 시각 |

- F3이 **지배적**이다(§2-B). F2는 싸게 고칠 수 있는 게 이미 보인다(§3-2의 미사용 왕복).
- 손글씨 OCR은 기본 OFF(`ocr_enabled=False`)라 지금은 제외한다. 켤 때 F5로 추가한다.

---

## 5. 권고 (우선순위 순)

각 권고에는 CLAUDE.md 규약에 따라 **측정 방법**과 **동결(회귀 방지) 방법**을 함께 적는다. 모든 권고에 공통으로 적용하는 규칙이 하나 있다. **"개선했다"는 주장은 꺼진 상태와 켜진 상태를 모두 재서 대조**한다(「보호 장치를 실패 주입 없이 선언 금지」).

### R1. 서버 경로별 지연 계측 — SLO S5 해소 (가장 싸고 가장 먼저)
- **무엇**: `ServiceMetrics`에 **라우트 템플릿 차원**을 더한다. 경로 문자열이 아니라 `/v1/coach/sessions/{dialogue_id}/turns` 같은 템플릿 단위로 모아야 경로 수가 폭발하지 않는다. 경로별 p50/p75/p95를 낸다.
- **함께 할 것**: 응답에 `Server-Timing` 헤더를 붙여 클라이언트가 서버 구간과 나머지(네트워크·디코드·렌더)를 나눌 수 있게 한다(P2).
- **왜**: SLO S5가 자기 문서에서 "미측정"이다. 기존 `OPS-30` ④는 "경로별 지연 분해(S5)"를 **범위 밖으로 명시**했으므로 **소유자가 없다.**
- **동결**: `test_slo_contract.py`의 S5 상태를 ❌에서 ✅로 바꾸고, 경로 차원이 사라지면 RED가 나는 테스트를 둔다.

### R2. 결정론 대리지표 CI 예산 + ratchet (글의 P3·P4 이식)
- **무엇**: F2·F3의 서버 경로에서 **잡음 없는 수**를 세고 상한을 건다.
  - **DB 문장 수**: SQLAlchemy `before_cursor_execute` 이벤트로 센다.
  - **LLM 호출 수**: fake provider 호출 카운터로 센다.
  - **WH-1 `tool_calls` 수**: 고정 시나리오 입력으로 센다.
- **왜 이 지표인가**: 벽시계는 CI 러너 잡음이 커서 밀리초 상한으로 쓰기 어렵다(글의 판단과 같다). 반면 문장 수와 LLM 호출 수는 **이 앱의 지연을 실제로 지배하는 양**이다. LLM 1회에 약 1초, DB 1회에 수 ms가 든다.
- **글의 폐기 규칙을 그대로 가져온다**: 채택 전에 실제 PG + 로컬 LLM에서 **대리지표와 벽시계의 상관**을 확인한다. 상관이 약한 지표는 버린다.
- **ratchet**: 커버리지 floor와 같은 방식이다. 상한을 넘는 PR은 실패시키고, 실측이 더 낮아지면 상한을 내린다. 이미 있는 `_NP_STMT_BASE` 같은 정확 일치 단언은 **동작 변별용이므로 그대로 둔다.** 상한 예산은 별도 테스트로 만든다.
- **변별력**: 문장 1개를 추가하는 뮤테이션을 주입해 RED가 나는지 확인한다.

### R3. 코치 턴 지연 예산 정합 (F3 — 지배 구간)
- **무엇**: ①한 턴의 **도구 호출 수 분포와 턴 지연 분포**를 실험실에서 잰다. 고정 시나리오 N건을 로컬 LLM으로 돌리되, **단순 턴("네"·인사)과 풀이 턴을 나눠** 잰다. ②단순 턴이 풀 루프를 도는 비용이 크면, 이미 설계된 **§5.3 fast path를 배선**한다. 기본 OFF canary 플래그로 넣는다. 핵심은 "풀이 없음" 사전 분류가 **틀렸을 때의 비용**이다. 풀이 턴을 단순 턴으로 오분류하면 검증 루프를 건너뛴다. 그러므로 분류기는 **애매하면 풀 루프**(fail-closed)로 보내야 하고, 그 오분류율을 재는 것까지가 이 권고의 범위다. ③결과를 보고 `wh1_primary_timeout_seconds`(15초)와 `max_tool_calls`(16)를 SLO T1 p95 5초에 맞출지, SLO를 고칠지 **Kiki가 판단**한다. ④어느 쪽이든 결정된 **기본값을 테스트로 동결**한다. 지금은 두 타임아웃 기본값을 참조하는 테스트가 0건이다.
- **선행 조건**: Phaiakes9 재측정(`OPS-75`)이 먼저다. 감염 기간 수치로는 결정하지 않는다.
- **교수학 축**(§2-C): 스트리밍 또는 진행 단계 표시를 설계한다. 이것은 `pedagogy-designer`의 결정이며, 성능 태스크가 단독으로 정하지 않는다.

### R4. 값싼 클라이언트 개선 — 실측 확인분만
F1~F4 계측(R5)이 없어도 **정적 분석만으로 낭비가 확정되는** 것만 고른다.

| 개선 | 근거 | 주의 |
|---|---|---|
| 진단의 3번째 왕복 제거 | `diagnoses` 표시처 0건(§3-2) | 나중에 표시할 계획이 있으면 제거 대신 **병렬화**(`Future.wait`)한다. 나 탭이 이미 이 방식을 쓴다 |
| 액세스 토큰 메모리 캐시 | 요청마다 보안 저장소 왕복 | **갱신·로그아웃 시 무효화가 핵심**이다. 1회용 리프레시 토큰 회전 로직(`_inFlightRefresh`)과의 정합을 테스트로 고정한다(보안 축 — 캐시가 낡은 토큰을 내면 401 폭주) |
| 전송 중 입력창 열어 두기 | `enabled: !state.isSending` | 잠그는 것은 전송 버튼만. 교수학적으로 "기다리는 동안 다음 생각을 적는 것"은 해가 없다 |
| 버블 `MediaQuery.sizeOf` | 키보드 프레임마다 재빌드 | 한 줄 변경이다 |
| `MathText` 파싱 결과 캐시 | 메시지는 불변 | `Math.tex`가 실제로 생성 시점에 파싱하는지 먼저 확인한다(§3-3 미확인) |
| 다음 문제 prefetch | '다음 문항'을 즉시 반응하게 | **보류 — 서버에서 조회와 처치 기록을 분리하기 전에는 금지**(§2-D) |

### R5. 클라이언트 흐름 계측 (F1~F4)
- **1단계(지금)**: 앱 안에 구간 마커(`Stopwatch`)와 개발용 오버레이를 둔다. profile 빌드로 Kiki 실기기에서 수동 측정한다. **외부 전송 없음.**
- **2단계(12/31 이후)**: 서버로 보내는 현장 계측. 미성년자 데이터 정책상 **학습 데이터가 아니라 기기 성능 텔레메트리**로 분리하고, 동의 범위와 PII 배제를 먼저 검토한다(`docs/standards/security_privacy.md`).
- **CI 동결**: 글의 "정적 입력창과 React 화면 1픽셀 정렬 검사"처럼, 위젯 테스트 수준에서 **빌드 횟수 상한**을 건다. 예: 키 입력 1회에 MathText build가 N회 이하. 디바이스가 필요한 `integration_test`는 CI 비용이 커서 후순위다.

### R6. 이벤트 루프를 막는 동기 CPU 작업 (가용성 축 — 성능 이상의 문제)
- SymPy 검증(`api/verify.py`, 코치 `verify_final_answer`)과 OCR 영역 검출(ONNX)이 **이벤트 루프 위에서 동기로, CPU 타임아웃 없이** 돈다. 입력 길이 상한(4,000자·50개)만 있다.
- 단일 asyncio 루프에서는 **느린 SymPy 요청 하나가 모든 학생의 요청을 멈춘다.** 전역 p95 오염을 넘어 가용성 문제다.
- `asyncio.to_thread` 또는 프로세스 풀로 옮기고 CPU 시간 상한을 둔다. **SymPy는 검증 단일 권위**이므로 타임아웃은 "통과"가 아니라 **"판정 불가(undecidable)"로 떨어져야 한다.** 타임아웃을 정답 처리하면 검증 우회가 된다.

### 지금 하지 않을 것 (글의 P7 — 안목)
- **현장 계측 인프라(RUM) 구축**: 소비자가 0이다(§2-A).
- **120fps 프레임 예산 작업**: 스트리밍이 없고 긴 응답 렌더가 병목이라는 증거도 없다.
- **V8 코드 캐시 류**: Flutter는 AOT 컴파일이라 해당 없다. WebView 안의 JS 코드 캐시는 R5 측정 뒤에 판단한다.
- **사용자 단위 단계 배포 체계**: 파일럿 전까지는 기존 전역 플래그와 킬스위치로 충분하다.

---

## 6. 태스크 후보 (3건 등재 · 6건 미등재)

등재는 `backlog.py add`로만 한다. 번호는 CLI가 배정한다(「태스크 ID 번호를 추론으로 배정 금지」). 등재 3건은 CLI가 제안한 번호를 그대로 썼다. 미등재 행의 이름은 가칭이다.

| 가칭 | 권고 | 레이어 | 크기 | 선행·연결 | 등재 |
|---|---|---|---|---|---|
| 경로별 서버 지연 계측 + Server-Timing | R1 | backend | 소 | `OPS-30`(범위 밖으로 넘긴 S5를 인수) | ✅ `OPS-95` (P1) |
| 핵심 흐름 결정론 예산 게이트(ratchet) | R2 | backend·infra | 중 | R1(상관 검증에 경로별 지연이 필요), `EOS-114`(next-problem 쿼리 실측과 합류 가능) | — |
| 코치 턴 도구 호출·지연 분포 실측(단순 턴/풀이 턴 분리) + 예산 정합 | R3 ①③④ | backend·L4 | 중 | `OPS-75`(재측정) 선행, 판정은 Kiki | — |
| WH-1 fast path(§5.3) 배선 — 기본 OFF, 애매하면 풀 루프 | R3 ② | backend·L4 | 중 | 위 실측 결과(단순 턴 비용이 유의할 때만). 설계는 있고 소유자가 없다 | — |
| 코치 대기 경험 설계(검증 후 부분 노출·진행 표시) | R3 교수학 축 | L4·mobile | 중 | `pedagogy-designer` | — |
| 클라이언트 값싼 개선 4종(미사용 왕복·토큰 캐시·입력창·sizeOf) | R4 | mobile | 소 | 없음 | ✅ `MOB-24` (P1) |
| next-problem 조회·처치 기록 분리 | R4 prefetch 전제 | backend·L2 | 중 | 추천 효과 분석 계약 검토 필요 | — |
| 클라이언트 흐름 구간 마커(F1~F4, 외부 전송 없음) | R5 1단계 | mobile | 소 | 없음 | — |
| SymPy 이벤트 루프 격리 + CPU 상한(타임아웃=판정 불가) | R6 | backend·L3 | 중 | 검증 권위 계약. 등재 시 ONNX(OCR)는 `ocr_enabled` 기본 OFF라 범위 밖으로 좁혔다 | ✅ `OPS-96` (P1) |

**12/31 내부 완성 기간에 권하는 최소 묶음**: R1 + R4(prefetch 제외) + R6. 셋 다 작고, 실사용자가 없어도 효과를 판정할 수 있다. R6은 성능이 아니라 가용성 결함이다. → 2026-09-25 Kiki 지정으로 이 3건을 등재했다. 등급은 셋 다 P1이다(12월 검증은 없어도 성립하지만 품질을 크게 높인다).

---

## 부록 A. 부재 판정에 쓴 검색 범위

"0건" 판정은 아래 검색으로 찾은 범위에 한정된다.

- **백엔드 계측**: `percentile`, `histogram`, `p75`, `p99`, `Server-Timing`, `X-Request-ID`, `prometheus`, `sentry`, `import opentelemetry`, `StreamingResponse`, `text/event-stream`, `EventSourceResponse` (`src/backend` 전체와 `pyproject.toml`)
- **CI**: `bench`, `perf`, `latency`, `p95`, `budget`, `pytest-benchmark`, `pytest-timeout` (`.github/workflows/*.yml` 6개 파일, dev 의존성)
- **테스트**: 파일명 `perf`, `bench`, `latency`, `budget`, `timeout`, `p95`, 그리고 `perf_counter`, `tracemalloc`, `cProfile`, 쿼리 카운트 이벤트 훅 (`tests/` 전체)
- **단계 배포**: `rollout`, `percent`, `cohort`, `staff`, `bucket`, `hash(user`, `allowlist` (`src/backend`)
- **클라이언트**: `Stopwatch`, `elapsedMilliseconds`, `Timeline`, `traceAction`, `watchPerformance`, `FrameTiming`, `addTimingsCallback`, `ShaderWarmUp`, `FlutterEngineCache`, `precacheImage`, `testGoldens`, `matchesGoldenFile`, `RepaintBoundary` (`src/mobile` 전체)
- **웹**: `web-vitals`, `useReportWebVitals`, `lighthouse`, `lhci`, `PerformanceObserver`, `performance.mark`, `speed-insights` (`src/web` 전체)
- **진단 목록 표시처**: `diagnoses`를 `src/mobile/lib/features/problems`·`src/mobile/lib/features/chat`에서 검색했다. 결과는 컨트롤러와 상태 정의뿐이다. 나 탭(`features/profile`)은 `meTabControllerProvider`의 별도 필드를 쓴다.

## 부록 B. 교차 확인 기록
- 조사 보조 에이전트 한 곳은 "코치는 정적 템플릿이라 LLM 0회, 스트리밍 우선순위 낮음"이라고 보고했다. `docs/architecture/ai_tutor_module_gap_review.md` §⑤·⑥ 행을 인용한 것이다. 코드로 확인한 결과는 **절반만 맞다.**
  - **맞는 부분**: 발화 본문은 여전히 결정론 템플릿이다. 프로즈 rephrase가 기본 OFF다.
  - **틀린 부분**: "LLM 0회"는 main `d5438782`와 다르다. `wh1_primary_enabled` 기본값이 True이고, `harness/wh1_primary.py`가 `LLMTutorPolicy`를 import해 **도구 선택마다 LLM을 부른다.**
  - 그래서 "스트리밍 우선순위 낮음"이라는 결론은 맞지만 이유가 다르다. 스트리밍이 필요 없는 이유는 LLM이 없어서가 아니라, **LLM 대기가 발화 생성이 아닌 도구 선택 루프에 있기 때문**이다(§2-C).
- 두 조사 보고의 핵심 주장 가운데 다음은 코드를 직접 열어 다시 확인했다.
  - `max_tool_calls=16`과 `asyncio.wait_for` 15초
  - Ollama `stream: False`와 `StreamingResponse` 0건
  - `ServiceMetrics.window_p95_latency_ms`
  - 진단 3연속 호출과 `diagnoses` 표시처 0건
  - `auth_interceptor`의 요청별 토큰 읽기
  - `mathlive.iife.js` 839,303바이트
  - 버블의 `MediaQuery.of(context).size`
  - next-problem의 처치 기록 쓰기
  - 기능 플래그 19개(ON 8, OFF 11)
- 줄번호를 인용한 나머지 세부(직렬 await 횟수 등)는 조사 보고 기준이며, 대략치로 읽는다.
