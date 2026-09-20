# 远端 Ubuntu 一键部署（Docker Compose 容器化）— 设计文档

日期：2026-08-06
状态：已确认

## 背景与目标

将本系统（前端 Next.js + 后端 FastAPI + agent_worker + web_renderer + PostgreSQL + Redis）部署到远端 Ubuntu 服务器。用户使用 Xshell（SSH）+ Xftp（文件传输），要求"傻瓜式"操作：**压缩包上传 → 解压 → 跑一个脚本**完成部署。

## 服务器环境（已核实）

| 项 | 值 |
|---|---|
| 系统 | Ubuntu 24 |
| 面板 | 宝塔 Linux 面板企业版 v11.8.0（Docker 已装，0 个网站站点） |
| 规格 | 2 核 4G（可用 ~3.4G，系统占用 27%） |
| 磁盘 | 剩余 ~47.9GB |
| 公网 IP | 115.29.187.169 |
| 现有服务 | 业务网站在 Docker 容器内占用业务端口；宝塔有 2 个数据库（MySQL 系）；宝塔 Nginx 已装未建站点 |
| 硬约束 | **8000 和 82 端口必须避开**；不碰宝塔 Nginx/MySQL/业务容器 |

## 架构

### 容器拓扑

```
Docker 网络: agent-net（独立，与业务容器完全隔离）

┌───────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐
│ postgres  │   │  redis    │   │  backend  │   │ web-render│
│ :5432     │   │  :6379    │   │  :8000    │   │  :9001    │
│ (数据卷)   │   │ (数据卷)   │   │ uvicorn   │   │ playwright│
└─────┬─────┘   └─────┬─────┘   └─────┬─────┘   └───────────┘
      │               │              │
┌─────┴───────────────┴───────┬──────┴───────┐
│        agent_worker         │   frontend   │  容器内互连用容器名
│        (同镜像,其他command)  │  next start  │
└─────────────────────────────┴──────┬───────┘
                                     │
宿主端口映射（自动避开占用）:
· http://115.29.187.169:3100 → 前端
· http://115.29.187.169:8100 → 后端 API（SSE 直通无代理，无缓冲问题）
· 15432 → Postgres（仅运维备份临时用）
· Redis/worker/web-renderer 不对外暴露（容器内网）
```

### 容器清单

| 容器 | 镜像 | 内存上限 | 说明 |
|---|---|---|---|
| postgres | **postgres:18** | 512M | 数据卷 agent-pgdata。**版本必须 ≥18**：本地 PostgreSQL 18.4 的 pg_dump 导出的 dump 只能导入版本 ≥18 的服务器（pg_restore 要求 dump 版本 ≤ 服务器版本） |
| redis | redis:7 | 128M | 数据卷 agent-redisdata；跨进程事件桥 |
| backend | 自建 | 768M | uvicorn app.main:app :8000 |
| agent_worker | 自建（同 backend 镜像） | 256M | `python -m app.workers.agent_worker`，WORKER_CONCURRENCY=1 |
| web-renderer | 自建 | 384M | playwright chromium headless，WEB_RENDERER_HEADLESS=true |
| frontend | 自建 | 256M | `next start` :3000，生产构建产物 |
| (一次性) migrate | 自建 backend 镜像 | — | alembic upgrade head + pg_restore |

### 端口映射与冲突规避

| 宿主端口 | 容器端口 | 用途 |
|---|---|---|
| 3100（冲突自动+1递增） | 3000 | 前端 |
| 8100（冲突自动+1递增） | 8000 | 后端 API |
| 15432（冲突自动+1递增） | 5432 | Postgres 运维备份 |

- **8000、82 视为已占用**，脚本选择端口时显式排除
- 脚本 `ss -ltn` 检测全部已监听端口，映射端口冲突 → 自动 +1 递增重选，不报错退出
- 前端 3100 与后端 8100 必须同选一轮递增（相差 5000 的映射关系保持，简化配置生成）

### 互连地址（容器内）

