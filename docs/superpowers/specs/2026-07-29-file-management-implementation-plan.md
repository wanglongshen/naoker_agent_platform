# 文件管理系统 — 完整开发计划（含测试与健壮性）

> 基于设计图 `file-management-diagrams.html`  
> 方案 B：新建独立文件模块  
> 核心纪律：**每一行后端代码都要有对应测试，每一个前端组件都要覆盖所有状态**

---

## 一、预检清单（每个 Phase 结束必查）

| # | 检查项 | 标准 |
|---|--------|------|
| 1 | 单元测试覆盖 | 每个 API 端点 ≥ 1 测试 / 每个组件 ≥ 1 测试 |
| 2 | 错误状态 | 组件有 loading / empty / error / 权限拒绝 四种状态 |
| 3 | 边界条件 | 空文件夹、0 字节文件、超长文件名、并发冲突 |
| 4 | 安全防护 | 路径穿越、MIME 伪造、越权访问、SQL 注入 |
| 5 | 数据库事务 | 批量操作使用原子事务，失败回滚 |
| 6 | import 验证 | `python -c "from app.main import app"` / `npx next build` |

---

## 二、Phase 1：数据库 + 模型（2 天）

### 2.1 实现

| 文件 | 操作 | 行数 |
|------|------|------|
| `alembic/versions/xxx_file_management.py` | 新建迁移 | ~60 |
| `app/models/file.py` | FileFolder + FileObject ORM | ~70 |
| `app/schemas/file.py` | Pydantic 请求/响应 | ~100 |

### 2.2 健壮性

