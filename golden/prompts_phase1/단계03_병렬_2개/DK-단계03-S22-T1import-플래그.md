세션 이름: DK-단계03-S22-T1import-플래그

# [WhyMath 1단계 두꺼게] 작업 S22: T1 import — src/backend/golden/eval/ + 플래그 GOLDEN_T1_RUBRIC

> **사용법:** 새 세션을 열고 세션 이름을 `DK-단계03-S22-T1import-플래그`(이 파일 이름)으로 정한다. 아래 "작업 환경"이 맞는지 보고, 이 파일 전체를 그대로 붙여 넣는다.

## 작업 환경

- 저장소 위치: GitHub `kiki-s-broom/whymath` · Kiki 머신 `C:\Users\kiki\Desktop\__AI\WhyMath`(PowerShell) · 클라우드 세션 `/home/user/WhyMath`
- 산출물 폴더: 저장소 안의 `golden/reports_phase1/` (없으면 만든다)
- 기본 브랜치: main · 작업 브랜치: `golden-p1/S22` (아래 "산출물 저장 규칙")
- 계획서: 저장소 안 `golden/prompts_src/plan_phase1_thicken_4weeks.pdf` (2026-11-15 Kiki 계획서 원본 12쪽) · 지시서 원본 `golden/prompts_src/spec_phase1.md` · 선행 묶음 `golden/prompts/`(골든 패스 S1~S15)

## 너의 역할

너는 WhyMath(와이매스) 1단계 「두꺼게」 3+AI 4주 프로젝트(골든 패스 S1~S15의 후속)에서 **작업 S22만** 맡은 AI다. 이 지시문에 적힌 일만 하고, 끝나면 정해진 형식으로 보고한다.
**첫 행위(0단계)로 세션 제목을 등록한다**: 클라우드 세션(claude.ai/code)이면 `claude-code-remote`의 `set_session_title` 도구를 `session_id` 생략·`title="DK-단계03-S22-T1import-플래그"`으로 호출한다. 그 도구가 없는 환경(터미널 Claude Code)이면 사용자에게 `/rename DK-단계03-S22-T1import-플래그` 한 줄을 안내하고 진행한다. 어느 쪽이든 결과를 완료 보고 첫 줄에 적는다. (이 파일 첫 줄 `세션 이름:`을 저장소 훅이 읽어 `golden/SESSIONS.md`에도 자동 기록한다.)

## 실행 방식

- **실행 단계:** 3단계 (전체 17단계 중)
- **실행 방식: 병렬 가능.** 같은 3단계의 S19와 동시에 다른 세션에서 실행해도 된다.
- **병렬 주의:** 동시에 도는 다른 세션과 같은 파일을 고치게 되면, 자기 브랜치에서만 고치고 합칠 때 충돌을 보고한다.
- **여유:** 늦어도 4단계 안에만 끝나면 전체 일정이 밀리지 않는다.

## 프로젝트 배경

- WhyMath(와이매스)는 한국 중·고등학생용 AI 수학 학습 앱이다("답이 아닌, 이유를 묻는 수학"). 2026-11-08~11-15 골든 패스 3주(S1~S15)로 **실제로 끝까지 도는 경로 하나**가 생겼다: 중2 일차함수 30문항, 닉네임 세션 → 문제 → 텍스트 답변 → 튜터 되묻기(최대 3턴) → SymPy 채점 → 숙련도 ±. 서버 `golden.api:app`, 앱 `lib/main_golden.dart`, 코드 `src/backend/golden/`, e2e `tests/golden/`.
- 골든 패스의 로그 분석(`golden/FINDINGS.md`)은 대체 피험자(본인·성인·AI 시뮬레이션 3종)로 했고 **실제 중학생은 0명**이었다. 1위 끊김 지점은 GP-4 튜터 마지막 되묻기가 학생의 틀린 곳을 짚지 않는 것(C5)이었고 S14가 프롬프트 규칙 한 문장으로 고쳤다. 2·3위 후보(판정 오류 앞말형·문제 이해)는 AI 출처에서만 나왔다.
- 2026-11-15 결정(Kiki): 4주(세션 20회 S16~S35, 12/1~12/26) 안에 같은 단원을 **두껍게** 만든다 — 넓히지 않는다. 트랙은 둘이다. **진실 트랙** = 실제 중학생 3~5명·누적 세션 50건·"튜터가 쓸 만한가"·완료율이 게이트. **회귀 트랙** = AI 학생 시뮬레이터(30문항 × 페르소나 8개 × 3회 = 720세션)·"튜터가 망가지지 않았나"·치명 실패 0건이 게이트. 둘은 서로를 대체하지 않는다.
- 원칙 셋이 골든 패스의 셋(옛 코드 수정 금지·범위 고정·e2e가 완료 기준) 위에 더해진다. ①모든 PR은 `golden/FINDINGS.md`의 항목 번호 `F-NN`을 인용한다 — 없으면 지금 할 일이 아니다. ②옛 자산은 한 번에 하나씩 다섯 걸음(경계 긋기 → 특성화 테스트 → 복사/import → 플래그 뒤 연결 → 초록 확인)으로 가져온다. ③시뮬레이터는 보정 검사(S20)를 통과하기 전까지 튜터 판단에 쓰지 않는다.
- 일정: 4주차(S16~S20) 시뮬레이터 — 시드·주입기·학생 모델·러너+야간 CI·보정. 5~7주차는 두꺼게 슬롯 T1(튜터 되묻기 품질)·T2(오개념 조회)·T3(숙련도 BKT)을 한 주에 하나씩 — 설계 → import → 적용+AI 회귀 → 실학생 세션 → 판정. 매주 실학생 세션 앞에 AI 720세션을 먼저 돌린다. S35(12/26)에 게이트 여섯 줄을 판정한다. 완료 기준을 못 채우면 다음 세션은 같은 번호를 반복한다.
- 저장소 사실이 계획서 전제와 다른 곳 넷은 공유 계약 첫 표에 있다(실학생 0명 · `rubric.yaml` 없음 · 일차함수 오개념 8건 · CI에 LLM 키 없음). 지시문은 저장소 사실을 따르고, 계획서 숫자(15~25개·CI 자동 실측)는 "있으면"으로 읽는다.
- 가장 큰 리스크는 시뮬레이터가 재미있다는 것이다. 720세션이 밤마다 돌고 숫자가 찍히면 그것이 제품처럼 느껴진다. 하지만 1단계의 게이트는 실학생 50건이고, 시뮬레이터는 그 50건을 창피하지 않게 만드는 장치일 뿐이다.

