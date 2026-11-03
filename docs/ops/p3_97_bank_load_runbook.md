# P3-97 — 운영 DB 미적분 문제은행 적재 (Kiki 실행 런북)

> 판정 기준: main `37e32712` 이후 + 이 런북의 PR. 이 런북이 쓰는 읽기 전용 미리보기
> `scripts/ops/p3_97_bank_load_probe.py`는 **이 PR이 병합돼야 `origin/main`에 있다.** 병합 전에 [B]를 돌리면
> `WT_OK=False`로 거부된다.
>
> **이 문서가 실행으로 검증한 것과 못 한 것은 §9에 따로 적었다.**

---

## 1. 과제 명칭

운영 DB 미적분 문제은행 적재 — `problem_bank_p3_calculus1_diff_v0`(504행)·`problem_bank_conceptual_v0`(360행)을
운영 DB `problem`에 넣는다.

## 2. 목적

P3-32 운영 실측(2026-11-03)에서 핵심 개념 힌트 연결이 2/10에서 멈췄다. 운영 DB(문항 1,703행)에 나머지 8개
개념(12미적Ⅰ-02-02~02-06 · 02-08~02-10)의 적격 문항이 **한 건도 없기** 때문이다. Kiki가 2026-11-03에
적재를 결정했고(학생 노출 승인 문항이 늘어나는 것을 알고), 범위는 문장 결함이 알려진 0건인 두 은행으로
정했다. `problem_bank_p3_fill_v0`는 문장 결함 수십 곳이 있고 P3-91 교정 때 문항 ID가 바뀌므로 넣지 않는다.

적재 후 P3-32 런북(`docs/ops/p3_32_hint_link_runbook.md`)을 다시 돌리면 hint 연결 10/10을 판정할 수 있다.

## 3. 구체적 절차

| 단계 | 무엇이 일어나는가 | DB 쓰기 | 기대 출력(판정값) |
|---|---|---|---|
| A | Docker Desktop·`whymath-pg` 기동 확인 | 없음 | `DOCKER_OK=True` |
| B | main 기준 임시 worktree 생성(공유 클론 무변경) | 없음 | `WT_OK=True` · `CLONE_HEAD_UNCHANGED=True` |
| C | 환경 · 코드 출처 · DB 도달 · **적재 전 미리보기** | 없음 | `PREVIEW_OK=True` · `LOAD_VERDICT=OK` |
| D | 적재가 쓰는 4개 표 백업 | 없음(파일만 생성) | `BACKUP_OK=True` |
| E | 적재 확인 입력(`APPLY` 한 단어) | 없음 | — |
| F | **적재** — 두 은행 | **있음** | `LOAD_OK=True` |
| G | **적재 후 실측** — 미리보기 재측정 · P3-32 프로브 | 없음 | `AFTER_OK=True` |
| H | 임시 worktree 정리 | 저장소 밖 폴더만 | `WT_REMOVED=True` |

**소요 시간**: 샌드박스(로컬 PG 16)에서 두 은행 적재가 합쳐 1분 안쪽이었다. 운영 규모도 같은 행 수라 비슷할
것으로 보지만 실측은 아니다.

**적재는 다시 돌려도 안전하다**(slug 기준 `ON CONFLICT` upsert — 두 번째 실행은 갱신만 한다). CMS로 고친 행과
발행 판이 있는 행은 건너뛰고 충돌로 보고한다. `--overwrite-cms-edits`는 **쓰지 않는다.**

## 4. 성공 기준

| 판정값 | 뜻 |
|---|---|
| `LOAD_VERDICT=OK` | 새로 들어갈 행이 있고 slug 충돌이 0이다(충돌이 있으면 옛 id가 남아 측정이 그 문항을 못 찾는다) |
| `LOAD_OK=True` | 두 은행 적재 CLI가 모두 exit 0 |
| `AFTER_OK=True` | 재측정에서 새로 들어갈 행이 0(`TOTAL_NEW=0`)이고, P3-32 프로브의 `VERDICT=READY` · `CONCEPTS_REPLAYABLE=10` |

