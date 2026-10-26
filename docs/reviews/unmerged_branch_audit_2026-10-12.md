# 미머지 브랜치 전수 감사 17회차 — 2026-10-12

> **판정 기준: main `d873d064`** (2026-10-12). 이 문서는 그 시점의 스냅샷이며 정본이 아니다.
> 실행 정본은 `backlog/`(회수 태스크)와 `.github/branch-cleanup-request.txt`(삭제 배치)다.
> 선행 판정 `unmerged_branch_audit_2026-10-09.md`(16회차)는 수정하지 않는다.
> 이 세션은 시작 시 shallow였고 `git fetch --unshallow origin` + `git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'`로 전제를 복구한 뒤에만 판정했다.

## 0. 요약

1. **16회차의 14차 삭제 배치 11건은 전건 집행됐다**(`ls-remote` 잔존 0/11 실측). 회수 필요로 판정한 4건 중 2건(`QUAL-15`·`OPS-123`)은 PR #1573으로 main에 착지했고, 그 두 원 브랜치(`friendly-pascal-mnmypk`·`blissful-lovelace-ubp9tw`)는 구현이 전량 흡수된 것으로 재확인했다(§3-③).
2. **16회차가 "claim 활성"이라 판정 밖에 둔 브랜치 중 4건이 완성품을 PR 없이 들고 있다.** claim이 TTL(72h)을 넘긴 지금 이 4건은 미추적 고립이다 — `MATH-06`(`brave-franklin`) · `OPS-34`(`amazing-goldberg`) · `OPS-50`(`happy-turing`) · `PED-26`(`nice-cray`). main 부재 줄은 각각 658 · 590 · 876 · 866이다. 회수 태스크 4건(`MATH-07` · `OPS-129` · `OPS-130` · `PED-45`)을 등재하고 소유 태스크 4건에 `depends_on`으로 부착했다.
3. **`nice-cray`에만 등재된 태스크 5건**(`ARCH-72` · `HARN-304` · `PED-43` · `PED-44` · `REND-05`)을 발견했다. 4건은 원 번호로 복원했고(`PED-43`은 빈 acceptance 오등재라 브랜치에서도 취소된 번호 — 복원하지 않음), 복원본의 title·acceptance·paths가 브랜치 원문과 글자 단위로 일치함을 확인했다.
4. **같은 사고가 4개 세션에서 동시에 났다** — 반복 실수다. 대책 태스크 `HARN-309`를 등재했다(§4). `backlog.py review`가 PR 증적을 묻지 않아 "PR 대기"가 합법 종료 상태가 된다.
5. **삭제 배치 이번 회차 0건.** 내용이 소멸한 3건은 claim 해제 대기(§3-③'), 3건은 Kiki 판단이 필요하다(§3-④, §6).

## 1. 전제 복구와 모집단 분리

| 구분 | 건수 | 내역 |
|---|---|---|
| 원격 ref 전수 | 51 | `git for-each-ref refs/remotes/origin` |
| 제외 — 판정 대상 아님 | 4 | `main` · `harness-claims` · `harness-reports` · `gh-readonly-queue/main/pr-1565-*`(머지 큐 임시 브랜치) |
| 제외 — 열린 PR이 소유 | 22 | 열린 PR 22건(GitHub MCP `list_pull_requests`) |
| **감사 대상** | **25** | §2 |

산술: 51 − 4 − 22 = 25.

**유령 PR 0건** — 열린 PR 22건의 head가 전부 원격에 실재한다.

**claim 대장 대조**(`harness-claims` 트리 직접 조회, 21건): `backlog.py claims reap`(dry-run, 삭제 안 함)이 **stale 14건**(`ttl` 13 · `task_missing` 1)을 지목했고 유예 구간 5건(`branch_gone_recent` — 오늘 생성돼 아직 push 전인 claim)은 제외했다. 16회차는 claim 활성 브랜치를 판정 밖에 뒀으나 그 사이 `brave-franklin`·`amazing-goldberg`·`happy-turing`·`nice-cray`의 claim이 TTL을 넘겨 감사 대상이 됐다. claim 해제(`claims reap --apply`)는 이 감사의 범위가 아니다.

방치가 긴 열린 PR(마지막 갱신 기준, 이 감사는 head 실재만 확인): `#844` `#856` `#858` `#865`(08-31) · `#1061` `#1076`(09-08) · `#1145`(09-12) · `#1294`(09-23) · `#1377`(09-29) · `#1410`(10-01, draft).

## 2. 측정과 분류

판정 기준 커밋 `d873d064` 기준, `B=origin/<브랜치>`:

```bash
git rev-list --left-right --count origin/main...$B                              # behind ahead
git diff --name-only origin/main...$B | wc -l                                   # 내용 diff
git diff --name-only origin/main...$B | grep -cE '^(src|tests|data|scripts)/'   # done-less 사각
```

부재 줄 대조(16회차 방법 승계): 브랜치가 추가한 줄(`git diff -U0`의 `+` 줄, 이벤트 샤드 제외)이 main의 같은 경로 파일에 **줄 전체 일치**로 있는지 센다. 서식·직렬화만 달라도 부재로 세는 한계가 있어, 부재가 많은 파일은 의미 단위로 다시 비교했다.

| 브랜치 | head | 최종 커밋 | behind | ahead | diff | 코드 | 분류 |
|---|---|---|---|---|---|---|---|
| `adoring-goodall-3dfsdi` | `6949dd47` | 2026-10-12 | 0 | 3 | 21 | 3 | ⓪ 활성 claim(QUAL-12) |
| `peaceful-bell-s7mlg8` | `fdfa09cc` | 2026-10-12 | 6 | 2 | 13 | 7 | ⓪ 활성 claim(MISC-61) |
| `brave-franklin-2999u5` | `70aa404d` | 2026-10-09 | 47 | 2 | 11 | 8 | ① 신규 `MATH-07` |
| `amazing-goldberg-1oc67i` | `777b860f` | 2026-10-09 | 22 | 3 | 6 | 2 | ① 신규 `OPS-129` |
| `happy-turing-kmrd5z` | `93861f63` | 2026-10-09 | 34 | 1 | 8 | 4 | ① 신규 `OPS-130` |
| `nice-cray-mbg1mq` | `dbe2e79c` | 2026-10-08 | 65 | 2 | 54 | 40 | ① 신규 `PED-45` |
| `practical-maxwell-kuwl7x` | `187bf271` | 2026-10-03 | 144 | 1 | 5 | 1 | ① 기존 `OPS-122` |
| `remaining-track-34zvse` | `7fb78470` | 2026-08-11 | 769 | 16 | 33 | 23 | ① 기존 `HARN-212` |
| `backend-audit-event-foundation-29ac1b` | `6507e018` | 2026-08-25 | 676 | 3 | 22 | 21 | ② 추적 중 |
| `openrouter-setup-guide-e98dw4` | `f8c0e3b6` | 2026-08-03 | 865 | 13 | 37 | 27 | ② 추적 중 |
| `subject-problems-theory-check-7n9n72` | `621b11f9` | 2026-08-11 | 778 | 34 | 83 | 49 | ② 추적 중 |
| `whymath-ai-recommendation-review-q8tvcx` | `e1835c0c` | 2026-08-07 | 843 | 3 | 11 | 2 | ② 추적 중 |
| `whymath-coding-architecture-iws58k` | `a8e01be2` | 2026-08-10 | 784 | 1 | 16 | 1 | ② 추적 중 |
| `whymath-curriculum-design-6eejrv` | `2f428729` | 2026-08-11 | 742 | 9 | 6 | 3 | ② 추적 중 |
| `whymath-issues-review-k20m0w` | `2330a095` | 2026-08-11 | 790 | 45 | 133 | 95 | ② 추적 중 |
| `whymath-mvp-plan-architecture-trjg5x` | `c8abbc17` | 2026-08-09 | 831 | 81 | 233 | 188 | ② 추적 중 |
| `whymath-pedagogy-review-gdmwhk` | `2915bf4e` | 2026-08-11 | 778 | 1 | 31 | 21 | ② 추적 중 |
| `whymath-pedagogy-review-uqyg79` | `5dc040b3` | 2026-08-03 | 859 | 38 | 76 | 51 | ② 추적 중 |
| `whymath-service-operations-review-5t5lmv` | `dd3e9475` | 2026-08-11 | 774 | 6 | 33 | 17 | ② 추적 중 |
| `blissful-lovelace-ubp9tw` | `d4e4b432` | 2026-10-02 | 165 | 2 | 15 | 13 | ③' 흡수됨 · claim 해제 후 삭제 |
| `status-f6qz0c` | `e90d2d6f` | 2026-09-01 | 602 | 0 | 0 | 0 | ③' 빈 브랜치 · claim 해제 후 삭제 |
| `stoic-hawking-vzumx5` | `a54f628f` | 2026-10-06 | 113 | 1 | 2 | 0 | ③' claim 기록뿐 · claim 해제 후 삭제 |
| `friendly-pascal-mnmypk` | `c229d21c` | 2026-10-03 | 160 | 2 | 7 | 4 | ④ 흡수됨 · Kiki 보존 지시와 충돌 |
| `gracious-cannon-xwn0lh` | `4a51ab09` | 2026-10-09 | 29 | 1 | 2 | 0 | ④ 취소 지시가 main과 충돌 |
| `status-f9lp65` | `d792c9d0` | 2026-09-03 | 585 | 2 | 5 | 2 | ④ `HARN-56`이 지목 |

| 분류 | 건수 |
|---|---|
| ⓪ 활성 claim(오늘) — 손대지 않음 | 2 |
| ① 회수 필요 | 6 (신규 등재 4 · 기존 태스크 2) |
| ② 추적 중 | 11 |
| ③' 삭제 가능하나 claim 해제 대기 | 3 |
| ④ Kiki 판단 필요 | 3 |

합계 2 + 6 + 11 + 3 + 3 = 25(감사 대상).

## 3. 판정 근거

### ⓪ 활성 claim 2건 — 손대지 않음

`adoring-goodall`(`QUAL-12`)과 `peaceful-bell`(`MISC-61`)은 오늘 push 중이다(claim 2026-10-12T08:11Z · 07:23Z). `peaceful-bell`은 브랜치에만 있는 태스크 `MISC-64`를 가지나 번호가 원격 reservations(`reservations/MISC-64.json`)에 걸려 있어 충돌 위험이 없다. 세션이 끝날 때 PR이 열리지 않으면 다음 회차의 ①이 된다.

### ① 회수 필요 6건

**신규 4건 — 16회차에서 claim 활성으로 제외했던 완성품.** 공통점: 구현·검증을 마치고 태스크를 `review`로 돌린 뒤 PR 없이 끝났다. 열린 PR 22건 중 이 4건을 다루는 것은 없다(제목 대조). main 대장 이벤트에도 `MATH-06`은 0건이다.

1. **`brave-franklin-2999u5`** (`70aa404d`) → **MATH-07**. `MATH-06` 교육과정 표기 범위 게이트 커버리지 확장. 커밋 메시지: 초등 밴드 관측 0 → 737회, 보조 코퍼스 5종 편입, 역삼각·편미분·프라임 정규화, 뮤테이션 13종 전건 RED. 추가 796줄 중 main 부재 658줄(`curriculum_notation_gate.py` 238/297 · 테스트 311/382).
2. **`amazing-goldberg-1oc67i`** (`777b860f`) → **OPS-129**. `OPS-34` 오프라인 리포트 면제의 수취인 선언 계약. 커밋 메시지: 백엔드 전체 18334+166 passed, infra 2961, harness 2256, constitution 39, 계층 커버리지 전 계층 PASS, mypy·lint-imports·ruff·black exit 0, 헌법 래칫 차단 0건, 뮤테이션 17종 전건 RED. 런북(128줄)과 테스트(286줄)는 main에 파일 자체가 없다.
3. **`happy-turing-kmrd5z`** (`93861f63`) → **OPS-130**. `OPS-50` MoE 파싱 실패 원인 규명 — 미분류 16건 전부 `output_tokens=512` 절단이라는 결론과 측정 도구. **부분 완료**: 라이브 재측정은 Phaiakes9가 필요해 미수행이다. 소유 태스크 `OPS-50`은 이 회수 뒤에도 닫지 않는다.
4. **`nice-cray-mbg1mq`** (`dbe2e79c`) → **PED-45**. `PED-26` 교수전략 카탈로그 정합. 04e→04g 문서번호 치환(저장소 전반 118곳), gdmwhk판 병합, 접두 중복 차단 테스트(`tests/infra/test_architecture_doc_numbers.py`), 정합 결과 문서. 추가 866줄 전부 main 부재. **이 브랜치가 `gdmwhk`·`uqyg79` 회수의 정합 결과를 들고 있으므로 §3-②의 두 브랜치 삭제는 `PED-45`가 done이 된 뒤에야 판정할 수 있다.**

**기존 태스크 2건 — 변동 없음.** `practical-maxwell-kuwl7x` → `OPS-122`(판정 문서 89줄·테스트 149줄 main 부재 재확인), `remaining-track-34zvse` → `HARN-212`(MEMORY 결정 로그 2블록 main 부재 — 부재 줄 38). 둘 다 head 불변, 태스크 `todo`.

**`nice-cray` 브랜치 전용 태스크 5건** — main에 파일도 번호도 없다(전 원격 브랜치 전수 확인: 사용처가 이 브랜치와 `REND-05`의 `gdmwhk` 원본뿐). `ARCH-72` · `HARN-304` · `PED-44` · `REND-05`는 원 번호로 CLI 재등재했고 `PED-45`를 선행으로 부착했다(`HARN-304` 제외 — CLI 입구 검증 축이라 독립). `PED-43`은 셸 인자 오류로 acceptance 5항이 빈 문자열로 저장된 오등재라 브랜치에서도 `cancelled`이며 복원하지 않는다(번호 1개 소비).

**등재 검증.** `backlog.py validate` exit 0(태스크 1116건), `backlog.py audit-deps` exit 0(위반 0건). `next --n 600 --all-eos --json` 전건 조회로 회수 태스크 4건이 후보에 오르고 소유 태스크 3건(`MATH-06`·`OPS-34`·`OPS-50`)과 `PED-26`, 복원 태스크 3건(`ARCH-72`·`PED-44`·`REND-05`)이 후보에서 빠짐을 확인했다. **한계**: 소유 태스크 4건은 부착 전에도 원격 claim 때문에 후보가 아니었으므로, 이 부착은 claim이 해제된 뒤에야 효과를 낸다(16회차와 같은 한계).

### ② 추적 중 11건 — 좌석 상실 0

head 불변 11/11(16회차 기록과 대조). 좌석 태스크 17종을 main 기준으로 다시 조회했고 전부 `todo`다.

| 브랜치 | 살아 있는 좌석 |
|---|---|
| `7n9n72` | MISC-01/03/05/06 · PB-02 · PED-14 · S3-33/34 · HARN-79 · HARN-213 — **삭제 절대 금지** |
| `trjg5x` | ADMIN-02 · PATH-03 · S4-20 |
| `k20m0w` | SEC-30 · MGMT-03 · HARN-25 · ARCH-102 · S4-22 |
| `gdmwhk` / `uqyg79` | PED-26 → 이제 `PED-45`(§3-①-4)가 선행 |
| `5t5lmv` | OPS-112 · OPS-113 · A11Y-02 |
| `iws58k` | ARCH-30 |
| `6eejrv` | PB-08 |
| `e98dw4` | VIZ-11 |
| `q8tvcx` | OPS-38 · OPS-67 |
| `29ac1b` | ADMIN-10 ⑦ |

### ③' 삭제 가능하나 claim 해제 대기 3건 (배치 제외)

1. **`blissful-lovelace-ubp9tw`** (`d4e4b432`) — `OPS-123` done(PR #1573). 코드 12파일의 추가 줄이 main에 전부 있고(부재 0), 잔여 22줄은 ⓐ태스크 YAML의 `status`·`session`·`updated`(WIP 상태 필드) 3줄 ⓑ테스트 19줄이다. 테스트는 루프 지연 측정 헬퍼 `_light_request_lateness_during_slow_step`인데 main에 같은 함수가 있고 신호 동기화(`entered`·`signal`)까지 더 강화된 형태다. #1573 판정 문서가 "머지 전까지 삭제 금지"라 적은 조건은 충족됐다. 원격 claim `OPS-96`(2026-10-02)은 TTL 초과 · 소유 태스크 `OPS-96`은 `todo`.
2. **`status-f6qz0c`** (`e90d2d6f`) — ahead 0 · diff 0. 잃을 내용이 없다. claim `EOS-63`(`kind=block`)은 TTL 초과(41일).
3. **`stoic-hawking-vzumx5`** (`a54f628f`) — `QUAL-10` 착수 claim 기록 커밋 1건(YAML 3줄 + 샤드)뿐. claim은 TTL 초과.

세 건 모두 `claims reap` dry-run이 stale로 지목했다. 16회차가 `f6qz0c`·`stoic-hawking`을 같은 사유로 보류했고 이번에 새 증거가 없으므로 선례를 따랐다. `claims reap --apply`로 claim이 풀리면 다음 배치에 오른다.

### ④ Kiki 판단 필요 3건

1. **`friendly-pascal-mnmypk`** (`c229d21c`) — **내용은 전량 흡수됐다.** 코드 3파일은 부재 0, 코퍼스 600행은 줄 단위로는 전건 부재로 나오지만 의미 비교(키 순서 무시)에서 **차이가 `authored_by` 필드 하나뿐**이다(main의 PB-17 #1549가 600/600에 추가). 잔여는 브랜치의 `QUAL-11` 태스크 YAML에 쓴 "처분 결과" 1,485자인데, #1573 판정 문서가 같은 판정(① 사실 기록 · ②③ 이행 · ④ 판정 완료)을 main 기준으로 다시 적었다. **다만 충돌이 있다**: `gracious-cannon-xwn0lh`의 커밋(2026-10-09 07:42Z)이 "Kiki 지시로 `QUAL-15` 취소 — 회수 착수 전이며 원 브랜치는 삭제하지 않고 보존한다"를 기록했는데, #1573은 그 4시간 뒤(11:47Z) `QUAL-15`를 done으로 착지시켰다. 취소는 main에 도달한 적이 없다. 보존 지시가 아직 유효한지 이 감사가 판정할 수 없어 삭제 배치에서 뺐다.
2. **`gracious-cannon-xwn0lh`** (`4a51ab09`) — 위 취소 1건뿐(태스크 YAML 7줄 + 샤드 2줄). 취소를 적용하면 main에서 done인 태스크를 `cancelled`로 되돌리는 퇴행이다. 내용상 폐기 대상이지만 Kiki 지시의 유일한 기록이라 판단을 넘긴다.
3. **`status-f9lp65`** (`d792c9d0`) — 백업 스케줄 등록 스크립트의 `-ErrorAction Stop` 수정이 main에 더 완성된 형태로 있어 내용은 소멸했다. 단 main의 `HARN-56`(`in_progress`)이 `session` 필드로 이 브랜치를 지목하고 `requires_gates` 2건이 열려 있다. 소유 세션의 의도를 확인하지 못했다.

## 4. 구조적 원인과 대책 — `HARN-309`

①-1~4는 **서로 다른 세션 4개가 사흘 안에 같은 방식으로 끝났다.** 각 브랜치의 마지막 커밋 메시지가 원인을 직접 적는다 — "태스크 in_progress → review (PR 미개설)" · "review 전환 (PR 대기 — CLAUDE.md '먼저 지시 대기')" · "상태 review(done은 PR 증적 필요 — PR 미개설)".

- **원인(실측)**: 클라우드 세션의 기본 지시("PR은 사용자가 요청할 때만")와 CLAUDE.md "완료·병합"("산출물이 있으면 요청 없이 PR을 연다")이 충돌할 때 세션이 전자를 택했다. 그리고 `scripts/harness/backlog.py`의 `cmd_review`는 PR 참조도 `--no-pr` 사유도 검사하지 않고, `check-stop`은 `in_progress` 소유 태스크만 막는다. 즉 `review`는 PR 없이도 대장상 정상 종료 상태다.
- **기존 대책이 못 본 이유**: `HARN-23`은 `done` 시점의 PR 증적만 막는다. `HARN-47`/야간 고립 리포트는 탐지인데 `review`가 원격 claim을 유지하므로(`cmd_review` docstring: "review는 여전히 in-flight — `_release_remote_claim`을 부르지 않는다") claim TTL(72h)이 지나야 브랜치를 올린다 — 최대 3일 늦다. 실제로 오늘 세션 브리핑의 고립 목록(야간 스냅샷)에는 `nice-cray`만 있고 `brave-franklin`·`amazing-goldberg`·`happy-turing`은 아직 없다(스냅샷 시점에 claim TTL 이내). 둘 다 `review` 전환 시점의 방치를 입구에서 막지 못한다.
- **대책**: `HARN-309` 등재 — `review` 전이에 PR 증적(또는 `--no-pr` 예외 4종)을 요구하고, `check-stop`이 review·PR 미개설을 차단한다. 통과 대조군과 뮤테이션을 acceptance에 명시했다. 2026-09-20 새 산문 규칙 등재 동결에 따라 CLAUDE.md는 수정하지 않았다.

## 5. 정직한 공백

- **부재 줄 대조의 한계**: 줄 전체 일치라 서식만 달라도 부재로 센다. `friendly-pascal` 코퍼스는 의미 비교로 보완했고 `blissful-lovelace` 테스트는 main의 대응 함수 존재로 보완했다. ①-1~4의 부재 줄 수는 "이식할 양의 상한"이지 정확한 필요량이 아니다(main이 그 뒤 파일을 진화시켰을 수 있다 — 회수 태스크가 파일 단위 재적용을 지정했다).
- ①-1~4의 브랜치 커밋 메시지가 말하는 검증 수치(전체 스위트 통과 건수·뮤테이션 건수)는 **이 감사가 재현하지 않았다.** 인용일 뿐이다.
- ②의 11건은 head 불변과 좌석 `status`만 재확인했다. 좌석 acceptance 본문 재정독과 `34zvse`·`kuwl7x`의 코드·테스트 재대조는 하지 않았다(16회차 결과 승계).
- 열린 PR 22건은 head 실재와 제목만 확인했다.
- **번호 예약 누락 — 원인 규명·해소 (2026-10-13 사후 정정).** 최초 서술은 "번호가 main 최대치보다 낮을 때 `add`가 예약을 생략하는 것으로 추정"이었으나 **틀렸다.** 이벤트 샤드(`backlog/events/claude_intelligent-gauss-99somv.ndjson`)에 `number_reserve_unavailable`(`status=error`, 원격 `git push` 실패)이 `ARCH-72`·`HARN-304`·`PED-44` 3건 기록돼 있었고 `REND-05`만 push가 성공했다 — `add`는 예약 실패를 경고로 넘기고 계속 진행하도록 설계돼 있다(`number_guard.reserve_for`). 경합 후 재시도 없이 `error`로 끝난 원인(일시적 push 실패)은 **재현하지 못했다.** 사실 하나 더: `nice-cray`가 2026-10-08에 이 4개 번호를 예약했으나(`harness-claims` 이력 `d4d007f6`·`eeb5df72`·`743ece08`·`2c809f63`) 72시간 TTL이 지나 지연 청소로 사라진 상태였다. 같은 날 `number_guard.reserve_for`로 3건을 재예약해 원격에 `reservations/{ARCH-72,HARN-304,PED-44,REND-05}.json` 4건이 실재함을 확인했다. **한계**: 예약 TTL이 72시간이라 회수 태스크 4건(`MATH-07`·`OPS-129`·`OPS-130`·`PED-45`, 2026-10-12 예약)과 이 4건은 2026-10-15~16경 다시 만료된다 — 그 전에 이 PR이 main에 착지해야 번호가 대장에 영구 귀속된다.
- `claims reap --apply`는 실행하지 않았다.
- 이번 감사는 소스·테스트를 건드리지 않아 전체 백엔드 스위트를 돌리지 않았다. 회수 태스크의 이식은 이 감사의 범위가 아니다 — `/drive`가 실행한다.

## 6. Kiki 판단 요청

1. `claims reap --apply`로 stale claim 14건을 풀어도 되는가 — 풀면 §3-③'의 3건이 다음 배치에 오른다. (회수 태스크 4건이 소유 태스크를 막고 있으므로 해제해도 중복 구현 경로는 열리지 않는다.)
2. `friendly-pascal-mnmypk`의 보존 지시(2026-10-09)가 `QUAL-15` done 이후에도 유효한가. 유효하면 보존하고, 아니면 `gracious-cannon-xwn0lh`와 함께 다음 배치에 올린다.
3. `status-f9lp65`를 `HARN-56` 소유자가 아직 쓰는가.
