# 管理后台全量汉化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将权限管理后台、Swagger 和 API 用户提示统一汉化为正式企业中文，同时保持全部 API、RBAC 和数据库稳定标识不变。

**Architecture:** 前端新增集中中文词典 `copy.ts`，所有面向管理员的界面文本从该模块引用。后端新增集中消息常量 `messages.py`，服务层仅保留英文错误码并返回中文业务消息。基础种子和演示种子按稳定 `code` 同步角色和权限展示字段，不改变任何编码、关系或账号。

**Tech Stack:** Next.js 16, React 19, TypeScript, Vitest, FastAPI, Pydantic v2, SQLAlchemy 2 async ORM, PostgreSQL, pytest.

## 全局约束

- 仅汉化管理后台、浏览器元数据、数据库展示名称/说明、Swagger/OpenAPI 和 API 用户提示。
- 不引入 `next-intl`、语言切换、语言偏好或多语言路由。
- API 路径、JSON 字段、HTTP 状态码、错误码、权限码、角色编码、用户账号、邮箱、手机号、数据库 ID 和关联关系必须保持不变。
- `active`、`disabled` 继续作为 API 和数据库状态值；界面只显示“启用”“停用”。
- `super_admin`、`user_manager`、`role_manager`、`user:read`、`role:assign_permission` 等稳定标识不得翻译。
- 前端用户可见中文文案只能来自 `frontend/src/lib/copy.ts`；后端业务中文消息只能来自 `backend/app/core/messages.py`。
- API 返回的中文 `message` 直接展示；网络、非 JSON 或未知异常使用统一回退文案“请求失败，请稍后重试。”。
- 不创建 Alembic 迁移，不删除或重建当前数据库，不改变用户密码和用户角色关系。
- `seed_rbac()` 和 `seed_demo_data()` 必须可重复执行，按 `code` 同步展示字段，不产生重复记录。

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `frontend/src/lib/copy.ts` | 集中管理前端用户可见中文文案与状态标签 |
| `frontend/src/app/layout.tsx` | 中文浏览器标题、描述和页面语言 |
| `frontend/src/components/auth/login-form.tsx` | 中文登录表单和本地校验 |
| `frontend/src/components/layout/*.tsx` | 中文导航、面包屑、退出登录与移动端控件 |
| `frontend/src/components/users/*.tsx` | 中文用户筛选、表格、抽屉、确认弹窗和空状态 |
| `frontend/src/components/roles/*.tsx` | 中文角色管理、权限树和系统角色提示 |
| `backend/app/core/messages.py` | 集中管理 API 用户提示 |
| `backend/app/core/security.py` | 中文密码规则错误 |
| `backend/app/core/dependencies.py` | 中文认证和授权错误 |
| `backend/app/services/user_service.py` | 统一中文用户业务错误 |
| `backend/app/services/role_service.py` | 统一中文角色业务错误 |
| `backend/app/api/*.py` | 中文 FastAPI tags、摘要和描述 |
| `backend/app/main.py` | 中文 OpenAPI 应用元信息 |
| `backend/app/db/seed.py` | 基础角色/权限中文展示字段同步 |
| `backend/app/db/seed_demo_data.py` | 演示角色中文展示字段和执行输出同步 |
| `backend/tests/test_localization.py` | 后端中文消息、OpenAPI 和种子同步测试 |
| `frontend/src/lib/copy.test.ts` | 前端词典和状态映射测试 |
| `frontend/src/localization.test.ts` | 用户可见英文文案扫描测试 |

## Task 1: 建立前端中文词典与浏览器元数据

**文件：**
- 新建：`frontend/src/lib/copy.ts`
- 新建：`frontend/src/lib/copy.test.ts`
- 修改：`frontend/src/app/layout.tsx`
- 修改：`frontend/src/components/auth/login-form.tsx`

**接口：**
- 导出 `copy` 常量，包含 `app`、`navigation`、`common`、`user`、`role`、`auth`、`status` 分组。
- `copy.status.active === "启用"`，`copy.status.disabled === "停用"`。

