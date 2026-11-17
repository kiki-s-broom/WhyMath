세션 이름: SC-단계16-S73-드라이런-diff0줄

# [WhyMath 3단계 세 번째 단원 + Subject Contract] 작업 S73: 드라이런 — 네 번째 단원 폴더 5파일 · e2e 4단원 · AI 720 · diff 0줄 (관문 ④ — 게이트 본체)

> **사용법:** 새 세션을 열고 세션 이름을 `SC-단계16-S73-드라이런-diff0줄`(이 파일 이름)으로 정한다. 아래 "작업 환경"이 맞는지 보고, 이 파일 전체를 그대로 붙여 넣는다.

## 작업 환경

- 저장소 위치: GitHub `kiki-s-broom/whymath` · Kiki 머신 `C:\Users\kiki\Desktop\__AI\WhyMath`(PowerShell) · 클라우드 세션 `/home/user/WhyMath`
- 산출물 폴더: 저장소 안의 `golden/reports_phase3/` (없으면 만든다)
- 기본 브랜치: main · 작업 브랜치: `golden-p3/S73` (아래 "산출물 저장 규칙")
- 계획서: `plan_phase3_contract_4weeks.docx` (2026-11-15 Kiki 계획서 원본 · Kiki 보관 원본(저장소 미포함 — office·PDF 문서는 `.gitignore`와 `scripts/ops/check_source_document_binaries.py`가 커밋을 막는다 · 저장소 안 정본은 지시서)) · 지시서 원본 `golden/prompts_src/spec_phase3.md` · 선행 묶음 `golden/prompts/`(S1~S15)·`golden/prompts_phase1/`(S16~S35)·`golden/prompts_phase2/`(S36~S55)

## 너의 역할

너는 WhyMath(와이매스) 3단계 「세 번째 단원 + 추상화(Subject Contract)」 4주 프로젝트(골든 패스 S1~S15 → 1단계 S16~S35 → 2단계 S36~S55의 후속)에서 **작업 S73만** 맡은 AI다. 이 지시문에 적힌 일만 하고, 끝나면 정해진 형식으로 보고한다.
**첫 행위(0단계)로 세션 제목을 등록한다**: 클라우드 세션(claude.ai/code)이면 `claude-code-remote`의 `set_session_title` 도구를 `session_id` 생략·`title="SC-단계16-S73-드라이런-diff0줄"`으로 호출한다. 그 도구가 없는 환경(터미널 Claude Code)이면 사용자에게 `/rename SC-단계16-S73-드라이런-diff0줄` 한 줄을 안내하고 진행한다. 어느 쪽이든 결과를 완료 보고 첫 줄에 적는다. (이 파일 첫 줄 `세션 이름:`을 저장소 훅이 읽어 `golden/SESSIONS.md`에도 자동 기록한다.)

## 실행 방식

- **실행 단계:** 16단계 (전체 17단계 중)
- **실행 방식: 순차 (단독).** 16단계에는 이 작업 하나뿐이다. 앞 단계가 끝난 뒤 이 세션만 실행한다.
- **여유: 없음 (크리티컬 패스).** 이 작업이 늦어지면 전체가 늦어진다.

## 프로젝트 배경

