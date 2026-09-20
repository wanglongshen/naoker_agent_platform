# DSH 侧栏合并设计（脑壳工作台 × DeepSeekHarness）

- 日期：2026-09-12
- 状态：设计已获用户逐节确认（v1-v5 视觉稿：`.superpowers/brainstorm/ui-merge-01/content/`）
- 范围：`/agent` 工作台与全局侧栏的导航合并（前端为主 + 一个 DSH 客户端插件）

## 1. 背景与目标

**现状问题**：`/agent` 页面同时存在两套左侧导航——平台侧栏（橙色，含旧自研会话列表）与 iframe 内 DSH 原生侧栏（含真实 DSH 会话）；会话数据也是两份（旧自研会话 vs DSH 会话）。

**目标**（用户拍板，方案一「完全合并」）：
1. 平台侧栏成为唯一导航（品牌、新会话、工作区/会话、平台菜单、账号）。
2. DSH 原生侧栏由新增的 client 插件隐藏，但**它具备的全部功能在合并侧栏的对应位置保留**，行为与 DSH 原生一致。
3. 视觉 100% 走平台设计语言（橙色体系，与平台其它页面一致）。

**关键事实**（调研证据见 `dsh-platform/NOTES.md` 与本次调研）：
- DSH 侧栏是插件（`@deepseek-ai/dsh-client-ui-sidebar` 外壳 + `@deepseek-ai/dsh-client-ui-workspace` 会话浏览器），无配置可隐藏；但官方 slot 机制允许注册 client 插件接管 `sidebar` 槽。
- DSH **无会话深链**（无 URL 路由），会话切换只存在于前端内存 → 必须用 postMessage 桥。
- DSH 品牌槽（`sidebar.brand.mark/name`）可替换；皮肤机制可做 DOM/CSS 覆盖。
- DSH 无 iframe embed 参数 → 隐藏原生侧栏由我方插件负责。
- 会话/工作区数据：DSH HTTP JSON-RPC `POST /api/session.list`、`POST /api/workspace.list`（同机调用过 Host 信任栅栏即可）。

## 2. 最终结构（冻结）

唯一侧栏自上而下：

| # | 区块 | 内容 |
|---|---|---|
| ① | 品牌区 | 脑壳工作台（脑 logo + AGENT WORKSPACE）+ 折叠按钮（收成 56px 图标轨） |
| ② | 新会话 | 主按钮（白底橙字），桥接 DSH 原生新建 |
| ③ | 工作区区 | 区头：`工作区` + 🔍搜索 + ⚙过滤 + ＋新建工作区（三个动作全部保留，走 DSH 原生）；下方工作区分组列表（图标+名称，可展开/折叠），展开后显示会话（标题 + 相对时间，如 `10天`），运行中会话带绿点 |
| ④ | 平台功能菜单 | 我的文件 / 账户 / 对话审计 / 文件管理 / 用户管理 / 角色管理 / **DSH 设置**（在角色管理下面，右侧小字"模型·皮肤·工作区"） |
| ⑤ | 账号区 | 头像、姓名、@用户名、角色徽章、退出 |

DSH 对话区（iframe）只保留会话内容 + 顶栏，原生侧栏隐藏。现有 `/agent` 顶部状态条（运行中/端口/重建/打开原版）保留不变。

## 3. 功能映射表（DSH 原生 → 合并后）

| DSH 原生侧栏功能 | 合并后位置 | 实现机制 |
|---|---|---|
| 品牌 + 折叠按钮 | ① 品牌区 | 平台组件；折叠 = 侧栏收成图标轨 |
| ⊕ 新会话 | ② 新会话 | 桥 `new-session` |
| 工作区列表（分组/展开折叠） | ③ 工作区区 | 插件推送 `workspace.list` + 各工作区会话 |
| 🔍 搜索 | ③ 区头 | 桥 `search-sessions`（DSH 原生搜索） |
| ⚙ 过滤/排序 | ③ 区头 | 桥 `open-filter`（DSH 原生面板） |
| ＋ 新建工作区 | ③ 区头 | 桥 `add-workspace`（DSH 原生选择器；**完全按 DSH 原生方式保留**） |
| 会话点击切换 / 相对时间 | ③ 列表项 | 桥 `select-session`；时间由推送数据渲染 |
| ⚙ 设置 | ④ DSH 设置 | 桥 `open-settings` → 打开原生设置面板 |
| 平台新增 | ④ 平台菜单 ⑤ 账号区 | 平台原生（现状保留） |

## 4. 交互与状态（冻结）

**五种状态**（视觉稿 states-v5）：
- A 实例启动中：侧栏加载态 + "正在启动 DSH 实例…（首次约 5-20 秒）"
- B 实例异常/已停止：红色提示条 + 原因 + 「重新启动」按钮；上次同步的工作区/会话灰显保留
- C 空状态：无会话引导（"点上方 + 新会话"）
- D 连接断开：黄条"与 DSH 的连接断开，正在自动重连…（第 N 次）"，列表保持可见
- E 正常态：实时同步标识 + 运行中会话绿点

