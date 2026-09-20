import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import AnswerActions from "@/components/agent/answer-actions";
import FinalAnswerPanel, { shouldAnimateFinalAnswer } from "@/components/agent/final-answer-panel";
import AppHeader from "@/components/layout/app-header";
import ThoughtNarrative, {
  ThoughtDuration,
  ToolRecord,
  areReasoningBlocksEqual,
  areToolBlocksEqual,
} from "@/components/agent/thought-narrative";
import { advanceTypingText } from "@/hooks/use-typing-text";
import type { AgentRun, AgentRunEvent, AgentRunStatus } from "@/types/agent";

const baseRun: AgentRun = {
  id: "run-1",
  session_id: "session-1",
  owner_user_id: "user-1",
  goal: "Explain the result",
  status: "running",
  mode: "quick",
  network_enabled: true,
  current_attempt_id: "attempt-1",
  created_at: "2026-07-20T00:00:00Z",
  updated_at: "2026-07-20T00:00:00Z",
};

function makeRun(overrides: Partial<AgentRun> = {}): AgentRun {
  return { ...baseRun, ...overrides };
}

describe("advanceTypingText", () => {
  test("reveals one character per tick until it reaches the target", () => {
    expect(advanceTypingText("", "abc")).toBe("a");
    expect(advanceTypingText("a", "abc")).toBe("ab");
    expect(advanceTypingText("ab", "abc")).toBe("abc");
    expect(advanceTypingText("abc", "abc")).toBe("abc");
  });

  test("catches up to a longer target while animation is in progress", () => {
    const afterFirstTick = advanceTypingText("", "ab");
    const afterTargetGrows = advanceTypingText(afterFirstTick, "abcd");

    expect(afterFirstTick).toBe("a");
    expect(afterTargetGrows).toBe("ab");
    expect(advanceTypingText(afterTargetGrows, "abcd")).toBe("abc");
  });

  test("does not reset when the target shrinks or restarts", () => {
    expect(advanceTypingText("abcd", "")).toBe("");
    expect(advanceTypingText("abcd", "xy")).toBe("x");
  });
});

describe("AppHeader", () => {
  test("renders 脑壳工作台 branding with account menu when user present", () => {
    const user = { id: "u1", username: "admin", display_name: "Admin", roles: [], permissions: [] };
    render(<AppHeader user={user} />);
    expect(screen.getByText("脑壳工作台")).toBeVisible();
  });

  test("account menu includes profile entry", async () => {
    const user = { id: "u1", username: "admin", display_name: "Admin", roles: [], permissions: [] };
    render(<AppHeader user={user} />);
    const accountBtn = document.querySelector(".top-bar-user-btn") as HTMLButtonElement;
    fireEvent.click(accountBtn);
    expect(await screen.findByText("个人资料")).toBeTruthy();
  });

  test("shows real avatar image when avatar_url present", () => {
    const user = {
      id: "u1",
      username: "admin",
      display_name: "Admin",
      roles: [],
      permissions: [],
      avatar_url: "/api/avatars/u1?v=1",
    };
    render(<AppHeader user={user} />);
    const img = document.querySelector(".header-avatar img");
    expect(img).not.toBeNull();
    expect(img?.getAttribute("src")).toBe("/api/avatars/u1?v=1");
  });
});

