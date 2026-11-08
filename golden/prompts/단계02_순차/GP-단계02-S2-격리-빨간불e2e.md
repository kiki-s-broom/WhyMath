세션 이름: GP-단계02-S2-격리-빨간불e2e

# [WhyMath 골든 패스] 작업 S2: 격리 — golden/ 자리 만들기와 빨간불 e2e

> **사용법:** 새 세션을 열고 세션 이름을 `GP-단계02-S2-격리-빨간불e2e`(이 파일 이름)으로 정한다. 아래 "작업 환경"이 맞는지 보고, 이 파일 전체를 그대로 붙여 넣는다.

## 작업 환경

- 저장소 위치: GitHub `kiki-s-broom/whymath` · Kiki 머신 `C:\Users\kiki\Desktop\__AI\WhyMath`(PowerShell) · 클라우드 세션 `/home/user/WhyMath`
- 산출물 폴더: 저장소 안의 `golden/reports/` (없으면 만든다)
- 기본 브랜치: main · 작업 브랜치: `golden/S2` (아래 "산출물 저장 규칙")
- 계획서: 저장소 안 `golden/prompts_src/plan_golden_path_3weeks.html` (2026-11-08 Kiki 계획서 원본) · 지시서 원본 `golden/prompts_src/spec.md`

## 너의 역할

너는 WhyMath(와이매스) 골든 패스 스켈레톤 3주 프로젝트에서 **작업 S2만** 맡은 AI다. 이 지시문에 적힌 일만 하고, 끝나면 정해진 형식으로 보고한다.
세션 제목을 바꾸는 기능이 있으면 이 세션 제목을 `GP-단계02-S2-격리-빨간불e2e`으로 바꾼다. 없으면 이 줄은 건너뛴다.

## 실행 방식

- **실행 단계:** 2단계 (전체 13단계 중)
- **실행 방식: 순차 (단독).** 2단계에는 이 작업 하나뿐이다. 앞 단계가 끝난 뒤 이 세션만 실행한다.
- **여유: 없음 (크리티컬 패스).** 이 작업이 늦어지면 전체가 늦어진다.

## 프로젝트 배경

- WhyMath(와이매스)는 한국 중·고등학생용 AI 수학 학습 앱이다("답이 아닌, 이유를 묻는 수학"). 저장소에는 PR 1,800여 건·백엔드 테스트 파일 1,100여 개·7계층 아키텍처 문서가 쌓였지만, **실제 학생 1명이 문제 1개를 끝까지 푸는 경로가 돌아가는지는 확인된 적이 없다.**
- 2026-11-08 결정(Kiki): 3주(작업 세션 15회, 세션당 2~4시간) 안에 경로 하나만 완성한다 — **실제 학생 1명이 Flutter 앱에서 중2 일차함수 문제 1개를 소크라테스 대화로 끝까지 풀고, 숙련도 숫자 하나가 PostgreSQL에 갱신된다.** 이것이 완료 정의이고 그 밖의 모든 것은 "지금이 아니다".
- 방식은 스트랭글러 피그다. 옛 코드는 한 줄도 고치지 않고 import만 한다. 새 코드는 `golden/`(문서·데이터), `src/backend/golden/`(파이썬), `src/mobile/lib/golden/`(Flutter), `tests/golden/`(테스트)에만 쓴다. 옛 코드를 고쳐야 돌아가면 `golden/` 아래로 복사해서 고치고 `golden/HARVEST.md`에 한 줄 적는다.
- 학생 경로는 여섯 단계다: GP-1 세션 시작(닉네임만) → GP-2 문제 제시(30문항 순서대로) → GP-3 텍스트 답변 → GP-4 튜터 되묻기(LLM 1회 호출·최대 3턴) → GP-5 정답 판정(SymPy 비교) → GP-6 숙련도 갱신(+0.10/−0.05) → 다시 GP-2. HTTP 엔드포인트는 3개뿐이다.
- 완료 기준은 `tests/golden/` 초록 하나다. S2가 일부러 빨간불 e2e 테스트를 심고, S5가 처음 초록으로 만든다. 그 뒤로 빨간불인 채 머지되는 PR은 없다. 범위를 넓히려는 제안에는 "§5(3주간 하지 않을 것)"라고만 답한다 — 지식 추적(BKT)·OCR·의도 분류·다과목·회원가입·옛 코드 리팩토링은 전부 그 목록에 있다.
- 일정: 1주차 백엔드(S1~S5), 2주차 Flutter와 첫 학생(S6~S9), 3주차 학생 5명과 수확(S10~S15). 11/9(월) 시작이면 11/29(토) 종료. 한 세션에 산출물 하나. 산출물이 안 나오면 다음 세션은 같은 번호를 반복하되 범위를 넓혀 만회하지 않는다.
- 가장 큰 리스크는 1,800개 PR을 만든 습관이 "이왕 하는 김에"라는 말로 돌아오는 것이다. 그 말이 나오면 세션을 끝내고 다음 날 다시 연다.