- [ ] **步骤 1：编写失败的中文词典测试。**

创建 `frontend/src/lib/copy.test.ts`：

```ts
import { describe, expect, test } from "vitest";
import { copy } from "@/lib/copy";

describe("中文文案词典", () => {
  test("提供统一的系统标题和状态映射", () => {
    expect(copy.app.title).toBe("权限管理系统");
    expect(copy.status.active).toBe("启用");
    expect(copy.status.disabled).toBe("停用");
  });

  test("提供登录和通用操作文案", () => {
    expect(copy.auth.signIn).toBe("登录");
    expect(copy.common.save).toBe("保存");
    expect(copy.common.requestFailed).toBe("请求失败，请稍后重试。");
  });
});
```

- [ ] **步骤 2：确认测试失败。**

运行：`cd frontend; npm test -- --run src/lib/copy.test.ts`

预期：由于 `@/lib/copy` 不存在而失败。

- [ ] **步骤 3：实现中文词典。**

创建 `copy.ts`，至少包含：

```ts
export const copy = {
  app: { title: "权限管理系统", description: "统一管理用户、角色与权限" },
  navigation: { users: "用户管理", roles: "角色管理", logout: "退出登录" },
  common: {
    create: "新建", edit: "编辑", delete: "删除", save: "保存", cancel: "取消",
    confirm: "确认", search: "查询", reset: "重置", loading: "加载中...",
    retry: "重新加载", noData: "暂无数据", requestFailed: "请求失败，请稍后重试。",
  },
  auth: {
    signIn: "登录", signingIn: "正在登录...", welcome: "欢迎登录",
    usernameRequired: "用户名不能为空", passwordRequired: "密码不能为空",
    invalidCredentials: "用户名或密码错误", usernamePlaceholder: "请输入用户名",
    passwordPlaceholder: "请输入密码",
  },
  user: {
    username: "用户名", displayName: "姓名", email: "邮箱", phone: "手机号",
    status: "状态", roles: "角色", resetPassword: "重置密码", create: "新建用户",
    edit: "编辑用户", deleteConfirm: "确认删除该用户吗？",
  },
  role: {
    code: "角色编码", name: "角色名称", description: "角色说明",
    permissionAssignment: "权限分配", create: "新建角色", edit: "编辑角色",
    systemRoleNotice: "系统角色自动拥有全部启用权限。",
  },
  status: { active: "启用", disabled: "停用" },
} as const;
```

更新 `app/layout.tsx`：

```tsx
export const metadata: Metadata = {
  title: "权限管理系统",
  description: "统一管理用户、角色与权限",
};

<html lang="zh-CN">
```

更新登录表单以从 `copy` 引用“用户名”“密码”“登录”“正在登录”“用户名不能为空”“密码不能为空”及占位符。

- [ ] **步骤 4：运行词典和登录测试。**

运行：`cd frontend; npm test -- --run src/lib/copy.test.ts src/components/auth/login-form.test.tsx`

预期：测试通过；登录表单测试的可访问名称改为“用户名”“密码”“登录”。

- [ ] **步骤 5：提交词典基础。**

```powershell
git add frontend/src/lib/copy.ts frontend/src/lib/copy.test.ts frontend/src/app/layout.tsx frontend/src/components/auth/login-form.tsx frontend/src/components/auth/login-form.test.tsx
git commit -m "feat: add centralized chinese interface copy"
```

## Task 2: 汉化前端管理后台页面与共享组件

**文件：**
- 修改：`frontend/src/components/layout/app-sidebar.tsx`
- 修改：`frontend/src/components/layout/app-header.tsx`
- 修改：`frontend/src/components/layout/page-header.tsx`
- 修改：`frontend/src/components/auth/protected-page.tsx`
- 修改：`frontend/src/components/users/confirm-dialog.tsx`
- 修改：`frontend/src/components/users/user-filters.tsx`
- 修改：`frontend/src/components/users/user-table.tsx`
- 修改：`frontend/src/components/users/user-drawer.tsx`
- 修改：`frontend/src/components/users/password-reset-dialog.tsx`
- 修改：`frontend/src/components/users/user-management.tsx`
- 修改：`frontend/src/components/roles/role-filters.tsx`
- 修改：`frontend/src/components/roles/role-table.tsx`
- 修改：`frontend/src/components/roles/permission-tree.tsx`
- 修改：`frontend/src/components/roles/role-drawer.tsx`
- 修改：`frontend/src/components/roles/role-management.tsx`
- 修改：对应 Vitest 文件