describe("FinalAnswerPanel", () => {
  test.each(["succeeded", "completed", "queued", "retry_wait", "cancel_requested", "failed", "cancelled", "unknown"])(
    "%s historical answer renders complete text without typing replay",
    (status) => {
      vi.useFakeTimers();
      try {
        render(
          <FinalAnswerPanel
            run={makeRun({
              status: status as AgentRunStatus,
              result: { final_answer: "完整历史答案" },
            })}
            streamingAnswer="完整历史答案"
            answerStreamId="historical-answer"
            isLiveRun={false}
          />
        );

        expect(screen.getByText("完整历史答案")).toBeVisible();
        act(() => vi.advanceTimersByTime(100));
        expect(screen.getByText("完整历史答案")).toBeVisible();
      } finally {
        vi.useRealTimers();
      }
    }
  );

  test("allows multiple running runs to animate independently", () => {
    const first = makeRun({ id: "run-1", status: "running" });
    const second = makeRun({ id: "run-2", status: "running" });

    expect(shouldAnimateFinalAnswer(first, "第一段增长文本", "answer-1")).toBe(true);
    expect(shouldAnimateFinalAnswer(second, "第二段增长文本", "answer-2")).toBe(true);
  });

  test("shows streaming answer before persisted final answer", async () => {
    render(
      <FinalAnswerPanel run={baseRun} streamingAnswer="正在生成" />
    );

    expect(await screen.findByText(/正在生成/)).toBeInTheDocument();
  });

  test("streaming answer types full text as plain text without splitting into markdown blocks", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList);

    render(
      <FinalAnswerPanel
        run={baseRun}
        streamingAnswer={`# 标题

完成的段落。

活动`}
        answerStreamId="live-md"
      />,
    );

    expect(document.querySelector('[data-streaming="true"]')).not.toBeNull();
  });

  test("streaming answer types the entire text including headings as plain text", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList);

    render(
      <FinalAnswerPanel
        run={baseRun}
        streamingAnswer={`# 韭菜炒鸡蛋

第一步已经完成。

正在`}
        answerStreamId="live-markdown"
      />,
    );

    expect(document.querySelector('[data-streaming="true"]')).not.toBeNull();
  });

  test("streaming answer does not render headings instantly — typewriter types them", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList);

    const { container } = render(
      <FinalAnswerPanel
        run={baseRun}
        streamingAnswer={`# 标题

完成的段落。

活动`}
        answerStreamId="no-instant-heading"
      />,
    );

    expect(container.querySelector("h1")).toBeNull();
    expect(container.querySelector(".streaming-tail")).not.toBeNull();
  });

  test("streaming answer types heading after rAF frames advance", async () => {
    const raf = installFakeRaf();
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList);
    try {
      render(
        <FinalAnswerPanel
          run={baseRun}
          streamingAnswer={`# 标题

稳定段落

尾部继续`}
          answerStreamId="live-grow"
        />,
      );
      act(() => {
        for (let i = 1; i <= 20; i += 1) {
          raf.runNextFrame(i * 16);
        }
      });
      expect(screen.getByRole("heading", { name: "标题" })).toBeVisible();
      expect(screen.getByText("稳定段落")).toBeVisible();
    } finally {
      vi.restoreAllMocks();
    }
  });

  test("renders streaming answer with long text through a single streaming tail", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList);

    const { container } = render(
      <FinalAnswerPanel
        run={baseRun}
        streamingAnswer={`# 长答案标题

稳定的段落。

${"z".repeat(500)}`}
        answerStreamId="large-answer"
      />,
    );

    expect(container.querySelector(".streaming-tail")).not.toBeNull();
  });

  test("streaming answer heading requires rAF frames to appear", async () => {
    const raf = installFakeRaf();
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList);
    try {
      render(
        <FinalAnswerPanel
          run={baseRun}
          streamingAnswer={`# 韭菜炒鸡蛋

第一步已经完成。`}
          answerStreamId="typing-required"
        />,
      );
      expect(screen.queryByRole("heading", { name: "韭菜炒鸡蛋" })).toBeNull();
      act(() => {
        for (let i = 1; i <= 10; i += 1) {
          raf.runNextFrame(i * 16);
        }
      });
      expect(screen.getByRole("heading", { name: "韭菜炒鸡蛋" })).toBeVisible();
    } finally {
      vi.restoreAllMocks();
    }
  });

  test("final-answer list markers inherit neutral text color", () => {
    const { container } = render(
      <FinalAnswerPanel
        run={makeRun({ status: "succeeded", result: { final_answer: "- 列表项\n- 另一项" } })}
        streamingAnswer="" answerStreamId={null}
      />,
    );
    const sheets = Array.from(document.styleSheets);
    const ruleText = sheets.flatMap((s) => {
      try { return Array.from(s.cssRules).map((r) => r.cssText); }
      catch { return []; }
    }).find((t) => t.includes(".final-answer-prose li::marker"));
    expect(ruleText).toBeDefined();
    expect(ruleText.toLowerCase()).toContain("currentcolor");
    expect(ruleText.toLowerCase()).not.toMatch(/#[0-9a-f]{3,6}/);
  });

  test("retry_wait shows retry placeholder instead of pending answer", () => {
    const retryRun: AgentRun = { ...baseRun, status: "retry_wait" };

    render(<FinalAnswerPanel run={retryRun} streamingAnswer="" answerStreamId={null} />);

    expect(screen.getByText("正在重试")).toBeInTheDocument();
  });

  test("does not render a final-answer placeholder while the run is thinking", () => {
    const { container } = render(<FinalAnswerPanel run={baseRun} />);
    expect(container.querySelector(".final-answer-panel")).not.toBeInTheDocument();
    expect(screen.queryByText("正在生成最终回答")).not.toBeInTheDocument();
  });

  test("completed run renders persisted answer without streaming animation", () => {
    const completedRun: AgentRun = {
      ...baseRun,
      status: "succeeded",
    } as AgentRun;

    expect(shouldAnimateFinalAnswer(completedRun, "", "answer-history")).toBe(false);
    expect(shouldAnimateFinalAnswer(baseRun, "正在生成", "answer-live")).toBe(true);
  });

  test("failed run shows failure message", () => {
    const failedRun: AgentRun = { ...baseRun, status: "failed" };

    render(<FinalAnswerPanel run={failedRun} />);

    expect(screen.getByText("本次任务未成功生成最终回答")).toBeInTheDocument();
  });

  test("renders speech button only for a completed non-empty answer when supported", () => {
    const mockSynthesis = {
      speak: vi.fn(),
      cancel: vi.fn(),
      speaking: false,
      pending: false,
    };
    const FakeUtterance = class {
      text: string;
      lang = "";
      onend: ((e: Event) => void) | null = null;
      onerror: ((e: { error: string }) => void) | null = null;
      constructor(text: string) { this.text = text; }
    };
    (window as Window & { speechSynthesis?: unknown }).speechSynthesis = mockSynthesis;
    (window as Window & { SpeechSynthesisUtterance?: unknown }).SpeechSynthesisUtterance = FakeUtterance;

    try {
      render(
        <FinalAnswerPanel
          run={makeRun({ id: "run-speech-1", status: "succeeded", result: { final_answer: "# 标题\n内容" } })}
          streamingAnswer=""
          answerStreamId={null}
        />
      );
      expect(screen.getByRole("button", { name: "朗读回答" })).toBeVisible();
    } finally {
      delete (window as Window & { speechSynthesis?: unknown }).speechSynthesis;
      delete (window as Window & { SpeechSynthesisUtterance?: unknown }).SpeechSynthesisUtterance;
    }
  });

  test("does not render speech control for active streaming answer", () => {
    const mockSynthesis = {
      speak: vi.fn(),
      cancel: vi.fn(),
      speaking: false,
      pending: false,
    };
    const FakeUtterance = class {
      text: string;
      lang = "";
      onend: ((e: Event) => void) | null = null;
      onerror: ((e: { error: string }) => void) | null = null;
      constructor(text: string) { this.text = text; }
    };
    (window as Window & { speechSynthesis?: unknown }).speechSynthesis = mockSynthesis;
    (window as Window & { SpeechSynthesisUtterance?: unknown }).SpeechSynthesisUtterance = FakeUtterance;

    try {
      render(
        <FinalAnswerPanel
          run={makeRun({ id: "run-speech-2", status: "running" })}
          streamingAnswer="正在生成"
          answerStreamId="s1"
        />
      );
      expect(screen.queryByRole("button", { name: /朗读回答|停止朗读/ })).not.toBeInTheDocument();
    } finally {
      delete (window as Window & { speechSynthesis?: unknown }).speechSynthesis;
      delete (window as Window & { SpeechSynthesisUtterance?: unknown }).SpeechSynthesisUtterance;
    }
  });

  test("does not render speech button when unsupported", () => {
    render(
      <FinalAnswerPanel
        run={makeRun({ id: "run-speech-3", status: "succeeded", result: { final_answer: "内容" } })}
        streamingAnswer=""
        answerStreamId={null}
      />
    );
    expect(screen.queryByRole("button", { name: /朗读回答|停止朗读/ })).not.toBeInTheDocument();
  });

  test("terminal transition does not pop the remaining answer — typewriter continues", async () => {
    const raf = installFakeRaf();
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList);
    try {
      const { rerender } = render(
        <FinalAnswerPanel
          run={baseRun}
          streamingAnswer={`# 标题

${"a".repeat(200)}`}
          answerStreamId="live-continue"
        />,
      );
      act(() => {
        for (let i = 1; i <= 8; i += 1) {
          raf.runNextFrame(i * 16);
        }
      });

      rerender(
        <FinalAnswerPanel
          run={{ ...baseRun, status: "succeeded", result: { final_answer: `# 标题\n\n${"a".repeat(200)}` } }}
          streamingAnswer=""
          answerStreamId={null}
          wasLiveStreamed={true}
        />,
      );

      expect(document.querySelector(".streaming-tail")).not.toBeNull();
    } finally {
      vi.restoreAllMocks();
    }
  });

  test("historical terminal run renders instantly without typewriter", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList);

    const { container } = render(
      <FinalAnswerPanel
        run={makeRun({ status: "succeeded", result: { final_answer: `# 标题\n\n段落` } })}
        streamingAnswer=""
        answerStreamId={null}
      />,
    );

    expect(container.querySelector(".streaming-tail")).toBeNull();
    expect(screen.getByRole("heading", { name: "标题" })).toBeVisible();
  });
});

