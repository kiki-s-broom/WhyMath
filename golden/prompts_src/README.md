# 골든 패스 AI 지시문 — 원본과 재생성 방법

이 폴더는 `golden/prompts/`(세션별 지시문 16개 + README), 학생 없는 변형 `golden/prompts_no_students/`(15개 + README), 1단계 두꺼게 `golden/prompts_phase1/`(21개 + README), 2단계 두 번째 단원 `golden/prompts_phase2/`(21개 + README), 3단계 세 번째 단원+Subject Contract `golden/prompts_phase3/`(21개 + README), 4단계 파일럿 `golden/prompts_phase4/`(32개 + README)를 **만들어 내는 원본**이다. 생성된 파일을 직접 고치지 말고 여기의 원본을 고친 뒤 다시 생성한다(생성기가 출력 폴더를 지우고 새로 만든다).

| 파일 | 역할 |
| --- | --- |
| `plan_golden_path_3weeks.html` | Kiki가 2026-11-08에 쓴 3주 실행 계획서 원본(그대로 보관) |
| (계획서 원본 PDF·DOCX) | 1~4단계 계획서 원본은 Kiki가 보관하며 저장소에 없다 — office·PDF 문서는 `.gitignore`와 `scripts/ops/check_source_document_binaries.py`가 커밋을 막는다(저작권 가드). 저장소 안 정본은 각 `spec_phaseN.md`다 |
| `spec.md` | 작업 지시서 — 공통 규칙 12개·용어·공유 계약(API 3개·문항 JSON·채점·숙련도·DB 표·환경변수)·작업 16개(S1~S15, H1) |
| `config.json` | 작업 번호·짧은 이름·레인·선행 관계(`deps`)·관문·배경 문장·사람이 할 일 |
| `spec_phase1.md` · `config_phase1.json` · (`plan_phase1_thicken_4weeks.pdf` — Kiki 보관 · 저장소 미포함) | **1단계 두꺼게(S16~S35)** 묶음의 원본. 골든 패스의 후속이며 시뮬레이터(S16~S20)·슬롯 T1·T2·T3·게이트(S35)와 사람 작업 H2. 접두 `DK`, 산출물 `golden/reports_phase1/`, 브랜치 `golden-p1/`. 계획서 전제와 저장소 사실이 다른 곳 4가지(실학생 0명·rubric.yaml 없음·오개념 8건·CI LLM 키 없음)는 공유 계약 첫 표에 있다 |
| `spec_phase2.md` · `config_phase2.json` · (`plan_phase2_second_unit_4weeks.docx` — Kiki 보관 · 저장소 미포함) | **2단계 두 번째 단원(S36~S55)** 묶음의 원본. 1단계의 후속이며 시작 조건(1단계 게이트 진실 트랙 "예")이 있다. 문항 파이프라인(S36~S40)·단원 스위치와 분기 장부(S41~S45)·혼합·재생성(S46~S51)·증거·판정(S52~S55)과 사람 작업 H3. 접두 `DU`, 산출물 `golden/reports_phase2/`, 브랜치 `golden-p2/` |
| `spec_phase3.md` · `config_phase3.json` · (`plan_phase3_contract_4weeks.docx` — Kiki 보관 · 저장소 미포함) | **3단계 세 번째 단원 + Subject Contract(S56~S75)** 묶음의 원본. 2단계의 후속이며 시작 조건(2단계 질문 1·2 "예")이 있다. 세 번째 단원(일차부등식)을 옛 방식으로(S56~S60) → `core/`+`units/` 새 길(S61~S66) → 실학생·삭제·정식화(S67~S70) → PREREG 개봉·네 번째 단원 드라이런·/legacy·게이트(S71~S75)와 사람 작업 H4. 네 번째 단원은 S56에서 `golden/PREREG.md`에 봉인되며 지시문은 S71~S73 본문에서만 그 이름을 쓴다. 접두 `SC`, 산출물 `golden/reports_phase3/`, 브랜치 `golden-p3/` |
| `spec_phase4.md` · `config_phase4.json` · (`plan_phase4_pilot_8weeks.docx` — Kiki 보관 · 저장소 미포함) | **4단계 파일럿(S76~S105)** 묶음의 원본. 3단계의 후속이며 시작 조건(3단계 게이트 첫 줄 "예")이 있다. 준비 2주(S76~S85 · 콘텐츠 확장·서버 이전·동의·마스킹·앱 배포·운영 리포트·AI 회귀·리허설·온보딩)·운영 5주(S86~S100 월·수·금 — 제품 변경 금지·결함만)·마감 1주(S101~S105 데이터 동결·분석·종합 보고·게이트 7줄)와 사람 작업 H5(학생 모집)·H6(법인·법률 상담). 접두 `PL`, 산출물 `golden/reports_phase4/`, 브랜치 `golden-p4/` |
| `spec_no_students.md` · `config_no_students.json` | **학생 없는 변형**의 원본. S1~S8은 `spec.md`와 글자 그대로 같고(생성 시 대조 확인), S9~S12를 본인·AI 시뮬레이션·성인으로 바꾸고 S13·S15의 집계·판정 문구를 고쳤다. 접두 `GPN`, 산출물 `golden/reports_no_students/`, 브랜치 `golden-ns/` |
| `scripts/golden_prompts/build_prompts.py`(이 폴더 밖·린트 배선된 scripts/ 아래) | 생성기. 선행 관계로 실행 단계(순차/병렬)와 여유·크리티컬 패스를 계산해 파일을 만든다 |

