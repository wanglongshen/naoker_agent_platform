import { describe, expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import FinalAnswerPanel from "@/components/agent/final-answer-panel";
import type { AgentRun } from "@/types/agent";

function createRun(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    id: "run-1",
    session_id: "s1",
    owner_user_id: "u1",
    goal: "test goal",
    status: "running",
    mode: "normal",
    network_enabled: false,
    current_attempt_id: "att-1",
    result: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("FinalAnswerPanel", () => {
  test("shows loading indicator when answerStreamId is set but streamingAnswer is empty", () => {
    const run = createRun({ status: "running" });
    render(
      <FinalAnswerPanel
        run={run}
        streamingAnswer=""
        answerStreamId="stream-1"
        isLiveRun={true}
      />
    );
    expect(screen.getByText("正在生成回答")).toBeVisible();
  });

  test("shows loading indicator when answerStreamId is set and streamingAnswer is whitespace-only", () => {
    const run = createRun({ status: "running" });
    render(
      <FinalAnswerPanel
        run={run}
        streamingAnswer="   "
        answerStreamId="stream-1"
        isLiveRun={true}
      />
    );
    expect(screen.getByText("正在生成回答")).toBeVisible();
  });

  test("does not show loading indicator when streamingAnswer has content", () => {
    const run = createRun({ status: "running" });
    render(
      <FinalAnswerPanel
        run={run}
        streamingAnswer="hello"
        answerStreamId="stream-1"
        isLiveRun={true}
      />
    );
    expect(screen.queryByText("正在生成回答")).not.toBeInTheDocument();
  });
});
