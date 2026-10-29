# EOS-210 — 힌트 정답 누설 사람 판정 (Kiki 실행 런북)

> 판정 기준: main `aed2b87a` (EOS-207 병합 직후). 이 런북이 쓰는 도구 `harness/hint_verdict_session`과
> 측정기 확장은 **EOS-210 PR이 병합돼야 `origin/main`에 있다.**
>
> **선행 조건 — 이 런북은 EOS-211 라이브 실행 *뒤에만* 쓴다.** EOS-211(PR #1772)이 저작 회차 폴더에
> `cu.hints.jsonl`(verified 힌트, `Hint` 모델 JSON 1행 1건)을 쓰고, 그 회차 폴더가 **main에 병합돼
> 있어야** 한다. 파일이 없으면 [B]가 `CU_HINTS_FILES=0` · `ENV_OK=False`를 내고 뒤 블록은 전부
> 스스로 거부한다.
>
> 이 문서가 실행으로 검증한 것과 못 한 것은 §7에 따로 적었다.

## 1. 과제 명칭

G3 "힌트 의미 누설 0"의 사람 판정 — 힌트 표본 추출 → 맹검 판정 세션 → 측정기 실행 → 판정 기록 커밋.

## 2. 목적

측정기 `ops/g3_content_measures`는 L1·L2 힌트의 정답 누설을 기계 두 축(글자·값)으로만 판정한다. 남는
두 구멍을 사람이 메운다.

- (가) **기계 판정 불가 힌트 전수** — 짧은 정답의 글자 축 유보 등. 측정기가 `UNDECIDED`(exit 2)로
  남긴 힌트를 사람이 "누설/아님"으로 판정한다.
- (나) **의미 누설 표본 30건** — 표준 §5 F-Ⅴ("자동 검사 밖")·§6("인간 30건"). 기계가 clean이라고 본
  힌트도 뜻으로는 정답을 흘릴 수 있다.

결과는 `data/runs/<회차>-review/`의 두 파일(표본 매니페스트·판정 기록)로 남고, 측정기가 그것을 읽어
`HINT_SEMANTIC_AXIS`(n·k·Wilson 상한)와 기계 판정 불가 해소를 낸다. G3 판정(11/22)의 입력이다 —
**이 런북은 게이트를 닫지 않는다.**

## 3. 구체적 절차

| 단계 | 무엇이 일어나는가 | 쓰기 | 기대 출력(판정값) |
|---|---|---|---|
| A | 회차 접두어 입력(한 줄 블록) | 없음 | 입력 대기 |
| B | main 일치·코드 출처·힌트 파일 확인 | 없음 | `ENV_OK=True` |
| C | 판정자 ID 입력(한 줄 블록) | 없음 | 입력 대기 |
| D | 표본 추출 — 매니페스트 작성 | 매니페스트 파일 1개 | `SAMPLE_OK=True` |
| E | 맹검 판정 세션(대화형 — 한 줄 블록) | 판정 1건마다 append | `SESSION_STATE=완료` |
| F | 측정기 실행 | `work\` 아래 리포트 JSON만 | `MEASURE_RAN=True` |
| G | 판정 기록 커밋·push(새 브랜치) | git 브랜치·커밋·push | `LAST_STEP=push` · `STEP_EXIT=0` |

**판정 세션 안에서 보이는 것**: 문항·선택지·정답·힌트 단계·힌트 본문뿐이다. 기계 판정, 게이트 기록, 그
힌트가 왜 물어졌는지(표본인지 기계 판정 불가인지), 이미 기록된 판정(자기 것·다른 사람 것)은 **보이지
않는다** — 헌법 R19-01. 항목마다 `1`(누설)·`2`(누설 아님)·`s`(건너뛰기)·`q`(종료)를 누르고 근거를 한
줄 적은 뒤 `y`로 확인한다. 항목이 뜬 뒤 2초 안에 들어온 판정은 버린다(붙여넣기 잔여 줄 방지).

**소요 시간**: 판정 대상은 표본 최대 30건 + 기계 판정 불가 전수(회차마다 다름 — [D]의 `WORK_ITEMS`).
1건에 1~2분이면 30~60분 안팎이다. 실측하지 못했다.

**중단·재개**: `q`나 창 닫기로 멈춰도 그때까지의 판정은 남는다. 같은 창에서 [E]를 다시 붙여넣으면 이미
판정한 항목을 건너뛴다. 창을 닫았으면 [A]부터 다시 한다([D]는 같은 매니페스트를 그대로 두고 통과한다).

## 4. 성공 기준

| 단계 | 성공 | 실패 신호 → 대처 |
|---|---|---|
| B | `ENV_OK=True` | `HEAD_OK=False` — 클론이 main이 아니다. 브랜치를 옮기지 말고 출력 전체를 세션에 전달(다른 세션 작업이 있을 수 있다) · `CU_HINTS_FILES=0` — EOS-211 라이브 실행분이 main에 없다 · `CODE_OK=False` — 다른 경로의 코드가 import됐다 |
| D | `SAMPLE_OK=True` · `SEMANTIC_SAMPLE_REACHES_30=True` | `SEMANTIC_SAMPLE_REACHES_30=False` — 모집단이 30 미만이라 의미 축은 측정 불가로 끝난다(그래도 판정은 진행 — (가) 해소에 쓰인다). `INPUT_ERROR=다른 매니페스트가 이미 있다` — 힌트가 바뀌었다. 출력 전달 |
| E | 마지막 요약 `SESSION_REMAINING=0` | `WRITE_PREFLIGHT_FAILED` — 판정 파일을 다른 프로그램(Excel 등)이 열고 있다. 닫고 [E] 재실행 · `기록 실패 — …` — 그 항목은 기록되지 않았다. 원인을 고치고 [E] 재실행 |
| F | `MEASURE_RAN=True` | `HINT_HUMAN_INPUT_ERRORS`가 0이 아님 — 판정 파일이 손상됐다. **손으로 고치지 말고** 출력 전달 |
| G | `LAST_STEP=push` · `STEP_EXIT=0` · `CLONE_NOW`가 `ORIGINAL`과 같음 · `MANIFEST_RESTORED=True` · `VERDICTS_RESTORED=True` | `WRITE_REFUSED=True` — 같은 줄의 False 항목을 보고 [G] 아래 표의 대처 · `WRITE_STOPPED=True` — 멈춘 단계 뒤는 실행되지 않았다. 출력 전달 |

**측정 결과 읽는 법**([F] 출력): `HINT_SEMANTIC_AXIS=PASS`면 표본 30건 이상에서 누설 0이고
`HINT_SEMANTIC_WILSON_UPPER_95`가 그 보증 상한이다(0/30이어도 약 0.083 — 0이 아니다). `FAIL`이면 누설이
1건 이상 있다. `NOT_MEASURABLE`이면 표본이 30건 미만이거나 덜 판정됐다(`HINT_SEMANTIC_UNJUDGED`).
`MEASURE_EXIT`는 0(통과)·1(위반)·2(측정 불가) 중 어느 것이든 **이 런북의 실패가 아니다** — 값 그대로
세션에 전달한다.

## 5. 실행 환경

- **머신**: Phaiakes9(= Kiki의 작업 PC · 별도 접속 없음)
- **시스템**: Windows PowerShell(WSL 아님)
- **작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath`(블록이 스스로 `cd`한다)
- **선행 조건**: ① EOS-210 PR이 main에 병합됨 ② EOS-211 라이브 실행으로 `data\runs\<회차>-*\cu.hints.jsonl`이
  생겼고 그 회차 폴더가 main에 병합됨 ③ 클론이 main 최신(`HEAD == origin/main`) ④ `src\backend\.venv` 준비됨
- DB·서버·Docker 불필요(파일만 읽고 쓴다)

## 6. 창 구분

**새 PowerShell 창 하나**에서 [A]~[G]를 순서대로 한다. 뒤 블록이 앞 블록의 변수(`$Round`·`$EnvOk`·
`$SampleOk` 등)를 읽으므로 **같은 창을 유지**한다. 창을 바꾸면 쓰기 블록은 스스로 거부한다
(`WRITE_REFUSED=True`). [A]·[C]·[E]는 **한 줄짜리 블록이며 혼자 붙여넣는다** — 입력 대기 중에 뒤 줄이
입력으로 먹히는 것을 막기 위해서다. [E] 실행 중에는 그 창에 다른 것을 붙여넣지 않는다.

---

## 실행 블록

> 자리표시자가 하나도 없다. 회차와 판정자 ID는 [A]·[C]가 멈춰서 묻는다. **블록 하나씩** 붙여넣고 판정값을
> 확인한 다음 넘어간다. 쓰기 블록([D]·[E]·[G])은 눈 확인에 기대지 않고 선행 판정을 **스스로 다시 검사해
> 거부**한다.

### [A] 회차 접두어 입력 (이 줄만 붙여넣는다)

```powershell
$Round = Read-Host "판정할 회차 접두어(data\runs 아래 폴더 이름의 앞부분)를 입력하고 Enter"
```

### [B] main 일치 · 코드 출처 · 힌트 파일 확인 (읽기 전용)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · B 환경·코드 출처·입력 확인 (읽기 전용)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$Repo = "C:\Users\kiki\Desktop\__AI\WhyMath"
$env:PYTHONPATH = "$Repo\src\backend"
$Py = "$Repo\src\backend\.venv\Scripts\python.exe"
function Get-KvMap([string[]]$Lines) { $Map = @{}; foreach ($L in $Lines) { if ($L -match '^([A-Z0-9_]+)=(.*)$') { $Map[$Matches[1]] = $Matches[2].Trim() } }; return $Map }
git fetch origin main
$HeadSha = (git rev-parse --short HEAD)
$MainSha = (git rev-parse --short origin/main)
$HeadOk = ($HeadSha -eq $MainSha)
git diff --quiet origin/main -- "src/backend/whymath_backend"
$CodeSame = ($LASTEXITCODE -eq 0)
$CodeFiles = @(& $Py -c "import whymath_backend.harness.hint_verdict_session as s, whymath_backend.ops.g3_content_measures as g; print(s.__file__); print(g.__file__)")
$CodeFiles
$CodeOk = ($CodeFiles.Count -eq 2) -and ($CodeFiles[0] -like "$Repo\src\backend\*") -and ($CodeFiles[1] -like "$Repo\src\backend\*")
$RoundOk = ([bool]$Round) -and ($Round -match '^[A-Za-z0-9][A-Za-z0-9_.-]*$')
$HintFiles = @()
if ($RoundOk) { $HintFiles = @(Get-ChildItem -Path "$Repo\data\runs" -Directory -Filter "$Round-*" | ForEach-Object { Join-Path $_.FullName "cu.hints.jsonl" } | Where-Object { Test-Path $_ }) } else { "ROUND_INVALID=True — 회차 접두어가 비었거나 형식이 다르다. [A]를 다시 붙여넣으세요" }
$HintFiles
$HintArgs = @()
foreach ($F in $HintFiles) { $HintArgs += "--hints-jsonl"; $HintArgs += $F }
$ReviewDir = "$Repo\data\runs\$Round-review"
$Manifest = "$ReviewDir\hint_sample_manifest.json"
$Verdicts = "$ReviewDir\hint_verdicts.jsonl"
$OutDir = "$Repo\work\eos210_$Round"
"HEAD=$HeadSha · ORIGIN_MAIN=$MainSha · HEAD_OK=$HeadOk · CODE_SAME_AS_MAIN=$CodeSame · CODE_OK=$CodeOk"
"ROUND=$Round · ROUND_OK=$RoundOk · CU_HINTS_FILES=" + $HintFiles.Count
"MANIFEST_EXISTS=" + (Test-Path $Manifest) + " · VERDICTS_EXISTS=" + (Test-Path $Verdicts)
$EnvOk = $HeadOk -and $CodeSame -and $CodeOk -and $RoundOk -and ($HintFiles.Count -ge 1)
"ENV_OK=$EnvOk"
```

**확인**: `ENV_OK=True`. 위에 찍힌 두 경로(`…\hint_verdict_session.py`·`…\g3_content_measures.py`)가
`C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\`로 시작해야 한다(그 밖이면 다른 코드가 돈 것이다).

### [C] 판정자 ID 입력 (이 줄만 붙여넣는다)

판정자 ID는 이름이 아니라 짧은 식별자다(영문·숫자로 시작, 1~32자, 영문·숫자·`_`·`.`·`-`). 판정 기록에
그대로 남는다.

```powershell
$Reviewer = Read-Host "판정자 짧은 ID(영문·숫자 1~32자 · 이름 아님)를 입력하고 Enter"
```

### [D] 표본 추출 (매니페스트 작성 · 조건 미충족이면 스스로 거부)

seed는 힌트 모집단에서 자동으로 정해진다(사람이 고르지 않는다). 매니페스트가 이미 있고 내용이 같으면
그대로 두고 통과한다(`MANIFEST_WRITTEN=EXISTS_IDENTICAL`). 다르면 **덮어쓰지 않고** 거부한다.

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · D 표본 추출 (매니페스트 쓰기 · 조건 미충족이면 스스로 거부)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$HeadNow = (git rev-parse --short HEAD)
$SampleReady = $EnvOk -and ($HeadNow -eq $MainSha)
"SAMPLE_READY=$SampleReady · ENV_OK=$EnvOk · HEAD_NOW=$HeadNow · MAIN=$MainSha"
if ($SampleReady) { $SampleLines = @(& $Py -m whymath_backend.harness.hint_verdict_session sample --round $Round @HintArgs); $SampleExit = $LASTEXITCODE; $SampleLines } else { $SampleExit = -1; $SampleLines = @(); "WRITE_REFUSED=True — ENV_OK=$EnvOk · HEAD_NOW=$HeadNow · MAIN=$MainSha · [A]·[B]를 같은 창에서 먼저 실행하세요" }
$SampleMap = Get-KvMap $SampleLines
$SampleOk = ($SampleExit -eq 0) -and (Test-Path $Manifest) -and ($SampleMap["MANIFEST_WRITTEN"] -in @("True", "EXISTS_IDENTICAL"))
"SAMPLE_EXIT=$SampleExit · MANIFEST_ON_DISK=" + (Test-Path $Manifest) + " · SAMPLE_OK=$SampleOk"
```

**확인**: `SAMPLE_OK=True`. `SAMPLE_SIZE`(표본 수)·`MACHINE_UNDECIDED`(기계 판정 불가 수)·`WORK_ITEMS`(이번에
판정할 전체 수)를 확인한다. 이 출력에는 개별 힌트의 기계 판정이 없다.

### [E] 맹검 판정 세션 (대화형 — 이 줄만 붙여넣는다)

```powershell
if ($SampleOk -and ($Reviewer -cmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$')) { & $Py -m whymath_backend.harness.hint_verdict_session review --round $Round @HintArgs --reviewer $Reviewer } else { "WRITE_REFUSED=True — SAMPLE_OK=$SampleOk · REVIEWER_FORMAT_OK=" + ($Reviewer -cmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$') + " · [C]·[D]를 같은 창에서 먼저 실행하세요" }
```

**확인**: 마지막 요약의 `SESSION_STATE=완료` · `SESSION_REMAINING=0`. 중간에 `q`로 멈췄으면
`SESSION_STATE=중단`이고 남은 수가 찍힌다 — 이 블록을 다시 붙여넣으면 이어서 한다. 이미 판정한 항목을
다시 판정하려면 세션에 hint_id를 알려 주면 된다(재판정은 덮어쓰지 않고 새 행을 덧붙인다).

### [F] 측정기 실행 (읽기 전용 · 리포트 JSON은 `work\` 아래)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · F 측정기 (읽기 전용 · 리포트는 gitignore된 work 폴더)
cd C:\Users\kiki\Desktop\__AI\WhyMath
"REVIEW_EXIT=$LASTEXITCODE"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$MeasureLines = @(& $Py -m whymath_backend.ops.g3_content_measures --round $Round @HintArgs --hint-verdicts $Verdicts --hint-sample-manifest $Manifest --json "$OutDir\g3_measures.json")
$MeasureExit = $LASTEXITCODE
$MeasureLines
$MeasureMap = Get-KvMap $MeasureLines
$MeasureRan = ($MeasureExit -in @(0, 1, 2)) -and ($MeasureMap["HINT_HUMAN_INPUT_ERRORS"] -eq "0") -and ([bool]$MeasureMap["HINT_SEMANTIC_AXIS"])
"MEASURE_EXIT=$MeasureExit · HINT_SEMANTIC_AXIS=" + $MeasureMap["HINT_SEMANTIC_AXIS"] + " · HINT_MACHINE_AXIS=" + $MeasureMap["HINT_MACHINE_AXIS"] + " · MEASURE_RAN=$MeasureRan"
```

**확인**: `MEASURE_RAN=True`. 출력 전체(50줄 안팎)를 복사해 세션에 전달한다 — 특히 `HINT_SEMANTIC_*`·
`HINT_HUMAN_*`·`HINT_UNDECIDED_L12_UNRESOLVED`·`EXIT` 줄. `HINT_HUMAN_MACHINE_MISMATCH`가 0이 아니면 사람
판정과 기계 판정이 어긋난 힌트가 있다는 뜻이다(둘 다 보존되며, 기계 누설은 사람 판정으로 뒤집히지
않는다).

### [G] 판정 기록 커밋·push (새 브랜치 · 조건 미충족이면 스스로 거부)

매니페스트와 판정 기록 **두 파일만** 새 브랜치에 커밋해 push하고, 클론을 **원래 위치로 되돌린다**. PR은
세션이 연다(브랜치 이름을 전달).

이 블록이 막는 것 두 가지(EOS-210 리뷰 P2-2·P2-3):

- **다른 세션이 스테이징해 둔 변경까지 커밋** — 공유 클론이다. 그래서 시작 전에 스테이징된 것이 **하나도
  없어야** 하고(`NOTHING_STAGED=True`), 커밋은 두 경로만 지정한다(`git commit … -- 두 파일`).
- **재실행하면 main에 커밋** — PowerShell의 `;`는 앞 명령이 실패해도 다음 명령을 실행한다. `git switch -c`가
  "이미 있음"으로 실패하면 그 뒤 커밋이 **현재 브랜치(main)**에 들어간다. 그래서 브랜치가 로컬·원격 어디에도
  없어야 시작하고(`BRANCH_FREE=True`), 단계마다 종료 코드를 보고 실패하면 **뒤 단계를 실행하지 않는다**.

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · G 기록 커밋·push (쓰기 · 조건 미충족이면 스스로 거부)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$HeadNow = (git rev-parse --short HEAD)
$OrigBranch = (git rev-parse --abbrev-ref HEAD)
$OrigSha = (git rev-parse HEAD)
$Branch = "eos210-hint-verdicts-$Round"
$RelManifest = "data/runs/$Round-review/hint_sample_manifest.json"
$RelVerdicts = "data/runs/$Round-review/hint_verdicts.jsonl"
$Changed = @(git status --porcelain -- "data/runs/$Round-review")
git diff --cached --quiet
$NothingStaged = ($LASTEXITCODE -eq 0)
git rev-parse --verify --quiet "refs/heads/$Branch" *> $null
$LocalBranchFree = ($LASTEXITCODE -ne 0)
git ls-remote --exit-code --heads origin $Branch *> $null
$RemoteRc = $LASTEXITCODE
$RemoteBranchFree = ($RemoteRc -eq 2)
$BranchFree = $LocalBranchFree -and $RemoteBranchFree
$CommitReady = $MeasureRan -and $SampleOk -and ($HeadNow -eq $MainSha) -and (Test-Path $Manifest) -and (Test-Path $Verdicts) -and ($Changed.Count -ge 1) -and $NothingStaged -and $BranchFree
"COMMIT_READY=$CommitReady · MEASURE_RAN=$MeasureRan · SAMPLE_OK=$SampleOk · HEAD_NOW=$HeadNow · MAIN=$MainSha · CHANGED=" + $Changed.Count + " · NOTHING_STAGED=$NothingStaged · BRANCH_FREE=$BranchFree(LOCAL=$LocalBranchFree REMOTE_RC=$RemoteRc)"
if ($CommitReady) {
  $Step = "switch"; $Switched = $false; $Committed = $false
  git switch -c $Branch; $Rc = $LASTEXITCODE
  if ($Rc -eq 0) { $Switched = $true; $Step = "add"; git add -- $Manifest $Verdicts; $Rc = $LASTEXITCODE }
  if ($Rc -eq 0) { $Step = "commit"; git commit -m "EOS-210: 힌트 누설 사람 판정 기록 $Round" -- $Manifest $Verdicts; $Rc = $LASTEXITCODE; $Committed = ($Rc -eq 0) }
  if ($Rc -eq 0) { $Step = "push"; git push -u origin $Branch; $Rc = $LASTEXITCODE }
  "LAST_STEP=$Step · STEP_EXIT=$Rc · BRANCH=$Branch · BRANCH_HEAD=" + (git rev-parse --short HEAD)
  if ($Rc -ne 0) { "WRITE_STOPPED=True — $Step 단계가 실패(exit $Rc)해 뒤 단계는 실행하지 않았다. 출력 전체를 세션에 전달하세요" }
  if ($Rc -eq 0) { git log -1 --stat --oneline }
  if ($Switched -and ($OrigBranch -ne "HEAD")) { git switch $OrigBranch }
  if ($Switched -and ($OrigBranch -eq "HEAD")) { git switch --detach $OrigSha }
  if ($Committed) { git restore --source=$Branch --worktree -- $Manifest $Verdicts; $RestoreRc = $LASTEXITCODE; $ManifestRestored = (Test-Path $Manifest) -and ((git hash-object $Manifest) -eq (git rev-parse "${Branch}:$RelManifest")); $VerdictsRestored = (Test-Path $Verdicts) -and ((git hash-object $Verdicts) -eq (git rev-parse "${Branch}:$RelVerdicts")); "RESTORE_EXIT=$RestoreRc · MANIFEST_RESTORED=$ManifestRestored · VERDICTS_RESTORED=$VerdictsRestored" }
} else { "WRITE_REFUSED=True — MEASURE_RAN=$MeasureRan · SAMPLE_OK=$SampleOk · HEAD_NOW=$HeadNow · MAIN=$MainSha · CHANGED=" + $Changed.Count + " · NOTHING_STAGED=$NothingStaged · BRANCH_FREE=$BranchFree · 아래 표의 대처를 보세요" }
"CLONE_NOW=" + (git rev-parse --abbrev-ref HEAD) + "@" + (git rev-parse --short HEAD) + " · ORIGINAL=$OrigBranch@$HeadNow"
```

**확인**: `LAST_STEP=push` · `STEP_EXIT=0` · `git log` 줄에 두 파일(`hint_sample_manifest.json`·
`hint_verdicts.jsonl`)만 보임 · `CLONE_NOW`가 `ORIGINAL`과 같음 · **`RESTORE_EXIT=0` ·
`MANIFEST_RESTORED=True` · `VERDICTS_RESTORED=True`**. `BRANCH=` 값을 세션에 전달한다.

**왜 복원하는가**: 원래 브랜치(main)에서 두 파일은 *미추적* 파일이고 새 브랜치에서는 *커밋된* 파일이다.
그래서 `git switch`로 돌아가는 순간 git이 두 파일을 작업 트리에서 **지운다**(EOS-210 확인 리뷰 실측).
그대로 두면 [E]를 다시 돌릴 때 판정 파일이 없어 처음부터 다시 묻고, [F]는 판정 파일 부재로 측정에
실패한다. 그래서 돌아간 직후 커밋본을 **작업 트리에만** 되살린다(`git restore --source=… --worktree` —
인덱스는 건드리지 않는다). `*_RESTORED=True`는 파일이 있고 그 내용이 커밋본과 같다는 뜻이다(git blob
해시 대조).

| 증상 | 뜻 | 대처 |
|---|---|---|
| `CHANGED=0` | 이번 실행으로 바뀐 기록이 없다(이미 커밋됨) | 커밋할 것이 없다. 그대로 끝 |
| `NOTHING_STAGED=False` | 공유 클론에 **다른 작업의 스테이징**이 있다 | 건드리지 말고 출력 전달 — 그 스테이징의 주인을 세션이 확인한다 |
| `BRANCH_FREE=False` | 같은 이름의 브랜치가 이미 있다(앞선 실행이 만들었거나 push까지 됐다) | 다시 붙여넣지 말고 출력 전달 — `REMOTE_RC=0`이면 이미 push된 것이고, 판정을 더 했으면 세션이 그 브랜치에 이어 올리는 절차를 따로 준다 |
| `REMOTE_RC`가 0·2가 아님 | 원격 조회 자체가 실패(네트워크·인증) | 쓰기는 거부됐다. 연결을 확인하고 [G] 재실행 |
| `WRITE_STOPPED=True` | 표시된 단계에서 멈췄고 뒤 단계는 안 돌았다 | 출력 전체 전달. `LAST_STEP=push`면 커밋은 로컬 브랜치에 있고 두 파일은 복원됐다(`*_RESTORED`로 확인). `LAST_STEP=commit`이면 두 파일이 **스테이징된 채** 원래 브랜치로 넘어왔을 수 있다 — 직접 고치지 말고 출력 전달. 클론은 원래 위치로 되돌렸다(`CLONE_NOW`로 확인) |
| `MANIFEST_RESTORED=False` 또는 `VERDICTS_RESTORED=False` | 작업 트리 복원이 안 됐다 | **[E]·[F]를 다시 돌리지 않는다**(빈 파일로 다시 묻게 된다). 기록은 브랜치 커밋에 안전하게 있다. 출력 전달 — 세션이 복원 명령을 따로 준다 |
| 다시 판정한 뒤 [G]를 또 돌림 | 같은 브랜치가 이미 있어 `BRANCH_FREE=False`로 거부된다 | 의도된 거부다. 추가 판정분을 같은 브랜치에 올리는 절차는 세션에 요청 |

### 판정 중 주의 (R19-01 맹검 — 도구 밖에서 깨지 않기)

도구는 기계 판정을 보여 주지 않지만, **파일을 직접 열면** 그 보호가 사라진다. 판정 세션이 끝날 때까지:

- `data\runs\<회차>-review\hint_sample_manifest.json`을 열지 않는다 — `machine_undecided_hint_ids`가 곧
  "기계가 판정하지 못한 힌트" 목록이다.
- `data\runs\<회차>-*\cu.hints.jsonl`을 열지 않는다 — 각 줄의 `gate_report`가 게이트(기계) 판정이다.
- `hint_verdicts.jsonl`을 열지 않는다 — 다른 판정자의 판정과 근거가 들어 있다.
- **우회 판정 누설(`HINT_HUMAN_BYPASSED_LEAK=` 줄)을 해소하는 길은 하나뿐이다** — 그 힌트의 *내용*이
  바뀌어(재저작) 지문이 달라지면 그 행은 낡음으로 빠진다. 판정 파일에서 행을 **지우거나 고치지 않는다**
  (append 전용 — 지우면 위조와 구별할 수 없다). 내용이 그대로면 세션에 전달해 재저작 여부를 Kiki가 정한다.
- **[F] 측정 뒤의 재판정은 맹검이 아니다.** [F] 출력의 `HINT_HUMAN_MISMATCH`·`HINT_HUMAN_DISAGREEMENT` 줄이
  기계 판정과 다른 판정자의 판정을 보여 준다. 그것을 본 뒤 `--rejudge`로 다시 판정하면 그 판정은 기계·타인
  판정을 본 상태의 판정이다 — 재판정이 필요하면 [F] 출력을 보지 않은 **다른 판정자**에게 맡기거나, 세션에
  알려 그 사실을 기록에 남긴다.

---

## 7. 이 문서가 검증한 것과 못 한 것

**검증함(Linux 샌드박스 · hermetic 테스트)**

- 도구·측정기 로직: `tests/backend/harness/test_hint_verdict_session.py`(맹검 출력 단언·입력 잠금·기록
  실패 정지·재개·재판정 이력) · `tests/backend/ops/test_hint_human_verdicts.py`(기록 계약·표본 결정론·
  매니페스트 변조 거부·의미 축 n/k/상한·종료 코드).
- 블록 형식: `scripts/ops/check_runbook_blocks.py`(쓰기 가드·대화형 단독)·`scripts/ops/check_ps_scripts.py`
  (괄호·정의 순서·UTF-8 강제) 정적 검사.

**못 함**

- **PowerShell 실제 실행**: 이 샌드박스에서 Windows PowerShell을 돌릴 수 없다. 특히 [E]의 대화형 입력
  (한국어 근거 입력·콘솔 인코딩)과 [G]의 git 브랜치 조작은 실기에서 처음 돈다. 첫 실행에서 이상이 보이면
  출력 전체를 전달해 달라.
- **실데이터**: EOS-211 라이브 산출물(`cu.hints.jsonl`)이 아직 없다. 실제 모집단 크기(30 이상인지)와
  기계 판정 불가 수는 [D]에서 처음 나온다.
