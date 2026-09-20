import type { AgentRunEvent } from "@/types/agent";

export type ThoughtReasoningBlock = {
  kind: "reasoning";
  id: string;
  streamId: string;
  stepIndex: number;
  text: string;
  isComplete: boolean;
};

export type ThoughtToolBlock = {
  kind: "tool";
  id: string;
  stepIndex: number;
  toolType: string;
  label: string;
  status: "running" | "completed";
  url: string | null;
  resultSummary: string | null;
};

export type ThoughtNarrativeBlock = ThoughtReasoningBlock | ThoughtToolBlock;

const THOUGHT_EVENT_TYPES = new Set<AgentRunEvent["event_type"]>([
  "visible_thought_started",
  "visible_thought_delta",
  "visible_thought_completed",
]);

export function getThoughtDurationSeconds(
  events: AgentRunEvent[],
  runStartedAt: string | null,
  runFinishedAt: string | null,
  nowMs: number = Date.now(),
  answerStartedAt: string | null = null,
): number | null {
  const orderedEvents = [...events].sort((a, b) => a.seq - b.seq);
  const firstThoughtEvent = orderedEvents.find((event) => THOUGHT_EVENT_TYPES.has(event.event_type));
  const startedAtMs = Date.parse(firstThoughtEvent?.created_at ?? runStartedAt ?? "");
  if (!Number.isFinite(startedAtMs)) {
    return null;
  }

  const answerStartedEvent = orderedEvents.find((event) => event.event_type === "answer_started");
  const finishedAt = answerStartedAt || answerStartedEvent?.created_at || runFinishedAt;
  const endedAtMs = finishedAt ? Date.parse(finishedAt) : nowMs;
  if (!Number.isFinite(endedAtMs)) {
    return null;
  }

  return Math.max(0, Math.round((endedAtMs - startedAtMs) / 1000));
}

export function readString(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export function readNumber(payload: Record<string, unknown>, key: string): number | null {
  const value = payload[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function readRecord(payload: Record<string, unknown>, key: string): Record<string, unknown> | null {
  const value = payload[key];
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function sanitizeToolUrl(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }

  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return null;
    }
    url.username = "";
    url.password = "";
    url.search = "";
    url.hash = "";
    return url.toString().replace(/\/$/, url.pathname === "/" ? "" : "/");
  } catch {
    return null;
  }
}

export function getToolUrl(payload: Record<string, unknown>): string | null {
  const toolCall = readRecord(payload, "tool_call");
  const observation = readRecord(payload, "observation");
  return sanitizeToolUrl(observation?.url) ?? sanitizeToolUrl(toolCall?.url);
}

export function getToolResultSummary(payload: Record<string, unknown>): string | null {
  const observation = readRecord(payload, "observation");
  const actionType = readString(payload, "action_type");
  if (actionType === "web_search") {
    const results = observation?.results;
    return Array.isArray(results) ? `找到 ${results.length} 个结果` : null;
  }
  if (actionType === "calculator") {
    const result = observation?.result;
    return typeof result === "number" && Number.isFinite(result) ? `结果 ${result}` : null;
  }
  return null;
}

export function getToolLabel(toolType: string): string {
  return {
    web_search: "联网搜索",
    http_request: "网页访问",
    extract_web_content: "网页访问",
    calculator: "计算器",
  }[toolType] ?? "工具调用";
}

export function getToolStatusCopy(
  toolType: string,
  status: "running" | "completed",
  resultSummary: string | null,
): string | null {
  if (status === "completed") {
    if (resultSummary) return resultSummary;
    if (toolType === "web_search") return "搜索完成";
    if (toolType === "calculator") return "计算完成";
    return "访问完成";
  }
  if (toolType === "web_search") return "正在搜索";
  if (toolType === "calculator") return "正在计算";
  return "正在访问";
}

export function findReasoningIndex(blocks: ThoughtNarrativeBlock[], streamId: string): number {
  return blocks.findIndex((block) => block.kind === "reasoning" && block.streamId === streamId);
}

export function findLatestToolIndex(blocks: ThoughtNarrativeBlock[], stepIndex: number, toolType: string): number {
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block = blocks[index];
    if (block.kind === "tool" && block.stepIndex === stepIndex && block.toolType === toolType) {
      return index;
    }
  }
  return -1;
}

