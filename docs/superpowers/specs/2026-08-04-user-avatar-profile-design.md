# 用户头像与个人资料页设计

日期：2026-08-04
状态：已批准

## 背景与目标

系统目前无任何头像数据：User 模型无头像字段，前端三处用户占位均为 `UserOutlined` 图标，没有"用户修改自己资料"的接口（只有管理员改用户的 `PUT /api/users/{id}`）。

目标：用户能设置自己的头像并维护个人资料（姓名/昵称、邮箱、手机号、密码），管理员可代改头像；导航栏与用户列表展示真实头像。

## 范围

- 新增头像存储与上传/读取/清除 API（本人 + 管理员代改）
- 新增 `PUT /api/users/me/profile`（本人改姓名/邮箱/手机号）
- 新增 `POST /api/users/me/password`（本人改密码，旧密码验证）
- 新增前端个人资料页 `/settings/profile`（头像 + 基本信息 + 修改密码三区块）
- app-header、app-sidebar 头像替换为真实头像；conversation-top-bar 保持不变
- 用户管理表格加头像列；编辑抽屉加头像上传/清除（管理员）
- 所有用户响应（/me、用户列表、用户详情）增加 `avatar_url` 字段

不包含：消息级头像（每条消息显示发送者头像）、头像裁剪/滤镜。

## 数据模型与存储

**User 模型**（`backend/app/models/rbac.py`）新增：

```python
avatar_path: Mapped[str | None] = mapped_column(String(512))
```

存相对路径，形式 `avatars/<user_id>.<ext>`。alembic 迁移（可空列，down_revision 取当前 head）。

**存储**：
- 根目录 `backend/var/avatars/`（与既有 `var/agent` 附件目录同一根）
- 文件名 `<user_id>.<ext>`，扩展名由服务端魔术字节嗅探结果决定，不信任上传文件名与 Content-Type
- 上传语义为覆盖：删除旧头像文件 → 写新文件 → 更新 `avatar_path`；写文件失败则不更新 DB
- 每个用户固定一个头像文件，无历史版本
- 用户删除为软删除（is_deleted），头像文件不立即清理（与现有数据保留策略一致，≤2MB/用户可接受）

**校验**（复用文件库 `_detect_mime_type` 模式）：
- 白名单：png / jpg / jpeg / gif / webp
- 大小上限：2MB
- 读前 4096 字节嗅探，命中即用检测结果，未命中拒绝

## 后端 API

**头像**（新文件 `backend/app/api/avatars.py`，`/api/avatars` 前缀）：

| 端点 | 方法 | 权限 | 说明 |
|---|---|---|---|
| `/api/avatars/me` | POST | 本人 | 上传头像（multipart 字段 `file`），返回 `{"avatar_url": "/api/avatars/<id>?v=<mtime>"}` |
| `/api/avatars/me` | DELETE | 本人 | 清除头像，返回 `{"avatar_url": null}` |
| `/api/avatars/{user_id}` | POST | user:update | 管理员代改头像 |
| `/api/avatars/{user_id}` | DELETE | user:update | 管理员代清除 |
| `/api/avatars/{user_id}` | GET | 任意登录用户 | 读取头像文件；目标用户已删除 → 404；无头像 → 404；带 Cache-Control 与 Content-Type |

`avatar_url` 带 `?v=<mtime>` 版本参数防浏览器缓存。

**个人资料**：`PUT /api/users/me/profile`
- body：`{ display_name?, email?, phone? }`，至少一项
- display_name 1-128 字符；email/phone 与既有规则一致，唯一性冲突 → 409
- 内置账号同样可改（既有保护只拦截删除/禁用/降权）
- 返回更新后的用户对象（含 avatar_url）

**修改密码**：`POST /api/users/me/password`
- body：`{ old_password, new_password }`
- 旧密码错误 → 401 `INVALID_PASSWORD`
- 新密码约束与既有创建/重置密码一致
- JWT 会话不强制失效（现有架构无失效列表，与现状一致）

**响应字段**：`/api/auth/me`、`/api/users` 列表、`/api/users/{id}` 的用户对象统一增加 `avatar_url`（`/api/avatars/<id>` 或 null），由 `_user_to_response` 统一补充。

## 前端

**个人资料页 `/settings/profile`**：
- 入口：app-header 右侧用户名/头像下拉菜单 → "个人资料"
- 三区块：
  1. 头像区：圆形预览（无头像显示 `UserOutlined`）、"上传头像"（文件选择，前端预校验类型/大小，以后端为准）、"移除头像"（有头像才显示）；上传后即时刷新
  2. 基本信息：姓名/昵称、邮箱、手机号表单 + 保存（`PUT /api/users/me/profile`）；成功提示、失败展示后端错误
  3. 修改密码：旧密码、新密码、确认新密码 + 提交（`POST /api/users/me/password`）；前端校验两次一致
- 布局沿用管理页风格（PageHeader + DataSurface），登录即可访问（挂现有守卫）

**导航头像**：
- `app-header.tsx`：用户名旁头像 → `avatar_url` 存在则 `<Avatar src>`，否则图标；下拉菜单加"个人资料"项
- `app-sidebar.tsx`：底部用户区头像 → 同样逻辑
- `conversation-top-bar.tsx`：保持不变

**用户管理**：
- 用户列表加头像列（`<Avatar src>`，无头像显示首字母），置于最前
- 编辑抽屉（user-drawer）加头像区块：管理员上传/清除（`POST/DELETE /api/avatars/{id}`）+ 预览

**类型与数据流**：
- `CurrentUser` / `UserListItem` 加 `avatar_url: string | null`
- 头像 URL 同源直连（cookie 鉴权），无需额外 token
- 变更后 `/me` 刷新（导航即时更新），列表重新拉取

## 安全与错误处理

- 上传双保险：Content-Type 白名单 + 魔术字节嗅探
- 路径安全：读取时 `Path.resolve()` 校验落在 `var/avatars/` 内，防目录穿越
- 权限矩阵见 API 表；写操作走现有 CSRF 机制（与 users.py 同模式；实现时核对前端 api 封装对 multipart 的 CSRF 头处理）
- 修改密码旧密码错误 → 401 `INVALID_PASSWORD`，错误提示不泄露账号状态差异
- 上传失败（类型/大小/格式）→ 400 中文错误（messages.py 模式）
- 写文件失败 → 500，DB 不更新
- 唯一性冲突 → 409；前端统一用 `api()` 封装 + `ApiError` 展示

## 测试

**后端**（新增 `tests/test_avatars_api.py` + 扩展 `tests/test_users_api.py`）：
- 上传：合法小 PNG 200；非白名单类型 400；超 2MB 400；伪造 Content-Type 但魔术字节不符 400；未登录 401
- 权限：普通用户对他人 POST/DELETE → 403；管理员代改成功
- 读取：无头像 404；有头像返回正确 Content-Type；已删除用户 404
- 资料：改 display_name/email/phone 成功；邮箱冲突 409；空 body 400
- 密码：旧密码错 401；改密后新密码可登录；内置账号改资料放行
- 清理：覆盖上传删除旧文件；清除后 avatar_url=null

**前端**（新增 `profile-page.test.tsx` + 扩展既有测试）：
- 资料页：三区块渲染；上传成功刷新预览；保存成功提示；密码不一致前端拦截
- app-header / app-sidebar：有 avatar_url 渲染 `<img>`，无则图标
- 用户管理：头像列渲染；编辑抽屉上传/清除流程

## 备注

- 头像目录与 `var/agent` 同根，无独立配置项；如需改路径，集中在一个常量
- 管理员代改与本人修改共用同一服务层函数，仅权限入口不同
