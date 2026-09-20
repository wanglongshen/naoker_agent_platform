# 跨平台部署包与安全重部署 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让本地打包的部署包在 Ubuntu 上解压出正确的 POSIX 目录结构，并以「临时验收 → 备份 → 受控替换」的流程安全升级远端，恢复固定端口 3100/8100。

**Architecture:** 打包侧改用 .NET ZipArchive 显式写正斜杠路径并加交付前硬校验（verify-zip.ps1 独立脚本）；远端新增 upgrade.sh（解压到 .incoming 验收结构 → 备份 code/data/.env/数据库 → 清理历史反斜杠错误条目 → 受控替换 → 调用 deploy.sh）；deploy.sh 端口逻辑从「冲突自动 +1」改为「固定 3100/8100/15432，非本系统占用即终止」。

**Tech Stack:** PowerShell 5.1（打包/校验）、Bash（远端脚本）、zipfile（服务器解压）、Docker Compose。

## Global Constraints

- 服务器硬约束：**8000 和 82 端口必须避开**（固定端口 3100/8100/15432 天然满足，脚本不做 +1 递增）。
- 不得停止、重建或改动 `lobster-*` 容器、宝塔 Nginx/MySQL、现有业务容器。
- 部署包必须满足：ZIP 条目全部使用 `/` 分隔（或单文件名无分隔符），任何 `\` 条目 = 打包失败，禁止交付。
- 关键条目必须存在：`code/deploy/deploy.sh`、`code/backend/requirements.txt`、`code/frontend/package.json`、`data/rbac.dump`、`secrets/prod.env`。
- `.env` 是服务器已生成密钥/数据库密码的唯一保留来源：替换后必须恢复原 `.env` 到新 `code/deploy/.env`。
- 所有脚本在本地以 `bash -n` 静态校验；Docker/服务器行为在远端实测（本机无 Docker、无 bash 环境）。
- 数据库恢复以部署包内 `data/rbac.dump` 为准；upgrade.sh 在替换前对远端 `rbac` 库做 pg_dump 备份（防远端新增数据被覆盖）。

---

### Task 1: pack.ps1 可移植打包 + verify-zip.ps1 硬校验

**Files:**
- Modify: `deploy/pack.ps1`（步骤 4 打包部分，第 54-66 行）
- Create: `deploy/verify-zip.ps1`
- Test: 实跑 `pack.ps1` + 直接调用 `verify-zip.ps1`（本任务验证，Task 4 做完整集成）

**Interfaces:**
- Produces: `deploy/verify-zip.ps1` — 用法 `powershell -ExecutionPolicy Bypass -File deploy/verify-zip.ps1 -Path <zip>`，退出码 0=通过 / 1=失败（stderr 打印原因）。Task 4 依赖此退出码语义。
- Produces: `pack.ps1` 打包后自动调用 verify-zip.ps1，校验失败删除 ZIP 并抛错退出。

- [ ] **Step 1: 创建 verify-zip.ps1（校验脚本）**

```powershell
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

$required = @('code/deploy/deploy.sh', 'code/backend/requirements.txt', 'code/frontend/package.json', 'data/rbac.dump', 'secrets/prod.env')
$missing = @($required | Where-Object { $names -notcontains $_ })
if ($missing.Count -gt 0) { Write-Error "缺少关键条目: $($missing -join ', ')"; exit 1 }

