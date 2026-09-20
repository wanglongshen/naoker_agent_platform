# 打字机动画恢复与增强方案

> 目标：恢复逐字流式效果（非一次性吐出），长文本自动加速  
> 根因：100ms 稳定计时器阻止了流式阶段的动画启动

---

## 一、问题诊断

### 当前行为（改坏了的）

```
SSE delta 到达
  → targetText 增长
  → 稳定计时器重启（100ms）
  → isAnimating = false
  → 返回 displayedText = targetText  ← 全文即刻显示，无动画
  → 100ms 后无新 delta
  → isAnimating = true
  → 动画启动但 displayedText 已 = targetText → 无内容可播
```

**效果：** 流式阶段文字一次性蹦出，没有打字机逐字效果。

### 目标行为

```
SSE delta 到达
  → targetText 增长
  → 动画持续运行
  → displayedText 逐字追赶 targetText
  → 每 20ms 推 1 字（短文本）/ 更快（长文本）
  → 像打字机一样平滑出现
```

---

## 二、方案

### 2.1 回退稳定计时器

`useTypingText` 恢复为参考系统原始逻辑：
- 删除 `STABILITY_DELAY_MS`、`isAnimating`、`stableTimerRef`
- 恢复原有 return 值 `return displayedText`
- 动画始终在 `displayedText < targetText` 时运行

### 2.2 增强加速算法（长文本自动加速）

当前参考系统：积压 ≥ 7 → 2x 加速（10ms/字）。长答案仍慢。

改为三级加速：

```
积压 0-15:   20ms/字  (50 字/s)   ← 短答案，自然速度
积压 15-80:  10ms/字  (100 字/s)  ← 中答案，适度加速
积压 > 80:   5ms/字   (200 字/s)  ← 长答案，快速追赶上屏
```

与之前失败的三级方案的区别：**阈值更高、速度更保守**，逐字流畅感不丢。

```
2000 字答案效果：
  0-15 字:   0.3s（自然速度）← 前 15 字逐字出现，有打字机感
  15-80 字:  0.65s（加速 1x） ← 中间段加速但不跳
  80-2000 字: 9.6s（加速 2x）  ← 长尾快速填完
  总计: ~10.5s（比当前 20s 快 2x，比之前三级方案更平滑）
```

**关键：** 前 15 个字始终保持 20ms/字，用户看到打字机效果。长尾加速在视觉上不突兀。

---

## 三、文件变更

| 文件 | 改动 | 行数 |
|------|------|------|
| `use-typing-text.ts` | 删除稳定计时器相关代码 | -15/+0 |
| `typing-animation.ts` | 三级加速替代原 2x 加速 | ~10 |

---

## 四、验证

```bash
cd frontend && npx vitest run src/hooks/use-typing-text.test.ts src/lib/typing-animation.test.ts
```
