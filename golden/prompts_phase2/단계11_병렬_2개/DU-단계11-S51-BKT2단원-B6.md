세션 이름: DU-단계11-S51-BKT2단원-B6

# [WhyMath 2단계 두 번째 단원] 작업 S51: 숙련도 2단원 — BKT 파라미터 연립방정식 값(B6) · 섀도

> **사용법:** 새 세션을 열고 세션 이름을 `DU-단계11-S51-BKT2단원-B6`(이 파일 이름)으로 정한다. 아래 "작업 환경"이 맞는지 보고, 이 파일 전체를 그대로 붙여 넣는다.

## 작업 환경

- 저장소 위치: GitHub `kiki-s-broom/whymath` · Kiki 머신 `C:\Users\kiki\Desktop\__AI\WhyMath`(PowerShell) · 클라우드 세션 `/home/user/WhyMath`
- 산출물 폴더: 저장소 안의 `golden/reports_phase2/` (없으면 만든다)
- 기본 브랜치: main · 작업 브랜치: `golden-p2/S51` (아래 "산출물 저장 규칙")
- 계획서: `plan_phase2_second_unit_4weeks.docx` (2026-11-15 Kiki 계획서 원본 · Kiki 보관 원본(저장소 미포함 — office·PDF 문서는 `.gitignore`와 `scripts/ops/check_source_document_binaries.py`가 커밋을 막는다 · 저장소 안 정본은 지시서)) · 지시서 원본 `golden/prompts_src/spec_phase2.md` · 선행 묶음 `golden/prompts/`(S1~S15)·`golden/prompts_phase1/`(S16~S35)

## 너의 역할

너는 WhyMath(와이매스) 2단계 「두 번째 단원」 4주 프로젝트(골든 패스 S1~S15 → 1단계 S16~S35의 후속)에서 **작업 S51만** 맡은 AI다. 이 지시문에 적힌 일만 하고, 끝나면 정해진 형식으로 보고한다.
**첫 행위(0단계)로 세션 제목을 등록한다**: 클라우드 세션(claude.ai/code)이면 `claude-code-remote`의 `set_session_title` 도구를 `session_id` 생략·`title="DU-단계11-S51-BKT2단원-B6"`으로 호출한다. 그 도구가 없는 환경(터미널 Claude Code)이면 사용자에게 `/rename DU-단계11-S51-BKT2단원-B6` 한 줄을 안내하고 진행한다. 어느 쪽이든 결과를 완료 보고 첫 줄에 적는다. (이 파일 첫 줄 `세션 이름:`을 저장소 훅이 읽어 `golden/SESSIONS.md`에도 자동 기록한다.)

## 실행 방식

- **실행 단계:** 11단계 (전체 17단계 중)
- **실행 방식: 병렬 가능.** 같은 11단계의 S47와 동시에 다른 세션에서 실행해도 된다.
- **병렬 주의:** 동시에 도는 다른 세션과 같은 파일을 고치게 되면, 자기 브랜치에서만 고치고 합칠 때 충돌을 보고한다.
- **여유:** 늦어도 13단계 안에만 끝나면 전체 일정이 밀리지 않는다.

## 프로젝트 배경

