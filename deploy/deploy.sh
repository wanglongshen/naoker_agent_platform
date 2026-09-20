#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"   # = /opt/agent-deploy（脚本在 code/deploy/ 下）
COMPOSE_DIR="$DEPLOY_ROOT/code/deploy"
ENV_FILE="$COMPOSE_DIR/.env"
PASS="\033[32m"; WARN="\033[33m"; FAIL="\033[31m"; RST="\033[0m"
ok()  { echo -e "${PASS}[OK]${RST} $*"; }
warn(){ echo -e "${WARN}[WARN]${RST} $*"; }
die() { echo -e "${FAIL}[FAIL]${RST} $*"; exit 1; }

echo "===== 0. 语法自检 ====="
bash -n "$0" || die "脚本自身语法错误"
command -v docker >/dev/null || die "未找到 docker"
docker compose version >/dev/null 2>&1 || die "未找到 docker compose v2"

echo "===== 1. 预检 ====="
FREE_MEM=$(free -m | awk '/Mem:/{print int($7/1024)}')
[ "${FREE_MEM:-0}" -ge 2 ] || warn "可用内存 <2G，部署后可能偏慢"
FREE_DISK=$(df -m "$DEPLOY_ROOT" | awk 'NR==2{print int($4/1024)}')
[ "${FREE_DISK:-0}" -ge 10 ] || die "磁盘剩余 <10GB，请清理后再部署"
if [ ! -f /swapfile ] && ! swapon --show | grep -q /swapfile; then
  warn "检测到无 swap，创建 2G swap（防内存打满杀进程）"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

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

# 镜像加速提示（只提示不自动改：改 daemon.json 需重启 docker，会连带重启现有业务容器）
if [ ! -f /etc/docker/daemon.json ] || ! grep -q registry-mirrors /etc/docker/daemon.json 2>/dev/null; then
  warn "未配置 Docker 镜像加速——首次拉取基础镜像可能很慢（国内服务器建议配置）"
  warn "可选（不动现有容器）：编辑 /etc/docker/daemon.json 加 registry-mirrors，重启 docker 后重跑本脚本"
fi

echo "===== 2. 校验密钥来源 ====="
PROD_ENV="$DEPLOY_ROOT/secrets/prod.env"
# 密钥来源：已有 .env（上次部署产物，优先）> prod.env（部署包）
# 若 .env 含未填充占位符（上次失败生成的半成品），回退 prod.env——否则会用占位符"自己填自己"
KEY_SRC=""
if [ -f "$ENV_FILE" ] && grep -q '^JWT_SECRET=.\+' "$ENV_FILE" && ! grep -q '__FROM_PROD_ENV__' "$ENV_FILE"; then
  KEY_SRC="$ENV_FILE"
  ok "密钥来源: 已有 .env（复用，prod.env 可已销毁）"
elif [ -f "$PROD_ENV" ]; then
  KEY_SRC="$PROD_ENV"
  ok "密钥来源: secrets/prod.env"
fi
[ -n "$KEY_SRC" ] || die "缺少密钥来源：需要 secrets/prod.env 或已有 .env（至少其一）"
MISSING=""
for k in JWT_SECRET INITIAL_ADMIN_PASSWORD DEEPSEEK_API_KEY TAVILY_API_KEY FEISHU_APP_ID FEISHU_APP_SECRET FEISHU_TOKEN_ENCRYPTION_KEY; do
  grep -q "^${k}=.\+" "$KEY_SRC" || MISSING="$MISSING $k"
done
[ -z "$MISSING" ] || die "密钥来源($KEY_SRC) 缺少:$MISSING"

# 公网 IP 探测：密钥来源显式配置 > 阿里云 metadata > hostname 兜底
if grep -q '^SERVER_IP=.\+' "$KEY_SRC" 2>/dev/null; then
  SERVER_IP=$(grep '^SERVER_IP=' "$KEY_SRC" | cut -d= -f2)
  ok "公网 IP（显式配置）: $SERVER_IP"
