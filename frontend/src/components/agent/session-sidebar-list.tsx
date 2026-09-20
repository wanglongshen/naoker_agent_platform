"use client";

import { useMemo, useRef, useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Dropdown, Modal, Input, App } from "antd";
import { MoreOutlined, PushpinOutlined, DeleteOutlined, EditOutlined } from "@ant-design/icons";
import type { AgentSession } from "@/types/agent";
import { agentApi } from "@/lib/agent-api";
import { invalidateAgentSessions } from "@/lib/agent-session-store";

function toGroupLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "最近";
  }
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const targetDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const daysAgo = Math.floor((startOfToday.getTime() - targetDate.getTime()) / (1000 * 60 * 60 * 24));

  if (daysAgo <= 0) return "今天";
  if (daysAgo === 1) return "昨天";
  if (daysAgo <= 7) return "7 天内";
  if (daysAgo <= 30) return "30 天内";
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

interface Props {
  sessions: AgentSession[];
  activeSessionId: string | null;
  onNavigate?: () => void;
  sessionTotal?: number;
  hasMore?: boolean;
  loadingMore?: boolean;
  onLoadMore?: () => void;
}

const GROUP_ORDER = ["今天", "昨天", "7 天内", "30 天内"];

export default function SessionSidebarList({ sessions, activeSessionId, onNavigate, sessionTotal, hasMore = false, loadingMore = false, onLoadMore }: Props) {
  const router = useRouter();
  const { message, modal } = App.useApp();
  const prefetched = useRef(new Set<string>());
  const sentinelRef = useRef<HTMLDivElement>(null);
  const [renamingSession, setRenamingSession] = useState<AgentSession | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!hasMore || !onLoadMore) return;
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          onLoadMore();
        }
      },
      { rootMargin: "100px" }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, onLoadMore, loadingMore]);

  function prefetch(sessionId: string) {
    const href = `/agent/sessions/${sessionId}`;
    if (!prefetched.current.has(href)) {
      prefetched.current.add(href);
      router.prefetch(href);
    }
  }

  const grouped = useMemo(() => {
    const buckets = new Map<string, AgentSession[]>();
    for (const s of sessions) {
      const g = toGroupLabel(s.updated_at);
      if (!buckets.has(g)) buckets.set(g, []);
      buckets.get(g)!.push(s);
    }
    const pinned = (buckets.get("今天") ?? []).filter((s) => s.is_pinned);
    const rest = [...buckets.entries()]
      .map(([group, groupSessions]) => ({ group, sessions: groupSessions, isPin: false }))
      .sort((a, b) => {
        const ia = GROUP_ORDER.indexOf(a.group);
        const ib = GROUP_ORDER.indexOf(b.group);
        if (ia === -1 && ib === -1) return a.group < b.group ? -1 : a.group > b.group ? 1 : 0;
        if (ia === -1) return 1;
        if (ib === -1) return -1;
        return ia - ib;
      });
    return [{ group: "置顶", sessions: pinned, isPin: true }, ...rest].filter((g) => g.sessions.length > 0);
  }, [sessions]);

  async function handleRename() {
    if (!renamingSession) return;
    const title = renameValue.trim();
    if (!title) {
      message.warning("标题不能为空");
      return;
    }
    setSaving(true);
    try {
      await agentApi.renameSession(renamingSession.id, title);
      message.success("已重命名");
      setRenamingSession(null);
      invalidateAgentSessions();
    } catch {
      message.error("重命名失败");
    } finally {
      setSaving(false);
    }
  }

  function handleDelete(session: AgentSession) {
    modal.confirm({
      title: "删除会话",
      content: `确认删除"${session.title?.trim() || "未命名会话"}"？该操作不可撤销。`,
      okText: "删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      async onOk() {
        try {
          await agentApi.deleteSession(session.id);
          message.success("已删除");
          invalidateAgentSessions();
          if (session.id === activeSessionId) {
            router.push("/agent");
          }
        } catch {
          message.error("删除失败");
        }
      },
    });
  }

  function buildMenu(session: AgentSession) {
    return {
      items: [
        {
          key: "rename",
          icon: <EditOutlined />,
          label: "重命名",
          onClick: () => {
            setRenamingSession(session);
            setRenameValue(session.title ?? "");
          },
        },
        {
          key: "pin",
          icon: <PushpinOutlined />,
          label: session.is_pinned ? "取消置顶" : "置顶",
          onClick: async () => {
            try {
              await agentApi.pinSession(session.id, !session.is_pinned);
              invalidateAgentSessions();
            } catch {
              message.error("操作失败");
            }
          },
        },
        { type: "divider" as const },
        {
          key: "delete",
          icon: <DeleteOutlined />,
          label: "删除",
          danger: true,
        },
      ],
      onClick: ({ key }: { key: string }) => {
        if (key === "delete") handleDelete(session);
      },
    };
  }

  if (sessions.length === 0) {
    return (
      <div className="sidebar-list">
        <div className="sidebar-empty">还没有会话，先开始一段新对话。</div>
      </div>
    );
  }

  return (
    <div className="sidebar-list">
      {grouped.map(({ group, sessions: groupSessions, isPin }) => (
        <div key={group}>
          <div className={`sidebar-group-label ${isPin ? "sidebar-group-label-pinned" : ""}`}>
            {isPin ? "📌 置顶" : group}
          </div>
          {groupSessions.map((session) => {
            const title = session.title?.trim() || "未命名会话";
            const active = session.id === activeSessionId;
            return (
              <div key={session.id} className="sidebar-session-row">
                <Link
                  href={`/agent/sessions/${session.id}`}
                  className={`session-item ${active ? "session-item-active" : ""}`}
                  onClick={onNavigate}
                  onMouseEnter={() => prefetch(session.id)}
                  onFocus={() => prefetch(session.id)}
                  title={title}
                  {...(active ? { "aria-current": "page" as const } : {})}
                >
                  <div className="session-title">
                    {session.is_pinned ? <PushpinOutlined style={{ fontSize: 11, marginRight: 4, color: "#D96313" }} /> : null}
                    {title}
                  </div>
                </Link>
                <Dropdown menu={buildMenu(session)} trigger={["click"]} placement="bottomRight">
                  <button
                    type="button"
                    className="session-item-more"
                    aria-label={`${title} 更多操作`}
                  >
                    <MoreOutlined />
                  </button>
                </Dropdown>
              </div>
            );
          })}
        </div>
      ))}
      {hasMore ? (
        <div ref={sentinelRef} className="sidebar-load-more">
          {loadingMore ? "加载中…" : ""}
        </div>
      ) : null}
      {!hasMore && sessionTotal && sessionTotal > 0 ? (
        <div className="sidebar-pagination-hint">
          共 {sessionTotal} 个会话
        </div>
      ) : null}

      <Modal
        title="重命名会话"
        open={renamingSession !== null}
        onOk={handleRename}
        onCancel={() => setRenamingSession(null)}
        okText="保存"
        cancelText="取消"
        confirmLoading={saving}
        destroyOnHidden
      >
        <Input
          value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
          onPressEnter={handleRename}
          placeholder="请输入会话名称"
          maxLength={200}
        />
      </Modal>
    </div>
  );
}