- WhyMath(와이매스)는 한국 중·고등학생용 AI 수학 학습 앱이다. 골든 패스 3주(S1~S15)로 중2 일차함수 30문항이 끝까지 도는 경로 하나(닉네임 세션 → 문제 → 답변 → 튜터 되묻기 3턴 → SymPy 채점 → 숙련도)가 생겼고, 1단계(S16~S35)가 AI 학생 시뮬레이터(720세션·M1~M5)와 슬롯 T1·T2·T3를, 2단계(S36~S55)가 두 번째 단원(연립일차방정식)·문항 파이프라인(`golden.content.pipeline`)·분기 장부(`golden/CONTRACT.md`)를 더했다. 코드는 `src/backend/golden/`, 서버 `golden.api:app`, 앱 `lib/main_golden.dart`, e2e `tests/golden/`.
- **시작 조건:** 2단계 S54·S55 게이트에서 질문 1(두 단원이 같은 코드로 도는가)과 질문 2(AI가 새 단원 문항 30개를 만들 수 있는가)가 모두 "예"다. 아니면 이 묶음을 열지 않는다. S56이 첫 단계에서 2단계 산출물(`content/`·`CONTRACT.md`·`problems_sys_eq.json`·단원별 숙련도 표·`VALIDATION_FINAL.md`)을 실측한다.
- 2026-11-15 결정(Kiki): 4주(세션 20회 S56~S75, 2027-02-01~03-05 · 설 연휴 2/6~2/9)에 **세 번째 단원(중2 일차부등식 · 답 유형 range)**을 먼저 2단계와 같은 옛 방식으로 넣어 분기 장부를 세 단원 기준으로 완성한 뒤(세 번 규칙 — 세 번째 사례가 있어야 무엇이 공통인지 보인다), 장부에서 **Subject Contract**(단원 하나 = 폴더 하나 · 파일 다섯 개 `unit.yaml`·`problems.json`·`misconceptions.json`·`error_rules.yaml`·`glossary.md` · 코드 0개)와 그것을 읽는 `core/`(단원을 모르는 코드 — `'unit =='` 비교 0줄)를 뽑아낸다. 네 번째 단원을 Contract만으로 추가하는 드라이런이 게이트다.
- 게이트는 하나다: **네 번째 단원을 추가하는 PR에서 `.py`와 `.dart`의 변경이 0줄.** 네 번째 단원이 무엇인지는 S56에서 `golden/PREREG.md`에 적고 커밋 해시로 봉인해 S71까지 열지 않는다(사전 등록 — 설계가 네 번째 단원에 맞춰지면 0줄은 증명이 아니라 연출이다). S57~S70 세션은 네 번째 단원을 **모르는 채로** 작업하며, 이 지시서도 S71~S73 본문 밖에서는 그 단원을 이름으로 부르지 않는다.
- 원칙 넷이 앞선 계획서들의 원칙 위에 더해진다. ①Contract 필드는 두 단원 이상이 서로 다른 값을 가질 때만 존재한다(세 단원이 같으면 상수다). ②`core/`에는 단원 이름·단원 ID 문자열을 쓰지 않는다 — 나타나면 그 PR은 닫는다(테스트로 동결). ③PREREG.md는 S71 전까지 열지 않는다. ④새 길 초록 → 옛 길 삭제, 그 반대 금지 — 삭제는 `git tag` 뒤에만. 과목 추상화(SubjectAdapter·과목 레지스트리·EOS Core)·단원 DSL·"미래 필드"·비교기 5종째·성능 최적화는 범위 밖이다. 두 번째 과목이 없는데 과목을 추상화하는 것은 사례 0개로 추상화하는 것이다.
- 일정: 12주차(S56~S60) 사전 등록·조사표·세 번째 단원 문항(파이프라인)·AI 회귀·옛 방식 연결·장부 3/3·2/3·1/3 표시, 13주차(S61~S66) Contract 설계(2쪽)·로더/스키마·비교기 4종+특성화 90케이스·튜터/숙련도/주입기·플래그 `GOLDEN_ENGINE=core|legacy`로 새 길 초록·2,160세션 비교 후 전환, 14주차(S67~S70) AI 학생 정독 15건(core 위 · 실학생 대체)·옛 분기 삭제 PR·Flutter 단원 목록(`GET /golden/units`)·Contract 정식화, 15주차(S71~S75) PREREG 개봉·네 번째 단원 문항·드라이런(diff 0줄 측정)·/legacy 판정(태그)·게이트 일곱 줄·`golden/`→`app/`·회고·4단계(파일럿) 초안. 완료 기준을 못 채우면 같은 번호를 반복한다.
- 저장소 사실이 계획서 전제와 다른 곳(공유 계약 첫 표): 중2 일차부등식 오개념은 DB에 3건(+선행 일차방정식 3건 · 나머지 부등식 18건은 고교) · 일차부등식 **범위 답** 문항 자산 없음(연립부등식 경계값 600건은 유사도 대조군만) · 옛 골든 `grade.py`에 `range` 비교기 없음(SymPy `solveset`·`Interval`로 만든다) · Flutter 골든 화면 6파일에 단원 문자열이 있을 수 있음(S69가 지운다) · 2단계 산출물은 사전 실측 시점에 없었다(S56이 실측). 가장 큰 유혹은 "네 번째 단원을 떠올리며 설계하기"와 "0줄을 만들려고 코드를 yaml에 숨기기"다 — 둘 다 게이트를 무효로 만든다.
- **2026-11-17 결정(Kiki): 3단계도 실 학생 없이 AI로 진행한다.** H4(실학생 섭외)는 중단이고 S67은 AI 학생 정독 세션(P2·P3·P4 × 일차부등식 5문항 = 15건)이다. 게이트 줄 ⑥은 "미실시"로 적고 판정 셈에서는 "아니오" 하나다. 실학생만 말할 수 있는 것(부등식 답 입력 표기 분포 등)은 "측정 불가(개방 시점 보완)"로 적어 4단계 초안에 넘긴다. 위 문단들의 "실학생"은 계획서 원문이고, 지금 읽는 법은 공유 계약 「실학생 대체 결정」 블록이 정한다.

## 이 작업의 위치

- 레인: 드라이런·게이트
- 선행 작업과 그 산출물 위치:
    - S72 (네 번째 단원 문항 — 파이프라인 · Kiki 검토 30분) → `golden/reports_phase3/S72/`
- 이 작업의 결과를 쓰는 다음 작업: S75
- 이 작업은 **관문 ④**이다. 보고에 판정(go 또는 no-go)을 반드시 적는다.
- 레인 메모: S71(개봉)→S72(문항)→S73(드라이런)은 직선이다. S74(/legacy 판정)는 S70만 기다리므로 S71~S73과 **동시에** 간다(다른 브랜치·다른 파일). S75가 게이트·이름 변경·회고.

