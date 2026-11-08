# WhyMath 골든 패스 스켈레톤 — 작업 지시서 (AI 실행용 · 학생 없는 변형)

작업 번호를 받은 AI는 이 문서의 공통 규칙·용어·공유 계약과 해당 번호의 지시만 읽고 작업한다. 지시에 없는 값은 추정하지 않고 "미확인"으로 보고한다. 원본 계획서는 `golden/prompts_src/plan_golden_path_3weeks.html`(2026-11-08 · Kiki)이다. **이 변형은 실제 중학생을 섭외하지 못했을 때 쓰는 묶음**이다 — S1~S8은 원본(`spec.md`)과 글자 그대로 같고, 검증 구간(S9~S12)만 본인·AI 시뮬레이션·성인으로 대체했으며 S13·S15의 집계·판정 문구를 그에 맞게 고쳤다. 실제 학생이 1명이라도 구해지면 원본 묶음 `golden/prompts/`의 S9 지시문으로 갈아탄다.

## 공통 규칙과 보고 형식

**공통 규칙**

1. (스크립트가 "읽을 범위" 표준 문장으로 바꾼다)
2. (스크립트가 "선행 작업 확인" 표준 문장으로 바꾼다)
3. **golden/ 바깥은 읽기 전용:** 새 코드는 저장소의 `golden/`(백엔드 파이썬은 `src/backend/golden/`, Flutter는 `src/mobile/lib/golden/`, 테스트는 `tests/golden/`)에만 쓴다. 옛 코드를 고쳐야 돌아가면 고치지 말고 `golden/` 아래로 복사해서 고치고, `golden/HARVEST.md`에 "가져온 것 / 버린 것 / 이유" 한 줄을 적는다. **예외는 S2 한 세션의 "배선 파일" 4개뿐**이다 — ①`CLAUDE.md` 맨 위 블록 ②`.github/workflows/ci.yml` ③`.github/pull_request_template.md` ④`src/backend/pyproject.toml`의 `packages`·`[tool.importlinter]`. `src/mobile/pubspec.yaml`은 어떤 세션도 건드리지 않는다(새 패키지 추가 금지). `constitution/` 폴더는 어떤 세션도 건드리지 않는다(가드 훅이 막는다. 막히면 우회하지 않고 멈춘다).
4. **범위 고정:** 중2 일차함수 1단원·문항 30개·학생 경로 GP-1~GP-6·HTTP 엔드포인트 3개(`POST /golden/session`, `GET /golden/next`, `POST /golden/answer`)가 전부다. 네 번째 엔드포인트, 새 추상화(베이스 클래스·인터페이스·플러그인 구조), 지식 추적(BKT), OCR, 의도 분류, 다과목, 회원가입·인증, 옛 코드 리팩토링·삭제는 제안하지 않는다. 떠오르면 `golden/LATER.md`에 한 줄 적고 넘어간다. "이왕 하는 김에"라는 생각이 들면 그 자리에서 멈추고 보고한다.
5. **완료 기준은 tests/golden 초록:** 코드를 건드린 세션은 끝날 때 `cd src/backend && python -m pytest ../../tests/golden`을 돌리고 **exit code**로 판정한다(`-q`·`| tail`로 출력을 줄이지 않는다). 빨간불이면 PR을 만들지 않는다. 유일한 예외는 S2다(S2는 빨간불이 성공이다).
6. **모르는 값은 추정 금지:** 경로·테이블·함수 이름처럼 지시에 없는 값은 먼저 저장소에서 찾는다. 이 문서의 "사전 실측(2026-11-08·main `62bcbecc`)" 값도 세션에서 다시 확인하고, 다르면 보고에 적는다. 못 찾으면 "미확인"으로 적고 그 부분만 멈춘다.
7. **검증은 CI와 같은 명령으로:** 백엔드 CI 잡이 쓰는 정적 검사 4종을 `src/backend`에서 그대로 돌린다 — `python -m ruff check . ../../tests/golden`, `python -m black --check --line-length 100 . ../../tests/golden`, `python -m mypy --strict golden`, `lint-imports`. Flutter를 건드렸으면 `src/mobile`에서 `flutter analyze`와 `flutter test`를 돌린다. 판정은 항상 exit code이며 보고에 숫자(통과 N건·소요 시간)를 적는다.
8. **LLM 호출 규칙:** 튜터의 LLM 호출은 옛 코드의 프로바이더 팩토리(`whymath_backend.l3.providers.factory.build_cloud_provider()` → `LLMProvider.generate`)를 통해서만 한다. SDK 직접 호출·API 키 하드코딩 금지. 2026-12-31까지 Anthropic API는 사용 중단이라 기본 클라우드 좌석은 OpenRouter(`deepseek/deepseek-v4.1-flash`)이고, 로컬은 Ollama(`qwen` 계열)다. **테스트와 CI는 실제 LLM을 부르지 않는다** — 환경변수 `GOLDEN_FAKE_LLM=1`이면 고정 문장을 돌려주는 가짜 프로바이더를 쓴다.
9. **미성년자 데이터:** 학생 식별자는 닉네임 문자열뿐이다. 실명·학교·학년·연락처는 어디에도 저장하지 않는다. 대화 로그는 로컬 PostgreSQL(`golden` 스키마)에만 쌓고, LLM에는 문제 본문과 학생이 친 텍스트만 보낸다(닉네임·세션 ID 제외). 학생 세션 전에는 보호자 동의를 받는다(Kiki 담당). 이 변형의 대체 피험자(본인·AI·성인)에게도 같은 저장 규칙을 적용한다 — 성인 지인의 실명도 저장하지 않는다.
10. **하네스·커밋·PR:** 코드나 문서를 바꾸는 세션은 첫 행위로 `python3 scripts/harness/backlog.py start <태스크 ID>`를 실행한다. 태스크 ID는 S2가 `backlog.py add`로 받아 `golden/STATE.md` 맨 아래에 적어 둔 것을 쓴다(번호를 눈으로 짓지 않는다. S1은 문서만 만들므로 claim 없이 진행). 커밋 메시지는 `S<번호>: <한 줄>` 형식(예: `S4: golden/api.py 엔드포인트 3개`). 작업이 끝나면 PR을 열고, PR 본문 첫 질문 "이 PR이 전진시키는 학생 단계"에 GP 번호를 적는다. 적을 수 없으면 PR을 만들지 않고 이유를 보고한다. main 머지는 Kiki가 한다.
11. **한국어:** 코드 주석·문서·보고는 한국어로 쓴다(식별자는 영어).
12. **종료 보고 5줄:** 완료 보고 형식 외에 다음 5줄을 답변 끝에 반드시 쓴다 — ①완료 기준 충족 여부(아니오면 어디까지) ②tests/golden 결과(초록/빨강·테스트 N개) ③HARVEST.md에 오늘 추가한 줄 ④LATER.md에 오늘 추가한 줄 ⑤오늘 범위 밖으로 나가려다 멈춘 순간.

**완료 보고 형식**

```
작업 번호: S4
결과: 완료 | 일부 완료 | 중단
만든 것: 파일·테이블·화면 이름 (경로 포함)
완료 기준 확인: 항목별 통과/실패와 근거 (실행한 명령 또는 본 화면)
미확인·가정한 것: 없으면 "없음"
다음 작업이 알아야 할 것: 없으면 "없음"
```

**용어**

| 용어 | 뜻 |
| --- | --- |
| 골든 패스 | 학생이 앱을 켜서 문제 하나를 끝까지 푸는 핵심 경로 1개. GP-1 세션 시작 → GP-2 문제 제시 → GP-3 답변 입력 → GP-4 튜터 응답(최대 3턴) → GP-5 정답 판정 → GP-6 숙련도 갱신 → 다시 GP-2 |
| 스켈레톤 | 그 경로를 최소 코드로 끝까지 잇는 뼈대. 못생겨도, 하드코딩이어도 된다 |
| 수확 장부 | `golden/HARVEST.md`. 옛 코드에서 무엇을 가져왔고 무엇을 버렸는지 한 줄씩 적는 표(열: 가져온 것 / 버린 것 / 이유 / 세션) |
| STATE.md | `golden/STATE.md`. S1이 만드는 저장소 상태 측정 문서. 이후 모든 세션이 작업 전에 읽는다 |
| LATER.md | `golden/LATER.md`. 지금 하지 않을 아이디어를 한 줄씩 적는 곳. 길어지는 것이 정상이다 |
| 스트랭글러 피그 | 옛 시스템을 한 번에 갈아엎지 않고, 새 경로를 옆에 세운 뒤 트래픽을 옮겨 옛 것이 말라 죽게 하는 방식. 여기서는 `golden/`이 새 경로, 옛 코드는 import만 당하는 쪽 |
| 파사드 | 사용자가 들어오는 입구. 여기서는 Flutter 진입점 `lib/main_golden.dart`와 FastAPI 앱 `golden.api:app` |
| 배선 파일 | S2만 고칠 수 있는 `golden/` 바깥 파일 4개(공통 규칙 3번 목록: CLAUDE.md·ci.yml·PR 템플릿·pyproject.toml) |
| tutor_turn / graded | `POST /golden/answer`의 두 가지 응답 종류. tutor_turn은 튜터의 되묻기(아직 판정 안 함), graded는 정답/오답 판정과 숙련도 |
| 숙련도(mastery) | 0.0~1.0 숫자 하나. 맞으면 +0.10, 틀리면 −0.05, 범위를 벗어나면 잘라낸다(clamp). 시작값 0.0 |
| 작업 세션 / 학생 세션 | 작업 세션은 이 지시문으로 여는 AI 세션(S1~S15). 학생 세션은 실제 중학생이 앱으로 문제를 푸는 20분 |
| 대체 피험자 | 실제 중학생 대신 로그를 만드는 세 출처 — 본인(Kiki, 닉네임 `self-*`), AI 시뮬레이션 학생(LLM이 오개념 페르소나를 연기, 닉네임 `sim-*`), 성인 지인(닉네임 `adult-*`). 집계는 항상 출처별로 나눈다 |
| 페르소나 | AI 시뮬레이션 학생에게 주는 역할 지시 1건(어떤 오개념을 가졌고 어떤 말투로 답하는지). S11이 3종을 정의한다 |
| 하네스 | `scripts/harness/backlog.py`. 이 저장소의 작업 대장. 코드 변경은 `start`(claim)로 시작하고 `done`에 PR 증적이 필요하다 |
| 사전 실측 | 이 지시서를 쓰며 2026-11-08에 main `62bcbecc` 기준으로 직접 확인한 값. 세션에서 재확인한다 |

**공유 계약**

아래 모양은 S3~S8이 전부 같이 쓴다. 바꿔야 한다고 판단하면 바꾸지 말고 보고에 "계약 변경 제안"으로 적고 멈춘다.

*저장소 사실(사전 실측 2026-11-08 · main `62bcbecc`)*

