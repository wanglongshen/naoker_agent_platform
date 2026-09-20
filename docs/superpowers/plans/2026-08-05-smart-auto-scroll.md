# 智能自动滚动（useSmartAutoScroll）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add smart auto-scroll to the agent session page — follow the latest message while content is generating, stop following when the user clicks the page or scrolls up (browsing history), resume when scrolled back to bottom, and force-follow on new message send.

**Architecture:** A reusable hook `useSmartAutoScroll(ref, deps)` attached to the session page scroll container (`detail-single-column-scroll`). `shouldFollowRef` tracks follow state (default true). Scroll events set false when leaving the bottom 40px, true when back at bottom. Pointer-down events (click/touch) set false. On deps change (turns updated), scrolls to bottom only when following. `reset()` force-follows for new runs.

**Tech Stack:** TypeScript / React 18 / Next.js / vitest / jsdom.

## Global Constraints

- 遵循 frontend/AGENTS.md 的 Next.js 规则（`node_modules/next/dist/docs/` 为权威文档）
- hook 挂载在 page.tsx 的 `detail-single-column-scroll` 滚动容器上（page.tsx:139）
- `reset()` 在 `handleContinue` 发送新消息时调用
- 阈值 40px；mousedown/touchstart 停止跟随；滚回底部恢复
- 既有前端测试必须通过（不新增失败；已知 11 个既有失败与本任务无关）
- commit 从仓库根 C:\01_agent_loop_pro 执行，仓库根相对路径
- 测试用 document.querySelectorAll / getByText 等文本查询（jsdom getComputedStyle 病理：禁止页面级 byRole，见项目约束 #73/#75）

---

### Task 1: useSmartAutoScroll hook + 测试

**Files:**
- Create: `frontend/src/hooks/use-smart-auto-scroll.ts`
- Create: `frontend/src/hooks/use-smart-auto-scroll.test.tsx`

**Interfaces:**
- Consumes: React useRef/useEffect
- Produces:
  - `useSmartAutoScroll<T extends HTMLElement>(ref: React.RefObject<T | null>, deps: unknown[]): { reset: () => void }`
  - `reset()`：置 shouldFollow=true 并滚动到底部（新 run 调用）

- [ ] **Step 1: Write the failing tests**（新建 `frontend/src/hooks/use-smart-auto-scroll.test.tsx`）

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useSmartAutoScroll } from "./use-smart-auto-scroll";

function makeEl() {
  const el = document.createElement("div");
  el.scrollTop = 0;
  el.clientHeight = 500;
  Object.defineProperty(el, "scrollHeight", { value: 1200, configurable: true });
  el.scrollTo = vi.fn(function (this: HTMLDivElement, opts?: ScrollToOptions) {
    if (opts && typeof opts.top === "number") this.scrollTop = opts.top;
  });
  return el;
}

function fireScroll(el: HTMLElement, scrollTop: number) {
  el.scrollTop = scrollTop;
  el.dispatchEvent(new Event("scroll"));
}

describe("useSmartAutoScroll", () => {
  let el: HTMLDivElement;
  let ref: React.RefObject<HTMLDivElement | null>;

  beforeEach(() => {
    el = makeEl();
    ref = { current: el } as React.RefObject<HTMLDivElement | null>;
  });

  it("scrolls to bottom on deps change when following", () => {
    renderHook(({ deps }) => useSmartAutoScroll(ref, deps), {
      initialProps: { deps: [1] },
    });
    expect(el.scrollTo).not.toHaveBeenCalled();
    const { rerender } = renderHook(
      ({ deps }) => useSmartAutoScroll(ref, deps),
      { initialProps: { deps: [1] } },
    );
    rerender({ deps: [2] });
    expect(el.scrollTo).toHaveBeenCalledWith({ top: 1200 });
  });

  it("does not scroll when user scrolled away from bottom", () => {
    const { rerender } = renderHook(
      ({ deps }) => useSmartAutoScroll(ref, deps),
      { initialProps: { deps: [1] } },
    );
    fireScroll(el, 200); // 远离底部 → shouldFollow=false
    rerender({ deps: [2] });
    expect(el.scrollTo).not.toHaveBeenCalled();
  });

  it("resumes following when scrolled back to bottom", () => {
    const { rerender } = renderHook(
      ({ deps }) => useSmartAutoScroll(ref, deps),
      { initialProps: { deps: [1] } },
    );
    fireScroll(el, 200);
    rerender({ deps: [2] });
    expect(el.scrollTo).not.toHaveBeenCalled();
    fireScroll(el, 700); // 1200-500-40=660 → 回底部 → shouldFollow=true
    rerender({ deps: [3] });
    expect(el.scrollTo).toHaveBeenCalledWith({ top: 1200 });
  });

  it("stops following on mousedown", () => {
    const { rerender } = renderHook(
      ({ deps }) => useSmartAutoScroll(ref, deps),
      { initialProps: { deps: [1] } },
    );
    el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    rerender({ deps: [2] });
    expect(el.scrollTo).not.toHaveBeenCalled();
  });

  it("reset force-scrolls to bottom and restores following", () => {
    const { result, rerender } = renderHook(
      ({ deps }) => useSmartAutoScroll(ref, deps),
      { initialProps: { deps: [1] } },
    );
    fireScroll(el, 200);
    rerender({ deps: [2] });
    expect(el.scrollTo).not.toHaveBeenCalled();
    result.current.reset();
    expect(el.scrollTo).toHaveBeenCalledWith({ top: 1200 });
    rerender({ deps: [3] });
    expect(el.scrollTo).toHaveBeenCalledWith({ top: 1200 });
  });

  it("removes listeners on unmount", () => {
    const removeSpy = vi.spyOn(el, "removeEventListener");
    const { unmount } = renderHook(() => useSmartAutoScroll(ref, [1]));
    unmount();
    expect(removeSpy).toHaveBeenCalledWith("scroll", expect.any(Function));
    expect(removeSpy).toHaveBeenCalledWith("mousedown", expect.any(Function), true);
  });
});
```

注意：第二个测试块重复 renderHook 是为了拿 rerender——**实际只保留一份**，以第一次 `renderHook` 为准，用解构出的 `rerender`/`result`。

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\frontend
npx vitest run src/hooks/use-smart-auto-scroll.test.tsx
```
Expected: FAIL（Cannot find module './use-smart-auto-scroll'）

