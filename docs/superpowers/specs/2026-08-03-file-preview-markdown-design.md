# 文件预览增强设计：Markdown 渲染 + 文档类文字版

> 日期：2026-08-03 · 状态：已批准（用户确认范围：md 渲染 + 文档类）

## 目标

"我的文件"（`/agent/files`）中点击文件"预览"时，按文件格式展示内容：
- **Markdown（`text/markdown`）**：渲染成 Markdown 文档（标题、表格、代码块、列表、链接生效）
- **docx**：后端提取纯文本，前端按排版文本展示
- **pdf / 图片 / 音视频**：维持现状（浏览器原生流式展示）
- 其他：维持"预览不可用 + 下载"提示

## 现状缺口

- `PreviewDrawer`（frontend/src/components/files/preview-drawer.tsx）将 `text/*` 一律显示为纯文本 `<pre>`，`text/markdown` 未渲染
- `docx`（application/vnd.openxmlformats-officedocument.wordprocessingml.document）落入 `unsupported`
- 文本类内容前端直接 fetch `/download` 端点（二进制不可读，docx 无法用）

## 改动

### 后端 `backend/app/api/files.py` `preview_file`

在 `text/` 分支之后新增 docx 分支：

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

pdf/图片/音视频分支不变。

### 前端 `frontend/src/components/files/preview-drawer.tsx`

1. 分类新增：`markdown`（`media_type === "text/markdown"`）与 `document`（docx mime）
2. 数据获取统一：text/markdown/document 类别改调 `GET /api/files/{id}/preview`，取响应 `data.content`
3. 渲染：
   - `markdown` → `react-markdown` + `remarkGfm` + `skipHtml`；URL 安全（外部链接 target=_blank + rel=noreferrer）、表格/代码块横向滚动（沿用 agent 对话渲染规则）
   - `text` / `document` → 现有 `<pre>` 排版文本
4. 其余类别（pdf/image/video/audio/unsupported）不变

### 测试

- 后端：`backend/tests/test_files_preview.py`（新建）——插入 docx FileObject（storage_key 指向 tmp 文件）+ monkeypatch `app.api.files.extract_file_text`，断言返回 `{type: "text", content}`；md 文件返回文本内容；pdf 维持 stream；断言 docx 提取失败时的兜底文案
- 前端：`frontend/src/components/files/preview-drawer.test.tsx`（新建）——mock fetch：md 渲染出标题/表格元素；docx 显示文本；断言 fetch 目标为 `/preview` 端点；非文本类别不触发 fetch

## 不在范围内

- xlsx / pptx 预览（保持 unsupported）
- csv 表格化
- 前端 Markdown 组件抽取重构（preview-drawer 内联实现，与 progressive-markdown 的映射规则保持一致）
