# WhyMath 상태 측정 (S1, 2026-11-08, 기준 커밋 b8904b77)

> 기준 커밋: main `b8904b77c5c0dbb6997fa785bb00194d8d5da56b` (P3-94 #1886). 이 커밋은 main의 마지막 CI 성공 run(#6859, 2026-11-08 07:51Z)과 같다.
> 지시서의 "사전 실측"은 `62bcbecc` 기준이다. 그 뒤 main에 커밋 4개가 더 들어왔다. 사전 실측과 값이 다른 곳은 각 답에 **[차이]**로 적었다.
> 측정 환경: 클라우드 세션(Linux, Python 3.13.18). Docker 데몬은 쓸 수 없었고, 로컬 PostgreSQL 16 + apt `postgresql-16-pgvector`로 대신했다. 이 문서는 코드를 한 줄도 바꾸지 않고 측정만 했다.

## 30분 테스트 결과: GP-2에서 끊김 — 중2 일차함수 문항이 데모 시드에 없어 출제되지 않는다 (소요 약 4분: 08:24:49 → 08:28:48 UTC)

**밟은 경로:** `scripts/demo/run_demo.sh`의 6단계를 같은 순서로 손으로 밟았다. 1단계(Docker Postgres)만 로컬 PG16(5432)으로 바꿨다.

| 단계 | 결과 | 근거 |
| --- | --- | --- |
| 서버 기동 | 됨 | `alembic upgrade head` exit 0(리비전 117개 적용) → `seed_demo.py` exit 0 → `uvicorn whymath_backend.app:create_app --factory` → `/health` `{"status":"ok"}` |
| GP-1 세션 시작 | 됨(닉네임이 아니라 데모 OAuth) | `GET /v1/auth/demo/state` → `POST /v1/auth/demo/callback` → `access_token` 발급 |
| **GP-2 문제 제시** | **끊김** | `GET /v1/me/next-problem` 200. 그러나 나온 문항은 고등 확률(`unit_codes=["PROB-INDEPENDENT-TRIAL"]`)이었다. DB `problem` 1,703행 중 일차함수(`LINEAR` 단원 코드 또는 본문 "일차함수")는 **0행**이다. `seed_demo.py`는 `problem_bank_v1`(4건)·`generated_v0`(619건)·`misconception_mc_v0`(1,080건)만 적재하고 `problem_bank_middle_function_v0`는 적재하지 않는다. 특정 단원을 고르는 요청 파라미터도 찾지 못했다 |
| GP-3 텍스트 답변 | (확률 문항으로 계속) 됨 | `POST /v1/coach/sessions` 201 → `dialogue_id` 발급. `POST /v1/coach/sessions/{id}/turns` 201 ×3 |
| GP-4 튜터 되묻기 | 형식만 됨 | 세 턴 모두 응답이 `"좋아, 지금까지 잘 하고 있어. 다음으로 가보자."`(`explanation_source=harness_template`)였다. 서버 로그: `LLMTutorPolicy provider 호출 실패 — 안전 강등(결정론 폴백): ConnectionError`. 이 환경에는 Ollama도 클라우드 키도 없다. 학생이 오개념("3번 연속 나왔으니 확률이 줄어드나요?")을 말해도 같은 칭찬 문장이 돌아왔다 |
| GP-5 정답 판정 | 안 됨(코치 경로 안) | 정답 텍스트 `5/11`과 `selected_choice_index=2`(정답 보기)를 보내도 `problem_complete=false`·`completed_attempt_id=null`이었다. 별도 `POST /v1/me/attempts`는 **`is_correct`를 클라이언트가 보내는 값**으로 받는다(필수 필드) — 서버 채점이 아니다 |
| GP-6 숙련도 갱신 | 안 됨 | `POST /v1/me/attempts`(`is_correct=true`) 201의 응답이 `mastery_updates=[]`·`coverage.concept="not_measured"`였다. `GET /v1/me/mastery`는 전후 모두 `[]`. 시드 로그: "개념 태깅 0건 · 개념 orphan skip 1,703건(원자 미적재)" |

**한 줄 결론:** 서버는 뜨고 문제·대화 API도 응답하지만, 목표 경로(중2 일차함수 → 소크라테스 대화 → 서버 판정 → 숙련도 갱신)는 GP-2에서 끊긴다. 다른 문항으로 이어 가도 GP-4는 LLM 없이 고정 문장이고, GP-5·GP-6은 코치 경로에서 일어나지 않는다.

## Q1~Q8 답

### Q1. 백엔드 프레임워크와 진입점
- FastAPI + uvicorn. 진입점 `src/backend/whymath_backend/app.py:990` `create_app`(uvicorn `--factory`). `requires-python = ">=3.12"`(`src/backend/pyproject.toml:5`). 사전 실측과 같다.
- 확인: `grep -n "def create_app" whymath_backend/app.py` · `grep -n requires-python pyproject.toml` · 실제 기동(위 30분 테스트).
- 참고: `pyproject.toml`의 `packages = ["whymath_backend"]`(176행) · `root_package = "whymath_backend"`(224행) · `testpaths = ["../../tests/backend"]`(521행).

### Q2. PostgreSQL 연결 설정과 테이블 수
- 설정: `whymath_backend/config.py:88` `Settings.database_url`(환경변수 `WHYMATH_DATABASE_URL`). 세션: `whymath_backend/db/session.py`의 `get_engine`(39행)·`get_sessionmaker`(64행)·`get_session`(82행)·`dispose_engine`(101행).
- 테이블 수: ORM `__tablename__` **86개**(`db/models/` 61파일). `alembic upgrade head` 뒤 실제 DB `public` 스키마 BASE TABLE **87개**(86 + `alembic_version`).
- 확인: `grep -rhoE "__tablename__ *= *['\"][a-z_0-9]+" whymath_backend/db/models/ | sort -u | wc -l` → 86 · `psql -c "select count(*) from information_schema.tables where table_schema='public' and table_type='BASE TABLE'"` → 87.
- **[차이]** Alembic 리비전은 `alembic/versions/*.py` **117개**다(사전 실측 116). `upgrade head`에는 pgvector 확장이 필요하다 — 확장이 없으면 19번째 리비전에서 `extension "vector" is not available`로 멈춘다(실측).

### Q3. 튜터 LLM 호출 위치와 모델
- 학생 대면 경로: `api/coach.py`의 `POST /v1/coach/sessions`(`create_session`, 3536행)·`POST /v1/coach/sessions/{dialogue_id}/turns`(`append_turns`, 4025행) → `harness/wh1_primary.py:394`에서 `LLMTutorPolicy(...)` 생성 → `harness/wh1_llm_policy.py:166` `LLMTutorPolicy.next_action`(338행) 안의 `self._seam.generate(self._routing_request(), prompt, _SYSTEM_PROMPT)`(350행).
- 프로바이더 조립: `app.py:1116` `CompositeProvider(local=OllamaProvider(), cloud=build_cloud_provider(settings_for_app))`. 팩토리 `l3/providers/factory.py:52` `build_cloud_provider(settings)`. 인터페이스 `l3/interfaces.py:19` `LLMProvider.generate(prompt, system, decision, *, ...)` — **세 번째 인자로 `RoutingDecision`(`l3/models.py:228`)이 필수**이고, 라우터 `l3/router.py:860` `Router.route(RoutingRequest)`가 그것을 만든다.
- 모델: `config.py` `cloud_provider` 기본 `"openrouter"`(794행) · `openrouter_model_mid` 기본 `"deepseek/deepseek-v4.1-flash"`(900행) · `anthropic_api_enabled`(692행) · `ollama_host`(68행). 사전 실측과 같다.
- 실측 동작: 이 환경에서는 LLM이 없어 `ConnectionError` → 결정론 폴백 문장(30분 테스트 GP-4).
- 확인: `grep -rn "LLMTutorPolicy(" whymath_backend` · `grep -n "CompositeProvider(\|build_cloud_provider" whymath_backend/app.py` · `uvicorn` 로그.

### Q4. 문항 데이터 위치·형식·중2 일차함수 수
- 위치·형식: `data/corpus/problem_bank_*/problems.jsonl`(한 줄 = JSON 객체 1개). **[차이]** 폴더 **40개**(사전 실측 39).
- 중2 일차함수: `data/corpus/problem_bank_middle_function_v0/problems.jsonl` **200건**. 전부 `unit_codes=["LINEAR-FUNC-VALUE"]` · `achievement_standard_codes=["[9수02-14]"]` · 본문 "f(k)를 구하시오" 한 유형(200/200) · 정답 정수 문자열(200/200) · `license=WHYMATH_GENERATED` · `is_published=False`. 예: `"일차함수 f(x) = -3x + 3에 대하여 f(5)를 구하시오."` · `answer "-12"` · `verify.conditions "(-3*x + 3).subs(x, 5) = y"` · `verify.answer_map {"y":"-12"}`. 성취기준 필드 이름은 `achievement_standard_codes`다.
- 다른 유형: 기울기·절편·그래프·식 세우기 유형의 **중2** 문항은 0건. **[차이]** 지시서의 `grep -l "기울기\|절편" data/corpus/*/problems.jsonl`은 0건이 아니라 **5개 파일**을 낸다(`coordinate_geometry_v0` 200건 `LINE-EQUATION`, `generated_v0`·`rephrased_v0` 각 40건 `CALC-TANGENT`, `p3_calculus1_diff_v0` 75건, `p3_fill_v0` 6건). 단원 코드로 보면 전부 고등(직선의 방정식·접선·미분)이다.
- 데모 DB 적재 여부: `seed_demo.py`는 이 은행을 적재하지 않는다(30분 테스트 GP-2).
- 확인: `wc -l`, Python으로 `unit_codes`·`achievement_standard_codes`·`license`·`is_published` 집계, 위 grep.

### Q5. Flutter 앱 폴더와 API 클라이언트
- `src/mobile/`. 진입 `lib/main.dart`, 라우트 `lib/core/router.dart`(go_router), API 클라이언트 `lib/core/api_client.dart:53` `dioProvider`, 베이스 URL `lib/core/env.dart`(`API_URL`, 기본 `http://localhost:8000`). `pubspec.yaml`: Dart `sdk: ^3.11.0` · `flutter_riverpod ^3.0.0` · `go_router ^14.0.0` · `dio ^5.4.0` · `flutter_math_fork ^0.7.4`. `lib/` 안 `.dart` 75개. CI `flutter-version: "3.41.9"`(ci.yml 1263행). 사전 실측과 같다.
- 확인: `ls lib/...` · `grep -n dioProvider lib/core/api_client.dart` · `grep -n API_URL lib/core/env.dart` · `grep pubspec.yaml`.
- 이 클라우드 환경에는 Flutter SDK가 없어 앱은 빌드·실행하지 않았다.

### Q6. 테스트 수·마지막 CI 통과 커밋·CI 설정 경로
- 테스트 파일: `tests/backend` `test_*.py` **1,114개**. **[차이]** 사전 실측 1,109.
- 테스트 건수: **26,649건 수집**(`cd src/backend && python -m pytest --collect-only -q` exit 0, 11.6초).
  - **[차이]** 지시서 명령 `python -m pytest --collect-only -q ../../tests/backend`는 **exit 4**로 거부된다. 경로를 인자로 주면 rootdir이 저장소 루트로 잡혀 `asyncio_mode`가 읽히지 않는 것을 저장소 가드(OPS-61)가 막는다. 그래서 CI처럼 경로 없이 불렀다.
  - 처음에는 `ModuleNotFoundError: No module named 'data_pipeline'`로 10개 파일이 수집 오류였다. `pip install -e src/data-pipeline` 뒤 0건.
- 마지막 CI 통과 커밋: main `b8904b77`(CI run #6859, conclusion success, 2026-11-08 07:51Z~08:13Z). 확인: GitHub Actions `list_workflow_runs`(ci.yml · branch main · event push · completed).
- CI 설정: `.github/workflows/ci.yml`. **[차이]** 잡은 **24개**다(사전 실측 26). `grep -E '^  [a-z][a-z0-9-]*:$'`은 26줄을 내지만 그중 `push`·`schedule` 2줄은 `on:` 아래 트리거다. 잡 목록: changes · data-pipeline · backend · backend-pytest-1/2/3 · backend-verdict · backend-migrations · data-pipeline-integration · data-pipeline-neo4j · mobile · concept-reach-guard · web · webapp · infra-contracts · docker-build · infra-shell · policy-guard · harness-integrity · declared-unwired-audit · corpus-authoring · e2e-nightly · backend-serial-nightly · constraints-freshness.
- PR 템플릿 `.github/pull_request_template.md`: "무엇을·왜 / 검증 / 변별력 / 정직한 공백 / 영향 범위·롤백" 5절(사전 실측과 같다).
- `tests/golden/`은 없다(사전 실측과 같다).

### Q7. 진입점에서 도달 가능한 모듈 수 / 전체 모듈 수
- 전체: `whymath_backend` 모듈 **839개**(grimp, 패키지 `__init__` 포함).
- `whymath_backend.app`이 직간접으로 import하는 모듈: **410개(48.9%)**. 학생 대화 라우트 `whymath_backend.api.coach`만 보면 **228개(27.2%)**. 프로바이더 팩토리 `l3.providers.factory`는 13개만 끌고 온다.
- 하위 패키지별 도달(app 기준): api 54/56 · l2 39/41 · schema 49/55 · db 51/66 · l4 70/100 · l3 71/166 · l1 24/93 · **harness 12/163** · **ops 4/38** · **whs 0/14** · l6 18/18 · l5 7/10.
- 해석 범위: grimp는 정적 import 문만 본다. CLI 스크립트·`importlib` 동적 로딩은 포함하지 않는다. Flutter 화면에서 시작하는 그래프는 Dart 쪽이라 세지 않았다(모름).
- 확인: `cd src/backend && python -c "import grimp; g=grimp.build_graph('whymath_backend'); print(len(g.modules)); print(len(g.find_upstream_modules('whymath_backend.app')))"`.
- 방향 메모: 지시서는 `find_downstream_modules`/`find_upstream_modules` 둘 다 적었다. grimp에서 "app이 import하는 모듈"은 `find_upstream_modules`이고, `find_downstream_modules('whymath_backend.app')`(app을 import하는 쪽)는 4개다.

### Q8. 최근 머지된 PR 20개의 변경 모듈이 Q7 도달 집합에 드는 비율
- 대상: `git log --first-parent -20 --name-only origin/main -- src/backend` → 커밋 20개(`7aff135c` ~ `843ceaec`).
- 결과: 커밋별로 바꾼 `whymath_backend` 모듈 57건 중 **19건(33.3%)**이 app 도달 집합(410)에 든다. 20개 커밋 중 도달 모듈을 1개라도 건드린 커밋은 **9개(45%)**이고, 11개는 도달 밖 모듈(harness·ops·측정 CLI 등)만 바꿨다.
- 주의: 이 클론은 얕은 클론이라, 처음 실행에서는 커밋이 14개만 나오고 경계 커밋이 838모듈을 "추가"한 것으로 보였다. `git fetch --deepen=200 origin main` 뒤 다시 계산한 값이 위 숫자다.
- 확인: 위 `git log` 출력을 Python으로 `src/backend/whymath_backend/**/*.py` → 모듈 이름으로 바꿔 Q7 집합과 대조.

## 골든 패스에 바로 쓸 수 있는 것 (import 후보, 파일 경로 포함)

1. **LLM 프로바이더 팩토리** — `src/backend/whymath_backend/l3/providers/factory.py` `build_cloud_provider(settings)`(52행). 반환 타입 `l3/interfaces.py` `LLMProvider`. 이 모듈이 끌고 오는 import는 13개뿐이다. `generate`는 `RoutingDecision`(`l3/models.py:228`)을 요구하며 `l3/router.py` `Router.route`가 만든다. 학생 대면 서빙의 조립 예는 `app.py:1116`(`CompositeProvider(local=OllamaProvider(), cloud=build_cloud_provider(...))`).
2. **중2 일차함수 문항 jsonl** — `data/corpus/problem_bank_middle_function_v0/problems.jsonl` 200건(필드 `problem_id`·`question_text`·`answer`·`answer_format`·`achievement_standard_codes`·`verify`). 한 유형뿐이다(Q4).
3. **SymPy 답 검산** — `src/backend/whymath_backend/l3/verify_answer.py:339` `verify_answer(conditions, answer_map, *, tol=1e-9)`. 위 jsonl의 `verify.conditions`를 그대로 받는다. 실측: `"(-3*x + 3).subs(x, 5) = y"`에 `{"y": "-12"}`·`"-24/2"`·`"-12.0"` → `pass`, `"-11"` → `fail`.
4. **DB 연결** — `src/backend/whymath_backend/db/session.py` `get_engine`·`get_sessionmaker`·`get_session`, 설정 `config.py` `Settings.database_url`(`WHYMATH_DATABASE_URL`).
5. **설정 객체** — `src/backend/whymath_backend/config.py` `Settings`(`cloud_provider`·`openrouter_model_mid`·`ollama_host`·`anthropic_api_enabled`).
6. **Flutter 기반** — `src/mobile/lib/core/api_client.dart` `dioProvider`, `lib/core/env.dart` `API_URL`, LaTeX 렌더 `flutter_math_fork`(이미 `pubspec.yaml`에 있음).

## 골든 패스에 쓰려면 고쳐야 하는 것

- **문항 공급:** `scripts/demo/seed_demo.py`가 일차함수 은행을 적재하지 않는다. 기존 `GET /v1/me/next-problem`은 단원 지정 없이 IRT·후보 풀로 고르며 일차함수를 낼 수 없다(DB 0행).
- **문항 유형:** 일차함수 200건이 전부 "f(k) 구하기" 한 유형이다. 기울기·절편·그래프·식 세우기 유형은 0건이다. 30문항을 같은 유형으로 채울지 다른 유형을 저작할지는 S3의 판단이 필요하다.
- **튜터 응답:** LLM이 없으면 `LLMTutorPolicy`가 학생 발화와 상관없이 같은 칭찬 문장을 낸다(오개념 발화에도 "잘 하고 있어"). 이 문장은 소크라테스 되묻기가 아니다.
- **서버 정답 판정:** 코치 세션은 정답 텍스트·정답 보기를 받아도 문제를 완료로 처리하지 않았다(`problem_complete=false`). `POST /v1/me/attempts`는 정오를 클라이언트가 보낸 `is_correct`로 받는다.
- **숙련도 갱신:** 기존 숙련도는 개념 태깅에 의존한다. 데모 시드에서는 개념 태깅 0건이라 `mastery_updates=[]`였다.
- **세션 시작:** 기존 경로는 데모 OAuth(state → callback → JWT)다. 닉네임만으로 시작하는 경로는 없다.
- **로컬 기동 전제:** `alembic upgrade head`에 pgvector 확장이 필요하다. 이 클라우드 환경에서는 Docker가 돌지 않아 `run_demo.sh`를 그대로 쓸 수 없었다. 백엔드 테스트 수집에는 `src/data-pipeline` 설치가 필요하다. Redis가 없으면 캐시 강등 로그가 나지만 요청은 계속된다.

## 당장은 필요 없는 것 (한 줄씩, 삭제 아님)

- `whymath_backend/harness/`(163모듈, app 도달 12) — 측정·저작·검수 도구.
- `whymath_backend/ops/`(38모듈, app 도달 4) — 운영 지표·수집기.
- `whymath_backend/whs/`(14모듈, app 도달 0) — WH-S 솔버 하네스.
- `whymath_backend/l3/equivalent/`의 단원별 `*_skeleton_generator.py` — 문항 생성기(골든 패스는 고정 30문항).
- L2 학습자 모델(BKT·IRT·`next-problem` 선택 로직) — 골든 패스 숙련도는 +0.10/−0.05 한 줄.
- 오개념 카탈로그·매칭(`misconceptions`·`active_hypotheses` 응답 필드).
- OCR·멀티모달(`/v1/ocr` 계열, `qwen3-vl`), 시각화.
- 관리자 CMS·검수 큐(`/v1/admin/*`) — OpenAPI 경로 149개 중 상당수.
- 데모 OAuth·JWT·refresh 토큰 경로.
- Langfuse·Redis·관측 계열.
- `data/corpus/`의 나머지 문제은행 39개.
- Flutter의 기존 화면(온보딩·홈·채팅·탐색·OCR·수식 입력 등 `lib/core/router.dart`의 라우트들).
