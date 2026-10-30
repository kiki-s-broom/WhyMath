# EOS-219 — 힌트 정답 누설 판정 창 (Kiki 실행 런북)

> 판정 기준: 이 런북은 EOS-219 PR이 main에 병합된 뒤에만 쓴다. 판정 창 `harness/hint_verdict_gui`와
> AI 권고 파일 `data/runs/eos197-a6-review/hint_ai_recommendations.jsonl`이 그 PR로 main에 들어간다.
>
> EOS-210 런북(`eos210_hint_human_verdict_runbook.md`)의 [A]~[G]를 **대신한다**. 달라진 점은 세 가지다.
>
> 1. **판정 전용 폴더에서 실행한다** — 공유 클론 `C:\Users\kiki\Desktop\__AI\WhyMath`는 여러 세션이 같이
>    쓰는 작업 사본이라, 2026-10-30 판정 도중 다른 세션의 브랜치로 바뀌어 도구가 사라졌다. 판정은
>    `C:\Users\kiki\Desktop\__AI\WhyMath-eos210`(main 기준 별도 작업 폴더 · `git worktree`)에서 하고,
>    공유 클론의 브랜치·파일은 건드리지 않는다.
> 2. **입력 창(`Read-Host`)을 쓰지 않는다** — 회차 `eos197-a6`·판정자 `kiki`를 블록에 채워 두었다(2026-10-30
>    실측: `Read-Host`를 뒤 블록과 함께 붙여넣으면 빈 값이 들어갔다).
> 3. **판정은 Windows 팝업 창으로 한다** — AI 권고는 **남은 45건을 모두 판정(또는 건너뛰기)한 뒤 세션 끝에 한 번에** 창에 나온다
>    (헌법 R19-01 "검토 도구는 사람이 판정을 입력하기 전에 AI 참고 판정을 보여주지 않는다").

## 1. 과제 명칭

G3 "힌트 의미 누설 0"의 사람 판정 — 판정 전용 폴더 준비 → 표본 추출 → **팝업 창 판정** → 측정기 실행 →
판정 기록 커밋.

## 2. 목적

측정기 `ops/g3_content_measures`의 기계 축은 생성 게이트와 같은 검출기라 "누설 0"이 증명이 아니다. 사람이
(나) 의미 누설 표본 30건과 (가) 기계가 판정하지 못한 30건을 판정해 G3 의미 축 값을 만든다(두 묶음이 15건
겹쳐 실제 판정 대상은 **45건**). 결과는 G3 판정(11/22)의 입력이다 — **이 런북은 게이트를 닫지 않는다.**

AI 권고(세션이 45건 전부 미리 써 둔 판정과 이유)는 **판정 도중에는 하나도 보이지 않고**, 남은 항목을 모두
판정(또는 건너뛰기)한 뒤 마지막 화면에서 한 번에 공개된다 — 일치 수와 불일치 목록(힌트·사람 판정·AI 판정·이유).
불일치 목록은 판정자별 파일로 남는다. 중간에 창을 닫으면 권고는 공개되지 않는다. **모든 사람 판정은 권고를
보기 전에 기록되므로 맹검 판정 그대로다**(헌법 R19-01). 처음 설계는 건별 공개였으나, 이번 회차 권고 45건이
전부 같은 판정이라 첫 공개 뒤 나머지가 사실상 미리 드러나므로 세션 끝 공개로 바꿨다(독립 검토 H1).

## 3. 구체적 절차

