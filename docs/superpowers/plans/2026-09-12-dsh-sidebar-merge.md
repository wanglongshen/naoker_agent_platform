# DSH 侧栏合并 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 DSH 原生侧栏隐藏、将工作区/会话/新会话/搜索/过滤/新建工作区/设置全部功能合并进平台唯一左侧导航（`docs/superpowers/specs/2026-09-12-dsh-sidebar-merge-design.md`）。

**Architecture:** DSH 侧新增一个 client 插件（挂在现有 `@naoker/dsh-platform-connector` 包上），负责：零宽隐藏原生侧栏（保留 DOM 存活以保住设置面板）、经 `postMessage` 桥执行平台侧命令、通过框架注入的 `useSessions/useWorkspaces` hooks 观察会话/工作区变化并上行推送。平台侧新增桥 hook + 状态 store + `DshNavSection` 组件，`AppSidebar` 在 `/agent` 路由渲染 DSH 区，`/agent/legacy` 保留旧列表。

**Tech Stack:** TypeScript、esbuild（client 打包成 DSH module-loader 信封）、vitest + jsdom（插件侧测试）、Next.js + React + AntD + vitest（平台侧测试）。

## Global Constraints

- DSH 版本锁定 vendored 0.1.1-rc.2；**不改 `deepseek-harness/` 源码**，只做插件层扩展。
- 插件包名 `@naoker/dsh-platform-connector`；client 入口产物必须是 `window.__ModuleLoader__.load({ id: '@naoker/dsh-platform-connector', factory: (require) => {...} })` 信封（参照 `dsh-at-file` 实测产物）。
- client bundle 的外部依赖（`react`、`react/jsx-runtime`、`@deepseek-ai/*`）一律 external，运行时由 loader 的 `require` 提供。
- 协议版本号固定 `v: 1`；消息只含会话/工作区元数据与命令，不含任何平台令牌。
- 前端遵循既有模式：AntD 组件、`copy.ts` 文案、模块级 store（参照 `frontend/src/lib/agent-session-store.ts`）。
- 每个任务提交前用 `git diff --cached --name-only` 核对暂存区，只 add 本任务文件（仓库常有他人预置文件）。
- 视觉规范：侧栏橙色渐变 `#FF8A3D → #F2620F`；选中项 `rgba(255,255,255,.22)` + 左侧 3px 白条；运行中绿点 `#7CFFB2`；异常条 `#7F1D1D/#FCA5A5`；重连条 `#92400E/#FCD34D`。
- 单测命令：插件侧 `cd dsh-platform/packages/server-connector && npx vitest run`；前端 `cd frontend && npm test -- --run`。

---

### Task 1: Spike — DSH 客户端能力核验与机制定稿

**Files:**
- Modify: `dsh-platform/NOTES.md`（追加 §8）
- Create: `dsh-platform/packages/server-connector/src/client/selectors.ts`

**Interfaces:**
- Consumes: vendored 源码 `deepseek-harness/packages/client/*`、已装 DSH `C:\Users\Lenovo\AppData\Roaming\npm\node_modules\@deepseek-ai\dsh\`
- Produces: `selectors.ts`（T4/T5 依赖的具体选择器常量）与 NOTES §8（机制决定）

- [ ] **Step 1: 核验客户端服务可用性**

在 vendored 源码确认以下调用链（记录 文件:行号 到 NOTES §8）：
- `ctx.sessions.open(sessionId)`（证据：`packages/client/ui-workspace/src/client/index.ts:76`）
- `ctx.workspaces.startSession(workspaceId)`（同文件 `:74`）
- `ctx.sessions.search(query)` 返回 `{ok, value}`（同文件 `:62-66`）
- 槽注册 `ctx.slots.register({name}, Component)` 与 `ctx.slots.inject(hole, cb)`（同文件 `:126-136`）
- 槽组件 props 注入 hooks：`useSessions`（`packages/client/ui-workspace/src/client/WorkspaceBrowser.tsx:218,258`）；`useWorkspaces`（`index.ts:5-6` 注释）
- `shell.overlay` 槽的声明位置与 kind（grep `ui-layout/src/client/index.ts` 与 `AppFrame.tsx:23`），确认可注册"返回 null 的观察组件"

- [ ] **Step 2: 定稿隐藏机制并核验**

决定：**零宽隐藏**（`width:0 + min-width:0 + overflow:hidden`），不替换 `sidebar` 槽——因为设置面板是侧栏列的 `position:fixed` 后代（证据：`ui-sidebar/src/client/SidebarRoot.tsx:89-91`），替换槽会连带销毁设置面板。
在真实实例（`http://127.0.0.1:3163`）浏览器 DevTools 里注入验证：
```js
const col = document.querySelector(":is([data-pane='sidebar'], [class*='sidebarCol'])");
col.style.width = '0px'; col.style.minWidth = '0px'; col.style.overflow = 'hidden';
```
确认：① 侧栏不可见且无残留空列；② 会话区铺满；③ 点击 `[data-slot='sidebar.settings'] > :is(button,[role='button'])` 后设置面板可见（fixed 后代逃逸 overflow 裁剪）。结果记入 NOTES §8。

- [ ] **Step 3: 定稿过滤/新建工作区/设置的触发选择器**

在 DevTools 里定位并记录到 `selectors.ts`：
- 设置：`[data-slot='sidebar.settings'] > :is(button, [role='button'])`
- 过滤/排序（滑杆图标）：在 `[data-slot='sidebar.workspaces']` 子树中定位真实按钮（记录 DOM 片段证据）
- ＋新建工作区：同上定位（注意：目录选择弹窗若为侧栏子树内联面板，则 `add-workspace` 命令改为"先临时恢复侧栏宽度 → 点击 → 弹窗关闭后恢复零宽"，并把该流程写入 NOTES §8）
- 搜索：确认走 `ctx.sessions.search` 服务自渲染（不点原生搜索框，因原生搜索 UI 在侧栏子树内会被裁剪）

- [ ] **Step 4: 创建 selectors.ts（用 Step 3 实测结果填值）**

```ts
/** DSH 原生侧栏内的稳定触发点（Task 1 spike 实测；与皮肤包同款 class 子串兜底）。 */
export const SIDEBAR_COLUMN_SELECTOR = ":is([data-pane='sidebar'], [class*='sidebarCol'])"
export const SETTINGS_TRIGGER_SELECTOR = "[data-slot='sidebar.settings'] > :is(button, [role='button'])"
export const WORKSPACE_REGION_SELECTOR = "[data-slot='sidebar.workspaces']"
/** 过滤/排序触发按钮（spike 定位，写实测选择器） */
export const FILTER_TRIGGER_SELECTOR = '<spike 实测值>'
/** ＋新建工作区触发按钮（spike 定位，写实测选择器） */
export const ADD_WORKSPACE_TRIGGER_SELECTOR = '<spike 实测值>'
```

- [ ] **Step 5: 写 NOTES §8 并提交**

```bash
git add dsh-platform/NOTES.md dsh-platform/packages/server-connector/src/client/selectors.ts
git commit -m "docs: dsh client capability spike for sidebar merge"
```

---

### Task 2: client 入口打包链路（esbuild + module-loader 信封）

**Files:**
- Modify: `dsh-platform/packages/server-connector/package.json`
- Create: `dsh-platform/packages/server-connector/build-client.mjs`
- Create: `dsh-platform/packages/server-connector/src/client/index.ts`（骨架：body 标记）
- Test: `dsh-platform/packages/server-connector/tests/client-build.test.ts`

