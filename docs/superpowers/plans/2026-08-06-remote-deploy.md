# 远端 Ubuntu 一键部署 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一套"傻瓜式"远端部署套件：本地 pack.ps1 打包（代码+数据+配置）→ Xftp 上传 → 服务器 `bash deploy.sh` 一键部署到 Docker Compose（与现有服务零冲突），附运维脚本与操作手册。

**Architecture:** 全套容器化（独立网络 agent-net，端口自定义映射避开 8000/82 及所有已监听端口）；postgres:18 接收本地 pg_dump 18.4 导出的全量数据；deploy.sh 幂等可重跑（预检→校验→构建→起库→还原→迁移→起服务→健康检查→清理密钥）。

**Tech Stack:** Docker Compose v2、Python 3.13-slim、Node 24-slim、patchright（chromium）、PostgreSQL 18、Redis 7、PowerShell 5.1（pack.ps1）、Bash（deploy.sh）。

## Global Constraints

- **8000 和 82 端口视为已占用**，端口选择显式排除；3100/8100/15432 冲突自动 +1 递增（前端与后端同轮递增保持相差 5000）
- **postgres 镜像必须 postgres:18**（本地 pg_dump 18.4 的 dump 只能导入 ≥18 服务器）
- 内存上限合计 ~2.3G：postgres 512M / redis 128M / backend 768M / worker 256M / web-renderer 384M / frontend 256M（cgroup 硬限制，不挤占现有服务 ~1G）
- WORKER_CONCURRENCY=1、WEB_RENDERER_HEADLESS=true
- 所有容器 `restart: unless-stopped`；密钥只经环境变量注入，**不写入 compose 明文、不 COPY 进镜像**；部署后 `shred -u prod.env`
- 部署包目录约定：服务器 `/opt/agent-deploy/`（zip 内结构：code/ + data/ + secrets/）
- 幂等可重跑：deploy.sh 任何一步失败，修复后重跑即可
- 本地 Windows 无 Docker、无 bash——Dockerfile/compose 用 PyYAML 校验结构；shell 脚本用 `bash -n`（服务器端预检自跑）；pack.ps1 本地实跑验证
- commit 从仓库根 C:\01_agent_loop_pro 执行，仓库根相对路径
- 打包排除：node_modules / .next / .venv / __pycache__ / var / .git / *.zip

---

### Task 1: Dockerfile.backend + Dockerfile.frontend + .dockerignore

**Files:**
- Create: `deploy/Dockerfile.backend`
- Create: `deploy/Dockerfile.frontend`
- Create: `deploy/.dockerignore`

**Interfaces:**
- Consumes: `backend/requirements.txt`（pip 依赖清单）、`frontend/package.json`（npm 依赖与 build/start 脚本）、`backend/app/workers/web_renderer.py`（patchright 启动方式）
- Produces: 两个可构建镜像。Task 2 的 compose 以 `build: {context: .., dockerfile: deploy/Dockerfile.backend}` 引用；**镜像内工作目录必须是 `/app/backend` 与 `/app/frontend`**（compose 的 working_dir 依赖此约定）

- [ ] **Step 1: 确认依赖清单**（读 `backend/requirements.txt` 与 `frontend/package.json` 的 scripts，确认 pip/npm 命令与 Node 版本要求）

- [ ] **Step 2: 写 `deploy/Dockerfile.backend`**

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libxml2 \
        libxslt1.1 \
        libjpeg62-turbo \
        libwebp7 \
        libtiff6 \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/ ./

# patchright bundled chromium（Linux 默认 channel=None 走 bundled chromium）
RUN python -m patchright install chromium || true

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: 写 `deploy/Dockerfile.frontend`**（多阶段：build 阶段产出 .next，运行阶段 next start）

```dockerfile
# syntax=docker/dockerfile:1
FROM node:24-slim AS builder

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

FROM node:24-slim AS runner

WORKDIR /app/frontend
ENV NODE_ENV=production
COPY --from=builder /app/frontend ./
EXPOSE 3000
CMD ["npm", "run", "start"]
```

- [ ] **Step 4: 写 `deploy/.dockerignore`**（构建上下文用仓库根，排除一切不需要进镜像的）

```
**/node_modules
**/.next
**/.venv
**/__pycache__
**/.pytest_cache
**/var
.git
*.zip
docs
.superpowers
.idea
.cortexkit
*.html
.env
backend/.env
frontend/.env*
```

