# 附件文件卡片网格（替代文本 chip）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the plain-text attachment chips with file cards — type icon + filename (ellipsis on overflow) + format·size, keep remove button and all addFiles validation unchanged.

**Architecture:** New pure-function lib `file-card-meta.ts` (type-icon key / format label / size formatter) + presentation-layer change in `attachment-input.tsx` (chip → card grid) + CSS in `agent-globals.css`. No behavior change to validation, drag-drop, or submit flow.

**Tech Stack:** TypeScript / React 18 / Next.js / vitest / jsdom.

## Global Constraints

- addFiles 校验逻辑不变（10 个 / 20MB / 错误提示）——只改展示层
- 文件名超长 → 单行 ellipsis + `title` 悬停完整名
- 类型图标 5 类：text / doc / pdf / image / generic（`data-file-icon` 属性标注，便于测试）
- 格式名映射：md/markdown→Markdown、其他文本→文本、doc/docx→Word 文档、pdf→PDF、image→图片、其他→扩展名大写（无扩展→文件）
- 大小格式：B / KB（整数）/ MB（一位小数）
- 测试用 querySelectorAll/textContent（jsdom 病理约束 #73/#75，禁止页面级 byRole）
- 既有前端测试通过（524 passed / 11 既有失败基线）
- commit 从仓库根 C:\01_agent_loop_pro 执行，仓库根相对路径

---

### Task 1: file-card-meta 工具函数 + 测试

**Files:**
- Create: `frontend/src/lib/file-card-meta.ts`
- Create: `frontend/src/lib/file-card-meta.test.ts`

**Interfaces:**
- Consumes: 无
- Produces:
  - `FileTypeIconKey = "text" | "doc" | "pdf" | "image" | "generic"`
  - `getFileTypeIconKey(file: { name: string; type?: string }): FileTypeIconKey`
  - `getFileFormatLabel(file: { name: string; type?: string }): string`
  - `formatFileSize(bytes: number): string`

- [ ] **Step 1: Write the failing tests**（新建 `frontend/src/lib/file-card-meta.test.ts`）

```ts
import { describe, it, expect } from "vitest";
import {
  formatFileSize,
  getFileFormatLabel,
  getFileTypeIconKey,
} from "./file-card-meta";

describe("getFileTypeIconKey", () => {
  it("maps markdown and text to text", () => {
    expect(getFileTypeIconKey({ name: "a.md", type: "text/markdown" })).toBe("text");
    expect(getFileTypeIconKey({ name: "b.txt", type: "text/plain" })).toBe("text");
    expect(getFileTypeIconKey({ name: "c.markdown" })).toBe("text");
  });

  it("maps docx/doc to doc", () => {
    expect(getFileTypeIconKey({ name: "d.docx" })).toBe("doc");
    expect(getFileTypeIconKey({ name: "e.doc", type: "application/msword" })).toBe("doc");
  });

  it("maps pdf to pdf", () => {
    expect(getFileTypeIconKey({ name: "f.pdf", type: "application/pdf" })).toBe("pdf");
  });

  it("maps images to image", () => {
    expect(getFileTypeIconKey({ name: "g.png", type: "image/png" })).toBe("image");
    expect(getFileTypeIconKey({ name: "h.webp" })).toBe("image");
  });

  it("falls back to generic for unknown types", () => {
    expect(getFileTypeIconKey({ name: "i.xlsx" })).toBe("generic");
    expect(getFileTypeIconKey({ name: "j" })).toBe("generic");
  });
});

describe("getFileFormatLabel", () => {
  it("labels markdown distinctly", () => {
    expect(getFileFormatLabel({ name: "a.md", type: "text/markdown" })).toBe("Markdown");
    expect(getFileFormatLabel({ name: "b.markdown" })).toBe("Markdown");
  });

  it("labels other text as 文本", () => {
    expect(getFileFormatLabel({ name: "c.txt", type: "text/plain" })).toBe("文本");
  });

  it("labels doc, pdf, image", () => {
    expect(getFileFormatLabel({ name: "d.docx" })).toBe("Word 文档");
    expect(getFileFormatLabel({ name: "e.pdf" })).toBe("PDF");
    expect(getFileFormatLabel({ name: "f.png" })).toBe("图片");
  });

  it("labels unknown by uppercase extension, extensionless as 文件", () => {
    expect(getFileFormatLabel({ name: "g.xlsx" })).toBe("XLSX");
    expect(getFileFormatLabel({ name: "h" })).toBe("文件");
  });
});

describe("formatFileSize", () => {
  it("formats bytes", () => {
    expect(formatFileSize(512)).toBe("512B");
  });

  it("formats kilobytes as integers", () => {
    expect(formatFileSize(8192)).toBe("8KB");
    expect(formatFileSize(1536)).toBe("2KB");
  });

  it("formats megabytes with one decimal", () => {
    expect(formatFileSize(1258291)).toBe("1.2MB");
    expect(formatFileSize(10_485_760)).toBe("10MB");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\frontend
npx vitest run src/lib/file-card-meta.test.ts
```
Expected: FAIL（Cannot find module './file-card-meta'）

