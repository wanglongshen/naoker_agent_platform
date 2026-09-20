# 脑壳工作台 · 广告营销 AI Agent 平台

> 面向广告营销场景的企业级 AI Agent 平台：把「人工 1-2 天出一份营销方案」压缩到 **10 分钟以内**，并在企业内部资料上做到 **90%+ 检索命中率**。
>
> 全栈实现：Next.js + Ant Design 前端、FastAPI 后端、LangGraph 任务编排、PostgreSQL + 向量检索、DeepSeekHarness Agent 运行时、Docker 一键部署。

**在线架构图：** https://wanglongshen.github.io/naoker_agent_platform/

---

## 亮点速览

| 指标 | 结果 |
| --- | --- |
| 方案产出耗时 | 人工 1-2 天 → **6 分 08 秒 / 10 分 40 秒**（两次真实端到端运行：调研、初稿、审校、交付、计费全链路） |
| 私有资料检索 | **recall@5 = 90.9%**（110 问黄金测试集）、P95 **26ms** |
| 知识库规模 | **8 个专业库 / 502 篇官方资料 / 5,822 个语义块** |
| 测试基线 | 后端 **1,300+ 条**、前端 **660+ 条**，全绿 |
| Agent 执行内核 | LangGraph 单轨化，**10/10 场景与旧引擎逐字节零差异**（事件流差分校准） |
| 真实计费 | 单次任务 **1,477,293 tokens → 148 积分**（从 DSH 会话事件采集真实 usage） |
| 权限体系 | 12 个权限码、3 类角色、跨用户审计；越权访问一律 404 |

## 系统架构

```
┌──────────────────────────── 平台层 ────────────────────────────┐
│  Next.js + Ant Design 门户（工作台 / 知识库管理 / 文件库 / 审计） │
└───────────────┬───────────────────────────────┬────────────────┘
                │ REST / SSE                    │ iframe 嵌入
┌───────────────▼───────────────┐   ┌───────────▼────────────────┐
│        FastAPI 平台服务        │   │   DeepSeekHarness 运行时    │
│  RBAC · 文件库 · 计费 · 审计   │◄──┤  每用户独立实例（独立 HOME）│
│  RAG 检索 · 任务链 · 事件总线  │   │  插件 / 技能 / 工具注入     │
└───────┬───────────────┬───────┘   └───────────┬────────────────┘
        │               │                       │
┌───────▼──────┐ ┌──────▼────────┐   ┌──────────▼────────────────┐
│  PostgreSQL  │ │ 任务链 Worker │   │  LangGraph 编排（8 节点）  │
│  + 向量检索  │ │ （领取/重试） │   │ 调研→初稿→审校→交付→计费  │
└──────────────┘ └───────────────┘   └───────────────────────────┘
```

交互式架构图（自包含 HTML，浏览器直接打开）：

| 图 | 文件 |
| --- | --- |
| 系统架构总览 | `system-architecture.html` · `system-architecture-diagrams.html` |
| 流式与双通道事件 | `streaming-flow-diagrams.html` |
| RBAC 权限模型 | `rbac-diagrams.html` |
| 文件管理模块 | `file-management-diagrams.html` |
| 对话审计页设计 | `audit-page-mockup.html` |

## 核心能力

