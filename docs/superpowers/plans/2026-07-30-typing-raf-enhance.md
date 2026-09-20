# 打字机动画帧率对齐方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 流式答案打字机动画始终保持追赶 SSE 到达速度，消除周期性"大块文字弹出"现象。

**Architecture:** `StreamingTail` 已使用 rAF（~16.7ms/帧），但 `advanceTypingAnimation` 的 `TYPING_SPEED_MS=20` > 帧间隔 16.7ms，导致每帧预算不够推进 1 个字符，实际速度仅 ~30 字/秒，被 DeepSeek ~50 字/秒甩开。积压超过 7 字时加速器突然爆发 → 用户看到"大块弹出"。将 `TYPING_SPEED_MS` 从 20 降到 12，使每帧至少推进 1 字（~90 字/秒，远超 50 字/秒），无积压、无爆发。同时降低加速器触发阈值 7→2，更早干预。

**Tech Stack:** React 19 + TypeScript + requestAnimationFrame

## Global Constraints

- 打字机动画永久保留（前段逐字效果不受影响，只是时速加快）
- 七级加速表保留不动（仅改触发阈值）
- `useTypingText` (ThoughtNarrative 用 setTimeout) 不受影响
- 仅改 `ProgressiveMarkdown` 的 `StreamingTail` 速度参数

---

### Task 1: 降低打字速度 + 加速阈值

**Files:**
- Modify: `frontend/src/components/agent/progressive-markdown.tsx:13`（`TYPING_SPEED_MS`）
- Modify: `frontend/src/lib/typing-animation.ts:8`（`ACCELERATION_TRIGGER_BACKLOG`）

**Interfaces:**
- Consumes: 无新接口（仅修改常量）
- Produces: `TYPING_SPEED_MS = 12`, `ACCELERATION_TRIGGER_BACKLOG = 2`

- [ ] **Step 1: 修改 `ProgressiveMarkdown` 的 `TYPING_SPEED_MS`**

```typescript
const TYPING_SPEED_MS = 12;
```

- [ ] **Step 2: 修改 `typing-animation.ts` 的 `ACCELERATION_TRIGGER_BACKLOG`**

```typescript
const ACCELERATION_TRIGGER_BACKLOG = 2;
```

- [ ] **Step 3: 验证构建**

```bash
cd C:\01_agent_loop_pro\frontend && npx next build
```

Expected: 构建成功

- [ ] **Step 4: 运行测试**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run -v
```

Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/agent/progressive-markdown.tsx frontend/src/lib/typing-animation.ts
git commit -m "perf: align typing speed with rAF 16ms frame — 20→12ms, acceleration threshold 7→2"
```

---

## 原理

**快速算式：**
- rAF 帧间隔 ≈ 16.7ms → 每帧预算 16.7ms
- 原 `TYPING_SPEED_MS=20` → 每帧 16.7 < 20 → 不够推进 1 字 → 需约 2 帧才推 1 字 → 实际 ~30 字/秒
- DeepSeek SSE 到达 ~50 字/秒 → 每秒积压 20 字 → 积压到 7 时加速器爆发 → 用户看到大块弹出
- 改 `TYPING_SPEED_MS=12` → 每帧 16.7 > 12 → 每帧至少推 1 字 → 实际 ~90 字/秒 >> 50 字/秒 → 无积压，无爆发
- 加速阈值 7→2 做双保险：即使罕见积压也立即加速，不会积累成大块

**不变项：**
- `StreamingTail` 的 rAF 驱动保留
- `useTypingText`（思考过程用 setTimeout）不碰
- 七级加速系数 (5/7/10/13/17/22/...) 不碰
