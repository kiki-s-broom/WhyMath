# OPS-30 — 업타임 프로브 + 알림 채널 연결 (Kiki 실행)

> 코드는 `src/backend/whymath_backend/ops/uptime_probe.py`(프로브·S4 계산)와 `ops/alert_delivery.py`
> (알림 웹훅)에 있다. 이 런북은 **Kiki 머신에서만 할 수 있는 두 가지**를 한다: ①알림이 도착할
> 채널(웹훅 URL)을 연결하고 ②1분 주기 프로브를 Windows 작업 스케줄러에 올린다.
> 코드 쪽 변별력은 이미 실측했다(서버를 `kill -9`로 죽였을 때 다운이 기록되고 알림이 수신기에
> 도달, 정상 상태에선 조용 — 2026-10-09). **이 런북의 PowerShell 블록은 Linux 세션에서 실행해
> 보지 못했다** — 각 블록의 자가검증 출력이 판정한다.

## 1. 과제 명칭

업타임 프로브 상시 가동 + 알림 채널(웹훅) 연결.

## 2. 목적

지금까지 모든 지표는 **서버가 살아 있을 때만** 나왔다 — 죽은 서버는 자기 죽음을 보고하지 못한다.
이 과제가 끝나면 ①서버 프로세스 밖에서 1분마다 `/health/ready`를 확인해 기록(JSONL)이 쌓이고
②서버가 죽거나 복구될 때, 그리고 서버가 에러율·지연 임계를 넘길 때 **로그가 아니라 채널(Slack 등)로
메시지가 온다**. 쌓인 기록으로 SLO S4(학습창 가용성 99%)를 처음으로 계산할 수 있다.

## 3. 구체적 절차

블록 5개다. **[A]는 조회, [B]는 환경변수 쓰기, [C]는 발송 1건, [D]는 스케줄러 등록, [E]는 조회**다.

- **[A] 사전 점검** (10초) — main에 OPS-30 코드가 들어와 있고 이 클론이 그것과 같은지, 프로브를 돌릴
  파이썬을 찾는다. 조회만 한다.
- **[B] 웹훅 URL 등록** (30초) — 채널의 수신 웹훅 URL을 붙여넣어 User 환경변수
  `WHYMATH_OPS_ALERT_WEBHOOK_URL`로 저장한다. 입력은 화면에 보이지 않는다.
- **[C] 채널 시험** (5초) — 장애 없이 시험 메시지 1건을 보낸다. 채널에서 메시지가 **눈에 보여야**
  마지막 1홉이 연결된 것이다.
- **[D] 스케줄러 등록** (20초) — 작업 `WhyMath-UptimeProbe`를 1분 주기로 등록한다.
- **[E] 가동 확인** (등록 후 3분 대기) — 기록이 실제로 쌓이는지, 스케줄러 환경에서 채널 설정이
  보이는지 본다.

웹훅 URL 만드는 법(Slack 기준): 채널용 앱의 「Incoming Webhooks」를 켜고 채널을 고른 뒤 나오는
`https://hooks.slack.com/services/…` 주소. Discord라면 채널 설정 → 연동 → 웹후크 URL 뒤에 `/slack`을
붙인 주소를 쓴다. **이 URL이 곧 암호다** — 채팅·커밋·스크린샷에 붙이지 않는다.

## 4. 성공 기준

- **[A]**: `PROBE_READY=True`. `False`면 같은 줄에 어느 조건이 False였는지 적힌다 — 그 줄을 회신.
- **[B]**: `WEBHOOK_SAVED=True`와 `READBACK_LENGTH=<숫자>`(0이 아님). `WRITE_REFUSED=True`면 URL 형태가
  틀린 것이며 아무것도 저장하지 않았다.
- **[C]**: `TEST_NOTIFY_EXIT=0` **그리고** 채널에 `알림 채널 시험` 메시지가 보인다. 둘 중 하나라도
  아니면 실패다 — `TEST_NOTIFY_EXIT=1`의 출력 `사유=`가 원인(`HTTP404`=URL 오류·`ConnectError`=네트워크).
