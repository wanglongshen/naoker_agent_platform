# 附件跟随会话（豆包模式）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make attachments follow the session lifecycle — session exists → attachments persist (no 1-day TTL); deleting a session cascades to attachment rows + storage files + attachment-folder file_objects; retention degrades to orphan cleanup.

**Architecture:** ① `delete_session` (agent_repository.py) collects the session's AgentAttachment rows, deletes them explicitly, deletes their storage files (best-effort), and soft-deletes matching file_objects records in the "附件" folder. ② `cleanup_attachment_folders` (retention.py) changes from "older than 1 day" to "storage_key not referenced by any AgentAttachment" (orphan cleanup), deleting storage + soft-deleting records; the old `_delete_attachments(expires_at-based)` call is replaced by the orphan cleanup. ③ config `agent_attachment_retention_days` 1 → 90.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy async / pytest.

## Global Constraints

- 附件跟随会话：会话存在 → 附件保留；会话删除 → 附件行 + storage 文件 + 附件文件夹 file_objects 记录全清
- 移除 1 天 TTL：`cleanup_attachment_folders` 不再按 created_at 1 天删，改按"storage_key 无对应 AgentAttachment"删（孤儿）
- file_objects 删除用**软删**（`is_deleted = True`，与 files.py delete_file / repo.delete_file 一致）
- storage 文件删除 best-effort（try/except，单文件失败不中断）
- config `agent_attachment_retention_days: 1 → 90`（长期保留兜底；不再有主动到期删路径）
- 附件文件夹判定：`FileFolder.name == "附件" AND parent_folder_id IS NULL AND is_deleted == False`
- 普通文件夹（非"附件"）不受影响
- 既有测试全部通过（后端 873 passed 基线）
- commit 从仓库根 C:\01_agent_loop_pro 执行，仓库根相对路径
- 共享 Postgres 测试 DB：同一时刻只允许一个 pytest 进程（测试前 `Get-Process python` 检查）

---

### Task 1: 会话删除级联附件（agent_repository.py）

**Files:**
- Modify: `backend/app/repositories/agent_repository.py`
- Test: `backend/tests/test_agent_repository.py`（先读现有 delete_session 相关测试确认 fixture 模式）

**Interfaces:**
- Consumes: `AgentAttachment`/`AgentRunAttachment` 模型、`FileObject`/`FileFolder` 模型、`PrivateObjectStorage`（`backend/app/services/agent/storage.py`，`async def delete(key, missing_ok=True)`）
- Produces: `delete_session` 行为变更——会话删除时清理附件行 + storage + 附件文件夹 file_objects

- [ ] **Step 1: Write the failing tests**（先读 `backend/tests/test_agent_repository.py` 现有测试——特别是 delete_session 测试和 fixture 如何构造 session/attachment）

```python
@pytest.mark.anyio
async def test_delete_session_cascades_attachments(...):
    # 构造: user + session + AgentAttachment(行) + storage 文件（storage.put）+ file_objects 附件文件夹记录（storage_key 同附件）
    # 调用: repo.delete_session(session_id, user_id)
    # 断言: AgentAttachment 行不存在
    # 断言: storage 文件不存在（get 抛 FileNotFoundError / 存在性检查）
    # 断言: file_objects 记录 is_deleted == True（软删）

@pytest.mark.anyio
async def test_delete_session_keeps_other_folders(...):
    # 构造: 同 session，附件文件夹 file_objects + 普通文件夹 file_objects（不同 storage_key）
    # 断言: 附件文件夹记录软删；普通文件夹记录 is_deleted == False 且 storage 文件保留
```

