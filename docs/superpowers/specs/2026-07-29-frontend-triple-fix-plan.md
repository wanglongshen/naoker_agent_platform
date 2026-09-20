# 前端流式渲染三重优化方案

> 目标：动画启动抖动、表格渲染卡顿、计时器漂移三题并解
> 原则：最小改动，不恢复已删组件

---

## 一、问题诊断

### 问题 1：动画启动过早 → 抖动

```
SSE burst 到达（一帧内 20+ delta）
  → answerText 突增 30 字符
  → useTypingText 立即开始逐字播放
  → 下一个 RAF 帧又增 15 字符
  → useTypingText 检测到 targetText 变化，reset 从头播
  → 视觉：文字闪现又重置，抖动
```

根因：动画与 SSE 到达**无协调**。SSE 快速涌入时，动画不断被新文本打断重建。

### 问题 2：表格渲染卡顿

```
流式阶段每帧 ReactMarkdown 全量 AST 解析整个 growing text
  2000 字符 × 60fps × 6s = 360 次 AST 解析
  表格每增一行，重新解析整个表格 → O(n²) 累积开销
```

根因：ReactMarkdown 每次收到全文都重新解析，无法利用增量特性。

### 问题 3：计时器用浏览器时间

```
narrativeEvents 不含 answer_started
  → getThoughtDurationSeconds 退回到 nowMs（浏览器时钟）
  → 浏览器时钟与服务器时钟偏差 → 显示不准
```

根因：fallback 链的最后一环是浏览器 `Date.now()`。

---

## 二、解决方案

### 方案 A：动画延迟启动（解决问题 1）

增加 100ms 的"冷却窗口"：文本变化后等 100ms，期间无新变化才启动动画。

```typescript
// useTypingText 新增逻辑
const stableTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
const [isStable, setIsStable] = useState(false);

useEffect(() => {
  // 每次 targetText 变化，重置稳定标记
  setIsStable(false);
  if (stableTimerRef.current) clearTimeout(stableTimerRef.current);
  stableTimerRef.current = setTimeout(() => setIsStable(true), 100);
  return () => { if (stableTimerRef.current) clearTimeout(stableTimerRef.current); };
}, [targetText]);

// 只有稳定后才启用动画
const effectiveTarget = isStable ? targetText : displayedText;
```

**效果：** SSE 涌入期间直显文字（零延迟），涌入停止 100ms 后平滑切换到动画模式。用户看到的是先快速填充再回放——视觉上更流畅。

### 方案 B：表格流式虚拟化（解决问题 2）

不改 ReactMarkdown 本身，在流式期间用一个 CSS trick 减少表格的重排开销：

```css
/* 流式阶段 */
.final-answer-prose[data-streaming="true"] table {
  contain: layout style;  /* 隔离表格的重排影响 */
  table-layout: fixed;     /* 固定列宽，避免每行插入时重新计算 */
}
```

同时在 `FinalAnswerPanel` 中：

```tsx
<div className="final-answer-prose" data-streaming={!isTerminal}>
```

**原理：** CSS `contain: layout style` 让浏览器把表格当作独立布局单元，新增行不影响外部布局。`table-layout: fixed` 基于第一行确定列宽，后续行插入不触发全表重算。

**效果：** 表格逐行追加时卡顿感大幅降低，无需改动 JS 渲染逻辑。

### 方案 C：计时器改用服务端事件时间戳（解决问题 3）

当前已部分修复（用了最后事件的时间戳），但 `narrativeEvents` 排除了 `answer_started`，而 `events` 全量数组包含它。

最简单修复：`ThoughtNarrative` 接收的 props 中加上 `answerStartedAt` 时间戳，直接传给 `getThoughtDurationSeconds` 作为结束时间。

```tsx
// SessionConversationStream 中
const answerStartedEvent = streamState.events.find(e => e.event_type === "answer_started");
<ThoughtNarrative answerStartedAt={answerStartedEvent?.created_at ?? null} ... />
```

```typescript
// getThoughtDurationSeconds 新增参数
function getThoughtDurationSeconds(
  events, runStartedAt, runFinishedAt, nowMs,
  answerStartedAt?: string | null,  // ← 新增
) {
  const endedAtMs = answerStartedAt
    ? Date.parse(answerStartedAt)
    : answerStartedEvent
      ? Date.parse(answerStartedEvent.created_at)
      : /* fallback chain */;
}
```

**效果：** 计时器完全基于服务端时间戳，不受浏览器时钟影响。

---

## 三、复合方案

三个方案独立、无依赖，可全部实施：

| # | 改动位置 | 行数 | 效果 |
|---|---------|------|------|
| A | `useTypingText` 加 100ms debounce | +15 | SSE burst 期直显，停止后动画回放 |
| B | CSS `contain` + `table-layout:fixed` + `data-streaming` | +5 | 表格逐行追加无卡顿 |
| C | `ThoughtNarrative` 收 `answerStartedAt` prop | +10 | 计时器精准对齐服务端 |

---

## 四、验证

```bash
cd frontend && npx next build
cd frontend && npx vitest run src/hooks/use-typing-text.test.ts
```