**Interfaces:**
- Produces: `lib/client.js`（信封产物，T3-T5 的代码都会被打进去）；`package.json` 的 `dsh.client` 声明

- [ ] **Step 1: 写失败测试（校验构建产物信封）**

```ts
// tests/client-build.test.ts
import { execSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('client bundle envelope', () => {
  it('builds lib/client.js wrapped in the dsh module loader envelope', () => {
    execSync('node build-client.mjs', { cwd: process.cwd(), stdio: 'pipe' })
    const out = readFileSync('lib/client.js', 'utf8')
    expect(out).toContain("window.__ModuleLoader__.load({")
    expect(out).toContain("id: '@naoker/dsh-platform-connector'")
    expect(out).toContain('factory: (require) =>')
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd dsh-platform/packages/server-connector && npx vitest run tests/client-build.test.ts`
Expected: FAIL（build-client.mjs 不存在）

- [ ] **Step 3: 实现构建脚本**

```js
// build-client.mjs —— 把 src/client/index.ts 打成 DSH client 插件信封
import { build } from 'esbuild'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'

const EXTERNAL = [
  'react', 'react/jsx-runtime',
  '@deepseek-ai/cordis',
  '@deepseek-ai/dsh-client-runtime',
  '@deepseek-ai/dsh-client-runtime/client',
  '@deepseek-ai/dsh-client-ui-slots',
  '@deepseek-ai/dsh-client-connection',
  '@deepseek-ai/dsh-client-locale',
]

mkdirSync('lib', { recursive: true })
await build({
  entryPoints: ['src/client/index.ts'],
  bundle: true,
  format: 'cjs',
  platform: 'browser',
  target: 'es2022',
  outfile: 'lib/client.body.js',
  external: EXTERNAL,
  jsx: 'automatic',
  define: { 'process.env.NODE_ENV': '"production"' },
})

const body = readFileSync('lib/client.body.js', 'utf8')
const wrapped = [
  'window.__ModuleLoader__.load({',
  "  id: '@naoker/dsh-platform-connector',",
  '  factory: (require) => {',
  '    var module = { exports: {} }; var exports = module.exports;',
  body,
  '    return module.exports;',
  '  },',
  '});',
  '',
].join('\n')
writeFileSync('lib/client.js', wrapped)
console.log('lib/client.js written')
```

- [ ] **Step 4: 骨架入口 + package.json 声明**

```ts
// src/client/index.ts
import type { Context } from '@deepseek-ai/cordis'

export const name = 'naoker-platform-nav'

/** Client 插件：把 DSH 原生侧栏与平台侧栏合并所需的最小入口（body 标记先行）。 */
export function apply(ctx: Context): void {
  document.body.setAttribute('data-naoker-nav', '1')
  ctx.effect(() => () => { document.body.removeAttribute('data-naoker-nav') }, 'naoker-nav: body marker')
}
```

package.json 三处修改：
```json
"exports": {
  ".": "./lib/index.js",
  "./client": "./lib/client.js",
  "./cordis.patch.yml": "./cordis.patch.yml",
  "./package.json": "./package.json"
},
"dsh": {
  "bundle": { "patch": "./cordis.patch.yml" },
  "client": { "inject": ["@deepseek-ai/dsh-client-runtime", "@deepseek-ai/dsh-client-ui-slots"], "platform": "web" }
},
"files": ["lib/index.js", "lib/client.js", "cordis.patch.yml"]
```
devDependencies 增加：`"esbuild": "^0.25.0"`、`"jsdom": "29.1.1"`、`"@types/react": "^18.2.0"`、`"react": "^18.2.0"`（仅类型/测试用）。

- [ ] **Step 5: 跑测试至绿 + 安装冒烟**

Run: `npx vitest run tests/client-build.test.ts` → PASS
Run: `pnpm install && npm run build` → `lib/index.js` 与 `lib/client.js` 都在
Run（真实实例）：`$env:DSH_HOME="C:\01_agent_loop_pro\backend\var\dsh\4c40bada-b2e6-45ea-b1b2-a2e43e663072"; dsh plugin --profile web add C:\01_agent_loop_pro\dsh-platform\packages\server-connector`
浏览器打开 `http://127.0.0.1:3163/`，DevTools 执行 `document.body.dataset.naokerNav` → 应为 `"1"`；无则看 Console 报错并在 NOTES §8 记录。

- [ ] **Step 6: 提交**

```bash
git add dsh-platform/packages/server-connector/package.json dsh-platform/packages/server-connector/build-client.mjs dsh-platform/packages/server-connector/src/client/index.ts dsh-platform/packages/server-connector/tests/client-build.test.ts dsh-platform/packages/server-connector/lib/client.js dsh-platform/packages/server-connector/lib/client.body.js
git commit -m "feat(dsh-connector): client entry with module-loader envelope"
```
（`lib/client.body.js` 若确认无需入库可改为 .gitignore，二选一在提交说明里写清。）

---

### Task 3: 原生侧栏零宽隐藏

**Files:**
- Create: `dsh-platform/packages/server-connector/src/client/sidebar-hide.ts`
- Modify: `dsh-platform/packages/server-connector/src/client/index.ts`
- Test: `dsh-platform/packages/server-connector/tests/client-hide.test.ts`

**Interfaces:**
- Consumes: `selectors.ts` 的 `SIDEBAR_COLUMN_SELECTOR`
- Produces: `installSidebarHide(): () => void`（apply 中安装、dispose 还原）

- [ ] **Step 1: 写失败测试**

```ts
// tests/client-hide.test.ts
// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { installSidebarHide, zeroFirstTrack } from '../src/client/sidebar-hide'

describe('zeroFirstTrack', () => {
  it('zeroes the first track and keeps the rest', () => {
    expect(zeroFirstTrack('260px minmax(0, 1fr) 0px')).toBe('0px minmax(0, 1fr) 0px')
  })
  it('returns null for values it cannot parse', () => {
    expect(zeroFirstTrack('')).toBeNull()
    expect(zeroFirstTrack('none')).toBeNull()
  })
})

describe('installSidebarHide', () => {
  it('injects a zero-width rule for the native sidebar column and cleans up', () => {
    const dispose = installSidebarHide()
    const style = document.getElementById('naoker-nav-hide')
    expect(style?.textContent).toContain('width: 0 !important')
    expect(style?.textContent).toContain('overflow: hidden !important')
    dispose()
    expect(document.getElementById('naoker-nav-hide')).toBeNull()
  })

  it('zeroes the frame grid track when a column exists and restores on dispose', () => {
    const frame = document.createElement('div')
    frame.style.gridTemplateColumns = '260px minmax(0, 1fr) 0px'
    const column = document.createElement('div')
    column.className = 'pI_x6G_sidebarCol'
    frame.appendChild(column)
    document.body.appendChild(frame)
    const dispose = installSidebarHide()
    expect(frame.style.gridTemplateColumns).toBe('0px minmax(0, 1fr) 0px')
    dispose()
    expect(frame.style.gridTemplateColumns).toBe('260px minmax(0, 1fr) 0px')
    frame.remove()
  })
})
```

- [ ] **Step 2: 确认失败**

Run: `npx vitest run tests/client-hide.test.ts` → FAIL（模块不存在）