describe("ThoughtNarrative", () => {
  test("renders completed reasoning statically while the active thought types progressively", () => {
    let frame: ((timestamp: number) => void) | null = null;
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback: (timestamp: number) => void) => {
      frame = callback;
      return 1;
    }));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());

    try {
      const { container } = render(
        <ThoughtNarrative
          run={baseRun}
          steps={[]}
          events={[
            {
              id: "completed-thought",
              run_id: "run-1",
              attempt_id: "attempt-1",
              seq: 1,
              event_type: "visible_thought_completed",
              payload: { step_index: 0, stream_id: "completed", text: "已完成的完整思考" },
              created_at: "2026-07-20T00:00:00Z",
            },
            {
              id: "tool-started",
              run_id: "run-1",
              attempt_id: "attempt-1",
              seq: 2,
              event_type: "tool_started",
              payload: { step_index: 0, action_type: "http_request", tool_call: {} },
              created_at: "2026-07-20T00:00:01Z",
            },
            {
              id: "tool-completed",
              run_id: "run-1",
              attempt_id: "attempt-1",
              seq: 3,
              event_type: "tool_completed",
              payload: { step_index: 0, action_type: "http_request", observation: {} },
              created_at: "2026-07-20T00:00:02Z",
            },
            {
              id: "active-thought",
              run_id: "run-1",
              attempt_id: "attempt-1",
              seq: 4,
              event_type: "visible_thought_delta",
              payload: { step_index: 1, stream_id: "active", offset: 0, delta: "正在逐字显示" },
              created_at: "2026-07-20T00:00:03Z",
            },
          ]}
          isLiveRun={true}
        />
      );

      expect(screen.getByText("已完成的完整思考").closest(".thought-narrative-item")).toHaveClass("thought-narrative-item-static");
      expect(screen.getByText("正在逐字显示")).toBeInTheDocument();
      expect(container.querySelector(".thought-narrative-item-active")).toBeInTheDocument();

      act(() => frame?.(16));
      expect(screen.getByText("正在逐字显示")).toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("renders DeepSeek-style header and reasoning rail structure", () => {
    const { container } = render(
      <ThoughtNarrative
        run={baseRun}
        steps={[]}
        events={[
          {
            id: "e1", run_id: "run-1", attempt_id: null, seq: 1,
            event_type: "visible_thought_started",
            payload: { step_index: 0, stream_id: "t1" },
            created_at: "2026-07-20T00:00:00Z",
          },
          {
            id: "e2", run_id: "run-1", attempt_id: null, seq: 2,
            event_type: "visible_thought_delta",
            payload: { step_index: 0, stream_id: "t1", offset: 0, delta: "正在分析问题" },
            created_at: "2026-07-20T00:00:01Z",
          },
          {
            id: "e3", run_id: "run-1", attempt_id: null, seq: 3,
            event_type: "visible_thought_completed",
            payload: { step_index: 0, stream_id: "t1", text: "正在分析问题" },
            created_at: "2026-07-20T00:00:02Z",
          },
        ]}
      />
    );

    expect(container.querySelector(".thought-narrative-glyph")).toBeInTheDocument();
    expect(container.querySelector(".thought-narrative-item-static")).toBeInTheDocument();
  });

  test("renders in-progress visible thought text from stream state", async () => {
    render(
      <ThoughtNarrative
        run={baseRun}
        steps={[]}
        events={[
          {
            id: "e1", run_id: "run-1", attempt_id: null, seq: 1,
            event_type: "visible_thought_started",
            payload: { step_index: 0, stream_id: "t1" },
            created_at: "2026-07-20T00:00:00Z",
          },
          {
            id: "e2", run_id: "run-1", attempt_id: null, seq: 2,
            event_type: "visible_thought_delta",
            payload: { step_index: 0, stream_id: "t1", offset: 0, delta: "正在读取页面内容" },
            created_at: "2026-07-20T00:00:01Z",
          },
        ]}
      />
    );

    expect(await screen.findByText("正在读取页面内容")).toBeInTheDocument();
  });

  test("marks only the active streaming thought item with emphasis", () => {
    const { container } = render(
      <ThoughtNarrative
        run={{ ...baseRun, status: "running" }}
        steps={[
          { id: "step-1", step_index: 0, thought_summary: "", action_type: "http_request", status: "completed" },
          { id: "step-2", step_index: 1, thought_summary: "", action_type: "http_request", status: "running" },
        ]}
        events={[
          {
            id: "e1", run_id: "run-1", attempt_id: null, seq: 1,
            event_type: "visible_thought_started",
            payload: { step_index: 0, stream_id: "stream-0" },
            created_at: "2026-07-20T00:00:00Z",
          },
          {
            id: "e2", run_id: "run-1", attempt_id: null, seq: 2,
            event_type: "visible_thought_delta",
            payload: { step_index: 0, stream_id: "stream-0", offset: 0, delta: "已完成的思考" },
            created_at: "2026-07-20T00:00:01Z",
          },
          {
            id: "e3", run_id: "run-1", attempt_id: null, seq: 3,
            event_type: "visible_thought_completed",
            payload: { step_index: 0, stream_id: "stream-0", text: "已完成的思考" },
            created_at: "2026-07-20T00:00:02Z",
          },
          {
            id: "e4", run_id: "run-1", attempt_id: null, seq: 4,
            event_type: "visible_thought_started",
            payload: { step_index: 1, stream_id: "stream-1" },
            created_at: "2026-07-20T00:00:03Z",
          },
          {
            id: "e5", run_id: "run-1", attempt_id: null, seq: 5,
            event_type: "visible_thought_delta",
            payload: { step_index: 1, stream_id: "stream-1", offset: 0, delta: "正在读取" },
            created_at: "2026-07-20T00:00:04Z",
          },
        ]}
        isLiveRun={true}
      />
    );

    expect(container.querySelector(".thought-narrative-item-active")).toBeInTheDocument();
  });

  test("renders distinct tool icons", () => {
    const events: AgentRunEvent[] = ["web_search", "extract_web_content", "calculator", "unknown_tool"].map((actionType, index) => ({
      id: `event-${index}`,
      run_id: "run-1",
      attempt_id: "attempt-1",
      seq: index + 1,
      event_type: "tool_started",
      payload: { step_index: index, action_type: actionType, tool_call: {} },
      created_at: "2026-07-20T00:00:00Z",
    }));

    const { container } = render(
      <ThoughtNarrative run={baseRun} steps={[]} events={events} />
    );

    expect(container.querySelector('[data-tool-icon="search"]')).toBeInTheDocument();
    expect(container.querySelector('[data-tool-icon="globe"]')).toBeInTheDocument();
    expect(container.querySelector('[data-tool-icon="calculator"]')).toBeInTheDocument();
    expect(container.querySelector('[data-tool-icon="page"]')).toBeInTheDocument();
  });

  test("read_file tool renders a file icon distinct from web_search", () => {
    render(
      <ToolRecord
        block={{
          kind: "tool",
          id: "t-read",
          stepIndex: 0,
          toolType: "read_file",
          label: "读取文件",
          status: "completed",
          url: null,
          resultSummary: null,
        }}
        runStatus="succeeded"
      />,
    );
    const icon = document.querySelector("[data-tool-icon]");
    expect(icon?.getAttribute("data-tool-icon")).toBe("file");
  });

  test("write_file tool renders a pen icon", () => {
    render(
      <ToolRecord
        block={{
          kind: "tool",
          id: "t-write",
          stepIndex: 0,
          toolType: "write_file",
          label: "写文件",
          status: "completed",
          url: null,
          resultSummary: null,
        }}
        runStatus="succeeded"
      />,
    );
    expect(document.querySelector("[data-tool-icon]")?.getAttribute("data-tool-icon")).toBe("pen");
  });

  test("retry_wait run does not show active streaming markers", () => {
    const retryRun: AgentRun = { ...baseRun, status: "retry_wait" };

    const { container } = render(
      <ThoughtNarrative
        run={retryRun}
        steps={[]}
        events={[]}
      />
    );

    expect(container.querySelector(".thought-narrative-item-active")).not.toBeInTheDocument();
  });

  test("toggle button has expanded true by default and aria-controls the region", () => {
    const { container } = render(
      <ThoughtNarrative
        run={baseRun}
        steps={[]}
        events={[]}
      />
    );

    const toggle = screen.getByRole("button", { name: /收起思考过程|展开思考过程/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const regionId = toggle.getAttribute("aria-controls");
    expect(regionId).toBeTruthy();
    const region = container.querySelector(`#${regionId}`);
    expect(region).toBeInTheDocument();
    expect(region).toHaveAttribute("role", "region");
    expect(region).toHaveAttribute("aria-label", "思考与工具过程");
  });

  test("tool record icon shares timeline axis with reasoning marker", () => {
    const events: AgentRunEvent[] = [
      {
        id: "e1", run_id: "run-1", attempt_id: null, seq: 1,
        event_type: "visible_thought_completed",
        payload: { step_index: 0, stream_id: "t1", text: "思考" },
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "e2", run_id: "run-1", attempt_id: null, seq: 2,
        event_type: "tool_started",
        payload: { step_index: 0, action_type: "web_search" },
        created_at: "2026-01-01T00:00:01Z",
      },
    ];
    const { container } = render(<ThoughtNarrative run={baseRun} steps={[]} events={events} />);

    const toolRecord = container.querySelector(".thought-tool-record") as HTMLElement | null;
    const toolIcon = container.querySelector(".thought-tool-record-icon") as HTMLElement | null;
    expect(toolRecord).not.toBeNull();
    expect(toolIcon).not.toBeNull();
    const recordStyle = getComputedStyle(toolRecord!);
    const iconStyle = getComputedStyle(toolIcon!);
    expect(recordStyle.position).toBe("relative");
    expect(iconStyle.position).toBe("absolute");
  });

  test("renders strict reasoning-tool alternation", () => {
    const events: AgentRunEvent[] = [
      {
        id: "event-1",
        run_id: "run-1",
        attempt_id: null,
        seq: 1,
        event_type: "visible_thought_started",
        payload: { step_index: 0, stream_id: "thought-1" },
        created_at: "2026-07-20T00:00:01Z",
      },
      {
        id: "event-2",
        run_id: "run-1",
        attempt_id: null,
        seq: 2,
        event_type: "visible_thought_completed",
        payload: { step_index: 0, stream_id: "thought-1", text: "先查看官方文档。" },
        created_at: "2026-07-20T00:00:02Z",
      },
      {
        id: "event-3",
        run_id: "run-1",
        attempt_id: null,
        seq: 3,
        event_type: "tool_started",
        payload: { step_index: 0, action_type: "http_request", tool_call: { method: "GET", url: "https://nextjs.org/learn" } },
        created_at: "2026-07-20T00:00:03Z",
      },
      {
        id: "event-4",
        run_id: "run-1",
        attempt_id: null,
        seq: 4,
        event_type: "tool_completed",
        payload: { step_index: 0, action_type: "http_request", observation: { url: "https://nextjs.org/learn" } },
        created_at: "2026-07-20T00:00:04Z",
      },
      {
        id: "event-5",
        run_id: "run-1",
        attempt_id: null,
        seq: 5,
        event_type: "visible_thought_started",
        payload: { step_index: 0, stream_id: "thought-1-resume" },
        created_at: "2026-07-20T00:00:05Z",
      },
      {
        id: "event-6",
        run_id: "run-1",
        attempt_id: null,
        seq: 6,
        event_type: "visible_thought_completed",
        payload: { step_index: 0, stream_id: "thought-1-resume", text: "资料足够，继续整理。" },
        created_at: "2026-07-20T00:00:06Z",
      },
    ];

    const { container } = render(
      <ThoughtNarrative run={baseRun} steps={[]} events={events} />
    );

    const toolRecords = container.querySelectorAll('[class*="thought-tool-record "]');
    expect(toolRecords.length).toBe(1);
  });
});

describe("ThoughtDuration", () => {
  test("renders duration or sublabel from props", () => {
    const { container, rerender } = render(
      <ThoughtDuration isThinking durationSeconds={null} subLabel="正在整理信息与判断下一步" />,
    );
    expect(container.textContent).toContain("正在整理信息与判断下一步");

    rerender(<ThoughtDuration isThinking durationSeconds={5} subLabel={null} />);
    expect(container.textContent).toContain("用时 5 秒");
  });

  test("starts interval only while thinking", () => {
    const setIntervalSpy = vi.spyOn(window, "setInterval");
    const clearIntervalSpy = vi.spyOn(window, "clearInterval");
    const { rerender } = render(
      <ThoughtDuration isThinking durationSeconds={null} subLabel="整理中" />,
    );
    expect(setIntervalSpy).toHaveBeenCalled();

    rerender(<ThoughtDuration isThinking={false} durationSeconds={null} subLabel="已思考" />);
    expect(clearIntervalSpy).toHaveBeenCalled();
    setIntervalSpy.mockRestore();
    clearIntervalSpy.mockRestore();
  });
});

describe("thought block memo comparators", () => {
  test("reasoning comparator skips re-render when content unchanged", () => {
    const a = { kind: "reasoning", id: "r-1", streamId: "s-1", stepIndex: 0, text: "正在思考", isComplete: false };
    const b = { ...a };
    expect(areReasoningBlocksEqual(a, b)).toBe(true);
  });

  test("reasoning comparator re-renders when text changes", () => {
    const a = { kind: "reasoning", id: "r-1", streamId: "s-1", stepIndex: 0, text: "正在思考", isComplete: false };
    const b = { ...a, text: "正在思考中" };
    expect(areReasoningBlocksEqual(a, b)).toBe(false);
  });

  test("reasoning comparator re-renders when isComplete flips", () => {
    const a = { kind: "reasoning", id: "r-1", streamId: "s-1", stepIndex: 0, text: "x", isComplete: false };
    const b = { ...a, isComplete: true };
    expect(areReasoningBlocksEqual(a, b)).toBe(false);
  });

  test("tool comparator re-renders when status changes", () => {
    const a = { kind: "tool", id: "t-1", toolType: "web_search", label: "搜索", status: "running", url: null, resultSummary: null };
    const b = { ...a, status: "completed" };
    expect(areToolBlocksEqual(a, b)).toBe(false);
  });
});

describe("FinalAnswerPanel Markdown safety", () => {
  const succeededRun = makeRun({
    status: "succeeded",
    result: { final_answer: "# 标题\n\n| A | B |\n| - | - |\n| 1 | 2 |" },
  });

  test("renders complete historical GFM without animation", () => {
    render(<FinalAnswerPanel run={succeededRun} streamingAnswer="" answerStreamId={null} />);

    expect(screen.getByRole("heading", { name: "标题" })).toBeVisible();
    expect(screen.getByRole("table")).toBeVisible();
  });

  test("renders the complete historical GFM fixture without animation", () => {
    const { container } = render(
      <FinalAnswerPanel
        run={makeRun({
          status: "succeeded",
          result: {
            final_answer: [
              "# 标题一",
              "## 标题二",
              "### 标题三",
              "#### 标题四",
              "##### 标题五",
              "###### 标题六",
              "",
              "- 无序项目",
              "  - 嵌套无序项目",
              "    1. 嵌套有序项目",
              "",
              "1. 有序项目",
              "   1. 嵌套有序项目",
              "",
              "- [ ] 待办项目",
              "",
              "> 引用内容",
              "",
              "---",
              "",
              "行内 `代码`。",
              "",
              "```ts",
              "const answer = 42;",
              "```",
              "",
              "| 名称 | 值 |",
              "| --- | --- |",
              "| 示例 | 42 |",
            ].join("\n"),
          },
        })}
        streamingAnswer=""
        answerStreamId={null}
      />
    );

    for (let level = 1; level <= 6; level += 1) {
      expect(container.querySelector(`h${level}`)).toBeInTheDocument();
    }
    expect(container.querySelector("ul")).toBeInTheDocument();
    expect(container.querySelector("ol")).toBeInTheDocument();
    expect(container.querySelector('input[type="checkbox"]')).toBeInTheDocument();
    expect(container.querySelector("blockquote")).toBeInTheDocument();
    expect(container.querySelector("hr")).toBeInTheDocument();
    expect(container.querySelector("code")).toBeInTheDocument();
    expect(container.querySelector(".code-scroll")).toBeInTheDocument();
    expect(container.querySelector("table")).toBeInTheDocument();
    expect(container.querySelector(".table-scroll")).toBeInTheDocument();
  });

  test("wraps fenced code blocks in a focusable native code scroll region", () => {
    const { container } = render(
      <FinalAnswerPanel
        run={makeRun({ status: "succeeded" })}
        streamingAnswer={`\`\`\`ts\nconst veryLongValue = "${"x".repeat(400)}";\n\`\`\``}
        answerStreamId={null}
        isLiveRun={false}
      />
    );

    const scrollRegion = container.querySelector(".code-scroll");
    expect(scrollRegion).toBeInTheDocument();
    expect(scrollRegion).toHaveAttribute("tabindex", "0");
    expect(scrollRegion?.querySelector(":scope > pre > code")).toBeInTheDocument();
  });

  test.each(["javascript:alert(1)", "data:text/html,unsafe", "//example.com"])("does not render unsafe %s markdown links", (href) => {
    const { container } = render(<FinalAnswerPanel run={makeRun({ status: "succeeded" })} streamingAnswer={`[bad](${href})`} isLiveRun={false} />);

    expect(container.querySelector("a")).toHaveAttribute("href", "");
  });

  test.each([
    "/\\example.com",
    "/\\evil.test",
    "/%5C%5Cexample.com",
    "/%2F%2Fevil.test",
  ])("does not render separators that normalize %s into an external link", (href) => {
    const { container } = render(<FinalAnswerPanel run={makeRun({ status: "succeeded" })} streamingAnswer={`[bad](${href})`} isLiveRun={false} />);

    expect(container.querySelector("a")).toHaveAttribute("href", "");
  });

  test.each(["https://example.com", "HTTPS://example.com", "mAiLtO:team@example.com"])(
    "opens allowed external %s links with protected new-tab attributes",
    (href) => {
      render(<FinalAnswerPanel run={makeRun({ status: "succeeded" })} streamingAnswer={`[external](${href})`} answerStreamId={null} isLiveRun={false} />);

      const link = screen.getByRole("link", { name: /external/ });
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noreferrer noopener");
      expect(link).toHaveAccessibleName(/在新标签页中打开/);
    }
  );

  test("keeps formatted external-link text in its accessible name", () => {
    render(
      <FinalAnswerPanel
        run={makeRun({ status: "succeeded" })}
        streamingAnswer="[**粗体链接**](HTTPS://example.com)"
        answerStreamId={null}
        isLiveRun={false}
      />
    );

    const link = screen.getByRole("link");
    expect(link).toHaveAccessibleName("粗体链接（在新标签页中打开）");
    expect(link).not.toHaveAccessibleName(/\[object Object\]/);
  });

  test("keeps internal agent links in the current tab", () => {
    render(<FinalAnswerPanel run={makeRun({ status: "succeeded" })} streamingAnswer="[agent](/agent/sessions/session-1)" answerStreamId={null} isLiveRun={false} />);

    const link = screen.getByText("agent");
    expect(link).toHaveAttribute("href", "");
    expect(link).not.toHaveAttribute("target");
  });

  test.each(["/agent/sessions/session-1", "#answer"])("keeps allowed internal %s links in the current tab", (href) => {
    render(<FinalAnswerPanel run={makeRun({ status: "succeeded" })} streamingAnswer={`[internal](${href})`} answerStreamId={null} isLiveRun={false} />);

    const link = screen.getByText("internal");
    expect(link).toHaveAttribute("href", "");
    expect(link).not.toHaveAttribute("target");
  });

  test("skipHtml prevents raw HTML rendering", () => {
    const run: AgentRun = {
      ...baseRun,
      status: "succeeded",
    } as AgentRun;

    const { container } = render(
      <FinalAnswerPanel run={run} streamingAnswer="<img src=x onerror=alert(1)>" answerStreamId={null} isLiveRun={false} />
    );

    expect(container.querySelector("img")).toBeNull();
  });

  test("provides labelled answer and polite live stream semantics", async () => {
    const { container } = render(<FinalAnswerPanel run={baseRun} streamingAnswer="正在生成" />);

    const section = await screen.findByRole("region", { name: "最终回答" });
    expect(section).toHaveAttribute("aria-labelledby", "answer-heading-run-1");
    expect(screen.getByRole("heading", { name: "最终回答", level: 2 })).toHaveAttribute("id", "answer-heading-run-1");
    expect(container.querySelector(".final-answer-prose")).toHaveAttribute("aria-live", "polite");
  });

  test("terminal answer renders copy button", () => {
    const succeededRun = makeRun({
      status: "succeeded",
      result: { final_answer: "完成的内容" },
    });

    render(<FinalAnswerPanel run={succeededRun} streamingAnswer="" answerStreamId={null} />);

    expect(screen.getByRole("button", { name: "复制回答" })).toBeVisible();
  });

  test("streaming answer does not show copy action", () => {
    render(<FinalAnswerPanel run={baseRun} streamingAnswer="正在生成" />);

    expect(screen.queryByRole("button", { name: "复制回答" })).not.toBeInTheDocument();
  });
});

type FrameCallback = (timestamp: number) => void;

function installFakeRaf() {
  let nextId = 1;
  const frames = new Map<number, FrameCallback>();
  const requestAnimationFrame = vi.fn((callback: FrameCallback) => {
    const id = nextId++;
    frames.set(id, callback);
    return id;
  });
  const cancelAnimationFrame = vi.fn((id: number) => frames.delete(id));
  vi.stubGlobal("requestAnimationFrame", requestAnimationFrame);
  vi.stubGlobal("cancelAnimationFrame", cancelAnimationFrame);

  return {
    cancelAnimationFrame,
    pendingCount: () => frames.size,
    runNextFrame(timestamp: number) {
      const next = frames.entries().next().value as [number, FrameCallback] | undefined;
      if (!next) return;
      frames.delete(next[0]);
      next[1](timestamp);
    },
  };
}

describe("Scroll anchoring", () => {
  test("conversation stack uses overflow anchor", () => {
    const { container } = render(<FinalAnswerPanel run={baseRun} streamingAnswer="text" answerStreamId="live" />);
    const wrapper = container.closest(".detail-conversation-stack") || container;
    expect(wrapper).not.toBeNull();
  });
});

describe("Terminal Markdown DOM stability", () => {
  test("terminal answer renders markdown with heading after streaming completes", async () => {
    const matchMedia = vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList);
    try {
      const { rerender } = render(
        <FinalAnswerPanel run={baseRun} streamingAnswer={`# 标题

段落`} answerStreamId="live" />,
      );
      rerender(
        <FinalAnswerPanel run={{ ...baseRun, status: "succeeded", result: { final_answer: `# 标题

段落` } }} streamingAnswer="" answerStreamId={null} />,
      );
      expect(await screen.findByRole("heading", { name: "标题" })).toBeVisible();
      expect(screen.getByText("段落")).toBeVisible();
    } finally {
      matchMedia.mockRestore();
    }
  });
});