- `DATABASE_URL=postgresql+asyncpg://agent:<pwd>@postgres:5432/rbac`
- `REDIS_URL=redis://redis:6379/0`
- `WEB_RENDERER_URL=http://web-renderer:9001`
- `NEXT_PUBLIC_API_BASE_URL=http://<服务器IP>:<后端宿主端口>`（浏览器侧访问，非容器内）

## 数据迁移（全量）

### 本地打包（pack.ps1，Windows 一条命令）

```
产出 C:\agent-deploy\agent-deploy.zip
├── code/
│   ├── backend/            # 排除 node_modules/.venv/__pycache__/var
│   ├── frontend/           # 排除 node_modules/.next
│   ├── docker-compose.yml
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   └── deploy/             # deploy.sh + backup.sh + logs.sh + restart.sh + .env.prod.template
├── data/
│   ├── rbac.dump           # pg_dump -Fc 本地 rbac 库（用户/历史/摘要/配置表）
│   └── var/                # 文件库全量（蓝图+规范文档+案例库+头像+附件）
└── secrets/
    └── prod.env            # 汇总本地 .env + backend/.env 的部署配置
```

- pg_dump 命令（本地 Windows 执行）：`pg_dump -Fc -d rbac -f rbac.dump`（连接参数从 .env 的 DATABASE_URL 解析；本地 docker/安装版 pg 均可）
- pack.ps1 幂等：重复运行覆盖 zip；打包前校验 rbac.dump 生成成功（非 0 字节）
- 敏感文件（.env 相关）打包后立即删除临时副本

### 服务器还原（deploy.sh 内）

1. postgres 容器 healthy 后：`pg_restore -d rbac --clean --if-exists rbac.dump`（先 drop 再导，幂等可重跑）
2. `alembic upgrade head`（数据库可能比代码旧）
3. var/ 文件库 → 挂载数据卷 `agent-files:/app/var`（容器内路径与后端一致）
4. admin 账号、历史会话、蓝图蒸馏摘要、workflow 配置随库迁移全部保留

## 配置与安全

### prod.env（随包上传，缺失必填项脚本红字列出并退出）

```env
# 必填（来自本地）
DATABASE_URL_BASE=host:port/dbname     # 本地连接信息（仅打包时用）
JWT_SECRET=
INITIAL_ADMIN_PASSWORD=
DEEPSEEK_API_KEY=
TAVILY_API_KEY=
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_TOKEN_ENCRYPTION_KEY=

# 部署专用（脚本自动生成）
COOKIE_SECURE=false        # IP+HTTP 必须 false，否则登录 cookie 不生效
CORS_ORIGINS=http://115.29.187.169:3100
NEXT_PUBLIC_API_BASE_URL=http://115.29.187.169:8100
POSTGRES_PASSWORD=<随机生成>
```

### 安全措施

- 密钥只经容器环境变量注入，**不写入 docker-compose.yml 明文**（.env 文件由脚本生成，docker compose 自动读取）
- **不进入镜像层**（构建时不 COPY prod.env）
- 部署完成后 `shred -u prod.env`（密钥不留服务器磁盘）；打包机本地临时副本删除
- Postgres 仅 15432 端口运维时临时映射（backup.sh 时才开），默认不映射
- 数据库密码未提供时随机生成（openssl rand -hex 16）
- 迁移后提示用户轮换 JWT_SECRET（可选，不强制——轮换会使旧 token 失效）

## 一键部署流程（deploy.sh）

```
① 预检    docker/compose 版本、内存、磁盘、端口占用（3100/8100/15432 被占自动+1，8000/82 显式排除）
② 校验    prod.env 必填项（缺 key 红字列出并退出）
③ 生成    .env（端口/CORS/NEXT_PUBLIC_API_BASE_URL/COOKIE_SECURE=false 自动填充）
④ 构建    docker compose build（基础镜像从 Docker Hub 拉取；构建失败重试 1 次）
⑤ 起库    postgres → healthcheck → pg_restore rbac.dump
⑥ 迁移    alembic upgrade head（migrate 一次性容器）
⑦ 起服务  redis → backend → worker → web-renderer → frontend（失败自动重试 3 次，间隔 5s）
⑧ 健康    curl 后端 /health + 前端 / → 全部 200 才报"部署成功"
⑨ 清理    shred prod.env → 打印部署报告（访问地址/admin 账号/运维命令）
```