- [ ] **Step 3: 实现（按 NOTES §8.3 修正：列零宽 + frame 网格轨归零 + MutationObserver 重放）**

```ts
// src/client/sidebar-hide.ts
import { SIDEBAR_COLUMN_SELECTOR } from './selectors.ts'

const STYLE_ID = 'naoker-nav-hide'

/** 把 `grid-template-columns` 的第一轨归零；无法解析时返回 null。 */
export function zeroFirstTrack(value: string): string | null {
  const tracks = value.trim().split(/\s+/)
  if (tracks.length < 2 || tracks[0] === '' || tracks[0] === 'none') return null
  tracks[0] = '0px'
  return tracks.join(' ')
}

/**
 * 隐藏原生侧栏（NOTES §8.3）：① 列元素零宽并裁剪（保留整棵 DOM——设置面板是该列的
 * fixed 后代，display:none 会连带隐藏，且 fixed 逃逸 overflow 裁剪）；② AppFrame 的
 * 第一网格轨归零（关闭态轨宽恒为 56px，仅列零宽会残留空轨）；③ AppFrame 每次 store
 * 变化都会重写内联 style，用 MutationObserver 重放覆盖。列内触发点仍可程序化点击。
 */
export function installSidebarHide(): () => void {
  const style = document.createElement('style')
  style.id = STYLE_ID
  style.textContent = `
${SIDEBAR_COLUMN_SELECTOR} {
  width: 0 !important;
  min-width: 0 !important;
  flex: 0 0 0 !important;
  overflow: hidden !important;
  border-right: none !important;
}
`
  document.head.appendChild(style)

  const column = document.querySelector(SIDEBAR_COLUMN_SELECTOR)
  const frame = column instanceof HTMLElement ? column.parentElement : null
  let observer: MutationObserver | null = null
  let originalTracks = ''

  if (frame instanceof HTMLElement) {
    originalTracks = frame.style.gridTemplateColumns
    const replay = (): void => {
      const zeroed = zeroFirstTrack(getComputedStyle(frame).gridTemplateColumns)
      if (zeroed !== null) frame.style.gridTemplateColumns = zeroed
    }
    replay()
    observer = new MutationObserver(replay)
    observer.observe(frame, { attributes: true, attributeFilter: ['style'] })
  }

  return () => {
    style.remove()
    observer?.disconnect()
    if (frame instanceof HTMLElement) frame.style.gridTemplateColumns = originalTracks
  }
}
```

- [ ] **Step 4: 跑测试至绿 + 真实实例目测（live 验证项，见 NOTES §8.5）**

Run: `npx vitest run tests/client-hide.test.ts` → PASS
在 `http://127.0.0.1:3163/` 重新加载后：侧栏不可见、会话区铺满、无空列/接缝；点击设置按钮（DevTools 控制台执行 `document.querySelector("[data-slot='sidebar.settings'] > :is(button,[role='button'])").click()`）→ 设置面板可见；窗口缩放触发 AppFrame 重渲染后再确认无空列（验证 MutationObserver 重放）。

- [ ] **Step 5: 接入 apply + 提交**

```ts
// src/client/index.ts（在 apply 中追加）
import { installSidebarHide } from './sidebar-hide.ts'
// ...
export function apply(ctx: Context): void {
  document.body.setAttribute('data-naoker-nav', '1')
  ctx.effect(() => () => { document.body.removeAttribute('data-naoker-nav') }, 'naoker-nav: body marker')
  ctx.effect(() => installSidebarHide(), 'naoker-nav: hide native sidebar')
}
```

```bash
git add dsh-platform/packages/server-connector/src/client/sidebar-hide.ts dsh-platform/packages/server-connector/src/client/index.ts dsh-platform/packages/server-connector/tests/client-hide.test.ts dsh-platform/packages/server-connector/lib/client.js
git commit -m "feat(dsh-connector): zero-width hide of native sidebar"
```

---

### Task 4: 桥命令层（协议 + 命令分发）

**Files:**
- Create: `dsh-platform/packages/server-connector/src/client/protocol.ts`
- Create: `dsh-platform/packages/server-connector/src/client/bridge.ts`
- Test: `dsh-platform/packages/server-connector/tests/client-bridge.test.ts`

**Interfaces:**
- Consumes: `ctx.get('sessions')`、`ctx.get('workspaces')`、`selectors.ts`
- Produces: `installBridge(ctx, post): () => void`；`runCommand(ctx, cmd, post): Promise<void>`；协议类型 `DshBridgeCommand` / `DshBridgeEvent`（T5/T6 复用同构类型）

- [ ] **Step 1: 写失败测试（命令分发 + 来源校验）**

```ts
// tests/client-bridge.test.ts
// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { installBridge, runCommand } from '../src/client/bridge'

function fakeCtx() {
  const sessions = { open: vi.fn(), search: vi.fn(async () => ({ ok: true, value: { items: [{ sessionId: 's1', snippet: 'hit' }] } })) }
  const workspaces = { startSession: vi.fn() }
  return { get: (name: string) => (name === 'sessions' ? sessions : workspaces), _sessions: sessions, _workspaces: workspaces } as any
}

describe('bridge', () => {
  it('ignores messages from windows other than the parent', () => {
    const ctx = fakeCtx(); const post = vi.fn()
    const dispose = installBridge(ctx, post)
    window.dispatchEvent(Object.assign(new MessageEvent('message', { data: { v: 1, type: 'cmd', action: 'select-session', payload: { sessionId: 's1' } } }), { source: window }))
    expect(ctx._sessions.open).not.toHaveBeenCalled()
    dispose()
  })

  it('select-session opens the session', async () => {
    const ctx = fakeCtx(); const post = vi.fn()
    await runCommand(ctx, { v: 1, type: 'cmd', action: 'select-session', payload: { sessionId: 's1' } }, post)
    expect(ctx._sessions.open).toHaveBeenCalledWith('s1')
  })

  it('new-session starts a session in the given workspace', async () => {
    const ctx = fakeCtx(); const post = vi.fn()
    await runCommand(ctx, { v: 1, type: 'cmd', action: 'new-session', payload: { workspaceId: 'w1' } }, post)
    expect(ctx._workspaces.startSession).toHaveBeenCalledWith('w1')
  })

  it('search-sessions posts results back', async () => {
    const ctx = fakeCtx(); const post = vi.fn()
    await runCommand(ctx, { v: 1, type: 'cmd', action: 'search-sessions', payload: { query: 'abc' } }, post)
    expect(post).toHaveBeenCalledWith(expect.objectContaining({ event: 'search-results' }))
  })
})
```

- [ ] **Step 2: 确认失败**

Run: `npx vitest run tests/client-bridge.test.ts` → FAIL

- [ ] **Step 3: 实现 protocol.ts**