- **Agent 工作台**：以 DeepSeekHarness 为 Agent 运行时，每用户一个独立实例（独立 `DSH_HOME`、独立插件层、独立会话库），平台侧统一注入工具与技能；工作台与平台导航合并为一套侧栏，会话列表全站常驻、跨页不中断。
- **多角色权限（RBAC）**：用户/角色/权限三张核心表，`super_admin` 不可变，所有管理操作留审计；资源访问在服务端强校验属主。
- **行业知识库**：8 个专业库（千川投放 / 直播运营 / 短视频与内容 / 商城与商品卡 / 达人与大促 / 行业案例 / 平台规则 / 课程与通用），从官方公开资料采集 → 解析（Quill delta / HTML / PDF / DOCX）→ 标题感知切分 → 向量化 → 检索；支持按库过滤、切块预览、启停用、增量导入、启动预热。
- **方案生产任务链**：LangGraph 状态机编排 8 个节点（收集输入 → 调研清单 → 并行调研 → 初稿 → 结构门禁 → 审校回环 → 交付 → 计费），每个子任务由 DSH 无头执行（独立 home，不与 Web 实例争用），失败重试、事件溯源、进度可观测。
- **平台工具注入**：Agent 可通过连接器插件调用平台能力（文件检索 / 读取文件 / 飞书文档 / 知识库检索），双端令牌校验。
- **计费与审计**：从 DSH 会话事件采集真实 token usage 折算积分；全链路事件持久化 + SSE 断线续传（游标补发）。
- **文件库**：上传魔术字节嗅探、类型白名单、sha256 去重、文本提取，作为 Agent 的一等公民资料源。
- **飞书集成**：OAuth 登录、企业应用配置、方案文档自动同步。
- **一键部署**：`docker compose` 全栈编排（后端 / 前端 / 多 worker / PostgreSQL / Redis），附迁移、健康检查、回滚与状态脚本。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | Next.js（App Router）、React、Ant Design、TypeScript、vitest |
| 后端 | FastAPI、SQLAlchemy 2.x（async）、Alembic、Pydantic、pytest |
| Agent 运行时 | DeepSeekHarness（vendored，MIT）、Cordis 插件、SKILL 技能、MCP |
| 编排 | LangGraph（状态机 + 回环 + 并行子任务） |
| 数据 | PostgreSQL、pgvector 兼容的向量检索层（bytea + 精确余弦，可平滑切换 pgvector） |
| LLM | DeepSeek（对话 / 结构化 JSON / 流式） |
| 检索 | 标题感知切分、本地 bge-small-zh 或 OpenAI 兼容 embedding、精确余弦召回 |
| 部署 | Docker、docker compose、Nginx 反代、健康检查与回滚脚本 |

## 工程方法（本项目的一个差异点）

这个仓库不只是"写完了功能"，而是**按可审计的工程流程做出来的**，过程文档全部保留在 `docs/superpowers/`：

- **设计先行**：每个大改动先出 spec（含边界、验收线、风险），评审通过才动手；
- **TDD**：每个任务先写失败测试，再实现，再回归；
- **差分校准**：执行内核从旧引擎切到 LangGraph 时，用真实 LLM 录制 10 个场景的调用夹具，回放驱动新旧两条轨道，**逐字节比对事件流**，做到 10/10 零差异才切换默认值；
- **搬迁式重构**：3,400 行的执行内核按职责拆成 `execution_kernel` / `quality_gate` / `tool_dispatch` 三个模块，`loop.py` 保留为门面——**调用方一行不改**，靠差分器与 1,300+ 条测试兜底；
- **验收留痕**：`docs/verification/` 里是每一项功能的验收清单与实测数据（不是"应该可以"）；
- **评测驱动**：检索用 110 问黄金集评测，从 54% 迭代到 90.9%（定位到是评测集抽样偏差而非检索缺陷，过程见 `docs/rag-eval/`）。

## 目录结构

```
backend/          FastAPI 服务、Agent 执行内核、RAG、任务链、worker、迁移与测试
frontend/         Next.js 门户（工作台 / 知识库 / 文件 / 审计 / 用户角色）
dsh-platform/     DSH 平台侧插件（连接器 + 客户端桥 / 侧栏隐藏 / 数据观察）
deepseek-harness/ DeepSeekHarness 源码快照（MIT，见 THIRD-PARTY 说明）
deploy/           Dockerfile、docker-compose、部署 / 升级 / 备份脚本
docs/             设计规格、实施计划、评测报告、验收清单
scripts/          本地一键启动 / 停止 / 状态脚本
```

## 快速开始（本机）

```powershell
# 1) 准备环境变量（按 .env.example 填 DeepSeek API Key、数据库连接等）
copy backend\.env.example backend\.env

# 2) 建库 + 迁移
cd backend; alembic upgrade head; cd ..

# 3) 一键启动（后端 / 前端 / 多个 worker）
.\启动系统.cmd
```

默认访问 `http://localhost:3001`，初始管理员见 `INITIAL_ADMIN_USERNAME/PASSWORD`。

## 界面截图

> 待补充：Agent 工作台、知识库管理、对话审计三张实机截图（`docs/screenshots/`）。

## 说明与许可

- **本仓库为个人作品集展示**：公开可见，但**不授予任何开源许可证**（保留所有权利），未经许可请勿用于商业用途。
- `deepseek-harness/` 为 DeepSeek 官方项目源码快照，遵循其 **MIT 许可**（见该目录下 `LICENSE`），版权归 DeepSeek 所有；本项目对其的使用方式为"以官方插件范式二次开发"，未修改其内核。
- 仓库**不包含**任何真实用户数据、业务数据或密钥；`backend/var/**` 运行时数据、`.env` 均在公开前剔除。