- [ ] **Step 5: 结构校验**（本地无 Docker，用 Python 检查 Dockerfile 存在且关键指令在）

```
cd C:\01_agent_loop_pro
python -X utf8 -c "import pathlib; b=pathlib.Path(r'deploy/Dockerfile.backend').read_text(encoding='utf-8'); f=pathlib.Path(r'deploy/Dockerfile.frontend').read_text(encoding='utf-8'); assert 'patchright install chromium' in b; assert 'npm run build' in f and 'npm run start' in f; assert 'postgres:18' not in b; print('Dockerfiles OK')"
```
Expected: `Dockerfiles OK`

- [ ] **Step 6: Commit**（从仓库根）

```bash
git add deploy/Dockerfile.backend deploy/Dockerfile.frontend deploy/.dockerignore
git commit -m "feat: dockerfiles for backend (python 3.13 + patchright chromium) and frontend (next build)"
```

---

### Task 2: docker-compose.yml + deploy/.env.template

**Files:**
- Create: `deploy/docker-compose.yml`
- Create: `deploy/.env.template`

**Interfaces:**
- Consumes: Task 1 的两个 Dockerfile（build 引用）；现有后端配置项（backend/app/core/config.py 的 env 名：DATABASE_URL/REDIS_URL/WEB_RENDERER_URL/WORKER_CONCURRENCY/WEB_RENDERER_HEADLESS/CORS_ORIGINS/COOKIE_SECURE 等）
- Produces: compose 服务名（**postgres/redis/backend/worker/web-renderer/frontend/migrate**）与网络名 **agent-net**、卷名（agent-pgdata/agent-redisdata/agent-files）。Task 3 的 deploy.sh 按这些名字做 docker compose 操作与健康检查；Task 4 运维脚本按服务名看日志

- [ ] **Step 1: 写 `deploy/.env.template`**（deploy.sh 据此生成最终 .env；所有值由脚本填充）

```env
# 由 deploy.sh 自动生成，勿手改
POSTGRES_DB=rbac
POSTGRES_USER=agent
POSTGRES_PASSWORD=__GENERATE__
DATABASE_URL=postgresql+asyncpg://agent:__GENERATE__@postgres:5432/rbac
JWT_SECRET=__FROM_PROD_ENV__
JWT_EXPIRE_MINUTES=43200
COOKIE_SECURE=false
CORS_ORIGINS=http://__SERVER_IP__:__FE_PORT__
INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_PASSWORD=__FROM_PROD_ENV__
DEEPSEEK_API_KEY=__FROM_PROD_ENV__
DEEPSEEK_MODEL=deepseek-v4-flash
TAVILY_API_KEY=__FROM_PROD_ENV__
REDIS_URL=redis://redis:6379/0
WORKER_CONCURRENCY=1
WEB_RENDERER_URL=http://web-renderer:9001
WEB_RENDERER_HEADLESS=true
WEB_RENDERER_CHANNEL=
FEISHU_APP_ID=__FROM_PROD_ENV__
FEISHU_APP_SECRET=__FROM_PROD_ENV__
FEISHU_REDIRECT_URI=http://__SERVER_IP__:__BE_PORT__/api/feishu/oauth/callback
FEISHU_TOKEN_ENCRYPTION_KEY=__FROM_PROD_ENV__
NEXT_PUBLIC_API_BASE_URL=http://__SERVER_IP__:__BE_PORT__
```

- [ ] **Step 2: 写 `deploy/docker-compose.yml`**

