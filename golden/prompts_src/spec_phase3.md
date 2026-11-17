# WhyMath 3단계 「세 번째 단원 + 추상화」 — 작업 지시서 (AI 실행용 · 4주)

작업 번호를 받은 AI는 이 문서의 공통 규칙·용어·공유 계약과 해당 번호의 지시만 읽고 작업한다. 지시에 없는 값은 추정하지 않고 "미확인"으로 보고한다. 원본 계획서는 `plan_phase3_contract_4weeks.docx`(Kiki 보관 원본(저장소 미포함 — office·PDF 문서는 `.gitignore`와 `scripts/ops/check_source_document_binaries.py`가 커밋을 막는다 · 저장소 안 정본은 지시서))(2026-11-15 · Kiki)이고, 골든 패스(S1~S15) → 1단계(S16~S35) → 2단계(S36~S55)의 후속이다. 세션 번호는 S56부터 S75까지. **시작 조건: 2단계 S54·S55 게이트에서 질문 1(아키텍처)과 질문 2(콘텐츠)가 모두 "예"**다. 아니면 이 묶음을 열지 않는다. 2027-02-01 시작, 설 연휴(2/6~2/9)로 달력상 3/5 종료. 세션 수는 줄이지 않는다.

이 단계의 산출물은 네 번째 단원이 아니라 **Subject Contract** — 단원 하나가 골든 패스에 들어오기 위해 채워야 하는 파일 다섯 개와 그 스키마 — 그리고 그것을 읽는 `core/`다. 게이트는 하나다: **네 번째 단원을 추가하는 PR에서 `.py`와 `.dart`의 변경이 0줄.**

## 공통 규칙과 보고 형식

**공통 규칙**

1. (스크립트가 "읽을 범위" 표준 문장으로 바꾼다)
2. (스크립트가 "선행 작업 확인" 표준 문장으로 바꾼다)
3. **golden/ 바깥은 읽기 전용:** 새 코드는 `src/backend/golden/`(하위 `core/`·`units/`·`content/`·`sim/`), `golden/`(문서), `src/mobile/lib/golden/`, `tests/golden/`에만 쓴다. 옛 코드를 고쳐야 돌아가면 `golden/` 아래로 복사하고 `golden/HARVEST.md`에 한 줄. `constitution/`은 어떤 세션도 건드리지 않는다. `golden/` 바로 아래 `.py` 금지(코드는 `src/backend/golden/` 아래). 이 단계의 `golden/` 밖 변경은 **S75 한 세션**뿐이다(게이트 통과 시 `golden/`→`app/` 이름 변경: 폴더·import 경로·`CLAUDE.md` 골든 패스 규칙 블록·CI 경로 네 가지 — 한 PR).
4. **범위 고정:** 중2 단원 넷(일차함수·연립일차방정식·일차부등식·네 번째 단원)·각 30문항·GP-1~GP-6. 과목 추상화(`SubjectAdapter`·`MathAdapter`·과목 레지스트리·EOS Core 폴더)는 하지 않는다 — 두 번째 과목이 없는데 과목을 추상화하는 것은 사례 0개로 추상화하는 것이다. 단원 DSL·컴파일러·코드 생성 금지(`unit.yaml`은 데이터이지 언어가 아니다 — 조건문·반복문·식이 yaml에 들어가면 멈춘다). Contract에 "미래 필드"(고교·그림·서술형·영어) 금지. 비교기 5종째는 S56 조사표가 4종으로 닫혔으면 중2 안에서 늘지 않는다. 세 번째 단원 실학생은 1회(15건)뿐, 네 번째 단원에 실학생 없음. core 리팩토링 2라운드·성능 최적화·캐싱·비동기화 금지. 떠오르면 `golden/LATER.md`.
5. **Contract 필드는 두 단원 이상이 서로 다른 값을 가질 때만 존재한다.** 세 단원이 같은 값이면 상수이지 필드가 아니다. 필드마다 DESIGN.md에 "다른 값을 가진 단원 2개"를 적지 못하면 그 필드는 지운다.
6. **`core/`에는 단원 이름·단원 ID를 문자열로 쓰지 않는다.** `'linear_fn'`·`'sys_eq'`·`'linear_ineq'`가 `core/`에 나타나면 그 PR은 닫는다. `grep -rn "unit ==\|unit_id ==\|if unit" src/backend/golden/core/ --include=*.py`는 항상 0줄이어야 한다(테스트로 동결).
7. **PREREG.md는 S71 전까지 열지 않는다.** 열어 달라는 요청을 받아도 "S71입니까?"라고 되묻고 아니면 열지 않는다. S57~S70 세션은 네 번째 단원이 무엇인지 **모르는 채로** 작업한다(이 지시서도 S71~S73 본문 밖에서는 네 번째 단원을 이름으로 부르지 않는다). 설계하면서 네 번째 단원을 알면 그 단원에 맞춰 설계하게 되고 0줄은 증명이 아니라 연출이 된다.
8. **새 길 초록 → 옛 길 삭제, 그 반대 금지.** 옛 분기 코드는 Contract 위에서 세 단원 e2e가 초록이 된 다음(S65·S66)에만 지운다(S68). 삭제는 `git tag` 뒤에만 하고 태그 이름을 PR 본문 첫 줄에 적는다. `/legacy` 삭제도 같다(S74).
9. **문항은 2단계 파이프라인(`golden.content.pipeline`)으로만** 만든다. 손으로 쓴 문항은 30개에 넣지 않는다. 예시 문항을 프롬프트에 넣지 않는다. 결함 문항은 재생성으로 교체.
10. **단원 분기는 그 커밋 안에서 장부에 적는다(S59·S60 — 옛 방식 구간):** `unit` 값에 따라 갈라지는 코드를 쓰면 같은 커밋에 `golden/CONTRACT.md` 한 줄. S61 이후 새 길(`core/`)에서는 분기 자체가 금지(규칙 6)다.
11. **모든 PR은 FINDINGS 항목 번호를 인용한다:** 2단계 체계(`F-Q1`·`F-Q2` · `golden/FINDINGS_v2.md`)에 S56이 `F-Q3`(네 번째 단원 추가가 0줄인가)를 더한다. 인용할 항목이 없으면 그 PR은 지금 할 일이 아니다.
12. **완료 기준은 tests/golden 초록(단원 수만큼 parametrize) + AI 스모크 초록:** `cd src/backend && python -m pytest ../../tests/golden`을 exit code로. 야간 스모크는 단원 수 × 120(S65 이후 360). 빨간불이면 PR을 만들지 않는다 — 예외 없음(S41 같은 "빨강이 목표" 세션은 이 단계에 없다).
13. **LLM 호출 규칙:** 옛 코드의 `build_cloud_provider()`+`Router.route`(클라우드) 또는 `OllamaProvider`(로컬) 경유. 키 하드코딩 금지. 테스트·CI는 `GOLDEN_FAKE_LLM=1`.
14. **미성년자 데이터·저작권:** 1·2단계 규칙 그대로(닉네임만 · 시드 로컬만 · 학생 로그를 생성 프롬프트에 넣지 않음 · `license=WHYMATH_GENERATED` · `_provenance.json` 사이드카).
15. **검증은 CI와 같은 명령으로:** `src/backend`에서 `python -m ruff check golden ../../tests/golden`, `python -m black --check --line-length 100 golden ../../tests/golden`, `python -m mypy --strict golden`, `lint-imports`. 로컬 CI 미러는 커밋 뒤에 돌리고 도는 동안 트리를 바꾸지 않는다.
16. **모르는 값은 추정 금지:** 이 문서의 "사전 실측(2026-11-15 · main `a9cff6ec`)"은 1·2단계 산출물이 **없는 시점**의 값이다. 3단계 세션은 2단계가 남긴 것(`content/`·`CONTRACT.md` B1~B(마지막)·`problems_sys_eq.json`·단원별 숙련도 표·`VALIDATION_FINAL.md`)을 먼저 실측하고 다르면 보고에 적는다.
17. **하네스·커밋·PR:** 첫 행위 `python3 scripts/harness/backlog.py start <태스크 ID>`(S56이 `add`로 받아 `golden/STATE.md`「하네스 태스크 ID」에 "3단계: <번호>"). 커밋 메시지 `S<번호>: <한 줄> (F-xx)`. main 머지는 Kiki.
18. **한국어:** 코드 주석·문서·보고는 한국어(식별자는 영어).
19. **종료 보고 10줄:** ①완료 기준 충족 여부 ②tests/golden 결과(단원 수·N개) ③HARVEST.md 추가 줄 ④LATER.md 추가 줄 ⑤범위 밖으로 나가려다 멈춘 순간 ⑥AI 스모크(단원별 M1~M5) ⑦FINDINGS F-xx 전진 여부 ⑧CONTRACT.md에 적은 분기 ID(S59·S60) ⑨**오늘 `core/`에 단원 이름이 들어간 적: 없음 / 있음 → 제거** ⑩**오늘 삭제한 줄 수와 태그 이름**(삭제가 있었으면).

**완료 보고 형식**

