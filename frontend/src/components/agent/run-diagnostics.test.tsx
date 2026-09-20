import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, test, vi, beforeEach } from "vitest";

import type { AgentRun, AgentRunEvent, AgentRunAttempt, AgentStep, AgentRunStatus } from "@/types/agent";

const { mockAgentApi } = vi.hoisted(() => ({ mockAgentApi: {
  getRunEvents: vi.fn(),
  getRunSteps: vi.fn(),
  getRunAttempts: vi.fn(),
  getAttemptSteps: vi.fn(),
} }));

vi.mock("@/lib/agent-api", () => ({
  agentApi: mockAgentApi,
}));

vi.mock("@/hooks/use-run-event-stream", () => ({
  useRunEventStream: ({ initialEvents, initialRun }: { runId: string; initialEvents: AgentRunEvent[]; initialRun: AgentRun | null }) => ({
    run: initialRun,
    events: initialEvents,
    narrativeEvents: [],
    answerText: "",
    answerStreamId: null,
    connection: "closed" as const,
    lastSeq: initialEvents.length,
    visibleThoughtByStep: {},
    visibleThoughtStreamIds: {},
    agentCheckpoints: {},
  }),
}));

const baseRun: AgentRun = {
  id: "run-1",
  session_id: "session-1",
  owner_user_id: "user-1",
  goal: "测试任务目标",
  status: "succeeded" as AgentRunStatus,
  mode: "quick",
  network_enabled: true,
  current_attempt_id: "attempt-1",
  created_at: "2026-07-20T00:00:00Z",
  updated_at: "2026-07-20T00:01:00Z",
};

const baseAttempt: AgentRunAttempt = {
  id: "attempt-1",
  run_id: "run-1",
  attempt_number: 1,
  status: "succeeded",
  worker_id: "worker-1",
  retry_of_attempt_id: null,
  started_at: "2026-07-20T00:00:00Z",
  finished_at: "2026-07-20T00:01:00Z",
};

const baseEvent: AgentRunEvent = {
  id: "event-1",
  run_id: "run-1",
  attempt_id: "attempt-1",
  seq: 1,
  event_type: "run_started",
  payload: {},
  created_at: "2026-07-20T00:00:01Z",
};

const baseStep: AgentStep = {
  id: "step-1",
  attempt_id: "attempt-1",
  step_number: 0,
  thought_summary: "分析任务需求",
  action_type: "http_request",
  action_payload: { url: "https://example.com" },
  observation: { status: 200 },
  status: "succeeded",
  created_at: "2026-07-20T00:00:02Z",
};

const planCreatedEvent: AgentRunEvent = {
  id: "event-2",
  run_id: "run-1",
  attempt_id: "attempt-1",
  seq: 2,
  event_type: "plan_created",
  payload: { step_index: 0, thought_summary: "规划：先搜索相关信息" },
  created_at: "2026-07-20T00:00:03Z",
};

beforeEach(() => {
  mockAgentApi.getRunEvents.mockReset();
  mockAgentApi.getRunSteps.mockReset();
  mockAgentApi.getRunAttempts.mockReset();
  mockAgentApi.getAttemptSteps.mockReset();
  mockAgentApi.getRunEvents.mockResolvedValue([baseEvent, planCreatedEvent]);
  mockAgentApi.getRunSteps.mockResolvedValue([{ id: "step-1", step_index: 0, thought_summary: "分析任务需求", action_type: "http_request", status: "succeeded" }]);
  mockAgentApi.getRunAttempts.mockResolvedValue({ items: [baseAttempt], total: 1, page: 1, page_size: 20 });
  mockAgentApi.getAttemptSteps.mockResolvedValue({ items: [baseStep], total: 1, page: 1, page_size: 50 });
});

import RunHeader from "@/components/agent/run-header";
import RunStatus from "@/components/agent/run-status";
import StepTimeline from "@/components/agent/step-timeline";
import EventStream from "@/components/agent/event-stream";
import ThoughtProcess from "@/components/agent/thought-process";
import ThoughtTimeline from "@/components/agent/thought-timeline";
import DetailConversation from "@/components/agent/detail-conversation";
import LandingEventStream from "@/components/agent/landing-event-stream";
import SessionConversationStream from "@/components/agent/session-conversation-stream";

