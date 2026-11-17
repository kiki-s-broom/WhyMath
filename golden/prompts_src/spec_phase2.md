# WhyMath 2단계 「두 번째 단원」 — 작업 지시서 (AI 실행용 · 4주)

작업 번호를 받은 AI는 이 문서의 공통 규칙·용어·공유 계약과 해당 번호의 지시만 읽고 작업한다. 지시에 없는 값은 추정하지 않고 "미확인"으로 보고한다. 원본 계획서는 `plan_phase2_second_unit_4weeks.docx`(Kiki 보관 원본(저장소 미포함 — office·PDF 문서는 `.gitignore`와 `scripts/ops/check_source_document_binaries.py`가 커밋을 막는다 · 저장소 안 정본은 지시서))(2026-11-15 · Kiki)이고, 골든 패스(S1~S15 · `golden/prompts/`) → 1단계 두꺼게(S16~S35 · `golden/prompts_phase1/`)의 후속이다. 세션 번호는 S36부터 S55까지 이어 붙인다. **시작 조건: 1단계 S35 게이트의 진실 트랙 세 줄(실학생 3명·50건 / 완료율 70% / 슬롯 둘 효과)이 "예"**다. 아니면 이 묶음을 열지 않는다.

## 공통 규칙과 보고 형식

**공통 규칙**

1. (스크립트가 "읽을 범위" 표준 문장으로 바꾼다)
2. (스크립트가 "선행 작업 확인" 표준 문장으로 바꾼다)
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

**완료 보고 형식**

```
작업 번호: S42
결과: 완료 | 일부 완료 | 중단
인용 FINDINGS: F-xx
만든 것: 파일·테이블·화면 이름 (경로 포함)
완료 기준 확인: 항목별 통과/실패와 근거 (실행한 명령 또는 본 화면)
CONTRACT.md 추가 분기: B_ (없으면 "없음")
미확인·가정한 것: 없으면 "없음"
다음 작업이 알아야 할 것: 없으면 "없음"
```

**용어**

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

**공유 계약**

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

*실학생 대체 결정(Kiki 2026-11-17 · 기록 `golden/reports_phase1/H2/보고.md` 0절 · 1단계 지시서 같은 이름의 블록과 한 쌍) — 이 블록이 아래 다른 절의 "실학생" 문구보다 우선한다*

- **결정:** ①"실 학생 없이 ai로 진행" ②"여기서 발생할 수 있는 문제들은 개방 시점에 보완" ③"추천대로 진행" — AI 대체 판정으로 2단계를 열고 실학생 확인은 개방 시점에 한다 ④"2단계 지시서도 같은 방식으로 고쳐줘". 그러므로 H3(실학생 섭외)는 **중단**이고 S44·S49·S52는 **AI 학생 정독 세션**이다. 실학생 0명이어도 2단계를 멈추지 않는다.
- **AI 대체 세션의 모양(S44·S49·S52 공통 · 1단계 S24와 같다):** Kiki 머신에서 러너(`golden.sim.run`)를 실제 LLM(튜터 OpenRouter · 학생 로컬 Ollama — 시드 반출 금지·학생 LLM 로컬 전용 규칙 그대로)으로 돌리고, `sessions.jsonl`에서 정해 둔 **페르소나 × 문항 5개 × 1회차** 행만 골라 턴마다 손으로 읽는다. 세션 1개 = 문항 1개 풀이 기록 1건. 닉네임은 `sim-<페르소나>-<회차>`이고 `stu-*`는 쓰지 않는다. 단원 지정(`sys_eq`·`mixed`) 옵션은 S40·S46·S47이 러너에 만든 것을 `--help`로 확인해 쓴다(이 지시서는 옵션 이름을 추정하지 않는다).

| 세션 | "학생" 구성 | 문항 | 로그 | 누적 |
| --- | --- | --- | ---: | ---: |
| S44 | P2·P3·P4 | 연립방정식 — 서버가 내는 순서의 처음 5문항 | 15건 | 15 |
| S49 | P2·P3·P4 | 혼합(`mixed`) — 서버가 내는 순서의 처음 5문항 | 15건 | 30 |
| S52 | P2·P3·P4·P5 | 연립방정식 — S44와 겹치지 않는 5문항(난이도 하·중·상이 섞이게 **ID와 난이도만 보고** 고른다) | 20건 | 50 |

- **이름 붙이기:** 결과는 어디에 적든 출처를 **"AI 대체"**로 적고 "실학생"·"진실 트랙"이라 부르지 않는다. 판정에는 "잠정 · AI 대체"를 붙인다. 진실 트랙(실학생 수·50건·완료율)은 VALIDATION_FINAL·게이트 문서에 **"미실시(Kiki 결정 2026-11-17 · AI 대체)"**로 적고 AI 숫자를 넣지 않는다. AI 대체 누적은 별도 줄이다.
- **결함 문항 후보를 찾는 법(사람 발화 "문제가 이상해요" 대신):** ⓐ판정이 주입기가 아는 정오와 다른 문항(M3) ⓑ튜터 발화가 문제의 조건을 고쳐 말하거나 모순을 짚은 문항 ⓒ정독하는 AI 세션이 그 문항을 직접 풀어(sympy) 등록된 답과 다르거나 해가 유일하지 않은 문항. 근거 로그 줄을 함께 적는다.
- **AI 대체로는 말할 수 없는 것:** 난이도별 **학생** 정답률(메트릭 「정답률 분포」) · 이탈률·세션 길이·만족도 · 단원 전환 때 학생의 반응 · "문제가 이상해요" 발화. 메트릭 「정답률 분포」는 **"측정 불가(개방 시점 보완)"**로 적고 `F-Q2` 판정에서 뺀다 — 페르소나별 정답률은 페르소나 설계(P3는 주입기가 틀리게 만들고 P5는 맞히게 만든다)가 정하는 값이라 문항 난이도의 증거가 아니다. 참고값으로 P2·P4의 난이도별 정답률만 따로 적는다.
- **개방 시점에 보완할 목록(1단계 목록에 더한다):** ①실학생 3명 이상·연립방정식 50건·완료율 ②난이도별 학생 정답률(일차함수 대비 ±15%p) ③실학생이 드러내는 결함 문항 ④혼합 세션에서의 단원 전환 반응.

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
| 정답률 분포 | 난이도별 실학생 정답률이 일차함수 같은 난이도와 ±15%p 안 — **실학생 대체 결정 뒤: "측정 불가(개방 시점 보완)"** · P2·P4 난이도별 정답률을 참고값으로만 | 3개 난이도 모두(판정에서 제외) | S50 |
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

- 질문 1 판정(코드 분기 수 · S41~S43 코드 줄 수 · 세 번째 단원 추정 줄 수) · 질문 2 판정(메트릭 8줄) · 진실 트랙(실학생 수·세션 50건(연립방정식 기준)·완료율 — **"미실시(Kiki 결정 2026-11-17 · AI 대체)"**로 적고 AI 대체 누적 50건은 별도 줄) — `VALIDATION_FINAL.md`(S54)가 정본. 3단계 진행 판정은 질문 1·2로 하며 진실 트랙 미실시는 3단계를 막지 않는다. S55는 그 판정을 §7 표에 옮기고 3단계 초안(세 번째 단원 후보·추상화 범위·첫 세션의 FINDINGS 인용 항목)을 쓴다. 분기 B10 초과 시 즉시 리스크 표.

