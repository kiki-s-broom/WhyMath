---
id: backlog-task-register
title: "백로그 태스크 등재 (새 할 일을 대장에 올리기)"
version: 1
updated: 2026-10-26
readiness: ready
owner: claude
open_questions: []
toolbox:
  - path: scripts/harness/backlog.py
    role: "등재(add)·착수(start)·선행 붙이기(amend --depends)의 유일한 쓰기 경로 — 대장 YAML 손편집 금지"
  - path: backlog/tasks
    role: "등재 결과가 쓰이는 곳 — 읽어서 대조만 한다"
  - path: docs/standards/build_harness.md
    role: "대장 규약 정본 (필드 의미·상태 전이)"
verify:
  - id: V1
    check: "대장 전체 무결성 검사가 통과한다"
    how: cmd
    cmd: "python3 scripts/harness/backlog.py validate"
  - id: V2
    check: "새 태스크 파일이 실제로 생겼다"
    how: cmd
    cmd: "ls backlog/tasks/{task_id}.yaml backlog/tasks/{task_id}-*.yaml 2>/dev/null | grep -q ."
  - id: V3
    check: "선행 관계가 산문(notes)이 아니라 depends_on 에 들어갔다"
    how: cmd
    cmd: "python3 scripts/harness/backlog.py audit-deps"
  - id: V4
    check: "acceptance 의 식별자(파일 경로·명령·태스크 id)가 셸 치환으로 사라지지 않았다"
    how: read
    evidence: "등재된 YAML 의 acceptance 를 다시 열어, 작성 원문 파일과 식별자를 하나씩 대조한 결과"
---

# 백로그 태스크 등재 — 업무 매뉴얼

> 방법론: `docs/standards/agent_manual_method.md` · 실행: `/manual-run backlog-task-register` · 오류 시: `/manual-fix backlog-task-register`

## 1. 목적과 범위
- 새로 발견한 할 일(버그 대책·기능·조사)을 작업일정 정본 `backlog/` 에 올려, 다른 세션이 보고 충돌 없이 고르게 한다.
- 범위 안: 새 태스크 등재, 등재 직후 선행 관계 붙이기.
- 범위 밖: 태스크 구현, 상태 변경(done·block), 게이트 처리 — 각각 별도 절차다.

## 2. 시작 전 입력
| 입력 | 어디서 얻는가 | 없으면 |
|---|---|---|
| 제목·완료 조건(acceptance) | 사용자 지시 또는 사고 분석 | 묻는다 |
| 트랙·스테이지 | 비슷한 기존 태스크 YAML (`grep -h '^track:' backlog/tasks/<접두>-*.yaml`) | 가장 많은 값을 쓴다 |
| EOS 등급 (P0~P3) | 사용자 지시 | P2 (판정 이후 품질 작업) |
| 선행 태스크 | 사용자 지시·노트 | 없음으로 둔다 |

## 3. 절차
1. acceptance 와 notes 를 **인용 heredoc**(`<<'EOF'`, 작은따옴표 필수)으로 스크래치 파일에 쓴다.
2. `backlog.py add --id <접두-번호> ... --acceptance "$(cat 파일)"` 로 등재한다. 번호가 거부되면 CLI 가 제안한 번호를 쓴다.
3. 선행이 있으면 `backlog.py amend <id> --depends <full-id> --reason ...` 로 붙인다.
4. 바로 착수할 거면 같은 흐름에서 `backlog.py start <id>` 까지 한다(코드를 읽기 전에).
5. §7 자체 검사를 돌린다.

## 4. 판단 분기
| 상황 | 기본 행동 | 사람에게 묻는 경우 |
|---|---|---|
| 번호 충돌로 add 거부 | CLI 제안 번호 사용 | 없음 |
| 파일 범위 겹침 경고 | 겹치는 태스크가 진행 중인지 확인 후 진행 | 상대가 in_progress 이고 같은 파일을 고칠 때 |
| 12/31 동결(D5) 대상 접두(HARN) | 등재만 하고 착수하지 않는다 | 착수가 필요하면 반드시 묻는다 |

## 5. 금지
- 대장 YAML 손편집 (병렬 세션의 번호·상태를 볼 수 없다)
- 번호를 눈으로 골라 배정 (병렬 세션의 예약 번호를 못 본다)
- 큰따옴표 인자에 백틱 직접 넣기 (명령 치환으로 식별자가 조용히 사라진다)
- 선행 관계를 notes 산문에만 적기 (선택기는 depends_on 만 본다)

## 6. 툴박스 사용 규칙
- 쓰기는 `backlog.py` 만. `backlog/tasks/` 는 읽기 대조용이다.
- acceptance 는 append 전용이라 잘못 쓰면 지울 수 없다 — 그래서 쓰기 전에 원문 파일을 남기고, 쓴 뒤 V4 로 대조한다.

## 7. 완료 조건 자체 검사
- `python3 scripts/manuals/manual.py verify backlog-task-register --arg task_id=<등재한 id>`
- ❌ 가 있으면 완료가 아니다. V4(⏳)는 대조 결과를 보고서에 적는다.

## 8. 실수 카탈로그
| 증상 | 원인 | 분류 | 매뉴얼 수정 위치 | 버전 |
|---|---|---|---|---|
| acceptance 에 "cron은 라 2~3회" 같은 깨진 문장 | 큰따옴표 인자 속 백틱이 명령 치환됨 (2026-09-08 HARN-87) | 절차 누락 | §3 1단계 · §5 · V4 | v1 |
| 같은 번호가 두 태스크에 배정 | 파일 목록 보고 번호를 눈으로 고름 (ARCH-13·OPS-15) | 금지 누락 | §5 | v1 |
| 선행을 적었는데 다른 세션이 먼저 착수 | 선행을 notes 산문에만 적음 (EOS-62) | 완료 조건 부재 | §3 3단계 · V3 | v1 |

## 9. 변경 이력
| 버전 | 날짜 | 무엇을 | 왜 |
|---|---|---|---|
| v1 | 2026-10-26 | 최초 작성 — 기존 사고 3건을 카탈로그로 이관 | HARN-316 예시 매뉴얼 |