- WhyMath(와이매스)는 한국 중·고등학생용 AI 수학 학습 앱이다. 골든 패스 3주(S1~S15)로 중2 일차함수 30문항이 끝까지 도는 경로 하나(닉네임 세션 → 문제 → 답변 → 튜터 되묻기 3턴 → SymPy 채점 → 숙련도)가 생겼고, 1단계 두꺼게 4주(S16~S35)가 AI 학생 시뮬레이터(페르소나 8종·720세션·M1~M5)와 슬롯 T1·T2·T3(루브릭 평가기·오개념 매칭·BKT 섀도)를 더했다. 코드는 `src/backend/golden/`, 서버 `golden.api:app`, 앱 `lib/main_golden.dart`, e2e `tests/golden/`.
- **시작 조건:** 1단계 S35 게이트의 진실 트랙 세 줄(실학생 3명·50건 / 완료율 70% / 슬롯 둘 효과)이 "예"다. 아니면 이 묶음을 열지 않는다. S36이 첫 단계에서 1단계 산출물(`sim/`·`eval/`·`mastery/`·`CALIBRATION.md`·`FINDINGS_v2.md`)을 실측한다.
- 2026-11-15 결정(Kiki): 4주(세션 20회 S36~S55, 2027-01-04~01-29) 안에 **두 번째 단원(중2 연립일차방정식)**을 더해 질문 둘에 증거로 답한다. 질문 1: 두 단원이 같은 골든 패스 코드로 도는가 — 답은 분기 장부 `golden/CONTRACT.md`의 코드 분기 수(0~3 예 · 4~6 조건부 · 7+ 아니오). 질문 2: 저작권 가이드 안에서 AI가 새 단원 문항 30개를 만들 수 있는가 — 답은 메트릭 8줄(수율·검토 시간·결함률 셋이 목표 안이면 예). 12/31 내부 검증은 1단계 산출물로 1차 판정이고 S54가 최종 판정이다.
- 연립일차방정식을 고른 이유: 답 유형이 수 하나에서 순서쌍 (x, y)로 바뀌어 판정 코드에 분기가 생길 수밖에 없고 오개념도 다르다. 반면 같은 학년이고 두 직선의 교점으로 일차함수와 이어져 튜터 프롬프트는 대부분 재사용된다. 일차함수 활용은 너무 비슷해 "분기 0개"라는 가짜 신호를 줄 위험이 있다. S36에서 바꿀 수 있지만 이 근거를 반박해야 한다.
- 문항은 **파이프라인으로만** 만든다. 스펙 1개 → 서로 다른 모델 2개가 각 45개 후보 → 검증 4단(V1 스키마 · V2 sympy · V3 저작권·유사도 · V4 AI 검토기 2개 교차) → 합의 통과·불일치·탈락. 사람(Kiki)은 검토기 둘이 어긋난 문항만 30분 상한으로 본다. 골든 패스에서 결함이 난 문항은 손으로 고치지 않고 같은 파이프라인을 다시 탄다 — 이 루프가 돌아야 "AI가 만들 수 있다"가 "AI가 유지할 수 있다"까지 답한다. 손으로 쓴 문항은 30개에 넣지 않는다.
- 원칙 둘이 앞선 계획서들의 원칙 위에 더해진다. ①단원 조건으로 갈라지는 코드를 한 줄이라도 추가하면 그 커밋 안에서 `golden/CONTRACT.md`에 한 줄 적는다 — 분기를 없애려 애쓰지 않는다, 세는 것이 목적이다. ②문항은 `golden.content.pipeline`로만 만든다. 범위는 두 단원 60문항이고, 세 번째 단원과 Subject Contract 구현은 3단계다.
- 일정: 8주차(S36~S40) 스펙·생성·검증·확정·AI 회귀, 9주차(S41~S45) 단원 스위치(S41은 연립방정식 e2e 빨강이 목표)·판정 pair·튜터/오개념 분기·실학생 1차·1차 판정, 10주차(S46~S50) 혼합 세션·AI 1,440·결함 재생성·실학생 2차·콘텐츠 중간 판정, 11주차(S51~S55) BKT 2단원·실학생 3차·아키텍처 증거·최종 검증·게이트. 매주 넷째 세션이 실학생이고 그 전에 AI 회귀가 먼저 돈다. 완료 기준을 못 채우면 같은 번호를 반복한다.
- 저장소 사실이 계획서 전제와 다른 곳(공유 계약 첫 표): 연립방정식 오개념은 DB에 4건(+선행 5건) · 연립방정식 문제은행은 없음(전부 파이프라인 생성 — 계획과 일치) · 옛 저작 파이프라인 자산(`l3/equivalent/acceptance.py`·`authoring_guard.py`·`llm_generator.py`)이 V1·V3 후보로 있음 · 옛 스키마에 순서쌍 답 유형 없음(B2는 예상대로 코드 분기). 가장 큰 유혹은 "급하니 문항 몇 개는 손으로"다 — 그 순간 질문 2에 답할 수 없게 된다.

## 이 작업의 위치

- 레인: 혼합·재생성
- 선행 작업과 그 산출물 위치:
    - S46 (혼합 세션 — GET /golden/next 단원 선택 · 숙련도 단원별 분리(B7)) → `golden/reports_phase2/S46/`
- 이 작업의 결과를 쓰는 다음 작업: S52
- 레인 메모: S46(혼합 세션·단원별 숙련도) 뒤에 S47(AI 전체 회귀 1,440)·S48(결함 재생성)·S51(BKT 2단원 파라미터)은 서로 독립이라 **동시에** 갈 수 있다. S49 실학생 2차는 S47·S48이 끝난 뒤, S50이 콘텐츠 중간 판정.

## 공통 규칙 (작업보다 먼저 지킨다)

규칙과 작업 지시가 충돌하면 규칙이 우선한다.

