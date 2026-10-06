> **[OPS-41 회수 2026-10-05 — 이식 주석]** 고립 브랜치 `azdnov`(판정 기준 `c335a787`)에서 회수. 본문의 `HARN-22`(이중 배정 조회 계기판·재채번 판정 권한 승계 좌석)는 main의 동번호 별건과 충돌해 **`HARN-213`으로 재발급**됐다. 본문 판정은 수정하지 않았다.

# 태스크 ID 재채번 — Kiki 판정서 (2026-08-11)

> **범위**: `HARN-15` acceptance ④가 Kiki 전권으로 유보한 **재채번 실행 판정**. 대상은 ①구(舊) 3중 충돌 `S3-26/27/28` ②착지대 브랜치 `claude/s3-25-bucket-c-renumber-fix` 처분 ③2026-08-11 실측으로 새로 드러난 live 이중 배정 16건과 조회 계기판 부재.
> **성격**: 판정서(사람 결정 기록). 실측 조사 → 3안 제시 → Kiki 판정 → 집행·등재. 이 문서가 그 판정의 정본이며, 이후 세션은 여기를 인용한다.
> **판정 3줄**:
> 1. **S3-26/27/28 재채번 = 불실행 확정.** 충돌 상대가 이미 소멸해 개명 실익이 0인 반면 축약 참조 90곳+ 파손 비용만 남는다. `S3-32/33/34` 우회를 정식 처분으로 추인한다.
> 2. **착지대 브랜치 = SHA만 보존하고 폐기 확정.** `05a1a344`를 기록에 남겨 참조 가능성만 지키고, 브랜치는 재생성하지 않는다.
> 3. **판정 권한은 `HARN-22`로 승계.** 유보가 산문에만 남아 고아가 된 상태를 열린 태스크로 옮기고, 충돌 조회 계기판을 그 태스크가 소유한다.

관련 정본: `backlog/tasks/HARN-15-id-collision-cross-branch-scan.yaml`(done·acceptance ④ 원문) · `backlog/tasks/HARN-22-id-collision-inventory-and-renumber-authority.yaml`(신규·승계 좌석) · `scripts/harness/store.py`(`_GRANDFATHERED_ID_NUMBERS`) · `docs/reviews/unmerged_branch_triage_2026-08-04.md` §4 · `docs/reviews/harness_constitution_rules_integrated_audit_2026-08-10.md` §7-1 · `MEMORY.md` 2026-08-11 (판정·거버넌스) 항목

---

## §0. 판정 방법과 한계

- 실측 기준 `origin/main` = `959ec4ad`(2026-08-11 fetch). 원격 38브랜치 전수 스캔(`git ls-remote`·`git ls-tree <ref>:backlog/tasks`)으로 충돌 생사를 개별 확인했다.
- **한계**: ①이미 삭제된 브랜치의 스냅샷은 이 컨테이너의 낡은 remote-tracking ref로만 읽었다(원격에는 없음) ②2026-08-04 문서가 센 13건 중 2건(`S3-16`·`S4-18(b)`)은 상대 브랜치 소실로 **원문 주장 자체를 재현하지 못했다** — "충돌 없음"이 아니라 "검증 불능"으로 기록한다 ③이 판정은 번호 참조 정합만 다루며, 각 브랜치의 **내용 처분**(미머지 12건 triage)은 범위 밖이다.

## §1. 판정 A — 구 3중 충돌 `S3-26/27/28`: **재채번 불실행 확정 (moot 추인)**

### 사실

| 항목 | 실측 |
|---|---|
| 충돌 구조 | 번호 3개가 각각 2벌 — main(`concept-supply-integrity`·`problem-type-tagging`·`canonicalize-answer-kind-scope-audit`) ↔ 섀도 계보(`learning-loop-closure`·`completion-in-solution-process`·`conversation-answer-detection`) |
| 발생 경위 | 섀도 브랜치 버킷 C(원 S3-09~15)를 1차로 S3-26~31에 재채번한 브랜치가 미머지로 방치되는 동안, main이 같은 번호를 무관한 작업에 독립 배정 |
| 상대측 현존 | ❌ 상대 YAML은 **삭제된 브랜치에만** 존재 — main `backlog/tasks/`에 등재된 적 없음 |
| 우회 상태 | main이 `S3-32`·`S3-33`·`S3-34`를 `backlog.py add` 경유 신규 등재(전부 `todo`) — 원 작업은 코드 drift로 "포팅이 아니라 재작성"으로 전환 |
| 개명 비용 | 축약(슬러그 없는) 참조가 docs 51곳·MEMORY 29곳 — S3-28만 docs 24·MEMORY 15 |

### 판정과 근거

**재채번을 실행하지 않는다.** main의 S3-26/27/28은 현재 저장소에서 **유일본**이므로 번호만으로 결정 가능하며, 개명은 결정 가능성을 개선하지 못한 채 참조 90곳+를 파손한다. `S3-32/33/34` 우회 등재를 **정식 처분으로 추인**하고, 이 판정으로 해당 안건을 종결한다.