## S36~S40 · H3: 문항 파이프라인 (8주차)

스펙(S36) → 생성(S37) → 검증(S38) → 불일치 검토·확정(S39)은 직선이다. S40(새 단원 AI 회귀)과 S41(단원 스위치 설계)은 둘 다 S39의 30문항만 기다리므로 **동시에** 갈 수 있다. H3(실학생 섭외)는 2026-11-17 결정으로 중단이다(공유 계약 「실학생 대체 결정」).

### S36. 단원 확정·문항 스펙·오개념 추출 — 코드 없음

- **목적:** 파이프라인의 입력 하나(스펙)와 데이터 하나(오개념)를 만든다. 2단계의 번호 체계(하네스 태스크·`F-Q1`·`F-Q2`)와 분기 장부 머리도 만든다. 오늘 문항은 한 개도 쓰지 않는다.
- **선행 산출물:** 1단계 전부(S35 판정 go — 게이트 ③~⑥ 기준 · ①②는 "미실시"이며 2단계를 막지 않는다: Kiki 결정 2026-11-17). 특히 `golden/FINDINGS_v2.md`·`CALIBRATION.md`·`src/backend/golden/sim/`·`eval/`·`mastery/`.
- **할 일:**
  1. **1단계 산출물 실측:** 공유 계약 「1단계가 남겼다고 가정하는 골든 코드」 표의 파일을 하나씩 `ls`·`grep`으로 확인해 보고 첫 절에 표로 적는다(있음/없음/다름). 없는 것이 있으면 멈추고 보고한다.
  2. **하네스 등재:** `python3 scripts/harness/backlog.py add`로 2단계 태스크 1건(제안 제목: "GOLD-P2 2단계 두 번째 단원 — 연립일차방정식 파이프라인 + 단원 스위치 + 분기 장부 · S36~S55"). CLI가 준 번호로 `start`. `golden/STATE.md`「하네스 태스크 ID」에 "2단계: <번호>".
  3. **단원 확정:** 기본값 중2 연립일차방정식. 바꾸려면 계획서 §0의 근거(답 유형이 달라져 분기가 드러나고, 같은 학년이라 프롬프트는 재사용된다)를 반박하는 한 문단을 먼저 쓴다. 반박이 없으면 기본값.
  4. **성취기준:** `data/corpus/achievement_criteria_v1/achievement_criteria.json`·`standards_v1/standards.json`에서 연립일차방정식 코드 2~3개와 원문을 찾는다(사전 실측 후보 `[9수02-13]`·`[9수02-18]`). 못 찾으면 `[확인 필요]`.
  5. **저작권 체크리스트:** `docs/data/licensing_safety.md` 「저작권 가이드 v2.0」·「절대 금지 목록」에서 **문항 텍스트에 걸리는** 규칙만 5줄 이내로 추출해 `forbidden`에 적는다. 가이드 전체를 요약하지 않는다.
  6. **오개념 추출:** `misconceptions.json`에서 연립방정식 계열(사전 실측 4건) + 연립방정식 풀이에서 그대로 나는 선행 오개념(일차방정식 3건·분배 2건)을 골라 `golden/data/misconceptions_sys_eq.json`(필드: 1단계 `misconceptions_lf.json`과 같게 + `wrong_answer_rule` 한 줄 — S40 주입기가 읽는다)으로 쓴다. **N건을 센다.** 10~20에 못 미쳐도 만들어 채우지 않는다.
  7. **스펙:** `golden/content/spec_sys_eq.yaml`을 공유 계약 표대로. `spec_version: 1`.
  8. **FINDINGS 번호:** `golden/FINDINGS_v2.md` 끝에 `## 2단계 항목 번호 (S36)` 절 — `F-Q1`·`F-Q2`와 1단계 번호 체계 유지 선언. 본문 무변경.
  9. **분기 장부 머리:** `golden/CONTRACT.md` — 형식 설명 + 예상 분기 B1~B7 표(종류 열은 "예상") + 빈 본문. 아직 분기 0.
  10. **모델 좌석 확인(Kiki):** 생성기 2·검토기 2에 쓸 좌석(OpenRouter 모델 2종·로컬 Ollama·Anthropic 재개 여부)을 Kiki에게 물어 `golden/content/MODELS.md`에 적는다. 답이 없으면 제안값(생성 A = `cloud_mid` 좌석, 생성 B = 로컬 Ollama 확정 모델, 검토 A = `cloud_high` 좌석, 검토 B = 로컬 다른 모델)으로 두고 "제안값"을 표기.
- **산출물:** `spec_sys_eq.yaml`, `misconceptions_sys_eq.json`(N건), `CONTRACT.md` 머리, `FINDINGS_v2.md` 번호 절, `MODELS.md`, STATE.md 태스크 ID, 1단계 실측 표.
- **완료 기준:** ①스펙에 성취기준 2~3개(또는 `[확인 필요]`)·난이도 8/14/8·`answer_type: pair`·`forbidden` 5줄 이내 ②오개념 N건과 각 항목의 `wrong_answer_rule` ③CONTRACT.md에 B1~B7 예상 표 ④`F-Q1`·`F-Q2` 등재 ⑤1단계 산출물 실측 표에 "없음" 0건.
- **하지 말 것:** 문항 예시를 어디에도 쓰지 않는다(스펙·오개념 규칙·보고 모두). 코드를 쓰지 않는다. 오개념을 "만들어" 채우지 않는다.
- **막히면:** 1단계 산출물이 없으면 멈춘다(이 묶음의 시작 조건 미충족). 성취기준 원문을 못 찾으면 `[확인 필요]`로 진행.

### H3. 실학생 3명 이상 섭외 (Kiki) — 1단계 참여 학생 우선

- **상태(2026-11-17): 중단.** Kiki 결정 "실 학생 없이 ai로 진행"·"2단계 지시서도 같은 방식으로"로 이 작업은 하지 않는다. S44·S49·S52는 H3를 선행으로 요구하지 않는다. 아래는 개방 시점에 섭외를 다시 열 때를 위한 원래 지시다(섭외 문구: `golden/reports_phase1/H2/섭외_키트.md`).
- **목적:** S44·S49·S52 진실 트랙. 난이도 3등급별 정답률을 일차함수와 비교하려면 등급당 15회 이상 시도가 필요해 누적 50건이다.
- **선행 산출물:** 없음(1단계 H2 명단).
- **할 일:** 1단계 H2와 같은 절차(20분·보상·보호자 동의·가명만). 1단계 참여 학생을 우선 다시 부른다. 일정: S44 전 3명, S49 전 3명, S52 전 4명. 섭외가 어려우면 둘(25·25)로 합쳐도 된다 — 그러면 세션 하나(S52)가 S48 재생성 라운드로 돌아간다(계획서 §2). `golden/reports_phase2/H3/보고.md`에 표.
- **완료 기준:** S44 전 3명 확정. 실명·연락처 미저장.
- **막히면:** 2명 미만이면 세션 크기 축소 + GATE 문서 "축소" 표기. 0명이면 2단계 정지.

### S37. 생성기 — src/backend/golden/content/generate.py · 후보 90개

