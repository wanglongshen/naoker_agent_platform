import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";

const { TestAgentSessionLoadError, mockLoadAgentSessionView, mockAgentApi, mockApi } = vi.hoisted(() => {
  class TestAgentSessionLoadError extends Error {
    scope: string;
    status?: number;
    code?: string;
    requestId?: string;
    constructor(scope: string, status?: number, code?: string, requestId?: string) {
      super(scope === "session" ? "会话不存在或无权访问" : "服务暂时不可用");
      this.name = "AgentSessionLoadError";
      this.scope = scope;
      this.status = status;
      this.code = code;
      this.requestId = requestId;
    }
  }

  return {
    TestAgentSessionLoadError,
    mockLoadAgentSessionView: vi.fn(),
    mockAgentApi: {
      createRun: vi.fn(),
      uploadAttachment: vi.fn(),
      updateSessionProject: vi.fn(),
    },
    mockApi: vi.fn(),
  };
});

vi.mock("@/lib/agent-session-view", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/agent-session-view")>();
  return {
    ...actual,
    loadAgentSessionView: mockLoadAgentSessionView,
    AgentSessionLoadError: TestAgentSessionLoadError,
  };
});

vi.mock("@/lib/agent-api", () => ({ agentApi: mockAgentApi }));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: mockApi };
});
vi.mock("next/navigation", () => ({
  useParams: () => ({ sessionId: "session-1" }),
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/lib/agent-session-store", () => ({ invalidateAgentSessions: vi.fn() }));

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  readyState: number = 0;
  close = vi.fn();
  private listeners: Map<string, EventListener[]> = new Map();

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: EventListener) {
    const existing = this.listeners.get(type) ?? [];
    existing.push(listener);
    this.listeners.set(type, existing);
  }

  dispatchEvent(type: string, data: string) {
    const event = new MessageEvent(type, { data });
    if (type === "message") this.onmessage?.(event as MessageEvent<string>);
    if (type === "open") this.onopen?.();
    if (type === "error") this.onerror?.();
    const listeners = this.listeners.get(type) ?? [];
    for (const listener of listeners) {
      listener(event);
    }
  }

  static reset() {
    MockEventSource.instances = [];
  }

  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
}

vi.stubGlobal("EventSource", MockEventSource);

const runningRun = {
  id: "run-1",
  session_id: "session-1",
  owner_user_id: "u1",
  goal: "test",
  status: "running",
  mode: "quick",
  network_enabled: true,
  current_attempt_id: null,
  result: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const failedRun = { ...runningRun, status: "failed" };

const session = {
  id: "session-1",
  title: "测试会话",
  owner_user_id: "u1",
  last_run_id: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const folders = [
  { id: "f1", name: "项目A", parent_folder_id: null, child_file_count: 0, children: [], created_at: "2026-01-01T00:00:00Z" },
  { id: "f2", name: "项目B", parent_folder_id: null, child_file_count: 0, children: [], created_at: "2026-01-01T00:00:00Z" },
  { id: "f-child", name: "子目录", parent_folder_id: "f1", child_file_count: 0, children: [], created_at: "2026-01-01T00:00:00Z" },
];

mockApi.mockResolvedValue(folders);

import SessionDetailPage from "./page";
import { mergeTurnsKeepingRicherAnswer } from "@/lib/agent-session-view";
import { clearSessionViewCache } from "@/lib/session-view-cache";

beforeEach(() => {
  clearSessionViewCache();
});

function Wrapper({ children }: { children: React.ReactNode }) {
  return <ConfigProvider>{children}</ConfigProvider>;
}

describe("Session page rendering", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    MockEventSource.reset();
  });

  it("renders session content without session title as heading", async () => {
    mockLoadAgentSessionView.mockResolvedValue({ session, turns: [], warnings: [] });
    render(<Wrapper><SessionDetailPage /></Wrapper>);
    expect(await screen.findByText("测试会话")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1, name: "测试会话" })).not.toBeInTheDocument();
  });
});

