# =============================================================================
# WhyMath prod DB backup - scheduled task registration (OPS-31)
# =============================================================================
# Registers a Windows scheduled task that runs backup_whymath_pg.ps1 daily.
#
# Why this exists: until now the backup ran only when a human remembered to
# run it, and the runbook (section 6) recorded "schedule depends on logon" as
# a known hole. A logon-dependent task silently skips every day the operator
# does not sign in - and a skipped backup looks exactly like a healthy one.
#
# Two settings do the actual work here:
#   -LogonType S4U        run whether or not the user is logged on, WITHOUT
#                         storing a password (S4U = service-for-user). This is
#                         what removes the logon dependency.
#   -StartWhenAvailable   if the machine was off at trigger time, run as soon
#                         as it comes back instead of dropping the occurrence.
#
# Neither of those makes a missed run OBSERVABLE - that is what the status file
# written by backup_whymath_pg.ps1 and read by backup_status.py does. Scheduling
# reduces misses; the status check is what refuses to call silence success.
#
# So this script registers TWO tasks, and the second one is not optional:
#   <TaskName>        runs the backup
#   <TaskName>-Check  runs check_backup_freshness.ps1 a few hours later
# Registering only the backup would leave the ledger unread - and an unread
# ledger detects nothing. That was the state this file shipped in first
# (2026-09-01 PR #968 Codex P1 caught it): the runbook printed the check command
# for a human to remember, which is the same silent-miss failure mode wearing a
# different hat.
#
# ASCII ONLY - PowerShell 5.1 reads .ps1 in the OS locale encoding (cp949 on
# Korean Windows). Korean documentation lives in the runbook.
#
# Usage (Windows PowerShell, ELEVATED - task registration needs admin):
#   .\scripts\backup\register_backup_schedule.ps1
#   .\scripts\backup\register_backup_schedule.ps1 -At 03:30 -RequireEncryption
#   .\scripts\backup\register_backup_schedule.ps1 -RequireEncryption -OffsiteDir "C:\Users\kiki\Google Drive\WhyMath-backups"
#   .\scripts\backup\register_backup_schedule.ps1 -Unregister
#
# Exit codes: 0 = success, 1 = failure (reason printed).

param(
    # Daily run time, 24h "HH:mm".
    [string]$At = "04:00",
    # Task name in Task Scheduler.
    [string]$TaskName = "WhyMath-DB-Backup",
    # Passed through to backup_whymath_pg.ps1.
    [string]$BackupDir = "C:\Users\kiki\Desktop\__AI\WhyMath-backups",
    [int]$RetentionDays = 14,
    # Refuse to produce a plaintext backup (see runbook 4-1). Recommended once
    # the key pair exists.
    [switch]$RequireEncryption,
    # Daily run time for the freshness check, "HH:mm". Defaults to a few hours
    # after -At so a slow or retried backup is not reported as missing.
    [string]$CheckAt = "09:00",
    # Freshness threshold in hours. 48 tolerates one skipped daily run; a third
    # missed day is a real outage.
    [double]$CheckMaxAgeHours = 48,
    # Interpreter used by the check task. Kiki's machine has conda base and a
    # .venv active at once, so an explicit path may be required.
    [string]$PythonExe = "python",
    # Offsite mirror directory passed through to backup_whymath_pg.ps1. Empty
    # by default. When set, each successful encrypted run is mirrored there and
    # the same retention is applied to it - without this the offsite copy is a
    # one-time snapshot whose RPO grows without bound and whose expired files
    # outlive the retention window that runbook 4-3 declares as the PIPA
    # deletion bound.
    [string]$OffsiteDir = "",
    # Remove the task instead of creating it.
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"

function Fail([string]$Reason) {
    Write-Host "[FAIL] $Reason"
    exit 1
}

# ---------------------------------------------------------------------------
# Step 0a: elevation. Registering a task needs an elevated session; without it
# Register-ScheduledTask fails with "Access is denied" (HRESULT 0x80070005).
# We check FIRST so the operator is told what to do, instead of reading a
# stack trace halfway through a run that has already printed [OK] lines.
# (2026-09-06: this script printed two [OK] lines after exactly that failure.)
# ---------------------------------------------------------------------------
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Fail "this window is not elevated - scheduled task registration needs Administrator. Open a NEW PowerShell window with 'Run as administrator' and re-run the same command."
}

# ---------------------------------------------------------------------------
# Step 0: unregister path
# ---------------------------------------------------------------------------
if ($Unregister) {
    # Both tasks - removing only the backup would leave a checker that alerts
    # forever about a backup nobody asked for any more.
    $removed = 0
    foreach ($name in @($TaskName, "$TaskName-Check")) {
        $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if (-not $existing) {
            Write-Host "[OK] task '$name' does not exist - nothing to remove"
            continue
        }
        try {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction Stop
        } catch {
            Fail "Unregister-ScheduledTask failed for '$name': $($_.Exception.GetType().Name): $($_.Exception.Message)"
        }
        $still = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($still) {
            Fail "Unregister-ScheduledTask returned but '$name' is still registered."
        }
        Write-Host "[OK] task '$name' removed"
        $removed = $removed + 1
    }
    Write-Host "[OK] removed $removed task(s)"
    exit 0
}

# ---------------------------------------------------------------------------
# Step 1: resolve the backup script by absolute path
# The task runs with an unpredictable working directory, so a relative path
# would fail at trigger time and be discovered only by a missed backup.
# ---------------------------------------------------------------------------
$scriptPath = Join-Path $PSScriptRoot "backup_whymath_pg.ps1"
if (-not (Test-Path $scriptPath)) {
    Fail "backup script not found next to this file: $scriptPath"
}
$checkScriptPath = Join-Path $PSScriptRoot "check_backup_freshness.ps1"
if (-not (Test-Path $checkScriptPath)) {
    Fail "freshness check script not found next to this file: $checkScriptPath"
}