### 샌드박스 리허설 수치와 대조

운영과 비슷하게 `generated_v0`·`misconception_mc_v0`만 적재한 샌드박스(문항 1,699행)에서 같은 블록 순서를 돌린
값이다. 운영 DB는 행 수가 조금 다르므로(1,703) 일치가 합격 기준은 아니다.

| 키 | 샌드박스 |
|---|---:|
| `TOTAL_NEW` · `TOTAL_NEW_APPROVED` | 864 · 864 |
| `TOTAL_SLUG_CONFLICT` · `TOTAL_PROTECTED` | 0 · 0 |
| `CONCEPTS_GAINING` | 9 (02-01은 이미 있음) |

`TOTAL_NEW_APPROVED`가 **학생 출제 후보로 새로 들어오는 승인 문항 수**다. 이 수를 [C]에서 보고 [E]에서 확인한다.

## 5. 실행 환경

- **머신**: Phaiakes9(= Kiki의 작업 PC 그 자체 · 별도 접속 없음)
- **시스템**: Windows PowerShell (WSL 아님)
- **작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath` (블록이 스스로 `cd`한다)
- **선행 조건**: ① 이 PR이 main에 병합됨 ② Docker Desktop, `whymath-pg`(호스트 포트 **5433**)
  ③ `src\backend\.venv`가 이미 세팅돼 있음
- **코드 출처**: 공유 작업 사본과 무관하게 main의 사본(임시 worktree `WhyMath_wt_<main 해시>`)에서 실행한다.

## 6. 창 구분

**전 단계가 새 PowerShell 창 하나에서 끝난다.** 블록 사이에 **같은 창을 유지**해야 한다 — 뒤 블록이 앞 블록의
변수를 읽는다. 창을 닫았거나 변수가 없으면 쓰기 블록은 **스스로 거부**한다(`WRITE_REFUSED=True`).

---

## 실행 블록

> 자리표시자가 하나도 없다. **블록 하나씩** 붙여넣고 각 블록 끝의 판정값을 확인한다. 쓰기 블록 [F]는
> 선행 판정을 스스로 다시 검사해 거부한다. [E]는 한 줄짜리 블록이며 **혼자** 붙여넣는다.

### [A] Docker 기동 + prod DB 컨테이너 확인

```powershell
# [Windows PowerShell · Phaiakes9] 새 창 · A Docker 기동 (읽기 전용)
cd C:\Users\kiki\Desktop\__AI\WhyMath
docker info *> $null
if ($LASTEXITCODE -ne 0) {
  "DOCKER_DAEMON=down — Docker Desktop 기동을 시도합니다(최대 180초)."
  $DockerExe = @(
    "C:\Program Files\Docker\Docker\Docker Desktop.exe",
    "$env:LOCALAPPDATA\Docker\Docker Desktop.exe"
  ) | Where-Object { Test-Path $_ } | Select-Object -First 1
  "DOCKER_EXE_FOUND=" + [bool]$DockerExe
  if ($DockerExe) { Start-Process $DockerExe }
  for ($i = 1; $i -le 36; $i++) {
    Start-Sleep -Seconds 5
    docker info *> $null
    if ($LASTEXITCODE -eq 0) { "DOCKER_UP_AFTER_SEC=" + ($i * 5); break }
  }
}
docker start whymath-pg *> $null
docker ps --filter "name=whymath-pg" --format "{{.Names}} | {{.Status}} | {{.Ports}}"
$Probe1 = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT 1;"
"DOCKER_OK=" + ($LASTEXITCODE -eq 0 -and $null -ne $Probe1)
```

**확인**: `DOCKER_OK=True`.

### [B] main 기준 임시 worktree (공유 클론을 옮기지 않는다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · B 임시 worktree (읽기 전용 · 클론 무변경)
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
$CloneHead = (git rev-parse --short HEAD)
$MainSha = (git rev-parse --short origin/main)
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath_wt_$MainSha"
if (Test-Path $Wt) { "WT_EXISTS=True · 이미 있는 폴더를 재사용합니다" } else { git worktree add --detach $Wt origin/main }
$WtHead = (git -C $Wt rev-parse --short HEAD)
git -C $Wt diff --quiet origin/main -- "src/backend/whymath_backend" "scripts/ops" "data/corpus"
$WtClean = ($LASTEXITCODE -eq 0)
$HasLoadProbe = (Test-Path "$Wt\scripts\ops\p3_97_bank_load_probe.py")
$HasLinkProbe = (Test-Path "$Wt\scripts\ops\p3_32_hint_link_probe.py")
$BankCalc = "$Wt\data\corpus\problem_bank_p3_calculus1_diff_v0\problems.jsonl"
$BankConc = "$Wt\data\corpus\problem_bank_conceptual_v0\problems.jsonl"
$HasBanks = (Test-Path $BankCalc) -and (Test-Path $BankConc)
$WtOk = ($WtHead -eq $MainSha) -and $WtClean -and $HasLoadProbe -and $HasLinkProbe -and $HasBanks
"MAIN_SHA=$MainSha · WT_HEAD=$WtHead · WT_CLEAN=$WtClean · LOAD_PROBE=$HasLoadProbe · LINK_PROBE=$HasLinkProbe · BANKS=$HasBanks · WT_OK=$WtOk"
"CLONE_HEAD_UNCHANGED=" + ((git rev-parse --short HEAD) -eq $CloneHead)
```