```ts
// src/client/protocol.ts —— 桥协议 v1（平台侧 frontend/src/lib/dsh-bridge.ts 同构）
export type DshBridgeAction =
  | 'new-session' | 'select-session' | 'search-sessions'
  | 'open-settings' | 'open-filter' | 'add-workspace'

export interface DshBridgeCommand {
  v: 1
  type: 'cmd'
  action: DshBridgeAction
  payload?: { sessionId?: string; workspaceId?: string; query?: string }
}

export interface DshSessionNode {
  id: string; title: string; blank: boolean; running: boolean; updatedAt: number
}

export interface DshWorkspaceGroup {
  key: string; workspaceId?: string; label: string; sessions: DshSessionNode[]
}

export interface DshNavState {
  currentSessionId?: string
  groups: DshWorkspaceGroup[]
}

export type DshBridgeEvent =
  | { v: 1; type: 'state'; event: 'ready'; payload: { currentSessionId?: string } }
  | { v: 1; type: 'state'; event: 'nav'; payload: DshNavState }
  | { v: 1; type: 'state'; event: 'search-results'; payload: { query: string; items: { id: string; snippet: string }[] } }
  | { v: 1; type: 'state'; event: 'connection'; payload: { connected: boolean; attempt?: number } }
```

- [ ] **Step 4: 实现 bridge.ts**

```ts
// src/client/bridge.ts
import type { Context } from '@deepseek-ai/cordis'
import type { DshBridgeCommand, DshBridgeEvent } from './protocol.ts'
import { ADD_WORKSPACE_TRIGGER_SELECTOR, FILTER_TRIGGER_SELECTOR, SETTINGS_TRIGGER_SELECTOR } from './selectors.ts'

export type BridgePost = (event: DshBridgeEvent) => void

function clickTrigger(selector: string): void {
  const el = document.querySelector<HTMLElement>(selector)
  if (el === null) { console.warn('[naoker-nav] trigger not found:', selector); return }
  el.click()
}

export async function runCommand(ctx: Context, cmd: DshBridgeCommand, post: BridgePost): Promise<void> {
  const sessions = ctx.get('sessions') as {
    open(id: string): void
    search(query: string): Promise<{ ok: boolean; value?: { items: { sessionId: string; snippet: string }[] } }>
  }
  const workspaces = ctx.get('workspaces') as { startSession(workspaceId?: string): void }
  switch (cmd.action) {
    case 'select-session':
      if (cmd.payload?.sessionId) sessions.open(cmd.payload.sessionId)
      return
    case 'new-session':
      workspaces.startSession(cmd.payload?.workspaceId)
      return
    case 'search-sessions': {
      const query = cmd.payload?.query ?? ''
      const result = await sessions.search(query)
      const items = result.ok && result.value ? result.value.items.map(i => ({ id: i.sessionId, snippet: i.snippet })) : []
      post({ v: 1, type: 'state', event: 'search-results', payload: { query, items } })
      return
    }
    case 'open-settings':
      clickTrigger(SETTINGS_TRIGGER_SELECTOR)
      return
    case 'open-filter':
      clickTrigger(FILTER_TRIGGER_SELECTOR)
      return
    case 'add-workspace':
      clickTrigger(ADD_WORKSPACE_TRIGGER_SELECTOR)
      return
  }
}

/** 监听父窗口命令（只接受 window.parent 的来源），返回卸载函数。 */
export function installBridge(ctx: Context, post: BridgePost): () => void {
  const onMessage = (event: MessageEvent): void => {
    if (event.source !== window.parent) return
    const data = event.data as Partial<DshBridgeCommand> | null
    if (data === null || typeof data !== 'object' || data.v !== 1 || data.type !== 'cmd') return
    void runCommand(ctx, data as DshBridgeCommand, post)
  }
  window.addEventListener('message', onMessage)
  return () => { window.removeEventListener('message', onMessage) }
}
```

- [ ] **Step 5: 跑测试至绿 + 提交**

Run: `npx vitest run tests/client-bridge.test.ts` → PASS（4 个）

```bash
git add dsh-platform/packages/server-connector/src/client/protocol.ts dsh-platform/packages/server-connector/src/client/bridge.ts dsh-platform/packages/server-connector/tests/client-bridge.test.ts dsh-platform/packages/server-connector/lib/client.js
git commit -m "feat(dsh-connector): postMessage bridge command layer"
```

---

### Task 5: 数据观察与上行推送

**Files:**
- Create: `dsh-platform/packages/server-connector/src/client/data.ts`
- Create: `dsh-platform/packages/server-connector/src/client/observer.tsx`
- Modify: `dsh-platform/packages/server-connector/src/client/index.ts`
- Test: `dsh-platform/packages/server-connector/tests/client-data.test.ts`

**Interfaces:**
- Consumes: 框架注入的 `useSessions` / `useWorkspaces` hooks（槽组件 props）；`DshNavState`（Task 4）
- Produces: `buildNavState(sessions, workspaces, archivedIds, currentId): DshNavState`；`createNavObserver(post)` 返回可注册的 React 组件；`installObserver(ctx, post): () => void`

- [ ] **Step 1: 写失败测试（分组/标题/相对时间字段）**

```ts
// tests/client-data.test.ts
import { describe, expect, it } from 'vitest'
import { buildNavState } from '../src/client/data'

describe('buildNavState', () => {
  it('groups sessions by workspace order and drops blank non-current sessions', () => {
    const sessions = {
      ids: ['s1', 's2', 's3'], current: 's1',
      byId: {
        s1: { id: 's1', displayTitle: 'New Session', blank: true, running: true, updatedAt: 100 },
        s2: { id: 's2', displayTitle: '方案 A', blank: false, running: false, updatedAt: 200 },
        s3: { id: 's3', displayTitle: '方案 B', blank: false, running: false, updatedAt: 300 },
      },
    }
    const workspaces = [{ workspaceId: 'w1', title: 'HC_ZiChan', sessionIds: ['s2', 's1'] }]
    const nav = buildNavState(sessions as any, workspaces as any, [], 's1')
    expect(nav.currentSessionId).toBe('s1')
    expect(nav.groups).toHaveLength(1)
    expect(nav.groups[0].label).toBe('HC_ZiChan')
    expect(nav.groups[0].sessions.map(s => s.id)).toEqual(['s2', 's1'])
    expect(nav.groups[0].sessions[1]).toMatchObject({ id: 's1', blank: true, running: true })
  })

  it('trails ungrouped sessions newest-first', () => {
    const sessions = {
      ids: ['s1', 's2'], current: undefined,
      byId: {
        s1: { id: 's1', displayTitle: '老会话', blank: false, running: false, updatedAt: 100 },
        s2: { id: 's2', displayTitle: '新会话', blank: false, running: false, updatedAt: 300 },
      },
    }
    const nav = buildNavState(sessions as any, [], [], undefined)
    expect(nav.groups.map(g => g.label)).toEqual(['Ungrouped'])
    expect(nav.groups[0].sessions.map(s => s.id)).toEqual(['s2', 's1'])
  })
})
```

- [ ] **Step 2: 确认失败**

Run: `npx vitest run tests/client-data.test.ts` → FAIL

- [ ] **Step 3: 实现 data.ts**

