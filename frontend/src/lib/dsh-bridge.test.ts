import { renderHook, act } from "@testing-library/react";
import type { RefObject } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useDshBridge } from "./dsh-bridge";
import { dshBridgeStore } from "./dsh-bridge-store";

function makeIframe() {
  const iframe = document.createElement("iframe");
  document.body.appendChild(iframe);
  return iframe;
}

function makeMessage(data: unknown, source: Window | null) {
  const event = new MessageEvent("message", { data });
  Object.defineProperty(event, "source", { value: source });
  return event;
}

describe("useDshBridge", () => {
  it("ignores messages from other sources and applies nav from the iframe", () => {
    const iframe = makeIframe();
    const ref = { current: iframe } as RefObject<HTMLIFrameElement | null>;
    const { result } = renderHook(() => useDshBridge(ref));
    act(() => {
      window.dispatchEvent(makeMessage({ v: 1, type: "state", event: "nav", payload: { groups: [] } }, window));
    });
    expect(result.current.nav).toBeNull();
    act(() => {
      window.dispatchEvent(makeMessage({ v: 1, type: "state", event: "nav", payload: { groups: [] } }, iframe.contentWindow));
    });
    expect(result.current.nav).toEqual({ groups: [] });
  });

  it("send posts a v1 command to the iframe", () => {
    const iframe = makeIframe();
    const post = vi.spyOn(iframe.contentWindow as Window, "postMessage");
    const ref = { current: iframe } as RefObject<HTMLIFrameElement | null>;
    const { result } = renderHook(() => useDshBridge(ref));
    act(() => { result.current.send({ v: 1, type: "cmd", action: "new-session" }); });
    expect(post).toHaveBeenCalledWith({ v: 1, type: "cmd", action: "new-session" }, "*");
  });
});

describe("dshBridgeStore", () => {
  afterEach(() => {
    dshBridgeStore.reset();
  });

  it("publishes state and notifies subscribers until unsubscribed", () => {
    const listener = vi.fn();
    const unsubscribe = dshBridgeStore.subscribe(listener);
    const nav = { currentSessionId: "s1", groups: [{ key: "w1", label: "工作区", sessions: [] }] };
    dshBridgeStore.publishNav(nav);
    expect(dshBridgeStore.getSnapshot().nav).toEqual(nav);
    expect(dshBridgeStore.getState().nav).toEqual(nav);
    expect(listener).toHaveBeenCalledTimes(1);

    dshBridgeStore.publishConnection({ connected: true, attempt: 2 });
    dshBridgeStore.publishSearchResults({ query: "hello", items: [{ id: "s1", snippet: "hello" }] });
    dshBridgeStore.publishReady(true);
    expect(listener).toHaveBeenCalledTimes(4);

    unsubscribe();
    dshBridgeStore.publishNav(null);
    expect(listener).toHaveBeenCalledTimes(4);
    expect(dshBridgeStore.getState().nav).toBeNull();
  });

  it("routes send through the registered sender and clears it on reset", () => {
    const sender = vi.fn();
    dshBridgeStore.setSender(sender);
    dshBridgeStore.send({ v: 1, type: "cmd", action: "open-settings" });
    expect(sender).toHaveBeenCalledWith({ v: 1, type: "cmd", action: "open-settings" });

    dshBridgeStore.reset();
    dshBridgeStore.send({ v: 1, type: "cmd", action: "new-session" });
    expect(sender).toHaveBeenCalledTimes(1);
    expect(dshBridgeStore.getState()).toEqual({
      nav: null,
      connection: { connected: false, attempt: 0 },
      searchResults: null,
      ready: false,
    });
  });
});
