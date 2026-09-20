import type { DshBridgeCommand, DshConnectionState, DshNavState, DshSearchResults } from "./dsh-bridge";

export interface DshBridgeSnapshot {
  nav: DshNavState | null;
  connection: DshConnectionState;
  searchResults: DshSearchResults | null;
  ready: boolean;
}

const EMPTY_SNAPSHOT: DshBridgeSnapshot = {
  nav: null,
  connection: { connected: false, attempt: 0 },
  searchResults: null,
  ready: false,
};

let snapshot: DshBridgeSnapshot = EMPTY_SNAPSHOT;
const listeners = new Set<() => void>();
let sender: ((cmd: DshBridgeCommand) => void) | null = null;

let instanceState = "starting";
let instanceStatus: DshInstanceStatus | null = null;
const instanceListeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

function publish(partial: Partial<DshBridgeSnapshot>): void {
  snapshot = { ...snapshot, ...partial };
  emit();
}

function publishNav(nav: DshNavState | null): void {
  publish({ nav });
}

function publishConnection(connection: DshConnectionState): void {
  publish({ connection });
}

function publishSearchResults(searchResults: DshSearchResults | null): void {
  publish({ searchResults });
}

function publishReady(ready: boolean): void {
  publish({ ready });
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function reset(): void {
  snapshot = { ...EMPTY_SNAPSHOT, connection: { ...EMPTY_SNAPSHOT.connection } };
  sender = null;
  emit();
}

export interface DshInstanceStatus {
  state: string;
  port: number | null;
  pid: number | null;
  last_active_at?: string | null;
  error_hint: string | null;
}

function publishInstanceStatus(status: DshInstanceStatus | null): void {
  const nextState = status?.state ?? "starting";
  const same =
    nextState === instanceState &&
    (status?.port ?? null) === (instanceStatus?.port ?? null) &&
    (status?.pid ?? null) === (instanceStatus?.pid ?? null) &&
    (status?.error_hint ?? null) === (instanceStatus?.error_hint ?? null);
  if (same) return;
  instanceStatus = status;
  instanceState = nextState;
  for (const listener of instanceListeners) listener();
}

export const dshInstanceStore = {
  getSnapshot: (): string => instanceState,
  getStatus: (): DshInstanceStatus | null => instanceStatus,
  subscribe(listener: () => void): () => void {
    instanceListeners.add(listener);
    return () => {
      instanceListeners.delete(listener);
    };
  },
  publishStatus: publishInstanceStatus,
  publish(state: string): void {
    publishInstanceStatus({ state, port: null, pid: null, error_hint: null });
  },
  reset(): void {
    instanceState = "starting";
    instanceStatus = null;
    for (const listener of instanceListeners) listener();
  },
};

export const dshBridgeStore = {
  getSnapshot: (): DshBridgeSnapshot => snapshot,
  getState: (): DshBridgeSnapshot => snapshot,
  subscribe,
  publish,
  publishNav,
  publishConnection,
  publishSearchResults,
  publishReady,
  reset,
  setSender(fn: ((cmd: DshBridgeCommand) => void) | null): void {
    sender = fn;
  },
  send(cmd: DshBridgeCommand): void {
    sender?.(cmd);
  },
};
