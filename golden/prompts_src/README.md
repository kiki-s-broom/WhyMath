# 골든 패스 AI 지시문 — 원본과 재생성 방법

이 폴더는 `golden/prompts/`(세션별 지시문 16개 + README)와 학생 없는 변형 `golden/prompts_no_students/`(15개 + README)를 **만들어 내는 원본**이다. 생성된 파일을 직접 고치지 말고 여기의 원본을 고친 뒤 다시 생성한다(생성기가 출력 폴더를 지우고 새로 만든다).

| 파일 | 역할 |
| --- | --- |
| `plan_golden_path_3weeks.html` | Kiki가 2026-11-08에 쓴 3주 실행 계획서 원본(그대로 보관) |
| `spec.md` | 작업 지시서 — 공통 규칙 12개·용어·공유 계약(API 3개·문항 JSON·채점·숙련도·DB 표·환경변수)·작업 16개(S1~S15, H1) |
| `config.json` | 작업 번호·짧은 이름·레인·선행 관계(`deps`)·관문·배경 문장·사람이 할 일 |
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

`spec.md`의 S1~S8을 고쳤으면 같은 절을 `spec_no_students.md`에도 그대로 반영한다(두 파일의 S1~S8 절은 글자 그대로 같아야 한다).

고칠 때의 규칙: 숫자·정의를 바꾸면 `spec.md`의 공유 계약을 고친다(모든 세션 파일에 같은 내용이 들어가므로 한 곳만 고치면 된다). 작업을 추가하면 `config.json`의 `tasks`에 번호·`deps`를 넣고 `spec.md`에 `### <번호>. <제목>` 절을 쓴다. 병렬 가능 여부는 `deps`에서 자동 계산된다.