| 항목 | 값 |
| --- | --- |
| 저장소 | `github.com/kiki-s-broom/whymath` · 기본 브랜치 `main` · Kiki 머신 경로 `C:\Users\kiki\Desktop\__AI\WhyMath`(Windows PowerShell) · 클라우드 세션 경로 `/home/user/WhyMath` |
| 백엔드 | Python 3.12 + FastAPI. 패키지 `src/backend/whymath_backend/`, 앱 팩토리 `whymath_backend.app:create_app`(uvicorn `--factory`), 설정 `src/backend/pyproject.toml`(`packages = ["whymath_backend"]`, `[tool.importlinter] root_package = "whymath_backend"`, pytest `testpaths = ["../../tests/backend"]`). CI 백엔드 잡은 `working-directory: src/backend` |
| DB | PostgreSQL 16(pgvector/pg16 이미지). 연결은 환경변수 `WHYMATH_DATABASE_URL`(`postgresql+asyncpg://...`), SQLAlchemy 비동기(`whymath_backend/db/session.py`의 `get_engine`·`get_sessionmaker`·`get_session`). Alembic `src/backend/alembic/`(리비전 116개). Kiki 머신 docker: prod `whymath-pg` 5433 · 시연 `whymath-demo-db` 55432 · 파일럿 5434. CI pytest 잡은 Postgres 서비스 컨테이너 + `WHYMATH_DATABASE_URL=postgresql+asyncpg://whymath@127.0.0.1:5432/whymath` |
| LLM | 라우터 `whymath_backend/l3/router.py`(`Router.route`), 프로바이더 팩토리 `whymath_backend/l3/providers/factory.py`(`build_cloud_provider(settings)`), 인터페이스 `whymath_backend/l3/interfaces.py`(`LLMProvider.generate`). 설정 `config.py`의 `cloud_provider`(기본 openrouter)·`openrouter_model_mid`·`ollama_host`·`anthropic_api_enabled=False` |
| 문항 자산 | `data/corpus/problem_bank_middle_function_v0/problems.jsonl` 200건 — 전부 `unit_codes=["LINEAR-FUNC-VALUE"]`, 성취기준 `[9수02-14]`, "일차함수 f(x)=ax+b에 대하여 f(k)를 구하시오" **한 유형**, 정답은 정수 문자열, `verify.conditions`에 SymPy 식, `license=WHYMATH_GENERATED`(자체 생성·본문 보유 합법), `is_published=False`(미검수). 기울기·절편·그래프·식 세우기 유형은 사전 grep 기준 0건 |
| Flutter | `src/mobile/`(CI: Flutter 3.41.9 stable, Dart `^3.11`, `flutter_riverpod ^3`, `go_router ^14`, `dio ^5.4`, LaTeX 렌더 `flutter_math_fork ^0.7.4`). 진입 `lib/main.dart`, 라우트 `lib/core/router.dart`, API 클라이언트 `lib/core/api_client.dart`(`dioProvider`), 베이스 URL `lib/core/env.dart`(`--dart-define=API_URL=`, 기본 `http://localhost:8000`). CI mobile 잡: `flutter pub get --enforce-lockfile` → `dart run build_runner build --delete-conflicting-outputs` → `flutter analyze` → `flutter test --coverage` |
| CI | `.github/workflows/ci.yml` 잡 26개(백엔드 정적 검사 `backend`, pytest 샤드 `backend-pytest-1..3`, `backend-migrations`, `mobile`, `infra-contracts` 등). PR 템플릿 `.github/pull_request_template.md`(현재 "무엇을·왜 / 검증 / 변별력 / 정직한 공백 / 영향 범위" 5절) |
| 테스트 | `tests/backend/` 테스트 파일 1,109개. `tests/golden/`은 아직 없음 |

*폴더 배치(S2가 만든다)*

```
golden/                         ← 문서·데이터·로그 (저장소 루트)
  STATE.md  HARVEST.md  LATER.md  CHECKLIST.md  FINDINGS.md  RETRO.md
  tutor_prompt.md               ← 튜터 시스템 프롬프트 1개 (S4)
  data/problems_linear_fn.json  ← 문항 30개 (S3)
  logs/                         ← 학생 세션 로그 (S9~S12, gitignore 대상)
  reports/<작업번호>/보고.md     ← 각 작업 세션의 완료 보고
src/backend/golden/             ← 파이썬 패키지 (pyproject packages에 S2가 추가)
  __init__.py  api.py  grade.py  tutor.py  store.py  problems.py
src/mobile/lib/golden/          ← Flutter 화면 (S6·S7) + lib/main_golden.dart 진입점
tests/golden/                   ← test_golden_path.py (e2e) · test_problems_schema.py · test_import_direction.py
```

*HTTP 계약 3개(서버: `golden.api:app`, 접두 `/golden`)*

| 요청 | 응답 |
| --- | --- |
| `POST /golden/session` 본문 `{"nickname": "문자열(1~20자)"}` | 200 `{"session_id": "uuid", "nickname": "...", "mastery": 0.0}`. 같은 닉네임이 다시 오면 숙련도는 이어받고 session_id만 새로 발급 |
| `GET /golden/next?session_id=<uuid>` | 200 `{"id": "LF-07", "stem": "문제 본문(한국어 + 인라인 LaTeX $...$)", "index": 7, "total": 30}`. 30개를 다 풀면 처음부터 순환. 환경변수 `GOLDEN_TEST_MODE=1`일 때만 `"_test_answer": "정답 문자열"` 필드를 추가한다(답·힌트는 평소 절대 내보내지 않는다) |
| `POST /golden/answer` 본문 `{"session_id": "uuid", "problem_id": "LF-07", "text": "학생 입력"}` | 200. 판정 순서는 고정: ①먼저 `grade.py`로 채점한다 ②정답이면 몇 턴째든 `{"kind": "graded", "correct": true, "mastery": 0.10, "turns_used": 1, "feedback": "한 줄"}` ③오답이고 이 문제에서 튜터 턴이 3회 미만이면 `{"kind": "tutor_turn", "message": "튜터의 되묻기 1~3문장", "turn": 1}` ④오답이고 튜터 턴 3회를 이미 썼으면 `{"kind": "graded", "correct": false, "mastery": 0.0, "turns_used": 3, "feedback": "한 줄(정답은 알려주되 비난 표현 금지)"}`. 알 수 없는 session_id·problem_id는 404 |

*문항 JSON 스키마(`golden/data/problems_linear_fn.json` — 객체 30개의 배열)*

| 필드 | 형식 | 설명 |
| --- | --- | --- |
| `id` | `"LF-01"`~`"LF-30"` | 접두 `LF-`(Linear Function) + 두 자리. 중복 금지 |
| `stem` | 문자열 | 문제 본문. 한국어 + 인라인 LaTeX(`$y = 2x + 1$`). 그림 없음 |
| `answer` | 문자열 | 정답. `answer_kind`가 `number`면 `"-12"`·`"3/2"`처럼 SymPy가 읽는 수, `expression`이면 `"2*x + 1"`처럼 변수 `x`만 쓰는 식 |
| `answer_kind` | `"number"` 또는 `"expression"` | 채점 방식 선택 |
| `hint1` | 문자열 | 튜터가 첫 되묻기에 쓸 수 있는 힌트 1문장(정답을 말하지 않는다) |
| `concept` | 문자열 | 성취기준 코드(예 `"[9수02-14]"`) |
| `source` | 문자열 | `"corpus:problem_bank_middle_function_v0:<problem_id>"` 또는 `"authored:S3"` |

*채점·숙련도 규칙(`grade.py`·`store.py`)*

- 채점: 학생 텍스트에서 공백·`y=`·`f(x)=`·`답:` 같은 접두를 떼고, `answer_kind=number`면 SymPy `nsimplify`로 수치 비교(허용 오차 1e-9), `expression`이면 SymPy `simplify(student - answer) == 0`. 파싱 실패는 오답(예외를 삼키지 않고 로그에 예외 타입명을 남긴다). 분수·소수 동치(`1.5`와 `3/2`) 허용.
- 숙련도: 학생(닉네임)당 1행. 맞으면 +0.10, 틀리면 −0.05, `0.0 ≤ m ≤ 1.0`으로 잘라낸다. 소수 둘째 자리 반올림.
- DB: PostgreSQL 스키마 `golden`에 표 3개 — `golden.students(nickname text PK, mastery numeric(3,2), attempts int, updated_at)`, `golden.sessions(session_id uuid PK, nickname text, cursor int, created_at)`, `golden.turns(id bigserial, session_id, problem_id text, turn_no int, student_text text, tutor_text text, kind text, correct bool null, created_at)`. 앱 시작 시 `CREATE SCHEMA IF NOT EXISTS golden` + `metadata.create_all`로 만든다(Alembic 리비전은 추가하지 않는다 — 리비전은 `golden/` 밖이고 infra-contracts 잡이 등재를 요구한다. 제안값·S2에서 Kiki 확인).

*환경변수*

| 이름 | 뜻 |
| --- | --- |
| `WHYMATH_DATABASE_URL` | 기존 설정 그대로 재사용(옛 `Settings`에서 읽는다) |
| `GOLDEN_TEST_MODE=1` | `GET /golden/next`가 `_test_answer`를 포함. 테스트에서만 켠다 |
| `GOLDEN_FAKE_LLM=1` | 튜터가 LLM 대신 고정 문장("어느 부분이 막히는지 한 가지만 말해 줄래?" + hint1)을 돌려준다. 테스트·CI에서 켠다 |

## S1~S2: 측정과 격리 (1주차 앞부분)

S1은 코드를 한 줄도 고치지 않고 현재 상태를 잰다. S2는 S1 결과 위에 새 경로가 살 자리를 만들고 **일부러 빨간불인** e2e 테스트를 CI에 심는다. (이 변형에는 학생 섭외 H1이 없다.)

### S1. 상태 측정 — golden/STATE.md

