# Agent Loop 与 RBAC 生产级集成设计

## 1. 目标与范围

将 `X:\01_agent_loop` 的 Agent Loop 能力整合进 `X:\01_RBAC`，形成由 RBAC 管理身份与授权、由 Agent 提供私有对话、工具调用、文件附件与运行审计的统一系统。

`X:\01_RBAC` 是唯一交付项目。`X:\01_agent_loop` 仅为能力与测试的迁移来源；不迁移其历史数据库、独立部署配置或旧 API 兼容层。

### 1.1 已确认的产品决策

- 附件采用正式文件上传，不采用浏览器读取后内嵌 JSON 文本的 MVP 模式。
- Agent 执行器为独立 Worker 进程，可水平扩展，不嵌入 FastAPI `lifespan`。
- 运行、步骤与事件保留 180 天；附件原文件与提取文本保留 90 天。
- 使用 PostgreSQL 实现原子领取、租约、事件持久化与 SSE 回放；本期不引入 Redis、RabbitMQ 或 Celery。
- 最大化复用 `X:\01_agent_loop` 的领域逻辑、流式事件协议、工具安全校验与测试语义；只替换与统一身份、可靠队列、私有附件、安全边界和 RBAC 契约冲突的基础设施适配层。

### 1.2 不在范围

- 迁移 Agent Loop 历史数据库数据。
- 兼容 Agent Loop 现有 `/runs` API 或独立前端路由。
- 修改现有 RBAC 用户、角色、权限接口的行为，或移除 `user_manager` 角色。
- 新增 `agent:*` 权限码。本期 Agent 使用登录用户所有权与 `super_admin` 角色审计规则。
- 公开对象存储 URL、静态文件目录或附件正文审计恢复能力。

## 2. 总体架构与部署

| 层级 | 职责 |
|---|---|
| Next.js 前端 | 基于登录态的页面、会话交互、SSE 断线恢复、受控附件上传、只读审计 UI |
| RBAC FastAPI API | Cookie JWT 鉴权、资源所有权校验、REST API、SSE 授权与回放、附件授权、任务入队 |
| PostgreSQL | RBAC/Agent 业务数据、运行租约、不可变事件、审计查询和留存作业记录 |
| Agent Worker | 原子领取运行、调用 LLM/工具、状态机推进、写入步骤和事件、取消与重试处理 |
| 私有文件存储 | 原始附件与受控提取文本；不提供静态公开访问 |

API 可部署多个副本，Worker 作为单独命令部署一个或多个副本。每个 Worker 通过 PostgreSQL 原子条件更新领取一个待执行 attempt，写入 `worker_id`、`claimed_at`、`lease_expires_at` 和 `attempt_number`。有效租约内同一 attempt 只允许一个 Worker 执行；租约到期后由恢复程序新建 attempt 重新排队。

FastAPI 不负责执行长时间模型或工具调用，也不在 `lifespan` 启动 Worker。它仅验证配置、管理 API 生命周期与共享 HTTP 客户端资源。Worker 自行初始化并在关闭时停止领取、等待受限时间完成或释放租约、关闭 LLM/HTTP 客户端。

所有 JSON REST 响应遵循既有 RBAC 成功信封 `{ data, message, request_id }` 和标准错误信封。SSE 使用原生 `text/event-stream`，且必须在开始响应之前完成认证、授权和游标校验。

## 3. 权限、资源隔离与 CSRF

现有 RBAC 角色体系保持不变。所有已登录用户，包括 `user_manager` 和 `super_admin`，可仅针对自己的会话创建会话、上传附件、发起运行、查看、取消和重试。只有活跃且未删除的 `super_admin` 可跨用户只读审计；任何角色均不能代替其他用户创建、取消或重试。

后端新增 `require_super_admin()`，通过 `UserRole -> Role` 查询 `Role.code == "super_admin"`，并过滤已删除或非 `active` 的角色。不能依据前端传入角色或“拥有所有当前权限”推断超级管理员。

所有用户资源依赖必须执行一条包含 `owner_user_id == current_user.id` 的查询。不存在和不归属资源统一返回 `404`，覆盖会话、运行、attempt、步骤、事件、SSE、附件上传、下载和删除。未登录统一为 RBAC 标准 `401`；非超级管理员访问审计统一为 `403`。

