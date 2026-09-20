"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Card, Tag, Typography, Spin, Alert, Button, Descriptions, Table, Breadcrumb } from "antd";
import { AuditOutlined } from "@ant-design/icons";
import { agentApi } from "@/lib/agent-api";
import { isSuperAdmin } from "@/lib/roles";
import { fetchCurrentUser } from "@/lib/auth";
import PageHeader from "@/components/ui/page-header";
import DataSurface from "@/components/ui/data-surface";
import { PageLoading, PageError, EmptyState } from "@/components/ui/view-states";
import type { CurrentUser } from "@/types/auth";
import type { AgentRun, AgentRunAttempt, AgentRunEvent } from "@/types/agent";

const { Title, Text } = Typography;

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: "等待中",
    running: "思考中",
    retry_wait: "准备重试",
    succeeded: "已完成",
    failed: "未完成",
    cancel_requested: "取消中",
    cancelled: "已取消",
    claimed: "已领取",
    retryable_failed: "可重试失败",
    lease_expired: "租约过期",
  };
  return labels[status] ?? status;
}

function statusColor(status: string): string {
  if (status === "succeeded") return "success";
  if (status === "running" || status === "queued" || status === "claimed") return "processing";
  if (status === "failed" || status === "cancelled") return "error";
  if (status === "retry_wait" || status === "retryable_failed") return "warning";
  return "default";
}

const EVENT_PAGE_SIZE = 50;

type QualityDimension = { name?: string; pass?: boolean; reason?: string };

function scoreColor(score: number | null): string {
  if (score === null) return "#8c8c8c";
  if (score >= 80) return "#52c41a";
  if (score >= 60) return "#fa8c16";
  return "#f5222d";
}

