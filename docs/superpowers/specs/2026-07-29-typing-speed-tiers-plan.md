# 打字动画三级速度自适应方案

> 目标：短答案保持逐字自然感，长答案快速追平不卡顿  
> 范围：`typing-animation.ts`，单文件 ~10 行

---

## 一、问题诊断

### 当前算法（参考系统原版）

```
加速触发：积压 >= 7 字
加速倍率：2x (msPerCharacter / 2)
正常速度：20ms/字 → 50 字/s
加速速度：10ms/字 → 100 字/s
```

**瓶颈：** 2000 字的旅游攻略，即使全程加速也需要 2000 / 100 = **20 秒**逐字播放。用户看到表格一行一行"画"出来，体验极差。

### 用户感知曲线

```
字数      当前耗时        理想耗时
100        2s              2s
500       5+2s=7s          3s
1000      5+9s=14s         5s
2000      5+19s=24s        8s
```

短答案差异不大，长答案差距呈倍数扩大。

---

## 二、改进算法

### 三级速度分级

| 积压（剩余未显示字数） | 速度 | 字/s | 场景 |
|----------------------|------|------|------|
| < 10 | 20ms/字 | 50 | 短答案、自然阅读节奏 |
| 10 - 50 | 8ms/字 | 125 | 中等答案、适度加速 |
| > 50 | 4ms/字 | 250 | 长答案、快速追平 |

**效果预估：** 2000 字 → 前 10 字 0.2s + 中间 40 字 0.32s + 剩余 1950 字 7.8s = **~8.3 秒**。比现 20 秒快 2.4 倍。

### 保留特性

- ✅ 标点停顿 60ms（句号、逗号等）—— 句子结尾自然节奏
- ✅ 平滑过渡 —— 从 20ms → 8ms → 4ms 随积压自然降级
- ✅ 积压清空后恢复 20ms —— 追平后恢复自然速度

---

## 三、代码改动

### 文件：`frontend/src/lib/typing-animation.ts`

**删除常量：**
```typescript
const ACCELERATED_CATCH_UP_DIVISOR = 2;
const ACCELERATION_TRIGGER_BACKLOG = 7;
const ACCELERATION_TAPER_BACKLOG = 3;
```

**新增常量：**
```typescript
const TIER_FAST_THRESHOLD = 50;
const TIER_MEDIUM_THRESHOLD = 10;
const TIER_SLOW_MS = 20;
const TIER_MEDIUM_MS = 8;
const TIER_FAST_MS = 4;
```

**修改函数：** `getEffectiveMsPerCharacter`

```typescript
// 改前：
function getEffectiveMsPerCharacter(
  displayedCount: number, targetLength: number,
  msPerCharacter: number, accelerateForThisTick: boolean,
): number {
  const remainingCharacters = targetLength - displayedCount;
  if (accelerateForThisTick && remainingCharacters >= ACCELERATION_TAPER_BACKLOG) {
    return Math.max(1, Math.floor(msPerCharacter / ACCELERATED_CATCH_UP_DIVISOR));
  }
  return msPerCharacter;
}

// 改后：
function getEffectiveMsPerCharacter(
  displayedCount: number, targetLength: number,
  msPerCharacter: number, accelerateForThisTick: boolean,
): number {
  if (!accelerateForThisTick) return msPerCharacter;
  const remaining = targetLength - displayedCount;
  if (remaining > TIER_FAST_THRESHOLD) return TIER_FAST_MS;
  if (remaining > TIER_MEDIUM_THRESHOLD) return TIER_MEDIUM_MS;
  return msPerCharacter;
}
```

### 文件：`frontend/src/hooks/use-typing-text.ts`

`DEFAULT_TYPING_SPEED_MS` 保持不变（20ms）。三级速度在 `getEffectiveMsPerCharacter` 内自动切换。

---

## 四、常量定义速查

| 常量 | 值 | 作用 |
|------|-----|------|
| `DEFAULT_TYPING_SPEED_MS` | 20 | 基础速度（短答案） |
| `TIER_SLOW_MS` | 20 | 一级：积压 < 10 |
| `TIER_MEDIUM_MS` | 8 | 二级：积压 10-50 |
| `TIER_FAST_MS` | 4 | 三级：积压 > 50 |
| `TIER_MEDIUM_THRESHOLD` | 10 | 进入中速的积压阈值 |
| `TIER_FAST_THRESHOLD` | 50 | 进入高速的积压阈值 |
| `PUNCTUATION_PAUSE_MS` | 60 | 标点停顿（不变） |

---

## 五、验证

```bash
cd frontend && npx vitest run src/lib/typing-animation.test.ts src/hooks/use-typing-text.test.ts
```