Cookie 身份认证的所有状态改变请求均实施 CSRF 防护。前端经受控端点取得 token，并以自定义请求头提交；服务端验证 CSRF token、精确允许的 `Origin` 和 `Referer`。Agent REST 与 SSE 都校验 Origin。生产 Cookie 使用 `HttpOnly`、`Secure` 与明确的 `SameSite`、Domain、Path；CORS 只允许配置的精确来源并启用凭据。

## 4. 数据模型与一致性

所有 Agent 物理表使用专有前缀，避免与统一系统未来的通用表名冲突。全部主键、`users.id` 相关外键均为 PostgreSQL `UUID`。

| 表 | 职责与核心字段 |
|---|---|
| `agent_sessions` | 对话容器：`id`、`owner_user_id`、`title`、`last_run_id`、时间戳 |
| `agent_runs` | 一次用户发起：`id`、`session_id`、`owner_user_id`、`goal`、`mode`、`network_enabled`、`status`、`current_attempt_id`、时间戳 |
| `agent_run_attempts` | 每次实际执行：`id`、`run_id`、`attempt_number`、`status`、`worker_id`、租约字段、开始/结束时间、失败码、`retry_of_attempt_id` |
| `agent_steps` | 单次 attempt 的规划/工具步骤：`attempt_id`、`step_number`、计划摘要、受控工具摘要、状态、耗时 |
| `agent_run_events` | 不可变回放日志：`run_id`、`attempt_id`、递增 `seq`、`event_type`、受控 JSON payload、`created_at` |
| `agent_attachments` | 附件授权与生命周期：所有者、会话、私有 `storage_key`、文件名、MIME、大小、SHA-256、提取状态、`expires_at` |
| `agent_run_attachments` | 运行与附件引用；同属用户与会话 |
| `agent_retention_jobs` | 留存清理作业、统计和受限错误摘要 |

所有 `owner_user_id` 均为 `NOT NULL`、带索引，并以 `ON DELETE RESTRICT` 外键引用 `users.id`。本期不支持无会话运行。会话定义 `(id, owner_user_id)` 唯一键；运行通过 `(session_id, owner_user_id)` 复合外键引用该键，数据库层面保证运行和会话的所有者一致。

关键索引为：`agent_sessions(owner_user_id, updated_at DESC)`、`agent_runs(owner_user_id, created_at DESC)`、`agent_runs(session_id, created_at)`、`agent_run_events(run_id, seq)`、`agent_steps(attempt_id, step_number)` 及 attempt 队列领取索引 `(status, lease_expires_at, created_at)`。Alembic migration 必须创建全部表、外键、约束和索引；模型必须被 `alembic/env.py` 和测试 metadata 导入。

运行状态为 `queued`、`running`、`retry_wait`、`succeeded`、`failed`、`cancel_requested`、`cancelled`。attempt 状态为 `queued`、`claimed`、`running`、`retryable_failed`、`succeeded`、`failed`、`cancelled`、`lease_expired`。状态迁移、步骤写入和业务事件插入必须处于同一个数据库事务；只在提交后发布实时唤醒。

创建运行在一个事务内创建 run、首次 attempt 和 `run_queued` 事件。Worker 使用 `SELECT ... FOR UPDATE SKIP LOCKED` 或等价的条件 `UPDATE ... RETURNING` 原子领取 attempt。Worker 定期续租；租约过期恢复为新的 queued attempt。取消先写入 `cancel_requested`，Worker 在规划、LLM 流和工具边界检查，最终原子写入 `cancelled`。重试从不删除旧数据，而是创建新的 attempt，原 attempt、步骤和事件保留至留存期结束。

## 5. API 与 SSE

用户 API 前缀为 `/api/agent`：

| 方法 | 路径 | 用途 |
|---|---|---|
| POST/GET | `/sessions` | 创建会话；分页列出自己的会话 |
| GET | `/sessions/{session_id}` | 会话及分页运行摘要 |
| POST/GET | `/sessions/{session_id}/attachments` | multipart 上传；附件元数据列表 |
| POST | `/sessions/{session_id}/runs` | 创建运行，仅提交 goal、模式、联网开关、附件 ID |
| GET | `/runs/{run_id}` | 运行及当前 attempt 摘要 |
| GET | `/runs/{run_id}/attempts` | attempt 列表 |
| GET | `/runs/{run_id}/attempts/{attempt_id}/steps` | 分页步骤摘要 |
| GET | `/runs/{run_id}/events` | 按 `after_seq` 分页回放事件 |
| GET | `/runs/{run_id}/stream` | SSE 实时流与持久化回放 |
| POST | `/runs/{run_id}/cancel` | 请求协作式取消 |
| POST | `/runs/{run_id}/retry` | 新建执行 attempt |
| GET | `/attachments/{attachment_id}/download` | 鉴权流式下载私有附件 |
| DELETE | `/attachments/{attachment_id}` | 删除未被执行中运行引用的附件 |

