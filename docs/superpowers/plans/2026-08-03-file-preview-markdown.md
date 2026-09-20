# 文件预览增强实现计划（Markdown 渲染 + 文档类文字版）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "我的文件"预览按格式展示——`text/markdown` 渲染为 Markdown 文档，docx 展示后端提取的文字版，pdf/图片/音视频维持原生流式预览。

**Architecture:** 后端 `preview_file` 增加 docx 分支（复用 `file_reader.extract_file_text` 提取文本）；前端 `PreviewDrawer` 新增 `markdown`/`document` 类别，文本类数据源统一改为 `/preview` 端点，Markdown 用 `react-markdown` + `remarkGfm` 渲染（URL 安全、表格/代码滚动规则与 agent 对话一致）。

**Tech Stack:** Python (FastAPI), TypeScript/React (antd Drawer, react-markdown, remark-gfm, vitest + @testing-library/react)

**Spec:** `docs/superpowers/specs/2026-08-03-file-preview-markdown-design.md`

## Global Constraints

- Markdown 渲染规则与 `progressive-markdown.tsx` 一致：`skipHtml`、外部链接 `target="_blank" rel="noreferrer noopener"` + sr-only 提示、表格包 `.table-scroll`、代码块包 `.code-scroll`
- docx MIME：`application/vnd.openxmlformats-officedocument.wordprocessingml.document`
- 文本类（text/markdown/document）数据源统一走 `GET /api/files/{id}/preview`，取响应 `data.content`；不再 fetch `/download`
- pdf/图片/音视频/unsupported 类别行为不变
- 提取失败兜底文案：`无法读取文档内容。`
- 后端测试库为 PostgreSQL（test_database_url），fixture 用 conftest 的 `test_engine`/`admin_client`

---

### Task 1: 后端 `preview_file` docx 文字版

**Files:**
- Modify: `backend/app/api/files.py:310-332`
- Test: `backend/tests/test_files_preview.py`（新建）

**Interfaces:**
- Consumes: `FileRepository.get_file(file_id)`、`_check_file_access(file_obj, current_user, db)`（files.py 现有）、`file_reader.extract_file_text(media_type, content_bytes) -> {"text": str, "truncated": bool}`（现有）
- Produces: `GET /api/files/{file_id}/preview` 对 docx 返回 `success(request, {"type": "text", "content": <提取文本>})`；md 文本分支不变

- [ ] **Step 1: Write the failing tests**

新建 `backend/tests/test_files_preview.py`：

```python
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.file import FileObject

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _insert_file(test_engine, *, media_type: str, filename: str, content: bytes, owner: uuid.UUID, tmp_path) -> str:
    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        f = FileObject(
            owner_user_id=owner,
            storage_key="",
            filename=filename,
            original_filename=filename,
            media_type=media_type,
            size_bytes=len(content),
        )
        s.add(f)
        await s.flush()
        storage = tmp_path / f"preview_{f.id.hex}.bin"
        storage.write_bytes(content)
        f.storage_key = str(storage)
        await s.commit()
        return str(f.id)


@pytest.mark.asyncio
async def test_preview_docx_returns_extracted_text(admin_client, test_engine, monkeypatch, tmp_path) -> None:
    from app.models.rbac import User
    from sqlalchemy import select

    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        owner = (await s.scalars(select(User).limit(1))).one()
        owner_id = owner.id

    docx_bytes = b"PK\x03\x04 fake docx content"
    file_id = await _insert_file(test_engine, media_type=_DOCX, filename="报告.docx", content=docx_bytes, owner=owner_id, tmp_path=tmp_path)

    import app.api.files as files_api
    monkeypatch.setattr(
        files_api,
        "extract_file_text",
        lambda media_type, content: {"text": "这是文档提取的文字", "truncated": False},
    )

    resp = await admin_client.get(f"/api/files/{file_id}/preview")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["type"] == "text"
    assert data["content"] == "这是文档提取的文字"


@pytest.mark.asyncio
async def test_preview_docx_extract_failure_returns_fallback(admin_client, test_engine, monkeypatch, tmp_path) -> None:
    from app.models.rbac import User
    from sqlalchemy import select

    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        owner = (await s.scalars(select(User).limit(1))).one()
        owner_id = owner.id

    file_id = await _insert_file(test_engine, media_type=_DOCX, filename="坏文档.docx", content=b"broken", owner=owner_id, tmp_path=tmp_path)

    import app.api.files as files_api
    monkeypatch.setattr(files_api, "extract_file_text", lambda media_type, content: (_ for _ in ()).throw(RuntimeError("boom")))

    resp = await admin_client.get(f"/api/files/{file_id}/preview")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["type"] == "text"
    assert data["content"] == "无法读取文档内容。"


@pytest.mark.asyncio
async def test_preview_markdown_returns_raw_text(admin_client, test_engine, tmp_path) -> None:
    from app.models.rbac import User
    from sqlalchemy import select

    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        owner = (await s.scalars(select(User).limit(1))).one()
        owner_id = owner.id

    md = "# 标题\n\n正文内容"
    file_id = await _insert_file(test_engine, media_type="text/markdown", filename="note.md", content=md.encode("utf-8"), owner=owner_id, tmp_path=tmp_path)

    resp = await admin_client.get(f"/api/files/{file_id}/preview")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["type"] == "text"
    assert "标题" in data["content"]


@pytest.mark.asyncio
async def test_preview_pdf_stays_stream(admin_client, test_engine, tmp_path) -> None:
    from app.models.rbac import User
    from sqlalchemy import select

    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        owner = (await s.scalars(select(User).limit(1))).one()
        owner_id = owner.id

    file_id = await _insert_file(test_engine, media_type="application/pdf", filename="doc.pdf", content=b"%PDF-1.4 fake", owner=owner_id, tmp_path=tmp_path)

    resp = await admin_client.get(f"/api/files/{file_id}/preview")
    assert resp.status_code == 200
    assert resp.json()["data"]["type"] == "stream"
```

