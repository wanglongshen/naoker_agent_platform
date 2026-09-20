"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { Alert, Spin, message } from "antd";
import ChatComposer from "@/components/agent/chat-composer";
import QuestionCard from "@/components/agent/question-card";
import SessionConversationStream from "@/components/agent/session-conversation-stream";
import { useSmartAutoScroll } from "@/hooks/use-smart-auto-scroll";
import { loadAgentSessionView, AgentSessionLoadError, mergeTurnsKeepingRicherAnswer, type AgentSessionTurn, type AgentLoadWarning } from "@/lib/agent-session-view";
import { readSessionView, writeSessionView, invalidateSessionView } from "@/lib/session-view-cache";
import { agentApi } from "@/lib/agent-api";
import { api, ApiError } from "@/lib/api";
import { invalidateAgentSessions } from "@/lib/agent-session-store";
import type { AgentSession, AgentRun } from "@/types/agent";
import type { FolderNode } from "@/types/file";

type SessionProjectFields = { project_folder_id?: string | null; project_name?: string | null };

function toSessionPageError(error: unknown): string {
  if (error instanceof AgentSessionLoadError) return error.message;
  return "服务暂时不可用";
}

function showInsufficientPoints(error: unknown): boolean {
  return error instanceof ApiError && error.code === "INSUFFICIENT_POINTS";
}

function toWarningText(w: AgentLoadWarning): string {
  return w.runId ? `执行 ${w.runId}：${w.message}` : w.message;
}

export default function SessionDetailPage() {
  const params = useParams();
  const sessionId = params?.sessionId as string;
  const [session, setSession] = useState<AgentSession | null>(null);
  const [turns, setTurns] = useState<AgentSessionTurn[]>([]);
  const [warnings, setWarnings] = useState<AgentLoadWarning[]>([]);
  const [reconciliationWarning, setReconciliationWarning] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [projectOptions, setProjectOptions] = useState<{ value: string; label: string }[]>([]);
  const [projectFolderId, setProjectFolderId] = useState<string | null>(null);
  const [projectName, setProjectName] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const { reset: resetScroll } = useSmartAutoScroll(scrollRef, [turns]);

  const loadSession = useCallback(async () => {
    if (!sessionId) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);

    const cached = readSessionView(sessionId);
    if (cached) {
      setSession(cached.session);
      setTurns(cached.turns);
      setWarnings(cached.warnings);
    }

    try {
      const view = await loadAgentSessionView(sessionId, controller.signal);
      if (controller.signal.aborted) return;
      writeSessionView(view);
      setSession(view.session);
      setTurns(view.turns);
      setWarnings(view.warnings);
    } catch (error) {
      if (!controller.signal.aborted) setError(toSessionPageError(error));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [sessionId]);

  const reconcileSession = useCallback(async () => {
    if (!sessionId) return;
    try {
      const view = await loadAgentSessionView(sessionId);
      setSession(view.session);
      setTurns((current) => mergeTurnsKeepingRicherAnswer(current, view.turns));
      setWarnings(view.warnings);
      setReconciliationWarning(null);
    } catch {
      setReconciliationWarning("执行状态刷新失败，当前回答已保留。");
    }
  }, [sessionId]);

  const handleTerminalState = useCallback(() => {
    void reconcileSession();
  }, [reconcileSession]);

  useEffect(() => {
    loadSession();
  }, [loadSession]);

  useEffect(() => {
    if (!session) return;
    const project = session as AgentSession & SessionProjectFields;
    setProjectFolderId(project.project_folder_id ?? null);
    setProjectName(project.project_name ?? "");
  }, [session]);

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

  async function handleProjectChange(value: string | null) {
    try {
      const res = await agentApi.updateSessionProject(sessionId, value);
      setSession((prev) =>
        prev
          ? { ...prev, project_folder_id: res.project_folder_id, project_name: res.project_name }
          : prev
      );
      if (res.project_folder_id) {
        message.success(`已切换到项目「${res.project_name}」，文件操作仅限该项目`);
      } else {
        message.info("已解除项目绑定，文件操作为全局范围");
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : "切换项目失败");
    }
  }

  async function handleContinue(input: { goal: string; attachmentIds: string[] }) {
    if (!sessionId) return;
    try {
      resetScroll();
      invalidateSessionView(sessionId);
      await agentApi.createRun(sessionId, {
        goal: input.goal,
        network_enabled: true,
        attachment_ids: input.attachmentIds,
      });
      invalidateAgentSessions();
      await loadSession();
    } catch (err) {
      if (showInsufficientPoints(err)) {
        message.error("积点余额不足，请前往「账户」充值或输入兑换码");
      } else {
        setError("发送消息失败");
      }
    }
  }

  async function handleRegenerate(run: AgentRun) {
    try {
      invalidateSessionView(sessionId);
      await agentApi.createRun(sessionId, {
        goal: run.goal,
        network_enabled: true,
        attachment_ids: [],
      });
      invalidateAgentSessions();
      await loadSession();
    } catch (err) {
      if (showInsufficientPoints(err)) {
        message.error("积点余额不足，请前往「账户」充值或输入兑换码");
      } else {
        setError("发送消息失败");
      }
    }
  }

  async function handleQuestionsSubmitted() {
    invalidateSessionView(sessionId);
    await loadSession();
  }

  const awaitingRuns = turns
    .filter((turn) => turn.run.status === "awaiting_question")
    .map((turn) => turn.run);

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 80 }}>
        <Spin />
      </div>
    );
  }

  if (error || !session) {
    return (
      <div style={{ maxWidth: 720, margin: "0 auto", padding: 40 }}>
        <Alert type="error" title={error || "会话未找到"} showIcon />
      </div>
    );
  }

  return (
    <div className="detail-single-column-page">
      <div className="detail-single-column-scroll" ref={scrollRef}>
        <div className="detail-single-column-main">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <div className="session-detail-title">{session.title?.trim() || "未命名会话"}</div>
          </div>

          {warnings.length > 0 ? (
            <Alert
              type="warning"
              showIcon
              title="部分历史执行记录暂时无法加载，已保留可用对话内容。"
              description={warnings.map(toWarningText).join("；")}
            />
          ) : null}

          {reconciliationWarning ? (
            <Alert type="warning" showIcon title={reconciliationWarning} />
          ) : null}

          <SessionConversationStream turns={turns} onTerminalState={handleTerminalState} onRegenerate={handleRegenerate} />

          {awaitingRuns.map((run) => (
            <QuestionCard key={run.id} run={run} onSubmitted={handleQuestionsSubmitted} />
          ))}

          <div className="detail-composer-wrap">
            <ChatComposer
              sessionId={sessionId}
              placeholder="继续这个会话"
              onSubmit={handleContinue}
              onFileCardsChange={resetScroll}
              projectOptions={projectOptions}
              projectFolderId={projectFolderId}
              onProjectChange={(v) => void handleProjectChange(v)}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
