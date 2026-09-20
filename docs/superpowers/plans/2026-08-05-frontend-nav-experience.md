# 前端导航体验优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过路由预热脚本（dev 场景）与生产模式脚本（使用场景）消除前端导航的编译等待体验。

**Architecture:** 新增 `frontend/scripts/prewarm-routes.mjs`（Node 内置 fetch，无第三方依赖）：等待 dev 服务器就绪后顺序 GET 全部路由触发按需编译；`package.json` 新增 `prewarm` 与 `serve`（`next build && next start`）脚本；README 补两段傻瓜式说明。

**Tech Stack:** Node 18+（内置 fetch/AbortSignal）、Next.js 16（保持 `--webpack`）、npm

## Global Constraints

- 保持 webpack（Turbopack 与本项目有已知兼容问题，dev/build 均不引入）
- 预热脚本零第三方依赖（只用 Node 内置模块）
- git 纪律：提交前 `git status --short` 核对暂存区只含本任务列出的文件；精确路径 `git add`，绝对禁止 `git add -A`
- 不并入 `dev` 脚本（避免阻塞启动与 Windows shell 兼容问题）
- 冒烟验证时若 3000 端口已被占用，用 `--port 3100` 验证并记录

---

### Task 1: 预热脚本 + package.json 脚本

**Files:**
- Create: `frontend/scripts/prewarm-routes.mjs`
- Modify: `frontend/package.json`（scripts 区加 `prewarm`、`serve`）

**Interfaces:**
- Produces: `npm run prewarm`（dev 就绪后预热全部路由）、`npm run serve`（生产构建并启动）（Task 2 文档引用）

- [ ] **Step 1: 创建脚本**（创建 `frontend/scripts/prewarm-routes.mjs`，完整内容）

```js
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
```

- [ ] **Step 2: 修改 package.json**

`frontend/package.json` 的 `"scripts"` 对象中，`"dev"` 行后追加（保持 JSON 合法）：

```json
    "prewarm": "node scripts/prewarm-routes.mjs",
    "serve": "next build && next start",
```

- [ ] **Step 3: 冒烟验证**（dev 服务器已由用户运行，或临时自启）

若 3000 端口已有 dev 服务器运行：直接执行 `npm run prewarm`，Expected: 全部路由 [OK]（状态 200/302，非 5xx），最后打印"预热完成: 11 成功, 0 失败"。
若 3000 没有 dev 服务器：先 `npm run dev` 放后台等就绪（或改用 `PREWARM_BASE_URL=http://localhost:3100` 配合 `next dev --webpack --port 3100` 验证），验证后关闭临时实例。
注：`/agent/sessions/00000000-...` 动态路由可能返回 200（渲染空会话页）或 500（若页面代码对不存在会话抛错）——若 500，在汇报中注明并视为编译完成（预热目的达成），不得改脚本吞掉 5xx。

- [ ] **Step 4: 提交**

```bash
git add frontend/scripts/prewarm-routes.mjs frontend/package.json
git commit -m "feat: add route prewarm and production serve scripts"
```

---

### Task 2: README 使用说明

**Files:**
- Modify: `README.md`（前端启动章节附近追加两段说明）

**Interfaces:**
- Consumes: `npm run prewarm`、`npm run serve`（Task 1）

- [ ] **Step 1: 定位插入点**

读 `README.md` 第 80-110 行（前端启动说明区域），在"运行前端"相关段落后追加两个小节。

- [ ] **Step 2: 追加说明**

在合适位置（`npm run dev` 说明之后）插入：

```markdown
#### 优化导航体验

- **路由预热（开发模式）**：`npm run dev` 启动后，另开终端执行 `npm run prewarm`，系统会自动把全部页面预编译一遍。之后首次进入任何页面都不会再出现 "Compiling..." 等待。每次重启 dev 服务器后重新执行一次。
- **生产模式（推荐日常使用）**：执行 `npm run serve` 一条命令完成生产构建并启动。生产模式下所有路由预构建，页面秒开、无编译提示。注意：每次修改代码后需重新执行 `npm run serve`。
```

- [ ] **Step 3: 提交**

```bash
git add README.md
git commit -m "docs: add prewarm and production serve usage notes"
```

---

### Task 3: 生产模式冒烟验证

**Files:** 无代码改动

- [ ] **Step 1: 构建**

Run（工作目录 `frontend`）: `npm run build`
Expected: 构建成功（输出含 Route 列表与生成统计）。若因 3000 端口被 dev 占用无法直接 `next start`，用 `npx next start --port 3100` 验证。

- [ ] **Step 2: 启动验证**

Run: `npx next start --port 3100`（若 3000 空闲可直接 `npm run serve`，构建后自动启动）
Expected: 服务器就绪；`curl http://localhost:3100/` 返回 200（HTML 页面）。验证后关闭临时实例。

- [ ] **Step 3: 汇报**

汇总提交 hash（Task 1/2）、预热冒烟结果、生产构建与启动验证结果。
