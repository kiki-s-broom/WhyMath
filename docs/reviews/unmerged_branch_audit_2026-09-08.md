# 미머지 브랜치 전수 감사 9회차 — 2026-09-08

> **판정 기준: main `4abacdce`** (unshallow 후 실측 · 1,043커밋). 이 문서는 그 시점의 스냅샷이며,
> 선행 판정 문서(7회차 `unmerged_branch_audit_2026-09-07.md` · 8회차 `_r2.md`)는 수정하지 않는다.
> 8회차 기준 `b75f495d`에서 main이 42커밋(8회차 판정 커밋 `d50781b7` 기준 34커밋) 전진했다.

## 0. 전제 복구 — shallow 해소

세션 시작 시 저장소는 **shallow(52커밋)**였고 SessionStart 브리핑도 "장기 미머지 브랜치 조회 불가 —
판정 보류"를 냈다. 판정 전에 풀었다.

```bash
git rev-parse --is-shallow-repository        # true → 판정 금지 상태
git fetch --unshallow origin                 # 52 → 1,043커밋
git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'
git rev-parse --is-shallow-repository        # false
```

## 1. 모집단 분리 (실측)

원격 브랜치 **38건**(`harness-claims`·`main`·`HEAD` 제외).

| 분류 | 건수 | 비고 |
|---|---|---|
| PR 소유(열린 PR) | 19 | 각 PR이 소유 — 감사 범위 밖. 유령 PR(head 브랜치 부재) **0건** |
| 원격 claim 활성 | 4 | `status-f6qz0c`·`status-f9lp65`·`status-iraoq3`·`test-driven-development-03elxp` — 다른 세션 작업 중, 손대지 않음 |
| **감사 대상(PR 미오픈·claim 없음)** | **15** | 전건 8회차가 이미 좌석 부여 |

`claims/` 대장 10건 중 **2건이 브랜치 없는 claim**이라 별도 판정했다.

| claim | 브랜치 | 판정 |
|---|---|---|
| EOS-02 → `claude/status-k9r51v` | 부재 | **정상** — `kind: "block"`(차단 홀드·HARN-45/48). 홀드는 자리를 지키는 것이 목적이라 살아 있는 브랜치를 전제하지 않는다 |
| MOB-18 → `claude/whymath-system-review-n75r24` | 부재 | **정상(아직)** — `kind` 없는 활성 claim이나 ts `2026-09-07T23:48:47Z`로 **경과 8.1h**, HARN-26 `branch_gone` grace 24h 안이다. 09-08 23:48Z 이후 `claims reap`이 잡는다 |

> 처음에 이 둘을 "유령 claim = 하네스 결함"으로 읽었으나, `remote_claims.stale_claims`를 실측하니
> HARN-26이 이미 `branch_gone`을 24h 유예와 함께 구현하고 있었다. **부재 판정 절차**(CLAUDE.md
> 2026-08-31)가 막은 오판이다 — 역할로 검색하기 전에 결론을 내렸으면 없는 결함을 등재할 뻔했다.

## 2. 직전 배치 집행 확인

```bash
for b in $(grep -v "^#" .github/branch-cleanup-request.txt | grep -v "^\s*$"); do
  git show-ref --verify --quiet "refs/remotes/origin/$b" && echo "잔존: $b"; done
# → 잔존 0 / 21
```

누적 21건 **전건 잔존 0**. 허용 패턴 밖 수동 삭제 3건(`gates/deploy-environment-approval` ·
`pr/collab-07` · `backend/cur-16-*`)도 전건 삭제 확인.

**부수 관측**: 이 파일은 이미 삭제된 21건을 계속 열거하고, `branch-cleanup.yml`이 그 404를 실패로
계상해 매 실행 red다. 이 감사가 그 전제를 독립 재확인했으며 소유 태스크는 **HARN-01**(등재 완료·
현재 `next` 1순위)이다 — 재등재하지 않는다.

## 3. 3축 측정 — 8회차 대비 델타

**신규 브랜치 0건 · 좌석 상실 0건.** 8회차 이후 done이 된 좌석은 3건이나 어느 브랜치도 마지막
좌석을 잃지 않았다.

