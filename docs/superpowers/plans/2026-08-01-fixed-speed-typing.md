# Fixed-Speed Typing Animation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace multi-tier acceleration with a single fixed speed of 20ms per character, producing visible character-by-character streaming at 50 chars/sec that stays in sync with DeepSeek's output rate.

**Architecture:** Remove `getEffectiveMsPerCharacter` function and `ACCELERATION_TRIGGER_BACKLOG` constant from `typing-animation.ts`. `advanceTypingAnimation` always uses the caller-provided `msPerCharacter` (20ms). Speed constants in `progressive-markdown.tsx` and `use-typing-text.ts` changed from 12 to 20.

**Tech Stack:** TypeScript

## Global Constraints

- `advanceTypingAnimation` signature must not change
- `TypingAnimationState` type must not change
- `PUNCTUATION_PAUSE_MS` (60ms) retained for punctuation
- Existing tests must pass after updates
- `StreamingTail` rAF drive and `lastTimeRef` fix retained

---

### Task 1: Flatten typing speed — remove acceleration, set 20ms uniform speed

**Files:**
- Modify: `frontend/src/lib/typing-animation.ts:8, 18-33, 53-62`
- Modify: `frontend/src/components/agent/progressive-markdown.tsx:13`
- Modify: `frontend/src/hooks/use-typing-text.ts:7`
- Modify: `frontend/src/lib/typing-animation.test.ts` (test expectations)
- Modify: `frontend/src/hooks/use-typing-text.test.ts` (test expectations)

**Interfaces:**
- Consumes: `advanceTypingAnimation(state, targetText, elapsedMs, msPerCharacter)` — unchanged
- Produces: Same return type, always advances at `msPerCharacter` pace (no acceleration)

- [ ] **Step 1: Remove acceleration from `typing-animation.ts`**

Delete the `ACCELERATION_TRIGGER_BACKLOG` constant (line 8) and the entire `getEffectiveMsPerCharacter` function (lines 18-33).

Replace the acceleration logic in `advanceTypingAnimation` (lines 53-62):

```typescript
export function advanceTypingAnimation(
  state: TypingAnimationState,
  targetText: string,
  elapsedMs: number,
  msPerCharacter: number,
): TypingAnimationState {
  if (!targetText) {
    return createTypingAnimationState();
  }

  const previousText = state.displayedText;
  const targetShrank = !targetText.startsWith(previousText);
  const startingText = targetShrank ? "" : previousText;
  let remainingMs = targetShrank
    ? msPerCharacter
    : state.remainingMs === null ? msPerCharacter : state.remainingMs;
  let displayedCount = startingText.length;
  let budgetMs = Math.max(elapsedMs, 0);

  while (budgetMs >= remainingMs && displayedCount < targetText.length) {
    budgetMs -= remainingMs;
    displayedCount += 1;
    const lastCharacter = targetText.charAt(displayedCount - 1);
    remainingMs = getTypingAnimationDelayMs(lastCharacter, msPerCharacter);
  }

  const displayedText = targetText.slice(0, displayedCount);

  if (displayedText === targetText) {
    return { displayedText, remainingMs: null };
  }

  return { displayedText, remainingMs: remainingMs - budgetMs };
}
```

Also delete `ACCELERATED_CATCH_UP_DIVISOR` (line 7) and `ACCELERATION_TAPER_BACKLOG` (line 9) since they're unused now.

- [ ] **Step 2: Set TYPING_SPEED_MS to 20 in `progressive-markdown.tsx`**

```typescript
const TYPING_SPEED_MS = 20;
```

- [ ] **Step 3: Set DEFAULT_TYPING_SPEED_MS to 20 in `use-typing-text.ts`**

```typescript
export const DEFAULT_TYPING_SPEED_MS = 20;
```

- [ ] **Step 4: Update `typing-animation.test.ts`**

The existing tests use `msPerCharacter=16` and check specific acceleration behavior. Update to reflect fixed-speed behavior:

```typescript
import { describe, expect, test } from "vitest";
import { advanceTypingAnimation } from "@/lib/typing-animation";

describe("advanceTypingAnimation", () => {
  test("advances one character per tick at fixed speed", () => {
    expect(advanceTypingAnimation({ displayedText: "你", remainingMs: 16 }, "你好", 16, 20).displayedText)
      .toBe("你好"); // 16ms >= 20ms? Wait, 16 < 20, so no advance...
  });
```

The tests need careful adjustment because with fixed 20ms speed and 16ms elapsed budget, fewer characters advance. Rewrite the test suite:

```typescript
import { describe, expect, test } from "vitest";
import { advanceTypingAnimation } from "@/lib/typing-animation";

describe("advanceTypingAnimation", () => {
  test("advances one character from empty with enough budget", () => {
    const result = advanceTypingAnimation({ displayedText: "", remainingMs: 20 }, "你好", 20, 20);
    expect(result.displayedText).toBe("你");
  });

  test("advances nothing with insufficient budget", () => {
    const result = advanceTypingAnimation({ displayedText: "", remainingMs: 20 }, "你好", 10, 20);
    expect(result.displayedText).toBe("");
  });

  test("advances multiple characters with large budget", () => {
    const result = advanceTypingAnimation({ displayedText: "", remainingMs: 20 }, "abcdef", 80, 20);
    expect(result.displayedText.length).toBe(4); // 80 / 20 = 4 chars
  });

  test("continues from partial text", () => {
    const result = advanceTypingAnimation({ displayedText: "ab", remainingMs: 10 }, "abcdef", 20, 20);
    expect(result.displayedText).toBe("abc"); // 20 >= 10 → advance 1 char
  });

  test("starts fresh when target prefix mismatches", () => {
    const state = advanceTypingAnimation({ displayedText: "abc", remainingMs: 20 }, "xy", 20, 20);
    expect(state.displayedText).toBe("x");
  });

  test("reaches target within accumulated ticks", () => {
    const target = "a".repeat(100);
    let state = { displayedText: "", remainingMs: 20 };
    let totalMs = 0;
    while (state.displayedText !== target && totalMs < 3000) {
      state = advanceTypingAnimation(state, target, 20, 20);
      totalMs += 20;
    }
    expect(state.displayedText).toBe(target);
  });

  test("does not move backward when target grows", () => {
    const result = advanceTypingAnimation({ displayedText: "ab", remainingMs: 20 }, "abcde", 20, 20);
    expect(result.displayedText.startsWith("ab")).toBe(true);
  });
});
```

- [ ] **Step 5: Update `use-typing-text.test.ts`**

Check if the test references `DEFAULT_TYPING_SPEED_MS`. If it uses hardcoded values, update to match 20.

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/hooks/use-typing-text.test.ts -v
```

- [ ] **Step 6: Run full test suite**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run -v
```

Expected: No new failures (typing-animation tests rewritten, others unchanged).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/typing-animation.ts frontend/src/lib/typing-animation.test.ts frontend/src/components/agent/progressive-markdown.tsx frontend/src/hooks/use-typing-text.ts
git commit -m "perf: replace acceleration tiers with fixed 20ms/char typing speed"
```
