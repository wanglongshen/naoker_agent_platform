# 拖拽附件 → 用户附件文件夹（双写 + 1 天删除）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow dragging files (batch or single) into the chat composer — files are double-written to the user's "附件" folder in the file library (file_objects) plus agent_attachments (1-day expiry), and become the run's attachment context for the model.

**Architecture:** Frontend: composer container gains drag-and-drop handlers; AttachmentInput switches to a unified pending-files path (any type, ≤20MB, ≤10 files) that uploads per file on submit. Backend: `upload_attachment` endpoint double-writes — `FileService.upload` into the user's auto-created "附件" folder + `AttachmentService.upload` (expires_at +1 day) referencing the same storage bytes. Cleanup: `agent_attachment_retention_days` 90→1 (existing RetentionService) + new attachment-folder cleaner deleting file_objects in "附件" folders older than 1 day.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy / pytest / TypeScript / React / Next.js / vitest / antd.

## Global Constraints

- 所有附件统一 1 天删除（`agent_attachment_retention_days: 90 → 1`）；普通文件库文件（非"附件"文件夹）不受影响
- 拖拽/选择任意类型（去白名单），单个 ≤20MB，批量 ≤10 个
- 双写：① file_objects 用户"附件"文件夹（自动创建，幂等）② agent_attachments 引用同一 storage 文件，expires_at = +1 天
- 附件 = 对话输入：模型经现有 `_read_attachment_context` 读取（无需新代码）
- 附件文件夹创建失败 → 回退仅 agent_attachments（不阻塞上传）
- 附件文件夹清理器只删"附件"文件夹的文件，不碰普通文件夹
- 既有测试全部通过（后端 836 passed 基线；前端 517 passed / 11 既有失败）
- commit 从仓库根 C:\01_agent_loop_pro 执行，仓库根相对路径
- 共享 Postgres 测试 DB：同一时刻只允许一个 pytest 进程
- 前端 jsdom 病理约束：#73/#75——测试用 querySelectorAll/textContent，页面级 byRole 禁止

---

### Task 1: 后端双写端点（agent_attachments.py + attachments.py + file_service 接入）

**Files:**
- Modify: `backend/app/api/agent_attachments.py`
- Modify: `backend/app/services/agent/attachments.py`
- Test: `backend/tests/test_agent_attachments.py`（先读现有测试确认 fixture/mock 模式）

**Interfaces:**
- Consumes: `AttachmentService.upload`（现有签名）、`FileService.upload`（`backend/app/services/file_service.py`，`async def upload(owner_user_id, folder_id, upload_file, db_session, settings=None) -> FileObjectResponse`）
- Produces:
  - `AttachmentService.upload` 增加双写（内部：附件文件夹 file_objects 写入 + storage 复用）
  - `upload_attachment` 端点行为：上传后附件同时出现在"附件"文件夹 + agent_attachments
  - 常量 `ATTACHMENT_FOLDER_NAME = "附件"`（attachments.py 或 file_service.py）

- [ ] **Step 1: Write the failing tests**（先读 `backend/tests/test_agent_attachments.py` 现有模式；追加）

```python
@pytest.mark.anyio
async def test_upload_attachment_creates_attachment_folder_file(...):
    # 上传一个 txt 附件
    # 断言: agent_attachments 记录存在
    # 断言: file_objects 中存在一条记录，其所属文件夹名为 "附件"，storage_key 与 attachment.storage_key 一致

@pytest.mark.anyio
async def test_attachment_folder_created_once(...):
    # 上传两次不同附件
    # 断言: 该用户只有 1 个名为 "附件" 的文件夹（幂等创建）
```

**关键**：双写设计——`AttachmentService.upload` 内（成功写 storage 后）追加：确保"附件"文件夹存在（查 user 的 folder name=附件 & parent None & is_deleted False，无则建）→ `FileService.upload` 或直接建 `FileObject` 记录（owner=user，folder=附件文件夹，storage_key=attachment.storage_key，extracted_text 同 attachment）。**注意**：`FileService.upload` 会自己写 storage——要复用 attachment 已写入的 storage 文件，不能二次写。**推荐实现**：不调 `FileService.upload`，直接建 `FileObject`（字段对齐现有 FileService.upload 写入的字段：owner_user_id/original_filename/storage_key/sha256/size_bytes/media_type/extracted_text/preview_status="ready"）。先读 file_objects 模型字段确认。

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_attachments.py -q
```
Expected: FAIL（附件文件夹无 file_objects 记录）

- [ ] **Step 3: Implement**

**3a.** `backend/app/services/agent/attachments.py` 顶部加：

```python
from app.models.file import FileFolder, FileObject

