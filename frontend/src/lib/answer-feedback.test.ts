import { describe, expect, test, vi } from "vitest";

const { readAnswerFeedback, writeAnswerFeedback, shareAnswer } = await vi.importActual("../lib/answer-feedback");

describe("answerFeedback", () => {
  test("feedback is mutually exclusive by run id", () => {
    writeAnswerFeedback("run-1", "like");
    expect(readAnswerFeedback("run-1")).toBe("like");
    writeAnswerFeedback("run-1", "dislike");
    expect(readAnswerFeedback("run-1")).toBe("dislike");
    writeAnswerFeedback("run-1", null);
    expect(readAnswerFeedback("run-1")).toBeNull();
  });

  test("different run ids have independent feedback", () => {
    writeAnswerFeedback("run-1", "like");
    expect(readAnswerFeedback("run-2")).toBeNull();
  });

  test("shareAnswer returns copied when navigator.share is unavailable", async () => {
    const originalShare = navigator.share;
    Object.defineProperty(navigator, "share", { value: undefined, configurable: true });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    const result = await shareAnswer({ text: "\u56de\u7b54", url: "https://app.test/agent/sessions/s1" });
    expect(result).toBe("copied");
    expect(writeText).toHaveBeenCalledWith("https://app.test/agent/sessions/s1");

    Object.defineProperty(navigator, "share", { value: originalShare, configurable: true });
  });
});
