---
description: 주도 모드 — 백로그의 다음 태스크를 순차적으로 골라 구현·검증·커밋·상태갱신을 반복
argument-hint: "[--max N] [--layer L] [--subject S] (기본 --max 3)"
---

# /drive — 주도 모드 루프

## 임무
지시를 기다리지 않고 백로그가 계산한 "다음 할 일"을 **순차적으로** 밀고 나간다.
태스크 선택 → 서브에이전트 위임 → 검증 → 커밋 → 상태 갱신 → 다음 태스크.
**사람 게이트에서만 멈춘다.**

## 인자
- `--max N` : 이번 루프에서 처리할 최대 태스크 수 (기본 3 — 폭주 방지)
- `--layer L` / `--subject S` : 후보를 특정 도메인/과목으로 한정

## 실행 절차

### 0. 무결성 선검사
```bash
python3 scripts/harness/backlog.py validate
```
실패 시 **즉시 정지·보고** (깨진 백로그 위에서 작업 금지).

### 반복 (최대 N회)

**1. 다음 태스크 계산**
```bash
python3 scripts/harness/backlog.py next --n 1 [--layer L] [--subject S]
```
후보가 없으면 정지 사유를 그대로 보고하고 루프 종료:
- `human_gate` → `/gates` 요약을 출력하고 정지 (Kiki 행동 필요 항목 명시)
- `all_done` → 스테이지 전환 계획(`/plan`)을 제안하고 정지
- `in_progress` → 다른 세션 진행 중 — 대기 또는 `--layer` 변경 제안

**2. 착수 (claim)**
```bash
python3 scripts/harness/backlog.py start <id>
```
출력된 acceptance 체크리스트가 이번 반복의 완료 기준이다.

**3. 서브에이전트 위임** — 태스크의 `layer`로 라우팅:

| layer | 서브에이전트 |
|---|---|
| backend / web | backend-engineer |
| mobile | flutter-engineer |
| data-pipeline | data-engineer |
| ml-models | ml-engineer |
| docs / infra | 태스크 성격에 따라 pedagogy-designer·content-curator·직접 수행 |

태스크 `notes`에 힌트가 있으면 그것을 우선한다 (프롬프트·교수학 작업은
llm-architect / pedagogy-designer). 위임 프롬프트에 반드시 포함:
acceptance 전 항목 · 7계층 경계 · CLAUDE.md 금기 · 한국어 주석 규칙.

**4. 검증** — 무엇을 돌릴지 사람이 고르지 않는다 (HARN-109·HARN-119)
```bash
python3 scripts/harness/ci_mirror.py run          # 변경이 닿는 잡을 자동 계산해 그대로 실행
```
이 한 줄이 종전의 "pytest·ruff green"을 대체한다. 사람이 검증 범위를 고르는 한
같은 계열이 다시 뚫린다 — 잡을 빠뜨리고(2026-09-17), 검사 종류를 빠뜨리고(09-10),
스코프를 틀리게 판정한다(09-19). 도구는 `changes` 잡의 path filter를 *정본으로 읽어*
대상을 계산하고, 스텝별 exit code와 **앞 스텝 실패로 건너뛴 스텝 수**를 함께 낸다.
- 재현 불가 잡(docker·서비스 컨테이너 의존)은 "재현 불가"로 표기되며 CI가 최종 판정한다
- 범위를 직접 지정해야 하면 `--job <이름>`(반복 지정). 무엇이 있는지는
  `python3 scripts/harness/ci_job_coverage.py scope`가 답한다
- acceptance 전 항목 자기평가 (하나라도 미충족 = 미완)
- 실패 → **1회 재시도**. 재실패 →
  `backlog.py block <id> --reason "..."` 후 다음 후보로 (같은 태스크 무한 재시도 금지)

**5. 커밋·기록**
- 테스트 동반 커밋 (커버리지 70%+ 원칙)
- 아키텍처·정책 결정이 발생했으면 MEMORY.md 끝에 결정로그 append

**5.5 PR 생성** (요청을 기다리지 않는다 — CLAUDE.md "완료·병합")
- 커밋한 산출물이 있으면 **PR을 연다**. "PR 지시를 못 받았다"는 보류 사유가 아니다 —
  이 단계가 없어서 완료작업이 브랜치에 갇히는 일이 4회 반복됐다(미병합 고립).
- **머지는 하지 않는다.** CI green 후 SQUASH 머지는 `"pr"` 지시 또는 Kiki 판단.
- 예외 4종이면 건너뛰되 **어느 예외인지 보고에 1줄로 적는다**:
  조사·계획 전용 / 미완·게이트 대기 / CI red / Kiki 명시 보류

**6. 완료 처리**
```bash
python3 scripts/harness/backlog.py done <id> --artifact "<PR 번호를 담은 증적>"
# 예외로 PR 없이 종결할 때만:
#   ... --artifact "<커밋>" --no-pr {investigation|incomplete|ci-red|kiki-hold}
```
증적에 PR 참조(`#12`·`.../pull/12`)가 없고 `--no-pr`도 없으면 CLI가 거부한다(exit 1).
출력되는 "해금된 후속 태스크"를 확인하고 반복 계속.

각 반복 사이 `git status` 청결 확인 (잔여 변경을 다음 태스크에 섞지 않는다).

### 종료 보고 (필수 형식)
```
🏁 /drive 종료 — N건 처리
[완료] <id> — <PR 링크 또는 번호>  (각 건 · PR 없이 종결했다면 예외 사유 명시)
[차단] <id> — <사유>     (있다면)
[정지 사유] human_gate: G-... / max 도달 / all_done
[게이트 리마인드] ⏳ G-... (Kiki, N일 경과)
[다음 next 미리보기] 1. <id> ...
```

## 안전장치 (협상 불가)
- 사람 게이트·acceptance 판단 불가(모호성)·2연속 실패에서 **반드시 정지**
- 정지·종료 시 **커밋된 산출물을 PR 없이 브랜치에 남기지 않는다** (예외 4종이면 사유 보고)
- ARCH-* 감사 태스크 완료 시 다음 회차를 `backlog.py add`로 재생성 (감시 끊김 방지)
- `--max` 없이 무한 루프 금지
- E축(subject-expansion) 태스크는 게이트가 열리기 전 절대 착수되지 않는다 — selector가 알고리즘 수준에서 차단하지만, 우회(waive) 판단은 Kiki 전용
