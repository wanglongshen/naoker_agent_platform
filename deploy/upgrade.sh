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
for p in code/deploy/deploy.sh code/backend/requirements.txt code/frontend/package.json code/deepseek-harness/apps/cli/lib/bin.js code/dsh-platform/packages/server-connector/lib/index.js data/rbac.dump secrets/prod.env; do
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
