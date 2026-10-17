# 데모 DB 마이그레이션·낡은 DB 진단/초기화 함수 모음 (OPS-133) — run_demo.ps1이 dot-source로 읽는다.
#
# 배경: run_demo.ps1은 예전 whymath-demo-db 컨테이너를 *재기동*한다. 그 DB의 alembic_version이 main에
# 없는 리비전(닫힌 PR·미머지 브랜치에서 돌린 마이그레이션)을 기억하면 `alembic upgrade head`가
# "Can't locate revision identified by '...'"로 죽는데, 예전에는 throw 한 줄로 끝나 원인이 안 보였다
# (2026-10-12 G-ops106-gate2-live-sample 실측 · 리비전 79de95331710 = 닫힌 PR #880).
#
# 불변식(어기면 운영 DB를 건드릴 수 있다 — tests/infra/test_run_demo_stale_db_diagnosis.py가 동결):
#   ① 진단·초기화는 DATABASE_URL이 데모 DB(127.0.0.1:55432)일 때만 한다. 운영 DB는 어떤 경로로도
#      읽지도 지우지도 않는다 — 이 파일에는 운영 DB의 포트·컨테이너 이름이 한 번도 등장하지 않는다(정적 테스트가 동결).
#   ② 컴포즈 파일은 docker-compose.demo.yml만 받는다(서비스가 demo-db 하나뿐이라 down -v의 범위가 그 컨테이너로 한정).
#   ③ 초기화(down -v)는 자동이 아니다 — 명시 플래그 -ResetStaleDemoDb가 있고 판정이 STALE일 때만.
#   ④ 판정 불가(UNKNOWN)·정상(CLEAN)은 초기화하지 않는다("모른다"를 "낡았다"로 접지 않는다).
#
# 판정은 diagnose_stale_demo_db.py(파이썬)가 한다 — 이 파일은 DB 리비전을 가져와 넘기고 결과로 분기만 한다.

# 데모 DB 접속 주소인가 — 호스트 포트 55432(docker-compose.demo.yml)만 데모로 인정한다.
function Test-DemoDatabaseUrl {
  param([string]$Url)
  if (-not $Url) { return $false }
  return [bool]($Url -match '@(127\.0\.0\.1|localhost):55432/')
}

# 데모 컴포즈 파일인가 — 이름이 다르면(운영 파일 등) 진단·초기화를 하지 않는다.
function Test-DemoComposeFile {
  param([string]$ComposeFile)
  if (-not $ComposeFile) { return $false }
  return ((Split-Path $ComposeFile -Leaf) -eq "docker-compose.demo.yml")
}

# PG가 응답할 때까지 대기(최대 $TimeoutSeconds초). 준비되면 $true.
function Wait-DemoDbReady {
  param(
    [Parameter(Mandatory = $true)][string]$ComposeFile,
    [int]$TimeoutSeconds = 60
  )
  for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
    docker compose -f $ComposeFile exec -T demo-db pg_isready -U whymath -d whymath *> $null
    if ($LASTEXITCODE -eq 0) { return $true }
    Start-Sleep -Seconds 1
  }
  return $false
}

# alembic upgrade head를 backend 디렉터리에서 돌리고 종료 코드를 돌려준다.
# `| Out-Host`: 네이티브 stdout이 함수 반환값에 섞이지 않게 한다(반환값은 종료 코드 하나여야 한다).
function Invoke-AlembicUpgrade {
  param([Parameter(Mandatory = $true)][string]$BackendDir)
  Push-Location $BackendDir
  try {
    alembic -c alembic.ini upgrade head | Out-Host
    $code = $LASTEXITCODE
  } finally {
    Pop-Location
  }
  return [int]$code
}

