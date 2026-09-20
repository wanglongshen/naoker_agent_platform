# 管理后台全量汉化设计

## 1. 目标

将权限管理系统中面向管理员和 API 调用方的英文文案统一替换为正式、简洁的企业后台中文。汉化覆盖管理后台、浏览器元数据、数据库展示数据、FastAPI Swagger/OpenAPI 信息与后端业务错误。

本次不引入多语言切换或国际化框架。前端使用集中中文词典，后端使用集中消息常量，避免分散字符串导致术语不一致。

## 2. 不变的技术标识

以下内容必须保持英文和现有值不变，因为它们是 API、数据库关系、权限校验、自动化测试或账号登录依赖的稳定标识：

```text
/api/auth/login
/api/users
/api/roles
username
role_ids
permission_ids
request_id
super_admin
user_manager
role_manager
user:read
role:assign_permission
active
wang.jian
wang.jian@acme.local
```

同样保持不变的内容包括 HTTP 状态码、业务错误码、数据库主键、角色编码、权限码、用户名、邮箱、手机号、密码规则和 API JSON 字段名称。

## 3. 范围

### 3.1 本期汉化

- 登录页、侧栏、顶栏、用户管理页、角色管理页。
- 按钮、表单标签、占位符、筛选条件、表格列、分页、加载态、空状态、确认弹窗、抽屉和错误态。
- 浏览器标题和页面描述。
- 数据库角色名称、角色说明、权限名称和权限说明。
- 演示数据脚本的角色展示数据和命令行输出。
- FastAPI OpenAPI 标题、摘要、描述、路由标签、接口摘要与接口说明。
- 后端业务错误、认证错误、授权错误、密码校验错误。

### 3.2 本期不做

- `next-intl`、语言切换、语言偏好持久化或多语言路由。
- README、开发文档、代码注释、变量名、组件名、测试名的全量中文化。
- API 路径、字段、编码、状态值或权限码的翻译。
- 数据库结构、Alembic 迁移、用户登录账号或用户角色关系的变化。

## 4. 术语表

| 英文概念 | 统一中文 |
| --- | --- |
| RBAC System | 权限管理系统 |
| User Management | 用户管理 |
| Role Management | 角色管理 |
| Permission | 权限 |
| Super Admin | 超级管理员 |
| User Manager | 用户管理员 |
| Role Manager | 角色管理员 |
| Security Auditor | 安全审计员 |
| Operations Specialist | 运营专员 |
| Read-Only Visitor | 只读访客 |
| Active | 启用 |
| Disabled | 停用 |
| Create | 新建 |
| Edit | 编辑 |
| Delete | 删除 |
| Save | 保存 |
| Cancel | 取消 |
| Confirm | 确认 |
| Search | 查询 |
| Reset | 重置 |
| Sign in | 登录 |
| Sign out | 退出登录 |
| Loading | 加载中 |
| No permission | 无权访问 |
| Username | 用户名 |
| Display Name | 姓名 |
| Reset Password | 重置密码 |

## 5. 前端设计

新增 `frontend/src/lib/copy.ts` 作为唯一的用户可见中文文案来源。该文件按领域导出只读对象：

```ts
export const copy = {
  app: {
    title: "权限管理系统",
    description: "统一管理用户、角色与权限",
  },
  navigation: {
    users: "用户管理",
    roles: "角色管理",
    logout: "退出登录",
  },
  common: {
    create: "新建",
    edit: "编辑",
    delete: "删除",
    save: "保存",
    cancel: "取消",
    confirm: "确认",
    search: "查询",
    reset: "重置",
    loading: "加载中...",
    retry: "重新加载",
    noData: "暂无数据",
    requestFailed: "请求失败，请稍后重试。",
  },
  user: {
    username: "用户名",
    displayName: "姓名",
    email: "邮箱",
    phone: "手机号",
    status: "状态",
    roles: "角色",
    resetPassword: "重置密码",
  },
  role: {
    code: "角色编码",
    name: "角色名称",
    description: "角色说明",
    permissionAssignment: "权限分配",
  },
} as const;
```

所有用户可见前端字符串引用该模块，不在页面组件内直接保留英文硬编码文本。

前端状态映射显示中文，但发送和接收的数据库状态值仍为 `active` 与 `disabled`：

```ts
const statusLabel = {
  active: "启用",
  disabled: "停用",
} as const;
```

API 返回的中文业务 `message` 直接展示。网络异常、非 JSON 错误和未知错误使用 `copy.common.requestFailed` 作为回退提示。错误码继续用于判断错误类型和字段位置。

页面范围：

- `app/layout.tsx`：标题、描述和 `<html lang="zh-CN">`。
- 登录页：欢迎语、字段标签、占位符、校验和提交状态。
- Dashboard Shell：品牌、导航、面包屑、退出登录、移动端导航控件。
- 用户页：查询、筛选、表格、状态标签、角色标签溢出提示、空态、加载态、抽屉、重置密码和删除确认。
- 角色页：查询、表格、权限分组、系统角色提示、权限变化摘要、状态操作和删除影响提示。