- [ ] **Step 3: Implement**（新建 `frontend/src/lib/file-card-meta.ts`）

```ts
export type FileTypeIconKey = "text" | "doc" | "pdf" | "image" | "generic";

const TEXT_EXTENSIONS = new Set(["md", "markdown", "txt", "text"]);
const DOC_EXTENSIONS = new Set(["doc", "docx"]);
const PDF_EXTENSIONS = new Set(["pdf"]);
const IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico"]);

function extensionOf(name: string): string {
  const idx = name.lastIndexOf(".");
  if (idx < 0 || idx === name.length - 1) return "";
  return name.slice(idx + 1).toLowerCase();
}

export function getFileTypeIconKey(file: { name: string; type?: string }): FileTypeIconKey {
  const mime = (file.type || "").toLowerCase();
  if (mime.startsWith("image/")) return "image";
  if (mime === "application/pdf") return "pdf";
  if (mime.startsWith("text/") || mime === "application/json" || mime.includes("markdown")) {
    const ext = extensionOf(file.name);
    if (ext && ext !== "md" && ext !== "markdown" && ext !== "txt") return "generic";
    return "text";
  }
  const ext = extensionOf(file.name);
  if (TEXT_EXTENSIONS.has(ext)) return "text";
  if (DOC_EXTENSIONS.has(ext)) return "doc";
  if (PDF_EXTENSIONS.has(ext)) return "pdf";
  if (IMAGE_EXTENSIONS.has(ext)) return "image";
  return "generic";
}

export function getFileFormatLabel(file: { name: string; type?: string }): string {
  const key = getFileTypeIconKey(file);
  const ext = extensionOf(file.name);
  if (key === "text") {
    if (ext === "md" || ext === "markdown") return "Markdown";
    return "文本";
  }
  if (key === "doc") return "Word 文档";
  if (key === "pdf") return "PDF";
  if (key === "image") return "图片";
  return ext ? ext.toUpperCase() : "文件";
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${Math.round(kb)}KB`;
  const mb = kb / 1024;
  const rounded = Math.round(mb * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)}MB`;
}
```

