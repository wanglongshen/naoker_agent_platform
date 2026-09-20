# 答案显示：即时段落 + 打字机尾部（方案 C）

**Date:** 2026-08-01
**Status:** approved

## 1. 背景

当前答案显示为纯 SSE 驱动（无打字机），用户反馈"先出一大段文字，之后才流式"，体验不佳。用户确认期望效果为"两遍"组合：

- **一遍（即时段落）**：`\n\n` 完成的段落 → 即时 ReactMarkdown 渲染
- **二遍（打字机尾部）**：正在写的段落 → 打字机逐字 + 渐进 Markdown + 光标

**不做：** run 完成后的全文重打（`animateTerminal` 机制）——那才是被投诉的"两遍 bug"。

## 2. 架构

`ProgressiveMarkdown` 流式分支（`terminal=false`）恢复 `splitBlocks(text)`：

```
completed（完成段落）→ CompletedBlock（即时 ReactMarkdown）
active（未完成尾部） → StreamingTail（打字机：rAF + advanceTypingAnimation + 渐进 Markdown + 光标）
```

`terminal=true` → `CompletedBlock` 全文（无打字）。

## 3. 组件

| 组件 | 状态 | 职责 |
|------|------|------|
| `CompletedBlock` | 保留（现状已有） | 已完成段落即时渲染 |
| `StreamingTail` | **恢复**（上个重构删除，commit 1a7b3f1） | 活动尾部打字机：rAF 驱动 + `advanceTypingAnimation` + `lastTimeRef` 修复（null 语义）+ 每 2 帧渲染渐进 Markdown（30fps 节流）+ 光标 `|` |

`StreamingTail` 从 commit `1a7b3f1` 之前的版本恢复（即 `832cd53` 时代含渐进 Markdown 渲染的版本），props：`{ targetText: string; onComplete?: () => void }`。

## 4. 数据流

```
SSE answer_delta → answerText 累积（reducer）
  → ProgressiveMarkdown(text=answerText, terminal=false)
    → splitBlocks(text) → { completed: [...], active: "..." }
      → completed.map → CompletedBlock（即时）
      → active → StreamingTail（打字机）
```

## 5. 不做清单（YAGNI）

- 无 `animateTerminal` / `terminalTyped` / 全文重打
- 无 `wasLiveStreamed` 相关逻辑（FinalAnswerPanel 不再传 animateTerminal）
- 思考区（ThoughtNarrative / useTypingText）不变

## 6. 影响文件

| 文件 | 改动 |
|------|------|
| `frontend/src/components/agent/progressive-markdown.tsx` | 恢复 `StreamingTail` 组件 + 流式分支 `splitBlocks` |
| `frontend/src/components/agent/agent-streaming.test.tsx` | 恢复打字机相关测试断言 |
