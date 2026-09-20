import { describe, expect, test, vi } from "vitest";
import { loadAuditSessionView } from "@/lib/audit-session-view";
import type { AuditSessionTranscript } from "@/types/agent";

function mockEnvelope<T>(data: T, init?: ResponseInit): Response {
  return new Response(JSON.stringify({ data, message: "OK", request_id: "req-1" }), init);
}

function makeTranscript(): AuditSessionTranscript {
  return {
    session: {
      id: "sess-1",
      owner_user_id: "owner-1",
      owner_display_name: "John Doe",
      title: "Test Session",
      last_run_id: "run-1",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
    owner: {
      id: "owner-1",
      username: "jdoe",
      display_name: "John Doe",
      roles: ["user_manager"],
    },
    turns: [
      {
        run: {
          id: "run-1",
          session_id: "sess-1",
          owner_user_id: "owner-1",
          goal: "test goal",
          status: "succeeded",
          mode: "quick",
          network_enabled: true,
          current_attempt_id: "att-1",
          result: { final_answer: "hello" },
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
        steps: [
          {
            id: "step-1",
            attempt_id: "att-1",
            step_number: 1,
            thought_summary: "thinking",
            action_type: "finish",
            action_payload: null,
            observation: { final_answer: "hello" },
            status: "success",
            created_at: "2026-01-01T00:00:00Z",
          },
        ],
        events: [
          {
            id: "evt-1",
            run_id: "run-1",
            attempt_id: "att-1",
            seq: 1,
            event_type: "run_queued",
            payload: { goal: "test goal" },
            created_at: "2026-01-01T00:00:00Z",
          },
          {
            id: "evt-2",
            run_id: "run-1",
            attempt_id: "att-1",
            seq: 2,
            event_type: "run_succeeded",
            payload: { final_answer: "hello" },
            created_at: "2026-01-01T00:00:01Z",
          },
        ],
      },
    ],
  };
}

describe("loadAuditSessionView", () => {
  test("returns owner identity with roles", async () => {
    const transcript = makeTranscript();
    global.fetch = vi.fn().mockResolvedValue(mockEnvelope(transcript, { status: 200 }));

    const view = await loadAuditSessionView("sess-1");

    expect(view.owner.id).toBe("owner-1");
    expect(view.owner.username).toBe("jdoe");
    expect(view.owner.display_name).toBe("John Doe");
    expect(view.owner.roles).toEqual(["user_manager"]);
  });

  test("returns session with turns in creation order", async () => {
    const transcript = makeTranscript();
    global.fetch = vi.fn().mockResolvedValue(mockEnvelope(transcript, { status: 200 }));

    const view = await loadAuditSessionView("sess-1");

    expect(view.session.id).toBe("sess-1");
    expect(view.turns).toHaveLength(1);
    expect(view.turns[0].run.goal).toBe("test goal");
    expect(view.turns[0].run.status).toBe("succeeded");
  });

  test("returns final answer from run result", async () => {
    const transcript = makeTranscript();
    global.fetch = vi.fn().mockResolvedValue(mockEnvelope(transcript, { status: 200 }));

    const view = await loadAuditSessionView("sess-1");

    expect(view.turns[0].run.result?.final_answer).toBe("hello");
  });

  test("returns steps with observation", async () => {
    const transcript = makeTranscript();
    global.fetch = vi.fn().mockResolvedValue(mockEnvelope(transcript, { status: 200 }));

    const view = await loadAuditSessionView("sess-1");

    expect(view.turns[0].steps).toHaveLength(1);
    expect(view.turns[0].steps[0].thought_summary).toBe("thinking");
    expect(view.turns[0].steps[0].observation).toEqual({ final_answer: "hello" });
  });

  test("returns redacted events", async () => {
    const transcript = makeTranscript();
    global.fetch = vi.fn().mockResolvedValue(mockEnvelope(transcript, { status: 200 }));

    const view = await loadAuditSessionView("sess-1");

    expect(view.turns[0].events).toHaveLength(2);
    expect(view.turns[0].events[0].event_type).toBe("run_queued");
    expect(view.turns[0].events[1].event_type).toBe("run_succeeded");
  });

  test("does not call owner-scoped /api/agent/runs/{id}", async () => {
    const transcript = makeTranscript();
    global.fetch = vi.fn().mockResolvedValue(mockEnvelope(transcript, { status: 200 }));

    await loadAuditSessionView("sess-1");

    const fetchCalls = (fetch as ReturnType<typeof vi.fn>).mock.calls as [string][];
    const nonAuditRunCalls = fetchCalls.filter(
      ([url]) => url.includes("/api/agent/runs/") && !url.includes("/audit/")
    );
    expect(nonAuditRunCalls).toHaveLength(0);
  });

  test("adds warning when owner is missing", async () => {
    const transcript = makeTranscript();
    (transcript as Record<string, unknown>).owner = null;
    global.fetch = vi.fn().mockResolvedValue(mockEnvelope(transcript, { status: 200 }));

    const view = await loadAuditSessionView("sess-1");

    expect(view.warning).toBe("audit transcript response missing required fields");
  });

  test("adds warning when turns are missing", async () => {
    const transcript = makeTranscript();
    (transcript as Record<string, unknown>).turns = null;
    global.fetch = vi.fn().mockResolvedValue(mockEnvelope(transcript, { status: 200 }));

    const view = await loadAuditSessionView("sess-1");

    expect(view.warning).toBe("audit transcript response missing required fields");
  });

  test("adds warning when turn has no session_id", async () => {
    const transcript = makeTranscript();
    transcript.turns[0].run.session_id = "";
    global.fetch = vi.fn().mockResolvedValue(mockEnvelope(transcript, { status: 200 }));

    const view = await loadAuditSessionView("sess-1");

    expect(view.warning).toBe("audit transcript turn missing session association");
  });
});
