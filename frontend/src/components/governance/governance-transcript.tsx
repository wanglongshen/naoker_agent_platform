"use client";

import React, { useState } from "react";
import FinalAnswerPanel from "@/components/agent/final-answer-panel";
import ThoughtNarrative from "@/components/agent/thought-narrative";
import { InlineAlert } from "@/components/ui/view-states";
import type { AuditSessionView } from "@/lib/audit-session-view";
import type { AgentConversationStep, AgentRunEvent } from "@/types/agent";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString("zh-CN");
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: "等待中",
    running: "思考中",
    retry_wait: "准备重试",
    succeeded: "已完成",
    failed: "未完成",
    cancelled: "已取消",
  };
  return labels[status] ?? status;
}

export default function GovernanceTranscript({ view }: { view: AuditSessionView }) {
  const [diagExpanded, setDiagExpanded] = useState(false);
  const diagId = `gov-diag-${view.session.id}`;

  const diagLabel = diagExpanded ? "收起运行诊断" : "展开运行诊断";

  return (
    <div className="governance-transcript">
      {view.warning ? (
        <div className="gov-transcript-warning">
          <InlineAlert type="warning" message={view.warning} />
        </div>
      ) : null}

      <div className="gov-transcript-owner">
        <span className="gov-owner-display-name">{view.owner.display_name}</span>
        <span className="gov-owner-username">{view.owner.username}</span>
        {view.owner.roles.map((role) => (
          <span key={role} className="gov-owner-role-tag">{role}</span>
        ))}
      </div>

      <div className="gov-transcript-session-info">
        <span className="gov-session-title">{view.session.title || "未命名会话"}</span>
        <span className="gov-session-time">{formatTime(view.session.created_at)}</span>
      </div>

      <div className="gov-transcript-body" role="region" aria-label="对话全文">
        {view.turns.length === 0 ? (
          <div className="empty-card">此会话暂无对话。</div>
        ) : (
          <div className="detail-conversation-stack">
            {view.turns.map((turn) => {
              const adaptedSteps: AgentConversationStep[] = turn.steps.map((s) => ({
                ...s,
              })) as unknown as AgentConversationStep[];

              const adaptedEvents: AgentRunEvent[] = turn.events;

              return (
                <section key={turn.run.id} className="session-turn-block">
                  <div className="message-row message-row-user">
                    <div className="message-bubble message-bubble-user">{turn.run.goal}</div>
                  </div>

                  <div className="session-turn-meta">
                    <span>{formatTime(turn.run.created_at)}</span>
                    <span className={`status-pill status-inline status-${turn.run.status}`}>
                      {statusLabel(turn.run.status)}
                    </span>
                  </div>

                  <ThoughtNarrative
                    run={turn.run}
                    steps={adaptedSteps.map((s) => ({
                      id: s.id,
                      step_number: s.step_number,
                      thought_summary: s.thought_summary,
                      action_type: s.action_type,
                      status: s.status,
                    }))}
                    events={adaptedEvents}
                  />
                  <FinalAnswerPanel
                    run={turn.run}
                    streamingAnswer=""
                    answerStreamId={null}
                  />
                </section>
              );
            })}
          </div>
        )}
      </div>

      <div className="gov-diag-section">
        <button
          type="button"
          className="gov-diag-toggle"
          aria-expanded={diagExpanded}
          aria-controls={diagId}
          onClick={() => setDiagExpanded((v) => !v)}
        >
          <span className="gov-diag-toggle-label">{diagLabel}</span>
          <span className="gov-diag-toggle-arrow">{diagExpanded ? "⌄" : "›"}</span>
        </button>

        {diagExpanded ? (
          <div id={diagId} className="gov-diag-body" role="region" aria-label="运行诊断">
            {view.turns.map((turn) => (
              <div key={turn.run.id} className="gov-diag-turn">
                <div className="gov-diag-turn-header">运行 {turn.run.id.slice(0, 8)}</div>

                <div className="gov-diag-grid">
                  <div className="gov-diag-item">
                    <span className="gov-diag-label">状态</span>
                    <span className="gov-diag-value">{statusLabel(turn.run.status)}</span>
                  </div>
                  <div className="gov-diag-item">
                    <span className="gov-diag-label">网络</span>
                    <span className="gov-diag-value">{turn.run.network_enabled ? "启用" : "禁用"}</span>
                  </div>
                  <div className="gov-diag-item">
                    <span className="gov-diag-label">步骤数</span>
                    <span className="gov-diag-value">{turn.steps.length}</span>
                  </div>
                  <div className="gov-diag-item">
                    <span className="gov-diag-label">事件数</span>
                    <span className="gov-diag-value">{turn.events.length}</span>
                  </div>
                  <div className="gov-diag-item">
                    <span className="gov-diag-label">创建时间</span>
                    <span className="gov-diag-value">{formatTime(turn.run.created_at)}</span>
                  </div>
                </div>

                {turn.steps.length > 0 ? (
                  <div className="gov-diag-subsection">
                    <div className="gov-diag-subtitle">步骤详情</div>
                    {turn.steps.map((step) => (
                      <div key={step.id} className="gov-diag-step">
                        <span>#{step.step_number}</span>
                        <span>{step.thought_summary || "-"}</span>
                        <span>{step.action_type || "-"}</span>
                        <span>{step.status}</span>
                      </div>
                    ))}
                  </div>
                ) : null}

                {turn.events.length > 0 ? (
                  <div className="gov-diag-subsection">
                    <div className="gov-diag-subtitle">事件记录 ({turn.events.length})</div>
                    {turn.events.map((ev) => (
                      <div key={ev.id} className="gov-diag-event">
                        <span className="gov-diag-event-seq">#{ev.seq}</span>
                        <span className="gov-diag-event-type">{ev.event_type}</span>
                        <span className="gov-diag-event-time">{formatTime(ev.created_at)}</span>
                      </div>
                    ))}
                  </div>
                ) : null}

                {turn.run.result?.final_answer ? (
                  <div className="gov-diag-item gov-diag-answer">
                    <span className="gov-diag-label">最终回答</span>
                    <span className="gov-diag-value">{turn.run.result.final_answer}</span>
                  </div>
                ) : null}
              </div>
            ))}

            <div className="gov-diag-meta">
              <div className="gov-diag-id-row">
                <span>会话 ID: <code className="gov-diag-code">{view.session.id}</code></span>
                <span>用户 ID: <code className="gov-diag-code">{view.session.owner_user_id}</code></span>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