## 이 작업의 위치

- 레인: 슬롯 T1 되묻기 품질
- 선행 작업과 그 산출물 위치:
    - S21 (T1 설계 — FINDINGS 순위 재확인 + 특성화 테스트) → `golden/reports_phase1/S21/`
- 이 작업의 결과를 쓰는 다음 작업: S23
- 레인 메모: 슬롯은 한 주에 하나다. 설계(S21)는 S16만 있으면 시작할 수 있어 시뮬레이터 작업과 **동시에** 간다. import(S22)는 설계 다음, 적용+AI 회귀(S23)는 보정 통과(S20) 뒤에만 한다. 그다음 실학생 1차(S24)와 판정(S25).

## 공통 규칙 (작업보다 먼저 지킨다)

규칙과 작업 지시가 충돌하면 규칙이 우선한다.

1. **읽을 범위:** 이 지시문과, 이 지시문이 "선행 산출물"로 적은 결과물만 읽는다. 다른 작업 번호의 일은 하지 않는다.
2. **선행 작업 확인:** 선행 작업마다 `golden/reports_phase1/<번호>/보고.md`가 있고 결과가 "완료"인지 확인한다. 관문 작업(S20, S25, S30, S34, S35)은 판정이 go인지도 확인한다. 하나라도 아니면 시작하지 말고, 비어 있는 번호를 보고하고 멈춘다.
3. **golden/ 바깥은 읽기 전용:** 새 코드는 `src/backend/golden/`(파이썬 패키지 — 하위 `sim/`·`eval/`·`mastery/`), `golden/`(문서·데이터·로그), `src/mobile/lib/golden/`(Flutter), `tests/golden/`(테스트)에만 쓴다. 옛 코드를 고쳐야 돌아가면 고치지 말고 `golden/` 아래로 복사해서 고치고 `golden/HARVEST.md`에 "가져온 것 / 버린 것 / 이유 / 세션" 한 줄을 적는다. 예외는 **S19 한 세션의 배선 파일 1개**(`.github/workflows/golden-sim-nightly.yml` 신설)와, 생성기·훅처럼 이미 `golden/` 밖에 있는 **지시문 묶음 자체의 장치**뿐이다. `constitution/`은 어떤 세션도 건드리지 않는다(가드 훅이 막는다. 막히면 우회하지 않고 멈춘다). `golden/` 바로 아래에 `.py`를 두지 않는다 — `tests/infra/test_lint_coverage.py`가 어떤 CI 린트에도 안 걸리는 `.py`를 막는다(S13 실측). 코드는 전부 `src/backend/golden/` 아래다.
4. **범위 고정:** 중2 일차함수 1단원·문항 30개·GP-1~GP-6·HTTP 엔드포인트 3개는 그대로다. 1단계가 더하는 것은 AI 학생 시뮬레이터(`sim/`)와 두꺼게 슬롯 T1·T2·T3이 가져오는 옛 자산 **각 1개**뿐이다. 계획서 §6 목록(페르소나 9개째, 감정·이탈 모델링, 강화학습 학생, 튜터 자동 최적화 루프, 시드를 클라우드로 보내기, 두 번째 단원, 세 슬롯 동시 진행, 옛 자산 리팩토링, 루브릭 전체 이식·합성 시나리오 200건·Laya v4, FINDINGS에 없는 문제 수정)은 제안하지 않는다. 떠오르면 `golden/LATER.md`에 한 줄 적는다. "시뮬레이터가 있으니 금방"이라는 생각이 들면 계획서 §0을 다시 읽는다.
5. **완료 기준은 tests/golden 초록 + 야간 스모크 초록:** 코드를 건드린 세션은 끝날 때 `cd src/backend && python -m pytest ../../tests/golden`을 돌리고 **exit code**로 판정한다(`-q`·`| tail` 금지). S19 이후에는 `python -m golden.sim.run --sessions 120`(가짜 모드)도 돌려 M4·M5 0건을 확인한다. 빨간불이면 PR을 만들지 않는다.
6. **모든 PR은 FINDINGS 항목 번호를 인용한다:** PR 제목과 본문 첫 질문에 `F-NN`(`golden/FINDINGS.md` 끝의 「항목 번호」 절 — S16이 붙인다)을 적는다. 인용할 항목이 없으면 그 PR은 지금 할 일이 아니다 — 만들지 않고 보고한다. 시뮬레이터 세션(S16~S20)은 `F-00`(시뮬레이터 기반 — 모든 항목의 측정 수단)을 인용한다.
7. **시드는 로컬에만:** `golden/sim/seed/` 아래 내용(사람 출처 발화·분포)은 로컬 Ollama 외 어디로도 보내지 않는다. 클라우드 LLM 호출(튜터·클라우드 학생)의 프롬프트에 시드 발화를 넣지 않는다. 학생 시뮬레이터의 LLM은 **로컬 Ollama만** 부른다. 검사: 시드를 읽는 코드와 클라우드 프로바이더를 부르는 코드가 같은 함수 안에 있으면 안 된다(테스트로 동결).
8. **옛 자산은 한 세션에 하나, 다섯 걸음 순서대로:** ①경계 긋기(가져올 함수·클래스를 파일 경로와 이름으로 HARVEST.md에 먼저 적는다 — "이 모듈"이 아니라 "이 함수 3개") ②특성화 테스트(옛 코드를 옛 자리에서 그대로 호출해 입력 10개 → 출력 10개를 `tests/golden/characterization/`에 고정한다. 지금 동작이 맞는지는 묻지 않는다 — 바뀌지 않는지만 본다) ③복사 또는 import(의존이 3개 이하면 import, 넘으면 `src/backend/golden/` 아래로 복사해 의존을 잘라낸다. 복사했으면 HARVEST.md에 "복사: 의존 과다") ④연결(골든 패스의 한 지점 — GP-4 프롬프트·GP-5 판정·GP-6 갱신 — 에만 붙인다. 기능 플래그 뒤에 둔다) ⑤초록 확인(특성화 테스트 + e2e + AI 야간 스모크 모두 초록. 하나라도 빨강이면 플래그를 끄고 원인을 LATER.md에 적는다). 한 걸음이 하루를 넘기면 자산이 너무 크다는 뜻이니 더 작은 조각으로 자른다. 같은 입력에 다른 출력이 나오는(비결정적) 자산은 가져오지 않고 HARVEST.md에 "버림: 비결정적"으로 적는다.
9. **LLM 호출 규칙:** 튜터 LLM은 지금처럼 `whymath_backend.l3.providers.factory.build_cloud_provider()` + `l3.router.Router.route` 경유다(`src/backend/golden/tutor.py` 그대로). 학생 LLM은 옛 코드의 `whymath_backend.l3.providers.ollama.OllamaProvider`를 import해 로컬 Ollama만 부른다(계획서 3-4 뼈대의 `import ollama` 직접 호출은 **의도(로컬만 호출)**로만 읽고, 구현은 프로바이더 경유로 한다 — CLAUDE.md "LLM 호출은 항상 라우터 경유"). 프로바이더가 모델 ID 지정을 못 하면 그 클래스를 `src/backend/golden/sim/`로 복사해 모델 인자를 연다(HARVEST.md "복사"). SDK 직접 호출·키 하드코딩 금지. **테스트와 CI는 실제 LLM을 부르지 않는다** — `GOLDEN_FAKE_LLM=1`이면 튜터·학생 모두 고정 대본이다.
10. **미성년자 데이터:** 학생 식별자는 닉네임뿐. 실명·학교·학년·연락처는 어디에도 저장하지 않는다. 시드 발화는 익명화(이름·학교·지역 낱말 → `[이름]`) 뒤에만 파일에 쓴다. 실학생 세션 전에는 보호자 동의를 받는다(Kiki 담당). 시뮬레이션 닉네임은 `sim-<페르소나>-<회차>`, 사람은 `stu-<번호>`(실학생)·`self-*`·`adult-*`.
11. **검증은 CI와 같은 명령으로:** `src/backend`에서 `python -m ruff check golden ../../tests/golden`, `python -m black --check --line-length 100 golden ../../tests/golden`, `python -m mypy --strict golden`, `lint-imports`를 돌린다(CI `golden-path` 잡과 같은 네 스텝). 판정은 exit code이며 보고에 숫자(통과 N건·소요 시간)를 적는다. 로컬 CI 미러(`python3 scripts/harness/ci_mirror.py run`)는 **커밋한 뒤** 돌리고, 미러가 도는 동안 커밋·amend를 하지 않는다(HARN-194 오염 무효).
12. **모르는 값은 추정 금지:** 이 문서의 "사전 실측(2026-11-15 · main `a9cff6ec`)" 값도 세션에서 다시 확인하고 다르면 보고에 적는다. 못 찾으면 "미확인"으로 적고 그 부분만 멈춘다.
13. **하네스·커밋·PR:** 코드나 문서를 바꾸는 세션은 첫 행위로 `python3 scripts/harness/backlog.py start <태스크 ID>`를 실행한다. 태스크 ID는 S16이 `backlog.py add`로 받아 `golden/STATE.md` 「하네스 태스크 ID」 절에 적어 둔 1단계 번호를 쓴다(번호를 눈으로 짓지 않는다). 커밋 메시지는 `S<번호>: <한 줄> (F-NN)` 형식. 작업이 끝나면 PR을 열고 본문 첫 질문에 GP 번호와 F 번호를 적는다. main 머지는 Kiki가 한다.
14. **한국어:** 코드 주석·문서·보고는 한국어로 쓴다(식별자는 영어).
15. **종료 보고 7줄:** 완료 보고 형식 외에 답변 끝에 반드시 쓴다 — ①완료 기준 충족 여부(아니오면 어디까지) ②tests/golden 결과(초록/빨강·테스트 N개) ③HARVEST.md에 오늘 추가한 줄 ④LATER.md에 오늘 추가한 줄 ⑤오늘 범위 밖으로 나가려다 멈춘 순간 ⑥AI 스모크 120 결과: M1 __% / M2 __턴 / M3 __% / M4 __건 / M5 __건(S19 전이면 "해당 없음") ⑦이 세션이 FINDINGS F-__를 전진시켰는가: 예/아니오/판정 세션에서 확인.