```yaml
name: agent

networks:
  agent-net:
    driver: bridge

volumes:
  agent-pgdata:
  agent-redisdata:
  agent-files:

services:
  postgres:
    image: postgres:18
    container_name: agent-postgres
    restart: unless-stopped
    mem_limit: 512m
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - agent-pgdata:/var/lib/postgresql/data
    networks: [agent-net]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 3s
      retries: 12

  redis:
    image: redis:7
    container_name: agent-redis
    restart: unless-stopped
    mem_limit: 128m
    volumes:
      - agent-redisdata:/data
    networks: [agent-net]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 12

  backend:
    build:
      context: ..
      dockerfile: deploy/Dockerfile.backend
    container_name: agent-backend
    restart: unless-stopped
    mem_limit: 768m
    env_file: .env
    environment:
      DATABASE_URL: ${DATABASE_URL}
      REDIS_URL: ${REDIS_URL}
      WEB_RENDERER_URL: ${WEB_RENDERER_URL}
      WEB_RENDERER_HEADLESS: ${WEB_RENDERER_HEADLESS}
      WORKER_CONCURRENCY: ${WORKER_CONCURRENCY}
    volumes:
      - agent-files:/app/backend/var
    networks: [agent-net]
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    ports:
      - "${BE_PORT}:8000"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]
      interval: 10s
      timeout: 5s
      retries: 12

  worker:
    build:
      context: ..
      dockerfile: deploy/Dockerfile.backend
    container_name: agent-worker
    restart: unless-stopped
    mem_limit: 256m
    env_file: .env
    command: ["python", "-m", "app.workers.agent_worker"]
    volumes:
      - agent-files:/app/backend/var
    networks: [agent-net]
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  web-renderer:
    build:
      context: ..
      dockerfile: deploy/Dockerfile.backend
    container_name: agent-web-renderer
    restart: unless-stopped
    mem_limit: 384m
    command: ["python", "-m", "app.workers.web_renderer"]
    networks: [agent-net]
    depends_on:
      backend:
        condition: service_healthy

  frontend:
    build:
      context: ..
      dockerfile: deploy/Dockerfile.frontend
    container_name: agent-frontend
    restart: unless-stopped
    mem_limit: 256m
    env_file: .env
    environment:
      NEXT_PUBLIC_API_BASE_URL: ${NEXT_PUBLIC_API_BASE_URL}
    networks: [agent-net]
    depends_on:
      backend:
        condition: service_healthy
    ports:
      - "${FE_PORT}:3000"

  migrate:
    build:
      context: ..
      dockerfile: deploy/Dockerfile.backend
    container_name: agent-migrate
    env_file: .env
    command: ["alembic", "upgrade", "head"]
    volumes:
      - agent-files:/app/backend/var
    networks: [agent-net]
    depends_on:
      postgres:
        condition: service_healthy
    restart: "no"
```

**关键说明**：
- `backend/worker/migrate` 同镜像；migrate 一次性容器（`restart: "no"`）
- **env_file: .env 相对 compose 文件目录解析**——deploy.sh 必须把生成的 .env 写到 `code/deploy/.env`（与 compose 同目录），Task 3 的路径约定即基于此
- 端口经 env 注入：backend `${BE_PORT}:8000`、frontend `${FE_PORT}:3000`；postgres 默认不映射（backup.sh 临时用 docker run 映射）

- [ ] **Step 3: 结构校验**（PyYAML）

```
cd C:\01_agent_loop_pro
python -X utf8 -c "import yaml; d=yaml.safe_load(open(r'deploy/docker-compose.yml',encoding='utf-8')); s=d['services']; assert set(s)=={'postgres','redis','backend','worker','web-renderer','frontend','migrate'}; assert 'agent-net' in d['networks']; assert all('restart' in v for k,v in s.items() if k!='migrate'); print('compose OK, services:', list(s))"
```
Expected: `compose OK, services: [...]`

- [ ] **Step 4: Commit**（从仓库根）

```bash
git add deploy/docker-compose.yml deploy/.env.template
git commit -m "feat: docker compose stack with isolated network, memory limits, healthchecks"
```

---

### Task 3: deploy/deploy.sh（一键部署）

**Files:**
- Create: `deploy/deploy.sh`

**Interfaces:**
- Consumes: Task 2 的 compose（服务名/卷/网络）、`.env.template`（占位符替换）、spec 的 prod.env 结构（secrets/prod.env：JWT_SECRET/INITIAL_ADMIN_PASSWORD/DEEPSEEK_API_KEY/TAVILY_API_KEY/FEISHU_APP_ID/FEISHU_APP_SECRET/FEISHU_TOKEN_ENCRYPTION_KEY）
- Produces: 完整部署流程脚本。Task 5 的 pack.ps1 把它打进 zip 的 code/deploy/；Task 6 手册按它写操作步骤

- [ ] **Step 1: 写 `deploy/deploy.sh`**（完整脚本，逐节实现 spec 的 ①~⑨；核心逻辑如下，须完整落盘）