describe("Session project selector", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    MockEventSource.reset();
  });

  async function renderBound() {
    mockLoadAgentSessionView.mockResolvedValue({ session, turns: [], warnings: [] });
    const { container } = render(
      <Wrapper>
        <SessionDetailPage />
      </Wrapper>,
    );
    await screen.findByText("测试会话");
    return container;
  }

  async function openAndSelect(container: HTMLElement, optionLabel: string) {
    const user = userEvent.setup();
    await user.click(container.querySelector(".composer-project-capsule") as Element);
    await user.click(
      Array.from(container.querySelectorAll<HTMLElement>(".composer-project-menu-item")).find(
        (el) => (el.textContent || "").includes(optionLabel)
      ) as Element
    );
    return user;
  }

  it("renders the project selector with unbound placeholder when the session has no project", async () => {
    const container = await renderBound();
    const capsule = container.querySelector(".composer-project-capsule");
    expect(capsule?.textContent).toContain("未绑定项目");
    expect(mockApi).toHaveBeenCalledWith("/api/files/folders");
  });

  it("switches the session project and shows a success message", async () => {
    mockAgentApi.updateSessionProject.mockResolvedValue({ project_folder_id: "f1", project_name: "项目A" });
    const container = await renderBound();
    await openAndSelect(container, "项目A");

    expect(mockAgentApi.updateSessionProject).toHaveBeenCalledWith("session-1", "f1");
    expect(await screen.findByText(/已切换到项目「项目A」，文件操作仅限该项目/)).toBeInTheDocument();
    expect(container.querySelector(".composer-project-capsule")?.textContent).toContain("项目A");
    expect(screen.queryByText("子目录")).not.toBeInTheDocument();
  });

  it("unbinds the project via dropdown and shows an info message", async () => {
    mockAgentApi.updateSessionProject.mockResolvedValue({ project_folder_id: "f1", project_name: "项目A" });
    const container = await renderBound();
    const user = await openAndSelect(container, "项目A");
    await screen.findByText(/已切换到项目「项目A」/);

    await user.click(container.querySelector(".composer-project-capsule") as Element);
    mockAgentApi.updateSessionProject.mockResolvedValue({ project_folder_id: null, project_name: "" });
    await user.click(
      Array.from(container.querySelectorAll<HTMLElement>(".composer-project-menu-item")).find(
        (el) => (el.textContent || "").includes("解除绑定")
      ) as Element
    );

    expect(mockAgentApi.updateSessionProject).toHaveBeenLastCalledWith("session-1", null);
    expect(await screen.findByText("已解除项目绑定，文件操作为全局范围")).toBeInTheDocument();
  });

  it("shows an error message when switching the project fails", async () => {
    mockAgentApi.updateSessionProject.mockRejectedValue(new Error("切换项目失败"));
    const container = await renderBound();
    await openAndSelect(container, "项目A");

    expect(mockAgentApi.updateSessionProject).toHaveBeenCalledWith("session-1", "f1");
    expect(await screen.findByText("切换项目失败")).toBeInTheDocument();
  });
});

