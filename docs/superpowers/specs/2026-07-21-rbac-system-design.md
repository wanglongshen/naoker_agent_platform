# RBAC System Design

## 1. 系统架构

```mermaid
graph TB
    subgraph "Frontend (Next.js)"
        LP[登录页]
        UP[用户管理页]
        RP[角色管理页]
        AC[AuthContext 登录态管理]
        PC[权限按钮控制]
    end

    subgraph "Backend (FastAPI)"
        AR[auth router]
        UR[users router]
        DEP[认证依赖 + 权限校验]
        SEC[JWT 签发/校验]
        SVC[auth_service / user_service]
    end

    subgraph "Database (PostgreSQL)"
        U[users]
        R[roles]
        P[permissions]
        UR_T[user_roles]
        RP_T[role_permissions]
    end

    LP -->|POST /api/auth/login| AR
    LP -->|POST /api/auth/logout| AR
    UP -->|CRUD| UR
    RP -->|预留路由| RP
    AR --> SEC
    UR --> DEP
    DEP --> SEC
    DEP --> SVC
    SVC --> U
    SVC --> R
    SVC --> P
    SVC --> UR_T
    SVC --> RP_T
    AC -->|GET /api/auth/me| AR
    PC -->|权限编码列表| AC
```

---

## 2. 数据库 ER 图

```mermaid
erDiagram
    users {
        uuid id PK
        string username UK "登录账号"
        string display_name "显示名称"
        string password_hash "Argon2"
        string email
        string phone
        string status "active / disabled"
        boolean is_deleted "软删除"
        datetime created_at
        datetime updated_at
    }

    roles {
        uuid id PK
        string code UK "super_admin / user_manager"
        string name "角色名称"
        string description
        string status "active / disabled"
        datetime created_at
    }

    permissions {
        uuid id PK
        string code UK "user:read / user:delete"
        string name "权限名称"
        string module "所属模块"
        string description
    }

    user_roles {
        uuid user_id PK,FK
        uuid role_id PK,FK
    }

    role_permissions {
        uuid role_id PK,FK
        uuid permission_id PK,FK
    }

    users ||--o{ user_roles : has
    roles ||--o{ user_roles : assigned_to
    roles ||--o{ role_permissions : contains
    permissions ||--o{ role_permissions : belongs_to
```

---

## 3. 鉴权与权限校验流程

```mermaid
sequenceDiagram
    actor U as 管理员
    participant FE as Next.js
    participant BE as FastAPI
    participant DB as PostgreSQL

    Note over U,DB: === 登录流程 ===

    U->>FE: 输入账号密码
    FE->>BE: POST /api/auth/login
    BE->>DB: 查询 users 表
    DB-->>BE: 用户记录
    BE->>BE: Argon2 校验密码
    BE->>BE: 签发 JWT
    BE-->>FE: 200 + Set-Cookie: access_token

    Note over U,DB: === 受保护请求 ===

    U->>FE: 点击"删除用户"
    FE->>BE: DELETE /api/users/{id} (携带 Cookie)
    BE->>BE: 解析 JWT → 获取 sub
    BE->>DB: 查询 user + user_roles + role_permissions
    DB-->>BE: 权限集合
    BE->>BE: 校验是否具备 user:delete
    alt 权限通过
        BE->>DB: 执行软删除
        DB-->>BE: OK
        BE-->>FE: 200 删除成功
        FE->>U: 提示成功, 刷新列表
    else 权限不足
        BE-->>FE: 403 Forbidden
        FE->>U: 提示无权限
    end
```

---

## 4. API 接口关系图

```mermaid
graph LR
    subgraph "Auth 模块 (无需鉴权)"
        LOGIN[POST /api/auth/login]
        LOGOUT[POST /api/auth/logout]
    end

    subgraph "Auth 模块 (需鉴权)"
        ME[GET /api/auth/me]
    end

    subgraph "Users 模块 (需鉴权+权限)"
        LIST[GET /api/users]
        CREATE[POST /api/users]
        UPDATE[PUT /api/users/{id}]
        DELETE[DELETE /api/users/{id}]
        STATUS[PATCH /api/users/{id}/status]
        RESET_PW[POST /api/users/{id}/reset-password]
    end

    LOGIN --> ME
    ME -->|返回用户+角色+权限| LIST

    LIST -->|user:read| LIST_V[用户列表分页]
    CREATE -->|user:create| CREATE_V[新增用户+绑定角色]
    UPDATE -->|user:update| UPDATE_V[编辑用户信息]
    DELETE -->|user:delete| DELETE_V[软删除用户]
    STATUS -->|user:status| STATUS_V[启用/停用]
    RESET_PW -->|user:reset_password| RESET_PW_V[重置密码]

    style LOGIN fill:#4CAF50,color:#fff
    style LOGOUT fill:#4CAF50,color:#fff
    style ME fill:#2196F3,color:#fff
    style LIST fill:#FF9800,color:#fff
    style CREATE fill:#FF9800,color:#fff
    style UPDATE fill:#FF9800,color:#fff
    style DELETE fill:#f44336,color:#fff
    style STATUS fill:#FF9800,color:#fff
    style RESET_PW fill:#FF9800,color:#fff
```

---

## 5. 页面结构与导航