**接口：**
- 所有上述组件从 `@/lib/copy` 读取用户可见文本。
- 数据库/API `active` 和 `disabled` 通过 `copy.status` 显示为“启用”“停用”。

- [ ] **步骤 1：编写失败的用户和角色页面中文测试。**

在 `frontend/src/components/users/user-management.test.tsx` 增加：

```tsx
test("以中文显示用户管理操作和状态", async () => {
  render(<UserManagement currentUser={adminUser} />);
  expect(await screen.findByRole("heading", { name: "用户管理" })).toBeVisible();
  expect(screen.getByRole("button", { name: "新建用户" })).toBeVisible();
  expect(screen.getByText("启用")).toBeVisible();
});
```

在 `frontend/src/components/roles/role-management.test.tsx` 增加：

```tsx
test("以中文显示角色管理和系统角色提示", async () => {
  render(<RoleManagement currentUser={adminUser} />);
  expect(await screen.findByRole("heading", { name: "角色管理" })).toBeVisible();
  expect(screen.getByRole("button", { name: "新建角色" })).toBeVisible();
});
```

- [ ] **步骤 2：确认页面测试失败。**

运行：`cd frontend; npm test -- --run src/components/users/user-management.test.tsx src/components/roles/role-management.test.tsx`

预期：因为当前页面仍显示英文标题、按钮和状态而失败。

- [ ] **步骤 3：替换导航、通用操作和访问状态文案。**

将以下可见内容替换为 `copy` 引用：

```text
User Management -> 用户管理
Role Management -> 角色管理
Sign out -> 退出登录
Open navigation -> 打开导航菜单
Close drawer -> 关闭抽屉
Loading... -> 加载中...
No permission -> 无权访问
Cancel -> 取消
Confirm -> 确认
```

保持无障碍名称中文，例如 `aria-label="打开导航菜单"` 和 `aria-label="关闭抽屉"`。

- [ ] **步骤 4：替换用户管理页面文案。**

替换以下内容：

```text
Search users -> 搜索用户
All statuses -> 全部状态
All roles -> 全部角色
Create User -> 新建用户
Edit User -> 编辑用户
Reset Password -> 重置密码
Delete User -> 删除用户
No users found -> 暂无用户数据
Retry -> 重新加载
Active -> 启用
Disabled -> 停用
```

将用户抽屉、密码重置弹窗、删除确认、字段标签、密码本地校验和网络异常回退全部改为中文。不要翻译请求 payload 中的 `username`、`role_ids` 和 `status` 值。

- [ ] **步骤 5：替换角色管理页面文案。**

替换以下内容：

```text
Role code -> 角色编码
Role name -> 角色名称
Description -> 角色说明
Permission assignment -> 权限分配
Permission count -> 权限数量
System role -> 系统角色
Delete role -> 删除角色
User Management -> 用户管理
Role Management -> 角色管理
System Management -> 系统管理
System role: all active permissions are assigned automatically. -> 系统角色自动拥有全部启用权限。
```

系统角色删除影响提示必须显示：`删除该角色后，将解除 N 位用户的角色关联。`

- [ ] **步骤 6：运行完整前端测试与构建。**

运行：`cd frontend; npm test -- --run; npm run build`

预期：所有测试通过，`/login`、`/users`、`/roles` 构建成功。

- [ ] **步骤 7：提交前端页面汉化。**

```powershell
git add frontend/src/components frontend/src/app frontend/src/lib/copy.ts
git commit -m "feat: localize admin interface in chinese"
```

## Task 3: 集中后端业务消息并汉化 Swagger

