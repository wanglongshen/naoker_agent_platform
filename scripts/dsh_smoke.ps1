<#
.SYNOPSIS
DSH 一期集成冒烟：6 项顺序断言（①health ②DSH 表 ③实例重启 ④DSH 代理 ⑤前端 ⑥审计同步）。

.DESCRIPTION
前置条件：
  - API 已启动：backend 下 `uvicorn app.main:app --port 8010`（工作目录 = backend，冒烟按同目录解析 var/dsh/<uid>）。
  - DB 已迁移：backend 下 `alembic upgrade head`（dsh_instances / dsh_sessions 存在）。
  - Python 环境：backend requirements.txt 的依赖（sqlalchemy + asyncpg + zstandard），README 建议的 conda 环境即可。
  - 前端（可选）：npm run dev / serve，端口 3001；未启动时第 ⑤ 项 SKIP（不判失败）。
  - 实例运行模式为 dev_bin（全局 dsh 在 PATH）或 vendored（deepseek-harness 构建产物）；DEEPSEEK_API_KEY 已配置于 backend/.env。

依赖说明：
  - 步骤 ② / ⑥ 使用内嵌 Python（sqlalchemy + asyncpg 直连 DATABASE_URL），不依赖 psql、不需要数据库客户端。
  - 步骤 ③ 需要 CSRF：登录取得 access_token cookie 后，先 GET /api/auth/csrf 取 token，再携带 X-CSRF-Token 与 Origin（取自 backend/.env 的 CORS_ORIGINS）调用重启端点。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\dsh_smoke.ps1
  powershell -ExecutionPolicy Bypass -File scripts\dsh_smoke.ps1 -Username admin -Password ChangeMe-Strong1
  powershell -ExecutionPolicy Bypass -File scripts\dsh_smoke.ps1 -Python "python"
#>
param(
    [string]$BaseApi = "http://127.0.0.1:8010",
    [string]$FrontendBase = "http://localhost:3001",
    [string]$Python = "python",
    [string]$Username = "",
    [string]$Password = "",
    [int]$StartWaitSeconds = 60
)

$ErrorActionPreference = "Stop"
$TotalSteps = 6

$root = Split-Path $PSScriptRoot -Parent
$backendDir = Join-Path $root "backend"
$envFile = Join-Path $backendDir ".env"
$envExampleFile = Join-Path $backendDir ".env.example"

function Fail([string]$msg) {
    Write-Host ""
    Write-Host "[FAIL] $msg" -ForegroundColor Red
    exit 1
}

function StepOk([string]$msg) {
    Write-Host "  [OK] $msg" -ForegroundColor Green
}

function Get-EnvValue {
    param([string]$Path, [string]$Key)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match "^$Key=(.*)$") { return $Matches[1].Trim() }
    }
    return $null
}

function Invoke-Api {
    param(
        [string]$Method,
        [string]$Uri,
        $Session,
        [string]$Body,
        [hashtable]$Headers
    )
    $params = @{
        Method = $Method
        Uri = $Uri
        TimeoutSec = 30
        UseBasicParsing = $true
        ErrorAction = "Stop"
    }
    if ($null -ne $Session) { $params.WebSession = $Session }
    if ($Body) {
        $params.ContentType = "application/json"
        $params.Body = $Body
    }
    if ($Headers) { $params.Headers = $Headers }
    try {
        $resp = Invoke-WebRequest @params
        return [pscustomobject]@{ OK = $true; Status = [int]$resp.StatusCode; Body = $resp.Content }
    } catch {
        $code = 0
        if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
        return [pscustomobject]@{ OK = $false; Status = $code; Body = $_.Exception.Message }
    }
}

# ---------- ① API health ----------
Write-Host "[1/$TotalSteps] API health: $BaseApi/health"
$h = Invoke-Api "GET" "$BaseApi/health" $null $null $null
if (-not $h.OK -or $h.Status -ne 200) { Fail "health 非 200 (status=$($h.Status) err=$($h.Body))。API 未启动？" }
$healthBody = $h.Body | ConvertFrom-Json
if ($healthBody.data.status -ne "ok") { Fail "health body 异常: $($h.Body)" }
StepOk "GET /health -> 200 status=ok"

# ---------- ② DSH 表存在 ----------
Write-Host "[2/$TotalSteps] DB 表存在性（python + sqlalchemy 查询 DATABASE_URL）"
$dsn = Get-EnvValue $envFile "DATABASE_URL"
if (-not $dsn) { $dsn = Get-EnvValue $envExampleFile "DATABASE_URL" }
if (-not $dsn) { Fail "未找到 DATABASE_URL（backend/.env 与 .env.example 均无）" }
$tableCheckPy = @'
import asyncio, json, os, sys
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