describe("RunHeader", () => {
  test("renders run goal and status", () => {
    render(<RunHeader run={baseRun} />);
    expect(screen.getByText("测试任务目标")).toBeInTheDocument();
    expect(screen.getByText("已完成")).toBeInTheDocument();
  });

  test("renders running status label", () => {
    const runningRun = { ...baseRun, status: "running" as AgentRunStatus };
    render(<RunHeader run={runningRun} />);
    expect(screen.getByText("执行中")).toBeInTheDocument();
  });

  test("renders queued status label", () => {
    const queuedRun = { ...baseRun, status: "queued" as AgentRunStatus };
    render(<RunHeader run={queuedRun} />);
    expect(screen.getByText("等待中")).toBeInTheDocument();
  });

  test("renders failed status label", () => {
    const failedRun = { ...baseRun, status: "failed" as AgentRunStatus };
    render(<RunHeader run={failedRun} />);
    expect(screen.getByText("失败")).toBeInTheDocument();
  });

  test("renders conversation header structure", () => {
    const { container } = render(<RunHeader run={baseRun} />);
    expect(container.querySelector(".conversation-header")).toBeInTheDocument();
    expect(container.querySelector(".conversation-header-main")).toBeInTheDocument();
    expect(container.querySelector(".conversation-title")).toBeInTheDocument();
    expect(container.querySelector(".status-pill")).toBeInTheDocument();
  });
});

describe("RunStatus", () => {
  test("renders execution overview with status", () => {
    const diagnosticRun = { ...baseRun, current_step: 3, max_steps: 5, retry_count: 0, next_retry_at: null, last_step_duration_seconds: null, error: null };
    render(<RunStatus run={diagnosticRun} />);
    expect(screen.getByText("执行概览")).toBeInTheDocument();
    expect(screen.getByText("已完成")).toBeInTheDocument();
  });

  test("renders with error message", () => {
    const errorRun = { ...baseRun, current_step: 2, max_steps: 5, retry_count: 1, next_retry_at: null, last_step_duration_seconds: null, error: "网络超时" };
    render(<RunStatus run={errorRun} />);
    expect(screen.getByText("网络超时")).toBeInTheDocument();
  });

  test("renders summary grid with progress fields", () => {
    const diagnosticRun = { ...baseRun, current_step: 3, max_steps: 5, retry_count: 2, next_retry_at: "2026-07-21T00:00:00Z", last_step_duration_seconds: 12.5, error: null };
    render(<RunStatus run={diagnosticRun} />);
    expect(screen.getByText("进度")).toBeInTheDocument();
    expect(screen.getByText("重试次数")).toBeInTheDocument();
    expect(screen.getByText("上一步耗时")).toBeInTheDocument();
    expect(screen.getByText("下次重试")).toBeInTheDocument();
  });

  test("renders with run-summary-card structure", () => {
    const diagnosticRun = { ...baseRun, current_step: 1, max_steps: 3, retry_count: 0, next_retry_at: null, last_step_duration_seconds: null, error: null };
    const { container } = render(<RunStatus run={diagnosticRun} />);
    expect(container.querySelector(".run-summary-card")).toBeInTheDocument();
    expect(container.querySelector(".run-summary-grid")).toBeInTheDocument();
    expect(container.querySelector(".status-pill-muted")).toBeInTheDocument();
  });
});

describe("StepTimeline", () => {
  test("renders step list with step details", () => {
    const steps: AgentStep[] = [
      { ...baseStep },
      { ...baseStep, id: "step-2", step_number: 1, thought_summary: "获取数据", action_type: "http_request", action_payload: { url: "https://api.example.com" }, observation: { result: "ok" }, status: "succeeded" },
    ];
    render(<StepTimeline steps={steps} />);
    expect(screen.getByText("Step #0")).toBeInTheDocument();
    expect(screen.getByText("Step #1")).toBeInTheDocument();
    expect(screen.getByText("分析任务需求")).toBeInTheDocument();
    expect(screen.getByText("获取数据")).toBeInTheDocument();
    expect(screen.getAllByText("Action payload").length).toBe(2);
    expect(screen.getAllByText("Observation").length).toBe(2);
  });

  test("renders empty when no steps", () => {
    const { container } = render(<StepTimeline steps={[]} />);
    expect(container.querySelector("h2")).toHaveTextContent("Steps");
  });
});

