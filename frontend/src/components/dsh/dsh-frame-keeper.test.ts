import { afterEach, describe, expect, it } from "vitest";
import {
  attachFrame,
  ensureFrame,
  parkFrame,
  peekFrameSrc,
  reloadFrame,
  resetFrameKeeper,
} from "./dsh-frame-keeper";

describe("dsh-frame-keeper", () => {
  afterEach(() => {
    resetFrameKeeper();
  });

  it("creates the iframe once and keeps the same element", () => {
    const first = ensureFrame("http://127.0.0.1:3163/");
    const second = ensureFrame("http://127.0.0.1:3163/");
    expect(first).toBe(second);
    expect(first.getAttribute("src")).toBe("http://127.0.0.1:3163/");
  });

  it("updates src only when it changes", () => {
    const frame = ensureFrame("http://127.0.0.1:3163/");
    ensureFrame("http://127.0.0.1:3163/");
    expect(peekFrameSrc()).toBe("http://127.0.0.1:3163/");
    ensureFrame("http://127.0.0.1:3200/");
    expect(frame.getAttribute("src")).toBe("http://127.0.0.1:3200/");
  });

  it("reloads by appending a cache-busting revision", () => {
    const frame = ensureFrame("http://127.0.0.1:3163/");
    reloadFrame();
    expect(frame.getAttribute("src")).toContain("http://127.0.0.1:3163/?rev=");
  });

  it("moves the same element between the page container and the hidden holder", () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    attachFrame(container, "http://127.0.0.1:3163/");
    const frame = container.querySelector("iframe");
    expect(frame).toBeTruthy();

    parkFrame();
    expect(container.querySelector("iframe")).toBeNull();
    const holder = document.querySelector(".dsh-frame-holder");
    expect(holder?.querySelector("iframe")).toBe(frame);

    attachFrame(container, "http://127.0.0.1:3163/");
    expect(container.querySelector("iframe")).toBe(frame);
    container.remove();
  });
});
