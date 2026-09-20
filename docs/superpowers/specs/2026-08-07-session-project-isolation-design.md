# 会话项目隔离（Agent 工作区） Design Spec

**Status:** Draft
**Date:** 2026-08-07

## 1. 需求（用户确认）

**项目隔离的真实含义**：对话绑定"项目"（= 文件库顶层文件夹）后：
1. Agent 与 LLM 对话只读取**当前项目**内的信息，不会读其他项目的文件
2. 生成的文件落在当前项目内，不会搞错项目
3. 跨项目访问需**明确授权**（用户在前端切换会话项目 = 授权动作）

已确认决策：
- **会话内可切换**：新建会话可选项目；会话内随时切换（切换后范围变，正在跑的 run 不受影响——run 启动时快照）
- **跨项目访问需明确授权**：工具命中项目外文件 → 返回观察错误提示切换项目，不返回内容
- **允许不绑定**：不选项目 = 现状全局行为，老会话零影响
- 参考模型：Codex 会话绑定工作目录；不做成员/权限制（个人工作区模型）

## 2. 数据模型

### 2.1 AgentSession 加一列（可空、可改）

```
project_folder_id  uuid NULL  FK file_folders.id
```

含义：该会话当前绑定的项目（顶层文件夹）。NULL = 未绑定（全局）。**无新表**。

### 2.2 AgentRun 加一列（run 启动快照）

```
project_folder_id  uuid NULL
```

`create_run`/`retry` 时从会话当前值拷贝——run 中途会话切换项目不影响已开始 run；审计可查每个 run 在哪个项目执行。

### 2.3 迁移

手写迁移（续当前 head）：`agent_sessions.project_folder_id` + `agent_runs.project_folder_id` 两列（FK 不强制——文件库文件夹可被软删，避免 FK 阻塞；查询时校验存在性）。

## 3. 后端

### 3.1 会话 API

| 端点 | 说明 |
|---|---|
| `POST /api/agent/sessions` | schema 加可选 `project_folder_id`——校验：文件夹属于当前用户且 `parent_id IS NULL`（顶层） |
| `PUT /api/agent/sessions/{id}/project` | `{project_folder_id: uuid\|null}` 切换/解绑；校验同上；401/404 非本人会话 |

（session 列表响应加 `project_folder_id` 字段，供前端显示。）

### 3.2 run 快照

`create_run`（agent.py:228）与 `retry`（agent.py:475）：INSERT AgentRun 时填 `project_folder_id = session.project_folder_id`。

### 3.3 FileRepository 新增（子树检索）

```python
async def get_folder_subtree_ids(self, folder_id: uuid.UUID) -> list[uuid.UUID]
# 含自身；BFS 沿 parent_id 收集全部子孙 folder id（is_deleted=False）
# FileFolder 表结构：id/parent_id/owner_user_id（核实字段名）

async def search_by_folder_ids(self, folder_ids: list[uuid.UUID], keyword: str) -> list[FileObject]
# FileObject.folder_id IN folder_ids AND is_deleted=False AND original_filename ILIKE %keyword%
# （folder_id IS NULL 的文件不属于任何项目——项目隔离下排除）

async def get_by_folder_ids(self, folder_ids: list[uuid.UUID], filename: str) -> FileObject | None
# 精确名 + IN folder_ids
```

### 3.4 tool_executor 项目范围

`execute(action, owner_user_id, project_folder_id=None, ...)` 加参数；loop 调用处传 `ctx.run.project_folder_id`（核实 loop 调 execute 的位置，owner_user_id 传法同源）。

**文件类工具隔离逻辑**（read_file / list_files / write_file / edit_file）：

1. `project_folder_id` 为 None → 现状逻辑不变（全局）
2. 绑定项目时：
   - 先取 `subtree_ids = get_folder_subtree_ids(project_folder_id)`（进程内短缓存：dict[folder_id] → (fingerprint, ids)，防每次工具调用重复 BFS）
   - **read_file**：路径含 `/` → 段[0] 是文件夹名——限定在 subtree 内 `find_folder_by_name` 变体（新建 `find_folder_in_tree(subtree_ids, name)`：folder.id IN subtree_ids AND name ILIKE）；无 `/` → `get_by_folder_ids(subtree_ids, filename)`（精确）→ 无精确匹配 → `search_by_folder_ids` 模糊
   - **list_files**：检索限定 subtree_ids
   - **write_file**：目标文件夹解析限定 subtree_ids；默认（未指定文件夹）→ 落在项目根（folder_id = project_folder_id）
   - **edit_file**：定位逻辑同 read_file
