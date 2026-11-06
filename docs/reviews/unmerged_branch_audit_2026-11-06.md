# 미머지 브랜치 전수 감사 19회차 — 2026-11-06

> **판정 기준: main `ce8c2165`** (2026-11-06). 이 문서는 그 시점의 스냅샷이며 정본이 아니다.
> 실행 정본은 `backlog/`(회수 태스크)와 `.github/branch-cleanup-request.txt`(삭제 배치)다.
> 선행 판정 `unmerged_branch_audit_2026-10-14.md`(18회차)는 수정하지 않는다.
> 이 세션은 시작 시 shallow였고 `git fetch --unshallow origin` + `git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'`로 전제를 복구한 뒤에만 판정했다(`git rev-parse --is-shallow-repository` → false 확인).

## 0. 요약

1. **18회차 이후 23일 동안 신규 고립 15건이 생겼다.** 그중 회수가 필요한 미추적 고립은 **2건**이다.
   - **`claude/fervent-maxwell-2b4w10`** — SEC-34 자격증명 전량 폐기·재발급 런북 920줄이 PR 없이 고립. main 언급 0건. SEC-34 acceptance ②(자격증명 로테이션)는 2026-09-10 등재 뒤 아직 미이행이고, 이 런북이 그 유일한 실행 준비물이다. 보안 축이라 **priority 1**로 회수 태스크 `SEC-45`를 등재했다.
   - **`weekly-metrics` 예약 실행 3회 연속 실패** — 10/19·10/25·11/02 실행이 산출 브랜치 push까지만 성공하고 PR을 열지 못했다. 10/19·10/25 행은 EOS-197 PR #1765가 수동으로 main에 실었지만 **11/02 행은 main에 없다**. 3주 동안 아무도 알아채지 못했다. 시스템 결함이라 `OPS-161`을 등재했다.
2. **18회차 회수 태스크 4건이 그 사이 완료됐다**(`OPS-140`·`OPS-130`·`PED-45`·`EOS-194`). 그러나 바로 삭제할 수 있는 것은 없다 — `OPS-130`·`PED-45`의 브랜치는 원격 claim이 걸려 있고, `OPS-140`의 두 브랜치(keller·allen)는 미완료 `HARN-311`이 그 이벤트 샤드를 사고 증거로 지목한다(§4).
3. **삭제 배치 18차 = 3건**(`jolly-fermi-6km81l`·`ops-83-inject-shard-failure`·`p3-50-02-01-chain-restore`). 세 브랜치 모두 소유 태스크가 main에서 완료·회수됐고 잔여 줄은 main의 더 새 버전으로 대체됐거나 머지 금지로 만든 고의 실패 주입뿐이다.
4. **수동 삭제 후보 5건 — 자동 삭제 배치에 넣을 수 없다.** `p3-78/`·`eos197/`·`eos211/`·`ops/weekly-metrics-*` 이름은 `branch-cleanup.yml` 허용 패턴(`claude/*`·`tmp-*`·`worktree-agent-*`) 밖이다(§6).
5. **18회차 이월 25건은 head가 전부 불변**이다.

## 1. 전제 복구와 모집단 분리

| 구분 | 건수 | 내역 |
|---|---|---|
| 원격 ref 전수 | 74 | `git for-each-ref refs/remotes/origin` (HEAD 별칭 없음) |
| 제외 — 판정 대상 아님 | 3 | `main`·`harness-claims`·`harness-reports` |
| 제외 — 머지 큐 임시 브랜치 | 1 | `gh-readonly-queue/main/pr-1844-*` |
| 제외 — 열린 PR이 소유 | 30 | 열린 PR 30건(GitHub MCP `list_pull_requests`) |
| **감사 대상** | **40** | §2 · 산술: 74 − 3 − 1 − 30 = 40 (§2-1 16건 + §2-2 24건) |

**유령 PR 0건** — 열린 PR 30건의 head가 전부 원격에 실재한다. `#1859`(`new-session-yb0cmb`)는 측정 도중 head가 `0a97ae2c`→`fd33f93c`로 움직였다(활성 세션).

