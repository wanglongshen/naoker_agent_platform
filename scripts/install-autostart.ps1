# Register / unregister a per-user logon task that starts the platform automatically.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1            # install
#   powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1 -Uninstall # remove
#   powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1 -SkipFrontend
#
# The task runs scripts\run-all.ps1 at logon of the current user (no admin required).
param(
    [switch]$Uninstall,
    [switch]$SkipFrontend,
    [switch]$SkipWebRenderer
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$taskName = "BrainShellPlatform"

if ($Uninstall) {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "[removed] scheduled task '$taskName'" -ForegroundColor Yellow
    } else {
        Write-Host "[skip] scheduled task '$taskName' does not exist" -ForegroundColor DarkGray
    }
    exit 0
}

$scriptPath = Join-Path $PSScriptRoot "run-all.ps1"
if (-not (Test-Path $scriptPath)) { throw "run-all.ps1 not found: $scriptPath" }

$extra = ""
if ($SkipFrontend) { $extra += " -SkipFrontend" }
if ($SkipWebRenderer) { $extra += " -SkipWebRenderer" }
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument ("-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"{0}`"{1}" -f $scriptPath, $extra) `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Start the BrainShell platform (backend, workers, frontend) at logon" | Out-Null

Write-Host "[installed] scheduled task '$taskName' will run at logon:" -ForegroundColor Green
Write-Host "            $scriptPath$extra"
Write-Host "Remove with: powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1 -Uninstall"
