# 左侧导航、会话列表与对话流式响应详细开发实施方案

**文档状态：** 待实施  
**编制日期：** 2026-07-27  
**适用系统：** 权限管理系统 / Agent Loop  
**目标版本：** 下一开发迭代  
**优先级：** P0（最终答案与流式链路）、P1（侧栏布局与会话列表）

## 1. 文档目的

本文档针对当前 Agent 会话页的四类问题给出可执行的开发方案：

1. 将“用户管理、角色管理、Agent 运行审计、超级管理员账户”稳定固定在左侧导航底部。
2. 将会话列表限制在侧栏中部独立滚动，始终保留底部管理入口和账户信息。
3. 将会话项改为参考截图中的紧凑单行样式，去除过宽、过高和冗余时间信息。
4. 修复最终答案偶发不显示以及回答不能实时流式呈现的问题，确保实时、重连和页面重载均能恢复答案。

本文档是后续实施、评审、测试和验收的统一依据。本阶段不直接修改业务代码。除阶段计划外，文档明确到页面结构、接口契约、数据模型、状态机、文件级改动和用例级验收，开发人员可据此拆分任务并实施。

## 2. 系统现状与技术基线

### 2.1 技术架构

| 层级 | 当前实现 |
|---|---|
| 前端 | Next.js 16、React 19、TypeScript、Ant Design 6 |
| 后端 | FastAPI、SQLAlchemy Async、Pydantic |
| 数据库 | PostgreSQL |
| 实时通信 | 浏览器 `EventSource` + FastAPI SSE |
| Agent 执行 | 独立 Worker，事件持久化至 `AgentRunEvent` |
| 测试 | Vitest/React Testing Library、pytest/httpx |

### 2.2 核心代码边界

| 功能 | 主要文件 |
|---|---|
| 左侧栏结构 | `frontend/src/components/layout/app-sidebar.tsx` |
| 页面壳和 Sider | `frontend/src/components/layout/dashboard-shell.tsx` |
| 会话列表 | `frontend/src/components/agent/session-sidebar-list.tsx` |
| 全局侧栏样式 | `frontend/src/app/globals.css` |
| Agent 组件样式 | `frontend/src/app/agent-globals.css` |
| 会话详情页 | `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx` |
| 会话流渲染 | `frontend/src/components/agent/session-conversation-stream.tsx` |
| 最终答案面板 | `frontend/src/components/agent/final-answer-panel.tsx` |
| SSE Hook | `frontend/src/hooks/use-run-event-stream.ts` |
| 事件归并器 | `frontend/src/lib/run-stream-reducer.ts` |
| SSE 接口 | `backend/app/api/agent_stream.py` |
| Agent 执行与答案产出 | `backend/app/services/agent/loop.py` |
| Run HTTP 接口 | `backend/app/api/agent.py` |

### 2.3 当前验证基线

分析阶段已运行以下测试：

- 前端：`run-stream-reducer`、`use-run-event-stream`、`session-sidebar-list`，共 21 项通过。
- 后端：`test_agent_stream.py`、`test_agent_api.py`，共 50 项通过。

结论：现有能力并非完全缺失，现场问题位于布局高度契约、事件终态归并和真实跨进程流式场景等测试盲区。

> 环境说明：当前工作目录未发现可用 Git 元数据。正式实施前必须确认真实代码仓库及基线提交，禁止在无版本基线的目录直接发布。

## 3. 问题分析

### 3.1 左侧底部区域没有稳定固定

现有 `AppSidebar` 已按品牌、新建对话、会话列表、管理菜单和账户区域排列，并对会话容器设置了 `flex: 1`。但外层仅使用 `min-height: 100vh`，Sider 及内容区缺少完整的视口高度和 `min-height: 0` 约束链。在内容较长或浏览器高度较小时，整个页面会被撑高，底部菜单被推到首屏之外。

需要建立清晰的三区结构：

```text
顶部固定区：品牌 + 新建对话
中部弹性区：会话列表，仅该区域滚动
底部固定区：用户管理 + 角色管理 + Agent 运行审计 + 当前账户
```

“超级管理员”在当前系统中是账户显示，不是独立导航路由，应保留为底部账户区；管理菜单仍按现有 RBAC 权限显示，不能为了视觉固定绕过权限控制。

### 3.2 会话列表滚动条存在样式但高度链不完整

`.sidebar-list` 已声明 `overflow-y: auto`，但滚动是否生效取决于所有祖先节点都能提供有限高度并允许子项收缩。当前缺少以下稳定约束：

- 桌面布局固定为 `100dvh` 或等价视口高度。
- `Layout.Sider`、`.sider-inner`、`.app-sidebar` 全链路 `min-height: 0`。
- `.sidebar-session-list-wrapper` 使用弹性行 `minmax(0, 1fr)` 或等价 Flex 约束。
- `.sidebar-list` 明确 `height: 100%`，而不仅是 `flex: 1`。

滚动条当前默认透明、悬停才显示，不符合“给中间会话区一个竖直滚动条”的明确需求。桌面端应使用低对比但持续可辨认的细滚动条；移动端沿用原生滚动体验。

### 3.3 会话项与目标稿不一致

当前每个会话项包含标题和完整本地时间，使用两行布局、较大内边距和块状选中背景，因此单项高度高、视觉宽重。目标截图是按时间分组的紧凑单行标题列表。

建议规格：