| 단계 | 무엇이 일어나는가 | 쓰기 | 기대 출력(판정값) |
|---|---|---|---|
| W | 판정 전용 폴더를 main 기준으로 만든다(있으면 main으로 맞춘다) | 별도 폴더만 | `WT_MATCHES_MAIN=True` |
| B | 코드 출처·힌트 파일·권고 파일 확인 | 없음 | `ENV_OK=True` |
| D | 표본 추출 — 매니페스트 작성 | 매니페스트 1개 | `SAMPLE_OK=True` · `WORK_ITEMS=45` |
| E | **팝업 창 판정**(한 줄 블록) | 판정 1건마다 append | 창을 닫으면 `SESSION_REMAINING=0` |
| F | 측정기 실행 | `work\` 아래 리포트 JSON만 | `MEASURE_RAN=True` |
| G | 판정 기록 커밋·push(새 브랜치) | git 브랜치·커밋·push | `LAST_STEP=push` · `STEP_EXIT=0` |

**판정 창에서 하는 일** (1건에 1~2분 · 45건이면 약 45~90분 · 실측하지 못했다):

1. 창에 문항·정답·힌트 단계·힌트 본문과 **"무엇이 누설인가" 기준표**가 보인다.
2. **`1  누설`** 또는 **`2  누설 아님`** 버튼을 누른다(키보드 1·2도 된다). 항목이 뜬 뒤 2초 동안은 기록 버튼이
   잠겨 있다(실수 입력 방지).
3. **근거**를 한 줄 적고 **`기록`**을 누르면 확인 창이 뜬다 — `예`를 누르면 판정 파일에 1건이 기록된다.
4. 기록되면 "기록했습니다"만 보이고 다음 항목으로 넘어간다(AI 권고는 이때 보이지 않는다). Enter 키로도 기록할 수 있다.
5. 판단이 어려우면 **`건너뛰기`**, 그만두려면 **`종료`** 또는 창 닫기. 그때까지의 판정은 남고, [E]를 다시
   붙여넣으면 남은 항목부터 이어서 한다. 중간에 닫으면 AI 권고는 공개되지 않는다.
6. 마지막 항목까지 끝나면 **결과 화면**에 AI 권고와의 일치 수·불일치 목록이 나온다. 판정은 여기서 바꿀 수
   없다. **`닫기`**를 누른다.

## 4. 성공 기준

| 단계 | 성공 | 실패 신호 → 대처 |
|---|---|---|
| W | `WT_MATCHES_MAIN=True` | `WORKTREE_UPDATE_SKIPPED=True`이면서 `DIRTY`가 0이 아님 — 그 폴더에 앞선 판정 기록이 있다. 지우지 말고 출력 전체를 세션에 전달 |
| B | `ENV_OK=True` · `RECS_FILE=True` · 경로 3줄이 `…\WhyMath-eos210\src\backend\`로 시작 | `CODE_OK=False` — 다른 폴더의 코드가 돌았다 · `RECS_FILE=False` — EOS-219 PR이 아직 main에 없다. 출력 전달 |
| D | `SAMPLE_OK=True` · `WORK_ITEMS=45` · `SAMPLE_ID=hvs-6bfbb1baa75f6e34` | `INPUT_ERROR=다른 매니페스트가 이미 있다` — 출력 전달 |
| E | 창을 닫은 뒤 `SESSION_REMAINING=0` · `AI_RECS_LOADED=45` · `AI_RECS_STALE=0` · `AI_AGREE`·`AI_DISAGREE` 줄 · `GUI_EXIT=0` | `GUI_UNAVAILABLE=` — 창을 띄울 수 없다(출력 전달) · `WRITE_PREFLIGHT_FAILED` — 판정 파일을 다른 프로그램이 열고 있다(닫고 [E] 재실행) · `INPUT_ERROR=권고 파일 —` — 권고 파일 손상(출력 전달) |
| F | `MEASURE_RAN=True` | `HINT_HUMAN_INPUT_ERRORS`가 0이 아님 — 판정 파일 손상. **손으로 고치지 말고** 출력 전달 |
| G | `LAST_STEP=push` · `STEP_EXIT=0` · `git log` 줄에 세 파일만 | `WRITE_REFUSED=True` — 같은 줄의 False 항목을 보고 출력 전달 · `WRITE_STOPPED=True` — 멈춘 단계 뒤는 실행되지 않았다. 출력 전달 |

**측정 결과 읽는 법**([F] 출력): `HINT_SEMANTIC_AXIS=PASS`면 표본 30건에서 누설 0이고
`HINT_SEMANTIC_WILSON_UPPER_95`가 보증 상한이다(0/30이어도 약 0.083). `FAIL`이면 누설이 1건 이상이다.
`MEASURE_EXIT`가 0·1·2 중 무엇이든 **이 런북의 실패가 아니다** — 값 그대로 세션에 전달한다.

## 5. 실행 환경

- **머신**: Phaiakes9(= Kiki의 작업 PC · 별도 접속 없음)
- **시스템**: Windows PowerShell(WSL 아님) — 판정 창은 Windows 팝업 창으로 뜬다
- **작업 디렉터리**: 판정 전용 폴더 `C:\Users\kiki\Desktop\__AI\WhyMath-eos210`(블록이 스스로 `cd`한다)
- **파이썬**: 공유 클론의 `C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe`를 쓰고,
  코드는 `PYTHONPATH`로 판정 전용 폴더의 것을 읽는다([B]가 실제로 읽힌 경로를 출력해 확인한다)
- **선행 조건**: EOS-219 PR이 main에 병합됨. DB·서버·Docker 불필요(파일만 읽고 쓴다)

## 6. 창 구분

**새 PowerShell 창 하나**에서 [W]~[G]를 순서대로 한다. 뒤 블록이 앞 블록의 변수를 읽으므로 **같은 창을
유지**한다(창을 바꾸면 쓰기 블록이 스스로 거부한다). **[E]는 한 줄짜리 블록이며 혼자 붙여넣는다.** [E]를
붙여넣으면 판정 팝업 창이 따로 뜨고, PowerShell 창은 판정 창을 닫을 때까지 기다린다 — 그동안 PowerShell
창에는 아무것도 붙여넣지 않는다.

---

## 실행 블록

> 자리표시자가 없다(회차·판정자·폴더를 채워 두었다). **블록 하나씩** 붙여넣고 판정값을 확인한 다음
> 넘어간다. 쓰기 블록([W]·[D]·[E]·[G])은 선행 판정을 스스로 다시 검사해 조건이 안 맞으면 거부한다.

### [W] 판정 전용 폴더 준비 (공유 클론의 브랜치·파일은 그대로)

```powershell
# [Windows PowerShell · Phaiakes9] 새 창 · W 판정 전용 폴더 준비 (별도 폴더만 쓴다)
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath-eos210"
$WtExisted = Test-Path $Wt
if (-not $WtExisted) { git worktree add --detach $Wt origin/main; "WORKTREE_ADD_EXIT=$LASTEXITCODE" } else { "WORKTREE_KEPT=True — 이미 있는 폴더를 씁니다(WT_EXISTED=$WtExisted)" }
$WtDirty = @(git -C $Wt status --porcelain).Count
$WtStale = ((git -C $Wt rev-parse HEAD) -ne (git rev-parse origin/main))
if ($WtStale -and ($WtDirty -eq 0)) { git -C $Wt checkout --detach origin/main; "WORKTREE_UPDATE_EXIT=$LASTEXITCODE" } else { "WORKTREE_UPDATE_SKIPPED=True — STALE=$WtStale · DIRTY=$WtDirty (STALE=False면 이미 최신 · DIRTY가 0이 아니면 앞선 판정 기록이 있으니 출력을 세션에 전달)" }
$WtMatchesMain = ((git -C $Wt rev-parse HEAD) -eq (git rev-parse origin/main))
"WT_HEAD=" + (git -C $Wt rev-parse --short HEAD) + " · ORIGIN_MAIN=" + (git rev-parse --short origin/main) + " · WT_MATCHES_MAIN=$WtMatchesMain · CLONE_HEAD(그대로)=" + (git rev-parse --short HEAD)
```

**확인**: `WT_MATCHES_MAIN=True`.

### [B] 환경 확인 (읽기 전용)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · B 코드 출처·힌트·권고 파일 확인 (읽기 전용)
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath-eos210"
cd $Wt
$Round = "eos197-a6"
$Reviewer = "kiki"
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = "$Wt\src\backend"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
function Get-KvMap([string[]]$Lines) { $Map = @{}; foreach ($L in $Lines) { if ($L -match '^([A-Z0-9_]+)=(.*)$') { $Map[$Matches[1]] = $Matches[2].Trim() } }; return $Map }
$WtHead = (git rev-parse --short HEAD)
$MainSha = (git rev-parse --short origin/main)
$HeadOk = ($WtHead -eq $MainSha)
$CodeFiles = @(& $Py -c "import whymath_backend.harness.hint_verdict_session as s, whymath_backend.harness.hint_verdict_gui as w, whymath_backend.ops.g3_content_measures as g; print(s.__file__); print(w.__file__); print(g.__file__)")
$CodeFiles
$CodeOk = ($CodeFiles.Count -eq 3) -and ($CodeFiles[0] -like "$Wt\src\backend\*") -and ($CodeFiles[1] -like "$Wt\src\backend\*") -and ($CodeFiles[2] -like "$Wt\src\backend\*")
$HintFiles = @(Get-ChildItem -Path "$Wt\data\runs" -Directory -Filter "$Round-*" | ForEach-Object { Join-Path $_.FullName "cu.hints.jsonl" } | Where-Object { Test-Path $_ })
$HintFiles
$HintArgs = @()
foreach ($F in $HintFiles) { $HintArgs += "--hints-jsonl"; $HintArgs += $F }
$ReviewDir = "$Wt\data\runs\$Round-review"
$Manifest = "$ReviewDir\hint_sample_manifest.json"
$Verdicts = "$ReviewDir\hint_verdicts.jsonl"
$Disagreements = "$ReviewDir\hint_ai_disagreements.$Reviewer.json"
$RecsFile = Test-Path "$ReviewDir\hint_ai_recommendations.jsonl"
$OutDir = "$Wt\work\eos210_$Round"
"WT_HEAD=$WtHead · ORIGIN_MAIN=$MainSha · HEAD_OK=$HeadOk · CODE_OK=$CodeOk · RECS_FILE=$RecsFile"
"ROUND=$Round · REVIEWER=$Reviewer · CU_HINTS_FILES=" + $HintFiles.Count + " · MANIFEST_EXISTS=" + (Test-Path $Manifest) + " · VERDICTS_EXISTS=" + (Test-Path $Verdicts)
$EnvOk = $HeadOk -and $CodeOk -and $RecsFile -and ($HintFiles.Count -eq 2)
"ENV_OK=$EnvOk"
```