elif EIP=$(curl -s --max-time 3 http://100.100.100.200/latest/meta-data/eipv4 2>/dev/null) && [ -n "$EIP" ]; then
  SERVER_IP="$EIP"
  ok "公网 IP（阿里云 metadata）: $SERVER_IP"
else
  SERVER_IP="$(hostname -I | awk '{print $1}')"
  warn "未探测到公网 IP，使用 $SERVER_IP——若不对，请 echo 'SERVER_IP=公网IP' >> secrets/prod.env 后重跑"
fi

echo "===== 3. 生成 .env ====="
# 数据库密码只生成一次：重跑复用旧值（postgres 卷密码首次初始化后固定，变了会失配）
if [ -f "$ENV_FILE" ] && grep -q '^POSTGRES_PASSWORD=' "$ENV_FILE"; then
  PG_PWD=$(grep '^POSTGRES_PASSWORD=' "$ENV_FILE" | cut -d= -f2)
  ok "复用已有数据库密码"
else
  PG_PWD=$(openssl rand -hex 16)
fi
cp "$COMPOSE_DIR/.env.template" "$ENV_FILE"
# __GENERATE__ → 随机数据库密码（两处: POSTGRES_PASSWORD 与 DATABASE_URL 内）
sed -i "s|__GENERATE__|$PG_PWD|g" "$ENV_FILE"
# 逐 key 从密钥来源填充 __FROM_PROD_ENV__
for k in JWT_SECRET INITIAL_ADMIN_PASSWORD DEEPSEEK_API_KEY TAVILY_API_KEY FEISHU_APP_ID FEISHU_APP_SECRET FEISHU_TOKEN_ENCRYPTION_KEY; do
  v=$(grep "^${k}=" "$KEY_SRC" | cut -d= -f2-)
  python3 - "$ENV_FILE" "$k" "$v" <<'EOF'
import sys, pathlib
p, k, v = sys.argv[1], sys.argv[2], sys.argv[3]
lines = pathlib.Path(p).read_text(encoding='utf-8').splitlines()
out = [f"{k}={v}" if ln.startswith(k + "=") else ln for ln in lines]
pathlib.Path(p).write_text("\n".join(out) + "\n", encoding='utf-8')
EOF
done
# 服务器 IP 与端口占位符
python3 - "$ENV_FILE" "$SERVER_IP" "$FE_PORT" "$BE_PORT" "$PG_PORT" <<'EOF'
import sys, pathlib
p, ip, fe, be, pg = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
t = pathlib.Path(p).read_text(encoding='utf-8')
t = t.replace("__SERVER_IP__", ip).replace("__FE_PORT__", fe).replace("__BE_PORT__", be).replace("__PG_PORT__", pg)
pathlib.Path(p).write_text(t, encoding='utf-8')
EOF
ok ".env 已生成（数据库密码随机）"
# 兜底校验：任一占位符残留 = 密钥来源无效，直接报错（避免部署出"认证失败"的半成品）
if grep -q '__FROM_PROD_ENV__\|__GENERATE__\|__SERVER_IP__\|__FE_PORT__\|__BE_PORT__\|__PG_PORT__' "$ENV_FILE"; then
  die ".env 仍有未替换占位符——secrets/prod.env 可能缺失或损坏，请检查后重跑（已生成的 .env 会被重新填充）"
fi

echo "===== 4. 构建镜像 ====="
# 构建前先停应用容器：释放内存（4G 机器并行构建峰值高，防止 OOM 杀构建进程）+ 断开 DB 连接
APP_CONTAINERS=(agent-backend agent-worker agent-task-chain-worker agent-dsh-sync-worker agent-web-renderer agent-frontend)
RUNNING_APP_CONTAINERS=()
for container in "${APP_CONTAINERS[@]}"; do
  if docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null | grep -qx true; then
    RUNNING_APP_CONTAINERS+=("$container")
  fi
done
if [ ${#RUNNING_APP_CONTAINERS[@]} -gt 0 ]; then
  echo "---- 停止应用容器，释放内存并断开数据库连接 ----"
  docker stop --time 30 "${RUNNING_APP_CONTAINERS[@]}" || die "无法停止应用容器: ${RUNNING_APP_CONTAINERS[*]}"
fi
# 串行构建（--parallel=false）：避免多镜像并行构建把 4G 内存打爆（OOM 杀构建）
docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" build --parallel=false || {
  warn "构建失败，重试 1 次"; sleep 5; docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" build --parallel=false || die "构建失败"
}

echo "===== 5. 起库 + 还原数据 ====="
# 恢复前必须断开应用连接：容器名固定，不能吞掉 compose stop 的失败。
APP_CONTAINERS=(agent-backend agent-worker agent-task-chain-worker agent-dsh-sync-worker agent-web-renderer agent-frontend)
RUNNING_APP_CONTAINERS=()
for container in "${APP_CONTAINERS[@]}"; do
  if docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null | grep -qx true; then
    RUNNING_APP_CONTAINERS+=("$container")
  fi
done
if [ ${#RUNNING_APP_CONTAINERS[@]} -gt 0 ]; then
  echo "---- 停止应用容器，释放内存并断开数据库连接 ----"
  docker stop --time 30 "${RUNNING_APP_CONTAINERS[@]}" || die "无法停止应用容器: ${RUNNING_APP_CONTAINERS[*]}"
fi
for container in "${APP_CONTAINERS[@]}"; do
  if docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null | grep -qx true; then
    die "应用容器仍在运行，拒绝恢复数据库: $container"
  fi
done
# 预拉基础镜像（国内 Docker Hub 不稳定：可见进度 + 10 分钟超时 + 重试 3 次；已下载层复用）
for img in pgvector/pgvector:pg16 redis:7; do
  for try in 1 2 3; do
    echo "---- 拉取 $img（第${try}/3 次，最长 10 分钟）----"
    if timeout 600 docker pull "$img"; then ok "拉取 $img 成功"; break; fi
    warn "拉取 $img 失败或超时（第${try}/3 次），10s 后重试"; sleep 10
    [ $try = 3 ] && warn "拉取 $img 连续失败——建议配置 Docker 镜像加速后重跑 deploy.sh（已下载层会复用）"
  done
done
docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" up -d postgres redis
# 等待 postgres 就绪（低配机器首次 initdb 可能 2 分钟；失败时打印容器日志定位）
echo "---- 等待 postgres 就绪（最长 3 分钟）----"
READY=0
for i in $(seq 1 90); do
  if docker exec agent-postgres pg_isready -U agent -d rbac >/dev/null 2>&1; then READY=1; break; fi
  sleep 2
done
if [ $READY = 1 ]; then
  ok "postgres 就绪"
else
  echo "---- agent-postgres 容器日志（最后 40 行）----"
  docker logs agent-postgres --tail 40 2>&1 || true
  die "postgres 未就绪（日志如上，常见原因: 初始化慢/内存不足/卷损坏）"
fi
# 密码验证：旧卷与新 .env 密码失配时（如 .env 曾重建）立即给出删卷指引，而非等到迁移才报错
if docker exec -e PGPASSWORD="$PG_PWD" agent-postgres psql -U agent -d rbac -c "SELECT 1" >/dev/null 2>&1; then
  ok "数据库密码验证通过"
else
  die "数据库密码失配（旧卷密码与新 .env 不一致）。修复: docker compose -f $COMPOSE_DIR/docker-compose.yml --env-file $ENV_FILE down && docker volume rm agent_agent-pgdata && bash 重跑本脚本（数据会从 rbac.dump 恢复）"
fi
if [ -f "$DEPLOY_ROOT/data/rbac.dump" ]; then
  ok "导入数据库 dump（幂等：先清空再导入）"
  # 防御性清理：没有应用容器后，终止所有残留连接再删库。
  docker exec agent-postgres psql -v ON_ERROR_STOP=1 -U agent -d postgres -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'rbac' AND pid <> pg_backend_pid();" \
    || die "无法终止 rbac 的残留数据库连接"
  docker exec agent-postgres dropdb -U agent --if-exists --force rbac \
    || die "清空 rbac 数据库失败"
  docker exec agent-postgres createdb -U agent rbac \
    || die "创建 rbac 数据库失败"
  docker exec -i agent-postgres pg_restore -U agent -d rbac --clean --if-exists --no-owner < "$DEPLOY_ROOT/data/rbac.dump" \
    || die "pg_restore 导入失败（stdin 模式单线程；--no-owner 使对象归 agent 用户）"
  # 修复历史 Windows 反斜杠 storage_key（Windows 打包的旧 dump 会带 var\files\...，Linux 读不到）
  docker exec agent-postgres psql -U agent -d rbac -c \
    "UPDATE file_objects SET storage_key = replace(storage_key, chr(92), '/') WHERE strpos(storage_key, chr(92)) > 0;" \
    >/dev/null 2>&1 && ok "storage_key 路径已规范化（正斜杠）" || warn "storage_key 规范化跳过"
fi

echo "===== 6. 还原文件库 ====="
if [ -d "$DEPLOY_ROOT/data/var" ] && [ -n "$(ls -A "$DEPLOY_ROOT/data/var" 2>/dev/null)" ]; then
  FILES_VOL="agent_agent-files"
  docker volume create "$FILES_VOL" >/dev/null 2>&1 || true
  if docker run --rm -v "$FILES_VOL":/var -v "$DEPLOY_ROOT/data":/data agent-backend cp -a /data/var/. /var/ 2>/dev/null; then
    ok "文件库已还原到卷 $FILES_VOL"
  else
    warn "文件库还原失败（backend 镜像不可用？可部署后手动复制）"
  fi
else
  warn "部署包无 data/var（全新部署，文件库留空）"
fi

echo "===== 7. 数据库迁移 ====="
docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" run --rm migrate || die "alembic 迁移失败"

echo "===== 8. 起服务 ====="
for s in backend worker task-chain-worker dsh-sync-worker web-renderer frontend; do
  for try in 1 2 3; do
    if docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" up -d "$s" >/dev/null 2>&1; then break; fi
    warn "$s 第${try}次启动失败，5s 后重试"; sleep 5
    [ $try = 3 ] && { docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" logs --tail 50 "$s" || true; die "$s 启动失败"; }
  done
done

echo "===== 9. 健康检查 ====="
BE_HEALTHY=0
for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${BE_PORT}/health" >/dev/null 2>&1; then BE_HEALTHY=1; break; fi
  sleep 2
done
FE_HEALTHY=0
for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${FE_PORT}/" >/dev/null 2>&1; then FE_HEALTHY=1; break; fi
  sleep 2
done
[ $BE_HEALTHY = 1 ] || die "后端健康检查失败（查看日志: bash logs.sh backend）"
[ $FE_HEALTHY = 1 ] || warn "前端健康检查未通过，请查看日志"
if ! docker ps --format '{{.Names}}' | grep -q agent-web-renderer; then warn "web-renderer 未运行（渲染工具降级，不影响主服务）"; fi

echo "===== 10. 清理与报告 ====="
if [ -f "$DEPLOY_ROOT/secrets/prod.env" ]; then
  shred -u "$DEPLOY_ROOT/secrets/prod.env" && ok "已销毁 prod.env"
fi
cat <<EOF

==================== 部署完成 ====================
前端:   http://${SERVER_IP}:${FE_PORT}
后端:   http://${SERVER_IP}:${BE_PORT}
admin:  $(grep '^INITIAL_ADMIN_USERNAME=' "$ENV_FILE" | cut -d= -f2) / $(grep '^INITIAL_ADMIN_PASSWORD=' "$ENV_FILE" | cut -d= -f2)
运维命令（在 $COMPOSE_DIR 下）:
  查看日志:  bash logs.sh backend
  重启:      bash restart.sh
  备份:      bash backup.sh
  状态:      bash status.sh
===================================================
EOF