```ts
// src/client/data.ts —— 镜像 ui-workspace/src/client/tree.ts 的分组语义（子集）
import type { DshNavState, DshSessionNode, DshWorkspaceGroup } from './protocol.ts'

interface SessionLike {
  id: string; displayTitle: string; blank: boolean; running: boolean; updatedAt: number
  origin?: string; cwd?: string
}
interface SessionListLike { ids: readonly string[]; byId: Record<string, SessionLike | undefined>; current?: string }
interface WorkspaceLike { workspaceId: string; title: string; sessionIds: readonly string[] }

const UNGROUPED = 'Ungrouped'

function visible(s: SessionLike, current: string | undefined, archived: ReadonlySet<string>): boolean {
  return s.origin !== 'subagent' && !archived.has(s.id) && (!s.blank || s.id === current)
}

function node(s: SessionLike): DshSessionNode {
  return { id: s.id, title: s.blank ? 'New Session' : s.displayTitle, blank: s.blank, running: s.running, updatedAt: s.updatedAt }
}

/** 工作区分组（Host 顺序 + sessionIds 成员序）；未归属会话按最近更新排在最后。 */
export function buildNavState(
  list: SessionListLike,
  workspaces: readonly WorkspaceLike[],
  archivedIds: readonly string[],
  currentId: string | undefined,
): DshNavState {
  const archived = new Set(archivedIds)
  const groups: DshWorkspaceGroup[] = []
  const accounted = new Set<string>()
  for (const w of workspaces) {
    const members: SessionLike[] = []
    for (const id of w.sessionIds) {
      const s = list.byId[id]
      if (s === undefined) continue
      accounted.add(id)
      if (!visible(s, currentId, archived)) continue
      members.push(s)
    }
    groups.push({ key: w.workspaceId, workspaceId: w.workspaceId, label: w.title, sessions: members.map(node) })
  }
  const stray = list.ids
    .map(id => list.byId[id])
    .filter((s): s is SessionLike => s !== undefined && !accounted.has(s.id) && visible(s, currentId, archived))
    .sort((a, b) => b.updatedAt - a.updatedAt)
  if (stray.length > 0) {
    groups.push({ key: '', label: UNGROUPED, sessions: stray.map(node) })
  }
  return currentId === undefined ? { groups } : { currentSessionId: currentId, groups }
}
```

- [ ] **Step 4: 实现 observer.tsx（React 观察组件）**

```tsx
// src/client/observer.tsx
import { useEffect } from 'react'
import { buildNavState } from './data.ts'
import type { DshBridgeEvent } from './protocol.ts'
import type { Context } from '@deepseek-ai/cordis'

type SessionList = Parameters<typeof buildNavState>[0]
type Workspaces = Parameters<typeof buildNavState>[1]

/** 槽组件 props：框架注入全局 hooks（见 ui-workspace WorkspaceBrowserProps）。 */
interface ObserverProps {
  useSessions: (selector: (state: SessionList) => SessionList) => SessionList
  useWorkspaces: (selector: (state: { items: Workspaces; archivedSessionIds: readonly string[] }) => { items: Workspaces; archivedSessionIds: readonly string[] }) => { items: Workspaces; archivedSessionIds: readonly string[] }
}

export function createNavObserver(post: (event: DshBridgeEvent) => void) {
  return function NavObserver(props: ObserverProps) {
    const list = props.useSessions(s => s)
    const ws = props.useWorkspaces(s => s)
    useEffect(() => {
      post({ v: 1, type: 'state', event: 'nav', payload: buildNavState(list, ws.items, ws.archivedSessionIds, list.current) })
    }, [list, ws])
    return null
  }
}

/** 注册观察组件到 root 级槽（返回卸载函数）。槽名以 Task 1 spike 结论为准。 */
export function installObserver(ctx: Context, post: (event: DshBridgeEvent) => void): () => void {
  const slots = ctx.get('slots') as { inject(hole: string, cb: () => unknown): unknown }
  const dispose = slots.inject('shell.overlay', () =>
    (ctx.get('slots') as any).register({ name: 'shell.overlay' }, createNavObserver(post)),
  )
  return () => { (dispose as unknown as () => void)?.() }
}
```

- [ ] **Step 5: 接入 apply（bridge + observer + ready 事件）**

```ts
// src/client/index.ts 追加
import { installBridge } from './bridge.ts'
import { installObserver } from './observer.tsx'
import type { DshBridgeEvent } from './protocol.ts'

export function apply(ctx: Context): void {
  document.body.setAttribute('data-naoker-nav', '1')
  const post = (event: DshBridgeEvent): void => { window.parent.postMessage(event, '*') }
  ctx.effect(() => () => { document.body.removeAttribute('data-naoker-nav') }, 'naoker-nav: body marker')
  ctx.effect(() => installSidebarHide(), 'naoker-nav: hide native sidebar')
  ctx.effect(() => installBridge(ctx, post), 'naoker-nav: bridge')
  ctx.effect(() => installObserver(ctx, post), 'naoker-nav: observer')
  window.setTimeout(() => { post({ v: 1, type: 'state', event: 'ready', payload: {} }) }, 0)
}
```

- [ ] **Step 6: 跑测试至绿 + 真实实例验证 + 提交**

Run: `npx vitest run` → 全绿（含前 3 个任务测试）
真实实例验证：重新 build + 重新加载页面，在平台页 Console 执行
```js
window.addEventListener('message', e => console.log('BRIDGE', e.data)); 
document.querySelector('iframe').contentWindow.postMessage({ v: 1, type: 'cmd', action: 'new-session' }, '*')
```
应看到 `BRIDGE {type:'state', event:'nav', ...}` 与新建会话生效。

```bash
git add dsh-platform/packages/server-connector/src/client/data.ts dsh-platform/packages/server-connector/src/client/observer.tsx dsh-platform/packages/server-connector/src/client/index.ts dsh-platform/packages/server-connector/tests/client-data.test.ts dsh-platform/packages/server-connector/lib/client.js
git commit -m "feat(dsh-connector): nav data observer + state push"
```

---

### Task 6: 平台侧桥 hook 与 store

**Files:**
- Create: `frontend/src/lib/dsh-bridge.ts`
- Create: `frontend/src/lib/dsh-bridge-store.ts`
- Test: `frontend/src/lib/dsh-bridge.test.ts`

**Interfaces:**
- Consumes: `DshBridgeCommand` / `DshBridgeEvent` / `DshNavState`（与插件 protocol.ts 同构，复制一份到前端）
- Produces: `useDshBridge(iframeRef)`；`dshBridgeStore`（`publishNav/publishConnection/publishSearchResults/send/getState/subscribe`，模式对齐 `agent-session-store.ts`）

- [ ] **Step 1: 写失败测试（source 校验 + 状态更新）**

```ts
// frontend/src/lib/dsh-bridge.test.ts
import { renderHook, act } from "@testing-library/react";
import { useRef } from "react";
import { describe, expect, it, vi } from "vitest";
import { useDshBridge } from "./dsh-bridge";

function makeIframe() {
  const iframe = document.createElement("iframe");
  document.body.appendChild(iframe);
  return iframe;
}

describe("useDshBridge", () => {
  it("ignores messages from other sources and applies nav from the iframe", () => {
    const iframe = makeIframe();
    const ref = { current: iframe } as React.RefObject<HTMLIFrameElement | null>;
    const { result } = renderHook(() => useDshBridge(ref));
    act(() => {
      window.dispatchEvent(Object.assign(new MessageEvent("message", { data: { v: 1, type: "state", event: "nav", payload: { groups: [] } } }), { source: window }));
    });
    expect(result.current.nav).toBeNull();
    act(() => {
      window.dispatchEvent(Object.assign(new MessageEvent("message", { data: { v: 1, type: "state", event: "nav", payload: { groups: [] } } }), { source: iframe.contentWindow }));
    });
    expect(result.current.nav).toEqual({ groups: [] });
  });

  it("send posts a v1 command to the iframe", () => {
    const iframe = makeIframe();
    const post = vi.spyOn(iframe.contentWindow as Window, "postMessage");
    const ref = { current: iframe } as React.RefObject<HTMLIFrameElement | null>;
    const { result } = renderHook(() => useDshBridge(ref));
    act(() => { result.current.send({ v: 1, type: "cmd", action: "new-session" }); });
    expect(post).toHaveBeenCalledWith({ v: 1, type: "cmd", action: "new-session" }, "*");
  });
});
```

