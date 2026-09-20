# 超级管理员文件管理页：查看全部用户文件 设计

**日期:** 2026-08-04
**状态:** 已确认设计（方案 A）

## 1. 背景与目标

超级管理员的文件管理页面应能看到**所有人的文件夹和文件**，但当前前端管理页（`adminView=true`）仍请求 owner 过滤的 `/api/files` 与 `/api/files/folders`，只显示管理员自己的文件。

**已确认需求：**
- 超管文件管理页能看到所有用户的文件夹和文件（按用户分组树导航）
- **仅查看**：不能删除/重命名/移动他人的文件；操作仍仅限自己的文件
- 进入页面默认显示管理员自己的文件（与现状一致）
- 文件归属通过导航结构体现（用户名分组），文件列表不加"所属者"列

## 2. 现状（已核实）

| 项 | 现状 |
|---|---|
| `GET /api/files` | owner 过滤，仅当前用户自己的文件 |
| `GET /api/files/admin`（require_super_admin） | 全部用户文件；参数 user_id/keyword/page/page_size；**缺 folder_id、media_type** |
| `GET /api/files/folders` | `get_folder_tree(current_user.id)`，仅自己的文件夹树；**无超管全量树端点** |
| `GET /api/users`（require_permissions("user:read")） | 用户列表，可作树顶层分组数据 |
| 下载/预览 `_check_file_access` | 已允许超管访问任意文件（下载/预览可用） |
| 删除/重命名/移动 `_check_file_owner` | 仅 owner，超管改他人文件 403（保持） |

## 3. 方案（方案 A）

### 3.1 后端

**新增 `GET /api/files/folders/admin`**（require_super_admin）：
- 返回"用户分组树"：`[{user_id, username, display_name, folders: [FileFolderNode...]}]`
- 用户列表只含**有文件或文件夹的用户**（排除空用户），无文件/文件夹的用户不出现
- folders 为该用户的完整文件夹层级（复用 `get_folder_tree` 的树构建逻辑，按 owner 分组）
- 管理员自己排在最前（便于前端默认选中自己）

**修改 `GET /api/files/admin`**：
- 参数增加 `folder_id: uuid.UUID | None = Query(None)`、`media_type: str | None = Query(None)`
- `get_admin_all_files` 相应增加 `folder_id`、`media_type` 过滤（复用 `list_files` 的过滤模式）

**不变**：`_check_file_owner`、`_check_folder_owner`（操作仍限 owner）；`list_files`、`list_folders` 普通端点；下载/预览的超管放行逻辑。

### 3.2 前端

`frontend/src/components/files/file-management.tsx` + `folder-tree.tsx`：

- **树数据源**：admin 模式下请求 `/api/files/folders/admin`；普通模式不变（`/api/files/folders`）
- **树结构**：顶层节点 = 用户名（显示名，不可操作——无重命名/删除图标），子节点 = 该用户文件夹层级；树根 label = "全部用户"
- **选中语义**（admin 模式）：
  - 用户根节点 → `GET /api/files/admin?user_id=<uid>`（该用户全部文件，跨文件夹）
  - 用户下文件夹 → `GET /api/files/admin?user_id=<uid>&folder_id=<fid>`
  - 默认选中"自己"的用户根节点 → 初始显示管理员自己的文件（与现状一致）
- **文件列表请求**：admin 模式请求 `/api/files/admin?user_id=&folder_id=&keyword=&media_type=&page=&page_size=`
- **操作可见性**（admin 模式）：
  - 选中自己：上传/新建文件夹/重命名/移动/删除/批量删除可见可操作（现状）
  - 选中他人：上述操作全部隐藏，列表只读；预览/下载保留
- **FolderTree 组件**：扩展支持 admin 树数据形态（用户分组节点），普通视图行为不变

### 3.3 数据流

```
管理页(adminView) → folders/admin → 用户分组树（自己排最前）
选中用户根 → files/admin?user_id=U → 该用户全部文件
选中文件夹 → files/admin?user_id=U&folder_id=F → 该文件夹内文件
（keyword/media_type 过滤随列表请求透传）
```

## 4. 错误处理与边界

- 非超管访问 `folders/admin` → 403（require_super_admin 已有模式）
- 树内用户"有文件或文件夹"判定：`EXISTS(FileFolder WHERE owner=U) OR EXISTS(FileObject WHERE owner=U)`，两表均排除 `is_deleted`
- admin 模式下树加载失败 → 静默降级（沿用现状树加载失败静默），列表请求失败 → 现有错误 Alert + 重试
- 分页：admin 列表沿用现有分页（page/page_size，page_size 上限 100）

## 5. 改动范围

**新增：** 无新文件

**修改：**
- `backend/app/api/files.py`：`/folders/admin` 端点；`list_all_files` 加 folder_id/media_type
- `backend/app/repositories/file_repository.py`：`get_admin_all_files` 加过滤；新增 `get_admin_user_folder_trees()`（分组树查询）
- `backend/app/schemas/file.py`：新增 admin 分组树响应 schema（用户分组 + 文件夹树）
- `frontend/src/components/files/file-management.tsx`：admin 模式数据源/选中语义/操作可见性
- `frontend/src/components/files/folder-tree.tsx`：admin 分组树渲染
- `backend/tests/`（file API 测试）：`folders/admin` 权限与结构、admin 列表 folder_id/media_type 过滤
- `frontend/src/components/files/file-management.test.tsx`（如存在）或新建：admin 模式行为测试

**不变：** 普通用户文件页、上传/移动/重命名/删除端点、下载/预览、权限模型

## 6. 测试策略

- **后端**：非超管调 `folders/admin` → 403；超管 → 分组树含正确用户与层级；空用户不出现在树中；`files/admin?folder_id=` 与 `media_type=` 过滤正确；既有测试不回归
- **前端**：admin 模式树渲染（用户分组节点）；选中他人时操作按钮隐藏、选中自己时可见；请求 URL 参数正确（user_id/folder_id 传递）；普通视图行为不回归
- **手动**：admin 登录 → 文件页 → 树显示所有用户 → 点他人用户看其文件 → 无操作按钮 → 点自己 → 操作正常

## 7. YAGNI（不做）

- 不做"所属者"列（结构已体现归属）
- 不做超管对他人文件的管理操作（仅查看是明确需求）
- 不做树内用户搜索/折叠状态持久化
- 不改动权限模型（复用 file:admin_view + require_super_admin）