export default function AuditRunDetailPage() {
  const params = useParams();
  const router = useRouter();
  const runId = params?.runId as string;
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [checking, setChecking] = useState(true);
  const [run, setRun] = useState<AgentRun | null>(null);
  const [attempts, setAttempts] = useState<AgentRunAttempt[]>([]);
  const [events, setEvents] = useState<AgentRunEvent[]>([]);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCurrentUser()
      .then((u) => {
        if (!u) {
          router.push("/login");
          return;
        }
        setUser(u);
      })
      .catch(() => router.push("/login"))
      .finally(() => setChecking(false));
  }, [router]);

  useEffect(() => {
    if (!user || !isSuperAdmin(user) || !runId) return;
    setLoading(true);
    setError(null);
    Promise.all([
      agentApi.getAuditRun(runId),
      agentApi.getAuditRunAttempts(runId),
      agentApi.getAuditRunEvents(runId, null, EVENT_PAGE_SIZE),
    ])
      .then(([runData, attemptsResult, eventsResult]) => {
        setRun(runData);
        setAttempts(attemptsResult.items);
        setEvents(eventsResult.items);
        setNextCursor(eventsResult.next_seq);
      })
      .catch(() => setError("加载运行详情失败"))
      .finally(() => setLoading(false));
  }, [user, runId]);

  async function loadMoreEvents() {
    if (eventsLoading || nextCursor === null) return;
    setEventsLoading(true);
    try {
      const result = await agentApi.getAuditRunEvents(runId, nextCursor, EVENT_PAGE_SIZE);
      setEvents((prev) => [...prev, ...result.items]);
      setNextCursor(result.next_seq);
    } catch {
      // keep existing events
    } finally {
      setEventsLoading(false);
    }
  }

  if (checking) {
    return <PageLoading />;
  }

  if (!user) return null;

  if (!isSuperAdmin(user)) {
    return (
      <div style={{ maxWidth: 720, margin: "0 auto", padding: 40 }}>
        <Alert type="error" title="无权限" description="仅超级管理员可访问治理中心。" showIcon />
      </div>
    );
  }

  if (loading) {
    return <PageLoading />;
  }

  if (error || !run) {
    return <PageError message={error || "运行未找到"} />;
  }

  const qualityEvents = events.filter(
    (e) => e.event_type === "quality_review_completed"
  );
  const qualityEvent =
    qualityEvents.length > 0 ? qualityEvents[qualityEvents.length - 1] : null;
  const qualityPayload = qualityEvent?.payload ?? {};
  const qualityScore =
    typeof qualityPayload.score === "number" ? qualityPayload.score : null;
  const qualityRounds =
    typeof qualityPayload.rounds === "number" ? qualityPayload.rounds : 0;
  const qualityDims = Array.isArray(qualityPayload.dims)
    ? (qualityPayload.dims as QualityDimension[])
    : [];

  const eventColumns = [
    { title: "序号", dataIndex: "seq", key: "seq", width: 80 },
    { title: "事件类型", dataIndex: "event_type", key: "event_type", width: 200, ellipsis: true },
    {
      title: "载体",
      dataIndex: "payload",
      key: "payload",
      ellipsis: true,
      render: (payload: Record<string, unknown>) => (
        <Text code style={{ fontSize: 12, maxWidth: 400, display: "inline-block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {JSON.stringify(payload).slice(0, 120)}
        </Text>
      ),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 180,
      render: (val: string) => new Date(val).toLocaleString("zh-CN"),
    },
  ];

  return (
    <div className="gov-page">
      <PageHeader
        title="运行详情"
        description={run.goal}
        action={
          <Breadcrumb
            items={[
              { title: <Link href="/agent/audit">治理中心</Link> },
              { title: <Link href={`/agent/audit/sessions/${run.session_id}`}>会话详情</Link> },
              { title: "运行详情" },
            ]}
          />
        }
      />

      <DataSurface>
        <Card size="small" style={{ marginBottom: 24 }}>
          <Descriptions bordered size="small" column={1}>
            <Descriptions.Item label="运行 ID">{run.id}</Descriptions.Item>
            <Descriptions.Item label="目标">{run.goal}</Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={statusColor(run.status)}>{statusLabel(run.status)}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="网络">{run.network_enabled ? "已启用" : "已禁用"}</Descriptions.Item>
            <Descriptions.Item label="会话 ID">{run.session_id}</Descriptions.Item>
            <Descriptions.Item label="用户 ID">{run.owner_user_id}</Descriptions.Item>
            <Descriptions.Item label="创建时间">{new Date(run.created_at).toLocaleString("zh-CN")}</Descriptions.Item>
            <Descriptions.Item label="更新时间">{new Date(run.updated_at).toLocaleString("zh-CN")}</Descriptions.Item>
          </Descriptions>
        </Card>

        {qualityEvent ? (
          <div className="quality-review-section">
            <Title level={5}>质量审校</Title>
            <Card size="small" style={{ marginBottom: 24 }}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 20 }}>
                <div
                  style={{
                    width: 72,
                    height: 72,
                    borderRadius: "50%",
                    background: scoreColor(qualityScore),
                    color: "#fff",
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                  }}
                >
                  <Text strong style={{ color: "#fff", fontSize: 22, lineHeight: 1.2 }}>
                    {qualityScore === null ? "—" : qualityScore}
                  </Text>
                  <Text style={{ color: "rgba(255,255,255,0.9)", fontSize: 12 }}>
                    分
                  </Text>
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  {qualityRounds > 1 ? (
                    <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
                      共 {qualityRounds} 轮评审
                    </Text>
                  ) : null}
                  {qualityDims.length === 0 ? (
                    <Text type="secondary">暂无评审维度详情。</Text>
                  ) : (
                    qualityDims.map((dim, i) => (
                      <div
                        key={i}
                        style={{ display: "flex", gap: 8, marginBottom: 10, alignItems: "flex-start" }}
                      >
                        <Text
                          strong
                          style={{
                            color: dim.pass ? "#52c41a" : "#f5222d",
                            fontSize: 15,
                            lineHeight: 1.5,
                          }}
                        >
                          {dim.pass ? "✓" : "✗"}
                        </Text>
                        <div style={{ minWidth: 0 }}>
                          <Text strong>{dim.name || "维度"}</Text>
                          {dim.reason ? (
                            <div>
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                {dim.reason}
                              </Text>
                            </div>
                          ) : null}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </Card>
          </div>
        ) : null}

        <Title level={5}>Attempt 记录</Title>
        {attempts.length === 0 ? (
          <Card className="empty-card" style={{ marginBottom: 24 }}>暂无 attempt 记录。</Card>
        ) : (
          <Table
            rowKey="id"
            dataSource={attempts}
            pagination={false}
            size="small"
            style={{ marginBottom: 24 }}
            columns={[
              { title: "编号", dataIndex: "attempt_number", key: "attempt_number", width: 80 },
              { title: "状态", dataIndex: "status", key: "status", width: 140, render: (s: string) => <Tag color={statusColor(s)}>{statusLabel(s)}</Tag> },
              { title: "Worker ID", dataIndex: "worker_id", key: "worker_id", width: 300, ellipsis: true, render: (v: string | null) => v || "-" },
              { title: "开始时间", dataIndex: "started_at", key: "started_at", width: 180, render: (v: string | null) => v ? new Date(v).toLocaleString("zh-CN") : "-" },
              { title: "结束时间", dataIndex: "finished_at", key: "finished_at", width: 180, render: (v: string | null) => v ? new Date(v).toLocaleString("zh-CN") : "-" },
            ]}
          />
        )}

        <Title level={5}>事件记录</Title>
        <Table
          rowKey="id"
          dataSource={events}
          columns={eventColumns}
          size="small"
          pagination={false}
        />
        {nextCursor !== null ? (
          <div style={{ textAlign: "center", marginTop: 12 }}>
            <Button loading={eventsLoading} onClick={loadMoreEvents}>加载更多事件</Button>
          </div>
        ) : null}
      </DataSurface>
    </div>
  );
}