- 侧栏桌面宽度由 258px 收敛至 236-244px，最终以 240px 为验收基准。
- 会话项只展示标题，不展示每条记录的时间。
- 标题单行省略：`white-space: nowrap; overflow: hidden; text-overflow: ellipsis`。
- 长标题通过原生 `title` 或 Tooltip 提供完整内容。
- 单项高度约 36px，左右内边距 8-10px，圆角不超过 6px。
- 月份分组继续保留；最近 30 天可显示“30 天内”，更早记录按 `YYYY-MM` 分组。
- 激活态使用克制的底色或左侧指示，不再使用大面积高圆角卡片。
- 列表容器和链接必须 `min-width: 0; width: 100%`，避免长标题撑宽侧栏。

当前接口只请求前 50 个会话。若真实用户可能超过 50 个，应在本次改造中至少明确“加载更多”或滚动分页策略，避免滚动条只覆盖不完整数据。建议本迭代先保留 50 条并增加总数判断，后续接入游标/分页加载；如产品要求完整历史，则本次直接实现滚动到底加载下一页。

### 3.4 最终答案不显示的高风险链路

当前答案事件顺序大致为：

```text
answer_started
answer_delta × N
answer_checkpoint × N
answer_completed（完整 text）
step_completed
run_succeeded（final_answer）
```

已识别的风险点：

1. 前端 reducer 处理 `run_succeeded` 时只设置 `status=succeeded` 并关闭连接，没有读取其 `payload.final_answer`。
2. 若 `answer_completed` 因断线、时序或重放边界未被归并，界面就会出现“任务已完成但无答案”。
3. `FinalAnswerPanel` 在成功但无答案时显示占位文案，与截图现象一致。
4. HTTP 重载虽会从历史事件补 `run.result`，但 `_populate_run_result()` 使用 `except Exception: pass` 静默吞错，无法提供可靠保证和诊断信息。
5. `AgentRun` 数据表当前没有明确持久化 `result` 字段，最终答案依赖扫描事件恢复，查询成本和脆弱性均较高。
6. 会话历史构建仍查找旧的 `run_completed` 事件，而当前主成功事件是 `run_succeeded`，会导致多轮上下文遗漏历史答案。

### 3.5 “流式”需要区分网络流与打字动画

系统目前同时存在两种逐步显示机制：

- 真流式：Worker 产生 LLM chunk，后端持久化 `answer_delta`，SSE 推送到浏览器。
- 展示动画：`useTypingText` 以固定速度逐字展示已收到文本。

用户反馈“不是流式的”不能只通过调快或保留打字动画解决。验收必须证明：在任务仍为 `running` 时，浏览器已收到多个不同序号的 `answer_delta`，并且页面文本随这些事件增长；不能等到完整答案到达后再做本地逐字动画。

后端 SSE 已加入 250ms 数据库轮询，用于 API 与 Worker 分进程时读取已持久化事件。仍需验证：

- 反向代理未缓冲 SSE（`X-Accel-Buffering: no` 已存在，部署层还需核对）。
- 生产链路未启用会聚合响应的压缩/缓存策略。
- `answer_delta` 的数据库事务在每个 chunk 后及时提交。
- 浏览器 `EventSource` 连接保持打开，事件按 `seq` 递增且不丢失。
- 前端不会因为终态先行处理而过早停止最后一批事件归并。

## 4. 目标架构与设计决策

### 4.1 侧栏布局

桌面端使用视口锁定的三段式布局：

```css
.warm-executive-layout { height: 100dvh; min-height: 100vh; overflow: hidden; }
.warm-executive-sider,
.sider-inner,
.app-sidebar { height: 100%; min-height: 0; }
.app-sidebar { display: grid; grid-template-rows: auto auto minmax(0, 1fr) auto; }
.sidebar-session-list-wrapper { min-height: 0; overflow: hidden; }
.sidebar-list { height: 100%; overflow-y: auto; }
```

底部区域新增语义容器 `.sidebar-footer`，内部依次放管理菜单和账户区。移动端 Drawer 复用同一组件，但高度使用 `100dvh`，确保触屏滚动正常。

### 4.2 最终答案单一事实来源

推荐将最终答案持久化到 `AgentRun.result`（JSONB 或现有模型可接受的等价字段），并在同一个终态事务中完成：

1. 写入 `run.result.final_answer`。
2. 将 Run 和 Attempt 标记为 `succeeded`。
3. 写入 `run_succeeded` 终态事件，payload 同样包含 `final_answer`。
4. 提交事务后通知 SSE。

读取优先级统一为：

```text
AgentRun.result.final_answer
→ run_succeeded.payload.final_answer
→ answer_completed.payload.text
→ 最后一个完整 answer_checkpoint（仅恢复场景）
```

HTTP 接口不应再以宽泛异常静默扫描事件作为日常读取路径；事件扫描只作为历史数据兼容层，并应记录可追踪的结构化告警。

### 4.3 前端终态归并

Reducer 必须保证：

- `answer_delta` 按 offset 追加。
- `answer_checkpoint` 可修复中间缺口。
- `answer_completed` 写入 `answerText` 和 `run.result.final_answer`。
- `run_succeeded` 若含 `final_answer`，同样写入结果；若不含答案则保留已累计文本。
- 只有终态事件已归并后才关闭连接。
- 终态回调携带完整的归并后 Run，再触发一次后台重载进行持久态校验。
- 同一 Run 的服务器重载不得用缺少答案的旧对象覆盖本地已流式收到的答案。

