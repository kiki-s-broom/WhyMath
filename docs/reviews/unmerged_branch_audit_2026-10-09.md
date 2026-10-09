# 미머지 브랜치 전수 감사 16회차 — 2026-10-09

> **판정 기준: main `15220b9f`** (2026-10-09). 이 문서는 그 시점의 스냅샷이며 정본이 아니다.
> 실행 정본은 `backlog/`(회수 태스크)와 `.github/branch-cleanup-request.txt`(삭제 배치)다.
> 선행 판정 `unmerged_branch_audit_2026-10-02.md`(14회차)는 수정하지 않는다.
> **15회차(`2026-10-03`)는 main에 없었다** — 그 산출물이 PR 없이 `claude/magical-maxwell-99n5e8`에 고립돼 있어 이 PR이 byte 그대로 이식했다(`git hash-object` 일치 확인). 15회차 문서의 판정은 §2에서 승계·갱신한다.
> 이 세션은 시작 시 shallow였고 `git fetch --unshallow origin` + `git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'`로 전제를 복구한 뒤에만 판정했다.

## 0. 요약

1. **15회차 산출물 자체가 고립돼 있었다.** 직전 감사 세션이 판정 문서·회수 태스크 `HARN-212`·14차 삭제 배치를 브랜치에만 남겼다. 이 PR이 문서를 이식하고 `HARN-212`를 같은 번호로 재등재한다(전 원격 브랜치에서 그 번호의 유일한 사용처임을 실측).
2. **미추적 고립 구현 3건 발견** — 전부 원격 claim이 TTL(72h)을 넘긴 stale 상태이고 main 태스크는 `todo`다. 세션이 `/drive`로 집으면 같은 구현을 처음부터 반복한다. 회수 태스크 3건(`QUAL-15`·`OPS-122`·`OPS-123`)을 등재하고 소유 태스크 3건에 `depends_on`으로 부착했다.
3. **분실된 태스크 등재 3건 복원** — `HARN-212`·`QUAL-12`·`OPS-108`이 브랜치에서만 등재돼 있었다. 원래 번호로 CLI 재등재(번호 충돌 0 실측).
4. **좌석이 소멸한 구형 브랜치 3개 삭제 가능** — `t608mk`·`azdnov`·`vafylb`. 소유 태스크 `OPS-41`·`OPS-53`이 done이 됐고 잔여 diff를 재열거한 결과 실질 손실이 없다.
5. 삭제 가능 총 10건을 14차 삭제 배치에 등재(15회차가 낸 2건 `tbj2jf`·`7x90dj` 포함). claim 해제 후 삭제 가능 3건은 배치에서 뺐다.

## 1. 전제 복구와 모집단 분리

| 구분 | 건수 | 내역 |
|---|---|---|
| 원격 ref 전수 | 61 | `git for-each-ref refs/remotes/origin`(HEAD 제외) |
| 제외 — 판정 대상 아님 | 3 | `main` · `harness-claims` · `gh-readonly-queue/main/pr-1507-*`(머지 큐 임시 브랜치) |
| 제외 — 열린 PR이 소유 | 27 | 열린 PR 27건(GitHub MCP `list_pull_requests`) |
| 제외 — 원격 claim 활성 · PR 없음 | 3 | `brave-franklin-2999u5`(MATH-06) · `nice-cray-mbg1mq`(PED-26) · `vibrant-pascal-9ebi61`(ADMIN-18·S4-64) |
| **감사 대상** | **28** | §2 |

산술: 61 − 3 − 27 − 3 = 28.

**유령 PR 0건** — 열린 PR 27건의 head가 전부 원격에 실재한다.

**claim 대장 대조**(`harness-claims` 트리 직접 조회, 19건): `claims reap`(dry-run, 삭제 안 함)이 **stale 10건**을 지목했다(`ttl` 9 · `task_missing` 1). 이 중 PR이 없는 브랜치는 §3의 대상이며, claim이 stale이어도 해제는 이 감사의 범위가 아니라 판정에서 "claim 해제 후"로 분리했다. `status-38gu4d`(OPS-73)·`s4-70-pila8m`(S4-70)은 claim JSON이 가리키는 브랜치가 원격에 없다(미push) — 기록만 하고 건드리지 않았다.

## 2. 3축 측정과 4분류

