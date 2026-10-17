# 미머지 브랜치 전수 감사 15회차 — 2026-10-03

> **판정 기준: main `381ec106`** (2026-10-03). 이 문서는 그 시점의 스냅샷이며 정본이 아니다.
> 실행 정본은 `backlog/`(회수 태스크)와 `.github/branch-cleanup-request.txt`(삭제 배치)다.
> 선행 판정 `unmerged_branch_audit_2026-10-02.md`(14회차)는 수정하지 않는다.
> 이 세션은 시작 시 shallow였고 `git fetch --unshallow origin` + `git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'`로 전제를 복구한 뒤에만 판정했다.

## 0. 계기와 요약

Kiki의 "떠돌이 코드 정리" 요청 → `/stray-code`. 14회차(10-02) 이후 하루 동안의 변화를 판정했다.

1. **13차 삭제 배치 집행 확인** — `hja5kh-eos129` · `hja5kh-s4-11` · `gk8vkz` 잔존 **0/3**(`git ls-remote` 실측).
2. **SEC-42 완료** — PR #1433이 `G-eos37-erasure-kpi-disposition`의 clear를 main으로 회수했다. 소유 사유가 소멸한 `tbj2jf`는 삭제 가능으로 내린다(§3-③).
3. **`34zvse`의 좌석이 전부 소멸** — CUR-07·HARN-80이 14회차 이후 `done`이 되어 살아 있는 소유 태스크가 0건이다. 잔여 diff를 재열거한 결과 **MEMORY.md 결정 로그 2건만** main에 없어 회수 태스크 **HARN-212**(priority 3)를 등재했다(§3-①).
4. **신규 브랜치 `dreamy-carson-7x90dj`** — 타 세션 claim 때문에 거부된 착수 시도의 이벤트 샤드 1개뿐이다. 삭제 가능.
5. 나머지 추적 중 14건은 head 불변 · 좌석 상실 0.

## 1. 전제 복구와 모집단 분리

```bash
git rev-parse --is-shallow-repository      # true였다 → 아래 두 줄 실행 후 false
git fetch --unshallow origin
git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'
git for-each-ref refs/remotes/origin       # HEAD 제외 44건 · git ls-remote --heads origin 44건과 일치
```

| 구분 | 건수 | 내역 |
|---|---|---|
| 원격 ref 전수 | 44 | 로컬 remote-tracking 44 = `ls-remote` 44 |
| 제외 — 판정 대상 아님 | 2 | `main` · `harness-claims` |
| 제외 — 열린 PR이 소유 | 19 | 열린 PR 19건(GitHub MCP `list_pull_requests`) |
| 제외 — 원격 claim 활성 · PR 없음 | 6 | `status-f6qz0c`(EOS-63) · `status-f9lp65`(HARN-56) · `practical-maxwell-kuwl7x`(OPS-104) · `blissful-lovelace-ubp9tw`(OPS-96) · `laughing-cerf-l9nqgq`(P3-19) · `friendly-pascal-mnmypk`(QUAL-11) |
| **감사 대상** | **17** | §2 |

산술: 44 − 2 − 19 − 6 = 17.

**유령 PR 0건** — 열린 PR 19건의 head 브랜치가 전부 원격에 실재한다(`git rev-parse --verify origin/<head>`로 19건 전수 확인, 실패 출력 0건).
claim 대장의 `friendly-pascal-mnmypk` 등 4개 claim은 `harness-claims`의 claim JSON `branch` 필드로 브랜치를 대조했다. 세션 브리핑이 나열한 claim 중 `status-38gu4d`(OPS-73) · `friendly-darwin-9fqq5z`(EOS-127) · `vigilant-brahmagupta-63qb9l`(EOS-27)은 이번 원격 ref 목록에 브랜치가 없다(미push) — 정보로만 기록하고 건드리지 않는다.

## 2. 3축 측정

```bash
B=origin/<브랜치>
git rev-list --left-right --count origin/main...$B                              # behind ahead
git diff --name-only origin/main...$B | wc -l                                   # 내용 diff
git diff --name-only origin/main...$B | grep -cE '^(src|tests|data|scripts)/'   # done-less 사각
```