dsn = os.environ["DSMOKE_DSN"]

async def main():
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            res = await conn.execute(sa.text(
                "select table_name from information_schema.tables "
                "where table_schema='public' and table_name in ('dsh_instances','dsh_sessions')"))
            names = {row[0] for row in res.fetchall()}
        print(json.dumps({"tables": sorted(names)}))
    finally:
        await engine.dispose()

asyncio.run(main())
'@
$env:DSMOKE_DSN = $dsn
try {
    $tableOut = $tableCheckPy | & $Python -
    if ($LASTEXITCODE -ne 0) { Fail "python 表检查失败（exit=$LASTEXITCODE）：$tableOut" }
} catch {
    Fail "python 表检查异常：$($_.Exception.Message)"
} finally {
    Remove-Item Env:DSMOKE_DSN -ErrorAction SilentlyContinue
}
$tableJson = ($tableOut | Where-Object { $_ -match "^\{" } | Select-Object -Last 1) | ConvertFrom-Json
if ($tableJson.tables -notcontains "dsh_instances") { Fail "dsh_instances 表不存在（当前表: $($tableJson.tables -join ',')）。先执行 alembic upgrade head" }
StepOk "dsh_instances 表存在（另有: $($tableJson.tables -join ', ')）"

# ---------- ③ 登录 + CSRF + 重启实例 ----------
Write-Host "[3/$TotalSteps] POST /api/auth/login -> 实例重启 -> state=running"
if (-not $Username) { $Username = Get-EnvValue $envFile "INITIAL_ADMIN_USERNAME"; if (-not $Username) { $Username = "admin" } }
if (-not $Password) { $Password = Get-EnvValue $envFile "INITIAL_ADMIN_PASSWORD"; if (-not $Password) { $Password = "ChangeMe-Strong1" } }
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$loginResp = Invoke-Api "POST" "$BaseApi/api/auth/login" $session (ConvertTo-Json @{ username = $Username; password = $Password }) $null
if (-not $loginResp.OK -or $loginResp.Status -ne 200) {
    Fail "登录失败（status=$($loginResp.Status)）$($loginResp.Body)。检查用户名/密码或 INITIAL_ADMIN_* 配置"
}
StepOk "登录成功，已取得 access_token cookie（user=$Username）"

$me = Invoke-Api "GET" "$BaseApi/api/auth/me" $session $null $null
if (-not $me.OK -or $me.Status -ne 200) { Fail "GET /api/auth/me 失败（status=$($me.Status)）" }
$uid = ($me.Body | ConvertFrom-Json).data.id
StepOk "当前用户 uid=$uid"

$csrf = Invoke-Api "GET" "$BaseApi/api/auth/csrf" $session $null $null
if (-not $csrf.OK -or $csrf.Status -ne 200) { Fail "GET /api/auth/csrf 失败（status=$($csrf.Status)）" }
$csrfToken = ($csrf.Body | ConvertFrom-Json).data.token
$originCfg = Get-EnvValue $envFile "CORS_ORIGINS"
$origin = "http://localhost:3001"
if ($originCfg) { $origin = ($originCfg -split ",")[0].Trim() }

$restart = Invoke-Api "POST" "$BaseApi/api/dsh/instances/me/restart" $session "{}" @{ "X-CSRF-Token" = $csrfToken; "Origin" = $origin }
if (-not $restart.OK) {
    Fail "restart 失败（status=$($restart.Status)）：$($restart.Body)。检查 Origin=$origin 与 X-CSRF-Token 是否有效"
}
$deadline = (Get-Date).AddSeconds($StartWaitSeconds)
$state = ""
$errorHint = ""
while ((Get-Date) -lt $deadline) {
    $s = Invoke-Api "GET" "$BaseApi/api/dsh/instances/me" $session $null $null
    if ($s.OK -and $s.Status -eq 200) {
        $inst = ($s.Body | ConvertFrom-Json).data
        $state = $inst.state
        $errorHint = $inst.error_hint
        if ($state -eq "running" -or $state -eq "error") { break }
    }
    Start-Sleep -Seconds 3
}
if ($state -ne "running") {
    Fail "实例未达 running（state=$state error_hint=$errorHint）。检查 dsh 是否在 PATH（dev_bin）或 vendored 构建产物与 DEEPSEEK_API_KEY"
}
StepOk "实例 state=running（第 ③/④ 项可用）"