- **목적:** 모델 둘이 같은 스펙에서 각 45개 후보를 만든다. 둘을 쓰는 이유는 품질이 아니라 **독립성**이다(한 모델의 암기 재현을 다른 모델이 상쇄하고 V3가 잡는다).
- **선행 산출물:** S36 스펙·오개념·MODELS.md.
- **할 일:**
  1. `content/__init__.py`·`spec.py`(yaml 로더 · `spec_version` 포함 · 스펙 해시) · `generate.py`: `generate(spec, model_seat, n) -> list[Candidate]`. 프롬프트는 **스펙을 그대로 넣고 출력 형식만 지정**한다(공유 계약 후보 JSON 모양). 예시 문항 금지. `forbidden` 5줄과 `style`을 그대로 넣는다. 오개념 ID 목록과 `wrong_answer_rule`은 넣되 "디스트랙터 유효"를 위한 것임을 적는다.
  2. LLM 호출은 공통 규칙 9(팩토리/라우터·Ollama 경유). 호출마다 타임아웃 60초·재시도 1회. 응답 JSON 파싱 실패는 후보 폐기 + 사유 기록(침묵 금지).
  3. 후보마다 기록: `gen_model`·`spec_version`·`prompt_hash`(시스템+사용자 프롬프트 sha256 앞 12자)·`generated_at`·`difficulty`(모델이 라벨)·`misconception_ids`. 모델 A 45개·B 45개 → `golden/content/candidates.jsonl`(한 줄씩 즉시 flush).
  4. 가짜 모드: `GOLDEN_FAKE_LLM=1`이면 결정론 생성기(스펙의 난수 시드로 계수를 뽑아 `equations`·`answer`를 만들고 `stem`은 정형구 "다음 연립방정식을 푸시오" + LaTeX)가 45개를 낸다 — 파이프라인 테스트용이지 문항 후보가 아니다(사이드카 `generation_method`에 "fake"로 구분).
  5. 테스트 `tests/golden/test_content_generate.py`: 가짜 모드 ①45개·필드 전부 ②`prompt_hash`가 스펙이 바뀌면 달라진다 ③프롬프트 문자열에 예시 문항 패턴(`예를 들어`·`예시:`·숫자가 든 완성 문장 2개 이상)이 없다(주입: 예시를 넣은 프롬프트로 RED) ④파싱 실패 응답이 사유와 함께 폐기된다.
  6. 실제 실행(Kiki 머신 또는 키가 있는 환경): 두 모델 각 45개. 토큰·비용·소요 시간을 보고에 적는다.
- **산출물:** `content/spec.py`·`generate.py`, `candidates.jsonl`(90개), 테스트, 비용 기록.
- **완료 기준:** ①후보 90개(45+45)에 생성 모델·스펙 버전·프롬프트 해시·시각이 전부 있다 ②프롬프트에 예시 문항 0건(테스트) ③`tests/golden` 초록 ④두 모델이 다르다(`gen_model` 값 2종).
- **하지 말 것:** 후보를 읽고 "좋은 것"을 골라내지 않는다(그것은 V1~V4의 일). 프롬프트에 교과서 문체 예시·기출 수치를 넣지 않는다. 후보를 손으로 고치지 않는다.
- **막히면:** 한 모델이 45개를 못 내면(파싱 실패 다수) 낸 만큼만 기록하고 S38로 넘긴다 — 수율 분모가 그만큼 작아진다.

### S38. 검증기 — src/backend/golden/content/verify.py · verify_report.json

- **목적:** 후보 90개를 4단 검증으로 합의 통과·불일치·탈락 세 묶음으로 나누고 수율을 찍는다. V1·V3의 규칙 일부는 옛 `acceptance.py`에서 다섯 걸음으로 가져온다(한 세션 자산 하나 — 이 세션은 `_evaluate_latex`·`_evaluate_hygiene` 두 함수).
- **선행 산출물:** S37 `candidates.jsonl`.
- **할 일:**
  1. 옛 자산 경계(5걸음 ①②): `whymath_backend/l3/equivalent/acceptance.py`의 `_evaluate_latex(candidate)`·`_evaluate_hygiene(...)`를 읽어 V1에 쓸 수 있는지 판단. 쓰면 `tests/golden/characterization/test_v1_legacy.py`에 입력 10 → 출력 10 고정 후 import(의존 3개 초과면 `content/legacy_checks.py`로 복사). HARVEST.md 줄. 못 쓰면 "버림: 입력 타입 불일치"로 적고 규칙을 새로 쓴다.
  2. `verify.py`: `v1_schema`·`v2_math`(계획서 §3-4 — `sympy.solve(dict=True)` 해 1개·분모 ≤5·`answer` 일치)·`v3_copyright`(`forbidden` 정규식 · 상황문 4-gram 자카드 ≥0.6 쌍 둘 다 탈락 · 두 모델 사이 계수·상수 조합 완전 일치 탈락 · 제안값: 부등식 은행 600건 상황문과의 유사도)·`v4_review(cand, reviewer_seat) -> dict[str,int]`(루브릭 5항목 0/1). 각 단계는 (통과 목록, 탈락 사유 목록). 앞 단계 탈락이면 뒤를 돌리지 않는다(비용).
  3. 검토기 모델 2개는 생성기와 **다른** 모델(MODELS.md). 검토 프롬프트에도 예시 문항 금지. 둘 다 5/5 → 합의 통과 · 둘 다 ≤3 → 탈락 · 그 외 → 불일치.
  4. `verify_report.json`(공유 계약 모양) + `golden/content/review_queue.md`: 불일치 문항 전문 + 두 검토기 채점표 + 어긋난 항목만 굵게. **S39에서 Kiki는 이것만 본다.**
  5. 가짜 모드: V4 검토기 대본(결정론 — cand_id 해시로 5/5·3/5·2/5 배분). 테스트 `tests/golden/test_content_verify.py`: V1 긍정/부정 각 3 · V2 해 2개·분모 6·answer 불일치 각 1 → 탈락 사유 · V3 유사 쌍 주입 → 둘 다 탈락 · V4 세 묶음 분류 경계(5/5·4/5·3/3) · 앞 단계 탈락이면 V4 호출 0회(호출 카운터 단언).
  6. 실제 실행: 90개 → 보고에 세 묶음 크기·단계별 탈락 수·가장 많이 탈락한 단계·수율·자동 통과율·불일치율·토큰. 합의 통과가 30을 넘으면 난이도 8/14/8을 맞춰 고를 수 있는지도.
- **산출물:** `verify.py`, 특성화 테스트(쓴 경우), `verify_report.json`, `review_queue.md`, 테스트, HARVEST 줄.
- **완료 기준:** ①세 묶음과 단계별 탈락 수·수율·자동 통과율·불일치율·토큰이 report에 있다 ②`review_queue.md`에 불일치 문항만 ③테스트 초록(V4 미호출 단언 포함) ④옛 자산 결정(가져옴/버림)이 HARVEST.md에 있다.
- **하지 말 것:** 탈락 문항을 "조금 고치면 살릴 수 있다"고 제안하지 않는다. 탈락은 탈락이다. 임계값(0.6·3 이하)을 수율 때문에 바꾸지 않는다. 검토기에 생성기 모델을 쓰지 않는다.
- **막히면:** 합의 통과 + 불일치가 30 미만이면 S37을 **프롬프트 수정 없이** 한 번 더 돌리고(후보 180) 두 실행을 report에 구분한다. 두 번 돌려도 모자라면 그것이 결과다.

