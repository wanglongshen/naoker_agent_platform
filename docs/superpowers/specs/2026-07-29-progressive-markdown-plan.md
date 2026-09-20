# 流式 Markdown 分段渲染方案

> 问题：ReactMarkdown 每帧全文重解析 → 图标/表格卡死  
> 方案：分段渲染——已完成的段落用 ReactMarkdown（只渲染一次），正在写的尾部用纯文本

---

## 一、根因

```
每帧 typing animation 推 N 个新字
  → displayText 全量传给 ReactMarkdown
  → ReactMarkdown 做全量 AST 解析（remark-parse → mdast → hast → React 元素）
  → 2000 字 × 60fps = 每秒 120,000 字符的 AST 解析
  → 表格节点 O(n²) 累积开销
  → 浏览器主线程卡死
```

**ReactMarkdown 是全量解析器，不支持增量。** 每帧都从第 0 字开始解析到最新字。这是 fundamental 的设计问题。

---

## 二、方案：分段渲染

### 核心思路

```
typedText = useTypingText(answerText)  ← 逐字动画，不变

typedText 按 "\n\n"（空行）切割为段落
  ├─ 最后一段（未完成）→ 纯文本 <pre>，不经过 ReactMarkdown
  └─ 前面的段落（已完成）→ ReactMarkdown，React.memo 记忆，不再重解析
```

### 为什么表格不卡了

```
表格 markdown 示例：
| 项目 | 价格 |
|------|------|
| 交通 | 100  |
| 住宿 | 500  |  ← 正在写这一行

切割：
  已完成段落: ""（表格前没有空行，整个表格是一个段落）
  正在写的尾部: "| 项目 | 价格 |\n|------|------|\n| 交通 | 100  |\n| 住宿 | 500  |"
  → 尾部作为纯文本，不经过 ReactMarkdown → 不解析 → 不卡
  → 直到空行出现（表格结束），整个表格一次性交给 ReactMarkdown → 渲染一次
```

### 代码结构

```tsx
function ProgressiveMarkdown({ text, terminal }: { text: string; terminal: boolean }) {
  if (terminal) {
    // 终态：全文 ReactMarkdown
    return <SafeMarkdown content={text} />;
  }

  // 流式：拆分段落
  const paragraphs = text.split("\n\n");
  const completed = paragraphs.slice(0, -1);
  const activeTail = paragraphs[paragraphs.length - 1] ?? "";

  return (
    <>
      {completed.map((p, i) => (
        <CompletedBlock key={i} content={p} />
      ))}
      {activeTail ? <pre className="streaming-tail">{activeTail}</pre> : null}
    </>
  );
}

const CompletedBlock = React.memo(({ content }: { content: string }) => (
  <SafeMarkdown content={content} />
));
```

**效果：**
- 每个段落只在完成后经过一次 ReactMarkdown
- 正在写的行是纯文本，零解析开销
- 表格在所有行到达后一次性渲染
- 图标/emoji 不受影响（它们通常在一行内，不跨段落）

---

## 三、文件变更

| 文件 | 操作 |
|------|------|
| `components/agent/progressive-markdown.tsx` | **新增**：分段渲染组件 |
| `components/agent/final-answer-panel.tsx` | 改：用 ProgressiveMarkdown 替代内联 ReactMarkdown |

---

## 四、CSS

```css
.streaming-tail {
  white-space: pre-wrap;
  font-family: inherit;
  font-size: inherit;
  color: inherit;
  margin: 0;
}
```

---

## 五、副作用：流式阶段无格式

**妥协：** 流式时正在写的段落是纯文本（黑字白底），不是渲染后的 Markdown。这看起来很朴素但是零性能开销。一旦写完（空行），立刻升级为格式化的 Markdown。

这是 ChatMarkdown 产品（ChatGPT、Claude）的流式渲染通用了的：

---

## 六、验证

```bash
cd frontend && npx next build
```