```mermaid
graph TB
    subgraph "路由分组"
        AUTH_GROUP["(auth) 未登录组"]
        DASH_GROUP["(dashboard) 已登录组"]
    end

    AUTH_GROUP --> LOGIN_PAGE["/login<br/>登录页"]

    DASH_GROUP --> LAYOUT["/ (dashboard layout)<br/>──────────────<br/>侧边栏 + 顶栏<br/>用户信息 + 退出登录"]
    LAYOUT --> USERS_PAGE["/users<br/>用户管理页"]
    LAYOUT --> ROLES_PAGE["/roles<br/>角色管理页(首期仅壳)"]

    USERS_PAGE --> TABLE["用户表格<br/>──────────────<br/>搜索/筛选工具栏"]
    TABLE --> MODAL_ADD["新增用户弹窗<br/>填写信息 + 选择角色"]
    TABLE --> MODAL_EDIT["编辑用户弹窗<br/>修改信息"]
    TABLE --> BTN_DEL["删除按钮<br/>(user:delete)"]
    TABLE --> BTN_STATUS["启用/停用按钮<br/>(user:status)"]
    TABLE --> MODAL_PW["重置密码弹窗<br/>(user:reset_password)"]

    style LOGIN_PAGE fill:#4CAF50,color:#fff
    style USERS_PAGE fill:#2196F3,color:#fff
    style ROLES_PAGE fill:#9E9E9E,color:#fff
```

---

## 6. 用户管理页组件树

```mermaid
graph TD
    PAGE[UserListPage] --> TOOLBAR[Toolbar]
    PAGE --> TABLE[UserTable]
    PAGE --> PAGINATION[Pagination]

    TOOLBAR --> SEARCH[搜索框]
    TOOLBAR --> FILTER_STATUS[状态下拉]
    TOOLBAR --> BTN_ADD["+ 新增 user:create"]

    TABLE --> ROW[行数据]
    ROW --> USERNAME[用户名 + 显示名]
    ROW --> ROLES[角色标签列表]
    ROW --> STATUS_TAG[状态标签 active/disabled]
    ROW --> ACTIONS[操作列]
    ACTIONS --> EDIT_BTN["编辑 user:update"]
    ACTIONS --> STATUS_TOGGLE["启用/停用 user:status"]
    ACTIONS --> RESET_PW_BTN["重置密码 user:reset_password"]
    ACTIONS --> DELETE_BTN["删除 user:delete"]

    MODAL_CREATE[CreateUserModal] --> FORM_NEW[表单: 用户名/密码/邮箱/手机/角色]
    MODAL_EDIT[EditUserModal] --> FORM_EDIT[表单: 显示名/邮箱/手机/状态]
    MODAL_RESET_PW[ResetPasswordModal] --> FORM_PW[表单: 新密码+确认]
```

---

## 7. 首期权限矩阵

```mermaid
graph LR
    subgraph "角色"
        SA[super_admin<br/>超级管理员]
        UM[user_manager<br/>用户管理员]
    end

    subgraph "权限点"
        P1[user:read]
        P2[user:create]
        P3[user:update]
        P4[user:delete]
        P5[user:status]
        P6[user:reset_password]
        P7[user:assign_role]
        P8[role:read]
    end

    SA --> P1
    SA --> P2
    SA --> P3
    SA --> P4
    SA --> P5
    SA --> P6
    SA --> P7
    SA --> P8

    UM --> P1
    UM --> P2
    UM --> P3
    UM --> P5
    UM --> P6
    UM --> P7

    style SA fill:#f44336,color:#fff
    style UM fill:#2196F3,color:#fff
```

> `super_admin` 拥有全部 8 个权限点。
> `user_manager` 拥有除 `user:delete` 和 `role:read` 外的 6 个权限点。

---

## 8. 首期完整数据流 (用户新增为例)

```mermaid
sequenceDiagram
    actor OP as 操作人
    participant FE as Next.js
    participant BE as FastAPI
    participant DB as PostgreSQL

    OP->>FE: 打开新增用户弹窗, 填写信息
    FE->>FE: 校验表单字段
    OP->>FE: 点击提交
    FE->>BE: POST /api/users (Cookie)
    BE->>BE: 解析 JWT → 查询当前用户权限
    BE->>BE: 校验 user:create 权限
    alt 无权限
        BE-->>FE: 403 Forbidden
    else 有权限
        BE->>BE: 校验 username 不重复
        BE->>DB: INSERT INTO users
        BE->>DB: INSERT INTO user_roles (绑定角色)
        DB-->>BE: OK
        BE-->>FE: 201 创建成功
        FE->>OP: 关闭弹窗, 刷新列表
    end
```

---

## 附：设计决策记录

| 决策点 | 选择 | 原因 |
|---|---|---|
| 技术栈 | Next.js + FastAPI + PostgreSQL | 前后端分离，清晰分层 |
| 认证 | JWT + HttpOnly Cookie | 安全性与实用性平衡 |
| 权限粒度 | 接口级 + 按钮级 | 真实后台系统标准 |
| 主键 | UUID (应用层生成) | 避免依赖 PostgreSQL uuid-ossp |
| 密码哈希 | Argon2 | 当前公认最安全的哈希算法 |
| 用户删除 | 软删除 (is_deleted) | 保留审计能力 |
| 角色绑定 | 合入用户新增/编辑接口 | 减少接口数量，降低复杂度 |
| 刷新 Token | 首期不做 | 控制在 9 个接口范围 |
| 角色管理页 | 首期仅壳 | 先聚焦用户管理 |