| 브랜치 | behind | ahead | diff | 코드 | 고립 done | head | 14회차 대비 |
|---|---|---|---|---|---|---|---|
| `backend-audit-event-foundation-29ac1b` | 535 | 3 | 22 | 21 | 0 | `6507e018` | head 불변 |
| `dreamy-carson-7x90dj` | 18 | 1 | 1 | 0 | 0 | `3b45cd97` | **신규** |
| `intelligent-noether-tbj2jf` | 36 | 1 | 2 | 0 | 0 | `c671a313` | head 불변 · SEC-42 done |
| `openrouter-setup-guide-e98dw4` | 724 | 13 | 37 | 27 | 1 | `f8c0e3b6` | head 불변 |
| `remaining-track-34zvse` | 628 | 16 | 33 | 23 | 0 | `7fb78470` | head 불변 · **좌석 소멸** |
| `subject-problems-theory-check-7n9n72` | 637 | 34 | 83 | 49 | 10 | `621b11f9` | head 불변 |
| `whymath-ai-content-design-vafylb` | 660 | 8 | 7 | 1 | 0 | `b1218739` | head 불변 |
| `whymath-ai-recommendation-review-q8tvcx` | 702 | 3 | 11 | 2 | 1 | `e1835c0c` | head 불변 |
| `whymath-coding-architecture-iws58k` | 643 | 1 | 16 | 1 | 0 | `a8e01be2` | head 불변 |
| `whymath-constitution-rules-check-azdnov` | 637 | 1 | 5 | 0 | 0 | `c335a787` | head 불변 |
| `whymath-curriculum-design-6eejrv` | 601 | 9 | 6 | 3 | 1 | `2f428729` | head 불변 |
| `whymath-data-platform-design-t608mk` | 633 | 1 | 7 | 0 | 0 | `d876b523` | head 불변 |
| `whymath-issues-review-k20m0w` | 649 | 45 | 133 | 95 | 12 | `2330a095` | head 불변 |
| `whymath-mvp-plan-architecture-trjg5x` | 690 | 81 | 233 | 188 | 34 | `c8abbc17` | head 불변 |
| `whymath-pedagogy-review-gdmwhk` | 637 | 1 | 31 | 21 | 0 | `2915bf4e` | head 불변 |
| `whymath-pedagogy-review-uqyg79` | 718 | 38 | 76 | 51 | 9 | `5dc040b3` | head 불변 |
| `whymath-service-operations-review-5t5lmv` | 633 | 6 | 33 | 17 | 2 | `dd3e9475` | head 불변 |

(`34zvse`의 고립 done이 14회차의 1에서 0으로 줄어든 것은 CUR-07이 main에서 `done`이 되어 대조식 `main != done`이 더는 참이 아니기 때문이다.)

## 3. 4분류 판정

| 분류 | 건수 | 내역 |
|---|---|---|
| ① 회수 필요 | **1** | `34zvse` 잔여(MEMORY 결정 로그 2건) → **HARN-212** |
| ② 추적 중 | **14** | 14회차 15건에서 `tbj2jf`(③으로)·`34zvse`(①로) 이동분 반영 |
| ③ 삭제 가능 | **2** | `tbj2jf` · `dreamy-carson-7x90dj` |
| ④ 제외 | 27 | PR 소유 19 · claim 활성 6 · 판정 대상 아님 2 |

합계 1 + 14 + 2 = 17(감사 대상).

### ① 회수 필요 — `claude/remaining-track-34zvse` (head `7fb78470`)

14회차는 좌석을 CUR-07·HARN-80(in_progress)으로 적었으나 둘 다 지금은 `done`이다. 같은 브랜치의 CUR-04·05·08도 `done`이라 **이 브랜치를 소유하는 살아 있는 태스크가 0건**이 되었다. 스킬 §4에 따라 소유 태스크가 `done`이어도 잔여 diff를 재열거했다.

**방법**: 브랜치가 추가한 줄(`git diff -U0 origin/main...$B`의 `+` 줄) 하나하나를 main의 같은 경로 파일에서 `grep -qxF`로 찾아 부재 개수를 셌다(32개 파일, 공백 줄 제외).

