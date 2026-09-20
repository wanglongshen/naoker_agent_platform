# Agent Loop 展示完整迁移与 RBAC 适配设计

## 1. 目标

将 `X:\01_agent_loop` 中所有仍有实际产品价值的前端展示、交互、流式事件和测试逻辑完整迁移到 `X:\01_RBAC`。迁移顺序必须是“先复制有效源逻辑，再仅为 RBAC 边界做最小适配”，不得重新设计一个近似 Agent 产品。

RBAC 负责认证、资源所有权、Cookie/CSRF、私有附件、管理员审计、独立 Worker、attempt 历史和暖色视觉 token；Agent Loop 继续是对话、Session、思考区、步骤、事件、工具记录与运行展示的领域来源。

## 2. 迁移原则

- Agent Loop 中仍被活跃产品路径使用的页面、组件、hooks、helpers、样式和测试默认迁移。
- 能直接使用的 Agent Loop 源代码必须先复制到 RBAC 目标文件，再只修改 RBAC 强制边界；禁止以“参考源文件”为名进行功能性重写。
- 每个实施任务必须列出源文件、目标文件和所有非复制改动的理由。允许的理由仅为：认证/所有权、Cookie/CSRF、API 信封、UUID、私有附件、attempt/lease、`succeeded` 状态、现有 RBAC Shell、暖色 token 或安全脱敏。
- 仅以下实现方式不迁移：匿名 `/runs/*` API、独立 `AppShell` 外壳、FastAPI lifespan Worker、内嵌附件内容、破坏历史的 retry、未鉴权数据访问。
- 对安全边界冲突的代码，保留展示和行为，替换数据来源：`owner_user_id`、UUID、RBAC 信封、`succeeded` 状态、私有 attachment IDs、attempt 关系和 Cookie/CSRF。
- 未被旧活跃页面使用的诊断组件也保留，作为 Session 内的可访问运行诊断能力；不删除 Agent Loop 的有效信息层次。
- 不建立旧 `/runs/*` 兼容路由；所有目标路由保持 `/api/agent/*` 与 `/agent/*`。

## 3. 左侧栏

### 3.1 桌面展开结构

```text
顶部固定
  [RBAC 品牌] [收起侧栏按钮]

中间可滚动 Agent 区
  智能助手
    新建对话
    Session 列表
      按 updated_at 的月份分组
      标题回退：title -> 未命名会话
      本地化更新时间
      当前 Session 高亮
      空态
      加载更多/分页

底部固定管理导航
  用户管理
  角色管理
  Agent 运行审计，仅 active super_admin

最底部固定账户区
  当前登录用户信息
```

智能助手 Session 行为直接迁移自 `AppShell.tsx` 和 `HomepageSidebarList.tsx`：分组、选中态、空态、滚动、标题和更新时间均保留；路由替换为 `/agent` 与 `/agent/sessions/{id}`。Session 创建、继续对话、附件上传完成后触发共享 Session 列表刷新；不复制旧的每三秒全页刷新。

### 3.2 折叠行为

- 桌面端迁移 Agent Loop 的持久化折叠行为，使用 `localStorage` 保存状态。
- 收起按钮位于品牌右侧的同一顶部行。
- 收起后侧栏滑出视口，主工作区扩展；工作区左上角出现浮动展开按钮。
- 移动端保持 RBAC 现有 Drawer，不使用桌面滑出动画。
- Agent Session 滚动区不会遮挡底部管理导航或账户区。

## 4. 用户 Agent 工作区

### 4.1 首页

`/agent` 保留 Agent Loop 的新会话展示层级：模式标题、快速/专家模式切换、能力提示、文本输入、附件、发送和 Session 历史入口。

首条消息支持附件：前端先创建 Session，上传已选择文件，再以返回 attachment IDs 创建第一条 run。阶段失败时保留输入/选文件并明确显示创建、上传或入队失败。

### 4.2 Session 详情

`/agent/sessions/{id}` 保留 Agent Loop 的多轮会话结构：Session 标题、轮数和状态；每一轮都有用户消息、思考区、工具记录和最终答案；底部为继续对话 Composer。

Session 下完整保留以下 Agent Loop 组件能力，直接迁移后适配 RBAC 数据契约：

| Agent Loop 来源 | RBAC 目标职责 |
|---|---|
| `ThoughtNarrative` | 默认可见的用户可读思考区和工具记录 |
| `FinalAnswerPanel` | 流式/历史 Markdown 最终答案 |
| `ThoughtProcess` | 步骤、动作、观察结果诊断 |
| `ThoughtTimeline`、`StepTimeline` | attempt 的步骤时间线 |
| `EventStream`、`LandingEventStream` | 事件列表与原始受控事件展示 |
| `LandingRunEventTimeline`、`LandingSelectedRunEventStream` | 可选择 run 的事件时间线和实时诊断 |
| `RunHeader`、`RunStatus` | run 模式、状态、耗时、attempt、取消/重试展示 |
| `DetailConversation` | 单 run 对话/诊断组合展示 |
| `eventNarrative` | 中文事件标题与摘要 |