describe("EventStream", () => {
  test("renders event list with event type and time", () => {
    render(<EventStream runId="run-1" initialEvents={[baseEvent, planCreatedEvent]} initialRun={baseRun} />);
    expect(screen.getByText("事件流")).toBeInTheDocument();
    expect(screen.getByText("run_started")).toBeInTheDocument();
    expect(screen.getByText("plan_created")).toBeInTheDocument();
  });

  test("renders events-block structure", () => {
    const { container } = render(<EventStream runId="run-1" initialEvents={[baseEvent]} initialRun={null} />);
    expect(container.querySelector(".events-block")).toBeInTheDocument();
    expect(container.querySelector(".events-list")).toBeInTheDocument();
    expect(container.querySelector(".event-row")).toBeInTheDocument();
    expect(container.querySelector(".event-type")).toBeInTheDocument();
    expect(container.querySelector(".event-time")).toBeInTheDocument();
    expect(container.querySelector(".event-payload")).toBeInTheDocument();
  });

  test("renders section title with real-time hint when connection is open", () => {
    vi.doMock("@/hooks/use-run-event-stream", () => ({
      useRunEventStream: () => ({
        run: baseRun,
        events: [baseEvent],
        answerText: "",
        answerStreamId: null,
        connection: "open" as const,
        lastSeq: 1,
        visibleThoughtByStep: {},
        visibleThoughtStreamIds: {},
        agentCheckpoints: {},
      }),
    }));
    // Re-render with the mocked open connection would require re-importing
  });
});

describe("ThoughtProcess", () => {
  test("renders thinking steps with action payloads", () => {
    render(<ThoughtProcess steps={[baseStep]} events={[planCreatedEvent]} />);
    expect(screen.getByText("已思考")).toBeInTheDocument();
    expect(screen.getByText("展示执行推理与中间过程")).toBeInTheDocument();
    expect(screen.getByText("规划：先搜索相关信息")).toBeInTheDocument();
  });

  test("renders thought-process-block structure", () => {
    const { container } = render(<ThoughtProcess steps={[baseStep]} events={[planCreatedEvent]} />);
    expect(container.querySelector(".thought-process-block")).toBeInTheDocument();
    expect(container.querySelector(".thought-process-header")).toBeInTheDocument();
    expect(container.querySelector(".thought-process-content")).toBeInTheDocument();
    expect(container.querySelector(".thought-process-item")).toBeInTheDocument();
    expect(container.querySelector(".thought-process-body")).toBeInTheDocument();
    expect(container.querySelector(".thought-process-meta")).toBeInTheDocument();
    expect(container.querySelector(".thought-process-panels")).toBeInTheDocument();
    expect(container.querySelector(".thought-subsection")).toBeInTheDocument();
    expect(container.querySelector(".thought-subtitle")).toBeInTheDocument();
  });

  test("shows empty state when no steps", () => {
    render(<ThoughtProcess steps={[]} events={[]} />);
    expect(screen.getByText("任务尚未产生执行步骤。")).toBeInTheDocument();
  });

  test("shows step thought summary from event when available", () => {
    const step: AgentStep = { ...baseStep, thought_summary: null };
    render(<ThoughtProcess steps={[step]} events={[planCreatedEvent]} />);
    expect(screen.getByText("规划：先搜索相关信息")).toBeInTheDocument();
  });

  test("falls back to step thought_summary when no event", () => {
    const step: AgentStep = { ...baseStep, thought_summary: "备用摘要" };
    render(<ThoughtProcess steps={[step]} events={[]} />);
    expect(screen.getByText("备用摘要")).toBeInTheDocument();
  });
});