- **[D]**: `TASK_REGISTERED=True`, `TASK_STATE=Ready`, `TASK_INTERVAL=PT1M`.
- **[E]**: `LAST_RECORD_AGE_S`가 120 미만, `LAST_OK=True`(서버가 떠 있을 때), `LAST_CHANNEL=configured`.
  `LAST_CHANNEL=unset`이면 스케줄러가 [B]의 환경변수를 못 보는 것이다 — 아래 6절 참조.
- 실패 시 대처: 어느 블록이든 출력의 `REFUSED`/`False` 줄을 그대로 회신하면 된다.

## 5. 실행 환경

- 머신: **Phaiakes9** (= 평소 쓰는 이 PC). 별도 접속 불요.
- 시스템: **Windows PowerShell**. [D]만 **관리자 권한 창**이 필요하다(작업 스케줄러 등록).
- 작업 디렉터리: `C:\Users\kiki\Desktop\__AI\WhyMath`
- 선행 조건: **OPS-30 PR이 main에 머지된 뒤**. 이 클론의 파이썬 가상환경에 `httpx`가 설치돼 있을 것
  (백엔드 의존성이라 이미 있다). 백엔드 서버(uvicorn)는 **켜져 있어야** [E]의 `LAST_OK=True`가 나온다.
- 한계 — 이 프로브는 **서버와 같은 PC에서 돈다**. PC가 꺼지면 서버도 프로브도 같이 죽으므로 그
  시간은 "다운 기록"이 아니라 **"기록 없음"**으로 남고, S4 리포트가 `INSUFFICIENT`(판정 보류)로 드러낸다.
  별도 호스트의 프로브는 이 과제 범위 밖이다.

## 6. 창 구분

**새 PowerShell 창 1개**에서 [A]→[B]→[C]를 순서대로 붙여넣는다. [D]는 **관리자 권한으로 연 새 창**에
붙여넣는다(이전 창과 별개 — 그 창에서도 [A]의 판정을 스스로 다시 계산한다). [E]는 아무 창이나 쓴다.
서버 점유 창이 없으므로 어느 창도 영구 점유되지 않는다.

> **스케줄러가 환경변수를 못 보는 경우**: [E]에서 `LAST_CHANNEL=unset`이면 [D]의 작업이 사용자 환경변수를
> 상속하지 못한 것이다(로그온 방식 문제). 이때 프로브는 **조용히 알림 없이** 돌아간다 — 그래서 매 기록에
> `channel`을 싣는다. 해결: 작업을 삭제하고(아래 [R]) 로그온한 상태로 [D]를 다시 실행한다.

---

## [A] 사전 점검 (조회만)

