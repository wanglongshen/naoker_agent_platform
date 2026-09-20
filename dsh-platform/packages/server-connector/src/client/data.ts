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