```
작업 번호: S63
결과: 완료 | 일부 완료 | 중단
인용 FINDINGS: F-xx
만든 것: 파일·테이블·화면 이름 (경로 포함)
완료 기준 확인: 항목별 통과/실패와 근거 (실행한 명령 또는 본 화면)
core/ 단원 이름 혼입: 없음 | 있음 → 제거
삭제: 없음 | N줄 · 태그 <이름>
미확인·가정한 것: 없으면 "없음"
다음 작업이 알아야 할 것: 없으면 "없음"
```

**용어**

| 용어 | 뜻 |
| --- | --- |
| 골든 패스 | GP-1 세션 → GP-2 문제 → GP-3 답변 → GP-4 튜터 되묻기(최대 3턴) → GP-5 판정 → GP-6 숙련도. 서버 `golden.api:app`, 앱 `lib/main_golden.dart`, 코드 `src/backend/golden/` |
| Subject Contract | "단원 하나 = 폴더 하나, 파일 다섯 개, 코드 0개"라는 약속. `units/<unit_id>/`에 `unit.yaml`·`problems.json`·`misconceptions.json`·`error_rules.yaml`·`glossary.md`. 정식 문서는 `core/CONTRACT.md`(S70) |
| core/ | 단원을 모르는 코드. `contract.py`(UnitSpec+검증)·`loader.py`·`grade.py`(비교기 4종)·`tutor.py`(용어 슬롯)·`mastery.py`(파라미터 주입)·`sim/errors.py`(규칙 테이블). `'unit =='` 비교가 한 줄도 없다 |
| 옛 방식 / 새 길 | 옛 방식 = 2단계처럼 분기를 장부에 적으며 단원을 넣는 것(S59). 새 길 = `core/` + `units/`로 단원을 폴더로 넣는 것(S62~S66). 새 길이 초록이 된 뒤에만 옛 길을 지운다(S68) |
| 세 번 규칙 | 세 번째 사례가 있어야 무엇이 공통인지 보인다. 둘만 보고 추상화하면 추측이다 |
| 사전 등록(PREREG) | S56에서 네 번째 단원을 `golden/PREREG.md`에 적고 커밋 해시를 봉인, S71까지 열지 않는다. 임상시험의 사전 등록과 같은 이유 — 설계가 네 번째 단원에 맞춰지는 것을 막는다 |
| 3/3 · 2/3 · 1/3 | 장부의 분기 줄마다 "세 단원 중 몇 개가 서로 다른 값인가". 3/3·2/3만 Contract 필드 또는 단원 폴더 파일이 되고 1/3은 상수로 core에 박는다(값과 단원을 DESIGN.md에 기록) |
| answer_type 4종 | `number`(일차함수) · `pair`(연립방정식) · `range`(일차부등식) · `expression`(S73). S56 조사표가 중2 텍스트 문항에서 닫는다. 늘리는 것은 core 변경 |
| 특성화 90케이스 | S63에서 옛 `grade.py`에 세 단원 × 30문항의 정답과 대표 오답 1개씩을 넣어 출력을 `tests/golden/characterization/grade_90.json`에 고정. core 비교기는 90개를 전부 같게 내야 한다. 다르면 core가 틀린 게 아니라 "옛 코드와 다르다"는 것 — Kiki가 판정해 파일에 적는다 |
| engine 플래그 | `GOLDEN_ENGINE=core|legacy` 환경변수 하나. `api.py`가 요청마다 읽는다. 기본값 S65까지 legacy, S66부터 core. S68 삭제 PR에서 플래그도 지운다 |
| 코어 갭 / 단원 갭 | S73 드라이런에서 0줄이 아닐 때 바뀐 줄의 분류. 코어 갭 = core가 이 단원을 받으려면 바뀌어야 했던 줄(비교기·파서·프롬프트 가정). 단원 갭 = unit.yaml에 필드가 없어서 코드로 쓴 줄(필드를 추가하면 다음엔 0줄) |
| /legacy 세 질문 | 모듈마다 ①지난 12주 golden/이 한 번이라도 import했는가 ②LATER.md에 "4·5단계에 필요"로 적혀 있는가 ③데이터(문항·오개념·그래프·패턴)인가 — 하나라도 "예"면 삭제하지 않는다 |
| 2단계 산출물 | S36~S55가 남긴 것 — `content/`(스펙·생성·검증·파이프라인), `golden/CONTRACT.md`(B1~B(마지막) · S53 분류), `problems_sys_eq.json`, 단원별 숙련도 표, `tutor_glossary.yaml`, `mastery_params.yaml`, `VALIDATION_FINAL.md`, `FINDINGS_v2.md`. 3단계는 이것들을 그대로 쓴다 |
| 사전 실측 | 2026-11-15 main `a9cff6ec` 기준으로 확인한 값. 1·2단계 산출물은 그 시점에 없었으므로 "가정"으로 표기 |

**공유 계약**

아래 모양은 S56~S75가 전부 같이 쓴다. 바꿔야 한다고 판단하면 바꾸지 말고 보고에 "계약 변경 제안"으로 적고 멈춘다. 앞선 세 묶음의 공유 계약은 그대로 유효하며 여기서는 3단계가 더하는 것만 적는다. **네 번째 단원은 이 절 어디에도 이름으로 나오지 않는다**(S71~S73 본문에만).

*계획서 전제와 저장소 사실이 다른 곳(사전 실측 2026-11-15 · main `a9cff6ec`)*

| 계획서가 전제한 것 | 저장소 사실 | 이 지시서의 처리 |
| --- | --- | --- |
| 오개념 DB에서 일차부등식분 추출 | `misconceptions.json` 843건 중 **중2 일차부등식 계열은 3건**(`M0564` 음수를 곱하거나 나눌 때 방향 유지 `[9수02-11]` · `M0028` 부등호 방향 안 바꿈 `[9수02-12]` · `M0565` 일차부등식 `[9수02-12]`). 나머지 부등식 항목 18건은 고교(절댓값·이차·로그·절대부등식). 선행 일차방정식 3건(`M0021`~`M0023`)이 부등식 풀이에서 그대로 난다 | S56이 **N건을 세어 적는다**. 고교 항목을 중2로 끌어오지 않는다 |
| 세 번째 단원 문항 자산 | 문제은행 39개 중 `problem_bank_linear_inequality_system_v0` 600건은 **연립일차부등식의 경계값(수 하나)** 문항(`answer_format` 실수·자연수 · 범위 답 아님). 중2 일차부등식 **범위 답** 문항 자산은 없다 — 전부 파이프라인 생성 | 600건은 V3 유사도 검사의 대조군으로만 쓴다(재현 방지) |
| 중2 소단원 조사표 | `data/corpus/achievement_criteria_v1/achievement_criteria.json`의 중학교 1~3학년군 트리(수와 연산 4 · 문자와 식 6 · 함수 4 · 기하 9 · 확률과 통계 4 = 소단원 27개)가 조사표의 뼈대다. 학년(중2) 구분은 트리에 없어 S56이 교육과정 원문(또는 `standards_v1`)으로 중2분을 고른다 | S56 조사표는 이 트리에서 시작한다. 기하·그래프 단원은 "그림 필요 — 범위 밖"으로 표기 |
| Flutter 앱의 단원 하드코딩 | `src/mobile/lib/golden/`에 `golden_api.dart`·`golden_app.dart`·`golden_state.dart`·`nickname_screen.dart`·`problem_screen.dart`·`result_screen.dart`(골든 패스 S6·S7). 2단계 S43·S46이 `unit`·`answer_kind`를 다루며 단원 문자열을 넣었을 수 있다 | S69가 `GET /golden/units`에서 목록을 받게 바꾸고 dart의 단원 문자열을 0으로 만든다(`grep -rn "linear_fn\|sys_eq\|linear_ineq" src/mobile/lib/golden` 0건 — 테스트) |
| 2단계 산출물이 전부 있다 | 사전 실측 시점에는 `content/`·`CONTRACT.md` 본문·`problems_sys_eq.json`·단원별 숙련도 표가 **없다**(2단계가 만든다) | S56 첫 단계에서 2단계 산출물을 실측해 없는 것이 있으면 멈춘다(시작 조건 미충족) |
| 옛 비교기 | 골든 `grade.py`는 2단계 S42 후 `number`·`expression`·`pair` 셋(가정). `range`는 없다. SymPy에는 `solveset`·`Interval`·`Union`이 있어 범위 동치 비교에 쓴다 | S59가 옛 방식으로 `range` 비교기를 `grade.py`에 더하고(분기 장부), S63이 core 비교기 4종으로 옮긴다 |

*실학생 대체 결정(Kiki 2026-11-17 · 기록 `golden/reports_phase1/H2/보고.md` 0절 · 1·2단계 지시서 같은 이름의 블록과 한 벌) — 이 블록이 아래 다른 절의 "실학생" 문구보다 우선한다*

