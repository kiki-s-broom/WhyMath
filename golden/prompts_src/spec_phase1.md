# WhyMath 1단계 「두꺼게」 — 작업 지시서 (AI 실행용 · 3+AI 4주)

작업 번호를 받은 AI는 이 문서의 공통 규칙·용어·공유 계약과 해당 번호의 지시만 읽고 작업한다. 지시에 없는 값은 추정하지 않고 "미확인"으로 보고한다. 원본 계획서는 `plan_phase1_thicken_4weeks.docx`(2026-11-15 개정판 · Kiki 보관 원본(저장소 미포함 — office·PDF 문서는 `.gitignore`와 `scripts/ops/check_source_document_binaries.py`가 커밋을 막는다 · 저장소 안 정본은 지시서))이고, 이 계획은 골든 패스 계획서(S1~S15 · `golden/prompts/`)의 후속이다. 세션 번호는 S16부터 S35까지 이어 붙이되, 개정판이 S20 뒤에 **S20+1 「전이 의존 절단」**(이 지시서의 작업 번호 `S20A`)을 더해 **총 21세션**이다. 4주 안에 흡수되지 않으면 S35가 5주차 월요일로 밀린다(세션 수는 줄이지 않는다).

## 공통 규칙과 보고 형식

**공통 규칙**

1. (스크립트가 "읽을 범위" 표준 문장으로 바꾼다)
2. (스크립트가 "선행 작업 확인" 표준 문장으로 바꾼다)
3. **golden/ 바깥은 읽기 전용:** 새 코드는 `src/backend/golden/`(파이썬 패키지 — 하위 `sim/`·`eval/`·`mastery/`), `golden/`(문서·데이터·로그), `src/mobile/lib/golden/`(Flutter), `tests/golden/`(테스트)에만 쓴다. 옛 코드를 고쳐야 돌아가면 고치지 말고 `golden/` 아래로 복사해서 고치고 `golden/HARVEST.md`에 "가져온 것 / 버린 것 / 이유 / 세션" 한 줄을 적는다. 예외는 **S19 한 세션의 배선 파일 1개**(`.github/workflows/golden-sim-nightly.yml` 신설)와, 생성기·훅처럼 이미 `golden/` 밖에 있는 **지시문 묶음 자체의 장치**뿐이다. `constitution/`은 어떤 세션도 건드리지 않는다(가드 훅이 막는다. 막히면 우회하지 않고 멈춘다). `golden/` 바로 아래에 `.py`를 두지 않는다 — `tests/infra/test_lint_coverage.py`가 어떤 CI 린트에도 안 걸리는 `.py`를 막는다(S13 실측). 코드는 전부 `src/backend/golden/` 아래다.
4. **범위 고정:** 중2 일차함수 1단원·문항 30개·GP-1~GP-6·HTTP 엔드포인트 3개는 그대로다. 1단계가 더하는 것은 AI 학생 시뮬레이터(`sim/`)와 두꺼게 슬롯 T1·T2·T3이 가져오는 옛 자산 **각 1개**뿐이다. 계획서 §6 목록(페르소나 9개째, 감정·이탈 모델링, 강화학습 학생, 튜터 자동 최적화 루프, 시드를 클라우드로 보내기, 두 번째 단원, 세 슬롯 동시 진행, 옛 자산 리팩토링, 루브릭 전체 이식·합성 시나리오 200건·Laya v4, FINDINGS에 없는 문제 수정)은 제안하지 않는다. 떠오르면 `golden/LATER.md`에 한 줄 적는다. "시뮬레이터가 있으니 금방"이라는 생각이 들면 계획서 §0을 다시 읽는다.
5. **완료 기준은 tests/golden 초록 + 야간 스모크 초록:** 코드를 건드린 세션은 끝날 때 `cd src/backend && python -m pytest ../../tests/golden`을 돌리고 **exit code**로 판정한다(`-q`·`| tail` 금지). S19 이후에는 `python -m golden.sim.run --sessions 120`(가짜 모드)도 돌려 M4·M5 0건을 확인한다. 빨간불이면 PR을 만들지 않는다.
6. **모든 PR은 FINDINGS 항목 번호를 인용한다:** PR 제목과 본문 첫 질문에 `F-NN`(`golden/FINDINGS.md` 끝의 「항목 번호」 절 — S16이 붙인다)을 적는다. 인용할 항목이 없으면 그 PR은 지금 할 일이 아니다 — 만들지 않고 보고한다. 시뮬레이터 세션(S16~S20)은 `F-00`(시뮬레이터 기반 — 모든 항목의 측정 수단)을 인용한다.
7. **시드는 로컬에만:** `golden/sim/seed/` 아래 내용(사람 출처 발화·분포)은 로컬 Ollama 외 어디로도 보내지 않는다. 클라우드 LLM 호출(튜터·클라우드 학생)의 프롬프트에 시드 발화를 넣지 않는다. 학생 시뮬레이터의 LLM은 **로컬 Ollama만** 부른다. 검사: 시드를 읽는 코드와 클라우드 프로바이더를 부르는 코드가 같은 함수 안에 있으면 안 된다(테스트로 동결).
8. **옛 자산은 한 세션에 하나, 다섯 걸음 순서대로:** ①경계 긋기(가져올 함수·클래스를 파일 경로와 이름으로 HARVEST.md에 먼저 적는다 — "이 모듈"이 아니라 "이 함수 3개") ②특성화 테스트(옛 코드를 옛 자리에서 그대로 호출해 입력 10개 → 출력 10개를 `tests/golden/characterization/`에 고정한다. 지금 동작이 맞는지는 묻지 않는다 — 바뀌지 않는지만 본다) ③복사 또는 import(의존이 3개 이하면 import, 넘으면 `src/backend/golden/` 아래로 복사해 의존을 잘라낸다. 복사했으면 HARVEST.md에 "복사: 의존 과다") ④연결(골든 패스의 한 지점 — GP-4 프롬프트·GP-5 판정·GP-6 갱신 — 에만 붙인다. 기능 플래그 뒤에 둔다) ⑤초록 확인(특성화 테스트 + e2e + AI 야간 스모크 모두 초록. 하나라도 빨강이면 플래그를 끄고 원인을 LATER.md에 적는다). 한 걸음이 하루를 넘기면 자산이 너무 크다는 뜻이니 더 작은 조각으로 자른다. 같은 입력에 다른 출력이 나오는(비결정적) 자산은 가져오지 않고 HARVEST.md에 "버림: 비결정적"으로 적는다. **전이 의존 예산(개정판 S20+1):** 골든이 직접 import하는 옛 모듈은 10개 이하, 전이(상류 전체)는 30개 이하다 — S20A가 이 수를 맞추고 `tests/golden/test_import_budget.py`로 동결한다. 그 뒤의 import(T1·T2·T3)는 예산 안에서만 가능하며, 넘기면 import 대신 복사한다(다섯 걸음 ③).
9. **LLM 호출 규칙:** 튜터 LLM은 지금처럼 `whymath_backend.l3.providers.factory.build_cloud_provider()` + `l3.router.Router.route` 경유다(`src/backend/golden/tutor.py` 그대로). 학생 LLM은 옛 코드의 `whymath_backend.l3.providers.ollama.OllamaProvider`를 import해 로컬 Ollama만 부른다(계획서 3-4 뼈대의 `import ollama` 직접 호출은 **의도(로컬만 호출)**로만 읽고, 구현은 프로바이더 경유로 한다 — CLAUDE.md "LLM 호출은 항상 라우터 경유"). 프로바이더가 모델 ID 지정을 못 하면 그 클래스를 `src/backend/golden/sim/`로 복사해 모델 인자를 연다(HARVEST.md "복사"). SDK 직접 호출·키 하드코딩 금지. **테스트와 CI는 실제 LLM을 부르지 않는다** — `GOLDEN_FAKE_LLM=1`이면 튜터·학생 모두 고정 대본이다.
10. **미성년자 데이터:** 학생 식별자는 닉네임뿐. 실명·학교·학년·연락처는 어디에도 저장하지 않는다. 시드 발화는 익명화(이름·학교·지역 낱말 → `[이름]`) 뒤에만 파일에 쓴다. 실학생 세션 전에는 보호자 동의를 받는다(Kiki 담당). 시뮬레이션 닉네임은 `sim-<페르소나>-<회차>`, 사람은 `stu-<번호>`(실학생)·`self-*`·`adult-*`.
11. **검증은 CI와 같은 명령으로:** `src/backend`에서 `python -m ruff check golden ../../tests/golden`, `python -m black --check --line-length 100 golden ../../tests/golden`, `python -m mypy --strict golden`, `lint-imports`를 돌린다(CI `golden-path` 잡과 같은 네 스텝). 판정은 exit code이며 보고에 숫자(통과 N건·소요 시간)를 적는다. 로컬 CI 미러(`python3 scripts/harness/ci_mirror.py run`)는 **커밋한 뒤** 돌리고, 미러가 도는 동안 커밋·amend를 하지 않는다(HARN-194 오염 무효).
12. **모르는 값은 추정 금지:** 이 문서의 "사전 실측(2026-11-15 · main `a9cff6ec`)" 값도 세션에서 다시 확인하고 다르면 보고에 적는다. 못 찾으면 "미확인"으로 적고 그 부분만 멈춘다.
13. **하네스·커밋·PR:** 코드나 문서를 바꾸는 세션은 첫 행위로 `python3 scripts/harness/backlog.py start <태스크 ID>`를 실행한다. 태스크 ID는 S16이 `backlog.py add`로 받아 `golden/STATE.md` 「하네스 태스크 ID」 절에 적어 둔 1단계 번호를 쓴다(번호를 눈으로 짓지 않는다). 커밋 메시지는 `S<번호>: <한 줄> (F-NN)` 형식. 작업이 끝나면 PR을 열고 본문 첫 질문에 GP 번호와 F 번호를 적는다. main 머지는 Kiki가 한다.
14. **한국어:** 코드 주석·문서·보고는 한국어로 쓴다(식별자는 영어).
15. **종료 보고 7줄:** 완료 보고 형식 외에 답변 끝에 반드시 쓴다 — ①완료 기준 충족 여부(아니오면 어디까지) ②tests/golden 결과(초록/빨강·테스트 N개) ③HARVEST.md에 오늘 추가한 줄 ④LATER.md에 오늘 추가한 줄 ⑤오늘 범위 밖으로 나가려다 멈춘 순간 ⑥AI 스모크 120 결과: M1 __% / M2 __턴 / M3 __% / M4 __건 / M5 __건(S19 전이면 "해당 없음") ⑦이 세션이 FINDINGS F-__를 전진시켰는가: 예/아니오/판정 세션에서 확인.

**완료 보고 형식**

```
작업 번호: S19
결과: 완료 | 일부 완료 | 중단
인용 FINDINGS: F-NN
만든 것: 파일·테이블·화면 이름 (경로 포함)
완료 기준 확인: 항목별 통과/실패와 근거 (실행한 명령 또는 본 화면)
미확인·가정한 것: 없으면 "없음"
다음 작업이 알아야 할 것: 없으면 "없음"
```

**용어**

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
| 전이 의존 절단 | 개정판 S20+1(작업 번호 `S20A`). 골든 패스 S15 측정(main `a9cff6ec`)에서 골든이 옛 모듈 122개(직접 import 대상 모듈 7종·파일 4개, 상류 전이 포함 120~122)를 쓰는 것을 직접 10개·전이 30개 이하로 줄인다. 끌고 오는 것은 `src/backend/golden/` 아래로 복사해 의존을 자른다(다섯 걸음 ③). 3단계 S74에서 옛 패키지를 통째로 지우기 위한 전제 |
| LEGACY_MANIFEST.txt | `golden/LEGACY_MANIFEST.txt`(S35 신설 · 개정판 §2). S15 미참조 목록(백엔드 722모듈·Flutter 74파일) + 1단계 3주간 여전히 import 안 된 옛 모듈 추가분을 모듈 이름 한 줄씩 적는 대장. `/legacy` 물리 이동은 Kiki 결정 |
| 사람 출처 로그 | 골든 패스 S9~S12가 남긴 본인(`self-1`·`self-norole`)·성인(`adult-1`·`adult-2`) 턴 기록. 실제 중학생 로그는 2026-11-15 현재 **0건**이다 |
| 사전 실측 | 이 지시서를 쓰며 2026-11-15에 main `a9cff6ec` 기준으로 직접 확인한 값. 세션에서 재확인한다 |

