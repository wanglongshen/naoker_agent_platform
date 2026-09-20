window.__ModuleLoader__.load({
  id: '@naoker/dsh-platform-connector',
  factory: (require) => {
    var module = { exports: {} }; var exports = module.exports;
"use strict";
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name2 in all)
    __defProp(target, name2, { get: all[name2], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// src/client/index.ts
var index_exports = {};
__export(index_exports, {
  apply: () => apply,
  name: () => name
});
module.exports = __toCommonJS(index_exports);

// src/client/selectors.ts
var SIDEBAR_COLUMN_SELECTOR = ":is([data-pane='sidebar'], [class*='sidebarCol'])";
var SETTINGS_TRIGGER_SELECTOR = "[data-slot='sidebar.settings'] > :is(button, [role='button'])";
var FILTER_TRIGGER_SELECTOR = "[data-slot='sidebar.workspaces'] button[aria-label='\u89C6\u56FE\u9009\u9879'], [data-slot='sidebar.workspaces'] button[aria-label='View options']";
var ADD_WORKSPACE_TRIGGER_SELECTOR = "[data-slot='sidebar.workspaces'] button[aria-label='\u6DFB\u52A0\u5DE5\u4F5C\u533A'], [data-slot='sidebar.workspaces'] button[aria-label='Add workspace']";

// src/client/bridge.ts
function clickTrigger(selector) {
  const el = document.querySelector(selector);
  if (el === null) {
    console.warn("[naoker-nav] trigger not found:", selector);
    return;
  }
  el.click();
}
async function runCommand(ctx, cmd, post) {
  const sessions = ctx.get("sessions");
  const workspaces = ctx.get("workspaces");
  switch (cmd.action) {
    case "select-session":
      if (cmd.payload?.sessionId) sessions.open(cmd.payload.sessionId);
      return;
    case "new-session":
      workspaces.startSession(cmd.payload?.workspaceId);
      return;
    case "search-sessions": {
      const query = cmd.payload?.query ?? "";
      const result = await sessions.search(query);
      const items = result.ok && result.value ? result.value.items.map((i) => ({ id: i.sessionId, snippet: i.snippet })) : [];
      post({ v: 1, type: "state", event: "search-results", payload: { query, items } });
      return;
    }
    case "open-settings":
      clickTrigger(SETTINGS_TRIGGER_SELECTOR);
      return;
    case "open-filter":
      clickTrigger(FILTER_TRIGGER_SELECTOR);
      return;
    case "add-workspace":
      clickTrigger(ADD_WORKSPACE_TRIGGER_SELECTOR);
      return;
  }
}
function installBridge(ctx, post) {
  const onMessage = (event) => {
    if (event.source !== window.parent) return;
    const data = event.data;
    if (data === null || typeof data !== "object" || data.v !== 1 || data.type !== "cmd") return;
    void runCommand(ctx, data, post);
  };
  window.addEventListener("message", onMessage);
  return () => {
    window.removeEventListener("message", onMessage);
  };
}

// src/client/observer.tsx
var import_react = require("react");

// src/client/data.ts
var UNGROUPED = "Ungrouped";
function visible(s, current, archived) {
  return s.origin !== "subagent" && !archived.has(s.id) && (!s.blank || s.id === current);
}
function node(s) {
  return { id: s.id, title: s.blank ? "New Session" : s.displayTitle, blank: s.blank, running: s.running, updatedAt: s.updatedAt };
}
function buildNavState(list, workspaces, archivedIds, currentId) {
  const archived = new Set(archivedIds);
  const groups = [];
  const accounted = /* @__PURE__ */ new Set();
  for (const w of workspaces) {
    const members = [];
    for (const id of w.sessionIds) {
      const s = list.byId[id];
      if (s === void 0) continue;
      accounted.add(id);
      if (!visible(s, currentId, archived)) continue;
      members.push(s);
    }
    groups.push({ key: w.workspaceId, workspaceId: w.workspaceId, label: w.title, sessions: members.map(node) });
  }
  const stray = list.ids.map((id) => list.byId[id]).filter((s) => s !== void 0 && !accounted.has(s.id) && visible(s, currentId, archived)).sort((a, b) => b.updatedAt - a.updatedAt);
  if (stray.length > 0) {
    groups.push({ key: "", label: UNGROUPED, sessions: stray.map(node) });
  }
  return currentId === void 0 ? { groups } : { currentSessionId: currentId, groups };
}

// src/client/observer.tsx
function createNavObserver(post) {
  return function NavObserver(props) {
    const list = props.useSessions((s) => s);
    const ws = props.useWorkspaces((s) => s);
    (0, import_react.useEffect)(() => {
      post({ v: 1, type: "state", event: "nav", payload: buildNavState(list, ws.items, ws.archivedSessionIds, list.current) });
    }, [list, ws]);
    return null;
  };
}
function installObserver(ctx, post) {
  const slots = ctx.get("slots");
  return slots.inject(
    "shell.overlay",
    () => slots.register({ name: "shell.overlay", id: "naoker-nav-observer" }, createNavObserver(post))
  );
}

// src/client/sidebar-hide.ts
var STYLE_ID = "naoker-nav-hide";
function zeroFirstTrack(value) {
  const tracks = value.trim().split(/\s+/);
  if (tracks.length < 3 || tracks[0] === "" || tracks[0] === "none") return null;
  tracks[0] = "0px";
  if (/^\d+(?:\.\d+)?px$/.test(tracks[1])) tracks[1] = "minmax(0, 1fr)";
  return tracks.join(" ");
}
function installSidebarHide() {
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
${SIDEBAR_COLUMN_SELECTOR} {
  width: 0 !important;
  min-width: 0 !important;
  flex: 0 0 0 !important;
  overflow: hidden !important;
  border-right: none !important;
}
`;
  document.head.appendChild(style);
  let frame = null;
  let originalTracks = "";
  let frameObserver = null;
  let waitObserver = null;
  const replay = () => {
    if (!(frame instanceof HTMLElement)) return;
    const inline = frame.style.gridTemplateColumns;
    const zeroed = zeroFirstTrack(inline !== "" ? inline : getComputedStyle(frame).gridTemplateColumns);
    if (zeroed !== null) frame.style.gridTemplateColumns = zeroed;
  };
  const attach = () => {
    const column = document.querySelector(SIDEBAR_COLUMN_SELECTOR);
    if (!(column instanceof HTMLElement)) return false;
    const parent = column.parentElement;
    if (!(parent instanceof HTMLElement)) return false;
    frame = parent;
    originalTracks = frame.style.gridTemplateColumns;
    replay();
    frameObserver = new MutationObserver(replay);
    frameObserver.observe(frame, { attributes: true, attributeFilter: ["style"] });
    return true;
  };
  if (!attach()) {
    waitObserver = new MutationObserver(() => {
      if (attach()) {
        waitObserver?.disconnect();
        waitObserver = null;
      }
    });
    waitObserver.observe(document.documentElement, { childList: true, subtree: true });
  }
  return () => {
    style.remove();
    frameObserver?.disconnect();
    waitObserver?.disconnect();
    if (frame instanceof HTMLElement) frame.style.gridTemplateColumns = originalTracks;
  };
}

// src/client/index.ts
var name = "naoker-platform-nav";
function apply(ctx) {
  document.body.setAttribute("data-naoker-nav", "1");
  const post = (event) => {
    window.parent.postMessage(event, "*");
  };
  ctx.effect(() => () => {
    document.body.removeAttribute("data-naoker-nav");
  }, "naoker-nav: body marker");
  ctx.effect(() => installSidebarHide(), "naoker-nav: hide native sidebar");
  ctx.effect(() => installBridge(ctx, post), "naoker-nav: bridge");
  ctx.effect(() => installObserver(ctx, post), "naoker-nav: observer");
  window.setTimeout(() => {
    post({ v: 1, type: "state", event: "ready", payload: {} });
  }, 0);
}

    return module.exports;
  },
});
