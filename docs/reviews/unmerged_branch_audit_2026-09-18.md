# 미머지 브랜치 전수 감사 12회차 — 2026-09-18

> **판정 기준: main `86733521`** (2026-09-18T08:17:43Z · "PR — User Creation → Diagnosis → …
> Week 1 Gate 판정" `#1194`). 이 세션은 시작 시 shallow(`rev-list --count` 44)였고
> `git fetch --unshallow origin` + `git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'`
> 로 전제를 복구한 뒤에만 판정했다(복구 후 1,167커밋). 이 문서는 그 시점의 스냅샷이며,
> 선행 판정 문서(11회차 `_2026-09-12.md`)는 수정하지 않는다.

## 0. 계기

Kiki의 `/stray-code` 호출. 11회차(2026-09-12) 이후 6일간의 변화 — 특히 그날 일괄 종료된
**"8월 PR 10건"의 처분이 브랜치 소유권을 어떻게 바꿨는지**가 이번 회차의 실질 내용이다.

## 1. 전제 복구와 모집단 분리

```bash
git rev-parse --is-shallow-repository          # true → 아래 두 줄 실행 후 false
git fetch --unshallow origin
git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'
git for-each-ref --format='%(refname:short)' refs/remotes/origin | wc -l   # 42
```

| 구분 | 건수 | 내역 |
|---|---|---|
| 원격 ref 전수 | 42 | |
| 제외 — 판정 대상 아님 | 3 | `main` · `harness-claims`(하네스 소유) · `gh-readonly-queue/main/pr-1195-86733521…`(머지 큐 임시 ref) |
| 제외 — 열린 PR이 소유 | 14 | #1197 #1196 #1195 #1183 #1174 #1145 #1076 #1061 #1007 #975 #865 #858 #856 #844 |
| 제외 — 원격 claim 활성(타 세션) | 3 | `status-f6qz0c`(ahead 0·diff 0) · `status-f9lp65`(ahead 2·diff 5) · `test-driven-development-03elxp`(ahead 0·diff 0) |
| **감사 대상** | **22** | 아래 §4 |

**유령 PR 0건** — 열린 PR 14건의 head 브랜치가 전부 원격에 실재한다(역방향 확인).

**claim 대장 이상 2건(판정 아님·보고)** — `origin/harness-claims:claims/`의 활성 claim 8건 중
2건이 **존재하지 않는 브랜치**를 가리킨다: `OPS-73` → `claude/status-38gu4d`,
`SEC-35` → `claude/exciting-allen-5dkjb0`. 둘 다 `git ls-remote --heads` 0건이다.
claim 활성 3건(위 표)은 그와 별개로 실재한다. 나머지 3건(`ASM-10`·`HARN-82`·`MGMT-06`)은
열린 PR 브랜치와 겹쳐 PR 소유로 계상했다.

## 2. 이번 회차의 실질 — 8월 PR 일괄 종료가 만든 신규 고립 5건

9회차(`_2026-09-08.md` §3.3)가 "다음 회차 최우선 관찰 대상"으로 지목한 8월 PR 10건 중
**6건이 2026-09-12에 닫혔다**(미머지). 닫힌 순간 그 head 브랜치들은 "PR 소유"에서
**감사 대상**으로 내려온다 — 11회차가 그중 1건(`ops-50-51-52-moe-rocm-followup`)만
10차 배치로 처리했으므로, 나머지 5건이 이번 회차에 처음 판정된다.

각 PR의 **닫기 사유가 곧 처분**이므로 close 코멘트를 1차 자료로 읽었다.

| PR | 브랜치 | 닫기 사유(요지) | 판정 |
|---|---|---|---|
| #882 | `backend-eos-204-education-event-phase1` | **설계 거부** — ADR-001(2026-08-02 채택)의 "범용 Event Bus 미도입"과 정면 충돌. `E204-*` 태스크 ID는 main에 등록된 적 없음 | ③ 삭제 |
| #880 | `claude/backend-audit-event-foundation-29ac1b` | 재작업 없음 — `ADMIN-10`은 대장에 남고(todo·P2·2027 이월), 겹침(SEC-29·ADMIN-01)을 notes에 정정 기록 | **② 추적 중** (아래 §3) |
| #847 | `claude/ops-02-offsite-backup-move` | 방식 자체가 `OPS-31`(PR #968, age 암호화+클라우드 동기화)로 대체. 게이트 `G-backup-offsite-move`는 2026-09-06/07 실측 클리어 | ③ 삭제 |
| #893 | `claude/backend-misc-12-16-misconception-review-impl` | 대체 PR **#1144로 회수 후 머지**(merged:true, 2026-09-12T05:16Z 실측) | ③ 삭제 |
| #846 | `s1-17-phase-b-math-extension` | 실작업이 `S1-16`(PR #941, done)으로 이미 흡수 — 중복 | ③ 삭제 |

> **집행 확인**: #880의 close 코멘트가 약속한 "ADMIN-10 notes 정정 기록"은 실제로 착지했다 —
> main `backlog/tasks/ADMIN-10-audit-event-foundation.yaml`에 `[정정 2026-09-12]`가 있고
> acceptance ⑥으로 겹침 축이 분리 기재돼 있다. **약속이 문서에 도달했는지까지 확인한 것**이
> 이 표에서 #880만 ②로 갈린 이유는 아니다(그것은 §3의 실측 때문이다).

## 3. #880만 삭제 후보에서 뺀 이유 — 좌석은 있는데 *산출물의 고립*이 대장에 없었다

`ADMIN-10` acceptance ①은 문자 그대로 **`docs/architecture/90_audit_log.md` 설계 문서 작성**이다.
그 파일은 main에 **없고**, 원 브랜치 `claude/backend-audit-event-foundation-29ac1b`
(head `6507e018`)에 **246줄 완성본으로 실재한다**(헤더: "설계 확정 (2026-08-25)").

```bash
git cat-file -e origin/main:docs/architecture/90_audit_log.md   # → 부재
git show origin/claude/backend-audit-event-foundation-29ac1b:docs/architecture/90_audit_log.md | wc -l   # 246
git ls-tree -r --name-only origin/main docs/architecture/ | grep -iE 'audit'   # 0건 — main에 대체 문서 없음
```

main 부재 파일은 총 6건이며 나머지 5건도 acceptance ②의 재료다(`audit_event` alembic 마이그레이션 ·
`audit/{__init__,event_bus,llm}.py` · `tests/backend/audit/test_event_bus.py`).

즉 **좌석(ADMIN-10)은 실재하고 acceptance가 그 산출물을 다루지만, "그 산출물이 이미 브랜치에
있다"는 사실은 어디에도 적혀 있지 않았다.** 이 상태로 브랜치를 지우면 246줄 설계가
notes의 3줄 요약으로 축소되고 재착수 세션은 백지에서 다시 쓴다 — 스킬 §4가 경고하는
"소유 태스크가 done이어도 잔여 diff가 남는다"의 *todo 판본*이다.

→ **조치**: `backlog.py amend ADMIN-10 --acceptance`로 **⑦-고립참조**를 부착했다(브랜치·head
SHA·재현 명령·파일 6건 열거 + "이 태스크 done 전 삭제 금지" + "통째 머지 금지, 파일 단위 이식").
브랜치는 삭제 배치에서 **의도적으로 제외**한다.

## 4. 4분류 판정

| 분류 | 건수 | 내역 |
|---|---|---|
| ① **회수 필요(미추적 고립)** | **1** | `claude/relaxed-fermat-8dui3u` → **`MP-06` 신규 등재** |
| ② 추적 중 | **15** | 기존 14(7n9n72 · trjg5x · k20m0w · gdmwhk · uqyg79 · 34zvse · 5t5lmv · iws58k · t608mk · azdnov · 6eejrv · e98dw4 · q8tvcx · vafylb) + **신규 29ac1b**(ADMIN-10 ⑦ 부착) |
| ③ 삭제 가능 | **6** | `claude/*` 4건(11차 배치) + 패턴 밖 2건(Kiki 수동) |
| ④ 제외 | 20 | PR 소유 14 · claim 활성 3 · 판정 대상 아님 3 |

합계 1+15+6 = 22(감사 대상) · 20(제외) = 42.

### ① 회수 필요 — `claude/relaxed-fermat-8dui3u` (head `03e45689`)

**미추적 실측**: main 전체에서 이 브랜치 접미사 언급이 **0건**이다(감사 대상 22건 중 유일).

```bash
git grep -l relaxed-fermat-8dui3u origin/main -- backlog docs   # 0건
```

**내용**: `MP-02` 실행 런북의 사이드카 경로 계산 버그 정정 + 저작 프롬프트 경고 강화.
런북은 `<out>` + `".rounds.jsonl"` **이어붙이기**로 짰으나 실제 코드
(`anchor_round_ledger.py`·`problem_corpus_accumulate.py`)는 `Path.with_suffix()`로 마지막
확장자를 **교체**한다. 그래서 §3의 stale-file 검사가 실제 사이드카를 **한 번도 찾지 못했고
재실행을 막지 못해 같은 회차가 의도치 않게 2번 기록**됐다(2026-09-10 Kiki 실행 로그.
둘 다 `accepted=0`이라 코퍼스 오염은 없었다).

**main 미흡수 교차 확인**(태스크 status 대조가 아니라 코드 grep):

```bash
git show origin/main:docs/reviews/mp02_first_llm_authoring_run_runbook.md | grep -c with_suffix   # 0
git show origin/main:docs/reviews/mp02_first_llm_authoring_run_runbook.md \
  | grep -nE '\$Out\.rounds\.jsonl|str\(out\)\+'                                                   # 155·192·233행 = 버그 잔존
git show origin/main:docs/prompts/l3_equivalent_gen.md | grep -c '가장 흔한 실패 원인'            # 0
```

`MP-02`의 claim이 걸린 `claude/test-driven-development-03elxp`도 이 정정을 담고 있지 **않다**
(ahead 151·diff **0파일** — 내용이 0건인 claim 전용 브랜치). 즉 어느 소유자도 없다.

→ **`MP-06-mp02-runbook-sidecar-path-fix-recovery`** 등재(P1·priority 2·`backlog.py add` 경유).
acceptance에 ①고립 실측 고정 ②파일 단위 이식(2파일·통째 머지 금지) ③**집행 지점**(정정된
검사가 사이드카 유/무 두 방향에서 실제로 변별력을 내는지) ④원 번호 재사용 금지
⑤사고 경위 이전을 분리 기재했고, notes에 "회수 완료 전 원 브랜치 삭제 금지"를 명시했다.

**긴급성**: `MP-02`는 Kiki 머신 실행 대기(사람 게이트)다. 정정이 착지하기 전에 다음 회차를
돌리면 재실행 차단이 또 발화하지 못한다.

### ② 추적 중 15건 — 좌석 상실 0

기존 14건은 각 브랜치 접미사를 참조하는 main 태스크의 status를 전수 조회해
**미완료(todo/blocked/in_progress) 좌석이 최소 1건씩 살아 있음**을 재확인했다.

| 브랜치 | 살아 있는 좌석 |
|---|---|
| `7n9n72` | MISC-01/03/05/06 · PB-02 · PED-14 · S3-33/34(todo) · ASM-06 · MISC-02(blocked) — **삭제 절대 금지** |
| `trjg5x` | PB-13(in_progress) · ADMIN-02 · PATH-03 · PB-14 |
| `k20m0w` | MOB-18(in_progress) · MOB-11 · SEC-19 · SEC-30 외 |
| `gdmwhk` / `uqyg79` | PED-26 |
| `34zvse` | CUR-07 · HARN-80 |
| `5t5lmv` | OPS-40 |
| `iws58k` | ARCH-30 |
| `t608mk` / `azdnov` | OPS-41 |
| `6eejrv` | PB-08 |
| `e98dw4` | VIZ-11 |
| `q8tvcx` | OPS-38 · OPS-67 · OPS-41 |
| `vafylb` | OPS-53 · OPS-41 · KG-02(blocked) · NLP-05(review) |
| **`29ac1b`(신규)** | **ADMIN-10 ⑦(이번 회차 부착)** |

### ③ 삭제 가능 6건 — 근거

각 건은 *태스크 status 대조가 아니라* **파일 단위 내용 대조**로 판정했다:
main 부재 파일 유무 + 브랜치 고유 줄(`comm -23` 정렬 집합 차)의 내용 확인.

```bash
B=origin/<브랜치>
for f in $(git diff --name-only origin/main...$B); do
  git cat-file -e origin/main:"$f" 2>/dev/null \
    && echo "$f $(comm -23 <(git show $B:"$f"|sort -u) <(git show origin/main:"$f"|sort -u)|wc -l)" \
    || echo "$f ★main부재"; done
```

**(a) `claude/backend-misc-12-16-misconception-review-impl` = `bce7a6be`**
main 부재 **0**. 고유 줄 전건이 옛 판이다 — `MISC-12.yaml`은 브랜치 `todo` vs main
**`cancelled`**(#1144가 설계 충돌을 근거로 취소), `concept.schema.yaml`의 고유 줄은
#1144가 **의도적으로 되돌린** `misconception_codes` 완전 제거분,
`test_neo4j_runtime_ban.py`의 고유 줄은 ruff가 지적해 #1144가 제거한 `import sys` 1줄.
회수는 PR **#1144(merged)** 가 수행했다.

**(b) `claude/ops-02-offsite-backup-move` = `fab70f96`**
main 부재 2(`scripts/backup/move_backup_to_nas.ps1`·그 테스트) — 둘 다 **채택되지 않은 방식**이다.
main의 `db_backup_dr_runbook.md`는 `OPS-31` age 암호화 판으로 전면 개정돼 §1b(키쌍 생성)·
§2(로그온 비의존 스케줄)·§2-2(누락 감시)를 갖췄고, 브랜치의 §7(NAS 이동)·§7-2(7-Zip AES)는
그 상위 설계로 대체됐다. `problem.py` 고유 줄 26은 스택 조상 #846에서 온 것으로 (f)와 동일 사유.

**(c) `claude/clever-bell-8lh19k` = `98c25456`**
main 부재 0. 고유 줄은 `ARCH-49` yaml의 **4줄뿐**이며 전부 옛 상태다 —
`status: in_progress`(main=**done**) · `session: <이 브랜치>`(main=null) · `artifacts: []`(main=증적 있음) ·
짧은 옛 `notes`. 이 브랜치가 만든 acceptance ⑥~⑩(OpenRouter 실측·관할 축 설계)은
**main에 그대로 실재한다**(`grep 'OpenRouter 경유 실측 확정' origin/main` 적중). claim도 2026-09-17
07:37Z에 release 됐다.

**(d) `claude/laughing-faraday-opgsjg` = `46bf374c`**
main 부재 0. `SKB-02`는 main **done**(브랜치는 `in_progress`), `SKB-01` notes는 main이
3,835자로 브랜치 1,235자를 **포함·초과**하며 브랜치가 남긴 2026-09-11 발견
(`atom_graph_v1/graph.json`에 `behavior_skills` 부재 → SKB-02 분리)이 main에
`[정정 2026-09-11 후속]`으로 더 자세히(PR #1127·크로스워크 437행 실측까지) 남아 있다.

**(e) `backend-eos-204-education-event-phase1` = `2ab82c24`** — ⚠ `claude/*` 패턴 밖
main 부재 13(이벤트 SDK·taxonomy·registry·xAPI/Caliper/CloudEvents 어댑터·설계 문서·
`E204-01/02` 태스크). **내용이 없어서가 아니라 설계가 거부돼서** 삭제 후보다 —
PR #882 close 코멘트가 ADR-001 충돌을 1차 근거로 명시하고 "재필요 시 재검토 조건을
실측으로 채운 뒤 **새 ADR과 함께 재제안**"을 처분으로 적었다. 복구 경로는 닫힌 PR #882의
diff와 아래 SHA다.

**(f) `s1-17-phase-b-math-extension` = `f9749daf`** — ⚠ `claude/*` 패턴 밖
main 부재 0. 고유 줄은 `problem.py` 26줄뿐이고, 그 내용(`schema_version` + `extensions.math` 분리)은
`S1-16`이 **PR #941로 done** 처리하며 main에 착지했다.
부수 정리 필요: `HARN-49` notes가 아직 *"S1-16의 구현 자체는 미머지 PR #846(브랜치
s1-17-phase-b-math-extension)에 실재한다 — 회수는 저비용"* 이라고 적고 있다. 이 문장은
#941 착지로 **사실이 아니게 됐다**(HARN-49 자체는 track_gate 설계 공백 태스크라 별건).

## 5. 조치

1. **회수 태스크 1건 등재** — `MP-06-mp02-runbook-sidecar-path-fix-recovery`(`backlog.py add` 경유,
   번호 손배정 없음).
2. **고립 참조 부착 1건** — `ADMIN-10` acceptance ⑦(+ 회차 오기 정정 ⑧).
3. **11차 삭제 배치 등재** — `.github/branch-cleanup-request.txt`에 `claude/*` 4건.
   패턴 밖 2건은 Kiki 수동 삭제 대상으로 같은 파일에 주석 기재.
4. **직전 배치 집행 확인** — 7~10차 + 수동 삭제분 표본 10건 전건 `ls-remote` **잔존 0/10**.

## 6. 정직한 공백

- **② 추적 중 15건의 *잔여 diff 전수 대조*는 하지 않았다.** 이번 회차가 확인한 것은
  "좌석이 살아 있는가"(전수 status 조회)까지이며, 각 브랜치의 파일별 잔여분이 좌석의
  acceptance 범위에 **빠짐없이** 들어가는지는 재검증하지 않았다. 그 대조는 8~10회차가
  수행한 범위를 승계한다. 이번 회차가 새로 연 축은 §3 한 건(29ac1b)이다.
- **`claude/*` 패턴 밖 2건은 이 세션이 삭제할 수 없다.** `branch-cleanup.yml`의 허용 패턴이
  `claude/*`·`tmp-*`·`worktree-agent-*`뿐이라 `backend-eos-204-…`·`s1-17-…`는 Kiki 수동
  집행 대상이다(누적 6건째 유형).
- **`in_progress`인데 세션 브랜치가 사라진 태스크 2건**(판정 아님·관측):
  `MOB-18`(`claude/whymath-system-review-n75r24`) · `SKB-04`(`claude/quirky-cori-x91nld`).
  둘 다 `ls-remote` 0건이나, 각 세션의 작업은 **머지됐다**(`#1031` · `#1172`/`#1173` 실측) —
  코드 소실이 아니라 **완료 표기 누락**이다. 떠돌이 *브랜치*가 아니라 떠돌이 *좌석*이라
  이 스킬의 4분류에 들어가지 않으므로 태스크로 등재하지 않고 관측만 남긴다
  (축 소유자 후보 = `HARN-80` 직접 착지 done 경로).
- **claim 대장 이상 2건**(§1) 역시 판정하지 않았다 — 하네스 소유 대장이고 타 세션 자산이다.
- **`HARN-49` notes의 사실 오류**(§4-(f))는 이 감사가 발견했으나 정정하지 않았다.
  그 태스크의 소유가 아닌 세션이 notes를 고치면 판정 맥락이 섞인다 — 삭제 배치 주석에
  근거를 남겨 다음 착수 세션이 판단하게 한다.
- **감사 중 main이 전진했다**(`86733521` → `4643a314`, PR #1195 머지). 판정 기준은 위 헤더대로
  `86733521`이며, 전진 후 §4-③의 삭제 후보 6건 + §4-①의 회수 대상 1건을 `4643a314` 기준으로
  **재실측해 판정이 그대로임을 확인**했다(main 부재 파일·고유 줄 수 전건 동일). 다만 §4-②의
  좌석 전수 조회와 §1의 모집단 표(42 ref)는 `86733521` 시점 값이다 — 그 사이
  `claude/inspiring-turing-cq44ly`가 PR #1195 머지와 함께 삭제돼 "열린 PR 소유 14"는
  지금 13이다. 이 문서는 스냅샷이므로 수치를 소급 갱신하지 않는다.