**확인**: `WT_OK=True` · `CLONE_HEAD_UNCHANGED=True`. `LOAD_PROBE=False`면 이 PR이 아직 main에 없다.

### [C] 환경 · 코드 출처 · DB 도달 · 적재 전 미리보기 (읽기 전용)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · C 환경 + 적재 전 미리보기 (읽기 전용)
cd $Wt
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$env:PYTHONPATH = "$Wt\src\backend"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$LoadProbe = "$Wt\scripts\ops\p3_97_bank_load_probe.py"
$LinkProbe = "$Wt\scripts\ops\p3_32_hint_link_probe.py"
$RelCalc = "data/corpus/problem_bank_p3_calculus1_diff_v0/problems.jsonl"
$RelConc = "data/corpus/problem_bank_conceptual_v0/problems.jsonl"
$OutDir = "C:\Users\kiki\Desktop\__AI\WhyMath\work\p3_97_$MainSha"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
function Get-KvMap([string[]]$Lines) { $Map = @{}; foreach ($L in $Lines) { if ($L -match '^([A-Z0-9_]+)=(.*)$') { $Map[$Matches[1]] = $Matches[2].Trim() } }; return $Map }
function Get-KvInt($Map, [string]$Key) { $V = $Map[$Key]; if ($null -ne $V -and $V -match '^-?\d+$') { return [int]$V } else { return -1 } }
"PY_OK=" + (Test-Path $Py)
& $Py -m whymath_backend.ops.db_host_reachability
$ReachExit = $LASTEXITCODE
"REACH_EXIT=$ReachExit"
$PreLines = & $Py $LoadProbe preview --bank $RelCalc --bank $RelConc
$PreExit = $LASTEXITCODE
$PreLines
"PREVIEW_EXIT=$PreExit"
$PreMap = Get-KvMap $PreLines
if ($PreLines) { [IO.File]::WriteAllLines("$OutDir\preview_before.kv", [string[]]$PreLines); "EVIDENCE_SAVED=$OutDir\preview_before.kv" }
$CodeOk = ([bool]$PreMap["CODE_PROBE"]) -and ($PreMap["CODE_PROBE"] -like "$Wt\*") -and ($PreMap["CODE_PHASE3"] -like "$Wt\*")
$PreviewOk = ($PreExit -eq 0) -and ($PreMap["LOAD_VERDICT"] -ceq "OK") -and ((Get-KvInt $PreMap "TOTAL_NEW") -gt 0) -and ((Get-KvInt $PreMap "TOTAL_SLUG_CONFLICT") -eq 0)
"NEW_APPROVED_FOR_STUDENTS=" + $PreMap["TOTAL_NEW_APPROVED"] + " · CONCEPTS_GAINING=" + $PreMap["CONCEPTS_GAINING"]
"CODE_OK=$CodeOk · PREVIEW_OK=$PreviewOk · REACH_EXIT=$ReachExit"
```

**확인**: `REACH_EXIT=0` · `PREVIEW_EXIT=0` · `CODE_OK=True` · `PREVIEW_OK=True`. `NEW_APPROVED_FOR_STUDENTS`가
학생 출제 후보로 새로 들어올 승인 문항 수다(샌드박스 864).

| 값 | 뜻 | 대처 |
|---|---|---|
| `LOAD_VERDICT=SLUG_CONFLICT` | 같은 slug가 다른 id로 이미 있다 | **적재하지 않는다**(가드가 거부). 출력 전체 전달 |
| `LOAD_VERDICT=NOTHING_NEW` | 두 은행이 이미 다 들어 있다 | 적재 불필요. P3-32 런북으로 바로 간다 |
| `TOTAL_PROTECTED`가 0이 아님 | CMS 편집·발행 판이 있는 행 — 적재가 건너뛴다 | 값만 전달 |

### [D] 적재가 쓰는 4개 표 백업 (DB 읽기 전용 · 파일 생성)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · D 백업 (DB 읽기 전용 · 파일 생성)
cd $Wt
$BackupFile = "$OutDir\p3_97_before.dump"
$BackupReady = $WtOk -and $CodeOk -and $PreviewOk -and ($ReachExit -eq 0) -and ($Wt -notmatch '\s')
"BACKUP_READY=$BackupReady · WT_OK=$WtOk CODE_OK=$CodeOk PREVIEW_OK=$PreviewOk REACH_EXIT=$ReachExit"
if ($BackupReady) { docker exec whymath-pg pg_dump -U whymath -d whymath -t problem -t problem_concept -t problem_relation -t content_provenance -Fc -f /tmp/p3_97_before.dump; $DumpExit = $LASTEXITCODE; docker cp whymath-pg:/tmp/p3_97_before.dump $BackupFile; $CopyExit = $LASTEXITCODE; "DUMP_EXIT=$DumpExit · COPY_EXIT=$CopyExit" } else { $DumpExit = -1; $CopyExit = -1; "BACKUP_REFUSED=True — WT_OK=$WtOk CODE_OK=$CodeOk PREVIEW_OK=$PreviewOk REACH_EXIT=$ReachExit · 전부 True/0이어야 백업합니다" }
$BackupBytes = 0
if (Test-Path $BackupFile) { $BackupBytes = (Get-Item $BackupFile).Length }
$TocLines = docker exec whymath-pg pg_restore -l /tmp/p3_97_before.dump
$ListExit = $LASTEXITCODE
$TocTables = @($TocLines | Where-Object { $_ -match 'TABLE DATA public (problem|problem_concept|problem_relation|content_provenance) ' }).Count
$BackupOk = $BackupReady -and ($DumpExit -eq 0) -and ($CopyExit -eq 0) -and ($BackupBytes -gt 0) -and ($ListExit -eq 0) -and ($TocTables -eq 4)
"BACKUP_BYTES=$BackupBytes · RESTORE_LIST_EXIT=$ListExit · TOC_TABLES=$TocTables · BACKUP_OK=$BackupOk"
```

