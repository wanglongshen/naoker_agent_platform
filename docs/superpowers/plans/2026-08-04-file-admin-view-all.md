# 超级管理员文件管理页：查看全部用户文件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 超级管理员文件管理页改为按用户分组的只读视图，能看到所有用户的文件夹和文件。

**Architecture:** 后端新增超管专属 `GET /api/files/folders/admin`（用户分组树：只含有文件/文件夹的用户，自己排最前），并为 `GET /api/files/admin` 补上 `folder_id`/`media_type` 过滤。前端管理页（`adminView`）树数据源切换到该端点、列表切换到 `/api/files/admin`，选中语义 = 用户根（该用户全部文件）/ 用户下文件夹（该文件夹内文件），默认选中自己；仅选中自己时显示操作按钮（上传/新建/删除/重命名/移动），选中他人时只读（预览/下载保留，后端 owner 校验已确保安全）。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy async / React 19 / Ant Design / vitest

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-04-file-admin-view-all-design.md`
- 需求边界：**仅查看**他人文件——删除/重命名/移动等操作仍仅限自己的文件（前后端双保险：前端隐藏按钮 + 后端 `_check_file_owner`/`_check_folder_owner` 不改）
- 树顶层用户列表 = 有文件或文件夹的用户（两表均排除 `is_deleted`），空用户不出现；**管理员自己排最前**
- 管理页默认选中"自己"的用户根 → 初始显示管理员自己的文件（与现状一致）
- `GET /api/files/admin` 需新增 `folder_id`、`media_type` 两个 Query 参数
- 文件归属通过导航结构体现，文件列表**不加**"所属者"列
- Python 执行器：`X:\python\anaconda\envs\01-rbac\python.exe`；后端测试工作目录 `C:\01_agent_loop_pro\backend`；前端工作目录 `C:\01_agent_loop_pro\frontend`
- **git 纪律**：仓库有其他并行会话的未提交变更——只能 `git add` 本任务列出的精确路径，禁止 `git add -A`/`git reset`/rebase/全局操作；提交前用 `git status` 确认暂存内容
- **前端 AGENTS.md 警告**：本项目 Next.js 版本与训练数据不同——写前端代码前先读 `node_modules/next/dist/docs/` 相关指南（如有涉及 Next 特有 API 的改动）

---

### Task 1: 后端 admin 用户分组树端点与 admin 列表过滤

**Files:**
- Modify: `backend/app/schemas/file.py`（追加 `UserFolderGroup` schema）
- Modify: `backend/app/repositories/file_repository.py`（新增 `get_admin_user_folder_trees`；`get_admin_all_files` 加过滤）
- Modify: `backend/app/api/files.py`（新增 `GET /folders/admin`；`list_all_files` 加参数）
- Test: `backend/tests/test_file_admin_api.py`（新建）

**Interfaces:**
- Consumes: 既有 `FileRepository.get_folder_tree(owner_id) -> list[FileFolder]`；`User` 模型（`username`/`display_name`/`is_deleted`）；`require_super_admin`（`app.core.dependencies`）；`app.models.rbac` 的 `User`、`app.models.file` 的 `FileFolder`/`FileObject`
- Produces:
  - `UserFolderGroup` schema（`app.schemas.file`）：`user_id: uuid.UUID`、`username: str`、`display_name: str`、`folders: list[FileFolderResponse]`
  - `FileRepository.get_admin_user_folder_trees() -> list[dict]`：每个元素 `{"user_id", "username", "display_name", "folders": [FileFolder...]}`，自己（调用时传入 `self_user_id`）排最前
  - `GET /api/files/folders/admin`（require_super_admin）→ `success(request, [UserFolderGroup...])`
  - `GET /api/files/admin` 新增 `folder_id: uuid.UUID | None = Query(None)`、`media_type: str | None = Query(None)`；`get_admin_all_files` 签名加 `folder_id`/`media_type`

- [ ] **Step 1: Write the failing tests**

Create `C:\01_agent_loop_pro\backend\tests\test_file_admin_api.py`:

```python
import uuid

from app.models.file import FileFolder, FileObject
from app.models.rbac import Role, UserRole