**文件：**
- 新建：`backend/app/core/messages.py`
- 修改：`backend/app/core/security.py`
- 修改：`backend/app/core/dependencies.py`
- 修改：`backend/app/services/auth_service.py`
- 修改：`backend/app/services/user_service.py`
- 修改：`backend/app/services/role_service.py`
- 修改：`backend/app/api/auth.py`
- 修改：`backend/app/api/users.py`
- 修改：`backend/app/api/roles.py`
- 修改：`backend/app/main.py`
- 新建：`backend/tests/test_localization.py`
- 修改：`backend/tests/test_auth_api.py`
- 修改：`backend/tests/test_users_api.py`
- 修改：`backend/tests/test_roles_api.py`

**接口：**
- 导出 `Messages` 类，服务层引用其中文常量。
- API 错误响应继续使用原有 `code`、`details` 和 `request_id` 字段。
- OpenAPI 标题为“权限管理系统 API”。

- [ ] **步骤 1：编写失败的后端汉化测试。**

创建 `backend/tests/test_localization.py`：

```python
async def test_missing_user_returns_chinese_message(admin_client) -> None:
    response = await admin_client.get("/api/users/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_FOUND"
    assert response.json()["message"] == "用户不存在"


async def test_openapi_metadata_and_tags_are_chinese(client) -> None:
    response = await client.get("/openapi.json")
    schema = response.json()
    assert schema["info"]["title"] == "权限管理系统 API"
    assert {tag["name"] for tag in schema["tags"]} >= {"认证管理", "用户管理", "角色管理", "权限管理"}
```

在安全测试增加：

```python
def test_password_requires_chinese_validation_messages() -> None:
    with pytest.raises(ValueError, match="密码长度不能少于 8 位"):
        validate_password("Abc123")
```

- [ ] **步骤 2：确认后端测试失败。**

运行：`cd backend; python -m pytest tests/test_localization.py tests/test_security.py -v`

预期：当前 OpenAPI 标题和错误消息为英文，测试失败。

- [ ] **步骤 3：实现消息常量和安全错误。**

创建 `messages.py`：

```python
class Messages:
    USER_NOT_FOUND = "用户不存在"
    ROLE_NOT_FOUND = "角色不存在"
    PERMISSION_NOT_FOUND = "权限不存在"
    USERNAME_EXISTS = "用户名已存在"
    EMAIL_EXISTS = "邮箱已存在"
    PHONE_EXISTS = "手机号已存在"
    ROLE_CODE_EXISTS = "角色编码已存在"
    ROLE_NAME_EXISTS = "角色名称已存在"
    INACTIVE_ROLE = "所选角色已停用"
    INACTIVE_PERMISSION = "所选权限已停用"
    SELF_DELETE_FORBIDDEN = "不能删除当前登录用户"
    SELF_STATUS_FORBIDDEN = "不能修改当前登录用户的状态"
    LAST_SUPER_ADMIN = "系统至少需要保留一名启用的超级管理员"
    SYSTEM_ROLE_PERMISSION_IMMUTABLE = "系统角色的权限不可修改"
    SYSTEM_ROLE_STATUS_IMMUTABLE = "系统角色不可停用"
    SYSTEM_ROLE_DELETE_IMMUTABLE = "系统角色不可删除"
    SUPER_ADMIN_ASSIGN_FORBIDDEN = "仅超级管理员可以分配超级管理员角色"
    INVALID_CREDENTIALS = "用户名或密码错误"
    ACCOUNT_DISABLED = "当前账号已停用"
    AUTH_EXPIRED = "登录状态已失效，请重新登录"
    PERMISSION_DENIED = "您没有执行此操作的权限"
```

修改 `validate_password`：

```python
if len(password) < 8:
    raise ValueError("密码长度不能少于 8 位")
if not any(char.isalpha() for char in password) or not any(char.isdigit() for char in password):
    raise ValueError("密码必须同时包含字母和数字")
```

- [ ] **步骤 4：替换服务层和依赖层英文消息。**

将 `auth_service.py`、`user_service.py`、`role_service.py`、`dependencies.py` 中的英文 `ApiError.message` 替换为 `Messages` 对应字段。保留：