판정이 서로 가려지지 않게 **네 가지를 따로** 본다: ①main에 OPS-30 코드가 있는가 ②이 클론의 파일이 실재하고 main과 같은가
③httpx가 설치된 가상환경이 있는가 ④그 가상환경으로 모듈을 불러오는가. 머지 전에는 ①②④가 False이고 ③은 독립적으로
나온다(머지 전에도 가상환경이 있는지는 알 수 있다).

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin
"ORIGIN_MAIN=$(git rev-parse --short origin/main)  LOCAL_HEAD=$(git rev-parse --short HEAD)"
$ProbeRel = "src/backend/whymath_backend/ops/uptime_probe.py"
$DeliveryRel = "src/backend/whymath_backend/ops/alert_delivery.py"
git cat-file -e "origin/main:$ProbeRel" 2>$null
$ProbeInMain = ($LASTEXITCODE -eq 0)
git cat-file -e "origin/main:$DeliveryRel" 2>$null
$DeliveryInMain = ($LASTEXITCODE -eq 0)
$InMain = $ProbeInMain -and $DeliveryInMain
$Root = (Get-Location).Path
$Work = Join-Path $Root "src\backend"
$FilesOnDisk = (Test-Path (Join-Path $Root $ProbeRel)) -and (Test-Path (Join-Path $Root $DeliveryRel))
$SameAsMain = $false
if ($InMain -and $FilesOnDisk) { git diff --quiet origin/main -- $ProbeRel $DeliveryRel; $SameAsMain = ($LASTEXITCODE -eq 0) }
$Py = $null
foreach ($Cand in @((Join-Path $Root ".venv\Scripts\python.exe"), (Join-Path $Work ".venv\Scripts\python.exe"))) {
  if ((-not $Py) -and (Test-Path $Cand)) {
    & $Cand -c "import httpx" 2>$null
    if ($LASTEXITCODE -eq 0) { $Py = $Cand }
  }
}
$ModuleImports = $false
if ($Py) { Push-Location $Work; & $Py -c "import whymath_backend.ops.uptime_probe" 2>$null; $ModuleImports = ($LASTEXITCODE -eq 0); Pop-Location }
$Pyw = $null
if ($Py) { $Pyw = Join-Path (Split-Path $Py) "pythonw.exe" }
$HasPyw = [bool]($Pyw -and (Test-Path $Pyw))
$ProbeReady = $InMain -and $SameAsMain -and [bool]$Py -and $ModuleImports -and $HasPyw
"IN_MAIN=$InMain (probe=$ProbeInMain delivery=$DeliveryInMain)  FILES_ON_DISK=$FilesOnDisk  SAME_AS_MAIN=$SameAsMain"
"VENV_PY=$Py  MODULE_IMPORTS=$ModuleImports  PYTHONW_EXISTS=$HasPyw"
"PROBE_READY=$ProbeReady"
if (-not $ProbeReady) { "PROBE_READY=False — False인 항목을 그대로 회신해 주십시오. IN_MAIN=False면 OPS-30 PR이 아직 머지되지 않은 것이니 기다리면 됩니다(VENV_PY가 비어 있으면 별개 문제: httpx가 설치된 가상환경이 없음)." }
```

**`PROBE_READY=True`를 눈으로 확인한 다음에만 [B]를 붙여넣으십시오.**

## [B] 웹훅 URL 등록 (User 환경변수 쓰기)

입력은 화면에 **별표조차 보이지 않습니다**. 붙여넣고 Enter를 누르면 길이만 출력됩니다.

```powershell
$Secure = Read-Host "웹훅 URL을 붙여넣고 Enter (화면에 표시되지 않습니다)" -AsSecureString
$Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
$Url = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr)
$UrlLength = $Url.Length
$UrlScheme = ($Url -match "^https?://")
$UrlClean = (-not ($Url -match "…|여기에|\s"))
$UrlLongEnough = ($UrlLength -ge 20)
"INPUT_LENGTH=$UrlLength SCHEME_OK=$UrlScheme NO_PLACEHOLDER=$UrlClean LONG_ENOUGH=$UrlLongEnough"
$Ok = $UrlScheme -and $UrlClean -and $UrlLongEnough
if ($Ok) { [Environment]::SetEnvironmentVariable("WHYMATH_OPS_ALERT_WEBHOOK_URL", $Url, "User"); $Back = [Environment]::GetEnvironmentVariable("WHYMATH_OPS_ALERT_WEBHOOK_URL", "User"); "WEBHOOK_SAVED=$($Back -eq $Url) READBACK_LENGTH=$($Back.Length)" } else { "WRITE_REFUSED=True — SCHEME_OK=$UrlScheme NO_PLACEHOLDER=$UrlClean LONG_ENOUGH=$UrlLongEnough. 아무것도 저장하지 않았습니다. 붙여넣기가 비었거나 http(s)로 시작하지 않습니다." }
$Url = $null
```

**`WEBHOOK_SAVED=True`와 0이 아닌 `READBACK_LENGTH`를 눈으로 확인한 다음에만 [C]를 붙여넣으십시오.**

## [C] 채널 시험 (메시지 1건 발송)

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Root = (Get-Location).Path
$Work = Join-Path $Root "src\backend"
$Py = $null
foreach ($Cand in @((Join-Path $Root ".venv\Scripts\python.exe"), (Join-Path $Work ".venv\Scripts\python.exe"))) {
  if ((-not $Py) -and (Test-Path $Cand)) { $Py = $Cand }
}
$Saved = [Environment]::GetEnvironmentVariable("WHYMATH_OPS_ALERT_WEBHOOK_URL", "User")
$HasUrl = [bool]$Saved
"PY=$Py HAS_SAVED_URL=$HasUrl"
if ($Py -and $HasUrl) { $env:WHYMATH_OPS_ALERT_WEBHOOK_URL = $Saved; Push-Location $Work; & $Py -m whymath_backend.ops.uptime_probe test-notify; "TEST_NOTIFY_EXIT=$LASTEXITCODE"; Pop-Location } else { "SEND_REFUSED=True — PY=$Py HAS_SAVED_URL=$HasUrl. [A]의 가상환경 판정과 [B]의 저장이 먼저입니다." }
```