- [ ] **Step 2: 确认失败**

Run: `cd frontend && npm test -- --run src/lib/dsh-bridge.test.ts` → FAIL

- [ ] **Step 3: 实现 dsh-bridge.ts（协议类型 + hook）**

```ts
// frontend/src/lib/dsh-bridge.ts
"use client";

import { useCallback, useEffect, useState } from "react";

export type DshBridgeAction =
  | "new-session" | "select-session" | "search-sessions"
  | "open-settings" | "open-filter" | "add-workspace";

export interface DshBridgeCommand {
  v: 1;
  type: "cmd";
  action: DshBridgeAction;
  payload?: { sessionId?: string; workspaceId?: string; query?: string };
}

export interface DshSessionNode {
  id: string; title: string; blank: boolean; running: boolean; updatedAt: number;
}

export interface DshWorkspaceGroup {
  key: string; workspaceId?: string; label: string; sessions: DshSessionNode[];
}

export interface DshNavState {
  currentSessionId?: string;
  groups: DshWorkspaceGroup[];
}

export interface DshSearchResults {
  query: string;
  items: { id: string; snippet: string }[];
}

export interface DshConnectionState { connected: boolean; attempt: number }

export function useDshBridge(iframeRef: React.RefObject<HTMLIFrameElement | null>) {
  const [nav, setNav] = useState<DshNavState | null>(null);
  const [connection, setConnection] = useState<DshConnectionState>({ connected: false, attempt: 0 });
  const [searchResults, setSearchResults] = useState<DshSearchResults | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    function onMessage(event: MessageEvent) {
      const frame = iframeRef.current;
      if (!frame || event.source !== frame.contentWindow) return;
      const data = event.data as { v?: number; type?: string; event?: string; payload?: unknown } | null;
      if (!data || data.v !== 1 || data.type !== "state") return;
      if (data.event === "ready") { setReady(true); setConnection({ connected: true, attempt: 0 }); return; }
      if (data.event === "nav") { setNav(data.payload as DshNavState); return; }
      if (data.event === "search-results") { setSearchResults(data.payload as DshSearchResults); return; }
      if (data.event === "connection") {
        const p = data.payload as { connected?: boolean; attempt?: number } | undefined;
        setConnection({ connected: p?.connected === true, attempt: p?.attempt ?? 0 });
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [iframeRef]);

  const send = useCallback((cmd: DshBridgeCommand) => {
    iframeRef.current?.contentWindow?.postMessage(cmd, "*");
  }, [iframeRef]);

  return { nav, connection, searchResults, ready, send };
}
```

- [ ] **Step 4: 实现 dsh-bridge-store.ts（供 AppSidebar 跨组件订阅）**

```ts
// frontend/src/lib/dsh-bridge-store.ts —— 模式对齐 agent-session-store.ts
import type { DshBridgeCommand, DshConnectionState, DshNavState, DshSearchResults } from "./dsh-bridge";

interface DshBridgeSnapshot {
  nav: DshNavState | null;
  connection: DshConnectionState;
  searchResults: DshSearchResults | null;
  ready: boolean;
}

let snapshot: DshBridgeSnapshot = { nav: null, connection: { connected: false, attempt: 0 }, searchResults: null, ready: false };
const listeners = new Set<() => void>();
let sender: ((cmd: DshBridgeCommand) => void) | null = null;

function emit() { for (const listener of listeners) listener(); }

export const dshBridgeStore = {
  getSnapshot: (): DshBridgeSnapshot => snapshot,
  subscribe(listener: () => void): () => void { listeners.add(listener); return () => listeners.delete(listener); },
  publish(partial: Partial<DshBridgeSnapshot>): void { snapshot = { ...snapshot, ...partial }; emit(); },
  reset(): void { snapshot = { nav: null, connection: { connected: false, attempt: 0 }, searchResults: null, ready: false }; sender = null; emit(); },
  setSender(fn: ((cmd: DshBridgeCommand) => void) | null): void { sender = fn; },
  send(cmd: DshBridgeCommand): void { sender?.(cmd); },
};
```

- [ ] **Step 5: 跑测试至绿 + 提交**

Run: `npm test -- --run src/lib/dsh-bridge.test.ts` → PASS

```bash
git add frontend/src/lib/dsh-bridge.ts frontend/src/lib/dsh-bridge-store.ts frontend/src/lib/dsh-bridge.test.ts
git commit -m "feat(frontend): dsh bridge hook + store"
```

---

### Task 7: DshNavSection 组件（工作区/会话/状态）

**Files:**
- Create: `frontend/src/components/agent/dsh-nav-section.tsx`
- Create: `frontend/src/components/agent/dsh-nav-section.test.tsx`

**Interfaces:**
- Consumes: `DshNavState` / `DshConnectionState`（Task 6）；`dshBridgeStore.send`
- Produces: `<DshNavSection nav={...} connection={...} instanceState={...} onSend={...} />`（T8 在 AppSidebar 中渲染）

- [ ] **Step 1: 写失败测试（分组渲染/展开折叠/绿点/空态/断线态）**

```tsx
// frontend/src/components/agent/dsh-nav-section.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import DshNavSection from "./dsh-nav-section";

const NAV = {
  currentSessionId: "s2",
  groups: [
    { key: "w1", workspaceId: "w1", label: "HC_ZiChan", sessions: [
      { id: "s2", title: "方案 A", blank: false, running: true, updatedAt: Date.now() },
      { id: "s3", title: "方案 B", blank: false, running: false, updatedAt: Date.now() },
    ]},
  ],
};

describe("DshNavSection", () => {
  it("renders workspace groups, running dot and current highlight", () => {
    render(<DshNavSection nav={NAV} connection={{ connected: true, attempt: 0 }} instanceState="running" onSend={() => {}} />);
    expect(screen.getByText("HC_ZiChan")).toBeTruthy();
    expect(screen.getByText("方案 A").closest("[data-session-id]")?.getAttribute("data-current")).toBe("true");
    expect(screen.getByText("方案 A").closest("[data-session-id]")?.getAttribute("data-running")).toBe("true");
  });

  it("collapses a group on click", () => {
    render(<DshNavSection nav={NAV} connection={{ connected: true, attempt: 0 }} instanceState="running" onSend={() => {}} />);
    fireEvent.click(screen.getByText("HC_ZiChan"));
    expect(screen.queryByText("方案 A")).toBeNull();
  });

  it("clicking a session sends select-session", () => {
    const onSend = vi.fn();
    render(<DshNavSection nav={NAV} connection={{ connected: true, attempt: 0 }} instanceState="running" onSend={onSend} />);
    fireEvent.click(screen.getByText("方案 B"));
    expect(onSend).toHaveBeenCalledWith({ v: 1, type: "cmd", action: "select-session", payload: { sessionId: "s3" } });
  });

  it("shows the starting state while the instance boots", () => {
    render(<DshNavSection nav={null} connection={{ connected: false, attempt: 0 }} instanceState="starting" onSend={() => {}} />);
    expect(screen.getByText(/正在启动 DSH 实例/)).toBeTruthy();
  });

  it("shows the reconnect banner while disconnected", () => {
    render(<DshNavSection nav={NAV} connection={{ connected: false, attempt: 2 }} instanceState="running" onSend={() => {}} />);
    expect(screen.getByText(/正在自动重连/)).toBeTruthy();
  });
});
```

