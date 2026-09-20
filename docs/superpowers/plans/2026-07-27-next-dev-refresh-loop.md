# Next Development Refresh Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the continuous login-page reload loop while retaining normal Next 16 Fast Refresh in `C:\01_agent_loop\frontend`.

**Architecture:** Replace the copied custom development command with the Next 16 default `next dev`. Keep production preview separate, clear only generated Next state, and verify both static script contracts and live browser-server stability.

**Tech Stack:** Next.js 16.2.10, React 19.2.4, npm, Vitest, Windows PowerShell.

## Global Constraints

- Do not change login, authentication, Agent SSE, typing animation, or backend code.
- Do not delete `node_modules`; the installed dependencies match the lock file unless verification proves otherwise.
- Do not modify `X:\01_RBAC` as part of this fix.
- Preserve `preview`, `build`, `start`, `lint`, and `test` scripts.
- `npm run dev` must execute exactly `next dev`.

---

### Task 1: Restore Default Next Development Mode

**Files:**
- Modify: `C:\01_agent_loop\frontend\src\package-scripts.test.ts`
- Modify: `C:\01_agent_loop\frontend\package.json`
- Modify: `C:\01_agent_loop\frontend\README.md`

**Interfaces:**
- Consumes: npm package scripts and Next 16's default development command.
- Produces: `npm run dev` starts `next dev`; `npm run preview` remains `npm run build && next start`.

- [ ] **Step 1: Write the failing package-script test**

Change the script assertions to:

```typescript
expect(packageJson.scripts.dev).toBe("next dev");
expect(packageJson.scripts.preview).toBe("npm run build && next start");
```

Rename the test to `uses default Next development mode and keeps production preview separate`.

- [ ] **Step 2: Verify the test fails for the custom development command**

Run from `C:\01_agent_loop\frontend`:

```powershell
npm test -- --run src/package-scripts.test.ts
```

Expected: FAIL because `dev` is `next dev --webpack --no-server-fast-refresh`.

- [ ] **Step 3: Implement the minimal script and documentation change**

Set the package scripts to:

```json
"dev": "next dev",
"preview": "npm run build && next start"
```

Update the README Quick Start text to state that `npm run dev` uses Next 16 default Turbopack and Fast Refresh. Retain the existing Production Preview section unchanged.

- [ ] **Step 4: Verify the focused test passes**

Run:

```powershell
npm test -- --run src/package-scripts.test.ts
```

Expected: 1 test passed.

### Task 2: Clear Generated State And Verify Stability

**Files:**
- Delete generated directory: `C:\01_agent_loop\frontend\.next`
- Verify only: `C:\01_agent_loop\frontend\package-lock.json`

**Interfaces:**
- Consumes: corrected `npm run dev` command from Task 1.
- Produces: a fresh Turbopack development cache and stable `/login` page.

- [ ] **Step 1: Stop only the current C-copy Next development process**

Identify the process whose command contains `C:\01_agent_loop\frontend` and `next dev`, then stop that process tree. Do not stop the backend on port 8000.

- [ ] **Step 2: Remove only generated Next state**

Delete `C:\01_agent_loop\frontend\.next`. Preserve `node_modules`, `package-lock.json`, and `.env.local`.

- [ ] **Step 3: Run complete static verification**

Run:

```powershell
npm test -- --run
npm run build
```

Expected: all frontend tests pass and the production build succeeds.

- [ ] **Step 4: Start corrected development server and verify the route**

Run `npm run dev`, wait for readiness, request `http://localhost:3000/login`, and confirm HTTP 200.

- [ ] **Step 5: Verify no idle remount loop**

Observe `C:\01_agent_loop\frontend\.next\dev\logs\next-development.log` for at least 15 seconds without changing source files. Expected: no repeating browser initialization entry approximately every second.

- [ ] **Step 6: Record completion without a Git commit**

`C:\01_agent_loop` contains no `.git` directory, so do not create a commit. Report the exact modified files and verification results.