- **목적:** 계획은 코드 상태를 모른 채 쓰였다. S2~S5의 세부(어디서 import하고 어디를 새로 쓸지)는 이 측정 결과로 정해진다.
- **선행 산출물:** 없음.
- **할 일:**
  1. **30분 테스트.** 현재 코드로 "학생이 중2 일차함수 문제 1개를 소크라테스 대화로 끝까지 푸는" 경로가 실제로 도는지 확인한다. 가장 짧은 방법을 고른다 — 리눅스면 `scripts/demo/run_demo.sh`(Postgres 55432·시드·uvicorn·데모 토큰 일괄), Kiki 머신이면 `scripts/demo/run_demo.ps1`. 서버가 뜨면 `src/backend/whymath_backend/api/coach.py`의 라우트 경로를 읽어 curl로 문제 요청→답변→튜터 응답을 시도한다. **30분이 지나면 멈춘다.** 어느 단계(GP-1~GP-6)에서 끊기는지와 이유 한 줄을 적는다. 고치려 하지 않는다. 시간을 재서 적는다.
  2. **질문 8개에 답한다.** 모르면 "모름"이라고 적는다. 아래 "사전 실측" 값은 출발점이며 세션에서 명령으로 다시 확인한다.
     - Q1. 백엔드 프레임워크와 진입점 파일 경로는? (사전 실측: FastAPI, `src/backend/whymath_backend/app.py`의 `create_app`, Python 3.12)
     - Q2. PostgreSQL 연결 설정은 어디 있고, 테이블은 몇 개인가? (사전 실측: `src/backend/whymath_backend/config.py`의 `Settings.database_url`·환경변수 `WHYMATH_DATABASE_URL`, `db/session.py`. 테이블 수는 모름 — `src/backend/whymath_backend/db/models/`의 `__tablename__` 수를 센다)
     - Q3. 튜터 LLM 호출은 어느 파일의 어느 함수에서 하는가? 어떤 모델·API를 쓰는가? (사전 실측: 라우터 `l3/router.py`, 팩토리 `l3/providers/factory.py`의 `build_cloud_provider`, 학생 대면 호출은 `api/coach.py` 어딘가 — 정확한 함수명은 세션에서. 모델: OpenRouter `deepseek/deepseek-v4.1-flash` 기본, 로컬 Ollama, Anthropic API는 12/31까지 중단)
     - Q4. 문항 데이터는 어디에 어떤 형식으로 있는가? 중2 일차함수 문항이 몇 개 있는가? (사전 실측: `data/corpus/problem_bank_*` 39개 폴더의 `problems.jsonl`. 일차함수는 `problem_bank_middle_function_v0` 200건이며 전부 "함숫값 구하기" 한 유형. 다른 유형은 0건 — `grep -l "기울기\|절편" data/corpus/*/problems.jsonl`로 재확인)
     - Q5. Flutter 앱은 어느 폴더이고, 백엔드와 통신하는 API 클라이언트 파일은 어디인가? (사전 실측: `src/mobile/`, `lib/core/api_client.dart`의 `dioProvider`, `lib/core/env.dart`의 `API_URL`)
     - Q6. 현재 테스트 수, 마지막 CI 통과 커밋, CI 설정 파일 경로는? (사전 실측: `tests/backend` 테스트 파일 1,109개 — 건수는 `cd src/backend && python -m pytest --collect-only -q ../../tests/backend | tail -1`로 센다. CI `.github/workflows/ci.yml`. 마지막 통과 커밋은 GitHub Actions 목록에서 main 최신 성공 run을 찾는다)
     - Q7. 사용자 진입점(HTTP 라우트, Flutter 화면)에서 호출 그래프를 따라 도달 가능한 Python 모듈 수와 전체 모듈 수는? (대략이면 된다. 방법: `src/backend`에서 `python -c "import grimp; g = grimp.build_graph('whymath_backend'); print(len(g.modules))"`로 전체를 세고, `whymath_backend.app`에서 `find_downstream_modules`/`find_upstream_modules`로 도달 집합을 센다. grimp는 import-linter의 의존성이라 이미 설치돼 있다)
     - Q8. 최근 머지된 PR 20개를 골라, 그 PR이 추가·수정한 Python 모듈이 Q7의 도달 가능 집합에 들어 있는 비율은? (방법: `git log --merges`가 아니라 스쿼시 커밋이므로 `git log --first-parent -20 --name-only -- src/backend`로 커밋 20개의 파일 목록을 뽑아 Q7 집합과 대조)
  3. **golden/STATE.md를 아래 형식으로 쓴다.** `golden/` 폴더가 없으면 이 파일 하나만 만든다.

     ```markdown
     # WhyMath 상태 측정 (S1, 2026-11-XX, 기준 커밋 <해시>)
     ## 30분 테스트 결과: [된다 / GP-N에서 끊김] — 이유 한 줄 (소요 시간)
     ## Q1~Q8 답
     ## 골든 패스에 바로 쓸 수 있는 것 (import 후보, 파일 경로 포함)
     ## 골든 패스에 쓰려면 고쳐야 하는 것
     ## 당장은 필요 없는 것 (한 줄씩, 삭제 아님)
     ```
- **산출물:** `golden/STATE.md` 1개. 커밋 메시지 `S1: 상태 측정 STATE.md`. PR은 연다(문서 1개).
- **완료 기준:** ①30분 테스트 결과 줄에 "된다" 또는 "GP-N에서 끊김"과 이유·소요 시간이 있다 ②Q1~Q8 각각에 답 또는 "모름"이 있고, 답마다 확인한 명령이나 파일 경로가 붙어 있다 ③"바로 쓸 수 있는 것"에 최소 2개(LLM 프로바이더 팩토리, 문항 jsonl)가 경로와 함께 있다.
- **하지 말 것:** 코드 수정 0줄. "이건 이렇게 고치면 됩니다"를 쓰지 않는다. 측정만 한다. 30분 테스트에서 서버가 안 뜨는 원인을 30분 넘게 파지 않는다.
- **막히면:** 서버가 30분 안에 안 뜨면 "GP-1 이전(서버 기동)에서 끊김"으로 적고 Q1~Q8로 넘어간다.

### S2. 격리 — golden/ 자리 만들기와 빨간불 e2e

- **목적:** 새 경로가 살 폴더·규칙·린트·테스트·CI를 한 번에 심는다. 이후 세션은 이 장치를 손대지 않는다. **오늘의 성공은 CI 빨간불이다** — 초록이면 테스트가 잘못된 것이다.
- **선행 산출물:** `golden/STATE.md`(S1).
- **할 일:**
  1. `golden/STATE.md`를 읽는다. Q1이 "FastAPI"가 아니면 아래 3·4단계의 도구를 그 언어에 맞게 바꾸고 보고에 적는다.
  2. **하네스 등재:** `python3 scripts/harness/backlog.py add`로 태스크 1건을 등재한다(제안 제목: "GOLD-01 골든 패스 스켈레톤 — 중2 일차함수 30문항 GP-1~GP-6 e2e"). 번호는 CLI가 준 것을 쓴다. 그 번호로 `backlog.py start <번호>`를 실행하고, 번호를 `golden/STATE.md` 맨 아래 "## 하네스 태스크 ID" 절에 적는다. 이후 모든 세션이 이 번호를 쓴다.
  3. **폴더 생성:** `golden/`에 `HARVEST.md`(첫 줄에 표 머리 `| 가져온 것 | 버린 것 | 이유 | 세션 |`), `LATER.md`, `CHECKLIST.md`, `data/.gitkeep`, `logs/.gitkeep`(저장소 `.gitignore` 88행의 `logs/` 패턴이 이미 `golden/logs/`를 무시하므로 `.gitignore`는 고치지 않고 `git add -f golden/logs/.gitkeep`으로만 추가한다 — 학생 로그가 커밋되지 않는 것이 의도다). `src/backend/golden/`에 `__init__.py`와 빈 `api.py`·`grade.py`·`tutor.py`·`store.py`·`problems.py`(각 파일 첫 줄에 한국어 docstring 한 줄만). `src/mobile/lib/golden/.gitkeep`.
  4. **배선 파일 ① `src/backend/pyproject.toml`:** `packages = ["whymath_backend"]`를 `["whymath_backend", "golden"]`로 바꾼다. `[tool.importlinter]` 아래 `root_packages`를 두 개(`whymath_backend`, `golden`)로 바꾸고(기존 `root_package` 한 줄을 `root_packages` 목록으로), 계약을 하나 추가한다:
     ```toml
     [[tool.importlinter.contracts]]
     name = "옛 코드는 golden을 모른다 (golden → whymath_backend 허용, 역방향 금지)"
     type = "forbidden"
     source_modules = ["whymath_backend"]
     forbidden_modules = ["golden"]
     ```
     `root_package`→`root_packages` 전환으로 기존 계약 3개의 판정이 바뀌지 않는지 `lint-imports`를 돌려 KEPT 수가 전후 동일함을 확인한다.
  5. **Flutter 방향 린트:** `tests/golden/test_import_direction.py`를 만든다 — `src/mobile/lib/` 아래 `lib/golden/`과 `lib/main_golden.dart`를 뺀 모든 `.dart` 파일에 `golden/` import가 0건인지 검사한다. 0건이면 통과. 검사 대상 파일이 0개면 실패(공허 통과 금지).
  6. **배선 파일 ② `CLAUDE.md`:** 맨 위에 아래 블록을 그대로 붙인다. 기존 내용은 그 아래 둔다. 파일 끝의 버전·수정일 표기 줄을 함께 갱신한다(버전 한 단계 올리고 "골든 패스 규칙 블록 신설 — Kiki 지시 2026-11-08 · 사고 유래 산문 규칙 아님"이라고 적는다).
     ```markdown
     # 골든 패스 규칙 (2026-11 ~ 3주간 최우선)

     이 저장소는 지금 golden/ 폴더 하나에만 새 코드를 쓴다.

     - golden/ 바깥의 파일은 읽기 전용이다. 수정 요청을 받아도 "golden/으로 복사해서 고칠까요?"라고 되묻는다.
     - golden/은 옛 모듈을 import할 수 있다. 옛 모듈이 golden/을 import하면 린트가 막는다.
     - 범위는 중2 일차함수 30문항, 골든 패스 GP-1~GP-6이다. 그 밖의 기능(BKT, OCR, 의도 분류기, 다과목, EOS, DSL)은 제안하지 않는다. 떠오르면 golden/LATER.md에 한 줄 적는다.
     - 완료 기준은 tests/golden/ 초록불이다. 빨간불이면 PR을 만들지 않는다.
     - 골든 패스가 지나는 파일: src/backend/golden/api.py, grade.py, tutor.py, store.py, problems.py, golden/tutor_prompt.md, golden/data/problems_linear_fn.json, tests/golden/test_golden_path.py, (Flutter) src/mobile/lib/golden/*.dart, lib/main_golden.dart. 이 목록 밖의 파일을 건드리면 먼저 이유를 말한다.
     - 모든 코드에 한국어 주석.
     ```
  7. **e2e 테스트 뼈대 `tests/golden/test_golden_path.py`:** 아래를 그대로 둔다. `from golden.api import app`에서 `app`이 아직 없으므로 import 단계에서 실패한다 — 그것이 의도된 빨간불이다. 함께 `tests/golden/conftest.py`에 `GOLDEN_TEST_MODE=1`·`GOLDEN_FAKE_LLM=1`을 세션 시작 시 `os.environ`에 넣는 autouse 픽스처를 둔다.
     ```python
     """골든 패스 e2e — 학생 한 명이 문제 하나를 끝까지 푼다.
     이 테스트가 빨간불이면 어떤 PR도 머지하지 않는다."""
     import pytest
     from fastapi.testclient import TestClient

     # golden/api.py에 app이 생기기 전까지는 import 자체가 실패한다 — 그것이 S2의 의도된 빨간불
     from golden.api import app

     client = TestClient(app)


     def test_student_solves_one_problem_end_to_end():
         # GP-1 세션 시작: 닉네임만으로 익명 세션
         r = client.post("/golden/session", json={"nickname": "테스트학생"})
         assert r.status_code == 200
         session_id = r.json()["session_id"]

         # GP-2 문제 제시: 30문항 중 첫 문제
         r = client.get(f"/golden/next?session_id={session_id}")
         assert r.status_code == 200
         problem = r.json()
         assert problem["id"].startswith("LF-")  # 일차함수(Linear Function) 문항 접두사

         # GP-3 + GP-4: 틀린 답을 내면 튜터가 되묻는다 (판정이 아니라 질문이 와야 함)
         r = client.post("/golden/answer", json={
             "session_id": session_id,
             "problem_id": problem["id"],
             "text": "모르겠어요",
         })
         assert r.status_code == 200
         assert r.json()["kind"] == "tutor_turn"  # 'graded'가 아니라 'tutor_turn'
         assert len(r.json()["message"]) > 0

         # GP-5 + GP-6: 정답을 내면 판정과 숙련도 갱신이 온다
         r = client.post("/golden/answer", json={
             "session_id": session_id,
             "problem_id": problem["id"],
             "text": problem["_test_answer"],  # 테스트 모드에서만 노출되는 정답 필드
         })
         assert r.status_code == 200
         body = r.json()
         assert body["kind"] == "graded"
         assert body["correct"] is True
         assert 0.0 <= body["mastery"] <= 1.0
         assert body["mastery"] > 0.0  # 맞았으니 0에서 올라가야 한다

         # 다음 문제로 돌아간다 (GP-6 → GP-2 루프)
         r = client.get(f"/golden/next?session_id={session_id}")
         assert r.json()["id"] != problem["id"]

         pytest.fail("S2: 아직 구현 전. 이 줄은 S5에서 지운다.")
     ```
  8. **배선 파일 ③ `.github/workflows/ci.yml`:** 잡 `golden-path`를 추가한다. `backend-pytest-1` 잡의 Postgres 서비스 블록·Python 3.12 설치·의존성 설치 스텝을 복사하고, 스텝 순서는 `python -m ruff check golden ../../tests/golden` → `python -m black --check --line-length 100 golden ../../tests/golden` → `python -m mypy --strict golden` → 마지막 `python -m pytest ../../tests/golden`(working-directory `src/backend`, `-q` 없음, 각 스텝의 마지막 명령이 검사 명령 자신이어야 종료 코드가 보존된다). 기존 `backend` 잡은 `golden`·`tests/golden`을 검사하지 않으므로(ruff/black 대상이 `. ../../tests/backend ../../tests/constitution`, mypy 대상이 `whymath_backend`) 이 잡이 유일한 검사 지점이다. `needs`는 두지 않는다(다른 잡과 병렬). 머지 차단은 브랜치 룰셋의 required check 목록에 이 잡을 넣어야 완성되는데 그 조작은 Kiki만 할 수 있다 — 보고의 "다음 작업이 알아야 할 것"에 "required check에 `golden-path` 추가 필요(Kiki)"라고 적는다.
  9. **배선 파일 ④ `.github/pull_request_template.md`:** 파일 맨 위에 아래 블록을 넣고, 기존 5절은 그 아래 그대로 둔다(기존 절을 지우지 않는 이유: `tests/infra`에 템플릿 절 이름을 검사하는 테스트가 있을 수 있다 — `grep -rn "pull_request_template" tests/infra`로 확인하고 결과를 보고에 적는다).
     ```markdown
     ## 이 PR이 전진시키는 학생 단계
     (GP-1~GP-6 중 하나. 적을 수 없으면 이 PR은 지금 할 일이 아니다.)

     ## 세션 번호
     S__

     ## tests/golden 결과
     - [ ] 초록 (S2만 예외: 빨강이 목표)

     ## HARVEST.md 갱신
     - [ ] 옛 코드를 가져왔거나 버렸으면 한 줄 적었다

     ## 범위 확인
     - [ ] golden/ 바깥 파일을 수정하지 않았다 (S2의 배선 파일 4개 제외)
     - [ ] 새 추상화(베이스 클래스, 인터페이스, 플러그인 구조)를 추가하지 않았다
     ```
  10. 로컬에서 `cd src/backend && python -m pytest ../../tests/golden`을 돌려 **빨강(exit 1 또는 2, ImportError)**을 확인하고, `lint-imports`·`ruff`·`black --check`가 초록인지 확인한다(새 패키지 `golden`에 `mypy --strict golden`도 돌린다 — 빈 모듈이라 통과해야 한다).
  11. 커밋 메시지 `S2: golden/ 격리, 빨간불 e2e 추가`. PR을 올리고 CI에서 `golden-path` 잡이 빨강이고 다른 잡은 S2 이전과 같은 색인지 확인한다. `backend` 잡의 `lint-imports`가 초록이어야 한다.