재생성(저장소 루트에서) — 원본 묶음:

```bash
python3 scripts/golden_prompts/build_prompts.py golden/prompts_src/spec.md golden/prompts_src/config.json golden/prompts
```

학생 없는 변형:

```bash
python3 scripts/golden_prompts/build_prompts.py golden/prompts_src/spec_no_students.md golden/prompts_src/config_no_students.json golden/prompts_no_students
```

1단계 두꺼게:

```bash
python3 scripts/golden_prompts/build_prompts.py golden/prompts_src/spec_phase1.md golden/prompts_src/config_phase1.json golden/prompts_phase1
```

2단계 두 번째 단원:

```bash
python3 scripts/golden_prompts/build_prompts.py golden/prompts_src/spec_phase2.md golden/prompts_src/config_phase2.json golden/prompts_phase2
```

3단계 세 번째 단원 + Subject Contract:

```bash
python3 scripts/golden_prompts/build_prompts.py golden/prompts_src/spec_phase3.md golden/prompts_src/config_phase3.json golden/prompts_phase3
```

4단계 파일럿:

```bash
python3 scripts/golden_prompts/build_prompts.py golden/prompts_src/spec_phase4.md golden/prompts_src/config_phase4.json golden/prompts_phase4
```

`spec.md`의 S1~S8을 고쳤으면 같은 절을 `spec_no_students.md`에도 그대로 반영한다(두 파일의 S1~S8 절은 글자 그대로 같아야 한다).

고칠 때의 규칙: 숫자·정의를 바꾸면 `spec.md`의 공유 계약을 고친다(모든 세션 파일에 같은 내용이 들어가므로 한 곳만 고치면 된다). 작업을 추가하면 `config.json`의 `tasks`에 번호·`deps`를 넣고 `spec.md`에 `### <번호>. <제목>` 절을 쓴다. 병렬 가능 여부는 `deps`에서 자동 계산된다.

## 세션 이름 자동 등록

지시문 파일의 첫 줄은 `세션 이름: GP-단계03-S4-API3개-튜터`처럼 파일 이름과 같다. 그 파일을 새 세션에 붙여 넣으면 두 가지가 자동으로 일어난다.

1. 저장소 훅 `.claude/hooks/golden_session_register.py`(UserPromptSubmit)가 첫 줄(접두 `GP`·`GPN`·`DK`·`DU`·`SC`·`PL`)을 읽어 `golden/SESSIONS.md` 등록부에 시각·세션 이름·작업 번호·묶음·session_id 앞 12자를 한 줄로 적는다(같은 세션은 중복 기록 없음). 지시문이 아닌 보통 프롬프트에는 아무것도 하지 않는다.
2. 같은 훅이 AI에게 "첫 행위로 세션 제목을 이 이름으로 바꿔라"를 알려 준다. 클라우드 세션(claude.ai/code)은 AI가 `set_session_title` 도구로 스스로 제목을 바꾼다. 터미널 Claude Code에는 그 도구가 없어서 AI가 `/rename <이름>` 한 줄을 안내하면 사용자가 쳐 준다.

훅 계약은 `tests/infra/test_golden_session_register.py`가 동결한다(지시문 첫 줄 형식·등록부 멱등성·깨진 입력에도 exit 0·생성된 지시문 전부가 첫 줄 형식을 갖는지).