**확인**: `ENV_OK=True`. 위에 찍힌 세 경로가 `C:\Users\kiki\Desktop\__AI\WhyMath-eos210\src\backend\`로 시작해야 한다.

### [D] 표본 추출 (조건 미충족이면 스스로 거부)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · D 표본 추출 (매니페스트 쓰기 · 조건 미충족이면 스스로 거부)
cd $Wt
$SampleReady = $EnvOk -and ((git rev-parse --short HEAD) -eq $WtHead) -and ((Get-Location).Path -eq $Wt)
"SAMPLE_READY=$SampleReady · ENV_OK=$EnvOk"
if ($SampleReady) { $SampleLines = @(& $Py -m whymath_backend.harness.hint_verdict_session sample --round $Round @HintArgs); $SampleExit = $LASTEXITCODE; $SampleLines } else { $SampleExit = -1; $SampleLines = @(); "WRITE_REFUSED=True — SAMPLE_READY=$SampleReady · ENV_OK=$EnvOk · [W]·[B]를 같은 창에서 먼저 실행하세요" }
$SampleMap = Get-KvMap $SampleLines
$SampleOk = ($SampleExit -eq 0) -and (Test-Path $Manifest) -and ($SampleMap["MANIFEST_WRITTEN"] -in @("True", "EXISTS_IDENTICAL"))
"SAMPLE_EXIT=$SampleExit · MANIFEST_ON_DISK=" + (Test-Path $Manifest) + " · SAMPLE_OK=$SampleOk"
```