## 이 작업의 위치

- 레인: 측정·격리
- 선행 작업과 그 산출물 위치:
    - S1 (상태 측정 — golden/STATE.md) → `golden/reports/S1/`
- 이 작업의 결과를 쓰는 다음 작업: S3, S4
- 이 작업은 **관문 ①**이다. 보고에 판정(go 또는 no-go)을 반드시 적는다.
- 레인 메모: S1은 코드를 한 줄도 고치지 않고 현재 상태를 잰다. S2는 S1 결과 위에 새 경로가 살 자리를 만들고 **일부러 빨간불인** e2e 테스트를 CI에 심는다. H1은 사람(Kiki)의 일이며 S1과 동시에 시작한다.

## 공통 규칙 (작업보다 먼저 지킨다)

규칙과 작업 지시가 충돌하면 규칙이 우선한다.

1. **읽을 범위:** 이 지시문과, 이 지시문이 "선행 산출물"로 적은 결과물만 읽는다. 다른 작업 번호의 일은 하지 않는다.
2. **선행 작업 확인:** 선행 작업마다 `golden/reports/<번호>/보고.md`가 있고 결과가 "완료"인지 확인한다. 관문 작업(S2, S5, S8)은 판정이 go인지도 확인한다. 하나라도 아니면 시작하지 말고, 비어 있는 번호를 보고하고 멈춘다.
3. **golden/ 바깥은 읽기 전용:** 새 코드는 저장소의 `golden/`(백엔드 파이썬은 `src/backend/golden/`, Flutter는 `src/mobile/lib/golden/`, 테스트는 `tests/golden/`)에만 쓴다. 옛 코드를 고쳐야 돌아가면 고치지 말고 `golden/` 아래로 복사해서 고치고, `golden/HARVEST.md`에 "가져온 것 / 버린 것 / 이유" 한 줄을 적는다. **예외는 S2 한 세션의 "배선 파일" 4개뿐**이다 — ①`CLAUDE.md` 맨 위 블록 ②`.github/workflows/ci.yml` ③`.github/pull_request_template.md` ④`src/backend/pyproject.toml`의 `packages`·`[tool.importlinter]`. `src/mobile/pubspec.yaml`은 어떤 세션도 건드리지 않는다(새 패키지 추가 금지). `constitution/` 폴더는 어떤 세션도 건드리지 않는다(가드 훅이 막는다. 막히면 우회하지 않고 멈춘다).
4. **범위 고정:** 중2 일차함수 1단원·문항 30개·학생 경로 GP-1~GP-6·HTTP 엔드포인트 3개(`POST /golden/session`, `GET /golden/next`, `POST /golden/answer`)가 전부다. 네 번째 엔드포인트, 새 추상화(베이스 클래스·인터페이스·플러그인 구조), 지식 추적(BKT), OCR, 의도 분류, 다과목, 회원가입·인증, 옛 코드 리팩토링·삭제는 제안하지 않는다. 떠오르면 `golden/LATER.md`에 한 줄 적고 넘어간다. "이왕 하는 김에"라는 생각이 들면 그 자리에서 멈추고 보고한다.
5. **완료 기준은 tests/golden 초록:** 코드를 건드린 세션은 끝날 때 `cd src/backend && python -m pytest ../../tests/golden`을 돌리고 **exit code**로 판정한다(`-q`·`| tail`로 출력을 줄이지 않는다). 빨간불이면 PR을 만들지 않는다. 유일한 예외는 S2다(S2는 빨간불이 성공이다).
6. **모르는 값은 추정 금지:** 경로·테이블·함수 이름처럼 지시에 없는 값은 먼저 저장소에서 찾는다. 이 문서의 "사전 실측(2026-11-08·main `62bcbecc`)" 값도 세션에서 다시 확인하고, 다르면 보고에 적는다. 못 찾으면 "미확인"으로 적고 그 부분만 멈춘다.
7. **검증은 CI와 같은 명령으로:** 백엔드 CI 잡이 쓰는 정적 검사 4종을 `src/backend`에서 그대로 돌린다 — `python -m ruff check . ../../tests/golden`, `python -m black --check --line-length 100 . ../../tests/golden`, `python -m mypy --strict golden`, `lint-imports`. Flutter를 건드렸으면 `src/mobile`에서 `flutter analyze`와 `flutter test`를 돌린다. 판정은 항상 exit code이며 보고에 숫자(통과 N건·소요 시간)를 적는다.
8. **LLM 호출 규칙:** 튜터의 LLM 호출은 옛 코드의 프로바이더 팩토리(`whymath_backend.l3.providers.factory.build_cloud_provider()` → `LLMProvider.generate`)를 통해서만 한다. SDK 직접 호출·API 키 하드코딩 금지. 2026-12-31까지 Anthropic API는 사용 중단이라 기본 클라우드 좌석은 OpenRouter(`deepseek/deepseek-v4.1-flash`)이고, 로컬은 Ollama(`qwen` 계열)다. **테스트와 CI는 실제 LLM을 부르지 않는다** — 환경변수 `GOLDEN_FAKE_LLM=1`이면 고정 문장을 돌려주는 가짜 프로바이더를 쓴다.
9. **미성년자 데이터:** 학생 식별자는 닉네임 문자열뿐이다. 실명·학교·학년·연락처는 어디에도 저장하지 않는다. 대화 로그는 로컬 PostgreSQL(`golden` 스키마)에만 쌓고, LLM에는 문제 본문과 학생이 친 텍스트만 보낸다(닉네임·세션 ID 제외). 학생 세션 전에는 보호자 동의를 받는다(Kiki 담당).
10. **하네스·커밋·PR:** 코드나 문서를 바꾸는 세션은 첫 행위로 `python3 scripts/harness/backlog.py start <태스크 ID>`를 실행한다. 태스크 ID는 S2가 `backlog.py add`로 받아 `golden/STATE.md` 맨 아래에 적어 둔 것을 쓴다(번호를 눈으로 짓지 않는다. S1은 문서만 만들므로 claim 없이 진행). 커밋 메시지는 `S<번호>: <한 줄>` 형식(예: `S4: golden/api.py 엔드포인트 3개`). 작업이 끝나면 PR을 열고, PR 본문 첫 질문 "이 PR이 전진시키는 학생 단계"에 GP 번호를 적는다. 적을 수 없으면 PR을 만들지 않고 이유를 보고한다. main 머지는 Kiki가 한다.
11. **한국어:** 코드 주석·문서·보고는 한국어로 쓴다(식별자는 영어).
12. **종료 보고 5줄:** 완료 보고 형식 외에 다음 5줄을 답변 끝에 반드시 쓴다 — ①완료 기준 충족 여부(아니오면 어디까지) ②tests/golden 결과(초록/빨강·테스트 N개) ③HARVEST.md에 오늘 추가한 줄 ④LATER.md에 오늘 추가한 줄 ⑤오늘 범위 밖으로 나가려다 멈춘 순간.

