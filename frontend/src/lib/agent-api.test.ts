import { describe, expect, test, vi } from "vitest";
import { agentApi } from "@/lib/agent-api";

function mockResponse(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), init);
}

function mockEnvelope<T>(data: T, init?: ResponseInit): Response {
  return mockResponse({ data, message: "OK", request_id: "req-1" }, init);
}

function makeEvent(seq: number) {
  return {
    id: `run-1:${seq}`,
    run_id: "run-1",
    attempt_id: null,
    seq,
    event_type: "test_event",
    type: "test_event",
    payload: {},
    created_at: "2026-01-01T00:00:00Z",
    timestamp: "2026-01-01T00:00:00Z",
  };
}

describe("agentApi", () => {
  test("createSession unwraps envelope", async () => {
    const session = {
      id: "sess-1",
      owner_user_id: "user-1",
      title: "test",
      last_run_id: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };

    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/auth/csrf")) {
        return Promise.resolve(mockEnvelope({ token: "csrf-token-1" }));
      }
      return Promise.resolve(mockEnvelope(session, { status: 201 }));
    });

    const result = await agentApi.createSession("test");
    expect(result).toEqual(session);

    const [, postInit] = (fetch as ReturnType<typeof vi.fn>).mock.calls.find(
      (call: [string, RequestInit?]) => call[0].includes("/sessions")
    );
    expect(postInit.headers["X-CSRF-Token"]).toBe("csrf-token-1");
    expect(postInit.headers["Content-Type"]).toBe("application/json");
  });

  test("listSessions returns paginated response", async () => {
    const page = {
      items: [
        {
          id: "sess-1",
          owner_user_id: "user-1",
          title: "test",
          last_run_id: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
      total: 1,
      page: 1,
      page_size: 20,
    };

    global.fetch = vi.fn().mockResolvedValue(mockEnvelope(page, { status: 200 }));
    const result = await agentApi.listSessions();

    expect(result.items).toHaveLength(1);
    expect(result.total).toBe(1);

    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toContain("/api/agent/sessions");
    expect(url).toContain("page=1");
  });

  test("createRun sends correct body and CSRF header", async () => {
    const run = {
      id: "run-1",
      session_id: "sess-1",
      owner_user_id: "user-1",
      goal: "analyze",
      status: "queued",
      mode: "quick",
      network_enabled: true,
      current_attempt_id: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };

    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/auth/csrf")) {
        return Promise.resolve(mockEnvelope({ token: "csrf-token-2" }));
      }
      return Promise.resolve(mockEnvelope(run, { status: 201 }));
    });

    const result = await agentApi.createRun("sess-1", {
      goal: "analyze",
      network_enabled: true,
      attachment_ids: ["att-1"],
    });
    expect(result.id).toBe("run-1");

    const [, postInit] = (fetch as ReturnType<typeof vi.fn>).mock.calls.find(
      (call: [string, RequestInit?]) => call[0].includes("/runs")
    ) as [string, RequestInit];
    expect(postInit.method).toBe("POST");
    expect(JSON.parse(postInit.body as string)).toEqual({
      goal: "analyze",
      network_enabled: true,
      attachment_ids: ["att-1"],
    });
    expect(postInit.headers["X-CSRF-Token"]).toBe("csrf-token-2");
  });

  test("cancelRun and retryRun use CSRF", async () => {
    const run = {
      id: "run-1",
      session_id: "sess-1",
      owner_user_id: "user-1",
      goal: "test",
      status: "cancelled",
      mode: "quick",
      network_enabled: true,
      current_attempt_id: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };

    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/auth/csrf")) {
        return Promise.resolve(mockEnvelope({ token: "csrf-token-3" }));
      }
      return Promise.resolve(mockEnvelope(run, { status: 200 }));
    });

    await agentApi.cancelRun("run-1");

    const calls = (fetch as ReturnType<typeof vi.fn>).mock.calls;
    const cancelCall = calls.find((c: [string]) => c[0].includes("/cancel"));
    expect(cancelCall[1].method).toBe("POST");
    expect(cancelCall[1].headers["X-CSRF-Token"]).toBe("csrf-token-3");
  });

  test("answerPendingQuestions posts answers to the answer endpoint", async () => {
    const run = {
      id: "run-9",
      session_id: "sess-1",
      owner_user_id: "user-1",
      goal: "test",
      status: "queued",
      mode: "quick",
      network_enabled: true,
      current_attempt_id: "att-2",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };

    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/auth/csrf")) {
        return Promise.resolve(mockEnvelope({ token: "csrf-token-answer" }));
      }
      return Promise.resolve(mockEnvelope(run, { status: 200 }));
    });

    const result = await agentApi.answerPendingQuestions("run-9", {
      预算级别: "50万",
    });
    expect(result.status).toBe("queued");

    const calls = (fetch as ReturnType<typeof vi.fn>).mock.calls;
    const answerCall = calls.find((c: [string]) =>
      c[0].includes("/answer")
    ) as [string, RequestInit];
    expect(answerCall[0]).toBe("/api/agent/runs/run-9/answer");
    expect(answerCall[1].method).toBe("POST");
    expect(JSON.parse(answerCall[1].body as string)).toEqual({
      answers: { 预算级别: "50万" },
    });
    expect(answerCall[1].headers["X-CSRF-Token"]).toBe("csrf-token-answer");
  });

  test("getRunEvents paginates until all events are fetched", async () => {
    const page1 = Array.from({ length: 200 }, (_, i) => makeEvent(i + 1));
    const page2 = Array.from({ length: 30 }, (_, i) => makeEvent(201 + i));
    const requests: string[] = [];

    global.fetch = vi.fn().mockImplementation((url: string) => {
      requests.push(url);
      if (url.includes("after_seq=0")) {
        return Promise.resolve(mockEnvelope({ items: page1 }));
      }
      if (url.includes("after_seq=200")) {
        return Promise.resolve(mockEnvelope({ items: page2 }));
      }
      return Promise.resolve(mockEnvelope({ items: [] }));
    });

    const events = await agentApi.getRunEvents("run-1", 0);
    expect(events).toHaveLength(230);
    expect(requests.length).toBe(3);
    expect(requests[0]).toContain("page_size=200");
    expect(requests[1]).toContain("after_seq=200");
    expect(requests[2]).toContain("after_seq=230");
  });
});
