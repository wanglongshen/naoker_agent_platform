# 全文件预览系统 — 企业级方案

> 目标：所有文件类型均支持在线预览，文件本地存储  
> 原则：按 MIME 类型路由，后端统一提供预览数据，前端统一渲染

---

## 一、当前问题

`preview-drawer.tsx` 判断逻辑不完整：

```typescript
if (mediaType === "pdf") → iframe   ← 实际 MIME 是 "application/pdf"，匹配失败
if (["image", "png"...].includes(mediaType)) → img  ← 匹配失败
if (["text", "csv", "markdown"].includes(mediaType)) → TextPreview  ← 匹配失败
```

**根因：** 代码用简写类型（如 `"pdf"`）判断，但 API 返回的是完整 MIME（如 `"application/pdf"`）。

---

## 二、后端预览增强

### 2.1 预览端点改造

`GET /api/files/{id}/preview` 返回按类型定制的数据：

```python
@router.get("/{file_id}/preview")
async def preview_file(file_id, ...):
    file_obj = await _check_file_access(...)
    media_type = file_obj.media_type
    preview_type = classify_preview_type(media_type)

    if preview_type == "stream":
        return {"type": "stream", "url": f"/api/files/{file_id}/download"}
    if preview_type == "text":
        text = read_text_from_storage(file_obj)
        return {"type": "text", "content": text}
    return {"type": "unsupported"}
```

### 2.2 预览类型分类

```python
def classify_preview_type(media_type: str) -> str:
    if media_type.startswith("image/") or media_type == "application/pdf":
        return "stream"    # 浏览器原生渲染
    if media_type.startswith("video/") or media_type.startswith("audio/"):
        return "stream"    # HTML5 播放器
    if media_type.startswith("text/") or media_type in ("application/json",):
        return "text"      # 文本内容返回
    # Office 文档 → 走下载（浏览器可能打不开）
    return "unsupported"
```

---

## 三、前端预览抽屉重构

### 3.1 MIME 类型匹配（修复匹配失败）

```typescript
function getPreviewCategory(mediaType: string) {
  if (mediaType === "application/pdf") return "pdf";
  if (mediaType.startsWith("image/")) return "image";
  if (mediaType.startsWith("video/")) return "video";
  if (mediaType.startsWith("audio/")) return "audio";
  if (mediaType.startsWith("text/") || mediaType === "application/json") return "text";
  return "unsupported";
}
```

### 3.2 渲染器

| 类型 | 组件 | 说明 |
|------|------|------|
| PDF | `<iframe>` 内嵌 | 浏览器原生 PDF 查看器 |
| 图片 | `<img>` | 支持 png/jpg/gif/webp/svg |
| 视频 | `<video controls>` | HTML5 播放器 |
| 音频 | `<audio controls>` | HTML5 播放器 |
| 文本 | `<pre>` | 从后端获取文本内容 |
| 不支持 | 下载按钮 + 提示 | 引导用户下载 |

---

## 四、存储

已实现：`./var/files/{user_id}/{uuid}`，`PrivateObjectStorage` 管理。

不需要改动——文件下载时流式读取，预览时通过 `/api/files/{id}/download` 获取。

---

## 五、文件变更

| 文件 | 改动 |
|------|------|
| `api/files.py` | `preview_file` 增强，返回 `{type, url/content}` |
| `preview-drawer.tsx` | 重写预览逻辑，MIME 类型匹配 + 5 种渲染器 |
| `file-management.tsx` | 透传即可，不改 |

---

## 六、验证

```bash
cd backend && python -m pytest tests/test_files_api.py -v -k preview
cd frontend && npx next build
```