注意：`formatFileSize(10_485_760)` = 10MB → `rounded=10` → `10MB`（无小数）✅；`1.2MB` → `1.2` ✅。

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\frontend
npx vitest run src/lib/file-card-meta.test.ts
```
Expected: PASS（13 测试）

- [ ] **Step 5: Commit**（从仓库根）

```bash
git add frontend/src/lib/file-card-meta.ts frontend/src/lib/file-card-meta.test.ts
git commit -m "feat: file card meta helpers — type icon key, format label, size formatter"
```

---

### Task 2: attachment-input 卡片渲染 + CSS

**Files:**
- Modify: `frontend/src/components/agent/attachment-input.tsx`
- Modify: `frontend/src/app/agent-globals.css`
- Test: `frontend/src/components/agent/attachment-input.test.tsx`（先读现有测试）

**Interfaces:**
- Consumes: Task 1 `getFileTypeIconKey/getFileFormatLabel/formatFileSize`
- Produces: 卡片网格渲染（chip 替换）；addFiles/拖拽/提交逻辑不变

- [ ] **Step 1: Write the failing tests**（追加到 `frontend/src/components/agent/attachment-input.test.tsx`——先读现有测试文件确认渲染 helper/模式）

```tsx
describe("AttachmentInput file cards", () => {
  function makeFile(name: string, size = 8192, type = "text/markdown"): File {
    return new File(["x".repeat(size)], name, { type });
  }

  it("renders file cards with name, format and size", () => {
    const { container } = render(
      <AttachmentInput pendingFiles={[{ file: makeFile("脑壳儿_Brief输入模板.md"), key: "k1" }]} onPendingFilesChange={() => {}} />,
    );
    const card = container.querySelector(".composer-file-card");
    expect(card).toBeTruthy();
    expect(card!.querySelector(".composer-file-card-name")!.textContent).toContain("脑壳儿_Brief输入模板.md");
    expect(card!.querySelector(".composer-file-card-meta")!.textContent).toContain("Markdown");
    expect(card!.querySelector(".composer-file-card-meta")!.textContent).toContain("8KB");
  });

  it("marks icon type via data attribute", () => {
    const { container } = render(
      <AttachmentInput pendingFiles={[{ file: makeFile("plan.docx", 1024, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"), key: "k2" }]} onPendingFilesChange={() => {}} />,
    );
    const icon = container.querySelector(".composer-file-card-icon");
    expect(icon?.getAttribute("data-file-icon")).toBe("doc");
  });

  it("keeps remove button working", () => {
    const onChange = vi.fn();
    const { container } = render(
      <AttachmentInput pendingFiles={[{ file: makeFile("a.md"), key: "k1" }]} onPendingFilesChange={onChange} />,
    );
    const buttons = Array.from(container.querySelectorAll("button"));
    const remove = buttons.find((b) => b.textContent?.includes("×"));
    expect(remove).toBeTruthy();
    remove!.click();
    expect(onChange).toHaveBeenCalledWith([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\frontend
npx vitest run src/components/agent/attachment-input.test.tsx
```
Expected: FAIL（`.composer-file-card` 不存在——当前是 chip）

- [ ] **Step 3: Implement**

**3a.** `attachment-input.tsx`：
- 顶部 import：

```tsx
import { formatFileSize, getFileFormatLabel, getFileTypeIconKey, type FileTypeIconKey } from "@/lib/file-card-meta";
```

- 加图标渲染辅助（组件文件内）：

```tsx
function FileTypeIcon({ type }: { type: FileTypeIconKey }) {
  const common = { width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  switch (type) {
    case "text":
      return (
        <svg aria-hidden="true" {...common}>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M8 13h8M8 17h5" />
        </svg>
      );
    case "doc":
      return (
        <svg aria-hidden="true" {...common}>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M12 18v-6M9 15h6" />
        </svg>
      );
    case "pdf":
      return (
        <svg aria-hidden="true" {...common}>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M9 12v6M9 12a2 2 0 0 1 2-2h1v6h-1a2 2 0 0 1-2-2z" />
        </svg>
      );
    case "image":
      return (
        <svg aria-hidden="true" {...common}>
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <circle cx="9" cy="10" r="2" />
          <path d="m5 19 5-5 3 3 4-4 2 2" />
        </svg>
      );
    default:
      return (
        <svg aria-hidden="true" {...common}>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6" />
        </svg>
      );
  }
}
```

- 渲染替换（`composer-attachment-list` 块内）：

```tsx
      {files.length > 0 ? (
        <div className="composer-file-card-grid" aria-label="已选择附件">
          {files.map(({ file, key }) => (
            <div key={key} className="composer-file-card" title={file.name}>
              <span className="composer-file-card-icon" data-file-icon={getFileTypeIconKey(file)}>
                <FileTypeIcon type={getFileTypeIconKey(file)} />
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

**3b.** CSS（`agent-globals.css`，替换/追加在 `.chat-composer .composer-attachment-list` 之后）：

```css
.chat-composer .composer-file-card-grid {
  position: absolute;
  left: 0;
  bottom: 48px;
  width: max-content;
  max-width: 440px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-content: flex-end;
}

.chat-composer .composer-file-card {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
  max-width: 200px;
  padding: 8px 10px;
  border: 1px solid #dce3f2;
  border-radius: 10px;
  background: white;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.08);
}

.chat-composer .composer-file-card-icon {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 6px;
  background: #eef2ff;
  color: var(--agent-blue);
}

.chat-composer .composer-file-card-body {
  min-width: 0;
  flex: 1;
}

.chat-composer .composer-file-card-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 120px;
  font-size: 12px;
  color: #334155;
}

.chat-composer .composer-file-card-meta {
  font-size: 11px;
  color: #99a1b3;
  margin-top: 2px;
}

.chat-composer .composer-file-card-remove {
  flex-shrink: 0;
  margin-left: 4px;
  padding: 0 2px;
  border: 0;
  background: transparent;
  color: #99a1b3;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
}

.chat-composer .composer-file-card-remove:hover {
  color: #d14343;
}
```

（`--agent-blue` 变量已存在于 agent-globals.css:10，确认后使用）

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\frontend
npx vitest run src/components/agent/attachment-input.test.tsx
```
Expected: PASS（含新卡片测试）

- [ ] **Step 5: 相关回归**

```
cd C:\01_agent_loop_pro\frontend
npx vitest run src/components/agent/chat-composer.test.tsx
```
Expected: PASS（addFiles/拖拽/提交测试不受展示层影响）

- [ ] **Step 6: Commit**（从仓库根）

```bash
git add frontend/src/components/agent/attachment-input.tsx frontend/src/app/agent-globals.css frontend/src/components/agent/attachment-input.test.tsx
git commit -m "feat: file card grid for composer attachments with type icon and size"
```

---

### Task 3: 集成验证

**Files:**
- Verify only（不改代码）

- [ ] **Step 1: 前端全量**

```
cd C:\01_agent_loop_pro\frontend
npx vitest run
```
Expected: 既有结果（524+ passed；11 个既有失败保持——若增加则调查）

- [ ] **Step 2: 类型检查**

```
cd C:\01_agent_loop_pro\frontend
npx tsc --noEmit
```
Expected: 无新错误（既有测试文件错误除外——与本任务无关）

- [ ] **Step 3: Report** — 无提交；回报用户：测试数、手动验证要点（拖入文件 → 卡片显示图标/文件名/格式·大小；超长文件名省略号 + 悬停完整名；移除正常）