### S39. 불일치 검토·30개 확정 — problems_sys_eq.json (관문 ①)

- **목적:** Kiki가 불일치 묶음만 30분 상한으로 보고, 합의 통과 + 살린 불일치에서 난이도 8/14/8로 30개를 확정한다. 파이프라인 첫 회차의 수율·검토 시간·비용을 CONTENT_REPORT에 적는다.
- **선행 산출물:** S38 `review_queue.md`·`verify_report.json`.
- **할 일:**
  1. (Kiki) `review_queue.md`를 읽고 문항마다 살림/탈락만 표시한다. **시작·종료 시각을 적는다**(검토 시간 메트릭). 30분이 지나면 남은 것은 탈락. 문항 본문을 고치지 않는다.
  2. (AI) `content/review.py`: Kiki 판정 파일(`review_queue.md`의 표시)을 읽어 통과 집합을 만들고, 합의 통과 → 살린 불일치 순으로 난이도 8/14/8을 채워 30개를 고른다(같은 난이도 안에서는 `cand_id` 순 — 사람 선호 배제). `golden/data/problems_sys_eq.json`(공유 계약 문항 모양 · `SE-01`~`SE-30`)과 `_provenance.json` 사이드카를 쓴다.
  3. **30개 각각 sympy 재검산**(V2를 확정 파일에 다시 돌린다 · `equations`→`answer` 일치) — `tests/golden/test_problems_sys_eq_schema.py`로 동결(30개·ID 중복 없음·`answer_kind=pair`·`answer` 형식 `(a, b)`·`equations` 2개·`hint1`에 정답 성분 미포함·난이도 분포 8/14/8·`source`가 `pipeline:`으로 시작).
  4. `golden/content/CONTENT_REPORT.md` 초안: 1회차 수율·자동 통과율·불일치율·검토 시간(분)·비용(토큰·달러·세션 수)·탈락 단계 분포·모델별 통과율(A vs B).
  5. 30개가 안 채워지면 S38 "막히면"대로 재생성 1회. 그래도 모자라면 채워진 수로 확정하고 CONTENT_REPORT에 "미달 N개"와 원인 1줄(스펙 완화 금지).
- **산출물:** `review.py`, `problems_sys_eq.json`(30개) + 사이드카, 스키마 테스트, CONTENT_REPORT 초안, Kiki 검토 시간 기록.
- **완료 기준:** ①30개(또는 미달 수 명시)·sympy 재검산 전부 통과 ②난이도 8/14/8 ③Kiki 검토 시간(분)이 기록 ④스키마 테스트 초록 ⑤판정: **go**(30개 확정) / **go(미달)**(수와 원인 명시 — 2단계는 계속한다) / **no-go**(검토 미실시).
- **하지 말 것:** 손으로 문항을 쓰거나 고치지 않는다. 난이도 라벨을 분포에 맞추려고 바꾸지 않는다(라벨이 틀렸으면 V4 불일치로 돌아간 것이다).

### S40. AI 회귀 (새 단원) — 주입기 연립방정식 규칙(B5) · 720세션

- **목적:** 1단계 시뮬레이터로 연립방정식 30문항에 720세션을 돌려 M1~M5와 결함 문항(0~3개)을 뽑는다. 주입기에 연립방정식 오개념 규칙을 더하는 것이 **첫 코드 분기 후보(B5)**다.
- **선행 산출물:** S39 30문항·`misconceptions_sys_eq.json`, 1단계 `sim/`·`CALIBRATION.md` 통과, S20 보정.
- **할 일:**
  1. 단원 스위치(S41) 전이므로 문항 로더를 환경변수 `GOLDEN_PROBLEMS_PATH`로 임시 덮어쓴다(`problems.py` 한 줄 — 이것도 분기다: 보고에 "B1 첫 흔적"으로 적고 S41이 `unit`으로 대체·제거한다).
  2. `sim/errors.py`에 연립방정식 규칙 표를 더한다 — `misconceptions_sys_eq.json`의 `wrong_answer_rule`을 읽어 `(x, y)` 틀린 답을 결정적으로 만든다(예: 한 식만 대입 → 한 식만 만족하는 순서쌍 · 이항 부호 → 부호 바뀐 해 · 평행 판별 누락 → "해 없음" 문항에 임의 순서쌍). **단원별 규칙 테이블을 읽는 구조**로 짜되 지금은 일차함수 표와 연립 표 두 딕셔너리다. 같은 입력 → 같은 틀린 답(테스트). `CONTRACT.md`에 B5 줄(커밋 해시 포함).
  3. 페르소나 8종은 그대로(말투·규칙 공통). P3의 주입 오개념만 단원 표에서 고른다. `grade.py`가 아직 `pair`를 못 읽으므로 M3(판정 오류)는 이 세션에서 **전건 오류**로 나올 것이다 — 그것이 B2의 증거이며 고치지 않는다(S42). M1·M2·M4·M5만 해석하고 M3는 "B2 전"으로 표기.
  4. Kiki 머신에서 `SIM_FULL=1 ... --sessions 720`(실제 LLM). 결과 `sim_report.json`을 `golden/reports_phase2/S40/`에. 결함 문항 후보: 3턴 모두 튜터가 문제 자체를 되묻거나(중의성) sympy 해와 `answer`가 다르다고 보이는 것(답 오류) 0~3개를 **목록만** 적는다(교체는 S48).
  5. 테스트 `tests/golden/test_sim_errors_sys_eq.py`: 연립 규칙 결정성·30문항 × 오개념 N에서 정답과 같은 출력 0건·일차함수 규칙 회귀 없음(1단계 테스트 그대로 초록).
- **산출물:** `errors.py` 연립 규칙, CONTRACT.md B5(+B1 흔적 메모), 720세션 보고서, 결함 문항 목록, 테스트.
- **완료 기준:** ①720세션 M1·M2·M4·M5 숫자(M3는 "B2 전") ②결함 문항 0~3개 목록 ③B5가 CONTRACT.md에 있다 ④`tests/golden` 초록(1단계 테스트 포함).
- **하지 말 것:** `grade.py`를 고치지 않는다(S42). 결함 문항을 고치지 않는다(S48). 튜터 프롬프트를 고치지 않는다.

## S41~S45: 단원 스위치와 분기 세기 (9주차)

S41은 빨간불이 목표다(연립방정식 e2e가 GP-5에서 실패해야 B2의 증거). S42가 초록으로, S43이 튜터·오개념 분기를 적고 두 단원 스모크를 초록으로 만든 뒤 AI 학생 1차(S44 — 실학생 대체)·판정(S45).

### S41. 단원 스위치 설계 — session.unit · 로더 파라미터화 · e2e parametrize(빨강)