- **결정:** "실 학생 없이 ai로 진행" · "여기서 발생할 수 있는 문제들은 개방 시점에 보완" · "3단계 지시서도 같은 방식으로 고쳐줘". 그러므로 H4(실학생 섭외)는 **중단**이고 S67은 **AI 학생 정독 세션**이다. 실학생 확인은 개방 시점에 한다 — 4단계도 같은 결정으로 AI 코호트 운영 리허설이 됐으므로, 실제 학생을 처음 만나는 자리는 **4단계 뒤의 실학생 파일럿**이다.
- **S67의 모양(1단계 S24·2단계 S44와 같다):** Kiki 머신에서 러너(`golden.sim.run`)를 실제 LLM(튜터 OpenRouter · 학생 로컬 Ollama — 시드 반출 금지·학생 LLM 로컬 전용 규칙 그대로)으로 돌리고, `sessions.jsonl`에서 **P2·P3·P4 × 일차부등식(서버가 내는 순서의 처음 5문항) × 1회차 = 15건**만 골라 턴마다 손으로 읽는다. 닉네임은 `sim-<페르소나>-<회차>`이고 `stu-*`는 쓰지 않는다. 단원 지정 옵션은 러너 `--help`로 확인한다(옵션 이름을 추정하지 않는다).
- **이름 붙이기:** 결과는 출처를 **"AI 대체"**로 적고 "실학생"이라 부르지 않는다. 판정에는 "잠정 · AI 대체"를 붙인다.
- **게이트 줄 ⑥(세 번째 단원 실학생 15건 완료율 70%):** GATE.md에 **"미실시(Kiki 결정 2026-11-17 · AI 대체)"**로 적고 AI 완료율은 별도 줄에 적는다. 판정 셈에서는 계획서 원문 규칙("0명이면 ⑥을 아니오로 둔다 · 이 단계의 게이트는 아키텍처라 정지하지 않는다")대로 **"아니오" 하나로 센다** — AI 숫자로 "예"를 만들지 않는다.
- **AI 대체로는 말할 수 없는 것:** 학생이 부등식 답을 실제로 어떻게 치는가(`range` 입력 표기 분포) · 난이도별 학생 정답률 · 이탈률·만족도. "측정 불가(개방 시점 보완)"로 적는다. AI 학생의 표기 분포는 로컬 모델과 시드 말투가 정하는 값이라 참고값으로만 적고 core 전처리 보강의 **근거로 쓰지 않는다**.
- **개방 시점에 보완할 목록(1·2단계 목록에 더한다):** ①세 번째 단원 실학생 15건·완료율 ②`range` 입력 표기 분포 ③core 엔진 위에서 실학생이 도는지. S75가 1~3단계의 목록 전부를 4단계 초안(`NEXT_PHASE4.md`)에 옮겨 적는다.

*2단계가 남겼다고 가정하는 골든 코드(S56에서 실측)*

| 파일 | 3단계가 쓰는 것 |
| --- | --- |
| `src/backend/golden/api.py`·`grade.py`·`tutor.py`·`store.py`·`problems.py` | 옛 길 본체. `unit` 분기가 흩어져 있는 다섯 파일(B1~B7) — S59가 세 번째 단원을 같은 방식으로 더하고, S68이 분기를 지운다 |
| `src/backend/golden/content/` | 스펙 로더·생성기·검증기·파이프라인(`python -m golden.content.pipeline --spec …`). S57·S72가 그대로 쓴다 |
| `src/backend/golden/sim/` | 주입기(단원별 규칙 표 두 개 — B5)·학생 모델·러너(`--unit`)·메트릭. S64가 규칙 표를 `units/*/error_rules.yaml`로 옮긴다 |
| `src/backend/golden/eval/`·`mastery/` | T2 오개념 매칭(`misconceptions_path(unit)` — B4)·T3 BKT(`bkt_params(unit)` — B6) |
| `golden/CONTRACT.md` | 2단계 장부(B1~B(마지막) · S53 분류 · 코드 줄 수 · 세 번째 단원 추정 줄 수). S59·S60이 이어 쓰고 S70에 `core/HISTORY.md`로 옮긴다 |
| `golden/data/problems_linear_fn.json`·`problems_sys_eq.json`·`misconceptions_lf.json`·`misconceptions_sys_eq.json`·`tutor_glossary.yaml`·`mastery_params.yaml` | 단원별 데이터·설정 — S62가 `units/<unit_id>/` 5파일로 옮긴다(옛 경로는 S68까지 공존) |
| `tests/golden/` | e2e(2단원 parametrize · mixed)·특성화·스모크. S59가 3단원, S73에서 4단원 자동 parametrize가 돼야 한다 |

*폴더 배치(계획서 §3-1 · 코드는 `src/backend/golden/` 아래)*

```
src/backend/golden/
  core/                    ← S62~S64 (단원을 모르는 코드 · 'unit ==' 0줄)
    contract.py  loader.py  grade.py  tutor.py  mastery.py  sim/errors.py
    ANSWER_TYPES.md(S56 조사표)  DESIGN.md(S61 · 2쪽 이내)  CONTRACT.md(S70 정식)  HISTORY.md(S70 · 옛 장부)
  units/                   ← S62 (단원 = 폴더 · 코드 0)
    linear_fn/   unit.yaml  problems.json  misconceptions.json  error_rules.yaml  glossary.md
    sys_eq/      (같은 5파일)
    linear_ineq/ (같은 5파일)
    <네 번째>/   ← S73 · .py 없음
  api.py                   ← core만 호출(S66 이후)   content/ · sim/ (그대로)
golden/
  PREREG.md                ← S56 봉인 · S71 개봉
  content/spec_linear_ineq.yaml  candidates·verify_report·review_queue(세 번째 단원)
  reports_phase3/<번호>/보고.md
tests/golden/characterization/grade_90.json · test_core_no_unit_strings.py · test_units_autodiscover.py
```

*`unit.yaml` 스키마 초안(계획서 §3-2 · S61이 3/3·2/3 표시를 보고 확정 — 필드는 **빠질 수는 있어도 늘어나면 안 된다**, 늘어나려면 장부 줄 번호가 있어야)*

| 필드 | 뜻 | 장부 출처 |
| --- | --- | --- |
| `unit_id` / `name_ko` / `grade` | 폴더명과 같다 · 이름 · 학년. 문항 ID 접두는 `unit.yaml`의 `problem_prefix`가 아니라 `problems.json`의 `id`가 정한다(제안값) | — |
| `answer_type` | `number \| pair \| range \| expression` — S56 조사표로 닫힌 집합 | B2 |
| `max_turns` | GP-4 되묻기 상한(기본 3). 세 단원이 같으면 S61에서 상수로 내림 | 2단계 B8 후보 |
| `bkt` | `p_init`·`p_learn`·`p_guess`·`p_slip` | B6 |
| `mastery_key` | `[student, unit]`. 세 단원이 같으면 상수로 내림 | B7 |
| (파일 4개) | `problems.json`(B1) · `misconceptions.json`(B4) · `error_rules.yaml`(B5) · `glossary.md`(B3) — 이름이 고정이라 필드가 없다 | B1·B3·B4·B5 |

*`UnitSpec`·로더(계획서 §3-3)*

- `core/contract.py`: `ANSWER_TYPES = ("number", "pair", "range", "expression")` · `@dataclass(frozen=True) class UnitSpec(unit_id, name_ko, grade, answer_type, max_turns, bkt, root)` · `validate() -> list[str]`(필수 파일 5개 존재 · `answer_type ∈ ANSWER_TYPES` · bkt 네 값 0~1 · 빈 목록이면 통과).
- `core/loader.py`: `load_all(units_dir) -> dict[str, UnitSpec]` — `units/` 아래 폴더를 전부 읽는다. **폴더가 늘면 단원이 는다, 코드는 모른다.** e2e는 `load_all()` 결과로 parametrize된다(S62 테스트 · S73 자동 발견의 근거).

*비교기 4종(`core/grade.py` · 계획서 §3-4 · 학생 입력 전처리(한글 "엑스"·전각·공백·접두·꼬리·마지막 `=` 규칙)는 넷이 공유하는 함수 하나)*

| `answer_type` | 학생 입력 예 | 비교 방법 |
| --- | --- | --- |
| `number` | `2`, `-3/4`, `0.5` | sympy `nsimplify` 후 동치(허용 오차 1e-9) |
| `pair` | `(2, 3)`, `x=2, y=3` | 두 값 각각 number 비교 · 순서 x, y 고정 |
| `range` | `x > 3`, `x ≥ -1`, `x<=2` | sympy `solveset`(또는 `Interval`)로 구간 객체를 만들어 동치 비교 · 부등호 방향·경계 포함 여부까지 · `≥`·`>=`·`=>` 표기 통일 |
| `expression` | `3x + 2`, `2x^2 - x` | sympy `expand` 후 차 == 0 · 정리 안 된 답(동치이나 전개·정리 전)은 "맞지만 정리 필요"로 분기(S73에서 처음 쓰인다 — 그때까지 구현만 두고 사용 단원 0) |

*전환·삭제 절차(계획서 §4)*

