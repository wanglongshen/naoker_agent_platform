# DeepSeek Harness 平台化改造设计（2026-09-07）

- 状态：设计定稿（已与用户分节确认 1-4 节）
- 结论：以 DeepSeek Harness（`@deepseek-ai/dsh` / `deepseek-ai/deepseek-harness`，MIT）为 Agent 运行时，保留现有「企业智助」平台企业层（Next.js + AntD / FastAPI / PostgreSQL / RBAC / 蓝图引擎 / 计费），三阶段交付。
- 配套素材：行业知识库素材已完成第一批采集（`var/kb_industry/`，601 篇正文 / 18.7M 字；核心白名单 226 篇方法论 ≈7,816 页，见 `manifest\manifest-core.json`）。

---

## 1. 背景与现状盘点

### 1.1 目标

当前平台（企业智助）为一套自研 Agent 平台：FastAPI + Next.js 16 + AntD 6 + PostgreSQL，含 RBAC（12 权限）、蓝图引擎（广告营销方案 8 模块结构）、平台登录（抖音/小红书 Cookie 体系，Playwright）、飞书文档、文件库、积点计费、LangGraph 编排（`settings.langgraph_enabled` 门控）。

简历目标句「**基于 DeepSeekHarness 源码二次开发**」当前零基础——现有 Agent Loop 为自研 Python 实现，与 DSH 无代码关系。本次改造的目的：**以 DeepSeek Harness 为主线（runtime + 插件生态），把平台升级为"基于 DeepSeekHarness 源码二次开发"的广告营销 AI Agent 平台**，同时完整继承 DSH 插件生态（皮肤/工具/MCP/技能）。

### 1.2 现状 vs 目标（证据盘点）

| 简历声称 | 现状 | 证据 |
|---|---|---|
| FastAPI 后端 + Next.js/AntD 前端 | ✅ 存在 | `backend/app`、`frontend/src/app`；README.md |
| RBAC 多角色权限 | ✅ 成熟 | 12 权限 + super_admin 不可变 + 审计；docs/superpowers/specs/2026-07-21-rbac-system-design.md、2026-08-04-enterprise-super-admin-model-design.md |
| LangGraph 任务流 | ✅ 已有（门控） | `requirements.txt` langgraph；plan 2026-08-27-langgraph-orchestration.md |
| 自动生成广告营销方案 | ✅ 已有 | 蓝图引擎（8 模块）；plan 2026-08-06-plan-generation-chain.md |
| Docker 部署 | ✅ 已有脚本 | `deploy/`（compose + Dockerfile.backend/frontend） |
| **基于 DeepSeekHarness 源码二次开发** | ❌ **零（本改造目标）** | 全仓无 DSH 引用；DSH 为独立官方仓库 |
| **RAG 私有资料检索** | ❌ **缺** | 全仓无 embedding/向量库（仅 langchain 实验报告，结论不替换生产实现） |
| 适配 DSH 插件 | ❌ **缺** | 机制需随接入引入 |

### 1.3 DSH 事实（决定设计形态）

- 官方仓库：github.com/deepseek-ai/deepseek-harness（MIT；`docs/`、`apps/cli`+`apps/web`、48 个 `packages/*`、`python/sdk`）。
- 运行形态：`dsh --profile <name>`；`dsh web` 启动浏览器 UI（`--host`、`--port 0=OS 随机`、`--no-open`、`--trusted-host <authority>` 为反代护栏）；`dsh --profile headless "task"` 一轮任务即退；Python SDK `deepseek-harness-sdk`（JSON-RPC stdio 子进程驱动，`dsh_home` 必须显式指定且绝不发现 `~/.dsh`）。
- 配置体系：`$DSH_HOME` 目录 = profile（`profiles/<name>/`）+ 两层 `cordis.patch.yml`（home 层 + profile 层，后写覆盖；皮肤互斥等均以此实现）。
- 插件体系：「一切皆插件」；`dsh plugin --profile <name> add <dir 或 file:...>` 安装外部插件；客户端插件（如皮肤）经 bundle `/plugins/<pkg>/client.js` 进入 Web UI；技能发现：`<dshHome>/skills` rank 400 自动收录（docs/subsystems/skills.md）。
- 开发者预览（`0.1.1-rc.2`），官方明示兼容性破坏——设计以「锁版本 vendored + 插件式二开」应对。
- Web UI 无 `X-Frame-Options`/`frame-ancestors` 限制（对安装包源码 grep 实证）→ iframe 嵌入可行；同源反代无 cookie 跨域问题。