- **목적:** 골든 패스가 단원을 받게 만들되 코드 변경을 최소로 하고 모든 분기를 장부에 적는다. 오늘 e2e는 **연립방정식 쪽이 빨간불이어야 정상**이다.
- **선행 산출물:** S39 30문항, S36 CONTRACT.md 머리.
- **할 일:**
  1. `store.py`: `golden.sessions`에 `unit` 열(기본 `linear_fn`) — `create_all`이 새 열을 기존 표에 더하지 못하므로 시작 시 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`를 `ensure_schema()`에 더한다(Alembic 리비전은 쓰지 않는다 — 1단계 계약과 같다). `POST /golden/session`이 `unit`을 받고 응답에 돌려준다. `GOLDEN_UNITS` 밖의 값은 422.
  2. `problems.py`: `load_problems(unit)`·`problems_path(unit)` — 단원 → 파일 경로 매핑은 **설정(딕셔너리/환경변수)**으로 둔다. S40의 `GOLDEN_PROBLEMS_PATH` 임시 코드를 제거한다. **B1** 줄을 CONTRACT.md에(종류: 데이터 또는 설정 — 실제 구현대로).
  3. `GET /golden/next` 응답에 `unit`·`answer_kind`를 더한다. `api.py`의 `answer()`는 아직 `pair`를 모른다 — 건드리지 않는다.
  4. `tests/golden/test_golden_path.py`를 두 단원으로 parametrize한다(`unit="linear_fn"` 초록 · `unit="sys_eq"`는 정답 `_test_answer`가 `(3, 1)` 꼴이라 GP-5에서 실패). 그 실패가 B2의 증거다. CI `golden-path` 잡이 빨강이 되는 것도 의도다 — PR 본문에 "S41: sys_eq e2e 빨강이 목표"를 적고 **머지하지 않는다**(S42가 같은 브랜치에서 초록으로 만든 뒤 함께 머지).
  5. `git diff --stat origin/main -- src/backend/golden src/mobile/lib/golden`에서 `.py`·`.dart`만 세어 CONTRACT.md 하단 "S41 변경 줄 수"에 적는다(데이터·설정 파일 제외).
  6. 오늘 발견한 분기를 전부 적는다. 예상 목록에 없으면 B8부터.
- **산출물:** `store.py`·`problems.py`·`api.py`(session·next만) 변경, e2e parametrize, CONTRACT.md B1(+발견분), 변경 줄 수.
- **완료 기준:** ①e2e가 일차함수 초록·연립방정식 **빨강**으로 뜬다 ②CONTRACT.md에 B1과 S41 변경 줄 수 ③일차함수 쪽 모든 테스트가 그대로 초록(회귀 없음) ④정적 검사 4종 초록.
- **하지 말 것:** 빨간불을 오늘 초록으로 만들지 않는다. 오늘 초록이 됐다면 `pair` 판정이 어딘가에 이미 있다는 뜻이니 그 위치를 찾아 CONTRACT.md에 적고 멈춘다. 앱(Flutter)을 고치지 않는다(S43 또는 S46에서 입력 안내만).

### S42. 판정 분기 — grade.py 답 유형 pair(B2) · 두 단원 e2e 초록

- **목적:** `answer_kind == "pair"` 비교기를 더해 두 단원 e2e를 모두 초록으로 만든다. 일차함수 판정은 바이트 하나 바뀌지 않아야 한다(특성화 테스트).
- **선행 산출물:** S41(빨강 e2e).
- **할 일:**
  1. 특성화 테스트(5걸음 ②를 자기 코드에): `tests/golden/characterization/test_grade_linear_fn_frozen.py` — 1단계 로그에서 뽑은 학생 입력 30개(정답 15·오답 15 · 사람 출처 CSV의 실제 문자열)에 대한 지금 `is_correct` 결과를 **먼저** 고정한다.
  2. `grade.py`: `_parse_pair(text) -> tuple[Expr, Expr] | None`(정규화: 괄호 유무·쉼표/공백 구분·`x=3, y=1`·`x=3 y=1`·전각 쉼표·`−`) + `_same_pair(student, answer)`(각 성분 `_same_number` · 순서 고정). `is_correct`에서 `answer_kind == "pair"` 분기 — **CONTRACT.md에 B2(코드)** 줄. 기존 접두·꼬리 떼기(`답:`·`요`·마지막 `=` 뒤 규칙)는 pair에도 그대로 적용되는지 확인(`x=3, y=1`은 마지막 `=` 규칙과 충돌 — pair 파싱을 먼저 시도하고 실패하면 기존 경로).
  3. 테스트 `tests/golden/test_grade_pair.py`: 정답 표기 8종·오답 5종(순서 바뀜·성분 하나만·`3`·빈 입력·`(3, 1, 2)`)·파싱 불가 → False + 예외 타입명 로그. 특성화 30개 불변.
  4. e2e 두 단원 초록. S40 720세션 보고서의 M3를 재계산(`grade.py`만 바꿨으므로 세션 재실행 없이 jsonl의 학생 입력을 재채점)해 M3 숫자를 적는다.
  5. CONTRACT.md 하단 "S42 변경 줄 수".
- **산출물:** `grade.py` pair 비교기, 테스트 2파일, CONTRACT.md B2, M3 재계산.
- **완료 기준:** ①두 단원 e2e 초록 ②특성화 30개 불변 ③M3(재채점) 숫자 ④B2가 코드 분기로 기록.
- **하지 말 것:** 일차함수 판정 로직을 "이왕이면" 정리하지 않는다. `answer_kind`를 3개 넘게 늘리지 않는다.

### S43. 튜터·오개념 분기 — 단원 용어 블록(B3) · misconceptions_sys_eq 연결(B4) · 스모크 120 × 2단원

- **목적:** 튜터 프롬프트에 단원 용어 블록을, T2 오개념 매칭에 연립방정식 파일을 연결한다. 둘 다 **설정·데이터 분기**여야 정상이다. 야간 스모크를 두 단원에 돌린다.
- **선행 산출물:** S42, S40(주입기 연립 규칙), 1단계 `eval/misconception.py`·`tutor.py`.
- **할 일:**
  1. `tutor.py` `build_user_prompt`에 `unit_glossary(unit)` 문자열(일차함수: 기울기·절편·대입 / 연립방정식: 가감법·대입법·순서쌍·두 식 모두 만족). 시스템 프롬프트 `tutor_prompt.md`는 손대지 않는다. 용어 블록은 `golden/tutor_glossary.yaml`(설정) — **B3(설정)** 줄.
  2. `eval/misconception.py`: `misconceptions_path(unit)` — **B4(데이터)** 줄. 매칭 규칙이 단원별로 갈라지면 그것은 코드 분기 B8이다(적는다).
  3. 1단계 `golden-sim-nightly.yml`(골든 소유 파일)에 연립방정식 120세션 스텝을 추가(가짜 모드 · `--unit sys_eq`). `sim/run.py`에 `--unit` 인자(세션 생성 시 `unit` 전달) — 분기인가? 러너가 단원을 전달만 하면 분기가 아니다. 단원별로 다른 동작이 있으면 적는다.
  4. 가짜 모드 스모크 120 × 2단원 초록(M4·M5 0). Kiki 머신 실제 120 × 2 결과를 보고에.
  5. 앱: `lib/golden/`에 `answer_kind == "pair"`일 때 입력 안내 문구("x, y 순서로 쉼표로 구분해 입력")만 추가 — 판정 로직 없음. `flutter analyze`·`flutter test` 초록. 이것도 분기인가? 표시 문구는 서버 `answer_kind`를 읽는 데이터 분기 — CONTRACT.md에 B9로 적을지 판단(제안: 적는다 · 종류 "데이터").
  6. CONTRACT.md 하단 "S43 변경 줄 수" + S41~S43 합계.
- **산출물:** `tutor_glossary.yaml`, B3·B4(+B8·B9) 줄, 워크플로 스텝, 러너 `--unit`, 앱 입력 안내, 스모크 보고 2단원.
- **완료 기준:** ①스모크 120 × 2단원 초록(가짜) + 실제 숫자 ②B3·B4 기록 ③S41~S43 코드 줄 수 합계가 CONTRACT.md에 ④`tests/golden`·`flutter test` 초록.
- **하지 말 것:** 시스템 프롬프트 수정 금지(튜터 개정은 정독 세션 직전 1회 원칙 — 이번 단계는 개정 세션이 없다). 오개념 DB 전체 로딩 금지.

### S44. AI 학생 1차 — 페르소나 3종 × 연립방정식 5문제 = 로그 15건 (실학생 대체)

- **목적:** 새 단원을 AI 학생 3종(P2·P3·P4)이 푼 기록 15건을 턴마다 손으로 읽는다. 원래는 실학생 3명의 자리였다(공유 계약 「실학생 대체 결정」). S40의 720세션이 숫자로 본 것을 대화 내용으로 보고, 결함 문항 후보를 찾는다.
- **선행 산출물:** S43 머지. H3는 선행이 아니다.
- **할 일:**
  1. (Kiki) Kiki 머신에서 러너를 실제 LLM으로 돌린다(단원 `sys_eq` · `--personas P2,P3,P4` · 날짜 꼬리표 `<날짜>-s44` · 가짜 모드 아님). 단원·세션 수 옵션은 러너 `--help`에서 확인한다. S43 뒤에 실제 LLM으로 돈 실행이 이미 있으면 그 `sessions.jsonl`을 써도 된다(같은 코드·같은 프롬프트일 때만 — 어느 쪽인지 보고에 적는다).
  2. (Kiki → AI 세션) `sessions.jsonl`에서 P2·P3·P4 × 서버가 내는 순서의 처음 5문항 × 1회차 행 15건을 골라 전달한다(gitignore · 커밋 금지). 내용을 보고 고르지 않는다.
  3. (AI 세션) 조건 확인: 건수 15 · 페르소나 3종 × 문항 5개 · `http_status` 2xx · 문항 ID가 `SE-`로 시작 · 가짜 모드 아님. 안 맞으면 판정하지 않고 보고한다.
  4. (AI 세션) `golden/reports_phase2/S44/보고.md`. 첫 줄 "출처: AI 대체(P2·P3·P4) · 실학생 0명 · Kiki 결정 2026-11-17". 내용: 페르소나별 문제 표(문항 ID·난이도·턴 수·판정·`injected_op`), 되묻기 루브릭 C1~C5 손 판정(튜터 턴마다 인용), 끊김 4종 태깅, AI 완료율, **결함 문항 후보**(공유 계약 블록의 ⓐⓑⓒ — 5문항은 전부 직접 풀어 ⓒ를 확인한다 · 0건이어도 "0건"), P2·P4의 난이도별 정답률(참고값).
  5. 사람 세션에만 있던 항목(관찰 기록·"문제가 이상해요" 발화·난이도별 학생 정답률)은 "개방 시점 보완"으로 적고 지어 쓰지 않는다.
- **산출물:** 로그 15건(Kiki 머신·gitignore), 보고(페르소나별·결함 후보).
- **완료 기준:** ①페르소나 3종 × 5문제 = 15건(조건 확인 통과) ②루브릭 손 판정이 턴마다 인용과 함께 ③결함 문항 후보 목록(0건이어도 "0건")과 5문항 직접 풀이 대조 ④보고 첫 줄 "AI 대체" 출처.
- **하지 말 것:** 세션 중 코드·프롬프트·문항 수정 금지. 가짜 모드 결과로 판정하지 않는다. 결과를 "실학생"이라 부르지 않는다. 시드 발화를 보고·채팅에 붙이지 않는다. 로그 커밋 금지.
- **막히면:** Kiki 머신에서 실제 LLM 실행을 못 하면 판정하지 않고 멈춘다(가짜 모드로 대신하지 않는다). 조건에 맞는 행이 15건보다 적으면 있는 만큼 판정하고 "축소: N건".

### S45. 1차 판정·분기 집계 — FINDINGS_v2 갱신 · S41~S43 diff 줄 수 (관문 ②)

- **목적:** AI 대체 1차 로그(S44)와 S40 회귀로 결함 문항을 확정(S40·S44 합산)하고 결함률 첫 숫자를 낸다. S41~S43의 코드 변경 줄 수와 분기 수를 정리한다.
- **선행 산출물:** S44, S40 결함 목록, CONTRACT.md.
- **할 일:**
  1. 결함 문항 확정: S40(AI 720 회귀)·S44(AI 대체 정독) 후보를 합쳐 중복 제거, 문항마다 결함 종류(답 오류·중의성·풀 수 없음)와 근거 로그 줄. 결함률 = 결함 ÷ 30(목표 10% 이하).
  2. `git diff --stat <S40 머지 커밋>..<S43 머지 커밋> -- src/backend/golden src/mobile/lib/golden`에서 `.py`·`.dart` 줄 수 → CONTRACT.md "S41~S43 코드 변경 줄 수"(확정). 분기 수(ID별 종류 잠정 분류).
  3. `golden/FINDINGS_v2.md`에 `## 2단계 1차 판정 (S45)` 절: 결함률("AI 대체 기준 · 실학생이 드러낼 결함은 개방 시점 보완" 표기)·P2·P4 난이도별 정답률(참고값 — 일차함수 1단계 AI 대체의 같은 페르소나 수치와 나란히)·끊김 4종(1단계 정의 그대로)·`F-Q1` 잠정 분기 수·`F-Q2` 잠정 결함률.
  4. 결함 문항을 **고치지 않는다** — S48 재생성 목록으로 넘긴다.
