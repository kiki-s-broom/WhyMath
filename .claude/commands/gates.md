---
description: 사람 게이트 대장 점검 — Kiki 행동 필요 항목을 한 화면 요약, clear/waive 처리
argument-hint: "[clear <G-id>|waive <G-id>] (인자 없으면 목록)"
---

# /gates — 사람 게이트 점검·리마인드

## 임무
프로젝트 진행을 막고 있는 **사람(Kiki) 행동 대기 항목**을 한 화면에 요약하고,
해소된 게이트를 증거와 함께 clear 처리한다.

## 실행 절차

### 1. 목록 (기본)
```bash
python3 scripts/harness/backlog.py gates list
```
출력에 다음을 덧붙여 보고:
- 경과일수 내림차순 정렬 (가장 오래 막힌 것 먼저)
- 각 게이트가 **몇 개의 태스크를 막고 있는지** (`backlog.py status --json`의 blocked·next로 판단)
- Kiki가 해야 할 **구체적 행동 1줄** (게이트 title·notes 기반)

### 2. clear (해소 확인 시)
증거 없이 clear 금지 — 커밋·문서·실측 기록을 evidence로 남긴다:
```bash
python3 scripts/harness/backlog.py gates clear <G-id> --evidence "<커밋/문서/기록>"
```
clear 후 `backlog.py next`를 실행해 **해금된 태스크를 즉시 보고**하고,
사용자가 원하면 `/drive`로 바로 이어간다.

### 3. waive (예외 통과)
게이트를 건너뛰는 결정은 **Kiki 전용**이다. 사용자가 명시적으로 지시했을 때만:
```bash
python3 scripts/harness/backlog.py gates waive <G-id> --reason "<사유>"
```
waive 사유는 MEMORY.md 결정로그에도 append한다.

### 4. add (게이트 등재 — 대장 손편집 금지)
게이트 신설은 반드시 CLI 경유(HARN-18 — gates.yaml 직접 편집은 "거부의 우회 금지" 위반):
```bash
python3 scripts/harness/backlog.py gates add <G-id> --title "..." \
  --kind <human|external|decision> --assignee kiki --remind-after-days <N>
```
등재 후 `backlog.py validate` green 확인.

### 5. amend --note (부분 답변·판정 근거 누적 — 게이트를 닫지 않는다)
Kiki가 일부만 답했거나 판정 근거가 생겼지만 clear 요건은 아직 미충족일 때, **MEMORY.md에만 적지 말고
게이트 notes에 기록한다**(clear 판단자는 `gates show`로만 읽는다 — 못 읽으면 추론으로 닫는다):
```bash
python3 scripts/harness/backlog.py gates amend <G-id> --note "<부분 답변·근거>" --reason "<사유>"
python3 scripts/harness/backlog.py gates show <G-id>   # notes 전문 확인
```
백틱이 든 산문은 인용 heredoc(`<<'EOF'`)으로 파일에 쓴 뒤 `--note "$(cat 파일)"`로 넘기고, 쓴 뒤 `show`로 읽어 대조한다.

## 원칙
- G-s5-subject-expansion(E축 하드락)은 S5 판정 태스크를 거치지 않고 clear/waive 금지
- 게이트 추가는 `gates add` CLI로만 — backlog/gates.yaml 손편집 금지 (HARN-18 · 2026-08-10 통합점검 정정: 종전 이 줄이 손편집을 안내하고 있었다)
