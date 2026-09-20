"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

export type DshBridgeAction =
  | "new-session"
  | "select-session"
  | "search-sessions"
  | "open-settings"
  | "open-filter"
  | "add-workspace";

export interface DshBridgeCommand {
  v: 1;
  type: "cmd";
  action: DshBridgeAction;
  payload?: { sessionId?: string; workspaceId?: string; query?: string };
}

export interface DshSessionNode {
  id: string;
  title: string;
  blank: boolean;
  running: boolean;
  updatedAt: number;
}

export interface DshWorkspaceGroup {
  key: string;
  workspaceId?: string;
  label: string;
  sessions: DshSessionNode[];
}

export interface DshNavState {
  currentSessionId?: string;
  groups: DshWorkspaceGroup[];
}

export interface DshSearchResults {
  query: string;
  items: { id: string; snippet: string }[];
}

export interface DshConnectionState {
  connected: boolean;
  attempt: number;
}

export type DshBridgeEvent =
  | { v: 1; type: "state"; event: "ready"; payload: { currentSessionId?: string } }
  | { v: 1; type: "state"; event: "nav"; payload: DshNavState }
  | { v: 1; type: "state"; event: "search-results"; payload: DshSearchResults }
  | { v: 1; type: "state"; event: "connection"; payload: { connected: boolean; attempt?: number } };

export function useDshBridge(iframeRef: RefObject<HTMLIFrameElement | null>) {
  const [nav, setNav] = useState<DshNavState | null>(null);
  const [connection, setConnection] = useState<DshConnectionState>({ connected: false, attempt: 0 });
  const [searchResults, setSearchResults] = useState<DshSearchResults | null>(null);
  const [ready, setReady] = useState(false);
  const trackedFrameRef = useRef<HTMLIFrameElement | null>(null);
  const frameLoadCountRef = useRef(0);

  useEffect(() => {
    function onMessage(event: MessageEvent) {
      const frame = iframeRef.current;
      if (!frame || event.source !== frame.contentWindow) return;
      const data = event.data as { v?: number; type?: string; event?: string; payload?: unknown } | null;
      if (!data || data.v !== 1 || data.type !== "state") return;
      if (data.event === "ready") {
        setReady(true);
        setConnection({ connected: true, attempt: 0 });
        return;
      }
      if (data.event === "nav") {
        setNav(data.payload as DshNavState);
        return;
      }
      if (data.event === "search-results") {
        setSearchResults(data.payload as DshSearchResults);
        return;
      }
      if (data.event === "connection") {
        const p = data.payload as { connected?: boolean; attempt?: number } | undefined;
        setConnection({ connected: p?.connected === true, attempt: p?.attempt ?? 0 });
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [iframeRef]);

  useEffect(() => {
    function reset() {
      setReady(false);
      setNav(null);
      setSearchResults(null);
      setConnection({ connected: false, attempt: 0 });
    }
    const frame = iframeRef.current;
    if (!frame) return;
    if (trackedFrameRef.current !== frame) {
      trackedFrameRef.current = frame;
      frameLoadCountRef.current = 0;
      reset();
    }
    function onLoad() {
      frameLoadCountRef.current += 1;
      // The first load of an element delivers the document whose bridge state
      // this hook already holds; later loads replace it and invalidate state.
      if (frameLoadCountRef.current > 1) reset();
    }
    frame.addEventListener("load", onLoad);
    return () => frame.removeEventListener("load", onLoad);
  });

  const send = useCallback((cmd: DshBridgeCommand) => {
    iframeRef.current?.contentWindow?.postMessage(cmd, "*");
  }, [iframeRef]);

  return { nav, connection, searchResults, ready, send };
}