**확인**: `TOC_TABLES=4` · `BACKUP_OK=True`.

### [E] 적재 확인 입력 (한 줄 블록 — 이 줄만 붙여넣는다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · E 적재 확인 입력 (이 블록만 혼자 붙여넣는다)
$Confirm = Read-Host "NEW_APPROVED_FOR_STUDENTS 수를 확인했다면 대문자 APPLY 를 입력하고 Enter"
```

**이 블록은 위아래 어떤 줄과도 같이 붙여넣지 않는다.** `APPLY` 외의 입력이면 [F]가 거부한다.

### [F] 적재 — 두 은행 (여기서만 DB에 쓴다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · F 적재 (쓰기 · 조건 미충족이면 스스로 거부)
cd $Wt
$ConfirmOk = ($Confirm -ceq "APPLY")
$LoadReady = $BackupOk -and $ConfirmOk -and $WtOk -and $CodeOk -and $PreviewOk -and ($ReachExit -eq 0)
"LOAD_READY=$LoadReady · BACKUP_OK=$BackupOk CONFIRMED=$ConfirmOk WT_OK=$WtOk CODE_OK=$CodeOk PREVIEW_OK=$PreviewOk REACH_EXIT=$ReachExit"
if ($LoadReady) { cmd /c "$Py -m whymath_backend.l1.problem_bank.populate --problems $RelCalc 1> $OutDir\load_calc.log 2>&1"; $LoadCalcExit = $LASTEXITCODE; cmd /c "$Py -m whymath_backend.l1.problem_bank.populate --problems $RelConc 1> $OutDir\load_conceptual.log 2>&1"; $LoadConcExit = $LASTEXITCODE; "LOAD_CALC_EXIT=$LoadCalcExit · LOAD_CONCEPTUAL_EXIT=$LoadConcExit" } else { $LoadCalcExit = -1; $LoadConcExit = -1; "WRITE_REFUSED=True — BACKUP_OK=$BackupOk CONFIRMED=$ConfirmOk WT_OK=$WtOk CODE_OK=$CodeOk PREVIEW_OK=$PreviewOk REACH_EXIT=$ReachExit · 전부 True/0이어야 적재합니다. [B]~[E]를 같은 창에서 순서대로 실행하세요" }
$Confirm = $null
Get-Content "$OutDir\load_calc.log", "$OutDir\load_conceptual.log" -ErrorAction SilentlyContinue | Select-String -Pattern "적재|orphan|충돌|Error|Traceback" | ForEach-Object { $_.Line }
$LoadOk = ($LoadCalcExit -eq 0) -and ($LoadConcExit -eq 0)
"LOAD_OK=$LoadOk"
```

