import { describe, expect, test } from "vitest";
import { advanceTypingAnimation } from "@/lib/typing-animation";

describe("advanceTypingAnimation", () => {
  test("advances one character with enough budget", () => {
    expect(advanceTypingAnimation({ displayedText: "", remainingMs: 20 }, "你好", 20, 20).displayedText)
      .toBe("你");
  });

  test("advances nothing with insufficient budget", () => {
    expect(advanceTypingAnimation({ displayedText: "", remainingMs: 20 }, "你好", 10, 20).displayedText)
      .toBe("");
  });

  test("advances multiple characters with large budget", () => {
    const result = advanceTypingAnimation({ displayedText: "", remainingMs: 20 }, "abcdef", 80, 20);
    expect(result.displayedText.length).toBe(4);
  });

  test("continues from partial text", () => {
    const result = advanceTypingAnimation({ displayedText: "ab", remainingMs: 20 }, "abcdef", 20, 20);
    expect(result.displayedText).toBe("abc");
  });

  test("starts fresh when target prefix mismatches", () => {
    const result = advanceTypingAnimation({ displayedText: "abc", remainingMs: 20 }, "xy", 20, 20);
    expect(result.displayedText).toBe("x");
  });

  test("reaches target within accumulated ticks", () => {
    const target = "a".repeat(100);
    let state = { displayedText: "", remainingMs: 20 };
    let totalMs = 0;
    while (state.displayedText !== target && totalMs < 5000) {
      state = advanceTypingAnimation(state, target, 20, 20);
      totalMs += 20;
    }
    expect(state.displayedText).toBe(target);
  });

  test("does not move backward when target grows", () => {
    const result = advanceTypingAnimation({ displayedText: "ab", remainingMs: 20 }, "abcde", 20, 20);
    expect(result.displayedText.startsWith("ab")).toBe(true);
  });
});
