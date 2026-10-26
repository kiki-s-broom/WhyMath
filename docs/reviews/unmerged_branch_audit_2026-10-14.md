# 미머지 브랜치 전수 감사 18회차 — 2026-10-14

> **판정 기준: main `24d8607d`** (2026-10-14). 이 문서는 그 시점의 스냅샷이며 정본이 아니다.
> 실행 정본은 `backlog/`(회수 태스크)와 `.github/branch-cleanup-request.txt`(삭제 배치)다.
> 선행 판정 `unmerged_branch_audit_2026-10-12.md`(17회차)와 그 보충 `..._deepdive.md`는 수정하지 않는다.
> 이 세션은 시작 시 shallow였고 `git fetch --unshallow origin` + `git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'`로 전제를 복구한 뒤에만 판정했다(`git rev-parse --is-shallow-repository` → false 확인).

## 0. 요약

1. **17회차 이후 신규 고립 1건 — `OPS-126`이 두 브랜치에 이중 구현된 채 PR 없이 방치됐다.** `relaxed-keller-4wk0b2`(`bd22bf43`)와 `wonderful-allen-vhbdra`(`af36c2cf`)는 같은 날(2026-10-12) 13:09Z에 같은 `/health/ready` `sympy_isolation` 섹션을 각자 구현했다. main 부재 줄은 649·696이다. main의 `OPS-126`은 `todo`, `app.py`에 `sympy_isolation` 소비자는 0건, 원격 claim은 13:50Z에 release됐고 열린 PR 14건 중 두 브랜치를 head로 갖는 것은 없다. 회수 태스크 `OPS-140`을 등재하고 `OPS-126`에 `depends_on`으로 부착했다.
2. **원인은 하네스 결함 2종이다(§4).** ① `wonderful-allen`은 시작 시 원격 claim 쓰기가 `error`였는데 착수가 허용돼 12분 뒤의 `relaxed-keller`가 그 존재를 볼 수 없었다 — 병렬 중복 구현의 **3회차**(2026-07-27 `OPS-07` · 2026-09-06 `MP-04` · 이번). 코드 대책 `HARN-311` 등재. ② `relaxed-keller`는 `done --no-pr incomplete`로 닫았다 — 완료인데 "미완" 사유가 CLI에서 합법이다. 17회차의 `HARN-309`(review 전이만 다룸)에 acceptance ⑤를 덧붙였다.
3. **브랜치 전용 태스크 1건 복원** — `relaxed-keller`에만 있던 `OPS-131`을 원 번호·원문 그대로 재등재했다(8개 필드 전부 브랜치 원문과 동일 확인).
4. **17회차 이월 23건은 head가 전부 불변**이다(17회차 표 25건 중 소멸 2건 제외). 소멸 2건은 `adoring-goodall-3dfsdi`(`QUAL-12` done · PR #1589)와 `whymath-ai-recommendation-review-q8tvcx`(16차 삭제 배치 집행 — `ls-remote` 잔존 0/1).
5. **삭제 배치 이번 회차 0건.** 내용이 소멸한 3건은 claim 해제 대기, 3건은 Kiki 판단이 필요하다(§6). 17회차 판단 요청 3건이 아직 답을 받지 못했다.

## 1. 전제 복구와 모집단 분리

| 구분 | 건수 | 내역 |
|---|---|---|
| 원격 ref 전수 | 46 | `git for-each-ref refs/remotes/origin` (HEAD 별칭 제외) |
| 제외 — 판정 대상 아님 | 4 | `main` · `harness-claims` · `harness-reports` · `gh-readonly-queue/main/pr-1591-*`(머지 큐 임시 브랜치) |
| 제외 — 열린 PR이 소유 | 14 | 열린 PR 14건(GitHub MCP `list_pull_requests`) |
| **감사 대상** | **28** | §2 |

산술: 46 − 4 − 14 = 28.

**유령 PR 0건** — 열린 PR 14건의 head가 전부 원격에 실재한다. 방치가 긴 열린 PR(마지막 갱신 기준, 이 감사는 head 실재만 확인): `#844` `#856` `#858` `#865`(08-31) · `#1061` `#1076`(09-08) · `#1145`(09-12) · `#1294`(09-23) · `#1377`(09-29) · `#1410`(10-01, draft).

**claim 대장 대조**(`backlog.py claims list --verbose` 24건 · `claims reap` dry-run): stale 14건(`ttl` 13 · `task_missing` 1), 유예 구간 5건(`branch_gone_recent` — 오늘 생성돼 아직 push 전인 claim: `OPS-130`·`OPS-138`·`OPS-139`·`P3-04`·`PED-45`). 17회차와 같은 14건이다. claim 해제(`claims reap --apply`)는 이 감사의 범위가 아니다.

## 2. 측정과 분류

판정 기준 커밋 `24d8607d`, `B=origin/<브랜치>`:

```bash
git rev-list --left-right --count origin/main...$B                              # behind ahead
git diff --name-only origin/main...$B | wc -l                                   # 내용 diff
git diff --name-only origin/main...$B | grep -cE '^(src|tests|data|scripts)/'   # done-less 사각
```

부재 줄 대조(17회차 방법 승계)는 신규 2건에만 새로 쟀다: 코드·문서(`src` `tests` `scripts` `docs`)의 추가 줄이 main의 같은 경로 파일에 **줄 전체 일치**로 있는지 센다(이벤트 샤드·대장·`MEMORY.md` 제외). 서식만 달라도 부재로 세는 한계가 있다.

| 브랜치 | head | 최종 커밋 | behind | ahead | diff | 코드 | 분류 |
|---|---|---|---|---|---|---|---|
| `peaceful-bell-s7mlg8` | `fdfa09cc` | 2026-10-12 | 40 | 2 | 13 | 7 | ⓪ 활성 claim(MISC-61 · 10-12T07:23Z) |
| `jolly-fermi-6km81l` | `636896a4` | 2026-10-14 | 5 | 1 | 22 | 14 | ⓪ 활성 claim(EOS-194) |
| `pensive-cerf-guowbr` | `81505cb7` | 2026-10-13 | 5 | 2 | 24 | 20 | ⓪ 활성 claim(EOS-195) |
| `zen-ramanujan-mzr0ug` | `11e9c076` | 2026-10-13 | 5 | 2 | 8 | 3 | ⓪ 활성 claim(OPS-137) |
| `relaxed-keller-4wk0b2` | `bd22bf43` | 2026-10-12 | 34 | 2 | 10 | 5 | ① 신규 `OPS-140` |
| `wonderful-allen-vhbdra` | `af36c2cf` | 2026-10-12 | 34 | 1 | 9 | 6 | ① 신규 `OPS-140` |
| `brave-franklin-2999u5` | `70aa404d` | 2026-10-09 | 81 | 2 | 11 | 8 | ① 기존 `MATH-07` |
| `amazing-goldberg-1oc67i` | `777b860f` | 2026-10-09 | 56 | 3 | 6 | 2 | ① 기존 `OPS-129` |
| `happy-turing-kmrd5z` | `93861f63` | 2026-10-09 | 68 | 1 | 8 | 4 | ① 기존 `OPS-130` (claim 신규 세션) |
| `nice-cray-mbg1mq` | `dbe2e79c` | 2026-10-08 | 99 | 2 | 54 | 40 | ① 기존 `PED-45` (claim 신규 세션) |
| `practical-maxwell-kuwl7x` | `187bf271` | 2026-10-03 | 178 | 1 | 5 | 1 | ① 기존 `OPS-122` |
| `remaining-track-34zvse` | `7fb78470` | 2026-08-11 | 803 | 16 | 33 | 23 | ① 기존 `HARN-212` |
| `backend-audit-event-foundation-29ac1b` | `6507e018` | 2026-08-25 | 710 | 3 | 22 | 21 | ② 추적 중 |
| `openrouter-setup-guide-e98dw4` | `f8c0e3b6` | 2026-08-03 | 899 | 13 | 37 | 27 | ② 추적 중 |
| `subject-problems-theory-check-7n9n72` | `621b11f9` | 2026-08-11 | 812 | 34 | 83 | 49 | ② 추적 중 |
| `whymath-coding-architecture-iws58k` | `a8e01be2` | 2026-08-10 | 818 | 1 | 16 | 1 | ② 추적 중 |
| `whymath-curriculum-design-6eejrv` | `2f428729` | 2026-08-11 | 776 | 9 | 6 | 3 | ② 추적 중 |
| `whymath-issues-review-k20m0w` | `2330a095` | 2026-08-11 | 824 | 45 | 133 | 95 | ② 추적 중 |
| `whymath-mvp-plan-architecture-trjg5x` | `c8abbc17` | 2026-08-09 | 865 | 81 | 233 | 188 | ② 추적 중 |
| `whymath-pedagogy-review-gdmwhk` | `2915bf4e` | 2026-08-11 | 812 | 1 | 31 | 21 | ② 추적 중 |
| `whymath-pedagogy-review-uqyg79` | `5dc040b3` | 2026-08-03 | 893 | 38 | 76 | 51 | ② 추적 중 |
| `whymath-service-operations-review-5t5lmv` | `dd3e9475` | 2026-08-11 | 808 | 6 | 33 | 17 | ② 추적 중 |
| `blissful-lovelace-ubp9tw` | `d4e4b432` | 2026-10-02 | 199 | 2 | 15 | 13 | ③' 흡수됨 · claim 해제 후 삭제 |
| `status-f6qz0c` | `e90d2d6f` | 2026-09-01 | 636 | 0 | 0 | 0 | ③' 빈 브랜치 · claim 해제 후 삭제 |
| `stoic-hawking-vzumx5` | `a54f628f` | 2026-10-06 | 147 | 1 | 2 | 0 | ③' claim 기록뿐 · claim 해제 후 삭제 |
| `friendly-pascal-mnmypk` | `c229d21c` | 2026-10-03 | 194 | 2 | 7 | 4 | ④ 흡수됨 · Kiki 보존 지시와 충돌 |
| `gracious-cannon-xwn0lh` | `4a51ab09` | 2026-10-09 | 63 | 1 | 2 | 0 | ④ 취소 지시가 main과 충돌 |
| `status-f9lp65` | `d792c9d0` | 2026-09-03 | 619 | 2 | 5 | 2 | ④ `HARN-56`이 지목 |

| 분류 | 건수 |
|---|---|
| ⓪ 활성 claim — 손대지 않음 | 4 |
| ① 회수 필요 | 8 (신규 등재 1 · 기존 태스크 7) |
| ② 추적 중 | 10 |
| ③' 삭제 가능하나 claim 해제 대기 | 3 |
| ④ Kiki 판단 필요 | 3 |

합계 4 + 8 + 10 + 3 + 3 = 28(감사 대상).

## 3. 판정 근거

### ⓪ 활성 claim 4건 — 손대지 않음

`peaceful-bell`(`MISC-61`, 태스크 `in_progress`, claim 46시간 경과 — TTL 72h는 10-15T07:23Z)과 `jolly-fermi`(`EOS-194`) · `pensive-cerf`(`EOS-195`) · `zen-ramanujan`(`OPS-137`)은 각 태스크가 `in_progress`이고 claim이 약 8시간 이내(앞 하나만 46시간)다. 세션이 PR 없이 끝나면 다음 회차의 ①이 된다. 17회차의 `HARN-309`가 막으려는 바로 그 경로다.

### ① 회수 필요 8건

**신규 — `relaxed-keller` + `wonderful-allen` → `OPS-140`.** 이중 구현이다.

| 항목 | `relaxed-keller` | `wonderful-allen` |
|---|---|---|
| 시작 | 12:50:48Z, 원격 claim `ok` | 12:38:00Z, 원격 claim `error`(`claim_remote_unavailable`) |
| 끝 | 13:50:58Z `done` + `no_pr_reason=incomplete`, claim release | 태스크 `in_progress`로 둠, claim 없음 |
| 산출 | `/health/ready` `sympy_isolation` · 상한 5.0초·워커 2 유지 판정 · `OPS-131` 분리 · 커밋 메시지상 전체 스위트·CI 잡 재현 통과 | 같은 섹션 + 세 비율의 합이 1이 되는 산술과 분모 0 → `null` 의미론 + 워커 RSS 실측 도구 + 테스트 12건·뮤테이션 8종 |
| main 부재 | 649/681줄 | 696/721줄 |

main 이중 확인: `git grep sympy_isolation origin/main`의 `app.py` 0건, 두 브랜치의 `app.py`에는 있다. 두 브랜치 간 diff는 777+/731−로 같은 파일 5개를 서로 다르게 고쳐 **통째 병합이 불가능**하다. 어느 쪽이 기준이어야 하는지는 이 감사가 정하지 않았다 — 대장 `done` 표기는 근거가 못 된다(`done`인 쪽이 `--no-pr incomplete`로 닫혔다). `OPS-140` acceptance ②가 "두 브랜치 테스트를 각각 main 위에서 돌려 기준을 정하라"를 요구한다.

**브랜치 전용 태스크 복원 — `OPS-131`.** `relaxed-keller`에만 있고 main에 번호가 없었다(원격 예약만 존재). 원 번호로 CLI 재등재, 브랜치 원문과 `title`·`acceptance`·`paths`·`track`·`stage`·`priority`·`eos_priority`·`layer` 8개 필드 동일 확인, `depends_on=[OPS-126]`. 원 예약(`relaxed-keller`, 10-12T13:05Z)은 곧 만료될 상태였으나 이 등재가 2026-10-14T05:24:39Z에 재예약했다(원격 `reservations/OPS-131.json` 실측 · 만료 2026-10-17T05:24Z경). **이 PR이 그 전에 착지해야 번호가 영구 귀속된다.**

**기존 태스크 7건 — 변동 없음.**

| 브랜치 | 소유 태스크 | main 상태 | 비고 |
|---|---|---|---|
| `brave-franklin` | `MATH-07` | todo | head 불변 · claim 없음 |
| `amazing-goldberg` | `OPS-129` | todo | head 불변 · claim 없음 |
| `happy-turing` | `OPS-130` | todo | **새 세션이 오늘 05:18Z claim**(`funny-edison-26h9wb`, 브랜치 push 전) — 회수 진행 중 |
| `nice-cray` | `PED-45` | todo | **새 세션이 오늘 05:18Z claim**(`eloquent-shannon-czqpqc`, push 전) — 회수 진행 중 |
| `practical-maxwell` | `OPS-122` | todo | head 불변 |
| `remaining-track` | `HARN-212` | todo | head 불변 |

17회차가 등재한 복원 태스크 `ARCH-72` · `HARN-304` · `PED-44` · `REND-05`는 PR #1593 착지로 main에 `todo`로 실재한다.

### ② 추적 중 10건 — 좌석 상실 0

head 불변 10/10. 좌석 태스크를 main 기준으로 재조회했다: `MISC-01/03/05/06` · `PB-02` · `PED-14` · `S3-33/34` · `HARN-79` · `HARN-213`(`7n9n72`) · `ADMIN-02` · `PATH-03` · `S4-20`(`trjg5x`) · `SEC-30` · `MGMT-03` · `HARN-25` · `ARCH-102` · `S4-22`(`k20m0w`) · `PED-45`(`gdmwhk`/`uqyg79`) · `OPS-112` · `OPS-113` · `A11Y-02`(`5t5lmv`) · `ARCH-30`(`iws58k`) · `PB-08`(`6eejrv`) · `VIZ-11`(`e98dw4`) · `ADMIN-10`(`29ac1b`) — **전부 `todo`**. `HARN-79`·`ARCH-102`는 파일명이 `<ID>.yaml`(슬러그 없음)이라 첫 조회에서 "부재"로 나왔다가 재확인했다.

16차에서 회수 완료로 삭제된 `q8tvcx`의 좌석 `OPS-38`·`SEC-32`는 `done`이다(이번 표에서 제외).

### ③' 삭제 가능하나 claim 해제 대기 3건 (배치 제외)

`blissful-lovelace-ubp9tw`(`d4e4b432` · `OPS-123` done) · `status-f6qz0c`(`e90d2d6f` · ahead 0) · `stoic-hawking-vzumx5`(`a54f628f` · claim 기록뿐). 17회차와 같은 사유·같은 head다. 세 건 모두 `claims reap` dry-run이 stale로 지목했다. `claims reap --apply`가 아직 실행되지 않았으므로 새 증거가 없어 선례를 따랐다.

### ④ Kiki 판단 필요 3건

`friendly-pascal-mnmypk` · `gracious-cannon-xwn0lh` · `status-f9lp65` — 17회차 §3-④와 head가 같고 새 증거가 없다. 판단 요청은 §6에 승계한다.

## 4. 구조적 원인과 대책

### 4-1. claim 쓰기 실패 상태에서 착수가 허용됨 → `HARN-311`

두 세션의 이벤트 샤드(`backlog/events/claude_*.ndjson`)에서 읽은 순서다.

> 실측: `wonderful-allen` 12:37:59Z `claim_remote_unavailable status=error` → 12:38:00Z `start remote=error+readscan_ok`. 이어서 `relaxed-keller` 12:50:48Z `start remote=ok`. `wonderful-allen`의 첫 커밋은 13:09Z다.

`wonderful-allen`은 다른 세션의 claim을 **읽는 데는** 성공했지만(`readscan_ok`) 자기 claim을 **쓰는 데는** 실패했고, 그 상태로 착수했다. 12분 뒤 시작한 `relaxed-keller`의 읽기 스캔은 claim도 브랜치도 없어 아무것도 볼 수 없었다. `HARN-07`(done)은 읽기 쪽을 닫았을 뿐 **내 claim이 안 올라간 경우의 가시성**은 닫지 않았다. 이것은 병렬 중복 구현의 3회차다: 2026-07-27 `OPS-07`(735줄 폐기) · 2026-09-06 `MP-04`(40분 구현 전량 폐기) · 2026-10-12 `OPS-126`.

- **한계(미규명)**: 12:37:59Z에 claim 쓰기가 **왜** 실패했는지는 이벤트에 `error` 한 줄뿐이라 이 감사가 재현하지 못했다. `HARN-311` acceptance ②가 start의 실패 원인(HTTP 상태·git stderr·타임아웃) 기록과 건수 분포 측정을 요구한다. main 이벤트 샤드의 `claim_remote_unavailable` 누계는 5건이나, 브랜치에만 있는 샤드는 이 수치에 안 들어가므로 상시 실패 여부를 판정할 수 없다.
- **대책**: `HARN-311` 등재(P2 · 선택지 (가) 거부+우회 플래그 (나) 즉시 브랜치 push (다) 혼합은 태스크가 판정). 산문 규칙은 추가하지 않는다(2026-09-20 등재 동결).

### 4-2. `done --no-pr incomplete`가 합법 — `HARN-309` ⑤ 추가

`relaxed-keller`는 13:50:58Z에 `OPS-126`을 `done`으로 닫으면서 `no_pr_reason=incomplete`를 썼다. 같은 브랜치 마지막 커밋의 메시지는 전체 스위트·CI 잡 재현 통과를 적었다. 완료와 미완이 한 이벤트에 공존한다. `HARN-309`(17회차)는 `review` 전이의 PR 증적만 다루므로 이 경로는 열린 채 남는다. 새 태스크를 만들지 않고 acceptance ⑤를 덧붙였다(append 전용 — 중복 등재 방지).

### 4-3. 야간 고립 리포트에 두 브랜치가 없었던 이유 — 미확인

세션 브리핑의 고립 목록(2026-10-13T22:31Z 스냅샷, isolated 16건)에 `relaxed-keller`·`wonderful-allen`이 없다. `backlog.py branches`는 "타 세션 진행중 11건"을 **개수로만** 출력해 두 브랜치의 개별 분류를 확인하지 못했다. 마지막 커밋이 33시간 이내라 최근 활동 구간으로 분류됐을 가능성은 있으나, 분류 코드를 읽지 않았으므로 **추정이다.**

## 5. 정직한 공백

- **부재 줄 대조의 한계**: 줄 전체 일치라 서식만 달라도 부재로 센다. `OPS-126` 두 브랜치의 649·696줄은 "이식할 양의 상한"이지 정확한 필요량이 아니다. 17회차 이월 브랜치는 head 불변 확인만 했고 부재 줄을 다시 재지 않았다.
- **`OPS-140`의 기준 구현 선택은 이 감사가 하지 않았다.** 두 브랜치의 테스트를 실행하지 않았다. 커밋 메시지가 말하는 검증 수치(테스트 12건·뮤테이션 8종·전체 스위트 통과)는 **인용일 뿐 재현하지 않았다.**
- ②의 10건은 head 불변과 좌석 `status`만 재확인했다. 좌석 acceptance 본문 재정독과 코드·테스트 재대조는 하지 않았다(17회차 결과 승계). 열린 PR 14건은 head 실재만 확인했다.
- `claims reap --apply`는 실행하지 않았다. 이번 감사는 소스·테스트를 건드리지 않아 전체 백엔드 스위트를 돌리지 않았다. 회수 태스크의 이식은 이 감사의 범위가 아니다 — `/drive`가 실행한다.
- **등재 시 실수 1건과 정정**: `HARN-311`을 처음 등재할 때 `paths`에 존재하지 않는 `scripts/harness/claims.py`를 추측으로 적었다. `claim_remote_unavailable`을 내는 곳이 `backlog.py` 하나뿐임을 grep으로 확인하고 `amend --path --drop-scope`로 정정했다. `OPS-131` notes의 "acceptance 3항"은 원문이 1항 안의 세 문단이라 `--notes-replace`로 정정했다. 두 정정 모두 이벤트 대장에 사유와 함께 남았다.
- **번호 예약 TTL**: `OPS-140`(05:24:19Z) · `OPS-131`(05:24:39Z) · `HARN-311`(05:28:48Z)의 예약이 원격 `harness-claims`에 실재함을 `git show origin/harness-claims:reservations/<번호>.json`으로 확인했다(2026-10-14, 브랜치 `claude/dazzling-turing-uxe03b`). 72시간 TTL이므로 이 PR이 2026-10-17경까지 착지해야 번호가 대장에 영구 귀속된다.

## 6. Kiki 판단 요청 (17회차 승계 — 아직 답 없음)

1. `claims reap --apply`로 stale claim 14건을 풀어도 되는가 — 풀면 §3-③'의 3건이 다음 배치에 오른다. 이번에는 `OPS-34`(`amazing-goldberg`)·`OPS-50`(`happy-turing`)·`MATH-06`(`brave-franklin`)·`PED-26`(`nice-cray`) 등 회수 대상 브랜치의 claim도 포함되어 있다. 회수 태스크(`OPS-129` · `OPS-130` · `MATH-07` · `PED-45`)가 소유 태스크에 `depends_on`으로 붙어 있으므로 해제해도 중복 구현 경로는 열리지 않는다.
2. `friendly-pascal-mnmypk`의 보존 지시(2026-10-09)가 `QUAL-15` done 이후에도 유효한가. 유효하면 보존하고, 아니면 `gracious-cannon-xwn0lh`와 함께 다음 배치에 올린다.
3. `status-f9lp65`를 `HARN-56` 소유자가 아직 쓰는가.