```text
USER_NOT_FOUND
ROLE_NOT_FOUND
PERMISSION_DENIED
DUPLICATE_VALUE
SYSTEM_ROLE_IMMUTABLE
```

当消息需要角色或权限编码作上下文时使用：

```python
message=f"角色不存在：{role_id}"
message=f"权限不存在：{permission_id}"
```

认证失败统一使用 `Messages.INVALID_CREDENTIALS`，账户停用使用 `Messages.ACCOUNT_DISABLED`。

- [ ] **步骤 5：汉化 OpenAPI 信息、Tags 和接口说明。**

在 `main.py` 使用：

```python
app = FastAPI(
    title="权限管理系统 API",
    summary="用户、角色与权限统一管理服务",
    description="提供基于角色的访问控制、用户管理和角色权限管理接口。",
    lifespan=lifespan,
)
```

路由使用中文 tags：

```text
认证管理
用户管理
角色管理
权限管理
系统监控
```

为每个端点添加中文 `summary` 和简短 `description`，例如“用户登录”“查询用户列表”“新建用户”“查询角色列表”“新建角色”“查询权限字典”。JSON 字段名不能变。

- [ ] **步骤 6：运行后端测试。**

运行：`cd backend; python -m pytest tests/test_localization.py tests/test_security.py tests/test_auth_api.py tests/test_users_api.py tests/test_roles_api.py -v`

预期：中文业务消息、中文 OpenAPI 信息和既有 API 契约测试全部通过。

- [ ] **步骤 7：提交后端汉化。**

```powershell
git add backend/app/core/messages.py backend/app/core/security.py backend/app/core/dependencies.py backend/app/services backend/app/api backend/app/main.py backend/tests
git commit -m "feat: localize api messages and openapi in chinese"
```

## Task 4: 同步数据库展示数据并验证幂等种子

**文件：**
- 修改：`backend/app/db/seed.py`
- 修改：`backend/app/db/seed_demo_data.py`
- 修改：`backend/tests/test_seed.py`
- 修改：`backend/tests/test_rbac_metadata.py`
- 新建：`backend/tests/test_demo_seed.py`

**接口：**
- `seed_rbac(session: AsyncSession) -> None` 对已有基础角色/权限同步中文展示字段。
- `seed_demo_data(session: AsyncSession | None = None) -> None` 对已有演示角色同步中文展示字段，不重建用户；传入测试会话时不自行提交或关闭会话。

- [ ] **步骤 1：编写失败的基础种子同步测试。**

在 `backend/tests/test_seed.py` 增加：

```python
async def test_seed_synchronizes_chinese_system_role_and_permission_labels(session) -> None:
    await seed_rbac(session)
    super_admin = await session.scalar(select(Role).where(Role.code == "super_admin"))
    user_read = await session.scalar(select(Permission).where(Permission.code == "user:read"))

    assert super_admin.name == "超级管理员"
    assert super_admin.description == "拥有系统全部管理权限"
    assert user_read.name == "查看用户"
```

- [ ] **步骤 2：确认基础种子测试失败。**

运行：`cd backend; python -m pytest tests/test_seed.py::test_seed_synchronizes_chinese_system_role_and_permission_labels -v`

预期：当前种子仍创建英文展示名称，测试失败。

- [ ] **步骤 3：让基础种子对已有记录同步展示字段。**

将 `PERMISSIONS` 改为：

```python
("user:read", "查看用户", "user", 10)
("user:create", "新建用户", "user", 20)
("user:update", "编辑用户", "user", 30)
("user:delete", "删除用户", "user", 40)
("user:status", "调整用户状态", "user", 50)
("user:reset_password", "重置用户密码", "user", 60)
("user:assign_role", "分配用户角色", "user", 70)
("role:read", "查看角色", "role", 10)
("role:create", "新建角色", "role", 20)
("role:update", "编辑角色", "role", 30)
("role:delete", "删除角色", "role", 40)
("role:status", "调整角色状态", "role", 50)
("role:assign_permission", "分配角色权限", "role", 60)
```