## 용어

| 용어 | 뜻 |
| --- | --- |
| 골든 패스 | S1~S15가 만든 경로. GP-1 세션 시작 → GP-2 문제 제시 → GP-3 답변 → GP-4 튜터 되묻기(최대 3턴) → GP-5 판정 → GP-6 숙련도 갱신. 서버 `golden.api:app`, 앱 `lib/main_golden.dart` |
| 두꺼게 | 골든 패스를 넓히지 않고(단원·기능 추가 없음) 같은 경로를 더 튼튼하게 만드는 것. 옛 자산을 슬롯 하나에 하나씩 가져온다 |
| 진실 트랙 | 실제 중학생 3~5명 · 누적 세션 50건. "튜터가 쓸 만한가"를 묻는다. 완료율이 게이트다 |
| 회귀 트랙 | AI 학생 시뮬레이터 · 30문항 × 페르소나 8개 × 3회 = 720세션. "튜터가 망가지지 않았나"를 묻는다. 치명 실패 0건이 게이트다 |
| 슬롯 T1·T2·T3 | 한 주에 하나씩 가져오는 옛 자산 자리. T1 튜터 되묻기 품질(루브릭) · T2 오개념 조회(오개념 DB 일차함수분) · T3 숙련도 엔진(BKT). 기본 배정은 가정이고 설계 세션(S21·S26·S31)에서 FINDINGS 순위로 다시 정한다 |
| FINDINGS | `golden/FINDINGS.md`(S13). 1위 끊김 지점 = GP-4 튜터 마지막 되묻기가 틀린 곳을 짚지 않음(C5). S14가 프롬프트 규칙 6으로 고쳤다. 항목 번호 `F-NN`은 S16이 붙인다 |
| 특성화 테스트 | 옛 코드를 고치기 전에 "지금 이렇게 동작한다"를 입력→출력 쌍으로 고정하는 테스트. 맞는지는 묻지 않고 바뀌지 않는지만 본다. `tests/golden/characterization/` |
| 주입기 | `sim/errors.py`. 문항과 오개념 ID를 받아 그 오개념을 가진 학생이 낼 틀린 답을 LLM 없이 규칙만으로 결정적으로 만든다 |
| 학생 모델 | `sim/student.py`. 주입기가 만든 답(또는 페르소나 규칙)에 중2 말투를 입혀 다음 발화를 만든다. 로컬 Ollama만 쓴다 |
| 러너 | `sim/run.py`. 학생 모델을 튜터(골든 API)에 붙여 세션을 돌리고 M1~M5를 잰다 |
| M1~M5 | 회귀 트랙 메트릭 5개(공유 계약 표). M1 답 유출률·M2 평균 턴 수·M3 판정 오류율·M4 크래시·M5 렌더 깨짐 |
| OP 코드 | 오답을 오류 유형으로 분류하는 코드 `OP_00`(미분류)~`OP_08`. S16이 정의하고 주입기·보정 검사가 같은 표를 쓴다 |
| 보정 | S20. 시뮬레이터가 사람을 닮았는지 세 기준(턴 수 분포·오류 유형 분포·블라인드 구분)으로 검사. 통과 전 시뮬레이터 숫자로 튜터를 판단하지 않는다 |
| 야간 스모크 | 120세션(30문항 × P1·P2·P5·P7 × 1회)을 매일 돌리는 회귀. CI(가짜 모드)와 Kiki 머신(실제 LLM) 두 겹 |
| 기능 플래그 | 옛 자산 연결을 켜고 끄는 환경변수(`GOLDEN_T1_RUBRIC`·`GOLDEN_T2_MISCONCEPTION`·`GOLDEN_MASTERY_ENGINE`). 기본값은 끔. 빨간불이면 끈다 |
| 섀도 기록 | T3에서 simple 엔진과 bkt 엔진이 같은 세션의 숙련도를 나란히 기록하되 화면은 simple만 보여 주는 방식 |
| 사람 출처 로그 | 골든 패스 S9~S12가 남긴 본인(`self-1`·`self-norole`)·성인(`adult-1`·`adult-2`) 턴 기록. 실제 중학생 로그는 2026-11-15 현재 **0건**이다 |
| 사전 실측 | 이 지시서를 쓰며 2026-11-15에 main `a9cff6ec` 기준으로 직접 확인한 값. 세션에서 재확인한다 |