- 플래그 `GOLDEN_ENGINE=core|legacy`: `api.py`가 요청마다 읽는다. 기본 legacy(S65) → core(S66). 전환 기준(S66): 2,160세션(720 × 3)을 두 엔진으로 돌려 **M1 차이 0 · M3 차이 0.5%p 이내 · M2 차이 0.2턴 이내.** 넘으면 전환하지 않고 차이 난 세션을 연다.
- 특성화 90케이스: `grade_90.json`(단원·문항·입력·옛 출력·core 출력·판정자·판정). 다른 케이스는 Kiki가 "옛 코드 오류"/"core 오류"를 판정하기 전에 core를 고치지 않는다. 옛 코드 오류가 10개를 넘으면 2단계 AI 대체 로그(S44·S49·S52)에 미친 영향을 FINDINGS에 적는다.
- 옛 분기 삭제(S68): `grep -rn "unit ==\|unit_id ==\|if unit" src/backend/golden/ --include=*.py`로 잡히는 줄 + 그 줄이 속한 함수 중 core에 같은 역할이 있는 것 전부. 삭제 PR 하나, 제목에 삭제 줄 수, 머지 조건 = e2e 3단원 초록 + 스모크 360 초록, 삭제 후 grep 0줄을 CONTRACT.md 하단에. 플래그도 같은 PR에서 삭제(legacy 값을 넣으면 에러).
- `/legacy` 판정(S74): 세 질문(용어 표). `git tag legacy-archive-2027-03` → 삭제 PR → HARVEST.md에 모듈마다 "삭제: 12주 미참조, LATER 미기재". 2주 안에 복구 3건을 넘으면 기준부터 고친다.
- `golden/`→`app/`(S75): 게이트 통과 시에만. 폴더·import·`CLAUDE.md` 블록·CI 경로 — 한 PR, e2e 초록. 안 바꾸면 이유를 RETRO.md에.

*단원 추가 절차(코드 0줄 · 계획서 §3-5 · S73이 이대로 한다)*

1. `units/<unit_id>/` 폴더를 만든다 2. 2단계 파이프라인으로 `problems.json` 30개 3. 오개념 DB 해당분 → `misconceptions.json`, 틀린 답 규칙 → `error_rules.yaml` 4. `glossary.md`(10줄 이내) 5. `unit.yaml`(answer_type은 4종 중 하나 · bkt는 이웃 단원 값) 6. `pytest tests/golden` — e2e가 폴더를 발견해 자동 parametrize. 초록이면 끝. **여섯 걸음에 `.py`도 `.dart`도 없다. 있으면 Contract가 덜 된 것이다.**

*HTTP·환경변수(3단계 추가분)*

| 항목 | 값 |
| --- | --- |
| `GET /golden/units` | S69 신설(네 번째 엔드포인트 — 계획서가 요구). `[{"unit_id","name_ko","answer_type"}]` — `load_all()` 그대로. 앱이 이 목록으로 단원 선택 화면을 그린다 |
| `GOLDEN_ENGINE` | `core` / `legacy`(S65~S68) |
| `GOLDEN_UNITS_DIR` | `units/` 경로 덮어쓰기(테스트용 · 기본 `src/backend/golden/units`) |

*게이트 일곱 줄(S75 · 계획서 §7)*

- ☐ 네 번째 단원 PR의 `.py`/`.dart` 변경 0줄(코어 갭·단원 갭 모두 0) — **본체** ☐ e2e 4단원 자동 parametrize 전부 초록 · AI 회귀 4단원 M1~M5 유지 ☐ `unit.yaml` 모든 필드에 "다른 값을 가진 단원 2개"가 DESIGN.md에(불필요 필드 0) ☐ `grep "unit =="` core/ 0줄 · 플래그 없음 · 삭제 PR 머지 ☐ /legacy 판정 완료(태그·HARVEST N·M·K) ☐ 세 번째 단원 실학생 15건 완료율 70% 이상(core 위에서) — **실학생 대체 결정 뒤: "미실시"로 적고 판정 셈에서는 "아니오" 하나** ☐ 4단계 초안에 첫 세션 FINDINGS 인용 항목과 파일럿 학생 모집 계획.
- 판정: 첫 줄 "예" + 나머지 "아니오" 둘 이하 → 4단계(파일럿). 첫 줄 "아니오" → S61~S73 반복(코어 갭 20줄 이하면 "조건부"로 4단계 첫 주에 메움).

## S56~S60: 세 번째 단원을 옛 방식으로 (12주차)

사전 등록·조사(S56) → 문항(S57) → 검토·AI 회귀(S58) → 옛 방식 연결(S59) → 장부 완성(S60)은 직선이다. H4(세 번째 단원 실학생 섭외)는 2026-11-17 결정으로 중단이다(공유 계약 「실학생 대체 결정」).

### S56. 사전 등록·조사 — PREREG.md 봉인 · 답 유형 조사표 · 세 번째 단원 스펙 (코드 없음)

- **목적:** 네 번째 단원을 봉인하고, 중2 텍스트 문항의 답 유형 집합을 닫고, 세 번째 단원(일차부등식) 스펙과 오개념을 만든다.
- **선행 산출물:** 2단계 전부(S54·S55 "예").
- **할 일:**
  1. **2단계 산출물 실측**(공유 계약 표) → 보고 첫 절. 없으면 멈춤.
  2. **하네스 등재:** `backlog.py add`(제안 제목 "GOLD-P3 3단계 세 번째 단원 + Subject Contract · S56~S75") → `start` → STATE.md "3단계: <번호>".
  3. **PREREG.md:** `golden/PREREG.md`에 계획서 §5-2 1번의 세 줄(네 번째 단원 이름·답 유형 / "S71까지 코드·스펙·문항 어디에도 등장하지 않는다" / "S73 PR의 .py/.dart 변경 줄 수가 게이트")을 쓰고 커밋한다. 커밋 해시를 파일 안에 적고 한 번 더 커밋한다. **이 세션 보고와 이후 세션은 이 파일 내용을 인용하지 않는다**(규칙 7).
  4. **답 유형 조사표 `src/backend/golden/core/ANSWER_TYPES.md`**(`core/` 폴더는 이 문서 하나로 시작 — `.py` 없음): 2022 개정 중2 수학 소단원 전부(성취기준 트리에서 중2분 선별 · 원문 확인)를 나열하고 각각 "정답이 무엇인 형태인가"를 `number / pair / range / expression / 기타`로 적는다. 기타는 무엇인지(예: 도형 — 그림 필요 · 이번 범위 밖). 결론 줄: "중2 텍스트 문항의 답 유형은 N종으로 닫힌다." 5종이 필요하다고 결론나면 그것도 결과다(억지로 4종에 맞추지 않는다).
  5. **세 번째 단원 스펙 `golden/content/spec_linear_ineq.yaml`:** 2단계 §3-1 형식. `unit: linear_ineq`(접두 `LI-`), `answer_type: range`, 해의 경계는 정수, 부등호 네 종류(`<`·`>`·`≤`·`≥`)가 고르게(제안값: 각 7~8개), 난이도 8/14/8, `forbidden` 2단계 것을 그대로.
  6. **오개념 추출 `golden/data/misconceptions_linear_ineq.json`:** 중2 일차부등식 계열(사전 실측 3건) + 선행 일차방정식 3건. 각 항목에 틀린 답 규칙 한 줄(예: "음수로 나눌 때 부등호 방향 유지"). **N건을 센다.** 고교 항목을 끌어오지 않는다.
  7. `golden/FINDINGS_v2.md`에 `F-Q3`(네 번째 단원 추가가 0줄인가) 등재.
- **산출물:** PREREG.md(봉인 해시), ANSWER_TYPES.md, spec_linear_ineq.yaml, misconceptions_linear_ineq.json(N건), F-Q3, STATE.md 태스크 ID.
- **완료 기준:** ①PREREG.md가 커밋되어 해시가 파일 안에 있다 ②조사표에 중2 소단원마다 답 유형이 적혀 있고 결론 줄에 N종 ③스펙에 `answer_type: range`·부등호 분포 ④오개념 N건 ⑤2단계 산출물 실측 "없음" 0건.
- **하지 말 것:** 문항을 쓰지 않는다. 코드를 쓰지 않는다. PREREG 내용을 보고에 옮기지 않는다. 조사표를 4종에 맞추려고 단원을 빼지 않는다.

### H4. 세 번째 단원 실학생 3명 섭외 (Kiki)

- **상태(2026-11-17): 중단.** Kiki 결정으로 이 작업은 하지 않는다. S67은 H4를 선행으로 요구하지 않는다. 아래는 개방 시점에 섭외를 다시 열 때를 위한 원래 지시다(섭외 문구: `golden/reports_phase1/H2/섭외_키트.md`).
- **목적:** S67 한 번(15건). 이 단계의 유일한 실학생 세션.
- **할 일:** 1·2단계와 같은 절차(1·2단계 참여 학생 우선 · 20분 · 보상 · 동의 · 가명). S67 전 3명.
- **완료 기준:** S67 전 3명 확정. 0명이면 S67을 열지 않고 게이트 줄 ⑥을 "아니오"로 둔다(1단계처럼 정지하지는 않는다 — 이 단계의 게이트는 아키텍처다).

