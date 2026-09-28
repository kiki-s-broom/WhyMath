# 미머지 브랜치 전수 감사 13회차 — 2026-09-28

> **판정 기준: main `919865d4`** (2026-09-28T09:31:16Z · "OPS-69: harness-integrity 잡 시간 제한
> 5→12분 …" `#1347`). 이 세션은 시작 시 shallow였고 `git fetch --unshallow origin` +
> `git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'`로 전제를 복구한 뒤에만
> 판정했다(복구 후 1,319커밋). 이 문서는 그 시점의 스냅샷이며, 선행 판정 문서(12회차
> `_2026-09-18.md`)는 수정하지 않는다.

## 0. 계기

Kiki의 "미머지 작업" 요청 → `/stray-code`. 12회차(2026-09-18) 이후 10일간의 변화를 판정한다.
이번 회차의 실질은 세 가지다.

1. **신규 삭제 후보 5건** — 새로 나타난 브랜치 3건과 claim이 풀린 1건, 회수 태스크가 끝난 1건.
   전부 main에 **더 새로운 판**으로 들어가 있어 잃을 내용이 없다.
2. **감사 중 발견한 실시간 중복 1건** — 열린 PR #1346이 이미 만든 EOS-129 ⑤ 게이트를, 감사
   도중 새로 나타난 세션이 main만 보고 **같은 측정의 두 번째 게이트**로 다시 만들었다(§5).
3. **두 회차 연속 원인 미상이던 claim 대장 이상의 원인 확정** — 개명이 claim을 옮기지 않았고,
   자동 청소는 판정 순서 때문에 그것을 못 본다(§6-①).

## 1. 전제 복구와 모집단 분리

```bash
git rev-parse --is-shallow-repository          # true였다 → 아래 두 줄 실행 후 false
git fetch --unshallow origin
git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'
git for-each-ref --format='%(refname:short)' refs/remotes/origin | grep -v '^origin$' | wc -l
git ls-remote --heads origin | wc -l            # 로컬 ref 목록과 diff 0 확인
```

| 구분 | 건수 | 내역 |
|---|---|---|
| 원격 ref 전수 | 39 | `ls-remote --heads`와 로컬 remote-tracking 목록이 diff 0 |
| 제외 — 판정 대상 아님 | 2 | `main` · `harness-claims`(하네스 소유) |
| 제외 — 열린 PR이 소유 | 15 | #1351 #1350 #1349 #1348 #1346 #1344 #1338 #1294 #1145 #1076 #1061 #865 #858 #856 #844 |
| 제외 — 원격 claim 활성(타 세션) | 2 | `status-f6qz0c`(EOS-63 block 홀드 · ahead 0 · diff 0) · `status-f9lp65`(HARN-56 block 홀드 · ahead 2 · diff 5) |
| **감사 대상** | **20** | 아래 §3 |

**유령 PR 0건** — 열린 PR 15건의 head 브랜치가 전부 원격에 실재하고, PR이 보고한 head SHA와
원격 브랜치 head가 15건 모두 일치한다(역방향 확인).

**12회차 대비 모집단 변화**: 42 → 39. 11차 배치 4건과 패턴 밖 수동 삭제 2건이 사라졌고(§4-1),
12회차의 claim 활성 `test-driven-development-03elxp`는 claim이 풀려 감사 대상으로 내려왔다.
신규 등장 3건(`adoring-mccarthy-sle0uj` · `new-session-fy0wry` · `new-session-jchdr8`)은 §3-③.

## 2. 3축 측정

```bash
B=origin/<브랜치>
git rev-list --left-right --count origin/main...$B                                   # behind ahead
git diff --name-only origin/main...$B | wc -l                                        # 내용 diff
git diff --name-only origin/main...$B | grep -cE '^(src|tests|data|scripts)/'        # done-less 사각
```

| 브랜치 | head | behind | ahead | diff | src/tests/data/scripts | 최종 커밋 |
|---|---|---|---|---|---|---|
| `adoring-mccarthy-sle0uj` | `a737df74` | 192 | 2 | 7 | 1 | 09-23 |
| `backend-audit-event-foundation-29ac1b` | `6507e018` | 451 | 3 | 22 | 21 | 08-25 |
| `new-session-fy0wry` | `3d534dcc` | 109 | **0** | **0** | 0 | 09-20 |
| `new-session-jchdr8` | `f34b7478` | 132 | 1 | 3 | 0 | 09-19 |
| `openrouter-setup-guide-e98dw4` | `f8c0e3b6` | 640 | 13 | 37 | 27 | 08-03 |
| `relaxed-fermat-8dui3u` | `03e45689` | 269 | 1 | 3 | 0 | 09-11 |
| `remaining-track-34zvse` | `7fb78470` | 544 | 16 | 33 | 23 | 08-11 |
| `subject-problems-theory-check-7n9n72` | `621b11f9` | 553 | 34 | 83 | 49 | 08-11 |
| `test-driven-development-03elxp` | `49d9d76a` | 303 | **0** | **0** | 0 | 09-07 |
| `whymath-ai-content-design-vafylb` | `b1218739` | 576 | 8 | 7 | 1 | 08-10 |
| `whymath-ai-recommendation-review-q8tvcx` | `e1835c0c` | 618 | 3 | 11 | 2 | 08-07 |
| `whymath-coding-architecture-iws58k` | `a8e01be2` | 559 | 1 | 16 | 1 | 08-10 |
| `whymath-constitution-rules-check-azdnov` | `c335a787` | 553 | 1 | 5 | 0 | 08-11 |
| `whymath-curriculum-design-6eejrv` | `2f428729` | 517 | 9 | 6 | 3 | 08-11 |
| `whymath-data-platform-design-t608mk` | `d876b523` | 549 | 1 | 7 | 0 | 08-11 |
| `whymath-issues-review-k20m0w` | `2330a095` | 565 | 45 | 133 | 95 | 08-11 |
| `whymath-mvp-plan-architecture-trjg5x` | `c8abbc17` | 606 | 81 | 233 | 188 | 08-09 |
| `whymath-pedagogy-review-gdmwhk` | `2915bf4e` | 553 | 1 | 31 | 21 | 08-11 |
| `whymath-pedagogy-review-uqyg79` | `5dc040b3` | 634 | 38 | 76 | 51 | 08-03 |
| `whymath-service-operations-review-5t5lmv` | `dd3e9475` | 549 | 6 | 33 | 17 | 08-11 |

고립 done 대조(브랜치 done vs main 비-done)는 신규 4건과 `relaxed-fermat` 모두 **0건**이다.
기존 추적 15건의 고립 done 목록(7n9n72 10 · k20m0w 13 · trjg5x 34 · uqyg79 9 등)은 12회차와
같고, 이 브랜치들은 8월 이후 커밋이 없다.

## 3. 4분류 판정

| 분류 | 건수 | 내역 |
|---|---|---|
| ① **회수 필요(미추적 고립)** | **0** | — |
| ② 추적 중 | **15** | 12회차 15건 전건 승계(좌석 상실 0) |
| ③ 삭제 가능 | **5** | `claude/*` 5건 → 12차 삭제 배치 |
| ④ 제외 | 19 | PR 소유 15 · claim 활성 2 · 판정 대상 아님 2 |

합계 0+15+5 = 20(감사 대상) · 19(제외) = 39.

### ① 회수 필요 — 0건

신규 4건과 `relaxed-fermat` 모두 main이 더 새로운 판을 갖고 있다(§3-③). 12회차가 등재한
회수 태스크 `MP-06`은 PR #1249로 **done**이 됐다.

### ② 추적 중 15건 — 좌석 상실 0

각 브랜치 접미사를 참조하는 main 태스크의 status를 전수 조회했고, 주요 좌석은 본문을 열어
"단순 언급"이 아니라 **회수 좌석**(고립 참조·head SHA·"삭제 금지"·"재구현 금지" 명기)인지
확인했다.

| 브랜치 | 살아 있는 좌석(todo/review) | 12회차 대비 |
|---|---|---|
| `7n9n72` | MISC-01/03/05/06 · PB-02 · PB-14 · PED-14 · S3-33/34 · OPS-41 · HARN-79 — **삭제 절대 금지** | 동일 |
| `trjg5x` | ADMIN-02(b3a58b02 병합 금지 명기) · PATH-03("재구현 금지" — done 구현 보존) · PB-14 | PB-13 → done |
| `k20m0w` | MOB-18 · MOB-11 · MOB-23 · SEC-19 · SEC-30 · MGMT-03 · HARN-25 · PB-14 | MOB-18 in_progress → todo |
| `gdmwhk` / `uqyg79` | PED-26 (+ gdmwhk HARN-31) | 동일 |
| `34zvse` | CUR-07 · HARN-80 | 동일 |
| `5t5lmv` | OPS-40 | 동일 |
| `iws58k` | ARCH-30 | 동일 |
| `t608mk` / `azdnov` | OPS-41 | 동일 |
| `6eejrv` | PB-08 | 동일 |
| `e98dw4` | VIZ-11 | 동일 |
| `q8tvcx` | OPS-38 · OPS-67 · OPS-41 | 동일 |
| `vafylb` | **OPS-53**(실제 회수 좌석 — cp949 출력 축). OPS-41·PB-14·KG-02·NLP-05는 참조만(§5-1) | S4-16 → cancelled · 브리핑 "이미 포팅됨"은 오분류(§5-1) |
| `29ac1b` | ADMIN-10 ⑦ 고립참조 — `docs/architecture/90_audit_log.md`(246줄) **main 부재 지속** | 동일 |

### ③ 삭제 가능 5건 — 근거

각 건을 태스크 status 대조가 아니라 **파일 단위 내용 대조**로 판정했다: main 부재 파일 유무 +
브랜치 고유 줄(`comm -23` 정렬 집합 차)의 내용 확인.

```bash
B=origin/<브랜치>
git merge-base --is-ancestor $B origin/main && echo ANCESTOR
for f in $(git diff --name-only origin/main...$B); do
  git cat-file -e origin/main:"$f" 2>/dev/null \
    && echo "$f $(comm -23 <(git show $B:"$f"|sort -u) <(git show origin/main:"$f"|sort -u)|wc -l)" \
    || echo "$f ★main부재"; done
```

| 브랜치 | head | main 조상 | diff | main 부재 | 고유 줄 |
|---|---|---|---|---|---|
| `adoring-mccarthy-sle0uj` | `a737df74` | 아니오 | 7 | 0 | 55 |
| `new-session-fy0wry` | `3d534dcc` | **예** | 0 | 0 | 0 |
| `new-session-jchdr8` | `f34b7478` | 아니오 | 3 | 0 | 49 |
| `test-driven-development-03elxp` | `49d9d76a` | **예** | 0 | 0 | 0 |
| `relaxed-fermat-8dui3u` | `03e45689` | 아니오 | 3 | 1 | 7 |

**(a) `claude/adoring-mccarthy-sle0uj` = `a737df74`** — 커밋 2개.

- `0367fce4`(2026-09-14 · "strict 해제 결정을 저장소에 집행")는 PR #1161로 main에 들어갔고
  (`HARN-101` yaml 고유 줄 0), 이후 main이 더 나아갔다. 고유 줄 46개(`branch-protection-setup.md`
  25 · `test_ruleset_drift.py` 21)는 전부 **main이 대체한 옛 판**이다 — 조회 명령이
  `| Out-File -Encoding utf8`인 판(main은 2026-09-14 실측 41자 유실 뒤 `cmd /c`로 교체 ·
  CLAUDE.md 인코딩 규칙 4회차 사고) · 클래식 보호 삭제 절의 "⏳ Kiki 실행 대기"(main은
  "✅ 완료 (2026-09-14)"). 테스트 파일은 main 1,107줄 대 브랜치 762줄이다.
- `a737df74`(2026-09-23 · 작성자 kiki · "Kiki 머신 로컬 잔여분 보존 커밋 (체크아웃 이동 전)")는
  **Kiki가 체크아웃을 옮기기 전에 로컬 잔여분을 보존하려고 올린 커밋**이다. 4파일 중
  `mp02_first_llm_authoring_run_runbook.md`·`l3_equivalent_gen.md`는 `relaxed-fermat` 정정분의
  사본이고, `MP-06`(PR #1249)이 그것을 회수한 뒤 main이 더 고쳤다(예: `$RunId` 읽기를 순수
  파이썬으로 교체, 코드 줄 참조 `anchor_round_ledger.py:530` → `harness/anchor_round_ledger.py:717`).
  `.github/ruleset-check-state.json`은 브랜치 `2026-09-14` 대 main `2026-09-25`로 main이 새롭다.
  이벤트 1줄은 §4에 원문 보존했다.

이 브랜치는 12회차 모집단에 없었다. 그 PR들(#1154·#1161·#1162·#1164)이 09-15까지 전부 닫혔고
12회차의 감사 대상·PR 소유·claim 어디에도 없으므로, 머지 후 사라졌다가 09-23 보존 커밋 push로
다시 생긴 것으로 **읽힌다**(브랜치 생성 이력 자체는 확인하지 않았다).

**(b) `claude/new-session-fy0wry` = `3d534dcc`** — main의 조상이다(고유 커밋 0). PR #1233·#1237로
머지됐고, `HARN-134` notes가 "브랜치 tip 3d534dcc가 origin/main 조상"이라고 이미 적었다. main의
언급 4건(EOS-128·EOS-23·HARN-111·HARN-134)은 모두 사고 경위 서술이라 좌석이 아니다.

**(c) `claude/new-session-jchdr8` = `f34b7478`** — PR #1215 머지(09-19 05:43Z) **3분 뒤에** 올린
후속 커밋 1개("EOS-117 done(머지 착지) + EOS-119 등재·착수")가 머지되지 않고 남았다. main이 이미
이관했다 — `EOS-117` 증적에 "done 기입이 고립 브랜치 claude/new-session-jchdr8 f34b7478에만 있어
main으로 이관(2026-09-24)"이 있고, `EOS-119`는 main **done**(PR #1300 · 브랜치는 in_progress).
고유 줄 49개 = 이벤트 41(EOS-117 done 1 · EOS-119 add/start 2 · policy_warn 38 — 같은 사실을
main에서 `admiring-wright-obipz1`이 09-24에 다시 기록) + EOS-117 yaml 2 + EOS-119 yaml 6(옛 상태).
EOS-117 증적의 상세 문구 1줄은 main 판보다 자세해 §4에 원문 보존했다.

**(d) `claude/test-driven-development-03elxp` = `49d9d76a`** — main의 조상이다(고유 커밋 0).
PR 9건(#981~#1036)이 전부 머지됐다. 12회차까지 `MP-02` block 홀드로 claim 활성이었으나,
2026-09-23 Kiki 승인으로 `claims release --force` 해제됐다(`MP-02` notes · 그 뒤 MP-02 done).
3회차 연속 "claim 해제 시 즉시 삭제 후보"로 적혀 온 브랜치다.
⚠ **부수 발견**: main의 `.github/branch-protection-setup.md` §트러블슈팅 「판정기 파일이 없다」
(651~667행)가 이 브랜치를 **체크아웃 대상으로 지명**한다. 판정기는 #981(2026-09-05)로 main에
들어왔으므로 그 절의 전제("아직 main에 병합되지 않은 상태")는 3주 전에 끝났고, 지금 그 안내를
따르면 09-07 트리의 **옛 판정기**(625줄 · `bypass_actors`·`merge_queue` 0회 — main은 855줄 ·
18회·2회)로 판정하게 된다. 삭제는 이 위험을 늘리지 않는다(fetch 단계에서 실패가 보이게 된다).
문서 정정에는 가드 테스트 단언 변경이 따르므로 → **`HARN-188` 등재**(처음 185로 받았으나 번호 충돌로 개명 — §6).

**(e) `claude/relaxed-fermat-8dui3u` = `03e45689`** — 12회차의 유일한 회수 대상. `MP-06`이
PR #1249로 파일 단위 이식 2건 + 문서-코드 표류 가드(`tests/infra/test_mp02_runbook_sidecar_paths.py`)를
착지시켜 **done**이다. main 부재 1건은 policy_warn 5줄뿐인 세션 이벤트 파일이고(`MP-06` acceptance
②가 "이식 대상이 아니다"라고 명시), 고유 줄 7개는 (a)와 같은 옛 판이다. 좌석 notes의 "회수 완료
전 원 브랜치 삭제 금지"는 회수 완료로 해소됐다.

## 4. 원문 보존 — 삭제될 브랜치에만 있는 두 줄

두 줄 모두 의미상 main에 이미 있으나 문구가 더 자세하다. 삭제 후에도 찾을 수 있게 여기 옮긴다.

1. `adoring-mccarthy-sle0uj`의 `backlog/events/claude_adoring-mccarthy-sle0uj.ndjson` 마지막 줄 —
   Kiki 머신에서 실행된 강제 해제 기록이다. 해제 자체는 `harness-claims` 커밋
   `56828b0a`("release EOS-128-phase3-plan-backlog-conversion", 2026-09-22T02:51:36Z)가
   정본으로 갖고 있고, 30초 뒤(`5f41efc4` · 02:52:06Z) `compassionate-hypatia-chznsu`가 EOS-128을
   claim했다(HARN-134가 기록한 홀드 해제 사고의 해소 지점). 이벤트 쪽에만 있는 정보는
   `forced: true` 표지다.

   > {"ts": "2026-09-22T11:51:39+09:00", "actor": "claude/adoring-mccarthy-sle0uj", "action": "claim_release", "id": "EOS-128-phase3-plan-backlog-conversion", "forced": true}

2. `new-session-jchdr8`의 `EOS-117` 증적 원문(main 판은 run ID 2개만 남겼다):

   > https://github.com/kiki-s-broom/WhyMath/pull/1215 — 머지 착지 main 82d43d52 · 실 CI 위반 주입 run 35421591228: backend 잡 스텝 #8 Import contracts failure(앞 스텝 Ruff/Black/Mypy 전건 success이므로 skipped 아님) · infra-contracts 잡 스텝 #9 Pytest failure(4 failed 1537 passed) · 원복 후 최종 run 35421783017 9 success 0 비-green

### 4-1. 직전 배치 집행 확인

9·10·11차 배치와 패턴 밖 수동 삭제분 8건을 `ls-remote`로 대조했다 — **잔존 0/8**
(`backend-misc-12-16-…` · `ops-02-offsite-backup-move` · `clever-bell-8lh19k` ·
`laughing-faraday-opgsjg` · `ops-50-51-52-moe-rocm-followup` · `misc-24-…` ·
`backend-eos-204-education-event-phase1` · `s1-17-phase-b-math-extension`).

## 5. 감사 중 발견 — 열린 PR의 부분 이행을 다른 세션이 중복 신설 (EOS-129 ⑤)

모집단을 확정한 뒤 재fetch하자 새 브랜치 `claude/focused-ramanujan-2p5q8w`(head `46fe6ffb`,
11:25~11:29Z 커밋)가 나타났다. 스냅샷 이후 등장분이라 4분류에는 넣지 않았지만, 내용이
**열린 PR #1346과 같은 측정**이었다.

| | PR #1346 (`magical-maxwell-hja5kh-eos129` · `c5983e59`) | `focused-ramanujan-2p5q8w` (`46fe6ffb`) |
|---|---|---|
| 시각 | 07:31~08:43Z | 11:25~11:29Z |
| 게이트 | `G-eos129-item-response-census` | `G-eos129-prod-response-distribution` |
| 측정 | 운영 DB(whymath-pg) 문항당 응답 축적 — 읽기 전용 · Kiki 머신 | 운영 DB 문항당 응답 수 분포 — 읽기 전용 · Kiki 머신 |
| 런북 | `docs/ops/eos129_item_response_census_runbook.md` 206줄 (전제가 거짓이면 실행 거부) | `docs/ops/eos129_prod_response_distribution_runbook.md` 52줄 |
| 도구 | `l2/item_response_census.py` 216줄 + 테스트 257줄 | 없음(SELECT 직접) |
| EOS-129 처리 | 부분 이행 → "게이트 대기로 claim 해제(todo)" | 착수(11:25:20Z) → 게이트 신설·acceptance amend(11:28:30~33Z) → `unblock`으로 원격 claim 해제(11:28:44Z) |

**기전**: PR #1346은 부분 이행 후 claim을 **정상적으로** 풀고 todo로 돌렸다(게이트 대기로 세션을
끝낼 때 claim을 붙들면 HARN-134류 홀드가 생긴다). 그러면 main에도 claim 대장에도 흔적이 없다.
`backlog.py start`의 프리플라이트 0(HARN-11)은 미머지 브랜치의 **done**만 보므로 막지 못했고,
SessionStart 브리핑은 EOS-129를 **다음 착수 후보 1위**로 내놓았다 — 이 감사 세션의 브리핑도
그랬다. 두 세션은 같은 화면을 봤고, 그 화면에 PR #1346의 부분 이행은 없었다.

**조치 — 이 감사는 소유하지 않는다(중복 등재 철회)**: 처음에는 사고 대장 1건 + 대책 태스크
`HARN-187`을 이 브랜치에 등재했다. 그런데 푸시 전에 원격을 다시 보니 PR #1346의 세션이 같은 사건을
**더 넓게**(EOS-129가 하루에 **세 세션**에서 착수 — 세 번째는 12:11Z `gallant-euler-blngpj`) 이미
기록하고 대책 태스크를 올려 두었다 — **PR #1356** · `HARN-193-unmerged-gate-attach-claim-release-gap`(PR 당시 번호
`HARN-186` — 머지 `3dbe54d3` 때 개명)
· 같은 사고 대장 1건(12:39Z). 같은 사고를 두 번 세면 계열 회차가 부풀므로 이 브랜치의 사고 1줄은
뺐고(푸시 전 제 추가분), `HARN-187`은 `backlog.py cancel`로 취소하며 사유에 #1356을 적었다.
두 게이트 중 어느 쪽을 남길지도 이 감사의 범위가 아니다 — PR #1346 쪽이 도구·실행 거부 가드까지
갖춘 상위 집합으로 **읽히지만**(실행 대조는 하지 않았다) 처분은 두 세션·Kiki가 판단한다.
**Kiki는 두 런북을 모두 실행할 필요가 없다.**

### 5-1. 재개 브리핑의 "이미 포팅됨" 오분류 — `vafylb` (HARN-190)

세션 재개 브리핑이 `whymath-ai-content-design-vafylb`를 "(참고) 이미 포팅됨 — 원본 정리만 필요,
결정 불요"로 표시했다. 이 감사는 그 브랜치를 추적 중(②)으로 두고 있었으므로 스킬 §4대로 근거 커밋을
열었다.

- 근거로 노출된 `9905fdc4`(2026-08-03 · #683)는 **그 브랜치 자신의 이력 안의 앞선 머지분**이다
  (`merge-base --is-ancestor` 참).
- 브랜치는 그 뒤 `f4c6f69c`(2026-08-09 · 강등전 리포트 출력의 cp949 크래시 해소)로 같은 파일
  `harness/residue_gate_demotion_battle.py`를 다시 고쳤고, 그 변경은 main에 **없다** — main판은
  출력·도움말 줄 16곳에 U+2014가 남아 있고 stdout 재구성도 없다(브랜치판 0곳).
- 분류기 `_find_ported_evidence()`는 근거 커밋이 건드린 **파일 경로**와 브랜치 코드 파일의
  교집합만 센다 → 1/1 전건 착지. 메모리 안에서 재현했다(landed 1 / total 1 · `is_full_port=True`).

즉 이 브랜치는 **삭제하면 안 된다** — 그 축의 실제 좌석은 `OPS-53`(todo · cp949 출력 안전성)이고
그 notes가 `vafylb`를 원 출처로 지목한다. 나머지 참조(KG-02·NLP-05 = 취소된 S4-16의 세션 브랜치
언급, OPS-41·PB-14 = "동형 사례" 언급)는 회수 좌석이 아니다. 이 오분류 계열은 40xspg(08-11)·
7n9n72(08-30 → HARN-37) 이후 **3회차**라 대책 태스크 **`HARN-190`**(근거 이후 같은 파일을 다시 고친
브랜치 커밋이 있으면 착지로 세지 않는다)과 사고 대장 1건을 등재했다.

## 6. 조치

1. **삭제 12차 배치** — `.github/branch-cleanup-request.txt`에 `claude/*` 5건(§3-③). 헤드 SHA
   스냅샷을 주석에 박았다.
2. **대책 태스크 3건 등재**(전건 `backlog.py add` 경유 · 쓴 뒤 식별자 대조) + **중복 1건 취소**:
   - `HARN-188` — 「판정기 파일이 없다」 절의 전제 소멸 정정 + 가드 단언 갱신(§3-(d)).
   - `HARN-189` — `claims reap` 판정 순서: 태스크 부재가 홀더 브랜치 소멸을 가려 고아 claim이
     자동 청소를 빠져나간다(아래 ①).
   - `HARN-190` — 브리핑 "이미 포팅됨" 오분류: 근거 커밋 이후의 같은 파일 변경을 보지 않는다(§5-1).
   - `HARN-187` **취소** — PR #1356의 `HARN-193-unmerged-gate-attach-claim-release-gap`(구 `HARN-186`)과 중복(§5).
   **번호 경합(HARN-111 실례)**: 처음 받은 번호는 185·186·187이었다. 푸시 전 원격 전 브랜치를 다시
   보니 그사이 다른 세션들이 185를 2건(`magical-maxwell-hja5kh-eos134` · `vibrant-rubin-tp7jfw`),
   186을 2건(`ecstatic-feynman-bxxxvd` · `magical-maxwell-hja5kh-gate-release-gap`) 각자 등재해 두었다
   — `add`가 "push 전까지 다른 세션에 보이지 않는다"고 고지한 바로 그 창이다. 원격 전 브랜치·claim
   대장에서 188~199가 비어 있음을 실측한 뒤 `backlog.py rename`으로 185→188 · 186→189를 옮겼다
   (과거 이벤트의 옛 ID 참조는 CLI가 의도적으로 그대로 두고 `rename` 이벤트로 잇는다).
   *추가(main `559be84e` 병합 시 실측)*: 같은 번호를 쓴 다른 태스크 `HARN-186-job-log-truncation-warning-hook`이
   PR #1349로 먼저 main에 들어왔고, PR #1356은 머지(`3dbe54d3`) 때 자기 태스크를 `HARN-193-unmerged-gate-attach-claim-release-gap`으로
   개명했다. 그래서 지금 main에서 `HARN-186`은 **다른 태스크**를 가리킨다 — 이 문서의 §5·§6 참조와 취소한 `HARN-187`의
   취소 사유(`amend --notes-replace` · 원문은 이벤트에 보존)를 `HARN-193`으로 고쳤다. 개명이 옛 번호 참조를 따라가지 않는
   축(사고 줄 `fix_ref`)은 main의 `HARN-195-incident-fix-ref-rename-misroute`가 소유한다.
3. **사고 대장 4건**(이 브랜치 순증) — `orphan-claim-reap-blindspot`(12회차 관측과 합치면 2회차 —
   `series_raw`에 명기 · 대책 `HARN-189`) · `ported-classification-false-positive`(선례 2건과 합치면
   3회차 — `series_raw`에 명기 · 대책 `HARN-190`) · `derived-index-not-rebuilt` **3회차**(이 감사 자신의
   검증에서 발생: 사고를 `incident add`로 쓴 뒤 `backlog/jit_index.json`을 재생성하지 않아 로컬 CI 미러의
   harness-integrity가 "적시 주입 인덱스 대조"에서 exit 1 · 뒤 스텝 7건 미실행. 푸시 전 발견 · origin/main
   워크트리 대조로 원인 확정 · `backlog.py jit build`로 재생성 · 대책 태스크 `HARN-179`는 이미 등재돼 있다) ·
   `harness-test-live-ledger-write` **14회차**(재검증 미러의 `tests/harness`가 이 세션 샤드에 편집한 적 없는
   `scripts/harness/backlog.py`에 대한 가짜 `policy_warn` 3줄을 씀 — 커밋본 앞부분 바이트 동일·추가분 전부 가짜임을
   단언한 뒤 제거. 대책 `HARN-170`은 09-24 이후 14회 기록됐는데 아직 우선순위 3·EOS P2다).
   *회차 표기 주의(스냅샷 — main `559be84e` 병합 후 `backlog.py incident series` 실측)*: 두 검증 사고는 이 브랜치에서
   기록할 때 각각 2회차·7회차였다(이벤트 샤드의 `nth` 값). 그런데 같은 날 다른 세션들이 **같은 두 계열을 계속 기록**해
   main을 병합할 때마다 앞에 끼어들었고(`harness-test-live-ledger-write` 기준 `ed3d14da` 8 · `78a8edff` 9 ·
   `6c880b67` 10 · `de3f5487` 11 · `09501c5f` 12 · `48138a88` 12 · `559be84e` 14), 지금 대장 기준 3회차·14회차다 —
   즉 HARN-179·HARN-170의 결함을 오늘만 여러 세션이 겪고 있다. 병합 시 main 쪽 기록을 그대로 앞에 두고 이 브랜치 줄 4개를
   끝에 붙였다(main 대비 순수 추가). `de3f5487` 병합 때는 이 표기를 갱신하지 않아 이 문서가 한동안 실제
   11회차를 10회차로 적고 있었다 — 병합할 때마다 `incident series`로 다시 재야 한다. 대장은 회차를 저장하지 않고 읽을 때 계산하므로, 이 숫자는 머지 시점에 또 바뀔 수
   있다. EOS-129 중복 사고는 #1356 쪽 1건으로 일원화했다(§5).
4. **직전 배치 집행 확인** — 잔존 0/8.

### ① claim 대장 이상의 원인 — 12회차가 "보고만" 한 건

12회차는 활성 claim 2건이 존재하지 않는 브랜치를 가리킨다고 보고했다. 그중 `SEC-35` 건은
해소됐고, `OPS-73-generated-inventory-conflict-blocks-ci` → `claude/status-38gu4d`는 **16일째**
남아 있다. 원인은 두 결함의 합성이다.

- 그 태스크는 2026-09-12에 `OPS-76-generated-inventory-conflict-blocks-ci`로 **개명**됐다
  (같은 번호를 다른 세션이 `OPS-73-runbook-evidence-fence-guard`로 먼저 머지 · OPS-76 notes
  [개명 2026-09-12]). 개명 CLI(HARN-100 · #1148)가 같은 날 늦게 착지하기 전의 수동 개명이라
  claim이 따라오지 않았다. OPS-76은 done이다.
- `remote_claims.stale_claims()`는 `task is None`이면 곧바로 `task_missing`으로 분류하고
  넘어가 홀더 브랜치 부재(`branch_gone`) 판정에 **도달하지 않는다**. 자동 청소
  (`harness-audit.yml` · main push·야간)는 `task_missing`을 의도적으로 제외하므로 이 claim은
  영구히 남는다. 기존 테스트 `test_branch_gone_takes_precedence_over_ttl`이 같은 논리("순서는
  표시 문구가 아니라 집행 여부를 바꾼다")를 ttl에 대해서는 고정했지만 task_missing에 대해서는
  그 순서를 검사하는 테스트가 없다.

```bash
python3 scripts/harness/backlog.py claims reap                      # dry-run: (task_missing, claude/status-38gu4d)
git ls-remote --heads origin claude/status-38gu4d | wc -l           # 0
git log origin/harness-claims --format='%h %cI %s' -- claims/OPS-73-generated-inventory-conflict-blocks-ci.json
```

## 7. 정직한 공백

- **② 추적 중 15건의 잔여 diff 전수 대조는 하지 않았다.** 확인한 것은 "좌석이 살아 있는가"
  (전수 status 조회 + 주요 좌석 본문 확인)까지다. 8~10회차 범위를 승계한다.
- **스킬 §3의 grep 범위를 넓혔다.** 스킬 원문은 `-- backlog/tasks docs`만 보는데, 이번에는
  `.github`·`MEMORY.md`까지 봤고 그래서 §3-(d)의 체크아웃 안내를 찾았다. 원래 범위로는 보이지
  않는 위치다. 스킬 문서는 고치지 않았다(범위 밖) — 다음 회차가 같은 범위로 돌려야 같은 것을 본다.
- **claim 활성 2건(`status-f6qz0c`·`status-f9lp65`)은 판정 보류를 유지했다.** 둘 다 block 홀드이고
  `claims reap`은 TTL 초과(stale)로 분류하지만, 자동 청소 대상 사유가 아니라 남아 있다. EOS-63은
  main에서 todo인데 원격 홀드는 27일째다 — 홀드를 걷는 것은 이 감사의 권한이 아니다.
- **감사 중 대장이 움직였다.** 재fetch에서 main은 `919865d4` 그대로였지만, 열린 PR #1349의 head가
  전진했고, 새 claim 2건(`ARCH-68`·`HARN-184`)과 새 브랜치 1건(§5)이 생겼다. 판정 수치는 위
  기준 시점 값이며 소급 갱신하지 않는다.
- **떠돌이 좌석 3건(판정 아님)** — `HARN-121`(review)·`SKB-03`(review)·`SKB-04`(in_progress)의
  세션 브랜치가 원격에 없다. 셋 다 작업은 머지됐다(#1246·#1241 · #1163 · #1165) — 코드 소실이
  아니라 상태 표기 문제다. 떠돌이 *브랜치*가 아니라 이 스킬의 4분류 밖이다.
- **Kiki 보존 커밋을 지운다.** (a)의 `a737df74`는 Kiki가 직접 보존하려고 올린 커밋이다. 내용이
  전부 main에 더 새로운 판으로 있음을 확인했지만, 이 배치가 머지되면 원격에서 사라진다(Kiki 로컬
  클론에는 남는다). 복구 경로는 위 SHA다.