将 `ROLES` 改为：

```python
("super_admin", "超级管理员", "拥有系统全部管理权限")
("user_manager", "用户管理员", "负责用户账号、状态、密码和角色分配")
```

当角色或权限已存在时，仅同步如下字段：

```python
role.name = name
role.description = description
permission.name = name
permission.module = module
permission.sort_order = sort_order
```

对 `super_admin` 同步 `is_system = True`；不得更新 `id`、`code`、`status`、用户关联或角色权限关联。

- [ ] **步骤 4：编写失败的演示角色同步测试。**

创建 `backend/tests/test_demo_seed.py`：

```python
async def test_demo_seed_synchronizes_chinese_demo_role_labels(session) -> None:
    await seed_demo_data(session)

    role = await session.scalar(select(Role).where(Role.code == "role_manager"))
    assert role.name == "角色管理员"
    assert role.description == "负责角色维护与权限分配"
```

Use the existing async `session` fixture from the backend test suite; the test must not connect to the local `rbac` database.

- [ ] **步骤 5：同步演示角色中文展示字段。**

将 `DEMO_ROLES` 改为：

```python
("role_manager", "角色管理员", "负责角色维护与权限分配", False)
("security_auditor", "安全审计员", "只读查看用户与角色信息", False)
("operations_specialist", "运营专员", "负责用户查询、新建和资料维护", False)
("read_only_visitor", "只读访客", "仅可查看用户信息", False)
```

在 `_upsert_demo_roles` 中，角色存在时同步 `name`、`description` 和 `is_system`，但不改变 `id`、`code`、`status` 或关联。将 `seed_demo_data` 改为接受可选 `session`：传入会话时直接运行同步逻辑并由调用方管理提交；未传入时创建 `async_session_factory()` 会话、运行同步逻辑并提交。将执行输出改为：

```python
print("演示数据写入完成。")
```

- [ ] **步骤 6：验证种子幂等性。**

运行：`cd backend; python -m pytest tests/test_seed.py tests/test_rbac_metadata.py tests/test_demo_seed.py -v`

预期：所有测试通过。对测试数据库连续执行两次基础种子与演示种子后，角色编码、权限码、用户数和关联数不增加。

- [ ] **步骤 7：同步当前开发数据库并核对。**

运行：

```powershell
cd X:\01_RBAC\backend
python -m app.db.seed_demo_data
```

`seed_demo_data` 必须先调用 `seed_rbac`，因此上述一条命令会同步基础角色、基础权限和演示角色的中文展示字段。

再查询：

```powershell
$env:PGPASSWORD = "rbac_local_password"
& "X:\database\postgresql\bin\psql.exe" -h 127.0.0.1 -p 5432 -U rbac -d rbac -c "SELECT code, name FROM roles WHERE is_deleted = false ORDER BY code;"
& "X:\database\postgresql\bin\psql.exe" -h 127.0.0.1 -p 5432 -U rbac -d rbac -c "SELECT code, name FROM permissions ORDER BY code;"
```

预期：6 个角色和 13 个权限均显示中文名称；用户总数、`user_roles` 数量、`role_permissions` 数量不因重复执行而增加。

- [ ] **步骤 8：提交种子汉化。**

```powershell
git add backend/app/db/seed.py backend/app/db/seed_demo_data.py backend/tests/test_seed.py backend/tests/test_rbac_metadata.py backend/tests/test_demo_seed.py
git commit -m "feat: localize seeded roles and permissions"
```

## Task 5: 文本扫描、全量回归与人工验收

**文件：**
- 新建：`frontend/src/localization.test.ts`
- 修改：`backend/tests/test_contracts.py`

**接口：**
- 文本扫描仅检查用户可见组件，不检查技术标识、测试名称、变量名、路由或 API 字段。

- [ ] **步骤 1：编写失败的前端遗留英文扫描测试。**

创建 `frontend/src/localization.test.ts`：