**확인**: `SAMPLE_OK=True` · `WORK_ITEMS=45` · `SAMPLE_ID=hvs-6bfbb1baa75f6e34`(세션이 같은 데이터로 미리 계산한 값).

### [E] 팝업 창 판정 (이 한 줄만 붙여넣는다)

```powershell
if ($SampleOk -and ((Get-Location).Path -eq $Wt)) { & $Py -m whymath_backend.harness.hint_verdict_gui --round $Round @HintArgs --reviewer $Reviewer; "GUI_EXIT=$LASTEXITCODE" } else { "WRITE_REFUSED=True — SAMPLE_OK=$SampleOk · [D]를 같은 창에서 먼저 실행하세요" }
```

**확인**: 창을 닫으면 PowerShell 창에 요약이 찍힌다 — `SESSION_REMAINING=0` · `AI_RECS_LOADED=45` ·
`AI_RECS_STALE=0` · `GUI_EXIT=0`. `AI_AGREE`·`AI_DISAGREE`는 사람 판정과 AI 권고가 같았던·달랐던 수다.
중간에 닫았으면 권고 비교 대신 `AI_COMPARE=WITHHELD`가 찍힌다(권고 비공개 — 정상).
중간에 멈췄으면 `SESSION_STATE=중단`과 남은 수가 찍힌다 — 이 한 줄을 다시 붙여넣으면 이어서 한다.

