/// <reference lib="dom" />
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
  const sessions = ctx.get('sessions') as unknown as {
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
