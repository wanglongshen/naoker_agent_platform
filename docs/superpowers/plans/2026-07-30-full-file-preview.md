# 全文件预览系统 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 所有上传文件类型均支持在线预览（PDF/图片/视频/音频/文本），文件列表图标正确显示。

**Architecture:** 后端 preview API 返回 `{type, url}` 结构；前端按 MIME 类型完整匹配，5 种渲染器（iframe/img/video/audio/pre）；file-list 图标按 MIME 前缀匹配。

**Tech Stack:** FastAPI + React 19 + Ant Design 6 + TypeScript

## Global Constraints

- 所有 MIME 类型匹配使用 `startsWith()` 前缀匹配，不使用简写标签
- 预览 API 返回 `{type: "stream"|"text", url?: string, content?: string}`
- 前端组件类型使用 `FileListItem`（字段：id, filename, media_type, size_bytes, folder_id, created_at, updated_at）
- 后端存储已就绪：`./var/files/{user_id}/{uuid}`

---

### Task 1: 后端预览 API 增强

**Files:**
- Modify: `backend/app/api/files.py:296-312`

**Interfaces:**
- Consumes: `FileRepository.get_file(file_id)`, `_check_file_access()`, `success()`
- Produces: `GET /api/files/{id}/preview` 返回 `{"data": {"type": "stream", "url": "/api/files/{id}/download"}}` 或 `{"data": {"type": "text", "content": "..."}}`

- [ ] **Step 1: 替换 preview_file 实现**

将 `backend/app/api/files.py` 第 296-312 行替换为：

```python
@router.get("/{file_id}/preview")
async def preview_file(
    file_id: uuid.UUID,
    request: Request,
    current_user: User = require_permissions("file:read"),
    db: AsyncSession = Depends(get_db),
):
    repo = FileRepository(db)
    file_obj = await _check_file_access(await repo.get_file(file_id), current_user, db)

    media_type = file_obj.media_type or ""

    if media_type.startswith("video/") or media_type.startswith("audio/") or media_type.startswith("image/") or media_type == "application/pdf":
        return success(request, {"type": "stream", "url": f"/api/files/{file_id}/download"})
    if media_type.startswith("text/") or media_type == "application/json":
        from pathlib import Path
        sp = Path(file_obj.storage_key)
        try:
            content = sp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            content = "无法读取文件内容。"
        return success(request, {"type": "text", "content": content})
    return success(request, {"type": "unsupported"})
```

- [ ] **Step 2: 验证预览 API**

```bash
cd backend && python -c "from app.api.files import router; from app.main import app; print('import ok')"
```

Expected: `import ok`

- [ ] **Step 3: 测试 PDF 预览返回 stream 类型**

```bash
cd backend && python -c "
import asyncio, httpx, hashlib
async def test():
    async with httpx.AsyncClient(base_url='http://localhost:8000') as c:
        await c.post('/api/auth/login', json={'username':'admin','password':'ChangeMe-Strong1'})
        csrf = await c.get('/api/auth/csrf')
        token = csrf.json()['data']['token']
        pdf = b'%PDF-1.4 test'
        files = {'file': ('t.pdf', pdf, 'application/pdf')}
        up = await c.post('/api/files/upload', files=files, headers={'X-CSRF-Token': token, 'Origin': 'http://localhost:3000'})
        fid = up.json()['data']['id']
        r = await c.get(f'/api/files/{fid}/preview')
        print('Status:', r.status_code)
        print('Data:', r.json()['data'])
asyncio.run(test())
"
```

Expected: `Status: 200`, `Data: {'type': 'stream', 'url': '/api/files/.../download'}`

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/files.py
git commit -m "feat: enhance preview API with stream/text type routing"
```

---

### Task 2: 前端预览抽屉重写

**Files:**
- Modify: `frontend/src/components/files/preview-drawer.tsx` (全文件替换，131行)

**Interfaces:**
- Consumes: `FileListItem {id, filename, media_type}`, `process.env.NEXT_PUBLIC_API_BASE_URL`
- Produces: `<PreviewDrawer open file onClose />` — 5 种渲染器

- [ ] **Step 1: 替换 preview-drawer.tsx 全部内容**

```typescript
"use client";

import { useState, useEffect } from "react";
import { Drawer, Result, Skeleton, Button } from "antd";
import { FileUnknownOutlined, DownloadOutlined } from "@ant-design/icons";
import type { FileListItem } from "@/types/file";

interface PreviewDrawerProps {
  open: boolean;
  file: FileListItem | null;
  onClose: () => void;
}

function classifyPreview(mediaType: string): "pdf" | "image" | "video" | "audio" | "text" | "unsupported" {
  if (mediaType === "application/pdf") return "pdf";
  if (mediaType.startsWith("image/")) return "image";
  if (mediaType.startsWith("video/")) return "video";
  if (mediaType.startsWith("audio/")) return "audio";
  if (mediaType.startsWith("text/") || mediaType === "application/json") return "text";
  return "unsupported";
}