## 공유 계약 (모든 세션이 같은 모양을 쓴다 — 바꾸려면 보고하고 멈춘다)

아래 모양은 S16~S35가 전부 같이 쓴다. 바꿔야 한다고 판단하면 바꾸지 말고 보고에 "계약 변경 제안"으로 적고 멈춘다. 골든 패스 공유 계약(HTTP 3개·문항 JSON·채점·숙련도·DB 표 3개·환경변수 — `golden/prompts_src/spec.md`)은 그대로 유효하며 여기서는 1단계가 더하는 것만 적는다.

*계획서 전제와 저장소 사실이 다른 곳(사전 실측 2026-11-15 · main `a9cff6ec`) — 지시문은 저장소 사실을 따른다*

| 계획서가 전제한 것 | 저장소 사실 | 이 지시서의 처리 |
| --- | --- | --- |
| 골든 패스 §6 완료 판정 5줄이 전부 "예"(실학생 5명·세션 30건) | **실제 중학생 0명.** 사람 출처 로그는 본인 `self-1`(5문제)·`self-norole`(30)·성인 `adult-1`·`adult-2`(60) = 문제 기록 95건·턴 약 125개. AI 시뮬레이션(S11 3 페르소나) 기록 70건. `golden/FINDINGS.md`「피험자 한계」 | S16 시드는 **사람 출처 로그**에서 뽑고 "실학생 0"을 시드 README와 CALIBRATION.md 첫 줄에 적는다. 실학생 섭외는 사람 작업 H2로 두고 S24 전까지 끝낸다. 게이트 §7 "실학생 3명 이상"은 그대로다 |
| `rubric.yaml v0.2`(T1이 가져올 루브릭 파일) | 그 이름의 파일은 저장소에 **없다**(`find . -name "rubric*.y*ml"` 0건). 루브릭 자산은 둘이다 — ①`src/backend/whymath_backend/harness/pedagogical_rubric.py`(정답 유출 결정론 탐지기 `detect_answer_leakage(response, answer)` + 소형 루브릭 `score_tutoring_response(response, *, answer)`, 순수 함수·LLM 불요) ②골든 패스 S9가 만든 되묻기 루브릭 v0 `golden/reports_no_students/S9/되묻기_루브릭.md`(C1 되짚기·C2 질문 하나·C3 정답 비노출·C4 학생 몫 보존·C5 오류 겨냥 — 사람이 판정) | T1의 옛 자산 후보 = ①의 함수 2개(결정론·5걸음 적용 가능). ②는 이미 골든 안에 있는 판정 틀이라 "가져올 것"이 아니라 S23·S25의 **사람 판정 기준**이다. S21이 확정한다 |
| 오개념 DB 400개 중 일차함수분 15~25개 | `data/corpus/misconceptions_v1/misconceptions.json` 총 843건 중 `subunit=일차함수` 또는 성취기준 `[9수02-14]`·`[9수02-15]`·`[9수02-16]`인 것은 **8건**(M0034 y절편을 기울기로 · M0035 음의 기울기 방향 · M0036 x절편·y절편 혼동 · M0037 f(2)를 2f로 · M0409 · M0567 · 외 2). 부호 오개념(M0001 (−)×(−)=(−) · M0002 3−(−5)=−2 · M0548)은 선행 단원(정수 연산)에 있다. 로더는 `whymath_backend/l1/misconception/catalog_loader.py`의 `load_misconceptions`·`MisconceptionCatalogStore` | S26이 일차함수 8건 + 일차함수 문항에서 실제로 나는 선행 오개념(부호·대입)을 더해 **N건을 세어 적는다**(목표 15~25는 "있으면"이지 채우라는 뜻이 아니다). 주입기(S17)는 이 목록을 기다리지 않고 OP 코드로 먼저 만든다 |
| 야간 스모크 120세션을 "매일 CI에서 자동" | CI(`.github/workflows/ci.yml`)에는 LLM 키가 **없다**(`secrets.*`는 `GITHUB_TOKEN`뿐 · `e2e-nightly` 잡도 mock LLM). 셀프호스트 러너 없음. 스케줄 트리거는 매일 18:00 UTC(03:00 KST) 하나 | 야간 스모크는 **두 겹**이다. ⓐ CI: 새 워크플로 `golden-sim-nightly.yml`(18:30 UTC)이 `GOLDEN_FAKE_LLM=1`로 120세션을 돌려 파이프라인 무결성(M4 크래시·M5 렌더·주입기 결정성·M1 규칙 검사기 자체)만 잰다 ⓑ Kiki 머신: 같은 명령을 실제 LLM(튜터 OpenRouter·학생 Ollama)으로 돌려 M1~M5를 잰다. 주 1회 720세션(`SIM_FULL=1`)도 Kiki 머신이다. 두 결과 파일은 이름으로 구분한다(`sim_report.json` vs `sim_report_fake.json`). CI에 LLM 키를 넣을지는 Kiki 결정(제안값: 넣지 않는다 — 시드 반출 규칙과 비용) |
| 학생 모델 `import ollama` 직접 호출 | CLAUDE.md "LLM 호출은 항상 라우터 경유". 옛 코드에 `whymath_backend/l3/providers/ollama.py`의 `OllamaProvider`가 있다(`ollama_host` 설정 사용) | 공통 규칙 9대로 `OllamaProvider` 경유. 모델 ID 지정이 안 되면 `sim/`에 복사 |
| BKT 옛 모듈 1개 + 파라미터 4개 | `src/backend/whymath_backend/l2/bkt.py` — `BktParameters`(pydantic·비퇴화 검증 포함), 순수 함수 `posterior_mastery(prior, correct, params)`·`apply_learning`·`apply_forgetting(mastery, elapsed_days, params)`·`update_mastery(prior, correct, params)`·`probability_correct`, 클래스 `BktModel(params)`(`initial_mastery`·`update`·`update_sequence`·`predict_correct`·`apply_forgetting`) | T3의 옛 자산 = `BktParameters` + `update_mastery`(망각은 §6 금지 — `apply_forgetting`은 가져오지 않는다). 파라미터 이름·개수는 S31이 파일에서 읽어 확정한다(사전 실측은 함수 이름까지만) |
| 옛 합성 학생 자산 | `grep synthetic_student|SyntheticStudent|student_simulator` 0건. 골든 패스 S11이 만든 `src/backend/golden/sim_student.py`(페르소나 3종 `slope-blind`·`sign-slip`·`no-setup`, 클라우드 LLM, `httpx.ASGITransport`로 `golden.api:app` 직접 호출, `--retry-rule`)가 유일한 선례 | S18·S19는 `sim_student.py`의 ASGI 호출·CSV 기록·개인정보 검사(`_check_privacy`)를 **재사용**하고, 페르소나 3종은 8종 체계(P1~P8)로 흡수한다(`slope-blind`→P3+OP_03 · `sign-slip`→P3+OP_01 · `no-setup`→P3+OP_06). `sim_student.py`는 지우지 않고 `golden/sim_personas.md`와 함께 남긴다(S35 미참조 목록에서 판단) |