注意：`admin_client` fixture 依赖 `test_db`（已 seed，`User` 表必有记录）；`tmp_path` 为 pytest 内置 fixture。

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_files_preview.py -q`（在 `C:\01_agent_loop_pro\backend`）
Expected: `test_preview_docx_returns_extracted_text` FAIL（当前 docx 走 unsupported 分支，`data["type"] == "unsupported"`）、`test_preview_docx_extract_failure_returns_fallback` FAIL、其余 PASS（md/pdf 现有行为已符合）。

- [ ] **Step 3: Implement the docx branch**

修改 `backend/app/api/files.py` `preview_file`（`text/` 分支之后、`return success(request, {"type": "unsupported"})` 之前）插入：

```python
    _DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if media_type == _DOCX_MIME:
        from pathlib import Path
        from app.services.agent.file_reader import extract_file_text
        sp = Path(file_obj.storage_key)
        try:
            extracted = extract_file_text(media_type, sp.read_bytes())
        except Exception:
            extracted = {"text": "无法读取文档内容。", "truncated": False}
        return success(request, {"type": "text", "content": extracted["text"]})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_files_preview.py -q`
Expected: 4/4 PASS。

- [ ] **Step 5: Run regression**

Run: `python -m pytest tests/test_file_service.py tests/test_agent_attachments.py -q`
Expected: 全部 PASS（preview 改动不影响上传/下载）。

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/files.py backend/tests/test_files_preview.py
git commit -m "feat: docx text preview via extract_file_text"
```

---

### Task 2: 前端 PreviewDrawer —— Markdown 渲染 + 文档文字版

**Files:**
- Modify: `frontend/src/components/files/preview-drawer.tsx`
- Test: `frontend/src/components/files/preview-drawer.test.tsx`（新建）

**Interfaces:**
- Consumes: `FileListItem`（`frontend/src/types/file`：`id`、`media_type`、`original_filename`、`owner_user_id` 等字段）、`NEXT_PUBLIC_API_BASE_URL`
- Produces: 分类 `classifyPreview` 新增 `"markdown" | "document"`；文本类（text/markdown/document）从 `/preview` 端点取 `data.content`；`markdown` 用 react-markdown 渲染

- [ ] **Step 1: Write the failing tests**

新建 `frontend/src/components/files/preview-drawer.test.tsx`：

```tsx
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import PreviewDrawer from "@/components/files/preview-drawer";
import type { FileListItem } from "@/types/file";

function makeFile(overrides: Partial<FileListItem> = {}): FileListItem {
  return {
    id: "f1",
    owner_user_id: "u1",
    filename: "a.md",
    original_filename: "a.md",
    media_type: "text/markdown",
    size_bytes: 10,
    folder_id: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const jsonResponse = (data: unknown) => ({ json: async () => data });

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PreviewDrawer", () => {
  test("renders markdown file as rendered markdown", async () => {
    const md = "# 标题\n\n| 列A | 列B |\n| --- | --- |\n| 1 | 2 |";
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse({ data: { content: md } }));

    render(<PreviewDrawer open file={makeFile()} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1, name: "标题" })).toBeTruthy();
    });
    expect(document.querySelector("table")).toBeTruthy();
  });

  test("renders docx file as extracted text", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ data: { content: "这是文档提取的文字" } }),
    );

    render(
      <PreviewDrawer
        open
        file={makeFile({
          media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          original_filename: "报告.docx",
        })}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("这是文档提取的文字")).toBeTruthy();
    });
  });

  test("text categories fetch the preview endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ data: { content: "hello" } }));
    vi.stubGlobal("fetch", fetchMock);

    render(<PreviewDrawer open file={makeFile({ media_type: "text/plain" })} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("hello")).toBeTruthy();
    });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/files/f1/preview"),
      expect.objectContaining({ credentials: "include" }),
    );
  });

  test("image category does not fetch text content", () => {
    render(<PreviewDrawer open file={makeFile({ media_type: "image/png", original_filename: "pic.png" })} onClose={() => {}} />);

    expect(fetch).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest --run "src/components/files/preview-drawer.test.tsx"`（在 `C:\01_agent_loop_pro\frontend`）
