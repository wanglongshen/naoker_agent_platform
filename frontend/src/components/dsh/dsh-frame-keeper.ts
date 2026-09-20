"use client";

/**
 * DSH iframe 单例保管器（方案 B：全局常驻）。
 *
 * 目的：把 iframe 元素做成进程内单例，页面切换时只在 DOM 中「搬家」——
 * 从 /agent 的内容区移到 body 下的隐藏容器（park），或反向移回（attach）。
 * DOM 搬家（appendChild）不会重建 browsing context，DSH UI 不重载、会话不中断。
 *
 * 注意：移动必须是原子 appendChild（同一元素从旧父节点摘除并挂到新父节点），
 * 不能先 remove() 再 append()——脱离文档会销毁 iframe 的嵌套浏览上下文。
 */

const HOLDER_CLASS = "dsh-frame-holder";

let frame: HTMLIFrameElement | null = null;
let holder: HTMLDivElement | null = null;
let baseSrc: string | null = null;

function ensureHolder(): HTMLDivElement {
  if (holder === null) {
    holder = document.createElement("div");
    holder.className = HOLDER_CLASS;
    holder.setAttribute("aria-hidden", "true");
    document.body.appendChild(holder);
  }
  return holder;
}

/** 取得（必要时创建）单例 iframe；基准 src 变化时重新加载（如实例重建后端口变化）。 */
export function ensureFrame(src: string): HTMLIFrameElement {
  if (frame === null) {
    frame = document.createElement("iframe");
    frame.className = "dsh-workspace-frame";
    frame.title = "DSH 工作区";
    frame.setAttribute("src", src);
    baseSrc = src;
    return frame;
  }
  if (src !== baseSrc) {
    baseSrc = src;
    frame.setAttribute("src", src);
  }
  return frame;
}

/** 强制重新加载单例 iframe（同端口重建实例后原文档已失联）。 */
export function reloadFrame(): void {
  if (frame === null || baseSrc === null) return;
  const sep = baseSrc.includes("?") ? "&" : "?";
  frame.setAttribute("src", `${baseSrc}${sep}rev=${Date.now()}`);
}

/** 把单例 iframe 挂进页面容器（/agent 内容区）。 */
export function attachFrame(container: HTMLElement, src: string): void {
  const el = ensureFrame(src);
  if (el.parentElement !== container) container.appendChild(el);
}

/** 把单例 iframe 移到隐藏容器（离开 /agent 时保活）。 */
export function parkFrame(): void {
  if (frame === null) return;
  const target = ensureHolder();
  if (frame.parentElement !== target) target.appendChild(frame);
}

/** 测试辅助：销毁单例与容器。 */
export function resetFrameKeeper(): void {
  frame?.remove();
  frame = null;
  baseSrc = null;
  holder?.remove();
  holder = null;
}

/** 测试辅助：读取当前基准 src。 */
export function peekFrameSrc(): string | null {
  return baseSrc;
}