**claim 대장 대조**: `backlog.py claims list`·`claims reap`(dry-run)은 이 세션에서 권한 분류기가 거부했다(공유 자원 변경 분류). 우회하지 않고 `git show origin/harness-claims:claims/<id>.json`을 직접 읽었다 — claim 19건. TTL 72시간 안은 `HARN-321`(11-06)·`P3-94`(11-06) 2건뿐이고 나머지 17건은 TTL을 넘겼다. 선례대로 **TTL 초과 claim이 걸린 브랜치도 손대지 않는다.** `claims reap --apply`는 이 감사의 범위가 아니다.

## 2. 측정과 분류

```bash
git rev-list --left-right --count origin/main...$B                              # behind ahead
git diff --name-only origin/main...$B | wc -l                                   # 내용 diff
git diff --name-only origin/main...$B | grep -cE '^(src|tests|data|scripts)/'   # done-less 사각
```

흡수 판정은 두 단계로 했다: ① 파일 blob 해시가 main과 같은가 ② 다르면 브랜치가 **추가한 줄**(3점 diff의 `+`줄) 중 main의 같은 파일에 **줄 전체 일치**로 없는 줄의 수(이벤트 샤드·`MEMORY.md`는 별도 축). 서식만 달라도 부재로 세므로 이식량의 상한이다.

### 2-1. 신규 15건 (18회차 이후)