1. **읽을 범위:** 이 지시문과, 이 지시문이 "선행 산출물"로 적은 결과물만 읽는다. 다른 작업 번호의 일은 하지 않는다.
2. **선행 작업 확인:** 선행 작업마다 `golden/reports_phase2/<번호>/보고.md`가 있고 결과가 "완료"인지 확인한다. 관문 작업(S39, S45, S50, S53, S54)은 판정이 go인지도 확인한다. 하나라도 아니면 시작하지 말고, 비어 있는 번호를 보고하고 멈춘다.
3. **golden/ 바깥은 읽기 전용:** 새 코드는 `src/backend/golden/`(파이썬 — 하위 `content/`·`sim/`·`eval/`·`mastery/`), `golden/`(문서·데이터·로그), `src/mobile/lib/golden/`, `tests/golden/`에만 쓴다. 옛 코드를 고쳐야 돌아가면 `golden/` 아래로 복사해서 고치고 `golden/HARVEST.md`에 한 줄 적는다. `constitution/`은 어떤 세션도 건드리지 않는다. `golden/` 바로 아래에 `.py`를 두지 않는다(`tests/infra/test_lint_coverage.py`가 막는다 — 코드는 전부 `src/backend/golden/` 아래). 이 단계의 배선 파일 예외는 **없다**(야간 CI 워크플로는 1단계 S19가 만든 `golden-sim-nightly.yml`을 S47이 고치는 것뿐 — 그 파일은 골든 소유다).
4. **범위 고정:** 두 단원(중2 일차함수 30문항 + 중2 연립일차방정식 30문항 = 60문항)·GP-1~GP-6·HTTP 엔드포인트 3개(요청 필드는 늘 수 있다 — `unit`). 세 번째 단원·Subject Contract 구현·분기 정리(코드 → 설정 내리기)는 3단계다. 분기를 없애려 애쓰지 않는다 — **세는 것**이 이 단계의 목적이다.
5. **단원 분기는 그 커밋 안에서 장부에 적는다:** `unit` 값에 따라 동작이 갈라지는 코드를 한 줄이라도 쓰면 같은 커밋에 `golden/CONTRACT.md` 한 줄(공유 계약의 형식)을 적는다. 적지 않은 분기는 리뷰에서 PR을 닫는다. 예상 목록 B1~B7에 없는 분기는 B8부터 번호를 붙인다. 번호가 B10을 넘으면 S53을 기다리지 않고 그 자리에서 보고하고 계획서 §7 리스크 표를 본다.
6. **문항은 파이프라인으로만 만든다:** 문항 JSON(`golden/data/problems_sys_eq.json`)을 손으로 쓰거나 고치지 않는다. 결함 문항은 재생성으로 교체한다. 급하다고 손으로 쓴 문항은 30개에 넣지 않는다 — 넣는 순간 "AI가 만들 수 있나"에 답할 수 없다. 생성기·검토기 프롬프트에 **예시 문항을 넣지 않는다**(예시를 넣으면 모델이 예시를 변형하고 그것은 창작이 아니다). 스펙의 `forbidden` 규칙은 프롬프트에 그대로 들어간다.
7. **모든 PR은 FINDINGS 항목 번호를 인용한다:** 1단계 번호 체계(`F-NN`, `golden/FINDINGS.md` 끝 「항목 번호」 절 · 2단계는 `golden/FINDINGS_v2.md`의 번호)를 쓴다. 2단계 공통 항목 두 개를 S36이 추가한다 — `F-Q1`(두 단원이 같은 코드로 도는가)·`F-Q2`(AI가 저작권 안에서 문항 30개를 만들 수 있는가). 인용할 항목이 없으면 그 PR은 지금 할 일이 아니다.
8. **완료 기준은 tests/golden 초록 + 야간 스모크 초록(두 단원):** 코드를 건드린 세션은 `cd src/backend && python -m pytest ../../tests/golden`을 exit code로 판정한다(`-q`·`| tail` 금지). S43 이후에는 가짜 모드 스모크를 두 단원에 돌려 M4·M5 0건을 확인한다. 빨간불이면 PR을 만들지 않는다 — **예외: S41**(연립방정식 e2e 빨강이 목표).
9. **LLM 호출 규칙:** 모든 LLM 호출은 옛 코드의 `whymath_backend.l3.providers.factory.build_cloud_provider()` + `l3.router.Router.route`(클라우드) 또는 `l3.providers.ollama.OllamaProvider`(로컬) 경유. 생성기 2개·검토기 2개는 **서로 다른 모델 4개**가 이상적이지만, 최소 조건은 "생성기 둘이 다르고 검토기 둘이 생성기와 다르다"이다. 모델 선택은 S36에서 Kiki 확인(Anthropic API 중단은 2026-12-31까지 · 2단계는 2027-01이라 재개 판정 `G-arch66`에 따라 Claude 좌석이 열릴 수 있다). 키 하드코딩 금지. **테스트와 CI는 실제 LLM을 부르지 않는다**(`GOLDEN_FAKE_LLM=1`이면 생성기·검토기·튜터·학생 모두 고정 대본).
10. **저작권 레일:** 문항 본문은 전부 AI 창작이며 `license=WHYMATH_GENERATED`·`source_type=자체생성`·`generation_type=FULLY_GENERATED`로 기록한다(옛 `ContentProvenance` 어휘 — `whymath_backend/schema/problem.py`). 교과서·EBS·평가원·시중 교재의 문장·상황·수치 조합을 재현하지 않는다(`docs/data/licensing_safety.md` 「저작권 가이드 v2.0」·「절대 금지 목록」). 후보마다 생성 모델·스펙 버전·프롬프트 해시·시각을 남긴다 — 이것이 "AI가 만들었다"는 증거다. `golden/data/problems_sys_eq.json` 옆에 `_provenance.json` 사이드카를 둔다(옛 문제은행 폴더 관례와 같은 필드 — `pool`·`source_citation`·`license_notice`·`record_count`·`generated`·`generation_method`·`review_status`).
11. **미성년자 데이터:** 학생 식별자는 닉네임뿐(실학생 `stu-<번호>-<회차>`). 실학생 로그를 생성기·검토기 프롬프트에 넣지 않는다(결함 문항 재생성 때도 "어느 문항이 결함인가"만 넘기고 학생 입력은 넘기지 않는다). 1단계 시드(`golden/sim/seed/`)는 로컬 Ollama 외 어디로도 보내지 않는다. 보호자 동의는 Kiki 담당.
12. **검증은 CI와 같은 명령으로:** `src/backend`에서 `python -m ruff check golden ../../tests/golden`, `python -m black --check --line-length 100 golden ../../tests/golden`, `python -m mypy --strict golden`, `lint-imports`(CI `golden-path` 잡의 네 스텝). 로컬 CI 미러(`python3 scripts/harness/ci_mirror.py run`)는 커밋한 뒤 돌리고, 미러가 도는 동안 커밋·amend를 하지 않는다.
13. **모르는 값은 추정 금지:** 이 문서의 "사전 실측(2026-11-15 · main `a9cff6ec`)"은 **1단계 산출물이 아직 없는 시점**의 값이다. 2단계 세션은 1단계가 남긴 파일(`src/backend/golden/sim/`·`eval/`·`mastery/`·`golden/CALIBRATION.md`·`FINDINGS.md` 판정 절)을 먼저 확인하고, 이 문서의 가정과 다르면 보고에 적는다. 못 찾으면 "미확인"으로 적고 그 부분만 멈춘다.
14. **하네스·커밋·PR:** 코드나 문서를 바꾸는 세션은 첫 행위로 `python3 scripts/harness/backlog.py start <태스크 ID>`. 태스크 ID는 S36이 `backlog.py add`로 받아 `golden/STATE.md`「하네스 태스크 ID」 절에 "2단계: <번호>"로 적어 둔 것을 쓴다. 커밋 메시지는 `S<번호>: <한 줄> (F-xx)`. PR 본문 첫 질문에 GP 번호와 F 번호. main 머지는 Kiki가 한다.
15. **한국어:** 코드 주석·문서·보고는 한국어(식별자는 영어).
16. **종료 보고 8줄:** ①완료 기준 충족 여부 ②tests/golden 결과(초록/빨강·N개) ③HARVEST.md 추가 줄 ④LATER.md 추가 줄 ⑤범위 밖으로 나가려다 멈춘 순간 ⑥AI 스모크 결과(일차함수 / 연립방정식 각각 M1~M5 · S43 전이면 "해당 없음") ⑦이 세션이 FINDINGS F-xx를 전진시켰는가 ⑧**오늘 CONTRACT.md에 적은 분기 ID**(없으면 "없음").

