# 미머지 브랜치 전수 감사 10회차 — 2026-09-10

> **판정 기준: main `df5acc33`** (unshallow 상태 유지 · 이 세션 시작 시 이미 이 저장소는 unshallow였다).
> 이 문서는 그 시점의 스냅샷이며, 선행 판정 문서(8회차 `_r2.md`·9회차 `_2026-09-08.md`)는
> 수정하지 않는다. 9회차 기준 `4abacdce`에서 main이 전진했다.

## 0. 전제 복구 — shallow 해소

이 세션은 이전 태스크(HARN-05, Gate 0 r6 판정 복원)를 진행하며 이미 `git fetch --unshallow origin`을
실행해 두었다. 이 감사 착수 시 재확인:

```bash
git rev-parse --is-shallow-repository        # false
git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'   # 유령 브랜치 0건
```

## 1. 모집단 분리 (실측)

원격 브랜치 **39건**(`harness-claims`·`main`·`HEAD` 제외) — 9회차(38건) 대비 +1.

| 분류 | 건수 | 비고 |
|---|---|---|
| PR 소유(열린 PR) | 20 | 각 PR이 소유 — 감사 범위 밖. 유령 PR(head 브랜치 부재) 0건 |
| 원격 claim 활성 | 3 | `status-f6qz0c`(EOS-63)·`status-f9lp65`(HARN-56)·`test-driven-development-03elxp`(MP-02) — 다른 세션 작업 중, 손대지 않음. 9회차의 `status-iraoq3`(MISC-21)는 이번 population에 **부재**(브랜치 삭제 확인 — claim 해제 후 정리된 것으로 보임) |
| **감사 대상(PR 미오픈·claim 없음)** | **15** | 14건은 8·9회차가 이미 좌석 부여, **1건 신규**(`misc-24-extremum-ambiguous-coincidence`) |

**중요 정정 — 이번 회차 자신의 오류 자가발견**: 이 감사에 착수하기 전, 별도 작업(HARN-05)에서
`claude/entity-model-freeze-lji37v` 브랜치를 "미머지 감사 문서 어디에도 등장하지 않는 완전 고립"으로
잘못 판단해 PR을 열고 처리한 바 있다. 이번 감사 과정에서 그 브랜치가 실제로는 **PR #1007로 이미
2026-09-06부터 노출되어 있었음**(오픈·`mergeable_state: blocked`)을 확인했다 — 즉 "고립"이 아니라
"PR 소유" 분류에 들어가야 했다. PR을 먼저 조회하지 않고 브랜치 히스토리만으로 판정한 것이 원인이다
(이 스킬 §1의 "열린 PR 목록을 먼저 확보하라" 절차를 그 작업에서는 밟지 않았다). HARN-05 자체의
조치(r6 판정문 복원)는 내용상 옳았고 이미 main에 머지됐으므로 되돌리지 않는다 — 다만 PR #1007은
이제 r6 부분에 한해 중복이 됐다(§6 정직한 공백에 기록).

## 2. 직전 배치 집행 확인

```bash
for b in $(grep -v "^#" .github/branch-cleanup-request.txt | grep -v "^\s*$"); do
  git show-ref --verify --quiet "refs/remotes/origin/$b" && echo "잔존: $b"; done
# → 잔존 0 / 22 (8차 배치 a3ysut 포함)
```

누적 22건 **전건 잔존 0**. 8차 배치(`backup/ai-content-a3ysut-pre-rebase` = `b271671b`)도 삭제 확인.

## 3. 3축 측정 — 15개 감사 대상 브랜치

14건은 head SHA가 9회차 시점과 **100% 동일**(신규 커밋 0 — 상태 변화 없음, 직접 확인). 이번 회차는
그 14건을 독립 재실측(3축 측정 + 이중 확인: main grep으로 코드 실재 여부 교차검증)하고, 신규 1건
(`misc-24`)을 추가로 조사했다.