主思考区和最终答案默认展示。其他原 Agent Loop 诊断组件维持其原有交互；若旧组件有折叠行为则保留，不为 RBAC 强行重新组织为陌生的“运行详情”产品结构。

普通用户只能读取自己的 run、attempt、step、event、附件元数据和下载。管理员审计复用展示组件，但仅消费后端脱敏字段，不使用 SSE。

## 5. API、流式与契约

### 5.1 用户 API

保留 RBAC `/api/agent` 作为唯一 API：

- `GET /sessions` 返回分页 Session。
- `GET /sessions/{id}/runs` 返回该用户 Session 的 creation-order runs。
- `GET /runs/{id}/steps` 返回当前 attempt 的步骤，兼容 Agent Loop Session 详情初始加载。
- attempt-scoped step API 必须验证 attempt 属于 URL 中 run，否则 404。
- events 使用 `after_seq` / `next_seq` 游标；前端统一在 `agent-api.ts` 解包为组件所需数组。
- 首条和后续附件都只使用 session-scoped upload 与 attachment IDs。

### 5.2 SSE

保留 Agent Loop 的 replay -> subscribe -> catch-up -> heartbeat -> terminal final catch-up 流程，并适配 RBAC 所有权与短生命周期数据库 session。

- 事件 wire shape 兼容 Agent Loop reducer：提供或统一标准化 `event_type`/`type` 与 `created_at`/`timestamp`。
- 所有实际事件被 frontend event allow-list 接收：`run_succeeded`、`run_cancel_requested`、`visible_thought_paused`、`answer_*`、工具和思考事件。
- `answer_completed.payload.text` 必须写入 reducer 的 `answerText` 和明确的 final answer 合约，使页面刷新/回放后仍能展示答案。
- `run_succeeded` 必须转换为终态 `succeeded`，关闭重连。
- 写入事件的数据库事务提交后，才能唤醒本地 EventBus 或 PostgreSQL notification；数据库事件日志始终是事实来源。

### 5.3 审计

审计唯一使用 `/api/agent/audit/*`，不建立 `/admin` 兼容路径。

- 前端只调用真实的粒度接口并在客户端组合会话、run、attempt、steps 和 events。
- 事件分页使用 cursor/`next_seq`，不伪装 offset page/total。
- 详情资源不存在返回符合 RBAC 规则的 404，不返回 `200 {data: null}`。
- 前端类型不声明后端未返回的聚合 fields。

## 6. Worker 可靠性

保留 Agent Loop `BackgroundRunWorker` 的 polling/semaphore 调度形式和 `AgentLoopService` 领域逻辑，替换为 RBAC 的 PostgreSQL claim/lease/attempt 模型：

- semaphore 从 claim 到 attempt 完成全程持有。
- 执行期间定期续租；关闭时停止领取并安全释放/过期未完成 lease。
- 过期 attempt 标记历史结果后，按 retry budget 创建新的 queued attempt；不删除旧步骤或事件。
- retry backoff 保留源 `next_retry_at` 语义，使用 persisted not-before 字段或等效字段阻止 Worker 提前领取。
- cancellation 保持协作式：Planner、LLM chunk、工具边界检查 `cancel_requested`，以条件更新完成 `cancelled`。
- `AgentStep.observation` 保持源模型的结构化 JSON 语义，不以 Text 字段承载字典。

## 7. 测试迁移与验收

优先迁移 Agent Loop 测试，而不是只为当前实现补近似测试：

- `test_event_streaming.py`：fan-out、replay/subscribe/catch-up、heartbeat、cursor 优先级、持久化后发布。
- `test_agent_tools.py`、`test_llm_streaming.py`：Planner、工具安全、可见思考、checkpoint、最终答案。
- `useTypingText.test.ts`、`typingAnimation.test.ts`、`thoughtNarrative.test.ts`、`runStreamReducer.test.ts`、组件测试。

补充 RBAC 特定回归测试：

- Session Sidebar 分组、空态、选择态、分页、创建/继续对话后的刷新、桌面折叠持久化与移动 Drawer。
- 首条附件的 create-session -> upload -> create-run 流程。
- 真实 audit endpoint/response shape/cursor 分页。
- `attempt_id` 和 `run_id` 资源关联校验。
- 长任务续租、租约过期恢复、delayed retry、取消完成竞争、Worker 并发上限。
- SSE 的 final answer 回放、`run_succeeded` 终态、multi-subscriber fan-out 和提交后唤醒。

验收时必须通过：后端 Agent/RBAC 全量测试、前端 Vitest、Next.js production build、Alembic upgrade head。不得破坏现有用户/角色管理。
