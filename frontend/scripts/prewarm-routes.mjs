// Route prewarm script: triggers Next.js dev on-demand compilation for all routes.
// Usage: start `npm run dev`, then run `npm run prewarm` once per dev server lifetime.
import { setTimeout as sleep } from "node:timers/promises";

const BASE = process.env.PREWARM_BASE_URL ?? "http://localhost:3000";

const ROUTES = [
  "/",
  "/login",
  "/agent",
  "/agent/audit",
  "/agent/debug/sse",
  "/agent/files",
  "/agent/sessions/00000000-0000-0000-0000-000000000000",
  "/files",
  "/roles",
  "/settings/profile",
  "/users",
];

async function waitForServer() {
  for (let attempt = 1; attempt <= 60; attempt += 1) {
    try {
      await fetch(`${BASE}/agent`, { signal: AbortSignal.timeout(3000) });
      return;
    } catch {
      // not ready yet
    }
    process.stdout.write(`等待 dev 服务器就绪 (${attempt}/60)...\n`);
    await sleep(1000);
  }
  throw new Error(`dev 服务器 ${BASE} 在 60s 内未就绪`);
}

async function main() {
  await waitForServer();
  let ok = 0;
  let fail = 0;
  for (const route of ROUTES) {
    const started = Date.now();
    try {
      const res = await fetch(`${BASE}${route}`, { signal: AbortSignal.timeout(120000) });
      const ms = Date.now() - started;
      if (res.status >= 500) {
        fail += 1;
        process.stdout.write(`[FAIL] ${route} -> ${res.status} (${ms}ms)\n`);
      } else {
        ok += 1;
        process.stdout.write(`[OK]   ${route} -> ${res.status} (${ms}ms)\n`);
      }
    } catch (err) {
      fail += 1;
      process.stdout.write(`[FAIL] ${route} -> ${err.message}\n`);
    }
  }
  process.stdout.write(`\n预热完成: ${ok} 成功, ${fail} 失败\n`);
  process.exit(fail > 0 ? 1 : 0);
}

main().catch((err) => {
  process.stderr.write(`${err.message}\n`);
  process.exit(1);
});