describe("Session page loading resilience", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    MockEventSource.reset();
  });

  it("renders available turns with a warning when one run diagnostics request fails", async () => {
    mockLoadAgentSessionView.mockResolvedValue({
      session,
      turns: [
        {
          run: {
            id: "run-1", session_id: "session-1", owner_user_id: "u1", goal: "test goal",
            status: "succeeded", mode: "quick", network_enabled: true, current_attempt_id: null,
            created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
          },
          steps: [],
          events: [],
          warning: { scope: "events" as const, sessionId: "session-1", runId: "run-1", message: "事件回放不可用" },
        },
      ],
      warnings: [{ scope: "events" as const, sessionId: "session-1", runId: "run-1", message: "事件回放不可用" }],
    });

    render(
      <Wrapper>
        <SessionDetailPage />
      </Wrapper>,
    );

    expect(await screen.findByText("测试会话")).toBeInTheDocument();
    expect(screen.queryByText("组织私有空间")).not.toBeInTheDocument();
    expect(screen.queryByText(/快速模式|专家模式|深度思考|智能搜索/)).not.toBeInTheDocument();
    expect(screen.getByText(/事件回放不可用/)).toBeInTheDocument();
  });

  it("shows a specific request error when the required Session request fails", async () => {
    mockLoadAgentSessionView.mockRejectedValue(new TestAgentSessionLoadError("session", 404, "RESOURCE_NOT_FOUND", "req-404"));

    render(
      <Wrapper>
        <SessionDetailPage />
      </Wrapper>,
    );

    expect(await screen.findByText("会话不存在或无权访问")).toBeInTheDocument();
  });

  it("shows step-specific warning when steps fail alone", async () => {
    mockLoadAgentSessionView.mockResolvedValue({
      session,
      turns: [{ run: failedRun, steps: [], events: [], warning: { scope: "steps" as const, sessionId: "session-1", runId: "run-1", message: "步骤数据暂时不可用" } }],
      warnings: [{ scope: "steps" as const, sessionId: "session-1", runId: "run-1", message: "步骤数据暂时不可用" }],
    });

    render(<Wrapper><SessionDetailPage /></Wrapper>);
    await screen.findByText("测试会话");
    expect(screen.getByText(/步骤数据暂时不可用/)).toBeInTheDocument();
  });

  it("shows events warning when events fail alone", async () => {
    mockLoadAgentSessionView.mockResolvedValue({
      session,
      turns: [{ run: failedRun, steps: [], events: [], warning: { scope: "events" as const, sessionId: "session-1", runId: "run-1", message: "事件回放暂时不可用" } }],
      warnings: [{ scope: "events" as const, sessionId: "session-1", runId: "run-1", message: "事件回放暂时不可用" }],
    });

    render(<Wrapper><SessionDetailPage /></Wrapper>);
    await screen.findByText("测试会话");
    expect(screen.getByText(/事件回放暂时不可用/)).toBeInTheDocument();
  });
});