| 좌석 | 전이 | 브랜치 | 잔여 좌석 |
|---|---|---|---|
| PED-37 | todo → **done** (#1036·#1037) | 7n9n72 | 좌석 10건 잔존 |
| SEC-32 | todo → **done** (#1036) | q8tvcx | OPS-38·OPS-67 잔존 |
| HARN-78 | todo → **done** (#1043) | (브랜치 좌석 아님) | — |

### 3.1 회수 done 2건의 acceptance 전수 재대조 (규칙 의무)

"회수로 done 선언 시 acceptance 전수 재대조 생략 금지"(CLAUDE.md 2026-08-10)의 이행이다.

- **PED-37** — Codex P1이 요구한 잔여(`duration_seconds` 미제공 시 `started_at`이 여전히 NULL →
  파기 불가)는 **SEC-33**(#1052·done)이 승계해 착지했다. 미이행 0.
- **SEC-32** — ①이 "후행 `eos_privacy_gap_analysis.md`도 정정 대상"이라 명시했고 artifacts 줄에는
  문서 정정이 안 적혀 있어 별도 확인했다. **실제로 정정됐다**: 같은 문서 166행에 정정 블록,
  245·274행이 "ClickHouse·S3는 미도입" 표기로 갱신. 미이행 0.

### 3.2 8회차 비평 #1이 남긴 미커버 17건 — 해소 확인

8회차 §8.1은 "7n9n72 좌석 8건의 커버가 **미머지** PR #1020에만 있다"고 자기 위반을 수용했다.
그 뒤 #1020·#1027·#1033이 전부 머지됐다. main 기준 재확인:

```bash
for t in ASM-06 MISC-02 MISC-05 MISC-06 PB-02 PED-14 S3-33 S3-34 MISC-01 MISC-03; do
  f=$(git ls-tree -r --name-only origin/main backlog/tasks/ | grep -m1 "/${t}-")
  echo "$t $(git show origin/main:"$f" | grep -c 7n9n72)"; done
# → 10건 전부 2건씩 참조 · 미커버 0
```

**해소.** 8회차가 "사람 기억에만 의존"이라 적은 상태는 끝났다.

### 3.3 8월 PR 10건 — 8회차가 지목한 "다음 회차 최우선 관찰 대상"

전건 라벨이 붙은 채 **2026-08-31T06:24Z 이후 8일간 갱신 0**이다.

| PR | 라벨 | 브랜치 | main 부재 파일 | 총 diff |
|---|---|---|---|---|
| #882 | eos-rework | `backend-eos-204-education-event-phase1` | **12** | 17 |
| #880 | eos-rework | `claude/backend-audit-event-foundation-29ac1b` | **6** | 22 |
| #847 | eos-rework | `claude/ops-02-offsite-backup-move` | 2 | 7 |
| #844 | eos-postpone | `s4-16-blocked-evidence` | 1 | 15 |
| #865 | eos-postpone | `claude/s4-16-openrouter-provider` | 1 | 42 |
| #893 | eos-rework | `claude/backend-misc-12-16-misconception-review-impl` | 1 | 8 |
| #846 | eos-rework | `s1-17-phase-b-math-extension` | 0 | 3 |
| #856 | eos-postpone | `claude/lic-01-rights-provenance-mvp` | 0 | 11 |
| **#858** | **eos-close** | `claude/lic-01-rights-provenance-mvp-2` | 0 | **28** |
| #860 | eos-postpone | `claude/ops-50-51-52-moe-rocm-followup` | 0 | 39 |

> **집계 기준 주의**: "main 부재 파일"은 `^(src|tests|scripts|data)/` 기준이다. 처음 `^(src|tests)/`로
> 재도출했더니 #847=1·#882=11이 나와 8회차 수치(2·12)와 어긋났고, 8회차가 틀렸다고 적을 뻔했다.
> 패턴을 넓히자 정확히 재현됐다 — **8회차 수치가 옳고 내 패턴이 좁았다**(라벨만 "src"로 뭉뚱그려진 것).
> `b75f495d`와 `4abacdce` 양쪽에서 같은 값이므로 그 사이 main 흡수도 0이다.

**탐지기 공백 (9회차 신규 관측)**: `backlog.py branches`는 PR의 열림/닫힘만 가르고 **처분 라벨을
보지 않는다**. 실측 출력에서 10건 전부가 활성 PR과 동일한 `[PR]`이며, PR #975(5일 전·실작업 중)와
#858(`eos-close`·16일 전·닫기로 결정됨)이 같은 줄 모양이다. HARN-78(done)이 닫힌 PR을 `pr_closed`로
분리했으나 그것은 *이미 닫힌 뒤*의 축이고 이 공백은 *닫히기 전*이다.

→ **HARN-93 등재**(아래 §5).

## 4. 4분류 판정

| 분류 | 건수 | 내역 |
|---|---|---|
| ① 회수 필요(미추적 고립) | **0** | 15건 전부 8회차가 좌석 부여·이번 회차에 좌석 상실 0 |
| ② 추적 중 | **14** | 7n9n72 · trjg5x · k20m0w · gdmwhk · uqyg79 · 34zvse · 5t5lmv · iws58k · t608mk · azdnov · 6eejrv · e98dw4 · q8tvcx · vafylb |
| ③ **삭제 가능** | **1** | `backup/ai-content-a3ysut-pre-rebase` (b271671b) |
| ④ 제외 | 23 | PR 소유 19 · claim 활성 4 |

### ③ 삭제 판정 근거 — a3ysut (독립 재도출)

8회차는 "OPS-41 ④(a): 이 축 충족·삭제 후보 근거 성립(**착수 세션 재확인 후**)"으로 조건을 달았다.
좌석 본문이 그 권한을 명시한다: *"착수 세션이 재확인 후 삭제 배치 후보로 내릴 수 있다."*
9회차가 그 재확인을 수행했다.

```bash
B=origin/claude/backup/ai-content-a3ysut-pre-rebase
for f in $(git diff --name-only origin/main...$B); do
  git cat-file -e origin/main:"$f" 2>/dev/null \
    && echo "$f $(comm -23 <(git show $B:"$f"|sort -u) <(git show origin/main:"$f"|sort -u)|wc -l)" \
    || echo "$f ★main부재"; done
```

- **main 부재 0/16** — diff 16파일 전부 main 실재(PR #819 `081d235a`로 착지, 파일 집합 일치).
- **고유 줄 20(6파일) 전건 옛 판** — 직접 판독: `CONT-02/03/04`는 `updated: 2026-08-11`과 옛 `notes`뿐,
  `concept_assessment_index.py` 2줄·`test_enums.py` 3줄은 옛 시그니처·docstring,
  `schema/enums.py` 9줄은 브랜치가 `ReviewStatus` 3종 docstring인 데 반해 **main은 3종+`quarantined`+
  EOS-71 비파괴 원칙 근거**를 갖는다 — 전 항목에서 main이 더 넓다.
- 8회차가 유일 uncovered로 남긴 `MEMORY.md` 글자 깨짐은 #1027이 정정해 **지금 고유 줄 0**.
- OPS-41의 나머지 두 축(`t608mk`·`azdnov`)은 브랜치가 그대로라 영향 없다.

→ `.github/branch-cleanup-request.txt` **8차 배치(1건)** 등재. head SHA `b271671b` 스냅샷 병기.

### claim 활성 4건 — 판정 아님·다음 회차 재료

| 브랜치 | ahead/behind | diff | 소유 | 비고 |
|---|---|---|---|---|
| `status-f6qz0c` | 0↑/99↓ | **0** | EOS-63 | 잃을 내용 0 — claim 해제 시 즉시 삭제 후보(7차 배치 승계) |
| `test-driven-development-03elxp` | 0↑/25↓ | **0** | MP-02 | 잃을 내용 0 — **9회차 신규 측정**(7차 배치는 diff를 적지 않았다) |
| `status-f9lp65` | 2↑/82↓ | 5 | HARN-56 | 8회차 §6이 줄 단위 대조 재료를 준비해 둠 |
| `status-iraoq3` | 1↑/0↓ | 2 | MISC-21 | **9회차 신규 등장** |

## 5. 조치

### 5.1 신규 등재 1건 (전건 `backlog.py add` 경유 — 대장 손편집 0)

| ID | 무엇 | priority / EOS |
|---|---|---|
| **HARN-93**-pr-disposal-label-expiry | 처분 라벨이 붙은 열린 PR 10건의 만료 없는 유예 — 닫기 전 파일 단위 대조·회수 좌석 선행이 **무소유**. 탐지기가 라벨을 안 보는 축 포함 | 2 / P2 |

역할 기준 검색 3종으로 기존 소유자 부재를 확인했다(이름 추측 금지 — CLAUDE.md 부재 판정 절차):
①라벨명 `grep` → `HARN-42`와 문서 2건뿐 ②"닫기 전/닫히면/PR 처분" 어구 → 무관 태스크 3건
③`HARN-42`(done)의 acceptance ④가 **집행을 사람에게 넘기고 종료**. `add`의 의미 중복 탐지는
HARN-79와 유사도 0.14로 무관 판정.

### 5.2 삭제 배치 1건

`claude/backup/ai-content-a3ysut-pre-rebase` = `b271671b` (§4 ③).

### 5.3 좌석 amend 0건

8회차가 12건을 amend했고 후속 #1033이 3건을 보완해 **main 기준 미커버 0**이다(§3.2). 이번 회차가
새로 붙일 것이 없다.

### 5.4 감사가 잡은 별건 — 이 세션 자신의 PR 결함

이 감사가 `MOB-18`(세션 끊긴 `in_progress`)을 실측하다가 **같은 세션이 30분 전에 연 PR #1067의
결함**을 발견했다. HARN-86이 추가한 전이 거부 안내가 이 상태에서 이렇게 나왔다:

```
❌ MOB-18-...: in_progress → in_progress 전이 불가 (허용: ['review','done','blocked','todo'])
  해소 경로 (0단계): in_progress          ← 실행할 명령이 하나도 없다
```

뿌리는 `_transition_route(x, x)`가 `[]`를 돌려주고(경로 탐색기로서는 옳은 답) 호출부가 그것을
0단계 경로로 렌더한 것이다. 전수 가드는 `src != dst` 쌍만 생성해 **이 절을 한 번도 밟지 않았다** —
CLAUDE.md 2026-09-07 "픽스처가 그 절을 실제로 밟는가"의 3회차다. PR #1067에서 수정했고
뮤테이션 4종(누적 13종) 전건 RED로 동결했다. 타이브레이크가 의미를 가른다: `in_progress` 재진입
고리는 `review` 경유·`todo` 경유가 둘 다 2단계지만 `cmd_review`는 원격 claim을 **유지**하고
`cmd_unblock`은 **해제**한다 — 재진입 요청은 앞 홀더가 사라졌다는 뜻이므로 자리를 비우는 쪽이 옳다.

## 6. 정직한 공백

- **실행 검증 0** — 전건 정적 git 대조다. 브랜치 코드를 현 main 위에서 돌리지 않았다. a3ysut의
  "main이 더 넓다" 판정은 **소스 판독**이며 테스트 실행 근거가 아니다(다만 부재 0·고유 줄 20이라
  판정에 실행이 필요한 구간이 없다).
- **PR 소유 19건은 판정 밖** — §3.3은 *위험 측정*이지 판정이 아니다. 각 PR의 처분은 그 PR이 소유하며,
  HARN-93은 닫기 전 선행을 만들 뿐 닫을지를 정하지 않는다(되돌리기 어려운 행위 = Kiki).
- **claim 활성 4건 무판정** — `f6qz0c`·`03elxp`는 diff 0이라 삭제해도 잃을 것이 없어 보이나,
  claim이 살아 있는 동안은 다른 세션 소유다. 다음 회차 재료로만 남긴다.
- **8회차가 등재한 7건의 착수 여부는 보지 않았다** — SEC-32만 done을 확인했고
  MGMT-03·HARN-78·79·80·OPS-67·VIZ-11의 진척은 이 감사 범위 밖이다(§3 표는 좌석 *생존*만 본다).
- **`branches` 라벨 공백의 조치안 2종(HARN-93 ②)은 설계가 아니라 선택지**다. 어느 쪽이 옳은지는
  착수 세션이 정한다 — 특히 (a)안은 토큰 없는 경로에서 라벨 조회가 불가하므로 HARN-78 ②의
  오프라인 원칙을 어떻게 승계할지가 미해결이다.
- **감사 중 main 전진 0** — 시작(`4abacdce`)과 종료 시점이 같다. 8회차가 겪은 판정 기준 드리프트는
  이번엔 없었다.

## 7. 검증 (전건 exit code — `-q`/`tail` 절단 없음)

```
✔ 백로그 무결성 green — 태스크 597건, 게이트 39건, 트랙 3건            EXIT=0
✔ 의존 선언↔집행 green — 위반 0건 (레거시 그랜드파더 0 · 소프트 8)     EXIT=0
next --n 200 --json → 후보 122건 · HARN-93 **1순위**                    (배선 확인)
overlap HARN-93 → 경고 3건(S4-57 · S4-59 · S5-01)                       EXIT=0
```

`overlap` 경고 3건은 전건 **상대측의 광범위 glob**이 이 태스크의 좁은 경로를 포함한 것이지
같은 파일을 고치는 작업이 아니다(`docs/**` ⊇ `docs/reviews/**` · `backlog/**` ⊇ `backlog/tasks/**`).
8회차 §9·08-31 감사 §7과 동형이다.

**대장 쓰기 내용 보존 대조** — `add`에 넘긴 산문을 인용 heredoc(`<<'EOF'`) + 파일 경유로 전달한 뒤
저장된 YAML을 파싱해 핵심 식별자 13종(`4abacdce`·`b75f495d`·`eos-close`·`#882`·`backlog.py branches`·
`pr_closed` 등)의 생존을 확인했다 — **누락 0**. 2026-09-08 백틱 명령 치환 사고(v0.2.19)의 절차 이행이며,
"쓰기 성공 ≠ 내용 보존"이므로 읽어서 대조하는 것까지가 한 동작이다.

### 7.1 부수 검증 — PR #1067(§5.4 결함 수정)

```
tests/harness 766 passed                        EXIT=0
ruff check scripts tests/harness                EXIT=0
black --check --line-length 100 …               EXIT=0
뮤테이션 N1~N4 전건 RED (누적 13/13)
```