### 4.4 可观测性

建议增加不含敏感内容的结构化指标或日志：

- `run_id`、`event_type`、`seq`、`answer_length`、`stream_id`。
- 首个答案 chunk 延迟（TTFT）。
- `answer_delta` 数量及最后序号。
- SSE 重连次数与最后确认序号。
- 成功 Run 无最终答案计数，该值上线后必须为 0。

禁止记录答案正文、Cookie、JWT、API Key 或完整提示词。

## 5. 分阶段实施计划

### 阶段 0：建立版本与现场诊断基线（P0）

**涉及：** 运行环境、浏览器 Network、数据库事件记录、部署代理配置。

- [ ] 确认真实 Git 仓库、分支和基线提交，保存当前部署版本号。
- [ ] 选取一个可稳定复现的 Run，导出脱敏后的事件类型、序号、时间和 payload 字段名。
- [ ] 在浏览器确认 SSE 请求状态、响应头、首事件时间和 `answer_delta` 到达节奏。
- [ ] 对照数据库确认 `answer_started → answer_delta → answer_completed → run_succeeded` 是否完整有序。
- [ ] 核对 API、Worker 是否为独立进程以及反向代理缓冲配置。

**退出条件：** 能明确区分“Worker 未产出”“SSE 未传输”“前端未归并”“终态重载覆盖”四类故障。

### 阶段 1：补齐失败用例与契约测试（P0）

**前端测试文件：**

- `frontend/src/lib/run-stream-reducer.test.ts`
- `frontend/src/hooks/use-run-event-stream.test.ts`
- `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx`
- `frontend/src/components/agent/agent-streaming.test.tsx`

**后端测试文件：**

- `backend/tests/test_agent_loop.py`
- `backend/tests/test_agent_stream.py`
- `backend/tests/test_agent_api.py`

- [ ] 新增仅收到 `run_succeeded.payload.final_answer` 仍显示答案的 reducer 测试。
- [ ] 新增 `answer_completed` 后紧接 `run_succeeded` 不丢答案、不重复答案的测试。
- [ ] 新增断线后从 `after_seq` 重放并恢复 checkpoint/终态答案的测试。
- [ ] 新增终态重载返回旧/空 `result` 时不覆盖本地答案的页面测试。
- [ ] 新增跨进程持久化事件在运行态 250ms 轮询窗口内到达的 SSE 测试。
- [ ] 新增成功事务同时持久化 Run 结果和终态事件的后端测试。

**退出条件：** 新增测试在修复前稳定失败，失败原因与现场现象一致。

### 阶段 2：修复后端答案持久化和 SSE 终态（P0）

**预计修改：**

- `backend/app/models/agent.py`
- `backend/alembic/versions/<new>_persist_agent_run_result.py`
- `backend/app/repositories/agent_repository.py`
- `backend/app/services/agent/loop.py`
- `backend/app/api/agent.py`
- `backend/app/schemas/agent.py`
- `backend/app/api/agent_stream.py`（仅在诊断证明需要时）

- [ ] 为 `AgentRun` 增加可空 `result` JSONB 字段并编写可回滚迁移。
- [ ] 在成功终态事务内原子写入 `result.final_answer`、状态及 `run_succeeded`。
- [ ] 保留 `answer_completed` 作为流式快照/回放事件，不作为唯一数据库事实来源。
- [ ] 将 HTTP Run 响应直接序列化持久化结果。
- [ ] 为迁移前历史数据保留事件回填兼容逻辑，但移除静默 `except Exception: pass`。
- [ ] 修正会话历史读取，使其识别 `run_succeeded` 和持久化 `result`。
- [ ] 确保 SSE 在终态时完成最后一次事件追赶，再结束生成器。

**兼容策略：** 数据迁移后可执行一次批量回填，从最新 `run_succeeded` 或 `answer_completed` 事件生成历史 `result`；回填脚本必须幂等。

### 阶段 3：修复前端事件归并和真实流式展示（P0）

**预计修改：**

- `frontend/src/lib/run-stream-reducer.ts`
- `frontend/src/hooks/use-run-event-stream.ts`
- `frontend/src/components/agent/final-answer-panel.tsx`
- `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx`

- [ ] `run_succeeded` 读取 `payload.final_answer` 并写入 Run 结果。
- [ ] 定义终态答案合并函数，避免三个事件分支出现不同规则。
- [ ] 防止相同 Run 的终态重载用空值覆盖已有流式答案。
- [ ] 将 EventSource 关闭时机放在终态事件完成归并之后。
- [ ] 保留 Markdown 安全渲染和断线续传，明确打字动画仅为视觉增强。
- [ ] 如动画积压明显，改为追赶式显示：收到新 chunk 时优先保证网络增量可见，终态后快速追平。
- [ ] 连接失败时展示可恢复状态，避免将“连接失败”误呈现为“任务成功但无答案”。

**性能目标：** Worker 持久化答案 chunk 后，正常本地环境 500ms 内应在页面可见；首个 chunk 到最终完成期间至少发生两次可观察 DOM 文本增长（短答案除外）。

### 阶段 4：重构侧栏高度、底部区域和中部滚动（P1）

**预计修改：**

- `frontend/src/components/layout/dashboard-shell.tsx`
- `frontend/src/components/layout/app-sidebar.tsx`
- `frontend/src/app/globals.css`

