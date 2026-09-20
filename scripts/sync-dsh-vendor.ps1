# scripts/sync-dsh-vendor.ps1
param([string]$Tag = "0.1.1-rc.2")
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$vendor = Join-Path $root "deepseek-harness"
$tmp = Join-Path $env:TEMP ("dsh-vendor-" + [guid]::NewGuid().ToString("N"))
git clone --depth 1 --branch $Tag https://github.com/deepseek-ai/deepseek-harness.git $tmp
Push-Location $tmp
$sha = (git rev-parse --short HEAD).Trim()
Pop-Location
# 仅保留构建所需：排除重目录（website 必须保留：tsconfig.host.json 含 website/**/*.ts，已实测删除后 tsc 报错）
Remove-Item (Join-Path $tmp ".git") -Recurse -Force
Remove-Item (Join-Path $tmp "snapshots") -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $tmp ".github") -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $vendor) { Remove-Item $vendor -Recurse -Force }
Move-Item $tmp $vendor
$record = [ordered]@{
  repo = "deepseek-ai/deepseek-harness"; tag = $Tag; sha = $sha;
  vendored_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
}
$record | ConvertTo-Json | Set-Content (Join-Path $vendor ".dsh-vendor.json") -Encoding utf8
Write-Host "vendored tag=$Tag sha=$sha -> $vendor"