- **산출물:** `golden/` 폴더 일체, `src/backend/golden/` 빈 패키지, `tests/golden/` 2파일 + conftest, 배선 파일 4개 변경(CLAUDE.md·ci.yml·PR 템플릿·pyproject.toml), PR 1개(CI 빨강).
- **완료 기준:** ①PR의 `golden-path` 잡이 빨강이고 실패 원인이 `ImportError: cannot import name 'app'`(또는 동등)이다 ②`backend` 잡 안 `lint-imports`가 초록이고 계약 수가 기존+1이다 ③`test_import_direction.py`가 초록이며, 검사한 dart 파일 수가 보고에 적혀 있다(0이 아니다) ④STATE.md 맨 아래 하네스 태스크 ID가 있다.
- **하지 말 것:** e2e 테스트를 초록으로 만들려고 `api.py`에 코드를 쓰지 않는다. 기존 PR 템플릿 절을 삭제하지 않는다. `constitution/`에 손대지 않는다. 다른 CI 잡의 스텝을 고치지 않는다.
- **막히면:** `root_packages` 전환으로 기존 import-linter 계약이 깨지면 전환하지 말고, 대신 `tests/golden/test_import_direction.py`에 파이썬 방향 검사(`src/backend/whymath_backend/**/*.py`에 `import golden`·`from golden` 0건)를 함께 넣고 보고에 "import-linter 계약 대신 테스트로 집행"이라고 적는다.

## S3~S5: 백엔드 스켈레톤 (1주차 뒷부분)

문항·API·채점을 셋으로 나눈다. S3과 S4는 **같은 공유 계약(문항 JSON·HTTP 응답 모양)을 보고 동시에** 진행할 수 있다. S5가 둘을 이어 e2e를 초록으로 만든다.

### S3. 문항 30개 — golden/data/problems_linear_fn.json

- **목적:** GP-2가 보여줄 문제 30개를 만든다. 옛 자산에서 가져올 수 있는 것은 가져오고, 없는 유형은 직접 쓴다.
- **선행 산출물:** `golden/STATE.md` Q4 답(문항 자산 위치), `golden/data/` 폴더(S2).
- **할 일:**
  1. `data/corpus/problem_bank_middle_function_v0/problems.jsonl`에서 **10개**를 고른다(제안값). 조건: `question_text`에 "일차함수"가 들어가고, `answer`가 정수이며, 계수·상수항이 서로 다른 문제. 각 문제를 공유 계약의 JSON 스키마로 변환한다 — `stem`은 `question_text`를 LaTeX 인라인(`$f(x) = -3x + 3$`)으로 다듬고, `answer_kind="number"`, `source="corpus:problem_bank_middle_function_v0:<problem_id>"`, `hint1`은 새로 쓴다(예: "x 자리에 5를 넣으면 식이 어떻게 되는지 말해 볼래?"). HARVEST.md에 "가져온 것: problem_bank_middle_function_v0 10건 / 버린 것: 나머지 190건(같은 유형 중복) / 이유: 유형 다양성 / S3"을 적는다.
  2. **20개**를 직접 쓴다(제안값). 유형 분배: 함숫값 추가 2 · 기울기 구하기 4(두 점, 식에서) · y절편·x절편 4 · 식 세우기 5(기울기+한 점, 두 점, 평행 조건) · 그래프 해석 3(증가/감소, 제1사분면 통과 여부 — 답은 숫자나 식으로 묻는다) · 실생활 식 세우기 2(예: 양초 길이). 그림이 필요한 문제는 쓰지 않는다. 식이 답인 문제는 `answer_kind="expression"`, `answer`는 `"2*x + 1"` 형태(변수는 `x`만).
  3. 각 문제의 `answer`를 SymPy로 스스로 검산한다(함숫값은 대입, 기울기는 공식, 식 세우기는 주어진 점을 대입해 성립 확인). 검산 스크립트는 `tests/golden/test_problems_schema.py` 안에 넣지 않고 S3 세션에서 1회 실행 후 보고에 결과만 적는다.
  4. `tests/golden/test_problems_schema.py`를 쓴다: ①정확히 30개 ②`id`가 `LF-01`~`LF-30` 중복 없음 ③7개 필드 모두 존재·비어 있지 않음 ④`answer_kind`는 두 값 중 하나 ⑤`answer`가 SymPy로 파싱된다(`number`면 수, `expression`이면 자유 변수가 `{x}` 이하) ⑥`hint1`에 `answer` 문자열이 그대로 들어 있지 않다(힌트가 답을 말하지 않는다) ⑦`stem`에 `$`가 짝수 개(LaTeX 열고 닫음).
  5. `cd src/backend && python -m pytest ../../tests/golden/test_problems_schema.py` 초록 확인. e2e(`test_golden_path.py`)는 아직 빨강인 것이 정상이다 — 보고에 "e2e 빨강은 S5 전까지 예정된 상태"라고 적는다.
- **산출물:** `golden/data/problems_linear_fn.json`(30개), `tests/golden/test_problems_schema.py`, HARVEST.md 1줄.
- **완료 기준:** ①스키마 테스트 7항목 초록 ②30개 중 코퍼스 유래 10·직접 작성 20이 `source`로 구분된다 ③유형 분배가 보고에 표로 있다 ④교과서·EBS·평가원 문항을 베낀 것이 0건이다(직접 쓴 20개는 숫자·맥락을 새로 만든 자체 문항).
- **하지 말 것:** 31개 이상 만들지 않는다. 중3·고1 내용(이차함수·연립방정식 응용)을 섞지 않는다. 그림·표가 필요한 문제를 쓰지 않는다. 검정교과서·EBS·평가원 문항을 그대로 또는 숫자만 바꿔 옮기지 않는다(저작권 금기).
- **막히면:** 코퍼스에서 10개를 못 채우면(예: 정수 답이 부족) 그만큼 직접 쓰고 보고에 적는다.

### S4. API 3개 + 튜터 프롬프트 1개 — src/backend/golden/api.py