- [ ] 将桌面 Layout 锁定到视口高度并禁止页面整体纵向滚动。
- [ ] 为 Sider 全链路补齐 `height: 100%` 和 `min-height: 0`。
- [ ] 新增 `.sidebar-footer`，将管理菜单与账户区固定为底部非收缩区域。
- [ ] 仅允许 `.sidebar-list` 纵向滚动。
- [ ] 桌面端持续显示 5-6px 细滚动条，Hover/Focus 时增强对比。
- [ ] 保持 RBAC 菜单过滤：用户、角色、审计入口只对有权限用户显示。
- [ ] 保持移动 Drawer 和桌面折叠状态逻辑。

### 阶段 5：会话项紧凑化（P1）

**预计修改：**

- `frontend/src/components/agent/session-sidebar-list.tsx`
- `frontend/src/components/agent/session-sidebar-list.test.tsx`
- `frontend/src/app/globals.css`
- `frontend/src/app/agent-globals.css`

- [ ] 删除会话项中的完整时间元数据 DOM。
- [ ] 标题改为单行省略，增加可访问的完整标题提示。
- [ ] 将项高度、间距、圆角和激活态调整为目标截图的紧凑规格。
- [ ] 调整月份分组文案和间距；“30 天内”与历史月份层次清晰。
- [ ] 将桌面 Sider 宽度调整为约 240px，并验证中文/英文长标题。
- [ ] 评估并实现 50 条以上会话的分页加载策略。

### 阶段 6：自动化、视觉和端到端验收（P0/P1）

- [ ] 运行完整前端测试：`npm test -- --run`。
- [ ] 运行生产构建：`npm run build`。
- [ ] 运行完整后端测试：`python -m pytest -q`。
- [ ] 使用真实 API、Worker、数据库完成新建会话到最终答案的端到端测试。
- [ ] 在 1920×1080、1366×768、1024×768、390×844 视口检查布局。
- [ ] 构造至少 60 条会话，验证中部滚动且底部菜单始终可见。
- [ ] 使用超长中英文标题，验证不撑宽、不换行、不遮挡滚动条。
- [ ] 在流式中途断网并恢复，验证从最后序号续传且答案不重复。
- [ ] 刷新已完成会话，验证最终答案与流式完成时一致。

## 6. 测试矩阵

| 场景 | 预期结果 |
|---|---|
| 5 条会话 | 无不必要滚动，底部区域贴近视口底部 |
| 60 条会话 | 仅会话区滚动，管理菜单和账户不移动 |
| 240px 侧栏长标题 | 单行省略，侧栏宽度不变化 |
| 普通用户 | 只显示获授权的管理入口 |
| 超级管理员 | 显示用户、角色、Agent 审计和底部账户身份 |
| 正常流式回答 | 运行中持续出现 `answer_delta`，文本逐步增长 |
| SSE 短暂断开 | 使用 `after_seq` 续传，不丢失、不重复 |
| 只收到成功终态 | 从 `run_succeeded.final_answer` 显示完整答案 |
| 页面刷新 | 从 `AgentRun.result` 恢复完整答案 |
| 历史未迁移数据 | 从兼容事件读取答案并可回填 |
| 失败/取消任务 | 不伪造最终答案，显示明确状态 |
| 移动端 Drawer | 会话区可滚动，底部入口可到达且不重叠 |

## 7. 验收标准

### 7.1 视觉与交互

1. 在 1366×768 及更高桌面视口中，用户管理、角色管理、Agent 运行审计和账户区无需滚动页面即可看到。
2. 会话超过可用高度后，仅中间会话列表出现竖直滚动条。
3. 会话项为单行紧凑样式，无逐条时间副标题；长标题显示省略号。
4. 侧栏宽度约 240px，不因标题、图标或选中态发生宽度变化。
5. 所有按钮、文字和滚动区域在桌面及移动端无重叠。

### 7.2 数据与流式

1. 任意 `succeeded` Run 均可通过 HTTP 获取非空 `result.final_answer`；业务确实返回空答案时必须视为异常而非成功。
2. SSE 事件按 `seq` 严格递增，重连后不重复归并。
3. 运行过程中浏览器能收到 `answer_delta`，不得等到终态后才一次性显示。
4. `answer_completed`、`run_succeeded`、页面重载三条路径产生一致最终文本。
5. 成功 Run 无答案监控值为 0。

### 7.3 质量门禁

- 前后端完整测试通过。
- Next.js 生产构建通过。
- 数据库迁移可升级、可降级，历史回填幂等。
- 无权限回归、无跨用户会话泄露、无敏感内容日志。
- 真实浏览器完成至少一次流式、断线恢复和刷新恢复验收。

## 8. 风险与控制措施

| 风险 | 控制措施 |
|---|---|
| 新增 `result` 字段影响历史数据 | 可空迁移、事件兼容读取、幂等回填、分阶段启用 |
| SSE 代理缓冲导致本地正常生产不流式 | 将代理配置纳入验收，使用时间戳和 Network 面板验证 |
| 终态刷新覆盖本地新状态 | 使用答案非空优先和序号优先的合并规则 |
| 会话列表只加载 50 条 | 明确分页加载，至少显示总数并提供加载更多 |
| 固定视口影响管理页长表格 | 只锁定应用壳，主内容区建立自己的滚动容器并逐页验证 |
| 移动浏览器地址栏改变视口高度 | 优先 `100dvh`，以 `100vh` 作为兼容回退 |
| 旧事件命名并存 | 建立明确兼容表，写入只使用当前规范，读取兼容旧值 |