**확인**: `LOAD_READY=True` → `LOAD_CALC_EXIT=0` · `LOAD_CONCEPTUAL_EXIT=0` → `LOAD_OK=True`. 요약 줄에 "문제 적재
완료: 504건"과 "360건"이 보여야 한다. `개념 orphan skip`이 0이 아니면 그 수를 전달한다(개념 태깅 일부가 빠졌다).

적재는 은행마다 한 트랜잭션이다 — 중간에 예외가 나면 그 은행은 롤백되고, 출력 파일에 예외가 남는다.

### [G] 적재 후 실측 (읽기 전용)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · G 적재 후 실측 (읽기 전용)
cd $Wt
$PostLines = & $Py $LoadProbe preview --bank $RelCalc --bank $RelConc
$PostExit = $LASTEXITCODE
$PostMap = Get-KvMap $PostLines
if ($PostLines) { [IO.File]::WriteAllLines("$OutDir\preview_after.kv", [string[]]$PostLines) }
$LinkLines = & $Py $LinkProbe link
$LinkExit = $LASTEXITCODE
$LinkMap = Get-KvMap $LinkLines
if ($LinkLines) { [IO.File]::WriteAllLines("$OutDir\link_after_load.kv", [string[]]$LinkLines) }
$LinkLines | Where-Object { $_ -match '^(DB_PROBLEM_ROWS|ELIGIBLE_IN_DB|REPLAYABLE_IN_DB|CONCEPTS_REPLAYABLE|REPLAY_BANK_COUNT|VERDICT)=' }
"BEFORE_AFTER DB 문항 행: " + $PreMap["DB_PROBLEM_ROWS"] + " -> " + $PostMap["DB_PROBLEM_ROWS"] + " · 남은 신규 행: " + $PostMap["TOTAL_NEW"]
$AfterOk = $LoadOk -and ($PostExit -eq 0) -and ((Get-KvInt $PostMap "TOTAL_NEW") -eq 0) -and ($LinkExit -eq 0) -and ($LinkMap["VERDICT"] -ceq "READY") -and ((Get-KvInt $LinkMap "CONCEPTS_REPLAYABLE") -eq 10)
"AFTER_OK=$AfterOk"
"JUDGED_AGAINST_MAIN=$MainSha"
```

**확인**: `AFTER_OK=True` · `VERDICT=READY` · `CONCEPTS_REPLAYABLE=10`. 이 상태면 **P3-32 런북을 새 창에서
[A]부터** 다시 돌린다 — 재생 은행 목록이 이번에는 여러 개로 늘어난다.

- `TOTAL_NEW`가 0이 아니면 적재되지 않은 행이 남았다 — `load_*.log`를 전달한다.
- `VERDICT=PARTIAL`이면 적재는 됐지만 일부 개념에 재생 가능한 문항이 없다 — `link_after_load.kv`를 전달한다.

### [H] 임시 worktree 정리 (저장소 밖 폴더만 지운다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · H 임시 worktree 정리
cd C:\Users\kiki\Desktop\__AI\WhyMath
if ($Wt -and ($Wt -like "C:\Users\kiki\Desktop\__AI\WhyMath_wt_*") -and (Test-Path $Wt)) { git worktree remove --force $Wt; "WT_REMOVE_EXIT=$LASTEXITCODE" } else { "WT_REMOVE_SKIPPED=True — WT=$Wt (WhyMath_wt_ 로 시작하는 폴더만 지웁니다)" }
"WT_REMOVED=" + (-not (Test-Path $Wt))
"OUT_DIR_KEPT=$OutDir"
```

