import type { AgentSessionView } from "./agent-session-view";

const cache = new Map<string, AgentSessionView>();

export function readSessionView(sessionId: string): AgentSessionView | null {
  return cache.get(sessionId) ?? null;
}

export function writeSessionView(view: AgentSessionView): void {
  cache.set(view.session.id, view);
}

export function invalidateSessionView(sessionId: string): void {
  cache.delete(sessionId);
}

export function clearSessionViewCache(): void {
  cache.clear();
}