```bash
#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"   # = /opt/agent-deploy（脚本在 code/deploy/ 下）
COMPOSE_DIR="$DEPLOY_ROOT/code/deploy"
ENV_FILE="$COMPOSE_DIR/.env"
SERVER_IP="$(hostname -I | awk '{print $1}')"
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

pick_port() {  # $1=起始端口 $2=端口名（用于唯一变量）；排除 8000/82 与已监听
  local start=$1 name=$2 p=$start
  local used; used=$(ss -ltn 2>/dev/null | awk 'NR>1{split($4,a,":"); print a[length(a)]}' | sort -u) || used=""
  while true; do
    if [ "$p" != "8000" ] && [ "$p" != "82" ] && ! echo "$used" | grep -qx "$p"; then
      echo "$p"; return 0
    fi
    p=$((p+1))
    [ $p -le $((start+50)) ] || die "端口范围耗尽"
  done
}
FE_PORT=$(pick_port 3100 FE); BE_PORT=$((FE_PORT+5000))
# BE_PORT 也要过占用检查（若被占则 FE/BE 同步上移）
while true; do
  if [ "$BE_PORT" = "8000" ] || ss -ltn 2>/dev/null | grep -q ":$BE_PORT "; then
    FE_PORT=$(pick_port $((FE_PORT+1)) FE); BE_PORT=$((FE_PORT+5000))
  else break; fi
done
PG_PORT=$(pick_port 15432 PG)
ok "端口: 前端=$FE_PORT 后端=$BE_PORT pg=$PG_PORT"

echo "===== 2. 校验 prod.env ====="
PROD_ENV="$DEPLOY_ROOT/secrets/prod.env"
[ -f "$PROD_ENV" ] || die "缺少 secrets/prod.env（pack.ps1 应已生成）"
MISSING=""
for k in JWT_SECRET INITIAL_ADMIN_PASSWORD DEEPSEEK_API_KEY TAVILY_API_KEY FEISHU_APP_ID FEISHU_APP_SECRET FEISHU_TOKEN_ENCRYPTION_KEY; do
  grep -q "^${k}=.\+" "$PROD_ENV" || MISSING="$MISSING $k"
done
[ -z "$MISSING" ] || die "prod.env 缺少:$MISSING"

echo "===== 3. 生成 .env ====="
PG_PWD=$(openssl rand -hex 16)
cp "$COMPOSE_DIR/.env.template" "$ENV_FILE"
# __GENERATE__ → 随机数据库密码（两处: POSTGRES_PASSWORD 与 DATABASE_URL 内）
sed -i "s|__GENERATE__|$PG_PWD|g" "$ENV_FILE"
# 逐 key 从 prod.env 填充 __FROM_PROD_ENV__
for k in JWT_SECRET INITIAL_ADMIN_PASSWORD DEEPSEEK_API_KEY TAVILY_API_KEY FEISHU_APP_ID FEISHU_APP_SECRET FEISHU_TOKEN_ENCRYPTION_KEY; do
  v=$(grep "^${k}=" "$PROD_ENV" | cut -d= -f2-)
  python3 - "$ENV_FILE" "$k" "$v" <<'EOF'
import sys, pathlib
p, k, v = sys.argv[1], sys.argv[2], sys.argv[3]
lines = pathlib.Path(p).read_text(encoding='utf-8').splitlines()
out = [f"{k}={v}" if ln.startswith(k + "=") else ln for ln in lines]
pathlib.Path(p).write_text("\n".join(out) + "\n", encoding='utf-8')
EOF
done
# 服务器 IP 与端口占位符
python3 - "$ENV_FILE" "$SERVER_IP" "$FE_PORT" "$BE_PORT" <<'EOF'
import sys, pathlib
p, ip, fe, be = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
t = pathlib.Path(p).read_text(encoding='utf-8')
t = t.replace("__SERVER_IP__", ip).replace("__FE_PORT__", fe).replace("__BE_PORT__", be)
pathlib.Path(p).write_text(t, encoding='utf-8')
EOF
ok ".env 已生成（数据库密码随机）"

echo "===== 4. 构建镜像 ====="
docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" build || {
  warn "构建失败，重试 1 次"; sleep 5; docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" build || die "构建失败"
}

echo "===== 5. 起库 + 还原数据 ====="
docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" up -d postgres redis
for i in $(seq 1 30); do
  if docker exec agent-postgres pg_isready -U agent -d rbac >/dev/null 2>&1; then break; fi
  sleep 2; [ $i = 30 ] && die "postgres 未就绪"
done
if [ -f "$DEPLOY_ROOT/data/rbac.dump" ]; then
  ok "导入数据库 dump（幂等：先清空再导入）"
  docker exec -i agent-postgres dropdb -U agent --if-exists rbac \
    && docker exec -i agent-postgres createdb -U agent rbac \
    && docker exec -i agent-postgres pg_restore -U agent -d rbac --clean --if-exists -j 2 < "$DEPLOY_ROOT/data/rbac.dump" \
    || die "pg_restore 失败"
fi

echo "===== 6. 数据库迁移 ====="
docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" run --rm migrate || die "alembic 迁移失败"

echo "===== 7. 起服务 ====="
for s in backend worker web-renderer frontend; do
  for try in 1 2 3; do
    if docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" up -d "$s" >/dev/null 2>&1; then break; fi
    warn "$s 第${try}次启动失败，5s 后重试"; sleep 5
    [ $try = 3 ] && { docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" logs --tail 50 "$s" || true; die "$s 启动失败"; }
  done
done

echo "===== 8. 健康检查 ====="
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

echo "===== 9. 清理与报告 ====="
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
```