- `FileFolder.name` 必须去首尾空白，长度 1-256
- `FileFolder.path` 自动计算（由 Service 层生成，不由用户传入）
- `FileFolder.depth` 自动计算，防止手动注入超深路径
- `FileObject.filename` 路径穿越防护（剔除 `../` `..` `/` `\`）
- `FileObject.media_type` 白名单校验（不在白名单内拒绝入库）
- `FileObject.sha256` 必须 64 位十六进制

### 2.3 测试

| 测试文件 | 测试内容 |
|---------|---------|
| `test_file_models.py` | Folder 深度自动计算、name 清洗、path 生成规则 |
| `test_file_schemas.py` | 请求校验（name 空、文件名含 `..`、media_type 非法） |

---

## 三、Phase 2：后端 Repository + Service（2 天）

### 3.1 实现

| 文件 | 操作 | 行数 |
|------|------|------|
| `repositories/file_repository.py` | CRUD 操作 | ~150 |
| `services/file_service.py` | 业务逻辑 | ~200 |

### 3.2 Repository 方法

| 方法 | 功能 | 事务 |
|------|------|------|
| `create_folder(owner_id, name, parent_id?)` | 创建文件夹，计算 path + depth | ✅ 原子 |
| `get_folder_tree(owner_id)` | 递归查询目录树 | ❌ 只读 |
| `rename_folder(folder_id, name)` | 重命名 + 递归更新子节点 path | ✅ 原子 |
| `delete_folder(folder_id)` | 软删除 + 级联子节点 + 更新父节点计数 | ✅ 原子 |
| `add_file(folder_id, file_data)` | 插入文件 + 更新文件夹计数和大小 | ✅ 原子 |
| `list_files(folder_id?, keyword?, media_type?, page, page_size)` | 分页查询 | ❌ 只读 |
| `move_file(file_id, target_folder_id)` | 原子更新 folder_id + 更新两个文件夹计数 | ✅ 原子 |
| `delete_file(file_id)` | 软删除 + 更新文件夹计数 | ✅ 原子 |
| `get_admin_all_files(user_id?, keyword?, page, page_size)` | 管理员全局查询 | ❌ 只读 |

### 3.3 Service 方法

| 方法 | 功能 | 健壮性 |
|------|------|--------|
| `upload(user, folder_id, upload_file)` | 完整上传流水线 | 大小限制 / MIME 校验 / 魔术字节扫描 / SHA-256 / 文本提取 / 计数更新 |
| `download(file_id, user)` | 流式下载 | 权限校验（owner 或 admin） |
| `preview(file_id, user)` | 返回预览内容 | 缓存命中直接返回；未命中生成后缓存 |
| `extract_text(storage_key, media_type)` | 文本提取 | UTF-8 decode ≤ 100KB；PDF/Office 调用外部库，失败不阻塞上传 |

### 3.4 健壮性

- `create_folder` 同层重名检测 → 返回 `FOLDER_NAME_DUPLICATE` 错误
- `move_file` 不能移动到自己的子文件夹（循环引用检测）
- `delete_folder` 返回受影响文件数，前端二次确认
- `upload` 文件大小硬限制（前端 + 后端双重校验）
- `upload` 10MB 限制分类型：图片 5MB
- 所有计数更新使用 `UPDATE ... SET count = count + 1` 避免竞态

### 3.5 测试

| 测试文件 | 测试内容 |
|---------|---------|
| `test_file_repository.py` | 每方法 ≥ 1 测试；同层重名；文件夹树递归；分页边界 |
| `test_file_service.py` | 上传各类型；MIME 伪造拦截；魔术字节拦截；文本提取；预览缓存 |
| `test_file_moves.py` | 移动到自身/子文件夹被拒绝；计数原子性验证 |

---

## 四、Phase 3：权限集成（1 天）

### 4.1 实现

| 文件 | 操作 |
|------|------|
| `db/seed.py` | 添加 5 个权限码 + 分配给 super_admin 和 user_manager |
| `api/files.py` | 每个端点注入 `Depends(require_permissions(...))` |
| `lib/permissions.ts` | 前端常量 |

### 4.2 测试

| 测试 | 内容 |
|------|------|
| 无权限用户访问全局视图 → 403 | |
| 无权限用户上传 → 403 | |
| 用户 A 访问用户 B 的文件 → 404 | |
| 管理员可查看所有用户文件 | |
| 管理员可删除任何用户文件 | |

---

## 五、Phase 4：后端 API（2 天）

### 5.1 实现

| 端点 | 健壮性 |
|------|--------|
| `GET /folders` | 空文件夹时返回 `[]` |
| `POST /folders` | 同层重名 → 409 |
| `PUT /folders/{id}` | 不存在 → 404；重名 → 409；他人的 → 404 |
| `DELETE /folders/{id}` | 系统保留文件夹不可删；返回 `{deleted_files: N, deleted_folders: M}` |
| `GET /` | 空列表 → 200 + `{items: [], total: 0}` |
| `GET /admin` | 需 `file:admin_view` |
| `POST /upload` | 缺少 file → 422；超限 → 413；非法类型 → 400；CSRF 失败 → 403 |
| `GET /{id}/download` | 文件不存在 → 404；无权限 → 404；Content-Disposition 头正确 |
| `GET /{id}/preview` | 无预览 → `{"status": "unavailable"}` |
| `PUT /{id}/move` | 目标不存在 → 404；循环引用 → 400 |
| `DELETE /{id}` | 软删除；返回 `{deleted: true}` |
| `DELETE /batch` | 部分成功 → 返回成功/失败列表；全部失败 → 422 |

### 5.2 测试（至少 30 个测试用例）

| 测试文件 | 覆盖 |
|---------|------|
| `test_files_api.py` | 每个端点 ≥ 2 测试（正常 + 异常） |
| `test_files_permissions.py` | 权限矩阵全覆盖 |
| `test_files_upload.py` | 各文件类型、边界大小、MIME 伪造、CSRF |
| `test_files_batch.py` | 批量删除部分成功、全部失败、空数组 |

---

## 六、Phase 5：前端组件（3 天）

### 6.1 组件清单及状态覆盖

每个组件必须覆盖以下四种状态：

| 状态 | UI 表现 |
|------|--------|
| **loading** | Skeleton / Spin |
| **empty** | EmptyState（"暂无文件，点击上传"） |
| **error** | Alert + 重试按钮 |
| **forbidden** | "无权限访问"提示 |

### 6.2 组件列表

| 组件 | 功能 | 测试 |
|------|------|------|
| `file-management.tsx` | 主状态容器，管理 dialogState + folderId + filter | ≥ 3 测试 |
| `folder-tree.tsx` | Ant Design Tree，右键菜单（新建、重命名、删除） | ≥ 3 测试 |
| `file-list.tsx` | Ant Design Table，多选、排序、筛选 | ≥ 3 测试 |
| `upload-modal.tsx` | 拖拽上传 + 进度条 + 类型校验 | ≥ 3 测试 |
| `preview-drawer.tsx` | PDF iframe / 图片 img / 文本 pre + 语法高亮 | ≥ 2 测试 |
| `move-modal.tsx` | 文件夹选择器（排除自身和子文件夹） | ≥ 2 测试 |
| `folder-create-modal.tsx` | 名称输入 + 重名校验 | ≥ 2 测试 |
| `confirm-dialog.tsx` | 通用确认弹窗（复用已有） | ≥ 1 测试 |

### 6.3 侧边栏集成

| 文件 | 操作 |
|------|------|
| `app-sidebar.tsx` | 加"文件管理"菜单项（Admin，需 `file:admin_view`） |
| `app-sidebar.tsx` | 加"我的文件"菜单项（Agent，需 `file:read`） |

### 6.4 前端测试

| 测试文件 | 覆盖 |
|---------|------|
| `file-management.test.tsx` | 四个状态 + 文件夹切换 + 搜索筛选 |
| `folder-tree.test.tsx` | 展开/折叠/右键/新建/重命名/删除 |
| `file-list.test.tsx` | 列表渲染/分页/排序/多选 |
| `upload-modal.test.tsx` | 拖拽/点击/类型拒绝/大小拒绝/成功 |
| `preview-drawer.test.tsx` | PDF/图片/文本 三种预览 |
| `move-modal.test.tsx` | 不能选自己/子文件夹；成功移动 |

---

## 七、Phase 6：Agent 附件关联（1 天）

### 7.1 实现

| 操作 | 说明 |
|------|------|
| `POST /api/files/link-attachment` | 输入 `{attachment_id, folder_id?}` |
| 复制文件存储 | `./var/agent/attachments/{uuid}` → `./var/files/{user_id}/{uuid}` |
| 创建 file_objects 记录 | `source_attachment_id = attachment_id` |
| 前端按钮 | Agent 附件列表中加"保存到文件库"操作 |

### 7.2 测试

| 测试 | 内容 |
|------|------|
| 已提取文本的附件 → 成功链接 | |
| 未提取文本的附件 → 拒绝链接 | |
| 同一文件多次链接 → 每次创建独立 file_object | |
| 附件被删除后 → file_object 不受影响（弱引用） | |

---

## 八、Phase 7：集成测试 + 安全扫描（1 天）

### 8.1 全流程测试

| 流程 | 步骤 |
|------|------|
| 上传→列表→预览→下载→删除 | 完整用户旅程 |
| 新建文件夹→上传到文件夹→移动文件 | 文件夹操作 |
| 管理员全局视图→按用户筛选→查看他人文件 | 权限验证 |
| 并发上传（2 个用户同时上传） | 计数一致性 |

### 8.2 安全测试

| 测试 | 预期 |
|------|------|
| 路径穿越文件名 `../../../etc/passwd` | 拒绝或清洗 |
| MIME 伪造（.exe 改 .txt） | 魔术字节拦截 |
| 越权访问他人文件 | 404 |
| SQL 注入 keyword 参数 | 参数化查询，注入无效 |
| CSRF 缺少 token | 403 |
| 超大文件 100MB | 413 |

### 8.3 回归测试

```bash
cd backend && python -m pytest tests/ -q
cd frontend && npx vitest run
```

预期：所有已有测试仍然通过，新增测试全部通过。

---

## 九、文件结构总览（含测试）

```
backend/
├── app/
│   ├── api/files.py                        # 15 端点
│   ├── models/file.py                      # ORM
│   ├── schemas/file.py                     # Pydantic
│   ├── repositories/file_repository.py     # DB 操作
│   ├── services/file_service.py            # 业务逻辑
│   └── db/seed.py                          # +5 权限码
├── alembic/versions/xxx_file_management.py # 迁移
└── tests/
    ├── test_file_models.py
    ├── test_file_schemas.py
    ├── test_file_repository.py
    ├── test_file_service.py
    ├── test_files_api.py
    ├── test_files_permissions.py
    ├── test_files_upload.py
    └── test_files_batch.py