ATTACHMENT_FOLDER_NAME = "附件"
```

**3b.** `upload` 方法尾部（`await self._rename_storage_key(temp_key, storage_key)` 之后、`return attachment` 之前）插入双写：

```python
        try:
            await self._write_attachment_folder_record(
                owner_user_id, attachment, db_session
            )
        except Exception:
            logger.warning("attachment_folder_write_failed", exc_info=True)
        return attachment
```

（attachments.py 需加 `import logging; logger = logging.getLogger("attachments")`）

**3c.** 新增方法：

```python
    async def _write_attachment_folder_record(
        self, owner_user_id: uuid.UUID, attachment: AgentAttachment, db_session
    ) -> None:
        """双写：在用户"附件"文件夹建 file_objects 记录（storage 复用，不二次写）。"""
        from sqlalchemy import select

        folder = await db_session.scalar(
            select(FileFolder).where(
                FileFolder.owner_user_id == owner_user_id,
                FileFolder.name == ATTACHMENT_FOLDER_NAME,
                FileFolder.parent_folder_id.is_(None),
                FileFolder.is_deleted == False,
            )
        )
        if folder is None:
            folder = FileFolder(
                owner_user_id=owner_user_id,
                name=ATTACHMENT_FOLDER_NAME,
                parent_folder_id=None,
            )
            db_session.add(folder)
            await db_session.flush()

        existing = await db_session.scalar(
            select(FileObject).where(
                FileObject.storage_key == attachment.storage_key,
                FileObject.is_deleted == False,
            )
        )
        if existing is not None:
            return

        file_obj = FileObject(
            owner_user_id=owner_user_id,
            folder_id=folder.id,
            original_filename=attachment.original_filename,
            storage_key=attachment.storage_key,
            media_type=attachment.media_type,
            size_bytes=attachment.size_bytes,
            sha256=attachment.sha256,
            extracted_text=attachment.extracted_text,
            preview_status="ready" if attachment.extraction_status == "ready" else "pending",
        )
        db_session.add(file_obj)
        await db_session.flush()
```

**注意**：先读 `backend/app/models/file.py` 的 FileObject/FileFolder 字段定义，确保字段名精确（created_at 等有默认值的可不传）。

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_attachments.py -q
```
Expected: PASS

- [ ] **Step 5: Regression**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_attachments.py tests/test_files_preview.py tests/test_files_authorization.py -q
```
Expected: PASS

- [ ] **Step 6: Commit**（从仓库根）

```bash
git add backend/app/services/agent/attachments.py backend/tests/test_agent_attachments.py
git commit -m "feat: double-write attachments to user attachment folder in file library"
```

---

### Task 2: 1 天保留 + 附件文件夹清理器

**Files:**
- Modify: `backend/app/core/config.py`（`agent_attachment_retention_days: 90 → 1`）
- Modify: `backend/app/services/agent/retention.py`（加附件文件夹清理）
- Modify: `backend/app/services/agent/worker.py`（挂载清理器）
- Test: `backend/tests/test_retention.py`（先读现有测试模式）

**Interfaces:**
- Consumes: `FileObject`/`FileFolder` 模型、`RetentionService` 模式
- Produces:
  - `RetentionService.cleanup_attachment_folders(now) -> int`：删 file_objects 中"附件"文件夹且 created_at < now - 1 天（含 storage 文件）
  - worker 主循环调用

- [ ] **Step 1: Write the failing tests**（追加到 `backend/tests/test_retention.py`）

```python
@pytest.mark.anyio
async def test_attachment_folder_cleanup_removes_expired(...):
    # 构造: 用户附件文件夹 + 2 个 FileObject（一个 created_at=2 天前，一个 now）
    # 断言: cleanup_attachment_folders 删掉 2 天前的（记录 + storage），保留 now 的

@pytest.mark.anyio
async def test_attachment_folder_cleanup_ignores_other_folders(...):
    # 构造: 普通文件夹（非"附件"）含 2 天前文件
    # 断言: 不被删除
```

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_retention.py -q
```
Expected: FAIL（cleanup_attachment_folders 不存在）

- [ ] **Step 3: Implement**

**3a.** `config.py`：`agent_attachment_retention_days: int = 90` → `1`（注释更新"附件 1 天删除"）。