**关键说明**（实现时逐条落实）：
- 端口选择：`pick_port` 排除 8000/82 与已监听端口；BE=FE+5000 但需再查占用（8000 排除）；PG 独立递增
- 步骤 3 用 python3 做占位符替换（避免 sed 特殊字符转义问题）
- 步骤 5 dropdb 会失败（连接中）时允许重试 1 次；dump 不存在则跳过还原（全新部署场景）
- 步骤 7 每服务重试 3 次，第三次失败打印日志尾部
- 健康检查后端用 `/health`（若实际端点不同，实现时先 `grep -rn "health" backend/app/main.py` 确认路径）
- 步骤 9 打印的 admin 密码来自 .env（由 prod.env 填充）——**注意**：服务器上 `shred prod.env` 后 admin 密码只在报告里出现一次，报告务必截图

- [ ] **Step 2: 校验脚本存在且关键函数齐全**（本地无 bash，用 grep 检查结构）

```
cd C:\01_agent_loop_pro
python -X utf8 -c "import pathlib; s=pathlib.Path(r'deploy/deploy.sh').read_text(encoding='utf-8'); assert 'pick_port' in s and '8000' in s and '82' in s; assert 'pg_restore' in s and 'alembic' in s and 'shred' in s; assert 'FE_PORT' in s and 'BE_PORT' in s; print('deploy.sh structure OK, lines:', len(s.splitlines()))"
```
Expected: `deploy.sh structure OK, lines: N`

- [ ] **Step 3: Commit**（从仓库根）

```bash
git add deploy/deploy.sh
git commit -m "feat: one-click deploy script (precheck, port selection, restore, migrate, healthcheck)"
```

---

### Task 4: 运维脚本（backup.sh / logs.sh / restart.sh / status.sh）

**Files:**
- Create: `deploy/backup.sh`
- Create: `deploy/logs.sh`
- Create: `deploy/restart.sh`
- Create: `deploy/status.sh`

**Interfaces:**
- Consumes: Task 2 的 compose（服务名）、Task 3 的 .env 位置（$DEPLOY_ROOT/.env）
- Produces: 4 个运维命令。Task 5 打包、Task 6 手册引用

- [ ] **Step 1: 写 `deploy/backup.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_DIR="$DEPLOY_ROOT/code/deploy"
ENV_FILE="$COMPOSE_DIR/.env"
STAMP=$(date +%Y%m%d_%H%M%S)
BK="$DEPLOY_ROOT/backups/$STAMP"
mkdir -p "$BK"

echo "== 1/2 数据库导出 =="
docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" up -d postgres
docker exec agent-postgres pg_dump -U agent -Fc -d rbac -f /tmp/rbac.dump
docker cp agent-postgres:/tmp/rbac.dump "$BK/rbac.dump"
docker exec agent-postgres rm -f /tmp/rbac.dump
[ -s "$BK/rbac.dump" ] || { echo "dump 为空"; exit 1; }

echo "== 2/2 文件库打包 =="
FILES_VOL=$(docker volume ls -q | grep 'agent.*files' | head -1 || true)
[ -n "$FILES_VOL" ] || { echo "未找到文件库卷"; exit 1; }
docker run --rm -v "$FILES_VOL":/data -v "$BK":/backup alpine:3.20 tar czf /backup/var.tar.gz -C /data .

echo "备份完成: $BK"
ls -lh "$BK"
```

