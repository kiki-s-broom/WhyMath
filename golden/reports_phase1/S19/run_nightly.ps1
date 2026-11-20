# WhyMath S19 야간 시뮬레이터 — Kiki 머신(Phaiakes9) · 실제 LLM(튜터 OpenRouter · 학생 로컬 Ollama)
# 작업 스케줄러가 매일 03:30에 부른다(등록: golden/reports_phase1/S19/런북.md 블록 T).
# 같은 명령의 CI판(가짜 모드)은 .github/workflows/golden-sim-nightly.yml이다.
#
# 하는 일(차례대로 · 단계마다 한 줄씩 로그에 바로 쓴다 — 중간에 멈춰도 어디서 멈췄는지 남는다):
#   1) 코드: 공유 작업 사본(WhyMath)은 건드리지 않고, 따로 둔 작업 폴더 WhyMath-sim을 origin/<Ref>에 맞춘다
#   2) DB: 시연용 일회용 Postgres(docker whymath-demo-db · 55432)를 켜고 준비될 때까지 최대 60초 기다린다
#   3) 환경: 실제 LLM 모드(GOLDEN_FAKE_LLM 제거) · OpenRouter 키 존재(값은 찍지 않는다) · 시드 · 학생 모델
#   4) 학생 모델 예열(첫 적재가 학생 제한 30초를 넘지 않게)
#   5) 조건이 전부 True일 때만 러너 120세션(P1,P2,P5,P7) — 하나라도 False면 실행을 거부하고 이유를 쓴다
# 결과: C:\Users\kiki\Desktop\__AI\sim-nightly\out\<날짜>\  (sim_report.json · run_meta.json · sessions.jsonl · errors.jsonl)
# 로그: C:\Users\kiki\Desktop\__AI\sim-nightly\logs\<날짜>.log (단계 줄) · <날짜>.sim.txt (러너 출력 그대로)
# 종료 코드: 러너 것 그대로(0 = 차단 기준 통과 · 1 = 차단 위반) · -1 = 실행 거부
param([string]$Ref = "main")

$ScriptVersion = "S19-1"
$Root = "C:\Users\kiki\Desktop\__AI"
$Main = "$Root\WhyMath"
$Wt = "$Root\WhyMath-sim"
$NightDir = "$Root\sim-nightly"
$Date = Get-Date -Format "yyyy-MM-dd"
$OutDir = "$NightDir\out\$Date"
$LogDir = "$NightDir\logs"
$Log = "$LogDir\$Date.log"
$SimLog = "$LogDir\$Date.sim.txt"
$Model = "qwen2.5:7b"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

function Write-Step([string]$Text) {
  $Line = "$(Get-Date -Format 'HH:mm:ss') $Text"
  Add-Content -Path $Log -Value $Line -Encoding UTF8
  Write-Host $Line
}

Write-Step "START version=$ScriptVersion ref=$Ref"

# 1) 코드 — WhyMath-sim 작업 폴더를 origin/<Ref>에 맞춘다(공유 작업 사본의 브랜치·미커밋 변경은 그대로)
git -C $Main fetch -q origin $Ref
$Expected = git -C $Main rev-parse "origin/$Ref" 2>$null
git -C $Main worktree prune
if (Test-Path "$Wt\.git") { git -C $Wt checkout -q --detach --force $Expected } else { git -C $Main worktree add -q --detach $Wt $Expected }
$WtHead = git -C $Wt rev-parse HEAD 2>$null
$HeadLine = git -C $Wt log -1 --oneline 2>$null
$HeadOk = [bool]$Expected -and ($WtHead -eq $Expected)
$HasRunner = Test-Path "$Wt\src\backend\golden\sim\run.py"
Write-Step "HEAD=$HeadLine"
Write-Step "EXPECTED=$Expected HEAD_OK=$HeadOk HAS_RUNNER=$HasRunner"