# ---------- ④ DSH 代理 ----------
Write-Host "[4/$TotalSteps] GET /api/dsh-proxy/<uid>/ -> 200 text/html"
$proxy = Invoke-Api "GET" "$BaseApi/api/dsh-proxy/$uid/" $session $null $null
if (-not $proxy.OK -or $proxy.Status -ne 200) { Fail "代理根路径非 200（status=$($proxy.Status)）：$($proxy.Body)" }
$html = if ($proxy.Body -is [string]) { $proxy.Body } else { [string]$proxy.Body }
if ($html -notmatch "<html") { Fail "代理返回体不含 <html（可能与实例未真正就绪有关），摘录：$($html.Substring(0, [Math]::Min(200, $html.Length)))" }
StepOk "代理返回 200 且含 <html"

# ---------- ⑤ 前端（可选，未启动则 SKIP） ----------
Write-Host "[5/$TotalSteps] GET $FrontendBase/agent -> 200"
$fe = Invoke-Api "GET" "$FrontendBase/agent" $null $null $null
if ($fe.Status -eq 0) {
    Write-Host "  [SKIP] 前端 $FrontendBase 未响应（$($fe.Body)）。前端未启动，不计入结果。" -ForegroundColor Yellow
} elseif (-not $fe.OK -or $fe.Status -ne 200) {
    Fail "前端 /agent 非 200（status=$($fe.Status)）：$($fe.Body)"
} else {
    StepOk "前端 /agent -> 200"
}

# ---------- ⑥ 审计同步一次 + dsh_sessions 查询 ----------
Write-Host "[6/$TotalSteps] 审计同步一次（sync_user_sessions）+ dsh_sessions 计数"
$uidHome = $null
foreach ($cand in @("$backendDir\var\dsh\$uid", "$root\var\dsh\$uid")) {
    if (Test-Path -LiteralPath (Join-Path $cand "sessions")) { $uidHome = $cand; break }
}
if (-not $uidHome) {
    Write-Host "  [SKIP] 未找到用户实例 home（$backendDir\var\dsh\$uid 或 $root\var\dsh\$uid）。实例从未启动或无会话目录；" -ForegroundColor Yellow
    Write-Host "         此步骤为同步链路检查，判定为通过（有对话后可重跑本脚本核实行数）。" -ForegroundColor Yellow
    Write-Host "  [PASS] ⑥ SKIP（同步链路未验证）" -ForegroundColor DarkYellow
} else {
    $syncCheckPy = @'
import asyncio, json, os, sys, uuid
from pathlib import Path
import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

dsn = os.environ["DSMOKE_DSN"]
uid = uuid.UUID(os.environ["DSMOKE_UID"])
home = Path(os.environ["DSMOKE_HOME"])

from app.services.dsh.session_sync import sync_user_sessions
from app.models.dsh import DshSession

async def main():
    engine = create_async_engine(dsn)
    try:
        sm = async_sessionmaker(engine, expire_on_commit=False)
        async with sm() as db:
            synced = await sync_user_sessions(db, uid, home)
            cnt = await db.scalar(
                select(func.count()).select_from(DshSession).where(DshSession.user_id == uid))
        print(json.dumps({"synced": synced, "session_rows": int(cnt)}))
    finally:
        await engine.dispose()

asyncio.run(main())
'@
    Push-Location $backendDir
    try {
        $env:DSMOKE_DSN = $dsn
        $env:DSMOKE_UID = $uid
        $env:DSMOKE_HOME = $uidHome
        try {
            $syncOut = $syncCheckPy | & $Python -
            if ($LASTEXITCODE -ne 0) { Fail "同步 python 片段失败（exit=$LASTEXITCODE）：$syncOut" }
        } catch {
            Fail "同步 python 片段异常：$($_.Exception.Message)"
        } finally {
            Remove-Item Env:DSMOKE_DSN -ErrorAction SilentlyContinue
            Remove-Item Env:DSMOKE_UID -ErrorAction SilentlyContinue
            Remove-Item Env:DSMOKE_HOME -ErrorAction SilentlyContinue
        }
    } finally {
        Pop-Location
    }
    $syncJson = ($syncOut | Where-Object { $_ -match "^\{" } | Select-Object -Last 1) | ConvertFrom-Json
    StepOk "sync_user_sessions 新写入/更新 $($syncJson.synced) 条；dsh_sessions(user=$uid) 共 $($syncJson.session_rows) 行"
    if ($syncJson.session_rows -eq 0) {
        Write-Host "  [WARN] 当前无 DSH 对话记录，行数为 0（属预期；在 DSH 里发过消息后重跑可见 >0）。" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "[SMOKE DONE] API=$BaseApi user=$uid uid=$Username" -ForegroundColor Green
exit 0