## 용어

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
| 하네스 | `scripts/harness/backlog.py`. 이 저장소의 작업 대장. 코드 변경은 `start`(claim)로 시작하고 `done`에 PR 증적이 필요하다 |
| 사전 실측 | 이 지시서를 쓰며 2026-11-08에 main `62bcbecc` 기준으로 직접 확인한 값. 세션에서 재확인한다 |

## 공유 계약 (모든 세션이 같은 모양을 쓴다 — 바꾸려면 보고하고 멈춘다)

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

## 작업 지시: S2. 격리 — golden/ 자리 만들기와 빨간불 e2e

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

## 산출물 저장 규칙

- 이 작업에서 만든 문서, 표, 보고서는 모두 `golden/reports/S2/`에 저장한다.
- 코드 변경은 저장소의 기존 위치에 하되, git을 쓰는 저장소라면 `golden/S2` 브랜치에서 작업하고 기본 브랜치에 직접 반영하지 않는다.
- 마지막으로 `golden/reports/S2/보고.md`에 아래 형식의 완료 보고를 쓰고, 같은 내용을 답변으로도 보여준다.

## 완료 보고 형식

```
작업 번호: S2
결과: 완료 | 일부 완료 | 중단
판정: go | no-go (근거 수치 포함)
만든 것: 파일·테이블·화면 이름 (경로 포함)
완료 기준 확인: 항목별 통과/실패와 근거 (실행한 명령 또는 본 화면)
미확인·가정한 것: 없으면 "없음"
다음 작업이 알아야 할 것: 없으면 "없음"
```

## 시작 순서

1. 공통 규칙 2번대로 선행 작업의 `보고.md`를 확인한다.
2. "작업 지시"의 할 일을 순서대로 수행한다.
3. "완료 기준"을 하나씩 확인하고 결과를 기록한다.
4. `golden/reports/S2/보고.md`를 쓰고 보고한다.