## 9. 发布与回滚方案

### 9.1 发布顺序

1. 发布数据库迁移和兼容读取后端。
2. 执行并核验历史结果回填。
3. 发布原子终态写入和 SSE 修复。
4. 发布前端 reducer/Hook 修复。
5. 发布侧栏和会话列表视觉改造。
6. 观察成功无答案、SSE 重连和接口错误指标至少一个完整业务周期。

### 9.2 回滚

- 前端可独立回滚到旧构建，后端保持兼容字段不会破坏旧客户端。
- 后端代码回滚前应停止新 Worker，避免不同版本同时写入不同终态契约。
- 数据库字段在确认无旧版本依赖后再执行降级；紧急回滚时可保留可空字段，不必立即删除数据。
- 历史回填不删除事件，因此可从事件重新构建结果。

## 10. 建议任务拆分

| 任务 | 角色 | 估算 | 依赖 |
|---|---|---:|---|
| 现场事件与代理诊断 | 全栈/运维 | 0.5-1 人日 | 无 |
| 后端结果持久化与迁移 | 后端 | 1-1.5 人日 | 诊断完成 |
| SSE 终态与回放测试 | 后端 | 0.5-1 人日 | 结果契约 |
| Reducer/Hook/页面合并修复 | 前端 | 1 人日 | 事件契约 |
| 侧栏三区布局 | 前端 | 0.5 人日 | 无 |
| 会话紧凑样式与分页 | 前端 | 0.5-1 人日 | 产品确认分页范围 |
| E2E、视觉回归与发布核验 | 测试/全栈 | 1 人日 | 全部开发完成 |

整体预计 4-6 人日，取决于生产代理诊断和历史数据回填规模。

## 11. 完成定义（Definition of Done）

只有同时满足以下条件，本专项才可关闭：

- 四项用户反馈均通过真实浏览器验证，不以单元测试替代现场验收。
- 侧栏底部区域在目标视口稳定固定，会话列表独立滚动且样式达到参考图要求。
- 最终答案在实时、重连和刷新三种场景均完整显示。
- 网络层能够证明增量事件在运行中到达，非仅依赖本地打字动画。
- 完整测试、构建、迁移、权限和安全检查全部通过。
- 发布和回滚记录、基线提交、验证截图及关键指标归档到本专项文档或对应变更记录。

## 12. 详细技术设计

本节是本专项的实施基准。除非在代码走查中发现当前实现与本文档描述不一致，否则开发不应自行改变事件名称、字段语义或状态转移。

### 12.1 页面结构与 CSS 高度契约

#### 12.1.1 目标组件树

`DashboardShell` 与 `AppSidebar` 必须形成以下固定的高度和滚动边界。`100dvh` 用于避免移动端浏览器地址栏变化造成的高度抖动；若系统已有统一视口变量，应复用该变量。

```text
html / body / Next 根节点（height: 100%）
└─ DashboardShell（height: 100dvh; overflow: hidden）
   ├─ AppSidebar（height: 100%; min-height: 0; display: flex; flex-direction: column）
   │  ├─ SidebarHeader（flex: 0 0 auto）
   │  │  ├─ Brand
   │  │  └─ NewSessionButton
   │  ├─ SidebarSessions（flex: 1 1 auto; min-height: 0; overflow: hidden）
   │  │  └─ SessionSidebarList（height: 100%; overflow-y: auto; overflow-x: hidden）
   │  └─ SidebarFooter（flex: 0 0 auto）
   │     ├─ RBACNavigation
   │     └─ CurrentAccount
   └─ MainContent（min-width: 0; min-height: 0; overflow: auto）
```

#### 12.1.2 必须满足的布局规则

| 编号 | 规则 | 实现要求 |
|---|---|---|
| L-01 | 仅 Session 区滚动 | 不允许由 `body` 或整个侧栏承载会话列表滚动。 |
| L-02 | 底部始终可见 | 管理菜单和当前账户位于 `SidebarFooter`，不得放在 Session 列表 DOM 内。 |
| L-03 | 子项可收缩 | 每一层参与 Flex 嵌套的容器均显式设置 `min-height: 0`；横向内容区另设 `min-width: 0`。 |
| L-04 | 侧栏尺寸稳定 | 桌面宽度固定为 `240px`，允许响应式断点下折叠，但 Session 条目不得用内容撑宽侧栏。 |
| L-05 | 滚动条可发现 | WebKit 和 Firefox 均配置细滚动条；默认低对比，悬停或滚动时提高轨道/滑块对比。 |
| L-06 | 小视口可用 | 在 `1280x720`、`1440x900`、`390x844` 验证底部区可访问；移动端以抽屉模式呈现时仍保持列表与底部区分离。 |

#### 12.1.3 会话项视觉规格

| 属性 | 目标值 | 说明 |
|---|---:|---|
| 条目高度 | 36px | 固定高度，避免标题、悬停状态引起列表跳动。 |
| 内边距 | 0 10px | 不再使用卡片式大留白。 |
| 圆角 | 4px | 与紧凑的管理系统侧栏一致。 |
| 标题 | 单行、14px、`text-overflow: ellipsis` | 隐藏时间副标题，完整标题以原生 `title` 或 Tooltip 提供。 |
| 激活态 | 左侧 2px 标记或低饱和背景色 | 不能只依赖颜色，需有清晰的当前项标识。 |
| 操作按钮 | Hover/键盘聚焦时出现 | 使用图标按钮和无障碍名称；不得挤压标题可用宽度。 |
| 分组间距 | 8px | 侧栏不额外包裹卡片。 |

