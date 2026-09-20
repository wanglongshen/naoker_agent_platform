# 智能自动滚动（useSmartAutoScroll）— 设计文档

日期：2026-08-05
状态：已确认

## 背景与问题

会话页（`frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx`）的滚动容器 `detail-single-column-scroll` 当前无任何智能滚动控制：

1. **新内容生成中**：新消息渲染后浏览器不强制滚动到底部——生成中的消息可能被视口截断，用户看不到最新内容
2. **用户浏览历史时**：如果新内容到达，页面行为不可预期（可能被拉回底部，打断阅读）
3. 用户明确需求：
   - **正在对话时**：新内容生成中自动下滑到正在生成的消息
   - **用户点击页面或向上滑动（意图浏览历史）**：停止自动跟随，保持当前位置不被打扰
   - **滚回底部**：恢复自动跟随

## 决策

1. **智能跟随开关 `shouldFollow`**（状态，默认 true）：跟随最新 vs 保持位置
2. **触发停止跟随**：① 用户上滑离开底部（scroll 事件，40px 阈值）② 用户点击页面（mousedown/touchstart——点击即浏览历史意图）
3. **触发恢复跟随**：用户滚回底部（scrollTop + clientHeight >= scrollHeight - 40px）
4. **新 run 开始（用户发消息）**：强制恢复跟随并滚到底部（新对话开始）
5. **实现为独立 hook** `useSmartAutoScroll(ref, deps)`——挂在滚动容器 ref 上，deps 变化（如 turns）时若 shouldFollow 则 scrollTo 底部；与容器解耦，可复用

## 架构

```
useSmartAutoScroll<T extends HTMLElement>(ref: RefObject<T | null>, deps: unknown[])

状态: shouldFollow (ref 存储, 不触发渲染)
监听:
  scroll  (容器)   → scrollTop+clientHeight < scrollHeight-40 → shouldFollow=false
                     scrollTop+clientHeight >= scrollHeight-40 → shouldFollow=true
  mousedown/touchstart (容器, capture) → shouldFollow=false
效果:
  deps 变化 && shouldFollow → ref.current.scrollTo({ top: scrollHeight })
暴露: { reset: () => void }  reset 置 shouldFollow=true 并滚到底部（新 run 调用）
```

## 组件明细

### 1. `frontend/src/hooks/use-smart-auto-scroll.ts`（新）

```ts
"use client";

import { useEffect, useRef } from "react";

const BOTTOM_THRESHOLD_PX = 40;

export function useSmartAutoScroll<T extends HTMLElement>(
  ref: React.RefObject<T | null>,
  deps: unknown[],
): { reset: () => void } {
  const shouldFollowRef = useRef(true);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const onScroll = () => {
      const nearBottom =
        el.scrollTop + el.clientHeight >= el.scrollHeight - BOTTOM_THRESHOLD_PX;
      shouldFollowRef.current = nearBottom;
    };
    const onPointerDown = () => {
      shouldFollowRef.current = false;
    };

    el.addEventListener("scroll", onScroll, { passive: true });
    el.addEventListener("mousedown", onPointerDown, true);
    el.addEventListener("touchstart", onPointerDown, { passive: true, capture: true });
    return () => {
      el.removeEventListener("scroll", onScroll);
      el.removeEventListener("mousedown", onPointerDown, true);
      el.removeEventListener("touchstart", onPointerDown, { capture: true } as EventListenerOptions);
    };
  }, [ref]);

  useEffect(() => {
    const el = ref.current;
    if (el && shouldFollowRef.current) {
      el.scrollTo({ top: el.scrollHeight });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const reset = () => {
    shouldFollowRef.current = true;
    const el = ref.current;
    if (el) {
      el.scrollTo({ top: el.scrollHeight });
    }
  };

  return { reset };
}
```

### 2. `page.tsx` 接入

```tsx
const scrollRef = useRef<HTMLDivElement>(null);
const { reset: resetScroll } = useSmartAutoScroll(scrollRef, [turns]);
// ...
<div className="detail-single-column-scroll" ref={scrollRef}>
```

`handleContinue` 中（发送新消息后 `loadSession()` 之前/之后）调用 `resetScroll()`：

```tsx
async function handleContinue(input: { goal: string; attachmentIds: string[] }) {
  if (!sessionId) return;
  try {
    resetScroll();
    invalidateSessionView(sessionId);
    await agentApi.createRun(sessionId, { ... });
    invalidateAgentSessions();
    await loadSession();
  } catch { ... }
}
```

### 3. 边界

- **40px 阈值**：滚动到底部 ±40px 视为"底部"（防误判；内容高动态变化时小偏差可接受）
- **mousedown 停止跟随**：点击 composer 输入框也会 stop——但用户发消息时 `resetScroll()` 恢复，可接受
- **历史会话（无流式）**：无新内容到达 → deps 不变 → 无强制滚动，正常浏览
- **deps 用 turns**：turns 每次加载/刷新变化 → 若 shouldFollow 则跟随；流式事件更新 turns（若通过流式更新）→ 自然跟随
- 注意：`page.tsx` 当前从 `loadSession()` 一次性加载（非流式更新 turns）——turns 变化仅在加载完成时。若流式更新也走同一 turns 状态（后续改动），hook 自动覆盖

## 测试策略

`frontend/src/hooks/use-smart-auto-scroll.test.tsx`（新建，jsdom + vitest）：

- 新 run 开始时 reset() 滚动到底部（scrollTo mock 断言）
- 用户上滑（触发 scroll 事件且不接近底部）→ 新 deps 变化不滚动
- 用户滚回底部（scroll 事件接近底部）→ 恢复跟随，deps 变化滚动
- mousedown → 停止跟随，deps 变化不滚动
- 组件卸载时监听器移除

## 范围边界

**本期做**：
- useSmartAutoScroll hook + 测试
- page.tsx 接入（scrollRef + resetScroll）
- handleContinue 调 resetScroll

**本期不做**：
- 流式更新 turns 的接入（当前 loadSession 一次性加载；hook 已兼容未来流式）
- 其他页面复用（hook 独立可复用，但不主动改其他页面）
- 滚动平滑动画（用 scrollTo 默认行为）

## 数据流示例

```
用户发送新消息 → resetScroll() → shouldFollow=true + 滚到底部
→ 新 run 开始生成 → loadSession 完成 turns 更新 → deps 变化 → 跟随滚动
用户上滑查看历史 → scroll 事件 → shouldFollow=false
→ 新内容到达（deps 变化）→ 不滚动（保持位置）
用户滚回底部 → scroll 事件 → shouldFollow=true
→ 后续新内容 → 跟随滚动
```
