import { describe, expect, test, vi, beforeEach, afterEach } from "vitest";
import { waitFor } from "@testing-library/react";

class MockEventSource {
  static instances: MockEventSource[] = [];
  static urls: string[] = [];
  static options: EventSourceInit[] = [];

  url: string;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  readyState: number = 0;
  close = vi.fn();
  private listeners: Map<string, EventListener[]> = new Map();

  constructor(url: string, options?: EventSourceInit) {
    this.url = url;
    MockEventSource.instances.push(this);
    MockEventSource.urls.push(url);
    MockEventSource.options.push(options ?? {});
  }

  addEventListener(type: string, listener: EventListener) {
    const existing = this.listeners.get(type) ?? [];
    existing.push(listener);
    this.listeners.set(type, existing);
  }

  dispatchEvent(type: string, data: string) {
    const event = new MessageEvent(type, { data });
    if (type === "message" || type === "open" || type === "error") {
      if (type === "message") this.onmessage?.(event as MessageEvent<string>);
      if (type === "open") this.onopen?.();
      if (type === "error") this.onerror?.();
    }
    const listeners = this.listeners.get(type) ?? [];
    for (const listener of listeners) {
      listener(event);
    }
  }

  static reset() {
    MockEventSource.instances = [];
    MockEventSource.urls = [];
    MockEventSource.options = [];
  }

  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
}

vi.stubGlobal("EventSource", MockEventSource);

let rafQueue: Array<FrameRequestCallback> = [];
vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
  rafQueue.push(cb);
  return rafQueue.length;
});
vi.stubGlobal("cancelAnimationFrame", () => {});

beforeEach(() => {
  rafQueue = [];
  MockEventSource.reset();
  vi.mocked(agentApi.getRun).mockClear();
  vi.mocked(agentApi.getRun).mockResolvedValue(undefined as any);
  vi.mocked(createGeneration).mockClear();
  vi.mocked(createGeneration).mockResolvedValue({ log: {} } as any);
});

afterEach(() => {
  vi.useRealTimers();
});

function flushRafQueue() {
  const cbs = rafQueue;
  rafQueue = [];
  for (const cb of cbs) {
    act(() => { cb(Date.now()); });
  }
}

import { useRunEventStream } from "@/hooks/use-run-event-stream";
import { renderHook, act } from "@testing-library/react";
import type { AgentRun, AgentRunEvent } from "@/types/agent";

vi.mock("@/lib/agent-api", () => ({
  agentApi: {
    getRun: vi.fn(),
  },
}));

vi.mock("@/lib/api", () => ({
  createGeneration: vi.fn(),
}));

import { agentApi } from "@/lib/agent-api";
import { createGeneration } from "@/lib/api";

const makeRun = (overrides: Partial<AgentRun> = {}): AgentRun => ({
  id: "run-1",
  session_id: "session-1",
  owner_user_id: "user-1",
  goal: "test",
  status: "queued",
  mode: "quick",
  network_enabled: true,
  current_attempt_id: "attempt-1",
  created_at: "2026-07-20T00:00:00Z",
  updated_at: "2026-07-20T00:00:00Z",
  ...overrides,
});

const emptyEvents: AgentRunEvent[] = [];

