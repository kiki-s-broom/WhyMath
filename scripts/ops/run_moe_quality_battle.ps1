# OPS-48 QUALITY 티어 dense 27B ↔ MoE 정확도 축 강등전 실행기 (Phaiakes9 전용)
#
# 목적: qwen3.5:27b(dense)와 qwen3:30b-a3b(MoE)를 같은 결함 주입 시험지로 대조하여
#   검출률·오경보율·지연을 측정한다. 속도 6배가 정확도 하락을 정당화하지 않는지
#   Wilson 단측 경계로 판정한다.
#
# 사용법(리포 루트, PowerShell):
#   powershell -ExecutionPolicy Bypass -File .\scripts\ops\run_moe_quality_battle.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\ops\run_moe_quality_battle.ps1 -NDefective 100 -NClean 100
#
# OPS-50(후보 프롬프트 변형 재측정 — 기준 27B는 OPS-48 감사 파일에서 재사용):
#   $A = "data\audit\ops-48-moe-accuracy-battle-20260822_232452.jsonl"
#   powershell -ExecutionPolicy Bypass -File .\scripts\ops\run_moe_quality_battle.ps1 `
#       -NDefective 50 -NClean 50 -PromptVariant short_reason -BaselineAudit $A
#
# 선행 조건: Ollama for Windows 설치·기동 가능, qwen3.5:27b/qwen3:30b-a3b 모델 설치.
#   모델이 없으면 스크립트가 /api/tags로 확인 후 중단한다(자동 pull하지 않음).

[CmdletBinding()]
param(
    [string]$BaselineModel = "qwen3.5:27b",
    [string]$CandidateModel = "qwen3:30b-a3b",
    [int]$NDefective = 70,
    [int]$NClean = 70,
    [int]$Seed = 20260708,
    [string]$OllamaHost = "http://127.0.0.1:11434",
    [int]$TimeoutSec = 600,
    [string]$OutDir = "",
    # OPS-50 — 후보에 적용할 프롬프트 변형(baseline|short_reason|reason_first|stage_split|latex_check|few_shot).
    [string]$PromptVariant = "baseline",
    # OPS-50 — 기준 모델 결과를 이전 감사 JSONL에서 재사용(27B 재실행 생략). 시험지가 다르면 중단된다.
    [string]$BaselineAudit = "",
    # 후보가 기준보다 열등한지 판정하는 허용 마진. OPS-48 문서의 판정 마진은 0.05였다.
    [double]$NotWorseMargin = 0.0,
    # 후보 미분류율 상한(1.0=끔). OPS-50 ③은 0.05.
    [double]$MaxUnresolvedRate = 1.0,
    # exclude=A(미분류 제외) | worst=검출 B·오경보 C 최악 가정. 세 값은 리포트에 항상 병기된다.
    [string]$UnresolvedPolicy = "exclude"
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path (Join-Path $PSScriptRoot "..") "..")).Path
if ($OutDir -eq "") { $OutDir = Join-Path (Join-Path $RepoRoot "data") "audit" }
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
if ($PromptVariant -eq "baseline" -and $BaselineAudit -eq "") {
    $AuditOut = Join-Path $OutDir ("ops-48-moe-accuracy-battle-{0}.jsonl" -f $Timestamp)
}
else {
    $AuditOut = Join-Path $OutDir ("ops-50-moe-prompt-{0}-{1}.jsonl" -f $PromptVariant, $Timestamp)
}

# ── 헬퍼 (호출보다 먼저 정의) ────────────────────────────────────────────────
function Write-Head {
    param([string]$Text)
    Write-Host ""
    Write-Host ("=" * 72)
    Write-Host $Text
    Write-Host ("=" * 72)
}

function Get-CommitFreeGB {
    $free = (Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue).FreeVirtualMemory
    if ($null -eq $free) { return -1 }
    return [math]::Round($free / 1MB, 1)
}

function Stop-OllamaAll {
    $procs = @(Get-Process ollama, "ollama app", llama-server -ErrorAction SilentlyContinue)
    if ($procs.Count -gt 0) {
        Write-Host ("  종료 대상 프로세스 " + $procs.Count + "개")
        $procs | Stop-Process -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 4
    $left = @(Get-Process ollama, "ollama app", llama-server -ErrorAction SilentlyContinue)
    $free = Get-CommitFreeGB
    Write-Host ("  잔존 " + $left.Count + "개 · CommitFree_GB = " + $free)
    return $free
}

function Start-OllamaServer {
    param([string]$Base)
    $app = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"
    if (Test-Path $app) {
        Start-Process -FilePath $app | Out-Null
        Write-Host "  트레이 앱 기동"
    }
    else {
        Start-Process -FilePath "ollama" -ArgumentList @("serve") -WindowStyle Hidden | Out-Null
        Write-Host "  ollama serve 기동(백그라운드)"
    }

    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        try {
            $v = Invoke-RestMethod -Uri ($Base + "/api/version") -TimeoutSec 5 -ErrorAction Stop
            Write-Host ("  서버 응답 확인 — version " + $v.version)
            return $true
        }
        catch { Start-Sleep -Seconds 3 }
    }
    Write-Host "  [FAIL] 90초 안에 서버가 응답하지 않았다."
    return $false
}