- [ ] **Step 3: Implement**（新建 `frontend/src/hooks/use-smart-auto-scroll.ts`）

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
    el.addEventListener("touchstart", onPointerDown, {
      passive: true,
      capture: true,
    });
    return () => {
      el.removeEventListener("scroll", onScroll);
      el.removeEventListener("mousedown", onPointerDown, true);
      el.removeEventListener("touchstart", onPointerDown, {
        capture: true,
      } as EventListenerOptions);
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

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\frontend
npx vitest run src/hooks/use-smart-auto-scroll.test.tsx
```
Expected: PASS（6 测试）

- [ ] **Step 5: Commit**（从仓库根）

```bash
git add frontend/src/hooks/use-smart-auto-scroll.ts frontend/src/hooks/use-smart-auto-scroll.test.tsx
git commit -m "feat: smart auto-scroll hook with follow-stop on user browsing"
```

---

### Task 2: 接入会话页（scrollRef + reset）

**Files:**
- Modify: `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx`
- Test: 无新测试（页面积分靠既有页面测试回归——`frontend/src/app/(agent)/agent/sessions/agent-page.test.tsx` 若存在则跑它）

**Interfaces:**
- Consumes: Task 1 `useSmartAutoScroll`
- Produces: 会话页滚动容器挂 hook；`handleContinue` 调 `resetScroll()`

- [ ] **Step 1: Modify page.tsx**

**1a.** import（page.tsx:3 附近）：

```tsx
import { useSmartAutoScroll } from "@/hooks/use-smart-auto-scroll";
```

**1b.** 组件内（`abortRef` 声明后）：

```tsx
  const scrollRef = useRef<HTMLDivElement>(null);
  const { reset: resetScroll } = useSmartAutoScroll(scrollRef, [turns]);
```

**1c.** `handleContinue`（page.tsx:85-99）开头加 `resetScroll();`：

```tsx
  async function handleContinue(input: { goal: string; attachmentIds: string[] }) {
    if (!sessionId) return;
    try {
      resetScroll();
      invalidateSessionView(sessionId);
      await agentApi.createRun(sessionId, {
        goal: input.goal,
        network_enabled: true,
        attachment_ids: input.attachmentIds,
      });
      invalidateAgentSessions();
      await loadSession();
    } catch {
      setError("发送消息失败");
    }
  }
```

**1d.** 滚动容器加 ref（page.tsx:139）：

```tsx
      <div className="detail-single-column-scroll" ref={scrollRef}>
```

- [ ] **Step 2: 页面回归**（先确认该测试文件存在；不存在则跳过）

```
cd C:\01_agent_loop_pro\frontend
npx vitest run "src/app/(agent)/agent/sessions"
```
Expected: PASS（或该目录无测试则报 no test found——跳过）

- [ ] **Step 3: 全量前端回归**

```
cd C:\01_agent_loop_pro\frontend
npx vitest run
```
Expected: 既有结果（509+ passed；11 个既有失败与本任务无关——若失败数增加则调查）

- [ ] **Step 4: Commit**（从仓库根）

```bash
git add "frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx"
git commit -m "feat: smart auto-scroll on session page — follow latest, stop on user browsing"
```

---

### Task 3: 集成验证

**Files:**
- Verify only（不改代码）

- [ ] **Step 1: 构建验证**

```
cd C:\01_agent_loop_pro\frontend
npx tsc --noEmit
```
Expected: 无类型错误

- [ ] **Step 2: ESLint**（若项目配置了 lint 脚本；`package.json` scripts 里找）

```
cd C:\01_agent_loop_pro\frontend
npm run lint
```
Expected: 通过（既有 warning 除外）

- [ ] **Step 3: 手动验证要点**（报告给用户）

- 打开会话页（历史会话）→ 不强制滚动
- 发送新消息 → 立即滚到底部 + 生成中跟随最新
- 生成中上滑 → 停止跟随，新内容不打断
- 生成中点击页面 → 停止跟随
- 滚回底部 → 恢复跟随
