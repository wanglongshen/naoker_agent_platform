# 流式渲染终极方案

> 两题同解：分段渲染消除卡顿 + 自适应速度恢复打字机效果

---

## 一、分段渲染（解决卡死）

### 问题
ReactMarkdown 每帧全量重解析 → 表格 O(n²) → 卡死

### 方案
流式阶段按空行切段落，已完成段落 ReactMarkdown 渲染一次后 memo，正在写的尾部纯文本。

### 文件
- 新增 `progressive-markdown.tsx`（~40 行）
- 改 `final-answer-panel.tsx`（替换内联 ReactMarkdown）
- 加 CSS（`streaming-tail` 类）

---

## 二、七级平滑加速（恢复打字机效果 + 长文本不慢）

### 问题
参考系统 2x 加速（20→10ms）太保守，2000 字要 20s。三级加速太跳跃（4ms 导致屏幕闪烁）。

### 方案：七级渐进加速

| 剩余字数 | 速度 | 字/s | 感受 |
|---------|------|------|------|
| ≤ 20 | 30ms | 33 | 尾声打字机 |
| 21-50 | 22ms | 45 | 轻微加速 |
| 51-80 | 17ms | 59 | 自然流畅 |
| 81-120 | 13ms | 77 | 略快 |
| 121-200 | 10ms | 100 | 快速追赶 |
| 201-400 | 7ms | 143 | 高速 |
| > 400 | 5ms | 200 | 极速 |

**2000 字效果：**
```
20×30 + 30×22 + 30×17 + 40×13 + 80×10 + 200×7 + 1600×5
= 0.6 + 0.66 + 0.51 + 0.52 + 0.8 + 1.4 + 8.0
= 12.5 秒
```
比参考系统 20s 快 38%，比三级方案 8s 更平滑（无跳跃感）。

**前 20 个字始终 30ms/字 → 打字机感完整。** 后续渐进加速，无突兀切换。

### 文件
- 改 `typing-animation.ts`（`getEffectiveMsPerCharacter`）
- `use-typing-text.ts` 恢复原版（删稳定计时器）

---

## 三、文件变更总览

| 文件 | 操作 |
|------|------|
| `progressive-markdown.tsx` | **新增** |
| `final-answer-panel.tsx` | 改用 ProgressiveMarkdown |
| `agent-globals.css` | 加 `.streaming-tail` |
| `typing-animation.ts` | 七级加速 |
| `use-typing-text.ts` | 恢复原版（删稳定计时器） |

---

## 四、验证

```bash
cd frontend && npx next build
```
