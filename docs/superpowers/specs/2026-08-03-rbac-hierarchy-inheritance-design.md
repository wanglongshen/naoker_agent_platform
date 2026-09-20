# RBAC 层级继承设计

> 日期：2026-08-03 · 状态：已批准（用户确认）

## 目标

实现角色层级继承：**上级角色自动拥有下级角色的全部权限**。`role_manager` 与 `user_manager` 平级、均继承 `regular_user`；`super_admin` 为根并物化全部权限（现状不变）。权限继承在**运行时递归计算**，修改下级角色权限即时反映到上级。

## 角色层级（决策确认）

```
super_admin（根，is_system，物化绑定全部 active 权限，无 parent）
├── role_manager（role:* 六个权限 + 继承 regular_user）
├── user_manager（user:* 七个权限 + 继承 regular_user）
└── regular_user（叶子：file:read / file:upload / file:delete / file:manage_folders）
```

- 已确认：**不新增 security_auditor 角色**；审计功能（`agent_audit.py`）维持 `require_super_admin`。
- 已确认：分配约束为"仅排除 super_admin"（`get_assignable_roles` 现状不变：任何持有 `user:assign_role` 者可分配任意非 super_admin 角色）。
- 已确认：继承实现为**运行时递归计算**（方案 A）。

## 架构与改动

### 1. 数据模型：`Role.parent_role_id`

`backend/app/models/rbac.py` 的 `Role` 增加自引用外键：

```python
parent_role_id: Mapped[uuid.UUID | None] = mapped_column(
    ForeignKey("roles.id", ondelete="SET NULL"), nullable=True, index=True
)
parent_role: Mapped["Role | None"] = relationship(remote_side="Role.id")
```

语义：`A.parent_role_id = B` 表示 A 继承 B —— A 的权限集 = A 自身权限 ∪ B 及其所有祖先的权限。

### 2. 权限解析：WITH RECURSIVE 向上合并

`auth_service.get_user_permissions` 与 `dependencies.get_current_user` 中的权限查询改为递归 CTE：

```sql
WITH RECURSIVE role_ancestors AS (
    SELECT role_id FROM user_roles WHERE user_id = :user_id
    UNION
    SELECT r.parent_role_id
      FROM roles r
      JOIN role_ancestors a ON r.id = a.role_id
     WHERE r.parent_role_id IS NOT NULL
)
SELECT DISTINCT p.code
  FROM permissions p
  JOIN role_permissions rp ON rp.permission_id = p.id
  JOIN role_ancestors a ON a.role_id = rp.role_id
  JOIN roles r ON r.id = rp.role_id
 WHERE p.status = 'active' AND r.status = 'active' AND r.is_deleted = false
```

实现注意：
- SQLAlchemy 使用 `select().with_recursive(...)`（PostgreSQL 支持）；为保持跨库简单，也可用循环查询代替 CTE（角色树深度浅，最大 ~3 层）。**首选 CTE**，循环为降级方案。
- 与 `user_roles` 中用户直接绑定角色保持 UNION 起点（用户拥有角色 R → 拥有 R 及 R 全部祖先的权限）。
- 结果 `distinct` 去重；权限码集合传给前端 `/me`，前端 `hasPermission` 零改动。

### 3. seed 与 reconciliation

`backend/app/db/seed.py`：

- `ROLES` 增加 `("role_manager", "角色管理员", "管理角色与角色权限")`。
- 仅对系统角色（`is_system=True`）设置 `parent_role_id` 映射：`user_manager → regular_user`、`role_manager → regular_user`、`super_admin` 为 None；自定义角色不受 seed 影响（幂等 reconciliation）。
- `role_manager` 绑定全部 `role:*` 权限（`role:read/create/update/delete/status/assign_permission`）。
- `super_admin` 逻辑不变（绑定全部 active 权限）。

### 4. 角色服务与 API

`backend/app/services/role_service.py` / `backend/app/api/roles.py`：

- `list_roles` / `get_role_detail` 返回 `parent_role_id` 与父角色 `parent_role_code`/`parent_role_name`（列表查询时一次批量解析，避免 N+1）。
- `create_role` / `update_role` 校验防环：
  - `parent_role_id` 不能等于自身；
  - 不能指向自己的任意后代（沿 parent 链向下遍历校验）；循环引用会破坏递归 CTE（无限递归），必须在写路径拦截。
- 删除角色：若被其他角色引用为 parent，需阻止删除（`ondelete=SET NULL` 会在 ORM 层静默置空；为安全，服务层先检查引用并报错——**设计决策**：删除前校验，存在子级引用时拒绝，提示先解除）。

### 5. 分配约束

`auth_service.get_assignable_roles` **不改动**（排除 super_admin，现状符合"仅排除 super_admin"决策）。

### 6. 审计

`agent_audit.py` 的 `require_super_admin` **不改动**。

### 7. 测试（TDD）

`backend/tests/`：

1. `test_rbac_inheritance.py`（新增）：
   - `user_manager` 拥有自身 `user:*` + 继承的 4 个 `file:*` 权限（合并去重）。
   - `role_manager` 拥有 `role:*` + 继承的 `file:*`。
   - 多级链：`A → B → C` 时 A 拥有 C 的全部权限。
   - 修改下级权限即时反映（同一 session 内两次解析对比）。
   - 防环：`update_role` 设置 parent 为自身 / 后代时被拒绝。
   - 删除被引用的角色被拒绝。
2. `test_seed.py`：`role_manager` 存在、parent 映射正确、权限绑定正确、幂等。
3. 现有 `test_auth_api.py` / `test_contracts.py` / `test_users_api.py` 保持通过（`assignable_roles` 不含 super_admin 的断言不变）。

## 边界与决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| 继承方向 | 用户角色沿 parent 向上合并祖先权限 | 上级自动拥有下级权限 |
| super_admin | 不设 parent，seed 物化全部权限 | 现状即如此，避免多父问题 |
| 防环 | 写路径（create/update）拦截 | 递归 CTE 无环保护 |
| 删除有子级引用的角色 | 拒绝 | 防止静默丢失继承关系 |
| 自定义角色 | 支持设置父角色 | 继承自动生效，无需额外代码 |
| 分配约束 | 仅排除 super_admin | 用户决策，保持简单 |

## 不在范围内

- 安全审计员角色（已取消）
- 权限编辑的越权控制（分配权限时限制为自己拥有的权限）
- 前端角色页面的层级树可视化（仅返回 parent 信息，展示由前端后续决定）
- 数据迁移脚本（无既有层级数据，seed reconciliation 足够）
