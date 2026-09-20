import { useEffect } from 'react'
import type { Context } from '@deepseek-ai/cordis'
import { buildNavState } from './data.ts'
import type { DshBridgeEvent } from './protocol.ts'

type SessionList = Parameters<typeof buildNavState>[0]
type Workspaces = Parameters<typeof buildNavState>[1]

/** 镜像框架 `SnapshotSelectorHook`：槽组件由框架按 PropsRuntime 注入全局 hooks。 */
type SelectorHook<State> = <Selected>(select: (state: State) => Selected) => Selected

interface WorkspaceState {
  items: Workspaces
  archivedSessionIds: readonly string[]
}

/** 槽组件 props：框架注入全局 hooks（见 ui-workspace WorkspaceBrowserProps）。 */
interface ObserverProps {
  useSessions: SelectorHook<SessionList>
  useWorkspaces: SelectorHook<WorkspaceState>
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

interface SlotsFace {
  inject(hole: string, callback: () => () => void): () => void
  register(options: { name: string; id: string }, component: unknown): () => void
}

/** 注册观察组件到 root 级槽（返回卸载函数）。槽名以 Task 1 spike 结论为准。 */
export function installObserver(ctx: Context, post: (event: DshBridgeEvent) => void): () => void {
  const slots = ctx.get('slots') as SlotsFace
  return slots.inject('shell.overlay', () =>
    slots.register({ name: 'shell.overlay', id: 'naoker-nav-observer' }, createNavObserver(post)),
  )
}
