import type { AgentRun, AgentRunStatus } from "@/types/agent";

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

export default function RunHeader({ run }: { run: AgentRun }) {
  return (
    <header className="conversation-header">
      <div className="conversation-header-main">
        <div className="conversation-title">{run.goal}</div>
        <div className="conversation-subtitle">
          <span className="conversation-mode-indicator" aria-hidden="true">&sect;</span>
          <span className={`status-pill status-inline status-${run.status}`}>{statusLabel(run.status)}</span>
        </div>
      </div>
      <div className="conversation-action" aria-hidden="true">
        &#8599;
      </div>
    </header>
  );
}
