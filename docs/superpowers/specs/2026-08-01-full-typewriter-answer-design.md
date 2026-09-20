# 答案显示：全文打字机（方案 B）

**Date:** 2026-08-01
**Status:** approved

## 1. 背景

当前答案显示为纯 SSE 驱动（splitBlocks 即时段落），用户反馈"开头膨一下出一堆，之后才流式"。根因：SSE 开头突发到达 → 完成的段落立即整体渲染。

**目标：** 消除开头爆发，全文从第一个字符起平滑逐字显示。

## 2. 方案

流式阶段（`terminal=false`）**全文**走打字机组件 `StreamingTail`（不 splitBlocks）：

```
SSE answer_delta → answerText 累积
  → ProgressiveMarkdown(text, terminal=false)
    → { completed: [], active: text }          ← 全文进打字机
      → StreamingTail：rAF 驱动 + advanceTypingAnimation
        → 渐进 Markdown 渲染（每 2 帧，30fps 节流）
        → 光标 `|` 闪烁
```

`terminal=true` → `CompletedBlock` 全文（无打字、无重打）。

## 3. 组件

| 组件 | 状态 | 职责 |
|------|------|------|
| `StreamingTail` | **恢复**（commit `1a7b3f1` 删除，现恢复） | 打字机：rAF + `advanceTypingAnimation` + `lastTimeRef` null 语义 + 30fps 渐进 Markdown + 光标 |
| `CompletedBlock` | 保留 | terminal 态全文渲染 |
| `splitBlocks` | 不再使用 | 从 progressive-markdown 移除 import |

`StreamingTail` props：`{ targetText: string; onComplete?: () => void }`（onComplete 当前调用方可传可不传）。

## 4. 不做清单（YAGNI）

- 无 `animateTerminal` / `terminalTyped` / run 完成全文重打
- 无 `wasLiveStreamed` 相关逻辑（FinalAnswerPanel 已不传 animateTerminal）
- 思考区（ThoughtNarrative / useTypingText）不变

## 5. 影响文件

| 文件 | 改动 |
|------|------|
| `frontend/src/components/agent/progressive-markdown.tsx` | 恢复 `StreamingTail` 组件；流式分支 `{completed:[], active:text}`；移除 `splitBlocks` import |
| `frontend/src/components/agent/agent-streaming.test.tsx` | 打字机相关断言恢复/调整 |