---

## 2. 总体架构与分期

### 2.1 分层

```
┌─ 平台门户 Next.js + AntD（现有，保留）──────────────────────────┐
│ 登录 / RBAC / 文件库 / 方案中心 / 计费 / 审计 /（二期）知识库管理 /（三期）任务链监控 │
├─ 平台服务 FastAPI（现有，保留；新增 dsh 域）───────────────────┤
│ + DshInstanceManager：每用户实例生命周期（启动/复用/空闲回收/端口槽位）        │
│ + DshAdapter：上下文注入 + SDK/headless 任务调用 + 会话审计回流              │
│ +（二期）RAG 服务：采集→解析→切分→embedding→pgvector→检索 API             │
│ +（三期）LangGraph 任务链：调研→方案→投流→交付→计费 + 计费打通              │
├─ DSH 运行时（vendored @deepseek-ai/deepseek-harness，pinned SHA）──┤
│ 每用户一台：DSH_HOME=var/dsh/<uid>/（web 交互面 + sdk/headless 后台面）     │
│ 平台适配层（全部以插件落地，不改 DSH 本体）：                                 │
│   @naoker/dsh-platform-connector（server 插件：平台工具注入 + 审计钩子）   │
│   skills 注入：<home>/skills/*.SKILL.md（知识检索/平台操作指导）              │
│ DSH 插件生态原样可用：皮肤/官方社区插件/MCP/skills ✔                        │
└──────────────────────────────────────────────────────────────┘
共享底座：PostgreSQL（平台库）· var/dsh/<uid>/（DSH SQLite 会话+配置+插件）
          · 对象存储（现有 var/）·（二期）pgvector 向量表
```

### 2.2 分期

| 期 | 范围 | 验收线（可测量） |
|---|---|---|
| 一期 | DSH 源码入仓 + 构建 + 每用户实例托管 + 登录桥 + Web UI 嵌入 + 皮肤插件验证 + 平台工具注入 + 会话审计回流 | 见 4.8 |
| 二期 | RAG：素材管线（采集→解析→切分→pgvector）→ 检索 API → DSH `knowledge_search` 工具 + skill → 知识库管理页 | 黄金集 100 问 recall@5 ≥90%；端到端引用正确；管理页全链路；P95 ≤500ms |
| 三期 | LangGraph 任务链 + 计费打通 + Docker 一键部署 + 全量验收 | 任务链 P95 交付 ≤10 分钟；回测指标保持；`docker compose up -d` 一套跑通 |

### 2.3 全局风险与对策（三阶段共用）

1. **DSH developer preview 兼容性破坏** → vendored + pinned SHA；升级 SOP：`scripts/sync-dsh-vendor.ps1`（拉指定 tag → 校验 → 更新 `deepseek-harness/.dsh-vendor.json`）→ 回归清单（一期验收 6 条 + 冒烟）→ bump。二开只做插件，上游升级无需改我们代码。
2. **皮肤许可（鲸鱼娘 CC BY-NC-SA 非商用）** → 插件机制商用无碍；商业交付仅内部演示皮肤或定制自有皮肤（许可预留）。
3. **每用户一个 Node 进程**（单机小团队可承受）→ 空闲 10 分钟回收；实例注册表持久化 + 起停幂等。
4. **DSH 无多租户鉴权** → 平台反代是唯一边界（`/dsh-proxy/<uid>` 强制平台登录 + 属主校验，非属主 404，与现有跨用户策略一致）。

---

## 3. 一期：DSH 接入

### 3.1 仓库与构建

