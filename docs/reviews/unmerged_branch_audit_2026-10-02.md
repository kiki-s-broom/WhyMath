# 미머지 브랜치 전수 감사 14회차 — 2026-10-02

> **판정 기준: main `f99d1dc1`** (2026-10-02). 이 문서는 그 시점의 스냅샷이며 정본이 아니다.
> 실행 정본은 `backlog/`(회수 태스크)와 `.github/branch-cleanup-request.txt`(삭제 배치)다.
> 선행 판정 `unmerged_branch_audit_2026-09-28.md`(13회차)는 수정하지 않는다.
> 이 세션은 시작 시 shallow였고 `git fetch --unshallow origin` + `git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'`로 전제를 복구한 뒤에만 판정했다.

## 0. 계기와 요약

Kiki의 "떠돌이 코드 정리" 요청 → `/stray-code`. 13회차(09-28) 이후 4일간의 변화를 판정했다.

1. **미추적 고립 1건 발견 — 법령 관련.** `claude/intelligent-noether-tbj2jf`가 게이트 `G-eos37-erasure-kpi-disposition`(PIPA 삭제권 처분)을 Kiki 판정 (나)로 `cleared` 처리했는데 main에서는 아직 `pending`이다. 이 때문에 SEC-40(삭제권 이행 뒤 `evidence_event` 잔존 차단)이 판정이 끝났는데도 착수되지 못한다. 회수 태스크 **SEC-42**(priority 1)를 등재했다.
2. **삭제 가능 3건** — `hja5kh-eos129` · `hja5kh-s4-11` · `gk8vkz`. 13차 삭제 배치로 등재.
3. **추적 중 15건 전건 승계** — 15건 head가 09-28 기록값과 전부 동일하고 좌석 상실 0.
4. 12차 삭제 배치 5건은 **잔존 0/5**(`git ls-remote` 실측)로 집행이 확인됐다.

## 1. 전제 복구와 모집단 분리

```bash
git rev-parse --is-shallow-repository      # true였다 → 아래 두 줄 실행 후 false
git fetch --unshallow origin
git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'
git for-each-ref refs/remotes/origin       # 45건 · git ls-remote --heads origin 45건과 일치
```

| 구분 | 건수 | 내역 |
|---|---|---|
| 원격 ref 전수 | 45 | 로컬 remote-tracking 45 = `ls-remote` 45 |
| 제외 — 판정 대상 아님 | 2 | `main` · `harness-claims` |
| 제외 — 열린 PR이 소유 | 21 | 열린 PR 21건(GitHub MCP `list_pull_requests`) |
| 제외 — 원격 claim 활성 · PR 없음 | 2 | `status-f6qz0c`(EOS-63) · `status-f9lp65`(HARN-56) |
| 제외 — 머지 큐 임시 브랜치 | 1 | `gh-readonly-queue/main/pr-1417-*`(자동 소멸 · 허용 패턴 밖) |
| **감사 대상** | **19** | §2 |

**유령 PR 0건** — 열린 PR 21건의 head 브랜치가 전부 원격에 실재한다(역방향 확인).
claim 대장에는 활성 claim 10건이 있으나 그중 `status-38gu4d`(OPS-73) · `awesome-bohr-cxff43`(OPS-95) · `blissful-lovelace-ubp9tw`(OPS-96) 3건은 **원격에 브랜치가 없다**(미push) — 정보로만 기록하고 건드리지 않는다.

산술: 45 − 2 − 21 − 2 − 1 = 19.

## 2. 3축 측정

```bash
B=origin/<브랜치>
git rev-list --left-right --count origin/main...$B                              # behind ahead
git diff --name-only origin/main...$B | wc -l                                   # 내용 diff
git diff --name-only origin/main...$B | grep -cE '^(src|tests|data|scripts)/'   # done-less 사각
```

| 브랜치 | behind | ahead | diff | 코드 | 고립 done | 최종 커밋 |
|---|---|---|---|---|---|---|
| `backend-audit-event-foundation-29ac1b` | 511 | 3 | 22 | 21 | 0 | 08-25 |
| `intelligent-noether-tbj2jf` | 12 | 1 | 2 | 0 | 0 | 09-30 |
| `magical-maxwell-hja5kh-eos129` | 64 | 3 | 10 | 6 | 0 | 09-28 |
| `magical-maxwell-hja5kh-s4-11` | 38 | 2 | 2 | 0 | 0 | 09-29 |
| `openrouter-setup-guide-e98dw4` | 700 | 13 | 37 | 27 | 1 | 08-03 |
| `optimistic-bell-gk8vkz` | 33 | 1 | 2 | 0 | 0 | 09-29 |
| `remaining-track-34zvse` | 604 | 16 | 33 | 23 | 1 | 08-11 |
| `subject-problems-theory-check-7n9n72` | 613 | 34 | 83 | 49 | 10 | 08-11 |
| `whymath-ai-content-design-vafylb` | 636 | 8 | 7 | 1 | 0 | 08-10 |
| `whymath-ai-recommendation-review-q8tvcx` | 678 | 3 | 11 | 2 | 1 | 08-07 |
| `whymath-coding-architecture-iws58k` | 619 | 1 | 16 | 1 | 0 | 08-10 |
| `whymath-constitution-rules-check-azdnov` | 613 | 1 | 5 | 0 | 0 | 08-11 |
| `whymath-curriculum-design-6eejrv` | 577 | 9 | 6 | 3 | 1 | 08-11 |
| `whymath-data-platform-design-t608mk` | 609 | 1 | 7 | 0 | 0 | 08-11 |
| `whymath-issues-review-k20m0w` | 625 | 45 | 133 | 95 | 12 | 08-11 |
| `whymath-mvp-plan-architecture-trjg5x` | 666 | 81 | 233 | 188 | 34 | 08-09 |
| `whymath-pedagogy-review-gdmwhk` | 613 | 1 | 31 | 21 | 0 | 08-11 |
| `whymath-pedagogy-review-uqyg79` | 694 | 38 | 76 | 51 | 9 | 08-03 |
| `whymath-service-operations-review-5t5lmv` | 609 | 6 | 33 | 17 | 2 | 08-11 |