- **목적:** GP-1·GP-2·GP-3·GP-4를 잇는 서버를 만든다. curl로 세션 시작→문제→답변→튜터 되묻기가 돌아야 한다. 채점·숙련도(GP-5·6)는 S5가 붙이므로, 이 세션에서는 `grade.py`에 "항상 오답" 스텁만 둔다.
- **선행 산출물:** `golden/STATE.md`(Q1·Q3), S2의 빈 패키지와 배선. S3의 문항 파일이 아직 없으면 `golden/data/problems_linear_fn.json` 자리에 **스키마와 똑같은 모양의 임시 3문항**을 두고 시작한다(S3 머지 시 S3 파일이 덮어쓴다 — 충돌 나면 S3 것을 택한다).
- **할 일:**
  1. `problems.py`: JSON 파일을 읽어 `list[dict]`로 돌려주는 함수 1개와, `GOLDEN_TEST_MODE` 환경변수에 따라 `_test_answer`를 붙이는 함수 1개. 파일 경로는 저장소 루트 기준 `golden/data/problems_linear_fn.json`(`pathlib.Path(__file__).resolve().parents[3] / "golden" / "data" / ...`).
  2. `store.py`: 공유 계약의 표 3개를 SQLAlchemy로 정의(`MetaData(schema="golden")`)하고, 앱 시작(lifespan)에서 `CREATE SCHEMA IF NOT EXISTS golden` + `create_all`. 엔진은 옛 코드의 `whymath_backend.db.session.get_engine()`을 import해서 쓴다(HARVEST.md에 적는다). 함수: `create_session(nickname) -> (session_id, mastery)`, `get_session(session_id)`, `advance_cursor(session_id)`, `record_turn(...)`, `get_mastery(nickname)`, `set_mastery(nickname, value)`. 전부 async.
  3. `tutor.py`: 시스템 프롬프트 파일 `golden/tutor_prompt.md`를 읽어, 문제 본문·`hint1`·이번 문제의 지금까지 대화(최대 3턴)·학생 입력을 넣어 LLM을 **1회** 호출하고 되묻기 문장을 돌려준다. 프로바이더는 `whymath_backend.l3.providers.factory.build_cloud_provider()`로 받는다(HARVEST.md). `GOLDEN_FAKE_LLM=1`이면 "어느 부분이 막히는지 한 가지만 말해 줄래? " + `hint1`을 돌려준다. 호출 실패(예외·타임아웃 10초)는 삼키지 않고 예외 타입명을 로그에 남긴 뒤 가짜 문장으로 대체하고 응답에 `"degraded": true`를 넣는다.
  4. `golden/tutor_prompt.md`(한국어, 300자 이내 제안값): 역할(중2 수학 튜터), 규칙 4개 — ①정답·최종 수치를 말하지 않는다 ②한 번에 질문 하나 ③학생 말을 한 문장 되짚은 뒤 묻는다 ④틀렸다·못한다 같은 평가어 금지. 출력은 2~3문장.
  5. `api.py`: `APIRouter(prefix="/golden")`에 엔드포인트 3개를 공유 계약 그대로 구현한다. `answer`의 판정 순서(채점 먼저 → 정답이면 graded → 오답이면 턴 수에 따라 tutor_turn/graded)를 그대로 코드에 쓰되, 이 세션에서는 `grade.py`의 `is_correct()`가 항상 `False`를 돌려주는 스텁이다(한국어 주석에 "S5에서 교체"). 모듈 끝에 `app = FastAPI(title="WhyMath Golden Path")` + `app.include_router(router)` + lifespan. 옛 `create_app`에는 등록하지 않는다(파사드 분리 — 옛 앱은 그대로 둔다).
  6. 서버를 띄운다: `cd src/backend && GOLDEN_FAKE_LLM=1 GOLDEN_TEST_MODE=1 uvicorn golden.api:app --port 8000`(DB는 `WHYMATH_DATABASE_URL`이 가리키는 Postgres — 로컬이면 `docker compose -f docker-compose.demo.yml up -d` 후 55432). curl 3개를 순서대로 치고 응답 JSON을 보고에 붙인다. 그다음 `GOLDEN_FAKE_LLM`을 빼고 실제 LLM으로 1회 호출해 되묻기 문장이 오는지 확인한다(키가 없으면 "미확인 — 키 없음"으로 적는다).
  7. 테스트 `tests/golden/test_api_contract.py`(제안): 세션 생성 200·닉네임 빈 문자열 422·모르는 session_id 404·`_test_answer`가 `GOLDEN_TEST_MODE` 없이는 없음·답변 3회 오답 후 4번째가 graded. `cd src/backend && python -m pytest ../../tests/golden` — `test_golden_path.py`는 `pytest.fail` 줄 때문에 아직 빨강이어야 한다. 그 외는 초록.
  8. 정적 검사 4종(공통 규칙 7) 초록.
- **산출물:** `api.py`·`problems.py`·`store.py`·`tutor.py`·`grade.py`(스텁), `golden/tutor_prompt.md`, `tests/golden/test_api_contract.py`, HARVEST.md 2줄(엔진·프로바이더 팩토리).
- **완료 기준:** ①curl 3개의 응답이 공유 계약 모양과 일치한다(보고에 JSON 첨부) ②실제 LLM 1회 호출로 되묻기 1턴이 온다(또는 키 없음 명시) ③`tests/golden`에서 `test_golden_path.py` 1건만 빨강이고 나머지 초록 ④정적 검사 4종 exit 0 ⑤`golden.api`가 `whymath_backend`를 import하는 모듈 수가 보고에 있다(2개 이하 목표 — 엔진·프로바이더).
- **하지 말 것:** 옛 `api/coach.py`의 7단계 파이프라인·오개념 DB·루브릭을 가져오지 않는다. 엔드포인트를 4개 이상 만들지 않는다. 프로바이더 팩토리가 다른 모듈 20개를 끌고 오면 가져오지 말고 `tutor.py`에 50줄로 직접 HTTP 호출을 쓰고 HARVEST.md에 "버림: 의존 과다"라고 적는다(단, 이 경우에도 키는 옛 `Settings`에서 읽는다).
- **막히면:** `get_engine()`이 옛 설정 전체를 요구해 기동이 안 되면 `store.py`에서 `create_async_engine(os.environ["WHYMATH_DATABASE_URL"])`로 직접 만들고 HARVEST.md에 "버림: get_engine 의존 과다"로 적는다.

### S5. 판정·숙련도 + e2e 초록 — src/backend/golden/grade.py

- **목적:** GP-5·GP-6을 붙여 골든 패스를 서버 쪽에서 끝까지 잇는다. 이 세션이 끝나면 `tests/golden`이 처음으로 초록이 된다(관문 ②).
- **선행 산출물:** S3의 문항 30개, S4의 API·store.
- **할 일:**
  1. `grade.py`: 공유 계약의 채점 규칙을 구현한다 — 정규화(공백 제거, `y=`·`f(x)=`·`답:`·`입니다` 제거, 전각 숫자·`−`(U+2212)를 반각 `-`로), `number`는 `sympy.nsimplify` 비교, `expression`은 `sympy.simplify(parse(student) - parse(answer)) == 0`. `parse_expr`에는 `transformations=standard_transformations + (implicit_multiplication_application,)`를 써서 `2x+1`도 읽는다. 파싱 실패는 `False`를 돌려주되 예외 타입명을 로그에 남긴다.
  2. 단위 테스트 `tests/golden/test_grade.py`: 맞는 입력 6종(`-12`, ` -12 `, `답: -12`, `y=2x+1`, `2x + 1`, `3/2`와 `1.5`), 틀린 입력 4종(다른 수, 다른 식, 빈 문자열, `모르겠어요`), 파싱 불가 문자열이 예외 없이 오답 처리.
  3. `api.py`의 `answer`에서 스텁을 실제 `grade.is_correct()`로 바꾸고, 공유 계약의 숙련도 갱신(+0.10/−0.05/clamp/반올림)을 `store.set_mastery`로 저장한다. graded 응답의 `feedback`은 정답이면 "맞았어요. 다음 문제로 가 볼까요?", 오답이면 "이번 문제의 답은 {answer}였어요. 다음 문제에서 다시 해 봐요."(비난 표현 금지).
  4. `golden/CHECKLIST.md`에 12항목(제안)을 적는다 — S8이 앱으로 확인할 목록: ①닉네임 입력 후 세션 생성 ②첫 문제 LaTeX 렌더 ③입력창에 "모르겠어요" → 되묻기 표시 ④되묻기가 정답을 말하지 않음 ⑤3턴 뒤 강제 판정 ⑥정답 입력 → 맞음 표시 ⑦숙련도 숫자 증가 ⑧오답 → 숙련도 감소(0 아래로 안 내려감) ⑨다음 문제 버튼 → 다른 문제 ⑩앱 재시작 후 같은 닉네임 → 숙련도 유지 ⑪서버 꺼진 상태 → 오류 문구(앱이 죽지 않음) ⑫문제 3개 연속 완료.
  5. `tests/golden/test_golden_path.py` 마지막 `pytest.fail(...)` 줄을 지운다. **그 줄만** 지운다.
  6. `cd src/backend && python -m pytest ../../tests/golden` → 전부 초록(exit 0). 변별력 확인: `grade.py`의 비교를 일부러 `return True`로 바꾸고(`cp`로 백업 후) e2e의 tutor_turn 단언이 빨강이 되는지 본 뒤 `cp`로 원복한다(`git checkout`으로 원복하지 않는다 — 미커밋 구현이 함께 날아간다). 보고에 "뮤테이션 1종 → 빨강 확인 → 원복"을 적는다.
  7. HARVEST.md에 1주차 수확을 정리한다(가져온 것: 문항 10건·엔진·프로바이더 팩토리 / 버린 것: coach.py 파이프라인·오개념 DB·루브릭 등 — 각각 이유).
  8. 정적 검사 4종 초록. PR. CI의 `golden-path` 잡이 처음으로 초록인지 확인한다.
- **산출물:** `grade.py`, `tests/golden/test_grade.py`, `golden/CHECKLIST.md`(12항목), e2e 초록, HARVEST.md 1주차 정리.
- **완료 기준:** ①`pytest ../../tests/golden` exit 0이고 테스트 수가 보고에 있다 ②CI `golden-path` 잡 초록 ③뮤테이션 1종이 e2e를 빨강으로 만들었다가 원복됨 ④Postgres `golden.students`에 테스트학생 1행이 남는다(테스트 후 `SELECT`로 확인하거나 테스트가 트랜잭션을 되돌리면 그 사실을 적는다) ⑤판정: **go**(초록) / **no-go**(빨강 — 다음 세션은 S5를 반복한다).
- **하지 말 것:** 부분 점수·풀이 과정 채점·오류 유형 분류를 넣지 않는다. BKT 같은 숙련도 모델로 바꾸지 않는다(+0.10/−0.05 고정). e2e의 단언을 약하게 고쳐서 초록을 만들지 않는다.
- **막히면:** `expression` 비교가 특정 문항에서 SymPy 때문에 느리거나(5초+) 실패하면 그 문항을 `number`형으로 바꿀 수 있는지 S3 파일을 보고 바꾸되 보고에 적는다.

