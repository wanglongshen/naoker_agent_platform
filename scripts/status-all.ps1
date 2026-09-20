# Show the runtime status of every platform component.
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\status-all.ps1
$root = Split-Path $PSScriptRoot -Parent
$pidDir = Join-Path $root ".runtime\pids"

function Get-PidInfo([string]$name) {
    $file = Join-Path $pidDir "$name.pid"
    if (-not (Test-Path $file)) { return @{ pid = $null; alive = $false } }
    $raw = (Get-Content $file -ErrorAction SilentlyContinue | Select-Object -First 1)
    $procId = 0
    if (-not ($raw -and [int]::TryParse($raw.Trim(), [ref]$procId))) { return @{ pid = $null; alive = $false } }
    $alive = [bool](Get-Process -Id $procId -ErrorAction SilentlyContinue)
    return @{ pid = $procId; alive = $alive }
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
    $found = Get-CimInstance Win32_Process |
        Where-Object { $_.Name -like "python*" -and $_.CommandLine -like ("*" + $pattern + "*") }
    return [bool]$found
}

function Test-Http([string]$url) {
    try {
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
        return $resp.StatusCode
    } catch {
        return "-"
    }
}

Write-Host "=== BrainShell platform status ===" -ForegroundColor Cyan
Write-Host ("{0,-18} {1,-10} {2,-8} {3}" -f "component", "pid", "port", "health")

$components = @(
    @{ name = "backend"; port = 8010; health = "http://127.0.0.1:8010/health"; match = "uvicorn app.main:app" },
    @{ name = "frontend"; port = 3001; health = "http://localhost:3001"; match = $null },
    @{ name = "web-renderer"; port = 9001; health = "http://127.0.0.1:9001/health"; match = "app.workers.web_renderer" },
    @{ name = "agent-worker"; port = $null; health = $null; match = "app.workers.agent_worker" },
    @{ name = "task-chain-worker"; port = $null; health = $null; match = "app.workers.task_chain_worker" },
    @{ name = "dsh-sync-worker"; port = $null; health = $null; match = "app.workers.dsh_sync_worker" },
    @{ name = "rag-ingest-worker"; port = $null; health = $null; match = "app.workers.rag_ingest_worker" }
)

foreach ($component in $components) {
    $info = Get-PidInfo $component.name
    $external = $false
    if (-not $info.alive -and $component.match) {
        $external = Test-ProcessByCommandLine $component.match
    }
    $pidText = "-"
    if ($info.pid -and $info.alive) { $pidText = [string]$info.pid }
    $portText = "-"
    $portOpen = $false
    if ($component.port) {
        $portOpen = Test-PortOpen $component.port
        $portText = [string]$component.port
    }
    $health = "-"
    if ($component.health -and $portOpen) {
        $health = [string](Test-Http $component.health)
    } elseif ($component.health -and -not $portOpen) {
        $health = "closed"
    } elseif ($info.alive) {
        $health = "alive"
    } elseif ($external) {
        $health = "alive (external)"
    } else {
        $health = "stopped"
    }
    $label = $component.name
    if ($info.alive) { $label = $label + " *" }
    Write-Host ("{0,-18} {1,-10} {2,-8} {3}" -f $label, $pidText, $portText, $health)
}

$dsh = Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*dsh*bin.js*" -and $_.CommandLine -like "*--profile web*" }
if ($dsh) {
    $ports = @()
    foreach ($proc in $dsh) {
        $match = [regex]::Match($proc.CommandLine, "--port (\d+)")
        if ($match.Success) { $ports += $match.Groups[1].Value }
    }
    Write-Host ""
    Write-Host ("DSH workspace instance: running (pid {0}, port {1})" -f ($dsh.ProcessId -join ","), ($ports -join ",")) -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "DSH workspace instance: not running (starts on demand when /agent is opened)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "* = started by scripts\run-all.ps1 (pid file present)"
Write-Host "Start: powershell -ExecutionPolicy Bypass -File scripts\run-all.ps1"
Write-Host "Stop:  powershell -ExecutionPolicy Bypass -File scripts\stop-all.ps1"