**关键实现约束**：
- `delete_session` 现在不接收 storage 实例——需要注入。检查现有构造函数 `AgentRepository(db)`——加可选参数 `storage: PrivateObjectStorage | None = None`（默认 None，无 storage 时跳过 storage 文件删除，只删行 + 软删记录）？或从 `app.services.agent.storage` 直接 import 单例。**先读 agent_repository.py 头部 import 与构造函数**，选与代码库一致的方式（`delete_if_unreferenced` 在 attachments.py 用 `self._storage`——repository 若已有 storage 引用则复用）。
- 软删 file_objects 用 `FileObject.is_deleted = True`（或 repo.delete_file 模式——但那是按 id 软删并可能删 storage；这里要**自己控制**：软删记录 + 单独删 storage，因为 storage_key 是附件 key 而非文件库 key）。
- 附件行删除：`delete(AgentAttachment).where(AgentAttachment.session_id == session_id)`（显式，不依赖 DB CASCADE 时机）。
- storage 文件删除：`await storage.delete(attachment.storage_key)`（try/except，失败继续）。
- 顺序：先查附件列表（id, storage_key）→ 删行 → 软删 file_objects → 删 storage 文件。任何一步失败不阻断后续（best-effort）。

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_repository.py -q
```
Expected: FAIL（附件行仍在 / storage 文件仍在 / file_objects 未软删）

- [ ] **Step 3: Implement**（按上面约束改 `delete_session`；如仓库无 storage 引用则加可选参数并在现有调用点不传——**先 grep `delete_session(` 的调用点**）

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_repository.py -q
```
Expected: PASS

- [ ] **Step 5: Regression**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_repository.py tests/test_agent_api.py -q
```
Expected: PASS

- [ ] **Step 6: Commit**（从仓库根）

```bash
git add backend/app/repositories/agent_repository.py backend/tests/test_agent_repository.py
git commit -m "feat: cascade attachment cleanup (rows + storage + attachment folder) on session delete"
```

---

### Task 2: retention 孤儿清理 + config（retention.py + worker.py + config.py）

**Files:**
- Modify: `backend/app/services/agent/retention.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_agent_retention.py`（先读现有 cleanup 测试）

**Interfaces:**
- Consumes: Task 1 不变（独立）；`AgentAttachment`/`FileObject`/`FileFolder` 模型
- Produces:
  - `RetentionService.cleanup_attachment_folders()` 语义变更：删"附件文件夹中 storage_key 无对应 AgentAttachment 的 file_objects"（孤儿）
  - `run_once` 不再调用 `_delete_attachments(expires_at-based)`——改为孤儿清理
  - `config.agent_attachment_retention_days = 90`

- [ ] **Step 1: Write the failing tests**（读 `backend/tests/test_agent_retention.py` 现有 cleanup_attachment_folders 测试——它们断言"1 天前文件被删"，必须更新）

```python
@pytest.mark.anyio
async def test_cleanup_removes_orphan_attachment_folder_files(...):
    # 构造: 附件文件夹 + file_objects A（storage_key=key_a，无对应 AgentAttachment）+ file_objects B（storage_key=key_b，有对应 AgentAttachment）
    # 调用: svc.cleanup_attachment_folders()
    # 断言: A 被软删 + storage 文件删除；B 保留（is_deleted == False 且 storage 存在）

@pytest.mark.anyio
async def test_cleanup_ignores_other_folders(...):
    # 构造: 普通文件夹含 file_objects（storage_key 无对应附件）
    # 断言: 不被删除
```

**关键实现约束**：
- 删除"1 天"判定：`cleanup_attachment_folders(now)` 签名改为**无参数或保留 now 但不用**——先读调用点（worker.py:169-177 `await svc.cleanup_attachment_folders(datetime.now(UTC))`）决定是否同步改。建议改签名 `cleanup_attachment_folders()`（无参）并同步 worker 调用点。
- 孤儿判定 SQL：
  ```python
  attached_keys = select(AgentAttachment.storage_key)
  orphans = select(FileObject).where(
      FileObject.folder_id.in_(folder_ids),
      FileObject.is_deleted == False,
      FileObject.storage_key.not_in(attached_keys),
  )
  ```
- 每个孤儿：`storage.delete(storage_key)` best-effort + `is_deleted = True` + flush。
- `run_once` 中删除 `attachment_cutoff = now - timedelta(...)` 与 `await self._delete_attachments(attachment_cutoff, result)`——替换为 `await self.cleanup_attachment_folders()`（或保留 _delete_attachments 但不再调用；**若 _delete_attachments 无其他调用点则删除该方法**——先 grep）。
- config: `agent_attachment_retention_days: int = 1` → `90`（注释更新为"附件长期保留（跟随会话），兜底配置"）。

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_retention.py -q
```
Expected: FAIL（旧测试断言 1 天行为，新孤儿行为不匹配）

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_retention.py -q
```
Expected: PASS

- [ ] **Step 5: Regression**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_retention.py tests/test_agent_attachments.py tests/test_agent_worker.py -q
```
Expected: PASS

- [ ] **Step 6: Commit**（从仓库根）

```bash
git add backend/app/services/agent/retention.py backend/app/core/config.py backend/tests/test_agent_retention.py
git commit -m "feat: attachment retention becomes orphan cleanup, follow session lifecycle"
```

（若 worker.py 调用点签名变化则一并 add）

---

### Task 3: 集成验证

**Files:**
- Verify only（不改代码）

- [ ] **Step 1: 后端全量**（仅一个 pytest 进程；先 `Get-Process python -ErrorAction SilentlyContinue`）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/ -q
```
Expected: 873+ passed（零失败；若首次有 DB 污染导致的失败，单独重跑失败文件确认后干净重跑全量）

- [ ] **Step 2: 冒烟 — 配置与清理器行为**（直连测试库或单测验证）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -c "import sys; sys.path.insert(0, r'C:\01_agent_loop_pro\backend'); from app.core.config import get_settings; print('retention days:', get_settings().agent_attachment_retention_days)"
```
Expected: retention days: 90

- [ ] **Step 3: Report** — 无提交；回报用户：测试数、冒烟输出、重启提醒（agent_worker 需重启加载新 retention 逻辑）