async def _seed_other_user(s, owner_id):
    u = User(
        username=f"owner_{uuid.uuid4().hex[:8]}",
        display_name="其他用户",
    )
    s.add(u)
    await s.flush()
    folder = FileFolder(
        owner_user_id=u.id,
        parent_folder_id=None,
        name="我的文件夹",
        path=f"/{uuid.uuid4().hex[:8]}",
        depth=1,
    )
    s.add(folder)
    s.add(
        FileObject(
            owner_user_id=u.id,
            storage_key="test/key",
            filename="root.txt",
            original_filename="root.txt",
            media_type="text/plain",
            size_bytes=10,
            sha256="abc",
        )
    )
    await s.commit()
    return u.id


async def test_non_super_admin_cannot_list_admin_folder_tree(ordinary_client) -> None:
    response = await ordinary_client.get("/api/files/folders/admin")
    assert response.status_code == 403


async def test_super_admin_folder_tree_groups_by_user(
    auth_db, admin_client, ordinary_user
) -> None:
    async with auth_db() as s:
        other_id = await _seed_other_user(s, ordinary_user.id)

    me_resp = await admin_client.get("/api/auth/me")
    assert me_resp.status_code == 200
    admin_id = me_resp.json()["data"]["id"]

    response = await admin_client.get("/api/files/folders/admin")
    assert response.status_code == 200
    groups = response.json()["data"]
    assert len(groups) >= 2
    user_ids = [g["user_id"] for g in groups]
    # admin 自己排最前
    assert str(admin_id) in user_ids
    assert user_ids[0] == str(admin_id)
    assert str(other_id) in user_ids
    other = next(g for g in groups if g["user_id"] == str(other_id))
    assert other["username"].startswith("owner_")
    assert len(other["folders"]) == 1
    assert other["folders"][0]["name"] == "我的文件夹"


async def test_super_admin_folder_tree_excludes_empty_users(
    auth_db, admin_client
) -> None:
    from app.models.rbac import User as UserModel

    async with auth_db() as s:
        empty = UserModel(username=f"empty_{uuid.uuid4().hex[:8]}", display_name="空用户")
        s.add(empty)
        await s.commit()
        empty_id = empty.id

    response = await admin_client.get("/api/files/folders/admin")
    groups = response.json()["data"]
    assert str(empty_id) not in [g["user_id"] for g in groups]


async def test_super_admin_list_filters_by_folder_and_media_type(
    auth_db, admin_client, ordinary_user
) -> None:
    async with auth_db() as s:
        other_id = await _seed_other_user(s, ordinary_user.id)
        folder_id = (
            await s.scalar(
                select(FileFolder).where(FileFolder.owner_user_id == other_id)
            )
        ).id

    # folder 过滤
    r1 = await admin_client.get(
        f"/api/files/admin?user_id={other_id}&folder_id={folder_id}"
    )
    assert r1.status_code == 200
    assert r1.json()["data"]["total"] == 0  # 文件夹内没有文件（root.txt 在根目录）

    # media_type 过滤
    r2 = await admin_client.get(
        f"/api/files/admin?user_id={other_id}&media_type=text/plain"
    )
    assert r2.json()["data"]["total"] == 1
    assert r2.json()["data"]["items"][0]["original_filename"] == "root.txt"

    r3 = await admin_client.get(
        f"/api/files/admin?user_id={other_id}&media_type=image/png"
    )
    assert r3.json()["data"]["total"] == 0


async def test_super_admin_list_all_returns_everyone(
    auth_db, admin_client, ordinary_user
) -> None:
    async with auth_db() as s:
        await _seed_other_user(s, ordinary_user.id)

    response = await admin_client.get("/api/files/admin")
    assert response.status_code == 200
    # 至少包含普通用户与其他用户两类文件（seeded admin 也可能无文件，不强制断言数量）
    assert response.json()["data"]["page"] == 1
```

注意 Step 1 测试代码顶部需要完整 import（`select` 来自 `sqlalchemy`）：

```python
import uuid

from sqlalchemy import select