*골든 코드 현행(사전 실측 · `src/backend/golden/`)*

| 파일 | 쓰는 것 |
| --- | --- |
| `api.py` | `FastAPI` 앱 `app` + 엔드포인트 3개. 상수 `MAX_TUTOR_TURNS`(=3)·`MASTERY_GAIN`(0.10)·`MASTERY_LOSS`(0.05)·`FEEDBACK_CORRECT`·`FEEDBACK_WRONG`. 함수 `answer(body)`가 판정 순서(채점 → graded/tutor_turn)를 쥔다. `_graded(...)`가 숙련도 갱신 |
| `grade.py` | `normalize(text)`(접두 `정답:`·`답:`·`f(x)=`·`y=` 떼기 → 마지막 `=` 뒤만 → 꼬리 7개 `같은데요·같아요·인가요·맞나요·이요·요·?` 떼기 · 전각·`−`·`×`·`÷` 치환) · `is_correct(problem, student_text)` · `_parse`는 `whymath_backend.l3.safe_parse.safe_parse_expr` 경유(코딩 헌법 R22-03) · `TOLERANCE=1e-9` · `MAX_INPUT_LEN=100` |
| `tutor.py` | `ask(problem, history, student_text) -> TutorReply` · `build_user_prompt`("3번 중 N번째" 표시 포함) · `LLM_TIMEOUT_S=20` · `FAKE_PREFIX`("어느 부분이 막히는지 한 가지만 말해 줄래? ") · 시스템 프롬프트는 `golden/tutor_prompt.md`(규칙 7개 · S14가 규칙 6에 "틀린 곳 짚기" 문장 추가) |
| `store.py` | `ensure_schema()`(스키마 `golden` + `create_all`) · `create_session`·`get_session`·`advance_cursor`·`record_turn`·`open_turns`·`get_mastery`·`set_mastery` · 데이터클래스 `SessionRow`·`TurnRow` |
| `problems.py` | `load_problems() -> list[Problem]` · `public_view(problem, index, total)` · 경로 `golden/data/problems_linear_fn.json`(30문항 LF-01~LF-30 · 10건은 코퍼스 유래 f(k) 유형 · 20건 직접 작성: 기울기·절편·식 세우기·그래프 해석·실생활) |
| `sim_student.py` | S11 시뮬레이터(위 표). `run_simulation`·`fetch_turn_rows`·`write_csv`·`_check_privacy(prompt, nickname, session_id)`·`build_student_prompt` |
| `tests/golden/` | `test_golden_path.py`(e2e) · `test_problems_schema.py` · `test_import_direction.py` · `test_api_contract.py` · `test_grade.py` · `test_sim_student.py` 등. CI 잡 `golden-path`(ruff → black → mypy --strict golden → pytest ../../tests/golden · Postgres 서비스 컨테이너) |
| FINDINGS 현황 | 1위 GP-4 C5(S14가 고침 · 재생 4/25 → 25/25). 2위 후보 GP-5 판정 오류 앞말형(`f(5)는 -12예요.` — AI 출처에서만 · 계약 변경이라 Kiki 결정 대기). 3위 후보 GP-2 문제 이해(no-setup 페르소나에서만). 공통 속성: 판정 문장이 학생의 마지막 답을 언급하지 않음(Kiki 결정 "이번엔 고치지 않음") |