### S57. 세 번째 단원 문항 — 2단계 파이프라인 한 명령

- **목적:** `python -m golden.content.pipeline --spec golden/content/spec_linear_ineq.yaml`로 생성 90 + 4단 검증을 한 번에 돌린다. 코드 변경은 V2(`range` 수학 검증)가 없으면 그것뿐이다.
- **선행 산출물:** S56 스펙·오개념.
- **할 일:** ①`verify.py`의 V2가 `answer_type=range`를 모르면 `v2_range`(sympy `solveset`으로 부등식을 풀어 `answer` 구간과 동치·경계 정수·부등호 종류 라벨) 추가 — **이것은 content/의 변경이지 골든 패스 분기가 아니다**(장부 대상 아님 · 보고에 명시) ②실제 실행(Kiki 머신 또는 키 환경) → `candidates.jsonl`·`verify_report.json`·`review_queue.md` ③수율·자동 통과율·불일치율·토큰 기록 ④가짜 모드 테스트(`range` 후보 결정론 생성·V2 range 긍정/부정).
- **산출물:** `v2_range`(필요 시), 세 번째 단원 후보·보고서·검토 큐.
- **완료 기준:** ①한 명령으로 생성+검증이 돌았다 ②수율·불일치율 숫자 ③`tests/golden` 초록.
- **하지 말 것:** 프롬프트를 손보지 않는다(2단계 그대로). 탈락을 살리지 않는다.

### S58. 검토·AI 회귀 — 30문항 확정 · 720세션

- **목적:** Kiki 불일치 검토(30분) → 30개 확정(`golden/data/problems_linear_ineq.json` + 사이드카) → 1단계 시뮬레이터로 720세션 → 결함 문항 재생성.
- **선행 산출물:** S57.
- **할 일:** ①2단계 S39 절차로 30개 확정(난이도 8/14/8 · sympy 재검산 · 스키마 테스트 `LI-01`~`LI-30` · `answer_kind=range` · `answer`는 `"x > 3"` 꼴 문자열) ②주입기에 일차부등식 규칙(`misconceptions_linear_ineq.json`의 규칙 줄 — 방향 유지·이항 부호 등 · `range` 틀린 답 생성)을 **옛 방식**으로 더한다(단원별 규칙 표 세 번째 — 장부 B5 줄에 "3단원째" 추가) ③`GOLDEN_PROBLEMS_PATH`류 임시 경로로 720세션(Kiki 머신 · 실제 LLM) — `grade.py`가 아직 `range`를 모르면 M3는 "S59 전"으로 표기 ④결함 문항 0~3개 → 같은 세션에서 파이프라인 재생성·교체(2단계 S48 경로) ⑤검토 시간·수율·비용 기록.
- **산출물:** 30문항 + 사이드카, 주입기 규칙 표, 720 보고서, 재생성 기록.
- **완료 기준:** ①30개 확정·스키마 테스트 초록 ②720세션 M1·M2·M4·M5(M3 "S59 전") ③결함 재생성 성공률 ④Kiki 검토 30분 이내 기록.
- **하지 말 것:** 손으로 문항 수정 금지. `grade.py` 수정 금지(S59).

### S59. 옛 방식 연결 — range 비교기 · 용어 블록 · 오개념 연결 · e2e 3단원

- **목적:** 2단계 S41~S43을 **한 세션에** 한다. 분기마다 CONTRACT.md 한 줄. 세 번째 단원을 넣는 데 든 코드 줄 수를 재어 2단계 S53의 추정치(50줄 이하)와 비교한다 — 이 단계의 첫 번째 숫자.
- **선행 산출물:** S58 30문항, 2단계 `CONTRACT.md`(S53 추정치).
- **할 일:** ①시작 커밋 해시 기록 ②`GOLDEN_UNITS`에 `linear_ineq` 추가 · 로더 경로(B1 — 설정이면 줄 수 0에 가깝다) ③`grade.py`에 `range` 비교기(옛 방식 — `answer_kind == "range"` 분기 · B2 줄 "3단원째") ④`tutor_glossary.yaml`에 일차부등식 블록(B3 — 설정) ⑤`misconceptions_path(unit)`에 세 번째 파일(B4 — 데이터) ⑥`mastery_params.yaml`에 세 번째 값(B6 — 설정) ⑦e2e 3단원 parametrize 초록(`mixed`도 3단원 순환) ⑧앱 입력 안내(`range`: "x > 3 처럼 입력")·단원 선택에 세 번째 단원(하드코딩이면 그대로 하드코딩 — S69가 지운다) ⑨`git diff --stat <시작>..HEAD -- '*.py' '*.dart'` 줄 수를 CONTRACT.md에 "S59 세 번째 단원 코드 줄 수"로 적고 2단계 추정치와 나란히. **2배(100줄)를 넘으면 리스크 표 1행** — S60을 한 세션 더 써서 2단계 분기를 다시 센다(보고에 권고) ⑩스모크 120 × 3단원 가짜 초록.
- **산출물:** 옛 방식 연결 전체, CONTRACT.md 줄들(B1~B6 3단원째 + 신규 B), 코드 줄 수 비교.
- **완료 기준:** ①e2e 3단원 초록 ②분기마다 장부 줄 ③코드 줄 수와 추정치 비교 ④`tests/golden`·`flutter test`·스모크 초록.
- **하지 말 것:** 이 세션에서 분기를 "정리"하지 않는다. core/를 만들지 않는다(S62).

### S60. 장부 완성 — CONTRACT.md 3/3·2/3·1/3 표시

- **목적:** 모든 분기 줄에 "세 단원 중 몇 개가 서로 다른 값인가"를 적는다. 3/3·2/3인 줄이 Contract 필드 후보다.
- **선행 산출물:** S59 CONTRACT.md.
- **할 일:** ①분기 줄마다 세 단원의 실제 값을 코드·설정·데이터에서 읽어 표에 적는다(값 3개·같음/다름) ②`3/3`·`2/3`·`1/3` 라벨 ③2단계 S53 분류(데이터/설정/코드)를 세 단원 기준으로 재확인 ④S59 줄 수가 추정의 2배를 넘었으면 이 세션에서 2단계 분기를 다시 센다(계획서 리스크 1 — 설계를 서두르지 않는다) ⑤장부 요약 표(필드 후보 목록 · 상수 후보 목록과 그 1/3 단원·값).
- **완료 기준:** ①모든 분기 줄에 세 값과 3/3·2/3·1/3 ②필드 후보·상수 후보 목록 ③코드 변경 0.
- **하지 말 것:** 설계하지 않는다(S61). 분기를 고치지 않는다.

## S61~S66: 새 길 — core/와 units/ (13주차)

설계(S61)는 가장 느리게 해야 하는 세션이다(설 연휴 전에 서두르지 않는다). 로더·스키마(S62) 뒤에 비교기(S63)와 튜터·숙련도·주입기(S64)는 서로 독립이라 **동시에** 간다. 새 길 초록(S65) → 전환·전체 회귀(S66). 옛 길은 이 동안 그대로 돈다.

### S61. Contract 설계 — core/DESIGN.md (2쪽 이내 · 코드 없음)

- **목적:** 장부에서 3/3·2/3 줄만 뽑아 `unit.yaml` 필드와 단원 폴더 파일을 확정한다. 1/3은 상수로 core에 박되 단원·값을 기록한다.
- **선행 산출물:** S60 장부, 공유 계약 스키마 초안.
- **할 일(계획서 §5-3):** ①장부 줄을 3/3·2/3·1/3로 나눈다 ②3/3·2/3만 필드/파일 · 1/3은 상수(어느 단원·어떤 값인지 DESIGN.md에 — 네 번째 단원이 그 값에서 다르면 S73 코어 갭으로 잡힌다) ③필드마다 "다른 값을 가진 단원: X, Y" 한 줄 — 못 쓰면 지운다 ④§3-1 폴더 구조·§3-2 스키마를 장부 결과에 맞게 고쳐 DESIGN.md에(초안보다 필드가 늘면 늘어난 필드마다 장부 줄 번호) ⑤옛 코드에서 core로 옮길 함수 목록: 파일 경로 + 함수 이름 + 특성화 케이스 수(90케이스가 어느 함수에 몇 개씩) ⑥마지막에 "이 설계가 틀렸다면 S73에서 어떻게 드러나는가" 세 줄.
- **산출물:** `src/backend/golden/core/DESIGN.md`(2쪽 이내).
- **완료 기준:** ①필드마다 "다른 값을 가진 단원 2개" ②1/3 줄이 상수로 처리되고 단원·값 기록 ③옮길 함수 목록과 케이스 배분 ④2쪽 이내.
- **하지 말 것:** "나중을 위해" 필드를 넣지 않는다(두 번째 과목·고교·그림용 자리 금지). 네 번째 단원을 떠올리지 않는다(PREREG 봉인). 코드를 쓰지 않는다.

### S62. 로더·스키마 — core/contract.py · core/loader.py · units/*/unit.yaml 3개

