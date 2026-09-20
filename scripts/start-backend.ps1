# Start backend: run DB migration, then launch FastAPI (Ctrl+C to stop)
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start-backend.ps1
param([int]$Port = 8010)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

# Local conda python (change if running on another machine)
$py = "X:\python\anaconda\envs\01-rbac\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Set-Location (Join-Path $root "backend")

Write-Host "[1/2] DB migration: alembic upgrade head ..." -ForegroundColor Cyan
& $py -m alembic upgrade head

Write-Host "[2/2] Backend API: http://127.0.0.1:$Port (Ctrl+C to stop)" -ForegroundColor Green
& $py -m uvicorn app.main:app --host 127.0.0.1 --port $Port --reload
