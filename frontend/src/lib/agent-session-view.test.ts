import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";

vi.mock("@/lib/agent-api", () => ({ agentApi: {
  getSession: vi.fn(),
  getSessionRuns: vi.fn(),
  getRunEvents: vi.fn(),
  getRunSteps: vi.fn(),
}}));

import { agentApi } from "@/lib/agent-api";

const session = { id: "session-1", title: "测试会话", owner_user_id: "u1", last_run_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" } as const;
const run1 = { id: "run-1", session_id: "session-1", owner_user_id: "u1", goal: "run1 goal", status: "succeeded", mode: "quick", network_enabled: true, current_attempt_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" } as const;
const run2 = { ...run1, id: "run-2", goal: "run2 goal" };
const events1 = [{ id: "evt-1", run_id: "run-1", attempt_id: null, seq: 1, event_type: "run_queued", payload: {}, created_at: "2026-01-01T00:00:00Z" }];
const steps1 = [{ id: "stp-1", attempt_id: "a1", step_number: 0, thought_summary: "test", action_type: "finish", action_payload: null, observation: null, status: "succeeded", created_at: "2026-01-01T00:00:00Z" }];

import { loadAgentSessionView } from "./agent-session-view";

describe("loadAgentSessionView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns source-shaped turns while isolating one failed historical run", async () => {
    vi.mocked(agentApi.getSession).mockResolvedValue(session as any);
    vi.mocked(agentApi.getSessionRuns).mockResolvedValue([run1 as any, run2 as any]);
    vi.mocked(agentApi.getRunEvents).mockResolvedValueOnce(events1 as any).mockRejectedValueOnce(new ApiError(404, "RESOURCE_NOT_FOUND", "events unavailable", null, "req-2"));
    vi.mocked(agentApi.getRunSteps).mockResolvedValueOnce(steps1 as any).mockResolvedValueOnce([]);

    const view = await loadAgentSessionView("session-1");

    expect(view.session).toEqual(session);
    expect(view.turns).toHaveLength(2);
    expect(view.turns[0]).toMatchObject({ run: run1, warning: null });
    expect(view.turns[1]).toMatchObject({ run: run2, events: [], steps: [] });
    expect(view.warnings).toEqual([expect.objectContaining({ scope: "events", runId: run2.id, requestId: "req-2" })]);
  });

  it("returns warnings with stable Chinese messages for ApiErrors", async () => {
    vi.mocked(agentApi.getSession).mockResolvedValue(session as any);
    vi.mocked(agentApi.getSessionRuns).mockResolvedValue([run1 as any]);
    vi.mocked(agentApi.getRunEvents).mockRejectedValue(new ApiError(404, "RESOURCE_NOT_FOUND", "not found", null, "req-404"));
    vi.mocked(agentApi.getRunSteps).mockResolvedValue([]);

    const view = await loadAgentSessionView("session-1");
    expect(view.warnings[0].message).toBe("事件回放暂时不可用");
  });

  it("preserves answer events when step diagnostics fail", async () => {
    vi.mocked(agentApi.getSession).mockResolvedValue(session as any);
    vi.mocked(agentApi.getSessionRuns).mockResolvedValue([run1 as any]);
    vi.mocked(agentApi.getRunEvents).mockResolvedValue(events1 as any);
    vi.mocked(agentApi.getRunSteps).mockRejectedValue(new ApiError(500, "INTERNAL_ERROR", "", null, "req-steps"));

    const view = await loadAgentSessionView("session-1");

    expect(view.turns[0].events).toEqual(events1);
    expect(view.turns[0].steps).toEqual([]);
    expect(view.warnings).toEqual([expect.objectContaining({ scope: "steps", requestId: "req-steps", message: "步骤数据暂时不可用" })]);
  });

  it("shows events warning when events fail but steps succeed", async () => {
    vi.mocked(agentApi.getSession).mockResolvedValue(session as any);
    vi.mocked(agentApi.getSessionRuns).mockResolvedValue([run1 as any]);
    vi.mocked(agentApi.getRunEvents).mockRejectedValue(new ApiError(500, "INTERNAL_ERROR", "", null, "req-evt"));
    vi.mocked(agentApi.getRunSteps).mockResolvedValue(steps1 as any);

    const view = await loadAgentSessionView("session-1");
    expect(view.turns[0].events).toEqual([]);
    expect(view.turns[0].steps).toEqual(steps1);
    expect(view.warnings).toEqual([expect.objectContaining({ scope: "events", requestId: "req-evt" })]);
  });

  it("retries a transient event replay failure before warning the conversation", async () => {
    vi.mocked(agentApi.getSession).mockResolvedValue(session as any);
    vi.mocked(agentApi.getSessionRuns).mockResolvedValue([run1 as any]);
    vi.mocked(agentApi.getRunEvents)
      .mockRejectedValueOnce(new ApiError(503, "SERVICE_UNAVAILABLE", "temporary", null, "req-transient"))
      .mockResolvedValueOnce(events1 as any);
    vi.mocked(agentApi.getRunSteps).mockResolvedValue(steps1 as any);

    const view = await loadAgentSessionView("session-1");

    expect(agentApi.getRunEvents).toHaveBeenCalledTimes(2);
    expect(view.turns[0].events).toEqual(events1);
    expect(view.warnings).toEqual([]);
  });

  it("throws for a required session request failure with a load error", async () => {
    vi.mocked(agentApi.getSession).mockRejectedValue(new ApiError(404, "RESOURCE_NOT_FOUND", "gone", null, "req-s-404"));
    await expect(loadAgentSessionView("session-1")).rejects.toMatchObject({ scope: "session", status: 404, code: "RESOURCE_NOT_FOUND" });
  });

  it("limits concurrent diagnostic jobs with a bounded mapper", async () => {
    vi.mocked(agentApi.getSession).mockResolvedValue(session as any);
    const runs = Array.from({ length: 6 }, (_, i) => ({ ...run1, id: `run-${i}` }));
    vi.mocked(agentApi.getSessionRuns).mockResolvedValue(runs as any);

    let active = 0;
    let maxActive = 0;

    vi.mocked(agentApi.getRunEvents).mockImplementation(() => {
      active++;
      maxActive = Math.max(maxActive, active);
      return Promise.resolve(events1 as any).finally(() => { active--; });
    });
    vi.mocked(agentApi.getRunSteps).mockImplementation(() => {
      active++;
      maxActive = Math.max(maxActive, active);
      return Promise.resolve(steps1 as any).finally(() => { active--; });
    });

    await expect(loadAgentSessionView("session-1")).resolves.toBeDefined();
    expect(maxActive).toBeLessThanOrEqual(8);
  });
});
