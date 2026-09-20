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