审计 API 前缀为 `/api/agent/audit`，全部为 `GET` 且仅限 `super_admin`：会话分页筛选、会话及运行摘要、运行及 attempt 摘要、分页步骤和按游标分页的受控事件。审计默认不返回附件正文、提取文本、完整 prompt、模型原文或未脱敏工具载荷，不创建 SSE 流。

前端经同源 Next.js 反向代理访问 SSE，使 Cookie JWT 不跨域。SSE 支持 `Last-Event-ID` 和 `after_seq`；事件 `id` 等于持久化 `seq`，按 `(run_id, seq)` 严格递增。客户端重连提交最后成功序号、按序号去重；文本 delta 使用稳定 `stream_id` 和精确 `offset` 以实现幂等重放。

服务端持久化事件后再发送唤醒。优先使用 PostgreSQL `LISTEN/NOTIFY` 唤醒连接，轮询数据库提供最终一致性兜底。每 15 秒 heartbeat；响应添加 `Cache-Control: no-store, no-transform` 与 `X-Accel-Buffering: no`。终态执行最终 catch-up 后关闭。`401`、`403`、`404`、`410`、协议错误均不可重连；短暂网络错误采用有限指数退避。SSE 生成器不得长期持有请求依赖 SQLAlchemy session，每次读取使用短生命周期只读 session。

## 6. 附件、LLM 与工具安全

附件上传至私有暂存区，经过 MIME 白名单、服务端内容嗅探、单文件/单会话数量和容量限制、SHA-256 计算、恶意软件扫描及受限文本提取，才标记为可引用。拒绝压缩包、可执行文件和未支持格式。提取任务限制 CPU、内存、时长和输出长度。服务端以 UUID 生成 `storage_key`，不由文件名构建路径；不暴露静态目录或公开 URL。

创建运行仅引用用户在该会话中已上传且可用的 attachment ID。原文件、提取文本、完整 prompt、模型输出和敏感工具输出不得写入事件 payload、应用日志或默认审计响应。附件文本进入 prompt 时必须被标记为不可信外部资料，不能覆盖系统指令或工具策略。到期、删除或扫描/提取失败通过受控作业删除存储对象与元数据。

复用 Agent Loop 的 `tool_executor.py` SSRF、DNS 私网拒绝和重定向复验逻辑，并补足响应体大小限制、出口策略与测试。DeepSeek、Tavily、存储和扫描配置均由环境变量提供，启动时校验必填项与范围，任何日志不得输出密钥。

## 7. 前端设计

建立仅要求已登录的 Agent 路由组，复用 `dashboard-shell`、顶部栏与侧栏，但不继承当前以 `USER_READ` 保护整个 dashboard 的 layout。`/users` 和 `/roles` 保持各自权限保护。

| 路由 | 访问规则 | 责任 |
|---|---|---|
| `/agent` | 已登录 | 创建会话、我的会话、附件管理 |
| `/agent/sessions/[sessionId]` | 已登录，后端校验所有权 | 历史对话、一个活跃运行的 SSE、取消与重试 |
| `/agent/audit` | 前端提示 + 后端 `super_admin` 强制 | 只读跨用户会话/运行检索 |
| `/agent/audit/sessions/[sessionId]` | 同上 | 会话和运行摘要 |
| `/agent/audit/runs/[runId]` | 同上 | 分页步骤、事件摘要 |

前端 `isSuperAdmin(user)` 只根据 `/api/auth/me` 的 `roles[].code` 驱动导航和体验，不能替代 API 授权。登录优先转到安全 callback；无 callback 时 `super_admin` 默认 `/users`，其他用户默认 `/agent`。侧栏按路由前缀计算选中状态，使会话和审计详情保持对应高亮。

迁移时复用既有 CSS variables 与 Ant Design Provider tokens，不增加相近但不一致的色值。Markdown 默认不渲染原始 HTML，链接采用安全策略，代码块和长文本支持窄屏溢出处理。

## 8. 代码迁移与复用

采用“保留领域能力，替换基础设施适配层”的迁移策略：