### [F] 측정기 실행 (읽기 전용 · 리포트는 `work\` 아래)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · F 측정기 (읽기 전용 · 리포트는 gitignore된 work 폴더)
cd $Wt
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$MeasureLines = @(& $Py -m whymath_backend.ops.g3_content_measures --round $Round @HintArgs --hint-verdicts $Verdicts --hint-sample-manifest $Manifest --json "$OutDir\g3_measures.json")
$MeasureExit = $LASTEXITCODE
$MeasureLines
$MeasureMap = Get-KvMap $MeasureLines
$MeasureRan = ($MeasureExit -in @(0, 1, 2)) -and ($MeasureMap["HINT_HUMAN_INPUT_ERRORS"] -eq "0") -and ([bool]$MeasureMap["HINT_SEMANTIC_AXIS"])
"MEASURE_EXIT=$MeasureExit · HINT_SEMANTIC_AXIS=" + $MeasureMap["HINT_SEMANTIC_AXIS"] + " · HINT_MACHINE_AXIS=" + $MeasureMap["HINT_MACHINE_AXIS"] + " · MEASURE_RAN=$MeasureRan"
```

**확인**: `MEASURE_RAN=True`. 출력 전체를 복사해 세션에 전달한다.

### [G] 판정 기록 커밋·push (판정 전용 폴더 안 · 조건 미충족이면 스스로 거부)

매니페스트·판정 기록·불일치 목록(`hint_ai_disagreements.kiki.json` — 45건을 다 끝냈을 때만 생긴다) **세 파일만** 새 브랜치에 커밋해 push한다. 공유 클론은 건드리지 않는다.
PR은 세션이 연다(브랜치 이름을 전달).

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · G 기록 커밋·push (판정 전용 폴더 안 · 조건 미충족이면 스스로 거부)
cd $Wt
$Branch = "eos210-hint-verdicts-$Round"
$Changed = @(git status --porcelain -- "data/runs/$Round-review")
git diff --cached --quiet
$NothingStaged = ($LASTEXITCODE -eq 0)
git rev-parse --verify --quiet "refs/heads/$Branch" *> $null
$LocalFree = ($LASTEXITCODE -ne 0)
git ls-remote --exit-code --heads origin $Branch *> $null
$RemoteRc = $LASTEXITCODE
$BranchFree = $LocalFree -and ($RemoteRc -eq 2)
$HeadNow = (git rev-parse --short HEAD)
$CommitReady = $MeasureRan -and $SampleOk -and ($HeadNow -eq $WtHead) -and ((Get-Location).Path -eq $Wt) -and (Test-Path $Manifest) -and (Test-Path $Verdicts) -and (Test-Path $Disagreements) -and ($Changed.Count -ge 1) -and $NothingStaged -and $BranchFree
"COMMIT_READY=$CommitReady · MEASURE_RAN=$MeasureRan · SAMPLE_OK=$SampleOk · CHANGED=" + $Changed.Count + " · NOTHING_STAGED=$NothingStaged · BRANCH_FREE=$BranchFree(LOCAL=$LocalFree REMOTE_RC=$RemoteRc)"
if ($CommitReady) {
  $Step = "switch"; git switch -c $Branch; $Rc = $LASTEXITCODE
  if ($Rc -eq 0) { $Step = "add"; git add -- $Manifest $Verdicts $Disagreements; $Rc = $LASTEXITCODE }
  if ($Rc -eq 0) { $Step = "commit"; git commit -m "EOS-210: 힌트 누설 사람 판정 기록 $Round" -- $Manifest $Verdicts $Disagreements; $Rc = $LASTEXITCODE }
  if ($Rc -eq 0) { $Step = "push"; git push -u origin $Branch; $Rc = $LASTEXITCODE }
  "LAST_STEP=$Step · STEP_EXIT=$Rc · BRANCH=$Branch · BRANCH_HEAD=" + (git rev-parse --short HEAD)
  if ($Rc -ne 0) { "WRITE_STOPPED=True — $Step 단계 실패(exit $Rc) · 뒤 단계는 실행하지 않았다. 출력 전체를 세션에 전달하세요" }
  if ($Rc -eq 0) { git log -1 --stat --oneline }
} else { "WRITE_REFUSED=True — COMMIT_READY=$CommitReady · 위 줄의 False 항목을 보고 출력 전체를 세션에 전달하세요" }
```