논리적 선례: `store._GRANDFATHERED_ID_NUMBERS`의 `ARCH-13`("개명 시 기존 참조 파손")과 동일한 판단 축이다. 다만 ARCH-13은 *2벌이 main 안에 공존*하는 반면 이 건은 *상대가 소멸*했다는 점에서 더 약한 사안이다.

**남는 부산물(보고만)**: 1차 재채번 시도가 만든 Alembic 리비전 `c5d6e7f0a2b3`는 main의 `SEC-07` 리비전과 충돌 상태 그대로이나, 그 파일이 삭제된 브랜치에만 존재하므로 main 마이그레이션 체인에는 영향이 없다. 재작성(S3-33) 시 새 리비전을 발급한다.

## §2. 판정 B — 착지대 브랜치 `claude/s3-25-bucket-c-renumber-fix`: **SHA 보존 + 폐기 확정**

### 사실

| 항목 | 실측 |
|---|---|
| head | `05a1a344` — 원격에서 **삭제됨**(`ls-remote` 부재) |
| 기록 상태 | 2026-08-10 브랜치 정리 17건 스냅샷 목록에 **없음** · head SHA가 저장소 어디에도 미기록(`git grep 05a1a344 origin/main` = 0건) — 이름만 MEMORY·통합점검 보고서에 잔존 |
| 내용 | merge-base `c3ec44b7` 기준 순수 delta 34파일 `+3,665/−55`. `l3/verify_final_answer.py`(+317 신규)·`l4/completion.py`(+246 신규)·`test_coach_completion.py`(+871 신규)·모바일 완료 플로우·Alembic 1건 |
| 재채번 포함 여부 | ❌ **미적용** — YAML rename 커밋 0건, S3-26/27/28이 각 2벌 공존, 계산해 둔 리비전 `e7f0a2b3c4d7` 미반영. "재채번 패치"가 아니라 **재채번 직전에 멈춰 세운 착지대** |
| 접근성 | GitHub API로는 아직 접근 가능(실측 확인). 포인터를 아는 곳은 이 컨테이너의 낡은 ref뿐이었다 |

### 판정과 근거

**브랜치를 재생성하지 않고 폐기를 확정하되, head SHA `05a1a344`를 이 문서와 MEMORY에 기록해 참조 가능성만 지킨다.** 코드 직접 포팅은 이미 drift로 불가 판정됐으므로 브랜치를 되살릴 실익이 없고, 되살리면 방금 정리한 미머지 목록만 다시 늘어난다. 반면 완성된 테스트 설계(`test_coach_completion.py` 871줄 등)는 `S3-32/33/34` 재작성 시 참고 가치가 있어, **포인터 유실만은 막는다**.

*(이 판정 자체가 "삭제 기록 없는 브랜치 소멸"이라는 프로세스 결함의 사후 수습이다. 브랜치 정리 배치가 삭제 목록을 남기는데 이 건이 그 목록에 없다는 사실은 §4에 관찰로 남긴다.)*

## §3. 판정 C — 신규 발견분: **`HARN-22` 승계 태스크 1건 등재**

### 사실 — 부채는 줄지 않고 회전했다

2026-08-04 문서가 센 이중 배정 13건의 2026-08-11 시점 생사:

| 처분 | 건수 | 내역 |
|---|---|---|
| ✅ 재채번으로 해소 | 2 | `HARN-14`→`HARN-18`(`id_rename` 이벤트 실재) · `S3-13`→`S3-17` |
| ✅ 동일 full-ID로 해소 | 1 | `HARN-15`(q8tvcx 정본을 2026-08-10 main 회수) |
| ✅ 브랜치 소멸 + 내용 흡수 | 7 | `ASM-01/02`(→ASM-03~06 재등재) · `OPS-17/18`(→OPS-22·QUAL-01) · `PATH-01/02/03`(폐기·PATH-05 분리) |
| ⏸ moot 추인(§1) | 3 | `S3-26/27/28` |
| ⚠️ 검증 불능 | 2 | `S3-16`·`S4-18(b)` — 상대 브랜치 소실로 원문 주장 재현 실패 |

그런데 원격 38브랜치 전수 스캔에서 **어디에도 등재되지 않은 live 이중 배정 16건**이 나왔다(8개 브랜치): `PED-04`~`PED-08`·`PED-13`·`PED-15`·`PED-16`·`OPS-20`·`OPS-21`·`OPS-24`·`OPS-25`·`MOB-14`·`S4-19`·`S4-22`·`VIZ-04`. 여기에 main 내부에 2벌 공존하는 `ARCH-13`(영구 유예 등재분)이 더해진다.

### 근본 결함 — 계기판이 없다