Expected: `renders markdown file as rendered markdown` FAIL（当前 `<pre>` 显示，无 heading）、`renders docx file as extracted text` FAIL（docx 显示"预览不可用"，且 fetch 未被调用）、`text categories fetch the preview endpoint` FAIL（fetch 目标是 /download）、`image category does not fetch text content` PASS。

- [ ] **Step 3: Implement classify + fetch + render changes**

修改 `frontend/src/components/files/preview-drawer.tsx`：

(a) 顶部 import 增加：

```tsx
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
```

(b) 替换 `classifyPreview`：

```tsx
function classifyPreview(mediaType: string): "pdf" | "image" | "video" | "audio" | "markdown" | "text" | "document" | "unsupported" {
  if (mediaType === "application/pdf") return "pdf";
  if (mediaType.startsWith("image/")) return "image";
  if (mediaType.startsWith("video/")) return "video";
  if (mediaType.startsWith("audio/")) return "audio";
  if (mediaType === "text/markdown") return "markdown";
  if (mediaType === "application/vnd.openxmlformats-officedocument.wordprocessingml.document") return "document";
  if (mediaType.startsWith("text/") || mediaType === "application/json") return "text";
  return "unsupported";
}

const TEXT_CATEGORIES = ["text", "markdown", "document"];

function classifyHref(href: string | undefined): { href: string; external: boolean } {
  if (!href) return { href: "", external: false };
  if (href.includes("\\")) return { href: "", external: false };
  try {
    const url = new URL(href);
    return ["http:", "https:", "mailto:"].includes(url.protocol)
      ? { href, external: true }
      : { href: "", external: false };
  } catch {
    return { href: "", external: false };
  }
}

const mdComponents = {
  a: ({ href, children, ...props }: any) => {
    const { href: safeHref, external } = classifyHref(href);
    return (
      <a href={safeHref} {...(external ? { target: "_blank", rel: "noreferrer noopener" } : {})} {...props}>
        {children}
        {external ? <span className="sr-only">（在新标签页中打开）</span> : null}
      </a>
    );
  },
  table: ({ children, ...props }: any) => (
    <div className="table-scroll" tabIndex={0}><table {...props}>{children}</table></div>
  ),
  pre: ({ children, ...props }: any) => (
    <div className="code-scroll" tabIndex={0}><pre {...props}>{children}</pre></div>
  ),
};
```

(c) `useEffect` 中的获取逻辑改为（判断条件与 fetch 目标）：

```tsx
  useEffect(() => {
    if (open && file) {
      const category = classifyPreview(file.media_type);
      if (TEXT_CATEGORIES.includes(category)) {
        setLoading(true);
        const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
        fetch(`${base}/api/files/${file.id}/preview`, { credentials: "include" })
          .then((r) => r.json())
          .then((d) => { setTextContent(d.data?.content ?? ""); setLoading(false); })
          .catch(() => { setTextContent("无法加载文本内容。"); setLoading(false); });
      }
    }
  }, [open, file]);
```

(d) `renderPreview` 的 `switch` 中替换 `case "text":` 为：

```tsx
      case "text":
      case "document":
        return <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", height: "100%", overflow: "auto", background: "var(--warm-surface, #faf8f5)", padding: 16, borderRadius: 8, fontSize: 13, lineHeight: 1.6 }}>{textContent}</pre>;
      case "markdown":
        return (
          <div style={{ height: "100%", overflow: "auto", fontSize: 14, lineHeight: 1.7, padding: 8 }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={mdComponents}>{textContent}</ReactMarkdown>
          </div>
        );
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest --run "src/components/files/preview-drawer.test.tsx"`
Expected: 4/4 PASS。

- [ ] **Step 5: Run related regression**

Run: `npx vitest --run "src/components/files/file-list.test.tsx"`
Expected: PASS（PreviewDrawer 改动不影响 FileList）。

- [ ] **Step 6: Typecheck / build**

Run: `npm run build`
Expected: 构建成功（无类型错误）。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/files/preview-drawer.tsx frontend/src/components/files/preview-drawer.test.tsx
git commit -m "feat: preview renders markdown and docx text via preview endpoint"
```

---

### Task 3: 全量回归

**Files:**
- 无（仅验证）

- [ ] **Step 1: Backend full suite**

Run: `python -m pytest -q`（在 `C:\01_agent_loop_pro\backend`）
Expected: 601 基线 + 新增 4 个 preview 测试全部 PASS。

- [ ] **Step 2: Frontend related suites**

Run: `npx vitest --run "src/components/files" "src/app/(agent)/agent"`（在 `C:\01_agent_loop_pro\frontend`）
Expected: 全部 PASS。