### 12.2 后端数据模型和迁移设计

#### 12.2.1 结果事实来源

为 `AgentRun` 增加可空的 `result` JSONB 字段。它保存“该次运行的最终业务结果”，不替代完整的 `AgentRunEvent` 审计日志。事件流仍是排障、回放和审计依据；`result` 是 HTTP 查询、页面刷新和历史上下文构建的稳定读取源。

建议结构如下：

```json
{
  "final_answer": "面向用户的最终回答正文",
  "answer_format": "markdown",
  "completed_at": "2026-07-27T08:00:00Z",
  "source_event_sequence": 42,
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0
  }
}
```

字段语义：

| 字段 | 类型 | 写入时机 | 读取要求 |
|---|---|---|---|
| `result.final_answer` | 非空字符串 | 运行成功事务 | `succeeded` 状态下必须可读取；空字符串视为异常。 |
| `result.answer_format` | 枚举字符串 | 同上 | 初期固定 `markdown`，为后续富文本留扩展位。 |
| `result.completed_at` | UTC ISO 8601 | 同上 | 与 Run 终态时间一致。 |
| `result.source_event_sequence` | 整数 | 同上 | 指向完成答案或成功事件的序号，便于追溯。 |
| `result.usage` | 对象，可空 | 有模型用量时 | 不能因缺少用量导致结果写入失败。 |

#### 12.2.2 迁移步骤

1. 创建 Alembic revision，仅新增可空 `agent_runs.result JSONB` 字段及必要的字段注释，不在同一迁移删除旧数据或修改既有事件表。
2. 部署迁移后，后端读路径保持兼容：优先读 `result.final_answer`，为空时按事件倒序查询 `run_succeeded.payload.final_answer`、`answer_completed.payload.text`。
3. 编写一次性、可重复执行的回填命令。每次只处理 `status='succeeded' AND result IS NULL` 的 Run，按同一回退顺序填入结果；没有答案的成功 Run 写入监控清单，不伪造空字符串。
4. 抽样核对回填数量、无答案异常数量和事件序号；确认后才将“成功 Run 必有结果”提升为运行时断言和监控指标。
5. 字段至少保留一个发布周期。回滚应用代码时不回滚或删除该字段，避免数据丢失。

#### 12.2.3 终态原子性

Worker 或服务层在单个数据库事务内完成以下行为：更新 `AgentRun.status`、`AgentRun.result`、终态时间，并写入 `run_succeeded` 事件。事务失败时四项均回滚，禁止出现“已成功但没有结果”或“有成功事件但 Run 仍 running”的部分提交状态。

### 12.3 SSE 事件契约

#### 12.3.1 通用信封

每条 SSE `data` 必须是 JSON，含有不可重复的运行内序号。SSE `id` 应与 `sequence` 一致，以支撑 `Last-Event-ID` 断线恢复。

```json
{
  "run_id": "uuid",
  "sequence": 17,
  "event_type": "answer_delta",
  "created_at": "2026-07-27T08:00:00.120Z",
  "payload": {}
}
```

#### 12.3.2 事件表和载荷约束

| 事件 | 是否可多次发送 | payload | 前端处理 |
|---|---|---|---|
| `answer_started` | 否 | `{ "format": "markdown" }` | 清除该 Run 旧的临时流状态，置 `answerStreaming=true`。 |
| `answer_delta` | 是 | `{ "text": "增量文本", "offset": 0 }` | 按 `offset` 去重、补齐或追加；不得依赖到达顺序盲目拼接。 |
| `answer_completed` | 否 | `{ "text": "完整答案", "format": "markdown" }` | 用完整文本校正缓存，置 `answerStreaming=false`。 |
| `run_succeeded` | 否 | `{ "final_answer": "完整答案", "result": { ... } }` | 作为终态兜底答案来源；同步 Run 状态与结果。 |
| `run_failed` | 否 | `{ "code": "...", "message": "...", "retryable": false }` | 保留已收到的文本，结束流并显示明确失败态。 |
| `heartbeat` | 是 | `{}` | 仅维持连接，不更新 UI 文本。 |

禁止事项：不允许将完整答案同时伪装成单条 `answer_delta` 和 `answer_completed`；不允许终态事件省略 `final_answer`；不允许使用前端本地打字效果作为流式成功判定。

#### 12.3.3 SSE 服务实现要求

- 响应头包含 `Content-Type: text/event-stream`、`Cache-Control: no-cache, no-transform`、`X-Accel-Buffering: no` 和适用的跨域头。
- 生成器在读取到新事件后立即 `yield` 并 flush，不等待 Run 终态；心跳间隔建议不高于 15 秒。
- 每个 `answer_delta` 在 Worker 产生后及时提交事件，不能在内存中累计完整答案后批量入库。
- 使用 `Last-Event-ID` 或 query 参数 `after_sequence` 回放漏失事件；回放和实时事件共享同一排序规则。
- 服务端日志以 `run_id`、`sequence`、`event_type`、写入时间和推送时间为结构化字段，禁止记录完整敏感答案正文。

### 12.4 前端状态机与 Reducer 设计

