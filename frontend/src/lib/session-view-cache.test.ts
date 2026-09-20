import { describe, expect, test } from "vitest";

const { readSessionView, writeSessionView, invalidateSessionView, clearSessionViewCache } = await vi.importActual("../lib/session-view-cache");

const view = {
  session: { id: "session-1", title: "test", owner_user_id: "u1", last_run_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
  turns: [],
  warnings: [],
} as any;

describe("sessionViewCache", () => {
  test("returns cached view until invalidated", () => {
    writeSessionView(view);
    expect(readSessionView("session-1")).toEqual(view);
    invalidateSessionView("session-1");
    expect(readSessionView("session-1")).toBeNull();
  });

  test("clearSessionViewCache removes all entries", () => {
    writeSessionView(view);
    writeSessionView({ ...view, session: { ...view.session, id: "session-2" } });
    clearSessionViewCache();
    expect(readSessionView("session-1")).toBeNull();
    expect(readSessionView("session-2")).toBeNull();
  });
});