- `deepseek-harness/`：上游完整快照（git subtree --squash，pinned = v0.1.1-rc.2 对应 commit；`deepseek-harness/.dsh-vendor.json` 记录 SHA/日期/来源）；**禁止任何手工改动**（升级只走协议化脚本）。
- `dsh-platform/`：新 pnpm workspace（我方代码）：
  - `packages/server-connector` → `@naoker/dsh-platform-connector`（Cordis server 插件：平台工具、审计/用量钩子）；
  - `skills-template/`：SKILL.md 源模板（实例创建时拷入 `<home>/skills/`，自动发现 rank 400）；
  - `build/`：tsdown 构建产物（对齐皮肤仓库结构：`src/` + `lib/` + `cordis.patch.yml` 片段；插件开发规范参照 DSH `packages/extensions` 与 dsh-web-ui 脚手架）。
- 构建：`deepseek-harness` 内 `pnpm install && pnpm run build`（上游 README run-from-source）；开发机复用已装同版本全局 `dsh`（`DSH_INSTANCE_MODE=dev_bin`），容器/生产使用 vendored 构建（三期入 compose）。
- 第三方插件：`dsh plugin --profile web add <目录/file:...>` 即装即生效（官方支持路径 spec / file: 形式）；鲸鱼娘三件套为本地验证用例（`dsh-deep-whale/`）。

### 3.2 每用户实例生命周期（`backend/app/services/dsh/`）

| 组件 | 行为 |
|---|---|
| `DshInstanceManager` | asyncio 单例。首次访问启动：`dsh --profile web --host 127.0.0.1 --port <槽位> --no-open --trusted-host <平台权威域>`；槽位 = 用户哈希映射 3100-3399 落库（`dsh_instances.port`，冲突重试）；健康检查通过才返回可用；**空闲 10 分钟优雅关停**（SIGTERM→30s→kill）；再访问重启且**会话保留**（会话在 home SQLite）。启动加幂等锁（DB 行锁或应用内 asyncio 锁）避免并发双起 |
| 实例初始化 | 创建 `var/dsh/<uid>/` home；写 `profiles/web/cordis.patch.yml`：`- id: naoker-platform-connector` 配置行（platformBase、userId、instanceToken）；拷贝 skills 清单；写入平台 LLM 密钥环境（`DEEPSEEK_API_KEY` 由平台 .env 透传，不进 DSH 凭证库、不落地用户可见处） |
| 平台密钥流转 | instanceToken：FastAPI 签发短 TTL 内部 token，随请求注入工具调用（connector 每次调用携带），平台侧双端校验 |

### 3.3 反代与登录桥

- 路径：`/dsh-proxy/<uid>/<rest>`（FastAPI 路由）→ 内部直连 `127.0.0.1:<port>`，改写 Host；WS 走 uvicorn WebSocket trampoline（DSH 下行用 WS，证据：上游 websocket-downlink 设计笔记）。
- 鉴权：仅平台登录态（现有 JWT HttpOnly cookie）；服务端强制 `request.user.id == uid`；非属主 404。生产环境该段代理可由 nginx 承担（三期 compose，逻辑等价：proxy_buffering off 同现有 SSE 指南）。
- 浏览器信任：实例以 `--trusted-host <平台权威域>` 启动（CLI 帮助原文：供 `/api` browser-trust 栅栏接受的外部 authority）；iframe 同源嵌入，无 XFO 限制（实证）。

### 3.4 会话审计回流（新增 2 表，字段可溯源）

| 表 | 字段 | 来源 |
|---|---|---|
| `dsh_instances` | user_id(PK)、port、state、pid、last_active_at、error_hint、created_at、updated_at | 实例管理器自身状态 |
| `dsh_sessions` | user_id、dsh_session_id、title、turn_count、last_activity_at、synced_at、created_at | DSH 会话库元数据（**字段名以 vendored 后实测 schema 为准**——一期任务预置 inspect 脚本，禁止臆造字段） |
- 同步：轮询任务（每 60s 活跃实例 + 审计页按需触发）；只同步元数据，正文留在 DSH home（**单权威存储**：会话内容唯一权威 = DSH SQLite；平台仅审计索引）。
- 审计视图：`/agent/audit` 增加「DSH 会话」标签（super_admin 全场、用户仅己、只读）。