export function buildThoughtNarrativeBlocks(
  events: AgentRunEvent[],
): ThoughtNarrativeBlock[] {
  const blocks: ThoughtNarrativeBlock[] = [];

  for (const event of [...events].sort((a, b) => a.seq - b.seq)) {
    const payload = event.payload;
    const streamId = readString(payload, "stream_id");
    const stepIndex = readNumber(payload, "step_index");

    if (event.event_type === "visible_thought_started" && streamId && stepIndex !== null) {
      if (findReasoningIndex(blocks, streamId) === -1) {
        blocks.push({
          kind: "reasoning",
          id: `reasoning-${streamId}`,
          streamId,
          stepIndex,
          text: "",
          isComplete: false,
        });
      }
      continue;
    }

    if (event.event_type === "visible_thought_delta" && streamId && stepIndex !== null) {
      let reasoningIndex = findReasoningIndex(blocks, streamId);
      if (reasoningIndex === -1) {
        blocks.push({
          kind: "reasoning",
          id: `reasoning-${streamId}`,
          streamId,
          stepIndex,
          text: "",
          isComplete: false,
        });
        reasoningIndex = blocks.length - 1;
      }

      const block = blocks[reasoningIndex];
      if (block.kind !== "reasoning") {
        continue;
      }
      const offset = readNumber(payload, "offset") ?? 0;
      const delta = typeof payload.delta === "string" ? payload.delta : "";
      if (offset === block.text.length) {
        blocks[reasoningIndex] = { ...block, text: block.text + delta };
      }
      continue;
    }

    if (event.event_type === "visible_thought_completed" && streamId && stepIndex !== null) {
      let reasoningIndex = findReasoningIndex(blocks, streamId);
      if (reasoningIndex === -1) {
        blocks.push({
          kind: "reasoning",
          id: `reasoning-${streamId}`,
          streamId,
          stepIndex,
          text: "",
          isComplete: false,
        });
        reasoningIndex = blocks.length - 1;
      }
      const block = blocks[reasoningIndex];
      if (block.kind === "reasoning") {
        blocks[reasoningIndex] = {
          ...block,
          text: typeof payload.text === "string" ? payload.text.trim() : block.text,
          isComplete: true,
        };
      }
      continue;
    }

    if (event.event_type === "visible_thought_paused" && streamId && stepIndex !== null) {
      let reasoningIndex = findReasoningIndex(blocks, streamId);
      if (reasoningIndex === -1) {
        blocks.push({
          kind: "reasoning",
          id: `reasoning-${streamId}`,
          streamId,
          stepIndex,
          text: "",
          isComplete: false,
        });
        reasoningIndex = blocks.length - 1;
      }
      const block = blocks[reasoningIndex];
      if (block.kind === "reasoning") {
        // pause 打断时 deltas 可能不完整，用事件携带的完整文本收尾
        blocks[reasoningIndex] = {
          ...block,
          text: typeof payload.text === "string" ? payload.text.trim() : block.text,
          isComplete: true,
        };
      }
      continue;
    }

    if (event.event_type === "plan_started" && streamId && stepIndex !== null) {
      if (findReasoningIndex(blocks, streamId) === -1) {
        blocks.push({
          kind: "reasoning",
          id: `reasoning-${streamId}`,
          streamId,
          stepIndex,
          text: "",
          isComplete: false,
        });
      }
      continue;
    }

    if (event.event_type === "plan_delta" && streamId && stepIndex !== null) {
      let reasoningIndex = findReasoningIndex(blocks, streamId);
      if (reasoningIndex === -1) {
        blocks.push({
          kind: "reasoning",
          id: `reasoning-${streamId}`,
          streamId,
          stepIndex,
          text: "",
          isComplete: false,
        });
        reasoningIndex = blocks.length - 1;
      }
      const block = blocks[reasoningIndex];
      if (block.kind !== "reasoning") {
        continue;
      }
      const offset = readNumber(payload, "offset") ?? 0;
      const delta = typeof payload.delta === "string" ? payload.delta : "";
      if (offset === block.text.length) {
        blocks[reasoningIndex] = { ...block, text: block.text + delta };
      }
      continue;
    }

    if (event.event_type === "plan_completed" && streamId && stepIndex !== null) {
      let reasoningIndex = findReasoningIndex(blocks, streamId);
      if (reasoningIndex === -1) {
        blocks.push({
          kind: "reasoning",
          id: `reasoning-${streamId}`,
          streamId,
          stepIndex,
          text: "",
          isComplete: false,
        });
        reasoningIndex = blocks.length - 1;
      }
      const block = blocks[reasoningIndex];
      if (block.kind === "reasoning") {
        blocks[reasoningIndex] = {
          ...block,
          text: typeof payload.text === "string" ? payload.text.trim() : block.text,
          isComplete: true,
        };
      }
      continue;
    }

    if (event.event_type === "tool_started" && stepIndex !== null) {
      const toolType = readString(payload, "action_type") ?? "external_tool";
      const previousBlock = blocks[blocks.length - 1];
      if (previousBlock?.kind === "reasoning") {
        blocks[blocks.length - 1] = { ...previousBlock, isComplete: true };
      }
      blocks.push({
        kind: "tool",
        id: `tool-${event.id}`,
        stepIndex,
        toolType,
        label: getToolLabel(toolType),
        status: "running",
        url: getToolUrl(payload),
        resultSummary: null,
      });
      continue;
    }

    if (event.event_type === "tool_completed" && stepIndex !== null) {
      const toolType = readString(payload, "action_type") ?? "external_tool";
      const toolIndex = findLatestToolIndex(blocks, stepIndex, toolType);
      if (toolIndex !== -1) {
        const block = blocks[toolIndex];
        if (block.kind === "tool") {
          blocks[toolIndex] = {
            ...block,
            status: "completed",
            url: getToolUrl(payload) ?? block.url,
            resultSummary: getToolResultSummary(payload),
          };
        }
      }
    }
  }

  return blocks.filter((block) => block.kind === "tool" || block.text.trim());
}
