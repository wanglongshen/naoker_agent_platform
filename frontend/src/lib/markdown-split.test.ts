import { describe, it, expect } from "vitest";
import { splitBlocks, partitionInline, fastHash } from "./markdown-split";

describe("splitBlocks", () => {
  it("splits by double newline", () => {
    const result = splitBlocks("a\n\nb");
    expect(result.completed).toEqual(["a"]);
    expect(result.active).toBe("b");
  });

  it("returns empty completed when no delimiter", () => {
    const result = splitBlocks("hello");
    expect(result.completed).toEqual([]);
    expect(result.active).toBe("hello");
  });

  it("returns empty active when text ends with delimiter", () => {
    const result = splitBlocks("hello\n\n");
    expect(result.completed).toEqual(["hello"]);
    expect(result.active).toBe("");
  });

  it("preserves fenced code block as atomic (```)", () => {
    const result = splitBlocks("```\n\ninner\n```\n\nafter");
    expect(result.completed).toEqual(["```\n\ninner\n```"]);
    expect(result.active).toBe("after");
  });

  it("preserves fenced code block as atomic (~~~)", () => {
    const result = splitBlocks("~~~\n\ninner\n~~~\n\nafter");
    expect(result.completed).toEqual(["~~~\n\ninner\n~~~"]);
    expect(result.active).toBe("after");
  });

  it("handles unclosed fence as active block", () => {
    const result = splitBlocks("done\n\n```\nopen fence");
    expect(result.completed).toEqual(["done"]);
    expect(result.active).toBe("```\nopen fence");
  });

  it("handles multiple completed blocks", () => {
    const result = splitBlocks("a\n\nb\n\nc");
    expect(result.completed).toEqual(["a", "b"]);
    expect(result.active).toBe("c");
  });

  it("handles empty string", () => {
    const result = splitBlocks("");
    expect(result.completed).toEqual([]);
    expect(result.active).toBe("");
  });

  it("handles delimiter inside code fence as content", () => {
    const result = splitBlocks("```\ncode\n\ninside\n```\n\nafter");
    expect(result.completed).toEqual(["```\ncode\n\ninside\n```"]);
    expect(result.active).toBe("after");
  });

  it("handles text with only newlines (no double)", () => {
    const result = splitBlocks("line1\nline2");
    expect(result.completed).toEqual([]);
    expect(result.active).toBe("line1\nline2");
  });
});

describe("partitionInline", () => {
  it("returns full text as stable when all markers balanced", () => {
    const result = partitionInline("Hello **world**");
    expect(result.stable).toBe("Hello **world**");
    expect(result.tail).toBe("");
  });

  it("splits at unbalanced bold marker", () => {
    const result = partitionInline("Hello **wor");
    expect(result.stable).toBe("Hello ");
    expect(result.tail).toBe("**wor");
  });

  it("splits at unbalanced inline code", () => {
    const result = partitionInline("text `cod");
    expect(result.stable).toBe("text ");
    expect(result.tail).toBe("`cod");
  });

  it("returns full text as stable with balanced inline code", () => {
    const result = partitionInline("text `code` end");
    expect(result.stable).toBe("text `code` end");
    expect(result.tail).toBe("");
  });

  it("handles empty string", () => {
    const result = partitionInline("");
    expect(result.stable).toBe("");
    expect(result.tail).toBe("");
  });

  it("handles text with no markers", () => {
    const result = partitionInline("plain text 123");
    expect(result.stable).toBe("plain text 123");
    expect(result.tail).toBe("");
  });

  it("handles unbalanced italic", () => {
    const result = partitionInline("Hello *wor");
    expect(result.stable).toBe("Hello ");
    expect(result.tail).toBe("*wor");
  });

  it("handles balanced italic", () => {
    const result = partitionInline("Hello *world* end");
    expect(result.stable).toBe("Hello *world* end");
    expect(result.tail).toBe("");
  });

  it("handles unbalanced link (missing paren)", () => {
    const result = partitionInline("see [link");
    expect(result.stable).toBe("see ");
    expect(result.tail).toBe("[link");
  });

  it("handles balanced link", () => {
    const result = partitionInline("see [link](https://x.com) ok");
    expect(result.stable).toBe("see [link](https://x.com) ok");
    expect(result.tail).toBe("");
  });

  it("handles unbalanced strikethrough", () => {
    const result = partitionInline("text ~~strike");
    expect(result.stable).toBe("text ");
    expect(result.tail).toBe("~~strike");
  });

  it("handles balanced strikethrough", () => {
    const result = partitionInline("text ~~strike~~ end");
    expect(result.stable).toBe("text ~~strike~~ end");
    expect(result.tail).toBe("");
  });

  it("handles nested bold-italic", () => {
    const result = partitionInline("**bold *italic* end**");
    expect(result.stable).toBe("**bold *italic* end**");
    expect(result.tail).toBe("");
  });

  it("handles bold opening only", () => {
    const result = partitionInline("start **bold content");
    expect(result.stable).toBe("start ");
    expect(result.tail).toBe("**bold content");
  });

  it("returns everything as tail when bold never opened", () => {
    const result = partitionInline("no markers here");
    expect(result.stable).toBe("no markers here");
    expect(result.tail).toBe("");
  });
});

describe("fastHash", () => {
  it("returns same hash for same content", () => {
    expect(fastHash("hello")).toBe(fastHash("hello"));
  });

  it("returns different hash for different content", () => {
    expect(fastHash("hello")).not.toBe(fastHash("world"));
  });

  it("handles empty string", () => {
    expect(typeof fastHash("")).toBe("number");
  });
});