*폴더 배치(코드는 `src/backend/golden/` 아래, 데이터·문서는 `golden/` 아래 — 계획서의 `golden/sim/*.py` 표기는 이 규칙으로 읽는다)*

```
src/backend/golden/sim/            ← S17~S20 코드 (패키지 · __init__.py)
  errors.py      주입기            student.py   학생 모델(로컬 Ollama)
  run.py         러너 + report()   calibrate.py 보정 검사
  metrics.py     M1~M5 계산(러너가 import)
src/backend/golden/eval/           ← T1 (S22) 가져온 루브릭 함수 + 평가기
src/backend/golden/mastery/bkt.py  ← T3 (S32) 가져온 BKT + 섀도 기록
golden/sim/
  seed/utterances.txt  seed/distributions.json  seed/README.md   ← S16 (gitignore 대상 · Kiki 머신에만)
  out/<YYYY-MM-DD>/sessions.jsonl  sim_report.json  sim_report_fake.json ← S19 (gitignore 대상)
  CALIBRATION.md  CALIBRATION_blind.md  CALIBRATION_key.txt(gitignore)  ← S20
golden/data/misconceptions_lf.json ← S26 (커밋)
golden/FINDINGS.md 끝 「항목 번호」 절 ← S16 · golden/FINDINGS_v2.md ← S35
tests/golden/characterization/     ← 특성화 테스트 (S21·S26·S31)
tests/golden/test_sim_*.py         ← 시뮬레이터 테스트
golden/reports_phase1/<번호>/보고.md ← 각 세션 보고
.github/workflows/golden-sim-nightly.yml ← S19 (배선 파일 1개)
```

*페르소나 8개(계획서 §3-1 · `golden/sim/personas.md`에 S18이 적는다)*

| ID | 이름 | 숙련도 | 행동 규칙 | 재는 것 |
| --- | --- | --- | --- | --- |
| P1 | 답 요구형 | 낮음 | 첫 턴부터 "답만 알려줘". 2턴째도 같은 말 | M1 답 유출률 |
| P2 | 시도형 | 낮음 | 틀린 답을 내고 힌트를 받으면 다시 시도 | M2 턴 수·힌트 품질 |
| P3 | 오개념 보유형 | 중간 | 주입기가 고른 오개념 1개를 세션 내내 유지(답은 주입기가 정한다) | 오개념 검출률(T2 이후) |
| P4 | 질문형 | 중간 | 답 대신 "기울기가 뭐예요?" 같은 개념 질문부터 | 개념 설명 길이·답 유출 |
| P5 | 검산 요청형 | 높음 | 맞는 답을 내고 "맞아요?"라고 확인 요구 | M3 판정 오류 |
| P6 | 잡담 섞음형 | 높음 | 2턴 중 1턴은 무관한 말("배고파") | 복귀 유도 여부 |
| P7 | 적대형 | — | 빈 입력, 영어, 비속어, 500자 붙여넣기 | M4 크래시·M5 렌더 |
| P8 | 게이밍형 | — | 3턴 제한을 알고 매 턴 아무 숫자나 내서 판정 유도 | 3턴 강제 이동·숙련도 오염 |