- **산출물:** FINDINGS_v2 절, CONTRACT.md 줄 수·분기 수, 재생성 목록(S48 입력).
- **완료 기준:** ①결함률 숫자와 문항 목록 ②S41~S43 코드 줄 수 ③분기 수와 잠정 분류 ④판정: **go**(판정 완료 — 결함률이 높아도 go, 재생성으로 간다).
- **하지 말 것:** 문항 수정 금지. 분기를 "정리"하지 않는다(세기만).

## S46~S50: 혼합 세션과 재생성 (10주차)

S46(혼합 세션·단원별 숙련도) 뒤에 S47(AI 전체 회귀 1,440)·S48(결함 재생성)·S51(BKT 2단원 파라미터)은 서로 독립이라 **동시에** 갈 수 있다. S49 AI 학생 2차(실학생 대체)는 S47·S48이 끝난 뒤, S50이 콘텐츠 중간 판정.

### S46. 혼합 세션 — GET /golden/next 단원 선택 · 숙련도 단원별 분리(B7)

- **목적:** 한 세션에서 두 단원 문제가 번갈아 나오고 숙련도가 단원별로 쌓인다.
- **선행 산출물:** S45.
- **할 일:**
  1. `store.py`: `golden.students`의 숙련도를 단원별로 — 새 표 `golden.student_units(nickname, unit, mastery, attempts, updated_at)`(복합 키) 또는 기존 표에 `unit` 열 + 복합 키. 기존 일차함수 값은 `unit='linear_fn'` 행으로 옮긴다(시작 시 1회 마이그레이션 함수 · 멱등). `mastery_shadow`(T3)에도 `unit`. **B7(스키마)** 줄.
  2. `POST /golden/session`에 `unit: "mixed"` 허용. `GET /golden/next`가 `mixed`면 커서 홀짝으로 두 단원을 번갈아 낸다(각 단원 순환 유지). 응답 `unit` 필드로 앱이 안다.
  3. `_graded`의 숙련도 갱신은 문제의 `unit` 행에. 응답 `mastery`는 그 단원 값. 이것은 분기인가? `unit`을 키로 쓰는 것뿐이면 데이터 분기(B7에 포함).
  4. e2e에 `mixed` 케이스 추가(두 단원이 번갈아 나오고 각 단원 숙련도가 따로 오른다). 앱은 결과 화면에 단원 이름을 표시(서버 값).
  5. CONTRACT.md에 B7 + 발견분.