- **목적:** 세 단원의 `unit.yaml`이 로드되고 스키마 검증을 통과한다. 로직 변경 없음(옛 길은 그대로).
- **선행 산출물:** S61 DESIGN.md.
- **할 일:** ①`core/__init__.py`·`contract.py`(`ANSWER_TYPES`·`UnitSpec`·`validate`)·`loader.py`(`load_all`) ②`units/linear_fn/`·`sys_eq/`·`linear_ineq/` 각 5파일 — 데이터·설정은 옛 경로(`golden/data/*.json`·`tutor_glossary.yaml`·`mastery_params.yaml`)에서 **복사**(옛 경로는 S68까지 공존 · 두 벌이 같음을 테스트로 동결) ③`tests/golden/test_core_contract.py`(세 단원 로드·validate 빈 목록·필수 파일 하나 지우면 위반 1건·`answer_type` 오타 위반·bkt 범위 밖 위반·**폴더를 하나 더 만들면 `load_all` 결과가 4개** — 자동 발견) ④`tests/golden/test_core_no_unit_strings.py`: `core/` 아래 `.py`에 단원 ID 문자열·`unit ==` 0건(주입: `'linear_fn'` 한 줄 넣으면 RED).
- **산출물:** core 2파일, units 15파일, 테스트 2파일.
- **완료 기준:** ①세 단원 로드·검증 통과 ②자동 발견 테스트 ③단원 문자열 0건 테스트 RED→GREEN ④옛 길 e2e 불변.
- **하지 말 것:** 옛 `problems.py`·`grade.py`를 고치지 않는다. `api.py`를 아직 core에 연결하지 않는다(S65).

### S63. 비교기 — core/grade.py 4종 · 특성화 90케이스

- **목적:** 옛 `grade.py`의 3단원 × 30문항 출력을 90케이스로 고정하고, core 비교기 4종이 전부 같게 내게 한다.
- **선행 산출물:** S62(UnitSpec·`answer_type`).
- **할 일:** ①`tests/golden/characterization/grade_90.json` — 단원 3 × 문항 30 × (정답 1 + 대표 오답 1)을 **옛** `grade.is_correct`에 넣어 출력 고정(입력은 2단계·S58 로그의 실제 학생 문자열 우선, 없으면 정답 문자열 표기 변형) ②`core/grade.py`: 공유 전처리 1개 + `number`·`pair`·`range`·`expression` 비교기 + `is_correct(spec: UnitSpec, problem, text)`(단원 ID를 보지 않고 `spec.answer_type`만 본다) ③90케이스 전부 일치 — 다른 케이스는 `grade_90.json`에 `core_output`·`verdict: ""`로 남기고 **고치지 않는다**. Kiki가 "옛 코드 오류"/"core 오류"를 적으면 그때 반영 ④`expression` 비교기는 S73 전까지 사용 단원 0이지만 단위 테스트(전개 전/후·정리 필요 분기)는 쓴다.
- **산출물:** `core/grade.py`, `grade_90.json`, 단위 테스트.
- **완료 기준:** ①90케이스 중 불일치 0(또는 불일치 목록 + Kiki 판정 대기) ②`core/`에 단원 문자열 0 ③옛 길 불변.
- **하지 말 것:** 불일치를 core 쪽에서 "맞춰" 없애지 않는다(판정 전).

### S64. 튜터·숙련도·주입기 — core/tutor.py · core/mastery.py · core/sim/errors.py + units/*/error_rules.yaml

- **목적:** 세 단원의 if문이 core에 하나도 없게 튜터 용어 슬롯·BKT 파라미터 주입·주입기 규칙 테이블을 만든다.
- **선행 산출물:** S62.
- **할 일:** ①`core/tutor.py`: 프롬프트 템플릿에 `{glossary}` 슬롯 하나 — `units/<id>/glossary.md`를 읽는다 · 시스템 프롬프트 `golden/tutor_prompt.md`는 그대로 ②`core/mastery.py`: BKT 계산은 1단계 `mastery/bkt.py`를 import, 파라미터는 `UnitSpec.bkt` ③`core/sim/errors.py`: `inject(spec, problem, misconception_id)`가 `units/<id>/error_rules.yaml`의 규칙 테이블을 읽는다 — 규칙 언어는 **데이터**여야 한다(연산 이름·대상 필드·치환 표 정도 · 파이썬 식·조건문 금지). 옛 `sim/errors.py`의 단원별 딕셔너리 3개를 yaml 3개로 옮기고 같은 (문항, 오개념) → 같은 틀린 답을 테스트로 대조 ④`grep -rn "unit ==\|unit_id ==\|if unit" src/backend/golden/core/` 0줄.
- **산출물:** core 3파일, `error_rules.yaml` 3개, 대조 테스트.
- **완료 기준:** ①세 단원 주입 결과가 옛 주입기와 전건 동일 ②core 단원 문자열·분기 0 ③옛 길 불변.
- **하지 말 것:** yaml에 식·조건문을 넣지 않는다. 규칙이 데이터로 표현되지 않으면 그 사실을 LATER.md에 적고 그 규칙은 "표현 불가"로 보고한다(억지로 코드를 yaml로 숨기지 않는다).

### S65. 새 길 초록 — GOLDEN_ENGINE=core|legacy · e2e 3단원 × 2엔진 (관문 ①)

- **목적:** `api.py`가 플래그로 core를 호출한다. 두 엔진 모두 e2e 초록. AI 스모크 360을 core로 돌려 M1~M5 기준.
- **선행 산출물:** S63·S64.
- **할 일:** ①`api.py`: 요청마다 `GOLDEN_ENGINE`을 읽어 `core`면 `loader.load_all()`·`core.grade`·`core.tutor`·`core.mastery`·`core.sim` 경로, `legacy`면 옛 경로(기본 legacy) ②e2e를 `(unit × engine)`으로 parametrize — 3 × 2 전부 초록 ③야간 워크플로를 360(120 × 3단원 · core 엔진 · 가짜)으로 ④Kiki 머신 실제 스모크 360(core) M1~M5 ⑤러너·주입기가 core 경로를 쓰는지(`--engine core`).
- **산출물:** 플래그, e2e 6케이스, 워크플로 360, 스모크 보고.
- **완료 기준:** ①두 엔진 e2e 초록 ②core 스모크 360 M1 0%·M3 1% 미만·M4·M5 0 ③판정 **go**.
- **하지 말 것:** 기본값을 core로 바꾸지 않는다(S66). 옛 길을 지우지 않는다.

### S66. 전환·전체 회귀 — 기본값 engine=core · 2,160세션 (관문 ②)

- **목적:** 2,160세션(720 × 3)을 두 엔진으로 돌려 차이가 잡음 수준이면 기본값을 core로 바꾼다.
- **선행 산출물:** S65.
- **할 일:** ①Kiki 머신 `SIM_FULL=1` 2,160 × 2엔진(실제 LLM · 같은 시드 순서) ②차이: M1 차이 0 · M3 0.5%p 이내 · M2 0.2턴 이내 — 넘으면 전환하지 않고 차이 난 세션을 열어 원인(core 오류/옛 오류/LLM 흔들림)을 적고 **S66 반복** ③통과 시 기본값 `core` + 앱 런북에 명시 ④`FINDINGS_v2.md`에 `## 엔진 전환 (S66)` 절.
- **완료 기준:** ①차이 표 ②판정 **go**(전환) / **no-go**(반복) ③전환 시 기본값 core에서 e2e·스모크 초록.
- **하지 말 것:** 기준을 넘는데 "거의 같다"로 전환하지 않는다.

## S67~S70: AI 학생 정독·삭제·정식화 (14주차)

S67(AI 학생 정독 — core 위 · 실학생 대체)과 S69(Flutter 단원 목록)는 독립이라 **동시에** 간다. S68(옛 분기 삭제)은 S67 뒤(AI 학생 15건이 core 위에서 돈 것을 정독으로 확인한 뒤). S70이 Contract를 정식화한다.

### S67. AI 학생 정독 — 페르소나 3종 × 일차부등식 5문제 = 로그 15건 (core 위 · 실학생 대체)