# 2) DB — 공유 작업 사본의 compose 파일로 켠다(낮 런북과 같은 프로젝트 이름 · 컨테이너 이름 고정)
docker compose -f "$Main\docker-compose.demo.yml" up -d 2>&1 | Out-Null
$DbReady = $false
for ($i = 0; $i -lt 30; $i++) {
  docker exec whymath-demo-db pg_isready -U whymath -d whymath 2>&1 | Out-Null
  if ($LASTEXITCODE -eq 0) { $DbReady = $true; break }
  Start-Sleep -Seconds 2
}
Write-Step "DB_READY=$DbReady"

# 3) 환경 — 실제 LLM 모드. 키 값은 찍지 않고 있는지만 본다
$Py = "$Main\src\backend\.venv\Scripts\python.exe"
$PyOk = Test-Path $Py
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:55432/whymath?ssl=disable"
Remove-Item Env:GOLDEN_FAKE_LLM -ErrorAction SilentlyContinue
Remove-Item Env:SIM_FULL -ErrorAction SilentlyContinue
$env:GOLDEN_SIM_SEED_DIR = "$Main\golden\sim\seed"
$env:GOLDEN_SIM_STUDENT_MODEL = $Model
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$KeyOk = (-not [string]::IsNullOrEmpty($env:WHYMATH_OPENROUTER_API_KEY)) -or (-not [string]::IsNullOrEmpty($env:OPENROUTER_API_KEY))
$SeedOk = Test-Path "$Main\golden\sim\seed\utterances.txt"
$Tags = @(ollama list 2>$null | Select-Object -Skip 1 | ForEach-Object { ($_ -split '\s+')[0] } | Where-Object { $_ })
$HasModel = $Tags -contains $Model

# 4) 학생 모델 예열 — 첫 호출의 모델 적재 시간을 미리 쓴다
if ($HasModel) { ollama run $Model "hi" 2>&1 | Out-Null }

# 5) 실행 모듈이 작업 폴더의 것인지(공유 .venv가 다른 폴더 코드를 잡지 않았는지) 확인
Set-Location "$Wt\src\backend"
$ModFile = ""
if ($PyOk -and $HasRunner) { $ModFile = & $Py -c "import golden.sim.run as m; print(m.__file__)" 2>$null }
$ModOk = [string]$ModFile -like "$Wt\*"
Write-Step "PY_OK=$PyOk KEY_OK=$KeyOk SEED_OK=$SeedOk HAS_MODEL=$HasModel MODULE_FROM_WORKTREE=$ModOk"

$SimExit = -1
if ($HeadOk -and $HasRunner -and $DbReady -and $PyOk -and $KeyOk -and $SeedOk -and $HasModel -and $ModOk) {
  # cmd를 거쳐 파일로 바로 쓴다 — PowerShell 5.1이 출력을 cp949로 다시 인코딩하지 않게(PYTHONUTF8=1)
  cmd /c "$Py -m golden.sim.run --sessions 120 --personas P1,P2,P5,P7 --date $Date --out-dir $OutDir > $SimLog 2>&1"
  $SimExit = $LASTEXITCODE
  $Done = @(Get-Content -Path $SimLog -Encoding UTF8 | Where-Object { $_ -like "SIM_DONE*" })
  Write-Step "SIM_DONE_LINES=$($Done.Count) $($Done -join ' ')"
} else {
  Write-Step "RUN_REFUSED=True — 위 두 줄에서 False인 항목을 본다: HEAD_OK(브랜치 갱신 실패) HAS_RUNNER(그 브랜치에 S19 러너 없음 — main이면 S19 미머지) DB_READY(Docker Desktop 꺼짐) PY_OK(.venv 없음) KEY_OK(OpenRouter 키 없음) SEED_OK(S16 시드 없음) HAS_MODEL(qwen2.5:7b 없음) MODULE_FROM_WORKTREE(다른 폴더 코드가 잡힘)"
}
Write-Step "SIM_EXIT=$SimExit (0=차단 기준 통과 / 1=차단 위반 / 2=인자 오류 / -1=실행 거부) OUT=$OutDir"
Set-Location $Root
exit $SimExit