```ts
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, test } from "vitest";

const visibleComponentFiles = [
  "components/auth/login-form.tsx",
  "components/auth/protected-page.tsx",
  "components/layout/app-sidebar.tsx",
  "components/layout/app-header.tsx",
  "components/users/user-filters.tsx",
  "components/users/user-table.tsx",
  "components/users/user-drawer.tsx",
  "components/users/password-reset-dialog.tsx",
  "components/users/confirm-dialog.tsx",
  "components/roles/role-filters.tsx",
  "components/roles/role-table.tsx",
  "components/roles/role-drawer.tsx",
  "components/roles/permission-tree.tsx",
];

describe("管理员界面中文化", () => {
  test("用户可见组件不保留已知英文界面文案", () => {
    const forbidden = ["Sign in", "Loading...", "No permission", "Cancel", "Create User", "Role Management", "Active", "Disabled"];
    const source = visibleComponentFiles
      .map((file) => readFileSync(resolve(process.cwd(), "src", file), "utf8"))
      .join("\n");

    for (const text of forbidden) {
      expect(source).not.toContain(`>${text}<`);
      expect(source).not.toContain(`\"${text}\"`);
    }
  });
});
```

- [ ] **步骤 2：确认扫描测试失败。**

运行：`cd frontend; npm test -- --run src/localization.test.ts`

预期：至少一个英文 UI 文案存在时失败。

- [ ] **步骤 3：修正遗留用户可见英文。**

修正测试报告出的组件，不翻译以下代码内容：

```text
/api/
user:
role:
active
disabled
super_admin
role_ids
permission_ids
request_id
```

当 `active` 或 `disabled` 用于条件判断、请求值、类型或 CSS class 时可保留；仅展示文本必须从 `copy.status` 取得。

- [ ] **步骤 4：补充 API 中文错误和 OpenAPI 契约测试。**

在 `backend/tests/test_contracts.py` 增加：

```python
async def test_contract_keeps_english_error_code_with_chinese_message(admin_client) -> None:
    response = await admin_client.get("/api/users/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "USER_NOT_FOUND"
    assert body["message"] == "用户不存在"
    assert body["request_id"]
```

- [ ] **步骤 5：运行完整验证。**

运行：

```powershell
cd X:\01_RBAC\backend
python -m pytest -v
```

运行：

```powershell
cd X:\01_RBAC\frontend
npm test -- --run
npm run build
```

预期：后端与前端所有测试通过，生产构建成功。

- [ ] **步骤 6：人工验收。**

在浏览器打开并检查：

1. `http://localhost:3000/login`：标题、标签、占位符、登录按钮和表单校验均为中文。
2. 用 `wang.jian / ChangeMe-Demo1` 登录：侧栏、顶栏、用户表格、状态、抽屉、弹窗和空态均为中文。
3. 打开角色页：角色名称、说明、权限树分组、系统角色提示和删除影响提示均为中文。
4. 打开 `http://localhost:8000/docs`：标题、标签、接口摘要和描述均为中文；路径和字段仍为英文。
5. 使用停用账号 `yao.ming / ChangeMe-Demo1` 登录：显示“当前账号已停用”。

- [ ] **步骤 7：提交验收测试。**

```powershell
git add frontend/src/localization.test.ts backend/tests/test_contracts.py frontend/src/components backend/app
git commit -m "test: verify chinese admin localization"
```

## 计划自检

### 规格覆盖

- 集中前端词典、浏览器元数据、登录与管理后台中文化：Task 1 和 Task 2。
- 集中后端消息、密码规则、认证授权和 Swagger/OpenAPI 中文化：Task 3。
- 角色/权限展示字段安全同步、演示数据中文输出和当前开发库更新：Task 4。
- 保持稳定技术标识、文本扫描、全量回归和人工验收：Task 5。

### 一致性

- 前端只使用 `copy` 输出展示状态，后端与数据库继续传递 `active`/`disabled`。
- 所有服务层错误仍保留原有英文错误码，只替换 `message`。
- 角色与权限按稳定 `code` 同步展示字段，不修改关联、ID、状态或账号。
- 所有 API 路径、字段和权限码保持英文；文本扫描明确排除这些技术标识。
