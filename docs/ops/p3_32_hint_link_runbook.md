# P3-32 — 운영 DB 핵심 개념 힌트 연결 (Kiki 실행 런북)

> 판정 기준: main `d92b3b50` (2026-11-02 · P3-95 PR #1828 병합) + 이 런북의 PR.
>
> 태스크 `P3-32`의 acceptance ③(핵심 개념 10종 승인 문항에 hint를 채워 `phase3_coverage` hint linked 10/10)을
> **운영 DB에서** 이행하는 Kiki 머신용 실행 절차다. 이 런북이 쓰는 두 가지 —
> 읽기 전용 프로브 `scripts/ops/p3_32_hint_link_probe.py`와 재생 옵션 `corpus_replay --only-existing-problems` —
> 는 **이 PR이 병합돼야 `origin/main`에 있다.** 병합 전에 [B]를 돌리면 `WT_OK=False`로 거부된다.
>
> **이 문서가 실행으로 검증한 것과 못 한 것은 §9에 따로 적었다.** 못 한 것을 한 것처럼 읽지 않는다.

---

## 1. 과제 명칭

운영 DB 핵심 개념 힌트 연결 — 대표 과정 핵심 개념 10종(12미적Ⅰ-02-01 ~ 02-10)의 승인 문항에 검증된
풀이 경로와 힌트를 적재해, 운영 DB 기준 `phase3_coverage --hints-from-db`의 hint 연결을 0/10에서 끌어올린다.

## 2. 목적

운영 DB에는 핵심 개념 문항의 검증 힌트가 한 건도 없다(P3-42 실측 2026-10-16: hint linked 0/10 · EOS-194 실측
2026-10-31: 노출 문항 1,699건 중 검증 힌트 0건). 원인은 힌트를 만드는 원천 경로(코퍼스 풀이 단계 → 재생 →
풀이 경로 승격 → 힌트 생성)가 세 곳에서 끊겨 있었기 때문이고, 셋 다 코드로 고쳐졌다.

| 끊긴 곳 | 고친 PR |
|---|---|
| 풀이 경로 승격이 외래 키 순서 버그로 전체 롤백 | #1801 (P3-32 · P3-96) |
| 재생 풀이 1,507건의 풀이 유형 미정 → 승격 0건 | 게이트 A안 · P3-96 |
| 12미적Ⅰ-02-09(실근 개수) 재생 39건 전부 거부 | #1828 (P3-95) |

샌드박스(로컬 PG · 문항 15,042행)에서는 이 경로로 hint linked **10/10**에 닿았다
(`docs/reviews/p3_95_count_answer_finalize_2026-11-02.md`). 운영 DB는 문항이 **1,703행뿐**이라, 같은 결과가
나오는지는 **적격 문항이 운영 DB에 같은 ID로 있는가**에 달려 있다. 이 런북은 그것을 쓰기 전에 재고, 없으면
쓰지 않는다.

결과는 세 곳에 쓰인다. ① 운영 DB의 `verified_solutions`·`solution_paths`·`problem_step`·`hints`에 행이 생긴다
② 전후 수치가 P3-32 acceptance ③·④의 증거가 된다 ③ EOS-194 acceptance ③(문항 1건 실제 발행)의 선행이
풀린다 — 발행 게이트가 요구하는 7필드 중 `hint_strategy`가 채워진다.

## 3. 구체적 절차

| 단계 | 무엇이 일어나는가 | DB 쓰기 | 기대 출력(판정값) |
|---|---|---|---|
| A | Docker Desktop·`whymath-pg` 기동 확인 | 없음 | `DOCKER_OK=True` |
| B | main 기준 임시 worktree 생성(공유 클론 무변경) | 없음 | `WT_OK=True` · `CLONE_HEAD_UNCHANGED=True` |
| C | 환경 주입 · 코드 출처 · DB 도달 · **적재 전 실측**(BEFORE) | 없음 | `CODE_OK=True` · `REACH_EXIT=0` · `BEFORE_OK=True` · `VERDICT=READY` 또는 `PARTIAL` |
| D | 쓰기 대상 5개 표 백업(되돌리기용 사본) | 없음(파일만 생성) | `BACKUP_OK=True` |
| E | 적재 확인 입력(`APPLY` 한 단어) | 없음 | — |
| F | **재생** — DB에 있는 문항만(`--only-existing-problems`) | **있음** | `REPLAY_OK=True` |
| G | 풀이 경로 승격 — 시험 실행 후 적재 | **있음** | `PROMO_OK=True` |
| H | 힌트 생성 — 시험 실행 후 적재 | **있음** | `HINTS_OK=True` |
| I | **적재 후 실측**(AFTER) · 계측기 · 정답 누설 판정 | 없음 | `LINK_OK=True` · `LEAK_CHECK_OK=True` |
| J | 임시 worktree 정리 | 저장소 밖 폴더만 | `WT_REMOVED=True` |

**소요 시간은 운영 규모로는 실측하지 못했다.** 샌드박스(이 PR의 세션 컨테이너)에서 같은 단계를 전 문항
15,042행 기준으로 돌렸을 때 재생 14개 은행이 약 25분, 승격 약 1분, 힌트 생성 약 2분이었다. 운영 DB는 문항이
적어 재생 대상이 그보다 적다([C]의 `REPLAYABLE_IN_DB`가 대상 수다). 첫 실행의 [F]~[H] 소요 시간을 기록해
전달해 달라.

**쓰기는 [F]·[G]·[H]에서만 일어난다.** 셋 다 다시 돌려도 안전하다.
- 재생은 같은 풀이를 다시 찾으면 기존 행을 재사용한다(`dedup` — 샌드박스 실측).
- 승격은 이미 승격된 경로를 건너뛴다(`already_promoted`).
- 힌트 생성은 같은 입력이면 `unchanged`이고 행을 삭제하지 않는다(P3-81 실측).

**운영 DB에 없는 문항은 재생하지 않는다.** `verified_solutions.problem_id`는 외래 키가 아니라서, 없는 문항을
재생하면 가리킬 문항이 없는 풀이 행이 쌓인다. [F]는 `--only-existing-problems`로 그 행을 만들지 않고, 건너뛴
수를 `REPLAY_SKIPPED_MISSING`으로 보고한다.

## 4. 성공 기준

[I]가 `LINK_OK=True`와 `LEAK_CHECK_OK=True`를 내면 성공이다.

| 판정값 | 뜻 |
|---|---|
| `REPLAY_OK=True` | 재생이 끝났고 대상 전건이 verified다(`REPLAY_OTHER=0` · 실패 0) |
| `PROMO_OK=True` | 승격 적재가 끝났고 형식 거부 0건(`PROMO_PYDANTIC_REJECTED=0`) |
| `HINTS_OK=True` | 힌트 적재가 끝났고 생성된 모든 힌트가 값 축 판정을 받았으며 CMS 충돌 0건 |
| `LINK_OK=True` | 적재 후 **힌트가 붙은 개념 수 == 적재 전 재생 가능 개념 수**(`CONCEPTS_HINT_LINKED` == BEFORE `CONCEPTS_REPLAYABLE`) |
| `LEAK_CHECK_OK=True` | 서빙 경로 표본·검수 통과 L3 전수에 정답 누설 판정 0건(P3-81 프로브 재사용) |

**`LINK_OK=True`가 곧 10/10은 아니다.** [C]의 `VERDICT`가 `PARTIAL`이면 재생 가능한 문항이 DB에 없는 개념이
있다는 뜻이고, 그 개념은 이 런북으로 linked가 될 수 없다. 이 런북은 그 수를 **모르는 척 넘기지 않고** 끝에
`HINT_LINKED_CONCEPTS=n/10`으로 그대로 낸다. 10/10이 아니면 P3-32는 done이 아니다 — 남은 개념은 문항 적재
(운영 DB에 그 문항 행을 넣는 일)가 선행이며, 그것은 이 런북의 범위가 아니다(§8).

### 샌드박스 수치와 어떻게 대조하는가

샌드박스(문항 15,042행 · 전 코퍼스 적재)에서 같은 프로브가 낸 값이다. 운영 DB는 모집단이 다르므로 **일치
여부가 합격 기준이 아니다.**

| 키 | 샌드박스 |
|---|---:|
| `ELIGIBLE` | 1,121 |
| `ELIGIBLE_IN_DB` | 1,121 |
| `REPLAYABLE_IN_DB` | 847 |
| `CONCEPTS_REPLAYABLE` | 10 |
| `WITH_VERIFIED_HINT`(적재 후) | 847 |
| `CONCEPTS_HINT_LINKED`(적재 후) | 10 |
| `REPLAY_BANK_COUNT` | 5 |

| 관측 | 해석 | 다음 행동 |
|---|---|---|
| `ELIGIBLE_IN_DB=0` | 운영 DB에 핵심 개념 적격 문항이 하나도 없다(ID 공간 불일치이거나 미적재) | [C]에서 멈춘다(`VERDICT=NONE` → 쓰기 거부). 출력 전체 전달 |
| `ELIGIBLE_IN_DB`가 1,121보다 훨씬 작다 | 운영 DB에 코퍼스 일부만 적재돼 있다 | `VERDICT`대로 진행하되, 개념별 `CONCEPT_Cnn_REPLAYABLE_IN_DB`가 0인 개념을 전달 |
| `ELIGIBLE_IN_DB`는 크지만 `REPLAYABLE_IN_DB`가 0 | 적격 문항은 있으나 풀이 단계를 가진 문항이 없다 | 쓰기 거부. 출력 전달 |

## 5. 실행 환경

- **머신**: Phaiakes9(= Kiki의 작업 PC 그 자체 · 별도 접속 없음)
- **시스템**: Windows PowerShell (WSL 아님)
- **작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath` (블록이 스스로 `cd`한다)
- **선행 조건**: ① 이 PR이 main에 병합됨 ② Docker Desktop 실행 가능, `whymath-pg`(호스트 포트 **5433**)
  ③ `src\backend\.venv`(Python 가상환경)가 이미 세팅돼 있음 ④ 디스크 여유(임시 worktree + 백업 파일)
- **DB**: prod = docker `whymath-pg`(5433, trust, user/db=`whymath`). 데모용 55432·타 프로젝트 5432와
  혼동 금지.
- **코드 출처**: 공유 작업 사본(`C:\Users\kiki\Desktop\__AI\WhyMath`)의 브랜치·미커밋 변경과 **무관하게**,
  main의 사본(임시 worktree `WhyMath_wt_<main 해시>`)에서 실행한다. 클론의 체크아웃을 옮기지 않는다.

## 6. 창 구분

**전 단계가 새 PowerShell 창 하나에서 끝난다.** 서버(uvicorn)를 띄우지 않으므로 점유되는 창이 없다. 블록 사이에
**같은 창을 유지**해야 한다 — 뒤 블록이 앞 블록의 변수(`$Wt`·`$Py`·`$BackupOk` 등)를 읽는다. 창을 닫았거나
변수가 없으면 쓰기 블록은 **스스로 거부**한다(`WRITE_REFUSED=True`).

---

## 실행 블록

> 자리표시자가 하나도 없다. **블록 하나씩** 붙여넣고, 각 블록 끝의 판정값을 확인한 다음에 넘어간다.
> 단 쓰기 블록 [F]·[G]·[H]는 눈 확인에 기대지 않고 **선행 판정을 스스로 다시 검사해 거부**한다 — 출력은 흐름을
> 멈추지 못한다(2026-09-15 실측). [E]는 한 줄짜리 블록이며 **혼자** 붙여넣는다.

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
전달한다(이후 블록은 전부 거부되거나 실패한다).

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
$HasLinkProbe = (Test-Path "$Wt\scripts\ops\p3_32_hint_link_probe.py")
$HasHintProbe = (Test-Path "$Wt\scripts\ops\p3_81_hint_catalog_probe.py")
$HasExistingFlag = ((Get-Content "$Wt\src\backend\whymath_backend\whs\corpus_replay.py" -Raw) -match "only-existing-problems")
$HasCountAnswer = ((Get-Content "$Wt\src\backend\whymath_backend\whs\harness.py" -Raw) -match "claimed_answer")
$HasFamilyTable = ((Get-Content "$Wt\src\backend\whymath_backend\whs\path_promotion.py" -Raw) -match "CORPUS_REPLAY_APPROACH_BY_FAMILY")
$WtOk = ($WtHead -eq $MainSha) -and $WtClean -and $HasLinkProbe -and $HasHintProbe -and $HasExistingFlag -and $HasCountAnswer -and $HasFamilyTable
"MAIN_SHA=$MainSha · WT_HEAD=$WtHead · WT_CLEAN=$WtClean · LINK_PROBE=$HasLinkProbe · HINT_PROBE=$HasHintProbe · EXISTING_FLAG=$HasExistingFlag · COUNT_ANSWER=$HasCountAnswer · FAMILY_TABLE=$HasFamilyTable · WT_OK=$WtOk"
"CLONE_HEAD_UNCHANGED=" + ((git rev-parse --short HEAD) -eq $CloneHead)
```

**확인**: `WT_OK=True` · `CLONE_HEAD_UNCHANGED=True`.

- `LINK_PROBE=False` 또는 `EXISTING_FLAG=False`면 이 PR이 아직 main에 없다 — 병합 후 다시 시작한다.
- `COUNT_ANSWER=False`면 P3-95(#1828)가, `FAMILY_TABLE=False`면 P3-96이 main에 없다 — 그 상태로 적재하면
  02-09 문항 또는 재생 풀이 전체가 승격되지 않는다. 멈추고 `MAIN_SHA`와 함께 전달한다.
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
$LinkProbe = "$Wt\scripts\ops\p3_32_hint_link_probe.py"
$HintProbe = "$Wt\scripts\ops\p3_81_hint_catalog_probe.py"
$OutDir = "C:\Users\kiki\Desktop\__AI\WhyMath\work\p3_32_$MainSha"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
function Get-KvMap([string[]]$Lines) { $Map = @{}; foreach ($L in $Lines) { if ($L -match '^([A-Z0-9_]+)=(.*)$') { $Map[$Matches[1]] = $Matches[2].Trim() } }; return $Map }
function Get-KvInt($Map, [string]$Key) { $V = $Map[$Key]; if ($null -ne $V -and $V -match '^-?\d+$') { return [int]$V } else { return -1 } }
"PY_OK=" + (Test-Path $Py)
& $Py -m whymath_backend.ops.db_host_reachability
$ReachExit = $LASTEXITCODE
"REACH_EXIT=$ReachExit"
$BeforeLines = & $Py $LinkProbe link
$LinkExit = $LASTEXITCODE
$BeforeLines
"LINK_EXIT=$LinkExit"
$BeforeMap = Get-KvMap $BeforeLines
if ($BeforeLines) { [IO.File]::WriteAllLines("$OutDir\before.kv", [string[]]$BeforeLines); "EVIDENCE_SAVED=$OutDir\before.kv" } else { "EVIDENCE_NOT_SAVED=True — 프로브 출력이 비었습니다" }
$CodeOk = ([bool]$BeforeMap["CODE_PHASE3"]) -and ($BeforeMap["CODE_PHASE3"] -like "$Wt\*") -and ($BeforeMap["CODE_REPLAY"] -like "$Wt\*") -and ($BeforeMap["CODE_PROBE"] -like "$Wt\*")
$Verdict = $BeforeMap["VERDICT"]
$Banks = @()
if ($BeforeMap["REPLAY_BANKS"]) { $Banks = @($BeforeMap["REPLAY_BANKS"].Split(";") | Where-Object { $_ } | ForEach-Object { "$Wt\" + ($_ -replace '/', '\') }) }
$BanksExist = ($Banks.Count -gt 0) -and (@($Banks | Where-Object { -not (Test-Path $_) }).Count -eq 0)
$BeforeOk = ($LinkExit -eq 0) -and (($Verdict -ceq "READY") -or ($Verdict -ceq "PARTIAL")) -and ((Get-KvInt $BeforeMap "REPLAYABLE_IN_DB") -gt 0) -and ($Banks.Count -eq (Get-KvInt $BeforeMap "REPLAY_BANK_COUNT")) -and $BanksExist
"VERDICT=$Verdict · REPLAY_BANK_COUNT=" + $Banks.Count + " · BANKS_EXIST=$BanksExist"
"CODE_OK=$CodeOk · BEFORE_OK=$BeforeOk · REACH_EXIT=$ReachExit"
```

**확인**: `PY_OK=True` · `REACH_EXIT=0` · `LINK_EXIT=0` · `CODE_OK=True` · `BEFORE_OK=True`. 그리고 출력된
`CODE_PHASE3`·`CODE_REPLAY`·`CODE_PROBE` 세 경로가 모두 `…\WhyMath_wt_<main 해시>\…`로 시작해야 한다.

| 값 | 실패 신호 | 대처 |
|---|---|---|
| `REACH_EXIT` | 1(도달 불가) 또는 2(측정 불가) | CLI가 출력하는 상태·대책을 따른다(`FOREIGN_LISTENER`면 5433을 다른 프로세스가 물고 있다 — 적재 금지, 출력 전달) |
| `VERDICT=NONE` | 어느 핵심 개념에도 DB에 있는 재생 가능 문항이 없다 | **적재하지 않는다**(이후 쓰기 블록이 전부 거부한다). §4 대조표를 보고 출력 전체를 전달 |
| `VERDICT=PARTIAL` | 일부 개념만 재생 가능 | 진행해도 된다. 단 결과는 10/10이 될 수 없다 — `CONCEPT_Cnn_REPLAYABLE_IN_DB=0`인 개념을 함께 전달 |
| `LINK_EXIT=2` | 측정 실패(`PROBE_ERROR=` 줄) | 그 줄을 그대로 전달 |

이 블록의 **BEFORE 수치 전체**가 acceptance ④의 "재측정 전" 실측이다. 화면 전체를 복사해 전달한다.

### [D] 쓰기 대상 5개 표 백업 (되돌리기용 사본 · DB는 읽기만)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · D 백업 (DB 읽기 전용 · 파일 생성)
cd $Wt
$BackupFile = "$OutDir\p3_32_before.dump"
$BackupReady = $WtOk -and $CodeOk -and $BeforeOk -and ($ReachExit -eq 0) -and ($Wt -notmatch '\s')
"BACKUP_READY=$BackupReady · WT_OK=$WtOk CODE_OK=$CodeOk BEFORE_OK=$BeforeOk REACH_EXIT=$ReachExit"
if ($BackupReady) { docker exec whymath-pg pg_dump -U whymath -d whymath -t verified_solutions -t solution_nodes -t solution_paths -t problem_step -t hints -Fc -f /tmp/p3_32_before.dump; $DumpExit = $LASTEXITCODE; docker cp whymath-pg:/tmp/p3_32_before.dump $BackupFile; $CopyExit = $LASTEXITCODE; "DUMP_EXIT=$DumpExit · COPY_EXIT=$CopyExit" } else { $DumpExit = -1; $CopyExit = -1; "BACKUP_REFUSED=True — WT_OK=$WtOk CODE_OK=$CodeOk BEFORE_OK=$BeforeOk REACH_EXIT=$ReachExit · 전부 True/0이어야 백업합니다" }
$BackupBytes = 0
if (Test-Path $BackupFile) { $BackupBytes = (Get-Item $BackupFile).Length }
$TocLines = docker exec whymath-pg pg_restore -l /tmp/p3_32_before.dump
$ListExit = $LASTEXITCODE
$TocTables = @($TocLines | Where-Object { $_ -match 'TABLE DATA public (verified_solutions|solution_nodes|solution_paths|problem_step|hints) ' }).Count
$BackupOk = $BackupReady -and ($DumpExit -eq 0) -and ($CopyExit -eq 0) -and ($BackupBytes -gt 0) -and ($ListExit -eq 0) -and ($TocTables -eq 5)
"BACKUP_BYTES=$BackupBytes · RESTORE_LIST_EXIT=$ListExit · TOC_TABLES=$TocTables · BACKUP_OK=$BackupOk"
```

**확인**: `DUMP_EXIT=0` · `COPY_EXIT=0` · `BACKUP_BYTES`가 0보다 큼 · `RESTORE_LIST_EXIT=0` · `TOC_TABLES=5` ·
`BACKUP_OK=True`. `BACKUP_OK`는 [F]·[G]·[H]의 가드가 다시 읽는다 — `False`면 적재가 전부 거부된다.

이 백업은 **복원 명령을 이 문서가 검증하지 않았다**(§9). 파일이 생겼고 `pg_restore -l` 목차에 다섯 표가 모두
있다는 것까지만 확인한다.

### [E] 적재 확인 입력 (한 줄 블록 — 이 줄만 붙여넣는다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · E 적재 확인 입력 (이 블록만 혼자 붙여넣는다)
$Confirm = Read-Host "BEFORE 수치(VERDICT·REPLAYABLE_IN_DB)를 확인했다면 대문자 APPLY 를 입력하고 Enter"
```

**이 블록은 위아래 어떤 줄과도 같이 붙여넣지 않는다.** 입력 대기 중에 뒤따라 붙여넣은 줄이 입력으로 먹히는
것을 막기 위해서다. `APPLY` 외의 입력이면 [F]가 거부한다(그러면 [G]·[H]도 연쇄로 거부된다).

### [F] 재생 — DB에 있는 문항만 (여기서 처음 DB에 쓴다)

이 블록은 **[B]~[E]의 판정값을 스스로 다시 검사하고, 하나라도 미충족이면 실행을 거부한다.** 재생은 은행 파일
목록([C]의 `REPLAY_BANKS`)을 받아 DB에 문항 행이 있는 대상만 처리한다.

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · F 재생 (쓰기 · 조건 미충족이면 스스로 거부)
cd $Wt
$ReplayJson = "$OutDir\replay.json"
$ConfirmOk = ($Confirm -ceq "APPLY")
$ReplayReady = $BackupOk -and $ConfirmOk -and $WtOk -and $CodeOk -and $BeforeOk -and ($ReachExit -eq 0)
"REPLAY_READY=$ReplayReady · BACKUP_OK=$BackupOk CONFIRMED=$ConfirmOk WT_OK=$WtOk CODE_OK=$CodeOk BEFORE_OK=$BeforeOk REACH_EXIT=$ReachExit"
if ($ReplayReady) { $T0 = Get-Date; & $Py -m whymath_backend.whs.corpus_replay @Banks --no-bad-branch --only-existing-problems --json $ReplayJson | Out-Null; $ReplayExit = $LASTEXITCODE; "REPLAY_EXIT=$ReplayExit · REPLAY_SEC=" + [int]((Get-Date) - $T0).TotalSeconds } else { $ReplayExit = -1; "WRITE_REFUSED=True — BACKUP_OK=$BackupOk CONFIRMED=$ConfirmOk WT_OK=$WtOk CODE_OK=$CodeOk BEFORE_OK=$BeforeOk REACH_EXIT=$ReachExit · 전부 True/0이어야 재생합니다. [B]~[E]를 같은 창에서 순서대로 실행하세요" }
$Confirm = $null
$ReplayLines = & $Py $LinkProbe summary --kind replay --json $ReplayJson
$ReplaySumExit = $LASTEXITCODE
$ReplayLines
$ReplayMap = Get-KvMap $ReplayLines
$ReplayOk = ($ReplayExit -eq 0) -and ($ReplaySumExit -eq 0) -and ((Get-KvInt $ReplayMap "REPLAY_VERIFIED") -gt 0) -and ((Get-KvInt $ReplayMap "REPLAY_OTHER") -eq 0) -and ((Get-KvInt $ReplayMap "REPLAY_FAILURES") -eq 0)
"REPLAY_OK=$ReplayOk"
```

**확인**: `REPLAY_READY=True` → `REPLAY_EXIT=0` → `REPLAY_OK=True`. `REPLAY_VERIFIED`가 [C]의
`REPLAYABLE_IN_DB` 이상이어야 정상이다(재생 은행에는 핵심 개념 밖 문항도 들어 있어 더 클 수 있다).
`REPLAY_SKIPPED_MISSING`은 DB에 문항 행이 없어 **일부러 재생하지 않은** 수다.

| 증상 | 뜻 | 대처 |
|---|---|---|
| `WRITE_REFUSED=True` | 선행 판정 하나가 False — **쓰기는 일어나지 않았다** | 같은 줄에 찍힌 값을 보고 [B]~[E]를 같은 창에서 다시 |
| `REPLAY_EXIT=1` · `REPLAY_OTHER`가 0이 아님 | 일부 대상이 verified가 아니다. 문항마다 독립 트랜잭션이라 **통과한 대상은 이미 적재됐다** | 다음 블록은 거부된다. `replay.json`의 `failures` 앞 10줄을 전달 |
| 화면에 `replay 대상 0건` | 은행의 어떤 문항도 DB에 없다([C]와 모순) | 출력 전달 |

### [G] 풀이 경로 승격 — 시험 실행 후 적재

시험 실행(쓰기 없음)으로 계획을 먼저 보고, 계획이 깨끗할 때만 같은 블록이 `--apply`로 적재한다. 승격 CLI는
검수 대기열 행을 **표준출력**에, 결과 JSON 한 줄을 **표준오류**에 쓴다. PowerShell이 표준오류를 받으면 줄을
오류 객체로 감싸고 인코딩을 왕복시키므로(CLAUDE.md 인코딩 규칙 — 셸 중계 축), `cmd /c`가 두 출력을 각각
파일로 바로 쓰게 한다. 경로에 공백이 없어야 하며 [D]의 가드가 그것을 이미 확인했다.

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · G 승격 (시험 실행 후 쓰기 · 조건 미충족이면 스스로 거부)
cd $Wt
$PromoDry = "$OutDir\promotion_dry.json"
$PromoApply = "$OutDir\promotion_apply.json"
$PromoDryReady = $ReplayOk -and $BackupOk -and $WtOk -and $CodeOk -and ($ReachExit -eq 0)
if ($PromoDryReady) { cmd /c "$Py -m whymath_backend.whs.path_promotion 1> $OutDir\promotion_dry_queue.jsonl 2> $PromoDry"; $PromoDryExit = $LASTEXITCODE } else { $PromoDryExit = -1; "PROMO_DRY_REFUSED=True — REPLAY_OK=$ReplayOk BACKUP_OK=$BackupOk" }
$DryLines = & $Py $LinkProbe summary --kind promotion --json $PromoDry
$PromoDrySumExit = $LASTEXITCODE
$DryLines
$PromoDryMap = Get-KvMap $DryLines
$PromoPlanOk = ($PromoDryExit -eq 0) -and ($PromoDrySumExit -eq 0) -and ($PromoDryMap["PROMO_MODE"] -ceq "dry-run") -and ((Get-KvInt $PromoDryMap "PROMO_PYDANTIC_REJECTED") -eq 0)
"PROMO_DRY_EXIT=$PromoDryExit · PROMO_PLAN_OK=$PromoPlanOk"
if ($PromoPlanOk -and $ReplayOk -and $BackupOk) { cmd /c "$Py -m whymath_backend.whs.path_promotion --apply 1> $OutDir\promotion_apply_queue.jsonl 2> $PromoApply"; $PromoExit = $LASTEXITCODE; "PROMO_APPLY_EXIT=$PromoExit" } else { $PromoExit = -1; "WRITE_REFUSED=True — PROMO_PLAN_OK=$PromoPlanOk REPLAY_OK=$ReplayOk BACKUP_OK=$BackupOk · 전부 True여야 승격을 적재합니다" }
$ApplyLines = & $Py $LinkProbe summary --kind promotion --json $PromoApply
$PromoSumExit = $LASTEXITCODE
$ApplyLines
$PromoMap = Get-KvMap $ApplyLines
$PromoOk = ($PromoExit -eq 0) -and ($PromoSumExit -eq 0) -and ($PromoMap["PROMO_MODE"] -ceq "apply") -and ((Get-KvInt $PromoMap "PROMO_PYDANTIC_REJECTED") -eq 0) -and (((Get-KvInt $PromoMap "PROMO_PROMOTED") + (Get-KvInt $PromoMap "PROMO_ALREADY")) -gt 0)
"PROMO_OK=$PromoOk"
```

**확인**: `PROMO_PLAN_OK=True` → `PROMO_APPLY_EXIT=0` → `PROMO_OK=True`.

- `PROMO_QUEUED_UNMAPPABLE`은 풀이 유형을 정하지 못해 **사람 검수 대기열로 보낸** 수다(오류가 아니다 —
  P3-96 표에 없는 문항군). 샌드박스에서는 핵심 개념 밖 은행의 재생 풀이가 여기로 갔다.
- `PROMO_SKIPPED_MISSING`은 문항 행이 없는 풀이다. [F]가 `--only-existing-problems`로 재생했으므로 **이번
  실행분은 0이어야 한다** — 0이 아니면 이전에 다른 경로로 쌓인 고아 행이 있다는 뜻이다(값 전달만).
- 승격 CLI의 `PROMO_FAILURES`에는 승격 대기열 사유도 함께 세어지므로 0이 아니어도 실패가 아니다.

### [H] 힌트 생성 — 시험 실행 후 적재

P3-81 런북과 같은 `populate` CLI와 같은 요약 프로브(`p3_81_hint_catalog_probe.py run-summary`)를 쓴다.
`--overwrite-cms-edits`는 **쓰지 않는다**: CMS로 고친 행은 건너뛰고 충돌로 보고만 한다.

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · H 힌트 (시험 실행 후 쓰기 · 조건 미충족이면 스스로 거부)
cd $Wt
$HintDryJson = "$OutDir\hints_dry.json"
$HintApplyJson = "$OutDir\hints_apply.json"
$HintDryReady = $PromoOk -and $BackupOk -and $WtOk -and $CodeOk -and ($ReachExit -eq 0)
if ($HintDryReady) { $HintDryOut = & $Py -m whymath_backend.l4.hint_content.populate; $HintDryExit = $LASTEXITCODE; [IO.File]::WriteAllLines($HintDryJson, [string[]]@($HintDryOut)) } else { $HintDryExit = -1; "HINT_DRY_REFUSED=True — PROMO_OK=$PromoOk BACKUP_OK=$BackupOk" }
$HintDryLines = & $Py $HintProbe run-summary --json $HintDryJson
$HintDrySumExit = $LASTEXITCODE
$HintDryLines
$HintDryMap = Get-KvMap $HintDryLines
$HintPlanOk = ($HintDryExit -eq 0) -and ($HintDrySumExit -eq 0) -and ($HintDryMap["RUN_WELLFORMED"] -eq "True") -and ($HintDryMap["RUN_APPLIED"] -eq "False") -and ($HintDryMap["RUN_VALUE_ACCOUNTED"] -eq "True") -and ((Get-KvInt $HintDryMap "RUN_VALUE_NOT_RUN") -eq 0) -and ((Get-KvInt $HintDryMap "RUN_GENERATED") -gt 0)
"HINT_DRY_EXIT=$HintDryExit · HINT_PLAN_OK=$HintPlanOk"
if ($HintPlanOk -and $PromoOk -and $BackupOk) { $HintApplyOut = & $Py -m whymath_backend.l4.hint_content.populate --apply; $HintExit = $LASTEXITCODE; [IO.File]::WriteAllLines($HintApplyJson, [string[]]@($HintApplyOut)); "HINT_APPLY_EXIT=$HintExit" } else { $HintExit = -1; "WRITE_REFUSED=True — HINT_PLAN_OK=$HintPlanOk PROMO_OK=$PromoOk BACKUP_OK=$BackupOk · 전부 True여야 힌트를 적재합니다" }
$HintLines = & $Py $HintProbe run-summary --json $HintApplyJson
$HintSumExit = $LASTEXITCODE
$HintLines
$HintMap = Get-KvMap $HintLines
$HintsOk = ($HintExit -eq 0) -and ($HintSumExit -eq 0) -and ($HintMap["RUN_WELLFORMED"] -eq "True") -and ($HintMap["RUN_APPLIED"] -eq "True") -and ((Get-KvInt $HintMap "RUN_CMS_CONFLICTS") -eq 0) -and ($HintMap["RUN_VALUE_ACCOUNTED"] -eq "True")
"HINTS_OK=$HintsOk"
```

**확인**: `HINT_PLAN_OK=True` → `HINT_APPLY_EXIT=0` → `HINTS_OK=True`. 샌드박스에서 검수 통과율(`RUN_VERIFIED_RATE`)은
0.94였다. 게이트가 거부한 힌트(정답 누설·단계 노출)는 `verified=false`로 저장돼 학생에게 나가지 않는다.

| 증상 | 뜻 | 대처 |
|---|---|---|
| `RUN_CMS_CONFLICTS`가 0이 아님 | CMS로 고친 힌트가 덮어쓰기에서 건너뛰어졌다 | 덮어쓰기는 Kiki가 정할 일이다 — `hints_apply.json`을 세션에 전달 |
| `RUN_VALUE_NOT_RUN`이 0이 아님 | 값 축 능력이 주입되지 않았다 | 적재되지 않는다(가드). 출력 전달 |

### [I] 적재 후 실측 · 계측기 · 정답 누설 판정 (읽기 전용)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · I AFTER 실측 + 계측기 + 누설 판정 (읽기 전용)
cd $Wt
$AfterLines = & $Py $LinkProbe link
$AfterExit = $LASTEXITCODE
$AfterLines
$AfterMap = Get-KvMap $AfterLines
if ($AfterLines) { [IO.File]::WriteAllLines("$OutDir\after.kv", [string[]]$AfterLines); "EVIDENCE_SAVED=$OutDir\after.kv" }
$CovFile = "$OutDir\coverage_after.txt"
cmd /c "$Py -m whymath_backend.l1.standards.phase3_coverage --hints-from-db 1> $CovFile 2>&1"
$CovExit = $LASTEXITCODE
Select-String -Path $CovFile -Pattern "Concept Completeness|hint  |Graph Connectivity" | ForEach-Object { $_.Line }
"COVERAGE_EXIT=$CovExit (1 = 목표 미달 지표가 하나라도 있음 · 2 = 측정 실패)"
$ServeLines = & $Py $HintProbe serve-sample --problems 300
$ServeExit = $LASTEXITCODE
$ScanLines = & $Py $HintProbe catalog-scan --levels 3
$ScanExit = $LASTEXITCODE
@($ServeLines + $ScanLines) | Where-Object { $_ -match '^(SERVE|SCAN)_(JUDGED|LEAK_EXPOSED|LEAK_HINT)' }
if ($ServeLines) { [IO.File]::WriteAllLines("$OutDir\serve.kv", [string[]]$ServeLines) }
if ($ScanLines) { [IO.File]::WriteAllLines("$OutDir\scan.kv", [string[]]$ScanLines) }
$Linked = Get-KvInt $AfterMap "CONCEPTS_HINT_LINKED"
$Expected = Get-KvInt $BeforeMap "CONCEPTS_REPLAYABLE"
$LinkOk = ($AfterExit -eq 0) -and ($CovExit -ne 2) -and ($Linked -ge 0) -and ($Linked -eq $Expected)
"BEFORE_AFTER 힌트 붙은 적격 문항: " + $BeforeMap["WITH_VERIFIED_HINT"] + " -> " + $AfterMap["WITH_VERIFIED_HINT"]
"BEFORE_AFTER 검증 풀이 붙은 적격 문항: " + $BeforeMap["WITH_VERIFIED_SOLUTION"] + " -> " + $AfterMap["WITH_VERIFIED_SOLUTION"]
"HINT_LINKED_CONCEPTS=$Linked/" + $AfterMap["CONCEPTS"] + " · 기대(재생 가능 개념)=$Expected"
"LINK_OK=$LinkOk"
"LEAK_CHECK_OK=" + (($ServeExit -eq 0) -and ($ScanExit -eq 0))
"JUDGED_AGAINST_MAIN=$MainSha"
```

**확인**: `LINK_OK=True` · `LEAK_CHECK_OK=True` · `HINT_LINKED_CONCEPTS=10/10`(이것이 acceptance ③의 완료값).

- `HINT_LINKED_CONCEPTS`가 10/10이 아니고 `LINK_OK=True`면, 재생 가능했던 개념은 전부 연결됐고 나머지는 DB에
  문항이 없다는 뜻이다(§4). 10/10이 아니면 P3-32는 done이 아니다 — 출력 전체를 전달한다.
- `LINK_OK=False`인데 `HINT_LINKED_CONCEPTS`가 기대보다 작으면, 재생 가능했던 개념 중 일부가 힌트까지 가지
  못했다(승격 대기열·힌트 게이트 전량 거부 등). `after.kv`의 `CONCEPT_Cnn_*` 줄로 어느 단계에서 끊겼는지 보인다.
- `COVERAGE_EXIT=1`은 **실패가 아니다** — Graph Connectivity(오답 보기↔오개념) 등 다른 지표가 미달이어도 1이다.
  hint 줄과 Concept Completeness 줄을 본다.
- 누설 판정 exit `1`이면 `*_LEAK_HINT=` 줄(`hint_id`·사유)을 전달한다. exit `2`는 측정 실패다(`*_JUDGED=0`이면
  통과가 아니다).

이 블록의 **전후 수치 전체**와 `coverage_after.txt`가 acceptance ④(재측정 전후 표)의 증거다.

### [J] 임시 worktree 정리 (저장소 밖 폴더만 지운다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · J 임시 worktree 정리
cd C:\Users\kiki\Desktop\__AI\WhyMath
if ($Wt -and ($Wt -like "C:\Users\kiki\Desktop\__AI\WhyMath_wt_*") -and (Test-Path $Wt)) { git worktree remove --force $Wt; "WT_REMOVE_EXIT=$LASTEXITCODE" } else { "WT_REMOVE_SKIPPED=True — WT=$Wt (WhyMath_wt_ 로 시작하는 폴더만 지웁니다)" }
"WT_REMOVED=" + (-not (Test-Path $Wt))
"OUT_DIR_KEPT=$OutDir"
```

**확인**: `WT_REMOVED=True`. 증거 폴더 `work\p3_32_<main 해시>`(백업·JSON·kv·계측기 출력)는 남는다 — 전달 후
필요 없으면 지워도 된다.

---

## 7. 전달할 것

[C]·[F]·[G]·[H]·[I] 화면 전체. 특히 `VERDICT`·`REPLAY_OK`·`PROMO_OK`·`HINTS_OK`·`LINK_OK`·`LEAK_CHECK_OK`·
`HINT_LINKED_CONCEPTS` 줄과 `coverage_after.txt`.

## 8. 범위 밖

- **운영 DB에 문항 행 적재**: [C]가 `PARTIAL`이나 `NONE`이면 남은 개념은 문항 행이 없어서 막힌다. 문항 적재
  (`l1.problem_bank.populate`)는 노출 문항 집합을 바꾸는 별도 결정이라 이 런북에서 하지 않는다.
- **오개념 서명·스킬 결손**: EOS-194 측정(2026-10-31)에서 노출 문항 표본 50건 중 `misconception_signature` 39건·
  `skill` 5건이 비었다. 힌트를 채워도 그 문항은 발행 7필드를 못 채운다 — 소유 태스크 미정.
- **문항 발행 확인**: EOS-194 acceptance ③은 이 런북 뒤에 `docs/reviews/eos194_acceptance3_2026-10-31/eos194_measure.py`
  ([A]→[B]→[W])를 다시 돌려 판정한다.

## 9. 이 문서가 검증한 것과 못 한 것

**실행으로 검증한 것**(이 PR의 세션 · 로컬 PostgreSQL 16 + pgvector · 운영 아님):
- 프로브 `link`가 전 코퍼스 적재 DB에서 `ELIGIBLE=1121 · REPLAYABLE_IN_DB=847 · CONCEPTS_HINT_LINKED=10 ·
  VERDICT=READY`를 냈다(계측기 `--hints-from-db`의 hint linked 10/10·hint_strategy present 847과 같은 값).
- `corpus_replay --only-existing-problems`가 DB에 없는 문항을 재생하지 않고 `skipped_problem_missing`으로 세며,
  대상이 전부 없으면 exit 1을 낸다(실 PG 통합 테스트 · 뮤테이션 2종 RED).
- 재생 → 승격 → 힌트 생성 순서 자체는 P3-95 샌드박스 실측(14개 은행 · 3,833건)에서 끝까지 돌았다.

**검증하지 못한 것**:
- **PowerShell 블록 자체는 실행하지 못했다**(세션은 Linux다). 블록의 형식(가드·자리표시자·펜스)은
  `scripts/ops/check_runbook_blocks.py`와 `tests/infra/test_p3_32_hint_link_runbook.py`가 정적으로 검사한다.
- **운영 DB의 적격 문항 겹침**: 모른다. 이 런북의 [C]가 처음 잰다.
- **백업 복원**: 복원 명령을 실행해 보지 않았다.
- **운영 규모 소요 시간**.