- **幂等可重跑**：任何一步失败，修复后重新 `bash deploy.sh`（pg_restore 先 drop 再导，docker compose up 增量）
- 每步输出 ✅/❌ 状态 + 失败原因 + 修复建议
- 所有容器 `restart: unless-stopped`（服务器重启自动拉起）

## 运维配套脚本（随包 deploy/）

| 脚本 | 功能 |
|---|---|
| backup.sh | pg_dump 导出 + 打包 var/ → /opt/agent-deploy/backups/（带时间戳） |
| logs.sh | `docker compose logs -f <service>` 按服务名看日志 |
| restart.sh | 重启全部服务（或单服务） |
| status.sh | 容器状态 + 端口监听 + 健康检查汇总 |

## 资源约束（2核4G）

- 实测内存：总 3.4G、现有服务已用 ~1G、余量 ~2.4G
- **全部容器 cgroup 硬上限合计 ~2.3G**（512+128+768+256+384+256）——物理上不挤占现有服务（1G + 2.3G = 3.3G < 3.4G）
- WORKER_CONCURRENCY=1（单 worker 串行，内存最稳）
- WEB_RENDERER_HEADLESS=true
- **swap 检查**：预检发现无 swap → 提示并自动创建 2G swap（`fallocate` + `mkswap` + `swapon` + fstab 持久化；宝塔面板"软件商店/系统"或手动亦可）——防 OOM killer 波及现有服务
- web_renderer 启动失败不影响其他服务（日志提示，渲染工具降级）
- 现有服务（~1G）与我们的容器上限 2.3G 并行运行，峰值总占用 < 3.4G

## 错误处理

| 场景 | 处理 |
|---|---|
| 端口被占 | 自动 +1 递增重选（8000/82 显式排除） |
| prod.env 缺 key | 红字列出缺失项，退出码 1 |
| Docker Hub 拉取失败 | 重试 1 次；仍失败提示检查网络 |
| pg_restore 失败 | 报错退出，重跑 deploy.sh 幂等恢复 |
| alembic 迁移失败 | 报错退出（迁移是重头戏，不静默跳过） |
| 服务启动失败 | 重试 3 次 × 5s；仍失败打印该容器日志尾部 |
| web_renderer 失败 | 仅告警，不阻断部署成功 |
| 磁盘不足 | 预检阶段检查剩余空间 ≥ 10GB |

## 测试策略

- **语法/结构校验**（本地）：
  - `docker compose config`（compose 文件合法性）
  - `bash -n deploy.sh` / shellcheck（deploy.sh 语法）
  - pack.ps1 本地实跑一次，验证 zip 结构与 dump 非空
- **冒烟（如本地有 Docker Desktop）**：起 postgres + migrate 容器验证 pg_restore/alembic 流程
- **服务器验证清单**（用户执行后）：
  - http://115.29.187.169:3100 打开登录页
  - admin 登录成功（数据迁移验证）
  - 历史会话可见、蓝图摘要存在（workflow_doc_summaries 表非空）
  - 文件库文件可读（蓝图文件在）
  - 发一条消息 → SSE 流式回复正常
  - 端口确认：ss -ltn 无 8000/82 冲突、业务容器无影响

## 范围边界

**本期做**：Dockerfile×2、docker-compose.yml、deploy.sh、pack.ps1、backup/logs/restart/status.sh、部署文档（傻瓜式操作手册）
**不做**：域名/HTTPS（用户选 IP+端口）、宝塔站点反代、CI/CD 自动化、多节点扩容、监控告警集成、密钥管理系统（Vault 等）
