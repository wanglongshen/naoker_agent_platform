import { Spin, Alert as AntAlert, Button } from "antd";

export function PageLoading() {
  return (
    <div className="view-state page-loading">
      <Spin />
    </div>
  );
}

export function PageError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="view-state page-error">
      <AntAlert
        type="error"
        message="加载失败"
        description={message}
        showIcon
        action={
          onRetry ? (
            <Button size="small" onClick={onRetry}>
              重新加载
            </Button>
          ) : undefined
        }
      />
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="view-state empty-state">
      <p>{message}</p>
    </div>
  );
}

export function InlineAlert({ type, message }: { type: "error" | "warning" | "info"; message: string }) {
  const mapping = {
    error: "error" as const,
    warning: "warning" as const,
    info: "info" as const,
  };
  return <AntAlert type={mapping[type]} title={message} showIcon banner />;
}