## 3. 4분류 판정

| 분류 | 건수 | 내역 |
|---|---|---|
| ① 회수 필요(미추적 고립) | **1** | `tbj2jf` → **SEC-42** |
| ② 추적 중 | **15** | 13회차 15건 전건 승계 |
| ③ 삭제 가능 | **3** | `hja5kh-eos129` · `hja5kh-s4-11` · `gk8vkz` |
| ④ 제외 | 24 | PR 소유 21 · claim 활성 2 · 머지 큐 임시 1 (+ 판정 대상 아님 2) |

합계 1 + 15 + 3 = 19(감사 대상).

### ① 회수 필요 — `claude/intelligent-noether-tbj2jf` (head `c671a313`)

- 내용: 커밋 1개(2026-09-30). `backlog/gates.yaml`에서 `G-eos37-erasure-kpi-disposition`을 `pending → cleared`로 바꾸고 이벤트 샤드 1줄을 남겼다. 증적에 판정 기준 main `f0ca37bb`, Kiki의 (나) 채택(삭제 시 그 세션의 추천 `evidence_event`를 같은 트랜잭션에서 함께 삭제)이 적혀 있다.
- 미추적 근거: `git grep -l tbj2jf origin/main -- backlog/tasks docs` 0건. 이 게이트의 clear를 담은 다른 브랜치·PR도 없다(`git log --all -S'G-eos37-erasure-kpi-disposition' -- backlog/gates.yaml`은 게이트를 *등재*한 커밋 `e7ac087d`만 반환).
- 이중 확인: main `backlog/gates.yaml`의 같은 게이트는 `status: pending`·`cleared_by: null`이다. main의 SEC-40·EOS-37은 둘 다 `requires_gates`에 이 게이트를 가져 착수가 막혀 있다.
- 위험: 법령(PIPA 삭제권) 유래 판정이라 우선순위 2번 → **priority 1**. 판정이 사람의 선택을 에이전트가 중계한 기록(`cleared_by: claude`)이라, SEC-42 acceptance ③에 이식 전 Kiki 1줄 재확인을 요구하는 항을 넣었다.
- 등재: **SEC-42**. 최초 시도 번호 SEC-41은 main에 이미 있는 다른 태스크(보존기간 파기 가드, #1404)라 CLI가 거부했고, SEC-42를 채택했다.

### ② 추적 중 15건 — 좌석 상실 0

head 불변 15/15(09-28 기록값과 대조). 소유 태스크 status는 main 기준으로 전수 조회했다.

| 브랜치 | 살아 있는 좌석 | 13회차 대비 |
|---|---|---|
| `7n9n72` | MISC-01/03/05/06 · PB-02 · PB-14 · PED-14 · S3-33/34 · OPS-41 · HARN-79 — **삭제 절대 금지** | 동일 |
| `trjg5x` | ADMIN-02 · PATH-03 · PB-14 | 동일 |
| `k20m0w` | SEC-19 · SEC-30 · MGMT-03 · HARN-25 · PB-14 | MOB-18 · MOB-11 · MOB-23이 **done**으로 바뀜 — 나머지 좌석은 todo라 유지 |
| `gdmwhk` / `uqyg79` | PED-26 (+ gdmwhk HARN-31) | 동일 |
| `34zvse` | CUR-07 · HARN-80(in_progress) | 동일 |
| `5t5lmv` | OPS-40 | 동일 |
| `iws58k` | ARCH-30 | 동일 |
| `t608mk` / `azdnov` | OPS-41 | 동일 |
| `6eejrv` | PB-08 | 동일 |
| `e98dw4` | VIZ-11 | 동일 |
| `q8tvcx` | OPS-38 · OPS-67 · OPS-41 | 동일 |
| `vafylb` | OPS-53(실제 회수 좌석) — 세션 브리핑의 "이미 포팅됨"은 오분류(HARN-190) | 동일 |
| `29ac1b` | ADMIN-10 ⑦ — `docs/architecture/90_audit_log.md`가 main 부재(실측 재확인) | 동일 |

이번 세션이 새로 한 것은 head 불변 확인과 좌석 태스크 status 재조회까지다. 좌석 본문(acceptance가 해당 산출물을 다루는지)은 13회차의 정독 결과를 승계했고 재정독하지 않았다 — §5 공백 참조.

### ③ 삭제 가능 3건 — 근거

1. **`magical-maxwell-hja5kh-eos129`** (head `c5983e59`): PR #1346이 2026-09-28에 머지 없이 닫혔다. main 결정 로그 PR #1389(`0f97ed64`)가 "`G-eos129-item-response-census`는 되살리지 않고, census 자산은 회수하지 않는다"고 명문화했다. 잔여 diff 10파일의 처분을 하나씩 대조했다.
   - census 모듈·테스트·런북: 위 결정으로 폐기.
   - `item_calibration.py`의 공용 로더 `load_graded_responses`: census의 `read_only` 옵션 전용이며 main 심볼 0건 — 쓰는 곳이 없어지므로 함께 폐기.
   - `next_problem_selection.py` 주석 정정: main이 EOS-129 ③ 착지(PR #1358)로 같은 주석을 더 새로 고쳐 두었다.
   - Rasch 45문항 하한 동결: main `tests/backend/l2/test_irt_discrimination_calibration.py`에 이미 있다.
2. **`magical-maxwell-hja5kh-s4-11`** (head `9adc142e`): 브랜치 커밋 메시지가 "타 세션이 #1372로 먼저 완료·머지해 이 브랜치는 폐기"를 기록한다. main S4-11은 `done`. 고유 내용은 이벤트 샤드와 태스크 YAML 6줄뿐.
3. **`optimistic-bell-gk8vkz`** (head `8fe81e89`): "EOS-141 착수 후 미완 종료 — claim 해제 기록(판정 산출물 없음)" 1커밋. main EOS-141은 `done`(PR #1387).

삭제 전 head SHA 3건은 배치 파일에 스냅샷으로 남겼다. 복구 경로는 GitHub API `commits/<sha>`·`contents?ref=<sha>`다.

### ④ 제외

- PR 소유 21건 · 원격 claim 활성(PR 없음) 2건 · 머지 큐 임시 브랜치 1건(`gh-readonly-queue/main/pr-1417-f99d1dc1...`, 자동 소멸) · 판정 대상 아님 2건(`main`·`harness-claims`).

## 4. 번호 탐색 중 발생한 실수 1건 (정직한 기록)

회수 태스크 번호를 찾으려고 `backlog.py add --id SEC-99 --title x ...`를 **탐색용으로** 실행했는데, 이 명령은 실제 등재 명령이라 로컬 파일 `backlog/tasks/SEC-99.yaml`과 원격 번호 예약 `harness-claims/reservations/SEC-99.json`(브랜치 `claude/gracious-ride-jxwgyq`)을 만들었다.

- 로컬 파일 2개(태스크 YAML · 이벤트 샤드)는 삭제해 작업 트리를 되돌렸다(`git status` 0건).
- **원격 예약 `SEC-99`는 남아 있다.** `backlog.py --help`에 예약을 해제하는 하위 명령이 보이지 않아 이 세션에서는 해제하지 못했다. 해당 번호는 다른 세션의 `add`가 거부하는 번호로 남는다(영향: SEC-99를 쓸 일이 생기면 거부될 뿐 데이터 손상은 없다).
- 재발 방지: 번호 후보 확인은 `git ls-tree`로 main·`harness-claims`를 조회하는 읽기 전용 명령으로 한다 — `add`를 탐색에 쓰지 않는다.

## 5. 정직한 공백

- **이벤트 샤드 원문을 판정 문서에 복사하지 않았다.** 삭제 대상 3건의 `backlog/events/*.ndjson`(약 16줄 · 98줄 · 3줄)은 해당 브랜치 head SHA로만 복구된다. 샤드 내용을 읽으려던 명령이 이 세션에서 권한 거부되어 우회하지 않았다. 앞선 회차는 샤드 원문 1줄씩을 판정 문서에 보존했으므로 이번 회차는 보존 수준이 한 단계 낮다.
- ② 추적 중 15건은 head 불변과 좌석 status만 재확인했다. 좌석 acceptance 본문 재정독은 하지 않았다.
- `hja5kh-eos129`의 잔여 diff 대조는 파일 단위 심볼·주석 확인이며, 줄 단위 전수 `comm -23` 대조는 하지 않았다.
- 열린 PR 21건은 head 브랜치 실재만 확인했고 각 PR의 head SHA 일치 여부는 대조하지 않았다.
- SEC-42의 이식은 이 감사의 범위가 아니다 — `/drive`가 실행한다. 그 전까지 `tbj2jf` 삭제 금지.
- 전체 백엔드 스위트는 돌리지 않았다 — 이 변경은 문서·대장·삭제 배치뿐이고 소스·테스트를 건드리지 않는다.