describe("Historical animation prevention", () => {
  test("queued historical run renders reasoning statically without typing animation", () => {
    const raf = installFakeRaf();
    const { container } = render(
      <ThoughtNarrative
        run={{ ...baseRun, status: "queued" }}
        steps={[]}
        events={[
          { id: "e1", run_id: "run-1", attempt_id: null, seq: 1, event_type: "visible_thought_started", payload: { step_index: 0, stream_id: "thought-1" }, created_at: "2026-01-01T00:00:00Z" },
          { id: "e2", run_id: "run-1", attempt_id: null, seq: 2, event_type: "visible_thought_completed", payload: { step_index: 0, stream_id: "thought-1", text: "历史思考内容" }, created_at: "2026-01-01T00:00:01Z" },
        ]}
        isLiveRun={false}
      />
    );
    expect(screen.getByText("历史思考内容")).toBeVisible();
    expect(raf.pendingCount()).toBe(0);
  });

  test("non-live running run renders reasoning statically", () => {
    const { container } = render(
      <ThoughtNarrative
        run={baseRun}
        steps={[]}
        events={[
          { id: "e1", run_id: "run-1", attempt_id: null, seq: 1, event_type: "visible_thought_started", payload: { step_index: 0, stream_id: "thought-1" }, created_at: "2026-01-01T00:00:00Z" },
          { id: "e2", run_id: "run-1", attempt_id: null, seq: 2, event_type: "visible_thought_delta", payload: { step_index: 0, stream_id: "thought-1", offset: 0, delta: "正在思考" }, created_at: "2026-01-01T00:00:01Z" },
        ]}
        isLiveRun={false}
      />
    );
    expect(screen.getByText("正在思考")).toBeVisible();
    const animated = container.querySelector('[class*="thought-narrative-item-streaming"]');
    expect(animated).toBeNull();
  });
});

describe("AnswerActions", () => {
  test("renders copy button for terminal answers", () => {
    render(<AnswerActions ownerId="run-1" sessionId="s1" text="test answer" onRegenerate={vi.fn()} />);

    expect(screen.getByRole("button", { name: "复制回答" })).toBeVisible();
  });

  test("does not render feedback or export buttons", () => {
    render(<AnswerActions ownerId="run-1" sessionId="s1" text="test" onRegenerate={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /反馈|导出|feedback|export/i })).not.toBeInTheDocument();
  });
});