## 용어

| 용어 | 뜻 |
| --- | --- |
| 골든 패스 | GP-1 세션 시작 → GP-2 문제 제시 → GP-3 답변 → GP-4 튜터 되묻기(최대 3턴) → GP-5 판정 → GP-6 숙련도 갱신. 서버 `golden.api:app`, 앱 `lib/main_golden.dart`, 코드 `src/backend/golden/` |
| 두 번째 단원 | 중2 연립일차방정식(기본값 · 단원 ID `sys_eq` · 문항 ID 접두 `SE-`). 답 유형이 수 하나에서 순서쌍 `(x, y)`로 바뀌어 판정 코드에 분기가 생기고 오개념도 다르다. 같은 학년이고 두 직선의 교점으로 일차함수와 이어져 튜터 프롬프트는 대부분 재사용된다 |
| 질문 1 (`F-Q1`) | 두 단원이 같은 골든 패스 코드로 도는가 — 답은 CONTRACT.md의 **코드 분기 수**(0~3 예 · 4~6 조건부 · 7 이상 아니오) |
| 질문 2 (`F-Q2`) | 저작권 가이드 안에서 AI가 새 단원 문항 30개를 만들 수 있는가 — 답은 메트릭 8줄(수율·검토 시간·결함률 셋이 목표 안이면 예 · 하나 벗어나면 조건부 · 둘 이상 아니오) |
| 파이프라인 | 스펙 1개 → 생성기 2개(각 45개 후보) → 검증 V1 스키마 · V2 수학 · V3 저작권 · V4 AI 검토 2개 → 합의 통과·불일치·탈락 세 묶음 → Kiki는 불일치만 → 30개. 결함 문항은 같은 파이프라인을 다시 탄다 |
| 분기 장부 | `golden/CONTRACT.md`. 단원에 따라 갈라지는 지점을 한 줄씩. S53에서 데이터(파일만 다름)·설정(값만 다름)·코드(if문·클래스·함수가 다름)로 분류. 코드 분기 수가 질문 1의 답 |
| B1~B7 | 예상 분기 7개(공유 계약 표). 코드 분기 예상은 B2(판정 pair)·B5(주입기 규칙)뿐이고 나머지는 데이터·설정이어야 정상 |
| 수율 | 30 ÷ 생성한 후보 수. 목표 33% 이상(90개로 30개) |
| 합의 통과 / 불일치 / 탈락 | V4 검토기 둘이 루브릭 5항목을 각 0/1로 채점해 둘 다 5/5면 합의 통과, 둘 다 3 이하면 탈락, 그 외는 불일치(Kiki가 본다) |
| 결함 문항 | AI 세션·실학생 세션에서 드러난 답 오류·중의성·풀 수 없음. 손으로 고치지 않고 재생성으로 교체 |
| 혼합 세션 | 한 세션에서 두 단원 문제가 번갈아 나오고 숙련도가 단원별로 쌓이는 상태(S46 · B7) |
| 1단계 산출물 | S16~S35가 남긴 것 — `src/backend/golden/sim/`(주입기·학생 모델·러너·보정), `eval/`(T1 루브릭 평가기·T2 오개념 매칭), `mastery/bkt.py`(T3), `golden/CALIBRATION.md`, `golden/FINDINGS.md` 판정 절, `golden/FINDINGS_v2.md`, `golden-sim-nightly.yml`. 2단계는 이것들을 **그대로** 쓴다 |
| 사전 실측 | 이 지시서를 쓰며 2026-11-15에 main `a9cff6ec` 기준으로 확인한 값. 1단계 산출물은 그 시점에 없었으므로 "1단계가 만든다"로 표기한 것은 가정이다 |

## 공유 계약 (모든 세션이 같은 모양을 쓴다 — 바꾸려면 보고하고 멈춘다)

아래 모양은 S36~S55가 전부 같이 쓴다. 바꿔야 한다고 판단하면 바꾸지 말고 보고에 "계약 변경 제안"으로 적고 멈춘다. 골든 패스·1단계의 공유 계약은 그대로 유효하며 여기서는 2단계가 더하는 것만 적는다.

*계획서 전제와 저장소 사실이 다른 곳(사전 실측 2026-11-15 · main `a9cff6ec`) — 지시문은 저장소 사실을 따른다*