#### 12.4.1 运行态模型

Reducer 状态至少包含以下字段：

```ts
type StreamRunState = {
  runId: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
  answerText: string;
  answerStreaming: boolean;
  lastSequence: number;
  receivedOffsets: Record<number, number>;
  result?: { final_answer?: string; [key: string]: unknown };
  error?: { code?: string; message: string; retryable?: boolean };
};
```

`receivedOffsets` 可以按现有数据结构替换为区间集合，但必须实现幂等消费：同一 sequence 或相同 offset 的事件重放不会重复文本。

#### 12.4.2 事件归并算法

```text
收到事件 E：
1. 若 E.sequence <= lastSequence 且该事件已被应用，忽略；否则继续。
2. answer_started：清空该次运行的临时 answerText，answerStreaming = true。
3. answer_delta：依据 offset 合并文本；更新 answerText、lastSequence、answerStreaming = true。
4. answer_completed：以 payload.text 覆盖/校正 answerText；result.final_answer 同步该文本；answerStreaming = false。
5. run_succeeded：
   a. 若 payload.final_answer 是非空字符串，则以其作为 answerText 和 result.final_answer；
   b. 否则保留已累计 answerText；
   c. status = succeeded，answerStreaming = false；
   d. 只有处理完 payload 后才能关闭 EventSource。
6. run_failed：status = failed，answerStreaming = false，保留已显示的增量文本及错误信息。
```

Reducer 不负责展示动画。`useTypingText` 若仍需保留，只能对已经接收到的文本做可选视觉效果，且不得延迟或遮蔽真实 `answer_delta` 的到达；默认应直接渲染网络增量。

#### 12.4.3 HTTP 初始加载与 SSE 并发

进入会话页面时可能同时发生 Run HTTP 查询和 SSE 回放。采用“sequence 更大者覆盖”规则：HTTP 返回的 `result.final_answer` 是快照，不得用旧快照覆盖已经处理的更高序号 SSE 增量；SSE 终态中的非空 `final_answer` 则可覆盖临时文本。页面卸载、Run 切换和组件重渲染必须关闭旧的 `EventSource`，避免跨 Run 串流。

### 12.5 逐文件改动清单

以下是实施时应检查和修改的文件边界。实际新增测试文件的命名遵循现有测试目录规范。

| 文件 | 改动 | 完成判定 |
|---|---|---|
| `frontend/src/components/layout/dashboard-shell.tsx` | 为 Shell、Sider、主内容建立可收缩的高度/宽度边界。 | 页面在目标视口无全页纵向滚动。 |
| `frontend/src/components/layout/app-sidebar.tsx` | 拆分 Header、Sessions、Footer 三个语义区；管理入口和账户移入 Footer。 | Footer 不随 Session 数量移动。 |
| `frontend/src/components/agent/session-sidebar-list.tsx` | 只负责列表滚动、虚空态和紧凑行渲染；标题单行截断。 | 100+ 会话不遮挡 Footer，长标题不溢出。 |
| `frontend/src/app/globals.css` | 增加根节点、Shell 和滚动条样式；避免全局规则破坏 Agent 页面。 | 高度链经浏览器检查成立。 |
| `frontend/src/app/agent-globals.css` | 调整 Session 行高、间距、激活态、焦点态和移动端抽屉规则。 | 与目标截图的密度一致，键盘焦点清晰。 |
| `frontend/src/lib/run-stream-reducer.ts` | 按 12.4 实现事件幂等归并，特别处理 `run_succeeded.final_answer`。 | 仅成功终态也能得到最终答案。 |
| `frontend/src/hooks/use-run-event-stream.ts` | 管理 EventSource 生命周期、Last-Event-ID、重连和诊断回调。 | 重连不重复文本，切换会话不串流。 |
| `frontend/src/components/agent/final-answer-panel.tsx` | 优先显示归并后的 `answerText/result.final_answer`，区分加载、空结果、失败。 | 成功 Run 不再显示“无最终答案”。 |
| `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx` | 合并 HTTP 快照与流状态，避免旧请求覆盖新 Run。 | 刷新和直接访问历史会话均可显示答案。 |
| `backend/app/models/...`（实际 AgentRun 模型文件） | 增加 `result` JSONB 映射和类型。 | ORM 读写与迁移一致。 |
| `backend/alembic/versions/...` | 新增可回滚的 `result` 字段迁移。 | 升级/降级在空库和已有数据上通过。 |
| `backend/app/services/agent/loop.py` | 每个 chunk 写 `answer_delta`；成功事务原子写结果和 `run_succeeded`。 | 数据库事件按序可回放。 |
| `backend/app/api/agent_stream.py` | SSE 回放、实时推送、心跳、无缓冲响应头和断线续传。 | `curl -N` 或浏览器 Network 可见多次分段到达。 |
| `backend/app/api/agent.py` | Run 查询优先读取 `result`，清除静默吞错，保留受控事件回退与日志。 | 成功 Run HTTP 响应稳定包含答案。 |
| `backend/app/services/...`（历史上下文构建） | 识别 `run_succeeded` 和 `result.final_answer`，兼容旧事件。 | 多轮 Agent 可读取前一轮答案。 |

### 12.6 自动化测试用例规格

#### 12.6.1 前端单元与组件测试

