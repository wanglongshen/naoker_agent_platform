# 前端流式动画对齐方案

> 目标：将前端流式文本动画从"批量跳跃式"改为参考系统的"逐字流畅式"
> 原则：不改 CSS 结构，只改组件和 hook 逻辑

---

## 一、参考系统怎么做

### 打字动画：逐字 + 标点停顿 + 加速

```
useTypingText(text)
  └─ setTimeout(20ms) 逐 tick
       └─ 每 tick 只推 1 个字符
       └─ 遇到标点（。！？，；：）额外等 60ms
       └─ 待显示字符 > 7 时速度翻倍
       └─ 待显示字符 < 3 时恢复正常速度
```

### Markdown 渲染：一路到底，不拆分

```
answerText → useTypingText() → <ReactMarkdown>{typedText}</ReactMarkdown>
```

流式阶段全文直接喂给 ReactMarkdown。每 tick 多一个字符，ReactMarkdown 只更新新增部分。不拆分 completed blocks / active tail。

### 思考展示：逐字 + 光标

```
visible_thought_delta → reduceRunStream → visibleThoughtByStep
  → useTypingText(stepText) → "我将搜索..."逐字出现
  → <span className="thought-narrative-cursor">|</span>
```

---

## 二、本系统现在怎么做（差距）

### 打字动画：批量跳跃

```
useTypingText(text)
  └─ requestAnimationFrame（~16ms）
       └─ charactersPerFrame(backlog) 决定每帧推几个字
            backlog < 12: 2 字/帧
            backlog 13-48: 每帧推 6-12 字
            backlog 400+: 每帧推 48 字
       └─ 无标点停顿
       └─ 无加速逻辑
```

**效果：** 文字一批一批跳出来，不是逐字流式。

### Markdown 渲染：拆分 activeTail + completedBlocks

```
answerText → useStreamingMarkdown()
  → {completedBlocks: ["# 标题\n", "内容段落\n"], activeTail: "当前正在输"}
  → completedBlocks 用 ReactMarkdown 渲染
  → activeTail 用纯文本 <div> 渲染
```

**效果：** 正在写的半行是无格式纯文本，等换行后才变成 Markdown。看起来"闪"。

---

## 三、改动方案

### 改动 1：`useTypingText` — 改为逐字模式

| 项 | 改前 | 改后 |
|----|------|------|
| 驱动方式 | `requestAnimationFrame` | `setTimeout`（20ms） |
| 每帧推字 | 2-48 字（批量） | 1 字 |
| 标点停顿 | 无 | 60ms |
| 加速 | 无 | 待显示 > 7 时速度翻倍 |
| 减速动画支持 | 有 | 保留 |

```typescript
// 核心改动：advanceTypingAnimation 改为每 tick 只推 1 个字符
// 参考系统 typingAnimation.ts 的算法：
// - remainingMs 累加每 tick 的预算
// - 每 msPerCharacter 毫秒推 1 个字符
// - 标点后额外等 PUNCTUATION_PAUSE = 60ms
// - 积压 > 7 时 msPerCharacter 减半
```

### 改动 2：`FinalAnswerPanel` + `StreamingMarkdown` — 拆掉，用直接 ReactMarkdown

| 项 | 改前 | 改后 |
|----|------|------|
| 组件 | `StreamingMarkdown`（分块 + tail） | `ReactMarkdown`（全文直喂） |
| hook | `useStreamingMarkdown` | `useTypingText` |
| 流式文本 | activeTail 纯文本 | 逐字递增的 Markdown 文本 |

```tsx
// 改后 FinalAnswerPanel 核心：
const typed = useTypingText(answerToRender ?? "", { resetKey: answerStreamId });
const displayText = shouldAnimate ? typed : answerToRender;

<ReactMarkdown remarkPlugins={[remarkGfm]}>{displayText}</ReactMarkdown>
```

**可删除：**
- `useStreamingMarkdown` hook
- `streaming-markdown.ts` 库（`appendStreamingMarkdown`, `createStreamingMarkdownState`, `snapshotStreamingMarkdown`）
- `StreamingMarkdown` 组件（`streaming-markdown.tsx`）
- `SafeMarkdown` 组件（内联到 FinalAnswerPanel 即可）

### 改动 3：`typing-animation.ts` — 对齐参考系统算法

```typescript
// 参考系统核心算法（逐字 + 标点停顿 + 加速）:
const PUNCTUATION_PAUSE_MS = 60;
const ACCELERATION_THRESHOLD = 7;
const NORMAL_SPEED_MS = 20;
const FAST_SPEED_MS = 10;

function advanceTypingAnimation(state, elapsedMs) {
  let { displayedText, remainingMs } = state;
  const fullText = state.fullText;
  const backlog = fullText.length - displayedText.length;
  const msPerChar = backlog > ACCELERATION_THRESHOLD ? FAST_SPEED_MS : NORMAL_SPEED_MS;
  remainingMs += elapsedMs;

  let charsAdvanced = 0;
  while (remainingMs >= msPerChar && displayedText.length < fullText.length) {
    remainingMs -= msPerChar;
    displayedText = fullText.slice(0, displayedText.length + 1);
    charsAdvanced++;
    // 标点后额外等
    if (charsAdvanced > 0) {
      const lastChar = displayedText[displayedText.length - 1];
      if ("。！？，；：.!?,;:".includes(lastChar)) {
        remainingMs -= PUNCTUATION_PAUSE_MS;
        break;
      }
    }
  }
  return { displayedText, remainingMs, isComplete: displayedText.length === fullText.length };
}
```

### 改动 4：`ThoughtNarrative` — 保留，不动

思考展示已有 `useTypingText` + 光标，改动 1 自动生效。不需要额外修改。

---

## 四、不改的部分

以下本系统优势保留：

- RAF 批量（`use-run-event-stream.ts`）
- 滚动锚定 CSS（`overflow-anchor: auto`）
- 减速动画支持（`prefers-reduced-motion`）
- 事件分离（`narrativeEvents`）
- `React.memo` 优化
- PERF 诊断

---

## 五、文件变更清单

| 文件 | 操作 |
|------|------|
| `hooks/use-typing-text.ts` | 重写：setTimeout 驱动，逐字，标点停顿，加速 |
| `lib/typing-animation.ts` | 重写：参考系统算法 |
| `components/agent/final-answer-panel.tsx` | 改：用 useTypingText + ReactMarkdown 直接渲染 |
| `hooks/use-streaming-markdown.ts` | **删除** |
| `lib/streaming-markdown.ts` | **删除** |
| `components/agent/streaming-markdown.tsx` | **删除** |
| `components/agent/thought-narrative.tsx` | 不动（自动受益于 useTypingText 改进） |

---

## 六、执行顺序

```
Step 1: 重写 typing-animation.ts（纯函数，无依赖）
Step 2: 重写 use-typing-text.ts（依赖 Step 1）
Step 3: 改 final-answer-panel.tsx（依赖 Step 2）
Step 4: 删除 3 个旧文件（use-streaming-markdown.ts, streaming-markdown.ts, streaming-markdown.tsx）
Step 5: 清理引用，跑测试，构建验证
```

---

## 七、预期效果

```
改前：文字 6-48 个一批跳出来，正在写的半行无格式
改后：文字逐字流式出现，标点处自然停顿，全程 Markdown 格式正常
```