from app.models.file import FileFolder, FileObject
from app.models.rbac import Role, User, UserRole
```

`_seed_other_user` 中 `User`/`Role`/`UserRole` 的引用按实际需要保留（`Role`/`UserRole` 若未用到可移除）。`ordinary_user` 是 conftest 提供的既有 fixture（普通用户，已登录客户端 `ordinary_client`）；`admin_client` 是超级管理员客户端；`auth_db` 是可提交事务的 session 工厂 fixture（参考 `backend/tests/test_agent_authorization.py` 的用法）。

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_file_admin_api.py -v --no-header` (workdir `C:\01_agent_loop_pro\backend`)
Expected: 4-5 FAIL（404 端点不存在 / ImportError）。

- [ ] **Step 3: Add UserFolderGroup schema**

In `C:\01_agent_loop_pro\backend\app\schemas\file.py`, append after `FileObjectListResponse`:

```python
class UserFolderGroup(BaseModel):
    user_id: uuid.UUID
    username: str
    display_name: str
    folders: list[FileFolderResponse]
```

- [ ] **Step 4: Implement repository methods**

In `C:\01_agent_loop_pro\backend\app\repositories\file_repository.py`:

1. Extend `get_admin_all_files` signature and filtering:

```python
    async def get_admin_all_files(
        self,
        user_id: uuid.UUID | None = None,
        folder_id: uuid.UUID | None = None,
        keyword: str | None = None,
        media_type: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Page:
        base = select(FileObject).where(FileObject.is_deleted == False)

        if user_id is not None:
            base = base.where(FileObject.owner_user_id == user_id)
        if folder_id is not None:
            base = base.where(FileObject.folder_id == folder_id)
        if keyword:
            pattern = f"%{keyword}%"
            base = base.where(FileObject.original_filename.ilike(pattern))
        if media_type:
            base = base.where(FileObject.media_type == media_type)
```

（其余 count/分页逻辑不变）

2. Add `get_admin_user_folder_trees`（放在 `get_admin_all_files` 之后）：

```python
    async def get_admin_user_folder_trees(
        self, self_user_id: uuid.UUID
    ) -> list[dict]:
        """All users that have files or folders, each with their folder tree.
        The current user (admin) is always first."""
        from sqlalchemy import exists as sql_exists

        has_content = sql_exists(
            select(FileObject.id).where(
                FileObject.owner_user_id == User.id,
                FileObject.is_deleted == False,
            )
        ) | sql_exists(
            select(FileFolder.id).where(
                FileFolder.owner_user_id == User.id,
                FileFolder.is_deleted == False,
            )
        )
        users = (
            await self.session.execute(
                select(User)
                .where(User.is_deleted == False, has_content)
                .order_by(User.id)
            )
        ).scalars().all()
        users = sorted(users, key=lambda u: u.id != self_user_id)
        groups = []
        for u in users:
            groups.append(
                {
                    "user_id": u.id,
                    "username": u.username,
                    "display_name": u.display_name,
                    "folders": await self.get_folder_tree(u.id),
                }
            )
        return groups
```

文件顶部需 import `User`：`from app.models.rbac import User`（若 `User` 已 import 则跳过）。

- [ ] **Step 5: Implement the API endpoints**

In `C:\01_agent_loop_pro\backend\app\api\files.py`:

1. Add the admin folder-tree endpoint right after `list_folders` (line ~118):

```python
@router.get("/folders/admin")
async def list_all_folders(
    request: Request,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = FileRepository(db)
    groups = await repo.get_admin_user_folder_trees(current_user.id)
    return success(
        request,
        [
            UserFolderGroup(
                user_id=g["user_id"],
                username=g["username"],
                display_name=g["display_name"],
                folders=[FileFolderResponse.model_validate(f) for f in g["folders"]],
            ).model_dump(mode="json")
            for g in groups
        ],
    )
```

2. Extend `list_all_files` (line ~220) parameters and repo call:

```python
@router.get("/admin")
async def list_all_files(
    request: Request,
    user_id: uuid.UUID | None = Query(None),
    folder_id: uuid.UUID | None = Query(None),
    keyword: str | None = Query(None),
    media_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = FileRepository(db)
    result = await repo.get_admin_all_files(
        user_id=user_id,
        folder_id=folder_id,
        keyword=keyword,
        media_type=media_type,
        page=page,
        page_size=page_size,
    )
```

3. Update imports in `files.py`: add `UserFolderGroup` to the `from app.schemas.file import ...` line（`FileFolderResponse`、`FileObjectResponse`、`FileObjectListResponse`、`UserFolderGroup`）.

⚠️ 路由顺序：`/folders/admin` 必须定义在 `@router.get("/folders/{folder_id}")` 之前（FastAPI 按定义顺序匹配）——本计划放在 `list_folders`（`/folders`）之后、`create_folder` 之前，天然安全；若现有文件中 `{folder_id}` 路由在更早位置，把新端点定义在 `list_folders` 旁即可（先于任何带路径参数的路由）。

- [ ] **Step 6: Run tests to verify they pass**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_file_admin_api.py -v --no-header` (workdir `C:\01_agent_loop_pro\backend`)
Expected: all PASS.

Run regression: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_file_repository.py tests/test_agent_authorization.py tests/test_file_schemas.py -q --no-header`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/file.py backend/app/repositories/file_repository.py backend/app/api/files.py backend/tests/test_file_admin_api.py
git commit -m "feat: super-admin user-grouped folder tree and admin file filters"
```
Workdir: `C:\01_agent_loop_pro`

---

### Task 2: 前端管理页按用户分组树与只读视图

**Files:**
- Modify: `frontend/src/types/file.ts`（追加 `UserFolderGroup` 类型）
- Modify: `frontend/src/components/files/folder-tree.tsx`（admin 分组树渲染）
- Modify: `frontend/src/components/files/file-management.tsx`（admin 数据源/选中语义/操作可见性）
- Test: `frontend/src/components/files/file-management.test.tsx`（新建）

**Interfaces:**
- Consumes: Task 1 的 `GET /api/files/folders/admin`（返回 `[{user_id, username, display_name, folders: [FileFolderNode]}]`）与 `GET /api/files/admin?user_id=&folder_id=&keyword=&media_type=&page=&page_size=`；既有 `FileListItem`/`FolderNode`/`FileListResponse` 类型（`frontend/src/types/file.ts`）
- Produces:
  - `UserFolderGroup` 类型：`{ user_id: string; username: string; display_name: string; folders: FolderNode[] }`
  - `FolderTree` 新增可选 prop：`adminGroups?: UserFolderGroup[]`、`onSelectUser?: (userId: string | null) => void`、`selectedUserId?: string`（admin 模式下渲染用户分组树；普通模式行为完全不变）
  - `FileManagement` admin 模式行为：树请求 `folders/admin`；选中用户根 → `files/admin?user_id=U`；选中文件夹 → `files/admin?user_id=U&folder_id=F`；默认选中自己；仅选中自己时显示操作按钮

- [ ] **Step 1: Read the existing types file**

Read `C:\01_agent_loop_pro\frontend\src\types\file.ts` first. Note the existing `FolderNode` / `FileListItem` / `FileListResponse` shapes — the new type must follow the same conventions.

- [ ] **Step 2: Add the UserFolderGroup type**

In `C:\01_agent_loop_pro\frontend\src\types\file.ts`, append:

```typescript
export interface UserFolderGroup {
  user_id: string;
  username: string;
  display_name: string;
  folders: FolderNode[];
}
```

(Adjust `FolderNode` import/name if the file uses different naming — read the file first.)

- [ ] **Step 3: Extend FolderTree for admin groups**

In `C:\01_agent_loop_pro\frontend\src\components\files\folder-tree.tsx`:

1. Extend props:

```typescript
interface FolderTreeProps {
  treeData: FolderNode[];
  selectedFolderId: string;
  loading: boolean;
  onSelect: (folderId: string | null) => void;
  rootLabel?: string;
  onRenameFolder?: (folder: FolderNode) => void;
  onDeleteFolder?: (folder: FolderNode) => void;
  adminGroups?: UserFolderGroup[];
  selectedUserId?: string;
  onSelectUser?: (userId: string | null) => void;
}
```

2. Add an admin-mode tree builder next to `buildTreeData`:

```typescript
function buildAdminTreeData(groups: UserFolderGroup[], currentUserId: string | null): TreeDataNode[] {
  return groups.map((g) => {
    function buildBranch(parentId: string | null): TreeDataNode[] {
      return g.folders
        .filter((n) => n.parent_folder_id === parentId)
        .map((node) => ({
          key: `folder:${node.id}`,
          title: `${node.name} (${node.child_file_count})`,
          icon: ({ expanded }: { expanded?: boolean }) =>
            expanded ? <FolderOpenOutlined /> : <FolderOutlined />,
          selectable: true,
          children: buildBranch(node.id),
        } as TreeDataNode));
    }
    return {
      key: `user:${g.user_id}`,
      title: g.display_name || g.username,
      icon: <HomeOutlined />,
      selectable: true,
      children: buildBranch(null),
    } as TreeDataNode;
  });
}
```

3. In the component body, when `adminGroups` is provided use admin mode:

```typescript
const isAdmin = !!adminGroups;
const treeNodes = useMemo(
  () =>
    isAdmin
      ? buildAdminTreeData(adminGroups ?? [], null)
      : buildTreeData(treeData, rootLabel),
  [isAdmin, adminGroups, treeData, rootLabel]
);