### 3.5 平台工具连接器（一期 3 个工具）

| 工具 | 平台侧对接 | 说明 |
|---|---|---|
| `platform_search_files` | `GET /api/files`（关键词/类型过滤） | 返回 id/标题/类型 |
| `platform_read_file` | 文件详情 + 文本提取 | file_id → Markdown |
| `platform_get_docs` | 飞书文档索引（现有 feishu service） | 文档列表/内容（受授权约束） |

调用携带 instanceToken（FastAPI 校验属主）；工具注册进 DSH tools 注册表（模型可调用），实现按 DSH `packages/extensions` 插件范式。

### 3.6 前端

- `/agent`：顶部状态条（实例状态/重建按钮）+ 100% 高 iframe `/dsh-proxy/<uid>/`；皮肤切换在 DSH「设置→皮肤管理」内完成；全宽布局（遵守现有无 1100px 居中规范）。
- 旧自研对话 UI 保留：`/agent/legacy`（回滚备胎），现有 SSE 事件管线不迁移不删除（决策记录，见 6.7）。
- 移动端：iframe 自适应（DSH 皮肤已适配窄宽布局）。

### 3.7 一期明确不做（防膨胀）

不改 DSH 本体、不做计费、不做 LangGraph 任务链、不做 RAG、不做 Docker 化（三期）、不新增 RBAC 权限码（复用现有 12 权限与审计准绳）、不把 DSH 会话正文复制进平台库、不做旧 UI 清理。

### 3.8 一期验收清单

1. 新用户注册→登录→/agent→实例自动启动→DSH Web UI 完整渲染、皮肤生效→发消息（deepseek-official / deepseek-v4-flash-vision-exp）→流式回复。
2. 对话内调用文件工具读已上传附件→内容准确出现。
3. 审计页出现该会话（super_admin 可见、他人不可见）。
4. 用户 B 直接访问 `/api/dsh-proxy/<A>/**` → 404。
5. 空闲回收→实例重启→会话保留。
6. 手册：任意社区 DSH 插件 `dsh plugin add` 安装到该实例 profile 即生效（以鲸鱼娘为验证样例）。

---

## 4. 二期：RAG 行业知识库

### 4.1 定位与口径

- 只做**平台级「广告营销行业知识库」**：管理员公开源头采集 → 切分 → 向量化 → DSH 检索工具使用 → 命中率 ≥90% 量化验收。不做用户私有库（一期文件工具已覆盖私域检索 80% 需求）；检索对全部登录用户开放（与文件工具同策略），管理页仅 super_admin（复用现有门，**不新增权限码**）。

### 4.2 管线五段

```
采集(白名单+人工审批) → 解析(复用现有抽取) → 标题感知切分 → embedding → pgvector → 检索API → DSH 工具
```

| 段 | 设计 | 依据 |
|---|---|---|
| 采集 | `backend/app/services/rag/collectors.py`；源白名单 yaml，默认全关；每条源含 source_url/publisher/license_note，管理员逐源审批启用；合规：只采公开发行内容、内部私有库使用不公开再分发 | 沿用 doc-source-validation（2026-08-04）源头校验思路 |
| 解析 | 网页→Markdown（trafilatura）；PDF/DOCX/XLSX 复用现有 `extract_file_text` 管线（universal-file-reader 已有解析器） | 现有代码 |
| 切分 | Markdown 标题栈为 section_path；段落优先 512 字符/64 重叠；策略以黄金集实验标定 | 黄金测试集定参数，不拍脑袋 |
| Embedding | 默认 bge-small-zh-v1.5（sentence-transformers，512 维，CPU 可跑）；端点/模型可配置（预留 SWA/硅基流动一行切换） | 私有化零成本单机 |
| 向量库 | **pgvector**（与业务库同库同管）；dev 用 `pgvector/pgvector:pg16` 容器（5433，不动本机现有 PG）；生产 compose 统一同一镜像（三期） | PG16 已是平台数据库 |