**注意**：文件库卷名以 `docker volume ls | grep agent.*files` 探测为准（compose 项目名 `agent` + 卷 `agent-files` → 通常 `agent_agent-files`，探测更稳）。

- [ ] **Step 2: 写 `deploy/logs.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_DIR="$DEPLOY_ROOT/code/deploy"
ENV_FILE="$COMPOSE_DIR/.env"
SVC="${1:-}"
if [ -z "$SVC" ]; then
  echo "用法: bash logs.sh <backend|worker|web-renderer|frontend|postgres|redis>"
  docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" ps
  exit 0
fi
docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" logs -f --tail 200 "$SVC"
```

- [ ] **Step 3: 写 `deploy/restart.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_DIR="$DEPLOY_ROOT/code/deploy"
ENV_FILE="$COMPOSE_DIR/.env"
SVC="${1:-}"
ARGS=(-f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE")
if [ -n "$SVC" ]; then
  docker compose "${ARGS[@]}" restart "$SVC"
else
  docker compose "${ARGS[@]}" restart
fi
echo "重启完成"
```

- [ ] **Step 4: 写 `deploy/status.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_DIR="$DEPLOY_ROOT/code/deploy"
ENV_FILE="$COMPOSE_DIR/.env"
docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" ps
echo "---- 内存 ----"
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}" | head -10
echo "---- 健康 ----"
BE_URL=$(grep '^NEXT_PUBLIC_API_BASE_URL=' "$ENV_FILE" | cut -d= -f2)
curl -sf "${BE_URL}/health" && echo "后端 OK" || echo "后端异常"
```

**注意**：BE 端口从 `.env` 的 `NEXT_PUBLIC_API_BASE_URL` 提取（该值形如 `http://IP:8100`，由 deploy.sh 生成时替换）——不依赖独立的 BE_PORT 键。

- [ ] **Step 5: 结构校验**

```
cd C:\01_agent_loop_pro
python -X utf8 -c "import pathlib; [print(f, 'OK') for f in ['backup','logs','restart','status'] if pathlib.Path(f'deploy/{f}.sh').read_text(encoding='utf-8').startswith('#!/usr/bin/env bash')]"
```
Expected: `backup OK` `logs OK` `restart OK` `status OK`

- [ ] **Step 6: Commit**（从仓库根）

```bash
git add deploy/backup.sh deploy/logs.sh deploy/restart.sh deploy/status.sh
git commit -m "feat: ops scripts backup/logs/restart/status"
```

---

### Task 5: pack.ps1（本地打包脚本）

**Files:**
- Create: `deploy/pack.ps1`

**Interfaces:**
- Consumes: Task 1-4 的全部 deploy/ 文件；本地 `pg_dump`（路径 X:\database\postgresql\bin\pg_dump.exe，或 PATH 中自动探测）；本地 `.env` / `backend/.env`（汇总 prod.env）；本地 `backend/var/`（文件库全量）；本地 PostgreSQL rbac 库
- Produces: `C:\agent-deploy\agent-deploy.zip`（code/ + data/ + secrets/）。Task 6 手册按它写上传步骤

- [ ] **Step 1: 写 `deploy/pack.ps1`**