const selectedKeys = isAdmin
  ? [selectedUserId ? `user:${selectedUserId}` : "", ...(selectedFolderId ? [`folder:${selectedFolderId}`] : [])]
  : [selectedFolderId || ""];
```

4. In `onSelect`, decode admin keys back to plain ids:

```typescript
onSelect={(keys) => {
  if (keys.length === 0) return;
  const key = keys[0] as string;
  if (isAdmin) {
    if (key.startsWith("user:")) {
      onSelectUser?.(key.slice(5));
      onSelect(null);
    } else if (key.startsWith("folder:")) {
      onSelect(key.slice(7));
    }
  } else {
    onSelect(key || null);
  }
}}
```

5. Admin mode: `defaultExpandAll` 可能导致大量节点展开——保持现状即可（YAGNI）；右键菜单在 admin 模式跳过（`onRightClick` 中若 `isAdmin` 直接 return，且不包 `Dropdown`——条件渲染）：

```typescript
if (isAdmin) {
  return (
    <div className="folder-tree">
      <Tree
        showIcon
        defaultExpandAll
        treeData={treeNodes}
        selectedKeys={selectedKeys}
        onSelect={...}
        style={{ background: "transparent" }}
      />
    </div>
  );
}
```

（在 `loading` 分支之后、原 `Dropdown` 包装之前插入。）

- [ ] **Step 4: Rewire FileManagement for admin mode**

In `C:\01_agent_loop_pro\frontend\src\components\files\file-management.tsx`:

1. State additions:

```typescript
const [adminGroups, setAdminGroups] = useState<UserFolderGroup[] | null>(null);
const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
const [userTreeLoading, setUserTreeLoading] = useState(false);
```

2. Compute `isAdminView = !!adminView`, `selectedUser = selectedUserId ?? currentUser.id`（默认选中自己）：

```typescript
const selectedUser = selectedUserId ?? currentUser.id;
```

3. `fetchFolders` branch by mode:

```typescript
const fetchFolders = useCallback(async () => {
  try {
    if (adminView) {
      const data = await api<UserFolderGroup[]>("/api/files/folders/admin");
      setAdminGroups(data);
      const self = data.find((g) => g.user_id === currentUser.id);
      if (self && selectedUserId === null) setSelectedUserId(currentUser.id);
    } else {
      const data = await api<FolderNode[]>("/api/files/folders");
      setFolderTree(data);
    }
  } catch {
    // silent fail for tree
  } finally {
    setTreeLoading(false);
    setUserTreeLoading(false);
  }
}, [adminView, currentUser.id, selectedUserId]);
```

（`selectedUserId` 依赖会形成重复 fetch 循环——改为用 ref 或仅在首次挂载设置。更稳的做法：初始化时 `useEffect` 设一次 `setSelectedUserId(currentUser.id)`，fetch 不再依赖它。）

4. `fetchFiles` uses the admin endpoint with owner context:

```typescript
const fetchFiles = useCallback(async (currentPage: number) => {
  setLoading(true);
  setError("");
  try {
    const params = new URLSearchParams();
    if (adminView) {
      if (selectedUser) params.set("user_id", selectedUser);
      if (folderId) params.set("folder_id", folderId);
      if (keyword) params.set("keyword", keyword);
      if (mediaType) params.set("media_type", mediaType);
      params.set("page", String(currentPage));
      params.set("page_size", String(PAGE_SIZE));
      const data = await api<FileListResponse>(`/api/files/admin?${params.toString()}`);
      setFiles(data.items);
      setPage(data.page);
      setTotal(data.total);
    } else {
      // 原有普通模式逻辑不变
    }
  } catch (err) {
    setError(err instanceof Error ? err.message : copy.common.requestFailed);
  } finally {
    setLoading(false);
  }
}, [adminView, folderId, keyword, mediaType, selectedUser]);
```

5. Selection handlers:

```typescript
function handleUserSelect(userId: string | null) {
  setSelectedUserId(userId);
  setFolderId("");
  fetchFiles(1);
}

