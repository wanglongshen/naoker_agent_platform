# 文件预览增强实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 PDF 预览（iframe 用 inline URL）+ 扩展 xlsx/pptx 文本提取预览，现有可预览格式保持不变。

**Architecture:** 前端 preview-drawer.tsx 的媒体 URL 去掉 `?download=1`（后端 download 端点默认 `Content-Disposition: inline`，浏览器原生渲染 PDF）；`classifyPreview` 把 xlsx/pptx 归入现有 `"document"` 类走 /preview 文本提取；后端 /preview 端点把 docx 单分支扩展为 xlsx/pptx 多类型（复用 `extract_file_text`，已支持两种格式）。

**Tech Stack:** React 19 + vitest；FastAPI + pytest

## Global Constraints

- 前端测试 jsdom 病理约束：禁止对完整页面做 byRole/getAllByRole 查询；用 `document.querySelectorAll` + textContent 匹配（本项目既有测试用 `screen.getByText`/`getByRole` 于小组件可沿用，本任务组件小，但 iframe 断言必须用 `document.querySelector("iframe")`）
- 后端 Python 环境：conda `01-rbac`（X:\python\anaconda\envs\01-rbac\python.exe）；测试前设置独立 `TEST_DATABASE_URL`（各任务指定库名），否则与其他会话并发测试互相破坏
- git 纪律：提交前 `git status --short` 核对暂存区只含本任务列出的文件；精确路径 `git add`，绝对禁止 `git add -A`
- 下载按钮与 download 端点参数语义不变（`download=1` 仅保留在"下载文件"按钮的 href 中——见 Task 2 注）

---

### Task 1: 后端 /preview 扩展 xlsx/pptx

**Files:**
- Modify: `backend/app/api/files.py:360-369`（docx 分支扩展为多类型）
- Test: `backend/tests/test_files_preview.py`

**Interfaces:**
- Consumes: `app.services.agent.file_reader.extract_file_text(media_type, content) -> {"text": str, "truncated": bool}`
- Produces: `/api/files/{id}/preview` 对 xlsx/pptx 返回 `{"type": "text", "content": str}`（Task 2 前端依赖）

- [ ] **Step 1: 写失败测试**（追加到 `backend/tests/test_files_preview.py` 末尾；沿用该文件 `_insert_file` helper 与 monkeypatch 模式）

```python
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("media_type", "filename", "extracted"),
    [
        (_XLSX, "报表.xlsx", "单元格数据"),
        (_PPTX, "演示.pptx", "幻灯片文字"),
    ],
)
async def test_preview_office_documents_returns_extracted_text(
    admin_client, test_engine, monkeypatch, tmp_path, media_type, filename, extracted
) -> None:
    from app.models.rbac import User
    from sqlalchemy import select

    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        owner = (await s.scalars(select(User).limit(1))).one()
        owner_id = owner.id

    file_id = await _insert_file(test_engine, media_type=media_type, filename=filename, content=b"PK\x03\x04 fake content", owner=owner_id, tmp_path=tmp_path)

    import app.services.agent.file_reader as file_reader
    monkeypatch.setattr(
        file_reader,
        "extract_file_text",
        lambda mt, content: {"text": extracted, "truncated": False},
    )

    resp = await admin_client.get(f"/api/files/{file_id}/preview")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["type"] == "text"
    assert data["content"] == extracted
```

- [ ] **Step 2: 跑测试确认失败**

Run（工作目录 `backend`）:
```
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_preview_t1"; python -X utf8 -m pytest tests/test_files_preview.py -k "office_documents" -q
```
Expected: 2 FAILED（返回 `{"type": "unsupported"}`）

- [ ] **Step 3: 扩展端点**（`backend/app/api/files.py`，将 360-369 行的 docx 分支整体替换为）

```python
    _DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    _XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    _PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if media_type in {_DOCX_MIME, _XLSX_MIME, _PPTX_MIME}:
        from pathlib import Path
        from app.services.agent.file_reader import extract_file_text
        sp = Path(file_obj.storage_key)
        try:
            extracted = extract_file_text(media_type, sp.read_bytes())
        except Exception:
            extracted = {"text": "无法读取文档内容。", "truncated": False}
        return success(request, {"type": "text", "content": extracted["text"]})
```

- [ ] **Step 4: 跑测试确认通过**

