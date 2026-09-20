import { render, screen, waitFor } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { ConfigProvider } from "antd";

const mockOnSubmit = vi.fn();

vi.mock("@/lib/agent-api", () => ({
  agentApi: {
    uploadAttachment: vi.fn().mockResolvedValue({ id: "attachment-1", filename: "test.txt", media_type: "text/plain", size_bytes: 100, extraction_status: "done", created_at: "2026-01-01T00:00:00Z" }),
  },
}));

const mockSpeechState = vi.fn();
const mockSpeechStart = vi.fn();
const mockSpeechStop = vi.fn();
const mockSpeechDispose = vi.fn();

vi.mock("@/hooks/use-speech-recognition", () => ({
  useSpeechRecognition: (options: { onFinalTranscript: any; disabled: boolean }) => {
    const state = mockSpeechState();
    return {
      state: state.state ?? "idle",
      interimText: state.interimText ?? "",
      message: state.message ?? null,
      supported: state.supported ?? true,
      start: mockSpeechStart,
      stop: mockSpeechStop,
      dispose: mockSpeechDispose,
    };
  },
}));

import ChatComposer from "./chat-composer";
import { agentApi } from "@/lib/agent-api";

function Wrapper({ children }: { children: React.ReactNode }) {
  return <ConfigProvider>{children}</ConfigProvider>;
}

function renderComposer(props: Partial<Parameters<typeof ChatComposer>[0]> = {}) {
  return render(
    <Wrapper>
      <ChatComposer
        placeholder="输入消息"
        onSubmit={mockOnSubmit}
        {...props}
      />
    </Wrapper>,
  );
}

describe("ChatComposer keyboard behavior", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSpeechState.mockReturnValue({ supported: true });
  });

  it("submits on Enter without Shift", async () => {
    const user = userEvent.setup();
    renderComposer();

    const textarea = screen.getByPlaceholderText("输入消息");
    await user.type(textarea, "问题{enter}");

    expect(mockOnSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ goal: "问题" }),
    );
  });

  it("does not submit on Shift+Enter, inserts newline instead", async () => {
    const user = userEvent.setup();
    renderComposer();

    const textarea = screen.getByPlaceholderText("输入消息") as HTMLTextAreaElement;
    await user.type(textarea, "第一行");

    textarea.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", shiftKey: true, bubbles: true }),
    );

    expect(mockOnSubmit).not.toHaveBeenCalled();
  });

  it("does not submit during IME composition", async () => {
    const user = userEvent.setup();
    renderComposer();

    const textarea = screen.getByPlaceholderText("输入消息");

    await user.type(textarea, "中文");

    textarea.dispatchEvent(new CompositionEvent("compositionstart"));
    textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", isComposing: true }));

    expect(mockOnSubmit).not.toHaveBeenCalled();
  });

  it("does not submit on Ctrl+Enter", async () => {
    const user = userEvent.setup();
    renderComposer();

    const textarea = screen.getByPlaceholderText("输入消息");
    await user.type(textarea, "消息{Control>}{enter}{/Control}");

    expect(mockOnSubmit).not.toHaveBeenCalled();
  });

  it("does not submit when textarea is empty or only whitespace", async () => {
    const user = userEvent.setup();
    renderComposer();

    const textarea = screen.getByPlaceholderText("输入消息");
    await user.type(textarea, "   ");
    await user.keyboard("{enter}");

    expect(mockOnSubmit).not.toHaveBeenCalled();
  });
});

describe("ChatComposer submission payload", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSpeechState.mockReturnValue({ supported: true });
  });

  it("submits goal without a mode field", async () => {
    const user = userEvent.setup();
    renderComposer();

    await user.type(screen.getByPlaceholderText("输入消息"), "写一份方案{enter}");
    await waitFor(() => {
      expect(mockOnSubmit).toHaveBeenCalledWith({
        goal: "写一份方案",
        attachmentIds: [],
      });
    });
  });

  it("does not render any mode terminology in the toolbar", () => {
    renderComposer();
    expect(screen.queryByText(/快速模式|专家模式|深度思考|智能搜索/)).not.toBeInTheDocument();
  });
});

