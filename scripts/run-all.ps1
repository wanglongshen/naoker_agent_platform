# One-click start for every runtime component of the platform (background, idempotent).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\run-all.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\run-all.ps1 -SkipFrontend -SkipWebRenderer
#
# Components: backend API, agent worker, task-chain worker, DSH session-sync worker,
#             RAG ingest worker, web renderer (platform login), frontend dev server.
# Logs:    .runtime\logs\<component>.log / .err.log
# PIDs:    .runtime\pids\<component>.pid   (used by scripts\stop-all.ps1)
# Stop:    powershell -ExecutionPolicy Bypass -File scripts\stop-all.ps1
param(
    [switch]$SkipFrontend,
    [switch]$SkipWebRenderer
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$runtime = Join-Path $root ".runtime"
$pidDir = Join-Path $runtime "pids"
$logDir = Join-Path $runtime "logs"
New-Item -ItemType Directory -Force -Path $pidDir, $logDir | Out-Null

# Local conda python (change if running on another machine)
$py = "X:\python\anaconda\envs\01-rbac\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

function Get-PidFile([string]$name) { return (Join-Path $pidDir "$name.pid") }

function Test-PidAlive([string]$name) {
    $file = Get-PidFile $name
    if (-not (Test-Path $file)) { return $false }
    $raw = (Get-Content $file -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $raw) { return $false }
    $procId = 0
    if (-not [int]::TryParse($raw.Trim(), [ref]$procId)) { return $false }
    return [bool](Get-Process -Id $procId -ErrorAction SilentlyContinue)
}

function Test-PortOpen([int]$port) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $port)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

function Test-ProcessByCommandLine([string]$pattern) {
    # python processes only: avoids matching this PowerShell script's own command line
    $found = Get-CimInstance Win32_Process |
        Where-Object { $_.Name -like "python*" -and $_.CommandLine -like ("*" + $pattern + "*") }
    return [bool]$found
}

function Wait-Http([string]$url, [int]$timeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) { return $true }
        } catch { }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Start-Component([string]$name, [string]$file, [string[]]$arguments, [string]$cwd) {
    $stdout = Join-Path $logDir "$name.log"
    $stderr = Join-Path $logDir "$name.err.log"
    $proc = Start-Process -FilePath $file -ArgumentList $arguments -WorkingDirectory $cwd `
        -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    Set-Content -Path (Get-PidFile $name) -Value $proc.Id -Encoding ascii
    Write-Host ("  [started] {0} (pid {1})" -f $name, $proc.Id) -ForegroundColor Green
    return $proc
}

Write-Host "=== BrainShell platform: starting all components ===" -ForegroundColor Cyan

# 1) Database migration (safe to run repeatedly)
Write-Host "[migrate] alembic upgrade head ..." -ForegroundColor Cyan
Push-Location $backend
& $py -m alembic upgrade head
Pop-Location

$summary = @()

# 2) Backend API
if (Test-PidAlive "backend") {
    Write-Host "  [skip] backend already started by this script" -ForegroundColor DarkGray
    $summary += "backend|already running"
} elseif (Test-PortOpen 8010) {
    Write-Host "  [skip] port 8010 is already serving (started outside this script)" -ForegroundColor DarkGray
    $summary += "backend|external"
} else {
    Start-Component "backend" $py @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010") $backend | Out-Null
    if (Wait-Http "http://127.0.0.1:8010/health" 60) {
        $summary += "backend|http://127.0.0.1:8010"
    } else {
        $summary += "backend|FAILED (see .runtime\logs\backend.err.log)"
    }
}

# 3) Background workers
$workers = @(
    @{ name = "agent-worker"; module = "app.workers.agent_worker" },
    @{ name = "task-chain-worker"; module = "app.workers.task_chain_worker" },
    @{ name = "dsh-sync-worker"; module = "app.workers.dsh_sync_worker" },
    @{ name = "rag-ingest-worker"; module = "app.workers.rag_ingest_worker" }
)
foreach ($worker in $workers) {
    $name = $worker.name
    if (Test-PidAlive $name) {
        Write-Host "  [skip] $name already started by this script" -ForegroundColor DarkGray
        $summary += "$name|already running"
        continue
    }
    if (Test-ProcessByCommandLine ("$py*" + $worker.module)) {
        Write-Host "  [skip] $name is already running (started outside this script)" -ForegroundColor DarkGray
        $summary += "$name|external"
        continue
    }
    Start-Component $name $py @("-m", $worker.module) $backend | Out-Null
    $summary += "$name|running"
}

# 4) Web renderer (platform login / search rendering)
if (-not $SkipWebRenderer) {
    if (Test-PidAlive "web-renderer") {
        Write-Host "  [skip] web-renderer already started by this script" -ForegroundColor DarkGray
        $summary += "web-renderer|already running"
    } elseif (Test-PortOpen 9001) {
        Write-Host "  [skip] port 9001 is already serving (started outside this script)" -ForegroundColor DarkGray
        $summary += "web-renderer|external"
    } else {
        Start-Component "web-renderer" $py @("-m", "app.workers.web_renderer") $backend | Out-Null
        if (Wait-Http "http://127.0.0.1:9001/health" 45) {
            $summary += "web-renderer|http://127.0.0.1:9001"
        } else {
            $summary += "web-renderer|starting (slow) - check .runtime\logs\web-renderer.err.log"
        }
    }
}

# 5) Frontend dev server
if (-not $SkipFrontend) {
    if (Test-PidAlive "frontend") {
        Write-Host "  [skip] frontend already started by this script" -ForegroundColor DarkGray
        $summary += "frontend|already running"
    } elseif (Test-PortOpen 3001) {
        Write-Host "  [skip] port 3001 is already serving (started outside this script)" -ForegroundColor DarkGray
        $summary += "frontend|external"
    } else {
        Start-Component "frontend" "cmd.exe" @("/c", "npm run dev -- -p 3001") $frontend | Out-Null
        if (Wait-Http "http://localhost:3001" 180) {
            $summary += "frontend|http://localhost:3001"
        } else {
            $summary += "frontend|starting (first compile can take 1-2 min)"
        }
    }
}

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
foreach ($row in $summary) {
    $parts = $row.Split("|")
    Write-Host ("  {0,-18} {1}" -f $parts[0], $parts[1])
}
Write-Host ""
Write-Host "Login:    http://localhost:3001   (admin / ChangeMe-Strong1)" -ForegroundColor Green
Write-Host "Logs:     $logDir"
Write-Host "Status:   powershell -ExecutionPolicy Bypass -File scripts\status-all.ps1"
Write-Host "Stop:     powershell -ExecutionPolicy Bypass -File scripts\stop-all.ps1" -ForegroundColor Yellow
Write-Host "Note:     the DSH workspace instance is started on demand by the backend (first visit to /agent)."