| 계획서가 전제한 것 | 저장소 사실 | 이 지시서의 처리 |
| --- | --- | --- |
| 400개 오개념 DB에서 연립방정식분 10~20개 | `data/corpus/misconceptions_v1/misconceptions.json` 843건 중 `subunit`이 연립방정식 계열인 것은 **4건**(`M0566` 연립일차방정식 `[9수02-13]` · `M0029` 한 식만 대입 `[9수02-18]` · `M0228` 평행·일치 판별 누락 `[9수02-18]` · `M0571` 두 일차함수와 연립방정식 `[9수02-18]`). 선행 일차방정식 3건(`M0021` 이항 시 부호 안 바꿈 · `M0022` 한 항에만 곱함 · `M0023` 0·x=0을 해 없음으로)과 분배 2건(`M0017`·`M0018`)이 연립방정식 풀이에서 그대로 난다 | S36이 **N건을 세어 적는다**(10~20은 "있으면"). 각 항목에 "틀린 답을 만드는 규칙" 한 줄을 S36이 쓴다 — 이것은 문항이 아니라 오개념 규칙이므로 손으로 써도 된다 |
| 2022 개정 중2 연립일차방정식 성취기준 코드 2~3개 | `data/corpus/achievement_criteria_v1/achievement_criteria.json`의 중학교 1~3학년군 단원 트리에 "(라) 일차부등식과 연립일차방정식"이 있고, 오개념 DB가 쓰는 코드는 `[9수02-13]`(연립일차방정식)·`[9수02-18]`(두 일차함수의 그래프와 연립일차방정식)이다. 코드별 원문은 세션에서 확인 | S36이 두 파일에서 코드 원문을 찾아 적는다. 못 찾으면 `[확인 필요]`로 두고 파이프라인은 돈다(계획서 §5-2) |
| 연립방정식 문항 자산 | 문제은행 39개 중 연립**방정식** 은행은 **없다**(`problem_bank_linear_inequality_system_v0` 600건은 연립일차**부등식**). 즉 30문항은 전부 파이프라인 생성이다 — 계획서 원칙과 일치 | 옛 문항을 가져올 유혹이 없다. 부등식 은행의 문장·상황을 참고하지도 않는다(V3 유사도 검사 대상에 넣어 재현을 막는다 — 제안값) |
| 생성·검증 파이프라인을 새로 짠다 | 옛 코드에 저작 파이프라인 자산이 있다 — `whymath_backend/l3/equivalent/llm_generator.py`(`LLMEquivalentProblemGenerator`·시스템 프롬프트·프롬프트 버전) · `acceptance.py`(`_evaluate_copyright`·`_evaluate_latex`·`_evaluate_hygiene`·`AcceptanceVerdict` — 자체생성 동등문제 수용 게이트) · `authoring_guard.py`(검산식 재진술·정답 키·단원 코드·교육과정 범위의 결정론 거부 규칙 · EOS-205) · `counterexample_fuzz.py`·`defect_seeder.py`·`difficulty.py`. CI 게이트 `provenance_audit`(`data/corpus/problem_bank_*` 사이드카 계약)·`prompt_asset_audit`(L3 프롬프트 레일). 라이선스 대장에 「LLM 저작 산출물 8-gram 일치율 기록」(EOS-222) 절차가 있다 | V1·V3는 옛 `acceptance.py`의 LaTeX·위생·저작권 값 검사 함수를 1단계와 같은 **다섯 걸음**(경계 → 특성화 테스트 → import/복사 → 플래그 연결 → 초록)으로 가져올 후보다(S38이 결정 · 한 세션에 자산 하나). V2는 계획서 뼈대(`v2_math`)를 새로 쓴다. 생성기 프롬프트는 옛 `llm_generator`의 시스템 프롬프트를 **읽어 보되 복사하지 않는다**(예시 문항이 들어 있으면 원칙 위반). 8-gram 일치율 절차는 V3 보조 지표로 기록만 |
| 1단계 산출물이 전부 있다 | 사전 실측 시점(main `a9cff6ec`)에는 `src/backend/golden/sim/`·`eval/`·`mastery/`·`golden/CONTRACT.md`·`CALIBRATION.md`가 **없다**(1단계가 만든다) | S36 첫 단계에서 1단계 산출물 목록을 실측해 보고에 적는다. 없는 것이 있으면 이 묶음을 열 조건(1단계 게이트)이 안 된 것이므로 멈춘다 |
| 답 유형 `pair` | 골든 `grade.py`의 `is_correct`는 `answer_kind ∈ {number, expression}` 둘뿐(`_same_number`·`_same_expression`). 옛 `schema/problem.py`에는 순서쌍 답 유형이 **없다**(`grep pair|순서쌍` 0건) | B2(판정 분기)는 예상대로 **코드 분기**다. S42가 `pair` 비교기를 새로 쓴다(옛 자산 없음 — HARVEST "버림: 해당 없음") |

*1단계가 남겼다고 가정하는 골든 코드(2단계 세션이 S36에서 실측)*