export default function PreviewDrawer({ open, file, onClose }: PreviewDrawerProps) {
  const [textContent, setTextContent] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open && file) {
      const category = classifyPreview(file.media_type);
      if (category === "text") {
        setLoading(true);
        const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
        fetch(`${base}/api/files/${file.id}/download`, { credentials: "include" })
          .then((r) => r.text())
          .then((t) => { setTextContent(t); setLoading(false); })
          .catch(() => { setTextContent("无法加载文本内容。"); setLoading(false); });
      }
    }
  }, [open, file]);

  function renderPreview() {
    if (!file) return null;
    if (loading) return <Skeleton active paragraph={{ rows: 12 }} />;

    const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
    const url = `${base}/api/files/${file.id}/download`;
    const category = classifyPreview(file.media_type);

    switch (category) {
      case "pdf":
        return <iframe src={url} style={{ width: "100%", height: "80vh", border: "none" }} title={file.filename} />;
      case "image":
        return <div style={{ textAlign: "center" }}><img src={url} alt={file.filename} style={{ maxWidth: "100%", maxHeight: "70vh", objectFit: "contain" }} /></div>;
      case "video":
        return <video controls style={{ width: "100%", maxHeight: "70vh" }} src={url} />;
      case "audio":
        return <audio controls style={{ width: "100%" }} src={url} />;
      case "text":
        return <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: "70vh", overflow: "auto", background: "var(--warm-surface, #faf8f5)", padding: 16, borderRadius: 8, fontSize: 13, lineHeight: 1.6 }}>{textContent}</pre>;
      default:
        return (
          <Result
            icon={<FileUnknownOutlined />}
            title="预览不可用"
            subTitle={`文件类型 "${file.media_type}" 暂不支持在线预览`}
            extra={<Button type="primary" icon={<DownloadOutlined />} href={url} download={file.filename}>下载文件</Button>}
          />
        );
    }
  }

  return (
    <Drawer title={file?.filename ?? "预览"} open={open} onClose={onClose} size="large" placement="right" destroyOnHidden styles={{ body: { padding: 16 } }}>
      {renderPreview()}
    </Drawer>
  );
}
```

- [ ] **Step 2: 构建验证**

```bash
cd frontend && npx next build
```

Expected: 构建成功，无错误

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/files/preview-drawer.tsx
git commit -m "feat: rewrite preview drawer with MIME-type matching and 5 renderers"
```

---

### Task 3: 文件列表图标修复

**Files:**
- Modify: `frontend/src/components/files/file-list.tsx:50-72`

**Interfaces:**
- Consumes: `FileListItem.media_type` (完整 MIME 字符串如 `"application/pdf"`)
- Produces: 正确的 Ant Design 图标组件

- [ ] **Step 1: 替换 getFileIcon 函数**

将 `file-list.tsx` 第 50-72 行替换为：

```typescript
function getFileIcon(mediaType: string) {
  if (!mediaType) return <FileOutlined />;
  if (mediaType === "application/pdf") return <FilePdfOutlined />;
  if (mediaType.startsWith("image/")) return <FileImageOutlined />;
  if (mediaType.startsWith("video/")) return <VideoCameraOutlined />;
  if (mediaType.startsWith("audio/")) return <AudioOutlined />;
  if (mediaType.includes("spreadsheet") || mediaType.includes("excel")) return <FileExcelOutlined />;
  if (mediaType.includes("presentation") || mediaType.includes("powerpoint")) return <FilePptOutlined />;
  if (mediaType.includes("word") || mediaType.includes("document")) return <FileWordOutlined />;
  if (mediaType.includes("zip") || mediaType.includes("rar") || mediaType.includes("7z") || mediaType.includes("gzip") || mediaType.includes("tar")) return <FileZipOutlined />;
  if (mediaType.startsWith("text/")) return <FileTextOutlined />;
  return <FileOutlined />;
}
```

- [ ] **Step 2: 构建验证**

```bash
cd frontend && npx next build
```

Expected: 构建成功

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/files/file-list.tsx
git commit -m "fix: file-list icon matching uses full MIME type prefixes"
```

---

### Task 4: 回归验证

- [ ] **Step 1: 后端测试**

```bash
cd backend && python -m pytest tests/test_files_api.py tests/test_file_service.py -v -k "upload or preview"
```

- [ ] **Step 2: 前端测试**

```bash
cd frontend && npx vitest run src/components/files/
```

- [ ] **Step 3: 全量构建**

```bash
cd frontend && npx next build && cd ../backend && python -m pytest tests/ -q -k "not test_retryable_tool_failure"
```