측정 명령(전 브랜치 공통, `B=origin/<브랜치>`):

```bash
git rev-list --left-right --count origin/main...$B                              # behind ahead
git diff --name-only origin/main...$B | wc -l                                   # 내용 diff
git diff --name-only origin/main...$B | grep -cE '^(src|tests|data|scripts)/'   # done-less 사각
```

| 브랜치 | head | 최종 커밋 | behind | ahead | diff | 코드 | 분류 |
|---|---|---|---|---|---|---|---|
| `admiring-hamilton-onojq9` | `f6bf7755` | 2026-10-07 | 33 | 1 | 1 | 0 | ③ 삭제 |
| `backend-audit-event-foundation-29ac1b` | `6507e018` | 2026-08-25 | 634 | 3 | 22 | 21 | ② 추적 중 |
| `blissful-lovelace-ubp9tw` | `d4e4b432` | 2026-10-02 | 123 | 2 | 15 | 13 | ① OPS-123 |
| `crosslink-signature-mm6kie` | `a48a0e9e` | 2026-10-05 | 72 | 2 | 7 | 4 | ③ 삭제 |
| `dreamy-carson-7x90dj` | `3b45cd97` | 2026-10-02 | 117 | 1 | 1 | 0 | ③ 삭제 |
| `friendly-pascal-mnmypk` | `c229d21c` | 2026-10-03 | 118 | 2 | 7 | 4 | ① QUAL-15 (+QUAL-12) |
| `intelligent-noether-tbj2jf` | `c671a313` | 2026-09-30 | 135 | 1 | 2 | 0 | ③ 삭제 |
| `magical-maxwell-99n5e8` | `bea5ebc5` | 2026-10-03 | 99 | 1 | 5 | 0 | ③ 삭제 |
| `openrouter-setup-guide-e98dw4` | `f8c0e3b6` | 2026-08-03 | 823 | 13 | 37 | 27 | ② 추적 중 |
| `practical-maxwell-kuwl7x` | `187bf271` | 2026-10-03 | 102 | 1 | 5 | 1 | ① OPS-122 (+OPS-108) |
| `remaining-track-34zvse` | `7fb78470` | 2026-08-11 | 727 | 16 | 33 | 23 | ① HARN-212 |
| `sleepy-feynman-skndtr` | `0490f7e6` | 2026-10-06 | 54 | 6 | 2 | 0 | ③ 삭제 |
| `status-f6qz0c` | `e90d2d6f` | 2026-09-01 | 560 | 0 | 0 | 0 | ③' claim 해제 후 |
| `status-f9lp65` | `d792c9d0` | 2026-09-03 | 543 | 2 | 5 | 2 | ③' claim 해제 후 |
| `stoic-hawking-vzumx5` | `a54f628f` | 2026-10-06 | 71 | 1 | 2 | 0 | ③' claim 해제 후 |
| `subject-problems-theory-check-7n9n72` | `621b11f9` | 2026-08-11 | 736 | 34 | 83 | 49 | ② 추적 중 |
| `vibrant-darwin-39xler` | `822b001b` | 2026-10-06 | 66 | 1 | 1 | 0 | ③ 삭제 |
| `whymath-ai-content-design-vafylb` | `b1218739` | 2026-08-10 | 759 | 8 | 7 | 1 | ③ 삭제 |
| `whymath-ai-recommendation-review-q8tvcx` | `e1835c0c` | 2026-08-07 | 801 | 3 | 11 | 2 | ② 추적 중 |
| `whymath-coding-architecture-iws58k` | `a8e01be2` | 2026-08-10 | 742 | 1 | 16 | 1 | ② 추적 중 |
| `whymath-constitution-rules-check-azdnov` | `c335a787` | 2026-08-11 | 736 | 1 | 5 | 0 | ③ 삭제 |
| `whymath-curriculum-design-6eejrv` | `2f428729` | 2026-08-11 | 700 | 9 | 6 | 3 | ② 추적 중 |
| `whymath-data-platform-design-t608mk` | `d876b523` | 2026-08-11 | 732 | 1 | 7 | 0 | ③ 삭제 |
| `whymath-issues-review-k20m0w` | `2330a095` | 2026-08-11 | 748 | 45 | 133 | 95 | ② 추적 중 |
| `whymath-mvp-plan-architecture-trjg5x` | `c8abbc17` | 2026-08-09 | 789 | 81 | 233 | 188 | ② 추적 중 |
| `whymath-pedagogy-review-gdmwhk` | `2915bf4e` | 2026-08-11 | 736 | 1 | 31 | 21 | ② 추적 중 |
| `whymath-pedagogy-review-uqyg79` | `5dc040b3` | 2026-08-03 | 817 | 38 | 76 | 51 | ② 추적 중 |
| `whymath-service-operations-review-5t5lmv` | `dd3e9475` | 2026-08-11 | 732 | 6 | 33 | 17 | ② 추적 중 |