**공유 계약**

아래 모양은 S16~S35가 전부 같이 쓴다. 바꿔야 한다고 판단하면 바꾸지 말고 보고에 "계약 변경 제안"으로 적고 멈춘다. 골든 패스 공유 계약(HTTP 3개·문항 JSON·채점·숙련도·DB 표 3개·환경변수 — `golden/prompts_src/spec.md`)은 그대로 유효하며 여기서는 1단계가 더하는 것만 적는다.

*계획서 전제와 저장소 사실이 다른 곳(사전 실측 2026-11-15 · main `a9cff6ec`) — 지시문은 저장소 사실을 따른다*

| 계획서가 전제한 것 | 저장소 사실 | 이 지시서의 처리 |
| --- | --- | --- |
| 골든 패스 §6 완료 판정 5줄이 전부 "예"(실학생 5명·세션 30건) | **실제 중학생 0명.** 사람 출처 로그는 본인 `self-1`(5문제)·`self-norole`(30)·성인 `adult-1`·`adult-2`(60) = 문제 기록 95건·턴 약 125개. AI 시뮬레이션(S11 3 페르소나) 기록 70건. `golden/FINDINGS.md`「피험자 한계」 | S16 시드는 **사람 출처 로그**에서 뽑고 "실학생 0"을 시드 README와 CALIBRATION.md 첫 줄에 적는다. 실학생 섭외(H2)는 2026-11-17 Kiki 결정으로 **중단**이고 S24·S29·S33은 AI 학생으로 연다(아래 「실학생 대체 결정」). 게이트 §7 "실학생 3명 이상"은 "미실시"로 적는다 |
| `rubric.yaml v0.2`(T1이 가져올 루브릭 파일) | 그 이름의 파일은 저장소에 **없다**(`find . -name "rubric*.y*ml"` 0건). 루브릭 자산은 둘이다 — ①`src/backend/whymath_backend/harness/pedagogical_rubric.py`(정답 유출 결정론 탐지기 `detect_answer_leakage(response, answer)` + 소형 루브릭 `score_tutoring_response(response, *, answer)`, 순수 함수·LLM 불요) ②골든 패스 S9가 만든 되묻기 루브릭 v0 `golden/reports_no_students/S9/되묻기_루브릭.md`(C1 되짚기·C2 질문 하나·C3 정답 비노출·C4 학생 몫 보존·C5 오류 겨냥 — 사람이 판정) | T1의 옛 자산 후보 = ①의 함수 2개(결정론·5걸음 적용 가능). ②는 이미 골든 안에 있는 판정 틀이라 "가져올 것"이 아니라 S23·S25의 **사람 판정 기준**이다. S21이 확정한다 |
| 오개념 DB 400개 중 일차함수분 15~25개 | `data/corpus/misconceptions_v1/misconceptions.json` 총 843건 중 `subunit=일차함수` 또는 성취기준 `[9수02-14]`·`[9수02-15]`·`[9수02-16]`인 것은 **8건**(M0034 y절편을 기울기로 · M0035 음의 기울기 방향 · M0036 x절편·y절편 혼동 · M0037 f(2)를 2f로 · M0409 · M0567 · 외 2). 부호 오개념(M0001 (−)×(−)=(−) · M0002 3−(−5)=−2 · M0548)은 선행 단원(정수 연산)에 있다. 로더는 `whymath_backend/l1/misconception/catalog_loader.py`의 `load_misconceptions`·`MisconceptionCatalogStore` | S26이 일차함수 8건 + 일차함수 문항에서 실제로 나는 선행 오개념(부호·대입)을 더해 **N건을 세어 적는다**(목표 15~25는 "있으면"이지 채우라는 뜻이 아니다). 주입기(S17)는 이 목록을 기다리지 않고 OP 코드로 먼저 만든다 |
| 야간 스모크 120세션을 "매일 CI에서 자동" | CI(`.github/workflows/ci.yml`)에는 LLM 키가 **없다**(`secrets.*`는 `GITHUB_TOKEN`뿐 · `e2e-nightly` 잡도 mock LLM). 셀프호스트 러너 없음. 스케줄 트리거는 매일 18:00 UTC(03:00 KST) 하나 | 야간 스모크는 **두 겹**이다. ⓐ CI: 새 워크플로 `golden-sim-nightly.yml`(18:30 UTC)이 `GOLDEN_FAKE_LLM=1`로 120세션을 돌려 파이프라인 무결성(M4 크래시·M5 렌더·주입기 결정성·M1 규칙 검사기 자체)만 잰다 ⓑ Kiki 머신: 같은 명령을 실제 LLM(튜터 OpenRouter·학생 Ollama)으로 돌려 M1~M5를 잰다. 주 1회 720세션(`SIM_FULL=1`)도 Kiki 머신이다. 두 결과 파일은 이름으로 구분한다(`sim_report.json` vs `sim_report_fake.json`). CI에 LLM 키를 넣을지는 Kiki 결정(제안값: 넣지 않는다 — 시드 반출 규칙과 비용) |
| 학생 모델 `import ollama` 직접 호출 | CLAUDE.md "LLM 호출은 항상 라우터 경유". 옛 코드에 `whymath_backend/l3/providers/ollama.py`의 `OllamaProvider`가 있다(`ollama_host` 설정 사용) | 공통 규칙 9대로 `OllamaProvider` 경유. 모델 ID 지정이 안 되면 `sim/`에 복사 |
| BKT 옛 모듈 1개 + 파라미터 4개 | `src/backend/whymath_backend/l2/bkt.py` — `BktParameters`(pydantic·비퇴화 검증 포함), 순수 함수 `posterior_mastery(prior, correct, params)`·`apply_learning`·`apply_forgetting(mastery, elapsed_days, params)`·`update_mastery(prior, correct, params)`·`probability_correct`, 클래스 `BktModel(params)`(`initial_mastery`·`update`·`update_sequence`·`predict_correct`·`apply_forgetting`) | T3의 옛 자산 = `BktParameters` + `update_mastery`(망각은 §6 금지 — `apply_forgetting`은 가져오지 않는다). 파라미터 이름·개수는 S31이 파일에서 읽어 확정한다(사전 실측은 함수 이름까지만) |
| 옛 합성 학생 자산 | `grep synthetic_student|SyntheticStudent|student_simulator` 0건. 골든 패스 S11이 만든 `src/backend/golden/sim_student.py`(페르소나 3종 `slope-blind`·`sign-slip`·`no-setup`, 클라우드 LLM, `httpx.ASGITransport`로 `golden.api:app` 직접 호출, `--retry-rule`)가 유일한 선례 | S18·S19는 `sim_student.py`의 ASGI 호출·CSV 기록·개인정보 검사(`_check_privacy`)를 **재사용**하고, 페르소나 3종은 8종 체계(P1~P8)로 흡수한다(`slope-blind`→P3+OP_03 · `sign-slip`→P3+OP_01 · `no-setup`→P3+OP_06). `sim_student.py`는 지우지 않고 `golden/sim_personas.md`와 함께 남긴다(S35 미참조 목록에서 판단) |
| S15 측정 "옛 코드 844모듈 중 722모듈 미참조 · 골든이 122개 사용" | main에 **있다**(PR #1915 · `golden/reports_no_students/S15/measure_summary.json` · 측정기 `src/backend/golden/measure_unreferenced.py` + `tests/golden/test_measure_unreferenced.py`). 숫자: 전체 844 · 미참조 722(286,275줄) · 사용 122(30,194줄) · 정적 직접 16(패키지 조상 포함) · 조상 포함 전이 120 · 런타임 122. **골든이 직접 import하는 옛 모듈은 7종**(`grade`→`l3.safe_parse` · `store`→`config`·`db.session` · `tutor`·`sim_student`→`l3.models`·`l3.providers.factory`·`l3.router`·`schema.enums`). 사용 122개의 대부분은 `db`(64)·`schema`(35)·`l3`(18)의 전이다 | S20A가 이 파일을 입력으로 쓴다. 목표 "직접 10 이하"는 7종 기준으로 이미 충족이므로 S20A의 본체는 **전이 120→30**이다(`config`·`db.session`이 끌고 오는 `db` 64·`schema` 35가 핵심). 측정기는 그대로 재사용하고 `--budget` 판정만 더한다 |
| 1단계 S16~S35 번호가 비어 있다 | main의 `golden/NEXT_3WEEKS.md`(S15 산출물)가 **같은 번호 S16~S28을 "골든 패스 2회차"(실제 중학생 1명 검증·FINDINGS 2·3위·LATER 상위)로 이미 쓴다**. 두 계획이 같은 번호를 다른 내용으로 가리킨다 | **Kiki 결정이 필요하다**(S16 첫 단계 · 제안값: 이 1단계 묶음이 정본이고 NEXT_3WEEKS.md 머리에 "1단계 계획서(개정판)로 대체됨 — 실학생 1명 검증은 H2·S24로 흡수" 한 줄을 적는다). 결정 전에는 S16이 번호 충돌을 보고 첫 줄에 적고 멈추지 않는다 |

*실학생 대체 결정(Kiki 2026-11-17 · 기록 `golden/reports_phase1/H2/보고.md` 0절) — 이 블록이 아래 다른 절의 "실학생" 문구보다 우선한다*

- **결정 둘:** ①"실 학생 없이 ai로 진행" — H2(실학생 섭외)는 중단이고 S24·S29·S33은 실제 중학생 대신 **AI 학생**으로 연다 ②"여기서 발생할 수 있는 문제들은 개방 시점에 보완" — 실학생이 없어서 생기는 공백은 1단계 안에서 메우지 않고 앱을 실제 사용자에게 여는 시점에 메운다. **실학생 0명이어도 1단계를 멈추지 않는다.**
- **AI 대체 세션의 모양(S24·S29·S33 공통):** 러너(`golden.sim.run`)를 Kiki 머신에서 실제 LLM(튜터 OpenRouter · 학생 로컬 Ollama — 공통 규칙 7·9 그대로)으로 돌리고, 그 `sessions.jsonl`에서 **정해 둔 페르소나 × LF-01~LF-05 × 1회차** 행만 골라 사람 세션 대신 **정독**한다. 세션 1개 = 문항 1개 풀이 기록 1건(시뮬레이터 입출력 모양 그대로). 닉네임은 `sim-<페르소나>-<회차>`이고 `stu-*`는 쓰지 않는다.

| 세션 | "학생" 구성 | 로그 | 누적 |
| --- | --- | ---: | ---: |
| S24 | P2·P3·P4 × LF-01~LF-05 | 15건 | 15 |
| S29 | P2·P3·P4 × LF-01~LF-05 (S24와 같은 구성 — T2 꺼짐/켜짐 전후 비교) | 15건 | 30 |
| S33 | P2·P3·P4·P5 × LF-01~LF-05 | 20건 | 50 |

- **720세션과의 구분:** S23·S28의 720세션은 M1~M5 **집계**(회귀 트랙)다. S24·S29·S33은 15~20건을 턴마다 **손으로 읽고 판정**(루브릭 C1~C5·끊김 4종)한다. 판정 세션(S25·S30·S34)의 근거는 이 손 판정이고 720 집계는 보조 근거다 — 각 절의 "시뮬레이션 숫자로 판정하지 않는다"는 "720 집계 숫자만으로 판정하지 않는다"로 읽는다.
- **보정 전제:** AI 대체 로그를 판정에 쓰는 것은 S20 판정이 go(조건부 통과 포함)이기 때문이다(S23이 이미 S20 go를 선행으로 요구한다). S20이 조건부 통과였다면 S25·S30·S34 판정 첫 줄에 "보정 조건부"를 적는다.
- **이름 붙이기:** S24·S29·S33의 결과는 어디에 적든 출처를 **"AI 대체"**로 적고 "실학생"·"진실 트랙"이라고 부르지 않는다. 모든 판정에는 "잠정 · AI 대체"를 붙인다.
- **다른 절 읽는 법:** S25·S30·S34·S35 절의 "실학생 로그/세션/N건"은 "AI 대체 로그(S24·S29·S33)"로 읽는다. 단 **게이트 ①(실학생 3명·50건)·②(완료율 70%)는 AI 숫자로 채우지 않고 "미실시(Kiki 결정 2026-11-17 · AI 대체)"로 적는다** — S35 "게이트 숫자를 대체 피험자 로그로 채우지 않는다"는 이 두 줄에 그대로 적용된다. GATE.md에는 AI 대체 누적 건수를 **별도 줄**로 적는다.
- **AI 대체로는 말할 수 없는 것:** 이탈률·세션 길이·만족도·"다시 할래?"의 답·소리 내어 말한 것·실제 중학생의 말투. 보고에 이 항목을 지어 적지 않고 "개방 시점 보완"으로 적는다.
- **개방 시점에 보완할 목록:** ①실제 중학생 3명 이상·누적 50건·완료율 70%(게이트 ①②) ②이탈률·세션 길이·만족도 ③AI 대체로 내린 T1·T2·T3 판정의 실학생 재확인 ④보호자 동의 절차(`golden/reports_phase1/H2/섭외_키트.md`). "개방 시점"의 날짜·단계는 미정이다.

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
tests/golden/test_import_budget.py ← S20A (직접 ≤10 · 전이 ≤30 동결)
golden/LEGACY_MANIFEST.txt         ← S35 (미참조 옛 모듈 대장 · 모듈 이름 한 줄씩)
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
- 판정 규칙(계획서 원문): 여섯 줄 모두 "예"면 2단계. 진실 트랙 셋 중 하나라도 "아니오"면 S21~S35를 한 번 더 돈다. 회귀 트랙만 "아니오"면 2단계로 가되 첫 주를 시뮬레이터 수정에 쓴다. 실학생 2명 미만이면 S24·S29·S33 크기를 줄여 누적 30건으로 낮추되 게이트 문서에 "축소"로 표기, 0명이면 1단계를 멈추고 섭외부터.
- **판정 규칙(실학생 대체 결정 뒤 · 2026-11-17):** ①②는 "미실시"로 적고 예/아니오를 매기지 않는다. "0명이면 1단계를 멈춘다"는 적용하지 않는다(Kiki 결정). ③은 AI 대체 로그 기준으로 판정하고 "잠정 · AI 대체"를 붙인다. ③~⑥ 네 줄로 2단계 진행 여부를 **제안**하고 확정은 Kiki가 한다 — 2단계 지시서의 시작 조건("1단계 게이트 진실 트랙 예")과 부딪히므로 S35가 보고 첫 줄에 올린다.

## S16~S20 · H2: 시뮬레이터 (4주차)

시드 추출(S16) 뒤 주입기(S17)·학생 모델(S18)·T1 설계(S21)가 **동시에** 갈 수 있다 — 셋 다 S16의 산출물(시드·OP 코드·FINDINGS 번호)만 기다린다. 러너(S19)는 S17·S18을 잇고, 보정(S20)은 러너 결과를 검사한다. 보정 통과 전까지 시뮬레이터 숫자로 튜터를 판단하지 않는다(계획서 원칙 3). H2(실학생 섭외)는 2026-11-17 결정으로 중단이다(공유 계약 「실학생 대체 결정」). 개정판이 더한 **S20A(전이 의존 절단)**는 S15 측정 파일만 입력으로 쓰므로 S16과 함께 시작할 수 있고, T1 import(S22)는 S20A가 정한 예산 안에서 한다.

### S16. 시드 추출 — 사람 출처 로그 → golden/sim/seed/ + FINDINGS 번호 + 하네스 등재

- **목적:** 시뮬레이터가 흉내 낼 **실제 말투**와 비교 기준(턴 수·오류 유형 분포)을 사람 출처 로그에서 뽑는다. 코드는 추출 스크립트 하나뿐이다. 함께 1단계의 번호 체계 두 가지(FINDINGS `F-NN`·하네스 태스크 ID)를 만든다.
- **선행 산출물:** 골든 패스 산출물 전부(main에 있음). 사람 출처 턴 CSV — `golden/logs/self1_turns.csv`·`adult1_turns.csv`·`adult2_turns.csv`는 gitignore라 **Kiki 머신에만** 있다. Kiki가 이 세션 컨테이너에 올려 주거나(파일 3개 · 닉네임·session_id 열 없음) 이 세션을 Kiki 머신에서 연다. 없으면 `golden/reports_no_students/S13/problems.csv`·`judging_errors.csv`의 학생 입력 열로 대신하고 보고에 "원본 CSV 없이 S13 집계본으로"라고 적는다.
- **할 일:**
  1. **하네스 등재:** `python3 scripts/harness/backlog.py add`로 1단계 태스크 1건을 등재한다(제안 제목: "GOLD-P1 1단계 두꺼게 — AI 시뮬레이터 + 슬롯 T1·T2·T3 · S16~S35"). CLI가 준 번호로 `backlog.py start <번호>`를 실행하고, 번호를 `golden/STATE.md`「하네스 태스크 ID」 절에 "1단계: <번호>" 한 줄로 적는다. 이후 S17~S35가 이 번호를 쓴다.
  1-b. **번호 충돌 보고:** main의 `golden/NEXT_3WEEKS.md`가 S16~S28을 다른 내용으로 쓴다(공유 계약 전제 표). 보고 첫 줄에 적고 Kiki 결정(제안값: 이 묶음이 정본 · NEXT_3WEEKS.md 머리에 "대체됨" 한 줄)을 받는다. 결정 전에도 이 세션은 진행한다.
  2. **FINDINGS 항목 번호:** `golden/FINDINGS.md` **끝에** `## 항목 번호 (1단계용 · S16)` 절을 덧붙인다. 본문은 한 글자도 고치지 않는다. 번호 표(제안값): `F-00` 시뮬레이터 기반(모든 항목의 측정 수단) · `F-01` 1위 GP-4 마지막 되묻기 C5(S14 적용) · `F-02` GP-5 판정 오류 앞말형(AI 출처) · `F-03` GP-2 문제 이해(no-setup) · `F-04` 판정 문장이 학생 마지막 답을 언급하지 않음 · `F-05` 학생 쪽 오개념 고수(튜터가 못 알아봄 — T2 후보) · `F-06` 숙련도 숫자가 체감과 다름(T3 후보 · 로그 근거 아직 없음 — "가정"으로 표기). 각 줄에 FINDINGS 본문의 절 이름과 출처별 N건 중 M건을 옮겨 적는다.
  3. **발화 수집:** 사람 출처 CSV에서 `student_text`만 모은다(튜터 발화 제외). 출처별 건수를 센다.
  4. **익명화:** 닉네임·이름·학교·지역이 들어간 발화는 그 낱말을 `[이름]`으로 바꾼다. 확신이 없으면 그 발화를 버린다. 결과에서 **20개**를 골라 `golden/sim/seed/utterances.txt`에 한 줄씩 쓴다 — 짧은 것, 오타 있는 것, 구어체인 것을 우선하고 "잘 쓴" 발화는 고르지 않는다(시뮬레이터가 흉내 낼 것은 실제 말투다). 각 줄 끝에 출처 라벨(`self`/`adult`)을 탭으로 붙인다.
  5. **분포 2개:** `golden/sim/seed/distributions.json`에 쓴다 — `turns`: 문항별 정답까지 튜터 턴 수 목록과 중앙값(출처별·합산) · `errors`: 오답을 OP_01~OP_08로 분류한 빈도(분류는 규칙 기반, 모르면 OP_00). OP 코드 표는 공유 계약의 제안값에서 시작해 실제 오답에 맞게 확정하고, 같은 표를 `golden/sim/op_codes.md`에 적는다(주입기·보정 검사가 이 파일을 읽는다 — 커밋 대상).
  6. **추출 스크립트** `src/backend/golden/sim/seed_extract.py`(패키지 `sim/__init__.py` 포함): 입력 CSV 경로들 → 위 두 파일. 익명화 규칙·OP 분류 규칙은 함수로 분리하고 `tests/golden/test_sim_seed.py`로 고정한다(익명화 긍정 3·부정 3 · OP 분류 8종 각 1 · 출력 스키마).
  7. `golden/sim/seed/README.md` 한 줄: "이 폴더의 내용은 로컬 Ollama 외 어디로도 보내지 않는다. 실제 중학생 로그 0건 · 사람 출처 = 본인·성인(2026-11-15)". `.gitignore`는 이미 `logs/`를 무시한다 — `golden/sim/seed/`와 `golden/sim/out/`도 무시되는지 `git check-ignore -v`로 확인하고, 안 되면 **`golden/sim/.gitignore`**(golden/ 안)에 두 줄을 적는다(저장소 루트 `.gitignore`는 건드리지 않는다).
  8. 실학생 3~5명 재참여(실제로는 신규 섭외) 여부를 `golden/CHECKLIST.md` 끝에 "1단계" 절로 적는다 — 값은 H2가 채운다.
- **산출물:** `seed/utterances.txt`(20줄)·`seed/distributions.json`·`seed/README.md`(로컬) · `golden/sim/op_codes.md` · `seed_extract.py` + 테스트 · FINDINGS 「항목 번호」 절 · STATE.md 태스크 ID · CHECKLIST 1단계 절.
- **완료 기준:** ①시드 20개가 익명화돼 있고 실명·학교 낱말이 0건(스크립트 검사 + 눈으로 1회) ②분포 파일에 출처별 중앙값과 OP 빈도가 있다 ③`F-00`~`F-06`이 FINDINGS 끝에 있고 본문 diff가 0줄 ④STATE.md에 1단계 태스크 번호 ⑤`tests/golden` 초록 ⑥시드 파일이 커밋 대상이 아님(`git status`에 안 보임)을 보고에 적는다.
- **하지 말 것:** 시드를 PR·보고·채팅에 그대로 붙이지 않는다(보고에는 건수와 라벨만). FINDINGS 본문을 고치지 않는다. 발화를 "다듬지" 않는다.
- **막히면:** 사람 출처 CSV를 못 받으면 S13 집계본(`problems.csv` 학생 입력 열)으로 진행하고 완료 기준 ①의 건수를 그대로 적는다. 20개를 못 채우면 채운 수를 적고 멈추지 않는다.

### H2. 실학생 3~5명 섭외 (Kiki)

- **상태(2026-11-17): 중단.** Kiki 결정 "실 학생 없이 ai로 진행"으로 이 작업은 하지 않는다(기록·섭외 문구: `golden/reports_phase1/H2/보고.md`·`섭외_키트.md`). S24·S29·S33은 더 이상 H2를 선행으로 요구하지 않는다. 아래는 개방 시점에 섭외를 다시 열 때를 위한 원래 지시다.
- **목적:** 진실 트랙(S24·S29·S33)에 실제 중학생이 필요하다. 골든 패스 3주 동안 0명이었으므로 **신규 섭외**다.
- **선행 산출물:** 없음.
- **할 일:** 골든 패스 H1과 같다 — 지인 자녀·학원·도서관 중 한 곳, 세션당 20분, 보상 문화상품권 1만 원, 보호자 동의 문구("AI 수학 앱을 20분 써 보고 느낌을 말해 주는 테스트. 이름·학교는 저장하지 않고 닉네임만 씁니다. 대화는 개발자 컴퓨터에만 보관"). `golden/reports_phase1/H2/보고.md`에 가명·학년·일정(S24/S29/S33)·동의 여부 표(실명·연락처 금지). 같은 학생이 세 차례 모두 오면 좋지만 필수는 아니다.
- **완료 기준:** S24 전 3명, S29 전 3명(같은 사람 가능), S33 전 4명. 누적 세션 50건이 목표이므로 1명당 회차마다 5문제 이상.
- **막히면:** S24에 2명 미만이면 S24·S29·S33 크기를 줄여 누적 30건을 게이트로 낮추고 게이트 문서에 "축소" 표기. 0명이면 1단계를 멈추고 섭외부터(계획서 §7 리스크 표).

### S17. 오개념 주입기 — src/backend/golden/sim/errors.py

- **목적:** LLM 없이 규칙만으로 "결정적으로 틀린 답"을 만든다. 같은 (문항, 오개념) 입력에는 항상 같은 틀린 답이 나와야 M3(판정 오류)과 오개념 검출률을 잴 수 있다.
- **선행 산출물:** S16의 `golden/sim/op_codes.md`·`distributions.json`(OP 빈도), 문항 30개(`golden/data/problems_linear_fn.json`).
- **할 일:**
  1. 데이터클래스 `WrongAnswer(text: str, op_code: str, misconception_id: str | None)`와 함수 `inject(problem: Problem, misconception_id: str) -> WrongAnswer`. 오개념 ID는 `data/corpus/misconceptions_v1/misconceptions.json`의 일차함수분 8건(`M0034`·`M0035`·`M0036`·`M0037`·`M0409`·`M0567`·외 2 — 세션에서 `subunit=일차함수` 또는 성취기준 `[9수02-14/15/16]`으로 다시 센다)과 선행 부호 오개념(`M0001`·`M0002`·`M0548`)을 받는다. 옛 로더는 쓰지 않고(5걸음 대상은 T2의 일) ID → OP 코드 → 변형 규칙 표를 `errors.py` 안 딕셔너리로 둔다(T2가 S26에서 정식 목록으로 바꾼다 — 그때까지 중복은 의도된 것).
  2. OP 코드별 변형 규칙(예: OP_01 부호 — 식의 음수 곱 결과 부호 뒤집기 · OP_02 — `f(k)`를 `k×(계수 합)`으로 · OP_03 — 기울기 분자·분모 교환 · OP_04 — 기울기↔절편 교환 · OP_05 — 대입식 문자열 그대로 · OP_06 — 문항 본문의 첫 숫자 · OP_07 — 절편 교환 · OP_08 — 부호 반대 기울기). 문항 유형에 맞지 않는 오개념(예: f(k) 문항에 OP_03)은 `None`을 반환하고 호출자가 다른 오개념을 고른다. 문항 유형은 `answer_kind`와 본문 키워드(`기울기`·`절편`·`식을 구하`)로 판별하고 그 판별 함수도 테스트한다.
  3. **정답과 같지 않음을 보장**: 만든 답을 `grade.is_correct`로 채점해 정답이면 변형을 한 단계 더 적용하고, 두 번째도 정답이면 `None`.
  4. 테스트 `tests/golden/test_sim_errors.py`: ①결정성 — 같은 입력 100회 호출이 같은 출력 ②30문항 × 오개념 전부에서 반환값이 `None` 또는 오답(정답인 경우 0건) ③OP 코드 8종 각각 최소 1문항에서 실제 예시가 나온다 ④유형 판별 함수의 긍정/부정.
  5. 30문항 × 오개념 ID 전부의 (문항, 오개념, 틀린 답, OP) 표를 `golden/reports_phase1/S17/injection_table.csv`로 저장하고 보고에 요약(오개념별 적용 가능 문항 수).
- **산출물:** `sim/errors.py`, 테스트, injection_table.csv.
- **완료 기준:** ①"같은 입력 → 같은 틀린 답" 테스트 초록 ②30문항 × 일차함수 오개념 8건 + 부호 3건 = 330 조합에서 정답과 같은 출력 0건 ③OP 8종 전부 예시 1건 이상 ④`tests/golden`·정적 검사 초록.
- **하지 말 것:** LLM을 부르지 않는다. 옛 오개념 로더·매칭 모듈을 import하지 않는다(T2 슬롯이 5걸음으로 가져온다). 오개념을 9개째부터 "만들어" 넣지 않는다 — DB에 없는 것은 OP 코드만으로 간다.

### S18. 학생 시뮬레이터 — src/backend/golden/sim/student.py + 페르소나 8개

- **목적:** 주입기의 답(또는 페르소나 규칙)에 중2 말투를 입혀 다음 발화를 만든다. 로컬 Ollama 모델 2개를 비교해 1개를 고른다.
- **선행 산출물:** S16 시드 발화 20개·`op_codes.md`. (S17과 동시에 진행 가능 — 주입기 결과가 필요한 P3 경로는 `forced_answer` 문자열을 인자로 받으므로 S17 없이도 테스트된다.)
- **할 일:**
  1. `golden/sim/personas.md`에 P1~P8을 공유 계약 표대로 적는다(절 형식은 `golden/sim_personas.md`와 같게 — `## P3 오개념 보유형` 절 본문이 지시문). 공통 말투 지시에 시드 발화 20개를 **파일에서 읽어** 넣는다(파일에 하드코딩 금지).
  2. `student.py`: `reply(persona, problem, history, forced_answer: str | None) -> str`. `forced_answer`가 있으면(P3·P8) 그 값을 반드시 포함하고 말투만 입힌다. P1·P5·P7·P8은 **규칙만으로** 발화를 만든다(LLM 불필요 — 가짜 모드·CI와 같은 경로). P2·P3·P4·P6은 로컬 Ollama. 출력은 한 줄(개행 제거), 길이 상한 100자(P7 500자 붙여넣기는 예외 경로).
  3. 학생 LLM 호출: 공통 규칙 9 — `whymath_backend.l3.providers.ollama.OllamaProvider`를 `Router.route`의 LOCAL 결정과 함께 쓴다. 모델 ID는 환경변수 `GOLDEN_SIM_STUDENT_MODEL`. 프로바이더가 임의 모델 ID를 못 받으면 클래스를 `sim/ollama_client.py`로 복사해 모델 인자를 열고 HARVEST.md에 "복사: 모델 지정 불가"로 적는다. 호출 전 `sim_student._check_privacy`와 같은 검사(닉네임·session_id·정답이 프롬프트에 없는지)를 통과해야 한다.
  4. **모델 비교(Kiki 머신 · Ollama 설치 전제):** 후보 2개(제안값: `exaone3.5:7.8b`와 `qwen2.5:7b` — Kiki 머신에 이미 있는 태그로 바꾼다 · `ollama list`로 확인). 기준 두 가지 — ⓐ시드 말투 재현(시드 20개와 모델 발화 20개를 섞어 세션 AI가 구분 시도 → 구분 정확도가 낮은 쪽) ⓑ페르소나 규칙 준수(P1은 "답만", P4는 질문으로 시작 등 규칙 위반 수 / 페르소나별 5개). 결과 표를 보고에 적고 1개를 `GOLDEN_SIM_STUDENT_MODEL` 기본값으로 확정한다. 클라우드 세션에는 Ollama가 없으므로 이 단계는 **Kiki 머신 런북**(PowerShell · 자리표시자 0 · `cd C:\Users\kiki\Desktop\__AI\WhyMath`)으로 낸다.
  5. 페르소나별 발화 샘플 5개씩(40개)을 `golden/reports_phase1/S18/samples.md`에 적는다(시드 원문은 넣지 않는다 — 모델 출력만).
  6. 테스트 `tests/golden/test_sim_student.py`(S11의 같은 이름 파일이 있으면 이름을 `test_sim_student_v2.py`로): 가짜 모드에서 ①P1·P5·P7·P8 규칙 발화 ②`forced_answer` 포함 보장 ③프라이버시 검사가 닉네임·정답 혼입을 막는다(주입 1건) ④시드 파일이 없을 때 명확한 오류(침묵 금지).
- **산출물:** `student.py`, `personas.md`, 모델 비교 표, samples.md, 테스트, Kiki 머신 런북.
- **완료 기준:** ①로컬 모델 2개 비교 표와 선택 1개 ②페르소나별 샘플 5개(40개) ③규칙 발화 4종 테스트 초록 ④프라이버시 주입 테스트 RED→GREEN 확인 ⑤시드 발화가 클라우드 프로바이더 호출 경로에 들어가지 않음을 테스트로 동결(공통 규칙 7).
- **하지 말 것:** 시드 발화를 보고·PR·채팅에 붙이지 않는다. 페르소나를 9개 이상 만들지 않는다. 튜터 코드(`api.py`·`tutor.py`)를 고치지 않는다.
- **막히면:** Kiki 머신 Ollama에 후보 모델이 없으면 `ollama pull` 명령을 런북에 넣고(모델 크기 명시), 7B급 하나만으로 진행해 "비교 미실시"로 적는다.

### S19. 러너 + 야간 CI — src/backend/golden/sim/run.py · metrics.py · golden-sim-nightly.yml

- **목적:** 주입기와 학생 모델을 튜터에 붙여 720세션(또는 120)을 돌리고 M1~M5를 잰다. 120세션 스모크를 매일 돌린다.
- **선행 산출물:** S17 `errors.py`, S18 `student.py`·`personas.md`.
- **할 일:**
  1. `metrics.py`: M1~M5 계산 함수(공유 계약 정의). M1 판정은 `whymath_backend.harness.pedagogical_rubric.detect_answer_leakage`를 **import해 쓴다**(순수 함수 · HARVEST.md에 한 줄 — 이것은 T1 슬롯 자산과 같은 파일이지만 측정용 import이지 GP-4 연결이 아니다. T1이 S22에서 GP-4에 붙이는 것과 구분한다). M5는 정규식(짝 안 맞는 `$`, `\frac` 뒤 중괄호 결손, 백틱).
  2. `run.py`: 인자 `--sessions`·`--personas`·`--date`·`--base-url`(없으면 ASGI). 세션마다 GP-1(닉네임 `sim-<P>-<회차>`) → GP-2 → 학생 발화 → GP-3/4 → … → GP-5/6을 **HTTP로만**(S11 `sim_student.py`의 ASGI 호출 코드 재사용 가능 — 복사 아닌 import). 세션 원자료를 `golden/sim/out/<날짜>/sessions.jsonl`에 **세션마다 즉시** 한 줄씩 쓴다(마지막에 모아 쓰지 않는다 — 중간에 죽어도 증거가 남게). `report()`는 `sim_report.json`(가짜 모드면 `sim_report_fake.json`)을 쓰고 차단 기준 위반 시 exit 1.
  3. 비용 가드: `--sessions 720`은 `SIM_FULL=1`일 때만. 외부 호출마다 타임아웃(튜터 30초·학생 30초).
  4. **야간 CI(배선 파일 1개):** `.github/workflows/golden-sim-nightly.yml` 신설 — cron `30 18 * * *`(03:30 KST), `workflow_dispatch` 포함. 잡 1개: `ci.yml`의 `golden-path` 잡과 같은 Postgres 서비스·Python 3.12·의존성 설치 스텝을 복사하고 `GOLDEN_FAKE_LLM=1 python -m golden.sim.run --sessions 120 --personas P1,P2,P5,P7`을 돈다. 마지막 스텝은 그 명령 자신(exit code 보존). 실패하면 `actions/github-script`로 main 대상 열린 PR 전부에 라벨 `sim-red`를 붙인다(제안값 · 라벨은 Kiki가 미리 만든다 · 권한 `pull-requests: write`). `tests/infra`에 워크플로 인벤토리 테스트가 있는지 `grep -rn "workflows" tests/infra | head`로 확인하고 요구하는 등재가 있으면 따른다.
  5. **Kiki 머신 야간 실행 런북**(`golden/reports_phase1/S19/런북.md`): Windows 작업 스케줄러에 03:30 등록하는 PowerShell 블록(자리표시자 0 · 서버 블록과 실행 블록 분리 · `git log -1 --oneline` 자가검증) — 실제 LLM으로 같은 120세션을 돌려 `sim_report.json`을 남긴다.
  6. 첫 실행: 클라우드 세션에서 가짜 모드 120 → M4·M5 0건 확인. Kiki 머신에서 실제 120 1회 → M1~M5 숫자·가장 많이 실패한 페르소나·가장 오래 걸린 문항을 보고에 적는다. **오늘 M1이 0%가 아니어도 튜터를 고치지 않는다**(보정 전 숫자는 시뮬레이터 버그일 수 있다).
  7. 테스트 `tests/golden/test_sim_run.py`: 가짜 모드 2페르소나 × 2문항 → jsonl 4줄·report 필드 전부·exit code(치명 위반 주입 시 1 — M4 강제 1건 주입 픽스처).
- **산출물:** `run.py`·`metrics.py`, 워크플로 1개, 런북, 첫 보고서 2개(fake·live), 테스트.
- **완료 기준:** ①가짜 모드 120세션이 돌고 `sim_report_fake.json`에 M1~M5가 찍힌다(M4·M5 0) ②Kiki 머신 실제 120세션 `sim_report.json` 1개 ③워크플로가 `workflow_dispatch`로 1회 수동 실행돼 초록 ④`report()` exit 1 주입 테스트 RED→GREEN ⑤`tests/golden`·정적 검사 초록.
- **하지 말 것:** 러너가 `api.py` 내부 함수를 직접 부르지 않는다(실학생과 같은 길). CI에 LLM 키를 넣자고 제안하지 않는다(Kiki 결정 사항으로만 적는다). 결과가 나쁘다고 프롬프트를 고치지 않는다.
- **막히면:** `golden-sim-nightly.yml`이 CI 인벤토리 테스트에 걸리면 그 테스트가 요구하는 등재만 하고(테스트 수정 금지), 안 되면 워크플로 없이 런북만으로 종료하고 "CI 배선 보류: <테스트 이름>"으로 적는다.

### S20. 보정 검사 — src/backend/golden/sim/calibrate.py · CALIBRATION.md (관문 ①)

- **목적:** 시뮬레이터가 사람을 닮았는지 세 기준으로 검사한다. 하나라도 어긋나면 튜터가 아니라 시뮬레이터를 고치고 다시 검사한다. 통과 전 시뮬레이터 숫자는 튜터 판단에 쓰지 않는다.
- **선행 산출물:** S16 `distributions.json`·시드, S19 `out/<최근>/sessions.jsonl`(Kiki 머신 실제 실행분 · 가짜 모드는 보정 대상이 아니다).
- **할 일:**
  1. `calibrate.py`: 입력 두 파일 → ①턴 수 중앙값 차이(P2·P4·P5 합산 vs 사람 출처) ②오류 유형 상위 3개 OP 겹침 수 ③블라인드 시트 생성. 출력은 JSON + 사람이 읽는 표.
  2. 블라인드: 사람 발화 20(시드) + AI 발화 20(실제 실행분)을 무작위로 섞어 `golden/sim/CALIBRATION_blind.md`에 번호만 붙여 쓴다. 정답 키는 `CALIBRATION_key.txt`(gitignore). Kiki가 맞히고 결과를 알려 주면 정확도를 계산한다(70% 이하면 통과 — 구분이 어려울수록 좋다).
  3. `golden/sim/CALIBRATION.md`: 첫 줄 "통과 (날짜)" 또는 "미통과 (날짜) — 기준 N". 세 기준의 숫자, 비교 불가 항목(이탈률 — AI는 항상 0 · 세션 길이 — AI는 지루해하지 않음 · 만족도)을 "진실 트랙만 말할 수 있다"로 명시, 실학생 0명 사실.
  4. 미통과면 원인 후보 3개 이내(흔한 것: 시드 발화가 너무 정제됨 → 더 거친 발화로 교체 · 페르소나 규칙이 모델에 안 먹힘 → 규칙을 더 짧게 · 주입기 OP 분류가 사람 분포와 다름 → 분류 규칙 통일). 시뮬레이터 쪽 파일(`seed/`·`personas.md`·`errors.py`·`student.py`)만 고치고 Kiki 머신에서 120세션을 다시 돌린 뒤 재검사. **튜터는 건드리지 않는다.**
  5. 세 번 반복해도 미통과면 계획서 §7 리스크 대응: 블라인드만 통과하면 "조건부 통과"로 S21 이후 진행하되 분포 기준은 "참고"로 격하하고 CALIBRATION.md에 명시(Kiki 결정).
  6. 테스트 `tests/golden/test_sim_calibrate.py`: 세 기준 계산 함수의 통과/미통과 픽스처 각 1, 블라인드 시트에 정답 라벨이 섞이지 않음.
- **산출물:** `calibrate.py`, `CALIBRATION.md`, `CALIBRATION_blind.md`, 테스트.
- **완료 기준:** ①CALIBRATION.md 첫 줄이 "통과" 또는 "조건부 통과(Kiki 결정)" ②세 기준 숫자가 있다 ③비교 불가 항목 명시 ④판정: **go**(통과/조건부 통과) / **no-go**(미통과 — 다음 세션은 S20 반복).
- **하지 말 것:** 튜터 코드·프롬프트 수정 금지. 블라인드 정답 키를 커밋하거나 보고에 붙이지 않는다. 기준을 낮춰 통과시키지 않는다(조건부 통과는 Kiki 결정으로만).

### S20A. 전이 의존 절단 — 골든이 쓰는 옛 모듈 직접 10개·전이 30개 이하 (개정판 S20+1)

- **목적:** 골든 패스 S15 측정에서 골든이 옛 모듈 122개를 쓰고 있다(직접 import 대상은 7종인데 `config`·`db.session`·`l3.router` 등이 전이로 120개를 끌고 온다). 3단계 S74에서 옛 패키지를 통째로 지우려면 이 수가 작아야 한다. 끌고 오는 것은 `src/backend/golden/` 아래로 복사해 의존을 자른다(다섯 걸음 ③ — "복사: 의존 과다").
- **선행 산출물:** main의 `golden/reports_no_students/S15/measure_summary.json`(`golden_direct_imports` · `static_with_ancestors_modules` · `runtime_modules`)과 측정기 `src/backend/golden/measure_unreferenced.py`. S16과 동시 진행 가능. **S22(T1 import) 전에 끝나야 한다** — 한 세션에 못 끝내면 S21을 하루 미루되 범위는 넓히지 않는다.
- **할 일:**
  1. **재측정:** `cd src/backend && python -m golden.measure_unreferenced`(S15 방식 그대로)로 현재 main의 직접 import 목록(7종 기대)·전이 집합(120 기대)을 받아 보고 첫 절에 숫자와 **전이 상위 10개 패키지**(`db` 64 · `schema` 35 · `l3` 18 …)를 적는다. S15 숫자와 다르면 그 차이도.
  2. **끊을 것 고르기(경계 긋기):** 직접 import 7종 각각에 대해 "골든이 실제로 쓰는 함수·클래스"를 이름 단위로 HARVEST.md에 적는다(예: `l3.safe_parse.safe_parse_expr` 1개 · `config.Settings`의 필드 N개 · `db.session`의 엔진 생성 1개 · `l3.router`·`providers.factory`의 호출 2~3개). 전이가 큰 순서(db·schema·l3)로 "복사해서 자른다 / import 유지" 결정을 적는다. 제안값: ⓐ `db.session`·`config` → 골든 전용 `src/backend/golden/settings.py`(환경변수 3~5개만)·`golden/db.py`(엔진 1개 · `store.py`가 쓴다)로 복사해 `whymath_backend.db`·`schema` 전이(약 99개)를 끊는다 ⓑ `l3.safe_parse` → 함수 1개 복사(sympy 의존만) ⓒ `l3.models`·`providers.factory`·`router`·`schema.enums` → **유지**(LLM 호출은 라우터 경유 — CLAUDE.md 불변 · 이 네 개가 끌고 오는 전이 수를 따로 센다). ⓒ만으로 30을 넘으면 Kiki에게 "라우터 경유 유지 vs 프로바이더 1개 복사" 결정을 올린다(이 세션에서 라우터를 우회하지 않는다).
  3. **복사(다섯 걸음 ③ 순서대로 한 개씩):** 복사본마다 ①HARVEST.md "복사: 의존 과다 · 원본 경로·함수" ②특성화 테스트(원본과 복사본이 같은 입력 10개에 같은 출력 — `tests/golden/characterization/test_s20a_<이름>.py`) ③`tests/golden` 초록 확인 후 다음 복사. 복사본에서 원본 import를 지운다(복사했는데 원본도 import하면 전이가 안 줄어든다 — 재측정으로 확인).
  4. **동결:** `tests/golden/test_import_budget.py` — 측정기로 직접 import 수·전이 수를 계산해 `≤10`·`≤30`을 단언한다(주입: `import whymath_backend.l4` 한 줄을 골든에 넣으면 RED). `lint-imports`(`옛 코드는 golden을 모른다` 계약) 초록 유지.
  5. 결과 표(이전 → 이후 · 직접/전이/모듈 이름)를 보고와 HARVEST.md에. 예산 안에 못 들어가면 **남은 수와 끊지 못한 이유**(라우터 경유 유지 등)를 적고 Kiki 결정으로 넘긴다 — 범위를 넓혀 옛 코드를 고치지 않는다.
- **산출물:** 복사본 모듈(`golden/settings.py`·`golden/db.py`·`golden/safe_parse.py` — 제안값), 특성화 테스트, `test_import_budget.py`, HARVEST.md 줄, 재측정 보고.
- **완료 기준:** ①직접 import 10개 이하 ②전이 30개 이하(둘 다 측정기 숫자 · 이전→이후) ③`lint-imports`·`tests/golden` 초록 ④예산 테스트 RED→GREEN 확인 ⑤라우터 경유 불변(튜터 LLM 호출 경로 diff 0).
- **하지 말 것:** 옛 코드를 고치지 않는다(복사만). LLM 호출을 라우터 밖으로 빼지 않는다. 예산을 맞추려고 측정기를 느슨하게 하지 않는다. 한 세션에 두 자산을 동시에 자르지 않는다(한 개씩 초록 확인).
- **막히면:** 하루 안에 ⓐ만 끝났으면 그 상태로 커밋(초록)하고 S21을 하루 미룬 뒤 같은 번호 `S20A`를 반복한다(보고에 "S20A 2일째").

## S21~S25: 슬롯 T1 — 튜터 되묻기 품질 (5주차)

슬롯은 한 주에 하나다. 설계(S21)는 S16만 있으면 시작할 수 있어 시뮬레이터 작업과 **동시에** 간다. import(S22)는 설계 다음, 적용+AI 회귀(S23)는 보정 통과(S20) 뒤에만 한다. 그다음 실학생 1차(S24)와 판정(S25).

### S21. T1 설계 — FINDINGS 순위 재확인 + 특성화 테스트

- **목적:** FINDINGS 1위를 다시 읽고 T1이 가져올 옛 자산 1개를 함수 단위로 확정한 뒤, 그 자산의 지금 동작을 특성화 테스트로 고정한다(5걸음 중 ①②).
- **선행 산출물:** S16의 FINDINGS 번호(`F-01` 등).
- **할 일:**
  1. FINDINGS 순위 재확인: `F-01`(GP-4 C5)은 S14가 프롬프트로 고쳤다. T1의 대상이 여전히 "되묻기 품질"인지, 남은 형태가 무엇인지(FINDINGS「1위」절의 "S10 뒤에도 남은 형태" · S14 보고의 측정 결과 · LATER의 S14 행 2건 — '학생' 호칭 · 앞말 정답)를 읽고 **이 슬롯이 인용할 F 번호 하나**를 정한다. 기본 배정이 FINDINGS와 다르면 슬롯 내용을 바꾸고 보고에 이유를 적는다(세션 수는 바꾸지 않는다).
  2. 옛 자산 확정(5걸음 ①): 계획서의 `rubric.yaml`은 없다(공유 계약 전제 표). 후보는 `whymath_backend/harness/pedagogical_rubric.py`의 `detect_answer_leakage(response, answer)`와 `score_tutoring_response(response, *, answer)` 두 함수(순수·결정론). 일차함수에 필요한 항목 5개 이내로 범위를 긋고 HARVEST.md에 "T1 경계: 함수 2개"를 먼저 적는다. 되묻기 루브릭 v0(C1~C5)는 사람 판정 기준으로 S23·S25가 쓴다 — 코드로 옮기지 않는다(LLM 판정기는 §6).
  3. 특성화 테스트(5걸음 ②): `tests/golden/characterization/test_t1_rubric.py` — 옛 함수를 옛 자리에서 그대로 import해 입력 10개(튜터 발화 10 · 그중 정답 유출 3·undecidable 2·깨끗함 5 — 골든 패스 로그에서 고른 실제 문장, 시드 아님) → 출력 10개를 고정한다. 출력이 지금 맞는지는 묻지 않는다.
  4. 비결정성 검사: 같은 입력 100회 → 같은 출력. 아니면 HARVEST.md "버림: 비결정적"으로 적고 T1은 옛 자산 없이 간다(계획서 §4-2).
- **산출물:** HARVEST.md 경계 줄, 특성화 테스트 1파일(10쌍), 보고(인용 F 번호·슬롯 내용 확정).
- **완료 기준:** ①보고 첫 줄에 `F-NN "항목 제목"` ②특성화 테스트 10쌍 초록 + 결정성 100회 ③HARVEST.md에 함수 이름 단위 경계.
- **하지 말 것:** 옛 코드를 고치지 않는다. 테스트가 "틀린" 동작을 고정해도 고치지 않는다. T2·T3의 특성화 테스트를 미리 쓰지 않는다.

### S22. T1 import — src/backend/golden/eval/ + 플래그 GOLDEN_T1_RUBRIC

- **목적:** 5걸음 ③④ — 옛 함수 2개를 골든 안으로 가져오고(의존 3개 이하면 import, 넘으면 복사), GP-4 뒤에 기능 플래그로 붙인다. e2e는 그대로 초록이어야 한다.
- **선행 산출물:** S21 특성화 테스트·경계, S20A(import 예산 — 이 세션의 import가 직접 10·전이 30을 넘기면 복사한다).
- **할 일:**
  1. `src/backend/golden/eval/__init__.py`·`rubric.py`: `whymath_backend.harness.pedagogical_rubric`를 import해 `evaluate_tutor_reply(reply: str, answer: str) -> RubricVerdict`(유출 여부·루브릭 점수·근거)로 감싼다. import 비용(끌려오는 옛 모듈 수)을 `python -X importtime`으로 재 보고에 적는다. 3개를 넘으면 두 함수를 `eval/rubric_copy.py`로 복사해 의존을 자르고 HARVEST.md "복사: 의존 과다".
  2. 연결(5걸음 ④): `api.py`의 `answer()`에서 튜터 응답을 받은 직후 `GOLDEN_T1_RUBRIC=1`일 때만 평가기를 부른다. 결과는 **기록만**(`golden.turns`에 열을 추가하지 않고 새 표 `golden.eval_log(turn_id, verdict_json, created_at)` — `store.py` `create_all` 대상에 추가) 하고 응답은 바꾸지 않는다. 유출(`leak`) 판정이면 로그에 경고(예외 타입명·문제 ID — 응답 문장은 로그에 남기지 않는다).
  3. 플래그 꺼짐(기본)에서 e2e·전체 `tests/golden` 초록, 켜짐에서도 초록(테스트 픽스처로 둘 다).
  4. 특성화 테스트가 골든 안 사본(또는 import)에 대해서도 같은 10쌍을 내는지 확인(복사했으면 테스트를 두 대상에 parametrize).
  5. HARVEST.md에 "T1 import: 함수 2개 · 의존 N개 · import|복사".
- **산출물:** `eval/`, `store.py` 표 1개 추가, 플래그, HARVEST 줄, 테스트.
- **완료 기준:** ①플래그 0/1 양쪽에서 `tests/golden` 초록 ②특성화 10쌍이 골든 안에서도 초록 ③import 비용 숫자가 보고에 있다 ④가짜 모드 스모크 120 M4·M5 0.
- **하지 말 것:** 튜터 응답을 평가 결과로 바꾸거나 막지 않는다(S23의 일이고, 그것도 프롬프트 개정 1회뿐). 루브릭 전체·합성 시나리오·7단계 파이프라인을 가져오지 않는다.

### S23. T1 적용 + AI 회귀 — 튜터 프롬프트 개정 1회, 720세션 전후 비교

- **목적:** T1 평가기가 잡은 것을 근거로 튜터 프롬프트를 **1회** 개정하고, 720세션을 개정 전후로 돌려 M1 0%·M3 1% 미만 유지와 M2 변화를 숫자로 본다. 이것이 실학생 1차(S24) 앞에 거는 체다.
- **선행 산출물:** S22(평가기·플래그), S20 판정 go(보정 통과 — **미통과면 이 세션을 열지 않는다**).
- **할 일:**
  1. Kiki 머신에서 `SIM_FULL=1 python -m golden.sim.run --sessions 720 --date <날짜>-before`(실제 LLM · 플래그 `GOLDEN_T1_RUBRIC=1`). `sim_report.json`과 `eval_log`에서 유출·루브릭 실패 사례를 뽑아 상위 유형 3개를 적는다.
  2. 개정 1회: `golden/tutor_prompt.md`에 **한 문장**(또는 한 규칙) 추가·수정. 후보는 S21이 정한 F 번호가 가리키는 것(예: LATER S14 행의 '학생' 호칭 금지 한 줄)이며 S23 보고에 바꾼 문장 전문을 적는다. 코드 변경 0.
  3. 같은 720세션을 `-after`로 다시 돌린다. 전후 표: M1·M2·M3·M4·M5, 페르소나별 M2, 루브릭 실패 수. **M1 0% · M3 1% 미만이 유지되지 않으면 개정을 되돌린다**(이 세션에서 두 번째 개정은 하지 않는다).
  4. 보정 전에 돌린 숫자(S19 첫 실행)와는 비교하지 않는다(시뮬레이터가 그 사이 바뀌었을 수 있다).
  5. e2e·`tests/golden` 초록, 야간 스모크(가짜) 초록.
- **산출물:** 전후 보고서 2개(`sim_report.json` × 2 · Kiki 머신 → `golden/reports_phase1/S23/`에 복사), 프롬프트 diff 1건, 전후 표.
- **완료 기준:** ①M1 0% · M3 1% 미만 유지 ②M2 전후 변화가 숫자로 있다 ③개정이 1회뿐(diff 1건) ④스모크 초록.
- **하지 말 것:** 개정 2회 금지. 시뮬레이션 숫자가 좋아졌다고 "효과 있음"을 선언하지 않는다(판정은 S25 실학생 로그로). 실학생 세션 직전 외의 시점에 프롬프트를 바꾸지 않는다(계획서 §7 리스크 2).

### S24. AI 학생 1차 — 페르소나 3종 × 5문제 = 로그 15건 (실학생 대체)

- **목적:** 개정된 프롬프트로 AI 학생 3종(P2 시도형·P3 오개념 보유형·P4 질문형)이 각각 LF-01~LF-05를 푼 기록 15건을 **턴마다 손으로 읽는다**. 원래는 실제 중학생 3명의 자리였다(공유 계약 「실학생 대체 결정」). S23의 720세션이 숫자로 본 것을 여기서는 대화 내용으로 본다.
- **선행 산출물:** S23(개정 프롬프트가 main에 머지됨 · 720세션 after 실행). H2는 선행이 아니다.
- **할 일:**
  1. (Kiki) Kiki 머신에서 러너를 실제 LLM으로 돌린다 — `python -m golden.sim.run --personas P2,P3,P4 --date <날짜>-s24`(튜터 OpenRouter · 학생 로컬 Ollama · `GOLDEN_FAKE_LLM` 없음 · `GOLDEN_T1_RUBRIC`은 S23 after와 같은 값). 세션 수·회차 옵션은 S19가 만든 러너의 `--help`에서 확인해 맞춘다(이 지시서는 옵션 이름을 추정하지 않는다). 1회차만 따로 못 돌리면 러너를 고치지 않고 기본 실행 결과에서 고른다. **새로 돌리는 대신** S23 after 실행의 `sessions.jsonl`을 써도 된다 — 조건: 같은 프롬프트(S23 개정 후)·실제 LLM·P2·P3·P4 포함. 어느 쪽인지 보고에 적는다.
  2. (Kiki → AI 세션) `golden/sim/out/<날짜>-s24/sessions.jsonl`에서 P2·P3·P4 × LF-01~LF-05 × 1회차 행 **15건**을 골라 세션에 전달한다(파일은 gitignore · 커밋하지 않는다). 고르는 기준은 이 셋뿐이다 — 내용이 좋아 보이는 것을 고르지 않는다.
  3. (AI 세션) 받은 15건이 조건에 맞는지 먼저 확인한다: 건수 15 · `persona` 3종 × `problem_id` 5개 · `http_status` 전부 2xx · 가짜 모드가 아님(튜터 발화가 `FAKE_PREFIX`로 시작하지 않음). 안 맞으면 판정하지 않고 보고한다.
  4. (AI 세션) `golden/reports_phase1/S24/보고.md`를 쓴다. 첫 줄: "출처: AI 대체(P2·P3·P4) · 실학생 0명 · Kiki 결정 2026-11-17". 내용: 페르소나별 문제 표(문항 ID·턴 수·판정·소요 시간 `elapsed_s`·`injected_op`), 되묻기 루브릭 v0(C1~C5 · `golden/reports_no_students/S9/되묻기_루브릭.md`) 손 판정(튜터 턴마다 ✓/✗와 튜터 발화 인용), 끊김 4종 태깅(FINDINGS 정의 그대로), AI 완료율(GP-6까지 간 세션 ÷ 시작한 세션 — **게이트 ②의 완료율이 아니다**). 고치지 않는다.
  5. (AI 세션) 사람 세션에만 있던 항목(소리 내어 말한 것·"어느 순간이 제일 답답했어?"·"다시 할래?")은 표에 "개방 시점 보완"으로 적고 지어 쓰지 않는다. 손 판정이 한 사람(AI 세션 하나)의 판정이라는 점도 한 줄로 적는다.
- **산출물:** 로그 15건(`sessions.jsonl` 발췌 — Kiki 머신·gitignore), 보고.
- **완료 기준:** ①페르소나 3종 × 5문제 = 15건 기록(조건 확인 통과) ②루브릭 손 판정이 튜터 턴마다 인용과 함께 있다 ③AI 완료율 숫자 ④페르소나별 학생 발화 인용 각 3개 이상 ⑤보고 첫 줄에 "AI 대체" 출처.
- **하지 말 것:** 세션 중 코드·프롬프트·러너 수정 금지. 15건을 내용 보고 골라내지 않는다. 가짜 모드(`GOLDEN_FAKE_LLM=1`) 결과로 판정하지 않는다. 결과를 "실학생"·"진실 트랙"이라 부르지 않는다. 시드 발화(`golden/sim/seed/`)를 보고·채팅에 붙이지 않는다(공통 규칙 7). 로그 파일 커밋 금지(보고에는 인용만).
- **막히면:** Kiki 머신에서 실제 LLM 실행을 못 하면(Ollama·키 문제) 이 세션은 판정하지 않고 멈춘다 — 클라우드 세션에서 가짜 모드로 대신하지 않는다. 조건에 맞는 행이 15건보다 적으면 있는 만큼 판정하고 "축소: N건"을 적는다.

### S25. T1 판정 — FINDINGS 갱신 (관문 ②)

- **목적:** S21이 정한 F 번호의 문제가 **실학생 로그에서** 줄었는지 숫자로 판정한다. 줄지 않았으면 T1을 되돌리고 다른 접근을 S21부터 다시 한다.
- **선행 산출물:** S24 보고·로그, S23 전후 표, 골든 패스 FINDINGS의 같은 항목 수치(사람 출처 기준).
- **할 일:**
  1. 비교 표: 같은 정의(끊김 4종·루브릭 C1~C5)로 S24 15건을 세고, FINDINGS의 사람 출처 수치(본인·성인)와 나란히 둔다. 출처가 다르다(본인·성인 vs 실학생)는 점을 첫 줄에 적는다 — 그래서 이 비교는 "같은 피험자의 전후"가 아니라 "대체 피험자 → 실학생"이다.
  2. 판정: F 번호 항목의 "N건 중 M건"이 줄었으면 **효과 있음**, 같거나 늘었으면 **효과 없음**. 15건은 작으므로 신뢰 구간(윌슨 하한)을 함께 적고 "잠정"을 붙인다.
  3. `golden/FINDINGS.md`에 `## T1 판정 (S25)` 절을 덧붙인다(기존 본문 불변). 항목 번호 표에 T1 결과 열을 더한다.
  4. 효과 없음이면 ①`GOLDEN_T1_RUBRIC` 기본값 0 유지 + 프롬프트 개정 되돌림(S23 diff 역적용) ②같은 슬롯을 두 번 시도하지 않는다(계획서 §4-2) — T1은 끝이고 다음 슬롯(S26)으로 간다. "다른 접근을 S21부터"는 2단계의 일로 FINDINGS_v2 후보에 적는다.
  5. 완료율(게이트 ②)·실학생 수(게이트 ①) 누적을 `golden/reports_phase1/GATE.md`에 적기 시작한다(S30·S34·S35가 이어 쓴다).
- **산출물:** FINDINGS T1 판정 절, GATE.md 초안, (효과 없음이면) 되돌림 PR.
- **완료 기준:** ①판정이 "효과 있음/없음"과 숫자·윌슨 하한으로 적혀 있다 ②GATE.md에 누적 세션 15·실학생 3·완료율 ③판정: **go**(어느 쪽이든 판정 완료 — 효과 없음도 go다) / **no-go**(판정 불가 — 로그 부족).
- **하지 말 것:** 시뮬레이션 숫자로 판정하지 않는다(보조 근거로만). 15건에서 "확정"이라고 쓰지 않는다.

## S26~S30: 슬롯 T2 — 오개념 조회 (6주차)

T1 판정(S25) 뒤에만 시작한다(세 슬롯 동시 진행 금지 — 특성화 테스트를 미리 쓰는 것도 금지). 절차는 T1과 같은 다섯 걸음이다.

### S26. T2 설계 — 오개념 DB 일차함수분 추출 + 특성화 테스트

- **목적:** FINDINGS에서 T2가 인용할 항목(기본 가정 `F-05` 학생 쪽 오개념 고수 · "같은 실수를 반복하는데 튜터가 못 알아본다")을 확인하고, 옛 오개념 카탈로그에서 일차함수분을 함수 단위로 가져올 준비를 한다.
- **선행 산출물:** S25 판정 완료, S16 FINDINGS 번호, S17 `errors.py`의 임시 오개념 표.
- **할 일:**
  1. FINDINGS 재확인: S24 실학생 로그에서 "같은 오개념 반복" 사례가 몇 건인지 센다(S25 보고). 0건이면 T2 기본 배정이 FINDINGS와 맞지 않는 것이다 — 그때는 실학생 로그의 2위 항목으로 슬롯 내용을 바꾸고 보고에 적는다(세션 수 불변).
  2. 옛 자산 경계(5걸음 ①): `whymath_backend/l1/misconception/catalog_loader.py`의 `load_misconceptions`(또는 `MisconceptionCatalogStore`) 1개 + 매칭 로직 후보 1개(`wrong_answer_signature_table.py` 또는 `resolve.py` — 세션에서 "틀린 답 → 오개념 ID"를 하는 함수를 찾는다. 없으면 "매칭 로직 없음 — T2는 로더만 가져오고 매칭은 S27이 주입기 표를 거꾸로 써서 50줄로 새로 쓴다"). HARVEST.md에 먼저 적는다.
  3. 추출: `data/corpus/misconceptions_v1/misconceptions.json`에서 일차함수분(사전 실측 8건) + 일차함수 문항에서 실제로 나는 선행 오개념(부호 3건·대입 등)을 골라 `golden/data/misconceptions_lf.json`으로 저장(필드: `mis_id`·`statement`·`student_wrong_thinking`·`distractor_rule`·`op_code`·`standard_code`·`source`). **N건을 세어 적는다** — 15~25에 못 미쳐도 채우지 않는다.
  4. 특성화 테스트(5걸음 ②): `tests/golden/characterization/test_t2_misconception.py` — 옛 로더를 옛 자리에서 호출해 입력 10개(ID 10개) → 출력 10개 고정. 매칭 함수가 있으면 (틀린 답, 문항) 10쌍 → ID 고정. 결정성 100회.
  5. S17의 `errors.py` 임시 표가 `misconceptions_lf.json`과 일치하도록 **표를 파일에서 읽게** 바꾼다(주입기 동작은 그대로 — 테스트 초록 유지).
- **산출물:** `misconceptions_lf.json`(N건), 특성화 테스트, HARVEST 경계 줄, errors.py 소폭 수정.
- **완료 기준:** ①`misconceptions_lf.json`에 N건(숫자 명시)과 OP 코드 매핑 ②특성화 테스트 초록·결정성 ③`tests/golden` 초록(주입기 테스트 포함).
- **하지 말 것:** 오개념 DB 843건 전체 로딩·그래프 탐색·디스트랙터 생성 금지. 8건이 적다고 LLM으로 오개념을 "생성"하지 않는다.

### S27. T2 import — grade.py 확장: 틀린 답 → 오개념 ID 또는 null

- **목적:** 5걸음 ③④ — 로더(와 매칭)를 골든 안으로 가져오고, GP-5 판정 뒤에 플래그로 붙여 "틀린 답이면 오개념 ID 또는 null"을 기록한다.
- **선행 산출물:** S26.
- **할 일:**
  1. `src/backend/golden/eval/misconception.py`(또는 `grade.py` 안 함수 1개): `match_misconception(problem, student_text) -> str | None`. 로더는 import(의존 3개 이하) 또는 복사. 매칭은 ①옛 매칭 함수가 있으면 그것 ②없으면 주입기 규칙을 거꾸로 적용(각 오개념의 "틀린 답"을 미리 계산해 두고 학생 답과 sympy 동치 비교 — 50줄).
  2. 연결: `api.py` `answer()`에서 오답일 때 `GOLDEN_T2_MISCONCEPTION=1`이면 매칭을 부르고 `golden.turns`에 열을 더하지 않고 `golden.eval_log`(S22 표)에 `misconception_id`를 기록한다. 응답은 바꾸지 않는다.
  3. 검증: S17 `injection_table.csv`의 (문항, 오개념, 틀린 답) 전체를 매칭에 넣어 **100개 중 90개 이상**이 원래 오개념 ID로 돌아오는지(계획서 완료 기준). 표본 100개는 OP 코드별 고르게 뽑는다. 결과 표를 보고에.
  4. 사람 출처 오답(FINDINGS·S24 로그)에도 돌려 매칭된 비율을 **별도로** 적는다(주입기 답이 아닌 실제 답에서의 성능 — 낮아도 고치지 않고 숫자만).
  5. 플래그 0/1 양쪽 테스트 초록. HARVEST 줄.
- **산출물:** 매칭 함수, 연결, 검증 표 2개, 테스트.
- **완료 기준:** ①주입기 틀린 답 100개 중 90개 이상 매칭 ②사람 출처 오답 매칭률 숫자 ③플래그 양쪽 초록 ④스모크 초록.
- **하지 말 것:** 매칭 결과를 아직 튜터에 보내지 않는다(S28). 오개념 DB를 통째로 로드하지 않는다.

### S28. T2 적용 + AI 회귀 — 매칭된 오개념을 튜터 프롬프트에 주입

- **목적:** 매칭된 오개념(있을 때만)을 튜터 사용자 프롬프트에 한 줄로 넣어, 튜터가 그 오개념을 짚는 비율(오개념 검출률)을 P3 세션으로 잰다. 기준 60%.
- **선행 산출물:** S27, 보정 통과(S20).
- **할 일:**
  1. `tutor.py` `build_user_prompt`에 `GOLDEN_T2_MISCONCEPTION=1`이고 매칭이 있을 때만 "학생의 답은 '<오개념 한 줄 설명>' 유형의 실수일 수 있다. 정답은 말하지 말고 그 지점을 짚어 묻는다" 한 줄을 추가(시스템 프롬프트 `tutor_prompt.md`는 손대지 않는다 — 개정 1회 한도는 S23이 썼다).
  2. 오개념 검출률 계산을 `metrics.py`에 추가(P3 세션 중 튜터 발화가 주입된 오개념의 `statement`/`student_wrong_thinking` 핵심 낱말 또는 그 오개념용 힌트 문구를 포함하는 비율 — 낱말 목록은 `misconceptions_lf.json`에 `keywords` 필드로 둔다).
  3. Kiki 머신에서 720세션 전후(플래그 0 → 1). 표: 오개념 검출률(P3), M1~M5 유지 여부. 기준 60% 미만이면 **고치지 않고** 숫자만 적고 S30 판정으로 넘긴다(프롬프트 2차 개정 금지).
  4. 야간 스모크 120(P1·P2·P5·P7)은 P3이 없어 검출률을 못 잰다 — 야간에 P3 30세션을 더 돌릴지는 비용(계획서 §3-5)을 적고 Kiki 결정.
- **산출물:** 프롬프트 주입 한 줄, metrics 추가, 전후 보고서 2개, 검출률 표.
- **완료 기준:** ①오개념 검출률 숫자(기준 60% 대비) ②M1 0%·M3 1% 미만·M4·M5 0 유지 ③플래그 0에서 동작 불변(테스트).
- **하지 말 것:** 검출률을 올리려고 매칭 임계값을 느슨하게 하지 않는다. 시스템 프롬프트 수정 금지.

### S29. AI 학생 2차 — 로그 15건 (누적 30 · 실학생 대체)

- **목적:** T2가 켜진 튜터로 S24와 **같은 구성**(P2·P3·P4 × LF-01~LF-05 × 1회차)을 다시 돌려 15건을 정독한다. 같은 페르소나·같은 문항이므로 S24(T2 꺼짐)와 나란히 놓고 볼 수 있다.
- **선행 산출물:** S28 머지(서버를 `GOLDEN_T2_MISCONCEPTION=1`로 실행 — 런북에 명시). H2는 선행이 아니다.
- **할 일:** S24의 1~5와 같다. 날짜 꼬리표는 `<날짜>-s29`. S28 after(플래그 1) 실행의 `sessions.jsonl`을 써도 된다(조건은 S24 할 일 1과 같다). 보고 첫 줄 출처 표기도 같다. 보고에 추가: ①AI 학생 오답 중 매칭된 오개념 ID가 있는 비율 ②그 뒤 정답 전환율(S30이 쓴다) ③P3 세션에서 `injected_op`와 매칭된 오개념이 같은 계열인지(주입한 것을 알고 있으므로 셀 수 있다) ④S24 같은 칸과의 나란한 표.
- **산출물:** 로그 15건, 보고.
- **완료 기준:** ①AI 대체 누적 30건 ②페르소나별 표·루브릭·끊김 태깅 ③매칭률·전환율 숫자 ④S24와의 나란한 표.
- **하지 말 것:** S24와 같다. S24와 다른 페르소나·문항으로 바꾸지 않는다(비교가 깨진다).
- **막히면:** S24 "막히면"과 같다.

### S30. T2 판정 — FINDINGS 갱신 (관문 ③)

- **목적:** 실학생 오답 중 오개념 매칭률과 그 뒤 정답 전환율로 T2 효과를 판정한다.
- **선행 산출물:** S29, S25의 GATE.md.
- **할 일:** S25와 같은 절차. ①S29 15건에서 매칭률·전환율, S24(T2 꺼짐) 15건의 같은 숫자와 비교 ②효과 있음/없음 + 윌슨 하한 + "잠정" ③`FINDINGS.md`에 `## T2 판정 (S30)` 절 ④효과 없음이면 플래그 기본 0 유지·S28 한 줄 되돌림 ⑤GATE.md 누적(세션 30·실학생 수·완료율·슬롯 결과 2개).
- **완료 기준:** 판정 숫자·절·GATE.md 갱신. 판정 **go/no-go**는 S25와 같은 뜻.
- **하지 말 것:** S25와 같다.

## S31~S35: 슬롯 T3 — 숙련도 엔진 (7주차) + 게이트

### S31. T3 설계 — BKT 옛 모듈 특성화 테스트

- **목적:** FINDINGS에서 T3 항목(`F-06` 숙련도 체감 — 로그 근거가 있는지 먼저 확인)을 검토하고 BKT 옛 모듈을 함수 단위로 가져올 준비를 한다.
- **선행 산출물:** S30 판정 완료.
- **할 일:**
  1. FINDINGS 재확인: S24·S29 관찰 기록에 "숙련도 숫자가 체감과 다르다"·"다음 문제가 너무 쉽거나 어렵다"류 발화가 몇 건인지 센다. 0건이면 T3 기본 배정은 FINDINGS 밖이다 — 실학생 로그의 다음 항목으로 슬롯을 바꾸거나, Kiki 결정으로 "옛 자산 없이 가는 슬롯"(계획서 §4-2)으로 두고 S32~S34는 섀도 기록만 한다. 보고에 적는다.
  2. 경계(5걸음 ①): `whymath_backend/l2/bkt.py`의 `BktParameters` + `update_mastery(prior, correct, params)` 2개(망각 `apply_forgetting`·`BktModel.apply_forgetting`은 가져오지 않는다 — §6). 파라미터 이름 4개(초기 숙련도·학습률·추측률·실수율에 해당하는 필드)를 파일에서 읽어 적고 일차함수용 기본값을 정한다(제안값: 0.2·0.3·0.2·0.1 — 근거는 S24·S29 정답률로 S32가 보정 가능하되 이 세션은 값만 적는다).
  3. 특성화 테스트(②): `tests/golden/characterization/test_t3_bkt.py` — 옛 함수를 옛 자리에서 호출해 (prior, correct, params) 10쌍 → 출력 고정 · 결정성 100회 · `BktParameters` 비퇴화 검증이 거부하는 입력 1건.
- **산출물:** HARVEST 경계 줄, 특성화 테스트, 파라미터 4개 표.
- **완료 기준:** ①F 번호 근거 건수(0이어도 숫자) ②파라미터 4개 이름·기본값 ③특성화 10쌍 초록·결정성.
- **하지 말 것:** AKT·망각 곡선·적응형 문항 선택 금지. 옛 코드 수정 금지.

### S32. T3 import — src/backend/golden/mastery/bkt.py · GOLDEN_MASTERY_ENGINE=simple|bkt 섀도

- **목적:** BKT를 골든 안으로 가져와 simple 엔진과 **나란히 기록**한다. 화면은 simple만 보여 준다.
- **선행 산출물:** S31.
- **할 일:**
  1. `src/backend/golden/mastery/__init__.py`·`bkt.py`: import 또는 복사(의존 3개 초과 시). `update(prior, correct) -> float`.
  2. `store.py`: `golden.students`에 열을 더하지 않고 새 표 `golden.mastery_shadow(nickname, engine, mastery, updated_at, session_id, problem_id)`를 `create_all`에 추가. `api.py` `_graded`에서 `GOLDEN_MASTERY_ENGINE` 값과 무관하게 **두 엔진 모두** 계산해 섀도 표에 기록하고, 응답 `mastery`는 플래그가 `bkt`일 때만 bkt 값(기본 `simple`).
  3. e2e의 `mastery` 단언은 simple 기준 그대로(플래그 기본). bkt 플래그 픽스처 테스트 추가.
  4. Kiki 머신 서버 런북에 플래그 기본값(simple) 명시.
- **산출물:** `mastery/bkt.py`, 섀도 표, 플래그, 테스트, HARVEST 줄.
- **완료 기준:** ①두 엔진이 같은 세션에서 나란히 기록된다(테스트: 1세션 2행) ②플래그 기본 simple에서 e2e 불변 ③스모크 초록.
- **하지 말 것:** 화면에 bkt 값을 보여 주지 않는다. 숙련도 계약(+0.10/−0.05)을 바꾸지 않는다.

### S33. AI 학생 3차 — 로그 20건 (누적 50 · 실학생 대체)

- **목적:** 섀도 기록이 켜진 서버로 AI 학생 4종(P2·P3·P4·P5 검산 요청형) × LF-01~LF-05 × 1회차 = 20건. 두 엔진(simple·bkt)의 궤적이 같은 세션에서 쌓인다. P5를 더한 것은 정답이 이어지는 궤적이 하나는 있어야 두 엔진의 차이가 보이기 때문이다.
- **선행 산출물:** S32 머지. H2는 선행이 아니다.
- **할 일:** S24의 1~5와 같다(`--personas P2,P3,P4,P5` · 날짜 꼬리표 `<날짜>-s33`). 보고에 추가: ①세션별 simple·bkt 궤적 표(문제마다 두 값 · `golden.mastery_shadow`에서 `sim-*` 닉네임으로 뽑는다 — Kiki가 CSV로 전달) ②"학생이 결과 화면의 숫자에 대해 말한 것"은 AI 대체로는 얻을 수 없다 — "개방 시점 보완"으로 적는다.
- **산출물:** 로그 20건, 궤적 표.
- **완료 기준:** ①AI 대체 누적 50건 ②궤적 표 20세션 ③보고 첫 줄 "AI 대체" 출처.
- **하지 말 것:** S24와 같다. 궤적이 그럴듯해 보인다는 이유로 엔진을 평가하지 않는다(판정은 S34).
- **막히면:** S24 "막히면"과 같다. 20건을 못 채우면 있는 만큼(누적 N건)으로 진행하고 "축소"를 적는다 — 게이트 ①은 어차피 "미실시"이므로 AI 대체 누적 줄에만 그 수를 적는다.

### S34. T3 판정 — 섀도 비교·플래그 전환 결정 (관문 ④)

- **목적:** 50세션의 두 궤적을 그림으로 비교하고 bkt로 전환할지 결정한다. 전환하면 e2e의 `mastery` 단언을 갱신한다.
- **선행 산출물:** S33, GATE.md.
- **할 일:**
  1. `golden/mastery_shadow` 전체(실학생 50 + 시뮬레이션)를 뽑아 세션별 두 궤적 그림(`golden/reports_phase1/S34/trajectories.png` + 수치 CSV)을 만든다. 비교 기준(제안값): ⓐ정답률과의 일치 — 각 엔진의 마지막 숙련도와 그 학생의 정답률 상관 ⓑ학생 발화와의 일치 — S33 인용 중 "숫자가 이상하다"류가 어느 엔진 값에서 나왔는지 ⓒ시뮬레이션 P8(게이밍형)에서 bkt가 simple보다 덜 오염되는지.
  2. 판정: 전환 / 유지. 전환이면 `GOLDEN_MASTERY_ENGINE` 기본값을 `bkt`로 바꾸고 e2e `mastery` 단언(`> 0.0`·범위)을 bkt 값 기준으로 갱신한다. 유지면 섀도 기록은 남기고 기본값 simple.
  3. `FINDINGS.md`에 `## T3 판정 (S34)` 절. GATE.md에 슬롯 결과 3개·누적 50·완료율.
- **산출물:** 궤적 그림·CSV, 판정 절, (전환 시) 플래그·e2e 갱신 PR.
- **완료 기준:** ①50세션 궤적 그림 ②판정과 근거 3개 ③e2e 초록(전환했으면 갱신 후).
- **하지 말 것:** 두 엔진을 섞거나 세 번째 엔진을 넣지 않는다. 망각 곡선 추가 금지.

### S35. 게이트 판정 — golden/FINDINGS_v2.md · 2단계 계획 초안 (관문 ⑤)

- **목적:** 12/26에 계획서 §7 여섯 줄을 판정하고, 2단계의 1순위 문제를 숫자와 함께 적는다. 3주간 import 안 된 옛 모듈 추가분을 `golden/LEGACY_MANIFEST.txt`에 더한다(개정판 §2).
- **선행 산출물:** S34, GATE.md, CALIBRATION.md, 야간 스모크 기록(Kiki 머신 `sim_report.json` 날짜별), HARVEST.md.
- **할 일:**
  1. 진실 트랙 3줄·회귀 트랙 3줄을 각각 예/아니오와 숫자로 `golden/reports_phase1/GATE.md`에 확정한다(⑤는 Kiki 머신 보고서 파일 수로: S20 통과 이후 날짜 중 치명 실패 0인 날 ÷ 전체 날).
  2. 판정 규칙 적용(공유 계약 게이트 절): 2단계 진행 / S21~S35 반복 / 2단계 + 첫 주 시뮬레이터 수정.
  3. `golden/FINDINGS_v2.md`: 실학생 50건 기준으로 끊김 4종·단계별·문항별 표를 **실학생 출처 하나로** 다시 집계(대체 피험자와 섞지 않는다), 1위 문제를 "N건 중 M건"으로, 2·3위, 슬롯 3개 결과 요약, 2단계 후보(슬롯에서 "효과 없음"이었던 것의 다른 접근 · LATER 상위).
  4. 미참조 옛 모듈 추가분: 골든 패스 S15 방식(grimp로 `golden` 상류 ∖ 전체)을 다시 돌려 S15 목록과의 차이(새로 import된 모듈 = T1·T2·T3 자산 · S20A 복사로 **빠진** 모듈 · 여전히 미참조인 모듈)를 HARVEST.md에 적고, 여전히 미참조인 옛 모듈 전부를 `golden/LEGACY_MANIFEST.txt`(모듈 이름 한 줄씩 · 머리에 측정 기준 커밋 해시·날짜 · S15 722건 + 추가분)에 쓴다. `/legacy` 물리 이동은 Kiki 결정(S15와 같다).
  5. 2단계 계획 초안(`golden/NEXT_PHASE2.md`): 계획서 §2 표 형식 그대로, 세션 번호 S36부터, FINDINGS_v2 순서대로. 새 계획서 형식을 만들지 않는다.
  6. 1단계 회고 `golden/RETRO_phase1.md`: 세션별 완료 기준 충족 표, 범위 밖으로 나가려다 멈춘 순간 모음(각 세션 보고 ⑤), LATER 항목 수, 시뮬레이터가 "재미있어서" 들인 시간 추정.
- **산출물:** GATE.md 확정, FINDINGS_v2.md, HARVEST 미참조 목록, `golden/LEGACY_MANIFEST.txt`, NEXT_PHASE2.md, RETRO_phase1.md.
- **완료 기준:** ①여섯 줄 전부 예/아니오 + 숫자 ②FINDINGS_v2의 1위가 "N건 중 M건" ③NEXT_PHASE2 첫 세션이 FINDINGS_v2 1위를 가리킨다 ⑤LEGACY_MANIFEST.txt에 측정 기준 해시와 모듈 수 ④판정: **go**(2단계) / **반복**(S21~S35) / **go+수정주**(회귀 트랙만 아니오).
- **하지 말 것:** 게이트 숫자를 대체 피험자 로그로 채우지 않는다(실학생만). 옛 모듈 삭제 금지. 2단계 계획에 §6 항목을 로그 근거 없이 넣지 않는다.
