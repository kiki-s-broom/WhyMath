# EOS-194 — 운영 DB 문항 1건 발행 측정 (Kiki 실행 런북)

> 판정 기준: main `4ff19484` 이후 + 이 런북의 PR. 측정 코드 = `docs/reviews/eos194_acceptance3_2026-10-31/eos194_measure.py`
> (이 PR에서 후보 검사 잘림 제거 · `SCAN_TRUNCATED` 출력 추가). 병합 전에 [B]를 돌리면 `WT_OK=False`로 거부된다.
>
> 지난 실행 기록: `docs/reviews/eos194_acceptance3_2026-10-31.md`(2026-10-31 · 발행 가능 후보 0 · 쓰기 0).

---

## 1. 과제 명칭

EOS-194 인수 조건 ③ — 운영 DB에서 문항 1건을 실제 CMS 발행 표면으로 발행하고, 학생 시도가 그 판에 고정(`outcome=pinned`)되는지
확인한다.

## 2. 목적

EOS-194가 만든 발행 표면(CMS 라우트 4개)이 운영 데이터에서 실제로 작동하는지 보는 마지막 확인이다. 10월 31일에는 발행 가능한
문항이 0건이라 쓰지 못했다. 그 뒤 P3-32·P3-97(#1834)로 운영 DB의 핵심 개념 문항에 검증 힌트가 생겼으므로 다시 잰다.

**먼저 읽기 전용 점검만 한다.** 발행 게이트는 문항 메타데이터 7필드를 요구한다. 리허설 DB(이 PR의 세션 · 운영 모사 2,563행)에서는
힌트가 붙은 979건이 **전부 오개념 서명(`misconception_signature`) 결손**으로 발행 후보가 0건이었다. 원인은 문항이 연결된 원자
개념 행의 `source_id`가 비어 있어 오개념 카탈로그 상속(`concept.source_id` ↔ `misconception_catalog.concept_src_id`)이 성립하지
않는 것이다(`l3/problem_metadata_evidence.py` 모듈 한계에 명시). 운영 DB도 같은 원자 백본 적재를 썼으므로 **같은 결과가 나올
가능성이 높다** — [C]가 `PUBLISHABLE=0`이면 거기서 멈추고 출력을 전달한다. 쓰기 블록은 스스로 거부한다.

**P3-99 이후(2026-11-04)**: 발행 게이트가 개념 `code`로도 오개념을 상속한다. 원자 유래 오개념(`ATOM:<code>` 1,823행)이
카탈로그에 있으면 원자 개념 문항이 상속으로 인정된다(오개념 유발 슬롯 문항은 규칙상 제외). 리허설 DB에서 그 행을 적재한 뒤
`PUBLISHABLE`이 0 → 861이 됐다. [C]가 `ATOM_MISCONCEPTION_ROWS=0`을 내면 `PUBLISHABLE` 값과 무관하게 [C2](백업 후 원자
오개념 적재)를 실행하고 [C]를 다시 돌린다(P3-102 · Kiki 결정 2026-11-05 — 운영은 `PUBLISHABLE=76`인데 903건이 오개념 서명
결손이라, 이전 조건 `PUBLISHABLE=0`이 적재를 막았다).

## 3. 구체적 절차

| 단계 | 무엇이 일어나는가 | DB 쓰기 | 기대 출력(판정값) |
|---|---|---|---|
| A | Docker Desktop·`whymath-pg` 기동 확인 | 없음 | `DOCKER_OK=True` |
| B | main 기준 임시 worktree(공유 클론 무변경) | 없음 | `WT_OK=True` |
| C | 환경 · 코드 출처 · DB 도달 · **발행 가능 후보 점검** | 없음 | `PREFLIGHT_OK=True` 또는 `PUBLISHABLE=0`(멈춤) |
| C2 | (조건부) 백업 후 원자 유래 오개념 1,823행 적재 → [C] 다시 | **있음**(`misconception_catalog`만 · 멱등) | `ATOM_LOAD_OK=True` |
| D | 운영 DB 전체 백업 | 없음(파일만) | `BACKUP_OK=True` |
| E | 발행 확인 입력(`APPLY` 한 단어) | 없음 | — |
| F | **발행 측정** — 측정 계정 2개 · 판 1개 발행 · 시도 1건 | **있음** | `EOS194_ACCEPTANCE3_OK=True` |
| G | (선택) 되돌리기 — 판 내리기 · 측정 학습자 삭제 | 있음 | `UNDO_OK=True` |
| H | 임시 worktree 정리 | 저장소 밖 폴더만 | `WT_REMOVED=True` |

**[F]가 쓰는 것**: `user_profile` 2행(측정 전용 staff·learner) · `problem_version` 1행(DRAFT→PUBLISHED) · 대상 문항의 발행 포인터 ·
`privacy_audit` 전이 5행 · 측정 학습자의 시도 1건과 학습 상태 행. 대상 문항은 스크립트가 고른다(후보 중 `problem_id` 오름차순 첫 1건).

## 4. 성공 기준

- [C] `PUBLISHABLE`이 1 이상이고 `SCAN_TRUNCATED=False`(후보를 전부 검사했다).
- [F] `EOS194_ACCEPTANCE3_OK=True` = 판 상태 PUBLISHED · 문항 포인터 일치 · 시도의 판 고정 일치 · 로그 `outcome=pinned`.
- 함께 나오는 `AFTER_EXPOSED_WITH_POINTER`/`AFTER_EXPOSED`가 인수 조건 ③의 "포인터 채워진 노출 문항 수 / 전체 노출 문항 수"다.

`PUBLISHABLE=0`은 실패가 아니라 **측정 결과**다 — `NOT_PUBLISHABLE_REASONS`가 어느 필드가 막는지 말한다. 그 값을 전달한다.

## 5. 실행 환경

- Phaiakes9 · Windows PowerShell · 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`(블록이 스스로 `cd`)
- 선행: ① 이 PR이 main에 병합됨 ② Docker Desktop, `whymath-pg`(5433) ③ `src\backend\.venv`

## 6. 창 구분

**새 PowerShell 창 하나**에서 끝낸다. 블록끼리 변수를 공유하므로 창을 바꾸지 않는다. 쓰기 블록은 선행 판정이 없으면 스스로 거부한다.

---

## 실행 블록

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

### [B] main 기준 임시 worktree

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · B 임시 worktree (읽기 전용 · 클론 무변경)
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
$CloneHead = (git rev-parse --short HEAD)
$MainSha = (git rev-parse --short origin/main)
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath_wt_$MainSha"
if (Test-Path $Wt) { "WT_EXISTS=True · 이미 있는 폴더를 재사용합니다" } else { git worktree add --detach $Wt origin/main }
$WtHead = (git -C $Wt rev-parse --short HEAD)
git -C $Wt diff --quiet origin/main -- "src/backend/whymath_backend" "docs/reviews/eos194_acceptance3_2026-10-31"
$WtClean = ($LASTEXITCODE -eq 0)
$MeasureFile = "$Wt\docs\reviews\eos194_acceptance3_2026-10-31\eos194_measure.py"
$HasFullScan = (Test-Path $MeasureFile) -and ((Get-Content $MeasureFile -Raw) -match "SCAN_TRUNCATED")
$WtOk = ($WtHead -eq $MainSha) -and $WtClean -and $HasFullScan
"MAIN_SHA=$MainSha · WT_HEAD=$WtHead · WT_CLEAN=$WtClean · FULL_SCAN=$HasFullScan · WT_OK=$WtOk"
"CLONE_HEAD_UNCHANGED=" + ((git rev-parse --short HEAD) -eq $CloneHead)
```

**확인**: `WT_OK=True`. `FULL_SCAN=False`면 이 PR이 아직 main에 없다.

### [C] 환경 · DB 도달 · 발행 가능 후보 점검 (읽기 전용)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · C 발행 가능 후보 점검 (읽기 전용)
cd $Wt
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$env:PYTHONPATH = "$Wt\src\backend"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$OutDir = "C:\Users\kiki\Desktop\__AI\WhyMath\work\eos194_$MainSha"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$env:EOS194_STATE = "$OutDir\eos194_state.json"
function Get-KvMap([string[]]$Lines) { $Map = @{}; foreach ($L in $Lines) { if ($L -match '^([A-Z0-9_]+)=(.*)$') { $Map[$Matches[1]] = $Matches[2].Trim() } }; return $Map }
function Get-KvInt($Map, [string]$Key) { $V = $Map[$Key]; if ($null -ne $V -and $V -match '^-?\d+$') { return [int]$V } else { return -1 } }
"PY_OK=" + (Test-Path $Py) + " · STATE_FILE_ABSENT=" + (-not (Test-Path $env:EOS194_STATE))
& $Py -m whymath_backend.ops.db_host_reachability
$ReachExit = $LASTEXITCODE
"REACH_EXIT=$ReachExit"
$PreLines = & $Py "$Wt\docs\reviews\eos194_acceptance3_2026-10-31\eos194_measure.py" preflight
$PreExit = $LASTEXITCODE
$PreLines
"PREFLIGHT_EXIT=$PreExit (0 = 후보 있음 · 3 = 후보 0 또는 스키마 불일치)"
$PreMap = Get-KvMap $PreLines
if ($PreLines) { [IO.File]::WriteAllLines("$OutDir\preflight_before.kv", [string[]]$PreLines); "EVIDENCE_SAVED=$OutDir\preflight_before.kv" }
$CodeOk = ([bool]$PreMap["CODE_FROM"]) -and ($PreMap["CODE_FROM"] -like "$Wt\*")
$PreflightOk = ($PreExit -eq 0) -and ($PreMap["SCHEMA_AT_HEAD"] -eq "True") -and ($PreMap["SCAN_TRUNCATED"] -eq "False") -and ((Get-KvInt $PreMap "PUBLISHABLE") -gt 0)
"CODE_OK=$CodeOk · PREFLIGHT_OK=$PreflightOk · REACH_EXIT=$ReachExit"
```

**확인**: `REACH_EXIT=0` · `CODE_OK=True`. 그리고 둘 중 하나다.

- `PREFLIGHT_OK=True` — 발행 가능 후보가 있다. [D]로 진행한다.
- `ATOM_MISCONCEPTION_ROWS=0` — `PUBLISHABLE` 값과 무관하게 [C2]로 원자 오개념을 적재한 뒤 [C]를 다시 붙여넣는다
  (P3-102). 다시 잰 [C]가 `PREFLIGHT_OK=True`면 [D]로 간다.
- `PUBLISHABLE=0`이고 `ATOM_MISCONCEPTION_ROWS`가 1 이상 — **여기서 멈춘다.** `NOT_PUBLISHABLE_REASONS` 줄을 포함한 화면
  전체를 전달한 뒤 [H]로 정리한다.

### [C2] (조건부) 백업 후 원자 유래 오개념 적재

[C]가 `ATOM_MISCONCEPTION_ROWS=0`을 낼 때만 실행한다(`PUBLISHABLE` 값과는 무관 — P3-102 · Kiki 결정 2026-11-05). 블록이
그 조건을 다시 확인하고, 맞지 않으면 스스로 거부한다. 이미 원자 행이 있으면(1 이상) 다시 적재하지 않는다. 쓰는 곳은 `misconception_catalog` 한 테이블이고 `mis_id` 기준 멱등 upsert라 다시 실행해도 같은 결과다.
끝나면 [C]를 다시 붙여넣는다.

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · C2 원자 오개념 적재 (쓰기 · 조건 미충족이면 스스로 거부)
cd $Wt
$AtomRowsBefore = Get-KvInt $PreMap "ATOM_MISCONCEPTION_ROWS"
$AtomReady = $WtOk -and $CodeOk -and ($ReachExit -eq 0) -and ($AtomRowsBefore -eq 0) -and ($Wt -notmatch '\s')
"ATOM_READY=$AtomReady · WT_OK=$WtOk CODE_OK=$CodeOk REACH_EXIT=$ReachExit ATOM_ROWS_BEFORE=$AtomRowsBefore"
if ($AtomReady) { Copy-Item "$OutDir\preflight_before.kv" "$OutDir\preflight_before_atomload.kv" -Force; docker exec whymath-pg pg_dump -U whymath -d whymath -Fc -f /tmp/eos194_atomload_before.dump; $ADumpExit = $LASTEXITCODE; docker cp whymath-pg:/tmp/eos194_atomload_before.dump "$OutDir\eos194_atomload_before.dump"; $ACopyExit = $LASTEXITCODE; docker exec whymath-pg pg_restore -l /tmp/eos194_atomload_before.dump *> $null; $AListExit = $LASTEXITCODE; $ABackupOk = ($ADumpExit -eq 0) -and ($ACopyExit -eq 0) -and ($AListExit -eq 0) -and (Test-Path "$OutDir\eos194_atomload_before.dump"); "ATOM_BACKUP_OK=$ABackupOk" } else { $ABackupOk = $false; "WRITE_REFUSED=True — ATOM_READY=False · [C]가 ATOM_MISCONCEPTION_ROWS=0 을 냈을 때만 적재합니다(이미 있으면 재적재 안 함)" }
if ($ABackupOk) { & $Py -m whymath_backend.l1.misconception.populate_atom --graph "$Wt\data\corpus\atom_graph_v1\graph.json"; $AtomLoadExit = $LASTEXITCODE; "ATOM_LOAD_EXIT=$AtomLoadExit" } else { $AtomLoadExit = -1; "ATOM_LOAD_SKIPPED=True — 백업이 확인되지 않아 적재하지 않습니다" }
$AtomRowsAfter = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM misconception_catalog WHERE mis_id LIKE 'ATOM:%';"
"ATOM_ROWS_AFTER=$AtomRowsAfter · ATOM_LOAD_OK=" + (($AtomLoadExit -eq 0) -and ("$AtomRowsAfter".Trim() -eq "1823"))
```

**확인**: `ATOM_LOAD_OK=True` · `ATOM_ROWS_AFTER=1823`. 적재 전 [C] 증거는 `preflight_before_atomload.kv`로 보존된다(다시 돌린
[C]가 `preflight_before.kv`를 덮어쓰므로). 그다음 [C]를 다시 붙여넣는다. 되돌리려면
`$OutDir\eos194_atomload_before.dump`로 복원한다.

### [D] 운영 DB 전체 백업 (DB 읽기 전용 · 파일 생성)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · D 백업 (DB 읽기 전용 · 파일 생성)
cd $Wt
$BackupFile = "$OutDir\eos194_before.dump"
$BackupReady = $WtOk -and $CodeOk -and $PreflightOk -and ($ReachExit -eq 0) -and ($Wt -notmatch '\s')
"BACKUP_READY=$BackupReady · WT_OK=$WtOk CODE_OK=$CodeOk PREFLIGHT_OK=$PreflightOk REACH_EXIT=$ReachExit"
if ($BackupReady) { docker exec whymath-pg pg_dump -U whymath -d whymath -Fc -f /tmp/eos194_before.dump; $DumpExit = $LASTEXITCODE; docker cp whymath-pg:/tmp/eos194_before.dump $BackupFile; $CopyExit = $LASTEXITCODE; "DUMP_EXIT=$DumpExit · COPY_EXIT=$CopyExit" } else { $DumpExit = -1; $CopyExit = -1; "BACKUP_REFUSED=True — WT_OK=$WtOk CODE_OK=$CodeOk PREFLIGHT_OK=$PreflightOk REACH_EXIT=$ReachExit · 전부 True/0이어야 백업합니다" }
$BackupBytes = 0
if (Test-Path $BackupFile) { $BackupBytes = (Get-Item $BackupFile).Length }
docker exec whymath-pg pg_restore -l /tmp/eos194_before.dump *> $null
$ListExit = $LASTEXITCODE
$BackupOk = $BackupReady -and ($DumpExit -eq 0) -and ($CopyExit -eq 0) -and ($BackupBytes -gt 0) -and ($ListExit -eq 0)
"BACKUP_BYTES=$BackupBytes · RESTORE_LIST_EXIT=$ListExit · BACKUP_OK=$BackupOk"
```

**확인**: `BACKUP_OK=True`.

### [E] 발행 확인 입력 (한 줄 블록 — 이 줄만 붙여넣는다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · E 발행 확인 입력 (이 블록만 혼자 붙여넣는다)
$Confirm = Read-Host "TARGET_PROBLEM_ID 를 확인했다면 대문자 APPLY 를 입력하고 Enter"
```

### [F] 발행 측정 (여기서만 DB에 쓴다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · F 발행 측정 (쓰기 · 조건 미충족이면 스스로 거부)
cd $Wt
$ConfirmOk = ($Confirm -ceq "APPLY")
$PublishReady = $BackupOk -and $ConfirmOk -and $WtOk -and $CodeOk -and $PreflightOk -and ($ReachExit -eq 0)
"PUBLISH_READY=$PublishReady · BACKUP_OK=$BackupOk CONFIRMED=$ConfirmOk WT_OK=$WtOk CODE_OK=$CodeOk PREFLIGHT_OK=$PreflightOk REACH_EXIT=$ReachExit"
if ($PublishReady) { $PubLines = & $Py "$Wt\docs\reviews\eos194_acceptance3_2026-10-31\eos194_measure.py" publish; $PubExit = $LASTEXITCODE; "PUBLISH_EXIT=$PubExit" } else { $PubLines = @(); $PubExit = -1; "WRITE_REFUSED=True — BACKUP_OK=$BackupOk CONFIRMED=$ConfirmOk WT_OK=$WtOk CODE_OK=$CodeOk PREFLIGHT_OK=$PreflightOk REACH_EXIT=$ReachExit · 전부 True/0이어야 발행합니다" }
$Confirm = $null
$PubLines
if ($PubLines) { [IO.File]::WriteAllLines("$OutDir\publish.kv", [string[]]$PubLines); "EVIDENCE_SAVED=$OutDir\publish.kv" }
$PubMap = Get-KvMap $PubLines
"RESULT · POINTER_FILLED_EXPOSED=" + $PubMap["AFTER_EXPOSED_WITH_POINTER"] + " / EXPOSED=" + $PubMap["AFTER_EXPOSED"] + " · EOS194_ACCEPTANCE3_OK=" + $PubMap["EOS194_ACCEPTANCE3_OK"]
```

**확인**: `PUBLISH_EXIT=0` · `EOS194_ACCEPTANCE3_OK=True`. 출력 전체를 전달한다.

- `PUBLISH_EXIT` 3·4 = 스크립트가 쓰기 전에 거부(후보 0·스키마 불일치·이전 실행 상태 파일 있음) — 쓰기 없음.
- 5·6·7 = 초안·전이·시도 단계에서 HTTP 실패(`*_ERROR` 줄에 응답 앞부분) — 그 전 단계까지는 쓰였다. 상태 파일이 남으므로 [G]로 되돌린다.
- 8 = 끝까지 돌았지만 판정 불일치 — `PROBLEM_POINTER_MATCH`·`ATTEMPT_PIN_MATCH`·`LOG_OUTCOME_PINNED` 줄을 전달한다.

### [G] (선택) 되돌리기 — 판 내리기 · 측정 학습자 삭제

측정이 끝난 뒤 운영 DB를 원래 상태로 돌리고 싶을 때만 실행한다. 발행된 판은 `DEPRECATED`가 되고 문항 포인터는 비워지며, 측정
학습자는 `DELETE /v1/me`로 지워진다(측정 staff 계정과 감사 행은 남는다). **실행 여부는 Kiki가 정한다** — 실행하지 않으면 그 문항
1건은 발행 상태로 남는다.

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · G 되돌리기 (선택 · 쓰기 · 상태 파일이 없으면 스스로 거부)
cd $Wt
$UndoReady = $WtOk -and $CodeOk -and (Test-Path $env:EOS194_STATE)
"UNDO_READY=$UndoReady · WT_OK=$WtOk CODE_OK=$CodeOk STATE_FILE=" + (Test-Path $env:EOS194_STATE)
if ($UndoReady) { $UndoLines = & $Py "$Wt\docs\reviews\eos194_acceptance3_2026-10-31\eos194_measure.py" deprecate; $UndoExit = $LASTEXITCODE; $UndoLines; "UNDO_EXIT=$UndoExit" } else { $UndoExit = -1; "WRITE_REFUSED=True — WT_OK=$WtOk CODE_OK=$CodeOk STATE_FILE=" + (Test-Path $env:EOS194_STATE) + " · 발행 상태 파일이 있어야 되돌립니다" }
```

**확인**: `UNDO_OK=True` · `POINTER_AFTER_UNDO=None`.

### [H] 임시 worktree 정리

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · H 임시 worktree 정리
cd C:\Users\kiki\Desktop\__AI\WhyMath
if ($Wt -and ($Wt -like "C:\Users\kiki\Desktop\__AI\WhyMath_wt_*") -and (Test-Path $Wt)) { git worktree remove --force $Wt; "WT_REMOVE_EXIT=$LASTEXITCODE" } else { "WT_REMOVE_SKIPPED=True — WT=$Wt (WhyMath_wt_ 로 시작하는 폴더만 지웁니다)" }
"WT_REMOVED=" + (-not (Test-Path $Wt))
"OUT_DIR_KEPT=$OutDir"
```

---

## 7. 이 문서가 검증한 것과 못 한 것

- **검증함**(이 PR의 세션 · 로컬 PostgreSQL 16 · 운영 아님): 운영 모사 DB(2,563행 · 힌트 4,147)에서 `preflight`가 힌트 붙은 979건을
  **전부** 검사(`SCANNED=979 · SCAN_TRUNCATED=False`)하고 `PUBLISHABLE=0 · {"misconception_signature": 979}`를 냈다(스킬·오개념
  카탈로그 적재 후). 종전 스크립트는 앞 300건만 봐서 0건이 "없음"인지 "잘림"인지 구분하지 못했다.
- **검증 못 함**: 운영 DB의 실제 후보 수 · PowerShell 블록 실행(형식은 `check_runbook_blocks.py`가 정적 검사 — 이 PR에서 측정
  스크립트의 `publish`·`deprecate` 모드를 쓰기로 인식하게 했다) · 백업 복원.