| 파일 | 2단계가 쓰는 것 |
| --- | --- |
| `src/backend/golden/api.py`·`grade.py`·`tutor.py`·`store.py`·`problems.py` | 골든 패스 본체. `store.py`의 `golden.sessions`에 `cursor`, `golden.students`에 `mastery`(닉네임당 1행), `problems.py`의 `PROBLEMS_PATH`(일차함수 JSON 고정 경로) — S41이 `unit`을 끼운다 |
| `src/backend/golden/sim/` | `errors.py`(`inject(problem, misconception_id) -> WrongAnswer | None` · OP 코드 규칙 표) · `student.py`(페르소나 8종 · 로컬 Ollama) · `run.py`(`--sessions`·`--personas` · `sessions.jsonl`·`sim_report.json`) · `metrics.py`(M1~M5) · `calibrate.py`. S40이 연립방정식 오개념 규칙을 더한다(B5) |
| `src/backend/golden/eval/` | T1 루브릭 평가기(`GOLDEN_T1_RUBRIC`) · T2 오개념 매칭 `match_misconception`(`GOLDEN_T2_MISCONCEPTION` · `golden/data/misconceptions_lf.json`) — S43이 `misconceptions_sys_eq.json`로 갈라지는 지점(B4) |
| `src/backend/golden/mastery/bkt.py` | T3 BKT(`GOLDEN_MASTERY_ENGINE=simple|bkt` · 섀도 표 `golden.mastery_shadow`) — S51이 단원별 파라미터(B6) |
| `golden/FINDINGS.md`(항목 번호 절·T1~T3 판정 절)·`golden/FINDINGS_v2.md`·`golden/CALIBRATION.md`·`.github/workflows/golden-sim-nightly.yml` | 인용 번호·보정 통과 여부·야간 스모크(S47이 240으로 확대) |

*폴더 배치(코드는 `src/backend/golden/` 아래, 데이터·문서는 `golden/` 아래 — 계획서의 `golden/content/*.py` 표기는 이 규칙으로 읽는다)*

```
src/backend/golden/content/        ← S37~S39·S48 코드 (패키지)
  spec.py        스펙 로더(yaml)        generate.py  생성기 2모델
  verify.py      V1~V4                 pipeline.py  전체 실행(python -m golden.content.pipeline --spec ...)
  review.py      review_queue.md 생성 · Kiki 판정 반영
golden/content/
  spec_sys_eq.yaml                 ← S36 (커밋)
  candidates.jsonl                 ← S37 (커밋 · 후보 90개 + 출처 기록)
  verify_report.json  review_queue.md  CONTENT_REPORT.md  ← S38·S39·S48 (커밋)
golden/data/problems_sys_eq.json + _provenance.json  ← S39 (커밋 · 30개)
golden/data/misconceptions_sys_eq.json               ← S36 (커밋)
golden/CONTRACT.md                                   ← S36 머리 · S41~S53 본문
golden/VALIDATION_FINAL.md                           ← S54
golden/reports_phase2/<번호>/보고.md                 ← 각 세션 보고
tests/golden/test_content_*.py · characterization/test_v*_legacy.py · test_unit_switch.py
```

*스펙 `golden/content/spec_sys_eq.yaml`(계획서 §3-1 그대로 · 생성기·검증기가 같은 파일을 읽는다)*

| 키 | 값 |
| --- | --- |
| `unit` / `unit_name_ko` / `grade` | `sys_eq` / 연립일차방정식 / 중2 |
| `standards` | 성취기준 코드 2~3개(S36 기입 · 못 찾으면 `[확인 필요]`) |
| `answer_type` | `pair` |
| `count` / `difficulty` | 30 / `{1: 8, 2: 14, 3: 8}`(1 기본 · 2 표준 · 3 응용) |
| `solution_domain` | `integer_or_simple_rational` — 해의 분모 ≤ 5 |
| `misconception_coverage` | 1 — 문항당 연계 오개념 최소 1개(`misconceptions_sys_eq.json`의 ID) |
| `style` | `max_chars: 180` · `situations: original_only`(상황 설정은 창작만) · `numbers: randomized`(계수·상수는 난수 · 기출과 같은 조합 회피) |
| `forbidden` | 5줄 이내(저작권 가이드 v2.0에서 문항 텍스트에 걸리는 것만): 실존 인물·학교·상표·지명 고유명사 / 교과서 예제 문장 구조 재현("다음 연립방정식을 푸시오" 같은 정형구는 허용, 상황문은 불가) / 특정 출판사 교재의 수치 조합 / 그림·그래프가 있어야 풀리는 문항(텍스트+LaTeX만) / 문항 하나에 소문항 둘 이상 |

*후보·문항 JSON 모양*

- `candidates.jsonl` 한 줄 = 후보 1개: `{"cand_id","unit":"sys_eq","stem","equations":["2*x + y - 7","x - y - 2"],"answer":["3","1"],"difficulty":1|2|3,"misconception_ids":[...],"situation":"상황문(없으면 \"\")","gen_model","spec_version","prompt_hash","generated_at"}`. `equations`는 SymPy 문자열(=0 꼴 좌변). `answer`는 `[x, y]` 문자열 둘.
- `problems_sys_eq.json`(배열 30개): 골든 패스 문항 스키마 7필드(`id`=`SE-01`~`SE-30`·`stem`·`answer`·`answer_kind`·`hint1`·`concept`·`source`) + 2단계 추가 필드 `unit:"sys_eq"`·`equations`·`difficulty`·`misconception_ids`·`cand_id`. **`answer_kind`는 `"pair"`, `answer`는 `"(3, 1)"` 문자열**(일차함수 JSON은 무변경). `source`는 `"pipeline:<gen_model>:<cand_id>"`. `hint1`은 생성기가 함께 낸다(정답을 말하지 않는다 — V4 루브릭 항목).
- `verify_report.json`: `{"spec_version","candidates":90,"v1_fail","v2_fail","v3_fail","v4":{"consensus","disagree","reject"},"yield":30/90,"auto_pass_rate","disagree_rate","tokens":{...},"cost_usd","by_difficulty":{...}}`.

*검증 4단(`verify.py` · 앞 단계 탈락이면 뒤를 돌리지 않는다)*