- [ ] **Step 2: 确认失败**

Run: `npm test -- --run src/components/agent/dsh-nav-section.test.tsx` → FAIL

- [ ] **Step 3: 实现组件（结构 + 交互；类名走 styles/agent.css 既有变量）**

```tsx
// frontend/src/components/agent/dsh-nav-section.tsx
"use client";

import { useState } from "react";
import type { DshBridgeCommand, DshConnectionState, DshNavState } from "@/lib/dsh-bridge";

interface Props {
  nav: DshNavState | null;
  connection: DshConnectionState;
  instanceState: "starting" | "running" | "stopped" | "error" | string;
  onSend: (cmd: DshBridgeCommand) => void;
}

export default function DshNavSection({ nav, connection, instanceState, onSend }: Props) {
  const [collapsed, setCollapsed] = useState<string[]>([]);
  const [searching, setSearching] = useState(false);
  const [query, setQuery] = useState("");

  if (instanceState === "starting") {
    return <div className="dsh-nav-state">◌ 正在启动 DSH 实例…（首次约 5-20 秒）</div>;
  }
  if (instanceState === "error" || instanceState === "stopped") {
    return (
      <div className="dsh-nav-state dsh-nav-state--error">
        <div>实例已停止</div>
        <button type="button" onClick={() => onSend({ v: 1, type: "cmd", action: "new-session" })}>重新启动</button>
      </div>
    );
  }
  return (
    <div className="dsh-nav" data-connected={connection.connected}>
      <div className="dsh-nav-new">
        <button type="button" onClick={() => onSend({ v: 1, type: "cmd", action: "new-session" })}>+ 新会话</button>
      </div>
      <div className="dsh-nav-header">
        <span>工作区</span>
        <span className="dsh-nav-actions">
          <button type="button" aria-label="搜索会话" onClick={() => setSearching(v => !v)}>🔍</button>
          <button type="button" aria-label="过滤" onClick={() => onSend({ v: 1, type: "cmd", action: "open-filter" })}>⚙</button>
          <button type="button" aria-label="新建工作区" onClick={() => onSend({ v: 1, type: "cmd", action: "add-workspace" })}>＋</button>
        </span>
      </div>
      {!connection.connected && (
        <div className="dsh-nav-banner">与 DSH 的连接断开，正在自动重连…（第 {connection.attempt || 1} 次）</div>
      )}
      {searching && (
        <div className="dsh-nav-search">
          <input value={query} placeholder="搜索会话…" onChange={(e) => {
            setQuery(e.target.value);
            onSend({ v: 1, type: "cmd", action: "search-sessions", payload: { query: e.target.value } });
          }} />
        </div>
      )}
      {nav === null || nav.groups.length === 0 ? (
        <div className="dsh-nav-empty">还没有会话，点上方「+ 新会话」开始第一个对话</div>
      ) : (
        nav.groups.map((group) => {
          const isCollapsed = collapsed.includes(group.key);
          return (
            <div key={group.key} className="dsh-nav-group">
              <button type="button" className="dsh-nav-group-row" onClick={() =>
                setCollapsed(prev => prev.includes(group.key) ? prev.filter(k => k !== group.key) : [...prev, group.key])
              }>{group.label}</button>
              {!isCollapsed && group.sessions.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  data-session-id={s.id}
                  data-current={s.id === nav.currentSessionId}
                  data-running={s.running}
                  className="dsh-nav-session"
                  onClick={() => onSend({ v: 1, type: "cmd", action: "select-session", payload: { sessionId: s.id } })}
                >
                  <span className="dsh-nav-session-title">{s.title}</span>
                  {s.running && <span className="dsh-nav-dot" />}
                </button>
              ))}
            </div>
          );
        })
      )}
      <div className="dsh-nav-settings">
        <button type="button" onClick={() => onSend({ v: 1, type: "cmd", action: "open-settings" })}>⚙ DSH 设置</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 跑测试至绿 + 提交**

Run: `npm test -- --run src/components/agent/dsh-nav-section.test.tsx` → PASS（5 个）

```bash
git add frontend/src/components/agent/dsh-nav-section.tsx frontend/src/components/agent/dsh-nav-section.test.tsx
git commit -m "feat(frontend): dsh nav section component"
```

---

### Task 8: AppSidebar 集成 + 深链 + 路由分流

**Files:**
- Modify: `frontend/src/components/dsh/dsh-workspace.tsx`（iframe ref + bridge 接入 + `?session=` 恢复 + replaceState）
- Modify: `frontend/src/components/layout/app-sidebar.tsx`（`/agent` 渲染 `DshNavSection`；`/agent/legacy` 保留 `SessionSidebarList`；其它路由不渲染会话区）
- Modify: `frontend/src/components/layout/app-shell.test.tsx` 或对应既有测试
- Test: `frontend/src/components/layout/app-sidebar.test.tsx`（新建或扩展）

**Interfaces:**
- Consumes: Task 6 store/hook、Task 7 组件、现有 `useSearchParams`
- Produces: 完整路由分流行为

- [ ] **Step 1: 写失败测试（分流 + 深链）**

```tsx
// frontend/src/components/layout/app-sidebar.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AppSidebar from "./app-sidebar";

const USER = { id: "u1", username: "admin", display_name: "管理员", roles: [], permissions: [], menu_permissions: [] } as any;

