# Stop every component started by scripts\run-all.ps1 (process tree kill).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\stop-all.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\stop-all.ps1 -IncludeExternal
#
# -IncludeExternal also stops processes that were NOT started by run-all.ps1
# (matched by command line, e.g. a backend launched from PyCharm).
# Note: the backend process tree includes the DSH workspace instance; it is
# restarted automatically on the next visit to /agent.
param(
    [switch]$IncludeExternal
)

$root = Split-Path $PSScriptRoot -Parent
$pidDir = Join-Path $root ".runtime\pids"

$names = @("backend", "agent-worker", "task-chain-worker", "dsh-sync-worker", "rag-ingest-worker", "web-renderer", "frontend")

Write-Host "=== Stopping BrainShell platform components ===" -ForegroundColor Cyan
foreach ($name in $names) {
    $file = Join-Path $pidDir "$name.pid"
    if (-not (Test-Path $file)) {
        Write-Host ("  [skip] {0}: no pid file" -f $name) -ForegroundColor DarkGray
        continue
    }
    $raw = (Get-Content $file -ErrorAction SilentlyContinue | Select-Object -First 1)
    $procId = 0
    if ($raw -and [int]::TryParse($raw.Trim(), [ref]$procId)) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc) {
            & taskkill /PID $procId /T /F | Out-Null
            Write-Host ("  [stopped] {0} (pid {1})" -f $name, $procId) -ForegroundColor Green
        } else {
            Write-Host ("  [gone] {0} (pid {1} not running)" -f $name, $procId) -ForegroundColor DarkGray
        }
    }
    Remove-Item $file -Force -ErrorAction SilentlyContinue
}

if ($IncludeExternal) {
    $patterns = @(
        @{ name = "backend (uvicorn app.main:app)"; match = "uvicorn app.main:app" },
        @{ name = "agent-worker"; match = "app.workers.agent_worker" },
        @{ name = "task-chain-worker"; match = "app.workers.task_chain_worker" },
        @{ name = "dsh-sync-worker"; match = "app.workers.dsh_sync_worker" },
        @{ name = "rag-ingest-worker"; match = "app.workers.rag_ingest_worker" },
        @{ name = "web-renderer"; match = "app.workers.web_renderer" }
    )
    foreach ($pattern in $patterns) {
        Get-CimInstance Win32_Process |
            Where-Object { $_.CommandLine -like ("*" + $pattern.match + "*") -and $_.Name -like "python*" } |
            ForEach-Object {
                & taskkill /PID $_.ProcessId /T /F | Out-Null
                Write-Host ("  [stopped] {0} (pid {1})" -f $pattern.name, $_.ProcessId) -ForegroundColor Green
            }
    }
}

Write-Host ""
Write-Host "All requested components are stopped." -ForegroundColor Yellow
