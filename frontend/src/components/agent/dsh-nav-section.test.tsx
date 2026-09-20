import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import DshNavSection from "./dsh-nav-section";

const NAV = {
  currentSessionId: "s2",
  groups: [
    { key: "w1", workspaceId: "w1", label: "HC_ZiChan", sessions: [
      { id: "s2", title: "方案 A", blank: false, running: true, updatedAt: Date.now() },
      { id: "s3", title: "方案 B", blank: false, running: false, updatedAt: Date.now() },
    ]},
  ],
};

interface Overrides {
  nav?: typeof NAV | null;
  connection?: { connected: boolean; attempt: number };
  instanceState?: string;
  onSend?: (cmd: unknown) => void;
  isDshRoute?: boolean;
  onOpenAgent?: (query?: { session?: string; newSession?: boolean }) => void;
}

function renderSection(overrides: Overrides = {}) {
  return render(
    <DshNavSection
      nav={overrides.nav === undefined ? NAV : overrides.nav}
      connection={overrides.connection ?? { connected: true, attempt: 0 }}
      instanceState={overrides.instanceState ?? "running"}
      onSend={overrides.onSend ?? (() => {})}
      isDshRoute={overrides.isDshRoute ?? true}
      onOpenAgent={overrides.onOpenAgent ?? (() => {})}
    />
  );
}

describe("DshNavSection", () => {
  it("renders workspace groups, running dot and current highlight", () => {
    renderSection();
    expect(screen.getByText("HC_ZiChan")).toBeTruthy();
    expect(screen.getByText("方案 A").closest("[data-session-id]")?.getAttribute("data-current")).toBe("true");
    expect(screen.getByText("方案 A").closest("[data-session-id]")?.getAttribute("data-running")).toBe("true");
  });

  it("collapses a group on click", () => {
    renderSection();
    fireEvent.click(screen.getByText("HC_ZiChan"));
    expect(screen.queryByText("方案 A")).toBeNull();
  });

  it("clicking a session sends select-session while on /agent", () => {
    const onSend = vi.fn();
    renderSection({ onSend });
    fireEvent.click(screen.getByText("方案 B"));
    expect(onSend).toHaveBeenCalledWith({ v: 1, type: "cmd", action: "select-session", payload: { sessionId: "s3" } });
  });

  it("navigates to /agent?session=… when a session is clicked outside /agent", () => {
    const onSend = vi.fn();
    const onOpenAgent = vi.fn();
    renderSection({ onSend, onOpenAgent, isDshRoute: false });
    fireEvent.click(screen.getByText("方案 B"));
    expect(onSend).not.toHaveBeenCalled();
    expect(onOpenAgent).toHaveBeenCalledWith({ session: "s3" });
  });

  it("navigates to /agent when 新会话 is clicked outside /agent", () => {
    const onOpenAgent = vi.fn();
    renderSection({ onOpenAgent, isDshRoute: false });
    fireEvent.click(screen.getByText("+ 新会话"));
    expect(onOpenAgent).toHaveBeenCalledWith({ newSession: true });
  });

  it("shows the starting state while the instance boots", () => {
    renderSection({ nav: null, connection: { connected: false, attempt: 0 }, instanceState: "starting" });
    expect(screen.getByText(/正在启动 DSH 实例/)).toBeTruthy();
  });

  it("shows the reconnect banner while disconnected", () => {
    renderSection({ connection: { connected: false, attempt: 2 } });
    expect(screen.getByText(/正在自动重连/)).toBeTruthy();
  });
});