**3b.** `retention.py` 加方法（import 加 `from app.models.file import FileFolder, FileObject` 和 `from app.services.agent.attachments import ATTACHMENT_FOLDER_NAME`——或直接字符串 "附件" 避免循环依赖；**用字符串字面量**）：

```python
    async def cleanup_attachment_folders(self, now: datetime) -> int:
        """删除用户"附件"文件夹中超过 1 天的文件（记录 + storage）。"""
        from sqlalchemy import select
        from app.models.file import FileFolder, FileObject

        folder_ids = (
            await self._session.execute(
                select(FileFolder.id).where(
                    FileFolder.name == "附件",
                    FileFolder.is_deleted == False,
                )
            )
        ).scalars().all()
        if not folder_ids:
            return 0

        expired = (
            await self._session.execute(
                select(FileObject).where(
                    FileObject.folder_id.in_(folder_ids),
                    FileObject.is_deleted == False,
                    FileObject.created_at < now - timedelta(days=1),
                )
            )
        ).scalars().all()

        deleted = 0
        for file_obj in expired:
            try:
                await self._storage.delete(file_obj.storage_key)
            except Exception:
                pass
            file_obj.is_deleted = True
            deleted += 1
        await self._session.flush()
        return deleted
```

注意：软删（is_deleted=True）与文件库删除策略一致（先读 file_objects 现有删除逻辑确认是软删还是硬删——files.py 的 delete 端点行为）。

**3c.** `worker.py`：主循环加（`_recover_expired` 附近）：

```python
            await self._cleanup_attachment_folders()
```
定义（或直接 inline 在循环内）：

```python
    async def _cleanup_attachment_folders(self) -> None:
        try:
            async with self._session_factory() as session:
                svc = RetentionService(session, PrivateObjectStorage())
                await svc.cleanup_attachment_folders(datetime.now(UTC))
                await session.commit()
        except Exception:
            logger.warning("attachment_folder_cleanup_failed", exc_info=True)
```

（先读 worker.py 现有 `_recover_expired` 实现，确认 session/storage 构造模式后对齐。）

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_retention.py -q
```
Expected: PASS

- [ ] **Step 5: Regression**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_retention.py tests/test_agent_attachments.py -q
```
Expected: PASS

- [ ] **Step 6: Commit**（从仓库根）

```bash
git add backend/app/core/config.py backend/app/services/agent/retention.py backend/app/services/agent/worker.py backend/tests/test_retention.py
git commit -m "feat: 1-day attachment retention and attachment folder cleanup"
```

---

### Task 3: 前端拖拽 + 统一 pending-files 上传

**Files:**
- Modify: `frontend/src/components/agent/attachment-input.tsx`
- Modify: `frontend/src/components/agent/chat-composer.tsx`
- Test: `frontend/src/components/agent/attachment-input.test.tsx`（先读现有测试，无则新建）

**Interfaces:**
- Consumes: `agentApi.uploadAttachment(sessionId, formData)`（现有，`frontend/src/lib/agent-api.ts`）
- Produces:
  - `AttachmentInput` 支持拖拽 + 选择（统一 pending-files 路径，任意类型 ≤20MB ≤10 个）
  - `chat-composer` 容器 drag-and-drop 高亮 + onDrop → AttachmentInput
  - `handleSubmit`：上传 pending files → 收集 attachment_ids → onSubmit 传入

- [ ] **Step 1: Write the failing tests**（新建/追加 `frontend/src/components/agent/attachment-input.test.tsx`）

```tsx
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import AttachmentInput from "./attachment-input";

describe("AttachmentInput drag-drop", () => {
  it("accepts dropped files into pending list", () => {
    const onPending = vi.fn();
    const { container } = render(<AttachmentInput pendingFiles={[]} onPendingFilesChange={onPending} />);
    const input = container.querySelector('input[type="file"]');
    expect(input).toBeTruthy();
    // 无 sessionId 分支：drop 由 chat-composer 容器处理 → AttachmentInput 暴露 handlePendingFiles？
    // 设计决策：drop 事件在 chat-composer 处理，调用 AttachmentInput 暴露的 addFiles(files)
  });

  it("rejects files over 20MB", () => {
    // 构造 >20MB File → addFiles → error 提示
  });

  it("allows any file type", () => {
    // 构造 .pdf/.png 文件 → addFiles → 不因类型被拒
  });
});
```