describe("ChatComposer attachments", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSpeechState.mockReturnValue({ supported: true });
  });

  it("renders a keyboard-operable attachment button", () => {
    renderComposer();

    const attachButton = screen.getByRole("button", { name: "添加附件" });
    expect(attachButton).toBeInTheDocument();
  });

  it("shows inline file chips after selecting files", async () => {
    const user = userEvent.setup();
    const { container } = renderComposer();

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["content"], "report.txt", { type: "text/plain" });
    await user.upload(fileInput, file);

    expect(screen.getByText("report.txt")).toBeInTheDocument();
  });

  it("allows removing a pending file chip", async () => {
    const user = userEvent.setup();
    const { container } = renderComposer();

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["content"], "report.txt", { type: "text/plain" });
    await user.upload(fileInput, file);

    const removeButton = screen.getByRole("button", { name: "移除 report.txt" });
    await user.click(removeButton);

    expect(screen.queryByText("report.txt")).not.toBeInTheDocument();
  });

  it("displays upload error with role alert", async () => {
    const user = userEvent.setup();
    const { container } = renderComposer();

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const largeFile = new File(["x".repeat(21_000_000)], "large.txt", { type: "text/plain" });
    Object.defineProperty(largeFile, "size", { value: 21_000_000 });
    await user.upload(fileInput, largeFile);

    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("uploads pending files and passes attachment ids to onSubmit", async () => {
    const user = userEvent.setup();
    const { container } = renderComposer({ sessionId: "session-1" });

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, new File(["content"], "report.txt", { type: "text/plain" }));

    await user.type(screen.getByPlaceholderText("输入消息"), "分析附件{enter}");

    await waitFor(() => {
      expect(vi.mocked(agentApi.uploadAttachment)).toHaveBeenCalledWith("session-1", expect.any(FormData));
    });
    await waitFor(() => {
      expect(mockOnSubmit).toHaveBeenCalledWith({
        goal: "分析附件",
        attachmentIds: ["attachment-1"],
      });
    });
  });

  it("shows an upload error, keeps pending files, and does not call onSubmit when upload fails", async () => {
    vi.mocked(agentApi.uploadAttachment).mockRejectedValueOnce(new Error("upload failed"));
    const user = userEvent.setup();
    const { container } = renderComposer({ sessionId: "session-1" });

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, new File(["content"], "report.txt", { type: "text/plain" }));

    await user.type(screen.getByPlaceholderText("输入消息"), "分析附件{enter}");

    await waitFor(() => {
      expect(container.querySelector('[role="alert"]')?.textContent).toContain("上传");
    });
    expect(screen.getByText("report.txt")).toBeInTheDocument();
    expect(mockOnSubmit).not.toHaveBeenCalled();
  });

  it("shows an error and keeps pending files when submitting without a session", async () => {
    const user = userEvent.setup();
    const { container } = renderComposer();

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, new File(["content"], "report.txt", { type: "text/plain" }));

    await user.type(screen.getByPlaceholderText("输入消息"), "分析附件{enter}");

    expect(container.querySelector('[role="alert"]')?.textContent).toContain("请在会话中上传文件");
    expect(screen.getByText("report.txt")).toBeInTheDocument();
    expect(mockOnSubmit).not.toHaveBeenCalled();
  });
});

describe("ChatComposer disabled state", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSpeechState.mockReturnValue({ supported: true });
  });

  it("disables submit when disabled prop is true", async () => {
    const user = userEvent.setup();
    renderComposer({ disabled: true });

    const textarea = screen.getByPlaceholderText("输入消息");
    expect(textarea).toBeDisabled();
  });

  it("does not submit when disabled", async () => {
    const user = userEvent.setup();
    renderComposer({ disabled: true });

    const textarea = screen.getByPlaceholderText("输入消息");
    await user.type(textarea, "test{enter}");

    expect(mockOnSubmit).not.toHaveBeenCalled();
  });
});

describe("ChatComposer autoFocus", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSpeechState.mockReturnValue({ supported: true });
  });

  it("auto-focuses the textarea when autoFocus is true", () => {
    renderComposer({ autoFocus: true });

    const textarea = screen.getByPlaceholderText("输入消息");
    expect(textarea).toHaveFocus();
  });

  it("does not auto-focus when autoFocus is not set", () => {
    renderComposer();

    const textarea = screen.getByPlaceholderText("输入消息");
    expect(textarea).not.toHaveFocus();
  });
});

describe("ChatComposer clears input after submit", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSpeechState.mockReturnValue({ supported: true });
  });

  it("clears textarea value after successful submit", async () => {
    mockOnSubmit.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderComposer();

    const textarea = screen.getByPlaceholderText("输入消息") as HTMLTextAreaElement;
    await user.type(textarea, "消息{enter}");

    await waitFor(() => {
      expect(textarea.value).toBe("");
    });
  });
});