```powershell
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
$missing = @('JWT_SECRET','INITIAL_ADMIN_PASSWORD','DEEPSEEK_API_KEY','TAVILY_API_KEY','FEISHU_APP_ID','FEISHU_APP_SECRET','FEISHU_TOKEN_ENCRYPTION_KEY') | Where-Object { -not ($prodEnv -match "^$_=") }
if ($missing) { Write-Warning "prod.env 缺少: $($missing -join ', ') —— deploy.sh 会拒绝部署，请先补全 .env" }

Write-Host "== 3/4 收集代码 =="
$codeSrcs = @("backend", "frontend")
foreach ($c in $codeSrcs) {
  $dst = Join-Path $Stage "code\$c"
  $src = Join-Path $Root $c
  robocopy $src $dst /E /XD node_modules .next .venv __pycache__ .pytest_cache var .git /XF *.zip /NFL /NDL /NJH /NJS | Out-Null
}
robocopy (Join-Path $Root "deploy") (Join-Path $Stage "code\deploy") /E /NFL /NDL /NJH /NJS | Out-Null

Write-Host "== 4/4 收集文件库 + 打包 =="
$varDst = Join-Path $Stage "data\var"
robocopy (Join-Path $Root "backend\var") $varDst /E /NFL /NDL /NJH /NJS | Out-Null
Copy-Item (Join-Path $OutDir "data\rbac.dump") (Join-Path $Stage "data\rbac.dump")
Copy-Item (Join-Path $OutDir "secrets\prod.env") (Join-Path $Stage "secrets\prod.env")

Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Zip -Force
Remove-Item -LiteralPath $Stage -Force -Recurse
Write-Host ""
Write-Host "打包完成: $Zip"
Write-Host ("大小: {0:N1} MB" -f ((Get-Item $Zip).Length / 1MB))
Write-Host "上传到服务器 /opt/agent-deploy/ 后执行: bash deploy.sh"
```