describe("useRunEventStream", () => {
  test("uses streamUrlWithSeq to construct the EventSource URL with after_seq", () => {
    const events: AgentRunEvent[] = [
      {
        id: "run-1:7",
        run_id: "run-1",
        attempt_id: "attempt-1",
        seq: 7,
        event_type: "answer_started",
        payload: {},
        created_at: "2026-07-20T00:00:00Z",
      },
    ];
    const run = makeRun({ status: "running" });

    renderHook(() => useRunEventStream({ runId: "run-1", initialEvents: events, initialRun: run }));

    expect(MockEventSource.urls.at(-1)).toBe("http://localhost:8010/api/agent/runs/run-1/stream?after_seq=7");
    expect(MockEventSource.options.at(-1)).toEqual({ withCredentials: true });
  });

  test("sets connection to closed when run has a terminal status", () => {
    const run = makeRun({ status: "succeeded" });

    const { result } = renderHook(() =>
      useRunEventStream({ runId: "run-1", initialEvents: emptyEvents, initialRun: run })
    );

    expect(result.current.connection).toBe("closed");
  });

  test("does not open an EventSource for a legacy completed run", () => {
    const run = makeRun({ status: "completed" as AgentRun["status"] });

    const { result } = renderHook(() =>
      useRunEventStream({ runId: "run-1", initialEvents: emptyEvents, initialRun: run })
    );

    expect(result.current.connection).toBe("closed");
    expect(MockEventSource.instances).toHaveLength(0);
  });

  test("reconnect delays follow exponential backoff capped at 5 seconds", () => {
    const run = makeRun({ status: "queued" });
    const delays: number[] = [];
    let d = 1000;
    for (let i = 0; i < 10; i++) {
      delays.push(d);
      d = Math.min(d * 2, 5000);
    }
    expect(delays).toEqual([1000, 2000, 4000, 5000, 5000, 5000, 5000, 5000, 5000, 5000]);
  });

  test("closes permanently when parsing malformed JSON (event fails)", () => {
    const run = makeRun({ status: "queued" });

    const { result } = renderHook(() =>
      useRunEventStream({ runId: "run-1", initialEvents: emptyEvents, initialRun: run })
    );

    expect(MockEventSource.instances.length).toBe(1);
    const source = MockEventSource.instances[0];

    act(() => {
      source.dispatchEvent("open", "");
    });

    act(() => {
      source.dispatchEvent("message", "not-valid-json{{{");
    });

    expect(result.current.connection).toBe("failed");
  });

  test("closes the EventSource when connection is set to failed", () => {
    const run = makeRun({ status: "queued" });

    const { unmount } = renderHook(() =>
      useRunEventStream({ runId: "run-1", initialEvents: emptyEvents, initialRun: run })
    );

    const source = MockEventSource.instances[0];
    unmount();
    expect(source.close).toHaveBeenCalledTimes(1);
  });

  test("receives run_started event and updates status to running", () => {
    const run = makeRun({ status: "queued" });

    const { result } = renderHook(() =>
      useRunEventStream({ runId: "run-1", initialEvents: emptyEvents, initialRun: run })
    );

    const source = MockEventSource.instances[0];

    act(() => {
      source.dispatchEvent("open", "");
    });

    act(() => {
      source.dispatchEvent("run_started", JSON.stringify({
        seq: 1,
        type: "run_started",
        run_id: "run-1",
        timestamp: "2026-07-20T00:00:01Z",
        payload: {},
      }));
    });

    flushRafQueue();

    expect(result.current.run?.status).toBe("running");
  });

  test("receives answer_delta events and accumulates text", () => {
    const run = makeRun({ status: "running" });

    const { result } = renderHook(() =>
      useRunEventStream({ runId: "run-1", initialEvents: emptyEvents, initialRun: run })
    );

    const source = MockEventSource.instances[0];

    act(() => {
      source.dispatchEvent("open", "");
    });

    act(() => {
      source.dispatchEvent("answer_started", JSON.stringify({
        seq: 1,
        type: "answer_started",
        run_id: "run-1",
        timestamp: "2026-07-20T00:00:00Z",
        payload: { stream_id: "answer-1" },
      }));
    });

    act(() => {
      source.dispatchEvent("answer_delta", JSON.stringify({
        seq: 2,
        type: "answer_delta",
        run_id: "run-1",
        timestamp: "2026-07-20T00:00:01Z",
        payload: { stream_id: "answer-1", offset: 0, delta: "你好" },
      }));
    });

    flushRafQueue();

    expect(result.current.answerText).toBe("你好");
  });

  test("calls onTerminalState after a run_failed event", async () => {
    const onTerminalState = vi.fn();
    const run = makeRun({ status: "queued" });

    renderHook(() =>
      useRunEventStream({
        runId: "run-1",
        initialEvents: emptyEvents,
        initialRun: run,
        onTerminalState,
      }),
    );

    const source = MockEventSource.instances[0];

    act(() => {
      source.dispatchEvent("open", "");
    });

    act(() => {
      source.dispatchEvent("run_failed", JSON.stringify({
        seq: 5,
        type: "run_failed",
        run_id: "run-1",
        timestamp: "2026-01-01T00:00:00Z",
        payload: { error: "worker_unhandled_error" },
      }));
    });

    await waitFor(() => expect(onTerminalState).toHaveBeenCalledTimes(1));
    expect(createGeneration).not.toHaveBeenCalled();
  });

  test("closes after run_succeeded and does not reconnect when the server then errors", () => {
    vi.useFakeTimers();
    const run = makeRun({ status: "running" });

    const { result } = renderHook(() =>
      useRunEventStream({ runId: "run-1", initialEvents: emptyEvents, initialRun: run }),
    );
    const source = MockEventSource.instances[0];

    act(() => {
      source.dispatchEvent("run_succeeded", JSON.stringify({
        seq: 1,
        type: "run_succeeded",
        run_id: "run-1",
        timestamp: "2026-01-01T00:00:00Z",
        payload: {},
      }));
    });

    expect(createGeneration).toHaveBeenCalledWith("session-1", "run-1");
    expect(result.current.connection).toBe("closed");
    expect(source.close).toHaveBeenCalledTimes(1);

    act(() => {
      source.dispatchEvent("error", "");
      vi.runAllTimers();
    });

    expect(MockEventSource.instances).toHaveLength(1);
    vi.useRealTimers();
  });

  test("ignores callbacks from a replaced source during a same-run reconnect", () => {
    vi.useFakeTimers();
    const run = makeRun({ status: "running" });

    const { result } = renderHook(() =>
      useRunEventStream({ runId: "run-1", initialEvents: emptyEvents, initialRun: run }),
    );
    const oldSource = MockEventSource.instances[0];

    act(() => {
      oldSource.dispatchEvent("error", "");
      vi.advanceTimersByTime(1000);
    });

    const activeSource = MockEventSource.instances[1];
    act(() => {
      oldSource.dispatchEvent("error", "");
      oldSource.dispatchEvent("answer_delta", JSON.stringify({
        seq: 1,
        type: "answer_delta",
        run_id: "run-1",
        timestamp: "2026-01-01T00:00:00Z",
        payload: { stream_id: "stale", offset: 0, delta: "OLD" },
      }));
      vi.advanceTimersByTime(1000);
    });

    expect(activeSource.close).not.toHaveBeenCalled();
    expect(MockEventSource.instances).toHaveLength(2);
    expect(result.current.answerText).not.toContain("OLD");
    vi.useRealTimers();
  });

  test("does not call onTerminalState after answer_completed alone", () => {
    const onTerminalState = vi.fn();
    const run = makeRun({ status: "running" });

    renderHook(() =>
      useRunEventStream({ runId: "run-1", initialEvents: emptyEvents, initialRun: run, onTerminalState }),
    );

    act(() => {
      MockEventSource.instances[0].dispatchEvent("answer_completed", JSON.stringify({
        seq: 1,
        type: "answer_completed",
        run_id: "run-1",
        timestamp: "2026-01-01T00:00:00Z",
        payload: { text: "完整答案" },
      }));
    });

    expect(onTerminalState).not.toHaveBeenCalled();
  });

  test("updates answerText immediately for each answer_delta event", () => {
    const run = makeRun({ status: "running" });
    const { result } = renderHook(() =>
      useRunEventStream({ runId: "run-1", initialEvents: emptyEvents, initialRun: run })
    );
    const source = MockEventSource.instances[0];

    act(() => {
      source.dispatchEvent("open", "");
    });

    act(() => {
      source.dispatchEvent("answer_started", JSON.stringify({
        seq: 1,
        type: "answer_started",
        run_id: "run-1",
        timestamp: "2026-01-01T00:00:00Z",
        payload: { stream_id: "answer-1" },
      }));
    });

    // Dispatch first delta and check immediate update
    act(() => {
      source.dispatchEvent("answer_delta", JSON.stringify({
        seq: 2,
        type: "answer_delta",
        run_id: "run-1",
        timestamp: "2026-01-01T00:00:00Z",
        payload: { stream_id: "answer-1", offset: 0, delta: "ABC" },
      }));
    });

    // One RAF callback queued — answer deltas are frame-coalesced
    expect(rafQueue.length).toBe(1);
    // answerText not yet visible (RAF hasn't fired)
    expect(result.current.answerText).toBe("");

    flushRafQueue();
    expect(result.current.answerText).toBe("ABC");

    // Dispatch remaining deltas
    for (let i = 1; i < 5; i++) {
      act(() => {
        source.dispatchEvent("answer_delta", JSON.stringify({
          seq: 2 + i,
          type: "answer_delta",
          run_id: "run-1",
          timestamp: "2026-01-01T00:00:00Z",
          payload: { stream_id: "answer-1", offset: i * 3, delta: "ABC" },
        }));
      });
    }

    // One RAF callback queued for the batch of deltas
    expect(rafQueue.length).toBe(1);
    flushRafQueue();
    expect(result.current.answerText).toBe("ABCABCABCABCABC");
  });

  test("FE-R-05: session switch closes old EventSource and prevents state contamination", () => {
    const runA = makeRun({ id: "run-a", status: "running" });
    const runB = makeRun({ id: "run-b", status: "running" });

    const { result, rerender } = renderHook(
      (props) => useRunEventStream(props),
      {
        initialProps: {
          runId: "run-a",
          initialEvents: emptyEvents,
          initialRun: runA,
        },
      },
    );

    const sourceA = MockEventSource.instances[0];
    expect(sourceA).toBeTruthy();
    expect(sourceA.url).toContain("run-a");

    rerender({
      runId: "run-b",
      initialEvents: emptyEvents,
      initialRun: runB,
    });

    expect(sourceA.close).toHaveBeenCalled();

    const sourceB = MockEventSource.instances.at(-1);
    expect(sourceB).toBeTruthy();
    expect(sourceB!.url).toContain("run-b");

    act(() => {
      sourceA.dispatchEvent(
        "answer_started",
        JSON.stringify({
          seq: 1,
          type: "answer_started",
          run_id: "run-a",
          timestamp: "2026-01-01T00:00:00Z",
          payload: { stream_id: "stale-a" },
        }),
      );
    });

    act(() => {
      sourceA.dispatchEvent(
        "answer_delta",
        JSON.stringify({
          seq: 2,
          type: "answer_delta",
          run_id: "run-a",
          timestamp: "2026-01-01T00:00:01Z",
          payload: { stream_id: "stale-a", offset: 0, delta: "OLD" },
        }),
      );
    });

    expect(result.current.run?.id).toBe("run-b");
    expect(result.current.answerText).not.toContain("OLD");
  });

  test("live answer_completed remains active until authoritative terminal state", () => {
    const run = makeRun({ status: "running" });

    const { result } = renderHook(() =>
      useRunEventStream({ runId: "run-1", initialEvents: emptyEvents, initialRun: run }),
    );

    const source = MockEventSource.instances[0];
    act(() => { source.dispatchEvent("open", ""); });

    act(() => {
      source.dispatchEvent("answer_completed", JSON.stringify({
        seq: 1,
        type: "answer_completed",
        run_id: "run-1",
        timestamp: "2026-01-01T00:00:00Z",
        payload: { text: "完整答案" },
      }));
    });

    flushRafQueue();

    expect(result.current.run?.status).toBe("running");
    expect(result.current.connection).not.toBe("closed");
    expect(result.current.answerText).toBe("完整答案");
  });

  test("closes EventSource and runs cleanup when disabled becomes true", () => {
    const run = makeRun({ status: "running" });

    const { result, rerender } = renderHook(
      ({ disabled }) => useRunEventStream({ runId: "run-1", initialEvents: emptyEvents, initialRun: run, disabled }),
      { initialProps: { disabled: false } },
    );

    expect(MockEventSource.instances).toHaveLength(1);
    const source = MockEventSource.instances[0];
    expect(result.current.connection).not.toBe("closed");

    rerender({ disabled: true });

    expect(source.close).toHaveBeenCalled();
    expect(MockEventSource.instances).toHaveLength(1);
    expect(result.current.connection).toBe("closed");
  });

  test("non-answer events (visible_thought_delta) schedule RAF instead of immediate setState", () => {
    const run = makeRun({ status: "running" });
    const { result } = renderHook(() =>
      useRunEventStream({ runId: "run-1", initialEvents: emptyEvents, initialRun: run }),
    );
    const source = MockEventSource.instances[0];

    act(() => { source.dispatchEvent("open", ""); });

    act(() => {
      source.dispatchEvent("visible_thought_delta", JSON.stringify({
        seq: 1,
        type: "visible_thought_delta",
        run_id: "run-1",
        timestamp: "2026-01-01T00:00:00Z",
        payload: { step_index: 0, stream_id: "thought-1", offset: 0, delta: "thinking..." },
      }));
    });

    expect(rafQueue.length).toBe(1);

    expect(result.current.visibleThoughtByStep[0]).toBeUndefined();

    flushRafQueue();

    expect(result.current.visibleThoughtByStep[0]).toBe("thinking...");
  });

  test("reconciles terminal run state after SSE closes without accumulated answer text", async () => {
    const mockGetRun = vi.mocked(agentApi.getRun);
    const terminalRun = makeRun({ id: "run-1", status: "succeeded", result: { final_answer: "完整答案" } });
    mockGetRun.mockResolvedValue(terminalRun);

    MockEventSource.instances = [];
    const { result } = renderHook(() =>
      useRunEventStream({
        runId: "run-1",
        initialEvents: [],
        initialRun: makeRun({ id: "run-1", status: "running" }),
      }),
    );

    const source = MockEventSource.instances[0];
    source.dispatchEvent("open", "");

    act(() => { source.readyState = EventSource.CLOSED; source.onerror?.({} as Event); });

    await waitFor(() => expect(result.current.connection).toBe("closed"));
    expect(result.current.run?.status).toBe("succeeded");
    expect(result.current.answerText).toBe("完整答案");
    expect(source.close).toHaveBeenCalled();
    expect(MockEventSource.instances).toHaveLength(1);
    expect(mockGetRun).toHaveBeenCalledTimes(1);
    expect(mockGetRun).toHaveBeenCalledWith("run-1", expect.any(AbortSignal));
  }, 10000);
});
