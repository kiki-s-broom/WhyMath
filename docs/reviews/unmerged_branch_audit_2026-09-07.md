# 미머지 브랜치 전수 감사 — 2026-09-07

> **시점 스냅샷 선언.** 이 문서는 2026-09-07 `origin/main = 98925b0e` 시점의 원격 상태를 고정한 것이다.
> 이후 브랜치·PR·태스크 상태 변화는 반영하지 않는다. **선행 판정 문서(08-04·08-11·08-29·08-31)는 수정하지 않는다.**
> 직전 정본: `docs/reviews/unmerged_branch_audit_2026-08-31.md`. 실행 정본은 `backlog/`(회수·정정)와
> `.github/branch-cleanup-request.txt`(삭제 배치)이며, 이 문서는 판정의 *근거*만 남긴다.

## 0. 전제 복구 — shallow 해소

세션 시작 시 클론이 shallow였고(브리핑 "장기 미머지 브랜치 조회 불가 — 판정 보류"), 그 상태의 ahead 수치·포팅
근거는 전부 오염된다(08-11 §1 결함 ①). 판정 전 복구했다.

```bash
git rev-parse --is-shallow-repository        # true → 판정 금지
git fetch --unshallow origin                 # EXIT=0
git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'
git rev-parse --is-shallow-repository        # false (실측)
git rev-list --count origin/main             # 994 (08-31 감사 904 → +90)
```

## 1. 모집단 분리 (실측)

| 구분 | 건수 | 비고 |
|---|---|---|
| 원격 ref 전수 | 40 | `git ls-remote --heads` |
| 제외: `main`·`harness-claims` | 2 | harness-claims는 하네스 claim 저장소·작업 브랜치 아님 |
| 열린 PR이 소유 | 17 | `list_pull_requests(state=open)` — 각 PR 소유, 감사 범위 밖 |
| 원격 claim 활성(다른 세션 소유) | 3 | `status-f6qz0c`(EOS-63 block) · `status-f9lp65`(HARN-56 block) · `test-driven-development-03elxp`(MP-02 block·MP-05) — 손대지 않음(④ 제외) |
| **감사 대상(PR 미오픈·claim 없음)** | **18** | 아래 §3~§4 |

**유령 PR(head 브랜치가 원격에 없는 열린 PR): 0건** — 17건의 head가 전부 원격에 실재한다.

**부수 관찰 ⓐ**: `claims/CUR-17.json`·`CUR-18.json`은 `claude/status-5kvqkv`를 가리키는데 그 브랜치는 원격에
**없다**(block 내용은 main CUR-17/18 notes에 착지). 브랜치 감사 대상이 아니라 claim 대장의 잔류 기록이다 — 이 감사의
범위 밖이므로 기록만 한다.

**부수 관찰 ⓑ**: 08-31 감사가 ②추적 중으로 분류한 `human-bottleneck-tasks-6dszy0`·`merge/human-bottleneck-6dszy0`
2건은 원격에서 사라졌다. PR 이력 0건 — `LIC-07` acceptance ⑪(2026-09-06)이 KICE PDF 이력 제거를 위해 삭제하면서
"MISC-01·MISC-03·PB-02 구현이 7n9n72에 보존(기능 마커 5/5·핵심 파일 6개 blob SHA 바이트 동일)"을 전수 증명했다.
소실 0으로 판정하며, 그 보존처가 §4-①의 `7n9n72`다.

## 2. 직전 배치 집행 확인 (`.github/branch-cleanup-request.txt` 관례)

4·5·6차 배치 19건을 `git ls-remote --heads`로 재확인: **잔존 0/19.** 허용 패턴 밖 수동 삭제 4건
(`pr/collab-07`·`backend/cur-16-*`·`curriculum/eos-curriculum-*`·`curriculum/cur-15-*`)도 **전건 삭제 완료.**

## 3. 3축 측정 (감사 대상 18 + 참고로 claim 3)