frontend/
└── src/
    ├── app/(dashboard)/files/page.tsx
    ├── app/(agent)/files/page.tsx
    ├── components/files/
    │   ├── file-management.tsx + .test.tsx
    │   ├── folder-tree.tsx + .test.tsx
    │   ├── file-list.tsx + .test.tsx
    │   ├── upload-modal.tsx + .test.tsx
    │   ├── preview-drawer.tsx + .test.tsx
    │   ├── move-modal.tsx + .test.tsx
    │   └── folder-create-modal.tsx + .test.tsx
    └── lib/permissions.ts  # +5 常量
```

---

## 十、估算

| 阶段 | 天数 | 产出 |
|------|------|------|
| Phase 1: DB + 模型 | 2 | 迁移 + ORM + Schema + 测试 |
| Phase 2: Repository + Service | 2 | CRUD + 业务逻辑 + 测试 |
| Phase 3: 权限 | 1 | 权限码 + 鉴权 + 测试 |
| Phase 4: API | 2 | 15 端点 + 30+ API 测试 |
| Phase 5: 前端 | 3 | 8 组件 + 18+ 组件测试 |
| Phase 6: Agent 关联 | 1 | 链接 + 测试 |
| Phase 7: 集成 + 安全 | 1 | 全流程 + 安全扫描 |
| **合计** | **12 天** | **80+ 测试用例** |
