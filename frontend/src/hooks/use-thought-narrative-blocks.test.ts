import { describe, it, expect, beforeEach } from "vitest";
import { buildThoughtNarrativeBlocks } from "@/lib/thought-narrative";
import type { AgentRunEvent } from "@/types/agent";

let seqCounter = 0;
function makeEvent(event_type: string, payload: Record<string, unknown>, run_id = "r1"): AgentRunEvent {
  seqCounter++;
  return {
    id: `evt-${seqCounter}`,
    run_id,
    attempt_id: null,
    seq: seqCounter,
    event_type,
    type: event_type,
    payload,
    created_at: new Date().toISOString(),
    timestamp: new Date().toISOString(),
  } as AgentRunEvent;
}

describe("buildThoughtNarrativeBlocks", () => {
  beforeEach(() => { seqCounter = 0; });

  it("creates one reasoning block from started + delta + completed", () => {
    const events = [
      makeEvent("visible_thought_started", { step_index: 0, stream_id: "s1" }),
      makeEvent("visible_thought_delta", { step_index: 0, stream_id: "s1", offset: 0, delta: "Hello" }),
      makeEvent("visible_thought_delta", { step_index: 0, stream_id: "s1", offset: 5, delta: " world" }),
      makeEvent("visible_thought_completed", { step_index: 0, stream_id: "s1", text: "Hello world" }),
    ];
    const blocks = buildThoughtNarrativeBlocks(events);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ kind: "reasoning", text: "Hello world", isComplete: true });
  });

  it("does not duplicate when delta events accumulate", () => {
    seqCounter = 0;
    const events = [
      makeEvent("visible_thought_started", { step_index: 0, stream_id: "s1" }),
      makeEvent("visible_thought_delta", { step_index: 0, stream_id: "s1", offset: 0, delta: "Hello" }),
      makeEvent("visible_thought_delta", { step_index: 0, stream_id: "s1", offset: 5, delta: " world" }),
    ];
    const blocks = buildThoughtNarrativeBlocks(events);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ kind: "reasoning", text: "Hello world", isComplete: false });
  });

  it("handles pause-tool-resume flow without duplicates", () => {
    const events = [
      makeEvent("visible_thought_started", { step_index: 0, stream_id: "s1" }),
      makeEvent("visible_thought_delta", { step_index: 0, stream_id: "s1", offset: 0, delta: "Searching..." }),
      makeEvent("visible_thought_paused", { step_index: 0, stream_id: "s1", text: "Searching..." }),
      makeEvent("tool_started", { step_index: 0, action_type: "web_search" }),
      makeEvent("tool_completed", { step_index: 0, action_type: "web_search" }),
      makeEvent("visible_thought_started", { step_index: 0, stream_id: "s1-resume" }),
      makeEvent("visible_thought_delta", { step_index: 0, stream_id: "s1-resume", offset: 0, delta: "Found results" }),
      makeEvent("visible_thought_completed", { step_index: 0, stream_id: "s1-resume", text: "Found results" }),
    ];
    const blocks = buildThoughtNarrativeBlocks(events);
    const reasoningBlocks = blocks.filter(b => b.kind === "reasoning");
    expect(reasoningBlocks).toHaveLength(2);
    expect(reasoningBlocks[0]).toMatchObject({ text: "Searching...", isComplete: true });
    expect(reasoningBlocks[1]).toMatchObject({ text: "Found results", isComplete: true });
    expect(blocks.filter(b => b.kind === "tool")).toHaveLength(1);
  });

  it("paused event carries full text even when deltas were partial", () => {
    const events = [
      makeEvent("visible_thought_started", { step_index: 0, stream_id: "s1" }),
      makeEvent("visible_thought_delta", { step_index: 0, stream_id: "s1", offset: 0, delta: "接下" }),
      makeEvent("visible_thought_paused", { step_index: 0, stream_id: "s1", text: "接下来我将继续检索相关信息" }),
      makeEvent("tool_started", { step_index: 0, action_type: "web_search" }),
    ];
    const blocks = buildThoughtNarrativeBlocks(events);
    const reasoningBlocks = blocks.filter(b => b.kind === "reasoning");
    expect(reasoningBlocks).toHaveLength(1);
    // 实时流式中 pause 打断时 deltas 可能不完整，必须用 paused 携带的完整 text
    expect(reasoningBlocks[0]).toMatchObject({
      text: "接下来我将继续检索相关信息",
      isComplete: true,
    });
  });

  it("handles completed event with full text overwrite", () => {
    const events = [
      makeEvent("visible_thought_started", { step_index: 0, stream_id: "s1" }),
      makeEvent("visible_thought_delta", { step_index: 0, stream_id: "s1", offset: 0, delta: "abc" }),
      makeEvent("visible_thought_completed", { step_index: 0, stream_id: "s1", text: "Finalized text" }),
    ];
    const blocks = buildThoughtNarrativeBlocks(events);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ kind: "reasoning", text: "Finalized text", isComplete: true });
  });

  it("returns empty for no events", () => {
    expect(buildThoughtNarrativeBlocks([])).toEqual([]);
  });

  it("filters out empty-text reasoning blocks", () => {
    const events = [
      makeEvent("visible_thought_started", { step_index: 0, stream_id: "s1" }),
    ];
    const blocks = buildThoughtNarrativeBlocks(events);
    expect(blocks).toHaveLength(0);
  });
});
