"use client";

import { useCallback, useEffect, useState } from "react";
import { Alert, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { api } from "@/lib/api";

const PAGE_SIZE = 20;

interface DshSessionAuditItem {
  dsh_session_id: string;
  title: string | null;
  turn_count: number;
  last_activity_at: string | null;
  synced_at: string | null;
  user_id: string;
  username?: string | null;
  display_name?: string | null;
}

interface DshSessionAuditPage {
  items: DshSessionAuditItem[];
  page: number;
  page_size: number;
  total: number;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

const columns: ColumnsType<DshSessionAuditItem> = [
  {
    title: "用户",
    dataIndex: "user_id",
    key: "user_id",
    width: 140,
    ellipsis: true,
    render: (_: string, row: DshSessionAuditItem) => (
      <span style={{ fontSize: 12 }}>
        {row.display_name || row.username || row.user_id.slice(0, 12)}
      </span>
    ),
  },
  {
    title: "标题",
    dataIndex: "title",
    key: "title",
    ellipsis: true,
    render: (value: string | null) => value || "未命名会话",
  },
  {
    title: "轮次",
    dataIndex: "turn_count",
    key: "turn_count",
    width: 80,
    align: "center",
    render: (value: number) => <span style={{ fontSize: 12 }}>{value}</span>,
  },
  {
    title: "最近活动",
    dataIndex: "last_activity_at",
    key: "last_activity_at",
    width: 140,
    render: (value: string | null) => (
      <span style={{ fontSize: 12, color: "#8b99ab" }}>{value ? formatTime(value) : "—"}</span>
    ),
  },
  {
    title: "同步时间",
    dataIndex: "synced_at",
    key: "synced_at",
    width: 140,
    render: (value: string | null) => (
      <span style={{ fontSize: 12, color: "#8b99ab" }}>{value ? formatTime(value) : "—"}</span>
    ),
  },
];

export default function AuditSessionsTable() {
  const [items, setItems] = useState<DshSessionAuditItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (p: number) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api<DshSessionAuditPage>(`/api/dsh/sessions/audit?page=${p}&page_size=${PAGE_SIZE}`);
      setItems(result.items);
      setTotal(result.total);
      setPage(result.page);
    } catch {
      setError("加载 DSH 会话审计数据失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void (async () => {
      await load(1);
    })();
  }, [load]);

  return (
    <div>
      {error ? (
        <Alert type="error" title={error} showIcon style={{ marginBottom: 12 }} />
      ) : null}
      <Table
        rowKey={(record) => `${record.user_id}-${record.dsh_session_id}`}
        dataSource={items}
        columns={columns}
        loading={loading}
        size="small"
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total,
          showSizeChanger: false,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p) => load(p),
        }}
      />
    </div>
  );
}