3. **跨项目命中**（绑定项目时匹配到 project_folder_id 树外的文件/文件夹）：**不返回内容**，返回工具观察错误：
   ```
   该文件属于其他项目（当前会话项目「X」）。如需访问，请在会话顶部切换到对应项目后重试。
   ```
   实现：子树限定后**根本不会命中**树外文件（检索范围已收窄）——跨项目"提示"仅在**用户显式请求**（如"读 B 项目的方案.md"）时由模型自然得到"未找到"结果 + 工具描述中注明范围。**补充**：tool 描述（planner 注入的 prompt）加一句"当前会话绑定项目「X」，文件操作仅限该项目"——让 LLM 知道边界。

### 3.5 无新工具 schema 改动

planner.py 工具描述维持；仅 `get_instruction`/prompt 注入处（loop.py 组装 messages 时）动态附加当前项目名提示（需查 session title？——取文件夹名 `get_folder(project_folder_id).name`——注入"当前项目：X，文件操作仅限该项目内"）。

## 4. 前端

### 4.1 会话页顶部项目选择器（[sessionId]/page.tsx）

- session 加载后：标题行右侧显示项目选择器（antd Select，可清空 = 不绑定）：
  - 选项 = 该用户顶层文件夹列表（复用文件页已用的接口——`GET /api/files/folders` 或 agent-api 的 listFolders；核实前端现有取文件夹列表函数）
  - 显示文件夹名；绑定后旁边显示项目名（如 `📁 项目名`）
- 切换 → `PUT /api/agent/sessions/{id}/project` → 成功后 message 提示 + 更新本地 session 状态（**不重新加载会话流**，仅显示变化）
- 切到已绑定项目时输入框/上下文提示"当前项目：X"

### 4.2 新建会话

- 新建会话入口（session-sidebar-list 的创建按钮）弹窗加可选"项目"下拉（同顶层文件夹列表）；不选 = 不绑定
- POST /sessions 带 project_folder_id

### 4.3 会话列表

- 会话侧边栏条目：绑定项目的会话显示小标签（项目名）——可选（低优先，好看为主）

## 5. 联动

- **generation_logs.folder_id**：绑定项目后 write_file 范围=项目树 → 产物自然在项目内 → generation 挂载 folder_id 自动正确（现有逻辑不动）
- **审计页**：run 详情可显示项目（AgentRun.project_folder_id → 文件夹名）——低优先，可后补

## 6. 失败与安全

- 切换校验：文件夹必须属于当前用户 + 顶层（parent_id IS NULL）；软删的文件夹拒绝
- 项目绑定不改变**权限模型**（仍是用户级 owner 隔离 + 超管读全）：隔离是**范围收窄**，不会放宽
- run 快照保证一致性；会话切换只影响后续新 run
- 检索范围收窄 = 跨项目文件**物理不可达**（查询条件层面），非提示层面

## 7. 测试

- repo：get_folder_subtree_ids（嵌套 3 层子孙、软删文件夹排除）、search_by_folder_ids/get_by_folder_ids（跨 folder 命中、folder_id NULL 排除）
- tool_executor：绑定项目 read 命中项目内文件 ✓；同文件名在项目外 → 读不到（返回 not found 观察）；write 默认落项目根；write 指定子文件夹（项目内）✓；指定项目外文件夹 → 拒绝观察；未绑定 → 全局现状（回归）
- API：创建会话带 project_folder_id（校验：他人文件夹 400/403、非顶层 400）；切换 PUT（成功/解绑 null/非法 400）；run 创建快照（会话项目 → run.project_folder_id）
- 前端：选择器渲染、切换调用、新建弹窗、未绑定默认
- 回归：既有文件工具测试（未绑定路径不变）

## 8. 明确不做

- 成员/权限制（owner/member）、跨用户项目共享、项目删除/转让
- run 中途动态改项目（快照模型）、会话项目历史记录
- 项目级计费/用量隔离