| 분류 | 건수 |
|---|---|
| ① 회수 필요 | 4 (`34zvse` · `mnmypk` · `kuwl7x` · `ubp9tw`) |
| ② 추적 중 | 11 |
| ③ 삭제 가능 | 10 |
| ③' claim 해제 후 삭제 가능 | 3 |

합계 4 + 11 + 10 + 3 = 28(감사 대상). 15회차 대비 head가 바뀐 구형 17건은 **0건**(전부 불변).

## 3. 판정 근거

### ① 회수 필요 4건

판정 방법: 브랜치가 추가한 줄(`git diff -U0`의 `+` 줄)을 main의 같은 경로 파일에서 줄 전체 일치(`grep -qxF` 동치)로 찾아 **부재 줄**을 센다. 서식·주석만 달라도 부재로 세는 한계가 있어, 부재 줄이 있는 파일은 열어서 대체 여부를 확인했다.

1. **`remaining-track-34zvse`** (`7fb78470`) → **HARN-212**. 15회차 판정 승계 — MEMORY 결정 로그 2블록(`구현·MATH-05`·`구현·CUR-07`)이 main에 0건임을 재확인(`grep -c` 0). 좌석 CUR-04·05·07·08·HARN-80 전부 done. 코드·코퍼스는 흡수됐거나 main이 대체. 15회차가 등재만 하고 브랜치에 남긴 태스크를 이 PR이 재등재했다.
2. **`friendly-pascal-mnmypk`** (`c229d21c`) → **QUAL-15** + **QUAL-12**(분실 복원). QUAL-11 교정(발문 "X의 자리까지"·코퍼스 600행 재생성·Decimal.quantize 독립 계산 동결 테스트) 구현이 브랜치에만 있다. main 생성기의 `자리까지` 0건 vs 브랜치 10건. 코퍼스 600행·테스트 84줄·QUAL-12 YAML 23줄 전부 main 부재. 원격 claim `QUAL-11`은 2026-10-02T11:45Z — TTL 초과.
3. **`practical-maxwell-kuwl7x`** (`187bf271`) → **OPS-122** + **OPS-108**(분실 복원). OPS-104 판정 문서(89줄)·전제 동결 테스트(149줄·35건)·후속 태스크 OPS-108이 브랜치에만 있다. 운영 코드 변경은 없다(판정 무변경). 3산출물 main 부재.
4. **`blissful-lovelace-ubp9tw`** (`d4e4b432`) → **OPS-123**. OPS-96 WIP — `l3/isolated_call.py`(315줄 워커 풀)·서빙 경로 배선·테스트 23건이 브랜치에만 있고 커밋 메시지가 미완 3항(tests/infra 경계·전체 스위트·문서)을 스스로 밝힌다. main이 `coach.py`·`verify.py`·`config.py`를 그 뒤로 진화시켜(부재 줄 합 약 140) 통째 이식 불가 — 변경 의도 재적용으로 지정했다.

세 회수 태스크는 소유 태스크(QUAL-11·OPS-104·OPS-96)를 `depends_on`으로 막는다. **정직한 기록**: 부착 전의 깨끗한 main에서도 이 3건은 이미 원격 claim 때문에 `next` 후보가 아니었으므로, 이 부착의 효과는 후보 목록 대조로 변별되지 않는다. `depends_on` 선언은 YAML에서 확인했고, claim이 해제된 뒤 회수 없이 착수되는 경로를 막는 안전장치다.

### ② 추적 중 11건 — 좌석 상실 0

head 불변 11/11. 좌석 태스크 status는 main 기준 전수 조회했다(2026-10-09).

