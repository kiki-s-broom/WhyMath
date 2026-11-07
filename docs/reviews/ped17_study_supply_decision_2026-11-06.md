# P3R-01_PED-17_학습단계404_생성폴백결정 — 학습 공급 경로 판정 대응 기록

판정 기준: main `ce8c2165` · 작성일 2026-11-06 · 작성: Claude(PED-17 소유 세션) · 대상 태스크: `backlog/tasks/PED-17-study-generate-fallback-decision.yaml`

## 0. 이 문서가 결정 요청이 아닌 이유

지시문은 이 세션이 선택지 (가) 생성 폴백 개방 / (나) 비개방 확정 / (다) 대안을 문서로 만들고 결정 게이트 `G-ped17-study-supply-route`를 등재하도록 계획했다(지시문 작성 기준 main `2a694f71`).
그 뒤 같은 날 Kiki가 이 결정을 이미 내렸다 — C안(조건부 개방) 채택(정본 `ped17/산출물/T0/결정기록.md` · PR #1857 · main `b74dc2c6`).
그래서 이 세션은 같은 질문으로 결정 게이트를 새로 열지 않는다. 대신 대장 acceptance ⑤가 "후속 작업이 한다"고 남긴 두 판정 — ①의 (a)/(b) 대응, CONT-05 연동 항(UNREVIEWED) — 을 이 문서에서 C안에 비추어 적는다.
해석이 Kiki 의도와 다르면 Kiki가 이 문서를 정정한다. 그 경우에만 결정 게이트가 필요하다.

## 1. 대응 판정

| 질문 | 판정 | 근거(C안 결정 기록) |
| --- | --- | --- |
| ① (a) 요청 시점 생성 폴백 개방(`supply()`에 `generate_request`·`provider`·`trace` 주입) | **채택하지 않는다** | 안전장치 1 "학생이 눌러서 생성하지 않는다. 배치로 만들고 검증한 뒤 합격본만 저장한다" — 요청 시점 LLM 생성과 정면으로 어긋난다 |
| ① (b) 비개방 확정·404 유지 | **채택하지 않는다** | 채택안 "나머지는 404 대신 '준비 중' 안내"(작업 C1) · 목표 "Gate A와 Q1을 12/31 전에 통과" |
| 그러면 무엇인가 | **(다) 계열 — 사전 생성·검증·저장 경로** | 안전장치 7가지 + B6 `can_publish` 관문을 통과한 합격본만 공개 상태로 저장되고, `/study`는 그 저장본을 읽어 서빙한다. 생성은 학생 요청 경로 밖(배치)에서 일어난다 |
| CONT-05 연동: UNREVIEWED(검수 전 행 있음)도 생성 대상인가 | **대상이다 — 단, 학생 요청 시점 생성이 아니라 사전 생성 대상** | 결정 요약 "검수 안 된 개념은 AI가 미리 생성하고 자동 검증을 통과한 것만 단계적으로 공개" — 대상은 '검수 안 된 개념' 전체(UNREVIEWED 1,720 · NO_DSL 963 · PR #1859 T1 실측)이고, 1차 범위는 그중 SymPy 기계 검산 가능 개념(작업 A2) |
| KG-02 보류(사람 검수 2027 이후)를 건드리는가 | **건드리지 않는다** | C안은 사람 서명 승격(`review_status="reviewed"`)이 아니라 별도 공개 상태(작업 A1: 초안·검증됨·공개됨·회수됨)로 연다. `G-kg02-review-promotion-llm-session`은 그대로다 |

## 2. 결과로 바뀌는 PED-17 acceptance 읽기

- **①**: (a)/(b) 어느 쪽도 아닌 (다) 계열로 확정. 이행은 C안 계획 작업(T1→A1~A3→B0~B7→C1~C5→D1~D7)이 맡는다. PED-17 ①은 그 경로의 마지막 배선 — `/study`가 B6 관문을 통과한 공개본을 읽게 하는 연결 — 이 main에 들어오고, 공개본이 있는 개념에서 404→응답, 공개본을 회수하면 404(또는 C1 "준비 중")가 재현되는 양방향 실측으로 닫는다.
- **②**: 이 세션에서 구현(아래 §3). 판정과 무관하며 학생 응답을 바꾸지 않는다.
- **③**: 변화 없음(클라이언트 배선 MOB-13은 범위 밖).
- **CONT-05 연동 항**: §1 표 4행으로 판정.
- **Gate A 하네스**(`tests/backend/api/test_release_gate_a_chain.py`): 학습 단계가 열리는 커밋에서 `_GAP_OWNERS["학습"]="PED-17"` 동결과 `test_study_break_is_the_known_content_gap`가 RED가 된다. 그 커밋이 "학습 도달"을 단언하는 형태로 바꾼다(지우지 않는다).

## 3. acceptance ② — SupplyTally 학생 수신 축

문제: `supply()`에서 생성 인자가 없어 폴백을 건너뛴 결과(학생 404)와 실제 생성(학생 수신)이 같은 (`content_source="generate"`, 전략, 폴백 사유) 키로 합산됐다. 회계만 보면 "생성했다"와 "아무것도 못 줬다"가 같았다.

변경(`src/backend/whymath_backend/l4/content_supply.py`):

- `SupplyResult.served` — 렌더 결과나 생성 본문이 있으면 True. 저장 필드가 아니라 산출물에서 유도한다.
- `SupplyTally.record(..., served=...)` + 축 2개: `by_served`(`served`·`unserved`), `unserved_by_source`(경로별 미수신 건수). 비율 `served_rate`와 Wilson 하한 `served_rate_lower`. 모르는 기록(`served=None`)은 분모에서 뺀다(미상 ≠ 0%).
- `supply()`의 기록 3곳이 모두 `served`를 넘긴다. `to_json()`·`reset_process_tally()`에 새 축 반영.
- `api/study.py` 공급 로그 1줄에 `served`·`served_rate` 추가(응답 무변경).

`content_source` 값을 쪼개지 않은 이유: `l2/pedagogy_evidence`·`ops/cost_report`·`l3/trace/langfuse_sink`·`api/study.py` 응답 스키마가 그 값을 읽는다. 값을 바꾸면 소비처 계약이 함께 바뀐다. served 축은 기존 키를 그대로 두고 수신 여부만 더한다.

검증(이 세션 실측 · 브랜치 `claude/new-session-yfujem`):

- `TestSupplyTallyServedAxis` 5건: 기존 세 축이 두 경로에서 같은 값을 낸다는 전제를 먼저 단언하고, served 축만 둘을 가른다는 것을 보인다. 대조군(렌더 성공 = 수신) 포함.
- 뮤테이션 3종 — ⓐ 건너뛴 경로를 `served=True`로 기록 ⓑ 건너뛴 경로에서 `served` 인자 제거 ⓒ `served`가 항상 True — 전부 RED(각 1 failed). 주입 적용 확인(원본과 다름), 원복은 `cmp`로 바이트 동일, 원본 GREEN(5 passed).

한계: `study.py`는 지금 `rendered`만 학생에게 내보낸다. 생성 본문(`text`)이 생겨도 `/study`는 404다. 사전 생성 경로가 `rendered` 형태로 서빙되지 않으면, 공급 층의 `served=True`와 API 층의 실제 응답이 어긋날 수 있다. 공개본 배선 작업이 이 둘을 맞춰야 한다.

## 4. 기준선 실측 (Gate A 하네스)

- 명령: `WHYMATH_RUN_INTEGRATION=1 WHYMATH_DB_DISABLE_POOL=1 python -m pytest -c src/backend/pyproject.toml --rootdir=src/backend tests/backend/api/test_release_gate_a_chain.py -s`
- 환경: PostgreSQL 16.15 + pgvector(로컬 클러스터) · `alembic upgrade head` exit 0 · Python 3.12 · CI 제약 파일 `infra/ci/constraints-py312.txt`
- 결과: exit 0 · 51 passed · 1 xfailed · `GATE_A_CHAIN_VERDICT :: 도달=9/10 · 끊김=학습(PED-17) · 봉인위반=0 · Gate A=FAIL`
- 기준: main `ce8c2165` + 이 브랜치의 회계 변경(학생 응답 무변경이라 판정에 영향 없음)

## 5. Kiki께 알릴 점 (결정 요청 아님)

1. **범위 규율과의 긴장**: C안은 AI 감사관·AI 학생 에이전트·AI 릴리스 에이전트를 둔다. Phase 3 범위 규율은 "새 AI Agent"를 Release Blocker 예외로만 허용한다. 학습 단계 404는 Gate A를 막는 Release Blocker라 예외에 들어간다고 읽히지만, 이 해석을 C안 작업이 착수 전에 명시해 두는 편이 안전하다.
2. **교차 검증 좌석**: 안전장치 4(생성 모델과 다른 모델 2개)는 ARCH-66(2026-12-31까지 Anthropic API 중단) 아래에서 로컬 Ollama 계열 + OpenRouter 좌석으로만 채울 수 있다. 서로 다른 계열 3개를 확보할 수 있는지는 B4 작업이 실측해야 한다.
3. **위 §1 해석**이 의도와 다르면 이 문서를 정정해 달라. 그때 게이트를 연다.
