"use client";

import { useEffect, useRef, useState } from "react";

import {
  isTerminalAgentRunStatus,
  parseStreamEvent,
  STREAM_EVENT_TYPES,
  streamUrlWithSeq,
} from "@/lib/agent-stream";
import {
  createInitialRunStreamState,
  reduceRunStream,
  shouldResetRunStreamState,
  type RunStreamState,
} from "@/lib/run-stream-reducer";
import type { AgentRun, AgentRunEvent } from "@/types/agent";
import { agentApi } from "@/lib/agent-api";
import { createGeneration } from "@/lib/api";

type UseRunEventStreamOptions = {
  runId: string;
  initialEvents: AgentRunEvent[];
  initialRun: AgentRun | null;
  onTerminalState?: (run: AgentRun) => void;
  disabled?: boolean;
};

const MAX_RETRY_DELAY_MS = 5000;
const MAX_RETRY_ATTEMPTS = 8;
const INITIAL_RETRY_DELAY_MS = 250;

export function useRunEventStream({ runId, initialEvents, initialRun, onTerminalState, disabled }: UseRunEventStreamOptions): RunStreamState {
  const [state, setState] = useState<RunStreamState>(() =>
    createInitialRunStreamState({
      initialEvents,
      initialRun: (initialRun ?? undefined),
      disabled,
    }),
  );
  const stateRef = useRef(state);
  const activeRunIdRef = useRef(runId);
  const lastNotifiedRef = useRef<string | null>(null);
  const onTerminalStateRef = useRef(onTerminalState);
  onTerminalStateRef.current = onTerminalState;
  const reconcilingRef = useRef(false);
  const rafPendingRef = useRef(false);
  const rafHandleRef = useRef<number>(0);

  useEffect(() => {
    if (!shouldResetRunStreamState(activeRunIdRef.current, runId)) {
      if (initialRun && isTerminalAgentRunStatus(initialRun.status)) {
        setState((current) => ({
          ...current,
          run: initialRun,
          connection: "closed",
        }));
      }
      return;
    }
    const nextState = createInitialRunStreamState({ initialEvents, initialRun: initialRun ?? undefined });
    activeRunIdRef.current = runId;
    stateRef.current = nextState;
    setState(nextState);
  }, [initialEvents, initialRun, runId, disabled]);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    if (disabled) {
      setState((current) => ({ ...current, connection: "closed" }));
      return;
    }

    const status = stateRef.current.run?.status ?? initialRun?.status;
    if (status && isTerminalAgentRunStatus(status)) {
      setState((current) => ({ ...current, connection: "closed" }));
      return;
    }

    let closed = false;
    let retryDelayMs = INITIAL_RETRY_DELAY_MS;
    let retryCount = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let source: EventSource | null = null;
    let reconcileAbort: AbortController | null = null;
    let connectTimer: ReturnType<typeof setTimeout> | null = null;

    const clearReconnectTimer = () => {
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    const updateState = (nextState: RunStreamState) => {
      stateRef.current = nextState;
      setState(nextState);
    };

    const scheduleReconnect = () => {
      if (closed || reconnectTimer !== null) {
        return;
      }

      if (retryCount >= MAX_RETRY_ATTEMPTS) {
        updateState({ ...stateRef.current, connection: "failed" });
        return;
      }

      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, retryDelayMs);
      retryDelayMs = Math.min(retryDelayMs * 2, MAX_RETRY_DELAY_MS);
      retryCount += 1;
    };

    async function performReconciliation() {
      if (reconcilingRef.current) return;
      reconcilingRef.current = true;

      if (reconcileAbort) {
        reconcileAbort.abort();
      }
      reconcileAbort = new AbortController();
      const signal = reconcileAbort.signal;

      try {
        const fetchedRun = await agentApi.getRun(runId, signal);

        if (closed || signal.aborted) return;

        if (fetchedRun && isTerminalAgentRunStatus(fetchedRun.status)) {
          const currentState = stateRef.current;

          if (currentState.answerText) {
            return;
          }

          const mergeResult = fetchedRun.result != null
            ? { ...(currentState.run?.result ?? {}), ...fetchedRun.result }
            : currentState.run?.result;

          updateState({
            ...currentState,
            run: {
              ...(currentState.run ?? fetchedRun),
              status: fetchedRun.status,
              result: mergeResult ?? null,
            },
            answerText: currentState.answerText || fetchedRun.result?.final_answer?.trim() || "",
            connection: "closed",
          });

          clearReconnectTimer();
          source?.close();
          source = null;

          const key = `${fetchedRun.id}:${fetchedRun.status}`;
          if (lastNotifiedRef.current !== key) {
            lastNotifiedRef.current = key;
            if (fetchedRun.status === "succeeded") {
              createGeneration(fetchedRun.session_id, fetchedRun.id).catch(() => {});
            }
            onTerminalStateRef.current?.(fetchedRun);
          }
        }
      } catch {
        if (!signal.aborted) {
          // Reconciliation failed, reconnect was already scheduled
        }
      } finally {
        if (reconcileAbort?.signal === signal) {
          reconcileAbort = null;
        }
        reconcilingRef.current = false;
      }
    }

    const handleDisconnect = (eventSource: EventSource, connection: RunStreamState["connection"]) => {
      if (source !== eventSource) {
        return;
      }
      eventSource.close();
      source = null;
      clearReconnectTimer();
      updateState({ ...stateRef.current, connection });

      if (connection === "reconnecting") {
        scheduleReconnect();
      }
    };

    const handleMessage = (eventSource: EventSource, messageEvent: MessageEvent<string>) => {
      if (closed || source !== eventSource) return;
      let parsed;
      try {
        parsed = parseStreamEvent(messageEvent.data);
      } catch {
        handleDisconnect(eventSource, "failed");
        return;
      }

      const now = performance.now();
      if (!window.__perf) {
        window.__perf = { firstEventAt: now, eventCount: 0, frameCount: 0, reconnectCount: 0, lastAnswerLen: 0, connStart: now };
      }
      const p = window.__perf;
      p.eventCount++;

      const nextState = reduceRunStream(stateRef.current, parsed);

      stateRef.current = nextState;
      if (!rafPendingRef.current) {
        rafPendingRef.current = true;
        rafHandleRef.current = requestAnimationFrame(() => {
          rafPendingRef.current = false;
          if (window.__perf) window.__perf.frameCount++;
          setState({ ...stateRef.current });
        });
      }

      if (parsed.type === "answer_completed" || parsed.type === "run_succeeded") {
        const elapsed = ((performance.now() - p.firstEventAt) / 1000).toFixed(1);
        console.log(
          `%c[PERF] %c${parsed.type} %c@${elapsed}s %c| ${p.eventCount}evt ${p.frameCount}frames ${p.reconnectCount}reconn %c| answer=${p.lastAnswerLen}chars`,
          "color:#16a34a;font-weight:bold", "color:inherit", "color:#D96313", "color:#888", ""
        );
      }

      if (
        nextState.run &&
        isTerminalAgentRunStatus(nextState.run.status)
      ) {
        if (rafPendingRef.current) {
          rafPendingRef.current = false;
          cancelAnimationFrame(rafHandleRef.current);
          setState({ ...stateRef.current });
        }
        const key = `${nextState.run.id}:${nextState.run.status}`;
        if (lastNotifiedRef.current !== key) {
          lastNotifiedRef.current = key;
          if (nextState.run.status === "succeeded") {
            createGeneration(nextState.run.session_id, nextState.run.id).catch(() => {});
          }
          onTerminalStateRef.current?.(nextState.run);
        }
      }

      if (nextState.run && isTerminalAgentRunStatus(nextState.run.status)) {
        clearReconnectTimer();
        source?.close();
        source = null;
        updateState({ ...nextState, connection: "closed" });
      } else if (nextState.connection === "reconnecting") {
        handleDisconnect(eventSource, "reconnecting");
      }
    };

    function connect() {
      if (closed) {
        return;
      }

      clearReconnectTimer();
      if (connectTimer !== null) {
        clearTimeout(connectTimer);
        connectTimer = null;
      }
      updateState({
        ...stateRef.current,
        connection: stateRef.current.lastSeq > 0 ? "reconnecting" : "connecting",
      });

      connectTimer = setTimeout(() => {
        if (closed || source?.readyState !== EventSource.CONNECTING) return;
        connectTimer = null;
        source?.close();
        source = null;
        scheduleReconnect();
      }, 15_000);

      const eventSource = new EventSource(streamUrlWithSeq(runId, stateRef.current.lastSeq), {
        withCredentials: true,
      });
      source = eventSource;
      eventSource.onopen = () => {
        if (closed || source !== eventSource) return;
        if (connectTimer !== null) {
          clearTimeout(connectTimer);
          connectTimer = null;
        }
        retryDelayMs = INITIAL_RETRY_DELAY_MS;
        retryCount = 0;
        updateState({ ...stateRef.current, connection: "open", liveStreamed: true });
      };
      eventSource.onerror = () => {
        if (closed || source !== eventSource) return;

        const currentStatus = stateRef.current.run?.status;
        if (currentStatus && isTerminalAgentRunStatus(currentStatus)) {
          handleDisconnect(eventSource, "closed");
          return;
        }

        if (eventSource.readyState === EventSource.CLOSED && retryCount >= MAX_RETRY_ATTEMPTS) {
          eventSource.close();
          source = null;
          updateState({ ...stateRef.current, connection: "failed" });
          return;
        }

        if (window.__perf) {
          window.__perf.reconnectCount++;
          console.log(
            `%c[PERF] %creconnect #${window.__perf.reconnectCount} %c@${(performance.now() / 1000).toFixed(1)}s %c| status=${currentStatus ?? "?"} retry=${retryCount}`,
            "color:#c24141;font-weight:bold", "color:inherit", "color:#c24141", "color:#888"
          );
        }

        handleDisconnect(eventSource, "reconnecting");

        if (currentStatus && !isTerminalAgentRunStatus(currentStatus) && !reconcilingRef.current) {
          performReconciliation();
        }
      };
      eventSource.onmessage = (messageEvent) => handleMessage(eventSource, messageEvent);

      for (const eventType of STREAM_EVENT_TYPES) {
        eventSource.addEventListener(eventType, ((messageEvent: MessageEvent<string>) =>
          handleMessage(eventSource, messageEvent)) as EventListener);
      }
    }

    connect();

    return () => {
      closed = true;
      clearReconnectTimer();
      if (connectTimer !== null) {
        clearTimeout(connectTimer);
        connectTimer = null;
      }
      source?.close();
      source = null;
      if (reconcileAbort) {
        reconcileAbort.abort();
        reconcileAbort = null;
      }
    };
  }, [initialRun?.status, runId, disabled]);

  return state;
}
