# StreamingTail LastTimeReset Bug Fix

**Author:** 2026-07-30
**Status:** approved

## Problem

Streaming answer text shows characters one-by-one briefly, then large chunks appear all at once. The typing animation cannot keep up with SSE arrival rate.

## Root Cause

In `frontend/src/components/agent/progressive-markdown.tsx`, the `StreamingTail` component resets `lastTimeRef` to `0` every time `targetText` changes (every SSE batch):

```typescript
// line 86
lastTimeRef.current = 0;  // BUG: resets every SSE event
```

Combined with line 70:
```typescript
const elapsed = lastTimeRef.current ? now - lastTimeRef.current : TYPING_SPEED_MS;
// 0 is falsy → always uses TYPING_SPEED_MS=12ms instead of real elapsed time
```

Each SSE event (every ~20ms) resets the timer, causing the animation to advance only 12ms of characters when real elapsed could be 20-50ms. Over 500 events, this accumulates 2+ seconds of lost time. The backlog triggers acceleration → large chunks burst out.

## Solution

Change `lastTimeRef` from `useRef<number>(0)` to `useRef<number | null>(null)`. Remove the reset on line 86. Change the null check on line 70.

```diff
- const lastTimeRef = useRef<number>(0);
+ const lastTimeRef = useRef<number | null>(null);

- const elapsed = lastTimeRef.current ? now - lastTimeRef.current : TYPING_SPEED_MS;
+ const elapsed = lastTimeRef.current !== null ? now - lastTimeRef.current : TYPING_SPEED_MS;

- lastTimeRef.current = 0;   // DELETE
```

**Effect:** `null` means "no previous tick" (first frame uses default speed). After that, all elapsed calculations use real `performance.now()` deltas, even across SSE restarts.

## Verification

Tracing the fixed timeline with 50ms SSE intervals:

```
Time   Event     lastTimeRef    elapsed calc        Result
0ms    mount     null           —                   —
16ms   rAF       null → 12ms    default budget       1 char
33ms   rAF       16 → 17ms     real frame            1 char  
50ms   SSE       33 (not reset) —                    pause
55ms   rAF       33 → 22ms     real + render time    2 chars
70ms   SSE       55 (not reset) —                    pause
80ms   rAF       55 → 25ms     real + render time    2 chars
```

No accumulated backlog. Animation stays in lockstep with real time.