- **목적:** core 엔진 위에서 세 번째 단원을 AI 학생 3종(P2·P3·P4)이 푼 기록 15건을 턴마다 손으로 읽는다. 원래는 이 단계의 유일한 실학생 세션이었다(공유 계약 「실학생 대체 결정」). 옛 분기를 지우기(S68) 전에 core 위의 대화가 멀쩡한지 사람 눈높이로 한 번 본다.
- **선행 산출물:** S66(기본값 core). H4는 선행이 아니다.
- **할 일:**
  1. (Kiki) Kiki 머신에서 러너를 실제 LLM으로 돌린다(단원 `linear_ineq` · `--personas P2,P3,P4` · 엔진 기본값 core · 가짜 모드 아님 · 날짜 꼬리표 `<날짜>-s67`). S66 전환 뒤 실제 LLM으로 돈 실행이 있으면 그 `sessions.jsonl`을 써도 된다(같은 코드·기본값 core일 때만 — 어느 쪽인지 보고에 적는다).
  2. (Kiki → AI 세션) P2·P3·P4 × 서버가 내는 순서의 처음 5문항 × 1회차 행 15건을 골라 전달한다(gitignore · 커밋 금지). 내용을 보고 고르지 않는다.
  3. (AI 세션) 조건 확인: 건수 15 · 페르소나 3종 × 문항 5개 · `http_status` 2xx · 가짜 모드 아님 · **core 엔진으로 돈 것**(실행 환경에 `GOLDEN_ENGINE=legacy`가 없었음을 Kiki가 알려 준다). 안 맞으면 판정하지 않고 보고한다.
  4. (AI 세션) `golden/reports_phase3/S67/보고.md`. 첫 줄 "출처: AI 대체(P2·P3·P4) · 실학생 0명 · Kiki 결정 2026-11-17". 내용: 페르소나별 문제 표, 되묻기 루브릭 C1~C5 손 판정(튜터 턴마다 인용), 끊김 4종, AI 완료율(게이트 ⑥의 완료율이 아니다), 결함 문항 후보(2단계 블록의 ⓐⓑⓒ — 5문항 직접 풀이 대조 포함), **`range` 판정 점검**(AI 학생이 낸 부등식 답 표기마다 core 비교기의 판정이 맞았는지 — 표기·판정·맞음/틀림 표).
  5. `range` 입력 표기 분포(학생이 `x>3`·`x > 3`·`3보다 큼` 중 무엇을 치는가)는 **"측정 불가(개방 시점 보완)"**로 적는다. AI 학생의 표기 분포는 참고값으로만 적고 "core 전처리 보강 근거"로 쓰지 않는다. 단 4의 점검에서 **판정이 틀린** 표기가 나오면 그것은 결함이므로 근거 로그 줄과 함께 적는다(고치지는 않는다).
- **산출물:** 로그 15건(Kiki 머신·gitignore), 보고.
- **완료 기준:** ①15건(조건 확인 통과) ②루브릭 손 판정과 AI 완료율 ③`range` 판정 점검 표 ④입력 표기 분포 "측정 불가" 표기 ⑤보고 첫 줄 "AI 대체" 출처.
- **하지 말 것:** 세션 중 코드·프롬프트·문항 수정 금지. 가짜 모드 결과로 판정하지 않는다. 결과를 "실학생"이라 부르지 않는다. 시드 발화를 보고·채팅에 붙이지 않는다. 로그 커밋 금지.
- **막히면:** Kiki 머신에서 실제 LLM 실행을 못 하면 판정하지 않고 멈춘다(가짜 모드로 대신하지 않는다 — 이때 S68도 열지 않는다). 조건에 맞는 행이 15건보다 적으면 있는 만큼 판정하고 "축소: N건".

### S68. 옛 분기 삭제 — 삭제 PR · 플래그 제거 (관문 ③)

- **목적:** 옛 길을 지운다. 태그 → grep 목록 → 삭제 → grep 0줄.
- **선행 산출물:** S67(core 위 AI 학생 정독 완료 — 판정이 틀린 `range` 표기 0건 또는 Kiki가 삭제 진행을 결정), S66.
- **할 일(계획서 §5-4):** ①`git tag golden-branches-before-delete`(태그 이름을 PR 본문 첫 줄에) ②`grep -rn "unit ==\|unit_id ==\|if unit" src/backend/golden/ --include=*.py` 결과를 PR 본문에 — 삭제 목록 ③잡힌 줄과 core에 같은 역할이 있는 함수 전체(옛 `grade.py` 비교기·옛 프롬프트 분기·옛 mastery 분기·`sim/errors.py` 단원별 if문·옛 `problems.py` 경로 표·`golden/data/*.json`의 단원 데이터 사본(`units/`가 정본)) 삭제 ④`GOLDEN_ENGINE` 플래그와 읽는 코드 삭제 — `legacy` 값을 넣으면 에러 ⑤`pytest tests/golden`(3단원) 초록 · 스모크 360 초록 — 둘 다 PR에 첨부 ⑥grep 재실행 0줄을 PR 본문 끝과 CONTRACT.md 하단에 ⑦삭제 줄 수를 PR 제목에.
- **산출물:** 삭제 PR 1개(제목에 줄 수), 태그, CONTRACT.md 하단 grep 0줄.
- **완료 기준:** ①grep 0줄 ②플래그 없음 ③e2e·스모크 초록 ④판정 **go**.
- **하지 말 것:** 지우다가 "이 함수는 core에 없네"를 발견하면 **삭제를 멈추고** LATER.md에 적는다 — 오늘 core에 급히 넣지 않는다(다음 세션에 특성화 테스트부터). 태그 없이 지우지 않는다.

### S69. Flutter 단원 목록 — GET /golden/units · dart 단원 하드코딩 제거

- **목적:** 앱이 단원 목록을 API에서 받는다. `unit.yaml` 추가만으로 앱에 단원이 나타난다.
- **선행 산출물:** S66(core 기본값) — S67과 동시 진행 가능.
- **할 일:** ①`api.py`에 `GET /golden/units`(`load_all()` 그대로 · 네 번째 엔드포인트 — 계획서 §2 S69가 요구) ②`lib/golden/`에서 단원 ID·이름·`answer_kind` 안내 문구의 하드코딩을 제거하고 목록·`answer_type`별 안내를 서버 값으로(안내 문구 자체는 `unit.yaml`에 넣지 않는다 — `answer_type` 4종별 문구는 앱 상수 4개 · 단원 수와 무관) ③`tests/golden/test_api_units.py`(목록 3개 · `units/`에 폴더 추가 시 4개 — `GOLDEN_UNITS_DIR` 픽스처) ④`tests/golden/test_dart_no_unit_strings.py`: `src/mobile/lib/golden/*.dart`에 단원 ID 문자열 0건(주입 RED) ⑤`flutter analyze`·`flutter test` 초록.
- **산출물:** 엔드포인트, dart 변경, 테스트 2파일.
- **완료 기준:** ①앱 단원 선택이 API 목록으로 그려진다(에뮬레이터 캡처) ②dart 단원 문자열 0건 ③`units/` 폴더 추가 시 목록 4개(테스트).
- **하지 말 것:** 앱에 단원별 화면을 만들지 않는다. 디자인 다듬기 금지.

### S70. Contract 정식화 — core/CONTRACT.md · HISTORY.md

- **목적:** 필드 의미·파일 5개·단원 추가 절차(§3-5)가 적힌 정식 문서. 옛 장부는 `core/HISTORY.md`로 이동.
- **선행 산출물:** S68·S69.
- **할 일:** ①`src/backend/golden/core/CONTRACT.md`: `unit.yaml` 필드 표(의미·허용값·"다른 값을 가진 단원 2개" · DESIGN.md 인용)·파일 5개 스키마(`problems.json` 필드 · `misconceptions.json` 필드 · `error_rules.yaml` 규칙 언어(데이터만) · `glossary.md` 10줄 이내)·단원 추가 절차 여섯 걸음·"코드 변경이 필요한 경우"(비교기 5종째 · 전처리 보강) 목록 ②`golden/CONTRACT.md`(장부)를 `core/HISTORY.md`로 `git mv`(내용 불변 · 머리에 "2단계 장부 · S70 이동") ③`golden/prompts_src`·README 등이 옛 경로를 가리키면 그 줄만 갱신(지시문 묶음 본문은 건드리지 않는다 — 역사 문서).
- **완료 기준:** ①CONTRACT.md에 필드 표·파일 5개·절차 ②HISTORY.md 이동 ③DESIGN.md와 모순 0(필드 목록 동일 — 테스트로 대조).
- **하지 말 것:** 필드를 더하지 않는다. 네 번째 단원을 언급하지 않는다.

## S71~S75: 드라이런과 게이트 (15주차)

S71(개봉)→S72(문항)→S73(드라이런)은 직선이다. S74(/legacy 판정)는 S70만 기다리므로 S71~S73과 **동시에** 간다(다른 브랜치·다른 파일). S75가 게이트·이름 변경·회고.

### S71. 네 번째 단원 개봉 — PREREG.md 개봉 · 스펙 (코드 없음)

- **목적:** 봉인 해시가 S56 커밋과 같은지 확인하고 네 번째 단원(**중2 식의 계산 — 단항식·다항식의 계산 · 답 유형 `expression`**)의 스펙을 쓴다. 이 본문부터 네 번째 단원을 이름으로 부른다.
- **선행 산출물:** S70, `golden/PREREG.md`.
- **할 일:** ①`git log -- golden/PREREG.md`로 봉인 커밋 해시가 파일 안의 해시와 같은지, S56 이후 변경 0건인지 확인해 보고 첫 줄에 ②`golden/content/spec_poly_calc.yaml`(2단계 형식 · `unit: poly_calc` · 접두 `PC-` · `answer_type: expression` · 난이도 8/14/8 · `forbidden` 그대로 · 상황문 없는 "정리하시오" 정형구 허용) ③오개념 추출 `misconceptions_poly_calc.json` — 사전 실측(2026-11-15) 중2 식의 계산 계열 6건(`M0561` 지수법칙 `[9수02-08]` · `M0016` 차수 무시 결합 · `M0017` 뒷항 분배 누락 · `M0018` `-(x-3)=-x-3` · `M0562` 다항식 덧셈·뺄셈 · `M0563` 분배 일부 누락 `[9수02-09/10]`) + 규칙 한 줄씩 · N건 ④`units/poly_calc/`는 **아직 만들지 않는다**(S73).
- **완료 기준:** ①봉인 해시 일치 ②스펙·오개념 ③코드 변경 0(`git diff --stat -- '*.py' '*.dart'` 0).
- **하지 말 것:** core를 "미리" 손보지 않는다 — `expression` 비교기가 부족해 보여도 S73에서 코어 갭으로 세게 둔다.