### 4.3 检索（90% 达成路径，阶梯触发）

- 主路：向量召回 20（HNSW cos）→ 无重排 → 直接供模型。
- 阶梯②：bge-reranker-base 重排（若 recall@5 < 90%）；③：BM25/pg_trgm 混合 + RRF；④：切分参数调优。每级触发条件明确，不预堆料。

### 4.4 素材源现状与判定（本次已实采/实测）

| 源 | 判定 | 数据 |
|---|---|---|
| 抖音电商官方学习中心 | ✅ 已采集 + 白名单 | 601 篇正文 18.7M 字；**核心 226 篇方法论 ≈7,816 页**（`var/kb_industry/manifest/manifest-core.json` 二期采集器直接消费） |
| 小红书种草学/电商学习中心 | ⏸ 视频为主无正文；待二期视频转写或人工通道 | SPA（formula），实测无文本 |
| 艾瑞公开报告 | ⏸ 免费版为图片型扫描 PDF，文本提取性低；待 OCR/元数据通道 | 实测定性 |
| 巨量算数 | ⏸ SPA + secsdk/webmssdk 反爬；待 playwright 或人工导出 | 实测定性 |

二期入库优先核心白名单；规则类（254 篇）冷存按需（检索命中引用原文 URL）。素材库为 `var/kb_industry/`（gitignore；不提交）。

### 4.5 数据模型（3 新表）

| 表 | 字段 | 来源 |
|---|---|---|
| `rag_documents` | id、title、doc_type(methodology/report/article)、source_url、publisher、license_note、file_key、sha256、status(pending/ready/disabled)、chunk_count、created_by、created_at、updated_at | 采集器输出+现有文件模型（file_key/sha256 同构） |
| `rag_chunks` | id、doc_id(FK)、chunk_index、section_path、content、embedding vector(512)、created_at | 切分输出+bge 维度 |
| `rag_eval_set` | id、query、expected_doc_ids(text[])、approved_at、created_by | 黄金测试集（评测工具产物） |
索引：HNSW(cosine)；迁移含 `CREATE EXTENSION IF NOT EXISTS vector`。

### 4.6 DSH 接入与前端

- connector 新增第 4 工具 `knowledge_search(query, top_k)` → `POST /api/rag/search`（instanceToken+user）→ 返回 chunks（含 title/section_path/source_url）。
- skill：`knowledge-search/SKILL.md`（拷贝 `<home>/skills/`，rank 400 自动发现）：“涉及行业方法论/规则/案例先检索，不凭记忆编造”。
- 管理页 `/knowledge`（super_admin）：文档列表（标题/来源/状态/分块数）、采集任务（源白名单/审批开关/手动采集）、预览/禁用——复用表格+抽屉既有组件（文件管理页即样）。

### 4.7 二期验收

1. 黄金集 100 问（LLM 生成 + 10 条人工复核）`scripts/rag_eval.py`：**recall@5 ≥90%**；
2. 端到端：DSH 中提问行业方法论 → 回答含知识库内容并给 source；
3. 管理页真实完成「采集→审批→入库→禁用」链；
4. 检索 P95 ≤500ms（本地单机）。

---

## 5. 三期：LangGraph 任务链 + 计费 + Docker 一键部署

### 5.1 职责边界

**LangGraph = 编排层（生产线）；DSH = 执行层（子任务 agent 循环/工具/流式）。** 单次「生成营销方案」= 平台级任务链状态机；DSH 以 SDK 无头模式承担子任务（复用一期每用户 home）。

```
collect_input → research_agenda(LLM+knowledge_search 定调研清单)
→ run_research[并行 N 个 DSH 子任务: 行业知识/竞品/投流方法论]
→ draft_plan(DSH 子任务, 8 模块蓝图驱动) → review_gate(现有模块清单校验器复用)
→ polish → deliver(落库 generation + 飞书文档 + 下载) → bill(usage→积点, 复用 points)
```

