import { describe, expect, test, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AnswerActions from "@/components/agent/answer-actions";

vi.mock("@/lib/browser-speech", () => ({
  browserSpeech: {
    supported: () => true,
    speak: vi.fn(() => true),
    stop: vi.fn(),
    reset: vi.fn(),
  },
}));

describe("AnswerActions", () => {
  test("renders all six terminal-answer action buttons", () => {
    render(<AnswerActions ownerId="run-1" sessionId="s1" text="\u5b8c\u6574\u56de\u7b54" onRegenerate={vi.fn()} />);
    expect(screen.getByRole("button", { name: "\u590d\u5236\u56de\u7b54" })).toBeVisible();
    expect(screen.getByRole("button", { name: "\u6717\u8bfb\u56de\u7b54" })).toBeVisible();
    expect(screen.getByRole("button", { name: "\u91cd\u65b0\u751f\u6210\u56de\u7b54" })).toBeVisible();
    expect(screen.getByRole("button", { name: "\u8d5e\u56de\u7b54" })).toBeVisible();
    expect(screen.getByRole("button", { name: "\u4e0d\u559c\u6b22\u56de\u7b54" })).toBeVisible();
    expect(screen.getByRole("button", { name: "\u8f6c\u53d1\u56de\u7b54" })).toBeVisible();
  });

  test("disables regeneration while pending", async () => {
    let resolve!: () => void;
    const onRegenerate = vi.fn(() => new Promise<void>((r) => { resolve = r; }));
    const user = userEvent.setup();
    render(<AnswerActions ownerId="run-1" sessionId="s1" text="\u56de\u7b54" onRegenerate={onRegenerate} />);
    await user.click(screen.getByRole("button", { name: "\u91cd\u65b0\u751f\u6210\u56de\u7b54" }));
    expect(screen.getByRole("button", { name: "\u91cd\u65b0\u751f\u6210\u56de\u7b54" })).toBeDisabled();
    resolve();
    await vi.waitFor(() => expect(screen.getByRole("button", { name: "\u91cd\u65b0\u751f\u6210\u56de\u7b54" })).not.toBeDisabled());
  });

  test("shows copy feedback and resets", async () => {
    const user = userEvent.setup();
    render(<AnswerActions ownerId="run-1" sessionId="s1" text="\u56de\u7b54" onRegenerate={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "\u590d\u5236\u56de\u7b54" }));
    expect(screen.getByText("\u5df2\u590d\u5236")).toBeVisible();
  });

  test("regenerate buttons do not appear for streaming or empty answers", () => {
    const { rerender } = render(<AnswerActions ownerId="run-1" sessionId="s1" text="" onRegenerate={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "\u91cd\u65b0\u751f\u6210\u56de\u7b54" })).not.toBeInTheDocument();
    rerender(<AnswerActions ownerId="run-1" sessionId="s1" text=" " onRegenerate={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "\u91cd\u65b0\u751f\u6210\u56de\u7b54" })).not.toBeInTheDocument();
  });
});