| # | 브랜치 | ahead/behind | diff(src/tests) | 판정 | 소유 |
|---|---|---|---|---|---|
| 1 | `misc-24-extremum-ambiguous-coincidence` | 11/3 | 13(8) | **삭제 가능(신규)** | 아래 §3.1 |
| 2 | `openrouter-setup-guide-e98dw4` | 373/13 | 37(27) | 추적중 | S3-28·VIZ-06(done)·NLP-04(done)·VIZ-11 |
| 3 | `remaining-track-34zvse` | 277/16 | 33(23) | 추적중 | CUR-07·HARN-80 |
| 4 | `subject-problems-theory-check-7n9n72` | 286/34 | 83(49) | 추적중 | ASM-06·MISC-01/03·HARN-79 |
| 5 | `whymath-ai-content-design-vafylb` | 309/8 | 7(1) | 추적중 | S4-59·OPS-53 |
| 6 | `whymath-ai-recommendation-review-q8tvcx` | 351/3 | 11(2) | 추적중 | OPS-67(SEC-32는 done 착지 확인) |
| 7 | `whymath-coding-architecture-iws58k` | 292/1 | 16(1) | 추적중 | ARCH-30 |
| 8 | `whymath-constitution-rules-check-azdnov` | 286/1 | 5(0) | 추적중 | OPS-41 |
| 9 | `whymath-curriculum-design-6eejrv` (PR #802 closed·미merge) | 250/9 | 6(3) | 추적중(잔여 0) | PB-08 |
| 10 | `whymath-data-platform-design-t608mk` | 282/1 | 7(0) | 추적중 | OPS-41 |
| 11 | `whymath-issues-review-k20m0w` | 298/45 | 133(95) | 추적중 | MOB-18·SEC-30·PB-14·HARN-25 |
| 12 | `whymath-mvp-plan-architecture-trjg5x` | 339/81 | 233(188) | 추적중 | PB-13·PB-14·ADMIN-02·PB-06 |
| 13 | `whymath-pedagogy-review-gdmwhk` | 286/1 | 31(21) | 추적중(코드 잔여 0) | PED-26 |
| 14 | `whymath-pedagogy-review-uqyg79` (PR #675 closed·미merge) | 367/38 | 76(51) | 추적중(코드 잔여 0) | PED-26 |
| 15 | `whymath-service-operations-review-5t5lmv` | 282/6 | 33(17) | 추적중(코드 미흡수 확인) | OPS-40 |

**신규 좌석 상실 0건 · 신규 미추적 고립 0건.** 8·9회차의 좌석 배정이 그대로 유효함을 이번 회차가
독립적으로 재확인했다(각 브랜치의 핵심 파일/심볼을 `git show origin/main:<path> | grep`으로 직접
대조 — 상세 근거는 이 감사에 위임한 조사 태스크의 원 출력을 §7에 요약).

### 3.1 misc-24-extremum-ambiguous-coincidence — 신규 판정

최종 커밋 2026-09-08(약 45시간 전). 소유 태스크 `MISC-24-extremum-ambiguous-coincidence-overconfidence`는
**이미 `done`**이고, notes에 처분 경위가 상세히 기록돼 있다:

- 원래 이 작업은 `claude/status-vlul18`에서 진행됐으나 그 브랜치에는 이미 PR #1071(MISC-22)이 열려
  있어(GitHub는 같은 head→base 쌍에 PR 1개만 허용) 별도 브랜치 `misc-24-extremum-ambiguous-coincidence`를
  만들어 PR #1072를 열었다.
- 이후 MISC-22·MISC-24·Codex P1 후속 대응이 전부 `status-vlul18`의 PR #1071 **하나로 순차 커밋 통합**됐고,
  PR #1072는 diff가 겹치는 중복이라 **close(머지하지 않음)**로 정리됐다.

GitHub 실측으로 이 경위를 직접 검증했다:
- **PR #1071**: `state: closed, merged: true` (2026-09-09 07:54:47 UTC 머지) — 본문이 MISC-22·MISC-24·
  Codex P1 후속을 모두 포함한다고 명시
- **PR #1072**: `state: closed, merged: false` — notes의 처분 결정과 GitHub 실제 상태가 일치

이중 확인: 브랜치 diff 13파일 중 `models.py`는 main과 바이트 동일, `catalog.py`는 main이 MISC-25
후속 작업까지 포함한 상위집합(고유 줄은 들여쓰기 차이뿐, 내용 유실 없음). **main 부재 0건**.

→ 고유 내용 없음 · PR 닫힘·미머지 확정 · 소유 태스크 done → **삭제 배치 등재** (§5.2).

## 4. 4분류 판정

| 분류 | 건수 | 내역 |
|---|---|---|
| ① 회수 필요(미추적 고립) | **0** | 15건 전부 좌석 보유(14건 기존·1건은 이미 done 처리된 코드의 잔여 브랜치) |
| ② 추적 중 | **14** | e98dw4·34zvse·7n9n72·vafylb·q8tvcx·iws58k·azdnov·6eejrv·t608mk·k20m0w·trjg5x·gdmwhk·uqyg79·5t5lmv |
| ③ **삭제 가능** | **1** | `misc-24-extremum-ambiguous-coincidence` (head 커밋은 §5.2에 스냅샷) |
| ④ 제외 | 23 | PR 소유 20(entity-model-freeze-lji37v 포함) · claim 활성 3 |

## 5. 조치

### 5.1 신규 회수 태스크 등재 — **0건**

15개 감사 대상 전부 기존 좌석(또는 이미 완결된 done 태스크)이 있어 새로 등재할 미추적 갭이 없다.
기존 좌석 중 다음은 여전히 `todo`이고 실제 코드 회수/판정이 남아 있다 — 착수는 각 담당 세션이
`backlog.py start`로 진행할 사안이며 이 감사는 그 착수를 대신하지 않는다:

- **OPS-40**(5t5lmv) — client version gate + A11Y-02 코드가 아직 main에 없음을 직접 확인(회수 미착수)
- **PED-26**(gdmwhk·uqyg79) — 코드는 main이 우세하나 문서/판정 축(REND-05·PED-21·04e/04f 번호 정리) 잔존
- **PATH-03 / PB-14**(trjg5x) — 회수 원천 amend 미완료(main PATH-03이 todo인데 회수 대상 지목이 안 됨)
- **HARN-80 / CUR-07**(34zvse) — 코드는 이미 main에 직접 커밋(`7b4fb546`)으로 착지했으나 대장(YAML)이
  이를 반영 못함 — PR 증적 게이트가 거부하는 경로를 HARN-80이 신설 예정
- **ASM-06**(7n9n72) — `problem_attempt.selected_choice_index` alembic 마이그레이션 미흡수
- **OPS-41**(azdnov·t608mk) — 판정 문서 미승격
- **OPS-67**(q8tvcx) · **ARCH-30**(iws58k) — 각 잔여 1건씩

### 5.2 삭제 배치 1건

`claude/misc-24-extremum-ambiguous-coincidence` — head SHA 스냅샷은 `.github/branch-cleanup-request.txt`
9차 배치 항목 참조.

### 5.3 좌석 amend — 0건

이번 회차가 새로 붙일 amend는 없다(§3의 재확인은 기존 좌석의 유효성을 재확인했을 뿐 새 갭을 찾지 못함).

## 6. 정직한 공백

- **PR #1007(entity-model-freeze-lji37v)의 처분 미정** — §1에서 기록한 대로, 이 PR의 "Gate 0 판정 r6"
  부분은 이미 이 세션의 별도 작업(HARN-05·PR #1081)이 main에 직접 포팅해 반영했다. PR #1007에는
  그 외에도 `HARN-77`·`OPS-65`·`OPS-66` 백로그 등재·`HARN-39`/`HARN-75` 정정이 남아 있어, PR 전체를
  단순히 닫아도 되는지는 이 감사가 판정하지 않는다(PR 소유 브랜치는 감사 범위 밖 — §1 원칙). PR
  작성자/후속 세션이 "r6 부분은 이미 다른 경로로 착지했으니 그 hunk만 제외하고 나머지(HARN-77 등)를
  재제출할지, PR 전체를 갱신할지"를 판단해야 한다.
- **실행 검증 0** — 전건 정적 git 대조다. 브랜치 코드를 현 main 위에서 실행하지 않았다. misc-24의
  "main이 더 넓다" 판정은 GitHub API로 PR 상태를 확인하고 파일 대조로 보강했으나 테스트 실행 근거는
  아니다(다만 소유 태스크가 이미 108 passed로 검증을 마친 done 상태라 재검증이 필요한 구간이 아니다).
- **PR 소유 20건은 판정 밖** — 각 PR의 처분은 그 PR이 소유한다.
- **claim 활성 3건 무판정** — 다음 회차 재료로만 남긴다.
- **14건의 todo 좌석 진척은 보지 않았다** — §3 표는 좌석 *생존*(main에서 여전히 그 브랜치를 참조하는
  유효한 소유자가 있는가)만 본다. 실제 착수 여부는 이 감사 범위 밖.

## 7. 검증 (전건 exit code — `-q`/`tail` 절단 없음)

```
✔ 백로그 무결성 green                                                  EXIT=0
```

```
python3 scripts/harness/backlog.py next --n 3
```
14건 좌석 중 다수가 `next`의 "이미 완료(미머지)" 배선(HARN-11)에 **실시간으로 잡힌다** — 이 감사가
git으로 직접 재확인한 좌석 목록과 하네스 자체의 판정이 서로 다른 경로로 일치한다:

```
⚠ 후보 제외 MISC-01/03·PB-02·PED-14·S3-33·S3-34 — 이미 완료(미머지): claude/subject-problems-theory-check-7n9n72
⚠ 후보 제외 MOB-11·PB-04·S4-22 — 이미 완료(미머지): claude/whymath-issues-review-k20m0w
⚠ 후보 제외 PATH-03 — 이미 완료(미머지): claude/whymath-mvp-plan-architecture-trjg5x
⚠ 후보 제외 PB-08 — 이미 완료(미머지): claude/whymath-curriculum-design-6eejrv
⚠ 후보 제외 S3-28 — 이미 완료(미머지): claude/openrouter-setup-guide-e98dw4, claude/status-9rqolq
```
(`status-9rqolq`는 오픈 PR #1076 소유 브랜치 — 여기서는 단순히 같은 태스크를 병렬로 건드리고
있다는 정보이지 감사 대상이 아니다.)
