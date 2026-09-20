# 一键打包部署包: C:\agent-deploy\agent-deploy.zip
$ErrorActionPreference = "Stop"
$Root = "C:\01_agent_loop_pro"
$OutDir = "C:\agent-deploy"
$Zip = Join-Path $OutDir "agent-deploy.zip"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Remove-Item -LiteralPath $Zip -Force -ErrorAction SilentlyContinue
$Stage = Join-Path $OutDir "_stage"
Remove-Item -LiteralPath $Stage -Force -Recurse -ErrorAction SilentlyContinue

Write-Host "== 1/4 导出数据库 dump =="
$PgDump = Get-Command pg_dump -ErrorAction SilentlyContinue
if (-not $PgDump) { $PgDump = Get-Item "X:\database\postgresql\bin\pg_dump.exe" -ErrorAction SilentlyContinue }
if (-not $PgDump) { throw "未找到 pg_dump，请安装 PostgreSQL 或把 pg_dump.exe 加入 PATH" }
# 从 backend/.env 解析 DATABASE_URL
$envContent = Get-Content (Join-Path $Root "backend\.env") -Encoding UTF8
$dbLine = $envContent | Where-Object { $_ -match '^DATABASE_URL=(.+)$' } | Select-Object -First 1
if (-not $dbLine) { throw "backend/.env 缺少 DATABASE_URL" }
$dbUrl = $Matches[1]
$m = [regex]::Match($dbUrl, '^postgresql\+asyncpg://([^:]+):([^@]+)@([^:]+):(\d+)/(\w+)')
if (-not $m.Success) { throw "DATABASE_URL 解析失败: $dbUrl" }
$user, $pwd, $host_, $port, $db = $m.Groups[1..5].Value
$env:PGPASSWORD = $pwd
New-Item -ItemType Directory -Force -Path (Join-Path $OutDir "data") | Out-Null
& $PgDump.Source -h $host_ -p $port -U $user -d $db -Fc -f (Join-Path $OutDir "data\rbac.dump")
if (-not (Test-Path (Join-Path $OutDir "data\rbac.dump"))) { throw "pg_dump 失败" }
Write-Host ("   dump: {0:N0} KB" -f ((Get-Item (Join-Path $OutDir "data\rbac.dump")).Length / 1KB))

Write-Host "== 2/4 汇总 prod.env =="
$secrets = @()
foreach ($f in @("backend\.env", ".env")) {
  $p = Join-Path $Root $f
  if (Test-Path $p) {
    Get-Content $p -Encoding UTF8 | ForEach-Object {
      if ($_ -match '^(JWT_SECRET|INITIAL_ADMIN_PASSWORD|DEEPSEEK_API_KEY|TAVILY_API_KEY|FEISHU_APP_ID|FEISHU_APP_SECRET|FEISHU_TOKEN_ENCRYPTION_KEY|INITIAL_ADMIN_USERNAME|DEEPSEEK_MODEL)=') { $secrets += $_ }
    }
  }
}
$prodEnv = ($secrets | Sort-Object -Unique) -join "`r`n"
New-Item -ItemType Directory -Force -Path (Join-Path $OutDir "secrets") | Out-Null
[System.IO.File]::WriteAllText((Join-Path $OutDir "secrets\prod.env"), $prodEnv + "`r`n", [System.Text.UTF8Encoding]::new($false))
$missing = @('JWT_SECRET','INITIAL_ADMIN_PASSWORD','DEEPSEEK_API_KEY','TAVILY_API_KEY','FEISHU_APP_ID','FEISHU_APP_SECRET','FEISHU_TOKEN_ENCRYPTION_KEY') | Where-Object { -not ($prodEnv -match "(?m)^$_=") }
if ($missing) { Write-Warning "prod.env 缺少: $($missing -join ', ') —— deploy.sh 会拒绝部署，请先补全 .env" }

Write-Host "== 3/4 收集代码 =="
# deepseek-harness/dsh-platform：镜像内 pnpm 构建 vendored DSH + connector 的源码
# （node_modules/.git/测试产物由 /XD 排除；构建在 Dockerfile.backend 的 dsh-build 阶段完成）
$codeSrcs = @("backend", "frontend", "deepseek-harness", "dsh-platform")
foreach ($c in $codeSrcs) {
  $dst = Join-Path $Stage "code\$c"
  $src = Join-Path $Root $c
  robocopy $src $dst /E /XD node_modules .next .venv __pycache__ .pytest_cache coverage .turbo var .git /XF *.zip /NFL /NDL /NJH /NJS | Out-Null
}
robocopy (Join-Path $Root "deploy") (Join-Path $Stage "code\deploy") /E /NFL /NDL /NJH /NJS | Out-Null

# 脚本文件强制 LF（Windows 工作区可能是 CRLF，服务器 bash 对 CRLF 报 set: pipefail 错误）
Get-ChildItem -LiteralPath (Join-Path $Stage "code") -Recurse -Filter *.sh | ForEach-Object {
  $text = [System.IO.File]::ReadAllText($_.FullName)
  if ($text -match "`r`n") {
    [System.IO.File]::WriteAllText($_.FullName, ($text -replace "`r`n", "`n"), [System.Text.UTF8Encoding]::new($false))
  }
}

Write-Host "== 4/4 收集文件库 + 打包 =="
$varDst = Join-Path $Stage "data\var"
robocopy (Join-Path $Root "backend\var") $varDst /E /NFL /NDL /NJH /NJS | Out-Null
Copy-Item (Join-Path $OutDir "data\rbac.dump") (Join-Path $Stage "data\rbac.dump")
New-Item -ItemType Directory -Force -Path (Join-Path $Stage "secrets") | Out-Null
Copy-Item (Join-Path $OutDir "secrets\prod.env") (Join-Path $Stage "secrets\prod.env")

# 打包：ZipArchive 显式正斜杠路径（Linux python3 -m zipfile -e 依赖 / 分隔符）
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zipArchive = [System.IO.Compression.ZipFile]::Open($Zip, [System.IO.Compression.ZipArchiveMode]::Create)
try {
  Get-ChildItem -LiteralPath $Stage -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($Stage.TrimEnd('\').Length).TrimStart('\').Replace('\', '/')
    $entry = $zipArchive.CreateEntry($rel, [System.IO.Compression.CompressionLevel]::Optimal)
    $es = $entry.Open()
    try {
      $fs = [System.IO.File]::OpenRead($_.FullName)
      try { $fs.CopyTo($es) } finally { $fs.Dispose() }
    } finally { $es.Dispose() }
  }
} finally {
  $zipArchive.Dispose()
}

# 硬校验：不合格即删除，禁止交付
& powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "verify-zip.ps1") -Path $Zip
if ($LASTEXITCODE -ne 0) {
  Remove-Item -LiteralPath $Zip -Force -ErrorAction SilentlyContinue
  throw "部署包校验失败，已删除 $Zip"
}
Remove-Item -LiteralPath $Stage -Force -Recurse
Write-Host ""
Write-Host "打包完成: $Zip"
Write-Host ("大小: {0:N1} MB" -f ((Get-Item $Zip).Length / 1MB))
Write-Host "上传到服务器 /opt/agent-deploy/ 后执行: bash deploy.sh"