**交互规则**：
| 操作 | 行为 |
|---|---|
| 点工作区行 | 展开/折叠（同 DSH） |
| 点会话行 | 右侧立即切换；当前项高亮；**自动记忆**（下次进入自动恢复） |
| + 新会话 | 在当前展开的工作区新建；无则用默认工作区（DSH 原生规则） |
| 🔍 搜索 | 侧栏内展开搜索框，实时过滤工作区/会话 |
| ⚙ 过滤 / ＋ 新建工作区 | 打开 DSH 原生面板/弹窗（与 DSH 完全一致） |
| ⚙ DSH 设置 | 右侧打开 DSH 设置面板（模型/皮肤/工作区），侧栏保持 |
| 折叠按钮 | 侧栏收成 56px 图标轨，再点展开 |
| 刷新/重进页面 | 自动恢复上次选中会话 |
| 实例被空闲回收后再进入 | 自动重新拉起（状态 A）→ 会话列表与选中态恢复（数据在实例 home，不丢） |

## 5. 技术设计

### 5.1 架构与数据流

```
平台页面 (/agent)                         DSH 实例（iframe）
┌───────────────────────┐   postMessage  ┌────────────────────────┐
│ AppSidebar            │ ──命令────────▶ │ client 插件            │
│  ├ 品牌/新会话/工作区  │ ◀─状态/事件──── │  ├ 隐藏原生侧栏        │
│  ├ 平台菜单/账号       │                │  ├ 执行命令(原生API)   │
│  └ useDshBridge()     │                │  └ 拉取+订阅会话数据   │
└───────────────────────┘                └────────────────────────┘
        │                                        │ HTTP JSON-RPC
        │ 其余页面用平台菜单                       ▼
        │                                /api/session.list, /api/workspace.list
```

### 5.2 DSH 侧 client 插件（新增）

- 位置：扩展现有插件包 `dsh-platform/packages/server-connector`，新增 `dsh.client`（platform=web）+ `./client` 入口（与皮肤包同款 `dsh: { client: { platform: "web" } }`）。
- 职责：
  1. **隐藏原生侧栏**：优先注册 `sidebar` 槽的空替换（slot 机制"registering here replaces the navigation column outright"）；若空替换不可行，回退 CSS 隐藏（`[class*='sidebarCol']`，皮肤同款稳定钩子），实现时以 spike 结论为准。
  2. **桥接命令**：监听 `window.message`（校验 `event.source === window.parent`），执行 `new-session` / `select-session` / `search-sessions` / `open-filter` / `add-workspace` / `open-settings`。
  3. **推送状态**：`ready`（桥就绪，附当前选中会话 id）、`workspaces`（工作区+会话+相对时间+运行中标记）、`session-changed`（用户直接在 DSH 内切换时同步给平台）、`connection`（重连状态）。
- 数据获取：插件内 `fetch('/api/session.list')`、`fetch('/api/workspace.list')`（JSON-RPC 信封，同源、loopback 过栅栏）；变更订阅优先用 DSH 客户端事件，回退 5s 轮询（与平台现有轮询风格一致）。
- 命令执行依赖 DSH 客户端内部 API（选中/新建会话、打开设置/过滤/搜索面板）——**列入实施前 spike**（见 §9）。

### 5.3 Bridge 协议（postMessage）

- 平台 → DSH（命令）：`{ v: 1, type: "cmd", action: "new-session" | "select-session" | "search-sessions" | "open-filter" | "add-workspace" | "open-settings", payload?: { sessionId?: string, query?: string } }`
- DSH → 平台（状态/事件）：`{ v: 1, type: "state", event: "ready" | "workspaces" | "session-changed" | "connection", payload }`
- 安全：平台侧校验 `event.source === iframe.contentWindow`；插件侧校验 `event.source === window.parent` 且 `event.data.v === 1`。消息不含任何平台令牌；会话标题本身会展示在平台上，无额外泄露。
- 版本号 `v:1` 用于未来协议演进。

### 5.4 平台侧改动（frontend）

- `AppSidebar` 重构：
  - `/agent*` 路由：③ 区渲染 DSH 工作区/会话（`useDshBridge` 提供实时状态）；旧自研会话列表仅保留在 `/agent/legacy*` 路由（回退通道不受影响）。
  - 其它路由：不渲染会话区（侧栏 = 品牌 + 平台菜单 + 账号），消除旧会话列表与新设计的双份数据。
- 平台级深链：`/agent?session=<dshSessionId>` —— 进入页面、桥 `ready` 后自动 `select-session`；在 `/agent` 内点击会话时用 `history.replaceState` 更新 URL。其它页面点会话 = 跳 `/agent?session=...`（解决了 DSH 无深链问题，完全在平台路由层实现）。
- 新增单元测试：bridge hook（postMessage 收发/校验）、③ 区渲染（工作区分组/展开/绿点/空态/断线态）、深链恢复。