| 단계 | 검사 | 도구 | 탈락 처리 |
| --- | --- | --- | --- |
| V1 스키마 | 필드 누락 · LaTeX `$` 짝 · 본문 길이 ≤180 · 소문항 수 1 · `equations` 2개 | 규칙(옛 `acceptance._evaluate_latex`·`_evaluate_hygiene` 후보) | 즉시 탈락 |
| V2 수학 | `sympy.solve`로 해가 유일하고 `solution_domain` 안이며 `answer`와 같은지(계획서 §3-4 `v2_math`) | sympy | 즉시 탈락 |
| V3 저작권 | `forbidden` 정규식 · 후보끼리 상황문 문자 4-gram 자카드 유사도 ≥0.6 → 둘 다 탈락(사유에 상대 ID) · 두 모델 사이 계수·상수 조합 완전 일치 → 탈락 · (제안값) 부등식 은행 600건 상황문과의 유사도도 같은 임계로 검사 | 규칙(+ 옛 `_evaluate_copyright` 값 검사) | 즉시 탈락 |
| V4 품질 | 검토기 LLM 2개(생성기와 다른 모델)가 루브릭 5항목(성취기준 부합 · 중의성 없음 · 난이도 라벨 적정 · 오개념 디스트랙터 유효 · 문체 자연스러움)을 각 0/1 | LLM 2개 | 둘 다 5/5 합의 통과 · 둘 다 ≤3 탈락 · 그 외 불일치(Kiki) |

- 30개를 채우는 순서: 합의 통과 → Kiki가 살린 불일치. 난이도 8/14/8을 맞추며 고른다. 안 채워지면 생성기를 **프롬프트 수정 없이** 한 번 더 돌린다. 두 번 돌려도 안 채워지면 그것이 결과다 — 스펙을 완화해 채우지 않는다.

*메트릭 8줄(계획서 §3-5 · `F-Q2`의 답)*

| 메트릭 | 정의 | 목표 | 재는 세션 |
| --- | --- | --- | --- |
| 수율 | 30 ÷ 생성한 후보 수 | 33% 이상 | S38 · S48 |
| 자동 통과율 | V4 합의 통과 ÷ V3까지 통과한 수 | 40% 이상 | S38 |
| 불일치율 | V4 불일치 ÷ V3까지 통과한 수 | 30% 이하 | S38 |
| 검토 시간 | Kiki가 불일치를 보는 데 쓴 분 | 30분 이하 | S39 · S48 |
| 결함률 | AI·실학생 세션에서 드러난 결함 문항 ÷ 30 | 10% 이하(3개) | S45 · S50 |
| 재생성 성공 | 결함 문항을 파이프라인 1회로 교체한 비율 | 100% | S48 |
| 정답률 분포 | 난이도별 실학생 정답률이 일차함수 같은 난이도와 ±15%p 안 | 3개 난이도 모두 | S50 |
| 비용 | 30문항에 든 토큰·달러·세션 수 | 기록만 | S39 · S48 |

- 판정: 수율·검토 시간·결함률 셋이 목표 안이면 "예", 하나가 벗어나면 "조건부"(항목·수치 명시), 둘 이상이면 "아니오". "아니오"도 결과다 — 3단계에서 파이프라인을 고치지 손으로 문항을 쓰지 않는다.

*분기 장부 `golden/CONTRACT.md`(계획서 §4 · `F-Q1`의 답)*

- 한 줄 형식: `| B8 | GP-4 | 3턴 제한이 연립방정식에선 짧아 4턴 필요 | 코드 → 설정으로 바꿀 수 있음 | max_turns(unit) | S43 | 커밋 a1b2c3 |`(ID · 위치 · 무엇이 갈라지나 · 종류(데이터/설정/코드 · "코드 → 설정으로 바꿀 수 있음"은 그렇게 적되 이 단계에서 내리지 않는다) · Subject Contract 후보 줄 · 발견 세션 · 커밋).
- 예상 분기 7개:

| ID | 위치 | 무엇이 갈라지나 | 예상 종류 | Subject Contract 후보 줄 |
| --- | --- | --- | --- | --- |
| B1 | GP-2 문항 로더 | `problems_linear_fn.json` vs `problems_sys_eq.json` | 데이터 | `problems_path(unit)` |
| B2 | GP-5 `grade.py` | 답 비교: 수 하나 vs 순서쌍 | **코드** | `answer_type ∈ {number, expression, pair}`와 각 비교기 |
| B3 | GP-4 튜터 프롬프트 | 단원 용어 블록(기울기·절편 vs 가감법·대입법) | 설정 | `unit_glossary` 문자열 |
| B4 | GP-5 오개념 매칭 | `misconceptions_lf.json` vs `misconceptions_sys_eq.json` | 데이터 | `misconceptions_path(unit)` |
| B5 | `sim/errors.py` 주입기 | 오개념별 틀린 답 규칙 | **코드** | `inject(problem, misconception)`이 단원별 규칙 테이블을 읽는 구조 |
| B6 | GP-6 BKT 파라미터 | 초기 숙련도·학습률·추측률·실수율 | 설정 | `bkt_params(unit)` |
| B7 | `golden.students`/`mastery_shadow` | 숙련도를 단원별로 따로 쌓음 | 스키마(데이터) | `(student, unit)` 복합 키 |