function handleFolderSelect(folderId: string | null) {
  setFolderId(folderId ?? "");
}
```

`handleFolderSelect` 已存在——保持签名，选中文件夹时 `user_id` 由 `selectedUser` 隐式携带（admin 模式下选中文件夹必须先选中其用户——树层级保证）。

6. 操作可见性——admin 模式仅选中自己时可操作：

```typescript
const ownView = !adminView || selectedUser === currentUser.id;
```

- 上传/新建文件夹按钮条件 `canUpload && !adminView` → `canUpload && ownView`
- `canManageFolders && !adminView` → `canManageFolders && ownView`
- 空态上传按钮同理（`canUpload && ownView`）
- FileList 传 `adminView={adminView}` 保持（其内部据此隐藏列/操作）——同时把操作回调在非 ownView 时不传/传空操作：

```typescript
<FileList
  ...
  onMove={ownView ? handleMove : undefined}
  onRename={ownView ? handleRename : undefined}
  onDelete={ownView ? handleDelete : undefined}
  onBatchDelete={ownView ? handleBatchDelete : undefined}
  adminView={adminView}
/>
```

（`file-list.tsx` 现有 `adminView` 处理保留；若它已按 adminView 隐藏操作，确认与 ownView 组合后行为正确——读 `file-list.tsx` 第 85-200 行确认操作按钮渲染条件，按需让 `adminView` 且非 ownView 时无操作入口。）

7. Tree props in render:

```typescript
<FolderTree
  treeData={folderTree}
  selectedFolderId={folderId}
  loading={adminView ? userTreeLoading : treeLoading}
  onSelect={handleFolderSelect}
  rootLabel={currentUser.display_name || currentUser.username}
  onRenameFolder={ownView ? handleRenameFolder : undefined}
  onDeleteFolder={ownView ? handleDeleteFolder : undefined}
  adminGroups={adminView ? (adminGroups ?? undefined) : undefined}
  selectedUserId={ownView ? null : selectedUser}
  onSelectUser={handleUserSelect}