**확인**: `LAST_STEP=push` · `STEP_EXIT=0` · `git log` 줄에 세 파일(`hint_sample_manifest.json`·
`hint_verdicts.jsonl`·`hint_ai_disagreements.json`)만 보임. `BRANCH=` 값을 세션에 전달한다. 판정 전용 폴더는
세션이 PR을 병합한 뒤 정리 명령을 따로 준다(지금 지우지 않는다).

### 판정 중 주의 (맹검을 도구 밖에서 깨지 않기)

창은 판정 전에 기계 판정·AI 권고를 보여 주지 않지만, **파일을 직접 열면** 그 보호가 사라진다. 판정이 끝날
때까지 `WhyMath-eos210\data\runs\eos197-a6-*` 아래 파일을 열지 않는다 — 특히 `hint_ai_recommendations.jsonl`
(AI 권고 전부)·`hint_sample_manifest.json`(기계 판정 불가 목록)·`cu.hints.jsonl`(게이트 판정).

**알려진 한계**: 권고 파일이 판정 폴더 안에 있어, 파일을 직접 열면 맹검이 깨진다(위 경고만이 막는다).

**재실행 주의**: [G]까지 끝낸 뒤 PR이 병합되기 전에 [W]를 다시 돌리면 판정 전용 폴더가 main으로 되돌아가
판정 파일이 폴더에서 사라진다(기록은 push한 브랜치에 안전하다). [G] 뒤에는 [W]를 다시 돌리지 말고 세션에
알린다. 2026-10-30의 첫 시도는 [B]에서 멈춰 판정 기록이 만들어지지 않았다 — 이어받을 판정은 없다.

## 7. 이 문서가 검증한 것과 못 한 것

**검증함(Linux 샌드박스)**

- 판정 창의 판정 흐름(권고 잠금·입력 잠금·기록·불일치 보고): `tests/backend/harness/test_hint_verdict_gui.py`
  와 실데이터 45건 끝까지 돌린 제어기 실행(실제 `eos197-a6` 힌트 · `SAMPLE_ID=hvs-6bfbb1baa75f6e34` ·
  권고 45건 로드 · 낡은 권고 0). 그 판정 기록을 측정기가 입력 오류 0건으로 읽는 것까지 확인했다.
- 창 자체: 가상 디스플레이(Xvfb)에서 기록 버튼 잠금 → 판정 → 기록 → 다음 항목(권고 비공개) → 마지막 결과 화면
  (권고 공개), 그리고 중간 종료 시 권고 비공개(`AI_COMPARE=WITHHELD`).
- 블록 형식: `scripts/ops/check_runbook_blocks.py`·`scripts/ops/check_ps_scripts.py` 정적 검사.

**못 함**

- **Windows 실기 실행**: 이 샌드박스에서 Windows PowerShell과 Windows용 Tk 창을 띄울 수 없다. 한글 글꼴
  ("맑은 고딕")·창 크기·`git worktree` 조작은 Kiki PC에서 처음 돈다. 이상이 보이면 출력 전체를 전달해 달라.