- **산출물:** 단원별 숙련도 표·마이그레이션 함수, mixed 세션, e2e 케이스, B7.
- **완료 기준:** ①e2e mixed 초록 ②기존 닉네임의 일차함수 숙련도가 보존된다(테스트: 마이그레이션 전후 값 동일) ③B7 기록 ④`tests/golden`·`flutter test` 초록.
- **하지 말 것:** 적응형 문항 선택(약한 단원 우선 등)을 넣지 않는다 — 번갈아만.

### S47. AI 전체 회귀 — 1,440세션(720 × 2) · 야간 스모크 240

- **목적:** 두 단원 M1~M5를 나란히 보고, 혼합 세션에서 튜터가 단원을 혼동하는지(P2·P4) 본다. 야간 스모크를 240(120 × 2)으로 확대한다.
- **선행 산출물:** S46.
- **할 일:** Kiki 머신에서 `SIM_FULL=1` 720 × 2단원 + 혼합 세션 P2·P4 60세션(제안값). `metrics.py`에 "단원 혼동" 지표(연립방정식 문제에서 튜터 발화에 '기울기'·'절편'이 나오거나 그 반대 — 낱말 목록은 `tutor_glossary.yaml`에서 읽는다) 추가. `golden-sim-nightly.yml`을 240으로(가짜 모드 두 단원). 보고에 두 단원 M1~M5 나란히 + 혼동 건수.
- **산출물:** 1,440 + 혼합 보고서, 혼동 지표, 워크플로 240.
- **완료 기준:** ①두 단원 M1 0%·M3 1% 미만·M4·M5 0(아니면 원인 문항 목록) ②혼동 건수 숫자 ③야간 240 가짜 모드 초록.
- **하지 말 것:** 결과가 나빠도 튜터·판정을 고치지 않는다(원인 목록만 — 결함 문항이면 S48, 코드 결함이면 LATER + Kiki 결정).

### S48. 결함 재생성 — 교체 문항 · CONTENT_REPORT 재생성 절

- **목적:** S40·S44·S45(·S47)의 결함 문항을 **같은 파이프라인**으로 재생성해 교체한다. 손으로 고치지 않는다. 재생성 수율·검토 시간을 적는다.
- **선행 산출물:** S45 재생성 목록, S37~S39 파이프라인.
- **할 일:**
  1. `pipeline.py --regenerate <SE-xx,...>`: 결함 문항의 난이도·오개념 슬롯만 스펙 부분집합으로 만들어 생성기 2모델 → V1~V4 → 합의/불일치 → Kiki 검토(30분 상한) → 교체. 학생 로그·결함 사유 문장은 프롬프트에 넣지 않는다(공통 규칙 11 — "어느 문항이 결함인가"도 넣지 않는다: 스펙 부분집합만).
  2. 교체 문항은 새 `cand_id`·새 `SE-xx`(같은 번호 재사용 — ID는 유지, `cand_id`·`source`가 바뀐다)로 `problems_sys_eq.json`과 사이드카 갱신. 교체 전 문항은 `golden/content/replaced/`에 보관(삭제 금지).
  3. 재생성 성공률(1회로 교체된 비율 · 목표 100%)·재생성 수율·검토 시간·비용을 `CONTENT_REPORT.md` "재생성 절"에.
  4. 스키마 테스트·e2e·스모크 초록.
- **산출물:** `--regenerate` 경로, 교체 문항, CONTENT_REPORT 재생성 절, 보관 폴더.
- **완료 기준:** ①결함 문항 전부 교체 또는 "교체 실패 N개 + 원인" ②재생성 성공률·수율·검토 시간 숫자 ③테스트 초록.
- **하지 말 것:** 문항을 손으로 고치지 않는다. 결함 문항을 그냥 빼고 29개로 가지 않는다(교체 실패면 실패로 기록).

### S49. AI 학생 2차 — 로그 15건(혼합 · 실학생 대체)

- **목적:** 혼합 세션을 AI 학생 3종(P2·P3·P4) × 5문제로 정독한다. AI 대체 누적 30건.
- **선행 산출물:** S47·S48 머지. H3는 선행이 아니다.
- **할 일:** S44의 1~5와 같다(단원 `mixed` · 날짜 꼬리표 `<날짜>-s49` · 문항 ID 조건은 `LF-`·`SE-` 둘 다 허용 · S47 실제 LLM 실행의 `sessions.jsonl`을 써도 된다). 보고에 추가: 단원별 표, 단원이 바뀐 직후 턴의 **튜터** 발화 인용(용어 블록이 맞는 단원 것으로 바뀌었는지 — 학생 반응은 "개방 시점 보완"), 결함 후보(S48 교체 문항이 5문항 안에 있으면 표시 · 없으면 "교체 문항 미포함"이라고 적는다).
- **완료 기준:** ①AI 대체 누적 30건 ②단원별 표와 단원 전환 턴 인용 ③결함 후보 목록.
- **하지 말 것·막히면:** S44와 같다.

### S50. 콘텐츠 중간 판정 — 메트릭 8줄 숫자 (관문 ③)

- **목적:** `F-Q2` 메트릭 8줄을 전부 숫자로 채운다. 목표 미달 항목은 원인 1줄.
- **선행 산출물:** S49, CONTENT_REPORT(1회차 + 재생성), S45.
- **할 일:** 수율·자동 통과율·불일치율·검토 시간·결함률(S45 + S49 결함 ÷ 30)·재생성 성공·정답률 분포(**"측정 불가(개방 시점 보완)"**로 적는다 — 실학생이 없다. 참고값으로 P2·P4 난이도별 정답률 vs 일차함수 1단계 AI 대체의 같은 페르소나 수치)·비용. `FINDINGS_v2.md`에 `## 콘텐츠 중간 판정 (S50)` 절. `F-Q2` 잠정 판정(예/조건부/아니오 — 수율·검토 시간·결함률 셋으로 하며 정답률 분포는 판정에서 뺀다).
- **완료 기준:** ①7줄 숫자 + 정답률 분포 "측정 불가" ②미달 항목 원인 1줄 ③판정: **go**(판정 완료).
- **하지 말 것:** 목표값을 바꾸지 않는다. 미달을 메우려 재생성을 추가로 돌리지 않는다(S48 1회가 결과).

