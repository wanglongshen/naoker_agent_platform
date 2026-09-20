"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Alert } from "antd";
import ChatComposer from "@/components/agent/chat-composer";
import { agentApi } from "@/lib/agent-api";
import { invalidateAgentSessions } from "@/lib/agent-session-store";
import { PRODUCT_NAME } from "@/lib/copy";
import { api } from "@/lib/api";
import type { FolderNode } from "@/types/file";

export default function AgentPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [projectOptions, setProjectOptions] = useState<{ value: string; label: string }[]>([]);
  const [projectFolderId, setProjectFolderId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<FolderNode[]>("/api/files/folders")
      .then((nodes) => {
        if (cancelled) return;
        setProjectOptions(
          (nodes ?? [])
            .filter((n) => n.parent_folder_id == null)
            .map((n) => ({ value: n.id, label: n.name }))
        );
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSubmit(input: { goal: string; attachmentIds: string[] }) {
    try {
      const session = await agentApi.createSession(input.goal.slice(0, 80), projectFolderId);
      await agentApi.createRun(session.id, {
        goal: input.goal,
        network_enabled: true,
        attachment_ids: input.attachmentIds,
      });
      invalidateAgentSessions();
      router.push(`/agent/sessions/${session.id}`);
    } catch {
      setError("创建会话失败");
    }
  }

  return (
    <section className="right-workspace-landing" aria-labelledby="landing-heading">
      <div className="right-workspace-welcome">
        <h1>{PRODUCT_NAME}</h1>
        <h2 id="landing-heading">今天有什么想一起完成？</h2>
        <p>在{PRODUCT_NAME}中提问、写作、分析与协作</p>
      </div>
      <ChatComposer
        placeholder="问问题、分析材料或开始创作…"
        submitLabel="发送消息"
        onSubmit={handleSubmit}
        autoFocus
        projectOptions={projectOptions}
        projectFolderId={projectFolderId}
        onProjectChange={setProjectFolderId}
      />
      {error ? (
        <Alert type="error" title={error} showIcon closable onClose={() => setError(null)} />
      ) : null}
    </section>
  );
}