- 말투: S16 시드 발화 20개(익명화)를 학생 모델 시스템 프롬프트의 예시로 넣는다("ㅁㄹ"·"x는 2 아님?" 같은 실제 표기 흉내가 목적). P1·P5·P7·P8은 말투 입히기 없이 고정 문장/규칙만으로도 돌 수 있어 **가짜 모드와 야간 스모크(P1·P2·P5·P7)에 쓴다**(P2의 "다시 시도"는 가짜 모드에서 주입기 답 → 정답 순).
- 숙련도 표시는 시뮬레이션용 가정이지 BKT 초기값이 아니다.

*메트릭 5개와 기준(계획서 §3-2 · `sim/metrics.py`)*

| 메트릭 | 정의 | 기준 | 어기면 |
| --- | --- | --- | --- |
| M1 답 유출률 | GP-5 판정 전 튜터 발화에 문항 `answer`가 그대로 나온 세션 비율. 판정은 `pedagogical_rubric.detect_answer_leakage` 또는 그와 같은 규칙(단어 경계·sympy 동치) | 0% | PR 차단 |
| M2 평균 턴 수 | P2·P4·P5에서 정답까지 튜터 턴 수 | 1.5~3.0 | 경고. 3.0 초과는 3턴 강제 이동이 깨진 것 |
| M3 판정 오류율 | 시뮬레이터가 아는 정답·오답과 `grade.py` 판정이 다른 비율(주입기가 답을 정한 입력만 센다) | 1% 미만 | PR 차단 |
| M4 크래시·타임아웃 | HTTP 5xx, 30초 초과, 예외 | 0건 | PR 차단 |
| M5 렌더 깨짐 | 튜터 응답에 짝이 안 맞는 `$`, 깨진 `\frac`, 마크다운 백틱 등 정규식 검사 | 0건 | PR 차단 |
| (T2 이후) 오개념 검출률 | P3 세션 중 튜터가 주입된 오개념을 언급하거나 그 오개념용 힌트를 낸 비율 | 60% 이상 | S28 판정 |

*OP 코드(S16이 확정 · 제안값)*

| 코드 | 뜻 | 예 |
| --- | --- | --- |
| OP_00 | 미분류 | — |
| OP_01 | 부호 오류(음수 곱·뺄셈) | −3×5=15 · 3−(−5)=−2 |
| OP_02 | 대입 오류(f(k)를 k·f로, 자리 바꿈) | f(2)=2f |
| OP_03 | 기울기 분자·분모 뒤바꿈 | 6/(−9) |
| OP_04 | 기울기·y절편 혼동 | y=2x+3의 기울기 3 |
| OP_05 | 계산 전 식만 쓰고 멈춤 | 3×5+1 |
| OP_06 | 식 세우기 실패(숫자 하나 찍기) | "3" |
| OP_07 | x절편·y절편 혼동 | 좌표 바꿔 배치 |
| OP_08 | 증가·감소 방향 혼동 | 음의 기울기를 증가로 |

*시뮬레이터 입출력 모양*

- `python -m golden.sim.run --sessions {120|720} --personas P1,P2,... --date YYYY-MM-DD`(기본 전체 8종 · `--sessions 720`은 환경변수 `SIM_FULL=1`이 있을 때만, 없으면 120으로 강제). 문항 30 × 페르소나 × 회차를 순서대로 돈다. 세션마다 GP-1~GP-6을 **HTTP로만** 밟는다(`httpx.ASGITransport` 또는 `--base-url http://...` — 내부 함수 직접 호출 금지).
- `golden/sim/out/<날짜>/sessions.jsonl` 한 줄 = 세션 1개: `{"persona","problem_id","turns":[{"n","student","tutor","kind","correct"}],"forced_answer","injected_op","elapsed_s","http_status","leak","render_broken"}`.
- `sim_report.json`: `{"date","sessions","mode":"live|fake","M1":{"value","threshold","pass"},...,"M5":{...},"worst_persona","slowest_problem","exit_code"}`. 차단 기준(M1·M3·M4·M5) 하나라도 어기면 `report()`가 exit code 1.
- 보정 기준 3개(S20): ①턴 수 분포 — P2·P4·P5 합산 중앙값이 사람 출처 중앙값 ±1턴 ②오류 유형 분포 — AI 세션 오답의 상위 3개 OP 코드 중 2개 이상이 사람 출처 상위 3개와 겹침 ③블라인드 — 사람 발화 20 + AI 발화 20을 섞어 Kiki가 맞히면 정확도 70% 이하이면 통과. 비교 불가 항목(이탈률·세션 길이·만족도)은 CALIBRATION.md에 "진실 트랙만 말할 수 있다"로 명시.

*기능 플래그·환경변수(1단계 추가분)*

| 이름 | 뜻 |
| --- | --- |
| `SIM_FULL=1` | 720세션 허용. 없으면 120 강제 |
| `GOLDEN_SIM_STUDENT_MODEL` | 학생 Ollama 모델 ID(S18이 2개 비교해 1개 확정 · 기본값은 확정 모델) |
| `GOLDEN_T1_RUBRIC=0|1` | T1 평가기를 GP-4 뒤에 붙일지(S22 · 기본 0) |
| `GOLDEN_T2_MISCONCEPTION=0|1` | 오개념 매칭을 GP-5·GP-4에 붙일지(S27·S28 · 기본 0) |
| `GOLDEN_MASTERY_ENGINE=simple|bkt` | 숙련도 엔진(S32 · 기본 simple · bkt는 섀도 기록) |
| `GOLDEN_FAKE_LLM=1` | 튜터·학생 모두 고정 대본(CI·테스트) |

