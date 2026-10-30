---
description: 업무 매뉴얼 생성 — 사용자를 인터뷰해 사람 없이 실행 가능한 수준까지 manuals/<id>/MANUAL.md 를 채운다
argument-hint: "<매뉴얼 id (영문 소문자-하이픈)> [업무 설명]"
---

# /manual-interview — 인터뷰로 업무 매뉴얼 만들기

## 임무
사용자의 반복 업무 하나를 `manuals/<id>/MANUAL.md` 로 명세화한다. 끝나는 기준은 "충분해 보인다"가 아니라
`docs/standards/agent_manual_method.md` §2 의 **멈춤 조건**(미해결 질문 0건 · 분기마다 기본값 · 툴박스 실재 · cmd 완료 조건 1건+ · lint exit 0)이다.

## 절차
1. `manuals/<id>/` 가 없으면 `manuals/_template/MANUAL.md` 를 복사하고 `id` 를 폴더명으로 바꾼다. 있으면 그 파일에서 이어 간다(open_questions 부터).
2. 저장소에서 알 수 있는 것은 **묻지 말고 먼저 찾는다** — 관련 스크립트·양식·기존 런북·사고 기록(`backlog.py incident report`).
3. 질문 8축(목적 → 범위 → 입력 → 절차 → 분기 → 금지 → 도구 → 완료)을 순서대로, **한 번에 3문항 이하**로 묻는다. 가능하면 AskUserQuestion 으로 선택지를 준다.
4. 답을 받을 때마다 해당 절에 바로 반영한다(대화에만 두지 않는다). 사용자가 모르는 질문은 `open_questions` 에 남긴다.
5. "끝났다는 걸 무엇으로 아나?"의 답은 가능한 한 **명령**으로 바꿔 `verify` 에 `how: cmd` 로 넣는다. 명령으로 못 바꾸면 `how: read` + `evidence`.
6. 매 라운드 끝에 `python3 scripts/manuals/manual.py lint` 를 돌려 남은 위반을 사용자에게 한 줄로 알린다.
7. 멈춤 조건이 전부 참이면 `readiness: ready` 로 올리고, §9 에 변경 이력 행을 쓴다.

## 하지 않는 것
- 사용자 답 없이 분기 기본값을 지어내지 않는다 — 모르면 open_questions.
- 툴박스에 저장소에 없는 경로를 적지 않는다(lint 가 막는다). 새 도구가 필요하면 먼저 만들고 등록한다.