| ID | 前置条件 | 操作 | 预期 |
|---|---|---|---|
| FE-R-01 | 新建 running Run | 依序 dispatch `answer_started`、3 个 `answer_delta` | 每个 delta 到达即增长文本，状态仍为 `running`。 |
| FE-R-02 | 无 delta | 仅 dispatch 含 `final_answer` 的 `run_succeeded` | 页面显示该答案，状态为 `succeeded`。 |
| FE-R-03 | 已收到 delta | dispatch `answer_completed` 后再 dispatch `run_succeeded` | 文本完整、不重复，终态答案与完成答案一致。 |
| FE-R-04 | 已处理 sequence 10 | 重放 sequence 10 | 文本和状态不变化。 |
| FE-R-05 | 会话 A 正在流 | 切换到会话 B | A 的 EventSource 关闭，后续 A 事件不写入 B。 |
| FE-L-01 | 100 条会话、720px 高度 | 渲染 Sidebar | Footer 可见，Session 容器可滚动，页面主体不出现额外滚动。 |
| FE-L-02 | 超长会话标题 | 渲染 Session 行 | 标题省略、不撑宽、Tooltip/`title` 可获取完整文字。 |
| FE-L-03 | 键盘操作 | Tab 聚焦导航项和会话操作 | 焦点可见，图标按钮有可访问名称。 |

#### 12.6.2 后端 API、数据库和 SSE 测试

| ID | 前置条件 | 操作 | 预期 |
|---|---|---|---|
| BE-D-01 | 成功 Run | 执行终态写入 | `status`、`result`、终态事件同事务可见。 |
| BE-D-02 | `result` 为空的历史 Run | 执行回填两次 | 首次补齐，第二次无重复更新；无法补齐的记录被报告。 |
| BE-A-01 | `result.final_answer` 存在 | GET Run | 返回稳定的完整答案，不依赖扫描事件。 |
| BE-A-02 | 无 `result`，有历史事件 | GET Run | 按规定回退返回，并输出受控日志。 |
| BE-S-01 | Worker 分 3 次生成 | 订阅 SSE | 客户端在终态前收到 3 条不同 sequence 的 `answer_delta`。 |
| BE-S-02 | 客户端于 sequence 2 断开 | 带 `Last-Event-ID: 2` 重连 | 只回放 sequence > 2 的事件，顺序正确。 |
| BE-S-03 | 代理模拟无缓冲 | 检查响应与时间戳 | `X-Accel-Buffering: no` 存在，首 delta 未等待终态。 |
| BE-H-01 | 两轮成功对话 | 构建下一轮上下文 | 能读取前一轮 `result.final_answer` 或兼容事件答案。 |

#### 12.6.3 真实浏览器验收脚本

1. 使用一个输出时间至少持续 5 秒的测试 Agent 任务，打开浏览器 Network 面板并保留时间列。
2. 发送任务，记录 `answer_started`、每条 `answer_delta`、`answer_completed`、`run_succeeded` 的到达时间和 sequence。
3. 在第二条 delta 后主动断网 3 秒，再恢复网络；确认恢复后文字不丢失、不重复，且最终答案正确。
4. 在成功后刷新页面和直接复制会话 URL 重新访问；两种方式均显示相同最终答案。
5. 分别在 `1280x720`、`1440x900` 和移动模拟视口下创建 100 条会话，滚动 Session 区并确认底部菜单与账户始终可访问。
6. 归档桌面/移动截图、Network 导出文件、Run ID、测试时间和构建版本号。

### 12.7 非功能要求与监控

| 类别 | 指标/约束 | 目标 |
|---|---|---|
| 流式时延 | Worker 写入 delta 到浏览器收到 delta 的 P95 | 开发/测试环境小于 2 秒；生产以代理链路实测制定阈值。 |
| 结果完整性 | `succeeded` Run 但 `result.final_answer` 为空的比例 | 0；出现即告警。 |
| 重连正确性 | 重连后重复文本或缺失文本 | 0，按 E2E 和采样日志验证。 |
| 可访问性 | 侧栏导航和图标按钮 | 满足键盘操作、语义标签与可见焦点。 |
| 权限 | 管理入口 | 保持既有 RBAC 判定，视觉重构不提升任何用户权限。 |
| 安全 | 日志与 SSE | 日志不记录完整敏感答案；SSE 继续校验当前用户对 Session/Run 的访问权。 |

### 12.8 实施顺序、代码评审关口与交付物

1. **建立复现证据**：录制当前浏览器 Network 时序，确认是 Worker 未分块、SSE 被缓冲还是前端归并丢失。
2. **先补测试再改协议**：合入 FE-R-02、FE-R-03、BE-A-01、BE-S-01 的失败用例，锁定本次缺陷。
3. **后端先行**：迁移、结果原子写入、HTTP 读取和 SSE 回放完成后，提供事件样本和迁移验证记录。
4. **前端状态修复**：Reducer/Hook/最终答案面板按契约消费事件；通过单测与真实 SSE 测试。
5. **再做视觉结构**：侧栏三区布局、紧凑 Session 行、断点与无障碍测试独立提交，避免与流式故障混在同一难以回滚的变更中。
6. **端到端验收和灰度**：执行 12.6.3，发布后观察 12.7 指标；只有结果完整性为零异常才关闭 P0。

每个合并请求至少附带：改动文件清单、关联测试 ID、桌面或接口证据、迁移影响说明和回滚方式。涉及事件契约或数据库字段的合并请求，必须由前后端各一名工程师共同评审。
