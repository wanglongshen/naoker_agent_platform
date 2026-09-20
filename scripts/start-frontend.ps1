# Start frontend (Ctrl+C to stop)
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start-frontend.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

Set-Location (Join-Path $root "frontend")

Write-Host "Frontend: http://localhost:3001 (Ctrl+C to stop)" -ForegroundColor Green
npm run dev -- -p 3001