| Agent Loop 模块 | 迁移策略 |
|---|---|
| `services/planner.py`、`services/llm.py` | 高度复用；接入 RBAC 设置与统一客户端生命周期 |
| `services/tool_executor.py` | 高度复用既有安全校验；增加边界限制与测试 |
| `services/agent_loop.py` | 复用 Planner、工具、事件和步骤语义；适配 attempt、租约与统一事务 |
| `services/background_worker.py` | 复用调度循环思路；改为独立 Worker 入口和原子领取 |
| `repositories/run_repository.py` | 重构为 Agent repository；移除内部任意 commit，由服务层控制事务 |
| `api/stream.py` | 复用回放、catch-up、心跳和终态关闭；接入 RBAC 授权与短会话访问 |
| `services/event_bus.py` | 保留本地低延迟优化；以数据库事件和 `LISTEN/NOTIFY` 为跨进程机制 |
| `models/*.py`、`schemas/*.py` | 结构性迁移为 UUID、命名空间表、所有权与 attempt 模型 |
| `lib/runStreamReducer.ts` | 直接迁移，适配目标类型；保留 seq 去重和 offset 幂等 |
| `hooks/useRunEventStream.ts` | 高度复用，适配路径、有限重连、不可恢复错误和终态停止 |
| `lib/thoughtNarrative.ts`、`hooks/useTypingText.ts` | 直接迁移并保留测试 |
| Composer、stream、thought、answer 组件 | 复用业务交互和展示层次，适配 Ant Design、RBAC API 与路由 |
| Jest 测试 | 迁移测试语义和案例到现有 Vitest 配置，不并存两套框架 |

## 9. 留存、可观测性与运维

独立维护任务每日小批次清理。附件和提取文本在 90 天后删除；运行、attempt、步骤和事件在 180 天后按依赖顺序删除。会话仅在无运行引用且满足会话留存条件时删除。清理任务使用行锁，失败可重试，并在 `agent_retention_jobs` 记录统计和受限错误摘要。

API 继承 `request_id`；Worker 为每次领取记录 `correlation_id`。指标包括队列积压、领取延迟、运行及模型/工具耗时、失败类型、重试、取消、租约过期、SSE 在线数、附件扫描/提取失败和清理结果。日志仅记录资源 ID 与脱敏、长度受限摘要。

健康检查区分 API 存活、数据库、Worker 心跳、队列积压和存储可用性。部署文档必须覆盖迁移顺序、API/Worker 启动、私有存储、HTTPS/Cookie、SSE 代理禁缓冲与 idle timeout、备份、留存、扩缩容与故障恢复。

## 10. 验收与分阶段交付

### 10.1 验收标准

- Alembic 能从现有 RBAC head 创建完整 Agent 表、约束、索引；Agent 模型对 migration 和测试 metadata 可见。
- JSON API 信封和请求 ID 与现有 RBAC 保持一致；SSE 建连前错误使用标准 JSON 错误。
- 未登录为 `401`；跨用户访问会话、运行、步骤、事件、SSE、附件统一为 `404`；只有有效 `super_admin` 能跨用户审计。
- 并发 Worker 领取相同 queued attempt 时恰好一个成功；租约过期可恢复；取消、完成和重试竞争不会覆盖合法终态。
- 重试保留完整 attempt 历史；SSE 事件 seq 严格递增，replay、重复和 delta offset 可幂等处理。
- 附件覆盖未授权、路径穿越、类型伪造、容量超限、扫描/提取/存储失败、执行中删除和到期清理测试。
- 保留并扩展 Agent Loop 的 Planner、工具、超时、backoff、SSRF、reducer、typing、composer 和流式 UI 测试。
- 普通用户可访问 Agent 但不可访问系统管理和审计；前端验证信封解包、SSE 重连、错误态、附件、取消/重试、窄屏和安全 Markdown。
- 全量执行 RBAC 后端测试、Vitest 测试、TypeScript/Next.js 生产构建，且不回归现有用户/角色能力。

### 10.2 交付阶段

1. 基础与迁移：模型、Alembic、设置、所有权依赖、API 骨架。
2. 可靠执行层：独立 Worker、原子领取、租约、状态机、事件事务、取消与重试。
3. 安全文件能力：私有存储、扫描/提取、附件 API、引用与 90 天清理。
4. 实时前端：路由组、导航、Agent 组件适配、SSE、会话与详情。
5. 审计与运维：只读审计、指标日志、180 天清理、部署与恢复文档。
6. 质量门禁：迁移、并发、安全、端到端、回归与生产构建验证。
