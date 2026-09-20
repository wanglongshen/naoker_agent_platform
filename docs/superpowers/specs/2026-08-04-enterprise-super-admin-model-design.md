# 企业级超级管理员模型设计

**日期**：2026-08-04
**状态**：已批准（brainstorming 流程）

## 背景与目标

系统（企业智助 — 私有 AI 工作空间）当前对超级管理员（`super_admin`）角色的处理不完整：

- 前端"分配角色"列表把 `super_admin` 排除在外（`auth_service.get_assignable_roles`），超管角色**无法在 UI 中分配**给其他用户；
- 系统只有"最后一个超管不可删除"的保护（`LAST_SUPER_ADMIN`），初始引导账号（admin）本身可以被删除/禁用/降权；
- 没有"不能移除自己超管角色"的自保护。

目标：实现企业主流的"**引导账号 + 角色可分配**"模型：

1. 超管角色可以分配给其他用户（仅超管可分配）；
2. 内置初始账号（admin）**不可删除、不可禁用、不可移除超管角色**（完全保护）；
3. 任何人都**不能移除自己的超管角色**；
4. 至少保留一个活跃超管（既有保护保留为兜底）；
5. **不做**角色分配审计（明确非目标）。

## 现状核查

| 模型要求 | 当前现状 |
|---|---|
| 超管角色可分配给用户 | 后端 API 允许超管分配（`user_service.py:128,184` 有 is_super_admin 门控），但前端 `assignable_roles` 排除 super_admin（`auth_service.py:81`），UI 无法操作 |
| 内置 admin 不可删除 | 无——只有 LAST_SUPER_ADMIN 保护（`user_service.py:293-322`） |
| 不能移除自己的超管角色 | 无 |
| 至少一个活跃超管 | 已有（LAST_SUPER_ADMIN） |

## 方案：A1 动态角色列表 + 服务层保护

### 1. 数据模型

- `users` 表新增 `is_builtin` 布尔列：`NOT NULL DEFAULT false`
- `User` 模型新增字段：`is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)`
- 一个 alembic 迁移（`alembic revision`，手写内容，不使用 autogenerate——避免卷入既有模型/迁移漂移）
- `seed_rbac`（`app/db/seed.py`）幂等标记：每次启动时对 `username == settings.initial_admin_username` 的用户置 `is_builtin=True`（已部署环境的存量 admin 也会被标记，不依赖迁移猜用户名）

### 2. 服务层保护（`app/services/user_service.py`）

新增两个检查函数，按顺序调用：内置保护 → 自保护 → 既有 LAST_SUPER_ADMIN（保留）。

**`_check_builtin_protection(db, user)`**：目标用户 `is_builtin=True` 时抛 `ApiError(400, "BUILTIN_USER", "内置账号不可执行此操作")`。应用于：

- `delete_user`（删除内置账号 → 拒绝）
- `update_status`（内置账号从 active 改为其他状态 → 拒绝）
- `update_user`（内置账号的 `role_ids` 移除 super_admin → 拒绝）

**`_check_self_demotion(target_user, current_user, new_role_ids)`**：`target_user.id == current_user.id` 且当前用户持有 super_admin 角色且新 `role_ids` 不含 super_admin 时抛 `ApiError(400, "SELF_DEMOTION", "不能移除自己的超级管理员角色")`。应用于 `update_user`。

内置账号允许修改 display_name / email / phone（不改变身份标识）。

### 3. 角色分配列表（`app/services/auth_service.py`）

`get_assignable_roles(db, current_user)` 增加 `current_user` 参数：

- 当前用户是超管 → 返回全部活跃角色（**包含 super_admin**）；
- 非超管 → 返回活跃角色但**排除 super_admin**（与现状一致）。

调用处：`app/api/auth.py:55`（`/api/auth/me`）传入当前用户。`user_service` 的 is_super_admin 门控**保留**（纵深防御：绕过前端直接调 API 的非超管也无法分配超管角色）。

### 4. API 层

无新增端点。错误码沿用 `LAST_SUPER_ADMIN` 模式（错误码 + `Messages` 常量）。

### 5. 前端

- 用户列表接口响应新增 `is_builtin` 字段（`_serialize_user` 返回）；
- 用户管理页：`is_builtin=True` 的用户的"删除/禁用"按钮 **disabled**，tooltip/提示"内置账号不可删除/禁用"；其余操作（编辑资料、重置密码）正常；
- 角色分配下拉无需改动（由后端 `/api/auth/me` 的 assignable_roles 驱动）。

### 6. 测试

**后端：**

- 迁移/seed：`users.is_builtin` 列存在；seed 后 admin 用户 `is_builtin=True`；非内置用户为 False；
- `user_service`：
  - 删除内置 admin → 400 `BUILTIN_USER`
  - 禁用内置 admin → 400 `BUILTIN_USER`
  - 移除内置 admin 的超管角色 → 400 `BUILTIN_USER`
  - 超管移除自己的超管角色 → 400 `SELF_DEMOTION`
  - 非内置超管在活跃超管 ≥2 时可被删除 ✓
  - 删除最后一个超管 → 400 `LAST_SUPER_ADMIN`（既有行为不回归）
- `auth_service`：
  - 超管登录，`/api/auth/me` 的 assignable_roles 含 super_admin
  - 非超管登录，assignable_roles 不含 super_admin

**前端：**

- 用户管理页：内置账号"删除/禁用"按钮 disabled；非内置账号正常

## 数据流

前端操作（删除/禁用/改角色）→ `users.py` API → `user_service` 拦截检查（内置 → 自降权 → 最后超管）→ 拒绝（400 + 错误码）或放行；角色分配下拉数据来自 `/api/auth/me` 的动态列表。

## 非目标（明确不做）

- 超管角色分配/回收的审计日志
- 内置账号改名/改密码的额外限制（改密码允许；改名未限制，但保护按 `is_builtin` 标记而非用户名，不受影响）
- 双人复核（separation of duty）