# 데모 DB가 기억하는 alembic 리비전들을 읽는다(컨테이너 안 psql — 호스트 포트·URL과 무관하게 demo-db 서비스 한정).
# 반환: Ok(조회 성공 여부) · Revisions(문자열 배열)
function Get-DemoDbRevisions {
  param([Parameter(Mandatory = $true)][string]$ComposeFile)
  # 이 함수 안에서만 오류 즉시중단을 푼다 — psql이 "relation does not exist"를 stderr로 내도 호출자가 죽지 않게.
  $ErrorActionPreference = "Continue"
  $raw = @(docker compose -f $ComposeFile exec -T demo-db psql -U whymath -d whymath -tA -c "SELECT version_num FROM alembic_version" 2>$null)
  $ok = ($LASTEXITCODE -eq 0)
  $revs = @($raw | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
  return [pscustomobject]@{ Ok = $ok; Revisions = $revs }
}

# 낡은 데모 DB 판정. State: STALE(코드에 없는 리비전 있음) · CLEAN · UNKNOWN(판정 불가).
function Get-DemoDbStaleVerdict {
  param(
    [Parameter(Mandatory = $true)][string]$ComposeFile,
    [Parameter(Mandatory = $true)][string]$HelperPath,
    [string]$PythonExe = "python"
  )
  $q = Get-DemoDbRevisions -ComposeFile $ComposeFile
  if ((-not $q.Ok) -or ($q.Revisions.Count -eq 0)) {
    return [pscustomobject]@{ State = "UNKNOWN"; Unknown = @(); Detail = "데모 DB에서 alembic_version을 읽지 못했습니다(테이블 없음·컨테이너 미응답)." }
  }
  $argList = @($HelperPath, "--db-revisions") + $q.Revisions
  $line = (& $PythonExe @argList | Out-String).Trim()
  $rc = $LASTEXITCODE
  $unknown = @()
  if ($line -match 'UNKNOWN_REVISIONS=(\S*)') {
    $unknown = @($Matches[1] -split ',' | Where-Object { $_ })
  }
  if ($rc -eq 1) { return [pscustomobject]@{ State = "STALE"; Unknown = $unknown; Detail = $line } }
  if ($rc -eq 0) { return [pscustomobject]@{ State = "CLEAN"; Unknown = @(); Detail = $line } }
  return [pscustomobject]@{ State = "UNKNOWN"; Unknown = @(); Detail = "판정 헬퍼가 판정하지 못했습니다(exit=$rc): $line" }
}

# [2/6] 단계 본체: alembic upgrade head. 실패하면 원인을 진단하고, 낡은 데모 DB면 안내(또는 명시 플래그로 초기화).
function Invoke-DemoMigration {
  param(
    [Parameter(Mandatory = $true)][string]$BackendDir,
    [Parameter(Mandatory = $true)][string]$ComposeFile,
    [Parameter(Mandatory = $true)][string]$HelperPath,
    [Parameter(Mandatory = $true)][string]$DatabaseUrl,
    [switch]$ResetStaleDemoDb,
    [string]$PythonExe = "python"
  )

  $rc = Invoke-AlembicUpgrade -BackendDir $BackendDir
  if ($rc -eq 0) { return }

  Write-Host "  · alembic upgrade 실패(exit=$rc) — 원인 진단…"
  # 데모 DB가 아니면(WHYMATH_DEMO_DATABASE_URL 오버라이드 등) 이 파일은 그 DB를 판정도 초기화도 하지 않는다.
  if (-not ((Test-DemoDatabaseUrl -Url $DatabaseUrl) -and (Test-DemoComposeFile -ComposeFile $ComposeFile))) {
    throw "alembic upgrade 실패. (접속 대상이 데모 DB(127.0.0.1:55432)가 아니거나 컴포즈 파일이 데모용이 아니라 낡은 데모 DB 진단·초기화를 건너뜁니다. 위 alembic 오류를 확인하세요.)"
  }

  $v = Get-DemoDbStaleVerdict -ComposeFile $ComposeFile -HelperPath $HelperPath -PythonExe $PythonExe

  if ($v.State -eq "CLEAN") {
    throw "alembic upgrade 실패 — 데모 DB가 기억하는 리비전은 모두 현재 코드에 있습니다(낡은 DB 문제가 아님). 위 alembic 오류를 확인하세요."
  }
  if ($v.State -eq "UNKNOWN") {
    throw "alembic upgrade 실패 — 낡은 데모 DB인지 판정하지 못했습니다(모르는 것을 낡았다고 단정하지 않습니다): $($v.Detail)"
  }

  # STALE: 원인을 사람이 읽는 문장으로 낸다.
  Write-Host ""
  Write-Host "  ✖ 낡은 데모 DB: 데모 컨테이너(whymath-demo-db · 호스트 55432)의 DB가 현재 코드에 없는 리비전을 기억합니다."
  Write-Host "    코드에 없는 리비전: $($v.Unknown -join ', ')"
  Write-Host "    원인: 예전에 이 컨테이너를 닫힌 PR·미머지 브랜치 코드로 마이그레이션했고, 컨테이너가 지워지지 않은 채 재기동됐습니다."
  Write-Host "    운영 DB(별도 컨테이너)와는 무관합니다. 데모 DB는 일회용이라 지워도 됩니다."

  if (-not $ResetStaleDemoDb) {
    Write-Host ""
    Write-Host "    해소(데모 컨테이너를 볼륨째 지우고 새로 만듭니다 — 데모 DB 데이터는 사라집니다):"
    Write-Host "      .\scripts\demo\run_demo.ps1 -ResetStaleDemoDb"
    Write-Host "    (자동으로 지우지 않습니다 — 위 플래그를 직접 붙여 다시 실행해야만 초기화됩니다.)"
    throw "낡은 데모 DB 때문에 중단했습니다. 위 안내의 -ResetStaleDemoDb로 다시 실행하세요."
  }

  Write-Host "    -ResetStaleDemoDb 지정됨 — 데모 컨테이너만 볼륨째 제거하고 재생성합니다…"
  docker compose -f $ComposeFile down -v | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "데모 컨테이너 제거(down -v) 실패 — Docker Desktop 상태를 확인하세요." }
  docker compose -f $ComposeFile up -d demo-db | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "데모 컨테이너 재생성(up -d) 실패 — Docker Desktop 상태를 확인하세요." }
  if (-not (Wait-DemoDbReady -ComposeFile $ComposeFile)) { throw "재생성한 PG가 시간 내 준비되지 않음." }
  Write-Host "    · 새 데모 DB ready — alembic 재시도…"
  $rc2 = Invoke-AlembicUpgrade -BackendDir $BackendDir
  if ($rc2 -ne 0) { throw "데모 DB를 새로 만든 뒤에도 alembic upgrade가 실패했습니다(exit=$rc2) — 낡은 DB가 아니라 마이그레이션 자체의 문제입니다." }
}