### 5.2 计费（诚实双口径）

- 首选：DSH 子任务 RunResult.events 含 usage → 提取 token 数 → 现有 points 记账（折算积点走配置项）。
- 若 vendored 实测无 usage 事件 → 任务级固定积点/字数档粗粒度计费（配置表先行）。实施期择一，不双跑。

### 5.3 Docker 一键部署（`deploy/` 升级，非重造）

- compose 服务：`postgres` → **pgvector/pgvector:pg16**（二期 dev 5433/生产统一）、`backend`（multi-stage：stage1 pnpm 构建 vendored DSH；stage2 Python runtime 内置 node+dsh bin；每用户实例与 API 同容器）、`worker`、`frontend`；volumes：var/、var/dsh/、pgdata。
- 一键：`docker compose up -d --build`（migrate/seed 自动化入口）+ 现有 status.sh/logs.sh/upgrade.sh 兼容；verify-zip.ps1 打包管线沿用。
- DSH 升级 SOP 见 2.3-1。

### 5.4 前端

- **方案中心** `/generations`：发布任务表单（品牌/产品/预算/平台/附件/蓝图）+ 任务链详情卡（阶段时间线复用 process-timeline/step 组件 + 产出预览、下载、飞书链接）。
- `/agent` 保持一期 DSH 面（自由对话）；两入口职责分派明确。

### 5.5 全量验收（逐句对齐简历）

| 简历句 | 验收 |
|---|---|
| 1-2 天→10 分钟 | 任务链真实计时 P95 ≤10 分钟（预期 3-8 分钟：并行调研+长文），日志/指标留证 |
| 检索 ≥90% | 二期 recall@5 ≥90% 闸门保持 + 终稿质检：8 模块完整性校验 + 黄金方案样例人工比对 10 份（要点覆盖 ≥90%） |
| RBAC | 现有 77 后端 + 65 前端测试全回归 + 新增边界用例（proxy 属主 404、审计可见性、任务链数据隔离） |
| 前端 Next.js+AntD/后端 FastAPI | 100% 保留，只增不换 |
| Docker 一键部署 | 全新服务器一条命令 → 全功能可用（部署手册 + verify 脚本 + upgrade.sh 兼容） |
| 适配 DSH 插件 | 手工冒烟 + platform smoke（皮肤 bundle 引用检查，复用现有 playwright/web-renderer 设施）+ 外部插件安装手册 |

### 5.6 决策记录

- 自研 SSE/事件管线**不退役**（legacy 标记）：旧 UI `/agent/legacy` 回滚备胎 + 审计语义保留；代价 = 维护两份，显式接受（回滚安全 > 精简）。
- 平台库不迁移 DSH 会话正文：**每个会话只有一个权威存储**（DSH home SQLite），避免双写失一致（同架构记忆 #1 精神）。

---

## 6. 引用清单（证据来源）

- DSH 仓库/文档：github.com/deepseek-ai/deepseek-harness（README.zh.md、docs/api-gateway.md、docs/subsystems/skills.md、python/sdk/README.md、apps/web/tests/*.e2e.ts）
- DSH CLI 实证：本机 `dsh --version`=0.1.1-rc.2；`dsh --help`/`dsh --profile web --help`（--host/--port/--no-open/--trusted-host）；`~/.dsh` 结构、`profiles/web/cordis.patch.yml`（皮肤双层 patch 实证）
- 皮肤参考：dsh-deep-whale README（`@dsh-external/*` 包、`dsh plugin add`、patch 互斥）——许可 CC BY-NC-SA
- 平台现状：README.md（企业智助）、docs/superpowers/specs/2026-07-21-rbac-system-design.md、2026-08-06-plan-generation-chain-design.md、2026-08-01-feishu-docs-integration-design.md、2026-08-06-remote-deploy-design.md、2026-08-27-langgraph-orchestration-design.md
- 素材：var/kb_industry/README.md 与 manifest{,-core}.json（真实采集记录：601 篇/18.7M 字/核心 226 篇/≈7,816 页；四源判定表）
