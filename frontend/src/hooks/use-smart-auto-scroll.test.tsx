import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useSmartAutoScroll } from "./use-smart-auto-scroll";

function makeEl() {
  const el = document.createElement("div");
  el.scrollTop = 0;
  Object.defineProperty(el, "clientHeight", { value: 500, configurable: true });
  Object.defineProperty(el, "scrollHeight", { value: 1200, configurable: true });
  el.scrollTo = vi.fn(function (this: HTMLDivElement, opts?: ScrollToOptions) {
    if (opts && typeof opts.top === "number") this.scrollTop = opts.top;
  }) as HTMLDivElement["scrollTo"];
  return el;
}

function fireScroll(el: HTMLElement, scrollTop: number) {
  el.scrollTop = scrollTop;
  el.dispatchEvent(new Event("scroll"));
}

describe("useSmartAutoScroll", () => {
  let el: HTMLDivElement;
  let ref: React.RefObject<HTMLDivElement | null>;

  beforeEach(() => {
    el = makeEl();
    ref = { current: el } as React.RefObject<HTMLDivElement | null>;
  });

  it("scrolls to bottom on deps change when following", () => {
    const { rerender } = renderHook(
      ({ deps }) => useSmartAutoScroll(ref, deps),
      { initialProps: { deps: [1] } },
    );
    expect(el.scrollTo).not.toHaveBeenCalled();
    rerender({ deps: [2] });
    expect(el.scrollTo).toHaveBeenCalledWith({ top: 1200 });
  });

  it("does not scroll when user scrolled away from bottom", () => {
    const { rerender } = renderHook(
      ({ deps }) => useSmartAutoScroll(ref, deps),
      { initialProps: { deps: [1] } },
    );
    fireScroll(el, 200); // 远离底部 → shouldFollow=false
    rerender({ deps: [2] });
    expect(el.scrollTo).not.toHaveBeenCalled();
  });

  it("resumes following when scrolled back to bottom", () => {
    const { rerender } = renderHook(
      ({ deps }) => useSmartAutoScroll(ref, deps),
      { initialProps: { deps: [1] } },
    );
    fireScroll(el, 200);
    rerender({ deps: [2] });
    expect(el.scrollTo).not.toHaveBeenCalled();
    fireScroll(el, 700); // 1200-500-40=660 → 回底部 → shouldFollow=true
    rerender({ deps: [3] });
    expect(el.scrollTo).toHaveBeenCalledWith({ top: 1200 });
  });

  it("stops following on mousedown", () => {
    const { rerender } = renderHook(
      ({ deps }) => useSmartAutoScroll(ref, deps),
      { initialProps: { deps: [1] } },
    );
    el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    rerender({ deps: [2] });
    expect(el.scrollTo).not.toHaveBeenCalled();
  });

  it("reset force-scrolls to bottom and restores following", () => {
    const { result, rerender } = renderHook(
      ({ deps }) => useSmartAutoScroll(ref, deps),
      { initialProps: { deps: [1] } },
    );
    fireScroll(el, 200);
    rerender({ deps: [2] });
    expect(el.scrollTo).not.toHaveBeenCalled();
    result.current.reset();
    expect(el.scrollTo).toHaveBeenCalledWith({ top: 1200 });
    rerender({ deps: [3] });
    expect(el.scrollTo).toHaveBeenCalledWith({ top: 1200 });
  });

  it("removes listeners on unmount", () => {
    const removeSpy = vi.spyOn(el, "removeEventListener");
    const { unmount } = renderHook(() => useSmartAutoScroll(ref, [1]));
    unmount();
    expect(removeSpy).toHaveBeenCalledWith("scroll", expect.any(Function));
    expect(removeSpy).toHaveBeenCalledWith("mousedown", expect.any(Function), true);
  });
});
