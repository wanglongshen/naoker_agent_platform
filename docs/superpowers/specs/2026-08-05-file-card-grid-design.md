# 附件文件卡片网格（替代文本 chip）— 设计文档

日期：2026-08-05
状态：已确认

## 背景与问题

拖入/选择附件后，`attachment-input.tsx` 当前以**文本 chip** 展示文件（`composer-attachment-chip`：文件名 + ×）。用户参考手机端 AI 对话界面（文件卡片网格展示：类型图标 + 文件名 + 格式/大小），要求：

1. 附件以**文件卡片**展示：类型小图标（md/docx/pdf/图片等区分）+ 文件名 + 格式与大小（如 `Markdown · 8KB`）
2. **文件名超长显示省略号**（单行截断），完整名可悬停查看
3. 移除按钮（×）保留
4. 其他不做：快捷指令按钮（用户确认不要）、输入栏功能菜单（用户确认保持现状）、卡片点击预览（本期不做）

## 决策

1. **文件卡片**（替换 chip）：`composer-file-card`——浅灰圆角卡片，图标 + 两行文字（文件名 / 格式·大小）+ 右上角 ×
2. **类型图标**：按文件类型映射 4 类 SVG——文本（md/txt/markdown）、文档（doc/docx）、PDF、图片；其他类型通用文件图标
3. **格式名**：`Markdown` / `Word 文档` / `PDF` / `图片` / `其他`（从 File.type + 扩展名推导）
4. **大小格式化**：`formatFileSize`——B/KB/MB（如 `8KB`、`1.2MB`）
5. **省略号**：卡片定宽，文件名 `nowrap + overflow hidden + text-overflow ellipsis`，`title` 属性显示完整名
6. **布局**：卡片列表 flex wrap（自然换行）；位置不变（composer 内 toolbar 上方）
7. **addFiles 校验逻辑不变**（10 个/20MB/错误提示）——只改展示层

## 架构

```
attachment-input.tsx（展示层改造）
  └── files.map → <div class="composer-file-card" title={file.name}>
        ├── <span class="composer-file-card-icon">{getFileTypeIcon(file)}</span>
        ├── <div class="composer-file-card-body">
        │     ├── <div class="composer-file-card-name">{file.name}</div>   ← ellipsis
        │     └── <div class="composer-file-card-meta">{formatLabel} · {formatSize}</div>
        └── <button class="composer-file-card-remove">×</button>
lib/file-card-meta.ts（新，纯函数）
  ├── getFileTypeIcon(file: File): SVG key 或 JSX
  ├── getFileFormatLabel(file: File): string
  └── formatFileSize(bytes: number): string
```

## 组件明细

### 1. `frontend/src/lib/file-card-meta.ts`（新，纯函数）

```ts
export type FileTypeIconKey = "text" | "doc" | "pdf" | "image" | "generic";

export function getFileTypeIconKey(file: { name: string; type?: string }): FileTypeIconKey;
// 优先级：type 前缀 → 扩展名
// text/markdown、.md/.txt/.markdown → "text"
// .doc/.docx、application/msword 等 → "doc"
// application/pdf、.pdf → "pdf"
// image/*、.png/.jpg/.jpeg/.gif/.webp/.svg → "image"
// 其他 → "generic"

export function getFileFormatLabel(file: { name: string; type?: string }): string;
// "text" → "Markdown"（.md/.markdown）| "文本"（其他文本）
// "doc" → "Word 文档"
// "pdf" → "PDF"
// "image" → "图片"
// "generic" → 扩展名大写（如 "XLSX"）或无扩展名 → "文件"

export function formatFileSize(bytes: number): string;
// < 1024 → "{bytes}B"
// < 1024² → "{kb}KB"（四舍五入整数，如 8KB、512KB）
// else → "{mb}MB"（一位小数，如 1.2MB）
```

### 2. `attachment-input.tsx` 展示层改造

- import `getFileTypeIconKey/getFileFormatLabel/formatFileSize`（或从新 icon 组件）
- 替换 `composer-attachment-list` 内的 chip 渲染为卡片：

```tsx
{files.length > 0 ? (
  <div className="composer-file-card-grid" aria-label="已选择附件">
    {files.map(({ file, key }) => (
      <div key={key} className="composer-file-card" title={file.name}>
        <span className="composer-file-card-icon" data-file-icon={getFileTypeIconKey(file)}>
          {/* 按 key 渲染对应 SVG */}
        </span>
        <div className="composer-file-card-body">
          <div className="composer-file-card-name">{file.name}</div>
          <div className="composer-file-card-meta">
            {getFileFormatLabel(file)} · {formatFileSize(file.size)}
          </div>
        </div>
        <button
          type="button"
          className="composer-file-card-remove"
          aria-label={`移除 ${file.name}`}
          onClick={() => setFiles(files.filter((f) => f.key !== key))}
        >
          ×
        </button>
      </div>
    ))}
  </div>
) : null}
```

### 3. CSS（composer 相关样式文件）

```css
.composer-file-card-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0 0 8px;
}
.composer-file-card {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
  max-width: 220px;
  padding: 8px 10px;
  background: var(--agent-surface-muted, #f5f5f5);
  border-radius: 8px;
  position: relative;
}
.composer-file-card-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 150px;
  font-size: 13px;
  color: var(--agent-text, #333);
}
.composer-file-card-meta {
  font-size: 11px;
  color: #999;
  margin-top: 2px;
}
.composer-file-card-remove {
  flex-shrink: 0;
  margin-left: auto;
  /* 现有 chip remove 风格复用 */
}
```

（具体样式值沿用现有 CSS 变量体系——实现时读 composer 样式文件确认变量名）

## 错误处理

| 场景 | 处理 |
|---|---|
| 文件名超长 | ellipsis 截断 + title 悬停完整名 |
| 无扩展名文件 | 格式名"文件"，图标 generic |
| 未知类型 | 格式名扩展名大写，图标 generic |
| 移除 | 现有 setFiles filter（不变） |

## 测试策略

**新** `frontend/src/lib/file-card-meta.test.ts`：
- `getFileTypeIconKey`：md→text、docx→doc、pdf→pdf、png→image、xlsx→generic
- `getFileFormatLabel`：md→Markdown、docx→Word 文档、pdf→PDF、png→图片、xlsx→XLSX、无扩展→文件
- `formatFileSize`：512→512B、8192→8KB、1258291→1.2MB

**改** `attachment-input.test.tsx`：
- 卡片渲染：文件名/格式/大小文本出现（getByText）
- 移除按钮仍工作（querySelectorAll button + textContent 匹配——项目约束 #73）
- 现有 addFiles 校验测试不变

## 范围边界

**本期做**：
- file-card-meta 工具函数 + 测试
- attachment-input 卡片渲染 + CSS
- 省略号 + title

**本期不做**：
- 快捷指令按钮（用户确认不要）
- 输入栏功能菜单（用户确认保持现状）
- 卡片点击预览（现有预览机制不接入）
- 图标组件抽公共（本期 inline SVG，`data-file-icon` 标注便于测试）