## S6~S8: Flutter 스켈레톤 (2주차)

Flutter는 옛 화면을 건드리지 않고 `lib/golden/`과 별도 진입점 `lib/main_golden.dart`로 만든다. S6은 S4의 API 계약만 있으면 시작할 수 있어 **S5와 동시에** 진행 가능하다. S7은 S6의 화면 파일을 이어 쓰므로 S6 다음이다.

### S6. Flutter 화면 1 — 닉네임·문제·대화

- **목적:** GP-1~GP-4를 앱에서 본다. 문제가 보이고, 입력하면 튜터 응답이 같은 화면에 쌓인다.
- **선행 산출물:** S4의 API(공유 계약), `src/mobile/lib/golden/` 자리(S2).
- **할 일:**
  1. `src/mobile/lib/main_golden.dart`: `runApp(ProviderScope(child: GoldenApp()))`. 옛 `main.dart`·`app.dart`·`core/router.dart`는 건드리지 않는다. 실행은 `flutter run -t lib/main_golden.dart --dart-define=API_URL=http://<서버 IP>:8000`.
  2. `lib/golden/golden_api.dart`: `Dio` 인스턴스를 **직접** 만든다(`BaseOptions(baseUrl: Env.apiUrl)` — `lib/core/env.dart`만 import, `api_client.dart`의 인증 인터셉터는 쓰지 않는다. HARVEST.md에 "가져온 것: Env.apiUrl / 버린 것: dioProvider(인증 인터셉터 불필요)"). 함수 3개: `createSession(nickname)`, `nextProblem(sessionId)`, `answer(sessionId, problemId, text)` — 응답은 공유 계약 모양의 Dart 클래스(`GoldenProblem`, `AnswerResult` with `kind`)로 받는다. `kind == "tutor_turn"`과 `"graded"`를 sealed class 또는 enum으로 구분한다.
  3. `lib/golden/golden_state.dart`: Riverpod `Notifier` 하나. 상태 = 세션 ID·닉네임·숙련도·현재 문제·대화 목록(`List<(String who, String text)>`)·로딩·오류 문구. 수학 로직은 넣지 않는다(채점은 서버).
  4. 화면 2개: `nickname_screen.dart`(텍스트 필드 1개 + 시작 버튼) → `problem_screen.dart`(위: 문제 본문을 `flutter_math_fork`로 LaTeX 렌더 — `$...$` 구간만 `Math.tex`, 나머지는 `Text`. 가운데: 대화 말풍선 목록(학생/튜터). 아래: 입력창 + 보내기). `graded`가 오면 이 세션에서는 대화 목록에 "판정: 맞음/틀림 · 숙련도 0.10" 한 줄만 추가한다(결과 화면은 S7).
  5. 서버 꺼짐·타임아웃이면 화면 위에 "서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요." 한 줄을 보여주고 앱은 죽지 않는다.
  6. 위젯 테스트 `src/mobile/test/golden/problem_screen_test.dart`: 가짜 API(인터페이스 주입)로 ①문제가 렌더된다 ②"모르겠어요" 전송 후 튜터 말풍선 1개 추가 ③graded 응답 후 판정 줄 표시.
  7. `cd src/mobile && flutter pub get --enforce-lockfile && flutter analyze && flutter test` 전부 exit 0(analyze 경고 0건). `tests/golden/test_import_direction.py`도 돌린다(옛 코드가 golden을 import하지 않음).
  8. 실제 서버(S4 또는 S5)에 붙여 에뮬레이터나 실기기에서 문제 1개를 보고 되묻기까지 받은 화면 캡처를 `golden/reports/S6/`에 둔다.
- **산출물:** `lib/main_golden.dart`, `lib/golden/` 4~5파일, 위젯 테스트 1파일, 캡처 1장, HARVEST.md 1줄.
- **완료 기준:** ①에뮬레이터/실기기에서 문제가 LaTeX 포함 보이고 ②입력 후 튜터 응답이 같은 화면에 쌓이며 ③`flutter analyze`·`flutter test` exit 0 ④위젯 테스트 3건 초록 ⑤`lib/golden/` 밖 dart 파일 변경 0건(`git diff --stat`으로 확인해 보고에 붙인다).
- **하지 말 것:** 옛 `router.dart`에 경로를 추가하지 않는다(진입점 분리). 손글씨·음성·수식 편집기를 넣지 않는다. 디자인을 다듬지 않는다(기본 Material 위젯이면 충분). 수학 판정을 클라이언트에 넣지 않는다.
- **막히면:** `flutter_math_fork`가 LaTeX 일부를 못 그리면 그 문항 번호를 LATER.md에 적고 `Text`로 대체한다.

### S7. Flutter 화면 2 — 결과·다음 문제

- **목적:** GP-5·GP-6을 앱에서 본다. 정답/오답과 숙련도 숫자가 보이고, 다음 문제 버튼이 GP-2로 돌아간다.
- **선행 산출물:** S5(graded 응답이 실제 채점·숙련도를 담음), S6의 화면·상태.
- **할 일:**
  1. `lib/golden/result_screen.dart`: `graded` 응답을 받으면 이 화면으로 간다. 표시: 맞음/틀림(색과 아이콘), 숙련도 숫자(소수 둘째 자리) + 이전 값에서 얼마나 바뀌었는지(+0.10 / −0.05), `feedback` 문장, 사용한 튜터 턴 수, 버튼 "다음 문제".
  2. "다음 문제" 버튼 → `nextProblem` 호출 → `problem_screen`으로 돌아가며 대화 목록을 비운다(GP-6→GP-2 루프).
  3. `problem_screen` 상단에 현재 숙련도와 "LF-07 · 7/30"을 작게 표시한다.
  4. 앱 재시작 후 같은 닉네임으로 시작하면 숙련도가 이어지는지(서버가 `POST /golden/session`에서 돌려주는 `mastery`를 그대로 표시) 확인한다.
  5. 위젯 테스트 추가: ①graded(correct=true) → 결과 화면에 "맞음"과 숙련도 ②"다음 문제" 탭 후 문제 화면 복귀 + 대화 비움 ③correct=false → 비난 표현 없음(`"틀렸"`·`"못"` 문자열 부재 단언).
  6. `flutter analyze`·`flutter test` exit 0. 실기기/에뮬레이터에서 문제 1개를 끝까지 풀어 결과 화면 캡처를 `golden/reports/S7/`에 둔다.
- **산출물:** `result_screen.dart`, 상태·문제 화면 수정, 위젯 테스트 3건, 캡처.
- **완료 기준:** ①정답/오답과 숙련도 숫자가 보인다 ②"다음 문제"가 다른 문제를 띄운다 ③재시작 후 숙련도 유지 ④`flutter analyze`·`flutter test` exit 0 ⑤`lib/golden/`·`lib/main_golden.dart` 밖 변경 0건.
- **하지 말 것:** 통계 화면·배지·연속 정답 효과 같은 게임화를 넣지 않는다. 숙련도 계산을 클라이언트에서 다시 하지 않는다(서버 값만 표시).

### S8. 앱 통합 — 본인 테스트와 CHECKLIST 12/12

- **목적:** 학생에게 보여주기 전에 Kiki가 직접 문제 3개를 끝까지 풀어 본다. 관문 ③ — 12/12가 아니면 S9를 열지 않는다.
- **선행 산출물:** S7(앱 완성), `golden/CHECKLIST.md`(S5).
- **할 일:**
  1. **Kiki 머신 실행 런북**을 `golden/reports/S8/런북.md`에 쓴다. 규칙: PowerShell 기준, `cd C:\Users\kiki\Desktop\__AI\WhyMath` 포함, 자리표시자 0개(값은 블록이 스스로 찾는다 — LAN IP는 `(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -like "192.168.*"}).IPAddress | Select-Object -First 1`), 서버 창과 앱 창을 **별도 블록**으로 분리, 서버 블록 끝에 "이 창은 이후 조작 금지" 경고, 실행 직전 `git log -1 --oneline` 자가검증(기대 해시 명기). 서버: `docker compose -f docker-compose.demo.yml up -d` → `$env:WHYMATH_DATABASE_URL="postgresql+asyncpg://whymath@127.0.0.1:55432/whymath?ssl=disable"` → `cd src\backend` → `python -m uvicorn golden.api:app --host 0.0.0.0 --port 8000`. 앱: `cd src\mobile` → `flutter run -t lib/main_golden.dart --dart-define=API_URL=http://<블록이 찾은 IP>:8000`. 사전 브리핑 6항목(과제 명칭·목적·절차·성공 기준·실행 환경·창 구분)을 런북 맨 위에 둔다.
  2. 세션 AI는 리눅스에서 같은 경로를 먼저 재현한다(`run_demo.sh` 방식의 Postgres 55432 + `uvicorn golden.api:app` + 에뮬레이터 또는 `flutter test`). 재현 결과를 보고에 적는다.
  3. Kiki가 앱으로 문제 3개를 끝까지 푼다. `golden/CHECKLIST.md` 12항목에 ✅/❌와 한 줄 메모를 적는다.
  4. ❌가 있으면 이 세션에서 고친다 — 단, 고치는 파일은 `golden/` 아래뿐이고, 고친 뒤 `tests/golden`·`flutter test`를 다시 돌린다. 2회 반복해도 12/12가 안 되면 멈추고 보고한다.
  5. 튜터 되묻기가 엉성하면 `golden/tutor_prompt.md`를 **이 세션에서 1회만** 다듬는다(루브릭·파이프라인은 LATER.md).
  6. 학생 세션용 **관찰 기록 양식** `golden/LOG_TEMPLATE.md`를 만든다(`golden/logs/`는 gitignore 대상이라 양식은 밖에 둔다): 학생 가명, 날짜, 문제 ID별(시작 시각·튜터 턴 수·판정·막힌 지점·학생이 소리 내어 말한 것·개발자 메모), 끝에 "가장 먼저 끊긴 지점 1개".
- **산출물:** 런북, CHECKLIST 12/12 기록, 관찰 기록 양식, (있으면) 수정 PR.
- **완료 기준:** ①CHECKLIST 12/12 ✅ ②Kiki가 문제 3개를 끝까지 풀었다(세 문제의 ID와 판정이 기록) ③`tests/golden` 초록 ④판정: **go**(12/12) / **no-go**(그 외 — S9를 열지 않고 S8을 반복).
- **하지 말 것:** 체크리스트 항목을 줄이거나 바꿔서 12/12를 만들지 않는다. 학생에게 보여주기 전에 기능을 추가하지 않는다.
- **막히면:** 실기기에서 `localhost`로 접속하면 기기 자신을 가리켜 실패한다 — 반드시 PC의 LAN IP를 쓴다(`/demo-doctor` 카탈로그 D행 참조).

## S9~S12: 대체 피험자 검증 (2주차 끝 ~ 3주차) — 학생 없는 변형