- 판정 기준(S53·S54): 코드 분기 0~3 "예"(골든 패스가 단원을 거의 모른다 — 3단계에서 Subject Contract를 뽑을 수 있다) · 4~6 "조건부"(3단계 첫 주를 분기 정리에) · 7 이상 "아니오"(3단계 전에 S41~S43 재설계). 함께 적는 둘: S41~S43의 `git diff --stat` 골든 **코드** 줄 수(`.py`·`.dart`만 · 데이터·설정 파일 제외) · "세 번째 단원을 지금 추가하면 몇 줄을 고쳐야 하는가" 추정(50줄 아래면 2단계 성공).

*HTTP 계약 변경(2단계 추가분 · 기본값은 일차함수라 옛 클라이언트는 무변경)*

| 요청 | 응답 |
| --- | --- |
| `POST /golden/session` 본문에 `"unit": "linear_fn" \| "sys_eq"` 선택 필드(기본 `linear_fn`) · S46 이후 `"mixed"` 허용 | 응답에 `"unit"` 추가. 같은 닉네임이면 **단원별** 숙련도를 이어받는다(B7) |
| `GET /golden/next?session_id=` | 응답에 `"unit"`·`"answer_kind"`(앱이 입력 안내를 바꾸는 데만 쓴다 — 판정은 서버) 추가. `mixed`면 두 단원을 번갈아 낸다(S46) |
| `POST /golden/answer` | 변경 없음. `pair` 판정은 `grade.py`(B2): 학생 입력 `(3, 1)`·`3, 1`·`x=3, y=1`·`x=3 y=1`을 정규화해 순서쌍으로 읽고 각 성분을 `number` 규칙으로 비교. 순서가 바뀐 `(1, 3)`은 오답 |

*기능 플래그·환경변수(2단계 추가분)*

| 이름 | 뜻 |
| --- | --- |
| `GOLDEN_PROBLEMS_PATH` | (S40 한정 · 임시) 문항 로더 경로 덮어쓰기 — 단원 스위치 전에 연립방정식 720세션을 돌리기 위한 것. S41이 `unit`으로 대체하면 제거 |
| `GOLDEN_GEN_MODEL_A` / `GOLDEN_GEN_MODEL_B` / `GOLDEN_REVIEW_MODEL_A` / `GOLDEN_REVIEW_MODEL_B` | 생성기·검토기 모델 ID(라우터 좌석 이름 — S36 Kiki 확인) |
| `GOLDEN_UNITS` | 서버가 아는 단원 목록(기본 `linear_fn,sys_eq`) — 로더가 읽는 설정(B1을 설정으로 두는 방식 · 제안값) |
| `GOLDEN_FAKE_LLM=1` | 생성기·검토기·튜터·학생 모두 고정 대본(테스트·CI) |

*게이트(S55 · 계획서 §7 — 세션에서 원문 재확인)*

- 질문 1 판정(코드 분기 수 · S41~S43 코드 줄 수 · 세 번째 단원 추정 줄 수) · 질문 2 판정(메트릭 8줄) · 진실 트랙(실학생 수·세션 50건(연립방정식 기준)·완료율) — `VALIDATION_FINAL.md`(S54)가 정본. S55는 그 판정을 §7 표에 옮기고 3단계 초안(세 번째 단원 후보·추상화 범위·첫 세션의 FINDINGS 인용 항목)을 쓴다. 분기 B10 초과 시 즉시 리스크 표.

## 작업 지시: S51. 숙련도 2단원 — BKT 파라미터 연립방정식 값(B6) · 섀도

- **목적:** T3 BKT 파라미터를 단원별 설정으로 분리한다. 코드 분기 없음이 목표.
- **선행 산출물:** S46(단원별 숙련도 표), 1단계 `mastery/bkt.py`·S31 파라미터.
- **할 일:** `golden/mastery_params.yaml`(단원 → 파라미터 4개 · 연립방정식 초깃값은 일차함수 값에서 시작하고 S44·S49 정답률로 Kiki 확인 · 제안값 표기) → `bkt.py`가 `bkt_params(unit)`로 읽는다. **B6(설정)** 줄. 섀도 기록이 두 단원에 쌓이는지 테스트. 코드에 `if unit ==`가 생기면 B8+로 적는다.
- **완료 기준:** ①파라미터 파일 분리·테스트 초록 ②B6 기록 ③코드 분기 0(또는 기록).

## 산출물 저장 규칙

- 이 작업에서 만든 문서, 표, 보고서는 모두 `golden/reports_phase2/S51/`에 저장한다.
- 코드 변경은 저장소의 기존 위치에 하되, git을 쓰는 저장소라면 `golden-p2/S51` 브랜치에서 작업하고 기본 브랜치에 직접 반영하지 않는다.
- 마지막으로 `golden/reports_phase2/S51/보고.md`에 아래 형식의 완료 보고를 쓰고, 같은 내용을 답변으로도 보여준다.

## 완료 보고 형식

```
작업 번호: S51
결과: 완료 | 일부 완료 | 중단
만든 것: 파일·테이블·화면 이름 (경로 포함)
완료 기준 확인: 항목별 통과/실패와 근거 (실행한 명령 또는 본 화면)
미확인·가정한 것: 없으면 "없음"
다음 작업이 알아야 할 것: 없으면 "없음"
```

## 시작 순서

0. 세션 제목을 `DU-단계11-S51-BKT2단원-B6`으로 등록한다("너의 역할"의 첫 행위).
1. 공통 규칙 2번대로 선행 작업의 `보고.md`를 확인한다.
2. "작업 지시"의 할 일을 순서대로 수행한다.
3. "완료 기준"을 하나씩 확인하고 결과를 기록한다.
4. `golden/reports_phase2/S51/보고.md`를 쓰고 보고한다.