---

## 7. 전달할 것

[C]·[F]·[G] 화면 전체. 특히 `NEW_APPROVED_FOR_STUDENTS`·`LOAD_OK`·`AFTER_OK`·`VERDICT` 줄.

## 8. 범위 밖

- `problem_bank_p3_fill_v0` 적재 — P3-91 교정(문항 ID 변경) 뒤 별도로.
- 힌트 생성 — P3-32 런북이 한다.

## 9. 이 문서가 검증한 것과 못 한 것

**실행으로 검증한 것**(이 PR의 세션 · 로컬 PostgreSQL 16 + pgvector · 운영 아님): 운영과 비슷한 샌드박스
(`generated_v0`·`misconception_mc_v0`만 적재 · 1,699행)에서 미리보기 → 적재 → 미리보기 재측정 → P3-32 프로브 →
P3-32 전 과정(재생·승격·힌트)을 돌렸다. 결과는 PR 본문과 `docs/reviews/p3_97_bank_load_rehearsal_2026-11-03.md`에
있다.

**검증하지 못한 것**: PowerShell 블록 자체(세션은 Linux · 형식은 `check_runbook_blocks.py`와
`tests/infra/test_p3_97_bank_load_runbook.py`가 정적으로 검사) · 운영 DB의 실제 slug 충돌 여부 · 백업 복원.

## 10. 운영 실행 기록 (2026-11-03 · 판정 기준 main `c4ef20c2`)

- **적재 실행**: 문항 1,703 → 2,567행(+864 = [C] 예측과 일치) · slug 충돌 0 · 개념 연결 누락 0 · [G] `VERDICT=READY` ·
  `CONCEPTS_REPLAYABLE=10`. 기록은 대장 PR #1834.
- **재실행(확인)**: 그 뒤 [A]~[C]를 다시 돌리자 [C]가 **`LOAD_VERDICT=NOTHING_NEW`**를 냈다(`IN_DB_SAME_ID` 504 + 360 ·
  `SLUG_CONFLICT=0` · `PROTECTED=0` · `DB_PROBLEM_ROWS=2567`). 런북 설계대로 `PREVIEW_OK=False`로 [D]~[G]가 실행되지 않아
  이 재실행의 쓰기는 0이다 — 이미 적재된 상태를 가드가 정확히 판정한 사례다.