**关键说明**（实现时逐条落实）：
- pg_dump 探测顺序：PATH → X:\database\postgresql\bin\pg_dump.exe
- DATABASE_URL 正则解析主机/端口/库名；PGPASSWORD 环境变量传密码
- prod.env 只取白名单 key（避免把 REDIS_URL 等开发配置带进生产）
- robocopy 排除：node_modules/.next/.venv/__pycache__/.pytest_cache/var/.git/*.zip（var 单独处理为 data/var）
- 若本地 rbac 库在 Docker 里跑（不是本机 pg），pg_dump 连接参数需调整——实现时若连接失败打印 `pg_dump: connection to server` 错误并提示检查 DATABASE_URL

- [ ] **Step 2: 实跑验证**（真实打包，验证 zip 结构与 dump 非空）

```
cd C:\01_agent_loop_pro
powershell -ExecutionPolicy Bypass -File deploy\pack.ps1
```
Expected: 输出"打包完成: C:\agent-deploy\agent-deploy.zip"，dump 非 0 字节

- [ ] **Step 3: 验证 zip 结构**

```
cd C:\agent-deploy
python -X utf8 -c "import zipfile; z=zipfile.ZipFile(r'C:\agent-deploy\agent-deploy.zip'); names=z.namelist(); need=['code/deploy/deploy.sh','code/deploy/docker-compose.yml','data/rbac.dump','secrets/prod.env']; missing=[n for n in need if not any(x.startswith(n) for x in names)]; print('zip entries:', len(names)); print('missing:', missing or 'none')"
```
Expected: `missing: none` 且 zip entries > 100

- [ ] **Step 4: Commit**（从仓库根）

```bash
git add deploy/pack.ps1
git commit -m "feat: local packaging script producing agent-deploy.zip (code + db dump + files + secrets)"
```

---

### Task 6: DEPLOY.md 傻瓜式操作手册 + 集成验证

**Files:**
- Create: `deploy/DEPLOY.md`

**Interfaces:**
- Consumes: Task 1-5 全部产物
- Produces: 最终交付手册。用户按它完成服务器部署

- [ ] **Step 1: 写 `deploy/DEPLOY.md`**（傻瓜式手册，面向非运维用户，覆盖）

```markdown
# 一键部署手册（傻瓜式）

## 你需要准备
- Xshell（SSH 终端）与 Xftp（文件传输）——连服务器用
- 服务器公网 IP：115.29.187.169（root 账号或 sudo 权限）

## 第一步：本地打包（Windows 电脑上做一次）
1. 打开 PowerShell，执行：
   cd C:\01_agent_loop_pro
   powershell -ExecutionPolicy Bypass -File deploy\pack.ps1
2. 打包完成后确认 C:\agent-deploy\agent-deploy.zip 存在

## 第二步：上传（Xftp）
1. Xftp 连接服务器（IP 115.29.187.169）
2. 进入 /opt 目录，新建文件夹 agent-deploy
3. 把 agent-deploy.zip 拖进 /opt/agent-deploy/

## 第三步：部署（Xshell）
1. Xshell 连接服务器
2. 依次执行：
   cd /opt/agent-deploy
   unzip -q agent-deploy.zip
   bash code/deploy/deploy.sh
3. 等待部署完成（约 5-15 分钟，构建镜像+还原数据）
4. 看到"部署完成"报告后，**截图保存报告**（含 admin 密码，仅出现一次）

## 第四步：使用
- 浏览器打开 http://115.29.187.169:<报告中的前端端口>
- 用 admin / <报告中的密码> 登录
- 验证：历史会话、文件库、发消息看流式回复

## 日常运维（在 /opt/agent-deploy/code/deploy 下）
| 命令 | 作用 |
|---|---|
| bash logs.sh backend | 看后端日志 |
| bash restart.sh | 重启全部服务 |
| bash backup.sh | 备份数据库+文件库（到 backups/） |
| bash status.sh | 查看容器状态与内存 |

## 常见问题
| 问题 | 处理 |
|---|---|
| 端口被占用 | 脚本自动 +1 换端口，看报告里的实际地址 |
| 部署中断 | 重新执行 bash code/deploy/deploy.sh（幂等） |
| 登录不了 | 确认报告里的 admin 密码（只显示一次） |
| 服务挂了 | bash restart.sh |
| 服务器重启后 | 全部容器自动拉起（restart: unless-stopped） |
```

- [ ] **Step 2: 集成验证**——全量检查交付物

```
cd C:\01_agent_loop_pro
python -X utf8 -c "
import pathlib
files = ['deploy/Dockerfile.backend','deploy/Dockerfile.frontend','deploy/docker-compose.yml','deploy/.env.template','deploy/deploy.sh','deploy/backup.sh','deploy/logs.sh','deploy/restart.sh','deploy/status.sh','deploy/pack.ps1','deploy/DEPLOY.md','deploy/.dockerignore']
missing = [f for f in files if not pathlib.Path(f).exists()]
assert not missing, missing
print('全部交付物存在:', len(files))
# 关键交叉引用一致性
c = pathlib.Path('deploy/docker-compose.yml').read_text(encoding='utf-8')
d = pathlib.Path('deploy/deploy.sh').read_text(encoding='utf-8')
assert 'postgres:18' in c and 'agent-net' in c
assert 'pick_port' in d and 'FE_PORT' in d and 'pg_restore' in d and 'alembic' in d
print('交叉引用 OK')
"
```

- [ ] **Step 3: pack.ps1 重新实跑**（确认 Task 5 之后仍可打包）并验证 zip 内 DEPLOY.md 存在

```
cd C:\01_agent_loop_pro
powershell -ExecutionPolicy Bypass -File deploy\pack.ps1
python -X utf8 -c "import zipfile; z=zipfile.ZipFile(r'C:\agent-deploy\agent-deploy.zip'); print('DEPLOY.md in zip:', any('DEPLOY.md' in n for n in z.namelist()))"
```
Expected: `DEPLOY.md in zip: True`

- [ ] **Step 4: Commit**（从仓库根）

```bash
git add deploy/DEPLOY.md
git commit -m "docs: foolproof deployment manual"
```

---

### Task 7: 集成验证（全量交付物检查 + 服务器执行指引）

**Files:**
- Verify only

- [ ] **Step 1: 交付物完整性与一致性终检**（同 Task 6 Step 2 的检查脚本再跑一遍 + 新增约束核对）

```
cd C:\01_agent_loop_pro
python -X utf8 -c "
import pathlib, re
s = pathlib.Path('deploy/deploy.sh').read_text(encoding='utf-8')
# 硬约束: 8000/82 排除、内存上限、无明文密钥
assert '\"8000\"' in s and '\"82\"' in s
c = pathlib.Path('deploy/docker-compose.yml').read_text(encoding='utf-8')
for lim in ['512m','128m','768m','256m','384m']: assert lim in c, lim
assert 'restart: unless-stopped' in c
assert 'JWT_SECRET' not in c  # 密钥不进 compose 明文
print('终检 OK')
"
```

- [ ] **Step 2: 服务器执行指引核对**——逐条确认手册步骤与脚本行为一致（人工核对 DEPLOY.md 与 deploy.sh 的端口逻辑/幂等性/报告输出）

- [ ] **Step 3: 汇报**——无提交；输出交付清单 + 服务器操作步骤摘要 + 验证结果