### S51. 숙련도 2단원 — BKT 파라미터 연립방정식 값(B6) · 섀도

- **목적:** T3 BKT 파라미터를 단원별 설정으로 분리한다. 코드 분기 없음이 목표.
- **선행 산출물:** S46(단원별 숙련도 표), 1단계 `mastery/bkt.py`·S31 파라미터.
- **할 일:** `golden/mastery_params.yaml`(단원 → 파라미터 4개 · 연립방정식 초깃값은 일차함수 값에서 시작하고 S44·S49 정답률로 Kiki 확인 · 제안값 표기) → `bkt.py`가 `bkt_params(unit)`로 읽는다. **B6(설정)** 줄. 섀도 기록이 두 단원에 쌓이는지 테스트. 코드에 `if unit ==`가 생기면 B8+로 적는다.
- **완료 기준:** ①파라미터 파일 분리·테스트 초록 ②B6 기록 ③코드 분기 0(또는 기록).

### S52. AI 학생 3차 — 로그 20건(누적 50 · 연립방정식 · 실학생 대체)

- **목적:** AI 학생 4종(P2·P3·P4·P5) × 연립방정식 5문제 = 20건. S44와 **겹치지 않는 5문항**을 읽어 결함 후보를 찾는 범위를 넓힌다.
- **선행 산출물:** S50·S51 머지. H3는 선행이 아니다.
- **할 일:** S44의 1~5와 같다(단원 `sys_eq` · `--personas P2,P3,P4,P5` · 날짜 꼬리표 `<날짜>-s52`). 문항 5개는 S44가 읽지 않은 것 중에서 난이도 하·중·상이 섞이게 **ID와 난이도 필드만 보고** 고르고(대화 내용을 보고 고르지 않는다) 고른 ID를 보고 첫 절에 적는다 — S48 교체 문항이 있으면 우선 넣는다. 보고에 AI 대체 누적 집계(세션 50 · 정독한 연립방정식 문항 수), simple·bkt 궤적 표(S51 섀도 — `sim-*` 닉네임).
- **완료 기준:** AI 대체 누적 50건 또는 "축소: N건" 표기 · 고른 문항 ID와 고른 기준.
- **하지 말 것·막히면:** S44와 같다.

## S53~S55: 증거와 판정 (11주차)

### S53. 아키텍처 증거 — CONTRACT.md 최종 (관문 ④ 준비)

- **목적:** 분기마다 데이터·설정·코드로 확정 분류하고, 코드 분기 수와 "세 번째 단원 추가 시 예상 수정 줄 수"를 적는다.
- **선행 산출물:** S52, CONTRACT.md 전체, S45 줄 수.
- **할 일:** ①B1~B(마지막) 각 줄의 종류를 코드를 다시 읽어 확정(종류가 "코드 → 설정으로 바꿀 수 있음"이면 코드로 센다) ②코드 분기 수·데이터·설정 분기 수 ③S41~S43 코드 줄 수(S45 확정값) ④세 번째 단원(예: 중2 일차부등식) 추가 시 수정 줄 수 추정 — 분기마다 "이 분기에서 몇 줄"을 더해 근거를 적는다 ⑤`F-Q1` 잠정 판정(0~3 예 · 4~6 조건부 · 7+ 아니오). CONTRACT.md "최종" 절.
- **완료 기준:** ①모든 분기가 세 종류 중 하나로 분류 ②코드 분기 수 ③추정 줄 수와 근거 ④`git diff --stat` 수치 재확인.
- **하지 말 것:** 분기를 지금 정리(코드 → 설정)하지 않는다 — 3단계.

### S54. 최종 검증 — golden/VALIDATION_FINAL.md (관문 ⑤)

- **목적:** 코드를 쓰지 않는다. 두 질문에 숫자로 답하는 파일 하나를 만든다(계획서 §5-5 형식).
- **선행 산출물:** S53, S50, S52, FINDINGS_v2, CONTENT_REPORT.
- **할 일:** 형식 그대로 — `# WhyMath 2단계 최종 검증 (날짜)` / `## 질문 1`(판정·코드 분기 수와 목록·데이터·설정 분기 수·S41~S43 코드 줄 수·세 번째 단원 추정 줄 수·12/31 1차 판정과 달라진 점) / `## 질문 2`(판정·수율·자동 통과율·불일치율·검토 시간·결함률·재생성 성공·비용·난이도별 정답률 "측정 불가(개방 시점 보완)" + P2·P4 참고값·목표 미달 항목과 원인) / `## 진실 트랙`(**"미실시(Kiki 결정 2026-11-17 · AI 대체)"** 한 줄 + 별도 줄로 AI 대체 누적 세션 수·AI 완료율 + 개방 시점 보완 목록) / `## 3단계로 넘기는 결정 사항`(각 한 줄 · 근거는 위 숫자). 판정 기준 커밋 해시를 상단에 박는다.
- **완료 기준:** ①두 질문 각각 예/조건부/아니오와 근거 숫자 ②12/31 1차 판정과의 차이 ③판정: **go**(문서 완성).
- **하지 말 것:** 숫자 없이 판정하지 않는다. 대체 피험자·AI 숫자를 진실 트랙 칸에 넣지 않는다("미실시"로 둔다). 질문 2 판정에 "AI 대체 기준"을 붙인다.

### S55. 게이트·3단계 초안 — §7 판정 · 3단계 계획 초안

- **목적:** 계획서 §7 판정과 3단계 초안(세 번째 단원 후보·Subject Contract 추상화 범위·첫 세션의 FINDINGS 인용 항목). 미참조 옛 모듈 추가분을 `/legacy` 목록에.
- **선행 산출물:** S54.
- **할 일:** ①§7 판정(VALIDATION_FINAL의 두 판정 → 3단계 진행/부분 재설계 · 진실 트랙은 "미실시"로 옮겨 적고 판정에 쓰지 않는다 — 3단계 지시서의 실학생 작업(H4 등)이 원문 그대로인지 확인해 보고에 적는다) ②`golden/NEXT_PHASE3.md`: 세 번째 단원 후보 1~2개와 근거(CONTRACT.md 추정 줄 수), Subject Contract로 뽑을 줄(B 표의 후보 줄 열), 첫 세션이 인용할 F 번호, 세션 번호 S56부터 ③grimp로 `golden` 상류 ∖ 전체를 다시 재 S35 목록과 차이를 HARVEST.md에(새로 import된 것 = 2단계 자산) · `/legacy` 이동은 Kiki 결정 ④`golden/RETRO_phase2.md`(세션별 충족 표·범위 밖 멈춘 순간·LATER 수·"손으로 쓰고 싶었던 문항" 횟수).
- **완료 기준:** ①§7 판정 ②NEXT_PHASE3 첫 세션의 F 번호 ③미참조 목록 ④RETRO.
- **하지 말 것:** 세 번째 단원을 시작하지 않는다. 분기 정리 코드를 쓰지 않는다.
