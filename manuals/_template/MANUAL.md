---
# ── 머리말: 기계가 읽는 부분 (scripts/manuals/manual.py 가 검사) ──
id: _template            # 폴더명과 같아야 한다 (예: manuals/weekly-report/ → weekly-report)
title: "업무 이름 한 줄"
version: 1               # 매뉴얼을 고칠 때마다 +1, §9 변경 이력에 같은 버전 행 추가
updated: 2026-10-26
readiness: draft         # draft = 인터뷰 중 · ready = 사람 없이 실행 가능
owner: claude            # 매뉴얼을 고칠 책임자
# 인터뷰(/manual-interview)가 아직 답을 못 얻은 질문. 1건이라도 있으면 ready 불가
open_questions:
  - "예: 결과물을 누구에게 보내는가?"
# 툴박스 — 에이전트가 이 업무에 쓰도록 *승인된* 파일·스크립트·템플릿. 경로가 저장소에 실재해야 한다
toolbox: []
#  - path: scripts/harness/backlog.py
#    role: "무엇에 쓰는가 (이 업무에서의 유일한 쓰기 경로 등)"
# 완료 조건 (Verification List) — '작업 완료'의 정의. 항목마다 확인 방법이 있어야 한다
#   how: cmd   → 명령이 exit 0 이면 통과 ({name} 자리는 manual.py verify --arg name=값 으로 채움)
#   how: read  → 에이전트가 산출물을 다시 읽고 evidence 에 적힌 것을 대조
#   how: human → 사람만 판정 가능 (ready 매뉴얼에서는 최소화)
verify:
  - id: V1
    check: "무엇이 참이어야 완료인가"
    how: read
    evidence: "무엇을 보고 판정하는가"
---

# 업무 이름 — 업무 매뉴얼

> 방법론: `docs/standards/agent_manual_method.md` · 실행: `/manual-run <id>` · 오류 시: `/manual-fix <id>`

## 1. 목적과 범위
- 이 업무는 무엇을 위해 하는가 (결과물이 어디에 쓰이는가)
- 범위 안: …
- 범위 밖 (이 매뉴얼로 하지 않는 것): …

## 2. 시작 전 입력
| 입력 | 어디서 얻는가 | 없으면 |
|---|---|---|
| 예: 태스크 id | 사용자 지시 | 묻는다 (기본값 없음) |

## 3. 절차
1. 단계 — 무엇을 한다 · 예상 결과
2. …

## 4. 판단 분기
> 사람에게 묻지 않고 진행하기 위한 기본값. 기본값이 없는 분기는 open_questions 로 올린다.

| 상황 | 기본 행동 | 사람에게 묻는 경우 |
|---|---|---|
| … | … | … |

## 5. 금지
- 이 업무에서 절대 하지 않는 것 (왜)

## 6. 툴박스 사용 규칙
- 머리말 toolbox 에 없는 스크립트를 새로 만들어 쓰지 않는다. 필요하면 먼저 매뉴얼에 등록한다(/manual-fix).

## 7. 완료 조건 자체 검사
- 결과를 내놓기 전에 `python3 scripts/manuals/manual.py verify <id>` 를 돌린다.
- ❌ 가 하나라도 있으면 완료가 아니다. ⏳ 항목은 증거를 보고서에 적는다.

## 8. 실수 카탈로그
> 증상 → 원인 → 이 매뉴얼의 어디를 고쳤는가. '수정 위치'는 §N · VN · 툴박스 중 하나를 반드시 가리킨다.

| 증상 | 원인 | 분류 | 매뉴얼 수정 위치 | 버전 |
|---|---|---|---|---|

## 9. 변경 이력
| 버전 | 날짜 | 무엇을 | 왜 |
|---|---|---|---|
| v1 | 2026-10-26 | 템플릿 | — |
