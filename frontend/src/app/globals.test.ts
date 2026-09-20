import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "vitest";

test("keeps primary button foreground text readable on orange backgrounds", () => {
  const css = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

  expect(css).toContain(".ant-btn-color-primary.ant-btn-variant-solid { background: var(--warm-primary) !important;");
  expect(css).toContain(".ant-btn-color-primary.ant-btn-variant-solid > span");
});

test("defines the shared warm-intelligence design tokens in :root", () => {
  const css = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

  expect(css).toContain("--color-bg-app: #FAF7F3");
  expect(css).toContain("--color-sidebar: #e8751d");
  expect(css).toContain("--color-sidebar-elevated: #B94F0C");
  expect(css).toContain("--color-primary: #D96313");
  expect(css).toContain("--color-text-primary: #2B2521");
  expect(css).toContain("--color-border: #E6DDD6");
  expect(css).toContain("--bp-sm: 640px");
  expect(css).toContain("--bp-md: 768px");
});

test("removes blanket outline reset on textarea/input/button", () => {
  const css = readFileSync(resolve(process.cwd(), "src/app/agent-globals.css"), "utf8");

  expect(css).not.toMatch(/textarea,\s*input,\s*button\s*\{[^}]*outline:\s*none/s);
});

test("brand orange sidebar: white-background selected state and brand mark", () => {
  const css = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

  expect(css).toContain(".sidebar-brand-mark { flex-shrink: 0; width: 34px; height: 34px; background: #fff;");
  expect(css).toContain("background: #fff !important; color: #a03c08 !important;");
  expect(css).toContain(".sidebar-session-list-wrapper .session-item-active { background: #fff !important; padding-left: 8px; border-radius: 8px; box-shadow: 0 3px 10px rgba(0,0,0,.18); }");
});

test("brand orange login panel: orange gradient with white glow and white mark", () => {
  const css = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

  expect(css).toContain("background: linear-gradient(155deg,#cf5a10 0%,#b94f0c 55%,#9a3d0a 100%);");
  expect(css).toContain("radial-gradient(ellipse at 20% 50%, rgba(255,255,255,.16) 0, transparent 50%)");
  expect(css).toContain("background: #fff; border-radius: 11px;");
  expect(css).toContain("font-size: 19px; font-weight: 800; color: #c74e0b;");
});

test("login page neural brain theme css", () => {
  const css = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

  expect(css).toContain("background: linear-gradient(155deg,#cf5a10 0%,#b94f0c 55%,#9a3d0a 100%);");
  expect(css).toContain("@keyframes login-pulse");
  expect(css).toContain("@keyframes login-spin");
  expect(css).toContain(".login-ai-chip { position: absolute; right: -6px; top: -8px;");
});

test("sidebar embellishment: gradient, decor, brand and new-chat styles", () => {
  const css = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

  expect(css).toContain("background: linear-gradient(160deg,#e8751d 0%,#d96313 50%,#b94f0c 100%);");
  expect(css).toContain(".sidebar-decor-ring { position: absolute; right: -34px; top: 96px; width: 110px; height: 110px;");
  expect(css).toContain(".new-chat-plus { width: 17px; height: 17px; border-radius: 5px;");
  expect(css).toContain(".sidebar-brand::after { content: \"\"; position: absolute; left: 18px; right: 18px; bottom: -1px; height: 1px;");
  expect(css).toContain(".sidebar-management .ant-menu-dark .ant-menu-item-selected::after");
});

test("orange unified top bar: gradient, white text, logo, product name and user button", () => {
  const css = readFileSync(resolve(process.cwd(), "src/app/agent-globals.css"), "utf8");

  expect(css).toContain(".app-header {");
  expect(css).toContain("background: linear-gradient(160deg,#e8751d 0%,#d96313 50%,#b94f0c 100%);");
  expect(css).toContain(".app-header .top-bar-logo { width: 26px; height: 26px;");
  expect(css).toContain(".app-header .header-product-name {");
  expect(css).toContain(".app-header .top-bar-user-btn {");
  expect(css).not.toContain(".conversation-top-bar");
});