`git rev-list --left-right --count origin/main...origin/<b>` · `git diff --name-only` · done-less 사각(HARN-31:
`src|tests|data|scripts` 신규 파일) · 고립 done 스캔(#701 선례).

| 브랜치 | head | ahead | behind | diff | src | 고립 done |
|---|---|---|---|---|---|---|
| `backup/ai-content-a3ysut-pre-rebase` | b271671b | 5 | 193 | 16 | 7 | 0 |
| `drive-eos-81-sequential-wbhw8v` | 9d5f81b2 | **0** | 11 | **0** | 0 | 0 |
| `openrouter-setup-guide-e98dw4` | f8c0e3b6 | 13 | 315 | 37 | 27 | 2 (S3-28·VIZ-04) |
| `remaining-track-34zvse` | 7fb78470 | 16 | 219 | 33 | 23 | 1 (CUR-07) |
| `review-dydkkx-runbook` | dbdcdf6f | 6 | 52 | 195 | 0 | 0 |
| `subject-problems-theory-check-7n9n72` | 621b11f9 | 34 | 228 | 83 | 49 | **11** |
| `whymath-ai-content-design-vafylb` | b1218739 | 8 | 251 | 7 | 1 | 0 |
| `whymath-ai-recommendation-review-q8tvcx` | e1835c0c | 3 | 293 | 11 | 2 | 1 (OPS-19) |
| `whymath-coding-architecture-iws58k` | a8e01be2 | 1 | 234 | 16 | 1 | 0 |
| `whymath-constitution-rules-check-azdnov` | c335a787 | 1 | 228 | 5 | 0 | 0 |
| `whymath-curriculum-design-6eejrv` | 2f428729 | 9 | 192 | 6 | 3 | 1 (PB-08) |
| `whymath-data-platform-design-t608mk` | d876b523 | 1 | 224 | 7 | 0 | 0 |
| `whymath-issues-review-k20m0w` | 2330a095 | 45 | 240 | 133 | 95 | 21 |
| `whymath-mvp-plan-architecture-trjg5x` | c8abbc17 | 81 | 281 | 233 | 188 | 34 |
| `whymath-pedagogy-review-gdmwhk` | 2915bf4e | 1 | 228 | 31 | 21 | 0 |
| `whymath-pedagogy-review-uqyg79` | 5dc040b3 | 38 | 309 | 76 | 51 | 9 |
| `whymath-service-operations-review-5t5lmv` | dd3e9475 | 6 | 224 | 33 | 17 | 2 |
| `gates/deploy-environment-approval` | 907d4629 | 2 | 51 | 3 | 0 | 0 |
| *(claim)* `status-f6qz0c` | e90d2d6f | **0** | 52 | **0** | 0 | 0 |
| *(claim)* `status-f9lp65` | d792c9d0 | 2 | 35 | 5 | 2 | 0 |
| *(claim)* `test-driven-development-03elxp` | 4d30ce3b | 1 | 0 | 3 | 0 | 0 |

**diff 0파일 = 전량 흡수 브랜치가 2건 생겼다**(`wbhw8v`·`f6qz0c`) — 08-31에는 0건이었다.

## 4. 4분류 판정

### ④ 제외 — 3건 (원격 claim 활성·다른 세션 소유)

`status-f6qz0c`·`status-f9lp65`·`test-driven-development-03elxp`. 판정하지 않는다. 다만 다음 회차를 위해 실측을
남긴다: `f6qz0c`는 ahead 0·diff 0(EOS-63 차단 사유는 main에 착지)이라 claim 해제 시 즉시 삭제 후보다. `f9lp65`의
고유 98줄(`register_backup_schedule.ps1`·`test_backup_encryption.py`·DR 런북, 09-03)은 main이 #993/#1009(09-06)로
같은 결함(등록 실패 시 [OK]·Access denied 귀속)을 독립 재구현한 것으로 *보인다* — 오류 처리 패턴 수 7:7·
`TestScheduledTaskRegistrationFailsClosed` main 실재 — 그러나 줄 단위 대조는 하지 않았다(§6).

### ② 이미 추적 중 — 14건 (조치 불요·삭제 금지)

소유 태스크가 main에 실재하고 **살아 있으며**(todo/in_progress/blocked) 본문이 브랜치를 지목하는지 교차 확인했다
(`git grep -l <접미사> origin/main -- backlog/tasks` + status).

| 브랜치 | 소유 태스크 | status | 08-31 대비 |
|---|---|---|---|
| `backup/ai-content-a3ysut-pre-rebase` | OPS-41 | todo | 불변 |
| `whymath-data-platform-design-t608mk` | OPS-41 | todo | 불변 |
| `whymath-constitution-rules-check-azdnov` | OPS-41 | todo | 불변 |
| `whymath-service-operations-review-5t5lmv` | OPS-40 | todo | 불변 |
| `whymath-ai-recommendation-review-q8tvcx` | OPS-38 | todo | 불변 |
| `openrouter-setup-guide-e98dw4` | S3-28 | todo | 불변 (VIZ-04 고립 done은 VIZ-06=done이 회수) |
| `remaining-track-34zvse` | CUR-07 | todo | 불변 |
| `whymath-issues-review-k20m0w` | MOB-18 (+SEC-30·PB-14·HARN-25) | todo | 불변 (SEC-13~18은 SEC-24=done이 회수, S3-37~50·NS-01/02는 S3-24 소관) |
| `whymath-coding-architecture-iws58k` | ARCH-30 | todo | 불변 |
| `whymath-pedagogy-review-gdmwhk` | PED-26 | todo | 불변 |
| `whymath-pedagogy-review-uqyg79` | PED-26 (PED-22~25=done) | todo | 불변 |
| `whymath-curriculum-design-6eejrv` | PB-08 | todo | 불변 |
| `whymath-ai-content-design-vafylb` | S4-59 · OPS-53 | todo | 불변 (08-31 신규 등재분) |
| `whymath-mvp-plan-architecture-trjg5x` | **PB-13** (+PB-14·ADMIN-02) | **in_progress** (PR #975) | **변화** — 08-31의 게이트 `G-authoring-expansion-merge-decision`이 Kiki "회수"로 clear되고 집행 태스크 PB-13이 착수·PR 대기. 잔여(S4-19~51 yaml 32건 → PB-14 · 수정 12파일+alembic → ADMIN-02)도 소유자 실재 |

### ① 회수 조치 — `subject-problems-theory-check-7n9n72`(621b11f9) — **좌석 소멸형 고아**

08-31 감사는 이 브랜치를 "MISC-05/06이 브랜치명을 적지 않으나 **HARN-37이 브랜치 단위 소유자**로 지목한다"로
②추적 중에 두었다. 그런데 `HARN-37`은 *탐지기 결함 수정* 태스크라 회수 acceptance가 없고, #962로 **done**이 됐다.
그 순간 아래 잔여의 명시 참조가 0이 됐다 — vafylb(08-31 `S4-59`)가 *done 후 잔여 고아*였다면 이번은 *좌석의 done이
잔여를 고아로 만든* 형태다.

**main 부재 실측 17파일**(`git diff --name-only origin/main...origin/<b>` 중 `git cat-file -e origin/main:<f>` 실패):

| 잔여 | 좌석(main status) | 좌석 본문의 브랜치 지목(정정 전) |
|---|---|---|
| `harness/misconception_slip_report.py` + 테스트 | MISC-05 (todo) | 0 |
| `tests/.../test_recurrence_signal.py` (+hypothesis_store·warmstart·coach 변경) | MISC-06 (todo) | 0 |
| `tests/.../test_wh1_evaluation_time_normalized_mastery.py` (+wh1_evaluation·growth_evidence_exposure·coach 변경) | PED-14 (todo) | 0 |
| `tests/infra/test_corpus_reverify_wiring.py`·`test_problem_bank_coverage_ci_wiring.py` | PB-02 (todo) | 0 (LIC-07 ⑪만 보존 사실 언급) |
| `src/mobile/.../chat_controller.dart` select-watch + 테스트 | S3-34 (todo) | 0 |
| (코드 0 — "이미 전량 충족" done 판정) | S3-33 (todo) | 0 |
| `l4/misconception/distractor_link.py` + 테스트 + alembic `attempt_selected_choice_index` | ASM-06 (**blocked**) | 0 |
| `l4/misconception/prerequisite_link.py` + 테스트 | MISC-02 (**blocked**) | 0 |
| `tests/backend/api/test_coach_similar_problem.py`·`test_coach_visualization.py`·`test_misconception_visualization_shadow.py` | MISC-01·MISC-03 (todo) | 1·1 (HARN-34 고립 참조 — 유지) |
| `backlog/tasks/PED-15-problem-attempt-started-at-null-*.yaml`·`PED-16-problem-attempt-retention-*.yaml` | **없음** — main PED-15/16은 다른 태스크 | — |
| alembic `dialogue_server_verified_completion` | S3-32 (done) — 대체 여부 미확인(§6) | — |

**이중 확인(태스크 status 대조가 아니라 main 코드 grep 교차):**

```bash
for s in distractor_link prerequisite_link misconception_slip_report recurrence_signal time_normalized_mastery \
         dialogue_server_verified_completion corpus_reverify_wiring problem_bank_coverage_ci_wiring; do
  git grep -l -- "$s" origin/main -- src tests scripts | wc -l; done        # 전건 0
git grep -n 'selected_choice_index' origin/main -- src tests               # 2파일 — 전부 dormancy_report(정본명 예약)·그 테스트뿐, 슬롯 실재 0
git show origin/main:src/mobile/lib/features/chat/application/chat_controller.dart | grep -cE 'select\(.*problemId'   # 0 (브랜치 1)
```

**왜 이 좌석들은 스스로 회수되지 않는가.** 좌석 태스크는 main에 todo/blocked로 살아 있지만 `backlog.py next`는
이들을 "이미 완료(미머지): 7n9n72"로 **제외**한다(HARN-11 필터). 즉 /drive가 영원히 집지 않고, 경고만 매번 뜬다.
회수는 사람이 `start <원본ID>`를 명시해야 시작되며(ADMIN-01 선례 `start_ignored_unmerged_done`), 그때 착수 세션이
읽는 것은 태스크 YAML 본문이다 — 본문에 브랜치 참조가 없으면 재구현한다(교수전략 카탈로그 4차 중복 직전 선례).

**조치 (재등재 아님 — ADMIN-08 "중복 좌석" 선례):** 8건 전부 `backlog.py amend <id> --acceptance "[고립 참조 2026-09-07 …]" --reason …`
으로 좌석 본문에 브랜치·커밋·파일·회수 방식(파일 단위·통째 머지 금지·삭제 금지)을 부착했다. HARN-34(#900)가
MISC-01/03에 notes 손편집으로 한 것과 같은 내용을 CLI 경유로 했으므로 정정 사유·이벤트가 대장에 남는다.
blocked 2건(ASM-06·MISC-02)에는 "unblock 후 대조 후보"로만 적었다 — ASM-06 브랜치 구현(087859bd)은 main 차단 사유의
'재정의 방향'(요청 슬롯 `selected_choice_index` 신설+마이그레이션)과 동형이고, MISC-02 브랜치 구현(43e5d6d8)은 차단
사유 ③(오라벨 우려)의 실물이라 무비판 이식을 금지했다.

**PED-15/16 — ID 충돌로 유실된 버그 수정 (재등재 2건):**

브랜치 `PED-15`(started_at 상시 NULL 근본수정·done·27faee2d)와 `PED-16`(Kiki 결정·todo)은 main이 같은 번호를 다른
태스크(`PED-15-growth-evidence-endpoint-client-wiring`·`PED-16-pedagogy-declared-unenforced-audit`)에 배정해
재등재 경로가 없었다(621b11f9 커밋 메시지가 "PED-15/16 ID 충돌 그랜드파더 등재"로 자인). HARN-35 유실 태스크
재등재(#900)에서도 빠졌고 HARN-37 acceptance ①이 "PED-15/16"을 잔여로 열거만 했다.

버그는 main에서 **살아 있다**:

```bash
git show origin/main:src/backend/whymath_backend/api/coach.py | sed -n '1012,1027p' | grep -c started_at   # 0 (ended_at만 대입)
git show origin/main:src/backend/whymath_backend/api/me.py    | sed -n '745,760p' | grep -c started_at   # 0 (duration_seconds·ended_at만)
git grep -c 'ProblemAttempt.started_at' origin/main -- src/backend/whymath_backend/harness/wh1_evaluation.py   # 8 (시간창 필터)
git grep -n '"started_at"' origin/main -- src/backend/whymath_backend/privacy/retention.py   # :80 (ProblemAttempt, "started_at") 파기 기준
git grep -l 'started_at' origin/main -- backlog/tasks   # ADMIN-02·HARN-32·OPS-47·PED-29 — 전부 무관, 추적 태스크 0
```

since/until을 지정한 R15·Brier·전이점수 호출은 상시 0행이고, **PII 보존기한 파기는 지금까지 0건**이다. 조치:

- **`PED-37-attempt-started-at-null-fix-recovery`** 신규 등재(`backlog.py add` 경유·priority **1**·EOS P1) — 보안·법령
  관련 고립분은 priority 1(stray-code 규칙). acceptance는 ①고립 실측 고정 ②파일 단위 이식·원 번호 재사용 금지·main
  writer 구조에 재적용 ③집행 지점(두 서빙 writer 통합 테스트 + 변별력 테스트 + retention 산출 assert) ④회귀 0(전체
  스위트)로 분리 기재. `--id PED-37`은 CLI가 충돌 없이 수락했다(가시성 고지: push 전까지 다른 세션에 안 보임).
- **`G-attempt-retention-purge-backfill-decision`** 게이트 신설(kind=decision·assignee=kiki·remind 14일) — 원 PED-16은
  kiki 소유 *태스크*였으나, 법령 유래 절차(PII 파기 소급 판단)는 기계 대체 금지이고 리마인드가 있는 게이트가 kiki
  소유 태스크보다 표면화가 확실하다(08-31 `G-authoring-expansion-merge-decision` 선례). 결정 3항(실 PII 축적 여부 ·
  NULL 행의 소급 파기 기준 · 스크립트 위임 여부)을 제목에 실었다.

### ③ 삭제 가능 — 3건 (7차 배치 2 + 수동 1)

| 브랜치 (head) | 흡수 근거 | 처분 |
|---|---|---|
| `drive-eos-81-sequential-wbhw8v` (9d5f81b2) | ahead 0·diff 0파일. EOS-81 main done(#980)·`backlog/events/claude_drive-eos-81-sequential-wbhw8v.ndjson` main 실재 | 7차 배치 |
| `review-dydkkx-runbook` (dbdcdf6f) | PR **#961 머지**(91c348fd). 머지 후 1커밋 "EOS-80 done"은 main EOS-80 done + `events/claude_eos80-done.ndjson`으로 승계. 브랜치 고유 53줄(21파일)을 전건 열람 — 전부 옛 상태(status·notes 후행 갱신 이전·`updated: 09-01`), 런북 §6 clear 명령은 main이 `--as kiki` 추가판으로 우세 | 7차 배치 |
| `gates/deploy-environment-approval` (907d4629) | PR **#967 닫힘·미머지**. 게이트 `G-deploy-environment-approval`은 main이 별도 경로(`events/claude_status-uh55gf.ndjson`)로 **상위 증거**(gh api 실측·환경 id·protection_rule id·baseline 변별력)와 함께 clear. 런북 §7-3 성공 판정은 main이 09-01 정정판("왜 워크플로 실행으로 판정하지 않는가")으로 브랜치 판정 기준을 명시 대체·§7-4 잔여 한계까지 추가. 브랜치 이벤트 파일 1줄은 같은 clear의 약한 중복 기록 — 손실 0 | 허용 패턴(`claude/*`) 밖 — **Kiki 수동 삭제** (`git push origin --delete gates/deploy-environment-approval`) |

`.github/branch-cleanup-request.txt`에 7차 배치(head SHA 스냅샷·근거·제외 목록 갱신·수동 삭제 명령)를 등재했다.

## 5. 별건 관찰 (이번 범위 밖·기록만)

- **HARN-11 제외 경고 20건**(`next` 상단)은 이 감사 대상과 정합한다 — 7n9n72 8건·k20m0w 3건·trjg5x 1건·e98dw4 1건·
  6eejrv 1건·zvknzk 2건(PR #1018)·k9r51v 2건(PR #1015)·7pytu8 2건(PR #1011). PR 소유 6건은 머지되면 사라지고,
  나머지는 §4-②·①의 좌석이 지킨다.
- claim 대장이 존재하지 않는 브랜치(`status-5kvqkv`)를 가리키는 상태(§1 ⓐ) — claim 회수(`claims reap`) 판단은
  하네스 소관.

## 6. 정직한 공백

- **claim 활성 3건은 판정하지 않았다**(④). f9lp65의 백업 스크립트 98줄이 main #993/#1009에 완전히 포섭되는지는
  줄 단위 대조를 하지 않았다 — "보인다"까지가 실측이다.
- **7n9n72 alembic `20260808_1200_7ef2b5a8e69e_dialogue_server_verified_completion.py`의 좌석은 확정하지 않았다.**
  S3-32(done) 회수가 "신규 리비전은 main HEAD 기준 down_revision"을 acceptance로 적었으므로 대체 리비전이 착지했을
  가능성이 높으나 main `alembic/versions`에 같은 이름은 없다(grep `server_verified` 0). S3-32 회수 세션의 대체
  리비전명을 확인해야 닫히는 공백이며, 이 브랜치가 삭제 금지 상태라 소실 위험은 없다.
- **추적 중 14건의 acceptance 전수 정독은 이번에도 하지 않았다**(08-31과 같은 공백). 소유 실재·생존·지목까지만
  기계 확인했다. 이번 7n9n72 사례가 보여주듯 좌석이 done이 되는 순간 이 공백은 고아를 만든다 — 다음 감사는 §4-②
  표의 소유 태스크 중 done으로 바뀐 것부터 본다.
- **코드 이식은 수행하지 않았다** — 이 감사의 범위가 아니다(`PED-37`·좌석 8건을 `/drive` 또는 명시 `start`가 실행한다).

## 7. 검증 (전건 exit code — `-q`/`tail` 절단 없음)

```bash
python3 scripts/harness/backlog.py validate
# ✔ 백로그 무결성 green — 태스크 562건, 게이트 36건, 트랙 3건 · EXIT=0

python3 scripts/harness/backlog.py next --n 3
# 1. PED-37-attempt-started-at-null-fix-recovery  (stage=S3 · priority=1)  ← 배선 확인: 등재 직후 최상위 후보
# 2. HARN-57 · 3. HARN-59 · EXIT=0  (전체 122건 — 감사 전 123건에서 EOS-89·EOS-99가 빠졌다: 다른 세션의 원격 claim으로 추정, 이 감사 범위 밖)

python3 scripts/harness/backlog.py overlap PED-37-attempt-started-at-null-fix-recovery --in-flight-only
# EXIT=0 · 경고 3건 — LIC-01(paths `src/backend/whymath_backend/**` 광범위 glob 포함) · NLP-05(`test_wh1_evaluation*.py` 프리픽스 포함만)
# · PB-13(`harness/**` 포함). 셋 다 *범위 포함*이지 같은 파일을 고치는 작업이 아니다 — PED-37이 만지는 것은 두 writer의
# started_at 대입과 시간창 테스트뿐. 등재 시 `add`의 전체 겹침 경고 51건도 전건 광범위 glob 포함·비활성 세션.

python3 scripts/harness/backlog.py gates list | grep G-attempt-retention
# G-attempt-retention-purge-backfill-decision [kiki/decision] … pending · EXIT=0
```

amend 8건은 각각 `EXIT=0`이었고, 각 태스크 YAML에 acceptance 1항 추가 + notes에 정정 사유가 기록됐다
(`git diff --stat backlog/tasks/` 8파일). `add`는 `--id PED-37`을 충돌 없이 수락했고 "push 전까지 다른 세션에
보이지 않는다"는 가시성 고지를 냈다 — 이 PR이 그 push다.
