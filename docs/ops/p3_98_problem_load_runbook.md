# P3-98 — 운영 DB 핵심 개념 문항은행 적재 (Kiki 실행 런북)

> 판정 기준: main `37e32712` (2026-11-03 · P3-32 힌트 런북 PR #1830 병합) + 이 런북의 PR.
>
> 태스크 `P3-98-core-bank-prod-problem-load`. 운영 DB에 핵심 개념 문항이 없어 P3-32 힌트 연결이 2/10에서
> 멈춘 것을 푼다. 이 런북이 쓰는 읽기 전용 프로브 `scripts/ops/p3_98_problem_load_probe.py`는 **이 PR이
> 병합돼야 `origin/main`에 있다.** 병합 전에 [B]를 돌리면 `WT_OK=False`로 거부된다.
>
> **이 문서가 실행으로 검증한 것과 못 한 것은 §9에 따로 적었다.**

---

## 1. 과제 명칭

운영 DB 핵심 개념 문항은행 적재 — 문항은행 2개(`p3_calculus1_diff_v0` 504문항 · `p3_fill_v0` 204문항)를
운영 DB `problem` 표에 넣어, 대표 과정 핵심 개념 10종 모두에 운영 DB 문항이 있게 만든다.

## 2. 목적

P3-32 힌트 런북을 2026-11-03에 Kiki 머신에서 실행한 결과([C] 실측 · main `37e32712`), 운영 DB `problem`
1,703행 안에 핵심 개념 적격 문항이 1,121건 중 **228건**(02-01 88 · 02-07 140)뿐이었고 나머지 **8개 개념은
0건**이었다. 힌트는 문항 행이 있어야 붙으므로 그 8개 개념은 힌트 런북을 몇 번 돌려도 연결되지 않는다.

이 런북은 그 8개 개념의 문항이 들어 있는 최소 은행 조합만 넣는다.

| 은행 | 문항 | 채우는 개념 |
|---|---:|---|
| `p3_calculus1_diff_v0` | 504 | 02-03 · 02-04 · 02-05 · 02-06 · 02-08 · 02-09 · 02-10 |
| `p3_fill_v0` | 204 | 02-02(이 은행이 유일) · 02-01 · 02-03 · 02-07 · 02-10 보강 |

다른 은행(`rephrased_v0`·`conceptual_v0`·`misconception_mc_v0`)은 10/10에 필요하지 않아 넣지 않는다 —
**학생 노출 문항 집합의 변화를 최소로** 한다. 적재 결정은 Kiki가 2026-11-03에 내렸다("문항은행 운영 DB 적재
런북 만들어줘").

**적재된 문항은 학생에게 노출될 수 있다.** 두 은행 708문항은 모두 검수 승인 상태라 서빙 후보 풀에 들어간다.

결과는 두 곳에 쓰인다. ① 운영 DB `problem`·`problem_concept`·`content_provenance`·`problem_relation`에 행이
생긴다 ② 이어서 P3-32 힌트 런북을 다시 돌리면 그 [C]가 `VERDICT=READY`(10개 개념 재생 가능)를 내고, 힌트
연결이 10/10까지 갈 수 있다.

## 3. 구체적 절차

| 단계 | 무엇이 일어나는가 | DB 쓰기 | 기대 출력(판정값) |
|---|---|---|---|
| A | Docker Desktop·`whymath-pg` 기동 확인 | 없음 | `DOCKER_OK=True` |
| B | main 기준 임시 worktree 생성(공유 클론 무변경) | 없음 | `WT_OK=True` · `CLONE_HEAD_UNCHANGED=True` |
| C | 환경 주입 · 코드 출처 · DB 도달 · **적재 전 실측**(BEFORE) | 없음 | `CODE_OK=True` · `REACH_EXIT=0` · `VERDICT=READY` · `BEFORE_OK=True` |
| D | 쓰기 대상 4개 표 백업(되돌리기용 사본) | 없음(파일만 생성) | `BACKUP_OK=True` |
| E | 적재 확인 입력(`APPLY` 한 단어) | 없음 | — |
| F | **문항 적재** — 은행 2개를 하나씩 | **있음** | `LOAD_OK=True` |
| G | **적재 후 실측**(AFTER) · 예측 대조 · P3-32 인계 확인 | 없음 | `LOAD_VERIFIED=True` · `HANDOFF_VERDICT=READY` |
| H | 임시 worktree 정리 | 저장소 밖 폴더만 | `WT_REMOVED=True` |

**소요 시간**: 샌드박스(로컬 PG)에서 [F] 적재는 은행마다 1분 이내였다. [C]·[G]의 프로브는 각각 1분 안팎이다.

**쓰기는 [F]에서만 일어난다.** 적재기는 `slug` 기준 멱등 upsert라 다시 돌려도 행이 늘지 않는다(이미 있는
행은 갱신, CMS로 고친 행·발행 판이 있는 행은 건드리지 않고 건너뛴다).

**적재 전에 멈추는 두 상태** — [C]의 프로브가 세고, 하나라도 있으면 `VERDICT=BLOCKED`로 [F]가 거부된다.

| 상태 | 뜻 | 왜 멈추는가 |
|---|---|---|
| `PK_COLLISION` | 코퍼스의 `problem_id`가 DB에 **다른 slug로** 이미 있다 | 적재기는 slug로만 충돌을 처리한다 — 이 행이 기본키 위반으로 그 은행 파일 전체를 롤백시킨다 |
| `ID_DRIFT` | 같은 slug가 DB에 **다른 `problem_id`로** 있다 | 적재기는 기존 ID를 보존하므로 그 문항은 코퍼스 ID로 생기지 않는다 — 힌트·계측기는 코퍼스 ID로 찾는다 |
| `SRC_UNRESOLVED` | 문항의 개념 태그가 DB의 개념 행으로 해석되지 않는다 | 문항은 들어가도 개념 연결(`problem_concept`)이 빠진다(원자 백본 미적재) |

## 4. 성공 기준

[G]가 `LOAD_VERIFIED=True`와 `HANDOFF_VERDICT=READY`를 내면 성공이다.

| 판정값 | 뜻 |
|---|---|
| `LOAD_OK=True` | 두 은행 적재 명령이 모두 종료 코드 0으로 끝났다 |
| `LOAD_VERIFIED=True` | 적재 후 실측이 **적재 전 예측과 정확히 같다**: 문항 행 증가 = 적재 전 `NEW_ROWS` · 남은 `NEW_ROWS=0` · 적재 후 `ELIGIBLE_IN_DB` = 적재 전 `PREDICTED_ELIGIBLE_IN_DB` · 적재 후 `CONCEPTS_IN_DB` = 적재 전 `PREDICTED_CONCEPTS_IN_DB` |
| `HANDOFF_VERDICT=READY` | P3-32 힌트 런북의 프로브가 10개 개념 모두 재생 가능하다고 본다 — 다음 단계(힌트 런북 재실행) 준비 완료 |

### 샌드박스 수치와 어떻게 대조하는가

샌드박스(로컬 PG · 운영과 비슷하게 `generated_v0` 619문항만 넣은 DB)에서 같은 프로브가 낸 값이다. 운영 DB는
문항이 1,703행이라 **절대 수는 다르다** — 대조할 것은 **차이**(NEW_ROWS 708 · 개념 2 → 10)다.

| 키 | 샌드박스 적재 전 | 샌드박스 적재 후 |
|---|---:|---:|
| `DB_PROBLEM_ROWS` | 619 | 1,327 |
| `NEW_ROWS` | 708 | 0 |
| `PK_COLLISION` · `ID_DRIFT` · `SRC_UNRESOLVED` | 0 · 0 · 0 | 0 · 0 · 0 |
| `ELIGIBLE_IN_DB` | 180 | 888 |
| `PREDICTED_ELIGIBLE_IN_DB` | 888 | 888 |
| `CONCEPTS_IN_DB` | 2 | 10 |
| `VERDICT` | `READY` | `DONE` |

| 관측 | 해석 | 다음 행동 |
|---|---|---|
| `VERDICT=DONE` | 두 은행이 이미 모두 들어 있다 | 적재하지 않는다(이후 쓰기 블록이 거부한다). [G]만 돌려 인계 판정을 본다 |
| `VERDICT=BLOCKED` | `BLOCK_REASONS`에 적힌 사유가 있다 | **적재하지 않는다.** [C] 출력 전체를 전달 |
| `NEW_ROWS`가 708보다 작고 `PRESENT_ROWS`가 0보다 큼 | 일부는 이미 들어 있다 | 정상이다. 진행 |
| `PROTECTED`가 0보다 큼 | 이미 있는 행 중 CMS 편집·발행 판 행 — 적재기가 건너뛴다 | 정상이다. 값만 전달 |

## 5. 실행 환경

- **머신**: Phaiakes9(= Kiki의 작업 PC 그 자체 · 별도 접속 없음)
- **시스템**: Windows PowerShell (WSL 아님)
- **작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath` (블록이 스스로 `cd`한다)
- **선행 조건**: ① 이 PR이 main에 병합됨 ② Docker Desktop 실행 가능, `whymath-pg`(호스트 포트 **5433**)
  ③ `src\backend\.venv`(Python 가상환경)가 이미 세팅돼 있음 ④ 디스크 여유(임시 worktree + 백업 파일)
- **DB**: prod = docker `whymath-pg`(5433, trust, user/db=`whymath`). 데모용 55432·타 프로젝트 5432와
  혼동 금지.
- **코드 출처**: 공유 작업 사본의 브랜치·미커밋 변경과 **무관하게**, main의 사본(임시 worktree
  `WhyMath_wt_<main 해시>`)에서 실행한다. 클론의 체크아웃을 옮기지 않는다.
- **증거 폴더**: 실행할 때마다 **새 폴더**(`work\p3_98_<main 해시>_<실행 시각>`)를 만든다. 지난 실행의 파일을
  이번 결과로 잘못 읽지 않게 하기 위해서다(2026-11-03 P3-32 실행에서 지난 실행의 `replay.json`이 화면에
  다시 나온 일이 있었다).

## 6. 창 구분

**전 단계가 새 PowerShell 창 하나에서 끝난다.** 서버를 띄우지 않으므로 점유되는 창이 없다. 블록 사이에
**같은 창을 유지**해야 한다 — 뒤 블록이 앞 블록의 변수(`$Wt`·`$Py`·`$BackupOk` 등)를 읽는다. 창을 닫았거나
변수가 없으면 쓰기 블록은 **스스로 거부**한다(`WRITE_REFUSED=True`).

---

## 실행 블록

> 자리표시자가 하나도 없다. **블록 하나씩** 붙여넣고, 각 블록 끝의 판정값을 확인한 다음에 넘어간다.
> 쓰기 블록 [F]는 눈 확인에 기대지 않고 **선행 판정을 스스로 다시 검사해 거부**한다. [E]는 한 줄짜리
> 블록이며 **혼자** 붙여넣는다.

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

**확인**: `DOCKER_OK=True` · `docker ps` 줄에 `Up …` + `0.0.0.0:5433->5432/tcp`. `False`면 멈추고 출력 전체를
전달한다.

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
$BankRel = @("data/corpus/problem_bank_p3_calculus1_diff_v0/problems.jsonl", "data/corpus/problem_bank_p3_fill_v0/problems.jsonl")
$HasLoadProbe = (Test-Path "$Wt\scripts\ops\p3_98_problem_load_probe.py")
$HasLinkProbe = (Test-Path "$Wt\scripts\ops\p3_32_hint_link_probe.py")
$HasProblemsFlag = ((Get-Content "$Wt\src\backend\whymath_backend\l1\problem_bank\populate.py" -Raw) -match '"--problems"')
$BanksPresent = (@($BankRel | Where-Object { -not (Test-Path ("$Wt\" + ($_ -replace '/', '\'))) }).Count -eq 0)
$WtOk = ($WtHead -eq $MainSha) -and $WtClean -and $HasLoadProbe -and $HasLinkProbe -and $HasProblemsFlag -and $BanksPresent
"MAIN_SHA=$MainSha · WT_HEAD=$WtHead · WT_CLEAN=$WtClean · LOAD_PROBE=$HasLoadProbe · LINK_PROBE=$HasLinkProbe · PROBLEMS_FLAG=$HasProblemsFlag · BANKS_PRESENT=$BanksPresent · WT_OK=$WtOk"
"CLONE_HEAD_UNCHANGED=" + ((git rev-parse --short HEAD) -eq $CloneHead)
```

**확인**: `WT_OK=True` · `CLONE_HEAD_UNCHANGED=True`.

- `LOAD_PROBE=False`면 이 PR이 아직 main에 없다 — 병합 후 다시 시작한다.
- `WT_EXISTS=True`로 재사용한 폴더는 `WT_CLEAN=True`가 아니면 거부된다(이전 실행의 흔적 방어).

### [C] 환경 · 코드 출처 · DB 도달 · 적재 전 실측 (읽기 전용)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · C 환경 + BEFORE 실측 (읽기 전용)
cd $Wt
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$env:PYTHONPATH = "$Wt\src\backend"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$LoadProbe = "$Wt\scripts\ops\p3_98_problem_load_probe.py"
$LinkProbe = "$Wt\scripts\ops\p3_32_hint_link_probe.py"
$Stamp = Get-Date -Format "yyyyMMddHHmmss"
$OutDir = "C:\Users\kiki\Desktop\__AI\WhyMath\work\p3_98_" + $MainSha + "_" + $Stamp
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
"OUT_DIR=$OutDir · OUT_DIR_FRESH=" + (@(Get-ChildItem $OutDir).Count -eq 0)
function Get-KvMap([string[]]$Lines) { $Map = @{}; foreach ($L in $Lines) { if ($L -match '^([A-Z0-9_]+)=(.*)$') { $Map[$Matches[1]] = $Matches[2].Trim() } }; return $Map }
function Get-KvInt($Map, [string]$Key) { $V = $Map[$Key]; if ($null -ne $V -and $V -match '^-?\d+$') { return [int]$V } else { return -1 } }
$ProbeArgs = @("measure")
foreach ($R in $BankRel) { $ProbeArgs += @("--bank", $R) }
"PY_OK=" + (Test-Path $Py)
& $Py -m whymath_backend.ops.db_host_reachability
$ReachExit = $LASTEXITCODE
"REACH_EXIT=$ReachExit"
$BeforeLines = & $Py $LoadProbe @ProbeArgs
$MeasureExit = $LASTEXITCODE
$BeforeLines
"MEASURE_EXIT=$MeasureExit"
$BeforeMap = Get-KvMap $BeforeLines
if ($BeforeLines) { [IO.File]::WriteAllLines("$OutDir\before.kv", [string[]]$BeforeLines); "EVIDENCE_SAVED=$OutDir\before.kv" } else { "EVIDENCE_NOT_SAVED=True — 프로브 출력이 비었습니다" }
$CodeOk = ([bool]$BeforeMap["CODE_POPULATE"]) -and ($BeforeMap["CODE_POPULATE"] -like "$Wt\*") -and ($BeforeMap["CODE_PHASE3"] -like "$Wt\*") -and ($BeforeMap["CODE_PROBE"] -like "$Wt\*")
$Verdict = $BeforeMap["VERDICT"]
$BeforeOk = ($MeasureExit -eq 0) -and ($Verdict -ceq "READY") -and ((Get-KvInt $BeforeMap "NEW_ROWS") -gt 0) -and ((Get-KvInt $BeforeMap "BANK_COUNT") -eq $BankRel.Count) -and ((Get-KvInt $BeforeMap "PK_COLLISION") -eq 0) -and ((Get-KvInt $BeforeMap "ID_DRIFT") -eq 0) -and ((Get-KvInt $BeforeMap "SRC_UNRESOLVED") -eq 0)
"VERDICT=$Verdict · NEW_ROWS=" + $BeforeMap["NEW_ROWS"] + " · PREDICTED_CONCEPTS_IN_DB=" + $BeforeMap["PREDICTED_CONCEPTS_IN_DB"] + " · BLOCK_REASONS=" + $BeforeMap["BLOCK_REASONS"]
"CODE_OK=$CodeOk · BEFORE_OK=$BeforeOk · REACH_EXIT=$ReachExit"
```

**확인**: `PY_OK=True` · `REACH_EXIT=0` · `MEASURE_EXIT=0` · `CODE_OK=True` · `VERDICT=READY` · `BEFORE_OK=True`.
출력된 `CODE_POPULATE`·`CODE_PHASE3`·`CODE_PROBE` 세 경로가 모두 `…\WhyMath_wt_<main 해시>\…`로 시작해야 한다.
`OUT_DIR_FRESH=True`여야 한다(이번 실행 전용 폴더).

| 값 | 실패 신호 | 대처 |
|---|---|---|
| `REACH_EXIT` | 1(도달 불가) 또는 2(측정 불가) | CLI가 출력하는 상태·대책을 따른다(`FOREIGN_LISTENER`면 5433을 다른 프로세스가 물고 있다 — 적재 금지, 출력 전달) |
| `VERDICT=BLOCKED` | `BLOCK_REASONS`의 사유(§3 표) | **적재하지 않는다**(이후 쓰기 블록이 거부한다). 출력 전체 전달 |
| `VERDICT=DONE` | 이미 다 들어 있다 | [D]~[F]는 거부된다. [G]만 돌려 인계 판정을 본다 |
| `MEASURE_EXIT=2` | 측정 실패(`PROBE_ERROR=` 줄) | 그 줄을 그대로 전달 |

이 블록의 **BEFORE 수치 전체**가 acceptance ④의 "적재 전" 실측이다. 화면 전체를 복사해 전달한다.

### [D] 쓰기 대상 4개 표 백업 (되돌리기용 사본 · DB는 읽기만)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · D 백업 (DB 읽기 전용 · 파일 생성)
cd $Wt
$BackupFile = "$OutDir\p3_98_before.dump"
$BackupReady = $WtOk -and $CodeOk -and $BeforeOk -and ($ReachExit -eq 0) -and ($Wt -notmatch '\s') -and ($OutDir -notmatch '\s')
"BACKUP_READY=$BackupReady · WT_OK=$WtOk CODE_OK=$CodeOk BEFORE_OK=$BeforeOk REACH_EXIT=$ReachExit"
if ($BackupReady) { docker exec whymath-pg pg_dump -U whymath -d whymath -t problem -t problem_concept -t content_provenance -t problem_relation -Fc -f /tmp/p3_98_before.dump; $DumpExit = $LASTEXITCODE; docker cp whymath-pg:/tmp/p3_98_before.dump $BackupFile; $CopyExit = $LASTEXITCODE; "DUMP_EXIT=$DumpExit · COPY_EXIT=$CopyExit" } else { $DumpExit = -1; $CopyExit = -1; "BACKUP_REFUSED=True — WT_OK=$WtOk CODE_OK=$CodeOk BEFORE_OK=$BeforeOk REACH_EXIT=$ReachExit · 전부 True/0이어야 백업합니다" }
$BackupBytes = 0
if (Test-Path $BackupFile) { $BackupBytes = (Get-Item $BackupFile).Length }
$TocLines = docker exec whymath-pg pg_restore -l /tmp/p3_98_before.dump
$ListExit = $LASTEXITCODE
$TocTables = @($TocLines | Where-Object { $_ -match 'TABLE DATA public (problem|problem_concept|content_provenance|problem_relation) ' }).Count
$BackupOk = $BackupReady -and ($DumpExit -eq 0) -and ($CopyExit -eq 0) -and ($BackupBytes -gt 0) -and ($ListExit -eq 0) -and ($TocTables -eq 4)
"BACKUP_BYTES=$BackupBytes · RESTORE_LIST_EXIT=$ListExit · TOC_TABLES=$TocTables · BACKUP_OK=$BackupOk"
```

**확인**: `DUMP_EXIT=0` · `COPY_EXIT=0` · `BACKUP_BYTES`가 0보다 큼 · `RESTORE_LIST_EXIT=0` · `TOC_TABLES=4` ·
`BACKUP_OK=True`. `BACKUP_OK`는 [F]의 가드가 다시 읽는다 — `False`면 적재가 거부된다.

이 백업은 **복원 명령을 이 문서가 검증하지 않았다**(§9). 파일이 생겼고 `pg_restore -l` 목차에 네 표가 모두
있다는 것까지만 확인한다.

### [E] 적재 확인 입력 (한 줄 블록 — 이 줄만 붙여넣는다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · E 적재 확인 입력 (이 블록만 혼자 붙여넣는다)
$Confirm = Read-Host "BEFORE 수치(VERDICT·NEW_ROWS)를 확인했다면 대문자 다섯 글자 APPLY 만 입력하고 Enter 키"
```

**이 블록은 위아래 어떤 줄과도 같이 붙여넣지 않는다.** 입력 대기 중에 뒤따라 붙여넣은 줄이 입력으로 먹히는
것을 막기 위해서다. 입력란에는 **`APPLY` 다섯 글자만** 친다(2026-11-03 P3-32 실행에서 `Enter`라는 글자가 입력돼
재생이 거부된 일이 있었다). `APPLY` 외의 입력이면 [F]가 거부한다 — 쓰기는 일어나지 않으니 [E]만 다시 붙여넣으면
된다.

### [F] 문항 적재 — 은행 2개를 하나씩 (여기서 처음 DB에 쓴다)

이 블록은 **[B]~[E]의 판정값을 스스로 다시 검사하고, 하나라도 미충족이면 실행을 거부한다.** 은행마다 적재
명령을 한 번 돌리고 출력을 은행별 로그 파일에 남긴다. 은행 하나는 한 트랜잭션이라, 실패한 은행은 통째로
롤백되고 앞서 성공한 은행은 남는다.

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · F 문항 적재 (쓰기 · 조건 미충족이면 스스로 거부)
cd $Wt
$ConfirmOk = ($Confirm -ceq "APPLY")
$LoadReady = $BackupOk -and $ConfirmOk -and $WtOk -and $CodeOk -and $BeforeOk -and ($ReachExit -eq 0)
"LOAD_READY=$LoadReady · BACKUP_OK=$BackupOk CONFIRMED=$ConfirmOk WT_OK=$WtOk CODE_OK=$CodeOk BEFORE_OK=$BeforeOk REACH_EXIT=$ReachExit"
$LoadExits = @()
if ($LoadReady) { $T0 = Get-Date; foreach ($R in $BankRel) { $Log = "$OutDir\load_" + (Split-Path (Split-Path $R -Parent) -Leaf) + ".log"; $LoadOut = & $Py -m whymath_backend.l1.problem_bank.populate --problems $R 2>&1 | ForEach-Object { "$_" }; $LoadExits += $LASTEXITCODE; [IO.File]::WriteAllLines($Log, [string[]]@($LoadOut)); "LOADED=$R · EXIT=$LASTEXITCODE · LOG=$Log" }; "LOAD_SEC=" + [int]((Get-Date) - $T0).TotalSeconds } else { "WRITE_REFUSED=True — BACKUP_OK=$BackupOk CONFIRMED=$ConfirmOk WT_OK=$WtOk CODE_OK=$CodeOk BEFORE_OK=$BeforeOk REACH_EXIT=$ReachExit · 전부 True/0이어야 적재합니다. [B]~[E]를 같은 창에서 순서대로 실행하세요" }
$Confirm = $null
Get-ChildItem "$OutDir\load_*.log" -ErrorAction SilentlyContinue | ForEach-Object { "--- " + $_.Name; Get-Content $_.FullName -Encoding UTF8 | Select-Object -Last 6 }
$LoadOk = ($LoadExits.Count -eq $BankRel.Count) -and (@($LoadExits | Where-Object { $_ -ne 0 }).Count -eq 0)
"LOAD_EXITS=" + ($LoadExits -join ",") + " · LOAD_OK=$LoadOk"
```

**확인**: `LOAD_READY=True` → 은행마다 `EXIT=0` → `LOAD_OK=True`. 로그 끝줄에 `문제 적재 완료: N건`(은행 문항 수)과
`개념 orphan skip: 0건`이 보여야 한다.

| 증상 | 뜻 | 대처 |
|---|---|---|
| `WRITE_REFUSED=True` | 선행 판정 하나가 False — **쓰기는 일어나지 않았다** | 같은 줄에 찍힌 값을 보고 해당 블록부터 같은 창에서 다시 |
| 어느 은행 `EXIT`가 0이 아님 | 그 은행 트랜잭션은 롤백됐다(앞 은행은 들어갔을 수 있다) | 멈추고 그 은행 로그(`load_….log`) 전체를 전달 |
| 로그에 `orphan skip`이 0이 아님 | 개념 연결 일부가 빠졌다([C]의 `SRC_UNRESOLVED=0`과 모순) | [G]까지 돌리고 함께 전달 |
| 로그에 `CMS 편집`·`발행` 충돌 줄 | 보호된 행을 건너뛰었다 | 정상이다. 값만 전달 |

### [G] 적재 후 실측 · 예측 대조 · P3-32 인계 확인 (읽기 전용)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · G AFTER 실측 + 예측 대조 + 인계 확인 (읽기 전용)
cd $Wt
$AfterLines = & $Py $LoadProbe @ProbeArgs
$AfterExit = $LASTEXITCODE
$AfterLines
$AfterMap = Get-KvMap $AfterLines
if ($AfterLines) { [IO.File]::WriteAllLines("$OutDir\after.kv", [string[]]$AfterLines); "EVIDENCE_SAVED=$OutDir\after.kv" }
$RowsDelta = (Get-KvInt $AfterMap "DB_PROBLEM_ROWS") - (Get-KvInt $BeforeMap "DB_PROBLEM_ROWS")
"BEFORE_AFTER 문항 행: " + $BeforeMap["DB_PROBLEM_ROWS"] + " -> " + $AfterMap["DB_PROBLEM_ROWS"] + " (증가 $RowsDelta · 예측 " + $BeforeMap["NEW_ROWS"] + ")"
"BEFORE_AFTER 적격 문항 DB 존재: " + $BeforeMap["ELIGIBLE_IN_DB"] + " -> " + $AfterMap["ELIGIBLE_IN_DB"] + " (예측 " + $BeforeMap["PREDICTED_ELIGIBLE_IN_DB"] + ")"
"BEFORE_AFTER 문항 있는 개념: " + $BeforeMap["CONCEPTS_IN_DB"] + " -> " + $AfterMap["CONCEPTS_IN_DB"] + "/" + $AfterMap["CONCEPTS"] + " (예측 " + $BeforeMap["PREDICTED_CONCEPTS_IN_DB"] + ")"
$LoadVerified = ($AfterExit -eq 0) -and ($RowsDelta -eq (Get-KvInt $BeforeMap "NEW_ROWS")) -and ((Get-KvInt $AfterMap "NEW_ROWS") -eq 0) -and ((Get-KvInt $AfterMap "ELIGIBLE_IN_DB") -eq (Get-KvInt $BeforeMap "PREDICTED_ELIGIBLE_IN_DB")) -and ((Get-KvInt $AfterMap "CONCEPTS_IN_DB") -eq (Get-KvInt $BeforeMap "PREDICTED_CONCEPTS_IN_DB"))
"LOAD_VERIFIED=$LoadVerified"
$HandoffLines = & $Py $LinkProbe link
$HandoffExit = $LASTEXITCODE
if ($HandoffLines) { [IO.File]::WriteAllLines("$OutDir\handoff_link.kv", [string[]]$HandoffLines) }
$HandoffMap = Get-KvMap $HandoffLines
"HANDOFF_EXIT=$HandoffExit · HANDOFF_ELIGIBLE_IN_DB=" + $HandoffMap["ELIGIBLE_IN_DB"] + " · HANDOFF_REPLAYABLE_IN_DB=" + $HandoffMap["REPLAYABLE_IN_DB"] + " · HANDOFF_CONCEPTS_REPLAYABLE=" + $HandoffMap["CONCEPTS_REPLAYABLE"]
"HANDOFF_VERDICT=" + $HandoffMap["VERDICT"]
"JUDGED_AGAINST_MAIN=$MainSha · OUT_DIR=$OutDir"
```

**확인**: `LOAD_VERIFIED=True` · `HANDOFF_VERDICT=READY` · `HANDOFF_CONCEPTS_REPLAYABLE=10`.

- `LOAD_VERIFIED=False`면 적재 결과가 적재 전 예측과 다르다. 그 사이 다른 쓰기가 있었거나(다른 세션의 적재 등)
  보호 행이 건너뛰어진 것이다. 위 세 `BEFORE_AFTER` 줄과 [F] 로그를 함께 전달한다.
- `HANDOFF_VERDICT=PARTIAL`이면 문항은 들어갔지만 재생 가능한 문항이 없는 개념이 남았다 — `handoff_link.kv`의
  `CONCEPT_Cnn_REPLAYABLE_IN_DB=0` 줄을 전달한다.

이 블록의 **전후 수치 전체**가 acceptance ④의 증거다.

**다음 단계**: `HANDOFF_VERDICT=READY`면 이 창을 닫지 말고 [H]로 정리한 뒤, `docs/ops/p3_32_hint_link_runbook.md`를
**[A]부터 새로** 실행한다(그 런북의 [C]가 `VERDICT=READY`·`CONCEPTS_REPLAYABLE=10`을 내야 한다).

### [H] 임시 worktree 정리 (저장소 밖 폴더만 지운다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · H 임시 worktree 정리
cd C:\Users\kiki\Desktop\__AI\WhyMath
if ($Wt -and ($Wt -like "C:\Users\kiki\Desktop\__AI\WhyMath_wt_*") -and (Test-Path $Wt)) { git worktree remove --force $Wt; "WT_REMOVE_EXIT=$LASTEXITCODE" } else { "WT_REMOVE_SKIPPED=True — WT=$Wt (WhyMath_wt_ 로 시작하는 폴더만 지웁니다)" }
"WT_REMOVED=" + (-not (Test-Path $Wt))
"OUT_DIR_KEPT=$OutDir"
```

**확인**: `WT_REMOVED=True`. 증거 폴더 `work\p3_98_<main 해시>_<실행 시각>`(백업·kv·로그)는 남는다.

---

## 7. 전달할 것

[C]·[F]·[G] 화면 전체. 특히 `VERDICT`·`NEW_ROWS`·`BLOCK_REASONS`·`LOAD_OK`·`LOAD_VERIFIED`·
`HANDOFF_VERDICT`·`HANDOFF_CONCEPTS_REPLAYABLE` 줄.

## 8. 범위 밖

- **힌트 생성**: 이 런북은 문항 행만 넣는다. 힌트는 P3-32 힌트 런북(`docs/ops/p3_32_hint_link_runbook.md`)을 다시
  실행해 만든다.
- **다른 은행**(`rephrased_v0`·`conceptual_v0`·`misconception_mc_v0` 등): 핵심 개념 10/10에 필요하지 않아 넣지
  않는다. 노출 문항을 더 늘릴지는 별도 결정이다.
- **되돌리기**: [D]의 백업 파일이 있지만, 복원 명령은 이 문서가 검증하지 않았으므로 싣지 않는다. 되돌려야 하면
  세션에 요청한다(적재로 생긴 행만 골라 지우는 절차를 따로 만들어 검증한다).

## 9. 이 문서가 검증한 것과 못 한 것

**실행으로 검증한 것**(이 PR의 세션 · 로컬 PostgreSQL 16 + pgvector · 운영 아님 · 운영과 비슷하게 성취기준·원자
백본·`generated_v0` 619문항만 넣은 DB):
- 프로브 `measure`가 적재 전 `NEW_ROWS=708 · PK_COLLISION=0 · ID_DRIFT=0 · SRC_UNRESOLVED=0 ·
  PREDICTED_CONCEPTS_IN_DB=10 · VERDICT=READY`를 냈다.
- 적재 명령(`l1.problem_bank.populate --problems`)을 두 은행에 돌린 결과(504건·204건 · orphan skip 0)가 예측과
  **정확히** 같았다: 문항 행 619 → 1,327(+708) · `ELIGIBLE_IN_DB` 180 → 888 · `CONCEPTS_IN_DB` 2 → 10 ·
  적재 후 `VERDICT=DONE`.
- 적재 후 P3-32 프로브 `link`가 `CONCEPTS_REPLAYABLE=10 · VERDICT=READY`를 냈다.
- 같은 DB에서 P3-32 런북의 쓰기 단계(재생 `--only-existing-problems` → 승격 `--apply` → 힌트 `--apply`)를 이어
  돌리자 프로브 `link`가 `CONCEPTS_HINT_LINKED=10 · WITH_VERIFIED_HINT=686`을 냈다 — 이 런북 다음에 P3-32
  런북을 돌리면 10/10에 닿는다는 것을 운영과 같은 순서로 확인했다.
- 프로브의 분류 함수가 기본키 충돌·ID 이탈·보호 행을 각각 세고 판정을 `BLOCKED`로 내리는 것을 단위 테스트가
  확인한다(`tests/infra/test_p3_98_problem_load_runbook.py`).

**검증하지 못한 것**:
- **PowerShell 블록 자체는 실행하지 못했다**(세션은 Linux다). 블록의 형식(가드·자리표시자·펜스)은
  `scripts/ops/check_runbook_blocks.py`와 `tests/infra/test_p3_98_problem_load_runbook.py`가 정적으로 검사한다.
- **운영 DB의 기본키 충돌·ID 이탈 여부**: 모른다. 이 런북의 [C]가 처음 잰다.
- **백업 복원**: 복원 명령을 실행해 보지 않았다.
