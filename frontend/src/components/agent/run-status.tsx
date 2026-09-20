import type { AgentRun, AgentRunStatus } from "@/types/agent";

type DiagnosticRun = AgentRun & {
  current_step?: number | null;
  max_steps?: number | null;
  retry_count?: number | null;
  next_retry_at?: string | null;
  last_step_duration_seconds?: number | null;
  error?: string | null;
};

function statusLabel(status: AgentRunStatus): string {
  switch (status) {
    case "queued":
      return "等待中";
    case "running":
      return "执行中";
    case "retry_wait":
      return "重试等待";
    case "succeeded":
      return "已完成";
    case "failed":
      return "失败";
    case "cancel_requested":
      return "取消中";
    case "cancelled":
      return "已取消";
    default:
      return status;
  }
}

export default function RunStatus({ run }: { run: DiagnosticRun }) {
  return (
    <section className="run-summary-card run-summary-card-secondary" aria-label="执行概览">
      <div className="run-summary-header">
        <div>
          <div className="run-summary-eyebrow">系统状态</div>
          <div className="run-summary-title">执行概览</div>
        </div>
        <span className={`status-pill status-pill-muted status-${run.status}`}>{statusLabel(run.status)}</span>
      </div>

      <div className="run-summary-grid run-summary-grid-compact">
        <div className="run-summary-item">
          <div className="summary-label">进度</div>
          <div className="summary-value">{run.current_step ?? "-"} / {run.max_steps ?? "-"}</div>
        </div>
        <div className="run-summary-item">
          <div className="summary-label">重试次数</div>
          <div className="summary-value">{run.retry_count ?? "-"}</div>
        </div>
        <div className="run-summary-item">
          <div className="summary-label">上一步耗时</div>
          <div className="summary-value">{run.last_step_duration_seconds ?? "-"}</div>
        </div>
        <div className="run-summary-item">
          <div className="summary-label">下次重试</div>
          <div className="summary-value">{run.next_retry_at ?? "-"}</div>
        </div>
      </div>

      {run.error ? (
        <div className="summary-inline-error">
          <span className="summary-inline-error-label">错误</span>
          <span className="summary-inline-error-text">{run.error}</span>
        </div>
      ) : null}
    </section>
  );
}