Write-Host "OK 条目数=$($names.Count) 反斜杠=0 关键条目齐全"
exit 0
```

- [ ] **Step 2: 验证校验脚本对坏包报错（先验证拒绝路径）**

Run: `powershell -ExecutionPolicy Bypass -File deploy\verify-zip.ps1 -Path C:\agent-deploy\agent-deploy.zip`（当前 zip 是旧反斜杠包）
Expected: 退出码 1，stderr 含 "反斜杠条目"（当前包 2675 个条目全部含 `\`，可作为天然坏包样本；若该文件已被删除，跳到 Step 3 后用新包验证通过路径 + Step 4 构造坏包）

- [ ] **Step 3: 修改 pack.ps1 步骤 4 为 ZipArchive 正斜杠打包 + 自动校验**

将 `deploy/pack.ps1` 第 61-66 行（从 `Compress-Archive ...` 到文件末尾）整体替换为：

```powershell
# 打包：ZipArchive 显式正斜杠路径（Linux python3 -m zipfile -e 依赖 / 分隔符）
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($Zip, [System.IO.Compression.ZipArchiveMode]::Create)
try {
  Get-ChildItem -LiteralPath $Stage -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($Stage.TrimEnd('\').Length).TrimStart('\').Replace('\', '/')
    $entry = $zip.CreateEntry($rel, [System.IO.Compression.CompressionLevel]::Optimal)
    $es = $entry.Open()
    try {
      $fs = [System.IO.File]::OpenRead($_.FullName)
      try { $fs.CopyTo($es) } finally { $fs.Dispose() }
    } finally { $es.Dispose() }
  }
} finally {
  $zip.Dispose()
}

# 硬校验：不合格即删除，禁止交付
& powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "verify-zip.ps1") -Path $Zip
if ($LASTEXITCODE -ne 0) {
  Remove-Item -LiteralPath $Zip -Force -ErrorAction SilentlyContinue
  throw "部署包校验失败，已删除 $Zip"
}
```

注意：`$Stage.TrimEnd('\')` 去掉暂存目录尾部反斜杠，保证 `Substring` 后相对路径以 `\` 开头可被 `TrimStart` 与 `Replace` 处理。文件头已有 `$ErrorActionPreference = "Stop"`，`throw` 会直接终止脚本。

- [ ] **Step 4: 实跑打包并验证通过路径**

Run: `powershell -ExecutionPolicy Bypass -File deploy\pack.ps1`
Expected: 输出包含 `OK 条目数=... 反斜杠=0 关键条目齐全`，随后 `打包完成: C:\agent-deploy\agent-deploy.zip`，大小约 11-12 MB。若输出 `部署包校验失败` 或抛错，检查 Step 3 代码后重跑。

- [ ] **Step 5: 独立复核新包结构（不经 pack.ps1 再跑一遍校验）**

Run: `powershell -ExecutionPolicy Bypass -File deploy\verify-zip.ps1 -Path C:\agent-deploy\agent-deploy.zip`
Expected: 退出码 0，输出 `OK 条目数=... 反斜杠=0 关键条目齐全`

- [ ] **Step 6: 构造坏包验证拒绝路径**

Run:
```powershell
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$z = [System.IO.Compression.ZipFile]::Open('C:\agent-deploy\bad-test.zip', 'Create')
[System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z, 'C:\agent-deploy\agent-deploy.zip', 'code\bad.txt') | Out-Null
$z.Dispose()
```
然后: `powershell -ExecutionPolicy Bypass -File deploy\verify-zip.ps1 -Path C:\agent-deploy\bad-test.zip; echo "exit=$LASTEXITCODE"`
Expected: 输出 `反斜杠条目` 且 `exit=1`；随后删除坏包 `Remove-Item C:\agent-deploy\bad-test.zip -Force`

- [ ] **Step 7: Commit**

```bash
git add deploy/pack.ps1 deploy/verify-zip.ps1
git commit -m "fix: portable zip packaging with forward-slash paths and hard validation"
```

---

### Task 2: deploy.sh 固定端口（3100/8100/15432，非本系统占用即终止）

**Files:**
- Modify: `deploy/deploy.sh:28-58`（self_ports + pick_port + FE/BE/PG 端口选择整块）

**Interfaces:**
- Consumes: 无（不依赖 Task 1）。
- Produces: `FE_PORT=3100`、`BE_PORT=8100`、`PG_PORT=15432` 三个固定变量（后续 .env 生成、健康检查步骤已使用这些变量名，签名不变）。Task 3 的 upgrade.sh 最终调用本脚本。

- [ ] **Step 1: 替换端口选择块**

将 `deploy/deploy.sh` 第 28-58 行（从 `# 自己项目容器映射的宿主端口` 注释到 `ok "端口: 前端=$FE_PORT 后端=$BE_PORT pg=$PG_PORT"` 为止）整体替换为：

```bash
# 自己项目容器映射的宿主端口（重跑时这些端口视为可用，避免端口漂移）
self_ports() {
  docker ps --format '{{.Names}} {{.Ports}}' 2>/dev/null | awk '/^agent-/{for(i=2;i<=NF;i++){if($i ~ /0.0.0.0:[0-9]+->/){split($i,a,":"); split(a[2],b,"->"); print b[1]}}}' | sort -u
}
# 固定端口：3100/8100/15432。被非本系统服务占用即终止并报告（不允许静默漂移）
FE_PORT=3100; BE_PORT=8100; PG_PORT=15432
for p in "$FE_PORT" "$BE_PORT" "$PG_PORT"; do
  if ss -ltn 2>/dev/null | grep -q ":$p "; then
    if self_ports | grep -qx "$p"; then
      ok "端口 $p 被本系统旧容器占用——容器重建后释放，视为可用"
    else
      die "固定端口 $p 已被其他服务占用。请先释放该端口，或手动编辑 code/deploy/.env 的 FE_PORT/BE_PORT/PG_PORT 后重跑"
    fi
  fi
done
ok "端口: 前端=$FE_PORT 后端=$BE_PORT pg=$PG_PORT"
```

删除原 `pick_port()` 函数与 FE/BE 同步上移的 while 循环（不再使用）。`.env.template` 的 `FE_PORT=__FE_PORT__` 等占位符填充逻辑（第 119-125 行）无需改动。

- [ ] **Step 2: 语法自检**

Run: `bash -n deploy/deploy.sh`
Expected: 无输出（退出码 0）。注意本机无 bash——若 `bash` 不存在，用 `git bash` 或 WSL 执行；不可用时以重读文件确认括号/引号配对代替并注明。

- [ ] **Step 3: 确认无残留引用**

Run: `rg -n "pick_port" deploy/` （本机无 rg 则用 `Select-String -Path deploy\* -Pattern "pick_port"`）
Expected: 无匹配（pick_port 已彻底删除）。

- [ ] **Step 4: Commit**

```bash
git add deploy/deploy.sh
git commit -m "fix: fix deployment ports to 3100/8100/15432, abort on foreign occupancy"
```

---

### Task 3: upgrade.sh 受控升级脚本（临时验收 → 备份 → 替换 → 部署）

**Files:**
- Create: `deploy/upgrade.sh`

**Interfaces:**
- Consumes: Task 2 的固定端口 `deploy.sh`（步骤 5 `exec bash "$DEPLOY_ROOT/code/deploy/deploy.sh"` 调用）。
- Produces: 服务器端唯一升级入口 `bash code/deploy/upgrade.sh /opt/agent_loop/agent-deploy.zip`；Task 4 的 DEPLOY.md 将以此为准。

- [ ] **Step 1: 创建 upgrade.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail
# 受控升级：上传 zip → 临时解压验收 → 备份 → 清理历史错误条目 → 受控替换 → 调用 deploy.sh
# 用法: bash code/deploy/upgrade.sh /opt/agent_loop/agent-deploy.zip

DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ZIP="${1:?用法: bash code/deploy/upgrade.sh <agent-deploy.zip 路径>}"
PASS="\033[32m"; WARN="\033[33m"; FAIL="\033[31m"; RST="\033[0m"
ok()  { echo -e "${PASS}[OK]${RST} $*"; }
warn(){ echo -e "${WARN}[WARN]${RST} $*"; }
die() { echo -e "${FAIL}[FAIL]${RST} $*"; exit 1; }

[ -f "$ZIP" ] || die "找不到 $ZIP"

echo "===== 1. 解压到临时目录验收 ====="
INCOMING="$DEPLOY_ROOT/.incoming-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$INCOMING"
python3 -m zipfile -e "$ZIP" "$INCOMING" || { rm -rf "$INCOMING"; die "解压失败（zip 损坏？）"; }
for p in code/deploy/deploy.sh code/backend/requirements.txt code/frontend/package.json data/rbac.dump secrets/prod.env; do
  [ -e "$INCOMING/$p" ] || { echo "缺少: $p"; rm -rf "$INCOMING"; die "部署包结构不正确（Windows 反斜杠打包错误会表现为此），已终止"; }
done
BAD=$(find "$INCOMING" -name '*\*' | head -5)
if [ -n "$BAD" ]; then
  echo "$BAD"
  rm -rf "$INCOMING"
  die "部署包含反斜杠命名条目（Windows 打包错误），已终止"
fi
ok "部署包结构验收通过"

echo "===== 2. 备份当前部署 ====="
BK="$DEPLOY_ROOT/backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BK"
[ -d "$DEPLOY_ROOT/code" ] && cp -a "$DEPLOY_ROOT/code" "$BK/code"
[ -d "$DEPLOY_ROOT/data" ] && cp -a "$DEPLOY_ROOT/data" "$BK/data"
if [ -f "$DEPLOY_ROOT/code/deploy/.env" ]; then
  cp "$DEPLOY_ROOT/code/deploy/.env" "$BK/.env"
fi
if docker ps --format '{{.Names}}' | grep -q '^agent-postgres$'; then
  docker exec agent-postgres pg_dump -U agent -d rbac -Fc -f /tmp/rbac-pre-upgrade.dump 2>/dev/null \
    && docker cp agent-postgres:/tmp/rbac-pre-upgrade.dump "$BK/rbac-pre-upgrade.dump" \
    && docker exec agent-postgres rm -f /tmp/rbac-pre-upgrade.dump \
    && ok "数据库已备份到 $BK/rbac-pre-upgrade.dump" \
    || warn "数据库备份失败（postgres 未就绪？），继续"
fi
ok "备份完成: $BK"

echo "===== 3. 清理历史反斜杠错误条目（仅部署根第一层） ====="
cd "$DEPLOY_ROOT"
find . -maxdepth 1 -name '*\*' -print > "$BK/backslash-entries.txt" || true
if [ -s "$BK/backslash-entries.txt" ]; then
  echo "---- 以下为历史错误文件，将删除（清单已备份）----"
  cat "$BK/backslash-entries.txt"
  find . -maxdepth 1 -name '*\*' -delete
  ok "已清理 $(wc -l < "$BK/backslash-entries.txt") 个错误条目"
else
  ok "无历史反斜杠错误条目"
fi

echo "===== 4. 受控替换 ====="
rm -rf "$DEPLOY_ROOT/code" "$DEPLOY_ROOT/data" "$DEPLOY_ROOT/secrets"
cp -a "$INCOMING/code" "$DEPLOY_ROOT/code"
cp -a "$INCOMING/data" "$DEPLOY_ROOT/data"
cp -a "$INCOMING/secrets" "$DEPLOY_ROOT/secrets"
[ -f "$BK/.env" ] && cp "$BK/.env" "$DEPLOY_ROOT/code/deploy/.env" && ok "已恢复原 .env（数据库密码/密钥复用）"
rm -rf "$INCOMING"
ok "替换完成"

echo "===== 5. 调用部署脚本 ====="
exec bash "$DEPLOY_ROOT/code/deploy/deploy.sh"
```

注意：`find -name '*\*'` 中单引号内的 `*\*` 匹配「以任意字符开头、以字面反斜杠结尾」的文件名——正是 Windows 打包错误产生的条目形态。`cd "$DEPLOY_ROOT"` 后的删除只作用于第一层，不触碰 `code/ data/ secrets/` 内部。

- [ ] **Step 2: 语法自检**

Run: `bash -n deploy/upgrade.sh`
Expected: 无输出（退出码 0）。bash 不可用时以重读文件核对括号/引号配对代替并注明。

- [ ] **Step 3: 对照 spec 检查回滚路径**

确认（重读文件核对）：
- 备份目录含 `code/`、`data/`、`.env`、`rbac-pre-upgrade.dump`（回滚素材齐全）。
- 替换顺序：先备份后删除（第 2 步在第 4 步之前）。
- `rm -rf` 只针对 `code data secrets` 三个固定目录名，无通配符。

- [ ] **Step 4: Commit**

```bash
git add deploy/upgrade.sh
git commit -m "feat: controlled upgrade script with staging validation, backup and swap"
```

---

### Task 4: DEPLOY.md 更新 + 集成验证

**Files:**
- Modify: `deploy/DEPLOY.md`
- Test: 实跑全部本地验证命令（依赖 Task 1/2/3 产物）

**Interfaces:**
- Consumes: Task 1 的 `pack.ps1`/`verify-zip.ps1`、Task 3 的 `upgrade.sh`。
- Produces: 最终交付手册（服务器操作唯一入口 = upgrade.sh）。

- [ ] **Step 1: 更新 DEPLOY.md**

替换第 24-42 行（方式 A 的 A3 解压 + A4 使用）为：

```markdown
### A3. 解压 + 部署（宝塔「终端」，一条命令）
1. 左侧菜单点「终端」→「开始终端」（默认 root，直接可用）
2. 粘贴执行（粘贴后按回车）：
   ```
   cd /opt/agent_loop
   ```
   ```
   bash code/deploy/upgrade.sh agent-deploy.zip
   ```
3. 脚本会自动：临时解压验收结构 → 备份旧代码/数据/数据库 → 清理历史错误文件 → 替换 → 部署
4. **等待 5-15 分钟**（下载基础镜像 + 构建 + 还原数据）。每步显示 ✅/❌，最后出现「部署完成」报告：
   - 报告含前端地址（`http://115.29.187.169:3100`）和 admin 密码
   - **马上截图**——密码只显示这一次（脚本自动销毁密钥文件）

### A4. 使用
浏览器打开 `http://115.29.187.169:3100`，用 `admin` + 截图里的密码登录。
验证：历史会话可见、文件库文件可读、发一条消息看流式回复。

### A5. 以后升级（新版本打包后）
1. 本地重新运行 pack.ps1，得到新 agent-deploy.zip
2. 上传覆盖 /opt/agent_loop/agent-deploy.zip
3. 终端执行同一条命令：
   ```
   bash code/deploy/upgrade.sh agent-deploy.zip
   ```
   备份自动存到 /opt/agent_loop/backups/<时间戳>/（旧代码/数据/数据库，可回滚）
```

将第 53-61 行（方式 B 的第三步）中的解压命令改为：

```bash
cd /opt/agent_loop
bash code/deploy/upgrade.sh agent-deploy.zip
```

（删除原 `python3 -m zipfile -e ...` 直解压命令。）

将「常见问题」表第 77 行「端口被占用」行改为：

```markdown
| 端口被占用 | 端口固定为 3100/8100。若报「固定端口已被其他服务占用」：先释放该端口，或手动编辑 code/deploy/.env 的 FE_PORT/BE_PORT 后重跑（不推荐改） |
```

将「日常运维」表下追加回滚说明：

```markdown
**回滚**：部署失败时 `bash restart.sh` 无法解决，可执行：
```
cd /opt/agent_loop/backups/<最新时间戳>
cp -a code /opt/agent_loop/code && cp -a data /opt/agent_loop/data
bash /opt/agent_loop/code/deploy/deploy.sh
```
```

- [ ] **Step 2: 重跑打包确认全链路**

Run: `powershell -ExecutionPolicy Bypass -File deploy\pack.ps1`
Expected: `OK 条目数=... 反斜杠=0 关键条目齐全` + `打包完成: C:\agent-deploy\agent-deploy.zip`

- [ ] **Step 3: 独立复核 + 坏包拒绝（关键验收）**

Run:
```powershell
powershell -ExecutionPolicy Bypass -File deploy\verify-zip.ps1 -Path C:\agent-deploy\agent-deploy.zip; echo "good_exit=$LASTEXITCODE"
Add-Type -AssemblyName System.IO.Compression
$z = [System.IO.Compression.ZipFile]::Open('C:\agent-deploy\bad-test.zip', 'Create')
[System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z, 'C:\agent-deploy\agent-deploy.zip', 'code\bad.txt') | Out-Null
$z.Dispose()
powershell -ExecutionPolicy Bypass -File deploy\verify-zip.ps1 -Path C:\agent-deploy\bad-test.zip; echo "bad_exit=$LASTEXITCODE"
Remove-Item C:\agent-deploy\bad-test.zip -Force
```
Expected: `good_exit=0` 且 `bad_exit=1`（两者同时满足才算通过）。

- [ ] **Step 4: 脚本静态校验**

Run: `bash -n deploy/deploy.sh deploy/upgrade.sh`
Expected: 无输出（退出码 0）。bash 不可用时以重读两份脚本确认括号/引号配对代替并注明。

- [ ] **Step 5: 抽查新 zip 内目录结构（模拟 Linux 视角）**

Run:
```powershell
Add-Type -AssemblyName System.IO.Compression.FileSystem
$z = [System.IO.Compression.ZipFile]::OpenRead('C:\agent-deploy\agent-deploy.zip')
$names = @($z.Entries | ForEach-Object { $_.FullName }); $z.Dispose()
$names | Select-Object -First 8
$names | Where-Object { $_ -match '^(code|data|secrets)/' } | Group-Object { ($_ -split '/')[0] } | Select-Object Name,Count
```
Expected: 前 8 条形如 `code/backend/...`（正斜杠）；分组显示 `code`、`data`、`secrets` 三个根目录。

- [ ] **Step 6: Commit**

```bash
git add deploy/DEPLOY.md
git commit -m "docs: upgrade flow via upgrade.sh, fixed ports, rollback instructions"
```

---

## 自审记录

- **Spec 覆盖**：①可移植 ZIP（生成+硬校验）→ Task 1；②服务器临时验收 → Task 3 步骤 1；③备份/替换边界（.env 恢复、数据库备份、卷不删）→ Task 3 步骤 2/4；④反斜杠条目清理 → Task 3 步骤 3；⑤固定端口 → Task 2；验证与验收 → Task 4 步骤 2-5；回滚 → Task 4 步骤 1（DEPLOY.md）+ Task 3 备份产物。
- **占位符扫描**：无 TBD/TODO；所有脚本步骤均含完整可粘贴代码。
- **类型一致性**：`verify-zip.ps1` 路径在 pack.ps1 中经 `$PSScriptRoot` 推导（同目录）；`upgrade.sh` 的 `DEPLOY_ROOT` 推导与 deploy.sh 一致（`dirname $0/../..`）；FE_PORT/BE_PORT/PG_PORT 变量名与 .env 生成、健康检查引用保持一致。
- **并行性**：Task 1 与 Task 2 改不同文件可并行；Task 3 依赖 Task 2 的 deploy.sh；Task 4 依赖全部——波次 A（1∥2）→ Task 3 → Task 4。
- **无 pytest 依赖**：本计划全部为脚本交付，无共享测试 DB 冲突，子代理可安全并行（Task 1/2）。