### 5.5 与既有机制的关系

| 既有机制 | 处理 |
|---|---|
| `dsh_sessions` 同步表 + `dsh_sync_worker` | 保留（审计用），不作为侧栏数据源 |
| `/agent` 顶部状态条（运行中/重建/打开原版） | 保留不变 |
| `/agent/legacy` + 平台会话列表 | 保留（仅 legacy 路由显示列表） |
| 反代 `/api/dsh-proxy/*` | 保留（生产 vhost 方案另行推进，本期不依赖） |
| `dsh-platform/skills-template`、connector 工具 | 不变 |

### 5.6 视觉规范

- 侧栏：平台橙色渐变（`#FF8A3D → #F2620F`）；文字白色系（`#FFF` / `rgba(255,255,255,.75)`）。
- 会话项：默认透明；悬停 `rgba(255,255,255,.12)`；选中 `rgba(255,255,255,.22)` + 左侧 3px 白条 + 加粗。
- 工作区项：`rgba(255,255,255,.18)` 圆角底；子会话列表左侧虚线导引线（`rgba(255,255,255,.45)` 虚线）。
- 新会话按钮：白底、`#E85D04` 字、圆角 10px。
- 状态色：运行中绿点 `#7CFFB2`；异常条 `#7F1D1D` 底 + `#FCA5A5` 边；重连条 `#92400E` 底 + `#FCD34D` 边。
- 间距/字号：侧栏宽 262px（折叠 56px）；列表行高约 30px；标题 12-13px、元信息 10px。

## 6. 验收标准

**自动化**：
- 前端单测全绿：bridge hook、侧栏 ③ 区各状态、深链 `?session=` 恢复、legacy 路由仍显示旧列表。
- connector 包构建通过（server + client 双入口）。

**手测（真实实例）**：
1. 进入 `/agent`：只有一个侧栏（DSH 原生侧栏不可见），品牌为脑壳工作台。
2. ③ 区显示真实工作区（HC_ZiChan、01_agent_loop_pro 等）与会话（标题+相对时间），与 DSH 原版一致。
3. 点会话 → 右侧立即切换；绿点运行态正确。
4. + 新会话 / 搜索 / 过滤 / ＋新建工作区 / DSH 设置 → 全部可用且与 DSH 原生行为一致。
5. 刷新页面 → 自动恢复上次会话；点「重建」→ 状态 A→E 流转，会话不丢。
6. `/agent/legacy` → 旧界面与旧会话列表正常（回退通道）。
7. 其它页面（如 /users）侧栏无会话区、功能菜单正常。
8. 视觉与平台设计语言一致（对照 states-v5 / layout-merge-v4 视觉稿）。

## 7. 边界与非目标

- 本期不改 DSH 服务端插件（connector 的 server 侧不动），只新增 client 入口。
- 不做平台侧会话管理（重命名/删除/置顶）——后续可基于桥扩展。
- 不做生产 per-user 虚拟主机（沿用现 iframe 直连实例端口方案）。
- 旧自研会话体系不迁移、不删除（legacy 保留）。

## 8. 风险与生产待办

| 风险/待办 | 说明 |
|---|---|
| DSH 客户端内部 API 稳定性 | 命令执行依赖 DSH 内部 API（选中/新建/设置），升级 DSH 可能破坏 → 锁定 vendored 版本 + 回归清单（沿既有 SOP） |
| ＋ 新建工作区暴露服务器目录 | 本机开发无风险；生产多用户需加白名单/权限（**记录为生产待办**） |
| 原生侧栏隐藏方式 | slot 空替换 vs CSS 隐藏，以 spike 结论为准；CSS 回退需验证无残留空白列 |
| 桥接断线体验 | 插件与平台各自重连；以状态 D 呈现 |

## 9. 实施前技术验证点（spikes，先于编码）

1. **会话选中/新建/设置打开的客户端 API**：在 vendored 源码 + 已装插件中定位 ui-workspace / ui-sidebar 调用链（选中会话、创建会话、打开设置/过滤/搜索面板的确切服务与调用方式）。
2. **sidebar 槽空替换可行性**：验证 client 插件注册 `sidebar` 槽为空组件是否干净移除原生侧栏（含 56px 折叠残留），否则确定 CSS 隐藏方案与选择器。
3. **client 入口打包**：`@naoker/dsh-platform-connector` 增加 `dsh.client` 入口后的构建产物与 `dsh plugin` 安装/加载验证。
4. **会话标题与工作区归属的获取路径**：`session.list` 的 `SessionSummary` 是否直接含标题/工作区（projections 字段），还是需组合 `session.history`/`workspace.list`；确定插件推送数据的最小调用集。
