# Session Sidebar: 五档分区 + 会话操作菜单

## Goal

左侧导航栏会话列表升级：
1. **五档时间分区**：今天 / 昨天 / 7天内 / 30天内 / 更早(按年月)
2. **会话条目 "..." 菜单**：重命名、置顶、删除（删除红色危险样式）
3. **置顶**：DB 字段 `is_pinned`，置顶会话永远排最前

用户/角色管理的操作菜单已存在（Dropdown + MoreOutlined），保持不动。

## Backend Changes

### AgentSession 模型加 `is_pinned` 字段
- `backend/app/models/agent.py`: `is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)`
- Alembic 迁移：新增列

### 新 API 端点（`backend/app/api/agent.py`）
| Method | Path | 说明 |
|--------|------|------|
| `PUT` | `/api/agent/sessions/{id}/rename` | 重命名，body `{title}` |
| `PATCH` | `/api/agent/sessions/{id}/pin` | 置顶/取消置顶，body `{pinned: bool}` |
| `DELETE` | `/api/agent/sessions/{id}` | 删除会话（软删 + 级联删 runs/events） |

### 列表排序
`list_sessions` 排序改为：`is_pinned DESC, updated_at DESC`

## Frontend Changes

### `session-sidebar-list.tsx`
1. `toGroupLabel` 改为五档：
   - 今天（同日）
   - 昨天（1天内）
   - 7天内
   - 30天内
   - 更早 → `YYYY-MM`
2. 条目右侧加 "..." 按钮（hover 显示，当前条目始终显示）
3. Dropdown 菜单：重命名 / 置顶(📌) / 删除(🗑️ 红色)
4. 重命名用 Modal + Input；删除用 ConfirmDialog

### `agent-api.ts`
新增 `renameSession`, `pinSession`, `deleteSession` 方法。

### `agent-session-store.ts`
删除/重命名后触发 `onAgentSessionsInvalidated` 刷新列表。