**`TEST_NOTIFY_EXIT=0`이고 채널에 시험 메시지가 보이는 것을 눈으로 확인한 다음에만 [D]를 붙여넣으십시오.**

## [D] 스케줄러 등록 (**관리자 권한 새 창**)

작업은 로그온한 사용자 권한으로, 콘솔 창이 뜨지 않는 `pythonw.exe`로 1분마다 돕니다.
기록 파일은 `work\ops30\uptime.jsonl`(저장소가 무시하는 폴더)에 쌓입니다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$Root = (Get-Location).Path
$Work = Join-Path $Root "src\backend"
$Pyw = $null
foreach ($Cand in @((Join-Path $Root ".venv\Scripts\pythonw.exe"), (Join-Path $Work ".venv\Scripts\pythonw.exe"))) {
  if ((-not $Pyw) -and (Test-Path $Cand)) { $Pyw = $Cand }
}
$SavedUrl = [bool][Environment]::GetEnvironmentVariable("WHYMATH_OPS_ALERT_WEBHOOK_URL", "User")
$LogDir = Join-Path $Root "work\ops30"
$Log = Join-Path $LogDir "uptime.jsonl"
$Name = "WhyMath-UptimeProbe"
"ADMIN=$Admin PYTHONW=$Pyw SAVED_URL=$SavedUrl"
$Go = $Admin -and [bool]$Pyw -and $SavedUrl
if ($Go) {
  New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
  $Arg = "-m whymath_backend.ops.uptime_probe probe --url http://127.0.0.1:8000/health/ready --log `"$Log`""
  $Action = New-ScheduledTaskAction -Execute $Pyw -Argument $Arg -WorkingDirectory $Work
  $Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
  $Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
  $Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
  try { Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force -ErrorAction Stop | Out-Null } catch { "REGISTER_ERROR=$($_.Exception.GetType().Name) $($_.Exception.Message)" }
  $T = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
  "TASK_REGISTERED=$([bool]$T) TASK_STATE=$($T.State) TASK_INTERVAL=$($T.Triggers[0].Repetition.Interval) TASK_EXECUTE=$($T.Actions[0].Execute)"
} else {
  "REGISTER_REFUSED=True — ADMIN=$Admin PYTHONW=$Pyw SAVED_URL=$SavedUrl. 관리자 권한 창이 아니면 ADMIN=False입니다(시작 메뉴에서 PowerShell을 우클릭 → 관리자 권한으로 실행). 아무것도 등록하지 않았습니다."
}
```

**`TASK_REGISTERED=True` `TASK_STATE=Ready` `TASK_INTERVAL=PT1M`을 눈으로 확인한 다음에만 3분 기다렸다가 [E]를 붙여넣으십시오.**

## [E] 가동 확인 (조회만 — 등록 후 3분 대기)

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Log = Join-Path (Get-Location).Path "work\ops30\uptime.jsonl"
$Exists = Test-Path $Log
"LOG_EXISTS=$Exists"
if ($Exists) {
  $Lines = @(Get-Content $Log -Tail 3 -Encoding UTF8)
  $Last = $Lines[-1] | ConvertFrom-Json
  $Age = [int]((Get-Date).ToUniversalTime() - [datetime]::Parse($Last.ts).ToUniversalTime()).TotalSeconds
  "RECORDS_IN_TAIL=$($Lines.Count) LAST_TS=$($Last.ts) LAST_RECORD_AGE_S=$Age"
  "LAST_OK=$($Last.ok) LAST_ERROR=$($Last.error) LAST_CHANNEL=$($Last.channel) LAST_NOTICE=$($Last.notice)"
  "TASK_LAST_RESULT=$((Get-ScheduledTaskInfo -TaskName 'WhyMath-UptimeProbe').LastTaskResult)"
} else {
  "LOG_MISSING — 작업이 아직 한 번도 돌지 않았거나(등록 직후 1분 대기) 실행이 실패했습니다. TASK_LAST_RESULT=$((Get-ScheduledTaskInfo -TaskName 'WhyMath-UptimeProbe' -ErrorAction SilentlyContinue).LastTaskResult)"
}
```

> `LAST_OK=False`는 이 시각에 서버가 꺼져 있었다는 뜻이다(프로브 고장이 아니다). 그 경우 `LAST_NOTICE`가
> `down:sent`이고 채널에 "서버 다운 감지" 메시지가 와 있어야 한다 — **그것이 두 번째 실측**이다.
> 서버를 켜면(`run_demo.ps1`) 다음 분에 "서버 복구" 메시지가 온다.

## 일주일 뒤 — S4 계산 (조회만)

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath\src\backend
$Root = (Resolve-Path ..\..).Path
$Py = $null
foreach ($Cand in @((Join-Path $Root ".venv\Scripts\python.exe"), (Join-Path $Root "src\backend\.venv\Scripts\python.exe"))) {
  if ((-not $Py) -and (Test-Path $Cand)) { $Py = $Cand }
}
$Log = Join-Path $Root "work\ops30\uptime.jsonl"
"PY=$Py LOG_EXISTS=$(Test-Path $Log)"
if ($Py -and (Test-Path $Log)) { & $Py -m whymath_backend.ops.uptime_probe report --log $Log --days 7; "REPORT_EXIT=$LASTEXITCODE" } else { "REPORT_SKIPPED=True — PY 또는 기록 파일이 없습니다." }
```

판독: `PASS`는 창(매일 15:00–24:00 KST) 안 표본이 충분(≥90%)하고 가용성이 99% 이상이라는 뜻이다.
`INSUFFICIENT`는 **통과가 아니다** — 프로브가 못 돈 시간이 너무 많아 판정할 수 없다는 뜻이며(PC가 꺼져 있었던
시간 포함), `REPORT_EXIT=1`로 나온다.

## [R] 되돌리기 (필요할 때만 — 관리자 권한 창)

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$Before = [bool](Get-ScheduledTask -TaskName "WhyMath-UptimeProbe" -ErrorAction SilentlyContinue)
"ADMIN=$Admin TASK_PRESENT_BEFORE=$Before"
if ($Admin -and $Before) { Unregister-ScheduledTask -TaskName "WhyMath-UptimeProbe" -Confirm:$false; "TASK_PRESENT_AFTER=$([bool](Get-ScheduledTask -TaskName 'WhyMath-UptimeProbe' -ErrorAction SilentlyContinue))" } else { "UNREGISTER_REFUSED=True — ADMIN=$Admin TASK_PRESENT_BEFORE=$Before" }
```

기록 파일(`work\ops30\uptime.jsonl`)은 지우지 않는다 — S4의 원천 증거다.