| 브랜치 | head | 최종 커밋 | behind | ahead | diff | 코드 | 분류 |
|---|---|---|---|---|---|---|---|
| `p3-94/seat-compare-20261106` | `04171bba` | 11-06 | 5 | 1 | 8 | 8 | ⓪ 활성 claim `P3-94`의 Kiki PC 수집 데이터(PR #1865 진행 중) |
| `claude/new-session-hwq1or` | `1a98c6fa` | 11-06 | 0 | 1 | 1 | 0 | ⑤ 유예 — 3시간 전 생성(P3R 작업 A1 중단 보고) |
| `claude/serene-planck-g6jhey` | `5ad7c401` | 10-31 | 67 | 1 | 3 | 0 | ⓪ claim `P3-87`(TTL 초과) |
| `claude/kind-allen-fvy6ow` | `6096c086` | 10-18 | 175 | 1 | 5 | 1 | ⓪ claim `P3-57`(TTL 초과) |
| `claude/fervent-maxwell-2b4w10` | `95576896` | 10-18 | 173 | 2 | 2 | 0 | **① 신규 `SEC-45`** |
| `ops/weekly-metrics-20261102T012320Z` | `d93b1475` | 11-02 | 45 | 1 | 1 | 0 | **① 신규 `OPS-161`** (11-02 행의 유일한 사본) |
| `claude/eos-compiler-pack-check` | `d7c8a365` | 10-19 | 158 | 1 | 47 | 0 | ② 추적 중 — ADR-010 D8=(가) 보존·2027-01 재검토 |
| `claude/laughing-edison-rb5hgl` | `62eb4503` | 10-14 | 242 | 2 | 2 | 0 | ④ Kiki 판단 — CLAUDE.md 대학 범위 수정안(채택 전) |
| `claude/jolly-fermi-6km81l` | `636896a4` | 10-14 | 242 | 1 | 22 | 14 | ③ 삭제 — `EOS-194` done |
| `claude/ops-83-inject-shard-failure` | `e8912657` | 10-27 | 105 | 8 | 19 | 13 | ③ 삭제 — `OPS-83` done · PR #1754 닫힘 |
| `claude/p3-50-02-01-chain-restore` | `4098266c` | 10-18 | 169 | 1 | 4 | 0 | ③ 삭제 — 판정이 main에 회수됨 |
| `p3-78/live-output-20261031` | `ea8b9123` | 10-31 | 72 | 5 | 15 | 13 | ③″ 수동 삭제 — `P3-78` done |
| `eos197/a6-authoring-output` | `a786bb70` | 10-28 | 97 | 1 | 13 | 13 | ③″ 수동 삭제 — 13파일 전부 main과 동일 |
| `eos211/cu-hint-output` | `cf9fb1cc` | 10-29 | 83 | 1 | 8 | 8 | ③″ 수동 삭제 — 8파일 전부 main과 동일 |
| `ops/weekly-metrics-20261019T000122Z` | `49d350f0` | 10-19 | 158 | 1 | 1 | 0 | ③″ 수동 삭제 — 추가 행이 main에 정확히 같은 행으로 있음 |
| `ops/weekly-metrics-20261025T235900Z` | `bee15501` | 10-25 | 121 | 1 | 1 | 0 | ③″ 수동 삭제 — 같음 |

`jolly-fermi-6km81l`은 18회차에서 활성 claim(`EOS-194`)이었으나 지금 claim이 없고 `EOS-194`가 done이다 — 그래서 신규 판정 표에 넣었다(최종 커밋은 18회차 이전).

### 2-2. 18회차 이월 (head 전부 불변)

| 브랜치 | head | 18회차 | 지금 | 분류 |
|---|---|---|---|---|
| `relaxed-keller-4wk0b2` | `bd22bf43` | ① `OPS-140` | `OPS-140` done(#1634) | ②′ 보존 — `HARN-311` 증거 샤드(§4) |
| `wonderful-allen-vhbdra` | `af36c2cf` | ① `OPS-140` | 같음 | ②′ 보존 — 같음 |
| `happy-turing-kmrd5z` | `93861f63` | ① `OPS-130` | `OPS-130` done | ③′ claim `OPS-50` 해제 대기 |
| `nice-cray-mbg1mq` | `dbe2e79c` | ① `PED-45` | `PED-45` done | ③′ claim `PED-26` 해제 대기 |
| `brave-franklin-2999u5` | `70aa404d` | ① `MATH-07` | todo | ① 기존 (claim `MATH-06`) |
| `amazing-goldberg-1oc67i` | `777b860f` | ① `OPS-129` | todo | ① 기존 (claim `OPS-34`) |
| `practical-maxwell-kuwl7x` | `187bf271` | ① `OPS-122` | todo | ① 기존 (claim `OPS-104`) |
| `remaining-track-34zvse` | `7fb78470` | ① `HARN-212` | todo | ① 기존 |
| `blissful-lovelace-ubp9tw` | `d4e4b432` | ③′ | 불변 | ③′ claim `OPS-96` 해제 대기 |
| `status-f6qz0c` | `e90d2d6f` | ③′ | 불변 | ③′ claim `EOS-63` 해제 대기 |
| `stoic-hawking-vzumx5` | `a54f628f` | ③′ | 불변 | ③′ claim `QUAL-10` 해제 대기 |
| `friendly-pascal-mnmypk` | `c229d21c` | ④ | 불변 | ④ Kiki 판단 (claim `QUAL-11`) |
| `gracious-cannon-xwn0lh` | `4a51ab09` | ④ | 불변 | ④ Kiki 판단 |
| `status-f9lp65` | `d792c9d0` | ④ | 불변 | ④ `HARN-56`(in_progress) 지목 · claim |
| `backend-audit-event-foundation-29ac1b` | `6507e018` | ② | 불변 | ② `ADMIN-10` todo (PR #880 닫힘) |
| `openrouter-setup-guide-e98dw4` | `f8c0e3b6` | ② | 불변 | ② `VIZ-11` todo |
| `subject-problems-theory-check-7n9n72` | `621b11f9` | ② | 불변 | ② **삭제 절대 금지** 승계 |
| `whymath-coding-architecture-iws58k` | `a8e01be2` | ② | 불변 | ② `ARCH-30` todo |
| `whymath-curriculum-design-6eejrv` | `2f428729` | ② | 불변 | ② `PB-08` todo (PR #802 닫힘) |
| `whymath-issues-review-k20m0w` | `2330a095` | ② | 불변 | ② 승계 |
| `whymath-mvp-plan-architecture-trjg5x` | `c8abbc17` | ② | 불변 | ② 승계 |
| `whymath-pedagogy-review-gdmwhk` | `2915bf4e` | ② | 불변 | ② `PED-26` todo |
| `whymath-pedagogy-review-uqyg79` | `5dc040b3` | ② | 불변 | ② `PED-26` 대조 대상 (PR #675 닫힘) |
| `whymath-service-operations-review-5t5lmv` | `dd3e9475` | ② | 불변 | ② `OPS-112`·`OPS-113`·`A11Y-02` todo |

18회차 표의 나머지 3건(`peaceful-bell-s7mlg8`·`pensive-cerf-guowbr`·`zen-ramanujan-mzr0ug`)은 원격에서 소멸했다.

### 2-3. 분류 합계

| 분류 | 건수 |
|---|---|
| ⓪ 활성·TTL 초과 claim 또는 활성 작업 — 손대지 않음 | 3 |
| ① 회수 필요 | 6 (신규 등재 2 · 기존 태스크 4) |
| ② 추적 중 (②′ 증거 보존 2 포함) | 13 |
| ③ 삭제 배치 등재 | 3 |
| ③′ 삭제 가능하나 claim 해제 대기 | 5 |
| ③″ 삭제 가능하나 허용 패턴 밖 — 수동 삭제 | 5 |
| ④ Kiki 판단 필요 | 4 |
| ⑤ 유예(당일 생성) | 1 |
| **합계** | **40** |

## 3. 판정 근거

### 3-① 신규 회수 — `SEC-45` (fervent-maxwell)

- 고유 커밋 2건: `f4351d44` 런북 신설(`docs/ops/sec34_phaiakes9_credential_rotation_runbook.md` · 920줄 · 작성 기준 main `e30984983`), `95576896` 이벤트 샤드 1줄.
- 추적 여부: `git grep -n -E 'fervent-maxwell|sec34_phaiakes9|credential_rotation_runbook' origin/main` → 0줄. main `docs/ops/`에 대체 런북도 없다.
- 비밀값 스캔: `ghp_`·`sk-`·`pk-lf-`·`AKIA`·`-----BEGIN` 패턴 0건.
- 런북은 작성 뒤 3주가 지나 main이 바뀌었다(ARCH-66 Anthropic API 중단 등). 그래서 `SEC-45` acceptance ②가 이식 전에 시크릿 이름 실재·명령 블록 규칙을 다시 대조하도록 적었다. **런북 실행(실제 폐기·재발급)은 SEC-34(owner kiki) 몫**이며 SEC-45의 범위가 아니다.

### 3-① 신규 회수 — `OPS-161` (weekly-metrics)

- 실행 기록(GitHub Actions `weekly-metrics.yml`): #4(10-05)·#5(10-12) success → **#6(10-19)·#7(10-25)·#8(11-02) failure**. OPS-151(산출물 0회 커밋 수리)이 착지한 직후부터 실패가 시작됐다.
- 세 실행 모두 산출 브랜치가 원격에 있다 = `git push`는 성공했다. PR은 0건이다(`backlog.py branches`가 "PR 이력 0건"으로 분류).
- **원인은 확정하지 못했다.** 실패 잡 로그의 끝 80줄은 서비스 컨테이너 정리 출력뿐이었다. `gh pr create`가 거부됐다는 가설은 위 두 관측과 맞지만 **미확인**이다 — `OPS-161` ②가 원인 실측을 첫 단계로 둔다.
- 원장 대조: main `metrics/weekly.json` 4행 중 10/19·10/25 행은 브랜치의 추가 행과 **정확히 같다**(EOS-197 PR #1765가 수동 반영). 11/02 행(window 10-26~11-02)은 main에 없다.
- `EOS-225`도 같은 원장에 행을 직접 싣는다 — `OPS-161`이 11/02 행을 실을 때 행 순서·중복을 함께 본다.

### 3-② 추적 중 — `eos-compiler-pack-check`

main `docs/architecture/adr/ADR-010-eos-labs-factory-track-freeze.md` 35행과 `docs/strategy/internal_verification_period_policy_2026-12-31.md` 2항이 "머지하지 않고 브랜치를 참고로 보존(D8=(가))·2027-01 재검토"를 명시한다. 백로그에 `ARCH-103` 태스크 파일은 없지만 소유 근거(ADR)가 main에 실재한다. 삭제 금지.

### 3-③ 삭제 배치 3건

| 브랜치 | 소유 태스크 | 잔여 줄(이벤트·MEMORY 제외) | 잔여분 처분 |
|---|---|---|---|
| `jolly-fermi-6km81l` | `EOS-194` done | 16 | 전부 main이 뒤에 갱신한 줄의 옛 판 — CMS 라우트 수 동결 `38`(main은 이후 작업으로 증가), 판정 문서 문장 3줄의 옛 표현. 이벤트 샤드는 main과 동일 |
| `ops-83-inject-shard-failure` | `OPS-83` done · PR #1754 닫힘 | 9 | 5줄은 `tests/backend/test_ops83_injected_failure_4.py` — 커밋 메시지가 "머지 금지"로 밝힌 **고의 실패 주입**(OPS-83 ⑥ 변별력 확인용). 나머지 4줄은 대장·문서의 옛 문면. 샤딩 구현 파일 13종은 main과 blob 동일 |
| `p3-50-02-01-chain-restore` | `P3-50` in_progress (다른 세션 `claude/p3-50-02-01-judgment-recovery`가 회수) | 5 | 판정 문서·게이트 `G-p350-02-01-core-and-route`·acceptance 정정 항이 main에 있다. 잔여는 `session`·`updated` 필드와 정정 문면 미세 차이. 이벤트 샤드 13줄은 main에 없다 — 착수 기록뿐이며 head `4098266c`로 복구 가능 |

### 3-④ Kiki 판단 — `laughing-edison-rb5hgl` (신규)

`docs/reviews/claude_md_university_scope_proposal_2026-10-14.md`(85줄) — CLAUDE.md 「한 줄 정의」의 "중·고등학생"을 대학 학부·초등 자산과 맞추자는 **채택 전 수정안**이다. main 언급 0건이고, main CLAUDE.md의 한 줄 정의는 여전히 "중·고등학생"이다. 내용이 Kiki 결정 사항이고 12/31 방침이 신규 decision 게이트를 금지하므로 **태스크·게이트를 만들지 않고** 이 문서에 판단 요청으로만 올린다. 선택지: (가) 수정안 문서를 main에 옮겨 검토 대상으로 둔다 (나) 폐기하고 브랜치를 삭제한다.

## 4. `OPS-140` 완료 뒤에도 keller·allen을 지우지 않는 이유

`OPS-140`(PR #1634 머지)의 판정 문서는 두 브랜치에서 "이식한 것 / 버린 것"을 명시했고, 같은 문서 244행이 "이 PR 머지 뒤 정리한다"고 적었다. 코드 축으로는 삭제 조건이 충족됐다.

그런데 미완료 `HARN-311`(claim 쓰기 error 시 fail-open 착수 — 병렬 중복 구현 3회차의 코드 대책)의 acceptance ①이 **두 브랜치의 `backlog/events` 샤드를 사고 증거로** 지목한다(`12:37:59Z claim_remote_unavailable status=error → 12:38:00Z start remote=error+readscan_ok`). 두 샤드(17줄·18줄)는 main에 없다. 그리고 `HARN-311`은 12/31 방침 2항으로 2027-01까지 착수가 막혀 있다.

따라서 두 브랜치는 **`HARN-311`이 샤드를 main에 옮기거나 증거를 다른 형태로 고정할 때까지 보존**한다. 스킬 §4 규칙("잔여분마다 후속 소유자를 지목하지 못하면 삭제 후보로 내리지 말라")의 역방향 적용이다 — 후속 소유자가 지목돼 있으므로 그 소유자가 끝날 때까지 남긴다.

## 5. 이번 회차가 드러낸 것

- **회수 태스크 완료 ≠ 브랜치 삭제 가능.** `OPS-140`은 코드 회수를 끝냈지만, 다른 태스크(`HARN-311`)가 같은 브랜치를 증거 저장소로 쓰고 있었다. 완료된 회수 태스크만 보고 삭제했다면 사고 증거가 소실됐을 것이다.
- **산출 브랜치 명명 규칙이 삭제 경로와 맞지 않는다.** Kiki 머신 실행분(`p3-78/`·`eos197/`·`eos211/`)과 예약 워크플로 산출(`ops/weekly-metrics-*`)이 전부 허용 패턴 밖이라, 내용이 main에 들어가도 브랜치는 자동으로 정리되지 않는다. weekly-metrics 축은 `OPS-161` ④가 처분 방식을 정한다. Kiki 머신 실행분 축은 이번에 태스크로 등재하지 않았다(정리 비용이 수동 삭제 5건 수준이라) — 다음 회차에도 같은 형태가 쌓이면 등재한다.

## 6. 조치

- **회수 태스크 등재 2건**: `SEC-45-fervent-maxwell-sec34-rotation-runbook-recovery`(priority 1 · EOS P1) · `OPS-161-weekly-metrics-pr-step-failure`(priority 2 · EOS P1). 둘 다 `backlog.py add` 경유이며 번호는 원격 예약됐다.
- **삭제 배치 18차 3건**: `.github/branch-cleanup-request.txt`에 head SHA 스냅샷과 함께 등재.
- **Kiki 수동 삭제 후보 5건**(허용 패턴 밖 — 내용은 전부 main에 있음):
  `p3-78/live-output-20261031`(`ea8b9123`) · `eos197/a6-authoring-output`(`a786bb70`) · `eos211/cu-hint-output`(`cf9fb1cc`) · `ops/weekly-metrics-20261019T000122Z`(`49d350f0`) · `ops/weekly-metrics-20261025T235900Z`(`bee15501`).
  `ops/weekly-metrics-20261102T012320Z`는 **삭제 금지**(11-02 행의 유일한 사본 — `OPS-161`).
- **Kiki 판단 요청 4건**: 신규 `laughing-edison-rb5hgl`(§3-④) + 17회차부터 미답변 3건(`friendly-pascal-mnmypk`·`gracious-cannon-xwn0lh`·`status-f9lp65`).
- **claim 해제 후 삭제 5건**: `blissful-lovelace-ubp9tw`·`status-f6qz0c`·`stoic-hawking-vzumx5`(17회차부터) + 신규 `happy-turing-kmrd5z`(`OPS-130` done)·`nice-cray-mbg1mq`(`PED-45` done). 단 `nice-cray-mbg1mq`는 claim `PED-26`(todo)이 걸려 있어 그 세션 종료를 기다린다.

## 7. 정직한 공백

- `claims reap`(dry-run 포함)를 실행하지 못했다 — 권한 분류기 거부. claim 상태는 원격 claim 트리를 직접 읽어 판정했다.
- `OPS-161`의 실패 원인은 미확정이다(§3-①). 로그 전체를 읽지 않았다.
- 부재 줄 대조는 줄 전체 일치라 이식량의 상한이다. 각 브랜치 커밋 메시지의 검증 수치는 재현하지 않았다.
- `claude/new-session-hwq1or`는 3시간 전 생성이라 판정을 유예했다. 같은 세션이 PR을 열 수 있다.
- `p3-94/seat-compare-20261106`은 활성 claim `P3-94` 세션 소관이라 내용 판정을 하지 않았다. 같은 날 다른 세션(hwq1or)의 보고가 "seat-*/ 폴더 0건"이라 적었는데, 이 브랜치가 바로 그 데이터다 — 보고 시각(12:57Z)에는 `p3-94/` 접두 브랜치를 보지 않은 것으로 읽힌다(읽어서 그렇게 보인다).
