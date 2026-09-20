# Plan Event Rendering in Thought Narrative

**Date:** 2026-07-30

## Problem

The planning phase (Planner LLM call) emits `plan_started` / `plan_delta` / `plan_completed` events to the frontend. The `runStreamReducer` handles them correctly (stores in `visibleThoughtByStep[0]`), but `buildThoughtNarrativeBlocks` in `thought-narrative.ts` does NOT recognize them. Result: the planner runs silently — UI shows static "正在分析你的需求..." with zero progress for 5-10 seconds, then everything appears at once.

## Solution

Add `plan_*` event handling to `buildThoughtNarrativeBlocks`. The logic is identical to `visible_thought_*` — create/update "reasoning" blocks identified by `streamId`.

### Files

- Modify: `frontend/src/lib/thought-narrative.ts:158-230`

### Change

Add three new `if` blocks after the `visible_thought_completed` handler (before the `tool_started` handler at line 232):

1. `plan_started` → push a new reasoning block if streamId not already tracked
2. `plan_delta` → append delta text to the matching block
3. `plan_completed` → set block text to final value, mark complete

### Verification

Existing `thought-narrative.test.ts` tests must pass. The test at line 38 already creates a `plan_created` event — an additional test should verify `plan_delta` creates a reasoning block.

### Effect

Before: "正在分析你的需求..." (static, 5-10s)
After: "正在分析你的需求..." → live streaming planner text with typing animation