- `HARN-15`(#763 `684aa430`)가 만든 것은 **`cmd_add` 시점 예방**(원격 브랜치 `backlog/tasks/` 파일명을 3번째 관측 표면으로 합류)뿐이다.
- 2선 `validate`는 `_id_number_collisions(backlog.tasks.keys())`로 **로컬 백로그만** 본다.
- 서브커맨드 18개 중 **"지금 무엇이 충돌 중인가"를 묻는 조회 표면이 없다** — 위 16건은 수동 `ls-tree` 루프로만 발견됐다. CLAUDE.md "측정 없는 게이트" 계열의 결함이다.

### 판정

**`HARN-22-id-collision-inventory-and-renumber-authority`를 등재한다**(`backlog.py add` 경유·stage S4·priority 3). 소유 범위: ①충돌 조회 CLI 계기판 신설(`scan_remote_task_files` 재사용·fetch=False·fail-open 유지) ②live 16건 생사 추적(수기 목록 동결 금지 — 소멸분은 출력에서 자동으로 빠져야 한다) ③**재채번 판정 권한의 승계 명시** ④grandfather 장부와의 정합(면제분을 숨기지 말고 사유와 함께 표시) ⑤범위 밖 = 브랜치 triage·문서 참조 일괄 정정·개별 재채번 실행.

**판정 권한 자체는 이 문서로 소멸하지 않는다.** 개별 충돌의 재채번 실행은 계속 Kiki 판정이며, `HARN-22`는 기계가 **목록과 근거를 제시하는** 좌석이다. `HARN-15`가 done이 되면서 유보가 산문(`MEMORY.md`·통합점검 보고서 §7-1)에만 남아 어떤 열린 태스크에도 승계되지 않았던 상태를 이것으로 해소한다.

## §4. 정직한 공백 — 이 판정이 하지 않은 것

1. **live 16건의 개별 재채번·폐기 판정** — `HARN-22` ②가 목록을 세운 뒤 건별로 판정한다. 대부분 미머지 브랜치 triage와 함께 결정될 사안이다.
2. **미머지 브랜치 12건의 처분** — 별도 안건(브랜치 triage). 이 판정은 번호 정합만 다룬다.
3. **문서 축약 번호 참조 150곳+ 정정** — 재채번을 하지 않기로 했으므로 정정 대상이 아니다. 다만 축약:슬러그 비율이 약 5:1이라 **개명 비용이 구조적으로 크다**는 사실은 향후 판정의 상수로 남는다.
4. **`S3-16`·`S4-18(b)` 검증 불능 2건** — 상대 브랜치가 사라져 원문 주장을 확인할 방법이 없다. "충돌 없음"으로 단정하지 않고 미확인으로 남긴다.
5. **브랜치 삭제 기록 누락의 재발 방지** — `s3-25-bucket-c-renumber-fix`가 삭제 스냅샷 목록에 없는 채 사라진 경위는 규명하지 못했다(정리 배치 로그와 대조 불가). 규칙·태스크 신설은 하지 않고 **1회 관측으로 기록**한다 — 동일 유형 재발 시(2회+) 실수 관리 규약에 따라 등재한다.
6. **grandfather 장부 등재 여부** — §1의 moot 판정을 `_GRANDFATHERED_ID_NUMBERS`에 실을지는 `HARN-22` ④로 넘긴다(코드 변경이라 이 판정서의 범위 밖).

## 부록 — 실측 근거 (2026-08-11)

- 기준 `origin/main` `959ec4ad`. 브랜치 생사: `git ls-remote origin refs/heads/<branch>` 전수 · 스냅샷 내용: `git ls-tree <ref>:backlog/tasks`.
- `claude/s3-25-bucket-c-renumber-fix`: head `05a1a344`(merge, parents `e74d2e7b`+`c3ec44b7`) · merge-base `c3ec44b7` · delta 34파일 `+3,665/−55` · 충돌 해결 4파일(`api/coach.py`·`db/schema_version.py`·`chat_screen.dart`·`test_coach_integration.py`) · 원격 부재 · `git grep 05a1a344 origin/main` = 0건.
- 1차 재채번 커밋(삭제된 `tlthrr` 계보): `a178ce10`(S3-26) `a4e42eab`(S3-27) `8e8a9218`(S3-28) `379bf2cc`(S3-29) `fcc554be`(S3-30) `220ca76a`(S3-31).
- `HARN-15` 구현: `684aa430`(#763) — `remote_claims.scan_remote_task_files()` 신설·`backlog.py:_taken_id_numbers()` 3번째 출처 합류·서브커맨드 조회 표면 미신설.
- 재채번 집행 이력 전량: `backlog/events.ndjson`의 `id_rename` **3건**(HARN-18·MOB-12·MOB-13).
- 축약 참조 표본(docs/MEMORY): S3-28 24/15 · S4-18 22/4 · PED-05 23/9 · ARCH-13 20/22 · S3-27 14/6 · S3-26 13/8.
- 등재 검증: `backlog.py validate` → green, exit 0.

---

**판정**: Kiki (2026-08-11) | **집행·기록**: claude 세션 `claude/whymath-constitution-rules-check-azdnov` | **승계 좌석**: `HARN-22`