이 변형은 실제 중학생 없이 **세 겹의 대체 피험자**로 로그 30건 이상을 만든다: ①Kiki 본인이 학생 역할(S9) ②AI 시뮬레이션 학생 3 페르소나(S11) ③성인 지인 2명(S12). S9와 S11은 사람 일정이 겹치지 않으므로 **동시에** 진행할 수 있고, S10이 둘의 로그를 한꺼번에 고친다. 세 출처는 S13에서 **반드시 분리 집계**한다 — 대체 피험자의 끊김 지점이 실제 학생의 끊김 지점과 같다는 보장이 없기 때문이다. 이 한계는 FINDINGS.md와 RETRO.md 첫머리에 그대로 적는다. 도중에 실제 학생이 1명이라도 구해지면 원본 묶음(`golden/prompts/`)의 S9 지시문으로 바꿔 진행한다 — 실제 학생 로그 1건이 시뮬레이션 10건보다 값지다.

### S9. 본인 학생 역할 — Kiki가 모르는 척 5문제

- **목적:** 첫 실사용 로그를 만든다. 피험자는 Kiki 본인이며, "답을 아는 사람의 함정"을 줄이기 위해 아래 규칙으로 일부러 서툴게 푼다.
- **선행 산출물:** S8 판정 go.
- **할 일:**
  1. (Kiki) S8 런북대로 서버·앱을 띄운다. 닉네임은 `self-1`로 한다.
  2. (Kiki) 문제 5개를 푼다. **역할 규칙 4개**를 지킨다 — ①첫 입력은 항상 질문이나 오답으로 한다(예: "x가 뭐예요?", 부호를 틀린 답) ②튜터 되묻기에는 중2가 쓸 법한 짧은 문장(10자 안팎)으로만 답한다 ③3문제 중 1문제는 끝까지 틀린다(3턴 소진) ④맞는 답은 2번째 또는 3번째 턴에만 낸다. 매 문제마다 "튜터 되묻기가 실제로 나를 다음 생각으로 이끌었는가"를 1~5점으로 적는다.
  3. (Kiki → AI 세션) 관찰 기록을 `golden/LOG_TEMPLATE.md` 양식으로 `golden/logs/2026-11-XX_self1.md`에 쓴다(점수 포함). 서버 측 기록을 `golden.turns`에서 뽑아 `self1_turns.csv`로 둔다(닉네임·session_id 열 제거).
  4. (AI 세션) 로그를 읽고 `golden/reports/S9/보고.md`에 문제별 결과 표(ID·턴 수·판정·되묻기 점수·막힌 척한 지점)와 "끊긴 지점 후보 상위 3개"를 적는다. 고치지 않는다.
  5. (AI 세션) 같은 보고에 "본인 피험자 한계" 절을 둔다: 정답을 알고 있었으므로 GP-2(문제 이해)·GP-5(판정) 축의 끊김은 과소 측정되고, GP-4(되묻기 품질) 축만 비교적 믿을 수 있다는 점을 명시한다.
- **산출물:** 관찰 기록 1건 + turns CSV, 보고(문제별 표·후보 3개·한계 절).
- **완료 기준:** ①문제 5개 기록 ②되묻기 점수 5개 ③후보 3개가 로그 줄 번호와 함께 있다 ④한계 절이 있다.
- **하지 말 것:** 세션 중 코드 수정 금지. 역할 규칙을 어기고 첫 턴에 정답을 내지 않는다(그러면 GP-4 로그가 0건이 된다).
- **막히면:** 앱이 5분 이상 멈추면 세션을 끝내고 그 지점을 1순위 끊김으로 기록한다.

### S11. AI 시뮬레이션 학생 — 페르소나 3종 × 10문제

- **목적:** 사람 없이 로그 30건을 만든다. LLM이 "특정 오개념을 가진 중2"를 연기해 골든 패스 API를 실제로 호출한다. 튜터 LLM과 학생 LLM이 서로 대화하는 구조다.
- **선행 산출물:** S8 판정 go(S9와 동시에 시작 가능 — S9 결과를 기다리지 않는다).
- **할 일:**
  1. `src/backend/golden/sim_student.py`를 만든다. 입력: 페르소나 이름·문제 수. 동작: `POST /golden/session`(닉네임 `sim-<페르소나>`) → 문제마다 `GET /golden/next` → 학생 LLM에게 "문제 본문 + 지금까지 튜터 말 + 페르소나 지시"를 주고 다음 입력 문장을 받아 `POST /golden/answer` → `graded`가 올 때까지 반복(최대 4회) → 다음 문제. HTTP는 `httpx`로 `golden.api:app`을 직접 부른다(`httpx.ASGITransport` — 서버를 따로 띄우지 않아도 된다). 학생 LLM도 공통 규칙 8번대로 `build_cloud_provider()`를 통해 부르고, `GOLDEN_FAKE_LLM=1`이면 페르소나별 고정 대본(문제당 오답 1회 → 정답)을 쓴다.
  2. 페르소나 3종을 `golden/sim_personas.md`에 한국어로 적는다(제안값, 각 200자 이내). ①`slope-blind`: 기울기 개념이 없어 두 점이 주어지면 y값 차이만 답한다 ②`sign-slip`: 음수 계산에서 부호를 자주 틀린다(−3×5를 15로) ③`no-setup`: 식 세우기 문제에서 식 대신 숫자 하나를 찍는다. 공통 말투 지시: 중2 어투, 한 문장 15자 안팎, 모르면 "모르겠어요"·"이게 뭐예요?"를 쓴다, 튜터가 되물으면 그 질문에만 짧게 답한다, **정답을 아는 척하지 않는다**. 저장소의 오개념 DB(`data/corpus/misconceptions_v1/misconceptions.json`)에서 일차함수 항목을 읽어 페르소나 서술에 참고할 수 있다 — 튜터가 아니라 **시뮬레이터 입력**으로만 쓴다(§5 위반 아님).
  3. 실행: `cd src/backend && python -m golden.sim_student --persona slope-blind --problems 10`을 페르소나 3종에 대해 돌린다(실제 LLM 사용 — 비용은 문제당 학생 LLM 최대 4회 + 튜터 최대 3회, 30문제면 약 210회 호출. OpenRouter deepseek 기준 수백 원 수준이지만 실행 전에 보고에 예상 호출 수를 적는다). 각 실행의 turns를 `golden/logs/sim_<페르소나>_turns.csv`로 저장한다.
  4. 테스트 `tests/golden/test_sim_student.py`: `GOLDEN_FAKE_LLM=1`에서 페르소나 1종·문제 2개를 돌려 ①turns 행이 생기고 ②모든 문제가 `graded`로 끝나며 ③학생 LLM 입력에 닉네임·session_id가 섞이지 않음을 확인한다.
  5. 보고에 페르소나별 표(문제 ID·턴 수·판정·튜터가 오개념을 짚었는가 예/아니오)와 "시뮬레이션 한계" 절(학생 LLM이 너무 잘 풀거나 정형화된 오답만 낸 건수를 세어 적는다 — 30건 중 N건이 "비현실적"으로 보이면 그 수를 그대로 적는다).
- **산출물:** `sim_student.py`, `golden/sim_personas.md`, 테스트 1파일, turns CSV 3건, 보고.
- **완료 기준:** ①로그 30건(3×10) ②`tests/golden` 초록 ③페르소나별 표와 한계 절 ④학생 LLM 프롬프트에 개인정보 0건(닉네임도 `sim-*`뿐).
- **하지 말 것:** 시뮬레이터를 튜터 코드에 섞지 않는다(`api.py`·`tutor.py` 수정 금지). 페르소나를 4종 이상 만들지 않는다. 결과가 마음에 안 든다고 페르소나를 튜터에 유리하게 고치지 않는다.
- **막히면:** 학생 LLM이 지시를 어기고 정답을 바로 내면(10문제 중 5개 이상 1턴 정답) 페르소나 지시에 "첫 입력은 반드시 질문 또는 오답" 한 줄을 추가해 1회만 재실행하고, 두 실행 결과를 모두 보고한다.

### S10. 로그 수정 — S9·S11에서 나온 것만

- **목적:** S9(본인)와 S11(AI 시뮬레이션) 로그가 가리킨 문제만 고친다. 로그에 없는 것은 고치지 않는다.
- **선행 산출물:** S9 보고의 후보 3개, S11 보고의 페르소나별 표.
- **할 일:**
  1. 두 보고의 후보를 합쳐 "재현 방법 → 원인 파일 → 고칠 범위(golden/ 안인가) → 출처(본인/AI)"를 표로 적는다. **본인과 AI 양쪽에서 나온 항목을 먼저** 고친다.
  2. `golden/` 안에서 고칠 수 있는 것만 고친다. 하나 고칠 때마다 그 버그를 재현하는 테스트를 먼저 빨강으로 만든 뒤 초록으로 바꾼다. 재현에는 S11의 turns CSV 입력을 그대로 `POST /golden/answer`로 재생하는 방식을 쓸 수 있다.
  3. 옛 코드를 고쳐야 하는 항목이면 `golden/`으로 복사해 고치거나 LATER.md에 적고 보고한다.
  4. 튜터 프롬프트 수정은 1회까지(S8에서 썼으면 이번엔 쓰지 않는다).
  5. `tests/golden`·`flutter test` 초록, 정적 검사 4종 초록. PR 1개.
- **산출물:** 버그 수정 PR 1개(항목별 커밋), 재현 테스트 N건.
- **완료 기준:** ①고친 항목마다 S9 또는 S11 로그의 줄 번호가 커밋 메시지에 있다 ②항목마다 수정 전 빨강·수정 후 초록 기록 ③로그에 없는 변경 0건(`git diff --stat`을 보고에 붙인다).
- **하지 말 것:** "이왕 고치는 김에" 금지. AI 시뮬레이션에서만 나온 항목 중 "학생 LLM의 비현실적 입력" 때문인 것은 고치지 않고 FINDINGS 후보로만 남긴다.

### S12. 성인 2명 + 시뮬레이션 재실행 — 회귀 확인

- **목적:** 수정된 앱을 사람 2명(성인 지인)이 혼자 쓰고, S11 시뮬레이션을 같은 페르소나로 재실행해 S10 수정이 효과가 있었는지 본다.
- **선행 산출물:** S10 머지.
- **할 일:**
  1. (Kiki) 성인 지인 2명에게 각각 5문제를 혼자 풀게 한다(조작 설명 없이, 닉네임 `adult-1`·`adult-2`). 끝나면 "어느 순간이 제일 답답했어요?"와 "다시 할래요?"를 묻고 기록한다. 관찰 기록은 `golden/LOG_TEMPLATE.md` 양식, turns는 CSV로.
  2. (AI 세션) S11의 페르소나 3종 × 10문제를 **같은 설정으로 재실행**하고 `golden/logs/sim_<페르소나>_rerun_turns.csv`로 저장한다. S11 결과와 문제별로 대조해 "S10 수정 항목이 재발했는가"를 표로 적는다.
  3. 보고에 누적 로그 표(본인 5 + AI 30 + 성인 10 + AI 재실행 30)와 출처별 건수를 적는다.
