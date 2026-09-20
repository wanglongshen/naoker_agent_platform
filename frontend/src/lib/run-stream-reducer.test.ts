import { describe, expect, test } from "vitest";
import {
  createInitialRunStreamState,
  hasAuthoritativeTerminalEvidence,
  hasCompletedAnswerEvidence,
  hasTerminalEvidence,
  reduceRunStream,
  shouldOpenRunStream,
  shouldResetRunStreamState,
} from "@/lib/run-stream-reducer";
import type { AgentRun, AgentRunEvent } from "@/types/agent";

describe("runStreamReducer", () => {
  test("answer_delta appends only when offset matches", () => {
    const initial = createInitialRunStreamState();
    const started = reduceRunStream(initial, {
      seq: 1,
      type: "answer_started",
      run_id: "run-1",
      timestamp: "2026-07-20T00:00:00Z",
      payload: { stream_id: "answer-1" },
    });

    const streamed = reduceRunStream(started, {
      seq: 2,
      type: "answer_delta",
      run_id: "run-1",
      timestamp: "2026-07-20T00:00:01Z",
      payload: { stream_id: "answer-1", offset: 0, delta: "你好" },
    });

    expect(streamed.answerText).toBe("你好");
  });

  test("visible_thought_delta is ignored when the offset skips ahead", () => {
    const initial = createInitialRunStreamState();
    const started = reduceRunStream(initial, {
      seq: 1,
      type: "visible_thought_started",
      run_id: "run-1",
      timestamp: "2026-07-20T00:00:00Z",
      payload: { stream_id: "thought-1", step_index: 0 },
    });

    const streamed = reduceRunStream(started, {
      seq: 2,
      type: "visible_thought_delta",
      run_id: "run-1",
      timestamp: "2026-07-20T00:00:01Z",
      payload: { stream_id: "thought-1", step_index: 0, offset: 5, delta: "跳过" },
    });

    expect(streamed.visibleThoughtByStep[0]).toBe("");
    expect(streamed.connection).toBe("reconnecting");
  });

  test("visible_thought_delta appends multiple chunks over time when offsets match", () => {
    const initial = createInitialRunStreamState();
    const started = reduceRunStream(initial, {
      seq: 1,
      type: "visible_thought_started",
      run_id: "run-1",
      timestamp: "2026-07-20T00:00:00Z",
      payload: { stream_id: "thought-1", step_index: 0 },
    });

    const firstDelta = reduceRunStream(started, {
      seq: 2,
      type: "visible_thought_delta",
      run_id: "run-1",
      timestamp: "2026-07-20T00:00:01Z",
      payload: { stream_id: "thought-1", step_index: 0, offset: 0, delta: "正在读取" },
    });

    const secondDelta = reduceRunStream(firstDelta, {
      seq: 3,
      type: "visible_thought_delta",
      run_id: "run-1",
      timestamp: "2026-07-20T00:00:02Z",
      payload: { stream_id: "thought-1", step_index: 0, offset: 4, delta: "页面内容" },
    });

    expect(firstDelta.visibleThoughtByStep[0]).toBe("正在读取");
    expect(secondDelta.visibleThoughtByStep[0]).toBe("正在读取页面内容");
    expect(secondDelta.visibleThoughtStreamIds[0]).toBe("thought-1");
    expect(secondDelta.connection).toBe("connecting");
  });

  test("answer_delta sets reconnecting when the offset skips ahead", () => {
    const initial = createInitialRunStreamState();

    const next = reduceRunStream(initial, {
      seq: 1,
      type: "answer_delta",
      run_id: "run-1",
      timestamp: "2026-07-20T00:00:00Z",
      payload: { stream_id: "answer-1", offset: 10, delta: "缺口" },
    });

    expect(next.connection).toBe("reconnecting");
    expect(next.answerText).toBe("");
  });

  test("checkpoint replay preserves the text prefix before later deltas", () => {
    const state = createInitialRunStreamState({
      initialEvents: [
        {
          id: "run-1:1",
          run_id: "run-1",
          attempt_id: null,
          seq: 1,
          event_type: "answer_started",
          payload: { stream_id: "answer-1" },
          created_at: "2026-07-20T00:00:00Z",
        },
        {
          id: "run-1:2",
          run_id: "run-1",
          attempt_id: null,
          seq: 2,
          event_type: "answer_checkpoint",
          payload: { stream_id: "answer-1", offset: 3, text: "根据现" },
          created_at: "2026-07-20T00:00:01Z",
        },
        {
          id: "run-1:3",
          run_id: "run-1",
          attempt_id: null,
          seq: 3,
          event_type: "answer_delta",
          payload: { stream_id: "answer-1", offset: 3, delta: "有资料" },
          created_at: "2026-07-20T00:00:02Z",
        },
      ],
    });

    expect(state.answerText).toBe("根据现有资料");
    expect(state.lastSeq).toBe(3);
    expect(state.connection).toBe("connecting");
  });

  test("repeated or older sequence events do not apply twice", () => {
    const initial = createInitialRunStreamState();
    const started = reduceRunStream(initial, {
      seq: 1,
      type: "answer_started",
      run_id: "run-1",
      timestamp: "2026-07-20T00:00:00Z",
      payload: { stream_id: "answer-1" },
    });
    const withDelta = reduceRunStream(started, {
      seq: 2,
      type: "answer_delta",
      run_id: "run-1",
      timestamp: "2026-07-20T00:00:01Z",
      payload: { stream_id: "answer-1", offset: 0, delta: "你好" },
    });

    const duplicate = reduceRunStream(withDelta, {
      seq: 2,
      type: "answer_delta",
      run_id: "run-1",
      timestamp: "2026-07-20T00:00:02Z",
      payload: { stream_id: "answer-1", offset: 0, delta: "你好" },
    });
    const older = reduceRunStream(withDelta, {
      seq: 1,
      type: "answer_started",
      run_id: "run-1",
      timestamp: "2026-07-20T00:00:03Z",
      payload: { stream_id: "answer-older" },
    });

    expect(duplicate).toBe(withDelta);
    expect(older).toBe(withDelta);
    expect(withDelta.answerText).toBe("你好");
    expect(withDelta.events.length).toBe(2);
  });

  test("repeated or older sequence visible-thought events do not append twice", () => {
    const initial = createInitialRunStreamState();
    const started = reduceRunStream(initial, {
      seq: 1,
      type: "visible_thought_started",
      run_id: "run-1",
      timestamp: "2026-07-20T00:00:00Z",
      payload: { stream_id: "thought-1", step_index: 0 },
    });
    const withDelta = reduceRunStream(started, {
      seq: 2,
      type: "visible_thought_delta",
      run_id: "run-1",
      timestamp: "2026-07-20T00:00:01Z",
      payload: { stream_id: "thought-1", step_index: 0, offset: 0, delta: "正在读取" },
    });

    const duplicate = reduceRunStream(withDelta, {
      seq: 2,
      type: "visible_thought_delta",
      run_id: "run-1",
      timestamp: "2026-07-20T00:00:02Z",
      payload: { stream_id: "thought-1", step_index: 0, offset: 0, delta: "正在读取" },
    });
    const older = reduceRunStream(withDelta, {
      seq: 1,
      type: "visible_thought_started",
      run_id: "run-1",
      timestamp: "2026-07-20T00:00:03Z",
      payload: { stream_id: "thought-older", step_index: 0 },
    });

    expect(duplicate).toBe(withDelta);
    expect(older).toBe(withDelta);
    expect(withDelta.visibleThoughtByStep[0]).toBe("正在读取");
    expect(withDelta.events.length).toBe(2);
  });

  test("server refresh for the same run does not reset stream state", () => {
    expect(shouldResetRunStreamState("run-1", "run-1")).toBe(false);
    expect(shouldResetRunStreamState("run-1", "run-2")).toBe(true);
  });

  test("keeps narrative events referentially stable for answer deltas", () => {
    const initial = createInitialRunStreamState();
    const started = reduceRunStream(initial, {
      seq: 1,
      type: "visible_thought_started",
      run_id: "run-1",
      timestamp: "2026-07-20T00:00:00Z",
      payload: { step_index: 0, stream_id: "thought-1" },
    });
    const narrativeEvents = started.narrativeEvents;

    const afterAnswer = reduceRunStream(started, {
      seq: 2,
      type: "answer_delta",
      run_id: "run-1",
      timestamp: "2026-07-20T00:00:01Z",
      payload: { stream_id: "answer-1", offset: 0, delta: "实时答案" },
    });

    expect(afterAnswer.events).toHaveLength(2);
    expect(afterAnswer.narrativeEvents).toBe(narrativeEvents);
  });

  test("run_completed event maps to succeeded status", () => {
    const initial = createInitialRunStreamState({
      initialRun: {
        id: "run-1",
        session_id: "session-1",
        owner_user_id: "user-1",
        goal: "test",
        status: "running",
        mode: "quick",
        network_enabled: true,
        current_attempt_id: "attempt-1",
        created_at: "2026-07-20T00:00:00Z",
        updated_at: "2026-07-20T00:00:00Z",
      },
    });

    const completedEvent = {
      seq: 5,
      type: "run_completed" as const,
      run_id: "run-1",
      timestamp: "2026-07-20T00:00:05Z",
      payload: {},
    };

    const state = reduceRunStream(initial, completedEvent);
    expect(state.run?.status).toBe("succeeded");
  });

  test.each(["succeeded", "completed"])(
    "preserves the persisted final answer while replaying stale answer events for a %s run",
    (status) => {
      const state = createInitialRunStreamState({
        initialRun: {
          id: "run-1",
          session_id: "s1",
          owner_user_id: "u1",
          goal: "test",
          status: status as any,
          mode: "quick",
          network_enabled: true,
          current_attempt_id: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
          result: { final_answer: "authoritative" },
        },
        initialEvents: [
          {
            id: "run-1:1",
            run_id: "run-1",
            attempt_id: null,
            seq: 1,
            event_type: "answer_started",
            payload: { stream_id: "answer-1" },
            created_at: "2026-07-27T00:00:00Z",
          },
          {
            id: "run-1:2",
            run_id: "run-1",
            attempt_id: null,
            seq: 2,
            event_type: "answer_checkpoint",
            payload: { stream_id: "answer-1", text: "stale" },
            created_at: "2026-07-27T00:00:01Z",
          },
          {
            id: "run-1:3",
            run_id: "run-1",
            attempt_id: null,
            seq: 3,
            event_type: "answer_completed",
            payload: { text: "stale" },
            created_at: "2026-07-27T00:00:02Z",
          },
        ],
      });

      expect(state.answerText).toBe("authoritative");
      expect(state.run?.result?.final_answer).toBe("authoritative");
      expect(state.run?.status).toBe(status);
    }
  );

  test("replays answer events normally for a running run", () => {
    const state = createInitialRunStreamState({
      initialRun: {
        id: "run-1",
        session_id: "s1",
        owner_user_id: "u1",
        goal: "test",
        status: "running",
        mode: "quick",
        network_enabled: true,
        current_attempt_id: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
        result: { final_answer: "authoritative" },
      },
      initialEvents: [
        {
          id: "run-1:1",
          run_id: "run-1",
          attempt_id: null,
          seq: 1,
          event_type: "answer_started",
          payload: { stream_id: "answer-1" },
          created_at: "2026-07-27T00:00:00Z",
        },
        {
          id: "run-1:2",
          run_id: "run-1",
          attempt_id: null,
          seq: 2,
          event_type: "answer_checkpoint",
          payload: { stream_id: "answer-1", text: "stale" },
          created_at: "2026-07-27T00:00:01Z",
        },
        {
          id: "run-1:3",
          run_id: "run-1",
          attempt_id: null,
          seq: 3,
          event_type: "answer_completed",
          payload: { text: "stale" },
          created_at: "2026-07-27T00:00:02Z",
        },
      ],
    });

    expect(state.answerText).toBe("stale");
    expect(state.run?.result?.final_answer).toBe("stale");
    expect(state.run?.status).toBe("running");
  });

  test("empty terminal payload preserves the accumulated answer text", () => {
    const state = createInitialRunStreamState({
      initialRun: {
        id: "run-1",
        session_id: "s1",
        owner_user_id: "u1",
        goal: "test",
        status: "running",
        mode: "quick",
        network_enabled: true,
        current_attempt_id: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    });
    const withAnswer = reduceRunStream(state, {
      seq: 1,
      type: "answer_delta",
      run_id: "run-1",
      timestamp: "2026-07-27T00:00:00Z",
      payload: { offset: 0, delta: "已累积答案" },
    });
    const completed = reduceRunStream(withAnswer, {
      seq: 2,
      type: "answer_completed",
      run_id: "run-1",
      timestamp: "2026-07-27T00:00:01Z",
      payload: { text: "" },
    });

    expect(completed.answerText).toBe("已累积答案");
    expect(completed.run?.result?.final_answer).toBe("已累积答案");
  });

  it("persists answer_completed text for a replayed succeeded run", () => {
    const state = createInitialRunStreamState({ initialRun: { id: "run-1", session_id: "s1", owner_user_id: "u1", goal: "test", status: "running", mode: "quick", network_enabled: true, current_attempt_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" } });
    const next = reduceRunStream(state, {
      seq: 9,
      type: "answer_completed",
      run_id: "run-1",
      timestamp: "2026-07-25T00:00:00Z",
      payload: { stream_id: "answer-run-1", text: "历史最终答案" },
    });
    expect(next.answerText).toBe("历史最终答案");
    expect((next.run as any)?.result?.final_answer).toBe("历史最终答案");
    expect(next.run?.status).toBe("running");
  });

  it("maps run_succeeded to a closed succeeded state", () => {
    const state = createInitialRunStreamState({ initialRun: { id: "run-1", session_id: "s1", owner_user_id: "u1", goal: "test", status: "running", mode: "quick", network_enabled: true, current_attempt_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" } });
    const next = reduceRunStream(state, {
      seq: 10,
      type: "run_succeeded",
      run_id: "run-1",
      timestamp: "2026-07-25T00:00:00Z",
      payload: {},
    });
    expect(next.run?.status).toBe("succeeded");
    expect(next.connection).toBe("closed");
  });

  const makeEvent = (overrides: Partial<AgentRunEvent> = {}): AgentRunEvent => ({
    id: `run-1:${overrides.seq ?? 1}`,
    run_id: "run-1",
    attempt_id: null,
    seq: overrides.seq ?? 1,
    event_type: "answer_started",
    payload: {},
    created_at: "2026-07-20T00:00:00Z",
    ...overrides,
  });

  const makeRun = (overrides: Partial<AgentRun> = {}): AgentRun => ({
    id: "run-1",
    session_id: "session-1",
    owner_user_id: "user-1",
    goal: "test",
    status: "running",
    mode: "quick",
    network_enabled: true,
    current_attempt_id: "attempt-1",
    created_at: "2026-07-20T00:00:00Z",
    updated_at: "2026-07-20T00:00:00Z",
    ...overrides,
  });

  describe("hasTerminalEvidence", () => {
    test("returns true when events contain answer_completed", () => {
      const events = [
        makeEvent({ seq: 1, event_type: "answer_completed", payload: { text: "done" } }),
      ];
      expect(hasTerminalEvidence(events)).toBe(true);
    });

    test("returns true for each listed terminal event type", () => {
      const terminalTypes = ["run_succeeded", "run_completed", "run_failed", "run_cancelled", "answer_completed"];
      for (const type of terminalTypes) {
        const events = [makeEvent({ seq: 1, event_type: type })];
        expect(hasTerminalEvidence(events)).toBe(true);
      }
    });

    test("returns false when events contain only non-terminal types", () => {
      const events = [
        makeEvent({ seq: 1, event_type: "answer_delta" }),
        makeEvent({ seq: 2, event_type: "visible_thought_started" }),
        makeEvent({ seq: 3, event_type: "visible_thought_delta" }),
        makeEvent({ seq: 4, event_type: "answer_started" }),
      ];
      expect(hasTerminalEvidence(events)).toBe(false);
    });

    test("returns false for empty event list", () => {
      expect(hasTerminalEvidence([])).toBe(false);
    });
  });

  describe("shouldOpenRunStream (old signature tests adapted)", () => {
    test("returns false when terminal events contain run_succeeded for latest running turn", () => {
      const run = makeRun({ status: "running" });
      expect(shouldOpenRunStream(run, true, [
        makeEvent({ event_type: "run_succeeded" }),
      ] as any)).toBe(false);
    });

    test("returns true for latest running turn without terminal evidence", () => {
      const run = makeRun({ status: "running" });
      expect(shouldOpenRunStream(run, true, [])).toBe(true);
      expect(shouldOpenRunStream(run, false, [])).toBe(false);
      expect(shouldOpenRunStream(makeRun({ status: "succeeded" }), true, [])).toBe(false);
    });

    test("queued latest turn now opens SSE", () => {
      const run = makeRun({ status: "queued" as AgentRun["status"] });
      expect(shouldOpenRunStream(run, true, [])).toBe(true);
    });

    test("historical run with answer_completed but no terminal is static", () => {
      const run = makeRun({ status: "running" });
      expect(shouldOpenRunStream(run, false, [
        makeEvent({ event_type: "answer_completed", payload: { text: "done" } }),
      ] as any)).toBe(false);
    });

    test("only latest running turn opens one EventSource (logic)", () => {
      const run1 = makeRun({ id: "run-1", status: "running" });
      const run2 = makeRun({ id: "run-2", status: "running" });
      expect(shouldOpenRunStream(run1, false, [])).toBe(false);
      expect(shouldOpenRunStream(run2, true, [])).toBe(true);
    });
  });

  describe("Corrected SSE opening rules (answer_completed is NOT terminal)", () => {
    describe("hasAuthoritativeTerminalEvidence", () => {
      test("returns true when run has a terminal raw status", () => {
        expect(hasAuthoritativeTerminalEvidence(makeRun({ status: "succeeded" }), [])).toBe(true);
        expect(hasAuthoritativeTerminalEvidence(makeRun({ status: "succeeded" }), [])).toBe(true);
        expect(hasAuthoritativeTerminalEvidence(makeRun({ status: "failed" }), [])).toBe(true);
        expect(hasAuthoritativeTerminalEvidence(makeRun({ status: "cancelled" }), [])).toBe(true);
      });

      test("returns true when events contain a terminal event type", () => {
        expect(hasAuthoritativeTerminalEvidence(makeRun({ status: "running" }), [
          makeEvent({ seq: 1, event_type: "run_succeeded" }),
        ])).toBe(true);
        expect(hasAuthoritativeTerminalEvidence(makeRun({ status: "running" }), [
          makeEvent({ seq: 2, event_type: "run_failed" }),
        ])).toBe(true);
        expect(hasAuthoritativeTerminalEvidence(makeRun({ status: "running" }), [
          makeEvent({ seq: 3, event_type: "run_cancelled" }),
        ])).toBe(true);
        expect(hasAuthoritativeTerminalEvidence(makeRun({ status: "running" }), [
          makeEvent({ seq: 4, event_type: "run_completed" }),
        ])).toBe(true);
      });

      test("returns false when only answer_completed is present", () => {
        expect(hasAuthoritativeTerminalEvidence(makeRun({ status: "running" }), [
          makeEvent({ seq: 1, event_type: "answer_completed", payload: { text: "done" } }),
        ])).toBe(false);
      });

      test("returns false for queued/retry_wait runs with no terminal events", () => {
        expect(hasAuthoritativeTerminalEvidence(makeRun({ status: "queued" }), [])).toBe(false);
        expect(hasAuthoritativeTerminalEvidence(makeRun({ status: "retry_wait" }), [])).toBe(false);
      });

      test("returns false for running run with no terminal events", () => {
        expect(hasAuthoritativeTerminalEvidence(makeRun({ status: "running" }), [])).toBe(false);
      });

      test("handles null/undefined run", () => {
        expect(hasAuthoritativeTerminalEvidence(null, [])).toBe(false);
        expect(hasAuthoritativeTerminalEvidence(undefined, [])).toBe(false);
      });
    });

    describe("hasCompletedAnswerEvidence", () => {
      test("returns true when answer_completed has non-empty text", () => {
        expect(hasCompletedAnswerEvidence([
          makeEvent({ seq: 1, event_type: "answer_completed", payload: { text: "完整答案" } }),
        ])).toBe(true);
      });

      test("returns false when answer_completed has empty text", () => {
        expect(hasCompletedAnswerEvidence([
          makeEvent({ seq: 1, event_type: "answer_completed", payload: { text: "" } }),
        ])).toBe(false);
      });

      test("returns false when answer_completed has no text key", () => {
        expect(hasCompletedAnswerEvidence([
          makeEvent({ seq: 1, event_type: "answer_completed", payload: {} }),
        ])).toBe(false);
      });

      test("returns false when answer_completed has whitespace-only text", () => {
        expect(hasCompletedAnswerEvidence([
          makeEvent({ seq: 1, event_type: "answer_completed", payload: { text: "   " } }),
        ])).toBe(false);
      });

      test("returns false for non-answer_completed events", () => {
        expect(hasCompletedAnswerEvidence([
          makeEvent({ seq: 1, event_type: "answer_delta" }),
        ])).toBe(false);
      });

      test("returns false for empty event list", () => {
        expect(hasCompletedAnswerEvidence([])).toBe(false);
      });
    });

    describe("shouldOpenRunStream (corrected)", () => {
      test("queued latest run opens SSE", () => {
        expect(shouldOpenRunStream(makeRun({ status: "queued" } as AgentRun["status"]), true, [])).toBe(true);
      });

      test("running latest run with answer_completed but no run_succeeded still opens SSE", () => {
        expect(shouldOpenRunStream(makeRun({ status: "running" }), true, [
          makeEvent({ event_type: "answer_completed", payload: { text: "done" } }),
        ] as any)).toBe(true);
      });

      test("succeeded run never opens SSE", () => {
        expect(shouldOpenRunStream(makeRun({ status: "succeeded" }), true, [])).toBe(false);
      });

      test("non-latest running turn never opens SSE", () => {
        expect(shouldOpenRunStream(makeRun({ status: "running" }), false, [])).toBe(false);
      });

      test("retry_wait latest run opens SSE", () => {
        expect(shouldOpenRunStream(makeRun({ status: "retry_wait" } as AgentRun["status"]), true, [])).toBe(true);
      });

      test("failed run never opens SSE", () => {
        expect(shouldOpenRunStream(makeRun({ status: "failed" }), true, [])).toBe(false);
      });

      test("cancelled run never opens SSE", () => {
        expect(shouldOpenRunStream(makeRun({ status: "cancelled" }), true, [])).toBe(false);
      });

      test("run with run_succeeded event never opens SSE", () => {
        expect(shouldOpenRunStream(makeRun({ status: "running" }), true, [
          makeEvent({ event_type: "run_succeeded" }),
        ] as any)).toBe(false);
      });

      test("run with run_failed event never opens SSE", () => {
        expect(shouldOpenRunStream(makeRun({ status: "running" }), true, [
          makeEvent({ event_type: "run_failed" }),
        ] as any)).toBe(false);
      });
    });
  });

  describe("Phase 1: final-answer gap tests (FE-R-02, FE-R-03, FE-R-04)", () => {
    test("FE-R-02: run_succeeded with final_answer only (no deltas)", () => {
      const state = createInitialRunStreamState({
        initialRun: {
          id: "run-1",
          session_id: "s1",
          owner_user_id: "u1",
          goal: "test",
          status: "running",
          mode: "quick",
          network_enabled: true,
          current_attempt_id: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      });

      const result = reduceRunStream(state, {
        seq: 5,
        type: "run_succeeded",
        run_id: "run-1",
        timestamp: "2026-07-25T00:00:00Z",
        payload: { final_answer: "完整答案" },
      });

      expect(result.run?.status).toBe("succeeded");
      expect(result.connection).toBe("closed");
      expect(result.answerText).toBe("完整答案");
      expect(result.run?.result?.final_answer).toBe("完整答案");
    });

    test("FE-R-03: answer_completed followed by run_succeeded preserves text without duplication", () => {
      const state = createInitialRunStreamState({
        initialRun: {
          id: "run-1",
          session_id: "s1",
          owner_user_id: "u1",
          goal: "test",
          status: "running",
          mode: "quick",
          network_enabled: true,
          current_attempt_id: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      });

      const afterCompleted = reduceRunStream(state, {
        seq: 8,
        type: "answer_completed",
        run_id: "run-1",
        timestamp: "2026-07-25T00:00:01Z",
        payload: { stream_id: "answer-1", text: "完整答案" },
      });

      const afterSucceeded = reduceRunStream(afterCompleted, {
        seq: 9,
        type: "run_succeeded",
        run_id: "run-1",
        timestamp: "2026-07-25T00:00:02Z",
        payload: { final_answer: "完整答案" },
      });

      expect(afterSucceeded.answerText).toBe("完整答案");
      expect(afterSucceeded.run?.result?.final_answer).toBe("完整答案");
      expect(afterSucceeded.run?.status).toBe("succeeded");
      expect(afterSucceeded.connection).toBe("closed");
      expect(afterSucceeded.lastSeq).toBe(9);
    });

    test("answer_failed sets connection to reconnecting to allow recovery", () => {
    const state = createInitialRunStreamState({
      initialRun: {
        id: "run-1",
        session_id: "s1",
        owner_user_id: "u1",
        goal: "test",
        status: "running",
        mode: "quick",
        network_enabled: true,
        current_attempt_id: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    });

    const result = reduceRunStream(state, {
      seq: 1,
      type: "answer_failed",
      run_id: "run-1",
      timestamp: "2026-07-25T00:00:00Z",
      payload: { error: "stream_corrupted" },
    });

    expect(result.connection).toBe("reconnecting");
    expect(result.lastSeq).toBe(1);
    expect(result.events).toHaveLength(1);
    expect(result.events[0].event_type).toBe("answer_failed");
  });

  test("FE-R-04: idempotent replay of same sequence does not change state", () => {
      const state = createInitialRunStreamState({
        initialRun: {
          id: "run-1",
          session_id: "s1",
          owner_user_id: "u1",
          goal: "test",
          status: "running",
          mode: "quick",
          network_enabled: true,
          current_attempt_id: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      });

      const after1 = reduceRunStream(state, {
        seq: 10,
        type: "answer_started",
        run_id: "run-1",
        timestamp: "2026-07-25T00:00:01Z",
        payload: { stream_id: "answer-1" },
      });

      const after2 = reduceRunStream(after1, {
        seq: 10,
        type: "answer_started",
        run_id: "run-1",
        timestamp: "2026-07-25T00:00:02Z",
        payload: { stream_id: "answer-seen" },
      });

      expect(after2).toBe(after1);
      expect(after2.answerStreamId).toBe("answer-1");
      expect(after2.lastSeq).toBe(10);
      expect(after2.events.length).toBe(1);
    });
  });

  describe("plan events", () => {
    test("plan_delta appends text to visibleThoughtByStep[0]", () => {
      const state = createInitialRunStreamState();
      const afterStarted = reduceRunStream(state, {
        seq: 1,
        type: "plan_started",
        run_id: "run-1",
        timestamp: "2026-07-30T00:00:00Z",
        payload: { step_index: 0, stream_id: "plan-1" },
      });
      expect(afterStarted.visibleThoughtByStep[0]).toBe("");

      const afterDelta = reduceRunStream(afterStarted, {
        seq: 2,
        type: "plan_delta",
        run_id: "run-1",
        timestamp: "2026-07-30T00:00:01Z",
        payload: { step_index: 0, stream_id: "plan-1", offset: 0, delta: "\u5206\u6790" },
      });
      expect(afterDelta.visibleThoughtByStep[0]).toBe("\u5206\u6790");

      const afterMore = reduceRunStream(afterDelta, {
        seq: 3,
        type: "plan_delta",
        run_id: "run-1",
        timestamp: "2026-07-30T00:00:02Z",
        payload: { step_index: 0, stream_id: "plan-1", offset: 2, delta: "\u9700\u6c42" },
      });
      expect(afterMore.visibleThoughtByStep[0]).toBe("\u5206\u6790\u9700\u6c42");
    });

    test("plan_completed sets final text", () => {
      const state = createInitialRunStreamState();
      const afterStarted = reduceRunStream(state, {
        seq: 1,
        type: "plan_started",
        run_id: "run-1",
        timestamp: "2026-07-30T00:00:00Z",
        payload: { step_index: 0, stream_id: "plan-2" },
      });
      const afterCompleted = reduceRunStream(afterStarted, {
        seq: 2,
        type: "plan_completed",
        run_id: "run-1",
        timestamp: "2026-07-30T00:00:01Z",
        payload: { step_index: 0, stream_id: "plan-2", text: "\u5b8c\u6574\u89c4\u5212", length: 4 },
      });
      expect(afterCompleted.visibleThoughtByStep[0]).toBe("\u5b8c\u6574\u89c4\u5212");
    });
  });
});
