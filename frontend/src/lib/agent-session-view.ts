import { agentApi } from "@/lib/agent-api";
import { ApiError } from "@/lib/api";
import type { AgentConversationStep, AgentRun, AgentRunEvent, AgentSession } from "@/types/agent";

export type AgentLoadWarning = {
  scope: "session" | "runs" | "events" | "steps";
  sessionId: string;
  runId?: string;
  status?: number;
  code?: string;
  requestId?: string;
  message: string;
};

export type AgentSessionTurn = {
  run: AgentRun;
  steps: AgentConversationStep[];
  events: AgentRunEvent[];
  warning: AgentLoadWarning | null;
};

export type AgentSessionView = {
  session: AgentSession;
  turns: AgentSessionTurn[];
  warnings: AgentLoadWarning[];
};

export class AgentSessionLoadError extends Error {
  scope: AgentLoadWarning["scope"];
  status?: number;
  code?: string;
  requestId?: string;
  constructor(scope: AgentLoadWarning["scope"], status?: number, code?: string, requestId?: string) {
    super(agentLoadMessage(scope, status, code));
    this.name = "AgentSessionLoadError";
    this.scope = scope;
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

function agentLoadMessage(scope: string, status?: number, code?: string): string {
  if (status === 401) return "登录状态已过期";
  if (status === 403) return "无权访问此会话";
  if (scope === "events") return "事件回放暂时不可用";
  if (scope === "steps") return "步骤数据暂时不可用";
  if (status === 404) return scope === "session" ? "会话不存在或无权访问" : "服务暂时不可用";
  return "服务暂时不可用";
}

async function mapWithConcurrency<T, R>(items: T[], limit: number, mapper: (item: T) => Promise<R>): Promise<R[]> {
  const results: R[] = new Array(items.length);
  let cursor = 0;
  await Promise.all(
    Array.from({ length: Math.min(limit, items.length) }, async () => {
      while (cursor < items.length) {
        const index = cursor++;
        results[index] = await mapper(items[index]!);
      }
    })
  );
  return results;
}

function toAgentLoadWarning(error: unknown, scope: AgentLoadWarning["scope"], sessionId: string, runId?: string): AgentLoadWarning {
  if (error instanceof ApiError) {
    return { scope, sessionId, runId, status: error.status, code: error.code, requestId: error.requestId, message: agentLoadMessage(scope, error.status, error.code) };
  }
  return { scope, sessionId, runId, message: agentLoadMessage(scope) };
}

async function loadRunEventsWithRetry(runId: string, signal?: AbortSignal): Promise<AgentRunEvent[]> {
  try {
    return await agentApi.getRunEvents(runId, 0, signal);
  } catch (error) {
    if (signal?.aborted || (error instanceof ApiError && error.status < 500)) {
      throw error;
    }
    return agentApi.getRunEvents(runId, 0, signal);
  }
}

export async function loadAgentSessionView(sessionId: string, signal?: AbortSignal): Promise<AgentSessionView> {
  const warnings: AgentLoadWarning[] = [];

  let session: AgentSession;
  try {
    session = await agentApi.getSession(sessionId, signal);
  } catch (error) {
    throw new AgentSessionLoadError("session", error instanceof ApiError ? error.status : undefined, error instanceof ApiError ? error.code : undefined, error instanceof ApiError ? error.requestId : undefined);
  }

  let runs: AgentRun[];
  try {
    runs = await agentApi.getSessionRuns(sessionId, signal);
  } catch (error) {
    const warning = toAgentLoadWarning(error, "runs", sessionId);
    warnings.push(warning);
    return { session, turns: [], warnings };
  }

  const MAX_CONCURRENT_RUNS = 4;
  const turns: AgentSessionTurn[] = await mapWithConcurrency(runs, MAX_CONCURRENT_RUNS, async (run) => {
    const [eventsSettled, stepsSettled] = await Promise.allSettled([
      loadRunEventsWithRetry(run.id, signal),
      agentApi.getRunSteps(run.id, signal),
    ]);

    const events = eventsSettled.status === "fulfilled" ? eventsSettled.value : [];
    const steps = stepsSettled.status === "fulfilled" ? stepsSettled.value : [];

    let warning: AgentLoadWarning | null = null;
    if (eventsSettled.status === "rejected") {
      warning = toAgentLoadWarning(eventsSettled.reason, "events", sessionId, run.id);
      warnings.push(warning);
    }
    if (stepsSettled.status === "rejected") {
      const stepWarning = toAgentLoadWarning(stepsSettled.reason, "steps", sessionId, run.id);
      warnings.push(stepWarning);
      if (!warning) warning = stepWarning;
    }

    return { run, events, steps, warning };
  });

  return { session, turns, warnings };
}

function finalAnswerLength(run: AgentRun): number {
  return (run.result as { final_answer?: string } | null | undefined)?.final_answer?.trim().length ?? 0;
}

export function mergeTurnsKeepingRicherAnswer(
  current: AgentSessionTurn[],
  refreshed: AgentSessionTurn[],
): AgentSessionTurn[] {
  const currentByRunId = new Map(current.map((turn) => [turn.run.id, turn]));
  const refreshedRunIds = new Set(refreshed.map((turn) => turn.run.id));
  const mergedRefreshed = refreshed.map((next) => {
    const existing = currentByRunId.get(next.run.id);
    if (!existing) return next;

    const keepExistingAnswer = finalAnswerLength(existing.run) > finalAnswerLength(next.run);
    return {
      ...next,
      run: keepExistingAnswer
        ? { ...next.run, result: existing.run.result }
        : next.run,
      steps: next.steps.length > 0 ? next.steps : existing.steps,
      events: next.events.length > 0 ? next.events : existing.events,
      warning: next.warning ?? existing.warning,
    };
  });
  return [...mergedRefreshed, ...current.filter((turn) => !refreshedRunIds.has(turn.run.id))];
}
