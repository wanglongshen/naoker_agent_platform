"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Button, Alert } from "antd";
import { agentApi } from "@/lib/agent-api";
import { isSuperAdmin } from "@/lib/roles";
import { fetchCurrentUser } from "@/lib/auth";
import { loadAuditSessionView } from "@/lib/audit-session-view";
import GovernanceTranscript from "@/components/governance/governance-transcript";
import PageHeader from "@/components/ui/page-header";
import { PageLoading, PageError } from "@/components/ui/view-states";
import type { AuditSessionView } from "@/lib/audit-session-view";
import type { CurrentUser } from "@/types/auth";

export default function AuditSessionDetailPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params?.sessionId as string;
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [checking, setChecking] = useState(true);
  const [view, setView] = useState<AuditSessionView | null>(null);
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
    if (!user || !isSuperAdmin(user) || !sessionId) return;
    setLoading(true);
    setError(null);
    loadAuditSessionView(sessionId)
      .then((data) => {
        setView(data);
      })
      .catch(() => setError("加载会话转录失败"))
      .finally(() => setLoading(false));
  }, [user, sessionId]);

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

  if (error || !view) {
    return <PageError message={error || "会话未找到"} onRetry={sessionId ? () => loadAuditSessionView(sessionId).then(setView).catch(() => {}) : undefined} />;
  }

  return (
    <div className="gov-page">
      <PageHeader
        title="治理中心"
        description={view.owner.display_name ? `${view.owner.display_name} 的对话` : "会话详情"}
        action={
          <Button onClick={() => router.push("/agent/audit")}>
            返回对话列表
          </Button>
        }
      />

      <GovernanceTranscript view={view} />
    </div>
  );
}