*게이트(S35 · 12/26 · 계획서 §7 여섯 줄)*

- 진실 트랙: ①실학생 3명 이상·누적 세션 50건 ②완료율 70% 이상(끝까지 푼 세션 ÷ 시작한 세션) ③세 슬롯 중 둘 이상 "효과 있음"(FINDINGS 해당 항목이 수치로 개선)
- 회귀 트랙: ④CALIBRATION.md 첫 줄이 "통과" ⑤야간 스모크 120이 S20 이후 치명 실패(M1·M3·M4·M5) 0건으로 끝난 날이 전체의 90% 이상 ⑥FINDINGS_v2.md에 2단계의 1순위 문제가 숫자와 함께 적혀 있다
- 판정 규칙: 여섯 줄 모두 "예"면 2단계. 진실 트랙 셋 중 하나라도 "아니오"면 S21~S35를 한 번 더 돈다. 회귀 트랙만 "아니오"면 2단계로 가되 첫 주를 시뮬레이터 수정에 쓴다. 실학생 2명 미만이면 S24·S29·S33 크기를 줄여 누적 30건으로 낮추되 게이트 문서에 "축소"로 표기, 0명이면 1단계를 멈추고 섭외부터.

## 작업 지시: S22. T1 import — src/backend/golden/eval/ + 플래그 GOLDEN_T1_RUBRIC

- **목적:** 5걸음 ③④ — 옛 함수 2개를 골든 안으로 가져오고(의존 3개 이하면 import, 넘으면 복사), GP-4 뒤에 기능 플래그로 붙인다. e2e는 그대로 초록이어야 한다.
- **선행 산출물:** S21 특성화 테스트·경계.
- **할 일:**
  1. `src/backend/golden/eval/__init__.py`·`rubric.py`: `whymath_backend.harness.pedagogical_rubric`를 import해 `evaluate_tutor_reply(reply: str, answer: str) -> RubricVerdict`(유출 여부·루브릭 점수·근거)로 감싼다. import 비용(끌려오는 옛 모듈 수)을 `python -X importtime`으로 재 보고에 적는다. 3개를 넘으면 두 함수를 `eval/rubric_copy.py`로 복사해 의존을 자르고 HARVEST.md "복사: 의존 과다".
  2. 연결(5걸음 ④): `api.py`의 `answer()`에서 튜터 응답을 받은 직후 `GOLDEN_T1_RUBRIC=1`일 때만 평가기를 부른다. 결과는 **기록만**(`golden.turns`에 열을 추가하지 않고 새 표 `golden.eval_log(turn_id, verdict_json, created_at)` — `store.py` `create_all` 대상에 추가) 하고 응답은 바꾸지 않는다. 유출(`leak`) 판정이면 로그에 경고(예외 타입명·문제 ID — 응답 문장은 로그에 남기지 않는다).
  3. 플래그 꺼짐(기본)에서 e2e·전체 `tests/golden` 초록, 켜짐에서도 초록(테스트 픽스처로 둘 다).
  4. 특성화 테스트가 골든 안 사본(또는 import)에 대해서도 같은 10쌍을 내는지 확인(복사했으면 테스트를 두 대상에 parametrize).
  5. HARVEST.md에 "T1 import: 함수 2개 · 의존 N개 · import|복사".
- **산출물:** `eval/`, `store.py` 표 1개 추가, 플래그, HARVEST 줄, 테스트.
- **완료 기준:** ①플래그 0/1 양쪽에서 `tests/golden` 초록 ②특성화 10쌍이 골든 안에서도 초록 ③import 비용 숫자가 보고에 있다 ④가짜 모드 스모크 120 M4·M5 0.
- **하지 말 것:** 튜터 응답을 평가 결과로 바꾸거나 막지 않는다(S23의 일이고, 그것도 프롬프트 개정 1회뿐). 루브릭 전체·합성 시나리오·7단계 파이프라인을 가져오지 않는다.

## 산출물 저장 규칙

- 이 작업에서 만든 문서, 표, 보고서는 모두 `golden/reports_phase1/S22/`에 저장한다.
- 코드 변경은 저장소의 기존 위치에 하되, git을 쓰는 저장소라면 `golden-p1/S22` 브랜치에서 작업하고 기본 브랜치에 직접 반영하지 않는다.
- 마지막으로 `golden/reports_phase1/S22/보고.md`에 아래 형식의 완료 보고를 쓰고, 같은 내용을 답변으로도 보여준다.

## 완료 보고 형식

```
작업 번호: S22
결과: 완료 | 일부 완료 | 중단
만든 것: 파일·테이블·화면 이름 (경로 포함)
완료 기준 확인: 항목별 통과/실패와 근거 (실행한 명령 또는 본 화면)
미확인·가정한 것: 없으면 "없음"
다음 작업이 알아야 할 것: 없으면 "없음"
```

## 시작 순서

0. 세션 제목을 `DK-단계03-S22-T1import-플래그`으로 등록한다("너의 역할"의 첫 행위).
1. 공통 규칙 2번대로 선행 작업의 `보고.md`를 확인한다.
2. "작업 지시"의 할 일을 순서대로 수행한다.
3. "완료 기준"을 하나씩 확인하고 결과를 기록한다.
4. `golden/reports_phase1/S22/보고.md`를 쓰고 보고한다.
