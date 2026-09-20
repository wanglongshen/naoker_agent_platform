const STORE_KEY = "agent-sessions-invalidated";

export function invalidateAgentSessions(): void {
  window.dispatchEvent(new CustomEvent(STORE_KEY));
}

export function onAgentSessionsInvalidated(handler: () => void): () => void {
  window.addEventListener(STORE_KEY, handler);
  return () => window.removeEventListener(STORE_KEY, handler);
}