describe("ChatComposer submit label", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSpeechState.mockReturnValue({ supported: true });
  });

  it("uses aria-label '发送消息' on the submit button regardless of submitLabel", () => {
    renderComposer({ submitLabel: "开始对话" });

    const submitButton = screen.getByRole("button", { name: "发送消息" });
    expect(submitButton).toBeInTheDocument();
  });

  it("uses default ↑ when no submitLabel provided", () => {
    renderComposer();

    const submitButton = screen.getByRole("button", { name: "发送消息" });
    expect(submitButton).toBeInTheDocument();
  });
});

describe("ChatComposer narrow-state regression", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("keeps textarea, mic, and send present in document during interim speech state", () => {
    mockSpeechState.mockReturnValue({
      supported: true,
      state: "listening",
      interimText: "正在转写…",
    });

    renderComposer();

    expect(screen.getByPlaceholderText("输入消息")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "停止语音输入" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送消息" })).toBeInTheDocument();
  });

  it("keeps textarea, mic, and send present in document during error speech state", () => {
    mockSpeechState.mockReturnValue({
      supported: true,
      state: "error",
      message: "浏览器未授予麦克风权限。",
    });

    renderComposer();

    expect(screen.getByPlaceholderText("输入消息")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "语音输入" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送消息" })).toBeInTheDocument();
  });
});

describe("ChatComposer speech recognition", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSpeechState.mockReturnValue({ supported: true });
  });

  it("renders microphone button with correct aria attributes when supported", () => {
    renderComposer();

    const micButton = screen.getByRole("button", { name: "语音输入" });
    expect(micButton).toBeVisible();
    expect(micButton).toHaveAttribute("aria-pressed", "false");
  });

  it("renders mic button without long privacy text in the DOM", () => {
    renderComposer();

    expect(screen.getByRole("button", { name: "语音输入" })).toBeInTheDocument();
    expect(screen.queryByText(/语音由当前浏览器或系统语音服务实时转写/)).not.toBeInTheDocument();
  });

  it("does not render microphone button when unsupported", () => {
    mockSpeechState.mockReturnValue({ supported: false });

    renderComposer();

    expect(screen.queryByRole("button", { name: "语音输入" })).not.toBeInTheDocument();
  });

  it("renders unsupported explanation text when unsupported", () => {
    mockSpeechState.mockReturnValue({ supported: false });

    renderComposer();

    expect(screen.getByText(/语音输入需要浏览器语音支持/)).toBeInTheDocument();
  });

  it("renders listening state with correct aria-pressed", () => {
    mockSpeechState.mockReturnValue({ supported: true, state: "listening" });

    renderComposer();

    const micButton = screen.getByRole("button", { name: "停止语音输入" });
    expect(micButton).toHaveAttribute("aria-pressed", "true");
  });

  it("renders interim text when present", () => {
    mockSpeechState.mockReturnValue({
      supported: true,
      state: "listening",
      interimText: "测试语音输入",
    });

    renderComposer();

    expect(screen.getByText("测试语音输入")).toBeInTheDocument();
  });

  it("renders error message with role alert", () => {
    mockSpeechState.mockReturnValue({
      supported: true,
      state: "error",
      message: "浏览器未授予麦克风权限。",
    });

    renderComposer();

    const error = screen.getByRole("alert");
    expect(error).toHaveTextContent("浏览器未授予麦克风权限。");
  });

  it("calls speech.start on mic click when idle", async () => {
    mockSpeechState.mockReturnValue({ supported: true, state: "idle" });
    const user = userEvent.setup();
    renderComposer();

    const micButton = screen.getByRole("button", { name: "语音输入" });
    await user.click(micButton);

    expect(mockSpeechStart).toHaveBeenCalledTimes(1);
  });

  it("calls speech.stop on mic click when listening", async () => {
    mockSpeechState.mockReturnValue({ supported: true, state: "listening" });
    const user = userEvent.setup();
    renderComposer();

    const micButton = screen.getByRole("button", { name: "停止语音输入" });
    await user.click(micButton);

    expect(mockSpeechStop).toHaveBeenCalledTimes(1);
  });

  it("calls speech.stop before submit", async () => {
    mockSpeechState.mockReturnValue({ supported: true, state: "idle" });
    const user = userEvent.setup();
    renderComposer();

    const textarea = screen.getByPlaceholderText("输入消息");
    await user.type(textarea, "问题{enter}");

    expect(mockSpeechStop).toHaveBeenCalled();
  });

  it("disables mic button when disabled prop is true", () => {
    mockSpeechState.mockReturnValue({ supported: true, state: "idle" });
    renderComposer({ disabled: true });

    const micButton = screen.getByRole("button", { name: "语音输入" });
    expect(micButton).toBeDisabled();
  });
});