- **산출물:** 관찰 기록 2건 + CSV 2건, 재실행 CSV 3건, 대조 표, 보고.
- **완료 기준:** ①성인 2명 각 5문제 기록 ②재실행 30건 ③S10 수정 항목별 재발 여부가 적혀 있다.
- **하지 말 것:** 세션 중 수정 금지. 성인이 쉽게 푼 것을 "학생도 쉽다"로 해석하지 않는다.
- **막히면:** 성인 2명을 못 구하면 Kiki가 `self-2` 닉네임으로 S9의 역할 규칙대로 한 번 더 하고 보고에 "본인 2회차"로 적는다.

## S13~S15: 수확과 회고 (3주차 끝)

### S13. 로그 분석 — golden/FINDINGS.md

- **목적:** 로그 30건에서 가장 자주 끊기는 지점 **1개**를 숫자로 적는다. 이것이 S14가 고칠 유일한 것이다.
- **선행 산출물:** S9(본인)·S11(AI 시뮬레이션)·S12(성인 + 시뮬레이션 재실행)의 로그와 turns CSV, `golden.turns` 전체.
- **할 일:**
  1. `golden.turns` 전체를 CSV로 뽑는다(닉네임·session_id 제외, 피험자는 `self-1`·`sim-slope-blind`·`adult-1` 같은 출처 라벨로 치환). 문제 단위로 집계: 문제 ID·피험자·출처(본인/AI/성인)·튜터 턴 수·판정·소요 시간(첫 턴~graded). **출처별로 표를 나눈다** — 세 출처를 합산한 숫자는 어디에도 쓰지 않는다.
  2. "끊김"을 정의한다(제안값, FINDINGS.md 첫 절에 적는다): ①3턴 소진 후 오답 판정 ②한 문제에 5분 이상 ③학생이 앱을 닫거나 "모르겠어요"를 2회 이상 반복 ④관찰 기록의 "막힌 지점". 각 문제 기록을 이 4종으로 태깅한다.
  3. 끊김을 단계별(GP-2 문제 이해 / GP-3 입력 방식 / GP-4 튜터 되묻기 품질 / GP-5 판정 오류 / GP-6 결과 이해)로 분류해 **출처별**로 "N건 중 M건" 표를 만든다. 문항별 표(어느 문항이 가장 많이 끊겼나)도 출처별로 만든다. 1위 지점은 **두 출처 이상에서 공통으로 1·2위인 것**을 고른다. 한 출처에서만 1위면 그 사실을 적고, 사람 출처(본인·성인)가 AI 출처보다 우선한다.
  4. 판정 오류 의심(학생이 맞게 썼는데 오답 처리)은 전수 재채점해 건수를 적는다 — 이것은 끊김 1위와 무관하게 S14 앞에 고친다(채점 버그는 신뢰의 문제).
  5. `golden/FINDINGS.md`: ##**피험자 한계(첫 절 — 실제 중학생 0명, 본인 N건·AI 시뮬레이션 N건·성인 N건이며 결론은 실제 학생으로 재검증 전까지 잠정)** ##정의 ##출처별 단계별 표 ##출처별 문항별 표 ##판정 오류 ##**1위 끊김 지점(출처별 N건 중 M건, 근거 로그 3개 인용 — 사람 출처 1개 이상 포함)** ##2·3위(참고) ##S14 제안(1위를 고치는 가장 작은 변경 한 가지, 옛 자산 중 필요한 최소 조각 명시).
- **산출물:** `golden/FINDINGS.md`, 집계 CSV(`golden/reports/S13/`).
- **완료 기준:** ①1위 끊김 지점이 출처별 "N건 중 M건" 형식의 숫자로 있고 근거에 사람 출처 로그가 1개 이상 있다 ②정의 4종이 적혀 있고 태깅 근거가 로그 줄과 연결된다 ③판정 오류 건수가 0이 아니면 재채점 결과와 함께 적혀 있다 ④S14 제안이 한 가지뿐이다 ⑤첫 절이 피험자 한계다.
- **하지 말 것:** 고치지 않는다. 2위·3위까지 고치자고 제안하지 않는다. 로그에 없는 원인을 적지 않는다. AI 시뮬레이션에서만 나온 끊김을 "학생이 여기서 끊긴다"로 쓰지 않는다("시뮬레이션 학생이 끊겼다"로 쓴다).

### S14. 개선 1개 — FINDINGS의 1위만

- **목적:** S13이 가리킨 1개만 고친다. 이때 비로소 옛 자산(루브릭·오개념 DB·힌트 규칙) 중 그 1개에 필요한 **가장 작은 조각**만 꺼낸다.
- **선행 산출물:** `golden/FINDINGS.md`의 1위 지점과 S14 제안.
- **할 일:**
  1. FINDINGS의 1위와 제안을 그대로 읽는다. 제안이 두 가지 이상이면 멈추고 보고한다.
  2. 옛 자산이 필요하면 그 조각만 `golden/`으로 복사한다(예: "튜터가 힌트를 너무 빨리 준다"면 루브릭 전체가 아니라 힌트 타이밍 규칙 1줄을 `tutor_prompt.md`에 넣는다. "판정 오류"면 `l3/equivalent/canonicalize.py`에서 해당 정규화 함수 1개만). HARVEST.md에 적는다.
  3. 재현 테스트를 먼저 빨강으로 만든 뒤 고친다. 1위 유형에 해당한 기록을 재생해(turns CSV의 학생 입력을 그대로 `POST /golden/answer`로 보내) 수정 전후 결과를 **출처별로** 비교한 표를 보고에 붙인다. 가능하면 S11의 시뮬레이션 3종도 재실행해 수정 후 끊김 수를 함께 적는다.
  4. `tests/golden`·`flutter test`·정적 검사 초록. PR 1개.
- **산출물:** PR 1개, 재현 테스트, 수정 전후 비교 표, HARVEST.md 1줄.
- **완료 기준:** ①변경 파일이 전부 `golden/` 아래다 ②1위 유형 기록 M건을 재생했을 때 수정 후 끊김 수가 줄었다(숫자) ③다른 유형의 결과가 나빠지지 않았다(전체 재생 N건 표).
- **하지 말 것:** 2위를 함께 고치지 않는다. 옛 자산을 모듈 단위로 통째로 가져오지 않는다.

### S15. 격리·회고 — /legacy 이동, RETRO.md, 다음 3주

- **목적:** 3주간 한 번도 import되지 않은 옛 모듈을 `/legacy`로 옮기고, 회고와 다음 3주 계획을 쓴다.
- **선행 산출물:** S14 머지, HARVEST.md 전체, `golden/STATE.md` Q7.
- **할 일:**
  1. 미참조 모듈 목록을 **측정**한다: `src/backend`에서 grimp로 `golden` 패키지의 상류(`find_upstream_modules`, 즉 golden이 직간접 import하는 whymath_backend 모듈)를 구하고, 전체 `whymath_backend` 모듈에서 빼 "golden이 쓰지 않는 모듈" 목록을 만든다. Flutter도 `lib/golden/`·`main_golden.dart`가 import하는 파일을 전수 열거한다. 목록을 HARVEST.md "## 3주간 미참조 모듈" 절에 붙인다(경로·줄 수).
  2. **/legacy 이동은 Kiki 결정 사항이다.** 이 세션은 이동 PR을 **초안**으로 만들되(`git mv src/backend/whymath_backend legacy/whymath_backend` 식의 통째 이동이 아니라, 1단계 목록의 모듈만), 다음 두 가지를 먼저 보고하고 Kiki의 "진행"을 받은 뒤 push한다: ①이동 대상 수·줄 수 ②이동 시 깨지는 것(옛 `create_app`·옛 테스트 1,109파일·CI 잡·import-linter 계약)과 그 대처(제안: 옛 앱과 옛 테스트는 `legacy/`에서 그대로 돌게 CI 잡의 경로만 바꾸거나, 1차로는 "이동 목록 확정 + `legacy/README.md`에 목록 기록"까지만 하고 물리 이동은 다음 3주 첫 세션으로 넘긴다). Kiki가 결정하지 않으면 물리 이동 없이 목록 기록으로 종료하고 보고에 "Kiki 결정 대기"로 적는다.
  3. `golden/RETRO.md`: ①계획 대비 실제(세션별 완료 기준 충족 여부 표) ②§6 완료 판정 5줄 각각 예/아니오와 근거 — **첫 줄(실제 중학생 5명)은 이 변형에서는 구조적으로 "아니오"다.** 그 줄을 "아니오(대체 피험자: 본인 N·AI N·성인 N)"로 적고, 원래 기준을 낮출지("학생 또는 대체 피험자 5명")·실제 학생 검증을 다음 3주의 첫 세션으로 둘지는 **Kiki가 결정**한다. 세션은 두 선택지의 장단을 3줄씩 적어 둔다 ③범위 밖으로 나가려다 멈춘 순간 목록(각 세션 보고 ⑤를 모음) ④LATER.md 항목 수와 상위 5개 ⑤잘된 것 3·안 된 것 3.
  4. 다음 3주 계획을 `golden/NEXT_3WEEKS.md`에 쓴다 — **첫 세션은 "실제 중학생 1명 검증"(원본 묶음의 S9 지시문 그대로)**, 그다음 FINDINGS의 2위·3위와 LATER.md 순서대로. 세션 번호는 S16부터 이어 붙인다. 계획서 형식을 새로 만들지 않고 이 문서의 §2 표 형식을 그대로 쓴다.
  5. `tests/golden` 초록 확인(이동이 없으면 그대로, 이동했으면 다시). PR.
- **산출물:** HARVEST.md 미참조 목록, (Kiki 승인 시) /legacy 이동 PR, `golden/RETRO.md`, `golden/NEXT_3WEEKS.md`.
- **완료 기준:** ①미참조 모듈 목록이 측정 명령과 함께 HARVEST.md에 있다 ②RETRO.md의 §6 5줄에 전부 예/아니오가 적혀 있고 첫 줄에 대체 피험자 내역과 Kiki 결정 요청이 있다 ③NEXT_3WEEKS.md의 첫 세션이 실제 학생 검증이다 ④/legacy 이동은 Kiki 결정 기록(진행/보류)과 함께 끝나 있다.
- **하지 말 것:** 옛 모듈을 삭제하지 않는다(이동만). `golden/`을 `app/`으로 이름 바꾸지 않는다(그건 과목 2개째가 생길 때). 다음 계획에 §5 항목을 로그 근거 없이 넣지 않는다.
- **막히면:** 첫 줄을 제외한 §6 4줄 중 2개 이하가 "예"면 RETRO에 "3주 반복"을 적고 NEXT_3WEEKS.md는 같은 S번호(S9~S15)를 반복하는 계획으로 쓴다.