| 구분 | 파일 | 결과 |
|---|---|---|
| main에 전량 존재(부재 0) | 코퍼스 JSON·provenance·`docs/data/achievement_criteria_v1.md`·`licensing_safety.md`·`criteria_loader.py`(376줄)·`achievement_level_unit.py`·`models/__init__.py`·`models/achievement_standard.py`·`schema/standard.py`·모바일 화면·테스트 4종·ORM 테스트 2종·적분 테스트 | 흡수 완료 |
| 부재 줄이 있으나 main이 대체 | `coach.py`(17) · `target_progress.py`(24) · `test_coach_grade_standard_code.py`(6) · `test_target_progress.py`(5) · `test_me_target_progress.py`(2) | main이 CUR-04(#810)로 같은 원자 축 조인을 이미 구현했다. main `coach.py:1830` `_standard_code_for`가 `Concept.code == AtomNode.code → AtomNode.standard_codes`를 쓰고 두 개의 조인 미스 경고도 같은 문구로 갖는다. `target_progress.py`도 같은 축으로 정렬돼 있다 |
| 부재 줄이 있으나 main이 대체 | `alembic/…fcfdfc277348…py`(2) · `schema_version.py`(1) | main에 같은 리비전 `fcfdfc277348`이 있고 `schema_version.py:127`이 등재했다. 차이는 docstring·주석 |
| 부재 줄이 있으나 소멸 | `ci.yml`(4) · `test_ci_enforcement_declaration_contract.py`(23) | 브랜치가 쓴 `pending-task:ARCH-23-qa-gate-enforcement` 선언은 main이 `ARCH-23`으로 `continue-on-error`를 제거해(`ci.yml:324~325`) 소멸했다. 그 선언을 단언하던 테스트도 함께 소멸 |
| 태스크 YAML 5건(CUR-04·05·07·OPS-29·MATH-05) | 부재 2~5줄 | 전부 main에서 `done`이고 main이 증적(#810 등)을 더 가진다 — 기록 정합 |
| **MEMORY.md** | 추가 48줄 중 **48줄 전부 부재** | `### 2026-08-11 (구현·MATH-05)`(브랜치 340행)·`### 2026-08-11 (구현·CUR-07)`(351행) 두 절이 main에 없다. main `MEMORY.md`의 MATH-05·CUR-07 언급은 모두 다른 맥락(통합 점검·CUR-08 회수 로그)이다 |

**결론**: 코드·코퍼스·테스트는 다 흡수됐거나 main이 대체했다. 브랜치에만 남은 것은 **결정 로그 2건**(MATH-05의 `plainLatex` 착시 근본 원인 추정·변별력 양방향 실측, CUR-07 스키마 확장 트레이드오프)이며 이것은 코드가 아니라 기록이라 main에서 재구성할 수 없다. 후속 소유자를 지목할 수 없으므로 삭제 후보로 내리지 않고 **HARN-212**(priority 3 · EOS P3)를 등재했다. 서빙 경로가 없는 문서 회수라 acceptance ③은 "main MEMORY.md에 두 절의 제목 줄이 실재하는지 grep"으로 판정한다. HARN-212가 done이 되면 `34zvse`는 다음 삭제 배치에 오른다.

### ② 추적 중 14건 — 좌석 상실 0

head 불변 14/14(14회차 기록값·09-28 문서 기록값과 대조). 좌석 태스크 status는 main 기준으로 전수 조회했다.

| 브랜치 | 살아 있는 좌석 (2026-10-03 실측 · 전부 `todo`) |
|---|---|
| `7n9n72` | MISC-01/03/05/06 · PB-02 · PB-14 · PED-14 · S3-33/34 · OPS-41 · HARN-79 — **삭제 절대 금지** |
| `trjg5x` | ADMIN-02 · PATH-03 · PB-14 |
| `k20m0w` | SEC-19 · SEC-30 · MGMT-03 · HARN-25 · PB-14 (MOB-18·MOB-11·MOB-23은 done) |
| `gdmwhk` / `uqyg79` | PED-26 (+ gdmwhk HARN-31) |
| `5t5lmv` | OPS-40 |
| `iws58k` | ARCH-30 |
| `t608mk` / `azdnov` | OPS-41 |
| `6eejrv` | PB-08 |
| `e98dw4` | VIZ-11 |
| `q8tvcx` | OPS-38 · OPS-67 · OPS-41 |
| `vafylb` | OPS-53(실제 회수 좌석 — 세션 브리핑의 "이미 포팅됨"은 오분류, HARN-190) |
| `29ac1b` | ADMIN-10 ⑦ — `docs/architecture/90_audit_log.md`가 main 부재 |

### ③ 삭제 가능 2건 — 근거

1. **`intelligent-noether-tbj2jf`** (head `c671a313`): 이 브랜치의 유일한 커밋은 `G-eos37-erasure-kpi-disposition`을 `pending → cleared`로 바꾸는 `backlog/gates.yaml` 6줄과 이벤트 샤드 1줄이다. 회수 태스크 **SEC-42가 PR #1433(`2de73590`)으로 done**이다. main `backlog/gates.yaml`의 같은 게이트는 `status: cleared`이고 `evidence`(1,478자)가 브랜치의 `evidence` 원문(1,160자)을 **그대로 부분 문자열로 포함**한다(파이썬 `in` 실측 True · SEC-42 이식 재확인 절이 덧붙은 형태). `evidence` 외의 필드(status·kind·assignee·requested·remind_after_days·notes·corrections·no_inputs_reason)와 `cleared_by`는 양쪽이 같다 — 이식본이 더 풍부할 뿐 브랜치에만 있는 내용이 없다. 이벤트 샤드 1줄은 같은 `gate_clear` 증적 문자열이며 main이 SEC-42 경로로 자기 이벤트를 남겼다. 이 판정은 SEC-40(PR #1439, main `381ec106`)이 이미 착지해 해금이 실제로 작동했음으로도 교차 확인된다.
2. **`dreamy-carson-7x90dj`** (head `3b45cd97`): 커밋 1개 · 파일 1개(`backlog/events/claude_dreamy-carson-7x90dj.ndjson` 25줄). 25줄 전부 `policy_warn`/`path_overlap`이며 대상 태스크는 `QUAL-11`이다. QUAL-11은 원격 claim 대장에서 **다른 브랜치 `friendly-pascal-mnmypk`**가 잡고 있고(claim JSON `branch` 필드 실측) 이 세션은 "타 세션 claim 중"이라며 착수를 거부당했다. 코드·문서·태스크 변경 0건 — 잃을 내용 없음. 이 브랜치가 claim 대장에 없음도 확인했다.

### ④ 제외

- PR 소유 19건 · 원격 claim 활성(PR 없음) 6건 · 판정 대상 아님 2건(`main`·`harness-claims`).
- `blissful-lovelace-ubp9tw`(OPS-96)는 14회차에는 원격에 없던 브랜치이며 이번에 push되어 나타났다 — claim JSON이 이 브랜치를 가리키므로 제외한다.

## 4. 정직한 공백

- **`34zvse` 줄 단위 대조의 한계**: `grep -qxF`는 줄 전체가 같아야 일치하므로 서식·주석만 달라진 줄도 "부재"로 센다. 부재 줄이 있는 5개 코드·테스트 파일 중 `coach.py`·`target_progress.py`·`ci.yml`·alembic·`test_ci_enforcement_declaration_contract.py`는 부재 줄을 열어 읽고 main 대체를 확인했다. **`test_coach_grade_standard_code.py`(6)·`test_target_progress.py`(5)·`test_me_target_progress.py`(2)의 부재 줄은 열어 읽지 않았다** — 같은 CUR-04 변경의 테스트라는 추정이다.
- **`34zvse` MEMORY 2절의 원문은 이 문서에 복사하지 않았다**(48줄) — 이식은 HARN-212가 한다. 그때까지 원본은 브랜치 head `7fb78470`에만 있다.
- ② 추적 중 14건은 head 불변과 좌석 `status`만 재확인했다. 좌석 acceptance 본문 재정독은 하지 않았고 13·14회차 정독 결과를 승계했다.
- `tbj2jf` 삭제 판정에서 이벤트 샤드 1줄은 main에 같은 파일이 없고(`origin/main:backlog/events/claude_intelligent-noether-tbj2jf.ndjson` 부재 실측) main이 SEC-42 경로로 남긴 자기 `gate_clear` 이벤트와 줄 단위 대조하지 않았다. 샤드 줄의 `evidence`는 위 게이트 `evidence`와 같은 문자열이라 내용 손실은 없다고 판단했으나, 샤드 원문 자체는 head `c671a313`으로만 복구된다.
- 세션 브리핑이 "claim 활성"으로 나열한 `status-38gu4d`·`friendly-darwin-9fqq5z`·`vigilant-brahmagupta-63qb9l`은 원격 브랜치가 없어 감사할 수 없다.
- 14회차가 기록한 원격 번호 예약 `SEC-99`(탐색용 `add`의 부산물)는 이 세션에서 해제하지 않았다.