### S72. 네 번째 단원 문항 — 파이프라인 · Kiki 검토 30분

- **목적:** 30문항. 파이프라인만. 검토 30분 이내.
- **선행 산출물:** S71 스펙.
- **할 일:** S57·S58의 문항 절차(생성 90 → V1~V4 → 불일치 검토 → 30개 확정 → sympy 재검산(`expression`: `expand` 후 차 0 · 정리된 형태인지) → `golden/data/problems_poly_calc.json` + 사이드카). V2가 `expression`을 모르면 `v2_expression` 추가(content/ 변경 — 장부 대상 아님). 결함 문항 재생성 1회.
- **완료 기준:** ①30개(`PC-01`~`PC-30`) ②검토 시간 ③코드 변경은 `content/`뿐(`git diff --stat -- 'src/backend/golden/core/*' 'src/backend/golden/api.py' '*.dart'` 0).
- **하지 말 것:** AI 회귀를 돌리지 않는다(S73). 손으로 문항 금지.

### S73. 드라이런 — 네 번째 단원 폴더 5파일 · e2e 4단원 · AI 720 · diff 0줄 (관문 ④ — 게이트 본체)

- **목적:** 네 번째 단원을 §3-5 여섯 걸음으로 추가한다. 오늘의 숫자는 하나: **이 PR의 `.py`/`.dart` 변경 줄 수.**
- **선행 산출물:** S72 30문항·오개념, S70 CONTRACT.
- **할 일(계획서 §5-5):** ①브랜치를 새로 딴다. 시작 커밋 해시를 적는다 ②`units/poly_calc/`에 5파일: `problems.json`(S72)·`misconceptions.json`(S71)·`error_rules.yaml`(규칙 언어로 — 분배 누락·부호·차수 결합)·`glossary.md`(10줄 이내 · 동류항·분배법칙·지수법칙)·`unit.yaml`(`answer_type: expression` · bkt는 `linear_fn` 값 복사) ③`pytest tests/golden` — 4단원 자동 parametrize 확인. 안 되면 **첫 번째 코어 갭** ④AI 회귀 720(poly_calc · Kiki 머신) M1~M5 ⑤앱을 띄워 단원 목록에 식의 계산이 보이는지 — 안 보이면 **두 번째 코어 갭** ⑥`git diff --stat <시작 해시> -- '*.py' '*.dart'` 결과를 `golden/reports_phase3/GATE.md`에 그대로 ⑦0줄이 아니면 바뀐 줄마다 분류: 코어 갭(core가 이 단원을 받으려면 바뀌어야 했던 줄 — 비교기·파서·프롬프트 가정) / 단원 갭(unit.yaml에 필드가 없어서 코드로 쓴 줄 — Contract에 필드 추가 후 재실행하면 다음엔 0줄 · **두 번째 실행의 0줄도 인정**) / 그 외(단원 무관 버그 — 계산에서 제외하되 적는다).
- **산출물:** `units/poly_calc/` 5파일, 4단원 e2e 결과, 720 보고서, GATE.md(diff 원문·분류 표).
- **완료 기준:** ①GATE.md에 `git diff --stat` 원문 ②0줄이면 통과, 아니면 줄마다 분류와 줄 수 ③e2e 4단원 결과(초록/빨강 그대로) ④판정: **통과**(0줄) / **조건부**(코어 갭 ≤20줄) / **미통과**(초과).
- **하지 말 것:** 0줄을 만들기 위해 코드 변경을 `unit.yaml`의 "스크립트 필드"로 숨기지 않는다(yaml 안에 python 식이 들어가면 그것은 코드다). 숫자가 0이 아니어도 그 숫자가 결과다. 실학생을 붙이지 않는다.

### S74. /legacy 판정 — git tag legacy-archive-2027-03 · 삭제 PR · HARVEST.md 최종

- **목적:** `/legacy`의 모듈을 세 질문으로 판정해 삭제분은 태그에 남기고 지운다. HARVEST.md에 가져온 N·버린 M·삭제 K.
- **선행 산출물:** S70(HARVEST.md 현행), 골든 패스 S15·1단계 S35·2단계 S55의 미참조 목록 — S71~S73과 동시 진행 가능(다른 브랜치).
- **할 일(계획서 §4-3):** ①`/legacy` 모듈 목록 + 지난 12주 golden/ import 여부(grimp 상류 ∖ 전체 · S35·S55 목록 대조) ②모듈마다 세 질문(import됐나 → 삭제 안 함 / LATER에 4·5단계 필요로 적혔나 → 둔다(세션 번호) / 데이터인가 → 둔다) ③`git tag legacy-archive-2027-03` → 삭제 PR(제목에 모듈 수·줄 수 · 본문 첫 줄에 태그) → HARVEST.md에 모듈마다 "삭제: 12주 미참조, LATER 미기재" ④삭제하지 않은 모듈 수와 이유(세 질문 중 어느 것)를 RETRO 재료로 ⑤복구 절차 한 줄(태그에서 복구 · HARVEST "복구" · 3건 넘으면 기준 수정).
- **완료 기준:** ①태그 ②삭제 PR ③HARVEST.md N·M·K ④보존 모듈 수와 이유.
- **하지 말 것:** 세 질문을 건너뛰고 "어차피 안 쓴다"로 지우지 않는다. 데이터 삭제 금지. "언젠가 쓸지도"로 보존하지 않는다(LATER에 세션 번호와 함께 적혀 있을 때만).

### S75. 게이트·이름 변경·회고 — §7 판정 · golden/→app/ · RETRO.md · 4단계 초안 (관문 ⑤)

- **목적:** 일곱 줄 판정, 통과 시 `golden/`→`app/`, 회고, 4단계(파일럿) 초안.
- **선행 산출물:** S73 GATE.md, S74, S67 보고(AI 완료율), S61 DESIGN.md, S68·S70.
- **할 일:** ①일곱 줄 각각 예/아니오와 근거(공유 계약 게이트 절 · 판정 기준 커밋 해시 상단) → `golden/reports_phase3/GATE.md` 확정 — 줄 ⑥은 "미실시(Kiki 결정 2026-11-17 · AI 대체)"로 적고 판정 셈에서는 "아니오" 하나, AI 완료율은 별도 줄 ②판정: 첫 줄 "예" + 나머지 "아니오" ≤2 → 4단계 / 첫 줄 "아니오" → S61~S73 반복(코어 갭 ≤20줄이면 "조건부") ③통과 시 `golden/`→`app/`: 폴더 이름(`src/backend/golden`→`src/backend/app`? — **충돌 확인**: 옛 `whymath_backend/app.py`와 혼동 가능 · 제안값은 `src/backend/app_core`가 아니라 계획서대로 `app`이되 import 경로 충돌을 S75가 실측해 Kiki 결정) · import 경로 · `CLAUDE.md` 골든 패스 규칙 블록을 "app/ 규칙"으로 · CI 경로(`golden-path` 잡·`pyproject.toml` `packages`·import-linter) — 한 PR · e2e 초록. 안 바꾸면 이유를 RETRO에 ④`golden/RETRO_phase3.md`: 세션별 충족 표 · 범위 밖 멈춘 순간 · LATER 수 · "추상화를 더 하고 싶었던 순간" 횟수 · /legacy 보존 모듈 수와 이유 ⑤`golden/NEXT_PHASE4.md`(파일럿): 첫 세션의 FINDINGS 인용 항목 · 파일럿 학생 20~30명 모집 계획(4단계는 2026-11-17 결정으로 AI 코호트 20명 운영 리허설이다 — 모집 계획 대신 "AI 코호트 구성"을 적고, 실학생 모집 계획은 4단계 뒤의 실학생 파일럿 몫으로 적는다) · **1~3단계 "개방 시점 보완" 목록 전부**(각 단계 공유 계약 블록과 보고에서 "측정 불가"로 적힌 것 — 4단계가 이어받아 실학생 파일럿까지 넘긴다) · 네 단원 함께 검증 · 게이트는 리텐션(단원 수와 무관) · 세션 번호 S76부터.
- **완료 기준:** ①일곱 줄 판정 ②이름 변경 PR 또는 미변경 이유 ③RETRO ④NEXT_PHASE4 첫 세션 F 번호와 모집 계획·개방 시점 보완 목록.
- **하지 말 것:** 다섯 번째 단원·두 번째 과목·EOS를 초안에 넣지 않는다(4단계 게이트는 학생 20~30명의 리텐션이고 단원 수와 무관하다). 통과 전 이름 변경 금지.
