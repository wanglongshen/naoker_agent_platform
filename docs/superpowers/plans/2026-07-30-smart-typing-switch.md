# 流式打字机智能切换方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 流式阶段答案直显（SSE 本身就是打字机），终态时用打字机动画平滑收尾，两者互不干扰。

**Architecture:** `useTypingText` 增加 200ms 冷却窗口检测。冷却期内（SSE 持续到达）→ 直接返回 targetText；冷却期后（SSE 停止）→ 启动打字机动画追平剩余 backlog。

**Tech Stack:** React 19 + TypeScript

## Global Constraints

- 打字机动画永久保留（终态回放和历史查看时使用）
- 流式阶段答案不打字机（SSE 逐段到达，本身就是打字机效果）
- 思考过程（ThoughtNarrative）不受影响，继续使用打字机动画
- 200ms 冷却窗口仅用于答案流式阶段（FinalAnswerPanel）

---

### Task 1: useTypingText 增加智能切换

**Files:**
- Modify: `frontend/src/hooks/use-typing-text.ts`（加冷却窗口逻辑）

**Interfaces:**
- Consumes: `targetText: string`（SSE 更新）
- Produces: 冷却期内返回 `targetText`，冷却期后返回 `displayedText`（打字机动画）

- [ ] **Step 1: 添加冷却窗口状态**

在 `useTypingText` 中添加两个 ref 和逻辑：

```typescript
const stableTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
const [isStable, setIsStable] = useState(true);

useEffect(() => {
  if (isFirstRenderRef.current) return;
  setIsStable(false);
  if (stableTimerRef.current) clearTimeout(stableTimerRef.current);
  stableTimerRef.current = setTimeout(() => setIsStable(true), 200);
  return () => { if (stableTimerRef.current) clearTimeout(stableTimerRef.current); };
}, [targetText]);
```

- [ ] **Step 2: 修改返回值**

将 `return displayedText` 改为根据冷却状态返回：

```typescript
return isStable ? displayedText : targetText;
```

**效果：**
- `targetText` 变化时 → `isStable = false` → 返回 `targetText`（直显）
- 200ms 无变化 → `isStable = true` → 返回 `displayedText`（打字机）
- 打字机持续运行（`speedMs` 驱动），`displayedText` 追 `targetText`
- 新文本到达 → `isStable = false` → 立刻切回直显

- [ ] **Step 3: 重置时清除定时器**

在 `resetKey` 变化时清除冷却定时器：

```typescript
useEffect(() => {
  // ... existing reset logic ...
  if (stableTimerRef.current) { clearTimeout(stableTimerRef.current); stableTimerRef.current = null; }
  setIsStable(true);
}, [resetKey]);
```

- [ ] **Step 4: 验证构建**

```bash
cd C:\01_agent_loop_pro\frontend && npx next build
```

Expected: 构建成功

- [ ] **Step 5: 运行测试**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/hooks/use-typing-text.test.ts -v
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/use-typing-text.ts
git commit -m "feat: smart typing animation — instant display during SSE, typewriter for finale"
```
