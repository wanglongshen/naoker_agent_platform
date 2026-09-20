"use client";

import { useMemo, useState } from "react";

import type { AgentRun, AgentRunStatus } from "@/types/agent";

type DiagnosticRun = AgentRun & {
  current_step?: number | null;
  max_steps?: number | null;
  retry_count?: number | null;
  next_retry_at?: string | null;
  error?: string | null;
};

type Props = {
  runs: DiagnosticRun[];
};

function summarizeRun(run: DiagnosticRun): string {
  if (run.error) {
    return `任务「${run.goal}」在第 ${run.current_step ?? "?"}/${run.max_steps ?? "?"} 步终止，错误为：${run.error}`;
  }

  switch (run.status) {
    case "succeeded":
      return `任务「${run.goal}」已完成，共执行 ${run.current_step ?? "?"}/${run.max_steps ?? "?"} 步。`;
    case "running":
      return `任务「${run.goal}」正在执行，当前进度为 ${run.current_step ?? "?"}/${run.max_steps ?? "?"} 步。`;
    case "retry_wait":
      return `任务「${run.goal}」正在等待重试，第 ${run.retry_count ?? "?"} 次重试计划于 ${run.next_retry_at ?? "稍后"} 继续。`;
    case "queued":
      return `任务「${run.goal}」已进入队列，等待开始执行。`;
    case "cancelled":
      return `任务「${run.goal}」已被取消。`;
    case "cancel_requested":
      return `任务「${run.goal}」正在取消中。`;
    case "failed":
    default:
      return `任务「${run.goal}」执行失败。`;
  }
}

export default function LandingEventStream({ runs }: Props) {
  const [open, setOpen] = useState(false);

  const items = useMemo(() => {
    return runs.slice(0, 8).map((run) => ({
      id: run.id,
      title: run.goal,
      status: run.status,
      createdAt: run.created_at,
      summary: summarizeRun(run),
    }));
  }, [runs]);

  return (
    <div className="landing-event-toggle-block">
      <div className="mode-pills">
        <span className="mode-pill mode-pill-active">研究模式</span>
        <span className="mode-pill">可见思考</span>
        <button type="button" className={`mode-pill mode-pill-button ${open ? "mode-pill-active" : ""}`} onClick={() => setOpen((value) => !value)}>
          事件流
        </button>
      </div>

      {open ? (
        <section className="landing-event-panel" aria-label="Agent Loop 事件流">
          <div className="landing-event-header">
            <div>
              <div className="section-eyebrow">系统记录</div>
              <h2>Agent Loop 事件流</h2>
            </div>
            <span className="section-hint">展示近期任务状态与关键执行摘要</span>
          </div>

          <div className="landing-event-list">
            {items.length === 0 ? (
              <div className="empty-card">当前还没有任务事件可展示。</div>
            ) : (
              items.map((item) => (
                <article key={item.id} className="landing-event-item">
                  <div className="landing-event-item-top">
                    <div className="landing-event-title">{item.title}</div>
                    <span className={`status-pill landing-status-pill status-${item.status}`}>{item.status}</span>
                  </div>
                  <div className="landing-event-time">{item.createdAt}</div>
                  <div className="landing-event-summary">{item.summary}</div>
                </article>
              ))
            )}
          </div>
        </section>
      ) : null}
    </div>
  );
}
