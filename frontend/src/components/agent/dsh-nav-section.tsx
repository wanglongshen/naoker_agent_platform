"use client";

import { useState } from "react";
import type { DshBridgeCommand, DshConnectionState, DshNavState } from "@/lib/dsh-bridge";

interface Props {
  nav: DshNavState | null;
  connection: DshConnectionState;
  instanceState: "starting" | "running" | "stopped" | "error" | string;
  onSend: (cmd: DshBridgeCommand) => void;
  /** 当前是否在 /agent（iframe 所在页）；非该页时命令改为「跳到 /agent 再执行」。 */
  isDshRoute: boolean;
  onOpenAgent: (query?: { session?: string; newSession?: boolean }) => void;
}

export default function DshNavSection({
  nav,
  connection,
  instanceState,
  onSend,
  isDshRoute,
  onOpenAgent,
}: Props) {
  const [collapsed, setCollapsed] = useState<string[]>([]);
  const [searching, setSearching] = useState(false);
  const [query, setQuery] = useState("");

  const runOrOpen = (cmd: DshBridgeCommand, open?: { session?: string; newSession?: boolean }) => {
    if (isDshRoute) {
      onSend(cmd);
      return;
    }
    onOpenAgent(open);
  };

  if (instanceState === "starting") {
    return <div className="dsh-nav-state">◌ 正在启动 DSH 实例…（首次约 5-20 秒）</div>;
  }
  if (instanceState === "error" || instanceState === "stopped") {
    return (
      <div className="dsh-nav-state dsh-nav-state--error">
        <div>实例已停止</div>
        <button type="button" onClick={() => onOpenAgent()}>前往工作区</button>
      </div>
    );
  }
  return (
    <div className="dsh-nav" data-connected={connection.connected}>
      <div className="dsh-nav-new">
        <button
          type="button"
          onClick={() => runOrOpen({ v: 1, type: "cmd", action: "new-session" }, { newSession: true })}
        >
          + 新会话
        </button>
      </div>
      <div className="dsh-nav-header">
        <span>工作区</span>
        <span className="dsh-nav-actions">
          <button
            type="button"
            aria-label="搜索会话"
            onClick={() => (isDshRoute ? setSearching(v => !v) : onOpenAgent())}
          >
            🔍
          </button>
          <button
            type="button"
            aria-label="过滤"
            onClick={() => runOrOpen({ v: 1, type: "cmd", action: "open-filter" })}
          >
            ⚙
          </button>
          <button
            type="button"
            aria-label="新建工作区"
            onClick={() => runOrOpen({ v: 1, type: "cmd", action: "add-workspace" })}
          >
            ＋
          </button>
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
                  onClick={() =>
                    runOrOpen(
                      { v: 1, type: "cmd", action: "select-session", payload: { sessionId: s.id } },
                      { session: s.id },
                    )
                  }
                >
                  <span className="dsh-nav-session-title">{s.title}</span>
                  {s.running && <span className="dsh-nav-dot" />}
                </button>
              ))}
            </div>
          );
        })
      )}
    </div>
  );
}
