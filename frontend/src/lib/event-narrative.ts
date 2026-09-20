import type { AgentRun, AgentRunEvent, AgentStep } from "@/types/agent";

type RunEventPayload = Record<string, unknown>;

type DiagnosticRun = AgentRun & {
  current_step?: number | null;
  max_steps?: number | null;
  retry_count?: number | null;
  error?: string | null;
};

function getString(payload: RunEventPayload, key: string): string | null {
  const value = payload[key];
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function getNumber(payload: RunEventPayload, key: string): number | null {
  const value = payload[key];
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function buildStepMap(steps: AgentStep[]): Map<number, AgentStep> {
  const map = new Map<number, AgentStep>();
  for (const step of steps) {
    map.set(step.step_number, step);
  }
  return map;
}

export function formatToolCall(
  actionType: string | null,
  _payload: Record<string, unknown> | null,
  _fallbackPayload?: Record<string, unknown> | null,
): string | null {
  if (actionType !== "http_request") {
    return null;
  }
  return "工具调用：网页访问";
}

export function describePlanCreated(payload: RunEventPayload): string {
  const thought = getString(payload, "thought_summary") ?? "我正在规划最合适的下一步操作。";
  return `我先对当前目标进行了判断：${thought}`;
}

export function describeStepCompleted(payload: RunEventPayload, stepMap: Map<number, AgentStep>): string | null {
  const stepIndex = getNumber(payload, "step_index");
  const actionType = getString(payload, "action_type");
  const observation = getString(payload, "observation_summary");
  const thoughtSummary = getString(payload, "thought_summary");
  const step = stepIndex === null ? null : (stepMap.get(stepIndex) ?? null);
  const resolvedActionType = actionType ?? step?.action_type ?? null;

  if (resolvedActionType !== "http_request") {
    return null;
  }

  const label = stepIndex === null ? "我完成了一次信息检索" : `第 ${stepIndex + 1} 步检索已经完成`;
  const detail = observation ?? thoughtSummary ?? step?.thought_summary?.trim() ?? "并获得了可以继续推进回答的结果。";
  const stepPayload = step?.action_payload as Record<string, unknown> | null;
  const toolCall = formatToolCall(resolvedActionType, stepPayload, payload);
  const completionText = `${label}，${detail}`;

  return toolCall ? `${toolCall}\n${completionText}` : completionText;
}

export function describeRetryScheduled(payload: RunEventPayload, run: DiagnosticRun): string {
  const retryCount = getNumber(payload, "retry_count") ?? run.retry_count ?? 0;
  const error = getString(payload, "error") ?? run.error ?? "未知错误";
  return `执行过程中遇到问题：${error}。系统已安排第 ${retryCount} 次自动重试。`;
}

export function describeRetryResumed(payload: RunEventPayload, run: DiagnosticRun): string {
  const retryCount = getNumber(payload, "retry_count") ?? run.retry_count ?? 0;
  return retryCount > 0
    ? `系统恢复了执行流程，并开始第 ${retryCount} 次继续尝试。`
    : "系统恢复了执行流程，并继续尝试完成当前任务。";
}

export function describeRunFailed(payload: RunEventPayload, run: DiagnosticRun): string {
  const reason = getString(payload, "error") ?? getString(payload, "reason") ?? run.error ?? "未提供具体原因";
  return `最终当前路径未能稳定完成任务，原因是：${reason}。`;
}

export function describeEvent(event: AgentRunEvent, run: DiagnosticRun, stepMap: Map<number, AgentStep>): string | null {
  switch (event.event_type) {
    case "run_queued":
      return "用户提交了一个新任务，系统已将其加入执行队列。";
    case "run_started":
      return "系统已经开始执行当前任务。";
    case "plan_created":
      return describePlanCreated(event.payload);
    case "step_completed":
      return describeStepCompleted(event.payload, stepMap);
    case "visible_thought_started":
      return "我已经确定了下一步动作，开始整理一条对用户可见的进展说明。";
    case "visible_thought_completed":
      return getString(event.payload, "text") ?? "我已经补充了一条当前进展说明。";
    case "visible_thought_failed":
      return "当前进展说明未能完整生成，系统已改用安全的简短描述继续执行。";
    case "tool_started":
      return formatToolCall(getString(event.payload, "action_type"), event.payload, null) ?? "工具调用：开始执行外部操作";
    case "tool_completed": {
      const toolLabel = formatToolCall(getString(event.payload, "action_type"), event.payload, null) ?? "工具调用：外部操作已完成";
      const observation = getString(event.payload, "observation_summary") ?? "已返回可用于继续回答的结果。";
      return `${toolLabel}\n${observation}`;
    }
    case "answer_started":
      return "现有信息已经足够，我正在整理最终回答。";
    case "answer_failed":
      return "最终回答在生成过程中中断了，这轮任务暂时无法返回完整结论。";
    case "run_retry_scheduled":
      return describeRetryScheduled(event.payload, run);
    case "run_retry_resumed":
      return describeRetryResumed(event.payload, run);
    case "run_failed":
      return describeRunFailed(event.payload, run);
    case "run_cancelled":
      return "这轮任务已按用户要求停止。";
    case "run_retried":
      return "我会沿用当前会话上下文重新尝试这轮任务。";
    case "run_completed":
    case "run_succeeded":
      return "任务已完成，最终答案已经生成。";
    default:
      return null;
  }
}

export function describeThoughtEvent(event: AgentRunEvent, run: DiagnosticRun, stepMap: Map<number, AgentStep>): string | null {
  if (["run_queued", "run_started", "run_completed", "run_succeeded", "answer_delta", "answer_checkpoint", "answer_completed", "visible_thought_delta"].includes(event.event_type)) {
    return null;
  }
  return describeEvent(event, run, stepMap);
}