| 브랜치 | 살아 있는 좌석(전부 `todo`) | 15회차 대비 |
|---|---|---|
| `7n9n72` | MISC-01/03/05/06 · PB-02 · PED-14 · S3-33/34 · HARN-79 · HARN-213 — **삭제 절대 금지** | OPS-41·PB-14 done으로 빠짐 |
| `trjg5x` | ADMIN-02 · PATH-03 · S4-20 | PB-14 done |
| `k20m0w` | SEC-30 · MGMT-03 · HARN-25 · ARCH-102 · S4-22 | SEC-19 done |
| `gdmwhk` / `uqyg79` | PED-26 (원격 claim 활성 `nice-cray-mbg1mq`) | 동일 |
| `5t5lmv` | OPS-112 · OPS-113 · A11Y-02 | **OPS-40 done(PR #1466)으로 좌석 이관** — 모바일 구현은 main 부재라 승계 태스크가 소유 |
| `iws58k` | ARCH-30 | 동일 |
| `6eejrv` | PB-08 | 동일 |
| `e98dw4` | VIZ-11 | 동일 |
| `q8tvcx` | OPS-38 · OPS-67 | OPS-41 done으로 빠짐 |
| `29ac1b` | ADMIN-10 ⑦ — `docs/architecture/90_audit_log.md`가 main 부재(재확인) | 동일 |

`5t5lmv`는 이번 회차에 좌석이 바뀐 유일한 곳이다. `OPS-40` 처분 기록(PR #1466)이 "구현은 Flutter 부재로 미이식·승계 등재 OPS-112·A11Y-02·OPS-113"이라고 적었고, 세 승계 태스크가 모두 `todo`이며 notes가 이 브랜치를 지목한다. `update_required.dart`·`update_required_test.dart`·`accessibility_coverage_governance_test.dart`가 main 부재임을 실측했다.

### ③ 삭제 가능 10건

1. **`whymath-data-platform-design-t608mk`** (`d876b523`): `OPS-41` done(PR #1472). r2 문서 비공백 324줄이 main의 `data_platform_eos_frame_gap_review_2026-08-11.md`에 **부재 0줄**(이름이 바뀌어 착지). 태스크 YAML 4건은 `OPS-114`·`OPS-115`로 재채번돼 부재로 센 줄이 전부 단어 겹침 97~100%(줄 포맷 차이). MEMORY 결정 로그는 main 2329행에 실재.
2. **`whymath-constitution-rules-check-azdnov`** (`c335a787`): `OPS-41` done. 판정서 `id_renumber_verdict_2026-08-11.md` 부재 0줄. `HARN-22` YAML은 `HARN-213`으로 재채번(겹침 100%).
3. **`whymath-ai-content-design-vafylb`** (`b1218739`): 좌석 `OPS-53`·`HARN-190` done. cp949 코드 수정은 `OPS-53`(PR #1475)이 진입점 재구성(`scripts/harness/_stdio.py`의 `ensure_utf8_stdio`, `errors="backslashreplace"`)으로 대체했다. 강등전 기록 문서는 `S4-59`가 byte-diff 0으로 이식. MEMORY 3블록 중 08-09분은 `S4-59`가 백필, 나머지 2블록은 고유 토큰 27개 중 main에 없는 것이 구절 1·커밋 해시 1뿐.
4. **`intelligent-noether-tbj2jf`** (`c671a313`): `SEC-42` done. 게이트 `G-eos37-erasure-kpi-disposition`의 브랜치 `evidence`가 main `evidence`의 부분 문자열로 **포함됨**(재실측 True) · 양쪽 status `cleared`.
5. **`dreamy-carson-7x90dj`** · **`admiring-hamilton-onojq9`** · **`vibrant-darwin-39xler`**: 이벤트 샤드 1개뿐(각 25 · 33 · 7줄). 전부 `policy_warn`(착수 시도가 타 세션 claim으로 거부된 기록). 코드·태스크 변경 0.
6. **`sleepy-feynman-skndtr`** (`0490f7e6`): `MISC-43` 철회 종결 기록(PR #1487 닫힘). 대체 결정이 main `MEMORY.md` 435행에 있다.
7. **`crosslink-signature-mm6kie`** (`a48a0e9e`): 10-05 중간 서명 판정이다. main은 10-06 Kiki 재판정(승인 4 · 보류 1 · 코퍼스 68행)이 최종이다. 이 브랜치가 신설한 보류 게이트 `G-misc40-deferred-two-rows-redecision`(M0515·M0671)은 두 행이 10-06에 승인돼 근거가 소멸했고, 새 보류 행 M0599는 main의 `G-misc40-deferred-m0599-redecision`(pending)이 추적한다.
8. **`magical-maxwell-99n5e8`** (`bea5ebc5`): 15회차 산출물 전량을 이 PR이 이식했다 — 판정 문서(byte 동일) · `HARN-212`(재등재) · 14차 삭제 배치(이 PR의 배치가 승계). 이벤트 샤드 1개는 이식하지 않았다.

### ③' claim 해제 후 삭제 가능 3건 (배치 제외)

- **`status-f6qz0c`** (`e90d2d6f`): ahead 0 · diff 0 — 잃을 내용 없음. claim `EOS-63`은 TTL 초과.
- **`status-f9lp65`** (`d792c9d0`): 백업 스케줄 등록 스크립트의 `-ErrorAction Stop` 수정이 main에 더 완성된 형태(관리자 권한 사전 점검 + 두 등록 지점)로 있고, main 테스트가 같은 근거 문구를 갖는다. 단 main `HARN-56`의 `session` 필드가 이 브랜치를 가리키고 상태는 `in_progress`다.
- **`stoic-hawking-vzumx5`** (`a54f628f`): `QUAL-10` claim 기록 커밋뿐(YAML 3줄 + 샤드). claim은 TTL 초과(`claims reap` dry-run `ttl`).

세 건 모두 `claims reap` dry-run이 stale로 지목했으나, 선행 감사(10-02 · 10-03)가 claim 활성 브랜치를 판정 보류로 둔 선례를 따라 삭제하지 않았다. `claims reap --apply`로 claim이 풀리면 다음 배치에 오른다.

## 4. 정직한 공백

- **부재 줄 대조의 한계**: 줄 전체 일치라 서식만 달라도 부재로 센다. `t608mk`·`azdnov`는 단어 겹침 비율로 보완했고 `vafylb`의 MEMORY는 고유 토큰(수치·식별자) 존재 여부로 보완했다. `vafylb` 서술 원문 2블록은 head `b1218739`로만 복구된다.
- `f9lp65`의 런북(`db_backup_dr_runbook.md`)·테스트는 줄 단위가 아니라 대응 단언과 핵심 문구의 존재로 확인했다.
- `34zvse`의 코드·테스트 대조는 15회차 문서의 결과를 승계했고(`test_coach_grade_standard_code.py` 등 3개 테스트 파일의 부재 줄은 열어 읽지 않았다) 이번에 재수행하지 않았다.
- ② 추적 11건은 head 불변과 좌석 `status`·좌석 notes의 브랜치 지목만 재확인했다. 좌석 acceptance 본문 재정독은 하지 않았다(`5t5lmv` 제외).
- `mm6kie`의 10-05 판정 이력은 세 가지 판본이 공존한다(#1454 전건 승인 · 이 브랜치의 승인 3·보류 2 · main 게이트 evidence의 승인 4·보류 1). 최종은 10-06 재판정이라 삭제에 영향이 없지만 10-05 당일 실제 서명이 어느 쪽이었는지는 이 감사가 판정하지 못한다.
- 열린 PR 27건은 head 실재만 확인했다. 방치가 긴 PR(마지막 갱신 기준): `#844` `#856` `#858` `#865`(08-31) · `#1061` `#1076`(09-08) · `#1145`(09-12). PR `#1478`(`friendly-dijkstra`)은 main의 같은 게이트가 이미 `cleared`라 중복일 가능성이 있다 — **확인하지 못했다**.
- 회수 태스크 `QUAL-15`는 PR 소유 태스크 `PB-09`(#1544)와 같은 생성기·코퍼스 경로를 선언한다(`add` 시 경고). 이식 시점에 충돌 여부를 먼저 확인해야 한다.
- 이번 감사는 소스·테스트를 건드리지 않아 전체 백엔드 스위트를 돌리지 않았다.
- 회수 태스크의 이식은 이 감사의 범위가 아니다 — `/drive`가 실행한다.