function Test-ModelsInstalled {
    param([string]$Base, [array]$Models)
    $tags = Invoke-RestMethod -Uri ($Base + "/api/tags") -TimeoutSec 10 -ErrorAction Stop
    $installed = @($tags.models | ForEach-Object { $_.name })
    $missing = @($Models | Where-Object { $_ -notin $installed })
    if ($missing.Count -gt 0) {
        Write-Host ("  [FAIL] 설치되지 않은 모델: " + ($missing -join ", "))
        Write-Host "  Ollama pull로 설치 후 다시 실행하세요."
        return $false
    }
    Write-Host ("  설치 확인: " + ($Models -join ", "))
    return $true
}

function Set-BattleEnv {
    # OPS-48은 27B dense + 30B-A3B MoE를 번갈아 호출하므로 스왑을 막기 위해
    # MAX_LOADED_MODELS=2, KEEP_ALIVE=30m, CONTEXT=8192, NUM_PARALLEL=1, FLASH_ATTENTION=1.
    # 이 값들은 이전 세션(docs/ops/amd395_local_llm_performance.md §3 L6)의 확정 권장값이다.
    $map = @{
        OLLAMA_CONTEXT_LENGTH  = "8192"
        OLLAMA_NUM_PARALLEL    = "1"
        OLLAMA_FLASH_ATTENTION = "1"
        OLLAMA_MAX_LOADED_MODELS = "2"
        OLLAMA_KEEP_ALIVE      = "30m"
    }
    foreach ($k in $map.Keys) {
        $v = $map[$k]
        [Environment]::SetEnvironmentVariable($k, $v, "User")
        [Environment]::SetEnvironmentVariable($k, $v, "Process")
        Write-Host ("  {0,-26} = {1}" -f $k, $v)
    }
}

# ── 실행 ────────────────────────────────────────────────────────────────────
Write-Head "OPS-48 QUALITY 티어 dense ↔ MoE 정확도 축 강등전"
Write-Host "기준: $BaselineModel"
Write-Host "후보: $CandidateModel"
Write-Host "시험지: 결함 $NDefective · 무결함 $NClean · seed $Seed"
Write-Host "후보 프롬프트 변형: $PromptVariant"
if ($BaselineAudit -ne "") { Write-Host "기준 결과 재사용: $BaselineAudit" }
Write-Host "감사 출력: $AuditOut"

Write-Head "① Ollama 환경변수 적용"
Set-BattleEnv

Write-Head "② Ollama·고아 프로세스 종료"
$commitFree = Stop-OllamaAll
if ($commitFree -ge 0 -and $commitFree -lt 16) {
    Write-Host "  [WARN] CommitFree_GB가 16GB 미만입니다. 고아 프로세스가 남았거나 다른 프로세스가 메모리를 점유 중일 수 있습니다."
}

Write-Head "③ Ollama 재기동"
if (-not (Start-OllamaServer -Base $OllamaHost)) {
    exit 1
}

Write-Head "④ 모델 설치 확인"
# 기준 결과를 감사 파일에서 재사용하면 기준 모델은 호출하지 않으므로 설치 여부도 요구하지 않는다.
$NeededModels = @($CandidateModel)
if ($BaselineAudit -eq "") { $NeededModels = @($BaselineModel, $CandidateModel) }
if (-not (Test-ModelsInstalled -Base $OllamaHost -Models $NeededModels)) {
    exit 1
}

Write-Head "⑤ 강등전 실행"
$python = Join-Path (Join-Path (Join-Path $RepoRoot ".venv") "Scripts") "python.exe"
if (-not (Test-Path $python)) {
    $python = "python3"
    if (-not (Get-Command $python -ErrorAction SilentlyContinue)) { $python = "python" }
}

$argsList = @(
    "-m", "whymath_backend.harness.quality_tier_moe_accuracy_battle",
    "--baseline-model", $BaselineModel,
    "--candidate-model", $CandidateModel,
    "--n-defective", [string]$NDefective,
    "--n-clean", [string]$NClean,
    "--seed", [string]$Seed,
    "--ollama-host", $OllamaHost,
    "--timeout", [string]$TimeoutSec,
    "--concurrency", "1",
    "--require-candidate-not-worse-than-baseline",
    "--not-worse-margin", [string]$NotWorseMargin,
    "--prompt-variant", $PromptVariant,
    "--max-unresolved-rate", [string]$MaxUnresolvedRate,
    "--unresolved-policy", $UnresolvedPolicy,
    "--audit-out", $AuditOut
)
if ($BaselineAudit -ne "") {
    if (-not (Test-Path $BaselineAudit)) {
        Write-Host "  [FAIL] 기준 감사 파일이 없다: $BaselineAudit"
        exit 1
    }
    $argsList += @("--baseline-audit", $BaselineAudit)
}

Write-Host "  명령: $python $argsList"
& $python $argsList
$battleExit = $LASTEXITCODE

Write-Head "⑥ 종료"
if ($battleExit -eq 0) {
    Write-Host "[OK] 강등전 통과 — 후보 모델이 기준보다 열등하지 않음."
    Write-Host "  감사 파일: $AuditOut"
}
else {
    Write-Host "[FAIL] 강등전 미통과 — 후보 모델이 기준보다 검출률/오경보에서 열등하거나 게이트 임계 미달."
    Write-Host "  감사 파일: $AuditOut"
}
exit $battleExit