## 공통 규칙 (작업보다 먼저 지킨다)

규칙과 작업 지시가 충돌하면 규칙이 우선한다.

1. **읽을 범위:** 이 지시문과, 이 지시문이 "선행 산출물"로 적은 결과물만 읽는다. 다른 작업 번호의 일은 하지 않는다.
2. **선행 작업 확인:** 선행 작업마다 `golden/reports_phase3/<번호>/보고.md`가 있고 결과가 "완료"인지 확인한다. 관문 작업(S65, S66, S68, S73, S75)은 판정이 go인지도 확인한다. 하나라도 아니면 시작하지 말고, 비어 있는 번호를 보고하고 멈춘다.
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

## 용어

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

## 공유 계약 (모든 세션이 같은 모양을 쓴다 — 바꾸려면 보고하고 멈춘다)

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

## 작업 지시: S73. 드라이런 — 네 번째 단원 폴더 5파일 · e2e 4단원 · AI 720 · diff 0줄 (관문 ④ — 게이트 본체)

- **목적:** 네 번째 단원을 §3-5 여섯 걸음으로 추가한다. 오늘의 숫자는 하나: **이 PR의 `.py`/`.dart` 변경 줄 수.**
- **선행 산출물:** S72 30문항·오개념, S70 CONTRACT.
- **할 일(계획서 §5-5):** ①브랜치를 새로 딴다. 시작 커밋 해시를 적는다 ②`units/poly_calc/`에 5파일: `problems.json`(S72)·`misconceptions.json`(S71)·`error_rules.yaml`(규칙 언어로 — 분배 누락·부호·차수 결합)·`glossary.md`(10줄 이내 · 동류항·분배법칙·지수법칙)·`unit.yaml`(`answer_type: expression` · bkt는 `linear_fn` 값 복사) ③`pytest tests/golden` — 4단원 자동 parametrize 확인. 안 되면 **첫 번째 코어 갭** ④AI 회귀 720(poly_calc · Kiki 머신) M1~M5 ⑤앱을 띄워 단원 목록에 식의 계산이 보이는지 — 안 보이면 **두 번째 코어 갭** ⑥`git diff --stat <시작 해시> -- '*.py' '*.dart'` 결과를 `golden/reports_phase3/GATE.md`에 그대로 ⑦0줄이 아니면 바뀐 줄마다 분류: 코어 갭(core가 이 단원을 받으려면 바뀌어야 했던 줄 — 비교기·파서·프롬프트 가정) / 단원 갭(unit.yaml에 필드가 없어서 코드로 쓴 줄 — Contract에 필드 추가 후 재실행하면 다음엔 0줄 · **두 번째 실행의 0줄도 인정**) / 그 외(단원 무관 버그 — 계산에서 제외하되 적는다).
- **산출물:** `units/poly_calc/` 5파일, 4단원 e2e 결과, 720 보고서, GATE.md(diff 원문·분류 표).
- **완료 기준:** ①GATE.md에 `git diff --stat` 원문 ②0줄이면 통과, 아니면 줄마다 분류와 줄 수 ③e2e 4단원 결과(초록/빨강 그대로) ④판정: **통과**(0줄) / **조건부**(코어 갭 ≤20줄) / **미통과**(초과).
- **하지 말 것:** 0줄을 만들기 위해 코드 변경을 `unit.yaml`의 "스크립트 필드"로 숨기지 않는다(yaml 안에 python 식이 들어가면 그것은 코드다). 숫자가 0이 아니어도 그 숫자가 결과다. 실학생을 붙이지 않는다.

## 산출물 저장 규칙

- 이 작업에서 만든 문서, 표, 보고서는 모두 `golden/reports_phase3/S73/`에 저장한다.
- 코드 변경은 저장소의 기존 위치에 하되, git을 쓰는 저장소라면 `golden-p3/S73` 브랜치에서 작업하고 기본 브랜치에 직접 반영하지 않는다.
- 마지막으로 `golden/reports_phase3/S73/보고.md`에 아래 형식의 완료 보고를 쓰고, 같은 내용을 답변으로도 보여준다.

## 완료 보고 형식

```
작업 번호: S73
결과: 완료 | 일부 완료 | 중단
판정: go | no-go (근거 수치 포함)
만든 것: 파일·테이블·화면 이름 (경로 포함)
완료 기준 확인: 항목별 통과/실패와 근거 (실행한 명령 또는 본 화면)
미확인·가정한 것: 없으면 "없음"
다음 작업이 알아야 할 것: 없으면 "없음"
```

## 시작 순서

0. 세션 제목을 `SC-단계16-S73-드라이런-diff0줄`으로 등록한다("너의 역할"의 첫 행위).
1. 공통 규칙 2번대로 선행 작업의 `보고.md`를 확인한다.
2. "작업 지시"의 할 일을 순서대로 수행한다.
3. "완료 기준"을 하나씩 확인하고 결과를 기록한다.
4. `golden/reports_phase3/S73/보고.md`를 쓰고 보고한다.
