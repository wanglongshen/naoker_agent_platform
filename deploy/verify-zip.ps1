# 部署包结构校验: powershell -ExecutionPolicy Bypass -File deploy\verify-zip.ps1 -Path <zip>
# 退出码 0=通过, 1=失败（原因打印到 stderr）
param([Parameter(Mandatory=$true)][string]$Path)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression.FileSystem

if (-not (Test-Path -LiteralPath $Path)) { Write-Error "文件不存在: $Path"; exit 1 }

$zip = [System.IO.Compression.ZipFile]::OpenRead($Path)
$names = @($zip.Entries | ForEach-Object { $_.FullName })
$zip.Dispose()

if ($names.Count -eq 0) { Write-Error "ZIP 没有任何条目"; exit 1 }

$bad = @($names | Where-Object { $_ -match '\\' })
if ($bad.Count -gt 0) {
  Write-Error "ZIP 含 $($bad.Count) 个反斜杠条目（Windows 打包错误，Linux 解压会乱）: $($bad[0])"
  exit 1
}

$required = @('code/deploy/deploy.sh', 'code/backend/requirements.txt', 'code/frontend/package.json', 'code/deepseek-harness/apps/cli/lib/bin.js', 'code/dsh-platform/packages/server-connector/lib/index.js', 'data/rbac.dump', 'secrets/prod.env')
$missing = @($required | Where-Object { $names -notcontains $_ })
if ($missing.Count -gt 0) { Write-Error "缺少关键条目: $($missing -join ', ')"; exit 1 }

Write-Host "OK 条目数=$($names.Count) 反斜杠=0 关键条目齐全"
exit 0