vi.mock("next/navigation", () => ({ usePathname: () => "/agent", useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/auth", () => ({ fetchCurrentUser: async () => USER }));

describe("AppSidebar route split", () => {
  it("renders the DSH nav section on /agent and not the legacy list", () => {
    render(<AppSidebar user={USER} />);
    expect(screen.getByText("+ 新会话")).toBeTruthy();
    expect(screen.queryByText(/加载会话/)).toBeNull();
  });
});
```

- [ ] **Step 2: 确认失败** → Run: `npm test -- --run src/components/layout/app-sidebar.test.tsx` → FAIL

- [ ] **Step 3: 实现 AppSidebar 分流**

在 `app-sidebar.tsx` 中：
```tsx
import DshNavSection from "@/components/agent/dsh-nav-section";
import { dshBridgeStore } from "@/lib/dsh-bridge-store";
// ...
const isLegacyRoute = pathname.startsWith("/agent/legacy");
const isAgentRoute = pathname === "/agent" || (pathname.startsWith("/agent/") && !isLegacyRoute && !pathname.startsWith("/agent/sessions/"));
// 订阅 store（useSyncExternalStore）
const bridge = useSyncExternalStore(dshBridgeStore.subscribe, dshBridgeStore.getSnapshot, dshBridgeStore.getSnapshot);
// 会话区渲染：
{isLegacyRoute ? (
  <SessionSidebarList ... />   // 现有旧列表原样保留
) : isAgentRoute ? (
  <DshNavSection
    nav={bridge.nav}
    connection={bridge.connection}
    instanceState={instanceState}          // 来自现有 /api/dsh/instances/me 轮询（把轮询提到 store 或在本组件保留）
    onSend={dshBridgeStore.send}
  />
) : null}
```

- [ ] **Step 4: 实现 DshWorkspace 的桥接入与深链**

在 `dsh-workspace.tsx` 中：
```tsx
const iframeRef = useRef<HTMLIFrameElement>(null);
const { nav, connection, searchResults, ready, send } = useDshBridge(iframeRef);
const searchParams = useSearchParams();
// 把桥状态写入 store 供 AppSidebar 使用
useEffect(() => {
  dshBridgeStore.setSender(send);
  return () => dshBridgeStore.setSender(null);
}, [send]);
useEffect(() => { dshBridgeStore.publish({ nav, connection, searchResults, ready }); }, [nav, connection, searchResults, ready]);
// ready 后恢复深链选中
useEffect(() => {
  if (!ready) return;
  const target = searchParams.get("session");
  if (target) send({ v: 1, type: "cmd", action: "select-session", payload: { sessionId: target } });
}, [ready, searchParams, send]);
// 当前会话变化时同步 URL（replaceState，避免触发路由重渲染）
useEffect(() => {
  if (!nav?.currentSessionId) return;
  const url = new URL(window.location.href);
  if (url.searchParams.get("session") !== nav.currentSessionId) {
    url.searchParams.set("session", nav.currentSessionId);
    window.history.replaceState(null, "", url);
  }
}, [nav?.currentSessionId]);
// iframe 加 ref
<iframe ref={iframeRef} ... />
```

- [ ] **Step 5: 跑测试至绿 + 回归 + 提交**

Run: `npm test -- --run`（前端全量，确认 legacy/agent 相关测试不回归）
Run: 真实环境手测——`/agent` 只有平台侧栏、DSH 原生侧栏不可见；点击会话切换；刷新后 URL 带 `?session=` 且自动恢复。

```bash
git add frontend/src/components/dsh/dsh-workspace.tsx frontend/src/components/layout/app-sidebar.tsx frontend/src/components/layout/app-sidebar.test.tsx
git commit -m "feat(frontend): merge dsh nav into app sidebar with deep link"
```

---

### Task 9: 视觉打磨（按视觉稿规格）

**Files:**
- Modify: `frontend/src/app/globals.css`（或既有 agent 样式文件，追加 `.dsh-nav*` 规则）
- Test: 现有测试全绿（样式无单测，以真实页面对照视觉稿）

- [ ] **Step 1: 按视觉规范实现样式（与 states-v5 / layout-merge-v4 稿一致）**

```css
.dsh-nav { display: flex; flex-direction: column; min-height: 0; }
.dsh-nav-new button {
  width: 100%; padding: 9px 12px; border-radius: 10px; border: none; cursor: pointer;
  background: #fff; color: #E85D04; font-weight: 600;
}
.dsh-nav-header { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px 6px; font-size: 12px; letter-spacing: 1px; }
.dsh-nav-actions button { background: transparent; border: none; color: inherit; cursor: pointer; margin-left: 8px; }
.dsh-nav-banner { margin: 0 10px 8px; padding: 7px 10px; border-radius: 9px; background: #92400E; border: 1px solid #FCD34D; font-size: 11px; }
.dsh-nav-session { display: flex; align-items: center; width: 100%; padding: 7px 14px; background: transparent; border: none; color: inherit; text-align: left; cursor: pointer; }
.dsh-nav-session:hover { background: rgba(255,255,255,.12); }
.dsh-nav-session[data-current="true"] { background: rgba(255,255,255,.22); border-left: 3px solid #fff; font-weight: 600; }
.dsh-nav-session-title { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dsh-nav-dot { width: 6px; height: 6px; border-radius: 50%; background: #7CFFB2; margin-left: 6px; }
.dsh-nav-group-row { width: 100%; text-align: left; padding: 7px 14px; background: rgba(255,255,255,.18); border: none; color: inherit; border-radius: 8px; cursor: pointer; }
.dsh-nav-settings { border-top: 1px solid rgba(255,255,255,.25); margin-top: 4px; }
.dsh-nav-settings button { width: 100%; text-align: left; padding: 8px 14px; background: transparent; border: none; color: inherit; cursor: pointer; }
.dsh-nav-state { padding: 14px; opacity: .9; }
.dsh-nav-state--error { background: #7F1D1D; border: 1px solid #FCA5A5; border-radius: 9px; margin: 0 10px; }
```

- [ ] **Step 2: 真实页面对照视觉稿逐项核验**

对照 `.superpowers/brainstorm/ui-merge-01/content/layout-merge-v4.html` 与 `states-v5.html`：品牌区、新会话、工作区头（3 动作）、分组、选中态、绿点、DSH 设置位置（角色管理下方）、账号区；A-E 五种状态逐一触发验证。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/app/globals.css
git commit -m "style(frontend): dsh nav section polish per approved mockups"
```

---

### Task 10: 端到端验收与回归

**Files:**
- Create: `docs/verification/dsh-sidebar-merge-checklist.md`
- Modify: `scripts/dsh_smoke.ps1`（追加侧栏合并冒烟项，可选）

- [ ] **Step 1: 写验收清单（8 条手测，来自 spec §6）**

```markdown
# DSH 侧栏合并 · 验收清单
1. /agent：仅一个侧栏；DSH 原生侧栏不可见；品牌=脑壳工作台
2. 工作区列表与会话（标题+相对时间）与 DSH 原版一致（对照 DSH 独立打开）
3. 点击会话 → 右侧切换；运行中绿点正确
4. 新会话 / 搜索 / 过滤 / ＋新建工作区 / DSH 设置 全部可用（设置面板可见）
5. 刷新 → 自动恢复上次会话（URL 带 ?session=）
6. 重建实例（状态条）→ A→E 流转；会话不丢
7. /agent/legacy：旧列表与旧界面正常
8. 其它页面（/users 等）：无会话区，功能菜单正常
```

- [ ] **Step 2: 全量回归**

Run: `cd dsh-platform/packages/server-connector && npx vitest run` → 全绿
Run: `cd frontend && npm test -- --run` → 全绿
Run: `cd backend && X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_dsh_*.py -q` → 全绿（后端未改，确认无回归）

- [ ] **Step 3: 逐条执行验收清单（真实浏览器）并记录结果**

每条记录：通过/失败 + 截图或现象；失败项开修复提交（同一任务内闭环）。

- [ ] **Step 4: 提交**

```bash
git add docs/verification/dsh-sidebar-merge-checklist.md scripts/dsh_smoke.ps1
git commit -m "docs: dsh sidebar merge acceptance checklist + smoke"
```

---

## Self-Review

- **Spec coverage**：结构①-⑥（T7/T8/T9）；功能映射 8 项（T4 命令 + T5 数据 + T9 位置）；交互规则（T7/T8）；5 状态（T7 测试 + T9 核验）；深链（T8）；legacy 保留（T8）；视觉规范（T9）；spike 4 项（T1）；验收（T10）。无缺口。
- **Placeholder scan**：T1 Step 4 的 `<spike 实测值>` 是 Task 1 的交付物本身（先行任务），非计划占位；其余步骤均含完整代码。
- **Type consistency**：`DshBridgeCommand/DshBridgeEvent/DshNavState` 在插件 `protocol.ts` 与前端 `dsh-bridge.ts` 中同构复制（两端独立工程，类型不可共享，已在两处完整定义）；`buildNavState` 签名在 T5 定义、T5 测试与 observer 调用一致；`dshBridgeStore` 方法在 T6 定义、T7/T8 使用一致。
