/// <reference lib="dom" />
import type { Context } from '@deepseek-ai/cordis'
import { installBridge } from './bridge.ts'
// @ts-ignore: package tsconfig sets no "jsx" flag; build-client.mjs bundles with jsx automatic.
import { installObserver } from './observer.tsx'
import { installSidebarHide } from './sidebar-hide.ts'
import type { DshBridgeEvent } from './protocol.ts'

export const name = 'naoker-platform-nav'

/** Client 插件：把 DSH 原生侧栏与平台侧栏合并所需的最小入口（body 标记先行）。 */
export function apply(ctx: Context): void {
  document.body.setAttribute('data-naoker-nav', '1')
  const post = (event: DshBridgeEvent): void => { window.parent.postMessage(event, '*') }
  ctx.effect(() => () => { document.body.removeAttribute('data-naoker-nav') }, 'naoker-nav: body marker')
  ctx.effect(() => installSidebarHide(), 'naoker-nav: hide native sidebar')
  ctx.effect(() => installBridge(ctx, post), 'naoker-nav: bridge')
  ctx.effect(() => installObserver(ctx, post), 'naoker-nav: observer')
  window.setTimeout(() => { post({ v: 1, type: 'state', event: 'ready', payload: {} }) }, 0)
}
