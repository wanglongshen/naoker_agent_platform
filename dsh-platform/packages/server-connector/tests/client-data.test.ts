import { describe, expect, it, vi } from 'vitest'
import { buildNavState } from '../src/client/data'
// @ts-ignore: package tsconfig sets no "jsx" flag; build-client.mjs bundles with jsx automatic.
import { installObserver } from '../src/client/observer'

describe('buildNavState', () => {
  it('groups sessions by workspace order and drops blank non-current sessions', () => {
    const sessions = {
      ids: ['s1', 's2', 's3'], current: 's1',
      byId: {
        s1: { id: 's1', displayTitle: 'New Session', blank: true, running: true, updatedAt: 100 },
        s2: { id: 's2', displayTitle: '方案 A', blank: false, running: false, updatedAt: 200 },
        s3: { id: 's3', displayTitle: '方案 B', blank: true, running: false, updatedAt: 300 },
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

describe('installObserver', () => {
  it('waits for the shell.overlay declaration and registers a list entry', () => {
    const unregister = vi.fn()
    const injectDispose = vi.fn()
    const register = vi.fn(() => unregister)
    let declaration: (() => unknown) | undefined
    const slots = {
      inject: vi.fn((_hole: string, callback: () => unknown) => { declaration = callback; return injectDispose }),
      register,
    }
    const ctx = { get: (name: string) => (name === 'slots' ? slots : undefined) } as any
    const dispose = installObserver(ctx, vi.fn())
    expect(slots.inject).toHaveBeenCalledWith('shell.overlay', expect.any(Function))
    const cleanup = declaration?.()
    expect(register).toHaveBeenCalledWith(
      { name: 'shell.overlay', id: 'naoker-nav-observer' },
      expect.any(Function),
    )
    expect(cleanup).toBe(unregister)
    dispose()
    expect(injectDispose).toHaveBeenCalled()
  })
})
