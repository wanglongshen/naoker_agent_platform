import { describe, expect, it } from "vitest";

import type { AgentRunEvent } from "@/types/agent";
import { buildThoughtNarrativeBlocks, getThoughtDurationSeconds, getToolStatusCopy } from "@/lib/thought-narrative";

function event(seq: number, eventType: string, payload: Record<string, unknown>): AgentRunEvent {
  return {
    id: `event-${seq}`,
    run_id: "run-1",
    attempt_id: null,
    seq,
    event_type: eventType,
    payload,
    created_at: `2026-07-20T00:00:0${seq}Z`,
  };
}

describe("buildThoughtNarrativeBlocks", () => {
  it("keeps provider chunks in one reasoning segment when no tool is invoked", () => {
    const events = [
      event(1, "visible_thought_started", { step_index: 0, stream_id: "thought-1" }),
      event(2, "visible_thought_delta", { step_index: 0, stream_id: "thought-1", offset: 0, delta: "先分析需求，" }),
      event(3, "visible_thought_delta", { step_index: 0, stream_id: "thought-1", offset: 6, delta: "再整理现有信息。" }),
      event(4, "visible_thought_completed", { step_index: 0, stream_id: "thought-1", text: "先分析需求，再整理现有信息。" }),
    ];

    const blocks = buildThoughtNarrativeBlocks(events);

    expect(blocks.length).toBe(1);
    expect(blocks[0].kind).toBe("reasoning");
    if (blocks[0].kind === "reasoning") {
      expect(blocks[0].text).toBe("先分析需求，再整理现有信息。");
    }
  });

  it("alternates reasoning tool and resumed reasoning in event order", () => {
    const events = [
      event(1, "plan_created", { step_index: 0, thought_summary: "lifecycle copy must stay hidden" }),
      event(2, "visible_thought_started", { step_index: 0, stream_id: "thought-1" }),
      event(3, "visible_thought_delta", { step_index: 0, stream_id: "thought-1", offset: 0, delta: "先查看官方文档。" }),
      event(4, "tool_started", {
        step_index: 0,
        action_type: "http_request",
        tool_call: { method: "GET", url: "https://nextjs.org/learn?token=secret" },
      }),
      event(5, "tool_completed", {
        step_index: 0,
        action_type: "http_request",
        tool_call: { method: "GET", url: "https://nextjs.org/learn?token=secret" },
        observation: {
          status_code: 200,
          url: "https://nextjs.org/learn?token=secret",
          headers: { authorization: "Bearer secret", "set-cookie": "session=secret" },
          text: "response body must never be rendered",
        },
      }),
      event(6, "visible_thought_started", { step_index: 0, stream_id: "thought-1-resume" }),
      event(7, "visible_thought_delta", { step_index: 0, stream_id: "thought-1-resume", offset: 0, delta: "资料足够，继续整理。" }),
      event(8, "step_completed", { step_index: 0, action_type: "http_request" }),
    ];

    const blocks = buildThoughtNarrativeBlocks(events);

    expect(blocks.map((block) => block.kind)).toEqual(["reasoning", "tool", "reasoning"]);
    if (blocks[0].kind === "reasoning") {
      expect(blocks[0].text).toBe("先查看官方文档。");
    }
    if (blocks[1].kind === "tool") {
      expect(blocks[1].status).toBe("completed");
      expect(blocks[1].label).toBe("网页访问");
      expect(blocks[1].url).toBe("https://nextjs.org/learn");
    }
    if (blocks[2].kind === "reasoning") {
      expect(blocks[2].text).toBe("资料足够，继续整理。");
    }
    expect(JSON.stringify(blocks)).not.toMatch(/搜索完成|authorization|set-cookie|response body|secret/i);
  });

  it("projects search and calculator tools with distinct safe summaries", () => {
    const events = [
      event(1, "tool_started", {
        step_index: 0,
        action_type: "web_search",
        tool_call: { query: "Next.js 教程", max_results: 5 },
      }),
      event(2, "tool_completed", {
        step_index: 0,
        action_type: "web_search",
        observation: {
          results: [
            { title: "Next.js Learn", url: "https://nextjs.org/learn", content: "private summary" },
            { title: "Next.js Docs", url: "https://nextjs.org/docs", content: "private summary" },
          ],
        },
      }),
      event(3, "tool_started", {
        step_index: 1,
        action_type: "calculator",
        tool_call: { expression: "2 + 2" },
      }),
      event(4, "tool_completed", {
        step_index: 1,
        action_type: "calculator",
        observation: { result: 4 },
      }),
    ];

    const blocks = buildThoughtNarrativeBlocks(events);

    if (blocks[0].kind === "tool") {
      expect(blocks[0].label).toBe("联网搜索");
      expect(blocks[0].resultSummary).toBe("找到 2 个结果");
    }
    if (blocks[1].kind === "tool") {
      expect(blocks[1].label).toBe("计算器");
      expect(blocks[1].resultSummary).toBe("结果 4");
    }
    expect(JSON.stringify(blocks)).not.toMatch(/private summary/);
  });

  it("uses the specified page label and tool-specific status copy", () => {
    const blocks = buildThoughtNarrativeBlocks([
      event(1, "tool_started", {
        step_index: 0,
        action_type: "extract_web_content",
        tool_call: { url: "https://example.com" },
      }),
    ]);

    if (blocks[0].kind === "tool") {
      expect(blocks[0].label).toBe("网页访问");
    }
    expect(getToolStatusCopy("web_search", "running", null)).toBe("正在搜索");
    expect(getToolStatusCopy("web_search", "completed", "找到 2 个结果")).toBe("找到 2 个结果");
    expect(getToolStatusCopy("calculator", "running", null)).toBe("正在计算");
    expect(getToolStatusCopy("extract_web_content", "completed", null)).toBe("访问完成");
  });
});

describe("getThoughtDurationSeconds", () => {
  it("calculates thought duration from first thought event to answer start", () => {
    const events: AgentRunEvent[] = [
      event(1, "visible_thought_started", { step_index: 0, stream_id: "thought-1" }),
      {
        ...event(2, "answer_started", { stream_id: "answer-1" }),
        created_at: "2026-07-20T00:00:07Z",
      },
    ];
    events[0] = { ...events[0], created_at: "2026-07-20T00:00:01Z" };

    expect(getThoughtDurationSeconds(events, null, null, Date.parse("2026-07-20T00:00:20Z"))).toBe(6);
  });

  it("uses current time while thought is still running", () => {
    const events: AgentRunEvent[] = [{
      ...event(1, "visible_thought_started", { step_index: 0, stream_id: "thought-1" }),
      created_at: "2026-07-20T00:00:01Z",
    }];

    expect(
      getThoughtDurationSeconds(events, "2026-07-20T00:00:00Z", null, Date.parse("2026-07-20T00:00:05Z")),
    ).toBe(4);
  });

  it("keeps growing while the thought is still running as nowMs advances", () => {
    const events: AgentRunEvent[] = [{
      ...event(1, "visible_thought_started", { step_index: 0, stream_id: "thought-1" }),
      created_at: "2026-07-20T00:00:01Z",
    }];

    const atFiveSeconds = getThoughtDurationSeconds(events, null, null, Date.parse("2026-07-20T00:00:05Z"));
    const atNineSeconds = getThoughtDurationSeconds(events, null, null, Date.parse("2026-07-20T00:00:09Z"));

    expect(atFiveSeconds).toBe(4);
    expect(atNineSeconds).toBe(8);
    expect(atNineSeconds!).toBeGreaterThan(atFiveSeconds!);
  });
});