**关键设计决策**：为让测试可测且拖拽可复用，`AttachmentInput` 暴露 `addFiles(files: File[])`（内部含大小/数量校验 + 追加 pending），`chat-composer` 的 onDrop 调用 `attachmentRef.current?.addFiles(Array.from(e.dataTransfer.files))`。attachment-input 的 handlePendingFiles（input onChange）改为调用同一个 addFiles。

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\frontend
npx vitest run src/components/agent/attachment-input.test.tsx
```
Expected: FAIL（addFiles 不存在）

- [ ] **Step 3: Implement**

**3a.** `attachment-input.tsx`：
- `ACCEPTED_EXTENSIONS` 删除/置空（任意类型）
- `MAX_BYTES = 20_000_000`；`MAX_FILES = 10`
- 加 `useImperativeHandle`/`forwardRef` 暴露 `addFiles(files: File[])`（校验大小/数量 → 追加 pending → 返回错误信息）
- `handlePendingFiles` 改调 `addFiles`
- sessionId 分支（antd Upload）**删除**——统一走 pending-files 路径（无 sessionId 分支逻辑）。附件上传移到 handleSubmit（chat-composer）

**3b.** `chat-composer.tsx`：
- `attachmentRef = useRef<AttachmentInputHandle>(null)`
- 容器（`<form className="chat-composer">`）加：

```tsx
  const [isDragOver, setIsDragOver] = useState(false);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  };
  const handleDragLeave = () => setIsDragOver(false);
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const files = Array.from(e.dataTransfer.files || []);
    if (files.length > 0) attachmentRef.current?.addFiles(files);
  };

  <form
    ref={formRef}
    onSubmit={handleSubmit}
    onDragOver={handleDragOver}
    onDragLeave={handleDragLeave}
    onDrop={handleDrop}
    className={`chat-composer${isDragOver ? " chat-composer-dragover" : ""}`}
  >
```

- `handleSubmit` 改：

```tsx
    setUploading(true);
    try {
      const ids: string[] = [];
      for (const { file } of pendingFiles) {
        const formData = new FormData();
        formData.append("file", file);
        const attachment = await agentApi.uploadAttachment(sessionId, formData);
        ids.push(attachment.id);
      }
      await onSubmit({ goal, attachmentIds: ids });
      setValue("");
      formRef.current?.reset();
      setPendingFiles([]);
    } finally {
      setUploading(false);
    }
```

（需 import `agentApi` from `@/lib/agent-api`；`sessionId` prop 已存在）

**3c.** CSS：`chat-composer-dragover` 高亮（app-sidebar.css 或对应样式文件加 outline/dashed border）。

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\frontend
npx vitest run src/components/agent/attachment-input.test.tsx
```
Expected: PASS

- [ ] **Step 5: 相关回归**（先确认现有测试文件）

```
cd C:\01_agent_loop_pro\frontend
npx vitest run src/components/agent/chat-composer.test.tsx src/components/agent/attachment-input.test.tsx
```
Expected: PASS（若 chat-composer 测试依赖旧 sessionId Upload 行为则需适配——报告改动）

- [ ] **Step 6: Commit**（从仓库根）

```bash
git add frontend/src/components/agent/attachment-input.tsx frontend/src/components/agent/chat-composer.tsx frontend/src/components/agent/attachment-input.test.tsx
git commit -m "feat: drag-drop files into composer, unified pending-files upload with attachment ids"
```

---

### Task 4: 集成验证

**Files:**
- Verify only（不改代码）

- [ ] **Step 1: 后端全量**（仅一个 pytest 进程；先 `Get-Process python -ErrorAction SilentlyContinue`）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/ -q
```
Expected: 836+ passed（零失败；retention 90→1 的既有测试若有断言 90 则更新为 1——在 Task 2 内处理）

- [ ] **Step 2: 前端全量**

```
cd C:\01_agent_loop_pro\frontend
npx vitest run
```
Expected: 既有结果（11 个既有失败保持不变；若增加则调查）

- [ ] **Step 3: 冒烟 — 双写真实验证**（直连 API：先启动后端，登录获取 token 或直接用测试库直连构造）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -c "import asyncio, sys; sys.path.insert(0, r'C:\01_agent_loop_pro\backend'); from app.services.agent.attachments import ATTACHMENT_FOLDER_NAME; print('folder name:', ATTACHMENT_FOLDER_NAME); from app.core.config import get_settings; print('retention days:', get_settings().agent_attachment_retention_days)"
```
Expected: folder name=附件 / retention days=1

- [ ] **Step 4: Report** — 无提交；回报用户：后端测试数、前端测试数、冒烟输出、重启提醒（agent_worker 需重启加载 retention 配置）
