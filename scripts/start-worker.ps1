# Start agent worker (separate process from the API; Ctrl+C to stop)
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start-worker.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

$py = "X:\python\anaconda\envs\01-rbac\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Set-Location (Join-Path $root "backend")

Write-Host "Agent worker starting (Ctrl+C to stop) ..." -ForegroundColor Green
& $py -m app.workers.agent_worker