## 6. 数据库展示数据设计

数据库只更新角色和权限的展示字段 `name`、`description`。不改编码、主键、关联、用户账号或状态。

### 6.1 角色展示数据

| code | name | description |
| --- | --- | --- |
| `super_admin` | 超级管理员 | 拥有系统全部管理权限 |
| `user_manager` | 用户管理员 | 负责用户账号、状态、密码和角色分配 |
| `role_manager` | 角色管理员 | 负责角色维护与权限分配 |
| `security_auditor` | 安全审计员 | 只读查看用户与角色信息 |
| `operations_specialist` | 运营专员 | 负责用户查询、新建和资料维护 |
| `read_only_visitor` | 只读访客 | 仅可查看用户信息 |

### 6.2 权限展示数据

| code | name |
| --- | --- |
| `user:read` | 查看用户 |
| `user:create` | 新建用户 |
| `user:update` | 编辑用户 |
| `user:delete` | 删除用户 |
| `user:status` | 调整用户状态 |
| `user:reset_password` | 重置用户密码 |
| `user:assign_role` | 分配用户角色 |
| `role:read` | 查看角色 |
| `role:create` | 新建角色 |
| `role:update` | 编辑角色 |
| `role:delete` | 删除角色 |
| `role:status` | 调整角色状态 |
| `role:assign_permission` | 分配角色权限 |

`seed_rbac()` 与 `seed_demo_data()` 都必须按 `code` 实现同步：

1. 记录不存在时创建。
2. 记录存在时只更新展示字段、权限模块、排序与系统角色标记。
3. 不改角色或权限编码、ID、状态、用户关系、角色权限关系。
4. 重复执行不创建重复数据。

不新增 Alembic 迁移；字段结构没有变化。

## 7. 后端消息设计

新增 `backend/app/core/messages.py`。服务层引用消息常量，不再散落英文用户提示。

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

错误码保持英文稳定值，例如 `USER_NOT_FOUND`、`DUPLICATE_VALUE`、`PERMISSION_DENIED` 和 `SYSTEM_ROLE_IMMUTABLE`。HTTP 状态码、`details`、`request_id`、成功信封字段不变。

密码规则显示为：

```text
密码长度不能少于 8 位
密码必须同时包含字母和数字
```

## 8. Swagger/OpenAPI 设计

FastAPI 元信息：

```python
FastAPI(
    title="权限管理系统 API",
    summary="用户、角色与权限统一管理服务",
    description="提供基于角色的访问控制、用户管理和角色权限管理接口。",
)
```

中文路由标签：

```text
认证管理
用户管理
角色管理
权限管理
系统监控
```

接口摘要与描述均用中文，例如：用户登录、退出登录、获取当前登录用户、查询用户列表、新建用户、更新用户、调整用户状态、重置用户密码、删除用户、查询角色列表、新建角色、分配角色权限。

请求与响应字段名保持现有英文 JSON 契约。

## 9. 验证

后端验证：

- 种子执行后 6 个角色、13 个权限名称和说明均为中文。
- 角色编码、权限码、用户数、角色数、角色权限关联和用户角色关联不变。
- 用户不存在、角色不存在、重复值、停用角色、密码规则、越权与系统角色保护均返回中文 `message` 和原有英文 `code`。
- `/openapi.json` 标题、路由标签、摘要和描述中文化。
- 所有既有后端测试保持通过。

前端验证：

- 登录、用户、角色、抽屉、弹窗、权限树、空态、加载态和错误态均展示中文。
- `active`/`disabled` 显示为启用/停用。
- 技术标识、接口路径、请求字段、权限码和角色编码不被翻译。
- API 中文错误在页面中正确展示，未知失败使用统一中文回退。
- 新增文本扫描测试，检查允许保留的技术标识以外没有遗留英文 UI 文案。
- 运行完整 Vitest 套件和 `npm run build`。

## 10. 实施顺序

1. 建立前端 `copy.ts` 与后端 `messages.py`。
2. 汉化浏览器元数据、登录、布局和共享 UI 组件。
3. 汉化用户管理页、用户抽屉、密码重置和确认弹窗。
4. 汉化角色管理页、权限树和系统角色提示。
5. 汉化后端业务错误、认证错误和密码校验错误。
6. 汉化 FastAPI OpenAPI 元信息、标签和接口说明。
7. 更新基础种子与演示种子，执行种子同步既有数据库展示数据。
8. 执行后端测试、前端测试、生产构建和数据库数据核对。

## 11. 验收标准

管理员登录、管理用户、管理角色和查看 Swagger 时，所有面向用户的文本均为中文。API 路径、JSON 字段、权限码、角色编码、数据库关系、测试契约和现有账号登录能力全部保持不变。
