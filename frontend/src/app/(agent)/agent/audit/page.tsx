"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Table, Input, Alert, Typography, Space, Button, Layout, Segmented, Pagination, Tabs } from "antd";
import { UserOutlined, ClockCircleOutlined, SearchOutlined, ReloadOutlined } from "@ant-design/icons";
import { agentApi } from "@/lib/agent-api";
import { isSuperAdmin } from "@/lib/roles";
import { fetchCurrentUser } from "@/lib/auth";
import PageHeader from "@/components/layout/page-header";
import DataSurface from "@/components/ui/data-surface";
import AuditSessionsTable from "@/components/dsh/audit-sessions-table";
import { PageLoading, PageError, EmptyState } from "@/components/ui/view-states";
import type { CurrentUser } from "@/types/auth";
import type { AgentSession } from "@/types/agent";

const { Sider, Content } = Layout;
const PAGE_SIZE = 50;

type GroupMode = "user" | "time";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function formatDateLabel(iso: string): string {
  return new Date(iso).toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric", weekday: "short" });
}

export default function AuditPage() {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [checking, setChecking] = useState(true);
  const [allSessions, setAllSessions] = useState<AgentSession[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [keyword, setKeyword] = useState("");
  const [groupMode, setGroupMode] = useState<GroupMode>("user");
  const [selectedUser, setSelectedUser] = useState<string | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"agent" | "dsh">("agent");

  useEffect(() => {
    fetchCurrentUser()
      .then((u) => { if (!u) { router.push("/login"); return; } setUser(u); })
      .catch(() => router.push("/login"))
      .finally(() => setChecking(false));
  }, [router]);

  async function loadData(p: number) {
    setLoading(true);
    setError(null);
    try {
      const result = await agentApi.listAuditSessions(p, PAGE_SIZE);
      setAllSessions(result.items);
      setTotal(result.total);
      setPage(p);
    } catch {
      setError("加载审计数据失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (user && isSuperAdmin(user)) { loadData(1); }
  }, [user]);

  const filtered = useMemo(() => {
    if (!keyword) return allSessions;
    const kw = keyword.toLowerCase();
    return allSessions.filter((s) =>
      (s.title ?? "").toLowerCase().includes(kw) ||
      (s.owner_display_name ?? "").toLowerCase().includes(kw)
    );
  }, [allSessions, keyword]);

  // Build user list
  const userList = useMemo(() => {
    const map = new Map<string, { name: string; count: number; sessions: AgentSession[] }>();
    for (const s of filtered) {
      const name = s.owner_display_name || s.owner_user_id.slice(0, 12);
      const entry = map.get(s.owner_user_id) || { name, count: 0, sessions: [] };
      entry.count++;
      entry.sessions.push(s);
      map.set(s.owner_user_id, entry);
    }
    const list = Array.from(map.entries()).map(([uid, data]) => ({
      userId: uid,
      name: data.name,
      count: data.count,
      sessions: data.sessions.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()),
      latest: data.sessions[0]?.created_at ?? "",
    }));
    list.sort((a, b) => b.count - a.count);
    return list;
  }, [filtered]);

  // Build time list
  const timeList = useMemo(() => {
    const map = new Map<string, { sessions: AgentSession[]; count: number }>();
    for (const s of filtered) {
      const key = new Date(s.created_at).toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric" });
      const entry = map.get(key) || { sessions: [], count: 0 };
      entry.count++;
      entry.sessions.push(s);
      map.set(key, entry);
    }
    return Array.from(map.entries()).map(([date, data]) => ({
      date,
      weekday: new Date(data.sessions[0].created_at).toLocaleDateString("zh-CN", { weekday: "short" }),
      count: data.count,
      sessions: data.sessions.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()),
    }));
  }, [filtered]);

  // Auto-select first item
  useEffect(() => {
    if (groupMode === "user" && userList.length > 0 && !selectedUser) {
      setSelectedUser(userList[0].userId);
    }
    if (groupMode === "time" && timeList.length > 0 && !selectedDate) {
      setSelectedDate(timeList[0].date);
    }
  }, [userList, timeList, groupMode]);

  // Selected user's sessions
  const selectedUserSessions = useMemo(() => {
    return userList.find((u) => u.userId === selectedUser)?.sessions ?? [];
  }, [userList, selectedUser]);

  // Selected date's sessions
  const selectedDateSessions = useMemo(() => {
    return timeList.find((d) => d.date === selectedDate)?.sessions ?? [];
  }, [timeList, selectedDate]);

  const columns = [
    {
      title: "会话",
      dataIndex: "title",
      key: "title",
      ellipsis: true,
      render: (title: string | null, record: AgentSession) => (
        <a className="audit-session-link" onClick={() => router.push(`/agent/audit/sessions/${record.id}`)}>
          {title || "未命名会话"}
        </a>
      ),
    },
    {
      title: groupMode === "time" ? "用户" : "时间",
      dataIndex: groupMode === "time" ? "owner_display_name" : "created_at",
      key: "meta",
      width: 150,
      render: (val: string) => {
        if (groupMode === "time") return <span style={{ fontSize: 12 }}>{val || "—"}</span>;
        return <span style={{ fontSize: 12, color: "#8b99ab" }}>{formatTime(val)}</span>;
      },
    },
  ];

  if (checking) return <PageLoading />;
  if (!user) return null;
  if (!isSuperAdmin(user)) {
    return (
      <div style={{ maxWidth: 720, margin: "0 auto", padding: 40 }}>
        <Alert type="error" title="无权限" description="仅超级管理员可访问治理中心。" showIcon />
      </div>
    );
  }

  return (
    <div>
      <div className="page-hero">
        <PageHeader
          title="治理中心"
          description="查看所有用户的对话记录 · 仅超级管理员可访问"
          actions={
            <Button icon={<ReloadOutlined />} onClick={() => loadData(page)} disabled={loading}>刷新</Button>
          }
        />
      </div>
      <div className="content">
        <Tabs
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key as "agent" | "dsh")}
          items={[
            {
              key: "agent",
              label: "Agent 会话",
              children: (
                <>
                  {error ? <PageError message={error} onRetry={() => loadData(page)} /> : null}
                  <Layout style={{ background: "transparent", gap: 16 }}>
          <Sider width={220} theme="light" style={{ background: "transparent", paddingRight: 8 }}>
            {groupMode === "user" ? (
              <div className="data-surface" style={{ padding: 0 }}>
                <div style={{ padding: "12px 16px", fontSize: 13, fontWeight: 600, color: "#526078", borderBottom: "1px solid #f0ebe0", display: "flex", alignItems: "center", gap: 6 }}>
                  <UserOutlined style={{ color: "#D96313" }} /> 所有用户
                </div>
                {userList.map((u) => (
                  <div
                    key={u.userId}
                    onClick={() => setSelectedUser(u.userId)}
                    style={{
                      padding: "9px 16px", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between",
                      fontSize: 13, borderBottom: "1px solid #f5f0eb",
                      background: selectedUser === u.userId ? "#fef0e5" : "transparent",
                      color: selectedUser === u.userId ? "#D96313" : "#172033",
                      fontWeight: selectedUser === u.userId ? 600 : 400,
                    }}
                  >
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{u.name}</span>
                    <span style={{
                      fontSize: 11, padding: "1px 6px", borderRadius: 8,
                      background: selectedUser === u.userId ? "#D96313" : "#f5f0eb",
                      color: selectedUser === u.userId ? "#fff" : "#526078",
                    }}>{u.count}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="data-surface" style={{ padding: 0 }}>
                <div style={{ padding: "12px 16px", fontSize: 13, fontWeight: 600, color: "#526078", borderBottom: "1px solid #f0ebe0", display: "flex", alignItems: "center", gap: 6 }}>
                  <ClockCircleOutlined style={{ color: "#D96313" }} /> 时间列表
                </div>
                {timeList.map((d) => (
                  <div
                    key={d.date}
                    onClick={() => setSelectedDate(d.date)}
                    style={{
                      padding: "9px 16px", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between",
                      fontSize: 13, borderBottom: "1px solid #f5f0eb",
                      background: selectedDate === d.date ? "#fef0e5" : "transparent",
                      color: selectedDate === d.date ? "#D96313" : "#172033",
                      fontWeight: selectedDate === d.date ? 600 : 400,
                    }}
                  >
                    <div style={{ lineHeight: 1.3 }}>
                      <div>{d.date}</div>
                      <div style={{ fontSize: 11, color: selectedDate === d.date ? "#D96313" : "#8b99ab", opacity: selectedDate === d.date ? 0.7 : 1 }}>{d.weekday}</div>
                    </div>
                    <span style={{
                      fontSize: 11, padding: "1px 6px", borderRadius: 8,
                      background: selectedDate === d.date ? "#D96313" : "#f5f0eb",
                      color: selectedDate === d.date ? "#fff" : "#526078",
                    }}>{d.count}</span>
                  </div>
                ))}
              </div>
            )}
          </Sider>
          <Content>
            <DataSurface>
              <div className="data-surface-toolbar">
                <Space wrap>
                  <Segmented
                    value={groupMode}
                    onChange={(v) => {
                      setGroupMode(v as GroupMode);
                      setSelectedUser(null);
                      setSelectedDate(null);
                    }}
                    options={[
                      { label: <><UserOutlined /> 按用户</>, value: "user" },
                      { label: <><ClockCircleOutlined /> 按时间</>, value: "time" },
                    ]}
                  />
                  <Input
                    placeholder="搜索会话内容…"
                    prefix={<SearchOutlined />}
                    value={keyword}
                    onChange={(e) => setKeyword(e.target.value)}
                    style={{ width: 220 }}
                    allowClear
                  />
                </Space>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  共 {total} 条记录
                  {groupMode === "user" && selectedUser ? ` · ${selectedUserSessions.length} 条当前` : ""}
                  {groupMode === "time" && selectedDate ? ` · ${selectedDate}` : ""}
                </Typography.Text>
              </div>

              {groupMode === "user" && selectedUser && selectedUserSessions.length > 0 ? (
                <>
                  <div style={{ margin: "0 18px", padding: "10px 0", display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #f0ebe0" }}>
                    <Space size={8}>
                      <span style={{ width: 32, height: 32, borderRadius: "50%", background: "#fef0e5", display: "inline-flex", alignItems: "center", justifyContent: "center", color: "#D96313", fontWeight: 700, fontSize: 14 }}>
                        {userList.find((u) => u.userId === selectedUser)?.name?.charAt(0) ?? "?"}
                      </span>
                      <Typography.Text strong style={{ fontSize: 14 }}>
                        {userList.find((u) => u.userId === selectedUser)?.name}
                      </Typography.Text>
                    </Space>
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                      {selectedUserSessions.length} 条会话 · 最近 {formatTime(selectedUserSessions[0].created_at)}
                    </Typography.Text>
                  </div>
                  <Table
                    rowKey="id"
                    dataSource={selectedUserSessions}
                    columns={columns}
                    loading={loading}
                    pagination={false}
                    size="small"
                  />
                </>
              ) : groupMode === "time" && selectedDate && selectedDateSessions.length > 0 ? (
                <>
                  <Table
                    rowKey="id"
                    dataSource={selectedDateSessions}
                    columns={columns}
                    loading={loading}
                    pagination={false}
                    size="small"
                  />
                </>
              ) : (
                <EmptyState message={keyword ? "未找到匹配的会话" : "暂无会话记录"} />
              )}

              {total > PAGE_SIZE ? (
                <div style={{ padding: "12px 18px", borderTop: "1px solid #f0ebe0", display: "flex", justifyContent: "center" }}>
                  <Pagination
                    current={page}
                    total={total}
                    pageSize={PAGE_SIZE}
                    onChange={(p) => { loadData(p); setSelectedUser(null); setSelectedDate(null); }}
                    showTotal={(t) => `共 ${t} 条`}
                    size="small"
                  />
                </div>
              ) : null}
            </DataSurface>
          </Content>
        </Layout>
                </>
              ),
            },
            ...(isSuperAdmin(user)
              ? [
                  {
                    key: "dsh",
                    label: "DSH 会话",
                    children: <AuditSessionsTable />,
                  },
                ]
              : []),
          ]}
        />
      </div>
    </div>
  );
}