```
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_preview_t1"; python -X utf8 -m pytest tests/test_files_preview.py -q
```
Expected: 全部 PASS（4 既有 + 2 新参数化 = 6）

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/files.py backend/tests/test_files_preview.py
git commit -m "feat: extend file preview text extraction to xlsx and pptx"
```

---

### Task 2: 前端 PDF inline URL 修复 + 分类扩展

**Files:**
- Modify: `frontend/src/components/files/preview-drawer.tsx`
- Test: `frontend/src/components/files/preview-drawer.test.tsx`

**Interfaces:**
- Consumes: `/api/files/{id}/preview` 支持 xlsx/pptx（Task 1）、`/api/files/{id}/download`（默认 inline，参数 download=1 时 attachment）
- Produces: 无（组件行为修复）

- [ ] **Step 1: 写失败测试**（追加到 `frontend/src/components/files/preview-drawer.test.tsx` 末尾；沿用该文件 `makeFile`/`jsonResponse` helper）

```tsx
  test("pdf preview uses inline download url", () => {
    render(
      <PreviewDrawer
        open
        file={makeFile({ media_type: "application/pdf", original_filename: "doc.pdf" })}
        onClose={() => {}}
      />,
    );
    const iframe = document.querySelector("iframe");
    expect(iframe).not.toBeNull();
    expect(iframe?.getAttribute("src")).toContain("/api/files/f1/download");
    expect(iframe?.getAttribute("src")).not.toContain("download=1");
  });

  test.each([
    ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "报表.xlsx"],
    ["application/vnd.openxmlformats-officedocument.presentationml.presentation", "演示.pptx"],
  ])("office document %s fetches the preview endpoint", async (mediaType, filename) => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ data: { content: "提取的文字" } }));
    vi.stubGlobal("fetch", fetchMock);

    render(<PreviewDrawer open file={makeFile({ media_type: mediaType, original_filename: filename })} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("提取的文字")).toBeTruthy();
    });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/files/f1/preview"),
      expect.objectContaining({ credentials: "include" }),
    );
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run（工作目录 `frontend`）: `npx vitest run src/components/files/preview-drawer.test.tsx`
Expected: 新 3 个测试 FAIL（iframe src 含 download=1；xlsx/pptx 显示"预览不可用"）

- [ ] **Step 3: 修复 URL**（`preview-drawer.tsx` `renderPreview()` 内）

```tsx
    const url = `${base}/api/files/${file.id}/download`;
```

（原为 `${base}/api/files/${file.id}/download?download=1`，去掉 query 参数。pdf/image/video/audio 四个分支共用该变量，一次修改全部生效。）

- [ ] **Step 4: 扩展分类**（`preview-drawer.tsx` `classifyPreview`，将现有 `if (mediaType === "...wordprocessingml.document") return "document";` 单行替换为）

```tsx
  if (
    mediaType === "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
    mediaType === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" ||
    mediaType === "application/vnd.openxmlformats-officedocument.presentationml.presentation"
  ) {
    return "document";
  }
```

- [ ] **Step 5: 跑测试确认通过**

Run: `npx vitest run src/components/files/preview-drawer.test.tsx`
Expected: 全部 PASS（4 既有 + 3 新 = 7）

- [ ] **Step 6: eslint**

Run: `npx eslint src/components/files/preview-drawer.tsx src/components/files/preview-drawer.test.tsx`
Expected: 0 errors

- [ ] **Step 7: 提交**

```bash
git add frontend/src/components/files/preview-drawer.tsx frontend/src/components/files/preview-drawer.test.tsx
git commit -m "fix: preview pdf inline and add xlsx/pptx text preview"
```

注：`renderPreview()` 中 url 变量同时被 Result（unsupported 兜底）的"下载文件"按钮引用——该按钮带 HTML5 `download` 属性（`href={url} download={file.original_filename}`），download 属性本身强制浏览器下载，url 变 inline 不影响其下载语义，**该按钮不改动**。`file-list.tsx` 等其他下载入口不在本任务范围。

---

### Task 3: 回归验证

**Files:** 无代码改动

- [ ] **Step 1: 后端文件相关全量**

```
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_preview_final"; python -X utf8 -m pytest tests/test_files_preview.py tests/test_files_api.py tests/test_file_service.py -q
```
Expected: 全部 PASS

- [ ] **Step 2: 前端文件组件全量**

Run（`frontend`）: `npx vitest run src/components/files`
Expected: 全部 PASS

- [ ] **Step 3: 汇报**

汇总提交 hash 与回归结果。
