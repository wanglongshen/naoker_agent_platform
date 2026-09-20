// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { installBridge, runCommand } from '../src/client/bridge.ts'
import type { DshBridgeCommand } from '../src/client/protocol.ts'

function fakeCtx() {
  const sessions = { open: vi.fn(), search: vi.fn(async () => ({ ok: true, value: { items: [{ sessionId: 's1', snippet: 'hit' }] } })) }
  const workspaces = { startSession: vi.fn() }
  return { get: (name: string) => (name === 'sessions' ? sessions : workspaces), _sessions: sessions, _workspaces: workspaces } as any
}

/** jsdom 29 的 MessageEvent#source 是只读 getter，不能用 Object.assign 覆写。 */
function messageFrom(source: unknown, data: DshBridgeCommand): MessageEvent {
  const event = new MessageEvent('message', { data })
  Object.defineProperty(event, 'source', { value: source })
  return event
}

describe('bridge', () => {
  it('ignores messages from windows other than the parent', () => {
    const ctx = fakeCtx(); const post = vi.fn()
    const dispose = installBridge(ctx, post)
    window.dispatchEvent(messageFrom({ not: 'the parent' }, { v: 1, type: 'cmd', action: 'select-session', payload: { sessionId: 's1' } }))
    expect(ctx._sessions.open).not.toHaveBeenCalled()
    dispose()
  })

  it('handles commands coming from the parent window', () => {
    const ctx = fakeCtx(); const post = vi.fn()
    const dispose = installBridge(ctx, post)
    window.dispatchEvent(messageFrom(window.parent, { v: 1, type: 'cmd', action: 'select-session', payload: { sessionId: 's1' } }))
    expect(ctx._sessions.open).toHaveBeenCalledWith('s1')
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
    expect(post).toHaveBeenCalledWith({
      v: 1,
      type: 'state',
      event: 'search-results',
      payload: { query: 'abc', items: [{ id: 's1', snippet: 'hit' }] },
    })
  })
})
