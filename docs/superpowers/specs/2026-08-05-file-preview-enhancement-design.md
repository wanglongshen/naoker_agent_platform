# 文件预览增强设计

日期：2026-08-05
状态：已批准

## 背景与目标

文件管理（/agent/files、/files）的预览抽屉（frontend/src/components/files/preview-drawer.tsx）中 PDF 无法预览（iframe 空白），且 xlsx/pptx 等常用 Office 文档显示"预览不可用"。目标：修复 PDF 预览，扩展 Office 文档文本预览，现有可预览格式保持不变。

## 根因

前端 iframe/媒体 src 使用了 `/api/files/{id}/download?download=1`。后端 download 端点（backend/app/api/files.py:326）对 `download=1` 返回 `Content-Disposition: attachment`（强制下载），浏览器对 iframe 内嵌 PDF 会直接触发下载而非渲染。端点默认（无参数）返回 `inline`，后端早已支持内嵌预览——前端只需去掉参数。

## 第一节：PDF 修复与 URL 统一

- preview-drawer.tsx 中 `renderPreview()` 的 URL 构造改为 `/api/files/${file.id}/download`（去掉 `?download=1`）
- 适用：pdf（iframe）、image（img）、video（video）、audio（audio）四个分支统一使用该 inline URL
- 效果：PDF 由浏览器原生渲染；图片/音视频行为不变（子资源本就忽略 attachment，inline 后效果一致）

## 第二节：Office 文档文本预览

**后端**（backend/app/api/files.py `/preview` 端点，第 360-369 行的 docx 分支扩展为多类型）：
- 新增两个 media_type 分支，复用 `from app.services.agent.file_reader import extract_file_text`（已支持 xlsx/pptx 提取）：
  - `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`（xlsx）
  - `application/vnd.openxmlformats-officedocument.presentationml.presentation`（pptx）
- 提取失败兜底返回 `{"type": "text", "content": "无法读取文档内容。"}`（与 docx 分支一致）
- 老 doc（application/msword）不接入（无提取器），保持 unsupported

**前端**（preview-drawer.tsx `classifyPreview`）：
- 新增两个 media_type 常量判断，归入现有 `"document"` 类别（TEXT_CATEGORIES 已含 "document"，自动走 /preview 文本提取）
- xlsx 显示提取的单元格文本、pptx 显示各页文本（与 docx 相同的 pre 样式）

## 保持不变

- text/markdown/image/video/audio 现有预览行为
- unsupported 分类的下载兜底（zip/rar/7z/二进制等）
- 下载按钮与 download=1 参数（预览之外的场景不变）

## 测试

- 前端 preview-drawer.test.tsx：新增断言——pdf 文件的 iframe src 不含 `download=1`；xlsx/pptx 文件触发 `/api/files/{id}/preview` 请求
- 后端 tests：preview 端点对 xlsx/pptx 返回提取文本（构造最小 xlsx/pptx 字节或 mock extract_file_text）
- 既有测试全部保持通过（前端 preview-drawer.test.tsx 现有用例、后端 files 相关测试）

**验收**：前端 preview-drawer 测试全绿；后端 files 相关测试全绿；浏览器实际验证 PDF 内嵌渲染。