describe("Session terminal state sync", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    MockEventSource.reset();
  });

  it("re-fetches session data when the last active run becomes terminal via SSE", async () => {
    mockLoadAgentSessionView
      .mockResolvedValueOnce({
        session: {
          id: "session-1",
          title: "test",
          owner_user_id: "u1",
          last_run_id: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
        turns: [{ run: runningRun, steps: [], events: [], warning: null }],
        warnings: [],
      })
      .mockResolvedValueOnce({
        session: {
          id: "session-1",
          title: "test",
          owner_user_id: "u1",
          last_run_id: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
        turns: [{ run: failedRun, steps: [], events: [], warning: null }],
        warnings: [],
      });

    render(
      <Wrapper>
        <SessionDetailPage />
      </Wrapper>,
    );

    await waitFor(() => expect(mockLoadAgentSessionView).toHaveBeenCalledTimes(1));

    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));

    const source = MockEventSource.instances[0];
    if (source) {
      act(() => {
        source.dispatchEvent("open", "");
      });
      act(() => {
        source.dispatchEvent(
          "run_failed",
          JSON.stringify({
            seq: 5,
            type: "run_failed",
            run_id: "run-1",
            timestamp: "2026-01-01T00:00:05Z",
            payload: { error: "worker_unhandled_error" },
          }),
        );
      });
    }

    await waitFor(() => expect(mockLoadAgentSessionView).toHaveBeenCalledTimes(2));
  });

  it("keeps the conversation mounted without a page spinner while terminal reconciliation is pending", async () => {
    let resolveReconciliation: ((view: { session: typeof session; turns: []; warnings: [] }) => void) | undefined;
    mockLoadAgentSessionView
      .mockResolvedValueOnce({
        session,
        turns: [{ run: runningRun, steps: [], events: [], warning: null }],
        warnings: [],
      })
      .mockImplementationOnce(() => new Promise((resolve) => {
        resolveReconciliation = resolve;
      }));
    render(<Wrapper><SessionDetailPage /></Wrapper>);
    expect(await screen.findByText("测试会话")).toBeInTheDocument();

    act(() => {
      const source = MockEventSource.instances[0];
      source.dispatchEvent("answer_completed", JSON.stringify({ seq: 1, type: "answer_completed", run_id: "run-1", timestamp: "2026-01-01T00:00:01Z", payload: { text: "完整答案" } }));
      source.dispatchEvent("run_succeeded", JSON.stringify({ seq: 2, type: "run_succeeded", run_id: "run-1", timestamp: "2026-01-01T00:00:02Z", payload: {} }));
    });

    expect(screen.getByText("测试会话")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(mockLoadAgentSessionView).toHaveBeenCalledTimes(2);

    await act(async () => {
      resolveReconciliation?.({ session, turns: [], warnings: [] });
    });
  });

  it("keeps a richer local final answer when reconciliation returns an older snapshot", () => {
    const current = [{ run: { ...runningRun, result: { final_answer: "完整本地答案" } }, steps: [{ id: "step" }], events: [{ id: "event" }], warning: null }];
    const refreshed = [{ run: { ...runningRun, status: "succeeded", result: null }, steps: [], events: [], warning: null }];

    const merged = mergeTurnsKeepingRicherAnswer(current as any, refreshed as any);

    expect(merged[0].run.result?.final_answer).toBe("完整本地答案");
    expect(merged[0].steps).toEqual(current[0].steps);
    expect(merged[0].events).toEqual(current[0].events);
  });

  it("keeps rich local turns when reconciliation omits every turn", () => {
    const current = [{
      run: { ...runningRun, result: { final_answer: "本地流式完整答案" } },
      steps: [{ id: "local-step" }],
      events: [{ id: "local-event" }],
      warning: { scope: "events", sessionId: "session-1", runId: "run-1", message: "本地诊断" },
    }];

    const merged = mergeTurnsKeepingRicherAnswer(current as any, []);

    expect(merged).toHaveLength(1);
    expect(merged[0].run.result?.final_answer).toBe("本地流式完整答案");
    expect(merged[0].steps).toEqual(current[0].steps);
    expect(merged[0].events).toEqual(current[0].events);
    expect(merged[0].warning).toEqual(current[0].warning);
  });

  it("keeps omitted local turns after refreshed turns in a partial reconciliation", () => {
    const current = [
      { run: { ...runningRun, id: "run-local-1", result: { final_answer: "本地答案" } }, steps: [{ id: "step-1" }], events: [{ id: "event-1" }], warning: null },
      { run: { ...runningRun, id: "run-local-2" }, steps: [], events: [], warning: null },
    ];
    const refreshed = [{ run: { ...runningRun, id: "run-refreshed" }, steps: [], events: [], warning: null }];

    const merged = mergeTurnsKeepingRicherAnswer(current as any, refreshed as any);

    expect(merged.map((turn) => turn.run.id)).toEqual(["run-refreshed", "run-local-1", "run-local-2"]);
    expect(merged[1].run.result?.final_answer).toBe("本地答案");
    expect(merged[1].steps).toEqual(current[0].steps);
    expect(merged[1].events).toEqual(current[0].events);
  });

  it("retains the answer and shows a scoped warning when terminal reconciliation fails", async () => {
    let frameNow = 0;
    const frameCallbacks: Array<FrameRequestCallback> = [];
    const rAF = vi.fn((cb: FrameRequestCallback) => {
      frameCallbacks.push(cb);
      return frameCallbacks.length;
    });
    const cAF = vi.fn();
    vi.stubGlobal("requestAnimationFrame", rAF);
    vi.stubGlobal("cancelAnimationFrame", cAF);
    try {
    mockLoadAgentSessionView
      .mockResolvedValueOnce({ session, turns: [{ run: runningRun, steps: [], events: [], warning: null }], warnings: [] })
      .mockRejectedValueOnce(new Error("offline"));
    render(<Wrapper><SessionDetailPage /></Wrapper>);
    await screen.findByText("测试会话");

    act(() => {
      const source = MockEventSource.instances[0];
      source.dispatchEvent("answer_completed", JSON.stringify({ seq: 1, type: "answer_completed", run_id: "run-1", timestamp: "2026-01-01T00:00:01Z", payload: { text: "完整答案" } }));
      source.dispatchEvent("run_succeeded", JSON.stringify({ seq: 2, type: "run_succeeded", run_id: "run-1", timestamp: "2026-01-01T00:00:02Z", payload: {} }));
    });

    while (frameCallbacks.length > 0) {
      await act(async () => {
        const pending = [...frameCallbacks];
        frameCallbacks.length = 0;
        for (const cb of pending) {
          frameNow += 20;
          cb(frameNow);
        }
      });
    }

    expect(screen.getByText("完整答案")).toBeInTheDocument();
    expect(await screen.findByText("执行状态刷新失败，当前回答已保留。")).toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
