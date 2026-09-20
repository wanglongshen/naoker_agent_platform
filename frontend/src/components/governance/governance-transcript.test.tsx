import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import GovernanceTranscript from "@/components/governance/governance-transcript";
import type { AuditSessionView } from "@/lib/audit-session-view";

function makeView(overrides: Partial<AuditSessionView> = {}): AuditSessionView {
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
        steps: [],
        events: [],
      },
    ],
    ...overrides,
  };
}

describe("GovernanceTranscript", () => {
  it("renders owner context with display_name and username", () => {
    const view = makeView();
    render(<GovernanceTranscript view={view} />);

    expect(screen.getByText("John Doe")).toBeDefined();
    expect(screen.getByText("jdoe")).toBeDefined();
  });

  it("renders conversation transcript region", () => {
    const view = makeView();
    render(<GovernanceTranscript view={view} />);

    expect(screen.getByRole("region", { name: "对话全文" })).toBeDefined();
  });

  it("renders collapsible diagnostics section default collapsed", () => {
    const view = makeView();
    render(<GovernanceTranscript view={view} />);

    const diagButton = screen.getByRole("button", { name: /展开运行诊断/ });
    expect(diagButton).toBeDefined();
    expect(diagButton).toHaveAttribute("aria-expanded", "false");
  });

  it("expands diagnostics on click", () => {
    const view = makeView();
    render(<GovernanceTranscript view={view} />);

    const diagButton = screen.getByRole("button", { name: /展开运行诊断/ });
    fireEvent.click(diagButton);

    expect(diagButton).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: /收起运行诊断/ })).toBeDefined();
  });

  it("does not display privileged-access wording", () => {
    const view = makeView();
    render(<GovernanceTranscript view={view} />);

    expect(screen.queryByText(/特权访问/)).toBeNull();
    expect(screen.queryByText(/自动留痕/)).toBeNull();
  });

  it("renders session title in transcript", () => {
    const view = makeView();
    render(<GovernanceTranscript view={view} />);

    expect(screen.getByText("Test Session")).toBeDefined();
  });

  it("shows owner roles", () => {
    const view = makeView();
    render(<GovernanceTranscript view={view} />);

    expect(screen.getByText("user_manager")).toBeDefined();
  });
});