/>
```

（注意：选中自己时树高亮"自己用户根"由 `selectedUserId` prop 控制——传 `selectedUserId={adminView ? selectedUser : undefined}` 更贴切：选中自己时高亮 user:自己，选中他人时高亮 user:他人。实现时按此语义调整。）

- [ ] **Step 5: Write frontend behavior tests**

Create `C:\01_agent_loop_pro\frontend\src\components\files\file-management.test.tsx`（先读 `file-list.test.tsx` 与 `preview-drawer.test.tsx` 了解既有测试基建：render helper、`api` mock 方式；若项目用 vitest + @testing-library/react，按既有模式写）：

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import FileManagement from "./file-management";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: vi.fn(),
}));

const mockedApi = vi.mocked(api);

const currentUser = {
  id: "u-admin",
  username: "admin",
  display_name: "管理员",
  roles: [],
  permissions: ["file:upload", "file:manage_folders", "file:admin_view"],
} as any;

const groups = [
  { user_id: "u-admin", username: "admin", display_name: "管理员", folders: [] },
  {
    user_id: "u-other",
    username: "other",
    display_name: "其他用户",
    folders: [{ id: "f1", parent_folder_id: null, name: "文件夹A", child_file_count: 1 } as any],
  },
];

beforeEach(() => {
  mockedApi.mockReset();
  mockedApi.mockImplementation(async (url: string, init?: any) => {
    if (url.startsWith("/api/files/folders/admin")) return groups;
    if (url.startsWith("/api/files/admin")) {
      return { items: [{ id: "file1", original_filename: "x.txt" }], page: 1, page_size: 20, total: 1 };
    }
    return { items: [], page: 1, page_size: 20, total: 0 };
  });
});

describe("FileManagement admin view", () => {
  it("renders user-grouped tree and loads admin list on mount", async () => {
    render(<FileManagement currentUser={currentUser} adminView />);
    await waitFor(() => expect(screen.getByText("其他用户")).toBeTruthy());
    expect(mockedApi).toHaveBeenCalledWith(
      expect.stringContaining("/api/files/admin?user_id=u-admin")
    );
  });

  it("shows upload buttons only for own files (ownView)", async () => {
    render(<FileManagement currentUser={currentUser} adminView />);
    await waitFor(() => expect(screen.getByText("上传文件")).toBeTruthy());
  });
});
```

（上传按钮断言依赖 antd Button 文本渲染；若树/按钮文本与 mock 数据不匹配，调整断言以真实渲染为准——测试目标：admin 挂载请求 `folders/admin` + `files/admin?user_id=自己`，且上传按钮在选中自己时可见。）

- [ ] **Step 6: TypeScript check**

Run: `npx tsc --noEmit` (workdir `C:\01_agent_loop_pro\frontend`)
Expected: no NEW errors from your files. (Pre-existing errors in other files — including other parallel work — are not yours to fix.)

- [ ] **Step 7: Run frontend tests**

Run: `npx vitest run src/components/files/file-management.test.tsx src/components/files/file-list.test.tsx` (workdir `C:\01_agent_loop_pro\frontend`)
Expected: new tests pass; file-list tests not regressed.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/types/file.ts frontend/src/components/files/folder-tree.tsx frontend/src/components/files/file-management.tsx frontend/src/components/files/file-management.test.tsx
git commit -m "feat: super-admin file page shows all users grouped by user"
```
Workdir: `C:\01_agent_loop_pro`

---

### Task 3: E2E 验证与收尾

**Files:**
- No new files (verification only)

- [ ] **Step 1: Backend full test suite**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/ -q --no-header` (workdir `C:\01_agent_loop_pro\backend`)
Expected: 4 known failures only (`test_file_reader.py` pypdf 缺失，既有），其余全部通过。

- [ ] **Step 2: Frontend full test suite + build**

Run: `npx vitest run` (workdir `C:\01_agent_loop_pro\frontend`)
Expected: all pass (既有 47 个 + 新增)。

Run: `npx tsc --noEmit` — no new errors.

- [ ] **Step 3: Live verification (user)**

1. admin 登录 → 顶栏/侧边栏进入"文件"管理页
2. 左侧树应显示：管理员（自己）+ 其他有文件的用户，展开他人用户名 → 其文件夹层级
3. 初始（未选中）文件列表 = 管理员自己的文件
4. 点其他用户 → 看到该用户全部文件；点其下文件夹 → 该文件夹内文件
5. 选中他人时无上传/新建/删除/重命名/移动按钮；选中自己时操作恢复
6. 预览/下载他人文件可用

- [ ] **Step 4: Commit any fixes**

```bash
git add <precise paths of changed files>
git commit -m "fix: adjustments from file admin view E2E verification"
```
(仅当有修复时执行；无改动则跳过。遵守 Global Constraints 的 git 纪律——只 add 精确路径。)