# ---------------------------------------------------------------------------
# Step 2: build the action
# ---------------------------------------------------------------------------
$argList = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -BackupDir `"$BackupDir`" -RetentionDays $RetentionDays"
if ($OffsiteDir) {
    $argList = "$argList -OffsiteDir `"$OffsiteDir`""
}
if ($RequireEncryption) {
    $argList = "$argList -RequireEncryption"
}
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argList

# ---------------------------------------------------------------------------
# Step 3: trigger + principal + settings
# S4U is the whole point: run without an interactive logon and without a
# stored password. RunLevel Highest is needed because the script talks to the
# Docker engine.
# ---------------------------------------------------------------------------
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)

# ---------------------------------------------------------------------------
# Step 4: register (replacing any earlier version of the same task)
# ---------------------------------------------------------------------------
try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force -ErrorAction Stop | Out-Null
} catch {
    Fail "Register-ScheduledTask failed for '$TaskName': $($_.Exception.GetType().Name): $($_.Exception.Message)"
}

# ---------------------------------------------------------------------------
# Step 5: self-verification - read the task BACK and check the two properties
# that carry the meaning. Registering successfully is not evidence that the
# logon dependency is gone; only LogonType is. A check that cannot fail when
# the setting is wrong is not a check.
# ---------------------------------------------------------------------------
$check = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $check) {
    Fail "Register-ScheduledTask reported success but '$TaskName' cannot be read back."
}
$logonType = $check.Principal.LogonType
if ("$logonType" -ne "S4U") {
    Fail "task '$TaskName' registered with LogonType '$logonType', not S4U - it would still depend on an interactive logon. Re-run this script elevated."
}
if (-not $check.Settings.StartWhenAvailable) {
    Fail "task '$TaskName' registered without StartWhenAvailable - a run missed while the machine was off would be dropped silently."
}

$registeredArgs = "$($check.Actions.Arguments)"
if ($registeredArgs -ne $argList) {
    Fail "task '$TaskName' exists but its action is NOT what this run built - an older registration is still in place (did registration silently fail?).`n  registered: $registeredArgs`n  expected:   $argList"
}

Write-Host "[OK] task '$TaskName' registered: daily $At, LogonType S4U, StartWhenAvailable"
Write-Host "[OK] action (read back from the task): powershell.exe $registeredArgs"

# ---------------------------------------------------------------------------
# Step 6: register the CHECK task. This is the half that makes a missed backup
# observable - see the header. It reads the status ledger the backup writes and
# raises an alert file when the last success is too old (or plaintext).
# ---------------------------------------------------------------------------
$checkTaskName = "$TaskName-Check"
$checkArgList = "-NoProfile -ExecutionPolicy Bypass -File `"$checkScriptPath`" -BackupDir `"$BackupDir`" -MaxAgeHours $CheckMaxAgeHours -PythonExe `"$PythonExe`""
if ($RequireEncryption) {
    $checkArgList = "$checkArgList -RequireEncrypted"
}
$checkAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $checkArgList
$checkTrigger = New-ScheduledTaskTrigger -Daily -At $CheckAt
$checkSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

try {
    Register-ScheduledTask -TaskName $checkTaskName -Action $checkAction -Trigger $checkTrigger -Principal $principal -Settings $checkSettings -Force -ErrorAction Stop | Out-Null
} catch {
    Fail "Register-ScheduledTask failed for '$checkTaskName': $($_.Exception.GetType().Name): $($_.Exception.Message)"
}

# ---------------------------------------------------------------------------
# Step 7: self-verification for the check task, same standard as step 5.
# A checker registered with the wrong logon type stops firing exactly when the
# machine is unattended - which is when a missed backup is most likely.
# ---------------------------------------------------------------------------
$checkBack = Get-ScheduledTask -TaskName $checkTaskName -ErrorAction SilentlyContinue
if (-not $checkBack) {
    Fail "Register-ScheduledTask reported success but '$checkTaskName' cannot be read back. The backup task exists but NOTHING READS ITS LEDGER - a missed backup would be silent."
}
$checkLogon = $checkBack.Principal.LogonType
if ("$checkLogon" -ne "S4U") {
    Fail "task '$checkTaskName' registered with LogonType '$checkLogon', not S4U - the freshness check would stop firing while the machine is unattended."
}
if (-not $checkBack.Settings.StartWhenAvailable) {
    Fail "task '$checkTaskName' registered without StartWhenAvailable."
}

$registeredCheckArgs = "$($checkBack.Actions.Arguments)"
if ($registeredCheckArgs -ne $checkArgList) {
    Fail "task '$checkTaskName' exists but its action is NOT what this run built - an older registration is still in place.`n  registered: $registeredCheckArgs`n  expected:   $checkArgList"
}

Write-Host "[OK] task '$checkTaskName' registered: daily $CheckAt, threshold $CheckMaxAgeHours h, LogonType S4U"
Write-Host "[OK] alert on failure: $BackupDir\backup_alert.txt (deleted automatically once a fresh backup is recorded)"
Write-Host "[NEXT] prove both halves now - runbook section 2-1:"
Write-Host "       Start-ScheduledTask -TaskName `"$TaskName`"; Start-ScheduledTask -TaskName `"$checkTaskName`""
exit 0
