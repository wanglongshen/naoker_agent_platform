import { act, render, screen } from "@testing-library/react";
import React, { useState } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { useTypingText } from "@/hooks/use-typing-text";

function TypingProbe({ targetText, resetKey }: {
  targetText: string;
  resetKey?: string | number | null;
}) {
  return React.createElement("output", { role: "status" }, useTypingText(targetText, { resetKey }));
}

function GrowingTypingProbe() {
  const [targetText, setTargetText] = useState("a");
  return React.createElement(
    "button",
    { onClick: () => setTargetText((current) => `${current}b`) },
    useTypingText(targetText),
  );
}

afterEach(() => {
  vi.useRealTimers();
});

describe("useTypingText", () => {
  test("keeps one pending frame after repeated target growth", () => {
    vi.useFakeTimers();
    const { getByRole } = render(React.createElement(GrowingTypingProbe));

    act(() => getByRole("button").click());
    act(() => getByRole("button").click());

    expect(vi.getTimerCount()).toBe(1);
  });

  test("grows displayed text monotonically across frames", () => {
    vi.useFakeTimers();
    render(React.createElement(TypingProbe, { targetText: "abcdef", resetKey: "init" }));

    act(() => { vi.advanceTimersByTime(120); });
    const first = screen.getByRole("status").textContent ?? "";
    act(() => { vi.advanceTimersByTime(20); });
    const second = screen.getByRole("status").textContent ?? "";

    expect("abcdef".startsWith(first)).toBe(true);
    expect(second.startsWith(first)).toBe(true);
  });

  test("clears only when resetKey confirms a new stream generation", () => {
    vi.useFakeTimers();
    const { rerender } = render(React.createElement(TypingProbe, { targetText: "first stream", resetKey: "one" }));

    act(() => { vi.advanceTimersByTime(100); });
    act(() => { vi.advanceTimersByTime(20); });
    const first = screen.getByRole("status").textContent ?? "";
    rerender(React.createElement(TypingProbe, { targetText: `${first} grows`, resetKey: "one" }));
    expect(screen.getByRole("status")).toHaveTextContent(first);

    rerender(React.createElement(TypingProbe, { targetText: "second stream", resetKey: "two" }));
    expect(screen.getByRole("status")).toHaveTextContent("");
  });

  test("cancels the pending timer on unmount", () => {
    vi.useFakeTimers();
    const clearTimeoutSpy = vi.spyOn(window, "clearTimeout");
    const { getByRole, unmount } = render(React.createElement(GrowingTypingProbe));

    act(() => getByRole("button").click());
    unmount();

    expect(clearTimeoutSpy).toHaveBeenCalled();
    clearTimeoutSpy.mockRestore();
  });
});
