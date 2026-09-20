import { act, renderHook } from "@testing-library/react";
import { describe, expect, test, vi, afterEach } from "vitest";
import { useLiveAnswerText } from "@/hooks/use-live-answer-text";

function installFakeRaf() {
  let nextId = 1;
  const frames = new Map<number, (ts: number) => void>();
  const raf = vi.fn((cb: (ts: number) => void) => { const id = nextId++; frames.set(id, cb); return id; });
  const caf = vi.fn((id: number) => frames.delete(id));
  vi.stubGlobal("requestAnimationFrame", raf);
  vi.stubGlobal("cancelAnimationFrame", caf);
  return {
    pendingCount: () => frames.size,
    runNextFrame(ts: number) {
      const [id, cb] = frames.entries().next().value ?? [];
      if (!id) return;
      frames.delete(id);
      cb(ts);
    },
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("useLiveAnswerText", () => {
  test("renders target immediately when disabled", () => {
    const { result } = renderHook(() => useLiveAnswerText("full answer", { enabled: false, resetKey: "s1" }));
    expect(result.current).toBe("full answer");
  });

  test("exposes the latest target after one RAF frame", () => {
    const raf = installFakeRaf();
    const { result, rerender } = renderHook(
      ({ text }) => useLiveAnswerText(text, { enabled: true, resetKey: "s1" }),
      { initialProps: { text: "hello" } },
    );
    expect(result.current).toBe("hello");

    rerender({ text: "hello world" });
    expect(result.current).toBe("hello");
    expect(raf.pendingCount()).toBe(1);

    act(() => raf.runNextFrame(16));
    expect(result.current).toBe("hello world");
    expect(raf.pendingCount()).toBe(0);
  });

  test("coalesces multiple target updates before a single frame", () => {
    const raf = installFakeRaf();
    const { result, rerender } = renderHook(
      ({ text }) => useLiveAnswerText(text, { enabled: true, resetKey: "s1" }),
      { initialProps: { text: "a" } },
    );
    expect(result.current).toBe("a");

    rerender({ text: "ab" });
    rerender({ text: "abc" });
    rerender({ text: "abcd" });
    expect(raf.pendingCount()).toBe(1);

    act(() => raf.runNextFrame(16));
    expect(result.current).toBe("abcd");
  });

  test("does not cancel a scheduled frame while high-frequency targets arrive", () => {
    const raf = installFakeRaf();
    const { result, rerender } = renderHook(
      ({ text }) => useLiveAnswerText(text, { enabled: true, resetKey: "s1" }),
      { initialProps: { text: "a" } },
    );

    rerender({ text: "ab" });
    rerender({ text: "abc" });
    rerender({ text: "abcd" });
    rerender({ text: "abcde" });

    act(() => raf.runNextFrame(16));

    expect(result.current).toBe("abcde");
  });

  test("resets on stream generation change", () => {
    const raf = installFakeRaf();
    const { result, rerender } = renderHook(
      ({ text, resetKey }) => useLiveAnswerText(text, { enabled: true, resetKey }),
      { initialProps: { text: "old stream", resetKey: "one" } },
    );
    act(() => raf.runNextFrame(16));
    expect(result.current).toBe("old stream");

    rerender({ text: "new stream", resetKey: "two" });
    expect(result.current).toBe("new stream");
  });

  test("cleans up pending RAF on unmount", () => {
    const raf = installFakeRaf();
    const { unmount, rerender } = renderHook(
      ({ text }) => useLiveAnswerText(text, { enabled: true, resetKey: "s1" }),
      { initialProps: { text: "a" } },
    );
    rerender({ text: "ab" });
    unmount();
    expect(raf.pendingCount()).toBe(0);
  });
});