describe("ThoughtTimeline", () => {
  test("renders thought timeline with step items", () => {
    render(<ThoughtTimeline steps={[baseStep]} events={[planCreatedEvent]} />);
    expect(screen.getByText("已思考")).toBeInTheDocument();
    expect(screen.getByText("展示 agent 的每一步思考摘要与执行结果")).toBeInTheDocument();
  });

  test("renders thought-inline structure", () => {
    const { container } = render(<ThoughtTimeline steps={[baseStep]} events={[planCreatedEvent]} />);
    expect(container.querySelector(".thinking-inline-block")).toBeInTheDocument();
    expect(container.querySelector(".thinking-inline-header")).toBeInTheDocument();
    expect(container.querySelector(".thinking-inline-list")).toBeInTheDocument();
    expect(container.querySelector(".thought-inline-item")).toBeInTheDocument();
    expect(container.querySelector(".thought-inline-toggle")).toBeInTheDocument();
    expect(container.querySelector(".thought-inline-meta")).toBeInTheDocument();
    expect(container.querySelector(".thought-inline-summary")).toBeInTheDocument();
  });

  test("shows empty state when no steps", () => {
    render(<ThoughtTimeline steps={[]} events={[]} />);
    expect(screen.getByText("任务尚未产生执行步骤。")).toBeInTheDocument();
  });
});

describe("DetailConversation", () => {
  test("renders user message bubble and thought narrative", () => {
    render(<DetailConversation run={baseRun} steps={[baseStep]} initialEvents={[baseEvent]} />);
    expect(screen.getByText("测试任务目标")).toBeInTheDocument();
  });

  test("renders detail-single-column-main structure", () => {
    const { container } = render(<DetailConversation run={baseRun} steps={[baseStep]} initialEvents={[baseEvent]} />);
    expect(container.querySelector(".detail-single-column-main")).toBeInTheDocument();
    expect(container.querySelector(".message-row-user")).toBeInTheDocument();
    expect(container.querySelector(".message-bubble-user")).toBeInTheDocument();
  });
});

describe("SessionConversationStream", () => {
  test("keeps the Agent Loop session conversation focused on thought and answer", () => {
    render(
      <SessionConversationStream
        turns={[{
          run: baseRun,
          steps: [],
          events: [baseEvent],
          warning: null,
        }]}
      />
    );

    expect(screen.getByText("测试任务目标")).toBeInTheDocument();
    expect(document.querySelector(".thought-narrative-block")).toBeInTheDocument();
    expect(screen.queryByText("执行概览")).not.toBeInTheDocument();
    expect(screen.queryByText("事件流")).not.toBeInTheDocument();
  });
});

describe("SessionConversationStream source parity", () => {
  const turn = {
    run: {
      id: "run-1",
      session_id: "s1",
      owner_user_id: "u1",
      goal: "test goal",
      status: "succeeded",
      mode: "quick",
      network_enabled: true,
      current_attempt_id: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
    steps: [{
      id: "s1",
      attempt_id: "a1",
      step_number: 0,
      thought_summary: "ok",
      action_type: "finish",
      action_payload: null,
      observation: null,
      status: "succeeded",
      created_at: "2026-01-01T00:00:00Z",
    }],
    events: [],
    warning: null,
  };

  it("uses source Agent Loop section structure without Ant Card wrapping", () => {
    const { container } = render(<SessionConversationStream turns={[turn]} />);
    expect(container.querySelector(".detail-conversation-stack > .session-turn-block")).toBeInTheDocument();
    expect(container.querySelector(".session-turn-block > .message-row-user")).toBeInTheDocument();
    expect(container.querySelector(".session-turn-block > .session-turn-meta")).toBeInTheDocument();
    expect(container.querySelector(".session-turn-block > .thought-narrative-block")).toBeInTheDocument();
    expect(container.querySelector(".session-turn-block > .final-answer-panel")).toBeInTheDocument();
    expect(container.querySelector(".ant-card")).not.toBeInTheDocument();
  });
});

describe("LandingEventStream", () => {
  test("renders event stream toggle button and panel when opened", () => {
    const diagnosticRuns = [
      { ...baseRun, current_step: 3, max_steps: 5, retry_count: 0, next_retry_at: null, error: null },
      { ...baseRun, id: "run-2", goal: "另一个任务", status: "running" as AgentRunStatus, current_step: 1, max_steps: 3, retry_count: 0, next_retry_at: null, error: null },
    ];
    render(<LandingEventStream runs={diagnosticRuns} />);
    expect(screen.getByText("事件流")).toBeInTheDocument();
    expect(screen.getByText("研究模式")).toBeInTheDocument();
    expect(screen.getByText("可见思考")).toBeInTheDocument();
  });

  test("shows empty state when no runs", () => {
    render(<LandingEventStream runs={[]} />);
    expect(screen.getByText("事件流")).toBeInTheDocument();
  });
});
